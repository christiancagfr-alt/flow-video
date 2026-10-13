
from __future__ import annotations
from pathlib import Path
import json
from app.services import quiet_process as subprocess
import os
import re
import sqlite3
import sys

CHROME_APP = "/Applications/Google Chrome.app"
CHROME_BIN = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CHROME_DATA = Path.home() / "Library" / "Application Support" / "Google" / "Chrome"

if os.name == 'nt':
    import shutil
    CHROME_DATA = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData/Local'))) / 'Google/Chrome/User Data'
    candidates = [Path(os.environ.get(key, 'C:/Program Files')) / 'Google/Chrome/Application/chrome.exe'
                  for key in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA')]
    CHROME_BIN = next((str(p) for p in candidates if p.is_file()), shutil.which('chrome.exe') or str(candidates[0]))
    CHROME_APP = CHROME_BIN
if sys.platform.startswith('linux'):
    import shutil
    CHROME_BIN=shutil.which('google-chrome') or shutil.which('google-chrome-stable') or shutil.which('chromium') or '/usr/bin/google-chrome'
    CHROME_APP=CHROME_BIN
    CHROME_DATA=Path(os.environ.get('XDG_CONFIG_HOME',str(Path.home()/'.config')))/('chromium' if 'chromium' in CHROME_BIN else 'google-chrome')


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def list_chrome_profiles():
    """
    Return [{"directory":"Default","name":"Flow账号", ...}].
    Prefer Chrome Local State profile.info_cache, with Preferences as fallback.
    """
    found = {}
    local_state = _read_json(CHROME_DATA / "Local State")
    info_cache = (
        local_state.get("profile", {}).get("info_cache", {})
        if isinstance(local_state, dict) else {}
    )

    for directory, info in info_cache.items():
        if not isinstance(info, dict):
            continue
        path = CHROME_DATA / directory
        if not path.exists():
            continue
        name = str(info.get("name") or directory)
        user_name = str(info.get("user_name") or "")
        gaia_name = str(info.get("gaia_name") or "")
        found[directory] = {
            "directory": directory,
            "name": name,
            "email": user_name,
            "gaia_name": gaia_name,
            "path": str(path),
        }

    # Fallback if info_cache is absent/stale.
    if CHROME_DATA.exists():
        candidates = [CHROME_DATA / "Default"] + sorted(CHROME_DATA.glob("Profile *"))
        for path in candidates:
            if not path.exists() or path.name in found:
                continue
            prefs = _read_json(path / "Preferences")
            profile = prefs.get("profile", {}) if isinstance(prefs, dict) else {}
            account = prefs.get("account_info", []) if isinstance(prefs, dict) else []
            email = ""
            if isinstance(account, list) and account and isinstance(account[0], dict):
                email = str(account[0].get("email") or "")
            found[path.name] = {
                "directory": path.name,
                "name": str(profile.get("name") or path.name),
                "email": email,
                "gaia_name": "",
                "path": str(path),
            }

    # Natural-ish order: Default, Profile 1, Profile 2...
    def key(item):
        directory = item["directory"]
        if directory == "Default":
            return (0, 0)
        try:
            return (1, int(directory.split()[-1]))
        except Exception:
            return (2, directory)

    return sorted(found.values(), key=key)


def chrome_exists():
    return Path(CHROME_BIN).exists()


def launch_flow(profile_directory: str, url: str):
    if not chrome_exists():
        raise RuntimeError(f"没有找到 Google Chrome：{CHROME_BIN}")

    profile_directory = (profile_directory or "Default").strip()
    url = (url or "https://flow.google.com/").strip()

    # Use the Chrome binary directly. If Chrome is already running, Chrome forwards
    # the request to the matching profile; otherwise it starts that profile.
    subprocess.Popen(
        [CHROME_BIN, f"--profile-directory={profile_directory}", url],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def launch_flow_window(profile_directory: str, url: str, window_name: str = ""):
    """
    Launch a normal native Google Chrome window under the selected Profile.

    Important:
    - Uses --new-window, NOT --app.
    - Keeps address bar, toolbar and extension UI visible.
    - Keeps the selected Chrome Profile's Google login + installed extensions.
    - Each Flow collection is opened in its own normal Chrome window.
    """
    if not chrome_exists():
        raise RuntimeError(f"没有找到 Google Chrome：{CHROME_BIN}")

    profile_directory = (profile_directory or "Default").strip()
    url = (url or "https://flow.google.com/").strip()

    subprocess.Popen(
        [
            CHROME_BIN,
            f"--profile-directory={profile_directory}",
            "--new-window",
            url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


_AUTH_COOKIES = ('SID', 'HSID', 'SSID', 'APISID', 'SAPISID', '__Secure-1PSID', '__Secure-3PSID')


def classify_session(email, flow_cookie, google_cookie):
    """A Flow cookie means already logged in. A Google account means Flow can open."""
    if flow_cookie:
        return '已登录 Flow'
    if google_cookie or '@' in str(email or ''):
        return '可打开 Flow'
    return '未登录'


def valid_profile_directory(directory):
    text = str(directory or '')
    if '..' in text or '/' in text or '\\' in text:
        return False
    return bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}', text))


def chrome_open_command(exe, directory):
    if not valid_profile_directory(directory):
        raise ValueError('Chrome 用户目录无效')
    return [str(exe), f'--profile-directory={directory}', 'https://flow.google.com/']


_SESSION_CACHE = {}


def session_flags(folder):
    """Look only at cookie host and name. Never read the encrypted cookie value."""
    flow_cookie = False
    google_cookie = False
    folder = Path(folder)
    for relative in ('Network/Cookies', 'Cookies'):
        path = folder / relative
        if not path.is_file():
            continue
        try:
            stat = path.stat()
            stamp = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            continue
        key = str(path)
        cached = _SESSION_CACHE.get(key)
        if cached and cached[0] == stamp:
            flow_cookie, google_cookie = cached[1], cached[2]
        else:
            try:
                uri = path.resolve().as_uri() + '?mode=ro&immutable=1'
                connection = sqlite3.connect(uri, uri=True)
                try:
                    flow_cookie = connection.execute(
                        "SELECT 1 FROM cookies WHERE host_key LIKE '%flow.google.com%' LIMIT 1"
                    ).fetchone() is not None
                    placeholders = ','.join('?' for _ in _AUTH_COOKIES)
                    google_cookie = connection.execute(
                        f"SELECT 1 FROM cookies WHERE name IN ({placeholders}) AND host_key LIKE '%google.com%' LIMIT 1",
                        _AUTH_COOKIES,
                    ).fetchone() is not None
                finally:
                    connection.close()
            except (sqlite3.Error, OSError):
                continue
            _SESSION_CACHE[key] = (stamp, flow_cookie, google_cookie)
        if flow_cookie or google_cookie:
            break
    return flow_cookie, google_cookie


_AVATAR_NAMES = (
    'Google Profile Picture.png',
    'Google Profile Picture.jpg',
    'Google Profile.ico',
)


def profile_avatar_file(directory_or_path):
    """Local Chrome profile picture. Never downloads one and never reads cookies."""
    raw = str(directory_or_path or '').strip()
    if not raw:
        return ''
    path = Path(raw)
    if path.is_absolute():
        folder = path
    else:
        if not valid_profile_directory(raw):
            return ''
        folder = CHROME_DATA / raw
    for name in _AVATAR_NAMES:
        candidate = folder / name
        try:
            if candidate.is_file():
                return str(candidate)
        except OSError:
            return ''
    return ''
