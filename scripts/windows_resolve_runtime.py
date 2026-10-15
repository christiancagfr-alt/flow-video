"""Windows implementation of the Resolve Lua bridge's OS operations.
No shell evaluation, console windows, or arbitrary task-derived shell commands.
"""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time

FLAGS = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
ROOT = Path.home() / 'Documents/FlowStudioResolveBridge'


def process_options():
    return dict(creationflags=FLAGS, stdin=subprocess.DEVNULL)


def _window_area(window):
    try:
        rect = window.rectangle()
        return max(0, int(rect.width())) * max(0, int(rect.height()))
    except Exception:
        return 0


def pick_resolve_window(candidates):
    """Choose the largest visible DaVinci window. Each item is (area, pid, hwnd)."""
    visible = [item for item in candidates if int(item[0]) > 0 and int(item[2])]
    if not visible:
        return None
    return max(visible, key=lambda item: int(item[0]))


def resolve_windows():
    """Visible top-level windows owned by Resolve.exe as (area, pid, hwnd).

    Resolve 21 can leave the main window title empty while it is starting, and
    localized builds do not always use the English product name in the title.
    Identify the process by its executable instead of relying on window text.
    """
    import psutil
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
    user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    candidates = []
    enumerator = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    user32.EnumWindows.argtypes = [enumerator, ctypes.c_void_p]
    user32.EnumWindows.restype = ctypes.c_int

    @enumerator
    def visit(hwnd, _param):
        if not user32.IsWindowVisible(hwnd):
            return True
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        area = max(0, int(rect.right) - int(rect.left)) * max(0, int(rect.bottom) - int(rect.top))
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        candidates.append((area, int(pid.value), int(hwnd or 0)))
        return True

    user32.EnumWindows(visit, 0)
    results = []
    for candidate in candidates:
        try:
            if psutil.Process(candidate[1]).name().lower() == 'resolve.exe':
                results.append(candidate)
        except (psutil.Error, OSError):
            continue
    return results


def force_foreground(hwnd):
    """Bring a window forward. Windows blocks SetForegroundWindow unless this process may take focus."""
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    user32.IsIconic.argtypes = [ctypes.c_void_p]
    user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.ShowWindow.restype = ctypes.c_int
    user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    user32.SetForegroundWindow.restype = ctypes.c_int
    user32.BringWindowToTop.argtypes = [ctypes.c_void_p]
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
    user32.AttachThreadInput.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_int]
    user32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, ctypes.c_ulong, ctypes.c_void_p]
    user32.AllowSetForegroundWindow.argtypes = [ctypes.c_ulong]
    kernel32.GetCurrentThreadId.restype = ctypes.c_ulong
    handle = ctypes.c_void_p(int(hwnd))
    user32.ShowWindow(handle, 9 if user32.IsIconic(handle) else 5)
    user32.AllowSetForegroundWindow(0xFFFFFFFF)
    # A momentary Alt tap is the documented way to lift the foreground lock.
    user32.keybd_event(0x12, 0, 0, None)
    foreground = user32.GetForegroundWindow()
    current = kernel32.GetCurrentThreadId()
    target = user32.GetWindowThreadProcessId(handle, None)
    source = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
    if source:
        user32.AttachThreadInput(current, source, True)
    if target:
        user32.AttachThreadInput(current, target, True)
    user32.BringWindowToTop(handle)
    user32.SetForegroundWindow(handle)
    if target:
        user32.AttachThreadInput(current, target, False)
    if source:
        user32.AttachThreadInput(current, source, False)
    user32.keybd_event(0x12, 0, 2, None)


