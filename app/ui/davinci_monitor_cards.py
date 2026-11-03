"""Recipient-grouped AI Host cards + inline video detail drawer for DaVinci Auto-Editing Center."""
from collections import OrderedDict
from pathlib import Path
import threading

from PySide6.QtCore import Qt, QRect, QRectF, QSize, QObject, Signal
from PySide6.QtGui import QPixmap, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QFrame, QWidget, QLabel, QPushButton, QProgressBar, QScrollArea,
    QVBoxLayout, QHBoxLayout, QLayout, QSizePolicy, QMenu,
)
from shiboken6 import isValid as _qt_is_valid

from app.services.image_assets import image_cache_key
from app.ui.image_preview import _THUMB_POOL, _thumbnail


_BASE_CARD_HEIGHT = 104
_VIDEO_ROW_HEIGHT = 26
_VIDEO_ROW_SPACING = 3
_MAX_VISIBLE_DRAWER_ROWS = 8

_PORTRAIT_CACHE = OrderedDict()
_PORTRAIT_LOCK = threading.RLock()
_PORTRAIT_MAX_ITEMS = 160


class _PortraitThumbBridge(QObject):
    ready = Signal(object, int, object, str)

    def __init__(self):
        super().__init__()
        self.ready.connect(self._apply)

    def _apply(self, label, req_id: int, image, raw_path: str):
        try:
            pix = None
            if image is not None and not image.isNull():
                pix = _rounded_cover_pixmap(image, 54, 80, 7.0)
                if raw_path:
                    with _PORTRAIT_LOCK:
                        _PORTRAIT_CACHE[raw_path] = pix
                        _PORTRAIT_CACHE.move_to_end(raw_path)
                        while len(_PORTRAIT_CACHE) > _PORTRAIT_MAX_ITEMS:
                            _PORTRAIT_CACHE.popitem(last=False)
            if label is None or not _qt_is_valid(label):
                return
            if label.property('_dv_img_req') != req_id:
                return
            if pix is not None and not pix.isNull():
                label.setText('')
                label.setPixmap(pix)
                label.setToolTip(raw_path)
            else:
                label.setPixmap(QPixmap())
                label.setText('无图')
                label.setToolTip(raw_path or '暂无参考图')
        except RuntimeError:
            pass


_THUMB_BRIDGE = None
_THUMB_REQ_SEQ = 0
_THUMB_REQ_LOCK = threading.Lock()


def _get_thumb_bridge() -> _PortraitThumbBridge:
    global _THUMB_BRIDGE
    if _THUMB_BRIDGE is None:
        _THUMB_BRIDGE = _PortraitThumbBridge()
    return _THUMB_BRIDGE


def _next_thumb_req() -> int:
    global _THUMB_REQ_SEQ
    with _THUMB_REQ_LOCK:
        _THUMB_REQ_SEQ += 1
        return _THUMB_REQ_SEQ


def _rounded_cover_pixmap(image, w_pt: int = 54, h_pt: int = 80, radius: float = 7.0) -> QPixmap:
    dpr = 2.0
    tw, th = int(w_pt * dpr), int(h_pt * dpr)
    scaled = image.scaled(QSize(tw, th), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    x0 = max(0, (scaled.width() - tw) // 2)
    y0 = max(0, (scaled.height() - th) // 2)
    cropped = scaled.copy(x0, y0, tw, th)
    src = QPixmap.fromImage(cropped)
    src.setDevicePixelRatio(dpr)

    out = QPixmap(tw, th)
    out.setDevicePixelRatio(dpr)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0.0, 0.0, float(w_pt), float(h_pt)), radius, radius)
    p.setClipPath(clip)
    p.drawPixmap(0, 0, src)
    p.end()
    return out


def _set_portrait_thumb(label: QLabel, path_str: str):
    raw = str(path_str or '').strip()
    prev_raw = label.property('_dv_img_path')
    if prev_raw == raw and (not raw or (label.pixmap() is not None and not label.pixmap().isNull())):
        return
    label.setProperty('_dv_img_path', raw)
    req_id = _next_thumb_req()
    label.setProperty('_dv_img_req', req_id)
    if not raw:
        label.setPixmap(QPixmap())
        label.setText('无图')
        label.setToolTip('暂无主播参考图')
        return
    with _PORTRAIT_LOCK:
        cached = _PORTRAIT_CACHE.get(raw)
        if cached is not None:
            _PORTRAIT_CACHE.move_to_end(raw)
            label.setText('')
            label.setPixmap(cached)
            label.setToolTip(raw)
            return

    bridge = _get_thumb_bridge()

    def _decode():
        try:
            rev = image_cache_key(raw)
            if rev[1] is None:
                bridge.ready.emit(label, req_id, None, raw)
                return
            img = _thumbnail(raw, QSize(160, 220), raw_key=(raw, 160, 220))
            bridge.ready.emit(label, req_id, img, raw)
        except Exception:
            bridge.ready.emit(label, req_id, None, raw)

    _THUMB_POOL.submit(_decode)


class _ClickableHeader(QFrame):
    clicked = Signal()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class _HostCardFrame(QFrame):
    doubleClicked = Signal()
    contextRequested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent, objectName='flowHostCard')
        self._desired_h = _BASE_CARD_HEIGHT
        self.setFixedHeight(_BASE_CARD_HEIGHT)
        self.setMinimumWidth(0)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda pos: self.contextRequested.emit(self.mapToGlobal(pos)))

    def set_desired_height(self, h: int) -> bool:
        h = max(_BASE_CARD_HEIGHT, int(h))
        if self._desired_h == h and self.minimumHeight() == h and self.maximumHeight() == h:
            return False
        self._desired_h = h
        self.setFixedHeight(h)
        self.updateGeometry()
        return True

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            child = self.childAt(event.position().toPoint())
            if not isinstance(child, QPushButton):
                self.doubleClicked.emit()
                event.accept()
                return
        super().mouseDoubleClickEvent(event)


