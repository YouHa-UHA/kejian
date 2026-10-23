import unittest
import test_classroom as helpers
import test_agent as agent_helpers
from classroom.app import connect


class PasswordTests(unittest.TestCase):
    setUp=helpers.ClassroomTests.setUp
    tearDown=helpers.ClassroomTests.tearDown
    call=helpers.ClassroomTests.call
    issue=agent_helpers.AgentTests.issue
    ai=agent_helpers.AgentTests.ai

    def payload(self,**patch):
        return {'owner':self.owners[0],'currentPassword':'test-password-123','newPassword':'changed-password-456','confirmPassword':'changed-password-456',**patch}

    def test_change_rotates_sessions_keeps_data_and_other_members_and_ai(self):
        cfg=self.issue()
        second=self.call('/api/login',payload={'student':'2026000001','password':'test-password-123'})[1]['Set-Cookie'].split(';')[0]
        result=self.call('/api/password',payload=self.payload(),cookie=self.cookies[0]);self.assertEqual(result[0],200,result)
        fresh=result[1]['Set-Cookie'].split(';')[0]
        self.assertNotEqual(fresh,self.cookies[0]);self.assertIn('HttpOnly',result[1]['Set-Cookie']);self.assertIn('Secure',result[1]['Set-Cookie'])
        self.assertEqual(self.call('/api/session',cookie=fresh)[0],200)
        for old in (self.cookies[0],second):self.assertEqual(self.call('/api/session',cookie=old)[0],401)
        self.assertEqual(self.call('/api/session',cookie=self.cookies[1])[0],200)
        self.assertEqual(self.call('/api/login',payload={'student':'2026000001','password':'test-password-123'})[0],401)
        self.assertEqual(self.call('/api/login',payload={'student':'2026000001','password':'changed-password-456'})[0],200)
        self.assertEqual(self.ai(cfg)[0],200)
        with connect(self.db) as c:
            dump='\n'.join(c.iterdump());self.assertNotIn('changed-password-456',dump)
        self.assertEqual(self.ai(cfg,'/password',self.payload())[0],403)

    def test_wrong_current_password_validation_csrf_and_owner_never_change_password(self):
        for patch in ({'currentPassword':'wrong-password'},{'newPassword':'short','confirmPassword':'short'},{'confirmPassword':'not-matching'},
                      {'newPassword':'test-password-123','confirmPassword':'test-password-123'},{'newPassword':' '*8,'confirmPassword':' '*8}):
            self.assertEqual(self.call('/api/password',payload=self.payload(**patch),cookie=self.cookies[0])[0],400)
        self.assertEqual(self.call('/api/password',payload=self.payload())[0],401)
        self.assertEqual(self.call('/api/password',payload=self.payload(),cookie=self.cookies[0],origin='https://evil.example')[0],403)
        self.assertEqual(self.call('/api/password',payload=self.payload(owner=self.owners[1]),cookie=self.cookies[0])[0],403)
        self.assertEqual(self.call('/api/login',payload={'student':'2026000001','password':'test-password-123'})[0],200)

    def test_failed_attempts_rate_limit_and_stale_session_cannot_change_again(self):
        for _ in range(5):self.assertEqual(self.call('/api/password',payload=self.payload(currentPassword='wrong-password'),cookie=self.cookies[0])[0],400)
        self.assertEqual(self.call('/api/password',payload=self.payload(),cookie=self.cookies[0])[0],429)
        self.assertEqual(self.call('/api/session',cookie=self.cookies[0])[0],200)

if __name__=='__main__':unittest.main()
