"""Roster-only classroom accounts, personal SQL schedules and homework.

This is a separate entry point. The W read-only deployment is not modified.
"""
import hashlib
import hmac
from http import HTTPStatus
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from urllib.parse import urlsplit, parse_qs

from production import FILES, HEADERS, PUBLIC
from . import course_store, homework, importer, merge, community, course_homework, agent, import_guide, agent_mcp, comments


class Problem(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def connect(path):
    c = sqlite3.connect(path, timeout=10, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    return c


def initialize(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript('''
        CREATE TABLE IF NOT EXISTS members(
            id INTEGER PRIMARY KEY, student TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
            salt TEXT, password_hash TEXT, activation_hash TEXT,
            shared INTEGER NOT NULL DEFAULT 0, disabled INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS sessions(
            token_hash TEXT PRIMARY KEY, member INTEGER NOT NULL REFERENCES members(id), expires INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS attempts(key TEXT NOT NULL, at INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS attempts_key ON attempts(key,at);
        ''')
        course_store.schema(c)
        community.schema(c)
        course_homework.schema(c)
        comments.schema(c)
        agent.schema(c)
        community.migrate_existing(c)
    path.chmod(0o600)


def provision(path, rows, default_password=None):
    """Create roster entries once. Existing passwords/data are never reset."""
    if default_password is not None and (not isinstance(default_password,str) or not 6 <= len(default_password) <= 128):
        raise ValueError('初始密码须为6至128位')
    checked = []
    for row in rows:
        student, name = str(row.get('student', '')).strip(), str(row.get('name', '')).strip()
        if not re.fullmatch(r'\d{6,20}', student) or not 1 <= len(name) <= 40:
            raise ValueError('名单须包含6至20位学号和姓名')
        checked.append((student, name))
    if not checked or len(set(s for s, _ in checked)) != len(checked):
        raise ValueError('名单为空或学号重复')
    initialize(path)
    created = []
    with connect(path) as c, course_store.transaction(c, write=True):
        for student, name in checked:
            if c.execute('SELECT 1 FROM members WHERE student=?', (student,)).fetchone():
                continue
            if default_password is not None:
                salt = secrets.token_hex(16)
                c.execute('INSERT INTO members(student,name,salt,password_hash) VALUES(?,?,?,?)', (student, name, salt, password_hash(default_password, salt)))
                created.append({'student': student, 'name': name})
            else:
                code = secrets.token_urlsafe(18)
                c.execute('INSERT INTO members(student,name,activation_hash) VALUES(?,?,?)', (student, name, digest(code)))
                created.append({'student': student, 'name': name, 'activation': code})
    return created


class ClassroomApplication:
    def __init__(self, database, origin='http://127.0.0.1:4186', base='/', release='classroom-dev', extra_origins=()):
        self.database, self.origin, self.base, self.release = str(database), origin.rstrip('/'), base, release
        self.allowed_origins = frozenset((self.origin, *(x.rstrip('/') for x in extra_origins)))
        for value in self.allowed_origins:
            parsed = urlsplit(value)
            if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
                raise ValueError('origin must be an explicit HTTP(S) origin')
        if not base.startswith('/') or not base.endswith('/'):
            raise ValueError('base must start and end with /')
        initialize(database)

    def __call__(self, env, start):
        method, path = env.get('REQUEST_METHOD', 'GET'), env.get('PATH_INFO', '/')
        c = None

        def reply(status, data, mime='application/json; charset=utf-8', extra=()):
            body = json.dumps(data, ensure_ascii=False).encode() if isinstance(data, (dict, list)) else data.encode() if isinstance(data, str) else data
            start(f'{status} {HTTPStatus(status).phrase}', [('Content-Type', mime), ('Content-Length', str(len(body))), *HEADERS, *extra])
            return [b'' if method == 'HEAD' else body]

        def body(machine=False):
            if not machine and (env.get('HTTP_ORIGIN') not in self.allowed_origins or env.get('HTTP_X_KEJIAN_REQUEST') != '1'):
                raise Problem(403, '请从课间页面发起操作')
            if env.get('CONTENT_TYPE', '').split(';')[0] != 'application/json':
                raise Problem(415, '需要JSON格式')
            try:
                length = int(env.get('CONTENT_LENGTH', '0'))
                if not 0 < length <= 200000:
                    raise Problem(413, '内容过大或为空')
                raw = env['wsgi.input'].read(length)
                if len(raw) != length:
                    raise ValueError()
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise ValueError()
                return value
            except (ValueError, TypeError):
                raise Problem(400, '请求格式不正确')

        def cookie(token='', age=30*86400):
            secure = '; Secure' if self.origin.startswith('https://') else ''
            return ('Set-Cookie', f'kejian_session={token}; Path={self.base}; HttpOnly; SameSite=Lax; Max-Age={age}{secure}')

        try:
            if method in ('GET', 'HEAD') and path in FILES:
                filename, mime = FILES[path]
                # Legacy single-person notification experiments are not exposed in classroom mode.
                if path in ('/reminders.html', '/reminders.mjs', '/push-test.html', '/push-test.mjs', '/wechat-test.html', '/wechat-test.mjs'):
                    raise Problem(404, '页面不存在')
                return reply(200, (PUBLIC / filename).read_bytes(), mime)
            if path == '/healthz' and method == 'GET':
                return reply(200, {'ok': True, 'release': self.release})
            if path == agent_mcp.PREFIX:
                c = connect(self.database)
                status, data, headers = agent_mcp.handle(self, c, env)
                return reply(status, data, extra=headers)
            if method not in ('GET', 'HEAD', 'POST'):
                raise Problem(405, '不支持此操作')
            c = connect(self.database)
            if path == agent.PREFIX or path.startswith(agent.PREFIX+'/'):
                return reply(200, agent.handle(self, c, env, lambda: body(machine=True)))
            if path in ('/api/login', '/api/activate') and method == 'POST':
                b = body()
                student, password = b.get('student', ''), b.get('password', '')
                minimum = 8 if path == '/api/activate' else 6
                if not isinstance(student, str) or not isinstance(password, str) or not re.fullmatch(r'\d{6,20}', student) or not minimum <= len(password) <= 128:
                    raise Problem(400, f'学号须为6至20位数字，密码须为{minimum}至128位')
                now = int(time.time())
                with course_store.transaction(c, write=True):
                    c.execute('DELETE FROM attempts WHERE at<?', (now-3600,))
                    c.execute('DELETE FROM sessions WHERE expires<?', (now,))
                    remote=env.get('REMOTE_ADDR','local')
                    client=env.get('HTTP_X_REAL_IP',remote) if remote in ('127.0.0.1','::1') else remote
                    keys = ['user:'+student, 'ip:'+digest(client)]
                    for key, limit in zip(keys, (12, 150)):
                        if c.execute('SELECT count(*) FROM attempts WHERE key=? AND at>?', (key, now-600)).fetchone()[0] >= limit:
                            raise Problem(429, '尝试较频繁，请10分钟后重试')
                        c.execute('INSERT INTO attempts VALUES(?,?)', (key, now))
                with course_store.transaction(c, write=True):
                    user = c.execute('SELECT * FROM members WHERE student=? AND disabled=0', (student,)).fetchone()
                    if path == '/api/activate':
                        code = b.get('activation', '')
                        if not isinstance(code, str) or not 1 <= len(code) <= 100 or not user or user['password_hash'] or not hmac.compare_digest(user['activation_hash'] or '', digest(code)):
                            raise Problem(401, '学号或开通码不正确，或账号已开通')
                        salt = secrets.token_hex(16)
                        c.execute('UPDATE members SET salt=?,password_hash=?,activation_hash=NULL WHERE id=?', (salt, password_hash(password, salt), user['id']))
                    else:
                        salt = user['salt'] if user and user['salt'] else '00'*16
                        test = password_hash(password, salt)
                        if not user or not user['password_hash'] or not hmac.compare_digest(test, user['password_hash']):
                            raise Problem(401, '学号或密码不正确')
                    token = secrets.token_urlsafe(32)
                    c.execute('INSERT INTO sessions VALUES(?,?,?)', (digest(token), user['id'], now+30*86400))
                return reply(200, {'ok': True}, extra=[cookie(token)])
            jar = SimpleCookie()
            try:
                jar.load(env.get('HTTP_COOKIE', ''))
                token = jar['kejian_session'].value if 'kejian_session' in jar else ''
            except Exception:
                token = ''
            user = c.execute('SELECT m.* FROM members m JOIN sessions s ON s.member=m.id WHERE s.token_hash=? AND s.expires>? AND m.disabled=0', (digest(token), int(time.time()))).fetchone()
            if not user:
                raise Problem(401, '请登录课间')
            member = user['id']
            if method in ('GET', 'HEAD'):
                if path == '/api/ai-connections':
                    return reply(200, agent.connections(c, member))
                if path == '/api/session':
                    return reply(200, {'id': member, 'student': user['student'], 'name': user['name'], 'shared': bool(user['shared']), **community.roles(c, member)})
                if path == '/api/schedule':
                    return reply(200, {**course_store.read_schedule(c, member), 'schema_version': 2, 'ownerName': user['name']})
                if path == '/api/homework':
                    return reply(200, course_homework.feed(c, member))
                if path == '/api/homework-comments':
                    query=parse_qs(env.get('QUERY_STRING',''))
                    return reply(200, comments.listing(c,member,query.get('homework',[''])[0],query.get('after',[None])[0],query.get('comment',[None])[0]))
                if path == '/api/course-homework':
                    key = parse_qs(env.get('QUERY_STRING', '')).get('course', [''])[0]
                    return reply(200, course_homework.for_course(c, member, key))
                if path == '/api/course-library':
                    return reply(200, community.library(c, member))
                if path == '/api/management':
                    return reply(200, community.management(c, member))
                if path == '/api/import-guide':
                    return reply(200, import_guide.document())
                if path == '/api/timetable-peers':
                    rows = c.execute('SELECT m.id,m.name,count(cc.id) AS courses FROM members m JOIN course_courses cc ON cc.member=m.id AND cc.slot=\'current\' WHERE m.shared=1 AND m.disabled=0 AND m.id<>? GROUP BY m.id ORDER BY m.name,m.id', (member,))
                    return reply(200, {'members': [{'member': r['id'], 'name': r['name'], 'courses': r['courses']} for r in rows]})
            elif method == 'POST':
                b = body()
                if type(b.get('owner')) is not int or b['owner'] != member:
                    raise Problem(403, '账号已变化，请刷新后重试')
                if path == '/api/ai-connections':
                    package = agent.issue(c, member, b, self.origin+self.base+'api/agent/v1')
                    if package is not None:
                        return reply(200, package, 'application/zip', [('Content-Disposition', 'attachment; filename="kejian-ai-connection.zip"')])
                    return reply(200, {'ok': True})
                if path == '/api/logout':
                    c.execute('DELETE FROM sessions WHERE token_hash=?', (digest(token),))
                    return reply(200, {'ok': True}, extra=[cookie(age=0)])
                if path == '/api/password':
                    if set(b)!={'owner','currentPassword','newPassword','confirmPassword'}:
                        raise Problem(400,'密码修改参数不正确')
                    old,new,confirmation=b['currentPassword'],b['newPassword'],b['confirmPassword']
                    if not isinstance(old,str) or not 6<=len(old)<=128:
                        raise Problem(400,'请填写当前密码')
                    if not isinstance(new,str) or not 8<=len(new)<=128 or not new.strip():
                        raise Problem(400,'新密码须为8至128位')
                    if new!=confirmation:raise Problem(400,'两次输入的新密码不一致')
                    if new==old:raise Problem(400,'新密码不能与当前密码相同')
                    stamp=int(time.time());attempt_key='password:'+str(member)
                    with course_store.transaction(c,write=True):
                        c.execute('DELETE FROM attempts WHERE at<?',(stamp-3600,))
                        if c.execute('SELECT count(*) FROM attempts WHERE key=? AND at>?',(attempt_key,stamp-600)).fetchone()[0]>=5:
                            raise Problem(429,'尝试较频繁，请10分钟后重试')
                        c.execute('INSERT INTO attempts VALUES(?,?)',(attempt_key,stamp))
                    with course_store.transaction(c,write=True):
                        fresh=c.execute('SELECT m.* FROM members m JOIN sessions s ON s.member=m.id WHERE m.id=? AND m.disabled=0 AND s.token_hash=? AND s.expires>?',
                                        (member,digest(token),stamp)).fetchone()
                        if not fresh:raise Problem(401,'登录已失效，请重新登录')
                        if not fresh['salt'] or not fresh['password_hash'] or not hmac.compare_digest(password_hash(old,fresh['salt']),fresh['password_hash']):
                            raise Problem(400,'当前密码不正确')
                        salt=secrets.token_hex(16)
                        c.execute('UPDATE members SET salt=?,password_hash=? WHERE id=?',(salt,password_hash(new,salt),member))
                        c.execute('DELETE FROM sessions WHERE member=?',(member,))
                        fresh_token=secrets.token_urlsafe(32)
                        c.execute('INSERT INTO sessions VALUES(?,?,?)',(digest(fresh_token),member,stamp+30*86400))
                        c.execute('DELETE FROM attempts WHERE key=?',(attempt_key,))
                    return reply(200,{'ok':True},extra=[cookie(fresh_token)])
                if path == '/api/profile':
                    if type(b.get('shared')) is not bool:
                        raise Problem(400, '共享设置无效')
                    c.execute('UPDATE members SET shared=? WHERE id=?', (int(b['shared']), member))
                    return reply(200, {'ok': True})
                if path == '/api/homework':
                    result = homework.change(c, member, b)
                    return reply(200, {**result, **course_homework.feed(c, member)})
                if path == '/api/homework-comments':
                    return reply(200, comments.change(c,member,b))
                if path == '/api/course-homework':
                    return reply(200, course_homework.change(c, member, b))
                if path == '/api/timetable-import':
                    return reply(200, self.import_schedule(c, member, b))
                if path == '/api/course-library':
                    return reply(200, community.change_subscription(c, member, b))
                if path == '/api/management':
                    return reply(200, community.manage(c, member, b))
            raise Problem(404, '页面不存在')
        except agent.AgentError as e:
            return reply(e.status, {'error': e.message, 'code': e.code, **e.context})
        except Problem as e:
            return reply(e.status, {'error': e.message})
        except PermissionError as e:
            return reply(403, {'error': str(e)})
        except ValueError as e:
            message = str(e)
            status = 409 if any(x in message for x in ('已变化', '已更新', '重新预览')) else 400
            return reply(status, {'error': message})
        except (sqlite3.Error, OSError):
            return reply(503, {'error': '暂时无法保存或读取，请稍后重试；原数据已保留'})
        finally:
            if c:
                c.close()

    def import_schedule(self, c, member, payload):
        action = payload.get('action', 'preview')
        if action not in ('preview', 'save', 'inspect', 'clear', 'restore', 'remove'):
            raise Problem(400, '操作无效')
        with course_store.transaction(c, write=action in ('save', 'clear', 'restore', 'remove')):
            current = course_store.read_schedule(c, member)
            base = importer.fingerprint(current)
            if action == 'inspect':
                return {'base': base, 'count': len(current['courses'])}
            if action != 'preview' and payload.get('base') != base:
                raise Problem(409, '课表已变化，请重新预览')
            source_version = None
            if action == 'clear':
                result, warnings = {**current, 'courses': [], 'events': []}, []
            elif action == 'remove':
                cid = payload.get('courseId')
                if not isinstance(cid, str) or not any(x['id'] == cid for x in current['courses']):
                    raise Problem(400, '这门课程已不在你的课表中，请刷新后查看')
                result = {**current, 'courses': [x for x in current['courses'] if x['id'] != cid],
                          'events': [e for e in current['events'] if e['course_id'] != cid]}
                warnings = []
            elif action == 'restore':
                result = course_store.read_schedule(c, member, 'previous')
                if result is None:
                    raise Problem(400, '暂无可恢复的上一版')
                warnings = []
            elif 'sourceMember' in payload:
                source_id = payload['sourceMember']
                if type(source_id) is not int or source_id == member or not c.execute('SELECT 1 FROM members WHERE id=? AND shared=1 AND disabled=0', (source_id,)).fetchone():
                    raise Problem(403, '这份课表未开放复制，请重新选择')
                source = course_store.read_schedule(c, source_id)
                if not source['courses']:
                    raise Problem(400, '对方暂无可复制课程')
                source_version = importer.fingerprint(source)
                if action == 'save' and payload.get('sourceVersion') != source_version:
                    raise Problem(409, '对方课表已更新，请重新预览')
                result = {**source, 'owner': member, 'version': 'peer-copy-v1'}
                warnings = ['请核对教学班、日期和教室。复制后独立保存，不会自动跟随对方更新；个人作业不复制，同一教学班的课程作业自动显示。']
            else:
                result, warnings = importer.parse(payload.get('text'), current)
            candidates = result['courses']
            conflicts = []
            if action in ('preview', 'save'):
                result, conflicts, extra = merge.plan(current, result, payload.get('selected'), payload.get('decisions'), payload.get('mode', 'merge'))
                warnings += extra
            if action != 'preview' and current != result:
                course_store.put_schedule(c, member, current, 'previous')
                course_store.put_schedule(c, member, result)
                community.sync(c, member, result, 'import')
                if action == 'remove':
                    community.audit(c, member, 'course-remove', payload['courseId'], {})
            return {'data': result, 'candidates': candidates, 'conflicts': conflicts, 'mode': payload.get('mode', 'merge'), 'warnings': warnings, 'changes': importer.diff_courses(current, result), 'base': base, 'nextBase': importer.fingerprint(result), 'sourceVersion': source_version}


def production():
    return ClassroomApplication(os.environ['KEJIAN_DB'], os.environ['KEJIAN_ORIGIN'], os.environ.get('KEJIAN_BASE', '/mem/'), os.environ.get('KEJIAN_RELEASE', 'classroom-v1'), tuple(x.strip() for x in os.environ.get('KEJIAN_EXTRA_ORIGINS', '').split(',') if x.strip()))
