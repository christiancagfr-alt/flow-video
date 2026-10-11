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

    def test_lua_modules_load_without_starting_resolve(self):
        self.lua.globals().FLOWSTUDIO_DAILY_TEST=True
        for name in ('FlowStudio_Resolve_Bridge_v0.5.0.lua','FlowStudio_Import_Batch.lua','Autoediting_V1.7_FlowStudio.lua','FlowStudio_Finish_Batch.lua'):
            self.lua.execute((self.root/name).read_text(encoding='utf-8'), name='@'+(self.root/name).as_posix())

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


if __name__=='__main__':unittest.main()
