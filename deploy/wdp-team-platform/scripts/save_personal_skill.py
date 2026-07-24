#!/usr/bin/env python3
"""个人 skill 沉淀（对话 agent 协助，非用户手写）.

对话 agent 观察到某成员反复做某类任务、或掌握了一套可复用的方法后，
提炼成一个个人 skill，写入该成员 profile 的 skills/personal/<name>/SKILL.md。
沉淀后默认启用；成员可在个人中心开关/删除。

设计：
  - 只沉淀成员**反复出现、可复用**的工作方法，不为单次任务造 skill。
  - SKILL.md 遵循标准格式（frontmatter: name/description/version + 正文步骤）。
  - 幂等：同名 skill 覆盖更新（视为迭代改进）。
  - 落盘后回读自验证。

用法：
  python save_personal_skill.py --name 竞品周报整理 \
      --description "把竞品动态整理成结构化周报" --file /tmp/skill_body.md
  （--file 是 SKILL.md 完整内容；不给则读 stdin）
"""
import argparse
import os
import re
import sys
from pathlib import Path


def detect_profile_home() -> Path:
    h = os.getenv('HERMES_HOME', '').strip()
    if h:
        return Path(h)
    return Path.home() / '.hermes'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--name', required=True, help='skill 名（简短，作目录名与展示名）')
    ap.add_argument('--description', required=True, help='一句话描述（触发/用途）')
    ap.add_argument('--file', help='SKILL.md 完整内容文件；不给则读 stdin')
    args = ap.parse_args()

    name = args.name.strip()
    if not name or '/' in name or '\\' in name or name.startswith('.'):
        print('ERROR: 非法 skill 名'); sys.exit(2)

    if args.file:
        content = Path(args.file).read_text(encoding='utf-8')
    else:
        content = sys.stdin.read()
    content = content.strip()
    if not content:
        print('ERROR: skill 内容为空'); sys.exit(2)

    # 确保有合法 frontmatter（name/description）
    if not content.startswith('---'):
        content = (f'---\nname: {name}\n'
                   f'description: "{args.description.strip()}"\n'
                   f'version: 1.0.0\nscope: personal\n---\n\n' + content)

    home = detect_profile_home()
    sk_dir = home / 'skills' / 'personal' / name
    # 若之前被停用（在 .disabled 下），先移除旧的禁用副本避免歧义
    disabled_old = home / 'skills' / 'personal' / '.disabled' / name
    if disabled_old.is_dir():
        import shutil
        shutil.rmtree(disabled_old, ignore_errors=True)
    sk_dir.mkdir(parents=True, exist_ok=True)
    md = sk_dir / 'SKILL.md'
    md.write_text(content, encoding='utf-8')

    # 回读自验证
    if not md.is_file() or args.description.strip()[:10] not in md.read_text(encoding='utf-8'):
        print('ERROR: 沉淀自检失败，请重试'); sys.exit(4)
    print(f'OK: 已沉淀个人 skill「{name}」（默认启用，成员可在个人中心开关）')
    print(f'VERIFIED: {md}')


if __name__ == '__main__':
    main()
