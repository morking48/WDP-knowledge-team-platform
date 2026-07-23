# WDP 团队工作台 · 开发 TODO（对齐设计文档 + 原型）

> 更新时间：2026-07-22
> 基准：设计稿 DSN-20260720（§2平台能力 / §12管理员操作清单 / §13开发TODO）+ workbench-prototype.html
> 用途：作为后续开发的对齐基准，避免"发现一块补一块"。每完成一项打 [x]。

---

## ✅ 已完成（本地验证通过）

### 基础设施
- [x] 多用户认证（users.json / 单点登录 / 角色 / session）
- [x] 权限隔离（member 访问 admin 接口 403，profile 隔离）
- [x] 全站未登录拦截（多用户模式强制鉴权）
- [x] 客制化前端（照原型重做 workbench.html + wb.css + wb.js/wb2/wb3/wb4）
- [x] 子agent默认用团队模型+key（成员未配key时fallback团队公共key）

### 5大视图
- [x] 对话（真SSE流式 + 会话列表 + 模板chip + 文件上传/拖拽）
- [x] 工作台三tab（信号表/需求看板/设计表，成员只读 vs admin可管）
- [x] 入库审核（待审列表+详情+《入库建议说明》+通过/驳回+git commit）
- [x] 成员管理（增删/停用启用/重置密码/踢下线）
- [x] 个人中心（SOUL编辑/模型渠道CRUD+测试/设备登记/工作库/Memory/日志/上传）

### 知识库互动（已完成部分）
- [x] config驱动分区注册表（knowledge.config.yaml，热扩展）
- [x] library母版分区结构（product-knowledge + archive）
- [x] R1读：/api/knowledge/{signals|requirements|designs|stats|item}（解析frontmatter）
- [x] 所有写操作 git commit（review/ops/admin 共19处）
- [x] 入库模板校验（enforce_template：signals/requirements/designs硬校验，decisions软提示）
- [x] 信号：沉淀为需求（源信号标记已转需求）
- [x] 信号：批量归并（源标记已归档）
- [x] 信号：标记已确认
- [x] 信号筛选（状态/来源/类别/紧急度）
- [x] 需求：分配/改派负责人
- [x] 需求：按负责人分组视图
- [x] 需求：通知组员（写inbox）
- [x] 需求：改status时追加tracking链（写入需求文件frontmatter）
- [x] 设计：新建设计稿（关联需求ID）
- [x] 全局搜索（信号/需求/设计三路）
- [x] 成员通知接收（铃铛+未读角标+标记已读+profile隔离）

---

## ✅ P0 已完成：生命周期状态流转（2026-07-22 补完）

### 需求生命周期
- [x] **改优先级**（P0-P3，弹窗单选）
- [x] **改状态/流转**（待校验→已确认→设计中→研发中→已上线→已关闭，含tracking链追加）
- [x] **关闭需求**（改status=已关闭 + 填关闭原因）

### 信号生命周期
- [x] **标记归档**（改status=已归档）

### 设计生命周期
- [x] **改状态**（草稿→评审中→已定稿→已交付研发→已废弃）
- [x] **定稿说明**（定稿时补说明，记入tracking）

---

## ✅ P1 已完成：派活/追溯/推进（2026-07-22 补完）

### 指派与提醒
- [x] **指派确认人**（信号：指派+发通知+记tracking）
- [x] **指派评审**（设计：指派+发通知）
- [x] **催办**（需求：给owner发催办+记tracking）
- [x] **分配自动通知**（分配负责人时自动通知新负责人）

### 可追溯（双向展示，/api/knowledge/traces）
- [x] **关联信号↔需求↔设计 双向展示**（信号详情/需求卡片显示上下游+可跳转）
- [x] **关联需求**（设计行"关联需求"按钮改requirement_id）

---

## ✅ P2 已完成：数据统计 + 知识库互动补全（2026-07-22 补完）

### 用量统计（设计§2能力13）
- [x] **真实用量统计**（成员管理显示 session数/入库贡献/工作库占用，/api/admin/users?stats=1）

### 知识库互动补全
- [x] **library前端入口**（工作台"📚母版库"tab，展示product-knowledge+archive文件树）
- [x] **decisions决策记录前端入口**（工作台"⚖️决策"tab，列表+新建）
- [ ] **tracking/目录利用**（当前tracking写进各文件frontmatter，已够用；独立目录暂不需要）
- [ ] **项目完成后归档到library/archive**（工作流终点，暂手动，可后续加"一键归档"）

---

## ✅ P3 已完成：主 Agent 定时任务（2026-07-22 补完）

> 本地用 web-ui 内置调度线程执行（api/team_scheduler.py）；线上用 WDP_SCHEDULER_ENABLED 单点控制。
> 管理入口：成员管理页 → ⏰ 主 Agent 定时任务。默认全部关闭，admin 可开启/编辑。
- [x] 4 个内置任务（信号清洗/需求停滞/周报/session归档），进程内执行
- [x] 默认全部关闭，admin 可开关
- [x] 改执行周期（cron，含非法拦截）+ 改参数
- [x] 立即运行 + 看结果
- [x] 自定义任务（自然语言 prompt，增删改）
- [x] 自动调度到点触发（croniter，实测通过；修复时区 bug）
- [x] 部署文档（docs/定时任务部署说明.md：多副本单点/PVC持久化/CronJob备选）
- [ ] 自定义 prompt 任务真正接主 Agent 执行（当前登记 pending_agent，部署时接 LLM）

---

## ⏸️ 明确延后（设计标注 Phase3/迭代，本期不做）
- 自定义个人skills（安装/创建）— §2能力9
- 跨agent产品讨论 — §2能力14 / Phase3
- 拖拽改状态的拖拽交互（可先用下拉/按钮替代）

---

## 🚧 部署相关（交运维规划，非本地开发）
- [x] 两仓库push到gitlab（platform + knowledge）✅ 2026-07-22 已推送
- [ ] init-knowledge.sh对齐新结构（library/ + knowledge.config.yaml + 三模板）
- [ ] 入库后自动push到gitlab（实时/定时二选一）
- [ ] 部署文档补git凭证配置（K8s Secret挂gitlab token）
- [ ] 主agent独立部署 + cron挂载

---

## 建议开发顺序
1. **P0生命周期流转**（一次做齐信号/需求/设计三组状态操作）← 最影响闭环，优先
2. **P1可追溯双向展示 + 指派/催办**（让闭环真正串起来）
3. **P2 library前端入口 + decisions入口**（知识库互动补全）
4. **P2用量统计**（数据可视化）
5. P3主agent自动化 + 部署（部署阶段）
