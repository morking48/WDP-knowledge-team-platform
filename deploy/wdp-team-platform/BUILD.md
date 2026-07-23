# WDP 团队平台 · 镜像构建说明

> 目标：基于官方 `web-ui` 镜像构建逻辑，叠加 `deploy/wdp-team-platform/webui-overlay/`
> 多用户定制层，并把 `agent-src/` 一并烘进镜像，得到一个**单容器即可跑通**的
> WDP 团队平台 WebUI 镜像。

---

## 1. 目录结构

构建前请确认项目根目录结构如下（已就绪）：

```
F:\wdp-team-hermes\
├── agent-src\                          # Hermes Agent 源码（进镜像 → /opt/hermes）
├── web-ui\                             # 官方 Hermes WebUI 源码（进镜像 → /apptoo）
│   ├── Dockerfile                      # 官方 Dockerfile（本构建不直接使用，只复刻其步骤）
│   ├── docker_init.bash                # 官方启动脚本（被 COPY 进镜像）
│   ├── server.py / api/ / static/ ...
│   └── requirements.txt
└── deploy\wdp-team-platform\
    ├── Dockerfile                      # ★ 本构建使用的 Dockerfile
    ├── .dockerignore                   # ★ 构建忽略清单（需复制到项目根目录才生效，见下）
    ├── BUILD.md                        # 本文档
    ├── webui-overlay\                  # ★ WDP 定制层（COPY 时覆盖到 /apptoo）
    │   ├── api\users.py
    │   ├── api\auth.py
    │   ├── api\routes.py
    │   └── static\login-multiuser.js
    ├── k8s\                            # 后续 K8s 部署清单
    ├── scripts\                        # 运维脚本
    └── team-config\                    # 团队配置（用户、模型等）
```

---

## 2. 构建命令

### 2.1 准备 `.dockerignore`

Docker 只会读取**构建上下文根目录**下的 `.dockerignore`。因为我们的构建上下文
是项目根 `F:\wdp-team-hermes`，所以需要先把交付包里的 `.dockerignore` 复制过去：

```bash
# 在 git-bash / MSYS 中执行
cp deploy/wdp-team-platform/.dockerignore .dockerignore
```

> ⚠️ 如果项目根目录已经有 `.dockerignore`，请先备份再合并；构建完成后可以恢复。

### 2.2 执行构建

在**项目根目录** `F:\wdp-team-hermes` 下执行：

```bash
# 基本构建
docker build \
  -f deploy/wdp-team-platform/Dockerfile \
  -t wdp-team-platform:latest \
  .

# 带版本号（推荐 CI 使用）
docker build \
  -f deploy/wdp-team-platform/Dockerfile \
  -t wdp-team-platform:$(git describe --tags --always) \
  --build-arg HERMES_VERSION=$(git describe --tags --always) \
  .

# 内网/CI 走 apt 代理加速
docker build \
  -f deploy/wdp-team-platform/Dockerfile \
  -t wdp-team-platform:latest \
  --build-arg BUILD_APT_PROXY=http://your-apt-proxy:3142 \
  .
```

**关键点**：
- `-f deploy/wdp-team-platform/Dockerfile` 指定 Dockerfile 路径；
- 最后的 `.` 表示构建上下文为**项目根目录**（不是 `deploy/wdp-team-platform/`）；
- 这样 Dockerfile 里才能同时 `COPY web-ui/`、`COPY agent-src/`、
  `COPY deploy/wdp-team-platform/webui-overlay/`。

### 2.3 运行

```bash
docker run -d \
  --name wdp-team-platform \
  -p 8787:8787 \
  -e HERMES_WEBUI_PASSWORD=change-me-strong-password \
  -e HERMES_WEBUI_MULTIUSER=1 \
  -v wdp-hermes-home:/home/hermeswebui/.hermes \
  -v wdp-workspace:/workspace \
  wdp-team-platform:latest
```

访问 `http://localhost:8787`，健康检查 `http://localhost:8787/health`。

---

## 3. 镜像里包含什么

| 路径 | 内容 | 来源 |
| --- | --- | --- |
| `/apptoo` | 官方 web-ui 源码 + WDP overlay 覆盖后的结果 | `web-ui/` + `deploy/wdp-team-platform/webui-overlay/` |
| `/opt/hermes` | Hermes Agent 源码（含 `pyproject.toml`） | `agent-src/` |
| `/hermeswebui_init.bash` | 官方启动脚本（root → 降权 → 启动 server.py） | `web-ui/docker_init.bash` |
| `/app` | 运行时目录（init 脚本从 `/apptoo` rsync 过来） | 容器启动时生成 |
| `/workspace` | 默认工作区（建议挂卷持久化） | 镜像预留空目录 |
| `/home/hermeswebui/.hermes` | Hermes 状态目录（建议挂卷持久化） | 镜像预留空目录 |
| `python:3.12-slim` 基座 | Python 3.12 + git/rsync/curl/uv/locales | 官方基础镜像 |

