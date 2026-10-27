import {request,currentUser} from './account.mjs';
import {searchCourses} from './course-ui.mjs';
import {escapeHTML as esc,courseTimeSummary,classTimeLabel,dateLabel,weekday,WEEKDAYS} from './schedule.mjs';

export function createCommunity({getData,showDialog,dialogTop,reload,goRoute,render}){
 let library={courses:[],base:''},management=null,problem='',managementQuery='';
 const $=s=>document.querySelector(s);
 const canManage=()=>currentUser?.admin||currentUser?.representativeOf?.length;
 const send=async(path,b)=>{const owner=currentUser?.id;if(!owner)throw Error('请先登录');const result=await request(path,{owner,...b});if(currentUser?.id!==owner)throw Error('账号已变化，请刷新后重试');return result;};
 async function refresh(){const owner=currentUser?.id;const result=await request('course-library');if(currentUser?.id!==owner)throw Error('账号已变化');library=result;management=null;problem='';}
 async function manager(){const owner=currentUser?.id;const result=await request('management');if(currentUser?.id!==owner)throw Error('账号已变化');management=result;return result;}
 function libraryEntry(){return `<button class="library-entry" data-library><span class="library-entry-icon">＋</span><span><strong>添加已有课程</strong><small>从班级课程列表中选择</small></span><span aria-hidden="true">↗</span></button>`;}
 const chevron='<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m6 9 6 6 6-6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
 function schedulePreview(c){
  const sessions=[...(c.sessions||[])].sort((a,b)=>(a.date+(a.start_time||'')).localeCompare(b.date+(b.start_time||'')));
  const r=c.recurrence;
  return `<p class="library-time">${esc(courseTimeSummary(c))}</p>${r?`<p class="library-card-meta">${esc(dateLabel(r.starts_on,true))}起${r.until?'，至'+esc(dateLabel(r.until,true)):'，结束日期待通知'}${r.excluded_dates?.length?'；停课日期：'+r.excluded_dates.map(d=>esc(dateLabel(d,true))).join('、'):''}</p>`:''}${sessions.length?`<details class="library-dates"><summary><span>查看上课日期 · ${sessions.length} 次安排</span>${chevron}</summary><ol>${sessions.map(s=>`<li><time datetime="${esc(s.date)}">${esc(dateLabel(s.date,true))} · 周${WEEKDAYS[weekday(s.date)]}</time><span>${esc(classTimeLabel(s))}</span>${s.kind==='online'?'<small>线上授课</small>':s.kind==='fieldwork'?'<small>实践活动 · 地点待通知</small>':s.location&&s.location!==c.location?`<small>${esc(s.location)}</small>`:''}${s.note?`<small>${esc(s.note)}</small>`:''}</li>`).join('')}</ol></details>`:''}`;
 }
 function card(c){return `<article class="library-card"><div class="library-card-heading"><span class="library-course-mark">${esc(c.name.slice(0,1))}</span><div><h3>${esc(c.name)}</h3><p>${esc(c.teacher||'教师待确认')} · ${esc(c.location||(c.recurrence?'线上授课':'地点待确认'))}</p></div>${c.subscribed?'<span class="subscribed-label">已加入</span>':''}</div><p class="library-card-meta">${esc(c.term)} · 教学班 ${esc(c.courseId)}</p>${schedulePreview(c)}${c.representatives.length?`<p class="library-card-meta">课代表 ${c.representatives.map(r=>esc(r.name)).join('、')}</p>`:''}<button class="secondary-button" ${c.subscribed?`data-course="${esc(c.courseId)}"`:`data-subscribe="${esc(c.key)}"`}>${c.subscribed?'查看课程':'加入我的课表'}</button></article>`;}
 async function openLibrary(){
  showDialog(`<div class="library-detail">${dialogTop('班级课程')}<h2 id="dialog-title">添加已有课程</h2><p class="panel-subtitle">核对老师、上课时间和教学班编号后添加。同名课程可能属于不同教学班。</p><div id="library-content" aria-live="polite">正在读取课程…</div></div>`,{kind:'course-library'});
  try{await refresh();if(!$('#library-content'))return;$('#library-content').innerHTML=library.courses.length?`<label class="search-box"><input type="search" id="library-search" placeholder="搜索课程、老师或教学班" aria-label="搜索班级课程"></label><div id="library-results" class="library-grid">${library.courses.map(card).join('')}</div>`:'<div class="hw-empty"><h3>班级课程列表暂无课程</h3><p>你仍可以导入自己的课表。</p></div>';
  if($('#library-search'))$('#library-search').oninput=e=>{const courses=searchCourses(library.courses,e.target.value);$('#library-results').innerHTML=courses.map(card).join('')||'<p class="panel-subtitle">没有找到匹配的课程，试试课程名、老师或教学班编号。</p>';};
  }catch(err){if($('#library-content'))$('#library-content').textContent=err.message;}
 }
 function subscription(key){const c=library.courses.find(x=>x.key===key);if(!c)return;
  showDialog(`<div class="library-detail">${dialogTop('课程')}<h2 id="dialog-title">${esc(c.name)}</h2><p class="panel-subtitle">${esc(c.teacher)} · ${esc(c.location||(c.recurrence?'线上授课':'地点待确认'))}<br>教学班 ${esc(c.courseId)}</p>${schedulePreview(c)}<div class="subscription-note"><strong>${c.subscribed?'已加入个人课表':'加入这门课程'}</strong><p>${c.subscribed?'移出后不再展示这门课程及课程作业，自己记录的作业保留。可通过导入中的“恢复上一版”撤回。':'同一教学班不会重复添加；如果你已有不同安排，将保留自己的安排。'}</p></div><p class="panel-error" role="alert"></p><button class="${c.subscribed?'secondary-button':'primary-button'}" id="confirm-subscription">${c.subscribed?'移出我的课表':'确认加入课表'}</button></div>`);
  $('#confirm-subscription').onclick=async e=>{e.target.disabled=true;try{await send('course-library',{action:c.subscribed?'unsubscribe':'subscribe',key,revision:c.revision,base:library.base});$('#detail-dialog').close();await reload();}catch(err){$('.panel-error').textContent=err.message;e.target.disabled=false;}};
 }
 const auditNames={'course-remove':'移出个人课程',publish:'开放到班级课程列表',preload:'批量预置课程','representative-add':'设置课代表','representative-remove':'移除课代表','admin-add':'设置管理员',subscribe:'加入课程',unsubscribe:'移出课程','homework-publish':'发布课程作业','homework-save':'修改课程作业','homework-delete':'撤回课程作业','homework-restore':'恢复课程作业'};
 function page(){
  if(!canManage())return '<div class="empty-state"><h1>暂无管理权限</h1></div>';
  if(!management)return `<section class="page-intro"><h1>课程管理</h1></section><p class="panel-subtitle">${esc(problem||'正在读取…')}</p>${problem?'<button class="secondary-button" data-management-refresh>重试</button>':''}`;
  const m=management,opened=m.courses.filter(c=>c.published);
  const card=c=>`<article class="management-course" data-managed-search="${esc([c.name,c.teacher,c.courseId,c.location].join(' ').toLocaleLowerCase())}" ${searchCourses([c],managementQuery).length?'':'hidden'}><div class="management-course-top"><span>${esc(c.term)}</span>${c.subscribed?'<span class="course-membership">我正在上</span>':''}</div><h3>${esc(c.name)}</h3><p>${esc(c.teacher)} · ${esc(c.location||(c.recurrence?'线上授课':'地点待通知'))}</p><small>教学班 ${esc(c.courseId)}</small><p class="library-time">${esc(courseTimeSummary(c))}</p><div class="representative-row"><span>课代表</span><strong>${c.representatives.length?c.representatives.map(r=>esc(r.name)).join('、'):'暂未设置'}</strong>${m.admin?`<button class="secondary-button compact-button" data-representatives="${esc(c.key)}">设置</button>`:''}</div><button class="secondary-button management-homework" data-course-homework="${esc(c.key)}">查看课程作业</button></article>`;
  return `<section class="page-intro management-intro"><div><span class="section-kicker">${m.admin?'管理员':'课代表'}</span><h1>课程管理</h1><p>${m.admin?'管理班级课程与课代表。':'你负责的教学班'}</p></div></section>${opened.length?`<label class="search-box management-search"><input type="search" id="management-search" value="${esc(managementQuery)}" placeholder="搜索课程、老师或教学班" aria-label="搜索可管理课程"></label>`:''}<p class="management-no-match panel-subtitle" ${opened.length&&!searchCourses(opened,managementQuery).length?'':'hidden'}>没有匹配的教学班，试试课程名、老师或编号。</p><div class="management-grid">${opened.map(card).join('')||'<p class="panel-subtitle">暂无可管理的课程。</p>'}</div>${m.admin?`<details class="management-tools"><summary>班级设置<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m6 9 6 6 6-6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg></summary><div class="management-tool-row"><div><strong>添加班级课程</strong><p>开放后显示在班级课程列表，由同学自行添加。当前 ${opened.length} 个教学班。</p></div><button class="secondary-button" data-publish>选择课程</button></div><div class="management-tool-row"><div><strong>为同学预先加课</strong><p>为指定同学补充课程，保留已有安排。班级共 ${m.members.length} 人。</p></div><button class="secondary-button" data-preload>选择同学</button></div>${m.audit.length?`<details class="management-audit"><summary>最近管理记录</summary>${m.audit.map(a=>`<p><strong>${esc(auditNames[a.action]||a.action)}</strong><span>${esc(a.actor||'系统管理')} · ${esc(new Date(a.created_at).toLocaleString('zh-CN'))}</span></p>`).join('')}</details>`:''}</details>`:''}`;
 }
 async function openManagement(){try{await manager();problem='';}catch(err){problem=err.message;}goRoute('manage');}
 function publish(){const choices=getData().courses.filter(c=>!c.id.startsWith('import-'));
  showDialog(`<div class="management-detail">${dialogTop('班级课程')}<h2 id="dialog-title">开放到班级课程列表</h2><p class="panel-subtitle">从自己的课表选取已核对的课程，供同学自行添加，并由管理员或课代表维护课程作业。已有个人课表不会随这里的更新而改变。</p><div class="member-picker">${choices.map(c=>`<label><input type="checkbox" data-publish-course value="${esc(c.id)}"><span><strong>${esc(c.name)}</strong><small>教学班 ${esc(c.id)} · ${esc(c.teacher)}</small></span></label>`).join('')||'<p>请先导入包含教学班编号的课程。</p>'}</div><p class="panel-error" role="alert"></p><button class="primary-button" id="confirm-publish">开放到班级课程列表</button></div>`);
  $('#confirm-publish').onclick=async e=>{const courses=[...document.querySelectorAll('[data-publish-course]:checked')].map(x=>x.value);if(!courses.length){$('.panel-error').textContent='请先选择要开放的教学班。';return;}e.target.disabled=true;try{await refresh();await send('management',{action:'publish',courses,base:library.base});$('#detail-dialog').close();await refresh();await manager();render();}catch(err){$('.panel-error').textContent=err.message;e.target.disabled=false;}};
 }
 function preload(){
  const m=management;if(!m)return;
  const available=m.courses.filter(c=>c.published);
  showDialog(`<div class="management-detail preload-flow">${dialogTop('批量加课')}<h2 id="dialog-title">为同学预先加课</h2><p class="panel-subtitle">选好教学班和同学，下一步核对。已有安排会保留。</p><div id="preload-compose"><div class="preload-columns"><section><div class="picker-title"><h3>选择教学班</h3><span id="preload-course-count">已选 0 门</span></div><label class="search-box"><input type="search" id="preload-course-search" placeholder="课程、老师或教学班" aria-label="搜索预置课程"></label><div class="member-picker preload-courses">${available.map(c=>`<label data-preload-search="${esc([c.name,c.teacher,c.courseId].join(' '))}"><input type="checkbox" data-preload-course value="${esc(c.key)}"><span><strong>${esc(c.name)}</strong><small>${esc(c.teacher)} · 教学班 ${esc(c.courseId)}</small><small>${esc(courseTimeSummary(c))}</small></span></label>`).join('')||'<p>请先开放班级课程。</p>'}</div><p id="preload-course-empty" class="field-help" hidden>没有匹配的教学班。</p></section><section><div class="picker-title"><h3>选择同学</h3><span id="preload-count">已选 0 人</span></div><label class="search-box"><input type="search" id="member-search" placeholder="姓名或学号" aria-label="搜索同学"></label><div class="member-picker member-scroll">${m.members.map(x=>`<label data-member-name="${esc(x.name+' '+x.student)}"><input type="checkbox" data-preload-member value="${x.id}"><span><strong>${esc(x.name)}</strong><small>${esc(x.student)}</small></span></label>`).join('')}</div><p id="preload-member-empty" class="field-help" hidden>没有匹配的同学。</p></section></div><div class="workflow-actions"><button class="primary-button" id="preview-preload">下一步 · 核对范围</button></div></div><div id="preload-result" aria-live="polite"></div><p class="panel-error" role="alert"></p></div>`,{kind:'management-flow'});
  const root=$('.preload-flow'),compose=$('#preload-compose'),output=$('#preload-result'),error=root.querySelector('.panel-error');
  const active=()=>root.isConnected&&$('#detail-dialog').open;
  const filterRows=(input,selector,attribute,empty)=>{input.oninput=()=>{const rows=[...root.querySelectorAll(selector)];rows.forEach(x=>x.hidden=!x.getAttribute(attribute).toLocaleLowerCase().includes(input.value.trim().toLocaleLowerCase()));root.querySelector(empty).hidden=rows.some(x=>!x.hidden);};};
  filterRows($('#member-search'),'[data-member-name]','data-member-name','#preload-member-empty');
  filterRows($('#preload-course-search'),'[data-preload-search]','data-preload-search','#preload-course-empty');
  root.onchange=()=>{$('#preload-count').textContent='已选 '+root.querySelectorAll('[data-preload-member]:checked').length+' 人';$('#preload-course-count').textContent='已选 '+root.querySelectorAll('[data-preload-course]:checked').length+' 门';error.textContent='';};
  $('#preview-preload').onclick=async event=>{
   const button=event.currentTarget,members=[...root.querySelectorAll('[data-preload-member]:checked')].map(x=>Number(x.value)),courses=[...root.querySelectorAll('[data-preload-course]:checked')].map(x=>x.value);
   if(!members.length||!courses.length){error.textContent='请选择至少一个教学班和一位同学。';return;}
   button.disabled=true;error.textContent='';
   try{
    const plan=await send('management',{action:'preload-preview',members,courses});if(!active())return;
    compose.hidden=true;
    output.innerHTML=`<div class="preload-review-heading"><h3>核对加课范围</h3><p>${courses.length} 个教学班 · ${members.length} 位同学</p></div><div class="preload-selected-courses">${available.filter(c=>courses.includes(c.key)).map(c=>`<p><strong>${esc(c.name)}</strong><span>${esc(c.teacher)} · 教学班 ${esc(c.courseId)}</span><small>${esc(courseTimeSummary(c))}</small></p>`).join('')}</div><div class="preload-plan">${plan.plans.map(x=>`<p><strong>${esc(x.name)}</strong><span>${x.skipped?'未处理：'+esc(x.skipped):'新增 '+x.added+' 门'+(x.kept?'，保留 '+x.kept+' 门已有安排':'')}</span></p>`).join('')}</div><p class="field-help">只补充以上同学缺少的课程，不会覆盖已有安排。</p><div class="workflow-actions"><button class="secondary-button" id="back-preload">返回修改</button><button class="primary-button" id="save-preload">确认加课</button></div>`;
    $('#back-preload').onclick=()=>{compose.hidden=false;output.replaceChildren();error.textContent='';};
    $('#save-preload').onclick=async event=>{const save=event.currentTarget;save.disabled=true;root.setAttribute('aria-busy','true');try{await send('management',{action:'preload-save',members,courses,token:plan.token});if(!active())return;output.innerHTML='<div class="flow-empty"><h3>课程已添加</h3><p>同学登录后即可查看，其他个人课程仍可自行补充。</p><button class="primary-button" data-close>完成</button></div>';error.textContent='';try{await manager();render();}catch{error.textContent='课程已添加，管理列表稍后刷新。';}}catch(err){if(active()){error.textContent=err.message;save.textContent='重新核对范围';save.onclick=()=>{compose.hidden=false;output.replaceChildren();$('#preview-preload').click();};}}finally{root.removeAttribute('aria-busy');save.disabled=false;}};
   }catch(err){if(active())error.textContent=err.message;}finally{button.disabled=false;}
  };
 }
 function representatives(key){const c=management?.courses.find(x=>x.key===key);if(!c)return;
  showDialog(`<div class="management-detail">${dialogTop('课代表')}<h2 id="dialog-title">${esc(c.name)}</h2><p class="panel-subtitle">${esc(c.teacher)} · 教学班 ${esc(c.courseId)}。仅本教学班同学可担任课代表。</p><div class="representative-current">${c.representatives.map(r=>`<p><strong>${esc(r.name)}</strong><button class="secondary-button compact-button" data-remove-rep="${r.id}">移除身份</button></p>`).join('')||'<p class="panel-subtitle">暂未设置课代表。</p>'}</div><label class="search-box"><input id="rep-search" type="search" placeholder="搜索要设置的同学" aria-label="搜索课代表"></label><div id="rep-results" class="member-picker member-scroll"></div><p class="panel-error" role="alert"></p></div>`);
  const change=async(action,member)=>{try{await send('management',{action,key,member});await manager();representatives(key);render();}catch(err){$('.panel-error').textContent=err.message;}};
  document.querySelectorAll('[data-remove-rep]').forEach(el=>el.onclick=()=>change('representative-remove',Number(el.dataset.removeRep)));
  $('#rep-search').oninput=e=>{const q=e.target.value.trim();$('#rep-results').innerHTML=q?management.members.filter(m=>(m.name+' '+m.student).includes(q)&&!c.representatives.some(r=>r.id===m.id)).slice(0,20).map(m=>`<button class="member-result" data-add-rep="${m.id}"><span><strong>${esc(m.name)}</strong><small>${esc(m.student)}</small></span><span>设置课代表</span></button>`).join(''):'';document.querySelectorAll('[data-add-rep]').forEach(el=>el.onclick=()=>change('representative-add',Number(el.dataset.addRep)));};
 }
 document.addEventListener('click',async e=>{const el=e.target.closest('button,a');if(!el||el.disabled)return;
  if(el.hasAttribute('data-library')){e.preventDefault();openLibrary();}
  else if(el.dataset.subscribe)subscription(el.dataset.subscribe);
  else if(el.hasAttribute('data-management')){e.preventDefault();if($('#detail-dialog').open)$('#detail-dialog').close();await openManagement();}
  else if(el.hasAttribute('data-management-refresh')){try{await manager();problem='';}catch(err){problem=err.message;}render();}
  else if(el.hasAttribute('data-publish'))publish();
  else if(el.hasAttribute('data-preload'))preload();
  else if(el.dataset.representatives)representatives(el.dataset.representatives);
 });
 document.addEventListener('input',event=>{if(event.target.id!=='management-search')return;managementQuery=event.target.value;const rows=[...document.querySelectorAll('[data-managed-search]')];rows.forEach(row=>row.hidden=!row.dataset.managedSearch.includes(managementQuery.trim().toLocaleLowerCase()));const empty=$('.management-no-match');if(empty)empty.hidden=rows.some(row=>!row.hidden);});
 let syncing=false;
 async function syncManagement(){
  if(syncing||document.hidden||document.body.dataset.route!=='manage'||$('#detail-dialog').open||!currentUser||document.activeElement?.matches('input,textarea'))return;
  syncing=true;
  try{const before=JSON.stringify(management);await manager();problem='';if(document.body.dataset.route==='manage'&&!$('#detail-dialog').open&&before!==JSON.stringify(management))render();}catch(err){problem=err.message;}finally{syncing=false;}
 }
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)syncManagement();});
 window.addEventListener('focus',syncManagement);
 setInterval(syncManagement,60000);
 return {refresh,page,manager,libraryEntry,canManage,clear(){library={courses:[],base:''};management=null;problem='';managementQuery='';}};
}
