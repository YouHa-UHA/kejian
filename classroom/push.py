"""Account-scoped, opt-in Web Push with separate production/testing scopes."""
import base64
import hashlib
import hmac
import json
import re
import secrets
import time
import uuid
from urllib.parse import urlsplit
from . import course_store

DELIVERY_GRACE_SECONDS = 3600
TEST_DELAY_SECONDS = 30

class ConfigurationError(Exception):
    """The sender could not prepare credentials; no request was sent."""


def schema(c):
    c.execute('''CREATE TABLE IF NOT EXISTS push_devices(
        id TEXT PRIMARY KEY, member INTEGER NOT NULL REFERENCES members(id),
        endpoint_hash TEXT UNIQUE NOT NULL, subscription TEXT NOT NULL,
        session_hash TEXT NOT NULL, label TEXT NOT NULL, active INTEGER NOT NULL,
        created INTEGER NOT NULL, updated INTEGER NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS push_jobs(
        id TEXT PRIMARY KEY, member INTEGER NOT NULL REFERENCES members(id),
        device TEXT NOT NULL REFERENCES push_devices(id), request_key TEXT NOT NULL,
        due INTEGER NOT NULL, expires INTEGER NOT NULL, created INTEGER NOT NULL,
        state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, updated INTEGER NOT NULL,
        receipt TEXT NOT NULL, provider_status INTEGER, error TEXT NOT NULL DEFAULT '',
        received INTEGER, shown INTEGER, clicked INTEGER, confirmed INTEGER,
        UNIQUE(member,request_key))''')
    columns={r[1] for r in c.execute('PRAGMA table_info(push_jobs)')}
    if 'test_round' not in columns:c.execute('ALTER TABLE push_jobs ADD COLUMN test_round INTEGER NOT NULL DEFAULT 0')
    if 'test_run' not in columns:c.execute("ALTER TABLE push_jobs ADD COLUMN test_run TEXT NOT NULL DEFAULT ''")
    if 'reminder_id' not in columns:c.execute("ALTER TABLE push_jobs ADD COLUMN reminder_id TEXT NOT NULL DEFAULT ''")
    c.execute('CREATE INDEX IF NOT EXISTS push_jobs_due ON push_jobs(state,due)')
    c.execute('CREATE INDEX IF NOT EXISTS push_jobs_expires ON push_jobs(expires)')
    c.execute('CREATE TABLE IF NOT EXISTS push_worker_state(id INTEGER PRIMARY KEY CHECK(id=1), heartbeat INTEGER NOT NULL)')
    from . import reminders
    reminders.schema(c)
    from . import reminder_changes
    reminder_changes.schema(c)


def config(value, base):
    if value is None:
        return None
    scopes={'testing':'/mem-test/','production':'/mem/'}
    if value.get('environment') not in scopes or base != scopes[value['environment']]:
        raise ValueError('Push environment and application scope do not match')
    key = value.get('publicKey', '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{87}', key):
        raise ValueError('Invalid push public key')
    return {**value, 'scope':base, 'delaySeconds':TEST_DELAY_SECONDS}


def subscription(value):
    if not isinstance(value, dict):
        raise ValueError('设备订阅格式不正确，请重新开启通知。')
    endpoint = value.get('endpoint', '')
    try:
        u = urlsplit(endpoint)
        host = u.hostname or ''
        allowed = host in ('web.push.apple.com','fcm.googleapis.com','updates.push.services.mozilla.com') or host.endswith('.push.apple.com') or host.endswith('.notify.windows.com')
        assert allowed and u.scheme == 'https' and u.port in (None,443) and not u.username and not u.password and not u.fragment and 1 <= len(endpoint) <= 3000
        keys = value['keys']
        for key,size in [('p256dh',65),('auth',16)]:
            assert isinstance(keys[key],str) and re.fullmatch(r'[A-Za-z0-9_-]+',keys[key])
            raw = base64.urlsafe_b64decode(keys[key] + '=' * (-len(keys[key]) % 4))
            assert len(raw) == size
            if key == 'p256dh': assert raw[0] == 4
    except (AssertionError,ValueError,KeyError,TypeError):
        raise ValueError('当前浏览器的推送订阅无法使用，请换用支持通知的系统浏览器。') from None
    return {'endpoint':endpoint, 'keys':{'p256dh':keys['p256dh'],'auth':keys['auth']}}


