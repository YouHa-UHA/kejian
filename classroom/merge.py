"""Safe, per-teaching-class import. Missing courses never mean withdrawal."""
from copy import deepcopy
import re
from . import importer


def term_key(term):
    return re.sub(r'[\s\-–—_/]|学期', '', term)


def same_term(a, b):
    return (term_key(a['term']), a['week_start'], a['display_range']) == (term_key(b['term']), b['week_start'], b['display_range'])


def course_slice(data, cid):
    return {'courses': [c for c in data['courses'] if c['id'] == cid],
            'events': [e for e in data['events'] if e['course_id'] == cid]}


def plan(current, incoming, selected=None, decisions=None, mode='merge'):
    if mode not in ('merge', 'replace'):
        raise ValueError('导入方式无效')
    choices = {c['id'] for c in incoming['courses']}
    if selected is None:
        selected = list(choices)
    if not isinstance(selected, list) or not selected or any(not isinstance(x, str) or x not in choices for x in selected) or len(set(selected)) != len(selected):
        raise ValueError('请至少选择一门有效课程')
    decisions = {} if decisions is None else decisions
    if not isinstance(decisions, dict) or any(k not in selected or v not in ('keep', 'incoming') for k, v in decisions.items()):
        raise ValueError('课程处理方式无效')
    if current['courses'] and not same_term(current, incoming) and mode == 'merge':
        raise ValueError('这份课表属于不同学期或校历，请核对后选择“替换整个学期”')
    old = {c['id']: c for c in current['courses']}
    result = deepcopy(incoming if mode == 'replace' or not current['courses'] else current)
    result['courses'] = [] if mode == 'replace' else deepcopy(current['courses'])
    result['events'] = [] if mode == 'replace' else deepcopy(current['events'])
    conflicts = []
    for course in incoming['courses']:
        cid = course['id']
        if cid not in selected:
            continue
        before = course_slice(current, cid)
        after = course_slice(incoming, cid)
        change = importer.diff_courses(before, after)[0]
        changed = cid in old and change['kind'] == '修改'
        if changed:
            conflicts.append({'id': cid, 'name': course['name'], 'fields': change['fields'],
                              'ambiguous': cid.startswith('import-'),
                              'decision': decisions.get(cid, 'keep' if mode == 'merge' else 'incoming'),
                              'before': before, 'after': after})
        use = cid not in old or mode == 'replace' or (changed and decisions.get(cid) == 'incoming')
        if use:
            result['courses'] = [c for c in result['courses'] if c['id'] != cid] + [deepcopy(course)]
            result['events'] = [e for e in result['events'] if e['course_id'] != cid] + deepcopy(after['events'])
        elif mode == 'replace':
            result['courses'].append(deepcopy(old[cid]))
            result['events'].extend(deepcopy(before['events']))
    result['events'].sort(key=lambda e: (e['date'], e.get('start_time') or '', e['id']))
    # A no-op import does not manufacture a new version or consume the restore slot.
    if same_term(current, result) and all(c['kind'] == '未变化' for c in importer.diff_courses(current, result)):
        result = deepcopy(current)
    else:
        result['version'] = 'safe-import-v3'
    warnings = []
    if any(c['id'].startswith('import-') for c in incoming['courses'] if c['id'] in selected):
        warnings.append('部分课程缺少教学班编号，仅保存在个人课表；不会仅凭课程名称订阅共同课程。')
    if conflicts and mode == 'merge':
        warnings.append('已有课程默认沿用原安排。需要更新时，请逐门选择“使用本次导入”。')
    return result, conflicts, warnings
