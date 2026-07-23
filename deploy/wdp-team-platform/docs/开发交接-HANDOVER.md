# WDP 团队 AI 工作台 · 项目交接文档

> 用途：从当前工程（F:\wdp-team-hermes）迁移到个人 hermes 后，凭此文档快速恢复上下文，继续开发。
> 整理时间：2026-07-21

---

## 一、项目目标（一句话）

把单机版 Hermes WebUI 升级为 **WDP 产品团队的多用户 AI 工作台**：
- 每个成员有独立风格的 agent（独立 memory/skills/对话/个人工作库）
- 共享唯一团队知识库（knowledge/，git 版本化，单一数据源）
- 三大工作组件：信息（信号）/ 需求 / 产品设计，自然语言 chat 调用
- 团队工作台可视化：成员只读，管理员（你）可管理操作
- 部署：公网可访问，Linux + K8s 集群，Jenkins CI/CD

---

## 二、关键架构决策（已定，勿推翻）

### 1. 部署架构：方案 A 单入口多副本集群
- 统一入口 Ingress(TLS) → Service → **2 副本 WebUI**（4C8G）→ 共享卷（knowledge + profiles）+ 独立主 Agent
- **sticky session**：按 hermes_session cookie 会话亲和（WebUI 有 SSE 长连接 + 内存态）
- 用户隔离：复用 WebUI 原生 `hermes_profile` cookie → thread-local 切换 profile（issue #798），**同一副本可服务多用户互不干扰**
- 运维建议（你同事）：资源集中分配 + 集群，优于每人独立实例（方案 B，已废弃但 git 留痕）

### 2. 个人 chatbox vs 团队工作台（核心概念）
- **个人 chatbox = 干活的地方**（多 session，按工作主题分）
- **团队工作台 = knowledge/ 的可视化窗口**（信息/需求/设计三 tab）
  - 成员**只读**；管理员（你）**可管理操作**
- 连接动作 = **归档**：chatbox 产出 → 提交入库 → 管理员审核 → 进团队工作台

### 3. 主/子 Agent 分层（异步协作，不直接通信）
- **主 Agent**（1 个，独立部署，团队公共 Key）：定时任务/入库协调/全局分析/跨 agent 讨论。**入库审核的执行者是主 Agent**
- **个人 Agent**（每用户 1 个，各自 profile，各自 Key）：日常对话/个人工作/提交申请
- 协作介质：profiles/<user>/inbox/、knowledge/、.inbox-index/、Kanban

### 4. 模型 Key 双层
- 用户 Key（各自 profile/.env）优先 → 个人对话/调用组件
- 团队公共 Key（主 Agent，K8s Secret）兜底 + 自动化任务
- 用户可配多渠道（服务商+Key→自动出模型下拉→测连通性→对话中选用）

### 5. SOUL 三层（团队 > 个人 > 项目）
- **团队 SOUL**（最高优先级，管理员维护，放各 profile 的 AGENTS.md）：6 条铁律
- **个人 SOUL**（profiles/<user>/SOUL.md，成员自定义个性）
- **项目 SOUL**（工作目录 .hermes.md）
- 实现路径：**复用 Hermes 现成槽位**——团队铁律放 AGENTS.md（项目规则槽，权威），个人风格放 SOUL.md（身份槽），不改核心代码

### 6. 个人工作库（重要，易误解）
- **本体留本地/个人设备**（大文件、杂文件不上服务器）
- **服务器只存索引**（profiles/<user>/workspace-index/，文件清单 JSON，不含本体）
- **环境鉴别**：机器指纹(Machine ID) + 工作库指纹文件 `.wdp-workspace.json` 双因子，**不用 IP**（内网 IP 不可靠）
- agent 读不到时明确提示（不编造），设备离线时若有 git 仓库可降级拉取
- 远程访问：Gateway 接入飞书/企微/Telegram，驱动服务器上同一份 profile

### 7. 知识库/skill/SOUL 更新 ≠ 重新部署
- 这些是**数据**（放共享卷），走 **git 工作流**（push → 服务器 pull），几秒生效，**不碰部署不重启**
- 只有**代码**（WebUI/agent 源码）改动才需要重新构建镜像部署

---

## 三、团队铁律（team-soul.md，6 条）

