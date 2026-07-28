# 团队共享 Skills

> 这里存放产品团队的工作方法论，写成 Hermes SKILL.md 格式（Markdown）。
> 部署后，所有团队成员的 agent 会自动加载这里的 skill，按统一规则执行工作。

## 什么是 skill

每个 skill 是一个独立目录，里面有一个 `SKILL.md`，告诉 agent：
- **什么时候用它**（触发条件）
- **怎么做**（分步流程）
- **输出什么**（交付物模板）
- **怎么算做好**（质量检查清单）

## 团队 skill 清单（现役）

| Skill | 干什么 |
|---|---|
| `signal-intake` | 信号清洗：会议纪要/客户反馈/语音 → 结构化信号条目 |
| `requirement-triage` | 需求校验+建档：信号→候选需求→人工校验→入库 |
| `design-converge` | 设计收敛工作流（🎯 设计模式激活）：批量拷问锁定意图→不可逆决策标风险→零歧义方案文档 |
| `wdp-online-knowledge-sync` | WDP 在线知识源同步（飞书/企微/API 文档路由） |
| `wdp-workbench-ui` | 工作台 UI 规范 |

> 团队 skill 分布于工程 `skills/` 与 `hermes-home/skills/wdp-team/`；成员 agent 实时扫描加载。
> admin 可在「团队 Agent」页用「技能助手」对话编辑、发布（发布前有 frontmatter 硬校验 + diff 展示）。

## 怎么新建/编辑 skill

- **可视化（推荐）**：团队 Agent 页 → 团队技能面板 → 「＋ 新建技能」或点某 skill 的「🤖 技能助手」对话编辑 → 存草稿 → 「🚀 发布」同步成员。
- **对话沉淀**：对 agent 说"把 XX 工作流程沉淀成一个 skill"，它帮起草。
- **手动**：建目录 `skills/<name>/SKILL.md`，含 YAML frontmatter（name/description 必填）+ 正文。

内置 4 个核心 skill（signal-intake/requirement-triage/wdp-online-knowledge-sync/wdp-workbench-ui）受保护，不可删除。
