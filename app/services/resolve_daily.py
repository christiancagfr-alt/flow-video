"""Resolve Free daily preparation. All Resolve API calls remain in internal Lua."""
from __future__ import annotations
import json
import os
import re
import shutil
from app.services import quiet_process as subprocess
import sys
import time
import uuid
from datetime import date
from pathlib import Path
from app.core import repository as repo

VERSION = '0.5.0'
BRIDGE_SOURCE = 'FlowStudio_Resolve_Bridge_v0.5.0.lua'
_BRIDGE_INSTALLED_RE = re.compile(r'^FlowStudio_Resolve_Bridge_v\d+\.\d+\.\d+\.lua$')


def installed_bridge_name(app_version=None):
    """Menu name shown inside DaVinci. It follows the app version so an upgrade is visible."""
    from app.version import VERSION as current
    version = str(app_version or current)
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('无效软件版本号')
    return f'FlowStudio_Resolve_Bridge_v{version}.lua'


SCRIPT = installed_bridge_name()
HEARTBEAT_FRESH_SECONDS = 30
IMPORT_DISCONNECT_SECONDS = 45
FPS_VALUES = ('23.976', '24', '25', '29.97', '30', '50', '59.94', '60')
BASE = Path(__file__).resolve().parents[2]


def bridge_root():
    return Path.home() / 'Documents' / 'FlowStudioResolveBridge'


def ensure_bridge_dirs(root=None):
    """Create the folders the Bridge writes. Resolve 21.1 often cannot mkdir itself."""
    root = Path(root or bridge_root())
    for name in ('v0_5_0/commands', 'v0_5_0/done', 'v0_5_0/error', 'v0_5_0/suspended', 'logs'):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def script_dir():
    if sys.platform.startswith('linux'):return Path.home()/'.local/share/DaVinciResolve/Fusion/Scripts/Utility/FlowStudioAuto'
    if os.name == 'nt':
        return Path(os.environ.get('APPDATA', str(Path.home() / 'AppData/Roaming'))) / 'Blackmagic Design/DaVinci Resolve/Support/Fusion/Scripts/Utility/FlowStudioAuto'
    return Path.home() / 'Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/FlowStudioAuto'


def bridge_dofile_command(script_path):
    """Return the Lua console command users can paste to start the installed Bridge."""
    path = Path(script_path).expanduser().resolve()
    if not _BRIDGE_INSTALLED_RE.fullmatch(path.name):
        raise ValueError('Bridge 本地脚本路径无效。')
    value = path.as_posix()
    if any(char in value for char in ('\r', '\n', '\x00')):
        raise ValueError('Bridge 本地脚本路径无效。')
    equals = ''
    while f']{equals}]' in value:
        equals += '='
    return 'dofile([' + equals + '[' + value + ']' + equals + '])'


def prepare_bridge_dofile_command():
    """Ensure the user Bridge file exists, then return its copy-and-paste command."""
    path = script_dir() / SCRIPT
    if not path.is_file():
        install_bridge()
    if not path.is_file():
        raise RuntimeError('没有找到已安装的 Bridge 脚本，请先在组件管理中安装 Bridge。')
    return bridge_dofile_command(path)


def read_pairs(path):
    try:
        return dict(line.split('=', 1) for line in path.read_text(encoding='utf-8').splitlines() if '=' in line)
    except (OSError, UnicodeError):
        return {}


def snapshot(root=None):
    root = root or bridge_root()
    state = read_pairs(root / 'bridge_state.ini')
    try:
        age = time.time() - float(state.get('updated_at', '0'))
        alive = 0 <= age < HEARTBEAT_FRESH_SECONDS and state.get('version') == VERSION and state.get('stage') != 'OFFLINE'
    except ValueError:
        alive = False
    return dict(state, alive=alive, root=str(root))


def _tail_line(path, limit=80):
    try:
        lines = Path(path).read_text(encoding='utf-8', errors='replace').splitlines()
    except (OSError, UnicodeError):
        return ''
    for line in reversed(lines):
        text = line.strip()
        if text:
            return text[:limit]
    return ''


def _resolve_debug_log_path():
    if os.name != 'nt':
        return None
    app_data = os.environ.get('APPDATA')
    if not app_data:
        return None
    return Path(app_data) / 'Blackmagic Design' / 'DaVinci Resolve' / 'Support' / 'logs' / 'ResolveDebug.txt'


