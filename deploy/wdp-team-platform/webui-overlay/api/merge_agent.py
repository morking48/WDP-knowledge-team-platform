"""
WDP 团队工作台 · 归并 Agent（R10）.

真 LLM 驱动的信号自动归并分析：
  1. 读所有活跃信号（池内）
  2. 用团队默认模型（OpenRouter/kimi-k3）+ 团队可调教的「归并规则 prompt」分析
  3. 返回可归并的信号分组建议，管理员在弹框做最终决策

团队规则：存 knowledge/team-tasks.json 同级或团队 SOUL；这里用独立配置 merge-rule.txt。
"""
from __future__ import annotations

from api._wdp_types import ApiResult

import json
import logging
import os
import re
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_RULE = """你是 WDP 产品团队的信号归并助手。给你一批"信号"（用户反馈/问题/需求线索），
请找出**主题相同或高度相关、应该合并成一条**的信号分组。

归并原则：
- 同一个功能点/模块的重复反馈 → 合并
- 描述同一问题的不同来源 → 合并
- 主题不同、模块不同的 → 不要强行合并
- 只有 1 条的孤立信号不算一组

对每个建议的归并组，给出：组内信号ID列表、归并后的建议标题、归并理由。"""


def _team_home() -> Path:
    env = os.getenv('HERMES_HOME', '').strip()
    if env:
        return Path(env)
    try:
        from api.profiles import _DEFAULT_HERMES_HOME
        return Path(_DEFAULT_HERMES_HOME)
    except Exception:
        return Path.home() / '.hermes'


def _rule_path() -> Path:
    return _team_home() / 'merge-rule.txt'


def _llm_call(key: str, model: str, prompt: str, max_tokens: int = 4000,
              title: str = 'WDP Agent', _retried: bool = False) -> str:
    """R45 同款容错的 LLM 调用：content=None 容错 + finish_reason=length 自动加大重试。

    归并/审核助手此前裸调用（max_tokens 2000/800），kimi-k3 推理模型思考吃掉
    token 后输出被截断 → JSON 解析炸 → 前端报错。统一走这里根治。
    """
    body = json.dumps({
        'model': model,
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': 0.2,
        'max_tokens': max_tokens,
    }).encode('utf-8')
    req = urllib.request.Request(
        'https://openrouter.ai/api/v1/chat/completions',
        data=body,
        headers={
            'Authorization': f'Bearer {key}',
            'Content-Type': 'application/json',
            'HTTP-Referer': 'https://wdp-team-workbench',
            'X-Title': title,
        })
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    choice = (data.get('choices') or [{}])[0]
    content = choice.get('message', {}).get('content') or ''
    if not isinstance(content, str):
        content = str(content)
    finish = choice.get('finish_reason')
    if finish == 'length' and not _retried:
        # 截断：加大 max_tokens 整体重试一次（推理模型思考也占额度，翻倍再来）
        logger.info('%s LLM 输出被截断(length)，加大 max_tokens 重试', title)
        return _llm_call(key, model, prompt, max_tokens=max_tokens * 2,
                         title=title, _retried=True)
    if not content.strip():
        raise RuntimeError(f'模型返回为空（finish_reason={finish}），请重试')
    return content


def _extract_json(content: str) -> dict:
    """从 LLM 输出提取 JSON，失败给可读错误而非裸异常。"""
    m = re.search(r'\{.*\}', content, re.DOTALL)
    if not m:
        raise RuntimeError('模型未返回有效 JSON（回复可能被截断），请重试')
    try:
        return json.loads(m.group(0))
    except Exception:
        raise RuntimeError('模型返回的 JSON 无法解析（可能被截断），请重试')


def get_merge_rule() -> str:
    p = _rule_path()
    if p.is_file():
        try:
            return p.read_text(encoding='utf-8')
        except Exception:
            pass
    return _DEFAULT_RULE


