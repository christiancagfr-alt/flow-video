import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

BASE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('windows_runtime', BASE/'scripts/windows_resolve_runtime.py')
runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime)

@unittest.skipUnless(os.name=='nt','Windows native integration')
class WindowsLuaTests(unittest.TestCase):
    def setUp(self):
        from lupa.luajit21 import LuaRuntime
        self.temp=tempfile.TemporaryDirectory(prefix='flow-win-lua-')
        self.root=Path(self.temp.name)
        for p in (BASE/'davinci_autoedit_v0_5_0').glob('*.lua'): shutil.copy2(p,self.root/p.name)
        helper=BASE/'scripts/windows_resolve_runtime.py'
        (self.root/'windows-runtime.ini').write_text(f'python={Path(sys.executable).as_posix()}\nhelper={helper.as_posix()}\n',encoding='utf-8')
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.platform=self.lua.execute((self.root/'FlowStudio_Platform.lua').read_text(encoding='utf-8'),name='@'+(self.root/'FlowStudio_Platform.lua').as_posix())
        self.lua.globals().platform=self.platform
    def tearDown(self):
        self.lua=None;self.platform=None
        self.temp.cleanup()

    def test_unicode_io_and_atomic_replace(self):
        self.assertTrue(self.platform.windows)
        target=self.root/'中文 空格.txt'
        self.lua.globals().target=target.as_posix()
        self.lua.execute("local f=assert(platform.io.open(target,'wb'));f:write('first');f:close();local g=assert(platform.io.open(target..'.tmp','wb'));g:write('second');g:close();assert(platform.os.rename(target..'.tmp',target));local r=assert(platform.io.open(target,'rb'));assert(r:read('*a')=='second');r:close()")
        self.assertEqual(target.read_text(),'second')

    def test_hidden_process_and_sorted_job_listing(self):
        folder=self.root/'中文 jobs'
        self.assertEqual(self.platform.os.execute("mkdir -p '"+folder.as_posix()+"'"),0)
        (folder/'b.job').write_text('b');(folder/'a.job').write_text('a')
        code,text=self.platform.rpc("find '"+folder.as_posix()+"' -maxdepth 1 -type f -name \"*.job\" -print | sort")
        self.assertEqual(code,0);self.assertEqual(text.splitlines(),[(folder/'a.job').as_posix(),(folder/'b.job').as_posix()])
        output=self.root/'probe.out';error=self.root/'probe.err'
        cmd="'"+Path(sys.executable).as_posix()+"' -c 'import ctypes; print(ctypes.windll.kernel32.GetConsoleWindow())' > '"+output.as_posix()+"' 2> '"+error.as_posix()+"'"
        self.assertEqual(self.platform.os.execute(cmd),0)
        self.assertEqual(output.read_text().strip(),'0')

    def test_popen_lines_are_real_paths_and_errors_can_be_archived(self):
        folder=self.root/'任务 jobs';folder.mkdir()
        task=folder/'a.job';task.write_text('request_id=abc\naction=PREPARE_DAILY\n')
        self.lua.globals().folder=folder.as_posix()
        self.lua.execute("local p=assert(platform.io.popen(\"find '\"..folder..\"' -maxdepth 1 -type f -name \\\"*.job\\\" -print | sort\"));for path in p:lines() do local f=assert(platform.io.open(path,'r'),path);assert(f:read('*l')=='request_id=abc');f:close();local e=assert(platform.io.open(path..'.txt','w'));e:write('test error');e:close() end;p:close()")
        self.assertEqual(task.with_suffix('.job.txt').read_text(),'test error')
        # Also tolerate CRLF replies from an already-installed older helper.
        self.lua.execute("platform.rpc=function() return 0, 'first\\r\\nsecond\\r\\n' end;local p=platform.io.popen('test');assert(p:read('*l')=='first');assert(p:read('*l')=='second');assert(p:read('*l')==nil)")

    def test_lua_modules_load_without_starting_resolve(self):
        self.lua.globals().FLOWSTUDIO_DAILY_TEST=True
        for name in ('FlowStudio_Resolve_Bridge_v0.5.0.lua','FlowStudio_Import_Batch.lua','Autoediting_V1.7_FlowStudio.lua','FlowStudio_Finish_Batch.lua'):
            self.lua.execute((self.root/name).read_text(encoding='utf-8'), name='@'+(self.root/name).as_posix())

    def test_bridge_loads_when_resolve_hides_debug_and_package(self):
        from lupa.luajit21 import LuaRuntime
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute("debug = nil; package = nil; jit = nil; ffi = nil; os.getenv = function() return '' end")
        platform = lua.execute((self.root / 'FlowStudio_Platform.lua').read_text(encoding='utf-8'), name='@' + (self.root / 'FlowStudio_Platform.lua').as_posix())
        self.assertEqual(platform.windows, False)
        lua.globals().FLOWSTUDIO_DAILY_TEST = True
        script = self.root / 'FlowStudio_Resolve_Bridge_v0.5.0.lua'
        prepare, _acquire = lua.execute(script.read_text(encoding='utf-8'), name='@' + script.as_posix())
        self.assertIsNotNone(prepare)

    def test_platform_uses_bridge_directory_when_console_hides_debug(self):
        from lupa.luajit21 import LuaRuntime
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute('debug = nil; package = nil')
        lua.globals()["__FLOWSTUDIO_PLATFORM_DIRECTORY"] = self.root.as_posix()
        platform = lua.execute(
            (self.root / 'FlowStudio_Platform.lua').read_text(encoding='utf-8'),
            name='=(Resolve Console)',
        )
        self.assertTrue(platform.windows)
        self.assertEqual(platform.directory, self.root.as_posix())

    def test_bridge_passes_its_directory_when_console_hides_debug(self):
        from lupa.luajit21 import LuaRuntime
        profile = self.root / 'console-user'
        script_dir = profile / 'AppData/Roaming/Blackmagic Design/DaVinci Resolve/Support/Fusion/Scripts/Utility/FlowStudioAuto'
        script_dir.mkdir(parents=True)
        shutil.copy2(self.root / 'FlowStudio_Platform.lua', script_dir / 'FlowStudio_Platform.lua')
        shutil.copy2(self.root / 'windows-runtime.ini', script_dir / 'windows-runtime.ini')
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute("ffi = require('ffi'); debug = nil; package = nil")
        lua.globals()['test_profile'] = profile.as_posix()
        lua.execute(r"""
            local nativeGetenv = os.getenv
            os.getenv = function(key)
                if key == 'HOME' then return '' end
                if key == 'USERPROFILE' then return test_profile end
                if key == 'APPDATA' then return test_profile .. '/AppData/Roaming' end
                if key == 'OS' then return 'Windows_NT' end
                return nativeGetenv(key)
            end
            FLOWSTUDIO_DAILY_TEST = true
        """)
        script = self.root / 'FlowStudio_Resolve_Bridge_v0.5.0.lua'
        lua.execute(script.read_text(encoding='utf-8'), name='=(Resolve Console)')
        platform = lua.globals()['__FLOWSTUDIO_PLATFORM']
        self.assertTrue(platform.windows)
        self.assertEqual(platform.directory, script_dir.as_posix())

    def test_windows_bridge_processes_daily_job_and_keeps_heartbeating(self):
        bridge=self.root/'Documents/FlowStudioResolveBridge'
        commands=bridge/'v0_5_0/commands';commands.mkdir(parents=True)
        (commands/'a.job').write_text('request_id=abc\naction=BAD\n')
        (commands/'b.job').write_text('request_id=def\naction=PREPARE_DAILY\nwork_date=2026-10-12\ntimeline_fps=25\n')
        self.lua.globals().test_home=self.root.as_posix()
        self.lua.execute(r"""
            local nativeGetenv=platform.os.getenv
            platform.os.getenv=function(key) if key=='HOME' then return test_home end;return nativeGetenv(key) end
            local execute=platform.os.execute
            ticks=0
            platform.os.execute=function(command)
                if command=='/bin/sleep 1' then
                    ticks=ticks+1
                    if ticks==3 then local f=assert(platform.io.open(test_home..'/Documents/FlowStudioResolveBridge/v0_5_0/STOP','w'));f:close() end
                    return 0
                end
                return execute(command)
            end
            local settings={};local timelineSettings={timelineFrameRate='25'}
            local timeline={GetName=function() return 'MAIN-2026-10-12' end,SetSetting=function(_,k,v) timelineSettings[k]=v;return true end,GetSetting=function(_,k) return timelineSettings[k] end}
            local project={GetName=function() return 'FlowStudio-2026-10-12' end,SetSetting=function(_,k,v) settings[k]=v;return true end,GetSetting=function(_,k) return settings[k] end,GetTimelineCount=function() return 0 end,SetCurrentTimeline=function() return true end,GetCurrentTimeline=function() return timeline end,GetMediaPool=function() return {CreateEmptyTimeline=function() return timeline end} end}
            local current=nil
            local pm={GetCurrentProject=function() return current end,GotoRootFolder=function() return true end,GetProjectListInCurrentFolder=function() return {} end,CreateProject=function() current=project;return project end,SaveProject=function() return true end}
            resolve={GetProjectManager=function() return pm end,GetVersionString=function() return 'test' end}
        """)
        script=self.root/'FlowStudio_Resolve_Bridge_v0.5.0.lua'
        self.lua.execute(script.read_text('utf-8'),name='@'+script.as_posix())
        self.assertTrue((bridge/'v0_5_0/done/b.job').is_file())
        self.assertTrue((bridge/'v0_5_0/error/a.job.txt').is_file())
        self.assertIn('stage=READY',(bridge/'logs/bridge.log').read_text('utf-8'))
        self.assertEqual(self.lua.globals().ticks,3)

    def test_exclusive_directory_lock(self):
        folder=self.root/'instance.lock'
        cmd="mkdir '"+folder.as_posix()+"' 2>/dev/null"
        self.assertEqual(self.platform.os.execute(cmd),0)
        self.assertNotEqual(self.platform.os.execute(cmd),0)
        self.assertEqual(self.platform.os.execute("rmdir '"+folder.as_posix()+"' 2>/dev/null"),0)

