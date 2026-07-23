# 团队共享 Skills

> 这里存放产品团队的工作方法论，写成 Hermes SKILL.md 格式（Markdown）。
> 部署后，所有团队成员的 agent 会自动加载这里的 skill，按统一规则执行工作。

## 什么是 skill

每个 skill 是一个独立目录，里面有一个 `SKILL.md`，告诉 agent：
- **什么时候用它**（触发条件）
- **怎么做**（分步流程）
- **输出什么**（交付物模板）
- **怎么算做好**（质量检查清单）

## 产品团队首批 skill 清单（待建）

| Skill | 干什么 | 状态 |
|---|---|---|
| `signal-intake` | 信号清洗：会议纪要/客户反馈/语音 → 结构化信号条目 | 待建 |
| `requirement-triage` | 需求校验+建档：信号→候选需求→人工校验→入库 | 待建 |
| `prd-writing` | PRD 撰写（面向 agent 的完整性：数据契约/状态/边界必填） | 待建 |
| `design-handoff-to-dev` | 末端设计自动化：功能定稿→生成给研发的执行脚本/说明 | 待建 |
| `release-tracking` | 节点跟踪：需求全生命周期状态更新+停滞提醒 | 待建 |

## 怎么新建一个 skill

最简单的方式：直接对 agent 说"把 XX 工作流程沉淀成一个 skill"，它会帮你起草，你确认后落到这个目录。

或手动建目录：
```
skills/
└── signal-intake/
    └── SKILL.md
```

SKILL.md 模板见各 skill 目录内的示例。
