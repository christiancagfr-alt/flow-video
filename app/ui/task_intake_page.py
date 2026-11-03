from __future__ import annotations

from pathlib import Path
from app.services import quiet_process as subprocess

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl, QSize, QRect
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QPlainTextEdit,
    QDialog, QDialogButtonBox, QProgressBar, QFileDialog, QCheckBox, QSpinBox,
    QScrollArea, QGridLayout, QSizePolicy, QSplitter, QComboBox, QListWidget, QListWidgetItem,
    QMenu, QStackedWidget
)
from PySide6.QtGui import QPixmap, QDesktopServices, QIcon
from app.ui.image_preview import set_image, set_image_async

from app.core import repository as repo
from app.ui import workspace_intake
from app.core import work_dates
from app.services import pre_gpt_pipeline as intake
from app.services.file_filters import is_valid_local_image
from app.services.material_assignment import material_folder
from app.ui.modern_widgets import ClickableFrame


class _HostCard(ClickableFrame):
    """Host card: single click selects, double click opens the manager."""
    doubleClicked = Signal()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)


def _group_state(g):
    """Return (short label, tone) for a host group status. tone: good / warn / bad / info."""
    st = str(g.get("status") or "")
    if st == "READY_FOR_GPT":
        return "✓ 已就绪", "good"
    if st == "NEEDS_MANUAL_CLASSIFY":
        return "待确认闭眼图", "warn"
    if st == "MATERIAL_SHORTAGE":
        return "缺少图片", "bad"
    if st in ("DRIVE_LINK_CONFLICT", "MATERIAL_LINK_MISSING"):
        return "素材链接异常", "bad"
    msg = str(g.get("message") or "").strip()
    return ((msg[:12] + "…") if len(msg) > 12 else msg) or "准备中", "info"


class IntakeWorker(QThread):
    finished_data = Signal(object)
    failed = Signal(str)
    progress_changed = Signal(int, str, str)

    def __init__(self, action: str, group_key: str = "", parent=None, payload=None):
        super().__init__(parent)
        self.action = action
        self.group_key = group_key
        self.payload = payload or {}

    def _emit_progress(self, percent, stage, detail=""):
        try:
            self.progress_changed.emit(max(0, min(100, int(percent))), str(stage or ""), str(detail or ""))
        except Exception:
            pass

    def run(self):
        try:
            if self.action in ("sync_all", "sync_auto"):
                data = intake.sync_download_and_prepare_all(progress_callback=self._emit_progress)
            elif self.action == "download":
                data = intake.download_drive_group(self.group_key, progress_callback=self._emit_progress)
                data["promote"] = intake.promote_ready_to_studio(group_key=self.group_key)
            elif self.action == "rescan_local":
                from app.services.local_host_materials import rescan
                data = rescan(self.group_key, self.payload['day'], self._emit_progress, random_fill=self.payload.get("random_fill", False))
            elif self.action == "delete_host":
                import importlib
                import app.services.delete_selected_host as _dsh
                importlib.reload(_dsh)
                data = _dsh.execute(self.payload)
            elif self.action == "connect_google":
                intake.google_creds(interactive=True)
                data = {"connected": intake.TOKEN_FILE.exists()}
            elif self.action == "switch_google":
                intake.disconnect_google()
                intake.google_creds(interactive=True, force_account_picker=True)
                data = {"connected": intake.TOKEN_FILE.exists()}
            else:
                raise ValueError("未知任务中心操作")
            self.finished_data.emit(data)
        except Exception as exc:
            self.failed.emit(str(exc))


class _ImageTileCard(QFrame):
    """9:16 clickable image tile with checkbox and filename underneath."""
    toggled = Signal(bool)

    TILE_W = 180
    TILE_H = 320  # Exact 9:16 ratio (180 x 320)

    def __init__(self, path: Path, checked: bool = False, parent=None):
        super().__init__(parent)
        self.path_str = str(path)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedWidth(self.TILE_W + 16)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        self.thumb = QLabel(self)
        self.thumb.setFixedSize(self.TILE_W, self.TILE_H)
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setStyleSheet("background:#11161F;border-radius:6px;")
        self._load_pixmap(path)
        lay.addWidget(self.thumb, 0, Qt.AlignHCenter)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(2, 0, 2, 0)
        bottom.setSpacing(6)
        self.checkbox = QCheckBox(self)
        self.checkbox.setChecked(bool(checked))
        self.checkbox.toggled.connect(self._on_toggled)
        bottom.addWidget(self.checkbox, 0)

        self.name_label = QLabel(path.name, self)
        self.name_label.setToolTip(path.name)
        self.name_label.setStyleSheet("font-size:12px;font-weight:600;background:transparent;border:none;")
        fm = self.name_label.fontMetrics()
        self.name_label.setText(fm.elidedText(path.name, Qt.ElideMiddle, self.TILE_W - 26))
        bottom.addWidget(self.name_label, 1)
        lay.addLayout(bottom)

        self._apply_style(bool(checked))

    def _load_pixmap(self, path: Path):
        set_image(self.thumb, path, QSize(self.TILE_W, self.TILE_H))

    def _on_toggled(self, checked: bool):
        self._apply_style(checked)
        self.toggled.emit(checked)

    def _apply_style(self, checked: bool):
        if checked:
            self.setStyleSheet(
                "_ImageTileCard{background:rgba(47,111,237,0.14);border:2px solid #2F6FED;border-radius:10px;}"
            )
        else:
            self.setStyleSheet(
                "_ImageTileCard{background:rgba(128,128,128,0.06);border:1px solid rgba(128,128,128,0.25);border-radius:10px;}"
                "_ImageTileCard:hover{border:1px solid #2F6FED;}"
            )

    def isChecked(self) -> bool:
        return self.checkbox.isChecked()

    def setChecked(self, checked: bool):
        self.checkbox.setChecked(bool(checked))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            child = self.childAt(event.pos())
            if child is not self.checkbox:
                self.checkbox.setChecked(not self.checkbox.isChecked())
                event.accept()
                return
        super().mousePressEvent(event)