def resolve_window(pid=None):
    import psutil
    from pywinauto import Application
    chosen = pick_resolve_window(resolve_windows())
    if pid and chosen and int(chosen[1]) != int(pid):
        chosen = pick_resolve_window([item for item in resolve_windows() if int(item[1]) == int(pid)])
    if not chosen:
        found = [p for p in psutil.process_iter(['name']) if (p.info.get('name') or '').lower() == 'resolve.exe']
        if not found:
            raise RuntimeError('请先启动 DaVinci Resolve。')
        raise RuntimeError('RESOLVE_MAIN_WINDOW_NOT_READY')
    _area, process_pid, hwnd = chosen
    try:
        if psutil.Process(process_pid).name().lower() != 'resolve.exe':
            raise RuntimeError('RESOLVE_PROCESS_MISMATCH')
    except psutil.Error as exc:
        raise RuntimeError('RESOLVE_MAIN_WINDOW_NOT_READY') from exc
    try:
        force_foreground(hwnd)
    except Exception:
        pass
    last = RuntimeError('RESOLVE_MAIN_WINDOW_NOT_READY')
    for _ in range(2):
        try:
            app = Application(backend='uia').connect(process=process_pid, timeout=4)
            # The UI title can be blank during startup or omit the product name
            # on localized/version-specific builds. The Application is already
            # attached to the verified Resolve PID, so process ownership is the
            # reliable filter here.
            windows = [w for w in app.windows() if w.is_visible() and _window_area(w) > 0]
            if not windows:
                last = RuntimeError('RESOLVE_MAIN_WINDOW_NOT_READY')
            else:
                window = max(windows, key=_window_area)
                try:
                    force_foreground(int(window.handle))
                except Exception:
                    pass
                time.sleep(0.1)
                return app, window, process_pid
        except Exception as exc:
            last = exc if isinstance(exc, RuntimeError) else RuntimeError('RESOLVE_MAIN_WINDOW_NOT_READY')
        time.sleep(0.25)
    raise last


def foreground_is(pid):
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetForegroundWindow.restype = ctypes.c_void_p
    user.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    actual = ctypes.c_ulong()
    user.GetWindowThreadProcessId(user.GetForegroundWindow(), ctypes.byref(actual))
    return actual.value == int(pid)


def foreground_window_is(hwnd):
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetForegroundWindow.restype = ctypes.c_void_p
    return int(user.GetForegroundWindow() or 0) == int(hwnd)


def _menu_label(item):
    try:
        return (item.window_text() or '').replace('&', '').split('\t')[0].strip()
    except Exception:
        return ''


def _normalize_menu_label(value):
    text = str(value or '').replace('&', '').split('\t')[0].strip()
    return re.sub(r'[\s.…．。]+$', '', text).casefold()


def _safe_children(parent, control_type):
    if parent is None:
        return []
    try:
        return list(parent.children(control_type=control_type))
    except Exception:
        return []


def _matching_items(items, alternatives):
    expected = {_normalize_menu_label(value) for value in alternatives}
    found = []
    for item in items:
        try:
            visible = item.is_visible()
        except Exception:
            visible = True
        if visible and _normalize_menu_label(_menu_label(item)) in expected:
            found.append(item)
    return found


def _items_under(parent, recursive=True):
    """Collect menu items through nested UIA Menu/MenuItem containers only."""
    found = []
    pending = [parent]
    visited = set()
    while pending:
        node = pending.pop()
        identity = getattr(node, 'handle', None) or id(node)
        if identity in visited:
            continue
        visited.add(identity)
        menus = _safe_children(node, 'Menu')
        items = _safe_children(node, 'MenuItem')
        found.extend(items)
        if recursive:
            pending.extend(menus)
            pending.extend(items)
        elif node is parent:
            for menu in menus:
                found.extend(_safe_children(menu, 'MenuItem'))
    return found


def _bar_items(window):
    bars = _safe_children(window, 'MenuBar')
    if not bars:
        return _items_under(window)
    found = []
    for bar in bars:
        found.extend(_items_under(bar, recursive=False))
    return found


def _popup_items(app, window):
    # A newly opened menu is its own top-level window. Never walk the whole Resolve tree.
    found = []
    try:
        tops = [top for top in app.windows() if getattr(top, 'handle', None) != getattr(window, 'handle', None)]
    except Exception:
        tops = []
    for top in tops:
        found.extend(_items_under(top))
    return found


def _unique_items(items):
    result = []
    seen = set()
    for item in items:
        identity = getattr(item, 'handle', None) or id(item)
        if identity not in seen:
            seen.add(identity)
            result.append(item)
    return result


