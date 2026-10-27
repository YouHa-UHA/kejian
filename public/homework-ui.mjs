import {request} from './account.mjs';
import {confirmAction} from './confirm-ui.mjs';
import {mountComments} from './comments-ui.mjs';
import {deadlineFields,mountDeadline} from './deadline-ui.mjs';
import {submissionSection} from './submission.mjs';
import {overdue,sortTasks,filterTasks,taskCourses,groupTasks} from './homework.mjs';
import {courseIdentity,courseChoice} from './course-ui.mjs';
import {escapeHTML as esc,chinaClock,addDays,dateLabel} from './schedule.mjs';

const privateFields=['id','title','courseId','notes','submission','dueDate','dueTime','createdAt','updatedAt','completedAt','deletedAt','revision'];
const pickerSearch='<label class="picker-search"><input type="search" data-picker-search placeholder="搜索课程、老师或教学班" aria-label="搜索可选课程" autocomplete="off"></label><p class="picker-empty" hidden>没有匹配的课程</p>';
const chevron='<svg class="hw-picker-chevron" aria-hidden="true" viewBox="0 0 24 24" fill="none"><path d="m6 9 6 6 6-6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
const addIcon='<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>';
const personalAction=(courseId='',variant='secondary-button')=>`<button type="button" class="${variant} hw-add-button" data-hw-add="${esc(courseId)}">${addIcon}<span>记个人作业</span></button>`;

