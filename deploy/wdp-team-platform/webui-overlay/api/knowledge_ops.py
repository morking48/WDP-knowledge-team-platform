"""
Hermes Web UI -- 知识库高级操作（WDP 团队工作台，对齐原型的管理增强功能）.

admin 专属操作（对应原型工作台各视图的按钮）：
  POST /api/knowledge/merge          信号归并（多条→合并成一条，源流转为已合并）
  POST /api/knowledge/to-requirement 信号沉淀为需求（生成需求草稿写入 requirements/）
  POST /api/knowledge/new-design     新建设计稿（写入 designs/ 草稿）
  POST /api/knowledge/notify         通知组员（写入目标 owner 的 inbox 作为提醒）

个人操作：
  GET  /api/me/logs/download?file=x  下载日志文件（raw）
  POST /api/me/workspace/reindex     同步工作库索引（重扫 workspace 文件清单）

设计约束：
  - 纯标准库；写 knowledge 后 git commit（复用 review 的提交模式）
  - merge/to-requirement/new-design/notify 需 admin
"""
from __future__ import annotations

from api._wdp_types import ApiResult

import json
import logging
import subprocess
import time
from pathlib import Path

from api import knowledge as _kb

logger = logging.getLogger(__name__)


def _git_commit(root: Path, rel_path: str, msg: str) -> str:
    try:
        r = subprocess.run(['git', '-C', str(root), 'add', rel_path],
                           capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return f'git add 失败: {r.stderr[:80]}'
        r2 = subprocess.run(['git', '-C', str(root), 'commit', '-m', msg],
                            capture_output=True, text=True, timeout=10)
        return 'git 已提交' if r2.returncode == 0 else f'commit 失败: {r2.stderr[:80]}'
    except Exception as e:
        return f'git 异常: {e}'


def _next_id(category: str, prefix: str) -> str:
    """生成下一个可用 ID，如 REQ-20260722-001。

    扫描该分区所有文件的 frontmatter id（而非文件名），取当天 prefix-YYYYMMDD-NNN
    的最大序号 +1，避免与已有 id 撞车。
    """
    root = _kb.get_knowledge_root()
    today = time.strftime('%Y%m%d')
    max_n = 0
    if root:
        cat_dir = root / _kb.get_categories().get(category, category)
        if cat_dir.is_dir():
            import re as _re
            pat = _re.compile(rf'^{prefix}-{today}-(\d+)$')
            for f in cat_dir.glob('*.md'):
                if f.name.startswith('_'):
                    continue
                try:
                    meta, _ = _kb.parse_frontmatter(f.read_text(encoding='utf-8'))
                except Exception:
                    continue
                m = pat.match(str(meta.get('id', '')))
                if m:
                    max_n = max(max_n, int(m.group(1)))
    return f'{prefix}-{today}-{max_n + 1:03d}'


# ── 信号归并 ────────────────────────────────────────────────────────────────
def merge_signals(ids: list[str], new_title: str, admin_user: str,
                  new_body: str = '', new_urgency: str = '') -> ApiResult:
    """把多条信号归并成一条新信号，源信号流转为 status=已合并。

    new_body: AI 生成的归并后描述（R32，管理员在对话框中确认/修改后传入）。
    """
    if len(ids) < 2:
        return {'error': '至少选 2 条信号归并'}, 400
    root = _kb.get_knowledge_root()
    if not root:
        return {'error': 'knowledge 根不可用'}, 500

    sources = []
    for sid in ids:
        item = _kb.get_item('signals', sid)
        if item:
            sources.append(item)
    if len(sources) < 2:
        return {'error': '选中信号不足 2 条有效'}, 400

    # 生成归并后的新信号
    new_id = _next_id('signals', 'SIG')
    today = time.strftime('%Y-%m-%d')
    _urg = new_urgency or max((s.get('urgency', '低') for s in sources),
                              key=lambda x: {'高': 3, '中': 2, '低': 1}.get(x, 0))
    # R32：优先用 AI 生成+管理员确认的归并描述；无则回退为源信号罗列
    if new_body.strip():
        body_section = f"## 信号内容\n{new_body.strip()}\n\n## 源信号\n" + '\n'.join(
            f"- {s.get('id','?')} {s.get('title','')}" for s in sources)
    else:
        body_section = f"## 信号内容\n本信号由以下 {len(sources)} 条信号归并而成：\n\n" + '\n'.join(
            f"### {s.get('id','?')} · {s.get('title','')}\n{s.get('_body','').strip()[:300]}\n" for s in sources)
    merged_body = f"""---
id: {new_id}
type: 信号
date: {today}
source: 归并
source_ref: 由 {len(sources)} 条信号归并（{', '.join(s.get('id','?') for s in sources)}）
title: {new_title or '归并信号'}
description: 由 {len(sources)} 条同主题信号归并
category: {sources[0].get('category', '需求信号')}
urgency: {_urg}
confidence: {sources[0].get('confidence', '中')}
related_module: {sources[0].get('related_module', '')}
status: 待triage
raw_excerpt: 归并自 {len(sources)} 条信号
---

""" + body_section + "\n"

    cat_dir = root / _kb.get_categories().get('signals', 'signals')
    target = cat_dir / f'{today}-merged-{new_id.lower()}.md'
    target.write_text(merged_body, encoding='utf-8')
    git1 = _git_commit(root, str(target.relative_to(root)),
                       f'feat(signals): 归并 {len(sources)} 条为 {new_id} (by {admin_user})')

    # 源信号流转为「已合并」（从信号池消失，不是归档；可追溯到新信号）
    from api import knowledge_admin as _ka
    merged = []
    for s in sources:
        fpath = cat_dir / s.get('_file', '')
        if fpath.exists():
            text = fpath.read_text(encoding='utf-8')
            meta, body = _kb.parse_frontmatter(text)
            meta['status'] = '已合并'
            meta['merged_into'] = new_id
            new_text = _ka._serialize_frontmatter(meta) + '\n' + body
            fpath.write_text(new_text, encoding='utf-8')
            merged.append(s.get('id'))
    if merged:
        subprocess.run(['git', '-C', str(root), 'add', '-A'], capture_output=True, timeout=10)
        subprocess.run(['git', '-C', str(root), 'commit', '-m', f'chore(signals): 源信号流转合并 {merged} → {new_id}'],
                       capture_output=True, timeout=10)

    return {'ok': True, 'new_id': new_id, 'merged_count': len(sources), 'git': git1}


# ── 信号沉淀为需求 ──────────────────────────────────────────────────────────
def signal_to_requirement(signal_id: str, admin_user: str,
                          priority: str = 'P2', owner: str = '') -> ApiResult:
    """从信号生成需求草稿，写入 requirements/，源信号标记已转需求。"""
    sig = _kb.get_item('signals', signal_id)
    if not sig:
        return {'error': f'信号 {signal_id} 不存在'}, 404
    root = _kb.get_knowledge_root()
    if not root:
        return {'error': 'knowledge 根不可用'}, 500

    req_id = _next_id('requirements', 'REQ')
    today = time.strftime('%Y-%m-%d')
    req_body = f"""---
id: {req_id}
type: 需求
date: {today}
title: {sig.get('title', '(待补充)')}
description: 由信号 {sig.get('id','')} 沉淀的需求
status: 待校验
priority: {priority}
source_signals: [{sig.get('id', '')}]
related_module: {sig.get('related_module', '')}
owner: {owner or '待分配'}
customer: {sig.get('source_ref', '')}
business_value: (待补充：从信号延伸的业务价值)
effort_estimate: 待评估
target_release: 待定
tags: []
tracking:
  - date: {today}
    event: 建档
    note: 由信号 {sig.get('id','')} 沉淀（{admin_user}）
---

## 需求描述
（基于信号 {sig.get('id','')}，待产品经理补充完善）

{sig.get('_body', '').strip()[:400]}

## 来源信号
- [[{sig.get('id','')}]] {sig.get('title','')}

## 待澄清问题
- [ ] 需求边界待明确
- [ ] 业务价值待量化
"""
    cat_dir = root / _kb.get_categories().get('requirements', 'requirements')
    safe = (sig.get('title', 'req') or 'req')[:20].replace(' ', '-').replace('/', '-')
    target = cat_dir / f'{req_id}-{safe}.md'
    target.write_text(req_body, encoding='utf-8')
    git = _git_commit(root, str(target.relative_to(root)),
                      f'feat(requirements): {req_id} 由信号 {signal_id} 沉淀 (by {admin_user})')

    # 源信号标记已转需求
    sig_dir = root / _kb.get_categories().get('signals', 'signals')
    sig_file = sig_dir / sig.get('_file', '')
    if sig_file.exists():
        from api import knowledge_admin as _ka
        text = sig_file.read_text(encoding='utf-8')
        meta, body = _kb.parse_frontmatter(text)
        meta['status'] = '已转需求'
        sig_file.write_text(_ka._serialize_frontmatter(meta) + '\n' + body, encoding='utf-8')
        subprocess.run(['git', '-C', str(root), 'add', '-A'], capture_output=True, timeout=10)
        subprocess.run(['git', '-C', str(root), 'commit', '-m', f'chore(signals): {signal_id} 标记已转需求'],
                       capture_output=True, timeout=10)

    # 分配了负责人 → 自动通知（协作体验：对方立刻知道被分配了需求）
    if owner and owner not in ('待分配', '未分配', ''):
        try:
            notify_member(owner, f'需求 {req_id}「{sig.get("title", "")}」已分配给你，请跟进', admin_user)
        except Exception as e:
            logger.debug('to-requirement auto-notify failed: %s', e)

    return {'ok': True, 'req_id': req_id, 'git': git}


# ── 新建设计稿 ──────────────────────────────────────────────────────────────
def new_design(title: str, requirement_id: str, designer: str) -> ApiResult:
    """新建设计稿草稿，写入 designs/。"""
    if not title:
        return {'error': '标题必填'}, 400
    root = _kb.get_knowledge_root()
    if not root:
        return {'error': 'knowledge 根不可用'}, 500
    dsn_id = _next_id('designs', 'DSN')
    today = time.strftime('%Y-%m-%d')
    req_ref = requirement_id or '待关联'   # 满足模板必填（草稿可先建后关联需求）
    body = f"""---
id: {dsn_id}
type: 设计
date: {today}
title: {title}
description: {title}（草稿）
requirement_id: {req_ref}
status: 草稿
designer: {designer}
target_release: 待定
---

## 设计目标
（待补充）

## 用户场景
（待补充）

## 功能设计
（待补充）

## 数据契约
（待补充：agent 执行所需的数据结构）

## 状态与流转
（待补充）

## 边界与异常
（待补充）
"""
    cat_dir = root / _kb.get_categories().get('designs', 'designs')
    safe = title[:20].replace(' ', '-').replace('/', '-')
    target = cat_dir / f'{dsn_id}-{safe}.md'
    target.write_text(body, encoding='utf-8')
    git = _git_commit(root, str(target.relative_to(root)),
                      f'feat(designs): 新建 {dsn_id} {title} (by {designer})')
    return {'ok': True, 'design_id': dsn_id, 'git': git}


# ── 通知组员 ────────────────────────────────────────────────────────────────
def notify_member(target_username: str, message: str, from_user: str) -> ApiResult:
    """给成员发通知：写入其 profile 的 inbox/notifications.jsonl。"""
    if not target_username or not message:
        return {'error': '缺 target/message'}, 400
    try:
        from api.profiles import _DEFAULT_HERMES_HOME
        base = Path(_DEFAULT_HERMES_HOME) / 'profiles' / target_username
        if not base.is_dir():
            # admin 自己是 default profile
            base = Path(_DEFAULT_HERMES_HOME)
        inbox = base / 'inbox'
        inbox.mkdir(parents=True, exist_ok=True)
        notif = {
            'from': from_user, 'message': message,
            'at': time.strftime('%Y-%m-%d %H:%M:%S'), 'read': False,
        }
        with open(inbox / 'notifications.jsonl', 'a', encoding='utf-8') as f:
            f.write(json.dumps(notif, ensure_ascii=False) + '\n')
        return {'ok': True}
    except Exception as e:
        return {'error': str(e)}, 500


def _my_inbox(handler) -> Path | None:
    """当前登录用户的 inbox 目录。"""
    try:
        from api.profiles import get_active_hermes_home
        inbox = Path(get_active_hermes_home()) / 'inbox'
        return inbox
    except Exception:
        return None


def list_notifications(handler) -> dict:
    """读当前用户收到的通知（按时间倒序），返回未读数。"""
    inbox = _my_inbox(handler)
    items = []
    if inbox:
        nf = inbox / 'notifications.jsonl'
        if nf.is_file():
            for line in nf.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except Exception:
                    pass
    items.reverse()  # 最新在前
    unread = sum(1 for n in items if not n.get('read'))
    return {'notifications': items, 'unread': unread, 'total': len(items)}


def mark_notifications_read(handler) -> ApiResult:
    """把当前用户所有通知标记已读。"""
    inbox = _my_inbox(handler)
    if not inbox:
        return {'error': 'inbox 不可用'}, 500
    nf = inbox / 'notifications.jsonl'
    if not nf.is_file():
        return {'ok': True, 'marked': 0}
    lines = []
    marked = 0
    for line in nf.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            n = json.loads(line)
            if not n.get('read'):
                n['read'] = True
                marked += 1
            lines.append(json.dumps(n, ensure_ascii=False))
        except Exception:
            lines.append(line)
    nf.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return {'ok': True, 'marked': marked}


def get_req_decisions(item_id: str) -> dict:
    """W2：返回需求关联的决策完整内容（作为分析背景内嵌需求详情）。"""
    out = []
    try:
        for dec in _kb.scan_category('decisions'):
            rr = dec.get('related_requirements') or []
            if isinstance(rr, str):
                rr = [rr]
            if any(item_id in str(x) for x in rr):
                full = _kb.get_item('decisions', dec.get('id') or dec.get('_file') or '')
                out.append({
                    'id': dec.get('id'),
                    'title': dec.get('title'),
                    'status': dec.get('status'),
                    'decision_maker': dec.get('decision_maker'),
                    'date': dec.get('date'),
                    'body': (full or {}).get('_body', '') if full else '',
                })
    except Exception as e:
        logger.warning('get_req_decisions failed: %s', e)
    return {'decisions': out}


def get_traces(item_type: str, item_id: str) -> dict:
    """可追溯反查：返回某条目的上下游关联。
    - 信号：downstream = 引用它的需求（反查 source_signals）
    - 需求：upstream = source_signals 里的信号；downstream = requirement_id 指向它的设计
    - 设计：upstream = requirement_id 指向的需求
    """
    up, down = [], []
    try:
        if item_type == 'signals':
            for r in _kb.scan_category('requirements'):
                ss = r.get('source_signals') or []
                if isinstance(ss, str):
                    ss = [ss]
                if any(item_id in str(s) for s in ss):
                    down.append({'type': 'requirements', 'id': r.get('id'), 'title': r.get('title')})
        elif item_type == 'requirements':
            item = _kb.get_item('requirements', item_id)
            if item:
                ss = item.get('source_signals') or []
                if isinstance(ss, str):
                    ss = [ss]
                for sid in ss:
                    sid = str(sid).strip()
                    if sid:
                        si = _kb.get_item('signals', sid)
                        up.append({'type': 'signals', 'id': sid, 'title': si.get('title') if si else None})
            for d in _kb.scan_category('designs'):
                if item_id in str(d.get('requirement_id') or ''):
                    down.append({'type': 'designs', 'id': d.get('id'), 'title': d.get('title')})
            # W2：关联决策（decisions 的 related_requirements 含该需求）
            for dec in _kb.scan_category('decisions'):
                rr = dec.get('related_requirements') or []
                if isinstance(rr, str):
                    rr = [rr]
                if any(item_id in str(x) for x in rr):
                    down.append({'type': 'decisions', 'id': dec.get('id'), 'title': dec.get('title')})
        elif item_type == 'designs':
            item = _kb.get_item('designs', item_id)
            if item:
                rid = str(item.get('requirement_id') or '').strip()
                if rid and rid != '待关联':
                    ri = _kb.get_item('requirements', rid)
                    up.append({'type': 'requirements', 'id': rid, 'title': ri.get('title') if ri else None})
    except Exception as e:
        logger.warning('get_traces failed: %s', e)
    return {'upstream': up, 'downstream': down}


def list_library() -> dict:
    """列出 library 母版库内容：product-knowledge + archive 两个子区的文件树（浅层）。"""
    root = _kb.get_knowledge_root()
    if not root:
        return {'sections': []}
    sections = []
    for sub, title, desc in [
        ('library/product-knowledge', '在线知识合集（母版）', 'WDP产品知识索引 + 在线源同步脚本 + 业务场景prompt模板'),
        ('library/archive', '历史归档', '完成/上线项目的设计稿、复盘、资料沉淀'),
    ]:
        d = root / sub
        files = []
        if d.is_dir():
            for f in sorted(d.rglob('*')):
                if f.is_file() and not f.name.startswith('.') and '__pycache__' not in str(f):
                    try:
                        rel = str(f.relative_to(d)).replace('\\', '/')
                        files.append({'path': rel, 'size': f.stat().st_size})
                    except Exception:
                        pass
        sections.append({'dir': sub, 'title': title, 'desc': desc, 'files': files, 'count': len(files)})
    return {'sections': sections}


def new_decision(title: str, decision_maker: str) -> ApiResult:
    """新建决策记录草稿，写入 decisions/。"""
    if not title:
        return {'error': '标题必填'}, 400
    root = _kb.get_knowledge_root()
    if not root:
        return {'error': 'knowledge 根不可用'}, 500
    dec_id = _next_id('decisions', 'DEC')
    today = time.strftime('%Y-%m-%d')
    body = f"""---
id: {dec_id}
type: 决策
date: {today}
title: {title}
description: {title}
status: 生效中
decision_maker: {decision_maker}
participants: []
related_requirements: []
related_module: ''
---

## 决策内容
（待补充）

## 背景与问题
（待补充）

## 最终决策
（待补充）

## 影响与后果
（待补充）
"""
    cat_dir = root / _kb.get_categories().get('decisions', 'decisions')
    safe = title[:20].replace(' ', '-').replace('/', '-')
    target = cat_dir / f'{dec_id}-{safe}.md'
    target.write_text(body, encoding='utf-8')
    git = _git_commit(root, str(target.relative_to(root)),
                      f'feat(decisions): 新建 {dec_id} {title} (by {decision_maker})')
    return {'ok': True, 'decision_id': dec_id, 'git': git}


def get_user_stats(username: str, profile: str) -> dict:
    """统计单个用户的用量：session数 / 入库贡献 / 工作库占用。

    - sessions：profile 的 webui/sessions 或 sessions 目录下 .json 数
    - contributions：knowledge git log 里 "by <user>" 的入库提交数
    - storage：profile/workspace 目录大小（MB）
    """
    from pathlib import Path
    sessions = 0
    contributions = 0
    storage_mb = 0.0
    try:
        from api.profiles import _DEFAULT_HERMES_HOME
        base = Path(_DEFAULT_HERMES_HOME) / 'profiles' / profile
        if not base.is_dir():
            base = Path(_DEFAULT_HERMES_HOME)  # admin=default
        # sessions
        for sd in [base / 'sessions', base / 'webui' / 'sessions']:
            if sd.is_dir():
                sessions += sum(1 for f in sd.glob('*.json') if not f.name.startswith('_'))
        # workspace 占用
        ws = base / 'workspace'
        if ws.is_dir():
            total = sum(f.stat().st_size for f in ws.rglob('*') if f.is_file())
            storage_mb = round(total / (1024 * 1024), 2)
    except Exception as e:
        logger.debug('get_user_stats profile part failed: %s', e)
    # 入库贡献：从 knowledge git log 数 "by <username>"
    try:
        import subprocess
        root = _kb.get_knowledge_root()
        if root:
            r = subprocess.run(['git', '-C', str(root), 'log', '--oneline', '--grep', f'by {username}'],
                               capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                contributions = len([l for l in r.stdout.splitlines() if l.strip()])
    except Exception as e:
        logger.debug('get_user_stats git part failed: %s', e)
    return {'sessions': sessions, 'contributions': contributions, 'storage_mb': storage_mb}


def archive_delete(category: str, item_id: str, operator: str = 'admin') -> ApiResult:
    """R6 删除：把条目移到 library/archive/_deleted/（软删除），30天后 cron 真删。保留 git 可追溯。"""
    import shutil
    root = _kb.get_knowledge_root()
    if not root:
        return {'error': 'knowledge 根不可用'}, 500
    cats = _kb.get_categories()
    if category not in cats:
        return {'error': f'非法类目 {category}'}, 400
    cat_dir = root / cats.get(category, category)
    item = _kb.get_item(category, item_id)
    if not item or not item.get('_file'):
        return {'error': f'条目不存在 {item_id}'}, 404
    src = cat_dir / item['_file']
    if not src.exists():
        return {'error': '源文件不存在'}, 404
    arc_dir = root / 'library' / 'archive' / '_deleted' / category
    arc_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime('%Y%m%d-%H%M%S')
    dst = arc_dir / f'{ts}__{item["_file"]}'
    try:
        shutil.move(str(src), str(dst))
    except Exception as e:
        return {'error': f'移动失败: {e}'}, 500
    try:
        subprocess.run(['git', '-C', str(root), 'add', '-A'], capture_output=True, timeout=10)
        subprocess.run(['git', '-C', str(root), 'commit', '-m',
                        f'chore({category}): 删除 {item_id} → 归档待清理 (by {operator})'],
                       capture_output=True, timeout=10)
    except Exception:
        pass
    return {'ok': True, 'archived_to': str(dst.relative_to(root)).replace('\\', '/'), 'item_id': item_id}


def purge_expired_deleted(retention_days: int = 30) -> dict:
    """cron：真删 library/archive/_deleted/ 里超过 retention_days 的文件。"""
    root = _kb.get_knowledge_root()
    if not root:
        return {'purged': 0}
    ddir = root / 'library' / 'archive' / '_deleted'
    if not ddir.is_dir():
        return {'purged': 0}
    now = time.time()
    purged = []
    for f in ddir.rglob('*'):
        if f.is_file():
            age = (now - f.stat().st_mtime) / 86400
            if age >= retention_days:
                try:
                    f.unlink()
                    purged.append(str(f.relative_to(root)).replace('\\', '/'))
                except Exception:
                    pass
    if purged:
        try:
            subprocess.run(['git', '-C', str(root), 'add', '-A'], capture_output=True, timeout=10)
            subprocess.run(['git', '-C', str(root), 'commit', '-m',
                            f'chore: cron 清理 {len(purged)} 个过期删除文件'],
                           capture_output=True, timeout=10)
        except Exception:
            pass
    return {'purged': len(purged), 'files': purged}


def team_output_board() -> dict:
    """R12：团队工作产出看板——统计各成员的信号/需求/设计产出 + 贡献。"""
    board = {}
    def _ensure(u):
        if u and u not in board:
            board[u] = {'username': u, 'requirements': 0, 'designs': 0, 'signals': 0,
                        'req_online': 0, 'req_active': 0}
        return u
    try:
        for r in _kb.scan_category('requirements'):
            o = (r.get('owner') or '').strip()
            if o and o not in ('待分配', '未分配'):
                _ensure(o); board[o]['requirements'] += 1
                if r.get('status') == '已上线':
                    board[o]['req_online'] += 1
                elif r.get('status') != '已关闭':
                    board[o]['req_active'] += 1
        for d in _kb.scan_category('designs'):
            o = (d.get('designer') or '').strip()
            if o:
                _ensure(o); board[o]['designs'] += 1
        for s in _kb.scan_category('signals'):
            o = (s.get('assignee') or '').strip()
            if o:
                _ensure(o); board[o]['signals'] += 1
    except Exception as e:
        logger.warning('team_output_board failed: %s', e)
    rows = list(board.values())
    for r in rows:
        r['total_output'] = r['requirements'] * 3 + r['designs'] * 2 + r['signals']
    rows.sort(key=lambda x: x['total_output'], reverse=True)
    return {'board': rows}
