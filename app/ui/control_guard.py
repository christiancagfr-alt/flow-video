"""Prevent incidental scrolling from changing settings throughout the application."""
from PySide6.QtCore import QObject, QEvent, Qt
from PySide6.QtWidgets import QApplication, QAbstractSpinBox, QComboBox, QSlider, QWidget


class ControlGuard(QObject):
    # Theme changes and page paints emit thousands of these. Walking parents for each one froze the window.
    _INTERESTING = frozenset((
        QEvent.Type.Show,
        QEvent.Type.MouseButtonPress,
        QEvent.Type.FocusOut,
        QEvent.Type.Wheel,
    ))

    def eventFilter(self, obj, event):
        if event.type() not in self._INTERESTING:
            return False
        control = obj
        while isinstance(control, QWidget) and not isinstance(control, (QAbstractSpinBox, QComboBox, QSlider)):
            control = control.parentWidget()
        if not isinstance(control, (QAbstractSpinBox, QComboBox, QSlider)):
            return False
        kind = event.type()
        if kind == QEvent.Type.Show and obj is control:
            control.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            if isinstance(control, QAbstractSpinBox):
                # Include decimals, signs and suffixes rather than truncating larger values.
                width = control.fontMetrics().horizontalAdvance(
                    max((control.textFromValue(control.minimum()), control.textFromValue(control.maximum())), key=len)
                    + control.prefix() + control.suffix()) + 42
                control.setMaximumWidth(max(76, width))
        elif kind == QEvent.Type.MouseButtonPress:
            control.setProperty('_wheelArmed', True)
        elif kind == QEvent.Type.FocusOut:
            control.setProperty('_wheelArmed', False)
        elif kind == QEvent.Type.Wheel:
            if not control.property('_wheelArmed') or not control.hasFocus():
                event.ignore()
                return True
        return False


def install_control_guard(app=None):
    app = app or QApplication.instance()
    if app is not None and not hasattr(app, '_flow_control_guard'):
        app._flow_control_guard = ControlGuard(app)
        app.installEventFilter(app._flow_control_guard)
