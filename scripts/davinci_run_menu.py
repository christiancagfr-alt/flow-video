#!/usr/bin/env python3
"""Click a DaVinci Resolve Workspace script.

Windows receives the script name as a Python argument and walks the menu bar.
macOS asks System Events for menu names in AppleScript. JXA byName on macOS 27
could not see 脚本, so wake reported that Bridge was missing. The Bridge script
runs until Resolve quits; its menu click uses "ignoring application responses"
so osascript returns as soon as the script starts. Linux has no auto-click.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from app.services import quiet_process as subprocess

_TARGET_RE = re.compile(r'^[A-Za-z0-9_.-]{1,80}$')
_MARKER = re.compile(r'OK:[^\r\n]*|ERR:[^\r\n]*')
_MENU_APPLESCRIPT = r'''
property targetName : __FLOWSTUDIO_TARGET__
on asNameList(value)
  if value is missing value then return {}
  if class of value is list then return value
  return {value as text}
end asNameList
on indexOfName(nameList, wanted)
  set namesFound to my asNameList(nameList)
  set i to 1
  repeat with n in namesFound
    set label to n as text
    repeat with w in wanted
      if label is equal to (contents of w as text) then return i
    end repeat
    set i to i + 1
  end repeat
  return 0
end indexOfName
on indexOfScript(nameList, scriptName)
  set namesFound to my asNameList(nameList)
  set i to 1
  repeat with n in namesFound
    set label to n as text
    if label is equal to scriptName or label is equal to scriptName & ".lua" or scriptName is not "" and label contains scriptName then return i
    set i to i + 1
  end repeat
  return 0
end indexOfScript
on previewNames(nameList)
  set namesFound to my asNameList(nameList)
  set seen to ""
  set i to 0
  repeat with n in namesFound
    set i to i + 1
    if i > 8 then exit repeat
    if seen is not "" then set seen to seen & ","
    set seen to seen & (n as text)
  end repeat
  return seen
end previewNames
on runClick()
  tell application "System Events"
    set proc to missing value
    if exists process "DaVinci Resolve" then set proc to process "DaVinci Resolve"
    if proc is missing value then
      if exists process "Resolve" then set proc to process "Resolve"
    end if
    if proc is missing value then return "ERR:no_process"
    tell proc
      try
        set frontmost to true
      end try
      delay 0.4
      try
        set barNames to name of menu bar items of menu bar 1
      on error errMsg
        return "ERR:no_menu_bar:" & errMsg
      end try
      set wsIndex to my indexOfName(barNames, {"Workspace", "工作区"})
      if wsIndex is 0 then return "ERR:workspace_not_found"
      set parentItem to menu bar item wsIndex of menu bar 1
      try
        click parentItem
      end try
      delay 0.25
      set folderQueue to {{"Scripts", "脚本"}, {"Utility", "实用工具", "实用程序"}, {"FlowStudioAuto"}}
      repeat while true
        try
          set namesNow to name of menu items of menu 1 of parentItem
        on error errMsg
          return "ERR:unreadable:" & errMsg
        end try
        set scriptIndex to my indexOfScript(namesNow, targetName)
        if scriptIndex > 0 then
          set chosen to name of menu item scriptIndex of menu 1 of parentItem as text
          ignoring application responses
            click menu item scriptIndex of menu 1 of parentItem
          end ignoring
          delay 0.3
          return "OK:" & chosen
        end if
        if (count of folderQueue) is 0 then return "ERR:not_found:" & targetName & "|saw:" & my previewNames(namesNow)
        set wanted to contents of item 1 of folderQueue
        set folderQueue to rest of folderQueue
        set folderIndex to my indexOfName(namesNow, wanted)
        if folderIndex is 0 then
          set childNamesList to my asNameList(namesNow)
          set childMax to count of childNamesList
          if childMax > 25 then set childMax to 25
          repeat with childIndex from 1 to childMax
            try
              set deepNames to name of menu items of menu 1 of menu item childIndex of menu 1 of parentItem
              set deepIndex to my indexOfScript(deepNames, targetName)
              if deepIndex > 0 then
                set chosen to name of menu item deepIndex of menu 1 of menu item childIndex of menu 1 of parentItem as text
                ignoring application responses
                  click menu item deepIndex of menu 1 of menu item childIndex of menu 1 of parentItem
                end ignoring
                delay 0.3
                return "OK:" & chosen
              end if
            end try
          end repeat
          return "ERR:not_found:" & (item 1 of wanted as text) & "|saw:" & my previewNames(namesNow)
        end if
        set parentItem to menu item folderIndex of menu 1 of parentItem
        try
          click parentItem
        end try
        delay 0.25
      end repeat
    end tell
  end tell
end runClick
return runClick()
'''


def script_basename(script_name):
    name = str(script_name or '').strip()
    if name.lower().endswith('.lua'):
        name = name[:-4]
    return name


def _applescript_string(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'


def macos_menu_source(script_name):
    """AppleScript that reads Workspace menu names and starts this script."""
    target = script_basename(script_name)
    if not _TARGET_RE.fullmatch(target):
        raise ValueError('达芬奇脚本名称无效。')
    return _MENU_APPLESCRIPT.replace('__FLOWSTUDIO_TARGET__', _applescript_string(target))


def macos_osascript_command(script_name):
    return ['/usr/bin/osascript', '-e', macos_menu_source(script_name)]


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--script-name', required=True)
    args = ap.parse_args()
    if sys.platform.startswith('linux'):
        print(json.dumps({'ok':False,'error':'Linux 请在达芬奇 工作区 → 脚本 菜单手动运行对应脚本。'},ensure_ascii=False));return 1
    if sys.platform == 'win32':
        try:
            from windows_resolve_runtime import invoke_menu
            output = invoke_menu(args.script_name)
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
