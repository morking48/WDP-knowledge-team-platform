#!/usr/bin/env bash
# ==============================================================================
# WDP 团队 AI 工作台 — 团队知识库卷初始化脚本（首次部署执行一次）
# ==============================================================================
# 作用：
#   在 knowledge 共享卷上完成首次初始化：
#     1) 建立标准目录：signals/ requirements/ designs/ decisions/ tracking/ knowledge/
#     2) git init + 初始 commit（知识库全程 git 版本化，可追溯、可备份）
#     3) 写入 README.md（团队知识资产库使用说明）
#     4) 提示配置 GitLab 远程仓库做异地备份
#
# 用法：
#   ./init-knowledge.sh
#
# 环境变量（可选）：
#   KNOWLEDGE_ROOT   knowledge 共享卷挂载路径   默认 /data/knowledge
#   GIT_REMOTE       GitLab 仓库地址            默认留空（脚本末尾提示手动配）
#   GIT_USER_NAME    git commit 署名            默认 "WDP Team Bot"
#   GIT_USER_EMAIL   git commit 邮箱            默认 "wdp-bot@local"
#
# 运维注意：
#   - 本脚本在挂载了 knowledge 共享卷的机器上执行一次即可（WebUI Pod /
#     主 Agent Pod / 运维跳板机均可）。
#   - 幂等：目录已存在、git 已 init、README 已写都会跳过，可安全重跑。
#   - 初始化完成后，请在 GitLab 建好空仓库，按脚本末尾提示配 remote 并首推。
# ==============================================================================
set -euo pipefail

# TODO(运维): 共享卷在脚本执行机上的实际挂载点，按部署环境修改
KNOWLEDGE_ROOT="${KNOWLEDGE_ROOT:-/data/knowledge}"
# TODO(运维): GitLab 备份仓库地址，例 git@gitlab.example.com:wdp/team-knowledge.git
GIT_REMOTE="${GIT_REMOTE:-}"
GIT_USER_NAME="${GIT_USER_NAME:-WDP Team Bot}"
GIT_USER_EMAIL="${GIT_USER_EMAIL:-wdp-bot@local}"

log()  { echo "[init-knowledge] $*"; }
warn() { echo "[init-knowledge][警告] $*" >&2; }
die()  { echo "[init-knowledge][错误] $*" >&2; exit 1; }

command -v git >/dev/null || die "缺少 git"

# ── 1. 初始化标准目录结构 ───────────────────────────────────────────────────
# 目录约定（与工作流一一对应，详见 README）：
#   signals/      信号层：清洗后的结构化原始信息
#   requirements/ 需求层：triage 后建档的需求（追溯信号）
#   designs/      设计层：方案设计（追溯需求）
#   decisions/    决策记录：重要判断的来龙去脉
#   tracking/     跟踪层：需求全生命周期状态
#   knowledge/    沉淀层：已验证可复用的知识/口径/FAQ
log "初始化知识库目录: $KNOWLEDGE_ROOT"
mkdir -p "$KNOWLEDGE_ROOT"/{signals,requirements,designs,decisions,tracking,knowledge}

# ── 2. git init + 初始 commit ───────────────────────────────────────────────
cd "$KNOWLEDGE_ROOT"
if [[ ! -d .git ]]; then
    log "git init ..."
    git init -q
    git config user.name "$GIT_USER_NAME"
    git config user.email "$GIT_USER_EMAIL"
else
    log "已是 git 仓库，跳过 init"
fi

# .gitignore：排除探针/临时文件，知识库内容全部入库
if [[ ! -f .gitignore ]]; then
    cat > .gitignore <<'EOF'
# 临时/探针文件
.link-probe-*
.jtest.txt
*.tmp
.DS_Store
EOF
    log "  写入 .gitignore"
fi

# ── 3. 写入 README.md ───────────────────────────────────────────────────────
if [[ ! -f README.md ]]; then
    cat > README.md <<'EOF'
# WDP 团队知识资产库