1. **单一数据源**：团队知识只认 knowledge/，不搞第二份清单
2. **知识优先级**：团队库 > 个人 memory > 模型自身知识
3. **工作流产出收敛**：信号/需求/设计必须结构化入 knowledge/ 对应目录，可追溯（需求追信号、设计追需求）
4. **汇报口径**：WDP=AES唯一开放平台层；国产化=金仓KingbaseES(非达梦)；编辑器五大主线(不含废弃画布/蓝图)；成果表述诚实(雏形≠已支持)
5. **环境鉴别防幻觉**：读文件先声明环境，读不到/指纹不符明确提示，绝不编造文件内容
6. **不可获取授权信息**：在线源(企微/飞书/API库)统一管理员授权，凭证禁硬编码/禁入git/禁回显

---

## 四、当前已完成（真实代码/产出）

### ✅ 后端（在 web-ui/）
- `api/users.py`（新增）：多用户管理——users.json 用户表（username/password_hash/profile/role/active_token/active）、单点登录（active_token 机制，后登录挤掉先登录）、create_user/reset_password/set_active/kick、current_request_user/is_request_admin
- `api/auth.py`（改）：check_auth 加多用户校验（验签后查 active_token）；新增 _reject_unauthorized
- `api/routes.py`（改）：多用户登录路由（/api/auth/login 校验账号密码+种 session+种 hermes_profile cookie）、admin 用户管理路由（/api/admin/users 系列）、/api/auth/me、多用户登录页模板 _LOGIN_PAGE_HTML_MULTIUSER
- `static/login-multiuser.js`（新增）：登录页前端（提交 username+password）
- 环境变量 `HERMES_WEBUI_MULTIUSER=1` 启用多用户模式（未启用回落官方单密码）
- **测试已通过**：登录/单点挤掉/admin 权限隔离/me 接口，均实测 OK

### ✅ 部署包（已推 gitlab wdp-team-platform）
- Dockerfile（继承官方 web-ui + COPY overlay + agent 源码到 /opt/hermes）+ .dockerignore + BUILD.md
- k8s/：pvc(knowledge+profiles 两个 RWX) / deployment(2副本4C8G) / service / ingress(TLS+sticky+SSE 3600s+上传100m) / main-agent(hermes gateway run，注入 Secret) / secret.example
- webui-overlay/：多用户定制代码 + README
- team-config/：team-soul.md(6铁律) / AGENTS.md.template / SOUL.md.template / skills(signal-intake, requirement-triage)
- scripts/：add-user.sh（幂等开通成员）/ init-knowledge.sh（初始化知识库卷）
- README.md：9 章部署文档（架构/步骤/运维替换清单/Jenkins/FAQ）

### ✅ 知识库（已推 gitlab wdp-team-knowledge）
- knowledge/ 结构：signals/ requirements/ designs/ decisions/ tracking/ + wdp-product-knowledge/(母版)
- 母版：2 skill + 5 prompt 模板 + 4 同步脚本（飞书凭证已剥离为环境变量）
- 含 .gitignore（保护凭证/secret/token）

### ✅ 界面原型（workbench/prototypes/workbench-prototype.html）
- 绿白 + 液体玻璃 + 淡网格，完整可交互原型
- 含：对话(chat，文件上传+模型选择器+模板按钮) / 工作台三tab(可展开卡片) / 入库审核(左列表+右chat) / 成员管理 / 个人中心(agent+模型渠道+工作库环境+memory+日志)
- 成员/管理员视角切换演示

---

## 五、未完成（待开发）

### 🔴 最高优先级：前端重构（当前任务）
**目标**：基于 WebUI 能力重构工作台交互界面（不是外挂独立面板，是换皮+重组）

**已定方案（深度复盘结论）**：
- **主题层**：新增 `data-skin="wdp"` 绿白皮肤（改 style.css 的 :root 变量）+ `wdp-workbench.css` 覆盖层（液体玻璃 backdrop-filter/宽 rail/淡网格背景）
- **导航层**：保留 `data-panel` + `switchPanel()` 机制，rail 改造成宽展开式（图标+中文标签+分组：工作/管理/我的），导航项：对话/工作台/审核(admin)/成员(admin)/个人中心/设置
- **面板层**：新增 panelWorkbench/panelReview/panelMembers/panelMe（复用 panel-view + 懒加载机制）；chat 引擎完全不动只换皮
- **关键**：同一套骨架/导航/主题，工作台与 chat/kanban/memory 在同一绿白世界，不割裂

**WebUI 架构要点（重构依赖）**：
- 面板切换：`switchPanel(name)` in static/panels.js（~line 203），靠 `data-panel` 导航 + `panel<Name>` 容器 + `showing-<name>` class on main + 懒加载
- 主题：static/style.css 的 :root 变量（--bg/--text/--accent/--border 等）+ data-theme(light/dark) + data-skin
- skin 注册：static/boot.js 的 _SKINS 数组 + _VALID_SKINS 校验

