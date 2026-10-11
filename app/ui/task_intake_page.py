from __future__ import annotations

from pathlib import Path
from app.services import quiet_process as subprocess

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QPlainTextEdit,
    QDialog, QDialogButtonBox, QProgressBar, QFileDialog, QCheckBox, QSpinBox,
    QScrollArea, QGridLayout, QSizePolicy, QSplitter, QComboBox
)
from PySide6.QtGui import QPixmap, QDesktopServices
from app.ui.image_preview import set_image

from app.core import repository as repo
from app.ui import workspace_intake
from app.core import work_dates
from app.services import pre_gpt_pipeline as intake
from app.services.file_filters import is_valid_local_image
from app.services.material_assignment import material_folder
from app.ui.modern_widgets import ClickableFrame


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
                data["promote"] = intake.promote_ready_to_studio()
            elif self.action == "rescan_local":
                from app.services.local_host_materials import rescan
                data = rescan(self.group_key, self.payload['day'], self._emit_progress, random_fill=self.payload.get("random_fill", False))
            elif self.action == "delete_host":
                from app.services.delete_selected_host import execute
                data = execute(self.payload)
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


class ManualClassifyDialog(QDialog):
    """Small always-on-top confirmation for mixed TALKING/PRAYING material."""
    completed = Signal(str)

    def __init__(self, group: dict, parent=None):
        super().__init__(parent)
        self.group = group
        self.group_key = group["group_key"]
        self.required = int(group.get("praying") or 0)
        self.selected = []
        self.setWindowTitle("闭眼素材确认")
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.resize(460, 250)

        root = QVBoxLayout(self)
        title = QLabel(f'{group.get("anchor_name", "主播")} · 闭眼素材确认')
        title.setStyleSheet("font-size:20px;font-weight:800;")
        root.addWidget(title)
        tip = QLabel(
            '请在访达中给闭眼图片的文件名加上“闭眼”，可带其他文字。'
            '确认后扫描本地文件夹，同类任务可共用图片，不读取当前选中项。',
            objectName="muted"
        )
        tip.setWordWrap(True)
        root.addWidget(tip)
        self.counter = QLabel(f"尚未扫描本地图片")
        self.counter.setStyleSheet("font-size:18px;font-weight:700;")
        root.addWidget(self.counter)
        self.note = QLabel("", objectName="muted")
        self.note.setWordWrap(True)
        root.addWidget(self.note)

        row = QHBoxLayout()
        open_btn = QPushButton("打开 Finder")
        open_btn.clicked.connect(self.open_finder)
        row.addWidget(open_btn)
        refresh_btn = QPushButton("扫描文件名")
        refresh_btn.clicked.connect(self.refresh_selection)
        row.addWidget(refresh_btn)
        self.confirm_btn = QPushButton("确认并继续", objectName="primaryBtn")
        self.confirm_btn.setEnabled(True)
        self.confirm_btn.clicked.connect(self.confirm)
        row.addWidget(self.confirm_btn)
        root.addLayout(row)

        cancel = QDialogButtonBox(QDialogButtonBox.Close)
        cancel.rejected.connect(self.reject)
        root.addWidget(cancel)
        QTimer.singleShot(150, self.open_finder)

    def open_finder(self):
        try:
            intake.finder_open(self.group_key)
            self.note.setText("访达已打开，请重命名闭眼图片，完成后点击确认。")
        except Exception as exc:
            self.note.setText(str(exc))

    def refresh_selection(self):
        try:
            files=intake.scan_named_materials(self.group_key)
            self.selected=[str(p) for p in files if '闭眼' in p.stem]
            self.counter.setText(f'识别闭眼图片：{len(self.selected)} 张')
            self.note.setText('可以确认' if self.selected else '请给图片文件名加上“闭眼”后再确认')
        except Exception as exc:self.note.setText(str(exc))

    def confirm(self):
        try:
            result=intake.confirm_named_materials(self.group_key)
            intake.promote_ready_to_studio()
            self.note.setText(result['message']);self.completed.emit(self.group_key);self.accept()
        except Exception as exc:QMessageBox.warning(self,'素材确认',str(exc))


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
        self.page_content.setMinimumWidth(760)
        root = QVBoxLayout(self.page_content)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)
        root.setAlignment(Qt.AlignTop)
        self.page_scroll.setWidget(self.page_content)
        outer.addWidget(self.page_scroll)

        # Header + only the daily actions we actually use.
        top = QHBoxLayout()
        titles = QVBoxLayout()
        titles.addWidget(QLabel("任务中心", objectName="pageTitle"))
        titles.addWidget(QLabel("同步任务、管理主播文案与图片，并进入后续生产流程", objectName="pageSubtitle"))
        top.addLayout(titles); top.addStretch(1)
        self.sync_btn = QPushButton("同步任务", objectName="primaryBtn"); self.sync_btn.clicked.connect(self.sync_all); top.addWidget(self.sync_btn)
        clear_btn=QPushButton("清空当前任务"); clear_btn.clicked.connect(lambda: self.clear_tasks(False)); top.addWidget(clear_btn)
        reset_btn=QPushButton("清空并重新同步"); reset_btn.clicked.connect(lambda: self.clear_tasks(True)); top.addWidget(reset_btn)
        root.addLayout(top)

        # Compact summary strip.
        strip=QFrame(objectName="topStrip"); sr=QHBoxLayout(strip); sr.setContentsMargins(14,9,14,9); sr.setSpacing(22)
        self.summary = QLabel("", objectName="compactMetric"); self.summary.setWordWrap(True); sr.addWidget(self.summary,1)
        self.google_state = QLabel("Google：检测中…", objectName="muted"); sr.addWidget(self.google_state)
        root.addWidget(strip)

        date_row=QHBoxLayout()
        self.date_hint=QLabel();self.date_hint.setWordWrap(True);date_row.addWidget(self.date_hint,1)
        self.available_dates=QComboBox();date_row.addWidget(self.available_dates)
        self.show_date_btn=QPushButton('查看该日期任务');self.show_date_btn.clicked.connect(self.show_available_date);date_row.addWidget(self.show_date_btn)
        root.addLayout(date_row)

        # Visible sync progress panel. A determinate percentage is much more useful than
        # an indeterminate spinner when a full Sheet -> Drive -> Studio sync can take minutes.
        self.progress_box = QFrame(objectName="topStrip")
        pv = QVBoxLayout(self.progress_box); pv.setContentsMargins(14,10,14,10); pv.setSpacing(6)
        phr = QHBoxLayout()
        self.progress_label = QLabel("同步进度 · 就绪", objectName="cardTitle")
        self.progress_percent = QLabel("0%", objectName="compactMetric")
        phr.addWidget(self.progress_label); phr.addStretch(1); phr.addWidget(self.progress_percent)
        pv.addLayout(phr)
        self.progress = QProgressBar(); self.progress.setRange(0,100); self.progress.setValue(0); self.progress.setTextVisible(False); pv.addWidget(self.progress)
        self.progress_detail = QLabel("等待同步任务", objectName="muted"); self.progress_detail.setWordWrap(True); pv.addWidget(self.progress_detail)
        root.addWidget(self.progress_box)

        # Recipient cards: first-level navigation, no tree/drop-down.
        recipient_head=QHBoxLayout(); recipient_head.addWidget(QLabel("接收人",objectName="sectionTitle")); recipient_head.addStretch(1)
        root.addLayout(recipient_head)
        self.recipient_scroll=QScrollArea(objectName="cardScroll"); self.recipient_scroll.setWidgetResizable(True); self.recipient_scroll.setFrameShape(QFrame.NoFrame); self.recipient_scroll.setFixedHeight(132); self.recipient_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded); self.recipient_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.recipient_content=QWidget(objectName="scrollContent"); self.recipient_cards=QHBoxLayout(self.recipient_content); self.recipient_cards.setContentsMargins(0,0,0,4); self.recipient_cards.setSpacing(10); self.recipient_cards.setAlignment(Qt.AlignLeft|Qt.AlignTop); self.recipient_scroll.setWidget(self.recipient_content); root.addWidget(self.recipient_scroll)

        body=QSplitter(Qt.Horizontal); body.setChildrenCollapsible(False); body.setHandleWidth(8)
        # Host card workspace.
        hosts_wrap=QFrame(objectName="pageCard"); hv=QVBoxLayout(hosts_wrap); hv.setContentsMargins(14,12,14,12); hv.setSpacing(10)
        self.hosts_title=QLabel("AI 主播",objectName="sectionTitle"); hv.addWidget(self.hosts_title)
        self.host_scroll=QScrollArea(objectName="cardScroll"); self.host_scroll.setWidgetResizable(True); self.host_scroll.setFrameShape(QFrame.NoFrame)
        self.host_content=QWidget(objectName="scrollContent"); self.host_grid=QGridLayout(self.host_content); self.host_grid.setContentsMargins(0,0,0,0); self.host_grid.setHorizontalSpacing(10); self.host_grid.setVerticalSpacing(10); self.host_grid.setAlignment(Qt.AlignTop|Qt.AlignLeft); self.host_scroll.setWidget(self.host_content); hv.addWidget(self.host_scroll,1); body.addWidget(hosts_wrap)

        # Detail panel: all infrequent actions live here instead of cluttering the page.
        detail=QFrame(objectName="detailPanel"); dv=QVBoxLayout(detail); dv.setContentsMargins(16,14,16,14); dv.setSpacing(10)
        self.detail_title=QLabel("选择一个主播",objectName="sectionTitle"); dv.addWidget(self.detail_title)
        self.detail_meta=QLabel("点击左侧主播卡片查看任务与素材情况。",objectName="muted"); self.detail_meta.setWordWrap(True); dv.addWidget(self.detail_meta)
        self.detail_preview=QLabel("暂无素材",objectName="thumb"); self.detail_preview.setAlignment(Qt.AlignCenter); self.detail_preview.setMinimumHeight(170); dv.addWidget(self.detail_preview)
        self.detail_counts=QLabel("",objectName="cardMeta"); self.detail_counts.setWordWrap(True); dv.addWidget(self.detail_counts)
        self.detail_status=QLabel("",objectName="statusInfo"); self.detail_status.setWordWrap(True); dv.addWidget(self.detail_status)
        self.manage_hint=QLabel("主播准备完成后，可直接在任务中心管理中文、外文文案和编号图片。",objectName="muted")
        self.manage_hint.setWordWrap(True); dv.addWidget(self.manage_hint)
        self.manage_btn=QPushButton("管理文案 / 图片",objectName="primaryBtn")
        self.manage_btn.clicked.connect(self.open_selected_host_manager); dv.addWidget(self.manage_btn)
        dv.addStretch(1)
        self.download_btn=QPushButton("同步该主播素材"); self.download_btn.clicked.connect(self.download_selected); dv.addWidget(self.download_btn)
        self.rescan_btn=QPushButton("重新扫描选中主播的本地素材")
        self.rescan_btn.clicked.connect(self.rescan_selected); dv.addWidget(self.rescan_btn)
        self.fill_btn=QPushButton("随机补齐缺少的图片")
        self.fill_btn.clicked.connect(lambda: self.rescan_selected(random_fill=True)); dv.addWidget(self.fill_btn)
        self.delete_host_btn=QPushButton("删除选中主播")
        self.delete_host_btn.clicked.connect(self.delete_selected_host); dv.addWidget(self.delete_host_btn)
        self.manual_btn=QPushButton("调整原始图片类型"); self.manual_btn.clicked.connect(self.open_manual_for_selected); dv.addWidget(self.manual_btn)
        open_folder=QPushButton("打开本地素材文件夹"); open_folder.clicked.connect(self.open_selected_folder); dv.addWidget(open_folder)
        body.addWidget(detail); body.setSizes([820,380]); body.setMinimumHeight(420); body.setMaximumHeight(720); root.addWidget(body)

        # Compatibility controls are kept but hidden; connection is normally configured in Settings.
        self._connect_google_btn=QPushButton(); self._switch_google_btn=QPushButton()
        self.status=QLabel("就绪",objectName="muted"); root.addWidget(self.status)
        self.log=QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumBlockCount(2500); self.log.hide(); root.addWidget(self.log)

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

        self._clear_box(self.recipient_cards)
        for name in recipients:
            owned=[g for g in groups if str(g.get("recipient") or "")==name]
            task_count=sum(int(g.get("talking",0) or 0)+int(g.get("praying",0) or 0) for g in owned)
            bad=sum(1 for g in owned if str(g.get("status") or "") not in ("READY_FOR_GPT",))
            card=ClickableFrame(objectName="recipientCard"); card.setProperty("selected", str(name==self.selected_recipient).lower()); card.setFixedWidth(175); card.setFixedHeight(104)
            row=QHBoxLayout(card); row.setContentsMargins(10,10,10,10)
            ini=QLabel(name[:1] if name else "?",objectName="recipientInitial"); ini.setAlignment(Qt.AlignCenter); row.addWidget(ini)
            info=QVBoxLayout(); info.addWidget(QLabel(name,objectName="cardTitle")); info.addWidget(QLabel(f"{len(owned)} 主播 · {task_count} 文案",objectName="cardMeta")); info.addWidget(QLabel((f"⚠ {bad} 待处理" if bad else "✓ 素材正常"),objectName="statusWarn" if bad else "statusGood")); row.addLayout(info,1)
            card.clicked.connect(lambda n=name:self.select_recipient(n)); self.recipient_cards.addWidget(card)
        self.recipient_cards.addStretch(1)

        self._clear_box(self.host_grid)
        selected=[g for g in groups if not self.selected_recipient or str(g.get("recipient") or "")==self.selected_recipient]
        self.hosts_title.setText(f"{self.selected_recipient or 'AI'} · AI 主播 ({len(selected)})")
        for idx,g in enumerate(selected):
            card=ClickableFrame(objectName="hostCard"); card.setProperty("selected", str(g.get("group_key")==self.selected_group_key).lower()); card.setMinimumSize(190,210); card.setMaximumHeight(235)
            cv=QVBoxLayout(card); cv.setContentsMargins(10,10,10,10); cv.setSpacing(6)
            thumb=QLabel("暂无图片",objectName="thumb"); thumb.setAlignment(Qt.AlignCenter); thumb.setFixedHeight(92)
            img=self._first_image(g, task_rows)
            set_image(thumb, img)
            cv.addWidget(thumb)
            cv.addWidget(QLabel(str(g.get("anchor_name") or "主播"),objectName="cardTitle"))
            total=int(g.get("talking",0) or 0)+int(g.get("praying",0) or 0)
            cv.addWidget(QLabel(f"{total} 文案 · {int(g.get('images',0) or 0)} 图片",objectName="cardMeta"))
            st=str(g.get("status") or ""); label="✓ 已准备" if st=="READY_FOR_GPT" else ("待分类" if st=="NEEDS_MANUAL_CLASSIFY" else (str(g.get("message") or st)[:28] or "准备中"))
            cv.addWidget(QLabel(label,objectName="statusGood" if st=="READY_FOR_GPT" else "statusWarn"))
            if g.get('mixed_requirement'):
                warning=QLabel('检测到混合文案，需要手动选取',objectName='statusWarn');warning.setWordWrap(True);warning.setStyleSheet('color:#C58A16;font-size:11px;');cv.addWidget(warning);card.setMaximumHeight(265)
            manage=QPushButton("管理文案 / 图片")
            manage.setToolTip("打开文案和图片管理；尚未准备时显示下一步操作")
            manage.clicked.connect(lambda checked=False,k=g.get("group_key"):self.open_group_manager(k))
            cv.addWidget(manage)
            card.clicked.connect(lambda k=g.get("group_key"):self.select_group(k)); cols=max(1,min(4,int(max(1,self.host_scroll.viewport().width())/220))); self.host_grid.addWidget(card,idx//cols,idx%cols)

        g=self._selected_group(groups)
        if not g and selected:
            self.selected_group_key=selected[0].get("group_key") or ""; g=self._selected_group(groups)
        if g:
            self.detail_title.setText(f'{g.get("recipient","")} · {g.get("anchor_name","")}')
            self.detail_meta.setText(f'TALKING {int(g.get("talking",0) or 0)} · PRAYING {int(g.get("praying",0) or 0)} · 图片 {int(g.get("images",0) or 0)}')
            img=self._first_image(g, task_rows); self.detail_preview.clear()
            set_image(self.detail_preview, img)
            self.detail_counts.setText(f'本地目录：{g.get("local_dir") or "尚未建立"}')
            st=str(g.get("status") or ""); self.detail_status.setText("✓ 已准备进入 GPT" if st=="READY_FOR_GPT" else (g.get("message") or st or "准备中")); self.detail_status.setObjectName("statusGood" if st=="READY_FOR_GPT" else "statusWarn"); self.detail_status.style().unpolish(self.detail_status); self.detail_status.style().polish(self.detail_status)
            self.manual_btn.setEnabled(bool(g.get("local_dir")) and not g.get("archived"))
            self.manual_btn.setToolTip("文案按红黑字体自动分类；只有原始图片类型识别不符时才需要调整。")
            self.download_btn.setEnabled(not g.get("archived"))
            self.rescan_btn.setEnabled(True); self.delete_host_btn.setEnabled(True)
            can_manage=bool(g.get("host_id")) or st=="READY_FOR_GPT"
            self.manage_btn.setEnabled(True)
            self.manage_hint.setText(
                "点击“管理文案 / 图片”可编辑该主播的中文、外文文案和编号图片。"
                if can_manage else "请先完成该主播的素材同步/分类；准备完成后即可在这里管理文案和图片。"
            )
        else:
            self.detail_title.setText("选择一个主播"); self.detail_meta.setText("暂无主播任务"); self.detail_preview.setText("暂无素材"); self.detail_counts.setText(""); self.detail_status.setText(""); self.manage_hint.setText("选择主播后可在这里管理文案、图片和素材。")
            self.manage_btn.setEnabled(False); self.manual_btn.setEnabled(False); self.download_btn.setEnabled(False)
            self.rescan_btn.setEnabled(False); self.delete_host_btn.setEnabled(False)

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
        try:
            info = intake.google_account_info()
        except Exception:
            info = {"connected": False}
        if not info.get("connected"):
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

    def download_selected(self):
        g = self._selected_group()
        if not g:
            QMessageBox.information(self, "同步素材", "请先选择一个主播。")
            return
        self.run_worker("download", g["group_key"])

    def rescan_selected(self, checked=False, *, random_fill=False):
        g = self._selected_group()
        if not g:
            QMessageBox.information(self, "本地扫描", "请先选择一个主播。")
            return
        self.run_worker("rescan_local", g["group_key"], {"day": work_dates.active(), "random_fill": random_fill})

    def delete_selected_host(self):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "删除主播", "当前操作尚未完成，请稍后再删除。")
            return
        g = self._selected_group()
        if not g:
            QMessageBox.information(self, "删除主播", "请先选择一个主播。")
            return
        from app.services.delete_selected_host import preview
        try:
            plan = preview(g["group_key"], work_dates.active())
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
            f'将移除 {len(plan["files"])} 个已登记的下游本地文件；原始图片素材不会删除。\n'
            f'{len(plan["shared_files"])} 个共享文件会保留；其他主播和其他日期不受影响。\n'
            'Google 表格源数据不删除，后续重新同步时仍可能再次导入该主播。'
        )
        box.setDetailedText(
            '任务中心编号：' + str(plan['intake_ids']) + '\n生产任务编号：' + str(plan['video_ids']) +
            '\n\n将移除的本地文件：\n' + ('\n'.join(plan['files']) or '无') +
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
        self.status.setText("正在处理…")
        self.sync_btn.setEnabled(False)
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
        self.sync_btn.setEnabled(True)
        self.status.setText("完成")
        if action in ("sync_all", "sync_auto"):
            s = data.get("sync", {})
            self._log(
                f'同步完成：新增 {s.get("imported",0)}，更新 {s.get("updated",0)}，已存在 {s.get("unchanged",0)}；'
                f'写回表格 {s.get("writeback",{}).get("written",0)} 行。'
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
        self.sync_btn.setEnabled(True)
        self.status.setText("失败")
        self._log("🔴 " + error)
        QMessageBox.warning(self, "任务中心", error)
        self.refresh_google_state()

    def clear_tasks(self, resync=False):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self,'清空当前任务','任务同步正在运行，请等待同步结束后清空。');return
        from app.ui.confirmation import confirm_clear
        if not confirm_clear(self, "清空当前任务", "仅清空今天任务中心的显示。任务源、提示词、Flow 下载、质检、重做、剪辑和历史记录全部保留。同步后可重新显示任务。"):
            return
        from app.services.local_bridge import get_bridge
        try:d = intake.clear_current_tasks(get_bridge())
        except Exception as exc:
            QMessageBox.warning(self,'清空当前任务',str(exc));return
        self._log('已清空任务中心显示；所有生产数据和素材均保留。')
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
                self.google_state.setText("Google：🟢 " + (info.get("email") or "已授权，同步时验证"))
            else:
                self.google_state.setText("Google：🔴 未连接")
        except Exception:
            self.google_state.setText("Google：状态未知")

    def show_available_date(self):
        day=self.available_dates.currentData()
        if day and self.parent_window:
            self.parent_window.set_work_date(day)

    def refresh(self):
        groups, tasks, dates = workspace_intake.snapshot()
        current=work_dates.active()
        other=sorted((d for d in dates if d!=current),reverse=True)
        self.available_dates.clear()
        for day in other:self.available_dates.addItem('历史未分类' if day==work_dates.LEGACY else day,day)
        empty=not tasks
        self.available_dates.setVisible(empty and bool(other));self.show_date_btn.setVisible(empty and bool(other))
        self.date_hint.setText(f'当前工作日期：{current}。'+('本日期没有任务；已有任务保留在原日期，请选择右侧日期查看。' if empty and other else ('本日期没有任务。请检查表格中可同步的任务行。' if empty else f'显示 {len(tasks)} 条文案。')))
        if empty and other and self.progress.value()==100:
            self.progress_detail.setText(f'同步已结束；当前显示 {current}，已有任务位于 '+ '、'.join(other[:5])+'。重复同步不会更改任务日期。')
        ready=sum(1 for g in groups if g.get("status")=="READY_FOR_GPT")
        manual=sum(1 for g in groups if g.get("status")=="NEEDS_MANUAL_CLASSIFY")
        error=sum(1 for g in groups if g.get("status") in ("MATERIAL_SHORTAGE","DRIVE_LINK_CONFLICT","MATERIAL_LINK_MISSING"))
        recipients=len({str(g.get("recipient") or "") for g in groups if g.get("recipient")})
        scripts=sum(int(g.get("talking",0) or 0)+int(g.get("praying",0) or 0) for g in groups)
        self.summary.setText(f"{recipients} 接收人   ·   {len(groups)} 主播   ·   {scripts} 文案   ·   {ready} 素材正常   ·   ⚠ {manual+error} 待处理")
        if not getattr(self,"_date_view_refresh",False): self.refresh_google_state()
        self.refresh_cards(groups, tasks); self.load_log()

    def load_log(self):
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
        self.log.appendPlainText(str(text))
