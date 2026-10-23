import copy
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from classroom.app import ClassroomApplication, provision, connect


class ClassroomTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Path(self.tmp.name)/'class.sqlite3'
        self.app=ClassroomApplication(self.db,origin='https://class.example',base='/mem/')
        self.codes=provision(self.db,[{'student':'2026000001','name':'测试甲'},{'student':'2026000002','name':'测试乙'}])
        self.cookies=[];self.owners=[]
        for item in self.codes:
            status,headers,_=self.call('/api/activate',payload={**item,'password':'test-password-123'})
            self.assertEqual(status,200);self.cookies.append(headers['Set-Cookie'].split(';')[0])
            self.owners.append(self.call('/api/session',cookie=self.cookies[-1])[2]['id'])
        self.text='【课表开始】'+json.dumps({'学期':'2026-2027秋冬','课程':[
            {'名称':'系统工程','教学班':'class-a','老师':'测试教师','地点':'测试楼301','原始备注':'四次确定日期','待确认':'','安排':[{'日期':['2026-10-16','2026-10-30','2027-01-08','2027-01-15'],'节次':'2-5','类型':'教室'}]},
            {'名称':'线上英语','教学班':'class-b','老师':'另一教师','地点':'','原始备注':'','待确认':'结束时间待定','安排':[{'教学周':[2,3,4],'星期':2,'开始时间':'19:00','类型':'线上'}]}
        ]},ensure_ascii=False)+'【课表结束】'

    def tearDown(self):self.tmp.cleanup()

    def call(self,path,payload=None,cookie='',origin='https://class.example',header=True):
        captured={};raw=json.dumps(payload).encode() if payload is not None else b''
        def start(s,h):captured.update(status=int(s[:3]),headers=dict(h))
        env={'PATH_INFO':path,'REQUEST_METHOD':'POST' if payload is not None else 'GET','wsgi.input':BytesIO(raw),'CONTENT_LENGTH':str(len(raw)),'CONTENT_TYPE':'application/json','HTTP_ORIGIN':origin,'HTTP_X_KEJIAN_REQUEST':'1' if header else '', 'HTTP_COOKIE':cookie,'REMOTE_ADDR':'test'}
        data=b''.join(self.app(env,start))
        try:data=json.loads(data)
        except ValueError:pass
        return captured['status'],captured['headers'],data

    def op(self,payload,index=0):
        return self.call('/api/timetable-import',payload={'owner':self.owners[index],**payload},cookie=self.cookies[index])

    def save(self,text=None,index=0,selected=None):
        b={'text':text or self.text}
        if selected is not None:b['selected']=selected
        status,_,preview=self.op(b,index);self.assertEqual(status,200,preview)
        status,_,result=self.op({**b,'action':'save','base':preview['base']},index)
        self.assertEqual(status,200,result);return result

    def task(self,index=0):
        return {'id':'task-test','title':'案例作业','courseId':'class-a','notes':'测试','dueDate':'2026-10-30','dueTime':'23:00','createdAt':'','updatedAt':'','completedAt':'','deletedAt':'','revision':''}

    def test_roster_activation_and_no_public_personal_data(self):
        for path in ['/api/session','/api/schedule','/api/homework','/api/timetable-peers']:
            self.assertEqual(self.call(path)[0],401)
        self.assertEqual(self.call('/api/login',payload={'student':'99999999','password':'test-password'})[0],401)
        self.assertEqual(self.call('/api/activate',payload={**self.codes[0],'password':'new-test-password'})[0],401)
        self.assertIn('HttpOnly',self.call('/api/login',payload={'student':'2026000001','password':'test-password-123'})[1]['Set-Cookie'])
        self.assertEqual(provision(self.db,[{'student':'2026000001','name':'ignored'}]),[])

    def test_default_password_login_and_repeat_roster_preserves_account(self):
        rows=[{'student':'2026000003','name':'初始密码测试'}]
        self.assertEqual(len(provision(self.db,rows,default_password='654321')),1)
        status,headers,_=self.call('/api/login',payload={'student':rows[0]['student'],'password':'654321'})
        self.assertEqual(status,200)
        self.assertEqual(provision(self.db,rows,default_password='777777'),[])
        self.assertEqual(self.call('/api/login',payload={'student':rows[0]['student'],'password':'654321'})[0],200)
        with connect(self.db) as c:
            member=c.execute('SELECT * FROM members WHERE student=?',(rows[0]['student'],)).fetchone()
            self.assertNotEqual(member['password_hash'],'654321')
            self.assertIsNone(member['activation_hash'])

    def test_import_dates_selection_persistence_and_owner_isolation(self):
        result=self.save(selected=['class-a'])
        self.assertEqual(len(result['data']['events']),4)
        self.assertEqual(result['data']['events'][-1]['date'],'2027-01-15')
        self.assertEqual(self.call('/api/schedule',cookie=self.cookies[1])[2]['courses'],[])
        self.assertEqual(self.op({'owner':self.owners[1],'text':self.text})[0],403)
        self.app=ClassroomApplication(self.db,origin='https://class.example',base='/mem/')
        self.assertEqual(len(self.call('/api/schedule',cookie=self.cookies[0])[2]['courses']),1)

    def test_invalid_import_and_stale_save_do_not_replace(self):
        preview=self.op({'text':self.text})[2]
        self.save()
        self.assertEqual(self.op({'action':'save','text':self.text,'base':preview['base']})[0],409)
        self.assertEqual(self.op({'text':'garbage','action':'save','base':'bad'})[0],409)
        self.assertEqual(self.op({'text':self.text.replace('2027-01-08','2027-02-08')})[0],400)
        self.assertEqual(len(self.call('/api/schedule',cookie=self.cookies[0])[2]['courses']),2)

    def test_peer_copy_requires_opt_in_and_is_independent(self):
        self.save()
        self.assertEqual(self.op({'sourceMember':self.owners[0]},1)[0],403)
        self.call('/api/profile',payload={'owner':self.owners[0],'shared':True},cookie=self.cookies[0])
        peer=self.op({'sourceMember':self.owners[0]},1)[2]
        self.assertEqual(self.op({'action':'save','base':peer['base'],'sourceMember':self.owners[0],'sourceVersion':'old'},1)[0],409)
        result=self.op({'action':'save','base':peer['base'],'sourceMember':self.owners[0],'sourceVersion':peer['sourceVersion']},1)
        self.assertEqual(result[0],200,result)
        base=self.op({'action':'inspect'})[2]['base'];self.op({'action':'clear','base':base})
        self.assertEqual(len(self.call('/api/schedule',cookie=self.cookies[1])[2]['courses']),2)
        self.assertEqual(self.call('/api/homework',cookie=self.cookies[1])[2]['items'],[])

    def test_clear_restore_and_homework_concurrency(self):
        self.save();cookie=self.cookies[0];owner=self.owners[0]
        payload={'owner':owner,'task':self.task(),'expected':None}
        status,_,result=self.call('/api/homework',payload=payload,cookie=cookie)
        self.assertEqual(status,200,result);self.assertTrue(result['next']['revision'])
        self.assertEqual(self.call('/api/homework',payload=payload,cookie=cookie)[0],409)
        self.assertEqual(self.call('/api/homework',payload={**payload,'owner':self.owners[1]},cookie=cookie)[0],403)
        base=self.op({'action':'inspect'})[2]['base'];self.op({'action':'clear','base':base})
        self.assertEqual(len(self.call('/api/homework',cookie=cookie)[2]['items']),1)
        base=self.op({'action':'inspect'})[2]['base'];self.op({'action':'restore','base':base})
        self.assertEqual(len(self.call('/api/schedule',cookie=cookie)[2]['courses']),2)

    def test_remove_any_personal_course_restore_and_stale_guard(self):
        self.save();self.save(index=1)
        cookie=self.cookies[0]
        self.call('/api/homework',payload={'owner':self.owners[0],'task':self.task(),'expected':None},cookie=cookie)
        before=self.call('/api/schedule',cookie=cookie)[2]
        other=self.call('/api/schedule',cookie=self.cookies[1])[2]
        base=self.op({'action':'inspect'})[2]['base']
        invalid={'action':'remove','base':base,'courseId':'missing'}
        self.assertEqual(self.op(invalid)[0],400)
        self.assertEqual(self.call('/api/timetable-import',payload={'owner':self.owners[1],**invalid},cookie=cookie)[0],403)
        status,_,removed=self.op({'action':'remove','base':base,'courseId':'class-a'})
        self.assertEqual(status,200,removed)
        self.assertEqual([x['id'] for x in removed['data']['courses']],['class-b'])
        self.assertTrue(all(e['course_id']=='class-b' for e in removed['data']['events']))
        self.assertEqual(len(self.call('/api/homework',cookie=cookie)[2]['items']),1)
        self.assertEqual(self.call('/api/schedule',cookie=self.cookies[1])[2],other)
        self.assertEqual(self.op({'action':'remove','base':base,'courseId':'class-b'})[0],409)
        status,_,restored=self.op({'action':'restore','base':removed['nextBase']})
        self.assertEqual(status,200)
        self.assertEqual(restored['data']['courses'],before['courses'])
        self.assertEqual(restored['data']['events'],before['events'])
        # A subsequent edit must not be erased by an old undo token.
        self.op({'action':'remove','courseId':'class-a','base':restored['nextBase']})
        now=self.op({'action':'inspect'})[2]['base']
        self.op({'action':'remove','courseId':'class-b','base':now})
        self.assertEqual(self.op({'action':'restore','base':removed['nextBase']})[0],409)

    def test_remove_course_without_teaching_class_number(self):
        obj={'学期':'2026-2027秋冬','课程':[{'名称':'自选课程','老师':'测试','安排':[]}]}
        self.save('【课表开始】'+json.dumps(obj)+'【课表结束】')
        courses=self.call('/api/schedule',cookie=self.cookies[0])[2]['courses']
        self.assertTrue(courses[0]['id'].startswith('import-'))
        base=self.op({'action':'inspect'})[2]['base']
        result=self.op({'action':'remove','courseId':courses[0]['id'],'base':base})
        self.assertEqual(result[0],200,result);self.assertEqual(result[2]['data']['courses'],[])

    def test_new_semester_explicit_times_and_strict_dates(self):
        obj={'学期':'2027-2028秋冬','开学日期':'2027-09-13','结束日期':'2028-01-16','课程':[{'名称':'另一门课','教学班':'new-course','安排':[{'教学周':[2],'星期':2,'开始时间':'19:00','结束时间':'20:30','类型':'线上','地点':'线上教室'}]}]}
        text='【课表开始】'+json.dumps(obj)+'【课表结束】'
        result=self.save(text)
        e=result['data']['events'][0];self.assertEqual((e['date'],e['start_time'],e['end_time']),('2027-09-21','19:00','20:30'))
        obj.pop('开学日期');self.assertEqual(self.op({'text':'【课表开始】'+json.dumps(obj)+'【课表结束】'})[0],400)
        self.assertEqual(self.op({'text':self.text.replace('2027-01-08','20270108')})[0],400)

    def test_csrf_logout_and_no_experimental_push(self):
        b={'owner':self.owners[0],'shared':True}
        self.assertEqual(self.call('/api/profile',payload=b,cookie=self.cookies[0],origin='https://evil.example')[0],403)
        self.assertEqual(self.call('/api/profile',payload=b,cookie=self.cookies[0],header=False)[0],403)
        for path in ['/reminders.html','/push-test.html','/data/sources/my-courses.json','/classroom/app.py']:
            self.assertEqual(self.call(path,cookie=self.cookies[0])[0],404)
        self.call('/api/logout',payload={'owner':self.owners[0]},cookie=self.cookies[0])
        self.assertEqual(self.call('/api/session',cookie=self.cookies[0])[0],401)
        self.assertEqual(self.call('/api/session',cookie=self.cookies[1])[0],200)

    def test_explicit_domain_and_ip_origins_keep_csrf_protection(self):
        self.app=ClassroomApplication(self.db,origin='https://kejian.example',base='/mem/',extra_origins=('https://203.0.113.10',))
        b={'student':'2026000001','password':'test-password-123'}
        for origin in ('https://kejian.example','https://203.0.113.10'):
            self.assertEqual(self.call('/api/login',payload=b,origin=origin)[0],200)
        for origin in ('https://evil.example','https://kejian.example.evil.example','null','http://kejian.example'):
            self.assertEqual(self.call('/api/login',payload=b,origin=origin)[0],403)
        self.assertEqual(self.call('/api/login',payload=b,origin='https://kejian.example',header=False)[0],403)
        with self.assertRaises(ValueError):
            ClassroomApplication(self.db,origin='https://kejian.example/mem/')

    def test_safe_merge_reimport_preserves_existing_and_restore_slot(self):
        self.save()
        before=self.call('/api/schedule',cookie=self.cookies[0])[2]
        with connect(self.db) as c:
            previous=c.execute("SELECT version FROM course_schedules WHERE member=? AND slot='previous'",(self.owners[0],)).fetchone()[0]
        self.save(selected=['class-a'])
        after=self.call('/api/schedule',cookie=self.cookies[0])[2]
        self.assertEqual(before,after)
        with connect(self.db) as c:self.assertEqual(c.execute("SELECT version FROM course_schedules WHERE member=? AND slot='previous'",(self.owners[0],)).fetchone()[0],previous)
        updated=self.text.replace('测试楼301','新楼401')
        p=self.op({'text':updated})[2]
        self.assertEqual(p['conflicts'][0]['decision'],'keep')
        self.assertEqual(p['data']['courses'][0]['location'],'测试楼301')
        b={'text':updated,'decisions':{'class-a':'incoming'}}
        p=self.op(b)[2];self.assertEqual(self.op({**b,'action':'save','base':p['base']})[0],200)
        self.assertEqual(next(c for c in self.call('/api/schedule',cookie=self.cookies[0])[2]['courses'] if c['id']=='class-a')['location'],'新楼401')

    def test_explicit_replace_and_different_semester_guard(self):
        self.save()
        p=self.op({'text':self.text,'selected':['class-a'],'mode':'replace'})[2]
        self.assertEqual([x['kind'] for x in p['changes']],['未变化','移除'])
        self.assertEqual(self.op({'text':self.text,'selected':['class-a'],'mode':'replace','action':'save','base':p['base']})[0],200)
        other='【课表开始】'+json.dumps({'学期':'2027-2028秋冬','开学日期':'2027-09-13','结束日期':'2028-01-16','课程':[{'名称':'新学期','教学班':'new-c','安排':[]}]})+'【课表结束】'
        self.assertEqual(self.op({'text':other})[0],400)
        self.assertEqual(self.op({'text':other,'mode':'replace'})[0],200)

    def admin(self):
        with connect(self.db) as c:c.execute('INSERT OR IGNORE INTO class_admins VALUES(?)',(self.owners[0],))

    def manage(self,b,index=0):
        return self.call('/api/management',payload={'owner':self.owners[index],**b},cookie=self.cookies[index])

    def publish(self):
        self.save();self.admin()
        base=self.op({'action':'inspect'})[2]['base']
        self.assertEqual(self.manage({'action':'publish','courses':['class-a','class-b'],'base':base})[0],200)
        return self.call('/api/course-library',cookie=self.cookies[0])[2]['courses']

    def test_management_permissions_and_no_roster_leak(self):
        self.assertEqual(self.call('/api/management',cookie=self.cookies[1])[0],403)
        self.assertEqual(self.manage({'action':'publish','courses':['class-a']},1)[0],403)
        courses=self.publish()
        lib=self.call('/api/course-library',cookie=self.cookies[1])[2]
        self.assertEqual(len(lib['courses']),2);self.assertNotIn('members',lib)
        self.assertEqual(self.manage({'action':'representative-add','key':courses[0]['key'],'member':self.owners[1]})[0],400)

    def test_library_exposes_shared_times_only_after_opening_without_changing_personal_schedules(self):
        self.save()
        self.assertEqual(self.call('/api/course-library',cookie=self.cookies[1])[2]['courses'],[])
        before=[self.call('/api/schedule',cookie=c)[2] for c in self.cookies]
        self.admin();base=self.op({'action':'inspect'})[2]['base']
        self.assertEqual(self.manage({'action':'publish','courses':['class-a','class-b'],'base':base})[0],200)
        courses=self.call('/api/course-library',cookie=self.cookies[1])[2]['courses']
        by_id={c['courseId']:c for c in courses}
        self.assertEqual(by_id['class-a']['teacher'],'测试教师')
        self.assertEqual([e['date'] for e in by_id['class-a']['sessions']],['2026-10-16','2026-10-30','2027-01-08','2027-01-15'])
        self.assertTrue(all((e['start_time'],e['end_time'])==('08:50','12:25') for e in by_id['class-a']['sessions']))
        self.assertTrue(all(e['start_time']=='19:00' and e['end_time'] is None for e in by_id['class-b']['sessions']))
        self.assertEqual([self.call('/api/schedule',cookie=c)[2] for c in self.cookies],before)
        self.assertFalse(any(c['subscribed'] for c in courses))
        self.assertNotIn('owner',by_id['class-a'])
        self.assertNotIn('raw_remark',by_id['class-a'])

    def test_library_keeps_recurring_schedule_and_fieldwork_actual_times(self):
        from classroom import community,course_store
        data=self.save()['data'];self.admin()
        rule={'weekday':2,'starts_on':'2026-09-22','until':None,'start_time':'19:00','end_time':None,'source':'用户确认每周二','excluded_dates':['2026-10-06']}
        data['courses'][1]['recurrence']=rule
        next(e for e in data['events'] if e['course_id']=='class-a').update(kind='fieldwork',start_time=None,end_time=None,nominal_time='08:50–12:25',location=None)
        with connect(self.db) as c,course_store.transaction(c,write=True):
            course_store.put_schedule(c,self.owners[0],data)
            for course in data['courses']:community.write_template(c,self.owners[0],data,course,True)
        courses=self.call('/api/course-library',cookie=self.cookies[1])[2]['courses']
        self.assertEqual(next(c for c in courses if c['courseId']=='class-b')['recurrence'],rule)
        practice=next(e for c in courses if c['courseId']=='class-a' for e in c['sessions'] if e['kind']=='fieldwork')
        self.assertIsNone(practice['start_time']);self.assertIsNone(practice['end_time'])
        self.assertEqual(practice['kind'],'fieldwork');self.assertNotIn('nominal_time',practice)

    def test_bulk_preload_is_atomic_idempotent_and_representatives_scoped(self):
        courses=self.publish();b={'members':[self.owners[1]],'courses':[c['key'] for c in courses]}
        p=self.manage({'action':'preload-preview',**b})[2]
        self.assertEqual(p['plans'][0]['added'],2)
        self.assertEqual(self.manage({'action':'preload-save',**b,'token':p['token']})[0],200)
        stale=self.manage({'action':'preload-save',**b,'token':p['token']});self.assertEqual(stale[0],409)
        p=self.manage({'action':'preload-preview',**b})[2];self.assertEqual(p['plans'][0]['added'],0)
        self.assertEqual(self.manage({'action':'preload-save',**b,'token':p['token']})[0],200)
        key=courses[0]['key'];self.assertEqual(self.manage({'action':'representative-add','key':key,'member':self.owners[1]})[0],200)
        m=self.call('/api/management',cookie=self.cookies[1])[2]
        self.assertEqual(m['members'],[]);self.assertEqual(len(m['courses']),1)
        self.assertEqual(self.manage({'action':'preload-preview',**b},1)[0],403)

    def test_import_never_rewrites_shared_template_and_unsubscribe_retains_homework(self):
        courses=self.publish();c=next(x for x in courses if x['courseId']=='class-a')
        lib=self.call('/api/course-library',cookie=self.cookies[1])[2]
        b={'owner':self.owners[1],'key':c['key'],'revision':c['revision'],'base':lib['base'],'action':'subscribe'}
        self.assertEqual(self.call('/api/course-library',payload=b,cookie=self.cookies[1])[0],200)
        self.save(self.text.replace('测试楼301','个人楼909'),index=1)
        b={'text':self.text.replace('测试楼301','个人楼909'),'decisions':{'class-a':'incoming'}}
        p=self.op(b,1)[2];self.assertEqual(self.op({**b,'action':'save','base':p['base']},1)[0],200)
        shared=next(x for x in self.call('/api/course-library',cookie=self.cookies[0])[2]['courses'] if x['courseId']=='class-a')
        self.assertEqual(shared['location'],'测试楼301');self.assertEqual(shared['revision'],c['revision'])
        self.assertEqual(self.call('/api/homework',payload={'owner':self.owners[1],'task':self.task(),'expected':None},cookie=self.cookies[1])[0],200)
        lib=self.call('/api/course-library',cookie=self.cookies[1])[2]
        b={'owner':self.owners[1],'key':c['key'],'revision':c['revision'],'base':lib['base'],'action':'unsubscribe'}
        self.assertEqual(self.call('/api/course-library',payload=b,cookie=self.cookies[1])[0],200)
        self.assertEqual(len(self.call('/api/homework',cookie=self.cookies[1])[2]['items']),1)
        self.assertFalse(next(x for x in self.call('/api/course-library',cookie=self.cookies[1])[2]['courses'] if x['courseId']=='class-a')['subscribed'])

    def test_unknown_teaching_class_remains_private(self):
        self.save(self.text.replace('"class-a"','""').replace('"class-b"','""'))
        self.admin();base=self.op({'action':'inspect'})[2]['base']
        cid=self.call('/api/schedule',cookie=self.cookies[0])[2]['courses'][0]['id']
        self.assertEqual(self.manage({'action':'publish','courses':[cid],'base':base})[0],400)
        with connect(self.db) as c:self.assertEqual(c.execute('SELECT count(*) FROM teaching_enrollments').fetchone()[0],0)

    def test_bulk_conflict_keeps_personal_course_and_rejects_partial_invalid_members(self):
        courses=self.publish();self.save(self.text.replace('测试楼301','个人修改楼'),index=1)
        b={'courses':[c['key'] for c in courses],'members':[self.owners[1]]}
        p=self.manage({'action':'preload-preview',**b})[2];self.assertEqual(p['plans'][0]['kept'],1)
        self.assertEqual(self.manage({'action':'preload-save',**b,'token':p['token']})[0],200)
        self.assertEqual(next(c for c in self.call('/api/schedule',cookie=self.cookies[1])[2]['courses'] if c['id']=='class-a')['location'],'个人修改楼')
        self.assertEqual(self.manage({'action':'preload-preview',**b,'members':[self.owners[1],999]})[0],400)

    def test_recurring_personal_course_survives_copy_and_restore(self):
        from classroom import course_store
        result=self.save()['data']
        rule={'weekday':2,'starts_on':'2026-09-22','until':None,'start_time':'19:00','end_time':None,'source':'用户确认每周二','excluded_dates':['2026-10-06']}
        result['courses'][1]['recurrence']=rule
        with connect(self.db) as c,course_store.transaction(c,write=True):
            course_store.put_schedule(c,self.owners[0],result)
        self.assertEqual(self.call('/api/schedule',cookie=self.cookies[0])[2]['courses'][1]['recurrence'],rule)
        self.save()
        self.assertEqual(self.call('/api/schedule',cookie=self.cookies[0])[2]['courses'][1]['recurrence'],rule)
        base=self.op({'action':'inspect'})[2]['base'];self.op({'action':'clear','base':base})
        base=self.op({'action':'inspect'})[2]['base'];self.op({'action':'restore','base':base})
        self.assertEqual(self.call('/api/schedule',cookie=self.cookies[0])[2]['courses'][1]['recurrence'],rule)


if __name__=='__main__':unittest.main()