class CommandTests(unittest.TestCase):
    def test_unknown_shell_commands_rejected(self):
        with self.assertRaises(ValueError):runtime.dispatch('cmd /c echo unexpected')

    def test_background_launch_parsed_without_shell(self):
        command="('C:/Python/python.exe' 'C:/中文 files/run.py' '--wav' 'C:/audio one.wav' > 'C:/audio one.log' 2>&1 & echo $! > 'C:/audio one.pid')"
        with patch.object(runtime,'launch_owned',return_value='') as launch:
            runtime.dispatch(command)
            self.assertEqual(launch.call_args.args,(['C:/Python/python.exe','C:/中文 files/run.py','--wav','C:/audio one.wav'],'C:/audio one.log','C:/audio one.pid'))

class ResolveDiscoveryTests(unittest.TestCase):
    def test_custom_install_folder_and_stale_configuration(self):
        from app.services import resolve_windows_paths as paths
        with tempfile.TemporaryDirectory() as folder:
            exe=Path(folder)/'Resolve.exe';exe.write_bytes(b'test')
            with patch.object(paths,'registry_candidates',return_value=iter([folder])):
                self.assertEqual(paths.find_executable(str(Path(folder)/'missing.exe')),exe)
            with patch.object(paths,'registry_candidates',return_value=iter([])):
                self.assertEqual(paths.find_executable(str(exe)),exe)

    @unittest.skipUnless(os.name=='nt','Windows script installation')
    def test_helper_installed_outside_resolve_script_menu(self):
        from app.services import resolve_daily as daily
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);menu=root/'Scripts/Utility/FlowStudioAuto';menu.mkdir(parents=True)
            legacy=menu/'windows_resolve_runtime.py';legacy.write_text('old internal helper')
            with patch.object(daily,'script_dir',return_value=menu),patch.object(daily,'bridge_root',return_value=root/'bridge'),patch.object(daily,'snapshot',return_value={'alive':False}):
                self.assertTrue(daily.install_bridge())
                self.assertFalse(legacy.exists())
                config=daily.read_pairs(menu/'windows-runtime.ini')
                self.assertEqual(Path(config['helper']),root/'bridge/runtime/windows_resolve_runtime.py')
                self.assertTrue(Path(config['helper']).is_file())
                self.assertFalse(daily.install_bridge())


