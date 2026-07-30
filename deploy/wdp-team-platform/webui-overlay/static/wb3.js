/* ============================================================
   WDP 团队工作台 · 对话模块（wb3.js）
   接 web-ui chat 后端：
     POST /api/chat/start  → {stream_id}
     EventSource /api/chat/stream?stream_id=xxx
       事件: token / reasoning / tool / done / apperror / stream_end
     会话列表 GET /api/sessions
     文件上传 POST /api/me/upload（个人工作库）
   ============================================================ */
(function(){
'use strict';
const W = window.__wb;
if(!W){ console.error('wb.js 未加载'); return; }
const {api, h, toast} = W;
const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);

let activeSid = null;
// R42/R43：流式状态按会话ID存储（对齐官方 INFLIGHT 机制），不再用全局单流
// STREAMS[sid] = {answer, reasoning, evtSource, busy, toolLog, ccSnapshot}
let STREAMS = {};
let pendingFiles = [];   // 已上传到工作库的文件 {name, path}

// 当前活跃会话是否正在流式
function isCurrentStreaming(){ return !!(activeSid && STREAMS[activeSid] && STREAMS[activeSid].busy); }
// 是否有任何会话在流式（用于"稍候"提示，不阻塞其它会话）
function anyStreaming(){ return Object.values(STREAMS).some(s=>s.busy); }


// ── 极简 markdown 渲染（够用：粗体/代码/换行/列表）──
function renderMd(text){
  // 🎯 设计模式：先把 ```choices JSON 块抽成占位符，避免后续 markdown 规则（\n→<br> 等）污染生成的控件 HTML
  const cards = [];
  let src = String(text).replace(/```choices\s*\n([\s\S]*?)```/g, (m, c)=>{
    try{ cards.push(renderChoicesCard(JSON.parse(c))); }
    catch(_){ cards.push(`<pre style="background:rgba(0,0,0,.05);padding:10px;border-radius:8px;overflow-x:auto;font-size:12px">${h(c)}</pre>`); }
    return `\u0000CHOICES${cards.length-1}\u0000`;
  });
  let s = h(src);
  s = s.replace(/```([\s\S]*?)```/g, (m,c)=>`<pre style="background:rgba(0,0,0,.05);padding:10px;border-radius:8px;overflow-x:auto;font-size:12px">${c}</pre>`);
  s = s.replace(/`([^`]+)`/g, '<code style="background:rgba(0,0,0,.06);padding:1px 5px;border-radius:4px;font-size:12px">$1</code>');
  s = s.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
  s = s.replace(/^### (.+)$/gm, '<div style="font-weight:700;margin:8px 0 4px">$1</div>');
  s = s.replace(/^## (.+)$/gm, '<div style="font-weight:700;font-size:15px;margin:10px 0 5px">$1</div>');
  s = s.replace(/^- (.+)$/gm, '<div style="margin-left:8px">• $1</div>');
  s = s.replace(/\n/g, '<br>');
  // 塞回 choices 卡片（占位符经 h() 转义后 \u0000 保持不变，可安全匹配）
  s = s.replace(/\u0000CHOICES(\d+)\u0000/g, (m, i)=>cards[+i] || '');
  return s;
}

// 设计收敛：选择题卡片（qid/question/why/multi/irrev/options[{label,default,risk}]）
// 统一退出能力模式（横幅退出 / 切 session 时复用）：清模式态 + 按钮 + choices缓存 + placeholder
// silent=false 时 toast 提示（切 session 场景用，让用户知道模式被关了）
function exitActiveMode(opts){
  opts = opts || {};
  if(!window._activeMode) return;
  window._activeMode = null;
  window._chAnswers = {};
  ['designModeBtn','signalModeBtn'].forEach(id=>{ const b=document.getElementById(id); if(b){b.style.background='';b.style.color='';b.style.borderColor='';} });
  if(typeof renderModeBanner==='function') renderModeBanner();
  const t=document.getElementById('composerInput'); if(t) t.placeholder='和你的 agent 对话… 或 @成员名 发快速通知；可拖文件上传';
  if(opts.toast && window.__wb && window.__wb.toast) window.__wb.toast(opts.toast);
}

// 顶部模式横幅：激活能力模式后，对话区顶部显示醒目提示（让"开/关"确定可见）
function renderModeBanner(){
  let banner = document.getElementById('modeBanner');
  const mode = window._activeMode;
  if(!mode){ if(banner) banner.remove(); return; }
  const cfg = {
    design: {icon:'🎯', text:'设计收敛模式', desc:'多轮流程：批量拷问 → 不可逆决策 → 方案文档；收敛完成后点 ✕ 退出'},
    signal: {icon:'📥', text:'沉淀入库模式', desc:'发送一条即完成：agent 判类清洗后提交入库，随后自动退出'},
  }[mode];
  const html = `<span style="font-weight:700">${cfg.icon} ${cfg.text}</span>
    <span style="font-size:11.5px;color:var(--ink-3);margin-left:8px">${cfg.desc}</span>
    <button id="modeBannerExit" style="margin-left:auto;background:none;border:none;color:var(--ink-3);cursor:pointer;font-size:12px">✕ 退出</button>`;
  if(!banner){
    banner = document.createElement('div');
    banner.id = 'modeBanner';
    banner.style.cssText = 'display:flex;align-items:center;gap:6px;padding:8px 14px;margin:0 0 8px;border-radius:10px;background:var(--brand-soft);border:1px solid var(--brand-strong);font-size:13px';
    const tr = document.getElementById('transcript');
    if(tr && tr.parentNode) tr.parentNode.insertBefore(banner, tr);
  }
  banner.innerHTML = html;
  const ex = document.getElementById('modeBannerExit');
  if(ex) ex.onclick = ()=>exitActiveMode();
}

// 模式激活时，把该模式的流程规则拼进发给 agent 的消息（强制注入，不靠 LLM 读 SOUL）
function _modeInjectedMessage(mode, msg){
  if(mode === 'design'){
    return `[设计模式·请严格按团队 skill「design-converge」的设计收敛流程执行本轮及后续对话]\n`
      + `务必：①一次性批量出 5-7 道选择题（用 \`\`\`choices JSON 代码块，前端会渲染成可点击控件），不要一问一答挤牙膏 ②不可逆决策单独出题并标注每个选项的风险 ③关键节点停下来让我确认（闸门）④最终产出零歧义的完整方案文档，问我是否入库为设计。\n`
      + `我的输入：${msg}`;
  }
  if(mode === 'signal'){
    return `[沉淀入库模式·请按团队规范把原始信息清洗沉淀并提交入库审核]\n`
      + `① 判类（只看阶段，不看细节定全没）：已在推进/已定要做的（有责任人·版本·验收·交付）→requirements；点名某项目的→标 related_project（项目没开档你可直接提开档申请 --category projects）；纯线索（没人接·没排期）→signals；设计只认设计模式产出或带文档链接。**没有"决策"类目，拍板结论并进对应需求**。告诉我你的判类和理由。\n`
      + `② 按判定类目的模板补全字段（价值字段两步策略：能推导的自己补，推导不了的一次问完我）。\n`
      + `③ 整理好后用 submit_review.py 提交入库审核（--category 用你判定的类目）。\n`
      + `原始信息：${msg}`;
  }
  return msg;
}

