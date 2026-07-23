#!/usr/bin/env python
"""WDP daily sync checker — uses wecom_call directly for reliable async polling."""
import sys, json, re
import os
sys.path.insert(0, os.path.expanduser(r"~\.hermes\skills\wecom\wecom-docs\scripts"))
from wecom_docs_mcp_server import wecom_call, read_doc

def read_sheet(url):
    """Read a WeCom sheet as smartsheet."""
    resp = wecom_call("smartsheet_get_sheet", {"url": url})
    if resp.get("errcode", 0) != 0:
        return f"ERROR: {resp.get('errmsg', '')}"
    sheets = resp.get("sheet_list", [])
    if not sheets:
        return "No sheets found"
    output = [f"# Sheet: {url}"]
    for sheet in sheets[:5]:
        sheet_id = sheet.get("sheet_id") or sheet.get("id")
        sheet_title = sheet.get("title", sheet_id)
        fields_resp = wecom_call("smartsheet_get_fields", {"url": url, "sheet_id": sheet_id})
        fields = fields_resp.get("fields", [])
        field_names = [f.get("field_title", f.get("title", "?")) for f in fields]
        records_resp = wecom_call("smartsheet_get_records", {"url": url, "sheet_id": sheet_id})
        records = records_resp.get("records", [])
        output.append(f"\n## {sheet_title} ({len(records)} records)")
        if field_names:
            output.append("| " + " | ".join(field_names) + " |")
            output.append("|" + "---|" * len(field_names))
        for rec in records[:200]:
            row_data = rec.get("values", rec.get("record", rec.get("fields", {})))
            row = []
            for fname in field_names:
                val = row_data.get(fname, "")
                if isinstance(val, list):
                    parts = []
                    for item in val:
                        if isinstance(item, dict):
                            parts.append(item.get("text", ""))
                        else:
                            parts.append(str(item))
                    val = "".join(parts)
                elif isinstance(val, str) and val.isdigit() and len(val) == 13:
                    from datetime import datetime, timezone
                    val = datetime.fromtimestamp(int(val) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
                row.append(str(val).replace("|", "｜").replace("\n", " ").strip())
            output.append("| " + " | ".join(row) + " |")
    return "\n".join(output)

def filter_images(text):
    return re.sub(r'data:image[^;]*;base64,[A-Za-z0-9+/=]{100,}', '[IMAGE_REMOVED]', text)

# --- Check 1: Version Release Index ---
print("=== CHECK 1: Version Release Index ===")
try:
    result = read_sheet("https://doc.weixin.qq.com/sheet/e3_AZUAxwZjALEBtbaTLd8Tzev2qgcY2?tab=hhayiq")
    print(result[:8000])
    print("---END_CHECK1---")
except Exception as e:
    print(f"ERROR: {e}")

# --- Check 2: Q2 R&D Progress ---
print("\n=== CHECK 2: Q2 R&D Progress ===")
try:
    result = read_sheet("https://doc.weixin.qq.com/sheet/e3_AAIANAaZAL8CNak2Wg8bWSUKpNSd9?tab=BB08J2")
    print(result[:8000])
    print("---END_CHECK2---")
except Exception as e:
    print(f"ERROR: {e}")

# --- Check 3: WDP Process Rules ---
print("\n=== CHECK 3: WDP Process Rules ===")
try:
    result = read_doc("https://doc.weixin.qq.com/doc/w3_AJ8A9QZOAMICNO7arKJWMRpm0rMoh")
    result = filter_images(result)
    print(result[:10000])
    print("---END_CHECK3---")
except Exception as e:
    print(f"ERROR: {e}")

# --- Check 4: FAQ-2 Platform Issues ---
print("\n=== CHECK 4: FAQ-2 Platform Issues ===")
try:
    result = read_doc("https://doc.weixin.qq.com/doc/w3_AeUAdAbVAH06A5jhqdKRj2Ew6xiKs")
    result = filter_images(result)
    print(result[:10000])
    print("---END_CHECK4---")
except Exception as e:
    print(f"ERROR: {e}")

# --- Check 5: FAQ-1 Localization ---
print("\n=== CHECK 5: FAQ-1 Localization ===")
try:
    result = read_doc("https://doc.weixin.qq.com/doc/w3_AJ8A9QZOAMICNXhtpMH9OT20lOihK")
    result = filter_images(result)
    print(result[:10000])
    print("---END_CHECK5---")
except Exception as e:
    print(f"ERROR: {e}")

print("\n=== ALL CHECKS COMPLETE ===")
