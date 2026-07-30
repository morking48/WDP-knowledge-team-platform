"""
WDP 团队工作台 · 决策中心对话式 Agent（R38 归并 / R41 审核）.

设计（与用户对齐）：
  - 归并/审核不是"表单+一次性LLM"，而是**对话式**：agent 给出初始方案后，
    管理员可多轮对话调优（"把标题改成XX""这两条别合""为什么建议驳回？"），
    对话内容持续影响 agent 的理解，直到管理员满意后执行。
  - 对话 session 是**内存态缓存**：关闭对话框即清除（dialog/close）。
  - 每轮回复末尾 agent 输出结构化方案 JSON（```proposal 代码块），前端解析出
    "当前方案"卡片供管理员一键执行；没有方案块则只是普通答疑轮。
  - 执行后决策仍写 wdp_agent_log（few-shot 学习闭环不变）。

接口：
  POST /api/admin/agent-dialog/start  {kind: merge|review, ref: {...}}
       → {dialog_id, reply, proposal}
  POST /api/admin/agent-dialog/send   {dialog_id, message}
       → {reply, proposal}
  POST /api/admin/agent-dialog/close  {dialog_id}
"""
from __future__ import annotations

from api._wdp_types import ApiResult

import json
import logging
import re
import threading
import time
import urllib.request
import uuid

logger = logging.getLogger(__name__)

# dialog_id -> {kind, messages: [...], created, ref}
_DIALOGS: dict = {}
_LOCK = threading.Lock()
_MAX_TURNS = 24          # 每个对话最多保留的消息数（防膨胀）
_TTL = 86400             # 24小时无操作自动过期（兜底防泄漏；主清理靠入库/驳回后主动 close）


def _gc():
    now = time.time()
    with _LOCK:
        for k in [k for k, v in _DIALOGS.items() if now - v.get('touched', 0) > _TTL]:
            _DIALOGS.pop(k, None)


def _call_llm(messages: list, max_tokens: int = 2000, _retried: bool = False) -> str:
    from api.merge_agent import _team_key_and_model
    key, model, _ = _team_key_and_model()
    if not key:
        raise RuntimeError('团队未配置 OpenRouter Key')
    body = json.dumps({'model': model, 'messages': messages,
                       'temperature': 0.3, 'max_tokens': max_tokens}).encode('utf-8')
    req = urllib.request.Request(
        'https://openrouter.ai/api/v1/chat/completions', data=body,
        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json',
                 'HTTP-Referer': 'https://wdp-team-workbench', 'X-Title': 'WDP Agent Dialog'})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode('utf-8'))

    # R45：容错——content 可能为 None（被截断/只有 finish_reason），正则处理 None 会报 NoneType
    choice = (data.get('choices') or [{}])[0]
    message = choice.get('message') or {}
    content = message.get('content')
    finish = choice.get('finish_reason')

    # 截断（finish_reason=length）且未重试过 → 加大 max_tokens 自动续写一次
    if finish == 'length' and not _retried:
        logger.info('agent-dialog LLM 输出被截断(length)，加大 max_tokens 重试')
        # 把已生成的部分作为 assistant 消息续上，让模型继续
        partial = content or ''
        cont_messages = messages + [
            {'role': 'assistant', 'content': partial},
            {'role': 'user', 'content': '（继续，把刚才没说完的接着说完，不要重复）'},
        ]
        try:
            more = _call_llm(cont_messages, max_tokens=max_tokens, _retried=True)
            return (partial + more) if isinstance(more, str) else partial
        except Exception as e:
            logger.warning('续写失败，返回已截断内容: %s', e)
            return partial or ''

    if content is None:
        # content 为 None（如 reasoning 模型只回了 reasoning、或异常）→ 回退空串避免 NoneType
        logger.warning('agent-dialog LLM 返回 content=None (finish=%s)', finish)
        return message.get('reasoning') or ''
    return content if isinstance(content, str) else str(content)


def _extract_proposal(text: str):
    """从回复中提取 ```proposal ...``` JSON 方案块。返回 (清理后的正文, proposal|None)。"""
    m = re.search(r'```proposal\s*(\{.*?\})\s*```', text, re.DOTALL)
    if not m:
        return text.strip(), None
    try:
        prop = json.loads(m.group(1))
    except Exception:
        return text.strip(), None
    clean = (text[:m.start()] + text[m.end():]).strip()
    return clean, prop


# ── 上下文构建 ────────────────────────────────────────────────────────────────

