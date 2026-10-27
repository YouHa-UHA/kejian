self.addEventListener('install',()=>self.skipWaiting());
self.addEventListener('activate',event=>event.waitUntil(self.clients.claim()));
const appScope=new URL(self.registration.scope);
function safeURL(value){
 try{const url=new URL(value||'./',appScope);if(!url.username&&!url.password&&url.origin===appScope.origin&&url.pathname.startsWith(appScope.pathname))return url.href;}catch{}
 return appScope.href;
}
function productionMessage(data){
 return appScope.pathname==='/mem/'&&data.managed===true&&data.environment==='production'&&data.scope===appScope.pathname
  &&Number.isSafeInteger(data.owner)&&data.owner>0&&typeof data.id==='string'&&typeof data.receipt==='string';
}
async function managedReceipt(data,stage){
 const response=await fetch(new URL('api/push/receipt',appScope),{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Kejian-Request':'1'},body:JSON.stringify({owner:data.owner,id:data.id,receipt:data.receipt,stage})});
 if(!response.ok)return {display:false};return response.json();
}
self.addEventListener('push',event=>{
 event.waitUntil((async()=>{
  let data={};try{data=event.data.json();}catch{}
  if(!productionMessage(data))return;
  try{if(!(await managedReceipt(data,'received')).display)return;}catch{return;}
  await self.registration.showNotification(data.title||'课间 · 消息提醒',{
   body:data.body||'',icon:new URL('icon-192.png',appScope).href,badge:new URL('icon-192.png',appScope).href,tag:data.key||data.id,
   data:{managed:true,environment:'production',scope:appScope.pathname,url:safeURL(data.url),owner:data.owner,id:data.id,receipt:data.receipt}
  });
  await managedReceipt(data,'shown').catch(()=>{});
 })());
});
self.addEventListener('notificationclick',event=>{
 event.notification.close();event.waitUntil((async()=>{
  const data=event.notification.data||{};
  if(!productionMessage(data))return;
  const target=new URL(safeURL(data.url));
  const business=target.searchParams.has('noticeOwner')&&(target.searchParams.has('homework')||target.searchParams.has('event'));
  // Business links remain usable after delivery metadata is cleaned. The app
  // checks the current owner and permissions before showing any detail.
  const receipt=!business?await managedReceipt(data,'clicked').catch(()=>null):null;
  const url=safeURL(receipt?.display===false?'./#today':data.url);
  const windows=await self.clients.matchAll({type:'window',includeUncontrolled:true});
  const existing=windows.find(client=>client.url.startsWith(appScope.href));
  if(existing){await existing.navigate(url);await existing.focus();}
  else await self.clients.openWindow(url);
 })());
});
