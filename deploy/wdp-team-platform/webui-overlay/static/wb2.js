/* ============================================================
   WDP 团队工作台 · 前端逻辑第二部分（wb2.js）
   审核 / 成员 / 个人中心 / 对话
   依赖 wb.js 暴露的 window.__wb
   ============================================================ */
(function(){
'use strict';
const W = window.__wb;
if(!W){ console.error('wb.js 未加载'); return; }
const {api, h, tag, toast} = W;
const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);

// ══════════════════════════════════════════════
//  入库审核（admin，接 /api/review/*）
// ══════════════════════════════════════════════
let _rvItems = [], _rvSel = null;

window.loadReview = async function(){
  // 决策中心 tab 切换（首次绑定）
  const tabs = document.querySelectorAll('[data-rvtab]');
  tabs.forEach(t=>{
    if(t._bound) return; t._bound=1;
    t.addEventListener('click', ()=>{
      tabs.forEach(x=>x.classList.remove('active'));
      t.classList.add('active');
      ['inbox','merge'].forEach(k=>{ const el=document.getElementById('rvtab-'+k); if(el) el.classList.toggle('hidden', k!==t.dataset.rvtab); });
      if(t.dataset.rvtab==='merge' && window.wbInitDecisionMerge) window.wbInitDecisionMerge();
    });
  });
  const list = $('#reviewList');
  if(!list) return;
  list.innerHTML = '<div style="color:var(--ink-3);padding:16px">加载中…</div>';
  try{
    const d = await api('/api/review/list');
    _rvItems = d.items || [];
    // R5：同步审核 rail 数字 + 决策中心tab徽标
    const rc = document.getElementById('railReviewCnt');
    if(rc){ if(_rvItems.length){ rc.textContent=_rvItems.length; rc.style.display=''; } else { rc.style.display='none'; } }
    const ib = document.getElementById('rvInboxBadge');
    if(ib) ib.textContent = _rvItems.length;
    if(!_rvItems.length){
      list.innerHTML = '<div style="color:var(--ink-3);padding:24px;text-align:center">暂无待审申请</div>';
      $('#reviewSuggest').innerHTML = '<div style="color:var(--ink-3)">没有待审内容</div>';
      $('#reviewChat').innerHTML = '';
      return;
    }
    list.innerHTML = _rvItems.map((r,i)=>`
      <div class="review-item ${i===0?'sel':''}" data-i="${i}">
        <div class="rt">${h(r.title||'(无标题)')}</div>
        <div class="rm">${tag(r.category||'—','green')}<span>${h(r.username)} · ${h(r.submitted_at||'')}</span></div>
      </div>`).join('');
    list.querySelectorAll('.review-item').forEach(el => el.addEventListener('click', ()=>{
      list.querySelectorAll('.review-item').forEach(x=>x.classList.remove('sel'));
      el.classList.add('sel');
      renderReviewDetail(+el.dataset.i);
    }));
    renderReviewDetail(0);
  }catch(e){
    if(e.status === 403){ list.innerHTML = '<div style="color:var(--ink-3);padding:24px">需要管理员权限</div>'; return; }
    list.innerHTML = `<div style="color:var(--danger);padding:16px">加载失败：${h(e.message)}</div>`;
  }
};

async function renderReviewDetail(i){
  _rvSel = _rvItems[i];
  if(!_rvSel) return;
  const sug = _rvSel.suggestion || {};
  $('#reviewSuggest').innerHTML =
    `<b>提交人：</b>${h(_rvSel.username)}　<b>提交时间：</b>${h(_rvSel.submitted_at||'')}<br>`+
    `<b>申报类目：</b>${h(sug.target_category||_rvSel.category||'')}/<br>`+
    `<b>文件：</b><code style="background:var(--brand-soft);padding:2px 6px;border-radius:4px">${h(sug.suggested_name||_rvSel.file||'')}</code>`+
    `<div id="aiAssistBox" style="margin-top:10px"><button class="btn sm primary" id="aiAssistBtn">🧐 与 Agent 协作审核</button>`+
    `<span style="font-size:11px;color:var(--ink-3);margin-left:8px">对话式协作：agent 分析归类/查重/质量，可多轮讨论后执行</span></div>`;
  // R41：对话式审核协作（替代一次性AI分析）
  const ab = $('#aiAssistBtn');
  if(ab) ab.onclick = ()=>{
    if(window.wbOpenReviewDialog) window.wbOpenReviewDialog(_rvSel);
  };
  // 载入产出全文
  const chat = $('#reviewChat');
  chat.innerHTML = '<div class="msg ai">加载产出全文…</div>';
  try{
    const d = await api('/api/review/item?user='+encodeURIComponent(_rvSel._profile)+'&file='+encodeURIComponent(_rvSel.file));
    chat.innerHTML = `<div class="msg ai" style="max-width:100%;white-space:pre-wrap;font-family:ui-monospace,monospace;font-size:12px">${h(d.content||'(空)')}</div>`;
  }catch(e){
    chat.innerHTML = `<div class="msg ai">加载失败：${h(e.message)}</div>`;
  }
}

// 绑定通过/驳回按钮（在原型的 review-detail 底部）
function bindReviewActions(){
  const detail = $('#viewReview .review-detail');
  if(!detail) return;
  const btns = detail.querySelectorAll('div[style*="margin-top:16px"] button, .review-detail > div:last-child button');
  // 更稳妥：按文字匹配
  detail.querySelectorAll('button').forEach(b=>{
    const t = b.textContent.trim();
    if(t.includes('通过入库')) b.onclick = doApprove;
    else if(t.includes('驳回')) b.onclick = doReject;
  });
}

async function doApprove(){
  if(!_rvSel){ toast('请先选择待审项', true); return; }
  const sug = _rvSel.suggestion || {};
  const finalName = await wbPrompt('最终文件名（.md 结尾）：', {value: sug.suggested_name || _rvSel.file});
  if(!finalName) return;
  const note = await wbPrompt('审核备注（可选）：') || '';
  try{
    const d = await api('/api/review/approve', {method:'POST', body:JSON.stringify({
      user:_rvSel._profile, file:_rvSel.file, final_name:finalName, note
    })});
    toast('已入库到 '+(d.final_path||''));
    // 简化session：记录审核决策(AI建议 vs 管理员通过)，供审核助手few-shot学习
    const adv = window.__wbReviewAdvice || {};
    api('/api/admin/team-agent/record-decision', {method:'POST', body:JSON.stringify({
      kind:'review', entry:{title:_rvSel.title, category:_rvSel.category, decision:'通过',
        ai_advice:(adv.recommendation||'')+(adv.reason?('·'+adv.reason):''), reason:note||''}
    })}).catch(()=>{});
    window.__wbReviewAdvice = null;
    W.LOADED.board = false; if(window.wbRefreshRailCnt)window.wbRefreshRailCnt();  // 工作台需刷新
    window.loadReview();
  }catch(e){
    // 模板校验失败（422）用 alert 醒目提示，其它错误用 toast
    if(e.status === 422 || (e.data && e.data.missing)){
      await wbAlert('⚠ 入库校验未通过\n\n'+(e.message||'')+'\n\n请让提交人在对话中补全 frontmatter 字段后重新提交。');
    } else {
      toast('入库失败：'+e.message, true);
    }
  }
}

async function doReject(){
  if(!_rvSel){ toast('请先选择待审项', true); return; }
  const reason = await wbPrompt('驳回理由（必填，会发给提交人）：');
  if(!reason) return;
  try{
    await api('/api/review/reject', {method:'POST', body:JSON.stringify({
      user:_rvSel._profile, file:_rvSel.file, reason
    })});
    toast('已驳回');
    // 简化session：记录驳回决策
    const adv = window.__wbReviewAdvice || {};
    api('/api/admin/team-agent/record-decision', {method:'POST', body:JSON.stringify({
      kind:'review', entry:{title:_rvSel.title, category:_rvSel.category, decision:'驳回',
        ai_advice:(adv.recommendation||'')+(adv.reason?('·'+adv.reason):''), reason}
    })}).catch(()=>{});
    window.__wbReviewAdvice = null;
    window.loadReview();
  }catch(e){ toast('驳回失败：'+e.message, true); }
}

// review 首次进入时绑定按钮
const _origLoadReview = window.loadReview;
window.loadReview = async function(){ await _origLoadReview(); bindReviewActions(); };

// ══════════════════════════════════════════════
//  成员管理（admin，接 /api/admin/users*）
// ══════════════════════════════════════════════
window.loadMembers = async function(){
  const tb = $('#memberRows');
  if(!tb) return;
  tb.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--ink-3);padding:24px">加载中…</td></tr>';
  try{
    const d = await api('/api/admin/users?stats=1');
    const users = d.users || [];
    tb.innerHTML = users.map(m=>{
      const me = W.USER && m.username===W.USER.username;
      const st = m.stats || {};
      const usage = `${st.sessions||0} 会话`;
      const contrib = `${st.contributions||0} 次入库`;
      const resp = (m.responsibilities||'').trim();
      const respCell = resp
        ? `<span title="${h(resp)}" style="display:inline-block;max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;vertical-align:middle;color:var(--ink-2)">${h(resp)}</span>`
        : `<span style="color:var(--ink-3)">未定义</span>`;
      return `<tr style="cursor:default">
        <td><div style="display:flex;align-items:center;gap:9px"><span class="oa" style="width:26px;height:26px;font-size:10px">${h((m.username||'?')[0])}</span><b>${h(m.username)}</b>${me?tag('你','green'):''}</div></td>
        <td style="color:var(--ink-3);font-family:monospace;font-size:12px">${h(m.profile)}</td>
        <td>${tag(m.role==='admin'?'管理员':'成员', m.role==='admin'?'purple':'gray')}</td>
        <td>${respCell} <button class="btn sm ghost" data-act="resp" data-u="${h(m.username)}" data-resp="${h(resp)}" title="编辑职责">✏️</button></td>
        <td style="color:var(--ink-2)">${usage}</td>
        <td style="color:var(--ink-2)">${contrib}</td>
        <td>${m.active?tag('正常','green'):tag('已停用','red')}</td>
        <td>${me?'<span style="color:var(--ink-3)">—</span>':
          `<button class="btn sm ghost" data-act="reset" data-u="${h(m.username)}">重置密码</button>`+
          `<button class="btn sm ghost" data-act="toggle" data-u="${h(m.username)}" data-active="${m.active?1:0}">${m.active?'停用':'启用'}</button>`+
          `<button class="btn sm ghost" data-act="kick" data-u="${h(m.username)}">踢下线</button>`}</td></tr>`;
    }).join('');
    tb.querySelectorAll('[data-act]').forEach(b => b.addEventListener('click', ()=>memberAction(b.dataset.act, b.dataset.u, b.dataset)));
    // 添加成员按钮
    const addBtn = $('#viewMembers .panel-head .btn.primary');
    if(addBtn) addBtn.onclick = addMember;
    // R12 产出看板
    if(window.wbLoadOutputBoard) window.wbLoadOutputBoard();
  }catch(e){
    if(e.status===403){ tb.innerHTML='<tr><td colspan="8" style="text-align:center;color:var(--ink-3);padding:24px">需要管理员权限</td></tr>'; return; }
    tb.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--danger);padding:24px">加载失败：${h(e.message)}</td></tr>`;
  }
};

