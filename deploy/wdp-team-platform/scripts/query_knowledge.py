#!/usr/bin/env python3
"""团队知识库查询工具（对话 agent 的「读」脚本，对称于 submit_review.py 的「写」）.

成员问「XX项目什么状态 / 谁负责什么 / 知识库现状 / 找一下关于YY的信号」时，
对话 agent 用 terminal 运行本脚本拿准确数据再回答——比 read_file 硬翻快、准、省上下文。

靠 HERMES_KNOWLEDGE_DIR 环境变量定位 knowledge 根（服务已注入），路径必达；
兜底按脚本位置上溯 / HERMES_HOME 同级。

用法：
  python query_knowledge.py --stats                知识库全景（各分区数量+状态分布）
  python query_knowledge.py --find "金仓"          跨分区搜标题/正文，返回匹配条目
  python query_knowledge.py --project "南水北调"   某项目全貌（档案+项目需求+交付材料）
  python query_knowledge.py --projects             所有项目列表
  python query_knowledge.py --member 张健          某成员名下需求/信号/画像
  python query_knowledge.py --item SIG-20260728-1  某条目详情+追溯链
"""
import argparse
import os
import re
import sys
from pathlib import Path

WORKING = ['signals', 'requirements', 'designs', 'decisions', 'tracking']
CAT_LABEL = {'signals': '信号', 'requirements': '需求', 'designs': '设计',
             'decisions': '决策', 'tracking': '跟踪', 'team': '团队成员'}


def kb_root() -> Path:
    env = os.getenv('HERMES_KNOWLEDGE_DIR', '').strip()
    if env and Path(env).is_dir():
        return Path(env)
    here = Path(__file__).resolve()
    for up in here.parents:
        if (up / 'knowledge' / 'knowledge.config.yaml').is_file():
            return up / 'knowledge'
    home = os.getenv('HERMES_HOME', '').strip()
    if home:
        cand = Path(home).parent / 'knowledge'
        if cand.is_dir():
            return cand
    return Path.cwd()


def parse_fm(text: str) -> dict:
    out = {}
    m = re.match(r'^---\s*\n(.*?)\n---', text, re.DOTALL)
    if not m:
        return out
    for line in m.group(1).splitlines():
        if ':' not in line or line.strip().startswith('#'):
            continue
        k, v = line.split(':', 1)
        k = k.strip()
        v = v.split('#')[0].strip().strip('"\'')
        if v.startswith('[') and v.endswith(']'):
            inner = v[1:-1].strip()
            out[k] = [x.strip().strip('"\'') for x in inner.split(',') if x.strip()] if inner else []
        else:
            out[k] = v
    return out


def body_of(text: str) -> str:
    m = re.match(r'^---\s*\n.*?\n---\s*\n?', text, re.DOTALL)
    return text[m.end():] if m else text


def scan(root: Path, cat: str):
    """扫一个工作分区，返回 [(file, meta)]。"""
    d = root / cat
    out = []
    if d.is_dir():
        for f in sorted(d.glob('*.md')):
            if f.name.startswith('_') or f.name == 'README.md':
                continue
            try:
                out.append((f, parse_fm(f.read_text(encoding='utf-8'))))
            except Exception:
                pass
    return out


def list_projects(root: Path):
    pr = root / 'projects'
    out = []
    if pr.is_dir():
        for pd in sorted(pr.iterdir()):
            if not pd.is_dir() or pd.name.startswith(('_', '.')):
                continue
            pm = pd / 'project.md'
            if pm.is_file():
                try:
                    out.append((pd, parse_fm(pm.read_text(encoding='utf-8'))))
                except Exception:
                    pass
    return out


