import {confirmAction as askConfirmation} from './confirm-ui.mjs';
import {escapeHTML as esc} from './schedule.mjs';

const handoffPrompt="请帮我连接课间：解压附件到私密目录，阅读 START-HERE.txt，使用包内客户端核对我的姓名、学号并查询今天的课程。默认用普通API，不要求我安装MCP；已有可用MCP时也可复用。请按你支持的方式安装同包Skill，保留其他技能和配置。以后每个任务和定时执行前静默同步最新功能、权限、Skill和客户端，无变化时不汇报更新。不要回显密钥，首次只查询，用自然简短的中文回答。以后我也可以直接发学校“我的课程”页面让你导入。";
const exampleGroups=[
 {id:'courses',name:'查课程',items:[['今天的课','今天有什么课？请列出时间、老师和教室。'],['周末安排','帮我整理这周五到周日的课程安排。'],['下次到校','我下次什么时候需要去学校？当天有哪些课？']]},
 {id:'import',name:'导入课程',note:'把学校“我的课程”页面文字、文件或截图一起发给助手。',items:[['导入学校课程','这是学校“我的课程”页面，请按课间最新导入规则，核对并导入我的课程。相同课程不重复，保留已有课程；有日期或教学班冲突时再问我。'],['补充缺少课程','我会发完整的学校课程页面，请与课间已有课程核对，只补充缺少的课程，保留现有安排。'],['核对课程变化','帮我对照这份学校“我的课程”页面和课间现有课程，先告诉我哪些安排有变化，暂时不要修改。']]},
 {id:'homework',name:'管作业',items:[['待完成作业','列出我未完成的作业，按截止时间排序。'],['记一项作业','帮我记一项个人作业：整理第一章笔记。先让我选课程和截止日期。'],['标记完成','我刚做完一项作业，列出我的待完成作业，让我选择并标记完成。'],['作业重点','帮我整理这周待完成作业的截止时间、老师明确的要求和建议先做的内容，区分原要求与建议。']]},
 {id:'study',name:'学习与讨论',items:[['截图记作业','这是老师布置作业的截图，请提取完整题目、提交要求和截止日，记为我的个人作业。看不清的关键内容再问我，不要猜。'],['拆解作业','请读完整的作业要求，告诉我要交什么、有哪些容易遗漏的要求，再帮我列一个可执行的完成步骤，区分老师要求和你的建议。'],['找课代表','查一下系统工程的课代表是谁，并看看案例分析作业下面是否有人问过提交格式；先告诉我，不要发评论。'],['回复讨论','帮我找到刚才那条作业讨论，整理一段回答，先给我看，暂时不发表。']]},
 {id:'reminders',name:'定时提醒',note:'发送给支持定时任务的助手设置，创建成功后才会开始提醒。',items:[['每天查课','请创建每天早上8点的定时任务：查询我当天的课，有课才提醒我时间、老师和教室。按北京时间执行；只有实际创建并核对任务后再确认成功，不支持时请说明未创建。','每天早上8点，有课才提醒我时间、老师和教室。'],['截止前提醒','请创建每天晚上8点的定时任务：查询我未完成的作业，只提醒未来两天截止的项目，没有就不打扰。按北京时间执行；只有实际创建并核对任务后再确认成功，不支持时请说明未创建。','每天晚8点，提醒未来两天截止的未完成作业。'],['每周安排','请创建每周日晚8点的定时任务：整理我下周的课和未完成作业。按北京时间执行；只有实际创建并核对任务后再确认成功，不支持时请说明未创建。','每周日晚8点，整理下一周的课和作业。']]},
 {id:'publishing',name:'课程发布',publisher:true,items:[['发布作业','帮我发布一项课程作业，先从我正在上的教学班核对课程，再填写作业要求和截止日期。同名、同老师的其他教学班不要一起发布。'],['调整截止日','我想调整一项已发布课程作业的截止时间，先列出我有权修改的作业让我选择。'],['整理提醒','将我负责课程已发布的作业整理成一段提醒文字，注明课程、要求和截止日期，先给我看。']]},
];
let serial=0;
const time=value=>value?new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(value)):'尚未使用';

