"""
WDP 团队工作台 · 团队 Agent 配置（P1，admin 专属）.

管理员在个人中心「团队 Agent」子页可视化配置：
  - 团队规则（团队 SOUL.md，所有成员 agent 共享的人格/铁律）
  - 团队默认模型（config.yaml 的 model.provider/default，成员未配个人渠道时的兜底）

不走后台改文件重启服务——改完即时生效（下次 agent 运行读最新）。
"""
from __future__ import annotations

from api._wdp_types import ApiResult

import logging
import json
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def _team_home() -> Path:
    """团队 HERMES_HOME（放 SOUL.md / config.yaml / integrations.json / 快照 / 技能草稿）。

    ⚠ 不能直接依赖运行时 HERMES_HOME：多用户 per-request profile 切换会把它改来改去，
    且 admin 绑的 default profile 会被解析成 base home（如 /data），导致
    「启动时把团队文件铺到 /data/profiles/default、请求时却去 /data 读」的读写错位
    （生产团队Agent页全空 + /data 下 mkdir Permission denied 的根因）。
    解法：显式 HERMES_TEAM_HOME 环境变量作为确定性锚点（deployment.yaml 设置），
    回落顺序：HERMES_TEAM_HOME > HERMES_HOME > default home。
    """
    th = os.getenv('HERMES_TEAM_HOME', '').strip()
    if th:
        return Path(th)
    env = os.getenv('HERMES_HOME', '').strip()
    if env:
        return Path(env)
    # 兜底：web-ui 的 default home
    try:
        from api.profiles import _DEFAULT_HERMES_HOME
        return Path(_DEFAULT_HERMES_HOME)
    except Exception:
        return Path.home() / '.hermes'


def _soul_path() -> Path:
    return _team_home() / 'SOUL.md'


def _config_path() -> Path:
    return _team_home() / 'config.yaml'


def get_team_agent() -> dict:
    """返回团队 agent 配置：团队规则(SOUL) + 默认模型。"""
    soul = ''
    sp = _soul_path()
    if sp.is_file():
        try:
            soul = sp.read_text(encoding='utf-8')
        except Exception as e:
            logger.warning('read team SOUL failed: %s', e)
    # 读默认模型
    provider = ''
    model = ''
    cp = _config_path()
    if cp.is_file():
        try:
            import yaml
            cfg = yaml.safe_load(cp.read_text(encoding='utf-8')) or {}
            m = cfg.get('model') or {}
            provider = m.get('provider', '')
            model = m.get('default', '')
        except Exception as e:
            logger.warning('read team config failed: %s', e)
    return {
        'soul': soul,
        'provider': provider,
        'model': model,
        'soul_path': str(sp),
        'config_path': str(cp),
    }


def _snapshot_dir() -> Path:
    d = _team_home() / '.soul-snapshots'
    d.mkdir(parents=True, exist_ok=True)
    return d


def _snapshot_soul(reason: str = '') -> str | None:
    """把当前团队 SOUL.md 存一份带时间戳的快照（发布/覆盖前调用，供回滚）。

    只保留最近 20 份，防无限膨胀。返回快照文件名。
    """
    sp = _soul_path()
    if not sp.is_file():
        return None
    try:
        ts = time.strftime('%Y%m%d-%H%M%S') + f'-{int(time.time()*1000)%1000:03d}'
        snap = _snapshot_dir() / f'{ts}.md'
        snap.write_text(sp.read_text(encoding='utf-8'), encoding='utf-8')
        # 清理：只留最近 20 份
        snaps = sorted(_snapshot_dir().glob('*.md'))
        for old in snaps[:-20]:
            try:
                old.unlink()
            except Exception:
                pass
        return snap.name
    except Exception as e:
        logger.warning('snapshot soul failed: %s', e)
        return None


def list_soul_snapshots() -> list[dict]:
    """列出快照（最新在前），供回滚选择。"""
    out = []
    for f in sorted(_snapshot_dir().glob('*.md'), reverse=True):
        try:
            out.append({'name': f.stem, 'size': f.stat().st_size,
                        'preview': f.read_text(encoding='utf-8')[:80]})
        except Exception:
            pass
    return out


