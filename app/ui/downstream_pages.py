from __future__ import annotations

from app.services.perf_diagnostics import measured

from pathlib import Path
import json
import os
from app.services import quiet_process as subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import Qt, QUrl, QTimer, QProcess, QDate, QDateTime, QRect, Signal, QEvent
from PySide6.QtGui import QDesktopServices, QPixmap, QShortcut, QKeySequence, QPainter, QPen, QColor, QBrush, QPalette
from PySide6.QtWidgets import (
    QLineEdit, QSlider, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QAbstractItemView, QMessageBox, QProgressBar, QSplitter, QDialog,
    QPlainTextEdit, QFileDialog, QLineEdit, QGridLayout, QScrollArea, QSizePolicy, QStackedWidget, QToolTip, QCheckBox
)

try:
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
    from PySide6.QtMultimediaWidgets import QVideoWidget
    MULTIMEDIA_OK = True
except Exception:
    QMediaPlayer = QAudioOutput = QVideoWidget = None
    MULTIMEDIA_OK = False

try:
    from app.ui.mac_avplayer import MacAVPlayerWidget, MAC_AVPLAYER_AVAILABLE
except Exception:
    MacAVPlayerWidget = None
    MAC_AVPLAYER_AVAILABLE = False

from app.ui.video_thumbnail import VideoThumbnailButton
from app.ui.image_preview import set_image
from app.ui.task_controls import GenerationModeToggle
from app.services.image_assets import image_cache_key
from app.core import repository as repo
from app.core import work_dates
from app.services import workflow
from app.services import davinci_workflow
from app.services import media_qc, drive_delivery, pipeline_orchestrator, resolve_finish, qc_image_replace
from app.services.local_bridge import get_bridge


def _make_table(headers):
    table = QTableWidget()
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.ExtendedSelection)
    table.setWordWrap(False)
    table.verticalHeader().setDefaultSectionSize(42)
    return table


def _open_path_or_url(value):
    value = str(value or "").strip()
    if not value:
        return False
    p = Path(value).expanduser()
    url = QUrl.fromLocalFile(str(p)) if p.exists() else QUrl(value)
    return QDesktopServices.openUrl(url)




class AspectVideoHost(QWidget):
    """Keeps the actual video surface at 9:16 while the surrounding area stays transparent."""
    def __init__(self, child, parent=None):
        super().__init__(parent)
        self.child = child
        self.setObjectName('videoHost')
        self.setMinimumSize(150, 270)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        if child is not None:
            child.setParent(self)
            child.show()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.child is None:
            return
        w=max(1,self.width()); h=max(1,self.height())
        target_w=min(w, int(h*9/16))
        target_h=int(target_w*16/9)
        if target_h>h:
            target_h=h; target_w=int(target_h*9/16)
        x=(w-target_w)//2; y=(h-target_h)//2
        self.child.setGeometry(x,y,max(1,target_w),max(1,target_h))




