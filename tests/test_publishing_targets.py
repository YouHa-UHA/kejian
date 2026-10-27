import json
import unittest
from unittest.mock import patch
from classroom.app import connect
from classroom import agent_mcp
import test_agent as agent_helpers
import test_mcp as mcp_helpers


class PublishingTargetTests(unittest.TestCase):
    tearDown=agent_helpers.AgentTests.tearDown
    call=agent_helpers.AgentTests.call
    save=agent_helpers.AgentTests.save
    op=agent_helpers.AgentTests.op
    admin=agent_helpers.AgentTests.admin
    publish=agent_helpers.AgentTests.publish
    manage=agent_helpers.AgentTests.manage
    issue=agent_helpers.AgentTests.issue
    ai=agent_helpers.AgentTests.ai
    mcp=mcp_helpers.MCPTests.mcp
    tool=mcp_helpers.MCPTests.tool

    def setUp(self):
        agent_helpers.AgentTests.setUp(self)
        # Two different teaching classes with the very same name and teacher.
        self.text=self.text.replace('线上英语','系统工程').replace('另一教师','测试教师')
        self.keys={r['courseId']:r['key'] for r in self.publish()}
        self.cfg=self.issue()
        base=self.op({'action':'inspect'})[2]['base']
        self.assertEqual(self.op({'action':'remove','courseId':'class-b','base':base})[0],200)
        self.save(index=1,selected=['class-b'])

    def payload(self,course='class-a',ident='coursework-target-test'):
        return {'action':'save','key':self.keys[course],'id':ident,'expected':None,
                'task':{'title':'系统工程阅读第一章','notes':'阅读并整理系统边界与环境，不需要提交小组报告。','dueDate':'2026-10-30','dueTime':''}}

    def counts(self):
        with connect(self.db) as c:
            return {r['offering']:r['n'] for r in c.execute('SELECT offering,count(*) AS n FROM teaching_homework GROUP BY offering')}

    def test_admin_own_class_is_preferred_and_one_write_never_broadcasts(self):
        caps=self.ai(self.cfg,'/capabilities')[1]['data']
        self.assertEqual(len(caps['editableCourses']),2)
        self.assertEqual([c['courseId'] for c in caps['preferredPublishCourses']],['class-a'])
        first=self.ai(self.cfg,'/course-homework',self.payload())
        self.assertEqual(first[0],200,first)
        self.assertEqual(first[1]['data']['task']['offeringKey'],self.keys['class-a'])
        self.assertTrue(self.ai(self.cfg,'/course-homework',self.payload())[1]['replayed'])
        self.assertEqual(self.counts(),{self.keys['class-a']:1})
        self.assertEqual(self.call('/api/homework',cookie=self.cookies[1])[2]['items'],[])

    def test_external_class_missing_or_wrong_confirmation_never_writes(self):
        for confirmation in [None,'class-a','*']:
            b=self.payload('class-b')
            if confirmation is not None:b['confirmedCourseId']=confirmation
            status,response=self.ai(self.cfg,'/course-homework',b,key='external-'+str(confirmation))
            self.assertEqual(status,409,response)
        status,response=self.ai(self.cfg,'/course-homework',{**self.payload(),'key':list(self.keys.values())})
        self.assertEqual(status,403,response)
        self.assertEqual(self.counts(),{})

    def test_explicit_external_class_can_be_managed_without_changing_own_class(self):
        b={**self.payload('class-b'),'confirmedCourseId':'class-b'}
        status,result=self.ai(self.cfg,'/course-homework',b)
        self.assertEqual(status,200,result)
        self.assertEqual(self.counts(),{self.keys['class-b']:1})
        t=result['data']['task']
        moved={**b,'key':self.keys['class-a'],'confirmedCourseId':'class-a','expected':t['revision']}
        self.assertEqual(self.ai(self.cfg,'/course-homework',moved,key='wrong-teaching-class')[0],403)
        self.assertEqual(self.counts(),{self.keys['class-b']:1})

    def test_mcp_enforces_same_guard_and_exposes_updated_parameter(self):
        tools=self.mcp(self.cfg)[2]['result']['tools']
        spec=next(t for t in tools if t['name']=='kejian_manage_course_homework')
        self.assertIn('confirmedCourseId',spec['inputSchema']['properties'])
        blocked=self.tool(self.cfg,'kejian_manage_course_homework',{**self.payload('class-b'),'idempotencyKey':'mcp-other-class'})
        self.assertTrue(blocked['isError'])
        self.assertIn('TEACHING_CLASS_CONFIRMATION_REQUIRED',json.dumps(blocked))
        self.assertEqual(self.counts(),{})
        success=self.tool(self.cfg,'kejian_manage_course_homework',{**self.payload(),'idempotencyKey':'mcp-own-class'})
        self.assertFalse(success.get('isError',False),success)
        self.assertEqual(self.counts(),{self.keys['class-a']:1})

    def test_existing_connection_gets_new_rules_silently_on_next_sync(self):
        with patch.object(agent_mcp,'skill_document',return_value={'name':'kejian','revision':'old-skill','text':'old rules'}):
            old=self.ai(self.cfg,'/discovery')[1]['sync']['versions']['context']
        result=self.ai(self.cfg,'/discovery',extra={'HTTP_X_KEJIAN_CONTEXT_REVISION':old})[1]
        self.assertTrue(result['sync']['changed'])
        self.assertIn('confirmedCourseId',result['updates']['skill']['text'])
        self.assertEqual(result['updates']['capabilities']['preferredPublishCourses'][0]['courseId'],'class-a')
        fresh=result['sync']['versions']['context']
        again=self.ai(self.cfg,'/discovery',extra={'HTTP_X_KEJIAN_CONTEXT_REVISION':fresh})[1]
        self.assertFalse(again['sync']['changed'])
        self.assertNotIn('updates',again)
