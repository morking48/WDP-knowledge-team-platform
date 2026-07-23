# WDP 团队平台 · 开发任务清单

> 临时工作清单，随开发进展更新。完成项打 [x]。
> 最终交付：本地跑通完整流程 → 交付运维正式部署测试。

## 已完成 ✅
- [x] 多用户认证后端（users.py/auth.py/routes.py/login-multiuser.js）— 用户表/单点登录/角色/登录页
- [x] 登录页（绿白液体玻璃 + 多用户表单）
- [x] 部署包（Dockerfile/k8s/overlay/脚本/README）— 已推 gitlab wdp-team-platform
- [x] 知识库母版（wdp-product-knowledge）— 已推 gitlab wdp-team-knowledge
- [x] 团队 SOUL（6 条铁律，含授权信息保护）
- [x] 工作流 skill（signal-intake / requirement-triage）

## 前端重构（当前最高优先级）🔴
- [ ] **F0 深度复盘 WebUI 交互架构**（面板系统/主题系统/导航/状态管理），产出重构设计方案
- [ ] **F1 工作台交互界面重构**（基于 WebUI 能力，绿白风格：对话/工作台/审核/成员/个人中心）
  - 不是另起炉灶，是在 WebUI 骨架上重构导航 + 主题 + 工作台视图
  - 保留 WebUI 现有能力（chat 引擎/SSE/profile 切换/文件/workspace）

## 后端接口 🔴
- [ ] **R1 工作台后端**：`/api/knowledge/signals|requirements|designs`（解析 markdown frontmatter）+ 详情 + 统计
- [ ] **R3 入库审核后端**：inbox 结构 + 待审列表 + 审核执行（移文件+git commit+建路由）
- [ ] **R4 个人中心后端**：SOUL 读写 / 模型渠道存取 / memory 读写 / 运行日志 / workspace-index 索引
- [ ] **R6 文件上传后端**：chat 上传 → 个人 workspace/uploads + 通知 agent
- [ ] **R8 管理操作后端**：工作台管理员操作（沉淀需求/分配/改态/通知/审核通过/驳回）

## 主 Agent 自动化 🟡
- [ ] **R7 定时任务**：信号定时清洗 / 需求停滞提醒 / 周报 / session 压缩归档

## 前端视图接入（依赖 F1 + 后端）
- [ ] 工作台三 tab（信息/需求/设计）接 R1，成员只读/管理员可管
- [ ] 入库审核界面接 R3（含 chat 确认）
- [ ] 个人中心四子页接 R4（agent/workspace/memory/logs）
- [ ] 登录后默认进对话页（R9）

## 测试与交付 🟢
- [ ] 本地起服务跑通完整流程（登录→对话→工作台→审核→个人中心）
- [ ] 交付运维：更新部署包（含新后端/前端）→ 正式环境部署测试

## 待确认决策
- [ ] knowledge 与 team-platform 是否合并（当前已分开两个仓库）
- [ ] 个人工作库索引（workspace-index）存储格式确认（已设计，待落地到 add-user.sh）
