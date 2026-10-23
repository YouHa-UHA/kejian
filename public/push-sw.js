self.addEventListener('install',()=>self.skipWaiting());
self.addEventListener('activate',event=>event.waitUntil(self.clients.claim()));
function safeURL(value){try{const url=new URL(value,self.location.origin);if(url.origin===self.location.origin&&url.pathname.startsWith('/mem/'))return url.href;}catch{}return '/mem/push-test.html';}
self.addEventListener('push',event=>{
 event.waitUntil((async()=>{
  let data={};try{data=event.data.json();}catch{}
  await self.registration.showNotification(data.title||'课间 · 通知测试',{
   body:data.body||'如果锁屏后看到了这条通知，说明这台设备可以接收课间推送。',
   icon:'/mem/icon-192.png',badge:'/mem/icon-192.png',tag:data.key||'kejian-push-test',
   data:{url:safeURL(data.url)}
  });
  if(data.id&&data.receipt)await fetch('/mem/api/push/receipt',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:data.id,receipt:data.receipt})}).catch(()=>{});
 })());
});
self.addEventListener('notificationclick',event=>{
 event.notification.close();event.waitUntil(self.clients.openWindow(safeURL(event.notification.data?.url)));
});
