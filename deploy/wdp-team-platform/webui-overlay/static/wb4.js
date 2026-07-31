/* ============================================================
   WDP 团队工作台 · 高级操作模块（wb4.js）
   对齐原型：信号(筛选/归并/沉淀为需求) 需求(分组/通知/分配)
             设计(新建) 全局搜索
   依赖 wb.js 的 window.__wb
   ============================================================ */
(function(){
'use strict';
const W = window.__wb;
if(!W){ console.error('wb.js 未加载'); return; }
const {api, h, tag, toast} = W;
const stColor = W.stColor || (s=>'gray');
const stLabel = W.stLabel || (s=>s||'');
const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);

// 归并模式：多选信号

// ── 绑定工作台所有增强按钮（在 board 首次加载后调用）──
function bindBoardActions(){
  // 信号：筛选
  const fb = $('#sigFilterBtn');
  if(fb && !fb._bound){ fb._bound=1; fb.onclick = openSigFilter; }
  // 信号：归并（进入多选模式）
  const mb = $('#sigMergeBtn');
  if(mb && !mb._bound){ mb._bound=1; mb.onclick = ()=>{ if(window.wbOpenMergeDialog) window.wbOpenMergeDialog(); }; }
  // 信号：沉淀为需求（顶部按钮 = 提示去展开选信号）
  const tr = $('#sigToReqBtn');
  if(tr && !tr._bound){ tr._bound=1; tr.onclick = pickSignalToReq; }
  // 需求：筛选
  const gb = $('#reqFilterBtn');
  if(gb && !gb._bound){ gb._bound=1; gb.onclick = openReqFilter; }
  // 需求：通知组员
  const nb = $('#reqNotifyBtn');
  if(nb && !nb._bound){ nb._bound=1; nb.onclick = ()=>notifyMember(''); }
  // 设计：新建
  const nd = $('#newDesignBtn');
  if(nd && !nd._bound){ nd._bound=1; nd.onclick = newDesign; }
}
// board 每次渲染后按钮会保留（panel-head 不重绘），首次绑定即可。用 MutationObserver 兜底：
document.addEventListener('DOMContentLoaded', ()=>setTimeout(bindBoardActions, 500));
// 也在切到工作台时绑（wb.js show 调 loadWorkbench 后 DOM 已就绪）
const _origShow = W.show;
// 监听 rail 点击补绑
$$('.rail-btn[data-view="board"]').forEach(b=>b.addEventListener('click', ()=>setTimeout(bindBoardActions, 300)));

// ════════════════════════════════════════════════
//  信号：筛选
// ════════════════════════════════════════════════
function openSigFilter(){
  const cur = W.getSigFilter();
  const overlay = mkOverlay(`
    <h3 style="margin-bottom:14px">🔍 信号筛选</h3>
    <div class="form-row" style="grid-template-columns:90px 1fr"><div class="fl">状态</div><div class="fc">
      <select id="fStatus"><option value="">全部</option>
        ${['待triage','待确认','已确认','已转需求','已归档'].map(s=>`<option ${cur.status===s?'selected':''}>${s}</option>`).join('')}</select></div></div>
    <div class="form-row" style="grid-template-columns:90px 1fr"><div class="fl">来源</div><div class="fc">
      <select id="fSource"><option value="">全部</option>
        ${['会议纪要','客户反馈','聊天记录','语音','竞品动态','其他'].map(s=>`<option ${cur.source===s?'selected':''}>${s}</option>`).join('')}</select></div></div>
    <div class="form-row" style="grid-template-columns:90px 1fr"><div class="fl">类别</div><div class="fc">
      <select id="fCategory"><option value="">全部</option>
        ${['需求信号','问题信号','趋势信号','风险信号'].map(s=>`<option ${cur.category===s?'selected':''}>${s}</option>`).join('')}</select></div></div>
    <div class="form-row" style="grid-template-columns:90px 1fr"><div class="fl">紧急度</div><div class="fc">
      <select id="fUrgency"><option value="">全部</option>
        ${['高','中','低'].map(s=>`<option ${cur.urgency===s?'selected':''}>${s}</option>`).join('')}</select></div></div>
    <div style="display:flex;gap:10px;margin-top:16px;justify-content:flex-end">
      <button class="btn" id="fClear">清除筛选</button>
      <button class="btn primary" id="fApply">应用</button></div>`);
  overlay.querySelector('#fApply').onclick = ()=>{
    W.setSigFilter({
      status: overlay.querySelector('#fStatus').value,
      source: overlay.querySelector('#fSource').value,
      category: overlay.querySelector('#fCategory').value,
      urgency: overlay.querySelector('#fUrgency').value,
    });
    overlay.remove();
  };
  overlay.querySelector('#fClear').onclick = ()=>{ W.setSigFilter({}); overlay.remove(); };
}

// ════════════════════════════════════════════════
//  信号：归并（多选模式）
// ════════════════════════════════════════════════
// R10：智能归并——调 LLM 分析可归并组，弹框让管理员决策
async function runSmartMerge(){
  const {card, close} = wbModal({width:600});
  card.innerHTML = `<div style="display:flex;align-items:center;gap:9px;margin-bottom:14px"><span style="font-size:20px">🤖</span><h3 style="margin:0;font-size:16px">智能归并分析</h3></div>
    <div id="smBody" style="min-height:120px"><div style="text-align:center;padding:30px;color:var(--ink-3)">
      <div style="font-size:24px">⚙️</div><div style="margin-top:10px">归并 Agent 正在分析活跃信号…</div>
      <div style="font-size:11px;margin-top:4px">调用团队模型，请稍候（约 10-30 秒）</div></div></div>`;
  try{
    const d = await api('/api/admin/merge/analyze');
    const groups = d.groups || [];
    const mis = d.miscategorized || [];
    // 类目错放提示块（归并agent顺带检查出的"不该是信号"的条目）
    const misHtml = mis.length ? `<div style="border:1px solid rgba(180,140,40,.35);border-radius:12px;padding:10px 14px;margin-bottom:10px;background:rgba(180,140,40,.07)">
        <div style="font-weight:700;color:#9a6b1a;margin-bottom:6px">⚠ 疑似类目错放（${mis.length} 条）</div>
        ${mis.map(m=>`<div style="font-size:12px;color:var(--ink-2);margin-bottom:4px">· <b>${h(m.signal_id)}</b> ${h(m.title||'')} → 建议改为 <b>${h(m.suggested_category)}</b>：${h(m.reason||'')}</div>`).join('')}
        <div style="font-size:11px;color:var(--ink-3);margin-top:6px">处理方式：需求类可直接用信号卡片的「沉淀为需求」流转；设计/决策类可让 agent 重新提交到对应类目。</div>
      </div>` : '';
    const body = card.querySelector('#smBody');
    if(!groups.length && !mis.length){
      body.innerHTML = `<div style="text-align:center;padding:24px;color:var(--ink-3)">✓ ${h(d.message||'没有发现可归并的信号')}</div>
        <div style="text-align:right"><button class="wbm-btn" id="smClose">知道了</button></div>`;
      body.querySelector('#smClose').onclick=()=>close();
      return;
    }
    body.innerHTML = `<div style="font-size:12px;color:var(--ink-3);margin-bottom:10px">${h(d.message||'')}（模型：${h(d.model||'')}）</div>`
      + misHtml
      + (d.history_count?`<div style="font-size:11px;color:var(--brand-strong);margin-bottom:8px">🧠 已学习 ${d.history_count} 条团队历史归并决策，建议已贴合团队风格</div>`:
         `<div style="font-size:11px;color:var(--ink-3);margin-bottom:8px">💡 首次使用：执行归并后决策会被记录，AI 将逐步学习团队风格</div>`)
      + groups.map((g,i)=>`
        <div class="sm-group" data-i="${i}" style="border:1px solid var(--brand);border-radius:12px;padding:12px 14px;margin-bottom:10px;background:var(--brand-soft)">
          <div style="font-weight:700;color:var(--brand-strong);margin-bottom:6px">建议 ${i+1}：${h(g.suggested_title||'归并信号')}</div>
          <div style="font-size:12px;color:var(--ink-2);margin-bottom:8px">📎 ${g.signals.map(s=>h(s.id+' '+(s.title||''))).join(' ＋ ')}</div>
          <div style="font-size:12px;color:var(--ink-3);margin-bottom:10px">💡 ${h(g.reason||'')}</div>
          <div style="display:flex;gap:8px">
            <input class="wbm-in sm-title" value="${h(g.suggested_title||'').replace(/"/g,'&quot;')}" style="flex:1">
            <button class="wbm-btn wbm-primary sm-do" data-i="${i}">执行归并</button>
          </div>
        </div>`).join('')
      + `<div style="text-align:right;margin-top:6px"><button class="wbm-btn" id="smClose">关闭</button></div>`;
    body.querySelector('#smClose').onclick=()=>close();
    body.querySelectorAll('.sm-do').forEach(btn=>btn.onclick=async()=>{
      const gi = +btn.dataset.i;
      const g = groups[gi];
      const grp = body.querySelector(`.sm-group[data-i="${gi}"]`);
      const title = grp.querySelector('.sm-title').value.trim() || g.suggested_title;
      btn.disabled=true; btn.textContent='归并中…';
      try{
        await api('/api/knowledge/merge', {method:'POST', body:JSON.stringify({ids:g.signal_ids, title:title, body:(g.suggested_body||''), urgency:g.suggested_urgency||''})});
        // 简化session：记录本次归并决策（AI建议 vs 管理员最终执行），供下次few-shot学习
        api('/api/admin/team-agent/record-decision', {method:'POST', body:JSON.stringify({
          kind:'merge', entry:{signal_ids:g.signal_ids, suggested_title:g.suggested_title,
            final_title:title, adopted:title===g.suggested_title, reason:g.reason||''}
        })}).catch(()=>{});
        grp.style.opacity='.5'; grp.innerHTML=`<div style="color:var(--brand-strong);font-weight:600">✓ 已归并为新信号：${h(title)}（决策已记录，AI 将学习）</div>`;
        W.LOADED.board=false; if(window.wbRefreshRailCnt)window.wbRefreshRailCnt(); W.loadSignals();
      }catch(e){ btn.disabled=false; btn.textContent='执行归并'; toast('归并失败：'+e.message, true); }
    });
  }catch(e){
    card.querySelector('#smBody').innerHTML = `<div style="text-align:center;padding:24px;color:var(--danger)">分析失败：${h(e.message)}</div>
      <div style="text-align:right"><button class="wbm-btn" id="smClose2">关闭</button></div>`;
    card.querySelector('#smClose2').onclick=()=>close();
  }
}


// ════════════════════════════════════════════════
//  信号：沉淀为需求（wb.js 详情里的按钮调这个）
// ════════════════════════════════════════════════
// 顶部「＋沉淀为需求」：弹出待沉淀信号列表选一条
// R11：拉成员列表（分配/指派/通知的下拉选项，含"待分配"）
let _memberCache = null;
async function getMemberOptions(includeUnassign){
  if(!_memberCache){
    try{
      const d = await api('/api/admin/users');
      _memberCache = (d.users||[]).filter(u=>u.active!==false).map(u=>({value:u.username, label:`${u.username}${u.role==='admin'?'(管理员)':''}`}));
    }catch(_){ _memberCache = []; }
  }
  return includeUnassign ? [{value:'待分配',label:'待分配'}, ..._memberCache] : _memberCache.slice();
}
// R11：拉需求列表（关联需求的下拉选项）
async function getRequirementOptions(){
  try{
    const d = await api('/api/knowledge/requirements');
    return (d.items||[]).map(r=>({value:r.id, label:`${r.id} · ${(r.title||'').slice(0,20)}`}));
  }catch(_){ return []; }
}

async function pickSignalToReq(){
  let sigs = [];
  try{
    sigs = ((await api('/api/knowledge/signals')).items || [])
      .filter(s => (s.status||'') !== '已转需求' && (s.status||'') !== '已合并');
  }catch(e){ toast('加载信号失败：'+e.message, true); return; }
  if(!sigs.length){ await wbAlert('没有可沉淀的信号（待处理信号为空）'); return; }
  const {card, close} = wbModal({width:520});
  card.innerHTML = `<div style="display:flex;align-items:center;gap:9px;margin-bottom:14px"><span style="font-size:20px">📋</span><h3 style="margin:0;font-size:16px">选择要沉淀为需求的信号</h3></div>
    <div style="max-height:50vh;overflow-y:auto">${sigs.map(s=>`
      <div class="pick-sig" data-id="${h(s.id||s._file)}" style="padding:10px 12px;border:1px solid var(--line);border-radius:10px;margin-bottom:8px;cursor:pointer;transition:.12s">
        <div style="font-weight:600;font-size:13px">${h(s.title||'(无标题)')}</div>
        <div style="font-size:11px;color:var(--ink-3);margin-top:2px">${h(s.id||'')} · ${h(s.category||'')} · 紧急度 ${h(s.urgency||'—')}</div>
      </div>`).join('')}</div>
    <div style="display:flex;justify-content:flex-end;margin-top:12px"><button class="wbm-btn" id="psCancel">取消</button></div>`;
  card.querySelectorAll('.pick-sig').forEach(el=>{
    el.onmouseenter=()=>el.style.background='var(--brand-soft)';
    el.onmouseleave=()=>el.style.background='';
    el.onclick=()=>{ close(); window.wbSignalToReq(el.dataset.id); };
  });
  card.querySelector('#psCancel').onclick=()=>close();
}

window.wbSignalToReq = async function(signalId){
  const members = await getMemberOptions(true);
  // 沉淀去向：公共需求池 / 某个已开档项目 / 新建项目并归入（信号可随时归类）
  let prjOptions = [];
  let projects = [];
  try{
    const pj = await api('/api/knowledge/projects');
    projects = (pj.projects||[]).filter(p=>p.status!=='已结项');
    prjOptions = projects.map(p=>({value:'prj:'+p.dir, label:`📦 项目：${p.title}（${p.customer||'—'}）`}));
  }catch(_){}
  // 项目归属预选：信号带 related_project 标记时，默认选中对应项目（agent 提交时标记的归属，
  // 管理员不用靠记忆匹配——项目链路的关键衔接点）
  let defDest = 'pool';
  try{
    const it = await api('/api/knowledge/item?type=signals&id='+encodeURIComponent(signalId));
    const rp = (it.item && it.item.related_project || '').trim();
    if(rp){
      const hit = projects.find(p => p.title===rp || p.dir===rp || (p.title||'').includes(rp) || rp.includes(p.title||''));
      if(hit) defDest = 'prj:'+hit.dir;
    }
  }catch(_){}
  const destOptions = [
    {value:'pool', label:'📋 公共需求池'},
    ...prjOptions,
    {value:'__new__', label:'＋ 新建项目并归入（项目信号，项目还没建）'},
  ];
  const form = await wbForm('沉淀为需求', [
    {key:'dest', label:'沉淀去向'+(defDest!=='pool'?'（已按信号的项目归属预选）':''), type:'select', value:defDest, options:destOptions},
    {key:'priority', label:'需求优先级（仅公共需求池用）', type:'select', value:'P2', options:['P0','P1','P2','P3']},
    {key:'owner', label:'分配负责人', type:'select', value:'待分配', options:members},
  ], {icon:'📋', okText:'下一步'});
  if(!form) return;
  const owner = form.owner==='待分配' ? '' : form.owner;
  let pdir = null;
  // 选「新建项目并归入」→ 先弹开档表单建项目
  if(form.dest === '__new__'){
    const pf = await wbForm('新建项目（开档）', [
      {key:'title', label:'项目名称', type:'text', required:true, placeholder:'如 XX市政数字孪生项目'},
      {key:'customer', label:'客户名称', type:'text', required:true},
      {key:'opportunity', label:'商机号', type:'text', placeholder:'如 SJ-2026-001'},
      {key:'phase', label:'阶段', type:'select', value:'售前', options:['售前','交付中','售后']},
      {key:'bd_owner', label:'BD 负责人', type:'text'},
      {key:'tb_contact', label:'客户 TB 对接人', type:'text'},
      {key:'description', label:'项目概述', type:'textarea', required:true},
    ], {icon:'📦', okText:'开档并沉淀'});
    if(!pf) return;
    try{
      const pr = await wbCreateProjectSafe(pf);
      if(!pr){ return; }
      if(!pr.dir){ toast('开档失败', true); return; }
      pdir = pr.dir;
      toast('项目「'+(pf.title)+'」已开档');
    }catch(e){ toast('开档失败：'+e.message, true); return; }
  }else if(form.dest.startsWith('prj:')){
    pdir = form.dest.slice(4);
  }
  try{
    if(pdir){
      // → 项目需求（PREQ）
      const d = await api('/api/knowledge/to-project-req', {method:'POST', body:JSON.stringify({
        signal_id:signalId, project:pdir, owner })});
      toast(d.message || `已沉淀为项目需求 ${d.id}`);
    }else{
      // → 公共需求池（REQ）
      const d = await api('/api/knowledge/to-requirement', {method:'POST', body:JSON.stringify({signal_id:signalId, priority:form.priority, owner})});
      toast(`已沉淀为需求 ${d.req_id}`);
    }
    W.LOADED.board=false; if(window.wbRefreshRailCnt)window.wbRefreshRailCnt();
    W.loadSignals(); W.loadRequirements();
  }catch(e){ toast('沉淀失败：'+e.message, true); }
};

// ════════════════════════════════════════════════
//  需求：分配 / 通知（wb.js 卡片按钮调这个）
// ════════════════════════════════════════════════
window.wbReqAction = async function(act, ds){
  if(act === 'assign'){
    const members = await getMemberOptions(true);
    const form = await wbForm('分配负责人', [
      {key:'owner', label:'负责人', type:'select', value:ds.owner||'待分配', options:members},
    ], {icon:'👤', okText:'分配'});
    if(!form) return;
    const owner = form.owner;
    try{
      await api('/api/admin/knowledge/update', {method:'POST', body:JSON.stringify({
        type:'requirements', id:ds.id, updates:{owner}, note:'工作台改派负责人'
      })});
      toast('已分配给 '+owner);
      // 自动通知新负责人（设计§12：分配自动通知）
      if(owner && owner!=='待分配'){
        try{ await api('/api/knowledge/notify', {method:'POST', body:JSON.stringify({username:owner, message:`需求「${ds.title||ds.id}」已分配给你，请跟进`})}); }catch(_){}
      }
      W.LOADED.board=false; if(window.wbRefreshRailCnt)window.wbRefreshRailCnt(); W.loadRequirements();
    }catch(e){ toast('分配失败：'+e.message, true); }
  } else if(act === 'notify'){
    const members = await getMemberOptions(false);
    const form = await wbForm('通知成员', [
      {key:'target', label:'通知谁', type:'select', value:ds.owner||'', options:members},
      {key:'msg', label:'通知内容', type:'textarea', value:`请跟进需求「${ds.title||''}」`, required:true},
    ], {icon:'🔔', okText:'发送'});
    if(!form) return;
    try{
      await api('/api/knowledge/notify', {method:'POST', body:JSON.stringify({username:form.target, message:form.msg})});
      toast('已通知 '+form.target);
    }catch(e){ toast('通知失败：'+e.message, true); }
  } else if(act === 'status'){
    const STATES = ['待校验','已确认','设计中','研发中','已上线','已关闭'];
    const cur = ds.status || '待校验';
    const next = await pickOne('改需求状态', STATES, cur);
    if(!next || next===cur) return;
    try{
      await api('/api/admin/knowledge/update', {method:'POST', body:JSON.stringify({
        type:'requirements', id:ds.id, updates:{status:next}, note:`状态 ${cur}→${next}`
      })});
      toast('状态已改为 '+next+'（tracking已记录）');
      W.LOADED.board=false; if(window.wbRefreshRailCnt)window.wbRefreshRailCnt(); W.loadRequirements();
    }catch(e){ toast('改状态失败：'+e.message, true); }
  } else if(act === 'priority'){
    const next = await pickOne('改优先级', ['P0','P1','P2','P3'], ds.priority||'P2');
    if(!next) return;
    try{
      await api('/api/admin/knowledge/update', {method:'POST', body:JSON.stringify({
        type:'requirements', id:ds.id, updates:{priority:next}, note:`优先级改为${next}`
      })});
      toast('优先级已改为 '+next);
      W.LOADED.board=false; if(window.wbRefreshRailCnt)window.wbRefreshRailCnt(); W.loadRequirements();
    }catch(e){ toast('操作失败：'+e.message, true); }
  } else if(act === 'urge'){
    const target = ds.owner;
    if(!target || target==='待分配' || target==='未分配'){ toast('该需求未分配负责人', true); return; }
    if(!(await wbConfirm(`向 ${target} 发送催办提醒？`))) return;
    try{
      await api('/api/knowledge/notify', {method:'POST', body:JSON.stringify({
        username:target, message:`⏰ 催办：需求「${ds.title||ds.id}」请尽快推进`
      })});
      // 催办同时打个标记到 tracking
      await api('/api/admin/knowledge/update', {method:'POST', body:JSON.stringify({
        type:'requirements', id:ds.id, updates:{}, note:`催办 @${target}`
      })}).catch(()=>{});
      toast('已催办 '+target);
    }catch(e){ toast('催办失败：'+e.message, true); }
  } else if(act === 'close'){
    const reason = await wbPrompt('关闭原因（必填）：');
    if(!reason) return;
    try{
      await api('/api/admin/knowledge/update', {method:'POST', body:JSON.stringify({
        type:'requirements', id:ds.id, updates:{status:'已关闭'}, note:`关闭：${reason}`
      })});
      toast('需求已关闭');
      W.LOADED.board=false; if(window.wbRefreshRailCnt)window.wbRefreshRailCnt(); W.loadRequirements();
    }catch(e){ toast('关闭失败：'+e.message, true); }
  } else if(act === 'delete'){
    await wbDeleteItem('requirements', ds.id, ds.title, ()=>{ W.LOADED.board=false; if(window.wbRefreshRailCnt)window.wbRefreshRailCnt(); W.loadRequirements(); });
  }
};

// R6：通用删除（危险操作，二次确认，软删除到归档区，30天后cron真删）
window.wbDeleteItem = async function(category, id, title, onDone){
  const ok = await wbConfirm(`确定删除「${title||id}」？\n\n删除后移入归档区，30天后自动彻底清理。此操作会同时影响关联追溯。`,
    {danger:true, title:'⚠ 删除确认', okText:'删除', icon:'🗑'});
  if(!ok) return;
  try{
    await api('/api/knowledge/delete-item', {method:'POST', body:JSON.stringify({category, id})});
    toast('已删除（移入归档，30天后清理）');
    if(onDone) onDone();
  }catch(e){ toast('删除失败：'+e.message, true); }
};

// ── 信号生命周期（指派确认人）──
window.wbSignalLifecycle = async function(act, sigId){
  if(act === 'assign'){
    const members = await getMemberOptions(false);
    const form = await wbForm('指派确认人', [
      {key:'target', label:'指派给谁校验', type:'select', options:members, required:true},
    ], {icon:'👤', okText:'指派'});
    if(!form) return;
    const target = form.target;
    try{
      // 记录指派人 + 发通知
      await api('/api/admin/knowledge/update', {method:'POST', body:JSON.stringify({
        type:'signals', id:sigId, updates:{assignee:target}, note:`指派 @${target} 校验`
      })});
      await api('/api/knowledge/notify', {method:'POST', body:JSON.stringify({
        username:target, message:`请校验信号「${sigId}」`
      })});
      toast('已指派给 '+target);
      W.LOADED.board=false; if(window.wbRefreshRailCnt)window.wbRefreshRailCnt(); W.loadSignals();
    }catch(e){ toast('指派失败：'+e.message, true); }
  }
};

// ── 设计生命周期（改状态/关联需求/指派评审）──
window.wbDesignAction = async function(act, ds){
  if(act === 'status'){
    const STATES = ['草稿','评审中','已定稿','已交付研发','已废弃'];
    const next = await pickOne('改设计状态', STATES, ds.status||'草稿');
    if(!next || next===ds.status) return;
    let note = `状态 ${ds.status}→${next}`;
    // 定稿/上线时补归档说明
    if(next==='已定稿'){
      const memo = await wbPrompt('定稿说明（可选，会记入 tracking）：') || '';
      if(memo) note += ' · ' + memo;
    }
    try{
      await api('/api/admin/knowledge/update', {method:'POST', body:JSON.stringify({
        type:'designs', id:ds.id, updates:{status:next}, note
      })});
      toast('设计状态已改为 '+next);
      W.LOADED.board=false; if(window.wbRefreshRailCnt)window.wbRefreshRailCnt(); W.loadDesigns();
    }catch(e){ toast('操作失败：'+e.message, true); }
  } else if(act === 'link'){
    const reqs = await getRequirementOptions();
    if(!reqs.length){ await wbAlert('暂无需求可关联'); return; }
    const form = await wbForm('关联需求', [
      {key:'reqId', label:'关联到哪个需求', type:'select', value:ds.req||'', options:reqs, required:true},
    ], {icon:'🔗', okText:'关联'});
    if(!form) return;
    const reqId = form.reqId;
    try{
      await api('/api/admin/knowledge/update', {method:'POST', body:JSON.stringify({
        type:'designs', id:ds.id, updates:{requirement_id:reqId||'待关联'}, note:`关联需求 ${reqId}`
      })});
      toast('已关联需求 '+reqId);
      W.LOADED.board=false; if(window.wbRefreshRailCnt)window.wbRefreshRailCnt(); W.loadDesigns();
    }catch(e){ toast('关联失败：'+e.message, true); }
  } else if(act === 'edit'){
    // ✏️ 编辑设计字段：designer / target_release / doc_url（闭环补全：这些字段非必填，
    // 提交时常没有，这里给 admin 事后补齐的入口，让卡片展示的字段真实有值）
    const members = await getMemberOptions(false);
    const form = await wbForm('编辑设计字段', [
      {key:'designer', label:'设计人', type:'select', value:ds.designer||'', options:[{value:'',label:'（不改）'}, ...members]},
      {key:'target_release', label:'目标版本（如 5.17）', type:'text', value:ds.release||'', placeholder:'留空=不改'},
      {key:'doc_url', label:'设计资料链接（飞书/企微文档 URL）', type:'text', value:ds.docurl||'', placeholder:'留空=不改'},
    ], {icon:'✏️', okText:'保存'});
    if(!form) return;
    const updates = {};
    if(form.designer) updates.designer = form.designer;
    if((form.target_release||'').trim()) updates.target_release = form.target_release.trim();
    if((form.doc_url||'').trim()) updates.doc_url = form.doc_url.trim();
    if(!Object.keys(updates).length){ toast('没有要更新的字段'); return; }
    try{
      await api('/api/admin/knowledge/update', {method:'POST', body:JSON.stringify({
        type:'designs', id:ds.id, updates, note:'编辑字段 '+Object.keys(updates).join('/')
      })});
      toast('已更新 '+Object.keys(updates).join('、'));
      W.LOADED.board=false; if(window.wbRefreshRailCnt)window.wbRefreshRailCnt(); W.loadDesigns();
    }catch(e){ toast('更新失败：'+e.message, true); }
  } else if(act === 'review'){
    const members = await getMemberOptions(false);
    const form = await wbForm('指派评审', [
      {key:'target', label:'指派谁评审', type:'select', options:members, required:true},
    ], {icon:'👤', okText:'指派'});
    if(!form) return;
    const target = form.target;
    try{
      await api('/api/knowledge/notify', {method:'POST', body:JSON.stringify({
        username:target, message:`请评审设计稿「${ds.title||ds.id}」`
      })});
      await api('/api/admin/knowledge/update', {method:'POST', body:JSON.stringify({
        type:'designs', id:ds.id, updates:{reviewer:target}, note:`指派 @${target} 评审`
      })}).catch(()=>{});
      toast('已指派 '+target+' 评审');
    }catch(e){ toast('操作失败：'+e.message, true); }
  } else if(act === 'delete'){
    await wbDeleteItem('designs', ds.id, ds.title, ()=>{ W.LOADED.board=false; if(window.wbRefreshRailCnt)window.wbRefreshRailCnt(); W.loadDesigns(); });
  }
};

// ── 通用单选弹层（返回 Promise<选中值|null>）──
function pickOne(title, options, current){
  return new Promise(resolve=>{
    const overlay = mkOverlay(`
      <h3 style="margin-bottom:14px">${h(title)}</h3>
      <div style="display:flex;flex-direction:column;gap:8px">
        ${options.map(o=>`<button class="btn ${o===current?'primary':''}" data-val="${h(o)}" style="justify-content:flex-start;text-align:left">${h(o)}${o===current?' （当前）':''}</button>`).join('')}
      </div>`);
    overlay.querySelectorAll('[data-val]').forEach(b=>b.addEventListener('click', ()=>{
      const v = b.dataset.val; overlay.remove(); resolve(v);
    }));
    overlay._onClose = ()=>resolve(null);
    // 点遮罩关闭时 resolve null
    const origClick = overlay.onclick;
    overlay.onclick = (e)=>{ if(e.target===overlay){ overlay.remove(); resolve(null); } };
  });
}

// 需求：顶部通知组员按钮
async function notifyMember(preset){
  const members = await getMemberOptions(false);
  const form = await wbForm('通知组员', [
    {key:'target', label:'通知谁', type:'select', value:preset||'', options:members, required:true},
    {key:'msg', label:'通知内容', type:'textarea', required:true},
  ], {icon:'🔔', okText:'发送'});
  if(!form) return;
  try{
    await api('/api/knowledge/notify', {method:'POST', body:JSON.stringify({username:form.target, message:form.msg})});
    toast('已通知 '+form.target);
  }catch(e){ toast('通知失败：'+e.message, true); }
}

// 需求：按负责人分组切换（前端重排看板）
// R12：团队工作产出看板
window.wbLoadOutputBoard = async function(){
  const box = $('#outputBoard');
  if(!box) return;
  box.innerHTML = '<div style="color:var(--ink-3);font-size:13px">加载中…</div>';
  try{
    const d = await api('/api/admin/output-board');
    const rows = d.board || [];
    if(!rows.length){ box.innerHTML = '<div style="color:var(--ink-3);font-size:13px">暂无产出数据（尚无分配到成员的需求/设计/信号）</div>'; return; }
    const max = Math.max(...rows.map(r=>r.total_output), 1);
    box.innerHTML = rows.map(r=>{
      const pct = Math.round(r.total_output/max*100);
      return `<div style="margin-bottom:14px">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:5px">
          <div style="font-weight:600;font-size:13px">${h(r.username)}</div>
          <div style="font-size:12px;color:var(--ink-3)">产出值 ${r.total_output}</div>
        </div>
        <div style="height:8px;background:var(--line-2);border-radius:5px;overflow:hidden;margin-bottom:6px">
          <div style="height:100%;width:${pct}%;background:linear-gradient(90deg,#22c55e,#16a34a);border-radius:5px"></div>
        </div>
        <div style="display:flex;gap:14px;font-size:11px;color:var(--ink-3)">
          <span>📋 需求 <b style="color:var(--ink)">${r.requirements}</b>（活跃${r.req_active}·上线${r.req_online}）</span>
          <span>📐 设计 <b style="color:var(--ink)">${r.designs}</b></span>
          <span>📥 信号 <b style="color:var(--ink)">${r.signals}</b></span>
        </div>
      </div>`;
    }).join('');
  }catch(e){
    box.innerHTML = `<div style="color:var(--danger);font-size:13px">加载失败：${h(e.message)}</div>`;
  }
};

// ════════════════════════════════════════════════
//  决策中心 · 归并建议 tab（内嵌版智能归并，复用 runSmartMerge 的分析+决策记录逻辑）
// ════════════════════════════════════════════════
window.wbInitDecisionMerge = async function(){
  const btn = $('#dcMergeBtn');
  if(btn && !btn._bound){ btn._bound=1; btn.onclick = ()=>{ if(window.wbOpenMergeDialog) window.wbOpenMergeDialog(); }; }
  // 显示历史学习状态
  try{
    const d = await api('/api/admin/agent-log/stats');
    const hist = $('#dcMergeHist');
    if(hist){
      const mc = d.merge && d.merge.count || 0;
      hist.textContent = mc ? `🧠 已积累 ${mc} 条团队归并决策经验` : '💡 首次使用：执行归并后决策会被记录，AI 将逐步学习团队风格';
    }
  }catch(_){}
};

async function runDecisionMerge(){
  const body = $('#dcMergeBody');
  if(!body) return;
  body.innerHTML = `<div style="text-align:center;padding:30px;color:var(--ink-3)">
    <div style="font-size:24px">⚙️</div><div style="margin-top:10px">归并 Agent 正在分析活跃信号…</div>
    <div style="font-size:11px;margin-top:4px">调用团队模型 + 参考历史决策，约 10-30 秒</div></div>`;
  try{
    const d = await api('/api/admin/merge/analyze');
    const groups = d.groups || [];
    if(!groups.length){
      body.innerHTML = `<div style="text-align:center;padding:24px;color:var(--ink-3)">✓ ${h(d.message||'没有发现可归并的信号')}</div>`;
      const mb=$('#rvMergeBadge'); if(mb) mb.style.display='none';
      return;
    }
    const mb=$('#rvMergeBadge'); if(mb){ mb.textContent=groups.length; mb.style.display=''; }
    body.innerHTML = `<div style="font-size:12px;color:var(--ink-3);margin-bottom:10px">${h(d.message||'')}（模型：${h(d.model||'')}）</div>`
      + groups.map((g,i)=>`
        <div class="dc-group" data-i="${i}" style="border:1px solid var(--brand);border-radius:12px;padding:12px 14px;margin-bottom:10px;background:var(--brand-soft)">
          <div style="font-weight:700;color:var(--brand-strong);margin-bottom:6px">建议 ${i+1}</div>
          <div style="font-size:12px;color:var(--ink-2);margin-bottom:8px">📎 ${g.signals.map(s=>h(s.id+' '+(s.title||''))).join(' ＋ ')}</div>
          <div style="font-size:12px;color:var(--ink-3);margin-bottom:10px">💡 ${h(g.reason||'')}</div>
          <div style="font-size:11px;color:var(--ink-3);margin-bottom:3px">归并后标题（可修改）</div>
          <input class="wbm-in dc-title" value="${h(g.suggested_title||'').replace(/"/g,'&quot;')}" style="width:100%;margin-bottom:8px">
          <div style="font-size:11px;color:var(--ink-3);margin-bottom:3px">归并后信号描述（AI 综合生成，可修改）</div>
          <textarea class="wbm-in dc-body" style="width:100%;min-height:88px;resize:vertical;margin-bottom:8px">${h(g.suggested_body||'')}</textarea>
          <div style="display:flex;gap:8px;align-items:center">
            <span style="font-size:11px;color:var(--ink-3)">紧急度 ${h(g.suggested_urgency||'中')}</span>
            <button class="wbm-btn wbm-primary dc-do" data-i="${i}" style="margin-left:auto">✓ 确认归并</button>
          </div>
        </div>`).join('');
    body.querySelectorAll('.dc-do').forEach(btn2=>btn2.onclick=async()=>{
      const gi = +btn2.dataset.i; const g = groups[gi];
      const grp = body.querySelector(`.dc-group[data-i="${gi}"]`);
      const title = grp.querySelector('.dc-title').value.trim() || g.suggested_title;
      const desc = grp.querySelector('.dc-body').value.trim();
      btn2.disabled=true; btn2.textContent='归并中…';
      try{
        await api('/api/knowledge/merge', {method:'POST', body:JSON.stringify({ids:g.signal_ids, title:title, body:desc, urgency:g.suggested_urgency||''})});
        api('/api/admin/team-agent/record-decision', {method:'POST', body:JSON.stringify({
          kind:'merge', entry:{signal_ids:g.signal_ids, suggested_title:g.suggested_title,
            final_title:title, adopted:title===g.suggested_title, reason:g.reason||''}
        })}).catch(()=>{});
        grp.style.opacity='.5'; grp.innerHTML=`<div style="color:var(--brand-strong);font-weight:600">✓ 已归并为新信号：${h(title)}（决策已记录，AI 将学习）</div>`;
        W.LOADED.board=false; if(window.wbRefreshRailCnt)window.wbRefreshRailCnt();
      }catch(e){ btn2.disabled=false; btn2.textContent='执行归并'; toast('归并失败：'+e.message, true); }
    });
  }catch(e){
    body.innerHTML = `<div style="text-align:center;padding:24px;color:var(--danger)">分析失败：${h(e.message)}</div>`;
  }
}

// R7：需求筛选（状态/优先级/负责人下拉）
async function openReqFilter(){
  const members = await getMemberOptions(false);
  const form = await wbForm('筛选需求', [
    {key:'status', label:'状态', type:'select', value:(window.__reqFilterVal&&window.__reqFilterVal.status)||'', options:[{value:'',label:'全部'},'待校验','已确认','设计中','研发中','已上线','已关闭']},
    {key:'priority', label:'优先级', type:'select', value:'', options:[{value:'',label:'全部'},'P0','P1','P2','P3']},
    {key:'owner', label:'负责人', type:'select', value:'', options:[{value:'',label:'全部'}, ...members]},
  ], {icon:'🔍', okText:'应用'});
  if(!form) return;
  const f = {};
  if(form.status) f.status = form.status;
  if(form.priority) f.priority = form.priority;
  if(form.owner) f.owner = form.owner;
  setReqFilter(f);
}
function setReqFilter(f){
  window.__reqFilterVal = f;
  if(window.__wb) window.__wb._setReqFilter(f);
}

// ════════════════════════════════════════════════
//  设计：新建
// ════════════════════════════════════════════════
async function newDesign(){
  const reqs = await getRequirementOptions();
  const form = await wbForm('新建设计稿', [
    {key:'title', label:'设计稿标题', type:'text', required:true, placeholder:'一句话概括设计'},
    {key:'reqId', label:'关联需求（可留空）', type:'select', value:'', options:[{value:'',label:'（暂不关联）'}, ...reqs]},
  ], {icon:'📐', okText:'创建'});
  if(!form) return;
  try{
    const d = await api('/api/knowledge/new-design', {method:'POST', body:JSON.stringify({title:form.title, requirement_id:form.reqId})});
    toast(`已新建设计稿 ${d.design_id}`);
    W.LOADED.board=false; if(window.wbRefreshRailCnt)window.wbRefreshRailCnt(); W.loadDesigns();
  }catch(e){ toast('新建失败：'+e.message, true); }
}

// ════════════════════════════════════════════════
//  顶部全局搜索
// ════════════════════════════════════════════════
const gs = $('#globalSearch');
if(gs){
  let _t=null;
  gs.addEventListener('keydown', (e)=>{
    if(e.key==='Enter'){ doSearch(gs.value.trim()); }
  });
}
async function doSearch(q){
  if(!q){ return; }
  W.show('board');  // 跳到工作台
  // 并发搜三类
  try{
    const [sig,req,dsn] = await Promise.all([
      api('/api/knowledge/signals?q='+encodeURIComponent(q)),
      api('/api/knowledge/requirements?q='+encodeURIComponent(q)),
      api('/api/knowledge/designs?q='+encodeURIComponent(q)),
    ]);
    const total = (sig.count||0)+(req.count||0)+(dsn.count||0);
    showSearchResult(q, sig.items||[], req.items||[], dsn.items||[], total);
  }catch(e){ toast('搜索失败：'+e.message, true); }
}
function showSearchResult(q, sigs, reqs, dsns, total){
  const rows = (arr, type, icon) => arr.map(x=>
    `<div style="padding:10px 12px;border-bottom:1px solid var(--line-2);cursor:pointer" data-type="${type}" data-id="${h(x.id||x._file)}">
      <div style="font-weight:600;font-size:13px">${icon} ${h(x.title||'(无标题)')}</div>
      <div style="color:var(--ink-3);font-size:11px;margin-top:3px">${h(x.id||'')} · ${h(x._excerpt||'')}</div></div>`).join('');
  const overlay = mkOverlay(`
    <h3 style="margin-bottom:6px">🔍 搜索「${h(q)}」</h3>
    <div style="color:var(--ink-3);font-size:12px;margin-bottom:14px">共 ${total} 条结果</div>
    ${sigs.length?`<div style="font-size:12px;font-weight:700;color:var(--brand-strong);margin:8px 0 4px">📥 信号 (${sigs.length})</div>${rows(sigs,'signals','📥')}`:''}
    ${reqs.length?`<div style="font-size:12px;font-weight:700;color:var(--brand-strong);margin:12px 0 4px">📋 需求 (${reqs.length})</div>${rows(reqs,'requirements','📋')}`:''}
    ${dsns.length?`<div style="font-size:12px;font-weight:700;color:var(--brand-strong);margin:12px 0 4px">📐 设计 (${dsns.length})</div>${rows(dsns,'designs','📐')}`:''}
    ${total===0?'<div style="color:var(--ink-3);text-align:center;padding:30px">无匹配结果</div>':''}`);
}

// ── 通用弹层 ──
function mkOverlay(html){
  const o = document.createElement('div');
  o.style.cssText = 'position:fixed;inset:0;background:rgba(15,31,22,.4);backdrop-filter:blur(6px);z-index:1000;display:flex;align-items:center;justify-content:center;padding:24px';
  o.innerHTML = `<div style="background:var(--glass-strong);backdrop-filter:blur(24px) saturate(180%);border:1px solid rgba(255,255,255,.65);border-radius:18px;max-width:560px;width:100%;max-height:82vh;overflow-y:auto;padding:24px 26px;box-shadow:0 20px 60px rgba(15,33,24,.25)">${html}</div>`;
  o.onclick = (e)=>{ if(e.target===o) o.remove(); };
  document.body.appendChild(o);
  return o;
}

// ════════════════════════════════════════════════
//  我的通知（铃铛）
// ════════════════════════════════════════════════
async function refreshNotifBadge(){
  try{
    const d = await api('/api/me/notifications');
    const badge = $('#notifBadge');
    if(!badge) return;
    if(d.unread > 0){
      badge.textContent = d.unread > 99 ? '99+' : d.unread;
      badge.style.display = 'block';
    } else {
      badge.style.display = 'none';
    }
    // #4：admin 顺带刷新决策中心待审角标（30s 轮询共用，不加新请求循环）；
    // 若当前正停留在决策中心页，同步刷新待审列表（提交后无需手动刷新页面）
    if(window.__wb && window.__wb.IS_ADMIN){
      try{
        const rv = await api('/api/review/list');
        const n = (rv.items||[]).length;
        const rc = document.getElementById('railReviewCnt');
        if(rc){ if(n>0){ rc.textContent=n; rc.style.display=''; } else { rc.style.display='none'; } }
        const reviewVisible = document.getElementById('viewReview') && !document.getElementById('viewReview').classList.contains('hidden');
        if(reviewVisible && window.loadReview){
          const listEl = document.getElementById('reviewList');
          const shown = listEl ? listEl.querySelectorAll('.review-item').length : 0;
          if(n !== shown) window.loadReview();   // 数量变化才重绘，避免打断正在看的详情
        }
      }catch(_){}
    }
  }catch(_){}
}

async function openNotifPanel(){
  let d;
  try{ d = await api('/api/me/notifications'); }
  catch(e){ toast('加载通知失败：'+e.message, true); return; }
  const items = d.notifications || [];
  const rows = items.length ? items.map(n=>`
    <div style="padding:12px 14px;border-radius:11px;background:${n.read?'rgba(255,255,255,.4)':'var(--brand-soft)'};border:1px solid var(--line-2);margin-bottom:9px">
      <div style="font-size:13px;line-height:1.5">${h(n.message||'')}</div>
      <div style="font-size:11px;color:var(--ink-3);margin-top:5px">来自 @${h(n.from||'?')} · ${h(n.at||'')}${n.read?'':' · <span style="color:var(--danger)">未读</span>'}</div>
    </div>`).join('') : '<div style="color:var(--ink-3);text-align:center;padding:30px">还没有通知</div>';
  const overlay = mkOverlay(`
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
      <h3 style="margin:0">🔔 我的通知 ${d.unread?`<span class="tag red" style="font-size:11px">${d.unread} 未读</span>`:''}</h3>
      ${d.unread?'<button class="btn sm" id="markReadBtn">全部已读</button>':''}
    </div>
    ${rows}`);
  const mr = overlay.querySelector('#markReadBtn');
  if(mr) mr.onclick = async ()=>{
    try{
      await api('/api/me/notifications/read', {method:'POST', body:JSON.stringify({})});
      overlay.remove(); refreshNotifBadge(); toast('已全部标为已读');
    }catch(e){ toast('操作失败：'+e.message, true); }
  };
  // 打开面板即视为看过——刷新角标（但不自动标已读，让用户点按钮）
}

// 绑定铃铛 + 启动轮询
const bell = $('#notifBell');
if(bell){
  bell.onclick = openNotifPanel;
  refreshNotifBadge();
  setInterval(refreshNotifBadge, 30000);  // 每30秒刷新未读数
}

// ════════════════════════════════════════════════
//  可追溯链展示（信号↔需求↔设计）
// ════════════════════════════════════════════════
function traceLink(t){
  const icon = t.type==='signals'?'📥':t.type==='requirements'?'📋':t.type==='decisions'?'⚖️':'📐';
  return `<a href="#" class="trace-link" data-ttype="${h(t.type)}" data-tid="${h(t.id)}" style="color:var(--brand-strong);text-decoration:none;margin-right:8px">${icon} ${h(t.id)}${t.title?' · '+h(t.title):''}</a>`;
}
function bindTraceLinks(box){
  box.querySelectorAll('.trace-link').forEach(a=>a.addEventListener('click',(e)=>{
    e.preventDefault(); e.stopPropagation();
    const tt=a.dataset.ttype;
    // 切到对应tab（简单跳转：切tab + toast定位提示）
    const tabMap={signals:'signals',requirements:'requirements',designs:'designs'};
    const btn=document.querySelector(`#viewBoard .tab[data-tab="${tabMap[tt]}"]`);
    if(btn) btn.click();
    toast('已切到'+(tt==='signals'?'信号':tt==='requirements'?'需求':'设计')+'，查找 '+a.dataset.tid);
  }));
}

window.wbLoadTraces = async function(type, id, row){
  // row 传入时（设计卡片 .dsn-trace-row）直接写入其 span；否则回落旧的 #trace-x-x 容器
  const span = row ? row.querySelector('span:last-child')
                   : document.querySelector(`#trace-${type}-${CSS.escape(id)} .sec-b`);
  if(!span) return;
  try{
    const d = await api(`/api/knowledge/traces?type=${type}&id=${encodeURIComponent(id)}`);
    const up = d.upstream||[], down = d.downstream||[];
    if(!up.length && !down.length){ span.innerHTML = '<span style="color:var(--ink-3);font-size:11px">暂无关联</span>'; return; }
    let html = '';
    if(row){
      // 紧凑单行样式（与需求追溯对齐）
      if(up.length) html += '⬆ '+up.map(traceLink).join('');
      if(down.length) html += (up.length?' ':'')+'⬇ '+down.map(traceLink).join('');
    }else{
      if(up.length) html += `<div style="margin-bottom:4px"><span style="color:var(--ink-3);font-size:11px">⬆ 上游：</span>${up.map(traceLink).join('')}</div>`;
      if(down.length) html += `<div><span style="color:var(--ink-3);font-size:11px">⬇ 下游：</span>${down.map(traceLink).join('')}</div>`;
    }
    span.innerHTML = html;
    bindTraceLinks(span);
  }catch(e){ span.innerHTML = '<span style="color:var(--danger);font-size:11px">追溯加载失败</span>'; }
};

window.wbLoadReqTrace = async function(reqId, row){
  const span = row.querySelector('span:last-child');
  if(!span) return;
  try{
    const d = await api(`/api/knowledge/traces?type=requirements&id=${encodeURIComponent(reqId)}`);
    const up = d.upstream||[], down = d.downstream||[];
    if(!up.length && !down.length){ span.innerHTML = '<span style="color:var(--ink-3);font-size:11px">暂无关联</span>'; return; }
    let html = '';
    if(up.length) html += '⬆ '+up.map(traceLink).join('');
    if(down.length) html += (up.length?' ':'')+'⬇ '+down.map(traceLink).join('');
    span.innerHTML = html;
    bindTraceLinks(span);
  }catch(e){ span.innerHTML = '<span style="color:var(--danger);font-size:11px">加载失败</span>'; }
};

// ════════════════════════════════════════════════
// #2：工作台「我的」tab —— 与我相关的信号/需求/设计
// ════════════════════════════════════════════════
let _mineTab = 'signals';   // 「我的」三级 tab 当前选中

window.wbLoadMine = async function(){
  const box = document.getElementById('mineBox');
  if(!box) return;
  // 三级 tab 绑定（幂等）
  document.querySelectorAll('#tab-mine .tab[data-minetab]').forEach(t=>{
    if(t._bound) return; t._bound=1;
    t.addEventListener('click', ()=>{
      document.querySelectorAll('#tab-mine .tab[data-minetab]').forEach(x=>x.classList.remove('active'));
      t.classList.add('active');
      _mineTab = t.dataset.minetab;
      window.wbLoadMine();
    });
  });
  box.innerHTML = '<div style="color:var(--ink-3);padding:12px">加载中…</div>';
  // 「我的」身份匹配：一个人可能被以 username(admin) 或中文名(display_name/马冠杰) 记为 owner——
  // 平台UI分配存 username，agent 提交按画像中文名存 owner，两种都要认，否则「我的」漏项。
  const _u = (window.__wb && window.__wb.USER) || {};
  const mineIds = [_u.username, _u.display_name].filter(Boolean);
  const isMine = (v)=> v!=null && mineIds.includes(String(v).trim());
  const sec = (title, items, cols) => {
    if(!items.length) return '';
    return `<div style="margin-bottom:18px">
      <div style="font-size:13px;font-weight:700;color:var(--brand-strong);margin-bottom:8px">${title}（${items.length}）</div>
      ${items.map(x=>`<div style="display:flex;align-items:center;gap:10px;padding:9px 12px;border:1px solid var(--line-2);border-radius:10px;margin-bottom:6px;background:rgba(255,255,255,.6);font-size:13px">
        <span style="font-weight:600;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${h(x.title||x.id||'')}</span>
        ${cols.map(c=>x[c]?`<span class="tag ${c==='status'?stColor(x[c]):'gray'}" style="flex-shrink:0">${h(c==='status'?stLabel(x[c]):x[c])}</span>`:'').join('')}
      </div>`).join('')}
    </div>`;
  };
  try{
    let html = '';
    if(_mineTab === 'signals'){
      const sig = await api('/api/knowledge/signals');
      html = sec('📥 与我相关的信号', (sig.items||[]).filter(x=>isMine(x.assignee) || isMine(x.submitted_by)), ['status','urgency']);
    }else if(_mineTab === 'requirements'){
      const req = await api('/api/knowledge/requirements');
      html = sec('📋 我负责的需求', (req.items||[]).filter(x=>isMine(x.owner)), ['status','priority']);
    }else if(_mineTab === 'designs'){
      const dsn = await api('/api/knowledge/designs');
      html = sec('📐 我的设计稿', (dsn.items||[]).filter(x=>isMine(x.designer) || isMine(x.reviewer)), ['status']);
    }else if(_mineTab === 'projects'){
      // 我负责的项目 + 我名下的项目需求
      const pj = await api('/api/knowledge/projects');
      const myPrj = (pj.projects||[]).filter(x=>isMine(x.owner));
      html = sec('📦 我负责的项目', myPrj.map(x=>({...x, title:`${x.title}（${x.customer||'—'} · ${x.phase||'—'}）`})), ['status']);
      // 逐项目找我名下的项目需求（数量少，串行可接受）
      let myReqs = [];
      for(const p of (pj.projects||[])){
        try{
          const d = await api('/api/knowledge/project?dir='+encodeURIComponent(p.dir));
          myReqs = myReqs.concat((d.requirements||[]).filter(r=>isMine(r.owner)).map(r=>({...r, title:`[${p.title}] ${r.title||r.id}`})));
        }catch(_){}
      }
      html += sec('📋 我名下的项目需求', myReqs, ['status','priority']);
    }
    const tabName = {signals:'信号',requirements:'需求',designs:'设计',projects:'项目'}[_mineTab];
    box.innerHTML = html || `<div style="color:var(--ink-3);padding:20px;text-align:center;font-size:13px">
      暂无与你（${h(me)}）相关的${tabName}。</div>`;
  }catch(e){
    box.innerHTML = `<div style="color:var(--danger);padding:12px">加载失败：${h(e.message)}</div>`;
  }
};

// ════════════════════════════════════════════════
// 团队成员 tab —— 档案 + 能力画像（随对话自动沉淀）
// ════════════════════════════════════════════════
window.wbLoadTeam = async function(){
  const box = document.getElementById('teamBox');
  if(!box) return;
  box.innerHTML = '<div style="color:var(--ink-3);padding:12px">加载中…</div>';
  try{
    const d = await api('/api/knowledge/team');
    const items = d.items || [];
    if(!items.length){ box.innerHTML = '<div style="color:var(--ink-3);padding:20px;text-align:center">暂无团队成员档案</div>'; return; }
    // 按部门分组
    const depts = {};
    items.forEach(m=>{ const dp=m.department||'其它'; (depts[dp]=depts[dp]||[]).push(m); });
    const order = ['产品','引擎','全栈','效率'];
    const deptKeys = Object.keys(depts).sort((a,b)=>{const ia=order.indexOf(a),ib=order.indexOf(b);return (ia<0?9:ia)-(ib<0?9:ib);});
    box.innerHTML = deptKeys.map(dp=>{
      const members = depts[dp].sort((a,b)=> (a.role==='负责人'?0:1)-(b.role==='负责人'?0:1));
      return `<div style="margin-bottom:18px">
        <div style="font-size:13px;font-weight:700;color:var(--brand-strong);margin-bottom:8px">${h(dp)}（${members.length}人）</div>
        <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:10px">
        ${members.map(m=>`<div class="team-card" data-name="${h(m.name||m.id)}" style="border:1px solid var(--line-2);border-radius:11px;padding:12px 14px;background:rgba(255,255,255,.6);cursor:pointer">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
            <span class="oa" style="width:30px;height:30px;font-size:12px">${h((m.name||'?')[0])}</span>
            <div><b>${h(m.name||m.id)}</b> ${m.role==='负责人'?'<span class="tag green" style="font-size:10px">负责人</span>':''}</div>
          </div>
          <div style="font-size:12px;color:var(--ink-3);line-height:1.6" class="team-portrait" data-name="${h(m.name||m.id)}">点击查看能力画像…</div>
        </div>`).join('')}
        </div></div>`;
    }).join('');
    // 点击卡片展开能力画像（读详情正文）
    box.querySelectorAll('.team-card').forEach(c=>c.addEventListener('click', async ()=>{
      const name = c.dataset.name;
      const pd = c.querySelector('.team-portrait');
      if(pd.dataset.loaded){ return; }
      pd.textContent = '加载中…';
      try{
        const dd = await api('/api/knowledge/item?type=team&id='+encodeURIComponent(name));
        const body = (dd.item && dd.item._body) || '';
        // 提取"能力画像"段
        const m = body.match(/##\s*能力画像\s*\n([\s\S]*?)(?=\n##|\Z)/);
        const portrait = m ? m[1].trim() : '';
        pd.innerHTML = portrait && !portrait.includes('待积累') && !portrait.includes('随对话')
          ? h(portrait) : '<span style="color:var(--ink-3)">能力画像待积累（随对话自动沉淀）</span>';
        pd.dataset.loaded = '1';
      }catch(e){ pd.textContent = '加载失败'; }
    }));
  }catch(e){
    box.innerHTML = `<div style="color:var(--danger);padding:12px">加载失败：${h(e.message)}</div>`;
  }
};

// W2：需求详情内嵌决策背景（决策作为分析背景并入需求）
window.wbLoadReqDecisions = async function(reqId, box){
  try{
    const d = await api(`/api/knowledge/req-decisions?id=${encodeURIComponent(reqId)}`);
    const decs = d.decisions || [];
    if(!decs.length){ box.style.display='none'; return; }
    box.style.display='block';
    box.innerHTML = `<div style="font-size:12px;font-weight:700;color:#a16207;margin-bottom:6px">⚖️ 决策背景（${decs.length}）</div>`
      + decs.map(dec=>{
        // 提取正文关键段（决策内容/最终决策/理由），限长
        const body = (dec.body||'').replace(/^#+\s*/gm,'').trim();
        const excerpt = body.length>260 ? body.slice(0,260)+'…' : body;
        return `<div style="margin-bottom:8px;padding-bottom:8px;border-bottom:1px dashed rgba(180,140,40,.25)">
          <div style="font-weight:600;font-size:12px;color:var(--ink)">${h(dec.title||dec.id)} <span class="tag ${dec.status==='生效中'?'green':'gray'}" style="font-size:10px">${h(dec.status||'')}</span></div>
          <div style="font-size:11px;color:var(--ink-3);margin:2px 0">${h(dec.decision_maker||'')} · ${h(dec.date||'')}</div>
          <div style="font-size:12px;color:var(--ink-2);line-height:1.6;white-space:pre-wrap">${h(excerpt)}</div>
        </div>`;
      }).join('');
  }catch(e){ box.style.display='none'; }
};

// ════════════════════════════════════════════════
// ════════════════════════════════════════════════
//  母版知识库 tab
// ════════════════════════════════════════════════
window.wbLoadLibrary = async function(){
  const box = $('#libraryBox');
  if(!box) return;
  box.innerHTML = '<div style="color:var(--ink-3)">加载中…</div>';
  try{
    const d = await api('/api/knowledge/library');
    const secs = d.sections || [];
    box.innerHTML = secs.map(s=>{
      const icon = s.dir.includes('product-knowledge')?'🌐':'🗄';
      const files = s.files.length ? s.files.map(f=>{
        const kb = f.size<1024?f.size+'B':(f.size/1024).toFixed(1)+'KB';
        return `<div style="display:flex;justify-content:space-between;padding:6px 10px;border-bottom:1px solid var(--line-2);font-size:12px">
          <span style="font-family:monospace">${h(f.path)}</span><span style="color:var(--ink-3)">${kb}</span></div>`;
      }).join('') : '<div style="color:var(--ink-3);font-size:12px;padding:10px">（此区暂无文件）</div>';
      return `<div style="margin-bottom:20px">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
          <span style="font-size:18px">${icon}</span>
          <div><div style="font-weight:700">${h(s.title)} <span class="tag gray" style="font-size:10px">${s.count}个文件</span></div>
          <div style="color:var(--ink-3);font-size:11px">${h(s.desc)} · <span style="font-family:monospace">${h(s.dir)}/</span></div></div>
        </div>
        <div style="border:1px solid var(--line);border-radius:10px;overflow:hidden;max-height:280px;overflow-y:auto">${files}</div>
      </div>`;
    }).join('');
  }catch(e){ box.innerHTML = `<div style="color:var(--danger)">加载失败：${h(e.message)}</div>`; }
};

// ════════════════════════════════════════════════
//  主 Agent 定时任务（admin）
// ════════════════════════════════════════════════
const CRON_HINT = {
  '0 9 * * *':'每天 09:00', '0 10 * * *':'每天 10:00',
  '0 18 * * 5':'每周五 18:00', '0 3 * * 0':'每周日 03:00',
};
function cronHuman(expr){ return CRON_HINT[expr] || expr; }

window.wbLoadTasks = async function(){
  const box = $('#taskList');
  if(!box) return;
  box.innerHTML = '<div style="color:var(--ink-3)">加载中…</div>';
  let d;
  try{ d = await api('/api/admin/tasks'); }
  catch(e){
    if(e.status===403){ box.innerHTML='<div style="color:var(--ink-3)">需要管理员权限</div>'; return; }
    box.innerHTML = `<div style="color:var(--danger)">加载失败：${h(e.message)}</div>`; return;
  }
  const ss = $('#schedStatus');
  if(ss) ss.textContent = d.scheduler_enabled ? '调度器运行中 · 默认关闭，按需开启' : '⚠ 调度器未启用（WDP_SCHEDULER_ENABLED=0）';
  const tasks = d.tasks || [];
  box.innerHTML = tasks.map(t=>{
    const st = t.last_status;
    const stTag = st==='ok'?tag('上次成功','green'):st==='error'?tag('上次失败','red'):st==='pending_agent'?tag('待Agent','amber'):(t.last_run?tag(st||'—','gray'):'');
    const paramStr = t.type==='builtin' && Object.keys(t.params||{}).length
      ? Object.entries(t.params).map(([k,v])=>`${k}=${v}`).join(', ') : '';
    return `<div class="task-card" style="border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-bottom:10px;background:${t.enabled?'var(--brand-soft)':'rgba(255,255,255,.5)'}">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
        <button class="toggle ${t.enabled?'on':''}" data-tk-act="toggle" data-id="${h(t.id)}" data-enabled="${t.enabled?1:0}" title="开关"></button>
        <b style="font-size:14px">${h(t.name)}</b>
        ${t.type==='custom'?tag('自定义','purple'):tag('内置','blue')}
        ${stTag}
        <span style="margin-left:auto;font-size:12px;color:var(--ink-3)">🕐 ${h(cronHuman(t.schedule))}</span>
      </div>
      <div style="font-size:12px;color:var(--ink-2);margin-bottom:8px">${h(t.desc||'')}${paramStr?` · <span style="color:var(--ink-3)">${h(paramStr)}</span>`:''}</div>
      ${t.type==='custom'&&t.prompt?`<div style="font-size:12px;color:var(--ink-3);background:rgba(0,0,0,.03);padding:8px 10px;border-radius:8px;margin-bottom:8px;white-space:pre-wrap">${h(t.prompt.slice(0,200))}</div>`:''}
      ${t.last_run?`<div style="font-size:11px;color:var(--ink-3);margin-bottom:8px">上次运行：${h(t.last_run)}（${h(t.last_trigger||'?')}）${t.last_result?` · <a href="#" data-tk-act="result" data-id="${h(t.id)}" style="color:var(--brand-strong)">查看结果</a>`:''}</div>`:''}
      <div style="display:flex;gap:6px;flex-wrap:wrap">
        <button class="btn sm" data-tk-act="run" data-id="${h(t.id)}">▶ 立即运行</button>
        <button class="btn sm" data-tk-act="schedule" data-id="${h(t.id)}" data-sch="${h(t.schedule)}">改周期</button>
        ${t.type==='builtin'&&Object.keys(t.params||{}).length?`<button class="btn sm" data-tk-act="params" data-id="${h(t.id)}">改参数</button>`:''}
        ${t.type==='custom'?`<button class="btn sm" data-tk-act="editPrompt" data-id="${h(t.id)}">改内容</button><button class="btn sm ghost" data-tk-act="delete" data-id="${h(t.id)}">删除</button>`:''}
      </div>
    </div>`;
  }).join('') || '<div style="color:var(--ink-3)">暂无任务</div>';
  // 事件
  box.querySelectorAll('[data-tk-act]').forEach(b=>b.addEventListener('click',(e)=>{
    e.preventDefault();
    taskAction(b.dataset.tkAct, b.dataset, tasks);
  }));
  const nb = $('#newTaskBtn');
  if(nb) nb.onclick = newCustomTask;
};

async function taskAction(act, ds, tasks){
  const id = ds.id;
  if(act==='toggle'){
    const enabled = ds.enabled!=='1';
    try{
      await api('/api/admin/tasks/update', {method:'POST', body:JSON.stringify({id, updates:{enabled}})});
      toast(enabled?'已开启':'已关闭'); window.wbLoadTasks();
    }catch(e){ toast('操作失败：'+e.message, true); }
  } else if(act==='run'){
    toast('执行中…');
    try{
      const d = await api('/api/admin/tasks/run', {method:'POST', body:JSON.stringify({id})});
      await wbAlert('▶ 运行完成（'+(d.status||'')+'）\n\n'+(d.result||'').slice(0,1000));
      window.wbLoadTasks();
    }catch(e){ toast('运行失败：'+e.message, true); }
  } else if(act==='schedule'){
    const sch = await wbPrompt('cron 表达式（5段：分 时 日 月 周）\n例：0 9 * * * = 每天9点；0 18 * * 5 = 每周五18点', {value: ds.sch||''});
    if(!sch) return;
    try{
      await api('/api/admin/tasks/update', {method:'POST', body:JSON.stringify({id, updates:{schedule:sch}})});
      toast('周期已更新'); window.wbLoadTasks();
    }catch(e){ toast('失败：'+e.message, true); }
  } else if(act==='params'){
    const t = tasks.find(x=>x.id===id);
    const cur = t.params||{};
    const key = Object.keys(cur)[0];
    const v = await wbPrompt(`修改参数 ${key}（当前 ${cur[key]}）：`, {value: cur[key]});
    if(v===null) return;
    const np = {...cur}; np[key] = isNaN(+v)?v:+v;
    try{
      await api('/api/admin/tasks/update', {method:'POST', body:JSON.stringify({id, updates:{params:np}})});
      toast('参数已更新'); window.wbLoadTasks();
    }catch(e){ toast('失败：'+e.message, true); }
  } else if(act==='editPrompt'){
    const t = tasks.find(x=>x.id===id);
    const p = await wbPrompt('任务内容（自然语言，交给主 Agent 执行）：', {value: t.prompt||''});
    if(p===null) return;
    try{
      await api('/api/admin/tasks/update', {method:'POST', body:JSON.stringify({id, updates:{prompt:p}})});
      toast('内容已更新'); window.wbLoadTasks();
    }catch(e){ toast('失败：'+e.message, true); }
  } else if(act==='delete'){
    if(!(await wbConfirm('删除该自定义任务？'))) return;
    try{
      await api('/api/admin/tasks/delete', {method:'POST', body:JSON.stringify({id})});
      toast('已删除'); window.wbLoadTasks();
    }catch(e){ toast('失败：'+e.message, true); }
  } else if(act==='result'){
    const t = tasks.find(x=>x.id===id);
    await wbAlert('📄 上次运行结果（'+(t.last_run||'')+'）\n\n'+(t.last_result||'（无）'));
  }
}

async function newCustomTask(){
  const name = await wbPrompt('任务名称：');
  if(!name) return;
  const schedule = await wbPrompt('执行周期 cron（5段）\n例：0 9 * * * = 每天9点', {value: '0 9 * * *'});
  if(!schedule) return;
  const promptText = await wbPrompt('任务内容（自然语言，描述要主 Agent 做什么）：');
  if(!promptText) return;
  try{
    await api('/api/admin/tasks/create', {method:'POST', body:JSON.stringify({name, schedule, prompt:promptText})});
    toast('已创建自定义任务（默认关闭）'); window.wbLoadTasks();
  }catch(e){ toast('创建失败：'+e.message, true); }
}

// ════════════════════════════════════════════════
// 📦 项目 tab —— 项目列表 + 三级（需求/交付材料/档案）
// ════════════════════════════════════════════════
let _prjCur = null;      // 当前打开的项目 dir
let _prjTab = 'reqs';    // 三级 tab

window.wbLoadProjects = async function(){
  const listV = document.getElementById('prjListView');
  const detV = document.getElementById('prjDetailView');
  if(!listV) return;
  // 回列表视图
  listV.classList.remove('hidden'); if(detV) detV.classList.add('hidden');
  _prjCur = null;
  const rows = document.getElementById('projectRows');
  if(rows) rows.innerHTML = '<tr><td colspan="7" style="color:var(--ink-3)">加载中…</td></tr>';
  let d;
  try{ d = await api('/api/knowledge/projects'); }
  catch(e){ if(rows) rows.innerHTML = `<tr><td colspan="7" style="color:var(--danger)">加载失败：${h(e.message)}</td></tr>`; return; }
  const pjs = d.projects || [];
  // 二级 tab 徽标
  const badge = document.querySelector('#viewBoard .tab[data-tab="projects"] .badge');
  if(badge) badge.textContent = pjs.length;
  if(rows){
    rows.innerHTML = pjs.length ? pjs.map(p=>`
      <tr class="exp-row prj-row" data-dir="${h(p.dir)}" style="cursor:pointer">
        <td style="text-align:left;font-weight:600">${h(p.title)}</td>
        <td>${h(p.customer||'—')}</td>
        <td><span class="tag gray">${h(p.phase||'—')}</span></td>
        <td>${h(p.owner||'—')}</td>
        <td><span class="tag ${p.status==='进行中'?'green':'gray'}">${h(p.status||'—')}</span></td>
        <td>${p.req_count}</td><td>${p.dlv_count}</td>
      </tr>`).join('')
      : '<tr><td colspan="7" style="color:var(--ink-3);padding:20px">还没有项目。成员可「📨 申请开档」提交审核，管理员可「＋ 直接开档」。</td></tr>';
    rows.querySelectorAll('.prj-row').forEach(r=>r.addEventListener('click', ()=>wbOpenProject(r.dataset.dir)));
  }
  // 按钮绑定（幂等）
  const applyBtn = document.getElementById('prjApplyBtn');
  if(applyBtn && !applyBtn._b){ applyBtn._b=1; applyBtn.onclick = prjApply; }
  const createBtn = document.getElementById('prjCreateBtn');
  if(createBtn && !createBtn._b){ createBtn._b=1; createBtn.onclick = prjCreate; }
  const backBtn = document.getElementById('prjBackBtn');
  if(backBtn && !backBtn._b){ backBtn._b=1; backBtn.onclick = ()=>window.wbLoadProjects(); }
  // 三级 tab 绑定（幂等）
  document.querySelectorAll('#prjDetailView .tab[data-prjtab]').forEach(t=>{
    if(t._b) return; t._b=1;
    t.addEventListener('click', ()=>{
      document.querySelectorAll('#prjDetailView .tab[data-prjtab]').forEach(x=>x.classList.remove('active'));
      t.classList.add('active');
      _prjTab = t.dataset.prjtab;
      ['reqs','dlvs','file'].forEach(k=>{
        const el = document.getElementById('prjtab-'+k);
        if(el) el.classList.toggle('hidden', k!==_prjTab);
      });
    });
  });
};

async function wbOpenProject(pdir){
  _prjCur = pdir;
  const listV = document.getElementById('prjListView');
  const detV = document.getElementById('prjDetailView');
  listV.classList.add('hidden'); detV.classList.remove('hidden');
  let d;
  try{ d = await api('/api/knowledge/project?dir='+encodeURIComponent(pdir)); }
  catch(e){ toast('项目加载失败：'+e.message, true); return; }
  const m = d.meta || {};
  document.getElementById('prjDetailTitle').textContent = '📦 ' + (m.title || pdir);
  document.getElementById('prjDetailMeta').textContent = `${m.customer||'—'} · ${m.phase||'—'} · 负责人 ${m.owner||'—'} · ${m.status||''}`;
  // ✏️ 编辑项目信息（逐步补充/修改档案字段，带乐观锁防并发覆盖）
  const _editBtn = document.getElementById('prjEditBtn');
  if(_editBtn){
    _editBtn.style.display = (window.__wb && window.__wb.IS_ADMIN) ? '' : 'none';
    _editBtn.onclick = async ()=>{
      const base = {customer:m.customer||'', phase:m.phase||'售前', owner:m.owner||'', status:m.status||'',
                    opportunity:m.opportunity||'', bd_owner:m.bd_owner||'', tb_contact:m.tb_contact||'', description:m.description||''};
      const form = await wbForm('编辑项目信息 · '+(m.title||pdir), [
        {key:'customer', label:'客户', type:'text', value:base.customer},
        {key:'phase', label:'阶段', type:'select', value:base.phase, options:['售前','交付中','售后']},
        {key:'status', label:'状态', type:'text', value:base.status},
        {key:'owner', label:'负责人', type:'text', value:base.owner},
        {key:'opportunity', label:'商机号', type:'text', value:base.opportunity},
        {key:'bd_owner', label:'BD 负责人', type:'text', value:base.bd_owner},
        {key:'tb_contact', label:'客户 TB 对接人', type:'text', value:base.tb_contact},
        {key:'description', label:'项目概述', type:'textarea', value:base.description},
      ], {icon:'✏️', okText:'保存', width:520});
      if(!form) return;
      // 只提交改动的字段，每个带 expect（乐观锁）
      let okN=0, conflicts=[];
      for(const k of Object.keys(base)){
        if((form[k]||'') === base[k]) continue;   // 未改
        try{
          await api('/api/knowledge/project-update', {method:'POST', body:JSON.stringify({
            project:pdir, field:k, value:form[k]||'', expect:base[k]})});
          okN++;
        }catch(e){
          if(e.data && e.data.error && e.data.error.indexOf('冲突')>=0){
            conflicts.push(`${k}（已被改为「${e.data.current}」）`);
          }else{ toast(`${k} 保存失败：${e.message}`, true); }
        }
      }
      if(conflicts.length){
        const ok = await wbConfirm(`以下字段期间被他人/agent 更新，你的修改基于旧值：\n${conflicts.join('\n')}\n\n是否用你的值强制覆盖？`);
        if(ok){
          for(const c of conflicts){
            const k = c.split('（')[0];
            try{ await api('/api/knowledge/project-update', {method:'POST', body:JSON.stringify({project:pdir, field:k, value:form[k]||''})}); okN++; }catch(_){}
          }
        }
      }
      if(okN) toast(`已更新 ${okN} 项`);
      wbOpenProject(pdir);   // 重载详情
    };
  }
  // 需求表
  const reqs = d.requirements || [];
  document.getElementById('prjReqBadge').textContent = reqs.length;
  document.getElementById('prjReqRows').innerHTML = reqs.length ? reqs.map(r=>`
    <tr><td>${h(r.id||'')}</td><td style="text-align:left">${h(r.title||'')}</td>
    <td><span class="tag gray">${h(r.priority||'—')}</span></td>
    <td><span class="tag ${r.status==='已交付'?'green':'gray'}">${h(r.status||'—')}</span></td>
    <td>${h(r.owner||'—')}</td><td style="font-size:11px">${h((r.source_signals||[]).join(', ')||'—')}</td></tr>`).join('')
    : '<tr><td colspan="6" style="color:var(--ink-3);padding:16px">暂无项目需求。到「信号」页选中信号 →「沉淀为项目需求」，或点上方按钮。</td></tr>';
  // 材料表
  const dlvs = d.deliverables || [];
  document.getElementById('prjDlvBadge').textContent = dlvs.length;
  document.getElementById('prjDlvRows').innerHTML = dlvs.length ? dlvs.map(v=>`
    <tr><td>${h(v.id||'')}</td><td style="text-align:left">${h(v.title||'')}</td>
    <td style="font-size:11px">${h(v.requirement_id||'—')}</td>
    <td><span class="tag gray">${h(v.phase||'—')}</span></td>
    <td><span class="tag ${v.status==='已交付'?'green':'gray'}">${h(v.status||'—')}</span></td>
    <td>${h(v.date||'—')}</td></tr>`).join('')
    : '<tr><td colspan="6" style="color:var(--ink-3);padding:16px">暂无交付材料。先有项目需求，再「＋ 新建材料」绑定。</td></tr>';
  // 档案正文
  document.getElementById('prjFileBody').textContent = (d.body||'').trim() || '（档案正文为空）';
  // 详情页按钮
  const s2r = document.getElementById('prjSigToReqBtn');
  if(s2r){ s2r.onclick = ()=>prjSigToReq(pdir); }
  const newDlv = document.getElementById('prjNewDlvBtn');
  if(newDlv){ newDlv.onclick = ()=>prjNewDlv(pdir, reqs); }
}

// 成员：申请开档（走决策中心审核流）
async function prjApply(){
  const f = await wbForm('申请项目开档（提交后由管理员审核）', [
    {key:'title', label:'项目名称', type:'text', required:true, placeholder:'如 XX市政数字孪生项目'},
    {key:'customer', label:'客户名称', type:'text', required:true},
    {key:'phase', label:'阶段', type:'select', options:['售前','交付中','售后']},
    {key:'description', label:'一句话描述（做什么）', type:'textarea', required:true},
  ]);
  if(!f) return;
  const today = new Date().toISOString().slice(0,10);
  const content = `---\nid: PRJ-申请待编号\ntype: project\ndate: ${today}\ntitle: ${f.title}\ndescription: ${f.description}\ncustomer: ${f.customer}\nphase: ${f.phase||'售前'}\nowner: ${(window.__wb&&window.__wb.USER&&window.__wb.USER.username)||''}\nstatus: 进行中\n---\n\n# ${f.title}\n\n## 项目背景\n\n${f.description}\n`;
  try{
    await api('/api/review/submit', {method:'POST', body:JSON.stringify({
      title: '项目开档申请：'+f.title, category: 'projects', content })});
    toast('开档申请已提交，等待管理员在决策中心审核');
  }catch(e){ toast('提交失败：'+(e.message||''), true); }
}

// 管理员：直接开档
async function prjCreate(){
  const f = await wbForm('直接开档（管理员）', [
    {key:'title', label:'项目名称', type:'text', required:true},
    {key:'customer', label:'客户名称', type:'text', required:true},
    {key:'phase', label:'阶段', type:'select', options:['售前','交付中','售后']},
    {key:'owner', label:'负责人（用户名）', type:'text'},
    {key:'description', label:'一句话描述', type:'textarea'},
  ]);
  if(!f) return;
  try{
    const r = await wbCreateProjectSafe(f);
    if(!r) return;
    toast(r.message||'已开档');
    window.wbLoadProjects();
  }catch(e){ toast('开档失败：'+e.message, true); }
}

// 带客户级去重确认的开档：命中同客户已有项目时先问，确认另开才 force
window.wbCreateProjectSafe = async function(body){
  try{
    return await api('/api/knowledge/project-create', {method:'POST', body:JSON.stringify(body)});
  }catch(e){
    if(e.status===409 && e.data && e.data.code==='CUSTOMER_HAS_PROJECT'){
      const list = (e.data.existing||[]).map(p=>`· ${p.title}（${p.phase||'—'}）`).join('\n');
      const ok = await wbConfirm(`客户「${e.data.customer}」已有项目：\n${list}\n\n确定要为该客户【另开一个新项目】吗？\n（如果需求属于已有项目，请点取消，改把需求归到已有项目）`);
      if(!ok) return null;
      return await api('/api/knowledge/project-create', {method:'POST', body:JSON.stringify({...body, force:true})});
    }
    throw e;
  }
};

// 从公共信号池沉淀为本项目的项目需求
async function prjSigToReq(pdir){
  let sig;
  try{ sig = await api('/api/knowledge/signals'); }catch(e){ toast('拉信号失败', true); return; }
  const cands = (sig.items||[]).filter(s=>!['已转需求','已合并','已归档'].includes(s.status||''));
  if(!cands.length){ toast('信号池没有可沉淀的活跃信号', true); return; }
  const f = await wbForm('从信号池沉淀为项目需求', [
    {key:'signal_id', label:'选择信号', type:'select', options:cands.map(s=>s.id+' · '+(s.title||'').slice(0,30))},
    {key:'owner', label:'负责人（可空=待分配）', type:'text'},
  ]);
  if(!f) return;
  const sid = (f.signal_id||'').split(' · ')[0];
  try{
    const r = await api('/api/knowledge/to-project-req', {method:'POST', body:JSON.stringify({
      signal_id: sid, project: pdir, owner: f.owner||'' })});
    toast(r.message||'已沉淀');
    wbOpenProject(pdir);
    if(window.wbRefreshRailCnt) window.wbRefreshRailCnt();
  }catch(e){ toast('沉淀失败：'+e.message, true); }
}

// 新建交付材料（必绑项目需求）
async function prjNewDlv(pdir, reqs){
  if(!reqs || !reqs.length){ toast('该项目还没有项目需求，先沉淀需求再建材料', true); return; }
  const f = await wbForm('新建交付材料（必须绑定项目需求）', [
    {key:'title', label:'材料标题', type:'text', required:true, placeholder:'如 技术方案书 / 验收报告'},
    {key:'requirement_id', label:'绑定项目需求', type:'select', options:reqs.map(r=>r.id+' · '+(r.title||'').slice(0,26))},
    {key:'phase', label:'阶段', type:'select', options:['售前','售中','售后']},
    {key:'description', label:'一句话描述', type:'textarea'},
  ]);
  if(!f) return;
  try{
    const r = await api('/api/knowledge/deliverable-create', {method:'POST', body:JSON.stringify({
      project: pdir, title: f.title, requirement_id: (f.requirement_id||'').split(' · ')[0],
      phase: f.phase||'售前', description: f.description||'' })});
    toast(r.message||'已创建');
    wbOpenProject(pdir);
  }catch(e){ toast('创建失败：'+e.message, true); }
}

})();
