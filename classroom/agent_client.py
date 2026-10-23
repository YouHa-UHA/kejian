#!/usr/bin/env python3
"""Standalone Kejian AI client. Standard library only; never prints credentials."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request


def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


BOOTSTRAP_PROTOCOL = 1
CLIENT_VERSION = '2.0.0'
MAX_RESPONSE = 4 * 1024 * 1024


def sha(value):return hashlib.sha256(value).hexdigest()


def private_dir(path):
    """Only touch directories belonging to the integration, never follow links."""
    if path.is_symlink():raise RuntimeError('课间更新目录不能是符号链接。')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.is_dir():raise RuntimeError('课间更新目录不可用。')
    path.chmod(0o700)


def atomic(path, data):
    if path.is_symlink():raise RuntimeError('课间管理文件不能是符号链接。')
    if path.exists() and path.read_bytes()==data:
        if os.name!='nt' and path.stat().st_mode & 0o077:path.chmod(0o600)
        return
    fd, name = tempfile.mkstemp(prefix='.kejian-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as out:
            os.chmod(name,0o600);out.write(data);out.flush();os.fsync(out.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        raise RuntimeError('接口发生重定向，已停止发送凭据；请核对连接地址。')


class ApiError(RuntimeError):
    def __init__(self,message,response):
        super().__init__(message)
        self.response=response


class Client:
    def __init__(self,path):
        file=Path(path).resolve()
        if os.name!='nt' and file.stat().st_mode & 0o077:
            raise RuntimeError('连接配置须仅本人可读写，请先执行 chmod 600 connection.json。')
        config=json.loads(file.read_text(encoding='utf-8'))
        self.base=config.get('apiBase','').rstrip('/');self.token=config.get('token','')
        value=urllib.parse.urlsplit(self.base)
        local=value.hostname in ('localhost','127.0.0.1','::1')
        if (value.scheme!='https' and not (local and value.scheme=='http')) or not value.netloc or value.username or value.password or value.query or value.fragment or not value.path.endswith('/api/agent/v1'):
            raise RuntimeError('连接地址无效：正式环境需要HTTPS，本地只允许回环地址。')
        if config.get('environment')!=('local' if local else 'production'):
            raise RuntimeError('连接配置与本地/正式环境标识不匹配。')
        if not isinstance(self.token,str) or not re.fullmatch(r'kj_ai_[A-Za-z0-9_-]{40,80}',self.token):
            raise RuntimeError('连接资料格式无效，请从账号页重新生成。')
        self.connection=config.get('connectionId')
        if not isinstance(self.connection,str) or not self.connection:raise RuntimeError('连接编号无效。')
        self.config_path=file
        self.binding=sha(canonical({'apiBase':self.base,'connectionId':self.connection,'credentialHash':sha(self.token.encode())}).encode())
        private_dir(file.parent/'.kejian')
        self.state=file.parent/'.kejian'/self.binding
        private_dir(self.state)
        self.transport=urllib.request.build_opener(NoRedirect())
        self.context=None
        self.versions={}
        self.notices=[]
        self._load_cache()

    def _validate_context(self,update,versions):
        caps=update['capabilities'];doc=update['openapi'];guide=update['guide']
        if sha(canonical(doc).encode())!=guide['openapiSha256']:
            raise RuntimeError('接口文档与指南不一致，请稍后重新核对。')
        if caps['apiVersion']!='kejian-agent-v1' or caps['apiVersion']!=doc['info']['version']:
            raise RuntimeError('接口与指南版本不一致。')
        skill=update.get('skill')
        if skill and sha(skill['text'].encode())!=skill['revision']:
            raise RuntimeError('Skill文件校验失败，已保留原文件。')
        if versions:
            for key,value in [('permissions',sha(canonical(caps).encode())),('guide',sha(guide['text'].encode())),('skill',skill['revision'] if skill else '')]:
                if key in versions and value!=versions[key]:raise RuntimeError('操作规则版本不一致，请重新同步。')

    def _load_cache(self):
        try:
            path=self.state/'context.json'
            if path.is_symlink() or path.stat().st_size>MAX_RESPONSE:raise ValueError()
            cached=json.loads(path.read_text(encoding='utf-8'))
            if cached['binding']!=self.binding:raise ValueError()
            self._validate_context(cached['updates'],cached['versions'])
            self.context=cached['updates'];self.versions=cached['versions']
        except (OSError,ValueError,KeyError,TypeError,RuntimeError):
            self.context=None;self.versions={}

    def _targets(self):
        targets=[]
        package_skill=self.config_path.parent/'skills'/'kejian'
        if package_skill.exists():targets.append(package_skill)
        try:targets += [Path(x) for x in json.loads((self.state/'skill-targets.json').read_text())]
        except (OSError,ValueError,TypeError):pass
        return list(dict.fromkeys(targets))

    def _sync_target(self,target):
        marker=target/'.kejian-managed.json'
        try:managed=json.loads(marker.read_text())
        except (OSError,ValueError):return False
        if managed.get('binding')!=self.binding:return False
        skill=target/'SKILL.md';latest=self.context['skill']
        if target.is_symlink() or marker.is_symlink() or skill.is_symlink():raise RuntimeError('Skill目录不能使用符号链接。')
        if skill.exists() and sha(skill.read_bytes()) not in (managed.get('revision'),latest['revision']):
            self.notices.append('已取得最新规则，但本地Skill有手动修改，未覆盖；请合并本地修改。')
            return False
        atomic(skill,latest['text'].encode())
        atomic(marker,(canonical({'binding':self.binding,'revision':latest['revision'],'managedBy':'kejian'})+'\n').encode())
        return True

    def _save_local(self):
        if not self.context:return
        try:
            atomic(self.state/'AGENT-GUIDE.txt',self.context['guide']['text'].encode())
            atomic(self.state/'openapi.json',(canonical(self.context['openapi'])+'\n').encode())
            if self.context.get('skill'):
                skill_dir=self.state/'skills';private_dir(skill_dir)
                skill_dir=skill_dir/'kejian';private_dir(skill_dir)
                atomic(skill_dir/'SKILL.md',self.context['skill']['text'].encode())
                for target in self._targets():self._sync_target(target)
            atomic(self.state/'context.json',(canonical({'binding':self.binding,'versions':self.versions,'updates':self.context})+'\n').encode())
        except (OSError,RuntimeError):
            self.notices.append('已取得在线规则，但本地文件暂时无法同步；请检查连接目录的写入权限。')

    def install_skill(self,directory):
        """Explicit, host-scoped installation; subsequent updates stay managed."""
        self.refresh()
        target=Path(directory).expanduser().absolute()
        if target.name!='kejian' or target.is_symlink():raise RuntimeError('请选择助手技能目录下的kejian文件夹。')
        if target.exists() and any(target.iterdir()):
            try:owned=json.loads((target/'.kejian-managed.json').read_text())['binding']==self.binding
            except (OSError,ValueError,KeyError):owned=False
            if not owned:raise RuntimeError('这个位置已有其他Skill或连接，未覆盖；请选择项目级技能目录。')
        private_dir(target)
        if not (target/'.kejian-managed.json').exists():
            atomic(target/'.kejian-managed.json',(canonical({'binding':self.binding,'revision':self.context['skill']['revision'],'managedBy':'kejian'})+'\n').encode())
        if not self._sync_target(target):raise RuntimeError('本地Skill有修改，请先合并后再安装。')
        # Paths only, never a credential. Relative paths in the package also work.
        atomic(target/'connection-location.json',(canonical({'client':str(self.config_path.parent/'kejian_client.py'),'config':str(self.config_path)})+'\n').encode())
        targets=self._targets()+[target]
        atomic(self.state/'skill-targets.json',(canonical(list(dict.fromkeys(str(x) for x in targets)))+'\n').encode())
        return {'installed':True,'directory':str(target)}

    def prepare_runtime(self):
        """Stage a checked release, then atomically select it before any write."""
        expected=self.context.get('client')
        if not expected:raise RuntimeError('服务器未提供客户端更新信息。')
        if expected.get('apiVersion')!='kejian-agent-v1' or expected.get('bootstrapProtocol')!=BOOTSTRAP_PROTOCOL:
            raise RuntimeError('新版连接需要更新启动器，请让助手读取在线接入指南；原密钥无需更换。')
        metadata={k:v for k,v in expected.items() if k not in ('revision','path')}
        if sha(canonical(metadata).encode())!=expected.get('revision') or expected.get('path')!='/client-release':
            raise RuntimeError('客户端更新清单校验失败，未运行更新。')
        entries=expected.get('files')
        if not isinstance(entries,list) or len(entries)!=1 or entries[0].get('path')!='kejian_runtime.py':
            raise RuntimeError('客户端更新包含不支持的文件，未运行更新。')
        entry=entries[0];checksum=entry.get('sha256','')
        if not re.fullmatch('[0-9a-f]{64}',checksum) or type(entry.get('size')) is not int or not 0<entry['size']<=512*1024:
            raise RuntimeError('客户端更新大小或摘要无效。')
        current=Path(__file__)
        if sha(current.read_bytes())==checksum:return current
        folder=self.state/'runtime';private_dir(folder)
        target=folder/(checksum+'.py')
        if target.is_symlink():raise RuntimeError('客户端更新文件不能是符号链接。')
        if not target.exists() or sha(target.read_bytes())!=checksum:
            release=self._request('GET','/client-release')['data']
            if {k:v for k,v in release.items() if k!='sources'}!=expected:
                raise RuntimeError('客户端发布已变化，请重新执行本次任务；尚未写入数据。')
            if set(release.get('sources',{}))!={'kejian_runtime.py'}:
                raise RuntimeError('客户端更新文件不完整。')
            source=release['sources']['kejian_runtime.py'].encode()
            if len(source)!=entry['size'] or sha(source)!=checksum:
                raise RuntimeError('客户端下载校验失败，已保留原版本；尚未写入数据。')
            try:compile(source,str(target),'exec')
            except SyntaxError:raise RuntimeError('客户端更新无法加载，已保留原版本。') from None
            atomic(target,source)
        return target

    def activate_runtime(self,target):
        # The stable launcher calls this only after import and Client construction.
        expected=self.context['client'];checksum=expected['files'][0]['sha256']
        if sha(target.read_bytes())!=checksum:raise RuntimeError('运行文件在加载时发生变化，未切换版本。')
        atomic(self.state/'active-runtime.json',(canonical({'sha256':checksum,'revision':expected['revision']})+'\n').encode())

    def request(self,method,path,payload=None,key=None):
        parsed=urllib.parse.urlsplit(path)
        if parsed.scheme or parsed.netloc or parsed.fragment or not parsed.path.startswith('/') or '..' in parsed.path.split('/'):
            raise RuntimeError('只允许连接资料对应API内的相对路径。')
        if any(k in urllib.parse.parse_qs(parsed.query) for k in ('token','access_token','owner','student')):
            raise RuntimeError('查询参数不能包含凭据或自报身份。')
        if method not in ('GET','POST'):raise RuntimeError('仅支持GET和POST。')
        if method=='GET' and payload is not None:raise RuntimeError('GET不接收JSON请求体。')
        if method=='POST' and not key:raise RuntimeError('写入或预览需要 --idempotency-key；重试时保留原键和原请求。')
        if parsed.path=='/discovery' and method=='GET':return self.refresh()
        refreshed=self.refresh()
        result=self._request(method,path,payload,key)
        self._accept(result)
        if 'updates' not in result and refreshed.get('updates'):
            result['updates']=refreshed['updates']
        return result

    def _request(self,method,path,payload=None,key=None):
        headers={'Authorization':'Bearer '+self.token,'Accept':'application/json'}
        if self.versions.get('context'):headers['X-Kejian-Context-Revision']=self.versions['context']
        data=None
        if method=='POST':
            headers.update({'Content-Type':'application/json','Idempotency-Key':key});data=canonical(payload or {}).encode()
        request=urllib.request.Request(self.base+path,data=data,headers=headers,method=method)
        try:
            with self.transport.open(request,timeout=20) as response:
                raw=response.read(MAX_RESPONSE+1)
                if len(raw)>MAX_RESPONSE:raise RuntimeError('课间响应过大，已停止处理。')
                result=json.loads(raw)
        except urllib.error.HTTPError as error:
            try:
                result=json.loads(error.read())
                if not isinstance(result,dict):raise ValueError()
                message=result.get('error','请求失败');code=result.get('code','HTTP_ERROR')
            except (ValueError,UnicodeError):result={};message='接口暂时不可用';code='HTTP_ERROR'
            if isinstance(result,dict):self._accept(result)
            raise ApiError((str(error.code)+' '+code+'：'+message).replace(self.token,'[REDACTED]'),result) from None
        except (urllib.error.URLError,TimeoutError):
            raise RuntimeError('连接失败或结果未知；写入请保留原幂等键和原请求，先回读再重试。') from None
        if not isinstance(result,dict) or result.get('apiVersion')!='kejian-agent-v1' or 'data' not in result:
            raise RuntimeError('接口版本或响应格式不匹配。')
        return result

    def _accept(self,result):
        update=result.get('updates')
        if update:
            self._validate_context(update,result.get('sync',{}).get('versions',{}))
            self.context=update
        versions=result.get('sync',{}).get('versions')
        if versions:
            if result['sync'].get('changed') and not update:
                raise RuntimeError('功能或权限发生变化，请重新同步后核对任务；不要直接重试写入。')
            self.versions=versions
        if self.context:self._save_local()

    def refresh(self):
        result=self._request('GET','/discovery')
        identity=result['data']['identity']
        if self.connection and identity['connection']['id']!=self.connection:
            raise RuntimeError('连接身份与资料包不匹配。')
        self._accept(result)
        if self.context is None:raise RuntimeError('未取得最新操作指南，请重新同步。')
        self._save_local()
        return result

    def connect(self):
        result=self.refresh()
        return {'identity':result['data']['identity'],'capabilities':result['data']['capabilities'],
                'guide':self.context['guide']['text'],'openapi':self.context['openapi'],
                'importGuide':self.context['importGuide'],'skill':self.context.get('skill'),
                'connectionMethods':result['data'].get('connectionMethods',{}),
                'versions':self.versions,'verified':True,'local':self.local_info()}

    def local_info(self):
        result={'clientVersion':CLIENT_VERSION,'skill':str(self.state/'skills'/'kejian'/'SKILL.md'),
                'guide':str(self.state/'AGENT-GUIDE.txt'),'openapi':str(self.state/'openapi.json'),
                'command':[str(self.config_path.parent/'kejian_client.py'),'--config',str(self.config_path)]}
        if self.notices:result['attention']=list(dict.fromkeys(self.notices))
        return result


def main(client=None,pending_updates=None):
    parser=argparse.ArgumentParser(description='课间个人AI接口客户端；凭据只从私密配置文件读取')
    parser.add_argument('--config',required=True,help='私密connection.json路径，不要把密钥放在参数里')
    commands=parser.add_subparsers(dest='command',required=True)
    for name in ('connect','sync','me','capabilities','courses','schedule','import-guide'):commands.add_parser(name)
    sub=commands.add_parser('install-skill');sub.add_argument('--directory',required=True,help='助手支持的技能目录下的kejian文件夹；不修改其他配置')
    for name in ('today','week'):
        sub=commands.add_parser(name);sub.add_argument('--date',help='YYYY-MM-DD；省略按北京时间')
    sub=commands.add_parser('homework');sub.add_argument('--status',choices=['all','pending','done'],default='all');sub.add_argument('--course');sub.add_argument('--due-before')
    sub=commands.add_parser('request');sub.add_argument('method',choices=['GET','POST']);sub.add_argument('path');sub.add_argument('--json-file');sub.add_argument('--idempotency-key')
    args=parser.parse_args()
    try:
        client=client or Client(args.config)
        if args.command=='connect':result=client.connect()
        elif args.command=='install-skill':result=client.install_skill(args.directory)
        elif args.command=='sync':result=client.refresh()
        elif args.command=='request':
            payload=json.loads(Path(args.json_file).read_text(encoding='utf-8')) if args.json_file else None
            result=client.request(args.method,args.path,payload,args.idempotency_key)
        elif args.command=='homework':
            query={'status':args.status}
            if args.course:query['courseId']=args.course
            if args.due_before:query['dueBefore']=args.due_before
            result=client.request('GET','/homework?'+urllib.parse.urlencode(query))
        else:
            path='/'+args.command
            if args.command in ('today','week') and args.date:path+='?'+urllib.parse.urlencode({'date':args.date})
            result=client.request('GET',path)
        if args.command!='connect':
            if pending_updates and 'updates' not in result:result['updates']=pending_updates
            result['local']=client.local_info()
        print(json.dumps(result,ensure_ascii=False,indent=2).replace(client.token,'[REDACTED]'))
    except (RuntimeError,OSError,ValueError,KeyError) as error:
        if isinstance(error,ApiError) and error.response.get('updates'):
            print(json.dumps({'sync':error.response['sync'],'updates':error.response['updates']},ensure_ascii=False).replace(client.token,'[REDACTED]'))
        print('课间连接失败：'+str(error),file=sys.stderr);return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
