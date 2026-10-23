"""Persistent discovery and pre-operation updates, using disposable accounts."""
from io import BytesIO
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch
from wsgiref.simple_server import make_server, WSGIRequestHandler
import zipfile

import test_agent as helpers
from classroom import agent, agent_mcp, agent_release
from classroom.app import connect


class Quiet(WSGIRequestHandler):
    def log_message(self, *args):pass


def release_for(source, version='2.0.1'):
    data=source.encode()
    meta={'apiVersion':agent.VERSION,'bootstrapProtocol':1,'clientVersion':version,
          'files':[{'path':'kejian_runtime.py','sha256':hashlib.sha256(data).hexdigest(),'size':len(data)}]}
    revision=agent.digest(agent.canonical(meta))
    meta.update(revision=revision,path='/client-release')
    def value(include_source=False):
        return {**meta,**({'sources':{'kejian_runtime.py':source}} if include_source else {})}
    return value


class AgentSyncTests(unittest.TestCase):
    def setUp(self):
        self.case=helpers.AgentTests();self.case.setUp()
        self.server=None
    def tearDown(self):
        if self.server:
            self.server.shutdown();self.thread.join();self.server.server_close()
        self.case.tearDown()

    def test_versions_survive_new_process_client_and_unchanged_files_are_untouched(self):
        cfg=self.case.issue();client,_,config=self.case.client(cfg)
        original=config.read_bytes();client.connect()
        files={p:(p.read_bytes(),p.stat().st_mtime_ns) for p in client.state.rglob('*') if p.is_file()}
        other,calls,_=self.case.client(cfg)
        result=other.request('GET','/today')
        self.assertNotIn('updates',result)
        self.assertEqual(calls[0][1],'/mem/api/agent/v1/discovery')
        self.assertEqual(other.versions,client.versions)
        for file,before in files.items():self.assertEqual((file.read_bytes(),file.stat().st_mtime_ns),before)
        self.assertEqual(config.read_bytes(),original)
        self.assertNotIn(cfg['token'],''.join(p.read_text() for p in client.state.rglob('*') if p.is_file()))
        self.assertTrue(all(p.stat().st_mode & 0o077==0 for p in client.state.rglob('*')))

    def test_corrupt_or_different_connection_cache_is_rebuilt(self):
        cfg=self.case.issue();client,_,_=self.case.client(cfg);client.connect()
        path=client.state/'context.json';path.write_text('{broken')
        other,_,_=self.case.client(cfg)
        self.assertIsNone(other.context);self.assertIn('updates',other.request('GET','/today'))
        cached=json.loads(path.read_text());cached['binding']='another-owner';path.write_text(json.dumps(cached))
        other,_,_=self.case.client(cfg);self.assertIsNone(other.context)
        self.assertTrue(other.connect()['verified'])

    def test_installed_skill_updates_without_overwriting_custom_files(self):
        cfg=self.case.issue();client,_,_=self.case.client(cfg);client.connect()
        target=Path(self.case.tmp.name)/'.codebuddy'/'skills'/'kejian'
        client.install_skill(target);extra=target/'my-notes.txt';extra.write_text('keep me')
        location=(target/'connection-location.json').read_bytes()
        old=agent_mcp.skill_document();new={**old,'text':old['text']+'\n新增课间用法'};new['revision']=agent.digest(new['text'])
        with patch('classroom.agent_mcp.skill_document',return_value=new):
            other,_,_=self.case.client(cfg);other.request('GET','/today')
            self.assertEqual((target/'SKILL.md').read_text(),new['text'])
            self.assertIn('新增课间用法',(other.state/'skills'/'kejian'/'SKILL.md').read_text())
        self.assertEqual(extra.read_text(),'keep me');self.assertEqual((target/'connection-location.json').read_bytes(),location)

    def test_user_edited_skill_is_preserved_and_unmanaged_target_is_not_overwritten(self):
        cfg=self.case.issue();client,_,_=self.case.client(cfg);client.connect()
        target=Path(self.case.tmp.name)/'skills'/'kejian';client.install_skill(target)
        file=target/'SKILL.md';file.write_text('my custom skill')
        other,_,_=self.case.client(cfg);other.refresh()
        self.assertEqual(file.read_text(),'my custom skill');self.assertTrue(other.local_info()['attention'])
        unrelated=Path(self.case.tmp.name)/'unrelated'/'kejian';unrelated.mkdir(parents=True)
        (unrelated/'SKILL.md').write_text('another integration')
        with self.assertRaisesRegex(RuntimeError,'未覆盖'):other.install_skill(unrelated)
        self.assertEqual((unrelated/'SKILL.md').read_text(),'another integration')

    def test_new_connection_uses_separate_cache_and_revocation_does_not_use_old_permissions(self):
        cfg=self.case.issue();client,_,_=self.case.client(cfg);client.connect()
        second=self.case.issue();other,_,_=self.case.client(second)
        self.assertNotEqual(client.state,other.state);self.assertIsNone(other.context)
        with connect(self.case.db) as c:c.execute("UPDATE ai_connections SET revoked_at='revoked' WHERE id=?",(cfg['connectionId'],))
        denied,_,_=self.case.client(cfg)
        with self.assertRaisesRegex(RuntimeError,'401'):denied.request('GET','/today')

    def live(self):
        self.requests=[]
        def record(env,start):
            self.requests.append((env['REQUEST_METHOD'],env['PATH_INFO']))
            return self.case.app(env,start)
        self.server=make_server('127.0.0.1',0,record,handler_class=Quiet)
        self.case.app.origin='http://127.0.0.1:'+str(self.server.server_port)
        self.case.app.base='/'
        self.case.app.allowed_origins=frozenset((self.case.app.origin,'https://class.example'))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.case.save(index=1);self.cfg=self.case.issue(1)
        caps=self.case.ai(self.cfg,'/capabilities')[1]['data']
        blob=agent.package(self.cfg['apiBase'],{'id':self.cfg['connectionId']},self.cfg['token'],caps)
        self.bundle=Path(self.case.tmp.name)/'download';self.bundle.mkdir(mode=0o700)
        with zipfile.ZipFile(BytesIO(blob)) as z:z.extractall(self.bundle)
        for file in self.bundle.rglob('*'):
            if file.is_file():file.chmod(0o600)
        self.config_bytes=(self.bundle/'connection.json').read_bytes()
        return self.run_client('connect')

    def run_client(self,*args,ok=True):
        result=subprocess.run([sys.executable,str(self.bundle/'kejian_client.py'),'--config',str(self.bundle/'connection.json'),*args],
            capture_output=True,text=True,timeout=20)
        self.assertNotIn(self.cfg['token'],result.stdout+result.stderr)
        if ok:
            self.assertEqual(result.returncode,0,result.stderr)
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode,0)
        return result

    def new_source(self):
        return Path(agent_release.__file__).with_name('agent_client.py').read_text().replace("CLIENT_VERSION = '2.0.0'","CLIENT_VERSION = '2.0.1'")

    def write_command(self):
        task=self.case.task();task['courseId']='class-a';task['id']='automatic-update-write'
        path=self.bundle/'task.json';path.write_text(json.dumps({'expected':None,'task':task}));path.chmod(0o600)
        return ('request','POST','/homework','--json-file',str(path),'--idempotency-key','sync-one-write')

    def test_downloaded_package_works_without_mcp_and_stable_tasks_do_not_fetch_code(self):
        result=self.live();self.assertEqual(result['identity']['student'],'2026000002')
        self.requests.clear();result=self.run_client('today','--date','2026-10-30')
        self.assertEqual(result['data']['events'][0]['teacher'],'测试教师')
        self.assertNotIn('updates',result)
        self.assertFalse(any(path.endswith('/client-release') for _,path in self.requests))
        self.assertEqual((self.bundle/'connection.json').read_bytes(),self.config_bytes)
        self.assertNotIn('MCP',result.get('local',{}).get('attention',''))

    def test_runtime_updates_before_one_write_and_next_task_reuses_checked_release(self):
        self.live();command=self.write_command();self.requests.clear()
        with patch('classroom.agent_release.release',side_effect=release_for(self.new_source())):
            result=self.run_client(*command)
            self.assertEqual(result['local']['clientVersion'],'2.0.1')
            self.assertEqual(sum(method=='POST' for method,_ in self.requests),1)
            self.assertEqual(sum(path.endswith('/client-release') for _,path in self.requests),1)
            self.assertEqual(result['data']['task']['id'],'automatic-update-write')
            self.requests.clear();again=self.run_client(*command)
            self.assertTrue(again['replayed']);self.assertEqual(again['local']['clientVersion'],'2.0.1')
            self.assertFalse(any(path.endswith('/client-release') for _,path in self.requests))
        self.assertEqual((self.bundle/'connection.json').read_bytes(),self.config_bytes)
        tasks=self.case.ai(self.cfg,'/homework')[1]['data']['items']
        self.assertEqual(sum(x['id']=='automatic-update-write' for x in tasks),1)

    def test_bad_release_preserves_old_files_and_never_sends_business_write(self):
        self.live();command=self.write_command();source=self.new_source();valid=release_for(source)
        def corrupted(include_source=False):
            value=valid(include_source)
            if include_source:value['sources']={'kejian_runtime.py':source+'\ncorrupted'}
            return value
        before=(self.bundle/'kejian_runtime.py').read_bytes();self.requests.clear()
        with patch('classroom.agent_release.release',side_effect=corrupted):
            failed=self.run_client(*command,ok=False);self.assertIn('校验失败',failed.stderr)
        self.assertFalse(any(method=='POST' for method,_ in self.requests))
        self.assertEqual((self.bundle/'kejian_runtime.py').read_bytes(),before)
        self.assertEqual((self.bundle/'connection.json').read_bytes(),self.config_bytes)
        self.assertTrue(self.run_client('connect')['verified'])

    def test_incompatible_update_or_invalid_python_is_not_executed(self):
        self.live();command=self.write_command();self.requests.clear()
        incompatible=release_for(self.new_source())
        def wrong_protocol(include_source=False):
            result=incompatible(include_source);result['bootstrapProtocol']=2;return result
        with patch('classroom.agent_release.release',side_effect=wrong_protocol):
            failed=self.run_client(*command,ok=False);self.assertIn('更新启动器',failed.stderr)
        with patch('classroom.agent_release.release',side_effect=release_for('def invalid python !')):
            failed=self.run_client(*command,ok=False);self.assertIn('无法加载',failed.stderr)
        self.assertFalse(any(method=='POST' for method,_ in self.requests))
        self.assertEqual((self.bundle/'connection.json').read_bytes(),self.config_bytes)

    def test_update_cannot_add_files_and_corrupt_active_runtime_is_repaired(self):
        self.live();command=self.write_command();source=self.new_source();valid=release_for(source)
        def extra_file(include_source=False):
            result=valid(include_source)
            result['files']=result['files']+[{'path':'../connection.json','size':3,'sha256':'0'*64}]
            result['revision']=agent.digest(agent.canonical({k:v for k,v in result.items() if k not in ('revision','path','sources')}))
            return result
        self.requests.clear()
        with patch('classroom.agent_release.release',side_effect=extra_file):
            failed=self.run_client(*command,ok=False);self.assertIn('不支持的文件',failed.stderr)
        self.assertFalse(any(method=='POST' for method,_ in self.requests))
        with patch('classroom.agent_release.release',side_effect=valid):
            first=self.run_client('today');self.assertEqual(first['local']['clientVersion'],'2.0.1')
            runtime=next(self.bundle.glob('.kejian/*/runtime/*.py'));runtime.write_text('raise RuntimeError("must not execute corrupt cache")')
            repaired=self.run_client('today');self.assertEqual(repaired['local']['clientVersion'],'2.0.1')
        self.assertEqual((self.bundle/'connection.json').read_bytes(),self.config_bytes)

    def test_authenticated_release_has_no_personal_secrets(self):
        cfg=self.case.issue()
        self.assertEqual(self.case.ai(None,'/client-release')[0],401)
        result=self.case.ai(cfg,'/client-release')[1]['data']
        self.assertNotIn(cfg['token'],json.dumps(result));self.assertEqual(set(result['sources']),{'kejian_runtime.py'})
        entry=result['files'][0];self.assertEqual(agent.digest(result['sources'][entry['path']]),entry['sha256'])
        self.assertEqual(self.case.ai(cfg,'/discovery')[1]['data']['connectionMethods']['preferred'],'api')

    def test_runtime_that_cannot_start_never_replaces_the_active_version(self):
        self.live();command=self.write_command();source=self.new_source()
        with patch('classroom.agent_release.release',side_effect=release_for(source)):
            self.run_client('today')
        pointer=next(self.bundle.glob('.kejian/*/active-runtime.json'));original=pointer.read_bytes()
        self.requests.clear()
        with patch('classroom.agent_release.release',side_effect=release_for('import missing_dependency_for_kejian_test\n'+source,'2.0.2')):
            failed=self.run_client(*command,ok=False);self.assertIn('无法启动',failed.stderr)
        self.assertEqual(pointer.read_bytes(),original)
        self.assertFalse(any(method=='POST' for method,_ in self.requests))
        self.assertEqual((self.bundle/'connection.json').read_bytes(),self.config_bytes)


if __name__=='__main__':unittest.main()
