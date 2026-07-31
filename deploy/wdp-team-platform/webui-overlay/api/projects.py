"""WDP 团队工作台 · 项目分区（售前/售后项目档案）.

数据模型（Q1 定案：按项目建子目录，物理隔离）：
  knowledge/projects/
    _template.md / _req_template.md / _dlv_template.md   模板
    <项目目录名>/
      project.md          项目档案（PRJ-xxx，含 customer/phase/owner）
      requirements/       项目需求（PREQ-xxx，从公共信号池沉淀转入，带 source_signals）
      deliverables/       交付材料（DLV-xxx，必须绑定 requirement_id，含售前/售中/售后 phase）

流转（Q2/Q3 定案）：
  - 开档：成员提交开档申请 → 决策中心审核通过 → 建档（管理员也可直接开档）
  - 信号入口统一：项目相关信号先进 signals/，再「沉淀为项目需求」时选项目
  - 交付材料必绑项目需求（类比 设计绑需求）
"""
from __future__ import annotations

from api._wdp_types import ApiResult

import logging
import re
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_DIR_RE = re.compile(r'^[\w\u4e00-\u9fff][\w\u4e00-\u9fff-]{0,62}$')  # 中英文目录名


def _projects_root() -> Path:
    from api.knowledge import get_knowledge_root
    root = get_knowledge_root()
    if not root:
        raise RuntimeError('knowledge 根目录不可用')
    return Path(root) / 'projects'


def _parse_fm(text: str) -> dict:
    """极简 frontmatter 解析（与 knowledge.py 同风格，纯标准库）。"""
    out = {}
    m = re.match(r'^---\s*\n(.*?)\n---', text, re.DOTALL)
    if not m:
        return out
    for line in m.group(1).splitlines():
        if ':' not in line or line.strip().startswith('#'):
            continue
        k, v = line.split(':', 1)
        k = k.strip()
        v = v.split('#')[0].strip().strip('"\'')
        if v.startswith('[') and v.endswith(']'):
            inner = v[1:-1].strip()
            out[k] = [x.strip().strip('"\'') for x in inner.split(',') if x.strip()] if inner else []
        else:
            out[k] = v
    return out


def _body_of(text: str) -> str:
    m = re.match(r'^---\s*\n.*?\n---\s*\n?', text, re.DOTALL)
    return text[m.end():] if m else text


def _git_commit(msg: str):
    """写操作后 git commit + 自动 push（与 review.py 同模式，失败不阻塞）。"""
    import subprocess
    root = _projects_root().parent
    try:
        subprocess.run(['git', 'add', '-A', 'projects/'], cwd=str(root),
                       capture_output=True, timeout=15)
        subprocess.run(['git', 'commit', '-m', msg], cwd=str(root),
                       capture_output=True, timeout=15)
        # commit 成功后自动推远程（后台静默，失败只记日志——防"只commit不push"积压）
        try:
            from api.knowledge_ops import _git_push_async
            _git_push_async(root)
        except Exception:
            pass
    except Exception as e:
        logger.warning('projects git commit failed: %s', e)
    # 项目数据变了 → 实时刷新知识库索引（对话 agent 导航用）
    try:
        from api.team_tasks import refresh_index
        refresh_index()
    except Exception as e:
        logger.debug('refresh_index after project write failed: %s', e)


def _next_id(prefix: str, scan_dirs: list) -> str:
    """扫描 frontmatter id 字段算下一个序号（不能靠文件名，见 skill 撞车教训）。"""
    today = time.strftime('%Y%m%d')
    pat = re.compile(r'^' + re.escape(prefix) + r'-' + today + r'-(\d+)$')
    mx = 0
    for d in scan_dirs:
        if not d.is_dir():
            continue
        for f in d.rglob('*.md'):
            if f.name.startswith('_'):
                continue
            try:
                fm = _parse_fm(f.read_text(encoding='utf-8'))
                m = pat.match(fm.get('id', ''))
                if m:
                    mx = max(mx, int(m.group(1)))
            except Exception:
                pass
    return f'{prefix}-{today}-{mx + 1:03d}'


