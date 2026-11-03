"""Downloaded-videos manager for Flow Generation Center.

Organizes completed downloads into Recipient -> AI Host cards matching the
visual language of ``生产进度`` (``flow_monitor_cards.py``), with inline
expandable Video -> Segment drawers, multi-level selection (Recipient / Host /
Video / Segment + Shift range), local file health inspection, and pure
cloud re-download (0 prompt changes, 0 re-generation, 0 credit spend).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.core import repository as repo
from app.core import work_dates
from app.services import flow_redownload, image_assets
from app.ui.flow_layouts import CardGrid
from app.ui.manual_video_import_dialog import (
    ManualVideoImportDialog,
    import_single_segment_interactive,
)
from app.ui.read_snapshot import SnapshotReader


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


def _format_size(num_bytes: int) -> str:
    b = int(num_bytes or 0)
    if b <= 0:
        return "0 B"
    if b < 1024 * 1024:
        return f"{b / 1024.0:.0f} KB"
    return f"{b / (1024.0 * 1024.0):.1f} MB"


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
            # Ignore clicks on embedded buttons or checkboxes
            w = child
            while w is not None and w is not self:
                if isinstance(w, (QPushButton, QCheckBox)):
                    super().mouseReleaseEvent(event)
                    return
                w = w.parentWidget()
            self.clicked.emit(event.modifiers())
        super().mouseReleaseEvent(event)


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


class DownloadedVideosDialog(QDialog):
    """Host-card grouped manager for completed Flow downloads with batch re-download."""

    def __init__(self, owner=None):
        super().__init__(owner)
        self.owner = owner
        self.setWindowTitle("下载完成管理 · 按主播查看与重新下载")
        self.resize(1120, 740)

        self._checked: set[int] = set()
        self._last_clicked_sid: int | None = None
        self._filter_mode: str = "all"
        self._expanded_hosts: set[int] = set()
        self._collapsed_recipients: dict[int, bool] = {}
        self._snapshot: dict | None = None
        self._seg_index: dict[int, dict] = {}
        self._visible_ordered_sids: list[int] = []
        self._rec_widgets: dict[int, dict] = {}
        self._thumb_cache: dict[int, tuple[object, QPixmap]] = {}
        self._busy_submitting = False

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        # ── 1. Top Title + Search Bar ──
        head = QHBoxLayout()
        head.setSpacing(10)
        self.title_lbl = QLabel("下载完成管理", objectName="sectionTitle")
        self.title_lbl.setToolTip("纯拉取原云端视频覆盖保存 · 不改提示词 · 不重新生成")
        head.addWidget(self.title_lbl)
        self.sub_hint = QLabel("", objectName="muted")
        self.sub_hint.hide()
        head.addWidget(self.sub_hint)
        head.addStretch(1)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍 搜索主播 / 编号 / 通道")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMinimumWidth(220)
        self.search_edit.textChanged.connect(self._on_filter_changed)
        head.addWidget(self.search_edit)
        root.addLayout(head)

        # ── 2. Filter Pills + Batch Selection Actions ──
        bar = QHBoxLayout()
        bar.setSpacing(6)
        self._filter_btns: dict[str, QPushButton] = {}
        for mode, init_txt, tip_txt in (
            ("all", "全部 0", "显示全部已下载片段"),
            ("missing", "⚠ 0", "本地视频缺失或 0 字节损坏"),
            ("redownloading", "↓ 0", "正在重新下载中的片段"),
        ):
            pill = QPushButton(init_txt, objectName="flowProgFilterPill")
            pill.setCheckable(True)
            pill.setChecked(mode == "all")
            pill.setProperty("pillKind", "failed" if mode == "missing" else ("running" if mode == "redownloading" else "all"))
            pill.setCursor(Qt.PointingHandCursor)
            pill.setFocusPolicy(Qt.NoFocus)
            pill.setToolTip(tip_txt)
            pill.clicked.connect(lambda _=False, m=mode: self._set_filter_mode(m))
            self._filter_btns[mode] = pill
            bar.addWidget(pill)

        bar.addSpacing(6)
        self.btn_select_all = QPushButton("全选")
        self.btn_select_all.setCursor(Qt.PointingHandCursor)
        self.btn_select_all.setToolTip("全选当前列表中的所有可重下片段")
        self.btn_select_all.clicked.connect(lambda: self._select_visible(True))
        bar.addWidget(self.btn_select_all)

        self.btn_clear_sel = QPushButton("清空")
        self.btn_clear_sel.setCursor(Qt.PointingHandCursor)
        self.btn_clear_sel.setToolTip("清空当前所有勾选")
        self.btn_clear_sel.clicked.connect(lambda: self._select_visible(False))
        bar.addWidget(self.btn_clear_sel)

        self.btn_select_missing = QPushButton("⚡ 勾选缺失")
        self.btn_select_missing.setCursor(Qt.PointingHandCursor)
        self.btn_select_missing.setToolTip("自动勾选当前所有本地缺失或损坏的片段")
        self.btn_select_missing.clicked.connect(self._select_all_missing)
        self.btn_select_missing.hide()
        bar.addWidget(self.btn_select_missing)

        bar.addStretch(1)

        self.btn_open_dir = QPushButton("📂", objectName="dlIconBtn")
        self.btn_open_dir.setCursor(Qt.PointingHandCursor)
        self.btn_open_dir.setToolTip("打开下载目录")
        self.btn_open_dir.clicked.connect(self._open_channels_root)
        bar.addWidget(self.btn_open_dir)

        self.btn_refresh = QPushButton("↻", objectName="dlIconBtn")
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.setToolTip("刷新列表")
        self.btn_refresh.clicked.connect(lambda: self.refresh_data(force=True))
        bar.addWidget(self.btn_refresh)
        root.addLayout(bar)

        # ── 3. Main Scroll Area (Recipient Cards -> Host Cards -> Inline Detail Drawers) ──
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

        self.empty_label = QLabel("当前工作日期暂无已下载完成的片段", self.scroll_content, objectName="flowMonitorEmpty")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setMinimumHeight(120)
        self.empty_label.hide()

        # ── 4. Footer Bar ──
        foot = QHBoxLayout()
        foot.setSpacing(10)
        self.sel_summary_lbl = QLabel("已选 0 个片段", objectName="cardMeta")
        foot.addWidget(self.sel_summary_lbl)
        self.status_banner_lbl = QLabel("", objectName="muted")
        foot.addWidget(self.status_banner_lbl, 1)

        close_btn = QPushButton("关闭")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(self.close)
        foot.addWidget(close_btn)

        self.btn_batch_redownload = QPushButton("↓ 批量重新下载选中项", objectName="primaryBtn")
        self.btn_batch_redownload.setCursor(Qt.PointingHandCursor)
        self.btn_batch_redownload.setEnabled(False)
        self.btn_batch_redownload.clicked.connect(self._on_batch_redownload_clicked)
        foot.addWidget(self.btn_batch_redownload)
        root.addLayout(foot)

        # Background Snapshot Reader + 2s Live Timer
        self.reader = SnapshotReader(self, flow_redownload.snapshot_for_date)
        self.reader.ready.connect(self._on_snapshot_ready)

        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.refresh_data)
        self.finished.connect(lambda *_: self.timer.stop())

        self.refresh_data(force=True)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.timer.start()
        self.refresh_data(force=True)

    def hideEvent(self, event) -> None:
        self.timer.stop()
        super().hideEvent(event)

    # ── Data Loading & Filtering ──────────────────────────────────────────

    def refresh_data(self, force: bool = False) -> None:
        if not self.isVisible() and not force:
            return
        self.reader.request(work_dates.active())

    def _on_snapshot_ready(self, day: str, result: dict, error: str) -> None:
        if error or not isinstance(result, dict):
            return
        if day != work_dates.active():
            return
        self._snapshot = result
        seg_map: dict[int, dict] = {}
        for rec in result.get("recipients") or []:
            for h in rec.get("hosts") or []:
                for v in h.get("videos") or []:
                    for s in v.get("segments") or []:
                        seg_map[int(s["segment_id"])] = {
                            **s,
                            "host_id": int(h["host_id"]),
                            "host_name": h["host_name"],
                            "recipient_id": int(rec["recipient_id"]),
                            "recipient_name": rec["recipient_name"],
                        }
        self._seg_index = seg_map
        # Prune selections that no longer exist or are currently mid-redownload
        valid_selectable = {
            sid
            for sid, info in seg_map.items()
            if info.get("can_redownload") and info.get("redownload_status") not in ("queued", "downloading")
        }
        self._checked &= valid_selectable
        self._render()

    def _set_filter_mode(self, mode: str) -> None:
        self._filter_mode = mode
        for k, b in self._filter_btns.items():
            b.setChecked(k == mode)
        self._render()

    def _on_filter_changed(self, *_) -> None:
        self._render()

    def _seg_matches_filter(self, seg: dict, host: dict, rec: dict, needle: str) -> bool:
        mode = self._filter_mode
        fstate = seg.get("file_state")
        rstate = seg.get("redownload_status")
        if mode == "ok" and fstate != "ok":
            return False
        if mode == "missing" and fstate == "ok":
            return False
        if mode == "redownloading" and rstate not in ("queued", "downloading"):
            return False
        if needle:
            hay = (
                f"{rec.get('recipient_name', '')} {host.get('host_name', '')} "
                f"{seg.get('code', '')} 视频{int(seg.get('video_seq') or 0):02d} "
                f"{seg.get('filename', '')} {seg.get('channel_key', '')} s{int(seg.get('segment_id') or 0):06d}"
            ).lower()
            if needle not in hay:
                return False
        return True

    def _host_pixmap(self, host_id: int, image_path: str) -> QPixmap:
        # 1. Try owner's pre-decoded cache first
        if self.owner is not None:
            owner_cache = getattr(self.owner, "_view_cache", None)
            if isinstance(owner_cache, dict):
                imgs = owner_cache.get("images") or {}
                if host_id in imgs:
                    ikey, qimg = imgs[host_id]
                    cached = self._thumb_cache.get(host_id)
                    if cached and cached[0] == ikey:
                        return cached[1]
                    if qimg is not None and not qimg.isNull():
                        pm = _rounded_portrait_pixmap(qimg)
                        self._thumb_cache[host_id] = (ikey, pm)
                        return pm
        # 2. Decode on demand & cache
        if not image_path:
            return QPixmap()
        ikey = image_assets.image_cache_key(image_path)
        cached = self._thumb_cache.get(host_id)
        if cached and cached[0] == ikey:
            return cached[1]
        try:
            qimg = image_assets.read_image(image_path)
            if not qimg.isNull():
                dpr = max(1.0, float(self.devicePixelRatioF() or 1.0))
                scaled = qimg.scaled(
                    int(46 * dpr),
                    int(66 * dpr),
                    Qt.KeepAspectRatioByExpanding,
                    Qt.SmoothTransformation,
                )
                # Center-crop to exact 46x66 * dpr
                tw, th = int(46 * dpr), int(66 * dpr)
                if scaled.width() > tw or scaled.height() > th:
                    scaled = scaled.copy(
                        max(0, (scaled.width() - tw) // 2),
                        max(0, (scaled.height() - th) // 2),
                        min(tw, scaled.width()),
                        min(th, scaled.height()),
                    )
                scaled.setDevicePixelRatio(dpr)
                pm = _rounded_portrait_pixmap(scaled)
                self._thumb_cache[host_id] = (ikey, pm)
                return pm
        except Exception:
            pass
        self._thumb_cache[host_id] = (ikey, QPixmap())
        return QPixmap()

    # ── Selection Helpers ─────────────────────────────────────────────────

    @staticmethod
    def _selectable_sids_from_list(segs: list[dict]) -> list[int]:
        return [
            int(s["segment_id"])
            for s in segs
            if s.get("can_redownload") and s.get("redownload_status") not in ("queued", "downloading")
        ]

    def _check_state_for_sids(self, sids: list[int]) -> Qt.CheckState:
        if not sids:
            return Qt.Unchecked
        sel_cnt = sum(1 for sid in sids if sid in self._checked)
        if sel_cnt == 0:
            return Qt.Unchecked
        if sel_cnt == len(sids):
            return Qt.Checked
        return Qt.PartiallyChecked

    def _toggle_group_sids(self, sids: list[int]) -> None:
        if not sids:
            return
        all_checked = all(sid in self._checked for sid in sids)
        if all_checked:
            for sid in sids:
                self._checked.discard(sid)
        else:
            for sid in sids:
                self._checked.add(sid)
        self._render()

    def _on_segment_clicked(self, sid: int, modifiers=Qt.NoModifier) -> None:
        info = self._seg_index.get(sid)
        if not info or not info.get("can_redownload") or info.get("redownload_status") in ("queued", "downloading"):
            return
        target_checked = sid not in self._checked
        if (modifiers & Qt.ShiftModifier) and self._last_clicked_sid is not None and self._last_clicked_sid in self._visible_ordered_sids and sid in self._visible_ordered_sids:
            i1 = self._visible_ordered_sids.index(self._last_clicked_sid)
            i2 = self._visible_ordered_sids.index(sid)
            lo, hi = min(i1, i2), max(i1, i2)
            for r_sid in self._visible_ordered_sids[lo : hi + 1]:
                r_info = self._seg_index.get(r_sid)
                if r_info and r_info.get("can_redownload") and r_info.get("redownload_status") not in ("queued", "downloading"):
                    if target_checked:
                        self._checked.add(r_sid)
                    else:
                        self._checked.discard(r_sid)
        else:
            if target_checked:
                self._checked.add(sid)
            else:
                self._checked.discard(sid)
        self._last_clicked_sid = sid
        self._render()

    def _select_visible(self, select: bool) -> None:
        if not select:
            self._checked.clear()
            self._render()
            return
        for sid in self._visible_ordered_sids:
            info = self._seg_index.get(sid)
            if info and info.get("can_redownload") and info.get("redownload_status") not in ("queued", "downloading"):
                self._checked.add(sid)
        self._render()

    def _select_all_missing(self) -> None:
        added = 0
        for sid, info in self._seg_index.items():
            if info.get("file_state") != "ok" and info.get("can_redownload") and info.get("redownload_status") not in ("queued", "downloading"):
                self._checked.add(sid)
                self._expanded_hosts.add(int(info["host_id"]))
                added += 1
        if added == 0:
            QMessageBox.information(self, "文件齐全", "当前所有已下载片段的本地视频文件均完整正常，没有缺失或损坏文件。")
            return
        self._render()

    def _toggle_recipient_collapse(self, rid: int) -> None:
        cur = bool(self._collapsed_recipients.get(rid, False))
        self._collapsed_recipients[rid] = not cur
        self._render()

    def _toggle_host_expand(self, hid: int) -> None:
        if hid in self._expanded_hosts:
            self._expanded_hosts.discard(hid)
        else:
            self._expanded_hosts.add(hid)
        self._render()

    # ── Rendering (Keyed & Scroll-Safe) ───────────────────────────────────

    def _render(self) -> None:
        snap = self._snapshot
        if not snap:
            return
        day = snap.get("work_date") or work_dates.active()
        tot_dl = int(snap.get("total_downloaded") or 0)
        tot_ok = int(snap.get("total_ok") or 0)
        tot_miss = int(snap.get("total_missing") or 0)
        tot_redl = int(snap.get("total_active_redl") or 0)
        tot_dl_videos = sum(int(r.get("dl_videos") or 0) for r in (snap.get("recipients") or []))

        title_bits = [f"{day}  ·  🎬 {tot_dl_videos} 视频 / 🎞 {tot_dl} 段"]
        if tot_redl > 0:
            title_bits.append(f"↓ {tot_redl}")
        _set_text(
            self.title_lbl,
            "  ·  ".join(title_bits),
            tip=f"工作日期：{day}\n已下载完成：{tot_dl} 个片段（{tot_dl_videos} 条完整视频）\n点击重下仅拉取原云端视频覆盖保存，不改提示词、不重新生成",
        )

        pill_texts = {
            "all": (f"全部 {tot_dl}", f"全部已下载片段：{tot_dl}"),
            "missing": (f"⚠ 缺 {tot_miss}" if tot_miss > 0 else "⚠ 0", f"本地缺失或损坏：{tot_miss} 段"),
            "redownloading": (f"↓ {tot_redl}", f"正在重新下载中：{tot_redl} 段"),
        }
        for k, (txt, tip_txt) in pill_texts.items():
            btn = self._filter_btns.get(k)
            if btn:
                _set_text(btn, txt, tip=tip_txt)
        redl_pill = self._filter_btns.get("redownloading")
        if redl_pill:
            redl_pill.setVisible(tot_redl > 0 or self._filter_mode == "redownloading")
        miss_btn = self._filter_btns.get("missing")
        if miss_btn:
            _set_prop(miss_btn, "hasAlert", "true" if tot_miss > 0 else "false")
        self.btn_select_missing.setEnabled(tot_miss > 0)
        self.btn_select_missing.setVisible(tot_miss > 0)

        needle = self.search_edit.text().strip().lower()
        auto_expand_matches = bool(needle) or self._filter_mode in ("missing", "redownloading")

        visible_rec_cards: list[QWidget] = []
        ordered_visible_sids: list[int] = []
        alive_rids = set()

        for rec_data in snap.get("recipients") or []:
            rid = int(rec_data["recipient_id"])
            alive_rids.add(rid)

            # Filter hosts & segments for this recipient
            filtered_hosts = []
            rec_selectable_sids: list[int] = []
            for h_data in rec_data.get("hosts") or []:
                hid = int(h_data["host_id"])
                f_videos = []
                h_selectable_sids: list[int] = []
                for v_data in h_data.get("videos") or []:
                    f_segs = [
                        s for s in (v_data.get("segments") or [])
                        if self._seg_matches_filter(s, h_data, rec_data, needle)
                    ]
                    if f_segs:
                        f_videos.append({**v_data, "segments": f_segs})
                        v_sel = self._selectable_sids_from_list(f_segs)
                        h_selectable_sids.extend(v_sel)
                        for s in f_segs:
                            ordered_visible_sids.append(int(s["segment_id"]))
                if f_videos:
                    rec_selectable_sids.extend(h_selectable_sids)
                    filtered_hosts.append((h_data, f_videos, h_selectable_sids))

            r_entry = self._ensure_recipient_widget(rid)
            if not filtered_hosts:
                r_entry["card"].hide()
                continue

            # Update Recipient Header
            rname = str(rec_data.get("recipient_name") or "未命名接收人")
            _set_text(r_entry["avatar"], rname[:1])
            _set_text(r_entry["title"], rname)

            r_miss = int(rec_data.get("missing_files") or 0)
            r_active = int(rec_data.get("redl_active") or 0)
            r_dl_s = int(rec_data.get("dl_segments") or 0)
            r_tot_s = max(1, int(rec_data.get("total_segments") or r_dl_s or 1))
            r_pct = int(round(100.0 * r_dl_s / r_tot_s))

            if r_active > 0:
                r_tone = "running"
                r_badge = f"↓ {r_active}"
            elif r_miss > 0:
                r_tone = "failed"
                r_badge = f"⚠ 缺 {r_miss}"
            else:
                r_tone = "done"
                r_badge = f"👤 {rec_data['dl_hosts']}"

            r_meta = f"🎬 {rec_data['dl_videos']}/{rec_data['total_videos']}   🎞 {r_dl_s}/{rec_data['total_segments']}"
            r_meta_tip = (
                f"主播数：{rec_data['dl_hosts']}\n"
                f"完整视频：{rec_data['dl_videos']}/{rec_data['total_videos']} 条\n"
                f"已下载片段：{r_dl_s}/{rec_data['total_segments']}\n"
                f"本地文件正常：{rec_data['ok_files']}/{r_dl_s}"
            )
            _set_text(r_entry["badge"], r_badge, tip=r_meta_tip)
            r_entry["meta"].set_raw_text(r_meta, tooltip=r_meta_tip)
            r_bar: QProgressBar = r_entry["bar"]
            if r_bar.maximum() != r_tot_s:
                r_bar.setRange(0, r_tot_s)
            if r_bar.value() != r_dl_s:
                r_bar.setValue(r_dl_s)
            _set_text(r_entry["pct"], f"{r_pct}%")

            for w_key in ("card", "avatar", "badge", "bar", "pct"):
                _set_prop(r_entry[w_key], "tone", r_tone)

            # Sync Recipient Tri-state Checkbox
            r_chk: QCheckBox = r_entry["check"]
            r_chk.blockSignals(True)
            r_chk.setCheckState(self._check_state_for_sids(rec_selectable_sids))
            r_chk.setEnabled(bool(rec_selectable_sids))
            r_chk.blockSignals(False)
            r_entry["selectable_sids"] = rec_selectable_sids

            collapsed = bool(self._collapsed_recipients.get(rid, False))
            _set_prop(r_entry["head"], "collapsed", "true" if collapsed else "false")
            _set_text(
                r_entry["chevron"],
                "▾" if collapsed else "▴",
                tip="展开该接收人" if collapsed else "收起该接收人",
            )

            # Sync Host Cards inside this Recipient
            visible_host_cards: list[QWidget] = []
            visible_drawers: list[QWidget] = []
            alive_hids = {int(h["host_id"]) for h, _, _ in filtered_hosts}
            for dead_hid in [k for k in list(r_entry["hosts"]) if k not in alive_hids]:
                r_entry["hosts"][dead_hid]["card"].hide()
                if r_entry["hosts"][dead_hid].get("drawer"):
                    r_entry["hosts"][dead_hid]["drawer"].hide()

            for h_data, f_videos, h_sel_sids in filtered_hosts:
                hid = int(h_data["host_id"])
                h_entry = self._ensure_host_widget(r_entry, hid)
                h_entry["selectable_sids"] = h_sel_sids

                # Host Check State
                h_state_chk = self._check_state_for_sids(h_sel_sids)
                h_chk: QCheckBox = h_entry["check"]
                h_chk.blockSignals(True)
                h_chk.setCheckState(h_state_chk)
                h_chk.setEnabled(bool(h_sel_sids))
                h_chk.blockSignals(False)

                # Portrait Thumbnail
                pm = self._host_pixmap(hid, str(h_data.get("image_path") or ""))
                if not pm.isNull():
                    h_entry["thumb"].setText("")
                    h_entry["thumb"].setPixmap(pm)
                else:
                    h_entry["thumb"].setPixmap(QPixmap())
                    h_entry["thumb"].setText("无图")

                h_dl_s = int(h_data["dl_segments"])
                h_tot_s = max(1, int(h_data["total_segments"] or h_dl_s))
                h_miss = int(h_data["missing_files"])
                h_act = int(h_data["redl_active"])
                h_pct = int(round(100.0 * h_dl_s / h_tot_s))

                h_tip = (
                    f"{h_data['host_name']}\n"
                    f"完整视频：{h_data['dl_videos']} / {h_data['total_videos']} 条\n"
                    f"已下载片段：{h_dl_s} / {h_data['total_segments']} 段 ({h_pct}%)\n"
                    f"本地正常：{h_data['ok_files']} 段"
                )
                h_entry["title"].set_raw_text(h_data["host_name"], tooltip=h_tip)
                _set_text(
                    h_entry["vid_meta"],
                    f"🎬 {h_data['dl_videos']}/{h_data['total_videos']}  ·  🎞 {h_dl_s}/{h_data['total_segments']}",
                    tip=h_tip,
                )

                hbar: QProgressBar = h_entry["bar"]
                if hbar.maximum() != h_tot_s:
                    hbar.setRange(0, h_tot_s)
                if hbar.value() != h_dl_s:
                    hbar.setValue(h_dl_s)

                is_expanded = (hid in self._expanded_hosts) or auto_expand_matches
                if h_act > 0:
                    h_tone = "running"
                    badge_txt = f"↓ {h_act}"
                elif h_miss > 0:
                    h_tone = "failed"
                    badge_txt = f"⚠ 缺 {h_miss}"
                else:
                    h_tone = "done"
                    badge_txt = f"{h_pct}%"

                _set_text(h_entry["seg_meta"], badge_txt, tip=h_tip)
                _set_prop(h_entry["seg_meta"], "tone", h_tone)

                _set_prop(h_entry["card"], "tone", h_tone)
                _set_prop(h_entry["card"], "expanded", "true" if is_expanded else "false")
                _set_prop(h_entry["card"], "checkedState", "full" if h_state_chk == Qt.Checked else "none")
                _set_prop(hbar, "tone", h_tone)
                h_entry["card"].setToolTip(h_tip + ("\n（点击卡片收起明细）" if is_expanded else "\n（点击卡片展开明细）"))
                h_entry["state"].hide()

                _set_text(
                    h_entry["expand_btn"],
                    "▴" if is_expanded else "▾",
                    tip="收起该主播视频与片段明细" if is_expanded else "展开该主播视频与片段明细",
                )
                _set_prop(h_entry["expand_btn"], "active", "true" if is_expanded else "false")
                h_entry["redl_btn"].setEnabled(bool(h_sel_sids) and not self._busy_submitting)

                visible_host_cards.append(h_entry["card"])

                # Build / update inline drawer ONLY when expanded
                if is_expanded and not collapsed:
                    drawer = self._sync_host_drawer(r_entry, h_entry, h_data, f_videos, h_sel_sids)
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
                "当前工作日期暂无已下载完成的片段"
                if tot_dl == 0
                else "当前筛选或搜索条件下没有匹配的已下载片段"
            )
            _set_text(self.empty_label, empty_msg)
            self.empty_label.show()
            _reorder_widgets(self.cards_layout, [self.empty_label])
        else:
            self.empty_label.hide()
            _reorder_widgets(self.cards_layout, visible_rec_cards)

        self._refresh_footer()

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
        chk.setToolTip("勾选 / 取消该接收人名下所有显示的已下载片段")
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
        h_entry = r_entry["hosts"].get(hid)
        if h_entry is not None:
            return h_entry

        hcard = _ClickableFrame(r_entry["grid_wrap"])
        hcard.setObjectName("flowHostCard")
        hcard.setFixedHeight(84)
        hcard.setMinimumWidth(0)
        hcard.setCursor(Qt.PointingHandCursor)
        hcard.clicked.connect(lambda _mods, h=hid: self._toggle_host_expand(h))

        hrow = QHBoxLayout(hcard)
        hrow.setContentsMargins(10, 8, 10, 8)
        hrow.setSpacing(8)

        chk = QCheckBox()
        chk.setTristate(True)
        chk.setCursor(Qt.PointingHandCursor)
        chk.setToolTip("勾选 / 取消该主播名下全部已下载片段")
        hrow.addWidget(chk, 0, Qt.AlignVCenter)

        thumb = QLabel("无图", objectName="flowHostThumb")
        thumb.setFixedSize(46, 66)
        thumb.setAlignment(Qt.AlignCenter)
        hrow.addWidget(thumb)

        rcol = QVBoxLayout()
        rcol.setContentsMargins(0, 0, 0, 0)
        rcol.setSpacing(4)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(4)
        htitle = _ElidingLabel("flowHostTitle", min_w=48)
        top_row.addWidget(htitle, 1)

        import_btn = QPushButton("📤", objectName="dlHostMiniBtn")
        import_btn.setProperty("kind", "import")
        import_btn.setProperty("iconOnly", "true")
        import_btn.setCursor(Qt.PointingHandCursor)
        import_btn.setFocusPolicy(Qt.NoFocus)
        import_btn.setToolTip("从外部按序号批量导入该主播的视频片段")
        import_btn.clicked.connect(lambda _=False, h=hid: self._open_host_import_dialog(h))
        top_row.addWidget(import_btn)

        redl_btn = QPushButton("↓", objectName="dlHostMiniBtn")
        redl_btn.setProperty("kind", "redl")
        redl_btn.setProperty("iconOnly", "true")
        redl_btn.setCursor(Qt.PointingHandCursor)
        redl_btn.setFocusPolicy(Qt.NoFocus)
        redl_btn.setToolTip("重新下载该主播全部片段")
        top_row.addWidget(redl_btn)

        expand_btn = QPushButton("▾", objectName="dlHostMiniBtn")
        expand_btn.setProperty("iconOnly", "true")
        expand_btn.setCursor(Qt.PointingHandCursor)
        expand_btn.setFocusPolicy(Qt.NoFocus)
        expand_btn.setToolTip("展开或收起该主播的视频与片段勾选明细")
        expand_btn.clicked.connect(lambda _=False, h=hid: self._toggle_host_expand(h))
        top_row.addWidget(expand_btn)
        rcol.addLayout(top_row)

        mid_row = QHBoxLayout()
        mid_row.setContentsMargins(0, 0, 0, 0)
        mid_row.setSpacing(6)
        vid_meta = QLabel(objectName="flowHostVideoMeta")
        seg_meta = QLabel(objectName="flowHostSegMeta")
        mid_row.addWidget(vid_meta)
        mid_row.addStretch(1)
        mid_row.addWidget(seg_meta)
        rcol.addLayout(mid_row)

        hbar = QProgressBar(objectName="flowHostBar")
        hbar.setFixedHeight(5)
        hbar.setTextVisible(False)
        rcol.addWidget(hbar)

        hstate = _ElidingLabel("flowHostState", min_w=60)
        hstate.hide()
        rcol.addWidget(hstate)

        hrow.addLayout(rcol, 1)

        h_entry = {
            "card": hcard,
            "check": chk,
            "thumb": thumb,
            "title": htitle,
            "redl_btn": redl_btn,
            "expand_btn": expand_btn,
            "vid_meta": vid_meta,
            "seg_meta": seg_meta,
            "bar": hbar,
            "state": hstate,
            "drawer": None,
            "videos": {},
            "selectable_sids": [],
        }
        chk.clicked.connect(lambda _=False, e=h_entry: self._toggle_group_sids(list(e["selectable_sids"])))
        redl_btn.clicked.connect(lambda _=False, e=h_entry, h=hid: self._confirm_and_submit(list(e["selectable_sids"]), scope_label=f"主播「{e['title']._raw}」全部 {len(e['selectable_sids'])} 个片段"))
        r_entry["hosts"][hid] = h_entry
        return h_entry

    def _sync_host_drawer(self, r_entry: dict, h_entry: dict, h_data: dict, f_videos: list[dict], h_sel_sids: list[int]) -> QFrame:
        hid = int(h_data["host_id"])
        drawer = h_entry.get("drawer")
        if drawer is None:
            drawer = QFrame(r_entry["drawers_wrap"], objectName="dlHostDrawer")
            d_lay = QVBoxLayout(drawer)
            d_lay.setContentsMargins(0, 0, 0, 10)
            d_lay.setSpacing(8)

            d_head = QFrame(drawer, objectName="dlHostDrawerHead")
            dh_lay = QHBoxLayout(d_head)
            dh_lay.setContentsMargins(12, 7, 12, 7)
            dh_lay.setSpacing(8)

            d_title = QLabel(objectName="dlHostDrawerTitle")
            dh_lay.addWidget(d_title, 1)

            btn_imp_host = QPushButton("📤 按序号导入本主播", objectName="dlHostMiniBtn")
            btn_imp_host.setProperty("kind", "import")
            btn_imp_host.setCursor(Qt.PointingHandCursor)
            btn_imp_host.setToolTip("从外部选择多个视频或文件夹，按序号批量导入该主播的片段")
            btn_imp_host.clicked.connect(lambda _=False, h=hid: self._open_host_import_dialog(h))
            dh_lay.addWidget(btn_imp_host)

            btn_sel_host = QPushButton("全选", objectName="dlHostMiniBtn")
            btn_sel_host.setCursor(Qt.PointingHandCursor)
            btn_sel_host.setToolTip("全选该主播名下所有片段")
            btn_sel_host.clicked.connect(lambda _=False, e=h_entry: self._set_sids_checked(list(e["selectable_sids"]), True))
            dh_lay.addWidget(btn_sel_host)

            btn_clr_host = QPushButton("清空", objectName="dlHostMiniBtn")
            btn_clr_host.setCursor(Qt.PointingHandCursor)
            btn_clr_host.setToolTip("清空该主播名下所有勾选")
            btn_clr_host.clicked.connect(lambda _=False, e=h_entry: self._set_sids_checked(list(e["selectable_sids"]), False))
            dh_lay.addWidget(btn_clr_host)

            btn_fold = QPushButton("▴", objectName="dlHostMiniBtn")
            btn_fold.setProperty("iconOnly", "true")
            btn_fold.setCursor(Qt.PointingHandCursor)
            btn_fold.setToolTip("收起明细")
            btn_fold.clicked.connect(lambda _=False, h=hid: self._toggle_host_expand(h))
            dh_lay.addWidget(btn_fold)

            d_lay.addWidget(d_head)

            v_holder = QWidget(drawer)
            v_lay = QVBoxLayout(v_holder)
            v_lay.setContentsMargins(10, 0, 10, 0)
            v_lay.setSpacing(8)
            d_lay.addWidget(v_holder)

            h_entry["drawer"] = drawer
            h_entry["drawer_title"] = d_title
            h_entry["drawer_videos_holder"] = v_holder
            h_entry["drawer_videos_layout"] = v_lay

        tot_segs_in_drawer = sum(len(v["segments"]) for v in f_videos)
        _set_text(
            h_entry["drawer_title"],
            f"📂 {h_data['host_name']}  ·  🎬 {len(f_videos)}  ·  🎞 {tot_segs_in_drawer}",
            tip=f"主播：{h_data['host_name']}\n显示 {len(f_videos)} 条视频 / {tot_segs_in_drawer} 个片段\n按住 Shift 点击可连续勾选片段",
        )

        visible_v_widgets: list[QWidget] = []
        alive_vids = {int(v["video_id"]) for v in f_videos}
        for dead_vid in [k for k in list(h_entry["videos"]) if k not in alive_vids]:
            h_entry["videos"][dead_vid]["frame"].hide()

        for v_data in f_videos:
            vid = int(v_data["video_id"])
            v_entry = self._ensure_video_widget(h_entry, vid)
            v_segs = v_data.get("segments") or []
            v_sel_sids = self._selectable_sids_from_list(v_segs)
            v_entry["selectable_sids"] = v_sel_sids
            v_entry["video_seq"] = int(v_data.get("video_seq") or 0)
            v_entry["host_name"] = h_data["host_name"]

            v_chk: QCheckBox = v_entry["check"]
            v_chk.blockSignals(True)
            v_chk.setCheckState(self._check_state_for_sids(v_sel_sids))
            v_chk.setEnabled(bool(v_sel_sids))
            v_chk.blockSignals(False)

            v_seq = int(v_data.get("video_seq") or 0)
            v_tot = int(v_data.get("total_segments") or len(v_segs))
            v_dl = int(v_data.get("downloaded_segments") or len(v_segs))
            _set_text(v_entry["title"], f"🎬 #{v_seq:02d}")
            _set_text(
                v_entry["badge"],
                f"{v_dl}/{v_tot}",
                tip=f"已下载 {v_dl}/{v_tot} 个片段",
            )
            _set_prop(v_entry["badge"], "tone", "done" if v_data.get("complete_video") else "warn")
            v_entry["redl_btn"].setEnabled(bool(v_sel_sids) and not self._busy_submitting)

            # Sync Segment Rows
            visible_s_widgets: list[QWidget] = []
            alive_sids = {int(s["segment_id"]) for s in v_segs}
            for dead_sid in [k for k in list(v_entry["segments"]) if k not in alive_sids]:
                v_entry["segments"][dead_sid]["row"].hide()

            for s_data in v_segs:
                sid = int(s_data["segment_id"])
                s_entry = self._ensure_segment_widget(v_entry, sid)
                s_entry["data"] = s_data

                is_checked = sid in self._checked
                can_sel = bool(s_data.get("can_redownload")) and s_data.get("redownload_status") not in ("queued", "downloading")

                s_chk: QCheckBox = s_entry["check"]
                s_chk.blockSignals(True)
                s_chk.setChecked(is_checked)
                s_chk.setEnabled(can_sel)
                s_chk.blockSignals(False)
                _set_prop(s_entry["row"], "checked", "true" if is_checked else "false")

                qc = str(s_data.get("qc_status") or "待质检")
                f_state_for_code = str(s_data.get("file_state") or "missing")
                if f_state_for_code in ("missing", "corrupt", "uncompleted") or qc == "退回":
                    code_tone = "failed"
                elif qc == "通过" or f_state_for_code == "ok":
                    code_tone = "done"
                else:
                    code_tone = "default"
                _set_text(s_entry["code"], s_data["code"], tip=f"片段 {s_data['code']} · 质检状态：{qc}")
                _set_prop(s_entry["code"], "tone", code_tone)
                full_path = str(s_data.get("output_path") or "")
                s_entry["file"].set_raw_text(
                    s_data["filename"],
                    tooltip=f"{full_path or s_data['filename']}\n质检状态：{qc}",
                )
                ch_txt = str(s_data.get("channel_key") or "—")
                _set_text(s_entry["ch_chip"], ch_txt, tip=f"下载通道：{ch_txt}")
                s_entry["qc_chip"].hide()

                r_status = str(s_data.get("redownload_status") or "")
                r_msg = str(s_data.get("redownload_message") or "")
                f_state = str(s_data.get("file_state") or "missing")
                f_status = str(s_data.get("flow_status") or "已完成")
                size_str = _format_size(s_data["file_size"])
                if r_status in ("queued", "downloading"):
                    st_txt = "↓ 下载中"
                    st_tip = f"↓ {r_msg or '正在重新下载…'}"
                    st_tone = "running"
                elif r_status == "failed":
                    st_txt = "⚠ 失败"
                    st_tip = f"⚠ {r_msg}"
                    st_tone = "missing"
                elif f_state == "uncompleted":
                    st_txt = f"⏳ {f_status}"
                    st_tip = f"尚未生成完成（{f_status}）· 可点击右侧 📤 直接导入外部视频"
                    st_tone = "missing"
                elif not s_data.get("can_redownload"):
                    st_txt = f"本地 ({size_str})" if f_state == "ok" else "本地"
                    st_tip = f"外部手动导入片段 · 本地视频就绪 · 质检：{qc}"
                    st_tone = "ok"
                elif r_status == "completed" and f_state == "ok":
                    st_txt = size_str
                    st_tip = f"已重新下载 ({size_str}) · 质检：{qc}"
                    st_tone = "ok"
                elif f_state == "ok":
                    st_txt = size_str
                    st_tip = f"本地文件正常 ({size_str}) · 质检：{qc}"
                    st_tone = "ok"
                elif f_state == "corrupt":
                    st_txt = "⚠ 损坏"
                    st_tip = "本地文件 0 字节损坏（建议重新下载或点击 📤 手动导入）"
                    st_tone = "missing"
                else:
                    st_txt = "⚠ 缺失"
                    st_tip = "本地文件缺失（点击右侧 ↓ 重新下载或 📤 手动导入）"
                    st_tone = "missing"

                _set_text(s_entry["status"], st_txt, tip=st_tip)
                _set_prop(s_entry["status"], "tone", st_tone)

                s_entry["redl_btn"].setEnabled(can_sel and not self._busy_submitting)
                s_entry["reveal_btn"].setEnabled(bool(full_path))

                visible_s_widgets.append(s_entry["row"])

            _reorder_widgets(v_entry["segs_layout"], visible_s_widgets)
            visible_v_widgets.append(v_entry["frame"])

        _reorder_widgets(h_entry["drawer_videos_layout"], visible_v_widgets)
        return drawer

    def _ensure_video_widget(self, h_entry: dict, vid: int) -> dict:
        v_entry = h_entry["videos"].get(vid)
        if v_entry is not None:
            return v_entry

        frame = QFrame(h_entry["drawer_videos_holder"], objectName="dlVideoGroup")
        f_lay = QVBoxLayout(frame)
        f_lay.setContentsMargins(0, 0, 0, 2)
        f_lay.setSpacing(0)

        head = _ClickableFrame(frame)
        head.setObjectName("dlVideoHead")
        head.setCursor(Qt.PointingHandCursor)
        h_lay = QHBoxLayout(head)
        h_lay.setContentsMargins(10, 5, 10, 5)
        h_lay.setSpacing(8)

        chk = QCheckBox()
        chk.setTristate(True)
        chk.setCursor(Qt.PointingHandCursor)
        chk.setToolTip("勾选 / 取消整条视频的所有已下载片段")
        h_lay.addWidget(chk)

        title = QLabel(objectName="dlVideoTitle")
        h_lay.addWidget(title)

        badge = QLabel(objectName="dlChip")
        h_lay.addWidget(badge)
        h_lay.addStretch(1)

        import_v_btn = QPushButton("📤", objectName="dlHostMiniBtn")
        import_v_btn.setProperty("kind", "import")
        import_v_btn.setProperty("iconOnly", "true")
        import_v_btn.setCursor(Qt.PointingHandCursor)
        import_v_btn.setFocusPolicy(Qt.NoFocus)
        import_v_btn.setToolTip("从外部按序号批量导入该条视频的所有片段")
        import_v_btn.clicked.connect(lambda _=False, v=vid: self._open_video_import_dialog(v))
        h_lay.addWidget(import_v_btn)

        redl_btn = QPushButton("↓", objectName="dlHostMiniBtn")
        redl_btn.setProperty("kind", "redl")
        redl_btn.setProperty("iconOnly", "true")
        redl_btn.setCursor(Qt.PointingHandCursor)
        redl_btn.setFocusPolicy(Qt.NoFocus)
        redl_btn.setToolTip("重新下载该条视频全部片段")
        h_lay.addWidget(redl_btn)

        f_lay.addWidget(head)

        segs_holder = QWidget(frame)
        segs_lay = QVBoxLayout(segs_holder)
        segs_lay.setContentsMargins(0, 0, 0, 0)
        segs_lay.setSpacing(0)
        f_lay.addWidget(segs_holder)

        v_entry = {
            "frame": frame,
            "head": head,
            "check": chk,
            "title": title,
            "badge": badge,
            "redl_btn": redl_btn,
            "segs_holder": segs_holder,
            "segs_layout": segs_lay,
            "segments": {},
            "selectable_sids": [],
            "video_seq": 0,
            "host_name": "",
        }
        chk.clicked.connect(lambda _=False, e=v_entry: self._toggle_group_sids(list(e["selectable_sids"])))
        head.clicked.connect(lambda _mods, e=v_entry: self._toggle_group_sids(list(e["selectable_sids"])))
        redl_btn.clicked.connect(
            lambda _=False, e=v_entry: self._confirm_and_submit(
                list(e["selectable_sids"]),
                scope_label=f"{e['host_name']} · 视频 {int(e['video_seq']):02d}（共 {len(e['selectable_sids'])} 段）",
            )
        )
        h_entry["videos"][vid] = v_entry
        return v_entry

    def _ensure_segment_widget(self, v_entry: dict, sid: int) -> dict:
        s_entry = v_entry["segments"].get(sid)
        if s_entry is not None:
            return s_entry

        row = _ClickableFrame(v_entry["segs_holder"])
        row.setObjectName("dlSegRow")
        row.setCursor(Qt.PointingHandCursor)
        row.clicked.connect(lambda mods, s=sid: self._on_segment_clicked(s, mods))

        r_lay = QHBoxLayout(row)
        r_lay.setContentsMargins(14, 5, 10, 5)
        r_lay.setSpacing(8)

        chk = QCheckBox()
        chk.setCursor(Qt.PointingHandCursor)
        chk.clicked.connect(lambda _=False, s=sid: self._on_segment_clicked(s, QApplication.keyboardModifiers()))
        r_lay.addWidget(chk)

        code = QLabel(objectName="dlSegCode")
        code.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        r_lay.addWidget(code)

        file_lbl = _ElidingLabel("dlSegFile", min_w=120)
        r_lay.addWidget(file_lbl, 1)

        ch_chip = QLabel(objectName="dlChip")
        ch_chip.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        r_lay.addWidget(ch_chip)

        qc_chip = QLabel(objectName="dlChip")
        qc_chip.setProperty("iconOnly", "true")
        qc_chip.setAlignment(Qt.AlignCenter)
        qc_chip.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        r_lay.addWidget(qc_chip)

        status_lbl = QLabel(objectName="dlSegStatus")
        status_lbl.setMinimumWidth(62)
        status_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        r_lay.addWidget(status_lbl)

        import_btn = QPushButton("📤", objectName="dlHostMiniBtn")
        import_btn.setProperty("kind", "import")
        import_btn.setProperty("iconOnly", "true")
        import_btn.setCursor(Qt.PointingHandCursor)
        import_btn.setFocusPolicy(Qt.NoFocus)
        import_btn.setToolTip("手动导入外部视频文件到此片段")
        import_btn.clicked.connect(lambda _=False, s=sid: self._import_single_segment(s))
        r_lay.addWidget(import_btn)

        redl_btn = QPushButton("↓", objectName="dlHostMiniBtn")
        redl_btn.setProperty("kind", "redl")
        redl_btn.setProperty("iconOnly", "true")
        redl_btn.setCursor(Qt.PointingHandCursor)
        redl_btn.setFocusPolicy(Qt.NoFocus)
        redl_btn.setToolTip("重新下载该片段")
        redl_btn.clicked.connect(lambda _=False, s=sid: self._submit_ids([s], confirm=False))
        r_lay.addWidget(redl_btn)

        reveal_btn = QPushButton("📂", objectName="dlHostMiniBtn")
        reveal_btn.setProperty("iconOnly", "true")
        reveal_btn.setCursor(Qt.PointingHandCursor)
        reveal_btn.setFocusPolicy(Qt.NoFocus)
        reveal_btn.setToolTip("在访达 (Finder) 中定位本地视频文件")
        reveal_btn.clicked.connect(lambda _=False, s=sid: self._reveal_segment_file(s))
        r_lay.addWidget(reveal_btn)

        s_entry = {
            "row": row,
            "check": chk,
            "code": code,
            "file": file_lbl,
            "ch_chip": ch_chip,
            "qc_chip": qc_chip,
            "status": status_lbl,
            "import_btn": import_btn,
            "redl_btn": redl_btn,
            "reveal_btn": reveal_btn,
            "data": {},
        }
        v_entry["segments"][sid] = s_entry
        return s_entry

    # ── Manual External Video Import Actions ──────────────────────────────

    def _on_manual_import_finished(self, res: dict | None) -> None:
        if not res or not int(res.get("imported") or 0):
            return
        cnt = int(res.get("imported") or 0)
        _set_text(self.status_banner_lbl, f"✓ 已手动导入 {cnt} 个外部视频片段")
        self.refresh_data(force=True)
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

    def _set_sids_checked(self, sids: list[int], checked: bool) -> None:
        for sid in sids:
            if checked:
                self._checked.add(sid)
            else:
                self._checked.discard(sid)
        self._render()

    def _refresh_footer(self) -> None:
        sel_count = len(self._checked)
        if sel_count > 0:
            hosts_sel = {self._seg_index[s]["host_id"] for s in self._checked if s in self._seg_index}
            vids_sel = {self._seg_index[s]["video_id"] for s in self._checked if s in self._seg_index}
            _set_text(
                self.sel_summary_lbl,
                f"已选 {sel_count} 段  ·  👤 {len(hosts_sel)}  ·  🎬 {len(vids_sel)}",
            )
            _set_text(self.btn_batch_redownload, f"↓ 重新下载 ({sel_count})")
        else:
            _set_text(self.sel_summary_lbl, "已选 0 段")
            _set_text(self.btn_batch_redownload, "↓ 重新下载")
        self.btn_batch_redownload.setEnabled(bool(sel_count) and not self._busy_submitting)

    # ── File / Folder Actions & Re-Download Submission ────────────────────

    def _open_channels_root(self) -> None:
        custom = repo.get_setting("flow_channel_download_root", "").strip()
        folder = Path(custom).expanduser() if custom else (Path.home() / "Downloads" / "FlowStudio_Channels")
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _reveal_segment_file(self, sid: int) -> None:
        info = self._seg_index.get(sid) or {}
        raw = str(info.get("output_path") or "").strip()
        if not raw:
            self._open_channels_root()
            return
        p = Path(raw).expanduser()
        if sys.platform == "darwin" and p.exists():
            subprocess.Popen(["open", "-R", str(p)])
        elif p.parent.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p.parent)))
        else:
            self._open_channels_root()

    def _on_batch_redownload_clicked(self) -> None:
        sids = sorted(self._checked)
        if not sids:
            return
        hosts_sel = {self._seg_index[s]["host_id"] for s in sids if s in self._seg_index}
        self._confirm_and_submit(sids, scope_label=f"已选中的 {len(sids)} 个片段（涉及 {len(hosts_sel)} 位主播）")

    def _confirm_and_submit(self, sids: list[int], scope_label: str) -> None:
        clean = sorted({int(x) for x in sids if int(x) > 0})
        if not clean:
            QMessageBox.information(self, "重新下载", "当前范围内没有可从云端重新下载的片段。")
            return
        from app.ui.confirm_dialog import ask_confirm
        if ask_confirm(
            self,
            "确认重新下载",
            f"确认重新下载 {scope_label} 吗？",
            confirm_text="立即下载",
            cancel_text="取消",
            icon_text="↓",
        ) != "confirm":
            return
        self._submit_ids(clean, confirm=False)

    def _submit_ids(self, sids: list[int], confirm: bool = False) -> None:
        if self._busy_submitting:
            return
        if confirm:
            self._confirm_and_submit(sids, f"{len(sids)} 个片段")
            return
        bridge = getattr(self.owner, "bridge", None)
        if bridge is None:
            from app.services.local_bridge import get_bridge
            bridge = get_bridge()
        self._busy_submitting = True
        self._refresh_footer()
        try:
            res = flow_redownload.submit_redownload(sids, bridge, work_date=work_dates.active())
        except Exception as exc:
            self._busy_submitting = False
            self._refresh_footer()
            QMessageBox.warning(self, "无法提交重新下载", str(exc))
            return

        self._busy_submitting = False
        queued = int(res.get("queued") or 0)
        skipped = res.get("skipped") or []
        for s in sids:
            self._checked.discard(int(s))

        if queued > 0:
            _set_text(
                self.status_banner_lbl,
                f"✓ 已下发 {queued} 个重新下载任务，浏览器正在拉取云端视频…"
                + (f"（跳过 {len(skipped)} 个不可重下项）" if skipped else ""),
            )
        elif skipped:
            reasons = "；".join(f"S{sid:06d}: {why}" for sid, why in skipped[:4])
            QMessageBox.information(self, "未加入重新下载队列", f"所选片段未能加入重下队列：\n{reasons}")

        self.refresh_data(force=True)
