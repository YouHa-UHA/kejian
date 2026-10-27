import {escapeHTML as esc} from './schedule.mjs';
export let currentUser=null;
let sessionEpoch=0;
async function readOrWrite(path,payload,{allowAnonymous=false}={}){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),20000);
 try{
  const r=await fetch('./api/'+path,{method:payload===undefined?'GET':'POST',cache:'no-store',credentials:'same-origin',signal:controller.signal,headers:payload===undefined?{}:{'Content-Type':'application/json','X-Kejian-Request':'1'},body:payload===undefined?undefined:JSON.stringify(payload)});
  if(r.status===401&&allowAnonymous)return null;
  const result=await r.json().catch(()=>null);
  if(!r.ok||!result){
   if(r.status===401&&!['login','activate'].includes(path))document.dispatchEvent(new Event('kejian-signed-out'));
   const error=Error(result?.error||(r.status>=500?'服务暂时无法连接，请稍后重试。':'暂时无法读取结果，请重试。'));error.status=r.status;throw error;
  }
  return result;
 }catch(error){
  if(error.name==='AbortError'||error instanceof TypeError){const friendly=Error('暂时无法连接课间，请检查网络后重试。');friendly.status=0;throw friendly;}
  throw error;
 }finally{clearTimeout(timer);}
}
export const request=(path,payload)=>readOrWrite(path,payload);
export async function checkSession(){
 const epoch=++sessionEpoch;
 const user=await readOrWrite('session',undefined,{allowAnonymous:true});
 if(epoch===sessionEpoch)currentUser=user;
 return currentUser;
}
export function showAuth(activate=false){
 sessionEpoch++;currentUser=null;document.body.classList.add('signed-out');document.querySelector('.bottom-nav').hidden=true;
 document.querySelector('#account-button').textContent='登录';document.querySelector('#account-button').removeAttribute('aria-label');document.querySelector('#account-button').removeAttribute('title');
 document.querySelector('#main').innerHTML=`<section class="account-entry"><span class="account-kicker">班级课程助手</span><h1>${activate?'开通课间':'登录课间'}</h1><p>${activate?'用班级开通码设置自己的课间密码。':'课表与作业随账号保存，换设备也能继续查看。'}</p><form id="account-form" novalidate><label>学号<input name="student" inputmode="numeric" autocomplete="username" pattern="[0-9]{6,20}" maxlength="20" required placeholder="输入学号"></label>${activate?'<label>开通码<input name="activation" autocomplete="off" maxlength="100" required placeholder="输入分配给你的开通码"></label>':''}<label>${activate?'设置课间密码':'密码'}<input name="password" type="password" minlength="${activate?8:6}" maxlength="128" autocomplete="${activate?'new-password':'current-password'}" required placeholder="${activate?'至少8位，无需使用学校密码':'输入课间密码'}"></label><p class="account-error" role="alert"></p><button class="primary-button" type="submit">${activate?'开通并登录':'登录'}</button></form><p class="account-help">账号由班级名单统一开通。忘记密码请联系管理员。</p><button class="secondary-button compact-button" data-install>添加到手机主屏幕</button></section>`;
 
 document.querySelector('#account-form').onsubmit=async e=>{e.preventDefault();const form=e.target,button=form.querySelector('[type=submit]');button.disabled=true;const b=Object.fromEntries(new FormData(form));try{form.querySelector('.account-error').textContent='';if(!/^[0-9]{6,20}$/.test(b.student)){form.elements.student.focus();throw Error('请填写正确的学号。');}if(activate&&!b.activation.trim()){form.elements.activation.focus();throw Error('请填写开通码。');}if(b.password.length<(activate?8:6)){form.elements.password.focus();throw Error(activate?'请设置至少 8 位的密码。':'请填写至少 6 位的课间密码。');}await request(activate?'activate':'login',b);form.reset();document.dispatchEvent(new Event('kejian-signed-in'));}catch(err){form.querySelector('.account-error').textContent=err.message;}finally{button.disabled=false;}};
}
export function openAccount({showDialog,dialogTop}){
 if(!currentUser){showAuth();return;}
 const user=currentUser;
 showDialog(`<div class="account-detail account-focused">${dialogTop('账号')}<h2 id="dialog-title">${esc(user.name)}</h2><p class="account-student">学号 ${esc(user.student)}</p><div class="account-settings-list"><button class="account-setting-row" id="change-password"><span><strong>修改密码</strong><small>更新你的课间登录密码</small></span><span aria-hidden="true">›</span></button></div><p class="account-result" role="status"></p><button class="secondary-button compact-button is-danger account-logout" id="sign-out">退出当前账号</button></div>`);
 document.querySelector('#change-password').onclick=()=>openPassword({showDialog,dialogTop});
 document.querySelector('#sign-out').onclick=async e=>{e.target.disabled=true;try{await request('logout',{owner:user.id});currentUser=null;document.dispatchEvent(new Event('kejian-signed-out'));}catch(err){const result=document.querySelector('.account-result');if(result)result.textContent=err.message;e.target.disabled=false;}};
}
function openPassword({showDialog,dialogTop}){
 const user=currentUser;if(!user)return;
 showDialog(`<div class="account-detail account-focused">${dialogTop('账号安全')}<h2 id="dialog-title">修改密码</h2><p class="account-password-note">修改成功后，其他设备需要重新登录。</p><form id="password-form" novalidate><input type="text" name="username" value="${esc(user.student)}" autocomplete="username" class="sr-only" tabindex="-1" aria-label="学号" readonly><label>当前密码<input name="currentPassword" type="password" autocomplete="current-password" required minlength="6" maxlength="128" placeholder="输入当前密码"></label><label>新密码<input name="newPassword" type="password" autocomplete="new-password" required minlength="8" maxlength="128" placeholder="至少8位"></label><label>确认新密码<input name="confirmPassword" type="password" autocomplete="new-password" required minlength="8" maxlength="128" placeholder="再次输入新密码"></label><p class="account-result account-error" role="alert"></p><button class="primary-button" type="submit">保存新密码</button><button type="button" class="secondary-button compact-button account-back">返回账号</button></form></div>`);
 const form=document.querySelector('#password-form');document.querySelector('#detail-dialog').addEventListener('close',()=>form.reset(),{once:true});form.querySelector('.account-back').onclick=()=>{form.reset();openAccount({showDialog,dialogTop});};
 form.onsubmit=async e=>{e.preventDefault();const button=form.querySelector('[type=submit]'),result=form.querySelector('.account-result');const fields=Object.fromEntries(new FormData(form));delete fields.username;
 if(fields.currentPassword.length<6){result.textContent='请填写当前密码。';form.elements.currentPassword.focus();return;}
 if(fields.newPassword.length<8||!fields.newPassword.trim()){result.textContent='新密码至少需要 8 位，不能全部为空格。';form.elements.newPassword.focus();return;}
 if(fields.newPassword!==fields.confirmPassword){result.textContent='两次输入的新密码不一致';return;}
 button.disabled=true;result.textContent='';
 try{await request('password',{owner:user.id,...fields});form.reset();if(currentUser?.id!==user.id||!form.isConnected||!document.querySelector('#detail-dialog').open)return;showDialog(`<div class="account-detail account-focused">${dialogTop('账号安全')}<h2 id="dialog-title">密码已修改</h2><p class="account-password-note">当前设备保持登录，其他设备需要使用新密码重新登录。</p><button class="primary-button" data-close>完成</button></div>`);}
 catch(err){result.textContent=err.message;}finally{button.disabled=false;}
 };
}
export function openSharing({showDialog,dialogTop}){
 const user=currentUser;if(!user)return;
 showDialog(`<div class="account-detail account-focused">${dialogTop('课程设置')}<h2 id="dialog-title">课表共享</h2><label class="sharing-switch"><span><strong>允许同学复制我的课表</strong><small>仅共享课程安排，个人作业和完成情况不会被复制。</small></span><input id="share-schedule" type="checkbox" role="switch" aria-label="允许同学复制我的课表" ${user.shared?'checked':''}><span class="switch-track" aria-hidden="true"></span></label><p class="account-result" role="status"></p></div>`);
 const control=document.querySelector('#share-schedule'),result=document.querySelector('.account-result');
 control.onchange=async()=>{const shared=control.checked;control.disabled=true;result.textContent='';try{await request('profile',{owner:user.id,shared});if(currentUser?.id===user.id)currentUser={...currentUser,shared};result.textContent=shared?'已开启共享':'已关闭共享';}catch(err){control.checked=!shared;result.textContent=err.message;}finally{control.disabled=false;}};
}
