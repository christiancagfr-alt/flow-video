"""Shared persona instructions and fully editable persistent preset libraries.

TALKING and PRAYING deliberately use independent preset namespaces. Existing
host_persona keys remain backward compatible. A legacy shared library is used only
as the one-time fallback source until each mode is saved independently.
"""
from __future__ import annotations

import copy
import json
import uuid

# Legacy exports are intentionally retained for older code/tests.
CAMERA_DEFINITIONS = (
    '固定中近景','缓慢推进','左侧 + Hard Cut','轻微右环绕','固定近景','缓慢拉远',
    '右侧 + 特写切换','轻微左环绕','推进 + Hard Cut','固定中景','轻微跟拍','左侧近景'
)
CAMERA_POOLS = {
    '稳定': tuple(CAMERA_DEFINITIONS[i] for i in (0,4,9)),
    '自然变化': tuple(CAMERA_DEFINITIONS[i] for i in (0,1,2,3,4,5,7,9,11)),
    '丰富变化': CAMERA_DEFINITIONS,
}
PERFORMANCE = dict(zip(('自然','亲和温柔','开心','严肃','慷慨激昂','感动','哭泣'), (
    '人物保持自然真实的交流状态，表情和动作不刻意表演。',
    '人物神态亲和温柔，语气柔和，表情真实而有温度。',
    '人物自然流露喜悦，笑容和语气轻快，避免夸张假笑。',
    '人物表情认真严肃，语气沉稳清晰，避免僵硬。',
    '人物充满坚定热情，声音有力量，情绪自然且不舞台化。',
    '人物真诚动容，通过眼神、呼吸和细微表情表达感受。',
    '人物自然哽咽、眼眶湿润或少量流泪，仍完整清晰说完文案，避免假哭。')))
ACTIONS = dict(zip(('原地','自然手势','可走动','动作克制','大幅手势'), (
    '人物始终留在原地，不走动。','手势自然配合文案，手部与道具保持合理连续。',
    '当本片段采用走动时，人物必须真正离开原始站位，连续向自然方向走动约2—3步或等价位移，空间位置明显变化；边走边说，合理绕开障碍物，禁止原地踏步、来回乱走、突然变向或穿模。','人物动作轻微克制，避免大幅摆动。',
    '人物以幅度较大的自然手势表达情绪，避免肢体与道具穿帮。')))

LEGACY_PRESET_LIBRARY_KEY = 'persona_preset_library_v1'
# Kept for source compatibility with older modules/tests. New writes use mode keys below.
PRESET_LIBRARY_KEY = LEGACY_PRESET_LIBRARY_KEY
PRESET_LIBRARY_KEYS = {
    'TALKING': 'persona_preset_library_talking_v2',
    'PRAYING': 'persona_preset_library_praying_v2',
}
PRESET_LIBRARY_DEFAULT_KEYS = {
    'TALKING': 'persona_preset_library_default_talking_v1',
    'PRAYING': 'persona_preset_library_default_praying_v1',
}
PERSONA_DEFAULT_KEYS = {
    'TALKING': 'persona_default_talking_v1',
    'PRAYING': 'persona_default_praying_v1',
}

def _mode_name(mode='TALKING'):
    return 'PRAYING' if str(mode or '').upper() == 'PRAYING' else 'TALKING'



def _item(item_id, name, prompt, aliases=None):
    return {'id': item_id, 'name': name, 'prompt': prompt, 'aliases': list(aliases or [])}