# ══════════════════════════════════════════════════════════════════
#  项目档案
# ══════════════════════════════════════════════════════════════════

def list_projects() -> dict:
    """列出所有项目（读各项目目录的 project.md）+ 需求/材料计数。"""
    root = _projects_root()
    projects = []
    if root.is_dir():
        for d in sorted(root.iterdir()):
            if not d.is_dir() or d.name.startswith(('_', '.')):
                continue
            pm = d / 'project.md'
            if not pm.is_file():
                continue
            try:
                fm = _parse_fm(pm.read_text(encoding='utf-8'))
            except Exception:
                fm = {}
            req_n = len([f for f in (d / 'requirements').glob('*.md')
                         if not f.name.startswith('_')]) if (d / 'requirements').is_dir() else 0
            dlv_n = len([f for f in (d / 'deliverables').glob('*.md')
                         if not f.name.startswith('_')]) if (d / 'deliverables').is_dir() else 0
            projects.append({
                'dir': d.name,
                'id': fm.get('id', ''),
                'title': fm.get('title', d.name),
                'customer': fm.get('customer', ''),
                'phase': fm.get('phase', ''),
                'owner': fm.get('owner', ''),
                'status': fm.get('status', ''),
                'description': fm.get('description', ''),
                'req_count': req_n,
                'dlv_count': dlv_n,
            })
    return {'projects': projects}


def create_project(body: dict, creator: str) -> ApiResult:
    """建档（管理员直接建，或审核通过后由 review 调用）。"""
    pdir = (body.get('dir') or body.get('title') or '').strip()
    title = (body.get('title') or pdir).strip()
    if not _DIR_RE.match(pdir):
        return {'error': '项目目录名需为中英文/数字/中划线（1-63字符）'}, 400
    root = _projects_root()
    d = root / pdir
    if (d / 'project.md').is_file():
        return {'error': f'项目「{pdir}」已存在'}, 409
    customer = (body.get('customer') or '').strip() or '待补充'
    # 客户级软去重：同一客户已有项目时，除非显式 force，提示已有项目防冗余开档
    if customer and customer != '待补充' and not body.get('force'):
        existing = []
        try:
            for p in root.glob('*/project.md'):
                m = _parse_fm(p.read_text(encoding='utf-8'))
                if (m.get('customer') or '').strip() == customer:
                    existing.append({'dir': p.parent.name, 'title': m.get('title', p.parent.name),
                                     'phase': m.get('phase', '')})
        except Exception:
            pass
        if existing:
            return {'error': f'客户「{customer}」已有 {len(existing)} 个项目，确认要另开新项目吗？',
                    'code': 'CUSTOMER_HAS_PROJECT', 'customer': customer,
                    'existing': existing,
                    'hint': '若确为不同项目，重试时带 force=true；否则请把需求归到已有项目'}, 409
    phase = (body.get('phase') or '售前').strip()
    owner = (body.get('owner') or creator or '待分配').strip()
    desc = (body.get('description') or '').strip() or f'{customer} 项目'
    opportunity = (body.get('opportunity') or '').strip() or '待补充'   # 商机号
    bd_owner = (body.get('bd_owner') or '').strip() or '待补充'          # BD 负责人
    tb_contact = (body.get('tb_contact') or '').strip() or '待补充'      # TB 对接人（客户侧）
    pid = _next_id('PRJ', [root])
    today = time.strftime('%Y-%m-%d')
    content = f"""---
id: {pid}
type: project
date: {today}
title: {title}
description: {desc}
customer: {customer}
opportunity: {opportunity}
phase: {phase}
owner: {owner}
bd_owner: {bd_owner}
tb_contact: {tb_contact}
status: 进行中
---

# {title}

## 项目背景

{body.get('background') or desc}

## 关键干系人

| 角色 | 姓名 | 备注 |
|---|---|---|
| 我方负责人 | {owner} |  |
| BD 负责人 | {bd_owner} |  |
| 客户 TB 对接人 | {tb_contact} | {customer} |

## 商机信息

- 商机号：{opportunity}
- 阶段：{phase}

## 里程碑

| 节点 | 时间 | 状态 |
|---|---|---|

## 备注

开档人：{creator} · {today}
"""
    try:
        (d / 'requirements').mkdir(parents=True, exist_ok=True)
        (d / 'deliverables').mkdir(parents=True, exist_ok=True)
        (d / 'project.md').write_text(content, encoding='utf-8')
    except Exception as e:
        return {'error': f'建档失败: {e}'}, 500
    _git_commit(f'项目开档: {pdir} ({pid}) by {creator}')
    return {'ok': True, 'dir': pdir, 'id': pid, 'message': f'项目「{title}」已开档'}


