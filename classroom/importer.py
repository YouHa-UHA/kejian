"""Validate AI transport JSON and atomically save normalized course rows."""
import json, hashlib, re
from datetime import date, timedelta
START = date(2026,9,14)
END = date(2027,1,17)
SLOTS = {'2-5':('08:50','12:25'),'6-9':('13:25','17:00'),'11-14':('18:00','21:15')}
def fingerprint(data):
    return hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def parse(text, current):
    if not isinstance(text,str) or len(text)>60000: raise ValueError('请粘贴完整课表文本（最多六万字）')
    try:
        body=text.split('【课表开始】',1)[1].split('【课表结束】',1)[0].strip()
        obj=json.loads(body)
    except (IndexError,ValueError): raise ValueError('格式无法识别，请完整复制从【课表开始】到【课表结束】的内容')
    if not isinstance(obj,dict):raise ValueError('课表必须是JSON对象')
    term=obj.get('学期','')
    if not isinstance(term,str) or not 1<=len(term)<=60:raise ValueError('请填写学期名称')
    try:
        start=date.fromisoformat(obj.get('开学日期','2026-09-14'))
        end=date.fromisoformat(obj.get('结束日期','2027-01-17'))
    except (ValueError,TypeError):raise ValueError('学期日期无效')
    if start.weekday()!=0 or not 7<=(end-start).days<=370:raise ValueError('开学日期须为第一教学周周一，学期范围须在8至371天内')
    if term!='2026-2027秋冬' and ('开学日期' not in obj or '结束日期' not in obj):raise ValueError('其他学期请同时填写开学日期与结束日期，不能套用旧校历')
    max_week=(end-start).days//7+1
    rows=obj.get('课程')
    if not isinstance(rows,list) or not 1<=len(rows)<=30: raise ValueError('课程数量须为1至30门')
    courses=[]; events=[]; warnings=[]; ids=set(); seen=set()
    for i,c in enumerate(rows):
        if not isinstance(c,dict): raise ValueError('课程必须是对象')
        def val(k,required=False):
            v=c.get(k,'')
            if not isinstance(v,str) or len(v)>3000 or (required and not v.strip()): raise ValueError(f'第{i+1}门课程的{k}无效')
            return v.strip()
        name=val('名称',True); cid=val('教学班') or 'import-'+hashlib.sha256(name.encode()).hexdigest()[:12]
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',cid):raise ValueError(name+'：教学班编号只允许字母、数字、下划线和短横线')
        if cid in ids: raise ValueError('同一教学班重复，请合并为一门课程')
        ids.add(cid); teacher=val('老师'); loc=val('地点'); remark=val('原始备注'); pending=val('待确认')
        courses.append(dict(id=cid,name=name,teacher=teacher,location=loc,raw_remark=remark,delivery_mode='classroom',note=pending))
        if pending: warnings.append(name+'：'+pending)
        arrangements=c.get('安排',[])
        if not isinstance(arrangements,list) or len(arrangements)>100: raise ValueError(name+'：安排格式无效')
        if not arrangements: warnings.append(name+'：没有确定的日期，暂不显示在周课表')
        for a in arrangements:
            if not isinstance(a,dict): raise ValueError(name+'：安排格式无效')
            days=a.get('日期',[]); weeks=a.get('教学周',[])
            if not isinstance(days,list) or not isinstance(weeks,list) or len(days)+len(weeks)>100: raise ValueError(name+'：日期或教学周格式无效')
            if days and weeks: raise ValueError(name+'：同一安排不能同时填写日期和教学周')
            if weeks:
                wd=a.get('星期')
                if type(wd)!=int or not 1<=wd<=7 or any(type(w)!=int or not 1<=w<=max_week for w in weeks): raise ValueError(name+'：教学周或星期无效')
                days=[(start+timedelta(days=(w-1)*7+wd-1)).isoformat() for w in weeks]
            if not days: raise ValueError(name+'：安排缺少日期或教学周')
            kind=a.get('类型','教室'); periods=a.get('节次','')
            if not isinstance(kind,str) or not isinstance(periods,str) or kind not in ('教室','线上','实践') or periods not in ('',*SLOTS): raise ValueError(name+'：类型或节次无法识别，请用待确认说明')
            t1,t2=SLOTS.get(periods,(None,None)) if kind!='实践' else (None,None)
            if a.get('开始时间') or a.get('结束时间'):
                t1=a.get('开始时间');t2=a.get('结束时间') or None
                if kind=='实践' or periods or not isinstance(t1,str) or not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d',t1) or (t2 is not None and (not isinstance(t2,str) or not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d',t2) or t2<=t1)):
                    raise ValueError(name+'：明确钟点无效；不能与节次混用')
            place='' if kind=='实践' else a.get('地点',loc)
            if not isinstance(place,str) or len(place)>3000:raise ValueError(name+'：地点无效')
            if not t1: warnings.append(name+'：存在时间待确认的安排')
            for ds in days:
                try: dt=date.fromisoformat(ds)
                except (ValueError,TypeError): raise ValueError(name+'：日期须为YYYY-MM-DD')
                if dt.isoformat()!=ds:raise ValueError(name+'：日期须为YYYY-MM-DD')
                if not start<=dt<=end: raise ValueError(name+'：日期超出本学期')
                key=(cid,ds,(t1 or periods or kind))
                if key in seen: raise ValueError(name+'：存在重复安排 '+ds)
                seen.add(key)
                events.append(dict(id='-'.join(key),course_id=cid,course_name=name,teacher=teacher,date=ds,kind='fieldwork' if kind=='实践' else 'online' if kind=='线上' else 'class',status='details_pending' if kind=='实践' or not t1 else 'scheduled',start_time=t1,end_time=t2,location=place,note='实践时间地点待通知' if kind=='实践' else '',meeting_number=0,periods=periods,teaching_week=(dt-start).days//7+1,nominal_time=None,timezone='Asia/Shanghai'))
    for c in courses:
        meetings=[e for e in events if e['course_id']==c['id']]
        if meetings and all(e['kind']=='online' for e in meetings):c['delivery_mode']='online'
    events.sort(key=lambda e:(e['date'],e['start_time'] or '',e['id']))
    for c in courses:
        for n,e in enumerate([e for e in events if e['course_id']==c['id']],1): e['meeting_number']=n
    for i,e in enumerate(events):
        for other in events[:i]:
            if e['date']==other['date'] and e['start_time'] and e['end_time'] and other['start_time'] and other['end_time'] and e['start_time']<other['end_time'] and other['start_time']<e['end_time']: warnings.append(e['date']+'：'+e['course_name']+'与'+other['course_name']+'时间重叠')
    result={**current,'term':term,'week_start':start.isoformat(),'display_range':{'start':start.isoformat(),'end':end.isoformat()},'courses':courses,'events':events,'version':'text-import-v2'}
    return result,list(dict.fromkeys(warnings))
def diff_courses(before,after):
    old={c['id']:c for c in before['courses']};new={c['id']:c for c in after['courses']}
    result=[]
    def meetings(data,cid,fields):
        return sorted([tuple(str(e.get(k) or '') for k in fields) for e in data['events'] if e['course_id']==cid])
    for cid,c in new.items():
        fields=[]
        if cid in old:
            if old[cid].get('recurrence')!=c.get('recurrence'):fields.append('周期安排')
            for k,label in [('name','课程名'),('teacher','老师'),('location','教室'),('raw_remark','备注'),('note','待确认信息')]:
                if (old[cid].get(k) or '')!=(c.get(k) or ''):fields.append(label)
            if meetings(before,cid,('date',))!=meetings(after,cid,('date',)):
                fields.append('上课日期或次数')
            else:
                for keys,label in [(('date','start_time','end_time'),'上课时间'),(('date','location'),'上课地点'),(('date','kind'),'课程类型'),(('date','status'),'安排状态')]:
                    if meetings(before,cid,keys)!=meetings(after,cid,keys):
                        if label=='安排状态':
                            old_events={(e['date'],e.get('kind')):e for e in before['events'] if e['course_id']==cid}
                            corrections=[e['date'] for e in after['events'] if e['course_id']==cid and e.get('status')=='details_pending' and old_events.get((e['date'],e.get('kind')),{}).get('status')=='scheduled']
                            if corrections:label='安排状态：'+ '、'.join(corrections)+' 已安排 → 详情待定'
                        fields.append(label)
        result.append(dict(id=cid,name=c['name'],kind='新增' if cid not in old else '修改' if fields else '未变化',fields=fields))
    result.extend(dict(id=cid,name=c['name'],kind='移除',fields=[]) for cid,c in old.items() if cid not in new)
    return result