def _default_library():
    shots = [
        _item(f'cam_{i+1:02d}', name, name)
        for i, name in enumerate(CAMERA_DEFINITIONS)
    ]
    shot_ids = {x['name']: x['id'] for x in shots}
    return {
        'version': 1,
        'performance': [
            _item(f'perf_{i+1:02d}', name, prompt)
            for i, (name, prompt) in enumerate(PERFORMANCE.items())
        ],
        'actions': [
            _item(f'action_{i+1:02d}', name, prompt)
            for i, (name, prompt) in enumerate(ACTIONS.items())
        ],
        'camera_shots': shots,
        'camera_strategies': [
            {'id': 'strategy_stable', 'name': '稳定',
             'shot_ids': [shot_ids[n] for n in CAMERA_POOLS['稳定']], 'prompt': '', 'aliases': []},
            {'id': 'strategy_natural', 'name': '自然变化',
             'shot_ids': [shot_ids[n] for n in CAMERA_POOLS['自然变化']],
             'prompt': '优先根据人物动作匹配镜头，不为变化而变化；每段只选1种主运镜，必要时最多1次 hard cut。',
             'aliases': []},
            {'id': 'strategy_rich', 'name': '丰富变化',
             'shot_ids': [shot_ids[n] for n in CAMERA_POOLS['丰富变化']], 'prompt': '', 'aliases': []},
        ],
    }


DEFAULT_PRESET_LIBRARY = _default_library()


def _default_strategy_prompt(item_id, name):
    """Compatibility default for strategy-level GPT rules."""
    if str(item_id or '') == 'strategy_natural' or str(name or '').strip() == '自然变化':
        return '优先根据人物动作匹配镜头，不为变化而变化；每段只选1种主运镜，必要时最多1次 hard cut。'
    return ''


def _clean_item(raw, fallback_id):
    if not isinstance(raw, dict):
        return None
    name = str(raw.get('name') or '').strip()
    if not name:
        return None
    return {
        'id': str(raw.get('id') or fallback_id),
        'name': name,
        'prompt': str(raw.get('prompt') or name).strip() or name,
        'aliases': [str(x).strip() for x in (raw.get('aliases') or []) if str(x).strip() and str(x).strip() != name],
    }


def normalize_library(raw=None):
    """Return a safe, editable library while preserving user order and stable IDs."""
    base = copy.deepcopy(DEFAULT_PRESET_LIBRARY)
    if not isinstance(raw, dict):
        return base

    out = {'version': 1}
    for section in ('performance', 'actions', 'camera_shots'):
        items = []
        for i, item in enumerate(raw.get(section) or []):
            clean = _clean_item(item, f'{section}_{i+1}_{uuid.uuid4().hex[:8]}')
            if clean:
                items.append(clean)
        out[section] = items or copy.deepcopy(base[section])

    shot_ids = {x['id'] for x in out['camera_shots']}
    strategies = []
    for i, item in enumerate(raw.get('camera_strategies') or []):
        if not isinstance(item, dict):
            continue
        name = str(item.get('name') or '').strip()
        if not name:
            continue
        ids = [str(x) for x in (item.get('shot_ids') or []) if str(x) in shot_ids]
        if not ids:
            continue
        strategy_id = str(item.get('id') or f'strategy_{i+1}_{uuid.uuid4().hex[:8]}')
        prompt = item.get('prompt')
        if prompt is None:
            prompt = _default_strategy_prompt(strategy_id, name)
        strategies.append({
            'id': strategy_id,
            'name': name,
            'shot_ids': ids,
            'prompt': str(prompt or '').strip(),
            'aliases': [str(x).strip() for x in (item.get('aliases') or []) if str(x).strip() and str(x).strip() != name],
        })
    if strategies:
        out['camera_strategies'] = strategies
    else:
        current_ids = [x['id'] for x in out['camera_shots']]
        out['camera_strategies'] = [{
            'id': 'strategy_natural',
            'name': '自然变化',
            'shot_ids': current_ids,
            'prompt': _default_strategy_prompt('strategy_natural', '自然变化'),
            'aliases': [],
        }]
    return out


def load_preset_library(mode='TALKING'):
    """Load one mode's independent preset library.

    Compatibility: if that mode has never been saved, the old shared v1 library is
    read as a fallback snapshot. Saving either mode never mutates the other mode.
    """
    mode = _mode_name(mode)
    try:
        from . import repository as repo
        raw = repo.get_setting(PRESET_LIBRARY_KEYS[mode], '')
        if raw:
            return normalize_library(json.loads(raw))
        legacy = repo.get_setting(LEGACY_PRESET_LIBRARY_KEY, '')
        return normalize_library(json.loads(legacy) if legacy else None)
    except Exception:
        return normalize_library(None)


