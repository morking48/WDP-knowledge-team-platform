"""个人中心 · 技能（skill）管理.

设计（保守方案，不碰 agent 核心，物理移动实现真开关）：
- 团队 skill：工程 skills/ + hermes-home/skills/wdp-team/，成员只读可见。
- 个人 skill：存成员 profile 的 skills/personal/<name>/（启用）
             与 skills/personal/.disabled/<name>/（禁用）。
  开关 = 物理移动目录：agent 只加载在位的 personal/<name>/，禁用即移到 .disabled/，
  agent 物理上加载不到 → 真生效，不依赖核心读禁用清单。
- 沉淀：对话 agent 用 scripts/save_personal_skill.py 写入（见该脚本）。

接口：
  GET  /api/me/skills                列出团队(只读) + 个人(带 enabled 状态)
  POST /api/me/skills/toggle {name, enabled}   启用/停用个人 skill（物理移动）
  POST /api/me/skills/delete {name}            删除个人 skill
"""
from __future__ import annotations

import shutil
from pathlib import Path

from api.me import _current


def _parse_meta(skill_md: Path) -> dict:
    """从 SKILL.md frontmatter 取 name/description。"""
    out = {'name': skill_md.parent.name, 'description': ''}
    try:
        raw = skill_md.read_text(encoding='utf-8')
    except Exception:
        return out
    import re
    m = re.match(r'^---\s*\n(.*?)\n---', raw, re.DOTALL)
    if not m:
        return out
    for line in m.group(1).splitlines():
        if line.startswith('name:'):
            out['name'] = line.split(':', 1)[1].strip().strip('"\'')
        elif line.startswith('description:'):
            out['description'] = line.split(':', 1)[1].strip().strip('"\'')
    return out


def _scan_dir(base: Path, scope: str, enabled: bool = True) -> list:
    """扫一层 skill 目录（每个子目录含 SKILL.md）。"""
    out = []
    if not base.is_dir():
        return out
    for d in sorted(base.iterdir()):
        if not d.is_dir() or d.name.startswith('.'):
            continue
        md = d / 'SKILL.md'
        if md.is_file():
            meta = _parse_meta(md)
            meta.update({'scope': scope, 'enabled': enabled, 'dir': d.name})
            out.append(meta)
    return out


def _team_skill_dirs() -> list:
    """团队 skill 目录（只读展示）。"""
    import os
    dirs = []
    home = os.getenv('HERMES_HOME', '').strip()
    if home:
        root = Path(home).parent            # 工程根
        dirs.append(root / 'skills')        # 工程团队工作 skill
        dirs.append(Path(home) / 'skills' / 'wdp-team')  # 团队专属 skill
    return [d for d in dirs if d.is_dir()]


def _personal_base(home: Path) -> Path:
    return home / 'skills' / 'personal'


def list_skills(handler) -> dict:
    u, home = _current(handler)
    if not u or not home:
        return {'error': '未登录'}, 401
    team = []
    for td in _team_skill_dirs():
        team += _scan_dir(td, 'team', enabled=True)
    pbase = _personal_base(home)
    personal = _scan_dir(pbase, 'personal', enabled=True)
    personal += _scan_dir(pbase / '.disabled', 'personal', enabled=False)
    personal.sort(key=lambda x: x['name'])
    return {'team': team, 'personal': personal}


def toggle_skill(handler, name: str, enabled: bool) -> dict:
    """物理移动实现真开关：启用=移回 personal/，停用=移到 personal/.disabled/。"""
    u, home = _current(handler)
    if not u or not home:
        return {'error': '未登录'}, 401
    if not name or '/' in name or '\\' in name or name.startswith('.'):
        return {'error': '非法 skill 名'}, 400
    pbase = _personal_base(home)
    active = pbase / name
    disabled = pbase / '.disabled' / name
    if enabled:
        if disabled.is_dir():
            active.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(disabled), str(active))
        elif not active.is_dir():
            return {'error': 'skill 不存在'}, 404
    else:
        if active.is_dir():
            disabled.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(active), str(disabled))
        elif not disabled.is_dir():
            return {'error': 'skill 不存在'}, 404
    return {'ok': True, 'name': name, 'enabled': enabled}


def delete_skill(handler, name: str) -> dict:
    u, home = _current(handler)
    if not u or not home:
        return {'error': '未登录'}, 401
    if not name or '/' in name or '\\' in name or name.startswith('.'):
        return {'error': '非法 skill 名'}, 400
    pbase = _personal_base(home)
    removed = False
    for cand in (pbase / name, pbase / '.disabled' / name):
        if cand.is_dir():
            shutil.rmtree(cand, ignore_errors=True)
            removed = True
    if not removed:
        return {'error': 'skill 不存在'}, 404
    return {'ok': True, 'name': name}
