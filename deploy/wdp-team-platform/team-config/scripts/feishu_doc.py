#!/usr/bin/env python3
"""飞书文档读取工具（供对话 agent 调用）。

用团队配置的飞书凭据（integrations.json）换 tenant_access_token，
调飞书云文档 API 拉取文档正文——绕过官方 web_extract 的限制（飞书文档需登录鉴权）。

用法：
    python feishu_doc.py <飞书文档URL或doc_token>
    python feishu_doc.py https://xxx.feishu.cn/docx/WMmwdAWOIo2GyQxpHN7c3EsqnRg
    python feishu_doc.py WMmwdAWOIo2GyQxpHN7c3EsqnRg

凭据来源（按优先级）：
    1. 环境变量 FEISHU_APP_ID / FEISHU_APP_SECRET
    2. 团队 HERMES_HOME 根的 integrations.json 的 feishu.app_id / app_secret
       （团队级配置，全团队共用一套；多用户下 agent 的 HERMES_HOME 可能被指到
       profiles/<user>，脚本会向上回溯到团队根找 integrations.json）

前置：飞书自建应用需开通「查看、评论、编辑和管理云文档」等文档读取权限，
      且目标文档已授权给该应用（或应用在文档所在空间有权限）。
"""
import json
import os
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path

# Windows 控制台默认 GBK，飞书文档含 emoji/生僻字会导致 print 崩溃 → 强制 UTF-8 输出
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

FEISHU_BASE = 'https://open.feishu.cn/open-apis'


def _load_cred() -> tuple[str, str]:
    """取飞书 app_id/app_secret：环境变量优先，回落团队 integrations.json。

    团队级配置：凭据存团队 HERMES_HOME 根的 integrations.json（全团队共用一套）。
    多用户下 agent 运行时 HERMES_HOME 可能被指到 profiles/<user>，故向上回溯找团队根。
    """
    aid = os.getenv('FEISHU_APP_ID', '').strip()
    sec = os.getenv('FEISHU_APP_SECRET', '').strip()
    if aid and sec:
        return aid, sec
    candidates = []
    home = os.getenv('HERMES_HOME', '').strip()
    if home:
        hp = Path(home)
        candidates.append(hp / 'integrations.json')
        # 若 HERMES_HOME 指向 profiles/<user>，团队根在上两级
        if hp.parent.name == 'profiles':
            candidates.append(hp.parent.parent / 'integrations.json')
    candidates.append(Path.home() / '.hermes' / 'integrations.json')
    for p in candidates:
        if p.is_file():
            try:
                data = json.loads(p.read_text(encoding='utf-8'))
                fs = data.get('feishu') or {}
                if fs.get('app_id') and fs.get('app_secret'):
                    return fs['app_id'].strip(), fs['app_secret'].strip()
            except Exception:
                pass
    return '', ''


def _tenant_token(app_id: str, app_secret: str) -> str:
    body = json.dumps({'app_id': app_id, 'app_secret': app_secret}).encode('utf-8')
    req = urllib.request.Request(
        f'{FEISHU_BASE}/auth/v3/tenant_access_token/internal',
        data=body, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.load(r)
    if d.get('code') != 0:
        raise RuntimeError(f'换 token 失败: code={d.get("code")} msg={d.get("msg")}')
    return d['tenant_access_token']


def _extract_token(url_or_token: str) -> tuple[str, str]:
    """从 URL 或裸 token 提取 (doc_token, doc_type)。doc_type: docx / doc / wiki。"""
    s = url_or_token.strip()
    # 裸 token（无 / 无 http）
    if '/' not in s and not s.startswith('http'):
        return s, 'docx'
    # URL：匹配 /docx/xxx /docs/xxx /wiki/xxx
    m = re.search(r'/(docx|docs|doc|wiki)/([A-Za-z0-9]+)', s)
    if m:
        kind = m.group(1)
        tok = m.group(2)
        dtype = 'wiki' if kind == 'wiki' else ('doc' if kind in ('doc', 'docs') else 'docx')
        return tok, dtype
    # 兜底：取最后一段路径
    tail = s.rstrip('/').split('/')[-1].split('?')[0]
    return tail, 'docx'


def _get(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + token})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode('utf-8'))
        except Exception:
            return {'code': e.code, 'msg': f'HTTP {e.code}'}


def read_doc(url_or_token: str) -> dict:
    app_id, app_secret = _load_cred()
    if not app_id or not app_secret:
        return {'ok': False, 'error': '未找到飞书凭据。飞书凭据为团队级配置，请管理员到「团队 Agent → 集成授权」配置飞书 App ID/Secret，或设 FEISHU_APP_ID/FEISHU_APP_SECRET 环境变量。'}
    try:
        token = _tenant_token(app_id, app_secret)
    except Exception as e:
        return {'ok': False, 'error': str(e)}

    doc_token, dtype = _extract_token(url_or_token)

    # wiki 节点先换成实际 doc obj_token
    if dtype == 'wiki':
        wd = _get(f'{FEISHU_BASE}/wiki/v2/spaces/get_node?token={doc_token}', token)
        if wd.get('code') == 0:
            node = wd.get('data', {}).get('node', {})
            doc_token = node.get('obj_token', doc_token)
            dtype = node.get('obj_type', 'docx')
        else:
            return {'ok': False, 'error': f'wiki 节点解析失败: {wd.get("msg")}（doc_token={doc_token}）'}

    # 优先新版 docx raw_content
    if dtype == 'docx':
        d = _get(f'{FEISHU_BASE}/docx/v1/documents/{doc_token}/raw_content', token)
        if d.get('code') == 0:
            return {'ok': True, 'doc_token': doc_token, 'type': 'docx',
                    'content': d.get('data', {}).get('content', '')}
        # 权限/类型问题回落旧版 doc
        err = f'docx 读取失败: code={d.get("code")} msg={d.get("msg")}'
    else:
        err = ''

    # 旧版 doc（doc/v2）
    d2 = _get(f'{FEISHU_BASE}/doc/v2/{doc_token}/content', token)
    if d2.get('code') == 0:
        raw = d2.get('data', {}).get('content', '')
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            return {'ok': True, 'doc_token': doc_token, 'type': 'doc', 'content': json.dumps(parsed, ensure_ascii=False)}
        except Exception:
            return {'ok': True, 'doc_token': doc_token, 'type': 'doc', 'content': raw}

    return {'ok': False, 'error': err or f'doc 读取失败: code={d2.get("code")} msg={d2.get("msg")}',
            'hint': '常见原因：①应用未开通云文档读取权限 ②该文档未授权给此应用（需在文档「...→添加文档应用」或空间成员里加该应用）'}


def main():
    if len(sys.argv) < 2:
        print(json.dumps({'ok': False, 'error': '用法: python feishu_doc.py <飞书文档URL或doc_token>'}, ensure_ascii=False))
        sys.exit(1)
    res = read_doc(sys.argv[1])
    if res.get('ok'):
        # 正文直接打印（供 agent 读取），附头部元信息
        print(f"# 飞书文档 [{res['type']}] {res['doc_token']}\n")
        print(res['content'])
    else:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        sys.exit(2)


if __name__ == '__main__':
    main()
