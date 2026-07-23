# webui-overlay · WDP 团队工作台定制层

> 构建时整目录 COPY 覆盖到官方 web-ui 之上（见根目录 Dockerfile）。
> **前端路线：独立客制化前端（workbench.html + wb*.js），多用户模式下替换官方 index；
> 不是在官方界面上打补丁**（旧补丁路线已废弃，boot.js/panels.js/index.html 不在本层）。

## api/（后端定制）

| 文件 | 类型 | 说明 |
|---|---|---|
| `auth.py` | 改动 | 多用户校验（active_token 单点登录）+ 多用户模式强制鉴权 |
| `users.py` | 新增 | 用户表 users.json：账号/角色/单点登录/踢下线 |
| `routes.py` | 改动 | 多用户登录路由、workbench.html 替换 index、全部 /api/knowledge|review|me|admin 路由、wb 静态文件 no-cache+mtime 版本号 |
| `knowledge.py` | 新增 | R1 知识库读：frontmatter 解析、config 驱动分区注册表 |
| `review.py` | 新增 | R3 入库审核：inbox 提交/列表/通过(git commit)/驳回、模板校验 |
| `knowledge_admin.py` | 新增 | R8 管理操作：改 frontmatter 字段/状态流转 |
| `knowledge_ops.py` | 新增 | 归并/沉淀需求/新建设计/通知/追溯/软删归档 |
| `me.py` | 新增 | R4 个人中心：SOUL/Memory/日志/工作库索引 |
| `channels.py` | 新增 | 模型渠道 CRUD+连通探测、设备登记(machine_id)、工作库目录、环境互锁 |
| `team_agent.py` | 新增 | 团队规则(保存/发布到成员 profile)、团队默认模型、发布状态 |
| `merge_agent.py` | 新增 | 归并 Agent + 审核助手（直连 OpenRouter，截断自动重试容错） |
| `agent_dialog.py` | 新增 | 对话式 agent 协作（归并/审核多轮讨论），few-shot 学习历史决策 |
| `wdp_agent_log.py` | 新增 | 归并/审核决策日志（knowledge/agent-sessions/，git 版本化） |
| `team_tasks.py` / `team_scheduler.py` | 新增 | 主 Agent 定时任务（croniter 调度线程，WDP_SCHEDULER_ENABLED 单点） |
| `workspace_upload.py` | 新增 | R6 chat 文件上传到个人工作库 |
| `agent_sessions.py` | 官方同步 | 官方文件（曾被误覆盖，此处为官方版本） |
| `server.py` | 改动 | 多用户模式启动调度线程 |

## static/（独立客制化前端）

| 文件 | 说明 |
|---|---|
| `workbench.html` | 页面骨架（对话/工作台/决策中心/成员管理/团队Agent/个人中心 六视图） |
| `wb.css` | 绿白液体玻璃全套样式 |
| `wb.js` | 框架：认证/视图切换/工作台三tab/统计 |
| `wb2.js` | 决策中心审核/成员管理/团队Agent/个人中心 |
| `wb3.js` | 对话：自写 SSE 客户端/会话列表/草稿态/@成员/工作库选择 |
| `wb4.js` | 工作台增强：筛选/沉淀/分配/通知/追溯/母版库/我的/定时任务面板 |
| `wb5.js` | 对话式 agent 协作弹窗（归并/审核） |
| `wb-modal.js` | 通用弹窗组件（wbAlert/wbConfirm/wbPrompt/wbForm/wbModal，全站禁用浏览器原生弹窗） |
| `login-multiuser.js` | 多用户登录页 |

## 必需环境变量

| 变量 | 说明 |
|---|---|
| `HERMES_WEBUI_MULTIUSER=1` | 启用多用户模式（未设则回落官方单密码模式+官方界面） |
| `HERMES_HOME` | 运行态根目录（users.json/profiles/SOUL 等在此） |
| `HERMES_KNOWLEDGE_DIR` | 团队知识库目录（git 仓库） |
| `HERMES_WEBUI_AGENT_DIR` | Hermes agent 源码目录 |
| `WDP_SCHEDULER_ENABLED` | 定时任务调度开关（多副本只在主 Pod 设 1） |
