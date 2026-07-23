#!/usr/bin/env python3
"""
WDP 团队工作台 · 主 Agent 定时任务集（R7）

用法：
  python3 main_agent_tasks.py <task_name>

任务：
  signal-clean     信号定时清洗（扫 signals/ 待 triage 的，提醒负责人）
  stagnant-req     需求停滞检测（N 天无更新 → 提醒 owner）
  weekly-report    生成需求流转周报（汇总到 tracking/weekly-YYYYMMDD.md）
  session-archive  session 压缩归档（老 session 标注时间/主题/用户）

部署：
  由 K8s CronJob 或主 Agent Pod 内的 crontab 周期调用：
    0 9 * * *    python3 main_agent_tasks.py signal-clean
    0 10 * * *   python3 main_agent_tasks.py stagnant-req
    0 18 * * 5   python3 main_agent_tasks.py weekly-report
    0 3 * * 0    python3 main_agent_tasks.py session-archive

设计约束：
  - 纯标准库，不依赖 hermes 包
  - knowledge/ 路径通过环境变量 HERMES_KNOWLEDGE_DIR（默认 /data/knowledge）
  - profiles/ 路径通过环境变量 HERMES_PROFILES_DIR（默认 /data/profiles）
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

KNOWLEDGE_DIR = Path(os.getenv('HERMES_KNOWLEDGE_DIR', '/data/knowledge'))
PROFILES_DIR = Path(os.getenv('HERMES_PROFILES_DIR', '/data/profiles'))
STALE_DAYS = int(os.getenv('WDP_STALE_DAYS', '7'))  # 需求停滞阈值（天）


# ── frontmatter 解析（复用 web-ui/api/knowledge.py 的极简版）─────────────
_FM_RE = re.compile(r'^---\s*\n(.*?)\n---\s*\n', re.DOTALL)


def parse_fm(text: str) -> tuple[dict, str]:
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    fm_block = m.group(1)
    body = text[m.end():]
    meta = {}
    for line in fm_block.split('\n'):
        if not line.strip() or line.strip().startswith('#'):
            continue
        if not line.startswith((' ', '\t')) and ':' in line:
            k, _, v = line.partition(':')
            meta[k.strip()] = v.strip()
    return meta, body


def scan(category: str) -> list[tuple[Path, dict, str]]:
    """扫描 knowledge/<category>/*.md，返回 [(path, meta, body)]"""
    cat_dir = KNOWLEDGE_DIR / category
    if not cat_dir.is_dir():
        return []
    out = []
    for f in sorted(cat_dir.glob('*.md')):
        if f.name.startswith('_'):
            continue
        try:
            text = f.read_text(encoding='utf-8')
            meta, body = parse_fm(text)
            out.append((f, meta, body))
        except Exception as e:
            print(f'[warn] 读 {f} 失败: {e}', file=sys.stderr)
    return out


# ── T1: 信号定时清洗 ─────────────────────────────────────────────────────
def task_signal_clean():
    """扫 signals/ 里 status=待triage 的，输出提醒清单。"""
    pending = []
    for path, meta, _ in scan('signals'):
        if meta.get('status') in ('待triage', '待确认', ''):
            pending.append({
                'file': path.name,
                'id': meta.get('id', '?'),
                'title': meta.get('title', '(无标题)'),
                'urgency': meta.get('urgency', '?'),
                'date': meta.get('date', '?'),
            })
    print(f'[signal-clean] 发现 {len(pending)} 条待 triage 信号：')
    for p in pending:
        print(f"  [{p['urgency']}] {p['id']} · {p['title']} ({p['date']})")
    # 写到 tracking/signal-clean-latest.json 供主 Agent / admin 查
    tracking_dir = KNOWLEDGE_DIR / 'tracking'
    tracking_dir.mkdir(exist_ok=True)
    (tracking_dir / 'signal-clean-latest.json').write_text(
        json.dumps({'ran_at': time.strftime('%Y-%m-%d %H:%M:%S'),
                    'pending_count': len(pending), 'pending': pending},
                   ensure_ascii=False, indent=2), encoding='utf-8')
    return 0


# ── T2: 需求停滞检测 ─────────────────────────────────────────────────────
def task_stagnant_req():
    """扫 requirements/ 里 N 天无更新（mtime）的需求，输出停滞清单。"""
    now = time.time()
    stale = []
    for path, meta, _ in scan('requirements'):
        if meta.get('status') in ('已上线', '已关闭'):
            continue
        mtime = path.stat().st_mtime
        days = (now - mtime) / 86400
        if days >= STALE_DAYS:
            stale.append({
                'file': path.name,
                'id': meta.get('id', '?'),
                'title': meta.get('title', '(无标题)'),
                'owner': meta.get('owner', '未分配'),
                'status': meta.get('status', '?'),
                'stale_days': int(days),
            })
    print(f'[stagnant-req] 发现 {len(stale)} 条停滞需求（≥{STALE_DAYS} 天未更新）：')
    for s in stale:
        print(f"  [{s['stale_days']}d] {s['id']} · {s['title']} (@{s['owner']}, {s['status']})")
    tracking_dir = KNOWLEDGE_DIR / 'tracking'
    tracking_dir.mkdir(exist_ok=True)
    (tracking_dir / 'stagnant-req-latest.json').write_text(
        json.dumps({'ran_at': time.strftime('%Y-%m-%d %H:%M:%S'),
                    'stale_days_threshold': STALE_DAYS,
                    'stale_count': len(stale), 'stale': stale},
                   ensure_ascii=False, indent=2), encoding='utf-8')
    return 0


# ── T3: 周报 ─────────────────────────────────────────────────────────────
def task_weekly_report():
    """生成需求流转周报（汇总到 tracking/weekly-YYYYMMDD.md）。"""
    today = time.strftime('%Y%m%d')
    stats = {'signals': 0, 'requirements': 0, 'designs': 0}
    status_dist: dict = {}
    for cat in ['signals', 'requirements', 'designs']:
        items = scan(cat)
        stats[cat] = len(items)
        for _, meta, _ in items:
            s = meta.get('status', '未标注')
            status_dist[f'{cat}/{s}'] = status_dist.get(f'{cat}/{s}', 0) + 1
    report_lines = [
        f'# WDP 团队工作台 · 周报 ({time.strftime("%Y-%m-%d")})',
        '',
        '## 知识库总量',
        f'- 信号：{stats["signals"]}',
        f'- 需求：{stats["requirements"]}',
        f'- 设计稿：{stats["designs"]}',
        '',
        '## 状态分布',
    ]
    for k, v in sorted(status_dist.items()):
        report_lines.append(f'- {k}: {v}')
    report_lines.append('')
    report_lines.append('> 由主 Agent 定时任务自动生成。')
    report = '\n'.join(report_lines)
    tracking_dir = KNOWLEDGE_DIR / 'tracking'
    tracking_dir.mkdir(exist_ok=True)
    out = tracking_dir / f'weekly-{today}.md'
    out.write_text(report, encoding='utf-8')
    print(f'[weekly-report] 周报已生成：{out}')
    return 0


# ── T4: session 压缩归档 ────────────────────────────────────────────────
def task_session_archive():
    """扫 profiles/<user>/sessions/，对 N 天未动的 session 做归档标记。"""
    if not PROFILES_DIR.is_dir():
        print(f'[session-archive] profiles 目录不存在: {PROFILES_DIR}', file=sys.stderr)
        return 1
    now = time.time()
    archived = []
    for user_dir in PROFILES_DIR.iterdir():
        if not user_dir.is_dir():
            continue
        sess_dir = user_dir / 'sessions'
        if not sess_dir.is_dir():
            continue
        for sess in sess_dir.glob('*.json'):
            mtime = sess.stat().st_mtime
            days = (now - mtime) / 86400
            if days >= 30:  # 30 天未动 → 归档
                archived.append({
                    'user': user_dir.name,
                    'session': sess.name,
                    'days_inactive': int(days),
                    'mtime': int(mtime),
                })
    print(f'[session-archive] 发现 {len(archived)} 个 ≥30 天未活跃的 session')
    # 归档索引（不实际移文件，由主 Agent / admin 人工确认后处理）
    tracking_dir = KNOWLEDGE_DIR / 'tracking'
    tracking_dir.mkdir(exist_ok=True)
    (tracking_dir / 'session-archive-candidates.json').write_text(
        json.dumps({'ran_at': time.strftime('%Y-%m-%d %H:%M:%S'),
                    'threshold_days': 30, 'candidates': archived},
                   ensure_ascii=False, indent=2), encoding='utf-8')
    return 0


# ── main ────────────────────────────────────────────────────────────────
TASKS = {
    'signal-clean': task_signal_clean,
    'stagnant-req': task_stagnant_req,
    'weekly-report': task_weekly_report,
    'session-archive': task_session_archive,
}

if __name__ == '__main__':
    if len(sys.argv) < 2 or sys.argv[1] not in TASKS:
        print(f'用法: {sys.argv[0]} <{"|".join(TASKS.keys())}>', file=sys.stderr)
        sys.exit(2)
    sys.exit(TASKS[sys.argv[1]]())