def _resolve_debug_log_offset():
    path = _resolve_debug_log_path()
    try:
        return path.stat().st_size if path else None
    except OSError:
        return None


def _recent_resolve_sandbox_error(after_offset=None):
    """Surface Resolve script-runtime restrictions instead of a generic wake timeout."""
    path = _resolve_debug_log_path()
    if path is None:
        return ''
    try:
        stat = path.stat()
        if time.time() - stat.st_mtime > 15 * 60:
            return ''
        with path.open('rb') as log_file:
            if after_offset is not None:
                log_file.seek(after_offset if stat.st_size >= after_offset else 0)
                content = log_file.read()
            else:
                log_file.seek(max(0, stat.st_size - 512 * 1024))
                content = log_file.read()
        lines = content.decode('utf-8', errors='replace').splitlines()[-500:]
    except OSError:
        return ''
    for line in reversed(lines):
        low = line.lower()
        if (('sandbox' in low and ('ffi' in low or 'file' in low or '读写文件' in line))
                or 'bridge_runtime_unavailable' in low):
            diagnostic = re.search(r'\[(platform\.windows=[^\]]+)\]', line, re.IGNORECASE)
            return sandbox_permission_message(diagnostic.group(1) if diagnostic else '')
    return ''


def sandbox_permission_message(diagnostic=''):
    message = ('达芬奇「工作区 → 脚本」的沙箱没有 Bridge 所需的文件接口；“Automatic scripted actions / Allow all”不能补回这些接口。'
               '你已确认「工作区 → 控制台」提供 ffi 与 dofile，可从控制台手动启动 Bridge；菜单启动暂不兼容。')
    if diagnostic:
        message += ' 诊断：' + diagnostic
    return message


def bridge_wait_reason(root):
    """Why the heartbeat is not alive yet. Shown on the wake status line."""
    root = Path(root)
    # Avoid letting the real user's Resolve log leak into checks that inspect
    # an explicitly supplied temporary bridge root.
    sandbox_error = ''
    try:
        if root.resolve() == bridge_root().resolve():
            sandbox_error = _recent_resolve_sandbox_error()
    except OSError:
        pass
    if sandbox_error:
        return sandbox_error
    bits = []
    state_path = root / 'bridge_state.ini'
    heart = root / 'bridge_heartbeat.txt'
    script_ran = heart.is_file() or state_path.is_file()
    if not state_path.is_file():
        bits.append('没有状态文件')
    else:
        state = read_pairs(state_path)
        if not state:
            bits.append('状态文件无法读取')
        else:
            age = None
            try:
                age = max(0, int(time.time() - float(state.get('updated_at') or 0)))
                age_text = f'{age}秒前'
            except (TypeError, ValueError):
                age_text = '时间无效'
            bits.append(f"状态{state.get('stage') or '空'}/{state.get('version') or '无版本'}/{age_text}")
            detail = str(state.get('detail') or '').strip()
            if detail and age is not None and age >= 30:
                detail = '上次记录：' + detail
            if detail:
                bits.append(detail[:60])
    if heart.is_file():
        bits.append(f'心跳文件{max(0, int(time.time() - heart.stat().st_mtime))}秒前')
    else:
        bits.append('没有心跳文件')
    last_log = _tail_line(root / 'logs' / 'bridge.log')
    if last_log:
        bits.append(last_log)
    boot = _tail_line(script_dir() / 'flowstudio-bridge-boot.txt')
    if sys.platform == 'darwin':
        tmp_boot = _tail_line('/tmp/flowstudio-bridge-boot.txt')
        if tmp_boot:
            boot = tmp_boot
    if boot:
        bits.append('脚本已启动 ' + boot)
    if sys.platform == 'darwin':
        error = _tail_line('/tmp/flowstudio-bridge-error.txt')
        if error and error not in boot:
            bits.append(error)
        click = _tail_line('/tmp/flowstudio-menu-click.log', 60)
        if click:
            bits.append('点击 ' + click)
        if 'DOFILE_SENT' in click and not script_ran:
            bits.append('已把脚本发送到控制台，等待达芬奇执行')
        elif not boot and click.startswith('CLICK') and not script_ran:
            bits.append('达芬奇没有执行脚本')
    bits.append(str(root))
    return '；'.join(bits)[:300]


