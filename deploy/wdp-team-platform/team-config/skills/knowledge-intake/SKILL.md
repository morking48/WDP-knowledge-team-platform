---
name: knowledge-intake
description: "多类目知识入库：把会议纪要/原始信息清洗成项目/需求/信号混合条目，判类、补字段、批量提交 submit_review.py 入库审核"
version: 1.0.0
---

# Knowledge Intake · 多类目知识入库

> 产品团队知识库的入口工作流：把多源原始信息（会议纪要/客户反馈/专题会记录）清洗成结构化条目，提交入库审核。
> 与 `signal-intake`（纯信号清洗）不同，本 skill 覆盖**混合类目**场景：一份会议纪要通常同时包含项目、需求、信号。

## 什么时候用这个 skill

- 成员给了一批会议纪要/原始信息，说"帮我归类入库/沉淀到知识库"
- 激活了「沉淀入库模式」，需要按团队规范清洗提交
- 原始信息混合多类目（有项目归属、有在推进的需求、有纯线索）

## 核心判类原则（只看阶段，不看细节定全没）

**别因为"范围/参数/时间没最终定"就退回信号**——已经在做的事就是需求。

| 类目 | 硬信号（命中任一） |
|------|------------------|
| **requirements** | 有责任人+推进动作 / 有版本规划（"放5.17"）/ 涉及验收·交付·测试 / 有明确方案方向在落地 |
| **signals** | 只有"听到个反馈、没人接、没排期、没开发动作"的纯线索 |
| **projects** | 点名了客户或项目（"中建""XX项目"），且知识库无该项目档案 → 提开档申请 |
| **designs** | 只认「设计模式产出」或「带具体文档/链接的提交」；早会里的方案探索/技术讨论算需求不算设计 |

**没有"决策"类目**——拍板结论并进对应需求，不单独立池。

**自检口诀**：判信号前先问"这事有没有人在做/有没有排期验收版本"，有就不是信号。

## 批量入库工作流

1. **先查重**：`python scripts/query_knowledge.py --stats` 看全景 + `--find 关键词` 逐条查，已有进展内容只作 raw_excerpt 背景不单独成条
2. **全量通读**：读完所有文件再判类，不边读边判（避免后文推翻前文判断）
3. **字段两步价值策略**：能推导的自己补（business_value/customer/related_module/target_release），推导不了的**一次问完**，不挤牙膏；成员说"不知道/先这样"就如实留"待补充"并标注
4. **用户确认后再提交**：把判类结果+字段推导列成清单给成员确认，特别是不确定的归属/版本/优先级/客户全称
5. **批量提交**：先交 1 条试水（确认 frontmatter 字段无误），再循环剩余。每条须见 `OK` + `VERIFIED` 才算成功
6. **临时文件**：写到工作目录 `.temp_submit/` 隐藏子目录，全部成功后 `rm -rf .temp_submit` 清理

## 各类目 frontmatter 必填字段

以 `knowledge/<category>/_template.md` 为准，比各 skill 模板更严格。

- **signals**：id/title/type:信号/date/source/category/urgency/confidence/status/description(≤50字)
- **requirements**：id/title/type:需求/priority(P0-P3)/date/source/owner/status + 推导 business_value/related_module/target_release
- **projects（开档）**：id/title/type:项目/date/customer/phase/owner/description/status + bd_owner/tb_contact

**projects 类目需要 id 字段**（格式如 PRJ-YYYYMMDD-NNN），漏了会报"ERROR: frontmatter 缺少必填字段: id"。

## 项目归属标记

内容明确涉及某项目时，frontmatter 必须加 `related_project: <项目名>`：
- 先 `python scripts/query_knowledge.py --projects` 查现有项目列表，用列表里的**准确全称**，不凭记忆写简称
- 查不到 = 该项目还没开档：先提开档申请 `--category projects`，或先标 related_project 待确认后开档
- 拿不准是不是同一个项目，问管理员，别自作主张新开

## BD/TB 对接人处理

项目档案里的 BD/TB 对接人是**外部客户方**，不在团队 18 人名单内：
- `update_member_profile` 会报"未找到成员档案"——这是正常的，不用建团队画像
- BD/TB 信息写在项目档案 frontmatter 的 `bd_owner`/`tb_contact` 字段即可
- 查项目全貌用 `--project "项目名"` 时会带出这些信息

## 入库质量底线

- **不完整的内容先不记录**——如果重要，后面还会提到
- 宁可少入不入，不入残缺/不准确的内容
- 清洗提炼时**不许把多义内容压缩到丢失判断依据**：raw_excerpt 保留原文语境（谁、什么场合说的、关键前后文），宁多勿删

## 提交脚本

```bash
# 先交 1 条试水
python scripts/submit_review.py --title "标题" --category projects --file .temp_submit/xxx.md
# 报 can't open file 立即改
python "$HERMES_HOME/scripts/submit_review.py" --title "标题" --category projects --file .temp_submit/xxx.md

# 试水后批量循环（以 requirements 为例）
for f in .temp_submit/req-*.md; do
  title=$(basename "$f" .md)
  python "$HERMES_HOME/scripts/submit_review.py" --title "$title" --category requirements --file "$f"
done
# 每条须见 OK + VERIFIED

# 全部成功后清理
rm -rf .temp_submit
```

## 参考示例

- `references/intake-example-202607.md`：一次典型的多类目混合入库实例（11 份早会/专题会 → 2 项目 + 7 需求 + 4 信号），含判类理由、关键判断点、BD/TB 映射

## 陷阱

- **heredoc 写多条 markdown 易翻车**：内容含特殊字符（反引号/引号/中文标点）时 shell heredoc 解析失败，改用 Python 写文件更稳妥
- **不要同一路径连续重试**：脚本路径报 can't open file 立即换 `$HERMES_HOME/scripts/`，不在原路径上重试
- **批量提交必须先试水**：projects 类目的 id 字段、requirements 的 type:需求 等必填字段漏了会打回，先交 1 条确认格式再跑剩余