def _activate_item(item, can_click):
    for name in ('expand', 'invoke'):
        action = getattr(item, name, None)
        if action is None:
            continue
        try:
            action()
            return name
        except Exception:
            continue
    if not can_click:
        raise RuntimeError('RESOLVE_FOCUS_LOST: 达芬奇窗口没有拿到前台。请点开达芬奇主界面后重试。')
    item.click_input()
    return 'click'


def menu_path(names, pid=None, optional_indices=()):
    app, window, pid = resolve_window(pid)
    current = None
    optional_indices = set(optional_indices)
    for index, alternatives in enumerate(names):
        focused = foreground_is(pid)
        if not focused:
            try:
                force_foreground(int(window.handle))
            except Exception:
                pass
            time.sleep(0.12)
            focused = foreground_is(pid)
        matches = []
        labels = []
        # Resolve sometimes builds the next submenu after a short delay. Poll
        # the currently open menu instead of failing on the first empty UIA
        # snapshot.
        for attempt in range(10):
            pool = _items_under(current) if current is not None else _bar_items(window)
            extra = _popup_items(app, window)
            if current is None:
                extra = _bar_items(window) + extra
            combined = _unique_items(pool + extra)
            labels = list(dict.fromkeys(_menu_label(item) for item in combined if _menu_label(item)))
            matches = _matching_items(combined, alternatives)
            if matches or len(matches) > 1 or attempt == 9:
                break
            time.sleep(0.12)
        if len(matches) != 1:
            if not matches and index in optional_indices:
                # Some Resolve builds expose the user script folder directly
                # under Scripts rather than exposing the Utility grouping.
                continue
            if index == 0 and not matches:
                raise RuntimeError('RESOLVE_MAIN_WINDOW_NOT_READY')
            seen = ', '.join(labels[:12]) or '无可读菜单项'
            raise RuntimeError('RESOLVE_MENU_NOT_FOUND: ' + ' / '.join(alternatives) + '|saw:' + seen)
        _activate_item(matches[0], focused)
        current = matches[0]
        time.sleep(0.12)
    return pid


def invoke_menu(script_name, pid=None):
    target = script_name.removesuffix('.lua')
    menu_path([('Workspace','工作区'),('Scripts','脚本'),
               ('Utility','Utilities','实用工具','实用程序','工具'),
               ('FlowStudioAuto',),(target,target+'.lua')], pid, optional_indices=(2,))
    return 'ok'


def console_dofile_line(script_path):
    """Build a safe Lua dofile command for the installed Bridge script."""
    from app.services.resolve_daily import bridge_dofile_command
    try:
        return bridge_dofile_command(script_path)
    except ValueError as exc:
        raise ValueError('INVALID_BRIDGE_SCRIPT_PATH') from exc


def _resolve_console_window(pid):
    from pywinauto import Application

    app = Application(backend='uia').connect(process=int(pid), timeout=5)
    deadline = time.monotonic() + 8
    last_windows = []
    while time.monotonic() < deadline:
        try:
            last_windows = [w for w in app.windows() if w.is_visible() and _window_area(w) > 0]
        except Exception:
            last_windows = []
        named = []
        marked = []
        for window in last_windows:
            title = _menu_label(window).casefold()
            if 'console' in title or '控制台' in title:
                named.append(window)
                continue
            try:
                buttons = window.descendants(control_type='Button')
            except Exception:
                buttons = []
            if any(_menu_label(button).casefold() in ('cls', 'clear', '清除') for button in buttons):
                marked.append(window)
        if named or marked:
            return (named or marked)[0]
        time.sleep(0.2)
    raise RuntimeError('RESOLVE_CONSOLE_NOT_FOUND')


def _resolve_console_input(window):
    candidates = []
    for control_type in ('Edit', 'Document'):
        try:
            controls = window.descendants(control_type=control_type)
        except Exception:
            controls = []
        for control in controls:
            try:
                if control.is_visible() and control.is_enabled():
                    rect = control.rectangle()
                    candidates.append((int(rect.bottom), int(rect.width()) * int(rect.height()), control))
            except Exception:
                continue
    if not candidates:
        raise RuntimeError('RESOLVE_CONSOLE_INPUT_NOT_FOUND')
    return max(candidates, key=lambda item: (item[0], item[1]))[2]


