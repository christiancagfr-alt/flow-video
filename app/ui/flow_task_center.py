
from __future__ import annotations

from app.services.perf_diagnostics import measured
from app.ui.serial_lane import production_ui_action

from pathlib import Path
import os
from app.services import quiet_process as subprocess
import time
import hashlib
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QPixmap
from app.ui.image_preview import set_image
from app.services.image_assets import image_cache_key
from PySide6.QtWidgets import (
    QTreeWidget, QTreeWidgetItem, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QMessageBox, QFrame, QPlainTextEdit, QDialog, QDialogButtonBox,
    QSplitter, QFileDialog, QLineEdit, QFormLayout, QSpinBox, QDoubleSpinBox, QCheckBox, QProgressBar, QScrollArea, QGridLayout, QSizePolicy
)

from app.core import repository as repo
from app.core import work_dates
from app.services import workflow
from app.ui.task_controls import CleanComboBox, CheckCell, GenerationModeToggle
from app.ui.flow_layouts import WrappingRow, CardGrid, ContentScroll, ContentPanel
from app.services import flow_bridge
from app.services import chrome_profiles
from app.services import multi_channel
from app.services import channel_pool, runtime_log, pipeline_orchestrator
from app.services.local_bridge import get_bridge


DEFAULT_FLOW_URL = "https://labs.google/fx/tools/flow/"


class FlowSettingsDialog(QDialog):
    VIDEO_MODELS = [
        ("Gemini Omni · 网页付费模型", "flow_omni"),
        ("Veo 3.1 Lite · Low Priority", "veo_3_1_lite_low_priority"),
        ("Veo 3.1 Lite", "veo_3_1_lite"),
        ("Veo 3.1 Fast", "veo_3_1_fast"),
        ("Veo 3.1 Quality", "veo_3_1_quality"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Flow 设置 · Chrome Profile + 批量插件")
        self.resize(720, 520)

        outer = QVBoxLayout(self)

        # Chrome profile
        chrome_box = QFrame(objectName="card")
        form = QFormLayout(chrome_box)

        self.profile = CleanComboBox()
        self.profiles = chrome_profiles.list_chrome_profiles()
        saved_profile = repo.get_setting("chrome_profile_directory", "Default")
        selected = 0
        for i, p in enumerate(self.profiles):
            detail = p["name"]
            if p["email"]:
                detail += f' · {p["email"]}'
            self.profile.addItem(detail, p["directory"])
            if p["directory"] == saved_profile:
                selected = i
        if self.profiles:
            self.profile.setCurrentIndex(selected)
        else:
            self.profile.addItem("未检测到 Chrome Profile", "Default")

        self.url = QLineEdit(repo.get_setting("flow_url", "https://flow.google.com/"))
        self.bridge_port = QSpinBox()
        self.bridge_port.setRange(1024, 65535)
        try:
            self.bridge_port.setValue(int(repo.get_setting("flow_bridge_port", "17831") or 17831))
        except (TypeError, ValueError):
            self.bridge_port.setValue(17831)
        self.bridge_port.setToolTip("网页插件连接本机 Flow Studio Bridge 的端口；插件里必须填写相同端口。")
        form.addRow("Chrome 身份", self.profile)
        form.addRow("Flow 页面", self.url)
        # form.addRow("本地 Bridge 端口", self.bridge_port)
        self.bridge_port.hide()
        chrome_box.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Maximum)
        outer.addWidget(chrome_box)

        # Plugin settings moved from extension UI
        plugin_box = QFrame(objectName="card")
        pf = QFormLayout(plugin_box)

        self.interval = QSpinBox()
        self.interval.setRange(1, 3600)
        self.interval.setValue(int(repo.get_setting("flow_plugin_interval", "20") or 20))

        self.aspect_ratio = CleanComboBox()
        self.aspect_ratio.addItems(['9:16', '16:9'])
        self.aspect_ratio.setCurrentText(repo.get_setting('flow_aspect_ratio','9:16'))
        pf.addRow('画面比例', self.aspect_ratio)
        self.interval_random = QSpinBox()
        self.interval_random.setRange(0, 3600)
        self.interval_random.setValue(int(repo.get_setting("flow_plugin_interval_random", "10") or 10))

        self.max4 = QSpinBox(); self.max4.setRange(1, 9999)
        self.max4.setValue(int(repo.get_setting("flow_plugin_max4", "40") or 40))
        self.max6 = QSpinBox(); self.max6.setRange(1, 9999)
        self.max6.setValue(int(repo.get_setting("flow_plugin_max6", "60") or 60))
        self.max8 = QSpinBox(); self.max8.setRange(1, 9999)
        self.max8.setValue(int(repo.get_setting("flow_plugin_max8", "80") or 80))

        self.video_model = CleanComboBox()
        saved_model = repo.get_setting("flow_plugin_video_model", "veo_3_1_lite_low_priority")
        model_idx = next((i for i, (_, key) in enumerate(self.VIDEO_MODELS) if key == "veo_3_1_lite_low_priority"), 0)
        for i, (label, value) in enumerate(self.VIDEO_MODELS):
            self.video_model.addItem(label, value)
            if value == saved_model:
                model_idx = i
        self.video_model.setCurrentIndex(model_idx)

        self.download = QCheckBox("自动下载生成视频")
        self.download.setChecked(repo.get_setting("flow_plugin_download", "1") != "0")

        self.preview = QCheckBox("显示文本预览")
        self.preview.setChecked(repo.get_setting("flow_plugin_preview", "1") != "0")

        self.download_root = QLineEdit(repo.get_setting("flow_channel_download_root", str(Path.home()/"Downloads"/"FlowStudio_Channels")))
        self.download_root_btn = QPushButton("选择…")
        def choose_download_root():
            folder=QFileDialog.getExistingDirectory(self,"选择通道下载根目录（包含 CH1/CH2/.../R1）",self.download_root.text().strip() or str(Path.home()/"Downloads"))
            if folder: self.download_root.setText(folder)
        self.download_root_btn.clicked.connect(choose_download_root)
        dr=QWidget(); drl=QHBoxLayout(dr); drl.setContentsMargins(0,0,0,0); drl.addWidget(self.download_root,1); drl.addWidget(self.download_root_btn)

        self.capture = QDoubleSpinBox()
        self.capture.setRange(0.01, 1.0)
        self.capture.setSingleStep(0.01)
        self.capture.setDecimals(2)
        self.capture.setValue(float(repo.get_setting("flow_plugin_capture", "0.95") or 0.95))

        pf.addRow("生成间隔（秒）", self.interval)
        pf.addRow("随机间隔（秒）", self.interval_random)
        # pf.addRow("4秒最大字符", self.max4)
        self.max4.hide()
        # pf.addRow("6秒最大字符", self.max6)
        self.max6.hide()
        # pf.addRow("8秒最大字符", self.max8)
        self.max8.hide()
        pf.addRow("视频模型", self.video_model)
        pf.addRow("下载", self.download)
        pf.addRow("通道下载根目录", dr)
        pf.addRow("文本预览", self.preview)
        pf.addRow("视频截图位置 0~1", self.capture)
        plugin_box.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Maximum)
        outer.addWidget(plugin_box)
        outer.addStretch(1)

        # hint removed from UI

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def save(self):
        repo.set_setting("chrome_profile_directory", self.profile.currentData() or "Default")
        repo.set_setting("flow_url", self.url.text().strip() or "https://flow.google.com/")
        old_port = int(repo.get_setting("flow_bridge_port", "17831") or 17831)
        new_port = int(self.bridge_port.value())
        repo.set_setting("flow_bridge_port", str(new_port))
        repo.set_setting("flow_aspect_ratio", self.aspect_ratio.currentText())
        repo.set_setting("flow_plugin_interval", str(self.interval.value()))
        repo.set_setting("flow_plugin_interval_random", str(self.interval_random.value()))
        repo.set_setting("flow_plugin_max4", str(self.max4.value()))
        repo.set_setting("flow_plugin_max6", str(self.max6.value()))
        repo.set_setting("flow_plugin_max8", str(self.max8.value()))
        repo.set_setting("flow_plugin_video_model", self.video_model.currentData())
        repo.set_setting("flow_plugin_download", "1" if self.download.isChecked() else "0")
        repo.set_setting("flow_channel_download_root", self.download_root.text().strip() or str(Path.home()/"Downloads"/"FlowStudio_Channels"))
        repo.set_setting("flow_download_root", self.download_root.text().strip() or str(Path.home()/"Downloads"/"FlowStudio_Channels"))
        repo.set_setting("flow_plugin_preview", "1" if self.preview.isChecked() else "0")
        repo.set_setting("flow_plugin_capture", str(self.capture.value()))
        if self.parent() and hasattr(self.parent(), "bridge") and new_port != old_port:
            try:
                self.parent().bridge.reconfigure_port(new_port)
            except Exception as exc:
                QMessageBox.critical(self, "Bridge 端口切换失败", str(exc))
                return
        if self.parent() and hasattr(self.parent(), "sync_bridge_config"):
            self.parent().sync_bridge_config()
            try: self.parent().bridge.touch_host_jobs()   # plugin applies new interval/random right away
            except Exception: pass
        self.accept()


class FlowTaskPreviewDialog(QDialog):
    def __init__(self, task, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'Flow任务 · {task["video_seq"]:02d}-{task["seg_seq"]:02d}')
        self.resize(900, 660)
        layout = QVBoxLayout(self)

        info = QLabel(
            f'接收人：{task["recipient_name"]}    主播：{task["host_name"]}    '
            f'任务：{task["video_seq"]:02d}-{task["seg_seq"]:02d}    '
            f'Flow状态：{task["flow_status"] or "待生成"}',
            objectName="muted"
        )
        layout.addWidget(info)

        if task["flow_error"]:
            err = QLabel("失败原因：" + task["flow_error"], objectName="muted")
            err.setWordWrap(True)
            layout.addWidget(err)

        splitter = QSplitter(Qt.Vertical)

        a = QWidget()
        av = QVBoxLayout(a)
        av.addWidget(QLabel("人物文案"))
        foreign = QPlainTextEdit()
        foreign.setReadOnly(True)
        foreign.setPlainText(task["foreign_text"] or "")
        av.addWidget(foreign)

        b = QWidget()
        bv = QVBoxLayout(b)
        bv.addWidget(QLabel("最终 Flow 提示词"))
        prompt = QPlainTextEdit()
        prompt.setReadOnly(True)
        prompt.setPlainText(task["prompt"] or "")
        bv.addWidget(prompt)

        splitter.addWidget(a)
        splitter.addWidget(b)
        layout.addWidget(splitter, 1)

        if task["flow_output_path"]:
            out = QLabel("渲染文件：" + task["flow_output_path"], objectName="muted")
            out.setWordWrap(True)
            layout.addWidget(out)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.clicked.connect(self.accept)
        layout.addWidget(buttons)



class FlowRunMonitorDialog(QDialog):
    def __init__(self, jobs, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Flow 运行进度")
        self.resize(760, 470)
        self.setModal(False)

        self.host_rows = {}
        self.host_totals = {}

        layout = QVBoxLayout(self)

        title = QLabel("Flow 全自动生成运行中")
        title.setStyleSheet("font-size:20px;font-weight:800;")
        layout.addWidget(title)

        hint = QLabel(
            "实时显示集合连接、图片上传、提示词写入、自动生成及失败回传。可隐藏窗口，不影响执行。",
            objectName="muted"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.overall = QProgressBar()
        self.overall.setRange(0,100)
        self.overall.setValue(0)
        layout.addWidget(self.overall)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["AI主播","图片进度","当前步骤","连接"])
        self.table.verticalHeader().setVisible(False)
        self.table.setRowCount(len(jobs))
        self.table.verticalHeader().setDefaultSectionSize(44)

        h=self.table.horizontalHeader()
        h.setSectionResizeMode(0,QHeaderView.Fixed)
        h.setSectionResizeMode(1,QHeaderView.Fixed)
        h.setSectionResizeMode(2,QHeaderView.Stretch)
        h.setSectionResizeMode(3,QHeaderView.Fixed)
        self.table.setColumnWidth(0,150)
        self.table.setColumnWidth(1,120)
        self.table.setColumnWidth(3,110)

        for row,job in enumerate(jobs):
            hid=int(job["host_id"])
            total=int(job.get("image_count") or 0)
            self.host_rows[hid]=row
            self.host_totals[hid]=total
            self.table.setItem(row,0,QTableWidgetItem(job.get("host_name") or str(hid)))
            self.table.setItem(row,1,QTableWidgetItem(f"0 / {total}"))
            self.table.setItem(row,2,QTableWidgetItem("等待集合页面"))
            self.table.setItem(row,3,QTableWidgetItem("⚪ 待连接"))

        layout.addWidget(self.table)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2500)
        self.log.setMaximumHeight(130)
        layout.addWidget(self.log)

        hide_btn = QPushButton("隐藏窗口")
        hide_btn.clicked.connect(self.hide)
        layout.addWidget(hide_btn)

    def append_log(self, message):
        runtime_log.log('channel_ui_log', message=str(message))
        self.log.appendPlainText(f"[{time.strftime('%H:%M:%S')}] {message}")

    def update_host(self, host_id, uploaded=None, step=None, connection=None):
        host_id=int(host_id)
        row=self.host_rows.get(host_id)
        if row is None:
            return

        if uploaded is not None:
            total=self.host_totals.get(host_id,0)
            self.table.setItem(row,1,QTableWidgetItem(f"{int(uploaded)} / {total}"))

        if step:
            self.table.setItem(row,2,QTableWidgetItem(step))

        if connection:
            self.table.setItem(row,3,QTableWidgetItem(connection))

        total_all=sum(self.host_totals.values())
        uploaded_all=0
        for hid,ridx in self.host_rows.items():
            item=self.table.item(ridx,1)
            if not item:
                continue
            try:
                uploaded_all += int(item.text().split("/")[0].strip())
            except Exception:
                pass
        self.overall.setValue(int(uploaded_all/max(total_all,1)*100))


class MultiChannelDialog(QDialog):
    """Configure per-host production channels and one dedicated fast-rework channel."""
    def __init__(self, host_id, host_name, parent=None):
        super().__init__(parent)
        self.host_id=int(host_id); self.host_name=str(host_name)
        self.setWindowTitle(f"多通道设置 · {self.host_name}")
        self.resize(900, 540)
        outer=QVBoxLayout(self)
        title=QLabel(f"{self.host_name} · 多通道生成")
        title.setStyleSheet("font-size:20px;font-weight:800;")
        outer.addWidget(title)
        hint=QLabel("普通通道负责并行生产；R1 是独立高速通道，不参与普通任务。普通任务会按通道平均分配，R1 预载该主播全部参考图。",objectName="muted")
        hint.setWordWrap(True); outer.addWidget(hint)
        top=QHBoxLayout(); top.addWidget(QLabel("普通通道"))
        self.count=QSpinBox(); self.count.setRange(1,2147483647); self.count.setValue(repo.flow_channel_count(self.host_id)); top.addWidget(self.count)
        self.rework=QCheckBox("启用 R1 高速通道"); self.rework.setChecked(True if repo.flow_rework_enabled(self.host_id) else True); top.addWidget(self.rework)
        top.addStretch(1); outer.addLayout(top)
        self.table=QTableWidget(); self.table.setColumnCount(4); self.table.setHorizontalHeaderLabels(["通道","用途","Flow集合链接","状态"])
        self.table.verticalHeader().setVisible(False); self.table.horizontalHeader().setSectionResizeMode(2,QHeaderView.Stretch)
        for c in (0,1,3): self.table.horizontalHeader().setSectionResizeMode(c,QHeaderView.ResizeToContents)
        outer.addWidget(self.table,1)
        self.count.valueChanged.connect(self.rebuild); self.rework.toggled.connect(self.rebuild)
        self.rebuild()
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel); buttons.accepted.connect(self.save); buttons.rejected.connect(self.reject); outer.addWidget(buttons)

    def current_urls(self):
        out={}
        for r in range(self.table.rowCount()):
            key=self.table.item(r,0).text() if self.table.item(r,0) else ''
            edit=self.table.cellWidget(r,2)
            out[key]=edit.text().strip() if isinstance(edit,QLineEdit) else ''
        return out

    def rebuild(self):
        cached=self.current_urls() if hasattr(self,'table') else {}
        existing={str(c['channel_key']):str(c['collection_url'] or '') for c in repo.list_flow_channels(host_id=self.host_id)}
        keys=[f"CH{i}" for i in range(1,self.count.value()+1)] + (["R1"] if self.rework.isChecked() else [])
        self.table.setRowCount(len(keys))
        for r,key in enumerate(keys):
            role="高速通道" if key=='R1' else "普通通道"
            self.table.setItem(r,0,QTableWidgetItem(key)); self.table.setItem(r,1,QTableWidgetItem(role))
            edit=QLineEdit(cached.get(key,existing.get(key,''))); edit.setPlaceholderText(f"粘贴 {key} 对应的 Flow 集合链接")
            self.table.setCellWidget(r,2,edit)
            state="待命" if key=='R1' else "等待连接"
            ch=next((x for x in repo.list_flow_channels(host_id=self.host_id) if x['channel_key']==key),None)
            if ch:
                state=f"{ch['upload_state'] or 'idle'} · 图片 {int(ch['images_uploaded'] or 0)}/{int(ch['images_total'] or 0)}"
            self.table.setItem(r,3,QTableWidgetItem(state))

    def save(self):
        repo.configure_flow_channels(self.host_id,self.count.value(),self.rework.isChecked())
        for r in range(self.table.rowCount()):
            key=self.table.item(r,0).text(); edit=self.table.cellWidget(r,2)
            ch=next((x for x in repo.list_flow_channels(host_id=self.host_id) if x['channel_key']==key),None)
            if ch and isinstance(edit,QLineEdit): repo.set_flow_channel_url(ch['id'],edit.text().strip())
        self.accept()


