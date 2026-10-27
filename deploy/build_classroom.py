"""Package only classroom code/assets; never roster, credentials or personal data."""
import argparse
import hashlib
from pathlib import Path
import tarfile

ROOT=Path(__file__).resolve().parents[1]


def build(target):
    target=Path(target)
    if target.exists():raise ValueError('输出文件已存在')
    files=[ROOT/'production.py',ROOT/'examples/demo-schedule.json',ROOT/'classroom/course-import-guide.txt',ROOT/'classroom/skills/kejian/SKILL.md',
           *sorted((ROOT/'classroom').glob('*.py')),*sorted((ROOT/'public').glob('*'))]
    # Old one-person notification/WeChat experiments must not enter classroom release.
    files=[p for p in files if p.is_file() and not (
        p.parent==ROOT/'public' and p.name.startswith(('reminders.','push-test.','wechat-test.')))]
    with tarfile.open(target,'x:gz') as archive:
        for file in files:archive.add(file,arcname=str(file.relative_to(ROOT)),recursive=False)
    print(hashlib.sha256(target.read_bytes()).hexdigest())


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('output');build(p.parse_args().output)
