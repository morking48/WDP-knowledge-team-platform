#!/usr/bin/env bash
# ==============================================================================
# WDP 团队 AI 工作台 — 添加团队成员脚本
# ==============================================================================
# 作用：
#   一键完成新成员开通的全部步骤：
#     1) 调用 WebUI 管理接口创建登录账号（username + 初始密码 + role）
#     2) 在 profiles 共享卷上初始化该成员的 profile 目录结构
#     3) 写入模板文件：SOUL.md / AGENTS.md / config.yaml / .env(600)
#     4) 建立 profile 下指向团队 knowledge/ 的符号链接（单一数据源）
#     5) 打印登录信息，提醒首次登录改密码
#
# 用法：
#   ./add-user.sh <username> <初始密码> [role]
#   例：./add-user.sh zhangsan 'Init@2026' member
#
# 环境变量（可选，有默认值）：
#   WEBUI_URL        WebUI 访问地址            默认 http://localhost:8080
#   ADMIN_USER       管理员账号                默认 admin
#   ADMIN_PASSWORD   管理员密码（脚本自动登录取 session/CSRF）
#   PROFILES_ROOT    profiles 共享卷挂载路径    默认 /data/profiles
#   KNOWLEDGE_ROOT   knowledge 共享卷挂载路径   默认 /data/knowledge
#   TEAM_CONFIG_DIR  团队模板目录               默认 <本脚本目录>/../team-config
#   SKIP_API=1       跳过 WebUI 接口调用（只做本地 profile 初始化）
#
# 运维注意：
#   - 本脚本需要在能访问 WebUI 且挂载了两个共享卷的机器上执行
#     （通常在 WebUI Pod 内 / 运维跳板机上）。
#   - ADMIN_PASSWORD 属于敏感信息，建议用环境变量传入，不要写进命令历史：
#       ADMIN_PASSWORD='xxx' ./add-user.sh zhangsan 'Init@2026'
#   - 如果没有 admin 凭证，可设 SKIP_API=1 先初始化目录，账号让管理员在
#     WebUI「用户管理」界面手动创建（界面会同步建 profile 目录，本脚本
#     会补齐模板文件与 knowledge 链接，幂等可重复执行）。
# ==============================================================================
set -euo pipefail

# ── 0. 参数与环境变量 ───────────────────────────────────────────────────────
USERNAME="${1:-}"
PASSWORD="${2:-}"
ROLE="${3:-member}"

WEBUI_URL="${WEBUI_URL:-http://localhost:8080}"
ADMIN_USER="${ADMIN_USER:-admin}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-}"
# TODO(运维): 以下两个路径需与 k8s deployment.yaml 中的 volumeMounts 保持一致
# （k8s 默认挂载点为 /data/profiles 和 /data/knowledge）
PROFILES_ROOT="${PROFILES_ROOT:-/data/profiles}"
KNOWLEDGE_ROOT="${KNOWLEDGE_ROOT:-/data/knowledge}"
# TEAM_CONFIG_DIR：团队模板目录。生产镜像内置在 /opt/hermes-team-config；
# 本地开发回落到脚本相对路径 ../team-config。
if [[ -z "${TEAM_CONFIG_DIR:-}" ]]; then
  if [[ -d /opt/hermes-team-config ]]; then
    TEAM_CONFIG_DIR=/opt/hermes-team-config
  else
    TEAM_CONFIG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/team-config"
  fi
fi
SKIP_API="${SKIP_API:-0}"

usage() {
    cat <<'EOF'
用法: ./add-user.sh <username> <初始密码> [role]

  username   小写字母/数字/连字符（同时作为 profile 名）
  初始密码    至少 6 位
  role       member(默认) 或 admin

示例:
  ./add-user.sh zhangsan 'Init@2026'
  ADMIN_PASSWORD='xxx' WEBUI_URL=https://wdp-team.example.com ./add-user.sh lisi 'Init@2026' member
  SKIP_API=1 ./add-user.sh wangwu 'Init@2026'   # 只初始化目录，不建账号
EOF
    exit 1
}

log()  { echo "[add-user] $*"; }
warn() { echo "[add-user][警告] $*" >&2; }
die()  { echo "[add-user][错误] $*" >&2; exit 1; }

