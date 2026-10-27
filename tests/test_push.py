import base64
import json
import time
import unittest
from unittest.mock import patch
from classroom.app import ClassroomApplication, connect, digest
from classroom import push
import test_classroom as helpers


class PushTests(unittest.TestCase):
    tearDown=helpers.ClassroomTests.tearDown
    call=helpers.ClassroomTests.call

    def setUp(self):
        helpers.ClassroomTests.setUp(self)
        self.cfg={'environment':'testing','publicKey':'B'*87}
        self.app=ClassroomApplication(self.db,origin='https://class.example',base='/mem-test/',push_config=self.cfg)
        self.now=int(time.time())
        self.sub={'endpoint':'https://web.push.apple.com/fictional-device', 'keys':{
            'p256dh':base64.urlsafe_b64encode(b'\x04'+b'\x01'*64).decode().rstrip('='),
            'auth':base64.urlsafe_b64encode(b'\x02'*16).decode().rstrip('=')}}
        with connect(self.db) as c: push.tick(c,self.cfg,lambda *a:201,self.now)

    def api(self,action,b=None,index=0):
        return self.call('/api/push/'+action,{'owner':self.owners[index],**(b or {})},cookie=self.cookies[index])

    def register(self,index=0):
        r=self.api('register',{'subscription':self.sub,'label':'测试手机'},index)
        self.assertEqual(r[0],200,r)
        return r[2]['deviceId']

    def schedule(self,device,key='test-unique-request-key'):
        result=self.api('test',{'deviceId':device,'requestKey':key})
        self.assertEqual(result[0],200,result)
        return result[2]['jobs'][0]

    def test_feature_off_by_default_and_pilot_scope_required(self):
        with self.assertRaises(ValueError):ClassroomApplication(self.db,base='/mem/',push_config=self.cfg)
        self.app=ClassroomApplication(self.db,origin='https://class.example')
        self.assertEqual(self.call('/notifications.html')[0],404)
        self.assertEqual(self.call('/api/push/config',cookie=self.cookies[0])[0],404)

    def test_auth_csrf_owner_and_endpoint_validation(self):
        self.assertEqual(self.call('/api/push/config')[0],401)
        b={'owner':self.owners[0],'subscription':self.sub}
        self.assertEqual(self.call('/api/push/register',b,cookie=self.cookies[0],header=False)[0],403)
        self.assertEqual(self.call('/api/push/register',{**b,'owner':self.owners[1]},cookie=self.cookies[0])[0],403)
        for endpoint in ['http://web.push.apple.com/x','https://127.0.0.1/x','https://web.push.apple.com.evil.test/x','https://web.push.apple.com:444/x','https://a:password@web.push.apple.com/x']:
            self.assertEqual(self.api('register',{'subscription':{**self.sub,'endpoint':endpoint}})[0],400)
        device=self.register()
        self.assertEqual(self.api('test',{'deviceId':device,'requestKey':'cross-account-request'},1)[0],403)

    def test_queue_persists_and_repeated_request_does_not_duplicate(self):
        device=self.register();first=self.schedule(device)
        self.assertEqual(first['id'],self.schedule(device)['id'])
        self.assertEqual(self.api('test',{'deviceId':device,'requestKey':'second-pending-request'})[0],400)
        deliveries=[]
        with connect(self.db) as c:
            push.tick(c,self.cfg,lambda *a:deliveries.append(a) or 201,first['due']-1)
            self.assertEqual(deliveries,[])
        with connect(self.db) as c:
            push.tick(c,self.cfg,lambda *a:deliveries.append(a) or 201,first['due'])
            push.tick(c,self.cfg,lambda *a:deliveries.append(a) or 201,first['due']+2)
        self.assertEqual(len(deliveries),1)
        data=deliveries[0][1]
        self.assertTrue(data['pilot']);self.assertEqual(data['owner'],self.owners[0])
        self.assertEqual(data['url'],'notifications.html')
        result=self.api('status',{'deviceId':device})[2]
        self.assertNotIn('subscription',json.dumps(result))
        self.assertNotIn(data['receipt'],json.dumps(result))
        self.assertEqual(result['jobs'][0]['state'],'accepted')

    def test_receipts_require_current_account_and_confirmation_is_separate(self):
        device=self.register();job=self.schedule(device);sent=[]
        with connect(self.db) as c:push.tick(c,self.cfg,lambda *a:sent.append(a[1]) or 201,job['due'])
        b={k:sent[0][k] for k in ('id','receipt')}
        self.assertEqual(self.api('receipt',{**b,'stage':'received'},1)[0],403)
        self.assertTrue(self.api('receipt',{**b,'stage':'received'})[2]['display'])
        self.assertEqual(self.api('receipt',{**b,'stage':'shown'})[0],200)
        self.assertFalse(self.api('receipt',{**b,'stage':'received'})[2]['display'])
        status=self.api('status',{'deviceId':device})[2]['jobs'][0]
        self.assertIsNotNone(status['shown']);self.assertIsNone(status['confirmed'])
        self.assertEqual(self.api('confirm',{'deviceId':device,'id':job['id'],'received':True})[2]['jobs'][0]['confirmed'],1)

    def test_logout_cancels_and_stops_old_device(self):
        device=self.register();job=self.schedule(device)
        self.assertEqual(self.call('/api/logout',{'owner':self.owners[0]},cookie=self.cookies[0])[0],200)
        with connect(self.db) as c:
            push.tick(c,self.cfg,lambda *a:self.fail('Logged-out device received a push'),job['due'])
            self.assertEqual(c.execute('SELECT state FROM push_jobs').fetchone()[0],'cancelled')
            self.assertEqual(c.execute('SELECT active FROM push_devices').fetchone()[0],0)

    def test_rebinding_shared_device_does_not_send_old_account_jobs(self):
        device=self.register();job=self.schedule(device)
        self.assertEqual(device,self.register(1))
        with connect(self.db) as c:push.tick(c,self.cfg,lambda *a:self.fail('Old job sent after switching account'),job['due'])
        self.assertEqual(self.api('status',{'deviceId':device})[0],403)
        self.assertEqual(self.api('status',{'deviceId':device},1)[2]['jobs'],[])

    def test_expired_subscription_and_expired_job_are_not_retried(self):
        device=self.register();job=self.schedule(device)
        class Gone(Exception):status_code=410
        def gone(*a):raise Gone()
        with connect(self.db) as c:
            push.tick(c,self.cfg,gone,job['due'])
            self.assertEqual(c.execute('SELECT state FROM push_jobs').fetchone()[0],'subscription_expired')
        self.assertFalse(self.api('status',{'deviceId':device})[2]['enabled'])
        device=self.register();job=self.schedule(device,'second-expired-test')
        with connect(self.db) as c:push.tick(c,self.cfg,lambda *a:self.fail('Expired job sent'),job['expires']+1)
        self.assertEqual(self.api('status',{'deviceId':device})[2]['jobs'][0]['state'],'expired')

    def test_network_uncertainty_is_not_reported_as_success_or_blindly_retried(self):
        device=self.register();job=self.schedule(device)
        def failed(*a):raise TimeoutError('private endpoint must never be returned')
        with connect(self.db) as c:
            push.tick(c,self.cfg,failed,job['due'])
            push.tick(c,self.cfg,lambda *a:self.fail('Uncertain delivery was retried'),job['due']+20)
        result=self.api('status',{'deviceId':device})[2]
        self.assertEqual(result['jobs'][0]['state'],'unknown')
        self.assertNotIn('private endpoint',json.dumps(result))

    def test_configuration_error_is_failed_not_an_uncertain_network_delivery(self):
        device=self.register();job=self.schedule(device)
        def failed(*a):raise push.ConfigurationError('Do not expose credential details')
        with connect(self.db) as c:
            push.tick(c,self.cfg,failed,job['due'])
            push.tick(c,self.cfg,lambda *a:self.fail('Bad configuration was retried'),job['due']+20)
            row=c.execute('SELECT state,error,attempts FROM push_jobs').fetchone()
            self.assertEqual(tuple(row),('failed','CONFIGURATION_ERROR',1))
        result=self.api('status',{'deviceId':device})[2]
        self.assertEqual(result['jobs'][0]['state'],'failed')
        self.assertNotIn('credential',json.dumps(result))

    def test_service_restart_does_not_repeat_inflight_job(self):
        device=self.register();job=self.schedule(device)
        with connect(self.db) as c:
            c.execute("UPDATE push_jobs SET state='sending',updated=?",(job['due']-61,))
            push.tick(c,self.cfg,lambda *a:self.fail('Inflight job repeated'),job['due'])
        self.assertEqual(self.api('status',{'deviceId':device})[2]['jobs'][0]['state'],'unknown')


if __name__=='__main__':unittest.main()
