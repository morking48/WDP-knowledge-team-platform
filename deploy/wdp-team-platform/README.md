# WDP 团队平台 · 总体说明与部署文档

> 面向：**技术评审 / 运维工程师** + **Jenkins CI/CD**
> 范围：平台技术实现概览、`deploy/wdp-team-platform/` 交付包说明、部署步骤、运维替换清单、日常维护、FAQ。
> 部署目标：Linux + Kubernetes，Jenkins 做构建/推送/滚动更新。
> 配套仓库：知识库数据 → [wdp-team-knowledge](http://gitlab.51cloud.local/Maguanjie/wdp-team-knowledge)

---

## 1. 项目简介

**WDP 团队平台** 是 WDP 产品团队的**多用户 AI 工作台**。基于开源 Hermes Agent 二次定制（后端 API 复用 + 前端完全自研），把"单人单 agent"的官方形态升级为"一个团队一套平台"：每位成员一个专属 AI 助手，全团队共享唯一知识库，产研工作流（信号→需求→设计）通过"AI 协作产出 → 提交 → 管理员审核 → 入库"闭环收敛为团队资产。

### 核心能力

| 能力 | 说明 |
| --- | --- |
| **多用户 + 每人独立 Agent** | 成员登录绑定独立 profile（会话/记忆/个人风格互不可见），单点登录（后登录挤掉先登录）；角色分 管理员/成员。 |
| **团队共享知识库** | 挂载共享 `knowledge/` 卷作为团队**唯一数据源**：信号/需求/设计结构化入库，Markdown+frontmatter+git 版本化，无独立数据库，工作台界面即知识库的可视化窗口。技术选型与 Google OKF（Open Knowledge Format）开放规范同构，可移植、不锁定。 |
| **产研闭环工作流** | 信号（收集）→ 需求（沉淀，带优先级/负责人/状态机流转）→ 设计（关联需求）三层可追溯；成员对话产出经 inbox 提交，管理员在**决策中心**审核后 git commit 入库。 |
| **AI 深度参与** | 智能归并 Agent（LLM 分析信号池给归并建议，n 对 n 分组、逐组拍板）、审核助手（归类/查重/质量分析）、对话式协作弹窗（多轮讨论后执行）；决策被记录为 few-shot 学习素材，越用越贴合团队尺度。 |
| **团队 Agent 统一管理** | 一级管理模块：团队规则（保存/一键发布到所有成员 agent）、团队默认模型（成员未配个人 Key 时兜底）、归并规则调教、主 Agent 定时任务（信号清洗/停滞提醒/周报，cron 调度）。 |
| **个人工作库与环境互锁** | 成员登记本机设备（machine_id 指纹）+ 工作库目录，服务器只存索引不存文件本体；环境不一致自动置灰，agent 读不到时明确提示不编造。 |
| **管理员后台** | 成员增删/重置密码/踢下线/用量统计，全部 WebUI 操作，无需登录服务器。 |

### 技术栈

- **后端**：Python 标准库 HTTP 服务（官方 web-ui 架构）+ 17 个定制 api 模块（overlay 层，构建时覆盖）
- **前端**：完全自研（workbench.html + 6 个 JS 模块 + 1 套 CSS），原生 JS 无框架依赖，自研弹窗组件全站统一
- **知识存储**：Markdown + YAML frontmatter + git（分区由 knowledge.config.yaml 声明式注册，加分区不改代码）
- **LLM**：OpenRouter（团队公共 Key K8s Secret 注入；成员可配个人渠道，自动 fallback）
- **部署**：Docker 镜像（官方源码+overlay 叠加构建）+ K8s（2 副本 + sticky session + RWX PVC ×2）

---

## 2. 架构图（文字版）

```
                        ┌─────────────────────────────────────────┐
                        │   团队口号（团队铁律，team-soul.md）      │
                        │   "团队知识只认 knowledge/；              │
                        │    信号→需求→设计→跟踪 必须入库可追溯"   │
                        └─────────────────────────────────────────┘
                                              │
                                              ▼
┌──────────┐   HTTPS   ┌─────────────────────────────────────────────────┐
│  成员浏览器 │ ───────► │  Ingress (TLS, sticky session by cookie)         │
└──────────┘           │  host: team.wdp.example.com                      │
                       │  证书 Secret: wdp-team-tls-secret                │
                       └────────────────────┬────────────────────────────┘
                                            │
                                            ▼
                            ┌───────────────────────────────┐
                            │  Service: wdp-team-webui       │
                            │  ClusterIP :8787               │
                            └───────────────┬───────────────┘
                                            │
                ┌───────────────────────────┴───────────────────────────┐
                ▼                                                       ▼
   ┌────────────────────────┐                              ┌────────────────────────┐
   │  WebUI Pod · 副本 1     │                              │  WebUI Pod · 副本 2     │
   │  image: wdp-team-platform│                             │  image: wdp-team-platform│
   │  requests: 2C / 4Gi     │                              │  requests: 2C / 4Gi     │
   │  limits:   4C / 8Gi     │                              │  limits:   4C / 8Gi     │
   └───────────┬────────────┘                              └───────────┬────────────┘
               │                                                       │
               └───────────────────────────┬───────────────────────────┘
                                           │  共享卷 (ReadWriteMany)
                ┌──────────────────────────┼──────────────────────────┐
                ▼                          ▼                          ▼
   ┌────────────────────┐      ┌────────────────────┐      ┌────────────────────┐
   │ PVC: wdp-team-      │      │ PVC: wdp-team-      │      │ 独立主 Agent         │
   │   knowledge         │      │   profiles          │      │ Deployment, 1 副本   │
   │ 50Gi, RWX           │      │ 100Gi, RWX          │      │ 1C/2Gi ~ 2C/4Gi     │
   │ 团队知识库（git 管理）│      │ 用户目录（每成员一个 │      │ 跑定时任务 / 入库审核 │
   │                     │      │ profile 子目录）     │      │ 用团队公共 LLM Key   │
   └────────────────────┘      └────────────────────┘      └─────────┬──────────┘
                                                                      │
                                                                      ▼
                                                          ┌────────────────────┐
                                                          │ Secret:             │
                                                          │ wdp-team-llm-secret │
                                                          │ OPENROUTER_API_KEY  │
                                                          │ （kubectl 创建，     │
                                                          │   不进 git）        │
                                                          └────────────────────┘
```

**要点回顾**：
- 单入口 Ingress（TLS + cookie sticky session，因为 WebUI 用 SSE 长连接）
- WebUI **2 副本**，每副本 4C8G limit
- 共享存储：两块 RWX PVC（knowledge 50Gi + profiles 100Gi）
- 主 Agent 单副本、无端口、纯后台，Secret 注入团队公共 Key

---

## 3. 目录结构说明

```
deploy/wdp-team-platform/
├── README.md                       # ★ 本文档（你正在读的）
├── BUILD.md                        # 镜像构建详细说明（构建上下文、overlay 覆盖关系、环境变量清单）
├── Dockerfile                      # WDP 定制镜像 Dockerfile（构建上下文必须是项目根）
├── .dockerignore                   # 构建忽略清单（构建前需复制到项目根）
│
├── k8s/                            # K8s 部署清单（kubectl apply 用）
│   ├── pvc.yaml                    #   两块 RWX PVC：knowledge(50Gi) + profiles(100Gi)
│   ├── secret.example.yaml         #   LLM Key Secret 示例（真实 Secret 用 kubectl 创建，勿提交）
│   ├── deployment.yaml             #   WebUI Deployment，2 副本，挂 knowledge + profiles
│   ├── service.yaml                #   ClusterIP Service :8787
│   ├── main-agent.yaml             #   主 Agent Deployment，1 副本，跑定时任务
│   └── ingress.yaml                #   Ingress + TLS + cookie sticky session
│
├── webui-overlay/                  # WDP 多用户定制代码层（构建时覆盖到官方 web-ui 源码上）
│   ├── README.md                   #   overlay 全量文件说明（api 17 个 + static 独立客制化前端）
│   ├── api/                        #     多用户认证/知识库/审核/团队Agent/定时任务 等全部后端定制
│   └── static/                     #     独立客制化前端（workbench.html + wb*.js + wb.css + 多用户登录页）
│
├── team-config/                    # 团队配置（知识库初始内容 + 模板）
│   ├── team-soul.md                #   ★ 团队铁律（最高优先级，不可被个人 SOUL 覆盖）
│   ├── AGENTS.md.template          #   新成员工作目录的 AGENTS.md 模板
│   ├── SOUL.md.template            #   新成员个人 SOUL 模板
│   └── skills/
│       ├── signal-intake/          #   信号录入 skill（→ knowledge/signals/）
│       └── requirement-triage/     #   需求分诊 skill（→ knowledge/requirements/）
│
└── scripts/                        # 运维脚本（在 Pod / 服务器上执行）
    ├── init-knowledge.sh           #   首次部署：初始化 knowledge 卷（拉 gitlab 仓库 + 写入 team-soul/skills）
    └── add-user.sh                 #   添加成员：创建 profile 目录 + 复制模板 + 注册到 users.json
```

---

## 4. 部署步骤

> 以下步骤假设你已经有 K8s 集群的管理员权限、能登录镜像仓库、有一个可用域名。

### ① 前置准备

| 资源 | 要求 | 验证命令 |
| --- | --- | --- |
| K8s 集群 | v1.24+，已安装 Ingress Controller（nginx 推荐） | `kubectl version && kubectl get ingressclass` |
| 镜像仓库 | 可推拉，如 Harbor / ACR / 腾讯云 TCR | `docker login <your-registry>` |
| StorageClass | **必须支持 ReadWriteMany**（nfs-client / longhorn / cephfs / 云厂商 NAS） | `kubectl get sc` |
| 域名 + 证书 | 域名已解析到 Ingress LB；证书文件 tls.crt / tls.key | `dig team.wdp.example.com` |
| Namespace | 交付包默认 `wdp-team`，可改 | `kubectl create namespace wdp-team` |

> ⚠️ **StorageClass 是最常见的坑**：如果集群没有支持 RWX 的 StorageClass，PVC 会卡在 Pending。自建集群推荐先装 [nfs-subdir-external-provisioner](https://github.com/kubernetes-sigs/nfs-subdir-external-provisioner) 或 Longhorn。

### ② 构建镜像并推送

**构建上下文必须是项目根目录**（`F:\wdp-team-hermes` 或 Linux 下的对应路径），因为 Dockerfile 需要同时访问 `web-ui/`、`agent-src/`、`deploy/wdp-team-platform/webui-overlay/` 三处。

```bash
# 在项目根目录执行
cd /path/to/wdp-team-hermes

# .dockerignore 必须先复制到项目根（Docker 只读上下文根的 .dockerignore）
cp deploy/wdp-team-platform/.dockerignore .dockerignore

# 构建（带版本号，推荐）
export VERSION=$(git describe --tags --always)
export REGISTRY=<your-registry>/wdp          # ← 运维替换
docker build \
  -f deploy/wdp-team-platform/Dockerfile \
  -t ${REGISTRY}/wdp-team-platform:${VERSION} \
  -t ${REGISTRY}/wdp-team-platform:latest \
  --build-arg HERMES_VERSION=${VERSION} \
  .

# 推送
docker push ${REGISTRY}/wdp-team-platform:${VERSION}
docker push ${REGISTRY}/wdp-team-platform:latest
```

详细构建原理、环境变量、排错见 [BUILD.md](./BUILD.md)。

### ③ 创建 Secret（OPENROUTER_API_KEY）

> ⚠️ **严禁把真实 Key 提交到 git**。用 `kubectl` 命令直接创建，不落盘：

```bash
kubectl create secret generic wdp-team-llm-secret \
  --from-literal=OPENROUTER_API_KEY="<真实 OpenRouter Key>" \
  -n wdp-team
```

如果还需要其他模型提供方的 Key，继续加 `--from-literal=OPENAI_API_KEY=...` 等。

如需参考文件方式，可看 `k8s/secret.example.yaml`，但**用完后立即删除本地文件**。

### ④ 依次 kubectl apply

**顺序有依赖**：PVC 要先就绪，Secret 要先存在，WebUI 才能起。

```bash
cd deploy/wdp-team-platform

# 1. 先建存储
kubectl apply -f k8s/pvc.yaml
kubectl get pvc -n wdp-team    # 等两块都变成 Bound

# 2. Secret 已在步骤 ③ 建好，这里只验证
kubectl get secret wdp-team-llm-secret -n wdp-team

# 3. WebUI 主服务
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml

# 4. 主 Agent（独立后台）
kubectl apply -f k8s/main-agent.yaml

# 5. 入口
kubectl apply -f k8s/ingress.yaml

# 观察启动
kubectl get pods -n wdp-team -w
kubectl logs -n wdp-team -l component=webui -f
```

### ⑤ 首次初始化：跑 init-knowledge.sh

知识库卷是空的，需要灌入 `team-soul.md` 和初始 skills，并把 `knowledge/` 对接 gitlab 远程仓库：

```bash
# 进入一个 WebUI Pod（任意一个都行，因为卷是共享的）
kubectl exec -it -n wdp-team deploy/wdp-team-webui -- bash

# 在 Pod 内执行
bash /path/to/scripts/init-knowledge.sh \
  --knowledge-dir /data/knowledge \
  --gitlab-remote git@gitlab.your-company.com:wdp/knowledge.git \
  --team-config /path/to/team-config
exit
```

脚本职责：
1. 在 `/data/knowledge` 下 `git init` 并配置远程
2. 从 gitlab 拉取已有知识库内容（若有）
3. 把 `team-config/team-soul.md`、`team-config/skills/` 复制进知识库
4. 提交并推送初始 commit（如知识库是新建）

### ⑥ 添加第一个管理员账号

平台首次启动时 `users.json` 是空的，**第一个创建的账号自动成为管理员**。

**方式 A：用脚本（推荐，服务器一次性操作）**

```bash
kubectl exec -it -n wdp-team deploy/wdp-team-webui -- bash
bash /path/to/scripts/add-user.sh \
  --username admin \
  --password '<强密码>' \
  --profile admin \
  --role admin
exit
```

**方式 B：通过 WebUI 注册页**

直接访问 `https://team.wdp.example.com/`，首次会进入"初始化管理员"页面，按提示创建第一个账号即可（系统检测到 `users.json` 为空时自动开放注册，**仅第一个账号**，之后注册入口自动关闭）。

之后用该管理员登录，在「管理后台 → 用户管理」里可以继续加普通成员。

---

## 5. 运维替换清单

部署前请按下表逐项替换占位符。**建议先全文搜索 `<YOUR_` 和 `TODO` 标记**确保不遗漏。

| 文件 | 占位符 / 待改项 | 改成什么 | 示例 |
| --- | --- | --- | --- |
| `k8s/pvc.yaml` | `<YOUR_STORAGE_CLASS>`（出现 2 次） | 集群里支持 RWX 的 StorageClass 名 | `nfs-client` / `longhorn` / `alicloud-nas` |
| `k8s/pvc.yaml` | `namespace: wdp-team` | 实际 namespace（如改） | `wdp-prod` |
| `k8s/deployment.yaml` | `image: wdp-team-platform:latest` | 完整镜像仓库地址 + tag | `harbor.your-company.com/wdp/wdp-team-platform:v1.0.0` |
| `k8s/main-agent.yaml` | `image: wdp-team-platform:latest` | 同上 | 同上 |
| `k8s/main-agent.yaml` | `HERMES_LLM_MODEL` | 实际使用的模型 | `moonshotai/kimi-k3` |
| `k8s/ingress.yaml` | `team.wdp.example.com`（出现 2 次） | 实际域名 | `wdp.ai.your-company.com` |
| `k8s/ingress.yaml` | `wdp-team-tls-secret` | TLS 证书 Secret 名 | `wdp-prod-tls` |
| `k8s/ingress.yaml` | `ingressClassName: nginx` | 实际 Ingress Controller | `nginx` / `traefik` / `alb` |
| `k8s/*.yaml` | 所有 `namespace: wdp-team` | 实际 namespace | 与上面保持一致 |
| `scripts/init-knowledge.sh` 参数 | `--gitlab-remote` | 团队知识库 gitlab 仓库地址 | `git@gitlab.your-company.com:wdp/knowledge.git` |
| 步骤 ③ | `OPENROUTER_API_KEY` | 团队真实 OpenRouter Key | 从 https://openrouter.ai/keys 申请 |

**TLS 证书 Secret 创建示例**：

```bash
kubectl create secret tls wdp-team-tls-secret \
  --cert=path/to/tls.crt \
  --key=path/to/tls.key \
  -n wdp-team
```

---

## 6. 日常维护

### 6.1 添加成员

**方式 A：脚本（适合批量初始化）**

```bash
kubectl exec -it -n wdp-team deploy/wdp-team-webui -- bash
bash /path/to/scripts/add-user.sh \
  --username zhangsan \
  --password '<初始密码>' \
  --profile zhangsan \
  --role member
```

脚本会：创建 `/data/profiles/zhangsan/` 目录 → 复制 `AGENTS.md.template` / `SOUL.md.template` → 注册到 `users.json`。

**方式 B：管理员界面（日常推荐）**

管理员登录 → 右上角头像 → 「管理后台」→ 「用户管理」→ 「添加用户」，填用户名 / 初始密码 / 角色即可，脚本干的事后台全自动做。

### 6.2 更新知识库 / skill / SOUL —— 不需要重新部署！

> ⭐ **关键设计**：`knowledge/`、skills、`team-soul.md`、各成员的 `SOUL.md` 全部是**数据**，存在共享 PVC 里，由 git 管理版本。更新这些内容**完全不需要重新构建镜像、不需要重启 Pod**。

**工作流**：

```bash
# 1. 在任意能访问 gitlab 的机器上克隆知识库
git clone git@gitlab.your-company.com:wdp/knowledge.git
cd knowledge

# 2. 改内容（新增/修改 team-soul.md、skills、signals、requirements、designs 等）
vim team-soul.md
vim skills/signal-intake/SKILL.md

# 3. 提交并推送
git add . && git commit -m "update signal-intake skill" && git push

# 4. 服务器侧拉取（手动 or 由主 Agent 定时 pull）
kubectl exec -it -n wdp-team deploy/wdp-team-webui -- \
  bash -c "cd /data/knowledge && git pull"
```

所有 Pod 因为挂的是同一个共享卷，**pull 一次，全员生效**，Agent 下次调用 skill 时自动读到新版本。

> 个人 SOUL.md 更简单：成员在「个人中心」里直接编辑保存，即改即生效。

### 6.3 升级代码（WebUI 本体 / overlay / agent 源码）

只有**代码**变更（Dockerfile、webui-overlay、agent-src、web-ui 上游）才需要重新构建：

```bash
# 1. Jenkins 或本地构建新镜像并推送（同步骤 ②）
export VERSION=$(git describe --tags --always)
docker build -f deploy/wdp-team-platform/Dockerfile -t ${REGISTRY}/wdp-team-platform:${VERSION} .
docker push ${REGISTRY}/wdp-team-platform:${VERSION}

# 2. 更新 Deployment 镜像 tag（推荐用 set image，不改 yaml）
kubectl set image deployment/wdp-team-webui \
  webui=${REGISTRY}/wdp-team-platform:${VERSION} -n wdp-team
kubectl set image deployment/wdp-team-main-agent \
  main-agent=${REGISTRY}/wdp-team-platform:${VERSION} -n wdp-team

# 或者 tag 没变、只想强制重新拉镜像：
kubectl rollout restart deployment/wdp-team-webui -n wdp-team
kubectl rollout restart deployment/wdp-team-main-agent -n wdp-team

# 3. 观察滚动更新（maxUnavailable=0 保证服务不中断）
kubectl rollout status deployment/wdp-team-webui -n wdp-team
```

### 6.4 备份

| 对象 | 备份方式 | 频率建议 |
| --- | --- | --- |
| **knowledge 卷** | 主要靠 `git push` 到 gitlab（`knowledge/` 本身就是 git 仓库）；额外可做 PVC 快照兜底 | git push 实时；快照每日 |
| **profiles 卷** | 云厂商 PVC 快照（`VolumeSnapshot`）或 Velero | 每日 |
| **users.json** | 在 profiles 卷的 `default/webui/` 下，随 profiles 快照一起备份 | 每日 |
| **K8s 清单 + 交付包** | 代码仓库本身就是备份 | 每次提交 |

**快照示例（Velero）**：

```bash
velero backup create wdp-team-daily-$(date +%Y%m%d) \
  --include-namespaces wdp-team \
  --snapshot-volumes \
  --ttl 720h        # 保留 30 天
```

---

## 7. Jenkins 流水线建议

三步：**build → push → apply**。建议在项目根放一个 `Jenkinsfile`：

```groovy
pipeline {
    agent any

    environment {
        REGISTRY   = 'harbor.your-company.com/wdp'                // ← 运维改
        IMAGE      = "${REGISTRY}/wdp-team-platform"
        KUBECONFIG = credentials('wdp-team-kubeconfig')           // Jenkins 凭据里维护
        REGISTRY_CRED = 'harbor-credentials'                      // Jenkins 凭据 ID
    }

    stages {
        stage('Prepare') {
            steps {
                sh 'cp deploy/wdp-team-platform/.dockerignore .dockerignore'
                script {
                    env.VERSION = sh(returnStdout: true,
                        script: 'git describe --tags --always').trim()
                }
            }
        }

        stage('Build') {
            steps {
                sh """
                    docker build \\
                      -f deploy/wdp-team-platform/Dockerfile \\
                      -t ${IMAGE}:${VERSION} \\
                      -t ${IMAGE}:latest \\
                      --build-arg HERMES_VERSION=${VERSION} \\
                      .
                """
            }
        }

        stage('Push') {
            steps {
                withDockerRegistry([credentialsId: "${REGISTRY_CRED}", url: "https://${REGISTRY}"]) {
                    sh "docker push ${IMAGE}:${VERSION}"
                    sh "docker push ${IMAGE}:latest"
                }
            }
        }

        stage('Deploy') {
            steps {
                sh """
                    kubectl set image deployment/wdp-team-webui \\
                        webui=${IMAGE}:${VERSION} -n wdp-team
                    kubectl set image deployment/wdp-team-main-agent \\
                        main-agent=${IMAGE}:${VERSION} -n wdp-team
                    kubectl rollout status deployment/wdp-team-webui -n wdp-team --timeout=300s
                    kubectl rollout status deployment/wdp-team-main-agent -n wdp-team --timeout=300s
                """
            }
        }
    }

    post {
        failure {
            echo '部署失败，开始回滚...'
            sh 'kubectl rollout undo deployment/wdp-team-webui -n wdp-team || true'
            sh 'kubectl rollout undo deployment/wdp-team-main-agent -n wdp-team || true'
        }
        success {
            echo "部署成功：${IMAGE}:${VERSION}"
        }
    }
}
```

**触发策略建议**：
- `main` 分支 merge → 自动跑全流水线
- 打 tag (`v*.*.*`) → 自动跑 + 发 release 通知
- 其他分支 → 只 build 不部署

---

## 8. 常见问题 FAQ

### Q1: 知识库 / skill / SOUL 更新为什么不用重启？

因为它们都是**数据**，存在共享 PVC 上，由 git 管理版本。所有 Pod 挂的是同一块卷，改完 `git push` + 服务器 `git pull` 之后，文件内容立刻就是新的。Agent 在调用 skill / 读取 SOUL 时是**运行时实时读文件**，不是启动时加载到内存，所以不用重启。

只有**代码**（Dockerfile、webui-overlay、agent 源码、web-ui 上游）变更才需要重新 build 镜像 + rollout restart。

### Q2: 成员忘记密码怎么办？

**管理员**登录 → 「管理后台」→ 「用户管理」→ 找到该成员 → 「重置密码」→ 设置新初始密码 → 通知成员用新密码登录后立即修改。

如果**管理员本人**忘记密码：用 `kubectl exec` 进入任意 WebUI Pod，找到 `users.json`（位于 `HERMES_WEBUI_STATE_DIR`，默认 `/data/profiles/default/webui/users.json`），删除该管理员条目后用初始管理员脚本重新创建。**注意**这是高危操作，先备份 `users.json`。

### Q3: 如何查看某用户占用了多少资源？

资源占用按 **Pod 粒度**统计，不按用户粒度。看整个 WebUI 的资源：

```bash
kubectl top pods -n wdp-team -l component=webui
kubectl top pods -n wdp-team -l component=main-agent
```

看某个用户的**会话/存储**占用：

```bash
# 该用户的 profile 目录大小
kubectl exec -n wdp-team deploy/wdp-team-webui -- \
  du -sh /data/profiles/<username>

# 该用户的会话数量（活跃 SSE 连接）
kubectl exec -n wdp-team deploy/wdp-team-webui -- \
  ls /data/profiles/<username>/webui/sessions/ | wc -l
```

### Q4: 主 Agent 是干嘛的？和成员自己聊的 Agent 有什么区别？

| 维度 | 主 Agent | 成员 Agent |
| --- | --- | --- |
| 触发方式 | 定时任务 / 系统事件（cron） | 成员在 WebUI 主动对话 |
| 副本数 | 1（避免定时任务重复跑） | 2（高可用 + sticky session） |
| LLM Key | 团队公共 Key（Secret 注入） | 默认也用团队 Key，但理论上可配置个人 Key |
| 职责 | 知识库整理、入库审核、停滞提醒、数据同步 | 响应成员即时的问答 / 写作 / 分析需求 |
| 是否暴露端口 | 否（纯后台） | 是（8787） |

**一句话**：成员 Agent 是"被人召唤的"，主 Agent 是"自己按时干活的"。

### Q5: WebUI 起不来，Pod 一直 CrashLoopBackOff 怎么排查？

按顺序看：

```bash
# 1. 看 Pod 状态和事件
kubectl describe pod -n wdp-team <pod-name>

# 2. 看日志（最常见原因）
kubectl logs -n wdp-team <pod-name> --previous

# 3. 常见原因清单
#    - PVC 没 Bound → kubectl get pvc -n wdp-team，看 StorageClass 是否支持 RWX
#    - Secret 不存在 → kubectl get secret wdp-team-llm-secret -n wdp-team
#    - 镜像拉不到 → 检查 image 地址 + imagePullSecret
#    - 端口被占 → 8787 是否被同 Pod 其他容器占用
#    - 权限问题 → 确认 fsGroup=1024 生效，卷属主是 hermeswebui
```

### Q6: 同一账号能在两个浏览器同时登录吗？

**不能**。平台做了**单点登录**：新登录会挤掉旧登录。这是设计意图，目的是：
- 避免同一账号多处会话互相覆盖 profile 状态
- 防止账号被共享滥用

旧浏览器会收到"您的账号已在其他地方登录"提示并被踢回登录页。

### Q7: 如何临时下线某个成员（比如离职）？

管理员后台 → 「用户管理」→ 找到该成员 → 「禁用」。

被禁用的账号立即无法登录，已登录的会话被强制下线。其 `profiles/<username>/` 目录保留，便于事后审计或交接，需要时可手动清理。

### Q8: 镜像能不能再瘦身？现在太大。

可以。当前镜像包含完整 web-ui + agent-src + Python 依赖，约 1.5–2GB。优化方向：
1. 主 Agent 单独构建一个**轻量镜像**（只含 agent 运行时，不含 web-ui 前端资源）
2. 用 `python:3.12-alpine` 替代 `slim`（需自行处理 glibc 依赖）
3. 多阶段构建，剥离构建期工具链

但默认交付包**优先保证开箱即用**，瘦身留作后续优化项。

---

## 9. 相关文档

- [BUILD.md](./BUILD.md) — 镜像构建详细说明
- [webui-overlay/README.md](./webui-overlay/README.md) — 多用户定制代码层设计
- [team-config/team-soul.md](./team-config/team-soul.md) — 团队铁律原文
- [k8s/](./k8s/) — 各 K8s 清单的内联注释（每份文件头部都有详细说明）

---

**维护**：本文档由 WDP 团队平台交付组维护，发现错漏请直接提 issue 或改完 push。
