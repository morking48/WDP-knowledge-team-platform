# 部署 Checklist（给 IT/运维）

> 这是一份不带术语的操作清单。每一步都有验证方法，做完一步勾一步。
> 目标：在公司自己的服务器上跑起一个 Hermes Agent，团队成员能通过浏览器/企微访问使用。

## 前置确认

- [ ] 服务器一台（Linux，建议 Ubuntu 22.04 / CentOS 8+，4核8G 起步，不需 GPU）
- [ ] 服务器有内网固定 IP 或域名（团队能访问到即可）
- [ ] 一个可用的 LLM API key（任选其一：Kimi / DeepSeek / Qwen / 或公司内网已有模型服务的地址）
- [ ] （可选）如果要挂企业微信：需要企微管理员配合创建一个自建应用

## 第一步：安装 Hermes（10分钟）

```bash
# 用 root 或 sudo 执行
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash

# 验证
hermes --version
```

**验证通过标准**：能看到版本号输出。

## 第二步：配置模型（5分钟）

```bash
hermes setup
# 进入交互式向导，按提示选择模型 provider，填入 API key
```

**验证通过标准**：
```bash
hermes chat -q "你好，回复 OK"
# 能收到模型回复即通
```

## 第三步：跑起 Web 访问入口（10分钟）

```bash
# 启动 WebUI（团队通过浏览器访问的入口）
# 假设项目放在 /srv/wdp-team-hermes/
cd /srv/wdp-team-hermes
hermes webui --host 0.0.0.0 --port 8788
```

**验证通过标准**：在团队任意一台电脑浏览器打开 `http://<服务器IP>:8788`，能看到对话界面并正常对话。

> 正式部署建议用 systemd 托管，开机自启：
> ```bash
> # 配置文件参考 deploy/systemd/hermes-webui.service
> sudo systemctl enable hermes-webui
> sudo systemctl start hermes-webui
> ```

## 第四步：挂载团队共享目录（5分钟）

把本仓库的两个目录挂载为 Hermes 的共享资源：

- `skills/` → 所有 profile 的共享 skills 目录
- `knowledge/` → 团队知识资产库（git 仓库）

```bash
cd /srv/wdp-team-hermes/knowledge && git init && git add -A && git commit -m "init team knowledge base"
```

**验证通过标准**：在 WebUI 里让 agent 写一个测试文件到 `knowledge/signals/test.md`，服务器上能看到该文件。

## 第五步：为团队成员建 profile（每人2分钟）

```bash
hermes profile create zhangsan
hermes profile create lisi
# ... 以此类推
```

**验证通过标准**：`hermes profile list` 能看到所有成员。

## 第六步（可选）：挂企业微信 gateway（30分钟）

> 需要企微管理员配合。详细步骤见 Hermes 官方文档 + 本仓库 deploy/wecom-setup.md

```bash
hermes gateway setup   # 选 WeCom，按引导填 企业ID/应用Secret 等
hermes gateway install # 装成系统服务
hermes gateway start
```

**验证通过标准**：团队成员在企业微信里 @机器人 发"你好"，能收到回复。

## 第七步：安全与备份（10分钟）

- [ ] 防火墙只开放团队需要的端口（如 8788），不对外网开放
- [ ] 配置每日自动备份 `knowledge/` 目录（git push 到内网 git 服务器 或 rsync 到备份机）
- [ ] API key 写入 `/root/.hermes/.env`，文件权限 600，不进 git

## 常见坑

| 现象 | 原因 | 处理 |
|---|---|---|
| 浏览器打不开 WebUI | 防火墙没放端口 / 没加 `--host 0.0.0.0` | 检查 `ss -tlnp` 看端口监听地址 |
| 模型调用失败 | API key 错 / 内网代理没配 | `hermes doctor` 自检 |
| 企微机器人不回复 | gateway 没起来 / 回调地址不对 | `hermes gateway status` + 看日志 `~/.hermes/logs/gateway.log` |

## 完成标志

全部勾完即部署完成。团队成员可以：
1. 浏览器打开 `http://<服务器IP>:8788` 使用
2. （如配置了企微）在企业微信直接 @机器人 使用