def _id_name_map(library, section):
    return {x['id']: x['name'] for x in library.get(section, [])}


def _rename_map(old, new, section):
    old_by_id = _id_name_map(old, section)
    new_by_id = _id_name_map(new, section)
    return {old_name: new_by_id[item_id] for item_id, old_name in old_by_id.items() if item_id in new_by_id}


def _migrate_saved_personas(old, new, mode='TALKING'):
    """Migrate only saved personas belonging to the edited mode namespace."""
    mode = _mode_name(mode)
    try:
        from . import repository as repo
        rename = {s: _rename_map(old, new, s) for s in
                  ('performance', 'actions', 'camera_shots', 'camera_strategies')}
        old_names = {s: set(_id_name_map(old, s).values()) for s in rename}
        new_names = {s: set(_id_name_map(new, s).values()) for s in rename}
        defaults = {
            'style': new['performance'][0]['name'],
            'action': new['actions'][0]['name'],
            'strategy': next((x['name'] for x in new['camera_strategies'] if x['name'] == '自然变化'),
                             new['camera_strategies'][0]['name']),
            'shot': new['camera_shots'][0]['name'],
        }
        with repo.connect() as con:
            rows = con.execute(
                "SELECT key,value FROM app_settings WHERE key LIKE 'host_persona_%' OR key=?",
                (PERSONA_DEFAULT_KEYS[mode],)
            ).fetchall()
            suffix = '_' + mode.lower()
            for row in rows:
                row_key = str(row['key'] or '')
                if row_key != PERSONA_DEFAULT_KEYS[mode] and not row_key.endswith(suffix):
                    continue
                try:
                    d = json.loads(row['value'] or '{}')
                except Exception:
                    continue
                if not isinstance(d, dict):
                    continue

                style = str(d.get('style') or '')
                if style != '自定义':
                    if style in rename['performance']:
                        d['style'] = rename['performance'][style]
                    elif style in old_names['performance'] and style not in new_names['performance']:
                        d['style'] = defaults['style']

                pp = {}
                for k, v in dict(d.get('performance_prompts') or {}).items():
                    nk = rename['performance'].get(k, k)
                    if nk in new_names['performance']:
                        pp[nk] = v
                d['performance_prompts'] = pp

                moves = []
                for x in list(d.get('moves') or []):
                    if x == '自定义':
                        moves.append(x); continue
                    nx = rename['actions'].get(x, x)
                    if nx in new_names['actions'] and nx not in moves:
                        moves.append(nx)
                d['moves'] = moves or [defaults['action']]

                ap = {}
                for k, v in dict(d.get('action_prompts') or {}).items():
                    nk = rename['actions'].get(k, k)
                    if nk in new_names['actions']:
                        ap[nk] = v
                d['action_prompts'] = ap

                cam = str(d.get('camera') or '')
                if cam != '自定义':
                    if cam in rename['camera_strategies']:
                        d['camera'] = rename['camera_strategies'][cam]
                    elif cam in old_names['camera_strategies'] and cam not in new_names['camera_strategies']:
                        d['camera'] = defaults['strategy']

                pool = []
                for x in list(d.get('custom_camera_pool') or []):
                    nx = rename['camera_shots'].get(x, x)
                    if nx in new_names['camera_shots'] and nx not in pool:
                        pool.append(nx)
                if d.get('camera') == '自定义' and not pool:
                    pool = [defaults['shot']]
                d['custom_camera_pool'] = pool

                d.pop('voice', None)

                con.execute("UPDATE app_settings SET value=? WHERE key=?",
                            (json.dumps(d, ensure_ascii=False), row['key']))
    except Exception:
        # A preset-library edit must never make the whole application unusable.
        # Runtime normalization still provides backward compatibility.
        return


def save_preset_library(library, mode='TALKING'):
    """Persist exactly one mode library and migrate only that mode's host selections."""
    from . import repository as repo
    mode = _mode_name(mode)
    old = load_preset_library(mode)
    clean = normalize_library(library)
    _migrate_saved_personas(old, clean, mode)
    repo.set_setting(PRESET_LIBRARY_KEYS[mode], json.dumps(clean, ensure_ascii=False))
    return clean