async function addMember(){
  const username = await wbPrompt('新成员用户名（小写字母/数字/连字符）：');
  if(!username) return;
  const password = await wbPrompt('初始密码（至少 6 位）：');
  if(!password) return;
  const role = (await wbConfirm('设为管理员？（确定=管理员，取消=普通成员）')) ? 'admin' : 'member';
  try{
    await api('/api/admin/users/create', {method:'POST', body:JSON.stringify({username, password, role})});
    toast('已添加成员 '+username);
    window.loadMembers();
  }catch(e){ toast('添加失败：'+e.message, true); }
}

async function memberAction(act, username, ds){
  try{
    if(act==='reset'){
      const np = await wbPrompt('为 '+username+' 设置新密码（至少 6 位）：');
      if(!np) return;
      await api('/api/admin/users/reset_password', {method:'POST', body:JSON.stringify({username, new_password:np})});
      toast('已重置 '+username+' 的密码');
    }else if(act==='toggle'){
      const willActive = ds.active !== '1';
      if(!(await wbConfirm((willActive?'启用':'停用')+'成员 '+username+'？'))) return;
      await api('/api/admin/users/set_active', {method:'POST', body:JSON.stringify({username, active:willActive})});
      toast('已'+(willActive?'启用':'停用')+' '+username);
      window.loadMembers();
    }else if(act==='kick'){
      if(!(await wbConfirm('强制 '+username+' 下线？'))) return;
      await api('/api/admin/users/kick', {method:'POST', body:JSON.stringify({username})});
      toast('已踢下线 '+username);
    }else if(act==='resp'){
      const cur = ds.resp || '';
      const txt = await wbPrompt(`「${username}」的职责定义\n（负责的产品方向/模块，主 Agent 据此给出分配建议）：`, {value:cur, multiline:true});
      if(txt===null) return;
      await api('/api/admin/users/responsibilities', {method:'POST', body:JSON.stringify({username, text:txt})});
      toast('已更新 '+username+' 的职责');
      window.loadMembers();
    }
  }catch(e){ toast('操作失败：'+e.message, true); }
}

