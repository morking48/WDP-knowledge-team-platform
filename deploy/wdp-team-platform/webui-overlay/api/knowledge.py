"""
Hermes Web UI -- 团队知识库 API（WDP 团队工作台 R1 扩展）.

提供工作台三 tab 所需的只读接口：
  GET /api/knowledge/signals        信号列表（解析 knowledge/signals/*.md frontmatter）
  GET /api/knowledge/requirements   需求列表
  GET /api/knowledge/designs        设计稿列表
  GET /api/knowledge/item?type=signals&id=<id>   单条详情（含正文）
  GET /api/knowledge/stats          汇总统计（各层数量/状态分布）

设计约束：
  - 纯标准库，无新增依赖
  - knowledge/ 为单一数据源，本模块只读；写操作走 R8 管理接口
  - knowledge 路径定位：优先 HERMES_KNOWLEDGE_DIR 环境变量；
    否则按 active profile 的 HERMES_HOME/knowledge（add-user.sh 已建符号链接）
  - frontmatter 用极简 YAML 子集解析（key: value / list / dict），
    避免引入 PyYAML 依赖
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# ── 分区注册表（从 knowledge.config.yaml 动态加载，长线可扩展）──────────────
# 兜底：config 读不到时用这份硬编码，保证服务不崩。
_FALLBACK_CATEGORIES = {
    'signals': 'signals',
    'requirements': 'requirements',
    'designs': 'designs',
    'decisions': 'decisions',
    'tracking': 'tracking',
}

# 缓存：{'categories': {name: dir}, 'config': full_dict, 'mtime': float}
_config_cache: dict = {}


def _load_config() -> dict:
    """读 knowledge.config.yaml，返回完整 config dict。带 mtime 缓存 + 兜底。"""
    root = get_knowledge_root()
    if not root:
        return {}
    cfg_path = root / 'knowledge.config.yaml'
    if not cfg_path.is_file():
        return {}
    try:
        mtime = cfg_path.stat().st_mtime
        if _config_cache.get('mtime') == mtime and 'config' in _config_cache:
            return _config_cache['config']
        import yaml
        cfg = yaml.safe_load(cfg_path.read_text(encoding='utf-8')) or {}
        _config_cache['config'] = cfg
        _config_cache['mtime'] = mtime
        return cfg
    except Exception as e:
        logger.warning('load knowledge.config.yaml failed: %s', e)
        return {}


def get_categories() -> dict:
    """返回工作文件区分区 {name: dir}。从 config 的 working 段加载，兜底硬编码。

    只有 working 区的分区可通过 /api/knowledge/<cat> 读写（library 是母版/归档，
    不走信号/需求那套流转接口）。
    """
    cfg = _load_config()
    working = (cfg or {}).get('working') or {}
    if not working:
        return dict(_FALLBACK_CATEGORIES)
    out = {}
    for name, spec in working.items():
        if isinstance(spec, dict) and spec.get('dir'):
            out[name] = spec['dir']
        else:
            out[name] = name
    return out


def get_category_spec(name: str) -> dict:
    """返回某分区的完整配置（含 template/required_fields/enforce_template）。"""
    cfg = _load_config()
    working = (cfg or {}).get('working') or {}
    return working.get(name) or {}


def validate_against_template(category: str, content: str) -> dict:
    """按分区模板校验 frontmatter 必填字段（单一数据源：config 的 required_fields）。

    返回 {
      'ok': bool,              # 是否通过（enforce_template=false 时恒 True，但仍给 missing 供软提示）
      'enforce': bool,         # 该分区是否开启硬校验
      'missing': [字段名...],  # 缺失的必填字段
      'message': str,          # 人类可读提示
    }
    """
    spec = get_category_spec(category)
    required = spec.get('required_fields') or []
    enforce = bool(spec.get('enforce_template'))
    if not required:
        return {'ok': True, 'enforce': enforce, 'missing': [], 'message': ''}

    meta, _ = parse_frontmatter(content or '')
    missing = []
    for field in required:
        v = meta.get(field)
        # 空/None/空串/空列表 都算缺失
        if v is None or v == '' or v == [] or (isinstance(v, str) and not v.strip()):
            missing.append(field)

    if not missing:
        return {'ok': True, 'enforce': enforce, 'missing': [], 'message': ''}

    title = spec.get('title', category)
    msg = f'{title}缺少必填字段：{"、".join(missing)}（按模板 _template.md 补全 frontmatter）'
    # enforce=True 时 ok=False（硬拦截）；否则 ok=True 但带 missing（软提示）
    return {'ok': not enforce, 'enforce': enforce, 'missing': missing, 'message': msg}


# 向后兼容：老代码用 CATEGORIES 常量的地方仍可工作（返回快照）。
# 注意：新代码应调 get_categories() 拿最新值。
CATEGORIES = _FALLBACK_CATEGORIES


# ── knowledge 根路径定位 ────────────────────────────────────────────────────
def get_knowledge_root() -> Path | None:
    """定位团队 knowledge/ 目录。

    优先级：
      1. 环境变量 HERMES_KNOWLEDGE_DIR
      2. active profile 的 HERMES_HOME/knowledge（add-user.sh 建的符号链接）
      3. 默认 HERMES_HOME 的同级 knowledge/（本地开发兜底；生产一律用 HERMES_KNOWLEDGE_DIR）
    """
    env = os.getenv('HERMES_KNOWLEDGE_DIR', '').strip()
    if env:
        p = Path(env)
        if p.is_dir():
            return p

    try:
        from api.profiles import get_active_hermes_home
        home = get_active_hermes_home()
        # profile 下的 knowledge 符号链接（成员视角）
        p = Path(home) / 'knowledge'
        if p.is_dir():
            return p
        # 默认 home 的同级 knowledge/（admin / 本地开发视角）
        p2 = Path(home).parent / 'knowledge'
        if p2.is_dir() and (p2 / 'signals').exists():
            return p2
    except Exception as e:
        logger.debug("get_knowledge_root profile lookup failed: %s", e)
    return None


# ── frontmatter 解析（极简 YAML 子集）────────────────────────────────────────
_FM_RE = re.compile(r'^---\s*\n(.*?)\n---\s*\n', re.DOTALL)


def _parse_scalar(v: str):
    v = v.strip()
    if not v:
        return ''
    if v in ('true', 'True'):
        return True
    if v in ('false', 'False'):
        return False
    if v in ('null', 'None', '~'):
        return None
    if v.startswith('[') and v.endswith(']'):
        inner = v[1:-1].strip()
        if not inner:
            return []
        return [x.strip().strip('"\'') for x in inner.split(',')]
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """解析 markdown frontmatter。返回 (meta_dict, body)。

    支持：一级 key: value、一级 key 下缩进 2 格的 list (- item) 和 dict (k: v)。
    够覆盖 signals/requirements/designs 模板的字段，不追求完整 YAML。
    """
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    fm_block = m.group(1)
    body = text[m.end():]
    meta: dict = {}
    lines = fm_block.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.strip().startswith('#'):
            i += 1
            continue
        # 一级 key
        if not line.startswith((' ', '\t')):
            km = re.match(r'^([A-Za-z_][\w-]*)\s*:\s*(.*)$', line)
            if not km:
                i += 1
                continue
            key, val = km.group(1), km.group(2)
            if val:
                meta[key] = _parse_scalar(val)
                i += 1
            else:
                # 可能是 list 或 dict，往下看缩进行
                items = []
                sub_dict: dict = {}
                j = i + 1
                is_list = False
                while j < len(lines):
                    sub = lines[j]
                    if sub.strip() and not sub.startswith((' ', '\t')):
                        break
                    s = sub.strip()
                    if s.startswith('- '):
                        is_list = True
                        # list item 可能是 scalar 或 "k: v" 起始
                        item_txt = s[2:]
                        if ':' in item_txt and not item_txt.startswith(('"', "'")):
                            # dict item，如 "- date: 2026-07-20"
                            dm = re.match(r'^([\w-]+)\s*:\s*(.*)$', item_txt)
                            if dm:
                                item = {dm.group(1): _parse_scalar(dm.group(2))}
                                # 后续缩进更深的行属于这个 dict item
                                k = j + 1
                                while k < len(lines):
                                    deep = lines[k]
                                    if deep.startswith('    ') and deep.strip():
                                        dm2 = re.match(r'^\s*([\w-]+)\s*:\s*(.*)$', deep)
                                        if dm2:
                                            item[dm2.group(1)] = _parse_scalar(dm2.group(2))
                                            k += 1
                                            continue
                                    break
                                items.append(item)
                                j = k - 1
                            else:
                                items.append(item_txt)
                        else:
                            items.append(_parse_scalar(item_txt))
                    elif ':' in s:
                        dm = re.match(r'^([\w-]+)\s*:\s*(.*)$', s)
                        if dm:
                            sub_dict[dm.group(1)] = _parse_scalar(dm.group(2))
                    j += 1
                if is_list:
                    meta[key] = items
                elif sub_dict:
                    meta[key] = sub_dict
                else:
                    meta[key] = None
                i = j
        else:
            i += 1
    return meta, body


# ── 扫描某类目下的所有 md ────────────────────────────────────────────────────
def scan_category(category: str) -> list[dict]:
    """扫描 knowledge/<dir>/*.md，返回 [{meta..., _file, _excerpt}...]"""
    cats = get_categories()
    if category not in cats:
        return []
    root = get_knowledge_root()
    if not root:
        return []
    cat_dir = root / cats[category]
    if not cat_dir.is_dir():
        return []
    out = []
    for f in sorted(cat_dir.glob('*.md'), reverse=True):
        if f.name.startswith('_'):  # 跳过 _template.md
            continue
        try:
            text = f.read_text(encoding='utf-8')
        except Exception as e:
            logger.warning("read %s failed: %s", f, e)
            continue
        meta, body = parse_frontmatter(text)
        # 取正文首个非空非标题行做摘要
        excerpt = ''
        for ln in body.split('\n'):
            ln = ln.strip()
            if ln and not ln.startswith('#') and not ln.startswith('>'):
                excerpt = ln[:120]
                break
        item = dict(meta)
        item['_file'] = f.name
        item['_category'] = category
        item['_excerpt'] = excerpt
        item['_mtime'] = int(f.stat().st_mtime)
        out.append(item)
    return out


def get_item(category: str, file_or_id: str) -> dict | None:
    """取单条详情（含正文）。file_or_id 可以是文件名或 frontmatter id。"""
    cats = get_categories()
    if category not in cats:
        return None
    root = get_knowledge_root()
    if not root:
        return None
    cat_dir = root / cats[category]
    if not cat_dir.is_dir():
        return None
    # 先按文件名找
    cand = cat_dir / file_or_id
    if not cand.suffix:
        cand = cat_dir / (file_or_id + '.md')
    target = cand if cand.exists() else None
    # 找不到就按 frontmatter id 找
    if target is None:
        for f in cat_dir.glob('*.md'):
            if f.name.startswith('_'):
                continue
            try:
                meta, _ = parse_frontmatter(f.read_text(encoding='utf-8'))
            except Exception:
                continue
            if meta.get('id') == file_or_id:
                target = f
                break
    if target is None:
        return None
    try:
        text = target.read_text(encoding='utf-8')
    except Exception:
        return None
    meta, body = parse_frontmatter(text)
    item = dict(meta)
    item['_file'] = target.name
    item['_category'] = category
    item['_body'] = body
    item['_mtime'] = int(target.stat().st_mtime)
    return item


def get_stats() -> dict:
    """工作台顶部汇总：各层数量、状态分布、最近更新。

    count = 全部数量；active_count = 池内活跃数量（排除已流转出池的状态）。
    保证「同一任务在信号池和需求池唯一」——信号转需求后从信号活跃统计中移除。
    """
    # 各分区「已流转出池」的状态（这些条目已流转到下一层，不再计入本层活跃统计）
    _FLOWED_OUT = {
        'signals': {'已转需求', '已合并'},   # 信号流转出池：转需求 / 归并（去掉"已归档"，R14）
        'requirements': {'已关闭'},          # 需求关闭后不占活跃
        'designs': {'已废弃'},
        'decisions': {'已废弃', '已被取代'},
        'tracking': set(),
    }
    stats: dict = {'categories': {}, 'total': 0, 'active_total': 0}
    for cat in get_categories():
        items = scan_category(cat)
        status_dist: dict = {}
        for it in items:
            s = it.get('status') or '未标注'
            status_dist[s] = status_dist.get(s, 0) + 1
        flowed = _FLOWED_OUT.get(cat, set())
        active = [it for it in items if (it.get('status') or '') not in flowed]
        stats['categories'][cat] = {
            'count': len(items),
            'active_count': len(active),   # 池内活跃（排除已流转）
            'status_distribution': status_dist,
            'latest_mtime': max((it['_mtime'] for it in items), default=0),
        }
        stats['total'] += len(items)
        stats['active_total'] += len(active)
    # 项目子分区（PREQ 项目需求 / DLV 交付材料）计入对应统计——
    # 项目档案本身不单列统计（项目是容器），但项目下属的需求/材料要算进来。
    try:
        root = get_knowledge_root()
        if root:
            projects_dir = root / get_categories().get('projects', 'projects')
            preq_n = dlv_n = 0
            if projects_dir.is_dir():
                for pdir in projects_dir.iterdir():
                    if not pdir.is_dir() or pdir.name.startswith('_'):
                        continue
                    rq = pdir / 'requirements'
                    dl = pdir / 'deliverables'
                    if rq.is_dir():
                        preq_n += len([f for f in rq.glob('*.md') if not f.name.startswith('_')])
                    if dl.is_dir():
                        dlv_n += len([f for f in dl.glob('*.md') if not f.name.startswith('_')])
            # PREQ 计入需求统计（项目需求也是需求，工作台「需求」badge 含项目需求）
            if 'requirements' in stats['categories']:
                stats['categories']['requirements']['count'] += preq_n
                stats['categories']['requirements']['active_count'] += preq_n
                stats['categories']['requirements']['project_req_count'] = preq_n
            stats['total'] += preq_n + dlv_n
            stats['active_total'] += preq_n + dlv_n
            stats['project_requirements'] = preq_n
            stats['project_deliverables'] = dlv_n
    except Exception as e:
        logger.debug('get_stats project sub-count failed: %s', e)
    return stats


# ── HTTP handler ─────────────────────────────────────────────────────────────
def handle_knowledge_list(handler, parsed, category: str):
    """GET /api/knowledge/<category>?status=xx&owner=xx&q=xx"""
    from urllib.parse import parse_qs
    qs = parse_qs(parsed.query)
    items = scan_category(category)
    # 简单筛选
    if 'status' in qs:
        want = qs['status'][0]
        items = [i for i in items if i.get('status') == want]
    if 'owner' in qs:
        want = qs['owner'][0]
        items = [i for i in items if i.get('owner') == want]
    if 'q' in qs:
        q = qs['q'][0].lower()
        items = [i for i in items
                 if q in str(i.get('title', '')).lower()
                 or q in str(i.get('_excerpt', '')).lower()]
    return {'items': items, 'count': len(items), 'category': category}


def handle_knowledge_item(handler, parsed):
    """GET /api/knowledge/item?type=signals&id=<id 或 文件名>"""
    from urllib.parse import parse_qs
    qs = parse_qs(parsed.query)
    cat = (qs.get('type') or [''])[0]
    fid = (qs.get('id') or [''])[0]
    if not cat or not fid:
        return {'error': '缺 type 或 id 参数'}, 400
    item = get_item(cat, fid)
    if item is None:
        return {'error': '未找到'}, 404
    return {'item': item}


def handle_knowledge_stats(handler, parsed):
    """GET /api/knowledge/stats"""
    return get_stats()
