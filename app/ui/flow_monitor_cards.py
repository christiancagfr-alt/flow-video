"""Keyed display widgets. Reads snapshots; never changes production state."""
import time
from pathlib import Path
from PySide6.QtCore import Qt, QSize, QPointF, QRectF, Signal
from PySide6.QtGui import QPixmap, QPainter, QColor, QIcon, QPolygonF, QPen, QPainterPath
from PySide6.QtWidgets import (
    QDialog, QFrame, QWidget, QLabel, QPushButton, QLineEdit, QProgressBar,
    QVBoxLayout, QHBoxLayout, QSizePolicy,
)
from app.ui.flow_layouts import CardGrid
from app.ui.image_preview import set_image
from app.ui.manual_video_import_dialog import ManualVideoImportDialog
from app.services.image_assets import image_cache_key
from app.services import pause_control


_ICONS={}
def _pause_icon(paused):
    """Running: green two bars (click to pause). Paused: red triangle (click to resume)."""
    if paused in _ICONS:return _ICONS[paused]
    pm=QPixmap(40,40);pm.fill(Qt.transparent)
    p=QPainter(pm);p.setRenderHint(QPainter.Antialiasing);p.setPen(Qt.NoPen)
    if paused:
        p.setBrush(QColor('#e5484d'))
        p.drawPolygon(QPolygonF([QPointF(11,6),QPointF(34,20),QPointF(11,34)]))
    else:
        p.setBrush(QColor('#30a46c'))
        p.drawRoundedRect(9,6,8,28,2,2);p.drawRoundedRect(23,6,8,28,2,2)
    p.end()
    _ICONS[paused]=QIcon(pm);return _ICONS[paused]


class _DoubleClickButton(QPushButton):
    """Icon button that only fires ``doubleClicked`` (single clicks are ignored)."""
    doubleClicked=Signal()
    def mouseDoubleClickEvent(self,event):
        if event.button()==Qt.LeftButton:self.doubleClicked.emit()
        event.accept()
    def mouseReleaseEvent(self,event):
        event.accept()


def _open_icon():
    """Curved arrow (no border)."""
    if 'open' in _ICONS:return _ICONS['open']
    pm=QPixmap(40,40);pm.fill(Qt.transparent)
    p=QPainter(pm);p.setRenderHint(QPainter.Antialiasing)
    pen=QPen(QColor('#3b82f6'),4.2);pen.setCapStyle(Qt.RoundCap);pen.setJoinStyle(Qt.RoundJoin);p.setPen(pen)
    path=QPainterPath();path.moveTo(8,32);path.quadTo(8,12,26,12);p.drawPath(path)
    p.setPen(Qt.NoPen);p.setBrush(QColor('#3b82f6'))
    p.drawPolygon(QPolygonF([QPointF(24,4),QPointF(36,12),QPointF(24,20)]))
    p.end();_ICONS['open']=QIcon(pm);return _ICONS['open']


def _delete_icon():
    """Red cross (no border)."""
    if 'delete' in _ICONS:return _ICONS['delete']
    pm=QPixmap(40,40);pm.fill(Qt.transparent)
    p=QPainter(pm);p.setRenderHint(QPainter.Antialiasing)
    pen=QPen(QColor('#e5484d'),4.6);pen.setCapStyle(Qt.RoundCap);p.setPen(pen)
    p.drawLine(11,11,29,29);p.drawLine(29,11,11,29)
    p.end();_ICONS['delete']=QIcon(pm);return _ICONS['delete']


_ICON_BTN_STYLE='QPushButton{border:none;background:transparent;padding:0;}QPushButton:hover{background:transparent;}QPushButton:pressed{background:transparent;}'


def _icon_button(icon,tip,cls=QPushButton):
    b=cls();b.setIcon(icon);b.setIconSize(QSize(20,20));b.setFixedSize(28,28);b.setFlat(True)
    b.setCursor(Qt.PointingHandCursor);b.setToolTip(tip);b.setFocusPolicy(Qt.NoFocus);b.setStyleSheet(_ICON_BTN_STYLE)
    return b


