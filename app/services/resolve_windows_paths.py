"""Find Resolve without assuming it is installed on the system drive."""
import os
from pathlib import Path


def registry_candidates():
    import winreg
    locations = [
        (r'SOFTWARE\Blackmagic Design\DaVinci Resolve', 'InstallLocation'),
        (r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\Resolve.exe', ''),
        (r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\DaVinci Resolve', 'InstallLocation'),
    ]
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            for key, value in locations:
                try:
                    with winreg.OpenKey(hive, key, 0, winreg.KEY_READ | view) as handle:
                        path, _ = winreg.QueryValueEx(handle, value)
                        if isinstance(path, str):
                            yield path
                except OSError:
                    continue


def find_executable(configured=''):
    candidates = [configured] if configured else []
    candidates.extend(registry_candidates())
    candidates.extend(str(Path(os.environ.get(key, 'C:/Program Files')) /
                          'Blackmagic Design/DaVinci Resolve/Resolve.exe')
                      for key in ('PROGRAMW6432', 'PROGRAMFILES'))
    for value in candidates:
        if not value:
            continue
        path = Path(os.path.expandvars(value.strip().strip('"')))
        if path.is_dir():
            path = path / 'Resolve.exe'
        if path.name.lower() == 'resolve.exe' and path.is_file():
            return path
    raise RuntimeError('未找到达芬奇。请确认已安装 DaVinci Resolve，并在设置中选择 Resolve.exe 路径。')
