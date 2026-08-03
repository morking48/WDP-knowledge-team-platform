---
name: wdp-online-knowledge-sync
description: "WDP 在线文档同步知识库（母版）：企微文档/飞书Wiki/API Skill库 实时拉取与索引、每日 cron 同步、5 类业务场景 prompt 模板（需求路由/售后/API支持/对外文档/售前控标）。配置在线源接入、做知识库同步、用 WDP 产品知识回答问题时用。母版位于 knowledge/library/product-knowledge/"
version: 1.0.0
---

# WDP 在线文档同步知识库（母版）

> 母版资产：`knowledge/library/product-knowledge/`（自 `F:\HermesAgent\projects\wdp-product-knowledge` 复制，原地址未动）。
> 核心原则：**在线源为权威，本地仅做索引**。所有回答以在线源拉取结果为准，本地快照只作背景认知。
> 同步链路已通：`knowledge/` 已配 gitlab 远程 `gitlab.51cloud.local/Maguanjie/wdp-team-knowledge.git`（master 分支）。知识库/母版更新 = 本地 commit+push → 服务器 pull，不碰部署。母版飞书凭证已剥离到环境变量（FEISHU_APP_ID/SECRET），无明文残留；knowledge/ 已加 .gitignore 挡敏感文件。

## 什么时候用

- 配置/运维在线源接入（企微文档、飞书 Wiki、API Skill 库）
- 跑/调度知识库同步任务（每日 18:00 同步、17:30 API 审查）
- 用 WDP 产品知识回答用户/客户问题（编辑器、API、报价、部署、FAQ、版本）
- 5 类业务场景：需求路由核对、售后技术支持、API 技术支持、对外文档生成、售前控标

## 在线源清单（需授权，管理员配置）

| 源 | 数量 | 内容 | 接入方式 |
|----|------|------|---------|
| 企微 FAQ 文档 | 7 | 国产化/平台问题/卡顿排查/Cloud导入/离线部署/云渲染下载/浏览器跨域 | 企微文档 MCP / wecom-cli |
| 企微规则文档 | 3 | 流程规则 / 报价明细表 / 售前控标参数 | 同上 |
| 企微部署文档 | 3 | 国产化快速部署 / Lite 国产化部署 / 性能指标体系 | 同上 |
| 飞书 Wiki | 1 | WDP5 产品操作手册（wikcnmC72WN01k0vWsr54RbCWXg） | 飞书 Open API |
| API Skill 库 | 1 | `http://wdpapi-skill.51aes.com`（261 文件 / 115 SKILL.md） | HTTP GET（公网免认证） |

## 🔒 授权信息保护（团队铁律，最高优先级）

**在线文档需授权查看，统一用管理员账号授权，团队成员不可获取授权信息。**

- 凭证（app_id / app_secret / token / 密码）**仅管理员配置**：个人环境变量或 K8s Secret。
- **严禁**：硬编码进代码、提交进 git、在对话/日志中回显。
- 成员用知识库内容时**无需也不应接触凭证**——由管理员配置的同步任务拉取后供全员使用。
- 脚本一律从环境变量读凭证；**无凭证时优雅降级**（提示管理员配置，不报错中断、不编造访问结果）。

环境变量约定：
- `FEISHU_APP_ID` / `FEISHU_APP_SECRET` — 飞书开放平台应用凭证
- 企微文档凭证 — 经企微文档 MCP / 对应环境变量（见 wdp-kb-ops）

⚠️ **历史教训**：母版脚本 `feishu_check.py` 曾硬编码飞书 app_secret 明文，整合时已剥离到环境变量。**引入任何外部脚本/资产前，先 grep `app_secret|app_id|token|password` 扫凭证再入库**，并提醒管理员撤销已暴露的旧凭证。

## 数据架构

```
在线源（实时拉取）                   本地技能（路由索引）
─────────────────                  ────────────────
企微文档 ×13  ──wecom-cli/MCP──▶   wdp-product-knowledge (产品知识)
飞书 Wiki ×1   ──Open API──▶        wdp-kb-ops (运维操作)
API Skill库 ×1 ──HTTP GET──▶
```

- 两个 skill：`wdp-product-knowledge`（产品知识索引）+ `wdp-kb-ops`（在线文档路由、认证授权、同步流程）
- 每日 cron：**知识库同步**（18:00，检查在线文档更新→自动更新 skill）、**API 文档审查**（17:30，检查 Skill 库变更→验证输出文档）

## 5 类业务场景 prompt 模板（templates/）

| 场景 | 流程 | 模板文件 |
|------|------|---------|
| **需求路由核对** | 三轮交叉验证（编辑器手册 → API库 → 版本日志+FAQ）判定 ✅已支持/⚠️部分/❌未支持，先过版本日志避免重复纳入 backlog | `demand-routing-prompt.md` |
| 售后技术支持 | 客户问题 → 匹配 FAQ 路由 → 拉在线文档 → 排查回复 | `support-session-prompt.md` |
| API 技术支持 | 开发者问题 → 拉 Skill 库 manifest → 定位 SKILL.md → 输出代码示例 | `api-tech-support-prompt.md` |
| 对外文档生成 | 三路交叉引用（编辑器+API库+版本日志）→ 生成 Word .docx | `external-doc-prompt.md` |
| 售前控标 | 售前控标参数 + 需求核对 → 输出控标点 | `presales-bidding-prompt.md` |

**需求路由已知已解决项**（先过一遍，避免重复纳入 backlog）：POI marker偏移+label交互(v5.11)、镜头飞行步长/速度(v5.9)、API日志等级(App.Debug.SetLogMode)、浏览器跨域(v5.7默认CORS+HTTPS)。

## 汇报口径红线（引用 WDP 知识时必守）

- WDP = AES **唯一开放平台层**；编辑器 = **五大主线**（废弃画布/蓝图等不提）；国产化数据库 = **金仓 KingbaseES（非达梦）**；云渲染是**串流（非 WebGL）**；编码以**发布版**为准（v2.3.1，`wdpapidoc.51aes.com/apifunc/wdpapi`），Skill 库是前瞻路由含未发布 API。
- 成果表述诚实：雏形 ≠ 已支持；按"已上线/已支持/雏形/原型/规划中"严格区分。

## 使用要点

- 脚本在 `knowledge/library/product-knowledge/scripts/`：feishu_check.py（飞书更新检查）、daily_sync_check*.py（每日同步）、filter_wecom_images.py（企微图片过滤）。
- 回答产品精确数据（版本号/报价/API清单）**以在线源为准**；未配置授权时以本地快照为背景认知，关键数据提示人工到在线源核对。
- 知识库内容更新**走 git 工作流**（改文件→push→服务器 pull），不重新部署服务。
