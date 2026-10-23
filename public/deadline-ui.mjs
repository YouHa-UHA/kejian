import {escapeHTML as esc,chinaClock,addDays} from './schedule.mjs';
const chevron='<svg class="hw-picker-chevron" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m6 9 6 6 6-6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';
export function deadlineFields(t){return `<div class="hw-deadline"><div class="hw-course-field"><div id="hw-deadline-label">截止日期 <span>选填</span></div><input type="hidden" name="dueDate" value="${esc(t?.dueDate||'')}"><details class="hw-picker hw-form-picker hw-date-picker"><summary aria-labelledby="hw-deadline-label hw-date-value"><span id="hw-date-value">${esc(t?.dueDate||'日期待定')}</span>${chevron}</summary><div class="hw-picker-panel"><div class="hw-calendar"></div><div class="hw-date-quick"><button type="button" data-date-shortcut="today">今天</button><button type="button" data-date-shortcut="tomorrow">明天</button><button type="button" data-date-shortcut="clear">日期待定</button></div></div></details></div><div class="hw-time-field"><div id="hw-time-label">具体时间 <span>选填</span></div><input type="hidden" name="dueTime" value="${esc(t?.dueTime||'')}"><div class="hw-time-control" role="group" aria-labelledby="hw-time-label"><input name="dueHour" aria-label="截止小时" aria-describedby="hw-time-help hw-time-error" type="text" inputmode="numeric" autocomplete="off" maxlength="2" placeholder="时" ${t?.dueDate?'':'disabled'} value="${esc(t?.dueTime?.split(':')[0]||'')}"><span aria-hidden="true">:</span><input name="dueMinute" aria-label="截止分钟" aria-describedby="hw-time-help hw-time-error" type="text" inputmode="numeric" autocomplete="off" maxlength="2" placeholder="分" ${t?.dueDate?'':'disabled'} value="${esc(t?.dueTime?.split(':')[1]||'')}"><button type="button" data-time-clear aria-label="清除截止时间" ${t?.dueDate?'':'disabled'}>清除</button></div><small id="hw-time-help">${t?.dueDate?'24 小时制 · 留空表示待定':'先选择截止日期'}</small><p id="hw-time-error" class="field-error" role="alert"></p></div></div><p class="hw-muted">北京时间；时刻待定不会自动设为 23:59。</p>`;}
export function mountDeadline(form){
 const picker=form.querySelector('.hw-date-picker'),calendar=picker.querySelector('.hw-calendar'),field=form.elements.dueDate;
 let month=(field.value||chinaClock().date).slice(0,7);
 function paint(){const [y,m]=month.split('-').map(Number),first=new Date(Date.UTC(y,m-1,1)),offset=(first.getUTCDay()+6)%7,count=new Date(Date.UTC(y,m,0)).getUTCDate();
  calendar.innerHTML=`<div class="hw-calendar-month"><button type="button" data-month="-1" aria-label="上个月">‹</button><strong aria-live="polite">${y} 年 ${m} 月</strong><button type="button" data-month="1" aria-label="下个月">›</button></div><div class="hw-calendar-grid">${['一','二','三','四','五','六','日'].map(d=>`<small>${d}</small>`).join('')}${'<span></span>'.repeat(offset)}${Array.from({length:count},(_,i)=>{const date=month+'-'+String(i+1).padStart(2,'0');return `<button type="button" data-date="${date}" aria-label="${date}" aria-pressed="${date===field.value}" ${date===chinaClock().date?'aria-current="date"':''}>${i+1}</button>`;}).join('')}</div>`;
 }
 function select(value){field.value=value;if(value)month=value.slice(0,7);form.querySelector('#hw-date-value').textContent=value||'日期待定';for(const name of ['dueHour','dueMinute']){form.elements[name].disabled=!value;if(!value){form.elements[name].value='';form.elements[name].removeAttribute('aria-invalid');}}form.querySelector('[data-time-clear]').disabled=!value;if(!value)form.elements.dueTime.value='';form.querySelector('#hw-time-help').textContent=value?'24 小时制 · 留空表示待定':'先选择截止日期';form.querySelector('#hw-time-error').textContent='';picker.open=false;picker.querySelector('summary').focus();paint();}
 picker.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;if(b.dataset.month){const [y,m]=month.split('-').map(Number);month=new Date(Date.UTC(y,m-1+Number(b.dataset.month),1)).toISOString().slice(0,7);paint();calendar.querySelector(`[data-month="${b.dataset.month}"]`).focus();}else if(b.dataset.date)select(b.dataset.date);else if(b.dataset.dateShortcut)select(b.dataset.dateShortcut==='clear'?'':addDays(chinaClock().date,b.dataset.dateShortcut==='tomorrow'?1:0));});
 picker.addEventListener('keydown',e=>{if(!e.target.dataset.date)return;const delta={ArrowLeft:-1,ArrowRight:1,ArrowUp:-7,ArrowDown:7}[e.key];if(delta){e.preventDefault();const date=addDays(e.target.dataset.date,delta);month=date.slice(0,7);paint();calendar.querySelector(`[data-date="${date}"]`)?.focus();}});
 const hour=form.elements.dueHour,minute=form.elements.dueMinute,error=form.querySelector('#hw-time-error');
 function update(final=false){
  const result=parseDeadlineTime(hour.value,minute.value);
  error.textContent=result.error;hour.setAttribute('aria-invalid',String(!!result.error));minute.setAttribute('aria-invalid',String(!!result.error));
  form.elements.dueTime.value=result.value||'';
  if(final&&!result.error&&result.value){[hour.value,minute.value]=result.value.split(':');}
  return result;
 }
 for(const input of [hour,minute]){
  input.addEventListener('input',e=>{if(!e.isComposing)update();});
  input.addEventListener('compositionend',()=>update());
  // Do not fill the next field while focus is entering it: it may already have
  // placed the caret, turning an intended minute value into e.g. "0059".
  input.addEventListener('blur',()=>{const result=update();if(!result.error&&result.value)input.value=result.value.split(':')[input===hour?0:1];});
  input.addEventListener('keydown',e=>{if(!['ArrowUp','ArrowDown'].includes(e.key))return;e.preventDefault();const max=input===hour?23:59,n=Number(input.value||0);if(!Number.isInteger(n))return;input.value=String((n+(e.key==='ArrowUp'?1:max))%(max+1)).padStart(2,'0');update();});
 }
 form.querySelector('[data-time-clear]').addEventListener('click',()=>{hour.value='';minute.value='';update();hour.focus();});
 form.validateDeadline=()=>{const result=update(true);if(result.error){(hour.value&&!/^\d{1,2}$/.test(hour.value)||Number(hour.value)>23||!hour.value?hour:minute).focus();return result.error;}return '';};
 paint();
}

export function parseDeadlineTime(hour,minute){
 const h=String(hour).normalize('NFKC').trim(),m=String(minute).normalize('NFKC').trim();
 if(!h&&!m)return {value:'',error:''};
 if(!/^\d{1,2}$/.test(h)||Number(h)>23)return {value:'',error:'小时请输入 0–23 之间的数字。'};
 if(m&&(!/^\d{1,2}$/.test(m)||Number(m)>59))return {value:'',error:'分钟请输入 0–59 之间的数字。'};
 return {value:h.padStart(2,'0')+':'+(m||'0').padStart(2,'0'),error:''};
}