class HorizontalDragScrollArea(QScrollArea):
    """Compact one-row scroller used by the QC segment strip.

    Scroll bars stay hidden, but trackpad/wheel movement and click-drag panning remain
    available.  Registering the segment buttons lets a horizontal drag start on a
    button without accidentally activating that button when the drag ends.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(48)
        self._drag_origin_x=None
        self._drag_scroll_start=0
        self._dragging=False
        self.viewport().installEventFilter(self)
        self.viewport().setCursor(Qt.OpenHandCursor)

    def register_drag_widget(self, widget):
        if widget is not None:
            widget.installEventFilter(self)

    @staticmethod
    def _global_x(event):
        try:
            return float(event.globalPosition().x())
        except Exception:
            try:
                return float(event.globalPos().x())
            except Exception:
                return 0.0

    def eventFilter(self, obj, event):
        et=event.type()
        if et==QEvent.Type.Wheel:
            bar=self.horizontalScrollBar()
            if bar.maximum()>0:
                try:
                    pixel=event.pixelDelta(); angle=event.angleDelta()
                    delta=(pixel.x() or pixel.y() or angle.x() or angle.y())
                except Exception:
                    delta=0
                if delta:
                    bar.setValue(bar.value()-int(delta))
                    event.accept()
                    return True
        elif et==QEvent.Type.MouseButtonPress and event.button()==Qt.LeftButton:
            self._drag_origin_x=self._global_x(event)
            self._drag_scroll_start=self.horizontalScrollBar().value()
            self._dragging=False
        elif et==QEvent.Type.MouseMove and self._drag_origin_x is not None and bool(event.buttons() & Qt.LeftButton):
            dx=self._global_x(event)-self._drag_origin_x
            if abs(dx)>=4:
                self._dragging=True
                try:
                    if isinstance(obj,QPushButton): obj.setDown(False)
                except Exception:
                    pass
                self.horizontalScrollBar().setValue(self._drag_scroll_start-int(dx))
                event.accept()
                return True
        elif et==QEvent.Type.MouseButtonRelease and event.button()==Qt.LeftButton and self._drag_origin_x is not None:
            dragged=self._dragging
            self._drag_origin_x=None
            self._dragging=False
            if dragged:
                try:
                    if isinstance(obj,QPushButton): obj.setDown(False)
                except Exception:
                    pass
                event.accept()
                return True
        return super().eventFilter(obj,event)


class BaseWorkflowPage(QWidget):
    """Responsive shell shared by QC / DaVinci / delivery / statistics pages.

    The business widgets still use the same repository/service APIs; only the viewport
    is changed so a small window scrolls instead of compressing/overlapping controls.
    """
    def __init__(self, title, subtitle, parent=None):
        super().__init__(parent)
        self._workflow_owner=parent
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.page_scroll = QScrollArea(objectName="workflowPageScroll")
        self.page_scroll.setWidgetResizable(True)
        self.page_scroll.setFrameShape(QFrame.NoFrame)
        self.page_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.page_content = QWidget(objectName="workflowPageContent")
        self.page_content.setMinimumWidth(760)
        self.root = QVBoxLayout(self.page_content)
        self.root.setContentsMargins(24, 20, 24, 22)
        self.root.setSpacing(12)
        self.root.setAlignment(Qt.AlignTop)
        self.page_scroll.setWidget(self.page_content)
        outer.addWidget(self.page_scroll)

        h = QLabel(title)
        h.setStyleSheet("font-size:28px;font-weight:800;")
        self.root.addWidget(h)

        s = QLabel(subtitle, objectName="muted")
        s.setWordWrap(True)
        self.root.addWidget(s)

    def card(self):
        return QFrame(objectName="card")


class VideoQCPage(BaseWorkflowPage):
    """Batch visual QC workspace. Core QC data and workflow APIs are unchanged."""
    def __init__(self, parent=None):
        super().__init__(
            "视频质检中心",
            "只负责审核视频片段：任务信息全部只读；点击任务自动播放，A 通过，D 退回重做。",
            parent
        )
        self.qc_page_index=0
        self.current_output=''
        self._qc_row_cache={}
        self._visible_qc_rows=[]
        self._pending_video_source=None
        self._row_index_by_output={}
        # V0.13.5.62: QC-left-only state. The player surface and media path logic stay untouched.
        self._selected_qc_host_id=None
        self._current_qc_video_id=None
        self._qc_current_rows=[]
        self._qc_queue_rows=[]
        self._qc_video_state={}
        self._qc_video_target={}
        self._qc_video_buttons={}
        self._qc_host_count_labels={}
        self._qc_optimistic={}
        self._qc_inflight=set()
        self._qc_jobs=[]
        self._qc_current_signature=None
        # V0.13.5.65: QC-only history/undo/prompt-edit state.
        self._qc_view_mode='pending'
        self._qc_undo_stack=[]

        # Top dashboard metrics, matching the batch-QC cockpit discussed with the user.
        metric_row=QHBoxLayout(); metric_row.setSpacing(10)
        def metric(title, value='0', tone='info'):
            card=QFrame(objectName='dashboardMetric'); card.setMaximumHeight(70); box=QVBoxLayout(card); box.setContentsMargins(14,10,14,10); box.setSpacing(2)
            v=QLabel(value, objectName='metricValue'); v.setProperty('tone',tone); v.setAlignment(Qt.AlignCenter)
            t=QLabel(title, objectName='metricLabel'); t.setAlignment(Qt.AlignCenter)
            box.addWidget(v); box.addWidget(t); metric_row.addWidget(card,1); return v
        self.metric_pending=metric('待质检','0','info')
        self.metric_passed=metric('今日通过','0','good')
        self.metric_redo=metric('累计退回重做','0','bad')
        self.metric_total=metric('累计质检','0','neutral')
        metric_row.addStretch(1)
        self.root.addLayout(metric_row)

        # Main workspace: left task pool / center player / right read-only task details.
        body=QSplitter(Qt.Horizontal); body.setChildrenCollapsible(False); body.setHandleWidth(7)

        left=QFrame(objectName='pageCard'); lv=QVBoxLayout(left); lv.setContentsMargins(12,12,12,12); lv.setSpacing(9)
        lh=QHBoxLayout(); lh.addWidget(QLabel('质检任务',objectName='sectionTitle')); self.summary=QLabel('',objectName='muted'); lh.addWidget(self.summary); lh.addStretch(1)
        self.pending_view_btn=QPushButton('待质检'); self.pending_view_btn.setCheckable(True); self.pending_view_btn.clicked.connect(lambda:self._set_qc_view_mode('pending')); lh.addWidget(self.pending_view_btn)
        self.history_view_btn=QPushButton('历史记录'); self.history_view_btn.setCheckable(True); self.history_view_btn.clicked.connect(lambda:self._set_qc_view_mode('history')); lh.addWidget(self.history_view_btn); lv.addLayout(lh)
        tools=QHBoxLayout()
        self.qc_search=QLineEdit(); self.qc_search.setPlaceholderText('搜索接收人 / 主播名称…'); self.qc_search.textChanged.connect(lambda:self.qc_change_page(0,True)); tools.addWidget(self.qc_search,1)
        refresh=QPushButton('刷新'); refresh.clicked.connect(self.reload); tools.addWidget(refresh); lv.addLayout(tools)
        # Keep the legacy status object for stable business-method contracts, but the new
        # navigation always shows the real complete-video state in one unified view.
        self.status=QComboBox(); self.status.addItem('全部'); self.status.hide()
        self.task_scroll=QScrollArea(objectName='cardScroll'); self.task_scroll.setWidgetResizable(True); self.task_scroll.setFrameShape(QFrame.NoFrame); self.task_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn); self.task_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); self.task_scroll.setMinimumHeight(180)
        self.task_content=QWidget(objectName='scrollContent'); self.task_cards=QVBoxLayout(self.task_content); self.task_cards.setContentsMargins(0,0,0,0); self.task_cards.setSpacing(8); self.task_cards.setAlignment(Qt.AlignTop); self.task_scroll.setWidget(self.task_content); lv.addWidget(self.task_scroll,1)
        left.setMinimumWidth(340)

        center=QFrame(objectName='pageCard'); cv=QVBoxLayout(center); cv.setContentsMargins(12,12,12,12); cv.setSpacing(8)
        self.preview_title=QLabel('选择一个待质检视频',objectName='sectionTitle'); self.preview_title.setAlignment(Qt.AlignCenter); cv.addWidget(self.preview_title)
        self.native_player_widget=None
        self.player_stack=QStackedWidget()
        self.player_stack.setStyleSheet('background:transparent;border:none;')
        if MULTIMEDIA_OK:
            from app.ui.clip_transform import TransformVideoWidget
            self.video_widget=TransformVideoWidget(); self.video_widget.setStyleSheet('background:transparent;border:none;')
            try: self.video_widget.setAspectRatioMode(Qt.KeepAspectRatio)
            except Exception: pass
            self.audio=QAudioOutput(self); self.player=QMediaPlayer(self); self.player.setAudioOutput(self.audio); self.player.setVideoSink(self.video_widget.videoSink()); self.player.mediaStatusChanged.connect(self._autoplay_loaded)
            self.player_stack.addWidget(self.video_widget)
        else:
            self.video_widget=QLabel('当前 PySide6 多媒体组件不可用'); self.video_widget.setAlignment(Qt.AlignCenter); self.player=None; self.player_stack.addWidget(self.video_widget)
        if MacAVPlayerWidget is not None and MAC_AVPLAYER_AVAILABLE:
            try:
                self.native_player_widget=MacAVPlayerWidget(); self.native_player_widget.backendError.connect(self._native_player_error); self.player_stack.addWidget(self.native_player_widget)
            except Exception:
                self.native_player_widget=None
        self.video_host=AspectVideoHost(self.player_stack); cv.addWidget(self.video_host,1)
        self.transform_btn=QPushButton('画面调整');self.transform_btn.clicked.connect(self.adjust_clip_frame);cv.addWidget(self.transform_btn,0,Qt.AlignRight)
        seek_layout = QHBoxLayout()
        self.time_current = QLabel("00:00")
        self.time_total = QLabel("00:00")
        self.time_current.setStyleSheet("color: #666; font-size: 13px; font-variant-numeric: tabular-nums;")
        self.time_total.setStyleSheet("color: #666; font-size: 13px; font-variant-numeric: tabular-nums;")
        self.seek=QSlider(Qt.Horizontal)
        
        def format_time(ms):
            s = max(0, ms // 1000)
            return f"{s//60:02d}:{s%60:02d}"
            
        def update_time_labels(pos=None, dur=None):
            if pos is not None: self.time_current.setText(format_time(pos))
            if dur is not None: self.time_total.setText(format_time(dur))
            
        if self.player:
            self.player.durationChanged.connect(lambda value:(self.seek.setRange(0,value), update_time_labels(dur=value)))
            self.player.positionChanged.connect(lambda value:(self.seek.setValue(value) if not self.seek.isSliderDown() else None, update_time_labels(pos=value)))
        if self.native_player_widget:
            self.native_player_widget.durationChanged.connect(lambda value:(self.seek.setRange(0,value), update_time_labels(dur=value)) if self._native_player_enabled() else None)
            self.native_player_widget.positionChanged.connect(lambda value:(self.seek.setValue(value) if not self.seek.isSliderDown() else None, update_time_labels(pos=value)) if self._native_player_enabled() else None)
        self.seek.sliderMoved.connect(self._set_active_player_position)
        
        seek_layout.addWidget(self.time_current)
        seek_layout.addWidget(self.seek)
        seek_layout.addWidget(self.time_total)
        cv.addLayout(seek_layout)
        
        playrow = QHBoxLayout()
        playrow.addStretch(1)
        
        self.play_btn = QPushButton('⏸')
        self.replay_btn = QPushButton('↻')
        
        for btn in (self.play_btn, self.replay_btn):
            btn.setFixedSize(50, 50)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet("QPushButton { border: none; background: transparent; font-size: 28px; color: #444; font-weight: bold; } QPushButton:hover { color: #111; }")
            
        # Monkey patch toggle_play to update button text
        original_toggle = self.toggle_play
        def new_toggle():
            original_toggle()
            self.play_btn.setText('▶' if getattr(self, '_qc_paused', False) else '⏸')
        self.toggle_play = new_toggle
            
        self.play_btn.clicked.connect(self.toggle_play)
        self.replay_btn.clicked.connect(lambda: (self._set_active_player_position(0), self.play_btn.setText('⏸')))
        
        playrow.addWidget(self.play_btn)
        playrow.addWidget(self.replay_btn)
        playrow.addStretch(1)
        
        self.mac_player_switch=QCheckBox('Mac 原生播放器'); self.mac_player_switch.setChecked(bool(self.native_player_widget)); self.mac_player_switch.setEnabled(bool(self.native_player_widget))
        self.mac_player_switch.setStyleSheet("color: #999;")
        self.mac_player_switch.toggled.connect(self._switch_qc_player_backend)
        playrow.addWidget(self.mac_player_switch)
        
        cv.addLayout(playrow)
        QTimer.singleShot(0, lambda:self._switch_qc_player_backend(self.mac_player_switch.isChecked()))
        center.setMinimumWidth(300)

        side=QFrame(objectName='detailPanel'); sv=QVBoxLayout(side); sv.setContentsMargins(14,12,14,12); sv.setSpacing(7)
        sh=QHBoxLayout(); badge=QLabel('当前质检',objectName='statusInfo'); sh.addWidget(badge); sh.addStretch(1)
        self.undo_qc_btn=QPushButton('↶ 撤销'); self.undo_qc_btn.setToolTip('撤销最近一次已保存的质检决定；若下游已开始执行则不会强制回滚'); self.undo_qc_btn.clicked.connect(self.undo_last_qc_action); sh.addWidget(self.undo_qc_btn)
        self.edit_prompt_btn=QPushButton('修改提示词'); self.edit_prompt_btn.setToolTip('修改当前片段提示词并通过现有 REWORK 返工链路重新生成'); self.edit_prompt_btn.clicked.connect(self.edit_current_qc_prompt); sh.addWidget(self.edit_prompt_btn)
        self.replace_image_btn=QPushButton('🖼️ 替换图片'); self.replace_image_btn.setToolTip('保持当前任务编号、文案和归属不变；可只换图、切换模式、编辑 Prompt，只有主动要求才重新调用 GPT'); self.replace_image_btn.clicked.connect(self.replace_current_qc_image); sh.addWidget(self.replace_image_btn)
        self.position_label=QLabel('0 / 0',objectName='muted'); sh.addWidget(self.position_label); sv.addLayout(sh)
        info_grid=QGridLayout(); info_grid.setHorizontalSpacing(10); info_grid.setVerticalSpacing(6)
        def info_line(row_no, title):
            label=QLabel(title,objectName='muted'); label.setFixedWidth(66); value=QLabel('—',objectName='cardTitle'); value.setTextInteractionFlags(Qt.TextSelectableByMouse); info_grid.addWidget(label,row_no,0); info_grid.addWidget(value,row_no,1); return value
        self.info_recipient=info_line(0,'接收人')
        self.info_host=info_line(1,'AI主播')
        self.info_video=info_line(2,'完整视频')
        self.info_status=info_line(3,'当前状态')
        sv.addLayout(info_grid)
        mode_row=QHBoxLayout(); mode_row.addWidget(QLabel('当前模式',objectName='muted'))
        self.qc_generation_mode=GenerationModeToggle('FRAME',self)
        self.qc_generation_mode.modeChanged.connect(self._qc_generation_mode_changed)
        mode_row.addWidget(self.qc_generation_mode); mode_row.addStretch(1); sv.addLayout(mode_row)

        # Show only the foreign-language text owned by the selected segment.
        copy_grid=QGridLayout(); copy_grid.setHorizontalSpacing(8); copy_grid.setVerticalSpacing(2)
        foreign_tag=QLabel('外文',objectName='muted'); foreign_tag.setFixedWidth(38)
        self.info_foreign_copy=QLineEdit(); self.info_foreign_copy.setReadOnly(True); self.info_foreign_copy.setFrame(False)
        self.info_foreign_copy.setStyleSheet('background:transparent;border:none;padding:0px;font-size:11px;')
        self.info_foreign_copy.setToolTip('当前片段外文口播文案')
        copy_grid.addWidget(foreign_tag,0,0); copy_grid.addWidget(self.info_foreign_copy,0,1)
        sv.addLayout(copy_grid)

        # Retain these hidden widgets so existing preview/business contracts remain stable.
        self.info_script=QLabel('',objectName='muted'); self.info_script.hide()
        self.dialogue=QPlainTextEdit(); self.dialogue.hide(); self.prompt=QPlainTextEdit(); self.prompt.hide()
        self.segment_title=QLabel('当前完整视频片段',objectName='cardTitle'); sv.addWidget(self.segment_title)
        # Keep the segment numbers on one compact horizontal rail.  A long video must
        # never widen the whole left QC column and squeeze the player out of view.
        self.segment_scroll=HorizontalDragScrollArea(self)
        self.segment_content=QWidget(objectName='segmentScrollContent')
        self.segment_content.setSizePolicy(QSizePolicy.MinimumExpanding,QSizePolicy.Fixed)
        self.segment_strip=QHBoxLayout(self.segment_content); self.segment_strip.setContentsMargins(0,0,0,0); self.segment_strip.setSpacing(6); self.segment_strip.setAlignment(Qt.AlignLeft|Qt.AlignVCenter)
        self.segment_scroll.setWidget(self.segment_content); self.segment_scroll.register_drag_widget(self.segment_content)
        self.segment_scroll.setToolTip('横向滚动或按住拖动查看更多片段；切换片段时会自动跟随当前编号')
        sv.addWidget(self.segment_scroll)
        actions=QHBoxLayout(); self.approve_btn=QPushButton('✓ 通过 (A)',objectName='successAction'); self.approve_btn.clicked.connect(lambda:self.set_selected('通过')); actions.addWidget(self.approve_btn); sv.addLayout(actions)
        self.qc_report=QLabel('Space 播放/暂停 · ←/→ 前后 3 秒 · ↑/↓ 上一条/下一条 · F 全屏',objectName='muted'); self.qc_report.setWordWrap(True); sv.addWidget(self.qc_report)
        left_column=QWidget(); column=QVBoxLayout(left_column);column.setContentsMargins(0,0,0,0);column.setSpacing(8)
        column.addWidget(side);column.addWidget(left,1)
        body.addWidget(left_column);body.addWidget(center)
        body.setSizes([490,650]);body.setStretchFactor(0,4);body.setStretchFactor(1,6); body.setOpaqueResize(True)
        # Make the existing left/player splitter deliberately visible and draggable.
        # The user's chosen width remains untouched by refreshes because the splitter is
        # created once with the page rather than rebuilt with task data.
        body.setHandleWidth(10)
        body.setStyleSheet('QSplitter::handle{background:#DCE6F2;border-radius:4px;margin:2px;} QSplitter::handle:hover{background:#AFC3DF;}')
        self.qc_main_splitter=body
        try: body.handle(1).setToolTip('拖动这里调整左侧质检区与视频播放器宽度')
        except Exception: pass
        body.setMinimumHeight(600);self.root.setAlignment(Qt.AlignmentFlag(0));self.root.addWidget(body,1)

        reason_card=QFrame(objectName='pageCard'); rg=QGridLayout(reason_card); rg.setContentsMargins(12,9,12,9); rg.setHorizontalSpacing(8); rg.setVerticalSpacing(7)
        rg.addWidget(QLabel('退回原因 · 点击即退回',objectName='cardTitle'),0,0,1,4)
        reasons=['人物/面部异常','口型/台词问题','动作问题','镜头问题','声音问题','画面穿帮','人物一致性','其他']
        for i,reason in enumerate(reasons):
            b=QPushButton(f'{i+1}  {reason}',objectName='reasonBtn'); b.clicked.connect(lambda _=False,r=reason:self.set_selected('退回',r)); b.setStyleSheet('min-height:0px;max-height:28px;padding:4px 5px;font-size:12px;');b.setFixedHeight(30); rg.addWidget(b,1+i//4,i%4)
        sv.addWidget(reason_card)
        self.approve_btn.setStyleSheet('min-height:0px;max-height:42px;padding:6px;font-size:15px;');self.approve_btn.setFixedHeight(42)
        for button in (self.undo_qc_btn,self.edit_prompt_btn,self.replace_image_btn,self.pending_view_btn,self.history_view_btn):
            button.setStyleSheet('min-height:0px;max-height:30px;padding:4px 9px;font-size:12px;'); button.setFixedHeight(30)
        self.qc_report.setStyleSheet('font-size:11px;');self.info_host.setStyleSheet('font-size:14px;font-weight:750;')
        side.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Maximum)

        # Hidden table keeps the already-stable selection/business methods intact.
        self.table=_make_table(['接收人','AI主播','完整视频','片段','状态']); self.table.hide(); self.table.itemSelectionChanged.connect(self.load_selected_preview); self.root.addWidget(self.table)
        self.reference=QLabel(); self.reference.hide(); self.open_btn=QPushButton(); self.play_btn=QPushButton(); self.meta=QLabel(); self.meta.hide()
        # V0.13.5.17: no automatic local/ffprobe pre-QC after download.
        # Download completion only binds the file and queues it for human QC.
        self.qc_future=None; self.qc_future_segment=None; self._ai_failed_once=set()
        self._qc_executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='qc-review')
        self._qc_replace_executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='qc-image-replace')
        self._qc_replace_future=None
        self._qc_async_timer=QTimer(self); self._qc_async_timer.setInterval(70); self._qc_async_timer.timeout.connect(self._poll_qc_jobs)
        self._qc_pool_timer=QTimer(self); self._qc_pool_timer.setInterval(1800); self._qc_pool_timer.timeout.connect(self._light_refresh_qc_pool)
        self._qc_downstream_timer=QTimer(self); self._qc_downstream_timer.setSingleShot(True); self._qc_downstream_timer.setInterval(300); self._qc_downstream_timer.timeout.connect(self._sync_qc_downstream)
        from app.ui.read_snapshot import SnapshotReader
        self._qc_reader=SnapshotReader(self,self._read_qc_snapshot);self._qc_reader.ready.connect(self._qc_snapshot_ready)
        self._qc_epoch=0;self._qc_dirty=True;self._qc_loaded_day=None
        self._qc_preload_reader=SnapshotReader(self,self._warm_next_file)
        self._install_shortcuts(); self.reload()

    def _clear_layout_widgets(self, layout):
        while layout.count():
            item=layout.takeAt(0); w=item.widget()
            if w: w.hide(); w.deleteLater()

    def _select_output_id(self, output_id):
        row=self._row_index_by_output.get(int(output_id))
        if row is None: return
        self.table.selectRow(row)
        self.load_selected_preview()

    def _effective_qc_status(self, output_id, fallback='待质检'):
        return str(self._qc_optimistic.get(int(output_id), fallback or '待质检'))

    def _set_qc_view_mode(self, mode):
        mode='history' if str(mode)=='history' else 'pending'
        if mode==self._qc_view_mode:
            self._sync_qc_view_buttons()
            return
        self._qc_view_mode=mode
        self._sync_qc_view_buttons()
        self._render_task_workspace(self._qc_current_rows)

    def _sync_qc_view_buttons(self):
        pending=self._qc_view_mode=='pending'
        self.pending_view_btn.setChecked(pending); self.history_view_btn.setChecked(not pending)
        active='background:#2F6FED;color:white;border:1px solid #2F6FED;border-radius:7px;font-weight:750;'
        idle='border:1px solid #D8E1EE;border-radius:7px;font-weight:650;'
        self.pending_view_btn.setStyleSheet(('min-height:0px;max-height:30px;padding:4px 9px;font-size:12px;'+active) if pending else ('min-height:0px;max-height:30px;padding:4px 9px;font-size:12px;'+idle))
        self.history_view_btn.setStyleSheet(('min-height:0px;max-height:30px;padding:4px 9px;font-size:12px;'+active) if not pending else ('min-height:0px;max-height:30px;padding:4px 9px;font-size:12px;'+idle))

    def _qc_generation_mode_changed(self, mode):
        ids=self.selected_ids()
        if not ids: return
        oid=int(ids[0]); row=self._qc_row_cache.get(oid) or repo.get_qc_output(oid)
        if not row: return
        old=repo.normalize_generation_mode(row['generation_mode'] if 'generation_mode' in row.keys() else 'FRAME')
        mode=repo.normalize_generation_mode(mode)
        if old==mode: return
        label='素材' if mode=='MATERIAL' else '帧'
        if QMessageBox.question(self,'切换生成模式',f'切换为“{label}”后，当前生成结果会作废并直接进入现有 REWORK 返工链路。\n图片、文案、Prompt、人物设置和片段编号均保持不变。\n\n确认继续吗？')!=QMessageBox.Yes:
            self.qc_generation_mode.setMode(old,emit=False); return
        try:
            repo.set_segment_generation_mode(int(row['segment_id']),mode,allow_active_rework=True,reason='切换生成模式')
        except Exception as exc:
            self.qc_generation_mode.setMode(old,emit=False); QMessageBox.warning(self,'切换生成模式',str(exc)); return
        self._qc_optimistic.clear(); self._qc_inflight.clear(); self._qc_current_signature=None
        self.qc_report.setText(f'已切换为“{label}”并进入 REWORK；旧结果即使稍后下载也会作为过期版本忽略。')
        self._refresh_qc_data(force=True,preserve_player=False)
        if not self._qc_downstream_timer.isActive(): self._qc_downstream_timer.start()

    def edit_current_qc_prompt(self):
        ids=self.selected_ids()
        if not ids:
            QMessageBox.information(self,'修改提示词','请先选择一个质检片段。'); return
        oid=int(ids[0])
        if oid in self._qc_inflight:
            QMessageBox.information(self,'修改提示词','当前质检结果正在保存，请稍后再修改提示词。'); return
        row=self._qc_row_cache.get(oid) or repo.get_qc_output(oid)
        if not row:
            QMessageBox.warning(self,'修改提示词','当前片段信息已经变化，请刷新后重试。'); return
        dlg=QDialog(self); dlg.setWindowTitle('修改当前片段提示词'); dlg.resize(680,420)
        box=QVBoxLayout(dlg)
        hint=QLabel(f"{row['recipient_name']} / {row['host_name']} / 视频 {int(row['video_seq']):02d} / 片段 {int(row['seg_seq']):02d}\n保存后当前结果会作废，并通过现有 REWORK 链路使用新提示词重新生成。",objectName='muted'); hint.setWordWrap(True); box.addWidget(hint)
        editor=QPlainTextEdit(); editor.setPlainText(str(row['prompt'] or '')); box.addWidget(editor,1)
        buttons=QHBoxLayout(); buttons.addStretch(1); cancel=QPushButton('取消'); save=QPushButton('保存并返工'); save.setObjectName('primaryAction'); buttons.addWidget(cancel); buttons.addWidget(save); box.addLayout(buttons)
        cancel.clicked.connect(dlg.reject); save.clicked.connect(dlg.accept)
        if dlg.exec()!=QDialog.Accepted: return
        prompt=editor.toPlainText().strip()
        if not prompt:
            QMessageBox.warning(self,'修改提示词','提示词不能为空。'); return
        if prompt==str(row['prompt'] or '').strip(): return
        try:
            repo.rework_qc_segment_prompt(int(row['segment_id']),prompt)
        except Exception as exc:
            QMessageBox.warning(self,'修改提示词失败',str(exc)); return
        cached=self._qc_row_cache.get(oid)
        if cached is not None:
            try: cached['prompt']=prompt
            except Exception: pass
        self.prompt.setPlainText(prompt)
        self.qc_report.setText('提示词已保存并进入 REWORK；原结果已标记失效，后续下载会回到原片段质检。')
        self._qc_optimistic.clear(); self._qc_current_signature=None; self._refresh_qc_data(force=True,preserve_player=False)

    def replace_current_qc_image(self):
        """Replace the complete video's reference image inside the selected date partition."""
        scope_day=work_dates.active()
        ids=self.selected_ids()
        if not ids:
            QMessageBox.information(self,'替换图片','请先选择一个质检视频片段。')
            return
        oid=int(ids[0])
        if oid in self._qc_inflight:
            QMessageBox.information(self,'替换图片','当前质检结果正在保存，请稍后再替换图片。')
            return
        if self._qc_replace_future is not None and not self._qc_replace_future.done():
            QMessageBox.information(self,'替换图片','上一条替换图片的 GPT 生成仍在运行，请等待完成。')
            return
        row=self._qc_row_cache.get(oid) or repo.get_qc_output(oid)
        if not row:
            QMessageBox.warning(self,'替换图片','当前质检任务已经变化，请刷新后重试。')
            return
        try:
            context=qc_image_replace.get_replacement_context(int(row['video_id']),work_date=scope_day)
        except Exception as exc:
            QMessageBox.warning(self,'替换图片',str(exc)); return
        state={'generated':None,'editors':{},'mode_touched':False,'target_mode':repo.normalize_generation_mode(row['generation_mode'] if 'generation_mode' in row.keys() else 'FRAME')}
        dlg=QDialog(self); dlg.setObjectName('qcReplaceDialog')
        dlg.setWindowTitle(f"替换图片 · 视频 {int(context['video_seq']):02d}")
        dlg.resize(1120,820); dlg.setMinimumSize(920,680); dlg.setModal(True)
        root=QVBoxLayout(dlg); root.setContentsMargins(18,16,18,14); root.setSpacing(12)

        header=QFrame(objectName='qcReplaceHeader'); hv=QVBoxLayout(header); hv.setContentsMargins(16,13,16,13); hv.setSpacing(6)
        head_row=QHBoxLayout();
        title=QLabel('🖼️ 替换图片',objectName='qcReplaceTitle'); head_row.addWidget(title)
        head_meta=QLabel(f"{context['recipient_name']}  /  {context['host_name']}  /  完整视频 {int(context['video_seq']):02d}",objectName='qcReplaceMeta'); head_row.addWidget(head_meta)
        head_row.addStretch(1)
        lock_badge=QLabel('仅替换源图 · 编号与文案不变',objectName='qcReplaceSafeBadge'); head_row.addWidget(lock_badge)
        hv.addLayout(head_row)
        lock=QLabel(
            f"工作日期：{scope_day}　·　共 {len(context['segments'])} 个原片段　·　修改只写回该日期。"
            " 接收人、AI 主播、片段编号、中文/外文文案全部锁定不变；旧图片和旧视频版本保留历史。",
            objectName='qcReplaceHint')
        lock.setWordWrap(True); hv.addWidget(lock); root.addWidget(header)
        settings_row=QHBoxLayout(); settings_row.addWidget(QLabel('当前生成模式',objectName='qcReplaceSectionTitle'))
        replace_mode=GenerationModeToggle(state['target_mode'],dlg)
        def on_replace_mode(mode): state['mode_touched']=True; state['target_mode']=repo.normalize_generation_mode(mode)
        replace_mode.modeChanged.connect(on_replace_mode); settings_row.addWidget(replace_mode)
        settings_row.addSpacing(14)
        persona_btn=QPushButton('人物提示词设置'); persona_btn.setToolTip('直接打开 GPT 提示词中心正在使用的同一套人物设置/预设，不建立第二套数据')
        def open_shared_persona():
            from app.ui.prompt_center import GenerationRulesDialog
            d=GenerationRulesDialog(int(context['host_id']),dlg)
            if d.exec():
                try: gen_status.setText('人物设置已更新；只有点击“重新生成提示词”时才会调用 GPT')
                except Exception: pass
        persona_btn.clicked.connect(open_shared_persona); settings_row.addWidget(persona_btn); settings_row.addStretch(1); root.addLayout(settings_row)

        preview_section=QFrame(objectName='qcReplaceSection'); pv=QVBoxLayout(preview_section); pv.setContentsMargins(14,12,14,12); pv.setSpacing(10)
        preview_head=QHBoxLayout(); preview_head.addWidget(QLabel('图片对比',objectName='qcReplaceSectionTitle')); preview_head.addStretch(1)
        preview_tip=QLabel('左侧原图只读，右侧选择新图片',objectName='qcReplaceMiniHint'); preview_head.addWidget(preview_tip); pv.addLayout(preview_head)
        preview_row=QHBoxLayout(); preview_row.setSpacing(12)
        def image_box(caption, badge_text):
            frame=QFrame(objectName='qcReplacePreviewCard'); box=QVBoxLayout(frame); box.setContentsMargins(11,10,11,10); box.setSpacing(7)
            cap_row=QHBoxLayout(); lab=QLabel(caption,objectName='qcReplaceCardTitle'); cap_row.addWidget(lab); cap_row.addStretch(1)
            badge=QLabel(badge_text,objectName='qcReplaceSmallBadge'); cap_row.addWidget(badge); box.addLayout(cap_row)
            image=QLabel('无图片',objectName='qcReplaceImage'); image.setAlignment(Qt.AlignCenter); image.setMinimumSize(250,215); image.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding)
            box.addWidget(image,1)
            status=QLabel('',objectName='qcReplaceImageStatus'); status.setWordWrap(True); box.addWidget(status)
            return frame,image,status
        old_frame,old_preview,old_status=image_box('当前原图片','历史保留')
        new_frame,new_preview,new_status=image_box('新图片预览','待选择')
        old_source=str(context.get('preview_image_path') or context.get('image_path') or '')
        old_loaded=set_image(old_preview,old_source)
        if old_loaded and context.get('image_recovered'):
            old_status.setText('✓ 原路径已失效，已从该任务绑定素材中安全恢复显示。')
            old_status.setProperty('tone','good')
        elif old_loaded:
            old_status.setText('✓ 原图已加载。替换后仍保留为历史版本。')
            old_status.setProperty('tone','good')
        else:
            old_status.setText('⚠ 原图当前无法读取；已保留原任务身份，可重新选择新图继续。')
            old_status.setProperty('tone','warn')
        new_status.setText('请选择新图片。之后可以直接沿用 Prompt，或主动让 GPT 重新生成。'); new_status.setProperty('tone','muted')
        preview_row.addWidget(old_frame,1); preview_row.addWidget(new_frame,1); pv.addLayout(preview_row)

        choose_row=QHBoxLayout(); choose_label=QLabel('新图片',objectName='qcReplaceFieldLabel'); choose_row.addWidget(choose_label)
        new_path=QLineEdit(); new_path.setObjectName('qcReplacePath'); new_path.setReadOnly(True); new_path.setPlaceholderText('尚未选择新图片'); choose_row.addWidget(new_path,1)
        choose=QPushButton('选择新图片…'); choose.setObjectName('qcReplaceChooseButton'); choose_row.addWidget(choose); pv.addLayout(choose_row)
        root.addWidget(preview_section,3)

        script_section=QFrame(objectName='qcReplaceSection'); sv=QVBoxLayout(script_section); sv.setContentsMargins(14,11,14,11); sv.setSpacing(8)
        script_head=QHBoxLayout(); script_head.addWidget(QLabel('锁定文案（只读）',objectName='qcReplaceSectionTitle')); script_head.addStretch(1)
        script_head.addWidget(QLabel('用于核对，不会因替换图片而改写',objectName='qcReplaceMiniHint')); sv.addLayout(script_head)
        script_row=QHBoxLayout(); script_row.setSpacing(10)
        def readonly_script(title_text, value):
            wrap=QFrame(objectName='qcReplaceTextCard'); lay=QVBoxLayout(wrap); lay.setContentsMargins(10,8,10,8); lay.setSpacing(5)
            lay.addWidget(QLabel(title_text,objectName='qcReplaceFieldLabel'))
            edit=QPlainTextEdit(); edit.setObjectName('qcReplaceReadOnlyText'); edit.setReadOnly(True); edit.setPlainText(' '.join(str(value or '').split()) or '—'); edit.setMaximumHeight(78); edit.setTextInteractionFlags(Qt.TextSelectableByMouse|Qt.TextSelectableByKeyboard); lay.addWidget(edit)
            return wrap
        script_row.addWidget(readonly_script('中文对照',context.get('chinese_script')),1)
        script_row.addWidget(readonly_script('外文文案',context.get('script')),1)
        sv.addLayout(script_row); root.addWidget(script_section,1)

        prompt_section=QFrame(objectName='qcReplaceSection'); gv=QVBoxLayout(prompt_section); gv.setContentsMargins(14,11,14,11); gv.setSpacing(9)
        gen_row=QHBoxLayout(); gen_row.addWidget(QLabel('GPT 新提示词',objectName='qcReplaceSectionTitle'))
        gen_status=QLabel('先选择新图片',objectName='qcReplaceStatus'); gen_status.setProperty('tone','muted'); gen_row.addWidget(gen_status); gen_row.addStretch(1)
        generate=QPushButton('✦ 根据新图片重新生成提示词'); generate.setObjectName('primaryBtn'); generate.setEnabled(False); gen_row.addWidget(generate); gv.addLayout(gen_row)
        prompt_scroll=QScrollArea(); prompt_scroll.setObjectName('qcReplacePromptScroll'); prompt_scroll.setWidgetResizable(True); prompt_scroll.setMinimumHeight(220); prompt_scroll.setFrameShape(QFrame.NoFrame)
        prompt_widget=QWidget(); prompt_widget.setObjectName('qcReplacePromptViewport'); prompt_layout=QVBoxLayout(prompt_widget); prompt_layout.setContentsMargins(0,0,0,0); prompt_layout.setSpacing(8); prompt_layout.setAlignment(Qt.AlignTop); prompt_scroll.setWidget(prompt_widget); gv.addWidget(prompt_scroll,1)
        placeholder=QFrame(objectName='qcReplacePromptPlaceholder'); ph=QVBoxLayout(placeholder); ph.setContentsMargins(14,12,14,12)
        ph_title=QLabel('等待生成',objectName='qcReplaceCardTitle'); ph.addWidget(ph_title)
        ph_text=QLabel('选择新图片后点击“根据新图片重新生成提示词”。GPT 会按原片段编号逐条生成，你仍可以在提交前逐条修改。',objectName='qcReplaceMiniHint'); ph_text.setWordWrap(True); ph.addWidget(ph_text)
        prompt_layout.addWidget(placeholder)
        root.addWidget(prompt_section,3)

        footer=QHBoxLayout(); footer_hint=QLabel('默认只换图片并沿用现有 Prompt；只有主动点击“重新生成提示词”才调用 GPT。模式和人物设置与 GPT 中心共用同一份数据。',objectName='qcReplaceMiniHint'); footer_hint.setWordWrap(True); footer.addWidget(footer_hint,1)
        cancel=QPushButton('取消'); confirm=QPushButton('确认替换并重新提交 Flow'); confirm.setObjectName('qcReplaceConfirm'); confirm.setEnabled(False); footer.addWidget(cancel); footer.addWidget(confirm); root.addLayout(footer)

        def clear_prompt_editors(message):
            while prompt_layout.count():
                item=prompt_layout.takeAt(0); widget=item.widget()
                if widget: widget.deleteLater()
            card=QFrame(objectName='qcReplacePromptPlaceholder'); box=QVBoxLayout(card); box.setContentsMargins(14,12,14,12)
            hint=QLabel(message,objectName='qcReplaceMiniHint'); hint.setWordWrap(True); box.addWidget(hint); prompt_layout.addWidget(card)
            state['generated']=None; state['editors']={}; confirm.setEnabled(False)

        def render_existing_prompts():
            while prompt_layout.count():
                item=prompt_layout.takeAt(0); widget=item.widget()
                if widget: widget.deleteLater()
            state['generated']=None; state['editors']={}
            for seg in context['segments']:
                sid=int(seg['segment_id']); seq=int(seg['seg_seq']); text=' '.join(str(seg.get('foreign_text') or '').split())
                card=QFrame(objectName='qcReplacePromptCard'); box=QVBoxLayout(card); box.setContentsMargins(11,9,11,10); box.setSpacing(6)
                top=QHBoxLayout(); top.addWidget(QLabel(f"片段 {seq:02d}",objectName='qcReplaceSegmentBadge'))
                original=QLabel('原文案：'+text,objectName='qcReplacePromptSource'); original.setWordWrap(True); top.addWidget(original,1); box.addLayout(top)
                editor=QPlainTextEdit(); editor.setObjectName('qcReplacePromptEditor'); editor.setPlainText(str(seg.get('prompt') or '')); editor.setMinimumHeight(92); box.addWidget(editor)
                prompt_layout.addWidget(card); state['editors'][sid]=editor
            confirm.setEnabled(bool(new_path.text().strip()) and bool(state['editors']))
            gen_status.setText('沿用当前 Prompt · 可直接修改；不调用 GPT')
            gen_status.setProperty('tone','info'); gen_status.style().unpolish(gen_status); gen_status.style().polish(gen_status)

        def choose_image():
            path,_=QFileDialog.getOpenFileName(dlg,'选择新的参考图片','', '图片文件 (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff *.heic *.heif);;所有文件 (*)')
            if not path: return
            if not set_image(new_preview,path):
                QMessageBox.warning(dlg,'替换图片','所选图片无法读取，请重新选择。'); return
            new_path.setText(path); new_path.setCursorPosition(0); generate.setEnabled(True)
            new_status.setText('✓ 新图片读取正常，可以重新生成提示词。'); new_status.setProperty('tone','good'); new_status.style().unpolish(new_status); new_status.style().polish(new_status)
            gen_status.setText('已选择新图片 · 尚未生成'); gen_status.setProperty('tone','info'); gen_status.style().unpolish(gen_status); gen_status.style().polish(gen_status)
            render_existing_prompts()

        def render_generated(result):
            while prompt_layout.count():
                item=prompt_layout.takeAt(0); widget=item.widget()
                if widget: widget.deleteLater()
            state['generated']=result; state['editors']={}
            for seg in result['context']['segments']:
                sid=int(seg['segment_id']); seq=int(seg['seg_seq']); text=' '.join(str(seg.get('foreign_text') or '').split())
                card=QFrame(objectName='qcReplacePromptCard'); box=QVBoxLayout(card); box.setContentsMargins(11,9,11,10); box.setSpacing(6)
                top=QHBoxLayout(); seq_label=QLabel(f"片段 {seq:02d}",objectName='qcReplaceSegmentBadge'); top.addWidget(seq_label)
                original=QLabel('原文案：'+text,objectName='qcReplacePromptSource'); original.setWordWrap(True); original.setMaximumHeight(48); top.addWidget(original,1); box.addLayout(top)
                editor=QPlainTextEdit(); editor.setObjectName('qcReplacePromptEditor'); editor.setPlainText(str(result['prompts'].get(sid) or '')); editor.setMinimumHeight(105); editor.setLineWrapMode(QPlainTextEdit.WidgetWidth); box.addWidget(editor)
                prompt_layout.addWidget(card); state['editors'][sid]=editor
            confirm.setEnabled(bool(state['editors']))
            gen_status.setText(f"✓ 已生成 {len(state['editors'])} 条 · 可逐条修改")
            gen_status.setProperty('tone','good'); gen_status.style().unpolish(gen_status); gen_status.style().polish(gen_status)

        poll=QTimer(dlg); poll.setInterval(100)
        def poll_generation():
            future=self._qc_replace_future
            if future is None or not future.done(): return
            poll.stop(); generate.setEnabled(True); cancel.setEnabled(True)
            try: result=future.result()
            except Exception as exc:
                self._qc_replace_future=None; gen_status.setText('生成失败 · 已恢复当前 Prompt'); gen_status.setProperty('tone','bad'); gen_status.style().unpolish(gen_status); gen_status.style().polish(gen_status); render_existing_prompts(); QMessageBox.warning(dlg,'GPT 生成失败',str(exc)); return
            self._qc_replace_future=None; render_generated(result)
        poll.timeout.connect(poll_generation)

        def start_generation():
            path=new_path.text().strip()
            if not path:
                QMessageBox.information(dlg,'替换图片','请先选择新图片。'); return
            generate.setEnabled(False); cancel.setEnabled(False); confirm.setEnabled(False); gen_status.setText('GPT 正在生成…'); gen_status.setProperty('tone','info'); gen_status.style().unpolish(gen_status); gen_status.style().polish(gen_status)
            clear_prompt_editors('正在根据新图片和原文案生成提示词，请不要关闭此窗口。生成完成前不会修改原任务。')
            self._qc_replace_future=self._qc_replace_executor.submit(qc_image_replace.generate_replacement_prompts,int(context['video_id']),path,scope_day)
            poll.start()

        def accept_replace():
            generated=state.get('generated')
            path=new_path.text().strip()
            if not path:
                QMessageBox.information(dlg,'替换图片','请先选择新图片。'); return
            prompts={sid:editor.toPlainText().strip() for sid,editor in state['editors'].items()}
            if any(not value for value in prompts.values()):
                QMessageBox.warning(dlg,'替换图片','所有片段的提示词都不能为空。'); return
            answer=QMessageBox.question(
                dlg,'确认替换图片',
                f"将作废完整视频 {int(context['video_seq']):02d} 当前图片对应的旧生成版本，并使用新图片重新生成 {len(prompts)} 个原片段。\n\n"
                "task_id、编号、原文案、接收人和 AI 主播不会改变；旧图片会保留为历史版本。\n\n确认继续吗？")
            if answer!=QMessageBox.Yes: return
            state['final_prompts']=prompts
            state['commit_payload']=generated or {'context':context,'work_date':scope_day,'selected_image':path}
            dlg.accept()

        choose.clicked.connect(choose_image); generate.clicked.connect(start_generation); cancel.clicked.connect(dlg.reject); confirm.clicked.connect(accept_replace)
        if dlg.exec()!=QDialog.Accepted:
            return
        try:
            result=qc_image_replace.commit_replacement(state['commit_payload'],state['final_prompts'],target_generation_mode=state['target_mode'],mode_touched=state['mode_touched'])
        except Exception as exc:
            QMessageBox.warning(self,'替换图片失败',str(exc)); return

        self._qc_optimistic.clear(); self._qc_inflight.clear(); self._qc_current_signature=None; self._qc_undo_stack.clear()
        self._refresh_qc_data(force=True,preserve_player=False)
        if not self._qc_downstream_timer.isActive(): self._qc_downstream_timer.start()
        self.qc_report.setText(f"完整视频 {int(context['video_seq']):02d} 已替换图片；原编号和文案保持不变，{len(result['segment_ids'])} 个片段已重新进入 Flow 返工队列。")
        QMessageBox.information(self,'替换图片完成',
            f"视频 {int(context['video_seq']):02d} 已使用新图片。\n"
            f"原任务身份和文案保持不变，共 {len(result['segment_ids'])} 个原片段已重新提交 Flow。\n"
            "旧图片和旧视频版本均保留，但旧视频已标记为“已替换图片”，不会进入自动剪辑或交付。")

    def undo_last_qc_action(self):
        if not self._qc_undo_stack:
            QMessageBox.information(self,'撤销','当前没有可撤销的质检操作。'); return
        action=self._qc_undo_stack[-1]
        if any(int(oid) in self._qc_inflight for oid in action.get('ids',[])):
            QMessageBox.information(self,'撤销','最近一次质检结果仍在保存，请稍后再撤销。'); return
        results=[]
        try:
            for oid in action.get('ids',[]):
                prev=action.get('previous',{}).get(int(oid),{})
                result=repo.undo_qc_output_decision(int(oid),str(action.get('status') or ''),str(prev.get('qc_status') or '待质检'),str(prev.get('qc_note') or ''))
                results.append(result)
                if not result.get('ok'):
                    raise ValueError(result.get('message') or '当前状态不能安全撤销')
        except Exception as exc:
            QMessageBox.warning(self,'无法撤销',str(exc)); return
        self._qc_undo_stack.pop()
        target=int(action.get('origin') or (action.get('ids') or [0])[0] or 0)
        self._qc_optimistic.clear(); self._qc_inflight.clear(); self._qc_current_signature=None
        self._qc_restore_output=target
        self._refresh_qc_data(force=True,preserve_player=True)
        if target in self._row_index_by_output:
            row=self._qc_row_cache.get(target)
            if row is not None: self._selected_qc_host_id=int(row['host_id']); self._qc_view_mode='pending'; self._sync_qc_view_buttons(); self._render_task_workspace(self._qc_current_rows)
            self._select_output_id(target)
        if not self._qc_downstream_timer.isActive(): self._qc_downstream_timer.start()
        self.qc_report.setText('已撤销最近一次质检决定；后续生产状态已按安全条件同步恢复。')

    def _recalculate_qc_left_state(self):
        by_video={}
        for item in self._qc_current_rows:
            by_video.setdefault(int(item['video_id']),[]).append(item)
        states={}; targets={}; host_counts={}
        for item in self._qc_queue_rows:
            vid=int(item['video_id']); hid=int(item['host_id'])
            current=sorted(by_video.get(vid,[]),key=lambda value:int(value['seg_seq']))
            expected=int(item.get('segment_count') or 0)
            effective=[self._effective_qc_status(value['output_id'],value['qc_status']) for value in current]
            passed=sum(1 for value in effective if value=='通过')
            rework=any(value=='退回' for value in effective) or int((item.get('waiting_reasons') or {}).get('返工中',0) or 0)>0
            if expected>0 and passed==expected:
                state='passed'
            elif rework:
                state='rework'
            else:
                state='pending'
            states[vid]=state
            target=None
            if state!='rework' and current:
                pending=next((value for value in current if self._effective_qc_status(value['output_id'],value['qc_status'])=='待质检' and int(value['output_id']) not in self._qc_inflight),None)
                target=pending or current[0]
            targets[vid]=int(target['output_id']) if target is not None else None
            bucket=host_counts.setdefault(hid,{'passed':0,'total':0})
            bucket['total']+=1; bucket['passed']+=1 if state=='passed' else 0
        self._qc_video_state=states; self._qc_video_target=targets; self._qc_host_pass_counts=host_counts

    def _apply_video_button_style(self, button, state, current=False):
        dark=self.palette().color(QPalette.Window).lightness()<128
        if dark:
            bg,fg,border='#252E3A','#D8E2EF','#3B4656'
            if state=='passed': bg,fg,border='#183B2F','#70E0A6','#2D654E'
        else:
            bg,fg,border='#F4F7FB','#33415A','#DDE5F0'
            if state=='passed': bg,fg,border='#E9F8F0','#178656','#B8E3CA'
        if current: border='#4B82F1' if dark else '#2F6FED'
        width=2 if current else 1
        button.setStyleSheet(
            f"QPushButton{{background:{bg};color:{fg};border:{width}px solid {border};border-radius:8px;font-weight:800;padding:0px;}}"
            f"QPushButton:hover{{border-color:{'#75A2FF' if dark else '#6E9AF5'};}}"
            f"QPushButton:disabled{{background:{bg};color:{fg};border:{width}px solid {border};}}"
        )
        marker=getattr(button,'_rework_marker',None)
        if marker is not None:
            marker.setVisible(state=='rework')

    def _update_qc_left_widgets(self):
        self._recalculate_qc_left_state()
        for vid,button in list(self._qc_video_buttons.items()):
            self._apply_video_button_style(button,self._qc_video_state.get(int(vid),'pending'),int(vid)==int(self._current_qc_video_id or 0))
            target=self._qc_video_target.get(int(vid)); button.setEnabled(bool(target))
            if target:
                button.setToolTip('点击切换到该完整视频')
            elif self._qc_video_state.get(int(vid))=='rework':
                button.setToolTip('已退回，正在返工；新片段返回后会自动恢复可点')
            else:
                button.setToolTip('尚未生成可质检片段')
        for hid,label in list(self._qc_host_count_labels.items()):
            counts=self._qc_host_pass_counts.get(int(hid),{'passed':0,'total':0}); label.setText(f"{counts['passed']}/{counts['total']}")
        self._update_qc_metrics_from_cache()

    def _select_qc_host(self, host_id, auto_open=True):
        host_id=int(host_id); changed=host_id!=self._selected_qc_host_id; self._selected_qc_host_id=host_id
        if changed:
            self._render_task_workspace(self._qc_current_rows)
        if auto_open:
            target=self._first_pending_output_for_host(host_id)
            if target is not None: self._select_output_id(target)

    def _first_pending_output_for_host(self, host_id):
        host_id=int(host_id)
        candidates=[item for item in self._qc_current_rows if int(item['host_id'])==host_id and int(item['output_id']) not in self._qc_inflight]
        for item in candidates:
            if self._effective_qc_status(item['output_id'],item['qc_status'])=='待质检': return int(item['output_id'])
        return int(candidates[0]['output_id']) if candidates else None

    def _next_pending_output(self, current_output_id):
        ordered=list(self._qc_current_rows)
        if not ordered: return None
        try: start=next(i for i,item in enumerate(ordered) if int(item['output_id'])==int(current_output_id))
        except StopIteration: start=-1
        sequence=ordered[start+1:]+ordered[:start+1]
        current=self._qc_row_cache.get(int(current_output_id)); preferred_host=int(current['host_id']) if current else int(self._selected_qc_host_id or 0)
        def valid(item):
            oid=int(item['output_id'])
            return oid not in self._qc_inflight and self._effective_qc_status(oid,item['qc_status'])=='待质检'
        same=next((item for item in sequence if int(item['host_id'])==preferred_host and valid(item)),None)
        target=same or next((item for item in sequence if valid(item)),None)
        return int(target['output_id']) if target is not None else None

    def _render_task_workspace(self, rows):
        from app.ui.qc_cards import render
        render(self)

    def _update_qc_metrics_from_cache(self):
        try:
            pending=sum(1 for item in self._qc_current_rows if self._effective_qc_status(item['output_id'],item['qc_status'])=='待质检')
            passed=sum(1 for item in self._qc_current_rows if self._effective_qc_status(item['output_id'],item['qc_status'])=='通过')
            counts=getattr(self,'_qc_rework_counts',{'total':0,'active':0})
            pending_redo=sum(1 for oid,status in self._qc_optimistic.items() if status=='退回' and int(oid) in self._qc_inflight)
            redo=int(counts['total'])+pending_redo
            self.metric_pending.setText(str(pending)); self.metric_passed.setText(str(passed)); self.metric_redo.setText(str(redo)); self.metric_total.setText(str(len(self._qc_current_rows)))
            self.metric_redo.setToolTip(f"累计退回 {redo} 次；当前返工待通过 {counts['active']} 个片段")
        except Exception:
            pass

    def _light_refresh_qc_pool(self):
        if not self.isVisible(): return
        self._refresh_qc_data(force=False,preserve_player=True)

    def _install_shortcuts(self):
        binds={"A":lambda:self.set_selected("通过"),"D":self.reject_with_reason,"Space":self.toggle_play,"Left":lambda:self._seek_by(-3000),"Right":lambda:self._seek_by(3000),"Up":lambda:self._move_row(-1),"Down":lambda:self._move_row(1),"F":self._toggle_fullscreen}
        self._shortcuts=[]
        for key,fn in binds.items():
            sc=QShortcut(QKeySequence(key),self); sc.setContext(Qt.WidgetWithChildrenShortcut); sc.activated.connect(fn); self._shortcuts.append(sc)
    def _native_player_enabled(self):
        return bool(getattr(self,'mac_player_switch',None) and self.mac_player_switch.isChecked() and getattr(self,'native_player_widget',None))

    def _native_player_error(self, message):
        if not self._native_player_enabled():
            return
        try:
            self.mac_player_switch.blockSignals(True); self.mac_player_switch.setChecked(False); self.mac_player_switch.blockSignals(False)
        except Exception:
            pass
        self.player_stack.setCurrentWidget(self.video_widget)
        self.qc_report.setText('Mac 原生播放器不可用，已自动回退 QMediaPlayer · '+str(message or ''))
        if self.current_output:
            source=QUrl.fromLocalFile(self.current_output) if Path(self.current_output).is_file() else QUrl(self.current_output)
            self._pending_video_source=source; QTimer.singleShot(0,self._apply_pending_video_source)

    def _switch_qc_player_backend(self, enabled):
        if not self.isVisible():
            self._deferred_player_backend=enabled;return
        want_native=bool(enabled and getattr(self,'native_player_widget',None))
        source_text=str(self.current_output or '').strip()
        position=0
        try:
            # toggled() fires after the checkbox state changes, therefore capture
            # the position from the backend we are leaving rather than the new one.
            position=(self.player.position() if self.player else 0) if want_native else (self.native_player_widget.position() if self.native_player_widget else 0)
        except Exception:
            position=0
        if want_native:
            if self.player:
                try: self.player.pause()
                except Exception: pass
            self.player_stack.setCurrentWidget(self.native_player_widget)
            if source_text:
                source=QUrl(source_text) if QUrl(source_text).scheme() else QUrl.fromLocalFile(source_text)
                if not self.native_player_widget.set_source(source):
                    self._native_player_error(self.native_player_widget.import_error or 'AVPlayer 初始化失败')
                    return
                if position>0: self.native_player_widget.set_position(position)
        else:
            if self.native_player_widget:
                try: self.native_player_widget.pause()
                except Exception: pass
            self.player_stack.setCurrentWidget(self.video_widget)
            if self.player and source_text:
                source=QUrl(source_text) if QUrl(source_text).scheme() else QUrl.fromLocalFile(source_text)
                self._pending_video_source=source; QTimer.singleShot(0,self._apply_pending_video_source)
                if position>0: QTimer.singleShot(150,lambda p=position:self.player.setPosition(p) if self.player else None)

    def _set_active_player_position(self, value):
        if self._native_player_enabled():
            self.native_player_widget.set_position(value)
        elif self.player:
            self.player.setPosition(value)

    def _active_player_position(self):
        if self._native_player_enabled():
            return self.native_player_widget.position()
        return self.player.position() if self.player else 0

    def _autoplay_loaded(self,status):
        if self.player and not self._native_player_enabled() and status in (QMediaPlayer.MediaStatus.LoadedMedia,QMediaPlayer.MediaStatus.BufferedMedia):
            self.player.play()
    def _seek_by(self,delta):
        self._set_active_player_position(max(0,self._active_player_position()+delta))
    def _move_row(self,delta):
        r=self.table.currentRow(); n=self.table.rowCount()
        if n: self.table.selectRow(max(0,min(n-1,(r if r>=0 else 0)+delta)))
    def _toggle_fullscreen(self):
        if self._native_player_enabled():
            self.native_player_widget.toggle_fullscreen(); return
        if self.video_widget and hasattr(self.video_widget,'setFullScreen'):self.video_widget.setFullScreen(not self.video_widget.isFullScreen())

    def qc_change_page(self, delta, reset=False):
        self.qc_page_index = 0 if reset else self.qc_page_index + delta
        self.reload()

    def selected_ids(self):
        rows = sorted({x.row() for x in self.table.selectionModel().selectedRows()})
        return [
            int(self.table.item(row, 0).data(Qt.UserRole))
            for row in rows if self.table.item(row, 0)
        ]

    def reject_with_reason(self):
        if not self.selected_ids():
            QMessageBox.information(self,"视频质检","请先选择需要处理的片段。")
            return
        dlg=QDialog(self)
        dlg.setWindowTitle("退回重做 · 选择主要原因")
        dlg.setModal(True)
        box=QVBoxLayout(dlg)
        title=QLabel("选择一个主要退回原因；点击后立即进入 REWORK。")
        title.setWordWrap(True); box.addWidget(title)
        reasons=["人物/面部异常","口型/台词问题","动作问题","镜头问题","声音问题","画面穿帮","人物一致性","其他"]
        grid=QGridLayout(); chosen={'value':''}
        def pick(reason):
            chosen['value']=reason; dlg.accept()
        for i,reason in enumerate(reasons):
            b=QPushButton(f"{i+1}. {reason}")
            b.setMinimumHeight(44)
            b.clicked.connect(lambda _=False,r=reason: pick(r))
            grid.addWidget(b,i//2,i%2)
        box.addLayout(grid)
        if dlg.exec()!=QDialog.Accepted or not chosen['value']:
            return
        self.set_selected("退回", chosen['value'])

    def keyPressEvent(self, event):
        key=event.key()
        if key==Qt.Key_A:
            self.set_selected("通过"); return
        if key==Qt.Key_D:
            self.reject_with_reason(); return
        if key==Qt.Key_Space:
            self.toggle_play(); return
        super().keyPressEvent(event)

    def set_selected(self, status, note=""):
        ids=self.selected_ids()
        if not ids:
            QMessageBox.information(self,"视频质检","请先选择需要处理的片段。")
            return
        ids=[int(oid) for oid in ids if int(oid) not in self._qc_inflight]
        if not ids: return
        current_id=ids[0]
        previous={}
        for oid in ids:
            item=self._qc_row_cache.get(int(oid))
            previous[int(oid)]={'qc_status':str(item.get('qc_status') if isinstance(item,dict) else (item['qc_status'] if item is not None else '待质检') or '待质检'),
                                'qc_note':str(item.get('qc_note') if isinstance(item,dict) else (item['qc_note'] if item is not None else '') or '')}
        # Optimistic left-side feedback: no full page rebuild and no wait for database/Flow work.
        for oid in ids:
            self._qc_optimistic[oid]=status; self._qc_inflight.add(oid)
        self._update_qc_left_widgets()
        next_id=self._next_pending_output(current_id)
        if next_id is not None:
            next_row=self._qc_row_cache.get(int(next_id))
            if next_row is not None and int(next_row['host_id'])!=int(self._selected_qc_host_id or 0):
                self._selected_qc_host_id=int(next_row['host_id']); self._render_task_workspace(self._qc_current_rows)
            self._select_output_id(next_id)
        else:
            self.info_status.setText('已通过' if status=='通过' else '返工中')
        self._qc_epoch+=1
        future=self._qc_executor.submit(workflow.review_outputs,list(ids),status,note)
        self._qc_jobs.append({'future':future,'ids':list(ids),'status':status,'note':note,'origin':current_id,'previous':previous})
        if not self._qc_async_timer.isActive(): self._qc_async_timer.start()

    def _poll_qc_jobs(self):
        if not self._qc_jobs:
            self._qc_async_timer.stop(); return
        remaining=[]
        for job in self._qc_jobs:
            future=job['future']
            if not future.done():
                remaining.append(job); continue
            error=None
            try: future.result()
            except Exception as exc: error=exc
            for oid in job['ids']:
                self._qc_inflight.discard(int(oid)); self._qc_optimistic.pop(int(oid),None)
            if error is not None:
                self._recalculate_qc_left_state(); self._update_qc_left_widgets()
                if int(job['origin']) in self._row_index_by_output: self._select_output_id(int(job['origin']))
                QMessageBox.warning(self,'质检失败',str(error))
            else:
                # Commit the result into the already-rendered left model only. A lightweight
                # timer reconciles with SQLite later, so successful clicks never rebuild the page.
                self._apply_committed_qc_locally(job)
                if not self._qc_downstream_timer.isActive(): self._qc_downstream_timer.start()
        if len(remaining)!=len(self._qc_jobs):self._qc_epoch+=1;self.mark_dirty()
        self._qc_jobs=remaining
        if not remaining: self._qc_async_timer.stop()

    def _apply_committed_qc_locally(self, job):
        status=str(job.get('status') or '')
        selected=set(self.selected_ids())
        for oid in job.get('ids',[]):
            oid=int(oid); item=self._qc_row_cache.get(oid)
            if item is not None:
                try: item['qc_status']=status
                except Exception: pass
            row_index=self._row_index_by_output.get(oid)
            if row_index is not None and self.table.item(row_index,4) is not None:
                self.table.item(row_index,4).setText(status)
        # Passing can stay fully local: this signature matches the committed DB row, so the
        # pool timer does not rebuild anything. Rework removes the current output from the DB,
        # which naturally produces a different signature on the next lightweight poll.
        self._qc_current_signature=tuple((int(item['output_id']),str(item['qc_status'] or '待质检'),int(item['video_id']),int(item['host_id'])) for item in self._qc_current_rows)
        self._qc_undo_stack.append({'ids':[int(x) for x in job.get('ids',[])],'status':status,'origin':int(job.get('origin') or 0),'previous':job.get('previous',{})})
        self._qc_undo_stack=self._qc_undo_stack[-20:]
        self._update_qc_left_widgets(); self._render_task_workspace(self._qc_current_rows)
        if selected.intersection({int(x) for x in job.get('ids',[])}):
            self.info_status.setText('已通过' if status=='通过' else ('返工中' if status=='退回' else status))

    def _sync_qc_downstream(self):
        owner=self._workflow_owner
        if not owner: return
        errors=[]
        # Preserve every original downstream handoff, but isolate refresh failures so one
        # page cannot prevent the rework dispatcher or editing queue from receiving the QC result.
        if hasattr(owner,'flow_task_center'):
            try: owner.flow_task_center.dispatch_redo(); owner.flow_task_center.reload_tasks()
            except Exception as exc: errors.append(f'Flow：{exc}')
        if hasattr(owner,'davinci_page'):
            try:
                owner.davinci_page._queue_signature=None
                if owner.davinci_page.isVisible():owner.davinci_page.reload()
            except Exception as exc: errors.append(f'DaVinci：{exc}')
        if hasattr(owner,'stats_page'):
            try:
                if owner.stats_page.isVisible():owner.stats_page.reload()
            except Exception as exc: errors.append(f'统计：{exc}')
        if errors:
            # QC decision has already committed; downstream refresh failure must not roll it back.
            self.qc_report.setText('质检结果已保存；下游刷新异常：'+'；'.join(errors))

    def reload(self):
        self._refresh_qc_data(force=True,preserve_player=False)

    def mark_dirty(self):
        self._qc_dirty=True

    def showEvent(self,event):
        super().showEvent(event)
        if hasattr(self,'_deferred_player_backend'):
            enabled=self._deferred_player_backend;del self._deferred_player_backend
            self._switch_qc_player_backend(enabled)
        if hasattr(self,'_qc_pool_timer'):
            self._qc_pool_timer.start();self._refresh_qc_data(preserve_player=True)

    def hideEvent(self,event):
        if hasattr(self,'_qc_pool_timer'):self._qc_pool_timer.stop()
        self._pending_video_source=None
        if self.native_player_widget:self.native_player_widget.pause()
        if self.player:self.player.pause()
        super().hideEvent(event)

    @staticmethod
    @measured('QC_refresh')
    def _read_qc_snapshot(key):
        day,query,epoch=key
        current=[dict(r) for r in repo.list_qc_segments(status_filter='全部',work_date=day)]
        queue=[dict(r) for r in repo.list_edit_queue(work_date=day)]
        if query:
            current=[r for r in current if query in f"{r['recipient_name']} {r['host_name']} {int(r['video_seq']):02d}".lower()]
            queue=[r for r in queue if query in f"{r.get('recipient_name','')} {r.get('host_name','')} {int(r.get('video_seq') or 0):02d}".lower()]
        from app.ui.qc_cards import thumbnails
        return current,queue,dict(repo.qc_rework_counts(work_date=day)),thumbnails(queue)

    def _refresh_qc_data(self, force=False, preserve_player=True):
        day=work_dates.active()
        if self._qc_loaded_day!=day:
            self._qc_loaded_day=day;self._qc_current_signature=None
            self.table.blockSignals(True);self.table.setRowCount(0);self.table.blockSignals(False)
            self._qc_row_cache={};self._row_index_by_output={};self._qc_current_rows=[];self._visible_qc_rows=[];self._qc_queue_rows=[]
            self.current_output='';self._pending_video_source=None;self._qc_next_path=None
            self._clear_layout_widgets(self.segment_strip);self._segment_buttons={}
            self._render_task_workspace([])
            if self.native_player_widget:self.native_player_widget.stop(clear=True)
            if self.player:self.player.stop();self.player.setSource(QUrl())
        if force:self._qc_epoch+=1
        if getattr(self,'_date_view_refresh',False):self._qc_no_autoplay_epoch=self._qc_epoch
        self._qc_dirty=True
        if self.isVisible():
            self._qc_reader.request((work_dates.active(),self.qc_search.text().strip().lower(),self._qc_epoch))

    def _qc_snapshot_ready(self,key,result,error):
        suppress=key[2]==getattr(self,'_qc_no_autoplay_epoch',None)
        previous=getattr(self,'_date_view_refresh',False)
        if suppress:self._date_view_refresh=True
        try:self._apply_qc_snapshot(key,result,error)
        finally:
            self._date_view_refresh=previous
            if suppress and self.isVisible() and not error:self._qc_no_autoplay_epoch=None

    @measured('QC_refresh')
    def _apply_qc_snapshot(self,key,result,error):
        if key!=(work_dates.active(),self.qc_search.text().strip().lower(),self._qc_epoch) or not self.isVisible():return
        if error:
            self.qc_report.setText('质检列表读取失败：'+error);return
        if self._qc_inflight:
            self._qc_dirty=True;return
        current,queue,counts,images=result
        self._qc_host_images=images
        current_signature=repr((current,queue,counts,[(hid,value[0]) for hid,value in images.items()]))
        if current_signature==self._qc_current_signature:return
        preserve_player=True
        if self._qc_loaded_day!=key[0]:
            self.table.blockSignals(True);self.table.setRowCount(0);self.table.blockSignals(False)
            self._qc_row_cache={};self._row_index_by_output={};self.current_output='';self._pending_video_source=None
            if self.native_player_widget:self.native_player_widget.stop(clear=True)
            if self.player:self.player.stop();self.player.setSource(QUrl())
            self._qc_loaded_day=key[0]
        self._qc_rework_counts=counts;self._qc_dirty=False
        previous_ids=self.selected_ids(); previous_id=int(previous_ids[0]) if previous_ids else None
        self._qc_current_rows=list(current);self._visible_qc_rows=list(current);self._qc_queue_rows=list(queue);self._qc_row_cache={int(r['output_id']):r for r in current}
        self.table.blockSignals(True)
        wanted=set(self._qc_row_cache)
        for oid,index in sorted(self._row_index_by_output.items(),key=lambda x:x[1],reverse=True):
            if oid not in wanted:self.table.removeRow(index)
        self._row_index_by_output={int(self.table.item(i,0).data(Qt.UserRole)):i for i in range(self.table.rowCount())}
        for desired_index,item in enumerate(current):
            oid=int(item['output_id']);index=self._row_index_by_output.get(oid)
            if index is None:
                index=desired_index;self.table.insertRow(index)
                self._row_index_by_output={key:(value+1 if value>=index else value) for key,value in self._row_index_by_output.items()};self._row_index_by_output[oid]=index
                for col in range(5):self.table.setItem(index,col,QTableWidgetItem())
                self.table.item(index,0).setData(Qt.UserRole,oid)
            values=[item['recipient_name'],item['host_name'],f'{int(item["video_seq"]):02d}',f'{int(item["seg_seq"]):02d}',self._effective_qc_status(oid,item['qc_status'])]
            for col,value in enumerate(values):
                cell=self.table.item(index,col)
                if cell.text()!=str(value):cell.setText(str(value))
        if previous_id in self._row_index_by_output:
            self.table.selectRow(self._row_index_by_output[previous_id])
        self.table.blockSignals(False)
        self._recalculate_qc_left_state(); self._render_task_workspace(current); self._update_qc_metrics_from_cache(); self._qc_current_signature=current_signature
        restore=getattr(self,'_qc_restore_output',None)
        if restore in self._row_index_by_output:
            self._qc_restore_output=None;self._select_output_id(restore);return
        if previous_id in self._row_index_by_output:
            # Keep the current media source exactly as-is during background pool refreshes.
            self.load_selected_preview()
            return
        target=self._first_pending_output_for_host(int(self._selected_qc_host_id or 0))
        if target is None:
            target=next((int(item['output_id']) for item in current if self._effective_qc_status(item['output_id'],item['qc_status'])=='待质检'),int(current[0]['output_id']) if current else None)
        if target is not None:
            target_row=self._qc_row_cache.get(int(target))
            if target_row is not None: self._selected_qc_host_id=int(target_row['host_id']); self._render_task_workspace(current)
            self._select_output_id(target)
        else:
            self.current_output=''; self._current_qc_video_id=None; self.preview_title.setText('暂无待审核片段'); self.info_host.setText('—'); self.info_recipient.setText('Flow 下载完成后会自动进入这里'); self.info_video.setText('—'); self.info_status.setText('等待任务'); self.qc_generation_mode.setMode('FRAME',emit=False); self.info_foreign_copy.setText(''); self.position_label.setText('0 / 0'); self._clear_layout_widgets(self.segment_strip); self._segment_buttons={}; self.segment_content.setMinimumWidth(0)
            if self.native_player_widget: self.native_player_widget.stop(clear=True)
            if self.player: self.player.stop(); self.player.setSource(QUrl())

    def adjust_clip_frame(self):
        ids=self.selected_ids()
        if not ids or not hasattr(self.video_widget,'set_transform'):return
        if self._native_player_enabled():self.mac_player_switch.setChecked(False)
        from app.ui.clip_transform import ClipTransformDialog
        dialog=ClipTransformDialog(int(ids[0]),self.video_widget,self)
        self._adjusting_clip=True
        try:dialog.exec()
        finally:self._adjusting_clip=False

    def load_selected_preview(self):
        if getattr(self,"_adjusting_clip",False):return
        ids=self.selected_ids()
        if not ids: return
        row=self._qc_row_cache.get(int(ids[0]))
        if row is None:self.mark_dirty();return
        if not row: return
        if hasattr(self.video_widget,'set_transform'):
            from app.services.clip_transform import get
            transform=get(int(row['output_id']))
            self.video_widget.set_transform(transform)
            adjusted=transform['ZoomX']!=1 or transform['Pan']!=0 or transform['Tilt']!=0
            self.transform_btn.setText('画面调整 · 已调整' if adjusted else '画面调整')
        old_video=self._current_qc_video_id; old_host=self._selected_qc_host_id
        self._current_qc_video_id=int(row['video_id']); self._selected_qc_host_id=int(row['host_id'])
        try:
            idx=next(i for i,item in enumerate(self._visible_qc_rows) if int(item['output_id'])==int(row['output_id']))
            self.position_label.setText(f'{idx+1} / {len(self._visible_qc_rows)}')
        except Exception: self.position_label.setText('—')
        self.preview_title.setText(f'{row["recipient_name"]} / {row["host_name"]} / 视频 {int(row["video_seq"]):02d} / 片段 {int(row["seg_seq"]):02d}')
        self.info_host.setText(str(row['host_name'] or '—')); self.info_recipient.setText(str(row['recipient_name'] or '—')); self.info_video.setText(f'{int(row["video_seq"]):02d}   ·   片段 {int(row["seg_seq"]):02d}')
        effective=self._effective_qc_status(row['output_id'],row['qc_status']); status_text={'通过':'已通过','退回':'返工中','待质检':'待质检'}.get(effective,effective); self.info_status.setText(status_text)
        self.qc_generation_mode.setMode(row['generation_mode'] if 'generation_mode' in row.keys() else 'FRAME',emit=False)
        segment_foreign=' '.join(str(row['foreign_text'] or '').split())
        shown_foreign=segment_foreign
        self.info_foreign_copy.setText(shown_foreign or '—'); self.info_foreign_copy.setCursorPosition(0); self.info_foreign_copy.setToolTip(shown_foreign or '暂无外文文案')
        script=segment_foreign; self.info_script.setText(script[:150]+('…' if len(script)>150 else ''))
        self.dialogue.setPlainText(row['foreign_text'] or ''); self.prompt.setPlainText(row['prompt'] or '')
        if not hasattr(self,'_segment_buttons'):self._segment_buttons={}
        siblings=[item for item in self._visible_qc_rows if int(item['video_id'])==int(row['video_id'])]
        ordered_siblings=sorted(siblings,key=lambda value:int(value['seg_seq']))
        rail_width=(len(ordered_siblings)*54)+max(0,len(ordered_siblings)-1)*6
        self.segment_content.setMinimumWidth(rail_width);self.segment_content.setFixedHeight(40)
        current_segment_button=None
        for item in ordered_siblings:
            current=int(item['output_id'])==int(row['output_id']); st=self._effective_qc_status(item['output_id'],item['qc_status'])
            obj='segmentBtnCurrent' if current else ('segmentBtnDone' if st=='通过' else ('segmentBtnRedo' if st=='退回' else 'segmentBtn'))
            oid=int(item['output_id']);button=self._segment_buttons.get(oid)
            if button is None:
                button=QPushButton();button.setFixedSize(54,40);button.clicked.connect(lambda _=False,o=oid:self._select_output_id(o));self.segment_scroll.register_drag_widget(button);self._segment_buttons[oid]=button
            button.setText(f'{int(item["seg_seq"]):02d}')
            if button.objectName()!=obj:button.setObjectName(obj);button.style().unpolish(button);button.style().polish(button)
            if current: current_segment_button=button
        wanted={int(r['output_id']) for r in ordered_siblings}
        for oid in list(self._segment_buttons):
            if oid not in wanted:
                button=self._segment_buttons.pop(oid);self.segment_strip.removeWidget(button);button.deleteLater()
        from app.ui.qc_cards import reorder
        reorder(self.segment_strip,[self._segment_buttons[int(r['output_id'])] for r in ordered_siblings])
        self._qc_preview_oid=int(row['output_id'])
        # Auto-follow the selected segment without exposing a scrollbar.  QTimer waits
        # until Qt has recalculated the rail width after the buttons were rebuilt.
        if current_segment_button is not None:
            QTimer.singleShot(0,lambda b=current_segment_button:self.segment_scroll.ensureWidgetVisible(b,24,0))
        if old_host!=self._selected_qc_host_id:
            self._render_task_workspace(self._qc_current_rows)
        else:
            for vid in {int(old_video or 0),int(self._current_qc_video_id or 0)}:
                button=self._qc_video_buttons.get(vid)
                if button is not None: self._apply_video_button_style(button,self._qc_video_state.get(vid,'pending'),vid==int(self._current_qc_video_id or 0))
        report=[]
        try:
            sp=json.loads(row['speech_analysis_json'] or '{}') if row['speech_analysis_json'] else {}
            if sp: report.append('Whisper有效区间已识别')
        except Exception: pass
        self.qc_report.setText('Space 播放/暂停 · ←/→ 前后 3 秒 · ↑/↓ 上一条/下一条 · F 全屏'+((' · '+report[0]) if report else ''))
        image=str(row['image_path'] or '')
        # The reference label is hidden; host thumbnails are loaded by the read worker.
        local=self._resolve_qc_local_path(str(row['flow_output_path'] or '').strip()); remote=str(row['flow_output_url'] or '').strip(); output=local or remote
        unchanged=self.current_output==output; self.current_output='' if getattr(self,"_date_view_refresh",False) else output
        if not output:
            self.qc_report.setText('等待下载文件路径同步… · Space 播放/暂停 · A 通过 · 下方原因按钮退回')
        if self.player and not unchanged and output and not getattr(self,"_date_view_refresh",False):
            source=QUrl.fromLocalFile(local) if local else QUrl(remote); self._pending_video_source=source; QTimer.singleShot(0,self._apply_pending_video_source)

    def _apply_pending_video_source(self):
        if not self.isVisible():return
        if self._pending_video_source is None:
            return
        if not self.player and not self._native_player_enabled():
            return
        source = self._pending_video_source
        self._pending_video_source = None
        try:
            if self._native_player_enabled():
                self.player.stop(); self.player.setSource(QUrl())
                if not self.native_player_widget.set_source(source):
                    self._native_player_error(self.native_player_widget.import_error or 'AVPlayer 无法加载当前视频')
            else:
                self.player.stop()
                self.player.setSource(source)
                # _autoplay_loaded() starts playback when Qt reports the media ready.
            self._preload_next_qc(getattr(self,'_qc_preview_oid',0))
        except Exception:
            pass

    def auto_qc_tick(self, force_segment=None):
        """Automatic post-download pre-QC intentionally disabled."""
        return

    def _resolve_qc_local_path(self, value):
        value=str(value or '').strip()
        return str(Path(value).expanduser()) if value else ''

    @staticmethod
    def _warm_next_file(path):
        # Bound the read to N+1 and 256 KiB. Never search directories or write files.
        if path:
            try:
                with open(path,'rb') as stream:stream.read(256*1024)
            except OSError:pass
        return None

    def _preload_next_qc(self,oid):
        next_id=self._next_pending_output(oid)
        row=self._qc_row_cache.get(next_id)
        path=self._resolve_qc_local_path(row.get('flow_output_path')) if row and next_id!=oid else ''
        if path!=getattr(self,'_qc_next_path',None):
            self._qc_next_path=path;self._qc_preload_reader.request(path)
            if self.native_player_widget:self.native_player_widget.preload_source(QUrl.fromLocalFile(path) if path else QUrl())

    def toggle_play(self):
        if not self.current_output:
            self.qc_report.setText('等待下载文件路径同步… 当前片段暂不可播放')
            return
        if self._native_player_enabled():
            if self.native_player_widget.is_playing(): self.native_player_widget.pause()
            else: self.native_player_widget.play()
            return
        if not self.player:
            self.qc_report.setText('QMediaPlayer 当前不可用')
            return
        from PySide6.QtMultimedia import QMediaPlayer as _QMP
        if self.player.playbackState() == _QMP.PlayingState:
            self.player.pause()
        else:
            # A paused clip, including its final frames, must resume in place.
            # Rewind only when Qt explicitly reports end of media.
            if self.player.mediaStatus() == _QMP.MediaStatus.EndOfMedia:
                self.player.setPosition(0)
            self.player.play()

    def open_current_output(self):
        if not self.current_output:
            QMessageBox.information(self, "视频预览", "当前片段没有输出文件/链接。")
            return
        _open_path_or_url(self.current_output)


class DaVinciPage(BaseWorkflowPage):
    def __init__(self, parent=None):
        super().__init__(
            '自动剪辑中心',
            '质检全部通过的完整视频自动进入 DaVinci 剪辑流程；这里只监控素材齐套、剪辑、人工检查与导出。',
            parent
        )
        # Dashboard cards. Only presentation changed; edit queue / Resolve APIs stay untouched.
        from app.ui.flow_layouts import CardGrid
        metrics=CardGrid(minimum=160,maximum=360,card_height=100); metrics.setSpacing(10)
        def card(icon,title,default='0',tone='info'):
            f=QFrame(objectName='dashboardMetric'); v=QHBoxLayout(f); v.setContentsMargins(13,10,13,10); ic=QLabel(icon,objectName='metricIcon'); ic.setAlignment(Qt.AlignCenter); v.addWidget(ic); txt=QVBoxLayout(); val=QLabel(default,objectName='metricValue'); val.setProperty('tone',tone); txt.addWidget(val); txt.addWidget(QLabel(title,objectName='metricLabel')); v.addLayout(txt,1); metrics.addWidget(f); return val
        self.metric_ready=QLabel(); self.metric_error=QLabel(); self.metric_wait=card('◇','素材待齐','0','warn'); self.metric_edit=card('⚙','剪辑中','0','info'); self.metric_review=card('●','待检查 · 完整视频','0','bad'); self.metric_export=card('⇧','待导出 / 导出中','0','info'); self.metric_done=card('✓','剪辑完成','0','good')
        status_card=QFrame(objectName='dashboardMetric'); sb=QVBoxLayout(status_card); sb.setContentsMargins(13,10,13,10); self.bridge_state=QLabel('Resolve Bridge：检测中',objectName='statusInfo'); self.bridge_state.setWordWrap(True); sb.addWidget(self.bridge_state); self.detect_status=QLabel('DaVinci：等待任务',objectName='cardMeta'); self.detect_status.setWordWrap(True); sb.addWidget(self.detect_status); metrics.addWidget(status_card); self.root.addLayout(metrics)
        # Full environment details must not be clipped by the 100px dashboard cards.
        self.environment_meta = QLabel('', objectName='cardMeta')
        self.environment_meta.setWordWrap(True)
        self.root.addWidget(self.environment_meta)
        sb.removeWidget(self.detect_status)
        self.root.addWidget(self.detect_status)


        from app.services import resolve_daily
        self._wake_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='resolve-wake')
        self._wake_future = None
        self._wake = None
        self._wake_error = ''
        tools = QHBoxLayout()
        self.launch_resolve_btn = QPushButton('唤醒达芬奇', objectName='primaryBtn')
        self.launch_resolve_btn.clicked.connect(self.open_resolve)
        tools.addWidget(self.launch_resolve_btn)
        self.import_batch_btn = QPushButton('导入剪辑素材')
        self.import_batch_btn.clicked.connect(self.import_materials)
        self._operation = 'wake'
        self.start_autoedit_btn = QPushButton('开始运行自动剪辑')
        self.start_autoedit_btn.clicked.connect(self.start_batch_autoedit)
        self.reanalyze_btn = QPushButton('↻ 重新识别当前批次')
        self.reanalyze_btn.clicked.connect(self.reanalyze_current_batch)
        for button in (self.import_batch_btn, self.start_autoedit_btn, self.reanalyze_btn):
            button.setEnabled(False)
            button.setStyleSheet('QPushButton:disabled { color: #8b94a7; background: #edf0f5; border: 1px solid #d8dfe9; }')
            tools.addWidget(button)
        self.import_batch_btn.setToolTip('导入新的待剪辑批次。')
        self.start_autoedit_btn.setToolTip('第三阶段：整批分析通过后执行切刀，完成后等待人工检查。')
        self.reanalyze_btn.setToolTip('对当前“等待人工检查”批次重新做 Whisper + 每个小片段头尾扫描；保留已有切点，不恢复已经切开的素材。')
        self.manual_complete_batch_btn = QPushButton('✓ 本批次已剪辑完成', objectName='primaryBtn')
        self.manual_complete_batch_btn.setEnabled(False)
        self.manual_complete_batch_btn.setToolTip('仅用于你已经人工完成这一批，但 Studio 仍停在旧批次的情况。')
        self.manual_complete_batch_btn.clicked.connect(self.manual_complete_batch)
        tools.addWidget(self.manual_complete_batch_btn)
        self.skip_batch_btn = QPushButton('跳过当前批次')
        self.skip_batch_btn.setEnabled(False)
        self.skip_batch_btn.setToolTip('结束当前批次并把未确认导出的任务退回后续待剪辑队列。')
        self.skip_batch_btn.clicked.connect(self.skip_current_batch)
        tools.addWidget(self.skip_batch_btn)
        tools.addStretch(1)
        self.root.addLayout(tools)
        logs = QHBoxLayout()
        for title, callback in (('查看本批次日志', self.view_batch_log), ('打开日志目录', self.open_batch_logs)):
            button=QPushButton(title);button.clicked.connect(callback);logs.addWidget(button)
        logs.addStretch(1);self.root.addLayout(logs)
        phase = QLabel('V2 第三阶段测试：斯瓦西里语识别 → 整批文案核对 → 切刀标红 → 等待人工检查。', objectName='muted')
        phase.setWordWrap(True)
        self.root.addWidget(phase)
        advanced_toggle = QPushButton('高级 / 旧版调试 ▸')
        advanced_toggle.setCheckable(True)
        self.root.addWidget(advanced_toggle)
        advanced = QWidget()
        advanced_layout = QVBoxLayout(advanced)
        advanced_layout.addWidget(QLabel('旧版流程会独立处理视频，仅供回退调试；请先停止新版 Bridge。', objectName='muted'))
        legacy_tools = QHBoxLayout()
        for title, callback in (
            ('安装 / 更新新版 Bridge', self.install_resolve_bridge),
            ('旧版：发送剪辑任务', self.submit_autoedit),
            ('旧版：安装 Bridge', self.install_legacy_bridge),
            ('打开集成模块', self.open_integrated_module),
            ('剪辑记录 / 重新剪辑', self.show_editing_history),
        ):
            button = QPushButton(title)
            button.clicked.connect(callback)
            legacy_tools.addWidget(button)
        advanced_layout.addLayout(legacy_tools)
        advanced.hide()
        advanced_toggle.toggled.connect(advanced.setVisible)
        self.root.addWidget(advanced)

        body=QSplitter(Qt.Horizontal); self.edit_body=body; body.setChildrenCollapsible(False); body.setHandleWidth(8)
        main=QWidget(); mv=QVBoxLayout(main); mv.setContentsMargins(0,0,0,0); mv.setSpacing(10)
        current=QFrame(objectName='pageCard'); cv=QVBoxLayout(current); cv.setContentsMargins(16,14,16,14); cv.setSpacing(10)
        h=QHBoxLayout(); h.addWidget(QLabel('当前执行',objectName='sectionTitle')); self.execution_status=QLabel('等待任务',objectName='statusInfo'); h.addWidget(self.execution_status); h.addStretch(1); cv.addLayout(h)
        self.current_batch_title=QLabel('暂无正在执行的剪辑批次',objectName='cardTitle'); cv.addWidget(self.current_batch_title); self.current_batch_meta=QLabel('质检通过并素材齐全后，会自动进入后续剪辑队列。',objectName='muted'); self.current_batch_meta.setWordWrap(True); cv.addWidget(self.current_batch_meta)
        stages=QHBoxLayout(); stages.setSpacing(5)
        for i,(title,sub) in enumerate((('1','素材准备'),('2','自动切分'),('3','人工检查'),('4','自动清理'))):
            sf=QFrame(objectName='stagePill'); sl=QVBoxLayout(sf); sl.setContentsMargins(10,7,10,7); a=QLabel(title,objectName='stageSymbol'); a.setAlignment(Qt.AlignCenter); b=QLabel(sub,objectName='cardMeta'); b.setAlignment(Qt.AlignCenter); sl.addWidget(a); sl.addWidget(b); stages.addWidget(sf,1)
        cv.addLayout(stages); self.current_progress=QProgressBar(); self.current_progress.setRange(0,100); self.current_progress.setValue(0); self.current_progress.setTextVisible(False); cv.addWidget(self.current_progress); self.current_stage=QLabel('等待可剪辑素材',objectName='cardMeta'); cv.addWidget(self.current_stage); mv.addWidget(current)

        queue=QFrame(objectName='pageCard'); qv=QVBoxLayout(queue); qv.setContentsMargins(14,12,14,12); qv.setSpacing(8); qh=QHBoxLayout(); qh.addWidget(QLabel('后续批次',objectName='sectionTitle')); qh.addStretch(1); qh.addWidget(QLabel('等待 DaVinci 自动剪辑',objectName='muted')); qv.addLayout(qh); self.batch_list=QVBoxLayout(); self.batch_list.setSpacing(8); qv.addLayout(self.batch_list); qv.addStretch(1); mv.addWidget(queue,1)
        body.addWidget(main)

        review=QFrame(objectName='detailPanel'); rv=QVBoxLayout(review); rv.setContentsMargins(14,12,14,12); rv.setSpacing(9); rh=QHBoxLayout(); rh.addWidget(QLabel('待人工检查',objectName='sectionTitle')); self.review_badge=QLabel('0 批',objectName='statusBad'); rh.addWidget(self.review_badge); rh.addStretch(1); rv.addLayout(rh); self.review_title=QLabel('暂无待检查批次',objectName='cardTitle'); rv.addWidget(self.review_title); self.review_meta=QLabel('剪辑完成后，整批进入这里。',objectName='muted'); self.review_meta.setWordWrap(True); rv.addWidget(self.review_meta); self.review_list=QVBoxLayout(); self.review_list.setSpacing(6); rv.addLayout(self.review_list); rv.addStretch(1); action=QHBoxLayout(); inspect=QPushButton('◉ 人工检查',objectName='primaryBtn'); inspect.clicked.connect(self.manual_inspect_batch); action.addWidget(inspect); self.finish_batch_btn=QPushButton('确认清理并导出'); self.finish_batch_btn.setEnabled(False); self.finish_batch_btn.clicked.connect(self.finish_batch); action.addWidget(self.finish_batch_btn); self.force_reexport_btn=QPushButton('重新全部导出'); self.force_reexport_btn.setEnabled(False); self.force_reexport_btn.setToolTip('删除该批次已导出的视频并强制重新导出所有视频'); self.force_reexport_btn.clicked.connect(self.force_reexport_all); action.addWidget(self.force_reexport_btn); rv.addLayout(action); body.addWidget(review); body.setSizes([820,390]); body.setMinimumHeight(420); body.setMaximumHeight(680); self.root.addWidget(body)

        wait=QFrame(objectName='pageCard'); wv=QVBoxLayout(wait); wv.setContentsMargins(12,9,12,9); wv.setSpacing(7); wh=QHBoxLayout(); wh.addWidget(QLabel('素材待齐',objectName='sectionTitle')); self.wait_count=QLabel('0',objectName='statusWarn'); wh.addWidget(self.wait_count); wh.addStretch(1); self.wait_expand=QPushButton('展开全部'); self.wait_expand.setCheckable(True); self.wait_expand.toggled.connect(self.render_host_cards); wh.addWidget(self.wait_expand); wv.addLayout(wh); self.wait_row=CardGrid(minimum=270,maximum=460,card_height=130); self.wait_row.setSpacing(8); wv.addLayout(self.wait_row); self.root.addWidget(wait)

        self.table=_make_table(['接收人','AI主播','完整视频','片段数','Flow已完成','质检通过','剪辑准备度','剪辑状态','输出文件']); self.table.hide(); self.details=QPushButton('请先选择主播查看任务明细'); self.details.setCheckable(True); self.details.setEnabled(False); self.details.toggled.connect(self.show_host_details); self.root.addWidget(self.details); self.root.addWidget(self.table); self.edit_root_label=QLabel(''); self.edit_root_label.hide(); self.root.addWidget(self.edit_root_label)
        self._edit_rows=[]; self._selected_host=None; self._host_cards_signature=None; self._thumbnail_cache={};
        self.proc=None; self.prepare_proc=None; self.menu_proc=None; self.pending_script_title=''; self.detect_timer=QTimer(self); self.detect_timer.setSingleShot(True); self.detect_timer.timeout.connect(self.run_preparer); self.resolve_poll_timer=QTimer(self); self.resolve_poll_timer.setInterval(1000); self.resolve_poll_timer.timeout.connect(self.refresh_resolve_bridge); self.resolve_poll_timer.start(); self.queue_poll_timer=QTimer(self); self.queue_poll_timer.setInterval(1500); self.queue_poll_timer.timeout.connect(self.refresh_queue_if_changed); self.queue_poll_timer.start(); self.reload(); self.refresh_resolve_bridge()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'edit_body'):
            narrow=self.width()<850
            self.edit_body.setOrientation(Qt.Vertical if narrow else Qt.Horizontal)
            self.edit_body.setMinimumHeight(700 if narrow else 420)
            self.edit_body.setMaximumHeight(950 if narrow else 680)

    def refresh_queue_if_changed(self):
        if not self.isVisible(): return
        rows=[dict(r) for r in repo.list_edit_queue(work_date=work_dates.active())]
        signature=(work_dates.active(),repr(rows))
        if signature!=getattr(self,'_queue_signature',None):
            self._queue_signature=signature;self.reload(rows)

    def open_resolve(self):
        from app.services.resolve_daily import DailyWake
        if self._wake_future and not self._wake_future.done():
            return
        try:
            self._wake_error = ''
            self._operation = 'wake'
            self._wake = DailyWake(repo.get_setting('timeline_fps', '25') or '25', day=work_dates.active())
            self._wake_future = self._wake_pool.submit(self._wake.run)
            self.launch_resolve_btn.setEnabled(False)
            self.detect_status.setText('正在唤醒达芬奇…')
        except Exception as exc:
            self._wake_error = str(exc)
            self.detect_status.setText('⚠ ' + str(exc))

    def open_batch_logs(self):
        from app.services import resolve_daily, resolve_batches, resolve_autoedit
        batch=resolve_autoedit.current(work_dates.active()) or resolve_batches.latest(work_dates.active())
        folder=resolve_daily.bridge_root()/'logs'
        if batch: folder=folder/batch['batch_id']
        folder.mkdir(parents=True,exist_ok=True)
        _open_path_or_url(str(folder))

    def view_batch_log(self):
        from app.services import resolve_daily, resolve_batches, resolve_autoedit
        batch=resolve_autoedit.current(work_dates.active()) or resolve_batches.latest(work_dates.active())
        path=resolve_daily.bridge_root()/'logs'/(batch['batch_id'] if batch else '')/'import.log'
        if path.with_name('autoedit.log').is_file(): path=path.with_name('autoedit.log')
        dialog=QDialog(self);dialog.setWindowTitle('本批次日志');dialog.resize(850,500)
        layout=QVBoxLayout(dialog);text=QPlainTextEdit();text.setReadOnly(True)
        text.setPlainText(path.read_text(encoding='utf-8') if path.is_file() else '暂无本批次日志。')
        layout.addWidget(text);dialog.exec()

    def force_reexport_all(self):
        if self._wake_future and not self._wake_future.done(): return
        if QMessageBox.question(self, '重新全部导出', '这将删除当前批次已经导出的所有成品视频，并强制达芬奇从头开始重新导出全部视频。\n\n（如果你正在导出中，请先在终端运行停止命令停止 Bridge，然后再重试）。\n\n继续吗？') != QMessageBox.Yes: return
        from app.services import resolve_finish
        from app.core import database
        from app.core import work_dates
        from pathlib import Path
        day = work_dates.active()
        try:
            with database.connect() as con:
                row = con.execute("SELECT payload_path FROM davinci_autoedit_runs WHERE batch_id=(SELECT batch_id FROM davinci_batches WHERE work_date=? AND status IN ('WAITING_USER_REVIEW','CLEANING_ERROR','EXPORT_ERROR','RENDERING','PREPARING_EXPORT') ORDER BY created_at DESC LIMIT 1)", (day,)).fetchone()
            if row:
                base = Path(row['payload_path']).parent
                import shutil
                # Delete all .mp4 and .txt files in the base directory
                for file in base.glob('*.mp4'):
                    file.unlink()
                for file in base.glob('*.txt'):
                    file.unlink()
        except Exception as e:
            QMessageBox.warning(self, "错误", f"清理旧文件失败: {e}")
            return
        self.finish_batch()

    def finish_batch(self):
        if self._wake_future and not self._wake_future.done(): return
        from app.services import resolve_finish
        if QMessageBox.question(self,'清理 / 恢复导出','清理只处理 V1 主视频：红色自动范围 + 蓝色人工指定片段；V2 以上不参与清理判断，但会正常合成进最终导出。若上次因 Ripple 核验中断，将从已保留现场继续，不会重复删除。继续？') != QMessageBox.Yes: return
        from types import SimpleNamespace
        self._operation='finish'
        self._wake=SimpleNamespace(detail='正在提交清理 / 恢复导出…')
        self._wake_future=self._wake_pool.submit(resolve_finish.submit,work_dates.active())
        self.finish_batch_btn.setEnabled(False)

    def manual_complete_batch(self):
        if self._wake_future and not self._wake_future.done(): return
        message=(
            '只在这一批实际上已经人工剪辑完成，或者你已经清空时间线但 Studio 仍卡在旧批次时使用。\n\n'
            '确认后会结束当前批次并解除该批次运行锁。能够核对到真实最终 MP4 的视频会标记为“已导出”；'
            '找不到最终成品文件的只标记为“已剪辑”，不会伪造成品路径，也不会删除任何本地文件。\n\n继续吗？'
        )
        if QMessageBox.question(self,'本批次已剪辑完成',message) != QMessageBox.Yes: return
        try:
            result=resolve_finish.manual_close(work_dates.active(),'complete')
        except Exception as exc:
            QMessageBox.warning(self,'本批次已剪辑完成',str(exc)); return
        self._wake_error=''
        self.detect_status.setText('✓ '+result['detail'])
        self.reload();self.refresh_resolve_bridge()
        QMessageBox.information(self,'本批次已剪辑完成',result['detail'])

    def skip_current_batch(self):
        if self._wake_future and not self._wake_future.done(): return
        message=(
            '跳过后会立即结束当前剪辑批次并解除该批次运行锁。\n\n'
            '已经确认导出的成品会保留；其余视频会回到“待剪辑”，后续可以重新导入新的批次。'
            '不会删除本地视频、不会清理其他日期的批次。\n\n确定跳过当前批次吗？'
        )
        if QMessageBox.question(self,'跳过当前批次',message) != QMessageBox.Yes: return
        try:
            result=resolve_finish.manual_close(work_dates.active(),'skip')
        except Exception as exc:
            QMessageBox.warning(self,'跳过当前批次',str(exc)); return
        self._wake_error=''
        self.detect_status.setText('✓ '+result['detail'])
        self.reload();self.refresh_resolve_bridge()
        QMessageBox.information(self,'跳过当前批次',result['detail'])

    def start_batch_autoedit(self):
        if self._wake_future and not self._wake_future.done(): return
        from types import SimpleNamespace
        from app.services import resolve_autoedit
        self._wake_error = ''
        self._operation = 'autoedit'
        self._wake = SimpleNamespace(detail='正在核对当前批次文案及 Whisper 设置…')
        self._wake_future = self._wake_pool.submit(resolve_autoedit.submit, work_dates.active())
        self.start_autoedit_btn.setEnabled(False)

    def reanalyze_current_batch(self):
        if self._wake_future and not self._wake_future.done(): return
        message=(
            '重新识别会保留当前已经存在的切点，不会自动撤销之前的切刀。\n\n'
            '程序会清除本批次旧的红色/橙色自动标记，保留蓝色人工标记，然后使用最新版算法重新扫描 V1 当前每个小片段的开头和结尾，并在需要的位置继续补切。\n\n'
            '确定重新识别当前批次吗？'
        )
        if QMessageBox.question(self,'重新识别当前批次',message)!=QMessageBox.Yes: return
        from types import SimpleNamespace
        from app.services import resolve_autoedit
        self._wake_error=''
        self._operation='reanalyze'
        self._wake=SimpleNamespace(detail='正在重新识别当前批次；旧红/橙自动标记将由新结果替换…')
        self._wake_future=self._wake_pool.submit(resolve_autoedit.reanalyze,work_dates.active())
        self.reanalyze_btn.setEnabled(False)

    def import_materials(self):
        if self._wake_future and not self._wake_future.done():
            return
        from types import SimpleNamespace
        from app.services import resolve_batches
        self._wake_error = ''
        self._operation = 'import'
        self._wake = SimpleNamespace(detail='正在检查当前待剪辑素材…')
        self._wake_future = self._wake_pool.submit(resolve_batches.submit, work_dates.active())
        self.import_batch_btn.setEnabled(False)
        self.launch_resolve_btn.setEnabled(False)

    def manual_inspect_batch(self):
        try:
            davinci_workflow.launch_resolve()
            self.detect_status.setText('DaVinci：已打开，等待人工检查当前批次')
        except Exception as exc:
            QMessageBox.warning(self,'DaVinci',str(exc))

    def install_resolve_bridge(self):
        from app.services.resolve_daily import install_bridge
        try:
            changed = install_bridge()
            self.detect_status.setText('✓ 新版 Bridge 已安装；首次安装需重新打开达芬奇刷新菜单。' if changed else '✓ 新版 Bridge 已是当前版本')
        except Exception as exc:
            self.detect_status.setText('⚠ ' + str(exc))

    def install_legacy_bridge(self):
        from app.services.resolve_daily import snapshot
        if snapshot().get('alive'):
            self.detect_status.setText('请先停止新版 Bridge，再使用旧版调试。')
            return
        ok, msg = davinci_workflow.install_integrated_bridge()
        self.detect_status.setText(('✓ ' if ok else '⚠ ') + msg)

    def open_integrated_module(self):
        _open_path_or_url(str(davinci_workflow.integrated_module_dir()))

    @staticmethod
    def _resolve_status_worker(day):
        from app.services.resolve_daily import snapshot
        from app.services import resolve_batches, resolve_autoedit, resolve_finish
        st=snapshot();error=''
        try:
            resolve_batches.sync_results()
            resolve_autoedit.sync()
            resolve_finish.sync()
            batch=resolve_autoedit.current(day) or resolve_batches.latest(day)
        except Exception as exc:
            batch=None;error=str(exc)
        return st,batch,error

    def refresh_resolve_bridge(self):
        if not hasattr(self,'_resolve_status_reader'):
            from app.ui.read_snapshot import SnapshotReader
            self._resolve_status_reader=SnapshotReader(self,self._resolve_status_worker)
            self._resolve_status_reader.ready.connect(self._resolve_status_ready)
        self._resolve_status_reader.request(work_dates.active())

    def _resolve_status_ready(self,day,result,error):
        if day!=work_dates.active():return
        if error:
            self._wake_error=error;return
        st,batch,sync_error=result
        if sync_error:self._wake_error=sync_error
        self.resolve_poll_timer.setInterval(1000 if self.isVisible() or st.get('alive') or self._wake_future is not None else 15000)
        future = self._wake_future
        if future and future.done():
            try:
                response = future.result()
                self._wake_error = ''
                if self._operation in ('import','autoedit','reanalyze') and not response.get('submitted'):
                    self._wake_error = response.get('detail', '')
            except Exception as exc:
                self._wake_error = str(exc)
            self._wake_future = None
            self.launch_resolve_btn.setEnabled(True)
        busy = self._wake_future is not None
        if busy:
            self.launch_resolve_btn.setText('唤醒达芬奇' if self._operation in ('import','autoedit','reanalyze') else '⟳ 正在唤醒达芬奇')
            self.detect_status.setText(self._wake.detail)
        else:
            self.launch_resolve_btn.setText('唤醒达芬奇')
            if self._wake_error:
                self.detect_status.setText('⚠ ' + self._wake_error)
            elif st.get('alive'):
                self.detect_status.setText(('⚠ ' + st['warning']) if st.get('warning') else st.get('detail', 'Bridge 在线'))
            elif st.get('version'):
                self.detect_status.setText('Resolve Bridge 连接中断，请重新唤醒；已保留最近状态。')
        ready = st.get('alive') and st.get('stage') == 'READY' and st.get('project') == 'FlowStudio-' + work_dates.active()
        self.bridge_state.setText('🟢 达芬奇已就绪' if ready else ('🟡 Bridge 在线' if st.get('alive') else '○ Bridge 未连接'))
        self.environment_meta.setText(
            ('项目：' + st['project'] if st.get('project') else '项目：等待唤醒') +
            ('    主时间线：' + st['timeline'] if st.get('timeline') else '') +
            '    · 剪辑操作跟随所选日期'
        )
        importing = st.get('alive') and st.get('stage') == 'IMPORTING'
        self.launch_resolve_btn.setEnabled(not busy and not importing)
        self.import_batch_btn.setText('⟳ 正在导入剪辑素材' if importing else ('重试原批次导入' if batch and batch['status']=='IMPORT_ERROR' else '导入剪辑素材'))
        allowed = st.get('alive') and 'IMPORT_BATCH' in st.get('capabilities','').split(',') and st.get('stage') in ('READY','ERROR','WAITING_USER_REVIEW') and st.get('project')=='FlowStudio-'+work_dates.active() and st.get('timeline')=='MAIN-'+work_dates.active()
        self.import_batch_btn.setEnabled(bool(allowed and not busy and (not batch or batch['status'] in ('IMPORTED','IMPORT_ERROR','COMPLETED','SKIPPED'))))
        running = bool(batch and batch['status'] in ('AUTOEDIT_QUEUED','AUDIO_RENDERING','WHISPER_RUNNING','TEXT_ALIGNING','CUTTING'))
        self.launch_resolve_btn.setEnabled(not busy and not importing and not running)
        self.start_autoedit_btn.setEnabled(bool(allowed and 'START_AUTOEDIT' in st.get('capabilities','').split(',') and not busy and batch and batch['status'] in ('IMPORTED','ANALYSIS_ERROR','CUTTING_ERROR')))
        self.start_autoedit_btn.setText('继续未完成切刀' if batch and batch['status']=='CUTTING_ERROR' else '重试整批分析' if batch and batch['status']=='ANALYSIS_ERROR' else '开始运行自动剪辑')
        reanalyze_allowed = bool(st.get('alive') and 'START_AUTOEDIT' in st.get('capabilities','').split(',') and st.get('stage') in ('READY','ERROR','WAITING_USER_REVIEW') and st.get('project')=='FlowStudio-'+work_dates.active() and st.get('timeline')=='MAIN-'+work_dates.active())
        self.reanalyze_btn.setEnabled(bool(reanalyze_allowed and not busy and batch and batch['status']=='WAITING_USER_REVIEW'))
        finishing = st.get('stage') in ('CLEANING','PREPARING_EXPORT','RENDERING')
        self.finish_batch_btn.setEnabled(bool(not busy and not finishing and st.get('alive') and st.get('project')=='FlowStudio-'+work_dates.active() and st.get('timeline')=='MAIN-'+work_dates.active() and 'FINISH_BATCH' in st.get('capabilities','').split(',') and batch and batch['status'] in ('WAITING_USER_REVIEW','CLEANING_ERROR','EXPORT_ERROR','PREPARING_EXPORT','RENDERING')))
        self.finish_batch_btn.setText('继续清理并导出' if batch and batch['status']=='CLEANING_ERROR' else ('重试未完成导出' if batch and batch['status'] in ('EXPORT_ERROR','PREPARING_EXPORT','RENDERING') else '确认清理并导出'))
        manual_states=('IMPORTED','IMPORT_ERROR','WAITING_USER_REVIEW','ANALYSIS_ERROR','CUTTING_ERROR','CLEANING_ERROR','EXPORT_ERROR')
        manual_allowed=bool(not busy and not finishing and batch and batch['status'] in manual_states)
        self.manual_complete_batch_btn.setEnabled(manual_allowed)
        self.skip_batch_btn.setEnabled(manual_allowed)
        if finishing: self.launch_resolve_btn.setEnabled(False)
        self.import_batch_btn.setToolTip('请先唤醒所选日期项目；当前批次未结束时不能导入新批次。')
        if batch:
            closed=batch['status'] in ('COMPLETED','SKIPPED')
            self.current_batch_title.setText(('最近批次：' if closed else '批次：') + batch['batch_id'])
            self.current_batch_meta.setText(f"本批次 {batch['video_count']} 个完整视频 · 新增 {batch['imported_count']} · 已存在跳过 {batch['skipped_count']}")
            self.current_stage.setText(batch['error_message'] or ('✓ 素材已导入，可以开始自动剪辑' if batch['status']=='IMPORTED' else st.get('detail','')))
            self.execution_status.setText({'IMPORTED':'已导入','IMPORT_ERROR':'导入需处理','IMPORTING':'导入中','AUTOEDIT_QUEUED':'准备自动剪辑','AUDIO_RENDERING':'生成 WAV','WHISPER_RUNNING':'识别斯瓦西里语','TEXT_ALIGNING':'核对文案','CUTTING':'执行切刀','WAITING_USER_REVIEW':'等待人工检查','ANALYSIS_ERROR':'分析未通过','CUTTING_ERROR':'切刀中断，需检查','CLEANING_ERROR':'清理中断，需人工处理','EXPORT_ERROR':'导出异常，可手动结束或跳过','COMPLETED':'✓ 本批次已结束','SKIPPED':'已跳过，任务已退回待剪辑'}.get(batch['status'],batch['status']))
            if importing or running:
                self.current_progress.setValue(int(100*int(st.get('current',0))/max(1,int(st.get('total',1)))))
            elif batch['status'] in ('IMPORTED','COMPLETED'):
                self.current_progress.setValue(100)
            elif batch['status']=='SKIPPED':
                self.current_progress.setValue(0)
        else:
            self.manual_complete_batch_btn.setEnabled(False)
            self.skip_batch_btn.setEnabled(False)


    def show_editing_history(self):
        from app.ui.editing_history_dialog import EditingHistoryDialog
        EditingHistoryDialog(self).exec()

    def submit_autoedit(self):
        from app.services.resolve_daily import snapshot
        if snapshot().get('alive'):
            self.detect_status.setText('请先停止新版 Bridge，再使用旧版调试。')
            return
        try:
            data=davinci_workflow.submit_autoedit_jobs()
        except Exception as exc:
            QMessageBox.warning(self,'自动剪辑',str(exc)); return
        if not data.get('ok'):
            QMessageBox.warning(self,'自动剪辑',str(data.get('reason') or '提交失败')); return
        n=int(data.get('submitted') or 0)
        self.detect_status.setText(f'DaVinci：已发送 {n} 个完整视频到 AutoEdit v0.4.5.3')
        if not n:
            QMessageBox.information(self,'自动剪辑','当前没有“全部片段质检通过”的待剪辑完整视频。')
        self.reload();self.refresh_resolve_bridge()

    def approve_batch(self):
        from app.services import resolve_autoedit
        if resolve_autoedit.current(work_dates.active()):
            self.detect_status.setText('当前批次须在后续人工确认与清理阶段处理，不能直接标记为待导出。')
            return
        rows=list(repo.list_edit_queue(work_date=work_dates.active()))
        review=[r for r in rows if str(r['edit_status'] or '') in ('已剪辑','待人工检查','剪辑中')]
        if not review:
            QMessageBox.information(self,'批次检查','当前没有可标记通过的剪辑批次。');return
        ids=[int(r['video_id']) for r in review]
        repo.set_video_edit_status(ids,'待导出')
        self.detect_status.setText(f'DaVinci：已标记 {len(ids)} 个完整视频通过人工检查，进入导出阶段')
        self.reload()

    def open_system_settings(self):
        owner = self.parent()
        if owner and hasattr(owner, 'open_settings'):
            owner.open_settings()

    def selected_ids(self):
        rows = sorted({x.row() for x in self.table.selectionModel().selectedRows()})
        return [int(self.table.item(row, 0).data(Qt.UserRole)) for row in rows if self.table.item(row, 0)]

    def set_selected(self, status):
        ids = self.selected_ids()
        if not ids:
            QMessageBox.information(self, "DaVinci", "请先选择完整视频。")
            return
        repo.set_video_edit_status(ids, status)
        self.reload()

    def bind_export_file(self):
        ids = self.selected_ids()
        if len(ids) != 1:
            QMessageBox.information(self, "绑定导出成品", "请只选择一个完整视频，然后选择对应的最终导出文件。")
            return
        root = repo.get_setting("edit_root_path", "")
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 DaVinci 导出的成品", root or "", "视频 (*.mp4 *.mov *.m4v *.mkv);;所有文件 (*)"
        )
        if not path:
            return
        repo.set_video_edit_output(ids[0], path, "已导出")
        self.reload()

    def launch_and_prepare(self):
        root = davinci_workflow.edit_root()
        if root is None:
            QMessageBox.information(self, "DaVinci", "请先在“系统设置”设置剪辑路径根目录。")
            self.open_system_settings()
            return
        try:
            manifest = davinci_workflow.write_manifest()
            davinci_workflow.launch_resolve()
        except Exception as exc:
            QMessageBox.warning(self, "DaVinci", f"准备失败：{exc}")
            return
        self._pending_manifest = manifest
        self.detect_status.setText("DaVinci：正在启动，随后自动新建项目、设置竖屏时间线并分组导入…")
        self.detect_timer.start(6500)

    def run_preparer(self):
        manifest = getattr(self, '_pending_manifest', None)
        if not manifest:
            return
        script = Path(__file__).resolve().parents[2] / "scripts" / "davinci_prepare.py"
        stamp = QDateTime.currentDateTime().toString("yyyyMMdd_HHmmss")
        project_name = f"FlowStudio_{stamp}"
        self.prepare_proc = QProcess(self)
        self.prepare_proc.setProgram(str(Path(__import__("sys").executable).with_name("python.exe")) if __import__("os").name == "nt" else __import__("sys").executable)
        self.prepare_proc.setArguments([str(script), "--manifest", str(manifest), "--project-name", project_name])
        self.prepare_proc.finished.connect(self.preparer_finished)
        self.prepare_proc.start()
        self.detect_status.setText("DaVinci：正在建立新项目并导入已质检视频…")

    def preparer_finished(self):
        raw = bytes(self.prepare_proc.readAllStandardOutput()).decode("utf-8", "replace").strip() if self.prepare_proc else ""
        err = bytes(self.prepare_proc.readAllStandardError()).decode("utf-8", "replace").strip() if self.prepare_proc else ""
        try:
            data = json.loads(raw.splitlines()[-1]) if raw else {}
        except Exception:
            data = {}
        if data.get("ok"):
            ids = [int(x) for x in data.get("video_ids", []) if int(x)]
            if ids:
                repo.set_video_edit_status(ids, "已导入DaVinci")
            group_count = len(data.get("groups") or [])
            folder_settings = data.get("settings") or {}
            missing = [k for k in ("folder_project_media", "folder_proxy", "folder_cache", "folder_gallery") if not folder_settings.get(k)]
            extra = ""
            if missing:
                extra = "；部分工作文件夹键未被当前 Resolve 脚本 API 接受，请在项目设置里核对一次"
            self.detect_status.setText(
                f'DaVinci：✅ {data.get("project","新项目")} / {data.get("timeline","FlowStudio_Master")} · '
                f'{data.get("imported_segments",0)} 个片段 · {group_count} 个主播分组 · 1080×1920 / 24fps{extra}'
            )
            # User requested Resolve to stay in the background after automatic setup.
            QTimer.singleShot(1000, self.minimize_resolve)
            self.reload()
        else:
            reason = data.get("error") or err or "无法完成 DaVinci 项目准备"
            self.detect_status.setText("DaVinci：⚠ " + reason[:220])

    def minimize_resolve(self):
        ok, msg = davinci_workflow.minimize_resolve()
        if ok:
            self.detect_status.setText(self.detect_status.text().split(" · 后台")[0] + " · 后台已最小化")
        elif msg:
            QMessageBox.information(
                self, "最小化 DaVinci",
                "自动最小化需要 macOS“辅助功能”权限。\n\n系统设置 → 隐私与安全性 → 辅助功能，允许 Flow Studio/Python 控制界面。\n\n" + msg[:180]
            )

    def run_resolve_script(self, filename, title):
        if os.name != "posix":
            QMessageBox.information(self, title, "当前脚本自动点击功能针对 macOS。")
            return
        # Bring Resolve to front because these existing Lua scripts contain their own dialogs/confirmation UI.
        try:
            davinci_workflow.launch_resolve()
        except Exception as exc:
            QMessageBox.warning(self, title, str(exc))
            return
        script = Path(__file__).resolve().parents[2] / "scripts" / "davinci_run_menu.py"
        self.menu_proc = QProcess(self)
        self.menu_proc.setProgram(str(Path(__import__("sys").executable).with_name("python.exe")) if __import__("os").name == "nt" else __import__("sys").executable)
        self.menu_proc.setArguments([str(script), "--script-name", filename])
        self.pending_script_title = title
        self.menu_proc.finished.connect(self.resolve_script_finished)
        QTimer.singleShot(700, self.menu_proc.start)
        self.detect_status.setText(f"DaVinci：正在启动“{title}”…")

    def resolve_script_finished(self):
        raw = bytes(self.menu_proc.readAllStandardOutput()).decode("utf-8", "replace").strip() if self.menu_proc else ""
        err = bytes(self.menu_proc.readAllStandardError()).decode("utf-8", "replace").strip() if self.menu_proc else ""
        try:
            data = json.loads(raw.splitlines()[-1]) if raw else {}
        except Exception:
            data = {}
        if data.get("ok"):
            self.detect_status.setText(f"DaVinci：✅ 已调用“{self.pending_script_title}”")
        else:
            QMessageBox.warning(
                self, self.pending_script_title or "DaVinci 脚本",
                "没有在 Workspace/工作区 → Scripts/脚本 菜单中找到或点击该脚本。\n\n"
                "请确认脚本仍在 DaVinci 的脚本列表里，并给 Flow Studio/Python macOS 辅助功能权限。\n\n" +
                (data.get("output") or err or raw or "未知错误")[:500]
            )

    def reload(self, cached_rows=None):
        root=repo.get_setting('edit_root_path','')
        if hasattr(self,'edit_root_label'): self.edit_root_label.setText(root or '')
        rows=cached_rows if isinstance(cached_rows,list) else list(repo.list_edit_queue(work_date=work_dates.active()))
        self._edit_rows=rows
        self._queue_signature=(work_dates.active(),repr(rows))
        if self._selected_host and not any((r['recipient_id'],r['host_id'])==self._selected_host for r in rows):
            self._selected_host=None;self.details.setChecked(False);self.details.setEnabled(False);self.details.setText('请先选择主播查看任务明细')
        if self.details.isChecked():self.show_host_details(True)
        counts=repo.editing_stats(rows)
        waiting=[r for r in rows if r['editing_stage']=='WAITING_MATERIAL']
        ready=[r for r in rows if r['editing_stage']=='READY_TO_EDIT']
        editing=[r for r in rows if r['editing_stage']=='EDITING']
        review=[r for r in rows if r['editing_stage']=='REVIEW']
        exporting=[r for r in rows if r['editing_stage']=='EXPORTING']
        done=[r for r in rows if r['editing_stage']=='COMPLETED']
        self.metric_ready.setText(str(counts['READY_TO_EDIT'])); self.metric_error.setText(str(counts['ERROR']))
        self.metric_wait.setText(str(len(waiting))); self.metric_edit.setText(str(len(editing))); self.metric_review.setText(str(len(review))); self.metric_export.setText(str(len(exporting))); self.metric_done.setText(str(len(done))); self.review_badge.setText(f'{len(review)} 个视频')
        if editing:
            names=[]
            for r in editing:
                key=f"{r['recipient_name']} · {r['host_name']}"
                if key not in names:names.append(key)
            self.current_batch_title.setText(f"当前剪辑批次 · {len(editing)} 个完整视频")
            self.current_batch_meta.setText(' / '.join(names[:6]) + (' …' if len(names)>6 else ''))
            self.current_progress.setRange(0,0); self.current_stage.setText('正在剪辑 · 等待 DaVinci 回传完成状态'); self.execution_status.setText('剪辑中');self.detect_status.setText('DaVinci：自动剪辑阶段')
        else:
            self.current_batch_title.setText('暂无正在执行的剪辑批次');self.current_batch_meta.setText('质检通过并素材齐全后，将自动进入后续剪辑批次。');self.current_progress.setRange(0,100); self.current_progress.setValue(0); self.execution_status.setText('等待任务'); self.current_stage.setText('等待可剪辑素材')
        # upcoming batch cards
        while self.batch_list.count():
            item=self.batch_list.takeAt(0);w=item.widget();
            if w:w.hide();w.deleteLater()
        if not ready:self.batch_list.addWidget(QLabel('暂无待剪辑任务',objectName='muted'))
        chunks=[ready[i:i+24] for i in range(0,len(ready),24)]
        for i,ch in enumerate(chunks[:5],1):
            rec=len({r['recipient_name'] for r in ch});hosts=len({(r['recipient_name'],r['host_name']) for r in ch});card=QFrame(objectName='queueCard');cr=QHBoxLayout(card);cr.setContentsMargins(12,9,12,9);cr.addWidget(QLabel(f'待剪辑组 {i:02d}',objectName='cardTitle'));cr.addWidget(QLabel(f'{rec} 接收人 · {hosts} 主播 · {len(ch)} 完整视频 · '+ ' / '.join(dict.fromkeys(str(r['host_name']) for r in ch)),objectName='cardMeta'),1);cr.addWidget(QLabel('等待剪辑',objectName='statusInfo'));self.batch_list.addWidget(card)
        while self.review_list.count():
            item=self.review_list.takeAt(0); w=item.widget()
            if w: w.hide(); w.deleteLater()
        if review:
            rec=len({r['recipient_name'] for r in review}); hosts=len({(r['recipient_name'],r['host_name']) for r in review}); self.review_title.setText('待人工检查批次'); self.review_meta.setText(f'{rec} 接收人 · {hosts} 主播 · {len(review)} 个完整视频')
            for r in review[:7]:
                rr=QFrame(objectName='reviewRow'); rl=QHBoxLayout(rr); rl.setContentsMargins(8,6,8,6); rl.addWidget(QLabel(str(r['host_name'] or '—'),objectName='cardTitle')); rl.addWidget(QLabel(f"{r['recipient_name']} · 视频 {int(r['video_seq']):02d}",objectName='cardMeta'),1); rl.addWidget(QLabel('待检查',objectName='statusWarn')); self.review_list.addWidget(rr)
        else:
            self.review_title.setText('暂无待检查批次'); self.review_meta.setText('剪辑完成后，整批进入这里。')
        self.render_host_cards()

    def show_host_details(self, checked):
        self.table.setVisible(bool(checked and self._selected_host))
        if not checked or not self._selected_host:return
        rows=[r for r in self._edit_rows if (r['recipient_id'],r['host_id'])==self._selected_host]
        signature=repr(rows)
        if signature==getattr(self,'_details_signature',None):return
        self._details_signature=signature
        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(len(rows))
            for i,row in enumerate(rows):
                segs=int(row['segment_count']);passed=int(row['qc_passed'])
                vals=[row['recipient_name'],row['host_name'],f"{int(row['video_seq']):02d}",segs,row['completed_segments'],passed,'可剪辑' if row['materials_ready'] else f'{passed}/{segs}',row['edit_status'],row['edit_output_path']]
                for j,value in enumerate(vals):
                    item=QTableWidgetItem(str(value))
                    if j==0:item.setData(Qt.UserRole,int(row['video_id']))
                    self.table.setItem(i,j,item)
        finally:self.table.setUpdatesEnabled(True)

    def select_waiting_host(self,key,name):
        self._selected_host=key;self.details.setEnabled(True);self.details.setText(name+' · 任务明细')
        self.details.setChecked(True);self.show_host_details(True)

    def render_host_cards(self, *_):
        from app.services.editing_presentation import host_progress
        from PySide6.QtGui import QImageReader
        groups=host_progress(self._edit_rows)
        signature=(repr([(g['key'],g['host_name'],g['recipient_name'],g['passed'],g['total'],image_cache_key(g['image_path'])) for g in groups]),self.wait_expand.isChecked())
        if signature==self._host_cards_signature:return
        self._host_cards_signature=signature
        while self.wait_row.count():
            item=self.wait_row.takeAt(0);w=item.widget()
            if w:w.hide();w.deleteLater()
        self.wait_count.setText(f'{len(groups)} 位主播')
        self.wait_expand.setText('收起主播' if self.wait_expand.isChecked() else f'展开全部主播 ({len(groups)})')
        for g in (groups if self.wait_expand.isChecked() else groups[:4]):
            card=QPushButton();card.setFixedHeight(130);card.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed);card.setObjectName('compactCard');card.setToolTip('点击查看该主播的完整视频任务')
            card.clicked.connect(lambda _=False,key=g['key'],name=g['host_name']:self.select_waiting_host(key,name))
            layout=QHBoxLayout(card);layout.setContentsMargins(10,8,10,8)
            avatar=QLabel('暂无图片');avatar.setFixedSize(64,80);avatar.setAlignment(Qt.AlignCenter);avatar.setAttribute(Qt.WA_TransparentForMouseEvents)
            path=str(g['image_path'] or '')
            set_image(avatar, path)
            layout.addWidget(avatar);info=QVBoxLayout();layout.addLayout(info,1)
            for text,name in [(g['host_name'],'cardTitle'),(g['recipient_name'],'cardMeta'),(f"{g['passed']} / {g['total']} 完整视频质检通过",'statusInfo')]:
                label=QLabel(text,objectName=name);label.setWordWrap(True);label.setAttribute(Qt.WA_TransparentForMouseEvents);info.addWidget(label)
            self.wait_row.addWidget(card)
        if not groups:self.wait_row.addWidget(QLabel('暂无待齐素材',objectName='muted'))


