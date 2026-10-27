import json
from classroom import push
from classroom.app import connect
from test_push_isolation import PushIsolationTests


class AccountRemoteTests(PushIsolationTests):
    def login(self,index=0,cookie=''):
        r=self.call('/api/login',{'student':'202600000'+str(index+1),'password':'test-password-123'},cookie=cookie)
        self.assertEqual(r[0],200,r)
        return r[1]['Set-Cookie'].split(';')[0]

    def test_mac_can_target_own_phone_from_a_separate_session_without_registering_mac(self):
        phone=self.bind(0,'my-iphone');mac=self.login()
        result=self.call('/api/push/account-status',{'owner':self.owners[0]},cookie=mac)
        self.assertEqual(result[0],200,result)
        self.assertEqual([d['id'] for d in result[2]['devices']],[phone])
        self.assertNotIn('subscription',json.dumps(result));self.assertNotIn('session_hash',json.dumps(result))
        body={'owner':self.owners[0],'deviceId':phone,'requestKey':'remote-iphone-test-key'}
        queued=self.call('/api/push/test-account',body,cookie=mac)
        self.assertEqual(queued[0],200,queued)
        again=self.call('/api/push/test-account',body,cookie=mac)
        job=queued[2]['devices'][0]['jobs'][0]
        self.assertEqual(again[2]['devices'][0]['jobs'][0]['id'],job['id'])
        sends=[]
        with connect(self.db) as c:push.tick(c,self.cfg,lambda sub,payload,*args:sends.append(payload['owner']) or 201,job['due'])
        self.assertEqual(sends,[self.owners[0]])

    def test_mac_switch_a_b_a_keeps_phone_binding_and_cannot_reuse_a_device_from_b(self):
        phone=self.bind(0,'my-iphone');before=self.business_snapshot();mac_a=self.login()
        mac_b=self.login(1,mac_a)
        status=self.call('/api/push/account-status',{'owner':self.owners[1]},cookie=mac_b)
        self.assertEqual(status[0],200);self.assertEqual(status[2]['devices'],[])
        forged={'owner':self.owners[1],'deviceId':phone,'requestKey':'forged-remote-phone-key'}
        self.assertEqual(self.call('/api/push/test-account',forged,cookie=mac_b)[0],403)
        self.assertEqual(self.call('/api/push/test-account',{**forged,'owner':self.owners[0]},cookie=mac_b)[0],403)
        mac_a2=self.login(0,mac_b)
        restored=self.call('/api/push/account-status',{'owner':self.owners[0]},cookie=mac_a2)
        self.assertEqual(restored[2]['devices'][0]['id'],phone)
        queued=self.call('/api/push/test-account',{'owner':self.owners[0],'deviceId':phone,'requestKey':'restored-remote-phone-key'},cookie=mac_a2)
        self.assertEqual(queued[0],200,queued)
        with connect(self.db) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM push_devices').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT active FROM push_devices').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT count(*) FROM push_jobs').fetchone()[0],1)
        self.assertEqual(self.call('/api/session',cookie=self.cookies[0])[2]['id'],self.owners[0])
        self.assertEqual(self.business_snapshot(),before)

    def test_b_with_a_phone_can_only_send_to_b_and_invalid_sessions_disappear(self):
        a=self.bind(0,'phone-a');b=self.bind(1,'phone-b');mac_b=self.login(1)
        status=self.call('/api/push/account-status',{'owner':self.owners[1]},cookie=mac_b)
        self.assertEqual([d['id'] for d in status[2]['devices']],[b])
        self.assertEqual(self.call('/api/push/test-account',{'owner':self.owners[1],'deviceId':a,'requestKey':'cannot-target-other-phone'},cookie=mac_b)[0],403)
        queued=self.call('/api/push/test-account',{'owner':self.owners[1],'deviceId':b,'requestKey':'only-target-own-phone'},cookie=mac_b)
        job=queued[2]['devices'][0]['jobs'][0];sent=[]
        with connect(self.db) as c:push.tick(c,self.cfg,lambda sub,payload,*args:sent.append(payload['owner']) or 201,job['due'])
        self.assertEqual(sent,[self.owners[1]])
        self.call('/api/logout',{'owner':self.owners[1]},cookie=self.cookies[1])
        status=self.call('/api/push/account-status',{'owner':self.owners[1]},cookie=mac_b)
        self.assertEqual(status[2]['devices'],[])

    def test_account_testing_preserves_csrf_and_sending_limits(self):
        phone=self.bind(0,'test-phone');mac=self.login()
        body={'owner':self.owners[0],'deviceId':phone,'requestKey':'csrf-remote-phone-key'}
        self.assertEqual(self.call('/api/push/test-account',body,cookie=mac,header=False)[0],403)
        self.assertEqual(self.call('/api/push/test-account',body,cookie=mac,origin='https://evil.example')[0],403)
        self.assertEqual(self.call('/api/push/test-account',{**body,'requestKey':'x'},cookie=mac)[0],400)
        first=self.call('/api/push/test-account',body,cookie=mac);self.assertEqual(first[0],200)
        self.assertEqual(self.call('/api/push/test-account',{**body,'requestKey':'different-pending-phone-key'},cookie=mac)[0],400)

    def test_already_queued_phone_notification_survives_sender_mac_switching_account(self):
        phone=self.bind(0,'persistent-iphone');mac_a=self.login()
        response=self.call('/api/push/test-account',{'owner':self.owners[0],'deviceId':phone,'requestKey':'queued-before-switch-key'},cookie=mac_a)
        self.assertEqual(response[0],200,response)
        job=response[2]['devices'][0]['jobs'][0]
        mac_b=self.login(1,mac_a);deliveries=[]
        with connect(self.db) as c:push.tick(c,self.cfg,lambda sub,payload,*args:deliveries.append(payload['owner']) or 201,job['due'])
        self.assertEqual(deliveries,[self.owners[0]])
        self.assertEqual(self.call('/api/push/account-status',{'owner':self.owners[1]},cookie=mac_b)[2]['devices'],[])
