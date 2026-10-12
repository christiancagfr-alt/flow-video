import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app.services import credential_pool as pool


class Vault:
    def __init__(self): self.values = {}
    def get_password(self, service, name): return self.values.get((service,name))
    def set_password(self, service, name, value): self.values[service,name] = value
    def delete_password(self, service, name): del self.values[service,name]


class ReliabilityTests(unittest.TestCase):
    def test_low_memory_does_not_start_render(self):
        from types import SimpleNamespace
        from scripts.packaging_render import wait_for_memory
        with patch('psutil.virtual_memory',return_value=SimpleNamespace(total=32*1024**3,available=1024**3)):
            with self.assertRaisesRegex(RuntimeError,'内存'):wait_for_memory(timeout=0)
        with patch('psutil.virtual_memory',return_value=SimpleNamespace(total=32*1024**3,available=8*1024**3)):
            wait_for_memory(timeout=0)

    def test_openai_status_does_not_advance_pool(self):
        from app.services import openai_service
        with patch.object(openai_service,'_api_keys',return_value=['first','second']),patch.dict(pool._positions,{},clear=True):
            self.assertEqual(openai_service.get_api_key(),'first')
            self.assertEqual(openai_service.get_api_key(),'first')
            self.assertEqual(openai_service.next_api_key(),'first')
            self.assertEqual(openai_service.next_api_key(),'second')

    def test_render_watchdog_terminates_silent_worker(self):
        import sys
        from scripts.packaging_render import run_render
        with self.assertRaisesRegex(RuntimeError, '进度'):
            run_render([sys.executable,'-c','import time; time.sleep(30)'],str(Path.cwd()),idle_timeout=.1)

    def test_pool_migrates_deduplicates_rotates_and_clears(self):
        vault = Vault(); vault.set_password('test','account','legacy')
        self.assertEqual(pool.read('test','account',vault), ['legacy'])
        pool.save('test','account','one\ntwo\none',vault)
        keys = pool.read('test','account',vault)
        self.assertEqual(keys, ['one','two'])
        self.assertEqual([pool.next_key('test','unique',keys) for _ in range(4)], ['one','two','one','two'])
        pool.clear('test','account',vault)
        self.assertEqual(vault.values,{})

    def test_partial_save_keeps_previous_pool(self):
        vault = Vault(); pool.save('test','account','old',vault)
        original = vault.set_password
        def failing(service, name, value):
            if value=='bad': raise RuntimeError('vault unavailable')
            original(service,name,value)
        with patch.object(vault,'set_password',side_effect=failing):
            with self.assertRaises(RuntimeError): pool.save('test','account','good\nbad',vault)
        self.assertEqual(pool.read('test','account',vault),['old'])

    def test_offline_restore_preserves_installed_components(self):
        from app.services import bundled_components as bundled
        with tempfile.TemporaryDirectory() as temp:
            app=Path(temp)/'app'; data=Path(temp)/'user'
            source=app/'bundled-components/packaging/node';source.mkdir(parents=True)
            (source/'runtime').write_text('bundled')
            (source.parent.parent/'manifest.json').write_text(json.dumps({'components':['node']}))
            with patch.object(bundled,'APP_ROOT',app),patch.object(bundled,'data_dir',return_value=data):
                bundled.restore(('ffmpeg-libs',))
                self.assertFalse((data/'packaging/node').exists())
                bundled.restore()
                installed=data/'packaging/node/runtime'
                self.assertEqual(installed.read_text(),'bundled')
                installed.write_text('upgraded');bundled.restore()
                self.assertEqual(installed.read_text(),'upgraded')

    def test_renderer_limits_resource_usage(self):
        from app.services.remotion_renderer import RemotionRenderer,RemotionStatus
        with tempfile.TemporaryDirectory() as temp:
            renderer=RemotionRenderer(temp)
            Path(temp,renderer.TEMPLATE_DIR).mkdir()
            status=RemotionStatus(ok=True,project_dir=temp,runner='remotion')
            with patch.object(renderer,'prepare_flowstudio_props',return_value=({'codec':'h264'},status)),patch.object(renderer,'_cli',return_value=['node','cli']):
                command,_=renderer.render_flowstudio_command({'_reels_prepared':True},str(Path(temp)/'out.mp4'))
            self.assertEqual(command[command.index('--concurrency')+1],'1')
            self.assertEqual(command[command.index('--offthreadvideo-video-threads')+1],'1')
            self.assertEqual(command[command.index('--offthreadvideo-cache-size-in-bytes')+1],'134217728')
