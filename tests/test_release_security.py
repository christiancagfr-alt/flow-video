"""Regression checks for the November 2026 release security boundaries."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class ReleaseSecurityTests(unittest.TestCase):
    def test_redaction_covers_provider_errors_and_signed_urls(self):
        from app.services.redaction import redact
        secret = 'synthetic-test-value-123456789'
        value = {'xi-api-key': secret, 'nested': [{'x-goog-api-key': secret}],
                 'error': f'https://example.invalid/?key={secret}&X-Goog-Signature={secret}',
                 'detail': f'{{"api_key": "{secret}"}}'}
        self.assertNotIn(secret, str(redact(value)))
        self.assertEqual(redact({'ok': True, 'count': 3}), {'ok': True, 'count': 3})

    def test_failed_key_health_never_persists_secret(self):
        from app.services import credential_pool
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'health.json'
            secret = 'synthetic-test-value-123456789'
            with patch.object(credential_pool, '_health_path', return_value=path):
                credential_pool.mark_key_status('test', 'test', secret, False, f'?key={secret}')
            self.assertNotIn(secret, path.read_text())

    def test_protected_windows_paths_use_components_and_case(self):
        from app.services.clear_all_history import _is_subpath
        self.assertTrue(_is_subpath(r'C:\Work\Exports\day\final.mp4', r'c:\work\exports'))
        self.assertFalse(_is_subpath(r'C:\Work\Exports-old\clip.mp4', r'C:\Work\Exports'))
        self.assertFalse(_is_subpath(r'D:\Work\Exports\clip.mp4', r'C:\Work\Exports'))
        self.assertFalse(_is_subpath(r'C:\Work\Exports', r'C:\Work\Exports'))

    def test_windows_trash_uses_recycle_bin_and_preserves_on_failure(self):
        from app.services import clear_all_history as history
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / 'clip.mp4'
            file.write_bytes(b'test')
            with patch.object(history, 'os', SimpleNamespace(name='nt')), \
                 patch('PySide6.QtCore.QFile.moveToTrash', return_value=(False, '')) as recycle, \
                 patch.object(history.shutil, 'move') as fallback:
                self.assertFalse(history.move_to_trash(file))
                recycle.assert_called_once_with(str(file))
                fallback.assert_not_called()
            self.assertTrue(file.exists())

    def test_installer_checksum_rejects_under_optimized_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / 'corrupt.exe'
            file.write_bytes(b'not-an-installer')
            code = '''import runpy,sys,subprocess,psutil
from unittest.mock import patch
sys.argv=['install_update.py','--parent','99999999','--file',sys.argv[1],'--sha256','0'*64]
with patch.object(psutil,'Process',side_effect=psutil.NoSuchProcess(99999999)), patch.object(subprocess,'Popen') as launch:
    try:runpy.run_path(%r,run_name='__main__')
    except SystemExit as exc:
        if 'checksum mismatch' not in str(exc):raise
    else:raise RuntimeError('verification was bypassed')
    if launch.called:raise RuntimeError('unverified installer launched')
''' % str(ROOT / 'scripts/install_update.py')
            result = subprocess.run([sys.executable, '-O', '-c', code, str(file)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_packaging_includes_reviewed_npm_lock(self):
        sys.path.insert(0, str(ROOT / 'scripts'))
        try:
            from build_windows_portable import source_files
            paths = {p.relative_to(ROOT).as_posix() for p in source_files()}
            self.assertIn('scripts/remotion-runtime/package-lock.json', paths)
            self.assertFalse(any(p.startswith(('scratch/', 'audit/local-', 'data/')) for p in paths))
        finally:
            sys.path.pop(0)
