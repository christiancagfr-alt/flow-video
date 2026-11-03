"""Dialog for a custom DaVinci task / batch rename / batch watermark: drop files/folder + choose mode."""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QPlainTextEdit, QPushButton, QComboBox, QFileDialog, QMessageBox,
    QAbstractItemView, QRadioButton, QButtonGroup, QFrame, QProgressDialog,
)

from app.services import custom_task


class _DropList(QListWidget):
    def __init__(self, on_paths):
        super().__init__()
        self._on_paths = on_paths
        self.setAcceptDrops(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DropOnly)

    def dragEnterEvent(self, event):
        event.acceptProposedAction() if event.mimeData().hasUrls() else event.ignore()

    def dragMoveEvent(self, event):
        event.acceptProposedAction() if event.mimeData().hasUrls() else event.ignore()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self._on_paths(paths)
            event.acceptProposedAction()


class _WatermarkWorker(QThread):
    progress = Signal(int, int, str)
    finished_res = Signal(bool, list, str)

    def __init__(self, file_paths, raw_names, watermark_path, pos_preset, output_dir=None, parent=None):
        super().__init__(parent)
        self.file_paths = file_paths
        self.raw_names = raw_names
        self.watermark_path = watermark_path
        self.pos_preset = pos_preset
        self.output_dir = output_dir
        self._canceled = False

    def cancel(self):
        self._canceled = True

    def run(self):
        try:
            res = custom_task.batch_watermark_files(
                self.file_paths,
                self.raw_names,
                self.watermark_path,
                pos_preset=self.pos_preset,
                output_dir=self.output_dir,
                progress_cb=lambda idx, total, msg: self.progress.emit(idx, total, msg),
                cancel_check=lambda: self._canceled,
            )
            self.finished_res.emit(True, res, '')
        except Exception as exc:
            self.finished_res.emit(False, [], str(exc))


