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


# ── 类目判别标准（单一数据源：审核/对话/归并 agent 共享注入）──────────────
CATEGORY_GUIDE = """## 类目判别标准（先项目归属，再判类型）

**大前提：判类只看"这件事处于什么阶段"，不看"细节定全了没有"。** 大量内容是"已经在做、但还有细节待定"——这类是**需求/需求进展，不是信号**。别因为"接口范围没定/参数没定/时间没最终敲死"就退回信号，那是拔高门槛的误判。

**第一步：是不是某个项目的事？**
内容点名了客户/项目（"中建""南水北调""XX项目"）→ 属于该项目。它要么是项目需求（走信号→项目需求流转），要么是已有项目需求的进展（合并更新）。**明确说了归属某项目的，绝不能只当公共信号丢着**——至少标 related_project。

**第二步：是新线索，还是已在推进/已定要做的事？（关键分水岭）**
判"需求"的硬信号——**命中任意一条就是需求（或已有需求的进展），不是信号**：
- 有**责任人+推进动作**（"X负责做Y""X跟进Z""下周拉研发"）
- 有**版本规划**（"放5.17""这个版本要做"）
- 涉及**验收/交付/测试**（"API验收""交付运维报告""本周要输出"）——验收交付＝需求已在开发周期里
- 有**明确方案方向在落地**（"用UE Sequence实现""按FBX做接口"），哪怕范围没定全
→ 上述若是"**上次说的/继续推进**"，是**已有需求的进展**，走合并更新；若是本轮新提出要做，是**新需求**。

**只有真正的"信号"才归 signals**：还停留在"发生了个情况/听到个反馈"，**没有人接、没排期、没进开发交付动作**的纯线索（客户随口一提、竞品动向、刚发现某现象）。

**其它类型**：客户项目立项建档（新商机）→projects。

⚠ **沉淀入库不主动判 designs（设计）**：设计必须有实体产出——只有「设计模式产出的收敛稿」或「提交时带具体设计文档/链接」才算 designs。早会里的"方案探索/技术方向讨论"（如"用UE Sequence实现""本地端协作方案"）**不是设计**，它是对应需求的技术方向，判为需求（或已有需求的进展合并）。

⚠ **没有"决策"这个类目**：拍板结论/工作流定论（"确立XX工作流""定了用XX方案"）**不要单独归类，也不要在分析里单列"决策"**——它就是某条需求的背景，直接并进对应需求；对应不到就当需求本身处理或先归 signals 留档。**判类只在 signals / requirements / designs / projects 四类里选，不出现 decisions。**

自检：判信号前先问自己——"这件事有没有人在做、有没有排期/验收/版本？" 只要有，就不是信号。"""

# ── 审核规则（审核助手的调教规则，与归并规则平级）──────────────────
_DEFAULT_REVIEW_RULE = f"""你是 WDP 产品团队知识库的审核助手，协助管理员审核成员提交的入库申请。

## 审核决策树（按顺序执行，每步的结论写进 proposal 对应字段）

**第一步：新事还是旧事？（迭代识别）**
对照现有条目清单：这条提交是不是某个已有条目的进展/补充？
- 是 → recommendation=「合并更新」，merge_into=目标id，merge_note=一句话提炼增量；进展暗示状态变化的，suggested_status 给建议新状态。**到此为止，不再往下判**。
- 否（真正的新事项）→ 继续第二步。

**第二步：归哪类？（独立判断，申报类目仅供参考）**
按下面的判别标准判类，suggested_category 填你的判断；与申报不一致时在回复里显式说"申报为 X，我判断应为 Y，理由：…"。
- **项目关联感知**：内容涉及现有条目清单里的某个项目（提到项目名/客户名）时，在 suggested_fields 里加 `related_project: <项目名>`，并在回复里提示"与XX项目相关，入库后可从信号池沉淀为该项目需求"。

**第三步：重不重？（查重）**
与现有条目比对主题，duplicate_risk 标风险等级，疑似重复填 duplicate_of。

**第四步：全不全？（质量+完整度）**
- 质量：内容具体、有事实依据、必填字段完整。
- 价值字段（business_value/customer/target_release/designer 等）空缺或"待补充"的：能从内容推导的填进 suggested_fields（入库时自动写入），推导不了的在 quality_notes 里提示。

**第五步：定处置 + 派单**
recommendation 四选一：通过/合并更新/建议修订后通过/建议驳回。
- 驳回理由必须具体可操作（指出缺什么+怎么改，会发给提交人）。
- 适合跟进的，按成员职责给 suggested_owner 并说明理由。

{CATEGORY_GUIDE}"""


def _review_rule_path() -> Path:
    return _team_home() / 'review-rule.txt'


def get_review_rule() -> str:
    p = _review_rule_path()
    if p.is_file():
        try:
            custom = p.read_text(encoding='utf-8')
            # 类目判别标准是结构性规训，自定义规则里没写也强制附加（防 admin 编辑规则时丢失）
            if '类目判别标准' not in custom:
                custom = custom.rstrip() + '\n\n' + CATEGORY_GUIDE
            return custom
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
{CATEGORY_GUIDE}

以下信号已按【模块+类别】分桶（归并只能在同一桶内发生，不同桶的信号不要合并）：
{json.dumps(bucketed, ensure_ascii=False, indent=2)}

请做两件事：
1. 在每个桶内部找出「主题相同、应合并成一条」的信号组。
2. 顺带检查类目错放：按上面的判别标准，若某条"信号"本质上是需求/设计（如已是明确诉求待办、或已是方案文档），列入 miscategorized。

只返回 JSON：
{{"groups": [{{"signal_ids": ["SIG-x","SIG-y"], "suggested_title": "归并后标题",
  "suggested_body": "归并后新信号的完整描述（150字内：综合各源信号的问题本质、影响面、客户诉求）",
  "suggested_urgency": "高/中/低（取组内最高）",
  "reason": "归并理由"}}],
 "miscategorized": [{{"signal_id": "SIG-x", "suggested_category": "requirements/designs/projects",
  "reason": "为什么它不是信号（一句话）"}}]}}
规则：①只合并同一桶内的信号，signal_ids 必须来自上面清单里真实存在的 id ②每组至少 2 条 ③没有可归并的组返回 {{"groups": []}}，没有错放返回 {{"miscategorized": []}}。不要输出 JSON 以外的任何文字。"""

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
        # 类目错放建议：只保留真实存在的信号 id（防幻觉）
        mis = []
        for m in (parsed.get('miscategorized') or []):
            sid = m.get('signal_id', '')
            if sid in valid_ids and m.get('suggested_category') in ('requirements', 'designs', 'projects'):
                m['title'] = by_id.get(sid, {}).get('title', sid)
                mis.append(m)
        if mis:
            msg += f'；⚠ 发现 {len(mis)} 条疑似类目错放（详见建议）'
        return {'ok': True, 'groups': groups, 'model': model, 'miscategorized': mis,
                'analyzed': len(signals), 'history_count': hist_count, 'message': msg}
    except Exception as e:
        logger.warning('analyze_merge LLM failed: %s', e)
        return {'error': f'归并分析失败: {e}'}, 500

