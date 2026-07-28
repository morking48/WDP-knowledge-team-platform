# 对话 Agent 设计与能力档案

> WDP 团队 AI 工作台 · 智能体留档 · 第 1 篇：对话 Agent
> 版本：v1.0 · 基线日期：2026-07-28 · 依据：代码实证（非记忆推测）
> 维护约定：能力有增删时同步更新本档，标注变更日期

---

## 〇、一句话定位

**对话 Agent = 每位团队成员的私人产研助手**，是平台唯一"全功能、天天用"的主力智能体。成员通过与它对话完成信号收集、需求沉淀、知识查询、项目协作，它是产研四层闭环的加速器，而非通用问答机器人。

---

## 一、设计目标与演进全过程

### 1.1 设计初衷（为什么要它）
团队产研工作分散在个人脑子、聊天记录、会议纪要里，缺乏统一沉淀。目标是给每个成员配一个"懂团队工作流、懂知识库结构、能主动帮忙落库和查询"的 agent，把零散信息收敛成结构化团队知识资产。

### 1.2 演进路线（实际发生的迭代，按时间）
| 阶段 | 能力增量 | 动机 |
|---|---|---|
| 初版 | 基于官方 AIAgent + 团队 SOUL 规训，懂四层闭环概念、能提交入库 | 让 agent 从"通用问答"转成"产研助手" |
| 加成员画像 | SOUL 加画像沉淀规训 + `update_member_profile.py` | 让 agent 越用越懂团队每个人 |
| 加个人技能 | SOUL 加技能沉淀规训 + `save_personal_skill.py` | 帮成员沉淀可复用工作方法 |
| 加个人工作库 | SOUL 加工作库定位规训 + chat/start 传真实工作库路径 | 让 agent 默认在成员本地文件区干活，不乱搜盘符 |
| 画像强触发（2026-07） | 画像规训升级为两级触发（管理员直述=必调脚本） | 解决触发率低、agent 只口头应付的问题 |
| **查询能力（2026-07-28 本轮）** | `query_knowledge.py` 查询脚本 + SOUL 查询问答章节 + 项目分区认知 + index 自动刷新 | 补齐"只会写不会查"的短板，修好路径够不到知识库的地基漏洞 |

### 1.3 设计哲学（对齐企业级 Agent 规范）
- **确定性逻辑用代码，生成/理解交 LLM**：提交、画像、查询全是 Python 脚本硬跑，LLM 只做"理解意图→选参数→把结果讲成人话"。
- **单 Agent + 多 Tool（脚本）**，不滥用多智能体：对话 agent 一个，通过 4 个专用脚本扩能力，工具集不膨胀。
- **控上下文**：查询脚本 + index 渐进披露，避免 agent read_file 硬翻整库塞爆 context。
- **人在环**：所有入库走"提交→管理员审核"，agent 不直接改团队知识库。

---

## 二、技术架构（代码实证）

| 维度 | 现状 | 位置/证据 |
|---|---|---|
| **Agent 内核** | 官方 Hermes `AIAgent`（run_agent），非自研 | streaming.py:138 `from run_agent import AIAgent` |
| **默认模型** | moonshotai/kimi-k3（openrouter） | hermes-home/config.yaml |
| **可切模型** | 成员可在个人中心配自己渠道（如 copilot claude-opus-4.8），三级 fallback | channels.py |
| **系统提示（SOUL）** | 走官方 `_cached_system_prompt`（缓存友好，会话内字节稳定） | streaming.py:4881 |
| **运行时指引** | WebUI 环境/进度提示走 `ephemeral_system_prompt`（不入历史，不污染缓存） | streaming.py:252,5056 |
| **工作目录** | 成员启用的个人工作库（devices.json active_workspace） | chat/start 传真实路径 |
| **工具集** | 官方全功能（terminal/file/web搜索/skills 等），未做裁剪 | config.yaml disabled_toolsets: [] |
| **传输** | SSE 流式（思考过程+工具状态透明展示） | streaming.py |

---

## 三、已具备的能力（逐项 · 代码实证）

### 能力 A：懂团队工作流与知识库结构
- 理解产研四层闭环：信号→需求→设计→决策
- 懂项目分区：项目档案 / 项目需求(PREQ) / 交付材料(DLV)
- 知道用 `knowledge/index.md` 导航（渐进披露），不全目录扫
- **依据**：SOUL §核心概念 + §项目分区

### 能力 B：提交入库（写）
- 成员说"记下来/这是个需求/提交入库"→ agent 整理成规范 frontmatter → 跑 `submit_review.py` 落 inbox → 通知管理员审核
- 硬验证 loop：必须看到 `OK + VERIFIED` 才算成功，否则按错误补字段重试
- **脚本**：`hermes-home/scripts/submit_review.py`
- **依据**：SOUL §提交入库

