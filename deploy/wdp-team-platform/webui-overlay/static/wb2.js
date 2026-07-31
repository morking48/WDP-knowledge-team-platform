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
    // 按 agent 建议去向分组（便于批量审）：
    //   📦 建议归项目 = 建议类目为需求 且 agent 预判了 related_project
    //   📋 建议归公共 = 建议类目为需求 且 无项目预判
    //   📥 其它       = 信号 / 设计 / 项目开档等非需求类
    // 待审项此刻并未真正分池（去向审核时才定），这里只是按「建议」分组呈现，语义成立。
    const groupOf = (r)=>{
      const cat = (r.suggestion && r.suggestion.target_category) || r.category || '';
      if(cat === 'requirements') return (r.suggested_project ? 'project' : 'public');
      return 'other';
    };
    const groups = [
      {key:'project', label:'📦 建议归项目需求', color:'#7c3aed'},
      {key:'public',  label:'📋 建议归公共需求', color:'#16a34a'},
      {key:'other',   label:'📥 其它（信号/设计/开档）', color:'#64748b'},
    ];
    const itemHtml = (r, i)=>`
      <div class="review-item" data-i="${i}">
        <div class="rt">${h(r.title||'(无标题)')}</div>
        <div class="rm">${tag(r.category||'—','green')}<span>${h(r.username)} · ${h(r.submitted_at||'')}</span>${r.suggested_project?`<span class="tag" style="background:#ede9fe;color:#6d28d9;font-size:10px;margin-left:4px">→${h(r.suggested_project)}</span>`:''}</div>
      </div>`;
    let html = '';
    for(const g of groups){
      const members = _rvItems.map((r,i)=>({r,i})).filter(x=>groupOf(x.r)===g.key);
      if(!members.length) continue;
      html += `<div class="rv-group-hd" style="font-size:11px;font-weight:700;color:${g.color};padding:8px 4px 4px;border-bottom:1px solid var(--line,#e5e9e7);margin-top:6px">${g.label} <span style="opacity:.6">(${members.length})</span></div>`;
      html += members.map(x=>itemHtml(x.r, x.i)).join('');
    }
    list.innerHTML = html;
    list.querySelectorAll('.review-item').forEach(el => el.addEventListener('click', ()=>{
      list.querySelectorAll('.review-item').forEach(x=>x.classList.remove('sel'));
      el.classList.add('sel');
      renderReviewDetail(+el.dataset.i);
    }));
    // 默认选中第一条（可能在任意分组内）——取第一个渲染出来的 item 的真实索引
    const first = list.querySelector('.review-item');
    if(first) first.classList.add('sel');
    renderReviewDetail(first ? +first.dataset.i : 0);
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
  const defCat = sug.target_category || _rvSel.category || 'signals';
  // 非需求类目仍可切换（信号/设计/项目开档），需求类目的公共/项目二选一改由标签页承载
  const nonReqOpts = [
    {value:'signals', label:'📥 信号池 signals'},
    {value:'requirements', label:'📋 需求（公共/项目见标签页）'},
    {value:'designs', label:'📐 设计池 designs'},
    {value:'projects', label:'📦 项目开档 projects'},
  ];
  const sugProject = (sug.suggested_fields && sug.suggested_fields.related_project) || '';
  // 拉已开档项目列表（供项目需求池选择）
  let prjOpts = [];
  try{
    const pj = await api('/api/knowledge/projects');
    prjOpts = (pj.projects||[]).filter(p=>p.status!=='已结项').map(p=>({value:p.dir, label:`${p.title}（${p.customer||'—'}）`}));
  }catch(_){}

  let category, target_pool = null, target_project = null, form;

  if(defCat === 'requirements'){
    // ── 需求入库：顶部两个标签页「公共需求池 / 项目需求池」，彻底分开、不再混一个下拉 ──
    // AI 若标了项目归属，默认落在「项目需求池」tab，否则默认「公共需求池」。
    const defTab = sugProject ? 'project' : 'public';
    const prjPreselect = sugProject && prjOpts.find(o=>o.label.includes(sugProject))
      ? prjOpts.find(o=>o.label.includes(sugProject)).value
      : (prjOpts[0] && prjOpts[0].value || '');
    const fields = [
      // 公共池 tab：纯说明,不放输入框
      {key:'_public_hint', label:'该需求进入公共需求池，面向全团队，不归属任何项目。直接点「通过入库」即可。', type:'note', tab:'public'},
      // 项目池 tab：必选项目
      prjOpts.length
        ? {key:'target_project', label:'归属项目', type:'select', value:prjPreselect, options:prjOpts, tab:'project', required:true}
        : {key:'_no_prj', label:'当前没有已开档项目。点「通过入库」将提示为该需求开档。', type:'note', tab:'project'},
      // 公共字段（两 tab 都显示）
      {key:'final_name', label:'最终文件名（.md 结尾）', type:'text', value: sug.suggested_name || _rvSel.file, required:true},
      {key:'target_release', label:'目标版本（可空）', type:'text', value:''},
      {key:'note', label:'审核备注（可选）', type:'textarea', value:''},
    ];
    form = await wbForm('通过入库 · 需求', fields, {
      icon:'📋', okText:'通过入库', width:540,
      tabs:[{key:'public', label:'📋 公共需求池'}, {key:'project', label:'📦 项目需求池'}],
      activeTab: defTab,
    });
    if(!form) return;
    if(!form.final_name){ toast('文件名必填', true); return; }
    category = 'requirements';
    if(form.__tab === 'project'){
      target_pool = 'project';
      target_project = form.target_project || sugProject || '';
      if(!target_project){ toast('请选择归属项目', true); return; }
    } else {
      target_pool = 'public';
    }
  } else {
    // ── 非需求类目：保持单下拉（信号/设计/项目开档）──
    const fields = [
      {key:'category', label:'入库去向', type:'select', value:defCat, options:nonReqOpts},
      {key:'final_name', label:'最终文件名（.md 结尾）', type:'text', value: sug.suggested_name || _rvSel.file, required:true},
      {key:'designer', label:'设计人（仅设计时生效，可空）', type:'text', value:''},
      {key:'target_release', label:'目标版本（仅设计生效，可空）', type:'text', value:''},
      {key:'note', label:'审核备注（可选）', type:'textarea', value:''},
    ];
    form = await wbForm('通过入库', fields, {icon:'📥', okText:'通过入库', width:520});
    if(!form) return;
    if(!form.final_name){ toast('文件名必填', true); return; }
    category = form.category;
    // 用户在下拉里把类目改成了需求 → 默认进公共池（要归项目请用需求类目走标签页）
    if(category === 'requirements') target_pool = 'public';
  }

  const extra = {};
  if((form.designer||'').trim()) extra.designer = form.designer.trim();
  if((form.target_release||'').trim()) extra.target_release = form.target_release.trim();
  const doIt = ()=>api('/api/review/approve', {method:'POST', body:JSON.stringify({
    user:_rvSel._profile, file:_rvSel.file, final_name:form.final_name, final_category:category,
    target_pool, target_project, note:form.note||'', extra_fields: extra})});
  try{
    const d = await doIt();
    toast(d.message || ('已入库到 '+(d.final_path||'')));
    api('/api/admin/team-agent/record-decision', {method:'POST', body:JSON.stringify({
      kind:'review', entry:{title:_rvSel.title, category:category, decision:'通过', ai_advice:'', reason:form.note||''}})}).catch(()=>{});
    W.LOADED.board = false; if(window.wbRefreshRailCnt)window.wbRefreshRailCnt();
    window.loadReview();
  }catch(e){
    // 项目未开档 → 引导开档或改公共池
    if(e.status===409 && e.data && e.data.code==='PROJECT_NOT_FOUND'){
      const pn = e.data.project_name||'该项目';
      const go = await wbConfirm(`项目「${pn}」还没开档，项目需求无法入库。\n\n点「确定」现在为它开档（填最简信息），点「取消」改入公共需求池。`);
      if(go){
        const pf = await wbForm('为「'+pn+'」开档', [
          {key:'customer', label:'客户名称', type:'text', value:pn, required:true},
          {key:'phase', label:'阶段', type:'select', value:'售前', options:['售前','交付中','售后']},
          {key:'description', label:'项目概述', type:'textarea', value:''},
        ], {icon:'📦', okText:'开档并入库需求'});
        if(!pf) return;
        try{
          const pr = await wbCreateProjectSafe({title:pn, customer:pf.customer, phase:pf.phase, description:pf.description});
          if(!pr){ return; }
          if(!pr.dir){ toast('开档失败', true); return; }
          target_project = pr.dir;
          const d2 = await api('/api/review/approve', {method:'POST', body:JSON.stringify({
            user:_rvSel._profile, file:_rvSel.file, final_name:form.final_name, final_category:'requirements',
            target_pool:'project', target_project, note:form.note||'', extra_fields: extra})});
          toast('项目已开档，'+(d2.message||'需求已入库'));
          W.LOADED.board=false; if(window.wbRefreshRailCnt)window.wbRefreshRailCnt(); window.loadReview();
        }catch(e2){ toast('开档/入库失败：'+e2.message, true); }
      } else {
        // 改入公共池
        try{
          const d3 = await api('/api/review/approve', {method:'POST', body:JSON.stringify({
            user:_rvSel._profile, file:_rvSel.file, final_name:form.final_name, final_category:'requirements',
            target_pool:'public', note:form.note||'', extra_fields: extra})});
          toast('已改入公共需求池：'+(d3.final_path||''));
          W.LOADED.board=false; if(window.wbRefreshRailCnt)window.wbRefreshRailCnt(); window.loadReview();
        }catch(e3){ toast('入库失败：'+e3.message, true); }
      }
    } else if(e.status === 422 || (e.data && e.data.missing)){
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
    // 记录驳回决策（基础入口无 AI 分析，ai_advice 留空）
    api('/api/admin/team-agent/record-decision', {method:'POST', body:JSON.stringify({
      kind:'review', entry:{title:_rvSel.title, category:_rvSel.category, decision:'驳回',
        ai_advice:'', reason}
    })}).catch(()=>{});
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
    ['agent','skills','team','workspace','memory','logs'].forEach(k => { const el=$('#me-'+k); if(el) el.classList.toggle('hidden', k!==b.dataset.me); });
    loadMeSub(b.dataset.me);
  }));
};