def save_merge_rule(content: str) -> ApiResult:
    try:
        _rule_path().write_text(content or _DEFAULT_RULE, encoding='utf-8')
        return {'ok': True}
    except Exception as e:
        return {'error': str(e)}, 500


# ── 审核规则（审核助手的调教规则，与归并规则平级）──────────────────
_DEFAULT_REVIEW_RULE = """你是 WDP 产品团队知识库的审核助手，协助管理员审核成员提交的入库申请。

审核原则：
- 质量：内容是否具体、有事实依据，避免空泛描述；必填字段是否完整。
- 查重：与现有知识库条目对比，主题重复的标记重复风险并指出疑似条目。
- 归类：判断申请归入 signals/requirements/designs/decisions/projects 哪个类目最合适（projects=项目开档申请：内容是给某个售前/售后项目立项建档）。
- 分配：适合跟进的申请，按成员职责给出建议负责人。
- 建议驳回时给出具体、可改进的理由（发给提交人）。"""


def _review_rule_path() -> Path:
    return _team_home() / 'review-rule.txt'


def get_review_rule() -> str:
    p = _review_rule_path()
    if p.is_file():
        try:
            return p.read_text(encoding='utf-8')
        except Exception:
            pass
    return _DEFAULT_REVIEW_RULE


def save_review_rule(content: str) -> ApiResult:
    try:
        _review_rule_path().write_text(content or _DEFAULT_REVIEW_RULE, encoding='utf-8')
        return {'ok': True}
    except Exception as e:
        return {'error': str(e)}, 500


def _team_key_and_model():
    """从团队 .env + config.yaml 读 OpenRouter key 和默认模型。"""
    home = _team_home()
    key = ''
    env_file = home / '.env'
    if env_file.is_file():
        m = re.search(r'OPENROUTER_API_KEY\s*=\s*(\S+)', env_file.read_text(encoding='utf-8'))
        if m:
            key = m.group(1).strip().strip('"').strip("'")
    if not key:
        key = os.getenv('OPENROUTER_API_KEY', '')
    model = 'moonshotai/kimi-k3'
    provider = 'openrouter'
    cfg_file = home / 'config.yaml'
    if cfg_file.is_file():
        try:
            import yaml
            cfg = yaml.safe_load(cfg_file.read_text(encoding='utf-8')) or {}
            m = cfg.get('model') or {}
            model = m.get('default', model)
            provider = m.get('provider', provider)
        except Exception:
            pass
    return key, model, provider


