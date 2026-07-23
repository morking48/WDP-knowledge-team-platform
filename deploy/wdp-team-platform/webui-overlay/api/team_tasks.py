"""
WDP 团队工作台 · 主 Agent 定时任务管理（team_tasks）.

设计：
  - 任务配置存 knowledge 同级的 team-tasks.json（部署时放共享卷 PVC，多副本读同一份）
  - 4 个内置任务（确定性脚本逻辑，复用 main_agent_tasks 的实现）：
      signal-clean / stagnant-req / weekly-report / session-archive
  - 支持 admin 新建「自定义任务」：一段自然语言 prompt（记录 + 预留接主 Agent 执行）
  - 每个任务：enabled(默认 false) / schedule(cron) / params / last_run / last_result

  Q1=C：内置任务可调参数 + 自定义 prompt 任务
  Q2=A：由 web-ui 内置调度线程执行（见 team_scheduler.py）

  admin 操作：列表 / 开关 / 改 schedule / 改参数或 prompt / 立即运行一次 / 删除自定义任务
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# 任务配置文件（放 knowledge 根同级，随 knowledge 卷持久化）
_TASKS_FILENAME = 'team-tasks.json'


def _tasks_path() -> Path | None:
    from api import knowledge as _kb
    root = _kb.get_knowledge_root()
    if not root:
        return None
    # 放 knowledge 根目录下（随 PVC 持久化 + git 可忽略）
    return root / _TASKS_FILENAME


# ── 内置任务定义（默认 schedule 参考设计文档）───────────────────────────────
_BUILTIN = {
    'signal-clean': {
        'name': '信号定时清洗',
        'desc': '扫 signals/ 里待 triage 的信号，输出提醒清单到 tracking/',
        'schedule': '0 9 * * *',        # 每天 9:00
        'builtin': True,
        'params': {},
    },
    'stagnant-req': {
        'name': '需求停滞提醒',
        'desc': '扫 requirements/ 里 N 天无更新的需求，输出停滞清单',
        'schedule': '0 10 * * *',       # 每天 10:00
        'builtin': True,
        'params': {'stale_days': 7},
    },
    'weekly-report': {
        'name': '需求流转周报',
        'desc': '汇总知识库总量+状态分布，生成 tracking/weekly-*.md',
        'schedule': '0 18 * * 5',       # 每周五 18:00
        'builtin': True,
        'params': {},
    },
    'session-archive': {
        'name': 'session 压缩归档',
        'desc': '扫 profiles 里 ≥30 天未活跃的 session，输出归档候选',
        'schedule': '0 3 * * 0',        # 每周日 3:00
        'builtin': True,
        'params': {'threshold_days': 30},
    },
    'upload-review': {
        'name': '上传文件处置提醒',
        'desc': '扫各成员对话上传的临时文件，通知管理员处置（尤其未转化进工作台的）',
        'schedule': '0 19 * * *',       # 每天 19:00
        'builtin': True,
        'params': {'stale_days': 3},
    },
    'purge-deleted': {
        'name': '清理已删除内容',
        'desc': '真删 library/archive/_deleted/ 里超过 N 天的软删除文件（R6）',
        'schedule': '0 4 * * *',        # 每天 4:00
        'builtin': True,
        'params': {'retention_days': 30},
    },
}


def _default_config() -> dict:
    """首次生成的默认配置：4 个内置任务，全部 enabled=false。"""
    tasks = []
    for tid, spec in _BUILTIN.items():
        tasks.append({
            'id': tid,
            'name': spec['name'],
            'desc': spec['desc'],
            'type': 'builtin',
            'enabled': False,           # 默认关闭（用户要求）
            'schedule': spec['schedule'],
            'params': dict(spec['params']),
            'prompt': '',
            'last_run': None,
            'last_result': None,
            'last_status': None,
        })
    return {'version': 1, 'tasks': tasks}


def load_config() -> dict:
    """读任务配置；不存在则生成默认（4 内置任务全关）。"""
    p = _tasks_path()
    if not p:
        return _default_config()
    if not p.is_file():
        cfg = _default_config()
        try:
            p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception as e:
            logger.warning('write default team-tasks.json failed: %s', e)
        return cfg
    try:
        cfg = json.loads(p.read_text(encoding='utf-8'))
        # 补齐：确保 4 个内置任务都在（升级兼容）
        have = {t['id'] for t in cfg.get('tasks', [])}
        for tid, spec in _BUILTIN.items():
            if tid not in have:
                cfg.setdefault('tasks', []).append({
                    'id': tid, 'name': spec['name'], 'desc': spec['desc'],
                    'type': 'builtin', 'enabled': False, 'schedule': spec['schedule'],
                    'params': dict(spec['params']), 'prompt': '',
                    'last_run': None, 'last_result': None, 'last_status': None,
                })
        return cfg
    except Exception as e:
        logger.warning('load team-tasks.json failed: %s', e)
        return _default_config()


def save_config(cfg: dict) -> bool:
    p = _tasks_path()
    if not p:
        return False
    try:
        p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
        return True
    except Exception as e:
        logger.warning('save team-tasks.json failed: %s', e)
        return False


def list_tasks() -> dict:
    cfg = load_config()
    return {'tasks': cfg.get('tasks', []), 'scheduler_enabled': _scheduler_enabled()}


def _find_task(cfg: dict, tid: str) -> dict | None:
    for t in cfg.get('tasks', []):
        if t.get('id') == tid:
            return t
    return None


def _valid_cron(expr: str) -> bool:
    """简单校验 5 段 cron。"""
    if not expr or len(expr.split()) != 5:
        return False
    try:
        from croniter import croniter
        return croniter.is_valid(expr)
    except Exception:
        # croniter 不可用时只做段数校验
        return len(expr.split()) == 5


def update_task(tid: str, updates: dict) -> dict:
    """更新任务：enabled / schedule / params / prompt / name / desc。"""
    cfg = load_config()
    t = _find_task(cfg, tid)
    if not t:
        return {'error': f'任务不存在 {tid}'}, 404
    if 'schedule' in updates:
        sch = (updates['schedule'] or '').strip()
        if not _valid_cron(sch):
            return {'error': f'非法 cron 表达式：{sch}（需 5 段，如 0 9 * * *）'}, 400
        t['schedule'] = sch
    for k in ['enabled', 'name', 'desc', 'prompt']:
        if k in updates:
            t[k] = updates[k]
    if 'params' in updates and isinstance(updates['params'], dict):
        t['params'] = updates['params']
    save_config(cfg)
    return {'ok': True, 'task': t}


def create_custom_task(name: str, schedule: str, prompt: str) -> dict:
    """新建自定义任务（自然语言 prompt，预留接主 Agent）。"""
    if not name or not prompt:
        return {'error': '名称和 prompt 必填'}, 400
    if not _valid_cron(schedule):
        return {'error': f'非法 cron：{schedule}'}, 400
    cfg = load_config()
    tid = 'custom-' + str(int(time.time()))
    task = {
        'id': tid, 'name': name, 'desc': '自定义任务（自然语言）',
        'type': 'custom', 'enabled': False, 'schedule': schedule,
        'params': {}, 'prompt': prompt,
        'last_run': None, 'last_result': None, 'last_status': None,
    }
    cfg.setdefault('tasks', []).append(task)
    save_config(cfg)
    return {'ok': True, 'task': task}


def delete_task(tid: str) -> dict:
    cfg = load_config()
    t = _find_task(cfg, tid)
    if not t:
        return {'error': '任务不存在'}, 404
    if t.get('type') == 'builtin':
        return {'error': '内置任务不可删除（可停用）'}, 400
    cfg['tasks'] = [x for x in cfg.get('tasks', []) if x.get('id') != tid]
    save_config(cfg)
    return {'ok': True}


# ── 任务执行 ────────────────────────────────────────────────────────────────
def _run_custom_llm(prompt: str) -> str:
    """R20：自定义任务真跑 LLM——用团队 key + 默认模型调 OpenRouter。

    任务上下文注入：给 LLM 提供工作台知识库摘要，让它能基于真实数据分析。
    """
    if not prompt.strip():
        return '[自定义任务] prompt 为空，跳过'
    try:
        from api.merge_agent import _team_key_and_model
        key, model, _ = _team_key_and_model()
    except Exception as e:
        return f'[自定义任务] 读取团队模型配置失败：{e}'
    if not key:
        return '[自定义任务] 团队未配置 OpenRouter Key，无法执行（部署时配置团队 key 后自动生效）'

    # 注入工作台数据摘要，让自定义任务能基于真实知识库分析
    context = ''
    try:
        from api import knowledge as _kb
        stats = _kb.get_stats()
        cats = stats.get('categories', {})
        context = '当前工作台数据概况：' + '，'.join(
            f'{k} {v.get("active_count", v.get("count", 0))} 条' for k, v in cats.items() if v.get('count'))
    except Exception:
        pass

    import json as _json
    import urllib.request as _ur
    full_prompt = (f'{prompt}\n\n---\n{context}\n' if context else prompt)
    try:
        body = _json.dumps({
            'model': model,
            'messages': [{'role': 'user', 'content': full_prompt}],
            'temperature': 0.4,
            'max_tokens': 1500,
        }).encode('utf-8')
        req = _ur.Request('https://openrouter.ai/api/v1/chat/completions', data=body,
                          headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json',
                                   'HTTP-Referer': 'https://wdp-team-workbench', 'X-Title': 'WDP Custom Task'})
        with _ur.urlopen(req, timeout=90) as resp:
            data = _json.loads(resp.read().decode('utf-8'))
        return data['choices'][0]['message']['content']
    except Exception as e:
        return f'[自定义任务] LLM 调用失败：{e}'


def run_task(tid: str, *, triggered_by: str = 'manual') -> dict:
    """执行一个任务，记录 last_run/last_result。返回执行摘要。"""
    cfg = load_config()
    t = _find_task(cfg, tid)
    if not t:
        return {'error': f'任务不存在 {tid}'}, 404

    result_text = ''
    status = 'ok'
    try:
        if t.get('type') == 'builtin':
            result_text = _run_builtin(tid, t.get('params') or {})
        else:
            # R20：自定义 prompt 任务真跑 LLM（团队 key + 默认模型）
            result_text = _run_custom_llm(t.get('prompt') or '')
    except Exception as e:
        result_text = f'执行异常：{e}'
        status = 'error'
        logger.warning('run_task %s failed: %s', tid, e)

    t['last_run'] = time.strftime('%Y-%m-%d %H:%M:%S')
    t['last_result'] = result_text[:2000]
    t['last_status'] = status
    t['last_trigger'] = triggered_by
    save_config(cfg)
    return {'ok': status != 'error', 'status': status, 'result': result_text, 'ran_at': t['last_run']}


def _run_builtin(tid: str, params: dict) -> str:
    """执行内置任务，复用 main_agent_tasks 的确定性逻辑（在进程内实现，避免依赖外部脚本路径）。"""
    from api import knowledge as _kb
    root = _kb.get_knowledge_root()
    if not root:
        return 'knowledge 根不可用'
    tracking = root / 'tracking'
    tracking.mkdir(exist_ok=True)
    today = time.strftime('%Y-%m-%d')
    now = time.time()

    def scan(cat):
        out = []
        d = root / _kb.get_categories().get(cat, cat)
        if d.is_dir():
            for f in sorted(d.glob('*.md')):
                if f.name.startswith('_'):
                    continue
                try:
                    meta, _ = _kb.parse_frontmatter(f.read_text(encoding='utf-8'))
                    out.append((f, meta))
                except Exception:
                    pass
        return out

    if tid == 'signal-clean':
        pending = [{'id': m.get('id', '?'), 'title': m.get('title', ''),
                    'urgency': m.get('urgency', '?'), 'date': m.get('date', '?')}
                   for f, m in scan('signals')
                   if m.get('status') in ('待triage', '待确认', '')]
        (tracking / 'signal-clean-latest.json').write_text(
            json.dumps({'ran_at': today, 'pending_count': len(pending), 'pending': pending},
                       ensure_ascii=False, indent=2), encoding='utf-8')
        lines = [f"发现 {len(pending)} 条待 triage 信号："]
        lines += [f"  [{p['urgency']}] {p['id']} · {p['title']}" for p in pending]
        return '\n'.join(lines)

    if tid == 'stagnant-req':
        stale_days = int(params.get('stale_days', 7))
        stale = []
        for f, m in scan('requirements'):
            if m.get('status') in ('已上线', '已关闭'):
                continue
            days = (now - f.stat().st_mtime) / 86400
            if days >= stale_days:
                stale.append({'id': m.get('id', '?'), 'title': m.get('title', ''),
                              'owner': m.get('owner', '未分配'), 'status': m.get('status', '?'),
                              'stale_days': int(days)})
        (tracking / 'stagnant-req-latest.json').write_text(
            json.dumps({'ran_at': today, 'stale_days_threshold': stale_days,
                        'stale_count': len(stale), 'stale': stale},
                       ensure_ascii=False, indent=2), encoding='utf-8')
        lines = [f"发现 {len(stale)} 条停滞需求（≥{stale_days} 天）："]
        lines += [f"  [{s['stale_days']}d] {s['id']} · {s['title']} (@{s['owner']})" for s in stale]
        return '\n'.join(lines)

    if tid == 'weekly-report':
        stats = {}
        dist = {}
        for cat in ['signals', 'requirements', 'designs']:
            items = scan(cat)
            stats[cat] = len(items)
            for _, m in items:
                key = f"{cat}/{m.get('status', '未标注')}"
                dist[key] = dist.get(key, 0) + 1
        rep = [f'# WDP 团队工作台 · 周报 ({today})', '', '## 知识库总量',
               f"- 信号：{stats.get('signals', 0)}",
               f"- 需求：{stats.get('requirements', 0)}",
               f"- 设计稿：{stats.get('designs', 0)}", '', '## 状态分布']
        rep += [f'- {k}: {v}' for k, v in sorted(dist.items())]
        rep += ['', '> 由主 Agent 定时任务自动生成。']
        report = '\n'.join(rep)
        out = tracking / f"weekly-{time.strftime('%Y%m%d')}.md"
        out.write_text(report, encoding='utf-8')
        return f'周报已生成：tracking/{out.name}\n\n' + report

    if tid == 'session-archive':
        threshold = int(params.get('threshold_days', 30))
        try:
            from api.profiles import _DEFAULT_HERMES_HOME
            profiles_dir = Path(_DEFAULT_HERMES_HOME) / 'profiles'
        except Exception:
            profiles_dir = None
        archived = []
        if profiles_dir and profiles_dir.is_dir():
            for ud in profiles_dir.iterdir():
                if not ud.is_dir():
                    continue
                for sd in [ud / 'sessions', ud / 'webui' / 'sessions']:
                    if sd.is_dir():
                        for s in sd.glob('*.json'):
                            if s.name.startswith('_'):
                                continue
                            days = (now - s.stat().st_mtime) / 86400
                            if days >= threshold:
                                archived.append({'user': ud.name, 'session': s.name,
                                                 'days_inactive': int(days)})
        (tracking / 'session-archive-candidates.json').write_text(
            json.dumps({'ran_at': today, 'threshold_days': threshold, 'candidates': archived},
                       ensure_ascii=False, indent=2), encoding='utf-8')
        return f'发现 {len(archived)} 个 ≥{threshold} 天未活跃 session（候选，未实际移动）'

    if tid == 'upload-review':
        # P3：扫各成员 workspace/uploads 里的临时文件，通知管理员处置
        stale_days = int(params.get('stale_days', 3))
        try:
            from api.profiles import _DEFAULT_HERMES_HOME
            base = Path(_DEFAULT_HERMES_HOME)
        except Exception:
            base = None
        pending = []
        if base:
            # 各成员 profile 的 uploads + default(admin) 的 uploads
            search_dirs = []
            pd = base / 'profiles'
            if pd.is_dir():
                for ud in pd.iterdir():
                    if ud.is_dir():
                        search_dirs.append((ud.name, ud / 'workspace' / 'uploads'))
            search_dirs.append(('admin', base / 'workspace' / 'uploads'))
            for user, ud in search_dirs:
                if ud.is_dir():
                    for f in ud.rglob('*'):
                        if f.is_file() and not f.name.startswith('.'):
                            age = (now - f.stat().st_mtime) / 86400
                            pending.append({'user': user, 'file': f.name,
                                            'size': f.stat().st_size, 'age_days': int(age),
                                            'stale': age >= stale_days})
        stale_cnt = sum(1 for p in pending if p['stale'])
        (tracking / 'upload-review-latest.json').write_text(
            json.dumps({'ran_at': today, 'stale_days': stale_days,
                        'total': len(pending), 'stale_count': stale_cnt, 'files': pending},
                       ensure_ascii=False, indent=2), encoding='utf-8')
        # 通知所有管理员
        if pending:
            try:
                from api import knowledge_ops as _ops
                from api import users as _users
                msg = f'📎 上传文件处置提醒：共 {len(pending)} 个临时文件待处置，其中 {stale_cnt} 个已超 {stale_days} 天未转化进工作台。请到成员管理查看清单。'
                for u in _users.list_users():
                    if u.get('role') == 'admin':
                        _ops.notify_member(u.get('username'), msg, 'system')
            except Exception as e:
                logger.debug('upload-review notify failed: %s', e)
        lines = [f'扫描到 {len(pending)} 个上传临时文件，{stale_cnt} 个超 {stale_days} 天未处置：']
        lines += [f"  [{p['age_days']}d] {p['user']}/{p['file']}" for p in pending if p['stale']][:20]
        return '\n'.join(lines)

    if tid == 'purge-deleted':
        from api import knowledge_ops as _ops
        r = _ops.purge_expired_deleted(int(params.get('retention_days', 30)))
        return f"清理已删除内容：真删 {r.get('purged',0)} 个超期文件"

    return f'未知内置任务 {tid}'


def _scheduler_enabled() -> bool:
    """本地默认启用调度线程；线上用 WDP_SCHEDULER_ENABLED 单点控制。"""
    v = os.getenv('WDP_SCHEDULER_ENABLED', '').strip().lower()
    if v in ('0', 'false', 'no'):
        return False
    return True  # 默认开（本地）；线上多副本时用 =0 关掉非主 Pod
