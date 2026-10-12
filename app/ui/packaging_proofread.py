from __future__ import annotations
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QPlainTextEdit, QTextBrowser,
    QSplitter, QWidget, QComboBox, QPushButton, QMessageBox, QFileDialog)
from app.services.reels.captions import (batch_script_paste_assignments,
    proofread_srt_keep_timestamps, align_word_srt_to_phrase_srt, html_word_diff, _srt_stamp)
class BatchScriptProofreadDialog(QDialog):
    """Per-video scripts with explicit spreadsheet mapping and timed differences."""
    def __init__(self, parent, rows):
        super().__init__(parent)
        self.setWindowTitle("批量文案校对与替换")
        self.resize(1040, 650)
        self.rows = rows
        self.results = {}
        layout = QVBoxLayout(self)
        tip = QLabel("每行对应一个视频。填写原文案或导入同名 TXT，再点自动对比。\n"
                     "句级时间保持不变；匹配词保留时间，改动词可能需要估时。请核对差异后勾选替换。")
        tip.setWordWrap(True)
        layout.addWidget(tip)
        self.table = QTableWidget(len(rows), 5)
        self.table.setHorizontalHeaderLabels(["替换", "视频", "原文案", "对比结果", "状态"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 50)
        self.table.setColumnWidth(1, 150)
        self.table.setColumnWidth(4, 135)
        for index, row in enumerate(rows):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            check.setCheckState(Qt.CheckState.Unchecked)
            self.table.setItem(index, 0, check)
            label = QTableWidgetItem(Path(row["path"]).name)
            label.setToolTip(row["path"])
            label.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(index, 1, label)
            editor = QPlainTextEdit()
            editor.setPlaceholderText("粘贴此视频对应的原文案")
            editor.textChanged.connect(lambda i=index: self.invalidate(i))
            self.table.setCellWidget(index, 2, editor)
            self.table.setCellWidget(index, 3, QTextBrowser())
            self.table.setItem(index, 4, QTableWidgetItem("等待文案"))
            self.table.setRowHeight(index, 120)
        layout.addWidget(self.table)
        self.detail_title = QLabel("选择视频查看时间戳及差异；此列表只显示已有字幕的视频")
        layout.addWidget(self.detail_title)
        details = QSplitter(Qt.Orientation.Horizontal)
        self.original_detail = QPlainTextEdit(); self.original_detail.setReadOnly(True)
        self.diff_detail = QTextBrowser()
        self.corrected_detail = QPlainTextEdit(); self.corrected_detail.setReadOnly(True)
        for title, widget in (("原字幕（含时间戳）", self.original_detail),
                              ("逐句差异（红字为改动）", self.diff_detail),
                              ("校对后字幕（时间不变）", self.corrected_detail)):
            panel = QWidget(); panel_layout = QVBoxLayout(panel)
            panel_layout.addWidget(QLabel(title)); panel_layout.addWidget(widget)
            details.addWidget(panel)
        details.setMinimumHeight(170)
        layout.addWidget(details)
        self.table.currentCellChanged.connect(lambda row, *_: self.show_details(row))
        paste_row = QHBoxLayout()
        self.paste_mode = QComboBox()
        self.paste_mode.addItem("一列文案：从选中行顺序填入", "order")
        self.paste_mode.addItem("两列：文件名（含扩展名）＋文案", "name")
        paste_button = QPushButton("从谷歌表格 / Excel 批量粘贴")
        paste_button.clicked.connect(self.paste_scripts)
        paste_button.setToolTip("在表格复制多行后点击。支持单元格内换行；只填写文案，不直接替换字幕。")
        paste_row.addWidget(self.paste_mode); paste_row.addWidget(paste_button)
        layout.addLayout(paste_row)
        selection_actions = QHBoxLayout()
        self.select_all_btn = QPushButton("全选可替换项")
        self.select_all_btn.setToolTip("只勾选已完成对比、文案未再次修改的项目；请先核对差异")
        self.select_all_btn.clicked.connect(lambda: self.select_results(True))
        self.clear_selection_btn = QPushButton("取消全选")
        self.clear_selection_btn.clicked.connect(lambda: self.select_results(False))
        self.selection_summary = QLabel()
        selection_actions.addWidget(self.select_all_btn)
        selection_actions.addWidget(self.clear_selection_btn)
        selection_actions.addWidget(self.selection_summary, 1)
        layout.addLayout(selection_actions)
        self.table.itemChanged.connect(lambda *_: self.update_selection_summary())
        self.update_selection_summary()
        actions = QHBoxLayout()
        for name, callback in (("导入同名 TXT", self.import_scripts), ("自动对比全部", self.compare_all),
                               ("批量替换勾选项", self.apply_checked), ("取消", self.reject)):
            button = QPushButton(name)
            button.clicked.connect(callback)
            actions.addWidget(button)
        layout.addLayout(actions)
        if rows:
            self.table.setCurrentCell(0, 1)

    def select_results(self, checked):
        self.table.blockSignals(True)
        try:
            for index in range(len(self.rows)):
                state = Qt.CheckState.Checked if checked and index in self.results else Qt.CheckState.Unchecked
                self.table.item(index, 0).setCheckState(state)
        finally:
            self.table.blockSignals(False)
        self.update_selection_summary()

    def update_selection_summary(self):
        selected = sum(self.table.item(i, 0).checkState() == Qt.CheckState.Checked for i in self.results)
        self.selection_summary.setText(f"已对比 {len(self.results)}/{len(self.rows)} 项 · 已勾选 {selected} 项")
        self.select_all_btn.setEnabled(bool(self.results))

    def show_details(self, row):
        if row < 0 or row >= len(self.rows):
            return
        self.detail_title.setText(f"第 {row + 1} 项：{Path(self.rows[row]['path']).name}")
        self.original_detail.setPlainText(self.rows[row]["srt"])
        result = self.results.get(row)
        self.corrected_detail.setPlainText(result["corrected"] if result else "请填写文案后点击自动对比全部")
        self.diff_detail.setHtml(self.table.cellWidget(row, 3).toHtml() if result else "尚未对比或文案已修改，请重新对比。")

    def paste_scripts(self):
        try:
            assignments = batch_script_paste_assignments(
                QApplication.clipboard().text(), self.rows, self.paste_mode.currentData(),
                max(0, self.table.currentRow()))
        except Exception as exc:
            QMessageBox.warning(self, "无法批量粘贴", str(exc))
            return
        names = "\n".join(f"第 {i + 1} 项：{Path(self.rows[i]['path']).name}" for i, _ in assignments[:8])
        if QMessageBox.question(self, "确认文案对应关系",
                f"将填写 {len(assignments)} 个视频的文案（覆盖这些行已有文案，尚不替换字幕）：\n{names}\n"
                "请确认表格行序/文件名对应正确，填写后点击自动对比全部。") != QMessageBox.StandardButton.Yes:
            return
        for index, script in assignments:
            self.table.cellWidget(index, 2).setPlainText(script)
        self.show_details(self.table.currentRow())

    def invalidate(self, row):
        self.results.pop(row, None)
        self.table.cellWidget(row, 3).clear()
        self.table.item(row, 0).setCheckState(Qt.CheckState.Unchecked)
        if self.table.item(row, 4):
            self.table.item(row, 4).setText("需要重新对比")
        if hasattr(self, "diff_detail") and self.table.currentRow() == row:
            self.show_details(row)

    def import_scripts(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "选择与视频同名的 UTF-8 文案", "", "文案 (*.txt)")
        for path in paths:
            matches = [i for i, row in enumerate(self.rows) if Path(row["path"]).stem.casefold() == Path(path).stem.casefold()]
            if len(matches) != 1:
                continue  # Ambiguous duplicate names must be assigned by the user.
            try:
                self.table.cellWidget(matches[0], 2).setPlainText(Path(path).read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeError) as exc:
                QMessageBox.warning(self, "导入失败", f"{Path(path).name}：{exc}")

    def compare_all(self):
        for index, row in enumerate(self.rows):
            script = self.table.cellWidget(index, 2).toPlainText().strip()
            if not script:
                continue
            corrected, changes = proofread_srt_keep_timestamps(row["srt"], script)
            words = align_word_srt_to_phrase_srt(row["words"], corrected, row["srt"])
            self.results[index] = dict(row, corrected=corrected, corrected_words=words, changes=changes)
            import html
            parts = []
            for change in changes:
                parts.append(f"<p><b>#{change['index']}　{_srt_stamp(change['start'])} → {_srt_stamp(change['end'])}</b><br>"
                             f"原文：{html.escape(change['old'])}<br>校对：{html_word_diff(change['old'], change['new'])}</p>")
            self.table.cellWidget(index, 3).setHtml("".join(parts) or "文字一致，无需修改")
            self.table.item(index, 4).setText(f"{len(changes)} 处改动；需核对估时" if changes else "文字一致")
            self.table.item(index, 0).setCheckState(Qt.CheckState.Unchecked)
        self.show_details(self.table.currentRow())

    def apply_checked(self):
        self.selected_results = [result for i, result in self.results.items()
                                 if self.table.item(i, 0).checkState() == Qt.CheckState.Checked]
        if not self.selected_results:
            QMessageBox.information(self, "未选择", "请先自动对比，核对后勾选要替换的项目。")
            return
        self.accept()