def _pause_button(kind):
    sz = 26 if kind == 'host' else 30
    isz = 15 if kind == 'host' else 18
    b=QPushButton();b.setFixedSize(sz,sz);b.setIconSize(QSize(isz,isz));b.setFlat(True)
    b.setCursor(Qt.PointingHandCursor);b.setFocusPolicy(Qt.NoFocus)
    b.setProperty('fs_paused',None);b.setProperty('fs_kind',kind)
    b.setStyleSheet('QPushButton{border:1px solid rgba(127,127,127,0.32);border-radius:6px;padding:0;background:transparent;}'
                    'QPushButton:hover{background:rgba(127,127,127,0.14);}')
    return b


class _ClickableHeader(QFrame):
    clicked = Signal()
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class _GridBody(QWidget):
    """Wraps CardGrid so QScrollArea always honors exact multi-row heightForWidth."""
    def __init__(self, parent, grid: CardGrid):
        super().__init__(parent)
        self.setObjectName('flowRecipientBody')
        self._grid = grid
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 12)
        lay.setSpacing(0)
        lay.addLayout(grid)

    def sync_height(self):
        lay = self.layout()
        if lay is None or self.width() <= 40:
            return
        m = lay.contentsMargins()
        avail_w = max(1, self.width() - m.left() - m.right())
        h = (self._grid.heightForWidth(avail_w) if self._grid.count() > 0 else 0) + m.top() + m.bottom()
        if self.minimumHeight() != h or self.maximumHeight() != h:
            self.setFixedHeight(h)
            self.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.sync_height()


