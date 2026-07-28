"""
Hermes Web UI -- 个人模型渠道 + 设备环境登记（WDP 团队工作台，个人中心补全）.

对应原型「个人中心 → 模型渠道」和「个人工作库 → 设备环境」两块。

模型渠道（channels.json，Key 落 .env）：
  GET  /api/me/channels                列出个人渠道（Key 脱敏）
  POST /api/me/channels/save           新增/更新渠道（含 Key → 写 .env 600）
  POST /api/me/channels/delete         删除渠道
  POST /api/me/channels/test           测试连通性（真实 HTTP 探测）
  POST /api/me/channels/activate       设为对话默认渠道

设备/工作库（devices.json）：
  GET  /api/me/devices                 列出已登记设备 + 工作库
  POST /api/me/devices/register        登记当前设备（machine_id 指纹）
  POST /api/me/devices/remove          移除设备
  POST /api/me/workspaces/save         添加/更新工作库目录（本地路径+设备+git）
  POST /api/me/workspaces/remove       移除工作库

设计约束：
  - 纯标准库；Key 只写个人 .env（权限 600），列表接口脱敏（只回尾 4 位）
  - 服务商 → 环境变量名映射固定；一个都不配时对话走团队公共 Key 兜底
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

# 服务商 → (环境变量名, 测试 endpoint, 默认模型列表)
PROVIDERS = {
    'OpenRouter': {
        'env': 'OPENROUTER_API_KEY',
        'test_url': 'https://openrouter.ai/api/v1/key',
        'models': ['moonshotai/kimi-k3', 'anthropic/claude-sonnet-4', 'deepseek/deepseek-v3', 'openai/gpt-4o'],
    },
    'DeepSeek': {
        'env': 'DEEPSEEK_API_KEY',
        'test_url': 'https://api.deepseek.com/models',
        'models': ['deepseek-chat', 'deepseek-reasoner'],
    },
    'Kimi': {
        'env': 'MOONSHOT_API_KEY',
        'test_url': 'https://api.moonshot.cn/v1/models',
        'models': ['kimi-k3', 'kimi-k2', 'moonshot-v1-128k'],
    },
    'Anthropic': {
        'env': 'ANTHROPIC_API_KEY',
        'test_url': 'https://api.anthropic.com/v1/models',
        'models': ['claude-sonnet-4', 'claude-opus-4', 'claude-haiku-4'],
    },
    'Claude(n1n代理)': {
        'env': 'N1N_CLAUDE_KEY',
        'base_url': 'https://llm-api.net/v1',   # OpenAI 兼容代理
        'test_url': 'https://llm-api.net/v1/models',
        'models': ['claude-opus-4-6', 'claude-opus-4-5-20251101', 'claude-sonnet-4-5-20250929', 'claude-sonnet-4-6'],
    },
    'GitHub Copilot': {
        # 成员填自己的 GitHub Copilot token（gho_/ghu_/ghp_，来自本机 copilot 登录），
        # 用各自的 Copilot 订阅额度。token 走 OpenAI 兼容端点 api.githubcopilot.com。
        'env': 'COPILOT_GITHUB_TOKEN',
        'base_url': 'https://api.githubcopilot.com',
        'test_url': 'https://api.githubcopilot.com/models',
        'models': ['claude-opus-4.8', 'claude-sonnet-4.5', 'gpt-5', 'o3', 'gpt-4o'],
        'provider_id': 'copilot',   # 映射到 hermes 运行时的 provider 名
    },
    '自定义OpenAI兼容': {
        'env': 'CUSTOM_OPENAI_API_KEY',
        'test_url': '',   # 用渠道自带 base_url
        'models': [],
    },
}


def _home() -> Path:
    from api.profiles import get_active_hermes_home
    return Path(get_active_hermes_home())


def _channels_file() -> Path:
    return _home() / 'channels.json'


def _devices_file() -> Path:
    return _home() / 'devices.json'


def _env_file() -> Path:
    return _home() / '.env'


# ── 通用 json 读写 ─────────────────────────────────────────────────────────
def _read_json(p: Path, default):
    try:
        if p.exists():
            return json.loads(p.read_text(encoding='utf-8'))
    except Exception as e:
        logger.warning('read %s failed: %s', p, e)
    return default


def _write_json(p: Path, data):
    tmp = p.with_suffix(p.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, p)


# ── .env Key 读写（复用 providers 的读，写用本地实现，权限 600）───────────
def _load_env() -> dict:
    from api.providers import _load_env_file
    return _load_env_file(_env_file())


def _set_env_key(env_name: str, value: str | None):
    """写入/删除个人 .env 中一个 key，保留其它行，权限 600。"""
    ep = _env_file()
    lines = []
    found = False
    if ep.exists():
        for raw in ep.read_text(encoding='utf-8').splitlines():
            s = raw.strip()
            if s and not s.startswith('#') and '=' in s and s.split('=',1)[0].strip() == env_name:
                found = True
                if value:
                    lines.append(f'{env_name}={value}')
                # value 为 None 则删除（不追加）
            else:
                lines.append(raw)
    if not found and value:
        lines.append(f'{env_name}={value}')
    tmp = ep.with_suffix('.env.tmp')
    tmp.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    os.replace(tmp, ep)
    try:
        os.chmod(ep, 0o600)
    except Exception:
        pass


def _mask_key(k: str) -> str:
    if not k:
        return ''
    if len(k) <= 8:
        return '****'
    return k[:6] + '****' + k[-4:]


# ══════════════════════════════════════════════════════════════════
#  模型渠道
# ══════════════════════════════════════════════════════════════════
def list_channels() -> dict:
    data = _read_json(_channels_file(), {'channels': [], 'active_id': None})
    env = _load_env()
    out = []
    for c in data.get('channels', []):
        prov = PROVIDERS.get(c.get('provider'), {})
        env_name = prov.get('env', '')
        key = env.get(env_name, '') if env_name else ''
        out.append({
            'id': c.get('id'),
            'name': c.get('name'),
            'provider': c.get('provider'),
            'model': c.get('model'),
            'base_url': c.get('base_url', ''),
            'has_key': bool(key),
            'key_masked': _mask_key(key),
            'status': c.get('status', 'idle'),
            'enabled': bool(c.get('enabled', False)),
        })
    return {
        'channels': out,
        'active_id': data.get('active_id'),
        'providers': {p: {'models': PROVIDERS[p]['models']} for p in PROVIDERS},
    }


def save_channel(body: dict) -> dict:
    cid = body.get('id')
    name = (body.get('name') or '').strip() or '新渠道'
    provider = body.get('provider')
    model = (body.get('model') or '').strip()
    base_url = (body.get('base_url') or '').strip()
    key = body.get('key')  # 可选：不传则不改 Key
    enabled = bool(body.get('enabled', False))
    if provider not in PROVIDERS:
        return {'error': f'未知服务商 {provider}'}, 400

    data = _read_json(_channels_file(), {'channels': [], 'active_id': None})
    chans = data.get('channels', [])
    if not cid:
        cid = 'ch-' + str(int(time.time()*1000))
        chans.append({'id': cid, 'name': name, 'provider': provider, 'model': model,
                      'base_url': base_url, 'status': 'idle', 'enabled': enabled})
    else:
        for c in chans:
            if c.get('id') == cid:
                c.update({'name': name, 'provider': provider, 'model': model,
                          'base_url': base_url, 'enabled': enabled})
                break
        else:
            chans.append({'id': cid, 'name': name, 'provider': provider, 'model': model,
                          'base_url': base_url, 'status': 'idle', 'enabled': enabled})
    # 写 Key 到 .env（key 非空才写；显式传空串表示清除）
    if key is not None:
        env_name = PROVIDERS[provider]['env']
        _set_env_key(env_name, key.strip() or None)
    # 若启用且没有 active，设为 active
    if enabled and not data.get('active_id'):
        data['active_id'] = cid
    data['channels'] = chans
    _write_json(_channels_file(), data)
    return {'ok': True, 'id': cid}


def delete_channel(cid: str) -> dict:
    data = _read_json(_channels_file(), {'channels': [], 'active_id': None})
    data['channels'] = [c for c in data.get('channels', []) if c.get('id') != cid]
    if data.get('active_id') == cid:
        data['active_id'] = (data['channels'][0]['id'] if data['channels'] else None)
    was_chat_default = data.get('chat_channel_id') == cid
    if was_chat_default:
        data['chat_channel_id'] = ''
    _write_json(_channels_file(), data)
    # 删的是当前对话模型 → 自动切回团队默认，防 config 残留指向已删渠道
    if was_chat_default:
        try:
            set_chat_model('')
        except Exception:
            logger.warning('delete_channel: reset chat model to team default failed')
    return {'ok': True}


def activate_channel(cid: str) -> dict:
    data = _read_json(_channels_file(), {'channels': [], 'active_id': None})
    if not any(c.get('id') == cid for c in data.get('channels', [])):
        return {'error': '渠道不存在'}, 404
    data['active_id'] = cid
    _write_json(_channels_file(), data)
    return {'ok': True}


def test_channel(cid: str) -> dict:
    """真实探测：带 Key 请求服务商 models endpoint，2xx 视为连通。"""
    data = _read_json(_channels_file(), {'channels': [], 'active_id': None})
    chan = next((c for c in data.get('channels', []) if c.get('id') == cid), None)
    if not chan:
        return {'error': '渠道不存在'}, 404
    prov = PROVIDERS.get(chan.get('provider'), {})
    env_name = prov.get('env', '')
    key = _load_env().get(env_name, '') if env_name else ''
    if not key:
        _update_channel_status(cid, 'fail')
        return {'ok': False, 'status': 'fail', 'message': '未配置 API Key'}
    url = prov.get('test_url') or (chan.get('base_url', '').rstrip('/') + '/models')
    if not url:
        _update_channel_status(cid, 'fail')
        return {'ok': False, 'status': 'fail', 'message': '缺少测试地址'}
    try:
        req = urllib.request.Request(url)
        # Anthropic 用 x-api-key，其它用 Bearer
        if chan.get('provider') == 'Anthropic':
            req.add_header('x-api-key', key)
            req.add_header('anthropic-version', '2023-06-01')
        else:
            req.add_header('Authorization', 'Bearer ' + key)
        # GitHub Copilot 的 /models 需要客户端标识头，否则返回 403/404
        if chan.get('provider') == 'GitHub Copilot':
            req.add_header('Copilot-Integration-Id', 'vscode-chat')
            req.add_header('Editor-Version', 'vscode/1.95.0')
        with urllib.request.urlopen(req, timeout=12) as r:
            ok = 200 <= r.status < 300
        _update_channel_status(cid, 'ok' if ok else 'fail')
        return {'ok': ok, 'status': 'ok' if ok else 'fail',
                'message': '连通正常' if ok else f'HTTP {r.status}'}
    except urllib.error.HTTPError as e:
        # 401/403 = Key 错；其它 4xx/5xx 也算 fail
        _update_channel_status(cid, 'fail')
        return {'ok': False, 'status': 'fail', 'message': f'HTTP {e.code}（检查 Key）'}
    except Exception as e:
        _update_channel_status(cid, 'fail')
        return {'ok': False, 'status': 'fail', 'message': str(e)[:80]}


def _update_channel_status(cid: str, status: str):
    data = _read_json(_channels_file(), {'channels': [], 'active_id': None})
    for c in data.get('channels', []):
        if c.get('id') == cid:
            c['status'] = status
            break
    _write_json(_channels_file(), data)


# ══════════════════════════════════════════════════════════════════
#  对话模型切换：团队默认 + 成员个人已启用渠道
# ══════════════════════════════════════════════════════════════════
def _provider_runtime_id(provider_display: str) -> str:
    """把渠道展示名映射到 hermes 运行时 provider id。

    多数 OpenAI 兼容渠道运行时都当 'openai'（配 base_url）；copilot 是一等公民
    provider（有专门 token 兑换），Anthropic 走 anthropic。
    """
    prov = PROVIDERS.get(provider_display, {})
    if prov.get('provider_id'):
        return prov['provider_id']
    mapping = {
        'OpenRouter': 'openrouter',
        'DeepSeek': 'deepseek',
        'Kimi': 'moonshot',
        'Anthropic': 'anthropic',
    }
    return mapping.get(provider_display, 'openai')


def get_chat_model_options() -> dict:
    """对话顶部下拉的选项：团队默认 + 成员已启用且填了 Key 的渠道。

    current = 该 profile config.yaml 当前 default（None/空 = 团队默认）。
    """
    data = _read_json(_channels_file(), {'channels': [], 'active_id': None})
    env = _load_env()
    opts = [{'id': '', 'label': '团队默认模型', 'is_default': True}]
    for c in data.get('channels', []):
        if not c.get('enabled'):
            continue
        prov = PROVIDERS.get(c.get('provider'), {})
        env_name = prov.get('env', '')
        if env_name and not env.get(env_name):
            continue  # 没填 Key 的渠道不进对话下拉
        model = c.get('model') or (prov.get('models') or [''])[0]
        if not model:
            continue
        opts.append({
            'id': c.get('id'),
            'label': f"{c.get('name') or c.get('provider')} · {model}",
            'provider': c.get('provider'),
            'model': model,
        })
    # 读当前选中项：优先用落盘的渠道 id（唯一标识，不靠 model 名反推——
    # 否则团队默认和某渠道同 model 时会误判选中），渠道已删/禁用则回落团队默认
    current = _current_profile_default_model()
    sel_id = data.get('chat_channel_id') or ''
    if sel_id and not any(o.get('id') == sel_id for o in opts):
        sel_id = ''   # 选中的渠道已不在可用列表 → 视为团队默认
    return {'options': opts, 'current_model': current, 'current_channel_id': sel_id}


def _profile_config_path() -> Path:
    return _home() / 'config.yaml'


def _is_root_home() -> bool:
    """当前请求的 home 是否是团队根 home（admin 用根，成员用各自 profile）。"""
    try:
        from api.profiles import _DEFAULT_HERMES_HOME
        return Path(_home()).resolve() == Path(_DEFAULT_HERMES_HOME).resolve()
    except Exception:
        return False


def _current_profile_default_model() -> str:
    try:
        import yaml as _yaml
        p = _profile_config_path()
        if p.exists():
            cfg = _yaml.safe_load(p.read_text(encoding='utf-8')) or {}
            return ((cfg.get('model') or {}).get('default') or '')
    except Exception:
        pass
    return ''


def _team_default_anchor_file() -> Path:
    """团队默认模型的独立锚点文件（存团队根 home，不被个人选择污染）。"""
    try:
        from api.profiles import _DEFAULT_HERMES_HOME
        return Path(_DEFAULT_HERMES_HOME) / '.team-default-model.json'
    except Exception:
        return _home() / '.team-default-model.json'


def _team_default_model() -> dict:
    """团队默认模型（回退目标）。

    ⚠️ 不能就地读根 config.yaml——admin 用根 home，切个人模型会覆盖它，
    再读就拿到被污染的值（循环依赖）。改用独立锚点文件：
    锚点存在就读锚点；不存在（首次）则从根 config 快照一次并落盘固化。
    """
    anchor = _team_default_anchor_file()
    saved = _read_json(anchor, None)
    if isinstance(saved, dict) and saved.get('default'):
        return {'default': saved['default'], 'provider': saved.get('provider')}
    # 首次：从根 config 快照团队默认，固化到锚点
    td = {'default': 'moonshotai/kimi-k3', 'provider': 'openrouter'}
    try:
        import yaml as _yaml
        from api.profiles import _DEFAULT_HERMES_HOME
        p = Path(_DEFAULT_HERMES_HOME) / 'config.yaml'
        if p.exists():
            cfg = _yaml.safe_load(p.read_text(encoding='utf-8')) or {}
            m = cfg.get('model') or {}
            if isinstance(m, dict) and m.get('default'):
                td = {'default': m.get('default'), 'provider': m.get('provider')}
    except Exception:
        pass
    try:
        _write_json(anchor, td)
    except Exception:
        pass
    return td


def set_chat_model(cid: str) -> dict:
    """把对话模型切到指定渠道（cid 为空 = 回到团队默认）。

    写当前用户 profile 的 config.yaml 的 model.default/provider，对话 agent 即生效。
    """
    try:
        import yaml as _yaml
    except ImportError:
        return {'error': 'yaml 不可用'}, 500
    p = _profile_config_path()
    cfg = {}
    if p.exists():
        try:
            cfg = _yaml.safe_load(p.read_text(encoding='utf-8')) or {}
        except Exception:
            cfg = {}
    is_root = _is_root_home()
    # 关键：切换前先固化团队默认锚点（幂等）。必须在污染根 config 之前调用，
    # 否则 admin 首次切个人模型后，锚点会快照到已污染的值。
    if is_root:
        _team_default_model()
    if not cid:
        # 回到团队默认：
        #  - 成员 profile（非根）：删 model 覆盖，继承团队 config
        #  - admin（根 home）：不能删（会破坏团队默认），显式写回团队默认模型
        if is_root:
            td = _team_default_model()
            ms = cfg.get('model') if isinstance(cfg.get('model'), dict) else {}
            ms['default'] = td['default']
            if td.get('provider'):
                ms['provider'] = td['provider']
            ms.pop('base_url', None)   # 团队默认不需要个人 base_url 覆盖
            cfg['model'] = ms
        else:
            cfg.pop('model', None)
        p.write_text(_yaml.dump(cfg, default_flow_style=False, allow_unicode=True, sort_keys=False), encoding='utf-8')
        # 记录选中态（空 = 团队默认），供下拉回显
        data0 = _read_json(_channels_file(), {'channels': [], 'active_id': None})
        data0['chat_channel_id'] = ''
        _write_json(_channels_file(), data0)
        return {'ok': True, 'current_model': '', 'label': '团队默认模型'}
    data = _read_json(_channels_file(), {'channels': [], 'active_id': None})
    chan = next((c for c in data.get('channels', []) if c.get('id') == cid), None)
    if not chan:
        return {'error': '渠道不存在'}, 404
    if not chan.get('enabled'):
        return {'error': '该渠道未启用'}, 400
    prov = PROVIDERS.get(chan.get('provider'), {})
    env_name = prov.get('env', '')
    if env_name and not _load_env().get(env_name):
        return {'error': '该渠道未配置 Key'}, 400
    model = chan.get('model') or (prov.get('models') or [''])[0]
    if not model:
        return {'error': '该渠道无可用模型'}, 400
    model_section = cfg.get('model') if isinstance(cfg.get('model'), dict) else {}
    model_section['default'] = model
    model_section['provider'] = _provider_runtime_id(chan.get('provider'))
    base = chan.get('base_url') or prov.get('base_url')
    if base:
        model_section['base_url'] = base
    else:
        model_section.pop('base_url', None)   # 无自定义端点时清掉残留 base_url
    cfg['model'] = model_section
    p.write_text(_yaml.dump(cfg, default_flow_style=False, allow_unicode=True, sort_keys=False), encoding='utf-8')
    # 记录选中的渠道 id，供下拉回显（比用 model 名反推可靠）
    data['chat_channel_id'] = cid
    _write_json(_channels_file(), data)
    return {'ok': True, 'current_model': model,
            'label': f"{chan.get('name') or chan.get('provider')} · {model}"}


# ══════════════════════════════════════════════════════════════════
#  设备 + 工作库登记
# ══════════════════════════════════════════════════════════════════
def _machine_id() -> str:
    import subprocess
    try:
        r = subprocess.run(['wmic', 'csproduct', 'get', 'uuid'],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            lines = [l.strip() for l in r.stdout.splitlines() if l.strip()]
            if len(lines) >= 2:
                return lines[1]
    except Exception:
        pass
    return os.environ.get('COMPUTERNAME', 'unknown')


def get_environment() -> dict:
    """P2 环境探测：返回当前机器环境状态 + 可用工作库。

    工作台每次启动调用，判断当前环境是否已登记设备。
    未登记设备 → 不能配工作库、对话不能选工作库。
    """
    data = _read_json(_devices_file(), {'devices': [], 'workspaces': []})
    cur = _machine_id()
    cur_dev = None
    for d in data.get('devices', []):
        if d.get('machine_id') == cur:
            cur_dev = d
            break
    # 当前设备下已登记的工作库（device_id 匹配当前设备，或未绑定设备的通用库）
    my_ws = []
    other_ws = []
    for w in data.get('workspaces', []):
        if cur_dev and (w.get('device_id') == cur_dev.get('id') or not w.get('device_id')):
            my_ws.append(w)
        else:
            other_ws.append(w)   # 其它设备/环境不一致的库 → 前端置灰展示
    return {
        'current_machine_id': cur,
        'registered': cur_dev is not None,
        'device': cur_dev,
        'workspaces': my_ws,          # 当前环境可用的工作库
        'other_workspaces': other_ws,  # 非当前环境的工作库（置灰不可选）
        'active_workspace': data.get('active_workspace'),  # 对话默认工作库 id
    }


def set_active_workspace(wid: str) -> dict:
    """设对话默认工作库（P2/C1：对话里选工作库）。"""
    data = _read_json(_devices_file(), {'devices': [], 'workspaces': []})
    if wid and not any(w.get('id') == wid for w in data.get('workspaces', [])):
        return {'error': '工作库不存在'}, 404
    data['active_workspace'] = wid
    _write_json(_devices_file(), data)
    return {'ok': True, 'active_workspace': wid}


def list_devices() -> dict:
    data = _read_json(_devices_file(), {'devices': [], 'workspaces': []})
    cur = _machine_id()
    for d in data.get('devices', []):
        d['is_current'] = (d.get('machine_id') == cur)
    return {'devices': data.get('devices', []), 'workspaces': data.get('workspaces', []),
            'current_machine_id': cur}


def register_device(body: dict) -> dict:
    name = (body.get('name') or '').strip() or '未命名设备'
    mid = _machine_id()
    data = _read_json(_devices_file(), {'devices': [], 'workspaces': []})
    devs = data.get('devices', [])
    for d in devs:
        if d.get('machine_id') == mid:
            d['name'] = name
            _write_json(_devices_file(), data)
            return {'ok': True, 'updated': True, 'machine_id': mid}
    devs.append({'id': 'dev-'+str(int(time.time()*1000)), 'name': name,
                 'machine_id': mid, 'registered_at': time.strftime('%Y-%m-%d %H:%M')})
    data['devices'] = devs
    _write_json(_devices_file(), data)
    return {'ok': True, 'machine_id': mid}


def remove_device(dev_id: str) -> dict:
    data = _read_json(_devices_file(), {'devices': [], 'workspaces': []})
    data['devices'] = [d for d in data.get('devices', []) if d.get('id') != dev_id]
    _write_json(_devices_file(), data)
    return {'ok': True}


def save_workspace_entry(body: dict) -> dict:
    wid = body.get('id')
    name = (body.get('name') or '').strip() or '未命名工作库'
    local_path = (body.get('local_path') or '').strip()
    device_id = body.get('device_id') or ''
    git_repo = (body.get('git_repo') or '').strip()
    if not local_path:
        return {'error': '本地路径必填'}, 400
    data = _read_json(_devices_file(), {'devices': [], 'workspaces': []})
    # P2 环境互锁：必须先登记当前设备，才能配工作库目录
    cur = _machine_id()
    cur_dev = next((d for d in data.get('devices', []) if d.get('machine_id') == cur), None)
    if not cur_dev:
        return {'error': '当前环境未登记设备，请先「登记当前设备」再配置工作库目录', 'need_register': True}, 409
    # 未指定 device_id 时默认绑当前设备
    if not device_id:
        device_id = cur_dev.get('id')
    wss = data.get('workspaces', [])
    if not wid:
        wid = 'ws-'+str(int(time.time()*1000))
        wss.append({'id': wid, 'name': name, 'local_path': local_path,
                    'device_id': device_id, 'git_repo': git_repo,
                    'created_at': time.strftime('%Y-%m-%d')})
    else:
        for w in wss:
            if w.get('id') == wid:
                w.update({'name': name, 'local_path': local_path,
                          'device_id': device_id, 'git_repo': git_repo})
                break
    data['workspaces'] = wss
    # 体验优化：登记后自动激活。若当前 active_workspace 为空，或指向的库已不存在，
    # 则把这个（通常是第一个）设为对话默认工作库——避免用户登记后还要手动"设为默认"，
    # 也让对话立即能识别到工作库（agent 读 active_workspace 定位工作目录）。
    cur_active = data.get('active_workspace')
    active_valid = cur_active and any(w.get('id') == cur_active for w in wss)
    if not active_valid:
        data['active_workspace'] = wid
    _write_json(_devices_file(), data)
    return {'ok': True, 'id': wid, 'active_workspace': data.get('active_workspace')}


def remove_workspace_entry(wid: str) -> dict:
    data = _read_json(_devices_file(), {'devices': [], 'workspaces': []})
    data['workspaces'] = [w for w in data.get('workspaces', []) if w.get('id') != wid]
    # 若删掉的正好是当前激活的工作库，自动切到剩下的第一个（避免 active 悬空 → 对话又识别不到）
    if data.get('active_workspace') == wid:
        data['active_workspace'] = data['workspaces'][0]['id'] if data['workspaces'] else None
    _write_json(_devices_file(), data)
    return {'ok': True, 'active_workspace': data.get('active_workspace')}
