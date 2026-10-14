#!/usr/bin/env python3
"""Start a DaVinci Resolve Workspace script.

Windows receives the script name as a Python argument and walks the menu bar.
macOS pastes dofile into the Resolve console. A menu click reports success
without running the Lua file on Resolve 21. Linux has no auto-start.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT))
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
from app.services import quiet_process as subprocess

_TARGET_RE = re.compile(r'^[A-Za-z0-9_.-]{1,80}$')
_MARKER = re.compile(r'OK:[^\r\n]*|ERR:[^\r\n]*')
_CONSOLE_APPLESCRIPT = r'''
property luaLine : __FLOWSTUDIO_LINE__
on trace(message)
  try
    do shell script "printf %s " & quoted form of ((message as text) & linefeed) & " >> /tmp/flowstudio-menu-click.log"
  end try
end trace
on isConsole(windowName)
  set label to windowName as text
  if label contains "Console" or label contains "console" or label contains "控制台" then return true
  return false
end isConsole
on consoleIndex(procName)
  set found to 0
  tell application "System Events"
    if exists process procName then
      tell process procName
        set totalCount to count of windows
        repeat with i from 1 to totalCount
          try
            if my isConsole(name of window i as text) then set found to i as integer
          end try
          if found is not 0 then exit repeat
        end repeat
      end tell
    end if
  end tell
  return found
end consoleIndex
set procName to "DaVinci Resolve"
tell application "System Events"
  if not (exists process procName) then set procName to "Resolve"
  if not (exists process procName) then set procName to ""
end tell
if procName is "" then
  my trace("NO_PROCESS")
  return "ERR:no_process"
end if
tell application "System Events"
  tell process procName to set frontmost to true
end tell
delay 0.4
set idx to my consoleIndex(procName)
if idx is 0 then
  my trace("OPEN_CONSOLE")
  tell application "System Events"
    tell process procName
      set opened to false
      repeat with barName in {"工作区", "Workspace"}
        repeat with itemName in {"控制台", "Console"}
          try
            click menu item itemName of menu 1 of menu bar item barName of menu bar 1
            set opened to true
            exit repeat
          end try
        end repeat
        if opened then exit repeat
      end repeat
    end tell
  end tell
  delay 0.8
  set idx to my consoleIndex(procName)
end if
if idx is 0 then
  my trace("NO_CONSOLE")
  return "ERR:no_console"
end if
tell application "System Events"
  tell process procName
    try
      perform action "AXRaise" of window idx
    end try
    click window idx
  end tell
end tell
delay 0.3
set frontName to ""
tell application "System Events"
  try
    set frontName to name of window 1 of process procName as text
  end try
end tell
if my isConsole(frontName) is false then
  my trace("FOCUS_FAIL " & frontName)
  return "ERR:console_not_focused:" & frontName
end if
my trace("TYPE_DOFILE")
try
  set previousClip to the clipboard
end try
set the clipboard to luaLine
delay 0.2
tell application "System Events"
  keystroke "v" using command down
  delay 0.35
  keystroke return
end tell
delay 0.15
try
  set the clipboard to previousClip
end try
my trace("DOFILE_SENT")
return "OK:console"
'''


def script_basename(script_name):
    name = str(script_name or '').strip()
    if name.lower().endswith('.lua'):
        name = name[:-4]
    return name


def _applescript_string(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'


def macos_console_source(script_path):
    """AppleScript that types dofile of this installed script into the Resolve console."""
    path = str(script_path).replace('\\', '/')
    name = path.rsplit('/', 1)[-1]
    stem = name[:-4] if name.endswith('.lua') else name
    if not path.startswith('/') or not path.endswith('.lua') or "'" in path or '\n' in path or not _TARGET_RE.fullmatch(stem):
        raise ValueError('达芬奇脚本路径无效。')
    line = "dofile('" + path + "')"
    source = _CONSOLE_APPLESCRIPT.replace('__FLOWSTUDIO_LINE__', _applescript_string(line))
    if '__FLOWSTUDIO_LINE__' in source:
        raise ValueError('达芬奇脚本路径无效。')
    return source


def macos_osascript_command(script_name, script_path=None):
    if script_path is None:
        from app.services.resolve_daily import script_dir
        script_path = script_dir() / str(script_name)
    return ['/usr/bin/osascript', '-e', macos_console_source(script_path)]


def macos_menu_status(stdout, stderr):
    """Success is an OK: line. A click that starts Bridge returns before the script ends."""
    text = ((stdout or '') + ('\n' + stderr if stderr else '')).strip()
    ok_line = ''
    err_line = ''
    for match in _MARKER.finditer(text):
        token = re.sub(r'\s*\(-?\d+\)\s*$', '', match.group(0)).strip()
        if token.startswith('OK:'):
            ok_line = token
        elif token.startswith('ERR:'):
            err_line = token
    if ok_line:
        return True, ok_line
    if err_line:
        return False, err_line
    return False, text


def macos_result(stdout, stderr, returncode):
    ok, detail = macos_menu_status(stdout, stderr)
    return {'ok': ok, 'output': detail, 'returncode': returncode}


def load_windows_menu():
    """Load the helper beside this file.

    The packaged Python keeps a ._pth file, so it never adds the script folder
    to sys.path. A bare import then fails after every restart.
    """
    from importlib.util import module_from_spec, spec_from_file_location
    helper = _HERE / 'windows_resolve_runtime.py'
    if not helper.is_file():
        raise RuntimeError('找不到唤醒达芬奇所需的组件 windows_resolve_runtime.py')
    spec = spec_from_file_location('flowstudio_windows_resolve_runtime', helper)
    if spec is None or spec.loader is None:
        raise RuntimeError('找不到唤醒达芬奇所需的组件 windows_resolve_runtime.py')
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.invoke_menu


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--script-name', required=True)
    args = ap.parse_args()
    if sys.platform.startswith('linux'):
        print(json.dumps({'ok':False,'error':'Linux 请在达芬奇 工作区 → 脚本 菜单手动运行对应脚本。'},ensure_ascii=False));return 1
    if sys.platform == 'win32':
        try:
            output = load_windows_menu()(args.script_name)
            print(json.dumps({'ok': True, 'output': output}))
            return 0
        except Exception as exc:
            print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=True))
            return 1
    try:
        command = macos_osascript_command(args.script_name)
    except ValueError as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False))
        return 1
    p = subprocess.run(command, capture_output=True, text=True)
    result = macos_result(p.stdout, p.stderr, p.returncode)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