window.loadMe = function(){ loadMeSub('agent'); };

const _meLoaded = {};
async function loadMeSub(which){
  if(_meLoaded[which]) return;
  try{
    if(which==='agent') await loadMeAgent();
    else if(which==='skills') await loadMeSkills();
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
  if(rulesBtn) rulesBtn.onclick = ()=>{ if(window.wbOpenRulesDialog) window.wbOpenRulesDialog($('#teamSoulText') ? $('#teamSoulText').value : (d.soul||'')); };
  // 回滚：把团队规则恢复到上一份快照（规则助手改坏时的安全网）
  const rbBtn = $('#rollbackSoulBtn');
  if(rbBtn){
    const snaps = d.snapshots || [];
    rbBtn.style.display = snaps.length ? '' : 'none';
    rbBtn.onclick = async ()=>{
      if(!snaps.length){ toast('暂无历史快照可回滚', true); return; }
      if(!(await wbConfirm(`回滚会把团队规则母本恢复到上一份快照（${snaps[0].name}）。回滚后需再点「发布」才生效到成员。确认回滚？`))) return;
      try{
        const r = await api('/api/admin/team-agent/rollback-rules', {method:'POST', body:'{}'});
        toast(r.message || '已回滚');
        W.LOADED.teamagent = false; window.loadTeamAgent();
      }catch(e){ toast('回滚失败：'+e.message, true); }
    };
  }
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
  // 集成授权（团队级，飞书等）
  loadTeamIntegrations(d);
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
  // 审核规则（与归并规则平级，驱动决策中心审核助手）
  try{
    const rr = await api('/api/admin/review/rule');
    const rrt = $('#reviewRuleText');
    if(rrt) rrt.value = rr.rule || '';
    const rrb = $('#saveReviewRuleBtn');
    if(rrb) rrb.onclick = async ()=>{
      try{
        await api('/api/admin/team-agent/review-rule', {method:'POST', body:JSON.stringify({rule: $('#reviewRuleText').value})});
        toast('已保存审核规则');
      }catch(e){ toast('保存失败：'+e.message, true); }
    };
  }catch(_){}
  // 定时任务（从成员管理迁入）
  if(window.wbLoadTasks) window.wbLoadTasks();
  // 团队技能编辑面板
  window.loadTeamSkills();
  const rtsBtn = $('#reloadTeamSkillsBtn');
  if(rtsBtn) rtsBtn.onclick = ()=>window.loadTeamSkills();
  // 新建团队技能：wbForm 表单 → 后端建骨架 → 引导用技能助手充实
  const ntsBtn = $('#newTeamSkillBtn');
  if(ntsBtn) ntsBtn.onclick = async ()=>{
    const f = await wbForm('新建团队技能', [
      {key:'skill_dir', label:'目录名（英文小写-中划线）', type:'text', required:true, placeholder:'如 competitor-analysis'},
      {key:'name', label:'技能名称', type:'text', placeholder:'如 竞品分析方法'},
      {key:'description', label:'一句话描述（做什么/何时触发）', type:'textarea', placeholder:'如 竞品动态跟踪与分析的标准流程'},
    ]);
    if(!f) return;
    try{
      const r = await api('/api/admin/team-agent/skill/create', {method:'POST', body:JSON.stringify(f)});
      toast(r.message || '已创建');
      window.loadTeamSkills();
    }catch(e){ toast('创建失败：'+e.message, true); }
  };
};

// ── 团队技能编辑（admin：技能助手对话改 → 存草稿 → 发布同步成员）──
window.loadTeamSkills = async function(){
  const box = $('#teamSkillsBox');
  if(!box) return;
  box.innerHTML = '<div style="color:var(--ink-3);font-size:13px">加载中…</div>';
  let d;
  try{ d = await api('/api/admin/team-agent/skills'); }
  catch(e){ box.innerHTML = `<div style="color:var(--danger)">加载失败：${h(e.message)}</div>`; return; }
  const skills = d.skills || [];
  if(!skills.length){ box.innerHTML = '<div style="color:var(--ink-3);font-size:13px">暂无团队技能</div>'; return; }
  box.innerHTML = skills.map(s=>`
    <div style="display:flex;align-items:center;gap:12px;padding:10px 12px;border:1px solid var(--line-2);border-radius:10px;margin-bottom:8px;background:rgba(255,255,255,.55)">
      <div style="flex:1;min-width:0">
        <div style="font-weight:600">${h(s.name||s.dir)}${s.protected?' <span class="tag green" style="font-size:10px">内置</span>':''}${s.has_draft?' <span class="tag" style="font-size:10px;background:#fef3c7;color:#b45309">有未发布草稿</span>':''}</div>
        <div style="font-size:12px;color:var(--ink-3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${h(s.description||'—')}</div>
      </div>
      <button class="btn sm ts-edit" data-dir="${h(s.dir)}" data-name="${h(s.name||s.dir)}">🤖 技能助手</button>
      ${s.has_draft?`<button class="btn sm primary ts-pub" data-dir="${h(s.dir)}">🚀 发布</button><button class="btn sm ts-discard" data-dir="${h(s.dir)}">丢弃草稿</button>`:''}
      ${s.protected?'':`<button class="btn sm ts-del" data-dir="${h(s.dir)}" title="删除该技能（内置技能不可删）" style="color:var(--danger)">🗑</button>`}
    </div>`).join('');
  // 技能助手：开对话编辑
  box.querySelectorAll('.ts-edit').forEach(b=>b.onclick=()=>{
    if(window.wbOpenSkillDialog) window.wbOpenSkillDialog(b.dataset.dir, b.dataset.name);
  });
  // 发布草稿到成员
  box.querySelectorAll('.ts-pub').forEach(b=>b.onclick=async ()=>{
    if(!(await wbConfirm('发布会把草稿写入正式团队技能，所有成员将实时同步。确认发布？'))) return;
    try{
      const r = await api('/api/admin/team-agent/skill/publish', {method:'POST', body:JSON.stringify({skill_dir:b.dataset.dir})});
      toast(r.message || '已发布，成员将实时同步');
      window.loadTeamSkills();
    }catch(e){ toast('发布失败：'+e.message, true); }
  });
  // 丢弃草稿
  box.querySelectorAll('.ts-discard').forEach(b=>b.onclick=async ()=>{
    if(!(await wbConfirm('丢弃这个技能的未发布草稿？'))) return;
    try{
      await api('/api/admin/team-agent/skill/discard', {method:'POST', body:JSON.stringify({skill_dir:b.dataset.dir})});
      toast('已丢弃草稿');
      window.loadTeamSkills();
    }catch(e){ toast('操作失败：'+e.message, true); }
  });
  // 删除技能（内置不可删，后端双重校验）
  box.querySelectorAll('.ts-del').forEach(b=>b.onclick=async ()=>{
    if(!(await wbConfirm('删除团队技能「'+b.dataset.dir+'」？删除后成员将不再加载它（有备份可人工恢复）。'))) return;
    try{
      const r = await api('/api/admin/team-agent/skill/delete', {method:'POST', body:JSON.stringify({skill_dir:b.dataset.dir})});
      toast(r.message || '已删除');
      window.loadTeamSkills();
    }catch(e){ toast('删除失败：'+e.message, true); }
  });
};

// ── 技能页（团队只读 + 个人可开关/删除）──
async function loadMeSkills(){
  const teamBox = $('#teamSkillList');
  const persBox = $('#personalSkillList');
  if(teamBox) teamBox.innerHTML = '<div style="color:var(--ink-3);font-size:13px">加载中…</div>';
  let d;
  try{ d = await api('/api/me/skills'); }
  catch(e){ if(teamBox) teamBox.innerHTML = `<div style="color:var(--danger)">加载失败：${h(e.message)}</div>`; return; }
  const card = (s, actions) => `<div style="display:flex;align-items:center;gap:12px;padding:10px 12px;border:1px solid var(--line-2);border-radius:10px;margin-bottom:8px;background:rgba(255,255,255,.55)">
    <div style="flex:1;min-width:0">
      <div style="font-weight:600">${h(s.name)}${s.enabled===false?' <span class="tag gray" style="font-size:10px">已停用</span>':''}</div>
      <div style="font-size:12px;color:var(--ink-3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${h(s.description||'（无描述）')}</div>
    </div>${actions||''}</div>`;
  // 团队技能（只读）
  const team = d.team || [];
  if(teamBox) teamBox.innerHTML = team.length ? team.map(s=>card(s,'<span class="tag green" style="font-size:10px">团队</span>')).join('')
    : '<div style="color:var(--ink-3);font-size:13px">暂无团队技能</div>';
  // 个人技能（开关 + 删除）
  const pers = d.personal || [];
  if(persBox){
    persBox.innerHTML = pers.length ? pers.map(s=>card(s,
      `<button class="toggle ${s.enabled?'on':''}" data-sk="${h(s.name)}" data-en="${s.enabled?1:0}" data-act="sktoggle" title="启用/停用"></button>
       <button class="btn sm ghost" data-sk="${h(s.name)}" data-act="skdel" style="color:var(--danger)">删除</button>`)).join('')
      : '<div style="color:var(--ink-3);font-size:13px;line-height:1.7">还没有个人技能。<br>在对话中让 agent 帮你把反复用的工作方法「沉淀成技能」，就会出现在这里。</div>';
    persBox.querySelectorAll('[data-act="sktoggle"]').forEach(b=>b.addEventListener('click', async ()=>{
      const en = b.dataset.en !== '1';
      try{ await api('/api/me/skills/toggle',{method:'POST',body:JSON.stringify({name:b.dataset.sk, enabled:en})});
        toast(en?'已启用（下次对话生效）':'已停用（下次对话生效）'); _meLoaded.skills=false; loadMeSkills();
      }catch(e){ toast('操作失败：'+e.message, true); }
    }));
    persBox.querySelectorAll('[data-act="skdel"]').forEach(b=>b.addEventListener('click', async ()=>{
      if(!(await wbConfirm('删除个人技能「'+b.dataset.sk+'」？不可恢复。'))) return;
      try{ await api('/api/me/skills/delete',{method:'POST',body:JSON.stringify({name:b.dataset.sk})});
        toast('已删除'); _meLoaded.skills=false; loadMeSkills();
      }catch(e){ toast('删除失败：'+e.message, true); }
    }));
  }
}

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
  const PICON = {'OpenRouter':'🌐','DeepSeek':'🔷','Kimi':'🌙','Anthropic':'🅰️','Claude(n1n代理)':'🅰️','GitHub Copilot':'🐙','自定义OpenAI兼容':'⚙️'};
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
        <div class="ch-row"><div class="k">${c.provider==='GitHub Copilot'?'Copilot Token':'API Key'}</div><input type="password" value="" data-f="key" placeholder="${c.has_key?'已配置（'+h(c.key_masked)+'），留空不改':(c.provider==='GitHub Copilot'?'gho_... / ghu_...（你的 GitHub Copilot token）':'sk-...')}"></div>
        ${c.provider==='GitHub Copilot'?`<div class="ch-row"><div class="k"></div><div style="font-size:11px;color:var(--ink-3);line-height:1.6">💡 用你自己的 GitHub Copilot 订阅额度。获取 token：本机装了 GitHub Copilot（VS Code 插件或 <code>gh</code> CLI）并登录后，token 在 <code>~/.config/github-copilot/</code> 或运行 <code>gh auth token</code> 获取（gho_/ghu_ 开头）。填入后点「测试连通性」验证。</div></div>`:''}
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
      <td><button class="btn sm ghost" data-ws="${h(w.id)}" data-act="editws" data-name="${h(w.name)}" data-path="${h(w.local_path)}" data-git="${h(w.git_repo||'')}" data-dev="${h(w.device_id||'')}">编辑</button>
          <button class="btn sm ghost" data-ws="${h(w.id)}" data-act="rmws">移除</button></td></tr>`).join('')
      : '<tr><td colspan="6" style="text-align:center;color:var(--ink-3);padding:20px">还没登记工作库目录</td></tr>';
    wsTable.querySelectorAll('[data-act="rmws"]').forEach(b=>b.addEventListener('click', async ()=>{
      if(!(await wbConfirm('移除该工作库登记？'))) return;
      try{ await api('/api/me/workspaces/remove',{method:'POST',body:JSON.stringify({id:b.dataset.ws})}); toast('已移除'); loadDevices(); }
      catch(e){ toast('失败：'+e.message, true); }
    }));
    wsTable.querySelectorAll('[data-act="editws"]').forEach(b=>b.addEventListener('click', async ()=>{
      const form = await wbForm('编辑工作库', [
        {key:'name', label:'名称', type:'text', value:b.dataset.name, required:true},
        {key:'local_path', label:'本地路径', type:'text', value:b.dataset.path, required:true},
        {key:'git_repo', label:'Git 仓库（可选）', type:'text', value:b.dataset.git}
      ]);
      if(!form) return;
      try{
        await api('/api/me/workspaces/save', {method:'POST', body:JSON.stringify({
          id:b.dataset.ws, name:form.name, local_path:form.local_path, git_repo:form.git_repo||'', device_id:b.dataset.dev})});
        toast('已更新'); loadDevices();
      }catch(e){ toast('更新失败：'+e.message, true); }
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
  const form = await wbForm('添加工作库目录', [
    {key:'name', label:'工作库名称', type:'text', required:true, placeholder:'如：默认工作库 / 竞品素材'},
    {key:'local_path', label:'本地物理地址', type:'text', required:true, placeholder:'如 D:\\work\\ 或 /Users/xx/work/'},
    {key:'git_repo', label:'Git 仓库（可选，离线降级用）', type:'text', placeholder:'不填留空'}
  ]);
  if(!form) return;
  // 绑定到当前设备
  const cur = _devData && (_devData.devices||[]).find(x=>x.machine_id===_devData.current_machine_id);
  try{
    await api('/api/me/workspaces/save', {method:'POST', body:JSON.stringify({
      name:form.name, local_path:form.local_path, git_repo:form.git_repo||'', device_id: cur?cur.id:''
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

// 团队级集成授权（admin 在团队 Agent 页配，全团队共用）— 由 loadTeamAgent 调用
async function loadTeamIntegrations(d){
  const box = $('#teamIntegrationsBox');
  if(!box) return;
  const fs = (d && d.integrations && d.integrations.feishu) || {};
  const wc = (d && d.integrations && d.integrations.wecom) || {};
  const cfgTag = fs.configured
    ? `<span class="tag green" style="font-size:10px">已配置</span>`
    : `<span class="tag gray" style="font-size:10px">未配置</span>`;
  const wcTag = wc.configured
    ? `<span class="tag green" style="font-size:10px">已配置</span>`
    : `<span class="tag gray" style="font-size:10px">未配置</span>`;
  box.innerHTML = `
    <div style="border:1px solid var(--line);border-radius:12px;padding:16px;background:rgba(255,255,255,.7);max-width:560px">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
        <span style="font-size:15px;font-weight:700">飞书（Lark）</span>${cfgTag}
      </div>
      <div style="font-size:11.5px;color:var(--ink-3);margin-bottom:14px">
        自建应用凭据（开放平台→开发者后台→凭证与基础信息）。全团队共用一套，成员读飞书文档时自动使用。${fs.updated_at?('上次更新：'+h(fs.updated_at)):''}
      </div>
      <div style="margin-bottom:12px">
        <label style="font-size:12px;font-weight:600;color:var(--ink-2)">App ID</label>
        <input id="fsAppId" type="text" placeholder="cli_xxxxxxxx" value="${h(fs.app_id||'')}"
          style="width:100%;padding:9px 12px;border-radius:9px;border:1px solid var(--line);font-size:13px;font-family:ui-monospace,monospace;background:#fff;color:var(--ink);margin-top:5px">
      </div>
      <div style="margin-bottom:16px">
        <label style="font-size:12px;font-weight:600;color:var(--ink-2)">App Secret</label>
        <input id="fsAppSecret" type="text" placeholder="${fs.configured?'已保存（留空或不改则保留原值）':'输入 App Secret'}" value="${h(fs.app_secret||'')}"
          style="width:100%;padding:9px 12px;border-radius:9px;border:1px solid var(--line);font-size:13px;font-family:ui-monospace,monospace;background:#fff;color:var(--ink);margin-top:5px">
        <div style="font-size:11px;color:var(--ink-3);margin-top:4px">🔒 存服务器团队配置（integrations.json，已 gitignore），不进任何仓库、不发往前端明文。</div>
      </div>
      <div style="text-align:right"><button class="btn sm primary" id="saveFeishuBtn">保存飞书凭据</button></div>
    </div>

    <div style="border:1px solid var(--line);border-radius:12px;padding:16px;background:rgba(255,255,255,.7);max-width:560px;margin-top:14px">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
        <span style="font-size:15px;font-weight:700">企业微信（WeCom）</span>${wcTag}
      </div>
      <div style="font-size:11.5px;color:var(--ink-3);margin-bottom:14px">
        企微自建应用凭据（企业ID/应用ID + 应用 Secret）。全团队共用一套。${wc.updated_at?('上次更新：'+h(wc.updated_at)):''}
      </div>
      <div style="margin-bottom:12px">
        <label style="font-size:12px;font-weight:600;color:var(--ink-2)">Corp ID（企业ID/应用ID）</label>
        <input id="wcCorpId" type="text" placeholder="企业ID或应用ID" value="${h(wc.corp_id||'')}"
          style="width:100%;padding:9px 12px;border-radius:9px;border:1px solid var(--line);font-size:13px;font-family:ui-monospace,monospace;background:#fff;color:var(--ink);margin-top:5px">
      </div>
      <div style="margin-bottom:16px">
        <label style="font-size:12px;font-weight:600;color:var(--ink-2)">Corp Secret（应用 Secret）</label>
        <input id="wcCorpSecret" type="text" placeholder="${wc.configured?'已保存（留空或不改则保留原值）':'输入 Secret'}" value="${h(wc.corp_secret||'')}"
          style="width:100%;padding:9px 12px;border-radius:9px;border:1px solid var(--line);font-size:13px;font-family:ui-monospace,monospace;background:#fff;color:var(--ink);margin-top:5px">
        <div style="font-size:11px;color:var(--ink-3);margin-top:4px">🔒 存服务器团队配置（integrations.json，已 gitignore），不进任何仓库。</div>
      </div>
      <div style="text-align:right"><button class="btn sm primary" id="saveWecomBtn">保存企微凭据</button></div>
    </div>`;
  $('#saveFeishuBtn').onclick = async ()=>{
    const app_id = $('#fsAppId').value.trim();
    const secret = $('#fsAppSecret').value.trim();
    if(!app_id){ toast('请填 App ID', true); return; }
    try{
      const r = await api('/api/admin/team-agent/integration', {method:'POST', body:JSON.stringify({
        provider:'feishu', values:{app_id, app_secret: secret}})});
      toast(r.configured ? '✅ 飞书凭据已保存（全团队生效）' : '已保存（凭据尚不完整）');
      if(window.__wb) window.__wb.LOADED.teamagent=false;
      if(window.loadTeamAgent) window.loadTeamAgent();
    }catch(e){ toast('保存失败：'+e.message, true); }
  };
  $('#saveWecomBtn').onclick = async ()=>{
    const corp_id = $('#wcCorpId').value.trim();
    const corp_secret = $('#wcCorpSecret').value.trim();
    if(!corp_id){ toast('请填 Corp ID', true); return; }
    try{
      const r = await api('/api/admin/team-agent/integration', {method:'POST', body:JSON.stringify({
        provider:'wecom', values:{corp_id, corp_secret}})});
      toast(r.configured ? '✅ 企微凭据已保存（全团队生效）' : '已保存（凭据尚不完整）');
      if(window.__wb) window.__wb.LOADED.teamagent=false;
      if(window.loadTeamAgent) window.loadTeamAgent();
    }catch(e){ toast('保存失败：'+e.message, true); }
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
      ? entries.map((e,i)=>`<option value="${i}">${h(e.file)}</option>`).join('')
      : '<option value="">（无日志文件）</option>';
    bar.innerHTML = `
      <select id="logFileSel">${opts}</select>
      <input id="logFilter" placeholder="过滤关键字…">
      <button class="btn sm" id="logRefreshBtn">刷新</button>
      <button class="btn sm" id="logDownloadBtn">下载</button>`;
    const sel = bar.querySelector('#logFileSel');
    const filt = bar.querySelector('#logFilter');
    // 切换文件下拉 → 只渲染选中的那个日志文件
    sel.addEventListener('change', ()=>renderLogBox(entries, filt.value, sel.value));
    filt.addEventListener('input', ()=>renderLogBox(entries, filt.value, sel.value));
    bar.querySelector('#logRefreshBtn').onclick = ()=>{ _meLoaded.logs=false; loadMeSub('logs'); };
    bar.querySelector('#logDownloadBtn').onclick = ()=>{
      const idx = sel.value;
      const e = entries[+idx];
      if(!e){ toast('没有可下载的日志', true); return; }
      // 触发浏览器下载
      window.location.href = '/api/me/logs/download?file='+encodeURIComponent(e.file);
    };
  }
  renderLogBox(entries, '', '0');
}
function renderLogBox(entries, filter, selIdx){
  const box = $('#logBox');
  if(!box) return;
  if(!entries.length){ box.innerHTML = '<div class="lt">暂无日志文件</div>'; return; }
  // 只渲染选中的那个文件（selIdx 为下拉的索引）；缺省渲染第一个
  const idx = (selIdx!==undefined && selIdx!=='') ? (+selIdx) : 0;
  const e = entries[idx] || entries[0];
  const f = (filter||'').toLowerCase();
  const head = `<div class="lw">━━ ${h(e.file)} (${(e.size/1024).toFixed(1)}KB) ━━</div>`;
  let lines = e.tail||[];
  if(f) lines = lines.filter(l=>l.toLowerCase().includes(f));
  const body = lines.map(l=>`<div><span class="li">${h(l)}</span></div>`).join('') || '<div class="lt">（无匹配行）</div>';
  box.innerHTML = head + body;
}

})();
