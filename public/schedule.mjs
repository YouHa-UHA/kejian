export const ZONE = 'Asia/Shanghai';
export const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日'];
export function chinaClock(now = new Date()) {
  const parts = new Intl.DateTimeFormat('en-GB', {timeZone: ZONE, year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', hourCycle:'h23'}).formatToParts(now);
  const p = Object.fromEntries(parts.map(x => [x.type, x.value]));
  return {date:`${p.year}-${p.month}-${p.day}`, time:`${p.hour}:${p.minute}`};
}
export function addDays(iso, amount) { const d = new Date(iso + 'T12:00:00Z'); d.setUTCDate(d.getUTCDate() + amount); return d.toISOString().slice(0,10); }
export function daysBetween(a,b) { return Math.round((Date.parse(b+'T12:00:00Z') - Date.parse(a+'T12:00:00Z'))/86400000); }
export function weekday(iso) { return (new Date(iso+'T12:00:00Z').getUTCDay()+6)%7; }
export function monday(iso) { return addDays(iso, -weekday(iso)); }
export function weekNumber(iso, start='2026-09-14') { return Math.floor(daysBetween(start, iso)/7)+1; }
export function dateLabel(iso, year=false) { const [y,m,d] = iso.split('-').map(Number); return `${year ? y+'年' : ''}${m}月${d}日`; }
export function eventState(event, clock) {
  if (event.date < clock.date) return 'past';
  if (event.date > clock.date) return 'future';
  if (!event.start_time) return 'pending';
  if (event.end_time && clock.time >= event.end_time) return 'past';
  if (!event.end_time && clock.time >= event.start_time) return 'started_unknown_end';
  return clock.time >= event.start_time ? 'live' : 'today';
}
export function nextEvent(events, clock) { return events.find(e => eventState(e,clock) !== 'past') || null; }
export function weekEvents(events, start) { const end = addDays(start,6); return events.filter(e => e.date >= start && e.date <= end); }
// An open-ended rule is expanded only inside the displayed semester. Its end
// remains unknown; these occurrences are not confirmed total lesson counts.
export function expandEvents(schedule) {
  const events = [...schedule.events], range = schedule.display_range;
  for (const c of schedule.courses) {
    const rule = c.recurrence;
    if (!rule || !range) continue;
    const end = rule.until && rule.until < range.end ? rule.until : range.end;
    for (let date = rule.starts_on; date <= end; date = addDays(date,7)) {
      if (date < range.start || rule.excluded_dates?.includes(date)) continue;
      events.push({id:`${c.id}-${date}`, course_id:c.id, course_name:c.name,
        teacher:c.teacher, date, weekday:rule.weekday, teaching_week:weekNumber(date),
        meeting_number:null, kind:'online', status:'recurring', start_time:rule.start_time,
        end_time:rule.end_time, location:null, timezone:ZONE, recurring:true,
        provisional:!rule.until, date_source:'user_weekly_rule', time_source:'user_confirmation',
        note:c.note});
    }
  }
  return events.sort((a,b)=>(a.date+(a.start_time||'00:00')).localeCompare(b.date+(b.start_time||'00:00')));
}
export function campusVisits(events) {
  const groups = new Map();
  for (const e of events.filter(e=>e.kind==='class')) {
    const week = monday(e.date);
    if (!groups.has(week)) groups.set(week,[]);
    groups.get(week).push(e);
  }
  return [...groups.entries()].sort(([a],[b])=>a.localeCompare(b)).map(([week,items])=>{
    const dates=[...new Set(items.map(e=>e.date))].sort();
    return {week,start:dates[0],end:dates.at(-1),dates,events:items};
  });
}
export function nextCampusVisit(events, clock) {
  return campusVisits(events).find(v=>v.events.some(e=>eventState(e,clock)!=='past')) || null;
}
export function eventPeriod(e) {
  if (!e.start_time) return 'pending';
  return e.start_time<'12:30'?'morning':e.start_time<'18:00'?'afternoon':'evening';
}
export function escapeHTML(value) { return String(value ?? '').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

// Use actual times only. A fieldwork session's nominal classroom slot does not
// establish when its activity takes place.
export function classTimeLabel(session) {
  if (!session.start_time) return session.kind === 'fieldwork' ? '实践时间待通知' : '上课时间待通知';
  const period = session.start_time < '12:30' ? '上午' : session.start_time < '18:00' ? '下午' : '晚上';
  return `${period} ${session.start_time}${session.end_time ? '–'+session.end_time : ' · 结束待定'}`;
}
export function courseTimeSummary(course) {
  const lines = (course.sessions || []).map(s => `周${WEEKDAYS[weekday(s.date)]}${classTimeLabel(s)}`);
  if (course.recurrence) {
    const r = course.recurrence;
    lines.unshift(`每周${WEEKDAYS[r.weekday-1]}${classTimeLabel(r)}`);
  }
  return [...new Set(lines)].join('；') || '上课时间待通知';
}