export async function mountAiConnections({container,request,getUser,showDialog,dialogTop}){
 const version=++serial,who=getUser()?.id;
 container.dataset.owner=String(who);
 const current=()=>version===serial&&getUser()?.id===who&&container.isConnected;
 const local=['localhost','127.0.0.1','::1','[::1]'].includes(location.hostname);
 let loaded=false,data={connections:[]},category='courses',wizard=null,wizardDialog=null;
 let signature='',busy=false,fetchSerial=0,syncing=false,pollTimer,failures=0,confirmId=null;
 container.innerHTML='<section class="page-intro"><h1>连接 AI</h1><p>正在读取连接…</p></section>';
 const groups=()=>exampleGroups.filter(g=>!g.publisher||getUser()?.admin||getUser()?.representativeOf?.length);
 const selectedGroup=()=>groups().find(g=>g.id===category)||groups()[0];
 function scope(){
  const user=getUser();
  return `查看课表和作业，管理自己的课程与个人作业。${user?.admin?'也可管理班级课程、课代表和课程作业。':user?.representativeOf?.length?'也可发布、维护负责课程的作业。':''}`;
 }
 function examplesHtml(){return `<section class="ai-examples" aria-labelledby="ai-examples-title"><h2 id="ai-examples-title">连好后，可以这样说</h2><div class="ai-example-tabs" role="group" aria-label="指令类型">${groups().map(g=>`<button type="button" data-ai-category="${g.id}" aria-pressed="${selectedGroup().id===g.id}">${g.name}</button>`).join('')}</div><div id="ai-example-content"></div><p class="ai-example-status" role="status"></p></section>`;}
 function guideHtml(){return `<section class="ai-connect-hero" aria-labelledby="ai-connect-title"><div class="ai-connect-intro"><span class="ai-connect-symbol" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="m10 13 4-4m-5 7-1.5 1.5a4.2 4.2 0 0 1-6-6L5 8m14 8 3.5-3.5a4.2 4.2 0 0 0-6-6L15 8" transform="translate(0 -1)"/></svg></span><h2 id="ai-connect-title">在 AI 里查课、处理作业</h2><p>支持 WorkBuddy 等助手。把连接资料交给它，就能查询课表、导入课程、管理作业。</p><button class="primary-button" type="button" id="ai-connect-start">连接 AI <span aria-hidden="true">↗</span></button>${local?'<small class="ai-connect-local">本地测试：请交给这台电脑上的助手使用。</small>':''}</div><ol class="ai-connect-steps"><li><span>1</span><div><strong>给助手取个名字</strong><p>例如“我的 WorkBuddy”，方便区分。</p></div></li><li><span>2</span><div><strong>下载连接资料</strong><p>配置和操作指引已备好，后续自动更新。</p></div></li><li><span>3</span><div><strong>发给你的 AI</strong><p>把资料和提示词交给助手，完成连接。</p></div></li></ol></section>`;}
 function connectionsHtml(){return '<section class="ai-connections" id="ai-connections-area" aria-labelledby="ai-connections-title"><div class="section-heading"><h2 id="ai-connections-title">我的连接 <small id="ai-connection-count"></small></h2></div><div class="ai-connection-list" id="ai-connection-list"></div></section>';}
 function draw(message=''){
  if(!current())return;
  const user=getUser();
  if(!loaded){container.innerHTML=`<section class="page-intro"><h1>连接 AI</h1></section><div class="flow-empty"><h2>暂时无法读取连接</h2><p role="alert">${esc(message||'恢复网络后会自动重试。')}</p><button class="primary-button" id="ai-load-retry">重新加载</button></div>`;container.querySelector('#ai-load-retry').onclick=async e=>{e.target.disabled=true;try{await refresh();}catch(error){if(current())draw(error.message);}};return;}
  container.dataset.hasConnections=String(data.connections.length>0);
  container.innerHTML=`<section class="page-intro ai-intro"><div><h1>连接 AI</h1></div><span class="ai-owner"><span class="status-dot"></span>${esc(user.name)}<small>${esc(user.student)}</small></span></section>${data.connections.length?connectionsHtml()+`<details class="ai-add-guide"><summary>连接另一个 AI 助手</summary>${guideHtml()}</details>`:guideHtml()+connectionsHtml()}<p class="ai-feedback" role="status">${esc(message)}</p>${examplesHtml()}
   <div class="ai-quick-help"><details><summary>资料找不到，或连接失效了？</summary><p>在“我的连接”中重新下载，再把新文件交给原来的助手。旧资料会立即失效。</p></details><details><summary>助手不能接收 ZIP 文件？</summary><p>在电脑上解压，把文件夹位置告诉助手，让它阅读 START-HERE.txt 并完成连接。需要助手能够执行脚本或发送网络请求，无需手动添加 MCP。</p></details></div>`;
  container.querySelector('#ai-connect-start').onclick=()=>openWizard();
  container.querySelectorAll('[data-ai-category]').forEach(button=>button.onclick=()=>{category=button.dataset.aiCategory;paintExamples();});
  paintExamples();paintConnections(true);
 }
 function openWizard(prepared=null){
  if(!current()||busy)return;
  wizard=prepared||{step:1,name:'WorkBuddy',key:crypto.randomUUID(),blob:null,error:''};
  wizardDialog=document.querySelector('#detail-dialog');
  wizardDialog.addEventListener('close',onWizardClose);
  wizardDialog.addEventListener('cancel',onWizardCancel);
  wizardDialog.addEventListener('click',onWizardBackdrop,true);
  drawWizard();
 }
 function onWizardClose(){
  wizard=null;
  if(wizardDialog){wizardDialog.removeEventListener('close',onWizardClose);wizardDialog.removeEventListener('cancel',onWizardCancel);wizardDialog.removeEventListener('click',onWizardBackdrop,true);wizardDialog=null;}
 }
 function onWizardCancel(event){if(busy&&wizard)event.preventDefault();}
 function onWizardBackdrop(event){if(busy&&wizard&&event.target===wizardDialog){event.preventDefault();event.stopImmediatePropagation();}}
 function closeWizard(){if(wizardDialog?.open)wizardDialog.close();onWizardClose();}
 function drawWizard(){
  if(!current()||!wizard)return;
  const step=wizard.step;
  const progress=`<ol class="ai-wizard-progress" aria-label="连接步骤">${['取名','下载资料','发给 AI'].map((label,i)=>`<li class="${i+1===step?'current':i+1<step?'done':''}" ${i+1===step?'aria-current="step"':''}><span>${i+1}</span>${label}</li>`).join('')}</ol>`;
  const file=`<div class="ai-wizard-file"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9zM14 3v6h6M12 12v6m-3-3 3 3 3-3"/></svg><div><strong>${esc(wizard.name)} · 连接资料.zip</strong><p>助手连接配置 · 课程与作业操作指引</p></div></div>`;
  const content=step===1?`<h2 id="dialog-title" tabindex="-1">给 AI 助手取个名字</h2><p class="ai-wizard-lead">方便你在“我的连接”中认出它。</p><form id="ai-create-form" class="ai-create-form" novalidate><label for="ai-connection-name">AI 名称</label><input id="ai-connection-name" name="name" required maxlength="60" value="${esc(wizard.name)}" placeholder="例如：我的 WorkBuddy" autocomplete="off"></form><div class="ai-scope"><strong>它可以帮你做什么</strong><p>${scope()}</p><small>功能和权限自动同步，升级后无需重新连接。</small></div>`:
   step===2?`<h2 id="dialog-title" tabindex="-1">下载连接资料</h2><p class="ai-wizard-lead">资料中的配置已备好，交给助手完成连接即可。</p>${file}<p class="ai-wizard-note">请只把这份资料交给你指定的助手。</p>`:
   `<h2 id="dialog-title" tabindex="-1">把文件和这段话发给 AI</h2><p class="ai-wizard-lead">在 WorkBuddy 等助手中新建对话，附上 ZIP，再发送下面这段话。</p><div class="ai-wizard-downloaded"><span>连接资料已下载</span><button type="button" class="secondary-button compact-button" id="ai-download-again">再次下载</button></div><textarea id="ai-handoff-prompt" class="ai-handoff-prompt" readonly aria-label="首次连接提示词" spellcheck="false">${esc(handoffPrompt)}</textarea><button type="button" class="secondary-button ai-copy-prompt" id="ai-copy-handoff">复制连接提示词</button><p class="ai-copy-status" role="status"></p><p class="ai-wizard-note">助手核对姓名学号并查询课程后，就可以直接交代任务。后续功能和权限会自动同步。</p>`;
  const actions=step===1?'<button type="button" class="secondary-button" data-ai-wizard-cancel>取消</button><button type="submit" form="ai-create-form" class="primary-button">下一步 →</button>':step===2?`${wizard.blob?'':'<button type="button" class="secondary-button" id="ai-wizard-back">上一步</button>'}<button type="button" class="primary-button" id="ai-wizard-download">下载连接资料 ↓</button>`:'<button type="button" class="primary-button" data-ai-wizard-cancel>完成</button>';
  showDialog(`<div class="ai-wizard"><header class="ai-wizard-header">${dialogTop('连接 AI')}${progress}</header><div class="ai-wizard-content">${content}</div><footer class="ai-wizard-footer"><p class="ai-wizard-error" role="alert">${esc(wizard.error||'')}</p><div>${actions}</div></footer></div>`,{kind:'ai-connection',replace:!!wizardDialog?.classList.contains('ai-connection-dialog')});
  const root=wizardDialog.querySelector('.ai-wizard');
  root.querySelector('[data-close]').setAttribute('aria-label','关闭连接向导');
  root.querySelectorAll('[data-ai-wizard-cancel]').forEach(button=>button.onclick=closeWizard);
  if(step===1){
   const form=root.querySelector('#ai-create-form'),input=form.elements.name;
   input.oninput=()=>{wizard.name=input.value;input.removeAttribute('aria-invalid');root.querySelector('.ai-wizard-error').textContent='';};
   form.onsubmit=event=>{event.preventDefault();const name=input.value.trim();if(!name){input.setAttribute('aria-invalid','true');root.querySelector('.ai-wizard-error').textContent='请填写助手名称。';input.focus();return;}wizard.name=name;wizard.step=2;wizard.error='';drawWizard();};
   input.focus({preventScroll:true});
  }else{
   root.querySelector('#dialog-title').focus({preventScroll:true});
   if(step===2){
    root.querySelector('#ai-wizard-back')?.addEventListener('click',()=>{wizard.step=1;wizard.error='';drawWizard();});
    root.querySelector('#ai-wizard-download').onclick=prepareWizard;
   }else{
    root.querySelector('#ai-download-again').onclick=()=>savePackage(wizard.blob,wizard.name);
    root.querySelector('#ai-copy-handoff').onclick=event=>copy(handoffPrompt,event.currentTarget,root.querySelector('#ai-handoff-prompt'));
   }
  }
 }
 async function prepareWizard(){
  if(busy||!wizard||!current())return;
  const run=wizard,root=wizardDialog.querySelector('.ai-wizard');busy=true;run.error='';
  root.querySelectorAll('button').forEach(button=>button.disabled=true);
  root.querySelector('#ai-wizard-download').textContent='正在准备…';
  root.querySelector('.ai-wizard-error').textContent='';
  try{
   if(!run.blob)run.blob=await preparePackage({action:'create',name:run.name,requestKey:run.key});
   if(!current()||wizard!==run)return;
   savePackage(run.blob,run.name);run.step=3;
   await refresh('连接资料已下载，请把文件和提示词交给助手。',true).catch(()=>feedback('资料已下载，连接列表稍后会自动同步。','sync'));
  }catch(error){if(current()&&wizard===run)run.error=error.message;}
  finally{busy=false;if(current()&&wizard===run)drawWizard();}
 }
 function paintExamples(){
  if(!current())return;const group=selectedGroup();
  container.querySelectorAll('[data-ai-category]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.aiCategory===group.id)));
  container.querySelector('#ai-example-content').innerHTML=`${group.note?`<p class="ai-example-note">${group.note}</p>`:''}<div class="ai-example-grid">${group.items.map(([title,prompt,preview],i)=>`<button type="button" data-ai-example="${i}" class="ai-example"><span>${title}<small>复制 ↗</small></span><p>${esc(preview||prompt)}</p></button>`).join('')}</div>`;
  container.querySelectorAll('[data-ai-example]').forEach(button=>button.onclick=()=>copy(group.items[Number(button.dataset.aiExample)][1],button));
 }
 function paintConnections(force=false){
  if(!current()||!container.querySelector('#ai-connection-list'))return;
  const next=JSON.stringify(data.connections);if(!force&&(confirmId||next===signature))return;signature=next;confirmId=null;
  container.querySelector('#ai-connections-area').hidden=!data.connections.length;
  container.querySelector('#ai-connection-count').textContent=data.connections.filter(c=>c.status==='active').length+' 个可用';
  container.querySelector('#ai-connection-list').innerHTML=data.connections.map(c=>`<article class="ai-connection" data-connection-id="${esc(c.id)}"><div class="ai-connection-heading"><strong>${esc(c.name)}</strong><span class="ai-status ${c.status==='active'?'ai-active':''}">${c.status==='active'?(c.lastUsedAt?'可用':'待连接'):'已失效'}</span></div><p>长期有效</p><small>${c.lastUsedAt?'最近使用：'+time(c.lastUsedAt):'把资料交给助手后开始使用'}</small><div class="ai-row-actions"><button type="button" class="secondary-button compact-button" data-ai-action="rotate" data-ai-id="${esc(c.id)}">重新下载</button><button type="button" class="secondary-button compact-button ai-delete" data-ai-action="delete" data-ai-id="${esc(c.id)}">删除连接</button></div><div class="ai-row-confirm" hidden></div></article>`).join('');
  container.querySelectorAll('[data-ai-action]').forEach(button=>button.onclick=()=>confirmAction(button.dataset.aiAction,button.dataset.aiId));
 }
 function feedback(message,kind='action'){const target=container.querySelector('.ai-feedback');if(target){target.textContent=message;target.dataset.kind=kind;}}
 async function copy(text,button,field){
  const label=button.innerHTML;button.disabled=true;
  try{await navigator.clipboard.writeText(text);if(!current())return;button.textContent='已复制';}
  catch{if(!current())return;if(field){field.focus();field.select();const status=field.closest('.ai-wizard')?.querySelector('.ai-copy-status');if(status)status.textContent='文字已选中，请复制后发给助手。';}else container.querySelector('.ai-example-status').textContent='未能自动复制，请选中示例文字复制。';}
  finally{setTimeout(()=>{if(button.isConnected){button.innerHTML=label;button.disabled=false;}},1800);}
 }
 async function refresh(message='',force=false){
  const ticket=++fetchSerial;
  const result=await request('ai-connections');if(ticket!==fetchSerial||result.owner!==who||!current())return;
  data=result;loaded=true;
  if(!container.querySelector('#ai-connect-start')||container.dataset.hasConnections!==String(data.connections.length>0))draw(message);else{paintConnections(force);if(message)feedback(message);else if(container.querySelector('.ai-feedback')?.dataset.kind==='sync')feedback('');}
 }
 async function preparePackage(payload){
  const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),20000);
  try{
   const response=await fetch('./api/ai-connections',{method:'POST',credentials:'same-origin',cache:'no-store',signal:controller.signal,headers:{'Content-Type':'application/json','X-Kejian-Request':'1'},body:JSON.stringify({owner:who,...payload})});
   if(!response.ok){if(response.status===401)document.dispatchEvent(new Event('kejian-signed-out'));const error=await response.json().catch(()=>null);throw Error(error?.error||'资料暂时无法生成，请稍后再试。');}
   return await response.blob();
  }catch(error){if(error.name==='AbortError')throw Error('暂时没有收到资料，请稍后重试。若连接已出现在列表中，可从那里重新下载。');if(error instanceof TypeError)throw Error('暂时无法下载，请检查网络后重试。');throw error;}
  finally{clearTimeout(timeout);}
 }
 function savePackage(blob,name){
  const url=URL.createObjectURL(blob),link=document.createElement('a');
  const filename=name.replace(/[\\/?:*"<>|\x00-\x1f]/g,'').trim().slice(0,40)||'AI';
  link.href=url;link.download='课间-'+filename+'-连接资料.zip';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
 }
 async function confirmAction(action,id){
  const item=data.connections.find(c=>c.id===id);if(!item||!current()||busy||confirmId)return;
  confirmId=id;
  const accepted=await askConfirmation({title:action==='delete'?'删除这个 AI 连接？':'重新下载连接资料？',message:action==='delete'?'删除后，这个助手会立即失去访问权限。如需重新使用，可以创建新的连接。':'旧资料会立即失效，请把新文件交给原来的助手。',confirm:action==='delete'?'删除连接':'下载新资料',danger:action==='delete'});
  if(!accepted||!current()){confirmId=null;return;}
  busy=true;
  try{
   const payload={action,id,expected:item.revision};let blob=null;
   if(action==='rotate'){blob=await preparePackage(payload);if(!current())return;savePackage(blob,item.name);}
   else await request('ai-connections',{owner:who,...payload});
   confirmId=null;
   if(blob){
    await refresh('新资料已下载，请重新交给助手。',true).catch(()=>feedback('资料已下载，连接列表稍后会自动同步。','sync'));
    if(current()){busy=false;openWizard({step:3,name:item.name,blob,error:''});}
   }else await refresh('连接已删除。',true);
  }catch(error){if(current()){confirmId=null;feedback(error.message);try{await refresh('',true);}catch{}}}finally{busy=false;confirmId=null;}
 }
 function cleanup(){closeWizard();clearTimeout(pollTimer);document.removeEventListener('visibilitychange',onReturn);window.removeEventListener('focus',onReturn);window.removeEventListener('online',onReturn);window.removeEventListener('hashchange',onNavigation);}
 function schedule(){clearTimeout(pollTimer);if(!current()){cleanup();return;}pollTimer=setTimeout(autoSync,Math.min(60000,20000*2**failures));}
 async function autoSync(){
  if(!current()){cleanup();return;}
  if(document.hidden||busy||syncing){schedule();return;}syncing=true;
  try{await refresh();failures=0;}catch{failures=Math.min(failures+1,2);if(current())feedback('连接状态暂时无法更新，恢复网络后会自动同步。','sync');}finally{syncing=false;schedule();}
 }
 function onReturn(){if(!document.hidden)autoSync();}
 function onNavigation(){if(!current())cleanup();}
 try{await refresh();}catch(error){if(current())draw(error.message);}
 if(current()){document.addEventListener('visibilitychange',onReturn);window.addEventListener('focus',onReturn);window.addEventListener('online',onReturn);window.addEventListener('hashchange',onNavigation);schedule();}
}
