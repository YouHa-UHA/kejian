"""Server-side timetable queries in the school's timezone."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

ZONE='Asia/Shanghai'


def day(value=None):
    if value is None:return datetime.now(ZoneInfo(ZONE)).date()
    if not isinstance(value,str):raise ValueError('日期须为YYYY-MM-DD')
    try:
        result=date.fromisoformat(value)
        if result.isoformat()!=value:raise ValueError()
        return result
    except ValueError:raise ValueError('日期须为有效的YYYY-MM-DD')


def query(data, value=None, weekly=False):
    target=day(value)
    start=target-timedelta(days=target.weekday()) if weekly else target
    try:end=start+timedelta(days=6) if weekly else start
    except OverflowError:raise ValueError('日期超出支持范围')
    courses={c['id']:c for c in data['courses']}
    events=[dict(e) for e in data['events'] if start.isoformat()<=e['date']<=end.isoformat()]
    for course in courses.values():
        rule=course.get('recurrence')
        if not rule:continue
        first=day(rule['starts_on'])
        lower=max(start,day(data['display_range']['start']),first)
        upper=min(end,day(data['display_range']['end']),day(rule['until']) if rule['until'] else end)
        if lower>upper:continue
        offset=max(0,(lower-first).days)
        try:occurrence=first+timedelta(days=((offset+6)//7)*7)
        except OverflowError:continue
        while occurrence<=upper:
            stamp=occurrence.isoformat()
            if stamp not in rule.get('excluded_dates',[]):
                events.append({'id':course['id']+'-'+stamp,'course_id':course['id'],'course_name':course['name'],
                    'teacher':course.get('teacher',''),'date':stamp,'kind':'online','status':'recurring',
                    'start_time':rule['start_time'],'end_time':rule['end_time'],'location':None,
                    'recurring':True,'provisional':not bool(rule['until']),'note':course.get('note','')})
            if (upper-occurrence).days<7:break
            occurrence+=timedelta(days=7)
    for event in events:
        course=courses.get(event['course_id'],{})
        event['course_name']=event.get('course_name') or course.get('name','')
        event['teacher']=event.get('teacher') or course.get('teacher','')
        event['timezone']=ZONE
        event['teaching_week']=(day(event['date'])-day(data['week_start'])).days//7+1
        event['timePending']=not bool(event.get('start_time'))
        event['endPending']=not bool(event.get('end_time'))
    events.sort(key=lambda e:(e['date'],e.get('start_time') or '00:00',e['id']))
    return {'timezone':ZONE,'term':data['term'],'start':start.isoformat(),'end':end.isoformat(),
            'teachingWeek':(start-day(data['week_start'])).days//7+1,'events':events,
            'withinTerm':not (end<day(data['display_range']['start']) or start>day(data['display_range']['end']))}