def clear_mac_wake_traces():
    if sys.platform != 'darwin':
        return
    paths = [Path('/tmp/flowstudio-menu-click.log'), Path('/tmp/flowstudio-bridge-error.txt'), Path('/tmp/flowstudio-bridge-boot.txt'), script_dir() / 'flowstudio-bridge-boot.txt']
    for path in paths:
        try:
            if path.name.endswith('.txt'):
                path.unlink(missing_ok=True)
            else:
                path.write_text('', encoding='utf-8')
        except OSError:
            return


def heartbeat_age(state):
    try:
        return time.time() - float(state.get('updated_at') or 0)
    except (TypeError, ValueError):
        return 10 ** 9


def atomic_pairs(path, values):
    if os.name == 'nt':
        values = {k:(str(v).replace(chr(92), '/') if isinstance(v, (str, Path)) and len(str(v))>2 and str(v)[1]==':' else v) for k,v in values.items()}
    path.parent.mkdir(parents=True, exist_ok=True)
    for k, v in values.items():
        if any(c in str(v) for c in '\r\n\x00'):
            raise ValueError('任务参数含非法换行：' + k)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(''.join(f'{k}={v}\n' for k, v in values.items()), encoding='utf-8')
    temp.replace(path)


def reconcile_rebuilt_timeline(day, root=None):
    """Archive stale attempts once; queue unfinished videos without deleting history."""
    from app.core import database
    from app.services import resolve_autoedit as auto
    root = root or bridge_root()
    receipt = read_pairs(root / 'v0_5_0' / ('rebuild_' + day + '.ini'))
    token = receipt.get('rebuild_id', '')
    if not token or receipt.get('work_date') != day or receipt.get('project') != 'FlowStudio-' + day or receipt.get('timeline') != 'MAIN-' + day:
        return 0
    auto.ensure_schema()
    with database.connect() as con:
        con.execute('CREATE TABLE IF NOT EXISTS davinci_rebuild_receipts (rebuild_id TEXT PRIMARY KEY, work_date TEXT NOT NULL, reset_count INTEGER NOT NULL)')
        con.execute('BEGIN IMMEDIATE')
        if con.execute('SELECT 1 FROM davinci_rebuild_receipts WHERE rebuild_id=?',(token,)).fetchone():
            return 0
        batches=[row[0] for row in con.execute("SELECT batch_id FROM davinci_batches WHERE work_date=? AND status NOT IN ('COMPLETED','PROJECT_REBUILT')",(day,))]
        reset=set()
        for bid in batches:
            run=con.execute('SELECT payload_path FROM davinci_autoedit_runs WHERE batch_id=?',(bid,)).fetchone()
            for row in con.execute('SELECT v.id,v.edit_status,v.edit_output_path FROM videos v JOIN davinci_video_state d ON d.video_id=v.id WHERE d.batch_id=?',(bid,)):
                # Preserve confirmed success; an arbitrary leftover file is not a completion receipt.
                out=read_pairs(Path(run['payload_path']).parent / ('export_'+str(row['id'])+'.ini')) if run else {}
                if out.get('status')=='COMPLETE' and out.get('video_id')==str(row['id']) and out.get('output_path') and Path(out['output_path']).is_file():
                    con.execute("UPDATE videos SET edit_status='已导出',edit_output_path=? WHERE id=?",(out['output_path'],row['id']))
                    continue
                if row['edit_status'] in ('已导出','已完成'):
                    continue
                reset.add(row['id'])
            con.execute("UPDATE davinci_batches SET status='PROJECT_REBUILT',error_message='对应时间线已重建；旧批次保留，未完成视频回到待剪辑' WHERE batch_id=?",(bid,))
            con.execute("UPDATE davinci_autoedit_runs SET status='PROJECT_REBUILT',error_message='对应时间线已重建，禁止复用旧切点' WHERE batch_id=?",(bid,))
            con.execute('UPDATE davinci_video_state SET timeline_imported=0 WHERE batch_id=?',(bid,))
        con.executemany("UPDATE videos SET edit_status='待剪辑' WHERE id=?",[(vid,) for vid in reset])
        con.execute('INSERT INTO davinci_rebuild_receipts VALUES(?,?,?)',(token,day,len(reset)))
    return len(reset)


