"""Teaching-class identities, scoped representatives and reviewable preloading.

Personal imports only link enrollments. They never rewrite a shared template.
"""
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from . import course_store, importer, merge


def now():
    return datetime.now(timezone.utc).isoformat()


def schema(c):
    columns = ','.join('"'+k+'" '+v for k, v in course_store.COURSE_FIELDS.items())
    c.execute(f'''CREATE TABLE IF NOT EXISTS teaching_offerings(
        key TEXT PRIMARY KEY, school TEXT NOT NULL, term TEXT NOT NULL, term_key TEXT NOT NULL,
        week_start TEXT NOT NULL, range_start TEXT NOT NULL, range_end TEXT NOT NULL,
        published INTEGER NOT NULL DEFAULT 0, revision TEXT NOT NULL, fields TEXT NOT NULL,
        updated_at TEXT NOT NULL, updated_by INTEGER REFERENCES members(id), {columns},
        UNIQUE(school,term_key,id))''')
    columns = ','.join('"'+k+'" '+v for k, v in course_store.EVENT_FIELDS.items())
    c.execute(f'''CREATE TABLE IF NOT EXISTS teaching_meetings(
        offering TEXT NOT NULL REFERENCES teaching_offerings(key), position INTEGER NOT NULL,
        fields TEXT NOT NULL, {columns}, PRIMARY KEY(offering,id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS teaching_recurrences(
        offering TEXT PRIMARY KEY REFERENCES teaching_offerings(key), weekday INTEGER NOT NULL,
        starts_on TEXT NOT NULL, until_date TEXT, start_time TEXT, end_time TEXT, source TEXT NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS teaching_exclusions(
        offering TEXT NOT NULL REFERENCES teaching_recurrences(offering), date TEXT NOT NULL,
        PRIMARY KEY(offering,date))''')
    c.execute('''CREATE TABLE IF NOT EXISTS teaching_enrollments(
        member INTEGER NOT NULL REFERENCES members(id), offering TEXT NOT NULL REFERENCES teaching_offerings(key),
        personal_course TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, source TEXT NOT NULL,
        linked_at TEXT NOT NULL, PRIMARY KEY(member,offering))''')
    c.execute('CREATE TABLE IF NOT EXISTS class_admins(member INTEGER PRIMARY KEY REFERENCES members(id))')
    c.execute('''CREATE TABLE IF NOT EXISTS teaching_representatives(
        offering TEXT NOT NULL REFERENCES teaching_offerings(key), member INTEGER NOT NULL REFERENCES members(id),
        PRIMARY KEY(offering,member))''')
    c.execute('''CREATE TABLE IF NOT EXISTS class_audit(
        id TEXT PRIMARY KEY, actor INTEGER REFERENCES members(id), action TEXT NOT NULL,
        target TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL)''')


def audit(c, actor, action, target, detail):
    c.execute('INSERT INTO class_audit VALUES(?,?,?,?,?,?)',
              (str(uuid.uuid4()), actor, action, str(target), json.dumps(detail, ensure_ascii=False), now()))


def roles(c, member):
    return {'admin': bool(c.execute('SELECT 1 FROM class_admins WHERE member=?', (member,)).fetchone()),
            'representativeOf': [r[0] for r in c.execute('SELECT offering FROM teaching_representatives WHERE member=?', (member,))]}


def require_admin(c, member):
    if not roles(c, member)['admin']:
        raise PermissionError('仅管理员可以执行这项管理操作')


def identity(data, cid):
    if cid.startswith('import-'):
        return None
    return hashlib.sha256(('zju\0'+merge.term_key(data['term'])+'\0'+cid).encode()).hexdigest()[:32]


