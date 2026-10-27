import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source=readFileSync(new URL('../public/push-sw.js',import.meta.url),'utf8');
const message={managed:true,environment:'production',scope:'/mem/',owner:17,id:'fixture-job',receipt:'fixture-receipt',title:'课程提醒',url:'./?noticeOwner=17&homework=fixture#homework'};
function runtime(scope='/mem/',display=true){
 const handlers={},notices=[],requests=[],actions=[];let pending;
 const context=vm.createContext({URL,self:{registration:{scope:'https://example.test'+scope,showNotification:async(...a)=>notices.push(a)},
  addEventListener:(key,fn)=>handlers[key]=fn,clients:{matchAll:async()=>[],openWindow:async url=>actions.push(url)}},
  fetch:async(url,options)=>{requests.push({url:String(url),body:JSON.parse(options.body)});return {ok:display,json:async()=>({display})};}});
 vm.runInContext(source,context);
 return {context,notices,requests,actions,push:async data=>{handlers.push({data:{json:()=>data},waitUntil:p=>pending=p});await pending;},
  click:async data=>{handlers.notificationclick({notification:{data,close(){}},waitUntil:p=>pending=p});await pending;}};
}
test('production display requires a matching managed envelope and account receipt',async()=>{
 const r=runtime();await r.push(message);assert.equal(r.notices.length,1);
 assert.deepEqual(r.requests.map(x=>x.body.stage),['received','shown']);
 assert.ok(r.requests.every(x=>x.url==='https://example.test/mem/api/push/receipt'&&x.body.owner===17));
 assert.equal(r.notices[0][1].data.url,'https://example.test/mem/?noticeOwner=17&homework=fixture#homework');
});
test('test, legacy, unowned and wrong-scope envelopes never display in production',async()=>{
 const r=runtime();for(const data of [{pilot:true,owner:17,id:'x',receipt:'x'},{...message,environment:'testing'},
  {...message,scope:'/mem-test/'},{...message,owner:'17'},{...message,managed:false}])await r.push(data);
 assert.equal(r.notices.length,0);assert.equal(r.requests.length,0);
 const wrongScope=runtime('/mem-test/');await wrongScope.push(message);assert.equal(wrongScope.notices.length,0);
});
test('logout or switched account rejects display before title and body are shown',async()=>{
 const r=runtime('/mem/',false);await r.push(message);assert.equal(r.notices.length,0);
});
test('business deep links survive delivery cleanup and validate current owner in the app',async()=>{
 const r=runtime();await r.click(message);assert.equal(r.requests.length,0);
 assert.deepEqual(r.actions,['https://example.test/mem/?noticeOwner=17&homework=fixture#homework']);
 const {notificationTarget}=await import('../public/notification-target.mjs');
 assert.deepEqual(notificationTarget('?noticeOwner=17&homework=fixture',19),{kind:'wrong-account'});
});
test('navigation cannot escape production or open credentials in a URL',()=>{
 const r=runtime();for(const url of ['../mem-test/','https://evil.test/','https://user:pass@example.test/mem/','/mem/../mem-test/'])
  assert.equal(vm.runInContext(`safeURL(${JSON.stringify(url)})`,r.context),'https://example.test/mem/');
});
test('production navigation, settings and branding contain no demo entry',()=>{
 const app=readFileSync(new URL('../public/app.mjs',import.meta.url),'utf8');
 const html=readFileSync(new URL('../public/index.html',import.meta.url),'utf8');
 const page=readFileSync(new URL('../public/notifications-reminders.html',import.meta.url),'utf8');
 assert.ok(app.includes('currentUser?.pushEnabled'));assert.ok(html.includes('data-reminders-nav'));
 assert.ok(!app.includes("pushEnabled&&document.body.dataset.environment==='testing'"));
 assert.ok(!html.includes('测试版'));assert.ok(!page.includes('测试环境'));
});
