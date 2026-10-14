import importlib.util
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
        self.assertTrue(daily.menu_attempt_due(None, 10, False))
        self.assertFalse(daily.menu_attempt_due(10, 17, False))
        self.assertTrue(daily.menu_attempt_due(10, 17, True))
        self.assertTrue(daily.menu_attempt_due(10, 18, False))
        self.assertFalse(daily.menu_attempt_due(10, 34, True, started=True))
        self.assertTrue(daily.menu_attempt_due(10, 35, True, started=True))
        self.assertFalse(daily.menu_attempt_due(10, 80, True, started=True, retried=True))
        ok, message = daily.interpret_menu_output('log\n{"ok": false, "error": "RESOLVE_FOCUS_LOST: 达芬奇窗口没有拿到前台。"}', '')
        self.assertFalse(ok)
        self.assertIn('RESOLVE_FOCUS_LOST', message)
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
        with patch.object(daily, '_run', side_effect=daily.subprocess.TimeoutExpired('menu', 12)):
            ok, message = wake._invoke_bridge_menu()
        self.assertFalse(ok)
        self.assertIn('超时', message)

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


class MacMenuCommandTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('davinci_run_menu_under_test', BASE / 'scripts' / 'davinci_run_menu.py')
        self.menu = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.menu)

    def test_macos_command_embeds_script_name_without_getenv(self):
        command = self.menu.macos_osascript_command('FlowStudio_Resolve_Bridge_v0.5.0.lua')
        self.assertEqual(command[:2], ['/usr/bin/osascript', '-e'])
        source = command[2]
        self.assertIn('"FlowStudio_Resolve_Bridge_v0.5.0"', source)
        self.assertIn('READY:', source)
        self.assertNotIn('ignoring application responses', source)
        self.assertIn('name of menu items', source)
        self.assertIn('FlowStudioAuto', source)
        self.assertNotIn('getenv', source)
        self.assertNotIn('FLOWSTUDIO_SCRIPT_TARGET', source)
        self.assertNotIn('.js', source)
        self.assertNotIn('__FLOWSTUDIO_TARGET__', source)
        self.assertNotIn('$.exit', source)
        self.assertNotIn('byName', source)

    def test_ready_path_clicks_the_script_in_its_own_session(self):
        ready = self.menu.macos_ready(
            'READY:DaVinci Resolve\t工作区\t脚本\t实用工具\tFlowStudioAuto\tFlowStudio_Resolve_Bridge_v1.1.5\n',
            '',
        )
        self.assertEqual(
            ready,
            ('DaVinci Resolve', ['工作区', '脚本', '实用工具', 'FlowStudioAuto', 'FlowStudio_Resolve_Bridge_v1.1.5']),
        )
        self.assertIsNone(self.menu.macos_ready('ERR:no_process\n', ''))
        click = self.menu.macos_click_source('DaVinci Resolve', ready[1])
        self.assertIn('ignoring application responses', click)
        self.assertIn('menu bar item "工作区"', click)
        self.assertIn('click menu item "FlowStudio_Resolve_Bridge_v1.1.5" of menu 1 of currentItem', click)
        self.assertLess(click.index('click currentItem'), click.index('ignoring application responses'))
        self.assertNotIn('getenv', click)
        self.assertNotIn('$.exit', click)
        with patch.object(self.menu.subprocess, 'Popen') as popen:
            output = self.menu.dispatch_macos_click('DaVinci Resolve', ready[1])
        self.assertEqual(output, 'OK:FlowStudio_Resolve_Bridge_v1.1.5')
        args, kwargs = popen.call_args
        self.assertEqual(args[0][:2], ['/usr/bin/osascript', '-e'])
        self.assertTrue(kwargs.get('start_new_session'))
        self.assertIn('ignoring application responses', args[0][2])

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