// ══════════════════════════════════════════════
//  个人中心（接 /api/me/*）
// ══════════════════════════════════════════════
window.bindMeNav = function(){
  $$('.me-nav button').forEach(b => b.addEventListener('click', ()=>{
    $$('.me-nav button').forEach(x=>x.classList.remove('active'));
    b.classList.add('active');
    ['agent','team','workspace','memory','logs'].forEach(k => { const el=$('#me-'+k); if(el) el.classList.toggle('hidden', k!==b.dataset.me); });
    loadMeSub(b.dataset.me);
  }));
};

window.loadMe = function(){ loadMeSub('agent'); };

const _meLoaded = {};
async function loadMeSub(which){
  if(_meLoaded[which]) return;
  try{
    if(which==='agent') await loadMeAgent();
    else if(which==='workspace') await loadMeWorkspace();
    else if(which==='memory') await loadMeMemory();
    else if(which==='logs') await loadMeLogs();
    _meLoaded[which] = true;
  }catch(e){ toast('加载失败：'+e.message, true); }
}

// ══════════════════════════════════════════════
// #8：团队 Agent 一级模块（rail 直达；原个人中心 me-team 升级）
// ══════════════════════════════════════════════
window.loadTeamAgent = async function(){
  let d;
  try{ d = await api('/api/admin/team-agent'); }
  catch(e){
    const ta=$('#teamSoulText'); if(ta) ta.value='（需要管理员权限）';
    return;
  }
  const ta = $('#teamSoulText');
  if(ta) ta.value = d.soul || '';
  const pubStatus = $('#teamPubStatus');
  if(pubStatus) pubStatus.textContent = d.published_at
    ? `上次发布：${d.published_at} · 保存后需再点「发布」才会同步到成员`
    : '⚠ 尚未发布过——成员 agent 还没有团队规则，编辑后点「发布到成员」';
  const saveBtn = $('#saveTeamSoulBtn');
  if(saveBtn) saveBtn.onclick = async ()=>{
    try{
      await api('/api/admin/team-agent/soul', {method:'POST', body:JSON.stringify({soul: $('#teamSoulText').value})});
      toast('已保存母本（尚未发布，点「发布到成员」生效）');
    }catch(e){ toast('保存失败：'+e.message, true); }
  };
  // #8：发布——把团队规则同步进每个成员 profile 的 SOUL（幂等块替换）
  const rulesBtn = $('#rulesAgentBtn');
  if(rulesBtn) rulesBtn.onclick = ()=>{ if(window.wbOpenRulesDialog) window.wbOpenRulesDialog(); };
  const pubBtn = $('#publishTeamSoulBtn');
  if(pubBtn) pubBtn.onclick = async ()=>{
    if(!(await wbConfirm('发布会把当前团队规则同步到所有成员 agent（覆盖成员 SOUL 中的团队规则块，不动个人个性部分）。确认发布？'))) return;
    try{
      // 先保存再发布，防止编辑了没存就发旧版
      await api('/api/admin/team-agent/soul', {method:'POST', body:JSON.stringify({soul: $('#teamSoulText').value})});
      const r = await api('/api/admin/team-agent/publish', {method:'POST', body:'{}'});
      toast(r.message || '已发布');
      W.LOADED.teamagent = false; window.loadTeamAgent();
    }catch(e){ toast('发布失败：'+e.message, true); }
  };
  // 团队默认模型
  const box = $('#teamModelBox');
  if(box){
    const opts = d.model_options || {};
    const provs = Object.keys(opts);
    const curProv = d.provider || provs[0] || '';
    const models = opts[curProv] || (d.model?[d.model]:[]);
    box.innerHTML = `
      <div style="display:flex;gap:12px;flex-wrap:wrap;align-items:end">
        <div style="flex:1;min-width:160px"><label style="font-size:12px;font-weight:600;color:var(--ink-2)">服务商</label>
          <select id="teamProv" class="wbm-in" style="margin-top:4px">${provs.map(p=>`<option ${p===curProv?'selected':''}>${h(p)}</option>`).join('')||`<option>${h(curProv)}</option>`}</select></div>
        <div style="flex:1;min-width:200px"><label style="font-size:12px;font-weight:600;color:var(--ink-2)">模型</label>
          <select id="teamModel" class="wbm-in" style="margin-top:4px">${models.map(m=>`<option ${m===d.model?'selected':''}>${h(m)}</option>`).join('')}</select></div>
        <button class="btn sm primary" id="saveTeamModelBtn">保存模型</button>
      </div>
      <div style="font-size:11px;color:var(--ink-3);margin-top:8px">当前：${h(d.provider||'—')} / ${h(d.model||'—')}</div>`;
    $('#teamProv').onchange = (e)=>{
      const ms = opts[e.target.value] || [];
      $('#teamModel').innerHTML = ms.map(m=>`<option>${h(m)}</option>`).join('');
    };
    $('#saveTeamModelBtn').onclick = async ()=>{
      try{
        await api('/api/admin/team-agent/model', {method:'POST', body:JSON.stringify({provider:$('#teamProv').value, model:$('#teamModel').value})});
        toast('已保存团队默认模型');
        W.LOADED.teamagent=false; window.loadTeamAgent();
      }catch(e){ toast('保存失败：'+e.message, true); }
    };
  }
  // R10：归并规则
  try{
    const mr = await api('/api/admin/merge/rule');
    const mrt = $('#mergeRuleText');
    if(mrt) mrt.value = mr.rule || '';
    const mrb = $('#saveMergeRuleBtn');
    if(mrb) mrb.onclick = async ()=>{
      try{
        await api('/api/admin/team-agent/merge-rule', {method:'POST', body:JSON.stringify({rule: $('#mergeRuleText').value})});
        toast('已保存归并规则');
      }catch(e){ toast('保存失败：'+e.message, true); }
    };
  }catch(_){}
  // 定时任务（从成员管理迁入）
  if(window.wbLoadTasks) window.wbLoadTasks();
};

