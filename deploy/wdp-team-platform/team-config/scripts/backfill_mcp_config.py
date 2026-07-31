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
    home = os.getenv("HERMES_HOME", "").strip()
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


def main() -> int:
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
