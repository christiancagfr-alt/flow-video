from __future__ import annotations

"""Flow Studio Video Packaging workspace · V0.13.5.96.

This page is intentionally isolated from the production scheduler, Flow browser
extension, QC/Rework, Resolve automation and database.  It edits local packaging
projects and invokes a user-managed local Remotion installation directly.
"""

import copy
import html
import json
import re
from pathlib import Path

from PySide6.QtCore import Qt, QProcess, QSettings, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QFrame, QPushButton,
    QLineEdit, QComboBox, QPlainTextEdit, QTabWidget, QSplitter, QListWidget,
    QListWidgetItem, QSizePolicy, QSlider, QSpinBox, QDoubleSpinBox, QCheckBox,
    QFileDialog, QMessageBox, QTreeWidget, QTreeWidgetItem, QAbstractItemView,
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar, QStackedLayout,
    QColorDialog, QFontComboBox, QDialog, QDialogButtonBox, QFormLayout, QInputDialog,
)

try:
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
    from PySide6.QtMultimediaWidgets import QVideoWidget
    MULTIMEDIA_OK = True
except Exception:
    QMediaPlayer = QAudioOutput = QVideoWidget = None
    MULTIMEDIA_OK = False

from app.services.remotion_renderer import RemotionRenderer
from app.services.caption_preset_library import CaptionPresetLibrary


VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}



