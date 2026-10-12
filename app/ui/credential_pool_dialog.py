from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPlainTextEdit, QDialogButtonBox, QMessageBox
from app.services import credential_pool


def edit_pool(parent, service, account):
    dialog = QDialog(parent)
    dialog.setWindowTitle(account + ' · 批量密钥')
    dialog.resize(500, 320)
    layout = QVBoxLayout(dialog)
    try: count = len(credential_pool.read(service, account))
    except Exception: count = 0
    label = QLabel(f'已保存 {count} 个。每行一个；保存会替换此服务的密钥列表。\n任务按顺序轮询，不会跨服务使用密钥。已有密钥不回显。\n临时输入框或对应 API 环境变量中的单密钥优先，请清空后使用轮询。')
    label.setWordWrap(True); layout.addWidget(label)
    text = QPlainTextEdit(); text.setPlaceholderText('在这里粘贴密钥，每行一个'); layout.addWidget(text)
    buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
    layout.addWidget(buttons)
    def save():
        try: credential_pool.save(service, account, text.toPlainText())
        except Exception:
            QMessageBox.warning(dialog, '保存失败', '请检查每行一个密钥（最多 20 个），并确认系统凭据库已解锁。'); return
        text.clear(); dialog.accept()
    buttons.accepted.connect(save); buttons.rejected.connect(dialog.reject)
    result = dialog.exec(); text.clear()
    return result
