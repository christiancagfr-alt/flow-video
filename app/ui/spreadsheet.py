
from __future__ import annotations
import csv
import io

from PySide6.QtWidgets import QTableWidget, QApplication, QTableWidgetItem
from PySide6.QtGui import QKeySequence
from PySide6.QtCore import Qt


class SpreadsheetTable(QTableWidget):
    """
    类 Google Sheets 的表格：
    - Command+V：批量粘贴 TSV
    - 正确保留单元格内部换行
    - Command+C：复制选区
    - Command+Z：撤销最近一次批量操作
    - Delete/Backspace：清空选中的中文/外语单元格
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._undo_stack = []
        self._max_undo = 30

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Paste):
            self.paste_clipboard()
            return
        if event.matches(QKeySequence.Copy):
            self.copy_selection()
            return
        if event.matches(QKeySequence.Undo):
            self.undo_last()
            return
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.push_undo_snapshot()
            self.blockSignals(True)
            try:
                for item in self.selectedItems():
                    if item.column() in (1, 2):
                        item.setText("")
            finally:
                self.blockSignals(False)
            if hasattr(self, "after_bulk_paste"):
                self.after_bulk_paste()
            return
        super().keyPressEvent(event)

    def editable_snapshot(self):
        data = []
        for r in range(self.rowCount()):
            row = []
            for c in (1, 2):
                item = self.item(r, c)
                row.append(item.text() if item else "")
            data.append(tuple(row))
        return data

    def push_undo_snapshot(self):
        snap = self.editable_snapshot()
        if self._undo_stack and self._undo_stack[-1] == snap:
            return
        self._undo_stack.append(snap)
        if len(self._undo_stack) > self._max_undo:
            self._undo_stack.pop(0)

    def undo_last(self):
        if not self._undo_stack:
            return False
        snap = self._undo_stack.pop()
        self.blockSignals(True)
        try:
            for r, values in enumerate(snap):
                if r >= self.rowCount():
                    break
                for offset, c in enumerate((1, 2)):
                    item = self.item(r, c)
                    if item is None:
                        item = QTableWidgetItem()
                        self.setItem(r, c, item)
                    item.setText(values[offset])
        finally:
            self.blockSignals(False)
        if hasattr(self, "after_bulk_paste"):
            self.after_bulk_paste()
        return True

    @staticmethod
    def parse_clipboard_tsv(text: str):
        """
        Google Sheets / Excel 复制多单元格时使用 TSV。
        单元格内部的换行通常会被双引号包住，例如：
            "第一行
            第二行"\t外语内容
        csv.reader 能把内部换行保留在同一个单元格，而不是误拆成新行。
        """
        if not text:
            return []
        stream = io.StringIO(text, newline="")
        reader = csv.reader(
            stream,
            delimiter="\t",
            quotechar='"',
            doublequote=True
        )
        return [row for row in reader]

    def paste_clipboard(self):
        text = QApplication.clipboard().text()
        if not text:
            return

        rows = self.parse_clipboard_tsv(text)
        if not rows:
            return

        start_row = self.currentRow()
        start_col = self.currentColumn()
        if start_row < 0:
            start_row = 0
        if start_col < 0:
            start_col = 1

        # 只允许粘贴到中文对照/外语文案两列。
        # 如果当前选中编号列，则默认从中文对照开始。
        if start_col == 0:
            start_col = 1
        if start_col > 2:
            start_col = 1

        self.push_undo_snapshot()

        self.blockSignals(True)
        try:
            for r_off, rowvals in enumerate(rows):
                rr = start_row + r_off
                if rr >= self.rowCount():
                    break

                for c_off, val in enumerate(rowvals):
                    cc = start_col + c_off
                    if cc > 2:
                        break
                    if cc not in (1, 2):
                        continue

                    item = self.item(rr, cc)
                    if item is None:
                        item = QTableWidgetItem()
                        self.setItem(rr, cc, item)

                    # 保留单元格内部真实换行；
                    # 只统一 Windows CRLF，避免出现多余 \r。
                    val = val.replace("\r\n", "\n").replace("\r", "\n")
                    item.setText(val)
        finally:
            self.blockSignals(False)

        if hasattr(self, "after_bulk_paste"):
            self.after_bulk_paste()

    def copy_selection(self):
        ranges = self.selectedRanges()
        if not ranges:
            return

        rg = ranges[0]
        output = io.StringIO(newline="")
        writer = csv.writer(
            output,
            delimiter="\t",
            quotechar='"',
            quoting=csv.QUOTE_MINIMAL,
            lineterminator="\n"
        )

        for r in range(rg.topRow(), rg.bottomRow() + 1):
            vals = []
            for c in range(rg.leftColumn(), rg.rightColumn() + 1):
                item = self.item(r, c)
                vals.append(item.text() if item else "")
            writer.writerow(vals)

        QApplication.clipboard().setText(output.getvalue().rstrip("\n"))
