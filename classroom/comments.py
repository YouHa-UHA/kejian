"""Course assignment discussions; web and personal AI share this boundary."""
import re
import uuid
from . import course_store, course_homework, community


def schema(c):
    c.execute('''CREATE TABLE IF NOT EXISTS homework_comments(
        seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
        homework TEXT NOT NULL REFERENCES teaching_homework(id),
        author INTEGER NOT NULL REFERENCES members(id), body TEXT NOT NULL,
        reply_to TEXT REFERENCES homework_comments(id),
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT NOT NULL DEFAULT '',
        revision TEXT NOT NULL)''')
    c.execute('CREATE INDEX IF NOT EXISTS homework_comments_page ON homework_comments(homework,seq)')


def access(c, member, homework):
    if not isinstance(homework,str):raise ValueError('请选择课程作业')
    task=c.execute('SELECT * FROM teaching_homework WHERE id=?',(homework,)).fetchone()
    if not task:raise PermissionError('这项课程作业不可访问')
    course_homework.offering(c,task['offering'])
    if not course_homework.enrolled(c,member,task['offering']) and not course_homework.can_edit(c,member,task['offering']):
        raise PermissionError('你没有加入这门课程')
    if task['deleted_at']:raise ValueError('课程作业已更新或撤回，请重新查看')
    return task


def representatives(c,key):
    # Names and opaque member IDs only, not the class roster or private contact data.
    return [{'id':r['id'],'name':r['name']} for r in c.execute('''SELECT m.id,m.name FROM teaching_representatives r
        JOIN members m ON m.id=r.member AND m.disabled=0
        JOIN teaching_enrollments e ON e.member=r.member AND e.offering=r.offering AND e.active=1
        WHERE r.offering=? ORDER BY m.name,m.id''',(key,))]


def serialize(c,row,member,key):
    author=c.execute('SELECT name FROM members WHERE id=?',(row['author'],)).fetchone()
    rep=row['author'] in {x['id'] for x in representatives(c,key)}
    admin=community.roles(c,row['author'])['admin']
    return {'id':row['id'],'homework':row['homework'],'author':author['name'] if author else '同学',
        'authorRole':'representative' if rep else 'admin' if admin else 'student',
        'mine':row['author']==member,'body':'' if row['deleted_at'] else row['body'],
        'replyTo':row['reply_to'],'createdAt':row['created_at'],'updatedAt':row['updated_at'],
        'deleted':bool(row['deleted_at']),'revision':row['revision'],
        'canEdit':not row['deleted_at'] and row['author']==member,
        'canDelete':not row['deleted_at'] and (row['author']==member or course_homework.can_edit(c,member,key))}


def listing(c,member,homework,after=None,comment=None):
    with course_store.transaction(c):
        task=access(c,member,homework)
        if comment is not None and (not isinstance(comment,str) or not re.fullmatch(r'comment-[a-zA-Z0-9-]{1,70}',comment) or after is not None):raise ValueError('评论查询条件无效')
        if after is None:after='0'
        if not isinstance(after,str) or not re.fullmatch(r'\d{1,18}',after):raise ValueError('评论分页位置无效')
        rows=c.execute('SELECT * FROM homework_comments WHERE homework=? AND seq>? ORDER BY seq LIMIT 51',(homework,int(after))).fetchall()
        if comment is not None:
            rows=c.execute('SELECT * FROM homework_comments WHERE homework=? AND id=?',(homework,comment)).fetchall()
        return {'homework':homework,'representatives':representatives(c,task['offering']),
            'items':[serialize(c,r,member,task['offering']) for r in rows[:50]],
            'total':c.execute("SELECT count(*) FROM homework_comments WHERE homework=? AND deleted_at=''",(homework,)).fetchone()[0],
            'nextCursor':str(rows[49]['seq']) if len(rows)>50 else None}


def authorize(c,member,b):
    task=access(c,member,b.get('homework'))
    row=c.execute('SELECT * FROM homework_comments WHERE id=?',(b.get('id'),)).fetchone() if isinstance(b.get('id'),str) else None
    if row and row['homework']!=task['id']:raise PermissionError('评论不属于这项作业')
    action=b.get('action')
    if row and action=='edit' and row['author']!=member:raise PermissionError('只能修改自己发表的评论')
    if row and action=='delete' and row['author']!=member and not course_homework.can_edit(c,member,task['offering']):
        raise PermissionError('只能删除自己的评论，课代表可以管理本课程讨论')
    if row and action=='create' and row['author']!=member:raise PermissionError('不能使用其他同学的评论编号')
    return task,row


def change(c,member,b):
    with course_store.transaction(c,write=True):
        if set(b)-{'owner','action','homework','id','body','replyTo','expected'}:raise ValueError('评论参数包含不支持的字段')
        if b.get('action') not in ('create','edit','delete'):raise ValueError('评论操作无效')
        if not isinstance(b.get('id'),str) or not re.fullmatch(r'comment-[a-zA-Z0-9-]{1,70}',b['id']):raise ValueError('评论编号无效')
        task,row=authorize(c,member,b);action=b['action'];text=b.get('body','')
        if action!='delete':
            if not isinstance(text,str) or not 1<=len(text.strip())<=4000:raise ValueError('评论请填写1至4000字')
            text=text.strip()
        reply=b.get('replyTo') or None
        if reply is not None:
            if not isinstance(reply,str):raise ValueError('回复对象无效')
            parent=c.execute('SELECT * FROM homework_comments WHERE id=? AND homework=?',(reply,task['id'])).fetchone()
            if not parent:raise ValueError('回复的评论不存在')
        if action=='create' and row:
            if not row['deleted_at'] and row['body']==text and row['reply_to']==reply:
                return {'comment':serialize(c,row,member,task['offering'])}
            raise ValueError('评论已更新，请重新查看')
        if action!='create' and not row:raise ValueError('评论不存在')
        if (row['revision'] if row else None)!=b.get('expected') or (row and row['deleted_at']):raise ValueError('评论已更新，请重新查看')
        stamp=community.now();revision=str(uuid.uuid4())
        if action=='create':
            recent=c.execute('SELECT count(*) FROM homework_comments WHERE author=? AND created_at>?',(member,stamp[:10]+'T00:00:00')).fetchone()[0]
            if recent>=500:raise ValueError('今天的评论较多，请稍后再试')
            c.execute('INSERT INTO homework_comments(id,homework,author,body,reply_to,created_at,updated_at,revision) VALUES(?,?,?,?,?,?,?,?)',
                (b['id'],task['id'],member,text,reply,stamp,stamp,revision))
        elif action=='edit':
            c.execute('UPDATE homework_comments SET body=?,updated_at=?,revision=? WHERE id=?',(text,stamp,revision,b['id']))
        else:
            c.execute("UPDATE homework_comments SET body='',deleted_at=?,updated_at=?,revision=? WHERE id=?",(stamp,stamp,revision,b['id']))
        community.audit(c,member,'comment-'+action,task['offering'],{'homework':task['id'],'comment':b['id']})
        return {'comment':serialize(c,c.execute('SELECT * FROM homework_comments WHERE id=?',(b['id'],)).fetchone(),member,task['offering'])}