def rollback_soul(snapshot_name: str = '') -> ApiResult:
    """回滚团队 SOUL 到指定快照（不传则回滚到最近一份历史快照）。

    注意：不传 snapshot_name 时，回滚目标是"最近的、且内容与当前不同的"快照——
    避免回滚到刚保存时留下的、内容等于当前的快照（那样等于没回滚）。
    回滚本身也先存一份快照（回滚可再回滚）。
    """
    snaps = sorted(_snapshot_dir().glob('*.md'), reverse=True)
    if not snaps:
        return {'error': '没有可回滚的历史快照'}, 404
    sp = _soul_path()
    cur = sp.read_text(encoding='utf-8') if sp.is_file() else ''
    if snapshot_name:
        target = _snapshot_dir() / (snapshot_name + '.md')
        if not target.is_file():
            return {'error': f'快照 {snapshot_name} 不存在'}, 404
    else:
        # 找最近一份内容与当前不同的快照（跳过等于当前的）
        target = None
        for s in snaps:
            try:
                if s.read_text(encoding='utf-8') != cur:
                    target = s
                    break
            except Exception:
                pass
        if target is None:
            return {'error': '没有与当前版本不同的历史快照可回滚'}, 404
    try:
        # 先把目标内容读进内存（避免下面存快照时若同名覆盖了 target）
        restored = target.read_text(encoding='utf-8')
        # 回滚前给当前版存一份快照（回滚可再回滚）
        _snapshot_soul('before-rollback')
        sp.write_text(restored, encoding='utf-8')
        return {'ok': True, 'restored_from': target.stem,
                'message': f'已回滚团队规则到快照 {target.stem}。如需生效到成员，请再点「发布」。'}
    except Exception as e:
        return {'error': f'回滚失败: {e}'}, 500


def save_team_soul(content: str) -> ApiResult:
    """写团队规则 SOUL.md（写前自动快照当前版，供回滚）。"""
    sp = _soul_path()
    try:
        _snapshot_soul('before-save')   # 覆盖前留快照
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(content or '', encoding='utf-8')
        return {'ok': True}
    except Exception as e:
        return {'error': f'保存失败: {e}'}, 500


# ── #8：团队规则发布——真正打通到成员 agent ──────────────────────────
# 成员对话 agent 读的是 profiles/<u>/SOUL.md（不是团队根 SOUL.md）。
# "保存"只落团队母本；"发布"才把规则块以幂等标记写进每个成员 profile。
_BLOCK_START = '<!-- ═══ WDP 团队规则（管理员发布，自动同步，勿手改此块）═══ -->'
_BLOCK_END = '<!-- ═══ WDP 团队规则结束 ═══ -->'


def _inject_block(soul_text: str, block: str) -> str:
    """把团队规则块写入 SOUL 文本（存在则原位替换，不存在则追加到开头）。"""
    import re as _re
    wrapped = f"{_BLOCK_START}\n{block.strip()}\n{_BLOCK_END}"
    if _BLOCK_START in soul_text:
        pat = _re.escape(_BLOCK_START) + r'[\s\S]*?' + _re.escape(_BLOCK_END)
        return _re.sub(pat, lambda _m: wrapped, soul_text)
    sep = '\n\n' if soul_text.strip() else ''
    # 团队规则放最前（最高优先级），成员个性在后
    return wrapped + '\n\n' + soul_text if soul_text.strip() else wrapped + '\n'


def _member_profiles_root() -> Path:
    """成员 profile 所在的父目录（遍历它下面每个成员发布团队规则）。

    两种布局：
      - 本地开发：HERMES_HOME=hermes-home，成员在 hermes-home/profiles/*（team_home 的子目录）
      - 生产多用户：HERMES_TEAM_HOME=/data/profiles/default，成员在 /data/profiles/*
        （team_home 的兄弟——成员目录的父级 = team_home 的父级）
    解析优先级：HERMES_PROFILES_ROOT 显式指定 > team_home/profiles(存在) > team_home 的父级(名为 profiles)。
    """
    env = os.getenv('HERMES_PROFILES_ROOT', '').strip()
    if env:
        return Path(env)
    home = _team_home()
    sub = home / 'profiles'
    if sub.is_dir():
        return sub
    # 生产：team_home 形如 .../profiles/default，成员在其父级 .../profiles
    if home.parent.name == 'profiles' or home.name == 'default':
        return home.parent
    return sub


def publish_team_rules() -> ApiResult:
    """把团队母本 SOUL.md 发布到所有成员 profile 的 SOUL.md（幂等替换标记块）。"""
    sp = _soul_path()
    if not sp.is_file():
        return {'error': '团队规则(SOUL.md)尚未保存，先保存再发布'}, 400
    try:
        block = sp.read_text(encoding='utf-8')
    except Exception as e:
        return {'error': f'读团队规则失败: {e}'}, 500
    published = []
    errors = []
    profiles_dir = _member_profiles_root()
    targets = []
    if profiles_dir.is_dir():
        targets = [p for p in profiles_dir.iterdir() if p.is_dir()]
    for pdir in targets:
        psoul = pdir / 'SOUL.md'
        try:
            cur = psoul.read_text(encoding='utf-8') if psoul.is_file() else ''
            psoul.write_text(_inject_block(cur, block), encoding='utf-8')
            published.append(pdir.name)
        except Exception as e:
            errors.append(f'{pdir.name}: {e}')
    import time as _t
    # 记录发布时间（前端展示"上次发布"）
    try:
        (_team_home() / '.team-soul-published').write_text(
            _t.strftime('%Y-%m-%d %H:%M'), encoding='utf-8')
    except Exception:
        pass
    return {'ok': True, 'published': published, 'errors': errors,
            'message': f'已发布到 {len(published)} 个成员 profile'
                       + (f'，{len(errors)} 个失败' if errors else '')}