class ResolveConsoleTests(unittest.TestCase):
    def test_bridge_console_command_is_scoped_to_a_versioned_local_bridge_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'FlowStudio_Resolve_Bridge_v1.0.0.lua'
            line = runtime.console_dofile_line(path)
            self.assertEqual(line, 'dofile([[' + path.resolve().as_posix() + ']])')
            with self.assertRaisesRegex(ValueError, 'INVALID_BRIDGE_SCRIPT_PATH'):
                runtime.console_dofile_line(path.with_name('untrusted.lua'))

    def test_console_launcher_opens_workspace_console_and_types_without_clipboard(self):
        from types import ModuleType

        class Window:
            handle = 123
            def __init__(self):
                self.edit = type('Edit', (), {
                    'is_visible': lambda self: True,
                    'is_enabled': lambda self: True,
                    'rectangle': lambda self: type('Rect', (), {'bottom': 100, 'width': lambda self: 200, 'height': lambda self: 24})(),
                    'set_focus': lambda self: None,
                    'click_input': lambda self, **_kwargs: None,
                })()
            def descendants(self, control_type=None):
                return [self.edit] if control_type == 'Edit' else []

        keyboard = ModuleType('pywinauto.keyboard')
        sent_keys = []
        keyboard.send_keys = lambda value, **_kwargs: sent_keys.append(value)
        pywinauto = ModuleType('pywinauto')
        pywinauto.keyboard = keyboard
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / 'FlowStudio_Resolve_Bridge_v1.0.0.lua'
            with patch.dict(sys.modules, {'pywinauto': pywinauto, 'pywinauto.keyboard': keyboard}), \
                    patch.object(runtime, 'menu_path', return_value=123) as menu, \
                    patch.object(runtime, '_resolve_console_window', return_value=Window()), \
                    patch.object(runtime, 'foreground_is', return_value=True), \
                    patch.object(runtime, 'foreground_window_is', return_value=True), \
                    patch.object(runtime, '_send_unicode_text') as type_text, \
                    patch.object(runtime.time, 'sleep'):
                result = runtime.invoke_console_dofile(script.name, script)
            self.assertEqual(result, 'OK:console')
            self.assertEqual(menu.call_args.args[0], [('Workspace', '工作区'), ('Console', '控制台')])
            self.assertEqual(menu.call_args.args[1], None)
            type_text.assert_called_once_with('dofile([[' + script.resolve().as_posix() + ']])')
            self.assertEqual(sent_keys, ['^{END}', '{ENTER}'])

