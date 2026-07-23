#!/usr/bin/env python
"""WDP daily sync — Checks 1 & 2 (sheets via get_doc_content, not smartsheet)."""
import sys, json, re
import os
sys.path.insert(0, os.path.expanduser(r"~\.hermes\skills\wecom\wecom-docs\scripts"))
from wecom_docs_mcp_server import wecom_call

def read_doc_poll(url):
    """Like read_doc but save to file for full output."""
    resp = wecom_call("get_doc_content", {"url": url, "type": 2})
    if resp.get("errcode", 0) != 0:
        return f"ERROR: code={resp.get('errcode')} {resp.get('errmsg','')}"
    if resp.get("task_done"):
        return resp.get("content", "")
    task_id = resp.get("task_id", "")
    if not task_id:
        return f"No task_id in response: {resp}"
    for i in range(10):
        import time
        time.sleep(2)
        resp = wecom_call("get_doc_content", {"url": url, "type": 2, "task_id": task_id})
        if resp.get("errcode", 0) != 0:
            return f"ERROR poll: code={resp.get('errcode')} {resp.get('errmsg','')}"
        if resp.get("task_done"):
            return resp.get("content", "")
    return "Timeout waiting for doc content"

# Check 1: Version Release Index
print("=== CHECK 1: Version Release Index ===", flush=True)
r1 = read_doc_poll("https://doc.weixin.qq.com/sheet/e3_AZUAxwZjALEBtbaTLd8Tzev2qgcY2?tab=hhayiq")
print(r1[:6000] if r1 else "EMPTY")
print("---END_CHECK1---", flush=True)

# Check 2: Q2 R&D Progress
print("\n=== CHECK 2: Q2 R&D Progress ===", flush=True)
r2 = read_doc_poll("https://doc.weixin.qq.com/sheet/e3_AAIANAaZAL8CNak2Wg8bWSUKpNSd9?tab=BB08J2")
print(r2[:6000] if r2 else "EMPTY")
print("---END_CHECK2---", flush=True)