class _DeliveryRecipientCard(QFrame):
    clicked=Signal()

    def __init__(self):
        super().__init__(objectName='deliveryRecipientCard')
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self._pressed=False

    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton:
            self._pressed=True; self.setFocus(); event.accept()
        else: super().mousePressEvent(event)

    def mouseReleaseEvent(self,event):
        if event.button()==Qt.LeftButton:
            activate=self._pressed and self.rect().contains(event.position().toPoint())
            self._pressed=False; event.accept()
            if activate: self.clicked.emit()
        else: super().mouseReleaseEvent(event)

    def keyPressEvent(self,event):
        if event.key() in (Qt.Key_Return,Qt.Key_Enter,Qt.Key_Space):
            if not event.isAutoRepeat(): self.clicked.emit()
            event.accept()
        else: super().keyPressEvent(event)


class UploadSharePage(BaseWorkflowPage):
    def __init__(self, parent=None):
        super().__init__(
            '成品管理中心',
            '集中管理导出成品、上传状态与交付操作，让每一份视频都顺利送达。',
            parent
        )
        self.bridge=get_bridge(); self.drive_executor=ThreadPoolExecutor(max_workers=1); self._local_drive_events=[]; self._drive_future=None
        self._selected_recipient=''
        self._delivery_filter='全部'
        self._delivery_groups={}
        self._filter_buttons={}

        # Six KPI cards mirror the supplied reference without introducing glass effects.
        metrics=QHBoxLayout(); metrics.setSpacing(9)
        def mcard(symbol,title,tone='info'):
            frame=QFrame(objectName='deliveryMetric'); frame.setProperty('tone',tone)
            row=QHBoxLayout(frame); row.setContentsMargins(12,10,12,10); row.setSpacing(10)
            icon=QLabel(symbol,objectName='deliveryMetricIcon'); icon.setProperty('tone',tone); icon.setAlignment(Qt.AlignCenter); row.addWidget(icon)
            texts=QVBoxLayout(); texts.setSpacing(0)
            value=QLabel('0',objectName='deliveryMetricValue'); value.setProperty('tone',tone)
            label=QLabel(title,objectName='deliveryMetricLabel')
            texts.addWidget(value); texts.addWidget(label); row.addLayout(texts,1)
            metrics.addWidget(frame,1)
            return value
        self.metric_exported=mcard('▶','今日成品','info')
        self.metric_uploading=mcard('◷','待上传','warn')
        self.metric_syncing=mcard('⇧','上传中','info')
        self.metric_ready=mcard('✓','待确认','warn')
        self.metric_delivered=mcard('●','已交付','good')
        self.metric_abnormal=mcard('!','异常','bad')
        self.root.addLayout(metrics)

        # Status tabs + search/actions.
        tools=QHBoxLayout(); tools.setSpacing(8)
        for key in ('全部','待上传','上传中','待确认','已交付','异常'):
            btn=QPushButton(key,objectName='deliveryFilterBtn'); btn.setCheckable(True); btn.setChecked(key=='全部')
            btn.clicked.connect(lambda _=False,k=key:self.set_delivery_filter(k))
            self._filter_buttons[key]=btn; tools.addWidget(btn)
        tools.addStretch(1)
        self.delivery_search=QLineEdit(); self.delivery_search.setObjectName('deliverySearch'); self.delivery_search.setPlaceholderText('搜索接收人 / AI 主播…'); self.delivery_search.setMinimumWidth(220); self.delivery_search.textChanged.connect(self.reload); tools.addWidget(self.delivery_search)
        copyall=QPushButton('复制全部链接',objectName='deliveryIconButton'); copyall.clicked.connect(self.copy_recipient_links); tools.addWidget(copyall)
        refresh=QPushButton('刷新',objectName='deliveryIconButton'); refresh.clicked.connect(self.reload); tools.addWidget(refresh)
        self.upload_all_btn=QPushButton('▷  继续全部上传 (0)',objectName='deliveryPrimaryBtn'); self.upload_all_btn.clicked.connect(self.start_drive_archive); tools.addWidget(self.upload_all_btn)
        self.root.addLayout(tools)

        # Main workspace: recipient list on the left, focused recipient details on the right.
        body=QSplitter(Qt.Horizontal); body.setObjectName('deliverySplitter'); body.setChildrenCollapsible(False); body.setHandleWidth(8)
        queue=QFrame(objectName='deliveryListPanel')
        qv=QVBoxLayout(queue); qv.setContentsMargins(13,12,13,12); qv.setSpacing(9)
        qh=QHBoxLayout(); qh.addWidget(QLabel('接收人列表',objectName='deliveryPanelTitle')); qh.addStretch(1)
        self.queue_summary=QLabel('0 个接收人',objectName='deliverySortLabel'); qh.addWidget(self.queue_summary); qh.addWidget(QLabel('按创建时间 ↓',objectName='deliverySortLabel')); qv.addLayout(qh)
        self.delivery_scroll=QScrollArea(objectName='cardScroll'); self.delivery_scroll.setWidgetResizable(True); self.delivery_scroll.setFrameShape(QFrame.NoFrame)
        self.delivery_content=QWidget(objectName='deliveryListContent'); self.delivery_layout=QVBoxLayout(self.delivery_content); self.delivery_layout.setContentsMargins(0,0,0,0); self.delivery_layout.setSpacing(9); self.delivery_layout.setAlignment(Qt.AlignTop)
        self.delivery_scroll.setWidget(self.delivery_content); qv.addWidget(self.delivery_scroll,1); body.addWidget(queue)

        detail=QFrame(objectName='deliveryDetailPanel')
        dv=QVBoxLayout(detail); dv.setContentsMargins(0,0,0,0); dv.setSpacing(0)
        self.detail_scroll=QScrollArea(objectName='deliveryDetailScroll'); self.detail_scroll.setWidgetResizable(True); self.detail_scroll.setFrameShape(QFrame.NoFrame)
        self.detail_content=QWidget(objectName='deliveryDetailContent'); self.detail_layout=QVBoxLayout(self.detail_content); self.detail_layout.setContentsMargins(14,13,14,13); self.detail_layout.setSpacing(10); self.detail_layout.setAlignment(Qt.AlignTop)
        self.detail_scroll.setWidget(self.detail_content); dv.addWidget(self.detail_scroll); body.addWidget(detail)
        body.setSizes([560,610]); body.setMinimumHeight(520); self.root.addWidget(body,1)

        # Kept for compatibility with existing Drive settings/actions. Configuration
        # remains in System Settings; this hidden field prevents behavior changes.
        self.drive_root=QLineEdit(repo.get_setting('drive_root_url','')); self.drive_root.hide()
        self.drive_state=QLabel('Drive：等待'); self.drive_state.hide()
        self.drive_hint=QLabel('桌面版自动同步 · 日期／接收人／AI主播'); self.drive_hint.hide()

        self.table=_make_table(['接收人','AI主播','完整视频','剪辑状态','导出文件','上传状态','上传目标']); self.table.hide(); self.root.addWidget(self.table); self.links=_make_table(['接收人','已上传','完整视频','接收人文件夹链接']); self.links.hide(); self.root.addWidget(self.links)
        self.event_timer=QTimer(self); self.event_timer.timeout.connect(self.process_drive_events); self.event_timer.start(700); self.reload()
        self.auto_archive_timer=QTimer(self); self.auto_archive_timer.timeout.connect(self.auto_archive_ready); self.auto_archive_timer.start(3000)

    def set_delivery_filter(self, key):
        self._delivery_filter=str(key or '全部')
        for name,button in self._filter_buttons.items():
            button.setChecked(name==self._delivery_filter)
        self.reload()

    def select_delivery_recipient(self, name):
        name=str(name or '')
        if name not in self._delivery_groups: return
        self._selected_recipient=name
        for card in self.delivery_content.findChildren(_DeliveryRecipientCard):
            card.setProperty('selected',card.property('recipientName')==name)
            card.style().unpolish(card); card.style().polish(card); card.update()
        self._render_delivery_detail(name,self._delivery_groups[name])
        self.detail_scroll.verticalScrollBar().setValue(0)

    @staticmethod
    def _delivery_bucket(row):
        status=str(row['upload_status'] or '未上传')
        if '失败' in status:
            return '异常'
        if status=='已交付':
            return '已交付'
        if status=='已上传':
            return '待确认'
        if status in ('已交给Drive同步','上传中','同步中'):
            return '上传中'
        return '待上传'

    @staticmethod
    def _delivery_exported(row):
        return str(row['edit_status'] or '') in ('已导出','已完成') or bool(str(row['edit_output_path'] or '').strip())

    def _clear_delivery_layout(self, layout):
        while layout.count():
            item=layout.takeAt(0)
            widget=item.widget()
            child=item.layout()
            if widget:
                widget.hide(); widget.deleteLater()
            elif child:
                self._clear_delivery_layout(child)

    def _group_delivery_stats(self, data):
        rows=list(data.get('rows') or [])
        total=len(rows)
        uploaded=sum(1 for r in rows if str(r['upload_status'] or '') in ('已上传','已交付'))
        syncing=sum(1 for r in rows if self._delivery_bucket(r)=='上传中')
        failed=sum(1 for r in rows if self._delivery_bucket(r)=='异常')
        delivered=sum(1 for r in rows if self._delivery_bucket(r)=='已交付')
        return {'total':total,'uploaded':uploaded,'syncing':syncing,'failed':failed,'delivered':delivered,'pending':max(0,total-uploaded-syncing-failed)}

    def _host_delivery_stats(self, rows):
        hosts={}
        for row in rows:
            name=str(row['host_name'] or '未命名主播')
            data=hosts.setdefault(name,{'total':0,'uploaded':0,'syncing':0,'failed':0,'delivered':0})
            data['total']+=1
            bucket=self._delivery_bucket(row)
            if bucket in ('待确认','已交付'): data['uploaded']+=1
            if bucket=='上传中': data['syncing']+=1
            if bucket=='异常': data['failed']+=1
            if bucket=='已交付': data['delivered']+=1
        return hosts

    def _open_recipient_target(self, rows):
        for row in rows:
            target=str(row['upload_target'] or '').strip()
            if target:
                path=Path(target).expanduser()
                return _open_path_or_url(str(path.parent if path.suffix else path))
        return False

    def auto_archive_ready(self):
        # This page is constructed at startup; uploads continue while editing is visible.
        if self._drive_future and not self._drive_future.done():return
        if self._drive_future:
            try:self._drive_future.result()
            except Exception as exc:
                self.drive_state.setText('Drive：'+str(exc)[:160])
            self._drive_future=None
        try:
            resolve_finish.sync()
            ok,reason=drive_delivery.configured()
            if not ok:
                self.drive_hint.setText(reason)
                return
            day=work_dates.active()
            rows=drive_delivery.pending_rows(day,retry_failed=False)
            if not rows:return
            self.reload()
            self.drive_state.setText(f'Drive：自动上传 {len(rows)} 个已导出成品')
            self._drive_future=self.drive_executor.submit(drive_delivery.upload_pending,
                lambda event:self._local_drive_events.append(dict(event or {})),work_date=day,retry_failed=False)
        except Exception as exc:
            self.drive_hint.setText('自动归档待处理：'+str(exc)[:140])

    def check_drive_sync(self):
        if self._drive_future and not self._drive_future.done():
            QMessageBox.information(self,'系统自检','正在复制成品，请等待完成后自检。');return
        def check():
            try:self._local_drive_events.append({'type':'drive_check_result','result':drive_delivery.self_check(work_dates.active())})
            except Exception as exc:self._local_drive_events.append({'type':'drive_failed','error':str(exc)})
        self._drive_future=self.drive_executor.submit(check)

    def resubmit_drive_sync(self):
        if self._drive_future and not self._drive_future.done():
            QMessageBox.information(self,'重新提交同步','当前复制或自检尚未完成。');return
        if QMessageBox.question(self,'重新提交同步','将所选日期的已导出成品重新复制到当前Drive同步目录，包括已提交的文件。同名不同内容不会覆盖。本地原件保留。继续？')!=QMessageBox.Yes:return
        self._drive_future=self.drive_executor.submit(drive_delivery.upload_pending,
            lambda e:self._local_drive_events.append(dict(e)),work_date=work_dates.active(),force=True)

    def save_drive_link(self):
        url = self.drive_root.text().strip()
        if url and "drive.google.com" not in url:
            QMessageBox.warning(self, "Google Drive", "请填写 Google Drive 文件夹链接。")
            return False
        repo.set_setting("drive_root_url", url)
        self.drive_state.setText("Drive 自动归档：根目录链接已保存")
        return True

    def start_drive_archive(self):
        ok, reason = drive_delivery.configured()
        if not ok:
            QMessageBox.information(
                self, "Google Drive 自动上传",
                reason + "\n\n请登录Google Drive桌面版，或在系统设置选择同步文件夹。"
            )
            return
        rows = [r for r in repo.build_drive_archive_rows(work_date=work_dates.active())
                if Path(str(r["edit_output_path"] or "")).is_file()
                and str(r["upload_status"] or "未上传") != "已上传"]
        if not rows:
            QMessageBox.information(self, "自动归档", "没有待上传的本地成品。已经上传成功的成品不会重复上传。")
            return
        if self._drive_future and not self._drive_future.done():
            QMessageBox.information(self, "自动归档", "Google Drive 自动上传正在运行。")
            return
        self.drive_state.setText(f"Drive 自动归档：开始上传 {len(rows)} 个成品…")
        def event(evt):
            self._local_drive_events.append(dict(evt or {}))
        self._drive_future = self.drive_executor.submit(drive_delivery.upload_pending, event, work_date=work_dates.active())

    def process_drive_events(self):
        changed = False
        events = list(self._local_drive_events)
        self._local_drive_events.clear()
        # Keep bridge events compatible with future/browser Drive executors, but V0.13.3's
        # functional path is the local rclone uploader above.
        events.extend(self.bridge.pop_drive_events())
        for e in events:
            et = str(e.get("type") or "")
            if et == 'drive_check_result':
                result=e['result'];lines=['当前目标：'+result['root'],result['cloud']]
                for row in result['rows']:lines.append(str(row['video_id'])+'：'+row['status']+'\n'+row['destination'])
                dialog=QMessageBox(self);dialog.setWindowTitle('同步系统自检');dialog.setText('检查完成：'+str(len(result['rows']))+' 个成品。云端完成状态未确认。');dialog.setDetailedText('\n\n'.join(lines));dialog.exec()
            elif et == "drive_started":
                self.drive_state.setText("Drive 自动归档：已连接网盘，正在创建目录…")
            elif et == "drive_folder_created":
                self.drive_state.setText("Drive 自动归档：正在创建 " + str(e.get("path") or ""))
            elif et == "drive_upload_progress":
                done = int(e.get("done") or 0); total = int(e.get("total") or 0)
                self.drive_state.setText(f"Drive 自动归档：正在同步成品 {done}/{total}")
            elif et == "drive_recipient_ready":
                rid = int(e.get("recipient_id") or 0)
                url = str(e.get("url") or "")
                if rid and url:
                    repo.set_recipient_drive_folder(rid, url)
                    changed = True
            elif et == "drive_file_uploaded":
                vid = int(e.get("video_id") or 0)
                if vid and e.get("status")!=drive_delivery.SYNCED:
                    repo.set_video_drive_result(vid, str(e.get("file_url") or ""), str(e.get("folder_url") or ""), str(e.get("status") or "已上传"))
                changed = True
            elif et == "drive_finished":
                self.drive_state.setText(f'Drive 同步目录：已复制 {int(e.get("uploaded") or 0)} 个，失败 {int(e.get("failed") or 0)} 个')
                self.bridge.clear_drive_jobs()
                changed = True
            elif et == "drive_failed":
                self.drive_state.setText("Drive 自动归档：❌ " + str(e.get("error") or "失败")[:180])
                self.bridge.clear_drive_jobs()
        if changed:
            self.reload()

    def copy_recipient_links(self):
        links=[r for r in repo.list_recipient_drive_links(work_date=work_dates.active()) if str(r['drive_folder_url'] or '').strip()]
        if not links:
            QMessageBox.information(self,'Google Drive','目前还没有可复制的接收人文件夹链接。');return
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText('\n'.join(f"{r['recipient_name']}：{r['drive_folder_url']}" for r in links));self.drive_state.setText(f'Drive：已复制 {len(links)} 个接收人链接')

    def copy_one_link(self, url):
        from PySide6.QtWidgets import QApplication
        if not str(url or '').strip():
            QMessageBox.information(self,'交付链接','当前接收人还没有 Drive 文件夹链接。');return
        QApplication.clipboard().setText(str(url));self.drive_state.setText('Drive：交付链接已复制')

    def mark_recipient_delivered_ui(self, recipient_id):
        n=repo.mark_recipient_delivered(recipient_id);self.drive_state.setText(f'已标记交付 {n} 个成品');self.reload()

    def manual_confirm_uploaded_ui(self, recipient_name, video_ids):
        ids=[int(x) for x in video_ids if int(x)>0]
        if not ids:
            return
        text=(f"确认【{recipient_name}】这 {len(ids)} 个成品已经成功上传到 Google Drive？\n\n"
              "确认后会标记为“已上传（手动确认）”，自动上传/重试会跳过这些成品。\n"
              "不会删除本地文件，也不会修改质检、自动剪辑或 DaVinci 数据。")
        if QMessageBox.question(self,'手动确认上传成功',text,QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:
            return
        n=repo.manual_confirm_video_uploads(ids)
        link=next((str(r['drive_folder_url'] or '') for r in repo.list_recipient_drive_links(work_date=work_dates.active()) if str(r['recipient_name'] or '')==str(recipient_name)), '')
        suffix='' if link.strip() else '；分享链接未获取'
        self.drive_state.setText(f'已手动确认上传成功 {n} 个成品{suffix}')
        self.reload()

    def cancel_manual_uploaded_ui(self, recipient_name, video_ids):
        ids=[int(x) for x in video_ids if int(x)>0]
        if not ids:
            return
        text=(f"取消【{recipient_name}】这 {len(ids)} 个成品的手动上传确认？\n\n"
              "取消后这些成品会重新进入待上传状态，本地文件和其他流程数据不会被修改。")
        if QMessageBox.question(self,'取消手动确认',text,QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:
            return
        n=repo.cancel_manual_video_uploads(ids)
        self.drive_state.setText(f'已取消 {n} 个成品的手动上传确认，可重新自动上传')
        self.reload()

    def open_recipient_link(self, row, _col):
        item = self.links.item(row, 3)
        if item and item.text().strip():
            _open_path_or_url(item.text().strip())

    def _make_delivery_recipient_card(self, name, data):
        rows=list(data.get('rows') or [])
        stats=self._group_delivery_stats(data)
        hosts=self._host_delivery_stats(rows)
        hist_total=int(data.get('hist_total') or 0)
        total=stats['total'] or hist_total
        completed=stats['uploaded'] if rows else total
        pct=int(round((completed/total)*100)) if total else 0
        selected=(name==self._selected_recipient)

        card=_DeliveryRecipientCard(); card.setProperty('selected',selected); card.setProperty('recipientName',name)
        card.setAccessibleName(name or '未命名接收人')
        card.clicked.connect(lambda n=name:self.select_delivery_recipient(n))
        box=QVBoxLayout(card); box.setContentsMargins(12,11,12,10); box.setSpacing(8)

        head=QHBoxLayout(); head.setSpacing(9)
        avatar=QLabel((name or '?')[:1],objectName='deliveryRecipientAvatar'); avatar.setAlignment(Qt.AlignCenter); head.addWidget(avatar)
        names=QVBoxLayout(); names.setSpacing(2)
        names.addWidget(QLabel(name or '未命名接收人',objectName='deliveryRecipientName'))
        names.addWidget(QLabel(f'{len(hosts) if rows else "历史"} 主播 · 共 {total} 成品',objectName='deliveryRecipientMeta'))
        head.addLayout(names,1)
        count=QLabel(f'{completed} / {total}',objectName='deliveryCountStrong'); head.addWidget(count)
        more=QPushButton('•••',objectName='deliveryMoreBtn'); more.setToolTip('查看接收人详情与操作'); more.clicked.connect(lambda _=False,n=name:self.select_delivery_recipient(n)); head.addWidget(more)
        box.addLayout(head)

        prog=QHBoxLayout(); prog.setSpacing(8)
        bar=QProgressBar(objectName='deliveryCardProgress'); bar.setRange(0,100); bar.setValue(pct); bar.setTextVisible(False); prog.addWidget(bar,1)
        prog.addWidget(QLabel(f'{pct}%',objectName='deliveryPct'))
        box.addLayout(prog)

        if hosts:
            host_row=QHBoxLayout(); host_row.setSpacing(6)
            for host_name,h in list(hosts.items())[:3]:
                hpct=int(round((h['uploaded']/h['total'])*100)) if h['total'] else 0
                tone='good' if h['uploaded']==h['total'] and h['total'] else ('bad' if h['failed'] else ('info' if h['syncing'] else 'warn'))
                symbol='✓' if tone=='good' else ('!' if tone=='bad' else ('⇧' if tone=='info' else '◷'))
                pill=QFrame(objectName='deliveryHostPill'); pill.setProperty('tone',tone)
                ph=QHBoxLayout(pill); ph.setContentsMargins(7,5,7,5); ph.setSpacing(5)
                icon=QLabel(symbol,objectName='deliveryHostIcon'); icon.setProperty('tone',tone); ph.addWidget(icon)
                txt=QVBoxLayout(); txt.setSpacing(0); txt.addWidget(QLabel(host_name,objectName='deliveryHostName')); txt.addWidget(QLabel(f'{h["uploaded"]} / {h["total"]} · {hpct}%',objectName='deliveryHostMeta')); ph.addLayout(txt,1)
                host_row.addWidget(pill,1)
            host_row.addStretch(1)
            box.addLayout(host_row)

        foot=QHBoxLayout(); foot.setSpacing(8)
        if stats['failed']:
            warning=QLabel(f'!  有 {stats["failed"]} 个成品上传异常',objectName='deliveryWarning'); foot.addWidget(warning)
        elif stats['pending']:
            warning=QLabel(f'!  还有 {stats["pending"]} 个文件未上传',objectName='deliveryWarning'); foot.addWidget(warning)
        elif stats['syncing']:
            foot.addWidget(QLabel(f'⇧  {stats["syncing"]} 个文件正在同步',objectName='deliveryInfoText'))
        elif rows and stats['uploaded']==stats['total']:
            foot.addWidget(QLabel('✓  文件已上传，可确认交付',objectName='deliveryGoodText'))
        else:
            foot.addWidget(QLabel('历史交付记录',objectName='deliveryGoodText'))
        foot.addStretch(1)
        view=QPushButton('查看详情  ›',objectName='deliveryLinkButton'); view.clicked.connect(lambda _=False,n=name:self.select_delivery_recipient(n)); foot.addWidget(view)
        box.addLayout(foot)
        # Decorative children let the whole card receive clicks; action buttons keep theirs.
        for child in card.findChildren(QWidget):
            if isinstance(child,(QLabel,QProgressBar)) or child.objectName()=='deliveryHostPill':
                child.setAttribute(Qt.WA_TransparentForMouseEvents,True)
        return card

    def _render_delivery_detail(self, name, data):
        self._clear_delivery_layout(self.detail_layout)
        if not name or not data:
            empty=QFrame(objectName='deliveryEmptyDetail'); ev=QVBoxLayout(empty); ev.setContentsMargins(30,80,30,80)
            t=QLabel('选择一个接收人查看详情',objectName='deliveryPanelTitle'); t.setAlignment(Qt.AlignCenter); ev.addWidget(t)
            h=QLabel('上传进度、Google Drive 状态与交付操作会显示在这里。',objectName='muted'); h.setAlignment(Qt.AlignCenter); h.setWordWrap(True); ev.addWidget(h)
            self.detail_layout.addWidget(empty); self.detail_layout.addStretch(1); return

        rows=list(data.get('rows') or [])
        stats=self._group_delivery_stats(data)
        hosts=self._host_delivery_stats(rows)
        total=stats['total'] or int(data.get('hist_total') or 0)
        completed=stats['uploaded'] if rows else total
        pct=int(round((completed/total)*100)) if total else 0
        link=str(data.get('link') or '')
        rid=int(data.get('rid') or 0)

        header=QHBoxLayout(); header.setSpacing(10)
        avatar=QLabel((name or '?')[:1],objectName='deliveryDetailAvatar'); avatar.setAlignment(Qt.AlignCenter); header.addWidget(avatar)
        info=QVBoxLayout(); info.setSpacing(2); info.addWidget(QLabel(name,objectName='deliveryDetailName'))
        info.addWidget(QLabel(f'{len(hosts) if rows else "历史"} 个 AI 主播 · {total} 个成品',objectName='deliveryRecipientMeta')); header.addLayout(info,1)
        if stats['failed']: status_text,status_tone='异常','bad'
        elif rows and stats['delivered']==stats['total'] and stats['total']: status_text,status_tone='已交付','good'
        elif rows and stats['uploaded']==stats['total'] and stats['total']: status_text,status_tone='待确认','warn'
        elif stats['syncing']: status_text,status_tone='上传中','info'
        else: status_text,status_tone='处理中','info'
        badge=QLabel(status_text,objectName='deliveryStatusBadge'); badge.setProperty('tone',status_tone); badge.setAlignment(Qt.AlignCenter); header.addWidget(badge)
        self.detail_layout.addLayout(header)

        progress_card=QFrame(objectName='deliveryProgressCard'); pv=QVBoxLayout(progress_card); pv.setContentsMargins(11,10,11,10); pv.setSpacing(7)
        prh=QHBoxLayout(); prh.addWidget(QLabel('总体进度',objectName='deliverySubTitle')); prh.addStretch(1); prh.addWidget(QLabel(f'{completed} / {total}',objectName='deliveryCountStrong')); prh.addWidget(QLabel(f'{pct}%',objectName='deliveryPct')); pv.addLayout(prh)
        bar=QProgressBar(objectName='deliveryOverallProgress'); bar.setRange(0,100); bar.setValue(pct); bar.setTextVisible(False); pv.addWidget(bar)
        self.detail_layout.addWidget(progress_card)

        if hosts:
            host_grid=QGridLayout(); host_grid.setHorizontalSpacing(8); host_grid.setVerticalSpacing(8)
            for i,(host_name,h) in enumerate(hosts.items()):
                hpct=int(round((h['uploaded']/h['total'])*100)) if h['total'] else 0
                tone='good' if h['uploaded']==h['total'] and h['total'] else ('bad' if h['failed'] else ('info' if h['syncing'] else 'warn'))
                symbol='✓' if tone=='good' else ('!' if tone=='bad' else ('⇧' if tone=='info' else '◷'))
                tile=QFrame(objectName='deliveryHostTile'); tile.setProperty('tone',tone); tv=QHBoxLayout(tile); tv.setContentsMargins(9,7,9,7); tv.setSpacing(7)
                ic=QLabel(symbol,objectName='deliveryHostTileIcon'); ic.setProperty('tone',tone); ic.setAlignment(Qt.AlignCenter); tv.addWidget(ic)
                tx=QVBoxLayout(); tx.setSpacing(0); tx.addWidget(QLabel(host_name,objectName='deliveryHostName')); tx.addWidget(QLabel(f'{h["uploaded"]} / {h["total"]}   {hpct}%',objectName='deliveryHostMeta')); tv.addLayout(tx,1)
                host_grid.addWidget(tile,i//3,i%3)
            self.detail_layout.addLayout(host_grid)

        lower=QHBoxLayout(); lower.setSpacing(9)
        drive_card=QFrame(objectName='deliverySubCard'); dc=QVBoxLayout(drive_card); dc.setContentsMargins(11,10,11,10); dc.setSpacing(7)
        dh=QHBoxLayout(); dh.addWidget(QLabel('△',objectName='deliveryDriveIcon')); dh.addWidget(QLabel('Google Drive 上传',objectName='deliverySubTitle')); dh.addStretch(1)
        try: drive_ok,_drive_reason=drive_delivery.configured()
        except Exception: drive_ok=False
        connected=QLabel('● 已连接' if drive_ok else '● 未连接',objectName='deliveryGoodText' if drive_ok else 'deliveryWarning'); dh.addWidget(connected); dc.addLayout(dh)
        target=''
        for row in rows:
            target=str(row['upload_target'] or '').strip()
            if target: break
        if not target: target=f'FlowStudio/{work_dates.active()}/{name}/'
        dc.addWidget(QLabel('目标目录',objectName='deliverySmallLabel'))
        target_label=QLabel(target,objectName='deliveryPathText'); target_label.setWordWrap(True); dc.addWidget(target_label)
        dp=QProgressBar(objectName='deliveryTinyProgress'); dp.setRange(0,100); dp.setValue(pct); dp.setTextVisible(False); dc.addWidget(dp)
        dc.addWidget(QLabel(f'上传状态   {completed} / {total}    {pct}%',objectName='deliveryRecipientMeta'))
        pending=max(0,stats['pending']+stats['failed'])
        upload=QPushButton(f'⇧  继续全部上传 ({pending})',objectName='deliveryPrimaryBtn'); upload.setEnabled(bool(pending)); upload.clicked.connect(self.start_drive_archive); dc.addWidget(upload)
        da=QHBoxLayout(); check=QPushButton('↻  重新检测 Drive',objectName='deliverySmallButton'); check.clicked.connect(self.check_drive_sync); da.addWidget(check)
        open_folder=QPushButton('▣  打开文件夹',objectName='deliverySmallButton'); open_folder.setEnabled(bool(target)); open_folder.clicked.connect(lambda _=False,rs=tuple(rows):self._open_recipient_target(rs)); da.addWidget(open_folder); dc.addLayout(da)
        confirm_ids=[int(x['video_id']) for x in rows if str(x['upload_status'] or '') not in ('已上传','已交付') and self._delivery_exported(x)]
        manual_rows=[x for x in rows if str(x['upload_status'] or '')=='已上传' and str(x['upload_confirm_mode'] or '')=='manual']
        if confirm_ids:
            manual=QPushButton('手动确认上传成功',objectName='deliverySmallButton'); manual.clicked.connect(lambda _=False,n=name,ids=tuple(confirm_ids):self.manual_confirm_uploaded_ui(n,ids)); dc.addWidget(manual)
        if manual_rows:
            undo_ids=tuple(int(x['video_id']) for x in manual_rows)
            undo=QPushButton('取消手动确认',objectName='deliverySmallButton'); undo.clicked.connect(lambda _=False,n=name,ids=undo_ids:self.cancel_manual_uploaded_ui(n,ids)); dc.addWidget(undo)
        lower.addWidget(drive_card,1)

        delivery_card=QFrame(objectName='deliverySubCard'); dl=QVBoxLayout(delivery_card); dl.setContentsMargins(11,10,11,10); dl.setSpacing(7)
        lh=QHBoxLayout(); lh.addWidget(QLabel('↗',objectName='deliveryDriveIcon')); lh.addWidget(QLabel('交付链接',objectName='deliverySubTitle')); lh.addStretch(1)
        copy=QPushButton('复制链接',objectName='deliverySmallButton'); copy.setEnabled(bool(link)); copy.clicked.connect(lambda _=False,u=link:self.copy_one_link(u)); lh.addWidget(copy); dl.addLayout(lh)
        link_edit=QLineEdit(link); link_edit.setReadOnly(True); link_edit.setPlaceholderText('上传完成后生成接收人文件夹链接'); dl.addWidget(link_edit)
        open_drive=QPushButton('↗  打开 Drive',objectName='deliverySmallButton'); open_drive.setEnabled(bool(link)); open_drive.clicked.connect(lambda _=False,u=link:_open_path_or_url(u)); dl.addWidget(open_drive)
        confirm_card=QFrame(objectName='deliveryConfirmCard'); cv=QVBoxLayout(confirm_card); cv.setContentsMargins(10,12,10,12); cv.setSpacing(6)
        ctitle=QLabel('✓  全部文件确认完成后\n即可标记为已交付',objectName='deliveryConfirmText'); ctitle.setAlignment(Qt.AlignCenter); ctitle.setWordWrap(True); cv.addWidget(ctitle)
        done=QPushButton('✓  确认交付',objectName='deliveryGoodButton'); done.setEnabled(bool(rows) and stats['uploaded']==stats['total'] and stats['total']>0 and rid>0); done.clicked.connect(lambda _=False,r=rid:self.mark_recipient_delivered_ui(r)); cv.addWidget(done); dl.addWidget(confirm_card,1)
        lower.addWidget(delivery_card,1)
        self.detail_layout.addLayout(lower)

        actions=QHBoxLayout(); actions.addStretch(1)
        retry=QPushButton('重新提交同步',objectName='deliverySmallButton'); retry.clicked.connect(self.resubmit_drive_sync); actions.addWidget(retry)
        self.detail_layout.addLayout(actions)
        self.detail_layout.addStretch(1)

    def reload(self):
        resolve_finish.sync()
        rows=list(repo.list_upload_queue(work_date=work_dates.active())); self.table.setRowCount(len(rows))
        for i,row in enumerate(rows):
            vals=[row['recipient_name'],row['host_name'],f"{int(row['video_seq']):02d}",row['edit_status'] or '等待片段',row['edit_output_path'] or '',row['upload_status'] or '未上传',row['upload_target'] or '']
            for c,v in enumerate(vals):
                item=QTableWidgetItem(str(v))
                if c==0: item.setData(Qt.UserRole,int(row['video_id']))
                self.table.setItem(i,c,item)
        links=list(repo.list_recipient_drive_links(work_date=work_dates.active())); self.links.setRowCount(len(links))
        for i,r in enumerate(links):
            vals=[r['recipient_name'],int(r['uploaded_count'] or 0),int(r['video_count'] or 0),r['drive_folder_url'] or '']
            for c,v in enumerate(vals): self.links.setItem(i,c,QTableWidgetItem(str(v)))

        # Only exported/syncing/uploaded items are treated as products on this page.
        # Upstream videos that are still being edited remain out of the delivery UI.
        product_rows=[r for r in rows if self._delivery_exported(r) or str(r['upload_status'] or '') not in ('','未上传')]
        counts={key:0 for key in ('待上传','上传中','待确认','已交付','异常')}
        for row in product_rows: counts[self._delivery_bucket(row)]+=1
        exported=len(product_rows)
        self.metric_exported.setText(str(exported)); self.metric_uploading.setText(str(counts['待上传'])); self.metric_syncing.setText(str(counts['上传中']))
        self.metric_ready.setText(str(counts['待确认'])); self.metric_delivered.setText(str(counts['已交付'])); self.metric_abnormal.setText(str(counts['异常']))
        for key,button in self._filter_buttons.items():
            button.setText(f'{key}  {exported if key=="全部" else counts[key]}')
        self.upload_all_btn.setText(f'▷  继续全部上传 ({counts["待上传"]+counts["异常"]})')
        self.upload_all_btn.setEnabled(bool(counts['待上传']+counts['异常']))

        link_by_name={str(r['recipient_name']):r for r in links}
        all_groups={}
        for row in product_rows:
            name=str(row['recipient_name'] or '')
            all_groups.setdefault(name,{'rows':[]})['rows'].append(row)
        for name,lr in link_by_name.items():
            group=all_groups.setdefault(name,{'rows':[]})
            group['rid']=int(lr['recipient_id']) if 'recipient_id' in lr.keys() else 0
            group['link']=str(lr['drive_folder_url'] or '')
            group['hist_total']=int(lr['video_count'] or 0)
            group['hist_uploaded']=int(lr['uploaded_count'] or 0)
        self._delivery_groups=all_groups

        query=self.delivery_search.text().strip().lower() if hasattr(self,'delivery_search') else ''
        visible=[]
        for name,data in all_groups.items():
            haystack=' '.join([name]+[str(r['host_name'] or '') for r in data.get('rows',[])])
            if query and query not in haystack.lower(): continue
            if self._delivery_filter!='全部':
                row_buckets={self._delivery_bucket(r) for r in data.get('rows',[])}
                if not row_buckets and data.get('link'): row_buckets={'已交付'}
                if self._delivery_filter not in row_buckets: continue
            visible.append((name,data))

        # Keep the previous selection if it still exists; otherwise select the first visible card.
        if self._selected_recipient not in all_groups:
            self._selected_recipient=visible[0][0] if visible else ''
        elif visible and self._selected_recipient not in {name for name,_ in visible}:
            self._selected_recipient=visible[0][0]
        elif not visible:
            self._selected_recipient=''

        self._clear_delivery_layout(self.delivery_layout)
        self.queue_summary.setText(f'{len(visible)} / {len(all_groups)}')
        if visible:
            for name,data in visible:
                self.delivery_layout.addWidget(self._make_delivery_recipient_card(name,data))
        else:
            empty=QFrame(objectName='deliveryEmptyList'); ev=QVBoxLayout(empty); ev.setContentsMargins(24,52,24,52)
            title=QLabel('暂无符合条件的成品',objectName='deliveryPanelTitle'); title.setAlignment(Qt.AlignCenter); ev.addWidget(title)
            hint=QLabel('成品导出后会自动出现在这里；也可以切换状态筛选或日期查看历史记录。',objectName='muted'); hint.setWordWrap(True); hint.setAlignment(Qt.AlignCenter); ev.addWidget(hint)
            self.delivery_layout.addWidget(empty)
        self.delivery_layout.addStretch(1)
        self._render_delivery_detail(self._selected_recipient,all_groups.get(self._selected_recipient))



class _MetricCard(QFrame):
    # Compact KPI card used only by the analytics workspace.
    def __init__(self, label, value='—', sub='', parent=None):
        super().__init__(parent)
        self.setObjectName('analyticsMetric')
        lay=QVBoxLayout(self); lay.setContentsMargins(15,12,15,11); lay.setSpacing(3)
        self.label=QLabel(label,objectName='analyticsMetricLabel')
        self.value=QLabel(str(value),objectName='analyticsMetricValue')
        self.sub=QLabel(sub,objectName='analyticsMetricSub'); self.sub.setWordWrap(True)
        lay.addWidget(self.label); lay.addWidget(self.value); lay.addWidget(self.sub)
        self.setMinimumWidth(130); self.setMinimumHeight(98); self.setMaximumHeight(112)
        self.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed)

    def set_data(self,value,sub='',tone='blue'):
        self.value.setText(str(value)); self.sub.setText(str(sub or ''))
        self.value.setProperty('tone',tone)
        self.value.style().unpolish(self.value); self.value.style().polish(self.value)


class _BarChart(QWidget):
    # Dependency-free bar chart with hover details.
    def __init__(self,parent=None):
        super().__init__(parent); self.setObjectName('analyticsChart'); self.labels=[]; self.values=[]; self.details=[]; self._rects=[]
        self.setMinimumHeight(250); self.setMouseTracking(True); self.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed)

    def set_data(self,labels,values,details=None):
        self.labels=list(labels or []); self.values=[float(v or 0) for v in (values or [])]; self.details=list(details or [])
        self.update()

    def paintEvent(self,event):
        super().paintEvent(event); p=QPainter(self); p.setRenderHint(QPainter.Antialiasing,True); self._rects=[]
        if not self.labels:
            p.setPen(self.palette().color(QPalette.WindowText)); p.drawText(self.rect(),Qt.AlignCenter,'暂无统计数据'); return
        r=self.rect().adjusted(46,18,-14,-34); vmax=max([4.0]+self.values)
        muted=self.palette().color(QPalette.WindowText); grid=QColor(muted); grid.setAlpha(55)
        p.setPen(QPen(grid,1))
        for i in range(5):
            y=r.bottom()-r.height()*i/4; p.drawLine(r.left(),int(y),r.right(),int(y))
            p.setPen(QPen(muted,1)); p.drawText(2,int(y)-8,38,16,Qt.AlignRight|Qt.AlignVCenter,str(int(round(vmax*i/4))))
            p.setPen(QPen(grid,1))
        n=max(1,len(self.values)); gap=max(2,min(10,int(r.width()/max(n,1)*0.22))); bw=max(3,(r.width()-gap*(n-1))/n)
        blue=QColor('#2F80ED'); p.setPen(Qt.NoPen)
        for i,val in enumerate(self.values):
            x=r.left()+i*(bw+gap); h=0 if vmax<=0 else r.height()*val/vmax
            rect=QRect(int(x),int(r.bottom()-h),max(2,int(bw)),max(1,int(h)))
            p.setBrush(blue)
            if val>0: p.drawRoundedRect(rect,3,3)
            self._rects.append((rect,i))
        step=max(1,(len(self.labels)+11)//12)
        p.setPen(QPen(muted,1))
        for i,label in enumerate(self.labels):
            if i%step and i!=len(self.labels)-1: continue
            if i>=len(self._rects): break
            rect=self._rects[i][0]; p.drawText(rect.center().x()-27,r.bottom()+7,54,20,Qt.AlignHCenter|Qt.AlignTop,str(label))

        if not any(self.values):
            p.setPen(muted); p.drawText(r,Qt.AlignCenter,'当前时段暂无产出')

    def mouseMoveEvent(self,event):
        for rect,i in self._rects:
            if rect.contains(event.position().toPoint()):
                detail=self.details[i] if i<len(self.details) else f'{self.labels[i]}：{self.values[i]:g}'
                QToolTip.showText(event.globalPosition().toPoint(),str(detail),self); return
        QToolTip.hideText()


class _HorizontalBars(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent); self.setObjectName('analyticsChart'); self.items=[]; self.setMinimumHeight(180); self.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed)
    def set_data(self,items):
        self.items=list(items or []); self.setFixedHeight(max(150,38*max(1,len(self.items))+26)); self.update()
    def paintEvent(self,event):
        super().paintEvent(event); p=QPainter(self); p.setRenderHint(QPainter.Antialiasing,True)
        if not self.items:
            p.setPen(self.palette().color(QPalette.WindowText)); p.drawText(self.rect(),Qt.AlignCenter,'暂无统计数据'); return
        left=128; right=52; top=12; row_h=36; maxv=max([float(x.get('value') or 0) for x in self.items]+[1.0]); text=self.palette().color(QPalette.WindowText); muted=self.palette().color(QPalette.WindowText)
        for i,item in enumerate(self.items):
            y=top+i*row_h; name=str(item.get('name') or ''); val=float(item.get('value') or 0); tone=item.get('tone','blue')
            color={'blue':'#2F80ED','green':'#16B877','orange':'#F1A23A','red':'#E25A63','gray':'#93A0B3'}.get(tone,'#2F80ED')
            p.setPen(QPen(text,1)); p.drawText(0,y,left-8,22,Qt.AlignRight|Qt.AlignVCenter,name)
            bg=QColor(muted); bg.setAlpha(35); p.setBrush(bg); p.setPen(Qt.NoPen); p.drawRoundedRect(left,y+5,max(10,self.width()-left-right),12,6,6)
            w=(self.width()-left-right)*(val/maxv); p.setBrush(QColor(color)); p.drawRoundedRect(left,y+5,max(2,int(w)),12,6,6)
            suffix=str(item.get('display') if item.get('display') is not None else (f'{val:.1f}' if val%1 else int(val)))
            p.setPen(QPen(muted,1)); p.drawText(self.width()-right+6,y,right-6,22,Qt.AlignLeft|Qt.AlignVCenter,suffix)


class _FunnelChart(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent); self.setObjectName('analyticsChart'); self.rows=[]; self.setMinimumHeight(350); self.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed)
    def set_data(self,rows): self.rows=list(rows or []); self.update()
    def paintEvent(self,event):
        super().paintEvent(event); p=QPainter(self); p.setRenderHint(QPainter.Antialiasing,True)
        if not self.rows:
            p.setPen(self.palette().color(QPalette.WindowText)); p.drawText(self.rect(),Qt.AlignCenter,'暂无生产流程数据'); return
        maxn=max([int(r.get('count') or 0) for r in self.rows]+[1]); top=10; h=36; gap=6; cx=self.width()/2
        for i,row in enumerate(self.rows):
            n=int(row.get('count') or 0); ratio=max(.32,n/maxn if maxn else .32); w=min(self.width()-32,max(420,(self.width()-32)*ratio)); x=cx-w/2; y=top+i*(h+gap)
            dark=self.palette().color(QPalette.WindowText).lightness()>128
            color=QColor(('#263A59' if i<4 else '#203E35') if dark else ('#E9F2FF' if i<4 else '#E9F8F2')); p.setPen(QPen(QColor('#D7E4F3'),1)); p.setBrush(color); p.drawRoundedRect(int(x),y,int(w),h,7,7)
            p.setPen(QPen(self.palette().color(QPalette.WindowText),1)); rate=row.get('rate'); rate_txt='—' if rate is None else f'{rate*100:.1f}%'
            sec=row.get('avg_stay_seconds')
            if sec is None: stay='—'
            elif sec<60: stay=f'{int(sec)}秒'
            elif sec<3600: stay=f'{sec/60:.1f}分'
            else: stay=f'{sec/3600:.1f}小时'
            p.drawText(int(x)+12,y,int(w)-24,h,Qt.AlignLeft|Qt.AlignVCenter,f"{i+1}. {row.get('label')}   {n} · {rate_txt} · 流失 {row.get('loss',0)} · {stay}")


