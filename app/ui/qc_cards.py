"""Keyed QC display widgets; all workflow actions remain in VideoQCPage."""
from PySide6.QtCore import Qt,QSize
from PySide6.QtGui import QPixmap,QImageReader
from functools import lru_cache
from pathlib import Path
from PySide6.QtWidgets import QFrame,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,QPushButton


@lru_cache(maxsize=96)
def _decode(path,stamp):
    reader=QImageReader(path);reader.setAutoTransform(True)
    size=reader.size()
    if size.isValid():reader.setScaledSize(size.scaled(QSize(44,44),Qt.KeepAspectRatio))
    return reader.read().scaled(QSize(44,44),Qt.KeepAspectRatio,Qt.SmoothTransformation)

def thumbnails(rows):
    result={}
    for row in rows:
        hid=int(row['host_id']);path=str(row.get('image_path') or '')
        if hid in result or not path:continue
        try:
            revision=(path,Path(path).stat().st_mtime_ns)
            result[hid]=(revision,_decode(*revision))
        except (OSError,ValueError):pass
    return result


def reorder(layout, widgets):
    if [layout.itemAt(i).widget() for i in range(layout.count())]==widgets:return
    while layout.count():layout.takeAt(0)
    for widget in widgets:layout.addWidget(widget)


def render(page):
    page._recalculate_qc_left_state()
    query=page.qc_search.text().strip().lower()
    active={int(r['host_id']) for r in page._qc_queue_rows if int(r.get('completed_segments') or 0)>0 or r.get('materials_ready') or int((r.get('waiting_reasons') or {}).get('返工中',0) or 0)>0}
    hosts={};passed=0
    for r in page._qc_queue_rows:
        state=page._qc_video_state.get(int(r['video_id']),'pending');passed+=state=='passed'
        if int(r['host_id']) not in active:continue
        if (page._qc_view_mode=='history')!=(state=='passed'):continue
        if query and query not in f"{r.get('recipient_name','')} {r.get('host_name','')}".lower():continue
        hosts.setdefault(int(r['host_id']),[]).append(r)
    page.history_view_btn.setText(f'历史记录 {passed}');page._sync_qc_view_buttons()
    if not hasattr(page,'_qc_host_cards'):
        page._qc_host_cards={};page._qc_recipient_cards={}
        page._qc_panel=QFrame(objectName='taskGroup');box=QVBoxLayout(page._qc_panel)
        page._qc_panel_title=QLabel(objectName='cardTitle');header=QHBoxLayout();header.addWidget(page._qc_panel_title);header.addStretch(1);page._qc_legend=QLabel(objectName='muted');header.addWidget(page._qc_legend);box.addLayout(header)
        page._qc_grid=QGridLayout();page._qc_grid.setAlignment(Qt.AlignLeft|Qt.AlignTop);page._qc_grid.setHorizontalSpacing(6);page._qc_grid.setVerticalSpacing(6);box.addLayout(page._qc_grid)
        page._qc_empty=QLabel('当前没有可显示的质检视频');page._qc_empty.setAlignment(Qt.AlignCenter)
    for hid in list(page._qc_host_cards):
        if hid not in hosts:
            frame=page._qc_host_cards.pop(hid)[0];page.task_cards.removeWidget(frame);frame.deleteLater();page._qc_host_count_labels.pop(hid,None)
    if page._selected_qc_host_id not in hosts:
        pending=[hid for hid in hosts if page._first_pending_output_for_host(hid) is not None]
        page._selected_qc_host_id=(pending or list(hosts) or [None])[0]
    frames=[]
    for hid,rows in hosts.items():
        row=rows[0]
        if hid not in page._qc_host_cards:
            frame=QFrame(objectName='taskRow');layout=QHBoxLayout(frame)
            thumb=QLabel(objectName='thumb');thumb.setFixedSize(44,44);thumb.mousePressEvent=lambda e,h=hid:page._select_qc_host(h,True);layout.addWidget(thumb)
            name=QPushButton();name.clicked.connect(lambda _,h=hid:page._select_qc_host(h,True));layout.addWidget(name,1)
            count=QLabel();layout.addWidget(count);page._qc_host_cards[hid]=(frame,name,count,thumb)
        frame,name,count,thumb=page._qc_host_cards[hid]
        image=getattr(page,'_qc_host_images',{}).get(hid)
        if image and getattr(thumb,'_revision',None)!=image[0]:thumb.setPixmap(QPixmap.fromImage(image[1]));thumb._revision=image[0]
        elif not image and getattr(thumb,'_revision',None) is not None:thumb.clear();thumb._revision=None
        label=str(row.get('host_name') or '未命名主播')
        if name.text()!=label:name.setText(label)
        object_name='hostSelectActive' if hid==page._selected_qc_host_id else 'hostSelect'
        if name.objectName()!=object_name:name.setObjectName(object_name);name.style().unpolish(name);name.style().polish(name)
        style='QFrame#taskRow{border:2px solid #2F6FED;}' if hid==page._selected_qc_host_id else ''
        if frame.styleSheet()!=style:frame.setStyleSheet(style)
        counts=page._qc_host_pass_counts.get(hid,{'passed':0,'total':len(rows)})
        count.setText(f"{counts['passed']}/{counts['total']}");page._qc_host_count_labels[hid]=count;frames.append(frame)
    selected=sorted(hosts.get(page._selected_qc_host_id,[]),key=lambda r:int(r.get('video_seq') or 0))
    wanted={int(r['video_id']) for r in selected}
    for vid in list(page._qc_video_buttons):
        if vid not in wanted:
            b=page._qc_video_buttons.pop(vid);page._qc_grid.removeWidget(b);b.deleteLater()
    order=[]
    for r in selected:
        vid=int(r['video_id']);b=page._qc_video_buttons.get(vid)
        if b is None:
            b=QPushButton();b.setFixedSize(42,38);b.clicked.connect(lambda _,v=vid:page._select_output_id(page._qc_video_target[v]) if page._qc_video_target.get(v) else None)
            marker=QLabel('●',b);marker.setGeometry(29,0,12,12);marker.setStyleSheet('color:#F59E0B;background:transparent;border:none;');marker.setAttribute(Qt.WA_TransparentForMouseEvents,True);b._rework_marker=marker
            page._qc_video_buttons[vid]=b
        b.setText(f"{int(r.get('video_seq') or 0):02d}");b.setEnabled(bool(page._qc_video_target.get(vid)))
        page._apply_video_button_style(b,page._qc_video_state.get(vid,'pending'),vid==page._current_qc_video_id);order.append(b)
    if getattr(page,'_qc_grid_order',None)!=order:
        while page._qc_grid.count():page._qc_grid.takeAt(0)
        for i,b in enumerate(order):page._qc_grid.addWidget(b,i//8,i%8)
        page._qc_grid_order=order
    title=(str(selected[0].get('host_name') or '') if selected else '')+(' · 历史记录' if page._qc_view_mode=='history' else ' · 待质检完整视频')
    page._qc_panel_title.setText(title)
    page._qc_legend.setText('绿色=通过' if page._qc_view_mode=='history' else '灰色=待审  ●=返工')
    page._qc_panel.setVisible(bool(hosts));page._qc_empty.setVisible(not hosts)
    recipients={}
    for hid,rows in hosts.items():recipients.setdefault(int(rows[0]['recipient_id']),[]).append(hid)
    for rid in list(page._qc_recipient_cards):
        if rid not in recipients:
            group,_,_=page._qc_recipient_cards.pop(rid);page.task_cards.removeWidget(group);group.deleteLater()
    groups=[]
    for rid,hids in recipients.items():
        if rid not in page._qc_recipient_cards:
            group=QFrame(objectName='taskGroup');box=QVBoxLayout(group);title=QLabel(objectName='cardTitle');box.addWidget(title);body=QVBoxLayout();box.addLayout(body);page._qc_recipient_cards[rid]=(group,title,body)
        group,title,body=page._qc_recipient_cards[rid];title.setText(str(hosts[hids[0]][0].get('recipient_name') or '未命名接收人'))
        reorder(body,[page._qc_host_cards[hid][0] for hid in hids]);groups.append(group)
    reorder(page.task_cards,groups+[page._qc_panel,page._qc_empty])
    page.summary.setText(f'{len(hosts)} 主播 · {sum(map(len,hosts.values()))} 视频')
