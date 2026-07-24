#!/usr/bin/env python3
"""生成知识库 index.md（OKF 渐进披露索引）.

扫各分区 md 的 frontmatter（title/description/status），生成：
  - knowledge/index.md            全库索引（各分区计数 + 活跃条目清单）
  - library/product-knowledge/index.md   母版库文件索引
  - library/archive/index.md             归档索引

用法（在 knowledge/ 目录或任意位置）：
  python generate_index.py [knowledge_root]
知识库有增删后重跑一次即可；也可挂到定时任务。纯标准库。
"""
import os
import re
import sys
import time


def parse_fm(path):
    try:
        raw = open(path, encoding='utf-8').read()
    except Exception:
        return {}
    m = re.match(r'^---\s*\n(.*?)\n---', raw, re.DOTALL)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).splitlines():
        if ':' in line and not line.startswith((' ', '\t', '-')):
            k, _, v = line.partition(':')
            fm[k.strip()] = v.strip().strip('"\'')
    return fm


def entry(name, fm, prefix=''):
    title = fm.get('title') or name
    desc = fm.get('description') or fm.get('note') or ''
    status = fm.get('status', '')
    st = f'（{status}）' if status else ''
    d = f' - {desc}' if desc else ''
    return f'* [{title}]({prefix}{name}){st}{d}'


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
    # 定位 knowledge 根（本脚本放 knowledge/scripts/ 下时上跳一级）
    if os.path.basename(root) == 'scripts':
        root = os.path.dirname(root)
    today = time.strftime('%Y-%m-%d %H:%M')

    # ── 1. 全库 index ──
    sections = []
    flowed = ('已转需求', '已合并', '已归档', '已关闭', '已废弃')
    for cat, label in [('signals', '📥 信号'), ('requirements', '📋 需求'),
                       ('designs', '📐 设计'), ('decisions', '⚖️ 决策'),
                       ('team', '👥 团队成员')]:
        d = os.path.join(root, cat)
        if not os.path.isdir(d):
            continue
        items, done = [], 0
        for f in sorted(os.listdir(d)):
            if not f.endswith('.md') or f in ('_template.md', 'README.md', 'index.md'):
                continue
            fm = parse_fm(os.path.join(d, f))
            if fm.get('status') in flowed:
                done += 1
                continue
            items.append(entry(f, fm, f'{cat}/'))
        head = f'# {label}（活跃 {len(items)}' + (f'，已流转 {done}' if done else '') + '）'
        sections.append(head + '\n\n' + ('\n'.join(items) if items else '（暂无）'))
    idx = (f'<!-- 由 scripts/generate_index.py 自动生成 · {today} · 勿手改 -->\n'
           f'# 团队知识库索引\n\n先读本索引再打开具体文件（渐进披露，省上下文）。\n\n'
           + '\n\n'.join(sections)
           + '\n\n# 📚 母版知识库\n\n* [product-knowledge](library/product-knowledge/) - WDP 产品知识索引 + 在线源同步脚本 + 业务 prompt 模板（见其 index.md）\n* [archive](library/archive/) - 已完成项目的历史归档\n')
    open(os.path.join(root, 'index.md'), 'w', encoding='utf-8').write(idx)

    # ── 2. 母版库 index ──
    pk = os.path.join(root, 'library', 'product-knowledge')
    if os.path.isdir(pk):
        lines = ['<!-- 自动生成 · %s -->' % today, '# 在线知识合集（母版）· 文件索引', '']
        DESC = {
            'README.md': '母版库说明',
            'scripts/feishu_check.py': '飞书文档变更检测（凭证走环境变量）',
            'scripts/daily_sync_check.py': '在线源日常巡检',
            'scripts/daily_sync_checks_1_2.py': '在线源巡检（分组1/2）',
            'scripts/filter_wecom_images.py': '企微文档 base64 图片过滤',
            'templates/api-tech-support-prompt.md': 'API 技术支持场景 prompt 模板',
            'templates/demand-routing-prompt.md': '需求路由场景 prompt 模板',
            'templates/external-doc-prompt.md': '对外文档生成 prompt 模板',
            'templates/presales-bidding-prompt.md': '售前应标场景 prompt 模板',
            'templates/support-session-prompt.md': '售后支持会话 prompt 模板',
        }
        for grp, title in [('', '# 根'), ('scripts', '# 同步脚本'), ('templates', '# 业务 prompt 模板')]:
            d = os.path.join(pk, grp) if grp else pk
            if not os.path.isdir(d):
                continue
            lines.append(title if grp else '# 说明')
            lines.append('')
            for f in sorted(os.listdir(d)):
                p = os.path.join(d, f)
                if not os.path.isfile(p) or f == 'index.md':
                    continue
                rel = f'{grp}/{f}' if grp else f
                desc = DESC.get(rel, '')
                if f.endswith('.md') and not desc:
                    desc = parse_fm(p).get('description', '')
                lines.append(f'* [{f}]({rel})' + (f' - {desc}' if desc else ''))
            lines.append('')
        open(os.path.join(pk, 'index.md'), 'w', encoding='utf-8').write('\n'.join(lines))

    # ── 3. 归档 index ──
    ar = os.path.join(root, 'library', 'archive')
    if os.path.isdir(ar):
        lines = ['<!-- 自动生成 · %s -->' % today, '# 历史归档索引', '']
        found = False
        for dirpath, _, files in os.walk(ar):
            for f in sorted(files):
                if f.endswith('.md') and f not in ('README.md', 'index.md'):
                    rel = os.path.relpath(os.path.join(dirpath, f), ar).replace('\\', '/')
                    fm = parse_fm(os.path.join(dirpath, f))
                    lines.append(entry(rel, fm))
                    found = True
        if not found:
            lines.append('（暂无归档）')
        open(os.path.join(ar, 'index.md'), 'w', encoding='utf-8').write('\n'.join(lines) + '\n')

    print(f'OK: index.md ×3 已生成（{today}）')


if __name__ == '__main__':
    main()