def get_project(pdir: str) -> ApiResult:
    """项目详情：档案全文 + 需求列表 + 交付材料列表。"""
    d = _projects_root() / pdir
    pm = d / 'project.md'
    if not pm.is_file():
        return {'error': '项目不存在'}, 404
    text = pm.read_text(encoding='utf-8')
    fm = _parse_fm(text)
    reqs, dlvs = [], []
    rdir = d / 'requirements'
    if rdir.is_dir():
        for f in sorted(rdir.glob('*.md')):
            if f.name.startswith('_'):
                continue
            rf = _parse_fm(f.read_text(encoding='utf-8'))
            rf['_file'] = f.name
            reqs.append(rf)
    ddir = d / 'deliverables'
    if ddir.is_dir():
        for f in sorted(ddir.glob('*.md')):
            if f.name.startswith('_'):
                continue
            df = _parse_fm(f.read_text(encoding='utf-8'))
            df['_file'] = f.name
            dlvs.append(df)
    return {'dir': pdir, 'meta': fm, 'body': _body_of(text),
            'requirements': reqs, 'deliverables': dlvs}


def delete_project(pdir: str, operator: str = 'admin') -> ApiResult:
    """删除整个项目：软删除 projects/<pdir>/ 目录到 library/archive/_deleted/projects/。

    项目是目录容器（project.md + requirements/ + deliverables/），不能走单文件的
    archive_delete，需整目录移动。软删除保留 git 可追溯，30天后 cron 真删（与其它类目一致）。
    """
    import shutil
    root = _projects_root().parent   # knowledge 根
    d = _projects_root() / pdir
    pm = d / 'project.md'
    if not pm.is_file():
        return {'error': f'项目不存在: {pdir}'}, 404
    # 取项目名（用于提交信息）
    try:
        title = _parse_fm(pm.read_text(encoding='utf-8')).get('title', pdir)
    except Exception:
        title = pdir
    arc_dir = root / 'library' / 'archive' / '_deleted' / 'projects'
    arc_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime('%Y%m%d-%H%M%S')
    dst = arc_dir / f'{ts}__{pdir}'
    try:
        shutil.move(str(d), str(dst))
    except Exception as e:
        return {'error': f'移动失败: {e}'}, 500
    _git_commit(f'chore(projects): 删除项目「{title}」({pdir}) → 归档待清理 (by {operator})')
    return {'ok': True, 'archived_to': str(dst.relative_to(root)).replace('\\', '/'), 'project': pdir}


def update_project_field(pdir: str, field: str, value: str, admin: str,
                         expect: str | None = None) -> ApiResult:
    """改项目档案 frontmatter 字段。支持逐步补充（字段不存在则新增）+ 乐观锁。

    expect 传入时做乐观锁：若档案里该字段现值 != expect（期间被别人改过），返回 409 冲突，
    附当前值让调用方决定是否覆盖——不锁卡片、不阻塞并发，只在真冲突时提示。
    """
    allowed = {'phase', 'owner', 'status', 'customer', 'description',
               'opportunity', 'bd_owner', 'tb_contact', 'background', 'title'}
    if field not in allowed:
        return {'error': f'不允许修改字段 {field}'}, 400
    pm = _projects_root() / pdir / 'project.md'
    if not pm.is_file():
        return {'error': '项目不存在'}, 404
    text = pm.read_text(encoding='utf-8')
    # 读现值（乐观锁校验用）
    cur_m = re.search(rf'^{field}:(.*)$', text, flags=re.MULTILINE)
    cur_val = (cur_m.group(1).strip().strip('"\'') if cur_m else '')
    if expect is not None and cur_val != expect.strip():
        return {'error': '冲突：该字段已被更新', 'current': cur_val,
                'your_base': expect, 'field': field}, 409
    if cur_m:
        new_text = re.sub(rf'(^{field}:).*$', rf'\1 {value}', text, count=1, flags=re.MULTILINE)
    else:
        # 逐步补充：字段原本不存在 → 插到 frontmatter 末尾（--- 前）
        m2 = re.match(r'^(---\s*\n.*?)(\n---)', text, re.DOTALL)
        if not m2:
            return {'error': '档案 frontmatter 格式异常'}, 422
        new_text = m2.group(1) + f'\n{field}: {value}' + text[m2.end(1):]
    pm.write_text(new_text, encoding='utf-8')
    _git_commit(f'项目 {pdir}: {field} → {value} by {admin}')
    return {'ok': True, 'field': field, 'value': value}


