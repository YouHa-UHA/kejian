import {confirmAction} from './confirm-ui.mjs';
import {currentUser,checkSession,showAuth,openAccount,openSharing,request} from './account.mjs';
import {mountAiConnections} from './ai-ui.mjs';
import {openCourseImport} from './import-ui.mjs';
import {createCommunity} from './community-ui.mjs';
import {openInstall} from './install.mjs';
import {createHomework} from './homework-ui.mjs';
import {ROUTES, routeFromHash, replaceRoute, watchViewport} from './browser.mjs';
import {chinaClock, addDays, daysBetween, weekday, monday, weekNumber as baseWeekNumber, dateLabel, eventState, nextEvent, weekEvents, expandEvents, campusVisits, nextCampusVisit, eventPeriod, escapeHTML as esc, WEEKDAYS} from './schedule.mjs';
const weekNumber=day=>baseWeekNumber(day,data?.week_start||'2026-09-14');
const $=selector=>document.querySelector(selector);
const icons={arrow:'<path d="M5 12h14m-6-6 6 6-6 6"/>',right:'<path d="m9 5 7 7-7 7"/>',left:'<path d="m15 5-7 7 7 7"/>',close:'<path d="m6 6 12 12M6 18 18 6"/>',pin:'<path d="M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 1 1 14 0Z"/><circle cx="12" cy="10" r="2.2"/>',clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',video:'<rect x="3" y="5" width="14" height="14" rx="3"/><path d="m17 10 4-3v10l-4-3"/>',calendar:'<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M7 3v4m10-4v4M3 10h18"/>',check:'<path d="m5 12 4 4L19 6"/>',search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',leaf:'<path d="M20 3C10 2 3 7 5 14c3 7 15 5 15-11ZM4 21 15 10"/>'};
const icon=(name)=>`<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name]||icons.calendar}</svg>`;
const themes={
 'theme-english':['#456797','#e9effb','英','英语'],
 'theme-intro':['#52657f','#e9eef6','导','管理导论'], 'theme-math':['#506c97','#e8eef8','数','管理数学'],
 'theme-economics':['#927041','#f3ecdf','经','工程经济'], 'theme-systems':['#796893','#ede8f5','系','系统工程'],
 'theme-theory':['#966956','#f4e9e3','理','现代化理论'], 'theme-hr':['#646c7b','#e9edf2','人','人力资源'],
};
let emptyImportShown=false;
let data, fixedEvents=[], clock=chinaClock(), modalCourse=null;
let preferredView='grid';try{if(localStorage.getItem('kejian.week-view')==='list')preferredView='list';}catch{}
const state={route:'today',week:monday(clock.date),day:null,query:'',view:preferredView};
let firstWeek='2026-09-14',lastWeek='2027-01-11';
const gridTitles={'theme-english':['英语'],'theme-intro':['管理','导论'],'theme-math':['管理','数学'],'theme-economics':['工程','经济'],'theme-systems':['系统','工程'],'theme-theory':['现代化','理论'],'theme-hr':['人力','资源']};
const courseNames={'研究生英语应用能力提升':'theme-english','人力资源管理':'theme-hr','工程管理导论':'theme-intro','中国式现代化的理论与实践':'theme-theory','工程经济学':'theme-economics','工程管理数学':'theme-math','系统工程':'theme-systems'};
const coursePalette=[['#496f9e','#e7effb'],['#98723f','#f5eddd'],['#79649c','#eee8f7'],['#4e8274','#e5f2ed'],['#a46d79','#f7e8ed'],['#588994','#e4f1f4'],['#9b775e','#f3e9e1'],['#747b46','#eef1df']];
const theme=id=>{
 const course=data?.courses.find(c=>c.id===id);
 if(themes[id])return themes[id];
 const name=course?.name||'待命名课程';
 if(courseNames[name])return themes[courseNames[name]];
 const names=[...new Set((data?.courses||[]).filter(c=>!themes[c.id]).map(c=>c.name))].sort();
 const colors=coursePalette[Math.max(0,names.indexOf(name))%coursePalette.length];
 return [...colors,name.slice(0,1),name];
};
const style=id=>`--course-color:${theme(id)[0]};--course-soft:${theme(id)[1]}`;
const courseById=id=>data.courses.find(c=>c.id===id);
const courseEvents=id=>data.events.filter(e=>e.course_id===id);
const smallDate=iso=>iso.split('-').slice(1).map(Number).join('.');
const timeText=e=>e.start_time?e.end_time?`${e.start_time}–${e.end_time}`:`${e.start_time} 开始 · 结束待定`:(e.kind==='fieldwork'?'实践时间待通知':'上课时间待通知');
const placeText=e=>e.kind==='online'?'线上授课':e.location||'实践地点待通知';
const gridPlace=e=>{
 if(e.kind==='online')return '<span>线上</span>';
 if(!e.location)return '<span>地点</span><span>待定</span>';
 const parts=e.location.match(/^(.*?)(\d+)$/);
 return parts?`<span class="grid-building">${esc(parts[1])}</span><span class="grid-room">${esc(parts[2])}</span>`:esc(e.location);
};
const sequence=e=>e.recurring?'每周二 · 按周安排':`第${e.meeting_number}次课`;
const rangeText=v=>v.start===v.end?dateLabel(v.start):`${dateLabel(v.start)} — ${dateLabel(v.end)}`;
const relative=e=>{const status=eventState(e,clock),diff=daysBetween(clock.date,e.date);if(status==='live')return '正在上课';if(status==='started_unknown_end')return '已到开课时间';if(diff===0)return e.kind==='fieldwork'?'今日实践':'今天';return diff===1?'明天':`${diff}天后`;};
function nav(){
 state.route=routeFromHash(location.hash);
 document.querySelectorAll('[data-route]').forEach(a=>{a.classList.toggle('active',a.dataset.route===state.route);if(a.dataset.route===state.route)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
 const more=$('.bottom-nav [data-more]');more.classList.toggle('active',['ai','manage'].includes(state.route));
 document.body.dataset.route=state.route;
 document.title=`${{today:'今天',week:'周课表',courses:'课程',homework:'作业',ai:'连接 AI',manage:'课程管理'}[state.route]} · 课间`;
}
function goRoute(route,top=true){
 if(!replaceRoute(route))return;
 render();if(top)window.scrollTo({top:0,behavior:'instant'});
}
function goWeek(day,filter=false){const changed=state.route!=='week';state.week=monday(day);state.day=filter?day:null;goRoute('week',changed);}
const standalone=()=>window.matchMedia('(display-mode: standalone)').matches||window.navigator.standalone===true;

function hero(e){
 if(!e)return `<section class="finished-panel">${icon('check')}<h2>暂无后续安排</h2><p>可在「课程」中查看已排课程。</p><a class="text-link" href="#courses">查看全部课程 ${icon('arrow')}</a></section>`;
 const status=eventState(e,clock),online=e.kind==='online';
 return `<button class="next-card" data-event="${e.id}" aria-label="查看${esc(e.course_name)}，${dateLabel(e.date)}，${timeText(e)}，${esc(placeText(e))}">
 <span class="next-top"><span class="eyebrow light">${status==='live'?'正在进行':status==='started_unknown_end'?'今日课程':'下一节课'}</span><span class="next-badge">${relative(e)}</span></span>
 <span class="next-name">${esc(e.course_name)}</span><span class="next-date">${dateLabel(e.date)}<span>周${WEEKDAYS[weekday(e.date)]}</span><span>${online?'线上':sequence(e)}</span></span>
 <span class="next-divider"></span><span class="next-facts"><span><span class="fact-label">${icon('clock')} 上课时间</span><strong class="hero-time">${e.start_time||'时间待定'}<small>${e.end_time?'— '+e.end_time:online?'结束时间待定':'实践调研'}</small></strong></span><span><span class="fact-label">${icon(online?'video':'pin')} ${online?'授课方式':e.kind==='fieldwork'?'实践地点':'上课教室'}</span><strong class="hero-place">${online?'线上授课':esc(e.location||'待通知')}</strong></span></span>
 <span class="next-bottom"><span>${esc(e.teacher||'教师待通知')}${online?' · 入口待通知':e.kind==='fieldwork'?' · 不在教室授课':''}</span><span class="round-arrow">${icon('arrow')}</span></span></button>`;
}
function campusCard(){
 const visit=nextCampusVisit(data.events,clock);if(!visit)return '';
 const current=clock.date>=visit.start&&clock.date<=visit.end;
 return `<button class="campus-card" data-campus="${visit.week}"><span class="campus-icon">${icon('pin')}</span><span><small>${current?'本次到校':'下次到校'}</small><strong>${rangeText(visit)}</strong><span>${visit.dates.length} 个到校日 · ${visit.events.length} 次教室课</span></span>${icon('right')}</button>`;
}
function row(e,options={}){
 const status=eventState(e,clock);
 return `<button class="lesson-row ${status==='past'?'is-past':''} ${options.compact?'compact':''}" style="${style(e.course_id)}" data-event="${e.id}"><span class="lesson-time"><strong>${e.start_time||'待定'}</strong><small>${e.end_time||(e.kind==='online'?'结束待定':'实践')}</small></span><span class="lesson-line"></span><span class="lesson-info"><span class="lesson-title">${esc(e.course_name)}</span><span class="lesson-meta">${esc(placeText(e))}<span>·</span>${esc(e.teacher)}</span><span class="lesson-extra">${sequence(e)}${e.kind==='fieldwork'?' · 不在教室授课':''}${status==='started_unknown_end'?' · 已到开课时间':''}</span></span><span class="lesson-tail">${status==='live'?'<span class="live-label">上课中</span>':status==='past'?icon('check'):icon('right')}</span></button>`;
}
function home(){
 const todayEvents=data.events.filter(e=>e.date===clock.date),upcoming=nextEvent(data.events,clock),remaining=todayEvents.filter(e=>eventState(e,clock)!=='past');
 const week=monday(clock.date),events=weekEvents(data.events,week),n=weekNumber(clock.date),days=[...new Set(events.map(e=>e.date))];
 return `<section class="page-intro"><div class="date-eyebrow"><span>${dateLabel(clock.date)}<span class="dot-sep">·</span>星期${WEEKDAYS[weekday(clock.date)]}</span><span>${n>0&&clock.date<=data.display_range.end?`第 ${n} 教学周`:esc(data.term)}</span></div><h1>${todayEvents.length?(remaining.length?`今天 ${todayEvents.length} 次课`:'今日课程已结束'):'今天没有课'}</h1></section>
 <div class="home-layout"><div class="home-primary">${hero(upcoming)}${campusCard()}${homework.home()}${todayEvents.length>1?`<section class="today-agenda"><div class="section-heading"><h2>今日安排</h2><span>${todayEvents.length} 次课</span></div>${todayEvents.map(e=>row(e,{compact:true})).join('')}</section>`:''}</div>
 <div class="home-secondary"><section class="week-preview"><div class="section-heading"><h2>本周安排<small>${events.length} 次课</small></h2><a href="#week" data-current-week class="text-link">查看 ${icon('arrow')}</a></div><div class="week-date-range">${dateLabel(week)} — ${dateLabel(addDays(week,6))}</div>
 ${days.length?`<div class="weekend-tiles" style="--tile-count:${Math.min(days.length,4)}">${days.map(d=>{const items=events.filter(e=>e.date===d);return `<button class="day-tile ${d===clock.date?'today-tile':''}" data-day="${d}"><span>周${WEEKDAYS[weekday(d)]}</span><strong>${Number(d.slice(-2))}</strong><span class="tile-dots">${items.map(e=>`<i style="background:${theme(e.course_id)[0]}"></i>`).join('')}</span><small>${items.every(e=>e.kind==='online')?'线上':items.length+' 次课'}</small></button>`;}).join('')}</div>`:`<div class="no-week"><p>本周没有已排课程</p></div>`}</section>
 ${standalone()?'':'<button class="install-entry" data-install>添加到手机主屏幕</button>'}</div></div>`;
}
function dayStrip(events,days){return `<div class="day-strip" aria-label="选择日期">${days.map(d=>{const items=events.filter(e=>e.date===d);return `<button class="strip-day ${state.day===d?'selected':''} ${d===clock.date?'is-today':''}" data-filter-day="${d}" aria-pressed="${state.day===d}" aria-label="${dateLabel(d)}，星期${WEEKDAYS[weekday(d)]}，${items.length}次课"><span>${d===clock.date?'今':WEEKDAYS[weekday(d)]}</span><strong>${Number(d.slice(-2))}</strong><span class="strip-dots">${items.map(e=>`<i style="--dot-color:${theme(e.course_id)[0]}"></i>`).join('')}</span></button>`;}).join('')}</div>`;}
function agenda(events){
 const dates=[...new Set(events.map(e=>e.date))];
 return dates.length?`<div class="agenda">${dates.map(d=>`<section class="agenda-group" aria-label="${dateLabel(d)}"><div class="agenda-date"><span>${smallDate(d)}</span><h2>星期${WEEKDAYS[weekday(d)]}</h2>${d===clock.date?'<span class="today-badge">今天</span>':''}<small>${events.filter(e=>e.date===d).length} 次课</small></div><div class="agenda-lessons">${events.filter(e=>e.date===d).map(e=>row(e)).join('')}</div></section>`).join('')}</div>`:`<div class="empty-state"><h2>${state.day?'当天没有课':'本周没有已排课程'}</h2></div>`;
}
const classPeriods={morning:{label:'上午',start:'08:50',end:'12:25'},afternoon:{label:'下午',start:'13:25',end:'17:00'},evening:{label:'晚上',start:'18:00',end:'21:15'}};
function gridLesson(e){
 const period=classPeriods[eventPeriod(e)],customTime=e.kind==='class'&&period&&(e.start_time!==period.start||e.end_time!==period.end);
 const timing=e.kind==='online'?'时间以当次通知为准':timeText(e);
 const exception=customTime?`<span class="grid-exception" aria-label="本次上课时间">${esc(e.start_time)}<span>${esc(e.end_time||'结束待定')}</span></span>`:e.kind==='fieldwork'?'<span class="grid-exception">实践</span>':'';
 return `<button class="grid-lesson ${eventState(e,clock)==='past'?'past':''}" style="${style(e.course_id)}" data-event="${e.id}" aria-label="${dateLabel(e.date)} ${esc(e.course_name)} ${esc(e.teacher)} ${timing} ${esc(placeText(e))}"><strong>${(gridTitles[e.course_id]||gridTitles[courseNames[e.course_name]]||[e.course_name||theme(e.course_id)[3]]).map(t=>`<span class="${t.length>2?'long-title':''}">${esc(t)}</span>`).join('')}</strong><span class="grid-teacher">${esc(e.teacher)}</span>${exception}<span class="grid-place">${gridPlace(e)}</span></button>`;
}
function timetable(events,days){
 const periods=Object.entries(classPeriods);if(events.some(e=>eventPeriod(e)==='pending'))periods.push(['pending',{label:'待定'}]);
 let html=`<div class="timetable" role="group" aria-label="七天课表，左侧钟点仅适用于线下课"><div class="grid-corner"><span>线下</span><span>时段</span></div>`;
 html+=days.map(d=>`<div class="grid-heading"><button data-filter-day="${d}" class="grid-date ${state.day===d?'selected':''} ${d===clock.date?'is-today':''}" aria-pressed="${state.day===d}" aria-label="${dateLabel(d)}，星期${WEEKDAYS[weekday(d)]}，${events.filter(e=>e.date===d).length}次课"><span>周${WEEKDAYS[weekday(d)]}</span><strong>${Number(d.slice(-2))}</strong>${d===clock.date?'<i aria-hidden="true"></i>':''}</button>${homework.dayBadge(d)}</div>`).join('');
 for(const [period,slot] of periods){
  html+=`<div class="grid-period" aria-label="${slot.label}${slot.start?`，线下课 ${slot.start} 至 ${slot.end}`:'，时间待通知'}"><span class="grid-period-label">${slot.label}</span>${slot.start?`<span class="grid-period-time"><time>${slot.start}</time><span class="period-range" aria-hidden="true"></span><time>${slot.end}</time></span>`:''}</div>`;
  html+=days.map(d=>`<div class="grid-cell ${state.day===d?'selected-day':''}">${events.filter(e=>e.date===d&&eventPeriod(e)===period).map(gridLesson).join('')}</div>`).join('');
 }
 return html+'</div>';
}
function weekView(){
 const events=weekEvents(data.events,state.week),days=Array.from({length:7},(_,i)=>addDays(state.week,i)),visible=state.day?events.filter(e=>e.date===state.day):events;
 const nextVisit=campusVisits(data.events).find(v=>v.week>state.week),campus=events.filter(e=>e.kind==='class'),online=events.filter(e=>e.kind==='online'),practice=events.filter(e=>e.kind==='fieldwork');
 const status=campus.length?'本周到校':online.length?'本周仅线上课':practice.length?'本周有实践安排':'本周暂无安排';
 return `<section class="page-intro week-intro"><h1>周课表</h1><div class="view-switch" role="group" aria-label="课表显示方式"><button data-view="grid" aria-pressed="${state.view==='grid'}">课表</button><button data-view="list" aria-pressed="${state.view==='list'}">列表</button></div></section>
 <section class="week-toolbar" aria-label="切换教学周"><div><strong>${dateLabel(state.week)} — ${dateLabel(addDays(state.week,6))}</strong><span>${state.week.slice(0,4)} · 第 ${weekNumber(state.week)} 教学周<span class="week-status">${status}</span></span></div><div class="week-controls"><button class="icon-button" data-week-step="-1" aria-label="上一周" ${state.week<=firstWeek?'disabled':''}>${icon('left')}</button><button class="plain-button" data-this-week aria-label="回到本周">本周</button><button class="icon-button" data-week-step="1" aria-label="下一周" ${state.week>=lastWeek?'disabled':''}>${icon('right')}</button></div></section>
 ${nextVisit?`<button class="campus-shortcut" data-campus="${nextVisit.week}"><span>${campus.length?'下个到校周':'下次到校'} <strong>${smallDate(nextVisit.start)} — ${smallDate(nextVisit.end)}</strong></span>${icon('arrow')}</button>`:''}
 ${state.view==='grid'?timetable(events,days):dayStrip(events,days)}
 <div class="week-list-label"><span>${state.day?`周${WEEKDAYS[weekday(state.day)]}的安排`:'整周安排'}<b>${visible.length} 次课</b></span>${state.day?'<button class="filter-pill" data-all-week>显示整周</button>':''}</div>
 ${state.view==='list'||state.day?agenda(visible):''}
 ${online.length?'<p class="recurrence-caption">线上课程时间以当次通知为准</p>':''}
 <button class="semester-jump" data-semester>${icon('calendar')}<span>查看学期到校安排</span>${icon('right')}</button>`;
}
function courseListHTML(query=''){
 if(!data.courses.length)return '<div class="search-empty"><h2>还没有课程</h2><p>点击上方“导入课表”，添加自己的课程。</p></div>';

 const ordered=[...data.courses].sort((a,b)=>{const ea=nextEvent(courseEvents(a.id),clock),eb=nextEvent(courseEvents(b.id),clock);return (ea?ea.date+(ea.start_time||'00:00'):'9999').localeCompare(eb?eb.date+(eb.start_time||'00:00'):'9999');});
 const found=ordered.filter(c=>[c.name,c.teacher,c.location||''].join(' ').toLowerCase().includes(query.trim().toLowerCase()));
 return found.length?found.map(c=>{const events=courseEvents(c.id),next=nextEvent(events,clock),past=events.filter(e=>eventState(e,clock)==='past').length;return `<button class="course-item" style="${style(c.id)}" data-course="${c.id}"><span class="course-monogram">${esc(theme(c.id)[2])}</span><span class="course-body"><span class="course-item-title">${esc(c.name)}</span><span class="course-item-meta">${esc(c.teacher)}<span>·</span>${esc(c.location||(c.delivery_mode==='online'?'线上课程':'地点待通知'))}</span><span class="course-next">${next?`下次 ${dateLabel(next.date)} · ${next.kind==='fieldwork'?'实践调研':(next.start_time||'时间待通知')}`:(c.note?esc(c.note):'暂无后续安排')}</span></span><span class="course-item-tail">${icon('right')}<small>${c.recurrence?'每周二':`${past} / ${events.length}`}</small></span></button>`;}).join(''):'<div class="search-empty"><h2>没有找到这门课</h2><p>试试课程名称、老师姓名或教室。</p></div>';
}
function coursesView(){const completed=fixedEvents.filter(e=>eventState(e,clock)==='past').length;
 return `<section class="page-intro courses-intro"><h1>我的课程</h1><p>${esc(data.term)}<span class="dot-sep">·</span>${data.courses.length} 门课程</p><div class="course-page-actions"><button class="primary-button" data-import>导入课表</button><button class="course-install-button" data-sharing>课表共享</button><button class="course-install-button course-desktop-install" data-install>添加到手机主屏幕</button></div></section><div class="courses-layout"><section class="course-main"><label class="search-box">${icon('search')}<input id="course-search" type="search" placeholder="搜索课程、老师或教室" aria-label="搜索课程、老师或教室" value="${esc(state.query)}" autocomplete="off"></label><div id="course-list" class="course-list">${courseListHTML(state.query)}</div></section><div class="course-sidebar">${community.libraryEntry()}<aside class="semester-summary"><div class="eyebrow">线下课程进度</div><div class="summary-numbers"><strong>${completed}<span>/ ${fixedEvents.length}</span></strong><p>已结束的教室课与实践安排</p></div><div class="progress-track" role="progressbar" aria-label="线下课程进度" aria-valuemin="0" aria-valuemax="${fixedEvents.length}" aria-valuenow="${completed}"><i style="width:${(fixedEvents.length?completed/fixedEvents.length*100:0)}%"></i></div><p class="summary-note">${fixedEvents.filter(e=>e.kind==='class').length} 次教室课 · ${fixedEvents.filter(e=>e.kind==='fieldwork').length} 次实践调研</p></aside></div></div>`;
}
function render(){
 if(!data)return;clock=chinaClock();nav();
 if(state.route==='ai'){
  // Clock and visibility updates must not reset a connection form or its download guidance.
  if($('#main #ai-connection-panel')?.dataset.owner===String(currentUser?.id))return;
  $('#main').innerHTML='<div class="ai-page" id="ai-connection-panel"></div>';
  mountAiConnections({container:$('#ai-connection-panel'),request,getUser:()=>currentUser,showDialog,dialogTop});return;
 }
 $('#main').innerHTML=state.route==='today'?home():state.route==='week'?weekView():state.route==='homework'?homework.page():state.route==='manage'?community.page():coursesView();
}
let editorScroll=null;
function releaseEditorScroll(){if(editorScroll===null)return;const y=editorScroll;editorScroll=null;document.body.classList.remove('homework-editor-open');document.body.style.removeProperty('--editor-page-top');window.scrollTo(0,y);}
function showDialog(content,{kind=''}={}){releaseEditorScroll();const editor=kind==='homework-editor';$('#detail-dialog').classList.toggle('homework-editor',editor);$('#detail-dialog').classList.toggle('ai-connection-dialog',kind==='ai-connection');if(editor){editorScroll=window.scrollY;document.body.style.setProperty('--editor-page-top',`${-editorScroll}px`);document.body.classList.add('homework-editor-open');}$('#dialog-body').innerHTML=content;const form=$('#hw-form');if(form)form.dataset.original=JSON.stringify([...new FormData(form)]);if(!$('#detail-dialog').open)$('#detail-dialog').showModal();document.body.classList.add('dialog-open');$('#detail-dialog').scrollTop=0;}
async function requestDialogClose(){
 const d=$('#detail-dialog'),form=d.querySelector('#hw-form'),comment=d.querySelector('.hw-comment-form textarea'),importText=d.querySelector('#import-text');
 if(form?.getAttribute('aria-busy')==='true'||d.querySelector('.hw-comment-form[aria-busy="true"]'))return;
 const dirty=form?JSON.stringify([...new FormData(form)])!==form.dataset.original:!!comment?.value.trim()||!!importText?.value.trim();
 if(!dirty){d.close();return;}
 const body=d.querySelector('#dialog-body').firstElementChild;
 if(await confirmAction({title:'放弃未保存的内容？',message:comment?'这条留言还没有发表。离开后，内容不会保留。':'本次修改还没有保存。你可以继续编辑，或放弃这次修改。',confirm:'放弃修改',cancel:'继续编辑',danger:true})){
  if(d.open&&body===d.querySelector('#dialog-body').firstElementChild)d.close();
 }
}
const dialogTop=label=>`<div class="dialog-top"><span class="eyebrow">${label}</span><button class="icon-button" data-close aria-label="关闭详情">${icon('close')}</button></div>`;
function openCourse(id,eventId=null){
 const c=courseById(id);if(!c)return;modalCourse=id;
 const events=courseEvents(id),selected=events.find(e=>e.id===eventId)||nextEvent(events,clock)||events.at(-1);
 showDialog(`<div class="course-detail" style="${style(id)}">${dialogTop('课程详情')}<div class="detail-heading"><span class="course-monogram">${esc(theme(id)[2])}</span><h2 id="dialog-title">${esc(c.name)}</h2><p>${esc(c.teacher||'教师待通知')}${Number.isFinite(c.credits)?`<span>·</span>${c.credits} 学分`:''}${c.recurrence?'<span class="online-tag">线上课</span>':''}</p></div>
 ${selected?`<section class="selected-lesson ${selected.kind==='fieldwork'?'practice-panel':''}"><div class="selected-top"><span>${dateLabel(selected.date,true)} · 周${WEEKDAYS[weekday(selected.date)]}</span><small>${selected.recurring?'每周安排':sequence(selected)}</small></div><strong class="${!selected.end_time?'pending-time':''}">${timeText(selected)}</strong><p>${icon(selected.kind==='online'?'video':selected.kind==='fieldwork'?'leaf':'pin')}${esc(placeText(selected))}</p>${selected.kind==='fieldwork'?'<span class="practice-explanation">不在教室授课。具体实践时间和地点待通知。</span>':''}${selected.kind==='online'?'<span class="practice-explanation">具体时间以当次通知为准；上课入口待通知。</span>':''}</section>`:''}
 ${c.recurrence?`<section class="recurrence-note"><strong>每周${WEEKDAYS[c.recurrence.weekday-1]} ${esc(c.recurrence.start_time||'时间待定')}</strong><p>从 ${dateLabel(c.recurrence.starts_on,true)} 开始。结束日期未定，本学期内暂按每周规则展示。</p></section>`:''}
 ${homework.courseSection(id)}<section class="meeting-section"><div class="section-heading"><h3>${c.recurrence?'按周展示的日期':'全部上课日期'}</h3><span>${c.recurrence?'结束日期待定':events.length+' 次安排'}</span></div><div class="meeting-grid">${events.map(e=>`<button class="meeting-date ${selected?.id===e.id?'chosen':''} ${eventState(e,clock)==='past'?'past':''}" data-meeting="${e.id}" aria-pressed="${selected?.id===e.id}"><span><strong>${smallDate(e.date)}</strong><small>${e.date.slice(0,4)} · 周${WEEKDAYS[weekday(e.date)]}</small></span><span class="meeting-label">${e.kind==='fieldwork'?icon('leaf')+'实践':eventState(e,clock)==='past'?icon('check'):(e.start_time||'待通知')}</span></button>`).join('')}</div></section>
 <details class="source-note"><summary>查看课程原始备注<span>来自「我的课程」</span></summary><p>${esc(c.raw_remark)}</p>${c.recurrence?`<p>${esc(c.recurrence.source)}</p>`:''}</details><p class="detail-footnote">${c.recurrence?'课程时间以你补充的安排为准。':'日期采用课程备注，钟点按非全日制校历校正。'}</p><div class="course-remove-actions"><button class="course-remove-button" id="remove-personal-course">移出我的课表</button><small>仅影响自己的课表，个人作业保留。</small><p class="panel-error" role="alert"></p></div></div>`);
 $('#remove-personal-course').onclick=()=>removePersonalCourse(c);
}
async function removePersonalCourse(course){
 const owner=currentUser?.id,button=$('#remove-personal-course'),error=button?.parentElement.querySelector('.panel-error');
 if(!button||!owner)return;
 button.disabled=true;error.textContent='';
 try{
  const inspected=await request('timetable-import',{owner,action:'inspect'});
  if(!button.isConnected||currentUser?.id!==owner)return;
  const accepted=await confirmAction({title:`移出「${course.name}」？`,message:'这门课的全部上课安排将从你的课表移除，对应课程作业不再显示。个人作业保留，其他同学不受影响。移出后可以撤销。',confirm:'移出课表',danger:true});
  if(!accepted||!button.isConnected||currentUser?.id!==owner)return;
  button.textContent='正在移出…';
  const result=await request('timetable-import',{owner,action:'remove',courseId:course.id,base:inspected.base});
  if(currentUser?.id!==owner)return;
  showDialog(`<div class="course-remove-result">${dialogTop('课程')}<h2 id="dialog-title">已移出课表</h2><p>「${esc(course.name)}」已移出，个人作业仍保留。</p><p class="course-restore-note">误操作可立即撤销，也可在导入课表中恢复上一版。再次修改课表后，上一版会更新。</p><p class="panel-error" role="alert"></p><div class="course-remove-result-actions"><button class="secondary-button" id="undo-course-remove">撤销移除</button><button class="primary-button" data-close>完成</button></div></div>`);
  const undo=$('#undo-course-remove'),status=undo.closest('.course-remove-result').querySelector('.panel-error');
  undo.onclick=async()=>{
   undo.disabled=true;status.textContent='';
   try{
    await request('timetable-import',{owner,action:'restore',base:result.nextBase});
    $('#detail-dialog').close();
    try{await load();}catch{showDialog(`<div class="course-remove-result">${dialogTop('课程')}<h2 id="dialog-title">已恢复课程</h2><p>课程已恢复，页面暂未刷新，请稍后刷新查看。</p><button class="primary-button" data-close>完成</button></div>`);}
   }catch(err){if(status.isConnected)status.textContent=err.message;undo.disabled=false;}
  };
  try{await load();}catch{if(status.isConnected)status.textContent='课程已移出，页面暂未刷新，请稍后刷新查看。';}
 }catch(err){if(error.isConnected)error.textContent=err.message;}
 finally{if(button.isConnected){button.disabled=false;button.textContent='移出我的课表';}}
}
function openMore(){
 showDialog(`<div class="account-detail more-detail">${dialogTop('导航')}<h2 id="dialog-title">更多</h2><div class="account-settings-list"><button class="account-setting-row" data-connect-ai><span><strong>连接 AI</strong><small>让常用助手帮你查课、处理作业</small></span><span aria-hidden="true">›</span></button>${community.canManage()?'<button class="account-setting-row" data-management><span><strong>课程管理</strong><small>维护你负责的教学班</small></span><span aria-hidden="true">›</span></button>':''}<button class="account-setting-row" data-install><span><strong>添加到手机主屏幕</strong><small>从桌面直接打开课间</small></span><span aria-hidden="true">›</span></button></div></div>`);
}
function openSemester(){if(!data)return;modalCourse=null;const visits=campusVisits(data.events);showDialog(`<div class="semester-detail">${dialogTop('学期总览')}<h2 id="dialog-title">到校安排</h2><p class="semester-subtitle">${esc(data.term)} · ${visits.length} 次集中到校</p><div class="semester-week-list">${visits.map((v,i)=>`<button data-semester-week="${v.week}"><span class="week-index">${String(i+1).padStart(2,'0')}</span><span><strong>${rangeText(v)}</strong><small>第 ${weekNumber(v.week)} 教学周 · ${v.events.length} 次教室课${v.start.startsWith('2027')?' · 2027年':''}</small></span>${icon('right')}</button>`).join('')}</div><p class="semester-note">只统计在教室上课的日期；实践调研另见周课表。</p></div>`);}
async function copyInstallLink(){
 const status=$('.copy-status');
 try{await navigator.clipboard.writeText(new URL('./',location.href).href);status.textContent='链接已复制';}
 catch{status.textContent='请长按下方链接复制';}
}
document.addEventListener('click',e=>{
 const target=e.target.closest('button,a');if(!target||target.disabled)return;
 if(target.tagName==='A'&&(e.button!==0||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey))return;
 const route=target.getAttribute('href')?.slice(1);
 if(target.tagName==='A'&&target.getAttribute('href')?.startsWith('#')&&ROUTES.includes(route)){
  e.preventDefault();if(target.hasAttribute('data-current-week')){state.week=monday(clock.date);state.day=null;}
  $('#detail-dialog').close();goRoute(route);return;
 }
 if(target.classList.contains('skip-link')){e.preventDefault();$('#main').focus();$('#main').scrollIntoView();return;}
 if(target.hasAttribute('data-more')){e.preventDefault();openMore();return;}
 if(target.hasAttribute('data-sharing')){openSharing({showDialog,dialogTop});return;}
 if(target.hasAttribute('data-account')){openAccount({showDialog,dialogTop});return;}
 if(target.hasAttribute('data-connect-ai')){$('#detail-dialog').close();goRoute('ai');return;}
 if(target.hasAttribute('data-import')){openCourseImport({getData:()=>data,showDialog,dialogTop,reload:load});return;}
 if(target.hasAttribute('data-install')){openInstall({showDialog,dialogTop});return;}
 if(target.hasAttribute('data-copy-link')){copyInstallLink();return;}

 if(target.dataset.event){const event=data.events.find(x=>x.id===target.dataset.event);if(event)openCourse(event.course_id,event.id);}
 else if(target.dataset.course)openCourse(target.dataset.course);
 else if(target.dataset.meeting)openCourse(modalCourse,target.dataset.meeting);
 else if(target.hasAttribute('data-close'))requestDialogClose();
 else if(target.hasAttribute('data-semester')||target.id==='semester-button')openSemester();
 else if(target.dataset.view){state.view=target.dataset.view;try{localStorage.setItem('kejian.week-view',state.view);}catch{}render();$(`[data-view="${state.view}"]`)?.focus({preventScroll:true});}
 else if(target.dataset.campus)goWeek(target.dataset.campus);
 else if(target.dataset.day)goWeek(target.dataset.day,true);
 else if(target.hasAttribute('data-this-week')){state.week=monday(clock.date);state.day=null;render();}
 else if(target.dataset.weekStep){const week=addDays(state.week,Number(target.dataset.weekStep)*7);if(week>=firstWeek&&week<=lastWeek){state.week=week;state.day=null;render();}}
 else if(target.dataset.filterDay){state.day=state.day===target.dataset.filterDay?null:target.dataset.filterDay;render();}
 else if(target.hasAttribute('data-all-week')){state.day=null;render();}
 else if(target.dataset.semesterWeek){$('#detail-dialog').close();goWeek(target.dataset.semesterWeek);}
});
document.addEventListener('input',e=>{if(e.target.id==='course-search'){state.query=e.target.value;$('#course-list').innerHTML=courseListHTML(state.query);}});
$('#detail-dialog').addEventListener('cancel',e=>{e.preventDefault();const picker=$('#detail-dialog .hw-picker[open]');if(picker){picker.open=false;picker.querySelector('summary').focus();return;}requestDialogClose();});
$('#detail-dialog').addEventListener('close',()=>{document.body.classList.remove('dialog-open');$('#detail-dialog').classList.remove('homework-editor','ai-connection-dialog');releaseEditorScroll();});
$('#detail-dialog').addEventListener('click',e=>{if(e.target===$('#detail-dialog')){const r=e.target.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)requestDialogClose();}});
window.addEventListener('hashchange',()=>{render();window.scrollTo({top:0,behavior:'instant'});});
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&!$('#detail-dialog').open)render();});
setInterval(()=>{const current=chinaClock();if((current.date!==clock.date||current.time!==clock.time)&&!$('#detail-dialog').open&&document.activeElement?.tagName!=='INPUT')render();},30000);
const homework=createHomework({courses:()=>data?.courses||[],owner:()=>data?.owner,render,showDialog,dialogTop,goRoute});
const community=createCommunity({getData:()=>data,showDialog,dialogTop,reload:load,goRoute,render});
let loadSerial=0;
async function load(){const serial=++loadSerial;try{
 const user=await checkSession();if(serial!==loadSerial)return;
 if(!user){data=null;homework.clear();showAuth();return;}
 const res=await fetch('./api/schedule',{cache:'no-store',credentials:'same-origin'});
 if(res.status===401){data=null;homework.clear();showAuth();return;}
 if(!res.ok)throw Error('课表暂时无法加载');const source=await res.json();if(serial!==loadSerial)return;
 if(source.owner!==user.id||!Array.isArray(source.courses)||!Array.isArray(source.events))throw Error('课表格式不正确');
 document.body.classList.remove('signed-out');document.querySelector('.bottom-nav').hidden=false;
 document.querySelector('[data-management]').hidden=!community.canManage();
 $('#account-button').textContent=user.name.slice(-2);$('#account-button').setAttribute('aria-label',user.name+'，账号设置');$('#account-button').title=user.name;
 const shortTerm=source.term.match(/(20\d{2}).*(秋冬|春夏)/);$('#semester-button').querySelector('.semester-label').textContent=shortTerm?shortTerm[1]+' '+shortTerm[2]:source.term;$('#semester-button').title=source.term;
 fixedEvents=source.events.filter(e=>e.kind!=='online');data={...source,events:expandEvents(source)};
 firstWeek=monday(source.display_range.start);lastWeek=monday(source.display_range.end);state.week=monday(clock.date);state.day=null;state.query='';
 await Promise.all([homework.refresh(),community.refresh()]);if(serial!==loadSerial)return;
 if(routeFromHash(location.hash)==='manage'&&community.canManage())await community.manager();
 render();
 if(!source.courses.length&&state.route!=='ai'){goRoute('courses');return;}
 const params=new URLSearchParams(location.search);const event=data.events.find(e=>e.id===params.get('event'));const day=params.get('day');
 if(event)openCourse(event.course_id,event.id);else if(day&&/^\d{4}-\d{2}-\d{2}$/.test(day)&&day>=source.display_range.start&&day<=source.display_range.end)goWeek(day,true);
 }catch(e){if(serial!==loadSerial)return;$('#main').innerHTML='<div class="empty-state error-state"><h1>暂时没能加载</h1><p>请检查连接后再试一次。</p><button class="primary-button" id="retry-load">重新加载</button></div>';$('#retry-load').onclick=load;}}
function clearPersonal(){loadSerial++;data=null;fixedEvents=[];modalCourse=null;state.query='';state.day=null;homework.clear();community.clear();$('#detail-dialog').close();$('#dialog-body').replaceChildren();document.querySelector('#hw-toast').hidden=true;showAuth();}
document.addEventListener('kejian-signed-out',clearPersonal);
document.addEventListener('kejian-signed-in',load);
window.addEventListener('pageshow',()=>{if(data)checkIdentity();});
async function checkIdentity(){document.body.classList.add('checking-identity');try{const user=await checkSession();if(data&&user?.id!==data.owner){clearPersonal();if(user)await load();}}catch{clearPersonal();const note=document.querySelector('.account-error');if(note)note.textContent='连接暂时不可用，请恢复网络后登录。';}finally{document.body.classList.remove('checking-identity');}}
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&data)checkIdentity();});
watchViewport();
load();

