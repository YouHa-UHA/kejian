"""Run a local, fictional classroom without connecting to any external service."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
from wsgiref.simple_server import make_server

from .app import ClassroomApplication,connect,initialize,provision
from . import community,course_store,course_homework
from .preview import Quiet

DEMO_PASSWORD='DemoOnly2026!'
DEMO_MEMBERS=[
    ('2026000001','演示管理员'),('2026000002','演示同学甲'),
    ('2026000003','演示课代表'),('2026000004','演示空课表'),
    ('2026000005','演示同学乙'),
]
EXAMPLE=Path(__file__).resolve().parents[1]/'examples'/'demo-schedule.json'


def seed(path):
    path=Path(path)
    if path.exists():
        return False
    initialize(path)
    provision(path,[{'student':s,'name':n} for s,n in DEMO_MEMBERS],default_password=DEMO_PASSWORD)
    source=json.loads(EXAMPLE.read_text(encoding='utf-8'))
    groups=[{'demo-systems-a','demo-systems-b','demo-practice','demo-english'},
            {'demo-systems-a','demo-practice','demo-english'},
            {'demo-systems-a','demo-practice','demo-english'},set(),
            {'demo-systems-b','demo-english'}]
    with connect(path) as c,course_store.transaction(c,write=True):
        members=[c.execute('SELECT id FROM members WHERE student=?',(s,)).fetchone()[0] for s,_ in DEMO_MEMBERS]
        admin=members[0]
        c.execute('INSERT INTO class_admins VALUES(?)',(admin,))
        for member,ids in zip(members,groups):
            data=deepcopy(source);data['owner']=member;data.pop('schema_version',None)
            data['courses']=[x for x in data['courses'] if x['id'] in ids]
            data['events']=[x for x in data['events'] if x['course_id'] in ids]
            course_store.put_schedule(c,member,data)
            community.sync(c,member,data,'fictional-demo')
        shared=course_store.read_schedule(c,admin)
        for course in shared['courses']:
            community.write_template(c,admin,shared,course,True)
        key=community.identity(shared,'demo-systems-a')
        c.execute('INSERT INTO teaching_representatives VALUES(?,?)',(key,members[2]))
        course_homework.change(c,members[2],{
            'action':'save','key':key,'id':'coursework-demo-a','expected':None,
            'task':{'title':'系统边界分析（演示）','notes':'虚构作业：选择一个生活中的系统，说明目标、边界和环境，整理成一页文字。','dueDate':'2026-10-30','dueTime':'20:00'}})
        other=community.identity(shared,'demo-systems-b')
        course_homework.change(c,admin,{
            'action':'save','key':other,'id':'coursework-demo-b','expected':None,
            'task':{'title':'要素关系图（演示）','notes':'虚构作业：用一张图说明系统要素及相互关系。此作业只属于 B 教学班。','dueDate':'2026-10-31','dueTime':''}})
    return True


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port',type=int,default=4188)
    p.add_argument('--db',default='state/demo.sqlite3')
    args=p.parse_args()
    created=seed(args.db)
    origin=f'http://127.0.0.1:{args.port}'
    app=ClassroomApplication(args.db,origin=origin,release='public-demo-r17')
    print(('已创建虚构演示数据。' if created else '使用已有本地数据库，保留原进度。')+' 不连接正式服务器。',flush=True)
    print(f'课间演示：{origin}/',flush=True)
    print('演示账号：2026000001 至 2026000005；仅本地密码：'+DEMO_PASSWORD,flush=True)
    with make_server('127.0.0.1',args.port,app,handler_class=Quiet) as server:
        try:server.serve_forever()
        except KeyboardInterrupt:pass


if __name__=='__main__':main()
