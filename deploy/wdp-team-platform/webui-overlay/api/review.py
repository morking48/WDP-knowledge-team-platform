"""
Hermes Web UI -- 入库审核 API（WDP 团队工作台 R3 扩展）.

流程（对应设计文档 §10 主子 Agent 分层）：
  成员 chat 中说"提交入库" → 个人 Agent 把产出写到 profiles/<user>/inbox/
    附一份《入库建议说明》（建议目录/命名/摘要/关联冲突分析）
  主 Agent / 管理员在「入库审核」tab 看到待审列表
  管理员确认（可内嵌 chat 沟通细节）→ 执行入库：
    - 移文件到 knowledge/<category>/<规范命名>.md
    - git add + commit
    - 从 inbox 移除（归档到 .inbox-archive/）
  驳回 → 退回 inbox 并附理由（成员 chat 里能看到）

接口：
  GET  /api/review/list                    待审列表（所有用户 inbox 汇总；admin）
  GET  /api/review/item?user=<u>&file=<f>  待审详情（含产出全文+建议说明）
  POST /api/review/submit                  成员侧提交入库申请（写自己 inbox）
  POST /api/review/approve                 admin 通过（移文件+git commit+归档）
  POST /api/review/reject                  admin 驳回（附理由）

设计约束：
  - 纯标准库
  - 多用户模式下：submit 只能写自己的 inbox；list/approve/reject 需要 admin
  - inbox 路径：active profile 的 HERMES_HOME/inbox（成员提交）；
    admin 看到的是 profiles 根下所有用户的 inbox 汇总
"""
from __future__ import annotations

from api._wdp_types import ApiResult

import json
import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from api import knowledge as _kb

logger = logging.getLogger(__name__)

INBOX_DIRNAME = 'inbox'
ARCHIVE_DIRNAME = '.inbox-archive'


# ── 路径定位 ────────────────────────────────────────────────────────────────
def _profiles_root() -> Path | None:
    """profiles 根目录（多用户模式下所有用户的 profile 父目录）。"""
    try:
        from api.profiles import _DEFAULT_HERMES_HOME
        root = Path(_DEFAULT_HERMES_HOME) / 'profiles'
        return root if root.is_dir() else None
    except Exception:
        return None


def _user_inbox(profile: str) -> Path | None:
    """某用户 profile 下的 inbox 目录（不存在则返回 None）。"""
    root = _profiles_root()
    if not root:
        return None
    if profile in ('default', ''):
        # admin 的 default profile 就是 HERMES_HOME 本体
        try:
            from api.profiles import _DEFAULT_HERMES_HOME
            p = Path(_DEFAULT_HERMES_HOME) / INBOX_DIRNAME
        except Exception:
            return None
    else:
        p = root / profile / INBOX_DIRNAME
    return p


def _active_profile_inbox() -> Path | None:
    """当前请求用户的 inbox（按 active profile）。"""
    try:
        from api.profiles import get_active_hermes_home, get_active_profile_name
        home = Path(get_active_hermes_home())
        p = home / INBOX_DIRNAME
        return p
    except Exception:
        return None


# ── 提交入库（成员侧）─────────────────────────────────────────────────────
def submit_request(profile: str, username: str, title: str, category: str,
                   content: str, suggestion: dict) -> ApiResult:
    """成员提交入库申请：写 inbox/<ts>-<safe-title>.md + .meta.json"""
    inbox = _user_inbox(profile)
    if inbox is None:
        return {'error': 'inbox 不可用'}, 500
    inbox.mkdir(parents=True, exist_ok=True)
    # 文件名：时间戳 + 安全化标题
    ts = time.strftime('%Y%m%d-%H%M%S')
    safe = re.sub(r'[^\w\u4e00-\u9fff-]+', '-', title)[:40].strip('-') or 'untitled'
    fname = f'{ts}-{safe}.md'
    fpath = inbox / fname
    try:
        fpath.write_text(content, encoding='utf-8')
        # meta 记录提交人/类目/建议
        meta = {
            'username': username,
            'profile': profile,
            'title': title,
            'category': category,
            'submitted_at': ts,
            'file': fname,
            'suggestion': suggestion,  # {suggested_name, target_category, summary, conflict_analysis}
            'status': 'pending',
        }
        (inbox / (fname + '.meta.json')).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception as e:
        logger.error("submit_request write failed: %s", e)
        return {'error': f'写入失败: {e}'}, 500
    # R16：通知所有管理员有新的入库申请（协作闭环）
    try:
        from api import users as _users
        from api import knowledge_ops as _ops
        for u in _users.list_users():
            if u.get('role') == 'admin':
                _ops.notify_member(u.get('username') or '',
                                   f'📥 {username} 提交了入库申请「{title}」（{category}），请审核',
                                   'system')
    except Exception as e:
        logger.warning("submit notify admins failed: %s", e)
    return {'ok': True, 'file': fname}


