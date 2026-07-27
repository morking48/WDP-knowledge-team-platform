#!/usr/bin/env python3
"""
WDP 团队工作台 · 测试环境全量重置脚本（R36）.

覆盖：对话(session/state.db)、工作台(knowledge业务数据→重造标准测试集)、
决策中心(inbox待审/agent-sessions决策日志)、成员(只留admin/zhangsan/lisi、密码重置)、
个人中心(设备/工作库配置/渠道/Memory增量)、工作库上传文件(所有profile+admin的uploads)、
通知、定时任务、merge-rule。

用法：先停服务，然后
  python reset_test_env.py           # 全量重置
"""
import glob
import json
import os
import shutil
import sqlite3
import subprocess
import sys

HOME = r"E:\wdp-team-hermes\hermes-home"
KB = r"E:\wdp-team-hermes\knowledge"
PY = r"E:\wdp-team-hermes\agent-src\.venv\Scripts\python.exe"

KEEP_USERS = {'admin', 'zhangsan', 'lisi'}
PASSWORDS = {'admin': 'Admin@2026', 'zhangsan': 'Test@2026', 'lisi': 'Test@2026'}


def clean_sessions():
    for f in glob.glob(HOME + r"\webui\sessions\*.json"):
        if '_index' not in f:
            os.remove(f)
    with open(HOME + r"\webui\sessions\_index.json", 'w') as f:
        f.write('{"sessions":[]}')
    try:
        c = sqlite3.connect(HOME + r"\state.db")
        for t in ('sessions', 'messages'):
            try:
                c.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        c.commit(); c.close()
    except Exception as e:
        print(f"  WARN state.db: {e}")
    # 各 profile 的 session/state
    for p in glob.glob(HOME + r"\profiles\*"):
        for sub in (r"webui\sessions", "sessions"):
            d = os.path.join(p, sub)
            if os.path.isdir(d):
                for f in glob.glob(d + r"\*"):
                    if os.path.isfile(f) and '_index' not in f:
                        os.remove(f)
        sdb = os.path.join(p, 'state.db')
        if os.path.isfile(sdb):
            try:
                c = sqlite3.connect(sdb)
                for t in ('sessions', 'messages'):
                    try:
                        c.execute(f"DELETE FROM {t}")
                    except Exception:
                        pass
                c.commit(); c.close()
            except Exception:
                pass
    print("✓ 对话 session 全清（webui + state.db + 各profile）")


def clean_inbox_uploads():
    # admin(default) + 各 profile 的 inbox / uploads / 工作库设备配置
    targets = [HOME] + glob.glob(HOME + r"\profiles\*")
    for p in targets:
        ib = os.path.join(p, 'inbox')
        if os.path.isdir(ib):
            shutil.rmtree(ib, ignore_errors=True)
        # workspace 下的上传文件 + agent 中转隐藏目录（.tmp_signals 等）
        # 保留 workspace 根的团队参考文档（如 团队说明.md）
        ws = os.path.join(p, 'workspace')
        if os.path.isdir(ws):
            up = os.path.join(ws, 'uploads')
            if os.path.isdir(up):
                shutil.rmtree(up, ignore_errors=True)
                os.makedirs(up, exist_ok=True)
            # 清 agent 生成的隐藏中转目录（. 开头，如 .tmp_signals）
            for hidden in glob.glob(ws + r"\.*"):
                if os.path.isdir(hidden):
                    shutil.rmtree(hidden, ignore_errors=True)
        # 个人中心配置：设备/工作库登记、渠道
        for cfgf in ('devices.json', 'channels.json'):
            fp = os.path.join(p, cfgf)
            if os.path.isfile(fp):
                os.remove(fp)
        # Memory 增量（保留文件头部说明的话可按需调整，这里直接清）
        mem = os.path.join(p, 'memories', 'MEMORY.md')
        if os.path.isfile(mem):
            os.remove(mem)
    # inbox 归档
    for p in targets:
        arch = os.path.join(p, '.inbox-archive')
        if os.path.isdir(arch):
            shutil.rmtree(arch, ignore_errors=True)
    print("✓ inbox/上传文件/设备工作库配置/渠道/Memory 全清（含 admin 最近上传）")