def save_preset_library_default(library, mode='TALKING'):
    """Save a user-owned restore point for one mode's entire preset library.

    This is intentionally separate from the active preset library and from the
    per-host/persona default combination. It acts as a backup baseline for the
    preset-library editor's “restore default library” action.
    """
    from . import repository as repo
    mode = _mode_name(mode)
    clean = normalize_library(library)
    repo.set_setting(PRESET_LIBRARY_DEFAULT_KEYS[mode], json.dumps(clean, ensure_ascii=False))
    return clean


def load_preset_library_default(mode='TALKING'):
    """Load the saved library restore point, falling back to factory defaults."""
    mode = _mode_name(mode)
    try:
        from . import repository as repo
        raw = repo.get_setting(PRESET_LIBRARY_DEFAULT_KEYS[mode], '')
        if raw:
            return normalize_library(json.loads(raw))
    except Exception:
        pass
    return normalize_library(copy.deepcopy(DEFAULT_PRESET_LIBRARY))


def _section_index(library, section):
    return {item['name']: item for item in library.get(section, [])}


def _find_item(library, section, value):
    text = str(value or '').strip()
    for item in library.get(section, []):
        if text == item['name'] or text in item.get('aliases', []):
            return item
    return None


def _canonical_name(library, section, value):
    item = _find_item(library, section, value)
    return item['name'] if item else str(value or '').strip()


def preset_names(section, library=None, mode='TALKING'):
    lib = normalize_library(library) if library is not None else load_preset_library(mode)
    return [x['name'] for x in lib.get(section, [])]


def preset_prompt(section, name, library=None, default='', mode='TALKING'):
    lib = normalize_library(library) if library is not None else load_preset_library(mode)
    item = _find_item(lib, section, name)
    return item['prompt'] if item else (default or str(name or ''))


def _load_saved_default_raw(mode='TALKING'):
    """Load the user's saved default combination without recursively normalizing it."""
    mode = _mode_name(mode)
    try:
        from . import repository as repo
        raw = repo.get_setting(PERSONA_DEFAULT_KEYS[mode], '')
        value = json.loads(raw) if raw else {}
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def save_persona_default(data, mode='TALKING', library=None):
    """Persist the complete current combination as the default for one mode only."""
    from . import repository as repo
    mode = _mode_name(mode)
    lib = normalize_library(library) if library is not None else load_preset_library(mode)
    clean = normalize(data, mode, lib, apply_saved_default=False)
    repo.set_setting(PERSONA_DEFAULT_KEYS[mode], json.dumps(clean, ensure_ascii=False))
    return clean


def load_persona_default(mode='TALKING', library=None):
    mode = _mode_name(mode)
    lib = normalize_library(library) if library is not None else load_preset_library(mode)
    raw = _load_saved_default_raw(mode)
    return normalize(raw, mode, lib, apply_saved_default=False)


