"""WDP 团队工作台 · 团队 Skill 编辑与发布（admin 专属）.

管理员在「团队 Agent」页可视化编辑团队 skill：
  - 列出所有团队 skill（跨工程 skills/ 与 hermes-home/skills/wdp-team/）
  - 用「技能助手」对话式修改某个 skill 的 SKILL.md
  - 保存 = 存草稿（不动正式 skill）
  - 发布 = 写回正式 SKILL.md → 成员实时扫描团队 skill 目录，自动同步

成员读团队 skill 是实时扫描共享目录（me_skills._team_skill_dirs()），
所以发布只需写正式目录，无需像 SOUL 那样逐 profile 下发。
"""
from __future__ import annotations

from api._wdp_types import ApiResult

import logging
import re
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def _team_skill_dirs() -> list:
    """复用 me_skills 的团队 skill 目录发现逻辑。"""
    from api.me_skills import _team_skill_dirs as _dirs
    return _dirs()


def _drafts_dir() -> Path:
    """草稿目录（存团队 home 下的隐藏目录，不进正式 skill）。"""
    import os
    home = os.getenv('HERMES_HOME', '').strip()
    if home:
        base = Path(home)
    else:
        try:
            from api.profiles import _DEFAULT_HERMES_HOME
            base = Path(_DEFAULT_HERMES_HOME)
        except Exception:
            base = Path.home() / '.hermes'
    d = base / '.team-skill-drafts'
    d.mkdir(parents=True, exist_ok=True)
    return d


def _parse_meta(skill_md: Path) -> dict:
    """从 SKILL.md frontmatter 取 name/description。"""
    out = {'name': skill_md.parent.name, 'description': ''}
    try:
        raw = skill_md.read_text(encoding='utf-8')
    except Exception:
        return out
    m = re.match(r'^---\s*\n(.*?)\n---', raw, re.DOTALL)
    if not m:
        return out
    for line in m.group(1).splitlines():
        if line.startswith('name:'):
            out['name'] = line.split(':', 1)[1].strip().strip('"\'')
        elif line.startswith('description:'):
            out['description'] = line.split(':', 1)[1].strip().strip('"\'')
    return out


def _find_skill(skill_dir: str) -> Path | None:
    """按目录名在团队 skill 目录里定位 SKILL.md 所在目录。"""
    if not skill_dir or '/' in skill_dir or '\\' in skill_dir or '..' in skill_dir:
        return None
    for base in _team_skill_dirs():
        cand = base / skill_dir
        if (cand / 'SKILL.md').is_file():
            return cand
    return None


def list_team_skills() -> dict:
    """列出所有团队 skill（含是否有未发布草稿）。"""
    skills = []
    seen = set()
    drafts = _drafts_dir()
    for base in _team_skill_dirs():
        if not base.is_dir():
            continue
        for d in sorted(base.iterdir()):
            if not d.is_dir() or d.name.startswith('.'):
                continue
            md = d / 'SKILL.md'
            if not md.is_file() or d.name in seen:
                continue
            seen.add(d.name)
            meta = _parse_meta(md)
            draft_f = drafts / (d.name + '.md')
            meta.update({
                'dir': d.name,
                'path': str(md),
                'has_draft': draft_f.is_file(),
                'protected': d.name in _PROTECTED_SKILLS,
                'mtime': int(md.stat().st_mtime),
            })
            skills.append(meta)
    return {'skills': skills}


def get_team_skill(skill_dir: str) -> ApiResult:
    """读取某团队 skill 的 SKILL.md 全文（优先返回草稿内容）。"""
    d = _find_skill(skill_dir)
    if not d:
        return {'error': 'skill 不存在'}, 404
    md = d / 'SKILL.md'
    try:
        published = md.read_text(encoding='utf-8')
    except Exception as e:
        return {'error': f'读取失败: {e}'}, 500
    draft_f = _drafts_dir() / (skill_dir + '.md')
    draft = None
    if draft_f.is_file():
        try:
            draft = draft_f.read_text(encoding='utf-8')
        except Exception:
            draft = None
    return {
        'dir': skill_dir,
        'published': published,
        'draft': draft,           # 有草稿则返回，前端优先展示
        'has_draft': draft is not None,
    }