def retire_old_bridge_scripts(folder, keep):
    """Remove previous Bridge menu entries. Other Resolve scripts stay in place."""
    folder = Path(folder)
    removed = []
    if not folder.is_dir():
        return removed
    for path in folder.glob('FlowStudio_Resolve_Bridge_v*.lua'):
        if path.name != keep and _BRIDGE_INSTALLED_RE.fullmatch(path.name):
            path.unlink()
            removed.append(path.name)
    return removed


def install_bridge():
    """Install just the new bridge; never quit Resolve or replace legacy scripts."""
    sources = [BASE / 'davinci_autoedit_v0_5_0' / name for name in (BRIDGE_SOURCE, 'FlowStudio_Import_Batch.lua', 'Autoediting_V1.7_FlowStudio.lua', 'FlowStudio_Finish_Batch.lua', 'FlowStudio_Platform.lua')]
    if os.name == 'nt':
        sources.append(BASE / 'scripts/windows_resolve_runtime.py')
    for source in sources:
        if not source.is_file():
            raise RuntimeError('安装文件缺失：' + str(source))
    folder = script_dir()
    def destination(source):
        if source.name == 'windows_resolve_runtime.py':
            return bridge_root() / 'runtime' / source.name
        if source.name == BRIDGE_SOURCE:
            return folder / SCRIPT
        return folder / source.name
    changed = [source for source in sources if not destination(source).is_file() or destination(source).read_bytes()!=source.read_bytes()]
    config = {'python':windows_python().as_posix(), 'helper':(bridge_root()/'runtime/windows_resolve_runtime.py').as_posix()} if os.name == 'nt' else {}
    config_changed = bool(config and read_pairs(folder/'windows-runtime.ini') != config)
    stale = [path for path in folder.glob('FlowStudio_Resolve_Bridge_v*.lua') if path.name != SCRIPT and _BRIDGE_INSTALLED_RE.fullmatch(path.name)] if folder.is_dir() else []
    if not changed and not config_changed and not stale:
        return False
    if snapshot().get('alive') and (changed or config_changed):
        raise RuntimeError('新版 Bridge 正在运行，请先停止 Bridge，再更新。')
    folder.mkdir(parents=True, exist_ok=True)
    # Install the module first and the calling bridge last.
    for source in reversed(changed):
        dest=destination(source)
        dest.parent.mkdir(parents=True,exist_ok=True)
        temp=dest.with_suffix('.tmp')
        shutil.copyfile(source,temp)
        temp.replace(dest)
    if os.name == 'nt':
        atomic_pairs(folder/'windows-runtime.ini', config)
        # Remove only our former internal helper entry from Resolve's menu.
        (folder/'windows_resolve_runtime.py').unlink(missing_ok=True)
    retire_old_bridge_scripts(folder, SCRIPT)
    return True


def _run(args, **kwargs):
    return subprocess.run(args, capture_output=True, text=True, timeout=12, **kwargs)


def grant_foreground():
    """Let the menu helper take focus. Only works while Flow Studio itself is the foreground process."""
    if os.name != 'nt':
        return
    try:
        import ctypes
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        user32.AllowSetForegroundWindow.argtypes = [ctypes.c_ulong]
        user32.AllowSetForegroundWindow(0xFFFFFFFF)
    except Exception:
        return


def windows_python():
    current = Path(sys.executable)
    if os.name != 'nt':
        return current
    sibling = current.with_name('python.exe')
    return sibling if sibling.is_file() else current


def menu_attempt_due(clicked_at, now, offline, started=False, retried=False):
    """Retry a missed click. After one successful start, allow only one later try.

    A state file that still says OFFLINE must not cause another click every
    second once Bridge has already been started. That click restarts the script.
    """
    if clicked_at is None:
        return True
    if started:
        if retried:
            return False
        return now - clicked_at >= 25
    if offline:
        return True
    return now - clicked_at >= 8


