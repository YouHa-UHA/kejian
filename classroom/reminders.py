"""Opt-in reminders from current personal schedules and exact teaching classes."""
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import hashlib
import json
import secrets
import time
import uuid
from urllib.parse import urlencode
from . import course_store,agent_schedule

ZONE=ZoneInfo('Asia/Shanghai')
DEFAULTS={'course':True,'newHomework':True,'homeworkDue':True,'courseMinutes':30,'homeworkHours':24}
KINDS={'course':'course','homework-new':'newHomework','homework-due':'homeworkDue'}


def schema(c):
    c.execute('''CREATE TABLE IF NOT EXISTS push_device_preferences(
        device TEXT PRIMARY KEY REFERENCES push_devices(id) ON DELETE CASCADE, enabled INTEGER NOT NULL DEFAULT 0,
        since INTEGER NOT NULL DEFAULT 0, epoch TEXT NOT NULL DEFAULT '')''')
    c.execute('''CREATE TABLE IF NOT EXISTS push_preferences(
        member INTEGER PRIMARY KEY REFERENCES members(id), settings TEXT NOT NULL,
        revision TEXT NOT NULL, course_since INTEGER NOT NULL,
        published_since INTEGER NOT NULL, deadline_since INTEGER NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS push_reminders(
        id TEXT PRIMARY KEY, member INTEGER NOT NULL REFERENCES members(id),
        kind TEXT NOT NULL, source_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
        due INTEGER NOT NULL, expires INTEGER NOT NULL, payload TEXT NOT NULL,
        created INTEGER NOT NULL, UNIQUE(member,kind,source_key,fingerprint))''')
    c.execute('CREATE INDEX IF NOT EXISTS push_reminders_member_due ON push_reminders(member,due)')
    c.execute('CREATE INDEX IF NOT EXISTS push_reminders_expires ON push_reminders(expires)')
    c.execute('CREATE INDEX IF NOT EXISTS push_jobs_reminder ON push_jobs(reminder_id)')
    # Older test releases duplicated notification text here for a history view.
    # Delivery now derives content from the current course/homework instead.
    c.execute("UPDATE push_reminders SET payload='{}' WHERE payload<>'{}'")


def preferences(c,member):
    row=c.execute('SELECT * FROM push_preferences WHERE member=?',(member,)).fetchone()
    return {'settings':json.loads(row['settings']) if row else dict(DEFAULTS),'revision':row['revision'] if row else None}


def ensure_preferences(c,member,now):
    c.execute('INSERT OR IGNORE INTO push_preferences VALUES(?,?,?,?,?,?)',
              (member,json.dumps(DEFAULTS),str(uuid.uuid4()),now,now,now))


def save_preferences(c,member,b,now=None):
    now=int(time.time()) if now is None else now
    settings=b.get('settings')
    if not isinstance(settings,dict) or set(settings)!=set(DEFAULTS):raise ValueError('提醒设置格式不正确')
    if any(type(settings[k]) is not bool for k in ('course','newHomework','homeworkDue')):
        raise ValueError('请确认要开启的提醒')
    if type(settings['courseMinutes']) is not int or settings['courseMinutes'] not in (15,30,60):raise ValueError('课前提醒支持提前15、30或60分钟')
    if type(settings['homeworkHours']) is not int or settings['homeworkHours'] not in (2,24):raise ValueError('作业提醒支持提前2小时或1天')
    old=preferences(c,member)
    if old['revision']!=b.get('expected'):raise ValueError('提醒设置已更新，请重新查看后再修改')
    ensure_preferences(c,member,now)
    row=c.execute('SELECT * FROM push_preferences WHERE member=?',(member,)).fetchone()
    fields=[('course_since','course','courseMinutes'),('published_since','newHomework',None),('deadline_since','homeworkDue','homeworkHours')]
    since=[now if settings[key]!=old['settings'][key] or (offset and settings[offset]!=old['settings'][offset]) else row[column]
           for column,key,offset in fields]
    c.execute('UPDATE push_preferences SET settings=?,revision=?,course_since=?,published_since=?,deadline_since=? WHERE member=?',
              (json.dumps(settings),str(uuid.uuid4()),*since,member))
    return preferences(c,member)


