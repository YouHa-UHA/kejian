import {escapeHTML as esc} from './schedule.mjs';

// One confirmation surface for dismissing drafts and consequential actions.
let pending=null;
export function confirmAction({title,message,confirm='确认',cancel='取消',danger=false}){
 if(pending)return Promise.resolve(false);
 return new Promise(resolve=>{
  const origin=document.activeElement,dialog=document.createElement('dialog');
  dialog.className='confirmation-dialog';dialog.setAttribute('aria-labelledby','confirmation-title');dialog.setAttribute('aria-describedby','confirmation-message');
  dialog.innerHTML=`<div class="confirmation-content"><h2 id="confirmation-title">${esc(title)}</h2><p id="confirmation-message">${esc(message)}</p><div class="confirmation-actions"><button type="button" class="secondary-button" data-cancel autofocus>${esc(cancel)}</button><button type="button" class="${danger?'danger-button':'primary-button'}" data-confirm>${esc(confirm)}</button></div></div>`;
  let accepted=false;
  const parent=origin?.closest('dialog');
  const finish=()=>{if(dialog.open)dialog.close();};
  dialog.querySelector('[data-cancel]').onclick=finish;
  dialog.querySelector('[data-confirm]').onclick=()=>{accepted=true;finish();};
  dialog.addEventListener('cancel',e=>{e.preventDefault();finish();});
  dialog.addEventListener('click',e=>{if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)finish();}});
  dialog.addEventListener('close',()=>{pending=null;dialog.remove();parent?.removeEventListener('close',finish);if(origin?.isConnected)origin.focus({preventScroll:true});resolve(accepted);},{once:true});
  parent?.addEventListener('close',finish,{once:true});
  pending=dialog;document.body.append(dialog);dialog.showModal();
 });
}
