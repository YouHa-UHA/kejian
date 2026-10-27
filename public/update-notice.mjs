import {escapeHTML as esc} from './schedule.mjs';

export function updateNoticeHTML(notice){
 return `<div class="update-intro"><button type="button" class="update-close" data-update-dismiss aria-label="关闭更新介绍"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="m6 6 12 12M6 18 18 6"/></svg></button><header class="update-hero"><span class="update-kicker">${esc(notice.eyebrow)}</span><div class="update-bell" aria-hidden="true"><svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 19a9 9 0 0 1 18 0c0 10 4 10 4 13H11c0-3 4-3 4-13Z"/><path d="M20 37a4.5 4.5 0 0 0 8 0M24 7V5M8 15l-3-2m35 2 3-2"/></svg><i></i></div><h2 id="update-notice-title" tabindex="-1">${esc(notice.title)}</h2><p>${esc(notice.lead)}</p><div class="update-features">${notice.features.map(label=>`<span>${esc(label)}</span>`).join('')}</div></header><div class="update-body"><h3>三小步，让提醒到你身边</h3><ol class="update-steps">${notice.steps.map(([title,body],index)=>`<li><span aria-hidden="true">${index+1}</span><div><strong>${esc(title)}</strong><p>${esc(body)}</p></div></li>`).join('')}</ol><p class="update-footnote">${esc(notice.footnote)}</p><div class="update-actions"><button type="button" class="primary-button" data-update-open>去开启提醒</button><button type="button" class="update-later" data-update-dismiss>知道啦，先逛逛</button></div></div></div>`;
}

export function mountUpdateNotice({request,getUser,blocked=()=>false,document:doc=document,window:win=window,navigate=url=>win.location.assign(url)}){
 let pending=null,flight=false,dialog=null,origin=null;
 const dismissed=new Set(),unsaved=new Map();
 const key=(owner,id)=>`${owner}:${id}`;
 async function persist(owner,id){
  const token=key(owner,id);unsaved.set(token,{owner,id});
  try{await request('update-notice',{owner,notice:id});unsaved.delete(token);}catch{}
 }
 function close(){
  if(!dialog?.open)return;
  const {owner,notice}=pending,token=key(owner,notice.id);
  dismissed.add(token);dialog.close();persist(owner,notice.id);
 }
 function tryOpen(){
  if(!pending||doc.hidden||blocked()||getUser()?.id!==pending.owner||dismissed.has(key(pending.owner,pending.notice.id))||dialog?.open)return;
  origin=doc.activeElement;
  dialog=doc.createElement('dialog');dialog.className='update-notice-dialog';dialog.setAttribute('aria-labelledby','update-notice-title');
  dialog.innerHTML=updateNoticeHTML(pending.notice);doc.body.append(dialog);
  dialog.addEventListener('cancel',event=>{event.preventDefault();close();});
  dialog.addEventListener('click',event=>{
   if(event.target.closest('[data-update-dismiss]'))close();
   if(event.target.closest('[data-update-open]')){
    const {owner,notice}=pending;dismissed.add(key(owner,notice.id));dialog.close();
    persist(owner,notice.id).finally(()=>{if(getUser()?.id===owner)navigate('./notifications-reminders.html');});
   }
   if(event.target===dialog){const rect=dialog.getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)close();}
  });
  dialog.addEventListener('close',()=>{doc.body.classList.remove('update-notice-open');dialog.remove();dialog=null;if(origin?.isConnected)origin.focus({preventScroll:true});},{once:true});
  dialog.showModal();doc.body.classList.add('update-notice-open');dialog.querySelector('#update-notice-title').focus({preventScroll:true});
 }
 async function check(){
  const user=getUser();if(!user||flight)return;flight=true;
  try{
   if(dialog?.open){if(pending?.owner===user.id)return;dialog.close();pending=null;}
   for(const {owner,id} of unsaved.values())if(owner===user.id)await persist(owner,id);
   const result=await request('update-notice');
   if(getUser()?.id!==user.id)return;
   pending=result.seen||!result.notice?null:{owner:user.id,notice:result.notice};tryOpen();
  }catch{}finally{flight=false;}
 }
 doc.addEventListener('close',()=>queueMicrotask(tryOpen),true);
 doc.addEventListener('visibilitychange',()=>{if(!doc.hidden)check();});
 win.addEventListener('online',check);
 doc.addEventListener('kejian-signed-out',()=>{pending=null;if(dialog?.open)dialog.close();});
 return {check};
}