**Overlay 覆盖关系**：

| Overlay 文件 | 覆盖到 | 作用 |
| --- | --- | --- |
| `webui-overlay/api/users.py` | `/apptoo/api/users.py` | 多用户用户模型 |
| `webui-overlay/api/auth.py` | `/apptoo/api/auth.py` | 多用户认证逻辑 |
| `webui-overlay/api/routes.py` | `/apptoo/api/routes.py` | 路由（注入多用户端点） |
| `webui-overlay/static/login-multiuser.js` | `/apptoo/static/login-multiuser.js` | 多用户登录页前端 |

---

## 4. 环境变量清单

### 4.1 镜像内置默认值（可在 `docker run -e` 覆盖）

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `HERMES_WEBUI_HOST` | `0.0.0.0` | 监听地址 |
| `HERMES_WEBUI_PORT` | `8787` | 监听端口 |
| `HERMES_WEBUI_MULTIUSER` | `1` | **WDP 多用户开关**（overlay 读取） |
| `HERMES_WEBUI_AGENT_DIR` | `/opt/hermes` | web-ui 用于发现 hermes-agent 源码 |
| `HERMES_HOME` | `/home/hermeswebui/.hermes` | Hermes 状态根目录 |
| `HERMES_WEBUI_STATE_DIR` | `/home/hermeswebui/.hermes/webui` | WebUI 状态目录（sessions/workspaces） |
| `HERMES_WEBUI_DEFAULT_WORKSPACE` | `/workspace` | 默认工作区 |
| `LANG` | `en_US.utf8` | 容器 locale |
| `PYTHONUNBUFFERED` | `1` | Python 输出不缓冲 |

### 4.2 运行时通常需要显式设置的变量

| 变量 | 是否必填 | 说明 |
| --- | --- | --- |
| `HERMES_WEBUI_PASSWORD` | **建议必填** | 单密码模式的管理员密码；多用户模式下作为兜底 |
| `HERMES_WEBUI_SECURE` | 可选 | `1` 强制 cookie secure（HTTPS 部署时打开） |
| `HERMES_WEBUI_SESSION_TTL` | 可选 | 会话有效期（秒），默认 7 天 |
| `WANTED_UID` / `WANTED_GID` | 可选 | 挂载卷 UID/GID 对齐，默认 1024 |
| `OPENAI_API_KEY` 等模型 key | 按需 | 团队使用的模型提供方密钥 |

完整变量列表见 `web-ui/.env.docker.example` 与 `web-ui/api/config.py`。

---

## 5. 常见构建/运行问题排查

| 现象 | 可能原因 | 处理 |
| --- | --- | --- |
| `COPY web-ui/ /apptoo` 报 `not found` | 构建上下文不是项目根 | 确认命令最后是 `.` 且在项目根目录执行 |
| 启动日志提示 `hermes-agent source not found` | `/opt/hermes` 为空或 `HERMES_WEBUI_AGENT_DIR` 被改 | 检查 Dockerfile 中 `COPY agent-src/ /opt/hermes` 是否成功；或运行时挂卷 `-v /path/to/agent-src:/opt/hermes:ro` |
| 启动时 `uv pip install` 卡住 | 容器内无法访问 pypi | 给容器配 `pip` 镜像源；或预先在镜像里安装依赖 |
| Overlay 没生效 | overlay 文件路径与 `/apptoo` 下的相对路径不一致 | 对照 `webui-overlay/` 目录结构是否与 `web-ui/` 内部结构对齐 |
| `/health` 一直 503 | server.py 还没起完 | 容器首启要装 Python 依赖，等 30s–2min 再看；`docker logs -f wdp-team-platform` 观察 |

---

## 6. 后续动作

- [ ] 在 `k8s/` 下补充 Deployment / Service / Ingress 清单；
- [ ] 在 `team-config/` 下放置团队用户/模型配置的初始化脚本；
- [ ] 在 `scripts/` 下放置 `build.sh` / `push.sh` 一键脚本；
- [ ] CI 流水线接入：构建 → 推镜像仓库 → 滚动更新。