class WhisperRangeTests(unittest.TestCase):
    def test_retry_start_zero_crops_the_requested_range(self):
        import wave
        from types import SimpleNamespace
        spec=importlib.util.spec_from_file_location('whisper_runner', BASE/'scripts/run_batch_whisper.py')
        runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);wav=root/'audio.wav';output=root/'retry'
            with wave.open(str(wav),'wb') as audio:
                audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(16000);audio.writeframes(bytes(16000*2*3))
            def launch(args,**kwargs):
                with wave.open(args[args.index('-f')+1],'rb') as audio:
                    self.assertEqual(audio.getnframes(),16000)
                output.with_suffix('.srt').write_text('valid test result')
                return SimpleNamespace(wait=lambda timeout:0)
            args=SimpleNamespace(output=str(output),wav=str(wav),language='sw',start=0.0,duration=1.0,fps=25,cli='test-cli',model='test-model',timeout=3)
            with patch.object(runner.subprocess,'Popen',side_effect=launch):self.assertEqual(runner.run(args),0)
            self.assertFalse(output.with_suffix('.crop.wav').exists())


class MenuWalkTests(unittest.TestCase):
    def _item(self, label, children=()):
        item = type('Item', (), {})()
        item.label = label
        item.kids = list(children)
        item.actions = []
        item.descendants_called = False
        def window_text():
            return label
        def is_visible():
            return True
        def children(control_type=None):
            if control_type == 'MenuItem':
                return list(item.kids)
            return []
        def descendants(**kwargs):
            item.descendants_called = True
            raise AssertionError('menu walk must not scan the whole Resolve tree')
        def expand():
            raise RuntimeError('no expand')
        def invoke():
            item.actions.append('invoke')
        item.window_text = window_text
        item.is_visible = is_visible
        item.children = children
        item.descendants = descendants
        item.expand = expand
        item.invoke = invoke
        return item

    def test_menu_walk_clicks_only_the_open_branch(self):
        leaf = self._item('FlowStudio_Resolve_Bridge_v0.5.0')
        folder = self._item('FlowStudioAuto', [leaf])
        utility = self._item('Utility', [folder])
        scripts = self._item('Scripts', [utility])
        workspace = self._item('Workspace', [scripts])
        bar = self._item('menu bar', [workspace])
        window = self._item('DaVinci Resolve')
        def window_children(control_type=None):
            if control_type == 'MenuBar':
                return [bar]
            return []
        window.children = window_children
        window.handle = 70
        app = type('App', (), {'windows': lambda self: []})()
        with patch.object(runtime, 'resolve_window', return_value=(app, window, 7)), patch.object(runtime, 'foreground_is', return_value=False), patch.object(runtime, 'force_foreground'):
            runtime.menu_path([('Workspace','工作区'), ('Scripts','脚本'), ('Utility','实用工具'), ('FlowStudioAuto',), ('FlowStudio_Resolve_Bridge_v0.5.0','FlowStudio_Resolve_Bridge_v0.5.0.lua')])
        self.assertEqual(leaf.actions, ['invoke'])
        self.assertFalse(leaf.descendants_called)

    def test_ambiguous_menu_item_is_rejected(self):
        window = self._item('DaVinci Resolve', [self._item('Workspace'), self._item('Workspace')])
        window.handle = 1
        app = type('App', (), {'windows': lambda self: []})()
        with patch.object(runtime, 'resolve_window', return_value=(app, window, 7)), patch.object(runtime, 'foreground_is', return_value=True):
            with self.assertRaisesRegex(RuntimeError, 'RESOLVE_MENU_NOT_FOUND'):
                runtime.menu_path([('Workspace',)])

    def test_largest_visible_window_is_selected(self):
        self.assertEqual(runtime.pick_resolve_window([(10, 1, 11), (0, 2, 22), (90, 3, 33)]), (90, 3, 33))
        self.assertIsNone(runtime.pick_resolve_window([(0, 1, 11), (12, 2, 0)]))

    @unittest.skipUnless(os.name == 'nt', 'Windows window enumeration')
    def test_window_enumeration_does_not_crash(self):
        found = runtime.resolve_windows()
        self.assertIsInstance(found, list)
        for area, pid, hwnd in found:
            self.assertGreater(area, 0)
            self.assertGreater(pid, 0)
            self.assertGreater(hwnd, 0)