function renderChoicesCard(q){
  const qid = h(q.qid||'');
  const irrev = q.irrev ? '<span style="background:var(--danger);color:#fff;font-size:10px;padding:2px 8px;border-radius:999px;margin-left:6px">不可逆 · 值得选</span>' : '';
  const multi = !!q.multi;
  const opts = (q.options||[]).map((o,i)=>{
    const dft = o.default ? ' data-default="1"' : '';
    const dftLabel = o.default ? '<span style="color:#3D7A4E;font-size:10px">（默认）</span>' : '';
    const risk = o.risk ? `<div class="ch-risk" style="display:none;font-size:11px;color:#9E5A33;background:#FAEDE5;padding:4px 8px;border-radius:6px;margin-top:4px">⚑ 风险：${h(o.risk)}</div>` : '';
    return `<div style="display:inline-block;vertical-align:top;margin:0 6px 6px 0"><button class="ch-opt" data-qid="${qid}" data-i="${i}" data-multi="${multi?1:0}"${dft}
      style="padding:5px 13px;border-radius:999px;border:1px ${o.default?'dashed #3D7A4E':'solid var(--line)'};background:#fff;cursor:pointer;font-size:12.5px;color:var(--ink-2)">${h(o.label)}${dftLabel}</button>${risk}</div>`;
  }).join('');
  return `<div class="choices-card" data-qid="${qid}" data-multi="${multi?1:0}" style="border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin:8px 0;background:rgba(255,255,255,.7)">
    <div style="font-weight:700;font-size:13px;margin-bottom:2px"><span style="color:var(--brand-strong);font-size:11px;letter-spacing:.1em">${qid}</span> ${h(q.question||'')}${irrev}</div>
    ${q.why?`<div style="font-size:11.5px;color:var(--ink-3);margin-bottom:6px">${h(q.why)}</div>`:''}
    <div>${opts}</div></div>`;
}

// 选项点击（事件委托，绑在 transcript 上）：选中高亮+显示风险；answers 存 window._chAnswers
window._chAnswers = window._chAnswers || {};
function onChoiceClick(e){
  const btn = e.target.closest('.ch-opt'); if(!btn) return;
  const card = btn.closest('.choices-card'); if(!card) return;
  const qid = btn.dataset.qid, multi = btn.dataset.multi === '1';
  if(!multi){
    card.querySelectorAll('.ch-opt').forEach(b=>{ b.style.background='#fff'; b.style.color='var(--ink-2)';
      const r=b.parentElement.querySelector('.ch-risk'); if(r) r.style.display='none'; });
    window._chAnswers[qid] = btn.textContent.replace('（默认）','').trim();
  }else{
    const on = btn.dataset.on === '1';
    btn.dataset.on = on ? '' : '1';
    const cur = new Set((window._chAnswers[qid]||'').split('、').filter(Boolean));
    const label = btn.textContent.replace('（默认）','').trim();
    if(on){ cur.delete(label); } else { cur.add(label); }
    window._chAnswers[qid] = [...cur].join('、');
  }
  if(!multi || btn.dataset.on === '1'){
    btn.style.background = 'var(--ink, #201D18)'; btn.style.color = '#fff';
    const r = btn.parentElement.querySelector('.ch-risk'); if(r) r.style.display='block';
  }else{
    btn.style.background = '#fff'; btn.style.color = 'var(--ink-2)';
    const r = btn.parentElement.querySelector('.ch-risk'); if(r) r.style.display='none';
  }
  // 把已选答案同步进输入框（用户可补充后发送）
  const parts = Object.entries(window._chAnswers).filter(([,v])=>v).map(([k,v])=>`${k}: ${v}`);
  const ta = $('#composerInput');
  if(ta && parts.length){ ta.value = parts.join('；'); autoGrow(); syncChips(); }
}

// ══════════════════════════════════════════════
//  初始化
// ══════════════════════════════════════════════
window.initChat = function(){
  const ta = $('#composerInput');
  const box = $('#composerBox');
  const sendBtn = $('.chat-composer .send');
  const attachBtn = $('#attachBtn');
  // R29：@成员自动提示
  bindMentionSuggest();

  // 模板 chip（纯填字类，mode-chip 是能力激活按钮，单独绑定）
  $$('.hintbar .chip:not(.mode-chip)').forEach(c => c.addEventListener('click', ()=>{
    if(c.disabled || !ta) return;
    ta.value = c.getAttribute('data-tpl') || '';
    ta.focus(); autoGrow(); syncChips();
  }));

  if(ta){
    ta.addEventListener('input', ()=>{ autoGrow(); syncChips(); saveDraftInput(); });
    ta.addEventListener('keydown', (e)=>{
      if(e.key==='Enter' && !e.shiftKey){ e.preventDefault(); doSend(); }
    });
  }
  if(sendBtn) sendBtn.addEventListener('click', doSend);
  if(attachBtn) attachBtn.addEventListener('click', ()=>{
    const inp = document.createElement('input');
    inp.type='file'; inp.multiple=true;
    inp.onchange = ()=>uploadFiles(inp.files);
    inp.click();
  });

  // ── 能力模式激活（设计模式 / 沉淀入库）──────────────────────────────
  // 模式 = 激活一种专属 agent 工作流；开启后每条消息强制注入该流程规则（不靠 LLM 自觉读 SOUL）。
  // window._activeMode: null | 'design' | 'signal'
  window._activeMode = window._activeMode || null;
  function setMode(mode){
    // 再点当前模式=关闭；点另一个=切换（互斥）
    window._activeMode = (window._activeMode === mode) ? null : mode;
    // 按钮高亮
    const dm = $('#designModeBtn'), sm = $('#signalModeBtn');
    [['design',dm],['signal',sm]].forEach(([k,btn])=>{
      if(!btn) return;
      const on = window._activeMode === k;
      btn.style.background = on ? 'var(--brand-strong)' : '';
      btn.style.color = on ? '#fff' : '';
      btn.style.borderColor = on ? 'var(--brand-strong)' : '';
    });
    renderModeBanner();
    // placeholder 提示
    if(ta){
      ta.placeholder = window._activeMode==='design' ? '描述你要规划的产品问题与约束（目标/背景/限制），agent 将带你走设计收敛…'
        : window._activeMode==='signal' ? '粘贴会议纪要 / 客户反馈 / 聊天记录，agent 会清洗成规范信号…'
        : '和你的 agent 对话… 或 @成员名 发快速通知；可拖文件上传';
    }
    toast(window._activeMode==='design' ? '🎯 设计模式已激活：接下来 agent 按「设计收敛」流程推进'
      : window._activeMode==='signal' ? '📥 沉淀入库模式已激活：粘贴原始信息，agent 判类清洗后提交入库'
      : '已退出模式，恢复普通对话');
  }
  const dmBtn = $('#designModeBtn');
  if(dmBtn) dmBtn.addEventListener('click', ()=>setMode('design'));
  const smBtn = $('#signalModeBtn');
  if(smBtn) smBtn.addEventListener('click', ()=>setMode('signal'));
  // choices 控件点击（事件委托到 transcript）
  const tr = $('#transcript');
  if(tr) tr.addEventListener('click', onChoiceClick);

  // 拖拽上传
  const tip = $('#dragTip');
  ['dragenter','dragover'].forEach(ev => document.addEventListener(ev, e=>{ e.preventDefault(); if(tip) tip.classList.add('show'); }));
  ['dragleave','drop'].forEach(ev => document.addEventListener(ev, e=>{ e.preventDefault(); if(e.target===tip||ev==='drop'){ if(tip) tip.classList.remove('show'); } }));
  document.addEventListener('drop', e=>{
    e.preventDefault(); if(tip) tip.classList.remove('show');
    if(e.dataTransfer && e.dataTransfer.files.length) uploadFiles(e.dataTransfer.files);
  });
};

window.loadChat = async function(){
  await loadSessions();
  await loadModelHint();
  // 若无会话，显示欢迎
  const tr = $('#transcript');
  if(tr && !tr.innerHTML.trim()){
    tr.innerHTML = `<div class="cmsg ai"><div class="cav">AI</div><div class="cb"><div class="cn">你的 agent</div>
      <div class="cc">你好 ${h(W.USER.username)}！我是你的 WDP 产品团队专属助手。<br>可以让我清洗信号、起草需求/PRD、问 WDP 产品知识，或点下方模板开始。</div></div></div>`;
  }
};

