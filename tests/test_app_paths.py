import os, unittest
from pathlib import Path
from unittest.mock import patch
from app.services import app_paths
class AppPathsTests(unittest.TestCase):
    def test_mac_bundle_uses_user_data(self):
        with patch.dict(os.environ, {'FLOWSTUDIO_DATA_DIR':''}), patch.object(app_paths.sys,'platform','darwin'), patch.object(app_paths,'APP_ROOT',Path('/Applications/Flow Studio.app/Contents/Resources')):
            self.assertEqual(app_paths.data_dir(),Path.home()/'Library/Application Support/FlowStudio/data')
    def test_source_layout_is_preserved(self):
        with patch.dict(os.environ, {'FLOWSTUDIO_DATA_DIR':''}), patch.object(app_paths,'APP_ROOT',Path('/source')):
            self.assertEqual(app_paths.data_dir(),Path('/source/data'))
    def test_explicit_isolation(self):
        with patch.dict(os.environ, {'FLOWSTUDIO_DATA_DIR':str(Path.home()/'isolated')}):
            self.assertEqual(app_paths.data_dir(),Path.home()/'isolated')