def normalize(data, mode='TALKING', library=None, apply_saved_default=True):
    mode = _mode_name(mode)
    lib = normalize_library(library) if library is not None else load_preset_library(mode)
    incoming = dict(data) if isinstance(data, dict) else {}
    d = {}
    if apply_saved_default and not incoming:
        saved_default = _load_saved_default_raw(mode)
        if saved_default:
            d.update(saved_default)
    # Explicit incoming values always win over the mode default.
    for key, value in incoming.items():
        if key in ('performance_prompts', 'action_prompts') and isinstance(value, dict) and isinstance(d.get(key), dict):
            merged = dict(d.get(key) or {})
            merged.update(value)
            d[key] = merged
        else:
            d[key] = value

    default_style = lib['performance'][0]['name']
    raw_style = d.get('style', default_style)
    if str(raw_style) == '自定义':
        d['style'] = '自定义'
    else:
        found = _find_item(lib, 'performance', raw_style)
        if found:
            d['style'] = found['name']
        else:
            d.setdefault('performance_custom', str(raw_style or ''))
            d['style'] = '自定义'

    default_moves = ['原地','自然手势'] if mode == 'TALKING' else ['原地','动作克制']
    if 'moves' not in d:
        available = set(preset_names('actions', lib))
        d['moves'] = [x for x in default_moves if x in available]
        if not d['moves'] and lib['actions']:
            d['moves'] = [lib['actions'][0]['name']]
    else:
        moves = []
        for value in (d.get('moves') or []):
            if str(value) == '自定义':
                moves.append('自定义')
                continue
            found = _find_item(lib, 'actions', value)
            if found and found['name'] not in moves:
                moves.append(found['name'])
        d['moves'] = moves

    default_strategy = next((x['name'] for x in lib['camera_strategies'] if x['name'] == '自然变化'),
                            lib['camera_strategies'][0]['name'])
    raw_camera = d.get('camera', default_strategy)
    if str(raw_camera) == '自定义':
        d['camera'] = '自定义'
    else:
        found = _find_item(lib, 'camera_strategies', raw_camera)
        d['camera'] = found['name'] if found else default_strategy

    # Voice presets were intentionally removed from persona settings.
    d.pop('voice', None)

    d.setdefault('custom', '')
    d.setdefault('performance_custom', '')
    d.setdefault('action_custom', '')
    # V0.13.5.97: selected action buttons are an allowed candidate pool by default.
    # GPT inspects the reference image once in the same prompt-generation request
    # and chooses only the safe/appropriate subset. Existing saved persona JSONs
    # remain compatible because a missing key defaults to the new automatic mode.
    d['auto_action_match'] = bool(d.get('auto_action_match', True))
    d.setdefault('performance_prompts', {})
    d.setdefault('action_prompts', {})

    # Canonicalize per-host override keys after a global rename.
    perf_prompts = {}
    for key, value in dict(d.get('performance_prompts') or {}).items():
        item = _find_item(lib, 'performance', key)
        if item:
            perf_prompts[item['name']] = value
    d['performance_prompts'] = perf_prompts
    action_prompts = {}
    for key, value in dict(d.get('action_prompts') or {}).items():
        item = _find_item(lib, 'actions', key)
        if item:
            action_prompts[item['name']] = value
    d['action_prompts'] = action_prompts

    pool = []
    for value in (d.get('custom_camera_pool') or []):
        found = _find_item(lib, 'camera_shots', value)
        if found and found['name'] not in pool:
            pool.append(found['name'])
    d['custom_camera_pool'] = pool
    return d


def active_camera_pool(data, library=None, mode='TALKING'):
    """Return display names of currently allowed camera shots for one mode."""
    mode = _mode_name(mode)
    lib = normalize_library(library) if library is not None else load_preset_library(mode)
    d = normalize(data, mode, lib)
    strategy = d.get('camera')
    if strategy == '自定义':
        return [x for x in d.get('custom_camera_pool', []) if _find_item(lib, 'camera_shots', x)]
    item = _find_item(lib, 'camera_strategies', strategy)
    if not item:
        return []
    shot_by_id = {x['id']: x for x in lib['camera_shots']}
    return [shot_by_id[sid]['name'] for sid in item.get('shot_ids', []) if sid in shot_by_id]


def active_camera_instructions(data, library=None, mode='TALKING'):
    mode = _mode_name(mode)
    lib = normalize_library(library) if library is not None else load_preset_library(mode)
    return [preset_prompt('camera_shots', name, lib, name) for name in active_camera_pool(data, lib, mode)]


def active_camera_catalog(data, library=None, mode='TALKING'):
    mode = _mode_name(mode)
    lib = normalize_library(library) if library is not None else load_preset_library(mode)
    d = normalize(data, mode, lib)
    strategy = d.get('camera')
    
    shot_by_id = {x['id']: x for x in lib['camera_shots']}
    shot_by_name = {x['name']: x for x in lib['camera_shots']}
    
    out = []
    if strategy == '自定义':
        names = [x for x in d.get('custom_camera_pool', []) if _find_item(lib, 'camera_shots', x)]
        for name in names:
            item = shot_by_name.get(name)
            if item:
                out.append({'id': item['id'], 'name': item['name'], 'prompt': preset_prompt('camera_shots', name, lib, name)})
        return out
        
    item = _find_item(lib, 'camera_strategies', strategy)
    if not item: return []
    for sid in item.get('shot_ids', []):
        if sid in shot_by_id:
            out.append({'id': sid, 'name': shot_by_id[sid]['name'], 'prompt': preset_prompt('camera_shots', shot_by_id[sid]['name'], lib, shot_by_id[sid]['name'])})
    return out