// #4：思考态显示净化——推理原文含markdown符号/被截断的半句，直接slice显示像乱码。
// 取最后一段完整文字，去掉markdown标记与代码符号，限长。
function thinkingPreview(reasoning){
  if(!reasoning) return '';
  let t = reasoning.replace(/```[\s\S]*?```/g, ' ')      // 代码块
                   .replace(/[#*`>|\[\]{}_~\-]{2,}/g, ' ') // 连续markdown符号
                   .replace(/[#*`>|]/g, '')
                   .replace(/\s+/g, ' ').trim();
  if(t.length > 100){
    t = t.slice(-100);
    const cut = t.search(/[，。；！？.,;!?\s]/);   // 从标点/空白后开始，避免半词
    if(cut > -1 && cut < 40) t = t.slice(cut+1);
  }
  return t;
}
function thinkingHtml(reasoning){
  const t = thinkingPreview(reasoning);
  return '<span style="color:var(--ink-3);font-style:italic">💭 思考中… '+(t?h(t):'')+'</span>';
}

// 2c修复：切回对话视图时恢复流式状态显示（wb.js show('chat') 调用）
window.wbChatResume = function(){
  setComposerBusy();   // 按当前会话是否流式刷新输入框置灰
  loadChatWorkspaceList();  // #3：个人中心可能刚登记设备/配了工作库，切回时重新拉环境刷新列表
  const S = activeSid && STREAMS[activeSid];
  if(S && S.busy){
    // 当前会话在流式：确认转录区最后有活的渲染节点，没有则补一个并重绑
    const tr = $('#transcript');
    const target = S.node;
    if(!target || !tr || !tr.contains(target)){
      // 防双气泡：补建前先清掉转录区里可能残留的旧流式占位节点
      // （历史渲染和流式恢复的时序差会留下孤儿节点，不清就会出现同一轮两个回复气泡）
      if(tr){
        tr.querySelectorAll('.cmsg.ai').forEach(n=>{
          const cc = n.querySelector('.cc');
          if(cc && (cc.textContent.trim()==='思考中…' || cc.textContent.trim()==='' )) n.remove();
        });
      }
      const aiNode = appendMsg('assistant', '');
      const cc = aiNode.querySelector('.cc');
      if(S.answer){ cc.innerHTML = renderMd(S.answer); }
      else if(S.reasoning){ cc.innerHTML = thinkingHtml(S.reasoning); }
      else { cc.innerHTML = '<span style="color:var(--ink-3)">思考中…</span>'; }
      S.node = cc;
    }
    scrollBottom();
  }
};

function autoGrow(){
  const ta = $('#composerInput');
  if(!ta) return;
  ta.style.height = 'auto';
  ta.style.height = Math.min(ta.scrollHeight, 120) + 'px';
}
function syncChips(){
  const ta = $('#composerInput');
  const hasText = (ta && ta.value.trim().length>0) || pendingFiles.length>0;
  $$('.hintbar .chip').forEach(c => c.disabled = hasText);
}

// ── 会话列表 ──
// R40 状态模型：activeSid=当前真实会话id；_draftMode=新对话草稿态(未发消息,不落盘)
let _draftMode = false;
let _realSessCount = 0;   // 侧栏真实会话数（新建上限判断）
// sid → 对话正文真实条数（过滤 tool/空占位后）。持久化到 localStorage：
// 侧栏计数 = 气泡数（归组后），打开过一次的会话记住，刷新/重进页面也显示一致。
// key 带版本 v2：口径从"过滤后消息数"改为"气泡数"，旧缓存作废重算，避免显示旧的偏大值。
let _visibleCnt = {};
try{ _visibleCnt = JSON.parse(localStorage.getItem('wb_visible_cnt_v2') || '{}') || {}; }catch(_){ _visibleCnt = {}; }
try{ localStorage.removeItem('wb_visible_cnt'); }catch(_){}   // 清掉旧口径缓存
function _saveVisibleCnt(){
  try{
    // 只保留最近 50 条，防止无限膨胀
    const keys = Object.keys(_visibleCnt);
    if(keys.length > 50){ keys.slice(0, keys.length-50).forEach(k=>delete _visibleCnt[k]); }
    localStorage.setItem('wb_visible_cnt_v2', JSON.stringify(_visibleCnt));
  }catch(_){}
}
const _MAX_SESS = 10;     // 对话卡片上限

function draftKey(){ return 'wb_draft_' + (activeSid || (_draftMode ? 'new' : 'welcome')); }
function saveDraftInput(){
  const ta = $('#composerInput');
  if(!ta) return;
  try{ sessionStorage.setItem(draftKey(), ta.value || ''); }catch(_){}
}
function restoreDraftInput(){
  const ta = $('#composerInput');
  if(!ta) return;
  try{ ta.value = sessionStorage.getItem(draftKey()) || ''; }catch(_){ ta.value=''; }
  autoGrow(); syncChips();
}

async function loadSessions(){
  const list = $('#sessList');
  if(!list) return;
  try{
    const d = await api('/api/sessions');
    const sessions = (d && (d.sessions || d.items)) || [];
    let html = '';
    // 草稿态：顶部插入草稿卡（点击可切回）
    if(_draftMode){
      html += `<div class="sess draft ${!activeSid?'active':''}" data-sid="__draft__">
        <div class="st">🆕 新对话</div><div class="sm">发消息后保存</div></div>`;
    }
    if(!sessions.length && !_draftMode){
      html += '<div style="color:var(--ink-3);font-size:12px;padding:12px;text-align:center">还没有对话，点上方 ＋ 开始</div>';
    }
    html += sessions.slice(0,30).map(s=>{
      const sid = s.session_id || s.id;
      const title = s.title || '未命名对话';
      // 计数口径：打开过的会话用真实对话正文条数（localStorage 持久化，刷新页面也一致）；
      // 从没打开过的不显示误导性的原始 message_count（含大量 tool/空占位，如 114 vs 13），
      // 显示中性占位，点开后自动回填真实值。
      const known = _visibleCnt[sid];
      const cntLabel = (known!=null) ? (known + ' 条消息') : '点击查看';
      return `<div class="sess ${sid===activeSid?'active':''}" data-sid="${h(sid)}">
        <div class="st">${h(title)}</div><div class="sm">${cntLabel}</div>
        <button class="sess-rename" data-sid="${h(sid)}" data-title="${h(title)}" title="重命名">✏️</button>
        <button class="sess-del" data-sid="${h(sid)}" data-title="${h(title)}" title="删除对话">🗑</button></div>`;
    }).join('');
    list.innerHTML = html;
    // 记录真实会话数（新建对话上限判断用）
    _realSessCount = sessions.length;
    // 卡片点击：切换会话 / 切回草稿
    list.querySelectorAll('.sess').forEach(el => el.addEventListener('click', ()=>{
      const sid = el.dataset.sid;
      if(sid === '__draft__'){ switchToDraft(); return; }
      switchSession(sid);
    }));
    // 重命名（阻止冒泡）
    list.querySelectorAll('.sess-rename').forEach(b => b.addEventListener('click', async (e)=>{
      e.stopPropagation();
      const nt = await wbPrompt('对话名称：', {value: b.dataset.title||''});
      if(!nt || nt === b.dataset.title) return;
      try{
        await api('/api/session/rename', {method:'POST', body:JSON.stringify({session_id:b.dataset.sid, title:nt})});
        loadSessions(); updateChatTitle(nt);
      }catch(err){ toast('重命名失败：'+err.message, true); }
    }));
    // 删除对话（双源删除：WebUI json + state.db，后端已实现）
    list.querySelectorAll('.sess-del').forEach(b => b.addEventListener('click', async (e)=>{
      e.stopPropagation();
      const delSid = b.dataset.sid, delTitle = b.dataset.title||'该对话';
      if(!(await wbConfirm(`确定删除对话「${delTitle}」？此操作会从服务器彻底删除，不可恢复。`))) return;
      try{
        await api('/api/session/delete', {method:'POST', body:JSON.stringify({session_id:delSid})});
        // 删的是当前会话 → 回到欢迎态
        if(delSid === activeSid){ activeSid = null; _draftMode = false;
          const tr=$('#transcript'); if(tr) tr.innerHTML=''; updateChatTitle(); }
        // 清掉该会话的计数缓存（防 localStorage 残留）
        delete _visibleCnt[delSid]; _saveVisibleCnt();
        toast('已删除对话');
        loadSessions();
      }catch(err){ toast('删除失败：'+err.message, true); }
    }));
  }catch(e){
    list.innerHTML = `<div style="color:var(--ink-3);font-size:12px;padding:12px">会话列表加载失败</div>`;
  }
  // 新对话按钮
  const newBtn = $('#viewChat .sess-panel .side-head button');
  if(newBtn) newBtn.onclick = newSession;
  // 重试上一条按钮：用上一条消息重新发送（模型/网络出错时不用重新输入）
  const rtb = $('#chatRetryBtn');
  if(rtb && !rtb._bound){ rtb._bound=1; rtb.onclick = retryLastMsg; }
  // 消息操作栏（复制/重试/编辑）——事件委托到 transcript，覆盖动态追加的消息
  const trEl = $('#transcript');
  if(trEl && !trEl._actBound){ trEl._actBound=1; trEl.addEventListener('click', onMsgAct); }
  // 个人工作库侧栏
  loadChatWorkspaceList();
}

// 顶部对话标题控件已移除（与侧栏标题重复，用户确认删除）；保留空函数兼容旧调用点
function updateChatTitle(_title){ /* no-op：chatTitleLabel 控件已从 workbench.html 删除 */ }

// R29：@成员自动提示（输入@时弹成员列表，点选补全，不靠手打）
let _memberList = null;
async function ensureMembers(){
  if(_memberList) return _memberList;
  try{ const d = await api('/api/me/members'); _memberList = (d.members||[]).filter(m=>m.username!==(W.USER&&W.USER.username)); }
  catch(_){ _memberList = []; }
  return _memberList;
}
function bindMentionSuggest(){
  const ta = $('#composerInput');
  const box = $('#composerBox');
  if(!ta || !box || ta._mentionBound) return;
  ta._mentionBound = 1;
  let panel = null;
  const closePanel = ()=>{ if(panel){ panel.remove(); panel=null; } };
  ta.addEventListener('input', async ()=>{
    const v = ta.value;
    const m = v.match(/^@([\w-]*)$/);   // 只在开头输入@xxx且未打空格时提示
    if(!m){ closePanel(); return; }
    const members = await ensureMembers();
    const kw = m[1].toLowerCase();
    const hits = members.filter(x=>!kw || x.username.toLowerCase().includes(kw));
    closePanel();
    if(!hits.length) return;
    panel = document.createElement('div');
    panel.className = 'mention-panel';
    panel.style.cssText = 'position:absolute;bottom:100%;left:44px;margin-bottom:8px;background:#fff;border:1px solid var(--line);border-radius:12px;box-shadow:var(--shadow);z-index:50;min-width:200px;overflow:hidden';
    panel.innerHTML = '<div style="padding:7px 12px;font-size:11px;color:var(--ink-3);border-bottom:1px solid var(--line-2)">@ 通知团队成员</div>'
      + hits.map(x=>`<div class="mention-item" data-u="${h(x.username)}" style="padding:9px 12px;cursor:pointer;font-size:13px;display:flex;align-items:center;gap:8px">
          <span style="width:24px;height:24px;border-radius:50%;background:var(--brand-soft);color:var(--brand-strong);display:inline-flex;align-items:center;justify-content:center;font-size:11px;font-weight:700">${h(x.username[0].toUpperCase())}</span>
          ${h(x.username)}<span style="color:var(--ink-3);font-size:11px">${x.role==='admin'?'管理员':'成员'}</span></div>`).join('');
    box.style.position = 'relative';
    box.appendChild(panel);
    panel.querySelectorAll('.mention-item').forEach(it=>{
      it.addEventListener('mouseenter', ()=>it.style.background='var(--brand-soft)');
      it.addEventListener('mouseleave', ()=>it.style.background='');
      it.addEventListener('click', ()=>{
        ta.value = '@'+it.dataset.u+' ';
        closePanel(); ta.focus();
      });
    });
  });
  ta.addEventListener('blur', ()=>setTimeout(closePanel, 200));
}

async function loadChatWorkspaceList(){
  const box = $('#wsList');
  if(!box) return;
  box.innerHTML = '<div style="color:var(--ink-3);font-size:12px;padding:8px">加载中…</div>';
  let env;
  try{ env = await api('/api/me/environment'); }
  catch(e){ box.innerHTML = '<div style="color:var(--ink-3);font-size:12px;padding:8px">加载失败</div>'; return; }
  _wsEnv = env;

  // P2 环境互锁：未登记设备 → 工作库整体置灰（不跳转，就地明示原因），＋号也置灰
  if(!env.registered){
    box.innerHTML = `<div style="font-size:12px;padding:10px;color:var(--ink-3);line-height:1.7;opacity:.75">
      <div style="color:var(--amber,#d97706);font-weight:600;margin-bottom:4px">⚠ 当前环境未登记</div>
      当前设备与已登记环境不一致或尚未登记，工作库不可用。<br>
      请先到 <a href="#" id="wsGoRegister" style="color:var(--brand-strong);font-weight:600">个人中心 · 登记当前设备</a>
    </div>` + renderOtherWs(env);
    const go = box.querySelector('#wsGoRegister');
    if(go) go.onclick = (e)=>{ e.preventDefault(); jumpToWorkspaceMgmt(); };
    setAddWsBtnState(false);
    return;
  }

  const wss = env.workspaces || [];
  const active = env.active_workspace;
  if(!wss.length){
    box.innerHTML = `<div style="font-size:12px;padding:10px;color:var(--ink-3);line-height:1.7">
      当前设备(${h((env.device&&env.device.name)||'本机')})还没配置工作库目录。<br>
      点上方 ＋ 直接添加工作库。
    </div>` + renderOtherWs(env);
    setAddWsBtnState(true);
    return;
  }

  // 列出可选工作库，点击设为对话默认
  box.innerHTML = wss.map(w=>{
    const on = w.id === active;
    return `<div class="ws-pick" data-wid="${h(w.id)}" title="${h(w.local_path)}" style="display:flex;align-items:center;gap:8px;padding:8px 10px;font-size:12px;border-radius:9px;cursor:pointer;margin-bottom:4px;border:1px solid ${on?'var(--brand)':'transparent'};background:${on?'var(--brand-soft)':'transparent'}">
      <span style="flex-shrink:0">${on?'📂':'📁'}</span>
      <div style="flex:1;min-width:0"><div style="font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${h(w.name)}</div>
      <div style="color:var(--ink-3);font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${h(w.local_path)}</div></div>
      ${on?'<span class="tag green" style="font-size:10px;flex-shrink:0">当前</span>':''}
    </div>`;
  }).join('') + renderOtherWs(env);
  box.querySelectorAll('.ws-pick').forEach(el=>el.addEventListener('click', async ()=>{
    const wid = el.dataset.wid;
    if(wid === active) return;
    try{
      await api('/api/me/workspaces/activate', {method:'POST', body:JSON.stringify({id:wid})});
      if(window.__wb) window.__wb.toast('已切换对话工作库（新对话生效）');
      // #2修复：不再清 activeSid！之前这里清空导致"在已有卡片输入却跳到新会话"（丢历史）。
      // 新工作库只对下一个【新建】对话生效（session/new 时读 active_workspace），当前对话不受影响。
      loadChatWorkspaceList();
    }catch(e){ if(window.__wb) window.__wb.toast('切换失败：'+e.message, true); }
  }));
  setAddWsBtnState(true);
}

// 非当前环境的工作库：置灰展示（可见不可选，含环境不一致场景）
function renderOtherWs(env){
  const others = (env && env.other_workspaces) || [];
  if(!others.length) return '';
  return others.map(w=>`
    <div title="该工作库属于其它设备环境，当前环境不可用" style="display:flex;align-items:center;gap:8px;padding:8px 10px;font-size:12px;border-radius:9px;margin-bottom:4px;opacity:.4;cursor:not-allowed;filter:grayscale(1)">
      <span style="flex-shrink:0">🔒</span>
      <div style="flex:1;min-width:0"><div style="font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${h(w.name)}</div>
      <div style="color:var(--ink-3);font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${h(w.local_path)} · 其它环境</div></div>
    </div>`).join('');
}

let _wsEnv = null;

function jumpToWorkspaceMgmt(){
  const meBtn = document.querySelector('.rail-btn[data-view="me"]');
  if(meBtn) meBtn.click();
  setTimeout(()=>{ const w=document.querySelector('[data-me="workspace"]'); if(w) w.click(); }, 150);
  if(window.__wb) window.__wb.toast('前往个人中心 · 工作库/设备管理');
}

// ＋号：从个人中心已配置的工作库列表中挑选启用（不在对话里新建路径）；未登记环境时置灰
function setAddWsBtnState(enabled){
  const addBtn = $('#viewChat .ws-panel .side-head button');
  if(!addBtn) return;
  addBtn.disabled = !enabled;
  addBtn.style.opacity = enabled ? '' : '.35';
  addBtn.style.cursor = enabled ? '' : 'not-allowed';
  addBtn.title = enabled ? '选择工作库（在个人中心配置）' : '当前环境未登记设备，先到个人中心登记';
  addBtn.onclick = enabled ? pickWorkspaceFromList : ()=>{
    if(window.__wb) window.__wb.toast('当前环境未登记设备，请先到个人中心登记', true);
  };
}
async function pickWorkspaceFromList(){
  // 只从个人中心已配置的工作库里选；没配过就引导去个人中心
  const env = _wsEnv || await api('/api/me/environment').catch(()=>null);
  const wss = (env && env.workspaces) || [];
  if(!wss.length){
    if(await wbConfirm('当前环境还没有配置工作库目录。\n\n工作库在「个人中心 → 个人工作库」配置，现在前往？')){
      jumpToWorkspaceMgmt();
    }
    return;
  }
  const active = env.active_workspace;
  const form = await wbForm('选择对话工作库', [
    {key:'wid', label:'工作库（个人中心已配置）', type:'select', required:true,
     value: active || wss[0].id,
     options: wss.map(w=>({value:w.id, label:`${w.name}（${w.local_path}）`}))}
  ], {okText:'启用'});
  if(!form) return;
  try{
    await api('/api/me/workspaces/activate', {method:'POST', body:JSON.stringify({id:form.wid})});
    if(window.__wb) window.__wb.toast('已切换对话工作库（新对话生效）');
    // #2修复：同上，不清 activeSid，当前对话继续，新工作库对下一个新对话生效
    loadChatWorkspaceList();
  }catch(e){ if(window.__wb) window.__wb.toast('切换失败：'+e.message, true); }
}
function bindAddWsBtn(){
  // 初始绑定（loadChatWorkspaceList 会按环境状态重设）
  setAddWsBtnState(true);
}

function newSession(){
  // 对话卡片上限：达到 10 个真实会话时，提示用户让 agent 帮迁移后手动删除，不再新建
  if(_realSessCount >= _MAX_SESS && !_draftMode){
    wbAlert(`对话数量已达上限（${_MAX_SESS} 个）。\n\n如需开启新对话，请先让 agent 帮你迁移（沉淀/归档）需要保留的一个或多个对话内容，然后手动删除对应的对话卡片（点卡片上的 🗑），腾出位置后即可新建。`);
    return;
  }
  // R40：进入草稿态（不真建session，发消息时才建）；重复点＋只保持一个草稿
  if(window._activeMode){ const mn = window._activeMode==='design'?'设计模式':'沉淀入库模式'; exitActiveMode({toast:`已退出${mn}（新建了会话）`}); }
  saveDraftInput();               // 缓存当前对话未发送的输入
  activeSid = null;
  _draftMode = true;
  const tr = $('#transcript');
  if(tr) tr.innerHTML = `<div class="cmsg ai"><div class="cav">AI</div><div class="cb"><div class="cn">你的 agent</div><div class="cc">新对话已开始，问我点什么吧。</div></div></div>`;
  loadSessions();                 // 重绘列表（含草稿卡高亮）
  updateChatTitle();
  restoreDraftInput();            // 恢复草稿态的输入缓存
  setComposerBusy();              // 2b修复：草稿态是新会话，不继承上一会话的流式置灰
  const inp = $('#composerInput');
  if(inp) inp.focus();
}

// R40：从其它会话切回草稿卡
function switchToDraft(){
  if(window._activeMode){ const mn = window._activeMode==='design'?'设计模式':'沉淀入库模式'; exitActiveMode({toast:`已退出${mn}（切换了会话）`}); }
  saveDraftInput();
  activeSid = null;
  _draftMode = true;
  const tr = $('#transcript');
  if(tr) tr.innerHTML = `<div class="cmsg ai"><div class="cav">AI</div><div class="cb"><div class="cn">你的 agent</div><div class="cc">新对话已开始，问我点什么吧。</div></div></div>`;
  const list = $('#sessList');
  if(list){
    list.querySelectorAll('.sess').forEach(x=>x.classList.toggle('active', x.dataset.sid==='__draft__'));
  }
  updateChatTitle();
  restoreDraftInput();
  setComposerBusy();              // 2b修复：切回草稿卡同样解除流式置灰
}

async function switchSession(sid){
  if(sid === activeSid) return;
  // 切会话前若有激活的能力模式，自动退出并提示（模式属于"当前这轮对话流"，切走即结束，防误操作）
  if(window._activeMode){
    const mn = window._activeMode==='design' ? '设计模式' : '沉淀入库模式';
    exitActiveMode({toast: `已退出${mn}（切换了会话）`});
  }
  saveDraftInput();               // R39/R40：切走前缓存当前输入
  activeSid = sid;
  // R40：切到真实会话时，若草稿无缓存输入则丢弃草稿卡（无内容即清除）
  let draftHasInput = false;
  try{ draftHasInput = !!(sessionStorage.getItem('wb_draft_new')||'').trim(); }catch(_){}
  if(!draftHasInput) _draftMode = false;
  const list = $('#sessList');
  if(list){
    list.querySelectorAll('.sess').forEach(x=>x.classList.toggle('active', x.dataset.sid===sid));
    if(!_draftMode){ const dr=list.querySelector('.sess.draft'); if(dr) dr.remove(); }
  }
  const tr = $('#transcript');
  if(tr) tr.innerHTML = '<div style="color:var(--ink-3);text-align:center;padding:20px">加载对话历史…</div>';
  try{
    const d = await api('/api/session?session_id='+encodeURIComponent(sid)).catch(()=>null)
           || await api('/api/sessions/'+encodeURIComponent(sid)).catch(()=>null);
    const msgs = (d && (d.messages || (d.session && d.session.messages))) || [];
    if(tr){
      // 只渲染对话正文：user + 有实际内容的 assistant。
      // 过滤 tool 角色消息、空 assistant（工具调用中间态）、纯工具结果——
      // 否则历史恢复会冒出一堆"读文件/工具过程"内容（用户反馈的问题）。
      const shown = msgs.filter(m => {
        const role = m.role;
        const c = (m.content || m.text || '').trim();
        if(role === 'user') return !!c;
        if(role === 'assistant') return !!c;   // 空 assistant（工具调用占位）丢弃
        return false;                          // tool / system 等一律不显示
      });
      // 视觉归组：连续的 assistant 消息（同一轮多步 agentic 执行，中间没有 user 打断）
      // 合并成一个气泡，跟实时流式观感一致——避免历史恢复时一轮任务散成一堆过程气泡。
      const groups = [];
      for(const m of shown){
        if(m.role === 'user'){ groups.push({role:'user', parts:[(m.content||m.text||'')]}); }
        else {
          const last = groups[groups.length-1];
          if(last && last.role === 'assistant') last.parts.push(m.content||m.text||'');
          else groups.push({role:'assistant', parts:[(m.content||m.text||'')]});
        }
      }
      // 侧栏计数口径 = 气泡数（groups.length），和转录区实际渲染一致——
      // 不用 shown.length（过滤后消息数），否则多步 agentic 会计数远大于肉眼气泡数。
      _visibleCnt[sid] = groups.length;
      _saveVisibleCnt();
      const _cntEl = document.querySelector('#sessList .sess[data-sid="'+sid+'"] .sm');
      if(_cntEl && !/回复中/.test(_cntEl.textContent)) _cntEl.textContent = groups.length + ' 条消息';
      tr.innerHTML = groups.map(g=>{
        if(g.role === 'user') return renderMsg('user', g.parts[0]);
        if(g.parts.length === 1) return renderMsg('assistant', g.parts[0]);
        // 方向A：同一轮的多段 agent 输出顺序拼成一个连续气泡（和实时观感一致），
        // 不做折叠拆分——设计对话等场景的多段是连贯思考，连续展示更自然。
        return renderAssistantGrouped(g.parts);
      }).join('')
        || '<div style="color:var(--ink-3);text-align:center;padding:20px">（空对话）</div>';
      tr.scrollTop = tr.scrollHeight;
    }
    const title = (d && (d.title || (d.session && d.session.title))) || '';
    updateChatTitle(title || '对话');
  }catch(e){
    if(tr) tr.innerHTML = '<div style="color:var(--ink-3);text-align:center;padding:20px">无法加载历史，可继续新对话</div>';
  }
  // R43：若切到的会话正在流式（后台累积中），恢复显示其进行中的回复
  const S = STREAMS[sid];
  if(S && S.busy){
    const aiNode = appendMsg('assistant', '');
    const cc = aiNode.querySelector('.cc');
    // 把该会话的流式 cc 引用接到新节点，让 refreshIfCurrent 继续写这里
    // 用当前累积状态先渲染一次
    if(S.answer){ cc.innerHTML = renderMd(S.answer); }
    else if(S.reasoning){ cc.innerHTML = thinkingHtml(S.reasoning); }
    else { cc.innerHTML = '<span style="color:var(--ink-3)">思考中…</span>'; }
    // 关键：把流的渲染目标切换到新节点（refreshIfCurrent 里 cc 是闭包变量，需在流定义处支持重绑——通过 S.node）
    S.node = cc;
    tr.scrollTop = tr.scrollHeight;
  }
  restoreDraftInput();            // 恢复该会话的输入缓存
  setComposerBusy();              // R42：切换后按新会话是否流式刷新置灰态
}

async function loadModelHint(){
  const sel = $('#chatModelSelect');
  const hint = $('#chatModelHint');
  if(!sel) return;
  try{
    const d = await api('/api/me/chat_models');
    const opts = (d && d.options) || [];
    // 选中项：后端落盘的渠道 id（唯一标识；空=团队默认）。不再用 model 名反推，
    // 避免团队默认与某渠道同 model 时误选。
    const curId = (d && d.current_channel_id) || '';
    sel.innerHTML = opts.map(o=>`<option value="${h(o.id)}"${o.id===curId?' selected':''}>${h(o.label)}</option>`).join('');
    sel.dataset.prev = curId;
    if(!sel._bound){ sel._bound=1; sel.addEventListener('change', onChatModelChange); }
    if(hint){
      hint.textContent = opts.length>1 ? '' : '个人渠道可在「个人中心」配置';
    }
  }catch(_){
    sel.innerHTML = '<option value="">团队默认模型</option>';
    if(hint) hint.textContent = '个人渠道可在「个人中心」配置';
  }
}

async function onChatModelChange(e){
  const sel = e.target;
  const cid = sel.value;
  const prev = sel.dataset.prev || '';
  try{
    const r = await api('/api/me/channels/set_chat_model', {method:'POST', body:JSON.stringify({id: cid})});
    sel.dataset.prev = cid;
    toast('已切换到「'+(r.label||'团队默认')+'」，下一条消息生效');
  }catch(err){
    // 切换失败回退到上一个选项
    sel.value = prev;
    toast('切换失败：'+(err.message||'请重试'), true);
  }
}

// ── 消息渲染 ──
// 一轮多段 agent 输出归组：顺序拼进同一个气泡（方向A，和实时流式观感一致）。
// 段落间留间距分隔，不折叠——连贯展示 agent 的思考推进。
function renderAssistantGrouped(parts){
  const body = parts.map((p,i)=>`<div${i>0?' style="margin-top:10px"':''}>${renderMd(p)}</div>`).join('');
  return `<div class="cmsg ai"><div class="cav">AI</div><div class="cb">
    <div class="cn">你的 agent</div><div class="cc">${body}</div>
    <div class="msg-acts"><button data-mact="copy" title="复制">📋 复制</button><button data-mact="retry" title="用上一条消息重新发送">🔄 重试</button></div></div></div>`;
}

function renderMsg(role, content){
  if(role === 'user'){
    return `<div class="cmsg me"><div class="cav">${h((W.USER.username||'我')[0])}</div><div class="cb">
      <div class="cn">我</div><div class="cc">${renderMd(content)}</div>
      <div class="msg-acts"><button data-mact="copy" title="复制">📋 复制</button><button data-mact="edit" title="编辑后重新发送">✏️ 编辑</button></div></div></div>`;
  }
  return `<div class="cmsg ai"><div class="cav">AI</div><div class="cb">
    <div class="cn">你的 agent</div><div class="cc">${renderMd(content)}</div>
    <div class="msg-acts"><button data-mact="copy" title="复制">📋 复制</button><button data-mact="retry" title="用上一条消息重新发送">🔄 重试</button></div></div></div>`;
}

// 消息操作栏事件委托：复制 / 重试 / 编辑
function onMsgAct(e){
  const btn = e.target.closest('.msg-acts [data-mact]'); if(!btn) return;
  const cmsg = btn.closest('.cmsg'); if(!cmsg) return;
  const cc = cmsg.querySelector('.cc');
  let text = cc ? (cc.innerText||'').trim() : '';
  // 清理流式尾标（复制/编辑时不带这些）
  text = text.replace(/\s*✓\s*回复完成\s*$/,'').replace(/\s*●?\s*回复中…\s*$/,'')
             .replace(/\s*⚙️\s*已调用\s*\d+\s*个工具\s*$/,'').trim();
  const act = btn.dataset.mact;
  if(act === 'copy'){ copyMsgText(text, btn); }
  else if(act === 'retry'){ retryLastMsg(); }
  else if(act === 'edit'){
    const ta = $('#composerInput');
    if(ta){
      // 去掉用户气泡里附加的\"[已上传到工作库：...]\"提示行
      ta.value = text.replace(/\n*\[已上传到工作库：[^\]]*\]\s*$/,'').trim();
      autoGrow(); ta.focus();
      try{ ta.setSelectionRange(ta.value.length, ta.value.length); }catch(_){}
    }
  }
}

function copyMsgText(text, btn){
  const done = ()=>{ if(btn){ const o=btn.innerHTML; btn.innerHTML='✓ 已复制'; setTimeout(()=>{ btn.innerHTML=o; },1200); } };
  const fallback = ()=>{
    try{ const t=document.createElement('textarea'); t.value=text; t.style.position='fixed'; t.style.opacity='0';
      document.body.appendChild(t); t.select(); document.execCommand('copy'); t.remove(); done(); }
    catch(_){ toast('复制失败', true); }
  };
  if(navigator.clipboard && navigator.clipboard.writeText){
    navigator.clipboard.writeText(text).then(done).catch(fallback);
  } else { fallback(); }
}

function appendMsg(role, content){
  const tr = $('#transcript');
  if(!tr) return null;
  const div = document.createElement('div');
  div.innerHTML = renderMsg(role, content);
  const node = div.firstElementChild;
  tr.appendChild(node);
  tr.scrollTop = tr.scrollHeight;
  return node;
}

// ══════════════════════════════════════════════
//  发送 + SSE 流式接收
// ══════════════════════════════════════════════
// 重试上一条：把上次发送的用户消息重新发一遍（模型/网络出错时免重输）
let _lastUserMsg = '';
function retryLastMsg(){
  if(isCurrentStreaming()){ toast('当前对话正在回复中，请稍候'); return; }
  if(!_lastUserMsg){ toast('还没有可重试的消息'); return; }
  const ta = $('#composerInput');
  if(ta){ ta.value = _lastUserMsg; autoGrow(); }
  doSend();
}

// 解析当前启用的个人工作库真实路径（active_workspace → local_path）。
// 未登记设备/未配工作库/环境不一致 → 返回 null（让 agent 用默认工作目录）。
async function resolveActiveWorkspacePath(){
  try{
    const env = await api('/api/me/environment');
    if(env.registered && env.active_workspace){
      const aw = (env.workspaces||[]).find(w=>w.id===env.active_workspace);
      if(aw && aw.local_path) return aw.local_path;
    }
  }catch(_){}
  return null;
}

async function doSend(){
  // R42：只阻塞"当前会话正在流式"的情况；其它会话在思考不影响当前会话输入
  if(isCurrentStreaming()){ toast('当前对话正在回复中，请稍候'); return; }
  const ta = $('#composerInput');
  const msg = (ta.value || '').trim();
  if(!msg && !pendingFiles.length){ return; }

  // ④ @通知：识别 "@用户名 内容" 或 "@用户名：内容" → 直接发站内通知，不进对话
  const mMention = msg.match(/^@([\w][\w-]*)\s*[:：]?\s*(.+)$/s);
  if(mMention){
    const target = mMention[1], text = mMention[2].trim();
    if(text){
      try{
        await api('/api/me/mention', {method:'POST', body:JSON.stringify({username:target, message:text})});
        appendMsg('user', msg);
        const n = appendMsg('assistant', '');
        n.querySelector('.cc').innerHTML = `✅ 已通知 <b>@${h(target)}</b>（对方铃铛会收到）`;
        ta.value=''; autoGrow(); syncChips(); saveDraftInput();
      }catch(e){
        const n = appendMsg('assistant', '');
        n.querySelector('.cc').innerHTML = `<span style="color:var(--danger)">@通知失败：${h(e.message)}</span>`;
      }
      return;
    }
  }

  // 用户气泡（含附件提示）
  let userText = msg;
  if(pendingFiles.length){
    userText += '\n\n[已上传到工作库：' + pendingFiles.map(f=>f.name).join(', ') + ']';
  }
  // 🎯 能力模式：把模式流程规则拼进发给 agent 的消息（强制注入，不靠 LLM 自觉读 SOUL）
  let sendMsg = msg;
  if(window._activeMode){
    const _m = window._activeMode;
    sendMsg = _modeInjectedMessage(_m, msg);
    window._chAnswers = {};   // 清空本轮已选 choices（答案已随消息发出）
    // 沉淀入库=一次性任务：本条消息带指令送出后即退出模式（下条消息回归普通对话）。
    // 设计模式=多轮收敛流程，保持激活，走完由 agent 提示或手动退出。
    if(_m === 'signal'){
      exitActiveMode({toast:'已提交本轮内容，沉淀入库模式已退出（需再沉淀请重新点开）'});
    }
  }
  _lastUserMsg = sendMsg;   // 记录发送消息，供"重试上一条"复用（不含附件提示）
  appendMsg('user', userText);
  ta.value = ''; autoGrow(); syncChips();
  // R40：真正发出消息 → 草稿态转正（会话将由后端落盘）
  const wasDraft = _draftMode && !activeSid;
  _draftMode = false;
  try{ sessionStorage.removeItem('wb_draft_new'); }catch(_){}
  saveDraftInput();
  const filesForThisTurn = pendingFiles.slice();
  pendingFiles = []; renderPending();

  // R42/R43：流式状态按会话存储。先建 session 拿到真实 sid，再建流式状态（修复新建对话 sid=null 的 bug）。
  let streamSid, cc, S;

  function renderStreamInto(node){
    // 把 STREAMS[sid] 当前状态渲染进指定气泡节点（当前活跃会话才调用）
    if(!node) return;
    if(S.answer){
      // #1：流式中的答案末尾加"回复中…"动态标识，明确区别于"✓ 回复完成"
      const typing = '<div class="reply-typing" style="margin-top:6px;font-size:11px;color:var(--ink-3)"><span class="busy-dot">●</span> 回复中…</div>';
      node.innerHTML = renderMd(S.answer) + (S.toolCount? renderToolPanel(S) : '') + typing;
    } else if(S.reasoning){
      node.innerHTML = thinkingHtml(S.reasoning);
    } else {
      node.innerHTML = '<span style="color:var(--ink-3)">思考中…</span>';
    }
  }
  function renderToolPanel(S){
    // 简化：工具面板文本（折叠区在 DOM 里重建复杂，这里用计数提示）
    return '\n\n<div style="font-size:11px;color:var(--ink-3)">⚙️ 已调用 '+S.toolCount+' 个工具</div>';
  }
  function refreshIfCurrent(){
    // 只有当前活跃会话是这条流时才更新 DOM；否则后台累积，切回时由 switchSession 恢复
    if(activeSid === streamSid){
      // R43：渲染目标优先用 switchSession 重绑的 S.node（切回后），否则用发起时的 cc
      const target = S.node || cc;
      renderStreamInto(target);
      scrollBottom();
    }
  }

  try{
    // 1. 若无 session，先创建（新建对话场景；已有会话直接复用 activeSid）
    // #2防御：activeSid 为空但转录区已有多条历史消息且非草稿态 → 状态被意外清空，
    // 拒绝静默新建（那会丢上下文），提示用户重新选卡片。
    if(!activeSid && !wasDraft){
      const trEl = document.getElementById('transcript');
      const histCnt = trEl ? trEl.querySelectorAll('.cmsg').length : 0;
      if(histCnt > 2){
        toast('会话状态异常（当前对话标识丢失），请点击左侧对话卡片重新进入后再发送', true);
        setComposerBusy(false);
        return;
      }
    }
    // 解析当前启用的个人工作库路径（新建会话时传给后端；已有会话也用它给 chat/start）
    const wsPath = await resolveActiveWorkspacePath();
    if(!activeSid){
      const s = await api('/api/session/new', {method:'POST', body:JSON.stringify(
        wsPath ? {profile: W.USER.profile || 'default', workspace: wsPath}
               : {profile: W.USER.profile || 'default'}
      )}).catch(err=>{ console.warn('session/new failed', err); return null; });
      if(s && s.session && s.session.session_id){
        activeSid = s.session.session_id;
      }
    }
    if(!activeSid){ throw new Error('无法创建会话'); }

    // 2a修复：拿到真实 sid 立即在侧栏插入占位卡片（不等流式结束）。
    // 否则 agent 工作期间该会话在侧栏无卡片，用户切走就"找不回"这个对话。
    if(wasDraft){
      const list0 = $('#sessList');
      if(list0){
        const dr = list0.querySelector('.sess.draft'); if(dr) dr.remove();
        const card = document.createElement('div');
        card.className = 'sess active';
        card.dataset.sid = activeSid;
        card.innerHTML = `<div class="st">${h(msg.slice(0,24)||'新对话')}</div><div class="sm">回复中…</div>`;
        card.addEventListener('click', ()=>switchSession(card.dataset.sid));
        list0.querySelectorAll('.sess').forEach(x=>x.classList.remove('active'));
        list0.prepend(card);
        _realSessCount++;
      }
      updateChatTitle(msg.slice(0,24)||'新对话');
    }

    // 拿到真实 sid 后，才创建气泡和流式状态
    streamSid = activeSid;
    const aiNode = appendMsg('assistant', '');
    cc = aiNode.querySelector('.cc');
    cc.innerHTML = '<span style="color:var(--ink-3)">思考中…</span>';
    S = STREAMS[streamSid] = {
      answer: '', reasoning: '', busy: true, toolLog: [], toolCount: 0,
      evtSource: null, finalHtml: null, node: cc
    };
    setComposerBusy(true);   // 仅当"当前活跃会话"是这条流时才真正置灰
    // 2. chat/start
    const startBody = {
      session_id: activeSid,
      message: sendMsg || '（见上传的文件）',
      profile: W.USER.profile || 'default',
      // 优先用用户在个人中心启用的工作库路径；没配则不传，让后端沿用 session 已设的 workspace
      workspace: wsPath || undefined
    };
    const startData = await api('/api/chat/start', {method:'POST', body:JSON.stringify(startBody)});
    const streamId = startData.stream_id;
    if(!streamId){ throw new Error('未返回 stream_id'); }

    // 3. SSE —— 事件统一写入 S（按 streamSid），渲染走 refreshIfCurrent
    const url = new URL('api/chat/stream?stream_id='+encodeURIComponent(streamId), document.baseURI||location.href).href;
    S.evtSource = new EventSource(url, {withCredentials:true});

    S.evtSource.addEventListener('token', e=>{
      try{ S.answer += JSON.parse(e.data).text || ''; }catch(_){}
      refreshIfCurrent();
    });
    S.evtSource.addEventListener('reasoning', e=>{
      try{ S.reasoning += JSON.parse(e.data).text || ''; }catch(_){}
      refreshIfCurrent();
    });
    S.evtSource.addEventListener('tool', e=>{
      try{
        const d = JSON.parse(e.data);
        if(d.name==='clarify') return;
        S.toolCount++;
        S.toolLog.push((d.name||'工具') + ' · ' + (d.preview||'调用中'));
        refreshIfCurrent();
      }catch(_){}
    });
    S.evtSource.addEventListener('done', e=>{
      try{ const d=JSON.parse(e.data); if(d.answer && !S.answer){ S.answer=d.answer; } }catch(_){}
      finishStream();
    });
    S.evtSource.addEventListener('apperror', e=>{
      let m=''; try{ m=JSON.parse(e.data).message||''; }catch(_){}
      S.answer = S.answer || '';
      S.error = m || '出错了';
      if(activeSid===streamSid){ const t=S.node||cc; if(t) t.innerHTML = '<span style="color:var(--danger)">出错了：'+h(m||'请重试')+'</span>'; }
      finishStream();
    });
    S.evtSource.addEventListener('stream_end', ()=>finishStream());
    S.evtSource.onerror = ()=>{ if(S.busy){ finishStream(); } };

  }catch(e){
    if(activeSid===streamSid && cc){ cc.innerHTML = '<span style="color:var(--danger)">发送失败：'+h(e.message)+'</span>'; }
    else { toast('发送失败：'+e.message, true); }
    if(S) S.busy = false;
    if(streamSid) delete STREAMS[streamSid];
    setComposerBusy(false);
  }

  function finishStream(){
    if(S.evtSource){ try{ S.evtSource.close(); }catch(_){} S.evtSource=null; }
    S.busy = false;
    // #1：回复完成标识——底部加一行"✓ 回复完成"，区别于流式中的"回复中…"
    const doneMark = '<div class="reply-done" style="margin-top:6px;font-size:11px;color:var(--brand-strong);opacity:.8">✓ 回复完成</div>';
    S.finalHtml = S.answer ? (renderMd(S.answer) + doneMark) : (S.error ? '<span style="color:var(--danger)">出错了：'+h(S.error)+'</span>' : '<span style="color:var(--ink-3)">（无回复）</span>');
    // 更新 DOM（若当前还是这条流）
    if(activeSid===streamSid){
      const target = S.node || cc;
      if(!S.answer.trim() && !S.error && target.innerHTML.includes('思考中')){ target.innerHTML = '<span style="color:var(--ink-3)">（无回复）</span>'; }
      else if(S.answer){ target.innerHTML = S.finalHtml; }
      setComposerBusy(false);
    }
    // 流结束，清掉该会话的流式状态（finalHtml 已由后端落盘，重新拉历史即有）
    // 保留一小段时间供切回渲染？不需要——switchSession 重新拉历史即可。
    delete STREAMS[streamSid];
    // 更新该会话的对话正文真实条数缓存（当前 transcript 里的 .cmsg 即过滤后的对话条数），
    // 供侧栏计数用，避免刚发完消息卡片显示后端偏大的 message_count。
    if(activeSid === streamSid){
      const tr2 = document.getElementById('transcript');
      if(tr2){ _visibleCnt[streamSid] = tr2.querySelectorAll('.cmsg').length; _saveVisibleCnt(); }
    }
    // 刷新会话列表（标题可能更新、新对话转正）
    loadSessions();
  }
}

// R39/R42：忙碌态——只当"当前活跃会话正在流式"时置灰该会话输入框；其它会话流式不影响
function setComposerBusy(_ignored){
  // 不再用传入的 busy 标志，改为根据当前 activeSid 是否流式动态判定（R42 关键）
  const busy = isCurrentStreaming();
  const ta = $('#composerInput');
  const sendBtn = document.querySelector('.chat-composer .send');
  const bar = $('#chatBusyBar');
  if(ta){
    ta.disabled = !!busy;
    ta.style.opacity = busy ? '.55' : '';
    ta.style.cursor = busy ? 'not-allowed' : '';
    if(busy) ta.placeholder = 'agent 正在思考回复中…';
    else ta.placeholder = '和你的 agent 对话… 或 @成员名 发快速通知；可拖文件上传';
  }
  if(sendBtn){ sendBtn.disabled = !!busy; sendBtn.style.opacity = busy ? '.4' : ''; }
  if(bar) bar.style.display = busy ? 'flex' : 'none';
  if(!busy){ const ta2=$('#composerInput'); if(ta2 && document.activeElement!==ta2) { /* 不强制抢焦 */ } }
}

function scrollBottom(){
  const tr = $('#transcript');
  if(tr) tr.scrollTop = tr.scrollHeight;
}

// ── 文件上传到个人工作库 ──
async function uploadFiles(fileList){
  for(const f of fileList){
    const fd = new FormData();
    fd.append('file', f, f.name);
    try{
      const r = await fetch('/api/me/upload', {method:'POST', credentials:'same-origin',
        headers: window.__CSRF_TOKEN__ ? {'X-CSRF-Token':window.__CSRF_TOKEN__} : {}, body:fd});
      if(r.status === 401){ location.href = '/login?next=' + encodeURIComponent(location.pathname); return; }
      const d = await r.json();
      if(r.ok){ pendingFiles.push({name:d.filename||f.name, path:d.path}); toast('已上传 '+(d.filename||f.name)); }
      else toast('上传失败：'+(d.error||r.status), true);
    }catch(e){ toast('上传失败：'+e.message, true); }
  }
  renderPending();
  syncChips();
}

function renderPending(){
  const box = $('#pendingFiles');
  if(!box) return;
  box.innerHTML = pendingFiles.map((f,i)=>`<div class="pf">📎 ${h(f.name)} <span class="x" data-i="${i}">✕</span></div>`).join('');
  box.querySelectorAll('.pf .x').forEach(x => x.addEventListener('click', ()=>{
    pendingFiles.splice(+x.dataset.i,1); renderPending(); syncChips();
  }));
}

})();
