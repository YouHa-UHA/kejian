import copy
from io import BytesIO
import json
import unittest
from urllib.parse import urlsplit
import test_classroom as helpers
from classroom.app import ClassroomApplication,connect


class CourseHomeworkTests(unittest.TestCase):
    setUp=helpers.ClassroomTests.setUp
    tearDown=helpers.ClassroomTests.tearDown
    op=helpers.ClassroomTests.op
    save=helpers.ClassroomTests.save
    admin=helpers.ClassroomTests.admin
    manage=helpers.ClassroomTests.manage
    publish=helpers.ClassroomTests.publish
    task=helpers.ClassroomTests.task

    def call(self,path,**kwargs):
        parts=urlsplit(path)
        if not parts.query:return helpers.ClassroomTests.call(self,path,**kwargs)
        captured={}
        def start(s,h):captured.update(status=int(s[:3]),headers=dict(h))
        raw=b''.join(self.app({'PATH_INFO':parts.path,'QUERY_STRING':parts.query,'REQUEST_METHOD':'GET','wsgi.input':BytesIO(),
                              'HTTP_COOKIE':kwargs.get('cookie','')},start))
        return captured['status'],captured['headers'],json.loads(raw)

    def setup_courses(self):
        cards=self.publish()
        self.keys={r['courseId']:r['key'] for r in cards}
        return self.keys

    def shared(self,action='save',index=0,**kwargs):
        payload={'owner':self.owners[index],'action':action,'id':'coursework-example-1','key':self.keys['class-a'],
                 'expected':None,'task':{'title':'案例分析','notes':'第1章案例，提交PDF','dueDate':'2026-10-30','dueTime':'23:00'},**kwargs}
        return self.call('/api/course-homework',payload=payload,cookie=self.cookies[index])

    def feed(self,index=0):return self.call('/api/homework',cookie=self.cookies[index])[2]['items']

    def test_import_automatically_receives_classwork_without_copies(self):
        self.setup_courses();self.assertEqual(self.shared()[0],200)
        self.assertEqual(self.feed(1),[])
        self.save(index=1,selected=['class-a'])
        task=self.feed(1)[0]
        self.assertEqual((task['scope'],task['title'],task['author'],task['canEdit']),('course','案例分析','测试甲',False))
        self.save(index=1)
        self.assertEqual(len(self.feed(1)),1)
        with connect(self.db) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM teaching_homework').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT count(*) FROM course_homework').fetchone()[0],0)
        self.assertEqual(self.call('/api/course-homework?course='+self.keys['class-a'],cookie=self.cookies[1])[0],200)

    def test_personal_tasks_stay_private_and_preserve_combined_feed(self):
        self.setup_courses();self.save(index=1);self.shared()
        status,_,result=self.call('/api/homework',payload={'owner':self.owners[0],'expected':None,'task':self.task()},cookie=self.cookies[0])
        self.assertEqual(status,200);self.assertEqual(len(result['items']),2)
        self.assertEqual(len(self.feed(1)),1)
        self.assertEqual(len([x for x in self.feed(1) if x.get('scope')!='course']),0)
        forged={**self.task(),'id':'coursework-example-1'}
        self.assertEqual(self.call('/api/homework',payload={'owner':self.owners[1],'expected':None,'task':forged},cookie=self.cookies[1])[0],400)

    def test_content_updates_reach_students_but_completion_is_independent(self):
        self.setup_courses();self.save(index=1);first=self.shared()[2]['next']
        done=self.shared('complete',index=1,completed=True)[2]['next']
        self.assertTrue(done['completedAt']);self.assertEqual(self.feed(0)[0]['completedAt'],'')
        content={'title':'案例分析（已补充）','notes':'提交PDF与PPT','dueDate':'2026-11-02','dueTime':'20:00'}
        updated=self.shared(expected=first['revision'],task=content)
        self.assertEqual(updated[0],200,updated)
        t=self.feed(1)[0];self.assertEqual(t['dueDate'],'2026-11-02');self.assertEqual(t['completedAt'],done['completedAt'])
        self.assertEqual(t['completionRevision'],done['completionRevision'])
        self.assertEqual(self.shared('complete',index=1,completed=False)[0],409)
        self.assertEqual(self.shared('complete',index=1,completed=False,expected=done['completionRevision'])[0],200)
        self.app=ClassroomApplication(self.db,origin='https://class.example',base='/mem/')
        self.assertEqual(self.feed(1)[0]['title'],content['title'])
        self.assertEqual(self.feed(0)[0]['completedAt'],'')

    def test_student_and_outsider_cannot_publish_modify_or_complete(self):
        self.setup_courses();first=self.shared()[2]['next']
        self.assertEqual(self.shared(index=1)[0],403)
        self.assertEqual(self.shared('complete',index=1,completed=True)[0],403)
        self.assertEqual(self.call('/api/course-homework?course='+self.keys['class-a'],cookie=self.cookies[1])[0],403)
        self.save(index=1)
        self.assertEqual(self.shared(index=1,expected=first['revision'])[0],403)
        self.assertEqual(self.shared('delete',index=1,expected=first['revision'])[0],403)
        self.assertNotIn('members',self.call('/api/homework',cookie=self.cookies[1])[2])

    def test_representative_is_limited_to_their_active_teaching_class(self):
        self.setup_courses();self.save(index=1)
        self.assertEqual(self.manage({'action':'representative-add','key':self.keys['class-a'],'member':self.owners[1]})[0],200)
        result=self.shared(index=1);self.assertEqual(result[0],200,result)
        self.assertEqual(result[2]['next']['author'],'测试乙')
        self.assertEqual(self.shared(index=1,id='coursework-other-1',key=self.keys['class-b'])[0],403)
        self.assertEqual([x['key'] for x in self.call('/api/homework',cookie=self.cookies[1])[2]['publishCourses']],[self.keys['class-a']])
        self.assertEqual(self.manage({'action':'representative-remove','key':self.keys['class-a'],'member':self.owners[1]})[0],200)
        self.assertEqual(self.shared(index=1,expected=result[2]['next']['revision'])[0],403)
        self.manage({'action':'representative-add','key':self.keys['class-a'],'member':self.owners[1]})
        base=self.op({'action':'inspect'},1)[2]['base'];self.op({'action':'clear','base':base},1)
        self.assertEqual(self.call('/api/homework',cookie=self.cookies[1])[2]['publishCourses'],[])
        self.assertEqual(self.shared(index=1,expected=result[2]['next']['revision'])[0],403)

    def test_same_name_different_class_or_term_never_receives_assignment(self):
        self.setup_courses();self.shared()
        self.save(self.text.replace('class-a','different-class'),index=1)
        self.assertEqual(self.feed(1),[])
        text=self.text.replace('2026-2027秋冬','2027-2028秋冬').replace('2026-10-16','2027-10-15').replace('2026-10-30','2027-10-29').replace('2027-01-08','2028-01-07').replace('2027-01-15','2028-01-14')
        obj=json.loads(text.split('【课表开始】')[1].split('【课表结束】')[0]);obj.update({'开学日期':'2027-09-13','结束日期':'2028-01-16'})
        text='【课表开始】'+json.dumps(obj)+'【课表结束】'
        b={'text':text,'mode':'replace'};p=self.op(b,1)[2]
        self.assertEqual(self.op({**b,'action':'save','base':p['base']},1)[0],200)
        self.assertEqual(self.feed(1),[])

    def test_leaving_and_restoring_course_retains_private_work_and_completion(self):
        self.setup_courses();self.save(index=1);self.shared()
        done=self.shared('complete',index=1,completed=True)[2]['next']
        self.call('/api/homework',payload={'owner':self.owners[1],'task':self.task(),'expected':None},cookie=self.cookies[1])
        base=self.op({'action':'inspect'},1)[2]['base'];self.op({'action':'clear','base':base},1)
        self.assertEqual(len(self.feed(1)),1);self.assertNotEqual(self.feed(1)[0].get('scope'),'course')
        base=self.op({'action':'inspect'},1)[2]['base'];self.op({'action':'restore','base':base},1)
        self.assertEqual(len(self.feed(1)),2)
        self.assertEqual(next(x for x in self.feed(1) if x.get('scope')=='course')['completedAt'],done['completedAt'])

    def test_remove_course_hides_shared_work_and_preserves_completion(self):
        self.setup_courses();self.save(index=1);self.shared()
        done=self.shared('complete',index=1,completed=True)[2]['next']
        base=self.op({'action':'inspect'},1)[2]['base']
        result=self.op({'action':'remove','courseId':'class-a','base':base},1)
        self.assertEqual(result[0],200,result)
        self.assertEqual(self.feed(1),[])
        self.assertEqual(len(self.feed(0)),1)
        self.assertEqual(self.op({'action':'restore','base':result[2]['nextBase']},1)[0],200)
        self.assertEqual(self.feed(1)[0]['completedAt'],done['completedAt'])

    def test_withdrawal_restore_and_stale_content_edits(self):
        self.setup_courses();self.save(index=1);first=self.shared()[2]['next']
        done=self.shared('complete',index=1,completed=True)[2]['next']
        self.assertEqual(self.shared()[0],409)
        self.assertEqual(self.shared(expected='stale')[0],409)
        withdrawn=self.shared('delete',expected=first['revision']);self.assertEqual(withdrawn[0],200)
        self.assertEqual(self.feed(1),[])
        self.assertEqual(self.shared('complete',index=1,completed=False,expected=done['completionRevision'])[0],409)
        self.assertEqual(self.shared('restore',expected=withdrawn[2]['next']['revision'])[0],200)
        self.assertEqual(self.feed(1)[0]['completedAt'],done['completedAt'])
        self.assertEqual(self.shared(key=self.keys['class-b'],expected=self.feed()[0]['revision'])[0],403)

    def test_csrf_owner_and_invalid_payloads_do_not_write(self):
        self.setup_courses()
        self.assertEqual(self.call('/api/course-homework')[0],401)
        payload={'owner':self.owners[0],'action':'save','id':'coursework-evil','key':self.keys['class-a'],'expected':None,'task':{'title':'test','notes':'','dueDate':'','dueTime':''}}
        for change in ({'origin':'https://evil.example'},{'header':False}):
            self.assertEqual(self.call('/api/course-homework',payload=payload,cookie=self.cookies[0],**change)[0],403)
        self.assertEqual(self.call('/api/course-homework',payload={**payload,'owner':self.owners[1]},cookie=self.cookies[0])[0],403)
        for patch in ({'title':' '},{'dueDate':'20261030'},{'dueTime':'25:00'},{'notes':'x'*10001},{'completedAt':'forged'}):
            self.assertEqual(self.shared(task={**payload['task'],**patch})[0],400)
        self.assertEqual(self.feed(),[])


if __name__=='__main__':unittest.main()
