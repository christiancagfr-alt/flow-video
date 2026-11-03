"""Google-Sheets-style Manual Task Entry Dialog for Flow Studio Task Center.

Key design guarantees:
- Starts completely blank (zero pre-filled recipient / host / mode / watermark / sample values).
- Every empty cell renders subtle, replaceable muted-gray placeholder text that disappears immediately
  upon typing or pasting.
- Supports multi-row, multi-column TSV bulk paste (`Cmd+V` / `Ctrl+V`) directly from Google Sheets,
  Excel, Numbers, or Feishu — preserving multi-line cells, auto-appending rows, and preserving red/black
  text color runs (`red = 睁眼说话`, `black = 闭眼祷告`) when copied from rich HTML spreadsheets.
- Supports `Cmd+C` copy, `Cmd+X` cut, `Cmd+D` fill-down, `Delete`/`Backspace` clear, `Cmd+Z` undo,
  `Cmd+Shift+Z` redo, and drag-and-drop of local image files or folders.
- Chinese script column is optional and explicitly labeled only for Prompt Center cross-checking
  (`选填：在提示词中心核对`).
"""
from __future__ import annotations

import copy
from pathlib import Path

from PySide6.QtCore import QEvent, QRect, Qt, QThread, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QKeySequence,
    QPainter,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextOption,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core import work_dates
from app.services import manual_task_intake as mti
from app.services.file_filters import IMAGE_EXTENSIONS

COL_RECIPIENT = 0
COL_HOST = 1
COL_PERF_MODE = 2
COL_FOREIGN = 3
COL_CHINESE = 4
COL_IMAGE = 5
COL_WATERMARK = 6
NUM_COLS = 7
COL_ASPECT = -1  # Deprecated: aspect ratio is now fully auto-detected from image dimensions

COLUMN_HEADERS = [
    "接收人 *",
    "主播名称 *",
    "表演模式",
    "外文口播文案 *",
    "中文文案（选填）",
    "图片 / 素材路径 *",
    "素材来源（水印）",
]

COLUMN_PLACEHOLDERS = {
    COL_RECIPIENT: "填写接收人",
    COL_HOST: "填写主播名",
    COL_PERF_MODE: "默认睁眼（可填闭眼/混合）",
    COL_FOREIGN: "粘贴或输入外文文案（支持多行粘贴、选中文字标红睁眼）",
    COL_CHINESE: "选填：在提示词中心核对",
    COL_IMAGE: "选单图或目录（同主播可共用）",
    COL_WATERMARK: "选填：副水印名",
}

COLUMN_WIDTHS = [
    115,  # 接收人
    125,  # 主播名称
    145,  # 表演模式
    360,  # 外文口播文案
    230,  # 中文文案（选填）
    220,  # 图片 / 素材路径
    135,  # 素材来源（水印）
]

ROLE_RED_SPANS = Qt.UserRole + 11


def _is_dark_palette(widget: QWidget | None) -> bool:
    if widget is None:
        return False
    return widget.palette().window().color().lightness() < 128


def _red_ink(dark: bool) -> QColor:
    return QColor("#f87171") if dark else QColor("#dc2626")


def _placeholder_ink(dark: bool) -> QColor:
    return QColor("#64748b") if dark else QColor("#94a3b8")


def _extract_editor_red_spans(doc: QTextDocument) -> tuple[str, list[tuple[int, int]]]:
    plain = doc.toPlainText().replace("\r\n", "\n").replace("\r", "\n")
    if not plain:
        return "", []
    spans: list[tuple[int, int]] = []
    block = doc.begin()
    pos_offset = 0
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid():
                frag_txt = frag.text().replace("\u2029", "\n")
                fmt = frag.charFormat()
                if fmt.hasProperty(QTextCharFormat.ForegroundBrush):
                    c = fmt.foreground().color()
                    if c.isValid() and c.red() >= 140 and c.red() > c.green() * 1.4 and c.red() > c.blue() * 1.4:
                        start = frag.position()
                        spans.append((start, start + len(frag_txt)))
            it += 1
        pos_offset += block.length()
        block = block.next()
    return plain, mti.normalize_red_spans(plain, spans)


def _populate_rich_document(doc: QTextDocument, text: str, red_spans, base_color: QColor, red_color: QColor, font: QFont):
    doc.clear()
    doc.setDefaultFont(font)
    if not text:
        return
    spans = mti.normalize_red_spans(text, red_spans)
    cursor = QTextCursor(doc)
    base_fmt = QTextCharFormat()
    base_fmt.setForeground(base_color)
    red_fmt = QTextCharFormat()
    red_fmt.setForeground(red_color)
    if not spans:
        cursor.insertText(text, base_fmt)
        return
    pos = 0
    for s, e in spans:
        if s > pos:
            cursor.insertText(text[pos:s], base_fmt)
        cursor.insertText(text[s:e], red_fmt)
        pos = e
    if pos < len(text):
        cursor.insertText(text[pos:], base_fmt)


class _RichScriptEditor(QTextEdit):
    """Multi-line cell editor for Foreign Script supporting red/default text runs & Google Sheets shortcuts."""
    commit_and_move = Signal(int, int)

    def __init__(self, parent=None, placeholder: str = ""):
        super().__init__(parent)
        self.setAcceptRichText(False)
        self.setPlaceholderText(placeholder)
        self.setFrameShape(QFrame.NoFrame)
        self.setTabChangesFocus(True)

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        if key in (Qt.Key_Return, Qt.Key_Enter):
            if mods & (Qt.AltModifier | Qt.ShiftModifier | Qt.MetaModifier):
                self.textCursor().insertText("\n")
                event.accept()
                return
            self.commit_and_move.emit(1, 0)
            event.accept()
            return
        if key == Qt.Key_Tab:
            self.commit_and_move.emit(0, -1 if (mods & Qt.ShiftModifier) else 1)
            event.accept()
            return
        super().keyPressEvent(event)


