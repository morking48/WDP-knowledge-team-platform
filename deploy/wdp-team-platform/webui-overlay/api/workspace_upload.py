"""
Hermes Web UI -- 上传到个人 workspace（WDP 团队工作台 R6 扩展）.

POST /api/me/upload   multipart 上传 → 落到 profiles/<user>/workspace/uploads/

与 /api/upload（chat 附件，走 STATE_DIR/attachments）的区别：
  - chat 附件是会话级临时上下文，agent 用完即弃
  - workspace 上传是用户的个人工作资料，长期保留、跨 session 可用、
    出现在个人中心「工作库」tab 的文件清单里

设计约束：
  - 复用 api/upload 的 multipart 解析
  - 只允许写自己 profile 的 workspace，多用户隔离天然由 active profile 决定
  - 单文件 ≤ 50MB
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_BYTES = 50 * 1024 * 1024  # 50MB


def _sanitize_name(filename: str) -> str:
    from api.upload import _sanitize_upload_name
    return _sanitize_upload_name(filename)


def _user_workspace_uploads() -> Path | None:
    try:
        from api.profiles import get_active_hermes_home
        d = Path(get_active_hermes_home()) / 'workspace' / 'uploads'
        d.mkdir(parents=True, exist_ok=True)
        return d
    except Exception as e:
        logger.error("workspace uploads dir failed: %s", e)
        return None


def handle_workspace_upload(handler):
    """multipart/form-data 上传单文件到个人 workspace/uploads/"""
    from api import users as _users
    from api.upload import parse_multipart, _sanitize_upload_name
    from api.routes import j

    if _users.multiuser_enabled():
        u = _users.current_request_user(handler)
        if not u:
            return j(handler, {'error': '未登录'}, status=401)

    try:
        content_type = handler.headers.get('Content-Type', '')
        content_length = int(handler.headers.get('Content-Length', '0'))
        if content_length > MAX_BYTES:
            return j(handler, {'error': f'文件超过 {MAX_BYTES//1024//1024}MB 上限'}, status=413)
        fields, files = parse_multipart(handler.rfile, content_type, content_length)
    except Exception as e:
        return j(handler, {'error': f'multipart 解析失败: {e}'}, status=400)

    if not files:
        return j(handler, {'error': '缺 file 字段'}, status=400)
    # files 是 dict：{'file': (filename, content_bytes)}，取第一个
    _field, (filename, content) = next(iter(files.items()))
    if isinstance(content, str):
        content = content.encode('utf-8')

    try:
        safe = _sanitize_upload_name(filename)
    except Exception as e:
        return j(handler, {'error': f'文件名不合法: {e}'}, status=400)

    uploads = _user_workspace_uploads()
    if uploads is None:
        return j(handler, {'error': 'workspace 不可用'}, status=500)

    dest = (uploads / safe).resolve()
    if not dest.is_relative_to(uploads):
        return j(handler, {'error': '非法目标路径'}, status=400)
    # 重名自动加 -1/-2
    if dest.exists():
        stem, suffix = dest.stem, dest.suffix
        for idx in range(1, 1000):
            cand = uploads / f'{stem}-{idx}{suffix}'
            if not cand.exists():
                dest = cand
                break
        else:
            return j(handler, {'error': '同名文件过多'}, status=409)
    try:
        dest.write_bytes(content)
    except Exception as e:
        return j(handler, {'error': f'写入失败: {e}'}, status=500)

    rel = f'workspace/uploads/{dest.name}'
    return j(handler, {
        'ok': True,
        'filename': dest.name,
        'path': rel,
        'size': len(content),
    })
