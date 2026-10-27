"""One assignment per teaching class, independent completion per student."""
import re
import uuid
from datetime import date
from . import community, course_store


def schema(c):
    c.execute('''CREATE TABLE IF NOT EXISTS teaching_homework(
        id TEXT PRIMARY KEY, offering TEXT NOT NULL REFERENCES teaching_offerings(key),
        title TEXT NOT NULL CHECK(length(trim(title)) BETWEEN 1 AND 120),
        notes TEXT NOT NULL CHECK(length(notes)<=10000), due_date TEXT NOT NULL, due_time TEXT NOT NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT NOT NULL DEFAULT '',
        revision TEXT NOT NULL, created_by INTEGER NOT NULL REFERENCES members(id),
        updated_by INTEGER NOT NULL REFERENCES members(id))''')
    if 'submission' not in {r[1] for r in c.execute('PRAGMA table_info(teaching_homework)')}:
        c.execute("ALTER TABLE teaching_homework ADD COLUMN submission TEXT NOT NULL DEFAULT '' CHECK(length(submission)<=2000)")
    c.execute('CREATE INDEX IF NOT EXISTS teaching_homework_course ON teaching_homework(offering,deleted_at,due_date)')
    c.execute('''CREATE TABLE IF NOT EXISTS teaching_homework_status(
        member INTEGER NOT NULL REFERENCES members(id), homework TEXT NOT NULL REFERENCES teaching_homework(id),
        completed_at TEXT NOT NULL, revision TEXT NOT NULL, PRIMARY KEY(member,homework))''')


def enrolled(c, member, key):
    return bool(c.execute('SELECT 1 FROM teaching_enrollments WHERE member=? AND offering=? AND active=1', (member,key)).fetchone())


def can_edit(c, member, key):
    role=community.roles(c,member)
    return role['admin'] or (key in role['representativeOf'] and enrolled(c,member,key))


def offering(c, key):
    row=c.execute('SELECT * FROM teaching_offerings WHERE key=? AND published=1',(key,)).fetchone()
    if not row:raise PermissionError('这门课程尚未开放或不可访问')
    return row


def serialization_context(c, member, rows):
    # Reuse identity and permissions within this request's existing read transaction.
    role=community.roles(c,member)
    offerings={r['key']:r for r in c.execute('SELECT * FROM teaching_offerings WHERE published=1 ORDER BY term DESC,name')}
    active={r['offering'] for r in c.execute('SELECT offering FROM teaching_enrollments WHERE member=? AND active=1',(member,))}
    statuses={r['homework']:r for r in c.execute('SELECT * FROM teaching_homework_status WHERE member=?',(member,))} if rows else {}
    authors=sorted({r[k] for r in rows for k in ('created_by','updated_by')})
    names={}
    for offset in range(0,len(authors),400):
        batch=authors[offset:offset+400]
        names.update({r['id']:r['name'] for r in c.execute('SELECT id,name FROM members WHERE id IN ('+','.join('?' for _ in batch)+')',batch)})
    return {'role':role,'offerings':offerings,'active':active,'statuses':statuses,'names':names}


def serial(c, row, member, context=None):
    if context is None:
        meta=offering(c,row['offering'])
        status=c.execute('SELECT * FROM teaching_homework_status WHERE member=? AND homework=?',(member,row['id'])).fetchone()
        names={r['id']:r['name'] for r in c.execute('SELECT id,name FROM members WHERE id IN (?,?)',(row['created_by'],row['updated_by']))}
        editable=bool(can_edit(c,member,row['offering']))
        active=enrolled(c,member,row['offering'])
    else:
        meta=context['offerings'].get(row['offering'])
        if meta is None:raise PermissionError('这门课程尚未开放或不可访问')
        status=context['statuses'].get(row['id']);names=context['names']
        active=row['offering'] in context['active']
        editable=context['role']['admin'] or (row['offering'] in context['role']['representativeOf'] and active)
    return {'id':row['id'],'title':row['title'],'courseId':meta['id'],'notes':row['notes'],'submission':row['submission'],
            'dueDate':row['due_date'],'dueTime':row['due_time'],'createdAt':row['created_at'],
            'updatedAt':row['updated_at'],'deletedAt':row['deleted_at'],'revision':row['revision'],
            'completedAt':status['completed_at'] if status else '',
            'completionRevision':status['revision'] if status else None,'scope':'course',
            'offeringKey':row['offering'],'courseName':meta['name'],'teacher':meta['teacher'] or '',
            'term':meta['term'],'author':names.get(row['created_by'],'课代表'),
            'updatedBy':names.get(row['updated_by'],'课代表'),
            'canEdit':bool(editable),'canComplete':active}


def publishers(c, member, context=None):
    role=context['role'] if context is not None else community.roles(c,member)
    result=[]
    rows=context['offerings'].values() if context is not None else c.execute('SELECT * FROM teaching_offerings WHERE published=1 ORDER BY term DESC,name')
    for row in rows:
        active=row['key'] in context['active'] if context is not None else enrolled(c,member,row['key'])
        if role['admin'] or (row['key'] in role['representativeOf'] and active):
            result.append({'key':row['key'],'courseId':row['id'],'name':row['name'],'teacher':row['teacher'] or '',
                           'term':row['term'],'enrolled':active})
    return result


