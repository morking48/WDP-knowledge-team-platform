"""
WDP 团队工作台 · 归并 Agent（R10）.

真 LLM 驱动的信号自动归并分析：
  1. 读所有活跃信号（池内）
  2. 用团队默认模型（OpenRouter/kimi-k3）+ 团队可调教的「归并规则 prompt」分析
  3. 返回可归并的信号分组建议，管理员在弹框做最终决策

团队规则：存 knowledge/team-tasks.json 同级或团队 SOUL；这里用独立配置 merge-rule.txt。
"""
from __future__ import annotations

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


def save_merge_rule(content: str) -> dict:
    try:
        _rule_path().write_text(content or _DEFAULT_RULE, encoding='utf-8')
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


def analyze_merge(admin_user: str = 'admin') -> dict:
    """读活跃信号，调 LLM 分析可归并组，返回建议。"""
    from api import knowledge as _kb
    signals = [s for s in _kb.scan_category('signals')
               if (s.get('status') or '') not in ('已转需求', '已合并', '已归档')]
    if len(signals) < 2:
        return {'ok': True, 'groups': [], 'message': '活跃信号少于 2 条，无需归并'}

    key, model, provider = _team_key_and_model()
    if not key:
        return {'error': '团队未配置 OpenRouter Key，无法调用归并 Agent'}, 500

    # 组装信号清单给 LLM
    sig_list = []
    for s in signals:
        sig_list.append({
            'id': s.get('id') or s.get('_file'),
            'title': s.get('title', ''),
            'category': s.get('category', ''),
            'module': s.get('related_module', ''),
            'urgency': s.get('urgency', ''),
            'excerpt': (s.get('raw_excerpt') or s.get('_body', ''))[:120],
        })

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
以下是当前活跃信号清单（JSON）：
{json.dumps(sig_list, ensure_ascii=False, indent=2)}

请只返回 JSON，格式：
{{"groups": [{{"signal_ids": ["SIG-x","SIG-y"], "suggested_title": "归并后标题",
  "suggested_body": "归并后新信号的完整描述（150字内：综合各源信号的问题本质、影响面、客户诉求）",
  "suggested_urgency": "高/中/低（取组内最高）",
  "reason": "归并理由"}}]}}
如果没有可归并的组，返回 {{"groups": []}}。不要输出 JSON 以外的任何文字。"""

    try:
        content = _llm_call(key, model, prompt, max_tokens=4000, title='WDP Merge Agent')
        parsed = _extract_json(content)
        groups = parsed.get('groups', [])
        # 补充每组信号的标题（前端展示）
        by_id = {s['id']: s for s in sig_list}
        for g in groups:
            g['signals'] = [{'id': sid, 'title': by_id.get(sid, {}).get('title', sid)}
                            for sid in g.get('signal_ids', []) if sid in by_id]
        groups = [g for g in groups if len(g.get('signals', [])) >= 2]
        return {'ok': True, 'groups': groups, 'model': model,
                'analyzed': len(signals), 'history_count': hist_count,
                'message': f'分析了 {len(signals)} 条活跃信号，发现 {len(groups)} 组可归并'
                           + (f'（参考了 {hist_count} 条团队历史决策）' if hist_count else '')}
    except Exception as e:
        logger.warning('analyze_merge LLM failed: %s', e)
        return {'error': f'归并分析失败: {e}'}, 500


def analyze_review(profile: str, fname: str) -> dict:
    """R22 审核助手：管理员发起，LLM 分析一条待审提交 → 建议(归类/查重/通过建议)。

    注入团队历史审核决策(few-shot)，越用越懂团队尺度。
    """
    from api import review as _rv
    from api import knowledge as _kb
    inbox = _rv._user_inbox(profile)
    if not inbox:
        return {'error': 'inbox 不可用'}, 500
    fpath = inbox / fname
    meta_file = inbox / (fname + '.meta.json')
    if not fpath.exists():
        return {'error': '待审文件不存在'}, 404
    content = fpath.read_text(encoding='utf-8')[:2000]
    meta = {}
    if meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text(encoding='utf-8'))
        except Exception:
            pass

    key, model, _p = _team_key_and_model()
    if not key:
        return {'error': '团队未配置 OpenRouter Key'}, 500

    # 现有知识库摘要(查重用)
    existing = []
    for cat in ('signals', 'requirements', 'designs', 'decisions'):
        try:
            for it in _kb.scan_category(cat):
                existing.append(f"[{cat}] {it.get('id','')} {it.get('title','')}")
        except Exception:
            pass

    history = ''
    hist_count = 0
    try:
        from api.wdp_agent_log import few_shot_block, history_stats
        history = few_shot_block('review', 5)
        hist_count = history_stats('review').get('count', 0)
    except Exception:
        pass

    prompt = f"""你是 WDP 产品团队知识库的审核助手。管理员正在审核一条成员提交的入库申请，请给出专业分析建议。
{history}
## 待审提交
提交人：{meta.get('username','')}  申报类目：{meta.get('category','')}  标题：{meta.get('title','')}
内容：
{content}

## 现有知识库条目（查重参考）
{chr(10).join(existing[:40])}

请只返回 JSON：
{{"suggested_category": "建议归入的类目(signals/requirements/designs/decisions)",
  "duplicate_risk": "无/低/中/高",
  "duplicate_of": "若疑似重复,写出相关条目id,否则空串",
  "quality_notes": "内容质量简评(字段完整性/表述清晰度,一两句)",
  "recommendation": "通过/建议修订后通过/建议驳回",
  "reason": "一句话理由"}}
不要输出 JSON 以外的文字。"""
    try:
        txt = _llm_call(key, model, prompt, max_tokens=3000, title='WDP Review Assist')
        advice = _extract_json(txt)
        advice['model'] = model
        advice['history_count'] = hist_count
        return {'ok': True, 'advice': advice}
    except Exception as e:
        logger.warning('analyze_review failed: %s', e)
        return {'error': f'审核助手分析失败: {e}'}, 500