def cmd_stats(root: Path):
    print('=== 团队知识库全景 ===')
    for cat in WORKING:
        items = scan(root, cat)
        if cat == 'tracking':
            print(f'{CAT_LABEL[cat]}({cat}): {len(items)} 项')
            continue
        # 状态分布
        by_status = {}
        for _, m in items:
            s = m.get('status', '(无状态)')
            by_status[s] = by_status.get(s, 0) + 1
        dist = ' / '.join(f'{k}:{v}' for k, v in sorted(by_status.items())) or '—'
        print(f'{CAT_LABEL[cat]}({cat}): {len(items)} 条  [{dist}]')
    projs = list_projects(root)
    print(f'项目(projects): {len(projs)} 个')
    for pd, m in projs:
        rn = len([f for f in (pd / "requirements").glob("*.md") if not f.name.startswith("_")]) if (pd / "requirements").is_dir() else 0
        dn = len([f for f in (pd / "deliverables").glob("*.md") if not f.name.startswith("_")]) if (pd / "deliverables").is_dir() else 0
        print(f'  - {m.get("title", pd.name)}（客户:{m.get("customer","—")} 阶段:{m.get("phase","—")} 需求:{rn} 材料:{dn}）')
    tm = scan(root, 'team')
    print(f'团队成员(team): {len(tm)} 人')


def cmd_find(root: Path, kw: str):
    kw_l = kw.lower()
    hits = []
    for cat in WORKING:
        for f, m in scan(root, cat):
            txt = (m.get('title', '') + ' ' + m.get('description', '') + ' ' + body_of(f.read_text(encoding='utf-8'))).lower()
            if kw_l in txt:
                hits.append((cat, m.get('id', f.stem), m.get('title', ''), m.get('status', '')))
    # 项目内的需求/材料也搜
    for pd, _ in list_projects(root):
        for sub in ('requirements', 'deliverables'):
            sd = pd / sub
            if sd.is_dir():
                for f in sd.glob('*.md'):
                    if f.name.startswith('_'):
                        continue
                    m = parse_fm(f.read_text(encoding='utf-8'))
                    txt = (m.get('title', '') + ' ' + body_of(f.read_text(encoding='utf-8'))).lower()
                    if kw_l in txt:
                        hits.append((f'项目:{pd.name}/{sub}', m.get('id', f.stem), m.get('title', ''), m.get('status', '')))
    print(f'=== 搜索「{kw}」命中 {len(hits)} 条 ===')
    for cat, iid, title, status in hits:
        print(f'[{cat}] {iid} · {title} · {status}')
    if not hits:
        print('（无匹配。换个关键词，或用 --stats 看全景）')


def cmd_project(root: Path, name: str):
    projs = list_projects(root)
    match = [(pd, m) for pd, m in projs if name in pd.name or name in m.get('title', '')]
    if not match:
        print(f'未找到项目「{name}」。现有项目：' + ('、'.join(m.get("title", pd.name) for pd, m in projs) or '（无）'))
        return
    pd, m = match[0]
    print(f'=== 项目：{m.get("title", pd.name)} ===')
    print(f'客户：{m.get("customer","—")} · 商机号：{m.get("opportunity","—")} · 阶段：{m.get("phase","—")}')
    print(f'负责人：{m.get("owner","—")} · BD：{m.get("bd_owner","—")} · 客户对接：{m.get("tb_contact","—")} · 状态：{m.get("status","—")}')
    print(f'\n项目需求：')
    rd = pd / 'requirements'
    reqs = [parse_fm((rd / f.name).read_text(encoding='utf-8')) for f in rd.glob('*.md') if not f.name.startswith('_')] if rd.is_dir() else []
    for r in reqs:
        print(f'  - {r.get("id","")} · {r.get("title","")} · {r.get("status","")} · 负责:{r.get("owner","—")} · 源信号:{r.get("source_signals",[])}')
    if not reqs:
        print('  （暂无）')
    print(f'\n交付材料：')
    dd = pd / 'deliverables'
    dlvs = [parse_fm((dd / f.name).read_text(encoding='utf-8')) for f in dd.glob('*.md') if not f.name.startswith('_')] if dd.is_dir() else []
    for d in dlvs:
        print(f'  - {d.get("id","")} · {d.get("title","")} · {d.get("phase","")} · {d.get("status","")} · 绑定:{d.get("requirement_id","—")}')
    if not dlvs:
        print('  （暂无）')


