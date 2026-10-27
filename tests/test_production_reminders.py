from pathlib import Path
import unittest
from classroom.app import ClassroomApplication,connect
from classroom import push,push_worker
import test_reminders as fixtures


class ProductionReminderTests(unittest.TestCase):
    tearDown=fixtures.ReminderTests.tearDown
    call=fixtures.ReminderTests.call
    api=fixtures.ReminderTests.api
    enable=fixtures.ReminderTests.enable
    publish=fixtures.ReminderTests.publish
    personal=fixtures.ReminderTests.personal
    plan=fixtures.ReminderTests.plan
    jobs=fixtures.ReminderTests.jobs
    dispatch=fixtures.ReminderTests.dispatch

    def setUp(self):
        fixtures.ReminderTests.setUp(self)
        self.cfg={'environment':'production','publicKey':'P'*87}
        self.app=ClassroomApplication(self.db,origin='https://class.example',base='/mem/',push_config=self.cfg)

    def test_environment_and_database_guards_do_not_allow_cross_environment(self):
        self.assertEqual(push.config(self.cfg,'/mem/')['scope'],'/mem/')
        for base,environment in [('/mem-test/','production'),('/mem/','testing'),('/','production')]:
            with self.assertRaises(ValueError):push.config({**self.cfg,'environment':environment},base)
        push_worker.validate_database(self.cfg,Path('/var/lib/kejian/classroom.sqlite3'))
        for database in ('/var/lib/kejian-test/classroom.sqlite3','/tmp/classroom.sqlite3','/var/lib/kejian/other.sqlite3'):
            with self.assertRaises(ValueError):push_worker.validate_database(self.cfg,Path(database))
        with self.assertRaises(ValueError):push_worker.validate_database({'environment':'testing'},Path('/var/lib/kejian/classroom.sqlite3'))

    def test_config_is_authenticated_and_reports_production_scope(self):
        self.assertEqual(self.call('/api/push/config')[0],401)
        result=self.call('/api/push/config',cookie=self.cookies[0])
        self.assertEqual(result[0],200);self.assertEqual(result[2]['environment'],'production')
        self.assertEqual(result[2]['scope'],'/mem/')
        self.assertTrue(self.call('/api/session',cookie=self.cookies[0])[2]['pushEnabled'])

    def test_demo_pages_and_operator_endpoints_are_not_published(self):
        for path in ('/notifications.html','/notifications-isolation.mjs','/notifications-account.mjs','/push-test.html','/wechat-test.html'):
            self.assertEqual(self.call(path,cookie=self.cookies[0])[0],404,path)
        for action in ('account-status','test-account','confirm'):
            self.assertEqual(self.api(action,{'deviceId':self.devices[0]})[0],404,action)

    def test_production_publication_is_exact_class_even_for_admin(self):
        self.enable(0,course=False,homeworkDue=False);self.enable(1,course=False,homeworkDue=False)
        ident=self.publish(self.keys[1]);self.plan();sent=self.dispatch()
        self.assertEqual(len(sent),1)
        endpoint,payload=sent[0]
        self.assertTrue(endpoint.endswith('phone-1'));self.assertEqual(payload['owner'],self.owners[1])
        self.assertTrue(payload['managed']);self.assertNotIn('pilot',payload)
        self.assertEqual(payload['environment'],'production');self.assertEqual(payload['scope'],'/mem/')
        self.assertIn(ident,payload['url'])

    def test_current_account_is_checked_again_before_display(self):
        self.enable(0,course=False,homeworkDue=False);self.publish();self.plan();payload=self.dispatch()[0][1]
        receipt={k:payload[k] for k in ('id','receipt')}
        self.assertEqual(self.api('receipt',{**receipt,'stage':'received'},1)[0],403)
        self.assertTrue(self.api('receipt',{**receipt,'stage':'received'})[2]['display'])
        self.assertEqual(self.call('/api/logout',{'owner':self.owners[0]},cookie=self.cookies[0])[0],200)
        self.assertEqual(self.api('receipt',{**receipt,'stage':'received'})[0],401)

    def test_manual_check_can_only_target_current_owned_device(self):
        self.enable(0)
        self.assertEqual(self.api('test',{'deviceId':self.devices[1],'requestKey':'production-foreign-device-test'})[0],403)
        result=self.api('test',{'deviceId':self.devices[0],'requestKey':'production-own-device-test'})
        self.assertEqual(result[0],200,result)
        due=result[2]['jobs'][0]['due'];sent=[]
        with connect(self.db) as c:push.tick(c,self.cfg,lambda sub,p,*a:sent.append(p) or 201,due)
        self.assertEqual(len(sent),1);self.assertEqual(sent[0]['owner'],self.owners[0])
        self.assertEqual(sent[0]['title'],'课间 · 测试提醒')
        self.assertEqual(sent[0]['url'],'notifications-reminders.html')
        self.assertNotIn('pilot',sent[0])

    def test_worker_recovery_is_reported_without_a_registered_browser_device(self):
        with connect(self.db) as c:c.execute('UPDATE push_worker_state SET heartbeat=0')
        self.assertFalse(self.api('reminder-settings')[2]['workerOnline'])
        with connect(self.db) as c:push.maintain(c)
        self.assertTrue(self.api('reminder-settings')[2]['workerOnline'])