class _PlainScriptEditor(QPlainTextEdit):
    """Multi-line plain text cell editor for Chinese Script."""
    commit_and_move = Signal(int, int)

    def __init__(self, parent=None, placeholder: str = ""):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setFrameShape(QFrame.NoFrame)
        self.setTabChangesFocus(True)

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        if key in (Qt.Key_Return, Qt.Key_Enter):
            if mods & (Qt.AltModifier | Qt.ShiftModifier | Qt.MetaModifier):
                self.insertPlainText("\n")
                event.accept()
                return
            self.commit_and_move.emit(1, 0)
            event.accept()
            return
        if key == Qt.Key_Tab:
            self.commit_and_move.emit(0, -1 if (mods & Qt.ShiftModifier) else 1)
            event.accept()
            return
        super().keyPressEvent(event)


class _ManualCellDelegate(QStyledItemDelegate):
    def __init__(self, table: "ManualTaskSpreadsheet"):
        super().__init__(table)
        self.table = table

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        col = index.column()
        raw_text = str(index.data(Qt.DisplayRole) or "")
        red_spans = index.data(ROLE_RED_SPANS) or []
        dark = _is_dark_palette(self.table)

        # Draw cell background / selection highlight first without text
        style = opt.widget.style() if opt.widget else QApplication.style()
        opt_bg = QStyleOptionViewItem(opt)
        opt_bg.text = ""
        style.drawControl(QStyle.CE_ItemViewItem, opt_bg, painter, opt.widget)

        rect = opt.rect.adjusted(8, 5, -8, -5)
        if rect.width() <= 4 or rect.height() <= 4:
            return

        painter.save()
        painter.setFont(opt.font)
        if not raw_text:
            ph = COLUMN_PLACEHOLDERS.get(col, "") if index.row() == 0 else ""
            if ph:
                painter.setPen(_placeholder_ink(dark))
                align = Qt.AlignLeft | (Qt.AlignTop if col in (COL_FOREIGN, COL_CHINESE) else Qt.AlignVCenter)
                flags = align | (Qt.TextWordWrap if col in (COL_FOREIGN, COL_CHINESE) else 0)
                elided = ph if col in (COL_FOREIGN, COL_CHINESE) else opt.fontMetrics.elidedText(ph, Qt.ElideRight, rect.width())
                painter.drawText(rect, flags, elided)
            painter.restore()
            return

        if col == COL_FOREIGN and red_spans:
            doc = QTextDocument()
            doc.setDocumentMargin(0)
            doc.setTextWidth(rect.width())
            t_opt = QTextOption()
            t_opt.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
            doc.setDefaultTextOption(t_opt)
            base_c = opt.palette.highlightedText().color() if (opt.state & QStyle.State_Selected) else opt.palette.text().color()
            _populate_rich_document(doc, raw_text, red_spans, base_c, _red_ink(dark), opt.font)
            painter.translate(rect.topLeft())
            painter.setClipRect(QRect(0, 0, rect.width(), rect.height()))
            doc.drawContents(painter)
            painter.restore()
            return

        txt_color = opt.palette.highlightedText().color() if (opt.state & QStyle.State_Selected) else opt.palette.text().color()
        painter.setPen(txt_color)
        if col in (COL_FOREIGN, COL_CHINESE):
            painter.drawText(rect, Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, raw_text)
        else:
            elided = opt.fontMetrics.elidedText(raw_text, Qt.ElideMiddle if col == COL_IMAGE else Qt.ElideRight, rect.width())
            painter.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter, elided)
        painter.restore()

    def createEditor(self, parent, option, index):
        col = index.column()
        ph = COLUMN_PLACEHOLDERS.get(col, "") if index.row() == 0 else ""
        if col == COL_PERF_MODE:
            cb = QComboBox(parent)
            cb.setEditable(True)
            cb.addItems(["", "睁眼说话", "闭眼祷告", "红睁黑闭混合"])
            if cb.lineEdit():
                cb.lineEdit().setPlaceholderText(ph)
            return cb
        if col == COL_FOREIGN:
            ed = _RichScriptEditor(parent, placeholder=ph)
            self.table._active_script_editor = ed
            self.table._active_script_index = (index.row(), index.column())
            ed.destroyed.connect(self.table._clear_active_script_editor)
            ed.commit_and_move.connect(lambda dr, dc, ed_ref=ed: self.table._commit_custom_editor(ed_ref, dr, dc))
            return ed
        if col == COL_CHINESE:
            ed = _PlainScriptEditor(parent, placeholder=ph)
            ed.commit_and_move.connect(lambda dr, dc, ed_ref=ed: self.table._commit_custom_editor(ed_ref, dr, dc))
            return ed
        le = QLineEdit(parent)
        le.setPlaceholderText(ph)
        le.setFrame(False)
        return le

    def setEditorData(self, editor, index):
        col = index.column()
        val = str(index.data(Qt.EditRole) or "")
        if isinstance(editor, QComboBox):
            editor.setCurrentText(val)
            return
        if isinstance(editor, _RichScriptEditor):
            dark = _is_dark_palette(self.table)
            base_c = self.table.palette().text().color()
            spans = index.data(ROLE_RED_SPANS) or []
            _populate_rich_document(editor.document(), val, spans, base_c, _red_ink(dark), self.table.font())
            cursor = editor.textCursor()
            cursor.movePosition(QTextCursor.End)
            editor.setTextCursor(cursor)
            return
        if isinstance(editor, _PlainScriptEditor):
            editor.setPlainText(val)
            cursor = editor.textCursor()
            cursor.movePosition(QTextCursor.End)
            editor.setTextCursor(cursor)
            return
        if isinstance(editor, QLineEdit):
            editor.setText(val)

    def setModelData(self, editor, model, index):
        row, col = index.row(), index.column()
        self.table._push_undo_if_needed()
        self.table._suppress_cell_signal = True
        try:
            if isinstance(editor, QComboBox):
                raw = editor.currentText().strip()
                if col == COL_PERF_MODE:
                    fx_item = self.table.item(row, COL_FOREIGN)
                    has_red = bool(fx_item and (fx_item.data(ROLE_RED_SPANS) or []))
                    norm = mti.display_perf_mode(raw, has_red_spans=has_red) if raw else (
                        "红睁黑闭混合" if has_red else ""
                    )
                    model.setData(index, norm, Qt.EditRole)
                else:
                    norm = mti.normalize_aspect_ratio(raw, fallback="")
                    model.setData(index, norm, Qt.EditRole)
            elif isinstance(editor, _RichScriptEditor):
                plain, spans = _extract_editor_red_spans(editor.document())
                model.setData(index, plain, Qt.EditRole)
                model.setData(index, spans, ROLE_RED_SPANS)
                if spans:
                    pm_item = self.table._ensure_item(row, COL_PERF_MODE)
                    if not pm_item.text().strip() or pm_item.text().strip() == "睁眼说话":
                        pm_item.setText("红睁黑闭混合")
            elif isinstance(editor, _PlainScriptEditor):
                model.setData(index, editor.toPlainText().replace("\r\n", "\n").replace("\r", "\n"), Qt.EditRole)
            elif isinstance(editor, QLineEdit):
                txt = editor.text().strip()
                model.setData(index, txt, Qt.EditRole)
                if col == COL_IMAGE and txt:
                    self.table._auto_detect_row_aspect(row, txt)
        finally:
            self.table._suppress_cell_signal = False
        self.table._adjust_row_height(row)
        self.table.content_modified.emit()


