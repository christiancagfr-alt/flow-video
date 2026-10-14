#!/usr/bin/env python3
"""Click a DaVinci Resolve Workspace script.

Windows uses the menu bar directly and receives the script name as a Python
argument. macOS used to read the name with JXA ``$.getenv(...).js``. On
macOS 27 that ``.js`` read is undefined, so the menu search looks for an item
named "undefined" and exits 3 with ``ERR:not_found:undefined``. The name is
now embedded as a JSON string in the script itself. Linux has no auto-click.
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
if (!target) { console.log('ERR:missing_target'); $.exit(5); }
var se = Application('System Events');
var p;
try { p = se.processes.byName('DaVinci Resolve'); } catch(e) { console.log('ERR:no_process'); $.exit(2); }
function n(x){ try { return String(x.name()); } catch(e) { return ''; } }
function walkMenu(menu, depth) {
  if (depth > 7) return false;
  var items = [];
  try { items = menu.menuItems(); } catch(e) { return false; }
  for (var i=0; i<items.length; i++) {
    var it = items[i];
    var name = n(it);
    if (name === target || name === target + '.lua' || name.indexOf(target) >= 0) {
      try { it.click(); console.log('OK:' + name); return true; } catch(e) {}
    }
    try {
      var subs = it.menus();
      for (var j=0; j<subs.length; j++) if (walkMenu(subs[j], depth+1)) return true;
    } catch(e) {}
  }
  return false;
}
try {
  p.frontmost = true;
  delay(0.3);
  var bars = p.menuBars();
  if (!bars.length) throw 'no_menu_bar';
  var top = bars[0].menuBarItems();
  var workspace = null;
  for (var i=0; i<top.length; i++) {
    var name = n(top[i]);
    if (name === 'Workspace' || name === '工作区') { workspace = top[i]; break; }
  }
  if (!workspace) throw 'workspace_not_found';
  var menus = workspace.menus();
  for (var m=0; m<menus.length; m++) {
    if (walkMenu(menus[m], 0)) $.exit(0);
  }
  console.log('ERR:not_found:' + target);
  $.exit(3);
} catch(e) { console.log('ERR:' + String(e)); $.exit(4); }
'''


def script_basename(script_name):
    name = str(script_name or '').strip()
    if name.lower().endswith('.lua'):
        name = name[:-4]
    return name


def macos_menu_source(script_name):
    """JXA source that searches Workspace for this script. The name is a JSON literal."""
    target = script_basename(script_name)
    if not _TARGET_RE.fullmatch(target):
        raise ValueError('达芬奇脚本名称无效。')
    return _MENU_JS.replace('__FLOWSTUDIO_TARGET__', json.dumps(target))


def macos_osascript_command(script_name):
    return ['/usr/bin/osascript', '-l', 'JavaScript', '-e', macos_menu_source(script_name)]


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
    out = ((p.stdout or '') + ('\n' + p.stderr if p.stderr else '')).strip()
    print(json.dumps({'ok': p.returncode == 0, 'output': out, 'returncode': p.returncode}, ensure_ascii=False))
    return p.returncode


if __name__ == '__main__':
    raise SystemExit(main())