def toggle_device(c,member,device,enabled,now=None):
    now=int(time.time()) if now is None else now
    if enabled:
        if device['label']!='iPhone / iPad':raise ValueError('本轮先开放 iPhone / iPad 的课程与作业提醒')
        if not device['active']:raise ValueError('请先连接这台设备的通知')
        ensure_preferences(c,member,now)
        before=c.execute('SELECT * FROM push_device_preferences WHERE device=?',(device['id'],)).fetchone()
        if not before or not before['enabled']:
            if not devices(c,member,now):
                c.execute('UPDATE push_preferences SET course_since=?,published_since=?,deadline_since=? WHERE member=?',(now,now,now,member))
            c.execute('''INSERT INTO push_device_preferences VALUES(?,1,?,?)
                ON CONFLICT(device) DO UPDATE SET enabled=1,since=excluded.since,epoch=excluded.epoch''',
                (device['id'],now,str(uuid.uuid4())))
    else:
        c.execute('UPDATE push_device_preferences SET enabled=0 WHERE device=?',(device['id'],))
        c.execute("UPDATE push_jobs SET state='cancelled',updated=? WHERE device=? AND reminder_id<>'' AND state IN ('scheduled','retry','sending')",(now,device['id']))


def devices(c,member,now):
    return c.execute('''SELECT d.*,p.since AS reminders_since,p.epoch AS reminders_epoch FROM push_devices d JOIN sessions s ON s.token_hash=d.session_hash AND s.member=d.member
        JOIN push_device_preferences p ON p.device=d.id AND p.enabled=1
        JOIN members m ON m.id=d.member WHERE d.member=? AND d.active=1
        AND d.label='iPhone / iPad' AND s.expires>? AND m.disabled=0''',(member,now)).fetchall()


def stamp(day,clock):
    try:return int(datetime.fromisoformat(day+'T'+clock).replace(tzinfo=ZONE).timestamp())
    except (TypeError,ValueError):return None


def utc_stamp(value):
    try:
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        return int(parsed.timestamp()) if parsed.tzinfo else None
    except (ValueError,TypeError,AttributeError):return None


def digest(*values):return hashlib.sha256(json.dumps(values,ensure_ascii=False).encode()).hexdigest()


def url(member,**params):
    return './?'+urlencode({'noticeOwner':member,**params})+('#homework' if 'homework' in params else '#today')


def course_candidates(c,member,settings,now):
    schedule=course_store.read_schedule(c,member)
    today=datetime.fromtimestamp(now,ZONE).date()
    for offset in range(3):
        for event in agent_schedule.query(schedule,(today+timedelta(days=offset)).isoformat())['events']:
            if not event.get('start_time') or event.get('status') in ('cancelled','canceled'):continue
            start=stamp(event['date'],event['start_time'])
            if start is None:continue
            due=start-settings['courseMinutes']*60
            place='线上授课' if event['kind']=='online' else event.get('location') or '地点待通知'
            title='课前提醒 · '+event['course_name']
            body=f"{event['date'][5:]} {event['start_time']} · {event.get('teacher') or '老师待通知'} · {place}"
            if event['kind']=='online':body+='；时间以当次通知为准'
            yield {'kind':'course','source_key':event['id'],
                   'fingerprint':digest(event['id'],event['date'],event['start_time'],settings['courseMinutes']),
                   'due':due,'expires':min(start,due+900),
                   'payload':{'title':title,'body':body,'url':url(member,event=event['id'])}}


