from pathlib import Path
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QMessageBox
)
from app.core import work_dates
from app.services import editing_history, davinci_workflow
from app.ui.sheet_rich_text import CleanItemColorDelegate


class EditingHistoryDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.day = work_dates.active()
        self.setWindowTitle(f'剪辑记录 / 重新剪辑 · {self.day}')
        self.resize(1100, 620)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        self.hint_label = QLabel(f'仅显示当前工作日期（{self.day}）的剪辑记录。选中完整视频后，可重新发送到达芬奇；原成品保留。')
        self.hint_label.setObjectName('muted')
        layout.addWidget(self.hint_label)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索接收人 / 主播 / 视频序号 / 剪辑状态…')
        self.search.textChanged.connect(self.render)
        bar.addWidget(self.search, 1)

        refresh = QPushButton('刷新')
        refresh.clicked.connect(self.reload)
        bar.addWidget(refresh)

        self.submit = QPushButton('重新提交选中视频', objectName='primaryBtn')
        self.submit.clicked.connect(self.resubmit)
        bar.addWidget(self.submit)
        layout.addLayout(bar)

        self.table = QTableWidget(0, 7)
        self.table.setObjectName('promptTaskTable')
        self.table.setAlternatingRowColors(False)
        self.table.setHorizontalHeaderLabels(['日期', '接收人', '主播', '完整视频', '剪辑状态', '更新时间', '成品文件'])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hdr = self.table.horizontalHeader()
        for col_idx, init_w in ((0, 108), (1, 114), (2, 156), (3, 86), (4, 126), (5, 162)):
            hdr.setSectionResizeMode(col_idx, QHeaderView.Interactive)
            self.table.setColumnWidth(col_idx, init_w)
        hdr.setSectionResizeMode(6, QHeaderView.Stretch)
        self._color_delegate = CleanItemColorDelegate(self.table)
        for col_idx in range(7):
            self.table.setItemDelegateForColumn(col_idx, self._color_delegate)
        self.table.cellDoubleClicked.connect(self._open_row_output_dir)
        layout.addWidget(self.table, 1)
        self.reload()

    def reload(self):
        self.day = work_dates.active()
        self.setWindowTitle(f'剪辑记录 / 重新剪辑 · {self.day}')
        self.hint_label.setText(f'仅显示当前工作日期（{self.day}）的剪辑记录。选中完整视频后，可重新发送到达芬奇；原成品保留。')
        self.records = editing_history.rows(self.day)
        self.render()

    def render(self):
        query = self.search.text().strip().lower()
        rows = [r for r in self.records if not query or query in str(r).lower()]
        model = self.table.model()
        self.table.setUpdatesEnabled(False)
        try:
            if self.table.rowCount() != len(rows):
                self.table.setRowCount(len(rows))
            model.blockSignals(True)
            try:
                for i, r in enumerate(rows):
                    seq_txt = f"{int(r.get('video_seq') or 0):02d}"
                    status_txt = str(r.get('status') or '')
                    out_path = str(r.get('output_path') or '').strip()
                    values = [
                        r.get('work_date') or self.day,
                        r.get('recipient_name') or '',
                        r.get('host_name') or '',
                        seq_txt,
                        status_txt,
                        r.get('created_at') or '',
                        out_path,
                    ]
                    for j, value in enumerate(values):
                        cell = QTableWidgetItem(str(value or ''))
                        cell.setData(Qt.UserRole, r['video_id'])
                        if j in (0, 3, 4):
                            cell.setTextAlignment(Qt.AlignCenter)
                        if j == 4:
                            if status_txt in ('已导出', '已完成'):
                                cell.setForeground(QColor('#16A34A'))
                            elif status_txt in ('已剪辑', '待人工检查', '剪辑中', '导出中'):
                                cell.setForeground(QColor('#2563EB'))
                            elif '失败' in status_txt or '异常' in status_txt:
                                cell.setForeground(QColor('#DC2626'))
                        self.table.setItem(i, j, cell)
            finally:
                model.blockSignals(False)
        finally:
            self.table.setUpdatesEnabled(True)
            self.table.viewport().update()

    def _open_row_output_dir(self, row: int, _col: int):
        item = self.table.item(row, 6)
        if not item:
            return
        p = Path(item.text().strip()).expanduser()
        if p.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p.parent)))

    def resubmit(self):
        ids = sorted({int(self.table.item(x.row(), 0).data(Qt.UserRole)) for x in self.table.selectionModel().selectedRows()})
        if not ids:
            QMessageBox.information(self, '重新剪辑', '请先选中完整视频')
            return
        self.submit.setEnabled(False)
        try:
            result = davinci_workflow.submit_autoedit_jobs(ids, reedit=True)
            if not result.get('ok'):
                raise ValueError(result.get('reason', '提交失败'))
            count = result.get('submitted', 0)
            QMessageBox.information(
                self,
                '重新剪辑',
                f'已发送 {count} 个完整视频到达芬奇。' + ('其余视频正在剪辑/导出，或当前素材尚未全部质检通过，未重复提交。' if count < len(ids) else ''),
            )
            self.reload()
            if self.parent() and hasattr(self.parent(), 'reload'):
                self.parent().reload()
        except Exception as exc:
            from app.ui.resolve_error_dialog import show_editing_warning
            show_editing_warning(
                self,
                '重新剪辑',
                str(exc),
                on_view_log=getattr(self.parent(), 'view_batch_log', None),
            )
        finally:
            self.submit.setEnabled(True)