def save_team_skill_draft(skill_dir: str, content: str) -> ApiResult:
    """保存草稿（不动正式 SKILL.md）。"""
    d = _find_skill(skill_dir)
    if not d:
        return {'error': 'skill 不存在'}, 404
    if not (content or '').strip():
        return {'error': '内容为空'}, 400
    draft_f = _drafts_dir() / (skill_dir + '.md')
    try:
        draft_f.write_text(content, encoding='utf-8')
        return {'ok': True, 'has_draft': True}
    except Exception as e:
        return {'error': f'保存失败: {e}'}, 500


def _validate_skill_frontmatter(text: str) -> dict:
    """校验 SKILL.md 的 YAML frontmatter：必须合法 + 含非空 name/description。

    成员 agent 靠 frontmatter 的 name/description 检索加载 skill，缺失/格式错会导致
    该 skill 检索失效，故发布前硬校验（对齐企业规范 Schema 强约束）。
    """
    t = (text or '').lstrip()
    if not t.startswith('---'):
        return {'ok': False, 'message': 'SKILL.md 必须以 YAML frontmatter（--- 开头）'}
    # 提取 frontmatter 块
    m = re.match(r'^---\s*\n(.*?)\n---', t, re.DOTALL)
    if not m:
        return {'ok': False, 'message': 'frontmatter 格式错误：缺少闭合的 --- 分隔线'}
    fm_text = m.group(1)
    fields = {}
    for line in fm_text.splitlines():
        if ':' in line and not line.strip().startswith('#') and not line.startswith((' ', '\t', '-')):
            k, v = line.split(':', 1)
            fields[k.strip()] = v.split('#')[0].strip().strip('"\'')
    missing = [k for k in ('name', 'description') if not fields.get(k)]
    if missing:
        return {'ok': False, 'message': f'frontmatter 缺少必填字段：{", ".join(missing)}（成员 agent 靠它检索加载技能）'}
    # 正文非空（frontmatter 之后要有内容）
    body = t[m.end():].strip()
    if len(body) < 10:
        return {'ok': False, 'message': 'SKILL.md 正文过短或为空，请补充技能内容（触发条件/步骤/注意事项）'}
    return {'ok': True}


def publish_team_skill(skill_dir: str, content: str | None = None) -> ApiResult:
    """发布：把草稿（或传入内容）写回正式 SKILL.md，成员实时同步。

    content 为空时用已保存的草稿；两者都无则报错。
    """
    d = _find_skill(skill_dir)
    if not d:
        return {'error': 'skill 不存在'}, 404
    draft_f = _drafts_dir() / (skill_dir + '.md')
    text = content if (content and content.strip()) else None
    if text is None and draft_f.is_file():
        try:
            text = draft_f.read_text(encoding='utf-8')
        except Exception:
            text = None
    if not text or not text.strip():
        return {'error': '没有可发布的内容（先保存草稿或传入内容）'}, 400
    # frontmatter 硬校验：必须是合法 YAML frontmatter 且含 name/description（成员靠它检索加载）
    vr = _validate_skill_frontmatter(text)
    if not vr['ok']:
        return {'error': vr['message'], 'invalid': True}, 422
    md = d / 'SKILL.md'
    try:
        # 备份原文件到草稿目录（不污染 skill 目录本身，防误发布可回溯）
        if md.is_file():
            bak = _drafts_dir() / ('.bak-' + skill_dir + '.md')
            bak.write_text(md.read_text(encoding='utf-8'), encoding='utf-8')
        md.write_text(text, encoding='utf-8')
    except Exception as e:
        return {'error': f'发布失败: {e}'}, 500
    # 发布成功 → 清掉草稿
    try:
        if draft_f.is_file():
            draft_f.unlink()
    except Exception:
        pass
    # 记录发布时间
    try:
        (_drafts_dir() / ('.published-' + skill_dir)).write_text(
            time.strftime('%Y-%m-%d %H:%M'), encoding='utf-8')
    except Exception:
        pass
    return {'ok': True, 'message': f'已发布团队技能「{skill_dir}」，成员将实时同步'}


