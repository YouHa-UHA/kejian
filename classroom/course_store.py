"""Relational course storage in the independent Kejian SQLite database.

The JSON HTTP/import format is a transport format only. No schedule/task blobs
are stored: each course, meeting and homework item has a separate row.
"""
from contextlib import contextmanager
from datetime import date
import re
import uuid

COURSE_FIELDS = {
    'id': 'TEXT', 'name': 'TEXT', 'teacher': 'TEXT', 'location': 'TEXT',
    'delivery_mode': 'TEXT', 'note': 'TEXT', 'raw_remark': 'TEXT', 'credits': 'REAL',
}
EVENT_FIELDS = {
    'id': 'TEXT', 'course_id': 'TEXT', 'course_name': 'TEXT', 'teacher': 'TEXT',
    'date': 'TEXT', 'kind': 'TEXT', 'status': 'TEXT', 'start_time': 'TEXT',
    'end_time': 'TEXT', 'location': 'TEXT', 'note': 'TEXT', 'meeting_number': 'INTEGER',
    'periods': 'TEXT', 'teaching_week': 'INTEGER', 'nominal_time': 'TEXT', 'timezone': 'TEXT',
}
TASK_FIELDS = ('id','title','courseId','notes','submission','dueDate','dueTime','createdAt',
               'updatedAt','completedAt','deletedAt','revision')
TABLES = ('course_schedules','course_courses','course_meetings','course_homework','course_migrations')


def schema(c):
    # Individual execute calls preserve the caller's migration transaction.
    c.execute('''CREATE TABLE IF NOT EXISTS course_schedules (
        member INTEGER NOT NULL REFERENCES members(id), slot TEXT NOT NULL CHECK(slot IN ('current','previous')),
        team INTEGER NOT NULL CHECK(team=1), term TEXT NOT NULL, version TEXT NOT NULL,
        week_start TEXT NOT NULL, range_start TEXT NOT NULL, range_end TEXT NOT NULL,
        PRIMARY KEY(member,slot))''')
    for table, fields in [('course_courses',COURSE_FIELDS),('course_meetings',EVENT_FIELDS)]:
        columns=','.join('"'+key+'" '+kind for key,kind in fields.items())
        extra=",FOREIGN KEY(member,slot,course_id) REFERENCES course_courses(member,slot,id) ON DELETE CASCADE" if table=='course_meetings' else ''
        c.execute(f'''CREATE TABLE IF NOT EXISTS {table} (
            member INTEGER NOT NULL, slot TEXT NOT NULL, position INTEGER NOT NULL,
            fields TEXT NOT NULL, {columns}, PRIMARY KEY(member,slot,id),
            FOREIGN KEY(member,slot) REFERENCES course_schedules(member,slot) ON DELETE CASCADE{extra})''')
    columns=','.join('"'+key+'" TEXT NOT NULL'+(" DEFAULT '' CHECK(length(submission)<=2000)" if key=='submission' else '') for key in TASK_FIELDS)
    c.execute(f'''CREATE TABLE IF NOT EXISTS course_homework (
        member INTEGER NOT NULL REFERENCES members(id), {columns}, PRIMARY KEY(member,id),
        CHECK(length(trim(title)) BETWEEN 1 AND 120), CHECK(length(notes)<=10000))''')
    if 'submission' not in {r[1] for r in c.execute('PRAGMA table_info(course_homework)')}:
        c.execute("ALTER TABLE course_homework ADD COLUMN submission TEXT NOT NULL DEFAULT '' CHECK(length(submission)<=2000)")
    c.execute('CREATE INDEX IF NOT EXISTS course_meetings_date ON course_meetings(member,slot,date)')
    c.execute('CREATE INDEX IF NOT EXISTS course_homework_due ON course_homework(member,deletedAt,completedAt,dueDate)')
    c.execute('''CREATE TABLE IF NOT EXISTS course_migrations (
        id TEXT PRIMARY KEY, source_hash TEXT NOT NULL, applied_at TEXT NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS course_recurrences (
        member INTEGER NOT NULL, slot TEXT NOT NULL, course_id TEXT NOT NULL,
        weekday INTEGER NOT NULL, starts_on TEXT NOT NULL, until_date TEXT,
        start_time TEXT, end_time TEXT, source TEXT NOT NULL,
        PRIMARY KEY(member,slot,course_id),
        FOREIGN KEY(member,slot,course_id) REFERENCES course_courses(member,slot,id) ON DELETE CASCADE)''')
    c.execute('''CREATE TABLE IF NOT EXISTS course_excluded_dates (
        member INTEGER NOT NULL, slot TEXT NOT NULL, course_id TEXT NOT NULL, date TEXT NOT NULL,
        PRIMARY KEY(member,slot,course_id,date),
        FOREIGN KEY(member,slot,course_id) REFERENCES course_recurrences(member,slot,course_id) ON DELETE CASCADE)''')