# ══════════════════════════════════════════════════════════════════
#  项目需求（含 信号 → 项目需求 沉淀）
# ══════════════════════════════════════════════════════════════════

def submit_to_project_req(pdir: str, content: str, meta: dict, admin_user: str,
                          owner: str = '', priority: str = '') -> ApiResult:
    """审核入库时：把一条'带项目归属的需求'直接落进 projects/<pdir>/requirements/（PREQ）。
    不经过公共池——related_project 命中已开档项目时的直路。"""
    from api import knowledge as _kb
    d = _projects_root() / pdir
    if not (d / 'project.md').is_file():
        return {'error': f'项目 {pdir} 未开档'}, 404
    # 解析提交内容的 frontmatter（title/description/priority/owner）
    fm, body = {}, content
    try:
        m = re.match(r'^---\s*\n(.*?)\n---\s*\n?(.*)$', content, re.DOTALL)
        if m:
            for line in m.group(1).splitlines():
                if ':' in line and not line.strip().startswith('#'):
                    k, v = line.split(':', 1)
                    fm[k.strip()] = v.split('#')[0].strip().strip('"\'')
            body = m.group(2)
    except Exception:
        pass
    preq_id = _next_id('PREQ', [_projects_root()])
    today = time.strftime('%Y-%m-%d')
    title = fm.get('title') or meta.get('title', '(待补充)')
    desc = (fm.get('description') or title)[:120]
    prio = priority or fm.get('priority') or '中'
    own = owner or fm.get('owner') or '待分配'
    preq = f"""---
id: {preq_id}
type: project_requirement
date: {today}
title: {title}
description: {desc}
project: {pdir}
status: {fm.get('status', '待评估')}
priority: {prio}
owner: {own}
---

{body.strip()}

## 备注
由 {admin_user} 审核入库为项目「{pdir}」需求 · {today}
"""
    fname = f'{today}-{preq_id}.md'
    try:
        (d / 'requirements').mkdir(parents=True, exist_ok=True)
        (d / 'requirements' / fname).write_text(preq, encoding='utf-8')
    except Exception as e:
        return {'error': f'写入失败: {e}'}, 500
    if own and own not in ('待分配', '未分配', ''):
        try:
            from api.knowledge_ops import notify_member
            notify_member(own, f'项目「{pdir}」需求 {preq_id}「{title}」已分配给你，请跟进', admin_user)
        except Exception:
            pass
    _git_commit(f'审核入库 → 项目需求 {preq_id} ({pdir}) by {admin_user}')
    return {'ok': True, 'id': preq_id, 'project': pdir,
            'final_path': f'projects/{pdir}/requirements/{fname}',
            'message': f'已入库为项目「{pdir}」的需求 {preq_id}'}


def project_dir_by_name(name: str) -> str:
    """按项目名/客户名模糊匹配已开档项目，返回 dir（找不到返回空串）。"""
    if not name:
        return ''
    name = name.strip()
    try:
        for p in _projects_root().glob('*/project.md'):
            meta, _ = __import__('api.knowledge', fromlist=['parse_frontmatter']).parse_frontmatter(
                p.read_text(encoding='utf-8'))
            pdir = p.parent.name
            if name in (pdir, meta.get('title', ''), meta.get('customer', '')) \
               or name in pdir or pdir in name \
               or (meta.get('title') and (name in meta['title'] or meta['title'] in name)):
                return pdir
    except Exception:
        pass
    return ''


