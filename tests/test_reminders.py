from datetime import datetime,timedelta,timezone
import json
import unittest
import uuid
from unittest.mock import patch
from classroom import push,reminders,course_store,community,course_homework
from classroom.app import connect
from test_push import PushTests


class ReminderTests(unittest.TestCase):
    tearDown=PushTests.tearDown
    call=PushTests.call
    api=PushTests.api

    def setUp(self):
        PushTests.setUp(self)
        self.now=self.now//60*60
        self.devices=[];self.data=[];self.keys=[]
        for index in (0,1):
            sub={**self.sub,'endpoint':'https://web.push.apple.com/phone-'+str(index)}
            self.devices.append(self.api('register',{'subscription':sub,'label':'iPhone / iPad'},index)[2]['deviceId'])
            start=datetime.fromtimestamp(self.now+(1800 if index==0 else 7200),reminders.ZONE)
            cid='class-'+str(index)
            data={**course_store.empty(self.owners[index]),'version':'reminder-fixture',
                  'courses':[{'id':cid,'name':'同名课程','teacher':'同一老师','location':'教室'+str(index)}],
                  'events':[{'id':'meeting-'+str(index),'course_id':cid,'course_name':'同名课程','teacher':'同一老师',
                             'date':start.date().isoformat(),'start_time':start.strftime('%H:%M'),'end_time':None,
                             'location':'教室'+str(index),'kind':'class','status':'scheduled'}]}
            self.data.append(data)
            with connect(self.db) as c:
                course_store.put_schedule(c,self.owners[index],data)
                key=community.write_template(c,self.owners[0],data,data['courses'][0],published=True)
                self.keys.append(key)
                c.execute('INSERT INTO teaching_enrollments VALUES(?,?,?,1,?,?)',
                          (self.owners[index],key,cid,'reminder-fixture',datetime.fromtimestamp(self.now-3600,timezone.utc).isoformat()))
        with connect(self.db) as c:c.execute('INSERT INTO class_admins VALUES(?)',(self.owners[0],))

    def enable(self,index=0,**settings):
        with connect(self.db) as c:
            device=c.execute('SELECT * FROM push_devices WHERE id=?',(self.devices[index],)).fetchone()
            reminders.toggle_device(c,self.owners[index],device,True,self.now-120)
            if settings:
                before=reminders.preferences(c,self.owners[index]);desired={**before['settings'],**settings}
                reminders.save_preferences(c,self.owners[index],{'expected':before['revision'],'settings':desired},self.now-120)

    def publish(self,key=None,offset=86400,clock=True):
        due=datetime.fromtimestamp(self.now+offset,reminders.ZONE)
        task={'title':'范围测试作业','notes':'阅读第一章','submission':'线下交到教室',
              'dueDate':due.date().isoformat(),'dueTime':due.strftime('%H:%M') if clock else ''}
        ident='coursework-'+uuid.uuid4().hex
        with connect(self.db) as c,patch.object(community,'now',return_value=datetime.fromtimestamp(self.now,timezone.utc).isoformat()):
            course_homework.change(c,self.owners[0],{'action':'save','key':key or self.keys[0],'id':ident,'expected':None,'task':task})
        return ident

    def personal(self,index=0,offset=86400):
        due=datetime.fromtimestamp(self.now+offset,reminders.ZONE);ident=str(uuid.uuid4())
        task={k:'' for k in course_store.TASK_FIELDS}
        task.update(id=ident,title='自己的作业',courseId='class-'+str(index),dueDate=due.date().isoformat(),dueTime=due.strftime('%H:%M'),revision=str(uuid.uuid4()),createdAt=datetime.fromtimestamp(self.now,timezone.utc).isoformat())
        with connect(self.db) as c:course_store.put_task(c,self.owners[index],task)
        return ident

    def jobs(self,kind=None):
        with connect(self.db) as c:
            rows=c.execute('SELECT j.*,r.kind FROM push_jobs j JOIN push_reminders r ON r.id=j.reminder_id ORDER BY j.due,j.member').fetchall()
            return [dict(r) for r in rows if kind is None or r['kind']==kind]

    def dispatch(self,at=None,callback=None):
        sent=[]
        def send(sub,payload,*args):
            sent.append((sub['endpoint'],payload))
            if callback:callback(payload)
            return 201
        with connect(self.db) as c:
            for _ in range(15):push.tick(c,self.cfg,send,self.now if at is None else at)
        return sent

    def plan(self,at=None):
        with connect(self.db) as c:reminders.plan(c,self.now if at is None else at)

    def test_existing_permission_does_not_enable_business_reminders(self):
        self.publish();self.plan()
        self.assertEqual(self.jobs(),[])
        self.enable(0);self.plan()
        self.assertTrue(self.jobs());self.assertEqual({r['member'] for r in self.jobs()},{self.owners[0]})

    def test_same_name_teacher_different_class_and_admin_do_not_broadcast(self):
        self.enable(0);self.enable(1);ident=self.publish();self.plan()
        jobs=self.jobs('homework-new')
        self.assertEqual([r['member'] for r in jobs],[self.owners[0]])
        sent=self.dispatch()
        self.assertTrue(sent);self.assertEqual({url for url,p in sent},{'https://web.push.apple.com/phone-0'})
        for url,p in sent:self.assertIn('noticeOwner='+str(self.owners[0]),p['url'])
        self.assertTrue(any(ident in p['url'] for _,p in sent))
        # Admin A is not enrolled in B's offering, so does not receive its publication.
        self.publish(self.keys[1]);self.plan()
        self.assertEqual([r['member'] for r in self.jobs('homework-new')],[self.owners[0],self.owners[1]])

    def test_course_uses_personal_schedule_and_only_current_term(self):
        self.enable(0,newHomework=False,homeworkDue=False);self.enable(1,newHomework=False,homeworkDue=False)
        self.plan();sent=self.dispatch()
        self.assertEqual([u for u,p in sent],['https://web.push.apple.com/phone-0'])
        self.assertIn('教室0',sent[0][1]['body']);self.assertIn('event=meeting-0',sent[0][1]['url'])
        self.assertEqual([r['state'] for r in self.jobs('course')],['accepted','scheduled'])

    def test_personal_homework_does_not_leak_to_another_member(self):
        self.enable(0,course=False,newHomework=False);self.enable(1,course=False,newHomework=False)
        ident=self.personal(0);self.plan();sent=self.dispatch()
        self.assertEqual(len(sent),1);self.assertTrue(sent[0][0].endswith('phone-0'));self.assertIn(ident,sent[0][1]['url'])

    def test_shared_completion_is_per_member(self):
        self.enable(0,course=False,newHomework=False);self.enable(1,course=False,newHomework=False)
        ident=self.publish()
        with connect(self.db) as c:
            c.execute('INSERT INTO teaching_enrollments VALUES(?,?,?,1,?,?)',(self.owners[1],self.keys[0],'class-0','fixture',datetime.fromtimestamp(self.now-3600,timezone.utc).isoformat()))
            c.execute('INSERT INTO teaching_homework_status VALUES(?,?,?,?)',(self.owners[0],ident,'done',str(uuid.uuid4())))
        self.plan();sent=self.dispatch()
        self.assertEqual([u for u,p in sent],['https://web.push.apple.com/phone-1'])

    def test_completed_or_deleted_personal_task_is_cancelled_before_send(self):
        self.enable(0,course=False,newHomework=False)
        ident=self.personal(0,86460);self.plan()
        with connect(self.db) as c:c.execute('UPDATE course_homework SET completedAt=? WHERE member=? AND id=?',('done',self.owners[0],ident))
        self.assertEqual(self.dispatch(self.now+60),[])
        self.assertEqual(self.jobs()[0]['state'],'cancelled')

    def test_unsubscribe_and_withdrawal_are_checked_again_at_dispatch(self):
        self.enable(0,course=False,homeworkDue=False);ident=self.publish();self.plan()
        with connect(self.db) as c:c.execute('UPDATE teaching_enrollments SET active=0 WHERE member=? AND offering=?',(self.owners[0],self.keys[0]))
        self.assertEqual(self.dispatch(),[]);self.assertEqual(self.jobs()[0]['state'],'cancelled')
        with connect(self.db) as c:c.execute('UPDATE teaching_enrollments SET active=1 WHERE member=? AND offering=?',(self.owners[0],self.keys[0]))
        self.publish();self.plan()
        with connect(self.db) as c:c.execute("UPDATE teaching_homework SET deleted_at='withdrawn'")
        self.assertEqual(self.dispatch(),[])

    def test_unpublished_offering_is_not_notified(self):
        self.enable(0);self.publish()
        with connect(self.db) as c:c.execute('UPDATE teaching_offerings SET published=0 WHERE key=?',(self.keys[0],))
        self.plan();self.assertEqual(self.jobs('homework-new'),[]);self.assertEqual(self.jobs('homework-due'),[])

    def test_deadline_change_cancels_old_job_and_updates_target_time(self):
        self.enable(0,course=False,newHomework=False);ident=self.personal(0,86460);self.plan()
        with connect(self.db) as c:
            next_due=datetime.fromtimestamp(self.now+86580,reminders.ZONE)
            c.execute('UPDATE course_homework SET dueDate=?,dueTime=? WHERE member=? AND id=?',(next_due.date().isoformat(),next_due.strftime('%H:%M'),self.owners[0],ident))
        self.plan();jobs=self.jobs('homework-due')
        self.assertEqual(len(jobs),2);self.assertEqual(jobs[0]['state'],'cancelled');self.assertEqual(jobs[1]['due'],self.now+180)
        self.assertEqual(self.dispatch(self.now+60),[]);self.assertEqual(len(self.dispatch(self.now+180)),1)

    def test_setting_offset_change_creates_new_correctly_timed_job(self):
        self.enable(0,newHomework=False,homeworkDue=False);self.plan()
        with connect(self.db) as c:
            old=reminders.preferences(c,self.owners[0]);reminders.save_preferences(c,self.owners[0],{'expected':old['revision'],'settings':{**old['settings'],'courseMinutes':15}},self.now)
        self.plan();jobs=self.jobs('course')
        self.assertEqual([r['state'] for r in jobs],['cancelled','scheduled']);self.assertEqual(jobs[1]['due'],self.now+900)

    def test_no_assumed_midnight_or_2359_for_unknown_time(self):
        self.enable(0,course=False,newHomework=False)
        tomorrow=datetime.fromtimestamp(self.now,reminders.ZONE).date()+timedelta(days=1)
        ident=self.personal(0)
        with connect(self.db) as c:c.execute('UPDATE course_homework SET dueDate=?,dueTime=? WHERE member=? AND id=?',(tomorrow.isoformat(),'',self.owners[0],ident))
        with connect(self.db) as c:
            items=reminders.homework_candidates(c,self.owners[0],reminders.DEFAULTS,self.now)
            item=next(items);expected=reminders.stamp((tomorrow-timedelta(days=1)).isoformat(),'12:00')
            self.assertEqual(item['due'],expected);self.assertIn('具体时间待定',item['payload']['body']);self.assertNotIn('23:59',item['payload']['body'])

    def test_undetermined_class_time_is_skipped_and_nominal_slot_is_not_used(self):
        self.enable(0)
        with connect(self.db) as c:c.execute("UPDATE course_meetings SET start_time=NULL WHERE member=?",(self.owners[0],))
        self.plan();self.assertEqual(self.jobs('course'),[])

    def test_course_homework_without_clock_uses_previous_day_noon_for_both_offsets(self):
        self.enable(0,course=False,newHomework=False)
        ident=self.publish(clock=False)
        with connect(self.db) as c:
            date=c.execute('SELECT due_date FROM teaching_homework WHERE id=?',(ident,)).fetchone()[0]
            previous=(datetime.fromisoformat(date).date()-timedelta(days=1)).isoformat()
            for hours in (2,24):
                items=reminders.homework_candidates(c,self.owners[0],{**reminders.DEFAULTS,'newHomework':False,'homeworkHours':hours},self.now)
                item=next(r for r in items if r['source_key']=='course:'+ident)
                self.assertEqual(item['due'],reminders.stamp(previous,'12:00'))
                self.assertIn('具体时间待定',item['payload']['body'])

    def test_service_restart_deduplicates_and_old_publications_are_not_replayed(self):
        self.publish();self.enable(0,course=False,newHomework=True,homeworkDue=False)
        with connect(self.db) as c:c.execute('UPDATE push_preferences SET published_since=?',(self.now+1,))
        self.plan();self.assertEqual(self.jobs(),[])
        with connect(self.db) as c:c.execute('UPDATE push_preferences SET published_since=?',(self.now-1,))
        self.plan();first=self.jobs()
        with connect(self.db) as c:push.schema(c);reminders.plan(c,self.now)
        self.assertEqual([j['id'] for j in self.jobs()],[j['id'] for j in first])

    def test_disable_device_cancels_business_only_and_reenable_keeps_future_delivery(self):
        self.enable(0,newHomework=False,homeworkDue=False)
        with connect(self.db) as c:
            c.execute('UPDATE course_meetings SET start_time=? WHERE member=?',((datetime.fromtimestamp(self.now+2400,reminders.ZONE)).strftime('%H:%M'),self.owners[0]))
        self.plan()
        with connect(self.db) as c:
            device=c.execute('SELECT * FROM push_devices WHERE id=?',(self.devices[0],)).fetchone();reminders.toggle_device(c,self.owners[0],device,False,self.now+1)
            device=c.execute('SELECT * FROM push_devices WHERE id=?',(self.devices[0],)).fetchone();reminders.toggle_device(c,self.owners[0],device,True,self.now+2)
        self.plan(self.now+2)
        self.assertEqual(sorted(j['state'] for j in self.jobs()),['cancelled','scheduled'])
        self.assertEqual(len(self.dispatch(self.now+600)),1)

    def test_receipt_after_membership_change_suppresses_content(self):
        self.enable(0,course=False,homeworkDue=False);self.publish();self.plan()
        def revoke(payload):
            with connect(self.db) as c:c.execute('UPDATE teaching_enrollments SET active=0 WHERE member=?',(self.owners[0],))
        sent=self.dispatch(callback=revoke);self.assertEqual(len(sent),1)
        p=sent[0][1]
        result=self.api('receipt',{'id':p['id'],'receipt':p['receipt'],'stage':'received'})
        self.assertEqual(result[0],200);self.assertFalse(result[2]['display'])

    def test_settings_and_device_changes_are_scoped_and_concurrent_safe(self):
        response=self.api('reminder-settings');self.assertEqual(response[0],200)
        self.assertEqual(self.api('reminders-enable',{'deviceId':self.devices[1]})[0],403)
        body={'settings':{**reminders.DEFAULTS,'courseMinutes':15},'expected':None}
        self.assertEqual(self.api('reminder-settings-save',body)[0],200)
        self.assertEqual(self.api('reminder-settings-save',body)[0],409)
        self.assertEqual(self.api('reminder-settings-save',{**body,'owner':self.owners[1]})[0],403)
        mac=self.api('register',{'subscription':{**self.sub,'endpoint':'https://web.push.apple.com/mac'},'label':'电脑浏览器'})[2]['deviceId']
        self.assertEqual(self.api('reminders-enable',{'deviceId':mac})[0],400)

    def test_rebinding_clears_previous_business_opt_in(self):
        self.enable(0)
        sub={**self.sub,'endpoint':'https://web.push.apple.com/phone-0'}
        response=self.api('register',{'subscription':sub,'label':'iPhone / iPad'},1)
        self.assertEqual(response[0],200);self.assertFalse(response[2]['remindersEnabled'])
        with connect(self.db) as c:reminders.plan(c,self.now)
        self.assertEqual(self.jobs(),[])

    def test_recurring_course_exclusions_and_previous_term_are_respected(self):
        self.enable(0,newHomework=False,homeworkDue=False)
        data=self.data[0];start=datetime.fromtimestamp(self.now+1800,reminders.ZONE)
        data['courses'][0]['recurrence']={'weekday':start.isoweekday(),'starts_on':start.date().isoformat(),
                'until':None,'start_time':start.strftime('%H:%M'),'end_time':None,'source':'confirmed','excluded_dates':[start.date().isoformat()]}
        data['events']=[]
        with connect(self.db) as c:
            course_store.put_schedule(c,self.owners[0],self.data[1]|{'owner':self.owners[0]},slot='previous')
            course_store.put_schedule(c,self.owners[0],data)
        self.plan();self.assertEqual(self.jobs('course'),[])
        data['courses'][0]['recurrence']['excluded_dates']=[]
        with connect(self.db) as c:course_store.put_schedule(c,self.owners[0],data)
        self.plan();sent=self.dispatch();self.assertEqual(len(sent),1);self.assertIn('线上',sent[0][1]['body'])

    def test_disabling_category_or_logging_out_suppresses_pending_notifications(self):
        self.enable(0,course=False,homeworkDue=False);self.publish();self.plan()
        with connect(self.db) as c:
            old=reminders.preferences(c,self.owners[0]);reminders.save_preferences(c,self.owners[0],{'expected':old['revision'],'settings':{**old['settings'],'newHomework':False}},self.now)
        self.assertEqual(self.dispatch(),[])
        self.enable(0,course=False,newHomework=True,homeworkDue=False);self.publish();self.plan()
        self.assertEqual(self.call('/api/logout',{'owner':self.owners[0]},cookie=self.cookies[0])[0],200)
        self.assertEqual(self.dispatch(),[])

    def test_sender_offline_does_not_replay_expired_reminders_after_restart(self):
        self.enable(0);self.publish();self.personal(0);self.plan()
        self.assertTrue(self.jobs());self.assertEqual(self.dispatch(self.now+7200),[])

    def test_notification_body_is_bounded_for_web_push_payload_size(self):
        self.enable(0,course=False,homeworkDue=False);self.publish()
        with connect(self.db) as c:c.execute('UPDATE teaching_offerings SET name=?,teacher=? WHERE key=?',('长课程'*700,'老师'*800,self.keys[0]))
        self.plan();sent=self.dispatch();self.assertEqual(len(sent),1)
        self.assertLess(len(json.dumps(sent[0][1],ensure_ascii=False).encode()),3000)

    def test_expired_inactive_device_cleanup_also_cleans_device_preferences(self):
        self.enable(0)
        with connect(self.db) as c:
            push.deactivate(c,device=self.devices[0]);c.execute('UPDATE push_devices SET updated=? WHERE id=?',(self.now-31*86400,self.devices[0]))
            push.tick(c,self.cfg,lambda *args:self.fail('Unexpected send'),self.now)
            self.assertEqual(c.execute('SELECT count(*) FROM push_device_preferences WHERE device=?',(self.devices[0],)).fetchone()[0],0)

    def test_manual_test_and_cancel_do_not_block_or_cancel_business_reminders(self):
        self.enable(0,newHomework=False,homeworkDue=False);self.plan()
        response=self.api('test',{'deviceId':self.devices[0],'requestKey':'manual-alongside-business-test'})
        self.assertEqual(response[0],200,response);self.assertEqual(len(response[2]['jobs']),1)
        self.assertEqual(self.api('cancel',{'deviceId':self.devices[0]})[0],200)
        self.assertEqual(self.jobs('course')[0]['state'],'scheduled')

    def test_notification_text_is_never_persisted_before_or_after_delivery(self):
        self.enable(0,course=False,homeworkDue=False);self.publish();self.plan()
        with connect(self.db) as c:
            self.assertEqual([r[0] for r in c.execute('SELECT payload FROM push_reminders')],['{}'])
        sent=self.dispatch();self.assertEqual(len(sent),1)
        self.assertIn('范围测试作业',sent[0][1]['body'])
        with connect(self.db) as c:
            self.assertEqual([r[0] for r in c.execute('SELECT payload FROM push_reminders')],['{}'])

    def test_migration_erases_legacy_notification_text_without_changing_bindings(self):
        self.enable(0,course=False,homeworkDue=False);self.publish();self.plan()
        with connect(self.db) as c:
            binding=[tuple(r) for r in c.execute('SELECT * FROM push_devices')]
            original=c.execute('SELECT notes FROM teaching_homework').fetchone()[0]
            c.execute('UPDATE push_reminders SET payload=?',(json.dumps({'title':'旧提醒','body':'不应保留的历史正文'}),))
            push.schema(c)
            self.assertEqual(c.execute('SELECT payload FROM push_reminders').fetchone()[0],'{}')
            self.assertEqual([tuple(r) for r in c.execute('SELECT * FROM push_devices')],binding)
            self.assertEqual(c.execute('SELECT notes FROM teaching_homework').fetchone()[0],original)

    def test_expiry_cleanup_preserves_dedup_then_removes_jobs_and_ledger(self):
        self.enable(0,course=False,homeworkDue=False);self.publish();self.plan();self.dispatch()
        original=self.jobs();self.assertEqual(len(original),1)
        self.plan(self.now+30);self.assertEqual([r['id'] for r in self.jobs()],[original[0]['id']])
        boundary=original[0]['expires']+push.DELIVERY_GRACE_SECONDS
        self.dispatch(boundary-1);self.assertEqual(len(self.jobs()),1)
        self.dispatch(boundary+1);self.assertEqual(self.jobs(),[])
        with connect(self.db) as c:self.assertEqual(c.execute('SELECT count(*) FROM push_reminders').fetchone()[0],0)
        self.plan(boundary+2);self.assertEqual(self.jobs(),[])

    def test_cleanup_uses_expiry_and_does_not_remove_old_but_future_work(self):
        self.enable(1,newHomework=False,homeworkDue=False);self.plan()
        with connect(self.db) as c:
            c.execute('UPDATE push_jobs SET created=?',(self.now-31*86400,))
            c.execute('UPDATE push_reminders SET created=?',(self.now-31*86400,))
        self.assertEqual(self.dispatch(),[])
        self.assertEqual(len(self.jobs()),1);self.assertEqual(self.jobs()[0]['state'],'scheduled')

    def test_cleanup_also_runs_for_disabled_devices_and_manual_tests(self):
        self.enable(0,course=False,homeworkDue=False);self.publish();self.plan()
        job=self.jobs()[0]
        manual=self.api('test',{'deviceId':self.devices[0],'requestKey':'cleanup-manual-test-unique'})
        self.assertEqual(manual[0],200)
        with connect(self.db) as c:push.deactivate(c,device=self.devices[0])
        self.dispatch(job['expires']+push.DELIVERY_GRACE_SECONDS+1)
        with connect(self.db) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM push_jobs').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT count(*) FROM push_reminders').fetchone()[0],0)

    def test_settings_response_only_lists_current_pending_work(self):
        self.enable(0)
        data=self.data[0]
        future=datetime.fromtimestamp(self.now+7200,reminders.ZONE)
        data['events'].append({**data['events'][0],'id':'later-meeting','date':future.date().isoformat(),'start_time':future.strftime('%H:%M')})
        with connect(self.db) as c:course_store.put_schedule(c,self.owners[0],data)
        self.plan();self.dispatch()
        with connect(self.db) as c:
            result=reminders.overview(c,self.owners[0],self.now)
        self.assertNotIn('recent',result)
        self.assertEqual(len(result['upcoming']),1)
        self.assertEqual(result['upcoming'][0]['state'],'pending')
        self.assertIn('event=later-meeting',result['upcoming'][0]['url'])
