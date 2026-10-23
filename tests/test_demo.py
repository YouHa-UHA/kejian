from pathlib import Path
import tempfile
import unittest
from classroom.demo import seed,DEMO_MEMBERS
from classroom.app import connect
from classroom import community,course_homework,course_store
from production import FILES,PUBLIC


class DemoTests(unittest.TestCase):
    def test_fictional_seed_roles_teaching_classes_and_private_completion(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Path(folder)/'demo.sqlite3'
            self.assertTrue(seed(db))
            with connect(db) as c:
                members=[c.execute('SELECT id FROM members WHERE student=?',(s,)).fetchone()[0] for s,_ in DEMO_MEMBERS]
                self.assertTrue(community.roles(c,members[0])['admin'])
                key=community.roles(c,members[2])['representativeOf'][0]
                cards=community.library(c,members[3])['courses']
                systems=[x for x in cards if x['name']=='系统工程']
                self.assertEqual(len(systems),2)
                self.assertEqual(systems[0]['teacher'],systems[1]['teacher'])
                self.assertNotEqual(systems[0]['key'],systems[1]['key'])
                a=course_homework.feed(c,members[1])['items']
                b=course_homework.feed(c,members[4])['items']
                self.assertEqual([x['id'] for x in a],['coursework-demo-a'])
                self.assertEqual([x['id'] for x in b],['coursework-demo-b'])
                self.assertEqual(a[0]['offeringKey'],key)
                self.assertEqual(course_store.read_schedule(c,members[3])['courses'],[])
                before=[tuple(r) for r in c.execute('SELECT * FROM members')]
            self.assertFalse(seed(db))
            with connect(db) as c:
                self.assertEqual([tuple(r) for r in c.execute('SELECT * FROM members')],before)

    def test_public_static_allowlist_has_only_existing_assets(self):
        for filename,_ in FILES.values():
            self.assertTrue((PUBLIC/filename).is_file(),filename)
        for private in ('/classroom/app.py','/examples/demo-schedule.json','/state/demo.sqlite3','/reminders.html','/push-test.html','/wechat-test.html'):
            self.assertNotIn(private,FILES)


if __name__=='__main__':unittest.main()