@contextmanager
def transaction(c, write=False):
    if c.in_transaction:
        # Business functions may participate in an atomic AI request containing
        # authentication, the change, its idempotency result and the audit entry.
        savepoint='course_'+uuid.uuid4().hex
        c.execute('SAVEPOINT '+savepoint)
        try:
            yield c
            c.execute('RELEASE SAVEPOINT '+savepoint)
        except BaseException:
            c.execute('ROLLBACK TO SAVEPOINT '+savepoint)
            c.execute('RELEASE SAVEPOINT '+savepoint)
            raise
        return
    c.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
    try:
        yield c
        c.commit()
    except BaseException:
        c.rollback()
        raise


def empty(member):
    return {'owner':member,'team':1,'term':'2026–2027 秋冬学期','week_start':'2026-09-14',
            'display_range':{'start':'2026-09-14','end':'2027-01-17'},'version':'empty-v1','courses':[],'events':[]}


def validate_schedule(data, member):
    if not isinstance(data,dict) or set(data)!=set(empty(member)):
        raise ValueError('课表字段不完整或包含不支持的字段，未迁移')
    if type(data['owner']) is not int or data['owner']!=member or data['team']!=1:
        raise ValueError('课表成员或小队不匹配')
    if not isinstance(data['display_range'],dict) or set(data['display_range'])!={'start','end'}:
        raise ValueError('学期日期范围无效')
    for value in [data['week_start'],*data['display_range'].values()]:
        if not isinstance(value,str) or date.fromisoformat(value).isoformat()!=value:raise ValueError('日期无效')
    if data['display_range']['start']>data['display_range']['end']:raise ValueError('学期日期范围无效')
    if any(not isinstance(data[k],str) for k in ('version','term')):raise ValueError('课表学期无效')
    ids=set()
    for group, fields, limit in [('courses',COURSE_FIELDS,100),('events',EVENT_FIELDS,10000)]:
        rows=data[group]
        if not isinstance(rows,list) or len(rows)>limit:raise ValueError('课程或安排数量无效')
        seen=set()
        for row in rows:
            allowed=set(fields)|({'recurrence'} if group=='courses' else set())
            if not isinstance(row,dict) or set(row)-allowed or not isinstance(row.get('id'),str) or not row['id'] or row['id'] in seen:
                raise ValueError('课程或安排字段、编号无效，未保存')
            seen.add(row['id'])
            for key,value in row.items():
                if key=='recurrence':
                    validate_recurrence(value)
                    continue
                if value is None:continue
                kind=fields[key]
                if (kind=='TEXT' and not isinstance(value,str)) or (kind=='INTEGER' and type(value) is not int) or (kind=='REAL' and type(value) not in (int,float)):
                    raise ValueError('课程或安排字段类型无效')
                if isinstance(value,str) and len(value)>10000:raise ValueError('课程字段过长')
            if group=='courses':
                if not row.get('name'):raise ValueError('课程名不能为空')
                ids.add(row['id'])
            else:
                if row.get('course_id') not in ids:raise ValueError('上课安排不属于当前课程')
                day=row.get('date')
                if not isinstance(day,str) or date.fromisoformat(day).isoformat()!=day:raise ValueError('安排日期无效')


