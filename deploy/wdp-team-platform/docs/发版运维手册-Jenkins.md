# WDP 团队 AI 工作台 · 发版运维手册（Jenkins CI）

> 更新：2026-07-31。联系人：马冠杰（产品）。
> 适用：**首次部署已完成后**的日常迭代发版。首次落地见 `docs/部署说明-给运维.md`。
> 本手册回答一个问题：**改了东西之后，怎么发到生产。**

---

## 一、三仓库 + CI 全景（先看懂再操作）

| 角色 | 地址 | 内容 | 改动后果 |
|---|---|---|---|
| **平台仓库** | http://gitlab.51cloud.local/Maguanjie/wdp-team-platform | Dockerfile、k8s 清单、定制代码（web-ui / webui-overlay / agent-src）、脚本 | **改了要重新构建镜像 + 滚动更新** |
| **知识库仓库** | http://gitlab.51cloud.local/Maguanjie/wdp-team-knowledge | 团队知识数据（信号/需求/设计/项目，Markdown + git） | **push/pull 即生效，永不触发部署** |
| **Jenkins** | http://jenkins.51vr.local/view/WDP%205.0/job/wdp-team/build | 构建镜像 → 推 harbor → （改 tag → 滚动更新） | 平台仓库的发版入口 |
| **镜像仓库(harbor)** | harbor.51vr.local/wdp-service/wdp-team-platform | 构建产物，tag 递增（1→2→3→…） | k8s 按 tag 拉取 |

> **上游镜像源说明**：本地魔改 fork 的工程根在 GitHub（`morking48/WDP-knowledge-team-platform`），
> 但**生产环境只认这两个 gitlab 仓库**。开发在本地改完 → 同步推到 gitlab platform 仓库 → Jenkins 才能构建。
> GitHub 仅作开发备份，生产链路不经过它。

---

## 二、发版决策树：先判断改了什么

```
改了什么？
├─ 只改了知识库数据（信号/需求/设计/项目/团队规则）
│    → git push 到 wdp-team-knowledge → Pod 内 git pull（或等自动同步）
│    → 【不构建、不重启、不动 Jenkins】页面刷新即见
│
└─ 改了平台代码（web-ui / webui-overlay / agent-src / Dockerfile / k8s）
     → 走下面「三、代码发版标准流程」
```

**核心边界**：`wdp-team-platform` = 代码（要构建）；`wdp-team-knowledge` = 数据（push 即生效）。
搞混会导致「改了数据却去构建镜像」或「改了代码却只 push 数据不见效」。

---

## 三、代码发版标准流程（平台仓库）

### 步骤 0：本地改动同步到 gitlab
开发在本地（`E:\wdp-team-hermes`）改完、自测通过后，把 deploy 仓库推到 gitlab：

```bash
cd E:\wdp-team-hermes\deploy\wdp-team-platform
git add <改动文件>
git commit -m "fix/feat: 说明"
git -c http.sslVerify=false push origin main
```

> **三处同步铁律**：自研模块（web-ui/api、static 等）改动必须同步到
> `webui-overlay/` 和 `web-ui/` 两副本后再提交，否则镜像里跑的是旧代码。
> 详见 `docs/开发交接-HANDOVER.md`。

### 步骤 1：Jenkins 构建镜像
打开 http://jenkins.51vr.local/view/WDP%205.0/job/wdp-team/build

- 触发构建（Build Now / 按参数构建）
- Jenkins 做的事：拉 gitlab platform 仓库 → `docker build` → 推 harbor
- 产物：`harbor.51vr.local/wdp-service/wdp-team-platform:<新tag>`

### 步骤 2：⚠️ 递增镜像 tag（关键，最容易漏）
**harbor 同 tag 覆盖推送，k8s 不会重新拉取**（`imagePullPolicy: IfNotPresent`）。
所以每次发版**必须用新 tag**：

- 当前生产 tag：`:3`（见 `k8s/deployment.yaml` 和 `k8s/main-agent.yaml`）
- 下次发版：Jenkins 构建出 `:4`，然后**同步改两个 k8s 文件的 image tag**：

```bash
# k8s/deployment.yaml 和 k8s/main-agent.yaml 里：
image: harbor.51vr.local/wdp-service/wdp-team-platform:3   # 改成 :4
```

改完把 k8s 清单也 push 回 gitlab（保持仓库与生产一致）。