def get_publish_status() -> str:
    try:
        f = _team_home() / '.team-soul-published'
        return f.read_text(encoding='utf-8').strip() if f.is_file() else ''
    except Exception:
        return ''


def get_team_rules_readonly() -> dict:
    """成员端只读视图：真实团队规则内容 + 发布时间（不需要 admin 权限）。"""
    soul = ''
    sp = _soul_path()
    if sp.is_file():
        try:
            soul = sp.read_text(encoding='utf-8')
        except Exception:
            pass
    return {'rules': soul, 'published_at': get_publish_status()}


def save_team_model(provider: str, model: str) -> ApiResult:
    """改团队默认模型（config.yaml 的 model.provider/default）。

    只改 model 段，保留其它配置。用 yaml 读改写。
    """
    provider = (provider or '').strip()
    model = (model or '').strip()
    if not provider or not model:
        return {'error': 'provider 和 model 必填'}, 400
    cp = _config_path()
    try:
        import yaml
        cfg = {}
        if cp.is_file():
            cfg = yaml.safe_load(cp.read_text(encoding='utf-8')) or {}
        if not isinstance(cfg.get('model'), dict):
            cfg['model'] = {}
        cfg['model']['provider'] = provider
        cfg['model']['default'] = model
        cp.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding='utf-8')
        return {'ok': True, 'provider': provider, 'model': model}
    except Exception as e:
        return {'error': f'保存失败: {e}'}, 500


# 供前端下拉：常见 provider + 模型（与 channels.py 的 PROVIDERS 对齐）
def model_options() -> dict:
    try:
        from api.channels import PROVIDERS
        return {'providers': {k: v.get('models', []) for k, v in PROVIDERS.items()}}
    except Exception:
        return {'providers': {'openrouter': ['moonshotai/kimi-k3']}}


# ── 团队级集成授权（飞书等，全团队共用一套凭据）──────────────────────────────
# 存团队 home 下 integrations.json（与 SOUL.md/config.yaml 同级）。
# hermes-home/ 已 gitignore；部署时该文件在服务器持久化卷上，不进任何仓库。
_SUPPORTED_INTEGRATIONS = {
    'feishu': ['app_id', 'app_secret'],
    'wecom_mcp': ['apikey'],   # 企业微信文档 MCP 的 apikey（官方机器人 MCP 接入，团队共用一套）
}


def _integrations_path() -> Path:
    return _team_home() / 'integrations.json'


def _mask_secret(s: str) -> str:
    s = s or ''
    if len(s) <= 10:
        return '••••' if s else ''
    return s[:4] + '•' * 8 + s[-4:]


def _load_team_integrations() -> dict:
    p = _integrations_path()
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding='utf-8')) or {}
        except Exception:
            return {}
    return {}


def get_team_integrations() -> dict:
    """读团队集成配置（secret 打码）。"""
    data = _load_team_integrations()
    out = {}
    for prov, fields in _SUPPORTED_INTEGRATIONS.items():
        cfg = data.get(prov) or {}
        entry = {}
        for f in fields:
            val = cfg.get(f, '')
            entry[f] = _mask_secret(val) if ('secret' in f or 'key' in f) else val
        entry['configured'] = bool(cfg.get(fields[0]) and cfg.get(fields[-1]))
        entry['updated_at'] = cfg.get('updated_at', '')
        out[prov] = entry
    return {'integrations': out}


def save_team_integration(provider: str, values: dict) -> ApiResult:
    """写团队某集成凭据。secret 为空/打码值时保留原值。"""
    if provider not in _SUPPORTED_INTEGRATIONS:
        return {'error': f'不支持的集成: {provider}'}, 400
    fields = _SUPPORTED_INTEGRATIONS[provider]
    data = _load_team_integrations()
    cur = data.get(provider) or {}
    new = dict(cur)
    for f in fields:
        v = (values.get(f) or '').strip()
        if ('secret' in f or 'key' in f) and (not v or '•' in v):
            continue
        new[f] = v
    new['updated_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
    data[provider] = new
    try:
        p = _integrations_path()
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        try:
            os.chmod(p, 0o600)
        except Exception:
            pass
    except Exception as e:
        return {'error': f'保存失败: {e}'}, 500
    return {'ok': True, 'provider': provider,
            'configured': bool(new.get(fields[0]) and new.get(fields[-1]))}
