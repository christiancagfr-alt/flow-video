#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from app.services import quiet_process as subprocess


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--script-name', required=True)
    args = ap.parse_args()
    if sys.platform.startswith('linux'):
        print(json.dumps({'ok':False,'error':'Linux 请在达芬奇 工作区 → 脚本 菜单手动运行对应脚本。'},ensure_ascii=False));return 1
    target = args.script_name.rsplit('.', 1)[0]
    # JXA recursively searches the Workspace/工作区 -> Scripts/脚本 menu tree.
    js = r'''
ObjC.import('stdlib');
var target = $.getenv('FLOWSTUDIO_SCRIPT_TARGET').js;
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
    env = dict(__import__('os').environ)
    env['FLOWSTUDIO_SCRIPT_TARGET'] = target
    if sys.platform == 'win32':
        try:
            from windows_resolve_runtime import invoke_menu
            output = invoke_menu(args.script_name)
            print(json.dumps({'ok': True, 'output': output}))
            return 0
        except Exception as exc:
            print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=True))
            return 1
    p = subprocess.run(['/usr/bin/osascript', '-l', 'JavaScript', '-e', js], env=env, capture_output=True, text=True)
    out = ((p.stdout or '') + ('\n' + p.stderr if p.stderr else '')).strip()
    print(json.dumps({'ok': p.returncode == 0, 'output': out, 'returncode': p.returncode}, ensure_ascii=False))
    return p.returncode


if __name__ == '__main__':
    raise SystemExit(main())