class _VideoRowFrame(QFrame):
    doubleClicked = Signal()
    contextRequested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent, objectName='dvVideoRow')
        self.setFixedHeight(_VIDEO_ROW_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda pos: self.contextRequested.emit(self.mapToGlobal(pos)))

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.doubleClicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class _ElidingLabel(QLabel):
    def __init__(self, object_name='', min_w=36, max_w=None):
        super().__init__(objectName=object_name)
        self._raw = ''
        self._tip_override = ''
        self.setMinimumWidth(min_w)
        if max_w is not None:
            self.setMaximumWidth(max_w)
            self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        else:
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def set_raw_text(self, value: str, tooltip: str = ''):
        value = str(value or '')
        tip = str(tooltip or value)
        if self._raw == value and self._tip_override == tip:
            return
        self._raw = value
        self._tip_override = tip
        self.setToolTip(tip)
        self._update_elided()

    def _update_elided(self):
        w = self.width()
        max_w = self.maximumWidth()
        target_w = w if w > 20 else (max_w if 20 < max_w < 10000 else 0)
        if target_w <= 20:
            super().setText(self._raw)
        else:
            pad = 12 if self.objectName() == 'dvHostTagPill' else 2
            super().setText(self.fontMetrics().elidedText(self._raw, Qt.ElideRight, max(16, target_w - pad)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_elided()


class VariableCardGrid(QLayout):
    """Multi-column responsive host grid where each row adapts cleanly to expanded host drawers."""

    def __init__(self, parent=None, minimum=315, maximum=480, base_height=_BASE_CARD_HEIGHT, spacing=10):
        super().__init__(parent)
        self.items = []
        self.minimum = minimum
        self.maximum = maximum
        self.base_height = base_height
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, i):
        return self.items[i] if 0 <= i < len(self.items) else None

    def takeAt(self, i):
        return self.items.pop(i) if 0 <= i < len(self.items) else None

    def expandingDirections(self):
        return Qt.Orientation.Horizontal

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self.arrange(QRect(0, 0, width, 0), False)

    def minimumSize(self):
        return QSize(0, 0)

    def sizeHint(self):
        w = max(self.minimum, 980)
        return QSize(w, self.heightForWidth(w))

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.arrange(rect, True)

    def dimensions(self, width):
        n = len(self.items)
        if n <= 0:
            return 1, max(1, width)
        sp = self.spacing()
        columns = max(1, (max(1, width) + sp) // (self.minimum + sp))
        columns = min(columns, n)
        card_width = min(self.maximum, max(1, (width - (columns - 1) * sp) // columns))
        return columns, card_width

    def _item_height(self, item) -> int:
        w = item.widget()
        if w is not None and hasattr(w, '_desired_h'):
            return int(w._desired_h)
        return self.base_height

    def arrange(self, rect, apply: bool) -> int:
        n = len(self.items)
        if n == 0:
            return 0
        sp = self.spacing()
        columns, card_w = self.dimensions(rect.width())
        y = rect.y()
        total_rows = (n + columns - 1) // columns
        for r in range(total_rows):
            row_items = self.items[r * columns : (r + 1) * columns]
            row_h = max(self._item_height(it) for it in row_items)
            if apply:
                for c_idx, it in enumerate(row_items):
                    ih = self._item_height(it)
                    x = rect.x() + c_idx * (card_w + sp)
                    it.setGeometry(QRect(x, y, card_w, ih))
            y += row_h + (sp if r + 1 < total_rows else 0)
        return y - rect.y()


class _DvGridBody(QWidget):
    """Wraps VariableCardGrid so QScrollArea honors exact multi-row variable height."""

    def __init__(self, parent, grid: VariableCardGrid):
        super().__init__(parent)
        self.setObjectName('flowRecipientBody')
        self._grid = grid
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 12)
        lay.setSpacing(0)
        lay.addLayout(grid)

    def sync_height(self):
        lay = self.layout()
        if lay is None:
            return
        w = self.width()
        if w <= 40:
            p = self.parentWidget()
            w = p.width() if p is not None and p.width() > 40 else 0
        if w <= 40:
            return
        m = lay.contentsMargins()
        avail_w = max(1, w - m.left() - m.right())
        h = (self._grid.heightForWidth(avail_w) if self._grid.count() > 0 else 0) + m.top() + m.bottom()
        if self.minimumHeight() != h or self.maximumHeight() != h:
            self.setFixedHeight(h)
            self.updateGeometry()
        if self.width() > 40:
            self._grid.setGeometry(QRect(m.left(), m.top(), avail_w, max(0, h - m.top() - m.bottom())))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.sync_height()


def _set_prop(widget, name: str, value: str) -> bool:
    if widget is None or widget.property(name) == value:
        return False
    widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    return True


def _set_text(widget, value: str, tip: str = ''):
    value = str(value or '')
    if widget.text() != value:
        widget.setText(value)
    wanted_tip = str(tip or value)
    if widget.toolTip() != wanted_tip:
        widget.setToolTip(wanted_tip)


def _reorder(layout, widgets: list) -> bool:
    if [layout.itemAt(i).widget() for i in range(layout.count())] == widgets:
        return False
    while layout.count():
        layout.takeAt(0)
    for w in widgets:
        layout.addWidget(w)
        w.show()
    return True


def _remove_missing(cache: dict, valid_keys: set, layout) -> bool:
    changed = False
    for key in list(cache):
        if key not in valid_keys:
            entry = cache.pop(key)
            card = entry.get('card') or entry.get('row')
            if card is not None:
                if layout is not None:
                    layout.removeWidget(card)
                card.hide()
                card.deleteLater()
                changed = True
    return changed


def row_matches_filter(row: dict, mode: str, needle: str, wm_bound_name: str = '') -> tuple[bool, bool]:
    """Return ``(matches, matched_by_video_detail_only)``."""
    stage = str(row.get('editing_stage') or '')
    if mode == 'ready' and stage != 'READY_TO_EDIT':
        return False, False
    if mode == 'active' and stage not in ('EDITING', 'REVIEW', 'EXPORTING'):
        return False, False
    if mode == 'done' and stage != 'COMPLETED':
        return False, False
    if mode == 'wait' and stage != 'WAITING_MATERIAL':
        return False, False
    if mode == 'error' and stage != 'ERROR':
        return False, False
    if not needle:
        return True, False
    seq = int(row.get('video_seq') or 0)
    host_hay = f"{row.get('recipient_name', '')} {row.get('host_name', '')} {wm_bound_name} {row.get('aspect_ratio', '')}".lower()
    if needle in host_hay:
        return True, False
    vid_hay = f"#{seq:02d} {seq:02d} {row.get('edit_status', '')} {row.get('edit_output_path', '')}".lower()
    if needle in vid_hay:
        return True, True
    return False, False


def _video_status_display(row: dict) -> tuple[str, str, str, str]:
    """Return ``(status_label, tone, detail_text, detail_tooltip)`` for a single video row."""
    stage = str(row.get('editing_stage') or '')
    raw_status = str(row.get('edit_status') or '')
    out_path = str(row.get('edit_output_path') or '').strip()
    segs = int(row.get('segment_count') or 0)
    passed = int(row.get('qc_passed') or 0)

    if stage == 'COMPLETED' or raw_status in ('已导出', '已完成'):
        st_lbl = '✓ 已导出' if out_path else f'✓ {raw_status or "已完成"}'
        tone = 'done'
    elif raw_status == '已剪辑':
        st_lbl = '✓ 已剪辑'
        tone = 'done'
    elif stage == 'ERROR':
        st_lbl = '⚠ 异常'
        tone = 'failed'
    elif stage == 'REVIEW' or raw_status == '待人工检查':
        st_lbl = '● 待检查'
        tone = 'prio'
    elif stage == 'EXPORTING' or raw_status in ('待导出', '导出中'):
        st_lbl = '⇧ 导出中'
        tone = 'running'
    elif stage == 'EDITING' or raw_status in ('已导入DaVinci', '剪辑中', '自动剪辑中'):
        st_lbl = '⚙ 剪辑中' if raw_status != '已导入DaVinci' else '⚙ 已导入'
        tone = 'running'
    elif stage == 'READY_TO_EDIT':
        st_lbl = '▣ 待剪辑'
        tone = 'ready'
    else:
        st_lbl = '◇ 素材待齐'
        tone = 'waiting'

    if out_path:
        detail = Path(out_path).name
        tip = f"成品路径：{out_path}\n💡 双击可打开所在文件夹"
    elif stage == 'ERROR':
        from app.services.resolve_error_guide import format_inline_editing_text
        vid_id = int(row.get('video_id') or 0)
        raw_err_str = raw_status if raw_status and raw_status not in ('异常', '失败') else f"video={vid_id} · {raw_status or '剪辑异常'}"
        cn_err, err_info = format_inline_editing_text(raw_err_str, batch_status='ERROR', max_len=95)
        detail = cn_err.lstrip('⚠ ').strip()
        tip = f"{err_info.title if err_info else detail}\n💡 点击右侧「查看详情」查看解决办法"
    elif stage == 'READY_TO_EDIT':
        detail = '片段已齐套，可导入达芬奇'
        tip = '全部片段已通过质检，可导入达芬奇自动剪辑'
    elif stage == 'WAITING_MATERIAL':
        reasons = row.get('waiting_reasons') or {}
        r_parts = [f"{k} {v}" for k, v in reasons.items() if int(v or 0) > 0]
        detail = ' / '.join(r_parts) if r_parts else f'等待生成与质检 ({passed}/{segs})'
        tip = f"等待上游片段完成与质检 ({passed}/{segs})" + (f" · {detail}" if r_parts else '') + "\n💡 右键可直接放弃移出队列"
    elif stage == 'REVIEW':
        detail = '在时间线待人工检查 / 导出'
        tip = detail
    else:
        detail = raw_status or '处理中'
        tip = detail

    return st_lbl, tone, detail, tip


def toggle_recipient_collapse(page, rid: int):
    manual = getattr(page, '_dv_manual_recipient_collapse', None)
    if manual is None:
        manual = {}
        page._dv_manual_recipient_collapse = manual
    entry = getattr(page, '_dv_monitor_recipients', {}).get(rid)
    cur = bool(entry.get('collapsed', False)) if entry else False
    manual[rid] = not cur
    page._dv_cards_sig = None
    refresh_edit_monitor(page)


def toggle_host_expand(page, host_key: tuple[int, int]):
    expanded = getattr(page, '_dv_expanded_hosts', None)
    if expanded is None:
        expanded = set()
        page._dv_expanded_hosts = expanded
    if host_key in expanded:
        expanded.discard(host_key)
    else:
        expanded.add(host_key)
    page._dv_cards_sig = None
    refresh_edit_monitor(page)


def _on_host_double_clicked(page, host_key: tuple[int, int], rows: list[dict]):
    for r in reversed(rows):
        out_p = str(r.get('edit_output_path') or '').strip()
        if out_p and Path(out_p).exists():
            page.open_exported_path(out_p)
            return
    toggle_host_expand(page, host_key)


def build_host_context_menu(page, host_key: tuple[int, int], rows: list[dict], parent=None) -> tuple[QMenu, dict]:
    menu = QMenu(parent or page)
    actions = {}
    if not rows:
        return menu, actions
    host_name = str(rows[0].get('host_name') or '未命名主播')
    existing_out = ''
    for r in reversed(rows):
        p = str(r.get('edit_output_path') or '').strip()
        if p and Path(p).exists():
            existing_out = p
            break
    if existing_out:
        actions['open_dir'] = (menu.addAction('📂 打开该主播成品文件夹'), existing_out)

    expanded_set = getattr(page, '_dv_expanded_hosts', set()) or set()
    is_exp = host_key in expanded_set
    exp_lbl = '▴ 收起视频明细' if is_exp else f'▾ 展开视频明细 ({len(rows)} 条)'
    actions['toggle_expand'] = (menu.addAction(exp_lbl), host_key)

    abandonable_stages = {'WAITING_MATERIAL', 'READY_TO_EDIT', 'ERROR'}
    wait_vids = [int(r['video_id']) for r in rows if str(r.get('editing_stage') or '') == 'WAITING_MATERIAL']
    all_abandonable = [int(r['video_id']) for r in rows if str(r.get('editing_stage') or '') in abandonable_stages]

    if wait_vids or all_abandonable:
        menu.addSeparator()
    if wait_vids:
        actions['abandon_wait'] = (
            menu.addAction(f'🚫 放弃「{host_name}」全部素材待齐任务 ({len(wait_vids)} 条)'),
            wait_vids,
        )
    if all_abandonable and set(all_abandonable) != set(wait_vids):
        actions['abandon_all'] = (
            menu.addAction(f'🚫 放弃「{host_name}」全部未导入任务 ({len(all_abandonable)} 条)'),
            all_abandonable,
        )
    return menu, actions


def show_host_context_menu(page, global_pos, host_key: tuple[int, int], rows: list[dict]):
    menu, actions = build_host_context_menu(page, host_key, rows, parent=page)
    if not menu.actions():
        return
    chosen = menu.exec(global_pos)
    if chosen is None:
        return
    for kind, (act, payload) in actions.items():
        if chosen == act:
            if kind == 'open_dir':
                page.open_exported_path(payload)
            elif kind == 'toggle_expand':
                toggle_host_expand(page, payload)
            elif kind in ('abandon_wait', 'abandon_all'):
                page._abandon_dv_videos(payload)
            return


def _open_video_row_error(page, row: dict):
    from app.ui.resolve_error_dialog import open_editing_error_detail
    vid = int(row.get('video_id') or 0)
    raw_st = str(row.get('edit_status') or '').strip()
    if not raw_st or raw_st in ('异常', '失败'):
        # Fall back to page's current stage error if available so video row opens the exact batch error
        stage_box = getattr(page, 'current_stage_box', None)
        if stage_box is not None and getattr(stage_box, 'error_info', None) is not None:
            open_editing_error_detail(
                page,
                stage_box.error_info,
                on_view_log=getattr(page, 'view_batch_log', None),
            )
            return
        raw_st = f'video={vid} · 剪辑状态异常'
    elif f'video={vid}' not in raw_st and f'视频 {vid}' not in raw_st and vid > 0:
        raw_st = f'video={vid} · {raw_st}'
    open_editing_error_detail(
        page,
        raw_st,
        batch_status='ERROR',
        on_view_log=getattr(page, 'view_batch_log', None),
    )


def build_video_context_menu(page, row: dict, host_rows: list[dict], parent=None) -> tuple[QMenu, dict]:
    menu = QMenu(parent or page)
    actions = {}
    stage = str(row.get('editing_stage') or '')
    if stage == 'ERROR':
        actions['err_detail'] = (menu.addAction('🔍 查看异常详情与解决办法'), row)

    out_path = str(row.get('edit_output_path') or '').strip()
    if out_path and Path(out_path).exists():
        actions['open_dir'] = (menu.addAction('📂 打开成品所在文件夹'), out_path)

    vid = int(row.get('video_id') or 0)
    host_name = str(row.get('host_name') or '')
    seq = int(row.get('video_seq') or 0)
    if vid > 0 and stage in {'WAITING_MATERIAL', 'READY_TO_EDIT', 'ERROR'}:
        actions['abandon_one'] = (
            menu.addAction(f'🚫 放弃该视频任务（{host_name} #{seq:02d}）'),
            [vid],
        )

    wait_vids = [int(r['video_id']) for r in host_rows if str(r.get('editing_stage') or '') == 'WAITING_MATERIAL']
    if len(wait_vids) > 1 and set(wait_vids) != ({vid} if vid > 0 else set()):
        actions['abandon_host_wait'] = (
            menu.addAction(f'🚫 放弃「{host_name}」全部素材待齐任务 ({len(wait_vids)} 条)'),
            wait_vids,
        )
    return menu, actions


def show_video_context_menu(page, global_pos, row: dict, host_rows: list[dict]):
    menu, actions = build_video_context_menu(page, row, host_rows, parent=page)
    if not menu.actions():
        return
    chosen = menu.exec(global_pos)
    if chosen is None:
        return
    for kind, (act, payload) in actions.items():
        if chosen == act:
            if kind == 'err_detail':
                _open_video_row_error(page, payload)
            elif kind == 'open_dir':
                page.open_exported_path(payload)
            elif kind in ('abandon_one', 'abandon_host_wait'):
                page._abandon_dv_videos(payload)
            return


def refresh_edit_monitor(page) -> bool:
    """Update recipient-grouped AI host cards in ``page.dv_cards_content`` with widget pooling."""
    if not hasattr(page, 'dv_cards_layout') or not hasattr(page, 'dv_cards_content'):
        return False

    all_rows = list(getattr(page, '_edit_rows', []) or [])
    filter_mode = str(getattr(page, '_dv_filter_mode', 'all') or 'all')
    needle = page.dv_search_input.text().strip().lower() if hasattr(page, 'dv_search_input') else ''
    auto_collapse = (
        bool(page.dv_auto_collapse_done_chk.isChecked())
        if hasattr(page, 'dv_auto_collapse_done_chk')
        else True
    )
    manual_collapse = getattr(page, '_dv_manual_recipient_collapse', None) or {}
    expanded_hosts = getattr(page, '_dv_expanded_hosts', None) or set()
    wm_cache = getattr(page, '_host_wm_cache', None) or {}

    sig = (
        getattr(page, '_queue_signature', None),
        filter_mode,
        needle,
        auto_collapse,
        tuple(sorted(manual_collapse.items())),
        tuple(sorted(expanded_hosts)),
        tuple(
            (int(k), str((v or {}).get('bound_name') or ''))
            for k, v in sorted(wm_cache.items(), key=lambda kv: int(kv[0]))
        ),
    )
    if sig == getattr(page, '_dv_cards_sig', None):
        return False
    page._dv_cards_sig = sig

    recipients = getattr(page, '_dv_monitor_recipients', None)
    if recipients is None:
        recipients = {}
        page._dv_monitor_recipients = recipients

    groups = {}
    for r in all_rows:
        rid = int(r.get('recipient_id') or 0)
        hid = int(r.get('host_id') or 0)
        g = groups.setdefault(rid, {'name': str(r.get('recipient_name') or '未命名接收人'), 'hosts': {}})
        g['hosts'].setdefault(hid, []).append(r)

    changed = _remove_missing(recipients, set(groups), page.dv_cards_layout)
    rec_order = []

    for rid, group in groups.items():
        entry = recipients.get(rid)
        if entry is None:
            card = QFrame(page.dv_cards_content, objectName='flowRecipientCard')
            box = QVBoxLayout(card)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(0)

            head_frame = _ClickableHeader(card)
            head_frame.setObjectName('flowRecipientHead')
            head_frame.setCursor(Qt.PointingHandCursor)
            head_frame.clicked.connect(lambda r=rid: toggle_recipient_collapse(page, r))
            head = QHBoxLayout(head_frame)
            head.setContentsMargins(14, 9, 14, 9)
            head.setSpacing(10)

            avatar = QLabel(objectName='flowRecAvatar')
            avatar.setFixedSize(30, 30)
            avatar.setAlignment(Qt.AlignCenter)
            head.addWidget(avatar)

            rec_name = QLabel(objectName='flowRecName')
            rec_name.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
            head.addWidget(rec_name)

            rec_badge = QLabel(objectName='flowRecBadge')
            rec_badge.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
            head.addWidget(rec_badge)

            rec_meta = _ElidingLabel('flowRecMeta', min_w=60)
            head.addWidget(rec_meta, 1)

            rec_bar = QProgressBar(objectName='flowRecBar')
            rec_bar.setFixedSize(112, 6)
            rec_bar.setTextVisible(False)
            head.addWidget(rec_bar)

            rec_pct = QLabel(objectName='flowRecPct')
            rec_pct.setMinimumWidth(38)
            rec_pct.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            head.addWidget(rec_pct)

            chevron = QLabel('收起 ▴', objectName='flowRecChevron')
            chevron.setFixedHeight(22)
            chevron.setMinimumWidth(52)
            chevron.setAlignment(Qt.AlignCenter)
            head.addWidget(chevron)

            box.addWidget(head_frame)

            grid = VariableCardGrid(minimum=315, maximum=480, base_height=_BASE_CARD_HEIGHT, spacing=10)
            grid_wrap = _DvGridBody(card, grid)
            box.addWidget(grid_wrap)

            entry = recipients[rid] = dict(
                card=card,
                head=head_frame,
                avatar=avatar,
                title=rec_name,
                badge=rec_badge,
                meta=rec_meta,
                bar=rec_bar,
                pct=rec_pct,
                chevron=chevron,
                grid_wrap=grid_wrap,
                grid=grid,
                hosts={},
                collapsed=False,
            )
            changed = True

        changed = _remove_missing(entry['hosts'], set(group['hosts']), entry['grid']) or changed

        hosts_total = len(group['hosts'])
        hosts_done = 0
        rec_err_hosts = 0
        rec_review_hosts = 0
        rec_edit_hosts = 0
        rec_ready_hosts = 0
        rec_v_total = 0
        rec_v_done = 0
        rec_v_ready_all = 0
        rec_seg_passed = 0
        rec_seg_total = 0

        visible_host_pairs = []

        for hid, h_rows in group['hosts'].items():
            h_rows_sorted = sorted(h_rows, key=lambda x: int(x.get('video_seq') or 0))
            first = h_rows_sorted[0]
            host_key = (rid, hid)
            host = entry['hosts'].get(hid)

            if host is None:
                hcard = _HostCardFrame(entry['grid_wrap'])
                outer_v = QVBoxLayout(hcard)
                outer_v.setContentsMargins(10, 10, 10, 10)
                outer_v.setSpacing(8)

                hrow = QHBoxLayout()
                hrow.setContentsMargins(0, 0, 0, 0)
                hrow.setSpacing(10)

                thumb = QLabel('无图', objectName='flowHostThumb')
                thumb.setFixedSize(54, 80)
                thumb.setAlignment(Qt.AlignCenter)
                hrow.addWidget(thumb, 0, Qt.AlignTop)

                rcol = QVBoxLayout()
                rcol.setContentsMargins(0, 0, 0, 0)
                rcol.setSpacing(4)

                top_row = QHBoxLayout()
                top_row.setContentsMargins(0, 0, 0, 0)
                top_row.setSpacing(5)
                htitle = _ElidingLabel('flowHostTitle', min_w=48)
                top_row.addWidget(htitle, 1)

                status_badge = QLabel(objectName='dvHostStatusBadge')
                status_badge.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
                top_row.addWidget(status_badge)

                open_btn = QPushButton('📂', objectName='dvHostMiniBtn')
                open_btn.setFixedWidth(28)
                open_btn.setCursor(Qt.PointingHandCursor)
                open_btn.setFocusPolicy(Qt.NoFocus)
                open_btn.setToolTip('打开该主播已导出成品所在文件夹')
                open_btn.hide()
                top_row.addWidget(open_btn)

                expand_btn = QPushButton('明细 ▾', objectName='dvHostMiniBtn')
                expand_btn.setCursor(Qt.PointingHandCursor)
                expand_btn.setFocusPolicy(Qt.NoFocus)
                expand_btn.clicked.connect(lambda _=False, hk=host_key: toggle_host_expand(page, hk))
                top_row.addWidget(expand_btn)
                rcol.addLayout(top_row)

                mid_row = QHBoxLayout()
                mid_row.setContentsMargins(0, 0, 0, 0)
                mid_row.setSpacing(5)
                vid_meta = QLabel(objectName='flowHostVideoMeta')
                mid_row.addWidget(vid_meta)

                wm_pill = _ElidingLabel('dvHostTagPill', min_w=28, max_w=112)
                wm_pill.setProperty('kind', 'wm')
                wm_pill.hide()
                mid_row.addWidget(wm_pill)

                ratio_pill = QLabel('16:9', objectName='dvHostTagPill')
                ratio_pill.setProperty('kind', 'ratio')
                ratio_pill.hide()
                mid_row.addWidget(ratio_pill)

                mid_row.addStretch(1)
                seg_meta = QLabel(objectName='flowHostSegMeta')
                mid_row.addWidget(seg_meta)
                rcol.addLayout(mid_row)

                hbar = QProgressBar(objectName='flowHostBar')
                hbar.setFixedHeight(6)
                hbar.setTextVisible(False)
                rcol.addWidget(hbar)

                hstate = _ElidingLabel('flowHostState', min_w=60)
                rcol.addWidget(hstate)

                hrow.addLayout(rcol, 1)
                outer_v.addLayout(hrow)

                drawer = QFrame(hcard, objectName='dvHostDrawer')
                drawer.hide()
                dv_lay = QVBoxLayout(drawer)
                dv_lay.setContentsMargins(0, 6, 0, 0)
                dv_lay.setSpacing(0)

                drawer_scroll = QScrollArea(drawer, objectName='dvDrawerScroll')
                drawer_scroll.setFrameShape(QFrame.NoFrame)
                drawer_scroll.setWidgetResizable(True)
                drawer_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                drawer_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

                drawer_content = QWidget(objectName='dvDrawerContent')
                drawer_rows_lay = QVBoxLayout(drawer_content)
                drawer_rows_lay.setContentsMargins(0, 0, 0, 0)
                drawer_rows_lay.setSpacing(_VIDEO_ROW_SPACING)
                drawer_scroll.setWidget(drawer_content)
                dv_lay.addWidget(drawer_scroll)
                outer_v.addWidget(drawer)

                host = entry['hosts'][hid] = dict(
                    card=hcard,
                    thumb=thumb,
                    title=htitle,
                    status_badge=status_badge,
                    open_btn=open_btn,
                    expand_btn=expand_btn,
                    vid_meta=vid_meta,
                    wm_pill=wm_pill,
                    ratio_pill=ratio_pill,
                    seg_meta=seg_meta,
                    bar=hbar,
                    state=hstate,
                    drawer=drawer,
                    drawer_scroll=drawer_scroll,
                    drawer_rows_lay=drawer_rows_lay,
                    video_rows={},
                    rows_snapshot=h_rows_sorted,
                    latest_out='',
                )
                hcard.doubleClicked.connect(
                    lambda hk=host_key, he=host: _on_host_double_clicked(page, hk, he['rows_snapshot'])
                )
                hcard.contextRequested.connect(
                    lambda gpos, hk=host_key, he=host: show_host_context_menu(page, gpos, hk, he['rows_snapshot'])
                )
                open_btn.clicked.connect(
                    lambda _=False, he=host: page.open_exported_path(he['latest_out']) if he['latest_out'] else None
                )
                changed = True

            host['rows_snapshot'] = h_rows_sorted

            # Watermark & Aspect Ratio metadata
            wm_info = wm_cache.get(hid) or {}
            wm_bound = str(wm_info.get('bound_name') or '').strip()
            aspect = str(first.get('aspect_ratio') or '9:16').strip()

            # Compute host metrics across ALL videos of this host today
            v_total = len(h_rows_sorted)
            v_done = 0
            v_exporting = 0
            v_review = 0
            v_editing = 0
            v_ready = 0
            v_wait = 0
            v_err = 0
            v_mat_ready = 0
            seg_passed = 0
            seg_total = 0
            latest_out = ''
            wait_reasons_agg = {}
            img_path = ''

            for r in h_rows_sorted:
                if not img_path and str(r.get('image_path') or '').strip():
                    img_path = str(r.get('image_path') or '').strip()
                st_stage = str(r.get('editing_stage') or '')
                seg_total += int(r.get('segment_count') or 0)
                seg_passed += int(r.get('qc_passed') or 0)
                if r.get('materials_ready'):
                    v_mat_ready += 1
                out_p = str(r.get('edit_output_path') or '').strip()
                if out_p and Path(out_p).exists():
                    latest_out = out_p
                if st_stage == 'COMPLETED':
                    v_done += 1
                elif st_stage == 'EXPORTING':
                    v_exporting += 1
                elif st_stage == 'REVIEW':
                    v_review += 1
                elif st_stage == 'EDITING':
                    v_editing += 1
                elif st_stage == 'READY_TO_EDIT':
                    v_ready += 1
                elif st_stage == 'ERROR':
                    v_err += 1
                else:
                    v_wait += 1
                    for rk, rv in (r.get('waiting_reasons') or {}).items():
                        if int(rv or 0) > 0:
                            wait_reasons_agg[rk] = wait_reasons_agg.get(rk, 0) + int(rv)

            host['latest_out'] = latest_out
            complete = (v_total > 0 and v_done == v_total)
            export_pct = 100 if complete else int(round(100.0 * v_done / max(1, v_total)))

            rec_v_total += v_total
            rec_v_done += v_done
            rec_v_ready_all += v_mat_ready
            rec_seg_passed += seg_passed
            rec_seg_total += seg_total
            if complete:
                hosts_done += 1
            elif v_err > 0:
                rec_err_hosts += 1
            elif v_review > 0:
                rec_review_hosts += 1
            elif (v_editing + v_exporting) > 0:
                rec_edit_hosts += 1
            elif v_ready > 0:
                rec_ready_hosts += 1

            # Check filter & search match
            matched_rows = []
            matched_by_detail_only = False
            for r in h_rows_sorted:
                ok_m, detail_only = row_matches_filter(r, filter_mode, needle, wm_bound)
                if ok_m:
                    matched_rows.append(r)
                    if detail_only:
                        matched_by_detail_only = True

            if not matched_rows:
                continue

            # Update thumbnail & labels
            _set_portrait_thumb(host['thumb'], img_path)
            hname_str = str(first.get('host_name') or '未命名主播')
            host['title'].set_raw_text(hname_str, f"{group['name']} / {hname_str}（画面比例 {aspect}）")

            if wm_bound:
                host['wm_pill'].set_raw_text(f'💧{wm_bound}', f'已绑定 AI 水印名字：{wm_bound}')
                if host['wm_pill'].isHidden():
                    host['wm_pill'].show()
            elif not host['wm_pill'].isHidden():
                host['wm_pill'].hide()

            if aspect == '16:9':
                host['ratio_pill'].setToolTip('横屏 16:9 主播任务')
                if host['ratio_pill'].isHidden():
                    host['ratio_pill'].show()
            elif not host['ratio_pill'].isHidden():
                host['ratio_pill'].hide()

            if latest_out:
                host['open_btn'].setToolTip(f"打开成品目录：{Path(latest_out).parent}")
                if host['open_btn'].isHidden():
                    host['open_btn'].show()
            elif not host['open_btn'].isHidden():
                host['open_btn'].hide()

            _set_text(host['vid_meta'], f'🎬 成品 {v_done} / {v_total} 条')

            # Determine card tone, status badge, progress bar value & smart summary line
            hbar = host['bar']
            if complete:
                tone = 'done'
                state_tone = 'done'
                badge_txt = '✓ 已导出'
                seg_txt = f'齐套 {v_mat_ready}/{v_total} · 100%'
                bar_max, bar_val = max(1, v_total), max(1, v_total)
                state_str = f'✓ 全部 {v_total} 条成品已导出（双击打开目录）'
            elif v_err > 0:
                tone = 'failed'
                state_tone = 'failed'
                badge_txt = f'⚠ 异常 {v_err}'
                seg_txt = f'齐套 {v_mat_ready}/{v_total} · {export_pct}%'
                bar_max, bar_val = max(1, v_total), max(1, v_done)
                state_str = f'⚠ {v_err} 条状态异常 · 已导出 {v_done}/{v_total} 条'
            elif v_exporting > 0:
                tone = 'running'
                state_tone = 'running'
                badge_txt = '⇧ 导出中'
                seg_txt = f'齐套 {v_mat_ready}/{v_total} · {export_pct}%'
                bar_max, bar_val = max(1, v_total), max(1, v_done) if v_done > 0 else v_exporting
                state_str = f'⇧ 正在批量导出 {v_exporting} 条 · 已完成 {v_done}/{v_total} 条'
            elif v_review > 0:
                tone = 'prio'
                state_tone = 'prio'
                badge_txt = '● 待检查'
                seg_txt = f'齐套 {v_mat_ready}/{v_total} · {export_pct}%' if v_done > 0 else f'齐套 {v_mat_ready}/{v_total} · 待导出'
                bar_max, bar_val = max(1, v_total), v_done if v_done > 0 else v_review
                bits = [f'● {v_review} 条在时间线待人工检查']
                if v_done:
                    bits.append(f'已导出 {v_done}')
                if v_ready:
                    bits.append(f'待剪辑 {v_ready}')
                state_str = ' · '.join(bits)
            elif v_editing > 0:
                tone = 'running'
                state_tone = 'running'
                badge_txt = '⚙ 剪辑中'
                seg_txt = f'齐套 {v_mat_ready}/{v_total} · 剪辑中'
                bar_max, bar_val = max(1, v_total), v_done if v_done > 0 else v_editing
                bits = [f'⚙ {v_editing} 条已在达芬奇剪辑中']
                if v_done:
                    bits.append(f'已导出 {v_done}')
                if v_ready:
                    bits.append(f'待导入 {v_ready}')
                state_str = ' · '.join(bits)
            elif v_ready > 0:
                tone = 'ready'
                state_tone = 'ready'
                badge_txt = '▣ 待剪辑'
                seg_txt = f'齐套 {v_mat_ready}/{v_total}' + (f' · {export_pct}%' if v_done > 0 else ' · 可导入')
                bar_max, bar_val = max(1, v_total), v_done if v_done > 0 else v_ready
                bits = [f'▣ {v_ready} 条齐套待导入达芬奇']
                if v_wait:
                    bits.append(f'◇ {v_wait} 条待齐')
                if v_done:
                    bits.append(f'✓ 已导出 {v_done}')
                state_str = ' · '.join(bits)
            else:
                tone = 'waiting'
                state_tone = 'waiting'
                badge_txt = '◇ 素材待齐'
                seg_pct = int(round(100.0 * seg_passed / max(1, seg_total))) if seg_total > 0 else 0
                seg_txt = f'片段 {seg_passed}/{seg_total} · {seg_pct}%'
                bar_max, bar_val = max(1, seg_total), seg_passed
                r_parts = [f'{k} {v}' for k, v in wait_reasons_agg.items()]
                reason_tail = ' / '.join(r_parts) if r_parts else '等待上游生成与质检'
                state_str = f'◇ {v_wait} 条素材待齐 · {reason_tail}'

            _set_text(host['status_badge'], badge_txt)
            _set_prop(host['status_badge'], 'tone', tone)
            _set_text(host['seg_meta'], seg_txt)
            if hbar.maximum() != bar_max:
                hbar.setRange(0, bar_max)
            if hbar.value() != bar_val:
                hbar.setValue(bar_val)
            _set_prop(host['card'], 'tone', tone)
            _set_prop(hbar, 'tone', tone)
            _set_prop(host['state'], 'tone', state_tone)
            host['state'].set_raw_text(state_str)

            # Inline per-video detail drawer (manual toggle OR auto-expanded on specific #seq search)
            is_expanded = (host_key in expanded_hosts) or matched_by_detail_only
            drawer_rows_source = matched_rows if (filter_mode != 'all' or matched_by_detail_only) else h_rows_sorted
            exp_txt = '收起 ▴' if is_expanded else f'明细 {len(drawer_rows_source)} ▾'
            _set_text(host['expand_btn'], exp_txt, '点击收起每条视频明细' if is_expanded else '点击展开该主播 #01 ~ #N 每条视频明细')
            _set_prop(host['expand_btn'], 'active', 'true' if is_expanded else 'false')

            if is_expanded and drawer_rows_source:
                v_cache = host['video_rows']
                valid_vids = {int(r['video_id']) for r in drawer_rows_source}
                _remove_missing(v_cache, valid_vids, host['drawer_rows_lay'])
                ordered_v_widgets = []
                for vr in drawer_rows_source:
                    vid = int(vr['video_id'])
                    v_entry = v_cache.get(vid)
                    if v_entry is None:
                        vrow = _VideoRowFrame()
                        vlay = QHBoxLayout(vrow)
                        vlay.setContentsMargins(8, 0, 6, 0)
                        vlay.setSpacing(6)

                        seq_lbl = QLabel(objectName='dvVidSeq')
                        seq_lbl.setFixedWidth(32)
                        vlay.addWidget(seq_lbl)

                        seg_lbl = QLabel(objectName='dvVidSeg')
                        seg_lbl.setFixedWidth(48)
                        vlay.addWidget(seg_lbl)

                        st_lbl_w = QLabel(objectName='dvVidStatus')
                        st_lbl_w.setFixedWidth(64)
                        vlay.addWidget(st_lbl_w)

                        path_lbl = _ElidingLabel('dvVidPath', min_w=40)
                        vlay.addWidget(path_lbl, 1)

                        from app.ui.resolve_error_dialog import make_inline_error_detail_btn
                        v_err_btn = make_inline_error_detail_btn(vrow)
                        v_err_btn.setFixedHeight(20)
                        v_err_btn.hide()
                        vlay.addWidget(v_err_btn)

                        v_open_btn = QPushButton('📂', objectName='dvHostMiniBtn')
                        v_open_btn.setFixedSize(24, 20)
                        v_open_btn.setCursor(Qt.PointingHandCursor)
                        v_open_btn.setFocusPolicy(Qt.NoFocus)
                        v_open_btn.hide()
                        vlay.addWidget(v_open_btn)

                        v_entry = v_cache[vid] = dict(
                            row=vrow,
                            seq=seq_lbl,
                            seg=seg_lbl,
                            status=st_lbl_w,
                            path=path_lbl,
                            err_btn=v_err_btn,
                            open_btn=v_open_btn,
                            data=vr,
                            out_path='',
                        )
                        vrow.doubleClicked.connect(
                            lambda ve=v_entry: page.open_exported_path(ve['out_path']) if ve['out_path'] else None
                        )
                        vrow.contextRequested.connect(
                            lambda gpos, ve=v_entry, he=host: show_video_context_menu(
                                page, gpos, ve['data'], he['rows_snapshot']
                            )
                        )
                        v_err_btn.clicked.connect(
                            lambda _=False, ve=v_entry: _open_video_row_error(page, ve['data'])
                        )
                        v_open_btn.clicked.connect(
                            lambda _=False, ve=v_entry: page.open_exported_path(ve['out_path']) if ve['out_path'] else None
                        )

                    v_entry['data'] = vr
                    seq_n = int(vr.get('video_seq') or 0)
                    v_segs = int(vr.get('segment_count') or 0)
                    v_pass = int(vr.get('qc_passed') or 0)
                    v_ready_flag = bool(vr.get('materials_ready'))
                    v_out = str(vr.get('edit_output_path') or '').strip()
                    v_out_exists = bool(v_out and Path(v_out).exists())
                    v_entry['out_path'] = v_out if v_out_exists else ''

                    st_txt, st_tone, det_txt, det_tip = _video_status_display(vr)
                    _set_text(v_entry['seq'], f'#{seq_n:02d}')
                    _set_text(v_entry['seg'], f"{'✓ ' if v_ready_flag else ''}{v_pass}/{v_segs}")
                    _set_prop(v_entry['seg'], 'ready', 'true' if v_ready_flag else 'false')
                    _set_text(v_entry['status'], st_txt)
                    _set_prop(v_entry['status'], 'tone', st_tone)
                    v_entry['path'].set_raw_text(det_txt, det_tip)
                    v_entry['row'].setToolTip(det_tip)

                    if st_tone == 'failed':
                        if v_entry['err_btn'].isHidden():
                            v_entry['err_btn'].show()
                    elif not v_entry['err_btn'].isHidden():
                        v_entry['err_btn'].hide()

                    if v_out_exists:
                        v_entry['open_btn'].setToolTip(f'打开所在文件夹：{Path(v_out).parent}')
                        if v_entry['open_btn'].isHidden():
                            v_entry['open_btn'].show()
                    elif not v_entry['open_btn'].isHidden():
                        v_entry['open_btn'].hide()

                    ordered_v_widgets.append(v_entry['row'])

                _reorder(host['drawer_rows_lay'], ordered_v_widgets)
                vis_n = min(len(ordered_v_widgets), _MAX_VISIBLE_DRAWER_ROWS)
                rows_px = vis_n * _VIDEO_ROW_HEIGHT + max(0, vis_n - 1) * _VIDEO_ROW_SPACING
                need_scroll = len(ordered_v_widgets) > _MAX_VISIBLE_DRAWER_ROWS
                host['drawer_scroll'].setVerticalScrollBarPolicy(
                    Qt.ScrollBarAsNeeded if need_scroll else Qt.ScrollBarAlwaysOff
                )
                host['drawer_scroll'].setFixedHeight(rows_px)
                if host['drawer'].isHidden():
                    host['drawer'].show()
                desired_h = _BASE_CARD_HEIGHT + 8 + 11 + rows_px
            else:
                if not host['drawer'].isHidden():
                    host['drawer'].hide()
                desired_h = _BASE_CARD_HEIGHT

            if host['card'].set_desired_height(desired_h):
                changed = True

            # Host sort order inside recipient
            if complete:
                h_sort = (5, 0, hid)
            elif v_err > 0:
                h_sort = (0, -v_err, hid)
            elif v_review > 0:
                h_sort = (1, -v_review, hid)
            elif (v_exporting + v_editing) > 0:
                h_sort = (2, -(v_exporting + v_editing), hid)
            elif v_ready > 0:
                h_sort = (3, -v_ready, hid)
            else:
                h_sort = (4, -seg_passed, hid)
            visible_host_pairs.append((h_sort, host['card']))

        # Recipient summary header
        rec_complete = (hosts_total > 0 and hosts_done == hosts_total)
        rec_pct_val = 100 if rec_complete else int(round(100.0 * rec_v_done / max(1, rec_v_total)))
        rname = group['name'] or '未命名接收人'
        _set_text(entry['avatar'], rname[:1])
        _set_text(entry['title'], rname)

        if rec_complete:
            rec_tone = 'done'
            badge_txt = '✓ 全部已导出'
            meta_txt = f'共 {hosts_total} 位主播 · {rec_v_total} 条成品视频全部导出完成'
            rbar_max, rbar_val = max(1, rec_v_total), max(1, rec_v_total)
        elif rec_err_hosts > 0:
            rec_tone = 'failed'
            badge_txt = f'⚠ 异常 {rec_err_hosts} 人'
            meta_txt = f'已完成 {hosts_done}/{hosts_total} 主播  ·  成品 {rec_v_done}/{rec_v_total} 条  ·  齐套 {rec_v_ready_all}/{rec_v_total} 条'
            rbar_max, rbar_val = max(1, rec_v_total), rec_v_done
        elif rec_review_hosts > 0:
            rec_tone = 'prio'
            badge_txt = f'● 待检查 {rec_review_hosts} 人'
            meta_txt = f'已完成 {hosts_done}/{hosts_total} 主播  ·  成品 {rec_v_done}/{rec_v_total} 条  ·  齐套 {rec_v_ready_all}/{rec_v_total} 条'
            rbar_max, rbar_val = max(1, rec_v_total), rec_v_done if rec_v_done > 0 else rec_v_ready_all
        elif rec_edit_hosts > 0:
            rec_tone = 'running'
            badge_txt = f'⚙ 剪辑/导出中 {rec_edit_hosts} 人'
            meta_txt = f'已完成 {hosts_done}/{hosts_total} 主播  ·  成品 {rec_v_done}/{rec_v_total} 条  ·  齐套 {rec_v_ready_all}/{rec_v_total} 条'
            rbar_max, rbar_val = max(1, rec_v_total), rec_v_done if rec_v_done > 0 else rec_v_ready_all
        elif rec_ready_hosts > 0:
            rec_tone = 'running'
            badge_txt = f'▣ 待剪辑 {rec_ready_hosts} 人'
            meta_txt = f'已完成 {hosts_done}/{hosts_total} 主播  ·  成品 {rec_v_done}/{rec_v_total} 条  ·  齐套可剪 {rec_v_ready_all}/{rec_v_total} 条'
            rbar_max, rbar_val = max(1, rec_v_total), rec_v_done if rec_v_done > 0 else rec_v_ready_all
        else:
            rec_tone = 'waiting'
            badge_txt = '◇ 素材待齐'
            meta_txt = f'共 {hosts_total} 位主播 · {rec_v_total} 条视频等待上游齐套（片段 {rec_seg_passed}/{rec_seg_total}）'
            rbar_max, rbar_val = max(1, rec_seg_total), rec_seg_passed

        _set_text(entry['badge'], badge_txt)
        entry['meta'].set_raw_text(meta_txt)
        rbar = entry['bar']
        if rbar.maximum() != rbar_max:
            rbar.setRange(0, rbar_max)
        if rbar.value() != rbar_val:
            rbar.setValue(rbar_val)
        _set_text(entry['pct'], f'{rec_pct_val}%')

        _set_prop(entry['card'], 'tone', rec_tone)
        _set_prop(entry['avatar'], 'tone', rec_tone)
        _set_prop(entry['badge'], 'tone', rec_tone)
        _set_prop(rbar, 'tone', rec_tone)
        _set_prop(entry['pct'], 'tone', rec_tone)

        sorted_host_widgets = [w for _, w in sorted(visible_host_pairs, key=lambda pair: pair[0])]
        visible_set = set(sorted_host_widgets)
        grid_changed = _reorder(entry['grid'], sorted_host_widgets)
        for h_entry in entry['hosts'].values():
            hc = h_entry['card']
            if hc not in visible_set and hc.isVisible():
                hc.hide()
                grid_changed = True

        # Hide entire recipient card when filter/search leaves 0 matching hosts
        if not sorted_host_widgets:
            if entry['card'].isVisible():
                entry['card'].hide()
                changed = True
            continue

        # Collapse state
        if rid in manual_collapse:
            collapsed = bool(manual_collapse[rid])
        elif needle or filter_mode != 'all':
            collapsed = False
        else:
            collapsed = bool(rec_complete and auto_collapse)
        entry['collapsed'] = collapsed
        _set_prop(entry['head'], 'collapsed', 'true' if collapsed else 'false')
        chev_char = '展开 ▾' if collapsed else '收起 ▴'
        if entry['chevron'].text() != chev_char:
            entry['chevron'].setText(chev_char)
        entry['head'].setToolTip('点击展开该接收人分组' if collapsed else '点击收起该接收人分组')

        vis_changed = (entry['grid_wrap'].isVisible() == collapsed)
        if vis_changed:
            entry['grid_wrap'].setVisible(not collapsed)
            changed = True
        if not collapsed and (grid_changed or vis_changed or changed):
            entry['grid'].invalidate()
            entry['grid_wrap'].sync_height()
            entry['card'].updateGeometry()

        if rec_complete:
            rec_sort = (5, rid)
        elif rec_err_hosts > 0:
            rec_sort = (0, rid)
        elif rec_review_hosts > 0:
            rec_sort = (1, rid)
        elif rec_edit_hosts > 0:
            rec_sort = (2, rid)
        elif rec_ready_hosts > 0:
            rec_sort = (3, rid)
        else:
            rec_sort = (4, rid)
        rec_order.append((rec_sort, entry['card']))

    ordered_recs = [w for _, w in sorted(rec_order, key=lambda pair: pair[0])]
    visible_rec_set = set(ordered_recs)
    for r_entry in recipients.values():
        rc = r_entry['card']
        if rc not in visible_rec_set and rc.isVisible():
            rc.hide()
            changed = True

    empty = getattr(page, '_dv_monitor_empty', None)
    if not ordered_recs:
        if empty is None:
            empty = QLabel(page.dv_cards_content, objectName='flowMonitorEmpty')
            empty.setAlignment(Qt.AlignCenter)
            empty.setMinimumHeight(110)
            page._dv_monitor_empty = empty
        empty_msg = (
            '今日暂无进入剪辑队列的视频任务（质检通过或进入生产管线后将自动显示）'
            if not all_rows
            else '当前筛选或搜索条件下暂无匹配的任务'
        )
        if empty.text() != empty_msg:
            empty.setText(empty_msg)
        empty.show()
        ordered_recs = [empty]
    elif empty is not None and empty.isVisible():
        empty.hide()

    changed = _reorder(page.dv_cards_layout, ordered_recs) or changed
    if not collapsed_all_check(recipients, ordered_recs):
        for r_entry in recipients.values():
            if r_entry['card'] in visible_rec_set and not r_entry['collapsed']:
                r_entry['grid_wrap'].sync_height()
    return changed


def collapsed_all_check(recipients: dict, ordered_recs: list) -> bool:
    vis = set(ordered_recs)
    return all(e['collapsed'] for e in recipients.values() if e['card'] in vis)
