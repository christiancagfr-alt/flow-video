"""Interactive configuration & per-host binding dialog for Auto-Edit AI Watermarks."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QThread, Signal
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core import work_dates
from app.services import ai_watermark


class _RescanSheetWorker(QThread):
    finished_result = Signal(object, str)

    def __init__(self, day: str, parent=None):
        super().__init__(parent)
        self.day = day

    def run(self):
        try:
            res = ai_watermark.rescan_sheet_material_sources(self.day)
            self.finished_result.emit(res, '')
        except Exception as exc:
            self.finished_result.emit(None, str(exc))


class _WatermarkPreviewCanvas(QWidget):
    """Real-time 9:16 composite layer preview (V1 backdrop + V2 Main PNG + V3 Sub PNG/Text)."""

    REF_W = 720
    REF_H = 1280

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(162, 288)
        self._enabled = True
        self._host_active = True
        self._main_img: QImage | None = None
        self._sub_img: QImage | None = None
        self._badge_text = ''

    def set_layers(
        self,
        *,
        enabled: bool,
        host_active: bool,
        main_img: QImage | None,
        sub_img: QImage | None,
        badge_text: str = '',
    ):
        self._enabled = bool(enabled)
        self._host_active = bool(host_active)
        self._main_img = main_img if (main_img is not None and not main_img.isNull()) else None
        self._sub_img = sub_img if (sub_img is not None and not sub_img.isNull()) else None
        self._badge_text = str(badge_text or '')
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)

        rect = QRectF(1.0, 1.0, float(self.width() - 2), float(self.height() - 2))
        grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        grad.setColorAt(0.0, QColor('#1E293B'))
        grad.setColorAt(0.55, QColor('#0F172A'))
        grad.setColorAt(1.0, QColor('#1E1B4B'))
        p.setPen(QPen(QColor('#475569'), 1.2))
        p.setBrush(grad)
        p.drawRoundedRect(rect, 10.0, 10.0)

        # Subtle V1 guide lines
        guide_pen = QPen(QColor(255, 255, 255, 22), 1.0, Qt.DashLine)
        p.setPen(guide_pen)
        p.drawLine(int(rect.center().x()), int(rect.top() + 8), int(rect.center().x()), int(rect.bottom() - 8))
        p.drawLine(int(rect.left() + 8), int(rect.center().y()), int(rect.right() - 8), int(rect.center().y()))

        p.setPen(QColor(255, 255, 255, 75))
        f = p.font()
        f.setPixelSize(11)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(rect.left() + 8, rect.top() + 8, rect.width() - 16, 18), Qt.AlignLeft | Qt.AlignVCenter, '9:16 画面图层预览')

        if self._enabled and self._host_active:
            # Layer 1 (Lower Track): Main PNG at 1:1 relative to 720x1280 frame (centered if smaller/larger)
            if self._main_img is not None:
                self._draw_overlay_image(p, rect, self._main_img)
            # Layer 2 (Upper Track): Sub PNG / Text stacked on top of Main PNG
            if self._sub_img is not None:
                self._draw_overlay_image(p, rect, self._sub_img)

        if self._badge_text:
            pill_h = 22.0
            pill_rect = QRectF(rect.left() + 8, rect.top() + 30, rect.width() - 16, pill_h)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(15, 23, 42, 185))
            p.drawRoundedRect(pill_rect, 6.0, 6.0)
            p.setPen(QColor('#E2E8F0'))
            f2 = p.font()
            f2.setPixelSize(10)
            f2.setBold(False)
            p.setFont(f2)
            p.drawText(pill_rect.adjusted(6, 0, -6, 0), Qt.AlignCenter, self._badge_text)

        p.end()

    def _draw_overlay_image(self, painter: QPainter, canvas_rect: QRectF, img: QImage):
        iw = float(img.width())
        ih = float(img.height())
        if iw <= 0 or ih <= 0:
            return
        scale_x = canvas_rect.width() / float(self.REF_W)
        scale_y = canvas_rect.height() / float(self.REF_H)
        # In DaVinci Resolve, a still image without zoom scaling sits 1:1 centered on the timeline canvas
        # (or fills the canvas if 720x1280 / matching aspect). Fit proportionally if oversized.
        fit_scale = min(scale_x, scale_y)
        dw = iw * fit_scale
        dh = ih * fit_scale
        if dw > canvas_rect.width() or dh > canvas_rect.height():
            shrink = min(canvas_rect.width() / dw, canvas_rect.height() / dh)
            dw *= shrink
            dh *= shrink
        dx = canvas_rect.left() + (canvas_rect.width() - dw) * 0.5
        dy = canvas_rect.top() + (canvas_rect.height() - dh) * 0.5
        painter.drawImage(QRectF(dx, dy, dw, dh), img)


class AIWatermarkDialog(QDialog):
    """Full settings & host binding dialog for Auto-Edit AI Watermarks."""

    def __init__(self, day: str | None = None, parent=None):
        super().__init__(parent)
        self.day = work_dates.normalize_scope(day or work_dates.active())
        self.setWindowTitle(f'AI 水印自动挂载设置（{self.day}）')
        self.resize(1100, 810)
        self.setMinimumSize(980, 680)

        self._cfg = ai_watermark.load_config()
        self._hosts: list[dict] = []
        self._row_widgets: list[dict] = []
        self._rescan_worker: _RescanSheetWorker | None = None
        self._image_cache: dict[str, QImage] = {}
        self._building = True

        self._build_ui()
        self._load_from_config(self._cfg)
        self._reload_hosts_table()
        self._building = False
        self._on_any_setting_changed()

    def _btn(self, text: str, tier: str = 'l3', height: int = 32, tip: str = '') -> QPushButton:
        b = QPushButton(text, objectName='pcBtn')
        b.setProperty('tier', tier)
        b.setFixedHeight(height)
        b.setMinimumWidth(b.fontMetrics().horizontalAdvance(text) + 24)
        b.setCursor(Qt.PointingHandCursor)
        if tip:
            b.setToolTip(tip)
        return b

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(10)

        # ── 1. Top Enable Banner ──
        top_card = QFrame(objectName='workspacePanel')
        tl = QVBoxLayout(top_card)
        tl.setContentsMargins(14, 10, 14, 10)
        tl.setSpacing(4)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        self.enable_chk = QCheckBox('启用自动剪辑 AI 水印（点击「确认清理」时自动按主播连续区间挂载到空视频轨）')
        self.enable_chk.setStyleSheet('font-size:14px; font-weight:800;')
        self.enable_chk.toggled.connect(self._on_any_setting_changed)
        top_row.addWidget(self.enable_chk)
        top_row.addStretch(1)
        self.layer_rule_chip = QLabel('图层顺序：主水印在下层轨 → 副水印叠加在上层轨', objectName='tcChip')
        top_row.addWidget(self.layer_rule_chip)
        tl.addLayout(top_row)

        rule_hint = QLabel(
            '规则说明：同一位主播从第一个视频开头连续覆盖到最后一个视频结尾（中间不断开、不缩放）；'
            '表格「素材来源」读取每位主播第一行名字，名字为空自动跳过不挂载且绝不报错。'
        )
        rule_hint.setObjectName('muted')
        rule_hint.setWordWrap(True)
        tl.addWidget(rule_hint)
        root.addWidget(top_card)

        # ── 2. Middle Split: Left Settings + Right 9:16 Live Layer Preview ──
        mid = QHBoxLayout()
        mid.setSpacing(12)

        left_col = QVBoxLayout()
        left_col.setSpacing(10)

        # Card A: Base / Main Watermark
        main_card = QFrame(objectName='workspacePanel')
        ml = QVBoxLayout(main_card)
        ml.setContentsMargins(14, 10, 14, 10)
        ml.setSpacing(8)

        mh = QHBoxLayout()
        mh.setSpacing(8)
        self.main_enable_chk = QCheckBox('① 基础水印（主水印 · 位于下方空视频轨，被副水印覆盖）')
        self.main_enable_chk.setStyleSheet('font-size:13px; font-weight:750;')
        self.main_enable_chk.toggled.connect(self._on_any_setting_changed)
        mh.addWidget(self.main_enable_chk)
        mh.addStretch(1)
        self.main_info_lbl = QLabel('未选择 PNG', objectName='muted')
        mh.addWidget(self.main_info_lbl)
        ml.addLayout(mh)

        mp_row = QHBoxLayout()
        mp_row.setSpacing(8)
        self.main_path_edit = QLineEdit()
        self.main_path_edit.setPlaceholderText('选择基础主水印透明 PNG 文件（保持原始尺寸批量挂载）…')
        self.main_path_edit.textChanged.connect(self._on_any_setting_changed)
        mp_row.addWidget(self.main_path_edit, 1)
        self.pick_main_btn = self._btn('选择主水印 PNG…', 'l2blue', 32)
        self.pick_main_btn.clicked.connect(self._choose_main_png)
        mp_row.addWidget(self.pick_main_btn)
        self.clear_main_btn = self._btn('清空', 'l3', 32)
        self.clear_main_btn.clicked.connect(lambda: self.main_path_edit.setText(''))
        mp_row.addWidget(self.clear_main_btn)
        ml.addLayout(mp_row)
        left_col.addWidget(main_card)

        # Card B: Sub Watermark (Mode A + Mode B)
        sub_card = QFrame(objectName='workspacePanel')
        sl = QVBoxLayout(sub_card)
        sl.setContentsMargins(14, 10, 14, 10)
        sl.setSpacing(8)

        sh = QHBoxLayout()
        sh.setSpacing(8)
        sub_title = QLabel('② 副水印（上层轨 · 盖在主水印上方 · 关联主播「素材来源」）')
        sub_title.setStyleSheet('font-size:13px; font-weight:750;')
        sh.addWidget(sub_title)
        sh.addStretch(1)
        sh.addWidget(QLabel('全局模式：', objectName='pcGroupLabel'))
        self.sub_mode_combo = QComboBox()
        self.sub_mode_combo.setMinimumWidth(268)
        self.sub_mode_combo.addItem('智能混合（优先同名 PNG，无图转文字）', ai_watermark.SUB_MODE_HYBRID)
        self.sub_mode_combo.addItem('方式 A：PNG 透明图匹配（<素材来源>.png）', ai_watermark.SUB_MODE_IMAGE)
        self.sub_mode_combo.addItem('方式 B：文字自动生成透明水印', ai_watermark.SUB_MODE_TEXT)
        self.sub_mode_combo.currentIndexChanged.connect(self._on_any_setting_changed)
        sh.addWidget(self.sub_mode_combo)
        sl.addLayout(sh)

        # Mode A folder row
        dir_row = QHBoxLayout()
        dir_row.setSpacing(8)
        dir_lbl = QLabel('方式A 图片库：', objectName='pcGroupLabel')
        dir_row.addWidget(dir_lbl)
        self.sub_dir_edit = QLineEdit()
        self.sub_dir_edit.setPlaceholderText('选择存放 <素材来源名字>.png 透明副水印的文件夹…')
        self.sub_dir_edit.textChanged.connect(self._on_any_setting_changed)
        dir_row.addWidget(self.sub_dir_edit, 1)
        self.sub_dir_count_lbl = QLabel('0 张 PNG', objectName='tcChip')
        dir_row.addWidget(self.sub_dir_count_lbl)
        self.pick_sub_dir_btn = self._btn('选择文件夹…', 'l2', 30)
        self.pick_sub_dir_btn.clicked.connect(self._choose_sub_dir)
        dir_row.addWidget(self.pick_sub_dir_btn)
        sl.addLayout(dir_row)

        # Mode B text style rows
        t_row1 = QHBoxLayout()
        t_row1.setSpacing(8)
        t_row1.addWidget(QLabel('方式B 文字样式：', objectName='pcGroupLabel'))
        t_row1.addWidget(QLabel('位置'))
        self.pos_combo = QComboBox()
        for pkey, plabel in ai_watermark.POS_PRESETS:
            self.pos_combo.addItem(plabel, pkey)
        self.pos_combo.currentIndexChanged.connect(self._on_any_setting_changed)
        t_row1.addWidget(self.pos_combo)

        t_row1.addWidget(QLabel('字号'))
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(12, 140)
        self.font_size_spin.setValue(34)
        self.font_size_spin.valueChanged.connect(self._on_any_setting_changed)
        t_row1.addWidget(self.font_size_spin)

        t_row1.addWidget(QLabel('不透明度%'))
        self.opacity_spin = QSpinBox()
        self.opacity_spin.setRange(10, 100)
        self.opacity_spin.setValue(88)
        self.opacity_spin.valueChanged.connect(self._on_any_setting_changed)
        t_row1.addWidget(self.opacity_spin)

        self.bold_chk = QCheckBox('粗体')
        self.bold_chk.setChecked(True)
        self.bold_chk.toggled.connect(self._on_any_setting_changed)
        t_row1.addWidget(self.bold_chk)

        t_row1.addWidget(QLabel('前缀'))
        self.prefix_edit = QLineEdit()
        self.prefix_edit.setPlaceholderText('可选，如 @')
        self.prefix_edit.setMaximumWidth(96)
        self.prefix_edit.textChanged.connect(self._on_any_setting_changed)
        t_row1.addWidget(self.prefix_edit)
        t_row1.addStretch(1)
        sl.addLayout(t_row1)

        t_row2 = QHBoxLayout()
        t_row2.setSpacing(8)
        t_row2.addWidget(QLabel('颜色与边距：', objectName='pcGroupLabel'))
        self.text_color_btn = self._btn('文字 #FFFFFF', 'l3', 28)
        self.text_color_btn.clicked.connect(self._pick_text_color)
        t_row2.addWidget(self.text_color_btn)

        self.stroke_color_btn = self._btn('描边 #000000', 'l3', 28)
        self.stroke_color_btn.clicked.connect(self._pick_stroke_color)
        t_row2.addWidget(self.stroke_color_btn)

        t_row2.addWidget(QLabel('描边粗细'))
        self.stroke_spin = QSpinBox()
        self.stroke_spin.setRange(0, 16)
        self.stroke_spin.setValue(3)
        self.stroke_spin.valueChanged.connect(self._on_any_setting_changed)
        t_row2.addWidget(self.stroke_spin)

        t_row2.addWidget(QLabel('X 边距'))
        self.offset_x_spin = QSpinBox()
        self.offset_x_spin.setRange(0, 480)
        self.offset_x_spin.setValue(36)
        self.offset_x_spin.valueChanged.connect(self._on_any_setting_changed)
        t_row2.addWidget(self.offset_x_spin)

        t_row2.addWidget(QLabel('Y 边距'))
        self.offset_y_spin = QSpinBox()
        self.offset_y_spin.setRange(0, 960)
        self.offset_y_spin.setValue(96)
        self.offset_y_spin.valueChanged.connect(self._on_any_setting_changed)
        t_row2.addWidget(self.offset_y_spin)
        t_row2.addStretch(1)
        sl.addLayout(t_row2)

        left_col.addWidget(sub_card)
        mid.addLayout(left_col, 1)

        # Right Preview Panel
        prev_card = QFrame(objectName='workspacePanel')
        prev_card.setFixedWidth(214)
        pl = QVBoxLayout(prev_card)
        pl.setContentsMargins(14, 10, 14, 10)
        pl.setSpacing(6)
        self.preview_canvas = _WatermarkPreviewCanvas(prev_card)
        pl.addWidget(self.preview_canvas, 0, Qt.AlignHCenter)
        self.preview_host_lbl = QLabel('点击下方主播预览对应图层', objectName='muted')
        self.preview_host_lbl.setAlignment(Qt.AlignCenter)
        self.preview_host_lbl.setWordWrap(True)
        pl.addWidget(self.preview_host_lbl)
        mid.addWidget(prev_card)

        root.addLayout(mid)

        # ── 3. Host <-> Material Source Binding Table + Rescan Button ──
        host_card = QFrame(objectName='workspacePanel')
        hl = QVBoxLayout(host_card)
        hl.setContentsMargins(14, 10, 14, 10)
        hl.setSpacing(8)

        hbar = QHBoxLayout()
        hbar.setSpacing(8)
        htitle = QLabel(f'👤 当前日期主播副水印绑定（{self.day}）', objectName='workspaceTitle')
        hbar.addWidget(htitle)
        self.host_stats_chip = QLabel('共 0 位主播', objectName='tcChip')
        hbar.addWidget(self.host_stats_chip)
        hbar.addStretch(1)

        self.rescan_status_lbl = QLabel('', objectName='muted')
        hbar.addWidget(self.rescan_status_lbl)

        self.rescan_sheet_btn = self._btn(
            '↻ 重新识别表格素材来源',
            'l2blue',
            32,
            '重新读取 Google 表格「素材来源」列每位主播第一行名字；若有新增或修改，立即同步替换下方绑定名字',
        )
        self.rescan_sheet_btn.clicked.connect(self._start_rescan_sheet)
        hbar.addWidget(self.rescan_sheet_btn)
        hl.addLayout(hbar)

        self.host_table = QTableWidget(0, 4)
        self.host_table.setObjectName('promptTaskTable')
        self.host_table.setHorizontalHeaderLabels([
            '接收人 · AI主播',
            '绑定的素材来源名字（为空不挂载）',
            '单独指定方式 / 图片',
            '预计挂载效果',
        ])
        self.host_table.verticalHeader().setVisible(False)
        self.host_table.verticalHeader().setDefaultSectionSize(42)
        self.host_table.setMinimumHeight(184)
        self.host_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.host_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.host_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hh = self.host_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Interactive)
        hh.setSectionResizeMode(1, QHeaderView.Interactive)
        hh.setSectionResizeMode(2, QHeaderView.Interactive)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        self.host_table.setColumnWidth(0, 210)
        self.host_table.setColumnWidth(1, 220)
        self.host_table.setColumnWidth(2, 250)
        self.host_table.itemSelectionChanged.connect(self._update_preview)
        hl.addWidget(self.host_table, 1)
        root.addWidget(host_card, 1)

        # ── 4. Footer ──
        foot = QHBoxLayout()
        foot.setSpacing(10)
        foot_tip = QLabel('提示：若首次没识别到名字或后续修改了表格名字，点「↻ 重新识别表格素材来源」保存后，在剪辑页点「💧 刷新水印」即可直接替换旧水印。')
        foot_tip.setObjectName('muted')
        foot_tip.setWordWrap(True)
        foot.addWidget(foot_tip, 1)

        cancel_btn = self._btn('取消', 'l3', 36)
        cancel_btn.clicked.connect(self.reject)
        foot.addWidget(cancel_btn)

        self.save_btn = self._btn('保存水印设置', 'l1blue', 36)
        self.save_btn.setMinimumWidth(132)
        self.save_btn.clicked.connect(self._save_and_accept)
        foot.addWidget(self.save_btn)
        root.addLayout(foot)

    def _set_color_btn_value(self, btn: QPushButton, prefix: str, hex_col: str):
        col = hex_col.upper()
        btn.setProperty('hex_color', col)
        btn.setText(f'{prefix} {col}')

    def _load_from_config(self, cfg: dict):
        self._building = True
        norm = ai_watermark.normalize_config(cfg)
        self.enable_chk.setChecked(bool(norm['enabled']))
        self.main_enable_chk.setChecked(bool(norm['main_enabled']))
        self.main_path_edit.setText(norm['main_png_path'])
        idx = self.sub_mode_combo.findData(norm['sub_mode'])
        self.sub_mode_combo.setCurrentIndex(max(0, idx))
        self.sub_dir_edit.setText(norm['sub_png_dir'])

        st = norm['text_style']
        pidx = self.pos_combo.findData(st['pos_preset'])
        self.pos_combo.setCurrentIndex(max(0, pidx))
        self.font_size_spin.setValue(int(st['font_size']))
        self.opacity_spin.setValue(int(st['opacity_pct']))
        self.bold_chk.setChecked(bool(st['bold']))
        self.prefix_edit.setText(str(st['prefix'] or ''))
        self._set_color_btn_value(self.text_color_btn, '文字', st['text_color'])
        self._set_color_btn_value(self.stroke_color_btn, '描边', st['stroke_color'])
        self.stroke_spin.setValue(int(st['stroke_width']))
        self.offset_x_spin.setValue(int(st['offset_x']))
        self.offset_y_spin.setValue(int(st['offset_y']))
        self._building = False

    def current_config_dict(self) -> dict:
        return ai_watermark.normalize_config({
            'enabled': self.enable_chk.isChecked(),
            'main_enabled': self.main_enable_chk.isChecked(),
            'main_png_path': self.main_path_edit.text().strip(),
            'sub_mode': self.sub_mode_combo.currentData() or ai_watermark.SUB_MODE_HYBRID,
            'sub_png_dir': self.sub_dir_edit.text().strip(),
            'text_style': {
                'pos_preset': self.pos_combo.currentData() or 'bottom_right',
                'font_size': self.font_size_spin.value(),
                'opacity_pct': self.opacity_spin.value(),
                'bold': self.bold_chk.isChecked(),
                'prefix': self.prefix_edit.text(),
                'text_color': self.text_color_btn.property('hex_color') or '#FFFFFF',
                'stroke_color': self.stroke_color_btn.property('hex_color') or '#000000',
                'stroke_width': self.stroke_spin.value(),
                'offset_x': self.offset_x_spin.value(),
                'offset_y': self.offset_y_spin.value(),
            },
        })

    def _reload_hosts_table(self):
        self._hosts = ai_watermark.list_hosts_for_date(self.day)
        self._row_widgets.clear()
        self.host_table.setRowCount(len(self._hosts))

        override_choices = (
            ('跟随全局设置', ai_watermark.OVERRIDE_AUTO),
            ('指定单张 PNG…', ai_watermark.OVERRIDE_CUSTOM_PNG),
            ('强制方式A（图片匹配）', ai_watermark.OVERRIDE_IMAGE),
            ('强制方式B（文字生成）', ai_watermark.OVERRIDE_TEXT),
            ('不挂载水印', ai_watermark.OVERRIDE_NONE),
        )

        for r_idx, h in enumerate(self._hosts):
            hid = int(h['host_id'])
            host_label = f"{h['recipient_name']} · {h['host_name']} ({int(h.get('video_count') or 0)}条)"
            item0 = QTableWidgetItem(host_label)
            item0.setData(Qt.UserRole, hid)
            self.host_table.setItem(r_idx, 0, item0)

            # Col 1: inline QLineEdit for bound_name
            name_wrap = QWidget()
            nl = QHBoxLayout(name_wrap)
            nl.setContentsMargins(6, 3, 6, 3)
            nl.setSpacing(4)
            name_edit = QLineEdit(str(h.get('bound_name') or ''))
            name_edit.setPlaceholderText('为空自动跳过不挂载')
            name_edit.setStyleSheet('min-height:26px; max-height:28px; padding:2px 8px; font-size:12.5px;')
            name_edit.textChanged.connect(lambda _t='', row=r_idx: self._on_host_row_changed(row))
            nl.addWidget(name_edit)
            self.host_table.setCellWidget(r_idx, 1, name_wrap)

            # Col 2: override combo + custom PNG button
            mode_wrap = QWidget()
            ml = QHBoxLayout(mode_wrap)
            ml.setContentsMargins(6, 3, 6, 3)
            ml.setSpacing(4)
            mode_combo = QComboBox()
            mode_combo.setStyleSheet('min-height:26px; max-height:28px; padding:1px 8px; font-size:12px;')
            for clabel, cval in override_choices:
                mode_combo.addItem(clabel, cval)
            cur_ov = str(h.get('override_mode') or ai_watermark.OVERRIDE_AUTO)
            ov_i = mode_combo.findData(cur_ov)
            mode_combo.setCurrentIndex(max(0, ov_i))

            pick_btn = QPushButton('选图…', objectName='pcBtn')
            pick_btn.setProperty('tier', 'l3')
            pick_btn.setFixedHeight(26)
            pick_btn.setCursor(Qt.PointingHandCursor)
            custom_png = str(h.get('custom_png_path') or '')
            pick_btn.setProperty('custom_png_path', custom_png)
            if custom_png:
                pick_btn.setToolTip(custom_png)
                pick_btn.setText(Path(custom_png).name[:10])
            pick_btn.setVisible(cur_ov == ai_watermark.OVERRIDE_CUSTOM_PNG)

            mode_combo.currentIndexChanged.connect(lambda _idx=0, row=r_idx: self._on_host_override_changed(row))
            pick_btn.clicked.connect(lambda _=False, row=r_idx: self._choose_host_custom_png(row))
            ml.addWidget(mode_combo, 1)
            ml.addWidget(pick_btn)
            self.host_table.setCellWidget(r_idx, 2, mode_wrap)

            # Col 3: status badge label
            st_wrap = QWidget()
            sl = QHBoxLayout(st_wrap)
            sl.setContentsMargins(8, 4, 8, 4)
            st_lbl = QLabel('')
            sl.addWidget(st_lbl, 1)
            self.host_table.setCellWidget(r_idx, 3, st_wrap)

            self._row_widgets.append({
                'host_id': hid,
                'host_meta': h,
                'name_edit': name_edit,
                'mode_combo': mode_combo,
                'pick_btn': pick_btn,
                'status_lbl': st_lbl,
            })

        if self._hosts:
            self.host_table.selectRow(0)

    def _row_binding_dict(self, row: int) -> dict:
        w = self._row_widgets[row]
        return {
            'host_id': w['host_id'],
            'last_sheet_name': str(w['host_meta'].get('last_sheet_name') or ''),
            'bound_name': w['name_edit'].text().strip(),
            'override_mode': w['mode_combo'].currentData() or ai_watermark.OVERRIDE_AUTO,
            'custom_png_path': str(w['pick_btn'].property('custom_png_path') or '').strip(),
        }

    def _on_host_override_changed(self, row: int):
        if row < 0 or row >= len(self._row_widgets):
            return
        w = self._row_widgets[row]
        is_custom = (w['mode_combo'].currentData() == ai_watermark.OVERRIDE_CUSTOM_PNG)
        w['pick_btn'].setVisible(is_custom)
        if is_custom and not str(w['pick_btn'].property('custom_png_path') or '').strip():
            self._choose_host_custom_png(row)
        self._on_host_row_changed(row)

    def _choose_host_custom_png(self, row: int):
        if row < 0 or row >= len(self._row_widgets):
            return
        w = self._row_widgets[row]
        start_dir = self.sub_dir_edit.text().strip() or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, '选择该主播专属透明 PNG 副水印', start_dir, 'PNG 透明水印 (*.png *.PNG)')
        if path:
            w['pick_btn'].setProperty('custom_png_path', path)
            w['pick_btn'].setToolTip(path)
            w['pick_btn'].setText(Path(path).name[:12])
        self._on_host_row_changed(row)

    def _on_host_row_changed(self, row: int):
        if self._building:
            return
        self.host_table.selectRow(row)
        self._refresh_all_host_statuses()
        self._update_preview()

    def _choose_main_png(self):
        cur = self.main_path_edit.text().strip()
        start_dir = str(Path(cur).parent) if cur else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, '选择基础主水印 PNG', start_dir, 'PNG 透明水印 (*.png *.PNG)')
        if path:
            self.main_path_edit.setText(path)

    def _choose_sub_dir(self):
        cur = self.sub_dir_edit.text().strip() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, '选择副水印 PNG 文件夹（文件名对应素材来源名字）', cur)
        if folder:
            self.sub_dir_edit.setText(folder)

    def _pick_text_color(self):
        cur = QColor(self.text_color_btn.property('hex_color') or '#FFFFFF')
        chosen = QColorDialog.getColor(cur, self, '选择副水印文字颜色')
        if chosen.isValid():
            self._set_color_btn_value(self.text_color_btn, '文字', chosen.name(QColor.HexRgb))
            self._on_any_setting_changed()

    def _pick_stroke_color(self):
        cur = QColor(self.stroke_color_btn.property('hex_color') or '#000000')
        chosen = QColorDialog.getColor(cur, self, '选择副水印描边颜色')
        if chosen.isValid():
            self._set_color_btn_value(self.stroke_color_btn, '描边', chosen.name(QColor.HexRgb))
            self._on_any_setting_changed()

    def _load_qimage_cached(self, path_str: str) -> QImage | None:
        s = str(path_str or '').strip()
        if not s:
            return None
        p = Path(s).expanduser()
        if not p.is_file():
            return None
        try:
            key = f'{p.resolve()}|{p.stat().st_mtime_ns}'
        except OSError:
            return None
        if key not in self._image_cache:
            img = QImage(str(p))
            self._image_cache[key] = img
        img = self._image_cache[key]
        return img if not img.isNull() else None

    def _on_any_setting_changed(self):
        if self._building:
            return
        cfg = self.current_config_dict()

        # Update main PNG badge
        mp = cfg['main_png_path']
        if not cfg['main_enabled']:
            self.main_info_lbl.setText('已关闭主水印（仅挂载上层副水印）')
        elif mp and Path(mp).expanduser().is_file():
            mimg = self._load_qimage_cached(mp)
            if mimg is not None:
                self.main_info_lbl.setText(f'✓ 已就绪 {mimg.width()}×{mimg.height()} PNG')
            else:
                self.main_info_lbl.setText('⚠ PNG 无法读取')
        elif mp:
            self.main_info_lbl.setText('⚠ 文件不存在')
        else:
            self.main_info_lbl.setText('未选择主水印 PNG')

        # Update Mode A folder PNG count
        sdir = cfg['sub_png_dir']
        png_cnt = 0
        if sdir and Path(sdir).expanduser().is_dir():
            try:
                png_cnt = sum(
                    1 for f in Path(sdir).expanduser().iterdir()
                    if f.is_file() and not f.name.startswith('.') and f.suffix.lower() == '.png'
                )
            except OSError:
                png_cnt = 0
        self.sub_dir_count_lbl.setText(f'{png_cnt} 张 PNG')

        self._refresh_all_host_statuses()
        self._update_preview()

    def _refresh_all_host_statuses(self):
        from app.ui.sheet_rich_text import is_dark_theme

        dark = is_dark_theme(self)
        cfg = self.current_config_dict()
        active_cnt = 0
        empty_cnt = 0

        tone_styles = {
            'success': ('#163829', '#6EE7B7') if dark else ('#DCFCE7', '#15803D'),
            'info': ('#1E3A5F', '#93C5FD') if dark else ('#DBEAFE', '#1D4ED8'),
            'warning': ('#3D2F1A', '#FBBF24') if dark else ('#FEF3C7', '#B45309'),
            'muted': ('#252E3A', '#94A3B8') if dark else ('#F1F5F9', '#64748B'),
        }

        for r_idx in range(len(self._row_widgets)):
            bdict = self._row_binding_dict(r_idx)
            ev = ai_watermark.resolve_host_watermark_status(bdict, cfg)
            w = self._row_widgets[r_idx]
            prefix_icon = {'success': '🟢 ', 'info': '🔵 ', 'warning': '🟠 ', 'muted': '⚪ '}.get(ev['status_tone'], '')
            if not cfg['enabled'] and ev['active']:
                lbl_txt = f"⏸ 开启总开关后生效 · {ev['status_label']}"
                bg, fg = tone_styles['muted']
            else:
                lbl_txt = prefix_icon + ev['status_label']
                bg, fg = tone_styles.get(ev['status_tone'], tone_styles['muted'])
            w['status_lbl'].setText(lbl_txt)
            w['status_lbl'].setStyleSheet(
                f'background:{bg}; color:{fg}; border-radius:6px; padding:3px 8px; font-size:12px; font-weight:700;'
            )
            if ev['active']:
                active_cnt += 1
            elif ev['mode_used'] == 'empty_skip':
                empty_cnt += 1

        self.host_stats_chip.setText(
            f'共 {len(self._row_widgets)} 位主播 · 将挂载 {active_cnt} 位 · 空名跳过 {empty_cnt} 位'
        )

    def _selected_host_row(self) -> int:
        sel = self.host_table.selectionModel().selectedRows() if self.host_table.selectionModel() else []
        if sel:
            return sel[0].row()
        return 0 if self._row_widgets else -1

    def _update_preview(self):
        cfg = self.current_config_dict()
        main_img = self._load_qimage_cached(cfg['main_png_path']) if cfg['main_enabled'] else None

        row = self._selected_host_row()
        if 0 <= row < len(self._row_widgets):
            w = self._row_widgets[row]
            bdict = self._row_binding_dict(row)
            ev = ai_watermark.resolve_host_watermark_status(bdict, cfg)
            hmeta = w['host_meta']
            host_title = f"{hmeta['recipient_name']} · {hmeta['host_name']}"
            if not ev['active']:
                self.preview_canvas.set_layers(
                    enabled=cfg['enabled'],
                    host_active=False,
                    main_img=None,
                    sub_img=None,
                    badge_text='该主播不挂载水印',
                )
                self.preview_host_lbl.setText(f"{host_title}\n{ev['status_label']}")
                return

            sub_img = None
            if ev['sub_png']:
                sub_img = self._load_qimage_cached(ev['sub_png'])
            elif ev['text_to_render']:
                sub_img = ai_watermark.render_text_watermark_qimage(
                    ev['text_to_render'],
                    style=cfg['text_style'],
                    width=720,
                    height=1280,
                )
            badge = '总开关未开启（预览）' if not cfg['enabled'] else ('V2 主水印 + V3 副水印' if main_img else '上层副水印')
            self.preview_canvas.set_layers(
                enabled=True,
                host_active=True,
                main_img=main_img,
                sub_img=sub_img,
                badge_text=badge,
            )
            self.preview_host_lbl.setText(f"{host_title}\n{ev['status_label']}")
        else:
            # Sample preview when current date has no imported hosts yet
            sample_name = f"{cfg['text_style']['prefix']}示例素材来源"
            sub_img = None
            if cfg['sub_mode'] in (ai_watermark.SUB_MODE_TEXT, ai_watermark.SUB_MODE_HYBRID):
                sub_img = ai_watermark.render_text_watermark_qimage(
                    sample_name,
                    style=cfg['text_style'],
                    width=720,
                    height=1280,
                )
            self.preview_canvas.set_layers(
                enabled=True,
                host_active=True,
                main_img=main_img,
                sub_img=sub_img,
                badge_text='示例图层叠加预览',
            )
            self.preview_host_lbl.setText('当前日期暂无已导入主播\n导入任务后将自动绑定每位主播')

    def _start_rescan_sheet(self):
        if self._rescan_worker is not None and self._rescan_worker.isRunning():
            return
        # Persist current override_mode/custom_png_path & current edits first so rescan compares accurately
        current_entries = [self._row_binding_dict(i) for i in range(len(self._row_widgets))]
        if current_entries:
            ai_watermark.save_host_bindings_bulk(current_entries)

        self.rescan_sheet_btn.setEnabled(False)
        self.rescan_sheet_btn.setText('⟳ 正在读取表格素材来源…')
        self.rescan_status_lbl.setText('正在连接 Google 表格读取最新「素材来源」列…')

        worker = _RescanSheetWorker(self.day, self)
        worker.finished_result.connect(self._on_rescan_finished)
        self._rescan_worker = worker
        worker.start()

    def _on_rescan_finished(self, result: dict | None, error: str):
        self.rescan_sheet_btn.setEnabled(True)
        self.rescan_sheet_btn.setText('↻ 重新识别表格素材来源')

        if error or not result:
            self.rescan_status_lbl.setText('⚠ 重新识别失败')
            from app.ui.resolve_error_dialog import show_editing_warning
            show_editing_warning(self, '重新识别素材来源', f'读取表格失败：{error or "未知错误"}')
            return

        # Reload fresh host bindings into the table immediately so any modified sheet names replace old ones on screen!
        changed_ids = {int(c['host_id']) for c in (result.get('changes') or [])}
        self._building = True
        self._reload_hosts_table()
        if changed_ids:
            for r_idx, w in enumerate(self._row_widgets):
                if w['host_id'] in changed_ids:
                    self.host_table.selectRow(r_idx)
                    break
        self._building = False
        self._refresh_all_host_statuses()
        self._update_preview()

        msg = str(result.get('message') or '重新识别完成。')
        self.rescan_status_lbl.setText('✓ ' + msg)

        changes = result.get('changes') or []
        if changes:
            lines = []
            for ch in changes[:12]:
                old_disp = f"「{ch['old']}」" if ch['old'] else '（空）'
                new_disp = f"「{ch['new']}」" if ch['new'] else '（空·不挂载）'
                lines.append(f"• {ch['host_label']}：{old_disp} → {new_disp}")
            if len(changes) > 12:
                lines.append(f'… 等共 {len(changes)} 位主播已同步更新')
            detail_body = '\n'.join(lines)
            QMessageBox.information(
                self,
                '重新识别表格素材来源',
                f"{msg}\n\n已立即同步更新主播绑定：\n{detail_body}\n\n"
                "提示：点击右下角「保存水印设置」后，若该批次已在达芬奇中，直接点击剪辑页「💧 刷新水印」即可把时间线上的旧水印替换为新水印！",
            )
        else:
            QMessageBox.information(self, '重新识别表格素材来源', msg)

    def _save_and_accept(self):
        cfg = self.current_config_dict()
        ai_watermark.save_config(cfg)
        entries = [self._row_binding_dict(i) for i in range(len(self._row_widgets))]
        if entries:
            ai_watermark.save_host_bindings_bulk(entries)
        self.accept()