def template(c, key, member):
    row = c.execute('SELECT * FROM teaching_offerings WHERE key=?', (key,)).fetchone()
    if not row:
        raise ValueError('共同课程不存在')
    course = {k: row[k] for k in row['fields'].split(',')}
    rule = c.execute('SELECT * FROM teaching_recurrences WHERE offering=?', (key,)).fetchone()
    if rule:
        course['recurrence'] = {'weekday': rule['weekday'], 'starts_on': rule['starts_on'], 'until': rule['until_date'],
                                'start_time': rule['start_time'], 'end_time': rule['end_time'], 'source': rule['source'],
                                'excluded_dates': [r[0] for r in c.execute('SELECT date FROM teaching_exclusions WHERE offering=? ORDER BY date', (key,))]}
    return {'owner': member, 'team': 1, 'term': row['term'], 'week_start': row['week_start'],
            'display_range': {'start': row['range_start'], 'end': row['range_end']}, 'version': 'shared-template-v1',
            'courses': [course], 'events': [{k: r[k] for k in r['fields'].split(',')}
                                            for r in c.execute('SELECT * FROM teaching_meetings WHERE offering=? ORDER BY position', (key,))]}


def write_template(c, actor, data, course, published=False):
    key = identity(data, course['id'])
    if key is None:
        raise ValueError('请先补全教学班编号，再建立共同课程')
    old = c.execute('SELECT * FROM teaching_offerings WHERE key=?', (key,)).fetchone()
    if old and not published:
        return key
    fields = [k for k in course if k != 'recurrence']
    metadata = ['key','school','term','term_key','week_start','range_start','range_end','published','revision','fields','updated_at','updated_by']
    values = [key,'zju',data['term'],merge.term_key(data['term']),data['week_start'],data['display_range']['start'],data['display_range']['end'],int(published),str(uuid.uuid4()),','.join(fields),now(),actor]
    columns = metadata+fields
    names = ','.join('"'+k+'"' for k in columns)
    updates = ','.join('"'+k+'"=excluded."'+k+'"' for k in columns if k != 'key')
    c.execute(f'INSERT INTO teaching_offerings({names}) VALUES({",".join("?" for _ in columns)}) ON CONFLICT(key) DO UPDATE SET {updates}', (*values,*(course[k] for k in fields)))
    c.execute('DELETE FROM teaching_meetings WHERE offering=?', (key,))
    c.execute('DELETE FROM teaching_exclusions WHERE offering=?', (key,))
    c.execute('DELETE FROM teaching_recurrences WHERE offering=?', (key,))
    for position, e in enumerate(x for x in data['events'] if x['course_id'] == course['id']):
        keys = list(e)
        names = ','.join('"'+k+'"' for k in keys)
        c.execute(f'INSERT INTO teaching_meetings(offering,position,fields,{names}) VALUES({",".join("?" for _ in range(3+len(keys)))})', (key,position,','.join(keys),*(e[k] for k in keys)))
    if course.get('recurrence'):
        r = course['recurrence']
        c.execute('INSERT INTO teaching_recurrences VALUES(?,?,?,?,?,?,?)', (key,r['weekday'],r['starts_on'],r['until'],r['start_time'],r['end_time'],r['source']))
        c.executemany('INSERT INTO teaching_exclusions VALUES(?,?)', [(key,d) for d in r['excluded_dates']])
    return key


def sync(c, member, data, source):
    c.execute('UPDATE teaching_enrollments SET active=0 WHERE member=?', (member,))
    for course in data['courses']:
        if identity(data, course['id']) is None:
            continue
        key = write_template(c, member, data, course)
        c.execute('''INSERT INTO teaching_enrollments VALUES(?,?,?,1,?,?)
                     ON CONFLICT(member,offering) DO UPDATE SET personal_course=excluded.personal_course,active=1''',
                  (member,key,course['id'],source,now()))


def migrate_existing(c):
    with course_store.transaction(c, write=True):
        if c.execute("SELECT 1 FROM course_migrations WHERE id='community-links-v1'").fetchone():
            return
        for row in c.execute("SELECT member FROM course_schedules WHERE slot='current'").fetchall():
            sync(c, row['member'], course_store.read_schedule(c, row['member']), 'existing')
        c.execute('INSERT INTO course_migrations VALUES(?,?,?)', ('community-links-v1','schema-v1',now()))


