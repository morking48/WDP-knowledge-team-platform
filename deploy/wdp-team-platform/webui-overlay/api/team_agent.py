"""
WDP 团队工作台 · 团队 Agent 配置（P1，admin 专属）.

管理员在个人中心「团队 Agent」子页可视化配置：
  - 团队规则（团队 SOUL.md，所有成员 agent 共享的人格/铁律）
  - 团队默认模型（config.yaml 的 model.provider/default，成员未配个人渠道时的兜底）

不走后台改文件重启服务——改完即时生效（下次 agent 运行读最新）。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def _team_home() -> Path:
    """团队 HERMES_HOME（放 SOUL.md / config.yaml）。"""
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


def save_team_soul(content: str) -> dict:
    """写团队规则 SOUL.md。"""
    sp = _soul_path()
    try:
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


def publish_team_rules() -> dict:
    """把团队母本 SOUL.md 发布到所有成员 profile 的 SOUL.md（幂等替换标记块）。"""
    sp = _soul_path()
    if not sp.is_file():
        return {'error': '团队规则(SOUL.md)尚未保存，先保存再发布'}, 400
    try:
        block = sp.read_text(encoding='utf-8')
    except Exception as e:
        return {'error': f'读团队规则失败: {e}'}, 500
    home = _team_home()
    published = []
    errors = []
    profiles_dir = home / 'profiles'
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


def save_team_model(provider: str, model: str) -> dict:
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