def deactivate(c, *, session=None, member=None, device=None):
    field, value = ('session_hash',session) if session else ('member',member) if member else ('id',device)
    c.execute(f"UPDATE push_jobs SET state='cancelled',updated=? WHERE device IN (SELECT id FROM push_devices WHERE {field}=?) AND state IN ('scheduled','retry','sending')", (int(time.time()),value))
    c.execute(f'UPDATE push_devices SET active=0,updated=? WHERE {field}=?', (int(time.time()),value))


def worker_online(c, now=None):
    row = c.execute('SELECT heartbeat FROM push_worker_state WHERE id=1').fetchone()
    return bool(row and (now or int(time.time())) - row[0] < 60)


def serial(row):
    return {**{k:row[k] for k in ('id','due','expires','state','received','shown','clicked','confirmed')},'testRound':row['test_round']}


def status(c, member, ident):
    device = c.execute('SELECT * FROM push_devices WHERE id=? AND member=?', (ident,member)).fetchone()
    if not device: return {'enabled':False,'jobs':[], 'workerOnline':worker_online(c)}
    jobs = [serial(r) for r in c.execute("SELECT * FROM push_jobs WHERE device=? AND member=? AND reminder_id='' ORDER BY created DESC,rowid DESC LIMIT 5", (ident,member))]
    option=c.execute('SELECT enabled FROM push_device_preferences WHERE device=?',(ident,)).fetchone()
    return {'enabled':bool(device['active']), 'remindersEnabled':bool(device['active'] and option and option['enabled']), 'deviceId':device['id'], 'label':device['label'], 'jobs':jobs, 'workerOnline':worker_online(c)}


def account_status(c, member, selected=''):
    # An authenticated browser may test its own account's registered devices.
    # Subscription endpoints, keys and session hashes never leave the server.
    rows=c.execute('''SELECT d.id,d.label FROM push_devices d
        JOIN sessions s ON s.token_hash=d.session_hash AND s.member=d.member
        JOIN members m ON m.id=d.member
        WHERE d.member=? AND d.active=1 AND s.expires>? AND m.disabled=0
        ORDER BY CASE WHEN d.label='电脑浏览器' THEN 1 ELSE 0 END,d.created,d.id''',
        (member,int(time.time()))).fetchall()
    if selected and selected not in {r['id'] for r in rows}:
        raise PermissionError('这个账号不能向该设备发送通知')
    return {'owner':member,'workerOnline':worker_online(c),
            'devices':[{'id':r['id'],'label':r['label'],'jobs':status(c,member,r['id'])['jobs']} for r in rows]}


def queue_test(c, member, device, key, now, *, test_round=0, test_run=''):
    if not isinstance(key,str) or not re.fullmatch(r'[a-zA-Z0-9-]{16,80}',key): raise ValueError('测试编号不正确')
    if test_round or test_run:
        student=c.execute('SELECT student FROM members WHERE id=?',(member,)).fetchone()[0]
        allowed={1:('2026000001',),2:('2026000003',),3:('2026000001','2026000003')}
        if type(test_round) is not int or student not in allowed.get(test_round,()) or not isinstance(test_run,str) or not re.fullmatch(r'[a-f0-9]{32}',test_run):
            raise ValueError('双用户测试仅适用于指定测试账号和轮次')
    old = c.execute('SELECT * FROM push_jobs WHERE member=? AND request_key=?',(member,key)).fetchone()
    if old:
        if old['device'] != device['id'] or old['test_round']!=test_round or old['test_run']!=test_run: raise ValueError('测试编号已使用')
        return
    if not worker_online(c,now): raise ValueError('测试发送服务暂时不可用，请稍后重试。')
    if c.execute("SELECT 1 FROM push_jobs WHERE device=? AND reminder_id='' AND state IN ('scheduled','retry','sending')",(device['id'],)).fetchone():
        raise ValueError('已有一条测试通知等待发送，请先等待或取消。')
    if c.execute("SELECT count(*) FROM push_jobs WHERE member=? AND created>? AND reminder_id=''",(member,now-3600)).fetchone()[0] >= 12 or c.execute("SELECT count(*) FROM push_jobs WHERE created>? AND reminder_id=''",(now-3600,)).fetchone()[0] >= 100:
        raise ValueError('测试次数较多，请一小时后再试。')
    c.execute('''INSERT INTO push_jobs(id,member,device,request_key,due,expires,created,state,updated,receipt,test_round,test_run)
        VALUES(?,?,?,?,?,?,?,'scheduled',?,?,?,?)''',(str(uuid.uuid4()),member,device['id'],key,now+TEST_DELAY_SECONDS,now+TEST_DELAY_SECONDS+300,now,now,secrets.token_urlsafe(32),test_round,test_run))


