/* ============================================================
   WDP 团队工作台 · 通用弹窗组件（wb-modal.js）
   替代浏览器原生 alert/prompt/confirm，统一绿白风格、Promise 化。
   全局暴露：wbAlert / wbConfirm / wbPrompt / wbForm / wbModal(自定义)
   依赖：wb.css 的 --brand 等变量；无其它依赖，最先加载。
   ============================================================ */
(function(){
'use strict';

function esc(s){
  return String(s==null?'':s).replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// 底层：创建遮罩 + 卡片，返回 {overlay, card, close}
function _shell(opts){
  opts = opts || {};
  const overlay = document.createElement('div');
  overlay.className = 'wbm-overlay';
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(15,31,22,.42);backdrop-filter:blur(6px);z-index:2000;display:flex;align-items:center;justify-content:center;padding:24px;animation:wbmFade .16s ease';
  const w = opts.width || 460;
  const card = document.createElement('div');
  card.className = 'wbm-card';
  card.style.cssText = `background:var(--glass-strong,rgba(255,255,255,.92));backdrop-filter:blur(24px) saturate(180%);border:1px solid rgba(255,255,255,.7);border-radius:18px;max-width:${w}px;width:100%;max-height:84vh;overflow-y:auto;padding:24px 26px;box-shadow:0 24px 70px rgba(15,33,24,.28);animation:wbmPop .18s cubic-bezier(.3,1.3,.5,1)`;
  overlay.appendChild(card);
  document.body.appendChild(overlay);
  // 注入一次性动画样式
  if(!document.getElementById('wbm-style')){
    const st = document.createElement('style'); st.id='wbm-style';
    st.textContent = '@keyframes wbmFade{from{opacity:0}to{opacity:1}}@keyframes wbmPop{from{opacity:0;transform:translateY(8px) scale(.98)}to{opacity:1;transform:none}}.wbm-btn{padding:9px 18px;border-radius:11px;font-size:13px;font-weight:600;cursor:pointer;border:1px solid var(--line,#dfe8e2);background:rgba(255,255,255,.7);color:var(--ink-2,#3a4a42);transition:.12s}.wbm-btn:hover{background:#fff}.wbm-btn.primary{background:linear-gradient(145deg,#22c55e,#16a34a);color:#fff;border:none}.wbm-btn.primary:hover{filter:brightness(1.05)}.wbm-btn.danger{background:#dc2626;color:#fff;border:none}.wbm-in{width:100%;padding:11px 13px;border-radius:11px;border:1px solid var(--line,#dfe8e2);font-size:14px;font-family:inherit;background:rgba(255,255,255,.85);color:var(--ink,#1a2620);box-sizing:border-box;margin-top:4px}.wbm-in:focus{outline:none;border-color:#16a34a;box-shadow:0 0 0 3px rgba(22,163,74,.12)}textarea.wbm-in{resize:vertical;min-height:80px;line-height:1.5}';
    document.head.appendChild(st);
  }
  const close = ()=>{ overlay.style.animation='wbmFade .14s ease reverse'; setTimeout(()=>overlay.remove(),120); };
  if(!opts.noBackdropClose){
    overlay.addEventListener('click', e=>{ if(e.target===overlay){ close(); if(opts.onCancel) opts.onCancel(); } });
  }
  // ESC 关闭
  const onKey = e=>{ if(e.key==='Escape'){ close(); if(opts.onCancel) opts.onCancel(); document.removeEventListener('keydown',onKey); } };
  document.addEventListener('keydown', onKey);
  return {overlay, card, close:()=>{ close(); document.removeEventListener('keydown',onKey); }};
}

function _head(title, icon){
  return `<div style="display:flex;align-items:center;gap:9px;margin-bottom:14px"><span style="font-size:20px">${icon||'💬'}</span><h3 style="margin:0;font-size:16px;font-weight:700;color:var(--ink,#1a2620)">${esc(title)}</h3></div>`;
}

// ── wbAlert：告知，一个确定按钮 ──
window.wbAlert = function(message, opts){
  opts = opts||{};
  return new Promise(resolve=>{
    const {card, close} = _shell({width:opts.width||440});
    card.innerHTML = _head(opts.title||'提示', opts.icon||'ℹ️')
      + `<div style="font-size:14px;line-height:1.6;color:var(--ink-2,#3a4a42);white-space:pre-wrap;margin-bottom:18px">${esc(message)}</div>`
      + `<div style="display:flex;justify-content:flex-end"><button class="wbm-btn primary" data-ok>${esc(opts.okText||'知道了')}</button></div>`;
    card.querySelector('[data-ok]').onclick = ()=>{ close(); resolve(true); };
    card.querySelector('[data-ok]').focus();
  });
};

// ── wbConfirm：确认，返回 true/false ──
window.wbConfirm = function(message, opts){
  opts = opts||{};
  return new Promise(resolve=>{
    const {card, close} = _shell({width:opts.width||440, onCancel:()=>resolve(false)});
    card.innerHTML = _head(opts.title||'确认', opts.icon||(opts.danger?'⚠️':'❓'))
      + `<div style="font-size:14px;line-height:1.6;color:var(--ink-2,#3a4a42);white-space:pre-wrap;margin-bottom:18px">${esc(message)}</div>`
      + `<div style="display:flex;justify-content:flex-end;gap:10px"><button class="wbm-btn" data-cancel>${esc(opts.cancelText||'取消')}</button><button class="wbm-btn ${opts.danger?'danger':'primary'}" data-ok>${esc(opts.okText||'确定')}</button></div>`;
    card.querySelector('[data-cancel]').onclick = ()=>{ close(); resolve(false); };
    card.querySelector('[data-ok]').onclick = ()=>{ close(); resolve(true); };
    card.querySelector('[data-ok]').focus();
  });
};

// ── wbPrompt：单行/多行输入，返回字符串或 null ──
window.wbPrompt = function(message, opts){
  opts = opts||{};
  return new Promise(resolve=>{
    const {card, close} = _shell({width:opts.width||460, onCancel:()=>resolve(null)});
    const multi = !!opts.multiline;
    const inputHtml = multi
      ? `<textarea class="wbm-in" data-in placeholder="${esc(opts.placeholder||'')}">${esc(opts.value||'')}</textarea>`
      : `<input class="wbm-in" data-in type="${opts.type||'text'}" placeholder="${esc(opts.placeholder||'')}" value="${esc(opts.value||'')}">`;
    card.innerHTML = _head(opts.title||'请输入', opts.icon||'✏️')
      + (message?`<div style="font-size:13px;line-height:1.55;color:var(--ink-2,#3a4a42);white-space:pre-wrap;margin-bottom:6px">${esc(message)}</div>`:'')
      + inputHtml
      + `<div style="display:flex;justify-content:flex-end;gap:10px;margin-top:18px"><button class="wbm-btn" data-cancel>${esc(opts.cancelText||'取消')}</button><button class="wbm-btn primary" data-ok>${esc(opts.okText||'确定')}</button></div>`;
    const inp = card.querySelector('[data-in]');
    const submit = ()=>{ const v=inp.value; close(); resolve(v); };
    card.querySelector('[data-cancel]').onclick = ()=>{ close(); resolve(null); };
    card.querySelector('[data-ok]').onclick = submit;
    if(!multi) inp.addEventListener('keydown', e=>{ if(e.key==='Enter') submit(); });
    setTimeout(()=>{ inp.focus(); inp.select&&inp.select(); }, 30);
  });
};

// ── wbForm：多字段表单弹窗。fields=[{key,label,type,value,options,placeholder,required}] ──
//    返回 {key:value,...} 或 null。type: text|password|textarea|select|number
window.wbForm = function(title, fields, opts){
  opts = opts||{};
  return new Promise(resolve=>{
    const {card, close} = _shell({width:opts.width||500, onCancel:()=>resolve(null)});
    const rows = fields.map((f,i)=>{
      let ctrl;
      if(f.type==='textarea'){
        ctrl = `<textarea class="wbm-in" data-k="${esc(f.key)}" placeholder="${esc(f.placeholder||'')}">${esc(f.value||'')}</textarea>`;
      } else if(f.type==='select'){
        ctrl = `<select class="wbm-in" data-k="${esc(f.key)}">${(f.options||[]).map(o=>{
          const val = typeof o==='object'?o.value:o; const lab = typeof o==='object'?o.label:o;
          return `<option value="${esc(val)}" ${String(val)===String(f.value)?'selected':''}>${esc(lab)}</option>`;
        }).join('')}</select>`;
      } else {
        ctrl = `<input class="wbm-in" data-k="${esc(f.key)}" type="${f.type||'text'}" placeholder="${esc(f.placeholder||'')}" value="${esc(f.value==null?'':f.value)}">`;
      }
      return `<div style="margin-bottom:13px"><label style="font-size:12px;font-weight:600;color:var(--ink-2,#3a4a42)">${esc(f.label)}${f.required?' <span style="color:#dc2626">*</span>':''}</label>${ctrl}</div>`;
    }).join('');
    card.innerHTML = _head(title, opts.icon||'📝')
      + rows
      + `<div id="wbmErr" style="color:#dc2626;font-size:12px;min-height:16px;margin-bottom:4px"></div>`
      + `<div style="display:flex;justify-content:flex-end;gap:10px"><button class="wbm-btn" data-cancel>${esc(opts.cancelText||'取消')}</button><button class="wbm-btn primary" data-ok>${esc(opts.okText||'确定')}</button></div>`;
    card.querySelector('[data-cancel]').onclick = ()=>{ close(); resolve(null); };
    card.querySelector('[data-ok]').onclick = ()=>{
      const out = {};
      for(const f of fields){
        const el = card.querySelector(`[data-k="${f.key}"]`);
        out[f.key] = el ? el.value : '';
        if(f.required && !String(out[f.key]).trim()){
          card.querySelector('#wbmErr').textContent = `「${f.label}」必填`;
          el && el.focus();
          return;
        }
      }
      close(); resolve(out);
    };
    setTimeout(()=>{ const first=card.querySelector('[data-k]'); first&&first.focus(); }, 30);
  });
};

// ── wbModal：完全自定义内容的弹窗，返回 {card, close} 供调用方自行填充 ──
window.wbModal = function(opts){
  return _shell(opts||{});
};

})();
