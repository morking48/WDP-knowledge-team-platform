# WDP 产品团队共享 Hermes 工作台

> 目标：在自己的服务器上部署一套定制化 Hermes Agent，作为 WDP 产品团队 AI Native 产研工作流的执行引擎。
> 团队成员通过企微/Web 浏览器使用；沉淀的团队知识资产全部落地在 knowledge 仓库（Markdown + git 版本化）。
>
> 本工作台是**独立客制化前端（workbench.html + wb.js~wb5.js）复用 Hermes 后端 API + SSE 的多用户工作台**，
> 不是官方单机 WebUI —— 官方源码在 `agent-src/`（运行时，勿改），定制层在 `web-ui/` 与 `deploy/.../webui-overlay/`。

## 目录结构

```
wdp-team-hermes/
├── README.md                      # 本文件
├── AGENTS.md                      # AI 助手工作指引（首要指引 + 目录 + 原则）
├── 团队工作台手册.md               # 核心手册（AI Native 工作流 + WDP 产品知识库索引）
├── docs/                          # 方案 / 架构 / 智能体档案
│   ├── 01-架构与数据流转.md
│   ├── 02-部署checklist-给IT.md
│   ├── 03-远程访问测试方案.md
│   ├── 智能体档案-01-对话Agent.md   # 对话 agent 设计+能力留档
│   └── 智能体档案-02-专职Agent.md   # 4个专职 agent 设计+完成度分析
├── web-ui/                        # 定制前端 + 后端 API（本地开发/测试主战场）
│   ├── static/                    # workbench.html + wb.js~wb5.js + wb-modal.js + wb.css
│   └── api/                       # 定制后端模块（projects/review/team_agent/...）
├── skills/                        # 团队共享 skills（方法论 → AI 可执行）
├── knowledge/                     # 团队知识资产库（独立 git 仓库，单一数据源）
│   ├── knowledge.config.yaml      # ★ 分区注册表（加/改分区只改这一个文件）
│   ├── signals/ requirements/ designs/ decisions/ tracking/   # 产研四层闭环 + 决策
│   ├── projects/                  # 项目分区（售前/售后项目：项目档案+项目需求+交付材料）
│   ├── team/                      # 团队成员档案（18人，能力画像随对话沉淀）
│   └── library/                   # 母版知识库（product-knowledge 在线路由 + archive 归档）
├── hermes-home/                   # 团队运行时 HERMES_HOME（SOUL/config/scripts，gitignore）
│   └── scripts/                   # agent 可调脚本（submit_review/query_knowledge/画像/个人技能）
├── agent-src/                     # 官方 Hermes 源码（运行时，勿改）
├── deploy/wdp-team-platform/      # 部署包（Dockerfile + overlay + team-config，gitlab）
└── scripts/
    └── start-team-webui.bat       # 本机测试服务一键启动（端口 8799）
```

## 核心能力

### 智能体体系（详见 docs/智能体档案）
- **对话 Agent（主力）**：每位成员的私人产研助手，官方 AIAgent 内核。懂四层闭环+项目分区，能提交入库、查询知识库、沉淀成员画像/个人技能、走设计收敛工作流。
- **4 个专职 Agent（admin 用）**：归并助手（信号去重）/ 审核助手（入库审核+派单建议）/ 团队规则助手（对话共创 SOUL）/ 团队技能助手（对话编辑 skill）。
- **定时任务（6 个内置，纯脚本机械化，默认关）**：信号清洗 / 需求停滞 / 需求周报 / 上传处置 / 清理已删 / 刷新知识库索引（提醒类任务扫描后主动通知 admin/负责人）。

### 产研工作流
- **四层闭环**：信号 → 需求 → 设计 → 跟踪（决策贯穿），各有 skill 和产出目录。
- **项目分区**：客户项目开档（含商机号/BD/TB），信号可沉淀为「项目需求」，交付材料绑定项目需求（售前/售中/售后）。
- **通用提交入库**：成员可提交信号/需求/设计三类，都进决策中心审核。
- **能力模式**（对话框）：🎯 设计模式（design-converge 收敛工作流，出可点选择题→零歧义方案）/ 📥 信号清洗模式（signal-intake）。

### 团队 vs 个人
- **团队统一**：团队 SOUL（规则块，管理员发布，标记块隔离）+ 团队 skill（只读共享）+ 团队默认模型。
- **个人定制**：个人 SOUL 块外区（个人习惯）+ 个人 skill（可开关）+ 个人模型渠道（如 copilot）。
- **优先级**：团队铁律 > 个人偏好（SOUL 显式声明，个人不得违背团队约定）。

## 工作流

### 第一步：本机功能验证（负责人自己做）
1. 双击 `scripts/start-team-webui.bat` 启动本机服务（端口 8799，会自动杀干净旧进程）
2. 浏览器打开 `http://127.0.0.1:8799`（首次登录 admin，测试前 Ctrl+Shift+R 硬刷新）
3. 按 `docs/03-远程访问测试方案.md` 验证功能

### 第二步：部署到服务器（IT 做）
功能验证 OK 后，把 `docs/02-部署checklist-给IT.md` 转给 IT。部署包 `deploy/wdp-team-platform/` 已自包含（web-ui + agent-src 随仓库自带），在仓库根 `docker build .` 即可。

### 第三步：团队使用（同事做）
IT 部署完成后，同事通过服务器 IP 或企微入口使用，各自账号独立 profile，团队知识资产沉淀到 knowledge 仓库。

## 三仓库结构

| 仓库 | 内容 | 远程 |
|---|---|---|
| 工程根（GitHub 备份） | 全量（含 web-ui/agent-src/docs） | GitHub |
| deploy/wdp-team-platform | 部署包（Dockerfile+overlay+副本） | gitlab platform |
| knowledge/ | 团队知识资产（单一数据源） | gitlab knowledge |

## 快速跳转

- 产研工作流 + WDP 产品知识 → `团队工作台手册.md`
- 整体架构和数据流转 → `docs/01-架构与数据流转.md`
- 智能体设计与能力 → `docs/智能体档案-01/02`
- IT 部署清单 → `docs/02-部署checklist-给IT.md`
- 本机功能测试 → `docs/03-远程访问测试方案.md`
