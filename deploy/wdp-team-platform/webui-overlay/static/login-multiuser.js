/* 多用户登录页（WDP 团队平台）— 提交账号+密码到 /api/auth/login。
 * 复用现有 login 路由（多用户模式已在后端按 username+password 校验）。
 */
document.addEventListener('DOMContentLoaded', function () {
  var form = document.getElementById('login-form');
  var userInput = document.getElementById('username');
  var pwInput = document.getElementById('pw');
  if (!form || !userInput || !pwInput) return;

  var invalidPw = form.getAttribute('data-invalid-pw') || '账号或密码错误';
  var connFailed = form.getAttribute('data-conn-failed') || '连接失败，请稍后再试';

  function showErr(msg) {
    var err = document.getElementById('err');
    if (err) { err.textContent = msg; err.style.display = 'block'; }
  }
  function hideErr() {
    var err = document.getElementById('err');
    if (err) { err.style.display = 'none'; }
  }

  // 与 login.js 相同的 next= 安全处理（防开放重定向）
  function _safeNextPath() {
    try {
      var raw = new URL(window.location.href).searchParams.get('next');
      if (!raw) return './';
      if (raw.charAt(0) !== '/') return './';
      if (raw.charAt(1) === '/' || raw.charAt(1) === '\\') return './';
      if (/[\x00-\x1f\x7f\s]/.test(raw)) return './';
      return raw;
    } catch (_) { return './'; }
  }

  async function doLogin(e) {
    e.preventDefault();
    hideErr();
    var username = userInput.value.trim();
    var password = pwInput.value;
    if (!username || !password) { showErr(invalidPw); return; }
    var btn = form.querySelector('button[type=submit]');
    if (btn) btn.disabled = true;
    try {
      var res = await fetch('api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: username, password: password })
      });
      var data = {};
      try { data = await res.json(); } catch (_) {}
      if (res.ok && data.ok) {
        window.location.href = _safeNextPath();
        return;
      }
      showErr(data.error || invalidPw);
    } catch (_) {
      showErr(connFailed);
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  form.addEventListener('submit', doLogin);
});
