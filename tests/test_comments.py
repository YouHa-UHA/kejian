import unittest
from unittest.mock import patch
import test_mcp as mcp_tests
from classroom.app import connect
from classroom import comments, agent_mcp, agent
import test_course_homework as course_tests
import test_agent as agent_tests


class DiscussionTests(unittest.TestCase):
    setUp=course_tests.CourseHomeworkTests.setUp
    tearDown=course_tests.CourseHomeworkTests.tearDown
    call=course_tests.CourseHomeworkTests.call
    op=course_tests.CourseHomeworkTests.op
    save=course_tests.CourseHomeworkTests.save
    admin=course_tests.CourseHomeworkTests.admin
    manage=course_tests.CourseHomeworkTests.manage
    publish=course_tests.CourseHomeworkTests.publish
    task=course_tests.CourseHomeworkTests.task
    setup_courses=course_tests.CourseHomeworkTests.setup_courses
    shared=course_tests.CourseHomeworkTests.shared
    issue=agent_tests.AgentTests.issue
    ai=agent_tests.AgentTests.ai
    mcp=mcp_tests.MCPTests.mcp
    tool=mcp_tests.MCPTests.tool

    def setup_discussion(self):
        self.setup_courses();self.shared();self.save(index=1)
        return {'action':'create','homework':'coursework-example-1','id':'comment-test-1','body':'需要附原始数据吗？','expected':None}

    def post(self,b,index=1):
        return self.call('/api/homework-comments',payload={'owner':self.owners[index],**b},cookie=self.cookies[index])

    def read(self,index=1,suffix=''):
        return self.call('/api/homework-comments?homework=coursework-example-1'+suffix,cookie=self.cookies[index])

    def test_web_reply_edit_delete_preserves_relations(self):
        b=self.setup_discussion();first=self.post(b);self.assertEqual(first[0],200,first)
        self.assertEqual(self.post(b)[0],200)
        self.assertEqual(self.read()[2]['total'],1)
        reply=self.post({**b,'id':'comment-reply','replyTo':b['id'],'body':'请附数据来源。'},0)[2]['comment']
        self.assertEqual(self.post({**b,'action':'edit','expected':'stale'})[0],409)
        changed=self.post({**b,'action':'edit','expected':first[2]['comment']['revision'],'body':'是否要附原始数据和计算表？'})
        self.assertEqual(changed[0],200)
        deleted=self.post({**b,'action':'delete','expected':changed[2]['comment']['revision']})
        self.assertEqual(deleted[0],200)
        listing=self.read()[2];self.assertTrue(listing['items'][0]['deleted']);self.assertEqual(listing['items'][0]['body'],'')
        self.assertEqual(listing['items'][1]['replyTo'],b['id']);self.assertEqual(listing['total'],1)
        with connect(self.db) as c:self.assertEqual(c.execute('SELECT body FROM homework_comments WHERE id=?',(b['id'],)).fetchone()[0],'')

    def test_private_outsider_csrf_and_other_author_are_blocked(self):
        b=self.setup_discussion();first=self.post(b)[2]['comment']
        # An administrator may moderate, but cannot edit another person's words.
        self.assertEqual(self.post({**b,'action':'edit','expected':first['revision']},0)[0],403)
        self.assertEqual(self.post({**b,'homework':'personal-task'},0)[0],403)
        self.assertEqual(self.call('/api/homework-comments?homework=coursework-example-1')[0],401)
        self.assertEqual(self.call('/api/homework-comments',payload={'owner':self.owners[1],**b},cookie=self.cookies[1],origin='https://evil.test')[0],403)
        base=self.op({'action':'inspect'},1)[2]['base'];self.op({'action':'clear','base':base},1)
        self.assertEqual(self.read()[0],403);self.assertEqual(self.post(b)[0],403)

    def test_representative_moderation_and_withdrawal(self):
        b=self.setup_discussion();first=self.post(b,0)[2]['comment']
        self.assertEqual(self.post({**b,'action':'delete','expected':first['revision']})[0],403)
        self.manage({'action':'representative-add','key':self.keys['class-a'],'member':self.owners[1]})
        data=self.read()[2];self.assertEqual(data['representatives'],[{'id':self.owners[1],'name':'测试乙'}])
        self.assertNotIn('student',data['items'][0])
        self.assertEqual(self.post({**b,'action':'delete','expected':first['revision']})[0],200)
        current=self.call('/api/course-homework?course='+self.keys['class-a'],cookie=self.cookies[0])[2]['items'][0]
        self.shared('delete',expected=current['revision'])
        self.assertEqual(self.read()[0],409);self.assertEqual(self.post({**b,'id':'comment-new'})[0],409)

    def test_pagination_bad_reply_and_limits(self):
        b=self.setup_discussion()
        self.assertEqual(self.post({**b,'body':' '})[0],400)
        self.assertEqual(self.post({**b,'body':'x'*4001})[0],400)
        self.assertEqual(self.post({**b,'replyTo':'comment-missing'})[0],400)
        self.shared(id='coursework-another-task')
        elsewhere={**b,'id':'comment-elsewhere','homework':'coursework-another-task'}
        self.assertEqual(self.post(elsewhere)[0],200)
        self.assertEqual(self.post({**b,'replyTo':elsewhere['id']})[0],400)
        with connect(self.db) as c:
            for i in range(53):comments.change(c,self.owners[1],{**b,'id':f'comment-page-{i}'})
        first=self.read()[2];self.assertEqual(len(first['items']),50);self.assertIsNotNone(first['nextCursor'])
        second=self.read(suffix='&after='+first['nextCursor'])[2];self.assertEqual(len(second['items']),3);self.assertIsNone(second['nextCursor'])
        self.assertEqual(self.read(suffix='&after=invalid')[0],400)

    def test_ai_discovery_mcp_contract_and_permission_revocation_before_replay(self):
        b=self.setup_discussion();cfg=self.issue(1)
        discovery=self.ai(cfg,'/discovery')[1]['data'];self.assertIn('/homework-comments',discovery['capabilities']['writeOperations'])
        tool=next(t for t in agent_mcp.tools(discovery['capabilities'],cfg['apiBase']) if t['name']=='kejian_comment_homework')
        agent_mcp.validate({**b,'idempotencyKey':'comment-test-request'},tool['inputSchema'])
        first=self.ai(cfg,'/homework-comments',b);self.assertEqual(first[0],200,first)
        self.assertTrue(self.ai(cfg,'/homework-comments',b)[1]['replayed'])
        self.assertEqual(self.ai(cfg,'/homework-comments?homework='+b['homework'])[1]['data']['total'],1)
        self.assertEqual(self.ai(cfg,'/homework-comments',{**b,'member':self.owners[0]})[0],403)
        base=self.op({'action':'inspect'},1)[2]['base'];self.op({'action':'clear','base':base},1)
        self.assertEqual(self.ai(cfg,'/homework-comments',b)[0],403)
        self.assertEqual(self.ai(cfg,'/homework-comments?homework='+b['homework'])[0],403)

    def test_mcp_comment_write_reads_exact_record_beyond_first_page(self):
        b=self.setup_discussion();cfg=self.issue(1)
        with connect(self.db) as c:
            for i in range(51):comments.change(c,self.owners[0],{**b,'id':f'comment-before-{i}'})
        result=self.tool(cfg,'kejian_comment_homework',{**b,'idempotencyKey':'mcp-comment-first'})
        self.assertFalse(result['isError'],result)
        self.assertTrue(result['structuredContent']['verification']['verified'])
        verified=result['structuredContent']['verification']['data']['items']
        self.assertEqual([x['id'] for x in verified],[b['id']])
        self.assertEqual(verified[0]['author'],'测试乙')
        self.assertTrue(self.tool(cfg,'kejian_comment_homework',{**b,'idempotencyKey':'mcp-comment-first'})['structuredContent']['replayed'])

    def test_existing_token_discovers_added_comment_tools_and_skill(self):
        b=self.setup_discussion();cfg=self.issue(1)
        with patch.dict(agent.READS,{k:v for k,v in agent.READS.items() if k!='/homework-comments'},clear=True), patch.dict(agent.WRITES,{k:v for k,v in agent.WRITES.items() if k!='/homework-comments'},clear=True):
            before=self.ai(cfg,'/discovery')[1]
        after=self.ai(cfg,'/discovery',extra={'HTTP_X_KEJIAN_CONTEXT_REVISION':before['sync']['versions']['context']})[1]
        self.assertTrue(after['sync']['changed'])
        self.assertNotEqual(before['sync']['versions']['features'],after['sync']['versions']['features'])
        self.assertIn('/homework-comments',after['data']['capabilities']['writeOperations'])
        self.assertEqual(after['data']['identity']['connection']['id'],cfg['connectionId'])

if __name__=='__main__':unittest.main()