# ── L3 稳态 loop：proposal 结构校验 + 修正提示 ──────────────────────────
_PROPOSAL_REQUIRED = {
    'merge': ['groups'],
    'review': ['recommendation'],
    'rules': ['soul'],
    'skill': ['skill_md'],
}


def _proposal_valid(kind: str, proposal) -> bool:
    """proposal 是否含该 kind 的必备键（None/残缺=False）。"""
    if not isinstance(proposal, dict):
        return False
    for k in _PROPOSAL_REQUIRED.get(kind or '', []):
        if k not in proposal:
            return False
        if kind == 'rules' and not (proposal.get('soul') or '').strip():
            return False
        if kind == 'skill' and not (proposal.get('skill_md') or '').strip():
            return False
    return True


def _proposal_fix_hint(kind: str) -> str:
    need = _PROPOSAL_REQUIRED.get(kind or '', [])
    return (f'你上一条回复的 ```proposal 代码块缺失或格式不合法（必须是含 {need} 键的 JSON）。'
            f'请重新输出完整回复：简短说明 + 末尾一个合法的 ```proposal 代码块，不要输出其它代码块。')


def _merge_system_prompt() -> str:
    from api.merge_agent import get_merge_rule
    from api import knowledge as _kb
    try:
        from api.wdp_agent_log import few_shot_block
        history = few_shot_block('merge', 5)
    except Exception:
        history = ''
    signals = [s for s in _kb.scan_category('signals')
               if (s.get('status') or '') not in ('已转需求', '已合并', '已归档')]
    sig_list = [{'id': s.get('id') or s.get('_file'), 'title': s.get('title', ''),
                 'category': s.get('category', ''), 'module': s.get('related_module', ''),
                 'urgency': s.get('urgency', ''),
                 'excerpt': (s.get('raw_excerpt') or s.get('_body', ''))[:150]} for s in signals]
    rule = get_merge_rule()
    return f"""{rule}
{history}
## 当前活跃信号池（JSON）
{json.dumps(sig_list, ensure_ascii=False, indent=1)}

## 对话规则（重要）
你是归并助手，正在和管理员对话协作完成信号归并。管理员的话会不断调整你的理解：
- 管理员可能否决某组、要求改标题/描述、追问理由——认真吸收并更新方案。
- **每当你的方案有更新（首轮必须），在回复末尾输出一个 ```proposal 代码块**，格式：
```proposal
{{"groups": [{{"signal_ids": ["SIG-x","SIG-y"], "suggested_title": "归并后标题", "suggested_body": "归并后完整描述(150字内,综合问题本质/影响面/诉求)", "suggested_urgency": "高/中/低", "reason": "归并理由"}}]}}
```
- 如果经讨论认为没有可归并的组，输出 {{"groups": []}}。
- proposal 块外用简洁中文说明你的思路/回应管理员，不要重复罗列方案内容。"""


def _get_review_rule_text() -> str:
    """审核助手的调教规则（团队 Agent 页可编辑，与归并规则平级）。"""
    try:
        from api.merge_agent import get_review_rule
        return get_review_rule()
    except Exception:
        return '你是 WDP 产品团队知识库的审核助手，正在和管理员对话协作审核一条入库申请。'