### 步骤 3：滚动更新
```bash
kubectl apply -f k8s/deployment.yaml    # WebUI Pod
kubectl apply -f k8s/main-agent.yaml    # main-agent Pod（如有改动）
kubectl -n wdp-team rollout status deployment/<name>   # 看滚动进度
```

> **首启慢是正常的**：容器首次启动会在线安装 web-ui/agent 依赖（走阿里云 pip 源），
> 探针 `initialDelaySeconds: 600`、`failureThreshold: 60` 就是为此放宽的——
> 给足 10 分钟，别以为卡住了。（曾踩坑：75s 被探针误杀反复重启）

### 步骤 4：验收
```bash
# 1. Pod 起来了
kubectl -n wdp-team get pods
# 2. 健康检查过
kubectl -n wdp-team exec <pod> -- curl -s localhost:8787/health
# 3. 登录页是定制品牌（不是 Hermes）
#    浏览器打开 → 标题应为「WDP产品协作平台」
# 4. 知识库 git 正常
kubectl -n wdp-team exec <pod> -- sh -c 'cd /data/knowledge && git log -1'
```

---

## 四、知识库数据发版（不走 Jenkins）

管理员在本地维护了知识库母版、或需要把 gitlab 上的知识同步进生产：

```bash
# 出向（本地 → gitlab）：管理员本地改完
cd knowledge && git push origin master

# 入向（gitlab → 生产卷）：在 Pod 里拉取
kubectl -n wdp-team exec <pod> -- sh -c 'cd /data/knowledge && git pull'
```

平台运行期的入库操作会**自动 git commit + push**到 knowledge 仓库
（push 串行锁 + rebase 重试已内置，多流转并发不会撞 ref）。
前提：Pod 内配好 git 身份（`wdp-workbench`）+ gitlab 凭据 Secret（`GIT_USER`/`GIT_TOKEN`）。

---

## 五、回滚

```bash
# 方式一：k8s 回退到上一个 revision（最快）
kubectl -n wdp-team rollout undo deployment/<name>

# 方式二：改回旧 tag 重新 apply
# k8s/deployment.yaml: image ...:4 → 改回 :3
kubectl apply -f k8s/deployment.yaml
```

镜像 tag 递增 + 保留历史 tag 的好处：任何一版都能靠 `:N` 精确回滚。**不要删 harbor 里的旧 tag。**

---

## 六、发版检查清单（每次照做）

- [ ] 本地自测通过（语法 + pyright + E2E）
- [ ] 三处同步（web-ui / webui-overlay / web-ui 副本）
- [ ] push 到 gitlab platform 仓库
- [ ] Jenkins 构建成功，产出新 tag
- [ ] **k8s 两个文件 image tag 已递增并 push**
- [ ] `kubectl apply` + `rollout status` 通过
- [ ] 验收 4 项（Pod / health / 登录品牌 / 知识库 git）
- [ ] 出问题能一键 `rollout undo`

---

## 七、关键坑位速查

| 现象 | 根因 | 处理 |
|---|---|---|
| 改了代码但生产没变 | tag 没递增，k8s 拉到旧镜像 | 递增 tag 重新 apply |
| Pod 反复重启 CrashLoop | 首启装依赖慢被探针杀（旧配置） | 确认探针 `initialDelaySeconds:600` |
| 入库能成但 gitlab 无提交 | Pod 内缺 git 身份 / 凭据 Secret | 查 `wdp-team-git-secret` |
| gitlab push 报 cannot lock ref | 并发流转撞车（旧版） | 已修（串行锁+rebase），升级镜像即可 |
| 登录页显示 Hermes | overlay 没打进镜像 / 旧镜像 | 重新构建，确认 tag 递增 |
| gitlab push 偶发 Could not resolve host | 内网 DNS 抖动 | 重试一次通常即好 |

---

## 八、当前生产状态基线（2026-07-31）

- 镜像：`harbor.51vr.local/wdp-service/wdp-team-platform:3`
- WebUI 端口：8787（NodePort 30787 对外）
- 存储：静态 NFS PV（knowledge + profiles 各一），见 `k8s/pv.yaml` / `k8s/pvc.yaml`
- 会话亲和：Ingress cookie + NodePort ClientIP（3h）
- 本版已含：登录页品牌化、审核公共/项目分组、统计口径修正、tui 崩溃修复、push 并发串行锁
