"""Keyed display widgets. Reads snapshots; never changes production state."""
import time
from pathlib import Path
from PySide6.QtCore import Qt, QSize, QPointF, Signal
from PySide6.QtGui import QPixmap, QPainter, QColor, QIcon, QPolygonF, QPen, QPainterPath
from PySide6.QtWidgets import QFrame,QLabel,QPushButton,QLineEdit,QVBoxLayout,QHBoxLayout,QSizePolicy
from app.ui.flow_layouts import CardGrid
from app.ui.image_preview import set_image
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
    b=QPushButton();b.setFixedSize(30,30);b.setIconSize(QSize(18,18));b.setFlat(True)
    b.setCursor(Qt.PointingHandCursor);b.setProperty('fs_paused',None);b.setProperty('fs_kind',kind)
    b.setStyleSheet('QPushButton{border:1px solid rgba(127,127,127,0.35);border-radius:6px;padding:0;background:transparent;}'
                    'QPushButton:hover{background:rgba(127,127,127,0.15);}')
    return b


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
    for w in widgets:layout.addWidget(w)
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

    recipients=getattr(page,'_monitor_recipients',None)
    if recipients is None:recipients={};page._monitor_recipients=recipients
    groups={}
    for t in tasks:
        rid=int(t['recipient_id']);hid=int(t['host_id'])
        group=groups.setdefault(rid,dict(name=t['recipient_name'],hosts={}))
        group['hosts'].setdefault(hid,[]).append(t)
    changed=remove_missing(recipients,set(groups),page.visual_progress_layout)
    generating={int(d['segment_id']) for d in dispatches if str(d['status'] or '')=='submitted'}
    downloading={int(d['segment_id']) for d in dispatches if str(d['status'] or '')=='downloading'}
    processing={int(d['segment_id']) for d in dispatches if str(d['status'] or '') in ('planned','queued')}
    ordered=[]
    for rid,group in groups.items():
        entry=recipients.get(rid)
        if entry is None:
            card=QFrame(objectName='compactCard');box=QVBoxLayout(card);box.setContentsMargins(12,10,12,10);box.setSpacing(7)
            head=QHBoxLayout();initial=QLabel(objectName='recipientInitial');initial.setAlignment(Qt.AlignCenter);head.addWidget(initial)
            titlebox=QVBoxLayout();title=label('cardTitle');count=label('cardMeta');titlebox.addWidget(title);titlebox.addWidget(count);head.addLayout(titlebox);head.addStretch(1);box.addLayout(head)
            grid=CardGrid(minimum=270,maximum=460,card_height=84);box.addLayout(grid)
            entry=recipients[rid]=dict(card=card,initial=initial,title=title,count=count,grid=grid,hosts={});changed=True
        text(entry['initial'],(group['name'] or '?')[:1]);text(entry['title'],group['name']);text(entry['count'],f"{len(group['hosts'])} 个主播")
        changed=remove_missing(entry['hosts'],set(group['hosts']),entry['grid']) or changed
        host_order=[]
        for hid,rows in group['hosts'].items():
            host=entry['hosts'].get(hid);first=rows[0]
            if host is None:
                card=QFrame(objectName='hostCard');card.setFixedHeight(84);card.setMinimumWidth(0);box=QVBoxLayout(card);box.setContentsMargins(9,8,9,8);box.setSpacing(4)
                row=QHBoxLayout();thumb=QLabel('图',objectName='thumb');thumb.setFixedSize(48,48);thumb.setAlignment(Qt.AlignCenter);row.addWidget(thumb)
                details=QVBoxLayout();title=label('cardTitle');count=label('cardMeta');details.addWidget(title);details.addWidget(count);row.addLayout(details,1)
                pause_btn=_pause_button('host');row.addWidget(pause_btn)
                pause_btn.clicked.connect(lambda _=False,h=hid,b=pause_btn:_toggle(b,pause_control.toggle_host,h))
                button=QPushButton('优先生成');row.addWidget(button);box.addLayout(row);state=label('muted');box.addWidget(state)
                host=entry['hosts'][hid]=dict(card=card,thumb=thumb,title=title,count=count,state=state,button=button,pause=pause_btn,day=day,image_key=None)
                button.clicked.connect(lambda _=False,h=hid,e=host:page._toggle_host_priority(h,e['day']));changed=True
            host['day']=day
            done=sum(str(t['flow_status'] or '')=='已完成' or bool(t.get('_output_exists')) for t in rows)
            total=len(rows);complete=done==total
            text(host['title'],first['host_name']);text(host['count'],f'{done} / {total}')
            text(host['button'],'取消优先' if hid in priority_hosts and not complete else '优先生成')
            if host['button'].isEnabled()==complete:host['button'].setEnabled(not complete)
            image_key,image=page._view_cache['images'].get(hid,(None,None))
            if image_key!=host['image_key']:
                if image is not None:host['thumb'].setPixmap(QPixmap.fromImage(image))
                else:host['thumb'].setText('无参考图')
                host['image_key']=image_key
            ids={int(t['segment_id']) for t in rows}
            state='✓ 已提交视频质检' if complete else '下载中' if ids & downloading else '生成中' if ids & generating else '处理中' if ids & processing else '⚠ 异常' if any(str(t['flow_status'] or '') in ('失败','下载失败') for t in rows) else '等待任务'
            h_paused=hid in paused_hosts;_sync_pause(host['pause'],h_paused)
            if h_paused and not complete:state='⏸ 已暂停 · '+state
            text(host['state'],state)
            completion=max(str(t['flow_completed_at'] or '') for t in rows)
            host_order.append(((0 if complete else 1,completion if complete else '',hid),host['card']))
        changed=reorder(entry['grid'],[w for _,w in sorted(host_order,key=lambda pair:pair[0])]) or changed
        ordered.append(entry['card'])
    empty=getattr(page,'_monitor_empty',None)
    if not ordered:
        if empty is None:empty=QLabel('暂无生产任务',objectName='muted');page._monitor_empty=empty
        empty.show();ordered=[empty]
    elif empty is not None:empty.hide()
    changed=reorder(page.visual_progress_layout,ordered) or changed
    if changed:page.visual_progress_scroll.schedule()
