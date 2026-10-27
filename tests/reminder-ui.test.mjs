import {test} from 'node:test';
import assert from 'node:assert/strict';
import {reminderSettingsHTML} from '../public/notification-settings-ui.mjs';
import {notificationTarget} from '../public/notification-target.mjs';
const base={user:{name:'测试同学',student:'2026000001'},model:{settings:{course:true,newHomework:true,homeworkDue:true,courseMinutes:30,homeworkHours:24},revision:null,upcoming:[],recent:[]},device:{enabled:false,remindersEnabled:false},supported:true,ios:true,standalone:true,permission:'granted',busy:false};
test('iOS onboarding and device opt in are distinct from existing permission',()=>{
 assert.match(reminderSettingsHTML(base),/开启这台设备的提醒/);
 const connected=reminderSettingsHTML({...base,device:{enabled:true,remindersEnabled:false}});
 assert.match(connected,/data-reminder-setting="device"/);assert.ok(!connected.includes('aria-label="在这台设备接收提醒" checked'));
 assert.match(reminderSettingsHTML({...base,standalone:false,supported:false}),/添加到主屏幕/);
 assert.match(reminderSettingsHTML({...base,ios:false,supported:false}),/目前仅支持 iOS/);
});
test('settings use accessible custom switches and buttons rather than native selects',()=>{
 const html=reminderSettingsHTML(base);
 assert.match(html,/role="switch"/);assert.match(html,/前一天中午12:00/);assert.ok(!html.includes('<select'));
 assert.match(html,/只接收你已加入的那个教学班/);assert.match(html,/已完成的作业不再提醒/);
});
test('upcoming content is escaped and old response history is never displayed',()=>{
 const html=reminderSettingsHTML({...base,model:{...base.model,upcoming:[{id:'x',kind:'homework-new',title:'<img src=x>',body:'<script>',url:'./?noticeOwner=1&homework=x#homework',due:1792839600,state:'pending'}],recent:[{title:'不应显示的历史提醒'}]}});
 assert.ok(!html.includes('<script>'));assert.ok(!html.includes('<img'));assert.match(html,/noticeOwner=1&amp;homework=x/);
 assert.ok(!html.includes('最近的提醒'));assert.ok(!html.includes('不应显示的历史提醒'));
});
test('notification deep links cannot open a different account or confuse identical personal IDs',()=>{
 assert.deepEqual(notificationTarget('?noticeOwner=1&homework=same-id',3),{kind:'wrong-account'});
 assert.deepEqual(notificationTarget('?noticeOwner=3&homework=same-id',3),{kind:'homework',id:'same-id'});
 assert.deepEqual(notificationTarget('?noticeOwner=3&event=class-a-day',3),{kind:'event',id:'class-a-day'});
 assert.deepEqual(notificationTarget('?event=legacy-event',3),{kind:'event',id:'legacy-event'});
 assert.deepEqual(notificationTarget('?noticeOwner=NaN&homework=x',3),{kind:'wrong-account'});
});
