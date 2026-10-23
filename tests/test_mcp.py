from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid
import zipfile

from classroom import agent, agent_mcp
from classroom.app import connect
import test_agent as agent_helpers


class MCPTests(unittest.TestCase):
    setUp = agent_helpers.AgentTests.setUp
    tearDown = agent_helpers.AgentTests.tearDown
    call = agent_helpers.AgentTests.call
    save = agent_helpers.AgentTests.save
    op = agent_helpers.AgentTests.op
    admin = agent_helpers.AgentTests.admin
    publish = agent_helpers.AgentTests.publish
    manage = agent_helpers.AgentTests.manage
    task = agent_helpers.AgentTests.task
    issue = agent_helpers.AgentTests.issue
    ai = agent_helpers.AgentTests.ai

    def mcp(self, config, method='tools/list', params=None, extra=None, ident=1, raw=None, verb='POST'):
        request = {'jsonrpc': '2.0', 'method': method, 'params': params or {}}
        if ident is not None:
            request['id'] = ident
        data = raw if raw is not None else json.dumps(request).encode()
        env = {'PATH_INFO': agent_mcp.PREFIX, 'REQUEST_METHOD': verb, 'CONTENT_TYPE': 'application/json',
            'CONTENT_LENGTH': str(len(data)), 'wsgi.input': BytesIO(data),
            'HTTP_AUTHORIZATION': 'Bearer ' + config['token'] if config else '',
            'HTTP_ACCEPT': 'application/json, text/event-stream', 'HTTP_HOST': 'class.example', **(extra or {})}
        captured = {}
        result = b''.join(self.app(env, lambda s, h: captured.update(status=int(s[:3]), headers=dict(h))))
        return captured['status'], captured['headers'], json.loads(result) if result else None

    def tool(self, config, name, args=None):
        status, _, value = self.mcp(config, 'tools/call', {'name': name, 'arguments': args or {}})
        self.assertEqual(status, 200, value)
        return value['result']

    def test_handshake_authorization_transport_and_private_config(self):
        cfg = self.issue()
        status, _, response = self.mcp(cfg, 'initialize', {'protocolVersion': '2025-11-25',
            'capabilities': {}, 'clientInfo': {'name': 'independent-test', 'version': '1'}})
        self.assertEqual(status, 200)
        self.assertEqual(response['result']['protocolVersion'], '2025-11-25')
        self.assertFalse(response['result']['capabilities']['tools']['listChanged'])
        self.assertEqual(self.mcp(cfg, 'notifications/initialized', ident=None)[::2], (202, None))
        self.assertEqual(self.mcp(cfg, 'ping')[2]['result'], {})
        for verb in ('GET', 'DELETE', 'HEAD'):
            self.assertEqual(self.mcp(cfg, verb=verb)[0], 405)
        self.assertEqual(self.mcp(None, extra={'HTTP_COOKIE': self.cookies[0]})[0], 401)
        self.assertIn('WWW-Authenticate', self.mcp(None)[1])
        self.assertEqual(self.mcp(cfg, extra={'HTTP_ORIGIN': 'https://evil.example'})[0], 403)
        self.assertEqual(self.mcp(cfg, extra={'HTTP_HOST': 'evil.example'})[0], 403)
        self.assertEqual(self.mcp(cfg, extra={'QUERY_STRING': 'token=private'})[0], 400)
        self.assertEqual(self.mcp(cfg, extra={'HTTP_ACCEPT': 'application/json'})[0], 406)
        self.assertEqual(self.mcp(cfg, extra={'HTTP_MCP_PROTOCOL_VERSION': 'unknown'})[0], 400)
        self.assertEqual(self.mcp(cfg, extra={'CONTENT_TYPE': 'text/plain'})[0], 415)
        self.assertEqual(self.mcp(cfg, raw=b'{')[2]['error']['code'], -32700)
        self.assertEqual(self.mcp(cfg, raw=b'[]')[2]['error']['code'], -32600)
        self.assertEqual(self.mcp(cfg, 'unsupported')[2]['error']['code'], -32601)
        self.assertEqual(self.mcp(cfg, 'initialize')[2]['error']['code'], -32602)

    def test_mcp_uses_same_identity_as_api_ignoring_browser_cookie(self):
        self.save()
        cfg = self.issue(1)
        result = self.mcp(cfg, 'tools/call', {'name': 'kejian_schedule'}, extra={'HTTP_COOKIE': self.cookies[0]})[2]['result']
        self.assertFalse(result['isError'])
        self.assertEqual(result['structuredContent']['data']['owner'], self.owners[1])
        self.assertEqual(result['structuredContent']['data']['courses'], [])
        before = self.ai(cfg, '/me')[1]['data']
        current = self.tool(cfg, 'kejian_context')['structuredContent']['data']
        self.assertEqual(before, current['identity'])
        self.assertIn('availableTools', current)
        for args in ({'owner': self.owners[0]}, {'member': self.owners[0]}, {'date': 4}, {'student': '2026000001'}):
            self.assertTrue(self.tool(cfg, 'kejian_today', args)['isError'])
        self.assertNotIn('kejian_manage_class', {x['name'] for x in current['availableTools']})
        denied = self.tool(cfg, 'kejian_manage_class', {'action': 'publish', 'courses': [], 'idempotencyKey': 'student-admin'})
        self.assertTrue(denied['isError'])
        self.assertEqual(denied['structuredContent']['status'], 403)

    def test_personal_write_verified_idempotent_and_other_person_unchanged(self):
        self.save()
        cfg = self.issue()
        body = {'task': self.task(), 'expected': None, 'idempotencyKey': 'mcp-personal-001'}
        first = self.tool(cfg, 'kejian_save_homework', body)
        self.assertFalse(first['isError'])
        self.assertTrue(first['structuredContent']['verification']['verified'])
        self.assertEqual(first['structuredContent']['verification']['data']['items'][0]['title'], self.task()['title'])
        replay = self.tool(cfg, 'kejian_save_homework', body)
        self.assertTrue(replay['structuredContent']['replayed'])
        changed = self.tool(cfg, 'kejian_save_homework', {**body, 'task': {**self.task(), 'title': '不应覆盖'}})
        self.assertTrue(changed['isError'])
        self.assertEqual(changed['structuredContent']['status'], 409)
        with connect(self.db) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM course_homework').fetchone()[0], 1)
        self.assertEqual(self.call('/api/homework', cookie=self.cookies[1])[2]['items'], [])
        # Original API access and secret remain valid after MCP use.
        self.assertEqual(self.ai(cfg, '/homework')[1]['data']['items'][0]['title'], self.task()['title'])

    def test_representative_upgrade_downgrade_and_cached_tools_cannot_bypass_permissions(self):
        cards = self.publish()
        self.save(index=1)
        key = next(x['key'] for x in cards if x['courseId'] == 'class-a')
        other = next(x['key'] for x in cards if x['courseId'] == 'class-b')
        cfg = self.issue(1)
        before = self.tool(cfg, 'kejian_context')['structuredContent']
        self.manage({'action': 'representative-add', 'key': key, 'member': self.owners[1]})
        after = self.tool(cfg, 'kejian_context', {'contextRevision': before['sync']['versions']['context']})['structuredContent']
        self.assertNotEqual(before['data']['toolsRevision'], after['data']['toolsRevision'])
        self.assertEqual(after['updates']['capabilities']['editableCourses'][0]['key'], key)
        body = {'action': 'save', 'id': 'coursework-mcp-publish', 'key': key, 'expected': None,
            'task': {'title': '阅读第一章', 'notes': '说明系统边界', 'dueDate': '2026-10-30', 'dueTime': ''},
            'idempotencyKey': 'representative-publish'}
        result = self.tool(cfg, 'kejian_manage_course_homework', body)
        self.assertFalse(result['isError'])
        self.assertTrue(result['structuredContent']['verification']['verified'])
        wrong = self.tool(cfg, 'kejian_manage_course_homework', {**body, 'key': other, 'id': 'coursework-wrong', 'idempotencyKey': 'wrong-teaching-class'})
        self.assertTrue(wrong['isError'])
        self.assertEqual(wrong['structuredContent']['status'], 403)
        self.manage({'action': 'representative-remove', 'key': key, 'member': self.owners[1]})
        # Even a cached full tool schema/replayed request loses publishing access.
        denied = self.tool(cfg, 'kejian_manage_course_homework', body)
        self.assertTrue(denied['isError'])
        current = self.tool(cfg, 'kejian_context')['structuredContent']['data']
        self.assertEqual(current['capabilities']['editableCourses'], [])
        self.assertNotIn('kejian_manage_class', {x['name'] for x in current['availableTools']})
        with connect(self.db) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM teaching_homework').fetchone()[0], 1)

    def test_import_preview_merge_and_latest_guides_without_new_credential(self):
        cfg = self.issue()
        initial = self.tool(cfg, 'kejian_context')['structuredContent']
        guide = self.tool(cfg, 'kejian_import_guide')['structuredContent']['data']
        self.assertEqual(guide, self.ai(cfg, '/import-guide')[1]['data'])
        preview = self.tool(cfg, 'kejian_import_timetable', {'text': self.text, 'action': 'preview', 'idempotencyKey': 'preview-mcp-import'})
        self.assertFalse(preview['isError'])
        self.assertEqual(self.call('/api/schedule', cookie=self.cookies[0])[2]['courses'], [])
        body = {'text': self.text, 'action': 'save', 'base': preview['structuredContent']['data']['base'], 'idempotencyKey': 'save-mcp-import'}
        saved = self.tool(cfg, 'kejian_import_timetable', body)
        self.assertEqual(len(saved['structuredContent']['verification']['data']['courses']), 2)
        again = self.tool(cfg, 'kejian_import_timetable', {'text': self.text, 'idempotencyKey': 'preview-again-import'})
        self.assertTrue(all(x['kind'] == '未变化' for x in again['structuredContent']['data']['changes']))
        old = agent.guide()
        with patch('classroom.agent.guide', return_value=old + '\n更新的在线规则'):
            refreshed = self.tool(cfg, 'kejian_context', {'contextRevision': initial['sync']['versions']['context']})['structuredContent']
            self.assertIn('更新的在线规则', refreshed['updates']['guide']['text'])
            resource = self.mcp(cfg, 'resources/read', {'uri': 'kejian://guide'})[2]['result']
            self.assertIn('更新的在线规则', resource['contents'][0]['text'])
        self.assertEqual(self.ai(cfg, '/me')[0], 200)

    def test_delete_rotate_disable_invalidate_both_entrypoints(self):
        cfg = self.issue()
        connection = self.call('/api/ai-connections', cookie=self.cookies[0])[2]['connections'][0]
        body = {'owner': self.owners[0], 'action': 'rotate', 'id': connection['id'], 'expected': connection['revision']}
        raw = self.call('/api/ai-connections', payload=body, cookie=self.cookies[0])[2]
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            fresh = json.loads(archive.read('connection.json'))
        self.assertEqual(self.mcp(cfg)[0], 401)
        self.assertEqual(self.ai(cfg)[0], 401)
        self.assertEqual(self.mcp(fresh)[0], 200)
        connection = self.call('/api/ai-connections', cookie=self.cookies[0])[2]['connections'][0]
        body.update(action='delete', expected=connection['revision'])
        self.assertEqual(self.call('/api/ai-connections', payload=body, cookie=self.cookies[0])[0], 200)
        self.assertEqual(self.mcp(fresh)[0], 401)
        active = self.issue()
        with connect(self.db) as c:
            c.execute('UPDATE members SET disabled=1 WHERE id=?', (self.owners[0],))
        self.assertEqual(self.mcp(active)[0], 401)

    def test_package_contains_real_mcp_and_secret_free_skill(self):
        status, _, raw = self.call('/api/ai-connections', payload={'owner': self.owners[0], 'action': 'create',
            'name': 'MCP包测试', 'requestKey': str(uuid.uuid4())}, cookie=self.cookies[0])
        self.assertEqual(status, 200)
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            config = json.loads(archive.read('connection.json'))
            mcp = json.loads(archive.read('mcp.json'))['mcpServers']['kejian']
            self.assertEqual(mcp['url'], 'https://class.example/mem/api/mcp')
            self.assertEqual(mcp['headers']['Authorization'], 'Bearer ' + config['token'])
            skill = archive.read('skills/kejian/SKILL.md').decode()
            self.assertNotIn(config['token'], skill)
            self.assertIn('name: kejian', skill)
            self.assertIn('kejian_context', skill)
            self.assertEqual(archive.getinfo('mcp.json').external_attr >> 16 & 0o777, 0o600)
            self.assertIn('默认方式：普通API + 统一Skill', archive.read('START-HERE.txt').decode())
            manifest = json.loads(archive.read('manifest.json'))
            self.assertEqual(manifest['preferred'], 'api+skill')
            self.assertEqual(manifest['formatVersion'], 3)
            self.assertIn('kejian_runtime.py',archive.namelist())
            self.assertNotIn(config['token'],archive.read('kejian_runtime.py').decode())
        self.assertEqual(self.mcp(config)[0], 200)

    def test_online_skill_updates_are_visible_to_existing_mcp_and_api_connections(self):
        cfg = self.issue()
        original = self.tool(cfg, 'kejian_context')['structuredContent']
        methods = original['data']['connectionMethods']
        self.assertEqual(methods['mcp']['url'], 'https://class.example/mem/api/mcp')
        self.assertEqual(methods['skill']['path'], '/skill')
        skill = agent_mcp.skill_document()
        updated = {**skill, 'text': skill['text'] + '\n新的课程重点整理规则'}
        updated['revision'] = agent.digest(updated['text'])
        with patch('classroom.agent_mcp.skill_document', return_value=updated):
            result = self.tool(cfg, 'kejian_context', {'contextRevision': original['sync']['versions']['context']})['structuredContent']
            self.assertTrue(result['sync']['changed'])
            self.assertNotEqual(result['sync']['versions']['skill'], original['sync']['versions']['skill'])
            self.assertIn('新的课程重点整理规则', result['updates']['skill']['text'])
            existing_api = self.ai(cfg, '/discovery', extra={'HTTP_X_KEJIAN_CONTEXT_REVISION': original['sync']['versions']['context']})[1]
            self.assertEqual(existing_api['updates']['skill'], updated)
            self.assertEqual(self.ai(cfg, '/skill')[1]['data'], updated)
        self.assertEqual(self.ai(cfg, '/me')[1]['data']['connection']['id'], cfg['connectionId'])

    def test_write_committed_but_readback_failed_does_not_claim_write_failure(self):
        self.save()
        cfg = self.issue()
        original = agent.handle
        def fail_readback(app, c, env, body):
            if env['PATH_INFO'] == agent.PREFIX + '/homework' and env['REQUEST_METHOD'] == 'GET':
                raise agent.AgentError(503, 'TEMPORARY', '暂时无法回读')
            return original(app, c, env, body)
        with patch('classroom.agent.handle', side_effect=fail_readback):
            result = self.tool(cfg, 'kejian_save_homework', {'task': self.task(), 'expected': None, 'idempotencyKey': 'readback-failure'})
        self.assertFalse(result['isError'])
        self.assertFalse(result['structuredContent']['verification']['verified'])
        self.assertEqual(self.ai(cfg, '/homework')[1]['data']['items'][0]['title'], self.task()['title'])

    def test_parallel_mcp_retries_create_one_personal_task(self):
        self.save()
        cfg = self.issue()
        body = {'task': self.task(), 'expected': None, 'idempotencyKey': 'parallel-mcp-task'}
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.tool(cfg, 'kejian_save_homework', body), range(2)))
        self.assertTrue(all(not x['isError'] for x in results))
        self.assertEqual(sum(x['structuredContent']['replayed'] for x in results), 1)
        with connect(self.db) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM course_homework').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