def signal_to_project_req(signal_id: str, pdir: str, admin_user: str,
                          owner: str = '') -> ApiResult:
    """把公共信号池的一条信号沉淀为某项目的项目需求（Q3：信号入口统一）。

    照 knowledge_ops.signal_to_requirement 模式：生成 PREQ、源信号标记已流转、
    指定 owner 时发通知。
    """
    from api import knowledge as _kb
    d = _projects_root() / pdir
    if not (d / 'project.md').is_file():
        return {'error': '项目不存在'}, 404
    # 找源信号
    sig = None
    for s in _kb.scan_category('signals'):
        if (s.get('id') or '') == signal_id:
            sig = s
            break
    if not sig:
        return {'error': f'信号 {signal_id} 不存在'}, 404
    preq_id = _next_id('PREQ', [_projects_root()])
    today = time.strftime('%Y-%m-%d')
    title = sig.get('title', '')
    body_excerpt = (sig.get('_body') or sig.get('raw_excerpt') or '')[:800]
    content = f"""---
id: {preq_id}
type: project_requirement
date: {today}
title: {title}
description: {(sig.get('description') or title)[:120]}
project: {pdir}
source_signals: [{signal_id}]
status: 待评估
priority: {'高' if sig.get('urgency') == '高' else '中'}
owner: {owner or '待分配'}
---

# {title}

## 需求描述（源自信号 {signal_id}）

{body_excerpt}

## 需求边界

- 范围内：（待项目负责人明确）
- 范围外：

## 备注

由 {admin_user} 从公共信号池沉淀 · {today}
"""
    fname = f'{today}-{preq_id}.md'
    try:
        (d / 'requirements').mkdir(parents=True, exist_ok=True)
        (d / 'requirements' / fname).write_text(content, encoding='utf-8')
    except Exception as e:
        return {'error': f'写入失败: {e}'}, 500
    # 源信号标记已流转（与转需求同状态语义）——直接改文件（照 knowledge_ops 模式）
    try:
        from api import knowledge_admin as _ka
        kb_root = _projects_root().parent
        sig_dir = kb_root / _kb.get_categories().get('signals', 'signals')
        sig_file = sig_dir / sig.get('_file', '')
        if sig_file.exists():
            stext = sig_file.read_text(encoding='utf-8')
            smeta, sbody = _kb.parse_frontmatter(stext)
            smeta['status'] = '已转需求'
            sig_file.write_text(_ka._serialize_frontmatter(smeta) + '\n' + sbody, encoding='utf-8')
    except Exception as e:
        logger.warning('mark signal converted failed: %s', e)
    # 指定负责人 → 通知（协作对称律）
    if owner and owner not in ('待分配', '未分配', ''):
        try:
            from api.knowledge_ops import notify_member
            notify_member(owner, f'项目「{pdir}」需求 {preq_id}「{title}」已分配给你，请跟进', admin_user)
        except Exception:
            pass
    _git_commit(f'信号 {signal_id} → 项目需求 {preq_id} ({pdir}) by {admin_user}')
    return {'ok': True, 'id': preq_id, 'project': pdir,
            'message': f'已沉淀为项目「{pdir}」的需求 {preq_id}'}


def update_project_req(pdir: str, fname: str, updates: dict, admin: str) -> ApiResult:
    """改项目需求字段（status/priority/owner 流转）。"""
    f = _projects_root() / pdir / 'requirements' / Path(fname).name
    if not f.is_file():
        return {'error': '项目需求不存在'}, 404
    text = f.read_text(encoding='utf-8')
    allowed = {'status', 'priority', 'owner', 'title', 'description'}
    changed = []
    for k, v in (updates or {}).items():
        if k not in allowed:
            continue
        text, n = re.subn(rf'(^{k}:).*$', rf'\1 {v}', text, count=1, flags=re.MULTILINE)
        if n:
            changed.append(k)
    if not changed:
        return {'error': '无有效修改字段'}, 400
    f.write_text(text, encoding='utf-8')
    if 'owner' in changed:
        new_owner = updates.get('owner', '')
        if new_owner and new_owner not in ('待分配', '未分配'):
            try:
                from api.knowledge_ops import notify_member
                notify_member(new_owner, f'项目「{pdir}」需求「{Path(fname).stem}」已分配给你', admin)
            except Exception:
                pass
    _git_commit(f'项目需求更新 {pdir}/{fname}: {",".join(changed)} by {admin}')
    return {'ok': True, 'changed': changed}


