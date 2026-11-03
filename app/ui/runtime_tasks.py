"""Runtime tasks & batch manual retry manager for Flow Generation Center.

Organizes all active, stalled, and failed tasks of the current work date into
Recipient -> AI Host cards with inline expandable Video -> Segment drawers,
real-time elapsed/stalled duration tracking, multi-level selection (including
Shift-click range and one-click stalled/failed selection), batch channel
reassignment, and single-confirmation batch reset-and-retry across ALL states
(including stuck ``已准备 / 已提交 / 生成中 / 下载中`` tasks and ``图片上传跳过``).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QImage, QPainter, QPainterPath, QPixmap, QTextOption
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.core import repository as repo
from app.core import work_dates
from app.core.database import connect
from app.services import image_assets, task_recovery
from app.services.flow_error_guide import diagnose_flow_error, translate_common_exception_cn
from app.services.perf_diagnostics import measured
from app.services.resolve_error_guide import EditingErrorInfo
from app.ui.flow_layouts import CardGrid
from app.ui.manual_video_import_dialog import (
    ManualVideoImportDialog,
    import_single_segment_interactive,
)
from app.ui.read_snapshot import SnapshotReader
from app.ui.resolve_error_dialog import EditingErrorDetailDialog
from app.ui.task_error_view import error_view, needs_prompt, upload_skipped


def _set_prop(widget: QWidget, name: str, value: str) -> bool:
    if widget.property(name) == value:
        return False
    widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    return True


def _set_text(widget: QLabel | QPushButton, value: str, tip: str | None = None) -> None:
    value = str(value or "")
    if widget.text() != value:
        widget.setText(value)
    if tip is not None and widget.toolTip() != tip:
        widget.setToolTip(tip)


def _rounded_portrait_pixmap(image: QImage) -> QPixmap:
    src = QPixmap.fromImage(image)
    if src.isNull():
        return src
    dpr = max(1.0, float(src.devicePixelRatio() or 1.0))
    out = QPixmap(src.size())
    out.setDevicePixelRatio(dpr)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0.0, 0.0, src.width() / dpr, src.height() / dpr), 7.0, 7.0)
    p.setClipPath(path)
    p.drawPixmap(0, 0, src)
    p.end()
    return out


class _ElidingLabel(QLabel):
    def __init__(self, object_name: str = "", min_w: int = 36):
        super().__init__(objectName=object_name)
        self._raw = ""
        self.setMinimumWidth(min_w)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def set_raw_text(self, value: str, tooltip: str | None = None) -> None:
        value = str(value or "")
        tip = value if tooltip is None else str(tooltip)
        if self._raw == value and self.toolTip() == tip:
            return
        self._raw = value
        self.setToolTip(tip)
        self._update_elided()

    def _update_elided(self) -> None:
        w = self.width()
        if w <= 20:
            super().setText(self._raw)
        else:
            super().setText(self.fontMetrics().elidedText(self._raw, Qt.ElideRight, max(20, w - 2)))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_elided()


class _ClickableFrame(QFrame):
    clicked = Signal(object)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            child = self.childAt(event.position().toPoint())
            w = child
            while w is not None and w is not self:
                if isinstance(w, (QPushButton, QCheckBox, QComboBox)):
                    super().mouseReleaseEvent(event)
                    return
                w = w.parentWidget()
            self.clicked.emit(event.modifiers())
        super().mouseReleaseEvent(event)


class _NoWheelCombo(QComboBox):
    """Prevents accidental channel changes while scrolling the task drawer."""

    def wheelEvent(self, event) -> None:
        event.ignore()


class _GridBody(QWidget):
    """Wraps CardGrid so QScrollArea honors exact multi-row heightForWidth."""

    def __init__(self, parent: QWidget, grid: CardGrid):
        super().__init__(parent)
        self.setObjectName("flowRecipientBody")
        self._grid = grid
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 10)
        lay.setSpacing(0)
        lay.addLayout(grid)

    def sync_height(self) -> None:
        lay = self.layout()
        if lay is None or self.width() <= 40:
            return
        m = lay.contentsMargins()
        avail_w = max(1, self.width() - m.left() - m.right())
        h = (self._grid.heightForWidth(avail_w) if self._grid.count() > 0 else 0) + m.top() + m.bottom()
        if self.minimumHeight() != h or self.maximumHeight() != h:
            self.setFixedHeight(h)
            self.updateGeometry()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.sync_height()


def _reorder_widgets(layout, widgets: list[QWidget]) -> bool:
    cur = [layout.itemAt(i).widget() for i in range(layout.count())]
    if cur == widgets:
        return False
    while layout.count():
        layout.takeAt(0)
    for w in widgets:
        layout.addWidget(w)
        w.show()
    return True


class RuntimeTasksDialog(QDialog):
    """Host-card grouped runtime task monitor & batch retry/reset manager."""

    def __init__(self, owner=None, initial_filter: str = "all"):
        super().__init__(owner)
        self.owner = owner
        self.setWindowTitle("运行任务与异常重试 · 按主播查看 / 批量重置卡住与失败任务")
        self.resize(1160, 760)

        self.channel_choices: dict[int, str] = {}
        self._checked: set[int] = set()
        self._last_clicked_sid: int | None = None
        self._filter_mode: str = initial_filter if initial_filter in (
            "all", "stalled", "failed", "upload_skipped", "needs_prompt", "running"
        ) else "all"
        self._expanded_hosts: set[int] = set()
        self._manually_toggled_hosts: set[int] = set()
        self._collapsed_recipients: dict[int, bool] = {}
        self._snapshot: dict | None = None
        self._queued_snapshot: tuple[str, dict] | None = None
        self._seg_index: dict[int, dict] = {}
        self._tasks: dict[int, dict] = {}
        self._visible_ordered_sids: list[int] = []
        self._rec_widgets: dict[int, dict] = {}
        self._thumb_cache: dict[int, tuple[object, QPixmap]] = {}
        self._view_day: str | None = None
        self._retry_busy = False

        try:
            saved_stall = int(repo.get_setting("flow_runtime_stall_minutes", "10") or 10)
        except Exception:
            saved_stall = 10
        self._stall_minutes = saved_stall if saved_stall in (3, 5, 10, 15, 20) else 10

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        # ── 1. Header Row: Title + Search + Stall Threshold ──
        head = QHBoxLayout()
        head.setSpacing(10)
        self.title_lbl = QLabel("运行任务与异常重试", objectName="sectionTitle")
        self.title_lbl.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        head.addWidget(self.title_lbl)
        self.sub_hint = _ElidingLabel("muted", min_w=40)
        self.sub_hint.hide()
        head.addStretch(1)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍 搜索主播 / 编号 / 报错")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setFixedWidth(210)
        self.search_edit.textChanged.connect(self._on_filter_changed)
        head.addWidget(self.search_edit)

        stall_lbl = QLabel("⏳ 阈值:", objectName="muted")
        stall_lbl.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        head.addWidget(stall_lbl)
        self.stall_combo = _NoWheelCombo()
        self.stall_combo.setMinimumWidth(116)
        self.stall_combo.setToolTip(
            "运行超过该时长仍未完成的任务会自动标橙归入「⏳ 卡住」，方便一键勾选批量重试\n"
            "（其中「已准备 / 已提交」超过 3 分钟未进入生成也会自动预警）"
        )
        for mins, txt in (
            (3, "≥ 3 分钟"),
            (5, "≥ 5 分钟"),
            (10, "≥ 10 分钟"),
            (15, "≥ 15 分钟"),
            (20, "≥ 20 分钟"),
        ):
            self.stall_combo.addItem(txt, mins)
        idx_st = self.stall_combo.findData(self._stall_minutes)
        if idx_st >= 0:
            self.stall_combo.setCurrentIndex(idx_st)
        self.stall_combo.currentIndexChanged.connect(self._on_stall_threshold_changed)
        head.addWidget(self.stall_combo)
        root.addLayout(head)

        # ── 2. Filter Pills + Quick Actions Row ──
        pills_row = QHBoxLayout()
        pills_row.setSpacing(6)
        self._filter_btns: dict[str, QPushButton] = {}
        pill_defs = (
            ("all", "全部 0", "all"),
            ("stalled", "⏳ 卡住 0", "waiting"),
            ("failed", "⚠ 失败 0", "failed"),
            ("upload_skipped", "🖼 跳过 0", "failed"),
            ("needs_prompt", "📝 改词 0", "waiting"),
            ("running", "● 运行 0", "running"),
        )
        for mode, init_txt, p_kind in pill_defs:
            pill = QPushButton(init_txt, objectName="flowProgFilterPill")
            pill.setCheckable(True)
            pill.setChecked(mode == self._filter_mode)
            pill.setProperty("pillKind", p_kind)
            pill.setCursor(Qt.PointingHandCursor)
            pill.setFocusPolicy(Qt.NoFocus)
            pill.clicked.connect(lambda _=False, m=mode: self._set_filter_mode(m))
            self._filter_btns[mode] = pill
            pills_row.addWidget(pill)

        pills_row.addSpacing(8)

        self.btn_select_all = QPushButton("全选", objectName="rtQuickSelectBtn")
        self.btn_select_all.setCursor(Qt.PointingHandCursor)
        self.btn_select_all.setToolTip("全选当前显示的所有片段")
        self.btn_select_all.clicked.connect(lambda: self._select_visible(True))
        pills_row.addWidget(self.btn_select_all)

        self.btn_clear_sel = QPushButton("清空", objectName="rtQuickSelectBtn")
        self.btn_clear_sel.setCursor(Qt.PointingHandCursor)
        self.btn_clear_sel.setToolTip("清空所有已勾选的片段")
        self.btn_clear_sel.clicked.connect(lambda: self._select_visible(False))
        pills_row.addWidget(self.btn_clear_sel)

        self.btn_select_stalled = QPushButton("⚡ 选卡住 (0)", objectName="rtQuickSelectBtn")
        self.btn_select_stalled.setProperty("accent", "amber")
        self.btn_select_stalled.setCursor(Qt.PointingHandCursor)
        self.btn_select_stalled.setToolTip("自动勾选当前工作日期所有超过卡住阈值的运行中任务")
        self.btn_select_stalled.clicked.connect(self._select_all_stalled)
        pills_row.addWidget(self.btn_select_stalled)

        self.btn_select_failed = QPushButton("⚡ 选失败 (0)", objectName="rtQuickSelectBtn")
        self.btn_select_failed.setProperty("accent", "red")
        self.btn_select_failed.setCursor(Qt.PointingHandCursor)
        self.btn_select_failed.setToolTip("自动勾选当前工作日期所有失败、下载失败与图片上传跳过的任务")
        self.btn_select_failed.clicked.connect(self._select_all_failed)
        pills_row.addWidget(self.btn_select_failed)

        pills_row.addStretch(1)

        route_lbl = QLabel("通道:", objectName="muted")
        pills_row.addWidget(route_lbl)
        self.batch_channel_combo = _NoWheelCombo()
        self.batch_channel_combo.setMinimumWidth(168)
        self.batch_channel_combo.setToolTip(
            "选择批量重置重试时的通道分配策略：\n"
            "• 🤖 自动分配空闲通道：解绑原卡死通道，交给当前空闲健康的通道执行（推荐）\n"
            "• 📌 保持原通道：继续使用每个任务原本绑定的通道（若你在单行改过通道则按单行设置）\n"
            "• 🎯 指定具体通道：将选中的任务统一改派到指定通道"
        )
        self._populate_batch_channel_combo([])
        pills_row.addWidget(self.batch_channel_combo)

        self.btn_refresh = QPushButton("↻", objectName="dlIconBtn")
        self.btn_refresh.setProperty("iconOnly", "true")
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.setToolTip("刷新运行任务与异常列表")
        self.btn_refresh.clicked.connect(lambda: self.refresh(force=True))
        pills_row.addWidget(self.btn_refresh)
        root.addLayout(pills_row)

        # ── 4. Main Scroll Area (Recipient -> Host Cards -> Inline Task Drawers) ──
        self.scroll = QScrollArea(objectName="cardScroll")
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_content = QWidget(objectName="scrollContent")
        self.cards_layout = QVBoxLayout(self.scroll_content)
        self.cards_layout.setContentsMargins(2, 2, 6, 8)
        self.cards_layout.setSpacing(12)
        self.cards_layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.scroll_content)
        root.addWidget(self.scroll, 1)

        self.empty_label = QLabel("当前工作日期没有运行中或待重试的任务", self.scroll_content, objectName="flowMonitorEmpty")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setMinimumHeight(130)
        self.empty_label.hide()

        # ── 5. Footer Action Bar ──
        foot = QHBoxLayout()
        foot.setSpacing(10)
        self.sel_summary_lbl = QLabel("已选 0 段", objectName="cardMeta")
        foot.addWidget(self.sel_summary_lbl)
        self.status_banner_lbl = QLabel("", objectName="muted")
        foot.addWidget(self.status_banner_lbl, 1)

        close_btn = QPushButton("关闭")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(self.close)
        foot.addWidget(close_btn)

        self.btn_batch_abandon = QPushButton("🗑 放弃视频", objectName="rtDangerBtn")
        self.btn_batch_abandon.setCursor(Qt.PointingHandCursor)
        self.btn_batch_abandon.setEnabled(False)
        self.btn_batch_abandon.setToolTip("将选中片段所属的整条视频作废，不再继续生成或进入剪辑")
        self.btn_batch_abandon.clicked.connect(self.abandon_selected_batch)
        foot.addWidget(self.btn_batch_abandon)

        self.batch_retry_btn = QPushButton("↻ 重置重试", objectName="primaryBtn")
        self.batch_retry_btn.setCursor(Qt.PointingHandCursor)
        self.batch_retry_btn.setEnabled(False)
        self.batch_retry_btn.setToolTip("一次性重置所有选中的卡住任务、失败任务或上传跳过任务，并重新加入生成队列")
        self.batch_retry_btn.clicked.connect(self.batch_retry_selected)
        foot.addWidget(self.batch_retry_btn)
        root.addLayout(foot)

        # Async Snapshot Reader + Live Refresh Timers
        self.reader = SnapshotReader(self, task_recovery.runtime_snapshot_for_date)
        self.reader.ready.connect(self._on_snapshot_ready)

        self.visual_timer = QTimer(self)
        self.visual_timer.setInterval(600)
        self.visual_timer.timeout.connect(self._flush_snapshot)

        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.refresh)
        self.finished.connect(lambda *_: (self.timer.stop(), self.visual_timer.stop()))

        self.refresh(force=True)

    # ── Legacy static helper preserved for existing unit test compatibility ──
    @staticmethod
    @measured("task_list_refresh")
    def _read_rows(day):
        rows = [
            dict(r)
            for r in repo.list_flow_tasks(work_date=day)
            if r["flow_status"] != "已完成"
            and (
                r["flow_status"] in ("失败", "下载失败")
                or r["generation_command"]
                or r["flow_error"]
                or int(r["flow_retry_count"] or 0) > 0
            )
        ]
        ids = {r["segment_id"] for r in rows}
        with connect() as con:
            states = {r["segment_id"]: dict(r) for r in con.execute("SELECT * FROM flow_recovery") if r["segment_id"] in ids}
        channels = [dict(c) for c in repo.list_channel_pool(enabled_only=True) if c["collection_url"]]
        with connect() as con:
            errors = {}
            for r in con.execute("SELECT segment_id,error FROM flow_dispatches WHERE coalesce(error,'')<>'' ORDER BY id"):
                if r["segment_id"] in ids:
                    errors[r["segment_id"]] = r["error"]
            for row in rows:
                if not row.get("flow_error") and row["flow_status"] in ("失败", "下载失败"):
                    row["flow_error"] = errors.get(row["segment_id"], "")
        records = []
        for row in rows:
            sid = row["segment_id"]
            label, count, reason, detail = error_view(row, states.get(sid, {}))
            records.append(
                dict(
                    sid=sid,
                    channel=str(row["flow_channel_key"] or ""),
                    detail=detail,
                    values=(
                        str(sid),
                        f"{row['recipient_name']} / {row['host_name']}",
                        f"{row['video_seq']} / {row['seg_seq']}",
                        "",
                        label,
                        str(count),
                        reason,
                        "修改提示词并重试" if needs_prompt(row) else "重置并重试",
                    ),
                )
            )
        retry_count = sum(
            row["flow_status"] in ("失败", "下载失败") and not needs_prompt(row) and not upload_skipped(row)
            for row in rows
        )
        return rows, states, channels, records, retry_count

    def set_initial_filter(self, mode: str) -> None:
        if mode in self._filter_btns:
            self._set_filter_mode(mode)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.timer.start()
        self.visual_timer.start()
        self.refresh(force=True)

    def hideEvent(self, event) -> None:
        self.timer.stop()
        self.visual_timer.stop()
        super().hideEvent(event)

    def refresh(self, force: bool = False) -> None:
        day = work_dates.active()
        if self._view_day != day:
            self._checked.clear()
            self._last_clicked_sid = None
            self._expanded_hosts.clear()
            self._manually_toggled_hosts.clear()
            self._queued_snapshot = None
            self._view_day = day
        self.reader.request(day)
        if force and self._queued_snapshot is not None:
            self._flush_snapshot()

    def _on_snapshot_ready(self, day: str, result: dict, error: str) -> None:
        if error or day != work_dates.active():
            return
        self._queued_snapshot = (day, result)
        if self._snapshot is None:
            self._flush_snapshot()

    def _flush_snapshot(self) -> None:
        if not self._queued_snapshot or not self.isVisible():
            return
        if QApplication.activePopupWidget() is not None:
            return
        vbar = self.scroll.verticalScrollBar()
        if vbar is not None and vbar.isSliderDown():
            return
        day, snap = self._queued_snapshot
        self._queued_snapshot = None
        if day != work_dates.active():
            return
        self._snapshot = snap
        self._reclassify_snapshot_in_place()
        self._apply_snapshot()

    def _reclassify_snapshot_in_place(self) -> None:
        if not self._snapshot:
            return
        for rec in self._snapshot.get("recipients") or []:
            for h in rec.get("hosts") or []:
                for v in h.get("videos") or []:
                    for s in v.get("segments") or []:
                        s.update(task_recovery.classify_runtime_segment(s, self._stall_minutes))

    def _on_stall_threshold_changed(self) -> None:
        mins = int(self.stall_combo.currentData() or 10)
        self._stall_minutes = mins
        try:
            repo.set_setting("flow_runtime_stall_minutes", str(mins))
        except Exception:
            pass
        if self._snapshot is not None:
            self._reclassify_snapshot_in_place()
            self._apply_snapshot()

    def _set_filter_mode(self, mode: str) -> None:
        self._filter_mode = mode
        for m, btn in self._filter_btns.items():
            btn.blockSignals(True)
            btn.setChecked(m == mode)
            btn.blockSignals(False)
        self._apply_snapshot()

    def _on_filter_changed(self) -> None:
        self._apply_snapshot()

    def _populate_batch_channel_combo(self, channels: list[dict]) -> None:
        prev = self.batch_channel_combo.currentData()
        sig = tuple((c["channel_key"], c["online"], c["busy"]) for c in channels)
        if getattr(self, "_batch_combo_sig", None) == sig and self.batch_channel_combo.count() > 0:
            return
        self._batch_combo_sig = sig
        self.batch_channel_combo.blockSignals(True)
        self.batch_channel_combo.clear()
        self.batch_channel_combo.addItem("🤖 自动分配空闲通道", "__AUTO__")
        self.batch_channel_combo.addItem("📌 保持原通道", "__KEEP__")
        for c in channels:
            ck = str(c["channel_key"])
            if not c.get("online"):
                st = "⚪离线"
            elif c.get("busy"):
                st = "🔵运行"
            else:
                st = "🟢空闲"
            self.batch_channel_combo.addItem(f"🎯 {ck} ({st})", ck)
        idx = self.batch_channel_combo.findData(prev) if prev else 0
        self.batch_channel_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.batch_channel_combo.blockSignals(False)

    def _seg_matches_filter(self, seg: dict, host: dict, rec: dict, needle: str) -> bool:
        cat = str(seg.get("category") or "running")
        fm = self._filter_mode
        if fm == "stalled" and cat != "stalled":
            return False
        if fm == "failed" and cat != "failed":
            return False
        if fm == "upload_skipped" and cat != "upload_skipped":
            return False
        if fm == "needs_prompt" and cat != "needs_prompt":
            return False
        if fm == "running" and cat not in ("running", "queued_retry"):
            return False
        if needle:
            code_dash = f"{int(seg['video_seq']):02d}-{int(seg['seg_seq']):02d}"
            code_slash = f"{int(seg['video_seq'])}/{int(seg['seg_seq'])}"
            hay = " ".join(
                (
                    str(rec.get("recipient_name") or ""),
                    str(host.get("host_name") or ""),
                    code_dash,
                    code_slash,
                    str(seg.get("segment_id") or ""),
                    str(seg.get("flow_channel_key") or ""),
                    str(seg.get("badge") or ""),
                    str(seg.get("reason") or ""),
                    str(seg.get("flow_error") or ""),
                    str(seg.get("prompt") or "")[:120],
                )
            ).lower()
            if needle not in hay:
                return False
        return True

    def _host_pixmap(self, hid: int, raw_path: str) -> QPixmap:
        if self.owner is not None:
            owner_cache = getattr(self.owner, "_view_cache", None)
            if isinstance(owner_cache, dict):
                imgs = owner_cache.get("images") or {}
                if hid in imgs:
                    ikey, qimg = imgs[hid]
                    cached = self._thumb_cache.get(hid)
                    if cached and cached[0] == ikey:
                        return cached[1]
                    if qimg is not None and not qimg.isNull():
                        pm = _rounded_portrait_pixmap(qimg)
                        self._thumb_cache[hid] = (ikey, pm)
                        return pm
        raw = str(raw_path or "").strip()
        if not raw:
            return QPixmap()
        ikey = image_assets.image_cache_key(raw)
        cached = self._thumb_cache.get(hid)
        if cached and cached[0] == ikey:
            return cached[1]
        try:
            qimg = image_assets.read_image(raw)
            if not qimg.isNull():
                dpr = max(1.0, float(self.devicePixelRatioF() or 1.0))
                tw, th = int(46 * dpr), int(66 * dpr)
                scaled = qimg.scaled(tw, th, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                if scaled.width() > tw or scaled.height() > th:
                    scaled = scaled.copy(
                        max(0, (scaled.width() - tw) // 2),
                        max(0, (scaled.height() - th) // 2),
                        min(tw, scaled.width()),
                        min(th, scaled.height()),
                    )
                scaled.setDevicePixelRatio(dpr)
                pm = _rounded_portrait_pixmap(scaled)
                self._thumb_cache[hid] = (ikey, pm)
                return pm
        except Exception:
            pass
        return QPixmap()

    def _check_state_for_sids(self, sids: list[int]) -> Qt.CheckState:
        if not sids:
            return Qt.Unchecked
        hit = sum(1 for sid in sids if sid in self._checked)
        if hit <= 0:
            return Qt.Unchecked
        if hit >= len(sids):
            return Qt.Checked
        return Qt.PartiallyChecked

    # ── Snapshot Rendering ──
    @measured("task_list_refresh")
    def _apply_snapshot(self) -> None:
        snap = self._snapshot
        if not snap:
            return

        channels = snap.get("channels") or []
        self._populate_batch_channel_combo(channels)
        channel_keys = [str(c["channel_key"]) for c in channels]

        # Rebuild global segment index & counts
        seg_index: dict[int, dict] = {}
        counts = {
            "all": 0,
            "stalled": 0,
            "failed": 0,
            "upload_skipped": 0,
            "needs_prompt": 0,
            "running": 0,
        }
        abnormal_host_ids: list[int] = []

        for rec in snap.get("recipients") or []:
            for h in rec.get("hosts") or []:
                h_has_issue = False
                for v in h.get("videos") or []:
                    for s in v.get("segments") or []:
                        sid = int(s["segment_id"])
                        seg_index[sid] = s
                        counts["all"] += 1
                        cat = str(s.get("category") or "running")
                        if cat in ("running", "queued_retry"):
                            counts["running"] += 1
                        elif cat in counts:
                            counts[cat] += 1
                        if cat in ("stalled", "failed", "upload_skipped", "needs_prompt"):
                            h_has_issue = True
                if h_has_issue:
                    abnormal_host_ids.append(int(h["host_id"]))

        self._seg_index = seg_index
        self._tasks = seg_index
        self._checked.intersection_update(seg_index.keys())

        # Auto-expand abnormal/stalled hosts on first load when manageable (<= 6 hosts)
        if abnormal_host_ids and not self._manually_toggled_hosts and not self._expanded_hosts:
            if len(abnormal_host_ids) <= 6:
                self._expanded_hosts.update(abnormal_host_ids)

        day_txt = str(snap.get("work_date") or work_dates.active())
        _set_text(
            self.title_lbl,
            f"{day_txt}  ·  未完 {counts['all']} 段",
        )

        pill_texts = {
            "all": f"全部 {counts['all']}",
            "stalled": f"⏳ 卡住 {counts['stalled']}",
            "failed": f"⚠ 失败 {counts['failed']}",
            "upload_skipped": f"🖼 跳过 {counts['upload_skipped']}",
            "needs_prompt": f"📝 改词 {counts['needs_prompt']}",
            "running": f"● 运行 {counts['running']}",
        }
        for k, txt in pill_texts.items():
            btn = self._filter_btns.get(k)
            if btn:
                _set_text(btn, txt)
                if k in ("upload_skipped", "needs_prompt"):
                    btn.setVisible(counts[k] > 0 or self._filter_mode == k)

        _set_text(self.btn_select_stalled, f"⚡ 选卡住 ({counts['stalled']})")
        self.btn_select_stalled.setEnabled(counts["stalled"] > 0 and not self._retry_busy)
        self.btn_select_stalled.setVisible(counts["stalled"] > 0)

        fail_selectable = counts["failed"] + counts["upload_skipped"]
        _set_text(self.btn_select_failed, f"⚡ 选失败 ({fail_selectable})")
        self.btn_select_failed.setEnabled(fail_selectable > 0 and not self._retry_busy)
        self.btn_select_failed.setVisible(fail_selectable > 0)

        needle = self.search_edit.text().strip().lower()
        auto_expand = bool(needle) or self._filter_mode in ("stalled", "failed", "upload_skipped", "needs_prompt")

        visible_rec_cards: list[QWidget] = []
        ordered_visible_sids: list[int] = []
        alive_rids: set[int] = set()

        for rec_data in snap.get("recipients") or []:
            rid = int(rec_data["recipient_id"])
            alive_rids.add(rid)

            filtered_hosts = []
            rec_visible_sids: list[int] = []
            rec_stalled = 0
            rec_failed = 0
            rec_running = 0

            for h_data in rec_data.get("hosts") or []:
                f_videos = []
                h_sids: list[int] = []
                h_cats = {"stalled": 0, "failed": 0, "upload_skipped": 0, "needs_prompt": 0, "running": 0, "queued_retry": 0}
                h_max_elapsed = 0

                for v_data in h_data.get("videos") or []:
                    # Compute whole-host stats from unfiltered segments, filter for display
                    for raw_s in v_data.get("segments") or []:
                        rcat = str(raw_s.get("category") or "running")
                        h_cats[rcat] = h_cats.get(rcat, 0) + 1
                        h_max_elapsed = max(h_max_elapsed, int(raw_s.get("elapsed_seconds") or 0))
                    f_segs = [
                        s for s in (v_data.get("segments") or [])
                        if self._seg_matches_filter(s, h_data, rec_data, needle)
                    ]
                    if f_segs:
                        f_videos.append({**v_data, "segments": f_segs})
                        for s in f_segs:
                            sid = int(s["segment_id"])
                            h_sids.append(sid)
                            ordered_visible_sids.append(sid)

                if f_videos:
                    rec_visible_sids.extend(h_sids)
                    rec_stalled += h_cats["stalled"]
                    rec_failed += h_cats["failed"] + h_cats["upload_skipped"] + h_cats["needs_prompt"]
                    rec_running += h_cats["running"] + h_cats["queued_retry"]
                    filtered_hosts.append((h_data, f_videos, h_sids, h_cats, h_max_elapsed))

            r_entry = self._ensure_recipient_widget(rid)
            if not filtered_hosts:
                r_entry["card"].hide()
                continue

            rname = str(rec_data.get("recipient_name") or "未命名接收人")
            _set_text(r_entry["avatar"], rname[:1])
            _set_text(r_entry["title"], rname)

            r_tot = max(1, int(rec_data.get("total_all_segments") or len(rec_visible_sids) or 1))
            r_done = int(rec_data.get("done_all_segments") or 0)
            r_pct = int(round(100.0 * r_done / r_tot))

            if rec_failed > 0:
                r_tone = "failed"
                r_badge = f"⚠ {rec_failed}" + (f" · ⏳ {rec_stalled}" if rec_stalled else "")
            elif rec_stalled > 0:
                r_tone = "prio"
                r_badge = f"⏳ {rec_stalled}"
            else:
                r_tone = "running"
                r_badge = f"● {rec_running}"

            r_meta = f"👤 {len(filtered_hosts)}   🎞 {r_done}/{rec_data.get('total_all_segments', r_tot)}"
            r_tip = (
                f"涉及 {len(filtered_hosts)} 位主播 · "
                f"当前显示 {len(rec_visible_sids)} 个未完片段 · "
                f"整体已完成 {r_done}/{rec_data.get('total_all_segments', r_tot)}"
            )
            _set_text(r_entry["badge"], r_badge, tip=r_tip)
            r_entry["meta"].set_raw_text(r_meta, tooltip=r_tip)
            r_bar: QProgressBar = r_entry["bar"]
            if r_bar.maximum() != r_tot:
                r_bar.setRange(0, r_tot)
            if r_bar.value() != r_done:
                r_bar.setValue(r_done)
            _set_text(r_entry["pct"], f"{r_pct}%")

            for wk in ("card", "avatar", "badge", "bar", "pct"):
                _set_prop(r_entry[wk], "tone", r_tone)

            r_chk: QCheckBox = r_entry["check"]
            r_chk.blockSignals(True)
            r_chk.setCheckState(self._check_state_for_sids(rec_visible_sids))
            r_chk.setEnabled(bool(rec_visible_sids))
            r_chk.blockSignals(False)
            r_entry["selectable_sids"] = rec_visible_sids

            collapsed = bool(self._collapsed_recipients.get(rid, False))
            _set_prop(r_entry["head"], "collapsed", "true" if collapsed else "false")
            _set_text(r_entry["chevron"], "▾" if collapsed else "▴", tip="展开或收起该接收人")

            visible_host_cards: list[QWidget] = []
            visible_drawers: list[QWidget] = []
            alive_hids = {int(h["host_id"]) for h, *_ in filtered_hosts}
            for dead_hid in [k for k in list(r_entry["hosts"]) if k not in alive_hids]:
                r_entry["hosts"][dead_hid]["card"].hide()
                if r_entry["hosts"][dead_hid].get("drawer"):
                    r_entry["hosts"][dead_hid]["drawer"].hide()

            for h_data, f_videos, h_sids, h_cats, h_max_el in filtered_hosts:
                hid = int(h_data["host_id"])
                h_entry = self._ensure_host_widget(r_entry, hid)
                h_entry["selectable_sids"] = h_sids

                # Quick-retry targets on the host card: stalled + failed + upload_skipped first, else all visible sids
                issue_sids = [
                    sid for sid in h_sids
                    if str((seg_index.get(sid) or {}).get("category") or "") in ("stalled", "failed", "upload_skipped")
                ]
                h_entry["quick_retry_sids"] = issue_sids if issue_sids else list(h_sids)

                h_chk_state = self._check_state_for_sids(h_sids)
                h_chk: QCheckBox = h_entry["check"]
                h_chk.blockSignals(True)
                h_chk.setCheckState(h_chk_state)
                h_chk.setEnabled(bool(h_sids))
                h_chk.blockSignals(False)

                pm = self._host_pixmap(hid, str(h_data.get("image_path") or ""))
                if not pm.isNull():
                    h_entry["thumb"].setText("")
                    h_entry["thumb"].setPixmap(pm)
                else:
                    h_entry["thumb"].setPixmap(QPixmap())
                    h_entry["thumb"].setText("无图")

                h_tot = max(1, int(h_data.get("total_all_segments") or len(h_sids) or 1))
                h_done = int(h_data.get("done_all_segments") or 0)

                h_entry["title"].set_raw_text(h_data["host_name"])
                h_entry["badge"].hide()

                parts = []
                if h_cats["stalled"]:
                    parts.append(f"⏳ 卡住 {h_cats['stalled']}")
                if h_cats["failed"] + h_cats["upload_skipped"]:
                    parts.append(f"⚠ 失败 {h_cats['failed'] + h_cats['upload_skipped']}")
                if h_cats["needs_prompt"]:
                    parts.append(f"📝 改词 {h_cats['needs_prompt']}")
                if h_cats["running"] + h_cats["queued_retry"]:
                    parts.append(f"● 运行 {h_cats['running'] + h_cats['queued_retry']}")
                mid_left = " · ".join(parts) if parts else f"未完 {len(h_sids)}"
                mid_right = (
                    f"⏳ {task_recovery.format_elapsed_cn(h_max_el)}"
                    if h_max_el > 0
                    else f"🎞 {h_done}/{h_data.get('total_all_segments', h_tot)}"
                )
                _set_text(h_entry["vid_meta"], mid_left)
                _set_text(h_entry["seg_meta"], mid_right)

                hbar: QProgressBar = h_entry["bar"]
                if hbar.maximum() != h_tot:
                    hbar.setRange(0, h_tot)
                if hbar.value() != h_done:
                    hbar.setValue(h_done)

                is_expanded = (hid in self._expanded_hosts) or (auto_expand and hid not in self._manually_toggled_hosts)
                h_fail_all = h_cats["failed"] + h_cats["upload_skipped"] + h_cats["needs_prompt"]
                if h_fail_all > 0:
                    h_tone = "failed"
                elif h_cats["stalled"] > 0:
                    h_tone = "prio"
                else:
                    h_tone = "running"

                _set_prop(h_entry["card"], "tone", h_tone)
                _set_prop(h_entry["card"], "expanded", "true" if is_expanded else "false")
                _set_prop(h_entry["card"], "checkedState", "full" if h_chk_state == Qt.Checked else "none")
                _set_prop(hbar, "tone", h_tone)
                h_entry["state"].hide()

                q_btn: QPushButton = h_entry["retry_btn"]
                if issue_sids:
                    _set_text(q_btn, f"↻ {len(issue_sids)}", tip=f"一键重置并重试该主播名下的 {len(issue_sids)} 个异常/卡住任务")
                    _set_prop(q_btn, "kind", "warn" if h_cats["stalled"] > 0 else "retry")
                else:
                    _set_text(q_btn, f"↻ {len(h_sids)}", tip=f"强制重置并重试该主播名下的 {len(h_sids)} 个任务")
                    _set_prop(q_btn, "kind", "retry")
                q_btn.setEnabled(bool(h_entry["quick_retry_sids"]) and not self._retry_busy)

                _set_text(h_entry["expand_btn"], "▴" if is_expanded else "▾", tip="展开或收起任务明细")
                _set_prop(h_entry["expand_btn"], "active", "true" if is_expanded else "false")

                visible_host_cards.append(h_entry["card"])

                if is_expanded and not collapsed:
                    drawer = self._sync_host_drawer(r_entry, h_entry, h_data, f_videos, h_sids, issue_sids, channel_keys)
                    visible_drawers.append(drawer)
                elif h_entry.get("drawer") is not None:
                    h_entry["drawer"].hide()

            grid_changed = _reorder_widgets(r_entry["grid"], visible_host_cards)
            if grid_changed:
                r_entry["grid"].invalidate()
            r_entry["grid_wrap"].setVisible(not collapsed)
            if not collapsed:
                r_entry["grid_wrap"].sync_height()

            _reorder_widgets(r_entry["drawers_layout"], visible_drawers)
            r_entry["drawers_wrap"].setVisible((not collapsed) and bool(visible_drawers))
            visible_rec_cards.append(r_entry["card"])

        for dead_rid in [k for k in list(self._rec_widgets) if k not in alive_rids]:
            dead = self._rec_widgets.pop(dead_rid)
            self.cards_layout.removeWidget(dead["card"])
            dead["card"].hide()
            dead["card"].deleteLater()

        self._visible_ordered_sids = ordered_visible_sids

        if not visible_rec_cards:
            empty_msg = (
                "当前工作日期没有运行中或待重试的任务 🎉"
                if counts["all"] == 0
                else "当前筛选或搜索条件下没有匹配的任务"
            )
            _set_text(self.empty_label, empty_msg)
            self.empty_label.show()
            _reorder_widgets(self.cards_layout, [self.empty_label])
        else:
            self.empty_label.hide()
            _reorder_widgets(self.cards_layout, visible_rec_cards)

        self._refresh_footer()

    # ── Widget Builders & Recyclers ──
    def _ensure_recipient_widget(self, rid: int) -> dict:
        entry = self._rec_widgets.get(rid)
        if entry is not None:
            return entry

        card = QFrame(self.scroll_content, objectName="flowRecipientCard")
        box = QVBoxLayout(card)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)

        head_frame = _ClickableFrame(card)
        head_frame.setObjectName("flowRecipientHead")
        head_frame.setCursor(Qt.PointingHandCursor)
        head_frame.clicked.connect(lambda _mods, r=rid: self._toggle_recipient_collapse(r))

        head = QHBoxLayout(head_frame)
        head.setContentsMargins(14, 9, 14, 9)
        head.setSpacing(10)

        chk = QCheckBox()
        chk.setTristate(True)
        chk.setCursor(Qt.PointingHandCursor)
        chk.setToolTip("勾选 / 取消该接收人名下所有显示的未完成任务")
        head.addWidget(chk)

        avatar = QLabel(objectName="flowRecAvatar")
        avatar.setFixedSize(30, 30)
        avatar.setAlignment(Qt.AlignCenter)
        head.addWidget(avatar)

        rec_name = QLabel(objectName="flowRecName")
        rec_name.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        head.addWidget(rec_name)

        rec_badge = QLabel(objectName="flowRecBadge")
        rec_badge.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        head.addWidget(rec_badge)

        rec_meta = _ElidingLabel("flowRecMeta", min_w=60)
        head.addWidget(rec_meta, 1)

        rec_bar = QProgressBar(objectName="flowRecBar")
        rec_bar.setFixedSize(110, 6)
        rec_bar.setTextVisible(False)
        head.addWidget(rec_bar)

        rec_pct = QLabel(objectName="flowRecPct")
        rec_pct.setMinimumWidth(38)
        rec_pct.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        head.addWidget(rec_pct)

        chevron = QLabel("▴", objectName="flowRecChevron")
        chevron.setFixedHeight(22)
        chevron.setMinimumWidth(26)
        chevron.setAlignment(Qt.AlignCenter)
        head.addWidget(chevron)

        box.addWidget(head_frame)

        grid = CardGrid(minimum=320, maximum=520, card_height=84)
        grid_wrap = _GridBody(card, grid)
        box.addWidget(grid_wrap)

        drawers_wrap = QWidget(card)
        drawers_lay = QVBoxLayout(drawers_wrap)
        drawers_lay.setContentsMargins(12, 0, 12, 12)
        drawers_lay.setSpacing(10)
        box.addWidget(drawers_wrap)
        drawers_wrap.hide()

        entry = {
            "card": card,
            "head": head_frame,
            "check": chk,
            "avatar": avatar,
            "title": rec_name,
            "badge": rec_badge,
            "meta": rec_meta,
            "bar": rec_bar,
            "pct": rec_pct,
            "chevron": chevron,
            "grid": grid,
            "grid_wrap": grid_wrap,
            "drawers_wrap": drawers_wrap,
            "drawers_layout": drawers_lay,
            "hosts": {},
            "selectable_sids": [],
        }
        chk.clicked.connect(lambda _=False, e=entry: self._toggle_group_sids(list(e["selectable_sids"])))
        self._rec_widgets[rid] = entry
        return entry

    def _ensure_host_widget(self, r_entry: dict, hid: int) -> dict:
        existing = r_entry["hosts"].get(hid)
        if existing is not None:
            return existing

        card = _ClickableFrame(r_entry["grid_wrap"])
        card.setObjectName("flowHostCard")
        card.setFixedHeight(84)
        card.setCursor(Qt.PointingHandCursor)
        card.clicked.connect(lambda _mods, h=hid: self._toggle_host_drawer(h))

        outer = QHBoxLayout(card)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(8)

        chk = QCheckBox()
        chk.setTristate(True)
        chk.setCursor(Qt.PointingHandCursor)
        chk.setToolTip("勾选 / 取消该 AI 主播所有未完成片段")
        outer.addWidget(chk, 0, Qt.AlignVCenter)

        thumb = QLabel("无图", objectName="flowHostThumb")
        thumb.setFixedSize(46, 66)
        thumb.setAlignment(Qt.AlignCenter)
        outer.addWidget(thumb, 0, Qt.AlignVCenter)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(6)
        title = _ElidingLabel("flowHostTitle", min_w=60)
        top.addWidget(title, 1)

        badge = QLabel("未完 0 段", objectName="dlChip")
        badge.hide()
        top.addWidget(badge)

        import_btn = QPushButton("📤", objectName="rtHostMiniBtn")
        import_btn.setProperty("iconOnly", "true")
        import_btn.setProperty("kind", "import")
        import_btn.setCursor(Qt.PointingHandCursor)
        import_btn.setFocusPolicy(Qt.NoFocus)
        import_btn.setToolTip("从外部按序号批量导入该主播的视频片段")
        import_btn.clicked.connect(lambda _=False, h=hid: self._open_host_import_dialog(h))
        top.addWidget(import_btn)

        retry_btn = QPushButton("↻ 1", objectName="rtHostMiniBtn")
        retry_btn.setProperty("kind", "retry")
        retry_btn.setCursor(Qt.PointingHandCursor)
        retry_btn.setFocusPolicy(Qt.NoFocus)
        retry_btn.setToolTip("一键重置并重试该主播名下的异常/卡住任务")
        top.addWidget(retry_btn)

        expand_btn = QPushButton("▾", objectName="rtHostMiniBtn")
        expand_btn.setProperty("iconOnly", "true")
        expand_btn.setCursor(Qt.PointingHandCursor)
        expand_btn.setFocusPolicy(Qt.NoFocus)
        expand_btn.setToolTip("展开或收起任务明细")
        expand_btn.clicked.connect(lambda _=False, h=hid: self._toggle_host_drawer(h))
        top.addWidget(expand_btn)
        right.addLayout(top)

        mid = QHBoxLayout()
        mid.setSpacing(6)
        vid_meta = QLabel(objectName="flowHostVideoMeta")
        mid.addWidget(vid_meta)
        mid.addStretch(1)
        seg_meta = QLabel(objectName="flowHostSegMeta")
        mid.addWidget(seg_meta)
        right.addLayout(mid)

        bar = QProgressBar(objectName="flowHostBar")
        bar.setFixedHeight(5)
        bar.setTextVisible(False)
        right.addWidget(bar)

        state = _ElidingLabel("flowHostState", min_w=40)
        state.hide()
        right.addWidget(state)
        outer.addLayout(right, 1)

        h_entry = {
            "card": card,
            "check": chk,
            "thumb": thumb,
            "title": title,
            "badge": badge,
            "vid_meta": vid_meta,
            "seg_meta": seg_meta,
            "bar": bar,
            "state": state,
            "retry_btn": retry_btn,
            "expand_btn": expand_btn,
            "selectable_sids": [],
            "quick_retry_sids": [],
            "drawer": None,
            "video_widgets": {},
        }
        chk.clicked.connect(lambda _=False, e=h_entry: self._toggle_group_sids(list(e["selectable_sids"])))
        retry_btn.clicked.connect(lambda _=False, e=h_entry: self._confirm_and_retry_sids(list(e["quick_retry_sids"])))
        r_entry["hosts"][hid] = h_entry
        return h_entry

    def _sync_host_drawer(
        self,
        r_entry: dict,
        h_entry: dict,
        h_data: dict,
        f_videos: list[dict],
        h_sids: list[int],
        issue_sids: list[int],
        channel_keys: list[str],
    ) -> QFrame:
        hid = int(h_data["host_id"])
        drawer = h_entry.get("drawer")
        if drawer is None:
            drawer = QFrame(r_entry["drawers_wrap"], objectName="dlHostDrawer")
            d_lay = QVBoxLayout(drawer)
            d_lay.setContentsMargins(0, 0, 0, 10)
            d_lay.setSpacing(8)

            d_head = QFrame(drawer, objectName="dlHostDrawerHead")
            dh_lay = QHBoxLayout(d_head)
            dh_lay.setContentsMargins(12, 8, 12, 8)
            dh_lay.setSpacing(8)

            d_title = QLabel(objectName="dlHostDrawerTitle")
            dh_lay.addWidget(d_title, 1)

            btn_imp_host = QPushButton("📤 按序号导入本主播", objectName="rtHostMiniBtn")
            btn_imp_host.setProperty("kind", "import")
            btn_imp_host.setCursor(Qt.PointingHandCursor)
            btn_imp_host.setToolTip("从外部选择多个视频或文件夹，按序号批量导入该主播的视频片段")
            btn_imp_host.clicked.connect(lambda _=False, h=hid: self._open_host_import_dialog(h))
            dh_lay.addWidget(btn_imp_host)

            btn_sel_issue = QPushButton("⚡ 选异常", objectName="rtHostMiniBtn")
            btn_sel_issue.setProperty("kind", "warn")
            btn_sel_issue.setCursor(Qt.PointingHandCursor)
            btn_sel_issue.setToolTip("勾选该主播名下所有异常或卡住片段")
            btn_sel_issue.clicked.connect(
                lambda _=False, e=h_entry: self._select_specific_sids(list(e["quick_retry_sids"]))
            )
            dh_lay.addWidget(btn_sel_issue)

            btn_sel_host = QPushButton("全选", objectName="rtHostMiniBtn")
            btn_sel_host.setCursor(Qt.PointingHandCursor)
            btn_sel_host.setToolTip("全选或取消全选该主播的所有片段")
            btn_sel_host.clicked.connect(lambda _=False, e=h_entry: self._toggle_group_sids(list(e["selectable_sids"])))
            dh_lay.addWidget(btn_sel_host)

            btn_fold = QPushButton("▴", objectName="rtHostMiniBtn")
            btn_fold.setProperty("iconOnly", "true")
            btn_fold.setCursor(Qt.PointingHandCursor)
            btn_fold.setToolTip("收起该主播的任务明细")
            btn_fold.clicked.connect(lambda _=False, h=hid: self._toggle_host_drawer(h))
            dh_lay.addWidget(btn_fold)

            d_lay.addWidget(d_head)

            v_container = QWidget(drawer)
            vc_lay = QVBoxLayout(v_container)
            vc_lay.setContentsMargins(10, 2, 10, 0)
            vc_lay.setSpacing(8)
            d_lay.addWidget(v_container)

            h_entry["drawer"] = drawer
            h_entry["drawer_title"] = d_title
            h_entry["drawer_sel_issue_btn"] = btn_sel_issue
            h_entry["drawer_videos_layout"] = vc_lay

        _set_text(
            h_entry["drawer_title"],
            f"🎬 {h_data['host_name']}  ·  🎬 {len(f_videos)}   🎞 {len(h_sids)}",
            tip=f"主播 {h_data['host_name']}：当前显示 {len(f_videos)} 条视频、{len(h_sids)} 个未完片段（支持按住 Shift 连选）",
        )
        h_entry["drawer_sel_issue_btn"].setVisible(bool(issue_sids))

        vw_map: dict[int, dict] = h_entry["video_widgets"]
        alive_vids = {int(v["video_id"]) for v in f_videos}
        for dead_vid in [k for k in list(vw_map) if k not in alive_vids]:
            vw_map[dead_vid]["box"].hide()

        visible_v_boxes: list[QWidget] = []
        for v_data in f_videos:
            vid = int(v_data["video_id"])
            v_entry = vw_map.get(vid)
            if v_entry is None:
                vbox = QFrame(drawer, objectName="dlVideoGroup")
                vb_lay = QVBoxLayout(vbox)
                vb_lay.setContentsMargins(0, 0, 0, 2)
                vb_lay.setSpacing(0)

                vhead = _ClickableFrame(vbox)
                vhead.setObjectName("dlVideoHead")
                vhead.setCursor(Qt.PointingHandCursor)
                vh_lay = QHBoxLayout(vhead)
                vh_lay.setContentsMargins(10, 6, 10, 6)
                vh_lay.setSpacing(8)

                vchk = QCheckBox()
                vchk.setTristate(True)
                vchk.setCursor(Qt.PointingHandCursor)
                vh_lay.addWidget(vchk)

                vtitle = QLabel(objectName="dlVideoTitle")
                vh_lay.addWidget(vtitle)

                vmeta = QLabel(objectName="dlChip")
                vmeta.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
                vh_lay.addWidget(vmeta)
                vh_lay.addStretch(1)

                v_import_btn = QPushButton("📤", objectName="rtHostMiniBtn")
                v_import_btn.setProperty("iconOnly", "true")
                v_import_btn.setProperty("kind", "import")
                v_import_btn.setCursor(Qt.PointingHandCursor)
                v_import_btn.setFocusPolicy(Qt.NoFocus)
                v_import_btn.setToolTip("从外部按序号批量导入该条视频的所有片段")
                v_import_btn.clicked.connect(lambda _=False, v_id=vid: self._open_video_import_dialog(v_id))
                vh_lay.addWidget(v_import_btn)

                v_img_btn = QPushButton("🖼", objectName="rtHostMiniBtn")
                v_img_btn.setProperty("iconOnly", "true")
                v_img_btn.setCursor(Qt.PointingHandCursor)
                v_img_btn.setFocusPolicy(Qt.NoFocus)
                v_img_btn.setToolTip("查看该视频绑定的参考图片")
                vh_lay.addWidget(v_img_btn)

                v_abandon_btn = QPushButton("🗑", objectName="rtHostMiniBtn")
                v_abandon_btn.setProperty("iconOnly", "true")
                v_abandon_btn.setProperty("kind", "danger")
                v_abandon_btn.setCursor(Qt.PointingHandCursor)
                v_abandon_btn.setFocusPolicy(Qt.NoFocus)
                v_abandon_btn.setToolTip("放弃整条视频（不再继续生成或进入剪辑）")
                vh_lay.addWidget(v_abandon_btn)

                vb_lay.addWidget(vhead)

                s_wrap = QWidget(vbox)
                sw_lay = QVBoxLayout(s_wrap)
                sw_lay.setContentsMargins(0, 0, 0, 0)
                sw_lay.setSpacing(0)
                vb_lay.addWidget(s_wrap)

                v_entry = {
                    "box": vbox,
                    "check": vchk,
                    "title": vtitle,
                    "meta": vmeta,
                    "img_btn": v_img_btn,
                    "abandon_btn": v_abandon_btn,
                    "segs_layout": sw_lay,
                    "seg_rows": {},
                    "selectable_sids": [],
                    "first_sid": 0,
                }
                vchk.clicked.connect(lambda _=False, ve=v_entry: self._toggle_group_sids(list(ve["selectable_sids"])))
                vhead.clicked.connect(lambda _mods, ve=v_entry: self._toggle_group_sids(list(ve["selectable_sids"])))
                v_img_btn.clicked.connect(lambda _=False, ve=v_entry: self.view_image_by_sid(int(ve["first_sid"])))
                v_abandon_btn.clicked.connect(lambda _=False, ve=v_entry: self.abandon_video_by_sid(int(ve["first_sid"])))
                vw_map[vid] = v_entry

            segs = v_data.get("segments") or []
            v_sids = [int(s["segment_id"]) for s in segs]
            v_entry["selectable_sids"] = v_sids
            v_entry["first_sid"] = v_sids[0] if v_sids else 0

            v_chk: QCheckBox = v_entry["check"]
            v_chk.blockSignals(True)
            v_chk.setCheckState(self._check_state_for_sids(v_sids))
            v_chk.setEnabled(bool(v_sids))
            v_chk.blockSignals(False)

            _set_text(v_entry["title"], f"🎬 #{int(v_data['video_seq']):02d}")
            _set_text(v_entry["meta"], f"未完 {len(segs)}")
            v_entry["abandon_btn"].setEnabled(bool(v_sids) and not self._retry_busy)

            sr_map: dict[int, dict] = v_entry["seg_rows"]
            alive_sids = set(v_sids)
            for dead_sid in [k for k in list(sr_map) if k not in alive_sids]:
                sr_map[dead_sid]["row"].hide()

            visible_s_rows: list[QWidget] = []
            for seg in segs:
                sid = int(seg["segment_id"])
                s_row = sr_map.get(sid)
                if s_row is None:
                    rframe = _ClickableFrame(v_entry["box"])
                    rframe.setObjectName("rtSegRow")
                    rframe.setCursor(Qt.PointingHandCursor)
                    rlay = QHBoxLayout(rframe)
                    rlay.setContentsMargins(14, 6, 10, 6)
                    rlay.setSpacing(8)

                    schk = QCheckBox()
                    schk.setCursor(Qt.PointingHandCursor)
                    rlay.addWidget(schk)

                    scode = QLabel(objectName="dlSegCode")
                    scode.setMinimumWidth(56)
                    scode.setAlignment(Qt.AlignCenter)
                    rlay.addWidget(scode)

                    ch_combo = _NoWheelCombo()
                    ch_combo.setObjectName("rtChannelCombo")
                    ch_combo.setMinimumWidth(88)
                    ch_combo.setMaximumWidth(108)
                    ch_combo.setToolTip("为该片段单独指定重试通道（选择「自动分配」可避开原卡死通道）")
                    rlay.addWidget(ch_combo)

                    sbadge = QLabel(objectName="rtStatusBadge")
                    sbadge.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
                    rlay.addWidget(sbadge)

                    sreason = _ElidingLabel("dlSegFile", min_w=120)
                    rlay.addWidget(sreason, 1)

                    btn_import = QPushButton("📤", objectName="rtHostMiniBtn")
                    btn_import.setProperty("iconOnly", "true")
                    btn_import.setProperty("kind", "import")
                    btn_import.setCursor(Qt.PointingHandCursor)
                    btn_import.setFocusPolicy(Qt.NoFocus)
                    btn_import.setToolTip("手动导入外部视频文件到此片段（直接完成该片段）")
                    rlay.addWidget(btn_import)

                    btn_retry = QPushButton("↻", objectName="rtHostMiniBtn")
                    btn_retry.setProperty("iconOnly", "true")
                    btn_retry.setProperty("kind", "retry")
                    btn_retry.setCursor(Qt.PointingHandCursor)
                    btn_retry.setFocusPolicy(Qt.NoFocus)
                    btn_retry.setToolTip("重置并重试该片段")
                    rlay.addWidget(btn_retry)

                    btn_prompt = QPushButton("✎", objectName="rtHostMiniBtn")
                    btn_prompt.setProperty("iconOnly", "true")
                    btn_prompt.setCursor(Qt.PointingHandCursor)
                    btn_prompt.setFocusPolicy(Qt.NoFocus)
                    btn_prompt.setToolTip("修改提示词并重试")
                    rlay.addWidget(btn_prompt)

                    btn_img = QPushButton("🖼", objectName="rtHostMiniBtn")
                    btn_img.setProperty("iconOnly", "true")
                    btn_img.setCursor(Qt.PointingHandCursor)
                    btn_img.setFocusPolicy(Qt.NoFocus)
                    btn_img.setToolTip("查看参考图片")
                    rlay.addWidget(btn_img)

                    btn_detail = QPushButton("查看详情", objectName="dvErrDetailBtn")
                    btn_detail.setCursor(Qt.PointingHandCursor)
                    btn_detail.setFocusPolicy(Qt.NoFocus)
                    btn_detail.setToolTip("查看中文错误原因分析与建议解决办法")
                    rlay.addWidget(btn_detail)

                    s_row = {
                        "row": rframe,
                        "check": schk,
                        "code": scode,
                        "channel": ch_combo,
                        "badge": sbadge,
                        "reason": sreason,
                        "btn_import": btn_import,
                        "btn_retry": btn_retry,
                        "btn_prompt": btn_prompt,
                        "btn_img": btn_img,
                        "btn_detail": btn_detail,
                        "combo_sig": None,
                    }
                    schk.clicked.connect(
                        lambda _=False, s_id=sid: self._on_seg_clicked(s_id, QApplication.keyboardModifiers())
                    )
                    rframe.clicked.connect(lambda mods, s_id=sid: self._on_seg_clicked(s_id, mods))
                    ch_combo.currentIndexChanged.connect(
                        lambda _idx, s_id=sid, cb=ch_combo: self._on_row_channel_changed(s_id, cb)
                    )
                    btn_import.clicked.connect(lambda _=False, s_id=sid: self._import_single_segment(s_id))
                    btn_retry.clicked.connect(lambda _=False, s_id=sid: self._retry_single_sid(s_id, edit_prompt=False))
                    btn_prompt.clicked.connect(lambda _=False, s_id=sid: self._retry_single_sid(s_id, edit_prompt=True))
                    btn_img.clicked.connect(lambda _=False, s_id=sid: self.view_image_by_sid(s_id))
                    btn_detail.clicked.connect(lambda _=False, s_id=sid: self.show_details_by_sid(s_id))
                    sr_map[sid] = s_row

                is_checked = sid in self._checked
                schk: QCheckBox = s_row["check"]
                schk.blockSignals(True)
                schk.setChecked(is_checked)
                schk.blockSignals(False)

                _set_prop(s_row["row"], "checked", "true" if is_checked else "false")
                _set_prop(s_row["row"], "tone", str(seg.get("tone") or "running"))

                seg_code_txt = f"{int(seg['video_seq']):02d}-{int(seg['seg_seq']):02d}"
                _set_text(s_row["code"], seg_code_txt)

                # Sync inline channel combo
                cur_choice = self.channel_choices.get(sid)
                eff_ch = (
                    cur_choice
                    if cur_choice is not None
                    else (str(seg.get("flow_channel_key") or seg.get("preferred_channel") or ""))
                )
                csig = (tuple(channel_keys), eff_ch)
                cb: QComboBox = s_row["channel"]
                if s_row["combo_sig"] != csig:
                    s_row["combo_sig"] = csig
                    cb.blockSignals(True)
                    cb.clear()
                    cb.addItem("自动分配", "")
                    seen_cks = set()
                    for ck in channel_keys:
                        seen_cks.add(ck)
                        cb.addItem(ck, ck)
                    if eff_ch and eff_ch not in seen_cks:
                        cb.addItem(f"{eff_ch} (原)", eff_ch)
                    idx_c = cb.findData(eff_ch)
                    cb.setCurrentIndex(idx_c if idx_c >= 0 else 0)
                    cb.blockSignals(False)

                _set_text(s_row["badge"], str(seg.get("badge") or ""))
                _set_prop(s_row["badge"], "tone", str(seg.get("tone") or "running"))

                raw_err = str(seg.get("flow_error") or "").strip()
                reason_txt = str(seg.get("reason") or "")
                prompt_snip = str(seg.get("prompt") or "").strip().replace("\n", " ")
                cat = str(seg.get("category") or "running")

                err_info = None
                if raw_err or cat in ("failed", "upload_skipped", "needs_prompt"):
                    err_info = diagnose_flow_error(
                        raw_err,
                        status=str(seg.get("flow_status") or "失败"),
                        channel_key=str(seg.get("flow_channel_key") or ""),
                        host_name=str(seg.get("host_name") or ""),
                        seg_code=seg_code_txt,
                        retry_count=int(seg.get("flow_retry_count") or 0),
                    )
                    display_line = err_info.inline_text
                else:
                    display_line = reason_txt

                full_tip = (
                    f"任务 ID: {sid}  |  视频 {int(seg['video_seq']):02d} - 片段 {int(seg['seg_seq']):02d}\n"
                    f"当前状态: {seg.get('badge')}  |  当前通道: {seg.get('flow_channel_key') or '待分配'}  |  已重试: {seg.get('flow_retry_count', 0)} 次\n"
                    + (
                        f"中文原因: {err_info.title}\n说明: {err_info.cause}\n建议: {err_info.solutions[0] if err_info.solutions else ''}\n"
                        if err_info
                        else f"状态说明: {reason_txt}\n"
                    )
                    + (f"内部原始码: {raw_err}\n" if raw_err else "")
                    + f"提示词预览: {prompt_snip[:240]}"
                )
                s_row["reason"].set_raw_text(display_line, tooltip=full_tip)

                if cat == "needs_prompt":
                    _set_text(s_row["btn_retry"], "↻", tip="按原提示词强制重试该片段")
                    _set_prop(s_row["btn_retry"], "kind", "normal")
                    _set_prop(s_row["btn_prompt"], "kind", "warn")
                elif cat == "stalled":
                    _set_text(s_row["btn_retry"], "↻", tip="强制重置并重试该卡住片段")
                    _set_prop(s_row["btn_retry"], "kind", "warn")
                    _set_prop(s_row["btn_prompt"], "kind", "normal")
                else:
                    _set_text(s_row["btn_retry"], "↻", tip="重置并重试该片段")
                    _set_prop(s_row["btn_retry"], "kind", "retry")
                    _set_prop(s_row["btn_prompt"], "kind", "normal")

                s_row["btn_retry"].setEnabled(not self._retry_busy)
                s_row["btn_prompt"].setEnabled(not self._retry_busy)

                visible_s_rows.append(s_row["row"])

            _reorder_widgets(v_entry["segs_layout"], visible_s_rows)
            visible_v_boxes.append(v_entry["box"])

        _reorder_widgets(h_entry["drawer_videos_layout"], visible_v_boxes)
        drawer.show()
        return drawer

    # ── Selection & Toggle Handlers ──
    def _on_row_channel_changed(self, sid: int, combo: QComboBox) -> None:
        self.channel_choices[int(sid)] = str(combo.currentData() or "")

    def _toggle_recipient_collapse(self, rid: int) -> None:
        self._collapsed_recipients[rid] = not bool(self._collapsed_recipients.get(rid, False))
        self._apply_snapshot()

    def _toggle_host_drawer(self, hid: int) -> None:
        self._manually_toggled_hosts.add(hid)
        if hid in self._expanded_hosts:
            self._expanded_hosts.remove(hid)
        else:
            self._expanded_hosts.add(hid)
        self._apply_snapshot()

    def _toggle_group_sids(self, sids: list[int]) -> None:
        if not sids:
            return
        all_in = all(sid in self._checked for sid in sids)
        if all_in:
            self._checked.difference_update(sids)
        else:
            self._checked.update(sids)
        self._last_clicked_sid = sids[-1]
        self._apply_snapshot()

    def _select_specific_sids(self, sids: list[int]) -> None:
        if not sids:
            return
        self._checked.update(sids)
        self._last_clicked_sid = sids[-1]
        self._apply_snapshot()

    def _on_seg_clicked(self, sid: int, modifiers) -> None:
        if sid not in self._seg_index:
            return
        shift = bool(modifiers & Qt.ShiftModifier) if modifiers is not None else False
        if shift and self._last_clicked_sid in self._visible_ordered_sids and sid in self._visible_ordered_sids:
            i1 = self._visible_ordered_sids.index(self._last_clicked_sid)
            i2 = self._visible_ordered_sids.index(sid)
            lo, hi = (i1, i2) if i1 <= i2 else (i2, i1)
            target_add = sid not in self._checked
            for rng_sid in self._visible_ordered_sids[lo : hi + 1]:
                if target_add:
                    self._checked.add(rng_sid)
                else:
                    self._checked.discard(rng_sid)
        else:
            if sid in self._checked:
                self._checked.discard(sid)
            else:
                self._checked.add(sid)
        self._last_clicked_sid = sid
        self._apply_snapshot()

    def _select_visible(self, select: bool) -> None:
        if select:
            self._checked.update(self._visible_ordered_sids)
        else:
            self._checked.clear()
        self._apply_snapshot()

    def _select_all_stalled(self) -> None:
        stalled_sids = [
            sid for sid, seg in self._seg_index.items()
            if seg.get("category") == "stalled"
        ]
        if not stalled_sids:
            QMessageBox.information(self, "一键选疑似卡住", "当前没有超过卡住判定阈值的运行中任务。")
            return
        self._checked = set(stalled_sids)
        for sid in stalled_sids:
            hid = int((self._seg_index.get(sid) or {}).get("host_id") or 0)
            if hid:
                self._expanded_hosts.add(hid)
        self._apply_snapshot()

    def _select_all_failed(self) -> None:
        failed_sids = [
            sid for sid, seg in self._seg_index.items()
            if seg.get("category") in ("failed", "upload_skipped")
        ]
        if not failed_sids:
            QMessageBox.information(self, "一键选失败/跳过", "当前没有可直接批量重试的失败或上传跳过任务。")
            return
        self._checked = set(failed_sids)
        for sid in failed_sids:
            hid = int((self._seg_index.get(sid) or {}).get("host_id") or 0)
            if hid:
                self._expanded_hosts.add(hid)
        self._apply_snapshot()

    def _refresh_footer(self) -> None:
        valid_checked = [sid for sid in self._checked if sid in self._seg_index]
        n = len(valid_checked)
        if n == 0:
            _set_text(self.sel_summary_lbl, "已选 0 段")
            self.batch_retry_btn.setEnabled(False)
            _set_text(self.batch_retry_btn, "↻ 重置重试")
            self.btn_batch_abandon.setEnabled(False)
            return

        n_run = sum(
            1 for sid in valid_checked
            if str(self._seg_index[sid].get("flow_status") or "") in ("已准备", "已提交", "生成中", "下载中")
        )
        n_fail = sum(
            1 for sid in valid_checked
            if self._seg_index[sid].get("category") in ("failed", "upload_skipped")
        )
        n_prompt = sum(
            1 for sid in valid_checked
            if self._seg_index[sid].get("category") == "needs_prompt"
        )
        detail_parts = []
        if n_run:
            detail_parts.append(f"⏳ {n_run}")
        if n_fail:
            detail_parts.append(f"⚠ {n_fail}")
        if n_prompt:
            detail_parts.append(f"📝 {n_prompt}")
        suffix = f"（{' · '.join(detail_parts)}）" if detail_parts else ""
        _set_text(self.sel_summary_lbl, f"已选 {n} 段{suffix}")

        self.batch_retry_btn.setEnabled(not self._retry_busy)
        _set_text(self.batch_retry_btn, f"↻ 重置重试 ({n})")
        self.btn_batch_abandon.setEnabled(not self._retry_busy)

    # ── Channel Resolution for Retries ──
    def _resolve_target_channel(self, sid: int, use_batch_routing: bool) -> str | None:
        """Return '' for automatic idle-channel allocation, or a specific channel_key."""
        snap_channels = {str(c["channel_key"]) for c in (self._snapshot or {}).get("channels") or []}
        seg = self._seg_index.get(sid) or {}

        if use_batch_routing:
            mode = str(self.batch_channel_combo.currentData() or "__AUTO__")
            if mode == "__AUTO__":
                # Honor explicit per-row override if user specifically set one; otherwise auto-allocate
                if sid in self.channel_choices:
                    manual = str(self.channel_choices[sid] or "")
                    return manual if (not manual or manual in snap_channels) else ""
                return ""
            if mode == "__KEEP__":
                cand = str(
                    self.channel_choices.get(sid)
                    if sid in self.channel_choices
                    else (seg.get("flow_channel_key") or seg.get("preferred_channel") or "")
                )
                return cand if cand in snap_channels else ""
            if mode in snap_channels:
                return mode
            return ""

        # Single-row retry: honor inline combo selection
        if sid in self.channel_choices:
            manual = str(self.channel_choices[sid] or "")
            return manual if (not manual or manual in snap_channels) else ""
        cand = str(seg.get("flow_channel_key") or seg.get("preferred_channel") or "")
        return cand if cand in snap_channels else ""

    # ── Single & Batch Retry Execution ──
    def _set_busy(self, busy: bool) -> None:
        self._retry_busy = busy
        self._refresh_footer()

    def _retry_single_sid(self, sid: int, edit_prompt: bool = False) -> None:
        if self._retry_busy:
            return
        seg = self._seg_index.get(int(sid))
        if not seg:
            return
        day = work_dates.active()
        target_ch = self._resolve_target_channel(int(sid), use_batch_routing=False)
        status = str(seg.get("flow_status") or "")
        is_running = status in ("已准备", "已提交", "生成中", "下载中")

        new_prompt = None
        if edit_prompt:
            dialog = QDialog(self)
            dialog.setWindowTitle(
                f"修改提示词并重试 · {seg.get('host_name', '')} · 视频{int(seg['video_seq']):02d}-片段{int(seg['seg_seq']):02d}"
            )
            dialog.resize(760, 520)
            lay = QVBoxLayout(dialog)
            if is_running:
                warn = QLabel(
                    f"⚠ 当前片段处于「{status}」状态。点击「保存并强制重置重试」将立即中断旧通道命令（迟到的旧生成结果会自动丢弃），并使用修改后的提示词重新生成。"
                )
                warn.setWordWrap(True)
                warn.setStyleSheet("color:#D97706; font-weight:700; padding:4px 0;")
                lay.addWidget(warn)
            else:
                lay.addWidget(QLabel("修改提示词后将重新排入通道生成："))

            editor = QPlainTextEdit(str(seg.get("prompt") or ""))
            editor.setLineWrapMode(QPlainTextEdit.WidgetWidth)
            editor.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
            editor.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            lay.addWidget(editor, 1)

            buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            buttons.button(QDialogButtonBox.Ok).setText("保存并强制重置重试" if is_running else "保存并重试")
            buttons.button(QDialogButtonBox.Cancel).setText("取消")
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            lay.addWidget(buttons)

            if dialog.exec() != QDialog.Accepted:
                return
            new_prompt = editor.toPlainText().strip()
            if not new_prompt:
                QMessageBox.warning(self, "修改提示词", "提示词不能为空。")
                return
            if needs_prompt(seg) and new_prompt == str(seg.get("prompt") or "").strip():
                QMessageBox.warning(self, "修改提示词", "该任务因提示词违规/格式被拒，请先修改提示词内容后再保存重试。")
                return
        else:
            if is_running:
                dur = task_recovery.format_elapsed_cn(int(seg.get("elapsed_seconds") or 0))
                ch_desc = f"通道 {target_ch}" if target_ch else "自动分配空闲通道"
                if (
                    QMessageBox.question(
                        self,
                        "强制重置运行中任务",
                        f"确定强制重置并重新生成「{seg.get('host_name')} · {int(seg['video_seq']):02d}-{int(seg['seg_seq']):02d}」？\n\n"
                        f"• 当前状态：{status}" + (f"（已运行 {dur}）" if dur else "") + "\n"
                        f"• 重试分配：{ch_desc}\n"
                        "• 旧命令将被解绑释放，网页若稍后返回迟到视频也会自动丢弃。",
                    )
                    != QMessageBox.Yes
                ):
                    return
            elif upload_skipped(seg):
                if (
                    QMessageBox.question(
                        self,
                        "重新上传图片并重试",
                        "该任务的参考图片此前上传 3 次失败已跳过。\n确定重新上传参考图片并重试？",
                    )
                    != QMessageBox.Yes
                ):
                    return

        self._execute_batch_reset(day, [(int(sid), target_ch, new_prompt)], allow_running_prompt=bool(edit_prompt))

    def batch_retry_selected(self) -> None:
        sids = [sid for sid in self._visible_ordered_sids if sid in self._checked]
        for sid in sorted(self._checked):
            if sid in self._seg_index and sid not in sids:
                sids.append(sid)
        self._confirm_and_retry_sids(sids)

    # Alias for legacy callers
    def batch_retry(self) -> None:
        if self._checked:
            self.batch_retry_selected()
        else:
            self._select_all_failed()
            if self._checked:
                self.batch_retry_selected()

    def _confirm_and_retry_sids(self, sids: list[int]) -> None:
        if self._retry_busy:
            return
        valid_sids = [int(sid) for sid in sids if int(sid) in self._seg_index]
        if not valid_sids:
            QMessageBox.information(self, "批量重置并重试", "请先勾选需要重试的任务片段。")
            return

        snap_channels = (self._snapshot or {}).get("channels") or []
        if not snap_channels:
            QMessageBox.warning(self, "无可用通道", "当前没有已启用且填写了链接的通道，请先在「运行通道」配置通道。")
            return

        prompt_blocked = [sid for sid in valid_sids if self._seg_index[sid].get("category") == "needs_prompt"]
        normal_targets = [sid for sid in valid_sids if sid not in prompt_blocked]

        # If ONLY 1 prompt-blocked task was selected, open the prompt editor directly for smooth UX
        if len(valid_sids) == 1 and len(prompt_blocked) == 1:
            self._retry_single_sid(prompt_blocked[0], edit_prompt=True)
            return

        if prompt_blocked and not normal_targets:
            res = QMessageBox.question(
                self,
                "包含需修改提示词的任务",
                f"你选中的 {len(prompt_blocked)} 个片段均被标记为「需修改提示词」（提示词违规或格式异常）。\n\n"
                "建议展开明细逐条点击「✎ 改词重试」；如果你确认无需改词、想直接按原提示词强制重跑，是否继续？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if res != QMessageBox.Yes:
                return
            chosen_sids = prompt_blocked
        else:
            chosen_sids = normal_targets
            skipped_prompt_count = len(prompt_blocked)
            from app.ui.confirm_dialog import ask_confirm
            if ask_confirm(
                self,
                "确认重置并重试",
                f"确认重置并重试选中的 {len(chosen_sids)} 个片段吗？",
                subtext=f"已自动跳过 {skipped_prompt_count} 个需改提示词片段" if skipped_prompt_count else "",
                confirm_text="确认重试",
                cancel_text="取消",
                icon_text="↻",
            ) != "confirm":
                return

        day = work_dates.active()
        candidates = [
            (sid, self._resolve_target_channel(sid, use_batch_routing=True), None)
            for sid in chosen_sids
        ]
        self._execute_batch_reset(day, candidates, allow_running_prompt=False)

    def _execute_batch_reset(
        self,
        day: str,
        candidates: list[tuple[int, str | None, str | None]],
        allow_running_prompt: bool = False,
    ) -> None:
        if not candidates or self.owner is None:
            return
        self._set_busy(True)
        bridge = self.owner.bridge

        def execute(_):
            if day != work_dates.active():
                raise ValueError("当前工作日期已变化，请刷新后再操作")
            return task_recovery.reset_tasks_batch(
                candidates,
                bridge,
                day=day,
                allow_running_prompt=allow_running_prompt,
            )

        def finished(result, error):
            self._set_busy(False)
            if error:
                QMessageBox.warning(self, "重置重试失败", translate_common_exception_cn(error))
                return
            ok = result.get("ok") or []
            errors = result.get("errors") or []
            released = result.get("released_channels") or []
            if ok:
                self._checked.difference_update(ok)
                bridge.request_progress_scan()
                self.owner.dispatch_redo()
                self.owner.auto_dispatch_tick()
                self.refresh(force=True)
            rel_txt = f" · 已释放通道 {', '.join(released)}" if released else ""
            banner = f"✓ 已重置 {len(ok)} 个片段并加入自动派发队列{rel_txt}"
            if errors:
                banner += f"（另有 {len(errors)} 个跳过）"
            _set_text(self.status_banner_lbl, banner)
            if errors:
                QMessageBox.information(
                    self,
                    "批量重试结果",
                    f"成功加入重试队列 {len(ok)} 个任务{rel_txt}。\n\n以下任务未重置：\n" + "\n".join(errors[:10]),
                )

        self.owner._production_lane.submit(("retry-write", id(self)), execute, None, finished)

    # ── Details, Image Preview, and Abandon Handlers ──
    def show_details_by_sid(self, sid: int) -> None:
        seg = self._seg_index.get(int(sid))
        if not seg:
            return
        with connect() as con:
            attempts = [
                dict(r)
                for r in con.execute(
                    "SELECT command_id, channel_key, status, stage, created_at, submitted_at, error "
                    "FROM flow_dispatches WHERE segment_id=? ORDER BY id DESC LIMIT 8",
                    (int(sid),),
                )
            ]
        elapsed_txt = task_recovery.format_elapsed_cn(int(seg.get("elapsed_seconds") or 0))
        seg_code = f"{int(seg['video_seq']):02d}-{int(seg['seg_seq']):02d}"
        raw_err = str(seg.get("flow_error") or "").strip()
        status = str(seg.get("flow_status") or "待生成")
        cat = str(seg.get("category") or "running")
        ch_key = str(seg.get("flow_channel_key") or "")
        host_name = str(seg.get("host_name") or "")
        rec_name = str(seg.get("recipient_name") or "")
        retry_cnt = int(seg.get("flow_retry_count") or 0)

        history_lines = []
        for a in attempts:
            a_err = str(a.get("error") or "").strip()
            a_err_cn = (
                f"{diagnose_flow_error(a_err, status='失败').title} ({a_err})"
                if a_err
                else "正常 / 无报错"
            )
            history_lines.append(
                f"{a.get('created_at') or '-'} | {a.get('channel_key') or '-'} | {a['command_id']} | "
                f"{a['status']}({a.get('stage') or '-'}) | {a_err_cn}"
            )
        history_block = "\n".join(history_lines) if history_lines else "暂无派发记录"

        full_raw_box = (
            f"任务 ID：{sid}  |  接收人：{rec_name}  |  主播：{host_name}  |  片段：{seg_code}\n"
            f"当前状态：{seg.get('badge') or status}  |  当前通道：{ch_key or '未分配'}  |  已耗时：{elapsed_txt}  |  已重试：{retry_cnt} 次\n"
            f"内部原始错误码：{raw_err or '（无）'}\n"
            f"绑定参考图：{seg.get('image_path') or '无'}\n"
            f"当前提示词：{str(seg.get('prompt') or '').strip()}\n\n"
            f"最近派发记录：\n{history_block}"
        )

        loc_items: list[tuple[str, str]] = [
            ("所属主播", f"{rec_name} · {host_name}"),
            ("视频片段", f"#{seg_code}（任务 ID: {sid}）"),
            ("当前通道", ch_key or "待分配"),
        ]
        if retry_cnt > 0 or elapsed_txt:
            loc_items.append(("运行记录", f"已重试 {retry_cnt} 次  ·  已耗时 {elapsed_txt}"))

        if raw_err or cat in ("failed", "upload_skipped", "needs_prompt"):
            base_info = diagnose_flow_error(
                raw_err,
                status=status,
                channel_key=ch_key,
                host_name=host_name,
                seg_code=seg_code,
                retry_count=retry_cnt,
            )
            info = EditingErrorInfo(
                code=base_info.code,
                stage_label=base_info.stage_label,
                title=base_info.title,
                inline_text=base_info.inline_text,
                cause=base_info.cause,
                location_items=base_info.location_items or loc_items,
                solutions=list(base_info.solutions),
                raw_error=full_raw_box,
            )
        elif cat == "stalled":
            info = EditingErrorInfo(
                code="STALLED_TASK",
                stage_label="Flow 网页执行超时预警",
                title=f"当前任务处于「{status}」已超过 {elapsed_txt}，疑似网页卡住",
                inline_text="网页端长时间未返回结果，建议重置并换空闲通道重试",
                cause=(
                    f"该片段在通道 {ch_key or '当前通道'} 上处于「{status}」状态已持续 {elapsed_txt}，"
                    "超过了设定的卡住判定阈值。通常是 Flow 网页标签页假死、网络断流或排队卡住导致。"
                ),
                location_items=loc_items,
                solutions=[
                    "直接点击该行右侧的「↻」按钮（或勾选后点底部「↻ 重置重试」），系统会自动解绑原卡死通道并改派给空闲健康通道；",
                    "如果该通道连续多条任务卡住，请切到对应的 Chrome 浏览器窗口刷新一下 Flow 页面。",
                ],
                raw_error=full_raw_box,
            )
        else:
            info = EditingErrorInfo(
                code="RUNNING_TASK",
                stage_label="Flow 任务运行状态",
                title=f"当前任务正在正常执行中（{seg.get('badge') or status}）",
                inline_text="任务正在网页通道正常排队或生成中",
                cause=(
                    f"该片段当前状态为「{status}」，已运行 {elapsed_txt}，尚未发现报错。"
                    "如果觉得等待时间过长，也可以随时手动强制重置重试。"
                ),
                location_items=loc_items,
                solutions=[
                    "当前无需干预，保持浏览器窗口开启等待生成完成即可；",
                    "如需立即换通道重跑，可点击右侧「↻」按钮强制重置。",
                ],
                raw_error=full_raw_box,
            )

        dlg = EditingErrorDetailDialog(
            info,
            parent=self,
            context_title=f"{rec_name} · {host_name} · 片段 {seg_code}",
        )
        dlg.exec()

    def view_image_by_sid(self, sid: int) -> None:
        seg = self._seg_index.get(int(sid))
        if not seg:
            return
        path = str(seg.get("image_path") or "").strip()
        if not path:
            QMessageBox.information(self, "查看参考图", "这个任务没有绑定参考图片。")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(
            f"任务参考图 · {seg.get('host_name', '')} · 视频 {int(seg['video_seq']):02d}"
        )
        dialog.resize(760, 760)
        lay = QVBoxLayout(dialog)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        view = QLabel()
        view.setAlignment(Qt.AlignCenter)
        scroll.setWidget(view)
        lay.addWidget(scroll, 1)

        info = QLabel(objectName="muted")
        info.setWordWrap(True)
        info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(info)

        file_obj = Path(path).expanduser()
        pixmap = QPixmap(str(file_obj)) if file_obj.is_file() else QPixmap()
        if pixmap.isNull():
            view.setText("图片不存在或无法读取")
            info.setText(path)
        else:
            view.setPixmap(pixmap.scaled(720, 640, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            info.setText(f"{path}\n原始尺寸 {pixmap.width()} × {pixmap.height()}")

        def open_system():
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(file_obj))):
                QMessageBox.information(dialog, "打开图片", "无法用系统程序打开这张图片。")

        def reveal():
            if sys.platform == "darwin" and file_obj.exists():
                subprocess.Popen(["open", "-R", str(file_obj)])
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(file_obj.parent)))

        row = QHBoxLayout()
        for txt, cb in (("用系统预览打开", open_system), ("在访达中显示", reveal)):
            b = QPushButton(txt)
            b.clicked.connect(cb)
            row.addWidget(b)
        row.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(dialog.accept)
        row.addWidget(close_btn)
        lay.addLayout(row)
        dialog.exec()

    def abandon_video_by_sid(self, sid: int) -> None:
        if not sid or self._retry_busy:
            return
        self._confirm_and_abandon_sids([int(sid)])

    def abandon_selected_batch(self) -> None:
        if self._retry_busy:
            return
        sids = [sid for sid in self._checked if sid in self._seg_index]
        if not sids:
            QMessageBox.information(self, "放弃视频", "请先勾选要放弃的任务片段。")
            return
        self._confirm_and_abandon_sids(sids)

    def _confirm_and_abandon_sids(self, sids: list[int]) -> None:
        if not sids or self.owner is None:
            return
        scopes = []
        seen_vids = set()
        for sid in sids:
            try:
                vid, seq, host, seg_ids, done = task_recovery.video_abandon_scope(int(sid))
                if vid not in seen_vids:
                    seen_vids.add(vid)
                    scopes.append((vid, seq, host, seg_ids, done, int(sid)))
            except ValueError:
                continue
        if not scopes:
            QMessageBox.warning(self, "放弃整条视频", "所选任务不存在或状态已变化，请刷新后再试。")
            return

        total_pending = sum(len(sc[3]) for sc in scopes)
        total_done = sum(int(sc[4]) for sc in scopes)
        preview_lines = [f"• {sc[2]} · 视频 {int(sc[1]):02d}（未完成 {len(sc[3])} 段）" for sc in scopes[:8]]
        if len(scopes) > 8:
            preview_lines.append(f"…等共 {len(scopes)} 条视频")

        msg = (
            f"确定放弃以下 {len(scopes)} 条完整视频（共涉及 {total_pending} 个未完成片段）？\n\n"
            + "\n".join(preview_lines)
            + "\n\n"
            + (f"• 已完成的 {total_done} 个片段本地文件会保留，但这些视频不会再进入剪辑\n" if total_done else "")
            + "• 正在运行中的通道命令会立即解绑，迟到的旧结果不会重新加入任务\n"
            + "• 原参考图、提示词和错误日志均会保留"
        )
        if QMessageBox.question(self, "确认放弃整条视频", msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return

        day = work_dates.active()
        rep_sids = [sc[5] for sc in scopes]
        self._set_busy(True)

        def execute(_):
            if day != work_dates.active():
                raise ValueError("当前工作日期已变化，请刷新")
            return task_recovery.abandon_videos_batch(rep_sids, self.owner.bridge, day)

        def finished(result, error):
            self._set_busy(False)
            if error:
                QMessageBox.warning(self, "放弃视频失败", str(error))
                return
            v_cnt = int((result or {}).get("abandoned_videos") or 0)
            s_cnt = int((result or {}).get("abandoned_segments") or 0)
            failed = (result or {}).get("failed") or []
            self._checked.clear()
            _set_text(self.status_banner_lbl, f"🗑 已放弃 {v_cnt} 条视频（共 {s_cnt} 个片段）")
            if failed:
                QMessageBox.information(
                    self,
                    "放弃整条视频",
                    f"已放弃 {v_cnt} 条视频；另有 {len(failed)} 项状态刚刚变化未处理，请刷新查看。",
                )
            self.refresh(force=True)
            self.owner.auto_dispatch_tick()

        self.owner._production_lane.submit(("abandon-batch", id(self)), execute, None, finished)

    # ── Manual External Video Import Actions ──────────────────────────────

    def _on_manual_import_finished(self, res: dict | None) -> None:
        if not res or not int(res.get("imported") or 0):
            return
        cnt = int(res.get("imported") or 0)
        for sid in res.get("segment_ids") or []:
            self._checked.discard(int(sid))
        _set_text(self.status_banner_lbl, f"✓ 已手动导入 {cnt} 个外部视频片段")
        self.refresh(force=True)
        if self.owner is not None and hasattr(self.owner, "refresh_data"):
            try:
                self.owner.refresh_data()
            except Exception:
                pass

    def _import_single_segment(self, sid: int) -> None:
        res = import_single_segment_interactive(
            self,
            sid,
            bridge=getattr(self.owner, "bridge", None),
            auto_pass_qc=True,
        )
        self._on_manual_import_finished(res)

    def _open_video_import_dialog(self, vid: int) -> None:
        dlg = ManualVideoImportDialog(
            self,
            scope="video",
            target_id=int(vid),
            bridge=getattr(self.owner, "bridge", None),
        )
        if dlg.exec() == QDialog.Accepted:
            self._on_manual_import_finished(dlg.import_result)

    def _open_host_import_dialog(self, hid: int) -> None:
        dlg = ManualVideoImportDialog(
            self,
            scope="host",
            target_id=int(hid),
            bridge=getattr(self.owner, "bridge", None),
        )
        if dlg.exec() == QDialog.Accepted:
            self._on_manual_import_finished(dlg.import_result)

