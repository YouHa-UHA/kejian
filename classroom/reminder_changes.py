"""One durable, coalesced change marker per reminder recipient, not an event log."""
from . import course_store


def eligible(member):
    return f'''(EXISTS(SELECT 1 FROM push_devices d JOIN push_device_preferences p ON p.device=d.id
        WHERE d.member={member} AND d.active=1 AND p.enabled=1)
        OR EXISTS(SELECT 1 FROM push_jobs j WHERE j.member={member}
            AND j.reminder_id<>'' AND j.state IN ('scheduled','retry','sending')))'''


def mark(member, condition='1'):
    return f'''INSERT INTO push_changes(member,version)
        SELECT {member},hex(randomblob(16)) WHERE {condition} AND {eligible(member)}
        ON CONFLICT(member) DO UPDATE SET version=excluded.version;'''


def shared(key):
    return f'''INSERT INTO push_changes(member,version)
        SELECT e.member,hex(randomblob(16)) FROM teaching_enrollments e
        WHERE e.offering={key} AND e.active=1 AND {eligible('e.member')}
        ON CONFLICT(member) DO UPDATE SET version=excluded.version;'''


def schema(c):
    c.execute('''CREATE TABLE IF NOT EXISTS push_changes(
        member INTEGER PRIMARY KEY REFERENCES members(id) ON DELETE CASCADE,
        version TEXT NOT NULL)''')
    c.execute('CREATE INDEX IF NOT EXISTS push_enrollments_offering ON teaching_enrollments(offering,active,member)')
    c.execute('CREATE INDEX IF NOT EXISTS push_devices_member_active ON push_devices(member,active)')
    c.execute('CREATE INDEX IF NOT EXISTS push_jobs_member_state ON push_jobs(member,state)')
    personal=('course_schedules','course_courses','course_meetings','course_recurrences','course_excluded_dates',
              'course_homework','teaching_homework_status','teaching_enrollments','push_preferences','sessions')
    for table in personal:
        for action,refs in [('INSERT',('NEW',)),('UPDATE',('OLD','NEW')),('DELETE',('OLD',))]:
            body=''.join(mark(ref+'.member',ref+".slot='current'" if table.startswith('course_') and table!='course_homework' else '1') for ref in refs)
            c.execute(f'CREATE TRIGGER IF NOT EXISTS push_change_{table}_{action.lower()} AFTER {action} ON {table} BEGIN {body} END')
    for table,column in [('teaching_homework','offering'),('teaching_offerings','key')]:
        for action,refs in [('INSERT',('NEW',)),('UPDATE',('OLD','NEW')),('DELETE',('OLD',))]:
            body=''.join(shared(ref+'.'+column) for ref in refs)
            c.execute(f'CREATE TRIGGER IF NOT EXISTS push_change_{table}_{action.lower()} AFTER {action} ON {table} BEGIN {body} END')
    for action,refs in [('INSERT',('NEW',)),('UPDATE',('OLD','NEW')),('DELETE',('OLD',))]:
        body=''.join(mark('(SELECT member FROM push_devices WHERE id='+ref+'.device)') for ref in refs)
        c.execute(f'CREATE TRIGGER IF NOT EXISTS push_change_device_preferences_{action.lower()} AFTER {action} ON push_device_preferences BEGIN {body} END')
    c.execute(f'''CREATE TRIGGER IF NOT EXISTS push_change_device_insert AFTER INSERT ON push_devices
        BEGIN {mark('NEW.member')} END''')
    c.execute(f'''CREATE TRIGGER IF NOT EXISTS push_change_device_update AFTER UPDATE OF member,active,session_hash,label ON push_devices
        BEGIN {mark('OLD.member')}{mark('NEW.member')} END''')
    c.execute(f'''CREATE TRIGGER IF NOT EXISTS push_change_member_disabled AFTER UPDATE OF disabled ON members
        BEGIN {mark('NEW.id')} END''')


def enqueue_active(c, now):
    with course_store.transaction(c,write=True):
        c.execute('''INSERT INTO push_changes(member,version)
            SELECT member,hex(randomblob(16)) FROM (
                SELECT DISTINCT d.member FROM push_devices d
                JOIN push_device_preferences p ON p.device=d.id AND p.enabled=1
                JOIN sessions s ON s.token_hash=d.session_hash AND s.member=d.member
                JOIN members m ON m.id=d.member
                WHERE d.active=1 AND d.label='iPhone / iPad' AND s.expires>? AND m.disabled=0
                UNION SELECT member FROM push_jobs WHERE reminder_id<>'' AND state IN ('scheduled','retry','sending')
            ) WHERE 1 ON CONFLICT(member) DO UPDATE SET version=excluded.version''',(now,))
