#!/usr/bin/env python3
"""启动自愈：给成员 profile 的 config.yaml 补齐团队级 mcp_servers，并注入企微 MCP apikey。

背景：成员 config.yaml 由 add-user.sh 首次生成后不再覆盖，新增的团队级 MCP 配置不会
进入存量老 profile；且企微 MCP 的 apikey 是团队级凭据，我们希望管理员在平台 UI
（团队 Agent → 集成授权）配一次即可，不必麻烦运维配 K8s Secret。

本脚本在容器启动时（docker_init 启 server 前）跑一次，做两件事：
  1. 给缺 mcp_servers 的 profile 补齐 wecom_doc 配置（幂等、保护成员已有配置）。
  2. 解析企微 MCP apikey，把各 profile config.yaml 里的占位符 ${WECOM_MCP_APIKEY}
     就地替换为真实值——这样 server 启动读 config 时 URL 已是可用真值，不依赖环境变量。

apikey 来源（按优先级）：
  1. 环境变量 WECOM_MCP_APIKEY（若运维仍用 K8s Secret 注入，兼容保留）
  2. 团队 integrations.json 的 wecom_mcp.apikey（管理员在平台 UI 配，免运维——推荐）

设计约束：
  - 幂等 / 只增不改 / 单点失败不阻断容器启动。
  - 若拿不到 apikey，占位符原样保留（MCP 连不上但不影响其它功能）。
"""
import json
import os
import re
import sys
from pathlib import Path

MCP_URL_TEMPLATE = "https://qyapi.weixin.qq.com/mcp/robot-doc?apikey=${WECOM_MCP_APIKEY}"

MCP_BLOCK = """
# 团队级 MCP 服务：企业微信文档（官方 Streamable HTTP，全团队共用）
# 由 backfill_mcp_config.py 启动时自动补齐；apikey 由管理员在平台「集成授权」配置或 Secret 注入。
mcp_servers:
  wecom_doc:
    url: "{url}"
    timeout: 180
    connect_timeout: 30
""".format(url=MCP_URL_TEMPLATE)


def _team_root() -> Path | None:
    """团队级 HERMES_HOME 根（放 integrations.json）。多用户下 HERMES_HOME 可能指向
    profiles/<user>，integrations.json 在团队根，故向上回溯。"""
    home = os.getenv("HERMES_TEAM_HOME", "").strip() or os.getenv("HERMES_HOME", "").strip()
    if home:
        hp = Path(home)
        if (hp / "integrations.json").is_file():
            return hp
        if hp.parent.name == "profiles" and (hp.parent.parent / "integrations.json").is_file():
            return hp.parent.parent
    # 生产默认：profiles 根的上一级 或 default
    proot = Path(os.getenv("PROFILES_ROOT", "/data/profiles"))
    for cand in (proot / "default", proot.parent):
        if (cand / "integrations.json").is_file():
            return cand
    return None


def _resolve_apikey() -> str:
    """取企微 MCP apikey：环境变量优先，回落团队 integrations.json 的 wecom_mcp.apikey。"""
    env = os.getenv("WECOM_MCP_APIKEY", "").strip()
    if env:
        return env
    root = _team_root()
    if root:
        try:
            data = json.loads((root / "integrations.json").read_text(encoding="utf-8"))
            ak = ((data.get("wecom_mcp") or {}).get("apikey") or "").strip()
            if ak:
                return ak
        except Exception:
            pass
    return ""


def _has_wecom_mcp(cfg_text: str) -> bool:
    return "wecom_doc" in cfg_text and "mcp_servers" in cfg_text


def process_one(cfg_path: Path, apikey: str) -> str:
    """给单个 config.yaml 补 mcp_servers（若缺）并注入 apikey（若有）。"""
    try:
        text = cfg_path.read_text(encoding="utf-8")
    except Exception as e:
        return f"skip(read-fail: {e})"

    changed = False
    # 1) 补齐缺失的 mcp_servers.wecom_doc
    if not _has_wecom_mcp(text):
        if "\nmcp_servers:" in text or text.startswith("mcp_servers:"):
            return "skip(has-other-mcp_servers)"
        if not text.endswith("\n"):
            text += "\n"
        text += MCP_BLOCK
        changed = True

    # 2) 注入 apikey：把占位符替换成真值（幂等——已是真值则不含占位符，跳过）
    if apikey and "${WECOM_MCP_APIKEY}" in text:
        text = text.replace("${WECOM_MCP_APIKEY}", apikey)
        changed = True

    if not changed:
        return "already"
    try:
        cfg_path.write_text(text, encoding="utf-8")
    except Exception as e:
        return f"skip(write-fail: {e})"
    return "patched"


