# 团队知识库

> WDP 产品团队的**单一数据源**（Single Source of Truth）。
> 独立 git 仓库，所有团队知识资产落在这里，可追溯、可版本化。
> 分区结构由 `knowledge.config.yaml` 统一声明，后端读配置而非硬编码——**加/改分区只改那一个文件**。
> 配套仓库：工作台平台代码 → [wdp-team-platform](http://gitlab.51cloud.local/Maguanjie/wdp-team-platform)（部署/技术文档见其 README 与 docs/）

## 两大分区

```
knowledge/
├── knowledge.config.yaml       ★ 分区注册表（单一配置源）
│
├── 【工作文件区】产研流转中的活文件（频繁增改）
│   ├── signals/          信号（结构化事实）
│   ├── requirements/     需求档案
│   ├── designs/          产品设计稿
│   ├── decisions/        决策记录
│   ├── tracking/         节点跟踪
│   ├── projects/         项目分区（每个项目一个子目录，物理隔离）
│   │   └── <项目名>/
│   │       ├── project.md          项目档案（PRJ，含客户/商机号/阶段/负责人/BD/TB）
│   │       ├── requirements/       项目需求（PREQ，从信号池沉淀转入）
│   │       └── deliverables/       交付材料（DLV，绑定项目需求，售前/售中/售后）
│   └── team/             团队成员档案（18人，能力画像随对话自动沉淀）
│
└── library/  【母版知识库】相对稳定的沉淀
    ├── product-knowledge/   在线知识合集（母版）：产品知识索引 + 在线源同步脚本 + 业务场景 prompt 模板
    └── archive/             历史归档：完成/上线后从工作区归档过来的设计稿、复盘、资料
```

**工作文件区 vs library 的区别**：
- **工作文件区**：信号→需求→设计→跟踪的产研闭环，状态流转、频繁增改。通过 `/api/knowledge/<分区>` 读写，走「提交入库→管理员审核」流程。
- **library 母版知识库**：相对稳定。`product-knowledge` 是"当前产品是什么"的在线知识路由（skill 母版）；`archive` 是"我们做过什么"的历史沉淀。不走信号/需求那套流转接口。

## 数据流转

```
原始信息（会议纪要/客户反馈/聊天记录/语音）
    ↓  signal-intake skill 清洗（或对话框「📥 信号清洗模式」）
signals/            信号
    ↓  requirement-triage skill 归并 + 人工校验（决策中心审核）
requirements/       需求档案（带优先级/负责人/溯源）
    ↓  design-converge skill / 对话框「🎯 设计模式」
designs/            设计稿（面向 agent 的完整性）
    ↓  研发实施 + 上线
tracking/           节点跟踪
    ↓  项目完成后归档
library/archive/    历史资料沉淀
    ↓  上线效果回流成新信号（形成闭环）
signals/

【项目分区并行】signals/（统一入口）→ 沉淀为 projects/<项目>/requirements/（项目需求）
                → projects/<项目>/deliverables/（交付材料，绑定项目需求）
```

`decisions/` 贯穿全流程；`library/product-knowledge/` 作为产品知识背景随时被引用。

## 各分区规范

| 分区 | 内容 | 命名规范 | 模板 | ID 前缀 |
|---|---|---|---|---|
| `signals/` | 清洗后的结构化信号 | `YYYY-MM-DD-<标识>.md` | `_template.md` | SIG |
| `requirements/` | 需求档案 | `REQ-YYYYMMDD-<标识>.md` | `_template.md` | REQ |
| `designs/` | 设计稿 | `DSN-YYYYMMDD-<标识>.md` | `_template.md` | DSN |
| `decisions/` | 决策记录 | `DEC-YYYYMMDD-<标识>.md` | `_template.md` | DEC |
| `tracking/` | 节点跟踪 | 按需求ID组织 | - | - |
| `projects/<项目>/project.md` | 项目档案 | 项目目录名 | `projects/_template.md` | PRJ |
| `projects/<项目>/requirements/` | 项目需求 | `<日期>-PREQ-*.md` | `projects/_req_template.md` | PREQ |
| `projects/<项目>/deliverables/` | 交付材料（绑定项目需求） | `<日期>-DLV-*.md` | `projects/_dlv_template.md` | DLV |
| `team/` | 团队成员档案 | `<姓名>.md` | `team/_template.md` | - |
| `library/product-knowledge/` | 在线知识合集（母版） | 自由组织 | - | - |
| `library/archive/` | 历史归档 | 按项目/时间组织 | - | - |

字段规范以各分区 `_template.md` 的 frontmatter 为准；必填字段清单在 `knowledge.config.yaml` 的 `required_fields`（预留入库校验开关 `enforce_template`）。

## 使用规则

1. **单一数据源**：所有团队知识资产只落这一个仓库，不搞第二份清单/备份。
2. **git 版本化**：所有变更走 git 提交，可追溯；配 gitlab 远程 `gitlab.51cloud.local/Maguanjie/wdp-team-knowledge.git`（master 分支）。
3. **frontmatter 按模板**：每类文件的元数据字段按 `_template.md` 填写。
4. **人工校验点**：关键节点（信号→需求、设计定稿、入库审核）保留人工校验入口。
5. **可追溯**：需求追源信号、设计追需求、信号追原始信息。
6. **分区扩展**：新增分区在 `knowledge.config.yaml` 声明即生效，无需改代码。

## 更新方式

知识库内容更新 = 本地 `git commit` + `push` → 服务器 `pull`，几秒生效，**不碰部署、不重启服务**。