class CustomTaskDialog(QDialog):
    def __init__(self, day, default_mode='SEGMENTS', parent=None):
        if not isinstance(default_mode, str):
            parent = default_mode
            default_mode = 'SEGMENTS'
        super().__init__(parent)
        self.day = day
        self.created_video_id = None
        self._raw_dropped_paths: list[str] = []
        self._default_mode = default_mode
        self._active_wm_worker = None

        self.setWindowTitle('自定义任务 / 批量命名 / 批量加水印')
        self.resize(720, 680)
        lay = QVBoxLayout(self)

        # Top mode selector: SEGMENTS vs COMPLETE vs RENAME_ONLY vs WATERMARK_RENAME
        mode_box = QFrame(objectName='customModeBox')
        mode_lay = QVBoxLayout(mode_box)
        mode_lay.setContentsMargins(8, 6, 8, 6)
        mode_lay.setSpacing(4)
        mode_title = QLabel('功能模式选择：')
        mode_title.setStyleSheet('font-weight: 700; border: none; padding: 0;')
        mode_lay.addWidget(mode_title)
        mode_row = QHBoxLayout()
        self.mode_group = QButtonGroup(self)
        self.rb_segments = QRadioButton('🧩 零散片段（拼接切刀）')
        self.rb_complete = QRadioButton('🎬 完整视频（识别配经文/合成）')
        self.rb_rename_only = QRadioButton('🏷️ 仅批量重命名（仅改名 · 无需文案）')
        self.rb_watermark_rename = QRadioButton('💧 批量添加水印 + 命名（加水印并重命名 · 无需文案）')

        self.mode_group.addButton(self.rb_segments)
        self.mode_group.addButton(self.rb_complete)
        self.mode_group.addButton(self.rb_rename_only)
        self.mode_group.addButton(self.rb_watermark_rename)

        mode_row.addWidget(self.rb_segments)
        mode_row.addWidget(self.rb_complete)
        mode_row.addWidget(self.rb_rename_only)
        mode_row.addWidget(self.rb_watermark_rename)
        mode_row.addStretch(1)
        mode_lay.addLayout(mode_row)
        lay.addWidget(mode_box)

        self.step1_label = QLabel('① 把单个视频文件或文件夹拖到下面（文件夹会递归读取视频，按文件名自然顺序排列）')
        lay.addWidget(self.step1_label)
        self.files = _DropList(self._add_paths)
        self.files.setMinimumHeight(140)
        lay.addWidget(self.files, 1)

        row = QHBoxLayout()
        for text, fn in (
            ('添加文件…', self._pick_files),
            ('添加文件夹…', self._pick_folder),
            ('移除选中', self._remove),
            ('清空', self._clear_files),
        ):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        self.count = QLabel('0 个视频', objectName='muted')
        row.addWidget(self.count)
        lay.addLayout(row)

        self.step2_label = QLabel('② 任务名称 / 批量导出命名（导出时按编号依次使用：可粘贴多行文件名每行1个，或只填1个总名自动编号）')
        lay.addWidget(self.step2_label)
        self.title = QPlainTextEdit()
        self.title.setPlaceholderText('可粘贴多行批量名称（每行对应1个视频，不会因标题里的逗号切碎）；或只填1个总名（如：自媒体男）')
        self.title.setFixedHeight(75)
        lay.addWidget(self.title)

        # Watermark settings frame (visible in WATERMARK_RENAME mode)
        self.wm_box = QFrame(objectName='customWmBox')
        wm_lay = QVBoxLayout(self.wm_box)
        wm_lay.setContentsMargins(8, 6, 8, 6)
        wm_lay.setSpacing(6)
        wm_title = QLabel('③ 水印图片与叠加设置：')
        wm_title.setStyleSheet('font-weight: 700; border: none; padding: 0;')
        wm_lay.addWidget(wm_title)

        wm_file_row = QHBoxLayout()
        wm_file_row.addWidget(QLabel('水印图片：'))
        from app.services import ai_watermark
        default_wm = str(ai_watermark.load_config().get('main_png_path') or '').strip()
        self.wm_path_edit = QLineEdit(default_wm)
        self.wm_path_edit.setPlaceholderText('请选择透明 PNG 水印图片文件…')
        wm_file_row.addWidget(self.wm_path_edit, 1)
        pick_wm_btn = QPushButton('选择水印…')
        pick_wm_btn.clicked.connect(self._pick_watermark)
        wm_file_row.addWidget(pick_wm_btn)
        wm_lay.addLayout(wm_file_row)

        wm_pos_row = QHBoxLayout()
        wm_pos_row.addWidget(QLabel('水印位置：'))
        self.wm_pos_combo = QComboBox()
        self.wm_pos_combo.addItem('全屏自适应贴合（推荐 · 适配全画幅透明图）', 'cover')
        self.wm_pos_combo.addItem('居中 (Center)', 'center')
        self.wm_pos_combo.addItem('右下角 (Bottom Right)', 'bottom_right')
        self.wm_pos_combo.addItem('右上角 (Top Right)', 'top_right')
        self.wm_pos_combo.addItem('左下角 (Bottom Left)', 'bottom_left')
        self.wm_pos_combo.addItem('左上角 (Top Left)', 'top_left')
        self.wm_pos_combo.addItem('底部居中 (Bottom Center)', 'bottom_center')
        wm_pos_row.addWidget(self.wm_pos_combo, 1)

        wm_pos_row.addWidget(QLabel('导出目录：'))
        self.wm_out_combo = QComboBox()
        self.wm_out_combo.addItem('保存在原视频同目录下（直接使用新文件名）', 'same')
        self.wm_out_combo.addItem('另存到独立文件夹…', 'custom')
        self.wm_out_combo.currentIndexChanged.connect(self._on_wm_out_changed)
        wm_pos_row.addWidget(self.wm_out_combo, 1)
        wm_lay.addLayout(wm_pos_row)

        self.wm_custom_out_row = QHBoxLayout()
        self.wm_out_path_edit = QLineEdit()
        self.wm_out_path_edit.setPlaceholderText('请选择另存的独立文件夹路径…')
        self.wm_custom_out_row.addWidget(self.wm_out_path_edit, 1)
        self.pick_out_btn = QPushButton('选择文件夹…')
        self.pick_out_btn.clicked.connect(self._pick_output_folder)
        self.wm_custom_out_row.addWidget(self.pick_out_btn)
        wm_lay.addLayout(self.wm_custom_out_row)
        self.wm_out_path_edit.setVisible(False)
        self.pick_out_btn.setVisible(False)

        lay.addWidget(self.wm_box)

        # Standard language & script controls (visible in SEGMENTS & COMPLETE modes)
        self.step3_label = QLabel('③ 口播语言（默认跟随“系统设置 → 自动剪辑口播语言”；在这里改只对本次任务临时生效）')
        lay.addWidget(self.step3_label)
        from app.ui.settings_page import _WHISPER_LANGUAGES
        from app.core import repository as repo
        self.language = QComboBox()
        self.language.addItems(_WHISPER_LANGUAGES)
        saved = str(repo.get_setting('whisper_language', '') or '')
        index = self.language.findText(saved)
        self.language.setCurrentIndex(index if index >= 0 else max(0, self.language.findText('斯瓦西里语 (Swahili) · sw')))
        self._default_language = self.language.currentText()
        self.language.setEditable(True)
        self.language.setInsertPolicy(QComboBox.NoInsert)
        self.language.setMaxVisibleItems(15)
        completer = self.language.completer()
        completer.setFilterMode(Qt.MatchContains)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.language.lineEdit().setPlaceholderText('输入语言名或代码搜索，例如 英语 / en')
        lay.addWidget(self.language)

        self.step4_label = QLabel('④ 文案（按这份文案识别、对齐；批量多条视频时可直接从表格复制多行文案一次性粘贴）')
        lay.addWidget(self.step4_label)
        self.script = QPlainTextEdit()
        self.script.setPlaceholderText('在这里粘贴/填写口播文案…')
        lay.addWidget(self.script, 2)

        self.note = QLabel(
            '创建后回到页面，可先点“📖 导入经文”识别经文，再依次点“唤醒达芬奇 → 导入剪辑素材 → 开始运行自动剪辑”。',
            objectName='muted',
        )
        self.note.setWordWrap(True)
        lay.addWidget(self.note)

        foot = QHBoxLayout()
        foot.addStretch(1)
        cancel = QPushButton('取消')
        cancel.clicked.connect(self.reject)
        foot.addWidget(cancel)
        self.ok = QPushButton('创建自定义任务', objectName='primaryBtn')
        self.ok.clicked.connect(self._create)
        foot.addWidget(self.ok)
        lay.addLayout(foot)

        # Wire mode toggle listener
        self.mode_group.buttonToggled.connect(self._on_mode_toggled)
        if self._default_mode == 'WATERMARK_RENAME':
            self.rb_watermark_rename.setChecked(True)
        elif self._default_mode == 'RENAME_ONLY':
            self.rb_rename_only.setChecked(True)
        elif self._default_mode == 'COMPLETE':
            self.rb_complete.setChecked(True)
        else:
            self.rb_segments.setChecked(True)
        self._on_mode_toggled()

    def _on_wm_out_changed(self):
        is_custom = self.wm_out_combo.currentData() == 'custom'
        self.wm_out_path_edit.setVisible(is_custom)
        self.pick_out_btn.setVisible(is_custom)

    def _pick_watermark(self):
        f, _ = QFileDialog.getOpenFileName(self, '选择水印图片', str(Path.home()), 'PNG Image (*.png)')
        if f:
            self.wm_path_edit.setText(f)

    def _pick_output_folder(self):
        d = QFileDialog.getExistingDirectory(self, '选择另存文件夹', str(Path.home()))
        if d:
            self.wm_out_path_edit.setText(d)

    def _on_mode_toggled(self, button=None, checked=True):
        if not checked:
            return
        is_wm = self.rb_watermark_rename.isChecked()
        is_rename = self.rb_rename_only.isChecked()

        if is_wm:
            self.step2_label.setText('② 批量命名规则（重命名并叠加水印：可粘贴多行文件名每行1个，或只填1个总名自动编号）：')
            self.title.setPlaceholderText('可粘贴多行新文件名（每行对应1个视频）；或只填1个总名（如：自媒体男 或 01-ZB-小原，将自动递增编号）')
            self.wm_box.setVisible(True)
            self.step3_label.setVisible(False)
            self.language.setVisible(False)
            self.step4_label.setVisible(False)
            self.script.setVisible(False)
            self.note.setText('💡 将使用硬件加速在本地直接为上述视频叠加水印并按新规则重命名导出，不导入达芬奇，无需填写口播文案。')
            self.ok.setText('💧 开始批量添加水印并重命名')
        elif is_rename:
            self.step2_label.setText('② 批量重命名规则（直接修改本地文件：可粘贴多行文件名每行1个，或只填1个总名自动编号）：')
            self.title.setPlaceholderText('可粘贴多行新文件名（每行对应1个视频）；或只填1个总名（如：自媒体男 或 01-ZB-小原，将自动递增编号）')
            self.wm_box.setVisible(False)
            self.step3_label.setVisible(False)
            self.language.setVisible(False)
            self.step4_label.setVisible(False)
            self.script.setVisible(False)
            self.note.setText('💡 仅对上方列表里的本地视频文件直接执行批量重命名，不导入达芬奇，无需填写口播文案。')
            self.ok.setText('🏷️ 开始批量重命名')
        else:
            self.step2_label.setText('② 任务名称 / 批量导出命名（导出时按编号依次使用：可粘贴多行文件名每行1个，或只填1个总名自动编号）')
            self.title.setPlaceholderText('可粘贴多行批量名称（每行对应1个视频，不会因标题里的逗号切碎）；或只填1个总名（如：自媒体男）')
            self.wm_box.setVisible(False)
            self.step3_label.setVisible(True)
            self.language.setVisible(True)
            self.step4_label.setVisible(True)
            self.script.setVisible(True)
            self.note.setText('创建后回到页面，可先点“📖 导入经文”识别经文，再依次点“唤醒达芬奇 → 导入剪辑素材 → 开始运行自动剪辑”。')
            self.ok.setText('创建自定义任务')

    def _paths(self):
        return [self.files.item(i).data(Qt.UserRole) for i in range(self.files.count())]

    def _clear_files(self):
        self.files.clear()
        self._raw_dropped_paths.clear()
        self.count.setText('0 个视频')

    def _add_paths(self, paths):
        for p in paths:
            if p not in self._raw_dropped_paths:
                self._raw_dropped_paths.append(p)
        have = set(self._paths())
        for f in custom_task.collect_files(paths):
            if f not in have:
                self.files.addItem(f'{Path(f).name}    —    {Path(f).parent}')
                self.files.item(self.files.count() - 1).setData(Qt.UserRole, f)
                have.add(f)
        self.count.setText(f'{self.files.count()} 个视频')

    def _pick_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, '选择视频', str(Path.home()), 'Video (*.mp4 *.mov *.m4v *.webm)')
        self._add_paths(files)

    def _pick_folder(self):
        folder = QFileDialog.getExistingDirectory(self, '选择视频文件夹', str(Path.home()))
        if folder:
            self._add_paths([folder])

    def _remove(self):
        for item in self.files.selectedItems():
            self.files.takeItem(self.files.row(item))
        self._raw_dropped_paths = self._paths()
        self.count.setText(f'{self.files.count()} 个视频')

    def _do_batch_rename(self):
        paths = self._paths()
        if not paths:
            QMessageBox.warning(self, '批量重命名', '请先拖入或添加需要重命名的视频文件！')
            return
        raw_names = self.title.toPlainText().strip()
        if not raw_names:
            QMessageBox.warning(self, '批量重命名', '请在第②步输入批量重命名规则或新文件名列表！')
            return

        try:
            names = custom_task.parse_batch_names(raw_names, len(paths))
        except Exception as exc:
            QMessageBox.warning(self, '批量重命名', f'解析命名规则失败：{exc}')
            return

        from app.core.naming import INVALID
        preview_lines = []
        for idx, (p_str, nm) in enumerate(zip(paths[:6], names[:6])):
            p = Path(p_str)
            clean_name = re.sub(INVALID, '', (nm or '').strip()).strip()
            if not clean_name:
                clean_name = f"video_{idx + 1:02d}"
            if not clean_name.lower().endswith(p.suffix.lower()):
                clean_name = f"{clean_name}{p.suffix}"
            preview_lines.append(f"{idx + 1}. {p.name}  ➔  {clean_name}")
        if len(paths) > 6:
            preview_lines.append(f"... 剩余 {len(paths) - 6} 个文件同样按规则依次重命名")
        preview_text = "\n".join(preview_lines)

        reply = QMessageBox.question(
            self,
            '确认批量重命名',
            f'即将对选中的 {len(paths)} 个视频文件进行重命名：\n\n{preview_text}\n\n确认直接在本地重命名吗？（不可撤销）',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            renamed = custom_task.batch_rename_files(paths, raw_names)
        except Exception as exc:
            from app.ui.resolve_error_dialog import show_editing_warning
            show_editing_warning(self, '批量重命名失败', str(exc))
            return

        self.files.clear()
        self._raw_dropped_paths.clear()
        for item in renamed:
            new_p = item['new_path']
            self._raw_dropped_paths.append(new_p)
            self.files.addItem(f"{Path(new_p).name}    —    {Path(new_p).parent}")
            self.files.item(self.files.count() - 1).setData(Qt.UserRole, new_p)
        self.count.setText(f"{self.files.count()} 个视频")

        QMessageBox.information(self, '批量重命名完成', f'已成功重命名 {len(renamed)} 个视频文件！')
        self.accept()

    def _do_batch_watermark(self):
        paths = self._paths()
        if not paths:
            QMessageBox.warning(self, '批量添加水印', '请先拖入或添加需要处理的视频文件！')
            return
        raw_names = self.title.toPlainText().strip()
        if not raw_names:
            QMessageBox.warning(self, '批量添加水印', '请在第②步输入批量命名规则或新文件名列表！')
            return
        wm_path = self.wm_path_edit.text().strip()
        if not wm_path or not Path(wm_path).is_file():
            QMessageBox.warning(self, '批量添加水印', '请先在第③步选择有效的水印 PNG 图片文件！')
            return

        out_dir = None
        if self.wm_out_combo.currentData() == 'custom':
            out_dir = self.wm_out_path_edit.text().strip()
            if not out_dir:
                QMessageBox.warning(self, '批量添加水印', '请选择另存的独立文件夹路径！')
                return

        try:
            names = custom_task.parse_batch_names(raw_names, len(paths))
        except Exception as exc:
            QMessageBox.warning(self, '批量添加水印', f'解析命名规则失败：{exc}')
            return

        from app.core.naming import INVALID
        preview_lines = []
        for idx, (p_str, nm) in enumerate(zip(paths[:6], names[:6])):
            p = Path(p_str)
            clean_name = re.sub(INVALID, '', (nm or '').strip()).strip()
            if not clean_name:
                clean_name = f"video_{idx + 1:02d}"
            if not clean_name.lower().endswith(p.suffix.lower()):
                clean_name = f"{clean_name}{p.suffix}"
            preview_lines.append(f"{idx + 1}. {p.name}  ➔  {clean_name}")
        if len(paths) > 6:
            preview_lines.append(f"... 剩余 {len(paths) - 6} 个文件同样按规则处理")
        preview_text = "\n".join(preview_lines)

        reply = QMessageBox.question(
            self,
            '确认批量添加水印与重命名',
            f'即将为 {len(paths)} 个视频叠加水印并重命名导出：\n\n水印图片：{Path(wm_path).name}\n叠加位置：{self.wm_pos_combo.currentText()}\n\n{preview_text}\n\n确认开始批量导出吗？',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return

        progress = QProgressDialog('正在准备批量添加水印与重命名…', '取消', 0, len(paths), self)
        progress.setWindowTitle('正在批量添加水印')
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        pos_preset = self.wm_pos_combo.currentData() or 'cover'
        worker = _WatermarkWorker(paths, raw_names, wm_path, pos_preset, output_dir=out_dir, parent=self)
        self._active_wm_worker = worker

        def on_prog(cur, total, msg):
            progress.setValue(cur)
            progress.setLabelText(msg)

        def on_done(ok, results, err):
            progress.close()
            if not ok:
                from app.ui.resolve_error_dialog import show_editing_warning
                show_editing_warning(self, '批量添加水印失败', f'处理过程中出错：{err}')
                return
            if len(results) < len(paths):
                QMessageBox.information(self, '批量添加水印已停止', f'已完成 {len(results)}/{len(paths)} 个视频的处理。')
            else:
                QMessageBox.information(self, '批量添加水印完成', f'已成功为 {len(results)} 个视频添加水印并重命名导出！')
            self.accept()

        worker.progress.connect(on_prog)
        worker.finished_res.connect(on_done)
        progress.canceled.connect(worker.cancel)
        worker.start()

    def _create(self):
        if self.rb_watermark_rename.isChecked():
            self._do_batch_watermark()
            return
        if self.rb_rename_only.isChecked():
            self._do_batch_rename()
            return
        if self.language.findText(self.language.currentText()) < 0:
            QMessageBox.warning(self, '自定义任务', '请从列表中选择有效的口播语言（可输入关键字搜索，如“英语”或 en）。')
            return
        lang_code = (
            None
            if self.language.currentText() == self._default_language
            else self.language.currentText().split(' · ')[-1].strip()
        )
        mode = 'COMPLETE' if self.rb_complete.isChecked() else 'SEGMENTS'
        input_paths = self._raw_dropped_paths if (mode == 'SEGMENTS' and self._raw_dropped_paths) else self._paths()
        try:
            self.created_video_id = custom_task.create(
                self.day,
                self.title.toPlainText(),
                input_paths,
                self.script.toPlainText(),
                lang_code,
                task_mode=mode,
            )
        except Exception as exc:
            from app.ui.resolve_error_dialog import show_editing_warning
            show_editing_warning(self, '自定义任务', str(exc))
            return
        self.accept()
