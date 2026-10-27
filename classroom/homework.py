"""Member-owned SQLite homework with transactions and optimistic revisions."""
import uuid
from datetime import date, datetime
import re
from . import course_store

def read(c,member):
    return course_store.read_tasks(c,member)

def change(c,member,payload):
    with course_store.transaction(c,write=True):
        items=read(c,member)
        t=payload.get('task')
        if not isinstance(t,dict):raise ValueError('作业格式无效')
        fields={'id','title','courseId','notes','dueDate','dueTime','createdAt','updatedAt','completedAt','deletedAt','revision'}
        if not fields<=set(t) or set(t)-fields-{'submission'} or any(not isinstance(v,str) for v in t.values()):raise ValueError('作业格式无效')
        if len(t.get('submission','').strip())>2000:raise ValueError('提交方式不能超过2000字')
        if not re.fullmatch(r'[a-zA-Z0-9-]{1,80}',t['id']) or not t['title'].strip() or len(t['title'])>120 or len(t['notes'])>10000:raise ValueError('作业名称或内容无效')
        if t['id'].startswith('coursework-'):raise ValueError('课程作业请通过课程入口管理')
        if t['dueDate']:
            try:date.fromisoformat(t['dueDate'])
            except ValueError:raise ValueError('截止日期无效')
        if t['dueTime'] and (not t['dueDate'] or not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d',t['dueTime'])):raise ValueError('截止时间无效')
        old=next((x for x in items if x['id']==t['id']),None)
        t={**t,'submission':t.get('submission',old['submission'] if old else '').strip()}
        if (old['revision'] if old else None)!=payload.get('expected'):raise ValueError('这条作业已更新，请刷新后再修改')
        schedule=course_store.read_schedule(c,member)
        if t['courseId'] not in {c['id'] for c in schedule['courses']} and (not old or old['courseId']!=t['courseId']):raise ValueError('请选择自己的课程')
        if len(items)>=2000 and not old:raise ValueError('作业数量已达上限')
        now=datetime.now().astimezone().isoformat()
        t={**t,'createdAt':old['createdAt'] if old else now,'updatedAt':now,'revision':str(uuid.uuid4())}
        items=[x for x in items if x['id']!=t['id']]+[t]
        course_store.put_task(c,member,t)
        return {'items':items,'before':old,'next':t}