def cards(c, member, management=False):
    result=[]
    for row in c.execute('SELECT * FROM teaching_offerings ORDER BY term DESC,name'):
        if not row['published'] and not management:
            continue
        shared=template(c,row['key'],member)
        sessions=[{k:e.get(k) for k in ('date','start_time','end_time','kind','location','note')}
                  for e in shared['events']]
        reps=[dict(r) for r in c.execute('SELECT m.id,m.name FROM members m JOIN teaching_representatives r ON r.member=m.id JOIN teaching_enrollments e ON e.member=r.member AND e.offering=r.offering AND e.active=1 WHERE r.offering=? AND m.disabled=0 ORDER BY m.name',(row['key'],))]
        result.append({'key':row['key'],'courseId':row['id'],'term':row['term'],'name':row['name'],'teacher':row['teacher'] or '',
                       'location':row['location'] or '', 'revision':row['revision'],'published':bool(row['published']),
                       'subscribed':bool(c.execute('SELECT 1 FROM teaching_enrollments WHERE member=? AND offering=? AND active=1',(member,row['key'])).fetchone()),
                       'representatives':reps,'meetings':len(sessions),'sessions':sessions,
                       'recurrence':shared['courses'][0].get('recurrence')})
    return result


def library(c, member):
    with course_store.transaction(c):
        return {'courses':cards(c,member),'base':importer.fingerprint(course_store.read_schedule(c,member))}


def change_subscription(c, member, b):
    with course_store.transaction(c,write=True):
        current=course_store.read_schedule(c,member)
        if b.get('base')!=importer.fingerprint(current):
            raise ValueError('课表已变化，请重新预览')
        key=b.get('key')
        if not isinstance(key,str):raise ValueError('请选择共同课程')
        row=c.execute('SELECT * FROM teaching_offerings WHERE key=? AND published=1',(key,)).fetchone()
        if not row or row['revision']!=b.get('revision'):raise ValueError('共同课程已更新，请重新预览')
        if b.get('action')=='subscribe':
            result,_,_=merge.plan(current,template(c,key,member))
        elif b.get('action')=='unsubscribe':
            if not c.execute('SELECT 1 FROM teaching_enrollments WHERE member=? AND offering=? AND active=1',(member,key)).fetchone():raise ValueError('尚未订阅这门课')
            cid=row['id']
            result={**current,'courses':[x for x in current['courses'] if x['id']!=cid],'events':[x for x in current['events'] if x['course_id']!=cid]}
        else:raise ValueError('订阅操作无效')
        if result!=current:
            course_store.put_schedule(c,member,current,'previous');course_store.put_schedule(c,member,result)
        sync(c,member,result,'subscription')
        audit(c,member,b['action'],key,{})
        return {'ok':True}


def management(c, member):
    with course_store.transaction(c):
        role=roles(c,member)
        if not role['admin'] and not role['representativeOf']:
            raise PermissionError('暂无课程管理权限')
        course_cards=cards(c,member,True)
        if not role['admin']:
            course_cards=[x for x in course_cards if x['key'] in role['representativeOf']]
        return {**role,'courses':course_cards,
                'members':[dict(r) for r in c.execute('SELECT id,name,student FROM members WHERE disabled=0 ORDER BY name')] if role['admin'] else [],
                'audit':[dict(r) for r in c.execute('SELECT a.action,a.target,a.created_at,m.name AS actor FROM class_audit a LEFT JOIN members m ON a.actor=m.id ORDER BY a.rowid DESC LIMIT 20')] if role['admin'] else []}


