from concurrent.futures import ThreadPoolExecutor
import hashlib
from io import BytesIO
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid
import zipfile
import urllib.error
from urllib.parse import urlsplit
import test_classroom as helpers
from classroom.app import connect,initialize
from classroom import agent,agent_schedule,course_store,import_guide
from classroom.agent_client import Client


class AgentTests(unittest.TestCase):
    setUp=helpers.ClassroomTests.setUp
    tearDown=helpers.ClassroomTests.tearDown
    call=helpers.ClassroomTests.call
    save=helpers.ClassroomTests.save
    op=helpers.ClassroomTests.op
    admin=helpers.ClassroomTests.admin
    publish=helpers.ClassroomTests.publish
    manage=helpers.ClassroomTests.manage
    task=helpers.ClassroomTests.task

    def issue(self,index=0,mode='delegate'):
        status,headers,body=self.call('/api/ai-connections',payload={'owner':self.owners[index],'action':'create','name':'测试AI','mode':mode,'requestKey':str(uuid.uuid4())},cookie=self.cookies[index])
        self.assertEqual(status,200);self.assertEqual(headers['Content-Type'],'application/zip')
        with zipfile.ZipFile(BytesIO(body)) as z:
            config=json.loads(z.read('connection.json'));manifest=json.loads(z.read('manifest.json'))
            self.assertEqual(z.getinfo('connection.json').external_attr>>16 & 0o777,0o600)
            for record in manifest['files']:self.assertEqual(hashlib.sha256(z.read(record['path'])).hexdigest(),record['sha256'])
            self.assertIn('kejian_client.py',z.namelist())
        return config

    def ai(self,config,path='/me',payload=None,key='test-request-001',cookie='',extra=None):
        raw=json.dumps(payload).encode() if payload is not None else b'';captured={}
        endpoint,_,query=path.partition('?')
        env={'PATH_INFO':agent.PREFIX+endpoint,'QUERY_STRING':query,'REQUEST_METHOD':'POST' if payload is not None else 'GET',
             'wsgi.input':BytesIO(raw),'CONTENT_TYPE':'application/json','CONTENT_LENGTH':str(len(raw)),
             'HTTP_AUTHORIZATION':'Bearer '+config['token'] if config else '', 'HTTP_COOKIE':cookie,'HTTP_IDEMPOTENCY_KEY':key,**(extra or {})}
        def start(s,h):captured.update(status=int(s[:3]),headers=dict(h))
        result=b''.join(self.app(env,start))
        return captured['status'],json.loads(result)

    def test_ai_remove_course_and_undo_share_personal_permissions(self):
        self.save();cfg=self.issue()
        base=self.ai(cfg,'/timetable-import',{'action':'inspect'},key='remove-inspect-001')[1]['data']['base']
        payload={'action':'remove','courseId':'class-a','base':base}
        first=self.ai(cfg,'/timetable-import',payload,key='remove-course-001')
        self.assertEqual(first[0],200,first)
        replay=self.ai(cfg,'/timetable-import',payload,key='remove-course-001')
        self.assertTrue(replay[1]['replayed'])
        self.assertEqual(len(self.ai(cfg,'/schedule')[1]['data']['courses']),1)
        undo=self.ai(cfg,'/timetable-import',{'action':'restore','base':first[1]['data']['nextBase']},key='remove-undo-001')
        self.assertEqual(undo[0],200,undo)
        self.assertEqual(len(self.ai(cfg,'/schedule')[1]['data']['courses']),2)

    def test_connection_package_private_and_cookie_cannot_act_as_ai(self):
        cfg=self.issue();self.assertEqual(self.ai(cfg)[0],200)
        self.assertEqual(self.ai(None,cookie=self.cookies[0])[0],401)
        with connect(self.db) as c:
            dump='\n'.join(c.iterdump());self.assertNotIn(cfg['token'],dump)
        listing=self.call('/api/ai-connections',cookie=self.cookies[0])[2]
        self.assertNotIn(cfg['token'],json.dumps(listing));self.assertNotIn('token_hash',json.dumps(listing))
        self.assertEqual(self.call('/api/ai-connections',cookie=self.cookies[1])[2]['connections'],[])
        self.assertEqual(self.call('/api/ai-connections')[0],401)
        self.assertEqual(self.ai(cfg,'/ai-connections')[0],404)
        self.assertEqual(self.call('/api/ai-connections',payload={'owner':self.owners[0],'action':'create'},cookie=self.cookies[0],origin='https://evil.example')[0],403)
        self.assertEqual(self.ai(cfg,extra={'HTTP_ORIGIN':'https://evil.example'})[0],403)

    def test_owner_is_derived_from_token_even_with_another_browser_session(self):
        self.save();cfg=self.issue(1)
        identity=self.ai(cfg,'/me',cookie=self.cookies[0])[1]['data']
        self.assertEqual(identity['student'],'2026000002');self.assertEqual(identity['name'],'测试乙')
        result=self.ai(cfg,'/schedule',cookie=self.cookies[0]);self.assertEqual(result[0],200)
        self.assertEqual(result[1]['data']['owner'],self.owners[1]);self.assertEqual(result[1]['data']['courses'],[])
        for path in ('/schedule?owner=1','/homework?member=1','/today?token=secret'):
            self.assertEqual(self.ai(cfg,path)[0],403)
        self.assertEqual(self.ai(cfg,'/homework',{'owner':self.owners[0],'expected':None,'task':self.task()})[0],403)

    def test_personal_write_idempotency_and_conflict_preserve_other_owner(self):
        self.save();cfg=self.issue();body={'expected':None,'task':self.task()}
        first=self.ai(cfg,'/homework',body);self.assertEqual(first[0],200,first[1])
        replay=self.ai(cfg,'/homework',body);self.assertEqual(replay[0],200);self.assertTrue(replay[1]['replayed'])
        self.assertEqual(first[1]['data'],replay[1]['data'])
        changed={'expected':None,'task':{**self.task(),'title':'不同内容'}}
        self.assertEqual(self.ai(cfg,'/homework',changed)[0],409)
        self.assertEqual(self.ai(cfg,'/homework',body,key='different-key')[0],409)
        self.assertEqual(self.call('/api/homework',cookie=self.cookies[1])[2]['items'],[])
        with connect(self.db) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM course_homework').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT count(*) FROM ai_requests').fetchone()[0],1)
            self.assertEqual(c.execute("SELECT count(*) FROM ai_audit WHERE operation='write:/homework'").fetchone()[0],2)

    def test_all_connections_follow_owner_role_and_legacy_mode_migrates_without_rotation(self):
        self.save();cfg=self.issue()
        with connect(self.db) as c:
            before=dict(c.execute('SELECT * FROM ai_connections WHERE id=?',(cfg['connectionId'],)).fetchone())
            c.execute("UPDATE ai_connections SET mode='read' WHERE id=?",(cfg['connectionId'],))
        initialize(self.db)
        with connect(self.db) as c:
            after=dict(c.execute('SELECT * FROM ai_connections WHERE id=?',(cfg['connectionId'],)).fetchone())
            self.assertEqual(before,after)
        caps=self.ai(cfg,'/capabilities')[1]['data'];self.assertEqual(caps['mode'],'delegate')
        self.assertIn('/homework',caps['writeOperations'])
        self.assertEqual(self.ai(cfg,'/homework',{'expected':None,'task':self.task()})[0],200)
        self.assertEqual(self.ai(cfg,'/timetable-import',{'action':'inspect'},key='')[0],200)
        doc=self.ai(cfg,'/openapi.json')[1]['data'];guide=self.ai(cfg,'/agent-guide')[1]['data']
        self.assertEqual(agent.digest(agent.canonical(doc)),guide['openapiSha256'])
        self.assertNotIn('/management',doc['paths'])
        self.assertIn('post',doc['paths']['/homework'])
        self.assertEqual(self.call('/api/ai-connections',payload={'owner':self.owners[0],'action':'create','name':'无查询选项','mode':'read','requestKey':str(uuid.uuid4())},cookie=self.cookies[0])[0],400)

    def test_atomic_rollback_includes_change_request_and_success_audit(self):
        self.save();cfg=self.issue();original=agent.log
        def fail_success(c,member,connection,operation,*args,**kwargs):
            if operation=='write:/homework':raise ValueError('模拟提交前失败')
            return original(c,member,connection,operation,*args,**kwargs)
        with patch('classroom.agent.log',side_effect=fail_success):
            self.assertEqual(self.ai(cfg,'/homework',{'expected':None,'task':self.task()})[0],400)
        with connect(self.db) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM course_homework').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT count(*) FROM ai_requests').fetchone()[0],0)
            self.assertEqual(c.execute("SELECT count(*) FROM ai_audit WHERE operation='write:/homework'").fetchone()[0],0)
        self.assertEqual(self.ai(cfg,'/homework',{'expected':None,'task':self.task()})[0],200)

    def test_parallel_retries_create_exactly_one_task(self):
        self.save();cfg=self.issue();body={'expected':None,'task':self.task()}
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.ai(cfg,'/homework',body),range(2)))
        self.assertTrue(all(x[0]==200 for x in results));self.assertEqual(sum(x[1]['replayed'] for x in results),1)
        with connect(self.db) as c:self.assertEqual(c.execute('SELECT count(*) FROM course_homework').fetchone()[0],1)

    def test_representative_scope_and_revocation_apply_even_to_idempotent_replay(self):
        cards=self.publish();self.save(index=1);keys={r['courseId']:r['key'] for r in cards}
        self.manage({'action':'representative-add','key':keys['class-a'],'member':self.owners[1]})
        cfg=self.issue(1);b={'action':'save','key':keys['class-a'],'id':'coursework-ai-test','expected':None,'task':{'title':'课程作业','notes':'','dueDate':'2026-10-30','dueTime':''}}
        first=self.ai(cfg,'/course-homework',b);self.assertEqual(first[0],200,first[1])
        self.assertEqual(self.ai(cfg,'/course-homework',{**b,'id':'coursework-ai-other','key':keys['class-b']},key='another-class')[0],403)
        self.manage({'action':'representative-remove','key':keys['class-a'],'member':self.owners[1]})
        self.assertEqual(self.ai(cfg,'/course-homework',b)[0],403)
        self.assertNotIn(keys['class-a'],[r['key'] for r in self.ai(cfg,'/capabilities')[1]['data']['editableCourses']])
        self.assertEqual(self.ai(cfg,'/management')[0],403)

    def test_join_leave_and_completion_only_affect_the_owner(self):
        cards=self.publish();key=next(x for x in cards if x['courseId']=='class-a')['key'];cfg=self.issue(1)
        library=self.ai(cfg,'/courses')[1]['data'];card=next(x for x in library['courses'] if x['key']==key)
        b={'action':'subscribe','key':key,'revision':card['revision'],'base':library['base']}
        self.assertEqual(self.ai(cfg,'/courses',b)[0],200)
        self.assertEqual(len(self.call('/api/schedule',cookie=self.cookies[1])[2]['courses']),1)
        admin_cfg=self.issue();task={'action':'save','key':key,'id':'coursework-completion-test','expected':None,'task':{'title':'作业','notes':'','dueDate':'','dueTime':''}}
        self.assertEqual(self.ai(admin_cfg,'/course-homework',task,key='publish-completion')[0],200)
        done={'action':'complete','id':task['id'],'expected':None,'completed':True}
        self.assertEqual(self.ai(cfg,'/course-homework',done,key='student-complete')[0],200)
        self.assertEqual(self.call('/api/homework',cookie=self.cookies[0])[2]['items'][0]['completedAt'],'')
        library=self.ai(cfg,'/courses')[1]['data'];b.update(action='unsubscribe',base=library['base'])
        self.assertEqual(self.ai(cfg,'/courses',b,key='student-leave')[0],200)
        self.assertEqual(self.ai(cfg,'/course-homework',done,key='student-complete')[0],403)

    def test_rotation_revoke_and_disabled_owner_invalidate_token_but_time_does_not(self):
        cfg=self.issue();item=self.call('/api/ai-connections',cookie=self.cookies[0])[2]['connections'][0]
        payload={'owner':self.owners[0],'action':'rotate','id':item['id'],'expected':item['revision']}
        self.assertEqual(self.call('/api/ai-connections',payload=payload,cookie=self.cookies[1])[0],403)
        status,_,raw=self.call('/api/ai-connections',payload=payload,cookie=self.cookies[0]);self.assertEqual(status,200)
        with zipfile.ZipFile(BytesIO(raw)) as z:new=json.loads(z.read('connection.json'))
        self.assertEqual(self.ai(cfg)[0],401);self.assertEqual(self.ai(new)[0],200)
        self.assertEqual(self.call('/api/ai-connections',payload=payload,cookie=self.cookies[0])[0],409)
        item=self.call('/api/ai-connections',cookie=self.cookies[0])[2]['connections'][0]
        self.call('/api/ai-connections',payload={'owner':self.owners[0],'action':'revoke','id':item['id'],'expected':item['revision']},cookie=self.cookies[0])
        self.assertEqual(self.ai(new)[0],401)
        permanent=self.issue()
        with patch('classroom.agent.clock',return_value=agent.clock()+100*365*86400):
            self.assertEqual(self.ai(permanent)[0],200)
        listing=self.call('/api/ai-connections',cookie=self.cookies[0])[2]['connections']
        self.assertIsNone(next(x for x in listing if x['id']==permanent['connectionId'])['expiresAt'])
        active=self.issue()
        with connect(self.db) as c:c.execute('UPDATE members SET disabled=1 WHERE id=?',(self.owners[0],))
        self.assertEqual(self.ai(active)[0],401)

    def test_creation_retry_does_not_duplicate_or_reveal_credentials(self):
        b={'owner':self.owners[0],'action':'create','name':'WorkBuddy','requestKey':str(uuid.uuid4())}
        self.assertEqual(self.call('/api/ai-connections',payload=b,cookie=self.cookies[0])[0],200)
        repeated=self.call('/api/ai-connections',payload=b,cookie=self.cookies[0]);self.assertEqual(repeated[0],409)
        self.assertEqual(repeated[2]['code'],'CONNECTION_ALREADY_CREATED')
        self.assertEqual(len(self.call('/api/ai-connections',cookie=self.cookies[0])[2]['connections']),1)

    def test_delete_connection_is_owner_scoped_invalidates_and_cannot_be_rotated(self):
        cfg=self.issue();other=self.issue(1)
        item=self.call('/api/ai-connections',cookie=self.cookies[0])[2]['connections'][0]
        payload={'owner':self.owners[0],'action':'delete','id':item['id'],'expected':item['revision']}
        self.assertEqual(self.call('/api/ai-connections',payload=payload,cookie=self.cookies[1])[0],403)
        self.assertEqual(self.call('/api/ai-connections',payload={**payload,'owner':self.owners[1]},cookie=self.cookies[1])[0],404)
        self.assertEqual(self.call('/api/ai-connections',payload={**payload,'expected':'old'},cookie=self.cookies[0])[0],409)
        self.assertEqual(self.ai(cfg)[0],200)
        self.assertEqual(self.call('/api/ai-connections',payload=payload,cookie=self.cookies[0])[0],200)
        self.assertEqual(self.ai(cfg)[0],401);self.assertEqual(self.ai(other)[0],200)
        listing=self.call('/api/ai-connections',cookie=self.cookies[0])[2]
        self.assertEqual(listing['connections'],[]);self.assertEqual(listing.get('activity',[]),[])
        self.assertEqual(self.call('/api/ai-connections',payload=payload,cookie=self.cookies[0])[0],200)
        self.assertEqual(self.call('/api/ai-connections',payload={**payload,'action':'rotate'},cookie=self.cookies[0])[0],404)
        with connect(self.db) as c:
            self.assertTrue(c.execute('SELECT deleted_at FROM ai_connections WHERE id=?',(item['id'],)).fetchone()[0])
            self.assertEqual(c.execute("SELECT count(*) FROM ai_audit WHERE connection=? AND operation='connectionDelete'",(item['id'],)).fetchone()[0],1)
        # Already inactive connections can also be removed from the normal list.
        inactive=self.issue()
        with connect(self.db) as c:c.execute('UPDATE ai_connections SET revoked_at=? WHERE id=?',(agent.now(),inactive['connectionId']))
        item=self.call('/api/ai-connections',cookie=self.cookies[0])[2]['connections'][0]
        self.assertEqual(self.call('/api/ai-connections',payload={**payload,'id':item['id'],'expected':item['revision']},cookie=self.cookies[0])[0],200)
        self.assertEqual(self.call('/api/ai-connections',cookie=self.cookies[0])[2]['connections'],[])

    def test_delete_audit_failure_rolls_back_access_and_list_changes(self):
        cfg=self.issue();item=self.call('/api/ai-connections',cookie=self.cookies[0])[2]['connections'][0]
        original=agent.log
        def fail(c,member,connection,operation,*args,**kwargs):
            if operation=='connectionDelete':raise ValueError('模拟日志失败')
            return original(c,member,connection,operation,*args,**kwargs)
        with patch('classroom.agent.log',side_effect=fail):
            status=self.call('/api/ai-connections',payload={'owner':self.owners[0],'action':'delete','id':item['id'],'expected':item['revision']},cookie=self.cookies[0])[0]
            self.assertEqual(status,400)
        self.assertEqual(self.ai(cfg)[0],200)
        self.assertEqual(self.call('/api/ai-connections',cookie=self.cookies[0])[2]['connections'][0]['revision'],item['revision'])

    def test_legacy_connection_schema_migrates_without_changing_credentials(self):
        import sqlite3
        c=sqlite3.connect(':memory:')
        c.execute('CREATE TABLE ai_connections(id TEXT PRIMARY KEY,member INTEGER,name TEXT,mode TEXT,token_hash TEXT UNIQUE,prefix TEXT,expires_at INTEGER,revoked_at TEXT,created_at TEXT,last_used_at TEXT,revision TEXT,request_key TEXT,UNIQUE(member,request_key))')
        row=('legacy',1,'Original','read','private-hash','prefix',100,'','created',None,'revision','request')
        c.execute('INSERT INTO ai_connections VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',row)
        agent.schema(c);agent.schema(c)
        migrated=c.execute('SELECT * FROM ai_connections').fetchone()
        expected=(*row[:3],'delegate',*row[4:6],0,*row[7:])
        self.assertEqual(migrated[:-1],expected);self.assertEqual(migrated[-1],'')
        c.close()

    def test_permanent_migration_keeps_original_keys_and_explicit_invalidations(self):
        active=self.issue();revoked=self.issue();deleted=self.issue(1)
        with connect(self.db) as c:
            c.execute('UPDATE ai_connections SET expires_at=1')
            c.execute('UPDATE ai_connections SET revoked_at=? WHERE id=?',(agent.now(),revoked['connectionId']))
            c.execute('UPDATE ai_connections SET revoked_at=?,deleted_at=? WHERE id=?',(agent.now(),agent.now(),deleted['connectionId']))
            before={r['id']:dict(r) for r in c.execute('SELECT * FROM ai_connections')}
        initialize(self.db);initialize(self.db)
        with connect(self.db) as c:
            after={r['id']:dict(r) for r in c.execute('SELECT * FROM ai_connections')}
        for ident,row in before.items():self.assertEqual(after[ident],{**row,'expires_at':0})
        self.assertEqual(self.ai(active)[0],200)
        self.assertEqual(self.ai(revoked)[0],401);self.assertEqual(self.ai(deleted)[0],401)

    def test_permanent_connections_still_respect_limit_and_rotation_at_capacity(self):
        configs=[self.issue() for _ in range(10)]
        create={'owner':self.owners[0],'action':'create','name':'超出数量','requestKey':str(uuid.uuid4())}
        self.assertEqual(self.call('/api/ai-connections',payload=create,cookie=self.cookies[0])[0],400)
        items=self.call('/api/ai-connections',cookie=self.cookies[0])[2]['connections']
        first=next(x for x in items if x['id']==configs[0]['connectionId'])
        self.assertEqual(self.call('/api/ai-connections',payload={'owner':self.owners[0],'action':'rotate','id':first['id'],'expected':first['revision']},cookie=self.cookies[0])[0],200)
        second=next(x for x in items if x['id']==configs[1]['connectionId'])
        self.assertEqual(self.call('/api/ai-connections',payload={'owner':self.owners[0],'action':'revoke','id':second['id'],'expected':second['revision']},cookie=self.cookies[0])[0],200)
        self.issue()
        inactive=next(x for x in self.call('/api/ai-connections',cookie=self.cookies[0])[2]['connections'] if x['id']==second['id'])
        self.assertEqual(self.call('/api/ai-connections',payload={'owner':self.owners[0],'action':'rotate','id':inactive['id'],'expected':inactive['revision']},cookie=self.cookies[0])[0],400)

    def test_administrator_can_manage_class_but_not_read_private_work(self):
        self.publish();self.save(index=1);cfg=self.issue()
        self.call('/api/homework',payload={'owner':self.owners[1],'expected':None,'task':self.task()},cookie=self.cookies[1])
        self.assertEqual(self.ai(cfg,'/homework')[1]['data']['items'],[])
        self.assertEqual(self.ai(cfg,'/management')[0],200)
        self.assertEqual(self.ai(cfg,'/homework?owner='+str(self.owners[1]))[0],403)
        normal=self.issue(1);self.assertEqual(self.ai(normal,'/management',{'action':'publish','courses':[]})[0],403)

    def test_safe_import_preview_and_save_reuse_web_rules(self):
        cfg=self.issue();preview=self.ai(cfg,'/timetable-import',{'text':self.text},key='preview-only')
        self.assertEqual(preview[0],200,preview[1]);self.assertEqual(self.call('/api/schedule',cookie=self.cookies[0])[2]['courses'],[])
        b={'text':self.text,'action':'save','base':preview[1]['data']['base']}
        self.assertEqual(self.ai(cfg,'/timetable-import',b,key='save-import')[0],200)
        self.assertEqual(len(self.call('/api/schedule',cookie=self.cookies[0])[2]['courses']),2)
        self.assertTrue(self.ai(cfg,'/timetable-import',b,key='save-import')[1]['replayed'])

    def client(self,cfg):
        path=Path(self.tmp.name)/'connection.json';path.write_text(json.dumps(cfg));path.chmod(0o600)
        client=Client(path);calls=[]
        def open_request(request,timeout):
            parsed=urlsplit(request.full_url);payload=json.loads(request.data) if request.data else None
            status,result=self.ai(cfg,parsed.path.removeprefix('/mem/api/agent/v1')+('?' + parsed.query if parsed.query else ''),payload,
                                  request.get_header('Idempotency-key') or '',
                                  extra={'HTTP_X_KEJIAN_CONTEXT_REVISION':request.get_header('X-kejian-context-revision') or ''})
            calls.append((request.method,parsed.path))
            raw=BytesIO(json.dumps(result).encode())
            if status>=400:raise urllib.error.HTTPError(request.full_url,status,'Failed',{},raw)
            return raw
        from unittest.mock import Mock
        client.transport=Mock();client.transport.open.side_effect=open_request
        return client,calls,path

    def test_discovery_changes_only_when_rules_features_or_permissions_change(self):
        cfg=self.issue()
        initial=self.ai(cfg,'/discovery')[1]
        self.assertTrue(initial['sync']['changed']);self.assertIn('updates',initial)
        version=initial['sync']['versions']
        same=self.ai(cfg,'/discovery',extra={'HTTP_X_KEJIAN_CONTEXT_REVISION':version['context']})[1]
        self.assertFalse(same['sync']['changed']);self.assertNotIn('updates',same)
        self.assertEqual(same['data']['versions'],version)
        old_guide=agent.guide()
        with patch('classroom.agent.guide',return_value=old_guide+'\n新增本地测试说明'):
            changed=self.ai(cfg,'/discovery',extra={'HTTP_X_KEJIAN_CONTEXT_REVISION':version['context']})[1]
        self.assertNotEqual(changed['sync']['versions']['guide'],version['guide'])
        self.assertEqual(changed['sync']['versions']['features'],version['features'])
        self.assertEqual(changed['sync']['versions']['permissions'],version['permissions'])
        self.assertIn('新增本地测试说明',changed['updates']['guide']['text'])
        with patch.dict(agent.READS,{'/new-feature':'localTestDiscovery'}):
            expanded=self.ai(cfg,'/discovery',extra={'HTTP_X_KEJIAN_CONTEXT_REVISION':version['context']})[1]
        self.assertNotEqual(expanded['sync']['versions']['features'],version['features'])
        self.assertIn('/new-feature',expanded['updates']['openapi']['paths'])
        self.assertEqual(self.ai(cfg,'/me')[1]['data']['connection']['id'],cfg['connectionId'])

    def test_client_automatically_refreshes_original_connection_for_role_changes(self):
        cards=self.publish();self.save(index=1);key=next(r['key'] for r in cards if r['courseId']=='class-a')
        cfg=self.issue(1);client,calls,path=self.client(cfg);original=path.read_bytes()
        result=client.request('GET','/today');self.assertIn('updates',result)
        self.assertEqual(calls[-2:],[('GET','/mem/api/agent/v1/discovery'),('GET','/mem/api/agent/v1/today')])
        before=client.versions.copy();self.assertEqual(client.context['capabilities']['editableCourses'],[])
        self.manage({'action':'representative-add','key':key,'member':self.owners[1]})
        task={'action':'save','key':key,'id':'coursework-live-role','expected':None,'task':{'title':'新课代表作业','notes':'','dueDate':'','dueTime':''}}
        saved=client.request('POST','/course-homework',task,'publish-live-role')
        self.assertNotEqual(client.versions['permissions'],before['permissions'])
        self.assertEqual(client.context['capabilities']['editableCourses'][0]['key'],key)
        self.assertEqual(saved['data']['task']['title'],'新课代表作业')
        self.manage({'action':'representative-remove','key':key,'member':self.owners[1]})
        with self.assertRaisesRegex(RuntimeError,'403'):client.request('POST','/course-homework',task,'publish-live-role')
        self.assertEqual(client.context['capabilities']['editableCourses'],[])
        self.assertEqual(path.read_bytes(),original)

    def test_permission_change_between_preflight_and_write_does_not_replay_or_escalate(self):
        cards=self.publish();self.save(index=1);key=next(r['key'] for r in cards if r['courseId']=='class-a')
        self.manage({'action':'representative-add','key':key,'member':self.owners[1]})
        cfg=self.issue(1);client,calls,_=self.client(cfg);real_open=client.transport.open.side_effect
        def revoke_before_post(request,timeout):
            if request.method=='POST':self.manage({'action':'representative-remove','key':key,'member':self.owners[1]})
            return real_open(request,timeout)
        client.transport.open.side_effect=revoke_before_post
        task={'action':'save','key':key,'id':'coursework-revoked-before-write','expected':None,'task':{'title':'不得发布','notes':'','dueDate':'','dueTime':''}}
        with self.assertRaisesRegex(RuntimeError,'403'):client.request('POST','/course-homework',task,'permission-race')
        self.assertEqual(client.context['capabilities']['editableCourses'],[])
        self.assertEqual(len([x for x in calls if x[0]=='POST']),1)
        with connect(self.db) as c:self.assertEqual(c.execute('SELECT count(*) FROM teaching_homework').fetchone()[0],0)

    def test_client_fetches_new_guides_and_features_without_reissuing_connection(self):
        cfg=self.issue();client,_,path=self.client(cfg);original=path.read_bytes()
        first=client.connect();old_versions=client.versions.copy();text=agent.guide()
        self.assertIn('verified',first)
        with patch('classroom.agent.guide',return_value=text+'\n本地新增功能用法'),patch.dict(agent.READS,{'/new-feature':'localFeature'}):
            result=client.request('GET','/today')
            self.assertIn('本地新增功能用法',result['updates']['guide']['text'])
            self.assertIn('/new-feature',client.context['openapi']['paths'])
            self.assertNotEqual(client.versions['guide'],old_versions['guide'])
            self.assertNotEqual(client.versions['features'],old_versions['features'])
            stable=client.request('GET','/today');self.assertNotIn('updates',stable)
        self.assertEqual(path.read_bytes(),original)

    def test_web_api_and_package_share_import_rules_and_import_keeps_existing(self):
        cfg=self.issue();web=self.call('/api/import-guide',cookie=self.cookies[0]);self.assertEqual(web[0],200)
        self.assertEqual(self.call('/api/import-guide')[0],401)
        self.assertEqual(web[2],self.ai(cfg,'/import-guide')[1]['data'])
        self.assertEqual(web[2],import_guide.document())
        self.assertNotIn('`;}',web[2]['extractionPrompt'])
        self.assertIn('我的课表',web[2]['extractionPrompt']);self.assertIn('2027-01-09',web[2]['extractionPrompt'])
        status,_,raw=self.call('/api/ai-connections',payload={'owner':self.owners[0],'action':'create','name':'导入规则包','requestKey':str(uuid.uuid4())},cookie=self.cookies[0])
        self.assertEqual(status,200)
        with zipfile.ZipFile(BytesIO(raw)) as z:self.assertIn(web[2]['extractionPrompt'],z.read('COURSE-IMPORT.txt').decode())
        self.save(selected=['class-a'])
        client,_,_=self.client(cfg)
        preview=client.request('POST','/timetable-import',{'action':'preview','text':self.text,'mode':'merge'},'import-preview-live')['data']
        self.assertEqual(sum(x['kind']=='新增' for x in preview['changes']),1)
        body={'action':'save','text':self.text,'base':preview['base'],'mode':'merge'}
        client.request('POST','/timetable-import',body,'import-save-live')
        final=client.request('GET','/schedule')['data'];self.assertEqual(len(final['courses']),2)
        again=client.request('POST','/timetable-import',{'action':'preview','text':self.text},'import-preview-again')['data']
        self.assertTrue(all(x['kind']=='未变化' for x in again['changes']))
        self.assertTrue(client.request('POST','/timetable-import',body,'import-save-live')['replayed'])