class _ElidingLabel(QLabel):
    def __init__(self, object_name='', min_w=36):
        super().__init__(objectName=object_name)
        self._raw = ''
        self.setMinimumWidth(min_w)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def set_raw_text(self, value: str):
        value = str(value or '')
        if self._raw == value:
            return
        self._raw = value
        self.setToolTip(value)
        self._update_elided()

    def _update_elided(self):
        w = self.width()
        if w <= 20:
            super().setText(self._raw)
        else:
            super().setText(self.fontMetrics().elidedText(self._raw, Qt.ElideRight, max(20, w - 2)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_elided()


def _set_prop(widget, name: str, value: str):
    if widget.property(name) == value:
        return False
    widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    return True


def _rounded_portrait_pixmap(image):
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


def _toggle_rec_collapse(page, rid: int):
    manual = getattr(page, '_manual_recipient_collapse', None)
    if manual is None:
        manual = {}
        page._manual_recipient_collapse = manual
    entry = getattr(page, '_monitor_recipients', {}).get(rid)
    cur = bool(entry.get('collapsed', False)) if entry else False
    manual[rid] = not cur
    page.refresh_visual_monitor()


def _sync_pause(b,paused):
    if b.property('fs_paused')==paused:return
    b.setProperty('fs_paused',paused);b.setIcon(_pause_icon(paused))
    what='通道' if b.property('fs_kind')=='channel' else '主播'
    b.setToolTip(f'{what}已暂停：不再派发新任务，点击恢复' if paused else f'{what}运行中：点击暂停（已发出的任务会正常完成）')


def _toggle(b,fn,key):
    try:_sync_pause(b,fn(key))
    except Exception as exc:b.setToolTip(f'切换失败：{exc}')


def _wake_plugin(page):
    """Make connected Flow tabs re-read the pause flag immediately instead of on their next poll."""
    try:page.bridge.touch_host_jobs()
    except Exception:pass


def _open_host_manual_import(page, hid: int):
    dlg = ManualVideoImportDialog(
        page,
        scope='host',
        target_id=int(hid),
        bridge=getattr(page, 'bridge', None),
    )
    if dlg.exec() == QDialog.Accepted:
        if hasattr(page, 'refresh_data'):
            page.refresh_data()
        elif hasattr(page, 'refresh_visual_monitor'):
            page.refresh_visual_monitor()


def text(widget,value):
    value=str(value)
    if widget.text()!=value:widget.setText(value);widget.setToolTip(value)


def label(style):
    w=QLabel(objectName=style);w.setMinimumWidth(0);w.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred)
    return w


def reorder(layout,widgets):
    if [layout.itemAt(i).widget() for i in range(layout.count())]==widgets:return False
    # Reorder layout items only. Keep the actual cards, images, edits and signals.
    while layout.count():layout.takeAt(0)
    for w in widgets:layout.addWidget(w);w.show()
    return True


def remove_missing(cache,keys,layout):
    changed=False
    for key in list(cache):
        if key not in keys:
            card=cache.pop(key)['card'];layout.removeWidget(card);card.hide();card.deleteLater();changed=True
    return changed


def channel_state(channel,dispatches,alive):
    if not alive:return '未连接'
    generating=sum(str(d['status'] or '')=='submitted' for d in dispatches)
    downloading=sum(str(d['status'] or '')=='downloading' for d in dispatches)
    processing=sum(str(d['status'] or '') in ('planned','queued') for d in dispatches)
    bits=[]
    if processing:bits.append(f'处理中 {processing}')
    if generating:bits.append(f'生成中 {generating}')
    if downloading:bits.append(f'下载中 {downloading}')
    if bits:return ' · '.join(bits)
    if channel['task_command_id'] or str(channel['upload_state'] or '') in ('queued','uploading'):return '处理中'
    return '空闲'


def refresh(page,tasks,dispatches,channels,now,day,priority_hosts):
    cache=getattr(page,'_monitor_channels',None)
    if cache is None:cache={};page._monitor_channels=cache
    by_channel={}
    for d in dispatches:by_channel.setdefault(str(d['channel_key']),[]).append(d)
    pend=getattr(page,'_pending_removed_channels',None)
    if pend:
        t_now=time.time()
        for k in [k for k,v in pend.items() if v<t_now]:pend.pop(k,None)
        channels=[c for c in channels if str(c['channel_key']) not in pend]   # never let a removed card flash back
    changed=remove_missing(cache,{str(c['channel_key']) for c in channels},page.visual_channel_grid)
    try:paused_ch=pause_control.paused_channels();paused_hosts=pause_control.paused_hosts()
    except Exception:paused_ch=set();paused_hosts=set()
    ordered=[]
    for c in channels:
        key=str(c['channel_key']);entry=cache.get(key)
        if entry is None:
            card=QFrame(objectName='channelCard');card.setFixedHeight(150);card.setMinimumWidth(0)
            box=QVBoxLayout(card);box.setContentsMargins(10,8,10,8);box.setSpacing(5)
            title=label('cardTitle');state=label('cardMeta')
            head=QHBoxLayout();head.setSpacing(6);head.addWidget(title,1);pause_btn=_pause_button('channel');head.addWidget(pause_btn);box.addLayout(head);box.addWidget(state)
            pause_btn.clicked.connect(lambda _=False,k=key,b=pause_btn:(_toggle(b,pause_control.toggle_channel,k),_wake_plugin(page)))
            link=QLineEdit();link.setPlaceholderText('独立的 Flow 集合链接');link.setToolTip(f'{key}：编辑完成自动保存')
            link.editingFinished.connect(lambda k=key,e=link:page._save_pool_link(k,e));box.addWidget(link)
            buttons=QHBoxLayout();buttons.setSpacing(10);buttons.addStretch(1)
            open_btn=_icon_button(_open_icon(),'打开通道');open_btn.clicked.connect(lambda _=False,k=key:page.open_channel_link(k));buttons.addWidget(open_btn)
            delete=_icon_button(_delete_icon(),'双击删除该通道',_DoubleClickButton)
            delete.doubleClicked.connect(lambda k=key,c=card:(c.hide(),page.remove_pool_channel(k)));buttons.addWidget(delete);box.addLayout(buttons)
            entry=cache[key]=dict(card=card,title=title,state=state,link=link,pause=pause_btn);changed=True
        alive=bool(c['last_seen'] and now-float(c['last_seen'])<8)
        text(entry['title'],f"{key} · {'高速返工' if c['role']=='fast' else '普通通道'} {'●' if alive else '○'}")
        ch_paused=key in paused_ch;_sync_pause(entry['pause'],ch_paused)
        text(entry['state'],channel_state(c,by_channel.get(key,[]),alive)+(' · ⏸ 已暂停派发' if ch_paused else ''))
        if not entry['link'].hasFocus() and not entry['link'].isModified():text(entry['link'],c['collection_url'] or '')
        ordered.append(entry['card'])
    changed=reorder(page.visual_channel_grid,ordered) or changed
    if changed:page.visual_channel_scroll.schedule()

    recipients = getattr(page, '_monitor_recipients', None)
    if recipients is None:
        recipients = {}
        page._monitor_recipients = recipients
    groups = {}
    for t in tasks:
        rid = int(t['recipient_id'])
        hid = int(t['host_id'])
        group = groups.setdefault(rid, dict(name=str(t['recipient_name'] or ''), hosts={}))
        group['hosts'].setdefault(hid, []).append(t)
    changed = remove_missing(recipients, set(groups), page.visual_progress_layout)

    gen_by_seg = {}
    dl_by_seg = {}
    proc_by_seg = {}
    for d in dispatches:
        sid = int(d['segment_id'])
        st = str(d['status'] or '')
        fst = str(d.get('flow_status', '') or '')
        ck = str(d.get('channel_key') or '').strip()
        if st == 'downloading' and fst != '已完成':
            dl_by_seg[sid] = ck
        elif st == 'submitted' and (not fst or fst in ('已提交', '生成中')):
            gen_by_seg[sid] = ck
        elif st in ('planned', 'queued'):
            proc_by_seg[sid] = ck

    prio_list = [int(h) for h in (priority_hosts or [])]
    prio_rank = {h: idx for idx, h in enumerate(prio_list)}
    filter_mode = str(getattr(page, '_prog_filter_mode', 'all') or 'all')
    auto_collapse = bool(page.auto_collapse_done_chk.isChecked()) if hasattr(page, 'auto_collapse_done_chk') else True
    manual_collapse = getattr(page, '_manual_recipient_collapse', None) or {}

    pill_counts = {'all': 0, 'running': 0, 'failed': 0, 'waiting': 0, 'done': 0}
    rec_order = []

    for rid, group in groups.items():
        entry = recipients.get(rid)
        if entry is None:
            card = QFrame(page.visual_progress_content, objectName='flowRecipientCard')
            box = QVBoxLayout(card)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(0)

            head_frame = _ClickableHeader(card)
            head_frame.setObjectName('flowRecipientHead')
            head_frame.setCursor(Qt.PointingHandCursor)
            head_frame.clicked.connect(lambda r=rid: _toggle_rec_collapse(page, r))
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

            grid = CardGrid(minimum=305, maximum=480, card_height=100)
            grid_wrap = _GridBody(card, grid)
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

        changed = remove_missing(entry['hosts'], set(group['hosts']), entry['grid']) or changed

        hosts_total = len(group['hosts'])
        hosts_done = 0
        rec_running_hosts = 0
        rec_failed_hosts = 0
        rec_prio_hosts = 0
        rec_v_done = 0
        rec_v_total = 0
        rec_seg_done = 0
        rec_seg_total = 0

        visible_host_pairs = []
        for hid, rows in group['hosts'].items():
            host = entry['hosts'].get(hid)
            first = rows[0]
            if host is None:
                hcard = QFrame(entry['grid_wrap'], objectName='flowHostCard')
                hcard.setFixedHeight(100)
                hcard.setMinimumWidth(0)
                hrow = QHBoxLayout(hcard)
                hrow.setContentsMargins(10, 10, 10, 10)
                hrow.setSpacing(10)

                thumb = QLabel('无图', objectName='flowHostThumb')
                thumb.setFixedSize(54, 78)
                thumb.setAlignment(Qt.AlignCenter)
                hrow.addWidget(thumb)

                rcol = QVBoxLayout()
                rcol.setContentsMargins(0, 0, 0, 0)
                rcol.setSpacing(4)

                top_row = QHBoxLayout()
                top_row.setContentsMargins(0, 0, 0, 0)
                top_row.setSpacing(6)
                htitle = _ElidingLabel('flowHostTitle', min_w=48)
                top_row.addWidget(htitle, 1)

                done_badge = QLabel('✓ 已进质检', objectName='flowHostDoneBadge')
                done_badge.hide()
                top_row.addWidget(done_badge)

                import_btn = QPushButton('📤', objectName='dlHostMiniBtn')
                import_btn.setProperty('kind', 'import')
                import_btn.setProperty('iconOnly', 'true')
                import_btn.setCursor(Qt.PointingHandCursor)
                import_btn.setFocusPolicy(Qt.NoFocus)
                import_btn.setToolTip('从外部按序号批量导入该主播的视频片段')
                import_btn.clicked.connect(lambda _=False, h=hid: _open_host_manual_import(page, h))
                top_row.addWidget(import_btn)

                prio_btn = QPushButton('优先生成', objectName='flowHostPrioBtn')
                prio_btn.setCursor(Qt.PointingHandCursor)
                prio_btn.setFocusPolicy(Qt.NoFocus)
                top_row.addWidget(prio_btn)

                pause_btn = _pause_button('host')
                pause_btn.clicked.connect(lambda _=False, h=hid, b=pause_btn: (_toggle(b, pause_control.toggle_host, h), page.refresh_visual_monitor()))
                top_row.addWidget(pause_btn)
                rcol.addLayout(top_row)

                mid_row = QHBoxLayout()
                mid_row.setContentsMargins(0, 0, 0, 0)
                mid_row.setSpacing(6)
                vid_meta = QLabel(objectName='flowHostVideoMeta')
                seg_meta = QLabel(objectName='flowHostSegMeta')
                mid_row.addWidget(vid_meta)
                mid_row.addStretch(1)
                mid_row.addWidget(seg_meta)
                rcol.addLayout(mid_row)

                hbar = QProgressBar(objectName='flowHostBar')
                hbar.setFixedHeight(6)
                hbar.setTextVisible(False)
                rcol.addWidget(hbar)

                hstate = _ElidingLabel('flowHostState', min_w=60)
                rcol.addWidget(hstate)

                hrow.addLayout(rcol, 1)
                host = entry['hosts'][hid] = dict(
                    card=hcard,
                    thumb=thumb,
                    title=htitle,
                    done_badge=done_badge,
                    button=prio_btn,
                    pause=pause_btn,
                    vid_meta=vid_meta,
                    seg_meta=seg_meta,
                    bar=hbar,
                    state=hstate,
                    day=day,
                    image_key=None,
                )
                prio_btn.clicked.connect(lambda _=False, h=hid, e=host: page._toggle_host_priority(h, e['day']))
                changed = True

            host['day'] = day

            # Complete-video metrics (exclude legacy aux pseudo-segments)
            by_vid = {}
            for t in rows:
                if int(t.get('seg_seq') or 0) >= 1000 and '[LEGACY_AUX]' in str(t.get('foreign_text') or ''):
                    continue
                by_vid.setdefault(int(t['video_id']), []).append(t)
            v_total = len(by_vid)
            v_done = sum(
                1 for segs in by_vid.values()
                if segs and all(str(s['flow_status'] or '') == '已完成' or bool(s.get('_output_exists')) for s in segs)
            )

            total = len(rows)
            done = 0
            gen_cnt = 0
            dl_cnt = 0
            proc_cnt = 0
            fail_cnt = 0
            active_chs = []
            seen_chs = set()
            for t in rows:
                sid = int(t['segment_id'])
                st = str(t['flow_status'] or '')
                if st == '已完成' or bool(t.get('_output_exists')):
                    done += 1
                elif sid in dl_by_seg:
                    dl_cnt += 1
                    ck = dl_by_seg[sid]
                    if ck and ck not in seen_chs:
                        seen_chs.add(ck); active_chs.append(ck)
                elif sid in gen_by_seg:
                    gen_cnt += 1
                    ck = gen_by_seg[sid]
                    if ck and ck not in seen_chs:
                        seen_chs.add(ck); active_chs.append(ck)
                elif sid in proc_by_seg:
                    proc_cnt += 1
                    ck = proc_by_seg[sid]
                    if ck and ck not in seen_chs:
                        seen_chs.add(ck); active_chs.append(ck)
                elif st in ('失败', '下载失败'):
                    fail_cnt += 1
            wait_cnt = max(0, total - done - gen_cnt - dl_cnt - proc_cnt - fail_cnt)
            active_cnt = gen_cnt + dl_cnt + proc_cnt
            complete = (total > 0 and done == total)
            pct = 100 if complete else int(round(100.0 * done / max(1, total)))

            is_prio = (not complete) and (hid in prio_rank)
            h_paused = hid in paused_hosts

            # Accumulate global filter pill counts & recipient totals
            pill_counts['all'] += 1
            if complete:
                pill_counts['done'] += 1
                hosts_done += 1
            else:
                if active_cnt > 0:
                    pill_counts['running'] += 1
                    rec_running_hosts += 1
                if fail_cnt > 0:
                    pill_counts['failed'] += 1
                    rec_failed_hosts += 1
                if active_cnt == 0 and fail_cnt == 0:
                    pill_counts['waiting'] += 1
                if is_prio:
                    rec_prio_hosts += 1

            rec_v_done += v_done
            rec_v_total += v_total
            rec_seg_done += done
            rec_seg_total += total

            # Update Host Card widgets
            host['title'].set_raw_text(str(first['host_name'] or '未命名主播'))
            text(host['vid_meta'], f'🎬 视频 {v_done} / {v_total} 条')
            text(host['seg_meta'], f'片段 {done}/{total} · {pct}%')

            hbar = host['bar']
            max_bar = max(1, total)
            if hbar.maximum() != max_bar:
                hbar.setRange(0, max_bar)
            val_bar = max_bar if complete else done
            if hbar.value() != val_bar:
                hbar.setValue(val_bar)

            if complete:
                if not host['done_badge'].isVisible():
                    host['done_badge'].show()
                if host['button'].isVisible():
                    host['button'].hide()
                if host['pause'].isVisible():
                    host['pause'].hide()
            else:
                if host['done_badge'].isVisible():
                    host['done_badge'].hide()
                if not host['button'].isVisible():
                    host['button'].show()
                if not host['pause'].isVisible():
                    host['pause'].show()
                btn_lbl = '⚡ 优先中' if is_prio else '优先生成'
                text(host['button'], btn_lbl)
                host['button'].setToolTip('点击取消该主播手动插队优先' if is_prio else '点击让该主播立即插队优先生成')
                _set_prop(host['button'], 'active', 'true' if is_prio else 'false')
                _sync_pause(host['pause'], h_paused)

            image_key, image = page._view_cache['images'].get(hid, (None, None))
            if image_key != host['image_key']:
                if image is not None:
                    host['thumb'].setText('')
                    host['thumb'].setPixmap(_rounded_portrait_pixmap(image))
                else:
                    host['thumb'].setPixmap(QPixmap())
                    host['thumb'].setText('无图')
                host['image_key'] = image_key

            # Card visual tone & status text
            if complete:
                tone = 'done'
                state_tone = 'done'
                state_str = f'✓ 全部 {v_total} 条完整视频已提交质检'
            elif active_cnt > 0:
                tone = 'prio' if is_prio else 'running'
                state_tone = 'failed' if fail_cnt > 0 else ('prio' if is_prio else 'running')
                ch_txt = '/'.join(active_chs[:2]) + (f'+{len(active_chs) - 2}' if len(active_chs) > 2 else '')
                bits = [f'● {ch_txt}' if ch_txt else '● 运行中']
                if gen_cnt:
                    bits.append(f'生成中 {gen_cnt}')
                if dl_cnt:
                    bits.append(f'下载中 {dl_cnt}')
                if proc_cnt:
                    bits.append(f'准备中 {proc_cnt}')
                if fail_cnt:
                    bits.append(f'⚠ 异常 {fail_cnt}')
                elif wait_cnt:
                    bits.append(f'待发 {wait_cnt}')
                state_str = ('⏸ 暂停新派发 · ' if h_paused else '') + ' · '.join(bits)
            elif h_paused:
                tone = 'paused'
                state_tone = 'failed' if fail_cnt > 0 else 'paused'
                state_str = f'⏸ 已暂停派发 · ⚠ 异常 {fail_cnt} · 待发 {wait_cnt}' if fail_cnt else f'⏸ 已暂停派发 · 待发 {wait_cnt}'
            elif fail_cnt > 0:
                tone = 'prio' if is_prio else 'failed'
                state_tone = 'failed'
                state_str = f'⚠ 异常 {fail_cnt} 条 · 待发 {wait_cnt}' if wait_cnt else f'⚠ 异常 {fail_cnt} 条（待重试）'
            elif is_prio:
                tone = 'prio'
                state_tone = 'prio'
                state_str = f'⚡ 优先插队中 · 待发 {wait_cnt}'
            else:
                tone = 'waiting'
                state_tone = 'waiting'
                state_str = f'⏳ 排队等待通道 · 待发 {wait_cnt}'

            _set_prop(host['card'], 'tone', tone)
            _set_prop(hbar, 'tone', tone)
            _set_prop(host['state'], 'tone', state_tone)
            host['state'].set_raw_text(state_str)

            # Check filter match
            if filter_mode == 'all':
                match = True
            elif filter_mode == 'running':
                match = (not complete) and active_cnt > 0
            elif filter_mode == 'failed':
                match = (not complete) and fail_cnt > 0
            elif filter_mode == 'waiting':
                match = (not complete) and active_cnt == 0 and fail_cnt == 0
            elif filter_mode == 'done':
                match = complete
            else:
                match = True

            if match:
                if complete:
                    s_key = (4, 0, 0, hid)
                elif is_prio:
                    s_key = (0, prio_rank.get(hid, 9999), -active_cnt, hid)
                elif active_cnt > 0:
                    s_key = (1, -active_cnt, -done, hid)
                elif fail_cnt > 0:
                    s_key = (2, -fail_cnt, -done, hid)
                else:
                    s_key = (3, 1 if h_paused else 0, -done, hid)
                visible_host_pairs.append((s_key, host['card']))

        # Update Recipient Header
        rec_complete = (hosts_total > 0 and hosts_done == hosts_total)
        rec_pct_val = 100 if rec_complete else int(round(100.0 * rec_seg_done / max(1, rec_seg_total)))
        rname = group['name'] or '未命名接收人'
        text(entry['avatar'], rname[:1])
        text(entry['title'], rname)

        if rec_complete:
            rec_tone = 'done'
            badge_txt = '✓ 全部已进质检'
            meta_txt = f'共 {hosts_total} 位主播 · {rec_v_total} 条完整视频（{rec_seg_total} 个片段）全部完成'
        elif rec_prio_hosts > 0:
            rec_tone = 'prio'
            badge_txt = f'⚡ 优先生产 {rec_prio_hosts} 人'
            meta_txt = f'已完成 {hosts_done}/{hosts_total} 主播  ·  完整视频 {rec_v_done}/{rec_v_total} 条  ·  片段 {rec_seg_done}/{rec_seg_total}'
        elif rec_running_hosts > 0:
            rec_tone = 'running'
            badge_txt = f'● 生成中 {rec_running_hosts} 人'
            meta_txt = f'已完成 {hosts_done}/{hosts_total} 主播  ·  完整视频 {rec_v_done}/{rec_v_total} 条  ·  片段 {rec_seg_done}/{rec_seg_total}'
        elif rec_failed_hosts > 0:
            rec_tone = 'failed'
            badge_txt = f'⚠ 异常 {rec_failed_hosts} 人'
            meta_txt = f'已完成 {hosts_done}/{hosts_total} 主播  ·  完整视频 {rec_v_done}/{rec_v_total} 条  ·  片段 {rec_seg_done}/{rec_seg_total}'
        else:
            rec_tone = 'waiting'
            badge_txt = '⏳ 排队中'
            meta_txt = f'已完成 {hosts_done}/{hosts_total} 主播  ·  完整视频 {rec_v_done}/{rec_v_total} 条  ·  片段 {rec_seg_done}/{rec_seg_total}'

        text(entry['badge'], badge_txt)
        entry['meta'].set_raw_text(meta_txt)
        rbar = entry['bar']
        rmax = max(1, rec_seg_total)
        if rbar.maximum() != rmax:
            rbar.setRange(0, rmax)
        rval = rmax if rec_complete else rec_seg_done
        if rbar.value() != rval:
            rbar.setValue(rval)
        text(entry['pct'], f'{rec_pct_val}%')

        _set_prop(entry['card'], 'tone', rec_tone)
        _set_prop(entry['avatar'], 'tone', rec_tone)
        _set_prop(entry['badge'], 'tone', rec_tone)
        _set_prop(rbar, 'tone', rec_tone)
        _set_prop(entry['pct'], 'tone', rec_tone)

        sorted_host_widgets = [w for _, w in sorted(visible_host_pairs, key=lambda pair: pair[0])]
        visible_set = set(sorted_host_widgets)
        grid_changed = reorder(entry['grid'], sorted_host_widgets)
        for h_entry in entry['hosts'].values():
            hc = h_entry['card']
            if hc not in visible_set and hc.isVisible():
                hc.hide()
                grid_changed = True
        if grid_changed:
            entry['grid'].invalidate()
            entry['grid_wrap'].sync_height()
            changed = True

        # Determine collapse state
        if rid in manual_collapse:
            collapsed = bool(manual_collapse[rid])
        else:
            collapsed = bool(rec_complete and auto_collapse and filter_mode == 'all')
        entry['collapsed'] = collapsed
        _set_prop(entry['head'], 'collapsed', 'true' if collapsed else 'false')
        chev_char = '展开 ▾' if collapsed else '收起 ▴'
        if entry['chevron'].text() != chev_char:
            entry['chevron'].setText(chev_char)
        entry['head'].setToolTip('点击展开该接收人分组' if collapsed else '点击收起该接收人分组')
        if entry['grid_wrap'].isVisible() == collapsed:
            entry['grid_wrap'].setVisible(not collapsed)
            if not collapsed:
                entry['grid_wrap'].sync_height()
            entry['card'].updateGeometry()
            changed = True

        # Hide entire recipient card when an active filter has 0 matching hosts in this group
        if filter_mode != 'all' and not sorted_host_widgets:
            if entry['card'].isVisible():
                entry['card'].hide()
                changed = True
            continue

        if rec_complete:
            rec_sort_key = (4, rid)
        elif rec_prio_hosts > 0:
            rec_sort_key = (0, rid)
        elif rec_running_hosts > 0:
            rec_sort_key = (1, rid)
        elif rec_failed_hosts > 0:
            rec_sort_key = (2, rid)
        else:
            rec_sort_key = (3, rid)
        rec_order.append((rec_sort_key, entry['card']))

    # Sync top filter pill texts & alert highlight
    pill_btns = getattr(page, '_prog_filter_btns', None)
    if isinstance(pill_btns, dict):
        pill_labels = {
            'all': f"全部 {pill_counts['all']}",
            'running': f"● 生成中 {pill_counts['running']}",
            'failed': f"⚠ 异常 {pill_counts['failed']}",
            'waiting': f"⏳ 排队 {pill_counts['waiting']}",
            'done': f"✓ 已完成 {pill_counts['done']}",
        }
        for mode_k, lbl_txt in pill_labels.items():
            btn = pill_btns.get(mode_k)
            if btn is not None and btn.text() != lbl_txt:
                btn.setText(lbl_txt)
        fail_btn = pill_btns.get('failed')
        if fail_btn is not None:
            _set_prop(fail_btn, 'hasAlert', 'true' if pill_counts['failed'] > 0 else 'false')

    ordered = [w for _, w in sorted(rec_order, key=lambda pair: pair[0])]
    visible_rec_set = set(ordered)
    for r_entry in recipients.values():
        rc = r_entry['card']
        if rc not in visible_rec_set and rc.isVisible():
            rc.hide()
            changed = True

    empty = getattr(page, '_monitor_empty', None)
    if not ordered:
        if empty is None:
            empty = QLabel(page.visual_progress_content, objectName='flowMonitorEmpty')
            empty.setAlignment(Qt.AlignCenter)
            empty.setMinimumHeight(96)
            page._monitor_empty = empty
        empty_msg = '暂无生产任务' if not groups else '当前筛选条件下暂无匹配的主播任务'
        if empty.text() != empty_msg:
            empty.setText(empty_msg)
        empty.show()
        ordered = [empty]
    elif empty is not None and empty.isVisible():
        empty.hide()
    changed = reorder(page.visual_progress_layout, ordered) or changed
    if changed:
        page.visual_progress_scroll.schedule()