### 🔴 后端接口（待开发）
- **R1 工作台**：`/api/knowledge/signals|requirements|designs`（解析 markdown frontmatter 返回 JSON，支持筛选）+ 详情 + 统计
- **R3 入库审核**：inbox 结构 + 待审列表 + 审核执行（移文件+git commit+建路由）
- **R4 个人中心**：SOUL 读写 / 模型渠道存取 / memory 读写 / 运行日志 / workspace-index 索引
- **R6 文件上传**：chat 上传 → 个人 workspace/uploads + 通知 agent
- **R8 管理操作**：沉淀需求/分配/改态/通知/审核通过/驳回
- **R9** 登录后默认进对话页

### 🟡 主 Agent 自动化
- **R7** cron 定时任务：信号定时清洗 / 需求停滞提醒 / 周报 / session 压缩归档（标注时间/主题/用户）

---

## 六、gitlab 仓库（内网 gitlab.51cloud.local）

| 仓库 | 地址 | 内容 | 分支 |
|------|------|------|------|
| 部署包 | `http://gitlab.51cloud.local/Maguanjie/wdp-team-platform.git` | Dockerfile/k8s/overlay/team-config/scripts/README | main |
| 知识库 | `http://gitlab.51cloud.local/Maguanjie/wdp-team-knowledge.git` | knowledge/ 全部 + 母版 | master |

**凭证**：推送用 token（你提供的，走 oauth2:token 方式）。⚠️ 该 token 已在对话中暴露，建议撤销重建。
**废弃**：`git.51vr.local/neon/wdp-team-platform`（neon 组默认分支保护，Owner 也无法 push 首个 commit，已弃用）

---

## 七、当前工程目录（F:\wdp-team-hermes）

```
├── agent-src/          # Hermes agent 官方源码（git 仓库，未改核心）
├── web-ui/             # WebUI（含多用户定制，正在这套上重构）★ 开发主战场
├── knowledge/          # 团队知识库（git 仓库，已推 gitlab）
├── deploy/wdp-team-platform/  # 部署包（git 仓库，已推 gitlab）
├── skills/             # 团队工作流 skill（signal-intake/requirement-triage）
├── workbench/          # 开发工作区
│   ├── prototypes/     # 界面原型（workbench-prototype.html 完整可交互）
│   ├── archive/        # 归档（旧启动脚本）
│   └── TASK-LIST.md    # 开发任务清单
├── hermes-home/        # Hermes 运行态（HERMES_HOME）
├── 团队工作台手册.md     # 团队纲领（工作流 + WDP 知识库索引）
└── AGENTS.md           # 项目上下文（Hermes 加载）
```

**后续要清理的历史包袱**：web-ui/api/__pycache__(2.1M)、hermes-home 测试残留、根目录临时文件(.monitor/baseline-knowledge.txt)、workbench/archive

---

## 八、继续开发的第一步（迁移后）

1. 在个人 hermes 上恢复此工程（web-ui 含多用户定制 + knowledge + deploy + skills + workbench）
2. 从 **workbench/TASK-LIST.md** 接着看任务清单
3. 从 **前端重构** 开始：新增 `data-skin="wdp"` 绿白皮肤 → 改造 rail → 新增工作台/审核/成员/个人中心面板
4. 参考原型：`workbench/prototypes/workbench-prototype.html`（视觉/交互蓝本）
5. 后端接口 R1-R9 随后，最后本地跑通完整流程 → 交付运维

---

## 九、用户使用说明（同事视角，部署后）

**首次使用**：管理员发网址+账号+初始密码 → 登录改密码 → 个人中心看团队规则/填个性 → （可选）配模型渠道/登记设备环境
**日常使用**：对话页干活（洗信号/写需求/写PRD/问知识，可拖文件上传）→ 工作台看团队沉淀 → 产出说"提交入库"等审核
**规矩**：知识只认 knowledge/、产出要入库收敛、汇报守口径

---

## 十、重要提醒（安全）

1. **飞书 app_secret 重置**：母版原文件硬编码的 `hyfCDfgj...` 已暴露过，去飞书开放平台撤销重置
2. **gitlab token 重置**：`x5MT976tszCWLFrgiJL5` 已在对话暴露，去 gitlab 撤销重建
3. **授权信息铁律**：所有凭证（飞书/企微/gitlab/LLM Key）只走环境变量/K8s Secret/凭据管理器，禁硬编码/禁入 git/禁对话回显