def homework_candidates(c,member,settings,now):
    courses={r['id']:r['name'] for r in c.execute("SELECT id,name FROM course_courses WHERE member=? AND slot='current'",(member,))}
    personal=[{'id':r['id'],'title':r['title'],'date':r['dueDate'],'time':r['dueTime'],
               'complete':bool(r['completedAt']),'deleted':bool(r['deletedAt']),
               'course':courses.get(r['courseId'],'原课程'),'scope':'personal'} for r in c.execute('SELECT * FROM course_homework WHERE member=?',(member,))]
    shared=c.execute('''SELECT h.*,o.name AS course,o.teacher,o.id AS class_id,e.linked_at,s.completed_at
        FROM teaching_homework h JOIN teaching_enrollments e ON e.offering=h.offering AND e.member=? AND e.active=1
        JOIN teaching_offerings o ON o.key=h.offering AND o.published=1
        LEFT JOIN teaching_homework_status s ON s.homework=h.id AND s.member=e.member
        WHERE h.deleted_at='' ''',(member,)).fetchall()
    for row in shared:
        if settings['newHomework']:
            created=utc_stamp(row['created_at']);changed=utc_stamp(row['updated_at']);joined=utc_stamp(row['linked_at'])
            if changed is not None and (joined is None or changed>=joined):
                when=(row['due_date']+(' '+row['due_time'] if row['due_time'] else ' · 时间待定')) if row['due_date'] else '截止日期待定'
                yield {'kind':'homework-new','source_key':row['id'],'fingerprint':row['revision'],
                       'due':changed,'expires':changed+3600,
                       'payload':{'title':('新课程作业 · ' if created==changed else '课程作业更新 · ')+row['course'],
                                  'body':f"{row['title']} · {when} · {row['teacher'] or '老师待通知'} · 教学班 {row['class_id']}",
                                  'url':url(member,homework=row['id'])}}
        personal.append({'id':row['id'],'title':row['title'],'date':row['due_date'],'time':row['due_time'],
                         'complete':bool(row['completed_at']),'deleted':False,'course':row['course'],'scope':'course'})
    if not settings['homeworkDue']:return
    for task in personal:
        if task['complete'] or task['deleted'] or not task['date']:continue
        if task['time']:
            deadline=stamp(task['date'],task['time'])
            if deadline is None:continue
            due=deadline-settings['homeworkHours']*3600
            timing=f"{task['date']} {task['time']} 截止"
        else:
            try:previous=(datetime.fromisoformat(task['date']).date()-timedelta(days=1)).isoformat()
            except (ValueError,TypeError):continue
            due=stamp(previous,'12:00');deadline=stamp(task['date'],'00:00')
            if due is None or deadline is None:continue
            timing=task['date']+' 截止，具体时间待定'
        yield {'kind':'homework-due','source_key':task['scope']+':'+task['id'],
               'fingerprint':digest(task['date'],task['time'],settings['homeworkHours']),
               'due':due,'expires':min(deadline,due+3600),
               'payload':{'title':'作业截止提醒 · '+task['course'],
                          'body':task['title']+' · '+timing,
                          'url':url(member,homework=task['id'])}}


def candidates(c,member,now):
    row=c.execute('SELECT * FROM push_preferences WHERE member=?',(member,)).fetchone()
    if not row:return []
    settings=json.loads(row['settings']);items=[]
    if settings['course']:items.extend(course_candidates(c,member,settings,now))
    items.extend(homework_candidates(c,member,settings,now))
    since={'course':row['course_since'],'homework-new':row['published_since'],'homework-due':row['deadline_since']}
    return [v for v in items if settings[KINDS[v['kind']]] and since[v['kind']]<=v['due']<=now+2*86400 and v['expires']>now]


def resolve(c,ledger,now):
    if not ledger or ledger['expires']<=now:return None
    for item in candidates(c,ledger['member'],now):
        if all(item[k]==ledger[k] for k in ('kind','source_key','fingerprint','due')):
            value=item['payload']
            return {**value,'title':value['title'][:80],'body':value['body'][:220]}
    return None


def allowed(c,job,device,now):
    option=c.execute('SELECT * FROM push_device_preferences WHERE device=?',(device['id'],)).fetchone()
    if not option or not option['enabled'] or device['label']!='iPhone / iPad':return None
    ledger=c.execute('SELECT * FROM push_reminders WHERE id=? AND member=?',(job['reminder_id'],job['member'])).fetchone()
    if not ledger or ledger['due']>now or ledger['due']<option['since']:return None
    return resolve(c,ledger,now)


