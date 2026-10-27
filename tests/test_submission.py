import unittest
import test_course_homework as fixtures
from classroom.app import connect
from classroom import homework


class SubmissionTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.CourseHomeworkTests(methodName='runTest')
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def test_shared_submission_can_be_updated_preserved_and_explicitly_cleared(self):
        f=self.fixture;f.setup_courses()
        task={'title':'虚构案例','notes':'阅读第一章','submission':'线下交到演示楼301','dueDate':'','dueTime':''}
        status,_,result=f.shared(task=task);self.assertEqual(status,200)
        first=result['next'];self.assertEqual(first['submission'],task['submission'])
        omitted={k:v for k,v in task.items() if k!='submission'}
        status,_,result=f.shared(expected=first['revision'],task=omitted);self.assertEqual(status,200)
        self.assertEqual(result['next']['submission'],task['submission'])
        status,_,result=f.shared(expected=result['next']['revision'],task={**omitted,'submission':''})
        self.assertEqual(status,200);self.assertEqual(result['next']['submission'],'')

    def test_personal_submission_keeps_notes_independent_and_is_member_scoped(self):
        f=self.fixture;f.save();task={**f.task(),'submission':'https://portal.example.test/submit'}
        with connect(f.db) as c:
            first=homework.change(c,f.owners[0],{'expected':None,'task':task})['next']
            self.assertEqual(first['notes'],task['notes']);self.assertEqual(first['submission'],task['submission'])
            self.assertEqual(homework.read(c,f.owners[1]),[])
            omitted={k:v for k,v in first.items() if k!='submission'}
            second=homework.change(c,f.owners[0],{'expected':first['revision'],'task':omitted})['next']
            self.assertEqual(second['submission'],task['submission'])
            third=homework.change(c,f.owners[0],{'expected':second['revision'],'task':{**second,'submission':''}})['next']
            self.assertEqual(third['submission'],'')
