"""Diagnostic detail dialog and inline '查看详情' widgets for DaVinci Resolve auto-editing errors."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.services.resolve_error_guide import (
    EditingErrorInfo,
    diagnose_editing_error,
    format_inline_editing_text,
)


def make_inline_error_detail_btn(parent: QWidget | None = None, text: str = '查看详情') -> QPushButton:
    btn = QPushButton(text, parent)
    btn.setObjectName('dvErrDetailBtn')
    btn.setFixedHeight(22)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setFocusPolicy(Qt.NoFocus)
    btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    btn.setToolTip('点击查看中文原因说明与分步解决建议')
    return btn


def _polish_prop(widget: QWidget, name: str, val: str):
    if widget.property(name) != val:
        widget.setProperty(name, val)
        st = widget.style()
        if st is not None:
            st.unpolish(widget)
            st.polish(widget)


class InlineErrorStatusBox(QWidget):
    """Packs a status QLabel + adjacent '查看详情' mini-button tightly on the left without overflowing."""

    def __init__(
        self,
        label: QLabel,
        *,
        on_open_detail: Callable[[EditingErrorInfo], None] | None = None,
        min_text_width: int = 150,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.label = label
        self._on_open_detail = on_open_detail
        self._min_text_w = max(80, int(min_text_width))
        self._full_display_text = label.text()
        self.error_info: EditingErrorInfo | None = None

        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(self._min_text_w)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.label.setWordWrap(False)
        self.label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        lay.addWidget(self.label, 0, Qt.AlignVCenter)

        self.detail_btn = make_inline_error_detail_btn(self)
        self.detail_btn.hide()
        self.detail_btn.clicked.connect(self._handle_click)
        lay.addWidget(self.detail_btn, 0, Qt.AlignVCenter)

        lay.addStretch(1)

    def _handle_click(self):
        if self.error_info is None:
            return
        if self._on_open_detail is not None:
            self._on_open_detail(self.error_info)
        else:
            open_editing_error_detail(self.window() or self, self.error_info)

    def set_raw_status(
        self,
        raw_text: str,
        *,
        batch_status: str = '',
        stage: str = '',
        tooltip_override: str = '',
    ):
        disp, info = format_inline_editing_text(
            raw_text,
            batch_status=batch_status,
            stage=stage,
            max_len=160,
        )
        self._full_display_text = disp
        self.error_info = info
        is_err = info is not None
        _polish_prop(self.label, 'isError', 'true' if is_err else 'false')
        self.detail_btn.setVisible(is_err)

        if is_err and info is not None:
            tip_lines = [info.title, f'原因：{info.cause}']
            if info.solutions:
                tip_lines.append(f'建议：{info.solutions[0]}')
            tip_lines.append('💡 点击右侧「查看详情」查看完整解决步骤')
            self.label.setToolTip('\n'.join(tip_lines))
        else:
            self.label.setToolTip(tooltip_override or disp)

        self._refresh_elision()

    def _refresh_elision(self):
        txt = self._full_display_text or ''
        if not txt:
            self.label.setMaximumWidth(16777215)
            if self.label.text() != '':
                self.label.setText('')
            return
        total_w = self.width()
        if total_w <= 40:
            # Before first layout pass, show un-elided up to reasonable bound and re-check once laid out
            self.label.setMaximumWidth(16777215)
            short = txt if len(txt) <= 56 else (txt[:55] + '…')
            if self.label.text() != short:
                self.label.setText(short)
            QTimer.singleShot(0, self._refresh_elision)
            return
        btn_reserve = (max(58, self.detail_btn.sizeHint().width()) + 12) if self.error_info is not None else 10
        avail = max(0, total_w - btn_reserve)
        self.label.setMaximumWidth(avail)
        elided = self.label.fontMetrics().elidedText(txt, Qt.ElideRight, avail) if avail > 14 else ''
        if self.label.text() != elided:
            self.label.setText(elided)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_elision()


class EditingErrorDetailDialog(QDialog):
    """Clean Light/Dark-themed modal explaining an editing error in Chinese with step-by-step solutions."""

    def __init__(
        self,
        info: EditingErrorInfo,
        parent: QWidget | None = None,
        *,
        context_title: str = '',
        on_view_log: Callable[[], None] | None = None,
    ):
        super().__init__(parent)
        self.info = info
        self._on_view_log = on_view_log
        self.setObjectName('dvErrDetailDialog')
        win_title = f'异常详情与解决建议 · {context_title}' if context_title else '剪辑异常详情与解决建议'
        self.setWindowTitle(win_title)
        self.resize(650, 624)
        self.setMinimumWidth(520)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        # ── 1. Top Hero Card (Stage Badge + Chinese Title + Location Tags) ──
        hero = QFrame(objectName='dvErrHeroCard')
        hv = QVBoxLayout(hero)
        hv.setContentsMargins(16, 14, 16, 14)
        hv.setSpacing(8)

        badge_row = QHBoxLayout()
        badge_row.setSpacing(8)
        stage_badge = QLabel(info.stage_label or '自动剪辑诊断', objectName='dvErrStageBadge')
        badge_row.addWidget(stage_badge)
        badge_row.addStretch(1)
        hv.addLayout(badge_row)

        title_lbl = QLabel(f'⚠ {info.title}', objectName='dvErrTitle')
        title_lbl.setWordWrap(True)
        title_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        hv.addWidget(title_lbl)

        if info.location_items:
            loc_box = QFrame(objectName='dvErrLocCard')
            lv = QVBoxLayout(loc_box)
            lv.setContentsMargins(11, 8, 11, 8)
            lv.setSpacing(4)
            for k_txt, v_txt in info.location_items:
                row = QHBoxLayout()
                row.setSpacing(8)
                kl = QLabel(f'{k_txt}：', objectName='dvErrLocKey')
                kl.setFixedWidth(74)
                vl = QLabel(v_txt, objectName='dvErrLocVal')
                vl.setWordWrap(True)
                vl.setTextInteractionFlags(Qt.TextSelectableByMouse)
                row.addWidget(kl, 0, Qt.AlignTop)
                row.addWidget(vl, 1)
                lv.addLayout(row)
            hv.addWidget(loc_box)

        root.addWidget(hero)

        # ── 2. Scrollable Body (Cause + Step-by-Step Solutions + Collapsible Raw Log) ──
        scroll = QScrollArea(objectName='dvErrScroll')
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget(objectName='dvErrScrollBody')
        bv = QVBoxLayout(body)
        bv.setContentsMargins(0, 0, 2, 0)
        bv.setSpacing(10)

        # Cause Card
        cause_card = QFrame(objectName='dvErrDialogCard')
        cv = QVBoxLayout(cause_card)
        cv.setContentsMargins(15, 12, 15, 12)
        cv.setSpacing(6)
        cv.addWidget(QLabel('💡 为什么会报这个错？', objectName='dvErrSectionTitle'))
        cause_lbl = QLabel(info.cause, objectName='dvErrBodyText')
        cause_lbl.setWordWrap(True)
        cause_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        cv.addWidget(cause_lbl)
        bv.addWidget(cause_card)

        # Solutions Card
        sol_card = QFrame(objectName='dvErrSolutionsCard')
        sv = QVBoxLayout(sol_card)
        sv.setContentsMargins(15, 12, 15, 14)
        sv.setSpacing(8)
        sv.addWidget(QLabel('🛠 建议解决办法（按顺序操作即可恢复）', objectName='dvErrSectionTitle'))

        for idx, step_text in enumerate(info.solutions or ['请先点击「唤醒达芬奇」刷新状态后重试。'], 1):
            srow = QHBoxLayout()
            srow.setSpacing(10)
            num_badge = QLabel(str(idx), objectName='dvErrStepBadge')
            num_badge.setFixedSize(22, 22)
            num_badge.setAlignment(Qt.AlignCenter)
            stxt = QLabel(step_text, objectName='dvErrStepText')
            stxt.setWordWrap(True)
            stxt.setTextInteractionFlags(Qt.TextSelectableByMouse)
            srow.addWidget(num_badge, 0, Qt.AlignTop)
            srow.addWidget(stxt, 1)
            sv.addLayout(srow)
        bv.addWidget(sol_card)

        # Collapsible Raw Technical String (collapsed by default)
        if info.raw_error:
            raw_wrap = QWidget()
            rv = QVBoxLayout(raw_wrap)
            rv.setContentsMargins(0, 2, 0, 0)
            rv.setSpacing(6)

            self._raw_toggle_btn = QPushButton('▸ 查看底层原始报错信息（仅供排查）', objectName='dvErrRawToggleBtn')
            self._raw_toggle_btn.setCheckable(True)
            self._raw_toggle_btn.setMinimumHeight(26)
            self._raw_toggle_btn.setCursor(Qt.PointingHandCursor)
            self._raw_toggle_btn.setFocusPolicy(Qt.NoFocus)
            rv.addWidget(self._raw_toggle_btn, 0, Qt.AlignLeft)

            self._raw_edit = QPlainTextEdit(objectName='dvErrRawBox')
            self._raw_edit.setReadOnly(True)
            self._raw_edit.setPlainText(info.raw_error)
            self._raw_edit.setMaximumHeight(92)
            self._raw_edit.hide()
            rv.addWidget(self._raw_edit)

            def _toggle_raw(checked: bool):
                self._raw_edit.setVisible(checked)
                self._raw_toggle_btn.setText(
                    '▾ 收起底层原始报错信息' if checked else '▸ 查看底层原始报错信息（仅供排查）'
                )

            self._raw_toggle_btn.toggled.connect(_toggle_raw)
            bv.addWidget(raw_wrap)

        bv.addStretch(1)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        # ── 3. Footer Actions ──
        foot = QHBoxLayout()
        foot.setSpacing(8)
        self.copy_btn = QPushButton('📋 复制诊断详情')
        self.copy_btn.setCursor(Qt.PointingHandCursor)
        self.copy_btn.clicked.connect(self._copy_all)
        foot.addWidget(self.copy_btn)

        if self._on_view_log is not None:
            log_btn = QPushButton('📂 查看本批日志')
            log_btn.setCursor(Qt.PointingHandCursor)
            log_btn.clicked.connect(self._open_log)
            foot.addWidget(log_btn)

        foot.addStretch(1)
        ok_btn = QPushButton('我知道了', objectName='primaryBtn')
        ok_btn.setCursor(Qt.PointingHandCursor)
        ok_btn.setMinimumWidth(96)
        ok_btn.clicked.connect(self.accept)
        foot.addWidget(ok_btn)
        root.addLayout(foot)

    def _copy_all(self):
        lines = [
            f'【剪辑异常】{self.info.title}',
            f'【所属阶段】{self.info.stage_label}',
        ]
        for k_txt, v_txt in self.info.location_items:
            lines.append(f'【{k_txt}】{v_txt}')
        lines.append(f'【原因说明】{self.info.cause}')
        lines.append('【建议解决办法】')
        for idx, s in enumerate(self.info.solutions, 1):
            lines.append(f'  {idx}. {s}')
        if self.info.raw_error:
            lines.append(f'【原始信息】{self.info.raw_error}')
        cb = QGuiApplication.clipboard()
        if cb is not None:
            cb.setText('\n'.join(lines))
        self.copy_btn.setText('✓ 已复制到剪贴板')
        QTimer.singleShot(1800, lambda: self.copy_btn.setText('📋 复制诊断详情'))

    def _open_log(self):
        cb = self._on_view_log
        if cb is not None:
            cb()


def open_editing_error_detail(
    parent: QWidget | None,
    raw_or_info: str | EditingErrorInfo,
    *,
    batch_status: str = '',
    stage: str = '',
    on_view_log: Callable[[], None] | None = None,
):
    if isinstance(raw_or_info, EditingErrorInfo):
        info = raw_or_info
    else:
        info = diagnose_editing_error(str(raw_or_info or ''), batch_status=batch_status, stage=stage)
        if info is None:
            info = EditingErrorInfo(
                code='NOTICE',
                stage_label='自动剪辑提示',
                title=str(raw_or_info or '当前没有异常详情'),
                inline_text=str(raw_or_info or ''),
                cause=str(raw_or_info or ''),
                solutions=['请按页面步骤提示继续操作。'],
                raw_error=str(raw_or_info or ''),
            )
    dlg = EditingErrorDetailDialog(info, parent=parent, on_view_log=on_view_log)
    dlg.exec()


def show_editing_warning(
    parent: QWidget | None,
    window_title: str,
    raw_error: str,
    *,
    batch_status: str = 'ERROR',
    stage: str = '',
    on_view_log: Callable[[], None] | None = None,
):
    """Drop-in replacement for ``QMessageBox.warning`` in editing views: pure Chinese + '查看详情' button."""
    info = diagnose_editing_error(str(raw_error or ''), batch_status=batch_status, stage=stage)
    if info is None:
        QMessageBox.warning(parent, window_title, str(raw_error or '操作未完成，请重试。'))
        return

    box = QMessageBox(parent)
    box.setWindowTitle(window_title)
    box.setIcon(QMessageBox.Warning)
    box.setText(info.title)
    summary_lines = [info.cause]
    if info.solutions:
        summary_lines.append('\n建议处理：')
        for idx, step in enumerate(info.solutions[:2], 1):
            summary_lines.append(f'{idx}. {step}')
    box.setInformativeText('\n'.join(summary_lines))
    btn_detail = box.addButton('查看详情', QMessageBox.ActionRole)
    btn_ok = box.addButton('我知道了', QMessageBox.AcceptRole)
    box.setDefaultButton(btn_ok)
    box.exec()
    if box.clickedButton() is btn_detail:
        open_editing_error_detail(parent, info, on_view_log=on_view_log)
