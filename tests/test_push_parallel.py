import collections
import json
import sqlite3
import threading
import time
import unittest
from unittest.mock import Mock,patch
from classroom import push,reminders
from classroom.app import connect
from classroom.push_dispatcher import ParallelSender,CONCURRENCY,ADMISSION_BATCH
from classroom.push_scheduler import Scheduler
from classroom import push_worker
import test_reminders as fixtures


class ParallelTests(unittest.TestCase):
    call=fixtures.ReminderTests.call
    api=fixtures.ReminderTests.api
    enable=fixtures.ReminderTests.enable
    personal=fixtures.ReminderTests.personal
    publish=fixtures.ReminderTests.publish
    plan=fixtures.ReminderTests.plan
    jobs=fixtures.ReminderTests.jobs

    def setUp(self):
        fixtures.ReminderTests.setUp(self)
        self.sender=ParallelSender(clock=lambda:self.now)
        self.release=threading.Event()

    def tearDown(self):
        self.release.set();self.sender.close()
        fixtures.ReminderTests.tearDown(self)

    def prepare(self,count=1,index=0):
        self.enable(index,course=False,newHomework=False)
        for _ in range(count):self.personal(index)
        self.plan()

    def drain(self,c,send,timeout=8):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            self.sender.pump(c,self.cfg,send)
            due=push.next_due(c)
            if not self.sender.pending and (due is None or due>self.now):return
            self.sender.pause(.02)
        self.fail('Queue did not drain')

    def test_maximum_five_requests_without_unbounded_executor_queue(self):
        self.prepare(12);active=0;peak=0;started=threading.Event();lock=threading.Lock()
        def blocked(*args):
            nonlocal active,peak
            with lock:
                active+=1;peak=max(peak,active)
                if active==CONCURRENCY:started.set()
            self.assertTrue(self.release.wait(5))
            with lock:active-=1
            return 201
        with connect(self.db) as c:
            first=self.sender.pump(c,self.cfg,blocked)
            self.assertTrue(started.wait(2));self.assertEqual(first['inflight'],5)
            for _ in range(3):self.sender.pump(c,self.cfg,blocked)
            self.assertEqual(len(self.sender.pending),5)
            self.assertEqual(c.execute("SELECT count(*) FROM push_jobs WHERE state='sending'").fetchone()[0],5)
            self.assertEqual(c.execute("SELECT count(*) FROM push_jobs WHERE state='scheduled'").fetchone()[0],7)
            self.release.set();self.drain(c,blocked)
        self.assertEqual(peak,5)

    def test_mixed_accounts_have_no_duplicates_omissions_or_cross_delivery(self):
        self.prepare(30,0);self.prepare(30,1)
        expected={r['id']:(r['member'],'https://web.push.apple.com/phone-'+str(self.owners.index(r['member']))) for r in self.jobs()}
        seen=[];lock=threading.Lock()
        def send(sub,payload,*args):
            # Reverse completion order repeatedly, without sharing a payload.
            time.sleep((int(payload['id'].replace('-','')[-2:],16)%3)*.001)
            with lock:seen.append((payload['id'],payload['owner'],sub['endpoint'],payload['url']))
            return 201
        with connect(self.db) as c:
            self.drain(c,send)
            self.sender.pump(c,self.cfg,send)
        self.assertEqual(len(seen),len(expected));self.assertEqual(len({r[0] for r in seen}),len(expected))
        for ident,member,endpoint,url in seen:
            self.assertEqual((member,endpoint),expected[ident]);self.assertIn('noticeOwner='+str(member),url)
        self.assertEqual({r['state'] for r in self.jobs()},{'accepted'})

    def test_exact_teaching_class_does_not_expand_for_administrator(self):
        self.enable(0,course=False,homeworkDue=False);self.enable(1,course=False,homeworkDue=False)
        ids={self.publish(self.keys[index]):self.owners[index] for index in (0,1) for _ in range(6)}
        self.plan();seen=[]
        with connect(self.db) as c:self.drain(c,lambda s,p,*a:seen.append((p['owner'],p['url'])) or 201)
        self.assertEqual(len(seen),12)
        for owner,url in seen:
            ident=next(i for i in ids if i in url);self.assertEqual(owner,ids[ident])

    def test_network_threads_never_use_the_sqlite_connection(self):
        self.prepare(5);main=threading.get_ident();network=set();db_threads=[];barrier=threading.Barrier(5)
        claim=push.claim;complete=push.complete
        def record_claim(*args):db_threads.append(threading.get_ident());return claim(*args)
        def record_complete(*args):db_threads.append(threading.get_ident());return complete(*args)
        def send(*args):network.add(threading.get_ident());barrier.wait(3);return 201
        with connect(self.db) as c,patch.object(push,'claim',side_effect=record_claim),patch.object(push,'complete',side_effect=record_complete):
            self.drain(c,send)
        self.assertEqual(set(db_threads),{main});self.assertEqual(len(network),5);self.assertNotIn(main,network)

    def test_slow_request_does_not_block_other_recipients(self):
        self.prepare(8);first=True;lock=threading.Lock();slow=threading.Event();fast=[]
        def send(sub,payload,*args):
            nonlocal first
            with lock:is_slow=first;first=False
            if is_slow:slow.set();self.release.wait(5)
            else:fast.append(payload['id'])
            return 201
        with connect(self.db) as c:
            end=time.monotonic()+3
            while c.execute("SELECT count(*) FROM push_jobs WHERE state='accepted'").fetchone()[0]<7 and time.monotonic()<end:
                self.sender.pump(c,self.cfg,send);self.sender.pause(.01)
            self.assertTrue(slow.is_set());self.assertEqual(len(fast),7)
            self.assertEqual(c.execute("SELECT count(*) FROM push_jobs WHERE state='accepted'").fetchone()[0],7)
            self.release.set();self.drain(c,send)

    def test_known_provider_busy_retries_only_affected_job_once_successful(self):
        self.prepare(6);calls=collections.Counter();accepted=collections.Counter();target=self.jobs()[0]['id']
        class Busy(Exception):status_code=429
        def send(sub,payload,*args):
            ident=payload['id'];calls[ident]+=1
            if ident==target and calls[ident]==1:raise Busy('Never log this')
            accepted[ident]+=1;return 201
        with connect(self.db) as c:
            self.drain(c,send)
            self.assertEqual(c.execute('SELECT state FROM push_jobs WHERE id=?',(target,)).fetchone()[0],'retry')
            self.now+=30;self.drain(c,send)
        self.assertEqual(calls[target],2);self.assertEqual(set(accepted.values()),{1});self.assertEqual(len(accepted),6)

    def test_uncertain_timeouts_are_recorded_without_blind_retry(self):
        self.prepare(7);calls=collections.Counter();target=self.jobs()[0]['id']
        def send(sub,payload,*args):
            calls[payload['id']]+=1
            if payload['id']==target:raise TimeoutError('Contains a private endpoint')
            return 201
        with connect(self.db) as c:
            self.drain(c,send);self.now+=35;self.drain(c,send)
            row=c.execute('SELECT state,error FROM push_jobs WHERE id=?',(target,)).fetchone()
        self.assertEqual(tuple(row),('unknown','NETWORK_OR_TIMEOUT'));self.assertEqual(set(calls.values()),{1})

    def test_cancelled_queued_jobs_are_not_sent(self):
        self.prepare(7)
        with connect(self.db) as c:
            c.execute("UPDATE push_jobs SET state='cancelled' WHERE id IN (SELECT id FROM push_jobs LIMIT 2)")
            seen=[];self.drain(c,lambda s,p,*a:seen.append(p['id']) or 201)
        self.assertEqual(len(seen),5)

    def test_late_completion_does_not_undo_inflight_cancellation(self):
        self.prepare();started=threading.Event()
        def send(*args):started.set();self.release.wait(5);return 201
        with connect(self.db) as c:
            self.sender.pump(c,self.cfg,send);self.assertTrue(started.wait(2))
            c.execute("UPDATE push_jobs SET state='cancelled'")
            self.release.set();self.sender.close();self.sender.reap(c)
            self.assertEqual(c.execute('SELECT state FROM push_jobs').fetchone()[0],'cancelled')

    def test_stale_gone_result_does_not_disable_rebound_device(self):
        self.prepare();started=threading.Event()
        class Gone(Exception):status_code=410
        def send(*args):started.set();self.release.wait(5);raise Gone()
        with connect(self.db) as c:
            self.sender.pump(c,self.cfg,send);self.assertTrue(started.wait(2))
            # Rebinding through the actual authenticated browser API cancels A.
            result=self.api('register',{'subscription':{**self.sub,'endpoint':'https://web.push.apple.com/phone-0'},'label':'iPhone / iPad'},1)
            self.assertEqual(result[0],200,result)
            self.release.set();self.sender.close();self.sender.reap(c)
            device=c.execute('SELECT member,active FROM push_devices WHERE id=?',(self.devices[0],)).fetchone()
            self.assertEqual(tuple(device),(self.owners[1],1))
            self.assertEqual(c.execute('SELECT state FROM push_jobs').fetchone()[0],'cancelled')

    def test_database_completion_failure_retries_write_without_resending(self):
        self.prepare();calls=[]
        with connect(self.db) as c:
            self.sender.pump(c,self.cfg,lambda s,p,*a:calls.append(p['id']) or 201)
            self.sender.close()
            with patch.object(push,'complete',side_effect=sqlite3.OperationalError('database is locked')):
                with self.assertRaises(sqlite3.OperationalError):self.sender.reap(c)
            self.assertEqual(len(self.sender.pending),1)
            self.sender.reap(c);self.assertFalse(self.sender.pending)
            self.assertEqual(c.execute('SELECT state FROM push_jobs').fetchone()[0],'accepted')
        self.assertEqual(len(calls),1)

    def test_restart_does_not_repeat_requests_with_lost_completion(self):
        self.prepare(5);calls=[]
        with connect(self.db) as c:
            self.sender.pump(c,self.cfg,lambda s,p,*a:calls.append(p['id']) or 201)
            self.sender.close()  # Simulate process death before result persistence.
            push.maintain(c,self.now+61)
            replacement=ParallelSender(clock=lambda:self.now+61)
            try:
                replacement.pump(c,self.cfg,lambda *args:self.fail('Uncertain request repeated'))
                self.assertEqual({r[0] for r in c.execute('SELECT state FROM push_jobs')},{'unknown'})
            finally:replacement.close()
        self.assertEqual(len(calls),5)

    def test_expiry_between_claim_and_network_skips_request(self):
        self.prepare()
        with connect(self.db) as c:
            delivery=push.claim(c,self.now)
            outcome=push.deliver(delivery,self.cfg,lambda *a:self.fail('Expired request sent'),lambda:delivery['job']['expires'])
            push.complete(c,delivery,outcome,delivery['job']['expires'])
            self.assertEqual(c.execute('SELECT state FROM push_jobs').fetchone()[0],'expired')

    def test_full_pool_waits_for_completion_instead_of_busy_polling(self):
        self.prepare(8);scheduler=Scheduler(clock=lambda:self.now,dispatcher=self.sender)
        def send(*args):self.release.wait(5);return 201
        with connect(self.db) as c:
            result=scheduler.step(c,self.cfg,send)
            self.assertEqual(len(self.sender.pending),5);self.assertGreater(result['delay'],1)
            self.release.set();self.sender.pause(2)
            self.drain(c,lambda *a:201)

    def test_discarded_jobs_still_have_bounded_admission(self):
        self.prepare(25)
        with connect(self.db) as c:
            c.execute('UPDATE sessions SET expires=?',(self.now-1,))
            result=self.sender.pump(c,self.cfg,lambda *a:self.fail('Expired login sent'))
            self.assertEqual(result['admitted'],ADMISSION_BATCH)
            self.assertFalse(self.sender.pending)
            self.assertEqual(c.execute("SELECT count(*) FROM push_jobs WHERE state='cancelled'").fetchone()[0],ADMISSION_BATCH)

    def test_graceful_close_completes_all_claimed_results(self):
        self.prepare(5)
        with connect(self.db) as c:
            self.sender.pump(c,self.cfg,lambda *a:201)
            self.sender.close();self.assertEqual(self.sender.reap(c),5)
            self.assertEqual({r[0] for r in c.execute('SELECT state FROM push_jobs')},{'accepted'})

    def test_submission_error_after_enqueue_does_not_blindly_repeat_request(self):
        self.prepare();calls=[];submit=self.sender.pool.submit
        def ambiguous(*args,**kwargs):
            submit(*args,**kwargs)
            raise RuntimeError('A thread-start error after enqueue')
        with connect(self.db) as c:
            with patch.object(self.sender.pool,'submit',side_effect=ambiguous):
                with self.assertRaises(RuntimeError):
                    self.sender.pump(c,self.cfg,lambda s,p,*a:calls.append(p['id']) or 201)
            self.sender.close()
            row=c.execute('SELECT state,error FROM push_jobs').fetchone()
            self.assertEqual(tuple(row),('unknown','DISPATCH_UNCERTAIN'))
            self.now+=35
            self.sender.pump(c,self.cfg,lambda *a:self.fail('Uncertain submission repeated'))
        self.assertEqual(len(calls),1)

    def test_old_completion_cannot_replace_a_newer_attempt(self):
        self.prepare()
        with connect(self.db) as c:
            delivery=push.claim(c,self.now)
            c.execute('UPDATE push_jobs SET attempts=attempts+1')
            push.complete(c,delivery,('accepted',201,''),self.now)
            self.assertEqual(c.execute('SELECT state FROM push_jobs').fetchone()[0],'sending')

    def test_database_error_backoff_cannot_be_bypassed_by_completed_requests(self):
        config=self.db.parent/'fake-push-config.json';config.write_text(json.dumps(self.cfg))
        stopped=False;waited=[]
        class Stop:
            def is_set(self):return stopped
            def set(self):pass
            def wait(self,seconds):
                nonlocal stopped
                waited.append(seconds);stopped=True
        sender=Mock();sender.pause.side_effect=AssertionError('Completed request bypassed DB backoff')
        scheduler=Mock();scheduler.step.side_effect=sqlite3.OperationalError('database is locked')
        connection=Mock()
        environment={'KEJIAN_DB':'/var/lib/kejian-test/fake-backoff.sqlite3','KEJIAN_BASE':'/mem-test/','KEJIAN_PUSH_CONFIG':str(config)}
        real_path=push_worker.Path
        def worker_path(value):
            if value==environment['KEJIAN_DB']:
                fake=Mock();fake.resolve.return_value=real_path(value);return fake
            return real_path(value)
        with patch.dict(push_worker.os.environ,environment),patch.object(push_worker,'validate_config'),\
             patch.object(push_worker,'ParallelSender',return_value=sender),patch.object(push_worker,'Scheduler',return_value=scheduler),\
             patch.object(push_worker,'connect',return_value=connection),patch.object(push_worker.signal,'signal'),\
             patch.object(push_worker.threading,'Event',return_value=Stop()),patch.object(push_worker,'Path',side_effect=worker_path),patch('builtins.print'):
            push_worker.main()
        self.assertEqual(waited,[5]);sender.pause.assert_not_called()
        sender.close.assert_called_once();sender.reap.assert_called_once_with(connection)
