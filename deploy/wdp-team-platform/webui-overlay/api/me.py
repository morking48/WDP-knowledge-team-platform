"""
Hermes Web UI -- 个人中心 API（WDP 团队工作台 R4 扩展）.

四个子页对应接口：
  Agent   : SOUL.md 读写 + 个人信息
  工作库   : workspace 文件列表（workspace-index 简化版）
  Memory  : 个人 memory 读写（复用 api/memory 思路但走文件）
  日志    : profile 下的运行日志（最近 N 行）

接口：
  GET  /api/me/agent          当前用户 + SOUL.md 内容
  POST /api/me/soul           写 SOUL.md（仅本人）
  GET  /api/me/workspace      个人 workspace 文件列表
  GET  /api/me/memory         读 MEMORY.md / USER.md
  POST /api/me/memory         写 MEMORY.md / USER.md
  GET  /api/me/logs?tail=200  最近日志（stderr/webui log）
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)


# ── 当前用户 + profile home ────────────────────────────────────────────────
def _current(handler):
    """返回 (user_dict, profile_home) 或 (None, None)。"""
    from api import users as _users
    if not _users.multiuser_enabled():
        # 单用户模式：视作 admin，用默认 home
        try:
            from api.profiles import get_active_hermes_home
            return ({'username': 'default', 'role': 'admin', 'profile': 'default'},
                    Path(get_active_hermes_home()))
        except Exception:
            return None, None
    u = _users.current_request_user(handler)
    if not u:
        return None, None
    try:
        from api.profiles import get_active_hermes_home
        return u, Path(get_active_hermes_home())
    except Exception:
        return u, None


# ── Agent 子页 ──────────────────────────────────────────────────────────────
def handle_me_agent(handler, parsed):
    u, home = _current(handler)
    if not u or not home:
        return {'error': '未登录'}, 401
    soul_path = home / 'SOUL.md'
    soul = ''
    if soul_path.exists():
        try:
            soul = soul_path.read_text(encoding='utf-8')
        except Exception:
            pass
    agents_path = home / 'AGENTS.md'
    agents = ''
    if agents_path.exists():
        try:
            agents = agents_path.read_text(encoding='utf-8')
        except Exception:
            pass
    return {
        'user': u,
        'profile_home': str(home),
        'soul': soul,
        'agents': agents,
    }


def handle_soul_write(handler, body):
    u, home = _current(handler)
    if not u or not home:
        return {'error': '未登录'}, 401
    content = body.get('soul') or ''
    try:
        (home / 'SOUL.md').write_text(content, encoding='utf-8')
    except Exception as e:
        return {'error': f'写入失败: {e}'}, 500
    return {'ok': True}


# ── 工作库子页 ─────────────────────────────────────────────────────────────
def handle_me_workspace(handler, parsed):
    u, home = _current(handler)
    if not u or not home:
        return {'error': '未登录'}, 401
    ws = home / 'workspace'
    files = []
    if ws.is_dir():
        try:
            for p in sorted(ws.rglob('*'), key=lambda x: -x.stat().st_mtime):
                if p.is_file():
                    rel = p.relative_to(ws)
                    # 跳过隐藏文件，以及任何隐藏目录（.开头）下的文件——
                    # 如 .tmp_signals/（agent 中转用），不该出现在"最近上传"列表
                    if any(part.startswith('.') for part in rel.parts):
                        continue
                    files.append({
                        'path': str(rel).replace('\\', '/'),
                        'size': p.stat().st_size,
                        'mtime': int(p.stat().st_mtime),
                    })
                    if len(files) >= 200:
                        break
        except Exception as e:
            logger.warning("workspace scan failed: %s", e)
    # 环境鉴别信息（Machine ID + 指纹文件）
    machine_id = ''
    try:
        import subprocess
        r = subprocess.run(['wmic', 'csproduct', 'get', 'uuid'],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            lines = [l.strip() for l in r.stdout.splitlines() if l.strip()]
            if len(lines) >= 2:
                machine_id = lines[1]
    except Exception:
        machine_id = os.environ.get('COMPUTERNAME', 'unknown')
    fingerprint_file = home / '.wdp-workspace.json'
    fingerprint = None
    if fingerprint_file.exists():
        try:
            fingerprint = json.loads(fingerprint_file.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {
        'workspace_root': str(ws),
        'exists': ws.is_dir(),
        'files': files,
        'count': len(files),
        'machine_id': machine_id,
        'fingerprint': fingerprint,
    }


# ── Memory 子页 ────────────────────────────────────────────────────────────
def handle_me_memory(handler, parsed):
    u, home = _current(handler)
    if not u or not home:
        return {'error': '未登录'}, 401
    mem_dir = home / 'memories'
    memory = ''
    user_md = ''
    if mem_dir.is_dir():
        mp = mem_dir / 'MEMORY.md'
        up = mem_dir / 'USER.md'
        if mp.exists():
            try:
                memory = mp.read_text(encoding='utf-8')
            except Exception:
                pass
        if up.exists():
            try:
                user_md = up.read_text(encoding='utf-8')
            except Exception:
                pass
    return {'memory': memory, 'user': user_md, 'mem_dir': str(mem_dir)}


def handle_memory_write(handler, body):
    u, home = _current(handler)
    if not u or not home:
        return {'error': '未登录'}, 401
    which = body.get('which') or 'memory'  # 'memory' | 'user'
    content = body.get('content') or ''
    mem_dir = home / 'memories'
    mem_dir.mkdir(parents=True, exist_ok=True)
    fname = 'MEMORY.md' if which == 'memory' else 'USER.md'
    try:
        (mem_dir / fname).write_text(content, encoding='utf-8')
    except Exception as e:
        return {'error': f'写入失败: {e}'}, 500
    return {'ok': True, 'file': fname}


# ── 日志子页 ───────────────────────────────────────────────────────────────
def handle_me_logs(handler, parsed):
    from urllib.parse import parse_qs
    u, home = _current(handler)
    if not u or not home:
        return {'error': '未登录'}, 401
    qs = parse_qs(parsed.query)
    tail = int((qs.get('tail') or ['200'])[0])
    tail = max(10, min(tail, 2000))
    log_dir = home / 'logs'
    entries = []
    if log_dir.is_dir():
        try:
            for p in sorted(log_dir.glob('*.log'), key=lambda x: -x.stat().st_mtime)[:5]:
                try:
                    text = p.read_text(encoding='utf-8', errors='replace')
                    lines = text.splitlines()
                    entries.append({
                        'file': p.name,
                        'size': p.stat().st_size,
                        'mtime': int(p.stat().st_mtime),
                        'tail': lines[-tail:],
                    })
                except Exception:
                    pass
        except Exception:
            pass
    # 也附 WebUI 自身 stderr（STATE_DIR 下）
    try:
        from api.config import STATE_DIR
        for cand in ['webui-error.log', 'webui.log', 'server.log']:
            p = STATE_DIR / cand
            if p.exists():
                text = p.read_text(encoding='utf-8', errors='replace')
                entries.append({
                    'file': f'webui/{cand}',
                    'size': p.stat().st_size,
                    'mtime': int(p.stat().st_mtime),
                    'tail': text.splitlines()[-tail:],
                })
    except Exception:
        pass
    return {'entries': entries, 'log_dir': str(log_dir)}
