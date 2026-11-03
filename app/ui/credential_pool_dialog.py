"""Multi-key credential pool manager dialog (append-by-default, never silently overwrites)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.services import credential_pool


class CredentialPoolDialog(QDialog):
    """Visual key-pool manager supporting safe append, per-key delete/copy, and status reset."""

    def __init__(self, parent, service: str, account: str):
        super().__init__(parent)
        self.service = str(service)
        self.account = str(account)
        self.changed = False

        title_name = 'OpenAI / GPT' if self.account == 'FlowStudio' else self.account
        self.setWindowTitle(f'{title_name} · API 密钥池管理（多密钥自动轮询）')
        self.resize(660, 540)
        self.setMinimumSize(580, 460)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        # ── 1. Saved Keys Section ──
        saved_card = QFrame(objectName='workspacePanel')
        sl = QVBoxLayout(saved_card)
        sl.setContentsMargins(14, 12, 14, 12)
        sl.setSpacing(8)

        hdr = QHBoxLayout()
        hdr.setSpacing(8)
        self.saved_title = QLabel(f'🔑 已保存密钥列表（{title_name}）')
        self.saved_title.setStyleSheet('font-size:14px; font-weight:800;')
        hdr.addWidget(self.saved_title)

        self.count_chip = QLabel('0 个密钥', objectName='tcChip')
        hdr.addWidget(self.count_chip)
        hdr.addStretch(1)

        self.reset_health_btn = self._btn('↻ 重置限流状态', 'l3', 28, '将今日被标记为额度耗尽/限流的密钥恢复为可用状态')
        self.reset_health_btn.clicked.connect(self._reset_health)
        hdr.addWidget(self.reset_health_btn)

        self.clear_all_btn = self._btn('清空全部', 'l3', 28, '清空当前服务的全部已保存密钥（需二次确认）')
        self.clear_all_btn.clicked.connect(self._clear_all)
        hdr.addWidget(self.clear_all_btn)
        sl.addLayout(hdr)

        sub_note = QLabel('任务按顺序自动轮询下方所有可用密钥；新增密钥默认「追加合并」，绝不会覆盖已有密钥。')
        sub_note.setObjectName('muted')
        sub_note.setWordWrap(True)
        sl.addWidget(sub_note)

        self.list_scroll = QScrollArea()
        self.list_scroll.setWidgetResizable(True)
        self.list_scroll.setFrameShape(QFrame.NoFrame)
        self.list_scroll.setMinimumHeight(156)
        self.list_host = QWidget()
        self.list_vbox = QVBoxLayout(self.list_host)
        self.list_vbox.setContentsMargins(0, 2, 4, 2)
        self.list_vbox.setSpacing(6)
        self.list_vbox.setAlignment(Qt.AlignTop)
        self.list_scroll.setWidget(self.list_host)
        sl.addWidget(self.list_scroll, 1)
        root.addWidget(saved_card, 3)

        # ── 2. Append New Keys Section ──
        add_card = QFrame(objectName='workspacePanel')
        al = QVBoxLayout(add_card)
        al.setContentsMargins(14, 12, 14, 12)
        al.setSpacing(8)

        ah = QHBoxLayout()
        ah.setSpacing(8)
        add_title = QLabel('＋ 添加新密钥（自动追加合并 · 保留原有密钥）')
        add_title.setStyleSheet('font-size:13.5px; font-weight:800;')
        ah.addWidget(add_title)
        ah.addStretch(1)
        al.addLayout(ah)

        self.input_edit = QPlainTextEdit()
        self.input_edit.setPlaceholderText(
            '在这里粘贴 1 个或多个新密钥（每行一个，自动去重，最多支持 50 个）。\n'
            '点击下方「＋ 追加到密钥池」即可保留旧密钥并把新密钥加进去。'
        )
        self.input_edit.setMinimumHeight(96)
        al.addWidget(self.input_edit, 1)

        act_row = QHBoxLayout()
        act_row.setSpacing(8)
        self.feedback_lbl = QLabel('', objectName='muted')
        act_row.addWidget(self.feedback_lbl, 1)

        self.replace_all_btn = self._btn(
            '全量覆盖替换…',
            'l3',
            32,
            '用输入框里的密钥整池替换掉所有旧密钥（会弹出二次确认，防误点）',
        )
        self.replace_all_btn.clicked.connect(self._replace_all)
        act_row.addWidget(self.replace_all_btn)

        self.append_btn = self._btn(
            '＋ 追加到密钥池',
            'l2blue',
            32,
            '保留上方已有密钥，将输入框中的新密钥追加合并进去（自动去重）',
        )
        self.append_btn.clicked.connect(self._append_from_input)
        act_row.addWidget(self.append_btn)
        al.addLayout(act_row)
        root.addWidget(add_card, 2)

        # ── 3. Footer ──
        foot = QHBoxLayout()
        foot.setSpacing(8)
        foot.addStretch(1)
        cancel_btn = self._btn('取消', 'l3', 36)
        cancel_btn.clicked.connect(self.reject)
        foot.addWidget(cancel_btn)

        done_btn = self._btn('完成', 'l1blue', 36)
        done_btn.setMinimumWidth(112)
        done_btn.clicked.connect(self._on_done)
        foot.addWidget(done_btn)
        root.addLayout(foot)

        self._refresh_list()

    def _btn(self, text: str, tier: str = 'l3', height: int = 30, tip: str = '') -> QPushButton:
        b = QPushButton(text, objectName='pcBtn')
        b.setProperty('tier', tier)
        b.setFixedHeight(height)
        b.setMinimumWidth(b.fontMetrics().horizontalAdvance(text) + 22)
        b.setCursor(Qt.PointingHandCursor)
        if tip:
            b.setToolTip(tip)
        return b

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_list()

    def _is_dark(self) -> bool:
        from app.ui.sheet_rich_text import is_dark_theme

        if is_dark_theme(self):
            return True
        app = QApplication.instance()
        qss = app.styleSheet() if app is not None else ''
        return '#151A22' in qss or '#0F172A' in qss and 'background: #151A22' in qss

    def _refresh_list(self):
        dark = self._is_dark()
        while self.list_vbox.count():
            item = self.list_vbox.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        try:
            keys = list(credential_pool.read(self.service, self.account) or [])
        except Exception:
            keys = []
        health = credential_pool._load_health()
        avail_count = sum(1 for k in keys if credential_pool.is_key_available(self.service, self.account, k, health))

        self.count_chip.setText(f'可用 {avail_count} / 共 {len(keys)} 个')
        self.clear_all_btn.setEnabled(bool(keys))
        self.reset_health_btn.setEnabled(bool(keys) and avail_count < len(keys))

        if not keys:
            empty = QLabel('当前尚未保存任何密钥。请在下方粘贴密钥并点击「＋ 追加到密钥池」。', objectName='muted')
            empty.setAlignment(Qt.AlignCenter)
            empty.setMinimumHeight(90)
            self.list_vbox.addWidget(empty)
            return

        row_bg = '#1E293B' if dark else '#F8FAFC'
        row_bd = '#334155' if dark else '#E2E8F0'
        txt_fg = '#F1F5F9' if dark else '#0F172A'
        muted_fg = '#94A3B8' if dark else '#64748B'
        for idx, k in enumerate(keys, start=1):
            ok = credential_pool.is_key_available(self.service, self.account, k, health)
            rf = QFrame()
            rf.setStyleSheet(
                f'QFrame {{ background:{row_bg}; border:1px solid {row_bd}; border-radius:8px; }}'
            )
            rl = QHBoxLayout(rf)
            rl.setContentsMargins(10, 6, 10, 6)
            rl.setSpacing(8)

            idx_lbl = QLabel(f'#{idx:02d}')
            idx_lbl.setStyleSheet(f'color:{muted_fg}; font-weight:800; font-size:12.5px; border:none; background:transparent;')
            idx_lbl.setFixedWidth(34)
            rl.addWidget(idx_lbl)

            mask_lbl = QLabel(credential_pool.mask_key(k))
            mask_lbl.setStyleSheet(
                f'color:{txt_fg}; font-family: Menlo, Monaco, Consolas, monospace; font-size:12.5px; font-weight:700; border:none; background:transparent;'
            )
            rl.addWidget(mask_lbl, 1)

            st_lbl = QLabel('✓ 可用' if ok else '⚠ 今日限流')
            if ok:
                st_bg, st_fg = ('#163829', '#6EE7B7') if dark else ('#DCFCE7', '#15803D')
            else:
                st_bg, st_fg = ('#3B1F24', '#FCA5A5') if dark else ('#FEE2E2', '#DC2626')
            st_lbl.setStyleSheet(
                f'background:{st_bg}; color:{st_fg}; border:none; border-radius:6px; padding:2px 8px; font-size:11.5px; font-weight:750;'
            )
            rl.addWidget(st_lbl)

            copy_btn = self._btn('复制', 'l3', 26, '复制此条完整密钥到剪贴板')
            copy_btn.clicked.connect(lambda _=False, raw=k, n=idx: self._copy_one(raw, n))
            rl.addWidget(copy_btn)

            del_btn = self._btn('删除', 'l3', 26, '仅从密钥池移除这一条密钥，不影响其他密钥')
            del_btn.clicked.connect(lambda _=False, raw=k, n=idx: self._delete_one(raw, n))
            rl.addWidget(del_btn)

            self.list_vbox.addWidget(rf)

    def _copy_one(self, raw_key: str, idx: int):
        QApplication.clipboard().setText(raw_key)
        self.feedback_lbl.setText(f'✓ 已复制第 #{idx:02d} 条密钥到剪贴板')

    def _delete_one(self, raw_key: str, idx: int):
        masked = credential_pool.mask_key(raw_key)
        if QMessageBox.question(
            self,
            '删除单条密钥',
            f'确认从密钥池中移除第 #{idx:02d} 条密钥（{masked}）吗？\n其他已保存的密钥会完整保留。',
        ) != QMessageBox.Yes:
            return
        try:
            left = credential_pool.remove_key(self.service, self.account, raw_key)
            self.changed = True
            self.feedback_lbl.setText(f'✓ 已移除 {masked}，当前剩余 {left} 个密钥')
            self._refresh_list()
        except Exception as exc:
            QMessageBox.warning(self, '删除失败', f'无法更新系统凭据库：\n{exc}')

    def _reset_health(self):
        credential_pool.reset_account_status(self.service, self.account)
        self.changed = True
        self.feedback_lbl.setText('✓ 已重置所有密钥的可用状态')
        self._refresh_list()

    def _clear_all(self):
        if QMessageBox.question(
            self,
            '清空全部密钥',
            f'确认清空 {self.account} 已保存的全部密钥吗？此操作不可撤销。',
        ) != QMessageBox.Yes:
            return
        try:
            credential_pool.clear(self.service, self.account)
            self.changed = True
            self.feedback_lbl.setText('✓ 已清空全部密钥')
            self._refresh_list()
        except Exception as exc:
            QMessageBox.warning(self, '清空失败', str(exc))

    def _append_from_input(self) -> bool:
        raw = self.input_edit.toPlainText().strip()
        if not raw:
            QMessageBox.information(self, '追加密钥', '请先在输入框中粘贴要添加的密钥（每行一个）。')
            return False
        try:
            before = len(credential_pool.read(self.service, self.account) or [])
            total = credential_pool.append_keys(self.service, self.account, raw)
        except Exception as exc:
            QMessageBox.warning(self, '追加密钥失败', f'请检查每行一个有效密钥（无空格、总数不超过 50 个），并确认系统凭据库已解锁。\n\n详情：{exc}')
            return False
        added = max(0, total - before)
        self.input_edit.clear()
        self.changed = True
        if added > 0:
            self.feedback_lbl.setText(f'✓ 成功追加 {added} 个新密钥，当前池内共 {total} 个密钥！')
        else:
            self.feedback_lbl.setText(f'✓ 输入的密钥已在池内（自动去重），当前池内共 {total} 个密钥')
        self._refresh_list()
        return True

    def _replace_all(self):
        raw = self.input_edit.toPlainText().strip()
        if not raw:
            QMessageBox.information(self, '全量覆盖替换', '请先在输入框中粘贴新的密钥列表（每行一个）。')
            return
        try:
            old_count = len(credential_pool.read(self.service, self.account) or [])
            new_keys = credential_pool.normalize(raw)
        except Exception as exc:
            QMessageBox.warning(self, '格式检查', str(exc))
            return
        if old_count > 0:
            if QMessageBox.question(
                self,
                '确认全量覆盖替换',
                f'注意：这将删除原先已保存的 {old_count} 个旧密钥，并仅保留输入框里的 {len(new_keys)} 个密钥！\n\n'
                '如果你只是想增加新密钥，请点「取消」后点击右侧蓝色的「➕ 追加到密钥池」。\n仍要全量覆盖替换吗？',
            ) != QMessageBox.Yes:
                return
        try:
            total = credential_pool.save(self.service, self.account, raw)
        except Exception as exc:
            QMessageBox.warning(self, '保存失败', str(exc))
            return
        self.input_edit.clear()
        self.changed = True
        self.feedback_lbl.setText(f'✓ 已全量替换为 {total} 个密钥')
        self._refresh_list()

    def _on_done(self):
        # If the user pasted keys into the box and clicked "完成" directly, append them automatically!
        raw = self.input_edit.toPlainText().strip()
        if raw:
            if not self._append_from_input():
                return
        self.accept()


def edit_pool(parent, service, account):
    dlg = CredentialPoolDialog(parent, service, account)
    result = dlg.exec()
    return QDialog.Accepted if (result == QDialog.Accepted or dlg.changed) else result
