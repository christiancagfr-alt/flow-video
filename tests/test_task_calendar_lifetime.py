import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from unittest.mock import patch
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from shiboken6 import delete, isValid
from app.ui.main_window import CalendarDialog
from app.ui.task_calendar import TaskCalendar

app = QApplication.instance() or QApplication([])

class TaskCalendarLifetimeTests(unittest.TestCase):
    def setUp(self):
        self.dates = patch('app.ui.task_calendar.work_dates.task_dates', return_value={'2026-10-01'})
        self.intake = patch('app.ui.task_calendar.workspace_intake.task_dates', return_value={'2026-10-02'})
        self.dates.start(); self.intake.start()

    def tearDown(self):
        self.dates.stop(); self.intake.stop()

    def test_refresh_marks_survives_deleted_calendar(self):
        calendar = TaskCalendar()
        calendar.show(); app.processEvents()
        self.assertEqual(calendar.task_days, {'2026-10-01', '2026-10-02'})
        self.assertTrue(calendar.mark_timer.isActive())
        calendar.hide(); app.processEvents()
        self.assertFalse(calendar.mark_timer.isActive())
        timer = calendar.mark_timer
        timer.setParent(None); timer.start(3000)
        delete(calendar)
        self.assertFalse(isValid(calendar))
        calendar.refresh_marks()
        calendar.refresh_marks()
        self.assertFalse(timer.isActive())
        if isValid(timer): timer.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_closing_dialog_stops_refresh_before_destroy(self):
        dialog = CalendarDialog()
        dialog.show(); app.processEvents()
        calendar = dialog.calendar
        self.assertTrue(calendar.mark_timer.isActive())
        dialog.reject(); app.processEvents()
        self.assertTrue(isValid(calendar))
        self.assertFalse(calendar.mark_timer.isActive())
        self.assertTrue(dialog.selected_date().isValid())
        dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertFalse(isValid(calendar))
        calendar.refresh_marks()

if __name__ == '__main__': unittest.main()