class _StatsPanel(QFrame):
    def __init__(self,title,subtitle='',parent=None):
        super().__init__(parent); self.setObjectName('analyticsPanel')
        self.layout_box=QVBoxLayout(self); self.layout_box.setContentsMargins(16,14,16,14); self.layout_box.setSpacing(10)
        head=QHBoxLayout(); title_label=QLabel(title,objectName='analyticsPanelTitle'); head.addWidget(title_label)
        if subtitle:
            sub=QLabel(subtitle,objectName='analyticsHint'); sub.setAlignment(Qt.AlignRight|Qt.AlignVCenter); head.addStretch(1); head.addWidget(sub)
        self.layout_box.addLayout(head)


class StatisticsPage(BaseWorkflowPage):
    # Read-only Analytics Layer. It never invokes production mutation APIs.
    TAB_NAMES=['总览','生产效率','Flow通道','质量分析','API & 系统']
    RANGE_NAMES=['今天','昨天','近7天','近30天']

    def __init__(self,parent=None):
        super().__init__('数据统计中心','生产进度、通道表现与质量趋势，一目了然。',parent)
        self.page_content.setObjectName('analyticsContent'); self.page_content.setMinimumWidth(780); self.root.setSpacing(16); self._last_payload=None

        tools=QHBoxLayout(); tools.setSpacing(8)
        self.date_label=QLabel('',objectName='analyticsDate'); tools.addWidget(self.date_label); tools.addStretch(1)
        self.range=QComboBox(); self.range.addItems(self.RANGE_NAMES); self.range.setCurrentText('今天'); self.range.setMinimumWidth(100); tools.addWidget(self.range); self.range.hide()
        self.refresh_btn=QPushButton('↻  手动刷新'); self.refresh_btn.setObjectName('analyticsRefresh'); self.refresh_btn.clicked.connect(lambda:self.reload(force=True)); tools.addWidget(self.refresh_btn)
        self.last_refresh=QLabel('',objectName='analyticsHint'); tools.addWidget(self.last_refresh)
        self.root.addLayout(tools)

        tab_bar=QFrame(objectName='analyticsTabs'); tab_lay=QHBoxLayout(tab_bar); tab_lay.setContentsMargins(6,5,6,5); tab_lay.setSpacing(4)
        self.tab_buttons=[]
        self.stack=QStackedWidget()
        for i,name in enumerate(self.TAB_NAMES):
            b=QPushButton(name); b.setCheckable(True); b.setObjectName('analyticsTab'); b.clicked.connect(lambda checked=False,n=i:self._select_tab(n)); self.tab_buttons.append(b); tab_lay.addWidget(b)
        tab_lay.addStretch(1); self.root.addWidget(tab_bar); self.root.addWidget(self.stack)

        self._build_overview(); self._build_efficiency(); self._build_flow(); self._build_quality(); self._build_api_system()
        self._select_tab(0)
        self.range.currentTextChanged.connect(lambda *_:self.reload(force=False))

        # Heavy aggregation is hourly. The 10-second Flow refresh reads only current
        # channel runtime rows and never recalculates the analytics database.
        self.stats_timer=QTimer(self); self.stats_timer.setInterval(60*60*1000); self.stats_timer.timeout.connect(lambda:self.reload(force=False) if self.isVisible() else None); self.stats_timer.start()
        self.channel_timer=QTimer(self); self.channel_timer.setInterval(10*1000); self.channel_timer.timeout.connect(self._refresh_channel_runtime); self.channel_timer.start()
        self.reload(force=False)

    def _new_page(self):
        page=QWidget(); lay=QVBoxLayout(page); lay.setContentsMargins(0,4,0,0); lay.setSpacing(16); lay.setAlignment(Qt.AlignTop); self.stack.addWidget(page); return page,lay

    def _metric_grid(self,layout,specs,cols=4):
        frame=QFrame(); grid=QGridLayout(frame); grid.setContentsMargins(0,0,0,0); grid.setSpacing(12); cards={}
        for i,(key,title) in enumerate(specs):
            c=_MetricCard(title); cards[key]=c; grid.addWidget(c,i//cols,i%cols)
        for c in range(cols): grid.setColumnStretch(c,1)
        layout.addWidget(frame); return cards

    def _two_col(self,layout,left,right,ratio=(2,1)):
        # Analytics rows should follow their content height instead of stretching to fill
        # the entire stacked-page viewport.  This keeps overview/detail cards compact.
        holder=QWidget(); holder.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Maximum)
        g=QGridLayout(holder); g.setContentsMargins(0,0,0,0); g.setSpacing(10); g.setAlignment(Qt.AlignTop)
        left.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Maximum); right.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Maximum)
        g.addWidget(left,0,0,Qt.AlignTop); g.addWidget(right,0,1,Qt.AlignTop); g.setColumnStretch(0,ratio[0]); g.setColumnStretch(1,ratio[1]); layout.addWidget(holder); return holder

    def _table(self,headers):
        t=_make_table(headers); t.setEditTriggers(QAbstractItemView.NoEditTriggers); t.setSelectionMode(QAbstractItemView.NoSelection); t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); return t

    def _build_overview(self):
        page,lay=self._new_page();self.overview_page=page
        self.overview_cards=self._metric_grid(lay,[('tasks','当天任务总数'),('completed','当天已完成'),('unfinished','当天未完成'),('rate','当天完成率'),('duration','已完成视频总时长'),('backlog','所有日期累计积压')],3)
        note=QLabel('按工作日期统计完整视频；已导出或已交付算完成。累计积压包含所有日期的未完成视频。',objectName='muted');note.setWordWrap(True);lay.addWidget(note)
        recip=_StatsPanel('每位接收人的任务与完成情况','任务数、完成数和时长属于当前日期；累计积压包含该接收人所有日期。')
        recip.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Maximum);recip.layout_box.setAlignment(Qt.AlignTop)
        self.recipient_table=self._table(['接收人','当天任务','已完成','未完成','完成率','成片总时长','累计积压']);recip.layout_box.addWidget(self.recipient_table);lay.addWidget(recip)
        from app.ui.read_snapshot import SnapshotReader
        from app.core.daily_statistics import snapshot
        self.daily_reader=SnapshotReader(self,snapshot);self.daily_reader.ready.connect(self._daily_ready)
        self.daily_timer=QTimer(self);self.daily_timer.setInterval(30000);self.daily_timer.timeout.connect(lambda:self.daily_reader.request(work_dates.active()) if self.isVisible() else None);self.daily_timer.start()

    def _build_efficiency(self):
        page,lay=self._new_page(); self.efficiency_page=page
        self.eff_cards=self._metric_grid(lay,[('completed','今日完整视频产出'),('speed','完整视频 / 小时'),('avg','平均生产耗时'),('backlog','当前总积压'),('auto','全自动完成率')],5)
        funnel=_StatsPanel('生产漏斗','数量 · 完成率 · 流失 · 平均停留时间'); self.funnel_chart=_FunnelChart(); funnel.layout_box.addWidget(self.funnel_chart)
        top=_StatsPanel('TOP 3 当前生产瓶颈'); self.top_bottlenecks=QVBoxLayout(); top.layout_box.addLayout(self.top_bottlenecks)
        self._two_col(lay,funnel,top,(2,1))
        duration=_StatsPanel('各生产环节平均耗时'); self.duration_chart=_HorizontalBars(); duration.layout_box.addWidget(self.duration_chart); lay.addWidget(duration)

    def _build_flow(self):
        page,lay=self._new_page(); self.flow_page=page
        self.flow_cards=self._metric_grid(lay,[('total','总通道'),('working','工作中'),('idle','空闲'),('abnormal','异常 / 离线'),('util','平均利用率'),('completed','今日完成 Flow 片段')],6)
        channels=_StatsPanel('CH 通道矩阵','状态 · 利用率 · 成功率 · 完成 / 失败 / 重试 · 平均耗时'); self.flow_channel_holder=QWidget(); self.flow_channel_grid=QGridLayout(self.flow_channel_holder); self.flow_channel_grid.setContentsMargins(0,0,0,0); self.flow_channel_grid.setSpacing(8); channels.layout_box.addWidget(self.flow_channel_holder); lay.addWidget(channels)
        util=_StatsPanel('通道利用率'); self.util_chart=_HorizontalBars(); util.layout_box.addWidget(self.util_chart)
        sched=_StatsPanel('调度异常'); self.scheduler_rows=QVBoxLayout(); sched.layout_box.addLayout(self.scheduler_rows)
        self._two_col(lay,util,sched,(1,1))

    def _build_quality(self):
        page,lay=self._new_page(); self.quality_page=page
        self.quality_cards=self._metric_grid(lay,[('qc','今日质检数'),('first','一次通过率'),('rework','返工率'),('second','二次通过率'),('rework3','≥3 次返工视频'),('avg','平均返工次数')],6)
        reasons=_StatsPanel('返工原因'); self.reason_chart=_HorizontalBars(); reasons.layout_box.addWidget(self.reason_chart)
        hosts=_StatsPanel('质量异常 TOP 5 AI 主播'); self.bad_hosts=QVBoxLayout(); hosts.layout_box.addLayout(self.bad_hosts)
        self._two_col(lay,reasons,hosts,(1,1))
        detail=_StatsPanel('AI 主播质量明细','只读查看，不提供质检/返工/删除操作'); self.quality_table=self._table(['接收人','AI主播','生成片段','一次通过率','返工次数','平均生成次数','平均完成耗时']); self.quality_table.setMinimumHeight(250); detail.layout_box.addWidget(self.quality_table); lay.addWidget(detail)

    def _build_api_system(self):
        page,lay=self._new_page(); self.api_page=page
        left=QWidget(); ll=QVBoxLayout(left); ll.setContentsMargins(0,0,0,0); ll.setSpacing(10)
        self.api_cards=self._metric_grid(ll,[('day','今日 API 费用'),('month','本月 API 费用'),('requests','请求次数'),('input','Input Tokens'),('output','Output Tokens'),('cached','Cached Tokens')],3)
        cost=_StatsPanel('每日 API 费用'); self.cost_chart=_BarChart(); self.cost_chart.setMinimumHeight(240); cost.layout_box.addWidget(self.cost_chart); ll.addWidget(cost)
        model=_StatsPanel('按模型'); self.model_table=self._table(['模型','请求数','Input','Output','Cached','费用']); self.model_table.setMinimumHeight(180); model.layout_box.addWidget(self.model_table); ll.addWidget(model)
        source=_StatsPanel('按功能来源'); self.source_table=self._table(['来源','请求数','费用']); self.source_table.setMinimumHeight(150); source.layout_box.addWidget(self.source_table); ll.addWidget(source)
        self.api_extra=QLabel('',objectName='analyticsHint'); self.api_extra.setWordWrap(True); ll.addWidget(self.api_extra)

        right=QWidget(); rl=QVBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(10)
        health=_StatsPanel('系统健康'); self.health_summary=QLabel(); self.health_summary.setWordWrap(True); health.layout_box.addWidget(self.health_summary); self.health_rows=QVBoxLayout(); health.layout_box.addLayout(self.health_rows); rl.addWidget(health); rl.addStretch(1)
        self._two_col(lay,left,right,(2,1))

    def _select_tab(self,index):
        self.stack.setCurrentIndex(index)
        for i,b in enumerate(self.tab_buttons): b.setChecked(i==index)
        if index==2: self._refresh_channel_runtime()

    @staticmethod
    def _pct(value): return '—' if value is None else f'{float(value)*100:.1f}%'
    @staticmethod
    def _num(value,digits=1): return '—' if value is None else f'{float(value):.{digits}f}'
    @staticmethod
    def _money(value): return f'${float(value or 0):.4f}'
    @staticmethod
    def _duration(seconds):
        if seconds is None: return '—'
        s=max(0,int(seconds))
        if s<60:return f'{s}秒'
        if s<3600:return f'{s/60:.1f}分钟'
        return f'{s/3600:.1f}小时'

    def _clear(self,layout):
        while layout.count():
            item=layout.takeAt(0); w=item.widget()
            if w: w.deleteLater()
            elif item.layout(): self._clear(item.layout())

    def _status_row(self,title,value,tone='gray',detail=''):
        obj={'orange':'analyticsAlert','red':'analyticsBad','green':'analyticsGood'}.get(tone,'analyticsGood' if tone=='ok' else 'analyticsPanel')
        f=QFrame(objectName=obj); h=QHBoxLayout(f); h.setContentsMargins(10,8,10,8); h.setSpacing(8)
        lab=QLabel(str(title)); lab.setWordWrap(True); h.addWidget(lab,1); val=QLabel(str(value)); val.setStyleSheet('font-weight:750;'); h.addWidget(val)
        if detail: f.setToolTip(detail)
        return f

    def _set_table(self,table,rows):
        table.setRowCount(len(rows))
        for i,row in enumerate(rows):
            for j,val in enumerate(row):
                item=QTableWidgetItem(str(val)); item.setTextAlignment(Qt.AlignVCenter| (Qt.AlignLeft if j<2 else Qt.AlignCenter)); table.setItem(i,j,item)
        table.setFixedHeight(min(320,38+max(1,len(rows))*37))

    def reload(self,force=False):
        from app.core.statistics_view import analytics_snapshot
        try:
            active=work_dates.active(); payload=analytics_snapshot(active,self.range.currentText(),force=force); self._last_payload=payload
        except Exception as exc:
            self.last_refresh.setText('统计读取失败'); self.last_refresh.setToolTip(str(exc)); return
        self.date_label.setText(f'工作日期：{payload["work_date"]}  ·  统计聚合：每小时')
        self.last_refresh.setText(QDateTime.currentDateTime().toString('HH:mm')+' 更新')
        self._render_overview(payload['overview']); self._render_efficiency(payload['efficiency']); self._render_flow(payload['flow']); self._render_quality(payload['quality']); self._render_api(payload['api'],payload['system'])

    def _render_overview(self,d):
        day=work_dates.active()
        if getattr(self,'_daily_day',None)!=day:
            self._daily_day=day
            for card in self.overview_cards.values():card.set_data('—','正在读取当前日期')
            self.recipient_table.setRowCount(0)
        self.daily_reader.request(day)

    @staticmethod
    def _video_time(seconds):
        seconds=int(round(seconds));hours,rest=divmod(seconds,3600);minutes,seconds=divmod(rest,60)
        return f'{hours:02d}:{minutes:02d}:{seconds:02d}'

    def _daily_ready(self,day,data,error):
        if day!=work_dates.active():return
        if error:
            self.last_refresh.setText('任务统计读取失败');self.last_refresh.setToolTip(error);return
        d=data;c=self.overview_cards
        c['tasks'].set_data(d['total'],day+' · 完整视频')
        c['completed'].set_data(d['completed'],'已导出或已交付','green')
        c['unfinished'].set_data(d['unfinished'],'当天任务尚未完成','orange')
        c['rate'].set_data(self._pct(d['rate']),'已完成 ÷ 当天任务总数')
        missing=d['duration_missing'];duration=self._video_time(d['seconds'])
        if missing and missing==d['completed']:duration='待读取'
        elif missing:duration+='（部分）'
        c['duration'].set_data(duration,f'{missing} 个成片时长暂不可读' if missing else '时:分:秒 · 成片实际播放时长')
        c['backlog'].set_data(d['backlog'],'所有工作日期累计未完成','orange' if d['backlog'] else 'green')
        rows=[]
        for r in d['recipients']:
            length=self._video_time(r['seconds'])
            if r['duration_missing']:length+='（部分待读取）'
            rows.append([r['recipient_name'],r['total'],r['completed'],r['unfinished'],self._pct(r['rate']),length,r['backlog']])
        self._set_table(self.recipient_table,rows)
        self.recipient_table.setFixedHeight(min(500,self.recipient_table.horizontalHeader().height()+sum(self.recipient_table.rowHeight(i) for i in range(len(rows)))+6))
        self.date_label.setText(f'工作日期：{day} · 任务总览每 30 秒刷新')
        self.last_refresh.setText(QDateTime.currentDateTime().toString('HH:mm:ss')+' 更新')

    def _render_efficiency(self,d):
        self.eff_cards['completed'].set_data(d['completed'],'最终完整视频','green'); self.eff_cards['speed'].set_data(self._num(d['videos_per_hour']),'完整视频 / 小时')
        self.eff_cards['avg'].set_data(self._duration(d['avg_video_seconds']),'平均生产耗时'); self.eff_cards['backlog'].set_data(d['backlog'],'当前未完成任务','orange' if d['backlog'] else 'green')
        self.eff_cards['auto'].set_data(self._pct(d['automation_rate']),'严格口径：无返工/无Flow重试/非手动上传','green')
        self.funnel_chart.set_data(d.get('funnel',[])); self._clear(self.top_bottlenecks)
        bs=d.get('bottlenecks',[])
        if not bs:self.top_bottlenecks.addWidget(self._status_row('生产线','暂无明显瓶颈','green'))
        for i,b in enumerate(bs,1): self.top_bottlenecks.addWidget(self._status_row(f'{i}. {b["stage"]}',f'{b["count"]} 个 · {self._duration(b.get("avg_wait_seconds"))}','orange'))
        items=[{'name':x['stage'],'value':x['seconds']/60,'display':self._duration(x['seconds']),'tone':'blue'} for x in d.get('stage_durations',[]) if x.get('seconds') is not None]
        self.duration_chart.set_data(items)

    def _render_flow(self,d):
        self.flow_cards['total'].set_data(d['total'],'已启用通道'); self.flow_cards['working'].set_data(d['working'],'当前有任务','green'); self.flow_cards['idle'].set_data(d['idle'],'在线但无任务','gray')
        self.flow_cards['abnormal'].set_data(d['abnormal'],'异常 + 离线','red' if d['abnormal'] else 'green'); self.flow_cards['util'].set_data(self._pct(d['avg_utilization']),'按调度占用时间估算'); self.flow_cards['completed'].set_data(d['completed_segments'],'调度检测完成','green')
        self._render_channel_cards(d.get('channels',[])); self.util_chart.set_data([{'name':c['channel_key'],'value':(c.get('utilization') or 0)*100,'display':self._pct(c.get('utilization')),'tone':'green' if c.get('state')=='工作中' else 'blue'} for c in d.get('channels',[])])
        self._clear(self.scheduler_rows)
        for r in d.get('scheduler',[]): self.scheduler_rows.addWidget(self._status_row(r['name'],r['value'],'red' if r.get('severity')=='bad' else 'orange' if r.get('severity')=='warn' else 'green'))

    def _render_channel_cards(self,channels):
        self._clear(self.flow_channel_grid)
        if not channels:
            self.flow_channel_grid.addWidget(QLabel('暂无通道数据',objectName='analyticsHint'),0,0); return
        cols=4
        for i,c in enumerate(channels):
            card=QFrame(objectName='analyticsChannelCard'); v=QVBoxLayout(card); v.setContentsMargins(12,10,12,10); v.setSpacing(4)
            top=QHBoxLayout(); name=QLabel(str(c.get('channel_key'))); name.setStyleSheet('font-weight:800;font-size:14px;'); top.addWidget(name); top.addStretch(1); st=QLabel(str(c.get('state'))); st.setStyleSheet('font-weight:700;color:'+('#16A36A' if c.get('state')=='工作中' else '#D94D55' if c.get('state') in ('异常','离线') else '#8A94A6')+';'); top.addWidget(st); v.addLayout(top)
            v.addWidget(QLabel(f"利用率 {self._pct(c.get('utilization'))}   ·   成功率 {self._pct(c.get('success_rate'))}",objectName='analyticsHint'))
            v.addWidget(QLabel(f"完成 {c.get('done',0)}   失败 {c.get('failed',0)}   重试 {c.get('retries',0)}")); v.addWidget(QLabel('平均生成 '+self._duration(c.get('avg_seconds')),objectName='analyticsHint'))
            if c.get('last_error'): card.setToolTip(str(c.get('last_error')))
            self.flow_channel_grid.addWidget(card,i//cols,i%cols)
        for n in range(cols): self.flow_channel_grid.setColumnStretch(n,1)

    def _refresh_channel_runtime(self):
        if not self.isVisible():return
        if not self._last_payload or self.stack.currentIndex()!=2:return
        try:
            from app.core.statistics_view import _channel_runtime
            current_stub={'channels_history':self._last_payload['flow'].get('channels',[])}
            channels=_channel_runtime(current_stub); self._last_payload['flow']['channels']=channels; self._render_channel_cards(channels)
            states={k:sum(c.get('state')==k for c in channels) for k in ('工作中','空闲','异常','离线')}
            self.flow_cards['working'].set_data(states.get('工作中',0),'当前有任务','green')
            self.flow_cards['idle'].set_data(states.get('空闲',0),'在线但无任务','gray')
            abnormal=states.get('异常',0)+states.get('离线',0); self.flow_cards['abnormal'].set_data(abnormal,'异常 + 离线','red' if abnormal else 'green')
        except Exception: pass

    def _render_quality(self,d):
        self.quality_cards['qc'].set_data(d['qc_count'],'质检决策记录'); self.quality_cards['first'].set_data(self._pct(d['first_pass_rate']),'首轮直接通过','green'); self.quality_cards['rework'].set_data(self._pct(d['rework_rate']),'发生过退回','orange' if d['rework_rate'] else 'green')
        self.quality_cards['second'].set_data(self._pct(d['second_pass_rate']),'第二次质检通过'); self.quality_cards['rework3'].set_data(d['rework3_videos'],'返工决策累计 ≥ 3','red' if d['rework3_videos'] else 'green'); self.quality_cards['avg'].set_data(self._num(d['avg_reworks']),'每个已进入质检的视频')
        tone={'人物/面部异常':'red','口型/台词问题':'red','动作问题':'orange','镜头问题':'orange','声音问题':'orange','画面穿帮':'orange','人物一致性':'red','其他':'gray'}
        self.reason_chart.set_data([{'name':r['reason'],'value':r['n'],'display':r['n'],'tone':tone.get(r['reason'],'gray')} for r in d.get('reasons',[])])
        self._clear(self.bad_hosts); hosts=d.get('hosts',[])[:5]
        if not hosts:self.bad_hosts.addWidget(self._status_row('AI主播','暂无质量数据','green'))
        for i,h in enumerate(hosts,1): self.bad_hosts.addWidget(self._status_row(f"{i}. {h['host_name']}",f"一次通过 {self._pct(h.get('first_pass_rate'))} · 返工 {h['reworks']}",'red' if h['reworks'] else 'green',h.get('recipient_name','')))
        rows=[]
        for h in d.get('hosts',[]): rows.append([h['recipient_name'],h['host_name'],h['segments'],self._pct(h.get('first_pass_rate')),h['reworks'],self._num(h.get('avg_attempts')),self._duration(h.get('avg_seconds'))])
        self._set_table(self.quality_table,rows)

    def _render_api(self,a,s):
        self.api_cards['day'].set_data(self._money(a['day_cost']),'按 API 日志实际费用'); self.api_cards['month'].set_data(self._money(a['month_cost']),'本月累计'); self.api_cards['requests'].set_data(a['requests'],'实际 API 请求次数')
        self.api_cards['input'].set_data(f"{a['input_tokens']:,}",'输入 tokens'); self.api_cards['output'].set_data(f"{a['output_tokens']:,}",'输出 tokens'); self.api_cards['cached'].set_data(f"{a['cached_tokens']:,}",'缓存输入 tokens','green')
        daily=a.get('daily_costs',[]); self.cost_chart.set_data([x['date'][5:] for x in daily],[x['cost'] for x in daily],[f"{x['date']}\n费用：{self._money(x['cost'])}" for x in daily])
        self._set_table(self.model_table,[[m.get('model') or '未标记',m['requests'],f"{m['input_tokens']:,}",f"{m['output_tokens']:,}",f"{m['cached_tokens']:,}",self._money(m['cost_usd'])] for m in a.get('models',[])])
        self._set_table(self.source_table,[[x['source'],x['requests'],self._money(x['cost_usd'])] for x in a.get('sources',[])])
        self.api_extra.setText(f"平均每个完整视频 API 成本：{self._money(a['avg_per_completed_video']) if a.get('avg_per_completed_video') is not None else '—'}    ·    短时间疑似重复 API 调用：{a.get('duplicate_calls',0)}")
        self.health_summary.setText(f"异常总数：{s['total']}    自动恢复：{s['auto_recovery']}    需人工处理：{s['manual']}    自动恢复率：{self._pct(s['auto_recovery_rate'])}")
        self._clear(self.health_rows)
        for row in s.get('items',[]): self.health_rows.addWidget(self._status_row(row['name'],row['count'],'red' if row['count'] else 'green'))