class AgentScheduleTests(unittest.TestCase):
    def test_china_calendar_recurring_dates_exclusions_and_unknown_end(self):
        data=course_store.empty(1);data['courses']=[{'id':'english','name':'英语','teacher':'马老师','recurrence':{'weekday':2,'starts_on':'2026-09-22','until':None,'start_time':'19:00','end_time':None,'excluded_dates':['2026-10-06']}}]
        first=agent_schedule.query(data,'2026-09-22');self.assertEqual(first['timezone'],'Asia/Shanghai');self.assertEqual(first['teachingWeek'],2)
        self.assertEqual(first['events'][0]['start_time'],'19:00');self.assertIsNone(first['events'][0]['end_time']);self.assertTrue(first['events'][0]['endPending'])
        self.assertEqual(agent_schedule.query(data,'2026-10-06')['events'],[])
        self.assertEqual(agent_schedule.query(data,'2026-09-15')['events'],[])
        self.assertEqual(agent_schedule.query(data,'2027-01-19')['events'],[])
        week=agent_schedule.query(data,'2026-09-23',True);self.assertEqual((week['start'],week['end']),('2026-09-21','2026-09-27'))
        self.assertEqual(len(week['events']),1)
        for invalid in ('20260922','2026-02-30','bad'):
            with self.assertRaises(ValueError):agent_schedule.query(data,invalid)


if __name__=='__main__':unittest.main()
