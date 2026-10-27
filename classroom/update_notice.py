"""One acknowledged feature introduction per account, with bounded storage."""
import time
from . import course_store

NOTICE={
    'id':'reminders-20261025',
    'eyebrow':'消息提醒 · 当前仅支持 iOS',
    'title':'课间会主动找你啦',
    'lead':'上课前、作业发布时、截止前，让课间轻轻提醒你。少惦记一点，安心一点。',
    'features':['上课前提醒','新作业提醒','截止前提醒'],
    'steps':[
        ['放到桌面','用 Safari 打开课间，点分享，再选“添加到主屏幕”。'],
        ['找到消息提醒','从桌面的课间打开“更多 → 消息提醒”。'],
        ['轻轻一开','开启“这台设备的提醒”，并允许系统通知。搞定！'],
    ],
    'footnote':'当前仅支持 iOS（iPhone / iPad）；只提醒你自己的课和作业。',
}

def schema(c):
    c.execute('''CREATE TABLE IF NOT EXISTS member_update_notices(
        member INTEGER PRIMARY KEY REFERENCES members(id) ON DELETE CASCADE,
        notice TEXT NOT NULL, dismissed_at INTEGER NOT NULL)''')

def current(c,member):
    row=c.execute('SELECT notice FROM member_update_notices WHERE member=?',(member,)).fetchone()
    return {'notice':NOTICE,'seen':bool(row and row['notice']==NOTICE['id'])}

def dismiss(c,member,body):
    if set(body)!={'owner','notice'} or body['notice']!=NOTICE['id']:
        raise ValueError('更新介绍已变化，请刷新后再试。')
    with course_store.transaction(c,write=True):
        c.execute('''INSERT INTO member_update_notices VALUES(?,?,?)
            ON CONFLICT(member) DO UPDATE SET notice=excluded.notice,dismissed_at=excluded.dismissed_at''',
            (member,NOTICE['id'],int(time.time())))
    return {'ok':True}