def _review_system_prompt(ref: dict) -> str:
    from api import review as _rv
    from api import knowledge as _kb
    try:
        from api.wdp_agent_log import few_shot_block
        history = few_shot_block('review', 5)
    except Exception:
        history = ''
    profile = ref.get('user') or ''
    fname = ref.get('file') or ''
    content = ''
    meta = {}
    inbox = _rv._user_inbox(profile)
    if inbox:
        fp = inbox / fname
        if fp.exists():
            content = fp.read_text(encoding='utf-8')[:2500]
        mf = inbox / (fname + '.meta.json')
        if mf.exists():
            try:
                meta = json.loads(mf.read_text(encoding='utf-8'))
            except Exception:
                pass
    existing = []
    for cat in ('signals', 'requirements', 'designs', 'decisions', 'projects'):
        try:
            for it in _kb.scan_category(cat):
                existing.append(f"[{cat}] {it.get('id','')} {it.get('title','')} status={it.get('status','')}")
        except Exception:
            pass
    # 项目档案在子目录（projects/<名>/project.md），scan_category 扫不到，单独注入
    try:
        from api.projects import list_projects
        for pj in list_projects().get('projects', []):
            existing.append(f"[projects] {pj.get('id','')} {pj.get('title','')} 客户={pj.get('customer','')} 阶段={pj.get('phase','')}")
    except Exception:
        pass
    return f"""{_get_review_rule_text()}
{history}
## 待审申请
提交人：{meta.get('username','')}  申报类目：{meta.get('category','')}  标题：{meta.get('title','')}
提交时间：{meta.get('submitted_at','')}
### 内容全文
{content}

## 现有知识库条目（查重参考）
{chr(10).join(existing[:50])}

## 团队成员职责（分配建议依据）
{_roster_block()}

## 对话规则（重要）
- 管理员会和你讨论这条申请，你的分析要具体、基于内容。审核逻辑严格按上面的「审核决策树」五步走（先判新旧→归类→查重→完整度→处置）。
- **每当你的审核建议有更新（首轮必须），在回复末尾输出 ```proposal 代码块**：
```proposal
{{"suggested_category": "signals/requirements/designs/projects(项目开档申请)", "duplicate_risk": "无/低/中/高", "duplicate_of": "疑似重复的条目id或空串", "quality_notes": "质量简评", "recommendation": "通过/建议修订后通过/建议驳回/合并更新", "reason": "一句话理由", "suggested_owner": "建议负责人用户名或空串", "suggested_reject_reason": "若建议驳回,给出发给提交人的驳回理由,否则空串", "suggested_fields": {{"business_value": "从内容推导的业务价值(推导不出则省略该键)", "customer": "...", "target_release": "..."}}, "merge_into": "若建议合并更新,填目标条目id(如REQ-20260729-001),否则空串", "merge_note": "若合并更新,一句话提炼增量进展(将写入目标条目tracking),否则空串", "suggested_status": "若进展暗示目标条目状态变化,给建议新状态(如已完成/开发中),否则空串"}}
```
- proposal 块外用简洁中文回应管理员，不重复方案内容。
- **驳回理由必须具体可操作**：`suggested_reject_reason` 不能只写"不符合标准"这类笼统结论，要指出**具体问题+怎么改**（如"缺少 urgency 字段，请补充紧急度"、"描述只有一句话，请补充问题背景和客户诉求"、"与 SIG-xxx 重复，请确认是否为同一件事"），让提交人看了知道下一步怎么做。"""


def _roster_block() -> str:
    """团队职责花名册文本块（供审核/规则 agent 注入）。"""
    try:
        from api import users as _u
        roster = _u.team_roster()
    except Exception:
        return '（暂无成员职责登记）'
    lines = []
    for m in roster:
        resp = m.get('responsibilities') or '（未登记职责）'
        lines.append(f"- {m['username']}（{m.get('role','member')}）：{resp}")
    return '\n'.join(lines) if lines else '（暂无成员职责登记）'


def _rules_system_prompt() -> str:
    """团队规则 agent：和管理员对话共创/优化团队 SOUL（团队规则母本）。"""
    from api import team_agent as _ta
    cur = ''
    try:
        cur = _ta.get_team_agent().get('soul', '') or ''
    except Exception:
        pass
    return f"""你是 WDP 产品团队的「团队规则助手」，和管理员对话协作编写/优化团队规则（团队 SOUL）。
团队规则是所有成员 AI 助手共享的最高优先级人格与铁律，会被发布注入每个成员 agent。

## 当前团队规则全文
{cur or '（当前为空，尚未设定团队规则）'}

## 你的职责
- 管理员会提出想强调/新增/修改的规则意图（如"数据口径要诚实""产出必须结构化入库"），你帮他组织成**规范、清晰、可执行**的规则条目。
- 保持团队规则的整体结构和已有有效内容，做增量优化而非推倒重写（除非管理员明确要求重写）。
- 规则要面向 AI 助手可执行：讲清"该怎么做/不该怎么做"，避免空泛口号。
- **每当规则文本有更新（首轮必须），在回复末尾输出 ```proposal 代码块**，内含**完整的新版团队规则全文**：
```proposal
{{"soul": "<完整的新版团队规则 Markdown 全文>"}}
```
- proposal 块外用简洁中文说明你改了什么、为什么，不要重复粘贴全文。
- 管理员满意后会点"应用并发布"，届时你的 soul 全文会写入母本并下发成员。"""