class ManualClassifyDialog(QDialog):
    """Tiled 9:16 confirmation dialog for mixed TALKING/PRAYING material."""
    completed = Signal(str)

    def __init__(self, group: dict, parent=None):
        super().__init__(parent)
        self.group = group
        self.group_key = group["group_key"]
        self.required = int(group.get("praying") or 0)
        self.selected = []
        self._tiles: list[_ImageTileCard] = []
        self._last_cols = 0
        self._confirmed_keys: list[str] = []
        self.setWindowTitle("图片睁眼 / 闭眼确认")
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.resize(1080, 780)
        self.setMinimumSize(720, 520)

        root = QVBoxLayout(self)
        self.title_label = QLabel(f'{group.get("anchor_name", "主播")} · 闭眼素材确认')
        self.title_label.setStyleSheet("font-size:20px;font-weight:800;")
        root.addWidget(self.title_label)
        self.tip = QLabel(
            f'一共有 {self.required} 张闭眼图片 · 直接点击图片即可勾选/取消（勾选=闭眼，未勾选=睁眼）；不会改动图片文件。'
        )
        self.tip.setWordWrap(True)
        root.addWidget(self.tip)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.grid_host = QWidget(self.scroll)
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(6, 6, 6, 6)
        self.grid.setHorizontalSpacing(12)
        self.grid.setVerticalSpacing(12)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.scroll.setWidget(self.grid_host)
        root.addWidget(self.scroll, 1)

        self.counter = QLabel(f"一共有 {self.required} 张闭眼图片 · 已选中：0/{self.required}")
        self.counter.setStyleSheet("font-size:17px;font-weight:800;")
        root.addWidget(self.counter)
        self.note = QLabel("", objectName="muted")
        self.note.setWordWrap(True)
        root.addWidget(self.note)

        row = QHBoxLayout()
        open_btn = QPushButton("打开图片文件夹")
        open_btn.clicked.connect(self.open_finder)
        row.addWidget(open_btn)
        refresh_btn = QPushButton("刷新图片")
        refresh_btn.clicked.connect(lambda: self.refresh_selection(True))
        row.addWidget(refresh_btn)
        select_all_btn = QPushButton("全选闭眼")
        select_all_btn.clicked.connect(lambda: self._set_all_checked(True))
        row.addWidget(select_all_btn)
        clear_all_btn = QPushButton("全部取消")
        clear_all_btn.clicked.connect(lambda: self._set_all_checked(False))
        row.addWidget(clear_all_btn)
        row.addStretch(1)
        self.confirm_btn = QPushButton("确认并继续", objectName="primaryBtn")
        self.confirm_btn.setEnabled(True)
        self.confirm_btn.clicked.connect(self.confirm)
        row.addWidget(self.confirm_btn)
        root.addLayout(row)

        cancel = QDialogButtonBox(QDialogButtonBox.Close)
        cancel.rejected.connect(self.reject)
        root.addWidget(cancel)
        QTimer.singleShot(0, self.refresh_selection)

    def load_group(self, group: dict):
        self.group = group
        self.group_key = group["group_key"]
        self.required = int(group.get("praying") or 0)
        self.title_label.setText(f'{group.get("anchor_name", "主播")} · 闭眼素材确认')
        self.scroll.verticalScrollBar().setValue(0)
        self.refresh_selection(keep_previous=False)

    def _set_all_checked(self, checked: bool):
        for tile in self._tiles:
            tile.setChecked(checked)
        self._update_counter()

    def _update_counter(self):
        total = len(self._tiles)
        closed = sum(1 for t in self._tiles if t.isChecked())
        target = self.required if self.required > 0 else total
        self.tip.setText(
            f'一共有 {self.required} 张闭眼图片 · 直接点击图片即可勾选/取消（勾选=闭眼，未勾选=睁眼）；不会改动图片文件。'
        )
        self.counter.setText(
            f'一共有 {self.required} 张闭眼图片   ·   已选中：{closed}/{target}   （共 {total} 张图片）'
        )

    def _relayout_tiles(self, force: bool = False):
        if not self._tiles:
            return
        viewport_w = max(1, self.scroll.viewport().width())
        tile_step = _ImageTileCard.TILE_W + 16 + self.grid.horizontalSpacing()
        cols = max(1, (viewport_w - 12) // tile_step)
        if not force and cols == self._last_cols:
            return
        self._last_cols = cols
        while self.grid.count():
            self.grid.takeAt(0)
        for idx, tile in enumerate(self._tiles):
            self.grid.addWidget(tile, idx // cols, idx % cols)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        t = getattr(self, "_relayout_timer", None)
        if t is None:
            t = QTimer(self)
            t.setSingleShot(True)
            t.timeout.connect(self._relayout_tiles)
            self._relayout_timer = t
        if not t.isActive():
            t.start(35)

    def open_finder(self):
        try:
            intake.finder_open(self.group_key)
            self.note.setText("图片文件夹已打开。也可以直接在本窗口点击图片勾选闭眼，无需重命名。")
        except Exception as exc:
            self.note.setText(str(exc))

    def refresh_selection(self, keep_previous: bool = True):
        try:
            files = intake.scan_named_materials(self.group_key)
            previous = {t.path_str: t.isChecked() for t in self._tiles} if keep_previous else {}
            self.grid_host.setUpdatesEnabled(False)
            try:
                while self.grid.count():
                    item = self.grid.takeAt(0)
                    w = item.widget()
                    if w:
                        w.deleteLater()
                self._tiles.clear()
                self._last_cols = 0
                from app.services.material_assignment import image_mode, manual_modes
                con = intake.init_db()
                try:
                    manual = manual_modes(con)
                    row = con.execute(
                        "SELECT COUNT(*) FROM tasks WHERE group_key=? AND sheet_row>0 AND mode='PRAYING'",
                        (self.group_key,),
                    ).fetchone()
                    if row is not None and int(row[0] or 0) > 0 and not self.required:
                        self.required = int(row[0])
                finally:
                    con.close()
                for path in files:
                    checked = previous.get(str(path), image_mode(path, manual=manual) == 'PRAYING')
                    tile = _ImageTileCard(path, checked=checked, parent=self.grid_host)
                    tile.toggled.connect(lambda _c: self._update_counter())
                    self._tiles.append(tile)
                self._relayout_tiles(force=True)
            finally:
                self.grid_host.setUpdatesEnabled(True)
            self._update_counter()
            self.note.setText('请直接点击 9:16 缩略图勾选闭眼图片，确认无误后点击“确认并继续”。')
        except Exception as exc:
            self.note.setText(str(exc))

    def _promote_group_safe(self, group_key: str):
        try:
            intake.promote_ready_to_studio(group_key=group_key)
        except Exception:
            pass

    def confirm(self):
        try:
            selected_paths = [t.path_str for t in self._tiles if t.isChecked()]
            finished_key = self.group_key
            result = intake.confirm_named_materials(finished_key, selected_paths)
            self._confirmed_keys.append(finished_key)
            next_group = next(
                (
                    g for g in intake.list_groups()
                    if g.get("status") == "NEEDS_MANUAL_CLASSIFY" and g.get("group_key") != finished_key
                ),
                None,
            )
            if next_group is not None:
                self.load_group(next_group)
                self.note.setText(f'上一个主播已确认；当前请继续确认“{next_group.get("anchor_name", "主播")}”。')
                QTimer.singleShot(10, lambda k=finished_key: self._promote_group_safe(k))
                return
            intake.promote_ready_to_studio(group_key=finished_key)
            self.note.setText(result['message'])
            self.completed.emit(finished_key)
            self.accept()
        except Exception as exc:
            QMessageBox.warning(self, '素材确认', str(exc))

    def reject(self):
        if self._confirmed_keys:
            self.completed.emit(self._confirmed_keys[-1])
        super().reject()


class TaskIntakePage(QWidget):
    """Integrated Task Center: Sheet -> Drive -> classification -> READY FOR GPT."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.worker = None
        self.manual_dialog = None
        self.selected_recipient = ""
        self.selected_group_key = ""
        self._build()
        self.auto_timer = QTimer(self)
        self.auto_timer.timeout.connect(self.auto_sync_tick)
        self._apply_auto_timer()
        self.refresh()

    @staticmethod
    def _set_prop(widget, name, value):
        """Update a dynamic style property and re-polish so the stylesheet takes effect."""
        widget.setProperty(name, value)
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0,0,0,0)
        outer.setSpacing(0)
        self.page_scroll = QScrollArea(objectName="pageScroll")
        self.page_scroll.setWidgetResizable(True)
        self.page_scroll.setFrameShape(QFrame.NoFrame)
        self.page_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.page_content = QWidget(objectName="pageScrollContent")
        self.page_content.setMinimumWidth(820)
        root = QVBoxLayout(self.page_content)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(12)
        self.page_scroll.setWidget(self.page_content)
        outer.addWidget(self.page_scroll)

        # ── 1. Header: title on the left; Google state + the only daily actions on the right.
        top = QHBoxLayout(); top.setSpacing(10)
        titles = QVBoxLayout(); titles.setSpacing(2)
        titles.addWidget(QLabel("任务中心", objectName="pageTitle"))
        self.date_hint = QLabel("", objectName="pageSubtitle")
        titles.addWidget(self.date_hint)
        top.addLayout(titles); top.addStretch(1)
        self.google_state = QLabel("Google：检测中…", objectName="tcChip")
        top.addWidget(self.google_state, 0, Qt.AlignVCenter)
        self.sync_btn = QPushButton("⟳  同步任务", objectName="primaryBtn")
        self.sync_btn.setMinimumWidth(116)
        self.sync_btn.setToolTip("从 Google 表格读取当天任务，并下载、整理主播素材")
        self.sync_btn.clicked.connect(self.sync_all)
        top.addWidget(self.sync_btn, 0, Qt.AlignVCenter)
        self.manual_task_btn = QPushButton("✎ 手动填写任务")
        self.manual_task_btn.setMinimumWidth(124)
        self.manual_task_btn.setToolTip("无需连接 Google 表格，直接本地填表或批量粘贴添加任务")
        self.manual_task_btn.clicked.connect(self.open_manual_task_dialog)
        top.addWidget(self.manual_task_btn, 0, Qt.AlignVCenter)
        self.rescan_source_btn = QPushButton("↻ 重读素材来源")
        self.rescan_source_btn.setToolTip("单独重新读取 Google 表格「素材来源」列；若有新增或名字修改，立即同步替换主播卡片绑定的副水印名字")
        self.rescan_source_btn.clicked.connect(self.rescan_material_sources)
        top.addWidget(self.rescan_source_btn, 0, Qt.AlignVCenter)
        # Destructive actions are tucked into a menu so they are never mis-clicked.
        self.more_btn = QPushButton("更多")
        self.more_btn.setToolTip("清空任务等低频操作")
        more_menu = QMenu(self.more_btn)
        more_menu.addAction("清空当前任务", lambda: self.clear_tasks(False))
        more_menu.addAction("清空并重新同步", lambda: self.clear_tasks(True))
        self.more_btn.setMenu(more_menu)
        top.addWidget(self.more_btn, 0, Qt.AlignVCenter)
        root.addLayout(top)

        # ── 2. Guide bar: 3-step flow indicator + live metrics + a one-line "what to do next".
        guide = QFrame(objectName="tcGuide")
        gv = QVBoxLayout(guide); gv.setContentsMargins(16,12,16,12); gv.setSpacing(8)
        steps_row = QHBoxLayout(); steps_row.setSpacing(8)
        self.step_labels = []
        for idx, text in enumerate(("① 同步任务", "② 确认素材", "③ 管理文案 / 图片")):
            if idx:
                steps_row.addWidget(QLabel("›", objectName="tcArrow"))
            lab = QLabel(text, objectName="tcStep"); lab.setProperty("state", "todo")
            self.step_labels.append(lab); steps_row.addWidget(lab)
        steps_row.addStretch(1)
        self.metric_chips = {}
        for key in ("recipients", "hosts", "scripts", "ready", "pending"):
            chip = QLabel("", objectName="tcStatChip"); chip.setProperty("tone", "")
            self.metric_chips[key] = chip; steps_row.addWidget(chip)
        gv.addLayout(steps_row)
        self.guide_hint = QLabel("", objectName="tcGuideHint"); self.guide_hint.setWordWrap(True)
        gv.addWidget(self.guide_hint)
        root.addWidget(guide)
        # Backwards-compatible handle; the metrics now live in the chips above.
        self.summary = QLabel(); self.summary.hide()

        # ── 3. Sync progress: only visible while a sync/scan is running (or just failed).
        self.progress_box = QFrame(objectName="topStrip")
        pv = QVBoxLayout(self.progress_box); pv.setContentsMargins(14,10,14,10); pv.setSpacing(6)
        phr = QHBoxLayout()
        self.progress_label = QLabel("同步进度 · 就绪", objectName="cardTitle")
        self.progress_percent = QLabel("0%", objectName="compactMetric")
        phr.addWidget(self.progress_label); phr.addStretch(1); phr.addWidget(self.progress_percent)
        pv.addLayout(phr)
        self.progress = QProgressBar(); self.progress.setRange(0,100); self.progress.setValue(0); self.progress.setTextVisible(False); self.progress.setFixedHeight(6); pv.addWidget(self.progress)
        self.progress_detail = QLabel("等待同步任务", objectName="muted"); self.progress_detail.setWordWrap(True); pv.addWidget(self.progress_detail)
        self.progress_box.hide()
        root.addWidget(self.progress_box)
        self._progress_hide_timer = QTimer(self); self._progress_hide_timer.setSingleShot(True)
        self._progress_hide_timer.timeout.connect(self.progress_box.hide)

        # ── 4. Recipients: a slim horizontal row, hidden entirely when there is nothing to show.
        self.recipient_section = QWidget()
        rs = QVBoxLayout(self.recipient_section); rs.setContentsMargins(0,0,0,0); rs.setSpacing(6)
        rs.addWidget(QLabel("接收人", objectName="tcSection"))
        self.recipient_scroll=QScrollArea(objectName="cardScroll"); self.recipient_scroll.setWidgetResizable(True); self.recipient_scroll.setFrameShape(QFrame.NoFrame); self.recipient_scroll.setFixedHeight(70); self.recipient_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded); self.recipient_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.recipient_content=QWidget(objectName="scrollContent"); self.recipient_cards=QHBoxLayout(self.recipient_content); self.recipient_cards.setContentsMargins(0,0,0,4); self.recipient_cards.setSpacing(10); self.recipient_cards.setAlignment(Qt.AlignLeft|Qt.AlignTop); self.recipient_scroll.setWidget(self.recipient_content)
        rs.addWidget(self.recipient_scroll)
        self.recipient_section.hide()
        root.addWidget(self.recipient_section)

        # ── 5. Main area: empty-state guide OR host workspace + detail panel.
        self.body_stack = QStackedWidget()
        self.body_stack.addWidget(self._build_empty_state())

        body=QSplitter(Qt.Horizontal); body.setChildrenCollapsible(False); body.setHandleWidth(10)
        hosts_wrap=QFrame(objectName="pageCard"); hv=QVBoxLayout(hosts_wrap); hv.setContentsMargins(16,14,16,14); hv.setSpacing(10)
        hh = QHBoxLayout()
        self.hosts_title=QLabel("AI 主播",objectName="tcSection"); hh.addWidget(self.hosts_title); hh.addStretch(1)
        hh.addWidget(QLabel("单击选中 · 双击打开管理", objectName="tcHint"))
        hv.addLayout(hh)
        self.host_scroll=QScrollArea(objectName="cardScroll"); self.host_scroll.setWidgetResizable(True); self.host_scroll.setFrameShape(QFrame.NoFrame); self.host_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.host_content=QWidget(objectName="scrollContent"); self.host_grid=QGridLayout(self.host_content); self.host_grid.setContentsMargins(0,0,0,0); self.host_grid.setHorizontalSpacing(12); self.host_grid.setVerticalSpacing(12); self.host_grid.setAlignment(Qt.AlignTop|Qt.AlignLeft); self.host_scroll.setWidget(self.host_content); hv.addWidget(self.host_scroll,1)
        body.addWidget(hosts_wrap)
        body.addWidget(self._build_detail_panel())
        body.setStretchFactor(0, 1); body.setStretchFactor(1, 0); body.setSizes([840, 360])
        self.body_stack.addWidget(body)
        self.body_stack.setMinimumHeight(440)
        root.addWidget(self.body_stack, 1)
        self._host_cards = []
        self._host_cols = 0

        # ── 6. Footer: last action result (one line, muted).
        self._connect_google_btn=QPushButton(); self._switch_google_btn=QPushButton()
        self.status=QLabel("就绪",objectName="tcHint"); self.status.setWordWrap(True); root.addWidget(self.status)
        self.log=QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumBlockCount(2500); self.log.hide(); root.addWidget(self.log)

    def _build_empty_state(self):
        wrap = QFrame(objectName="tcEmpty")
        v = QVBoxLayout(wrap); v.setContentsMargins(40,40,40,40); v.setSpacing(10); v.setAlignment(Qt.AlignCenter)
        icon = QLabel("🗂", objectName="tcEmptyIcon"); icon.setAlignment(Qt.AlignCenter); v.addWidget(icon)
        self.empty_title = QLabel("今天还没有任务", objectName="tcEmptyTitle"); self.empty_title.setAlignment(Qt.AlignCenter); v.addWidget(self.empty_title)
        self.empty_text = QLabel("", objectName="muted"); self.empty_text.setAlignment(Qt.AlignCenter); self.empty_text.setWordWrap(True); self.empty_text.setFixedWidth(560)
        self.empty_text.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        v.addWidget(self.empty_text, 0, Qt.AlignHCenter)
        v.addSpacing(6)
        btn_row = QHBoxLayout(); btn_row.setSpacing(10); btn_row.addStretch(1)
        self.empty_sync_btn = QPushButton("⟳  立即同步任务", objectName="primaryBtn"); self.empty_sync_btn.setMinimumWidth(150)
        self.empty_sync_btn.clicked.connect(self.sync_all); btn_row.addWidget(self.empty_sync_btn)
        self.empty_manual_btn = QPushButton("✎  手动填写任务"); self.empty_manual_btn.setMinimumWidth(150)
        self.empty_manual_btn.clicked.connect(self.open_manual_task_dialog); btn_row.addWidget(self.empty_manual_btn)
        self.available_dates = QComboBox(); self.available_dates.setMinimumWidth(130); btn_row.addWidget(self.available_dates)
        self.show_date_btn = QPushButton("查看该日期任务"); self.show_date_btn.clicked.connect(self.show_available_date); btn_row.addWidget(self.show_date_btn)
        btn_row.addStretch(1)
        v.addLayout(btn_row)
        v.addSpacing(14)
        tips = QLabel(
            "使用流程：① 点击「同步任务」读取 Google 表格，或点击「手动填写任务」本地填表/粘贴　"
            "② 有闭眼图片需要确认时会自动提示　③ 准备完成后在右侧管理文案和图片",
            objectName="tcHint")
        tips.setAlignment(Qt.AlignCenter); tips.setWordWrap(True)
        v.addWidget(tips)
        return wrap

    def _build_detail_panel(self):
        detail=QFrame(objectName="detailPanel")
        dv=QVBoxLayout(detail); dv.setContentsMargins(16,14,16,14); dv.setSpacing(8)
        head = QHBoxLayout(); head.setSpacing(8)
        self.detail_title=QLabel("选择一个主播",objectName="tcSection"); self.detail_title.setMinimumWidth(1); self.detail_title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred); head.addWidget(self.detail_title, 1)
        self.detail_status=QLabel("",objectName="tcChip"); self.detail_status.setProperty("tone", ""); head.addWidget(self.detail_status, 0, Qt.AlignTop)
        dv.addLayout(head)
        self.detail_preview=QLabel("暂无素材",objectName="thumb"); self.detail_preview.setAlignment(Qt.AlignCenter); self.detail_preview.setFixedHeight(124); dv.addWidget(self.detail_preview)
        self.detail_meta=QLabel("点击左侧主播卡片查看任务与素材情况。",objectName="cardMeta"); self.detail_meta.setWordWrap(True); dv.addWidget(self.detail_meta)
        self.detail_counts=QLabel("",objectName="tcHint"); self.detail_counts.setWordWrap(False); self.detail_counts.setMinimumWidth(1); self.detail_counts.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred); dv.addWidget(self.detail_counts)
        self.manage_hint=QLabel("",objectName="tcTip"); self.manage_hint.setWordWrap(True); dv.addWidget(self.manage_hint)
        self.manage_btn=QPushButton("管理文案 / 图片",objectName="primaryBtn"); self.manage_btn.setMinimumHeight(38)
        self.manage_btn.clicked.connect(self._primary_action); dv.addWidget(self.manage_btn)

        dv.addSpacing(4)
        line = QFrame(objectName="tcDivider"); line.setFrameShape(QFrame.NoFrame); dv.addWidget(line)
        dv.addWidget(QLabel("素材工具", objectName="tcHint"))
        tools = QGridLayout(); tools.setHorizontalSpacing(8); tools.setVerticalSpacing(8)
        self.download_btn=QPushButton("⇣ 同步素材"); self.download_btn.setToolTip("重新从 Google Drive 下载该主播的素材"); self.download_btn.clicked.connect(self.download_selected)
        self.open_folder_btn=QPushButton("📂 打开文件夹"); self.open_folder_btn.setToolTip("在访达中打开该主播的本地素材目录"); self.open_folder_btn.clicked.connect(self.open_selected_folder)
        self.rescan_btn=QPushButton("⟲ 重新扫描"); self.rescan_btn.setToolTip("你手动增删了本地图片后，点这里重新识别"); self.rescan_btn.clicked.connect(self.rescan_selected)
        self.fill_btn=QPushButton("🎲 随机补齐缺图"); self.fill_btn.setToolTip("图片数量不够时，从已有图片中随机补齐"); self.fill_btn.clicked.connect(lambda: self.rescan_selected(random_fill=True))
        self.manual_btn=QPushButton("👁 调整睁眼 / 闭眼"); self.manual_btn.clicked.connect(self.open_manual_for_selected)
        for i, b in enumerate((self.download_btn, self.open_folder_btn, self.rescan_btn, self.fill_btn)):
            b.setObjectName("tcTool"); tools.addWidget(b, i // 2, i % 2)
        self.manual_btn.setObjectName("tcTool"); tools.addWidget(self.manual_btn, 2, 0, 1, 2)
        dv.addLayout(tools)
        dv.addStretch(1)
        self.delete_host_btn=QPushButton("删除该主播", objectName="dangerBtn")
        self.delete_host_btn.setToolTip("删除该主播今天的任务及全部后续生产数据（会二次确认）")
        self.delete_host_btn.clicked.connect(self.delete_selected_host); dv.addWidget(self.delete_host_btn)
        # The panel scrolls on its own when the window is short, so the page itself stays put.
        panel_scroll = QScrollArea(objectName="cardScroll")
        panel_scroll.setWidgetResizable(True); panel_scroll.setFrameShape(QFrame.NoFrame)
        panel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        panel_scroll.setMinimumWidth(330); panel_scroll.setMaximumWidth(440)
        panel_scroll.setWidget(detail)
        return panel_scroll

    def _primary_action(self):
        g = self._selected_group()
        if g and str(g.get("status") or "") == "NEEDS_MANUAL_CLASSIFY" and g.get("local_dir") and not g.get("archived"):
            self.open_manual_dialog(g)
        else:
            self.open_selected_host_manager()

    def _open_group_by_double_click(self, group_key):
        self.selected_group_key = str(group_key or "")
        self._primary_action()

    def _layout_host_cards(self, force=False):
        if not self._host_cards:
            return
        width = max(1, self.host_scroll.viewport().width())
        cols = max(1, min(6, (width + 12) // (200 + 12)))
        if not force and cols == self._host_cols:
            return
        self._host_cols = cols
        while self.host_grid.count():
            self.host_grid.takeAt(0)
        for idx, card in enumerate(self._host_cards):
            self.host_grid.addWidget(card, idx // cols, idx % cols, Qt.AlignTop | Qt.AlignLeft)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        t = getattr(self, "_host_relayout_timer", None)
        if t is None:
            t = QTimer(self)
            t.setSingleShot(True)
            t.timeout.connect(self._layout_host_cards)
            self._host_relayout_timer = t
        if not t.isActive():
            t.start(35)

    def _selected_group(self, groups=None):
        if not self.selected_group_key:
            return None
        source = groups if groups is not None else workspace_intake.list_groups()
        for g in source:
            if g.get("group_key") == self.selected_group_key:
                return g
        return None

    def open_selected_folder(self):
        g=self._selected_group()
        if not g or not g.get("local_dir"):
            QMessageBox.information(self,"素材目录","当前主播还没有本地素材目录。")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(material_folder(g["local_dir"]))))

    def open_group_manager(self, group_key):
        self.selected_group_key=str(group_key or "")
        self.open_selected_host_manager()

    def open_selected_host_manager(self):
        """Resolve the current host and report failures instead of silently doing nothing."""
        try:
            g = self._selected_group()
            if not g:
                QMessageBox.information(self, "主播管理", "请先选择一个主播。")
                return
            host_id = g.get("host_id")
            if not host_id and str(g.get("status") or "") == "READY_FOR_GPT":
                requested_key = self.selected_group_key
                intake.promote_ready_to_studio()
                groups, tasks, _ = workspace_intake.snapshot()
                self.refresh_cards(groups, tasks)
                self.selected_group_key = requested_key
                g = self._selected_group(groups)
                host_id = g.get("host_id") if g else None
            if not host_id:
                QMessageBox.information(
                    self, "主播管理",
                    "该主播尚未建立文案/图片管理数据。请先点击“同步该主播素材”；"
                    "如状态为“待分类”，请完成闭眼素材确认后再打开。"
                )
                return
            # Keep the controller supplied at construction; Qt may reparent pages.
            parent = self.parent_window
            if not callable(getattr(parent, "show_host", None)):
                parent = self.window()
            if not callable(getattr(parent, "show_host", None)):
                raise RuntimeError("主播管理页面未连接到主窗口，请重新启动 Flow Studio。")
            parent.show_host(int(host_id))
        except Exception as exc:
            intake.log.exception("Task Center host manager failed: %s", self.selected_group_key)
            QMessageBox.warning(self, "打开主播管理失败", f"无法打开文案/图片管理：\n{exc}")

    def _clear_box(self, layout):
        while layout.count():
            item=layout.takeAt(0); w=item.widget(); child=item.layout()
            if w: w.deleteLater()
            elif child: self._clear_box(child)

    def select_recipient(self, name):
        self.selected_recipient=str(name or "")
        # keep selected host only if it belongs to this recipient
        g=self._selected_group()
        if not g or g.get("recipient") != self.selected_recipient:
            self.selected_group_key=""
        self.refresh_cards()

    def select_group(self, group_key):
        self.selected_group_key=str(group_key or "")
        self.refresh_cards()

    def _first_image(self, g, tasks=None):
        from app.services.image_assets import resolve_path,ImageAssetError
        source = tasks if tasks is not None else workspace_intake.list_tasks()
        for task in source:
            if task.get('recipient')==g.get('recipient') and task.get('anchor_name')==g.get('anchor_name') and task.get('asset'):
                return task['asset']
        raw=str(g.get('local_dir') or '')
        if not raw:return None
        root=Path(raw).expanduser()
        if not root.is_dir():return None
        for path in sorted(root.rglob('*')):
            if is_valid_local_image(path):
                return str(path)
        return None

    def refresh_cards(self, groups=None, tasks=None):
        if groups is None or tasks is None:
            snapshot_groups, snapshot_tasks, _ = workspace_intake.snapshot()
            groups = list(snapshot_groups)
            task_rows = list(snapshot_tasks)
        else:
            groups = list(groups)
            task_rows = list(tasks)
        recipients=[]
        for g in groups:
            n=str(g.get("recipient") or "")
            if n and n not in recipients: recipients.append(n)
        if recipients and self.selected_recipient not in recipients:
            self.selected_recipient=recipients[0]
        selected_preview = [g for g in groups if not self.selected_recipient or str(g.get("recipient") or "") == self.selected_recipient]
        if (not self.selected_group_key or not any(g.get("group_key") == self.selected_group_key for g in groups)) and selected_preview:
            self.selected_group_key = selected_preview[0].get("group_key") or ""

        cards_sig = (
            work_dates.active(),
            self.selected_recipient,
            self.selected_group_key,
            tuple(sorted(g.items()) for g in groups),
            tuple((t.get("id"), t.get("asset"), t.get("status"), t.get("mode")) for t in task_rows),
        )
        if cards_sig == getattr(self, "_last_cards_sig", None):
            return
        self._last_cards_sig = cards_sig

        self._clear_box(self.recipient_cards)
        for name in recipients:
            owned=[g for g in groups if str(g.get("recipient") or "")==name]
            bad=sum(1 for g in owned if str(g.get("status") or "") not in ("READY_FOR_GPT",))
            card=ClickableFrame(objectName="recipientCard"); card.setProperty("selected", str(name==self.selected_recipient).lower()); card.setMinimumWidth(170); card.setFixedHeight(64)
            card.setCursor(Qt.PointingHandCursor)
            row=QHBoxLayout(card); row.setContentsMargins(10,8,14,8); row.setSpacing(10)
            ini=QLabel(name[:1] if name else "?",objectName="recipientInitialSmall"); ini.setAlignment(Qt.AlignCenter); row.addWidget(ini)
            info=QVBoxLayout(); info.setSpacing(1)
            info.addWidget(QLabel(name,objectName="cardTitle"))
            info.addWidget(QLabel((f"{len(owned)} 主播 · ⚠ {bad} 待处理" if bad else f"{len(owned)} 主播 · ✓ 正常"),objectName="statusWarn" if bad else "cardMeta"))
            row.addLayout(info,1)
            card.clicked.connect(lambda n=name:self.select_recipient(n)); self.recipient_cards.addWidget(card)
        self.recipient_cards.addStretch(1)
        self.recipient_section.setVisible(bool(recipients))
        self.body_stack.setCurrentIndex(1 if groups else 0)

        self._clear_box(self.host_grid)
        self._host_cards = []
        first_asset_by_pair = {}
        for t_row in task_rows:
            asset = t_row.get("asset")
            if asset:
                pair = (t_row.get("recipient"), t_row.get("anchor_name"))
                if pair not in first_asset_by_pair:
                    first_asset_by_pair[pair] = asset
        selected=[g for g in groups if not self.selected_recipient or str(g.get("recipient") or "")==self.selected_recipient]
        self.hosts_title.setText(f"{self.selected_recipient or 'AI'} · AI 主播（{len(selected)}）")
        for g in selected:
            card=_HostCard(objectName="hostCard"); card.setProperty("selected", str(g.get("group_key")==self.selected_group_key).lower())
            card.setFixedWidth(200); card.setCursor(Qt.PointingHandCursor)
            card.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Maximum)
            card.setToolTip("单击选中，双击打开文案 / 图片管理")
            cv=QVBoxLayout(card); cv.setContentsMargins(10,10,10,10); cv.setSpacing(5)
            thumb=QLabel("暂无图片",objectName="thumb"); thumb.setAlignment(Qt.AlignCenter); thumb.setFixedHeight(110)
            pair = (g.get("recipient"), g.get("anchor_name"))
            first_img = first_asset_by_pair.get(pair) or self._first_image(g, ())
            set_image_async(thumb, first_img, QSize(180, 110))
            cv.addWidget(thumb)
            name_lab=QLabel(str(g.get("anchor_name") or "主播"),objectName="cardTitle")
            name_lab.setText(name_lab.fontMetrics().elidedText(name_lab.text(), Qt.ElideRight, 160)); name_lab.setToolTip(str(g.get("anchor_name") or ""))
            cv.addWidget(name_lab)
            total=int(g.get("talking",0) or 0)+int(g.get("praying",0) or 0)
            cv.addWidget(QLabel(f"{total} 文案 · {int(g.get('images',0) or 0)} 图片",objectName="cardMeta"))
            ms_name = str(g.get("material_source") or "").strip()
            if ms_name:
                ms_lab = QLabel(f"💧 水印：{ms_name}", objectName="cardMeta")
                ms_lab.setText(ms_lab.fontMetrics().elidedText(ms_lab.text(), Qt.ElideRight, 172))
                ms_lab.setToolTip(f"表格「素材来源」绑定名字：{ms_name}")
                cv.addWidget(ms_lab)
            label, tone = _group_state(g)
            pill=QLabel(label,objectName="tcChip"); pill.setProperty("tone", tone)
            pill_row=QHBoxLayout(); pill_row.setContentsMargins(0,2,0,0); pill_row.addWidget(pill); pill_row.addStretch(1); cv.addLayout(pill_row)
            if g.get('mixed_requirement'):
                warning=QLabel('⚠ 混合文案，需手动选取',objectName='statusWarn');warning.setWordWrap(True);cv.addWidget(warning)
            card.clicked.connect(lambda k=g.get("group_key"):self.select_group(k))
            card.doubleClicked.connect(lambda k=g.get("group_key"):self._open_group_by_double_click(k))
            self._host_cards.append(card)
        self._layout_host_cards(force=True)

        g=self._selected_group(groups)
        if not g and selected:
            self.selected_group_key=selected[0].get("group_key") or ""; g=self._selected_group(groups)
        tools=(self.download_btn,self.open_folder_btn,self.rescan_btn,self.fill_btn,self.manual_btn,self.delete_host_btn)
        if g:
            st=str(g.get("status") or "")
            anchor=str(g.get("anchor_name","") or "")
            self.detail_title.setText(self.detail_title.fontMetrics().elidedText(anchor, Qt.ElideRight, 200)); self.detail_title.setToolTip(anchor)
            label, tone = _group_state(g)
            self.detail_status.setText(label); self._set_prop(self.detail_status, "tone", tone); self.detail_status.show()
            ms_detail = str(g.get("material_source") or "").strip()
            ms_suffix = f" · 💧 素材来源：{ms_detail}" if ms_detail else ""
            self.detail_meta.setText(f'{g.get("recipient","")}　·　TALKING {int(g.get("talking",0) or 0)} · PRAYING {int(g.get("praying",0) or 0)} · 图片 {int(g.get("images",0) or 0)}{ms_suffix}')
            pair = (g.get("recipient"), g.get("anchor_name"))
            img = first_asset_by_pair.get(pair) or self._first_image(g, ())
            self.detail_preview.clear()
            set_image_async(self.detail_preview, img, QSize(300, 124))
            local_dir=str(g.get("local_dir") or "")
            dir_text=f'📁 {local_dir}' if local_dir else '📁 尚未建立本地素材目录'
            self.detail_counts.setText(self.detail_counts.fontMetrics().elidedText(dir_text, Qt.ElideMiddle, 290))
            self.detail_counts.setToolTip(local_dir)
            for b in tools: b.setEnabled(True)
            self.download_btn.setEnabled(not g.get("archived"))
            self.open_folder_btn.setEnabled(bool(local_dir))
            self.manual_btn.setEnabled(bool(local_dir) and not g.get("archived"))
            self.manual_btn.setToolTip("手动确认图片睁眼/闭眼。文案优先读取需求说明，闭眼文案内部再按红黑颜色区分。")
            self.manage_btn.setEnabled(True)
            # The primary button always shows the single most useful next step for this host.
            if st=="NEEDS_MANUAL_CLASSIFY":
                self.manage_btn.setText("👁  确认闭眼图片"); self.manage_btn.setObjectName("warnBtn")
                hint="💡 下一步：点击下方按钮，勾选这个主播的闭眼图片并确认，然后就能管理文案。"
            elif st=="READY_FOR_GPT" or g.get("host_id"):
                self.manage_btn.setText("📝  管理文案 / 图片"); self.manage_btn.setObjectName("primaryBtn")
                hint="💡 素材已就绪，可编辑中文 / 外文文案和编号图片。也可以直接双击左侧卡片打开。"
            elif st=="MATERIAL_SHORTAGE":
                self.manage_btn.setText("📝  管理文案 / 图片"); self.manage_btn.setObjectName("primaryBtn")
                hint="💡 图片数量不足：把图片放进本地文件夹后点「重新扫描」，或直接「随机补齐缺图」。"
            elif st in ("DRIVE_LINK_CONFLICT","MATERIAL_LINK_MISSING"):
                self.manage_btn.setText("📝  管理文案 / 图片"); self.manage_btn.setObjectName("primaryBtn")
                hint="💡 素材链接有问题：请检查表格里的 Drive 链接，修正后点「同步素材」。"
            else:
                self.manage_btn.setText("📝  管理文案 / 图片"); self.manage_btn.setObjectName("primaryBtn")
                hint="💡 素材还在准备中：可点「同步素材」重新下载，完成后即可管理文案。"
            self._set_prop(self.manage_btn, "_tone", self.manage_btn.objectName())
            self.manage_hint.setText(hint); self.manage_hint.show()
        else:
            self.detail_title.setText("选择一个主播"); self.detail_meta.setText("点击左侧主播卡片查看任务与素材情况。")
            self.detail_preview.setText("暂无素材"); self.detail_counts.setText(""); self.detail_status.hide()
            self.manage_hint.hide()
            self.manage_btn.setText("📝  管理文案 / 图片"); self.manage_btn.setObjectName("primaryBtn"); self._set_prop(self.manage_btn, "_tone", "primaryBtn")
            self.manage_btn.setEnabled(False)
            for b in tools: b.setEnabled(False)

    def connect_google(self, switch=False):
        oauth = repo.get_setting("google_oauth_client_path", "").strip()
        if not oauth or not Path(oauth).expanduser().exists():
            path, _ = QFileDialog.getOpenFileName(
                self, "首次连接 Google：选择 OAuth Desktop Client JSON", str(Path.home()), "JSON 文件 (*.json)"
            )
            if not path:
                return
            repo.set_setting("google_oauth_client_path", path)
            self._log("已保存 Google OAuth 授权文件；接下来会打开 Google 官方登录页面。")
        self.run_worker("switch_google" if switch else "connect_google")

    def _apply_auto_timer(self):
        if not hasattr(self, "auto_timer"):
            return
        self.auto_timer.stop()

    def auto_sync_changed(self, checked):
        self._apply_auto_timer()

    def auto_interval_changed(self, value):
        self._apply_auto_timer()

    def auto_sync_tick(self):
        # Manual-only intake: old saved settings cannot restart background reads.
        return

    def _system_notify(self, title, body):
        if __import__('sys').platform != 'darwin':
            return
        try:
            esc=lambda v: str(v).replace('\\','\\\\').replace('"','\\"')
            script=f'display notification "{esc(body)}" with title "{esc(title)}"'
            subprocess.run(["osascript","-e",script],capture_output=True,timeout=4)
        except Exception:
            pass

    def sync_all(self):
        if not repo.get_setting("task_source_sheet_url", "").strip():
            self._goto_settings("尚未设置任务获取表格链接。")
            return
        if not repo.default_creator().strip():
            self._goto_settings("尚未设置默认制作人。")
            return
        if not repo.get_setting("task_asset_root", "").strip():
            self._goto_settings("尚未设置任务素材本地根目录。")
            return
        if not intake.TOKEN_FILE.exists():
            box = QMessageBox(self)
            box.setWindowTitle("Google 账号尚未连接")
            box.setText("同步任务还需要读取私有 Drive 素材并回写作者/制作情况，请先连接有权限的 Google 账号。")
            go = box.addButton("连接 Google", QMessageBox.AcceptRole)
            box.addButton("取消", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is go:
                self.connect_google(False)
            return
        self.run_worker("sync_all")

    def open_manual_task_dialog(self):
        from app.ui.manual_task_dialog import ManualTaskDialog
        dlg = ManualTaskDialog(self, work_date=work_dates.active())
        dlg.tasks_imported.connect(self._on_manual_tasks_imported)
        dlg.exec()

    def _on_manual_tasks_imported(self, res: dict):
        if res.get("first_recipient"):
            self.selected_recipient = str(res["first_recipient"])
        if res.get("first_group_key"):
            self.selected_group_key = str(res["first_group_key"])
        self._last_cards_sig = None
        self.refresh()
        created_n = int(res.get("created_tasks") or 0)
        promoted_n = int(res.get("promoted_created") or 0)
        need_cls = list(res.get("needs_manual_classify_groups") or [])
        short_grps = list(res.get("shortage_groups") or [])
        msg = f"手动导入完成：新增 {created_n} 条任务（已进入生产链路 {promoted_n} 条）"
        if need_cls:
            msg += f"，{len(need_cls)} 个主播需确认闭眼图片"
        if short_grps:
            msg += f"，{len(short_grps)} 个主播图片数量不足（可点「随机补齐缺图」）"
        self._log("✓ " + msg)
        parent = self.parent_window or self.window()
        if hasattr(parent, "refresh_all"):
            try:
                parent.refresh_all()
            except Exception:
                pass
        if need_cls:
            QTimer.singleShot(150, self._open_first_manual_if_needed)

    def download_selected(self):
        g = self._selected_group()
        if not g:
            QMessageBox.information(self, "同步素材", "请先选择一个主播。")
            return
        if str(g.get("drive_url") or "").startswith("local:"):
            self.rescan_selected()
            return
        self.run_worker("download", g["group_key"])

    def rescan_selected(self, checked=False, *, random_fill=False):
        g = self._selected_group()
        if not g:
            QMessageBox.information(self, "本地扫描", "请先选择一个主播。")
            return
        self.run_worker("rescan_local", g["group_key"], {"day": work_dates.active(), "random_fill": random_fill})

    def rescan_material_sources(self):
        if getattr(self, "_rescan_ms_worker", None) and self._rescan_ms_worker.isRunning():
            return
        day = work_dates.active()
        self.rescan_source_btn.setEnabled(False)
        self.rescan_source_btn.setText("⟳ 读取中…")
        self.status.setText("正在重新读取 Google 表格「素材来源」列…")

        class _MsWorker(QThread):
            done = Signal(object, str)

            def run(self_w):
                try:
                    from app.services import ai_watermark
                    self_w.done.emit(ai_watermark.rescan_sheet_material_sources(day), "")
                except Exception as exc:
                    self_w.done.emit(None, str(exc))

        def _finish(res, err):
            self.rescan_source_btn.setEnabled(True)
            self.rescan_source_btn.setText("↻ 重读素材来源")
            if err or not res:
                self.status.setText(f"⚠ 重读素材来源失败：{err or '未知错误'}")
                QMessageBox.warning(self, "重读素材来源", err or "读取失败")
                return
            self._last_cards_sig = None
            self.refresh_cards()
            msg = str(res.get("message") or "已重新读取素材来源。")
            self.status.setText("✓ " + msg)
            QMessageBox.information(self, "重读素材来源", msg)

        w = _MsWorker(self)
        w.done.connect(_finish)
        self._rescan_ms_worker = w
        w.start()

    def delete_selected_host(self):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "删除主播", "当前操作尚未完成，请稍后再删除。")
            return
        g = self._selected_group()
        if not g:
            QMessageBox.information(self, "删除主播", "请先选择一个主播。")
            return
        import importlib
        import app.services.delete_selected_host as _dsh
        importlib.reload(_dsh)
        try:
            plan = _dsh.preview(g["group_key"], work_dates.active())
        except Exception as exc:
            QMessageBox.warning(self, "无法删除主播", str(exc))
            return
        box = QMessageBox(self)
        box.setWindowTitle("确认删除选中主播")
        box.setIcon(QMessageBox.Warning)
        box.setText(f'{plan["day"]} · {plan["recipient"]} · {plan["anchor"]}')
        box.setInformativeText(
            f'确认后将删除当前 AI 主播在任务中心的 {plan["task_count"]} 条任务，并从“提示词”开始清除后续全部生产链路：\n'
            'GPT 提示词任务 → Flow 排队/生成/下载 → 返工 → 质检 → 自动剪辑记录。\n'
            '正在执行或已提交的旧任务也会立即作废；旧结果之后返回时不会重新进入质检。\n'
            f'将彻底删除该主播关联的 {len(plan["files"])} 个本地文件（含本地图片素材目录及全部已生成视频文件）。\n'
            f'{len(plan["shared_files"])} 个共享文件会保留；其他主播和其他日期不受影响。\n'
            'Google 表格源数据不删除，后续重新同步时仍可能再次导入该主播。'
        )
        box.setDetailedText(
            '任务中心编号：' + str(plan['intake_ids']) + '\n生产任务编号：' + str(plan['video_ids']) +
            '\n\n将删除的本地目录：\n' + ('\n'.join(plan.get('local_dirs', [])) or '无') +
            '\n\n将删除的本地文件：\n' + ('\n'.join(plan['files']) or '无') +
            '\n\n保留的共享文件：\n' + ('\n'.join(plan['shared_files']) or '无')
        )
        remove = box.addButton("确认删除该主播", QMessageBox.DestructiveRole)
        cancel = box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(cancel)
        box.exec()
        if box.clickedButton() is remove:
            self.run_worker("delete_host", g["group_key"], plan)

    def run_worker(self, action, group_key="", payload=None):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "任务中心", "当前操作还在运行，请稍候。")
            return
        self.progress.setValue(0)
        self.progress_percent.setText("0%")
        self.progress_label.setText("同步进度 · 正在启动")
        self.progress_detail.setText("正在准备同步环境…")
        self._progress_hide_timer.stop()
        self.progress_box.show()
        self.status.setText("正在处理…")
        self.sync_btn.setEnabled(False); self.empty_sync_btn.setEnabled(False)
        self.worker = IntakeWorker(action, group_key, self, payload=payload)
        self.worker.progress_changed.connect(self.update_sync_progress)
        self.worker.finished_data.connect(lambda d, a=action: self.worker_done(a, d))
        self.worker.failed.connect(self.worker_failed)
        self.worker.finished.connect(self._release_worker)
        self.worker.start()

    def _release_worker(self):
        worker = self.sender()
        if self.worker is worker:
            self.worker = None
        worker.deleteLater()

    def update_sync_progress(self, percent, stage, detail):
        percent=max(0,min(100,int(percent)))
        self.progress.setValue(percent)
        self.progress_percent.setText(f"{percent}%")
        self.progress_label.setText(f"同步进度 · {stage or '处理中'}")
        self.progress_detail.setText(detail or "正在处理…")
        self.status.setText(stage or "正在处理…")

    def worker_done(self, action, data):
        self.progress.setValue(100)
        self.progress_percent.setText("100%")
        self.progress_label.setText("同步进度 · 已完成")
        self.progress_detail.setText("任务、素材与 Studio 数据已完成本轮同步。")
        self.sync_btn.setEnabled(True); self.empty_sync_btn.setEnabled(True)
        self.status.setText("完成")
        # Keep the finished bar visible briefly, then collapse it to give space back to the cards.
        self._progress_hide_timer.start(2500)
        if action in ("sync_all", "sync_auto"):
            s = data.get("sync", {})
            dls = data.get("downloads") or []
            skipped_hosts = sum(1 for d in dls if d.get("skipped_check") or d.get("unchanged"))
            skip_note = f"，跳过重复校验主播 {skipped_hosts} 个" if skipped_hosts else ""
            self._log(
                f'同步完成：新增 {s.get("imported",0)}，更新 {s.get("updated",0)}，已存在 {s.get("unchanged",0)}；'
                f'写回表格 {s.get("writeback",{}).get("written",0)} 行{skip_note}。'
            )
            if action == "sync_auto" and int(s.get("imported",0) or 0) > 0:
                self._system_notify("Flow Studio · 获取到新任务", f"新增 {int(s.get('imported',0))} 条任务，已加入任务中心")
            if data.get("errors"):
                for err in data["errors"][:20]:
                    self._log("⚠ " + str(err.get("error") or "素材准备失败"))
        elif action in ("connect_google", "switch_google"):
            self._log("Google 账号：" + (data.get("email") or data.get("display_name") or "已连接"))
        else:
            self._log(data.get("message") or data.get("status") or "操作完成")
        if action in ("rescan_local", "delete_host"):
            if action == "delete_host":
                # Also cancel the live in-memory Bridge snapshot immediately. The DB
                # snapshot was already scrubbed transactionally by delete_selected_host.
                try:
                    flow = getattr(self.parent_window, 'flow_task_center', None)
                    bridge = getattr(flow, 'bridge', None)
                    commands = list(data.get('old_command_ids') or [])
                    if bridge is not None and commands:
                        bridge.cancel_host_commands(commands)
                except Exception:
                    pass
            self._date_view_refresh = True
            try:
                self.refresh()
            finally:
                self._date_view_refresh = False
            self.progress_detail.setText(data.get("message") or "操作完成")
            QMessageBox.information(self, "本地扫描完成" if action == "rescan_local" else "删除完成", data.get("message") or "完成")
        else:
            self.refresh()
            self._open_first_manual_if_needed()

    def worker_failed(self, error):
        self.progress_label.setText("同步进度 · 失败")
        self.progress_detail.setText(str(error))
        self.progress_percent.setText(f"{self.progress.value()}%")
        self._progress_hide_timer.stop(); self.progress_box.show()
        self.sync_btn.setEnabled(True); self.empty_sync_btn.setEnabled(True)
        self.status.setText("失败")
        self._log("🔴 " + error)
        QMessageBox.warning(self, "任务中心", error)
        self.refresh_google_state()

    def clear_tasks(self, resync=False):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self,'清空当前任务','任务同步正在运行，请等待同步结束后清空。');return
        from app.ui.confirmation import confirm_clear
        day = work_dates.active()
        if not confirm_clear(self, "清空当前任务", f"仅清空任务中心当前日期（{day}）的任务显示，其它日期不受影响。任务源、提示词、Flow 下载、质检、重做、剪辑和历史记录全部保留。同步后可重新显示任务。"):
            return
        from app.services.local_bridge import get_bridge
        try:d = intake.clear_current_tasks(get_bridge(), day=day)
        except Exception as exc:
            QMessageBox.warning(self,'清空当前任务',str(exc));return
        self._log(f'已清空 {day} 的任务中心显示；所有生产数据和素材均保留。')
        self.refresh()
        if resync:
            self.sync_all()

    def open_manual_for_selected(self):
        g = self._selected_group()
        if not g:
            QMessageBox.information(self, "素材分类", "请先选择一个主播。")
            return
        if g.get("archived") or not g.get("local_dir"):
            QMessageBox.information(self, "素材分类", "请先同步该主播素材，建立本地素材文件夹。")
            return
        self.open_manual_dialog(g)

    def open_manual_dialog(self, g):
        if self.manual_dialog and self.manual_dialog.isVisible():
            self.manual_dialog.raise_()
            self.manual_dialog.activateWindow()
            return
        self.manual_dialog = ManualClassifyDialog(g, self)
        self.manual_dialog.completed.connect(lambda _k: (self.refresh(), QTimer.singleShot(150, self._open_first_manual_if_needed)))
        self.manual_dialog.show()

    def _open_first_manual_if_needed(self):
        for g in intake.list_groups():
            if g.get("status") == "NEEDS_MANUAL_CLASSIFY":
                self.open_manual_dialog(g)
                break

    def open_prompt_center(self):
        parent = self.window()
        if hasattr(parent, "show_prompt_center"):
            parent.show_prompt_center()

    def _goto_settings(self, message):
        box = QMessageBox(self)
        box.setWindowTitle("需要完成系统设置")
        box.setText(message)
        go = box.addButton("前往", QMessageBox.AcceptRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is go:
            parent = self.window()
            if hasattr(parent, "open_settings"):
                parent.open_settings()

    def refresh_google_state(self):
        try:
            info = {"connected": intake.TOKEN_FILE.exists()}
            if info.get("connected"):
                self.google_state.setText("🟢 Google 已连接")
                self.google_state.setToolTip(info.get("email") or "已授权，同步时验证")
                self._set_prop(self.google_state, "tone", "good")
            else:
                self.google_state.setText("🔴 Google 未连接")
                self.google_state.setToolTip("请在系统设置中连接 Google 账号")
                self._set_prop(self.google_state, "tone", "bad")
        except Exception:
            self.google_state.setText("Google 状态未知")

    def show_available_date(self):
        day=self.available_dates.currentData()
        if day and self.parent_window:
            self.parent_window.set_work_date(day)

    def _set_empty_text(self, text):
        """Set the empty-state description and size it to fit every wrapped line (no clipping)."""
        self.empty_text.setText(text)
        self.empty_text.ensurePolished()
        fm = self.empty_text.fontMetrics()
        w = self.empty_text.width() or 560
        rect = fm.boundingRect(QRect(0, 0, w, 10000), Qt.AlignCenter | Qt.TextWordWrap, text)
        self.empty_text.setFixedHeight(rect.height() + fm.leading() + 8)

    def refresh(self):
        groups, tasks, dates = workspace_intake.snapshot()
        current=work_dates.active()
        other=sorted((d for d in dates if d!=current),reverse=True)
        self.available_dates.clear()
        for day in other:self.available_dates.addItem('历史未分类' if day==work_dates.LEGACY else day,day)
        empty=not groups
        self.available_dates.setVisible(empty and bool(other));self.show_date_btn.setVisible(empty and bool(other))
        self.date_hint.setText(f'📅 工作日期 {current}' + (f'　·　{len(tasks)} 条文案' if tasks else ''))
        if empty:
            if other:
                self.empty_title.setText("这个日期还没有任务")
                self._set_empty_text(f"可点击「立即同步任务」读取 Google 表格、「手动填写任务」本地填表/粘贴，或查看其它已有任务的日期（共 {len(other)} 个日期）。")
            else:
                self.empty_title.setText("今天还没有任务")
                self._set_empty_text("点击「立即同步任务」从 Google 表格读取任务，或点击「手动填写任务」直接在本地表格填写 / 批量粘贴任务。")

        ready=sum(1 for g in groups if g.get("status")=="READY_FOR_GPT")
        manual=sum(1 for g in groups if g.get("status")=="NEEDS_MANUAL_CLASSIFY")
        error=sum(1 for g in groups if g.get("status") in ("MATERIAL_SHORTAGE","DRIVE_LINK_CONFLICT","MATERIAL_LINK_MISSING"))
        preparing=len(groups)-ready-manual-error
        recipients=len({str(g.get("recipient") or "") for g in groups if g.get("recipient")})
        scripts=sum(int(g.get("talking",0) or 0)+int(g.get("praying",0) or 0) for g in groups)
        self.summary.setText(f"{recipients} 接收人   ·   {len(groups)} 主播   ·   {scripts} 文案   ·   {ready} 素材正常   ·   ⚠ {manual+error} 待处理")

        chips=self.metric_chips
        chips["recipients"].setText(f"{recipients} 接收人")
        chips["hosts"].setText(f"{len(groups)} 主播")
        chips["scripts"].setText(f"{scripts} 文案")
        chips["ready"].setText(f"✓ {ready} 就绪"); self._set_prop(chips["ready"], "tone", "good" if ready else "")
        pending=manual+error+preparing
        chips["pending"].setText(f"⚠ {pending} 待处理"); self._set_prop(chips["pending"], "tone", "warn" if pending else "")
        for c in chips.values(): c.setVisible(not empty)

        # Step guide: highlight where the user is and say exactly what to do next.
        if empty:
            states=("active","todo","todo")
            hint="👉 第 1 步：点击右上角「同步任务」读取 Google 表格，或点击「手动填写任务」在本地直接录入 / 批量粘贴任务。"
        elif manual:
            states=("done","active","todo")
            hint=f"👉 第 2 步：有 {manual} 个主播需要确认闭眼图片 —— 选中标着「待确认闭眼图」的主播，点击右侧橙色按钮完成确认。"
        elif error:
            states=("done","active","todo")
            hint=f"👉 第 2 步：有 {error} 个主播素材异常（缺图或链接问题）—— 选中后在右侧「素材工具」里重新扫描或随机补齐。"
        elif preparing:
            states=("done","active","todo")
            hint=f"⏳ 有 {preparing} 个主播素材仍在准备中，稍等片刻或在右侧点击「同步素材」。"
        else:
            states=("done","done","active")
            hint=f"✅ 全部 {len(groups)} 个主播素材已就绪。双击主播卡片可检查文案和图片；确认无误后，从左侧栏进入下一步。"
        for lab, state in zip(self.step_labels, states):
            self._set_prop(lab, "state", state)
        self.guide_hint.setText(hint)

        if not getattr(self,"_date_view_refresh",False): self.refresh_google_state()
        self.refresh_cards(groups, tasks)
        if self.log.isVisible():
            self.load_log()

    def load_log(self):
        if not self.log.isVisible():
            return
        try:
            from app.services.runtime_log import read_tail
            text = read_tail(intake.LOG_FILE)
            self.log.setPlainText("\n".join(text.splitlines()[-2500:]))
            self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())
        except Exception:
            pass

    def _log(self, text):
        self.status.setText(str(text))
        from app.services.runtime_log import log
        log('intake_ui_log', message=str(text))
        if self.log.isVisible():
            self.log.appendPlainText(str(text))
