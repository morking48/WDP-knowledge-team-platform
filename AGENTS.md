# WDP 产品团队 AI 工作台

本工作区是 WDP 产品团队的 Hermes AI 工作台。团队成员通过它完成信号收集、需求管理、产品设计、知识沉淀等产研工作。

## 首要指引

**涉及产研工作流或 WDP 产品知识时，先读工作区根目录的 `团队工作台手册.md`**——它定义了完整的 AI Native 四层闭环工作流和 WDP 产品知识库索引。

## 目录结构

```
wdp-team-hermes/
├── 团队工作台手册.md        # 核心手册（工作流 + WDP知识库，先读它）
├── skills/                  # 团队 skills（signal-intake / requirement-triage / design-converge 等）
├── knowledge/               # 团队知识资产库（git 版本化，单一数据源）
│   ├── signals/             # 信号层产出
│   ├── requirements/        # 需求档案
│   ├── designs/             # 产品设计稿
│   ├── decisions/           # 决策记录
│   ├── tracking/            # 节点跟踪
│   ├── projects/            # 项目分区（项目档案+项目需求+交付材料）
│   └── team/                # 团队成员档案（画像随对话沉淀）
├── docs/                    # 部署/架构文档 + 智能体档案
├── web-ui/                  # 定制前端+后端（本地开发主战场）
└── agent-src/               # Hermes 官方源码（运行时，勿改）
```

## 工作原则

1. **单一数据源**：团队知识资产只落在 `knowledge/` 目录，git 版本化，不搞第二份清单。
2. **四层闭环**：信号→需求→设计→跟踪，各有对应 skill 和产出目录。
3. **面向 agent 的完整性**：产品设计稿要写清数据契约、状态、边界、执行规则。
4. **人工介入点低门槛**：人只在关键处（信号确认/需求校验/设计把关）介入。
5. **中文交付**：所有交付物正文与回复用中文。

## WDP 知识注意

产品精确数据（版本号/报价/API清单）以在线源为准。本工作台的 WDP 知识是快照 + 在线源路由；若需实时拉在线源（企微文档/飞书），需先配置对应 MCP。未配置时以快照为背景认知，关键数据人工核对。

## 定制后端代码约定（web-ui/api/）

改动 `web-ui/api/` 的自研业务模块（team_*/projects/review/knowledge_ops/me_skills 等）后，跑一次类型检查再交付：

```bash
cd web-ui && npx pyright   # 只查自研模块（pyrightconfig.json 已限定范围），应 0 error
```

- 类型检查只覆盖我们写的模块，不碰官方 Hermes 源码。**pyright 是开发期工具，不需部署到服务器**（服务器只跑 Python）。
- API handler 统一返回契约：成功 `dict`，失败 `(dict, http_status)` 元组，标注用 `api/_wdp_types.py` 的 `ApiResult`（该文件是运行时依赖，必须随代码部署）。
- pyright 报 None 相关错误时优先当真 bug 查（很可能是 `None` 未防御的潜在崩溃点），不要用 `# type: ignore` 图省事糊过去。
