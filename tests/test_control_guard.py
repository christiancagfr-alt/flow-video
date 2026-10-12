import os,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication,QWidget,QVBoxLayout,QSpinBox,QComboBox,QLineEdit
from PySide6.QtCore import Qt,QPoint,QPointF
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from app.ui.control_guard import install_control_guard
APP=QApplication.instance() or QApplication([])
class ControlGuardTests(unittest.TestCase):
    def test_requires_click_and_disarms_on_focus_loss(self):
        install_control_guard(APP)
        host=QWidget();layout=QVBoxLayout(host);spin=QSpinBox();spin.setValue(20);combo=QComboBox();combo.addItems(['one','two','three']);edit=QLineEdit()
        for w in (spin,combo,edit):layout.addWidget(w)
        host.show();host.activateWindow();APP.processEvents()
        def wheel(w):
            event=QWheelEvent(QPointF(10,10),QPointF(w.mapToGlobal(QPoint(10,10))),QPoint(),QPoint(0,-120),Qt.NoButton,Qt.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
            APP.sendEvent(w,event)
        wheel(spin);self.assertEqual(spin.value(),20)
        QTest.mouseClick(spin,Qt.LeftButton,pos=QPoint(10,10));wheel(spin);self.assertEqual(spin.value(),19)
        QTest.mouseClick(edit,Qt.LeftButton);wheel(spin);self.assertEqual(spin.value(),19)
        wheel(combo);self.assertEqual(combo.currentIndex(),0)
        self.assertLessEqual(spin.maximumWidth(),100)
        host.close();host.deleteLater()
if __name__=='__main__':unittest.main()