# ── 待审列表（admin）───────────────────────────────────────────────────────
def list_pending() -> list[dict]:
    """扫所有用户 inbox，返回所有 pending 申请（按时间倒序）。"""
    root = _profiles_root()
    if not root:
        return []
    out = []
    # 包括 default profile（HERMES_HOME 本体）和所有命名 profile
    candidates = []
    try:
        from api.profiles import _DEFAULT_HERMES_HOME
        default_inbox = Path(_DEFAULT_HERMES_HOME) / INBOX_DIRNAME
        if default_inbox.is_dir():
            candidates.append(('default', default_inbox))
    except Exception:
        pass
    for d in root.iterdir():
        if not d.is_dir():
            continue
        inbox = d / INBOX_DIRNAME
        if inbox.is_dir():
            candidates.append((d.name, inbox))
    for profile, inbox in candidates:
        for meta_file in inbox.glob('*.meta.json'):
            try:
                meta = json.loads(meta_file.read_text(encoding='utf-8'))
            except Exception:
                continue
            if meta.get('status') != 'pending':
                continue
            meta['_profile'] = profile
            meta['_meta_file'] = meta_file.name
            out.append(meta)
    out.sort(key=lambda x: x.get('submitted_at', ''), reverse=True)
    return out


def get_pending_item(profile: str, fname: str) -> dict | None:
    """取单个待审详情：正文 + meta。"""
    inbox = _user_inbox(profile)
    if not inbox:
        return None
    fpath = inbox / fname
    meta_file = inbox / (fname + '.meta.json')
    if not fpath.exists() or not meta_file.exists():
        return None
    try:
        content = fpath.read_text(encoding='utf-8')
        meta = json.loads(meta_file.read_text(encoding='utf-8'))
    except Exception:
        return None
    return {'content': content, 'meta': meta}


