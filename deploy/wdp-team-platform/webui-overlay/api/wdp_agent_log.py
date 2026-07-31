"""
WDP 团队工作台 · Agent 决策日志（简化版 session 管理，勿与官方 agent_sessions.py 混淆）.

设计（与用户对齐的简化架构）：
  - 每次"人发起的 agent 任务"（归并/审核助手）执行后，把
    {输入摘要, AI建议, 管理员最终决策, 是否采纳} 存一条 JSONL 记录。
  - 存放：knowledge/agent-sessions/{merge,review}.jsonl（知识库一部分，git 版本化）
  - 下次执行同类任务时，读最近 N 条注入 prompt（few-shot），
    让 agent 参考团队历史风格 → 越用越贴合团队判断。
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_KINDS = ('merge', 'review')


def _sessions_dir() -> Path | None:
    from api import knowledge as _kb
    root = _kb.get_knowledge_root()
    if not root:
        return None
    d = root / 'agent-sessions'
    d.mkdir(parents=True, exist_ok=True)
    return d


def record_decision(kind: str, entry: dict) -> dict:
    """追加一条决策记录。entry 自带业务字段，自动补时间戳。"""
    if kind not in _KINDS:
        return {'error': f'未知 session 类型 {kind}'}
    d = _sessions_dir()
    if not d:
        return {'error': 'knowledge 根不可用'}
    entry = dict(entry)
    entry['at'] = time.strftime('%Y-%m-%d %H:%M:%S')
    f = d / f'{kind}.jsonl'
    try:
        with open(f, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + '\n')
        try:
            import subprocess
            from api import knowledge as _kb
            root = _kb.get_knowledge_root()
            if root:
                subprocess.run(['git', '-C', str(root), 'add', str(f.relative_to(root))],
                               capture_output=True, timeout=10)
                subprocess.run(['git', '-C', str(root), 'commit', '-m',
                                f'chore(agent-sessions): {kind} 决策记录'],
                               capture_output=True, timeout=10)
                try:
                    from api.knowledge_ops import _git_push_async
                    _git_push_async(root)
                except Exception:
                    pass
        except Exception:
            pass
        return {'ok': True}
    except Exception as e:
        logger.warning('record_decision failed: %s', e)
        return {'error': str(e)}


def recent_decisions(kind: str, n: int = 5) -> list[dict]:
    """读最近 n 条决策（few-shot 注入用）。"""
    d = _sessions_dir()
    if not d:
        return []
    f = d / f'{kind}.jsonl'
    if not f.is_file():
        return []
    out = []
    try:
        lines = f.read_text(encoding='utf-8').splitlines()
        for line in lines[-n:]:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        pass
    return out


def history_stats(kind: str) -> dict:
    """该类型决策的累计数（界面显示"已积累N条团队决策经验"）。"""
    d = _sessions_dir()
    if not d:
        return {'count': 0}
    f = d / f'{kind}.jsonl'
    if not f.is_file():
        return {'count': 0}
    try:
        return {'count': sum(1 for line in f.read_text(encoding='utf-8').splitlines() if line.strip())}
    except Exception:
        return {'count': 0}


def few_shot_block(kind: str, n: int = 5) -> str:
    """把最近决策格式化成 prompt 注入块（空历史返回空串）。

    隔离规训：历史决策是"别的条目"的记录，只作风格参考——注入块头尾都
    明确声明与本次内容无关，防 LLM 把旧条目的结论/标题套到当前分析上
    （否则管理员会感觉"对话被串联了"，且影响判断合理性）。
    """
    items = recent_decisions(kind, n)
    if not items:
        return ''
    lines = ['\n## 团队历史决策参考（仅学习判断风格——注意：以下是**其他条目**的历史记录，'
             '与你本次要分析的内容**无关**，禁止引用其中的标题/结论/理由来分析本条）']
    for it in items:
        if kind == 'merge':
            adopted = '采纳' if it.get('adopted') else ('修正后执行' if it.get('final_title') else '未执行')
            lines.append(f"- 信号[{','.join(it.get('signal_ids', []))}] AI建议「{it.get('suggested_title','')}」"
                         f" → 管理员{adopted}，最终标题「{it.get('final_title','')}」")
        elif kind == 'review':
            lines.append(f"- 提交「{it.get('title','')}」({it.get('category','')}) AI建议:{it.get('ai_advice','')[:40]}"
                         f" → 管理员{it.get('decision','')}{('，理由:'+it.get('reason','')) if it.get('reason') else ''}")
    lines.append('（历史参考结束。你的分析必须完全基于本次待审内容本身。）')
    return '\n'.join(lines) + '\n'
