import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import gc
import unittest
from unittest.mock import MagicMock, patch
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QDialog
from shiboken6 import isValid
from app.ui.settings_page import SettingsPage

app = QApplication.instance() or QApplication([])


def _getter(key, default=''):
    return default


class SettingsLifetimeTests(unittest.TestCase):
    def test_hidden_fields_survive_and_the_page_is_not_a_dialog(self):
        with patch('app.ui.settings_page.repo.get_setting', side_effect=_getter), \
             patch('app.ui.settings_page.repo.default_creator', return_value='test'), \
             patch('app.ui.settings_page.repo.set_setting') as save, \
             patch('app.ui.settings_page.repo.set_default_creator'), \
             patch('app.services.sheet_columns.repo.get_setting', side_effect=_getter), \
             patch('app.services.sheet_columns.repo.set_setting', save):
            settings = MagicMock()
            settings.value.side_effect = lambda key, default='': default
            page = SettingsPage(settings)
            gc.collect()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            self.assertNotIsInstance(page, QDialog)
            self.assertTrue(isValid(page.drive_desktop_path))
            self.assertTrue(isValid(page.drive_upload_root_url))
            self.assertTrue(isValid(page.drive_desktop_folder))
            self.assertTrue(page.template_radio.isChecked())
            image = page._column_boxes['主播图片链接']
            date = page._column_boxes['日期']
            self.assertEqual(image.currentData(), '9')
            self.assertFalse(image.isEnabled())
            self.assertEqual(date.currentData(), 'unused')
            page.custom_radio.setChecked(True)
            self.assertTrue(image.isEnabled())
            self.assertEqual(image.currentData(), '9')
            page.drive_desktop_path.setText('D:/Drive')
            app.processEvents()
            page.save()
            save.assert_any_call('drive_desktop_path', 'D:/Drive')
            save.assert_any_call('default_wrap', '18')
            save.assert_any_call('task_sheet_column_mode', 'custom')
            page.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


if __name__ == '__main__':
    unittest.main()
