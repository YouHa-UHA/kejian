"""One extraction rulebook for web import, connected assistants and ZIP snapshots."""
import hashlib
from pathlib import Path


WORKFLOW='''用户可以直接把学校「我的课程」页面交给你，要求导入课间，不必先打开网页导入功能。
先按 extractionPrompt 提取课程；该提示词的 JSON 是内部中间数据，不是连接助手的最终回复格式。仅有链接但无法读取学校登录后的内容时，索取复制文字、网页文件或截图，不索取学校密码。
POST /timetable-import 使用 {action:"preview",text:完整标记JSON,mode:"merge"}，预览不保存。结合 candidates、conflicts、warnings、changes 核对：相同课程不重复；未出现课程保留；教学班缺失只作为个人课程，不按课程名订阅。
无歧义且用户已明确要求导入时，可以直接保存；有日期或教学班歧义、已有安排变化时，先询问有变化的部分，不能替用户猜选 incoming。未确定安排保留待确认，不补造日期、老师或地点。
保存使用 {action:"save",text,mode:"merge",base:最新预览base,selected:选中教学班编号,decisions:逐门keep或incoming} 和稳定 Idempotency-Key。整学期替换、清空、恢复只在用户明确要求后操作。409 回读重新预览，不直接重试覆盖。
保存后 GET /schedule 回读核对，简短说明新增、更新和待确认内容，不要求用户把 JSON 再复制进网页。'''


def document():
    text=Path(__file__).with_name('course-import-guide.txt').read_text(encoding='utf-8').strip()
    revision=hashlib.sha256((text+'\n'+WORKFLOW).encode()).hexdigest()
    return {'revision':revision,'source':'学校「我的课程」页面及原始备注',
            'extractionPrompt':text,'workflow':WORKFLOW}


def snapshot():
    value=document()
    return '课间课程导入规则（离线快照，执行时优先读取在线 /import-guide）\n\n'+value['workflow']+'\n\n'+value['extractionPrompt']+'\n'
