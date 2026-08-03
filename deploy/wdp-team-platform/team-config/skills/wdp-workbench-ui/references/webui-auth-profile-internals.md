# WebUI 认证与 Profile 隔离机制（多用户改造落点）

> 为 WDP 团队工作台把 WebUI 从"单密码单用户"扩为"多用户 + 按 profile 隔离"时核实过的机制与代码落点。源码基线：`web-ui/`（api/auth.py、api/users.py、api/routes.py、api/profiles.py、api/helpers.py、server.py）。接真实代码前读这份，别重新考古。

## 1. 原版认证链路（单密码）
- `api/auth.py`：PBKDF2-SHA256(600k) `_hash_password`；`create_session()` 生成 `token.sig` 签名 cookie（`hermes_session`），`verify_session` 验签 + 过期；rate limit（`_check_login_rate` 60s/5 次，IP 维度）；CSRF（`csrf_token_for_session`，`X-Hermes-CSRF-Token` header）。
- session 持久化 `STATE_DIR/.sessions.json`，TTL 默认 30 天（`HERMES_WEBUI_SESSION_TTL`）。
- `check_auth(handler, parsed)`：未认证 → API 返 401、页面 302 跳 `/login?next=`（next 已做 percent-encode 防 query 截断/注入）。
- `/login` 用 `_LOGIN_PAGE_HTML` 模板渲染（只有一个 password 输入框），POST `/api/auth/login` 校验单密码。
- 安全 cookie：`set_auth_cookie` 带 httponly/samesite=Lax，HTTPS（反代 X-Forwarded-Proto）时加 Secure。

## 2. Profile 隔离（issue #798，多用户的地基，原生支持）
- `api/helpers.py`：`hermes_profile` cookie；`get_profile_cookie()` 读并校验名字（`_PROFILE_ID_RE` 或 'default'）；`build_profile_cookie(name)` 生成 Set-Cookie（httponly）。
- `server.py`：`do_GET/do_POST` 每个请求开始 `set_request_profile(cookie_profile)`，结束 `clear_request_profile()`。
- `api/profiles.py`：thread-local（`_tls`）存当前请求 profile → `get_active_profile_name()` / `get_active_hermes_home()` 按请求解析，**同一进程可同时服务多用户互不串**（已实测 3 用户并发隔离成立）。
- `create_profile_api(name)`：编程建 profile 目录（含 skills seeding、写 config/.env），add-user 时复用。
- 跨 profile 写保护：agent 运行中改别的 profile 的 memories/skills 会被 soft guard 拦（需显式确认）——天然隔离兜底。

## 3. 多用户改造落点（本项目已实现并验证）
- **`api/users.py`（新建）**：用户表 `STATE_DIR/users.json`（username/password_hash/profile/role/active/active_token），原子写 + 0600；`multiuser_enabled()`（env `HERMES_WEBUI_MULTIUSER=1` 或 users.json 存在）；admin=default profile，member=同名 profile。
- **单点登录（后登录挤掉先登录）**：用户表存 `active_token`，登录时新 token 覆盖；`session_username(cookie)` 反查"该 cookie 是否仍是某人 active_token"；`check_auth` 验签后再查 active_token——旧 session 签名有效也判失效。停用/重置密码/踢人都清 active_token。
- **登录路由**：`/api/auth/login` 多用户分支（username+password→校验→`login_user`→种 session cookie + `build_profile_cookie(profile)`）；单密码模式原样保留。
- **admin 接口**：GET `/api/auth/me`（当前用户，前端按 role 渲染）、GET `/api/admin/users`；POST `/api/admin/users/create|reset_password|set_active|kick`（写操作走 POST + CSRF + `is_request_admin`）。注意只读查询放 `handle_get`，写操作放 `handle_post`（routes.py 两段，别放错）。
- **登录页**：多用户渲染 `_LOGIN_PAGE_HTML_MULTIUSER`（绿白玻璃 + 账号/密码双字段），JS 用 `static/login-multiuser.js`（提交 username+password，复用 next= 安全处理）。`/login` 路由按 `multiuser_enabled()` 选模板。

## 4. 已踩过的坑
- **Windows 建共享 knowledge/ 链接**：git-bash `ln -s` 会退化成**拷贝**（破坏单一数据源）；`cmd mklink /J` 在该 shell 调用方式下不可靠。**正解：PowerShell `New-Item -ItemType Junction -Path <link> -Target <target>`**（实时同步已验证）。Linux 生产用 `ln -s`/NFS 即可。写 add-user 脚本要分平台。
- **测试服务器别用 `&` 后台**（terminal 工具规则），用 `terminal(background=true)` 起，再单独 curl 健康检查；8799 常被本人正在用的 WebUI 占着，测试用别的端口（如 8801）+ 独立 `HERMES_WEBUI_STATE_DIR` 隔离。
- CSRF 豁免仅 `/api/auth/login` 等少数 public path；admin 写接口必须带登录态 + CSRF token，属正常安全设计，不是 bug。

## 5. 待做（接真实界面时）
- 工作台三 tab 后端：`/api/knowledge/signals|requirements|designs`（扫 knowledge/*.md 解析 frontmatter 返回 JSON），复用现有 `/api/file` 读取逻辑。
- 主题：绿白玻璃 token 已在 `templates/workbench-theme.css`，接入时注意 WebUI 现有 skin/theme 体系（settings.json 的 theme/skin）。