def bulk_plan(c, actor, b):
    members=b.get('members');keys=b.get('courses')
    if not isinstance(members,list) or not 1<=len(members)<=200 or any(type(x) is not int for x in members) or len(set(members))!=len(members):raise ValueError('请选择有效同学')
    if not isinstance(keys,list) or not 1<=len(keys)<=30 or any(not isinstance(x,str) for x in keys) or len(set(keys))!=len(keys):raise ValueError('请选择共同课程')
    revisions=[];templates=[]
    for key in sorted(keys):
        row=c.execute('SELECT revision FROM teaching_offerings WHERE key=? AND published=1',(key,)).fetchone()
        if not row:raise ValueError('只能预置已开放的共同课程')
        revisions.append((key,row['revision']));templates.append(template(c,key,actor))
    if any(not merge.same_term(templates[0],t) for t in templates):raise ValueError('请选择同一学期与校历的课程')
    source={**templates[0],'courses':[x for t in templates for x in t['courses']],'events':[e for t in templates for e in t['events']]}
    plans=[];versions=[]
    for member in sorted(members):
        row=c.execute('SELECT name FROM members WHERE id=? AND disabled=0',(member,)).fetchone()
        if not row:raise ValueError('同学账号不存在或已停用')
        current=course_store.read_schedule(c,member);versions.append((member,importer.fingerprint(current)))
        try:
            result,conflicts,_=merge.plan(current,{**source,'owner':member})
            changes=importer.diff_courses(current,result)
            plans.append({'member':member,'name':row['name'],'added':sum(x['kind']=='新增' for x in changes),'kept':len(conflicts),'skipped':'','data':result})
        except ValueError as e:
            plans.append({'member':member,'name':row['name'],'added':0,'kept':0,'skipped':str(e),'data':None})
    token=importer.fingerprint({'courses':revisions,'members':versions})
    return token,plans


def manage(c, member, b):
    with course_store.transaction(c,write=True):
        require_admin(c,member)
        action=b.get('action')
        if action=='publish':
            data=course_store.read_schedule(c,member);ids=b.get('courses')
            if b.get('base')!=importer.fingerprint(data):raise ValueError('课表已变化，请重新预览')
            if not isinstance(ids,list) or not ids or any(not isinstance(x,str) for x in ids) or len(set(ids))!=len(ids) or not set(ids)<={x['id'] for x in data['courses']}:raise ValueError('请选择自己的有效课程')
            for course in data['courses']:
                if course['id'] in ids:
                    key=write_template(c,member,data,course,True)
                    audit(c,member,'publish',key,{'name':course['name']})
            sync(c,member,data,'existing')
            return {'ok':True}
        if action in ('representative-add','representative-remove'):
            key,target=b.get('key'),b.get('member')
            if not isinstance(key,str) or type(target) is not int or not c.execute('SELECT 1 FROM teaching_offerings WHERE key=? AND published=1',(key,)).fetchone() or not c.execute('SELECT 1 FROM members WHERE id=? AND disabled=0',(target,)).fetchone():raise ValueError('课程或同学无效')
            if action=='representative-add':
                if not c.execute('SELECT 1 FROM teaching_enrollments WHERE member=? AND offering=? AND active=1',(target,key)).fetchone():raise ValueError('请先将这位同学加入该课程，再设置课代表')
                c.execute('INSERT OR IGNORE INTO teaching_representatives VALUES(?,?)',(key,target))
            else:c.execute('DELETE FROM teaching_representatives WHERE offering=? AND member=?',(key,target))
            audit(c,member,action,key,{'member':target})
            return {'ok':True}
        if action in ('preload-preview','preload-save'):
            token,plans=bulk_plan(c,member,b)
            if action=='preload-save':
                if b.get('token')!=token:raise ValueError('课表或共同课程已变化，请重新预览')
                for p in plans:
                    if p['data'] is None:continue
                    before=course_store.read_schedule(c,p['member'])
                    if before!=p['data']:
                        course_store.put_schedule(c,p['member'],before,'previous');course_store.put_schedule(c,p['member'],p['data'])
                    sync(c,p['member'],p['data'],'preload')
                audit(c,member,'preload',token,{'members':b['members'],'courses':b['courses']})
            return {'ok':True,'token':token,'plans':[{k:v for k,v in p.items() if k!='data'} for p in plans]}
        raise ValueError('管理操作无效')