def clean_users():
    up = HOME + r"\webui\users.json"
    if not os.path.isfile(up):
        print("  WARN users.json 不存在"); return
    d = json.load(open(up, encoding='utf-8'))
    users = d if isinstance(d, list) else d.get('users', [])
    keep = [u for u in users if u.get('username') in KEEP_USERS]
    for u in keep:
        u['active'] = True
    if isinstance(d, list):
        json.dump(keep, open(up, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    else:
        d['users'] = keep
        json.dump(d, open(up, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    # 删多余 profile 目录
    for p in glob.glob(HOME + r"\profiles\*"):
        if os.path.basename(p) not in KEEP_USERS:
            shutil.rmtree(p, ignore_errors=True)
    # 重置密码（调 users.py 的哈希逻辑）
    sys.path.insert(0, r"E:\wdp-team-hermes\web-ui")
    os.environ.setdefault('HERMES_WEBUI_STATE_DIR', HOME + r"\webui")
    try:
        from api import users as U
        for uname, pwd in PASSWORDS.items():
            try:
                U.reset_password(uname, pwd)
            except Exception as e:
                print(f"  WARN 重置{uname}密码: {e}")
        print("✓ 成员只留 admin/zhangsan/lisi，密码已重置为标准测试密码")
    except Exception as e:
        print(f"  WARN 密码重置失败(可手动): {e}")


def clean_knowledge():
    # 业务数据清空
    # team/ 是长期知识（成员档案+能力画像），与 library 同级待遇，不参与重置
    for cat in ('signals', 'requirements', 'designs', 'decisions', 'tracking'):
        d = os.path.join(KB, cat)
        if os.path.isdir(d):
            for f in glob.glob(d + r"\*"):
                if os.path.isfile(f) and '_template' not in f:
                    os.remove(f)
    os.makedirs(os.path.join(KB, 'tracking'), exist_ok=True)
    # agent-sessions 决策日志清空
    ags = os.path.join(KB, 'agent-sessions')
    if os.path.isdir(ags):
        shutil.rmtree(ags, ignore_errors=True)
    print("✓ 工作台业务数据 + agent-sessions 决策日志清空")


def seed_test_data():
    """标准测试数据集：4信号(001/003同主题测归并) 2需求 2设计 2决策。"""
    files = {}
    files["signals/2026-07-18-kingbase-offline-upgrade.md"] = """---
id: SIG-20260718-001
type: 信号
date: 2026-07-18
source: 客户反馈
source_ref: 某能源集团国产化项目
title: 国产化离线环境缺一键升级工具
description: 国产化离线环境缺一键升级工具
category: 需求信号
urgency: 高
confidence: 高
related_module: 部署运维
status: 待triage
raw_excerpt: "现场纯离线金仓环境，升级要手动替换包。"
---

## 信号内容
国产化离线部署升级全靠手动，客户希望一键升级工具。
"""
    files["signals/2026-07-20-editor-4k-material-blur.md"] = """---
id: SIG-20260720-002
type: 信号
date: 2026-07-20
source: 会议纪要
source_ref: 7月20日产品周会
title: 编辑器材质面板4K屏下模糊
description: 编辑器材质面板4K屏下模糊
category: 问题信号
urgency: 中
confidence: 高
related_module: 编辑器
status: 待triage
raw_excerpt: "4K屏150%缩放下材质面板发虚。"
---

## 信号内容
编辑器材质面板在4K高分屏下模糊。
"""
    files["signals/2026-07-21-customer-manual-upgrade-pain.md"] = """---
id: SIG-20260721-003
type: 信号
date: 2026-07-21
source: 售前反馈
source_ref: 华南区售前周报
title: 客户抱怨离线环境升级流程繁琐
description: 客户抱怨离线环境升级流程繁琐
category: 需求信号
urgency: 中
confidence: 中
related_module: 部署运维
status: 待triage
raw_excerpt: "多个国产化客户反馈每次版本升级要停机手动操作。"
---

## 信号内容
华南区多个国产化项目客户反馈离线升级繁琐、需停机手动替换，希望简化。
"""
    files["signals/2026-07-22-scene-load-slow.md"] = """---
id: SIG-20260722-004
type: 信号
date: 2026-07-22
source: 客户反馈
source_ref: 某园区数字孪生项目
title: 大场景首次加载超过40秒
description: 大场景首次加载超过40秒
category: 问题信号
urgency: 高
confidence: 高
related_module: 渲染引擎
status: 待triage
raw_excerpt: "3GB场景包首次打开要40多秒。"
---

## 信号内容
园区级大场景首次加载超40秒，影响演示，希望优化。
"""
    files["requirements/REQ-20260721-kingbase-upgrade-tool.md"] = """---
id: REQ-20260721-001
type: 需求
date: 2026-07-21
title: 国产化离线环境一键升级工具
description: 国产化离线环境一键升级工具
status: 已确认
priority: P0
source_signals: [SIG-20260718-001]
related_module: 部署运维
owner: zhangsan
customer: 某能源集团
business_value: 降低国产化交付运维成本
effort_estimate: 中
target_release: WDP5.16
tags: [国产化]
tracking:
  - date: 2026-07-21
    event: 建档
    note: 由 SIG-20260718-001 沉淀
---

## 需求描述
为国产化离线部署提供一键升级工具。
"""
    files["requirements/REQ-20260721-material-batch-import.md"] = """---
id: REQ-20260721-002
type: 需求
date: 2026-07-21
title: 材质库批量导入
description: 材质库批量导入
status: 设计中
priority: P1
source_signals: []
related_module: 编辑器
owner: lisi
customer: 某设计院
business_value: 提升素材准备效率
effort_estimate: 中
target_release: WDP5.16
tags: [编辑器]
tracking:
  - date: 2026-07-21
    event: 建档
    note: 客户访谈提出
---

## 需求描述
支持材质库批量导入。
"""
    files["designs/DSN-20260722-kingbase-upgrade-tool.md"] = """---
id: DSN-20260722-001
type: 设计
date: 2026-07-22
title: 国产化一键升级工具设计
description: 国产化一键升级工具设计
requirement_id: REQ-20260721-001
status: 评审中
designer: zhangsan
target_release: WDP5.16
doc_url: 
---

## 设计目标
命令行+页面双入口一键升级，支持预检/升级/回滚。
"""
    files["designs/DSN-20260722-material-batch-import.md"] = """---
id: DSN-20260722-002
type: 设计
date: 2026-07-22
title: 材质库批量导入设计
description: 材质库批量导入设计
requirement_id: REQ-20260721-002
status: 草稿
designer: lisi
target_release: WDP5.16
doc_url: 
---

## 设计目标
拖入文件夹批量导入材质。
"""
    files["decisions/DEC-20260722-kingbase-only-db.md"] = """---
id: DEC-20260722-001
type: 决策
date: 2026-07-22
title: 国产化数据库统一采用金仓KingbaseES
description: 国产化数据库统一采用金仓KingbaseES
status: 生效中
decision_maker: 产品负责人
participants: [zhangsan, 架构组]
related_requirements: [REQ-20260721-001]
related_module: 部署运维
supersedes: 
superseded_by: 
---

## 决策内容
国产化项目数据库统一采用金仓KingbaseES。
"""
    files["decisions/DEC-20260722-editor-five-mainlines.md"] = """---
id: DEC-20260722-002
type: 决策
date: 2026-07-22
title: 编辑器能力对外统一表述为五大主线
description: 编辑器能力对外统一表述为五大主线
status: 生效中
decision_maker: 产品负责人
participants: [产品组]
related_requirements: []
related_module: 编辑器
supersedes: 
superseded_by: 
---

## 决策内容
编辑器对外统一为五大主线。
"""
    files["signals/2026-07-23-park-project-loading-complaint.md"] = """---
id: SIG-20260723-005
type: 信号
date: 2026-07-23
source: 售后工单
source_ref: 华东区售后工单 #4521
title: 项目现场演示时场景打开等待过久
description: 项目现场演示时场景打开等待过久
category: 问题信号
urgency: 高
confidence: 高
related_module: 渲染引擎
status: 待triage
raw_excerpt: "客户在业主汇报现场打开项目等了将近1分钟，非常尴尬。"
---

## 信号内容
华东区某智慧园区项目，现场给业主演示时打开场景等待近 1 分钟，客户强烈要求优化首次加载速度。
"""
    files["signals/2026-07-23-large-scene-preload-request.md"] = """---
id: SIG-20260723-006
type: 信号
date: 2026-07-23
source: 客户反馈
source_ref: 某交通枢纽数字孪生项目
title: 希望提供大场景预加载或分级加载机制
description: 希望提供大场景预加载或分级加载机制
category: 需求信号
urgency: 中
confidence: 中
related_module: 渲染引擎
status: 待triage
raw_excerpt: "枢纽场景资产量大，客户建议支持预加载/分块流式加载。"
---

## 信号内容
交通枢纽项目场景资产量大（>2GB），客户建议平台提供预加载或分级/分块加载机制，缩短进入场景的等待时间。
"""
    for rel, content in files.items():
        p = os.path.join(KB, rel.replace('/', os.sep))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8') as f:
            f.write(content)
    print(f"✓ 标准测试数据 {len(files)} 条（信号6/需求2/设计2/决策2；001+003升级组、004+005+006加载慢组，测n对n归并）")


def clean_misc():
    # team-tasks 重置
    tp = os.path.join(KB, 'team-tasks.json')
    if os.path.isfile(tp):
        d = json.load(open(tp, encoding='utf-8'))
        d['tasks'] = [t for t in d.get('tasks', []) if t.get('type') == 'builtin']
        for t in d['tasks']:
            t['enabled'] = False
            t['last_run'] = None
            t['last_result'] = None
            t['last_status'] = None
        json.dump(d, open(tp, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    # merge-rule 重置
    mr = os.path.join(HOME, 'merge-rule.txt')
    if os.path.isfile(mr):
        os.remove(mr)
    print("✓ 定时任务/merge-rule 重置")


def git_commit():
    try:
        subprocess.run(['git', '-C', KB, 'add', '-A'], capture_output=True, timeout=15)
        subprocess.run(['git', '-C', KB, 'commit', '-m', 'test: 环境全量重置(标准测试数据集)'],
                       capture_output=True, timeout=15)
        print("✓ knowledge git 已提交")
    except Exception as e:
        print(f"  WARN git: {e}")


if __name__ == '__main__':
    print("═══ WDP 工作台测试环境全量重置 ═══")
    clean_sessions()
    clean_inbox_uploads()
    clean_users()
    clean_knowledge()
    seed_test_data()
    clean_misc()
    git_commit()
    print("\n完成。账号: admin/Admin@2026, zhangsan/Test@2026, lisi/Test@2026")
