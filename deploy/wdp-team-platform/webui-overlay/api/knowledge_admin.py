"""
Hermes Web UI -- 知识库管理操作（WDP 团队工作台 R8 扩展，admin 专属）.

POST /api/admin/knowledge/update
  body: {
    "type": "signals|requirements|designs",
    "id": "<frontmatter id 或 文件名>",
    "updates": { "status": "已确认", "priority": "P1", "owner": "zhangsan", ... },
    "note": "改态备注（追加到 tracking 链）"
  }

效果：
  - 修改目标文件的 frontmatter 字段（保留其他字段和正文）
  - 如果 updates 含 status 且文件 frontmatter 有 tracking 字段，
    自动追加一条 tracking 记录（date/event=改态/note）
  - git add + commit

设计约束：
  - 仅 admin 可调用
  - 只做 frontmatter 级修改，不动正文（正文改动走 chat + 提交入库）
"""
from __future__ import annotations

import logging
import re
import subprocess
import time
from pathlib import Path

from api import knowledge as _kb

logger = logging.getLogger(__name__)


def _serialize_frontmatter(meta: dict) -> str:
    """把 meta dict 转回 YAML frontmatter 块（仅支持一级 scalar/list/dict）。"""
    lines = ['---']
    for k, v in meta.items():
        if k.startswith('_'):
            continue
        if v is None:
            lines.append(f'{k}:')
        elif isinstance(v, bool):
            lines.append(f'{k}: {"true" if v else "false"}')
        elif isinstance(v, (int, float)):
            lines.append(f'{k}: {v}')
        elif isinstance(v, list):
            if not v:
                lines.append(f'{k}: []')
            else:
                lines.append(f'{k}:')
                for item in v:
                    if isinstance(item, dict):
                        # dict item：第一个 k:v 同行，后续缩进
                        pairs = list(item.items())
                        if pairs:
                            fk, fv = pairs[0]
                            lines.append(f'  - {fk}: {fv}')
                            for sk, sv in pairs[1:]:
                                lines.append(f'    {sk}: {sv}')
                    else:
                        lines.append(f'  - {item}')
        elif isinstance(v, dict):
            lines.append(f'{k}:')
            for sk, sv in v.items():
                lines.append(f'  {sk}: {sv}')
        else:
            s = str(v)
            # 含冒号/特殊字符的加引号
            if ':' in s or s.startswith(('[', '{', '"', "'")):
                s = '"' + s.replace('"', '\\"') + '"'
            lines.append(f'{k}: {s}')
    lines.append('---')
    return '\n'.join(lines) + '\n'


def handle_admin_knowledge_update(handler, body):
    from api import users as _users
    from api.routes import j

    u = _users.current_request_user(handler)
    if not u:
        return j(handler, {'error': '未登录'}, status=401)

    cat = (body.get('type') or '').strip()
    fid = (body.get('id') or '').strip()
    updates = body.get('updates') or {}
    note = (body.get('note') or '').strip()

    if cat not in _kb.get_categories():
        return j(handler, {'error': f'非法类目 {cat}'}, status=400)
    if not fid:
        return j(handler, {'error': '缺 id'}, status=400)
    if not updates and not note:
        return j(handler, {'error': 'updates 和 note 不能都为空'}, status=400)

    # 找到目标文件
    root = _kb.get_knowledge_root()
    if not root:
        return j(handler, {'error': 'knowledge 根不可用'}, status=500)
    cat_dir = root / _kb.get_categories().get(cat, cat)
    if not cat_dir.is_dir():
        return j(handler, {'error': f'类目目录不存在 {cat}'}, status=404)

    # 先按文件名找
    target = cat_dir / fid
    if not target.suffix:
        target = cat_dir / (fid + '.md')
    if not target.exists():
        # 按 frontmatter id 找
        for f in cat_dir.glob('*.md'):
            if f.name.startswith('_'):
                continue
            try:
                meta, _ = _kb.parse_frontmatter(f.read_text(encoding='utf-8'))
            except Exception:
                continue
            if meta.get('id') == fid:
                target = f
                break
    if not target.exists():
        return j(handler, {'error': f'未找到 {fid}'}, status=404)

    # 读 + 改 frontmatter
    try:
        text = target.read_text(encoding='utf-8')
    except Exception as e:
        return j(handler, {'error': f'读文件失败: {e}'}, status=500)
    meta, body_text = _kb.parse_frontmatter(text)

    # 应用 updates
    changed = []
    for k, v in updates.items():
        old = meta.get(k)
        if old != v:
            meta[k] = v
            changed.append(f'{k}: {old!r} → {v!r}')

    # tracking 链：改 status 或有 note（催办/指派/关联等）都追加一条轨迹
    # tracking 字段不存在时自动创建（信号/设计原本无此字段）
    if 'status' in updates or note:
        if not isinstance(meta.get('tracking'), list):
            meta['tracking'] = []
        if 'status' in updates:
            event = f'改态为{updates["status"]}'
        else:
            event = '操作记录'
        meta['tracking'].append({
            'date': time.strftime('%Y-%m-%d'),
            'event': event,
            'note': note or f'admin {u["username"]} 操作',
        })

    # 写回
    new_text = _serialize_frontmatter(meta) + '\n' + body_text
    try:
        target.write_text(new_text, encoding='utf-8')
    except Exception as e:
        return j(handler, {'error': f'写入失败: {e}'}, status=500)

    # git commit
    git_msg = ''
    try:
        r = subprocess.run(['git', '-C', str(root), 'add', str(target.relative_to(root))],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            commit_msg = f'chore({cat}): admin {u["username"]} 更新 {target.name}'
            if changed:
                commit_msg += ' — ' + '; '.join(changed[:3])
            r2 = subprocess.run(['git', '-C', str(root), 'commit', '-m', commit_msg],
                                capture_output=True, text=True, timeout=10)
            if r2.returncode == 0:
                git_msg = 'git 已提交'
                try:
                    from api.knowledge_ops import _git_push_async
                    _git_push_async(root)
                except Exception:
                    pass
            else:
                git_msg = f'commit 失败: {r2.stderr[:100]}'
        else:
            git_msg = f'add 失败: {r.stderr[:100]}'
    except Exception as e:
        git_msg = f'git 异常: {e}'

    return j(handler, {
        'ok': True,
        'file': target.name,
        'changed': changed,
        'git': git_msg,
    })