### 能力 C：知识库查询（读）★本轮新增
| 查询 | 命令 | 场景 |
|---|---|---|
| 全景 | `query_knowledge.py --stats` | "知识库现在有什么" |
| 搜索 | `--find 关键词` | "金仓相关有哪些信号" |
| 项目列表 | `--projects` | "现在有哪些项目" |
| 项目全貌 | `--project 名` | "南水北调什么进展" |
| 成员名下 | `--member 姓名` | "张健负责哪些需求" |
| 条目详情 | `--item ID` | "SIG-xxx 具体内容" |
- 靠 `HERMES_KNOWLEDGE_DIR` 定位（修好了 agent cwd 在工作库、相对路径够不到知识库的地基漏洞）
- **脚本**：`hermes-home/scripts/query_knowledge.py`
- **依据**：SOUL §查询问答

### 能力 D：成员画像沉淀
- 两级触发：①【强触发·必调】管理员/成员直接陈述某人能力职责时 ②【观察触发·主动】协作中真实体现能力时
- 跑 `update_member_profile.py` 融合更新画像（≤150字），"不执行=违规"
- **脚本**：`hermes-home/scripts/update_member_profile.py`
- **依据**：SOUL §成员画像

### 能力 E：个人技能沉淀
- 发现成员反复做某类任务/磨出可复用方法时，主动提议存成个人 skill（存成员 profile，默认启用可开关）
- **脚本**：`hermes-home/scripts/save_personal_skill.py`
- **依据**：SOUL §个人技能

### 能力 F：个人工作库操作
- 成员提文件不给路径时，默认在其个人工作库找/存，不乱搜盘符、不编内容
- **依据**：SOUL §个人工作库

### 能力 G：主动建议 + 规范交付
- 对话中识别到价值线索时主动问"要不要沉淀为信号/需求"
- 回答简洁直接、中文交付
- **依据**：SOUL §工作风格

### 能力 H：官方全套通用能力（继承 AIAgent）
- terminal 执行、文件读写、web 搜索、跨会话记忆、skill 加载等
- **注意**：hermes-home/skills 下有 80+ 个官方自带 skill（apple/creative/mlops 等），与团队产研无关但 agent 能加载；团队专用 skill 实际只有 `signal-intake`、`requirement-triage`（+ wdp-team 下几个）

---

## 四、配套资产清单

### 4.1 专用脚本（agent 的"手"）
| 脚本 | 作用 | 读/写 |
|---|---|---|
| `submit_review.py` | 提交入库审核 | 写 |
| `query_knowledge.py` | 知识库查询（6种） | 读 |
| `update_member_profile.py` | 更新成员画像 | 写 |
| `save_personal_skill.py` | 沉淀个人技能 | 写 |

（均在 `hermes-home/scripts/`，靠 `HERMES_KNOWLEDGE_DIR`/`HERMES_HOME` 定位，部署时 Dockerfile 复制进镜像）

### 4.2 规训（SOUL）章节
身份定位 / 四层闭环概念 / 知识库导航 / 成员画像(两级触发) / 个人技能 / 个人工作库 / 提交入库 / **查询问答** / **项目分区认知** / 工作风格
（文件：`hermes-home/SOUL.md`，部署模板 `deploy/wdp-team-platform/team-config/SOUL.md.team`）

### 4.3 团队 skill（方法论，agent 按需加载）
- `signal-intake`（信号清洗方法）
- `requirement-triage`（需求建档方法）
- 成员对话时说"用 signal-intake 清洗这段纪要"，agent 加载对应 skill 执行

---

## 五、当前边界与已知短板（诚实留档）

| 短板 | 说明 | 优化候选方向 |
|---|---|---|
| 官方 skill 噪音 | 80+ 官方 skill 与团队无关，可能干扰 agent 选择 | 考虑裁剪 disabled，只留团队相关 |
| 项目辅助浅 | agent 懂项目概念，但不能直接辅助开档/建项目需求（只能引导去工作台点） | 深接项目分区 |
| 查询仅人读 | query_knowledge 纯文本输出，专职 agent 无法机器解析调用 | 需要时加 `--json` 模式（暂不做，避免过度设计） |
| 无查询审计 | 谁查了什么无 trace | 轻量场景暂不做 |
| 主动性弱 | 靠成员触发，不会主动推送（如新信号提醒） | 属专职 agent/定时任务范畴 |

---

## 六、预期能力（规划中，未实现）

按盘点后与用户确认的优化方向，对话 Agent 后续预期：
1. **深接项目分区**：能辅助成员开档、建项目需求、查项目进展（部分已通过查询能力覆盖）
2. **更强的主动性**：识别到关键线索主动提示落库/派单（需配合专职 agent）
3. **官方 skill 裁剪**：收敛到团队相关 skill，降低选择噪音

---

*本档随能力迭代更新。下一篇：4 个专职 Agent（归并/审核/规则/技能）设计档案。*