def analyze_merge(admin_user: str = 'admin') -> ApiResult:
    """读活跃信号，调 LLM 分析可归并组，返回建议。"""
    from api import knowledge as _kb
    signals = [s for s in _kb.scan_category('signals')
               if (s.get('status') or '') not in ('已转需求', '已合并', '已归档')]
    if len(signals) < 2:
        return {'ok': True, 'groups': [], 'message': '活跃信号少于 2 条，无需归并'}

    key, model, provider = _team_key_and_model()
    if not key:
        return {'error': '团队未配置 OpenRouter Key，无法调用归并 Agent'}, 500

    # 组装信号清单（excerpt 给足依据：120→300 字，判归并更准）
    sig_list = []
    for s in signals:
        sig_list.append({
            'id': s.get('id') or s.get('_file'),
            'title': s.get('title', ''),
            'category': s.get('category', ''),
            'module': s.get('related_module', ''),
            'urgency': s.get('urgency', ''),
            'excerpt': (s.get('raw_excerpt') or s.get('_body', ''))[:300],
        })

    # ── 优化A：代码粗筛分桶（related_module + category）──
    # 归并只可能发生在「同模块同类别」内；不同桶的信号本就不该合。
    # 好处：①信号多时不全池混喂 LLM（省token、防错配）②信号少时行为不变。
    buckets = {}
    for s in sig_list:
        bkey = (s.get('module') or '(无模块)', s.get('category') or '(无类别)')
        buckets.setdefault(bkey, []).append(s)
    # 只保留 ≥2 条的桶（单条无从归并）；把桶信息给 LLM，让它在桶内判断
    candidate_buckets = {k: v for k, v in buckets.items() if len(v) >= 2}
    if not candidate_buckets:
        return {'ok': True, 'groups': [], 'model': model, 'analyzed': len(signals),
                'message': f'分析了 {len(signals)} 条活跃信号，未发现同模块同类别的重复信号（无需归并）'}
    # 有效候选 id 集合（优化B 自校验用）
    valid_ids = {s['id'] for v in candidate_buckets.values() for s in v}
    # 分桶后的清单（LLM 只在同桶内找组）
    bucketed = []
    for (mod, cat), items in candidate_buckets.items():
        bucketed.append({'module': mod, 'category': cat, 'signals': items})

    rule = get_merge_rule()
    # 简化session架构：注入团队历史归并决策(few-shot)，越用越贴合团队风格
    history = ''
    try:
        from api.wdp_agent_log import few_shot_block, history_stats
        history = few_shot_block('merge', 5)
        hist_count = history_stats('merge').get('count', 0)
    except Exception:
        hist_count = 0
    prompt = f"""{rule}
{history}
以下信号已按【模块+类别】分桶（归并只能在同一桶内发生，不同桶的信号不要合并）：
{json.dumps(bucketed, ensure_ascii=False, indent=2)}

请在每个桶内部找出「主题相同、应合并成一条」的信号组。只返回 JSON：
{{"groups": [{{"signal_ids": ["SIG-x","SIG-y"], "suggested_title": "归并后标题",
  "suggested_body": "归并后新信号的完整描述（150字内：综合各源信号的问题本质、影响面、客户诉求）",
  "suggested_urgency": "高/中/低（取组内最高）",
  "reason": "归并理由"}}]}}
规则：①只合并同一桶内的信号，signal_ids 必须来自上面清单里真实存在的 id ②每组至少 2 条 ③没有可归并的组返回 {{"groups": []}}。不要输出 JSON 以外的任何文字。"""

    try:
        content = _llm_call(key, model, prompt, max_tokens=4000, title='WDP Merge Agent')
        parsed = _extract_json(content)
        groups = parsed.get('groups', [])
        # ── 优化B：结果自校验（防 LLM 幻觉/跨桶乱配）──
        by_id = {s['id']: s for s in sig_list}
        # 桶归属：id → 桶key，用于校验一组是否都在同一桶
        id_bucket = {}
        for (mod, cat), items in candidate_buckets.items():
            for s in items:
                id_bucket[s['id']] = (mod, cat)
        clean_groups = []
        dropped = 0
        for g in groups:
            raw_ids = g.get('signal_ids', [])
            # 只保留真实存在且在候选集内的 id，去重
            ids = []
            for sid in raw_ids:
                if sid in valid_ids and sid not in ids:
                    ids.append(sid)
            if len(ids) < 2:
                dropped += 1
                continue
            # 跨桶校验：一组必须全在同一个桶
            bks = {id_bucket.get(sid) for sid in ids}
            if len(bks) != 1:
                dropped += 1
                continue
            g['signal_ids'] = ids
            g['signals'] = [{'id': sid, 'title': by_id.get(sid, {}).get('title', sid)} for sid in ids]
            clean_groups.append(g)
        groups = clean_groups
        msg = f'分析了 {len(signals)} 条活跃信号（{len(candidate_buckets)} 个候选桶），发现 {len(groups)} 组可归并'
        if dropped:
            msg += f'（已过滤 {dropped} 组无效建议）'
        if hist_count:
            msg += f'，参考了 {hist_count} 条团队历史决策'
        return {'ok': True, 'groups': groups, 'model': model,
                'analyzed': len(signals), 'history_count': hist_count, 'message': msg}
    except Exception as e:
        logger.warning('analyze_merge LLM failed: %s', e)
        return {'error': f'归并分析失败: {e}'}, 500

