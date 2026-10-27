from datetime import datetime,timedelta,timezone
from io import BytesIO
import json
import unittest
from unittest.mock import patch
from classroom import push,reminders,reminder_changes,course_store,course_homework,agent
from classroom.app import connect
from classroom.push_scheduler import Scheduler,SEND_BATCH,FALLBACK_SECONDS
from test_reminders import ReminderTests


class Clock:
    def __init__(self,now):self.now=now;self.elapsed=0
    def time(self):return self.now
    def monotonic(self):return self.elapsed
    def advance(self,seconds):self.now+=seconds;self.elapsed+=seconds


class SchedulerTests(unittest.TestCase):
    setUp=ReminderTests.setUp
    tearDown=ReminderTests.tearDown
    call=ReminderTests.call
    api=ReminderTests.api
    enable=ReminderTests.enable
    publish=ReminderTests.publish
    personal=ReminderTests.personal
    plan=ReminderTests.plan
    jobs=ReminderTests.jobs
    dispatch=ReminderTests.dispatch

    def dirty(self):
        with connect(self.db) as c:return {r[0] for r in c.execute('SELECT member FROM push_changes')}

    def clear_dirty(self):
        with connect(self.db) as c:c.execute('DELETE FROM push_changes')

    def test_idle_does_not_replan_or_write_every_poll(self):
        self.enable(0,course=False,newHomework=False,homeworkDue=False)
        clock=Clock(self.now);scheduler=Scheduler(clock.time,clock.monotonic)
        with connect(self.db) as c,patch.object(reminders,'candidates',wraps=reminders.candidates) as calls:
            scheduler.step(c,self.cfg,lambda *args:self.fail('Idle notification'))
            initial=c.total_changes;self.assertEqual(calls.call_count,1)
            for _ in range(2):clock.advance(10);scheduler.step(c,self.cfg,lambda *args:201)
            self.assertEqual(c.total_changes,initial)
            clock.advance(10);scheduler.step(c,self.cfg,lambda *args:201)
            self.assertEqual(c.total_changes,initial+1)
            self.assertEqual(calls.call_count,1)

    def test_due_time_wakes_exactly_without_waiting_for_next_poll(self):
        self.enable(0,course=False,newHomework=False,homeworkDue=False)
        result=self.api('test',{'deviceId':self.devices[0],'requestKey':'scheduler-exact-due-test'})
        due=result[2]['jobs'][0]['due'];clock=Clock(due-45);scheduler=Scheduler(clock.time,clock.monotonic)
        sent=[]
        with connect(self.db) as c:
            for _ in range(10):
                step=scheduler.step(c,self.cfg,lambda *args:sent.append(clock.now) or 201)
                if sent:break
                clock.advance(step['delay'])
        self.assertEqual(sent,[due])

    def test_changes_are_coalesced_and_only_affected_member_is_planned(self):
        self.enable(0);self.enable(1);self.plan();self.assertEqual(self.dirty(),set())
        ident=self.personal(0)
        with connect(self.db) as c:
            c.execute('UPDATE course_homework SET title=? WHERE id=?',('第一次修改',ident))
            c.execute('UPDATE course_homework SET notes=? WHERE id=?',('第二次修改',ident))
        self.assertEqual(self.dirty(),{self.owners[0]})
        with connect(self.db) as c,patch.object(reminders,'candidates',wraps=reminders.candidates) as calls:
            result=reminders.plan_dirty(c,self.now)
            self.assertEqual(result['processed'],1);self.assertFalse(result['remaining'])
            self.assertEqual([call.args[1] for call in calls.call_args_list],[self.owners[0]])

    def test_shared_publication_only_marks_exact_teaching_class(self):
        self.enable(0);self.enable(1);self.plan()
        self.publish(self.keys[1]);self.assertEqual(self.dirty(),{self.owners[1]})

    def test_import_and_recurrence_updates_mark_owner_not_other_members(self):
        self.enable(0);self.enable(1);self.plan()
        with connect(self.db) as c:course_store.put_schedule(c,self.owners[0],self.data[0])
        self.assertEqual(self.dirty(),{self.owners[0]});self.clear_dirty()
        with connect(self.db) as c:
            c.execute('UPDATE course_meetings SET start_time=? WHERE member=?',('20:00',self.owners[0]))
        self.assertEqual(self.dirty(),{self.owners[0]})

    def test_previous_term_and_comments_do_not_trigger_planning(self):
        self.enable(0);self.plan()
        with connect(self.db) as c:course_store.put_schedule(c,self.owners[0],self.data[0],slot='previous')
        self.assertEqual(self.dirty(),set())

    def test_opt_out_and_logout_cancel_pending_work(self):
        self.enable(1);self.plan();self.assertTrue(self.jobs())
        with connect(self.db) as c:
            c.execute('DELETE FROM sessions WHERE member=?',(self.owners[1],))
            reminders.plan_dirty(c,self.now)
        self.assertEqual({r['state'] for r in self.jobs()},{'cancelled'})

    def test_completion_marks_only_completing_student(self):
        self.enable(0);self.enable(1);ident=self.publish();self.plan()
        with connect(self.db) as c:
            c.execute('INSERT INTO teaching_homework_status VALUES(?,?,?,?)',(self.owners[0],ident,'done','r1'))
        self.assertEqual(self.dirty(),{self.owners[0]})

    def test_read_snapshot_does_not_block_writes_and_race_stays_dirty(self):
        self.enable(0,course=False,newHomework=False);ident=self.personal(0);self.plan()
        with connect(self.db) as c:c.execute('UPDATE course_homework SET notes=? WHERE id=?',('first',ident))
        original=reminders.candidates;fired=[]
        def concurrent(c,member,now):
            result=original(c,member,now)
            if not fired:
                fired.append(True)
                with connect(self.db) as writer:
                    writer.execute('UPDATE course_homework SET completedAt=? WHERE id=?',('done',ident))
            return result
        with connect(self.db) as c,patch.object(reminders,'candidates',side_effect=concurrent):
            result=reminders.plan_dirty(c,self.now)
            self.assertTrue(result['remaining']);self.assertEqual(result['processed'],0)
        with connect(self.db) as c:reminders.plan_dirty(c,self.now)
        self.assertEqual(self.dirty(),set())
        self.assertEqual({r['state'] for r in self.jobs()},{'cancelled'})

    def test_dirty_marker_survives_restart_and_is_not_an_event_log(self):
        self.enable(0);self.plan();self.personal(0)
        with connect(self.db) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM push_changes').fetchone()[0],1)
        with connect(self.db) as c:reminders.plan_dirty(c,self.now)
        first=[r['id'] for r in self.jobs()]
        with connect(self.db) as c:reminder_changes.enqueue_active(c,self.now);reminders.plan_dirty(c,self.now)
        self.assertEqual([r['id'] for r in self.jobs()],first)

    def test_fallback_catches_rolling_horizon_without_business_writes(self):
        self.enable(0,course=False,newHomework=False,homeworkDue=False)
        clock=Clock(self.now);scheduler=Scheduler(clock.time,clock.monotonic)
        with connect(self.db) as c,patch.object(reminders,'candidates',wraps=reminders.candidates) as calls:
            scheduler.step(c,self.cfg,lambda *a:201);self.assertEqual(calls.call_count,1)
            clock.advance(FALLBACK_SECONDS);scheduler.step(c,self.cfg,lambda *a:201)
            self.assertEqual(calls.call_count,2)

    def test_sender_drains_a_bounded_batch_instead_of_one_per_two_seconds(self):
        self.enable(0,course=False,newHomework=False)
        for _ in range(SEND_BATCH+2):self.personal(0)
        clock=Clock(self.now);scheduler=Scheduler(clock.time,clock.monotonic);sent=[]
        with connect(self.db) as c:
            first=scheduler.step(c,self.cfg,lambda *a:sent.append(a[1]) or 201)
            self.assertEqual(len(sent),SEND_BATCH);self.assertEqual(first['deliveryAttempts'],SEND_BATCH)
            self.assertLessEqual(first['delay'],.05)
            clock.advance(first['delay']);scheduler.step(c,self.cfg,lambda *a:sent.append(a[1]) or 201)
        self.assertEqual(len(sent),SEND_BATCH+2)
        self.assertEqual(len({r['id'] for r in sent}),len(sent))

    def test_sender_time_budget_yields_after_slow_network(self):
        self.enable(0,course=False,newHomework=False)
        for _ in range(3):self.personal(0)
        clock=Clock(self.now);scheduler=Scheduler(clock.time,clock.monotonic);sent=[]
        def slow(*args):sent.append(args[1]);clock.advance(1.1);return 201
        with connect(self.db) as c:result=scheduler.step(c,self.cfg,slow)
        self.assertEqual(len(sent),1);self.assertEqual(result['deliveryAttempts'],1)

    def test_web_and_authenticated_ai_writes_both_mark_same_owner(self):
        self.enable(0,course=False,newHomework=False);self.plan()
        task={k:'' for k in course_store.TASK_FIELDS};task.update(id='web-dirty-task',title='网页作业',courseId='class-0')
        response=self.call('/api/homework',{'owner':self.owners[0],'task':task,'expected':None},cookie=self.cookies[0])
        self.assertEqual(response[0],200,response);self.assertEqual(self.dirty(),{self.owners[0]});self.clear_dirty()
        token='kj_ai_'+'a'*43
        with connect(self.db) as c:
            c.execute('INSERT INTO ai_connections(id,member,name,mode,token_hash,prefix,expires_at,revoked_at,created_at,last_used_at,revision,request_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                ('scheduler-ai',self.owners[0],'测试','delegate',agent.digest(token),token[:10],0,'',agent.now(),None,'r1','scheduler-ai-test-key'))
        task={**task,'id':'ai-dirty-task','title':'AI作业'};raw=json.dumps({'task':task,'expected':None}).encode();captured={}
        env={'PATH_INFO':agent.PREFIX+'/homework','REQUEST_METHOD':'POST','CONTENT_TYPE':'application/json','CONTENT_LENGTH':str(len(raw)),
             'wsgi.input':BytesIO(raw),'HTTP_AUTHORIZATION':'Bearer '+token,'HTTP_IDEMPOTENCY_KEY':'scheduler-ai-homework-01'}
        body=b''.join(self.app(env,lambda s,h:captured.update(status=int(s[:3]))))
        self.assertEqual(captured['status'],200,body);self.assertEqual(self.dirty(),{self.owners[0]})