# ── 通过入库（admin）───────────────────────────────────────────────────────
def approve(profile: str, fname: str, final_name: str | None,
            final_category: str | None, admin_note: str, admin_user: str,
            extra_fields: dict | None = None) -> ApiResult:
    """通过：移文件到 knowledge/<cat>/<final_name>.md，git commit，inbox 归档。

    extra_fields: 审核时补充的 frontmatter 字段（如设计的 designer/target_release），
    写入前合并进内容——审核是补齐字段的最后闸口。
    """
    item = get_pending_item(profile, fname)
    if not item:
        return {'error': '待审项不存在'}, 404
    meta = item['meta']
    content = item['content']

    # 目标位置：优先用管理员的最终决定，回落到建议
    suggestion = meta.get('suggestion') or {}
    category = final_category or suggestion.get('target_category') or meta.get('category') or 'signals'
    if category not in _kb.get_categories():
        return {'error': f'非法类目 {category}'}, 400
    target_name = final_name or suggestion.get('suggested_name') or fname
    # 规范化：必须 .md 结尾
    if not target_name.endswith('.md'):
        target_name += '.md'

    # ── 项目开档申请：不平铺写文件，走 projects.create_project 建目录结构 ──
    if category == 'projects':
        fm = {}
        try:
            import re as _re
            m = _re.match(r'^---\s*\n(.*?)\n---', content, _re.DOTALL)
            if m:
                for line in m.group(1).splitlines():
                    if ':' in line and not line.strip().startswith('#'):
                        k, v = line.split(':', 1)
                        fm[k.strip()] = v.split('#')[0].strip().strip('"\'')
        except Exception:
            pass
        from api import projects as _prj
        res = _prj.create_project({
            'dir': fm.get('title') or target_name[:-3],
            'title': fm.get('title') or target_name[:-3],
            'customer': fm.get('customer', ''),
            'phase': fm.get('phase', '售前'),
            'owner': fm.get('owner', '') or meta.get('username', ''),
            'description': fm.get('description', ''),
            'background': '',
        }, creator=meta.get('username', admin_user))
        if isinstance(res, tuple):
            return res
        # inbox 归档 + 通知提交人（复用下方逻辑的简化版）
        try:
            inbox = _user_inbox(profile)
            if inbox is None:
                raise RuntimeError('inbox 目录不可用')
            archive = inbox.parent / ARCHIVE_DIRNAME / time.strftime('%Y%m%d-%H%M%S')
            archive.mkdir(parents=True, exist_ok=True)
            shutil.move(str(inbox / fname), str(archive / fname))
            meta['status'] = 'approved'
            meta['resolved_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
            mf = inbox / (fname + '.meta.json')
            if mf.exists():
                (archive / (fname + '.meta.json')).write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
                mf.unlink()
        except Exception as e:
            logger.warning('project approve archive failed: %s', e)
        try:
            from api import knowledge_ops as _ops
            _ops.notify_member(meta.get('username', ''),
                               f'✅ 你的项目开档申请「{res.get("dir","")}」已通过，项目已建档', admin_user)
        except Exception:
            pass
        try:
            from api.agent_dialog import purge_dialog_by_ref
            purge_dialog_by_ref('review', {'user': profile, 'file': fname})
        except Exception:
            pass
        return {'ok': True, 'category': 'projects', 'project': res.get('dir'),
                'message': res.get('message', '项目已开档')}

    # 审核补充字段：合并进 frontmatter（放模板校验前，补的字段也参与校验）
    if extra_fields:
        try:
            import re as _re
            m = _re.match(r'^(---\s*\n)(.*?)(\n---)', content, _re.DOTALL)
            if m:
                fm_text = m.group(2)
                for k, v in extra_fields.items():
                    if not v or not str(k).strip():
                        continue
                    k = str(k).strip()
                    # 已有该字段则替换值，没有则追加
                    pat = _re.compile(r'^' + _re.escape(k) + r':.*$', _re.MULTILINE)
                    if pat.search(fm_text):
                        fm_text = pat.sub(f'{k}: {v}', fm_text)
                    else:
                        fm_text = fm_text + f'\n{k}: {v}'
                content = m.group(1) + fm_text + m.group(3) + content[m.end():]
        except Exception as e:
            logger.warning('merge extra_fields failed: %s', e)

    # 模板校验（触点2：管理员审核入库时，二次守门）
    vr = _kb.validate_against_template(category, content)
    if not vr['ok']:
        return {'error': f'入库校验未通过：{vr["message"]}', 'missing': vr['missing'], 'stage': 'approve'}, 422

    # 写到 knowledge/
    kb_root = _kb.get_knowledge_root()
    if not kb_root:
        return {'error': 'knowledge 根不可用'}, 500
    target_dir = kb_root / _kb.get_categories().get(category, category)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / target_name
    if target_path.exists():
        return {'error': f'目标已存在 {target_name}，请改命名'}, 409
    try:
        target_path.write_text(content, encoding='utf-8')
    except Exception as e:
        return {'error': f'写入 knowledge 失败: {e}'}, 500

    # git commit（失败不阻塞，记 warning）
    git_msg = ''
    try:
        r = subprocess.run(
            ['git', '-C', str(kb_root), 'add', str(target_path.relative_to(kb_root))],
            capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            commit_msg = f'feat({category}): 入库 {target_name} (by {meta.get("username")}, 审核 {admin_user})'
            r2 = subprocess.run(['git', '-C', str(kb_root), 'commit', '-m', commit_msg],
                                capture_output=True, text=True, timeout=10)
            if r2.returncode == 0:
                git_msg = 'git 已提交'
            else:
                git_msg = f'git commit 失败: {r2.stderr[:100]}'
        else:
            git_msg = f'git add 失败: {r.stderr[:100]}'
    except Exception as e:
        git_msg = f'git 调用异常: {e}'

    # inbox 归档（移到 .inbox-archive/<profile>/<ts>/）
    try:
        inbox = _user_inbox(profile)
        if inbox is None:
            raise RuntimeError('inbox 目录不可用')
        archive = inbox.parent / ARCHIVE_DIRNAME / time.strftime('%Y%m%d-%H%M%S')
        archive.mkdir(parents=True, exist_ok=True)
        shutil.move(str(inbox / fname), str(archive / fname))
        # meta 更新 + 也归档
        meta['status'] = 'approved'
        meta['resolved_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
        meta['resolved_by'] = admin_user
        meta['admin_note'] = admin_note
        meta['final_path'] = f'{category}/{target_name}'
        (archive / (fname + '.meta.json')).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
        (inbox / (fname + '.meta.json')).unlink(missing_ok=True)
    except Exception as e:
        logger.error("archive failed: %s", e)

    # R18：通知提交人审核通过（协作闭环回程）
    try:
        from api import knowledge_ops as _ops
        submitter = meta.get('username') or profile
        title = meta.get('title') or fname
        if submitter:
            _ops.notify_member(submitter,
                               f'✅ 你的入库申请「{title}」已通过审核，已正式入库到 {category}/',
                               'system')
    except Exception as e:
        logger.warning("approve notify submitter failed: %s", e)

    # 入库成功 → 实时刷新知识库索引（对话 agent 导航用）
    try:
        from api.team_tasks import refresh_index
        refresh_index()
    except Exception as e:
        logger.debug('refresh_index after approve failed: %s', e)

    # 审批完成 → 后端主动清除该待审项的协作对话（防旧讨论残留串到同名新提交）
    try:
        from api.agent_dialog import purge_dialog_by_ref
        purge_dialog_by_ref('review', {'user': profile, 'file': fname})
    except Exception:
        pass

    return {'ok': True, 'final_path': f'{category}/{target_name}', 'git': git_msg}


# ── 驳回 ──────────────────────────────────────────────────────────────────
def reject(profile: str, fname: str, reason: str, admin_user: str) -> ApiResult:
    """驳回：更新 meta.status=rejected 附理由，文件留在 inbox 让成员修订。"""
    inbox = _user_inbox(profile)
    if not inbox:
        return {'error': 'inbox 不可用'}, 500
    fpath = inbox / fname
    meta_file = inbox / (fname + '.meta.json')
    if not meta_file.exists():
        return {'error': '待审项不存在'}, 404
    try:
        meta = json.loads(meta_file.read_text(encoding='utf-8'))
        meta['status'] = 'rejected'
        meta['resolved_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
        meta['resolved_by'] = admin_user
        meta['reject_reason'] = reason
        meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception as e:
        return {'error': f'更新失败: {e}'}, 500
    # R18：通知提交人被驳回 + 理由（协作闭环回程）
    try:
        from api import knowledge_ops as _ops
        submitter = meta.get('username') or profile
        title = meta.get('title') or fname
        if submitter:
            _ops.notify_member(submitter,
                               f'↩ 你的入库申请「{title}」被驳回，理由：{reason}。可修订后重新提交。',
                               'system')
    except Exception as e:
        logger.warning("reject notify submitter failed: %s", e)
    # 驳回完成 → 后端主动清除该待审项的协作对话（成员修订后重新提交=新一轮审核，不接旧讨论）
    try:
        from api.agent_dialog import purge_dialog_by_ref
        purge_dialog_by_ref('review', {'user': profile, 'file': fname})
    except Exception:
        pass
    return {'ok': True}


# ── HTTP handlers ────────────────────────────────────────────────────────────
def handle_review_list(handler, parsed):
    return {'items': list_pending()}


def handle_review_item(handler, parsed):
    from urllib.parse import parse_qs
    qs = parse_qs(parsed.query)
    profile = (qs.get('user') or [''])[0]
    fname = (qs.get('file') or [''])[0]
    if not profile or not fname:
        return {'error': '缺参数'}, 400
    item = get_pending_item(profile, fname)
    if not item:
        return {'error': '未找到'}, 404
    return item


def handle_review_submit(handler, body):
    from api import users as _users
    u = _users.current_request_user(handler)
    if not u:
        return {'error': '未登录'}, 401
    title = (body.get('title') or '').strip()
    category = (body.get('category') or '').strip()
    content = body.get('content') or ''
    suggestion = body.get('suggestion') or {}
    if not title or not content:
        return {'error': '标题/正文不能为空'}, 400
    if category and category not in _kb.get_categories():
        return {'error': f'非法类目 {category}'}, 400
    # 模板校验：按分区 required_fields 检查 frontmatter（触点1：成员提交时）
    if category:
        vr = _kb.validate_against_template(category, content)
        if not vr['ok']:
            return {'error': vr['message'], 'missing': vr['missing'], 'stage': 'submit'}, 422
        # 软提示：enforce=false 但缺字段，附 warning 不阻断
        if vr['missing']:
            res = submit_request(u['profile'], u['username'], title, category, content, suggestion)
            if isinstance(res, dict):
                res['warning'] = vr['message']
            return res
    return submit_request(u['profile'], u['username'], title, category, content, suggestion)


def handle_review_approve(handler, body):
    from api import users as _users
    u = _users.current_request_user(handler)
    if not u:
        return {'error': '未登录'}, 401
    profile = (body.get('user') or '').strip()
    fname = (body.get('file') or '').strip()
    final_name = (body.get('final_name') or '').strip() or None
    final_category = (body.get('final_category') or '').strip() or None
    note = (body.get('note') or '').strip()
    extra = body.get('extra_fields') or {}
    if not isinstance(extra, dict):
        extra = {}
    if not profile or not fname:
        return {'error': '缺参数'}, 400
    return approve(profile, fname, final_name, final_category, note, u['username'],
                   extra_fields=extra)


def handle_review_reject(handler, body):
    from api import users as _users
    u = _users.current_request_user(handler)
    if not u:
        return {'error': '未登录'}, 401
    profile = (body.get('user') or '').strip()
    fname = (body.get('file') or '').strip()
    reason = (body.get('reason') or '').strip()
    if not profile or not fname or not reason:
        return {'error': '缺参数（reason 必填）'}, 400
    return reject(profile, fname, reason, u['username'])