def change(c, member, session, action, b):
    now = int(time.time())
    with course_store.transaction(c, write=True):
        if action in ('reminder-settings','reminder-settings-save'):
            from . import reminders
            if action=='reminder-settings-save':reminders.save_preferences(c,member,b,now)
            return {**reminders.overview(c,member,now),'workerOnline':worker_online(c,now)}
        if action=='account-status':
            return account_status(c,member)
        if action=='test-account':
            ident=b.get('deviceId')
            if not isinstance(ident,str):raise ValueError('请选择这个账号已开启通知的设备')
            account_status(c,member,ident)
            device=c.execute('SELECT * FROM push_devices WHERE id=? AND member=? AND active=1',(ident,member)).fetchone()
            if not device:raise PermissionError('这个账号不能向该设备发送通知')
            queue_test(c,member,device,b.get('requestKey',''),now)
            return account_status(c,member,ident)
        if action == 'register':
            sub = subscription(b.get('subscription'))
            hashed = hashlib.sha256(sub['endpoint'].encode()).hexdigest()
            previous = c.execute('SELECT * FROM push_devices WHERE endpoint_hash=?',(hashed,)).fetchone()
            if previous and json.loads(previous['subscription']) != sub:
                raise ValueError('订阅已变化，请关闭此设备通知后重新开启。')
            if (not previous or not previous['active'] or previous['member'] != member) and c.execute('SELECT count(*) FROM push_devices WHERE member=? AND active=1',(member,)).fetchone()[0] >= 8:
                raise ValueError('已连接的设备较多，请先关闭不再使用的设备通知。')
            ident = previous['id'] if previous else str(uuid.uuid4())
            if previous and (previous['member'] != member or previous['session_hash'] != session):
                deactivate(c,device=ident)
                c.execute('UPDATE push_device_preferences SET enabled=0 WHERE device=?',(ident,))
            label = b.get('label','这台设备')
            if not isinstance(label,str) or not 1 <= len(label) <= 40: raise ValueError('设备名称不正确')
            c.execute('''INSERT INTO push_devices(id,member,endpoint_hash,subscription,session_hash,label,active,created,updated) VALUES(?,?,?,?,?,?,1,?,?)
                ON CONFLICT(id) DO UPDATE SET member=excluded.member,session_hash=excluded.session_hash,
                label=excluded.label,active=1,updated=excluded.updated''',
                (ident,member,hashed,json.dumps(sub),session,label,now,now))
            return status(c,member,ident)
        ident = b.get('deviceId')
        if not isinstance(ident,str): raise ValueError('请先开启这台设备的通知。')
        device = c.execute('SELECT * FROM push_devices WHERE id=? AND member=? AND session_hash=?',(ident,member,session)).fetchone()
        if not device: raise PermissionError('此设备未连接当前账号，请重新开启通知。')
        if action == 'status': return status(c,member,ident)
        if action in ('reminders-enable','reminders-disable'):
            from . import reminders
            reminders.toggle_device(c,member,device,action=='reminders-enable',now)
            return {**status(c,member,ident),'preferences':reminders.overview(c,member,now)}
        if action == 'disable':
            deactivate(c,device=ident)
            return status(c,member,ident)
        if action == 'cancel':
            c.execute("UPDATE push_jobs SET state='cancelled',updated=? WHERE device=? AND reminder_id='' AND state IN ('scheduled','retry','sending')",(now,ident))
            return status(c,member,ident)
        if action == 'confirm':
            if type(b.get('received')) is not bool: raise ValueError('请选择是否在锁屏上看到了通知。')
            row = c.execute('SELECT * FROM push_jobs WHERE id=? AND device=? AND member=?',(b.get('id'),ident,member)).fetchone()
            if not row or row['state'] in ('scheduled','retry','cancelled'): raise ValueError('请等待测试发送后再确认。')
            c.execute('UPDATE push_jobs SET confirmed=? WHERE id=?',(int(b['received']),row['id']))
            return status(c,member,ident)
        if action != 'test': raise ValueError('通知操作不支持')
        if not device['active']: raise ValueError('请先开启这台设备的通知。')
        queue_test(c,member,device,b.get('requestKey',''),now)
        return status(c,member,ident)