def seed_team_root() -> None:
    """铺设团队根（HERMES_HOME）的团队级文件：SOUL.md / config.yaml。

    根因：add-user 只初始化成员 profile，团队根 default 的 SOUL.md / config.yaml
    从没人建 → 团队 Agent 页全空（团队规则/模型/集成授权都读团队根文件）。
    这里启动时从镜像内置母本铺设，缺就补、已有不覆盖（保护管理员已改的规则）。

    母本源：TEAM_CONFIG_SRC（默认 /opt/hermes-team-config，Dockerfile COPY 进来）。
    """
    home = os.getenv("HERMES_TEAM_HOME", "").strip() or os.getenv("HERMES_HOME", "").strip()
    if not home:
        return
    home_p = Path(home)
    try:
        home_p.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"[seed_team_root] 无法创建团队根 {home_p}: {e}")
        return
    src = Path(os.getenv("TEAM_CONFIG_SRC", "/opt/hermes-team-config"))
    if not src.is_dir():
        print(f"[seed_team_root] 母本源不存在 {src}，跳过")
        return
    # (母本文件, 目标文件, 团队标记) —— 目标缺失时铺；已存在但"不含团队标记"(即官方默认
    # SOUL 或占位内容)时也覆盖成母本；只有"真正的团队内容"才保护不覆盖。
    # 背景：Hermes 首启会自建官方默认 SOUL.md，seed 若简单"存在就跳过"，团队规则就永远
    # 停留在官方默认（生产团队Agent页显示 "You are Hermes Agent..." 的根因）。
    seeds = [
        ("SOUL.md.team", "SOUL.md", "WDP 产品团队"),
        ("config.yaml.fallback-template", "config.yaml", None),
    ]
    for src_name, dst_name, marker in seeds:
        sp = src / src_name
        dp = home_p / dst_name
        if not sp.is_file():
            print(f"[seed_team_root] 母本缺失 {sp}，跳过 {dst_name}")
            continue
        if dp.exists():
            try:
                cur = dp.read_text(encoding="utf-8")
            except Exception:
                cur = ""
            # 有团队标记则视为管理员真配过的内容，保护不覆盖
            if marker and marker in cur:
                print(f"[seed_team_root] {dst_name}: 已含团队内容，保护不覆盖")
                continue
            # config.yaml 无标记概念：已存在就保护（成员/团队可能改过模型），只补不覆盖
            if marker is None:
                print(f"[seed_team_root] {dst_name}: 已存在，跳过（保护现有）")
                continue
            # SOUL 存在但不含团队标记 → 官方默认/占位，覆盖成团队母本
            print(f"[seed_team_root] {dst_name}: 现有内容非团队规则(官方默认?)，覆盖为母本 {src_name}")
        try:
            dp.write_text(sp.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"[seed_team_root] {dst_name}: 已从母本 {src_name} 铺设 ✅")
        except Exception as e:
            print(f"[seed_team_root] 铺设 {dst_name} 失败: {e}")
    # integrations.json 不铺母本（含凭据，由管理员在平台 UI 配）；但确保空文件存在，避免读取报错
    ij = home_p / "integrations.json"
    if not ij.exists():
        try:
            ij.write_text("{}", encoding="utf-8")
            print("[seed_team_root] integrations.json: 已建空文件（凭据由 UI 配）")
        except Exception:
            pass


def main() -> int:
    # ① 先铺团队根母本（SOUL.md / config.yaml），根治团队 Agent 页空
    seed_team_root()

    # ② 再做 MCP 配置补齐 + apikey 注入
    apikey = _resolve_apikey()
    if apikey:
        src = "env" if os.getenv("WECOM_MCP_APIKEY", "").strip() else "integrations.json"
        print(f"[backfill_mcp] 企微 apikey 已获取（来源：{src}），将注入各 profile")
    else:
        print("[backfill_mcp] 未获取到企微 apikey（管理员未在集成授权配置、也无 Secret）——占位符保留，MCP 暂不可用")

    profiles_root = Path(os.getenv("PROFILES_ROOT", "/data/profiles"))
    targets = []
    if profiles_root.is_dir():
        for d in sorted(profiles_root.iterdir()):
            if d.is_dir() and (d / "config.yaml").is_file():
                targets.append(d / "config.yaml")
    home = os.getenv("HERMES_HOME", "").strip()
    if home:
        hc = Path(home) / "config.yaml"
        if hc.is_file() and hc not in targets:
            targets.append(hc)

    if not targets:
        print(f"[backfill_mcp] 未找到任何 config.yaml (PROFILES_ROOT={profiles_root})")
        return 0

    counts = {"patched": 0, "already": 0, "skip": 0}
    for cfg in targets:
        st = process_one(cfg, apikey)
        key = "patched" if st == "patched" else ("already" if st == "already" else "skip")
        counts[key] += 1
        print(f"[backfill_mcp] {cfg}: {st}")
    print(f"[backfill_mcp] 完成 — 变更 {counts['patched']} / 已就绪 {counts['already']} / 跳过 {counts['skip']}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"[backfill_mcp] 非致命错误（不阻断启动）: {e}")
        sys.exit(0)
