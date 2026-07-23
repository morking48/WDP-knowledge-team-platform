#!/usr/bin/env python
"""Check Feishu wiki node for last-edit time vs skill snapshot date.

Reports whether the wiki was updated after the given baseline date.

凭证安全（团队规则：不可获取授权信息）：
    飞书 app_id / app_secret 一律从环境变量读取，严禁硬编码进本文件或提交进 git。
    访问在线文档使用管理员账号授权，凭证由管理员在个人环境变量 / K8s Secret 中配置。

环境变量：
    FEISHU_APP_ID      飞书应用 app_id
    FEISHU_APP_SECRET  飞书应用 app_secret

Usage:
    FEISHU_APP_ID=xxx FEISHU_APP_SECRET=xxx python scripts/feishu_check.py [--baseline 2026-05-11]
"""

import urllib.request
import json
import datetime
import os
import sys

# 凭证从环境变量读取（不可获取授权信息——不硬编码、不打印、不提交）
APP_ID = os.environ.get("FEISHU_APP_ID", "").strip()
APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "").strip()
WIKI_TOKEN = "wikcnmC72WN01k0vWsr54RbCWXg"  # WDP5 产品操作手册 wiki 节点（非敏感）

if not APP_ID or not APP_SECRET:
    print("FEISHU_CREDENTIALS_MISSING: 未检测到 FEISHU_APP_ID / FEISHU_APP_SECRET 环境变量。")
    print("请管理员配置授权（个人环境变量或 K8s Secret），凭证不得硬编码进代码或提交进 git。")
    sys.exit(3)

BASELINE = sys.argv[3] if len(sys.argv) > 3 and sys.argv[2] == "--baseline" else "2026-06-05"

# Step 1: get tenant_access_token
data = json.dumps({"app_id": APP_ID, "app_secret": APP_SECRET}).encode()
req = urllib.request.Request(
    "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
    data=data,
    headers={"Content-Type": "application/json"},
)
resp = json.loads(urllib.request.urlopen(req).read())
token = resp["tenant_access_token"]

# Step 2: query wiki node
req2 = urllib.request.Request(
    f"https://open.feishu.cn/open-apis/wiki/v2/spaces/get_node?token={WIKI_TOKEN}",
    headers={"Authorization": f"Bearer {token}"},
)
r = json.loads(urllib.request.urlopen(req2).read())

if r.get("code") != 0:
    print(f"FEISHU_API_ERROR: code={r.get('code')}, msg={r.get('msg')}")
    sys.exit(1)

n = r["data"]["node"]
et = int(n["obj_edit_time"])
ct = int(n["obj_create_time"])
ed = datetime.datetime.fromtimestamp(et, tz=datetime.timezone.utc).strftime("%Y-%m-%d")
cd = datetime.datetime.fromtimestamp(ct, tz=datetime.timezone.utc).strftime("%Y-%m-%d")

print(f"node_type: {n['node_type']}")
print(f"title: {n['title']}")
print(f"obj_create_time: {ct} ({cd})")
print(f"obj_edit_time: {et} ({ed})")
print(f"BASELINE: {BASELINE}")

if ed > BASELINE:
    print("RESULT: UPDATED")
    sys.exit(2)
else:
    print("RESULT: NO_CHANGE")
    sys.exit(0)
