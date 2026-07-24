/* ============================================================
   WDP 团队工作台 · 前端主逻辑（wb.js）
   独立客制化前端，接 web-ui 后端真实 API：
     认证    /api/auth/me  /api/auth/logout
     工作台  /api/knowledge/{signals,requirements,designs,stats,item}
     审核    /api/review/{list,item,approve,reject}
     成员    /api/admin/users{,/create,/reset_password,/set_active,/kick}
     个人    /api/me/{agent,workspace,memory,logs,soul,upload}
     对话    /api/chat/start + EventSource /api/chat/stream
   ============================================================ */
(function(){
'use strict';

const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);
function h(s){return (s==null?'':String(s)).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function tag(txt,color){return `<span class="tag ${color}">${h(txt)}</span>`;}
function urgColor(u){return u==='高'?'red':u==='中'?'amber':'gray';}
function stColor(s){return s==='待确认'||s==='待triage'?'amber':s==='已确认'?'blue':s==='已转需求'?'green':'gray';}
// #7：面向人的状态显示映射（"待triage"是agent术语，人看着像乱码）
function stLabel(s){ return (!s||s==='待triage') ? '待处理' : s; }
// #7：正文轻量渲染——md 井号/星号/横线是"面向agent的标识符"，转成人读的排版
function bodyHtml(text){
  if(!text) return '<span style="color:var(--ink-3)">（无正文）</span>';
  const esc = h(text);
  return esc.split(/\n/).map(line=>{
    const t = line.trim();
    if(!t) return '';
    if(/^#{1,6}\s/.test(t)) return `<div style="font-weight:700;color:var(--brand-strong);margin:10px 0 4px">${t.replace(/^#{1,6}\s*/,'')}</div>`;
    if(/^[-*]\s/.test(t))   return `<div style="padding-left:14px;position:relative"><span style="position:absolute;left:2px">•</span>${t.replace(/^[-*]\s*/,'')}</div>`;
    if(/^\d+[.、]\s/.test(t)) return `<div style="padding-left:14px">${t}</div>`;
    if(/^---+$/.test(t)) return '<hr style="border:none;border-top:1px dashed var(--line);margin:8px 0">';
    return `<div>${t.replace(/\*\*([^*]+)\*\*/g,'<b>$1</b>')}</div>`;
  }).join('');
}

// ── CSRF + fetch 封装 ──
const CSRF = window.__CSRF_TOKEN__ || '';
async function api(path, opts){
  opts = opts || {};
  opts.credentials = 'same-origin';
  opts.headers = opts.headers || {};
  if(opts.method && opts.method !== 'GET'){
    opts.headers['Content-Type'] = opts.headers['Content-Type'] || 'application/json';
    if(CSRF) opts.headers['X-CSRF-Token'] = CSRF;
  }
  const r = await fetch(path, opts);
  let data = null;
  try{ data = await r.json(); }catch(_){}
  if(!r.ok){
    const err = new Error((data && data.error) || ('HTTP '+r.status));
    err.status = r.status; err.data = data;
    throw err;
  }
  return data;
}

// ── 全局状态 ──
let USER = null;          // {username, profile, role}
let IS_ADMIN = false;
let WORKSPACE = null;     // 个人 workspace 目录（chat 需要）

// ══════════════════════════════════════════════
//  启动：拉当前用户
// ══════════════════════════════════════════════
async function boot(){
  try{
    const d = await api('/api/auth/me');
    if(d && d.multiuser && d.user){
      USER = d.user; IS_ADMIN = (d.user.role === 'admin');
    } else if(d && d.multiuser === false){
      // 单用户模式：视作管理员
      USER = {username:'admin', role:'admin', profile:'default'};
      IS_ADMIN = true;
    } else {
      location.href = '/login'; return;
    }
  }catch(e){
    if(e.status === 401){ location.href = '/login'; return; }
    console.error('boot failed', e);
  }
  applyRole();
  bindNav();
  bindWorkbenchTabs();
  if(window.bindMeNav) window.bindMeNav();
  // 解析个人 workspace 目录（chat 需要合法 workspace）
  try{
    const me = await api('/api/me/agent');
    if(me && me.profile_home){
      const sep = me.profile_home.indexOf('/')>=0 ? '/' : '\\';
      WORKSPACE = me.profile_home + sep + 'workspace';
      window.__wb.WORKSPACE = WORKSPACE;
      // 幂等加入 saved workspace 列表（首次登录自动就绪；已存在则后端返回 already，忽略）
      try{
        await api('/api/workspaces/add', {method:'POST', body:JSON.stringify({
          path: WORKSPACE, name: '个人工作库', create: true
        })});
      }catch(_){ /* already in list */ }
    }
  }catch(_){}
  if(window.initChat) window.initChat();
  show('chat');
  // 启动即同步边栏工作台计数（M1，不用等进工作台）
  if(window.wbRefreshRailCnt) window.wbRefreshRailCnt();
  if(window.wbRefreshReviewCnt) window.wbRefreshReviewCnt();
}

function applyRole(){
  $$('.admin-only').forEach(el => el.style.display = IS_ADMIN ? '' : 'none');
  const name = USER.username || '?';
  const roleTxt = IS_ADMIN ? '管理员' : '成员';
  if($('#chipName')) $('#chipName').textContent = name;
  if($('#chipRole')) $('#chipRole').textContent = roleTxt;
  if($('#avatarEl')) $('#avatarEl').textContent = name[0].toUpperCase();
}

// ══════════════════════════════════════════════
//  视图切换
// ══════════════════════════════════════════════
const TITLES = {
  chat:['对话','和你的专属 agent 协作'],
  board:['团队工作台','知识库沉淀与产研协作'],
  review:['决策中心','入库审核与归并决策'],
  members:['成员管理','账号与权限'],
  teamagent:['团队 Agent','团队规则 · 默认模型 · 归并规则 · 定时任务'],
  teammembers:['团队成员','产研团队档案与能力画像'],
  me:['个人中心','配置你的 agent 与空间']
};
const VIEWS = {chat:'#viewChat',board:'#viewBoard',review:'#viewReview',members:'#viewMembers',teamagent:'#viewTeamAgent',teammembers:'#viewTeamMembers',me:'#viewMe'};
const LOADED = {};

function show(v){
  Object.values(VIEWS).forEach(s => { const el=$(s); if(el) el.classList.add('hidden'); });
  const el = $(VIEWS[v]); if(el) el.classList.remove('hidden');
  $$('.rail-btn[data-view]').forEach(b => b.classList.toggle('active', b.dataset.view===v));
  const [t,c] = TITLES[v] || ['',''];
  if($('#pageTitle')) $('#pageTitle').textContent = t;
  if($('#pageCrumb')) $('#pageCrumb').textContent = c;
  // 懒加载
  if(v==='board' && !LOADED.board){ loadWorkbench(); LOADED.board=true; }
  else if(v==='review'){ if(window.loadReview) window.loadReview(); LOADED.review=true; }  // #4：每次进入都拉最新待审（不做一次性懒加载，保证提交后即时可见）
  else if(v==='members' && !LOADED.members){ if(window.loadMembers) window.loadMembers(); LOADED.members=true; }
  else if(v==='teamagent' && !LOADED.teamagent){ if(window.loadTeamAgent) window.loadTeamAgent(); LOADED.teamagent=true; }
  else if(v==='teammembers' && !LOADED.teammembers){ if(window.wbLoadTeam) window.wbLoadTeam(); LOADED.teammembers=true; }
  else if(v==='me' && !LOADED.me){ if(window.loadMe) window.loadMe(); LOADED.me=true; }
  else if(v==='chat' && !LOADED.chat){ if(window.loadChat) window.loadChat(); LOADED.chat=true; }
  // 2c修复：切回对话视图时，若当前会话正在流式，刷新思考态渲染+置灰态（防切走期间状态丢失）
  else if(v==='chat' && window.wbChatResume){ window.wbChatResume(); }
}

function bindNav(){
  $$('.rail-btn[data-view]').forEach(b => b.addEventListener('click', ()=>show(b.dataset.view)));
  // 设置按钮 = 登出（原型的设置暂作登出入口）
  const sb = $('.rail-btn.settings-btn');
  if(sb) sb.addEventListener('click', async ()=>{
    if(!(await wbConfirm('退出登录？'))) return;
    try{ await api('/api/auth/logout', {method:'POST'}); }catch(_){}
    location.href = '/login';
  });
}

// ══════════════════════════════════════════════
//  工作台三 tab（接 /api/knowledge/*）
// ══════════════════════════════════════════════
function bindWorkbenchTabs(){
  $$('#viewBoard .tab').forEach(t => t.addEventListener('click', ()=>{
    $$('#viewBoard .tab').forEach(x=>x.classList.remove('active'));
    t.classList.add('active');
    ['signals','requirements','designs','decisions','mine','library'].forEach(k =>{
      const el = $('#tab-'+k); if(el) el.classList.toggle('hidden', k!==t.dataset.tab);
    });
    // 懒加载 library（决策已并入需求，不再独立 tab）
    if(t.dataset.tab==='library' && window.wbLoadLibrary) window.wbLoadLibrary();
    // #2：我的工作项 tab
    if(t.dataset.tab==='mine' && window.wbLoadMine) window.wbLoadMine();
  }));
}

async function loadWorkbench(){
  // 拉 stats 更新 tab 徽标 + 顶部统计 + 边栏计数
  try{
    const st = await api('/api/knowledge/stats');
    const cats = st.categories || {};
    setBadge('signals', cats.signals && cats.signals.active_count);
    setBadge('requirements', cats.requirements && cats.requirements.active_count);
    setBadge('designs', cats.designs && cats.designs.active_count);
    // R3：边栏工作台数字只算 信号+需求+设计的活跃数（已流转的不重复计数，保证唯一性）
    const boardTotal = (cats.signals&&cats.signals.active_count||0)+(cats.requirements&&cats.requirements.active_count||0)+(cats.designs&&cats.designs.active_count||0);
    updateRailBoardCnt(boardTotal);
    renderSignalStats(cats.signals);
  }catch(e){ console.warn('stats failed', e); }
  loadSignals();
  loadRequirements();
  loadDesigns();
}

// 边栏「工作台」计数实时同步（M1）：任何数据增删后调用
function updateRailBoardCnt(total){
  const el = document.getElementById('railBoardCnt');
  if(el) el.textContent = (total==null?0:total);
}
// 刷新边栏计数 + tab 徽标（R13：数据增删/流转后调用，同步所有计数）
window.wbRefreshRailCnt = async function(){
  try{
    const st = await api('/api/knowledge/stats');
    const c = st.categories || {};
    setBadge('signals', c.signals && c.signals.active_count);
    setBadge('requirements', c.requirements && c.requirements.active_count);
    setBadge('designs', c.designs && c.designs.active_count);
    const boardTotal = (c.signals&&c.signals.active_count||0)+(c.requirements&&c.requirements.active_count||0)+(c.designs&&c.designs.active_count||0);
    updateRailBoardCnt(boardTotal);
    if(c.signals) renderSignalStats(c.signals);
    // 需求tab当前可见时，重载需求列表以同步统计条（删除/流转后实时）
    const reqTab = document.getElementById('tab-requirements');
    if(reqTab && !reqTab.classList.contains('hidden') && typeof loadRequirements==='function') loadRequirements();
  }catch(_){}
};
// R5：刷新入库审核待审数字徽标（admin）
window.wbRefreshReviewCnt = async function(){
  const el = document.getElementById('railReviewCnt');
  if(!el || !IS_ADMIN) return;
  try{
    const d = await api('/api/review/list');
    const n = (d.items||[]).length;
    if(n>0){ el.textContent = n; el.style.display=''; }
    else { el.style.display='none'; }
  }catch(_){ el.style.display='none'; }
};

function setBadge(tab, n){
  const el = document.querySelector(`#viewBoard .tab[data-tab="${tab}"] .badge`);
  if(el) el.textContent = (n==null?0:n);
}

function renderSignalStats(sig){
  const box = $('#signalStatGrid');
  if(!box || !sig) return;
  const dist = sig.status_distribution || {};
  const active = sig.active_count!=null ? sig.active_count : (sig.count||0);
  const pending = (dist['待triage']||0) + (dist['待确认']||0);
  const converted = dist['已转需求'] || 0;
  box.innerHTML = `
    <div class="stat"><div class="num">${active}</div><div class="lbl">池内信号</div></div>
    <div class="stat"><div class="num">${pending}</div><div class="lbl">待确认</div><div class="trend" style="color:var(--amber)">需人工校验</div></div>
    <div class="stat"><div class="num">${converted}</div><div class="lbl">已转需求</div><div class="trend" style="color:var(--brand-strong)">已流转</div></div>
    <div class="stat"><div class="num" id="sigHighCnt">—</div><div class="lbl">高紧急待处理</div><div class="trend" style="color:var(--danger)">优先跟进</div></div>`;
}

let _sigFilter = {};  // {status, source, category, urgency}
let _showFlowed = false;  // R8：是否显示已流转(已转需求/已归档)的信号
async function loadSignals(){
  const tb = $('#signalRows');
  if(!tb) return;
  tb.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--ink-3);padding:24px">加载中…</td></tr>';
  try{
    const qs = new URLSearchParams();
    if(_sigFilter.status) qs.set('status', _sigFilter.status);
    if(_sigFilter.source) qs.set('source', _sigFilter.source);
    const d = await api('/api/knowledge/signals' + (qs.toString()?'?'+qs.toString():''));
    let items = d.items || [];
    // 前端补充筛选（category/urgency 后端没有专门参数）
    if(_sigFilter.category) items = items.filter(x=>x.category===_sigFilter.category);
    if(_sigFilter.urgency) items = items.filter(x=>x.urgency===_sigFilter.urgency);
    // R8/R14：信号转需求/归并后从池子流转走，默认隐藏"已转需求/已合并"（除非开"显示已流转"或明确按该状态筛选）
    const flowedOut = items.filter(x=>x.status==='已转需求'||x.status==='已合并');
    if(!_showFlowed && !_sigFilter.status){
      items = items.filter(x=>x.status!=='已转需求'&&x.status!=='已合并');
    }
    // #1：统计卡"高紧急待处理" = 池内(未流转)且紧急度=高
    const hc = $('#sigHighCnt');
    if(hc){ hc.textContent = (d.items||[]).filter(x=>x.urgency==='高'&&x.status!=='已转需求'&&x.status!=='已合并'&&x.status!=='已归档').length; }
    const filterHint = Object.keys(_sigFilter).length ? ` · 筛选中(${Object.values(_sigFilter).filter(Boolean).join('/')})` : '';
    const hintEl = document.querySelector('#tab-signals .panel-head .hint');
    if(hintEl){ hintEl.innerHTML = '点击行展开详情' + filterHint
      + (flowedOut.length?` · <a href="#" id="toggleFlowed" style="color:var(--brand-strong)">${_showFlowed?'隐藏':'显示'}已流转(${flowedOut.length})</a>`:'');
      const tf = hintEl.querySelector('#toggleFlowed');
      if(tf) tf.onclick = (e)=>{ e.preventDefault(); _showFlowed = !_showFlowed; loadSignals(); };
    }
    if(!items.length){ tb.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--ink-3);padding:24px">无匹配信号</td></tr>'; return; }
    tb.innerHTML = items.map((x,i)=>{
      const idv = x.id || x._file;
      return `<tr class="exp-row" data-id="${h(idv)}">
        <td style="color:var(--ink-3)"><span class="caret">▶</span>${h(x.date||'—')}</td>
        <td style="font-weight:600;max-width:300px">${h(x.title||'(无标题)')}</td>
        <td>${tag(x.source||'—','gray')}</td>
        <td>${tag(x.category||'—','blue')}</td>
        <td>${tag(x.urgency||'—',urgColor(x.urgency))}</td>
        <td>${tag(x.confidence||'—','green')}</td>
        <td>${tag(stLabel(x.status),stColor(x.status))}</td></tr>
      <tr class="exp-detail" data-id="${h(idv)}"><td colspan="7"><div class="detail-box" data-loading="1">
        <div style="color:var(--ink-3);font-size:12px">展开加载详情…</div>
      </div></td></tr>`;
    }).join('');
    tb.querySelectorAll('.exp-row').forEach(row => row.addEventListener('click', ()=>toggleSignalDetail(row)));
  }catch(e){
    tb.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--danger);padding:24px">加载失败：${h(e.message)}</td></tr>`;
  }
}

async function toggleSignalDetail(row){
  const id = row.dataset.id;
  const open = row.classList.toggle('open');
  const det = document.querySelector(`#signalRows .exp-detail[data-id="${CSS.escape(id)}"]`);
  if(!det) return;
  det.classList.toggle('show', open);
  if(open){
    const box = det.querySelector('.detail-box');
    if(box && box.dataset.loading === '1'){
      try{
        const d = await api('/api/knowledge/item?type=signals&id='+encodeURIComponent(id));
        const it = d.item || {};
        box.dataset.loading = '0';
        box.innerHTML = `
          <div class="sec"><div class="sec-t">📄 信号内容</div><div class="sec-b">${bodyHtml(it._body||'')}</div></div>
          <div class="sec"><div class="sec-t">🔑 关键信息</div><div class="kv">
            <div><div class="k">信号编号</div><div class="v">${h(it.id||'—')}</div></div>
            <div><div class="k">相关模块</div><div class="v">${h(it.related_module||'—')}</div></div>
            <div><div class="k">来源说明</div><div class="v">${h(it.source_ref||it.source||'—')}</div></div>
            <div><div class="k">文件</div><div class="v" style="font-family:monospace;font-size:11px">${h(it._file||'—')}</div></div>
          </div></div>
          ${it.raw_excerpt ? `<div class="sec"><div class="sec-t">💬 原始信息</div><div class="raw">"${h(it.raw_excerpt)}"</div></div>` : ''}
          <div class="sec" id="trace-signals-${h(id)}"><div class="sec-t">🔗 追溯</div><div class="sec-b" style="color:var(--ink-3);font-size:12px">加载中…</div></div>
          ${IS_ADMIN ? `<div class="detail-actions">
            <button class="btn sm primary" data-act="to-req" data-id="${h(id)}">＋ 沉淀为需求</button>
            <button class="btn sm" data-act="mark" data-id="${h(id)}">标记已确认</button>
            <button class="btn sm" data-act="sig-assign" data-id="${h(id)}">指派确认人</button>
            <button class="btn sm" data-act="sig-delete" data-id="${h(id)}" data-title="${h(it.title||'')}" style="color:var(--danger);border-color:var(--danger)">🗑 删除</button>
          </div>` : ''}`;
        if(window.wbLoadTraces) window.wbLoadTraces('signals', id);
        if(IS_ADMIN) bindSignalAdminActions(box);
      }catch(e){
        box.innerHTML = `<div style="color:var(--danger)">加载失败：${h(e.message)}</div>`;
      }
    }
  }
}

function bindSignalAdminActions(box){
  box.querySelectorAll('[data-act="mark"]').forEach(b => b.addEventListener('click', async (e)=>{
    e.stopPropagation();
    try{
      await api('/api/admin/knowledge/update', {method:'POST', body:JSON.stringify({
        type:'signals', id:b.dataset.id, updates:{status:'已确认'}, note:'工作台标记已确认'
      })});
      toast('已标记为已确认'); LOADED.board=false; if(window.wbRefreshRailCnt)window.wbRefreshRailCnt(); loadSignals();
    }catch(err){ toast('操作失败：'+err.message, true); }
  }));
  box.querySelectorAll('[data-act="to-req"]').forEach(b => b.addEventListener('click', async (e)=>{
    e.stopPropagation();
    if(window.wbSignalToReq) window.wbSignalToReq(b.dataset.id);
  }));
  box.querySelectorAll('[data-act="sig-assign"]').forEach(b => b.addEventListener('click', (e)=>{
    e.stopPropagation();
    if(window.wbSignalLifecycle) window.wbSignalLifecycle('assign', b.dataset.id);
  }));
  box.querySelectorAll('[data-act="sig-delete"]').forEach(b => b.addEventListener('click', (e)=>{
    e.stopPropagation();
    if(window.wbDeleteItem) window.wbDeleteItem('signals', b.dataset.id, b.dataset.title, ()=>{ LOADED.board=false; if(window.wbRefreshRailCnt)window.wbRefreshRailCnt(); loadSignals(); });
  }));
}

let _reqFilter = {};  // {status, priority, owner}
async function loadRequirements(){
  const tb = $('#requirementRows');
  if(!tb) return;
  tb.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--ink-3);padding:24px">加载中…</td></tr>';
  try{
    const d = await api('/api/knowledge/requirements');
    let items = d.items || [];
    // 已关闭的默认不显示在活跃池（流转出池）
    const closed = items.filter(x=>x.status==='已关闭');
    if(!_reqFilter.status) items = items.filter(x=>x.status!=='已关闭');
    if(_reqFilter.status) items = items.filter(x=>x.status===_reqFilter.status);
    if(_reqFilter.priority) items = items.filter(x=>x.priority===_reqFilter.priority);
    if(_reqFilter.owner) items = items.filter(x=>(x.owner||'')===_reqFilter.owner);
    renderReqStats(d.items||[]);
    const hintEl = document.querySelector('#tab-requirements .panel-head .hint');
    if(hintEl){
      const fh = Object.keys(_reqFilter).length?` · 筛选中(${Object.values(_reqFilter).filter(Boolean).join('/')})`:'';
      hintEl.innerHTML = '点击行展开详情、溯源与决策背景'+fh
        + (closed.length&&!_reqFilter.status?` · <a href="#" id="toggleReqClosed" style="color:var(--brand-strong)">显示已关闭(${closed.length})</a>`:'');
      const tc = hintEl.querySelector('#toggleReqClosed');
      if(tc) tc.onclick=(e)=>{ e.preventDefault(); _reqFilter.status='已关闭'; loadRequirements(); };
    }
    if(!items.length){ tb.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--ink-3);padding:24px">无匹配需求</td></tr>'; return; }
    tb.innerHTML = items.map(c=>{
      const idv = c.id||c._file;
      const pri = c.priority||'';
      const pc = pri==='P0'?'red':pri==='P1'?'amber':'gray';
      const sig = Array.isArray(c.source_signals)?c.source_signals.join(', '):(c.source_signals||'—');
      return `<tr class="exp-row" data-id="${h(idv)}">
        <td style="color:var(--ink-3)"><span class="caret">▶</span>${h(c.date||'—')}</td>
        <td style="font-weight:600;max-width:280px">${h(c.title||'(无标题)')}</td>
        <td>${pri?tag(pri,pc):'—'}</td>
        <td>${tag(c.status||'待校验',reqStColor(c.status))}</td>
        <td>${h(c.owner||'未分配')}</td>
        <td>${tag(c.related_module||'—','blue')}</td>
        <td style="color:var(--ink-3)">${h(c.target_release||'—')}</td></tr>
      <tr class="exp-detail" data-id="${h(idv)}"><td colspan="7"><div class="detail-box">
        <div class="row"><span class="k">业务价值</span><span>${h(c.business_value||'—')}</span></div>
        <div class="row"><span class="k">溯源信号</span><span>${h(sig)}</span></div>
        <div class="row trace-row" data-req="${h(idv)}"><span class="k">🔗 追溯</span><span style="color:var(--ink-3);font-size:11px">展开时加载…</span></div>
        <div class="decision-bg" data-req="${h(idv)}" style="display:none;margin-top:8px;padding:10px 12px;background:rgba(180,140,40,.06);border:1px solid rgba(180,140,40,.2);border-radius:10px"></div>
        ${IS_ADMIN ? `<div class="detail-actions" style="margin-top:10px;padding-top:10px;border-top:1px dashed var(--line);display:flex;flex-wrap:wrap;gap:6px">
          <button class="btn sm" data-req-act="status" data-id="${h(idv)}" data-status="${h(c.status||'')}">改状态</button>
          <button class="btn sm" data-req-act="priority" data-id="${h(idv)}" data-priority="${h(c.priority||'')}">改优先级</button>
          <button class="btn sm" data-req-act="assign" data-id="${h(idv)}" data-owner="${h(c.owner||'')}">分配</button>
          <button class="btn sm" data-req-act="notify" data-id="${h(idv)}" data-owner="${h(c.owner||'')}" data-title="${h(c.title||'')}">通知</button>
          <button class="btn sm" data-req-act="urge" data-id="${h(idv)}" data-owner="${h(c.owner||'')}" data-title="${h(c.title||'')}">催办</button>
          <button class="btn sm" data-req-act="close" data-id="${h(idv)}">关闭</button>
          <button class="btn sm" data-req-act="delete" data-id="${h(idv)}" data-title="${h(c.title||'')}" style="color:var(--danger);border-color:var(--danger)">🗑 删除</button>
        </div>` : ''}
      </div></td></tr>`;
    }).join('');
    bindExpandRows(tb, (idv, detailBox)=>{
      const tr = detailBox.querySelector('.trace-row');
      if(tr && !tr.dataset.loaded){ tr.dataset.loaded='1'; if(window.wbLoadReqTrace) window.wbLoadReqTrace(idv, tr); }
      const dbg = detailBox.querySelector('.decision-bg');
      if(dbg && !dbg.dataset.loaded){ dbg.dataset.loaded='1'; if(window.wbLoadReqDecisions) window.wbLoadReqDecisions(idv, dbg); }
    });
    tb.querySelectorAll('[data-req-act]').forEach(b => b.addEventListener('click', (e)=>{
      e.stopPropagation();
      if(window.wbReqAction) window.wbReqAction(b.dataset.reqAct, b.dataset);
    }));
  }catch(e){
    tb.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--danger);padding:24px">加载失败：${h(e.message)}</td></tr>`;
  }
}
function reqStColor(s){ return s==='已上线'?'green':s==='已关闭'?'gray':s==='研发中'?'green':s==='设计中'?'purple':s==='已确认'?'blue':'amber'; }
function renderReqStats(items){
  const box = $('#reqStatGrid');
  if(!box) return;
  const active = items.filter(x=>x.status!=='已关闭').length;
  const p0 = items.filter(x=>x.priority==='P0'&&x.status!=='已关闭').length;
  const dev = items.filter(x=>x.status==='研发中').length;
  const online = items.filter(x=>x.status==='已上线').length;
  box.innerHTML = `
    <div class="stat"><div class="num">${active}</div><div class="lbl">活跃需求</div></div>
    <div class="stat"><div class="num">${p0}</div><div class="lbl">P0待办</div><div class="trend" style="color:var(--danger)">最高优先</div></div>
    <div class="stat"><div class="num">${dev}</div><div class="lbl">研发中</div></div>
    <div class="stat"><div class="num">${online}</div><div class="lbl">已上线</div><div class="trend" style="color:var(--brand-strong)">已交付</div></div>`;
}
// R7 通用：表格行点击展开/收起（信号/需求/设计共用）
function bindExpandRows(tb, onExpand){
  tb.querySelectorAll('tr.exp-row').forEach(row=>{
    row.style.cursor='pointer';
    row.addEventListener('click', ()=>{
      const id = row.dataset.id;
      const detail = tb.querySelector(`tr.exp-detail[data-id="${CSS.escape(id)}"]`);
      const caret = row.querySelector('.caret');
      const open = detail && detail.classList.toggle('show');
      if(caret) caret.textContent = open?'▼':'▶';
      if(open && onExpand){ onExpand(id, detail.querySelector('.detail-box')); }
    });
  });
}

