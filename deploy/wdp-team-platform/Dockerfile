# =============================================================================
# WDP 团队平台 · Hermes WebUI 多用户定制镜像
# =============================================================================
# 基础：python:3.12-slim
# 思路：
#   1) 复刻官方 web-ui/Dockerfile 的系统依赖、用户、目录、uv 安装、启动脚本；
#   2) COPY 官方 web-ui 源码到 /apptoo（官方镜像的运行目录约定）；
#   3) COPY 本地 agent-src 到 /opt/hermes（web-ui 运行时通过
#      HERMES_WEBUI_AGENT_DIR 环境变量发现 agent；docker_init.bash 也会到
#      /opt/hermes 寻找 pyproject.toml 并安装其 Python 依赖）；
#   4) COPY deploy/wdp-team-platform/webui-overlay/ 覆盖到 /apptoo 对应路径，
#      实现“多用户认证 + WDP 定制”的叠加层，而不改动 web-ui/ 仓库本体。
#
# 【重要】构建上下文必须是【项目根目录】F:\\wdp-team-hermes，
# 以便同时访问 web-ui/、agent-src/ 和 deploy/wdp-team-platform/webui-overlay/。
#
# 构建命令示例（在项目根目录下执行）：
#   docker build \
#     -f deploy/wdp-team-platform/Dockerfile \
#     -t wdp-team-platform:latest \
#     .
# =============================================================================

FROM python:3.12-slim

LABEL maintainer="WDP Team"
LABEL description="WDP 团队平台 · Hermes WebUI 多用户定制镜像（基于官方 web-ui 叠加 overlay）"

# -----------------------------------------------------------------------------
# 1) 系统依赖：与官方 web-ui Dockerfile 完全一致
#    git / rsync / curl / ca-certificates / openssh-client / xz-utils / locales
#    rsync 被 docker_init.bash 用来把 /apptoo 同步到 /app；
#    curl 用来安装 uv 以及 HEALTHCHECK 探活。
# -----------------------------------------------------------------------------
ENV DEBIAN_FRONTEND=noninteractive

# 可选：构建期 apt 代理（与官方一致，便于内网/CI 加速）
ARG BUILD_APT_PROXY=
RUN if [ "A${BUILD_APT_PROXY}" != "A" ]; then \
        echo "Using APT proxy: ${BUILD_APT_PROXY}"; \
        printf 'Acquire::http::Proxy \"%s\";\n' "$BUILD_APT_PROXY" > /etc/apt/apt.conf.d/01proxy; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates wget gnupg \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

RUN apt-get update -y --fix-missing --no-install-recommends \
    && apt-get install -y --no-install-recommends \
        apt-utils \
        locales \
        ca-certificates \
        curl \
        rsync \
        openssh-client \
        git \
        xz-utils \
    && apt-get upgrade -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /etc/apt/apt.conf.d/01proxy

# UTF-8 locale（官方一致）
RUN localedef -i en_US -c -f UTF-8 -A /usr/share/locale/locale.alias en_US.UTF-8
ENV LANG=en_US.utf8
ENV LC_ALL=C

# Python 运行参数（官方一致）
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8

# -----------------------------------------------------------------------------
# 2) 创建运行用户与目录约定（官方一致）
#    - 用户 hermeswebui (uid/gid 1024)，启动脚本会按挂载卷自动调整 UID/GID
#    - /apptoo  ：构建期放入 web-ui 源码（只读模板）
#    - /app     ：运行期由 docker_init.bash 从 /apptoo rsync 出来并 chown
#    - /uv_cache：uv 包缓存
#    - /workspace：默认工作区（可挂载卷）
# -----------------------------------------------------------------------------
WORKDIR /apptoo

RUN groupadd -g 1024 hermeswebui \
    && useradd -u 1024 -d /home/hermeswebui -g hermeswebui -G users -s /bin/bash -m hermeswebui \
    && mkdir -p /app /uv_cache /workspace \
    && chown -R hermeswebui:hermeswebui /home/hermeswebui /app /uv_cache /workspace \
    && chmod 0755 /home/hermeswebui \
    && chmod 1777 /app /uv_cache /workspace

# 官方启动脚本：root 启动 → UID/GID 对齐 + 目录准备 → 切到 hermeswebui 运行 server.py
COPY --chmod=555 web-ui/docker_init.bash /hermeswebui_init.bash

# 标记当前在容器内（官方一致）
RUN touch /.within_container

# -----------------------------------------------------------------------------
# 3) 预装 uv 到系统路径（官方一致）
#    运行时 docker_init.bash 检测到 uv 已存在则跳过下载，离线也能起。
# -----------------------------------------------------------------------------
USER root
RUN curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh

# -----------------------------------------------------------------------------
# 4) COPY 官方 web-ui 源码到 /apptoo
#    注意：构建上下文是项目根目录，所以路径前缀是 web-ui/
#    配合 .dockerignore（位于 deploy/wdp-team-platform/）排除掉
#    __pycache__、.git、本地 venv 等。
# -----------------------------------------------------------------------------
COPY --chown=root:root web-ui/ /apptoo

# 烧入版本号（官方一致）：CI 传 --build-arg HERMES_VERSION=$(git describe --tags --always)
ARG HERMES_VERSION=unknown
RUN echo "__version__ = '${HERMES_VERSION}'" > /apptoo/api/_version.py

# -----------------------------------------------------------------------------
# 5) COPY agent 源码到 /opt/hermes（关键 · WDP 定制点）
#
#    web-ui 通过 HERMES_WEBUI_AGENT_DIR 环境变量发现 hermes-agent；
#    docker_init.bash 在首次启动时也会按下述顺序寻找 agent 源码并安装依赖：
#        /home/hermeswebui/.hermes/hermes-agent   （HERMES_HOME 下）
#        /opt/hermes                              （本镜像使用）
#
#    我们把宿主机的 agent-src/ 直接烘到镜像里 /opt/hermes，这样：
#      - 单容器即可跑通，无需再挂 agent 源码卷；
#      - 也仍然支持运行时通过 -v 覆盖 /opt/hermes 来升级 agent。
#
#    如果团队希望 agent 源码不进镜像、改成运行时挂载：
#      - 把下面这段 COPY 注释掉；
#      - 运行时加： -v /path/to/agent-src:/opt/hermes:ro
# -----------------------------------------------------------------------------
COPY --chown=root:root agent-src/ /opt/hermes

# -----------------------------------------------------------------------------
# 6) COPY WDP overlay 覆盖到 /apptoo（核心定制层）
#
#    overlay 目录结构与 /apptoo 对齐：
#        deploy/wdp-team-platform/webui-overlay/
#            api/users.py               → /apptoo/api/users.py
#            api/auth.py                → /apptoo/api/auth.py     （多用户认证）
#            api/routes.py              → /apptoo/api/routes.py
#            static/login-multiuser.js  → /apptoo/static/login-multiuser.js
#
#    因为 docker_init.bash 启动时会 rsync /apptoo → /app，
#    overlay 文件会在容器启动时自然出现在 /app 中，被 server.py 加载。
# -----------------------------------------------------------------------------
COPY --chown=root:root deploy/wdp-team-platform/webui-overlay/ /apptoo/

# 7) 团队 skills（个人中心"团队技能"只读展示 + agent 加载）→ 镜像内置
COPY --chown=root:root deploy/wdp-team-platform/team-config/skills/ /opt/hermes-team-skills/

# 8) agent 提交/画像/个人skill 沉淀脚本 → 镜像内置（启动脚本会同步到 PVC 的 hermes-home/scripts/）
COPY --chown=root:root deploy/wdp-team-platform/scripts/submit_review.py \
     deploy/wdp-team-platform/scripts/update_member_profile.py \
     deploy/wdp-team-platform/scripts/save_personal_skill.py \
     /opt/wdp-scripts/

# -----------------------------------------------------------------------------
# 7) 运行时环境变量默认值（可被 docker run -e 覆盖）
# -----------------------------------------------------------------------------
ENV HERMES_WEBUI_HOST=0.0.0.0 \
    HERMES_WEBUI_PORT=8787 \
    # WDP 多用户开关（overlay 中的 api/auth.py / users.py 读取）
    HERMES_WEBUI_MULTIUSER=1 \
    # 显式告诉 web-ui agent 源码位置（对应 /opt/hermes）
    HERMES_WEBUI_AGENT_DIR=/opt/hermes \
    # 状态目录默认值（单机/本地运行的兜底）。
    # ★ K8s 集群部署时会被 deployment.yaml 覆盖为共享卷路径
    #   （HERMES_HOME=/data/profiles/<user>），多副本因此共享同一批 profile。
    HERMES_HOME=/home/hermeswebui/.hermes \
    HERMES_WEBUI_STATE_DIR=/home/hermeswebui/.hermes/webui \
    HERMES_WEBUI_DEFAULT_WORKSPACE=/workspace

# -----------------------------------------------------------------------------
# 8) 端口 / 健康检查 / 启动命令（官方一致）
# -----------------------------------------------------------------------------
EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8787/health || exit 1

# 以 root 进入 init 脚本，由它完成 UID/GID 对齐与 /apptoo → /app 同步后
# 自行降权到 hermeswebui 用户并启动 server.py
USER root
CMD ["/hermeswebui_init.bash"]
