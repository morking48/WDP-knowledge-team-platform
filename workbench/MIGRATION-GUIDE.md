# WDP 团队工作台 · 迁移工作说明（给接手的 Hermes Agent）

> 读者：接手本项目的 Hermes Agent（个人 hermes）。
> 来源：原 team hermes（F:\wdp-team-hermes，即将关闭服务）。
> 任务：阅读本文后，无缝接手 WDP 团队工作台工程，从「WebUI 改造（前端重构）」继续开发。
> 本文含：①工程现状与边界 ②要拷贝什么/清理什么 ③历史对话查询方法 ④记忆灌注 ⑤接续开发任务 ⑥关键决策与铁律 ⑦gitlab 仓库与凭证安全。

---

## 一、这是什么项目（30 秒理解）

把单机版 Hermes WebUI 升级为 **WDP 产品团队的多用户 AI 工作台**：
- 每个成员有独立风格的 agent（独立 memory/skills/对话/个人工作库）
- 共享唯一团队知识库（`knowledge/`，git 版本化，单一数据源）
- 三大工作组件：信息（信号）/ 需求 / 产品设计，自然语言 chat 调用
- 团队工作台可视化：成员只读，管理员（guanjie）可管理操作
- 部署：公网可访问，Linux + K8s 集群，Jenkins CI/CD

**当前阶段**：后端（多用户认证）已完成并测试通过；部署包与知识库已推 gitlab；**正要做「WebUI 前端重构」**（绿白主题 + 工作台/审核/成员/个人中心面板）。这是你要接手的第一步任务。

---

## 二、工程目录与边界（拷贝前先看）

