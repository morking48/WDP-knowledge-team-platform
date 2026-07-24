"""
Hermes Web UI -- 多用户管理（WDP 团队平台扩展）.

在现有单密码认证基础上扩展出"用户表"模型：
  - users.json 存储用户列表（username / password_hash / profile / role / active_token / active）
  - 单点登录：每个用户只有一个活跃 session token（active_token），新登录挤掉旧登录
  - 登录时按用户绑定 profile（username ↔ profile 同名；admin 用 default profile）

设计约束（遵循 docs/CONTRACTS.md 与本仓库 AGENTS.md）：
  - 纯 Python 标准库，无新增依赖
  - 复用 api.auth 的 PBKDF2(_hash_password) 与签名 session(create_session/verify_session)
  - 文件原子写（tmp + os.replace）+ 0600 权限，与 auth.py 的持久化风格一致
  - 不破坏现有单密码模式：未启用多用户时，一切行为与原版一致
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import tempfile
import threading
import time

from api.config import STATE_DIR

logger = logging.getLogger(__name__)

_USERS_FILE = STATE_DIR / 'users.json'
_USERS_LOCK = threading.Lock()

# 角色
ROLE_ADMIN = 'admin'
ROLE_MEMBER = 'member'


# ── 启用开关 ────────────────────────────────────────────────────────────────
def multiuser_enabled() -> bool:
    """是否启用多用户模式。

    启用条件（满足其一）：
      1. 环境变量 HERMES_WEBUI_MULTIUSER=1
      2. users.json 已存在（说明已被管理员初始化过用户表）

    未启用时，认证回落到 api.auth 的单密码模式，行为与原版完全一致。
    """
    env = os.getenv('HERMES_WEBUI_MULTIUSER', '').strip().lower()
    if env in {'1', 'true', 'yes', 'on'}:
        return True
    try:
        return _USERS_FILE.exists()
    except OSError:
        return False


# ── 用户表读写 ──────────────────────────────────────────────────────────────
def _load_users() -> list[dict]:
    try:
        if _USERS_FILE.exists():
            data = json.loads(_USERS_FILE.read_text(encoding='utf-8'))
            if isinstance(data, dict) and isinstance(data.get('users'), list):
                return data['users']
    except Exception as e:
        logger.debug("Failed to load users.json: %s", e)
    return []


def _save_users(users: list[dict]) -> None:
    """原子写 users.json（0600）。"""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=STATE_DIR, suffix='.users.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump({'users': users}, f, ensure_ascii=False, indent=2)
            os.chmod(tmp, 0o600)
            os.replace(tmp, _USERS_FILE)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception as e:
        logger.error("Failed to persist users.json: %s", e)
        raise


def get_user(username: str) -> dict | None:
    if not username:
        return None
    for u in _load_users():
        if u.get('username') == username:
            return u
    return None


def list_users(with_stats: bool = False) -> list[dict]:
    """返回用户列表（脱敏：不返回 password_hash / active_token）。

    with_stats=True 时附带用量统计（session数/入库贡献/工作库占用）。
    """
    out = []
    for u in _load_users():
        entry = {
            'username': u.get('username'),
            'profile': u.get('profile'),
            'role': u.get('role', ROLE_MEMBER),
            'active': bool(u.get('active', True)),
            'created_at': u.get('created_at'),
            'responsibilities': u.get('responsibilities', ''),  # 职责定义（分配建议抓手）
        }
        if with_stats:
            try:
                from api import knowledge_ops as _ops
                entry['stats'] = _ops.get_user_stats(u.get('username'), u.get('profile') or u.get('username'))
            except Exception:
                entry['stats'] = {'sessions': 0, 'contributions': 0, 'storage_mb': 0.0}
        out.append(entry)
    return out


def create_user(username: str, password: str, *, role: str = ROLE_MEMBER,
                profile: str | None = None) -> dict:
    """创建用户。profile 默认与 username 同名；admin 通常用 'default'。"""
    from api.auth import _hash_password
    from api.profiles import _PROFILE_ID_RE

    username = (username or '').strip()
    if not username or not _PROFILE_ID_RE.fullmatch(username):
        raise ValueError('用户名不合法（需小写字母/数字/连字符）')
    if role not in {ROLE_ADMIN, ROLE_MEMBER}:
        raise ValueError('非法角色')
    if not password or len(password) < 6:
        raise ValueError('密码至少 6 位')

    profile_name = (profile or username).strip() or username
    with _USERS_LOCK:
        users = _load_users()
        if any(u.get('username') == username for u in users):
            raise ValueError('用户已存在')
        rec = {
            'username': username,
            'password_hash': _hash_password(password),
            'profile': profile_name,
            'role': role,
            'active': True,
            'active_token': None,
            'created_at': time.strftime('%Y-%m-%d'),
        }
        users.append(rec)
        _save_users(users)
    return {k: rec[k] for k in ('username', 'profile', 'role', 'active', 'created_at')}


def set_user_active(username: str, active: bool) -> bool:
    with _USERS_LOCK:
        users = _load_users()
        for u in users:
            if u.get('username') == username:
                u['active'] = bool(active)
                if not active:
                    u['active_token'] = None  # 停用即踢下线
                _save_users(users)
                return True
    return False


def set_responsibilities(username: str, text: str) -> bool:
    """设置成员职责定义（分配建议抓手；主 agent 据此判断需求该派给谁）。"""
    with _USERS_LOCK:
        users = _load_users()
        for u in users:
            if u.get('username') == username:
                u['responsibilities'] = (text or '').strip()
                _save_users(users)
                return True
    return False


def team_roster() -> list[dict]:
    """团队职责花名册：给审核/分配 agent 用的精简清单（用户名+角色+职责）。"""
    out = []
    for u in _load_users():
        if not u.get('active', True):
            continue
        out.append({
            'username': u.get('username'),
            'role': u.get('role', ROLE_MEMBER),
            'responsibilities': (u.get('responsibilities') or '').strip(),
        })
    return out


def reset_password(username: str, new_password: str) -> bool:
    from api.auth import _hash_password
    if not new_password or len(new_password) < 6:
        raise ValueError('密码至少 6 位')
    with _USERS_LOCK:
        users = _load_users()
        for u in users:
            if u.get('username') == username:
                u['password_hash'] = _hash_password(new_password)
                u['active_token'] = None  # 重置后强制重新登录
                _save_users(users)
                return True
    return False


# ── 登录校验 + 单点登录 ─────────────────────────────────────────────────────
def verify_user_credentials(username: str, password: str) -> dict | None:
    """校验账号密码。成功返回用户记录，失败返回 None。"""
    import hmac as _hmac
    from api.auth import _hash_password

    u = get_user(username)
    if not u or not u.get('active', True):
        return None
    if _hmac.compare_digest(_hash_password(password), u.get('password_hash', '')):
        return u
    return None


def login_user(username: str) -> tuple[str, str] | None:
    """登录：创建 session 并把 token 记为该用户的 active_token（单点登录）。

    返回 (signed_cookie_value, profile_name)；用户不存在/被停用返回 None。
    新登录会覆盖 active_token，使旧 session 在校验时被判为"被挤下线"。
    """
    from api.auth import create_session, _session_token_from_cookie_value

    with _USERS_LOCK:
        users = _load_users()
        target = None
        for u in users:
            if u.get('username') == username:
                target = u
                break
        if not target or not target.get('active', True):
            return None
        cookie_val = create_session()
        token = _session_token_from_cookie_value(cookie_val)
        target['active_token'] = token
        _save_users(users)
        return cookie_val, target.get('profile') or 'default'


def is_session_current(username: str, cookie_value: str) -> bool:
    """单点登录校验：cookie 中的 token 是否仍是该用户的 active_token。

    用于"后登录挤掉先登录"：旧 cookie 虽然签名有效，但 token 已不是
    active_token，应判为失效（被挤下线）。
    """
    from api.auth import _session_token_from_cookie_value

    u = get_user(username)
    if not u or not u.get('active', True):
        return False
    token = _session_token_from_cookie_value(cookie_value)
    return bool(token) and token == u.get('active_token')


def logout_user(username: str) -> None:
    """登出：清空 active_token。"""
    with _USERS_LOCK:
        users = _load_users()
        for u in users:
            if u.get('username') == username:
                u['active_token'] = None
                _save_users(users)
                return


def kick_user(username: str) -> bool:
    """管理员踢人：清空 active_token 使其 session 立即失效。"""
    return set_user_active(username, get_user(username).get('active', True)) if get_user(username) else False


def session_username(cookie_value: str) -> str | None:
    """反查：给定 session cookie，返回它属于哪个用户（且仍是其 active_token）。"""
    from api.auth import _session_token_from_cookie_value

    token = _session_token_from_cookie_value(cookie_value)
    if not token:
        return None
    for u in _load_users():
        if u.get('active') and u.get('active_token') == token:
            return u.get('username')
    return None


def current_request_user(handler) -> dict | None:
    """从请求 handler 的 session cookie 解析当前登录用户（脱敏记录）。

    多用户模式下返回 {'username','profile','role',...}；未启用或未登录返回 None。
    """
    if not multiuser_enabled():
        return None
    from api.auth import parse_cookie
    cookie_val = parse_cookie(handler)
    if not cookie_val:
        return None
    username = session_username(cookie_val)
    if not username:
        return None
    u = get_user(username)
    if not u:
        return None
    return {k: u.get(k) for k in ('username', 'profile', 'role', 'active', 'created_at')}


def is_request_admin(handler) -> bool:
    """当前请求是否来自 admin 用户。"""
    u = current_request_user(handler)
    return bool(u and u.get('role') == ROLE_ADMIN)