def _fmt_ms(value: int) -> str:
    sec = max(0, int(value or 0) // 1000)
    return f"{sec // 60:02d}:{sec % 60:02d}"


def _as_float(text, default=0.0):
    try:
        return float(text)
    except Exception:
        return float(default)


class PackagingPage(QWidget):
    """Production-style packaging editor backed by local Remotion."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pageRoot")
        self._settings = QSettings("FlowStudio", "FlowStudio")
        self._project_path = ""
        self._project = {"version": 1, "videos": {}, "order": []}
        self._current_path = ""
        self._loading_state = False
        self._render_process = None
        self._render_queue: list[str] = []
        self._rendering_path = ""
        self._render_total = 0
        self._render_done = 0
        self._tree_items = {}
        self._engine_ok = False
        self._caption_presets = CaptionPresetLibrary()
        self._build_ui()
        self._set_color_button(self.caption_color_btn, "#FFFFFF")
        self._set_color_button(self.caption_stroke_color_btn, "#111111")
        self._set_color_button(self.caption_bg_color_btn, "#000000")
        self._set_color_button(self.caption_karaoke_active_btn, "#FFD54A")
        self._set_color_button(self.caption_karaoke_read_btn, "#FFFFFF")
        self._set_color_button(self.caption_karaoke_unread_btn, "#C9C9C9")
        self._refresh_caption_preset_choices(prefer_name="经典白字黑描边")
        self._apply_caption_effect_preset()
        self._install_shortcuts()
        self._update_engine_badge()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 14, 18, 16)
        outer.setSpacing(10)

        # Header / global tools
        top = QHBoxLayout()
        title_box = QVBoxLayout(); title_box.setSpacing(1)
        title = QLabel("视频包装工作台", objectName="pageTitle")
        sub = QLabel("字幕 · 水印 · B-roll · 标题 · 片头片尾 · Remotion 本地批量渲染", objectName="pageSubtitle")
        title_box.addWidget(title); title_box.addWidget(sub)
        top.addLayout(title_box, 1)

        self.engine_badge = QLabel("● Remotion 未检测", objectName="statusInfo")
        self.engine_badge.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top.addWidget(self.engine_badge)
        self.detect_top_btn = QPushButton("检测引擎")
        self.detect_top_btn.clicked.connect(self._check_remotion)
        top.addWidget(self.detect_top_btn)
        outer.addLayout(top)

        tool = QFrame(objectName="pageCard")
        th = QHBoxLayout(tool); th.setContentsMargins(10, 8, 10, 8); th.setSpacing(7)
        self.import_video_btn = QPushButton("＋ 导入视频")
        self.import_video_btn.clicked.connect(self._import_videos)
        th.addWidget(self.import_video_btn)
        self.import_folder_btn = QPushButton("导入文件夹")
        self.import_folder_btn.clicked.connect(self._import_folder)
        th.addWidget(self.import_folder_btn)
        th.addWidget(self._vline())
        save_btn = QPushButton("保存工程")
        save_btn.clicked.connect(self._save_project)
        th.addWidget(save_btn)
        load_btn = QPushButton("载入工程")
        load_btn.clicked.connect(self._load_project)
        th.addWidget(load_btn)
        th.addWidget(self._vline())
        self.preset_combo = QComboBox(); self.preset_combo.setMinimumWidth(150)
        self._reload_preset_combo()
        th.addWidget(self.preset_combo)
        apply_preset = QPushButton("套用模板")
        apply_preset.clicked.connect(self._apply_named_preset)
        th.addWidget(apply_preset)
        save_preset = QPushButton("保存当前为模板")
        save_preset.clicked.connect(self._save_named_preset)
        th.addWidget(save_preset)
        apply_all = QPushButton("应用到全部视频")
        apply_all.clicked.connect(self._apply_to_all)
        th.addWidget(apply_all)
        th.addStretch(1)
        self.render_btn = QPushButton("▶ 渲染当前")
        self.render_btn.clicked.connect(self._render_current)
        th.addWidget(self.render_btn)
        self.batch_btn = QPushButton("批量渲染全部")
        self.batch_btn.clicked.connect(self._render_all)
        th.addWidget(self.batch_btn)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.clicked.connect(self._stop_render)
        self.stop_btn.setEnabled(False)
        th.addWidget(self.stop_btn)
        outer.addWidget(tool)

        # Editor region: materials / preview / controls
        self.editor_split = QSplitter(Qt.Horizontal, objectName="packagingEditorSplitter")
        self.editor_split.setChildrenCollapsible(False)
        self.editor_split.setHandleWidth(7)
        self.editor_split.addWidget(self._build_material_panel())
        self.editor_split.addWidget(self._build_preview_panel())
        self.editor_split.addWidget(self._build_properties_panel())
        self.editor_split.setSizes([310, 620, 430])

        # Full page vertical split with a real timeline summary.
        self.vertical_split = QSplitter(Qt.Vertical, objectName="packagingVerticalSplitter")
        self.vertical_split.setChildrenCollapsible(False)
        self.vertical_split.setHandleWidth(7)
        self.vertical_split.addWidget(self.editor_split)
        self.vertical_split.addWidget(self._build_timeline_panel())
        self.vertical_split.setSizes([630, 250])
        outer.addWidget(self.vertical_split, 1)

        # Render status bar
        status = QFrame(objectName="pageCard")
        sh = QHBoxLayout(status); sh.setContentsMargins(12, 7, 12, 7)
        self.current_info = QLabel("当前片段：未选择", objectName="muted")
        sh.addWidget(self.current_info, 1)
        self.render_progress = QProgressBar(); self.render_progress.setRange(0, 100); self.render_progress.setValue(0)
        self.render_progress.setMaximumWidth(260); self.render_progress.hide()
        sh.addWidget(self.render_progress)
        self.render_status = QLabel("就绪", objectName="muted")
        sh.addWidget(self.render_status)
        outer.addWidget(status)

    @staticmethod
    def _vline():
        line = QFrame(); line.setFrameShape(QFrame.VLine); line.setFrameShadow(QFrame.Sunken); line.setMaximumWidth(1)
        return line

    def _build_material_panel(self):
        card = QFrame(objectName="pageCard")
        card.setMinimumWidth(250)
        box = QVBoxLayout(card); box.setContentsMargins(12, 12, 12, 12); box.setSpacing(8)
        head = QHBoxLayout(); head.addWidget(QLabel("素材与片段", objectName="sectionTitle")); head.addStretch(1)
        self.material_count = QLabel("0 个视频", objectName="muted"); head.addWidget(self.material_count)
        box.addLayout(head)
        self.search = QLineEdit(); self.search.setPlaceholderText("搜索接收人 / 主播 / 文件名…")
        self.search.textChanged.connect(self._filter_tree)
        box.addWidget(self.search)
        self.task_tree = QTreeWidget()
        self.task_tree.setObjectName("packagingTaskList")
        self.task_tree.setHeaderHidden(True)
        self.task_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.task_tree.itemSelectionChanged.connect(self._tree_selected)
        box.addWidget(self.task_tree, 1)
        hint = QLabel("可直接导入自动剪辑后的母版视频。本页不修改质检、返工、Resolve 或 Flow 任务状态。", objectName="muted")
        hint.setWordWrap(True); box.addWidget(hint)
        return card

    def _build_preview_panel(self):
        card = QFrame(objectName="pageCard")
        card.setMinimumWidth(350)
        box = QVBoxLayout(card); box.setContentsMargins(10, 10, 10, 10); box.setSpacing(7)
        head = QHBoxLayout(); head.addWidget(QLabel("实时预览", objectName="sectionTitle")); head.addStretch(1)
        self.preview_mode = QLabel("UI Overlay Preview", objectName="muted"); head.addWidget(self.preview_mode)
        box.addLayout(head)

        self.preview_host = QFrame(objectName="compactCard")
        self.preview_host.setMinimumHeight(420)
        stack = QStackedLayout(self.preview_host); stack.setStackingMode(QStackedLayout.StackAll); stack.setContentsMargins(0, 0, 0, 0)

        if MULTIMEDIA_OK:
            self.video_widget = QVideoWidget()
            self.video_widget.setStyleSheet("background:#000;border:none;")
            self.audio = QAudioOutput(self); self.audio.setVolume(0.8)
            self.player = QMediaPlayer(self); self.player.setAudioOutput(self.audio); self.player.setVideoOutput(self.video_widget)
            self.player.positionChanged.connect(self._player_position)
            self.player.durationChanged.connect(self._player_duration)
            stack.addWidget(self.video_widget)
        else:
            self.video_widget = None; self.audio = None; self.player = None
            no_video = QLabel("当前环境不可用 QMediaPlayer\n仍可编辑并使用 Remotion 渲染")
            no_video.setAlignment(Qt.AlignCenter); no_video.setStyleSheet("background:#111;color:white;")
            stack.addWidget(no_video)

        # Lightweight overlay preview of the packaging state.
        self.overlay = QWidget(); self.overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        og = QGridLayout(self.overlay); og.setContentsMargins(18, 18, 18, 22); self.overlay_grid = og
        self.preview_title = QLabel(""); self.preview_title.setAlignment(Qt.AlignCenter); self.preview_title.setWordWrap(True)
        self.preview_title.setStyleSheet("color:white;font-size:20px;font-weight:800;background:rgba(0,0,0,110);padding:6px;border-radius:6px;")
        og.addWidget(self.preview_title, 0, 0, 1, 3, Qt.AlignTop | Qt.AlignHCenter)
        self.preview_watermark = QLabel(""); self.preview_watermark.setAlignment(Qt.AlignCenter); self.preview_watermark.setFixedSize(100, 70)
        og.addWidget(self.preview_watermark, 0, 2, Qt.AlignTop | Qt.AlignRight)
        og.setRowStretch(1, 1)
        self.preview_caption = QLabel(""); self.preview_caption.setAlignment(Qt.AlignCenter); self.preview_caption.setWordWrap(True)
        self.preview_caption.setStyleSheet("color:white;font-size:18px;font-weight:800;background:rgba(0,0,0,145);padding:7px;border-radius:7px;")
        og.addWidget(self.preview_caption, 2, 0, 1, 3, Qt.AlignBottom | Qt.AlignHCenter)
        stack.addWidget(self.overlay)
        box.addWidget(self.preview_host, 1)

        self.seek = QSlider(Qt.Horizontal); self.seek.setRange(0, 0); self.seek.sliderMoved.connect(self._seek_to)
        box.addWidget(self.seek)
        controls = QHBoxLayout()
        self.play_btn = QPushButton("▶") ; self.play_btn.setFixedWidth(44); self.play_btn.clicked.connect(self._toggle_play)
        controls.addWidget(self.play_btn)
        self.volume = QSlider(Qt.Horizontal); self.volume.setRange(0, 100); self.volume.setValue(80); self.volume.setMaximumWidth(100)
        self.volume.valueChanged.connect(lambda v: self.audio.setVolume(v / 100.0) if self.audio else None)
        controls.addWidget(QLabel("🔊")); controls.addWidget(self.volume)
        self.time_label = QLabel("00:00 / 00:00", objectName="muted"); controls.addWidget(self.time_label)
        controls.addStretch(1)
        self.ratio_badge = QLabel("9:16", objectName="statusInfo"); controls.addWidget(self.ratio_badge)
        open_btn = QPushButton("打开原视频"); open_btn.clicked.connect(self._open_current_video); controls.addWidget(open_btn)
        full_btn = QPushButton("⛶"); full_btn.setFixedWidth(42); full_btn.clicked.connect(self._toggle_fullscreen); controls.addWidget(full_btn)
        box.addLayout(controls)
        return card

    def _build_properties_panel(self):
        card = QFrame(objectName="pageCard"); card.setMinimumWidth(360)
        box = QVBoxLayout(card); box.setContentsMargins(10, 10, 10, 10); box.setSpacing(5)
        head = QHBoxLayout(); head.addWidget(QLabel("包装设置", objectName="sectionTitle")); head.addStretch(1)
        self.modified_badge = QLabel("未修改", objectName="muted"); head.addWidget(self.modified_badge)
        box.addLayout(head)
        self.tabs = QTabWidget(objectName="packagingTabs"); self.tabs.setDocumentMode(True)
        self.tabs.addTab(self._watermark_tab(), "水印")
        self.tabs.addTab(self._caption_tab(), "字幕")
        self.tabs.addTab(self._broll_tab(), "B-roll")
        self.tabs.addTab(self._title_tab(), "标题/文字")
        self.tabs.addTab(self._intro_outro_tab(), "片头片尾")
        self.tabs.addTab(self._params_tab(), "参数")
        box.addWidget(self.tabs, 1)
        return card

    def _tab(self):
        w = QWidget(); b = QVBoxLayout(w); b.setContentsMargins(8, 10, 8, 10); b.setSpacing(8); return w, b

    def _watermark_tab(self):
        w, b = self._tab()
        self.wm_enabled = QCheckBox("启用水印"); self.wm_enabled.stateChanged.connect(self._state_changed); b.addWidget(self.wm_enabled)
        b.addWidget(QLabel("图片水印", objectName="cardTitle"))
        r = QHBoxLayout(); self.wm_path = QLineEdit(); self.wm_path.setPlaceholderText("PNG / JPG / WEBP")
        self.wm_path.textChanged.connect(self._state_changed); r.addWidget(self.wm_path, 1)
        choose = QPushButton("选择…"); choose.clicked.connect(self._choose_watermark); r.addWidget(choose); b.addLayout(r)
        presets = QHBoxLayout(); self.wm_preset = QComboBox(); self.wm_preset.addItems(["右上 Logo", "左上 Logo", "右下 Logo", "底部居中半透明"])
        self.wm_preset.currentIndexChanged.connect(self._apply_wm_preset); presets.addWidget(self.wm_preset, 1)
        clear = QPushButton("清除"); clear.clicked.connect(lambda: self.wm_path.setText("")); presets.addWidget(clear); b.addLayout(presets)
        grid = QGridLayout()
        grid.addWidget(QLabel("位置", objectName="muted"), 0, 0); self.wm_position = QComboBox(); self.wm_position.addItems(["左上", "顶部居中", "右上", "左中", "居中", "右中", "左下", "底部居中", "右下"]); self.wm_position.currentIndexChanged.connect(self._state_changed); grid.addWidget(self.wm_position, 0, 1)
        grid.addWidget(QLabel("大小", objectName="muted"), 1, 0); self.wm_scale = QSlider(Qt.Horizontal); self.wm_scale.setRange(4, 45); self.wm_scale.setValue(18); self.wm_scale.valueChanged.connect(self._state_changed); grid.addWidget(self.wm_scale, 1, 1)
        self.wm_scale_value = QLabel("18%", objectName="muted"); grid.addWidget(self.wm_scale_value, 1, 2)
        grid.addWidget(QLabel("透明度", objectName="muted"), 2, 0); self.wm_opacity = QSlider(Qt.Horizontal); self.wm_opacity.setRange(10, 100); self.wm_opacity.setValue(92); self.wm_opacity.valueChanged.connect(self._state_changed); grid.addWidget(self.wm_opacity, 2, 1)
        self.wm_opacity_value = QLabel("92%", objectName="muted"); grid.addWidget(self.wm_opacity_value, 2, 2)
        b.addLayout(grid)
        b.addStretch(1)
        return w

    def _caption_tab(self):
        w, b = self._tab()
        head = QHBoxLayout(); head.addWidget(QLabel("字幕内容", objectName="cardTitle")); head.addStretch(1)
        import_btn = QPushButton("导入分段文案/SRT"); import_btn.clicked.connect(self._import_captions); head.addWidget(import_btn)
        b.addLayout(head)
        self.caption_table = QTableWidget(0, 3); self.caption_table.setHorizontalHeaderLabels(["开始", "结束", "字幕原文"])
        self.caption_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents); self.caption_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents); self.caption_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.caption_table.verticalHeader().setVisible(False); self.caption_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.caption_table.itemChanged.connect(self._state_changed); b.addWidget(self.caption_table, 1)
        row = QHBoxLayout(); add = QPushButton("＋ 添加一段"); add.clicked.connect(self._add_caption_row); row.addWidget(add)
        auto = QPushButton("按视频时长自动分配"); auto.clicked.connect(self._auto_caption_timing); row.addWidget(auto)
        delete = QPushButton("删除选中"); delete.clicked.connect(self._delete_caption_rows); row.addWidget(delete); b.addLayout(row)

        # Data-driven caption preset library. Built-ins live in JSON files and
        # user presets are stored outside the app bundle so upgrades keep them.
        b.addWidget(QLabel("字幕效果模板库", objectName="cardTitle"))
        filter_row = QHBoxLayout()
        self.caption_preset_category = QComboBox(); self.caption_preset_category.addItem("全部")
        self.caption_preset_category.addItems(self._caption_presets.categories())
        self.caption_preset_category.currentTextChanged.connect(self._refresh_caption_preset_choices)
        filter_row.addWidget(self.caption_preset_category)
        self.caption_preset_search = QLineEdit(); self.caption_preset_search.setPlaceholderText("搜索字幕预设 / 标签…")
        self.caption_preset_search.textChanged.connect(self._refresh_caption_preset_choices); filter_row.addWidget(self.caption_preset_search, 1)
        refresh_presets = QPushButton("刷新"); refresh_presets.clicked.connect(self._reload_caption_presets); filter_row.addWidget(refresh_presets)
        b.addLayout(filter_row)

        preset_row = QHBoxLayout()
        self.caption_effect_preset = QComboBox(); self.caption_effect_preset.setMinimumWidth(210)
        self.caption_effect_preset.currentIndexChanged.connect(self._caption_preset_changed); preset_row.addWidget(self.caption_effect_preset, 1)
        apply_effect = QPushButton("应用"); apply_effect.clicked.connect(self._apply_caption_effect_preset); preset_row.addWidget(apply_effect)
        save_effect = QPushButton("保存当前为新预设"); save_effect.clicked.connect(self._save_current_caption_preset); preset_row.addWidget(save_effect)
        update_effect = QPushButton("更新自定义"); update_effect.clicked.connect(self._update_current_caption_preset); preset_row.addWidget(update_effect)
        manage_effect = QPushButton("管理…"); manage_effect.clicked.connect(self._manage_caption_presets); preset_row.addWidget(manage_effect)
        b.addLayout(preset_row)
        self.caption_preset_note = QLabel("", objectName="muted")
        self.caption_preset_note.setWordWrap(True); b.addWidget(self.caption_preset_note)

        b.addWidget(QLabel("字幕样式参数", objectName="cardTitle"))
        style = QGridLayout(); style.setHorizontalSpacing(8); style.setVerticalSpacing(7)
        style.addWidget(QLabel("字体", objectName="muted"), 0, 0); self.caption_font = QFontComboBox(); self.caption_font.currentFontChanged.connect(self._state_changed); style.addWidget(self.caption_font, 0, 1, 1, 3)
        style.addWidget(QLabel("字号", objectName="muted"), 1, 0); self.caption_size = QSpinBox(); self.caption_size.setRange(18, 110); self.caption_size.setValue(52); self.caption_size.valueChanged.connect(self._state_changed); style.addWidget(self.caption_size, 1, 1)
        style.addWidget(QLabel("粗细", objectName="muted"), 1, 2); self.caption_weight = QComboBox(); self.caption_weight.addItems(["500", "600", "700", "800", "900"]); self.caption_weight.setCurrentText("800"); self.caption_weight.currentIndexChanged.connect(self._state_changed); style.addWidget(self.caption_weight, 1, 3)
        style.addWidget(QLabel("文字颜色", objectName="muted"), 2, 0); self.caption_color_btn = QPushButton("#FFFFFF"); self.caption_color_btn.clicked.connect(lambda: self._choose_caption_color(self.caption_color_btn, "文字颜色")); style.addWidget(self.caption_color_btn, 2, 1)
        style.addWidget(QLabel("位置", objectName="muted"), 2, 2); self.caption_position = QComboBox(); self.caption_position.addItems(["顶部居中", "居中", "底部居中"]); self.caption_position.setCurrentText("底部居中"); self.caption_position.currentIndexChanged.connect(self._state_changed); style.addWidget(self.caption_position, 2, 3)

        style.addWidget(QLabel("描边宽度", objectName="muted"), 3, 0); self.caption_stroke_width = QSpinBox(); self.caption_stroke_width.setRange(0, 12); self.caption_stroke_width.setValue(4); self.caption_stroke_width.valueChanged.connect(self._state_changed); style.addWidget(self.caption_stroke_width, 3, 1)
        style.addWidget(QLabel("描边颜色", objectName="muted"), 3, 2); self.caption_stroke_color_btn = QPushButton("#000000"); self.caption_stroke_color_btn.clicked.connect(lambda: self._choose_caption_color(self.caption_stroke_color_btn, "描边颜色")); style.addWidget(self.caption_stroke_color_btn, 3, 3)

        self.caption_bg = QCheckBox("背景框"); self.caption_bg.setChecked(False); self.caption_bg.stateChanged.connect(self._state_changed); style.addWidget(self.caption_bg, 4, 0)
        self.caption_bg_color_btn = QPushButton("#000000"); self.caption_bg_color_btn.clicked.connect(lambda: self._choose_caption_color(self.caption_bg_color_btn, "背景颜色")); style.addWidget(self.caption_bg_color_btn, 4, 1)
        style.addWidget(QLabel("背景透明度", objectName="muted"), 4, 2); self.caption_bg_opacity = QSpinBox(); self.caption_bg_opacity.setRange(0, 100); self.caption_bg_opacity.setSuffix("%"); self.caption_bg_opacity.setValue(55); self.caption_bg_opacity.valueChanged.connect(self._state_changed); style.addWidget(self.caption_bg_opacity, 4, 3)

        self.caption_shadow = QCheckBox("阴影"); self.caption_shadow.setChecked(True); self.caption_shadow.stateChanged.connect(self._state_changed); style.addWidget(self.caption_shadow, 5, 0)
        style.addWidget(QLabel("阴影柔化", objectName="muted"), 5, 1); self.caption_shadow_blur = QSpinBox(); self.caption_shadow_blur.setRange(0, 30); self.caption_shadow_blur.setValue(10); self.caption_shadow_blur.valueChanged.connect(self._state_changed); style.addWidget(self.caption_shadow_blur, 5, 2)
        style.addWidget(QLabel("阴影下移", objectName="muted"), 5, 3); self.caption_shadow_y = QSpinBox(); self.caption_shadow_y.setRange(0, 20); self.caption_shadow_y.setValue(4); self.caption_shadow_y.valueChanged.connect(self._state_changed); style.addWidget(self.caption_shadow_y, 5, 4)

        style.addWidget(QLabel("入场效果", objectName="muted"), 6, 0); self.caption_animation = QComboBox(); self.caption_animation.addItems(["无", "淡入", "弹入", "上滑", "轻微放大"]); self.caption_animation.setCurrentText("淡入"); self.caption_animation.currentIndexChanged.connect(self._state_changed); style.addWidget(self.caption_animation, 6, 1)
        style.addWidget(QLabel("最大宽度", objectName="muted"), 6, 2); self.caption_max_width = QSpinBox(); self.caption_max_width.setRange(50, 96); self.caption_max_width.setSuffix("%"); self.caption_max_width.setValue(88); self.caption_max_width.valueChanged.connect(self._state_changed); style.addWidget(self.caption_max_width, 6, 3)

        style.addWidget(QLabel("行距", objectName="muted"), 7, 0); self.caption_line_height = QDoubleSpinBox(); self.caption_line_height.setRange(0.9, 1.8); self.caption_line_height.setSingleStep(0.05); self.caption_line_height.setDecimals(2); self.caption_line_height.setValue(1.22); self.caption_line_height.valueChanged.connect(self._state_changed); style.addWidget(self.caption_line_height, 7, 1)
        style.addWidget(QLabel("字间距", objectName="muted"), 7, 2); self.caption_letter_spacing = QSpinBox(); self.caption_letter_spacing.setRange(-3, 12); self.caption_letter_spacing.setValue(0); self.caption_letter_spacing.valueChanged.connect(self._state_changed); style.addWidget(self.caption_letter_spacing, 7, 3)

        self.caption_karaoke = QCheckBox("卡拉OK逐词高亮"); self.caption_karaoke.stateChanged.connect(self._state_changed); style.addWidget(self.caption_karaoke, 8, 0, 1, 2)
        style.addWidget(QLabel("当前词", objectName="muted"), 8, 2); self.caption_karaoke_active_btn = QPushButton("#FFD54A"); self.caption_karaoke_active_btn.clicked.connect(lambda: self._choose_caption_color(self.caption_karaoke_active_btn, "当前词高亮颜色")); style.addWidget(self.caption_karaoke_active_btn, 8, 3)
        style.addWidget(QLabel("已读颜色", objectName="muted"), 9, 0); self.caption_karaoke_read_btn = QPushButton("#FFFFFF"); self.caption_karaoke_read_btn.clicked.connect(lambda: self._choose_caption_color(self.caption_karaoke_read_btn, "已读文字颜色")); style.addWidget(self.caption_karaoke_read_btn, 9, 1)
        style.addWidget(QLabel("未读颜色", objectName="muted"), 9, 2); self.caption_karaoke_unread_btn = QPushButton("#C9C9C9"); self.caption_karaoke_unread_btn.clicked.connect(lambda: self._choose_caption_color(self.caption_karaoke_unread_btn, "未读文字颜色")); style.addWidget(self.caption_karaoke_unread_btn, 9, 3)
        style.addWidget(QLabel("当前词放大", objectName="muted"), 10, 0); self.caption_karaoke_scale = QSpinBox(); self.caption_karaoke_scale.setRange(100, 140); self.caption_karaoke_scale.setSuffix("%"); self.caption_karaoke_scale.setValue(110); self.caption_karaoke_scale.valueChanged.connect(self._state_changed); style.addWidget(self.caption_karaoke_scale, 10, 1)
        self.caption_karaoke_hint = QLabel("有词级时间戳时精确跟随；没有时按该字幕段的词数和时长自动估算。", objectName="muted"); self.caption_karaoke_hint.setWordWrap(True); style.addWidget(self.caption_karaoke_hint, 10, 2, 1, 3)
        b.addLayout(style)

        note = QLabel("预设只修改字幕视觉效果，不修改字幕正文、字幕时间点或任务映射。内置预设由 JSON 动态加载；你可以保存、复制、重命名、删除自己的预设。", objectName="muted"); note.setWordWrap(True); b.addWidget(note)
        return w

    def _broll_tab(self):
        w, b = self._tab()
        b.addWidget(QLabel("B-roll 覆盖轨", objectName="cardTitle"))
        self.broll_table = QTableWidget(0, 4); self.broll_table.setHorizontalHeaderLabels(["素材", "开始(s)", "结束(s)", "适配"])
        self.broll_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for c in (1,2,3): self.broll_table.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.broll_table.verticalHeader().setVisible(False); self.broll_table.setSelectionBehavior(QAbstractItemView.SelectRows); self.broll_table.itemChanged.connect(self._state_changed)
        b.addWidget(self.broll_table, 1)
        row = QHBoxLayout(); add = QPushButton("＋ 添加 B-roll"); add.clicked.connect(self._add_broll); row.addWidget(add)
        at = QPushButton("从当前播放位置添加"); at.clicked.connect(lambda: self._add_broll(use_current=True)); row.addWidget(at)
        delete = QPushButton("删除选中"); delete.clicked.connect(self._delete_broll_rows); row.addWidget(delete); b.addLayout(row)
        info = QLabel("B-roll 只覆盖画面，主视频原声音继续播放。时间以主视频开始为 0 秒。", objectName="muted"); info.setWordWrap(True); b.addWidget(info)
        return w

    def _title_tab(self):
        w, b = self._tab()
        self.title_enabled = QCheckBox("启用标题 / 文字图层"); self.title_enabled.stateChanged.connect(self._state_changed); b.addWidget(self.title_enabled)
        self.title_text = QPlainTextEdit(); self.title_text.setPlaceholderText("输入标题文字…"); self.title_text.setMaximumHeight(120); self.title_text.textChanged.connect(self._state_changed); b.addWidget(self.title_text)
        row = QHBoxLayout(); row.addWidget(QLabel("模板", objectName="muted")); self.title_preset = QComboBox(); self.title_preset.addItems(["普通标题", "顶部新闻标题", "两行大标题", "金色重点标题"]); self.title_preset.currentIndexChanged.connect(self._apply_title_preset); row.addWidget(self.title_preset, 1); b.addLayout(row)
        grid = QGridLayout(); grid.addWidget(QLabel("位置", objectName="muted"), 0, 0); self.title_position = QComboBox(); self.title_position.addItems(["顶部居中", "居中", "底部居中"]); self.title_position.currentIndexChanged.connect(self._state_changed); grid.addWidget(self.title_position, 0, 1)
        grid.addWidget(QLabel("字号", objectName="muted"), 1, 0); self.title_size = QSpinBox(); self.title_size.setRange(24, 140); self.title_size.setValue(58); self.title_size.valueChanged.connect(self._state_changed); grid.addWidget(self.title_size, 1, 1)
        self.title_color_btn = QPushButton("文字颜色"); self.title_color_btn.clicked.connect(lambda: self._choose_color("title")); grid.addWidget(self.title_color_btn, 2, 0)
        self.title_bg = QCheckBox("背景框"); self.title_bg.setChecked(True); self.title_bg.stateChanged.connect(self._state_changed); grid.addWidget(self.title_bg, 2, 1)
        b.addLayout(grid); b.addStretch(1)
        return w

    def _intro_outro_tab(self):
        w, b = self._tab()
        b.addWidget(QLabel("片头", objectName="cardTitle"))
        self.intro_enabled = QCheckBox("启用片头"); self.intro_enabled.stateChanged.connect(self._state_changed); b.addWidget(self.intro_enabled)
        self.intro_path, self.intro_duration = self._media_asset_row(b, "选择片头图片或视频", self._choose_intro)
        b.addWidget(QLabel("片尾", objectName="cardTitle"))
        self.outro_enabled = QCheckBox("启用片尾"); self.outro_enabled.stateChanged.connect(self._state_changed); b.addWidget(self.outro_enabled)
        self.outro_path, self.outro_duration = self._media_asset_row(b, "选择片尾图片或视频", self._choose_outro)
        b.addStretch(1)
        return w

    def _media_asset_row(self, box, placeholder, callback):
        r = QHBoxLayout(); path = QLineEdit(); path.setPlaceholderText(placeholder); path.textChanged.connect(self._state_changed); r.addWidget(path, 1)
        choose = QPushButton("选择…"); choose.clicked.connect(callback); r.addWidget(choose); box.addLayout(r)
        dur = QDoubleSpinBox(); dur.setRange(0.5, 30.0); dur.setValue(2.0); dur.setSuffix(" 秒"); dur.setSingleStep(0.5); dur.valueChanged.connect(self._state_changed)
        line = QHBoxLayout(); line.addWidget(QLabel("时长", objectName="muted")); line.addWidget(dur); line.addStretch(1); box.addLayout(line)
        return path, dur

    def _params_tab(self):
        w, b = self._tab()
        b.addWidget(QLabel("输出参数", objectName="cardTitle"))
        g = QGridLayout()
        g.addWidget(QLabel("画面比例", objectName="muted"), 0, 0); self.output_ratio = QComboBox(); self.output_ratio.addItems(["9:16", "16:9", "1:1"]); self.output_ratio.currentIndexChanged.connect(self._state_changed); g.addWidget(self.output_ratio, 0, 1)
        g.addWidget(QLabel("分辨率", objectName="muted"), 1, 0); self.resolution_label = QLabel("1080 × 1920", objectName="cardTitle"); g.addWidget(self.resolution_label, 1, 1)
        g.addWidget(QLabel("FPS", objectName="muted"), 2, 0); g.addWidget(QLabel("30", objectName="cardTitle"), 2, 1)
        g.addWidget(QLabel("编码", objectName="muted"), 3, 0); g.addWidget(QLabel("Remotion 默认 H.264 / AAC", objectName="cardTitle"), 3, 1)
        b.addLayout(g)
        b.addWidget(QLabel("输出目录", objectName="muted"))
        r = QHBoxLayout(); self.output_dir = QLineEdit(); self.output_dir.setText(self._settings.value("packaging/output_dir", str(Path.home() / "Movies" / "FlowStudio_Packaged"), type=str)); self.output_dir.textChanged.connect(self._state_changed); r.addWidget(self.output_dir, 1)
        choose = QPushButton("选择…"); choose.clicked.connect(self._choose_output_dir); r.addWidget(choose); b.addLayout(r)
        open_out = QPushButton("打开输出目录"); open_out.clicked.connect(self._open_output_dir); b.addWidget(open_out)
        b.addWidget(QLabel("Remotion 引擎", objectName="cardTitle"))
        self.remotion_status = QLabel("未检测", objectName="statusInfo"); self.remotion_status.setWordWrap(True); b.addWidget(self.remotion_status)
        path_row = QHBoxLayout(); self.remotion_dir = QLineEdit(); saved = self._settings.value("packaging/remotion_project_dir", "", type=str); self.remotion_dir.setText(saved or RemotionRenderer.autodetect()); self.remotion_dir.setPlaceholderText("Remotion 项目目录"); path_row.addWidget(self.remotion_dir, 1)
        browse = QPushButton("选择…"); browse.clicked.connect(self._choose_remotion_dir); path_row.addWidget(browse); b.addLayout(path_row)
        buttons = QHBoxLayout(); check = QPushButton("检测 Remotion"); check.clicked.connect(self._check_remotion); buttons.addWidget(check)
        install = QPushButton("安装/更新包装模板"); install.clicked.connect(self._install_template); buttons.addWidget(install); b.addLayout(buttons)
        self.remotion_log = QPlainTextEdit(); self.remotion_log.setReadOnly(True); self.remotion_log.setMaximumHeight(120); self.remotion_log.setPlaceholderText("这里只显示简洁的检测/渲染日志，不再把 CLI 帮助文档塞到页面顶部。")
        b.addWidget(self.remotion_log)
        b.addStretch(1)
        return w

    def _build_timeline_panel(self):
        card = QFrame(objectName="pageCard"); card.setMinimumHeight(190)
        box = QVBoxLayout(card); box.setContentsMargins(10, 9, 10, 9); box.setSpacing(5)
        top = QHBoxLayout(); top.addWidget(QLabel("包装时间线", objectName="sectionTitle")); top.addStretch(1)
        self.timeline_zoom = QSlider(Qt.Horizontal); self.timeline_zoom.setRange(50, 200); self.timeline_zoom.setValue(100); self.timeline_zoom.setMaximumWidth(180); top.addWidget(QLabel("缩放", objectName="muted")); top.addWidget(self.timeline_zoom)
        box.addLayout(top)
        self.timeline = QTableWidget(6, 2); self.timeline.setHorizontalHeaderLabels(["轨道", "内容 / 时间范围"]); self.timeline.verticalHeader().setVisible(False); self.timeline.horizontalHeader().setVisible(False)
        self.timeline.setEditTriggers(QAbstractItemView.NoEditTriggers); self.timeline.setSelectionMode(QAbstractItemView.NoSelection); self.timeline.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents); self.timeline.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.timeline.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        tracks = ["片头/片尾", "水印", "标题/文字", "字幕", "B-roll", "主视频 + 音频"]
        for i, name in enumerate(tracks):
            it = QTableWidgetItem(name); it.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft); self.timeline.setItem(i, 0, it); self.timeline.setItem(i, 1, QTableWidgetItem("—")); self.timeline.setRowHeight(i, 35)
        box.addWidget(self.timeline)
        return card

    # -------------------------------------------------------------- data model
    def _default_state(self, path: str) -> dict:
        return {
            "source": path,
            "status": "未包装",
            "duration": 0.0,
            "watermark": {"enabled": False, "path": "", "position": "右上", "scale": 18, "opacity": 92},
            "captions": [],
            "captionStyle": {
                "preset": "经典白字黑描边", "presetId": "builtin.classic-white-outline", "font": "Arial", "size": 54, "color": "#FFFFFF",
                "position": "底部居中", "weight": 800, "strokeColor": "#111111", "strokeWidth": 5,
                "background": False, "backgroundColor": "#000000", "backgroundOpacity": 0,
                "shadow": True, "shadowBlur": 10, "shadowY": 4, "radius": 16,
                "paddingX": 18, "paddingY": 10, "animation": "淡入", "maxWidth": 88,
                "lineHeight": 1.22, "letterSpacing": 0,
                "karaokeEnabled": False, "karaokeMode": "逐词高亮",
                "karaokeActiveColor": "#FFD54A", "karaokeReadColor": "#FFFFFF",
                "karaokeUnreadColor": "#C9C9C9", "karaokeActiveScale": 110, "karaokeTiming": "auto",
            },
            "broll": [],
            "title": {"enabled": False, "text": "", "position": "顶部居中", "size": 58, "color": "#FFFFFF", "background": True},
            "intro": {"enabled": False, "path": "", "duration": 2.0},
            "outro": {"enabled": False, "path": "", "duration": 2.0},
            "params": {"ratio": "9:16", "output_dir": self.output_dir.text() if hasattr(self, "output_dir") else ""},
        }

    def _current_state(self):
        return self._project.get("videos", {}).get(self._current_path)

    def _capture_controls(self):
        state = self._current_state()
        if not state or self._loading_state:
            return state
        state["watermark"] = {
            "enabled": self.wm_enabled.isChecked(), "path": self.wm_path.text().strip(),
            "position": self.wm_position.currentText(), "scale": self.wm_scale.value(), "opacity": self.wm_opacity.value(),
        }
        captions = []
        for r in range(self.caption_table.rowCount()):
            text_item = self.caption_table.item(r, 2)
            cap = {
                "start": _as_float(self.caption_table.item(r, 0).text() if self.caption_table.item(r,0) else 0),
                "end": _as_float(self.caption_table.item(r, 1).text() if self.caption_table.item(r,1) else 0),
                "text": text_item.text() if text_item else "",
            }
            # Preserve precise word-level timestamps only while the caption text itself
            # has not been edited.  If edited, Remotion safely falls back to estimated
            # word timing inside this caption segment.
            word_payload = text_item.data(Qt.UserRole) if text_item else None
            if isinstance(word_payload, dict) and word_payload.get("sourceText") == cap["text"] and word_payload.get("words"):
                cap["words"] = copy.deepcopy(word_payload["words"])
            captions.append(cap)
        state["captions"] = captions
        current_preset_id = self.caption_effect_preset.currentData() or ""
        current_preset = self._caption_presets.get(str(current_preset_id))
        state["captionStyle"] = {
            "preset": current_preset.name if current_preset else self.caption_effect_preset.currentText(), "presetId": current_preset_id,
            "font": self.caption_font.currentFont().family(), "size": self.caption_size.value(),
            "color": self.caption_color_btn.property("colorValue") or "#FFFFFF",
            "position": self.caption_position.currentText(), "weight": int(self.caption_weight.currentText() or 800),
            "strokeColor": self.caption_stroke_color_btn.property("colorValue") or "#000000",
            "strokeWidth": self.caption_stroke_width.value(),
            "background": self.caption_bg.isChecked(),
            "backgroundColor": self.caption_bg_color_btn.property("colorValue") or "#000000",
            "backgroundOpacity": self.caption_bg_opacity.value(),
            "shadow": self.caption_shadow.isChecked(), "shadowBlur": self.caption_shadow_blur.value(),
            "shadowY": self.caption_shadow_y.value(), "radius": 16, "paddingX": 18, "paddingY": 10,
            "animation": self.caption_animation.currentText(), "maxWidth": self.caption_max_width.value(),
            "lineHeight": self.caption_line_height.value(), "letterSpacing": self.caption_letter_spacing.value(),
            "karaokeEnabled": self.caption_karaoke.isChecked(), "karaokeMode": "逐词高亮",
            "karaokeActiveColor": self.caption_karaoke_active_btn.property("colorValue") or "#FFD54A",
            "karaokeReadColor": self.caption_karaoke_read_btn.property("colorValue") or "#FFFFFF",
            "karaokeUnreadColor": self.caption_karaoke_unread_btn.property("colorValue") or "#C9C9C9",
            "karaokeActiveScale": self.caption_karaoke_scale.value(), "karaokeTiming": "auto",
        }
        broll = []
        for r in range(self.broll_table.rowCount()):
            broll.append({
                "path": self.broll_table.item(r,0).data(Qt.UserRole) if self.broll_table.item(r,0) else "",
                "start": _as_float(self.broll_table.item(r,1).text() if self.broll_table.item(r,1) else 0),
                "end": _as_float(self.broll_table.item(r,2).text() if self.broll_table.item(r,2) else 0),
                "fit": self.broll_table.item(r,3).text() if self.broll_table.item(r,3) else "cover",
            })
        state["broll"] = broll
        state["title"] = {
            "enabled": self.title_enabled.isChecked(), "text": self.title_text.toPlainText(),
            "position": self.title_position.currentText(), "size": self.title_size.value(),
            "color": self.title_color_btn.property("colorValue") or "#FFFFFF", "background": self.title_bg.isChecked(),
        }
        state["intro"] = {"enabled": self.intro_enabled.isChecked(), "path": self.intro_path.text().strip(), "duration": self.intro_duration.value()}
        state["outro"] = {"enabled": self.outro_enabled.isChecked(), "path": self.outro_path.text().strip(), "duration": self.outro_duration.value()}
        state["params"] = {"ratio": self.output_ratio.currentText(), "output_dir": self.output_dir.text().strip()}
        return state

    def _load_state(self, state: dict):
        self._loading_state = True
        try:
            wm = state.get("watermark") or {}
            self.wm_enabled.setChecked(bool(wm.get("enabled"))); self.wm_path.setText(str(wm.get("path") or "")); self.wm_position.setCurrentText(str(wm.get("position") or "右上")); self.wm_scale.setValue(int(wm.get("scale") or 18)); self.wm_opacity.setValue(int(wm.get("opacity") or 92))
            cs = state.get("captionStyle") or {}
            preset_key = str(cs.get("presetId") or cs.get("preset") or "经典白字黑描边")
            self._refresh_caption_preset_choices(prefer_id=preset_key, prefer_name=str(cs.get("preset") or ""))
            self.caption_size.setValue(int(cs.get("size") or 54)); self.caption_position.setCurrentText(str(cs.get("position") or "底部居中"))
            self.caption_weight.setCurrentText(str(int(cs.get("weight") or 800))); self.caption_stroke_width.setValue(int(cs.get("strokeWidth") or 0))
            self.caption_bg.setChecked(bool(cs.get("background", False))); self.caption_bg_opacity.setValue(int(cs.get("backgroundOpacity") or 0))
            self.caption_shadow.setChecked(bool(cs.get("shadow", True))); self.caption_shadow_blur.setValue(int(cs.get("shadowBlur") or 10)); self.caption_shadow_y.setValue(int(cs.get("shadowY") or 4))
            self.caption_animation.setCurrentText(str(cs.get("animation") or "淡入")); self.caption_max_width.setValue(int(cs.get("maxWidth") or 88))
            self.caption_line_height.setValue(float(cs.get("lineHeight") or 1.22)); self.caption_letter_spacing.setValue(int(cs.get("letterSpacing") or 0))
            self._set_color_button(self.caption_color_btn, str(cs.get("color") or "#FFFFFF")); self._set_color_button(self.caption_stroke_color_btn, str(cs.get("strokeColor") or "#000000")); self._set_color_button(self.caption_bg_color_btn, str(cs.get("backgroundColor") or "#000000"))
            self.caption_karaoke.setChecked(bool(cs.get("karaokeEnabled", False)))
            self.caption_karaoke_scale.setValue(int(cs.get("karaokeActiveScale") or 110))
            self._set_color_button(self.caption_karaoke_active_btn, str(cs.get("karaokeActiveColor") or "#FFD54A"))
            self._set_color_button(self.caption_karaoke_read_btn, str(cs.get("karaokeReadColor") or "#FFFFFF"))
            self._set_color_button(self.caption_karaoke_unread_btn, str(cs.get("karaokeUnreadColor") or "#C9C9C9"))
            if cs.get("font"):
                self.caption_font.setCurrentFont(QFont(str(cs.get("font"))))
            self.caption_table.setRowCount(0)
            for cap in state.get("captions") or []: self._append_caption(cap)
            self.broll_table.setRowCount(0)
            for item in state.get("broll") or []: self._append_broll(item)
            title = state.get("title") or {}; self.title_enabled.setChecked(bool(title.get("enabled"))); self.title_text.setPlainText(str(title.get("text") or "")); self.title_position.setCurrentText(str(title.get("position") or "顶部居中")); self.title_size.setValue(int(title.get("size") or 58)); self.title_bg.setChecked(bool(title.get("background", True))); self._set_color_button(self.title_color_btn, str(title.get("color") or "#FFFFFF"))
            intro = state.get("intro") or {}; self.intro_enabled.setChecked(bool(intro.get("enabled"))); self.intro_path.setText(str(intro.get("path") or "")); self.intro_duration.setValue(float(intro.get("duration") or 2.0))
            outro = state.get("outro") or {}; self.outro_enabled.setChecked(bool(outro.get("enabled"))); self.outro_path.setText(str(outro.get("path") or "")); self.outro_duration.setValue(float(outro.get("duration") or 2.0))
            params = state.get("params") or {}; self.output_ratio.setCurrentText(str(params.get("ratio") or "9:16"));
            if params.get("output_dir"): self.output_dir.setText(str(params["output_dir"]))
        finally:
            self._loading_state = False
        self.modified_badge.setText(str(state.get("status") or "未包装"))
        self._update_preview_overlays(); self._update_timeline(); self._update_resolution()

    def _state_changed(self, *args):
        if self._loading_state: return
        state = self._capture_controls()
        if state:
            if state.get("status") not in ("渲染中", "已完成"):
                state["status"] = "已编辑"
            self.modified_badge.setText(state["status"])
            self._update_tree_status(self._current_path)
        self.wm_scale_value.setText(f"{self.wm_scale.value()}%")
        self.wm_opacity_value.setText(f"{self.wm_opacity.value()}%")
        self._update_preview_overlays(); self._update_timeline(); self._update_resolution()

    # -------------------------------------------------------------- import/tree
    def _import_videos(self):
        files, _ = QFileDialog.getOpenFileNames(self, "导入包装视频", str(Path.home() / "Movies"), "Video (*.mp4 *.mov *.m4v *.webm *.mkv)")
        self._add_video_paths(files)

    def _import_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "导入视频文件夹", str(Path.home() / "Movies"))
        if not folder: return
        paths = [str(p) for p in sorted(Path(folder).rglob("*")) if p.is_file() and p.suffix.lower() in VIDEO_EXTS]
        self._add_video_paths(paths)

    def _add_video_paths(self, paths):
        changed = False
        for raw in paths:
            p = str(Path(raw).expanduser().resolve())
            if not Path(p).is_file() or Path(p).suffix.lower() not in VIDEO_EXTS: continue
            if p not in self._project["videos"]:
                self._project["videos"][p] = self._default_state(p); self._project["order"].append(p); changed = True
        if changed: self._rebuild_tree(select_first=not bool(self._current_path))

    @staticmethod
    def _group_for_path(path: str):
        p = Path(path); stem = p.stem; bits = stem.split("-")
        if len(bits) >= 5 and bits[0].isdigit(): return bits[2] or "未分组", bits[3] or p.parent.name
        parent = p.parent.name or "本地视频"; grand = p.parent.parent.name if p.parent.parent != p.parent else "本地任务"
        return grand or "本地任务", parent

    def _rebuild_tree(self, select_first=False):
        keep = self._current_path; self.task_tree.blockSignals(True); self.task_tree.clear(); self._tree_items = {}; groups = {}; chosen = None
        for path in self._project.get("order", []):
            state = self._project["videos"].get(path)
            if not state: continue
            recipient, host = self._group_for_path(path)
            ritem = groups.get((recipient,))
            if not ritem:
                ritem = QTreeWidgetItem([f"👤 {recipient}"]); groups[(recipient,)] = ritem; self.task_tree.addTopLevelItem(ritem)
            hitem = groups.get((recipient, host))
            if not hitem:
                hitem = QTreeWidgetItem([f"▶ {host}"]); groups[(recipient, host)] = hitem; ritem.addChild(hitem)
            status = state.get("status", "未包装")
            icon = "✓" if status == "已完成" else ("⚠" if status == "失败" else "•")
            v = QTreeWidgetItem([f"{icon}  {Path(path).name}"]); v.setData(0, Qt.UserRole, path); hitem.addChild(v); self._tree_items[path] = v
            if path == keep: chosen = v
        self.task_tree.expandAll(); self.task_tree.blockSignals(False)
        self.material_count.setText(f"{len(self._project.get('order', []))} 个视频")
        if chosen: self.task_tree.setCurrentItem(chosen)
        elif select_first:
            for i in range(self.task_tree.topLevelItemCount()):
                r = self.task_tree.topLevelItem(i)
                if r.childCount() and r.child(0).childCount(): self.task_tree.setCurrentItem(r.child(0).child(0)); break

    def _filter_tree(self, text):
        needle = str(text or "").strip().lower()
        for i in range(self.task_tree.topLevelItemCount()):
            r = self.task_tree.topLevelItem(i); any_r = False
            for j in range(r.childCount()):
                h = r.child(j); any_h = False
                for k in range(h.childCount()):
                    v = h.child(k); hit = not needle or needle in (r.text(0)+" "+h.text(0)+" "+v.text(0)).lower(); v.setHidden(not hit); any_h |= hit
                h.setHidden(not any_h); any_r |= any_h
            r.setHidden(not any_r)

    def _tree_selected(self):
        items = self.task_tree.selectedItems();
        if not items: return
        path = items[0].data(0, Qt.UserRole)
        if path: self._select_video(str(path))

    def _select_video(self, path: str):
        if path == self._current_path and self._current_state(): return
        if self._current_path: self._capture_controls()
        self._current_path = path; state = self._project["videos"].get(path)
        if not state: return
        self.current_info.setText(f"当前片段：{Path(path).name}")
        self._load_state(state)
        if self.player:
            self.player.setSource(QUrl.fromLocalFile(path)); self.player.play(); self.play_btn.setText("❚❚")

    def _update_tree_status(self, path):
        if not path: return
        item = self._tree_items.get(path)
        state = self._project.get("videos", {}).get(path)
        if not item or not state: return
        status = state.get("status", "未包装")
        icon = "✓" if status == "已完成" else ("⚠" if status == "失败" else "•")
        item.setText(0, f"{icon}  {Path(path).name}")
        item.setToolTip(0, status)

    # -------------------------------------------------------------- preview
    def _player_position(self, value):
        if not self.seek.isSliderDown(): self.seek.setValue(int(value))
        duration = self.player.duration() if self.player else 0; self.time_label.setText(f"{_fmt_ms(value)} / {_fmt_ms(duration)}")
        self._update_current_caption(value / 1000.0)

    def _player_duration(self, value):
        self.seek.setRange(0, max(0, int(value)))
        state = self._current_state()
        if state and value > 0:
            state["duration"] = float(value) / 1000.0; self._update_timeline()
        self.time_label.setText(f"{_fmt_ms(self.player.position() if self.player else 0)} / {_fmt_ms(value)}")

    def _seek_to(self, value):
        if self.player: self.player.setPosition(int(value))

    def _toggle_play(self):
        if not self.player or not self._current_path: return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState: self.player.pause(); self.play_btn.setText("▶")
        else: self.player.play(); self.play_btn.setText("❚❚")

    def _toggle_fullscreen(self):
        if self.video_widget and hasattr(self.video_widget, "setFullScreen"): self.video_widget.setFullScreen(not self.video_widget.isFullScreen())

    def _open_current_video(self):
        if self._current_path: QDesktopServices.openUrl(QUrl.fromLocalFile(self._current_path))

    @staticmethod
    def _overlay_slot(position):
        mapping = {
            "左上": (0,0,Qt.AlignTop|Qt.AlignLeft), "顶部居中": (0,1,Qt.AlignTop|Qt.AlignHCenter), "右上": (0,2,Qt.AlignTop|Qt.AlignRight),
            "左中": (1,0,Qt.AlignVCenter|Qt.AlignLeft), "居中": (1,1,Qt.AlignCenter), "右中": (1,2,Qt.AlignVCenter|Qt.AlignRight),
            "左下": (2,0,Qt.AlignBottom|Qt.AlignLeft), "底部居中": (2,1,Qt.AlignBottom|Qt.AlignHCenter), "右下": (2,2,Qt.AlignBottom|Qt.AlignRight),
        }
        return mapping.get(str(position), mapping["右上"])

    def _place_overlay(self, widget, position):
        try: self.overlay_grid.removeWidget(widget)
        except Exception: pass
        r,c,a=self._overlay_slot(position); self.overlay_grid.addWidget(widget,r,c,a)

    def _update_preview_overlays(self):
        state = self._current_state()
        if not state:
            self.preview_title.clear(); self.preview_caption.clear(); self.preview_watermark.clear(); return
        title = state.get("title") or {}
        self.preview_title.setVisible(bool(title.get("enabled") and title.get("text"))); self.preview_title.setText(str(title.get("text") or "")); self._place_overlay(self.preview_title,title.get("position","顶部居中"))
        if title.get("color"):
            px=max(14,min(34,int(title.get("size",58)*0.38))); bg="rgba(0,0,0,110)" if title.get("background",True) else "transparent"
            self.preview_title.setStyleSheet(f"color:{title.get('color')};font-size:{px}px;font-weight:800;background:{bg};padding:6px;border-radius:6px;")
        wm = state.get("watermark") or {}; path = str(wm.get("path") or ""); self._place_overlay(self.preview_watermark,wm.get("position","右上"))
        size=max(44,min(160,int(wm.get("scale",18)*5.3))); self.preview_watermark.setFixedSize(size,max(36,int(size*0.7)))
        self.preview_watermark.clear(); self.preview_watermark.setVisible(bool(wm.get("enabled") and Path(path).is_file()))
        if wm.get("enabled") and Path(path).is_file():
            pm = QPixmap(path)
            if not pm.isNull(): self.preview_watermark.setPixmap(pm.scaled(self.preview_watermark.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        pos = (self.player.position() / 1000.0) if self.player else 0.0; self._update_current_caption(pos)
        self.ratio_badge.setText((state.get("params") or {}).get("ratio", "9:16"))

    def _update_current_caption(self, sec: float):
        state = self._current_state(); current = None
        if state:
            for cap in state.get("captions") or []:
                if float(cap.get("start") or 0) <= sec < float(cap.get("end") or 0):
                    current = cap; break
            style = state.get("captionStyle") or {}; color = style.get("color", "#FFFFFF"); self._place_overlay(self.preview_caption,style.get("position","底部居中"))
            px=max(13,min(34,int(style.get("size",54)*0.36)))
            bg = "transparent"
            if style.get("background", False):
                c = QColor(str(style.get("backgroundColor") or "#000000")); alpha = max(0, min(255, int(float(style.get("backgroundOpacity",55))*2.55)))
                bg = f"rgba({c.red()},{c.green()},{c.blue()},{alpha})"
            weight = int(style.get("weight") or 800)
            radius = max(0, int(float(style.get("radius",16))*0.45))
            self.preview_caption.setStyleSheet(f"color:{color};font-size:{px}px;font-weight:{weight};background:{bg};padding:7px 10px;border-radius:{radius}px;")
        if not current:
            self.preview_caption.clear(); self.preview_caption.setVisible(False); return

        text = str(current.get("text") or "")
        if state and bool((state.get("captionStyle") or {}).get("karaokeEnabled")) and text.strip():
            style = state.get("captionStyle") or {}
            words = current.get("words") if isinstance(current.get("words"), list) else []
            active_index = -1
            explicit = False
            if words:
                cap_start = float(current.get("start") or 0); cap_end = float(current.get("end") or cap_start)
                cap_dur = max(0.001, cap_end-cap_start)
                for i, word in enumerate(words):
                    try:
                        ws = float(word.get("start")); we = float(word.get("end"))
                    except Exception:
                        continue
                    # Support both absolute video time and segment-relative time.
                    if ws < cap_start - 0.001 and 0 <= ws <= cap_dur + 0.001:
                        ws += cap_start; we += cap_start
                    if ws <= sec < we:
                        active_index = i; explicit = True; break
                if active_index < 0 and words:
                    # Between explicit words: mark all finished words as read, next as active.
                    for i, word in enumerate(words):
                        try:
                            ws = float(word.get("start")); we = float(word.get("end"))
                        except Exception:
                            continue
                        if ws < cap_start - 0.001 and 0 <= ws <= cap_dur + 0.001:
                            ws += cap_start; we += cap_start
                        if sec < ws:
                            active_index = i; explicit = True; break
                    if active_index < 0: active_index = len(words)-1
                display_words = [str(w.get("text") or "").strip() for w in words]
            else:
                display_words = text.split()
            if display_words:
                if not explicit:
                    cap_start = float(current.get("start") or 0); cap_end = float(current.get("end") or cap_start + 0.1)
                    progress = max(0.0, min(0.999999, (sec-cap_start) / max(0.001, cap_end-cap_start)))
                    active_index = min(len(display_words)-1, int(progress * len(display_words)))
                active_color = str(style.get("karaokeActiveColor") or "#FFD54A")
                read_color = str(style.get("karaokeReadColor") or "#FFFFFF")
                unread_color = str(style.get("karaokeUnreadColor") or "#C9C9C9")
                pieces=[]
                for i, word in enumerate(display_words):
                    c = active_color if i == active_index else (read_color if i < active_index else unread_color)
                    pieces.append(f'<span style="color:{html.escape(c)}">{html.escape(word)}</span>')
                self.preview_caption.setText(" ".join(pieces))
            else:
                self.preview_caption.setText(html.escape(text))
        else:
            self.preview_caption.setText(text)
        self.preview_caption.setVisible(bool(text))

    # -------------------------------------------------------------- controls
    def _choose_watermark(self):
        f, _ = QFileDialog.getOpenFileName(self, "选择水印", str(Path.home()), "Image (*.png *.jpg *.jpeg *.webp *.gif)")
        if f: self.wm_path.setText(f); self.wm_enabled.setChecked(True)

    def _apply_wm_preset(self):
        name = self.wm_preset.currentText()
        presets = {"右上 Logo":("右上",18,92), "左上 Logo":("左上",18,92), "右下 Logo":("右下",18,90), "底部居中半透明":("底部居中",24,70)}
        pos, scale, opacity = presets.get(name, ("右上",18,92)); self.wm_position.setCurrentText(pos); self.wm_scale.setValue(scale); self.wm_opacity.setValue(opacity)

    def _refresh_caption_preset_choices(self, *args, prefer_id: str = "", prefer_name: str = ""):
        if not hasattr(self, "caption_effect_preset"):
            return
        current_id = str(self.caption_effect_preset.currentData() or "")
        target_id = str(prefer_id or current_id or "")
        target_name = str(prefer_name or "")
        category = self.caption_preset_category.currentText() if hasattr(self, "caption_preset_category") else "全部"
        query = self.caption_preset_search.text() if hasattr(self, "caption_preset_search") else ""
        choices = self._caption_presets.filtered(category, query)
        self.caption_effect_preset.blockSignals(True)
        self.caption_effect_preset.clear()
        selected = -1
        for i, preset in enumerate(choices):
            suffix = "" if preset.builtin else " · 自定义"
            self.caption_effect_preset.addItem(f"{preset.name}{suffix}", preset.id)
            if preset.id == target_id or (target_name and preset.name == target_name):
                selected = i
        if selected < 0 and choices:
            # Prefer the classic baseline when it is visible.
            for i, preset in enumerate(choices):
                if preset.id == "builtin.classic-white-outline":
                    selected = i
                    break
        if selected >= 0:
            self.caption_effect_preset.setCurrentIndex(selected)
        self.caption_effect_preset.blockSignals(False)
        self._caption_preset_changed()

    def _reload_caption_presets(self):
        current = str(self.caption_effect_preset.currentData() or "") if hasattr(self, "caption_effect_preset") else ""
        self._caption_presets.reload()
        if hasattr(self, "caption_preset_category"):
            category = self.caption_preset_category.currentText()
            self.caption_preset_category.blockSignals(True)
            self.caption_preset_category.clear(); self.caption_preset_category.addItem("全部"); self.caption_preset_category.addItems(self._caption_presets.categories())
            if self.caption_preset_category.findText(category) >= 0:
                self.caption_preset_category.setCurrentText(category)
            self.caption_preset_category.blockSignals(False)
        self._refresh_caption_preset_choices(prefer_id=current)
        if self._caption_presets.errors:
            QMessageBox.warning(self, "字幕预设", "有部分 JSON 预设未能加载：\n\n" + "\n".join(self._caption_presets.errors[:8]))

    def _caption_preset_changed(self, *args):
        if not hasattr(self, "caption_preset_note"):
            return
        preset = self._caption_presets.get(str(self.caption_effect_preset.currentData() or ""))
        if not preset:
            self.caption_preset_note.setText("当前筛选条件下没有字幕预设。")
            return
        origin = "系统内置" if preset.builtin else "自定义"
        tags = f" · {' / '.join(preset.tags)}" if preset.tags else ""
        self.caption_preset_note.setText(f"{preset.category} · {origin}{tags}\n{preset.description}")

    def _caption_style_from_controls(self) -> dict:
        """Capture visual-only caption settings for preset save/apply."""
        return {
            "font": self.caption_font.currentFont().family(), "size": self.caption_size.value(),
            "color": self.caption_color_btn.property("colorValue") or "#FFFFFF",
            "position": self.caption_position.currentText(), "weight": int(self.caption_weight.currentText() or 800),
            "strokeColor": self.caption_stroke_color_btn.property("colorValue") or "#000000",
            "strokeWidth": self.caption_stroke_width.value(), "background": self.caption_bg.isChecked(),
            "backgroundColor": self.caption_bg_color_btn.property("colorValue") or "#000000",
            "backgroundOpacity": self.caption_bg_opacity.value(), "shadow": self.caption_shadow.isChecked(),
            "shadowBlur": self.caption_shadow_blur.value(), "shadowY": self.caption_shadow_y.value(),
            "radius": 16, "paddingX": 18, "paddingY": 10, "animation": self.caption_animation.currentText(),
            "maxWidth": self.caption_max_width.value(), "lineHeight": self.caption_line_height.value(),
            "letterSpacing": self.caption_letter_spacing.value(), "karaokeEnabled": self.caption_karaoke.isChecked(),
            "karaokeMode": "逐词高亮", "karaokeActiveColor": self.caption_karaoke_active_btn.property("colorValue") or "#FFD54A",
            "karaokeReadColor": self.caption_karaoke_read_btn.property("colorValue") or "#FFFFFF",
            "karaokeUnreadColor": self.caption_karaoke_unread_btn.property("colorValue") or "#C9C9C9",
            "karaokeActiveScale": self.caption_karaoke_scale.value(), "karaokeTiming": "auto",
        }

    def _apply_caption_style_dict(self, preset: dict):
        preset = CaptionPresetLibrary.normalize_style(preset or {})
        self._loading_state = True
        try:
            if preset.get("font"):
                self.caption_font.setCurrentFont(QFont(str(preset.get("font"))))
            self.caption_size.setValue(int(preset.get("size", 54)))
            self.caption_position.setCurrentText(str(preset.get("position", "底部居中")))
            self.caption_weight.setCurrentText(str(int(preset.get("weight", 800))))
            self.caption_stroke_width.setValue(int(preset.get("strokeWidth", 0)))
            self.caption_bg.setChecked(bool(preset.get("background", False)))
            self.caption_bg_opacity.setValue(int(preset.get("backgroundOpacity", 0)))
            self.caption_shadow.setChecked(bool(preset.get("shadow", True)))
            self.caption_shadow_blur.setValue(int(preset.get("shadowBlur", 10)))
            self.caption_shadow_y.setValue(int(preset.get("shadowY", 4)))
            self.caption_animation.setCurrentText(str(preset.get("animation", "淡入")))
            self.caption_max_width.setValue(int(preset.get("maxWidth", 88)))
            self.caption_line_height.setValue(float(preset.get("lineHeight", 1.22)))
            self.caption_letter_spacing.setValue(int(preset.get("letterSpacing", 0)))
            self._set_color_button(self.caption_color_btn, str(preset.get("color", "#FFFFFF")))
            self._set_color_button(self.caption_stroke_color_btn, str(preset.get("strokeColor", "#000000")))
            self._set_color_button(self.caption_bg_color_btn, str(preset.get("backgroundColor", "#000000")))
            self.caption_karaoke.setChecked(bool(preset.get("karaokeEnabled", False)))
            self.caption_karaoke_scale.setValue(int(preset.get("karaokeActiveScale", 110)))
            self._set_color_button(self.caption_karaoke_active_btn, str(preset.get("karaokeActiveColor", "#FFD54A")))
            self._set_color_button(self.caption_karaoke_read_btn, str(preset.get("karaokeReadColor", "#FFFFFF")))
            self._set_color_button(self.caption_karaoke_unread_btn, str(preset.get("karaokeUnreadColor", "#C9C9C9")))
        finally:
            self._loading_state = False
        self._state_changed()

    def _apply_caption_effect_preset(self):
        preset = self._caption_presets.get(str(self.caption_effect_preset.currentData() or ""))
        if not preset:
            return
        self._apply_caption_style_dict(preset.style)
        state = self._current_state()
        if state:
            state.setdefault("captionStyle", {})["preset"] = preset.name
            state["captionStyle"]["presetId"] = preset.id

    def _save_current_caption_preset(self):
        name, ok = QInputDialog.getText(self, "保存字幕预设", "新预设名称：")
        if not ok or not str(name).strip():
            return
        category, ok = QInputDialog.getItem(self, "字幕预设分类", "分类：", ["自定义", "基础", "短视频", "宗教", "卡拉OK"], 0, True)
        if not ok:
            return
        description, ok = QInputDialog.getText(self, "字幕预设说明", "说明（可留空）：")
        if not ok:
            return
        try:
            preset = self._caption_presets.save_custom(name=str(name).strip(), style=self._caption_style_from_controls(), category=str(category).strip() or "自定义", description=str(description).strip())
            self._reload_caption_presets()
            self.caption_preset_category.setCurrentText("全部")
            self.caption_preset_search.clear()
            self._refresh_caption_preset_choices(prefer_id=preset.id)
        except Exception as exc:
            QMessageBox.warning(self, "字幕预设", f"保存失败：{exc}")

    def _update_current_caption_preset(self):
        preset = self._caption_presets.get(str(self.caption_effect_preset.currentData() or ""))
        if not preset:
            return
        if preset.builtin:
            QMessageBox.information(self, "字幕预设", "系统内置预设保持只读。请先“保存当前为新预设”或在管理器中复制，再编辑自定义版本。")
            return
        try:
            updated = self._caption_presets.save_custom(name=preset.name, style=self._caption_style_from_controls(), category=preset.category, description=preset.description, tags=preset.tags, preset_id=preset.id)
            self._reload_caption_presets(); self._refresh_caption_preset_choices(prefer_id=updated.id)
        except Exception as exc:
            QMessageBox.warning(self, "字幕预设", f"更新失败：{exc}")

    def _manage_caption_presets(self):
        dlg = QDialog(self); dlg.setWindowTitle("字幕预设模板库"); dlg.resize(660, 480)
        outer = QVBoxLayout(dlg)
        info = QLabel("系统内置预设只读；复制后可自由修改。自定义预设保存在用户目录，升级 Flow Studio 不会覆盖。", objectName="muted")
        info.setWordWrap(True); outer.addWidget(info)
        lst = QListWidget(); outer.addWidget(lst, 1)

        def refill(select_id=""):
            lst.clear()
            for preset in self._caption_presets.presets:
                item = QListWidgetItem(f"[{preset.category}] {preset.name}    {'系统' if preset.builtin else '自定义'}")
                item.setData(Qt.UserRole, preset.id); item.setToolTip(preset.description); lst.addItem(item)
                if preset.id == select_id:
                    lst.setCurrentItem(item)
            if lst.currentRow() < 0 and lst.count(): lst.setCurrentRow(0)

        refill(str(self.caption_effect_preset.currentData() or ""))
        row = QHBoxLayout()
        duplicate = QPushButton("复制为自定义"); rename = QPushButton("重命名"); delete = QPushButton("删除"); open_dir = QPushButton("打开自定义预设目录"); refresh = QPushButton("刷新")
        for btn in (duplicate, rename, delete, open_dir, refresh): row.addWidget(btn)
        outer.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.Close); buttons.rejected.connect(dlg.reject); outer.addWidget(buttons)

        def selected():
            item = lst.currentItem()
            return self._caption_presets.get(str(item.data(Qt.UserRole))) if item else None

        def do_duplicate():
            source = selected()
            if not source: return
            name, ok = QInputDialog.getText(dlg, "复制字幕预设", "新名称：", text=f"{source.name} 副本")
            if not ok or not str(name).strip(): return
            try:
                p = self._caption_presets.duplicate(source.id, str(name).strip()); refill(p.id)
            except Exception as exc: QMessageBox.warning(dlg, "字幕预设", str(exc))

        def do_rename():
            source = selected()
            if not source: return
            if source.builtin:
                QMessageBox.information(dlg, "字幕预设", "系统内置预设不能直接改名，请先“复制为自定义”。")
                return
            name, ok = QInputDialog.getText(dlg, "重命名字幕预设", "新名称：", text=source.name)
            if not ok or not str(name).strip(): return
            try:
                p = self._caption_presets.rename_custom(source.id, str(name).strip()); refill(p.id)
            except Exception as exc: QMessageBox.warning(dlg, "字幕预设", str(exc))

        def do_delete():
            source = selected()
            if not source: return
            if source.builtin:
                QMessageBox.information(dlg, "字幕预设", "系统内置预设不能删除。")
                return
            if QMessageBox.question(dlg, "删除字幕预设", f"确定删除“{source.name}”吗？") != QMessageBox.Yes: return
            try:
                self._caption_presets.delete_custom(source.id); refill()
            except Exception as exc: QMessageBox.warning(dlg, "字幕预设", str(exc))

        duplicate.clicked.connect(do_duplicate); rename.clicked.connect(do_rename); delete.clicked.connect(do_delete)
        open_dir.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._caption_presets.user_dir))))
        refresh.clicked.connect(lambda: (self._caption_presets.reload(), refill()))
        dlg.exec()
        self._reload_caption_presets()

    def _choose_caption_color(self, btn, title):
        initial = QColor(btn.property("colorValue") or "#FFFFFF")
        c = QColorDialog.getColor(initial, self, title)
        if c.isValid():
            self._set_color_button(btn, c.name().upper())
            self._state_changed()

    def _import_captions(self):
        f, _ = QFileDialog.getOpenFileName(self, "导入字幕/分段文案", str(Path.home()), "Subtitle/Text (*.srt *.txt *.md);;All Files (*)")
        if not f: return
        try: text = Path(f).read_text(encoding="utf-8-sig")
        except Exception as exc: QMessageBox.warning(self, "字幕", f"读取失败：{exc}"); return
        caps = self._parse_srt(text) if Path(f).suffix.lower() == ".srt" else [{"text": line.strip(), "start":0, "end":0} for line in text.splitlines() if line.strip()]
        self._loading_state = True; self.caption_table.setRowCount(0)
        for cap in caps: self._append_caption(cap)
        self._loading_state = False
        if caps and all(float(c.get("end") or 0) <= 0 for c in caps): self._auto_caption_timing()
        else: self._state_changed()

    @staticmethod
    def _parse_srt(text: str):
        blocks = re.split(r"\n\s*\n", text.strip()); out = []
        def ts(s):
            m = re.search(r"(\d+):(\d+):(\d+)[,.](\d+)", s)
            return int(m.group(1))*3600 + int(m.group(2))*60 + int(m.group(3)) + int(m.group(4))/1000 if m else 0.0
        for block in blocks:
            lines = [x.strip() for x in block.splitlines() if x.strip()]
            idx = next((i for i,x in enumerate(lines) if "-->" in x), -1)
            if idx < 0: continue
            a,b = [x.strip() for x in lines[idx].split("-->",1)]; body = " ".join(lines[idx+1:])
            if body: out.append({"start":ts(a), "end":ts(b), "text":body})
        return out

    def _append_caption(self, cap):
        r = self.caption_table.rowCount(); self.caption_table.insertRow(r)
        self.caption_table.setItem(r,0,QTableWidgetItem(f"{float(cap.get('start') or 0):.2f}")); self.caption_table.setItem(r,1,QTableWidgetItem(f"{float(cap.get('end') or 0):.2f}"))
        text = str(cap.get('text') or ""); text_item = QTableWidgetItem(text)
        if isinstance(cap.get("words"), list) and cap.get("words"):
            text_item.setData(Qt.UserRole, {"sourceText": text, "words": copy.deepcopy(cap.get("words"))})
            text_item.setToolTip("包含词级时间戳：卡拉OK高亮将精确跟随单词。")
        self.caption_table.setItem(r,2,text_item)

    def _add_caption_row(self):
        start = (self.player.position()/1000.0) if self.player else 0.0; self._append_caption({"start":start,"end":start+5,"text":"新字幕"}); self._state_changed()

    def _delete_caption_rows(self):
        rows = sorted({i.row() for i in self.caption_table.selectionModel().selectedRows()}, reverse=True)
        for r in rows: self.caption_table.removeRow(r)
        self._state_changed()

    def _auto_caption_timing(self):
        n = self.caption_table.rowCount(); state = self._current_state(); duration = float((state or {}).get("duration") or 0)
        if not n: return
        if duration <= 0 and self._current_path:
            duration = RemotionRenderer(self.remotion_dir.text().strip()).probe_duration(self._current_path)
            if state and duration > 0: state["duration"] = duration
        if duration <= 0: duration = n * 7.5
        step = duration / n; self._loading_state = True
        for r in range(n):
            self.caption_table.item(r,0).setText(f"{r*step:.2f}"); self.caption_table.item(r,1).setText(f"{min(duration,(r+1)*step):.2f}")
        self._loading_state = False; self._state_changed()

    def _add_broll(self, use_current=False):
        files, _ = QFileDialog.getOpenFileNames(self, "添加 B-roll", str(Path.home()), "Media (*.mp4 *.mov *.m4v *.webm *.png *.jpg *.jpeg *.webp)")
        start = (self.player.position()/1000.0) if use_current and self.player else 0.0
        for i, f in enumerate(files): self._append_broll({"path":f,"start":start+i*5,"end":start+i*5+5,"fit":"cover"})
        if files: self._state_changed()

    def _append_broll(self, item):
        r = self.broll_table.rowCount(); self.broll_table.insertRow(r)
        file_item = QTableWidgetItem(Path(str(item.get("path") or "")).name); file_item.setData(Qt.UserRole, str(item.get("path") or "")); file_item.setToolTip(str(item.get("path") or "")); self.broll_table.setItem(r,0,file_item)
        self.broll_table.setItem(r,1,QTableWidgetItem(f"{float(item.get('start') or 0):.2f}")); self.broll_table.setItem(r,2,QTableWidgetItem(f"{float(item.get('end') or 0):.2f}")); self.broll_table.setItem(r,3,QTableWidgetItem(str(item.get("fit") or "cover")))

    def _delete_broll_rows(self):
        rows = sorted({i.row() for i in self.broll_table.selectionModel().selectedRows()}, reverse=True)
        for r in rows: self.broll_table.removeRow(r)
        self._state_changed()

    def _apply_title_preset(self):
        name = self.title_preset.currentText()
        if name == "普通标题": self.title_position.setCurrentText("顶部居中"); self.title_size.setValue(58); self._set_color_button(self.title_color_btn,"#FFFFFF"); self.title_bg.setChecked(True)
        elif name == "顶部新闻标题": self.title_position.setCurrentText("顶部居中"); self.title_size.setValue(50); self._set_color_button(self.title_color_btn,"#FFFFFF"); self.title_bg.setChecked(True)
        elif name == "两行大标题": self.title_position.setCurrentText("居中"); self.title_size.setValue(72); self._set_color_button(self.title_color_btn,"#FFFFFF"); self.title_bg.setChecked(True)
        else: self.title_position.setCurrentText("顶部居中"); self.title_size.setValue(64); self._set_color_button(self.title_color_btn,"#FFD54A"); self.title_bg.setChecked(False)
        self._state_changed()

    def _choose_color(self, which):
        btn = self.caption_color_btn if which == "caption" else self.title_color_btn
        initial = QColor(btn.property("colorValue") or "#FFFFFF"); c = QColorDialog.getColor(initial, self, "选择颜色")
        if c.isValid(): self._set_color_button(btn, c.name().upper()); self._state_changed()

    @staticmethod
    def _set_color_button(btn, color):
        btn.setProperty("colorValue", color); btn.setText(color); btn.setStyleSheet(f"background:{color};color:{'#111' if QColor(color).lightness()>150 else '#fff'};")

    def _choose_intro(self): self._choose_asset_into(self.intro_path, self.intro_enabled)
    def _choose_outro(self): self._choose_asset_into(self.outro_path, self.outro_enabled)
    def _choose_asset_into(self, line, enabled):
        f, _ = QFileDialog.getOpenFileName(self, "选择媒体", str(Path.home()), "Media (*.mp4 *.mov *.m4v *.webm *.png *.jpg *.jpeg *.webp)")
        if f: line.setText(f); enabled.setChecked(True)

    def _choose_output_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择包装输出目录", self.output_dir.text() or str(Path.home() / "Movies"))
        if d: self.output_dir.setText(d); self._settings.setValue("packaging/output_dir", d)

    def _open_output_dir(self):
        p = Path(self.output_dir.text().strip()).expanduser(); p.mkdir(parents=True, exist_ok=True); QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def _update_resolution(self):
        ratio = self.output_ratio.currentText(); text = {"9:16":"1080 × 1920","16:9":"1920 × 1080","1:1":"1080 × 1080"}.get(ratio,"1080 × 1920")
        self.resolution_label.setText(text); self.ratio_badge.setText(ratio)

    # -------------------------------------------------------------- timeline
    def _update_timeline(self):
        state = self._current_state()
        values = ["—"] * 6
        if state:
            intro = state.get("intro") or {}; outro = state.get("outro") or {}
            parts=[]
            if intro.get("enabled") and intro.get("path"): parts.append(f"片头 {float(intro.get('duration') or 0):.1f}s · {Path(intro['path']).name}")
            if outro.get("enabled") and outro.get("path"): parts.append(f"片尾 {float(outro.get('duration') or 0):.1f}s · {Path(outro['path']).name}")
            values[0] = "  |  ".join(parts) or "—"
            wm=state.get("watermark") or {}; values[1] = f"{Path(wm.get('path','')).name} · {wm.get('position','右上')} · {wm.get('scale',18)}%" if wm.get("enabled") and wm.get("path") else "—"
            title=state.get("title") or {}; values[2] = (str(title.get("text") or "")[:80] or "—") if title.get("enabled") else "—"
            values[3] = f"{len(state.get('captions') or [])} 段字幕" if state.get("captions") else "—"
            values[4] = "  |  ".join(f"{Path(x.get('path','')).name} [{x.get('start',0):.1f}-{x.get('end',0):.1f}s]" for x in (state.get("broll") or [])[:4]) or "—"
            values[5] = f"{Path(state.get('source','')).name} · {float(state.get('duration') or 0):.1f}s"
        for r, value in enumerate(values):
            if self.timeline.item(r,1): self.timeline.item(r,1).setText(value)

    # -------------------------------------------------------------- project/presets
    def _save_project(self):
        self._capture_controls()
        target = self._project_path
        if not target:
            target, _ = QFileDialog.getSaveFileName(self, "保存视频包装工程", str(Path.home()/"Documents"/"FlowStudio_Packaging.flowpack.json"), "Flow Packaging Project (*.flowpack.json);;JSON (*.json)")
        if not target: return
        if not target.lower().endswith(".json"): target += ".flowpack.json"
        try:
            Path(target).write_text(json.dumps(self._project, ensure_ascii=False, indent=2), encoding="utf-8"); self._project_path = target; self.render_status.setText("工程已保存")
        except Exception as exc: QMessageBox.warning(self,"保存工程",str(exc))

    def _load_project(self):
        f, _ = QFileDialog.getOpenFileName(self, "载入视频包装工程", str(Path.home()/"Documents"), "Flow Packaging Project (*.flowpack.json *.json)")
        if not f: return
        try:
            data = json.loads(Path(f).read_text(encoding="utf-8")); assert isinstance(data.get("videos"), dict)
        except Exception as exc: QMessageBox.warning(self,"载入工程",f"工程文件无效：{exc}"); return
        self._project = data; self._project.setdefault("order", list(self._project["videos"].keys())); self._project_path = f; self._current_path = ""; self._rebuild_tree(select_first=True); self.render_status.setText("工程已载入")

    def _preset_store(self):
        try: return json.loads(self._settings.value("packaging/custom_presets", "{}", type=str) or "{}")
        except Exception: return {}

    def _reload_preset_combo(self):
        if not hasattr(self,"preset_combo"): return
        current=self.preset_combo.currentText(); self.preset_combo.clear(); self.preset_combo.addItems(["标准包装", "字幕优先", "无水印简洁版"] + sorted(self._preset_store().keys())); self.preset_combo.setCurrentText(current)

    def _snapshot_packaging(self, state):
        return copy.deepcopy({k:state.get(k) for k in ("watermark","captions","captionStyle","broll","title","intro","outro","params")})

    def _save_named_preset(self):
        state=self._capture_controls()
        if not state: QMessageBox.information(self,"包装模板","请先选择一个视频并设置包装参数。"); return
        # Use the title text as a convenient suggested name only when short; otherwise generate a numbered name.
        store=self._preset_store(); base=f"自定义模板 {len(store)+1}"; name=base
        store[name]=self._snapshot_packaging(state); self._settings.setValue("packaging/custom_presets",json.dumps(store,ensure_ascii=False)); self._reload_preset_combo(); self.preset_combo.setCurrentText(name); self.render_status.setText(f"已保存模板：{name}")

    def _builtin_preset(self, name):
        state=self._default_state(self._current_path or "")
        if name=="标准包装": return self._snapshot_packaging(state)
        if name=="字幕优先":
            state["watermark"]["enabled"]=False; state["captionStyle"]["size"]=58; state["captionStyle"]["background"]=True; return self._snapshot_packaging(state)
        if name=="无水印简洁版":
            state["watermark"]["enabled"]=False; state["title"]["enabled"]=False; return self._snapshot_packaging(state)
        return None

    def _apply_named_preset(self):
        state=self._current_state()
        if not state: QMessageBox.information(self,"包装模板","请先选择视频。"); return
        name=self.preset_combo.currentText(); snap=self._builtin_preset(name) or self._preset_store().get(name)
        if not snap: return
        source=state.get("source"); duration=state.get("duration",0); status=state.get("status","未包装"); state.update(copy.deepcopy(snap)); state["source"]=source; state["duration"]=duration; state["status"]=status; self._load_state(state); self._state_changed()

    def _apply_to_all(self):
        state=self._capture_controls()
        if not state: QMessageBox.information(self,"应用到全部","请先选择并设置一个视频。"); return
        snap=self._snapshot_packaging(state); count=0
        for path, target in self._project.get("videos",{}).items():
            if path==self._current_path: continue
            source=target.get("source",path); duration=target.get("duration",0); status=target.get("status","未包装"); target.update(copy.deepcopy(snap)); target["source"]=source; target["duration"]=duration; target["status"]="已编辑" if status!="已完成" else status; count+=1
        self._rebuild_tree(False); self.render_status.setText(f"已应用到另外 {count} 个视频")

    # -------------------------------------------------------------- Remotion
    def _choose_remotion_dir(self):
        d = QFileDialog.getExistingDirectory(self,"选择 Remotion 项目目录",self.remotion_dir.text() or str(Path.home()))
        if d: self.remotion_dir.setText(d); self._settings.setValue("packaging/remotion_project_dir",d); self._engine_ok=False; self._update_engine_badge(); self._check_remotion()

    def _check_remotion(self):
        renderer=RemotionRenderer(self.remotion_dir.text().strip()); status=renderer.check(); self._engine_ok=status.ok
        if status.project_dir: self.remotion_dir.setText(status.project_dir); self._settings.setValue("packaging/remotion_project_dir",status.project_dir)
        self.remotion_status.setText(("✓ " if status.ok else "⚠ ")+status.message + (f"\nRemotion {status.version} · Node {status.node_version}" if status.ok else ""))
        self.remotion_status.setObjectName("statusGood" if status.ok else "statusInfo"); self.remotion_status.style().unpolish(self.remotion_status); self.remotion_status.style().polish(self.remotion_status)
        self.remotion_log.appendPlainText(f"检测：{status.message}")
        if status.ok: self.remotion_log.appendPlainText(f"Remotion {status.version} · Node {status.node_version}\n项目：{status.project_dir}")
        elif status.detail: self.remotion_log.appendPlainText(status.detail[-800:])
        self._update_engine_badge(); return status.ok

    def _update_engine_badge(self):
        if self._engine_ok: self.engine_badge.setText("● Remotion 已连接"); self.engine_badge.setObjectName("statusGood")
        else: self.engine_badge.setText("● Remotion 未检测"); self.engine_badge.setObjectName("statusInfo")
        self.engine_badge.style().unpolish(self.engine_badge); self.engine_badge.style().polish(self.engine_badge)

    def _install_template(self):
        try:
            entry=RemotionRenderer(self.remotion_dir.text().strip()).ensure_flowstudio_template(); self._engine_ok=True; self._update_engine_badge(); self.remotion_log.appendPlainText(f"Flow Studio 包装模板已就绪：{entry}"); QMessageBox.information(self,"Remotion","Flow Studio 包装模板已安装/更新。")
        except Exception as exc: QMessageBox.warning(self,"Remotion",str(exc))

    def _payload_for(self, path: str):
        if path == self._current_path: self._capture_controls()
        state=self._project["videos"][path]; duration=float(state.get("duration") or 0); renderer=RemotionRenderer(self.remotion_dir.text().strip())
        if duration<=0: duration=renderer.probe_duration(path); state["duration"]=duration
        if duration<=0: duration=30.0
        intro=state.get("intro") or {}; outro=state.get("outro") or {}; total=duration + (float(intro.get("duration") or 0) if intro.get("enabled") and intro.get("path") else 0) + (float(outro.get("duration") or 0) if outro.get("enabled") and outro.get("path") else 0)
        wm=copy.deepcopy(state.get("watermark") or {}); wm["opacity"]=float(wm.get("opacity",92))/100.0
        payload={"source":path,"mainDuration":duration,"totalDuration":total,"ratio":(state.get("params") or {}).get("ratio","9:16"),"watermark":wm,"captions":copy.deepcopy(state.get("captions") or []),"captionStyle":copy.deepcopy(state.get("captionStyle") or {}),"broll":copy.deepcopy(state.get("broll") or []),"title":copy.deepcopy(state.get("title") or {}),"intro":copy.deepcopy(intro),"outro":copy.deepcopy(outro)}
        return payload

    def _output_for(self, path: str):
        state=self._project["videos"][path]; outdir=Path((state.get("params") or {}).get("output_dir") or self.output_dir.text() or (Path.home()/"Movies"/"FlowStudio_Packaged")).expanduser(); outdir.mkdir(parents=True,exist_ok=True); return str(outdir/(Path(path).stem+"_packaged.mp4"))

    def _render_current(self):
        if not self._current_path: QMessageBox.information(self,"视频包装","请先导入并选择一个视频。"); return
        self._start_queue([self._current_path])

    def _render_all(self):
        paths=[p for p in self._project.get("order",[]) if Path(p).is_file()]
        if not paths: QMessageBox.information(self,"视频包装","当前没有可渲染的视频。"); return
        self._start_queue(paths)

    def _start_queue(self, paths):
        if self._render_process is not None: QMessageBox.information(self,"视频包装","已有渲染任务正在进行。"); return
        if not self._check_remotion(): QMessageBox.warning(self,"Remotion","Remotion 尚未连接，请先检查项目目录。"); return
        self._render_queue=list(paths); self._render_total=len(self._render_queue); self._render_done=0; self.render_progress.show(); self.render_progress.setValue(0); self.stop_btn.setEnabled(True); self.render_btn.setEnabled(False); self.batch_btn.setEnabled(False); self._render_next()

    def _render_next(self):
        if not self._render_queue:
            self._render_process=None; self._rendering_path=""; self.render_progress.setValue(100); self.render_status.setText("批量渲染完成"); self.stop_btn.setEnabled(False); self.render_btn.setEnabled(True); self.batch_btn.setEnabled(True); self._rebuild_tree(False); return
        path=self._render_queue.pop(0); self._rendering_path=path; state=self._project["videos"][path]; state["status"]="渲染中"; self.render_status.setText(f"渲染中：{Path(path).name}"); self.modified_badge.setText("渲染中") if path==self._current_path else None
        try:
            renderer=RemotionRenderer(self.remotion_dir.text().strip()); payload=self._payload_for(path); output=self._output_for(path); cmd,cwd=renderer.render_flowstudio_command(payload,output)
        except Exception as exc:
            state["status"]="失败"; self.remotion_log.appendPlainText(f"准备渲染失败：{exc}"); QTimer.singleShot(0,self._render_next); return
        self.remotion_log.appendPlainText("\n$ "+" ".join(cmd[:5])+" …")
        proc=QProcess(self); proc.setWorkingDirectory(cwd); proc.setProgram(cmd[0]); proc.setArguments(cmd[1:]); proc.setProcessChannelMode(QProcess.MergedChannels); proc.readyReadStandardOutput.connect(lambda:self._read_render_output(proc)); proc.finished.connect(lambda code,status:self._render_finished(proc,code)); proc.errorOccurred.connect(lambda err:self.remotion_log.appendPlainText("启动错误："+proc.errorString())); self._render_process=proc; proc.start()

    def _read_render_output(self, proc):
        data=bytes(proc.readAllStandardOutput()).decode("utf-8",errors="replace")
        if not data: return
        self.remotion_log.moveCursor(self.remotion_log.textCursor().End); self.remotion_log.insertPlainText(data)
        m=re.findall(r"(\d{1,3})%",data)
        if m: self.render_progress.setValue(max(0,min(99,int(m[-1]))))

    def _render_finished(self, proc, code):
        self._read_render_output(proc); path=self._rendering_path; self._render_process=None
        if path in self._project.get("videos",{}):
            state=self._project["videos"][path]; state["status"]="已完成" if code==0 else "失败"
            state["last_output"]=self._output_for(path) if code==0 else ""
        self.remotion_log.appendPlainText(f"\n退出码：{code} · {'完成' if code==0 else '失败'}")
        self._render_done += 1; self.render_progress.setValue(min(99,int(self._render_done/max(1,self._render_total)*100)))
        if path==self._current_path: self.modified_badge.setText(self._project["videos"][path]["status"])
        self._rebuild_tree(False); QTimer.singleShot(0,self._render_next)

    def _stop_render(self):
        self._render_queue.clear()
        if self._render_process is not None:
            try: self._render_process.kill()
            except Exception: pass
        self.render_status.setText("已停止"); self.stop_btn.setEnabled(False); self.render_btn.setEnabled(True); self.batch_btn.setEnabled(True)

    # -------------------------------------------------------------- shortcuts/lifecycle
    def _install_shortcuts(self):
        self._shortcuts=[]
        for key, fn in (("Space",self._toggle_play),("Ctrl+S",self._save_project),("Meta+S",self._save_project)):
            sc=QShortcut(QKeySequence(key),self); sc.setContext(Qt.WidgetWithChildrenShortcut); sc.activated.connect(fn); self._shortcuts.append(sc)

    def hideEvent(self, event):
        if self.player:
            try:self.player.pause(); self.play_btn.setText("▶")
            except Exception:pass
        super().hideEvent(event)

    def closeEvent(self, event):
        if self._render_process is not None:
            try:self._render_process.kill()
            except Exception:pass
        super().closeEvent(event)