原工程根目录：`F:\wdp-team-hermes\`

### ✅ 要拷贝的（产品工程本体 + 运行数据）
```
web-ui/            # WebUI（含多用户定制，开发主战场，后续重构在这里做）
agent-src/         # Hermes agent 官方源码（git 仓库，未改核心）
knowledge/         # 团队知识库（git 仓库，已推 gitlab wdp-team-knowledge）
deploy/            # 部署包（git 仓库，已推 gitlab wdp-team-platform）
skills/            # 团队工作流 skill（signal-intake / requirement-triage）
workbench/         # 开发工作区（原型 + HANDOVER.md + TASK-LIST.md）
团队工作台手册.md    # 团队纲领（工作流 + WDP 知识库索引）
AGENTS.md          # 项目上下文
hermes-home/       # 运行数据（含 memories/对话记录/config，见下）
```

### 🗑️ 拷贝后清理的（缓存/测试残留/敏感凭证）
```
web-ui/api/__pycache__/ 及各 __pycache__/       # Python 缓存，可再生
hermes-home/audio_cache/ image_cache/ images/ cache/ lsp/   # 缓存，可再生
hermes-home/*_cache.json                        # 模型缓存，可再生
hermes-home/webui-test*/  *.log                 # 测试残留
hermes-home/auth.json auth.lock *.lock          # 敏感凭证 + 锁（新环境重配）
.monitor baseline-knowledge.txt                 # 根目录临时文件
```

### ⚠️ 凭证敏感（勿带进 git，勿外泄）
- `hermes-home/auth.json`、webui `.sessions.json` — 删除，新环境重配
- knowledge/ 和 deploy/ 里的 `.git/` 目录**保留**（是 git 仓库，别删）

---

## 三、历史对话记录怎么查（不迁移也能用）

原 team hermes 的对话记录**不压缩、原样保留在本地**（拷贝后本地会清理，但你可提前备份这几样）：

| 内容 | 路径（原 F:\wdp-team-hermes 下） | 用途 |
|------|------|------|
| 全部会话 FTS 索引 | `hermes-home/state.db` | 全文检索历史对话 |
| 单个会话记录 | `hermes-home/webui/sessions/*.json` | 结构化对话 JSON |
| 会话运行 journal | `hermes-home/webui/sessions/_run_journal/` | 每轮运行详情 |

**查询方法**：把这些备份到安全位置后，任何时候想查"当时某决策怎么定的"，把 `HERMES_HOME` 指向该备份目录，用 hermes 的 `session_search` 工具全文检索即可。

> 💡 真正有价值的结论已沉淀进 memories / knowledge/designs / 团队手册 / gitlab 代码，对话记录多为过程性探索，备份 state.db + sessions/ 即可，不必全量迁移。

---

## 四、记忆灌注（接手后先做）

把以下内容灌入你的持久记忆（memory 工具），确保你一开始就有团队上下文：

1. **读 `hermes-home/memories/MEMORY.md` 和 `USER.md`**——这是原 hermes 沉淀的：
   - 团队铁律与 AI Native 工作流（四层闭环）
   - WDP 产品知识要点（开放平台定位/五大主线/国产化/报价）
   - 汇报口径铁律
   - WDP 在线源路由
   - 工作台概念模型（个人 chatbox / 团队工作台 / 入库审核）
   - **guanjie 的工作偏好**（产出归置指定目录、绿白玻璃设计风格、先粗糙能用、先深化设计再开发、数据走git、并行子agent后要整合检查）
2. **读 `团队工作台手册.md`**——团队纲领（工作流 + WDP 知识库索引）
3. **读 `workbench/HANDOVER.md`**——完整交接文档（架构决策/已完成/未完成/gitlab/安全提醒）

灌完后，你应能复述：团队 6 条铁律、工作台四层闭环、个人 chatbox vs 团队工作台关系、主/子 Agent 分工。

---

## 五、接续开发任务（从这里开始）

**当前任务：WebUI 前端重构**（在 `web-ui/` 上进行）。完整任务清单见 `workbench/TASK-LIST.md`。

### 已定方案（深度复盘结论，勿推翻）
基于 WebUI 能力重构工作台交互（**不是外挂独立面板，是换皮 + 重组面板**）：

1. **主题层**：新增 `data-skin="wdp"` 绿白皮肤（改 `web-ui/static/style.css` 的 `:root` 变量为绿白：`--accent:#16a34a`、`--bg:#f4faf6` 等）+ 新增 `wdp-workbench.css` 覆盖层（液体玻璃 backdrop-filter、宽 rail、淡绿网格背景）
2. **导航层**：保留 `data-panel` + `switchPanel()` 机制（`web-ui/static/panels.js` ~line 203），把 rail 改造成宽展开式（图标+中文标签+分组：工作/管理/我的），导航项：对话/工作台/审核(admin)/成员(admin)/个人中心/设置
3. **面板层**：新增 panelWorkbench / panelReview / panelMembers / panelMe（复用 panel-view + 懒加载机制）；chat 引擎完全不动只换皮 + 文件上传入口 + 模型选择器

**关键原则**：同一套骨架/导航/主题，工作台与 chat/kanban/memory 在同一绿白世界，**不割裂**。

**视觉/交互蓝本**：`workbench/prototypes/workbench-prototype.html`（完整可交互原型，照它做）

### 后续任务（重构后）
- 后端接口 R1-R9：knowledge 接口（解析 markdown frontmatter）/ 入库审核 / 个人中心（SOUL/模型渠道/memory/日志/workspace-index）/ 文件上传 / 管理操作
- 主 Agent 定时任务 R7：信号清洗 / 停滞提醒 / 周报 / session 归档
- 最后：本地跑通完整流程 → 更新部署包 → 交付运维正式部署

---

## 六、关键架构决策（已定，勿推翻）

1. **部署**：方案 A 单入口多副本集群（Ingress TLS → 2 副本 WebUI 4C8G + 共享卷 knowledge/profiles + 独立主 Agent + sticky session）
2. **隔离**：复用 WebUI 原生 `hermes_profile` cookie → thread-local 切 profile（issue #798），同副本多用户互不干扰
3. **概念**：个人 chatbox 干活（多 session）/ 团队工作台只看（管理员可管）/ 归档连接（提交→审核→入库）
4. **主/子 Agent**：异步协作不直接通信，靠 inbox/knowledge/kanban；入库审核执行者=主 Agent
5. **SOUL 三层**：团队(AGENTS.md，6铁律) > 个人(SOUL.md) > 项目(.hermes.md)
6. **个人工作库**：本体留本地设备，服务器存索引（workspace-index/），机器指纹+指纹文件双因子鉴别（不用 IP），读不到不编造
7. **知识更新**：数据（知识/skill/SOUL）走 git 不重新部署；代码改动才重新 build 镜像

---

## 七、团队铁律（team-soul.md，必须遵守并传递给成员 agent）

1. **单一数据源**：团队知识只认 knowledge/，不搞第二份清单
2. **知识优先级**：团队库 > 个人 memory > 模型自身知识
3. **工作流产出收敛**：信号/需求/设计必须结构化入 knowledge/，可追溯（需求追信号、设计追需求）
4. **汇报口径**：WDP=AES唯一开放平台层；国产化=金仓KingbaseES(非达梦)；编辑器五大主线(不含废弃)；成果诚实(雏形≠已支持)
5. **环境鉴别防幻觉**：读文件先声明环境，读不到/指纹不符明确提示，绝不编造
6. **不可获取授权信息**：凭证禁硬编码/禁入git/禁回显，统一管理员授权

---

## 八、gitlab 仓库（内网 gitlab.51cloud.local）

| 仓库 | 地址 | 内容 | 分支 |
|------|------|------|------|
| 部署包 | `Maguanjie/wdp-team-platform.git` | Dockerfile/k8s/overlay/team-config/scripts/README | main |
| 知识库 | `Maguanjie/wdp-team-knowledge.git` | knowledge/ 全部 + 母版 | master |

- 推送凭证：guanjie 提供的 token（走 `oauth2:token` 方式）。
- ⚠️ **最终目标**：提交到 gitlab 的是**纯粹完整、面向产品团队的工作台工程**——web-ui + agent-src + deploy + knowledge + skills + team-config + docs，**不含** hermes-home(运行数据)/state.db/对话记录/缓存/凭证。

---

## 九、安全提醒（务必处理）

1. **飞书 app_secret 重置**：母版原文件硬编码的凭证已在历史暴露 → 提醒 guanjie 去飞书开放平台撤销重置
2. **gitlab token 重置**：guanjie 提供的 token 已在对话暴露 → 提醒撤销重建
3. **授权信息铁律**：所有凭证只走环境变量/K8s Secret/凭据管理器，禁硬编码/禁入 git/禁对话回显

---

## 十、快速上手清单（按序执行）

- [ ] 1. 拷贝工程目录（见第二节"要拷贝的"）到你的工作区
- [ ] 2. 清理缓存/测试残留/敏感凭证（见第二节"要清理的"）
- [ ] 3. 备份 state.db + webui/sessions（历史对话，见第三节）
- [ ] 4. 记忆灌注（读 memories/手册/HANDOVER，见第四节）
- [ ] 5. 读 workbench/TASK-LIST.md 确认当前任务
- [ ] 6. 开始 WebUI 前端重构：新增 data-skin="wdp" 绿白皮肤（见第五节方案 + 原型蓝本）
- [ ] 7. 重构完成后做后端接口 R1-R9，本地跑通，更新部署包，交付运维

> 有问题优先查 `workbench/HANDOVER.md`（最全）和 `团队工作台手册.md`。祝接手顺利。
