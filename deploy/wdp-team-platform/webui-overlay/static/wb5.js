/* ============================================================
   WDP 团队工作台 · wb5.js
   通用 agent 对话组件（R38 归并 / R41 审核）
   - 对话式界面（参考对话模块）：消息流 + 输入框 + agent多轮调优
   - 明确关闭按钮，点遮罩不关闭（防误触）
   - agent 每轮可产出"当前方案"卡片，管理员满意后一键执行
   - 关闭对话框 = 清除后端对话缓存
   ============================================================ */
(function(){
'use strict';
const W = window.__wb;
if(!W){ console.error('wb5: __wb missing'); return; }
const {api, h, toast} = W;
const $ = s => document.querySelector(s);

// opts: {kind:'merge'|'review', title, icon, ref, renderProposal(prop)->html,
//        onExecute(prop, dlg)->Promise, executeLabel}
window.wbAgentDialog = function(opts){
  const overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(15,31,22,.45);backdrop-filter:blur(7px);z-index:2100;display:flex;align-items:center;justify-content:center;padding:20px';
  const card = document.createElement('div');
  card.style.cssText = 'background:linear-gradient(160deg,#fdfffe,#f3faf5);border:1px solid var(--line);border-radius:20px;box-shadow:0 24px 70px rgba(15,31,22,.28);width:min(940px,96vw);height:min(780px,94vh);display:flex;flex-direction:column;overflow:hidden';
  overlay.appendChild(card);
  document.body.appendChild(overlay);
  // 注意：不绑定遮罩点击关闭（用户明确要求必须走关闭按钮）

  let dialogId = null;
  let curProposal = null;
  let busy = false;

  card.innerHTML = `
    <div style="display:flex;align-items:center;gap:10px;padding:14px 18px;border-bottom:1px solid var(--line-2);flex-shrink:0">
      <span style="font-size:19px">${opts.icon||'🤖'}</span>
      <div style="flex:1">
        <div style="font-weight:700;font-size:15px">${h(opts.title||'Agent 协作')}</div>
        <div style="font-size:11px;color:var(--ink-3)">对话式协作 · 你的意见会实时影响 agent 的方案 · 关闭即清除本次对话</div>
      </div>
      <button class="ad-close" style="border:none;background:rgba(0,0,0,.05);width:30px;height:30px;border-radius:9px;cursor:pointer;font-size:15px;color:var(--ink-2)" title="关闭并清除对话">✕</button>
    </div>
    <div class="ad-msgs" style="flex:1;overflow-y:auto;padding:16px 18px;display:flex;flex-direction:column;gap:12px"></div>
    <div class="ad-prop" style="flex-shrink:0;display:none;border-top:1px solid var(--line-2);padding:10px 18px;background:rgba(22,163,74,.05);max-height:320px;overflow-y:auto"></div>
    <div style="flex-shrink:0;display:flex;gap:8px;padding:12px 18px;border-top:1px solid var(--line-2)">
      <textarea class="ad-input" rows="2" placeholder="和 agent 讨论调整方案，如：把标题改短一点 / 这两条不该合并…" style="flex:1;padding:12px 14px;border-radius:12px;border:1px solid var(--line);font-size:14px;min-height:52px;max-height:160px;resize:vertical;background:#fff;color:var(--ink);outline:none;font-family:inherit;line-height:1.55"></textarea>
      <button class="ad-send btn primary sm" style="align-self:flex-end">发送</button>
    </div>`;

  const msgsBox = card.querySelector('.ad-msgs');
  const propBox = card.querySelector('.ad-prop');
  const input = card.querySelector('.ad-input');
  const sendBtn = card.querySelector('.ad-send');

  function addMsg(role, html_){
    const div = document.createElement('div');
    if(role==='user'){
      div.style.cssText='align-self:flex-end;max-width:82%;background:linear-gradient(145deg,#22c55e,#16a34a);color:#fff;padding:9px 13px;border-radius:13px 13px 4px 13px;font-size:13px;line-height:1.6';
      div.textContent = html_;
    }else if(role==='agent'){
      div.style.cssText='align-self:flex-start;max-width:86%;background:#fff;border:1px solid var(--line-2);padding:10px 14px;border-radius:13px 13px 13px 4px;font-size:13px;line-height:1.7;color:var(--ink)';
      div.innerHTML = html_;
    }else{
      div.style.cssText='align-self:center;font-size:11px;color:var(--ink-3)';
      div.innerHTML = html_;
    }
    msgsBox.appendChild(div);
    msgsBox.scrollTop = msgsBox.scrollHeight;
    return div;
  }
  function mdLite(t){
    return h(t).replace(/\*\*(.+?)\*\*/g,'<b>$1</b>').replace(/\n/g,'<br>');
  }
  function setBusy(b){
    busy = b;
    input.disabled = b; sendBtn.disabled = b;
    input.style.opacity = b?'.55':''; sendBtn.style.opacity = b?'.5':'';
    input.placeholder = b ? 'agent 思考中…' : '和 agent 讨论调整方案，如：把标题改短一点 / 这两条不该合并…';
  }
  function showProposal(prop){
    curProposal = prop;
    if(!prop){ propBox.style.display='none'; return; }
    propBox.style.display='block';
    propBox.innerHTML = `<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
        <span style="font-size:12px;font-weight:700;color:var(--brand-strong)">📋 当前方案</span>
        <span style="font-size:10px;color:var(--ink-3)">继续对话可让 agent 调整；满意后执行</span>
      </div>` + (opts.renderProposal ? opts.renderProposal(prop) : `<pre style="font-size:11px">${h(JSON.stringify(prop,null,2))}</pre>`);
    // 执行按钮由 renderProposal 内部放置（带 class ad-exec），统一绑定
    propBox.querySelectorAll('.ad-exec').forEach(b=>b.onclick = async ()=>{
      if(busy) return;
      b.disabled = true; b.textContent = '执行中…';
      try{
        await opts.onExecute(curProposal, {close, addSys:(t)=>addMsg('sys',t), el:b});
        // #5：执行成功后互斥——同方案的所有动作按钮（通过/驳回）一并禁用，防止二次操作
        propBox.querySelectorAll('.ad-exec').forEach(x=>{
          x.disabled = true; x.style.opacity='.45'; x.style.cursor='not-allowed';
        });
        b.textContent = '✓ 已执行';
      }catch(e){
        toast('执行失败：'+e.message, true);
        b.disabled = false; b.textContent = opts.executeLabel || '✓ 执行方案';
      }
    });
  }
  async function start(){
    setBusy(true);
    addMsg('sys','⚙️ agent 正在分析（约10-30秒）…');
    try{
      const d = await api('/api/admin/agent-dialog/start', {method:'POST', body:JSON.stringify({kind:opts.kind, ref:opts.ref||{}})});
      dialogId = d.dialog_id;
      msgsBox.lastChild.remove();
      addMsg('agent', mdLite(d.reply||'(无回复)'));
      showProposal(d.proposal);
    }catch(e){
      msgsBox.lastChild.remove();
      addMsg('sys', `<span style="color:var(--danger)">启动失败：${h(e.message)} </span>`);
    }
    setBusy(false);
    input.focus();
  }
  async function send(){
    if(busy) return;
    const t = (input.value||'').trim();
    if(!t) return;
    addMsg('user', t);
    input.value='';
    setBusy(true);
    const thinking = addMsg('sys','⚙️ agent 思考中…');
    try{
      const d = await api('/api/admin/agent-dialog/send', {method:'POST', body:JSON.stringify({dialog_id:dialogId, message:t})});
      thinking.remove();
      addMsg('agent', mdLite(d.reply||'(无回复)'));
      if(d.proposal) showProposal(d.proposal);
    }catch(e){
      thinking.remove();
      addMsg('sys', `<span style="color:var(--danger)">发送失败：${h(e.message)}</span>`);
    }
    setBusy(false);
    input.focus();
  }
  function close(){
    if(dialogId){ api('/api/admin/agent-dialog/close', {method:'POST', body:JSON.stringify({dialog_id:dialogId})}).catch(()=>{}); }
    overlay.remove();
  }
  card.querySelector('.ad-close').onclick = ()=>close();
  sendBtn.onclick = send;
  input.addEventListener('keydown', e=>{
    if(e.key==='Enter' && !e.shiftKey){ e.preventDefault(); send(); }
  });
  start();
  return {close};
};

// ── R38：归并 agent 对话（决策中心 + 信号tab共用）─────────────────────────
window.wbOpenMergeDialog = function(){
  window.wbAgentDialog({
    kind: 'merge', icon: '🤖', title: '智能归并 · Agent 协作',
    executeLabel: '✓ 确认归并',
    renderProposal(prop){
      const groups = prop.groups || [];
      if(!groups.length) return '<div style="font-size:12px;color:var(--ink-3)">agent 认为当前没有可归并的组</div>';
      return groups.map((g,i)=>`
        <div style="border:1px solid var(--brand);border-radius:10px;padding:10px 12px;margin-bottom:8px;background:#fff">
          <div style="font-size:12px;font-weight:700;color:var(--brand-strong)">组${i+1}：${h(g.suggested_title||'')} <span style="font-weight:400;color:var(--ink-3)">紧急度${h(g.suggested_urgency||'中')}</span></div>
          <div style="font-size:11px;color:var(--ink-2);margin:4px 0">📎 ${(g.signal_ids||[]).map(h).join(' ＋ ')}</div>
          <div style="font-size:11px;color:var(--ink-3);margin-bottom:6px">${h(g.suggested_body||'')}</div>
          <button class="ad-exec btn sm primary" data-gi="${i}">✓ 确认归并这组</button>
        </div>`).join('');
    },
    async onExecute(prop, dlg){
      // 每组独立执行：按钮上有 data-gi
      const gi = +((dlg.el && dlg.el.dataset.gi) || 0);
      const g = (prop.groups||[])[gi];
      if(!g) return;
      await api('/api/knowledge/merge', {method:'POST', body:JSON.stringify({
        ids: g.signal_ids, title: g.suggested_title, body: g.suggested_body||'', urgency: g.suggested_urgency||''})});
      api('/api/admin/team-agent/record-decision', {method:'POST', body:JSON.stringify({
        kind:'merge', entry:{signal_ids:g.signal_ids, suggested_title:g.suggested_title,
          final_title:g.suggested_title, adopted:true, reason:g.reason||'', via:'dialog'}})}).catch(()=>{});
      dlg.addSys(`✅ 已归并为新信号「${h(g.suggested_title||'')}」（决策已记录，agent 将学习）`);
      dlg.el.textContent = '✓ 已归并'; 
      if(W.LOADED) W.LOADED.board=false;
      if(window.wbRefreshRailCnt) window.wbRefreshRailCnt();
      if(W.loadSignals) W.loadSignals();
    }
  });
};

// ── R41：审核 agent 对话（决策中心待审入库）──────────────────────────────
window.wbOpenReviewDialog = function(item){
  window.wbAgentDialog({
    kind: 'review', icon: '🧐', title: `审核协作 · ${item.title||item.file||''}`,
    ref: {user: item._profile || item.profile, file: item.file},
    renderProposal(prop){
      const recColor = prop.recommendation==='通过' ? 'var(--brand-strong)'
        : prop.recommendation==='建议驳回' ? 'var(--danger)' : '#d97706';
      return `<div style="border:1px solid var(--line);border-radius:10px;padding:10px 12px;background:#fff;font-size:12px;line-height:1.8">
        <div style="font-weight:700;color:var(--ink-3);font-size:11px;margin-bottom:2px">🧐 AI 分析（仅供参考，决定权在你）</div>
        <div><b>建议归类：</b>${h(prop.suggested_category||'—')} · <b>重复风险：</b>${h(prop.duplicate_risk||'—')}${prop.duplicate_of?` (疑似与 ${h(prop.duplicate_of)} 重复)`:''}</div>
        <div><b>质量：</b>${h(prop.quality_notes||'—')}</div>
        ${prop.suggested_owner?`<div><b>建议负责人：</b><span style="color:var(--brand-strong);font-weight:700">${h(prop.suggested_owner)}</span>（按职责匹配）</div>`:''}
        <div><b>AI 倾向：</b><span style="color:${recColor};font-weight:700">${h(prop.recommendation||'—')}</span> — ${h(prop.reason||'')}</div>
        <div style="display:flex;gap:8px;margin-top:8px">
          <button class="ad-exec btn sm primary" data-act="approve">✓ 入库</button>
          <button class="ad-exec btn sm" data-act="reject" style="color:var(--danger);border-color:var(--danger)">↩ 驳回</button>
        </div></div>`;
    },
    async onExecute(prop, dlg){
      const act = dlg.el && dlg.el.dataset.act;
      const adv = (prop.recommendation||'') + (prop.reason ? ('·'+prop.reason) : '');
      if(act === 'approve'){
        const d = await api('/api/review/approve', {method:'POST', body:JSON.stringify({
          user: item._profile || item.profile, file: item.file})});
        api('/api/admin/team-agent/record-decision', {method:'POST', body:JSON.stringify({
          kind:'review', entry:{title:item.title, category:item.category, decision:'通过', ai_advice:adv, reason:'', via:'dialog'}})}).catch(()=>{});
        dlg.addSys(`✅ 已入库到 ${h(d.final_path||'')}（决策已记录）`);
      }else{
        const reason = prop.suggested_reject_reason || prop.reason || '不符合入库标准';
        await api('/api/review/reject', {method:'POST', body:JSON.stringify({
          user: item._profile || item.profile, file: item.file, reason})});
        api('/api/admin/team-agent/record-decision', {method:'POST', body:JSON.stringify({
          kind:'review', entry:{title:item.title, category:item.category, decision:'驳回', ai_advice:adv, reason, via:'dialog'}})}).catch(()=>{});
        dlg.addSys(`↩ 已驳回，理由已通知提交人：${h(reason)}`);
      }
      dlg.el.disabled = true;
      if(window.loadReview) window.loadReview();
      if(window.wbRefreshRailCnt) window.wbRefreshRailCnt();
    }
  });
};

// ── 团队规则 agent 对话（团队 Agent 页「规则助手」）──────────────────────
window.wbOpenRulesDialog = function(){
  window.wbAgentDialog({
    kind: 'rules', icon: '🤖', title: '团队规则助手 · 对话共创',
    ref: {},
    executeLabel: '✓ 应用并发布',
    renderProposal(prop){
      const soul = prop.soul || '';
      const preview = soul.length > 600 ? soul.slice(0,600)+'…' : soul;
      return `<div style="border:1px solid var(--line);border-radius:10px;padding:10px 12px;background:#fff;font-size:12px;line-height:1.7">
        <div style="font-weight:700;color:var(--ink-3);font-size:11px;margin-bottom:4px">📋 新版团队规则（预览，应用后写入母本并发布给全体成员）</div>
        <div style="max-height:220px;overflow-y:auto;white-space:pre-wrap;color:var(--ink);font-size:12px">${h(preview)}</div>
        <div style="display:flex;gap:8px;margin-top:8px">
          <button class="ad-exec btn sm primary" data-act="apply">✓ 应用并发布</button>
        </div></div>`;
    },
    async onExecute(prop, dlg){
      if(!prop.soul){ dlg.addSys('⚠️ 暂无可应用的规则文本'); return; }
      const r = await api('/api/admin/team-agent/apply-rules', {method:'POST', body:JSON.stringify({soul: prop.soul})});
      dlg.addSys(`✅ 已写入团队规则母本并发布（${r.message||'成员 agent 已更新'}）`);
      // 刷新团队 Agent 页文本框
      if(window.loadTeamAgent){ if(window.__wb) window.__wb.LOADED.teamagent=false; window.loadTeamAgent(); }
    }
  });
};

})();