def _skill_system_prompt(ref: dict) -> str:
    """团队 skill 编辑 agent：和管理员对话协作修改某个团队 skill 的 SKILL.md。"""
    skill_dir = (ref or {}).get('skill_dir') or ''
    cur = ''
    try:
        from api import team_skills_admin as _ts
        got = _ts.get_team_skill(skill_dir)
        if isinstance(got, dict):
            cur = got.get('draft') or got.get('published') or ''
    except Exception:
        pass
    return f"""你是 WDP 产品团队的「团队技能助手」，和管理员对话协作编辑团队 skill（技能）。
团队 skill 是所有成员 AI 助手共享的方法论/操作规程，发布后成员实时同步、按需加载执行。

## 当前正在编辑的 skill：{skill_dir or '（未指定）'}
### 当前 SKILL.md 全文
{cur or '（当前为空或读取失败）'}

## 你的职责
- 管理员会提出想改进/新增/修正的技能内容意图（如"补一个操作步骤""改进触发条件""加个避坑说明"），你帮他组织成**规范、清晰、可执行**的 SKILL.md。
- 保持 skill 的整体结构和已有有效内容，做增量优化而非推倒重写（除非管理员明确要求重写）。
- **必须保留 YAML frontmatter**（--- 开头，含 name/description 等），成员 agent 靠它检索加载；description 要准确概括技能用途和触发场景。
- 技能正文面向 AI 助手可执行：清晰的触发条件、编号步骤、具体命令、避坑说明、验证步骤。
- **每当 skill 文本有更新（首轮必须），在回复末尾输出 ```proposal 代码块**，内含**完整的新版 SKILL.md 全文**：
```proposal
{{"skill_md": "<完整的新版 SKILL.md（含 frontmatter）全文>"}}
```
- proposal 块外用简洁中文说明你改了什么、为什么，不要重复粘贴全文。
- 管理员满意后会点"发布"，届时你的 skill_md 全文会写入正式 skill，成员实时同步。"""


# ── 接口实现 ────────────────────────────────────────────────────────────────

def _resume_key(kind: str, ref: dict) -> str:
    """审批期对话的稳定标识：同一待审项/技能重开窗口能接续上次对话。
    review 绑 profile+file；skill 绑 skill_dir；merge/rules 是全局单例。
    """
    ref = ref or {}
    if kind == 'review':
        return f"review:{ref.get('user','')}:{ref.get('file','')}"
    if kind == 'skill':
        return f"skill:{ref.get('skill_dir','')}"
    return kind  # merge / rules：全局一个


def _find_live_dialog(kind: str, ref: dict):
    """查同一 resume_key 下未过期的对话，返回 (dialog_id, dialog) 或 (None, None)。"""
    rk = _resume_key(kind, ref)
    with _LOCK:
        for did, d in _DIALOGS.items():
            if d.get('resume_key') == rk:
                return did, d
    return None, None


def purge_dialog_by_ref(kind: str, ref: dict) -> int:
    """按待审项标识清除对话（approve/reject 成功后由后端主动调用——
    不依赖前端 setTimeout，保证审批完成后旧讨论不残留、不会串到下一轮同名提交）。"""
    rk = _resume_key(kind, ref or {})
    n = 0
    with _LOCK:
        for did in [k for k, v in _DIALOGS.items() if v.get('resume_key') == rk]:
            _DIALOGS.pop(did, None)
            n += 1
    return n


