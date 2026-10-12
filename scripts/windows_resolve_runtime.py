"""Windows implementation of the Resolve Lua bridge's OS operations.
No shell evaluation, console windows, or arbitrary task-derived shell commands.
"""
import argparse
import ctypes
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


def resolve_window(pid=None):
    import psutil
    from pywinauto import Application
    if pid:
        process = psutil.Process(int(pid))
        if process.name().lower() != 'resolve.exe':
            raise RuntimeError('RESOLVE_PROCESS_MISMATCH')
    else:
        found = [p for p in psutil.process_iter(['name']) if (p.info['name'] or '').lower() == 'resolve.exe']
        if len(found) != 1:
            raise RuntimeError('请启动并进入唯一一个 DaVinci Resolve 主窗口。')
        process = found[0]
    app = Application(backend='uia').connect(process=process.pid, timeout=5)
    windows = [w for w in app.windows() if w.is_visible() and 'DaVinci Resolve' in w.window_text()]
    if len(windows) != 1:
        raise RuntimeError('RESOLVE_MAIN_WINDOW_NOT_READY')
    window = windows[0]
    window.set_focus()
    return app, window, process.pid


def foreground_is(pid):
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetForegroundWindow.restype = ctypes.c_void_p
    user.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    actual = ctypes.c_ulong()
    user.GetWindowThreadProcessId(user.GetForegroundWindow(), ctypes.byref(actual))
    return actual.value == int(pid)


def menu_path(names, pid=None):
    app, window, pid = resolve_window(pid)
    from pywinauto import Desktop
    for alternatives in names:
        matches = []
        for top in Desktop(backend='uia').windows(process=pid):
            matches += [x for x in top.descendants(control_type='MenuItem')
                        if x.is_visible() and x.window_text().replace('&','').split('\t')[0].strip() in alternatives]
        if len(matches) != 1:
            raise RuntimeError('RESOLVE_MENU_NOT_FOUND: ' + ' / '.join(alternatives))
        if not foreground_is(pid):
            raise RuntimeError('RESOLVE_FOCUS_LOST')
        matches[0].click_input()
        time.sleep(0.12)
    return pid


def invoke_menu(script_name, pid=None):
    target = script_name.removesuffix('.lua')
    menu_path([('Workspace','工作区'),('Scripts','脚本'),('Utility','实用工具','实用程序'),
               ('FlowStudioAuto',),(target,target+'.lua')], pid)
    return 'ok'


def timeline_focus(pid):
    pid = menu_path([('Workspace','工作区'),('Active Panel Selection','活动面板选择'),('Timeline','时间线')], pid)
    from pywinauto.keyboard import send_keys
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
