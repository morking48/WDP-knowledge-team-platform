# F1 前端重构 · 落地设计（原型 → 真实 web-ui 映射）

> 状态：设计稿，待 guanjie 审批决策点后开工
> 目标：把 workbench-prototype.html 的 5 大视图，落到真实 web-ui（static/）上，换皮+重组+新面板，复用 chat 引擎/SSE/profile
> F0 复盘结论见文末附录

---

## 一、原型 5 视图 → web-ui 映射

| 原型视图 | web-ui 落地方式 | 复用 or 新增 |
|---|---|---|
| **对话** (viewChat) | 复用现有 `panelChat`（chat 引擎/SSE/composer/会话侧栏全都在），只换皮 + 加模板 chip 条 + 文件上传入口 | 复用为主 |
| **工作台** (viewBoard 三tab) | 新增 `panelWorkbench`（信号表/需求看板/设计表），接 R1 后端 | 新增 |
| **入库审核** (viewReview) | 新增 `panelReview`（admin），接 R3 | 新增 |
| **成员管理** (viewMembers) | 新增 `panelMembers`（admin），接已完成的 /api/admin/users | 新增 |
| **个人中心** (viewMe 四子页) | 新增 `panelMe`（Agent/工作库/Memory/日志），接 R4 | 新增 |

## 二、三层改造（HANDOVER 已定方案）

### 主题层（绿白皮肤）
- 新增 `static/style.css` 里 `:root[data-skin="wdp"]` 段：绿白变量（`--accent:#16a34a` / `--bg:#f4faf6` / 液体玻璃 / 淡网格背景），亮/暗两套
- 原型的品牌绿 `#16a34a`、玻璃 `rgba(255,255,255,.6)`、淡网格 `linear-gradient 28px` 全部搬进来
- `static/boot.js` 的 `_SKINS` 数组加一项 `{name:'WDP', value:'wdp', colors:['#16a34a','#15803d','#22c55e']}`
- 团队实例默认激活 wdp 皮肤（settings.json 或启动注入）

### 导航层（rail 改造）
- rail（index.html line182-195 桌面 + line200-212 移动）**两份都改**
- 按原型分组：**工作**（对话/工作台）/ **管理**（审核·admin/成员·admin）/ **我的**（个人中心）
- admin-only 项按 `/api/auth/me` 的 role 显隐
- 新增 4 个 `data-panel`：workbench / review / members / me

### 面板层（新增 4 面板）
- 复用 `.panel-view` + `switchPanel()` + `showing-<name>` + 懒加载机制
- 每个新面板：index.html 加 `<div class="panel-view" id="panelXxx">` + panels.js 加渲染函数 + switchPanel 分支
- **chat 引擎完全不动**，只换皮

## 三、关键决策点（待拍板）

**Q1｜皮肤默认激活方式**
团队实例要默认就是绿白 wdp 皮肤。三种做法：
- A. 启动脚本注入 `HERMES_WEBUI_DEFAULT_SKIN=wdp` 环境变量（若 web-ui 支持）
- B. 预置 team 的 settings.json 里 `skin:"wdp"`
- C. boot.js 里对团队实例硬默认 wdp
→ 建议 **B**（干净、可回退、不改代码逻辑）。你选？

**Q2｜admin-only 显隐的数据源**
原型用 demo-bar 假切换。真实要按登录用户角色。已完成的多用户后端有 `/api/auth/me` 返回 role。
→ 前端启动时拉 `/api/auth/me`，`role==='admin'` 才显示审核/成员。确认？

**Q3｜新面板先做壳还是先接数据**
按你"先粗糙能用、先出效果"偏好：
- A. 先做 4 面板的**静态壳**（绿白皮 + 原型布局 + Mock 数据），你先看整体效果，再逐个接 R1-R9 真接口
- B. 一个面板做到底（壳+接口）再下一个
→ 建议 **A**（先立骨架看效果，符合你偏好）。你选？

**Q4｜改造范围隔离**
web-ui 是 fork 的官方版，改动要可控。建议所有团队定制：
- 皮肤 → 单独 `static/wdp-workbench.css`（覆盖层，不改 style.css 主体，只在 style.css 末尾加一行 `@import` 或 index.html 引一个 link）
- 新面板 JS → 单独 `static/wdp-panels.js`（不塞进 7980 行的 panels.js）
→ 好处：团队定制集中、易维护、跟官方 web-ui 冲突面小。确认？

## 四、F1 第一步（拍板后立即做）
1. 建 `wdp-workbench.css`：绿白皮肤 + 4 面板样式（照原型搬）
2. `boot.js` 注册 wdp skin
3. index.html：rail 加 4 导航项（分组）+ 4 个 panel-view 空壳
4. `wdp-panels.js`：4 面板渲染函数（先 Mock 数据）+ switchPanel 接入
5. 启动看效果（你自己开浏览器）

---

## 附录：F0 复盘结论（web-ui 交互架构）

| 层 | 机制 | 位置 | 扩展方式 |
|---|---|---|---|
| 主题 | `:root` 变量 + `[data-skin="X"]` 段 | style.css | 加 wdp 段（已有12套皮肤同构） |
| skin 注册 | `_SKINS` 数组 | boot.js line1312 | 加一项 |
| 导航 | `data-panel` + `switchPanel(name)` | index.html line182+ / panels.js line203 | 加导航项（桌面+移动两份） |
| 面板 | `.panel-view` + `showing-<name>` + 懒加载 | index.html line220+ / panels.js | 加 panel-view + 渲染函数 |
| chat引擎 | SSE/composer/会话/profile切换 | 现有 panelChat | 完全不动，只换皮 |

**核心结论**：web-ui 皮肤/面板系统设计规整，所有团队定制都是**加法**（加 skin、加 panel、加 css/js 文件），不改 chat 引擎和现有 12 面板，冲突面小、可回退。
