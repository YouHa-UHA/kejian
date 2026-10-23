"""Local administrator tools; no roster or secret is printed to stdout."""
import argparse
import csv
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3

from .app import provision, connect, initialize
from . import community, course_store


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--db',required=True)
    sub=p.add_subparsers(dest='action',required=True)
    roster=sub.add_parser('roster')
    roster.add_argument('csv',help='UTF-8 CSV with 学号,姓名 or student,name headers')
    roster.add_argument('--codes',help='new private activation CSV; never publish it')
    roster.add_argument('--default-password-file',help='use a private file to initialize only new accounts')
    backup=sub.add_parser('backup');backup.add_argument('--output',required=True)
    admin=sub.add_parser('admin');admin.add_argument('student');admin.add_argument('--remove',action='store_true')
    args=p.parse_args()
    os.umask(0o077)
    if args.action=='roster':
        with open(args.csv,encoding='utf-8-sig',newline='') as f:
            rows=[{'student':r.get('学号',r.get('student','')),'name':r.get('姓名',r.get('name',''))} for r in csv.DictReader(f)]
        if args.default_password_file:
            if args.codes:p.error('初始密码与开通码模式不能同时使用')
            result=provision(args.db,rows,Path(args.default_password_file).read_text().strip())
            print(f'名单核对完成：输入{len(rows)}人，新增{len(result)}人；初始密码已设置，已有账号和数据保持原样。')
        else:
            if not args.codes:p.error('请选择初始密码文件或开通码输出文件')
            target=Path(args.codes)
            if target.exists():p.error('开通码输出文件已存在，请换新路径，避免覆盖')
            # Reserve output first so a failed file creation never loses activation codes.
            with target.open('x',encoding='utf-8-sig',newline='') as f:
                result=provision(args.db,rows)
                out=csv.DictWriter(f,fieldnames=['student','name','activation']);out.writeheader();out.writerows(result);f.flush();os.fsync(f.fileno())
            print(f'名单核对完成：输入{len(rows)}人，新增{len(result)}人；已有账号和数据保持原样。开通码已写入指定私密文件。')
    elif args.action=='admin':
        if not Path(args.db).is_file():p.error('数据库不存在')
        initialize(args.db)
        with connect(args.db) as c,course_store.transaction(c,write=True):
            row=c.execute('SELECT id FROM members WHERE student=? AND disabled=0',(args.student,)).fetchone()
            if not row:p.error('账号不存在')
            if args.remove:
                if c.execute('SELECT count(*) FROM class_admins').fetchone()[0]<=1:p.error('不能移除最后一位管理员')
                c.execute('DELETE FROM class_admins WHERE member=?',(row['id'],))
            else:c.execute('INSERT OR IGNORE INTO class_admins VALUES(?)',(row['id'],))
            community.audit(c,None,'admin-remove' if args.remove else 'admin-add',row['id'],{})
        print('管理员权限已更新')
    else:
        if not Path(args.db).is_file():p.error('源数据库不存在')
        target=Path(args.output)
        if target.exists():p.error('备份目标已存在')
        with connect(args.db) as source, sqlite3.connect(target) as dest:
            source.backup(dest)
            if dest.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('备份校验失败')
        target.chmod(0o600);print('数据库备份及完整性校验完成')


if __name__=='__main__':main()