class FlowBatchCenterPage(QWidget):
    def __init__(self, parent_window=None):
        super().__init__()
        self.parent_window = parent_window
        self.task_rows = []
        self.checked_ids = set()
        self._fill_source_row = None
        self._fill_target_state = None
        self.bridge = get_bridge()
        # V0.13.5 production control is owned by the live Bridge pause state. Older
        # builds could leave these DB flags at 0/1 even though the current UI no longer
        # exposes them, producing a false “自动生产运行中” while the scheduler silently
        # returned on every tick. Migrate that stale state once at page construction.
        legacy_auto=repo.get_setting('flow_auto_production_enabled','1')
        legacy_pause=repo.get_setting('flow_production_paused','0')
        if legacy_auto!='1' or legacy_pause=='1':
            repo.set_setting('flow_auto_production_enabled','1')
            repo.set_setting('flow_production_paused','0')
            runtime_log.log('legacy_auto_production_flags_migrated',old_auto=legacy_auto,old_pause=legacy_pause)
        # Background workers keep SQLite/file-system work out of the Qt GUI thread.
        self.telemetry_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="flowstudio-telemetry")
        self.download_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="flowstudio-download-scan")
        self._download_scan_future = None
        from app.services.production_worker import ProductionWorker
        from app.ui.serial_lane import SerialLane
        self._production_worker = ProductionWorker(self.bridge)
        self._production_lane = SerialLane(self)

        # These objects are used during reload_filters() -> reload_tasks()
        # -> refresh_link_table(), so they MUST exist before the first reload.
        self.host_last_seen = {}
        self.flow_monitor = None
        # Current generation command per host. Delayed callbacks from an older
        # command are ignored so they cannot overwrite a newer run.
        self.active_task_commands = {}

        self.build()
        from app.ui.read_snapshot import SnapshotReader
        from app.services.flow_view_snapshot import read_snapshot
        self._view_cache = None
        self._view_pending = None
        self._view_dirty = True
        self._view_reader = SnapshotReader(self, read_snapshot)
        self._view_reader.ready.connect(self._view_ready)
        self._visual_timer = QTimer(self)
        self._visual_timer.setInterval(750)
        self._visual_timer.timeout.connect(self._flush_view)
        self._visual_timer.start()
        self.reload_filters()
        self.sync_bridge_config()

        self.bridge_timer = QTimer(self)
        self.bridge_timer.timeout.connect(self.refresh_bridge_status)
        self.bridge_timer.timeout.connect(self.process_bridge_events)
        self.bridge_timer.timeout.connect(self.refresh_live_connection_states)
        self.bridge_timer.timeout.connect(self.dispatch_redo)
        self.bridge_timer.start(1200)

        # Folder scanning and local-file acceptance are I/O-heavy; poll them separately
        # and execute the work off the UI thread.
        self.download_scan_timer = QTimer(self)
        self.download_scan_timer.timeout.connect(self.process_channel_downloads)
        self.download_scan_timer.start(2500)

        # V0.13.5: GPT“提交到 Flow” is the production authorization.
        # Flow Center automatically consumes approved tasks; no first-run Start button is required.
        self._auto_dispatch_running = False
        self.auto_dispatch_timer = QTimer(self)
        self.auto_dispatch_timer.timeout.connect(self.auto_dispatch_tick)
        # Central queue watchdog: continuously scan approved waiting tasks and refill
        # every genuinely available channel.  Do not depend on a one-shot completion event.
        self.auto_dispatch_timer.start(2000)

        # Explicit desktop -> web-plugin progress scan every 10 seconds.
        self.progress_scan_timer = QTimer(self)
        self.progress_scan_timer.timeout.connect(self.request_progress_scan)
        self.progress_scan_timer.start(10000)
        # Do not perform a full task/channel rescan while the window is still being built.
        QTimer.singleShot(700, self.request_progress_scan)
        self.refresh_pause_button()
        self.refresh_bridge_status()

    def build(self):
        # Responsive shell: the whole Flow Center scrolls as one page when the
        # window becomes smaller, instead of compressing/overlapping controls.
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0,0,0,0)
        root_layout.setSpacing(0)
        self.page_scroll = QScrollArea(objectName="pageScroll")
        self.page_scroll.setWidgetResizable(True)
        self.page_scroll.setFrameShape(QFrame.NoFrame)
        self.page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.page_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.page_scroll.setMinimumWidth(0)
        self.page_content = QWidget(objectName="pageScrollContent")
        self.page_content.setMinimumWidth(0)
        layout = QVBoxLayout(self.page_content)
        layout.setContentsMargins(16,18,16,18)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignTop)
        self.page_scroll.setWidget(self.page_content)
        root_layout.addWidget(self.page_scroll)

        # Header
        header=ContentPanel()
        top = WrappingRow(header,spacing=12)
        title_block=QWidget(); tb = QVBoxLayout(title_block); tb.setContentsMargins(0,0,0,0)
        title = QLabel("Flow 生成中心")
        title.setStyleSheet("font-size:27px;font-weight:800;")
        sub = QLabel(
            "按接收人和主播管理批次 · 下载完成后自动进入视频质检",
            objectName="muted"
        )
        tb.addWidget(title)
        sub.setWordWrap(True)
        tb.addWidget(sub)
        top.addWidget(title_block)

        self.bridge_status = QLabel("Bridge：检查中…", objectName="muted")
        top.addWidget(self.bridge_status)
        self.bridge_port_badge = QLabel(f"端口 {getattr(self.bridge, 'port', 17831)}", objectName="cardMeta")
        self.bridge_port_badge.setToolTip("网页插件必须使用相同的本地 Bridge 端口")
        top.addWidget(self.bridge_port_badge)

        settings = QPushButton("⚙ Flow设置")
        settings.clicked.connect(self.open_settings)
        top.addWidget(settings)

        layout.addWidget(header)

        # Production monitor: GPT submission is the authorization, so there is no Start button here.
        prod=ContentPanel(objectName="topStrip"); pr=WrappingRow(prod); pr.setContentsMargins(14,10,14,10); pr.setSpacing(14)
        self.visual_auto_state=QLabel("● 自动生产运行中",objectName="statusGood"); pr.addWidget(self.visual_auto_state)
        self.visual_pause_btn=QPushButton("⏸ 暂停生产"); self.visual_pause_btn.clicked.connect(self.toggle_generation_pause); pr.addWidget(self.visual_pause_btn)
        stop_btn=QPushButton("■ 停止生产",objectName="ghostDanger"); stop_btn.clicked.connect(self.stop_production); pr.addWidget(stop_btn)
        self.visual_today=QLabel("今日完成 0 / 0",objectName="cardTitle"); pr.addWidget(self.visual_today)
        layout.addWidget(prod)

        state_strip=ContentPanel(objectName="topStrip",floor=44); ss=WrappingRow(state_strip); ss.setContentsMargins(14,8,14,8); ss.setSpacing(26)
        self.visual_running=QLabel("生成中 0",objectName="statusInfo"); self.visual_downloading=QLabel("下载完成 0",objectName="statusGood"); self.visual_failed=QLabel("异常 0",objectName="statusBad"); self.visual_rework=QLabel("返工 0",objectName="statusWarn")
        for w in (self.visual_running,self.visual_downloading,self.visual_failed,self.visual_rework): ss.addWidget(w)
        state_strip.setMinimumHeight(44); layout.addWidget(state_strip)

        # Channels: normal and fast cards share the same responsive grid.
        ch_section=ContentPanel(objectName="pageCard"); chv=QVBoxLayout(ch_section); chv.setContentsMargins(14,12,14,12); chv.setSpacing(8)
        chh=QHBoxLayout(); chh.addWidget(QLabel("运行通道",objectName="sectionTitle")); self.visual_channel_summary=QLabel("0 / 0 在线",objectName="muted"); chh.addWidget(self.visual_channel_summary); chh.addStretch(1); chv.addLayout(chh)
        channel_actions=WrappingRow()
        self.channel_add_browser=CleanComboBox(); self.channel_add_browser.addItem('浏览器A','A'); channel_actions.addWidget(self.channel_add_browser)
        self.add_normal_btn=QPushButton('＋ 添加普通通道',objectName='channelAddNormalBtn'); self.add_normal_btn.clicked.connect(self.add_normal_channel); channel_actions.addWidget(self.add_normal_btn)
        runtime_btn=QPushButton('运行任务 / 重试',objectName='channelRuntimeRetryBtn'); runtime_btn.clicked.connect(self.show_runtime_tasks); channel_actions.addWidget(runtime_btn)
        browser_add=QPushButton('＋ 添加浏览器',objectName='channelAddBrowserBtn'); browser_add.clicked.connect(self.add_browser_group_ui); channel_actions.addWidget(browser_add)
        chv.addLayout(channel_actions)
        chbody=QHBoxLayout(); chbody.setSpacing(10)
        self.visual_channel_scroll=ContentScroll(lambda: (4 if self.visual_channel_grid.count()<=8 else 3)*158-8)
        self.visual_channel_content=QWidget(objectName="scrollContent")
        self.visual_channel_grid=CardGrid(self.visual_channel_content)
        self.visual_channel_scroll.setWidget(self.visual_channel_content); chbody.addWidget(self.visual_channel_scroll,1)
        self.visual_rework_card=QFrame(objectName="channelCard"); self.visual_rework_card.setMinimumWidth(180); self.visual_rework_card.setMaximumWidth(205); rw=QVBoxLayout(self.visual_rework_card); rw.setContentsMargins(14,12,14,12); rw.addWidget(QLabel("REWORK",objectName="cardTitle")); self.visual_rework_state=QLabel("○ 未连接",objectName="muted"); rw.addWidget(self.visual_rework_state); self.visual_rework_meta=QLabel("返工专用通道",objectName="muted"); self.visual_rework_meta.setWordWrap(True); rw.addWidget(self.visual_rework_meta); self.visual_rework_link=QLineEdit(); self.visual_rework_link.setPlaceholderText('高速通道 Flow 集合链接'); self.visual_rework_link.editingFinished.connect(self._save_fast_link); rw.addWidget(self.visual_rework_link); rw.addStretch(1); chbody.addWidget(self.visual_rework_card)
        self.visual_rework_card.hide()
        chv.addLayout(chbody); layout.addWidget(ch_section)

        # Recipient/host production progress: same visual grammar as Task Center, but no editing controls.
        progress_section=ContentPanel(objectName="pageCard"); psv=QVBoxLayout(progress_section); psv.setContentsMargins(14,12,14,12); psv.setSpacing(8); psv.addWidget(QLabel("生产进度",objectName="sectionTitle"))
        self.visual_progress_scroll=ContentScroll(lambda: max(160,self.height()//2))
        self.visual_progress_content=QWidget(objectName="flowProductionProgressContent")
        self.visual_progress_layout=QVBoxLayout(self.visual_progress_content); self.visual_progress_layout.setContentsMargins(0,0,0,0); self.visual_progress_layout.setSpacing(10); self.visual_progress_layout.setAlignment(Qt.AlignTop)
        self.visual_progress_scroll.setWidget(self.visual_progress_content); psv.addWidget(self.visual_progress_scroll); layout.addWidget(progress_section)
        self.channel_section=ch_section; self.progress_section=progress_section


        # Filters + primary production actions
        filters = QFrame(objectName="card")
        f = QHBoxLayout(filters)
        f.setSpacing(10)

        f.addWidget(QLabel("接收人"))
        self.recipient = CleanComboBox()
        self.recipient.currentIndexChanged.connect(self.recipient_changed)
        f.addWidget(self.recipient)

        f.addWidget(QLabel("AI主播"))
        self.host = CleanComboBox()
        self.host.currentIndexChanged.connect(self.reload_tasks)
        f.addWidget(self.host)

        f.addWidget(QLabel("生成模式"))
        self.task_mode_manager_btn = QPushButton("管理任务帧 / 素材")
        self.task_mode_manager_btn.setToolTip("每个 Flow 片段独立使用帧或素材；这里只修改尚未进入 Flow 的任务")
        self.task_mode_manager_btn.clicked.connect(self.open_task_mode_manager)
        f.addWidget(self.task_mode_manager_btn)

        f.addWidget(QLabel("生成轮数"))
        self.generation_count = CleanComboBox()
        for n in range(1, 5):
            self.generation_count.addItem(str(n), n)
        try:
            saved_generation_count = int(repo.get_setting("flow_generation_count", "1") or 1)
        except (TypeError, ValueError):
            saved_generation_count = 1
        saved_generation_count = max(1, min(4, saved_generation_count))
        self.generation_count.setCurrentIndex(saved_generation_count - 1)
        self.generation_count.currentIndexChanged.connect(self.save_generation_count)
        self.generation_count.setToolTip("每个片段生成几轮，由本地 Studio 统一控制。默认：1")
        f.addWidget(self.generation_count)

        f.addStretch(1)

        copy_btn = QPushButton("复制到插件")
        copy_btn.setToolTip("复制当前选中任务：任务ID / 图片 / 人物文案 / Flow提示词")
        copy_btn.clicked.connect(self.copy_selected_for_plugin)
        f.addWidget(copy_btn)

        layout.addWidget(filters)

        # Stats
        stats = QHBoxLayout()
        self.total_label = QLabel("可生成：0")
        self.pending_label = QLabel("待生成：0")
        self.prepared_label = QLabel("已准备：0")
        self.submitted_label = QLabel("已提交：0")
        self.running_label = QLabel("生成中：0")
        self.done_label = QLabel("已完成：0")
        self.failed_label = QLabel("失败：0")
        self.downloading_label = QLabel("下载完成：0")
        for w in [
            self.total_label,self.pending_label,self.prepared_label,
            self.submitted_label,self.running_label,self.downloading_label,self.done_label,self.failed_label
        ]:
            stats.addWidget(w)
        stats.addStretch(1)
        layout.addLayout(stats)
        self.channel_summary_label=QLabel("生成通道：未配置", objectName="muted")
        self.channel_summary_label.setWordWrap(True)
        layout.addWidget(self.channel_summary_label)

        # Global channel pool: links are configured once, not once per host/task.
        channel_card = QFrame(objectName="card")
        channel_layout = QVBoxLayout(channel_card)
        channel_top = QHBoxLayout()
        channel_title = QLabel("生成通道池 · 统一配置")
        channel_title.setStyleSheet("font-size:17px;font-weight:700;")
        channel_top.addWidget(channel_title)
        channel_top.addStretch(1)

        add_browser = QPushButton("＋ 添加浏览器")
        add_browser.setToolTip("增加浏览器C/D/E…；浏览器数量不写死")
        add_browser.clicked.connect(self.add_browser_group_ui)
        channel_top.addWidget(add_browser)
        add_channel = QPushButton("＋ 当前浏览器普通通道")
        add_channel.setToolTip("给当前选择的浏览器增加普通通道；无固定软件上限")
        add_channel.clicked.connect(self.add_normal_channel)
        channel_top.addWidget(add_channel)
        self.fast_channel_btn = QPushButton("切换当前高速通道")
        self.fast_channel_btn.clicked.connect(self.toggle_current_fast_channel)
        channel_top.addWidget(self.fast_channel_btn)
        save_channels = QPushButton("保存通道")
        save_channels.clicked.connect(self.save_channel_pool)
        channel_top.addWidget(save_channels)
        open_channels = QPushButton("打开全部通道")
        open_channels.clicked.connect(self.open_all_channel_links)
        channel_top.addWidget(open_channels)
        upload_all = QPushButton("上传图片")
        upload_all.setToolTip("调度器先自动分配任务，再把每个通道需要的参考图发送到对应 Flow 集合")
        upload_all.clicked.connect(self.upload_all_host_images)
        channel_top.addWidget(upload_all)
        self.auto_production_state = QLabel("● 自动生产", objectName="muted")
        self.auto_production_state.setToolTip("GPT 页面提交到 Flow 后，调度器自动领取任务；无需手动开始。")
        channel_top.addWidget(self.auto_production_state)
        logs = QPushButton("运行日志")
        logs.clicked.connect(self.open_runtime_log)
        channel_top.addWidget(logs)
        channel_layout.addLayout(channel_top)

        guide = QLabel(
            "默认浏览器A共 8 个通道：CH1~CH7 为普通通道，R1 为高速通道。"
            "可继续添加浏览器B/C/D/E…，每个浏览器的普通通道数量不设固定软件上限。"
            "不同浏览器并行启动；10~15秒随机错峰只在同一浏览器内部独立计算，高速通道不等待。",
            objectName="muted"
        )
        guide.setWordWrap(True)
        channel_layout.addWidget(guide)

        browser_row=QHBoxLayout()
        browser_row.addWidget(QLabel("当前浏览器"))
        self.browser_pool_selector=CleanComboBox()
        self.browser_pool_selector.currentIndexChanged.connect(self.browser_group_changed)
        browser_row.addWidget(self.browser_pool_selector)
        browser_row.addWidget(QLabel("Chrome Profile"))
        self.browser_pool_profile=CleanComboBox()
        profiles=chrome_profiles.list_chrome_profiles()
        if profiles:
            for prof in profiles:
                label=prof['name']+(f" · {prof['email']}" if prof.get('email') else '')
                self.browser_pool_profile.addItem(label,prof['directory'])
        else:
            self.browser_pool_profile.addItem("Default","Default")
        browser_row.addWidget(self.browser_pool_profile,1)
        save_browser=QPushButton("保存当前浏览器")
        save_browser.clicked.connect(self.save_current_browser_profile)
        browser_row.addWidget(save_browser)
        browser_row.addSpacing(18)
        browser_row.addWidget(QLabel("通道释放随机间隔"))
        self.dispatch_stagger_min=QSpinBox(); self.dispatch_stagger_min.setRange(1,3600)
        self.dispatch_stagger_min.setValue(int(repo.get_setting('flow_dispatch_stagger_min','10') or 10))
        self.dispatch_stagger_max=QSpinBox(); self.dispatch_stagger_max.setRange(1,3600)
        self.dispatch_stagger_max.setValue(int(repo.get_setting('flow_dispatch_stagger_max','15') or 15))
        browser_row.addWidget(self.dispatch_stagger_min)
        browser_row.addWidget(QLabel("～"))
        browser_row.addWidget(self.dispatch_stagger_max)
        browser_row.addWidget(QLabel("秒"))
        channel_layout.addLayout(browser_row)

        self.channel_table = QTableWidget()
        self.channel_table.setColumnCount(9)
        self.channel_table.setHorizontalHeaderLabels(["浏览器","通道","用途","Flow集合 / 端口链接","本地下载文件夹","当前负载","插件连接","Flow页面","最近状态"])
        self.channel_table.verticalHeader().setVisible(False)
        self.channel_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.channel_table.setFocusPolicy(Qt.NoFocus)
        chh=self.channel_table.horizontalHeader()
        for col in [0,1,2,4,5,6,7,8]: chh.setSectionResizeMode(col,QHeaderView.Fixed)
        chh.setSectionResizeMode(3,QHeaderView.Stretch)
        for col,w in {0:78,1:82,2:92,4:165,5:80,6:100,7:115,8:170}.items(): self.channel_table.setColumnWidth(col,w)
        self.channel_table.verticalHeader().setDefaultSectionSize(48)
        self.channel_table.setMinimumHeight(250)
        self.channel_table.setMaximumHeight(360)
        channel_layout.addWidget(self.channel_table)
        layout.addWidget(channel_card)

        # Host/task overview stays visible below the channel configuration. No per-row generate button.
        overview_card = QFrame(objectName="card")
        overview_layout = QVBoxLayout(overview_card)
        overview_title = QLabel("任务概览 · 调度器自动分配通道")
        overview_title.setStyleSheet("font-size:16px;font-weight:700;")
        overview_layout.addWidget(overview_title)
        self.link_table = QTableWidget()
        self.link_table.setColumnCount(8)
        self.link_table.setHorizontalHeaderLabels(["接收人","AI主播","待生成","已提交/生成中","已完成","失败","分配通道","状态"])
        self.link_table.verticalHeader().setVisible(False)
        self.link_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.link_table.setFocusPolicy(Qt.NoFocus)
        oh=self.link_table.horizontalHeader()
        for col in range(8): oh.setSectionResizeMode(col,QHeaderView.Fixed)
        oh.setSectionResizeMode(1,QHeaderView.Stretch)
        for col,w in {0:130,2:82,3:115,4:82,5:82,6:180,7:130}.items(): self.link_table.setColumnWidth(col,w)
        self.link_table.verticalHeader().setDefaultSectionSize(42)
        self.link_table.setMinimumHeight(120)
        self.link_table.setMaximumHeight(230)
        overview_layout.addWidget(self.link_table)
        layout.addWidget(overview_card)

        # Secondary operations
        ops = QHBoxLayout()
        self.selected_label = QLabel("已选择：0", objectName="muted")
        ops.addWidget(self.selected_label)
        ops.addStretch(1)

        ops.addWidget(QLabel("状态"))
        self.status = CleanComboBox()
        self.status.addItems(["全部","待生成","已准备","已提交","生成中","已完成","失败","下载失败"])
        self.status.setToolTip("选择状态后，下面任务区中符合该状态的任务会直接勾选")
        self.status.currentIndexChanged.connect(self.select_tasks_by_status)
        ops.addWidget(self.status)

        reset = QPushButton("重置所选")
        reset.clicked.connect(self.reset_selected)
        ops.addWidget(reset)

        self.pause_all_btn = QPushButton("⏸ 暂停全部")
        self.pause_all_btn.clicked.connect(self.toggle_generation_pause)
        ops.addWidget(self.pause_all_btn)

        layout.addLayout(ops)

        self.scope_key = None
        self.page_index = 0
        self.tree_signature = None
        paging = QHBoxLayout()
        self.search_tasks = QLineEdit()
        self.search_tasks.setPlaceholderText("搜索接收人、主播、任务编号或文案")
        self.search_tasks.textChanged.connect(lambda: self.change_task_page(0, reset=True))
        paging.addWidget(self.search_tasks, 1)
        self.page_label = QLabel()
        paging.addWidget(self.page_label)
        for label, delta in [("上一页", -1), ("下一页", 1)]:
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, d=delta: self.change_task_page(d))
            paging.addWidget(button)
        layout.addLayout(paging)
        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(12)
        self.table.setHorizontalHeaderLabels([
            "☐","任务ID","参考图","人物文案","最终Flow提示词",
            "Flow状态","尝试","失败原因","输出文件","接收人","主播","通道"
        ])
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(44)

        h = self.table.horizontalHeader()
        for col in range(12):
            h.setSectionResizeMode(col, QHeaderView.Fixed)
        h.setSectionResizeMode(3, QHeaderView.Stretch)
        h.setSectionResizeMode(4, QHeaderView.Stretch)

        widths = {0:58,1:86,2:105,5:92,6:62,7:180,8:125,9:92,10:92,11:72}
        for col,width in widths.items():
            self.table.setColumnWidth(col,width)

        self.table.horizontalHeader().sectionClicked.connect(self.header_clicked)
        self.table.cellDoubleClicked.connect(self.open_preview)
        split = QSplitter(Qt.Horizontal)
        self.task_tree = QTreeWidget()
        self.task_tree.setHeaderLabels(["接收人 / 主播 / 完整视频", "已下载 / 总数"])
        self.task_tree.setMinimumWidth(270)
        self.task_tree.itemClicked.connect(self.select_task_scope)
        split.addWidget(self.task_tree)
        split.addWidget(self.table)
        split.setStretchFactor(1, 1)
        split.setSizes([300, 1050])
        layout.addWidget(split, 1)
        # Keep the mature management widgets alive for compatibility, but the confirmed
        # production UI is intentionally monitor-first. Technical configuration stays in dialogs/settings.
        for w in (filters, channel_card, overview_card, split, self.channel_summary_label):
            w.hide()
        for lay in (stats, ops, paging):
            for i in range(lay.count()):
                ww=lay.itemAt(i).widget()
                if ww: ww.hide()

        self._legacy_monitor_layouts=(stats,ops,paging)
        for hidden_layout in self._legacy_monitor_layouts:
            layout.removeItem(hidden_layout)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self,'visual_channel_scroll'):
            self.visual_channel_scroll.schedule()
            self.visual_progress_scroll.schedule()

    def _clear_visual_layout(self, layout):
        while layout.count():
            item=layout.takeAt(0); w=item.widget(); child=item.layout()
            if w: w.hide(); w.deleteLater()
            elif child: self._clear_visual_layout(child)

    def stop_production(self):
        # Stop is intentionally safe: no new dispatches are taken, while jobs already
        # submitted to Flow remain monitored so paid generations are not thrown away.
        if QMessageBox.question(self,"停止生产","停止领取新的 Flow 任务？已经提交到 Flow 的任务仍会继续监控和下载。") != QMessageBox.Yes:
            return
        self.bridge.set_generation_paused(True)
        self.refresh_pause_button(); self.refresh_visual_monitor()

    @production_ui_action
    def _save_fast_link(self):
        if not hasattr(self,'visual_rework_link'): return
        fast=next((c for c in repo.list_channel_pool(enabled_only=False) if str(c['role'])=='fast'),None)
        if fast:
            repo.save_channel_pool(str(fast['channel_key']), collection_url=self.visual_rework_link.text().strip())

    def _toggle_host_priority(self, host_id, day):
        from app.services import host_priority
        enabled=host_priority.toggle(day,host_id)
        runtime_log.log('host_generation_priority',work_date=day,host_id=host_id,enabled=enabled)
        self._progress_signature=None
        self.refresh_visual_monitor()

    @measured('flow_ui_refresh')
    def refresh_visual_monitor(self):
        cache = getattr(self, '_view_cache', None)
        if not self.isVisible() or not cache or cache['key'][0] != work_dates.active():
            self.reload_tasks(); return
        if not hasattr(self,'visual_channel_grid'): return
        tasks=cache['all_tasks']
        # UI运行态必须以“当前命令对应的实时 dispatch”为准，不能直接累计
        # flow_segments 里的历史 已提交/生成中 状态；后者在插件重启/旧批次残留时
        # 可能长期存在，从而造成“生成中 81”以及空通道仍显示若干片段。
        live_dispatches=cache['live']
        live_generating_ids={int(d['segment_id']) for d in live_dispatches
                             if str(d['status'] or '')=='submitted' and str(d['flow_status'] or '') in ('已提交','生成中')}
        live_downloading_ids={int(d['segment_id']) for d in live_dispatches if str(d['status'] or '')=='downloading'}
        total=len(tasks); done=sum(1 for t in tasks if str(t['flow_status'] or '')=='已完成')
        running=sum(1 for t in tasks if int(t['segment_id']) in live_generating_ids)
        downloaded=sum(1 for t in tasks if str(t['flow_status'] or '')=='已完成')
        failed=sum(1 for t in tasks if str(t['flow_status'] or '') in ('失败','下载失败'))
        rework=sum(1 for t in tasks if int(t['flow_retry_count'] or 0)>0 and str(t['flow_status'] or '')!='已完成')
        self.visual_today.setText(f"当日完成 {done} / {total}")
        self.visual_running.setText(f"生成中 {running}"); self.visual_downloading.setText(f"下载完成 {downloaded}"); self.visual_failed.setText(f"异常 {failed}"); self.visual_rework.setText(f"返工 {rework}")
        paused=bool(self.bridge.generation_control().get('paused'))
        if paused!=getattr(self,'_monitor_paused',None):
            self._monitor_paused=paused
            self.visual_auto_state.setText('● 自动生产已暂停' if paused else '● 自动生产运行中')
            self.visual_auto_state.setObjectName('statusWarn' if paused else 'statusGood')
            self.visual_auto_state.style().unpolish(self.visual_auto_state);self.visual_auto_state.style().polish(self.visual_auto_state)
            self.visual_pause_btn.setText('▶ 恢复生产' if paused else '⏸ 暂停生产')

        # Every normal and fast channel is editable in the same scrolling area.
        channels=cache['channels']
        now=time.time(); online=sum(1 for c in channels if c['last_seen'] and now-float(c['last_seen'])<8)
        self.visual_channel_summary.setText(f"{online} / {len(channels)} 在线")
        from app.services import host_priority
        from app.ui import flow_monitor_cards
        day=work_dates.active()
        flow_monitor_cards.refresh(self,tasks,live_dispatches,channels,now,day,cache['priorities'])

    def reload_filters(self):
        current_rid = self.recipient.currentData() if self.recipient.count() else None
        self.recipient.blockSignals(True)
        self.recipient.clear()
        self.recipient.addItem("全部", None)
        selected_index = 0
        for i, row in enumerate(repo.list_recipients(work_date=work_dates.active()), start=1):
            self.recipient.addItem(row["name"], row["id"])
            if row["id"] == current_rid:
                selected_index = i
        self.recipient.setCurrentIndex(selected_index)
        self.recipient.blockSignals(False)
        self.recipient_changed()

    def recipient_changed(self):
        rid = self.recipient.currentData()
        old_hid = self.host.currentData() if self.host.count() else None
        self.host.blockSignals(True)
        self.host.clear()
        self.host.addItem("全部", None)
        selected_index = 0
        if rid:
            for i,h in enumerate(repo.list_hosts(rid, work_date=work_dates.active()), start=1):
                self.host.addItem(h["name"], h["id"])
                if h["id"] == old_hid:
                    selected_index = i
        self.host.setCurrentIndex(selected_index)
        self.host.blockSignals(False)
        self.reload_tasks()

    def _view_key(self):
        return (work_dates.active(), self.recipient.currentData(), self.host.currentData(),
                tuple(self.scope_key) if self.scope_key else None,
                self.search_tasks.text().strip().lower(), self.page_index)

    def reload_tasks(self):
        self._view_dirty = True

    def showEvent(self, event):
        super().showEvent(event)
        if hasattr(self, '_visual_timer'):
            self._visual_timer.start()
            self._view_dirty = True
            self._flush_view()

    def hideEvent(self, event):
        if hasattr(self, '_visual_timer'): self._visual_timer.stop()
        super().hideEvent(event)

    def _view_ready(self, key, result, error):
        if key != self._view_key(): return
        if error:
            runtime_log.log('flow_view_read_failed',level='ERROR',error=error)
            self._view_dirty = True
            return
        self._view_pending = result

    def _flush_view(self):
        if not self.isVisible(): return
        if self._view_pending is not None:
            snapshot, self._view_pending = self._view_pending, None
            if snapshot['key'] == self._view_key():
                self._view_cache = snapshot
                self._apply_view(snapshot)
        if self._view_dirty:
            self._view_dirty = False
            self._view_reader.request(self._view_key())

    @measured('flow_ui_refresh')
    def _apply_view(self, snapshot):
        self.refresh_task_tree(snapshot['tree_rows'])
        self.page_index = snapshot['page']
        self.page_label.setText(f"{snapshot['total']} 个片段 · {self.page_index+1}/{snapshot['pages']} 页 · 每页100条")
        self.task_rows = snapshot['rows']

        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(self.task_rows))
        self.table.horizontalHeaderItem(0).setText("☐")

        previous = getattr(self, '_task_table_ids', [])
        for row, task in enumerate(self.task_rows):
            sid = task['segment_id']
            if row >= len(previous) or previous[row] != sid:
                check = CheckCell(sid in self.checked_ids)
                check.changed.connect(lambda checked, segment_id=sid: self.on_row_check_changed(segment_id, checked))
                check.drag_started.connect(lambda state, source_row=row: self.start_fill_drag(source_row, state))
                check.drag_moved_global.connect(self.update_fill_drag)
                check.drag_finished.connect(self.finish_fill_drag)
                self.table.setCellWidget(row, 0, check)
            values = (
                (f"{task['video_seq']:02d}-{task['seg_seq']:02d}", ''),
                (Path(task['image_path']).name if task['image_path'] else '无图片', ''),
                (task['foreign_text'] or '', task['foreign_text'] or ''),
                (task['prompt'] or '', task['prompt'] or ''),
                (task['flow_status'] or '待生成', ''),
                (str(task['flow_attempts'] or 0), ''),
                (task['flow_error'] or '', task['flow_error'] or ''),
                (Path(task['flow_output_path']).name if task['flow_output_path'] else '', task['flow_output_path'] or ''),
                (task['recipient_name'], ''), (task['host_name'], ''),
                (task['flow_channel_key'] or '—', ''),
            )
            for column, (text, tip) in enumerate(values, 1):
                item = self.table.item(row, column)
                if item is None:
                    item = QTableWidgetItem()
                    self.table.setItem(row, column, item)
                if item.text() != text:
                    item.setText(text)
                if item.toolTip() != tip:
                    item.setToolTip(tip)
        self._task_table_ids = [task['segment_id'] for task in self.task_rows]

        self.update_header_check()
        self.table.setUpdatesEnabled(True)
        self.refresh_stats()
        if not getattr(self,"_date_view_refresh",False):
            self.refresh_channel_pool_table()
            self.refresh_link_table()
        self.refresh_visual_monitor()

    @measured('statistics_refresh')
    def refresh_stats(self):
        cache = getattr(self, '_view_cache', None)
        if not cache or cache['key'][:3] != self._view_key()[:3]:
            self.reload_tasks(); return
        s = cache['stats']
        self.total_label.setText(f'任务总数：{s["total"]}')
        self.pending_label.setText(f'待生成：{s["pending"]}')
        self.prepared_label.setText(f'已准备：{s["prepared"]}')
        self.submitted_label.setText(f'已提交：{s["submitted"]}')
        self.running_label.setText(f'生成中：{s["running"]}')
        self.done_label.setText(f'已完成：{s["done"]}')
        self.downloading_label.setText(f'下载完成：{s["done"]}')
        self.failed_label.setText(f'失败：{s["failed"]}')
        self.selected_label.setText(f"已选择：{len(self.selected_ids())}")
        if not getattr(self,"_date_view_refresh",False): self.refresh_channel_summary()

    def refresh_channel_summary(self):
        if not hasattr(self,'channel_summary_label'): return
        rid=self.recipient.currentData() if hasattr(self,'recipient') else None
        hid=self.host.currentData() if hasattr(self,'host') else None
        if hid:
            repo.ensure_flow_channels(hid,repo.flow_channel_count(hid),repo.flow_rework_enabled(hid))
        summary=repo.channel_summary(host_id=hid,recipient_id=rid)
        if not summary['total']:
            self.channel_summary_label.setText("生成通道：未配置 · 选择一个 AI 主播后点击“⚡ 多通道”")
            return
        parts=[]
        for ch in repo.list_flow_channels(host_id=hid,recipient_id=rid,enabled_only=True):
            age=time.time()-float(ch['last_seen'] or 0) if ch['last_seen'] else 999
            icon='🟢' if age<8 else '⚪'
            role='返工' if ch['role']=='rework' else '生产'
            parts.append(f"{ch['channel_key']} {icon} {role} · 图片 {int(ch['images_uploaded'] or 0)}/{int(ch['images_total'] or 0)}")
        self.channel_summary_label.setText(f"生成通道：{summary['online']}/{summary['total']} 在线 · 普通 {summary['normal']} · 返工 {summary['rework']}  ｜  "+"  ｜  ".join(parts))

    def open_multi_channel_settings(self):
        hid=self.host.currentData() if hasattr(self,'host') else None
        if not hid:
            QMessageBox.information(self,"多通道设置","请先在顶部选择一个 AI 主播，再配置它的生成通道。")
            return
        name=self.host.currentText()
        if MultiChannelDialog(hid,name,self).exec():
            self.refresh_channel_summary(); self.refresh_link_table()

    def _make_channel_job(self, row, channel, tasks, preload_all_images=False):
        data=dict(row); data['flow_collection_url']=channel['collection_url'] or ''
        base=self._make_host_job(data,tasks)
        if not base: return None
        paths=[x['image_path'] for x in repo.get_host_images(row['host_id'])] if preload_all_images else multi_channel.unique_images(tasks)
        image_files,fp=multi_channel.image_payload(paths)
        base.update({
            'channel_id':int(channel['id']),'channel_key':str(channel['channel_key']),'channel_role':str(channel['role']),
            'collection_url':str(channel['collection_url'] or ''),'collection_name':f"{row['recipient_name']}-{row['host_name']}-{channel['channel_key']}",
            'image_count':len(paths),'image_files':image_files,'image_set_id':fp,'expected_image_names':[x['name'] for x in image_files],
            'upload_batches':[paths[i:i+20] for i in range(0,len(paths),20)],
            'upload_proof':{
                'verified': bool(channel['upload_state']=='verified' and str(channel['upload_fingerprint'] or '')==fp and (not paths or int(channel['images_uploaded'] or 0)>=len(paths)) and bool(channel['upload_verified_at'])),
                'host_id':int(row['host_id']),'channel_id':int(channel['id']),'image_set_id':str(channel['upload_fingerprint'] or ''),
                'collection_url':str(channel['collection_url'] or ''),'upload_command_id':str(channel['upload_command_id'] or ''),
                'uploaded':int(channel['images_uploaded'] or 0),'verified_at':str(channel['upload_verified_at'] or '')
            },
            'studio_upload_state':str(channel['upload_state'] or 'idle'),'studio_upload_fingerprint':str(channel['upload_fingerprint'] or '')
        })
        return base

    def _multi_host_rows(self):
        rows=list(repo.list_flow_host_links(self.recipient.currentData(), work_date=work_dates.active()))
        return [r for r in rows if repo.flow_channel_count(r['host_id'])>1 or repo.flow_rework_enabled(r['host_id'])]

    @production_ui_action
    def upload_multi_channel_images(self, rows):
        jobs=[]; missing=[]; skipped=[]; stamp=str(int(time.time()*1000))
        redo=workflow.redo_ids(work_date=work_dates.active())
        for row in rows:
            channels=multi_channel.ensure_for_host(row['host_id']); normals=[c for c in channels if c['role']=='normal']; r1=next((c for c in channels if c['role']=='rework'),None)
            tasks=[t for t in repo.list_flow_tasks(host_id=row['host_id'], work_date=work_dates.active()) if t['segment_id'] not in redo]
            plan=multi_channel.distribute(tasks,normals)
            targets=[(c,plan.get(int(c['id']),[]),False) for c in normals]
            if r1: targets.append((r1,tasks,True))
            for ch,ctasks,preload in targets:
                if not (ch['collection_url'] or '').strip(): missing.append(f"{row['host_name']}/{ch['channel_key']}"); continue
                if not ctasks and not preload: continue
                job=self._make_channel_job(row,ch,ctasks,preload_all_images=preload)
                fp=job['image_set_id']; total=job['image_count']
                if ch['upload_state']=='verified' and str(ch['upload_fingerprint'] or '')==fp and (not total or int(ch['images_uploaded'] or 0)>=total): skipped.append(f"{row['host_name']}/{ch['channel_key']}"); continue
                cmd=f"upload-{row['host_id']}-{ch['channel_key']}-{stamp}"
                job.update(command_id=cmd,open_window=False,execute_upload=True,dispatch_tasks=False,auto_execute=False)
                repo.set_flow_channel_runtime(ch['id'],'queued',command_id=cmd,fingerprint=fp,uploaded=0,total=total,error='')
                jobs.append(job)
        if jobs:
            ver=self.bridge.publish_host_jobs(jobs)
            QMessageBox.information(self,"多通道上传",f"已向 {len(jobs)} 个通道发送图片准备任务。\nBridge版本：{ver}\nR1 会预载该主播全部参考图，方便质检退回后快速重做。")
        elif skipped:
            QMessageBox.information(self,"多通道上传","所有已配置通道的图片都已验证，无需重复上传。")
        if missing: QMessageBox.warning(self,"通道缺少链接","以下通道未执行：\n"+"\n".join(missing[:20]))
        self.refresh_channel_summary()

    @production_ui_action
    def generate_multi_channel(self, rows):
        jobs=[]; missing=[]; not_ready=[]; stamp=str(int(time.time()*1000)); redo=workflow.redo_ids(work_date=work_dates.active())
        for row in rows:
            normals=multi_channel.normal_channels(row['host_id'])
            tasks=[t for t in repo.list_flow_tasks(host_id=row['host_id'], work_date=work_dates.active()) if t['flow_status'] in ('待生成','已准备') and t['segment_id'] not in redo]
            plan=multi_channel.distribute(tasks,normals)
            for ch in normals:
                ctasks=plan.get(int(ch['id']),[])
                if not ctasks: continue
                if not (ch['collection_url'] or '').strip(): missing.append(f"{row['host_name']}/{ch['channel_key']}"); continue
                job=self._make_channel_job(row,ch,ctasks)
                if not job['upload_proof']['verified']:
                    not_ready.append(f"{row['host_name']}/{ch['channel_key']} 图片 {int(ch['images_uploaded'] or 0)}/{job['image_count']}"); continue
                cmd=f"generate-{row['host_id']}-{ch['channel_key']}-{stamp}"
                job.update(command_id=cmd,open_window=False,execute_upload=False,dispatch_tasks=True,auto_execute=True)
                repo.set_flow_channel_task_command(ch['id'],cmd)
                for t in ctasks: repo.assign_flow_channel(t['segment_id'],ch['channel_key'])
                jobs.append(job)
        if not jobs:
            detail="没有可启动的多通道任务。"
            if not_ready: detail+="\n尚未完成图片验证："+"、".join(not_ready[:12])
            if missing: detail+="\n缺少集合链接："+"、".join(missing[:12])
            QMessageBox.warning(self,"多通道生成",detail); return
        ver=self.bridge.publish_host_jobs(jobs)
        QMessageBox.information(self,"多通道生成",f"已启动 {len(jobs)} 个并行生产通道，共分配 {sum(len(j['tasks']) for j in jobs)} 个片段。\nBridge版本：{ver}")
        self.reload_tasks()

    def _cell_check(self,row):
        cell = self.table.cellWidget(row,0)
        return cell if isinstance(cell,CheckCell) else None

    def on_row_check_changed(self,sid,checked):
        if checked:
            self.checked_ids.add(sid)
        else:
            self.checked_ids.discard(sid)
        self.update_header_check()
        self.refresh_stats()

    def update_header_check(self):
        ids = [t["segment_id"] for t in self.task_rows]
        all_checked = bool(ids) and all(x in self.checked_ids for x in ids)
        self.table.horizontalHeaderItem(0).setText("☑" if all_checked else "☐")

    def header_clicked(self,section):
        if section != 0:
            return
        ids = [t["segment_id"] for t in self.task_rows]
        target = not (bool(ids) and all(x in self.checked_ids for x in ids))
        for row,t in enumerate(self.task_rows):
            cell = self._cell_check(row)
            if cell:
                cell.setChecked(target,block=True)
            if target:
                self.checked_ids.add(t["segment_id"])
            else:
                self.checked_ids.discard(t["segment_id"])
        self.update_header_check()
        self.refresh_stats()

    def start_fill_drag(self,row,state):
        self._fill_source_row=row
        self._fill_target_state=bool(state)

    def update_fill_drag(self,global_pos):
        if self._fill_source_row is None:
            return
        p=self.table.viewport().mapFromGlobal(global_pos)
        target=self.table.rowAt(p.y())
        if target < 0:
            target=0 if p.y()<0 else self.table.rowCount()-1
        lo=min(self._fill_source_row,target)
        hi=max(self._fill_source_row,target)
        for row in range(lo,hi+1):
            if row>=len(self.task_rows):
                continue
            sid=self.task_rows[row]["segment_id"]
            cell=self._cell_check(row)
            if cell:
                cell.setChecked(self._fill_target_state,block=True)
            if self._fill_target_state:
                self.checked_ids.add(sid)
            else:
                self.checked_ids.discard(sid)
        self.update_header_check()
        self.refresh_stats()

    def finish_fill_drag(self):
        self._fill_source_row=None
        self._fill_target_state=None

    def selected_ids(self):
        return sorted(self.checked_ids)

    def selected_tasks(self):
        ids = set(self.selected_ids())
        return [t for t in repo.list_flow_tasks(work_date=work_dates.active()) if t['segment_id'] in ids]

    def require_selected(self):
        tasks=self.selected_tasks()
        if not tasks:
            QMessageBox.information(self,"Flow任务","请先选择任务。")
            return []
        return tasks

    def _today_project_name(self, row):
        # One Flow project per work date; all recipients/hosts for that day go inside it.
        work_date = str(row["work_date"] or "").strip()
        return f"{work_date}-Flow Studio" if work_date else "Flow Studio"

    def _collection_name(self, row, ordinal):
        # Include recipient + host to avoid collisions between same-named hosts.
        return f"{ordinal:02d}-{row['recipient_name']}-{row['host_name']}"

    def refresh_prep_table(self):
        rid = self.recipient.currentData()
        rows = list(repo.get_flow_prep_rows(rid, work_date=work_dates.active()))
        self.prep_table.setRowCount(len(rows))

        for idx, row in enumerate(rows, start=1):
            project = row["flow_project_name"] or self._today_project_name(row)
            collection = row["flow_collection_name"] or self._collection_name(row, idx)
            images = f'{int(row["flow_images_uploaded"] or 0)}/{int(row["image_count"] or 0)}'
            window = row["flow_window_key"] or "未打开"
            status = row["flow_prep_status"] or "未准备"

            vals = [
                row["recipient_name"], row["host_name"], project,
                collection, images, window, status
            ]
            for col, value in enumerate(vals):
                self.prep_table.setItem(idx-1, col, QTableWidgetItem(str(value)))

    @production_ui_action
    def prepare_today_project(self):
        """
        Publish a deterministic preparation plan to the Bridge and open one separate
        Chrome app-window per collection.

        V0.8 test scope:
        - project/collection naming
        - correct host/image grouping
        - 20-image chunk plan
        - separate-window launch
        - bridge delivery
        The extension receives explicit 'refresh only after all uploads' instructions.
        """
        rid = self.recipient.currentData()
        rows = list(repo.get_flow_prep_rows(rid))
        if not rows:
            QMessageBox.information(self, "Flow 项目准备", "当前没有 AI 主播可以准备。")
            return

        profile = repo.get_setting("chrome_profile_directory", "Default") or "Default"
        flow_url = repo.get_setting("flow_url", DEFAULT_FLOW_URL) or DEFAULT_FLOW_URL

        jobs = []
        for ordinal, row in enumerate(rows, start=1):
            project_name = row["flow_project_name"] or self._today_project_name(row)
            collection_name = row["flow_collection_name"] or self._collection_name(row, ordinal)

            repo.set_recipient_flow_project_name(row["recipient_id"], project_name)
            repo.set_host_flow_collection(row["host_id"], collection_name)

            images = list(repo.get_host_images(row["host_id"]))
            image_paths = [img["image_path"] for img in images if (img["image_path"] or "").strip()]

            # Strict maximum 20 images per upload batch.
            upload_batches = [
                image_paths[i:i+20]
                for i in range(0, len(image_paths), 20)
            ]

            window_key = f"host-{row['host_id']}"
            repo.set_host_flow_prep(
                row["host_id"],
                "等待浏览器",
                uploaded=0,
                total=len(image_paths),
                window_key=window_key
            )

            jobs.append({
                "recipient_id": int(row["recipient_id"]),
                "host_id": int(row["host_id"]),
                "recipient_name": row["recipient_name"],
                "host_name": row["host_name"],
                "project_name": project_name,
                "collection_name": collection_name,
                "window_key": window_key,
                "chrome_profile": profile,
                "flow_url": flow_url,
                "image_count": len(image_paths),
                "upload_batches": upload_batches,
                "max_upload_batch": 20,
                "refresh_policy": "after_all_images_uploaded",
                "refresh_once": True,
                "wait_for_plugin_auto_recognition_after_refresh": True,
                "preserve_original_plugin_collection_download_logic": True,
            })

        # V0.9: publish one plan; the modified ORIGINAL plugin controls browser windows.
        # It creates exactly one Flow project first, then opens one normal Chrome
        # window per AI host/collection, all pointing at that same project URL.
        version = self.bridge.publish_prep_jobs(jobs)

        try:
            # Wake the chosen Chrome Profile so the modified original plugin can connect.
            chrome_profiles.launch_flow(profile, flow_url)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Flow 项目准备",
                f"任务已经发布，但启动指定 Chrome Profile 失败：\\n{exc}"
            )
            return

        for job in jobs:
            repo.set_host_flow_prep(
                job["host_id"],
                "等待网页插件接管",
                uploaded=0,
                total=job["image_count"],
                window_key=job["window_key"]
            )

        self.refresh_link_table()

        total_images = sum(job["image_count"] for job in jobs)
        total_batches = sum(len(job["upload_batches"]) for job in jobs)
        QMessageBox.information(
            self,
            "Flow 自动准备已启动",
            f"AI主播/集合：{len(jobs)} 个\\n"
            f"图片：{total_images} 张\\n"
            f"上传批次：{total_batches} 个（每批最多20张）\\n"
            f"Bridge版本：{version}\\n\\n"
            "这版由修改后的网页生成引擎直接接管 Flow 页面。\\n"
            "只创建1个当天项目；项目创建成功后，每个AI主播建立独立Chrome窗口，"
            "所有窗口进入同一个项目，再分别创建自己的集合。"
        )

    def refresh_live_connection_states(self):
        if not hasattr(self, "link_rows"):
            return
        now=time.monotonic()
        last_seen_map=getattr(self, "host_last_seen", {})
        changed=False
        for i,row in enumerate(self.link_rows):
            hid=int(row["host_id"])
            online=(now-last_seen_map.get(hid,0)) < 8.0
            snap={}
            try:
                snap=self.bridge.web_plugin_state(hid) or {}
                snap_age=time.time()-float(snap.get("last_seen") or 0) if snap else 999
                online=online or snap_age < 8.0
            except Exception:
                snap={}

            # READY self-heal: do not depend on one transient media_ready event.
            # A fresh heartbeat can restore readiness only when it belongs to the
            # exact current image set and the browser reports every image present.
            try:
                if snap and bool(snap.get("ready")):
                    current_job=self._make_host_job(row)
                    current_fp=str(current_job.get("image_set_id") or "") if current_job else ""
                    snap_fp=str(snap.get("image_set_id") or "")
                    recognized=int(snap.get("recognized") or snap.get("image_recognized") or 0)
                    total=int(snap.get("total") or snap.get("image_total") or 0)
                    task_matched=int(snap.get("task_matched") or 0)
                    task_total=int(snap.get("task_total") or 0)
                    if current_fp and snap_fp==current_fp and total>0 and recognized>=total and (not task_total or task_matched>=task_total):
                        runtime=repo.get_host_upload_runtime(hid)
                        already=(runtime and str(runtime["flow_upload_state"] or "")=="verified" and str(runtime["flow_upload_fingerprint"] or "")==current_fp and int(runtime["flow_images_uploaded"] or 0)>=total)
                        if not already:
                            repo.set_host_upload_runtime(
                                hid,"verified",
                                command_id=str(snap.get("command_id") or (runtime["flow_upload_command_id"] if runtime else "")),
                                fingerprint=current_fp,uploaded=total,total=total,
                                status="🟢 准备完成",error="",verified=True
                            )
                            repo.set_host_flow_prep(hid,"🟢 准备完成",uploaded=total,total=total)
                            changed=True
            except Exception:
                pass

            item=self.link_table.item(i,5)
            if item is None:
                item=QTableWidgetItem()
                self.link_table.setItem(i,5,item)
            item.setText("🟢 已连接" if online else "🔴 未连接")

        if changed:
            self.refresh_link_table()

    def _submit_channel_telemetry(self,event):
        if event.get('type') not in ('web_plugin_heartbeat','web_plugin_progress_snapshot'):
            self.telemetry_executor.submit(channel_pool.record_event,dict(event));return
        if not hasattr(self,'_pending_telemetry'):self._pending_telemetry={}
        self._pending_telemetry[(event.get('channel_id'),event.get('type'))]=dict(event)
        future=getattr(self,'_telemetry_batch_future',None)
        if future is not None and not future.done():return
        batch=list(self._pending_telemetry.values());self._pending_telemetry.clear()
        def write_batch():
            for row in batch:channel_pool.record_event(row)
        self._telemetry_batch_future=self.telemetry_executor.submit(write_batch)

    @measured('plugin_message')
    def process_bridge_events(self):
        events = self.bridge.pop_events()
        if not events:
            return
        changed = False
        task_changed = False
        for event in events:
            if event.get("type")=="channel_focus_failed":
                QMessageBox.information(self,"定位通道",str(event.get("message") or "未能定位原标签页，请刷新通道后重试。"))
            etype = event.get("type")
            host_id = event.get("host_id")
            raw_channel_id = event.get("channel_id")
            channel_id = 0
            try:
                channel_id = int(raw_channel_id or 0)
            except (TypeError, ValueError):
                raw_key = str(raw_channel_id or "").strip().upper()
                if raw_key:
                    match = next((c for c in repo.list_channel_pool(enabled_only=False) if str(c["channel_key"] or "").strip().upper() == raw_key), None)
                    if match:
                        channel_id = int(match["id"])
                if not channel_id:
                    runtime_log.log("bridge_event_channel_id_normalized_failed", level="WARNING", raw_channel_id=str(raw_channel_id or ""), channel_key=str(event.get("channel_key") or ""), event_type=str(event.get("type") or ""))
            if channel_id:
                # Channel telemetry is useful, but it must never block the Qt event loop.
                # Serialize it in one background worker; the durable workflow receipt was
                # already committed by the HTTP bridge before this UI event arrives.
                try:
                    self._submit_channel_telemetry(event)
                    changed = changed or etype not in ('web_plugin_heartbeat','web_plugin_progress_snapshot')
                except Exception as exc:
                    runtime_log.log('channel_runtime_write_deferred',level='WARNING',error=str(exc)[:180],channel_id=channel_id)
            # Pool jobs intentionally use host_id=0.  Previously these events were skipped
            # before the UI could kick the dispatcher, so refill depended solely on the next
            # timer tick. Trigger a coalesced immediate refill whenever a pool wave finishes
            # or an authenticated channel reports itself idle.
            if etype=='generation_batch_finished' or (etype=='web_plugin_heartbeat' and bool(event.get('idle_channel'))):
                if not bool(getattr(self,'_auto_refill_kick_pending',False)):
                    self._auto_refill_kick_pending=True
                    def _kick_auto_refill():
                        self._auto_refill_kick_pending=False
                        self.auto_dispatch_tick()
                    QTimer.singleShot(120,_kick_auto_refill)
                if etype=='generation_batch_finished' and int(event.get('deferred') or 0)==0:
                    # Completion, workflow receipts and Bridge retirement are delivered by
                    # separate threads.  A short follow-up sweep closes that tiny race and
                    # guarantees a freshly freed channel is offered the next waiting wave.
                    QTimer.singleShot(900,self.auto_dispatch_tick)
                    QTimer.singleShot(2400,self.auto_dispatch_tick)
            if not host_id:
                continue

            host_id=int(host_id)
            if etype in workflow.EVENTS:
                # The HTTP handler committed this receipt before acknowledging it.
                task_changed = True
                continue
            if etype in {"generation_batch_finished", "generation_paused"}:
                if channel_id:
                    if str(event.get("command_id")) == str(repo.get_flow_channel_task_command(channel_id)):
                        repo.set_flow_channel_task_command(channel_id, "")
                elif str(event.get("command_id")) == str(repo.get_host_task_command(host_id)):
                    self.active_task_commands.pop(host_id, None); repo.set_host_task_command(host_id, "")
                repo.set_host_flow_prep(host_id, "提交结束 · 等待渲染下载" if etype=="generation_batch_finished" else "提交暂停")
                changed = True
                continue

            # Upload events are command-scoped. A delayed event from an older upload
            # command must never mutate the current host state or create a false success.
            strict_upload_events={
                "upload_precheck","upload_drag_attempt","upload_flow_progress",
                "upload_flow_verified","upload_refresh_started","upload_post_refresh_check",
                "upload_verified","upload_retry","upload_stopped","upload_verification_failed",
                "upload_existing_unverified",
                "media_match_progress","media_ready","media_upload_started",
                "media_upload_dispatched","media_upload_dispatch_failed","media_upload_stopped"
            }
            if etype in strict_upload_events:
                runtime=repo.get_flow_channel(channel_id) if channel_id else repo.get_host_upload_runtime(host_id)
                active_cmd=str(runtime["upload_command_id"] or "") if (channel_id and runtime) else (str(runtime["flow_upload_command_id"] or "") if runtime else "")
                event_cmd=str(event.get("command_id") or "")
                active_fp=str(runtime["upload_fingerprint"] or "") if (channel_id and runtime) else (str(runtime["flow_upload_fingerprint"] or "") if runtime else "")
                event_fp=str(event.get("image_set_id") or "")
                # Upload workflow events are accepted only with BOTH exact IDs.
                # Missing IDs are treated as untrusted rather than loosely accepted.
                if (not event_cmd or not active_cmd or event_cmd!=active_cmd or
                        not event_fp or not active_fp or event_fp!=active_fp):
                    if self.flow_monitor:
                        self.flow_monitor.append_log(
                            f"主播 #{host_id}：忽略过期上传事件 {etype} · {event_cmd or '无command_id'}"
                        )
                    continue

            strict_task_events={
                "plugin_media_sync_waiting","original_plugin_media_load_triggered",
                "plugin_media_synced","plugin_media_sync_failed",
                "task_adapter_waiting_upload_proof","task_adapter_waiting_media_sync","task_adapter_started",
                "task_adapter_waiting_media","task_adapter_writing",
                "task_adapter_written","task_adapter_failed",
                "generation_auto_started","generation_task_status",
                "generation_progress","generation_batch_finished"
            }
            if etype in strict_task_events:
                # Keep the gate persistent across a Studio restart. In-memory state
                # is only a cache; the DB command id is the authority.
                active_cmd=str(repo.get_host_task_command(host_id) or "")
                event_cmd=str(event.get("command_id") or "")
                if not active_cmd or not event_cmd or event_cmd!=active_cmd:
                    if self.flow_monitor:
                        self.flow_monitor.append_log(
                            f"主播 #{host_id}：忽略旧生成事件 {etype} · {event_cmd}"
                        )
                    continue

            if etype in ("host_heartbeat","host_page_bound","web_plugin_bound","web_plugin_heartbeat","web_plugin_tasks_received"):
                self.host_last_seen[host_id]=time.monotonic()
                # Heartbeat itself is also a durable READY signal. This recovers
                # from a lost one-shot media_ready delivery after MV3 worker sleep.
                if etype=="web_plugin_heartbeat" and bool(event.get("ready")):
                    try:
                        row_now=next((r for r in repo.list_flow_host_links(self.recipient.currentData(), work_date=work_dates.active()) if int(r["host_id"])==host_id),None)
                        current_job=self._make_host_job(row_now) if row_now else None
                        current_fp=str(current_job.get("image_set_id") or "") if current_job else ""
                        event_fp=str(event.get("image_set_id") or "")
                        recognized=int(event.get("recognized") or event.get("image_recognized") or 0)
                        total=int(event.get("total") or event.get("image_total") or 0)
                        task_matched=int(event.get("task_matched") or 0)
                        task_total=int(event.get("task_total") or 0)
                        if current_fp and event_fp==current_fp and total>0 and recognized>=total and (not task_total or task_matched>=task_total):
                            repo.set_host_upload_runtime(
                                host_id,"verified",command_id=str(event.get("command_id") or ""),
                                fingerprint=current_fp,uploaded=total,total=total,
                                status="🟢 准备完成",error="",verified=True
                            )
                            repo.set_host_flow_prep(host_id,"🟢 准备完成",uploaded=total,total=total)
                    except Exception:
                        pass
                changed=True
                if self.flow_monitor:
                    # Connection events must never overwrite upload/task workflow text.
                    self.flow_monitor.update_host(host_id, connection="🟢 已连接")
                    if etype in ("host_page_bound","web_plugin_bound"):
                        self.flow_monitor.append_log(
                            f'{event.get("host_name","主播")}：网页执行器已连接'
                        )

            if etype == "prep_started":
                repo.set_host_flow_prep(
                    host_id,
                    f'窗口已绑定 #{event.get("window_id","")}'
                )
                changed = True
            elif etype == "project_created":
                repo.set_host_flow_prep(host_id, "当天项目已创建，正在分配集合窗口")
                changed = True
            elif etype == "collection_created":
                repo.set_host_flow_prep(host_id, "集合已创建，准备上传")
                changed = True
            elif etype == "media_match_progress":
                recognized=int(event.get("recognized") or 0)
                total=int(event.get("total") or 0)
                # 新网页插件的扫描进度只用于内部/监控展示；主表仍保持红色“未准备”，
                # 直到 media_ready 最终回执到达，避免中间状态造成误判。
                repo.set_host_upload_runtime(
                    host_id,"uploading",total=total,
                    status=f"网页插件正在匹配集合图片 {recognized}/{total}"
                )
                if self.flow_monitor:
                    self.flow_monitor.update_host(host_id,uploaded=recognized,step=f"网页插件匹配集合图片 {recognized}/{total}",connection="🟢 已连接")
                changed=True
            elif etype == "media_ready":
                recognized=int(event.get("recognized") or 0)
                total=int(event.get("total") or 0)
                task_matched=int(event.get("task_matched") or 0)
                task_total=int(event.get("task_total") or 0)
                if total <= 0 or recognized < total:
                    if self.flow_monitor:
                        self.flow_monitor.append_log(f"主播 #{host_id}：忽略不完整 READY 回执 {recognized}/{total}")
                    continue
                repo.set_host_upload_runtime(
                    host_id,"verified",command_id=str(event.get("command_id") or ""),
                    fingerprint=str(event.get("image_set_id") or ""),uploaded=total,total=total,
                    status="🟢 准备完成",error="",verified=True
                )
                repo.set_host_flow_prep(host_id,"🟢 准备完成",uploaded=total,total=total)
                if self.flow_monitor:
                    self.flow_monitor.update_host(host_id,uploaded=total,step=f"🟢 READY · 图片 {total}/{total} · 任务 {task_matched}/{task_total}",connection="🟢 已连接")
                    self.flow_monitor.append_log(f"主播 #{host_id}：网页插件 READY 回执已接收，生成按钮已解锁")
                changed=True
            elif etype == "upload_precheck":
                matched=int(event.get("matched") or 0)
                total=int(event.get("total") or 0)
                repo.set_host_upload_runtime(
                    host_id,"precheck",total=total,
                    status=f"上传前检查 {matched}/{total}",error=""
                )
                if self.flow_monitor:
                    self.flow_monitor.update_host(
                        host_id,uploaded=matched,step=f"上传前检查 · 已存在 {matched}/{total}",connection="🟢 已连接"
                    )
                changed=True
            elif etype == "upload_drag_attempt":
                attempt=int(event.get("attempt") or 1)
                missing=int(event.get("missing") or 0)
                matched=int(event.get("matched") or 0)
                total=int(event.get("total") or 0)
                repo.set_host_upload_runtime(
                    host_id,"uploading",total=total,
                    status=f"正在上传 · 第 {attempt}/3 次 · 缺少 {missing} 张"
                )
                if self.flow_monitor:
                    self.flow_monitor.update_host(
                        host_id,uploaded=matched,step=f"第 {attempt}/3 次上传 · 只补传缺失 {missing} 张",connection="🟢 已连接"
                    )
                changed=True
            elif etype == "upload_flow_progress":
                matched=int(event.get("matched") or 0)
                total=int(event.get("total") or 0)
                repo.set_host_upload_runtime(
                    host_id,"uploading",total=total,
                    status=f"等待 Flow 完成上传 {matched}/{total}"
                )
                if self.flow_monitor:
                    self.flow_monitor.update_host(host_id,uploaded=matched,step=f"Flow 正在确认文件 {matched}/{total}")
                changed=True
            elif etype == "upload_retry":
                attempt=int(event.get("attempt") or 1)
                missing=int(event.get("missing") or 0)
                repo.set_host_upload_runtime(
                    host_id,"uploading",status=f"上传校验未完成 · 准备第 {attempt+1}/3 次，仅补传 {missing} 张",
                    error=str(event.get("error") or "")
                )
                if self.flow_monitor:
                    self.flow_monitor.update_host(host_id,step=f"校验未完成 · 下一次只补传缺失 {missing} 张")
                changed=True
            elif etype == "upload_flow_verified":
                total=int(event.get("total") or 0)
                # This is NOT the final success receipt. It only means the exact
                # expected filenames are present and stable before the one refresh.
                repo.set_host_upload_runtime(
                    host_id,"flow_verified",total=total,
                    status="Flow 已确认全部图片，准备刷新验证"
                )
                if self.flow_monitor:
                    self.flow_monitor.update_host(host_id,uploaded=total,step="Flow 已确认全部指定文件 · 准备唯一一次刷新")
                changed=True
            elif etype == "upload_refresh_started":
                total=int(event.get("total") or 0)
                # V0.12.22: upload_verified is final. Refresh is only needed so the
                # original batch engine can reload the newly uploaded media; it must
                # never downgrade the verified upload state.
                repo.set_host_upload_runtime(
                    host_id,"verified",total=total,
                    status="✅ 图片已验证 · 正在刷新 Flow 以加载素材",verified=True
                )
                if self.flow_monitor:
                    self.flow_monitor.update_host(host_id,uploaded=total,step="✅ 图片已验证 · 正在刷新 Flow",connection="🟢 已连接")
                    self.flow_monitor.append_log(f"主播 #{host_id}：图片已稳定验证，执行一次刷新；刷新后不再二次验证图片")
                changed=True
            elif etype == "upload_post_refresh_check":
                matched=int(event.get("matched") or 0)
                total=int(event.get("total") or 0)
                repo.set_host_upload_runtime(
                    host_id,"post_refresh",total=total,
                    status=f"刷新后验证图片 {matched}/{total}"
                )
                if self.flow_monitor:
                    self.flow_monitor.update_host(host_id,uploaded=matched,step=f"刷新后重新核对指定文件 {matched}/{total}",connection="🟢 已连接")
                changed=True
            elif etype == "upload_verified":
                total=int(event.get("total") or 0)
                repo.set_host_upload_runtime(
                    host_id,"verified",command_id=str(event.get("command_id") or ""),
                    fingerprint=str(event.get("image_set_id") or ""),uploaded=total,total=total,
                    status="✅ 图片上传已验证，可以开始批量生成",error="",verified=True
                )
                if self.flow_monitor:
                    self.flow_monitor.update_host(host_id,uploaded=total,step="✅ 图片上传已验证 · 可以开始批量生成",connection="🟢 已连接")
                    self.flow_monitor.append_log(
                        f"主播 #{host_id}：全部 {total} 个指定文件已稳定通过，上传确认成功"
                    )
                changed=True
            elif etype == "upload_existing_unverified":
                matched=int(event.get("matched") or 0)
                total=int(event.get("total") or 0)
                error=str(event.get("error") or "当前集合存在未验证的同名图片")
                repo.set_host_upload_runtime(
                    host_id,"blocked_existing",total=total,
                    status=f"⚠ 存在未验证同名图片 {matched}/{total}",error=error
                )
                if self.flow_monitor:
                    self.flow_monitor.update_host(
                        host_id,step=f"⚠ 检测到未验证同名图片 {matched}/{total} · 已停止，不会刷新或重复上传"
                    )
                    self.flow_monitor.append_log(f"主播 #{host_id}：{error[:180]}")
                changed=True
            elif etype in ("upload_stopped","upload_verification_failed"):
                error=str(event.get("error") or "上传验证失败")
                matched=int(event.get("matched") or 0)
                total=int(event.get("total") or 0)
                attempts=int(event.get("attempts") or 3)
                repo.set_host_upload_runtime(
                    host_id,"failed",total=total,
                    status=f"⛔ 上传未通过验证 · {matched}/{total}",error=error
                )
                if self.flow_monitor:
                    self.flow_monitor.update_host(host_id,uploaded=matched,step=f"⛔ 上传停止 · {matched}/{total} · {error[:80]}")
                    self.flow_monitor.append_log(f"主播 #{host_id}：上传流程停止（{attempts}/3）· {error[:180]}")
                changed=True
            elif etype == "host_wrong_url":
                repo.set_host_flow_prep(host_id, "集合链接不匹配")
                changed = True
            elif etype == "plugin_media_sync_waiting":
                recognized=int(event.get("recognized") or 0)
                required=int(event.get("required") or 0)
                attempt=int(event.get("attempt") or 0)
                repo.set_host_flow_prep(host_id, f"同步网页生成素材 {recognized}/{required} · {attempt}/3")
                if self.flow_monitor:
                    self.flow_monitor.update_host(host_id,step=f"同步网页生成素材 {recognized}/{required} · 第 {attempt}/3 次",connection="🟢 已连接")
                changed=True
            elif etype == "original_plugin_media_load_triggered":
                attempt=int(event.get("attempt") or 1)
                repo.set_host_flow_prep(host_id, f"网页插件正在同步图片 · {attempt}/3")
                if self.flow_monitor:
                    self.flow_monitor.update_host(host_id,step=f"已触发网页插件图片同步 · 第 {attempt}/3 次")
                changed=True
            elif etype == "plugin_media_synced":
                recognized=int(event.get("recognized") or 0)
                required=int(event.get("required") or 0)
                repo.set_host_flow_prep(host_id, f"网页生成素材已就绪 {recognized}/{required}")
                if self.flow_monitor:
                    self.flow_monitor.update_host(host_id,step=f"✅ 网页生成素材已就绪 {recognized}/{required}",connection="🟢 已连接")
                changed=True
            elif etype == "plugin_media_sync_failed":
                recognized=int(event.get("recognized") or 0)
                required=int(event.get("required") or 0)
                error=str(event.get("error") or "网页生成素材同步失败")
                repo.set_host_flow_prep(host_id, f"插件素材同步失败 {recognized}/{required}")
                if self.flow_monitor:
                    self.flow_monitor.update_host(host_id,step=f"⛔ 网页生成素材同步失败 {recognized}/{required}")
                    self.flow_monitor.append_log(f"主播 #{host_id}：{error[:180]}")
                changed=True
            elif etype == "task_adapter_waiting_upload_proof":
                error=str(event.get("error") or "缺少图片最终验证凭证")
                repo.set_host_flow_prep(host_id, "等待图片最终验证凭证")
                if self.flow_monitor:
                    self.flow_monitor.update_host(host_id,step="⛔ 任务未写入 · 等待图片最终验证凭证",connection="🟢 已连接")
                    self.flow_monitor.append_log(f"主播 #{host_id}：生成任务被门禁阻止 · {error[:180]}")
                changed=True
            elif etype == "task_adapter_waiting_media_sync":
                error=str(event.get("error") or "网页生成引擎尚未完成当前命令的素材同步")
                repo.set_host_flow_prep(host_id, "等待网页生成素材同步凭证")
                if self.flow_monitor:
                    self.flow_monitor.update_host(host_id,step="等待网页插件完成图片同步并核对素材",connection="🟢 已连接")
                    self.flow_monitor.append_log(f"主播 #{host_id}：任务写入门禁等待素材同步 · {error[:180]}")
                changed=True
            elif etype == "task_adapter_started":
                repo.set_host_flow_prep(host_id, "准备写入插件任务 · 等待素材")
                if self.flow_monitor:
                    self.flow_monitor.update_host(host_id,step="任务已送达 Bridge · 先核对网页生成素材",connection="🟢 已连接")
                changed=True
            elif etype == "task_adapter_waiting_media":
                repo.set_host_flow_prep(host_id, "等待网页插件识别素材")
                if self.flow_monitor:
                    self.flow_monitor.update_host(
                        host_id,
                        step="等待网页生成引擎识别当前集合素材",
                        connection="🟢 已连接"
                    )
                changed = True
            elif etype == "task_adapter_writing":
                repo.set_host_flow_prep(host_id, "正在写入插件任务")
                if self.flow_monitor:
                    self.flow_monitor.update_host(
                        host_id,
                        step=f'正在写入网页生成任务 · {int(event.get("task_count") or 0)} 个',
                        connection="🟢 已连接"
                    )
                changed = True
            elif etype == "task_adapter_written":
                expected=int(event.get("expected") or 0)
                actual=int(event.get("actual") or 0)
                mode=event.get("mode_label") or "素材"
                repo.set_host_flow_prep(
                    host_id,
                    f"任务已送达 {actual}/{expected} · {mode}"
                )
                if self.flow_monitor:
                    self.flow_monitor.update_host(
                        host_id,
                        step=f"网页生成任务已接收 {actual}/{expected} · {mode}",
                        connection="🟢 已连接"
                    )
                    self.flow_monitor.append_log(
                        f"主播 #{host_id}：网页生成引擎回读确认 {actual}/{expected} 个任务"
                    )
                changed = True
            elif etype == "task_adapter_failed":
                repo.set_host_flow_prep(host_id, "插件任务写入失败：" + str(event.get("error") or "未知原因"))
                if self.flow_monitor:
                    self.flow_monitor.update_host(
                        host_id,
                        step="任务写入失败：" + str(event.get("error") or "")[:80]
                    )
                changed = True
            elif etype == "studio_queue_received":
                # Informational compatibility receipt; host-routed jobs carry the real execution.
                changed = True
            elif etype == "generation_start_requested":
                attempt=int(event.get("attempt") or 1)
                repo.set_host_flow_prep(host_id, f"正在启动生成 · {attempt}/3")
                if self.flow_monitor:
                    self.flow_monitor.update_host(host_id, step=f"正在启动 Flow 生成 · 第 {attempt}/3 次")
                changed=True
            elif etype == "generation_start_retry":
                attempt=int(event.get("attempt") or 1)
                repo.set_host_flow_prep(host_id, f"启动未确认 · 准备重试 {attempt}/3")
                if self.flow_monitor:
                    self.flow_monitor.update_host(host_id, step=f"启动未确认，准备重试 · {attempt}/3")
                changed=True
            elif etype == "generation_start_failed":
                repo.set_host_flow_prep(host_id, "生成启动失败")
                if self.flow_monitor:
                    self.flow_monitor.update_host(host_id, step="⛔ 生成启动失败 · 已停止")
                    self.flow_monitor.append_log(f"主播 #{host_id}：网页生成引擎连续 3 次未确认启动")
                changed=True
            elif etype == "generation_auto_started":
                segment_ids=[int(x) for x in (event.get("segment_ids") or []) if x]
                for sid in segment_ids:
                    repo.set_flow_task_status(sid, "已准备")
                task_changed = bool(segment_ids) or task_changed
                repo.set_host_flow_prep(host_id, "已自动开始生成")
                if self.flow_monitor:
                    self.flow_monitor.update_host(host_id, step=f'🚀 已自动开始生成 · {int(event.get("total") or len(segment_ids))} 个任务')
                    self.flow_monitor.append_log(f"主播 #{host_id}：网页插件已自动点击开始")
                changed = True
            elif etype == "generation_task_status":
                sid=int(event.get("segment_id") or 0)
                state=event.get("state") or "pending"
                message=str(event.get("message") or event.get("raw_status") or "")
                if sid:
                    task_changed = True
                    output_url=str(event.get("output_url") or "")
                    if state in ("preparing", "running", "uncertain"):
                        # Do not expose pre-click / unconfirmed browser activity as 已提交.
                        # Only the plugin's confirmed `success` receipt proves Flow accepted it.
                        repo.set_flow_task_status(sid, "已准备")
                    elif state == "success":
                        # success means Flow accepted the submission; only a completed
                        # download may move the segment to 已完成.
                        repo.set_flow_task_status(sid, "生成中")
                        if output_url:
                            repo.save_flow_output_url(sid, output_url)
                    elif state == "failed":
                        repo.set_flow_task_status(sid, "失败", message[:1000])
                changed = True
            elif etype == "generation_progress":
                total=int(event.get("total") or 0)
                success=int(event.get("success") or 0)
                failed=int(event.get("failed") or 0)
                running_count=int(event.get("running") or 0)
                pending=int(event.get("pending") or 0)
                repo.set_host_flow_prep(host_id, f"生成中 · 成功{success} 失败{failed} 进行中{running_count} 等待{pending}")
                if self.flow_monitor:
                    self.flow_monitor.update_host(host_id, step=f"生成 {success+failed}/{total} · 成功 {success} · 失败 {failed} · 进行中 {running_count}")
                changed = True
            elif etype == "generation_batch_finished":
                finished_cmd=str(event.get("command_id") or "")
                if str(repo.get_host_task_command(host_id) or "")==finished_cmd:
                    self.active_task_commands.pop(host_id,None)
                    repo.set_host_task_command(host_id, "")
                success=int(event.get("success") or 0)
                failed=int(event.get("failed") or 0)
                total=int(event.get("total") or success+failed)
                final_status=(f"生成完成 {success}/{total}" if failed==0 else f"生成结束 · 成功{success} 失败{failed}")
                repo.set_host_flow_prep(host_id, final_status)
                if self.flow_monitor:
                    self.flow_monitor.update_host(host_id, step=("✅ " if failed==0 else "⚠ ")+final_status)
                    self.flow_monitor.append_log(f"主播 #{host_id}：{final_status}")
                changed = True
            elif etype == "prep_completed":
                repo.set_host_flow_prep(
                    host_id,
                    "准备完成",
                    uploaded=int(event.get("uploaded") or 0)
                )
                changed = True
            elif etype == "prep_failed":
                attempt=int(event.get("attempt") or 0)
                will_retry=bool(event.get("will_retry"))
                error=str(event.get("error") or "")
                if will_retry:
                    repo.set_host_flow_prep(host_id, f"上传失败 {attempt}/3，等待重试")
                    step=f"上传失败 {attempt}/3 · 等待自动重试"
                elif attempt >= 3:
                    repo.set_host_flow_prep(host_id, "已停止 · 连续失败 3/3")
                    step="⛔ 连续失败 3/3，已自动停止"
                else:
                    repo.set_host_flow_prep(host_id, "准备失败")
                    step="失败：" + error[:90]
                if self.flow_monitor:
                    self.flow_monitor.update_host(host_id, step=step)
                    self.flow_monitor.append_log(
                        f"主播 #{host_id}：{step}" + (f" · {error[:140]}" if error else "")
                    )
                changed = True

        if task_changed:
            if self.isVisible():self.reload_tasks()
            if self.parent_window and hasattr(self.parent_window, 'qc_page'):
                self.parent_window.qc_page.mark_dirty()
                if self.parent_window.davinci_page.isVisible():self.parent_window.davinci_page.reload()
                if hasattr(self.parent_window, 'stats_page') and self.parent_window.stats_page.isVisible(): self.parent_window.stats_page.reload()
        elif changed and self.isVisible():
            self.refresh_link_table()

    def refresh_link_table(self):
        rows=list(repo.list_flow_host_links(self.recipient.currentData(), work_date=work_dates.active()))
        self.link_rows=rows
        self.link_table.setRowCount(len(rows))
        for i,row in enumerate(rows):
            self.link_table.setItem(i,0,QTableWidgetItem(row["recipient_name"]))
            self.link_table.setItem(i,1,QTableWidgetItem(row["host_name"]))

            edit=QLineEdit(row["flow_collection_url"] or "")
            edit.setPlaceholderText("粘贴这个主播的 Flow 集合链接")
            edit.setMinimumHeight(36)
            edit.setContentsMargins(6,0,6,0)
            edit.editingFinished.connect(
                lambda idx=i: self._autosave_flow_link(idx)
            )
            self.link_table.setCellWidget(i,2,edit)

            self.link_table.setItem(i,3,QTableWidgetItem(
                f'{int(row["flow_images_uploaded"] or 0)}/{int(row["image_count"] or 0)}'
            ))
            upload_state=str(row["flow_upload_state"] or "idle")
            uploaded=int(row["flow_images_uploaded"] or 0)
            total_images=int(row["image_count"] or 0)
            current_job=self._make_host_job(row)
            current_fp=current_job["image_set_id"] if current_job else ""
            ready=(upload_state=="verified" and str(row["flow_upload_fingerprint"] or "")==current_fp and (not total_images or uploaded>=total_images))
            is_multi=repo.flow_channel_count(row["host_id"])>1 or repo.flow_rework_enabled(row["host_id"])
            if is_multi:
                channels=multi_channel.ensure_for_host(row["host_id"]); normals=[c for c in channels if c["role"]=="normal"]
                multi_ready=bool(normals) and all(c["upload_state"]=="verified" for c in normals)
                ready=multi_ready
                prep_text=f"⚡ {len(normals)}通道 · "+("🟢 已准备" if multi_ready else "🟠 待准备")
            else:
                prep_text="🟢 准备完成" if ready else "🔴 未准备"
            self.link_table.setItem(i,4,QTableWidgetItem(prep_text))

            last_seen=getattr(self, "host_last_seen", {}).get(int(row["host_id"]),0)
            online=(time.monotonic()-last_seen) < 6.5 if last_seen else False
            try:
                web_snap=self.bridge.web_plugin_state(int(row["host_id"]))
                snap_age=time.time()-float(web_snap.get("last_seen") or 0) if web_snap else 999
                online=online or snap_age < 7.5
            except Exception:
                pass
            self.link_table.setItem(i,5,QTableWidgetItem("🟢 已连接" if online else "🔴 未连接"))

            b=QPushButton("打开")
            b.setMinimumSize(76,34)
            b.clicked.connect(lambda _=False,idx=i:self.open_host_link(idx))
            self.link_table.setCellWidget(i,6,b)

            s=QPushButton(("多通道生成" if is_multi else "开始生成") if ready else "等待准备")
            s.setObjectName("primaryBtn")
            s.setMinimumSize(90,34)
            s.setEnabled(bool(ready and online))
            s.setToolTip("网页插件已确认图片和任务准备完成" if ready else "等待网页插件返回 READY")
            s.clicked.connect(lambda _=False,idx=i:self.send_host_tasks(idx))
            self.link_table.setCellWidget(i,7,s)

    def _autosave_flow_link(self, index):
        row, url = self._row_url(index)
        if row is not None:
            if repo.flow_channel_count(row["host_id"])>1 or repo.flow_rework_enabled(row["host_id"]):
                repo.ensure_flow_channels(row["host_id"],repo.flow_channel_count(row["host_id"]),repo.flow_rework_enabled(row["host_id"]))
                ch1=next((c for c in repo.list_flow_channels(host_id=row["host_id"]) if c["channel_key"]=="CH1"),None)
                if ch1: repo.set_flow_channel_url(ch1["id"],url or "")
            else:
                repo.set_host_flow_collection_url(row["host_id"], url or "")

    @production_ui_action
    def save_all_flow_links(self):
        if not hasattr(self,"link_rows"): return
        for i,row in enumerate(self.link_rows):
            edit=self.link_table.cellWidget(i,2)
            if isinstance(edit,QLineEdit):
                url=edit.text().strip()
                if repo.flow_channel_count(row["host_id"])>1 or repo.flow_rework_enabled(row["host_id"]):
                    repo.ensure_flow_channels(row["host_id"],repo.flow_channel_count(row["host_id"]),repo.flow_rework_enabled(row["host_id"]))
                    ch1=next((c for c in repo.list_flow_channels(host_id=row["host_id"]) if c["channel_key"]=="CH1"),None)
                    if ch1: repo.set_flow_channel_url(ch1["id"],url)
                else:
                    repo.set_host_flow_collection_url(row["host_id"],url)

    def _row_url(self,index):
        if not hasattr(self,"link_rows") or not (0<=index<len(self.link_rows)):
            return None,None
        row=self.link_rows[index]
        edit=self.link_table.cellWidget(index,2)
        url=edit.text().strip() if isinstance(edit,QLineEdit) else (row["flow_collection_url"] or "")
        return row,url

    def open_host_link(self,index):
        row,url=self._row_url(index)
        if not row or not url:
            QMessageBox.information(self,"Flow集合链接","请先填写这个主播的集合链接。")
            return

        repo.set_host_flow_collection_url(row["host_id"],url)
        fresh=next((x for x in repo.list_flow_host_links(self.recipient.currentData(), work_date=work_dates.active())
                    if x["host_id"]==row["host_id"]),None)
        if not fresh:
            return

        job=self._make_host_job(fresh)
        job["open_window"]=True
        job["focus_window"]=True
        job["execute_upload"]=False
        job["command_id"]=f'open-{row["host_id"]}'
        self.bridge.publish_host_jobs([job])


    def open_task_mode_manager(self):
        rid=self.recipient.currentData() if hasattr(self,'recipient') else None
        hid=self.host.currentData() if hasattr(self,'host') else None
        rows=list(repo.list_flow_tasks(rid,hid,'全部',work_date=work_dates.active()))
        # This UI is deliberately an editor over the same flow_segments.generation_mode field,
        # not a second task/mode data source.
        dlg=QDialog(self); dlg.setWindowTitle('任务生成模式 · 帧 / 素材'); dlg.resize(720,560)
        root=QVBoxLayout(dlg)
        hint=QLabel('只允许直接修改尚未正式执行的任务。已提交/生成/下载/完成的片段请在质检中心切换，系统会通过现有 REWORK 返工。',objectName='muted'); hint.setWordWrap(True); root.addWidget(hint)
        table=QTableWidget(); table.setColumnCount(5); table.setHorizontalHeaderLabels(['任务ID','接收人','AI主播','状态','模式']); table.setRowCount(len(rows)); table.verticalHeader().setVisible(False); table.setSelectionMode(QAbstractItemView.NoSelection)
        table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeToContents); table.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch); table.horizontalHeader().setSectionResizeMode(2,QHeaderView.Stretch); table.horizontalHeader().setSectionResizeMode(3,QHeaderView.ResizeToContents); table.horizontalHeader().setSectionResizeMode(4,QHeaderView.ResizeToContents)
        for i,t in enumerate(rows):
            table.setItem(i,0,QTableWidgetItem(f"{int(t['video_seq']):02d}-{int(t['seg_seq']):02d}")); table.setItem(i,1,QTableWidgetItem(str(t['recipient_name'] or ''))); table.setItem(i,2,QTableWidgetItem(str(t['host_name'] or ''))); table.setItem(i,3,QTableWidgetItem(str(t['flow_status'] or '待生成')))
            toggle=GenerationModeToggle(t['generation_mode'] if 'generation_mode' in t.keys() else 'FRAME',table)
            active=bool(str(t['generation_command'] or '').strip()) or str(t['flow_status'] or '') not in ('','待生成','失败','已准备')
            toggle.setEnabled(not active)
            def apply_mode(mode,sid=int(t['segment_id']),widget=toggle):
                try: repo.set_segment_generation_mode(sid,mode,allow_active_rework=False)
                except Exception as exc: QMessageBox.warning(dlg,'切换模式',str(exc)); widget.setEnabled(False)
            toggle.modeChanged.connect(apply_mode); table.setCellWidget(i,4,toggle)
        root.addWidget(table,1)
        close=QPushButton('完成'); close.clicked.connect(dlg.accept); row=QHBoxLayout(); row.addStretch(1); row.addWidget(close); root.addLayout(row)
        dlg.exec(); self.reload_tasks()

    def save_footage_mode(self):
        if not hasattr(self, "footage_mode"):
            return
        repo.set_setting(
            "flow_footage_mode",
            self.footage_mode.currentData() or "VIDEO_REFERENCES"
        )

    def save_generation_count(self):
        if not hasattr(self, "generation_count"):
            return
        try:
            value = int(self.generation_count.currentData() or 1)
        except (TypeError, ValueError):
            value = 1
        repo.set_setting("flow_generation_count", str(max(1, min(4, value))))

    def _make_host_job(self,row, task_subset=None):
        from app.services.text_processing import flow_timing
        url=(row["flow_collection_url"] or "").strip()
        if not url: return None

        imgs=list(repo.get_host_images(row["host_id"]))
        paths=[x["image_path"] for x in imgs if (x["image_path"] or "").strip()]
        batches=[paths[i:i+20] for i in range(0,len(paths),20)]

        # Stable local image-set identity. This prevents an old upload receipt from
        # being reused after the user replaces one of the source files but keeps the
        # same host/collection. We intentionally avoid hashing file contents here so
        # large batches stay responsive; basename + size + mtime_ns is enough to
        # invalidate the proof when a local file changes.
        image_files=[]
        fingerprint_parts=[]
        for image_path in paths:
            pp=Path(image_path)
            try:
                st=pp.stat()
                size=int(st.st_size)
                mtime_ns=int(st.st_mtime_ns)
            except OSError:
                size=-1
                mtime_ns=-1
            name=pp.name
            image_files.append({
                "path":str(image_path),
                "name":name,
                "size":size,
                "mtime_ns":mtime_ns,
            })
            fingerprint_parts.append(f"{name.lower()}|{size}|{mtime_ns}")
        image_set_id=hashlib.sha256("\n".join(fingerprint_parts).encode("utf-8")).hexdigest()[:24]

        tasks=(list(task_subset) if task_subset is not None else repo.list_flow_tasks(
            recipient_id=row["recipient_id"],
            host_id=row["host_id"],
            status_filter="全部",
            work_date=work_dates.active()
        ))
        if task_subset is None:
            tasks = [t for t in tasks if t['flow_status'] in ('待生成','已准备')]
        task_payload=[{
            "segment_id":int(x["segment_id"]),
            "task_id":f'{x["video_seq"]:02d}-{x["seg_seq"]:02d}',
            **__import__('app.services.duration_choices',fromlist=['dispatch_timing']).dispatch_timing(x),
            "dialogue":x["foreign_text"] or "",
            "prompt":x["prompt"] or "",
            "image_path":x["image_path"] or "",
            "generation_mode":repo.normalize_generation_mode(x["generation_mode"] if "generation_mode" in x.keys() else "FRAME"),
            "document_number":int(x["video_seq"])
        } for x in tasks]

        footage_mode = 'MIXED' if any(str(t.get('generation_mode') or 'FRAME')=='MATERIAL' for t in task_payload) else 'VIDEO_FRAMES'

        try:
            generation_count = int(
                self.generation_count.currentData()
                if hasattr(self, "generation_count")
                else repo.get_setting("flow_generation_count", "1")
            )
        except (TypeError, ValueError):
            generation_count = 1
        generation_count = max(1, min(4, generation_count))

        saved_state=str(row["flow_upload_state"] or "idle")
        saved_fp=str(row["flow_upload_fingerprint"] or "")
        saved_uploaded=int(row["flow_images_uploaded"] or 0)
        verified_at=str(row["flow_upload_verified_at"] or "")
        proof_verified=(
            saved_state=="verified"
            and saved_fp==image_set_id
            and (len(paths)==0 or saved_uploaded>=len(paths))
            and bool(verified_at)
        )

        return {
            "work_date":str(row["work_date"] or work_dates.active()),
            "recipient_id":int(row["recipient_id"]),
            "host_id":int(row["host_id"]),
            "recipient_name":row["recipient_name"],
            "host_name":row["host_name"],
            "collection_url":url,
            "image_count":len(paths),
            "image_files":image_files,
            "image_set_id":image_set_id,
            "expected_image_names":[x["name"] for x in image_files],
            "upload_batches":batches,
            "upload_proof":{
                "verified":bool(proof_verified),
                "host_id":int(row["host_id"]),
                "image_set_id":saved_fp if proof_verified else "",
                "collection_url":url if proof_verified else "",
                "upload_command_id":str(row["flow_upload_command_id"] or "") if proof_verified else "",
                "uploaded":saved_uploaded if proof_verified else 0,
                "verified_at":verified_at if proof_verified else "",
            },
            "tasks":task_payload,
            "settings":self.plugin_settings_payload(),
            "footage_mode":footage_mode,
            "footage_mode_label":"混合" if footage_mode=="MIXED" else ("帧" if footage_mode=="VIDEO_FRAMES" else "素材"),
            "generation_count":generation_count,
            "generation_count_label":str(generation_count),
            "open_window":False,
            "focus_window":False,
            "execute_upload":False,
            "dispatch_tasks":False,
            "auto_execute":False,
            "retry_only":False,
            "command_id":"",
            "studio_upload_state":str(row["flow_upload_state"] or "idle"),
            "studio_upload_fingerprint":str(row["flow_upload_fingerprint"] or "")
        }

    def auto_dispatch_tick(self):
        self._queue_production('auto')

    def _queue_production(self, kind):
        if not hasattr(self, '_production_lane'): return
        key = (kind, work_dates.active(), int(self.generation_count.currentData() or 1))
        self._production_lane.submit(kind, self._production_worker.run, key, self._production_ready)

    def _production_ready(self, result, error):
        if error:
            runtime_log.log('production_worker_failed', level='ERROR', error=error)
            if self.isVisible(): self.auto_production_state.setText('⚠ 后台任务异常，详见日志')
            return
        if result['day'] != work_dates.active(): return
        self._production_status = result
        if self.isVisible():
            self.auto_production_state.setText(result['text'])
            self.auto_production_state.setToolTip(result['tooltip'])
        if result['dirty']: self.reload_tasks()



    def _auto_retry_timed_out_active_commands(self, scope_day):
        """A delayed receipt is not permission to regenerate a paid or failed task."""
        now=time.time()
        if now-getattr(self,'_last_active_progress_scan',0)>=60:
            self._last_active_progress_scan=now
            try:self.bridge.request_progress_scan()
            except Exception as exc:runtime_log.log('progress_scan_failed',level='WARNING',error=str(exc))
        return 0

    def _auto_reclaim_unclaimed_dispatches(self, scope_day):
        """Return a released-but-never-claimed wave to the central waiting pool.

        This is deliberately narrower than timeout retry: a browser command owner or any
        submitted/download receipt blocks reclamation, and active image uploads are also
        protected.  Therefore automatic refill cannot duplicate work that may already be
        inside Flow.
        """
        try:
            threshold=max(30,int(repo.get_setting('flow_auto_reclaim_unclaimed_seconds','60') or 60))
        except Exception:
            threshold=60
        rows=list(repo.list_auto_reclaimable_unsubmitted_dispatches(now=time.time(),threshold_seconds=threshold,work_date=scope_day))
        if not rows:
            return 0
        grouped={}
        for row in rows:
            grouped.setdefault(str(row['command_id'] or ''),[]).append(int(row['id']))
        recovered=0
        for command,dispatch_ids in grouped.items():
            if not command:
                continue
            # Remove the executable bridge job first. A delayed browser pull can no longer
            # start this obsolete wave after its segments have returned to WAITING.
            try:
                self.bridge.cancel_host_commands([command])
            except Exception as exc:
                runtime_log.log('auto_refill_cancel_old_command_failed',level='WARNING',command_id=command,error=str(exc))
                continue
            moved=repo.requeue_unsubmitted_dispatches(dispatch_ids,work_date=scope_day)
            recovered+=int(moved or 0)
            if moved:
                runtime_log.log('auto_refill_unclaimed_wave_recovered',work_date=scope_day,command_id=command,dispatches=len(dispatch_ids),segments=moved)
        if recovered:
            repo.release_finished_channel_commands()
        return recovered

    def _auto_dispatch_ready_tasks(self, scope_day=None, audit=None):
        if scope_day is None:
            from app.core import work_dates as _work_dates
            scope_day=_work_dates.active()
        # Automatic production must consume the GLOBAL approved queue, not the
        # recipient/host currently selected in the Flow Center UI. Otherwise a
        # prompt submitted from GPT can sit forever when another recipient/host
        # is selected on this page.
        from app.services import task_recovery
        task_recovery.restore_normal_tasks(work_date=scope_day)
        # Repair only provably unsubmitted/orphaned local ownership before reading the
        # queue.  This makes waiting rows eligible again without touching any submitted,
        # rendering, downloading or QC-owned task.
        preconfirm=repo.recover_unconfirmed_preclick_dispatches(work_date=scope_day)
        if preconfirm.get('segments') or preconfirm.get('channels'):
            runtime_log.log('auto_dispatch_false_submitted_recovered',work_date=scope_day,segments=preconfirm.get('segments',[]),channels=preconfirm.get('channels',[]),commands=preconfirm.get('commands',[]))
        recovered=repo.recover_orphaned_waiting_commands(work_date=scope_day)
        if recovered.get('segments') or recovered.get('channels'):
            runtime_log.log('auto_dispatch_orphan_recovered',work_date=scope_day,segments=recovered.get('segments',[]),channels=recovered.get('channels',[]))
        self.bridge.request_ch2_rebalance()
        rows=[dict(t) for t in repo.list_flow_tasks(None,None,'全部', work_date=scope_day)]
        # V0.13.5.87: every 2-second scheduler pass audits production progress by AI host,
        # independent of the Flow Center's current recipient/host filter. This keeps the
        # central pool authoritative: any unfinished host with dispatchable segments will
        # be planned onto currently idle normal channels in this same pass.
        host_scan={}
        for row in rows:
            hid=int(row.get('host_id') or 0)
            if not hid: continue
            bucket=host_scan.setdefault(hid,{'host_id':hid,'host_name':str(row.get('host_name') or ''),'total':0,'complete':0,'active':0,'waiting':0})
            bucket['total']+=1
            status=str(row.get('flow_status') or '待生成')
            has_output=bool(str(row.get('flow_output_path') or '').strip())
            if status=='已完成' or has_output: bucket['complete']+=1
            elif str(row.get('generation_command') or '').strip(): bucket['active']+=1
            else: bucket['waiting']+=1
        unfinished_hosts=[v for v in host_scan.values() if v['complete']<v['total']]
        progress_sig=tuple((v['host_id'],v['complete'],v['active'],v['waiting'],v['total']) for v in sorted(unfinished_hosts,key=lambda x:x['host_id']))
        if progress_sig!=getattr(self,'_last_auto_host_progress_signature',None):
            self._last_auto_host_progress_signature=progress_sig
            runtime_log.log('auto_production_host_progress_scan',work_date=scope_day,unfinished_hosts=unfinished_hosts,
                            unfinished_host_count=len(unfinished_hosts),scan_interval_seconds=2,timeout_seconds=300)
        from app.services import host_priority
        redo_ids=workflow.redo_ids(work_date=scope_day)
        tasks=[]
        for t in rows:
            if int(t['segment_id']) in redo_ids:
                continue
            if str(t['generation_command'] or ''):
                continue
            if str(t['flow_status'] or '待生成') in ('待生成','已准备'):
                tasks.append(t)
        tasks=host_priority.apply(tasks,rows,scope_day)
        if not tasks:
            if hasattr(self,'auto_production_state'):
                audit=audit or repo.reconcile_selected_date_unfinished_tasks(work_date=scope_day)
                unfinished=int(audit.get('unfinished',0) or 0)
                active=int(audit.get('active',0) or 0)
                failed=int(audit.get('failed',0) or 0)
                download_failed=int(audit.get('download_failed',0) or 0)
                if unfinished:
                    self.auto_production_state.setText(f'● {scope_day} 已检查 · 未完成 {unfinished} · 当前可派发 0')
                    self.auto_production_state.setToolTip(
                        f'当前日期已自动扫描。运行/等待结果 {active}，生成失败 {failed}，下载失败 {download_failed}。'
                        '有真实提交回执的任务不会自动重复生成。'
                    )
                else:
                    self.auto_production_state.setText(f'● {scope_day} 已检查 · 没有等待任务')
                    self.auto_production_state.setToolTip('自动调度器每 2 秒只检查当前选中日期。')
            return 0

        ready=[]; image_errors=[]
        for task in tasks:
            try:
                channel_pool.resolve_task_image_path(task)
                ready.append(task)
            except Exception as exc:
                image_errors.append(str(exc))
                runtime_log.log('auto_dispatch_image_blocked',level='ERROR',segment_id=task['segment_id'],error=str(exc))
        tasks=ready
        if image_errors and hasattr(self,'auto_production_state'):
            self.auto_production_state.setText(f'⚠ {len(image_errors)} 条图片待修复')
            self.auto_production_state.setToolTip('\n'.join(image_errors[:10]))
        if not tasks:return 0

        # Only configured normal channels participate in unattended dispatch.
        # Unconfigured slots (for example CH4-CH7 when the user only uses three
        # browser tabs) must NOT block every submitted video task.
        channel_pool.recover_unpublished_auto_dispatches(work_date=scope_day)
        healed=repo.heal_recent_online_channels()
        if healed:
            runtime_log.log('auto_dispatch_live_channel_healed',channels=healed)
        all_channels=list(channel_pool.available_channels('normal',work_date=scope_day))
        channels=[]
        seen={}
        for ch in all_channels:
            url=str(ch['collection_url'] or '').strip()
            if not url:
                continue
            norm=url.split('#',1)[0].strip().lower()
            if norm in seen:
                runtime_log.log('auto_dispatch_channel_ignored',level='WARNING',reason='duplicate_channel_url',channel=ch['channel_key'],duplicate_of=seen[norm])
                continue
            seen[norm]=str(ch['channel_key'])
            channels.append(ch)
        if not channels:
            configured=[dict(c) for c in repo.list_channel_pool(enabled_only=True) if str(c['role'])=='normal' and str(c['collection_url'] or '').strip()]
            detail=[{'channel':str(c['channel_key']),'online_age':round(time.time()-float(c['last_seen'] or 0),1) if c['last_seen'] else None,
                     'task_command_id':str(c['task_command_id'] or ''),'health':str(c['health_status'] or ''),
                     'quarantine_until':float(c['quarantine_until'] or 0)} for c in configured]
            if hasattr(self,'auto_production_state'):
                self.auto_production_state.setText(f'等待可用通道 · {len(tasks)} 条任务保留 · 已配置 {len(configured)} 个普通通道')
                self.auto_production_state.setToolTip('调度器没有发现可领取任务的普通通道；详细原因已写入运行日志。')
            runtime_log.log('auto_dispatch_waiting_for_channel',level='WARNING',reason='no_available_configured_channel',pending=len(tasks),channels=detail)
            return 0
        pressure=pipeline_orchestrator.backpressure_state()
        if pressure.get('throttled'):
            # Retaining downstream data must not silently stop authorized new work.
            # Backpressure remains advisory, matching the service's stated contract.
            runtime_log.log('auto_dispatch_backlog_advisory',level='WARNING',reason=pressure.get('reason',''))
        plan=channel_pool.plan(tasks,channels); jobs=[]; stamp=str(time.time_ns())
        try: rounds=max(1,min(4,int(self.generation_count.currentData() or 1)))
        except Exception: rounds=1
        for ch in channels:
            ctasks=plan.get(str(ch['channel_key']),[])
            if not ctasks: continue
            cmd=f"auto-pool-{ch['channel_key']}-{stamp}"
            prelim=self._make_pool_job(ch,ctasks,cmd,generation_count=rounds,dispatch_tasks=True,work_date=scope_day)
            need_upload=not bool(prelim['upload_proof']['verified'])
            job=self._make_pool_job(ch,ctasks,cmd,generation_count=rounds,execute_upload=need_upload,dispatch_tasks=True,work_date=scope_day)
            jobs.append(job)
        if not jobs:
            # Never silently leave visible WAITING rows with idle channels. Record the
            # exact planner state so the next 2-second watchdog tick can self-heal.
            runtime_log.log('auto_dispatch_zero_plan',level='WARNING',work_date=scope_day,pending=len(tasks),channels=[str(c['channel_key']) for c in channels])
            if hasattr(self,'auto_production_state'):
                self.auto_production_state.setText(f'⚠ {scope_day} 有 {len(tasks)} 条等待任务 · 调度计划为空，2秒后自动重试')
            return 0
        for job in jobs:
            cmd=job['command_id'];channel_key=job['channel_key']
            repo.set_channel_pool_task_command(channel_key,cmd)
            if job['execute_upload']:
                repo.set_channel_pool_runtime(channel_key,'queued',command_id=cmd,fingerprint=job['image_set_id'],uploaded=0,total=job['image_count'],error='')
            for order,t in enumerate(job['tasks'],1):
                repo.assign_flow_channel(t['segment_id'],channel_key)
                for r in range(1,rounds+1):
                    stem=channel_pool.render_stem(t,r,rounds)
                    repo.create_dispatch(t['segment_id'],channel_key,cmd,order,r,stem,stem+'.mp4','queued')
        lo,hi=channel_pool.stagger_bounds()
        jobs=channel_pool.apply_random_release_schedule(jobs,minimum=lo,maximum=hi)
        for job in jobs:
            repo.set_dispatch_release_for_command(job['command_id'],job.get('release_at') or 0)
        self.bridge.publish_host_jobs(jobs)
        if hasattr(self,'auto_production_state'):
            self.auto_production_state.setText(f"已发送 {sum(len(j['tasks']) for j in jobs)} 条到插件队列（每通道最多5条），剩余 {len(tasks)-sum(len(j['tasks']) for j in jobs)} 条等待空闲通道"+(f' · {len(image_errors)} 条图片异常' if image_errors else ''))
            self.auto_production_state.setToolTip('\n'.join(image_errors[:10]) if image_errors else '等待网页插件领取；运行中任务与历史记录保留。')
        runtime_log.log('auto_flow_dispatch',jobs=len(jobs),segments=sum(len(j['tasks']) for j in jobs))
        self.reload_tasks(); self.refresh_channel_pool_table()
        return sum(len(j['tasks']) for j in jobs)

    @production_ui_action
    def upload_all_host_images(self):
        self.save_all_flow_links()
        rows=list(repo.list_flow_host_links(self.recipient.currentData(), work_date=work_dates.active()))
        multi=[r for r in rows if repo.flow_channel_count(r['host_id'])>1 or repo.flow_rework_enabled(r['host_id'])]
        if multi:
            self.upload_multi_channel_images(multi)
            if len(multi)==len(rows): return
            rows=[r for r in rows if r not in multi]
        jobs=[]
        missing=[]
        already_verified=[]
        resumed=[]
        command_stamp=str(int(time.time()*1000))
        active_states={"queued","precheck","uploading","flow_verified","refreshing","post_refresh"}

        for row in rows:
            job=self._make_host_job(row)
            if not job:
                missing.append(row["host_name"])
                continue

            job["open_window"]=False
            job["execute_upload"]=True
            job["dispatch_tasks"]=False
            job["auto_execute"]=False
            current_fp=job["image_set_id"]
            saved_fp=str(row["flow_upload_fingerprint"] or "")
            saved_state=str(row["flow_upload_state"] or "idle")
            saved_cmd=str(row["flow_upload_command_id"] or "")
            uploaded_now=int(row["flow_images_uploaded"] or 0)
            total_now=int(row["image_count"] or 0)

            # A receipt is reusable only for the exact same local image-set fingerprint.
            if (saved_state=="verified" and saved_fp==current_fp and
                    (total_now==0 or uploaded_now>=total_now)):
                already_verified.append(row["host_name"])
                continue

            # If Studio restarted while an upload was between drag and post-refresh
            # verification, republish the SAME command so the page resumes the same
            # state machine. Never create a second upload command for the same batch.
            if saved_state in active_states and saved_fp==current_fp and saved_cmd:
                job["command_id"]=saved_cmd
                resumed.append(row["host_name"])
                job["studio_upload_state"]=saved_state
                job["studio_upload_fingerprint"]=current_fp
                repo.set_host_upload_runtime(
                    row["host_id"], saved_state, command_id=saved_cmd,
                    fingerprint=current_fp, total=job["image_count"],
                    status="恢复未完成的图片上传流程"
                )
            else:
                command_id=f'upload-{row["host_id"]}-{command_stamp}'
                job["command_id"]=command_id
                job["studio_upload_state"]="queued"
                job["studio_upload_fingerprint"]=current_fp
                repo.set_host_upload_runtime(
                    row["host_id"], "queued", command_id=command_id,
                    fingerprint=current_fp, uploaded=0, total=job["image_count"],
                    status="等待网页端开始上传", error=""
                )
            self.active_task_commands.pop(int(row["host_id"]),None)
            repo.set_host_task_command(int(row["host_id"]), "")
            jobs.append(job)

        if not jobs:
            detail="没有需要上传的图片。"
            if already_verified:
                detail += "\n\n以下主播已经通过严格校验，会自动跳过：" + "、".join(already_verified[:8])
            if missing:
                detail += "\n缺少集合链接：" + "、".join(missing[:8])
            QMessageBox.information(self,"上传图片",detail)
            self.refresh_link_table()
            return

        version=self.bridge.publish_host_jobs(jobs)
        self.refresh_link_table()
        self.flow_monitor=FlowRunMonitorDialog(jobs,self)
        self.flow_monitor.append_log(
            f"已下发 {len(jobs)} 个主播图片上传任务 · 严格状态机 · 最多 3 次缺失文件补传 · Bridge {version}"
        )
        if resumed:
            self.flow_monitor.append_log("恢复未完成上传："+"、".join(resumed[:8]))
        if already_verified:
            self.flow_monitor.append_log("已严格验证，跳过上传："+"、".join(already_verified[:8]))
        if missing:
            self.flow_monitor.append_log("未执行（没有链接）："+"、".join(missing[:8]))
        self.flow_monitor.show(); self.flow_monitor.raise_()

    @production_ui_action
    def generate_all_host_tasks(self):
        self.save_all_flow_links()
        rows=list(repo.list_flow_host_links(self.recipient.currentData(), work_date=work_dates.active()))
        multi=[r for r in rows if repo.flow_channel_count(r['host_id'])>1 or repo.flow_rework_enabled(r['host_id'])]
        if multi:
            self.generate_multi_channel(multi)
            if len(multi)==len(rows): return
            rows=[r for r in rows if r not in multi]
        jobs=[]
        missing=[]
        not_ready=[]
        stamp=str(int(time.time()*1000))
        for row in rows:
            job=self._make_host_job(row)
            if not job:
                missing.append(row["host_name"]); continue
            uploaded=int(row["flow_images_uploaded"] or 0)
            total=int(row["image_count"] or 0)
            state=str(row["flow_upload_state"] or "idle")
            saved_fp=str(row["flow_upload_fingerprint"] or "")
            current_fp=job["image_set_id"]
            if state!="verified" or saved_fp!=current_fp or (total and uploaded < total):
                not_ready.append(f'{row["host_name"]} {uploaded}/{total} · {state}')
                continue
            job["open_window"]=False
            job["execute_upload"]=False
            job["dispatch_tasks"]=True
            job["auto_execute"]=True
            job["command_id"]=f'generate-{row["host_id"]}-{stamp}'
            jobs.append(job)
        if not jobs:
            detail="没有可以生成的任务。"
            if not_ready: detail += "\n图片尚未确认上传："+"、".join(not_ready[:8])
            if missing: detail += "\n缺少集合链接："+"、".join(missing[:8])
            QMessageBox.information(self,"全部生成",detail)
            return
        for _job in jobs:
            self.active_task_commands[int(_job["host_id"])]=str(_job["command_id"])
            repo.set_host_task_command(int(_job["host_id"]), str(_job["command_id"]))
        version=self.bridge.publish_host_jobs(jobs)
        self.flow_monitor=FlowRunMonitorDialog(jobs,self)
        self.flow_monitor.append_log(f"已发送 {len(jobs)} 个主播的全部生成任务 · Bridge {version}")
        if not_ready:
            self.flow_monitor.append_log("跳过（图片未上传完成）："+"、".join(not_ready[:8]))
        if missing:
            self.flow_monitor.append_log("跳过（没有链接）："+"、".join(missing[:8]))
        self.flow_monitor.show(); self.flow_monitor.raise_()

    @production_ui_action
    def send_host_tasks(self,index):
        row,url=self._row_url(index)
        if row and (repo.flow_channel_count(row['host_id'])>1 or repo.flow_rework_enabled(row['host_id'])):
            if url: repo.set_host_flow_collection_url(row['host_id'],url)
            self.generate_multi_channel([row]); return
        if not row or not url:
            QMessageBox.information(self,"发送任务","请先填写这个主播的集合链接。")
            return

        repo.set_host_flow_collection_url(row["host_id"],url)
        fresh=next((x for x in repo.list_flow_host_links(self.recipient.currentData(), work_date=work_dates.active())
                    if x["host_id"]==row["host_id"]),None)
        if not fresh:
            return

        uploaded=int(fresh["flow_images_uploaded"] or 0)
        total=int(fresh["image_count"] or 0)
        job=self._make_host_job(fresh)
        state=str(fresh["flow_upload_state"] or "idle")
        saved_fp=str(fresh["flow_upload_fingerprint"] or "")
        current_fp=job["image_set_id"]
        if state!="verified" or saved_fp!=current_fp or (total and uploaded < total):
            QMessageBox.information(
                self,"开始生成",
                f"图片尚未通过严格上传验证：{uploaded}/{total} · {state}。\n\n"
                "请等待网页插件完成图片扫描与任务匹配；收到 READY 后按钮会自动变蓝。"
            )
            return

        import time
        job["open_window"]=False
        job["execute_upload"]=False
        job["dispatch_tasks"]=True
        job["auto_execute"]=True
        job["command_id"]=f'tasks-{row["host_id"]}-{int(time.time()*1000)}'

        self.active_task_commands[int(job["host_id"])]=str(job["command_id"])
        repo.set_host_task_command(int(job["host_id"]), str(job["command_id"]))
        version=self.bridge.publish_host_jobs([job])
        QMessageBox.information(
            self,"发送任务",
            f'已向“{row["host_name"]}”当前已打开的集合页面发送 {len(job["tasks"])} 个任务。\\n'
            f"Bridge版本：{version}\\n"
            "不会打开新的浏览器窗口。"
        )


    def plugin_settings_payload(self):
        return {
            "aspect_ratio": repo.get_setting("flow_aspect_ratio", "9:16"),
            "interval": int(repo.get_setting("flow_plugin_interval", "20") or 20),
            "intervalRandom": int(repo.get_setting("flow_plugin_interval_random", "10") or 10),
            "maxLetterFor4s": int(repo.get_setting("flow_plugin_max4", "40") or 40),
            "maxLetterFor6s": int(repo.get_setting("flow_plugin_max6", "60") or 60),
            "maxLetterFor8s": int(repo.get_setting("flow_plugin_max8", "80") or 80),
            "videoModel": repo.get_setting(
                "flow_plugin_video_model", "veo_3_1_lite_low_priority"
            ) or "veo_3_1_lite_low_priority",
            "extraFolder": "none",
            "displayTextPreview": repo.get_setting("flow_plugin_preview", "1") != "0",
            "maxHeight": 300,
            "download": repo.get_setting("flow_plugin_download", "1") != "0",
            "capturePosition": float(repo.get_setting("flow_plugin_capture", "0.95") or 0.95),
        }

    def sync_bridge_config(self):
        self.bridge.update_config({
            "profileDirectory": repo.get_setting("chrome_profile_directory", "Default") or "Default",
            "flowUrl": repo.get_setting("flow_url", DEFAULT_FLOW_URL) or DEFAULT_FLOW_URL,
            "pluginSettings": self.plugin_settings_payload(),
        })

    def refresh_bridge_status(self):
        if not self.isVisible(): return
        cache=getattr(self,'_view_cache',None)
        if not cache:return
        status=self.bridge.status()
        profile=cache['profile']
        name=next((p['name'] for p in cache['profiles'] if p['directory']==profile),profile)
        version=status.get('extension',{}).get('extensionVersion','')
        self.bridge_status.setText(f"Bridge：{'● 已连接' if status['connected'] else '○ 等待插件'} · {name}"+(f' · v{version}' if version else ''))
        if hasattr(self,'bridge_port_badge'):self.bridge_port_badge.setText(f"端口 {status.get('port',17831)}")

    def request_progress_scan(self):
        """Ask every connected Flow page to rescan generation/download progress."""
        self.bridge.request_progress_scan()
        # Database is updated by reliable plugin receipts. Refresh visible Studio
        # data immediately after each request so task center and dashboard stay in sync.
        if self.isVisible():self.reload_tasks()
        owner = self.parent_window or self.parent()
        if owner and hasattr(owner, "stack") and hasattr(owner, "dashboard"):
            if owner.stack.currentWidget() is owner.dashboard and hasattr(owner, "show_dashboard"):
                owner.show_dashboard()
        if owner and hasattr(owner, "qc_page"):
            try:
                owner.qc_page.mark_dirty()
            except Exception:
                pass

    def refresh_pause_button(self):
        paused = bool(self.bridge.generation_control().get("paused"))
        self.pause_all_btn.setText("▶ 继续全部" if paused else "⏸ 暂停全部")
        self.pause_all_btn.setProperty("paused", paused)
        if hasattr(self,"visual_pause_btn"):
            self.visual_pause_btn.setText("▶ 恢复生产" if paused else "⏸ 暂停生产")

    def toggle_generation_pause(self):
        paused = bool(self.bridge.generation_control().get("paused"))
        self.bridge.set_generation_paused(not paused)
        # Force a control refresh immediately instead of waiting for the next 10-second scan.
        self.bridge.request_progress_scan()
        self.refresh_pause_button()

    def select_tasks_by_status(self):
        if not hasattr(self, "table") or not hasattr(self, "task_rows"):
            return
        wanted = self.status.currentText()
        for row, task in enumerate(self.task_rows):
            task_status = task["flow_status"] or "待生成"
            checked = (wanted == "全部" or task_status == wanted)
            cell = self._cell_check(row)
            if cell:
                cell.setChecked(checked, block=True)
            if checked:
                self.checked_ids.add(task["segment_id"])
            else:
                self.checked_ids.discard(task["segment_id"])
        self.update_header_check()
        self.selected_label.setText(f"已选择：{len(self.selected_ids())}")

    @production_ui_action
    def send_selected_to_bridge(self):
        tasks = self.require_selected()
        if not tasks:
            return

        self.sync_bridge_config()
        link_rows=list(repo.list_flow_host_links(self.recipient.currentData(), work_date=work_dates.active()))
        links={int(r["host_id"]):r for r in link_rows}
        by_host={}
        for task in tasks:
            by_host.setdefault(int(task["host_id"]),[]).append(task)

        stamp=str(int(time.time()*1000))
        jobs=[]
        ready_tasks=[]
        missing=[]
        not_ready=[]
        for host_id, host_tasks in by_host.items():
            row=links.get(host_id)
            if not row or not (row["flow_collection_url"] or "").strip():
                missing.append(host_tasks[0]["host_name"])
                continue
            job=self._make_host_job(row, host_tasks)
            state=str(row["flow_upload_state"] or "idle")
            saved_fp=str(row["flow_upload_fingerprint"] or "")
            uploaded=int(row["flow_images_uploaded"] or 0)
            total=int(row["image_count"] or 0)
            if state!="verified" or saved_fp!=job["image_set_id"] or (total and uploaded<total):
                not_ready.append(f'{row["host_name"]} {uploaded}/{total} · {state}')
                continue
            job["open_window"]=False
            job["execute_upload"]=False
            job["dispatch_tasks"]=True
            job["auto_execute"]=True
            job["command_id"]=f'selected-{host_id}-{stamp}'
            jobs.append(job)
            ready_tasks.extend(host_tasks)

        if not jobs:
            detail="没有任务通过图片最终验证，因此没有向网页端发送任何生成任务。"
            if not_ready:
                detail += "\n\n图片尚未通过严格验证：" + "、".join(not_ready[:8])
            if missing:
                detail += "\n\n缺少 Flow 集合链接：" + "、".join(missing[:8])
            QMessageBox.information(self, "未发送", detail)
            return

        # Legacy queue remains for compatibility, but it receives ONLY the same
        # verified subset that is allowed into /host-jobs. This prevents a task
        # from racing ahead of the upload state machine through another channel.
        payload=[]
        for task in ready_tasks:
            payload.append({
                "segment_id":int(task["segment_id"]),
                "task_id":f'{task["video_seq"]:02d}-{task["seg_seq"]:02d}',
                "recipient":task["recipient_name"],
                "host":task["host_name"],
                "image_path":task["image_path"] or "",
                "dialogue":task["foreign_text"] or "",
                "prompt":task["prompt"] or "",
            })
        queue_version=self.bridge.publish_tasks(payload)

        for _job in jobs:
            self.active_task_commands[int(_job["host_id"])]=str(_job["command_id"])
            repo.set_host_task_command(int(_job["host_id"]), str(_job["command_id"]))
        host_version=self.bridge.publish_host_jobs(jobs)
        sent_host_ids={int(j["host_id"]) for j in jobs}
        for task in ready_tasks:
            if int(task["host_id"]) in sent_host_ids:
                repo.set_flow_task_status(task["segment_id"], "已准备")
        self.reload_tasks()

        msg=(
            f"已发送 {len(payload)} 个通过验证的所选任务。\n"
            f"队列版本：{queue_version}\n"
            f"网页执行器版本：{host_version}\n"
            "生成命令不会触发上传或刷新；网页端会先同步网页生成素材，再写提示词并回读验证。"
        )
        if not_ready:
            msg += "\n\n未发送（图片未最终验证）：" + "、".join(not_ready[:8])
        if missing:
            msg += "\n\n未发送（缺少集合链接）：" + "、".join(missing[:8])
        QMessageBox.information(self, "已发送到网页执行器", msg)

    def open_flow(self):
        url = repo.get_setting("flow_url", DEFAULT_FLOW_URL) or DEFAULT_FLOW_URL
        profile = repo.get_setting("chrome_profile_directory", "Default") or "Default"
        try:
            chrome_profiles.launch_flow(profile, url)
        except Exception as exc:
            QMessageBox.critical(self, "打开 Flow 失败", str(exc))

    def open_settings(self):
        dlg = FlowSettingsDialog(self)
        if dlg.exec():
            self.sync_bridge_config()
            self.refresh_bridge_status()

    def copy_selected_for_plugin(self):
        tasks=self.require_selected()
        if not tasks:
            return
        text=flow_bridge.clipboard_tsv(tasks)
        QGuiApplication.clipboard().setText(text)
        QMessageBox.information(
            self,"已复制",
            f"已复制 {len(tasks)} 个任务到剪贴板。\n"
            "格式：任务ID / 参考图 / 人物文案 / 最终Flow提示词。"
        )

    @production_ui_action
    def mark_selected(self,status):
        tasks=self.require_selected()
        if not tasks:
            return
        for t in tasks:
            repo.set_flow_task_status(t["segment_id"],status)
        self.reload_tasks()

    @production_ui_action
    def reset_selected(self):
        ids=self.selected_ids()
        if not ids:
            QMessageBox.information(self,"重置任务","请先选择任务。")
            return
        if QMessageBox.question(
            self,"重置任务",
            f"将 {len(ids)} 个任务重置为“待生成”？"
        ) != QMessageBox.Yes:
            return
        repo.reset_flow_tasks(ids)
        self.reload_tasks()

    @production_ui_action
    def retry_selected_tasks(self):
        selected = self.require_selected()
        if not selected:
            return

        links={int(r["host_id"]):r for r in repo.list_flow_host_links(self.recipient.currentData(), work_date=work_dates.active())}
        by_host={}
        for task in selected:
            by_host.setdefault(int(task["host_id"]),[]).append(task)

        stamp=str(int(time.time()*1000))
        jobs=[]
        missing=[]
        not_ready=[]
        accepted_ids=set()
        for host_id,host_tasks in by_host.items():
            row=links.get(host_id)
            if not row or not (row["flow_collection_url"] or "").strip():
                missing.append(host_tasks[0]["host_name"])
                continue
            job=self._make_host_job(row,host_tasks)
            state=str(row["flow_upload_state"] or "idle")
            saved_fp=str(row["flow_upload_fingerprint"] or "")
            uploaded=int(row["flow_images_uploaded"] or 0)
            total=int(row["image_count"] or 0)
            if state!="verified" or saved_fp!=job["image_set_id"] or (total and uploaded<total):
                not_ready.append(f'{row["host_name"]} {uploaded}/{total} · {state}')
                continue
            ids=[int(t["segment_id"]) for t in host_tasks]
            repo.reset_flow_tasks(ids)
            accepted_ids.update(ids)
            job["open_window"]=False
            job["execute_upload"]=False
            job["dispatch_tasks"]=True
            job["auto_execute"]=True
            job["retry_only"]=True
            job["command_id"]=f'retry-selected-{host_id}-{stamp}'
            jobs.append(job)

        if not jobs:
            detail="选中任务暂时无法重新生成。"
            if not_ready:
                detail += "\n图片尚未通过验证："+"、".join(not_ready[:8])
            if missing:
                detail += "\n缺少 Flow 集合链接："+"、".join(missing[:8])
            QMessageBox.warning(self,"仅重试选中",detail)
            return

        for job in jobs:
            self.active_task_commands[int(job["host_id"])]=str(job["command_id"])
            repo.set_host_task_command(int(job["host_id"]), str(job["command_id"]))
        version=self.bridge.publish_host_jobs(jobs)
        for task in selected:
            if int(task["segment_id"]) in accepted_ids:
                repo.set_flow_task_status(task["segment_id"],"已准备")
        self.reload_tasks()
        msg=f"已将 {len(accepted_ids)} 个选中任务重新加入生成队列。\nBridge版本：{version}"
        if missing:
            msg += "\n未发送（缺少集合链接）："+"、".join(missing[:8])
        QMessageBox.information(self,"仅重试选中",msg)

    @production_ui_action
    def import_render_folder(self):
        folder=QFileDialog.getExistingDirectory(self,"选择 Flow 渲染结果文件夹")
        if not folder:
            return

        video_ext={".mp4",".mov",".m4v",".webm"}
        files=[
            p for p in Path(folder).iterdir()
            if p.is_file() and p.suffix.lower() in video_ext
        ]
        if not files:
            QMessageBox.information(self,"没有视频","这个文件夹中没有找到视频文件。")
            return

        matched=0
        unmatched=[]
        # Match 01-03 / 01_03 / 0103 token in filename.
        for p in files:
            normalized=p.stem.replace("_","-").replace(" ","-")
            found=False
            for task in self.task_rows:
                tid=f'{task["video_seq"]:02d}-{task["seg_seq"]:02d}'
                compact=tid.replace("-","")
                if tid in normalized or compact in normalized.replace("-",""):
                    repo.save_flow_output(task["segment_id"],str(p))
                    matched+=1
                    found=True
                    break
            if not found:
                unmatched.append(p.name)

        self.reload_tasks()
        msg=f"匹配并登记：{matched} 个视频。"
        if unmatched:
            msg+=f"\n未匹配：{len(unmatched)} 个。\n\n建议输出文件名包含 01-01 这类任务ID。"
        QMessageBox.information(self,"导入完成",msg)

    def open_preview(self,row,col):
        if 0<=row<len(self.task_rows):
            FlowTaskPreviewDialog(self.task_rows[row],self).exec()

    def dispatch_redo(self):
        pending=workflow.redo_ids(work_date=work_dates.active())
        if not pending: return
        by_host={}
        for t in repo.list_flow_tasks(work_date=work_dates.active()):
            if int(t['segment_id']) in pending: by_host.setdefault(int(t['host_id']),[]).append(t)
        for hid,tasks in by_host.items():
            r1=multi_channel.rework_channel(hid)
            if not r1 or not (r1['collection_url'] or '').strip(): continue
            if repo.get_flow_channel_task_command(r1['id']): continue
            row=next((x for x in repo.list_flow_host_links(work_date=work_dates.active()) if int(x['host_id'])==hid),None)
            if not row: continue
            # R1 always uses the full host image set so any rejected fragment can return immediately.
            job=self._make_channel_job(row,r1,tasks,preload_all_images=True)
            cmd=f"redo-{hid}-R1-{time.time_ns()}"
            proof=job['upload_proof']['verified']
            job.update(command_id=cmd,open_window=False,execute_upload=not proof,dispatch_tasks=True,auto_execute=True,retry_only=True,generation_count=1)
            repo.set_flow_channel_task_command(r1['id'],cmd)
            for t in tasks: repo.assign_flow_channel(t['segment_id'],'R1')
            self.bridge.publish_host_jobs([job])
        self.reload_tasks()

    def change_task_page(self, delta, reset=False):
        self.page_index = 0 if reset else self.page_index + delta
        self.reload_tasks()

    def select_task_scope(self, item, column):
        self.scope_key = item.data(0, Qt.UserRole)
        self.change_task_page(0, reset=True)

    def refresh_task_tree(self, rows):
        snapshot=self._view_cache
        if snapshot is None:return
        info=snapshot['tree']
        nodes=getattr(self,'_tree_nodes',{})
        top=getattr(self,'_tree_top',None)
        if top is None:
            top=QTreeWidgetItem(self.task_tree,['全部任务','']);top.setExpanded(True);self._tree_top=top
        top.setText(1,str(len(rows)))
        # Remove deepest nodes first, retaining expanded/selected state elsewhere.
        for key in reversed(list(nodes)):
            if key not in info:
                node=nodes.pop(key);parent=node.parent()
                if parent is not None:parent.removeChild(node)
        for key,(parent_key,title,done,total) in info.items():
            parent=nodes.get(parent_key,top)
            node=nodes.get(key)
            if node is None:
                node=QTreeWidgetItem(parent,[title,'']);node.setData(0,Qt.UserRole,key)
                node.setExpanded(key[0]=='recipient_id');nodes[key]=node
            elif node.parent() is not parent:
                node.parent().removeChild(node);parent.addChild(node)
            if node.text(0)!=title:node.setText(0,title)
            value=f'{done}/{total}'
            if node.text(1)!=value:node.setText(1,value)
        self._tree_nodes=nodes

    # ===== V0.13.2 multi-browser unlimited channel-pool overrides =====
    def refresh_channel_summary(self):
        if not hasattr(self,'channel_summary_label'):
            return
        cache=getattr(self,'_view_cache',None)
        if not self.isVisible() or not cache or cache['key'][0]!=work_dates.active():
            self.reload_tasks();return
        channels=cache['channels']
        now=time.time(); online=0; parts=[]
        a_count=sum(repo.channel_browser_group(c['channel_key'])=='A' for c in channels)
        b_count=sum(repo.channel_browser_group(c['channel_key'])=='B' for c in channels)
        for ch in channels:
            age=now-float(ch['last_seen'] or 0) if ch['last_seen'] else 999
            on=age<8; online+=1 if on else 0
            role='高速通道' if ch['role']=='fast' else '普通通道'
            group=repo.channel_browser_group(ch['channel_key'])
            load=cache['summaries'][str(ch['channel_key'])]['active']
            parts.append(f"{group}:{ch['channel_key']} {'🟢' if on else '⚪'} {role} · 负载 {load}")
        b_state='已启用' if cache['b_enabled'] else '未启用'
        self.channel_summary_label.setText(
            f"全局通道池：{online}/{len(channels)} 在线 · 浏览器A {a_count} 个 · 浏览器B {b_state}"
            + (f" {b_count} 个" if cache['b_enabled'] else "")
            + "  ｜  " + "  ｜  ".join(parts)
        )

    def refresh_channel_pool_table(self):
        if not hasattr(self,'channel_table'):
            return
        cache=getattr(self,'_view_cache',None)
        if not self.isVisible() or not cache or cache['key'][0]!=work_dates.active():
            self.reload_tasks();return
        channels=cache['channels']
        root=Path(cache['root']).expanduser()
        self.channel_table.setRowCount(len(channels))
        self._channel_rows=channels
        for i,ch in enumerate(channels):
            key=str(ch['channel_key']); group=repo.channel_browser_group(key)
            self.channel_table.setItem(i,0,QTableWidgetItem('浏览器'+group))
            self.channel_table.setItem(i,1,QTableWidgetItem(key))
            self.channel_table.setItem(i,2,QTableWidgetItem('高速通道' if ch['role']=='fast' else '普通通道'))
            edit=self.channel_table.cellWidget(i,3)
            if not isinstance(edit,QLineEdit):
                edit=QLineEdit(str(ch['collection_url'] or ''))
                edit.setPlaceholderText(f"粘贴 {key} 对应的 Flow 集合 / 端口链接")
                edit.editingFinished.connect(lambda k=key,e=edit:self._save_pool_link(k,e))
                self.channel_table.setCellWidget(i,3,edit)
            elif not edit.hasFocus():
                edit.setText(str(ch['collection_url'] or ''))
            folder=root/str(ch['download_subdir'] or key)
            self.channel_table.setItem(i,4,QTableWidgetItem(str(folder)))
            summary=cache['summaries'][key]
            self.channel_table.setItem(i,5,QTableWidgetItem(str(summary['active'])))
            age=time.time()-float(ch['last_seen'] or 0) if ch['last_seen'] else 999
            status_btn=self.channel_table.cellWidget(i,6)
            if not isinstance(status_btn,QPushButton):
                status_btn=QPushButton(); status_btn.setEnabled(False)
                self.channel_table.setCellWidget(i,6,status_btn)
            online=age<8
            health=str(ch['health_status'] or '')
            status_btn.setText('🟢 在线' if online else ('🟠 恢复中' if health in ('recovering','stale') else '⚪ 待连接'))
            status_btn.setStyleSheet('QPushButton{background:#163d2a;color:#7ee2a8;border:1px solid #2b7650;border-radius:7px;padding:5px 8px;font-weight:700;}' if online else 'QPushButton{background:#262b34;color:#aab2bf;border:1px solid #444b57;border-radius:7px;padding:5px 8px;}')
            page=str(ch['page_status'] or '')
            page_label='🟢 正常' if page in ('complete','loaded') else ('🔵 后台运行' if page=='background' else ('🟡 恢复中' if page in ('recovering','heartbeat_stale','discarded','loading') else (page or '待检测')))
            self.channel_table.setItem(i,7,QTableWidgetItem(page_label))
            recent=str(ch['last_status'] or ch['upload_state'] or '待命')
            if health=='quarantined': recent='🔴 已隔离 · '+recent
            if ch['last_error']: recent='🔴 '+str(ch['last_error'])[:120]
            self.channel_table.setItem(i,8,QTableWidgetItem(recent))

        signature=repr(cache['groups'])
        if signature!=getattr(self,'_browser_groups_signature',None):
            self._browser_groups_signature=signature
            self._refresh_browser_selector()
        self.refresh_channel_summary()

    def _current_browser_group(self):
        if hasattr(self,'channel_add_browser'):
            return str(self.channel_add_browser.currentData() or 'A')
        if hasattr(self,'browser_pool_selector'):
            return str(self.browser_pool_selector.currentData() or self.browser_pool_selector.currentText() or 'A').upper()
        return 'A'

    def _refresh_browser_selector(self):
        if not hasattr(self,'browser_pool_selector'): return
        current=self._current_browser_group()
        groups=self._view_cache['groups']
        self.browser_pool_selector.blockSignals(True)
        self.browser_pool_selector.clear()
        idx=0
        for i,g in enumerate(groups):
            label=f"浏览器{g['id']}" + ('' if g.get('enabled') else ' · 已关闭')
            self.browser_pool_selector.addItem(label,g['id'])
            if g['id']==current: idx=i
        self.browser_pool_selector.setCurrentIndex(idx if groups else -1)
        self.browser_pool_selector.blockSignals(False)
        if hasattr(self,'channel_add_browser'):
            self.channel_add_browser.blockSignals(True); self.channel_add_browser.clear()
            for g in groups: self.channel_add_browser.addItem('浏览器'+g['id'],g['id'])
            self.channel_add_browser.setCurrentIndex(max(0,self.channel_add_browser.findData(current)))
            self.channel_add_browser.blockSignals(False)
        self.browser_group_changed()

    def browser_group_changed(self):
        if not hasattr(self,'browser_pool_profile') or not getattr(self,'_view_cache',None): return
        gid=self._current_browser_group(); profile=next((g.get('profile') or 'Default' for g in self._view_cache['groups'] if g['id']==gid),'Default')
        idx=self.browser_pool_profile.findData(profile)
        if idx<0 and profile:
            self.browser_pool_profile.addItem(profile,profile); idx=self.browser_pool_profile.count()-1
        if idx>=0:self.browser_pool_profile.setCurrentIndex(idx)
        g=next((x for x in self._view_cache['groups'] if x['id']==gid),None)
        if hasattr(self,'fast_channel_btn'):
            self.fast_channel_btn.setText(('关闭' if g and g.get('fast_enabled') else '＋ 开启')+f' 浏览器{gid}高速通道')

    @production_ui_action
    def save_current_browser_profile(self):
        gid=self._current_browser_group(); profile=self.browser_pool_profile.currentData() or 'Default'
        repo.update_browser_group(gid,profile=profile,enabled=True)
        if gid=='A':
            repo.set_setting('flow_browser_a_profile',profile);repo.set_setting('chrome_profile_directory',profile)
        runtime_log.log('browser_profile_saved',browser=gid,profile=profile)
        self.refresh_channel_pool_table()

    @production_ui_action
    def add_browser_group_ui(self):
        gid=repo.add_browser_group(profile='Default',normal_count=0,fast_enabled=False)
        runtime_log.log('browser_group_added',browser=gid)
        self.refresh_channel_pool_table()
        idx=self.browser_pool_selector.findData(gid)
        if idx>=0:self.browser_pool_selector.setCurrentIndex(idx)
        if hasattr(self,'channel_add_browser'): self.channel_add_browser.setCurrentIndex(self.channel_add_browser.findData(gid))

    @production_ui_action
    def toggle_current_fast_channel(self):
        gid=self._current_browser_group(); g=next((x for x in repo.list_browser_groups(True) if x['id']==gid),None)
        if not g:return
        repo.update_browser_group(gid,enabled=True,fast_enabled=not bool(g.get('fast_enabled')))
        runtime_log.log('browser_fast_toggled',browser=gid,enabled=not bool(g.get('fast_enabled')))
        self.refresh_channel_pool_table()

    @production_ui_action
    def _save_pool_link(self,key,edit):
        if isinstance(edit,QLineEdit):
            repo.save_channel_pool(key,collection_url=edit.text().strip())
            runtime_log.log('channel_link_saved',channel=key,browser=repo.channel_browser_group(key),url=edit.text().strip())

    @production_ui_action
    def save_channel_pool(self):
        if hasattr(self,'_channel_rows'):
            for i,ch in enumerate(self._channel_rows):
                edit=self.channel_table.cellWidget(i,3)
                if isinstance(edit,QLineEdit): repo.save_channel_pool(ch['channel_key'],collection_url=edit.text().strip())
        self.save_current_browser_profile()
        lo=int(self.dispatch_stagger_min.value()); hi=int(self.dispatch_stagger_max.value())
        if hi<lo:
            lo,hi=hi,lo;self.dispatch_stagger_min.setValue(lo);self.dispatch_stagger_max.setValue(hi)
        repo.set_setting('flow_dispatch_stagger_min',str(lo));repo.set_setting('flow_dispatch_stagger_max',str(hi))
        channel_pool.ensure_defaults();self.refresh_channel_pool_table()
        runtime_log.log('channel_pool_saved',stagger_min=lo,stagger_max=hi,
                        browsers=repo.list_browser_groups(True),enabled_channels=[str(c['channel_key']) for c in repo.list_channel_pool(enabled_only=True)])
        QMessageBox.information(self,'通道设置','已保存。不同浏览器并行；10～15秒错峰仅在各浏览器内部独立运行。')

    @production_ui_action
    def add_normal_channel(self):
        gid=self._current_browser_group()
        repo.add_pool_channel(gid,'normal')
        runtime_log.log('channel_added',browser=gid,role='normal')
        self.refresh_channel_pool_table(); self.refresh_visual_monitor()

    @production_ui_action
    def add_fast_channel(self):
        gid=self._current_browser_group()
        repo.add_pool_channel(gid,'fast')
        runtime_log.log('channel_added',browser=gid,role='fast')
        self.refresh_channel_pool_table(); self.refresh_visual_monitor()

    def open_channel_link(self,key):
        channel=repo.get_channel_pool(channel_key=key)
        url=str(channel['collection_url'] or '').strip() if channel else ''
        if not url:
            QMessageBox.information(self,'打开通道','请先填写这个通道的 Flow 集合链接。'); return
        try:
            self.bridge.request_channel_focus(int(channel['id']),url)
        except ValueError as exc:
            QMessageBox.information(self,'定位通道',str(exc))

    # Legacy slots retained so older saved signal/state references remain harmless.
    @production_ui_action
    def toggle_browser_b(self):
        gid='B'; g=next((x for x in repo.list_browser_groups(True) if x['id']==gid),None)
        if g:repo.update_browser_group(gid,enabled=not g['enabled'])
        else:repo.add_browser_group(profile='Default',normal_count=0,fast_enabled=False)
        self.refresh_channel_pool_table()
    @production_ui_action
    def add_browser_b_normal_channel(self): repo.add_pool_channel('B','normal');self.refresh_channel_pool_table()
    @production_ui_action
    def toggle_browser_b_fast_channel(self):
        g=next((x for x in repo.list_browser_groups(True) if x['id']=='B'),None)
        if g:repo.update_browser_group('B',enabled=True,fast_enabled=not g['fast_enabled'])
        self.refresh_channel_pool_table()

    def open_all_channel_links(self):
        self.save_channel_pool()
        channels=[c for c in repo.list_channel_pool(enabled_only=True) if str(c['collection_url'] or '').strip()]
        if not channels:
            QMessageBox.information(self,'打开通道','请先填写至少一个 Flow 集合 / 端口链接。');return
        opened=[]
        for ch in channels:
            group=repo.channel_browser_group(ch['channel_key']);profile=repo.browser_profile(group) or 'Default';url=str(ch['collection_url'] or '').strip()
            chrome_profiles.launch_flow(profile,url)
            opened.append({'browser':group,'profile':profile,'channel':str(ch['channel_key']),'url':url})
        runtime_log.log('open_all_channels',count=len(opened),channels=opened)

    @production_ui_action
    def reclaim_unsubmitted_tasks(self):
        rows=list(repo.list_stale_unsubmitted_dispatches(threshold_seconds=int(repo.get_setting('unsubmitted_reclaim_seconds','300') or 300)))
        if not rows:
            QMessageBox.information(self,'释放未生成任务','当前没有超过超时且仍处于“从未提交”状态的任务。')
            return
        commands=sorted({str(r['command_id']) for r in rows})
        if QMessageBox.question(self,'释放未生成任务',
            f'发现 {len(rows)} 个卡住且没有任何提交回执的任务。\n\n将先从 Bridge 取消 {len(commands)} 个旧命令，再把这些片段放回待生成队列。\n已提交/生成中/下载中的任务不会移动。\n\n继续吗？') != QMessageBox.Yes:
            return
        self.bridge.cancel_host_commands(commands)
        count=repo.requeue_unsubmitted_dispatches([int(r['id']) for r in rows])
        runtime_log.log('stale_unsubmitted_reclaimed',dispatches=count,commands=commands)
        self.reload_tasks();self.refresh_channel_pool_table()
        QMessageBox.information(self,'释放完成',f'已安全释放 {count} 个从未提交的任务，并放回待生成队列；调度器会重新分配到健康通道。')

    def open_runtime_log(self):
        d=QDialog(self);d.setWindowTitle('Flow Studio 详细运行日志');d.resize(1000,680)
        lay=QVBoxLayout(d)
        path=runtime_log.path()
        info=QLabel(f'日志文件：{path}',objectName='muted');info.setWordWrap(True);lay.addWidget(info)
        box=QPlainTextEdit();box.setReadOnly(True);box.setPlainText(runtime_log.tail());lay.addWidget(box,1)
        row=QHBoxLayout(); refresh=QPushButton('刷新'); refresh.clicked.connect(lambda:box.setPlainText(runtime_log.tail()));row.addWidget(refresh)
        copy=QPushButton('复制日志路径'); copy.clicked.connect(lambda:QGuiApplication.clipboard().setText(str(path)));row.addWidget(copy);row.addStretch(1)
        close=QPushButton('关闭'); close.clicked.connect(d.accept);row.addWidget(close);lay.addLayout(row)
        d.exec()

    def refresh_link_table(self):
        cache=getattr(self,'_view_cache',None)
        if not self.isVisible() or not cache or cache['key'][0]!=work_dates.active():
            self.reload_tasks();return
        self.link_rows=cache['links']
        self.link_table.setRowCount(len(cache['link_values']))
        for i, values in enumerate(cache['link_values']):
            for c, value in enumerate(values):
                text=str(value)
                item=self.link_table.item(i,c)
                if item is None:self.link_table.setItem(i,c,QTableWidgetItem(text))
                elif item.text()!=text:item.setText(text)

    def refresh_live_connection_states(self):
        now = time.monotonic()
        if now - getattr(self, '_last_watchdog_tick', 0) > 10:
            self._last_watchdog_tick = now
            self._queue_production('watchdog')
        self.reload_tasks()

    def _pool_scope_tasks(self, redo=False):
        rid=self.recipient.currentData() if hasattr(self,'recipient') else None
        hid=self.host.currentData() if hasattr(self,'host') else None
        rows=[dict(t) for t in repo.list_flow_tasks(None if redo else rid,None if redo else hid,'全部', work_date=work_dates.active())]
        redo_ids=workflow.redo_ids(work_date=work_dates.active())
        if redo:
            return [t for t in rows if int(t['segment_id']) in redo_ids and t['flow_status'] in ('待生成','已准备') and not str(t['generation_command'] or '')]
        out=[]

        for t in rows:
            if int(t['segment_id']) in redo_ids: continue
            status=t['flow_status'] or '待生成'; command=str(t['generation_command'] or '')
            if command: continue
            if status not in ('待生成','已准备'): continue
            

            out.append(t)
            
        return out

    def _make_pool_job(self,ch,tasks,command_id,generation_count=None,execute_upload=False,dispatch_tasks=False,retry_only=False,work_date=None):

        from app.services.text_processing import flow_timing
        tasks=channel_pool.prepare_task_images(tasks,work_date or work_dates.active())
        paths=channel_pool.unique_images(tasks)
        image_files,fp=channel_pool.image_payload(paths)
        try: rounds=int(generation_count if generation_count is not None else (self.generation_count.currentData() or 1))
        except Exception: rounds=1
        rounds=max(1,min(4,rounds))
        payload=[]
        for order,t in enumerate(tasks,1):
            base=channel_pool.task_stem(t,1)
            if rounds>1 and base.endswith('-R01'): base=base[:-4]
            exact_names=[channel_pool.render_stem(t,r,rounds) for r in range(1,rounds+1)]
            payload.append({
                'segment_id':int(t['segment_id']), 'task_id':f"{int(t['video_seq']):02d}-{int(t['seg_seq']):02d}",
                'task_name':base, 'download_stem':base, 'download_names':exact_names, 'dispatch_order':order,
                **__import__('app.services.duration_choices',fromlist=['dispatch_timing']).dispatch_timing(t), 'dialogue':t['foreign_text'] or '', 'prompt':t['prompt'] or '', 'image_path':t['image_path'] or '',
                'generation_mode':repo.normalize_generation_mode(t['generation_mode'] if 'generation_mode' in t.keys() else 'FRAME'),
                'document_number':int(t['video_seq']), 'host_id':int(t['host_id']), 'host_name':t['host_name'],
                'recipient_id':int(t['recipient_id']), 'recipient_name':t['recipient_name'],
                'video_seq':int(t['video_seq']), 'seg_seq':int(t['seg_seq']), 'flow_retry_count':int(t['flow_retry_count'] or 0)
            })
        verified=(str(ch['upload_state'] or '')=='verified' and str(ch['upload_fingerprint'] or '')==fp and (not paths or int(ch['images_uploaded'] or 0)>=len(paths)) and bool(ch['upload_verified_at']))
        footage='MIXED' if any(str(t.get('generation_mode') or 'FRAME')=='MATERIAL' for t in payload) else 'VIDEO_FRAMES'
        return {
            'work_date':str(work_date or work_dates.active()),
            'recipient_id':0,'host_id':0,'recipient_name':'通道池','host_name':str(ch['channel_key']),
            'channel_id':int(ch['id']),'channel_key':str(ch['channel_key']),'channel_role':str(ch['role']),
            'browser_group':repo.channel_browser_group(str(ch['channel_key'])),
            'collection_url':str(ch['collection_url'] or ''),'collection_name':str(ch['channel_key']),
            'download_folder':channel_pool.relative_download_folder(ch),
            'image_count':len(paths),'image_files':image_files,'image_set_id':fp,'expected_image_names':[x['name'] for x in image_files],
            'upload_batches':[paths[i:i+20] for i in range(0,len(paths),20)],
            'upload_proof':{'verified':verified,'host_id':0,'channel_id':int(ch['id']),'image_set_id':str(ch['upload_fingerprint'] or '') if verified else '',
                            'collection_url':str(ch['collection_url'] or '') if verified else '', 'upload_command_id':str(ch['upload_command_id'] or '') if verified else '',
                            'uploaded':int(ch['images_uploaded'] or 0) if verified else 0,'verified_at':str(ch['upload_verified_at'] or '') if verified else ''},
            'tasks':payload,'settings':self.plugin_settings_payload(),'footage_mode':footage,'footage_mode_label':'混合' if footage=='MIXED' else ('帧' if footage=='VIDEO_FRAMES' else '素材'),
            'generation_count':rounds,'generation_count_label':str(rounds),'open_window':False,'focus_window':False,
            'execute_upload':bool(execute_upload),'dispatch_tasks':bool(dispatch_tasks),'auto_execute':bool(dispatch_tasks),'retry_only':bool(retry_only),
            'command_id':str(command_id),'studio_upload_state':str(ch['upload_state'] or 'idle'),'studio_upload_fingerprint':str(ch['upload_fingerprint'] or '')
        }

    def _validate_channel_pool_urls(self, channels):
        seen={};duplicates=[];missing=[]
        for ch in channels:
            key=str(ch['channel_key']); url=str(ch['collection_url'] or '').strip()
            if not url:
                missing.append(key); continue
            norm=url.split('#',1)[0].strip().lower()
            if norm in seen:duplicates.append((seen[norm],key))
            else:seen[norm]=key
        if missing:
            QMessageBox.warning(self,'通道缺少链接','请先填写：'+'、'.join(missing))
            runtime_log.log('channel_url_validation_failed',level='WARNING',reason='missing',channels=missing)
            return False
        if duplicates:
            pairs='；'.join(f'{a} 与 {b}' for a,b in duplicates)
            QMessageBox.warning(self,'通道链接重复',f'每个通道必须对应一个独立的 Flow 集合链接。\n重复：{pairs}')
            runtime_log.log('channel_url_validation_failed',level='WARNING',reason='duplicate',pairs=duplicates)
            return False
        return True

    @production_ui_action
    def upload_all_host_images(self):
        self.save_channel_pool()
        tasks=self._pool_scope_tasks(False)
        if not tasks:
            QMessageBox.information(self,'上传图片','当前筛选范围没有待生成任务。');return
        channels=channel_pool.available_channels('normal',work_date=work_dates.active())
        if not self._validate_channel_pool_urls(channels): return
        plan=channel_pool.plan(tasks,channels);jobs=[];stamp=str(time.time_ns())
        for ch in channels:
            ctasks=plan.get(str(ch['channel_key']),[])
            if not ctasks: continue
            cmd=f"upload-pool-{ch['channel_key']}-{stamp}"
            job=self._make_pool_job(ch,ctasks,cmd,execute_upload=True,dispatch_tasks=False)
            repo.set_channel_pool_runtime(ch['channel_key'],'queued',command_id=cmd,fingerprint=job['image_set_id'],uploaded=0,total=job['image_count'],error='')
            jobs.append(job)
            runtime_log.log('channel_upload_planned',browser=job.get('browser_group','A'),channel=ch['channel_key'],command_id=cmd,tasks=[t['task_name'] for t in job['tasks']],images=job['expected_image_names'])
        if jobs:
            ver=self.bridge.publish_host_jobs(jobs)
            self.refresh_channel_pool_table()
            QMessageBox.information(self,'上传图片',f'调度器已向 {len(jobs)} 个普通通道发送图片准备任务。\nBridge版本：{ver}')

    @production_ui_action
    def generate_all_host_tasks(self):
        self.save_channel_pool()
        pressure=pipeline_orchestrator.backpressure_state()
        if pressure.get('throttled'):
            if QMessageBox.question(self,'生产节流提醒',
                f"下游当前存在积压：{pressure.get('reason','')}。\n\n继续大量派发 Flow 任务可能让质检/剪辑队列继续堆高。是否仍继续？") != QMessageBox.Yes:
                return
        tasks=self._pool_scope_tasks(False)
        if not tasks:
            QMessageBox.information(self,'统一开始生成','当前筛选范围没有待生成任务。');return
        channels=channel_pool.available_channels('normal',work_date=work_dates.active())
        if not channels:
            QMessageBox.warning(self,'统一开始生成','当前没有已启用的普通通道。');return
        if not self._validate_channel_pool_urls(channels): return
        plan=channel_pool.plan(tasks,channels);jobs=[];stamp=str(time.time_ns())
        try: rounds=max(1,min(4,int(self.generation_count.currentData() or 1)))
        except Exception: rounds=1
        for ch in channels:
            ctasks=plan.get(str(ch['channel_key']),[])
            if not ctasks: continue
            cmd=f"generate-pool-{ch['channel_key']}-{stamp}"
            prelim=self._make_pool_job(ch,ctasks,cmd,generation_count=rounds,dispatch_tasks=True)
            need_upload=not bool(prelim['upload_proof']['verified'])
            job=self._make_pool_job(ch,ctasks,cmd,generation_count=rounds,execute_upload=need_upload,dispatch_tasks=True)
            repo.set_channel_pool_task_command(ch['channel_key'],cmd)
            if need_upload:
                repo.set_channel_pool_runtime(ch['channel_key'],'queued',command_id=cmd,fingerprint=job['image_set_id'],uploaded=0,total=job['image_count'],error='')
            for order,t in enumerate(ctasks,1):
                repo.assign_flow_channel(t['segment_id'],ch['channel_key'])
                for r in range(1,rounds+1):
                    stem=channel_pool.render_stem(t,r,rounds)
                    repo.create_dispatch(t['segment_id'],ch['channel_key'],cmd,order,r,stem,stem+'.mp4','queued')
            jobs.append(job)
        if not jobs:return
        lo,hi=channel_pool.stagger_bounds()
        jobs=channel_pool.apply_random_release_schedule(jobs,minimum=lo,maximum=hi)
        base_release=min(float(j.get('release_at') or time.time()) for j in jobs)
        for job in jobs:
            delay=max(0.0,float(job.get('release_at') or base_release)-base_release)
            repo.set_dispatch_release_for_command(job['command_id'],job.get('release_at') or 0)
            runtime_log.log('channel_generation_planned',browser=job.get('browser_group','A'),channel=job['channel_key'],command_id=job['command_id'],
                            rounds=rounds,upload_first=bool(job.get('execute_upload')),release_order=job.get('release_order'),
                            release_delay_seconds=round(delay,2),release_at=job.get('release_at'),stagger_range=f'{lo}-{hi}',
                            assignments=[{'order':t.get('dispatch_order'),'segment_id':t.get('segment_id'),'task':t.get('task_name')} for t in job.get('tasks',[])])
        ver=self.bridge.publish_host_jobs(jobs)
        self.reload_tasks();self.refresh_channel_pool_table()
        last_delay=max(float(j.get('release_at') or base_release)-base_release for j in jobs)
        QMessageBox.information(self,'统一开始生成',
            f'已分配 {sum(len(j["tasks"]) for j in jobs)} 个片段到 {len(jobs)} 个普通通道。\n'
            f'不同浏览器同时并行；每个浏览器内部按 {lo}～{hi} 秒随机间隔独立释放普通通道。\n'
            f'当前所有浏览器中，最晚通道约 {int(round(last_delay))} 秒后收到任务。\nBridge版本：{ver}\n高速通道不参与普通错峰。')

    def dispatch_redo(self):
        self._queue_production('redo')

    def _dispatch_redo_ready_tasks(self):
        if bool(self.bridge.generation_control().get('paused')):
            return
        from app.services import task_recovery
        task_recovery.queue_failures()
        self.notify_blocked_tasks()
        pending=self._pool_scope_tasks(True)
        readable=[]
        for task in pending:
            try:
                channel_pool.resolve_task_image_path(task);readable.append(task)
            except Exception as exc:
                runtime_log.log('rework_image_blocked',level='ERROR',segment_id=task['segment_id'],error=str(exc))
        pending=readable
        if not pending:return
        fast=channel_pool.available_channels('fast',work_date=work_dates.active())
        preferred=task_recovery.preferred_channels(pending)
        available={str(c['channel_key']):c for c in fast+channel_pool.available_channels('normal',work_date=work_dates.active())}
        plan={};chosen={}
        for task in pending:
            key=preferred.get(task['segment_id'])
            candidates=[available[key]] if key in available else ([] if key else (fast or (list(available.values()) if task['segment_id'] in preferred else [])))
            for ch in candidates:
                k=str(ch['channel_key'])
                if k not in plan:plan[k]=[task];chosen[k]=ch;break
        fast=list(chosen.values())
        if not fast:return
        jobs=[];stamp=str(time.time_ns())
        for ch in fast:
            ctasks=plan.get(str(ch['channel_key']),[])
            if not ctasks:continue
            cmd=f"redo-pool-{ch['channel_key']}-{stamp}"
            job=self._make_pool_job(ch,ctasks,cmd,generation_count=1,dispatch_tasks=True,retry_only=True)
            job['execute_upload']=True; job['force_media_scan']=True; job['release_at']=time.time()
            repo.set_channel_pool_task_command(ch['channel_key'],cmd)
            if job['execute_upload']:
                repo.set_channel_pool_runtime(ch['channel_key'],'queued',command_id=cmd,fingerprint=job['image_set_id'],uploaded=0,total=job['image_count'],error='')
            for order,t in enumerate(ctasks,1):
                repo.assign_flow_channel(t['segment_id'],ch['channel_key'])
                stem=channel_pool.task_stem(t,1)
                repo.create_dispatch(t['segment_id'],ch['channel_key'],cmd,order,1,stem,stem+'.mp4','queued')
            jobs.append(job)
            runtime_log.log('fast_rework_dispatched',browser=job.get('browser_group','A'),channel=ch['channel_key'],command_id=cmd,
                            tasks=[channel_pool.task_stem(t,1) for t in ctasks],immediate=True)
        if jobs:
            self.bridge.publish_host_jobs(jobs)
            self.reload_tasks();self.refresh_channel_pool_table()

    @staticmethod
    def _channel_download_worker():
        try:
            changed = workflow.recover_pending_downloads()
        except Exception as exc:
            runtime_log.log('download_recovery_worker_failed', level='ERROR', error=str(exc))
            changed = False
        try:
            matches = channel_pool.scan_downloads()
        except Exception as exc:
            runtime_log.log('channel_scan_failed', level='ERROR', error=str(exc))
            return changed
        for dispatch, ch, path in matches:
            try:
                if workflow.accept_channel_file(dispatch, str(path)):
                    changed = True
            except Exception as exc:
                try:
                    repo.update_dispatch(int(dispatch['id']), status='failed', download_path=str(path), error=str(exc))
                except Exception:
                    pass
                runtime_log.log('channel_file_accept_failed', level='ERROR', channel=ch['channel_key'], path=str(path), error=str(exc))
        return changed

    @measured('file_scan')
    def process_channel_downloads(self):
        # Never scan folders or write accepted download records on the GUI thread.
        if self._download_scan_future is None:
            self._download_scan_future = self.download_executor.submit(self._channel_download_worker)
            return
        if not self._download_scan_future.done():
            return
        try:
            changed = bool(self._download_scan_future.result())
        except Exception as exc:
            runtime_log.log('channel_scan_worker_failed', level='ERROR', error=str(exc))
            changed = False
        finally:
            self._download_scan_future = None
        if changed:
            self.reload_tasks(); self.refresh_channel_pool_table()
            if self.parent_window and hasattr(self.parent_window,'qc_page'):
                self.parent_window.qc_page.mark_dirty()
                if self.parent_window.davinci_page.isVisible():self.parent_window.davinci_page.reload()


    @production_ui_action
    def remove_pool_channel(self,key):
        key=str(key)
        # Hide the card right now and keep it hidden even if an in-flight monitor snapshot
        # (taken before the removal) is still delivered; entries expire after a few seconds.
        pend=getattr(self,'_pending_removed_channels',None)
        if pend is None:pend=self._pending_removed_channels={}
        pend[key]=time.time()+15
        try:
            result=repo.remove_pool_channel(key) or {}
            commands=result.get('commands') or []
            if commands:
                try:self.bridge.cancel_host_commands(commands)
                except Exception as exc:runtime_log.log('remove_channel_bridge_cancel_failed',level='WARNING',channel=key,error=str(exc))
            runtime_log.log('channel_removed_tasks_transferred',channel=key,commands=commands,segments=result.get('segments',[]))
            self.sync_bridge_config();self.refresh_visual_monitor();self.refresh_channel_pool_table()
        except Exception as exc:
            pend.pop(key,None)
            entry=(getattr(self,'_monitor_channels',None) or {}).get(key)
            if entry:entry['card'].show()
            QMessageBox.warning(self,'移除通道',str(exc))

    def notify_blocked_tasks(self):
        # This method is called by the realtime scheduler. A modal warning dialog here
        # becomes a popup storm when delayed duplicate failure receipts arrive. Keep the
        # failure cap and manual-retry state, but acknowledge new blocked tasks silently and
        # write one aggregated runtime-log entry instead. The tasks remain visible in
        # “运行任务 / 重试”.
        from app.core.database import connect
        with connect() as con:
            rows=con.execute('SELECT segment_id FROM flow_recovery WHERE blocked=1 AND notified=0').fetchall()
            if not rows:return
            con.execute('UPDATE flow_recovery SET notified=1 WHERE blocked=1 AND notified=0')
        runtime_log.log('generation_retry_cap_reached',level='WARNING',
                        segment_ids=[int(r[0]) for r in rows],count=len(rows),
                        message='累计生成失败 3 次，已停止自动重试；请在运行任务 / 重试中人工处理')

    def show_runtime_tasks(self):
        if getattr(self, "_runtime_dialog", None) is not None:
            self._runtime_dialog.show(); self._runtime_dialog.raise_(); self._runtime_dialog.activateWindow()
            return
        from app.ui.runtime_tasks import RuntimeTasksDialog
        dialog=RuntimeTasksDialog(self);dialog.setAttribute(Qt.WA_DeleteOnClose);dialog.show()
        self._runtime_dialog=dialog
        dialog.destroyed.connect(lambda: setattr(self, "_runtime_dialog", None))
