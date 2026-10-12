"""OS-vault credentials; rotation only happens when a request is dispatched."""
import json
import sys
import threading

_lock = threading.Lock()
_positions = {}


def backend():
    if sys.platform == 'win32':
        from keyring.backends.Windows import WinVaultKeyring as Keyring
    elif sys.platform == 'darwin':
        from keyring.backends.macOS import Keyring
    else:
        from keyring.backends.SecretService import Keyring
    return Keyring()


def normalize(text):
    keys = list(dict.fromkeys(line.strip() for line in text.splitlines() if line.strip()))
    if not keys or len(keys) > 20:
        raise ValueError('请输入 1–20 个密钥，每行一个。')
    if any(any(c.isspace() for c in key) for key in keys):
        raise ValueError('密钥中不能包含空格。')
    return keys


def read(service, account, vault=None):
    vault = vault or backend()
    raw = vault.get_password(service, account + ':pool')
    if raw:
        names = json.loads(raw)
        return [key for name in names if (key := vault.get_password(service, name))]
    legacy = vault.get_password(service, account)
    return [legacy] if legacy else []


def save(service, account, text, vault=None):
    import uuid
    vault = vault or backend()
    keys = normalize(text)
    # One credential per entry avoids Windows vault size limits on bulk imports.
    old = json.loads(vault.get_password(service, account + ':pool') or '[]')
    names = []
    try:
        for key in keys:
            name = account + ':' + uuid.uuid4().hex
            vault.set_password(service, name, key)
            names.append(name)
        vault.set_password(service, account + ':pool', json.dumps(names))
    except Exception:
        for name in names:
            try: vault.delete_password(service, name)
            except Exception: pass
        raise
    for name in old + [account]:
        try:
            if vault.get_password(service, name) is not None: vault.delete_password(service, name)
        except Exception: pass
    return len(keys)


def clear(service, account, vault=None):
    vault = vault or backend()
    names = json.loads(vault.get_password(service, account + ':pool') or '[]')
    for name in names + [account, account + ':pool']:
        if vault.get_password(service, name) is not None: vault.delete_password(service, name)


def next_key(service, account, keys):
    if not keys: return ''
    with _lock:
        identity = (service, account)
        position = _positions.get(identity, 0)
        _positions[identity] = position + 1
        return keys[position % len(keys)]
