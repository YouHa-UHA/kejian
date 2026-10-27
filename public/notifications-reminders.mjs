import {request,checkSession} from './account.mjs';
import {reminderSettingsHTML} from './notification-settings-ui.mjs';
import {escapeHTML as esc} from './schedule.mjs';

const main=document.querySelector('#notification-main');
const ios=/iPhone|iPad|iPod/.test(navigator.userAgent)||(navigator.platform==='MacIntel'&&navigator.maxTouchPoints>1);
const standalone=matchMedia('(display-mode: standalone)').matches||navigator.standalone;
const supported=ios&&standalone&&isSecureContext&&'serviceWorker' in navigator&&'PushManager' in window&&'Notification' in window&&!/MicroMessenger/.test(navigator.userAgent);
const store='kejian.push-device:'+new URL('./',location.href).pathname;
let user,config,registration,deviceId='',device={enabled:false,remindersEnabled:false},model,busy=false,error='',notice='',flight=false,timer;
const api=(action,body={})=>request('push/'+action,{owner:user.id,...body});
function render(){
 if(!user||!model)return;
 main.querySelector('.notification-layout,.notification-card')?.remove();
 main.insertAdjacentHTML('beforeend',reminderSettingsHTML({user,model,device,supported,ios,standalone,permission:'Notification' in window?Notification.permission:'default',busy,error,notice}));
}
async function sameIdentity(){const current=await checkSession();if(current?.id===user.id)return true;location.reload();return false;}
async function refresh(){
 if(document.hidden||busy||flight||!user)return;flight=true;
 try{
  if(!await sameIdentity())return;
  const next=await api('reminder-settings');
  const state=deviceId?await api('status',{deviceId}):device;
  const combined={...next,workerOnline:next.workerOnline??state.workerOnline??config.workerOnline};
  if(JSON.stringify([combined,state])!==JSON.stringify([model,device])){model=combined;device=state;render();}
 }catch(e){error=e.message;render();}finally{flight=false;}
}
async function ensureDevice(permission){
 if(await permission!=='granted')throw Error('尚未获得通知权限，请在系统设置中允许课间发送通知。');
 let subscription=await registration.pushManager.getSubscription();
 const key=Uint8Array.from(atob(config.publicKey.replace(/-/g,'+').replace(/_/g,'/')+'='.repeat((4-config.publicKey.length%4)%4)),c=>c.charCodeAt(0));
 if(subscription?.options?.applicationServerKey&&Array.from(new Uint8Array(subscription.options.applicationServerKey)).join()!==Array.from(key).join()){
  await subscription.unsubscribe();subscription=null;
 }
 if(!subscription)subscription=await registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:key});
 device=await api('register',{subscription:subscription.toJSON(),label:'iPhone / iPad'});deviceId=device.deviceId;
 try{localStorage.setItem(store,JSON.stringify({owner:user.id,id:deviceId}));}catch{}
}
async function change(target){
 const key=target.dataset.reminderSetting,choice=target.dataset.reminderChoice;
 const connecting=target.hasAttribute('data-reminder-connect');
 const on=connecting||key==='device'&&target.checked;
 // Initiate the permission prompt directly within the user gesture.
 const permission=on&&supported?(Notification.permission==='granted'?Promise.resolve('granted'):Notification.requestPermission()):null;
 busy=true;error='';notice='';render();
 try{
  if(!await sameIdentity())return;
  if(target.hasAttribute('data-reminder-test')){
   if(!device.remindersEnabled||!deviceId)throw Error('请先开启这台设备的提醒。');
   device=await api('test',{deviceId,requestKey:crypto.randomUUID()});
   notice='测试提醒已安排，约30秒后送达。现在可以锁屏试试看。';
  }else if(connecting||key==='device'){
   if(on){if(!supported)throw Error('请从 iPhone / iPad 桌面打开课间后开启提醒。');await ensureDevice(permission);}
   if(!deviceId)throw Error('请先连接这台设备的通知。');
   const result=await api(on?'reminders-enable':'reminders-disable',{deviceId});device=result;
   model={...result.preferences,workerOnline:result.workerOnline};notice=on?'这台设备的提醒已开启':'这台设备的提醒已关闭';
  }else{
   const settings={...model.settings,[key||choice]:choice?Number(target.dataset.value):target.checked};
   model=await api('reminder-settings-save',{expected:model.revision,settings});notice='已保存';
  }
 }catch(e){
  if(e.status===409){const latest=await api('reminder-settings').catch(()=>null);if(latest)model=latest;error='设置已在其他页面更新，请重新查看后再调整。';}
  else error=e.message||'暂时无法保存提醒设置，请稍后再试。';
 }finally{busy=false;if(user)render();}
}
main.addEventListener('click',event=>{const button=event.target.closest('[data-reminder-connect],[data-reminder-choice],[data-reminder-test]');if(button&&!busy)change(button);});
main.addEventListener('change',event=>{if(event.target.matches('[data-reminder-setting]')&&!busy)change(event.target);});
document.addEventListener('kejian-signed-out',()=>{user=null;clearInterval(timer);main.innerHTML='<section class="notification-card"><h1>请先登录课间</h1><p>提醒设置和接收设备只属于你自己的账号。</p><a class="primary-button" href="./#today">前往登录</a></section>';});
try{
 user=await checkSession();
 if(!user)document.dispatchEvent(new Event('kejian-signed-out'));
 else{
  config=await request('push/config');model=await api('reminder-settings');
  if(!({production:'/mem/',testing:'/mem-test/'}[config.environment]===config.scope&&config.scope===new URL('./',location.href).pathname))throw Error('请从正式版课间重新打开消息提醒。');
  if(supported){registration=await navigator.serviceWorker.register('./push-sw.js',{scope:'./',updateViaCache:'none'});await navigator.serviceWorker.ready;await registration.update();if(registration.scope!==new URL('./',location.href).href)throw Error('请重新打开课间后再设置提醒。');}
  try{const saved=JSON.parse(localStorage.getItem(store)||'null');if(saved?.owner===user.id)deviceId=saved.id;}catch{}
  if(deviceId){try{device=await api('status',{deviceId});}catch{deviceId='';}}
  render();timer=setInterval(refresh,20000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
 }
}catch(e){main.querySelector('.notification-card').innerHTML=`<h2>暂时无法读取提醒设置</h2><p>${esc(e.message)}</p><a href="./#today">返回课间</a>`;}
