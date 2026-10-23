import {confirmAction} from './confirm-ui.mjs';
import {mountComments} from './comments-ui.mjs';
import {deadlineFields,mountDeadline} from './deadline-ui.mjs';
import {overdue,sortTasks} from './homework.mjs';
import {escapeHTML as esc,chinaClock,addDays,dateLabel} from './schedule.mjs';

const privateFields=['id','title','courseId','notes','dueDate','dueTime','createdAt','updatedAt','completedAt','deletedAt','revision'];
const chevron='<svg class="hw-picker-chevron" aria-hidden="true" viewBox="0 0 24 24" fill="none"><path d="m6 9 6 6 6-6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';

export function createHomework({courses,render,showDialog,dialogTop,goRoute,owner}){
 let cache=[],publishCourses=[],loaded=false,busy=false,generation=0;
 let status='pending',scopeFilter='all',filter='',problem='',undo=null,timer,editing=null,publishKey='',managed=null;
 const dialog=()=>document.querySelector('#detail-dialog');
 const all=()=>cache.filter(t=>!t.deletedAt);
 const course=id=>courses().find(c=>c.id===id);
 const tasks=()=>sortTasks(all());
 const find=id=>all().find(t=>t.id===id)||managed?.items.find(t=>t.id===id);
 const courseName=t=>t.courseName||course(t.courseId)?.name||'原课程';
 const publisherScope=p=>p?`${esc(p.name)} · ${esc(p.teacher)}<small>${esc(p.term)} · 教学班 ${esc(p.courseId)}<br>发布后，这个教学班的同学都会看到。</small>`:'选择发布课程后，这个教学班的同学都会看到。';
 function publishPicker(key,editing){return `<input type="hidden" name="offeringKey" value="${esc(key)}">${editing||publishCourses.length===1?'':`<div class="hw-course-field"><div id="hw-publish-label">发布课程 <span>必选</span></div><details class="hw-picker hw-form-picker"><summary aria-labelledby="hw-publish-label hw-publish-value"><span id="hw-publish-value">${esc(publishCourses.find(c=>c.key===key)?.name||'选择课程')}</span>${chevron}</summary><div class="hw-picker-panel"><div class="hw-picker-options">${publishCourses.map(c=>`<button type="button" data-hw-publish-course="${esc(c.key)}" aria-pressed="${key===c.key}"><span><strong>${esc(c.name)}</strong><small>${esc(c.teacher)} · ${esc(c.term)} · ${esc(c.courseId)}</small></span><span aria-hidden="true">${key===c.key?'✓':''}</span></button>`).join('')}</div></div></details></div>`}`;}
 function pageActions(){return publishCourses.length?'<div class="hw-page-actions"><button class="secondary-button" data-hw-add>＋ 记个人作业</button><button class="primary-button" data-hw-publish>发布课程作业</button></div>':'<button class="primary-button" data-hw-add>＋ 记个人作业</button>';}

 const dateText=t=>!t.dueDate?'截止日期待定':`${dateLabel(t.dueDate,true)}${t.dueTime?' '+t.dueTime:'（时刻待定）'}截止`;
 const apply=result=>{cache=result.items;publishCourses=result.publishCourses||[];loaded=true;problem='';};
 async function api(path,payload){
  const who=owner(),version=generation;
  const r=await fetch('./api/'+path,{method:payload?'POST':'GET',cache:'no-store',credentials:'same-origin',headers:payload?{'Content-Type':'application/json','X-Kejian-Request':'1'}:{},body:payload?JSON.stringify({owner:who,...payload}):undefined});
  const result=await r.json();
  if(who!==owner()||version!==generation)throw Error('身份已变化，请重新进入');
  if(r.status===401)document.dispatchEvent(new Event('kejian-signed-out'));
  if(!r.ok)throw Error(result.error||'暂时无法保存或读取，请重试');
  return result;
 }
 async function refresh(){const result=await api('homework');if(result.owner!==owner())throw Error('身份已变化，请重新进入');apply(result);}
 function rows(items){return items.map(t=>`<article class="hw-row ${t.completedAt?'hw-done':''}"><button class="hw-check" data-hw-toggle="${esc(t.id)}" aria-label="${t.completedAt?'恢复待完成':'标记完成'}：${esc(t.title)}" aria-pressed="${!!t.completedAt}">${t.completedAt?'✓':'<span></span>'}</button><button class="hw-body" data-hw-edit="${esc(t.id)}"><span class="hw-title-line"><strong>${esc(t.title)}</strong><span class="hw-scope-badge ${t.scope==='course'?'is-course':''}">${t.scope==='course'?'课程作业':'个人作业'}</span></span><span class="hw-meta"><span class="hw-course">${esc(courseName(t))}</span><span class="${overdue(t,chinaClock())?'hw-overdue':''}">${overdue(t,chinaClock())?'已逾期 · ':''}${dateText(t)}</span></span><span class="hw-source">${t.scope==='course'?`${esc(t.author)}发布 · 同班可见`:'仅自己可见'}</span>${t.notes?`<span class="hw-notes">${esc(t.notes)}</span>`:''}</button><button class="hw-edit" data-hw-edit="${esc(t.id)}" aria-label="${t.scope==='course'?'查看':'编辑'}：${esc(t.title)}">›</button></article>`).join('');}
 function error(){return problem?`<p class="hw-error" role="alert">${esc(problem)}</p>`:'';}
 function page(){
  const list=tasks(),pending=list.filter(t=>!t.completedAt),done=list.filter(t=>t.completedAt),visible=(status==='pending'?pending:done).filter(t=>(!filter||t.courseId===filter)&&(scopeFilter==='all'||(t.scope==='course'?'course':'personal')===scopeFilter));
  return `<section class="page-intro hw-intro"><div><h1>作业</h1><p>${pending.length} 项待完成${pending.filter(t=>overdue(t,chinaClock())).length?' · '+pending.filter(t=>overdue(t,chinaClock())).length+' 项逾期':''}</p></div>${pageActions()}</section><div class="hw-toolbar"><div class="view-switch" role="group" aria-label="作业状态"><button data-hw-status="pending" aria-pressed="${status==='pending'}">待完成 ${pending.length}</button><button data-hw-status="done" aria-pressed="${status==='done'}">已完成 ${done.length}</button></div><details class="hw-picker"><summary aria-label="按课程筛选"><span>${esc(course(filter)?.name||'全部课程')}</span>${chevron}</summary><div class="hw-picker-panel"><p>筛选课程</p><div class="hw-picker-options">${[{id:'',name:'全部课程'},...courses()].map(c=>`<button data-hw-filter="${esc(c.id)}" aria-label="${esc(c.name)}" aria-pressed="${filter===c.id}"><span>${esc(c.name)}</span><span aria-hidden="true">${filter===c.id?'✓':''}</span></button>`).join('')}</div></div></details></div>${error()}<div class="hw-scope-filters" role="group" aria-label="作业类型">${[['all','全部'],['course','课程作业'],['personal','个人作业']].map(([value,label])=>`<button data-hw-scope="${value}" aria-pressed="${scopeFilter===value}">${label}</button>`).join('')}</div><div class="hw-list">${visible.length?rows(visible):`<div class="hw-empty"><span class="hw-empty-symbol">${status==='done'?'✓':'▤'}</span><h2>${filter?'这门课暂无'+(status==='done'?'已完成':'待完成')+'作业':status==='done'?'还没有已完成的作业':'暂无待完成作业'}</h2><p>${status==='done'?'完成的作业会保留在这里。':'课程发布的作业会自动出现在这里，也可以记一项自己的作业。'}</p>${status==='pending'?'<button class="text-link" data-hw-add>记个人作业 →</button>':''}</div>`}</div>`;
 }
 function home(){const list=tasks().filter(t=>!t.completedAt&&t.dueDate&&t.dueDate<=addDays(chinaClock().date,7)).slice(0,3);return list.length?`<section class="hw-preview"><div class="section-heading"><h2>近期作业</h2><a class="text-link" href="#homework">查看全部 →</a></div>${rows(list)}</section>`:error();}
 function courseSection(id){const list=tasks().filter(t=>t.courseId===id&&!t.completedAt),publisher=publishCourses.find(c=>c.courseId===id&&c.enrolled);return `<section class="hw-course-section"><div class="section-heading"><h3>待完成作业${list.length?' · '+list.length:''}</h3><div class="hw-course-actions"><button class="text-link" data-hw-add="${esc(id)}">＋ 记个人作业</button>${publisher?`<button class="text-link" data-course-homework="${esc(publisher.key)}">管理课程作业</button>`:''}</div></div>${error()}${list.length?rows(list):'<p class="hw-muted">这门课还没有待完成作业。</p>'}</section>`;}
 function dayBadge(day){const list=tasks().filter(t=>t.dueDate===day);if(!list.length)return '';const pending=list.filter(t=>!t.completedAt).length;return `<button class="hw-day-badge ${pending?'':'hw-day-done'}" data-hw-day="${day}" aria-label="${dateLabel(day,true)}，${list.length}项作业，${pending}项待完成">${pending?'作业'+pending:'✓'}</button>`;}
 function openDay(day){const list=tasks().filter(t=>t.dueDate===day);showDialog(`<div class="hw-detail hw-day-detail">${dialogTop('截止作业')}<h2 id="dialog-title">${dateLabel(day,true)}</h2><p class="hw-muted">${list.filter(t=>!t.completedAt).length} 项待完成 · ${list.length} 项作业</p>${error()}${rows(list)}</div>`);}
 function sharedDetail(t){
  showDialog(`<div class="hw-detail hw-shared-detail">${dialogTop('课程作业')}<span class="hw-detail-course">${esc(courseName(t))}</span><h2 id="dialog-title">${esc(t.title)}</h2><p class="hw-shared-due">${dateText(t)}</p><p class="hw-publisher">${esc(t.author)}发布${t.updatedBy!==t.author?' · '+esc(t.updatedBy)+'更新':''}</p><section class="hw-requirements-section"><h3>具体要求</h3><div class="hw-requirements">${esc(t.notes||'尚未填写具体要求，可以在下方讨论中询问课代表。')}</div></section><p class="hw-muted">完成状态仅自己可见。</p><div class="hw-shared-actions">${t.canComplete?`<button class="primary-button" data-hw-toggle="${esc(t.id)}">${t.completedAt?'恢复待完成':'标记已完成'}</button>`:''}${t.canEdit?`<button class="secondary-button" data-shared-edit="${esc(t.id)}">修改课程作业</button>`:''}</div><section class="hw-discussion"></section></div>`);
  mountComments(dialog().querySelector('.hw-discussion'),{homework:t.id,api});
 }
 function open(id=null,courseId='',key='',publishing=false){
  const t=id?find(id):null;if(id&&!t)return;
  if(problem){notify(problem);return;}
  if(t?.scope==='course'&&!key){sharedDetail(t);return;}
  publishing=publishing||!!key;
  if(publishing&&!key)key=publishCourses.find(c=>c.courseId===courseId)?.key||(publishCourses.length===1?publishCourses[0].key:'');
  const publisher=publishing?publishCourses.find(c=>c.key===key):null;
  if(publishing&&(!publishCourses.length||(key&&!publisher))){notify('课程管理权限已变化，请刷新后重试');return;}
  editing=t;publishKey=key;
  const selected=t?.courseId||courseId;
  const options=courses().map(c=>`<button type="button" data-hw-course="${esc(c.id)}" aria-label="${esc(c.name)}" aria-pressed="${selected===c.id}"><span>${esc(c.name)}</span><span aria-hidden="true">${selected===c.id?'✓':''}</span></button>`).join('');
  const title=publishing?(t?'修改课程作业':'发布课程作业'):(t?'编辑个人作业':'记个人作业');
  showDialog(`<div class="hw-detail hw-editor"><header class="hw-editor-header"><h2 id="dialog-title">${title}</h2><button type="button" class="icon-button" data-close aria-label="关闭详情"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><path d="m6 6 12 12M6 18 18 6"/></svg></button></header><form id="hw-form" novalidate data-scope="${publishing?'course':'personal'}"><div class="hw-form-content"><p class="hw-scope-note ${publishing?'hw-scope-course':''}">${publishing?publisherScope(publisher):'仅自己可见，不会发布给同学。'}</p>${publishing?publishPicker(key,t):''}<label>作业名称 <span>必填</span><input name="title" aria-label="作业名称" required maxlength="120" placeholder="例如：系统工程案例分析" value="${esc(t?.title||'')}"></label>${publishing?'':`<div class="hw-course-field"><div id="hw-course-label">所属课程 <span>必选</span></div><input type="hidden" name="courseId" value="${esc(selected)}"><details class="hw-picker hw-form-picker"><summary aria-labelledby="hw-course-label hw-course-value"><span id="hw-course-value">${esc(course(selected)?.name||'选择课程')}</span>${chevron}</summary><div class="hw-picker-panel"><div class="hw-picker-options">${options}</div></div></details></div>`}${deadlineFields(t)}<label>具体要求 <span>选填</span><textarea name="notes" aria-label="具体要求" rows="7" maxlength="10000" placeholder="任务与题目：\n提交内容、格式与方式：\n个人或小组要求：\n字数、参考资料及其他说明：">${esc(t?.notes||'')}</textarea><small class="hw-field-help">保留老师的具体要求；图片可以交给已连接的 AI 整理为文字后保存。</small></label>${t?`<div class="hw-actions">${publishing?'':`<button type="button" data-hw-toggle="${esc(t.id)}">${t.completedAt?'恢复待完成':'标记已完成'}</button>`}<button type="button" class="hw-danger" data-hw-delete-prompt>${publishing?'撤回课程作业':'删除作业'}</button></div><div class="hw-delete-confirm" hidden><p>${publishing?'撤回后，同学将不再看到这项作业。可立即撤销。':'删除这项个人作业？删除后可立即撤销。'}</p><button type="button" class="hw-danger" data-hw-delete="${esc(t.id)}">${publishing?'确认撤回':'确认删除'}</button><button type="button" data-hw-delete-cancel>保留作业</button></div>`:''}</div><footer class="hw-editor-footer"><p class="hw-form-error" role="alert"></p><button class="primary-button hw-save" type="submit">${publishing?(t?'保存课程作业':'发布给本教学班'):(t?'保存修改':'保存个人作业')}</button></footer></form></div>`,{kind:'homework-editor'});
  mountDeadline(dialog().querySelector('#hw-form'));
 }
 function notify(message,action=null){clearTimeout(timer);undo=action;const box=document.querySelector('#hw-toast');box.innerHTML=`<span>${esc(message)}</span>${action?'<button data-hw-undo>撤销</button>':''}`;box.hidden=false;timer=setTimeout(()=>{box.hidden=true;undo=null;},8000);}
 async function write(id,expected,mutate){
  if(!loaded||busy)throw Error('正在同步，请稍后再试');busy=true;
  try{const before=cache.find(t=>t.id===id)||null;const source={...mutate(before),id,revision:expected||''};const task=Object.fromEntries(privateFields.map(k=>[k,source[k]]));const result=await api('homework',{expected,task});apply(result);return result;}finally{busy=false;}
 }
 async function sharedWrite(payload){
  if(!loaded||busy)throw Error('正在同步，请稍后再试');busy=true;
  try{const result=await api('course-homework',payload);apply(result);if(managed){managed.items=managed.items.filter(t=>t.id!==result.next.id);if(result.next.offeringKey===managed.course.key&&!result.next.deletedAt)managed.items.push(result.next);}return result;}finally{busy=false;}
 }
 function finish(message,action){if(dialog().open)dialog().close();render();notify(message,action);}
 function changed(result,message){finish(message,async()=>{const previous=result.before;await write(result.next.id,result.next.revision,t=>previous?{...previous}:{...t,deletedAt:new Date().toISOString()});render();notify('已撤销');});}
 async function openManaged(key){
  const response=await api('course-homework?course='+encodeURIComponent(key));
  managed=response;
  showDialog(`<div class="hw-detail hw-shared-list">${dialogTop('课程作业')}<h2 id="dialog-title">${esc(response.course.name)}</h2><p class="panel-subtitle">${esc(response.course.teacher)} · 教学班 ${esc(response.course.courseId)}</p>${response.canEdit?`<button class="primary-button" data-course-publish="${esc(key)}">＋ 发布课程作业</button>`:''}<div class="hw-managed-list">${response.items.length?response.items.map(t=>`<button class="hw-managed-item" data-hw-edit="${esc(t.id)}"><span><strong>${esc(t.title)}</strong><small>${dateText(t)} · ${esc(t.author)}发布</small></span><span aria-hidden="true">›</span></button>`).join(''):'<p class="hw-muted">还没有发布课程作业。</p>'}</div></div>`);
 }
 dialog().addEventListener('close',()=>{editing=null;publishKey='';});
 document.addEventListener('submit',async event=>{
  if(event.target.id!=='hw-form')return;event.preventDefault();const f=event.target;if(f.getAttribute('aria-busy')==='true')return;const timeError=f.validateDeadline();if(timeError)return;const v=new FormData(f),prior=editing,key=String(v.get('offeringKey')||publishKey),publishing=f.dataset.scope==='course';
  const save=f.querySelector('[type=submit]'),label=save.textContent;
  try{
   f.querySelector('.hw-form-error').textContent='';
   if(!String(v.get('title')||'').trim()){f.elements.title.setAttribute('aria-invalid','true');f.elements.title.focus();throw Error('请填写作业名称。');}
   f.elements.title.removeAttribute('aria-invalid');f.setAttribute('aria-busy','true');save.disabled=true;save.textContent=publishing?'正在发布…':'正在保存…';
   const content={title:String(v.get('title')).trim(),dueDate:String(v.get('dueDate')||''),dueTime:String(v.get('dueTime')||''),notes:String(v.get('notes')||'').trim()};
   if(publishing){if(!key||!publishCourses.some(c=>c.key===key))throw Error('请选择要发布的课程。');await sharedWrite({action:'save',key,id:prior?.id||'coursework-'+crypto.randomUUID(),expected:prior?.revision||null,task:content});finish(prior?'课程作业已更新':'已发布给本教学班');}
   else{
    const c=String(v.get('courseId'));if(!course(c)&&prior?.courseId!==c)throw Error('请选择有效课程。');
    const now=new Date().toISOString(),result=await write(prior?.id||crypto.randomUUID(),prior?.revision||null,()=>({...prior,...content,courseId:c,createdAt:prior?.createdAt||now,updatedAt:now,completedAt:prior?.completedAt||'',deletedAt:''}));
    if(!prior){status='pending';filter='';}changed(result,prior?'修改已保存':'个人作业已保存');
   }
  }catch(e){f.querySelector('.hw-form-error').textContent=e.message;}finally{f.removeAttribute('aria-busy');save.disabled=false;save.textContent=label;}
 });
 document.addEventListener('change',e=>{if(e.target.name==='dueDate'&&e.target.closest('#hw-form')){const time=e.target.form.elements.dueTime;time.disabled=!e.target.value;if(time.disabled)time.value='';}});
 document.addEventListener('click',async e=>{
  const b=e.target.closest('button');if(!b||b.disabled)return;
  try{
   const draft=dialog().querySelector('.hw-comment-form textarea');
   if((b.dataset.sharedEdit||b.dataset.hwToggle)&&draft?.value.trim()&&!await confirmAction({title:'放弃未发表的留言？',message:'继续操作会关闭当前详情，未发表的内容不会保留。',confirm:'放弃并继续',cancel:'继续编辑',danger:true}))return;
   if(b.hasAttribute('data-hw-publish')){b.disabled=true;try{await refresh();open(null,filter,'',true);}finally{b.disabled=false;}return;}
   if(b.hasAttribute('data-hw-publish-course')){
    const f=b.closest('form'),key=b.dataset.hwPublishCourse,p=publishCourses.find(c=>c.key===key);if(!p)return;
    f.elements.offeringKey.value=key;publishKey=key;f.querySelector('#hw-publish-value').textContent=p.name;f.querySelector('.hw-scope-note').innerHTML=publisherScope(p);
    f.querySelectorAll('[data-hw-publish-course]').forEach(item=>{const active=item.dataset.hwPublishCourse===key;item.setAttribute('aria-pressed',String(active));item.lastElementChild.textContent=active?'✓':'';});
    const picker=b.closest('details');picker.open=false;picker.querySelector('summary').focus();return;
   }
   if(b.dataset.courseHomework){await openManaged(b.dataset.courseHomework);return;}
   if(b.dataset.coursePublish){open(null,'',b.dataset.coursePublish);return;}
   if(b.dataset.sharedEdit){const t=find(b.dataset.sharedEdit);if(t)open(t.id,'',t.offeringKey);return;}
   if(b.dataset.hwDay){openDay(b.dataset.hwDay);return;}
   if(b.hasAttribute('data-hw-add')){open(null,b.dataset.hwAdd||filter);return;}
   if(b.dataset.hwEdit){open(b.dataset.hwEdit);return;}
   if(b.hasAttribute('data-hw-course')){const f=b.closest('form'),id=b.dataset.hwCourse;f.elements.courseId.value=id;f.querySelector('#hw-course-value').textContent=course(id).name;f.querySelectorAll('[data-hw-course]').forEach(item=>{const active=item.dataset.hwCourse===id;item.setAttribute('aria-pressed',String(active));item.lastElementChild.textContent=active?'✓':'';});const picker=b.closest('details');picker.open=false;picker.querySelector('summary').focus();return;}
   if(b.hasAttribute('data-hw-filter')){filter=b.dataset.hwFilter;render();document.querySelector('.hw-picker summary')?.focus();return;}
   if(b.dataset.hwScope){scopeFilter=b.dataset.hwScope;render();return;}
   if(b.dataset.hwStatus){status=b.dataset.hwStatus;render();return;}
   if(b.hasAttribute('data-hw-delete-prompt')){const t=editing;if(!t)return;const shared=t.scope==='course';if(!await confirmAction({title:shared?'撤回这项课程作业？':'删除这项个人作业？',message:shared?'撤回后，本教学班的同学将不再看到。操作完成后可立即撤销。':'这项作业将从你的列表移除。操作完成后可立即撤销。',confirm:shared?'撤回作业':'删除作业',danger:true}))return;b.dataset.hwDelete=t.id;}
   if(b.hasAttribute('data-hw-delete-cancel')){document.querySelector('.hw-delete-confirm').hidden=true;return;}
   if(b.hasAttribute('data-hw-undo')){const action=undo;undo=null;if(action)await action();return;}
   const id=b.dataset.hwToggle||b.dataset.hwDelete;
   if(id){
    const t=editing?.id===id?editing:find(id);if(!t)return;const deleting=!!b.dataset.hwDelete;
    if(t.scope==='course'){
     const result=await sharedWrite(deleting?{action:'delete',id,key:t.offeringKey,expected:t.revision}:{action:'complete',id,completed:!t.completedAt,expected:t.completionRevision});
     finish(deleting?'课程作业已撤回':result.next.completedAt?'已标记完成，仅自己可见':'已恢复待完成',async()=>{
      await sharedWrite(deleting?{action:'restore',id,key:t.offeringKey,expected:result.next.revision}:{action:'complete',id,completed:!!t.completedAt,expected:result.next.completionRevision});render();notify('已撤销');
     });
    }else{
     const result=await write(id,t.revision,old=>({...old,updatedAt:new Date().toISOString(),...(deleting?{deletedAt:new Date().toISOString()}:{completedAt:old.completedAt?'':new Date().toISOString()})}));changed(result,deleting?'作业已删除':result.next.completedAt?'已标记完成':'已恢复待完成');
    }
   }
  }catch(e){const field=dialog().open&&dialog().querySelector('.hw-form-error');if(field)field.textContent=e.message;else notify(e.message);}
 });
 document.addEventListener('click',e=>{document.querySelectorAll('.hw-picker[open]').forEach(picker=>{if(!picker.contains(e.target))picker.open=false;});});
 document.addEventListener('keydown',e=>{if(e.key==='Escape'){const picker=document.querySelector('.hw-picker[open]');if(picker){e.preventDefault();picker.open=false;picker.querySelector('summary').focus();}}});
 async function syncVisible(){
  if(!loaded||busy||!owner()||document.hidden||dialog().open||!['today','week','homework'].includes(document.body.dataset.route)||document.activeElement?.matches('input,textarea'))return;
  try{const before=JSON.stringify([cache,publishCourses]);await refresh();if(JSON.stringify([cache,publishCourses])!==before)render();}catch(e){problem=e.message;}
 }
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)syncVisible();});
 setInterval(syncVisible,60000);
 return {page,home,courseSection,dayBadge,refresh:async()=>{try{await refresh();}catch(e){problem=e.message;}},clear:()=>{generation++;scopeFilter='all';filter='';status='pending';cache=[];publishCourses=[];loaded=false;busy=false;undo=null;editing=null;publishKey='';managed=null;problem='';clearTimeout(timer);}};
}