// R9补：设计统计条（与信号/需求统一结构）
function renderDsnStats(items){
  const box = $('#dsnStatGrid');
  if(!box) return;
  const active = items.filter(x=>x.status!=='已废弃').length;
  const draft = items.filter(x=>(x.status||'草稿')==='草稿').length;
  const reviewing = items.filter(x=>x.status==='评审中').length;
  const linked = items.filter(x=>x.requirement_id && x.requirement_id!=='待关联').length;
  const cover = items.length ? Math.round(linked/items.length*100) : 0;
  box.innerHTML = `
    <div class="stat"><div class="num">${active}</div><div class="lbl">设计稿</div></div>
    <div class="stat"><div class="num">${draft}</div><div class="lbl">草稿</div></div>
    <div class="stat"><div class="num">${reviewing}</div><div class="lbl">评审中</div><div class="trend" style="color:var(--amber)">待评审</div></div>
    <div class="stat"><div class="num">${cover}%</div><div class="lbl">需求关联覆盖</div><div class="trend" style="color:var(--brand-strong)">可追溯</div></div>`;
}

async function loadDesigns(){
  const tb = $('#designRows');
  if(!tb) return;
  tb.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--ink-3);padding:24px">加载中…</td></tr>';
  try{
    const d = await api('/api/knowledge/designs');
    const items = d.items || [];
    renderDsnStats(items);
    if(!items.length){ tb.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--ink-3);padding:24px">暂无设计稿</td></tr>'; return; }
    tb.innerHTML = items.map(x=>{
      const st = x.status||'草稿';
      const sc = st==='已定稿'||st==='已确认'?'green':st==='已归档'?'gray':'purple';
      const sig = Array.isArray(x.source_signals)?x.source_signals.join(','):(x.source_signals||'—');
      const idv = x.id||x._file;
      return `<tr class="exp-row" data-id="${h(idv)}">
        <td style="color:var(--ink-3);font-family:monospace;font-size:12px"><span class="caret">▶</span>${h(x.id||'—')}</td>
        <td style="font-weight:600;text-align:left">${h(x.title||'(无标题)')}</td>
        <td style="color:var(--ink-3)">${h(x.requirement_id||sig)}</td>
        <td>${tag(x.related_module||'—','blue')}</td>
        <td>${tag(st,sc)}</td>
        <td style="color:var(--ink-3)">${h(x.date||'—')}</td>
        ${IS_ADMIN ? `<td><div style="display:flex;gap:4px;flex-wrap:wrap;justify-content:center">
          <button class="btn sm ghost" data-dsn-act="status" data-id="${h(idv)}" data-status="${h(st)}">改状态</button>
          <button class="btn sm ghost" data-dsn-act="link" data-id="${h(idv)}" data-req="${h(x.requirement_id||'')}">关联需求</button>
          <button class="btn sm ghost" data-dsn-act="review" data-id="${h(idv)}" data-title="${h(x.title||'')}">指派评审</button>
          <button class="btn sm ghost" data-dsn-act="delete" data-id="${h(idv)}" data-title="${h(x.title||'')}" style="color:var(--danger);border-color:var(--danger)">🗑</button>
        </div></td>` : ''}</tr>
      <tr class="exp-detail" data-id="${h(idv)}"><td colspan="${IS_ADMIN?7:6}"><div class="detail-box">
        <div class="row"><span class="k">设计人</span><span>${h(x.designer||'—')}</span></div>
        <div class="row"><span class="k">目标版本</span><span>${h(x.target_release||'—')}</span></div>
        <div class="row"><span class="k">📄 设计资料</span><span>${x.doc_url?`<a href="${h(x.doc_url)}" target="_blank" style="color:var(--brand-strong)">${h(x.doc_url)}</a>`:`<span style="color:var(--ink-3);font-size:12px">未挂设计文档 · 可在对话中让 agent 提交设计资料（文档链接/原始文件），或让管理员编辑本设计的 doc_url 字段</span>`}</span></div>
        <div class="row"><span class="k">原始文件</span><span style="color:var(--ink-3);font-size:12px">${h(x._file||'—')}（knowledge/designs/）</span></div>
        <div class="row dsn-trace-row" data-dsn="${h(idv)}"><span class="k">🔗 追溯</span><span style="color:var(--ink-3);font-size:11px">展开时加载…</span></div>
      </div></td></tr>`;
    }).join('');
    // R34：设计行展开详情（与信号/需求交互对齐）
    bindExpandRows(tb, (idv, detailBox)=>{
      const tr = detailBox.querySelector('.dsn-trace-row');
      if(tr && !tr.dataset.loaded){
        tr.dataset.loaded='1';
        if(window.wbLoadTraces) window.wbLoadTraces('designs', idv, tr);
      }
    });
    // 设计行操作（admin）——阻止冒泡避免触发展开
    tb.querySelectorAll('[data-dsn-act]').forEach(b => b.addEventListener('click', (e)=>{
      e.stopPropagation();
      if(window.wbDesignAction) window.wbDesignAction(b.dataset.dsnAct, b.dataset);
    }));
  }catch(e){
    tb.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--danger);padding:24px">加载失败：${h(e.message)}</td></tr>`;
  }
}