def discard_team_skill_draft(skill_dir: str) -> ApiResult:
    """丢弃草稿。"""
    draft_f = _drafts_dir() / (skill_dir + '.md')
    try:
        if draft_f.is_file():
            draft_f.unlink()
        return {'ok': True}
    except Exception as e:
        return {'error': f'丢弃失败: {e}'}, 500


# ── 新增 / 删除团队 skill ────────────────────────────────────────────
# 内置核心 skill 受保护，不可删除（团队工作流依赖）
_PROTECTED_SKILLS = {'signal-intake', 'requirement-triage',
                     'wdp-online-knowledge-sync', 'wdp-workbench-ui',
                     'design-converge'}

_DIR_RE = re.compile(r'^[a-z0-9][a-z0-9-_]{1,63}$')


def create_team_skill(skill_dir: str, name: str = '', description: str = '') -> ApiResult:
    """新建团队 skill（骨架 SKILL.md，创建后用技能助手充实再发布）。

    写入第一个团队 skill 目录（工程 skills/）。
    """
    skill_dir = (skill_dir or '').strip().lower()
    if not _DIR_RE.match(skill_dir):
        return {'error': '目录名需为小写字母/数字/中划线（2-64字符），如 my-new-skill'}, 400
    if _find_skill(skill_dir):
        return {'error': f'skill「{skill_dir}」已存在'}, 409
    dirs = _team_skill_dirs()
    if not dirs:
        return {'error': '未找到团队 skill 目录'}, 500
    base = dirs[0]
    name = (name or '').strip() or skill_dir
    description = (description or '').strip() or '（待补充：这个技能做什么、什么场景触发）'
    skeleton = f"""---
name: {skill_dir}
description: {description}
---

# {name}

## 触发场景

（什么情况下使用这个技能）

## 步骤

1. （第一步）
2. （第二步）

## 注意事项

（避坑说明）
"""
    try:
        d = base / skill_dir
        d.mkdir(parents=True, exist_ok=False)
        (d / 'SKILL.md').write_text(skeleton, encoding='utf-8')
    except FileExistsError:
        return {'error': f'目录「{skill_dir}」已存在'}, 409
    except Exception as e:
        return {'error': f'创建失败: {e}'}, 500
    return {'ok': True, 'dir': skill_dir,
            'message': f'已创建技能「{skill_dir}」骨架，用「🤖 技能助手」充实内容后发布'}


def delete_team_skill(skill_dir: str) -> ApiResult:
    """删除团队 skill（内置四个核心 skill 受保护不可删）。"""
    if skill_dir in _PROTECTED_SKILLS:
        return {'error': f'「{skill_dir}」是内置核心技能，团队工作流依赖它，不可删除'}, 403
    d = _find_skill(skill_dir)
    if not d:
        return {'error': 'skill 不存在'}, 404
    import shutil
    try:
        # 删除前整目录备份到草稿区（可人工恢复）
        bak_dir = _drafts_dir() / ('.deleted-' + skill_dir)
        if bak_dir.exists():
            shutil.rmtree(bak_dir)
        shutil.copytree(d, bak_dir)
        shutil.rmtree(d)
    except Exception as e:
        return {'error': f'删除失败: {e}'}, 500
    # 清掉草稿
    try:
        draft_f = _drafts_dir() / (skill_dir + '.md')
        if draft_f.is_file():
            draft_f.unlink()
    except Exception:
        pass
    return {'ok': True, 'message': f'已删除技能「{skill_dir}」（已备份，可人工恢复）'}
