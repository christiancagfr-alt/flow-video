from PySide6.QtWidgets import QMessageBox


def confirm_clear(parent, title, text):
    dialog = QMessageBox(QMessageBox.Warning, title, text, parent=parent)
    confirm = dialog.addButton("确定清除", QMessageBox.AcceptRole)
    cancel = dialog.addButton("取消", QMessageBox.RejectRole)
    dialog.setDefaultButton(cancel)
    dialog.setEscapeButton(cancel)
    dialog.exec()
    return dialog.clickedButton() is confirm
