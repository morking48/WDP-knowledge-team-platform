# WDP 产品团队共享 Hermes 工作台

> 目标：在你们自己的服务器上部署一套 Hermes Agent，作为产品团队 AI Native 工作流的执行引擎。
> 团队成员通过企微/Web 浏览器使用，沉淀的团队知识资产全部落地在本仓库（Markdown + git 版本化）。

## 目录结构

```
wdp-team-hermes/
├── README.md                  # 本文件
├── docs/                      # 方案文档（给负责人/IT 看）
│   ├── 01-架构与数据流转.md
│   ├── 02-部署checklist-给IT.md
│   └── 03-远程访问测试方案.md
├── skills/                    # 团队共享 skills（你的工作规则/方法论 → AI 可执行）
│   └── README.md
├── knowledge/                 # 团队知识资产库（git 版本化）
│   ├── signals/               # 信号层：清洗后的结构化信号
│   ├── requirements/          # 需求档案（带 frontmatter：状态/优先级/负责人）
│   ├── designs/               # 产品设计（面向 agent 的完整性设计稿）
│   ├── decisions/             # 决策记录
│   ├── knowledge/             # 产品知识沉淀
│   └── tracking/              # 节点跟踪数据
├── deploy/                    # 部署相关（docker-compose / systemd / 配置模板）
└── scripts/                   # 启动脚本
    └── start-test-server.bat  # 本机测试服务一键启动
```

## 工作流

### 第一步：本机功能验证（你自己做）

1. 双击 `scripts/start-test-server.bat` 启动本机服务
2. 浏览器打开 `http://127.0.0.1:8799`
3. 按 `docs/03-远程访问测试方案.md` 验证功能

### 第二步：部署到服务器（IT 做）

功能验证 OK 后，把 `docs/02-部署checklist-给IT.md` 转给 IT，按清单在你们服务器部署。

### 第三步：团队使用（同事做）

IT 部署完成后，同事通过服务器 IP 或企微入口使用，团队知识资产沉淀到 `knowledge/`。

## 快速跳转

- 想了解整体架构和数据怎么流 → `docs/01-架构与数据流转.md`
- IT 要部署，需要一份不带术语的清单 → `docs/02-部署checklist-给IT.md`
- 本机功能怎么测 → `docs/03-远程访问测试方案.md`