def feed(c, member):
    if not c.in_transaction:
        with course_store.transaction(c):return feed(c,member)
    shared=c.execute('''SELECT h.* FROM teaching_homework h
        JOIN teaching_enrollments e ON e.offering=h.offering AND e.member=? AND e.active=1
        JOIN teaching_offerings o ON o.key=h.offering AND o.published=1
        WHERE h.deleted_at='' ORDER BY h.created_at,h.id''',(member,)).fetchall()
    context=serialization_context(c,member,shared)
    return {'owner':member,'items':course_store.read_tasks(c,member)+[serial(c,r,member,context) for r in shared],
            'publishCourses':publishers(c,member,context)}


def for_course(c, member, key):
    with course_store.transaction(c):
        meta=offering(c,key)
        if not enrolled(c,member,key) and not can_edit(c,member,key):raise PermissionError('你没有加入这门课程')
        rows=c.execute("SELECT * FROM teaching_homework WHERE offering=? AND deleted_at='' ORDER BY due_date,created_at",(key,)).fetchall()
        context=serialization_context(c,member,rows)
        return {'owner':member,'course':{'key':key,'name':meta['name'],'courseId':meta['id'],
                'teacher':meta['teacher'] or '', 'term':meta['term']},'canEdit':bool(can_edit(c,member,key)),
                'items':[serial(c,r,member,context) for r in rows]}


def validate(task):
    fields={'title','notes','dueDate','dueTime'}
    if not isinstance(task,dict) or not fields<=set(task) or set(task)-fields-{'submission'} or any(not isinstance(v,str) for v in task.values()):
        raise ValueError('作业内容格式无效')
    t={**task,'title':task['title'].strip(),'notes':task['notes'].strip()}
    if not 1<=len(t['title'])<=120 or len(t['notes'])>10000:raise ValueError('作业名称或内容无效')
    if 'submission' in t:
        t['submission']=t['submission'].strip()
        if len(t['submission'])>2000:raise ValueError('提交方式不能超过2000字')
    if t['dueDate']:
        try:
            if date.fromisoformat(t['dueDate']).isoformat()!=t['dueDate']:raise ValueError()
        except ValueError:raise ValueError('截止日期无效')
    if t['dueTime'] and (not t['dueDate'] or not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d',t['dueTime'])):
        raise ValueError('截止时间无效')
    return t


def change(c, member, b):
    with course_store.transaction(c,write=True):
        action=b.get('action');ident=b.get('id')
        if not isinstance(ident,str) or not re.fullmatch(r'coursework-[a-zA-Z0-9-]{1,70}',ident):raise ValueError('作业编号无效')
        row=c.execute('SELECT * FROM teaching_homework WHERE id=?',(ident,)).fetchone()
        if action=='complete':
            if not row:raise PermissionError('这项作业不可访问')
            offering(c,row['offering'])
            if not enrolled(c,member,row['offering']):raise PermissionError('你没有加入这门课程')
            if row['deleted_at']:raise ValueError('作业已更新或撤回，请刷新后再操作')
            if type(b.get('completed')) is not bool:raise ValueError('完成状态无效')
            status=c.execute('SELECT * FROM teaching_homework_status WHERE member=? AND homework=?',(member,ident)).fetchone()
            if (status['revision'] if status else None)!=b.get('expected'):raise ValueError('完成状态已更新，请刷新后再修改')
            before=serial(c,row,member)
            c.execute('''INSERT INTO teaching_homework_status VALUES(?,?,?,?)
                ON CONFLICT(member,homework) DO UPDATE SET completed_at=excluded.completed_at,revision=excluded.revision''',
                (member,ident,community.now() if b['completed'] else '',str(uuid.uuid4())))
        elif action in ('save','delete','restore'):
            key=b.get('key')
            if not isinstance(key,str):raise ValueError('请选择课程')
            offering(c,key)
            if not can_edit(c,member,key):raise PermissionError('仅这门课的课代表或管理员可以发布和修改')
            if row and row['offering']!=key:raise PermissionError('不能将作业移到另一个教学班')
            if (row['revision'] if row else None)!=b.get('expected'):raise ValueError('作业已更新，请刷新后再修改')
            before=serial(c,row,member) if row else None
            timestamp=community.now();revision=str(uuid.uuid4())
            if action=='save':
                t=validate(b.get('task'))
                # Older clients may omit the new field; omission never clears it.
                t.setdefault('submission',row['submission'] if row else '')
                if row and row['deleted_at']:raise ValueError('作业已更新或撤回，请刷新后再操作')
                if not row and c.execute('SELECT count(*) FROM teaching_homework WHERE offering=?',(key,)).fetchone()[0]>=2000:
                    raise ValueError('这门课的作业数量已达上限')
                c.execute('''INSERT INTO teaching_homework(id,offering,title,notes,due_date,due_time,created_at,updated_at,deleted_at,revision,created_by,updated_by,submission) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET title=excluded.title,notes=excluded.notes,due_date=excluded.due_date,
                    due_time=excluded.due_time,updated_at=excluded.updated_at,revision=excluded.revision,updated_by=excluded.updated_by,submission=excluded.submission''',
                    (ident,key,t['title'],t['notes'],t['dueDate'],t['dueTime'],timestamp,timestamp,'',revision,member,member,t['submission']))
            else:
                if not row:raise ValueError('作业不存在')
                c.execute('UPDATE teaching_homework SET deleted_at=?,updated_at=?,revision=?,updated_by=? WHERE id=?',
                          (timestamp if action=='delete' else '',timestamp,revision,member,ident))
            community.audit(c,member,'homework-'+('publish' if action=='save' and not row else action),key,{'id':ident})
        else:raise ValueError('作业操作无效')
        next_task=serial(c,c.execute('SELECT * FROM teaching_homework WHERE id=?',(ident,)).fetchone(),member)
        return {**feed(c,member),'before':before,'next':next_task}