def _send_unicode_text(text):
    """Type Unicode without changing or temporarily replacing the user's clipboard."""
    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ('wVk', wintypes.WORD), ('wScan', wintypes.WORD),
            ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD),
            ('dwExtraInfo', ctypes.c_size_t),
        ]

    class INPUT_UNION(ctypes.Union):
        _fields_ = [('ki', KEYBDINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [('type', wintypes.DWORD), ('union', INPUT_UNION)]

    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_UNICODE = 0x0004
    events = []
    for char in text:
        code = ord(char)
        if code > 0xFFFF:
            code -= 0x10000
            units = (0xD800 + (code >> 10), 0xDC00 + (code & 0x3FF))
        else:
            units = (code,)
        for unit in units:
            events.append(INPUT(type=1, union=INPUT_UNION(ki=KEYBDINPUT(0, unit, KEYEVENTF_UNICODE, 0, 0))))
            events.append(INPUT(type=1, union=INPUT_UNION(ki=KEYBDINPUT(0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, 0))))
    if not events:
        return
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
    data = (INPUT * len(events))(*events)
    sent = user32.SendInput(len(events), data, ctypes.sizeof(INPUT))
    if sent != len(events):
        raise RuntimeError('RESOLVE_CONSOLE_INPUT_FAILED')


def invoke_console_dofile(script_name, script_path, pid=None):
    """Open Resolve's Lua console and run the installed Bridge without menu sandboxing."""
    name = Path(str(script_name)).name
    target = Path(script_path).expanduser().resolve()
    if name != target.name:
        raise ValueError('INVALID_BRIDGE_SCRIPT_PATH')
    line = console_dofile_line(target)
    pid = menu_path([('Workspace', '工作区'), ('Console', '控制台')], pid)
    window = _resolve_console_window(pid)
    input_control = _resolve_console_input(window)
    try:
        input_control.set_focus()
    except Exception:
        pass
    try:
        rect = input_control.rectangle()
        input_control.click_input(coords=(max(2, int(rect.width()) // 2), max(2, int(rect.height()) - 4)))
    except Exception:
        pass
    if not foreground_is(pid) or not foreground_window_is(int(window.handle)):
        try:
            force_foreground(int(window.handle))
        except Exception:
            pass
        try:
            input_control.set_focus()
        except Exception:
            pass
    if not foreground_is(pid) or not foreground_window_is(int(window.handle)):
        raise RuntimeError('RESOLVE_CONSOLE_NOT_FOCUSED')
    # Resolve's console is a command prompt at the end of its output view.
    # Ctrl+End puts the caret on the Lua prompt even when the window opened
    # with focus on the output pane.
    from pywinauto.keyboard import send_keys
    try:
        send_keys('^{END}', pause=0.04)
        time.sleep(0.1)
        _send_unicode_text(line)
        send_keys('{ENTER}', pause=0.04)
    except Exception as exc:
        if isinstance(exc, RuntimeError) and str(exc) == 'RESOLVE_CONSOLE_INPUT_FAILED':
            raise
        raise RuntimeError('RESOLVE_CONSOLE_INPUT_FAILED') from exc
    return 'OK:console'


def timeline_focus(pid):
    pid = menu_path([('Workspace','工作区'),('Active Panel Selection','活动面板选择'),('Timeline','时间线')], pid)
    from pywinauto.keyboard import send_keys
    _, window, pid = resolve_window(pid)
    if not foreground_is(pid):
        try:
            window.set_focus()
        except Exception:
            pass
        time.sleep(0.2)
    if not foreground_is(pid): raise RuntimeError('RESOLVE_FOCUS_LOST')
    send_keys('k^+a', pause=0.04)
    return 'ok'


def finish_choice():
    from PySide6.QtWidgets import QApplication, QMessageBox
    from PySide6.QtCore import Qt
    app = QApplication.instance() or QApplication([])
    dialog = QMessageBox()
    dialog.setWindowTitle('Flow Studio · 完成批次')
    dialog.setText('选择当前批次的操作：')
    dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    cleanup = dialog.addButton('清理并导出', QMessageBox.ButtonRole.ActionRole)
    export = dialog.addButton('直接批量导出', QMessageBox.ButtonRole.ActionRole)
    dialog.addButton('取消', QMessageBox.ButtonRole.RejectRole)
    dialog.exec()
    return 'cleanup' if dialog.clickedButton() == cleanup else 'export' if dialog.clickedButton() == export else 'cancel'



def _owned_file(pid):
    folder=ROOT/'windows-runtime/owned';folder.mkdir(parents=True,exist_ok=True)
    return folder/(str(int(pid))+'.json')


def launch_owned(args, log_path, pid_path):
    import psutil
    with Path(log_path).open('ab') as log:
        child=subprocess.Popen(args,stdout=log,stderr=subprocess.STDOUT,**process_options())
    try:
        stamp=psutil.Process(child.pid).create_time()
        _owned_file(child.pid).write_text(json.dumps({'created':stamp}),encoding='utf-8')
        Path(pid_path).write_text(str(child.pid),encoding='utf-8')
    except psutil.NoSuchProcess:
        Path(pid_path).write_text('0',encoding='utf-8')
    return ''


def terminate_owned(pid):
    import psutil
    record=_owned_file(pid)
    if not record.is_file(): return ''
    try:
        owner=psutil.Process(pid)
        if abs(owner.create_time()-json.loads(record.read_text())['created']) > .01:
            raise RuntimeError('PROCESS_ID_REUSED')
        children=owner.children(recursive=True)
        for child in children: child.terminate()
        owner.terminate()
        _,alive=psutil.wait_procs(children+[owner],timeout=3)
        for child in alive: child.kill()
    except psutil.NoSuchProcess:
        pass
    record.unlink(missing_ok=True)
    return ''


def dispatch(command, pid=0):
    if command == 'FS_TIMELINE_FOCUS': return timeline_focus(pid)
    if command == 'FS_FINISH_CHOICE': return finish_choice()
    # Existing Lua command strings use POSIX quoting, even on Windows. Parse
    # arguments only; never execute them through cmd/PowerShell or a POSIX shell.
    tokens = shlex.split(command, posix=True)
    if not tokens: return ''
    if tokens[:2] == ['mkdir','-p']:
        Path(tokens[2]).mkdir(parents=True,exist_ok=True);return ''
    if tokens[0] == 'mkdir': Path(tokens[1]).mkdir();return ''
    if tokens[0] == 'rmdir': Path(tokens[1]).rmdir();return ''
    if tokens[:3] == ['/usr/bin/stat','-f','%m']:
        return str(int(Path(tokens[3]).stat().st_mtime))+'\n'
    if tokens[0] == 'find':
        return ''.join(p.as_posix()+'\n' for p in sorted(Path(tokens[1]).glob('*.job')) if p.is_file())
    if tokens[:2] == ['pkill','-TERM']:
        return terminate_owned(int(tokens[3]))
    if command.startswith('(') and command.endswith(')'):
        tokens=shlex.split(command[1:-1])
        out=tokens.index('>');background=tokens.index('&')
        if tokens[background+1:background+4] != ['echo','$!','>']:
            raise ValueError('UNSUPPORTED_BACKGROUND_COMMAND')
        return launch_owned(tokens[:out],tokens[out+1],tokens[background+4])
    # Only the generated Python audio probe is a foreground external command.
    if tokens[0].lower().endswith(('python.exe','pythonw.exe')) and '>' in tokens and '2>' in tokens:
        split=tokens.index('>');err=tokens.index('2>')
        with Path(tokens[split+1]).open('wb') as output, Path(tokens[err+1]).open('wb') as error:
            result=subprocess.run(tokens[:split],stdout=output,stderr=error,timeout=180,**process_options())
        if result.returncode: raise RuntimeError('AUDIO_PROBE_FAILED')
        return ''
    raise ValueError('UNSUPPORTED_WINDOWS_BRIDGE_COMMAND: '+command[:160])


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--request',required=True);parser.add_argument('--pid',type=int,default=0)
    args=parser.parse_args();request=Path(args.request)
    try:
        output=dispatch(request.read_text(encoding='utf-8'), args.pid)
        request.with_suffix('.out').write_text(output or '',encoding='utf-8',newline='\n')
        return 0
    except Exception as exc:
        request.with_suffix('.out').write_text(str(exc),encoding='utf-8',newline='\n')
        return 1

if __name__=='__main__':
    raise SystemExit(main())