def receipt(c, member, session, b):
    with course_store.transaction(c,write=True):
        row = c.execute('SELECT * FROM push_jobs WHERE id=? AND member=?',(b.get('id'),member)).fetchone()
        supplied = b.get('receipt','')
        if not row or not isinstance(supplied,str) or not hmac.compare_digest(row['receipt'],supplied):
            raise PermissionError('通知凭据无效')
        device = c.execute('''SELECT * FROM push_devices WHERE id=? AND member=? AND session_hash=? AND active=1''', (row['device'],member,session)).fetchone()
        now = int(time.time())
        if not device or row['state'] in ('cancelled','expired','subscription_expired') or now > row['expires']+3600:
            return {'ok':True,'display':False}
        if row['reminder_id']:
            from . import reminders
            if reminders.allowed(c,row,device,now) is None:return {'ok':True,'display':False}
        stage = b.get('stage')
        if stage not in ('received','shown','clicked'): raise ValueError('通知回执不正确')
        c.execute(f'UPDATE push_jobs SET {stage}=coalesce({stage},?) WHERE id=?',(now,row['id']))
        return {'ok':True,'display':stage != 'received' or (now <= row['expires'] and not row['shown'])}


def prune(c, now):
    """Keep only live delivery/deduplication state plus a short receipt grace."""
    cutoff=now-DELIVERY_GRACE_SECONDS
    c.execute('DELETE FROM push_jobs WHERE expires<?',(cutoff,))
    c.execute('''DELETE FROM push_reminders WHERE expires<?
        AND NOT EXISTS(SELECT 1 FROM push_jobs j WHERE j.reminder_id=push_reminders.id)''',(cutoff,))
    c.execute('DELETE FROM push_devices WHERE active=0 AND updated<? AND NOT EXISTS(SELECT 1 FROM push_jobs j WHERE j.device=push_devices.id)',(now-30*86400,))


def maintain(c, now=None, cleanup=True):
    now = int(time.time()) if now is None else now
    with course_store.transaction(c,write=True):
        c.execute('INSERT INTO push_worker_state VALUES(1,?) ON CONFLICT(id) DO UPDATE SET heartbeat=excluded.heartbeat',(now,))
        if cleanup:prune(c,now)
        c.execute("UPDATE push_jobs SET state='unknown',updated=? WHERE state='sending' AND updated<?",(now,now-60))
        c.execute("UPDATE push_jobs SET state='expired',updated=? WHERE state IN ('scheduled','retry') AND expires<?",(now,now))


def next_due(c):
    # Separate index seeks avoid sorting the entire pending queue.
    due=[c.execute('SELECT min(due) FROM push_jobs WHERE state=?',(state,)).fetchone()[0] for state in ('scheduled','retry')]
    return min((value for value in due if value is not None),default=None)


def claim(c, now):
    """Main-thread claim: None means no work, False means safely discarded.

    A delivery contains detached snapshots only, never a SQLite connection or
    cursor. Persist the claim before handing network I/O to another thread.
    """
    due=next_due(c)
    if due is None or due>now:return None
    with course_store.transaction(c,write=True):
        ready=[c.execute('SELECT * FROM push_jobs WHERE state=? AND due<=? ORDER BY due LIMIT 1',(state,now)).fetchone() for state in ('scheduled','retry')]
        row=min((item for item in ready if item is not None),key=lambda item:item['due'],default=None)
        if not row:return None
        if row['expires']<=now:
            c.execute("UPDATE push_jobs SET state='expired',updated=? WHERE id=?",(now,row['id']));return False
        device = c.execute('''SELECT d.*,m.name AS recipient_name,m.student AS recipient_student FROM push_devices d JOIN sessions s ON s.token_hash=d.session_hash
            JOIN members m ON m.id=d.member WHERE d.id=? AND d.active=1 AND d.member=?
            AND s.member=d.member AND s.expires>? AND m.disabled=0''',(row['device'],row['member'],now)).fetchone()
        if not device or (row['test_round'] and device['recipient_student'] not in ('2026000001','2026000003')):
            c.execute("UPDATE push_jobs SET state='cancelled',updated=? WHERE id=?",(now,row['id']));return False
        reminder_payload=None
        if row['reminder_id']:
            from . import reminders
            reminder_payload=reminders.allowed(c,row,device,now)
            if reminder_payload is None:
                c.execute("UPDATE push_jobs SET state='cancelled',updated=? WHERE id=?",(now,row['id']));return False
        c.execute("UPDATE push_jobs SET state='sending',attempts=attempts+1,updated=? WHERE id=?",(now,row['id']))
    payload = {'id':row['id'],'owner':row['member'],'receipt':row['receipt'],'pilot':True,
               'title':'课间测试 · 给'+device['recipient_name'],
               'body':'仅发给'+device['recipient_name']+'（测试账号尾号'+device['recipient_student'][-4:]+'）。点开后请确认是否在锁屏上看到它。',
               'key':row['id'],'url':'notifications.html'}
    if reminder_payload:payload.update(reminder_payload)
    if row['test_round']:
        role={'2026000001':'A','2026000003':'B'}.get(device['recipient_student'])
        label='仅 '+role if row['test_round'] in (1,2) else role+' 专属'
        example='给 A 的课程提醒（模拟）' if role=='A' else '给 B 的作业提醒（模拟）'
        payload.update(title=f"第{row['test_round']}轮 · {label} · 课间测试",
                       body=f"{example}。收件人：{device['recipient_name']}，账号尾号{device['recipient_student'][-4:]}。测试批次{row['test_run'][:6]}。",
                       url='notifications.html?target=device&test=isolation')
    return {'job':dict(row),'device':dict(device),'payload':payload}


