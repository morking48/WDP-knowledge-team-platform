#!/usr/bin/env python3
"""团队成员画像自动沉淀（≤150字）.

对话 agent 在真实协作中识别到某成员的能力表现/专长时，调用本脚本
把观察写入 knowledge/team/<姓名>.md 的「能力画像」段（自动沉淀，不走审核）。

设计原则：
  - 只沉淀有据的观察（本次真实体现出的**能力特质**），不脑补、不夸大。
  - **写能力和负责领域，不写某次任务动作/具体功能名**——抽象到能力层/产品线层，
    不要到具体功能、接口名、某次验收动作或"本次同步N个模块"这类当次流水。
  - 能力画像累计 ≤150 字（建议聚焦 120 字内）：新观察与旧画像融合，超长则精简。
  - 幂等：同一档案可多次更新，每次覆盖「能力画像」段。

用法：
  python update_member_profile.py --name 张健 --profile "负责前端架构与性能方向，擅长大场景渲染优化，技术扎实、风格严谨。"
"""
import argparse
import os
import re
import sys
from pathlib import Path


def find_team_dir() -> Path:
    # 优先环境变量，再按脚本位置上溯找 knowledge/team
    env = os.getenv('HERMES_KNOWLEDGE_DIR', '').strip()
    if env and (Path(env) / 'team').is_dir():
        return Path(env) / 'team'
    here = Path(__file__).resolve()
    for up in here.parents:
        cand = up / 'knowledge' / 'team'
        if cand.is_dir():
            return cand
    # 兜底：HERMES_HOME 同级
    home = os.getenv('HERMES_HOME', '').strip()
    if home:
        cand = Path(home).parent / 'knowledge' / 'team'
        if cand.is_dir():
            return cand
    return Path.cwd() / 'team'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--name', required=True, help='成员姓名（须与 team/<姓名>.md 对应）')
    ap.add_argument('--profile', required=True, help='能力画像文本（≤150字，与已有画像融合后的完整版）')
    args = ap.parse_args()

    profile = args.profile.strip()
    if len(profile) > 150:
        print(f'ERROR: 能力画像超过 150 字（当前 {len(profile)} 字），请精简后重试')
        sys.exit(2)

    team_dir = find_team_dir()
    fpath = team_dir / f'{args.name}.md'
    if not fpath.is_file():
        print(f'ERROR: 未找到成员档案 {fpath}（该成员可能不在团队名单，或姓名不符）')
        sys.exit(3)

    content = fpath.read_text(encoding='utf-8')
    # 覆盖「## 能力画像」段（到下一个 ## 或文件末尾）
    new_section = f'## 能力画像\n{profile}\n'
    pat = re.compile(r'## 能力画像\n.*?(?=\n## |\Z)', re.DOTALL)
    if pat.search(content):
        content = pat.sub(new_section, content, count=1)
    else:
        content = content.rstrip() + '\n\n' + new_section
    fpath.write_text(content, encoding='utf-8')

    # 回读自验证
    check = fpath.read_text(encoding='utf-8')
    if profile[:20] not in check:
        print('ERROR: 写入自检失败，请重试')
        sys.exit(4)
    print(f'OK: 已更新 {args.name} 的能力画像（{len(profile)} 字）')
    print(f'VERIFIED: {fpath}')


if __name__ == '__main__':
    main()
