"""Check tracked source for credential material and private runtime files."""
from pathlib import Path
import ipaddress
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
BLOCKED_PARTS={'.private','state','data','artifacts','.venv','node_modules','__pycache__','.workbuddy','.codebuddy'}
BLOCKED_NAMES={'connection.json','connection-location.json','mcp.json'}
BLOCKED_SUFFIXES={'.sqlite3','.sqlite','.db','.pem','.key','.p12','.pfx','.zip','.gz','.pyc'}
PATTERNS={
    'private-key':re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),
    'github-token':re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{30,})\b'),
    'ai-token':re.compile(r'\bkj_ai_[A-Za-z0-9_-]{40,80}\b'),
    'cloud-access-key':re.compile(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
    'mac-user-path':re.compile('/'+'Users'+r'/[^/\s]+/'),
    'roster-student-id':re.compile(r'\b2266[0-9]{4}\b'),
}
IPV4=re.compile(r'(?<![\w.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![\w.])')


def files():
    result=subprocess.run(['git','ls-files','-z'],cwd=ROOT,text=True,capture_output=True)
    if result.returncode==0 and result.stdout:
        return [Path(p) for p in result.stdout.split('\0') if p]
    return [p.relative_to(ROOT) for p in ROOT.rglob('*') if p.is_file()
            and not ({'.git','.venv','__pycache__','state'}&set(p.relative_to(ROOT).parts))]


def main():
    problems=[];paths=files()
    for relative in paths:
        path=ROOT/relative
        if path.is_symlink() or set(relative.parts)&BLOCKED_PARTS or relative.name in BLOCKED_NAMES or path.suffix in BLOCKED_SUFFIXES or relative.name.startswith('.env') and relative.name!='.env.example':
            problems.append((str(relative),0,'private-file'));continue
        if path.suffix=='.png':continue
        try:text=path.read_text(encoding='utf-8')
        except (UnicodeError,OSError):
            problems.append((str(relative),0,'unexpected-binary'));continue
        for line_no,line in enumerate(text.splitlines(),1):
            for label,pattern in PATTERNS.items():
                if pattern.search(line):problems.append((str(relative),line_no,label))
            for match in IPV4.finditer(line):
                try:address=ipaddress.ip_address(match.group())
                except ValueError:continue
                if address.is_global:problems.append((str(relative),line_no,'public-server-ip'))
    if problems:
        for path,line,label in problems:print(f'{path}:{line}: {label}')
        print('检查未通过；仅报告位置和类型，不输出疑似凭据。')
        return 1
    print(f'公开源码检查通过：{len(paths)} 个文件。真实资料和运行状态仍应由贡献者人工核对。')
    return 0


if __name__=='__main__':sys.exit(main())