def _reconcile(c,member,now):
    # Compute from a WAL read snapshot; do not hold the writer lock while
    # expanding schedules or reading homework. Changes carry a fresh token.
    with course_store.transaction(c):
        marker=c.execute('SELECT version FROM push_changes WHERE member=?',(member,)).fetchone()
        if not marker:return False
        version=marker['version'];receivers=devices(c,member,now)
        items=candidates(c,member,now) if receivers else []
    with course_store.transaction(c,write=True):
        marker=c.execute('SELECT version FROM push_changes WHERE member=?',(member,)).fetchone()
        if not marker or marker['version']!=version:return False
        valid=set()
        for item in items:
            c.execute('INSERT OR IGNORE INTO push_reminders VALUES(?,?,?,?,?,?,?,?,?)',
                      (str(uuid.uuid4()),member,item['kind'],item['source_key'],item['fingerprint'],item['due'],item['expires'],'{}',now))
            ledger=c.execute('SELECT * FROM push_reminders WHERE member=? AND kind=? AND source_key=? AND fingerprint=?',
                             (member,item['kind'],item['source_key'],item['fingerprint'])).fetchone()
            valid.add(ledger['id'])
            for device in receivers:
                if ledger['due']<device['reminders_since']:continue
                key='reminder-'+digest(ledger['id'],device['id'],device['reminders_epoch'])
                c.execute("""INSERT OR IGNORE INTO push_jobs(id,member,device,request_key,due,expires,created,state,updated,receipt,reminder_id)
                    VALUES(?,?,?,?,?,?,?,'scheduled',?,?,?)""",
                    (str(uuid.uuid4()),member,device['id'],key,ledger['due'],ledger['expires'],now,now,secrets.token_urlsafe(32),ledger['id']))
        for job in c.execute("SELECT id,reminder_id FROM push_jobs WHERE member=? AND reminder_id<>'' AND state IN ('scheduled','retry','sending')",(member,)).fetchall():
            if job['reminder_id'] not in valid:c.execute("UPDATE push_jobs SET state='cancelled',updated=? WHERE id=?",(now,job['id']))
        c.execute('DELETE FROM push_changes WHERE member=? AND version=?',(member,version))
    return True


def plan_dirty(c,now=None,limit=5,budget_seconds=.05):
    now=int(time.time()) if now is None else now
    rows=c.execute('SELECT member FROM push_changes ORDER BY member LIMIT ?',(limit,)).fetchall()
    started=time.monotonic();processed=0
    for row in rows:
        if processed and time.monotonic()-started>=budget_seconds:break
        processed+=int(_reconcile(c,row['member'],now))
    return {'processed':processed,'remaining':bool(c.execute('SELECT 1 FROM push_changes LIMIT 1').fetchone())}


def plan(c,now=None):
    """Explicit full reconciliation for maintenance/tests, one member at a time."""
    from . import reminder_changes
    now=int(time.time()) if now is None else now
    reminder_changes.enqueue_active(c,now)
    for row in c.execute('SELECT member FROM push_changes ORDER BY member').fetchall():
        _reconcile(c,row['member'],now)


def overview(c,member,now=None):
    now=int(time.time()) if now is None else now
    upcoming=[]
    current={(r['kind'],r['source_key'],r['fingerprint'],r['due']):r['payload'] for r in candidates(c,member,now)}
    for row in c.execute('''SELECT r.* FROM push_reminders r WHERE r.member=? AND r.due>?
        AND EXISTS(SELECT 1 FROM push_jobs j WHERE j.reminder_id=r.id AND j.member=r.member
            AND j.state IN ('scheduled','retry','sending')) ORDER BY r.due''',(member,now)):
        payload=current.get((row['kind'],row['source_key'],row['fingerprint'],row['due']))
        if not payload:continue
        upcoming.append({'id':row['id'],'kind':row['kind'],'due':row['due'],'state':'pending',**payload})
        if len(upcoming)==3:break
    return {'owner':member,**preferences(c,member),'upcoming':upcoming}