async function loadMeAgent(){
  const d = await api('/api/me/agent');
  const ta = $('#soulText');
  if(ta) ta.value = d.soul || '';
  // #8：真实拉取团队规则（发布母本）填充只读区，替代硬编码
  try{
    const tr = await api('/api/me/team-rules');
    const ro = $('#teamRulesRO');
    if(ro) ro.textContent = (tr.rules||'').trim() || '（管理员尚未发布团队规则）';
    const meta = $('#teamRulesROMeta');
    if(meta) meta.textContent = (tr.published_at?`发布于 ${tr.published_at} · `:'')+'个人风格与团队规则冲突时，以团队规则为准';
  }catch(_){}
  // 保存按钮
  const saveBtn = $('#me-agent .btn.primary');
  if(saveBtn) saveBtn.onclick = async ()=>{
    try{
      await api('/api/me/soul', {method:'POST', body:JSON.stringify({soul: ta.value})});
      toast('已保存个人风格');
    }catch(e){ toast('保存失败：'+e.message, true); }
  };
  await loadChannels();
}

// ── 模型渠道 ──
let _chData = null;
async function loadChannels(){
  const box = $('#channelList');
  if(!box) return;
  box.innerHTML = '<div style="color:var(--ink-3);padding:12px">加载中…</div>';
  try{
    _chData = await api('/api/me/channels');
  }catch(e){ box.innerHTML = `<div style="color:var(--danger);padding:12px">加载失败：${h(e.message)}</div>`; return; }
  renderChannels();
  const addBtn = $('#addChannelBtn');
  if(addBtn) addBtn.onclick = ()=>{
    _chData.channels.push({id:'', name:'新渠道', provider:'OpenRouter', model:'', base_url:'', has_key:false, key_masked:'', status:'idle', enabled:false, _new:true, _expanded:true});
    renderChannels();
  };
}