def _not_found_message(raw):
    """Explain which menu level was missing. Include names System Events actually saw."""
    body = raw[raw.lower().find('err:not_found:') + len('err:not_found:'):].splitlines()[0].strip()
    body = re.sub(r'\s*\(-?\d+\)\s*$', '', body).strip()
    missing, _, saw = body.partition('|saw:')
    missing = missing.strip()
    saw = saw.strip()
    missing_low = missing.lower()
    if 'flowstudio_resolve_bridge' in missing_low:
        text = '达芬奇的「工作区 → 脚本」里没有找到 Bridge。请重新打开达芬奇，让脚本菜单刷新后再唤醒。'
    elif 'script' in missing_low or '脚本' in missing:
        text = '达芬奇的「工作区」菜单里没有「脚本」。请让达芬奇主窗口显示在前台后再唤醒。'
    elif missing:
        text = f'达芬奇菜单里没有找到「{missing}」。请重新打开达芬奇后再唤醒。'
    else:
        text = '达芬奇的「工作区 → 脚本」里没有找到 Bridge。请重新打开达芬奇后再唤醒。'
    if saw:
        text += '当前菜单有：' + saw
    return text


def _menu_detail(detail):
    """Use the helper's output field when a status line still contains its JSON."""
    text = str(detail or '').strip()
    for line in reversed(text.splitlines()):
        candidate = line.strip()
        if not candidate.startswith('{'):
            continue
        try:
            payload = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(payload, dict):
            inner = payload.get('error') or payload.get('output')
            if inner:
                return str(inner).strip()
    return text


def menu_failure_text(detail):
    """Turn a menu-helper failure into a short status line.

    The macOS helper reports ``output`` (for example ``ERR:not_found:Scripts|saw:File``)
    rather than ``error``. Showing that JSON makes the wake button look stuck.
    """
    raw = _menu_detail(detail)
    low = raw.lower()
    if ('sandbox_permission_required' in low or 'bridge_runtime_unavailable' in low
            or ('sandbox' in low and ('ffi' in low or '读写文件' in raw))):
        diagnostic = re.search(r'\[(platform\.windows=[^\]]+)\]', raw, re.IGNORECASE)
        return sandbox_permission_message(diagnostic.group(1) if diagnostic else '')
    if '发生错误' in raw:
        return '唤醒没有把命令送进达芬奇控制台。请让达芬奇窗口留在前台，打开「工作区 → 控制台」，再点一次唤醒。'
    if 'resolve_main_window_not_ready' in low:
        return '检测到达芬奇进程，但目前没有可操作的主窗口。请退出启动画面/弹窗，切回达芬奇主界面后重试连接。'
    if 'resolve_focus_lost' in low:
        return '达芬奇窗口没有到前台，已停止输入。请切回达芬奇主界面后重试连接。'
    if any(token in low for token in ('-1719', '-1743', 'assistive', 'not authorized', 'not allowed', '辅助', '不允许')):
        return raw
    if 'err:not_found:undefined' in low or 'err:missing_target' in low:
        return '唤醒没有拿到要运行的达芬奇脚本名称。请更新 Flow Studio 后再唤醒。'
    if 'err:not_found:' in low:
        return _not_found_message(raw)
    if 'err:no_process' in low:
        return '没有找到正在运行的达芬奇。请先打开 DaVinci Resolve，再点唤醒。'
    if 'no module named' in low and 'windows_resolve_runtime' in low:
        return '唤醒组件没有随软件加载。请完全退出并重新打开 Flow Studio，再点一次唤醒。'
    if 'resolve_main_window_not_ready' in low:
        return '达芬奇进程已启动，正在等待主窗口完成加载；请保持达芬奇打开，软件会继续重试。'
    if 'resolve_menu_not_found' in low:
        detail = raw.split('RESOLVE_MENU_NOT_FOUND:', 1)[-1].strip()
        requested, _, seen = detail.partition('|saw:')
        if 'console' in requested.lower() or '控制台' in requested:
            message = '没找到达芬奇控制台入口。请确认 DaVinci Resolve 已完全启动，并在「工作区」菜单中能看到「控制台」。'
        elif 'utility' in requested.lower() or '实用' in requested or '工具' in requested:
            message = '已找到达芬奇主窗口，但没有读到「工作区 → 脚本 → 实用工具」菜单。若刚安装或更新 Bridge，请完全退出并重新打开达芬奇，让它刷新脚本菜单后再唤醒。'
        else:
            message = '已找到达芬奇主窗口，但脚本菜单层级与当前版本不一致。请确认达芬奇已完全启动，并检查「工作区 → 脚本」菜单。'
        if seen:
            message += '当前可读菜单：' + seen[:90]
        return message
    if 'err:no_console' in low:
        return '没有找到达芬奇控制台。请在达芬奇打开「工作区 → 控制台」，看到 Lua> 后，再点一次唤醒。'
    if 'resolve_console_not_found' in low:
        return '达芬奇控制台没有成功打开。请确认「工作区 → 控制台」已经显示 Lua>，再点连接 Bridge。'
    if 'resolve_console_input_not_found' in low:
        return '没有识别到达芬奇 Lua> 命令输入区。请在「工作区 → 控制台」打开 Lua 控制台后再点连接 Bridge。'
    if 'resolve_console_input_failed' in low:
        return '达芬奇控制台已打开，但没有成功输入 Bridge 命令。请点一下控制台中的 Lua> 输入行，再重试连接。'
    if 'invalid_bridge_script_path' in low:
        return 'Bridge 本地脚本路径无效。请在 Flow Studio 的组件管理中重新安装 / 更新 Bridge。'
    if 'console_not_focused' in low:
        return '控制台没有到前台，已停止输入，避免打到时间线上。请点一下达芬奇的控制台窗口，再点唤醒。'
    if 'workspace_not_found' in low or 'no_menu_bar' in low or 'err:unreadable' in low or '不能获取对象' in raw or '-1728' in low or '$.exit' in raw:
        return '达芬奇菜单暂时读不到。请让达芬奇主窗口显示在前台，并在系统设置 → 隐私与安全性 → 辅助功能中允许 Flow Studio。'
    if raw.startswith('ERR:'):
        return '唤醒达芬奇失败：' + raw[4:]
    return raw