class WakeStatusTests(unittest.TestCase):
    def test_retry_and_status_text(self):
        from app.services import resolve_daily as daily
        self.assertIn('没有识别到达芬奇 Lua>', daily.menu_failure_text('RESOLVE_CONSOLE_INPUT_NOT_FOUND'))
        self.assertIn('没有成功输入', daily.menu_failure_text('RESOLVE_CONSOLE_INPUT_FAILED'))
        self.assertIn('没有可操作的主窗口', daily.menu_failure_text('RESOLVE_MAIN_WINDOW_NOT_READY'))
        self.assertIn('没有可操作的主窗口', daily.menu_error(daily.menu_failure_text('RESOLVE_MAIN_WINDOW_NOT_READY')))
        self.assertIn('脚本菜单层级', daily.menu_error('已找到达芬奇主窗口，但脚本菜单层级与当前版本不一致。'))
        self.assertTrue(daily.menu_attempt_due(None, 10, False))
        self.assertFalse(daily.menu_attempt_due(10, 17, False))
        self.assertTrue(daily.menu_attempt_due(10, 17, True))
        self.assertTrue(daily.menu_attempt_due(10, 18, False))
        self.assertFalse(daily.menu_attempt_due(10, 34, True, started=True))
        self.assertTrue(daily.menu_attempt_due(10, 35, True, started=True))
        self.assertFalse(daily.menu_attempt_due(10, 80, True, started=True, retried=True))
        ok, message = daily.interpret_menu_output('log\n{"ok": false, "error": "RESOLVE_FOCUS_LOST: 达芬奇窗口没有拿到前台。"}', '')
        self.assertFalse(ok)
        self.assertIn('达芬奇窗口没有到前台', message)
        self.assertTrue(daily.menu_error(message))
        ok, message = daily.interpret_menu_output('{"ok": true, "output": "ok"}', '')
        self.assertTrue(ok)
        self.assertEqual(message, '')
        whisper = '请在组件管理中填写可执行的 whisper.cpp 命令路径，或点击“检测 / 安装 whisper.cpp”。'
        disconnected = {'alive': False, 'version': '0.5.0', 'project': 'FlowStudio-2026-10-13', 'timeline': 'MAIN-2026-10-13'}
        text = daily.connection_status_text(disconnected, whisper)
        self.assertIn('请重新唤醒', text)
        self.assertIn('whisper.cpp', text)
        self.assertNotIn('请在组件管理中填写可执行的', text)
        self.assertIn('RESOLVE_FOCUS_LOST', daily.connection_status_text(disconnected, 'RESOLVE_FOCUS_LOST: 没拿到前台'))

    def test_menu_timeout_stays_a_retry_instead_of_aborting(self):
        from app.services import resolve_daily as daily
        wake = daily.DailyWake('25', root=Path('.'), day='2026-10-13')
        with patch.object(daily.sys, 'platform', 'win32'), patch.object(daily, '_run', side_effect=daily.subprocess.TimeoutExpired('menu', 12)):
            ok, message = wake._invoke_bridge_menu()
        self.assertFalse(ok)
        self.assertIn('超时', message)

    def test_mac_menu_timeout_is_not_killed_or_clicked_again(self):
        from app.services import resolve_daily as daily
        wake = daily.DailyWake('25', root=Path('.'), day='2026-10-13')

        class Proc:
            def communicate(self, timeout=None):
                raise daily.subprocess.TimeoutExpired('menu', timeout or 12)

            def kill(self):
                raise AssertionError('the menu process must keep running')

        with patch.object(daily.sys, 'platform', 'darwin'), patch.object(daily.subprocess, 'Popen', return_value=Proc()):
            ok, message = wake._invoke_bridge_menu()
        self.assertTrue(ok)
        self.assertIn('不再重复点击', message)

    def test_empty_state_file_is_described_as_unreadable(self):
        from app.services import resolve_daily as daily
        root = Path(tempfile.mkdtemp(prefix='flow-state-'))
        try:
            (root / 'bridge_state.ini').write_text('', encoding='utf-8')
            (root / 'bridge_heartbeat.txt').write_text('1', encoding='utf-8')
            reason = daily.bridge_wait_reason(root)
            self.assertIn('状态文件无法读取', reason)
            self.assertNotIn('达芬奇没有执行脚本', reason)
        finally:
            shutil.rmtree(root)

    def test_wake_creates_the_bridge_folders_before_the_script_runs(self):
        from app.services import resolve_daily as daily
        root = Path(tempfile.mkdtemp(prefix='flow-bridge-dirs-'))
        try:
            daily.ensure_bridge_dirs(root)
            self.assertTrue((root / 'v0_5_0' / 'commands').is_dir())
            self.assertTrue((root / 'logs').is_dir())
            daily.ensure_bridge_dirs(root)
        finally:
            shutil.rmtree(root)

    def test_bridge_startup_does_not_shell_out_on_macos(self):
        text = (BASE / 'davinci_autoedit_v0_5_0' / 'FlowStudio_Resolve_Bridge_v0.5.0.lua').read_text(encoding='utf-8')
        self.assertNotIn('osascript', text)
        self.assertNotIn('id -P', text)
        self.assertIn('posixMkdir', text)
        self.assertIn("bootWrite('ENTER')", text)
        self.assertIn("rawget(_G, 'ffi')", text)
        self.assertIn('installSandboxIo', text)
        self.assertIn('io-from-ffi', text)
        self.assertIn('fchmod', text)
        self.assertIn('lib.cdef(line)', text)
        self.assertNotIn('cdef[[', text)
        self.assertIn("noteFailure('BOOT '", text)

    def test_wait_reason_names_the_missing_heartbeat(self):
        from app.services import resolve_daily as daily
        root = Path(tempfile.mkdtemp(prefix='flow-bridge-wait-'))
        try:
            reason = daily.bridge_wait_reason(root)
            self.assertIn('没有状态文件', reason)
            self.assertIn('没有心跳文件', reason)
            self.assertIn(str(root), reason)
            log = root / 'logs'
            log.mkdir()
            (log / 'bridge.log').write_text('2026-10-14 00:00:00 START home=/Users/test\n', encoding='utf-8')
            (root / 'bridge_state.ini').write_text('version=0.5.0\nstage=OFFLINE\nupdated_at=1\ndetail=HOME unavailable\n', encoding='utf-8')
            reason = daily.bridge_wait_reason(root)
            self.assertIn('OFFLINE', reason)
            self.assertIn('上次记录：HOME unavailable', reason)
            self.assertIn('START home=/Users/test', reason)
            folder = Path(tempfile.mkdtemp(prefix='flow-boot-'))
            (folder / 'flowstudio-bridge-boot.txt').write_text('BOOT /Users/hauhua/Library\n', encoding='utf-8')
            try:
                with patch.object(daily, 'script_dir', return_value=folder):
                    booted = daily.bridge_wait_reason(root)
                self.assertIn('脚本已启动', booted)
                self.assertIn('BOOT /Users/hauhua/Library', booted)
            finally:
                shutil.rmtree(folder)
        finally:
            shutil.rmtree(root)

    def test_bridge_menu_name_follows_the_app_version_and_old_names_are_removed(self):
        from app.version import VERSION
        from app.services import resolve_daily as daily
        self.assertEqual(daily.SCRIPT, f'FlowStudio_Resolve_Bridge_v{VERSION}.lua')
        self.assertTrue((daily.BASE / 'davinci_autoedit_v0_5_0' / daily.BRIDGE_SOURCE).is_file())
        folder = Path(tempfile.mkdtemp(prefix='flow-bridge-names-'))
        try:
            current = folder / daily.SCRIPT
            current.write_text('current', encoding='utf-8')
            (folder / 'FlowStudio_Resolve_Bridge_v0.5.0.lua').write_text('old', encoding='utf-8')
            (folder / 'FlowStudio_Resolve_Bridge_v1.0.0.lua').write_text('previous', encoding='utf-8')
            (folder / 'FlowStudio_Import_Batch.lua').write_text('keep', encoding='utf-8')
            (folder / 'notes.lua').write_text('keep', encoding='utf-8')
            removed = daily.retire_old_bridge_scripts(folder, daily.SCRIPT)
            self.assertCountEqual(removed, ['FlowStudio_Resolve_Bridge_v0.5.0.lua', 'FlowStudio_Resolve_Bridge_v1.0.0.lua'])
            self.assertEqual(current.read_text(encoding='utf-8'), 'current')
            self.assertEqual((folder / 'FlowStudio_Import_Batch.lua').read_text(encoding='utf-8'), 'keep')
            self.assertEqual((folder / 'notes.lua').read_text(encoding='utf-8'), 'keep')
        finally:
            shutil.rmtree(folder)

    def test_macos_undefined_target_is_chinese_not_raw_json(self):
        from app.services import resolve_daily as daily
        raw = '{"ok": false, "output": "ERR:not_found:undefined", "returncode": 3}'
        ok, message = daily.interpret_menu_output(raw, '')
        self.assertFalse(ok)
        self.assertNotIn('undefined', message)
        self.assertNotIn('{', message)
        self.assertIn('脚本名称', message)
        ok, message = daily.interpret_menu_output('{"ok": false, "output": "ERR:no_process", "returncode": 2}', '')
        self.assertIn('没有找到正在运行的达芬奇', message)
        ok, message = daily.interpret_menu_output('{"ok": false, "output": "ERR:not_found:FlowStudio_Resolve_Bridge_v0.5.0", "returncode": 3}', '')
        self.assertIn('没有找到 Bridge', message)
        self.assertNotIn('undefined', message)
        ok, message = daily.interpret_menu_output('{"ok": false, "output": "ERR:not_found:Scripts|saw:文件,编辑,工作区", "returncode": 0}', '')
        self.assertIn('没有「脚本」', message)
        self.assertIn('文件', message)
        raw_exit = '{"ok": false, "output": "ERR:Error: 不能获取对象。\\nexecution error: Error: TypeError: $.exit is not a function. (In \'$.exit(4)\', \'$.exit\' is undefined) (-2700)", "returncode": 1}'
        ok, message = daily.interpret_menu_output(raw_exit, '')
        self.assertFalse(ok)
        self.assertIn('辅助功能', message)
        self.assertNotIn('$.exit', message)
        self.assertNotIn('TypeError', message)
        ok, message = daily.interpret_menu_output('{"ok": false, "output": "ERR:no_console", "returncode": 1}', '')
        self.assertFalse(ok)
        self.assertIn('控制台', message)
        self.assertNotIn('no_console', message)
        ok, message = daily.interpret_menu_output('{"ok": false, "output": "ERR:console_not_focused:Edit", "returncode": 1}', '')
        self.assertIn('避免打到时间线', message)
        ok, message = daily.interpret_menu_output('{"ok": false, "error": "No module named \'windows_resolve_runtime\'"}', '')
        self.assertIn('唤醒组件', message)
        self.assertNotIn('No module named', message)
        raw = '{"ok": false, "output": "ERR:Error: 发生错误。", "returncode": 4}\nexecution error: Error: 发生错误。 (4)'
        ok, message = daily.interpret_menu_output(raw, '')
        self.assertFalse(ok)
        self.assertIn('控制台', message)
        self.assertNotIn('{"ok"', message)


class MacMenuCommandTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('davinci_run_menu_under_test', BASE / 'scripts' / 'davinci_run_menu.py')
        self.menu = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.menu)

    def test_macos_command_types_dofile_into_the_console(self):
        path = '/Users/hauhua/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/FlowStudioAuto/FlowStudio_Resolve_Bridge_v1.1.11.lua'
        command = self.menu.macos_osascript_command('FlowStudio_Resolve_Bridge_v1.1.11.lua', path)
        self.assertEqual(command[:2], ['/usr/bin/osascript', '-e'])
        source = command[2]
        self.assertIn('dofile(\'' + path + '\')', source)
        self.assertIn('set the clipboard to luaLine', source)
        self.assertIn('keystroke "v" using command down', source)
        self.assertIn('keystroke return', source)
        self.assertIn('控制台', source)
        self.assertIn('TYPE_DOFILE', source)
        self.assertLess(source.index('TYPE_DOFILE'), source.index('keystroke return'))
        self.assertIn('console_not_focused', source)
        self.assertIn('/tmp/flowstudio-menu-click.log', source)
        self.assertNotIn('ignoring application responses', source)
        self.assertNotIn('click at', source)
        self.assertFalse(hasattr(self.menu, '_MENU_APPLESCRIPT'))
        self.assertNotIn('start_new_session', source)
        self.assertNotIn('getenv', source)
        self.assertNotIn('__FLOWSTUDIO_LINE__', source)
        self.assertNotIn('$.exit', source)
        self.assertNotIn('return w', source)
        self.assertIn('consoleIndex', source)
        self.assertIn('Cls', source)
        self.assertIn('click menu bar item barName', source)

    def test_windows_helper_loads_when_python_omits_the_script_directory(self):
        source = (BASE / 'scripts' / 'davinci_run_menu.py').read_text(encoding='utf-8')
        self.assertNotIn('from windows_resolve_runtime import', source)
        folder = Path(tempfile.mkdtemp(prefix='flow-menu-import-'))
        env = os.environ.copy()
        env['PYTHONSAFEPATH'] = '1'
        env.pop('PYTHONPATH', None)
        env['FLOWSTUDIO_DATA_DIR'] = str(folder)
        probe = '\n'.join([
            'import importlib.util, json, sys',
            'from pathlib import Path',
            'script = Path(sys.argv[1])',
            'sys.path = [item for item in sys.path if Path(item or ".").resolve() != script.parent.resolve()]',
            'spec = importlib.util.spec_from_file_location("menu_isolated", script)',
            'module = importlib.util.module_from_spec(spec)',
            'spec.loader.exec_module(module)',
            'print(json.dumps({"ok": callable(module.load_windows_menu())}))',
        ])
        import subprocess
        completed = subprocess.run(
            [sys.executable, '-c', probe, str(BASE / 'scripts' / 'davinci_run_menu.py')],
            capture_output=True, text=True, env=env, cwd=folder,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout.strip().splitlines()[-1])['ok'], True)

    def test_macos_result_uses_ok_line_instead_of_exit_code(self):
        failed = self.menu.macos_result('ERR:not_found:FlowStudio_Resolve_Bridge_v0.5.0\n', '', 0)
        self.assertFalse(failed['ok'])
        self.assertEqual(failed['output'], 'ERR:not_found:FlowStudio_Resolve_Bridge_v0.5.0')
        wrapped = self.menu.macos_result('', 'execution error: ERR:not_found:Scripts|saw:文件 (-2700)', 1)
        self.assertFalse(wrapped['ok'])
        self.assertEqual(wrapped['output'], 'ERR:not_found:Scripts|saw:文件')
        clicked = self.menu.macos_result('OK:FlowStudio_Resolve_Bridge_v0.5.0\n', '', 0)
        self.assertTrue(clicked['ok'])

    def test_macos_command_rejects_a_name_that_could_break_the_script(self):
        with self.assertRaises(ValueError):
            self.menu.macos_osascript_command('bad"; $.exit(0);//.lua')


if __name__=='__main__':unittest.main()