function renderChannels(){
  const box = $('#channelList');
  if(!box || !_chData) return;
  const provs = _chData.providers || {};
  const PICON = {'OpenRouter':'🌐','DeepSeek':'🔷','Kimi':'🌙','Anthropic':'🅰️','自定义OpenAI兼容':'⚙️'};
  const chans = _chData.channels || [];
  if(!chans.length){
    box.innerHTML = '<div style="color:var(--ink-3);padding:12px;font-size:13px">还没有配置渠道。点右上「＋ 添加渠道」，或不配则对话走团队公共 Key 兜底。</div>';
    return;
  }
  box.innerHTML = chans.map((c,idx)=>{
    const models = (provs[c.provider] && provs[c.provider].models) || [];
    const statTxt = c.status==='ok'?'● 已连通':c.status==='fail'?'● 未连通':'○ 未测试';
    const isActive = _chData.active_id === c.id;
    return `<div class="channel ${c.enabled?'on':''} ${c._expanded?'expanded':''}" data-idx="${idx}">
      <div class="ch-head" data-act="toggle">
        <div class="ci">${PICON[c.provider]||'🔌'}</div>
        <div class="ct"><div class="cn">${h(c.name)} ${isActive?'<span class="tag green" style="font-size:10px">对话默认</span>':''}</div>
          <div class="cs">${h(c.provider)} · ${h(c.model||'(未选模型)')} ${c.has_key?'· '+h(c.key_masked):'· 无Key'}</div></div>
        <div class="cstat ${c.status}">${statTxt}</div>
        <button class="toggle ${c.enabled?'on':''}" data-act="switch" title="启用/停用"></button>
        <span class="caret">▶</span>
      </div>
      <div class="ch-body">
        <div class="ch-row"><div class="k">渠道名称</div><input type="text" value="${h(c.name)}" data-f="name"></div>
        <div class="ch-row"><div class="k">服务商</div>
          <select data-f="provider">${Object.keys(provs).map(p=>`<option ${p===c.provider?'selected':''}>${h(p)}</option>`).join('')}</select></div>
        <div class="ch-row"><div class="k">API Key</div><input type="password" value="" data-f="key" placeholder="${c.has_key?'已配置（'+h(c.key_masked)+'），留空不改':'sk-...'}"></div>
        ${c.provider==='自定义OpenAI兼容'?`<div class="ch-row"><div class="k">Base URL</div><input type="text" value="${h(c.base_url)}" data-f="base_url" placeholder="https://..."></div>`:''}
        <div class="ch-row"><div class="k">模型</div>
          ${models.length?`<select data-f="model">${models.map(m=>`<option ${m===c.model?'selected':''}>${h(m)}</option>`).join('')}</select>`:`<input type="text" value="${h(c.model)}" data-f="model" placeholder="模型ID">`}</div>
        <div class="ch-actions">
          <button class="btn sm primary" data-act="save">保存</button>
          <button class="btn sm" data-act="test">⚡ 测试连通性</button>
          ${!isActive?`<button class="btn sm" data-act="activate">设为对话默认</button>`:''}
          <button class="btn sm ghost" data-act="del">删除</button>
          <span class="result ${c.status}">${c.status==='ok'?'✓ 上次测试通过':c.status==='fail'?'✗ 连接失败':''}</span>
        </div>
      </div></div>`;
  }).join('');
  // 事件
  box.querySelectorAll('.channel').forEach(el=>{
    const idx = +el.dataset.idx;
    const c = _chData.channels[idx];
    el.querySelector('.ch-head').addEventListener('click', (e)=>{
      if(e.target.dataset.act==='switch'){
        e.stopPropagation();
        c.enabled = !c.enabled;
        chSave(c, {silent:true});
        return;
      }
      c._expanded = !c._expanded; renderChannels();
    });
    el.querySelectorAll('[data-f]').forEach(inp => inp.addEventListener('change', ()=>{
      const f = inp.dataset.f; c[f] = inp.value;
      if(f==='provider'){ const ms=(provs[c.provider]&&provs[c.provider].models)||[]; c.model=ms[0]||''; renderChannels(); }
    }));
    el.querySelectorAll('[data-act]').forEach(b => b.addEventListener('click', (e)=>{
      e.stopPropagation();
      const act = b.dataset.act;
      if(act==='save') chSave(c);
      else if(act==='test') chTest(c, el);
      else if(act==='activate') chActivate(c);
      else if(act==='del') chDelete(c);
    }));
  });
}