class ManualTaskSpreadsheet(QTableWidget):
    """Spreadsheet widget supporting Google-Sheets-like bulk paste, copy, cut, fill-down, undo/redo, and drag-drop."""
    content_modified = Signal()

    def __init__(self, parent=None):
        super().__init__(0, NUM_COLS, parent)
        self._undo_stack: list[list[dict]] = []
        self._redo_stack: list[list[dict]] = []
        self._suppress_cell_signal = False
        self._active_script_editor: _RichScriptEditor | None = None
        self._active_script_index: tuple[int, int] | None = None

        self.setHorizontalHeaderLabels(COLUMN_HEADERS)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.setEditTriggers(
            QAbstractItemView.DoubleClicked
            | QAbstractItemView.EditKeyPressed
            | QAbstractItemView.AnyKeyPressed
        )
        self.setAcceptDrops(True)
        self.setWordWrap(True)
        self.setAlternatingRowColors(False)
        self.verticalHeader().setDefaultSectionSize(54)
        self.verticalHeader().setMinimumWidth(36)
        self.verticalHeader().setDefaultAlignment(Qt.AlignCenter)

        hh = self.horizontalHeader()
        hh.setStretchLastSection(False)
        for c, w in enumerate(COLUMN_WIDTHS):
            self.setColumnWidth(c, w)
            hh.setSectionResizeMode(c, QHeaderView.Interactive)
        hh.setSectionResizeMode(COL_FOREIGN, QHeaderView.Stretch)

        self._delegate = _ManualCellDelegate(self)
        self.setItemDelegate(self._delegate)
        self.cellChanged.connect(self._on_cell_changed)

    def _clear_active_script_editor(self, *_args):
        self._active_script_editor = None
        self._active_script_index = None

    def _commit_custom_editor(self, editor: QWidget, delta_row: int, delta_col: int):
        cur_row, cur_col = self.currentRow(), self.currentColumn()
        self.commitData(editor)
        self.closeEditor(editor, QStyledItemDelegate.NoHint)
        self._clear_active_script_editor()
        next_r = cur_row + delta_row
        next_c = cur_col + delta_col
        if next_c >= NUM_COLS:
            next_c = 0
            next_r += 1
        elif next_c < 0:
            next_c = NUM_COLS - 1
            next_r -= 1
        if delta_row > 0 and next_r >= self.rowCount():
            self.append_blank_rows(1, record_undo=False)
        if 0 <= next_r < self.rowCount() and 0 <= next_c < NUM_COLS:
            self.setCurrentCell(next_r, next_c)

    def _ensure_item(self, row: int, col: int) -> QTableWidgetItem:
        it = self.item(row, col)
        if it is None:
            it = QTableWidgetItem("")
            it.setData(ROLE_RED_SPANS, [])
            self.setItem(row, col, it)
        return it

    def _on_cell_changed(self, row: int, col: int):
        if self._suppress_cell_signal:
            return
        if col == COL_IMAGE:
            it = self.item(row, col)
        self._adjust_row_height(row)
        self.content_modified.emit()

    def _auto_detect_row_aspect(self, row: int, img_path: str):
        pass

    def _adjust_row_height(self, row: int):
        if row < 0 or row >= self.rowCount():
            return
        fx = self.item(row, COL_FOREIGN)
        zh = self.item(row, COL_CHINESE)
        fx_txt = fx.text() if fx else ""
        zh_txt = zh.text() if zh else ""
        lines = max(fx_txt.count("\n") + 1, zh_txt.count("\n") + 1, max(1, len(fx_txt) // 36 + 1), max(1, len(zh_txt) // 22 + 1))
        target_h = max(54, min(180, 26 + lines * 20))
        self.setRowHeight(row, target_h)

    def export_rows(self) -> list[dict]:
        out: list[dict] = []
        for r in range(self.rowCount()):
            fx_it = self.item(r, COL_FOREIGN)
            out.append({
                "recipient": (self.item(r, COL_RECIPIENT).text() if self.item(r, COL_RECIPIENT) else ""),
                "host": (self.item(r, COL_HOST).text() if self.item(r, COL_HOST) else ""),
                "perf_mode": (self.item(r, COL_PERF_MODE).text() if self.item(r, COL_PERF_MODE) else ""),
                "foreign_text": (fx_it.text() if fx_it else ""),
                "chinese_text": (self.item(r, COL_CHINESE).text() if self.item(r, COL_CHINESE) else ""),
                "image_path": (self.item(r, COL_IMAGE).text() if self.item(r, COL_IMAGE) else ""),
                "aspect_ratio": "",
                "material_source": (self.item(r, COL_WATERMARK).text() if self.item(r, COL_WATERMARK) else ""),
                "red_spans": list((fx_it.data(ROLE_RED_SPANS) if fx_it else None) or []),
            })
        return out

    def load_rows(self, rows: list[dict], *, min_rows: int = 8):
        self._suppress_cell_signal = True
        try:
            total = max(min_rows, len(rows))
            self.setRowCount(total)
            for r in range(total):
                src = rows[r] if r < len(rows) else {}
                vals = [
                    str(src.get("recipient") or ""),
                    str(src.get("host") or ""),
                    str(src.get("perf_mode") or ""),
                    str(src.get("foreign_text") or ""),
                    str(src.get("chinese_text") or ""),
                    str(src.get("image_path") or ""),
                    str(src.get("material_source") or ""),
                ]
                spans = mti.normalize_red_spans(vals[COL_FOREIGN], src.get("red_spans"))
                for c in range(NUM_COLS):
                    it = self._ensure_item(r, c)
                    it.setText(vals[c])
                    it.setData(ROLE_RED_SPANS, spans if c == COL_FOREIGN else [])
                self._adjust_row_height(r)
        finally:
            self._suppress_cell_signal = False
        self.viewport().update()
        self.content_modified.emit()

    def _push_undo_if_needed(self):
        snap = copy.deepcopy(self.export_rows())
        if not self._undo_stack or self._undo_stack[-1] != snap:
            self._undo_stack.append(snap)
            if len(self._undo_stack) > 50:
                self._undo_stack.pop(0)
            self._redo_stack.clear()

    def undo(self):
        if not self._undo_stack:
            return
        cur = copy.deepcopy(self.export_rows())
        prev = self._undo_stack.pop()
        self._redo_stack.append(cur)
        self.load_rows(prev, min_rows=max(1, len(prev)))

    def redo(self):
        if not self._redo_stack:
            return
        cur = copy.deepcopy(self.export_rows())
        nxt = self._redo_stack.pop()
        self._undo_stack.append(cur)
        self.load_rows(nxt, min_rows=max(1, len(nxt)))

    def append_blank_rows(self, count: int = 1, *, record_undo: bool = True):
        if count <= 0:
            return
        if record_undo:
            self._push_undo_if_needed()
        self._suppress_cell_signal = True
        try:
            start = self.rowCount()
            self.setRowCount(start + count)
            for r in range(start, start + count):
                for c in range(NUM_COLS):
                    it = self._ensure_item(r, c)
                    it.setText("")
                    it.setData(ROLE_RED_SPANS, [])
                self.setRowHeight(r, 54)
        finally:
            self._suppress_cell_signal = False
        self.content_modified.emit()

    def delete_selected_rows(self):
        rows = sorted({idx.row() for idx in self.selectedIndexes()}, reverse=True)
        if not rows and self.currentRow() >= 0:
            rows = [self.currentRow()]
        if not rows:
            return
        self._push_undo_if_needed()
        self._suppress_cell_signal = True
        try:
            for r in rows:
                if self.rowCount() > 1:
                    self.removeRow(r)
                else:
                    for c in range(NUM_COLS):
                        it = self._ensure_item(0, c)
                        it.setText("")
                        it.setData(ROLE_RED_SPANS, [])
        finally:
            self._suppress_cell_signal = False
        self.viewport().update()
        self.content_modified.emit()

    def duplicate_current_row(self):
        src_rows = sorted({idx.row() for idx in self.selectedIndexes()})
        if not src_rows and self.currentRow() >= 0:
            src_rows = [self.currentRow()]
        if not src_rows:
            return
        self._push_undo_if_needed()
        all_rows = self.export_rows()
        insert_at = src_rows[-1] + 1
        clones = [copy.deepcopy(all_rows[r]) for r in src_rows]
        new_rows = all_rows[:insert_at] + clones + all_rows[insert_at:]
        self.load_rows(new_rows, min_rows=len(new_rows))
        self.setCurrentCell(insert_at, max(0, self.currentColumn()))

    def clear_selected_cells(self):
        indexes = self.selectedIndexes()
        if not indexes:
            return
        self._push_undo_if_needed()
        self._suppress_cell_signal = True
        try:
            touched_rows = set()
            for idx in indexes:
                r, c = idx.row(), idx.column()
                it = self._ensure_item(r, c)
                it.setText("")
                it.setData(ROLE_RED_SPANS, [])
                touched_rows.add(r)
            for r in touched_rows:
                self._adjust_row_height(r)
        finally:
            self._suppress_cell_signal = False
        self.viewport().update()
        self.content_modified.emit()

    def copy_selection_to_clipboard(self, *, cut: bool = False):
        indexes = self.selectedIndexes()
        if not indexes:
            return
        min_r = min(i.row() for i in indexes)
        max_r = max(i.row() for i in indexes)
        min_c = min(i.column() for i in indexes)
        max_c = max(i.column() for i in indexes)
        selected_set = {(i.row(), i.column()) for i in indexes}
        matrix: list[list[str]] = []
        for r in range(min_r, max_r + 1):
            row_vals: list[str] = []
            for c in range(min_c, max_c + 1):
                if (r, c) in selected_set and self.item(r, c):
                    row_vals.append(self.item(r, c).text())
                else:
                    row_vals.append("")
            matrix.append(row_vals)
        QApplication.clipboard().setText(mti.format_tsv_grid(matrix))
        if cut:
            self.clear_selected_cells()

    def fill_down_selection(self):
        """Google Sheets Cmd+D / Ctrl+D: copy top cell of each selected column down into selected rows."""
        indexes = self.selectedIndexes()
        if len(indexes) < 2:
            return
        by_col: dict[int, list[int]] = {}
        for idx in indexes:
            by_col.setdefault(idx.column(), []).append(idx.row())
        if not any(len(rlist) >= 2 for rlist in by_col.values()):
            return
        self._push_undo_if_needed()
        self._suppress_cell_signal = True
        try:
            for c, rlist in by_col.items():
                rlist.sort()
                top_r = rlist[0]
                src_it = self._ensure_item(top_r, c)
                src_txt = src_it.text()
                src_spans = list(src_it.data(ROLE_RED_SPANS) or [])
                for r in rlist[1:]:
                    dst_it = self._ensure_item(r, c)
                    dst_it.setText(src_txt)
                    dst_it.setData(ROLE_RED_SPANS, list(src_spans) if c == COL_FOREIGN else [])
                    if c == COL_IMAGE and src_txt:
                        self._auto_detect_row_aspect(r, src_txt)
                    self._adjust_row_height(r)
        finally:
            self._suppress_cell_signal = False
        self.viewport().update()
        self.content_modified.emit()

    def paste_from_clipboard(self):
        mime = QApplication.clipboard().mimeData()
        if mime is None:
            return
        # Support pasting files copied directly from macOS Finder!
        if mime.hasUrls():
            local_paths = [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]
            if local_paths:
                self.apply_dropped_paths(local_paths)
                return
        plain = mime.text() if mime.hasText() else ""
        html = mime.html() if mime.hasHtml() else ""
        self.paste_grid_data(plain, html)

    def paste_grid_data(self, plain_text: str, html_text: str = ""):
        grid = mti.parse_clipboard_grid(plain_text, html_text)
        if not grid:
            return
        indexes = self.selectedIndexes()
        if indexes:
            start_r = min(i.row() for i in indexes)
            start_c = min(i.column() for i in indexes)
        else:
            start_r = max(0, self.currentRow())
            start_c = max(0, self.currentColumn())

        self._push_undo_if_needed()
        self._suppress_cell_signal = True
        try:
            # Google Sheets behavior: if clipboard is 1x1 and user selected multiple cells, fill entire selection!
            if len(grid) == 1 and len(grid[0]) == 1 and len(indexes) > 1:
                cell_obj = grid[0][0]
                for idx in indexes:
                    self._apply_pasted_cell(idx.row(), idx.column(), cell_obj["text"], cell_obj["red_spans"])
                for r in {i.row() for i in indexes}:
                    self._adjust_row_height(r)
            else:
                needed_rows = start_r + len(grid)
                if needed_rows > self.rowCount():
                    old_cnt = self.rowCount()
                    self.setRowCount(needed_rows)
                    for r in range(old_cnt, needed_rows):
                        for c in range(NUM_COLS):
                            it = self._ensure_item(r, c)
                            it.setText("")
                            it.setData(ROLE_RED_SPANS, [])
                        self.setRowHeight(r, 54)
                for r_off, row_cells in enumerate(grid):
                    target_r = start_r + r_off
                    for c_off, cell_obj in enumerate(row_cells):
                        target_c = start_c + c_off
                        if target_c >= NUM_COLS:
                            break
                        self._apply_pasted_cell(target_r, target_c, cell_obj["text"], cell_obj["red_spans"])
                    self._adjust_row_height(target_r)
        finally:
            self._suppress_cell_signal = False
        self.viewport().update()
        self.content_modified.emit()

    def _apply_pasted_cell(self, row: int, col: int, raw_val: str, red_spans):
        it = self._ensure_item(row, col)
        if col == COL_FOREIGN:
            txt = str(raw_val or "")
            spans = mti.normalize_red_spans(txt, red_spans)
            it.setText(txt)
            it.setData(ROLE_RED_SPANS, spans)
            if spans:
                pm_it = self._ensure_item(row, COL_PERF_MODE)
                if not pm_it.text().strip() or pm_it.text().strip() == "睁眼说话":
                    pm_it.setText("红睁黑闭混合")
            return
        if col == COL_CHINESE:
            it.setText(str(raw_val or ""))
            return
        txt = str(raw_val or "").strip()
        if col == COL_PERF_MODE:
            fx_it = self.item(row, COL_FOREIGN)
            has_red = bool(fx_it and (fx_it.data(ROLE_RED_SPANS) or []))
            it.setText(mti.display_perf_mode(txt, has_red_spans=has_red) if txt else ("红睁黑闭混合" if has_red else ""))
        elif col == COL_IMAGE:
            it.setText(txt)
        else:
            it.setText(txt)

    def mark_foreign_color(self, make_red: bool):
        """Mark active selection in _RichScriptEditor or selected COL_FOREIGN cells as Red (TALKING) or Default (PRAYING)."""
        dark = _is_dark_palette(self)
        ed = self._active_script_editor
        if ed is not None and ed.isVisible():
            cursor = ed.textCursor()
            if not cursor.hasSelection():
                cursor.select(QTextCursor.Document)
            fmt = QTextCharFormat()
            fmt.setForeground(_red_ink(dark) if make_red else self.palette().text().color())
            cursor.mergeCharFormat(fmt)
            if self._active_script_index is not None:
                r, _ = self._active_script_index
                plain, spans = _extract_editor_red_spans(ed.document())
                if spans:
                    pm_it = self._ensure_item(r, COL_PERF_MODE)
                    if not pm_it.text().strip() or pm_it.text().strip() == "睁眼说话":
                        self._suppress_cell_signal = True
                        try:
                            pm_it.setText("红睁黑闭混合")
                        finally:
                            self._suppress_cell_signal = False
            ed.setFocus()
            return

        target_rows = sorted({i.row() for i in self.selectedIndexes() if i.column() == COL_FOREIGN})
        if not target_rows and self.currentRow() >= 0:
            target_rows = [self.currentRow()]
        if not target_rows:
            return
        self._push_undo_if_needed()
        self._suppress_cell_signal = True
        try:
            for r in target_rows:
                fx_it = self._ensure_item(r, COL_FOREIGN)
                txt = fx_it.text()
                if not txt:
                    continue
                fx_it.setData(ROLE_RED_SPANS, [(0, len(txt))] if make_red else [])
                pm_it = self._ensure_item(r, COL_PERF_MODE)
                pm_it.setText("睁眼说话" if make_red else "闭眼祷告")
        finally:
            self._suppress_cell_signal = False
        self.viewport().update()
        self.content_modified.emit()

    def apply_dropped_paths(self, paths: list[str], *, anchor_row: int | None = None):
        clean_paths = [str(p).strip() for p in paths if str(p).strip()]
        if not clean_paths:
            return
        selected_rows = sorted({i.row() for i in self.selectedIndexes()})
        if anchor_row is None:
            anchor_row = selected_rows[0] if selected_rows else max(0, self.currentRow())

        self._push_undo_if_needed()
        self._suppress_cell_signal = True
        try:
            if len(clean_paths) == 1 and len(selected_rows) > 1:
                for r in selected_rows:
                    it = self._ensure_item(r, COL_IMAGE)
                    it.setText(clean_paths[0])
                    self._auto_detect_row_aspect(r, clean_paths[0])
            else:
                needed = anchor_row + len(clean_paths)
                if needed > self.rowCount():
                    self.append_blank_rows(needed - self.rowCount(), record_undo=False)
                for idx, p_str in enumerate(clean_paths):
                    r = anchor_row + idx
                    it = self._ensure_item(r, COL_IMAGE)
                    it.setText(p_str)
                    self._auto_detect_row_aspect(r, p_str)
        finally:
            self._suppress_cell_signal = False
        self.viewport().update()
        self.content_modified.emit()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not event.mimeData().hasUrls():
            event.ignore()
            return
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if not paths:
            event.ignore()
            return
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        hit = self.indexAt(pos)
        row = hit.row() if hit.isValid() else max(0, self.rowCount() - 1)
        self.apply_dropped_paths(paths, anchor_row=row)
        event.acceptProposedAction()

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Paste):
            self.paste_from_clipboard()
            event.accept()
            return
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_selection_to_clipboard(cut=False)
            event.accept()
            return
        if event.matches(QKeySequence.StandardKey.Cut):
            self.copy_selection_to_clipboard(cut=True)
            event.accept()
            return
        if event.matches(QKeySequence.StandardKey.Undo):
            self.undo()
            event.accept()
            return
        if event.matches(QKeySequence.StandardKey.Redo):
            self.redo()
            event.accept()
            return
        mods = event.modifiers()
        key = event.key()
        if (mods & (Qt.ControlModifier | Qt.MetaModifier)) and key == Qt.Key_D:
            self.fill_down_selection()
            event.accept()
            return
        if key in (Qt.Key_Delete, Qt.Key_Backspace) and self.state() != QAbstractItemView.EditingState:
            self.clear_selected_cells()
            event.accept()
            return
        super().keyPressEvent(event)


class _ImportWorker(QThread):
    finished_ok = Signal(dict)
    failed_err = Signal(str)

    def __init__(self, rows: list[dict], work_date: str, parent=None):
        super().__init__(parent)
        self.rows = rows
        self.work_date = work_date

    def run(self):
        try:
            res = mti.import_manual_tasks(self.rows, work_date=self.work_date)
            self.finished_ok.emit(res)
        except Exception as exc:
            self.failed_err.emit(str(exc))


class ManualTaskDialog(QDialog):
    """Spreadsheet-based manual task creation dialog for Task Center."""
    tasks_imported = Signal(dict)

    def __init__(self, parent=None, *, work_date: str | None = None):
        super().__init__(parent)
        self.work_date = work_dates.canonical(work_date) or work_dates.active()
        self._worker: _ImportWorker | None = None
        self.setWindowTitle(f"手动填写任务 · 工作日期 {self.work_date}")
        self.resize(1320, 740)
        self.setMinimumSize(960, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        # ── Header
        header_row = QHBoxLayout()
        header_row.setSpacing(10)
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel(f"✎ 手动填写任务（{self.work_date}）")
        title.setStyleSheet("font-size:18px;font-weight:800;")
        subtitle = QLabel(
            "支持像 Google 云端表格一样直接框选多行多列批量粘贴（Cmd+V / Ctrl+V）、向下填充（Cmd+D）与撤销（Cmd+Z）；"
            "从云端表格复制带颜色的外文文案会自动保留红字（睁眼说话）与黑字（闭眼祷告）。",
            objectName="muted",
        )
        subtitle.setWordWrap(True)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header_row.addLayout(title_box, 1)
        root.addLayout(header_row)

        # ── Toolbar (all buttons Qt.NoFocus where needed so active text selection in editor stays intact!)
        toolbar_frame = QFrame(objectName="topStrip")
        tb = QHBoxLayout(toolbar_frame)
        tb.setContentsMargins(10, 8, 10, 8)
        tb.setSpacing(6)

        def _make_tb_btn(text: str, tip: str = "", click_cb=None, no_focus: bool = False) -> QPushButton:
            btn = QPushButton(text)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(30)
            if no_focus:
                btn.setFocusPolicy(Qt.NoFocus)
            if tip:
                btn.setToolTip(tip)
            if click_cb:
                btn.clicked.connect(click_cb)
            needed_w = btn.fontMetrics().horizontalAdvance(text) + 20
            btn.setMinimumWidth(needed_w)
            return btn

        btn_add1 = _make_tb_btn("＋ 新增 1 行", "在表格末尾追加 1 行空白任务", lambda: self.table.append_blank_rows(1))
        tb.addWidget(btn_add1)

        btn_add5 = _make_tb_btn("＋ 新增 5 行", "在表格末尾追加 5 行空白任务", lambda: self.table.append_blank_rows(5))
        tb.addWidget(btn_add5)

        btn_dup = _make_tb_btn("⧉ 复制行", "复制当前选中的行并插入到下方", self.table_duplicate_row)
        tb.addWidget(btn_dup)

        btn_del = _make_tb_btn("✕ 删除行", "删除当前选中的行", self.table_delete_rows)
        tb.addWidget(btn_del)

        tb.addSpacing(6)

        btn_red = _make_tb_btn(
            "🔴 标红（睁眼）",
            "双击外文文案单元格选中句子后点击，标记为睁眼说话（红字）",
            lambda: self.table.mark_foreign_color(True),
            no_focus=True,
        )
        tb.addWidget(btn_red)

        btn_black = _make_tb_btn(
            "⚫ 标黑（闭眼）",
            "双击外文文案单元格选中句子后点击，标记为闭眼祷告（默认黑字）",
            lambda: self.table.mark_foreign_color(False),
            no_focus=True,
        )
        tb.addWidget(btn_black)

        tb.addSpacing(6)

        btn_pick_img = _make_tb_btn(
            "🖼 选单图…",
            "为当前选中行选择本地图片（支持一次多选图片按行填入，或多选表格行批量填入同一张图）",
            self.pick_images_for_selection,
        )
        tb.addWidget(btn_pick_img)

        btn_pick_dir = _make_tb_btn(
            "📂 选目录…",
            "为当前选中行选择主播图片文件夹（同名主播多行可自动共用该目录）",
            self.pick_folder_for_selection,
        )
        tb.addWidget(btn_pick_dir)

        tb.addStretch(1)

        btn_undo = _make_tb_btn("↶ 撤销", "撤销上一步操作（Cmd+Z / Ctrl+Z）", lambda: self.table.undo(), no_focus=True)
        tb.addWidget(btn_undo)

        btn_clear = _make_tb_btn("清空表格", "清空当前表格中的所有内容", self.clear_all_rows)
        tb.addWidget(btn_clear)

        root.addWidget(toolbar_frame)

        # ── Main Spreadsheet Table
        self.table = ManualTaskSpreadsheet(self)
        self.table.content_modified.connect(self._refresh_stats)
        root.addWidget(self.table, 1)

        # ── Footer Status + Actions
        footer = QHBoxLayout()
        footer.setSpacing(10)
        self.stats_label = QLabel("", objectName="muted")
        self.stats_label.setWordWrap(True)
        footer.addWidget(self.stats_label, 1)

        self.draft_btn = QPushButton("暂存草稿")
        self.draft_btn.setToolTip("保存当前填写内容为草稿，下次打开可继续编辑")
        self.draft_btn.clicked.connect(self.save_draft_manual)
        footer.addWidget(self.draft_btn)

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self.reject)
        footer.addWidget(self.cancel_btn)

        self.submit_btn = QPushButton("✓ 保存并导入任务中心", objectName="primaryBtn")
        self.submit_btn.setMinimumHeight(36)
        self.submit_btn.setMinimumWidth(186)
        self.submit_btn.clicked.connect(self.submit_tasks)
        footer.addWidget(self.submit_btn)

        root.addLayout(footer)

        # Load saved draft if any; otherwise start 100% empty with 8 blank rows (zero defaults).
        draft = mti.load_draft(self.work_date)
        if draft:
            self.table.load_rows(draft, min_rows=max(8, len(draft) + 2))
            self._refresh_stats(extra_note=f"已恢复未提交草稿（{len(draft)} 行）")
        else:
            self.table.load_rows([], min_rows=8)
            self._refresh_stats()
        self.table.setCurrentCell(0, COL_RECIPIENT)

    def table_duplicate_row(self):
        self.table.duplicate_current_row()

    def table_delete_rows(self):
        self.table.delete_selected_rows()

    def clear_all_rows(self):
        rows = self.table.export_rows()
        has_any = any(
            any(str(r.get(k) or "").strip() for k in ("recipient", "host", "foreign_text", "chinese_text", "image_path", "material_source"))
            for r in rows
        )
        if not has_any:
            return
        ans = QMessageBox.question(
            self,
            "清空表格",
            "确认清空当前表格中的全部内容吗？（清空后仍可通过 Cmd+Z 撤销）",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return
        self.table._push_undo_if_needed()
        self.table.load_rows([], min_rows=8)
        mti.clear_draft(self.work_date)

    def pick_images_for_selection(self):
        exts = " ".join(f"*{ext}" for ext in sorted(IMAGE_EXTENSIONS))
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择主播参考图片（可单选或多选）",
            str(Path.home()),
            f"图片文件 ({exts});;所有文件 (*)",
        )
        if not files:
            return
        self.table.apply_dropped_paths(files)

    def pick_folder_for_selection(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "选择主播图片素材文件夹",
            str(Path.home()),
        )
        if not folder:
            return
        self.table.apply_dropped_paths([folder])

    def _active_row_stats(self) -> tuple[int, int, int]:
        rows = self.table.export_rows()
        non_empty = 0
        hosts = set()
        recipients = set()
        for r in rows:
            rec = str(r.get("recipient") or "").strip()
            host = str(r.get("host") or "").strip()
            fx = str(r.get("foreign_text") or "").strip()
            zh = str(r.get("chinese_text") or "").strip()
            img = str(r.get("image_path") or "").strip()
            if any((rec, host, fx, zh, img)):
                non_empty += 1
                if rec:
                    recipients.add(rec)
                if rec or host:
                    hosts.add((rec, host))
        return non_empty, len(recipients), len(hosts)

    def _refresh_stats(self, extra_note: str = ""):
        cnt, rec_cnt, host_cnt = self._active_row_stats()
        if cnt == 0:
            base = "当前已填写 0 行 · 可直接在任意单元格输入，或按 Cmd+V / Ctrl+V 批量粘贴多行数据（空行导入时自动忽略）"
        else:
            base = f"当前有效任务 {cnt} 条 · {rec_cnt} 个接收人 · {host_cnt} 个主播（空白行导入时自动忽略）"
        if extra_note:
            base = f"{base}　|　{extra_note}"
        self.stats_label.setText(base)

    def save_draft_manual(self):
        # Commit any active editor first
        if self.table.state() == QAbstractItemView.EditingState and self.focusWidget():
            self.table.setFocus()
        rows = self.table.export_rows()
        mti.save_draft(rows, self.work_date)
        self._refresh_stats(extra_note="✓ 草稿已暂存")

    def submit_tasks(self):
        if self._worker and self._worker.isRunning():
            return
        # Ensure any open inline cell editor commits its latest text before reading rows
        if self.table.state() == QAbstractItemView.EditingState:
            ed = QApplication.focusWidget()
            if ed is not None and ed is not self.table:
                self.table.commitData(ed)
                self.table.closeEditor(ed, QStyledItemDelegate.NoHint)

        rows = self.table.export_rows()
        self.submit_btn.setEnabled(False)
        self.submit_btn.setText("⟳ 正在导入…")
        self.draft_btn.setEnabled(False)

        worker = _ImportWorker(rows, self.work_date, self)
        worker.finished_ok.connect(self._on_import_ok)
        worker.failed_err.connect(self._on_import_err)
        self._worker = worker
        worker.start()

    def _on_import_ok(self, res: dict):
        self.submit_btn.setEnabled(True)
        self.submit_btn.setText("✓ 保存并导入任务中心")
        self.draft_btn.setEnabled(True)
        self.tasks_imported.emit(res)
        self.accept()

    def _on_import_err(self, err_msg: str):
        self.submit_btn.setEnabled(True)
        self.submit_btn.setText("✓ 保存并导入任务中心")
        self.draft_btn.setEnabled(True)
        QMessageBox.warning(self, "无法导入手动任务", err_msg)

    def reject(self):
        if self._worker and self._worker.isRunning():
            return
        rows = self.table.export_rows()
        has_any = any(
            any(str(r.get(k) or "").strip() for k in ("recipient", "host", "foreign_text", "chinese_text", "image_path", "material_source"))
            for r in rows
        )
        if has_any:
            mti.save_draft(rows, self.work_date)
        super().reject()