def start_dialog(kind: str, ref: dict) -> ApiResult:
    _gc()
    if kind not in ('merge', 'review', 'rules', 'skill'):
        return {'error': f'未知对话类型 {kind}'}, 400
    # 续接：同一待审项/技能已有存活对话 → 返回历史消息，接着聊（不重新分析）
    live_id, live = _find_live_dialog(kind, ref)
    if live_id and live is not None and kind == 'review':
        # 防串联：若待审文件在对话创建后被重新提交（驳回→修订→重提），旧讨论作废
        try:
            from api import review as _rv
            inbox = _rv._user_inbox((ref or {}).get('user', ''))
            if inbox:
                mf = inbox / ((ref or {}).get('file', '') + '.meta.json')
                if mf.exists():
                    meta = json.loads(mf.read_text(encoding='utf-8'))
                    sub_at = meta.get('submitted_at', '')
                    if sub_at:
                        sub_ts = time.mktime(time.strptime(sub_at, '%Y-%m-%d %H:%M:%S'))
                        if sub_ts > live.get('created', live.get('touched', 0)):
                            with _LOCK:
                                _DIALOGS.pop(live_id, None)
                            live_id, live = None, None
        except Exception:
            pass
    if live_id and live is not None:
        live['touched'] = time.time()
        msgs = [m for m in live.get('messages', []) if m['role'] in ('user', 'assistant')]
        # 提取最后一条 assistant 的 proposal 供前端恢复动作区
        last_proposal = None
        for m in reversed(live.get('messages', [])):
            if m['role'] == 'assistant':
                _, last_proposal = _extract_proposal(m['content'])
                break
        return {'dialog_id': live_id, 'resumed': True, 'history': msgs,
                'proposal': last_proposal}
    try:
        if kind == 'merge':
            sys_prompt = _merge_system_prompt()
        elif kind == 'review':
            sys_prompt = _review_system_prompt(ref or {})
        elif kind == 'skill':
            sys_prompt = _skill_system_prompt(ref or {})
        else:  # rules
            sys_prompt = _rules_system_prompt()
    except Exception as e:
        return {'error': f'构建上下文失败: {e}'}, 500
    first_user = {'merge': '请分析当前信号池，给出你的归并方案。',
                  'review': '请分析这条入库申请，给出你的审核建议。',
                  'skill': (ref or {}).get('intent') or '请先概述这个技能当前的内容和结构，然后问我想改进/新增什么。',
                  'rules': (ref or {}).get('intent') or '请基于当前团队规则，问我想强调或调整什么，帮我组织成规范条目。'}[kind]
    messages = [{'role': 'system', 'content': sys_prompt},
                {'role': 'user', 'content': first_user}]
    _mt = 8000 if kind in ('rules', 'skill') else 2000   # 规则/skill agent 要输出完整全文，需大额度
    try:
        raw = _call_llm(messages, max_tokens=_mt)
    except Exception as e:
        logger.warning('agent-dialog start LLM failed: %s', e)
        return {'error': f'agent 分析失败: {e}'}, 500
    messages.append({'role': 'assistant', 'content': raw})
    reply, proposal = _extract_proposal(raw)
    # L3 稳态 loop：首轮必须有合法 proposal，格式错则带错误信息重试一次
    if not _proposal_valid(kind, proposal):
        messages.append({'role': 'user', 'content': _proposal_fix_hint(kind)})
        try:
            raw2 = _call_llm(messages, max_tokens=_mt)
            messages.append({'role': 'assistant', 'content': raw2})
            reply2, proposal2 = _extract_proposal(raw2)
            if _proposal_valid(kind, proposal2):
                reply, proposal = reply2, proposal2
        except Exception as e:
            logger.warning('proposal 格式重试失败: %s', e)
    did = uuid.uuid4().hex[:12]
    with _LOCK:
        _DIALOGS[did] = {'kind': kind, 'ref': ref or {}, 'messages': messages,
                         'resume_key': _resume_key(kind, ref or {}),
                         'created': time.time(), 'touched': time.time()}
    return {'dialog_id': did, 'reply': reply, 'proposal': proposal}


def send_dialog(dialog_id: str, message: str) -> ApiResult:
    _gc()
    with _LOCK:
        d = _DIALOGS.get(dialog_id)
    if not d:
        return {'error': '对话已过期或关闭，请重新发起'}, 404
    if not message.strip():
        return {'error': '消息为空'}, 400
    d['messages'].append({'role': 'user', 'content': message.strip()})
    # 截断：保留 system + 最近 N 条
    if len(d['messages']) > _MAX_TURNS:
        d['messages'] = [d['messages'][0]] + d['messages'][-(_MAX_TURNS - 1):]
    _mt = 8000 if d.get('kind') in ('rules', 'skill') else 2000
    try:
        raw = _call_llm(d['messages'], max_tokens=_mt)
    except Exception as e:
        d['messages'].pop()
        return {'error': f'agent 回复失败: {e}'}, 500
    d['messages'].append({'role': 'assistant', 'content': raw})
    d['touched'] = time.time()
    reply, proposal = _extract_proposal(raw)
    # L3：有 proposal 块但格式残缺 → 重试一次（无 proposal 的纯讨论轮不强求）
    if proposal is not None and not _proposal_valid(d.get('kind'), proposal):
        d['messages'].append({'role': 'user', 'content': _proposal_fix_hint(d.get('kind'))})
        try:
            raw2 = _call_llm(d['messages'], max_tokens=_mt)
            d['messages'].append({'role': 'assistant', 'content': raw2})
            reply2, proposal2 = _extract_proposal(raw2)
            if _proposal_valid(d.get('kind'), proposal2):
                reply, proposal = reply2, proposal2
        except Exception as e:
            logger.warning('proposal 格式重试失败: %s', e)
    return {'reply': reply, 'proposal': proposal}


def close_dialog(dialog_id: str) -> dict:
    with _LOCK:
        _DIALOGS.pop(dialog_id, None)
    return {'ok': True}