def active_action_presets(data, library=None, mode='TALKING'):
    """Return the currently selected action presets as a stable candidate catalog.

    The catalog preserves global preset IDs while applying per-host prompt overrides.
    In automatic mode GPT may choose only from this catalog (or the internal safe
    fallback), so user-authored preset wording stays deterministic.
    """
    mode = _mode_name(mode)
    lib = normalize_library(library) if library is not None else load_preset_library(mode)
    d = normalize(data, mode, lib)
    out = []
    for name in d.get('moves', []):
        if name == '自定义':
            prompt = str(d.get('action_custom') or '').strip()
            if prompt:
                out.append({'id': 'custom', 'name': '自定义', 'prompt': prompt})
            continue
        item = _find_item(lib, 'actions', name)
        if not item:
            continue
        prompt = str(d.get('action_prompts', {}).get(
            item['name'], preset_prompt('actions', item['name'], lib, ACTIONS.get(item['name'], item['name']))
        ) or '').strip()
        if prompt:
            out.append({'id': str(item['id']), 'name': str(item['name']), 'prompt': prompt})
    return out


def active_camera_strategy_prompt(data, library=None, mode='TALKING'):
    """Return the selected strategy's editable internal GPT rule."""
    mode = _mode_name(mode)
    lib = normalize_library(library) if library is not None else load_preset_library(mode)
    d = normalize(data, mode, lib)
    if d.get('camera') == '自定义':
        return ''
    item = _find_item(lib, 'camera_strategies', d.get('camera'))
    return str((item or {}).get('prompt') or '').strip()


def rule_text(data, mode='TALKING', library=None):
    mode = _mode_name(mode)
    lib = normalize_library(library) if library is not None else load_preset_library(mode)
    d = normalize(data, mode, lib)
    pool_names = active_camera_pool(d, lib, mode)
    pool_prompts = active_camera_instructions(d, lib, mode)
    if not pool_names:
        raise ValueError('请至少选择一种镜头方式')

    style = d['style']
    if style == '自定义':
        performance = d.get('performance_custom', '')
    else:
        performance = d['performance_prompts'].get(
            style, preset_prompt('performance', style, lib, PERFORMANCE.get(style, style))
        )

    action_catalog = active_action_presets(d, lib, mode)
    auto_action_match = bool(d.get('auto_action_match', True))
    if auto_action_match:
        # Do not serialize every candidate prompt as a simultaneous hard rule. The
        # full candidate catalog is supplied separately to GPT and Studio locally
        # appends only the preset(s) actually selected for this reference image.
        action_rule = '人物动作选择模式：根据参考图自动匹配；人物动作候选预设：' + (
            '、'.join(x['name'] for x in action_catalog) if action_catalog else '无'
        )
    else:
        action_rule = '人物动作：' + '；'.join(x['prompt'] for x in action_catalog)

    strategy_prompt = active_camera_strategy_prompt(d, lib, mode)
    strategy_text = '镜头调度策略：' + d['camera']
    if strategy_prompt:
        strategy_text += '；策略内部规则：' + strategy_prompt

    parts = [
        '表演要求：' + performance,
        action_rule,
        strategy_text,
        # 允许镜头池现在通过结构化 JSON 发送给模型以节约 Token
        '本批次必须从给定的镜头池(camera_catalog)中结合人物、文案和参考图片自然选择，并在结果中只输出其ID。此镜头限制覆盖基础模板及核心默认摄影组合。'
    ]
    if d.get('custom'):
        parts.append('人物自定义要求：' + d['custom'])
    return '；'.join(parts)
