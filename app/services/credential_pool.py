"""OS-vault credentials; rotation only happens when a request is dispatched."""
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
from app.services.redaction import redact

_lock = threading.Lock()
_positions = {}
_cache = {}

ASR_PROVIDERS = ('Groq', 'ElevenLabs', 'Gladia', 'Gemini')
ASR_ENV_VARS = {
    'Groq': 'GROQ_API_KEY',
    'ElevenLabs': 'ELEVENLABS_API_KEY',
    'Gladia': 'GLADIA_API_KEY',
    'Gemini': 'GEMINI_API_KEY',
}


def _health_path() -> Path:
    try:
        from app.services.app_paths import data_dir
        return data_dir() / 'asr_key_health.json'
    except Exception:
        return Path.home() / '.flowstudio_asr_key_health.json'


def _key_fp(key: str) -> str:
    return hashlib.sha256(str(key or '').strip().encode('utf-8')).hexdigest()[:16]


def _load_health() -> dict:
    path = _health_path()
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _save_health(data: dict) -> None:
    path = _health_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(path)
    except Exception:
        pass


def mark_key_status(service: str, account: str, key: str, ok: bool = True, reason: str = '') -> None:
    if not key:
        return
    fp = _key_fp(key)
    bucket_key = f'{service}:{account}'
    today = date.today().isoformat()
    with _lock:
        data = _load_health()
        bucket = data.get(bucket_key)
        if not isinstance(bucket, dict):
            bucket = {}
        if ok:
            bucket.pop(fp, None)
        else:
            bucket[fp] = {
                'ok': False,
                'reason': redact(str(reason or ''))[:200],
                'day': today,
                'updated_at': time.time(),
            }
        data[bucket_key] = bucket
        _save_health(data)


def reset_account_status(service: str, account: str) -> None:
    bucket_key = f'{service}:{account}'
    with _lock:
        data = _load_health()
        if bucket_key in data:
            data.pop(bucket_key, None)
            _save_health(data)


def is_key_available(service: str, account: str, key: str, health_data: dict | None = None) -> bool:
    if not key:
        return False
    data = health_data if isinstance(health_data, dict) else _load_health()
    bucket = data.get(f'{service}:{account}')
    if not isinstance(bucket, dict):
        return True
    entry = bucket.get(_key_fp(key))
    if not isinstance(entry, dict):
        return True
    if entry.get('ok', True):
        return True
    # Daily quota / rate limits reset automatically on a new day
    if entry.get('day') != date.today().isoformat():
        return True
    return False



def backend():
    if sys.platform == 'win32':
        from keyring.backends.Windows import WinVaultKeyring as Keyring
    elif sys.platform == 'darwin':
        from keyring.backends.macOS import Keyring
    else:
        from keyring.backends.SecretService import Keyring
    return Keyring()


def normalize(text):
    keys = list(dict.fromkeys(line.strip() for line in str(text or '').splitlines() if line.strip()))
    if not keys or len(keys) > 50:
        raise ValueError('请输入 1–50 个密钥，每行一个。')
    if any(any(c.isspace() for c in key) for key in keys):
        raise ValueError('密钥中不能包含空格。')
    return keys


def read(service, account, vault=None):
    cache_key = (service, account)
    if vault is None:
        with _lock:
            if cache_key in _cache:
                return list(_cache[cache_key])
    v = vault or backend()
    raw = v.get_password(service, account + ':pool')
    if raw:
        names = json.loads(raw)
        result = [key for name in names if (key := v.get_password(service, name))]
    else:
        legacy = v.get_password(service, account)
        result = [legacy] if legacy else []
    if vault is None:
        with _lock:
            _cache[cache_key] = list(result)
    return result


def save(service, account, text, vault=None, reset_status: bool = True):
    import uuid
    v = vault or backend()
    keys = normalize(text)
    # One credential per entry avoids Windows vault size limits on bulk imports.
    old = json.loads(v.get_password(service, account + ':pool') or '[]')
    names = []
    try:
        for key in keys:
            name = account + ':' + uuid.uuid4().hex
            v.set_password(service, name, key)
            names.append(name)
        v.set_password(service, account + ':pool', json.dumps(names))
    except Exception:
        for name in names:
            try: v.delete_password(service, name)
            except Exception: pass
        raise
    for name in old + [account]:
        try:
            if v.get_password(service, name) is not None: v.delete_password(service, name)
        except Exception: pass
    if vault is None:
        with _lock:
            _cache[(service, account)] = list(keys)
    if reset_status:
        reset_account_status(service, account)
    return len(keys)


def append_keys(service, account, text, vault=None):
    """Append 1 or more keys to the existing pool (deduplicating while preserving order)."""
    new_keys = normalize(text)
    try:
        existing = list(read(service, account, vault=vault) or [])
    except Exception:
        existing = []
    merged = list(dict.fromkeys(existing + new_keys))
    if len(merged) > 50:
        raise ValueError(f'合并后超过 50 个密钥上限（当前已有 {len(existing)} 个，本次新增 {len(new_keys)} 个）。')
    return save(service, account, '\n'.join(merged), vault=vault, reset_status=False)


def remove_key(service, account, target_key: str, vault=None) -> int:
    """Remove a single key from the pool; clears the pool if it was the last key."""
    target = str(target_key or '').strip()
    existing = [k for k in (read(service, account, vault=vault) or []) if k != target]
    if not existing:
        clear(service, account, vault=vault)
        return 0
    return save(service, account, '\n'.join(existing), vault=vault, reset_status=False)


def mask_key(key: str) -> str:
    s = str(key or '').strip()
    if len(s) <= 10:
        return s[:2] + '••••' + s[-2:] if len(s) >= 4 else '••••••'
    return f'{s[:6]}••••••••{s[-4:]}'


def clear(service, account, vault=None):
    v = vault or backend()
    names = json.loads(v.get_password(service, account + ':pool') or '[]')
    for name in names + [account, account + ':pool']:
        if v.get_password(service, name) is not None: v.delete_password(service, name)
    if vault is None:
        with _lock:
            _cache[(service, account)] = []
    reset_account_status(service, account)


def next_key(service, account, keys):
    if not keys: return ''
    with _lock:
        identity = (service, account)
        position = _positions.get(identity, 0)
        _positions[identity] = position + 1
        return keys[position % len(keys)]


def read_with_env(service: str, account: str) -> list[str]:
    try:
        keys = list(read(service, account) or [])
    except Exception:
        keys = []
    if service == 'com.flowstudio.asr':
        env_name = ASR_ENV_VARS.get(account, '')
        env_val = os.environ.get(env_name, '').strip() if env_name else ''
        if env_val and env_val not in keys:
            keys.append(env_val)
    return keys


def pool_counts(service: str, account: str) -> tuple[int, int]:
    """Return (available_count, total_count) for the specified service/account."""
    keys = read_with_env(service, account)
    total = len(keys)
    if total == 0:
        return 0, 0
    health = _load_health()
    avail = sum(1 for k in keys if is_key_available(service, account, k, health))
    return avail, total


def candidate_keys(service: str, account: str) -> list[str]:
    """Return keys rotated from the current round-robin index, prioritizing available keys."""
    keys = read_with_env(service, account)
    if not keys:
        return []
    with _lock:
        identity = (service, account)
        pos = _positions.get(identity, 0)
        _positions[identity] = pos + 1
    rotated = [keys[(pos + i) % len(keys)] for i in range(len(keys))]
    health = _load_health()
    avail = [k for k in rotated if is_key_available(service, account, k, health)]
    unavail = [k for k in rotated if not is_key_available(service, account, k, health)]
    return avail + unavail