def read_schedule(c, member, slot='current'):
    if not c.in_transaction:
        with transaction(c):return read_schedule(c,member,slot)
    r=c.execute('SELECT * FROM course_schedules WHERE member=? AND slot=?',(member,slot)).fetchone()
    if r is None:return empty(member) if slot=='current' else None
    data={'owner':member,'team':r['team'],'term':r['term'],'version':r['version'],
          'week_start':r['week_start'],'display_range':{'start':r['range_start'],'end':r['range_end']}}
    for group, table in [('courses','course_courses'),('events','course_meetings')]:
        data[group]=[{k:r[k] for k in r['fields'].split(',')} for r in c.execute(
            f'SELECT * FROM {table} WHERE member=? AND slot=? ORDER BY position',(member,slot))]
    rules={r['course_id']:r for r in c.execute('SELECT * FROM course_recurrences WHERE member=? AND slot=?',(member,slot))}
    for course in data['courses']:
        rule=rules.get(course['id'])
        if rule:
            excluded=[r[0] for r in c.execute('SELECT date FROM course_excluded_dates WHERE member=? AND slot=? AND course_id=? ORDER BY date',(member,slot,course['id']))]
            course['recurrence']={'weekday':rule['weekday'],'starts_on':rule['starts_on'],'until':rule['until_date'],'start_time':rule['start_time'],'end_time':rule['end_time'],'source':rule['source'],'excluded_dates':excluded}
    return data


def put_schedule(c, member, data, slot='current'):
    validate_schedule(data,member)
    c.execute('DELETE FROM course_schedules WHERE member=? AND slot=?',(member,slot))
    c.execute('INSERT INTO course_schedules VALUES(?,?,?,?,?,?,?,?)',
              (member,slot,data['team'],data['term'],data['version'],data['week_start'],data['display_range']['start'],data['display_range']['end']))
    for group,table in [('courses','course_courses'),('events','course_meetings')]:
        for position,row in enumerate(data[group]):
            keys=[k for k in row if k!='recurrence']
            columns=','.join('"'+k+'"' for k in keys)
            c.execute(f'INSERT INTO {table}(member,slot,position,fields,{columns}) VALUES({",".join("?" for _ in range(4+len(keys)))})',
                      (member,slot,position,','.join(keys),*(row[k] for k in keys)))
            if group=='courses' and row.get('recurrence'):
                rule=row['recurrence']
                c.execute('INSERT INTO course_recurrences VALUES(?,?,?,?,?,?,?,?,?)',(member,slot,row['id'],rule['weekday'],rule['starts_on'],rule['until'],rule['start_time'],rule['end_time'],rule['source']))
                c.executemany('INSERT INTO course_excluded_dates VALUES(?,?,?,?)',[(member,slot,row['id'],day) for day in rule['excluded_dates']])


def validate_recurrence(rule):
    fields={'weekday','starts_on','until','start_time','end_time','source','excluded_dates'}
    if not isinstance(rule,dict) or set(rule)!=fields or type(rule['weekday']) is not int or not 1<=rule['weekday']<=7:
        raise ValueError('周期课程格式无效')
    excluded=rule['excluded_dates']
    if not isinstance(excluded,list) or len(excluded)>100 or any(not isinstance(d,str) for d in excluded) or len(excluded)!=len(set(excluded)):
        raise ValueError('周期课程例外日期无效')
    for day in [rule['starts_on'],*excluded]+([rule['until']] if rule['until'] is not None else []):
        if not isinstance(day,str) or date.fromisoformat(day).isoformat()!=day:raise ValueError('周期课程日期无效')
    if date.fromisoformat(rule['starts_on']).weekday()+1!=rule['weekday'] or (rule['until'] and rule['until']<rule['starts_on']):raise ValueError('周期课程日期无效')
    for value in [rule['start_time'],rule['end_time']]:
        if value is not None and (not isinstance(value,str) or not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d',value)):raise ValueError('周期课程时间无效')
    if rule['end_time'] and (not rule['start_time'] or rule['end_time']<=rule['start_time']):raise ValueError('周期课程时间无效')
    if not isinstance(rule['source'],str) or len(rule['source'])>3000:raise ValueError('周期课程来源无效')


def read_tasks(c, member):
    return [{k:r[k] for k in TASK_FIELDS} for r in c.execute('SELECT * FROM course_homework WHERE member=? ORDER BY createdAt,id',(member,))]


def put_task(c, member, task):
    columns=','.join('"'+k+'"' for k in TASK_FIELDS)
    updates=','.join('"'+k+'"=excluded."'+k+'"' for k in TASK_FIELDS if k!='id')
    c.execute(f'INSERT INTO course_homework(member,{columns}) VALUES({",".join("?" for _ in range(1+len(TASK_FIELDS)))}) ON CONFLICT(member,id) DO UPDATE SET {updates}',
              (member,*(task.get(k,'') if k=='submission' else task[k] for k in TASK_FIELDS)))
