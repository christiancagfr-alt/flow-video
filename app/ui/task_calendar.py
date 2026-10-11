from PySide6.QtCore import Qt,QDate,QTimer
from PySide6.QtGui import QColor,QPen
from PySide6.QtWidgets import QCalendarWidget
from app.core import work_dates
from app.ui import workspace_intake

class TaskCalendar(QCalendarWidget):
    def __init__(self,parent=None):
        super().__init__(parent);self.task_days=set()
        self.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        self.refresh_marks()
        self.mark_timer=QTimer(self);self.mark_timer.timeout.connect(self.refresh_marks);self.mark_timer.start(3000)
    def refresh_marks(self):
        self.task_days=work_dates.task_dates() | workspace_intake.task_dates()
        self.updateCells()
    def paintCell(self,painter,rect,day):
        super().paintCell(painter,rect,day)
        selected=day==self.selectedDate();has_task=day.toString('yyyy-MM-dd') in self.task_days
        painter.save()
        if selected or has_task:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor('#2f7cf6' if selected else '#e0f4e8'))
            painter.drawRoundedRect(rect.adjusted(2,2,-2,-2),5,5)
            painter.setPen(QColor('#ffffff' if selected else '#17643b'))
            painter.drawText(rect,Qt.AlignCenter,str(day.day()))
        if day==QDate.currentDate():
            painter.setPen(QPen(QColor('#ffffff' if selected else '#2f7cf6'),2))
            painter.drawLine(rect.center().x()-8,rect.bottom()-5,rect.center().x()+8,rect.bottom()-5)
        painter.restore()
