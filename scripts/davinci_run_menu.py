#!/usr/bin/env python3
"""Click a DaVinci Resolve Workspace script.

Windows receives the script name as a Python argument and walks the menu bar.
macOS embeds that name as a JSON string and clicks one menu level at a time.
JXA on macOS 27 has no $.exit, and calling menuItems() or menuBars() realizes
every item, including separators, which throws "不能获取对象". Success is an
OK: line. Linux has no auto-click.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from app.services import quiet_process as subprocess

_TARGET_RE = re.compile(r'^[A-Za-z0-9_.-]{1,80}$')
_MENU_JS = r'''
var target = __FLOWSTUDIO_TARGET__;
function pick(elements, alternatives) {
  for (var a = 0; a < alternatives.length; a++) {
    try {
      var item = elements.byName(alternatives[a]);
      if (String(item.name())) return item;
    } catch (e) {}
  }
  return null;
}
function pickScript(elements) {
  var exact = pick(elements, [target, target + '.lua']);
  if (exact) return exact;
  var misses = 0;
  for (var i = 0; i < 80; i++) {
    var item;
    try { item = elements[i]; }
    catch (e) { misses += 1; if (misses > 2) break; continue; }
    misses = 0;
    var name = '';
    try { name = String(item.name()); } catch (e2) { continue; }
    if (name && name.indexOf(target) >= 0) return item;
  }
  return null;
}
function clickDown(item, label) {
  try { item.click(); }
  catch (e) { return 'ERR:click:' + label + ':' + e; }
  delay(0.25);
  try { return item.menus[0].menuItems; }
  catch (e2) { return 'ERR:no_submenu:' + label + ':' + e2; }
}
function run() {
  if (!target) return 'ERR:missing_target';
  var se = Application('System Events');
  var p = null;
  var processNames = ['DaVinci Resolve', 'Resolve'];
  for (var i = 0; i < processNames.length; i++) {
    try {
      var candidate = se.processes.byName(processNames[i]);
      if (String(candidate.name())) { p = candidate; break; }
    } catch (e) {}
  }
  if (!p) return 'ERR:no_process';
  try { p.frontmost = true; } catch (e) {}
  delay(0.4);
  var elements;
  try { elements = p.menuBars[0].menuBarItems; }
  catch (e) { return 'ERR:no_menu_bar:' + e; }
  var workspace = pick(elements, ['Workspace', '工作区']);
  if (!workspace) return 'ERR:workspace_not_found';
  var opened = clickDown(workspace, 'Workspace');
  if (typeof opened === 'string') return opened;
  elements = opened;
  var folders = [
    ['Scripts', '脚本'],
    ['Utility', '实用工具', '实用程序'],
    ['FlowStudioAuto']
  ];
  for (var f = 0; f < folders.length; f++) {
    var found = pickScript(elements);
    if (found) {
      try { found.click(); return 'OK:' + String(found.name()); }
      catch (e) { return 'ERR:click:' + target + ':' + e; }
    }
    var folder = pick(elements, folders[f]);
    if (!folder) {
      if (f === 0) return 'ERR:not_found:' + folders[f].join('/');
      return 'ERR:not_found:' + target;
    }
    opened = clickDown(folder, folders[f][0]);
    if (typeof opened === 'string') return opened;
    elements = opened;
  }
  found = pickScript(elements);
  if (!found) return 'ERR:not_found:' + target;
  try { found.click(); return 'OK:' + String(found.name()); }
  catch (e3) { return 'ERR:click:' + target + ':' + e3; }
}
try { console.log(run()); }
catch (e) { console.log('ERR:' + String(e)); }
'''


def script_basename(script_name):
    name = str(script_name or '').strip()
    if name.lower().endswith('.lua'):
        name = name[:-4]
    return name


def macos_menu_source(script_name):
    """JXA source that clicks Workspace → Scripts down to this script."""
    target = script_basename(script_name)
    if not _TARGET_RE.fullmatch(target):
        raise ValueError('达芬奇脚本名称无效。')
    return _MENU_JS.replace('__FLOWSTUDIO_TARGET__', json.dumps(target))


def macos_osascript_command(script_name):
    return ['/usr/bin/osascript', '-l', 'JavaScript', '-e', macos_menu_source(script_name)]


def macos_menu_status(stdout, stderr):
    """Success is an OK: line. macOS 27 has no $.exit, so the exit code is not enough."""
    text = ((stdout or '') + ('\n' + stderr if stderr else '')).strip()
    ok_line = ''
    err_line = ''
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('OK:'):
            ok_line = stripped
        elif stripped.startswith('ERR:'):
            err_line = stripped
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
