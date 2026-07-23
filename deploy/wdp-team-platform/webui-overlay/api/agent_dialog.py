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
_TTL = 3600              # 1小时无操作自动过期


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
    for cat in ('signals', 'requirements', 'designs', 'decisions'):
        try:
            for it in _kb.scan_category(cat):
                existing.append(f"[{cat}] {it.get('id','')} {it.get('title','')} status={it.get('status','')}")
        except Exception:
            pass
    return f"""你是 WDP 产品团队知识库的审核助手，正在和管理员对话协作审核一条入库申请。
{history}
## 待审申请
提交人：{meta.get('username','')}  申报类目：{meta.get('category','')}  标题：{meta.get('title','')}
提交时间：{meta.get('submitted_at','')}
### 内容全文
{content}

## 现有知识库条目（查重参考）
{chr(10).join(existing[:50])}

## 对话规则（重要）
- 管理员会和你讨论这条申请（质量如何/是否重复/该归哪类/要不要驳回），你的分析要具体、基于内容。
- **每当你的审核建议有更新（首轮必须），在回复末尾输出 ```proposal 代码块**：
```proposal
{{"suggested_category": "signals/requirements/designs/decisions", "duplicate_risk": "无/低/中/高", "duplicate_of": "疑似重复的条目id或空串", "quality_notes": "质量简评", "recommendation": "通过/建议修订后通过/建议驳回", "reason": "一句话理由", "suggested_reject_reason": "若建议驳回,给出发给提交人的驳回理由,否则空串"}}
```
- proposal 块外用简洁中文回应管理员，不重复方案内容。"""


# ── 接口实现 ────────────────────────────────────────────────────────────────

def start_dialog(kind: str, ref: dict) -> dict:
    _gc()
    if kind not in ('merge', 'review'):
        return {'error': f'未知对话类型 {kind}'}, 400
    try:
        sys_prompt = _merge_system_prompt() if kind == 'merge' else _review_system_prompt(ref or {})
    except Exception as e:
        return {'error': f'构建上下文失败: {e}'}, 500
    first_user = ('请分析当前信号池，给出你的归并方案。' if kind == 'merge'
                  else '请分析这条入库申请，给出你的审核建议。')
    messages = [{'role': 'system', 'content': sys_prompt},
                {'role': 'user', 'content': first_user}]
    try:
        raw = _call_llm(messages)
    except Exception as e:
        logger.warning('agent-dialog start LLM failed: %s', e)
        return {'error': f'agent 分析失败: {e}'}, 500
    messages.append({'role': 'assistant', 'content': raw})
    reply, proposal = _extract_proposal(raw)
    did = uuid.uuid4().hex[:12]
    with _LOCK:
        _DIALOGS[did] = {'kind': kind, 'ref': ref or {}, 'messages': messages,
                         'touched': time.time()}
    return {'dialog_id': did, 'reply': reply, 'proposal': proposal}


def send_dialog(dialog_id: str, message: str) -> dict:
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
    try:
        raw = _call_llm(d['messages'])
    except Exception as e:
        d['messages'].pop()
        return {'error': f'agent 回复失败: {e}'}, 500
    d['messages'].append({'role': 'assistant', 'content': raw})
    d['touched'] = time.time()
    reply, proposal = _extract_proposal(raw)
    return {'reply': reply, 'proposal': proposal}


def close_dialog(dialog_id: str) -> dict:
    with _LOCK:
        _DIALOGS.pop(dialog_id, None)
    return {'ok': True}