async function chSave(c, opts){
  opts = opts||{};
  try{
    const body = {id:c._new?undefined:c.id, name:c.name, provider:c.provider, model:c.model, base_url:c.base_url, enabled:c.enabled};
    const keyInp = document.querySelector(`.channel[data-idx] input[data-f="key"]`);
    // 取当前卡片的 key 输入
    const el = [...document.querySelectorAll('.channel')].find(x=>_chData.channels[+x.dataset.idx]===c);
    if(el){ const ki = el.querySelector('input[data-f="key"]'); if(ki && ki.value) body.key = ki.value; }
    const r = await api('/api/me/channels/save', {method:'POST', body:JSON.stringify(body)});
    if(!opts.silent) toast('已保存渠道');
    await loadChannels();
  }catch(e){ toast('保存失败：'+e.message, true); }
}
async function chTest(c, el){
  if(c._new){ toast('请先保存渠道再测试', true); return; }
  const res = el.querySelector('.result');
  if(res){ res.className='result testing'; res.textContent='⏳ 测试中…'; }
  try{
    const d = await api('/api/me/channels/test', {method:'POST', body:JSON.stringify({id:c.id})});
    toast(d.ok?'连通正常':('未连通：'+(d.message||'')), !d.ok);
    await loadChannels();
  }catch(e){ toast('测试失败：'+e.message, true); }
}
async function chActivate(c){
  if(c._new){ toast('请先保存渠道', true); return; }
  try{ await api('/api/me/channels/activate',{method:'POST',body:JSON.stringify({id:c.id})}); toast('已设为对话默认'); await loadChannels(); }
  catch(e){ toast('操作失败：'+e.message, true); }
}
async function chDelete(c){
  if(c._new){ _chData.channels = _chData.channels.filter(x=>x!==c); renderChannels(); return; }
  if(!(await wbConfirm('删除渠道「'+c.name+'」？'))) return;
  try{ await api('/api/me/channels/delete',{method:'POST',body:JSON.stringify({id:c.id})}); toast('已删除'); await loadChannels(); }
  catch(e){ toast('删除失败：'+e.message, true); }
}

async function loadMeWorkspace(){
  const d = await api('/api/me/workspace');
  // uploads 列表
  const up = $('#uploadList');
  if(up){
    const files = d.files || [];
    up.innerHTML = files.length ? files.map(f=>{
      const kb = f.size<1024?f.size+'B':(f.size/1024).toFixed(1)+'KB';
      return `<div class="attach-card" style="margin-bottom:8px"><span class="ai">📄</span><span class="an">${h(f.path)}</span><span class="as">${kb}</span></div>`;
    }).join('') : '<div style="color:var(--ink-3);font-size:12px">工作库为空。对话中拖文件或点 📎 上传。</div>';
  }
  await loadDevices();
  // 同步索引按钮
  const reindexBtn = $('#reindexBtn');
  if(reindexBtn) reindexBtn.onclick = async ()=>{
    try{
      const r = await api('/api/me/workspace/reindex', {method:'POST', body:JSON.stringify({})});
      const cnt = (r.workspace && r.workspace.count) || 0;
      toast('索引已同步，共 '+cnt+' 个文件');
      _meLoaded.workspace = false; loadMeSub('workspace');
    }catch(e){ toast('同步失败：'+e.message, true); }
  };
}

// ── 设备 + 工作库登记 ──
let _devData = null;
async function loadDevices(){
  try{ _devData = await api('/api/me/devices'); }
  catch(e){ return; }
  renderDevices();
  // 登记设备按钮（envList 上方的 panel-head 里）
  const regBtn = document.querySelector('#me-workspace .panel-head .btn.primary');
  if(regBtn) regBtn.onclick = registerDevice;
  // 添加工作库按钮（第二个 panel）
  const addWsBtn = document.querySelectorAll('#me-workspace .panel-head .btn.primary')[1];
  if(addWsBtn) addWsBtn.onclick = addWorkspaceEntry;
}

