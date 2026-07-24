#!/usr/bin/env python3
"""
WDP 团队工作台 · 成员 agent 提交入库脚本（R31 核心链路）.

对话 agent 用 terminal 运行本脚本，把整理好的内容真正提交到入库审核：
  python submit_review.py --title "标题" --category signals --file /path/to/content.md

脚本做三件事（与 WebUI 的 review/submit 等价，纯文件系统操作，无需 HTTP/cookie）：
  1. 把内容写入当前 profile 的 inbox/<ts>-<title>.md
  2. 写 .meta.json（status=pending，决策中心扫盘即可见）
  3. 给所有管理员的 inbox 追加通知（铃铛+决策中心数字响应）
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path


def detect_profile_home() -> Path:
    """当前 agent 的 HERMES_HOME（就是成员自己的 profile 目录）。"""
    env = os.getenv('HERMES_HOME', '').strip()
    if env:
        return Path(env)
    return Path.home() / '.hermes'


def detect_username(home: Path) -> str:
    """从路径推断用户名：.../profiles/<user> → user；否则 default(admin)。"""
    parts = [p.lower() for p in home.parts]
    if 'profiles' in parts:
        i = parts.index('profiles')
        if i + 1 < len(home.parts):
            return home.parts[i + 1]
    return 'admin'


def team_root(home: Path) -> Path:
    """团队 HERMES_HOME 根（default）。成员 profile 的上两级。"""
    parts = [p.lower() for p in home.parts]
    if 'profiles' in parts:
        i = parts.index('profiles')
        return Path(*home.parts[:i])
    return home


# ── L2 稳态 loop：落盘前模板校验（与平台 knowledge.config.yaml 同一数据源）──
def _parse_frontmatter(content: str) -> dict:
    m = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).splitlines():
        if ':' in line and not line.startswith((' ', '\t', '-')):
            k, _, v = line.partition(':')
            fm[k.strip()] = v.strip().strip('"\'')
    return fm


def validate_content(category: str, content: str, root: Path) -> list:
    """返回缺失的必填字段列表（读团队 knowledge.config.yaml，单一数据源）。"""
    cfg_file = root.parent / 'knowledge' / 'knowledge.config.yaml'
    if not cfg_file.is_file():
        # 兜底路径：HERMES_KNOWLEDGE_DIR
        import os
        env = os.getenv('HERMES_KNOWLEDGE_DIR', '')
        if env:
            cfg_file = Path(env) / 'knowledge.config.yaml'
    required = []
    enforce = True
    if cfg_file.is_file():
        # 极简 yaml 子集解析（只取该分区的 required_fields / enforce_template）
        in_cat = False
        for line in cfg_file.read_text(encoding='utf-8').splitlines():
            if re.match(rf'^  {re.escape(category)}:\s*$', line):
                in_cat = True
                continue
            if in_cat:
                if re.match(r'^  \S', line):   # 下一个分区
                    break
                mm = re.search(r'required_fields:\s*\[([^\]]*)\]', line)
                if mm:
                    required = [x.strip() for x in mm.group(1).split(',') if x.strip()]
                if 'enforce_template: false' in line:
                    enforce = False
    if not required or not enforce:
        return []
    fm = _parse_frontmatter(content)
    return [f for f in required if not (fm.get(f) or '').strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--title', required=True, help='入库标题')
    ap.add_argument('--category', default='signals',
                    choices=['signals', 'requirements', 'designs', 'decisions'])
    ap.add_argument('--file', help='内容文件路径（md，含frontmatter）。不给则读 stdin')
    args = ap.parse_args()

    if args.file:
        content = Path(args.file).read_text(encoding='utf-8')
    else:
        content = sys.stdin.read()
    if not content.strip():
        print('ERROR: 内容为空'); sys.exit(1)

    home = detect_profile_home()
    username = detect_username(home)
    root0 = team_root(home)

    # ── L2：落盘前硬校验，缺字段直接报错（agent 看到清单会自行补全重试）──
    missing = validate_content(args.category, content, root0)
    if missing:
        print(f'ERROR: frontmatter 缺少必填字段: {", ".join(missing)}')
        print(f'请在 --- 包裹的 frontmatter 中补全这些字段后重新提交。')
        print(f'字段说明可参考 knowledge/{args.category}/_template.md')
        sys.exit(2)

    inbox = home / 'inbox'
    inbox.mkdir(parents=True, exist_ok=True)

    ts = time.strftime('%Y%m%d-%H%M%S')
    safe = re.sub(r'[\\/:*?"<>|\s]+', '-', args.title)[:40]
    fname = f'{ts}-{safe}.md'
    (inbox / fname).write_text(content, encoding='utf-8')

    meta = {
        'username': username,
        'profile': username if username != 'admin' else 'default',
        'title': args.title,
        'category': args.category,
        'submitted_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'file': fname,
        'suggestion': {'target_category': args.category},
        'status': 'pending',
    }
    (inbox / (fname + '.meta.json')).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')

    # 通知所有管理员（读团队 users.json 找 admin）
    root = team_root(home)
    users_file = root / 'webui' / 'users.json'
    notified = []
    try:
        data = json.loads(users_file.read_text(encoding='utf-8'))
        users = data if isinstance(data, list) else data.get('users', [])
        for u in users:
            if u.get('role') == 'admin' and u.get('active', True) is not False:
                uname = u.get('username')
                admin_inbox = root / 'inbox' if uname == 'admin' else root / 'profiles' / uname / 'inbox'
                admin_inbox.mkdir(parents=True, exist_ok=True)
                notif = {'from': 'system',
                         'message': f'📥 {username} 提交了入库申请「{args.title}」（{args.category}），请到决策中心审核',
                         'at': time.strftime('%Y-%m-%d %H:%M:%S'), 'read': False}
                with open(admin_inbox / 'notifications.jsonl', 'a', encoding='utf-8') as f:
                    f.write(json.dumps(notif, ensure_ascii=False) + '\n')
                notified.append(uname)
    except Exception as e:
        print(f'WARN: 通知管理员失败 {e}')

    # ── L1 稳态 loop：落盘回读自验证（防"假成功"）──
    fpath = inbox / fname
    mpath = inbox / (fname + '.meta.json')
    if not (fpath.is_file() and fpath.stat().st_size > 0 and mpath.is_file()):
        print(f'ERROR: 提交自检失败——inbox 文件未正确落盘（{fpath}），请重试')
        sys.exit(3)
    try:
        json.loads(mpath.read_text(encoding='utf-8'))
    except Exception:
        print(f'ERROR: 提交自检失败——meta.json 损坏，请重试')
        sys.exit(3)

    print(f'OK: 已提交入库审核 file={fname} 提交人={username} 已通知管理员={notified}')
    print(f'VERIFIED: inbox 落盘自检通过（{fpath}）')


if __name__ == '__main__':
    main()
