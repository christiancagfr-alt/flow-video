"""Clean, modern, Chinese-button confirmation dialog replacing native QMessageBox.question."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


def ask_confirm(
    parent: QWidget | None,
    title: str,
    headline: str,
    *,
    bullets: list[str] | None = None,
    subtext: str = "",
    confirm_text: str = "确认执行",
    cancel_text: str = "取消",
    extra_text: str = "",
    tone: str = "primary",
    icon_text: str = "✨",
) -> str:
    """Show a modern card-styled confirmation dialog.

    Returns ``"confirm"``, ``"extra"``, or ``"cancel"``.
    """
    dlg = QDialog(parent, objectName="modernConfirmDialog")
    dlg.setWindowTitle(title)
    dlg.setModal(True)
    dlg.setMinimumWidth(420)
    dlg.setMaximumWidth(500)

    result_choice = {"value": "cancel"}

    root = QVBoxLayout(dlg)
    root.setContentsMargins(18, 16, 18, 16)
    root.setSpacing(12)

    # Top Hero Row (Icon Badge + Headline + Subtext)
    card = QFrame(dlg, objectName="modernConfirmCard")
    card.setProperty("tone", tone)
    c_lay = QVBoxLayout(card)
    c_lay.setContentsMargins(16, 14, 16, 14)
    c_lay.setSpacing(10)

    head_row = QHBoxLayout()
    head_row.setSpacing(12)

    badge = QLabel(icon_text, card, objectName="modernConfirmIcon")
    badge.setProperty("tone", tone)
    badge.setFixedSize(36, 36)
    badge.setAlignment(Qt.AlignCenter)
    head_row.addWidget(badge, 0, Qt.AlignTop)

    title_col = QVBoxLayout()
    title_col.setSpacing(4)
    hl_lbl = QLabel(headline, card, objectName="modernConfirmHeadline")
    hl_lbl.setWordWrap(True)
    title_col.addWidget(hl_lbl)

    if subtext:
        sub_lbl = QLabel(subtext, card, objectName="modernConfirmSub")
        sub_lbl.setWordWrap(True)
        title_col.addWidget(sub_lbl)

    head_row.addLayout(title_col, 1)
    c_lay.addLayout(head_row)

    clean_bullets = [str(b).strip() for b in (bullets or []) if str(b).strip()]
    if clean_bullets:
        pills_frame = QFrame(card, objectName="modernConfirmBullets")
        p_lay = QVBoxLayout(pills_frame)
        p_lay.setContentsMargins(12, 9, 12, 9)
        p_lay.setSpacing(5)
        for item in clean_bullets:
            b_lbl = QLabel(item, pills_frame, objectName="modernConfirmBulletItem")
            b_lbl.setWordWrap(True)
            p_lay.addWidget(b_lbl)
        c_lay.addWidget(pills_frame)

    root.addWidget(card)

    # Footer Buttons (Chinese labels, clear visual hierarchy)
    foot = QHBoxLayout()
    foot.setSpacing(8)
    foot.addStretch(1)

    btn_cancel = QPushButton(cancel_text, dlg, objectName="modernConfirmCancelBtn")
    btn_cancel.setCursor(Qt.PointingHandCursor)
    btn_cancel.setMinimumWidth(84)
    btn_cancel.setFixedHeight(34)

    def _on_cancel():
        result_choice["value"] = "cancel"
        dlg.reject()

    btn_cancel.clicked.connect(_on_cancel)
    foot.addWidget(btn_cancel)

    if extra_text:
        btn_extra = QPushButton(extra_text, dlg, objectName="modernConfirmExtraBtn")
        btn_extra.setCursor(Qt.PointingHandCursor)
        btn_extra.setMinimumWidth(104)
        btn_extra.setFixedHeight(34)

        def _on_extra():
            result_choice["value"] = "extra"
            dlg.accept()

        btn_extra.clicked.connect(_on_extra)
        foot.addWidget(btn_extra)

    btn_ok = QPushButton(confirm_text, dlg, objectName=" primaryBtn" if tone != "danger" else "rtDangerBtn")
    btn_ok.setObjectName("modernConfirmOkBtn")
    btn_ok.setProperty("tone", tone)
    btn_ok.setCursor(Qt.PointingHandCursor)
    btn_ok.setMinimumWidth(104)
    btn_ok.setFixedHeight(34)
    btn_ok.setDefault(True)

    def _on_ok():
        result_choice["value"] = "confirm"
        dlg.accept()

    btn_ok.clicked.connect(_on_ok)
    foot.addWidget(btn_ok)

    root.addLayout(foot)
    dlg.exec()
    return result_choice["value"]
