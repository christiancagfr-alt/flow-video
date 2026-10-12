"""Store Google OAuth refresh credentials in the OS credential store.

Windows keeps a DPAPI blob in the token file. macOS and Linux write the
secret to the system keyring and replace the local file with a pointer only
after a successful read-back. A locked or missing credential store raises
CredentialStoreError and does not write plaintext.
"""
import base64
import json
import os
from pathlib import Path

SERVICE = "com.flowstudio.google-oauth"


class CredentialStoreError(RuntimeError):
    """The system credential store refused the token. Plaintext was not written."""


def _account(path):
    return "google-oauth:" + Path(path).name


def _atomic_write(path, text):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    if os.name != "nt":
        os.chmod(temporary, 0o600)
    temporary.replace(path)


def _dpapi_wrap(text):
    import win32crypt
    encrypted = win32crypt.CryptProtectData(
        text.encode("utf-8"), "Flow Studio Google OAuth", None, None, None, 1)
    return json.dumps({"windows_dpapi": base64.b64encode(encrypted).decode("ascii")})


def _vault_or_raise():
    try:
        from app.services.credential_pool import backend
        return backend()
    except CredentialStoreError:
        raise
    except Exception as exc:
        raise CredentialStoreError(
            "系统凭据库不可用，已拒绝明文保存 Google 登录令牌。"
            "请解锁系统钥匙串后重试（macOS 钥匙串，或 Linux Secret Service / gnome-keyring）。"
        ) from exc


def _save_keyring(path, text, vault):
    account = _account(path)
    try:
        vault.set_password(SERVICE, account, text)
        stored = vault.get_password(SERVICE, account)
    except CredentialStoreError:
        raise
    except Exception as exc:
        raise CredentialStoreError(
            "系统凭据库写入失败，已保留原有本地令牌文件，未回退到明文保存。"
        ) from exc
    if stored != text:
        raise CredentialStoreError("系统凭据库回读校验失败，未替换本地令牌文件。")
    pointer = json.dumps(
        {"keyring": {"service": SERVICE, "account": account}}, ensure_ascii=False)
    _atomic_write(path, pointer)


def save(path, text, vault="auto"):
    path = Path(path)
    if vault == "auto" and os.name == "nt":
        _atomic_write(path, _dpapi_wrap(text))
        return
    if vault == "auto":
        vault = _vault_or_raise()
    if vault is None:
        raise CredentialStoreError("系统凭据库不可用，已拒绝明文保存 Google 登录令牌。")
    _save_keyring(path, text, vault)


def _read_keyring(pointer, vault):
    info = pointer.get("keyring") or {}
    service = info.get("service") or SERVICE
    account = info.get("account")
    if service != SERVICE or not account:
        raise CredentialStoreError("本地令牌指针无效，请重新授权。")
    if vault == "auto":
        vault = _vault_or_raise()
    try:
        stored = vault.get_password(service, account)
    except CredentialStoreError:
        raise
    except Exception as exc:
        raise CredentialStoreError("系统凭据库读取失败，本地令牌文件未改动。") from exc
    if not stored:
        raise CredentialStoreError("系统凭据库中找不到 Google 登录令牌，本地指针未改动。请重新授权。")
    return json.loads(stored)


def load(path, vault="auto"):
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "windows_dpapi" in data:
        if os.name != "nt":
            raise ValueError("Windows credentials must be reauthorized on this platform")
        import win32crypt
        blob = base64.b64decode(data["windows_dpapi"])
        return json.loads(win32crypt.CryptUnprotectData(blob, None, None, None, 1)[1].decode("utf-8"))
    if isinstance(data, dict) and "keyring" in data:
        return _read_keyring(data, vault)
    text = json.dumps(data, ensure_ascii=False)
    # Legacy plaintext. Persist to the secure store first; save() replaces the
    # file only after the credential store reads the same value back.
    save(path, text, vault=vault)
    return data


def _delete_keyring(service, account, vault):
    if vault == "auto":
        vault = _vault_or_raise()
    try:
        if vault.get_password(service, account) is not None:
            vault.delete_password(service, account)
    except CredentialStoreError:
        raise
    except Exception as exc:
        raise CredentialStoreError("系统凭据库无法删除 Google 登录令牌，本地文件未删除。") from exc


def delete(path, vault="auto"):
    path = Path(path)
    account = _account(path)
    service = SERVICE
    remove_vault = not (vault == "auto" and os.name == "nt")
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = None
        if isinstance(data, dict) and isinstance(data.get("keyring"), dict):
            service = data["keyring"].get("service") or SERVICE
            account = data["keyring"].get("account") or account
            remove_vault = True
        elif isinstance(data, dict) and "windows_dpapi" in data:
            remove_vault = vault != "auto"
        if remove_vault:
            _delete_keyring(service, account, vault)
        path.unlink()
        return
    if remove_vault:
        _delete_keyring(service, account, vault)