def deliver(delivery, cfg, send, clock=time.time):
    """Thread-safe network phase: no database access and no shared payload."""
    row=delivery['job'];device=delivery['device'];now=int(clock())
    if now>=row['expires']:return ('expired',None,'')
    try:
        payload=dict(delivery['payload'])
        if cfg.get('environment')=='production':
            payload.pop('pilot',None)
            payload.update(managed=True,environment='production',scope='/mem/')
            if not row['reminder_id']:
                payload.update(title='课间 · 测试提醒',body='这台设备已连接课间提醒。课程和作业消息将按你自己的账号与教学班发送。',url='notifications-reminders.html')
        code = send(subscription(json.loads(device['subscription'])),payload,cfg,max(1,row['expires']-now))
        state,error = ('accepted','') if 200 <= code < 300 else ('failed','PROVIDER_REJECTED')
    except Exception as e:
        code = getattr(e,'status_code',None)
        response = getattr(e,'response',None)
        if code is None and response is not None: code = getattr(response,'status_code',None)
        if isinstance(e,ConfigurationError): state,error='failed','CONFIGURATION_ERROR'
        elif code in (404,410): state,error='subscription_expired','SUBSCRIPTION_EXPIRED'
        elif code in (429,500,502,503,504) and row['attempts'] < 2 and int(clock())+30 < row['expires']: state,error='retry','PROVIDER_BUSY'
        else: state,error=('unknown','NETWORK_OR_TIMEOUT') if code is None else ('failed','PROVIDER_REJECTED')
    return state,code,error


def complete(c, delivery, outcome, now):
    """Main-thread completion; a late result must not undo cancellation/rebind."""
    row=delivery['job'];device=delivery['device'];state,code,error=outcome
    if state=='retry' and now+30>=row['expires']:state='failed'
    with course_store.transaction(c,write=True):
        changed=c.execute("UPDATE push_jobs SET state=?,provider_status=?,error=?,updated=?,due=CASE WHEN ?='retry' THEN ? ELSE due END WHERE id=? AND member=? AND device=? AND attempts=? AND state='sending'",
                  (state,code,error,now,state,now+30,row['id'],row['member'],row['device'],row['attempts']+1)).rowcount
        if changed and state == 'subscription_expired':
            current=c.execute('SELECT member,session_hash,subscription FROM push_devices WHERE id=?',(device['id'],)).fetchone()
            # The same browser endpoint may since have moved to another account.
            if current and all(current[k]==device[k] for k in ('member','session_hash','subscription')):
                deactivate(c,device=device['id'])


def tick(c, cfg, send, now=None, maintenance=True):
    """Synchronous maintenance/test adapter over the same claim/deliver/complete."""
    now = int(time.time()) if now is None else now
    if maintenance:maintain(c,now)
    delivery=claim(c,now)
    if delivery is None:return False
    if delivery is not False:complete(c,delivery,deliver(delivery,cfg,send,lambda:now),now)
    return True