# ══════════════════════════════════════════════════════════════════
#  交付材料（必绑项目需求）
# ══════════════════════════════════════════════════════════════════

def create_deliverable(pdir: str, body: dict, creator: str) -> ApiResult:
    d = _projects_root() / pdir
    if not (d / 'project.md').is_file():
        return {'error': '项目不存在'}, 404
    req_id = (body.get('requirement_id') or '').strip()
    if not req_id:
        return {'error': '交付材料必须绑定项目需求（requirement_id 必填）'}, 422
    # 校验绑定的需求真实存在于该项目
    rdir = d / 'requirements'
    found = False
    if rdir.is_dir():
        for f in rdir.glob('*.md'):
            if f.name.startswith('_'):
                continue
            if _parse_fm(f.read_text(encoding='utf-8')).get('id') == req_id:
                found = True
                break
    if not found:
        return {'error': f'项目「{pdir}」下不存在需求 {req_id}，先沉淀需求再建材料'}, 422
    title = (body.get('title') or '').strip()
    if not title:
        return {'error': '标题必填'}, 400
    phase = (body.get('phase') or '售前').strip()
    dlv_id = _next_id('DLV', [_projects_root()])
    today = time.strftime('%Y-%m-%d')
    content = f"""---
id: {dlv_id}
type: deliverable
date: {today}
title: {title}
description: {(body.get('description') or title)[:120]}
project: {pdir}
requirement_id: {req_id}
phase: {phase}
status: 草稿
---

# {title}

## 材料内容

{body.get('content') or '（待补充）'}

## 交付记录

| 时间 | 交付对象 | 方式 | 备注 |
|---|---|---|---|

（创建人：{creator} · {today}）
"""
    fname = f'{today}-{dlv_id}.md'
    try:
        (d / 'deliverables').mkdir(parents=True, exist_ok=True)
        (d / 'deliverables' / fname).write_text(content, encoding='utf-8')
    except Exception as e:
        return {'error': f'写入失败: {e}'}, 500
    _git_commit(f'交付材料 {dlv_id} ({pdir}, 绑定 {req_id}) by {creator}')
    return {'ok': True, 'id': dlv_id, 'message': f'交付材料 {dlv_id} 已创建（{phase}，绑定 {req_id}）'}


def update_deliverable(pdir: str, fname: str, updates: dict, admin: str) -> ApiResult:
    f = _projects_root() / pdir / 'deliverables' / Path(fname).name
    if not f.is_file():
        return {'error': '交付材料不存在'}, 404
    text = f.read_text(encoding='utf-8')
    allowed = {'status', 'phase', 'title', 'description'}
    changed = []
    for k, v in (updates or {}).items():
        if k not in allowed:
            continue
        text, n = re.subn(rf'(^{k}:).*$', rf'\1 {v}', text, count=1, flags=re.MULTILINE)
        if n:
            changed.append(k)
    if not changed:
        return {'error': '无有效修改字段'}, 400
    f.write_text(text, encoding='utf-8')
    _git_commit(f'交付材料更新 {pdir}/{fname}: {",".join(changed)} by {admin}')
    return {'ok': True, 'changed': changed}


def get_item_body(pdir: str, kind: str, fname: str) -> ApiResult:
    """读项目需求/交付材料正文（详情展开用）。"""
    sub = 'requirements' if kind == 'req' else 'deliverables'
    f = _projects_root() / pdir / sub / Path(fname).name
    if not f.is_file():
        return {'error': '文件不存在'}, 404
    text = f.read_text(encoding='utf-8')
    return {'meta': _parse_fm(text), 'body': _body_of(text)}