function renderDevices(){
  if(!_devData) return;
  const cur = _devData.current_machine_id || '';
  // 设备列表
  const envList = $('#envList');
  if(envList){
    const devs = _devData.devices || [];
    // 当前设备是否已登记
    const curReg = devs.find(x=>x.machine_id===cur);
    let html = devs.map(e=>{
      const isCur = e.machine_id===cur;
      return `<div class="mem-item"><span style="font-size:18px">🖥</span>
        <div class="mt"><b>${h(e.name)}</b> ${isCur?'<span class="tag green" style="font-size:10px">当前设备</span>':''}
          <span style="font-family:monospace;font-size:11px;color:var(--ink-3);margin-left:6px">ID:${h((e.machine_id||'').slice(0,16))}…</span>
          <div class="md">${isCur?'🟢 在线 — agent 可实时读取该设备工作库':'⚪ 其它设备 — 离线时可走 git 降级'}</div></div>
        <div class="ma"><button data-dev="${h(e.id)}" data-act="rmdev" title="移除">🗑</button></div></div>`;
    }).join('');
    if(!curReg){
      html += `<div style="color:var(--ink-3);font-size:12px;padding:10px;border:1px dashed var(--line);border-radius:10px;margin-top:8px">
        当前设备（ID:${h(cur.slice(0,16))}…）还没登记。点右上「＋ 登记当前设备」，agent 就能识别这台机器的工作库。</div>`;
    }
    envList.innerHTML = html || '<div style="color:var(--ink-3);font-size:12px">还没登记任何设备</div>';
    envList.querySelectorAll('[data-act="rmdev"]').forEach(b=>b.addEventListener('click', async ()=>{
      if(!(await wbConfirm('移除该设备登记？'))) return;
      try{ await api('/api/me/devices/remove',{method:'POST',body:JSON.stringify({id:b.dataset.dev})}); toast('已移除'); loadDevices(); }
      catch(e){ toast('失败：'+e.message, true); }
    }));
  }
  // 工作库表格
  const wsTable = $('#wsTable');
  if(wsTable){
    const wss = _devData.workspaces || [];
    const devName = id => { const d=(_devData.devices||[]).find(x=>x.id===id); return d?d.name:'—'; };
    wsTable.innerHTML = wss.length ? wss.map(w=>`<tr style="cursor:default">
      <td style="font-weight:600">${h(w.name)}</td>
      <td style="color:var(--ink-3);font-family:monospace;font-size:11px">${h(w.local_path)}</td>
      <td>${h(devName(w.device_id))}</td>
      <td style="font-size:11px">${w.git_repo?`<span style="font-family:monospace;color:var(--ink-2)">${h(w.git_repo)}</span>`:'<span style="color:var(--ink-3)">未配置</span>'}</td>
      <td>${tag('已登记','green')}</td>
      <td><button class="btn sm ghost" data-ws="${h(w.id)}" data-act="rmws">移除</button></td></tr>`).join('')
      : '<tr><td colspan="6" style="text-align:center;color:var(--ink-3);padding:20px">还没登记工作库目录</td></tr>';
    wsTable.querySelectorAll('[data-act="rmws"]').forEach(b=>b.addEventListener('click', async ()=>{
      if(!(await wbConfirm('移除该工作库登记？'))) return;
      try{ await api('/api/me/workspaces/remove',{method:'POST',body:JSON.stringify({id:b.dataset.ws})}); toast('已移除'); loadDevices(); }
      catch(e){ toast('失败：'+e.message, true); }
    }));
  }
}

async function registerDevice(){
  const name = await wbPrompt('给这台设备起个名字（如：公司办公机 / 家里笔记本）：');
  if(!name) return;
  try{
    const d = await api('/api/me/devices/register', {method:'POST', body:JSON.stringify({name})});
    toast('已登记当前设备');
    loadDevices();
  }catch(e){ toast('登记失败：'+e.message, true); }
}

async function addWorkspaceEntry(){
  const name = await wbPrompt('工作库名称（如：默认工作库 / 竞品素材）：');
  if(!name) return;
  const local_path = await wbPrompt('本地物理地址（如 D:\\work\\ 或 /Users/xx/work/）：');
  if(!local_path) return;
  const git_repo = await wbPrompt('Git 仓库地址（可选，离线降级用；不填留空）：') || '';
  // 绑定到当前设备
  const cur = _devData && (_devData.devices||[]).find(x=>x.machine_id===_devData.current_machine_id);
  try{
    await api('/api/me/workspaces/save', {method:'POST', body:JSON.stringify({
      name, local_path, git_repo, device_id: cur?cur.id:''
    })});
    toast('已添加工作库');
    loadDevices();
  }catch(e){ toast('添加失败：'+e.message, true); }
}