def interpret_menu_output(stdout, stderr):
    text = ((stdout or '') + ('\n' + stderr if stderr else '')).strip()
    try:
        payload = json.loads(text.splitlines()[-1])
    except (ValueError, IndexError, AttributeError):
        return False, menu_failure_text(text)[:300]
    if payload.get('ok'):
        return True, ''
    detail = payload.get('error')
    if not detail:
        detail = payload.get('output') or text
    return False, menu_failure_text(str(detail))[:300]


def connection_status_text(state, wake_error=''):
    """Status line for the auto-edit page. A missing whisper path does not block waking Resolve."""
    alive = bool(state.get('alive'))
    error = str(wake_error or '')
    whisper = 'whisper.cpp' in error
    if error and not (not alive and whisper):
        return '⚠ ' + error
    if alive:
        return ('⚠ ' + state['warning']) if state.get('warning') else (state.get('detail') or 'Bridge 在线')
    if state.get('version'):
        text = 'Resolve Bridge 连接中断，请重新唤醒；已保留最近状态。'
        if whisper:
            text += '自动剪辑前请在组件管理中检测或安装 whisper.cpp，这不阻止唤醒。'
        return text
    return ('⚠ ' + error) if error else ''


def menu_error(output):
    text = str(output or '')
    if any(message in text for message in (
        '没找到达芬奇控制台入口', '达芬奇控制台没有成功打开',
        '没有识别到达芬奇 Lua>', '控制台已打开，但没有成功输入 Bridge 命令',
        '控制台没有到前台', '达芬奇窗口没有到前台', '没有可操作的主窗口', '脚本菜单层级与当前版本不一致',
        '工作区」菜单里没有「脚本', '没有读到「工作区 → 脚本',
    )):
        return text
    if '发生错误' in text:
        return '唤醒没有把命令送进达芬奇控制台。请让达芬奇窗口留在前台，打开「工作区 → 控制台」，再点一次唤醒。'
    if any(x in text.lower() for x in ('-1719', '-1743', 'assistive', 'not authorized', 'not allowed', '辅助', '不允许')):
        return '缺少 macOS 辅助功能或自动化权限：请在系统设置 → 隐私与安全性中允许 Flow Studio / Python 控制 DaVinci Resolve。'
    return ''