[[ -z "$USERNAME" || -z "$PASSWORD" ]] && usage

# ── 1. 参数校验 ─────────────────────────────────────────────────────────────
# 1.1 用户名合法性：小写字母/数字/连字符，与 WebUI 侧 _PROFILE_ID_RE 保持一致
if [[ ! "$USERNAME" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
    die "用户名不合法：须以小写字母或数字开头，只能含小写字母/数字/连字符（当前: '$USERNAME'）"
fi

# 1.2 密码长度 ≥ 6
if (( ${#PASSWORD} < 6 )); then
    die "密码长度不足：至少 6 位（当前 ${#PASSWORD} 位）"
fi

# 1.3 角色合法性
if [[ "$ROLE" != "member" && "$ROLE" != "admin" ]]; then
    die "非法角色 '$ROLE'（只能 member 或 admin）"
fi

# 1.4 用户名不重复：profile 目录已存在即视为已开通
PROFILE_DIR="$PROFILES_ROOT/$USERNAME"
if [[ -d "$PROFILE_DIR" && -f "$PROFILE_DIR/config.yaml" ]]; then
    die "用户 '$USERNAME' 似乎已存在（$PROFILE_DIR 已有 config.yaml）。如需补齐文件可删除该目录重跑，或手动处理。"
fi

command -v curl >/dev/null || die "缺少 curl"
command -v python3 >/dev/null || die "缺少 python3（用于 JSON 处理）"

# ── 2. 调用 WebUI 接口创建账号 ──────────────────────────────────────────────
# 说明：/api/admin/users/create 需要 admin 已登录的 session cookie + CSRF token。
# 脚本先用 ADMIN_USER/ADMIN_PASSWORD 调 /api/auth/login 换取 cookie，
# 再带 cookie 调创建接口。CSRF token 取自登录响应种的 hermes_csrf cookie。
API_DONE=0
if [[ "$SKIP_API" == "1" ]]; then
    warn "SKIP_API=1：跳过账号创建。请管理员在 WebUI「用户管理」界面手动创建账号：$USERNAME"
elif [[ -z "$ADMIN_PASSWORD" ]]; then
    warn "未提供 ADMIN_PASSWORD，跳过账号创建。"
    warn "  方式一：ADMIN_PASSWORD='xxx' $0 $USERNAME '***' $ROLE 重跑"
    warn "  方式二：管理员登录 WebUI「用户管理」界面手动创建账号：$USERNAME（角色 $ROLE）"
else
    log "调用 WebUI 创建账号: $USERNAME (role=$ROLE) @ $WEBUI_URL"
    COOKIE_JAR="$(mktemp)"
    trap 'rm -f "$COOKIE_JAR"' EXIT

    # 2.1 管理员登录（多用户模式：username+password）
    LOGIN_BODY="$(python3 -c 'import json,sys; print(json.dumps({"username":sys.argv[1],"password":sys.argv[2]}))' "$ADMIN_USER" "$ADMIN_PASSWORD")"
    LOGIN_HTTP="$(curl -sS -o /tmp/.adduser-login-resp.$$ -w '%{http_code}' \
        -c "$COOKIE_JAR" -X POST "$WEBUI_URL/api/auth/login" \
        -H 'Content-Type: application/json' -d "$LOGIN_BODY")" \
        || die "无法连接 WebUI：$WEBUI_URL"
    if [[ "$LOGIN_HTTP" != "200" ]]; then
        rm -f /tmp/.adduser-login-resp.$$
        die "管理员登录失败 (HTTP $LOGIN_HTTP)，请检查 ADMIN_USER/ADMIN_PASSWORD"
    fi
    rm -f /tmp/.adduser-login-resp.$$

    # 2.2 从 cookie jar 取 CSRF token（WebUI 对 POST 有 CSRF 校验）
    CSRF_TOKEN="$(awk '$6=="hermes_csrf"{print $7}' "$COOKIE_JAR" | tail -n1 || true)"

    # 2.3 调用创建接口
    CREATE_BODY="$(python3 -c 'import json,sys; print(json.dumps({"username":sys.argv[1],"password":sys.argv[2],"role":sys.argv[3]}))' "$USERNAME" "$PASSWORD" "$ROLE")"
    CURL_ARGS=(-sS -b "$COOKIE_JAR" -X POST "$WEBUI_URL/api/admin/users/create"
               -H 'Content-Type: application/json' -d "$CREATE_BODY")
    [[ -n "$CSRF_TOKEN" ]] && CURL_ARGS+=(-H "X-CSRF-Token: $CSRF_TOKEN")
    CREATE_HTTP="$(curl "${CURL_ARGS[@]}" -o /tmp/.adduser-create-resp.$$ -w '%{http_code}')" \
        || die "调用创建接口失败（网络层）"
    CREATE_RESP="$(cat /tmp/.adduser-create-resp.$$)"; rm -f /tmp/.adduser-create-resp.$$
    if [[ "$CREATE_HTTP" != "200" ]]; then
        die "创建账号失败 (HTTP $CREATE_HTTP)：$CREATE_RESP"
    fi
    log "账号创建成功（接口返回）：$CREATE_RESP"
    API_DONE=1
fi

# ── 3. 初始化 profile 目录结构 ──────────────────────────────────────────────
log "初始化 profile 目录: $PROFILE_DIR"
# memories/skills/sessions/cron 为 Hermes profile 标准子目录；
# cache/audio_cache/logs 为运行期目录，一并预建避免首次运行权限问题
mkdir -p "$PROFILE_DIR"/{memories,skills,sessions,cron,cache,logs,workspace}

# ── 4. 写入模板文件（已存在则跳过，保证幂等）──────────────────────────────
# 4.1 SOUL.md —— 个人个性模板（成员后续自行修改）
if [[ ! -f "$PROFILE_DIR/SOUL.md" ]]; then
    if [[ -f "$TEAM_CONFIG_DIR/SOUL.md.template" ]]; then
        sed "s/<你的名字>/$USERNAME/" "$TEAM_CONFIG_DIR/SOUL.md.template" > "$PROFILE_DIR/SOUL.md"
    else
        warn "未找到 $TEAM_CONFIG_DIR/SOUL.md.template，写入极简 SOUL.md"
        printf '# 个人 SOUL · %s\n\n> 个人风格定义，不能覆盖团队铁律。\n' "$USERNAME" > "$PROFILE_DIR/SOUL.md"
    fi
    log "  写入 SOUL.md"
fi

# 4.2 AGENTS.md —— 团队规则（从 team-config 模板拷贝）
if [[ ! -f "$PROFILE_DIR/AGENTS.md" ]]; then
    if [[ -f "$TEAM_CONFIG_DIR/AGENTS.md.template" ]]; then
        cp "$TEAM_CONFIG_DIR/AGENTS.md.template" "$PROFILE_DIR/AGENTS.md"
    else
        warn "未找到 $TEAM_CONFIG_DIR/AGENTS.md.template，跳过 AGENTS.md"
    fi
    [[ -f "$PROFILE_DIR/AGENTS.md" ]] && log "  写入 AGENTS.md"
fi

# 4.3 config.yaml —— 基础模型配置（成员可在个人中心自行改模型/填 Key）
if [[ ! -f "$PROFILE_DIR/config.yaml" ]]; then
    cat > "$PROFILE_DIR/config.yaml" <<'EOF'
# Hermes 个人配置 · 由 add-user.sh 生成，可在 WebUI「个人中心」修改
# 模型与 API Key：个人 Key 优先；留空则回落到团队公共 Key（平台侧注入）
model:
  default: anthropic/claude-sonnet-4-5   # 默认模型，可按需改
  provider: openrouter                    # 平台统一走 openrouter 网关
# 个人 API Key（可选）。填了走个人额度，不填走团队公共 Key 兜底。
# api_keys:
#   openrouter: "sk-or-xxx"
# 团队级 MCP 服务：企业微信文档（官方 Streamable HTTP 接入，全团队共用）。
# apikey 走环境变量 WECOM_MCP_APIKEY（K8s Secret 注入，不进仓库）。
# 未注入该环境变量时 URL 里占位符不展开，MCP 连接失败但不影响其它功能。
mcp_servers:
  wecom_doc:
    url: "https://qyapi.weixin.qq.com/mcp/robot-doc?apikey=${WECOM_MCP_APIKEY}"
    timeout: 180
    connect_timeout: 30
EOF
    log "  写入 config.yaml"
fi

# 4.4 .env —— 空文件，权限 600（存个人密钥，严禁团队卷上共享可读）
if [[ ! -f "$PROFILE_DIR/.env" ]]; then
    : > "$PROFILE_DIR/.env"
fi
chmod 600 "$PROFILE_DIR/.env"
log "  写入 .env (权限 600)"

# ── 5. 建立指向团队 knowledge/ 的符号链接 ──────────────────────────────────
# 单一数据源铁律：所有 profile 看到的是同一份 knowledge/，实时同步。
KNOWLEDGE_LINK="$PROFILE_DIR/knowledge"
if [[ ! -d "$KNOWLEDGE_ROOT" ]]; then
    warn "团队知识库目录不存在：$KNOWLEDGE_ROOT（先跑 init-knowledge.sh？）链接暂不建立"
else
    # 已存在则先清掉（可能是旧链接或误建的目录——若是真目录且非空，保险起见不删，报错人工处理）
    if [[ -L "$KNOWLEDGE_LINK" ]]; then
        rm -f "$KNOWLEDGE_LINK"
    elif [[ -d "$KNOWLEDGE_LINK" ]]; then
        if [[ -n "$(ls -A "$KNOWLEDGE_LINK" 2>/dev/null)" ]]; then
            die "$KNOWLEDGE_LINK 是非空真实目录（疑似历史拷贝），为避免破坏单一数据源请人工检查后删除重跑"
        fi
        rmdir "$KNOWLEDGE_LINK"
    fi
    if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]]; then
        # Windows 本地调试用：git-bash 的 ln -s 无权限时会静默退化为"目录拷贝"，
        # 破坏单一数据源。必须用 PowerShell Junction（已验证可靠，无需管理员权限）。
        # 生产 Linux 环境走下方 ln -s，无此问题。
        log "  检测到 Windows(MSYS)，用 PowerShell Junction 建立链接"
        WIN_LINK="$(cygpath -w "$KNOWLEDGE_LINK")"
        WIN_TARGET="$(cygpath -w "$KNOWLEDGE_ROOT")"
        powershell -NoProfile -Command \
            "New-Item -ItemType Junction -Path '$WIN_LINK' -Target '$WIN_TARGET' -ErrorAction Stop | Out-Null" \
            || die "PowerShell 建立 Junction 失败"
    else
        ln -s "$KNOWLEDGE_ROOT" "$KNOWLEDGE_LINK"
    fi
    # 实时同步验证：源侧写 → 链接侧读（防止"链接变拷贝"假象，必须做）
    SYNC_PROBE=".link-probe-$$"
    echo "probe-$$" > "$KNOWLEDGE_ROOT/$SYNC_PROBE"
    if [[ "$(cat "$KNOWLEDGE_LINK/$SYNC_PROBE" 2>/dev/null)" == "probe-$$" ]]; then
        log "  knowledge 链接建立并验证实时同步 ✓ ($KNOWLEDGE_LINK -> $KNOWLEDGE_ROOT)"
    else
        rm -f "$KNOWLEDGE_ROOT/$SYNC_PROBE"
        die "knowledge 链接同步验证失败（读到内容不符），请检查共享卷挂载"
    fi
    rm -f "$KNOWLEDGE_ROOT/$SYNC_PROBE"
fi

# ── 6. 完成信息 ─────────────────────────────────────────────────────────────
cat <<EOF

================================================================================
✅ 成员开通完成
--------------------------------------------------------------------------------
  登录网址 : $WEBUI_URL
  账号     : $USERNAME
  初始密码 : $PASSWORD
  角色     : $ROLE
  profile  : $PROFILE_DIR
EOF
[[ "$API_DONE" == "0" ]] && echo "  ⚠ 账号未通过接口创建，请管理员在 WebUI「用户管理」手动创建（同上账号名）"
cat <<EOF

  请把以上信息发给该成员，并提醒：
  ① 首次登录后立即在「个人中心」修改密码（初始密码仅限首次登录使用）
  ② 个人 SOUL.md / config.yaml 可按喜好在个人中心调整
  ③ knowledge/ 为团队共享知识库（只读），入库走申请→审核流程
================================================================================
EOF