async function loadMeMemory(){
  const d = await api('/api/me/memory');
  const box = $('#memList');
  if(!box) return;
  const mem = d.memory || '';
  const usr = d.user || '';
  box.innerHTML = `
    <div style="margin-bottom:16px">
      <div style="font-size:12px;font-weight:600;color:var(--ink-2);margin-bottom:8px">MEMORY.md（事实/偏好/环境）</div>
      <textarea id="meMemoryText" style="width:100%;min-height:140px;padding:12px;border-radius:11px;border:1px solid var(--line);font-size:13px;font-family:ui-monospace,monospace;line-height:1.6;background:rgba(255,255,255,.8);color:var(--ink);resize:vertical">${h(mem)}</textarea>
      <div style="text-align:right;margin-top:8px"><button class="btn sm primary" id="saveMemBtn">保存 Memory</button></div>
    </div>
    <div>
      <div style="font-size:12px;font-weight:600;color:var(--ink-2);margin-bottom:8px">USER.md（关于你）</div>
      <textarea id="meUserText" style="width:100%;min-height:120px;padding:12px;border-radius:11px;border:1px solid var(--line);font-size:13px;font-family:ui-monospace,monospace;line-height:1.6;background:rgba(255,255,255,.8);color:var(--ink);resize:vertical">${h(usr)}</textarea>
      <div style="text-align:right;margin-top:8px"><button class="btn sm primary" id="saveUserBtn">保存 USER</button></div>
    </div>`;
  $('#saveMemBtn').onclick = async ()=>{
    try{ await api('/api/me/memory',{method:'POST',body:JSON.stringify({which:'memory',content:$('#meMemoryText').value})}); toast('已保存 Memory'); }
    catch(e){ toast('保存失败：'+e.message, true); }
  };
  $('#saveUserBtn').onclick = async ()=>{
    try{ await api('/api/me/memory',{method:'POST',body:JSON.stringify({which:'user',content:$('#meUserText').value})}); toast('已保存 USER'); }
    catch(e){ toast('保存失败：'+e.message, true); }
  };
  // 手动添加（原型 panel-head 静态按钮）→ 追加一行到 MEMORY.md textarea
  const addMemBtn = document.querySelector('#me-memory .panel-head .btn.primary');
  if(addMemBtn) addMemBtn.onclick = async ()=>{
    const line = await wbPrompt('添加一条记忆（会追加到 MEMORY.md）：');
    if(!line) return;
    const ta = $('#meMemoryText');
    ta.value = (ta.value.trim() ? ta.value.trimEnd()+'\n' : '') + '- ' + line;
    toast('已追加，记得点「保存 Memory」');
    ta.scrollTop = ta.scrollHeight;
  };
}

async function loadMeLogs(){
  const d = await api('/api/me/logs');
  const box = $('#logBox');
  if(!box) return;
  const entries = d.entries || [];
  // 动态渲染 log-bar（真实文件下拉 + 刷新 + 下载）
  const bar = document.querySelector('#me-logs .log-bar');
  if(bar){
    const opts = entries.length
      ? entries.map(e=>`<option value="${h(e.file)}">${h(e.file)}</option>`).join('')
      : '<option value="">（无日志文件）</option>';
    bar.innerHTML = `
      <select id="logFileSel">${opts}</select>
      <input id="logFilter" placeholder="过滤关键字…">
      <button class="btn sm" id="logRefreshBtn">刷新</button>
      <button class="btn sm" id="logDownloadBtn">下载</button>`;
    bar.querySelector('#logRefreshBtn').onclick = ()=>{ _meLoaded.logs=false; loadMeSub('logs'); };
    bar.querySelector('#logDownloadBtn').onclick = ()=>{
      const f = bar.querySelector('#logFileSel').value;
      if(!f){ toast('没有可下载的日志', true); return; }
      // 触发浏览器下载
      window.location.href = '/api/me/logs/download?file='+encodeURIComponent(f);
    };
    bar.querySelector('#logFilter').addEventListener('input', (e)=>renderLogBox(entries, e.target.value));
  }
  renderLogBox(entries, '');
}
function renderLogBox(entries, filter){
  const box = $('#logBox');
  if(!box) return;
  if(!entries.length){ box.innerHTML = '<div class="lt">暂无日志文件</div>'; return; }
  const f = (filter||'').toLowerCase();
  box.innerHTML = entries.map(e=>{
    const head = `<div class="lw">━━ ${h(e.file)} (${(e.size/1024).toFixed(1)}KB) ━━</div>`;
    let lines = e.tail||[];
    if(f) lines = lines.filter(l=>l.toLowerCase().includes(f));
    const body = lines.map(l=>`<div><span class="li">${h(l)}</span></div>`).join('') || '<div class="lt">（无匹配行）</div>';
    return head + body;
  }).join('');
}

})();
