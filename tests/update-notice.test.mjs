import {test} from 'node:test';
import assert from 'node:assert/strict';
import {updateNoticeHTML} from '../public/update-notice.mjs';
import {reminderSettingsHTML} from '../public/notification-settings-ui.mjs';
const base={user:{name:'测试同学',student:'2026000001'},model:{settings:{course:true,newHomework:true,homeworkDue:true,courseMinutes:30,homeworkHours:24},upcoming:[]},device:{enabled:true,remindersEnabled:true,jobs:[]},supported:true,ios:true,standalone:true,permission:'granted',busy:false};
test('the device card owns the short test action and collapsed delivery help',()=>{
 const html=reminderSettingsHTML(base);
 assert.match(html,/30 秒后/);assert.match(html,/测试一下/);assert.match(html,/<details class="reminder-receive-help">/);
 assert.ok(!html.includes('关于接收'));assert.ok(!html.includes('45秒'));assert.ok(!html.includes('reminder-upcoming-card'));
});
test('desktop has account settings but no nonfunctional device test action',()=>{
 const html=reminderSettingsHTML({...base,ios:false,supported:false,permission:'default'});
 assert.match(html,/仅支持 iOS 设备接收/);assert.ok(!html.includes('data-reminder-test'));assert.match(html,/提醒内容/);
});
test('a denied notification permission points to settings rather than another permission prompt',()=>{
 const html=reminderSettingsHTML({...base,permission:'denied'});
 assert.match(html,/系统设置/);assert.ok(!html.includes('data-reminder-connect'));
});
test('a queued test cannot be submitted repeatedly',()=>{
 const html=reminderSettingsHTML({...base,device:{...base.device,jobs:[{state:'scheduled'}]}});
 assert.match(html,/data-reminder-test disabled/);assert.match(html,/等待发送/);
});
test('the introduction explains the entry and opt in while escaping supplied copy',()=>{
 const html=updateNoticeHTML({eyebrow:'新功能',title:'<script>bad</script>',lead:'<img>',features:['上课前'],steps:[['找到入口','更多 → 消息提醒'],['开启','允许系统通知']],footnote:'iPhone / iPad'});
 assert.ok(!html.includes('<script>'));assert.ok(!html.includes('<img>'));assert.match(html,/更多 → 消息提醒/);
 assert.match(html,/aria-label="关闭更新介绍"/);assert.match(html,/data-update-open/);assert.match(html,/data-update-dismiss/);
});