// ── toast ──
let _toastT = null;
function toast(msg, isErr){
  let el = $('#wbToast');
  if(!el){ el = document.createElement('div'); el.id='wbToast'; document.body.appendChild(el); }
  el.textContent = msg;
  el.style.cssText = `position:fixed;bottom:28px;left:50%;transform:translateX(-50%);z-index:300;padding:12px 22px;border-radius:14px;font-size:13px;font-weight:600;color:#fff;box-shadow:0 8px 30px rgba(0,0,0,.2);background:${isErr?'#dc2626':'linear-gradient(145deg,#22c55e,#16a34a)'}`;
  el.style.display = 'block';
  clearTimeout(_toastT);
  _toastT = setTimeout(()=>{ el.style.display='none'; }, 2600);
}

// 暴露给后续模块
window.__wb = {api, h, tag, toast, stColor, stLabel, get USER(){return USER;}, get IS_ADMIN(){return IS_ADMIN;}, show, LOADED,
  loadSignals, loadRequirements, loadDesigns,
  setSigFilter(f){ _sigFilter = f||{}; loadSignals(); },
  getSigFilter(){ return _sigFilter; },
  _setReqFilter(f){ _reqFilter = f||{}; loadRequirements(); },
};

// 启动（等所有脚本 + DOM 就绪，确保 wb2/wb3 的 window.* 已注册）
if(document.readyState === 'complete') boot();
else window.addEventListener('load', boot);

// 其余模块（review/members/me/chat）在 wb2.js 里，通过 window.__wb 协作
})();
