"""Completed-videos window of the auto-edit center: pick videos and re-export them."""
from __future__ import annotations
from pathlib import Path
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)
from app.core import repository as repo, work_dates
from app.services import reexport

COLS = ('', '接收人', '主播', '视频', '成品文件', '状态')


def _row_key(row):
    return (str(row['recipient_name'] or ''), str(row['host_name'] or ''), int(row['video_seq'] or 0), int(row['video_id']))


class CompletedVideosDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('剪辑完成 · 导出管理')
        self.resize(980, 640)
        self._checked = set()
        self._rows = []
        self._signature = None
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)

        head = QHBoxLayout()
        self.title = QLabel('', objectName='sectionTitle')
        head.addWidget(self.title)
        head.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索 接收人 / 主播 / 视频编号')
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(240)
        self.search.textChanged.connect(self._render)
        head.addWidget(self.search)
        root.addLayout(head)

        tools = QHBoxLayout()
        self.select_all = QPushButton('全选当前列表')
        self.select_all.clicked.connect(lambda: self._set_all(True))
        self.clear_all = QPushButton('清空选择')
        self.clear_all.clicked.connect(lambda: self._set_all(False))
        self.only_missing = QCheckBox('只看未导出 / 文件缺失的')
        self.only_missing.toggled.connect(self._render)
        refresh = QPushButton('↻ 刷新')
        refresh.clicked.connect(lambda: self.reload(force=True))
        for w in (self.select_all, self.clear_all, self.only_missing):
            tools.addWidget(w)
        tools.addStretch(1)
        tools.addWidget(refresh)
        root.addLayout(tools)

        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 36)
        for col, init_w in ((1, 118), (2, 160), (3, 76), (5, 136)):
            header.setSectionResizeMode(col, QHeaderView.Interactive)
            self.table.setColumnWidth(col, init_w)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.cellClicked.connect(self._toggle_row)
        root.addWidget(self.table, 1)

        from app.ui.resolve_error_dialog import InlineErrorStatusBox
        self.note = QLabel('', objectName='muted')
        self.note_box = InlineErrorStatusBox(
            self.note,
            on_open_detail=lambda info: self._open_note_error(info),
            min_text_width=240,
            parent=self,
        )
        self.note_err_btn = self.note_box.detail_btn
        root.addWidget(self.note_box)

        foot = QHBoxLayout()
        self.selected_label = QLabel('已选 0 个', objectName='cardMeta')
        foot.addWidget(self.selected_label)
        foot.addStretch(1)
        close = QPushButton('关闭')
        close.clicked.connect(self.accept)
        self.go = QPushButton('重新导出选中视频', objectName='primaryBtn')
        self.go.clicked.connect(self._reexport)
        foot.addWidget(close)
        foot.addWidget(self.go)
        root.addLayout(foot)

        self.timer = QTimer(self)
        self.timer.setInterval(3000)
        self.timer.timeout.connect(self.reload)
        self.timer.start()
        self.reload(force=True)

    # ---- data -------------------------------------------------------
    def reload(self, force=False):
        day = work_dates.active()
        try:
            reexport.sync()
        except Exception:
            pass
        rows = [dict(r) for r in repo.list_edit_queue(work_date=day)
                if r['editing_stage'] == 'COMPLETED' or str(r['edit_status'] or '') in ('导出中', '已剪辑')]
        rows.sort(key=_row_key)
        signature = (day, tuple((r['video_id'], r['edit_status']) for r in rows))
        if not force and signature == self._signature:
            return
        self._signature = signature
        self._rows = rows
        for r in rows:
            r['_exists'] = self._exists(r)
        alive = {int(r['video_id']) for r in rows}
        self._checked &= alive
        self._render()

    @staticmethod
    def _exists(row):
        path = str(row.get('edit_output_path') or '').strip()
        try:
            return bool(path) and Path(path).is_file() and Path(path).stat().st_size > 0
        except OSError:
            return False

    def _visible(self):
        needle = self.search.text().strip().lower()
        out = []
        for r in self._rows:
            if self.only_missing.isChecked() and r['_exists']:
                continue
            hay = f"{r['recipient_name']} {r['host_name']} {int(r['video_seq']):02d} {r.get('edit_output_path') or ''}".lower()
            if needle and needle not in hay:
                continue
            out.append(r)
        return out

    # ---- view -------------------------------------------------------
    def _render(self, *_):
        day = work_dates.active()
        rows = self._visible()
        busy = reexport.pending_count(day)
        unexported = sum(1 for r in self._rows if str(r['edit_status'] or '') == '已剪辑')
        done = sum(1 for r in self._rows if str(r['edit_status'] or '') not in ('导出中', '已剪辑'))
        self.title.setText(f'{day} · 剪辑完成 {done} 个视频' + (f' · 另有 {unexported} 个已剪辑但未导出' if unexported else ''))
        model = self.table.model()
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        try:
            if self.table.rowCount() != len(rows):
                self.table.setRowCount(len(rows))
            self.table.setProperty('rows', [int(r['video_id']) for r in rows])
            model.blockSignals(True)
            try:
                for i, r in enumerate(rows):
                    vid = int(r['video_id'])
                    exporting = str(r['edit_status'] or '') == '导出中'
                    not_exported = str(r['edit_status'] or '') == '已剪辑'
                    box = QTableWidgetItem('☑' if vid in self._checked else '☐')
                    box.setTextAlignment(Qt.AlignCenter)
                    path = str(r.get('edit_output_path') or '')
                    status = ('重新导出中…' if exporting else '已剪辑 · 未导出' if not_exported
                              else ('✓ 文件正常' if r['_exists'] else '⚠ 文件缺失'))
                    cells = [box, QTableWidgetItem(str(r['recipient_name'] or '')), QTableWidgetItem(str(r['host_name'] or '')),
                             QTableWidgetItem(f"{int(r['video_seq']):02d}"), QTableWidgetItem(Path(path).name if path else '—'),
                             QTableWidgetItem(status)]
                    cells[4].setToolTip(path)
                    if exporting:
                        for c in cells:
                            c.setForeground(Qt.gray)
                    elif not_exported:
                        cells[5].setForeground(Qt.darkYellow)
                    elif not r['_exists']:
                        cells[5].setForeground(Qt.red)
                    for col, item in enumerate(cells):
                        self.table.setItem(i, col, item)
            finally:
                model.blockSignals(False)
        finally:
            self.table.blockSignals(False)
            self.table.setUpdatesEnabled(True)
            self.table.viewport().update()
        message = reexport.last_message(day)
        if busy:
            message = '正在重新导出，请在达芬奇里等待渲染完成；完成后这里会自动更新。'
        self.note_box.set_raw_status(
            message or '点击任意一行勾选；重新导出会把选中视频按当前时间线再渲染一次，旧文件会在新文件成功后才被替换。'
        )
        self._refresh_footer(busy)

    def _open_note_error(self, info):
        from app.ui.resolve_error_dialog import open_editing_error_detail
        parent_log_cb = getattr(self.parent(), 'view_batch_log', None)
        open_editing_error_detail(self, info, on_view_log=parent_log_cb)

    def _refresh_footer(self, busy=None):
        busy = reexport.pending_count(work_dates.active()) if busy is None else busy
        count = len(self._checked)
        self.selected_label.setText(f'已选 {count} 个')
        self.go.setText(f'重新导出选中视频（{count}）' if count else '重新导出选中视频')
        self.go.setEnabled(bool(count) and not busy)

    def _toggle_row(self, row, _col):
        ids = self.table.property('rows') or []
        if row >= len(ids):
            return
        vid = int(ids[row])
        item = self.table.item(row, 3)
        if item and str(self.table.item(row, 5).text()).startswith('重新导出中'):
            return
        if vid in self._checked:
            self._checked.discard(vid)
        else:
            self._checked.add(vid)
        self.table.item(row, 0).setText('☑' if vid in self._checked else '☐')
        self._refresh_footer()

    def _set_all(self, value):
        for r in self._visible():
            if str(r['edit_status'] or '') == '导出中':
                continue
            (self._checked.add if value else self._checked.discard)(int(r['video_id']))
        self._render()

    # ---- action -----------------------------------------------------
    def _reexport(self):
        ids = sorted(self._checked)
        if not ids:
            return
        missing = sum(1 for r in self._rows if int(r['video_id']) in self._checked and not r['_exists'])
        text = (f'将重新导出选中的 {len(ids)} 个视频。\n\n'
                '• 使用达芬奇当前时间线上的画面，按原文件名重新渲染\n'
                '• 旧成品会先备份，新文件导出成功后才删除；失败会自动恢复\n'
                '• 需要达芬奇已唤醒并打开当天项目，导出期间请不要操作达芬奇\n')
        if missing:
            text += f'\n其中 {missing} 个视频的成品文件已缺失，会直接补导出。\n'
        if QMessageBox.question(self, '重新导出选中视频', text + '\n继续吗？') != QMessageBox.Yes:
            return
        try:
            result = reexport.submit(work_dates.active(), ids)
        except Exception as exc:
            from app.ui.resolve_error_dialog import show_editing_warning
            show_editing_warning(
                self,
                '重新导出选中视频',
                str(exc),
                batch_status='EXPORT_ERROR',
                on_view_log=getattr(self.parent(), 'view_batch_log', None),
            )
            return
        self._checked.clear()
        self.reload(force=True)
        QMessageBox.information(self, '重新导出选中视频', result['detail'] + '。达芬奇开始渲染后，状态会在这里更新。')