class DailyWake:
    def __init__(self, fps='25', root=None, day=None):
        self.day = date.fromisoformat(day or date.today().isoformat()).isoformat()
        if str(fps) not in FPS_VALUES:
            raise ValueError('无效时间线帧率，请检查系统设置。')
        self.fps = str(fps)
        self.root = root or bridge_root()
        self.stage = 'LAUNCHING'
        self.detail = '正在唤醒达芬奇'
        self.request_id = ''

    def _invoke_bridge_menu(self):
        python = windows_python()
        script = BASE / 'scripts/davinci_run_menu.py'
        if not python.is_file() or not script.is_file():
            return False, '找不到唤醒达芬奇所需的 Python 或菜单脚本。'
        command = [str(python), str(script), '--script-name', SCRIPT, '--script-path', str(script_dir() / SCRIPT)]
        if sys.platform == 'darwin':
            return self._invoke_macos_menu(command)
        try:
            completed = _run(command)
        except subprocess.TimeoutExpired:
            return False, '达芬奇菜单响应超时，正在重试。请保持达芬奇主界面可见。'
        except OSError as exc:
            return False, '无法启动达芬奇菜单脚本：' + str(exc)[:160]
        return interpret_menu_output(completed.stdout, completed.stderr)

    def _invoke_macos_menu(self, command):
        """Leave a slow click running. Killing it aborts the Bridge script."""
        try:
            proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        except OSError as exc:
            return False, '无法启动达芬奇菜单脚本：' + str(exc)[:160]
        try:
            stdout, stderr = proc.communicate(timeout=12)
        except subprocess.TimeoutExpired:
            return True, '已把脚本发送到控制台，不再重复点击。' + bridge_wait_reason(self.root)
        return interpret_menu_output(stdout, stderr)

    def progress(self, stage, detail):
        self.stage, self.detail = stage, detail
        from app.services.app_paths import data_dir
        log_dir = data_dir() / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / 'davinci-workflow.log').open('a', encoding='utf-8') as f:
            f.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")} request={self.request_id} stage={stage} detail={detail}\n')

    def connect(self, foreground=False):
        try:
            return self._connect(foreground=foreground)
        except Exception as exc:
            self.progress('ERROR', str(exc))
            raise

    def _connect(self, foreground=False):
        """Install, launch and wait for Bridge only; never enqueue project creation."""
        if sys.platform not in ('darwin', 'win32'):
            raise RuntimeError('DaVinci 自动化支持 Windows 与 macOS。')
        ensure_bridge_dirs(self.root)
        state = snapshot(self.root)
        if state['alive']:
            if foreground:
                # Preserve the daily-wake update guard: never use a stale
                # running Bridge when this app's installed files have changed.
                install_bridge()
                from app.services.davinci_workflow import launch_resolve
                launch_resolve()
            self.stage = state.get('stage', 'ONLINE')
            self.detail = 'Bridge 已连接；尚未创建当天项目。'
            self.progress('BRIDGE_CONNECTED', self.detail)
            return state
        heartbeat = self.root / 'bridge_heartbeat.txt'
        if not state['alive'] and state.get('version') != VERSION and heartbeat.exists() and time.time() - heartbeat.stat().st_mtime < HEARTBEAT_FRESH_SECONDS:
            raise RuntimeError('检测到旧版 Resolve Bridge 正在运行。请先停止旧 Bridge；旧版本文件会保留。')
        installed = install_bridge()
        from app.services.davinci_workflow import launch_resolve
        launch_resolve()
        if not state['alive']:
            self.progress('BRIDGE_STARTING', '正在打开达芬奇控制台并启动 Bridge')
            clear_mac_wake_traces()
            deadline = time.monotonic() + 120
            clicked_at = None
            resolve_log_offset = None
            started = False
            retried = False
            last_message = ''
            last_report = 0.0
            menu_attempts = 0
            while time.monotonic() < deadline:
                observed = snapshot(self.root)
                if observed['alive']:
                    state = observed
                    break
                if resolve_log_offset is not None:
                    runtime_error = _recent_resolve_sandbox_error(after_offset=resolve_log_offset)
                    if runtime_error:
                        raise RuntimeError(runtime_error)
                now = time.monotonic()
                if now - last_report >= 5:
                    reason = bridge_wait_reason(self.root)
                    if reason != last_message:
                        self.progress('BRIDGE_STARTING', reason)
                        last_message = reason
                    last_report = now
                if menu_attempt_due(clicked_at, time.monotonic(), observed.get('stage') == 'OFFLINE', started, retried):
                    menu_attempts += 1
                    resolve_log_offset = _resolve_debug_log_offset()
                    grant_foreground()
                    was_started = started
                    ok, message = self._invoke_bridge_menu()
                    clicked_at = time.monotonic()
                    if was_started:
                        retried = True
                    if ok:
                        started = True
                        if '不再重复点击' in message:
                            retried = True
                        message = message or '已向达芬奇 Lua 控制台发送 Bridge 启动命令，正在等待上线。'
                    permission = menu_error(message)
                    if permission:
                        raise RuntimeError(permission)
                    if not ok and menu_attempts >= 3:
                        raise RuntimeError('已尝试连接 3 次，停止重复操作。' + (message or '请确认达芬奇主窗口可见后重试。'))
                    if message and message != last_message:
                        self.progress('BRIDGE_STARTING', message)
                        last_message = message
                time.sleep(1)
            else:
                hint = '首次安装后，达芬奇可能需要重新打开以刷新脚本菜单。' if installed else ''
                detail = bridge_wait_reason(self.root)
                menu_detail = ('最近一次连接结果：' + last_message + '。') if last_message else ''
                bridge_detail = ('Bridge 状态：' + detail) if detail else ''
                raise RuntimeError('Resolve Bridge 启动超时。' + hint + menu_detail + bridge_detail)
        state = snapshot(self.root)
        if not state['alive']:
            raise RuntimeError('Bridge 启动命令已发送，但尚未收到在线心跳。' + bridge_wait_reason(self.root))
        self.stage = state.get('stage', 'ONLINE')
        self.detail = 'Bridge 已连接；尚未创建当天项目。'
        self.progress('BRIDGE_CONNECTED', self.detail)
        return state

    def run(self):
        try:
            return self._run()
        except Exception as exc:
            self.progress('ERROR', str(exc))
            raise

    def _run(self):
        state = self._connect(foreground=True)
        if state.get('stage') not in ('IDLE', 'READY', 'ERROR', 'WAITING_USER_REVIEW'):
            raise RuntimeError('Bridge 当前正在执行任务，请等待当前操作结束：' + state.get('stage', ''))
        self.request_id = uuid.uuid4().hex
        self.progress('PREPARING_PROJECT', '准备当天项目和主时间线')
        day = self.day
        atomic_pairs(self.root / 'v0_5_0/commands' / (self.request_id + '.job'), {
            'action': 'PREPARE_DAILY', 'request_id': self.request_id, 'work_date': day,
            'timeline_fps': self.fps, 'whisper_language': str(repo.get_setting('whisper_language', 'sw')).split(' · ')[-1].strip(),
        })
        deadline = time.monotonic() + 60
        last_alive = time.monotonic()
        while time.monotonic() < deadline:
            state = snapshot(self.root)
            if state.get('stage') == 'OFFLINE':
                raise RuntimeError('Resolve Bridge 连接中断，未继续发送任务。')
            if state['alive']:
                last_alive = time.monotonic()
            elif time.monotonic() - last_alive > HEARTBEAT_FRESH_SECONDS:
                raise RuntimeError('Resolve Bridge 连接中断，未继续发送任务。')
            if state.get('request_id') == self.request_id:
                self.stage, self.detail = state.get('stage', ''), state.get('detail', '')
                if self.stage == 'ERROR':
                    raise RuntimeError(self.detail or '准备失败，请查看 Bridge 日志')
                if self.stage == 'READY':
                    if state.get('project') != 'FlowStudio-' + day or state.get('timeline') != 'MAIN-' + day:
                        raise RuntimeError('Bridge 返回的项目或时间线不匹配。')
                    reset=reconcile_rebuilt_timeline(day,self.root)
                    self.progress('READY', ('已重建时间线，'+str(reset)+' 个未完成视频已回到待剪辑') if reset else state.get('warning') or '达芬奇已就绪')
                    return state
            time.sleep(0.5)
        raise RuntimeError('准备项目超时，保留任务状态；请查看 Bridge 日志后再唤醒。')
