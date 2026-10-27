from unittest.mock import patch
from classroom import push,update_notice
from classroom.app import connect,ClassroomApplication
from test_production_reminders import ProductionReminderTests

class UpdateNoticeTests(ProductionReminderTests):
    def test_notice_requires_login_and_acknowledgement_is_owner_scoped(self):
        self.assertEqual(self.call('/api/update-notice')[0],401)
        first=self.call('/api/update-notice',cookie=self.cookies[0])
        self.assertFalse(first[2]['seen'])
        body={'owner':self.owners[0],'notice':update_notice.NOTICE['id']}
        self.assertEqual(self.call('/api/update-notice',body,cookie=self.cookies[1])[0],403)
        self.assertEqual(self.call('/api/update-notice',body,cookie=self.cookies[0])[0],200)
        self.app=ClassroomApplication(self.db,origin='https://class.example',base='/mem/',push_config=self.cfg)
        self.assertTrue(self.call('/api/update-notice',cookie=self.cookies[0])[2]['seen'])
        self.assertFalse(self.call('/api/update-notice',cookie=self.cookies[1])[2]['seen'])

    def test_ack_is_idempotent_and_only_one_row_is_kept_for_each_member(self):
        body={'owner':self.owners[0],'notice':update_notice.NOTICE['id']}
        for _ in range(3):self.assertEqual(self.call('/api/update-notice',body,cookie=self.cookies[0])[0],200)
        with connect(self.db) as c:
            before=c.execute('SELECT count(*) FROM push_jobs').fetchone()[0]
            self.assertEqual(c.execute('SELECT count(*) FROM member_update_notices').fetchone()[0],1)
            with patch.dict(update_notice.NOTICE,{'id':'next-reviewed-feature'}):
                self.assertFalse(update_notice.current(c,self.owners[0])['seen'])
                update_notice.dismiss(c,self.owners[0],{**body,'notice':'next-reviewed-feature'})
                self.assertTrue(update_notice.current(c,self.owners[0])['seen'])
            self.assertEqual(c.execute('SELECT count(*) FROM member_update_notices').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT count(*) FROM push_jobs').fetchone()[0],before)

    def test_unknown_notice_is_rejected_without_marking_seen(self):
        result=self.call('/api/update-notice',{'owner':self.owners[0],'notice':'not-this-release'},cookie=self.cookies[0])
        self.assertEqual(result[0],409)
        self.assertFalse(self.call('/api/update-notice',cookie=self.cookies[0])[2]['seen'])

    def test_test_notification_is_scheduled_at_thirty_seconds(self):
        self.assertEqual(self.call('/api/push/config',cookie=self.cookies[0])[2]['delaySeconds'],30)
        with connect(self.db) as c:
            d=c.execute('SELECT * FROM push_devices WHERE id=?',(self.devices[0],)).fetchone()
            push.queue_test(c,self.owners[0],d,'notice-thirty-second-test',self.now)
            row=c.execute('SELECT due,created,expires FROM push_jobs WHERE request_key=?',('notice-thirty-second-test',)).fetchone()
            self.assertEqual(row['due']-row['created'],30)
            self.assertEqual(row['expires']-row['due'],300)