def cmd_projects(root: Path):
    projs = list_projects(root)
    print(f'=== 所有项目（{len(projs)} 个）===')
    for pd, m in projs:
        print(f'- {m.get("title", pd.name)}（客户:{m.get("customer","—")} 阶段:{m.get("phase","—")} 状态:{m.get("status","—")}）')
    if not projs:
        print('（暂无项目）')


def cmd_member(root: Path, name: str):
    # 画像
    tf = root / 'team' / f'{name}.md'
    print(f'=== 成员：{name} ===')
    if tf.is_file():
        txt = tf.read_text(encoding='utf-8')
        m = parse_fm(txt)
        print(f'部门：{m.get("department","—")} · 职责：{m.get("role","—")}')
        pm = re.search(r'## 能力画像\s*\n(.*?)(?=\n## |\Z)', txt, re.DOTALL)
        if pm:
            print(f'能力画像：{pm.group(1).strip()}')
    else:
        print('（无成员档案）')
    # 名下需求/信号
    print(f'\n名下需求：')
    reqs = [m for _, m in scan(root, 'requirements') if m.get('owner') == name]
    for r in reqs:
        print(f'  - {r.get("id","")} · {r.get("title","")} · {r.get("status","")} · {r.get("priority","")}')
    if not reqs:
        print('  （无）')
    # 项目需求
    prj_reqs = []
    for pd, _ in list_projects(root):
        rd = pd / 'requirements'
        if rd.is_dir():
            for f in rd.glob('*.md'):
                if f.name.startswith('_'):
                    continue
                rm = parse_fm(f.read_text(encoding='utf-8'))
                if rm.get('owner') == name:
                    prj_reqs.append((pd.name, rm))
    if prj_reqs:
        print(f'\n名下项目需求：')
        for pn, rm in prj_reqs:
            print(f'  - [{pn}] {rm.get("id","")} · {rm.get("title","")} · {rm.get("status","")}')


def cmd_item(root: Path, iid: str):
    for cat in WORKING:
        for f, m in scan(root, cat):
            if m.get('id') == iid:
                print(f'=== {iid}（{CAT_LABEL.get(cat,cat)}）===')
                for k, v in m.items():
                    print(f'{k}: {v}')
                print('\n--- 正文 ---')
                print(body_of(f.read_text(encoding='utf-8'))[:1500])
                return
    # 项目内
    for pd, _ in list_projects(root):
        for sub in ('requirements', 'deliverables'):
            sd = pd / sub
            if sd.is_dir():
                for f in sd.glob('*.md'):
                    if f.name.startswith('_'):
                        continue
                    m = parse_fm(f.read_text(encoding='utf-8'))
                    if m.get('id') == iid:
                        print(f'=== {iid}（项目 {pd.name}/{sub}）===')
                        for k, v in m.items():
                            print(f'{k}: {v}')
                        print('\n--- 正文 ---')
                        print(body_of(f.read_text(encoding='utf-8'))[:1500])
                        return
    print(f'未找到条目 {iid}')


def main():
    ap = argparse.ArgumentParser(description='团队知识库查询工具')
    ap.add_argument('--stats', action='store_true', help='知识库全景')
    ap.add_argument('--find', help='跨分区搜关键词')
    ap.add_argument('--project', help='某项目全貌')
    ap.add_argument('--projects', action='store_true', help='所有项目列表')
    ap.add_argument('--member', help='某成员名下内容')
    ap.add_argument('--item', help='某条目详情')
    args = ap.parse_args()

    root = kb_root()
    if not (root / 'knowledge.config.yaml').is_file():
        print(f'ERROR: 未定位到团队知识库（root={root}）。请确认 HERMES_KNOWLEDGE_DIR 已设置。')
        sys.exit(2)

    if args.stats:
        cmd_stats(root)
    elif args.find:
        cmd_find(root, args.find)
    elif args.project:
        cmd_project(root, args.project)
    elif args.projects:
        cmd_projects(root)
    elif args.member:
        cmd_member(root, args.member)
    elif args.item:
        cmd_item(root, args.item)
    else:
        ap.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
