import copy
import json
from classroom import push,course_store
from classroom.app import connect
from test_push import PushTests
import test_classroom as helpers


class PushIsolationTests(PushTests):
    op=helpers.ClassroomTests.op
    save=helpers.ClassroomTests.save
    task=helpers.ClassroomTests.task

    def bind(self,index,tag):
        sub={**self.sub,'endpoint':'https://web.push.apple.com/fictional-'+tag}
        r=self.api('register',{'subscription':sub,'label':'测试设备'+tag},index)
        self.assertEqual(r[0],200,r)
        return r[2]['deviceId']

    def queue(self,index,device,key):
        r=self.api('test',{'deviceId':device,'requestKey':key},index)
        self.assertEqual(r[0],200,r)
        return r[2]['jobs'][0]

    def business_snapshot(self):
        with connect(self.db) as c:
            names=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'") if r[0].startswith(('course_','teaching_'))]
            return {n:sorted(json.dumps(dict(r),sort_keys=True) for r in c.execute('SELECT * FROM '+n)) for n in names}

    def test_two_accounts_deliver_only_to_their_devices_without_changing_business_data(self):
        self.save(index=0);self.save(index=1)
        for i in (0,1):
            r=self.call('/api/homework',{'owner':self.owners[i],'expected':None,'task':self.task()},cookie=self.cookies[i])
            self.assertEqual(r[0],200,r)
        before=self.business_snapshot()
        devices=[self.bind(0,'person-a'),self.bind(1,'person-b')]
        jobs=[self.queue(i,devices[i],'isolation-request-'+str(i)) for i in (0,1)]
        sends=[]
        with connect(self.db) as c:
            for _ in range(2):push.tick(c,self.cfg,lambda sub,payload,*a:sends.append((sub['endpoint'],payload)) or 201,max(j['due'] for j in jobs))
        self.assertEqual(len(sends),2)
        self.assertEqual({(url,p['owner']) for url,p in sends},{('https://web.push.apple.com/fictional-person-a',self.owners[0]),('https://web.push.apple.com/fictional-person-b',self.owners[1])})
        for url,p in sends:
            i=0 if url.endswith('person-a') else 1
            name=('测试甲','测试乙')[i]
            self.assertEqual(p['title'],'课间测试 · 给'+name)
            self.assertIn('尾号000'+str(i+1),p['body'])
            self.assertNotIn(('测试乙','测试甲')[i],p['body'])
        for i in (0,1):
            self.assertEqual(self.call('/api/session',cookie=self.cookies[i])[2]['id'],self.owners[i])
            status=self.api('status',{'deviceId':devices[i]},i)
            self.assertEqual(status[0],200)
            self.assertEqual([j['id'] for j in status[2]['jobs']],[jobs[i]['id']])
            self.assertEqual(self.api('status',{'deviceId':devices[1-i]},i)[0],403)
            self.assertEqual(self.api('confirm',{'deviceId':devices[i],'id':jobs[1-i]['id'],'received':True},i)[0],400)
        self.assertEqual(self.business_snapshot(),before)

    def test_logging_in_another_person_on_an_independent_device_does_not_disable_me(self):
        device=self.bind(0,'first-phone');job=self.queue(0,device,'independent-login-test')
        r=self.call('/api/login',{'student':'2026000002','password':'test-password-123'})
        self.assertEqual(r[0],200)
        other_cookie=r[1]['Set-Cookie'].split(';')[0]
        sends=[]
        with connect(self.db) as c:
            self.assertEqual(c.execute('SELECT active FROM push_devices WHERE id=?',(device,)).fetchone()[0],1)
            push.tick(c,self.cfg,lambda sub,payload,*a:sends.append(payload['owner']) or 201,job['due'])
        self.assertEqual(sends,[self.owners[0]])
        self.assertEqual(self.call('/api/session',cookie=self.cookies[0])[2]['id'],self.owners[0])
        self.assertEqual(self.call('/api/session',cookie=other_cookie)[2]['id'],self.owners[1])

    def test_same_browser_account_switch_cancels_previous_binding_and_requires_new_opt_in(self):
        device=self.bind(0,'same-phone');job=self.queue(0,device,'same-browser-switch-test')
        before=self.business_snapshot()
        r=self.call('/api/login',{'student':'2026000002','password':'test-password-123'},cookie=self.cookies[0])
        self.assertEqual(r[0],200)
        with connect(self.db) as c:
            push.tick(c,self.cfg,lambda *a:self.fail('Previous account sent after switch'),job['due'])
            self.assertEqual(c.execute('SELECT state FROM push_jobs WHERE id=?',(job['id'],)).fetchone()[0],'cancelled')
            self.assertEqual(c.execute('SELECT active FROM push_devices WHERE id=?',(device,)).fetchone()[0],0)
        self.assertEqual(self.business_snapshot(),before)

    def test_account_switch_during_send_suppresses_inflight_old_account_display(self):
        device=self.register();job=self.schedule(device);sent=[]
        def race(sub,payload,*args):
            sent.append(payload)
            self.assertEqual(self.register(1),device)
            return 201
        with connect(self.db) as c:push.tick(c,self.cfg,race,job['due'])
        data=sent[0]
        # Even after provider acceptance, account validation prevents displaying old content.
        result=self.api('receipt',{'id':data['id'],'receipt':data['receipt'],'stage':'received'})
        self.assertEqual(result[0],200,result);self.assertFalse(result[2]['display'])
        self.assertEqual(self.api('receipt',{'id':data['id'],'receipt':data['receipt'],'stage':'received'},1)[0],403)

    def test_other_account_logout_does_not_cancel_my_queued_notification(self):
        first=self.bind(0,'phone-a');second=self.bind(1,'phone-b')
        a=self.queue(0,first,'logout-isolation-a');b=self.queue(1,second,'logout-isolation-b')
        self.assertEqual(self.call('/api/logout',{'owner':self.owners[1]},cookie=self.cookies[1])[0],200)
        deliveries=[]
        with connect(self.db) as c:
            push.tick(c,self.cfg,lambda sub,payload,*args:deliveries.append(payload['owner']) or 201,max(a['due'],b['due']))
        self.assertEqual(deliveries,[self.owners[0]])
        self.assertEqual(self.call('/api/session',cookie=self.cookies[0])[0],200)
