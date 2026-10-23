import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {chinaClock,addDays,monday,weekNumber,eventState,nextEvent,weekEvents,expandEvents,campusVisits,nextCampusVisit,eventPeriod,weekday,escapeHTML,courseTimeSummary,classTimeLabel} from '../public/schedule.mjs';

const data=JSON.parse(readFileSync(new URL('../examples/demo-schedule.json',import.meta.url)));

test('Shanghai clock, cross-year dates and teaching weeks are independent of device timezone',()=>{
 assert.deepEqual(chinaClock(new Date('2026-10-16T16:00:00Z')),{date:'2026-10-17',time:'00:00'});
 assert.equal(monday('2027-01-10'),'2027-01-04');
 assert.equal(addDays('2026-12-31',1),'2027-01-01');
 assert.equal(weekNumber('2027-01-17'),18);
});
test('same course and same teacher retain distinct teaching-class times',()=>{
 const groups=['demo-systems-a','demo-systems-b'].map(course_id=>({sessions:data.events.filter(e=>e.course_id===course_id)}));
 assert.equal(courseTimeSummary(groups[0]),'周六上午 08:50–12:25');
 assert.equal(courseTimeSummary(groups[1]),'周六下午 13:25–17:00');
});
test('pending fieldwork and unknown course times are not fabricated',()=>{
 assert.equal(classTimeLabel(data.events.find(e=>e.kind==='fieldwork')),'实践时间待通知');
 assert.equal(courseTimeSummary({sessions:[]}), '上课时间待通知');
});
test('next class advances at its actual end and fieldwork stays pending',()=>{
 const first=data.events[0];
 assert.equal(eventState(first,{date:first.date,time:'08:49'}),'today');
 assert.equal(eventState(first,{date:first.date,time:'08:50'}),'live');
 assert.equal(eventState(first,{date:first.date,time:'12:25'}),'past');
 assert.equal(nextEvent(data.events,{date:first.date,time:'12:25'}).course_id,'demo-systems-b');
 const practice=nextEvent(data.events,{date:'2026-11-15',time:'10:00'});
 assert.equal(practice.kind,'fieldwork');assert.equal(practice.start_time,null);
 assert.equal(nextEvent(data.events,{date:'2027-01-18',time:'00:00'}),null);
});
test('weekly overview includes both teaching classes, empty weeks and January',()=>{
 assert.equal(weekEvents(data.events,'2026-10-12').length,2);
 assert.equal(weekEvents(data.events,'2026-10-19').length,0);
 assert.equal(weekEvents(data.events,'2027-01-11').length,1);
 assert.equal(weekEvents(data.events,'2026-11-09').filter(e=>e.kind==='fieldwork').length,1);
});
test('weekly rules retain unknown ends, exclusions and a later confirmed end',()=>{
 const events=expandEvents(data),english=events.filter(e=>e.kind==='online');
 assert.equal(english[0].date,'2026-09-22');
 assert.ok(english.every(e=>weekday(e.date)===1&&e.start_time==='19:00'&&e.end_time===null&&e.provisional));
 assert.equal(weekEvents(events,'2026-09-14').length,0);
 assert.equal(weekEvents(events,'2026-10-19').length,1);
 const bounded={...data,courses:data.courses.map(c=>c.recurrence?{...c,recurrence:{...c.recurrence,until:'2026-10-20',excluded_dates:['2026-10-06']}}:c)};
 const online=expandEvents(bounded).filter(e=>e.kind==='online');
 assert.equal(online.length,4);assert.ok(online.every(e=>e.date<='2026-10-20'&&!e.provisional));
 assert.equal(courseTimeSummary(data.courses.find(c=>c.recurrence)),'每周二晚上 19:00 · 结束待定');
});
test('unknown class end does not create an ongoing state overnight',()=>{
 const e=expandEvents(data).find(e=>e.kind==='online'&&e.date==='2026-10-13');
 assert.equal(eventState(e,{date:e.date,time:'18:59'}),'today');
 assert.equal(eventState(e,{date:e.date,time:'19:00'}),'started_unknown_end');
 assert.equal(eventState(e,{date:e.date,time:'23:59'}),'started_unknown_end');
 assert.equal(eventState(e,{date:'2026-10-14',time:'00:00'}),'past');
});
test('campus visits exclude online and fieldwork while retaining consecutive January weeks',()=>{
 const events=expandEvents(data),visits=campusVisits(events);
 assert.equal(visits.length,4);
 assert.equal(nextCampusVisit(events,{date:'2026-10-13',time:'10:00'}).start,'2026-10-17');
 assert.equal(nextCampusVisit(events,{date:'2026-10-17',time:'17:00'}).start,'2026-10-31');
 assert.deepEqual(visits.at(-2).dates,['2027-01-09']);
 assert.equal(nextCampusVisit(events,{date:'2027-01-09',time:'12:25'}).start,'2027-01-16');
 assert.equal(nextCampusVisit(events,{date:'2027-01-17',time:'17:00'}),null);
});
test('grid uses actual slots and keeps fieldwork without a slot',()=>{
 const events=expandEvents(data);
 assert.equal(eventPeriod(events.find(e=>e.kind==='online')),'evening');
 assert.equal(eventPeriod(events.find(e=>e.kind==='fieldwork')),'pending');
 assert.equal(eventPeriod(events.find(e=>e.course_id==='demo-systems-a')),'morning');
 assert.equal(eventPeriod(events.find(e=>e.course_id==='demo-systems-b')),'afternoon');
});
test('HTML supplied in a course title is escaped',()=>{
 assert.equal(escapeHTML('<a title="x">&'), '&lt;a title=&quot;x&quot;&gt;&amp;');
});