export function createHomework({courses,render,showDialog,dialogTop,goRoute,owner,mountDiscussion=mountComments}){
 let cache=[],publishCourses=[],loaded=false,busy=false,generation=0;
 let status='pending',scopeFilter='all',filter='',problem='',undo=null,timer,editing=null,publishKey='',managed=null;
 const dialog=()=>document.querySelector('#detail-dialog');
 const all=()=>cache.filter(t=>!t.deletedAt);
 const course=id=>courses().find(c=>c.id===id);
 const filterCourses=()=>taskCourses(courses(),all());
 const tasks=()=>sortTasks(all());
 const find=id=>all().find(t=>t.id===id)||managed?.items.find(t=>t.id===id);
 const courseName=t=>t.courseName||course(t.courseId)?.name||'原课程';
 const duplicateName=t=>filterCourses().filter(c=>c.name===courseName(t)).length>1;
 const publisherScope=p=>p?`发布给「${esc(p.name)}」教学班<small>${esc(courseIdentity(p))}${p.enrolled===false?' · 你未加入此教学班':''}</small>`:'课程作业对所选教学班的同学可见。';
 function publishPicker(key,editing){
  const chosen=publishCourses.find(c=>c.key===key);
  return `<input type="hidden" name="offeringKey" value="${esc(key)}">${editing||publishCourses.length===1?'':`<div class="hw-course-field"><div id="hw-publish-label">发布课程 <span>必选</span></div><details class="hw-picker hw-form-picker"><summary aria-labelledby="hw-publish-label hw-publish-value"><span id="hw-publish-value">${courseChoice(chosen)}</span>${chevron}</summary><div class="hw-picker-panel">${pickerSearch}<div class="hw-picker-options">${publishCourses.map(c=>`<button type="button" data-hw-publish-course="${esc(c.key)}" aria-pressed="${key===c.key}">${courseChoice(c)}<span class="publisher-membership">${c.enrolled?'我正在上':'其他教学班'}</span><span aria-hidden="true">${key===c.key?'✓':''}</span></button>`).join('')}</div></div></details></div>`}`;
 }
 function pageActions(){return publishCourses.length?`<div class="hw-page-actions">${personalAction()}<button class="primary-button" data-hw-publish>发布课程作业</button></div>`:personalAction('','primary-button');}

 const dateText=t=>!t.dueDate?'截止日期待定':`${dateLabel(t.dueDate,t.dueDate.slice(0,4)!==chinaClock().date.slice(0,4))}${t.dueTime?' '+t.dueTime+' 截止':' 截止 · 时间待定'}`;
 const apply=result=>{cache=result.items;publishCourses=[...(result.publishCourses||[])].sort((a,b)=>Number(b.enrolled)-Number(a.enrolled));loaded=true;problem='';};
 async function api(path,payload){
  const who=owner(),version=generation;
  const result=await request(path,payload?{owner:who,...payload}:undefined);
  if(who!==owner()||version!==generation)throw Error('身份已变化，请重新进入');
  return result;
 }
 async function refresh(){const result=await api('homework');if(result.owner!==owner())throw Error('身份已变化，请重新进入');apply(result);}
 function rows(items){return items.map(t=>`<article class="hw-row ${t.completedAt?'hw-done':''}"><button class="hw-check" data-hw-toggle="${esc(t.id)}" aria-label="${t.completedAt?'恢复待完成':'标记完成'}：${esc(t.title)}" aria-pressed="${!!t.completedAt}">${t.completedAt?'✓':'<span></span>'}</button><button class="hw-body" data-hw-edit="${esc(t.id)}"><span class="hw-title-line"><strong>${esc(t.title)}</strong><span class="hw-scope-badge ${t.scope==='course'?'is-course':''}">${t.scope==='course'?'课程作业':'个人作业'}</span></span><span class="hw-meta"><span class="hw-course">${esc(courseName(t))}</span><span class="${overdue(t,chinaClock())?'hw-overdue':''}">${overdue(t,chinaClock())?'已逾期 · ':''}${dateText(t)}</span></span>${duplicateName(t)?`<span class="hw-class-identity">${esc(courseIdentity(course(t.courseId)||{courseId:t.courseId,teacher:t.teacher}))}</span>`:''}${t.scope==='course'?`<span class="hw-source">${esc(t.author)}发布</span>`:''}${t.notes?`<span class="hw-notes">${esc(t.notes)}</span>`:''}</button><button class="hw-edit" data-hw-edit="${esc(t.id)}" aria-label="查看：${esc(t.title)}">›</button></article>`).join('');}
 function error(){return problem?`<p class="hw-error" role="alert">${esc(problem)}</p>`:'';}
 function page(){
  const list=tasks(),pending=list.filter(t=>!t.completedAt),done=list.filter(t=>t.completedAt);
  const visible=filterTasks(list,{status,courseId:filter,scope:scopeFilter});
  const choices=filterCourses(),chosen=choices.find(c=>c.id===filter),filtered=!!filter||scopeFilter!=='all';
  const empty=filtered?`<h2>当前筛选下没有作业</h2><p>试试其他课程或作业类型。</p><button class="secondary-button" data-hw-reset>清除筛选</button>`:
   `<h2>${status==='done'?'还没有已完成的作业':'暂无待完成作业'}</h2><p>${status==='done'?'完成的作业会保留在这里。':'课程作业会自动显示，也可以记一项自己的作业。'}</p>`;
  return `<section class="page-intro hw-intro"><div><h1>作业</h1><p>${pending.length} 项待完成${pending.filter(t=>overdue(t,chinaClock())).length?' · '+pending.filter(t=>overdue(t,chinaClock())).length+' 项逾期':''}</p></div>${pageActions()}</section>
  <div class="hw-toolbar"><div class="view-switch" role="group" aria-label="作业状态"><button data-hw-status="pending" aria-pressed="${status==='pending'}">待完成 ${pending.length}</button><button data-hw-status="done" aria-pressed="${status==='done'}">已完成 ${done.length}</button></div>
  <details class="hw-picker"><summary aria-label="按课程筛选">${courseChoice(chosen,'全部课程')}${chevron}</summary><div class="hw-picker-panel">${pickerSearch}<div class="hw-picker-options">${[{id:'',name:'全部课程'},...choices].map(c=>`<button data-hw-filter="${esc(c.id)}" aria-label="${esc(c.name+' '+courseIdentity(c))}" aria-pressed="${filter===c.id}">${courseChoice(c)}<span aria-hidden="true">${filter===c.id?'✓':''}</span></button>`).join('')}</div></div></details></div>${error()}
  <div class="hw-filter-row"><div class="hw-scope-filters" role="group" aria-label="作业类型">${[['all','全部'],['course','课程作业'],['personal','个人作业']].map(([value,label])=>`<button data-hw-scope="${value}" aria-pressed="${scopeFilter===value}">${label}</button>`).join('')}</div>${filtered?'<button class="secondary-button compact-button hw-reset" data-hw-reset>清除筛选</button>':''}</div>
  <div class="hw-list">${visible.length?groupTasks(visible,chinaClock()).map(g=>`<section class="hw-group" aria-label="${g.title}"><div class="hw-group-heading ${g.id==='overdue'?'is-overdue':''}"><h2>${g.title}</h2><span>${g.items.length}</span></div>${rows(g.items)}</section>`).join(''):`<div class="hw-empty">${empty}</div>`}</div>`;
 }
 function home(){const list=tasks().filter(t=>!t.completedAt&&t.dueDate&&t.dueDate<=addDays(chinaClock().date,7)).slice(0,3);return list.length?`<section class="hw-preview"><div class="section-heading"><h2>近期作业</h2><a class="text-link" href="#homework">查看全部 →</a></div>${rows(list)}</section>`:error();}
 function courseSection(id){const list=tasks().filter(t=>t.courseId===id&&!t.completedAt),publisher=publishCourses.find(c=>c.courseId===id&&c.enrolled);return `<section class="hw-course-section"><div class="section-heading"><h3>待完成作业${list.length?' · '+list.length:''}</h3><div class="hw-course-actions">${personalAction(id)}${publisher?`<button class="secondary-button" data-course-homework="${esc(publisher.key)}">管理课程作业</button>`:''}</div></div>${error()}${list.length?'<div class="course-assignment-list">'+rows(list)+'</div>':'<p class="hw-muted">这门课还没有待完成作业。</p>'}</section>`;}
 function dayBadge(day){const list=tasks().filter(t=>t.dueDate===day);if(!list.length)return '';const pending=list.filter(t=>!t.completedAt).length;return `<button class="hw-day-badge ${pending?'':'hw-day-done'}" data-hw-day="${day}" aria-label="${dateLabel(day,true)}，${list.length}项作业，${pending}项待完成">${pending?'作业'+pending:'✓'}</button>`;}
 function openDay(day){const list=tasks().filter(t=>t.dueDate===day);showDialog(`<div class="hw-detail hw-day-detail">${dialogTop('截止作业')}<h2 id="dialog-title">${dateLabel(day,true)}</h2><p class="hw-muted">${list.filter(t=>!t.completedAt).length} 项待完成 · ${list.length} 项作业</p>${error()}${rows(list)}</div>`);}
 function detail(t){
  const shared=t.scope==='course';
  if(shared){
   const identity=courseIdentity({...course(t.courseId),...t});
   const due=t.dueDate?`${dateLabel(t.dueDate,t.dueDate.slice(0,4)!==chinaClock().date.slice(0,4))}${t.dueTime?' '+t.dueTime:' · 时间待定'}`:'日期待定';
   showDialog(`<div class="hw-detail hw-shared-detail reading-page assignment-detail" data-task-detail="${esc(t.id)}">${dialogTop('课程作业')}
    <header class="reading-heading assignment-heading"><div class="assignment-course-line"><span>${esc(courseName(t))}</span>${t.completedAt?'<span class="assignment-state">已完成</span>':''}</div><h2 id="dialog-title" class="reading-title">${esc(t.title)}</h2><p class="reading-class-id">${esc(identity)}</p></header>
    <div class="assignment-layout"><div class="assignment-main"><div class="assignment-deadline ${overdue(t,chinaClock())?'is-overdue':''}"><span>截止时间</span><strong>${due}</strong>${overdue(t,chinaClock())?'<small>已逾期</small>':''}</div><section class="hw-requirements-section"><h3>具体要求</h3><div class="hw-requirements">${esc(t.notes||'尚未填写具体要求，可在讨论中询问课代表。')}</div></section>${submissionSection(t.submission)}<p class="hw-publisher">${esc(t.author)}发布${t.updatedBy&&t.updatedBy!==t.author?' · '+esc(t.updatedBy)+'更新':''}</p></div><aside class="hw-discussion" aria-label="作业讨论"></aside></div>
    <footer class="reading-actionbar"><p class="detail-privacy">${t.canComplete?'完成状态仅自己可见。':'你正在管理本教学班的课程作业。'}</p><div class="hw-shared-actions">${t.canComplete?`<button class="primary-button" data-hw-toggle="${esc(t.id)}">${t.completedAt?'恢复待完成':'标记已完成'}</button>`:''}${t.canEdit?`<button class="secondary-button" data-shared-edit="${esc(t.id)}">修改课程作业</button>`:''}</div></footer></div>`,{kind:'homework-detail'});
   mountDiscussion(dialog().querySelector('.hw-discussion'),{homework:t.id,api});return;
  }
  showDialog(`<div class="hw-detail hw-shared-detail" data-task-detail="${esc(t.id)}">${dialogTop(shared?'课程作业':'个人作业')}<span class="hw-detail-course">${esc(courseName(t))}</span><p class="hw-detail-context">${esc(courseIdentity(course(t.courseId)||{courseId:t.courseId}))}</p><h2 id="dialog-title">${esc(t.title)}</h2><div class="hw-detail-deadline ${overdue(t,chinaClock())?'is-overdue':''}"><span>${t.completedAt?'已完成':overdue(t,chinaClock())?'已逾期':'截止安排'}</span><strong>${dateText(t)}</strong></div>${shared?`<p class="hw-publisher">${esc(t.author)}发布${t.updatedBy&&t.updatedBy!==t.author?' · '+esc(t.updatedBy)+'更新':''}</p>`:''}<section class="hw-requirements-section"><h3>具体要求</h3><div class="hw-requirements">${esc(t.notes||(shared?'尚未填写具体要求，可在下方询问课代表。':'暂未填写具体要求。'))}</div></section>${submissionSection(t.submission)}<div class="hw-shared-actions">${!shared||t.canComplete?`<button class="primary-button" data-hw-toggle="${esc(t.id)}">${t.completedAt?'恢复待完成':'标记已完成'}</button>`:''}${!shared||t.canEdit?`<button class="secondary-button" ${shared?'data-shared-edit':'data-personal-edit'}="${esc(t.id)}">${shared?'修改课程作业':'编辑个人作业'}</button>`:''}</div><p class="detail-privacy">${shared?'完成状态仅自己可见。':'个人作业仅自己可见。'}</p>${shared?'<section class="hw-discussion"></section>':''}</div>`,{kind:'detail'});
  if(shared)mountDiscussion(dialog().querySelector('.hw-discussion'),{homework:t.id,api});
 }
 function open(id=null,courseId='',key='',publishing=false,edit=false){
  const t=id?find(id):null;if(id&&!t)return;
  if(problem){notify(problem);return;}
  if(t&&!key&&!edit){detail(t);return;}
  publishing=publishing||!!key;
  if(!publishing&&!t&&!courses().length){showDialog(`<div class="hw-detail">${dialogTop('个人作业')}<h2 id="dialog-title">先添加一门课程</h2><p class="panel-subtitle">个人作业需要关联课程。先导入自己的课表，或从班级课程中选择正在上的教学班。</p><div class="workflow-actions"><button class="secondary-button" data-library>从班级课程添加</button><button class="primary-button" data-import>导入课表</button></div></div>`);return;}
  if(publishing&&!key)key=publishCourses.find(c=>c.courseId===courseId)?.key||(publishCourses.length===1?publishCourses[0].key:'');
  const publisher=publishing?publishCourses.find(c=>c.key===key):null;
  if(publishing&&(!publishCourses.length||(key&&!publisher))){notify('课程管理权限已变化，请刷新后重试');return;}
  editing=t;publishKey=key;
  const selected=t?.courseId||(course(courseId)?courseId:'');
  const options=courses().map(c=>`<button type="button" data-hw-course="${esc(c.id)}" aria-label="${esc(c.name+' '+courseIdentity(c))}" aria-pressed="${selected===c.id}">${courseChoice(c)}<span aria-hidden="true">${selected===c.id?'✓':''}</span></button>`).join('');
  const title=publishing?(t?'修改课程作业':'发布课程作业'):(t?'编辑个人作业':'记个人作业');
  showDialog(`<div class="hw-detail hw-editor"><header class="hw-editor-header"><h2 id="dialog-title">${title}</h2><button type="button" class="icon-button" data-close aria-label="关闭详情"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><path d="m6 6 12 12M6 18 18 6"/></svg></button></header><form id="hw-form" novalidate data-scope="${publishing?'course':'personal'}"><div class="hw-form-content"><p class="hw-scope-note ${publishing?'hw-scope-course':''}">${publishing?publisherScope(publisher):'仅自己可见，不会发布给同学。'}</p>${publishing?publishPicker(key,t):''}<label>作业名称 <span>必填</span><input name="title" aria-label="作业名称" required maxlength="120" placeholder="例如：系统工程案例分析" value="${esc(t?.title||'')}"></label>${publishing?'':`<div class="hw-course-field"><div id="hw-course-label">所属课程 <span>必选</span></div><input type="hidden" name="courseId" value="${esc(selected)}"><details class="hw-picker hw-form-picker"><summary aria-labelledby="hw-course-label hw-course-value"><span id="hw-course-value">${courseChoice(course(selected)||(t?filterCourses().find(c=>c.id===selected):null))}</span>${chevron}</summary><div class="hw-picker-panel">${pickerSearch}<div class="hw-picker-options">${options}</div></div></details></div>`}${deadlineFields(t)}<label>具体要求 <span>选填</span><textarea name="notes" aria-label="具体要求" rows="7" maxlength="10000" placeholder="任务与题目：\n提交内容与格式：\n个人或小组要求：\n字数、参考资料及其他说明：">${esc(t?.notes||'')}</textarea><small class="hw-field-help">写清题目、提交内容和格式。老师发的是图片？可交给已连接的 AI 转为文字。</small></label><label>提交方式 <span>选填</span><textarea name="submission" aria-label="提交方式" rows="3" maxlength="2000" placeholder="例如：https://…，或线下交至工教二301；也可填写邮箱、课程群及提交步骤。">${esc(t?.submission||'')}</textarea><small class="hw-field-help">填写提交网址、线下地点或渠道说明；未通知可留空。</small></label>${t?`<div class="hw-actions"><button type="button" class="secondary-button compact-button is-danger hw-danger" data-hw-delete-prompt>${publishing?'撤回课程作业':'删除作业'}</button></div>`:''}</div><footer class="hw-editor-footer"><p class="hw-form-error" role="alert"></p><button class="primary-button hw-save" type="submit">${publishing?(t?'保存课程作业':'发布给本教学班'):(t?'保存修改':'保存个人作业')}</button></footer></form></div>`,{kind:'homework-editor'});
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
   f.elements.title.removeAttribute('aria-invalid');f.setAttribute('aria-busy','true');save.disabled=true;save.textContent=publishing&&!prior?'正在发布…':'正在保存…';
   const content={title:String(v.get('title')).trim(),dueDate:String(v.get('dueDate')||''),dueTime:String(v.get('dueTime')||''),notes:String(v.get('notes')||'').trim(),submission:String(v.get('submission')||'').trim()};
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
    f.elements.offeringKey.value=key;publishKey=key;f.querySelector('#hw-publish-value').innerHTML=courseChoice(p);f.querySelector('.hw-scope-note').innerHTML=publisherScope(p);
    f.querySelectorAll('[data-hw-publish-course]').forEach(item=>{const active=item.dataset.hwPublishCourse===key;item.setAttribute('aria-pressed',String(active));item.lastElementChild.textContent=active?'✓':'';});
    const picker=b.closest('details');picker.open=false;picker.querySelector('summary').focus();return;
   }
   if(b.dataset.courseHomework){await openManaged(b.dataset.courseHomework);return;}
   if(b.dataset.coursePublish){open(null,'',b.dataset.coursePublish);return;}
   if(b.dataset.personalEdit){open(b.dataset.personalEdit,'','',false,true);return;}
   if(b.dataset.sharedEdit){const t=find(b.dataset.sharedEdit);if(t)open(t.id,'',t.offeringKey);return;}
   if(b.dataset.hwDay){openDay(b.dataset.hwDay);return;}
   if(b.hasAttribute('data-hw-add')){open(null,b.dataset.hwAdd||filter);return;}
   if(b.dataset.hwEdit){open(b.dataset.hwEdit);return;}
   if(b.hasAttribute('data-hw-course')){const f=b.closest('form'),id=b.dataset.hwCourse;f.elements.courseId.value=id;f.querySelector('#hw-course-value').innerHTML=courseChoice(course(id));f.querySelectorAll('[data-hw-course]').forEach(item=>{const active=item.dataset.hwCourse===id;item.setAttribute('aria-pressed',String(active));item.lastElementChild.textContent=active?'✓':'';});const picker=b.closest('details');picker.open=false;picker.querySelector('summary').focus();return;}
   if(b.hasAttribute('data-hw-filter')){filter=b.dataset.hwFilter;render();document.querySelector('.hw-picker summary')?.focus();return;}
   if(b.dataset.hwScope){scopeFilter=b.dataset.hwScope;render();document.querySelector(`[data-hw-scope="${scopeFilter}"]`)?.focus({preventScroll:true});return;}
   if(b.dataset.hwStatus){status=b.dataset.hwStatus;render();document.querySelector(`[data-hw-status="${status}"]`)?.focus({preventScroll:true});return;}
   if(b.hasAttribute('data-hw-reset')){filter='';scopeFilter='all';render();document.querySelector('.hw-toolbar summary')?.focus({preventScroll:true});return;}
   if(b.hasAttribute('data-hw-delete-prompt')){const t=editing;if(!t)return;const shared=t.scope==='course';if(!await confirmAction({title:shared?'撤回这项课程作业？':'删除这项个人作业？',message:shared?'撤回后，本教学班的同学将不再看到。操作完成后可立即撤销。':'这项作业将从你的列表移除。操作完成后可立即撤销。',confirm:shared?'撤回作业':'删除作业',danger:true}))return;b.dataset.hwDelete=t.id;}
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
 async function syncVisible(){
  if(!loaded||busy||!owner()||document.hidden||dialog().open||!['today','week','homework'].includes(document.body.dataset.route)||document.activeElement?.matches('input,textarea'))return;
  try{const before=JSON.stringify([cache,publishCourses]);await refresh();if(JSON.stringify([cache,publishCourses])!==before)render();}catch(e){problem=e.message;}
 }
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)syncVisible();});
 setInterval(syncVisible,60000);
 return {page,home,courseSection,dayBadge,openNotification:id=>{const task=all().find(t=>t.id===id);if(!task||problem)return false;detail(task);return true;},refresh:async()=>{try{await refresh();}catch(e){problem=e.message;}},clear:()=>{generation++;scopeFilter='all';filter='';status='pending';cache=[];publishCourses=[];loaded=false;busy=false;undo=null;editing=null;publishKey='';managed=null;problem='';clearTimeout(timer);}};
}