> 本目录是团队知识的**单一数据源**（团队铁律第一条）。
> 所有成员 profile 下的 `knowledge/` 都是指向本目录的链接——你读到的永远是同一份。

## 两条硬规则

1. **单一数据源**：团队知识只认这里，不在个人目录/聊天记录里搞第二份清单。
2. **git 版本化**：本目录是一个 git 仓库，每次入库/修改都有 commit，可追溯、可回滚、可备份（远程仓库见 git remote）。

## 目录用法

| 目录 | 层 | 放什么 | 命名规范 |
|------|-----|--------|----------|
| `signals/` | 信号层 | 清洗后的结构化原始信息（客户反馈/竞品动态/行业情报） | `SIG-YYYYMMDD-<主题>.md` |
| `requirements/` | 需求层 | triage 后建档的需求，frontmatter 里 `source_signals` 追溯信号 | `REQ-YYYYMMDD-<主题>.md` |
| `designs/` | 设计层 | 方案设计文档，frontmatter 里 `source_requirements` 追溯需求 | `DSN-YYYYMMDD-<主题>.md` |
| `decisions/` | 决策层 | 重要决策记录：背景/选项/结论/理由 | `DEC-YYYYMMDD-<主题>.md` |
| `tracking/` | 跟踪层 | 需求全生命周期状态（唯一状态源，工作台直接渲染） | `REQ-YYYYMMDD-<主题>.md`（与需求同名） |
| `knowledge/` | 沉淀层 | 已验证可复用的知识：口径/FAQ/最佳实践 | `KNW-<主题>.md` |

## 文件格式

- 一律 Markdown，**必须带 frontmatter**（id/title/status/created/追溯字段），工作台靠它渲染。
- 追溯链必须闭环：需求追信号、设计追需求，保证知识库收敛不发散（铁律第三条）。
- 成员对本目录**只读**；入库走流程：成员申请 → 管理员审核 → 主 Agent 执行写入 + git commit。

## 备份

本仓库应配置 GitLab 远程仓库并定期推送（部署时由运维配置，见 deploy 脚本提示）。
EOF
    log "  写入 README.md"
fi

# ── 4. 初始 commit ──────────────────────────────────────────────────────────
if git rev-parse --verify HEAD >/dev/null 2>&1; then
    # 已有 commit：把本次新增（如有）补一个 commit
    if [[ -n "$(git status --porcelain)" ]]; then
        git add -A
        git commit -q -m "chore: 补齐知识库初始化内容 (init-knowledge.sh)"
        log "  已补充 commit"
    else
        log "  无变更，跳过 commit"
    fi
else
    git add -A
    git commit -q -m "init: WDP 团队知识资产库初始化（目录结构 + README）"
    log "  初始 commit 完成"
fi

# ── 5. 提示配置 GitLab 远程备份 ────────────────────────────────────────────
if [[ -n "$GIT_REMOTE" ]]; then
    if git remote get-url origin >/dev/null 2>&1; then
        git remote set-url origin "$GIT_REMOTE"
    else
        git remote add origin "$GIT_REMOTE"
    fi
    log "远程仓库已配置: origin -> $GIT_REMOTE"
    log "请执行首推:  cd $KNOWLEDGE_ROOT && git push -u origin HEAD"
else
    cat <<EOF

================================================================================
⚠ 还差一步：配置 GitLab 远程仓库做备份
--------------------------------------------------------------------------------
  1. 在 GitLab 上新建空仓库（不要带 README），例如：
       git@gitlab.example.com:wdp/team-knowledge.git        # TODO(运维): 换成实际地址
  2. 配置远程并首推：
       cd $KNOWLEDGE_ROOT
       git remote add origin <gitlab仓库地址>
       git push -u origin HEAD
  3. 建议后续在主 Agent 的 cron 里加定时 push（每次入库 commit 后自动备份）。
================================================================================
EOF
fi

log "✅ 知识库初始化完成: $KNOWLEDGE_ROOT"
