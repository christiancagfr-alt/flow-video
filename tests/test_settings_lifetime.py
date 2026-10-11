import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import gc
import unittest
from unittest.mock import MagicMock, patch
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid
from app.ui.main_window import SettingsDialog

app = QApplication.instance() or QApplication([])

class SettingsLifetimeTests(unittest.TestCase):
    def test_hidden_fields_survive_dialog_and_save(self):
        with patch('app.ui.main_window.repo.get_setting', side_effect=lambda key, default='': default), patch('app.ui.main_window.repo.default_creator', return_value='test'), patch('app.ui.main_window.repo.set_setting') as save, patch('app.ui.main_window.repo.set_default_creator'):
            settings=MagicMock()
            settings.value.side_effect=lambda key, default='': default
            dialog=SettingsDialog(settings)
            gc.collect()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            self.assertTrue(isValid(dialog.drive_desktop_path))
            self.assertTrue(isValid(dialog.drive_upload_root_url))
            self.assertTrue(isValid(dialog.drive_desktop_folder))
            dialog.drive_desktop_path.setText('D:/Drive')
            dialog.accept()
            app.processEvents()
            dialog.save()
            save.assert_any_call('drive_desktop_path', 'D:/Drive')
            save.assert_any_call('default_wrap', '18')
            dialog.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

if __name__ == '__main__': unittest.main()
