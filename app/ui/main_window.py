
from __future__ import annotations
import traceback
import time
from functools import partial
from pathlib import Path
import re

from PySide6.QtCore import Qt, QDate, QSettings, QSize, QTimer, QUrl
from PySide6.QtGui import QPixmap
from app.ui.image_preview import set_image
from app.ui.confirmation import confirm_clear
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QFrame, QStackedWidget, QScrollArea, QDialog, QFormLayout, QLineEdit, QDateEdit, QDialogButtonBox, QMessageBox, QSpinBox, QTableWidgetItem, QHeaderView, QFileDialog, QComboBox, QProgressBar, QGridLayout, QCalendarWidget, QButtonGroup, QPlainTextEdit, QCheckBox, QTableWidget, QSizePolicy, QSplitter
)

from app.core.database import init_db, DB_PATH
from app.core import repository as repo
from app.core import work_dates
from app.ui.task_calendar import TaskCalendar
from app.core.default_prompt import DEFAULT_CORE_PROMPT
from app.core.naming import final_filename
from app.ui.styles import LIGHT, DARK
from app.ui.spreadsheet import SpreadsheetTable
from app.ui.prompt_center import PromptCenterPage
from app.ui.flow_task_center import FlowBatchCenterPage
from app.ui.downstream_pages import VideoQCPage, DaVinciPage, StatisticsPage
from app.ui.packaging_page import PackagingPage
from app.ui.task_intake_page import TaskIntakePage
from app.ui.modern_widgets import ClickableFrame
from app.services.reflow_rules import prepare_configured_speech as prepare_swahili_speech
from app.services.local_bridge import get_bridge
from app.services import pipeline_orchestrator, runtime_log


def normalize_foreign_punctuation(text: str) -> str:
    """Compatibility helper: punctuation normalization now happens after smart reflow."""
    return (text or "").replace("\r\n", "\n").replace("\r", "\n")

def wrap_foreign(text: str, width: int) -> str:
    """Compatibility wrapper for the current reference-length reflow engine."""
    prepared = prepare_swahili_speech(text or "", max_chars=width)
    return "\n".join(prepared.segments)


class CalendarDialog(QDialog):
    def __init__(self, initial_date=None, parent=None, workspace=False):
        super().__init__(parent)
        self.setWindowTitle("选择制作日期")
        self.resize(560, 470)
        layout = QVBoxLayout(self)

        title = QLabel("选择制作日期")
        title.setStyleSheet("font-size:20px;font-weight:700;")
        layout.addWidget(title)

        self.calendar = TaskCalendar()
        self.calendar.setGridVisible(False)
        self.calendar.setNavigationBarVisible(True)
        self.calendar.setMinimumSize(520, 360)
        if initial_date and initial_date.isValid():
            self.calendar.setSelectedDate(initial_date)
        else:
            self.calendar.setSelectedDate(QDate.currentDate())
        self.calendar.activated.connect(self.accept)
        layout.addWidget(self.calendar, 1)
        layout.addWidget(QLabel('绿色：有任务　下划线：今天　蓝色：当前选中',objectName='muted'))
        self.legacy_selected=False
        if workspace:
            self.setWindowTitle('任务日历'); title.setText('任务日历')
            self.calendar.clicked.connect(self.accept)
            if work_dates.LEGACY in self.calendar.task_days:
                legacy=QPushButton('历史未分类任务');legacy.clicked.connect(self.select_legacy);layout.addWidget(legacy)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def select_legacy(self):
        self.legacy_selected=True; self.accept()

    def selected_date(self):
        return self.calendar.selectedDate()


class AddRecipientDialog(QDialog):
    def __init__(self, default_code="ZB", parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加接收人")
        self.resize(500, 300)

        form = QFormLayout(self)
        self.name = QLineEdit()
        self.code = QLineEdit(default_code or "ZB")

        date_wrap = QWidget()
        date_layout = QHBoxLayout(date_wrap)
        date_layout.setContentsMargins(0,0,0,0)
        self.work_date = QLineEdit(QDate.currentDate().toString("yyyyMMdd"))
        self.work_date.setPlaceholderText("例如 20260910")
        self.work_date.setMaxLength(8)
        pick = QPushButton("选择日期", objectName="dateBtn")
        pick.clicked.connect(self.pick_date)
        date_layout.addWidget(self.work_date, 1)
        date_layout.addWidget(pick)

        form.addRow("接收人", self.name)
        form.addRow("固定编号", self.code)
        form.addRow("制作日期", date_wrap)

        hint = QLabel("日期可以直接手动输入 8 位数字，也可以点击“选择日期”。", objectName="muted")
        hint.setWordWrap(True)
        form.addRow(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def pick_date(self):
        d = QDate.fromString(self.work_date.text().strip(), "yyyyMMdd")
        dialog = CalendarDialog(d if d.isValid() else QDate.currentDate(), self)
        if dialog.exec():
            self.work_date.setText(dialog.selected_date().toString("yyyyMMdd"))

    def validate_and_accept(self):
        raw = self.work_date.text().strip()
        d = QDate.fromString(raw, "yyyyMMdd")
        if len(raw) != 8 or not raw.isdigit() or not d.isValid():
            QMessageBox.warning(self, "日期格式", "制作日期请输入有效的 8 位日期，例如 20260910。")
            return
        self.accept()

    def values(self):
        return self.name.text(), self.code.text(), self.work_date.text().strip()


class AddHostDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加 AI 主播")
        form = QFormLayout(self)
        self.name = QLineEdit()
        self.count = QSpinBox()
        self.count.setRange(1, 99); self.count.setValue(12)
        form.addRow("主播名称", self.name)
        form.addRow("完整视频数量", self.count)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self):
        return self.name.text(), self.count.value()


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("系统设置")
        self.resize(920, 860)
        form = QFormLayout(self)

        self.creator = QLineEdit(repo.default_creator() or str(settings.value("creator", "")))
        self.default_code = QLineEdit(str(settings.value("default_code", "ZB")))
        self.default_wrap = QLineEdit(str(settings.value("default_wrap", "18")))

        form.addRow("默认制作人", self.creator)
        form.addRow("默认固定编号", self.default_code)
        form.addRow("默认外语断行字符数", self.default_wrap)

        self.task_sheet = QLineEdit(repo.get_setting("task_source_sheet_url", ""))
        self.task_sheet.setPlaceholderText("每天固定使用的 Google Sheets 链接")
        form.addRow("任务获取表格链接", self.task_sheet)

        asset_wrap = QWidget(); asset_row = QHBoxLayout(asset_wrap); asset_row.setContentsMargins(0,0,0,0)
        self.task_asset_root = QLineEdit(repo.get_setting("task_asset_root", ""))
        self.task_asset_root.setPlaceholderText("主播 Drive 图片下载和任务准备的本地根目录")
        asset_row.addWidget(self.task_asset_root, 1)
        asset_pick = QPushButton("浏览…"); asset_pick.clicked.connect(lambda: self.pick_folder_into(self.task_asset_root, "选择任务素材本地根目录")); asset_row.addWidget(asset_pick)
        form.addRow("任务素材本地根目录", asset_wrap)

        segment_wrap = QWidget(); segment_row = QHBoxLayout(segment_wrap); segment_row.setContentsMargins(0,0,0,0)
        self.segment_output_root = QLineEdit(repo.get_setting("segment_output_root", ""))
        self.segment_output_root.setPlaceholderText("各 Flow 通道下载完成后统一回收成品片段的根目录")
        segment_row.addWidget(self.segment_output_root, 1)
        segment_pick = QPushButton("浏览…"); segment_pick.clicked.connect(lambda: self.pick_folder_into(self.segment_output_root, "选择成品片段根目录")); segment_row.addWidget(segment_pick)
        form.addRow("成品片段根目录", segment_wrap)

        self.drive_upload_root_url = QLineEdit(repo.get_setting("drive_upload_root_url", ""), self)
        self.drive_upload_root_url.setPlaceholderText("最终成品上传到 Google Drive 的根文件夹链接")
        # form.addRow("Drive 成品上传根目录链接", self.drive_upload_root_url)
        self.drive_upload_root_url.hide()

        oauth_wrap = QWidget(); oauth_row = QHBoxLayout(oauth_wrap); oauth_row.setContentsMargins(0,0,0,0)
        self.google_oauth_client_path = QLineEdit(repo.get_setting("google_oauth_client_path", ""))
        self.google_oauth_client_path.setPlaceholderText("首次连接 Google 所需的 OAuth Desktop Client JSON")
        oauth_row.addWidget(self.google_oauth_client_path, 1)
        oauth_pick = QPushButton("选择…"); oauth_pick.clicked.connect(self.pick_oauth_json); oauth_row.addWidget(oauth_pick)
        form.addRow("Google OAuth 客户端 JSON", oauth_wrap)

        self.talking_base_prompt = QPlainTextEdit(); self.talking_base_prompt.setMaximumHeight(125)
        self.talking_base_prompt.setPlaceholderText("留空也可以；第一次批量生成 TALKING 提示词前会提醒你设置。")
        self.talking_base_prompt.setPlainText(repo.get_setting("talking_base_prompt", ""))
        form.addRow("TALKING｜睁眼基础模板", self.talking_base_prompt)

        self.praying_base_prompt = QPlainTextEdit(); self.praying_base_prompt.setMaximumHeight(125)
        self.praying_base_prompt.setPlaceholderText("留空也可以；第一次批量生成 PRAYING 提示词前会提醒你设置。")
        self.praying_base_prompt.setPlainText(repo.get_setting("praying_base_prompt", ""))
        form.addRow("PRAYING｜闭眼基础模板", self.praying_base_prompt)

        self.whisper_cli = QLineEdit(repo.get_setting("whisper_cli_path", ""))
        self.whisper_cli.setPlaceholderText("留空自动寻找 whisper-cli")
        form.addRow("whisper.cpp 命令", self.whisper_cli)
        self.whisper_model = QLineEdit(repo.get_setting("whisper_model_path", ""))
        self.whisper_model.setPlaceholderText("请选择本机 whisper.cpp 模型文件")
        form.addRow("Whisper 模型", self.whisper_model)

        self.drive_desktop_path=QLineEdit(repo.get_setting('drive_desktop_path',''))
        self.drive_desktop_path.setPlaceholderText('留空自动识别Google Drive桌面版；也可选择我的云端硬盘')
        sync_wrap=QWidget(self);sync_row=QHBoxLayout(sync_wrap);sync_row.setContentsMargins(0,0,0,0);sync_row.addWidget(self.drive_desktop_path)
        pick_sync=QPushButton('浏览…');pick_sync.clicked.connect(lambda:self.pick_folder_into(self.drive_desktop_path,'选择Google Drive同步目录'));sync_row.addWidget(pick_sync)
        # form.addRow('Drive桌面版同步目录',sync_wrap)
        sync_wrap.hide()
        self.drive_desktop_folder=QLineEdit(repo.get_setting('drive_desktop_folder','FlowStudio') or 'FlowStudio', self)
        # form.addRow('Drive归档文件夹',self.drive_desktop_folder)
        self.drive_desktop_folder.hide()

        edit_wrap = QWidget()
        edit_row = QHBoxLayout(edit_wrap)
        edit_row.setContentsMargins(0, 0, 0, 0)
        self.edit_root = QLineEdit(repo.get_setting("edit_root_path", str(settings.value("edit_root_path", ""))))
        self.edit_root.setPlaceholderText("例如 /Volumes/LEONARDO/000/Davinci")
        edit_row.addWidget(self.edit_root, 1)
        browse = QPushButton("浏览…")
        browse.clicked.connect(self.pick_edit_root)
        edit_row.addWidget(browse)
        form.addRow("剪辑路径根目录", edit_wrap)
        from app.services.resolve_daily import FPS_VALUES
        self.timeline_fps = QComboBox()
        self.timeline_fps.addItems(FPS_VALUES)
        saved_fps = repo.get_setting('timeline_fps', '25') or '25'
        self.timeline_fps.setCurrentText(saved_fps)
        form.addRow('达芬奇时间线帧率', self.timeline_fps)
        self.whisper_language = QComboBox()
        self.whisper_language.addItems([
            "自动识别 (Auto) · auto", "英语 (English) · en", "中文 (Chinese) · zh", "德语 (German) · de",
            "西班牙语 (Spanish) · es", "俄语 (Russian) · ru", "韩语 (Korean) · ko", "法语 (French) · fr",
            "日语 (Japanese) · ja", "葡萄牙语 (Portuguese) · pt", "土耳其语 (Turkish) · tr",
            "波兰语 (Polish) · pl", "加泰罗尼亚语 (Catalan) · ca", "荷兰语 (Dutch) · nl",
            "阿拉伯语 (Arabic) · ar", "瑞典语 (Swedish) · sv", "意大利语 (Italian) · it",
            "印尼语 (Indonesian) · id", "印地语 (Hindi) · hi", "芬兰语 (Finnish) · fi",
            "越南语 (Vietnamese) · vi", "希伯来语 (Hebrew) · he", "乌克兰语 (Ukrainian) · uk",
            "希腊语 (Greek) · el", "马来语 (Malay) · ms", "捷克语 (Czech) · cs",
            "罗马尼亚语 (Romanian) · ro", "丹麦语 (Danish) · da", "匈牙利语 (Hungarian) · hu",
            "泰米尔语 (Tamil) · ta", "挪威语 (Norwegian) · no", "泰语 (Thai) · th",
            "乌尔都语 (Urdu) · ur", "克罗地亚语 (Croatian) · hr", "保加利亚语 (Bulgarian) · bg",
            "立陶宛语 (Lithuanian) · lt", "拉丁语 (Latin) · la", "毛利语 (Maori) · mi",
            "马拉雅拉姆语 (Malayalam) · ml", "威尔士语 (Welsh) · cy", "斯洛伐克语 (Slovak) · sk",
            "泰卢固语 (Telugu) · te", "波斯语 (Persian) · fa", "拉脱维亚语 (Latvian) · lv",
            "孟加拉语 (Bengali) · bn", "塞尔维亚语 (Serbian) · sr", "阿塞拜疆语 (Azerbaijani) · az",
            "斯洛文尼亚语 (Slovenian) · sl", "卡纳达语 (Kannada) · kn", "爱沙尼亚语 (Estonian) · et",
            "马其顿语 (Macedonian) · mk", "布列塔尼语 (Breton) · br", "巴斯克语 (Basque) · eu",
            "冰岛语 (Icelandic) · is", "亚美尼亚语 (Armenian) · hy", "尼泊尔语 (Nepali) · ne",
            "蒙古语 (Mongolian) · mn", "波斯尼亚语 (Bosnian) · bs", "哈萨克语 (Kazakh) · kk",
            "阿尔巴尼亚语 (Albanian) · sq", "斯瓦西里语 (Swahili) · sw", "加利西亚语 (Galician) · gl",
            "马拉地语 (Marathi) · mr", "旁遮普语 (Punjabi) · pa", "僧伽罗语 (Sinhala) · si",
            "高棉语 (Khmer) · km", "修纳语 (Shona) · sn", "约鲁巴语 (Yoruba) · yo",
            "索马里语 (Somali) · so", "南非荷兰语 (Afrikaans) · af", "奥克语 (Occitan) · oc",
            "格鲁吉亚语 (Georgian) · ka", "白俄罗斯语 (Belarusian) · be", "塔吉克语 (Tajik) · tg",
            "信德语 (Sindhi) · sd", "古吉拉特语 (Gujarati) · gu", "阿姆哈拉语 (Amharic) · am",
            "意第绪语 (Yiddish) · yi", "老挝语 (Lao) · lo", "乌兹别克语 (Uzbek) · uz",
            "法罗语 (Faroese) · fo", "海地克里奥尔语 (Haitian Creole) · ht", "普什图语 (Pashto) · ps",
            "土库曼语 (Turkmen) · tk", "尼诺斯克挪威语 (Nynorsk) · nn", "马耳他语 (Maltese) · mt",
            "梵语 (Sanskrit) · sa", "卢森堡语 (Luxembourgish) · lb", "缅甸语 (Myanmar) · my",
            "藏语 (Tibetan) · bo", "他加禄语 (Tagalog) · tl", "马达加斯加语 (Malagasy) · mg",
            "阿萨姆语 (Assamese) · as", "鞑靼语 (Tatar) · tt", "夏威夷语 (Hawaiian) · haw",
            "林加拉语 (Lingala) · ln", "豪萨语 (Hausa) · ha", "巴什基尔语 (Bashkir) · ba",
            "爪哇语 (Javanese) · jv", "巽他语 (Sundanese) · su"
        ])
        saved_lang = repo.get_setting("whisper_language", "斯瓦西里语 (Swahili) · sw")
        idx = self.whisper_language.findText(saved_lang)
        if idx >= 0:
            self.whisper_language.setCurrentIndex(idx)
        else:
            self.whisper_language.setCurrentText("斯瓦西里语 (Swahili) · sw")
        form.addRow('自动剪辑口播语言', self.whisper_language)


        tip = QLabel(
            "制作者是整台电脑的全局设置。剪辑根目录用于 DaVinci 的项目媒体、ProxyMedia、CacheClip、.gallery、导入素材与最终导出；"
            "视频质检全部通过后，会自动把源片段从下载目录移动到这个根目录。",
            objectName="muted"
        )
        tip.setWordWrap(True)
        form.addRow(tip)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def pick_folder_into(self, line_edit, title):
        start = line_edit.text().strip() or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, title, start)
        if path:
            line_edit.setText(path)

    def pick_oauth_json(self):
        start = str(Path(self.google_oauth_client_path.text().strip()).expanduser().parent) if self.google_oauth_client_path.text().strip() else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, "选择 Google OAuth Desktop Client JSON", start, "JSON 文件 (*.json)")
        if path:
            self.google_oauth_client_path.setText(path)

    def pick_edit_root(self):
        start = self.edit_root.text().strip() or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "选择 DaVinci 剪辑路径根目录", start)
        if path:
            self.edit_root.setText(path)

    def validate_and_accept(self):
        wrap = self.default_wrap.text().strip()
        if wrap and (not wrap.isdigit() or int(wrap) <= 0):
            QMessageBox.warning(self, "设置错误", "默认断行字符数必须是大于 0 的整数。")
            return
        for label, value in (("任务素材根目录", self.task_asset_root.text().strip()), ("成品片段根目录", self.segment_output_root.text().strip()), ("剪辑路径", self.edit_root.text().strip())):
            if value:
                try:
                    Path(value).expanduser().mkdir(parents=True, exist_ok=True)
                except Exception as exc:
                    QMessageBox.warning(self, label, f"无法创建/写入目录：{exc}")
                    return
        oauth = self.google_oauth_client_path.text().strip()
        if oauth and not Path(oauth).expanduser().exists():
            QMessageBox.warning(self, "Google OAuth", "选择的 OAuth JSON 文件不存在。")
            return
        if oauth:
            from app.services.google_oauth_config import load_desktop_config
            try:
                load_desktop_config(oauth)
            except ValueError as exc:
                QMessageBox.warning(self, "Google 授权文件类型错误", str(exc))
                return
        self.accept()

    def save(self):
        creator=self.creator.text().strip()
        self.settings.setValue("creator", creator)
        repo.set_default_creator(creator)
        repo.set_setting("task_source_sheet_url", self.task_sheet.text().strip())
        repo.set_setting("task_asset_root", self.task_asset_root.text().strip())
        repo.set_setting("segment_output_root", self.segment_output_root.text().strip())
        repo.set_setting("flow_download_root", self.segment_output_root.text().strip())
        repo.set_setting("drive_upload_root_url", self.drive_upload_root_url.text().strip())
        repo.set_setting("google_oauth_client_path", self.google_oauth_client_path.text().strip())
        repo.set_setting("talking_base_prompt", self.talking_base_prompt.toPlainText().strip())
        repo.set_setting("praying_base_prompt", self.praying_base_prompt.toPlainText().strip())
        repo.set_setting("whisper_cli_path", self.whisper_cli.text().strip())
        repo.set_setting("whisper_model_path", self.whisper_model.text().strip())
        repo.set_setting('timeline_fps', self.timeline_fps.currentText())
        repo.set_setting("whisper_language", self.whisper_language.currentText())

        repo.set_setting('drive_desktop_path',self.drive_desktop_path.text().strip())
        repo.set_setting('drive_desktop_folder',self.drive_desktop_folder.text().strip() or 'FlowStudio')
        self.settings.setValue("default_code", self.default_code.text().strip() or "ZB")
        repo.set_setting("default_code", self.default_code.text().strip() or "ZB")
        wrap_value = self.default_wrap.text().strip() or "18"
        self.settings.setValue("default_wrap", wrap_value)
        repo.set_setting("default_wrap", wrap_value)
        root = self.edit_root.text().strip()
        self.settings.setValue("edit_root_path", root)
        repo.set_setting("edit_root_path", root)
        if root:
            try:
                from app.services.davinci_workflow import ensure_root_layout
                ensure_root_layout(Path(root))
            except Exception:
                pass


class MultilineEditorDialog(QDialog):
    def __init__(self, title, value, parent=None, segmented=False, segment_modes=None):
        super().__init__(parent)
        self.segmented = segmented
        self.setWindowTitle(title)
        self.setFixedSize(900, 620)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18,16,18,16)

        if segmented:
            head = QLabel("每一行就是一个 Flow 片段；保存时会按真实换行合并。")
            head.setStyleSheet("font-size:14px;font-weight:600;")
            layout.addWidget(head)

            sub = QLabel("保留原文正常朗读标点；不会再把每段结尾统一改成英文句号。", objectName="muted")
            layout.addWidget(sub)

            self.segment_table = QTableWidget()
            self.segment_table.setColumnCount(3)
            self.segment_table.setHorizontalHeaderLabels(["片段", "外语文案", "类型"])
            self.segment_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
            self.segment_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
            self.segment_table.setColumnWidth(0, 72)
            self.segment_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
            self.segment_table.setColumnWidth(2, 110)
            self.segment_table.verticalHeader().setVisible(False)
            self.segment_table.setWordWrap(True)
            self.segment_table.setAlternatingRowColors(True)
            self.segment_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

            lines = [x for x in (value or "").replace("\r\n","\n").replace("\r","\n").split("\n") if x.strip()]
            if not lines:
                lines = [""]

            self.segment_table.setRowCount(len(lines))
            for i, line in enumerate(lines):
                idx = QTableWidgetItem(str(i+1))
                idx.setFlags(idx.flags() & ~Qt.ItemIsEditable)
                idx.setTextAlignment(Qt.AlignCenter)
                self.segment_table.setItem(i, 0, idx)
                self.segment_table.setItem(i, 1, QTableWidgetItem(line))
                combo=QComboBox()
                combo.addItem("睁眼","TALKING");combo.addItem("闭眼","PRAYING")
                mode=segment_modes[i] if segment_modes and i<len(segment_modes) else "TALKING"
                combo.setCurrentIndex(max(0,combo.findData(mode)))
                combo.setToolTip("保存后用于此片段下一次 GPT 提示词生成；已有提示词和在途任务保留。")
                self.segment_table.setCellWidget(i,2,combo)

            self.segment_table.resizeRowsToContents()
            for i in range(self.segment_table.rowCount()):
                self.segment_table.setRowHeight(i, max(48, min(self.segment_table.rowHeight(i) + 8, 150)))

            self.segment_table.itemChanged.connect(self._resize_segment_rows)
            layout.addWidget(self.segment_table, 1)
        else:
            head = QLabel("保留原有真实换行；长文本仅在编辑窗口内自动折行显示。")
            head.setStyleSheet("font-size:14px;font-weight:600;")
            layout.addWidget(head)

            self.editor = QPlainTextEdit()
            self.editor.setPlainText((value or "").replace("\r\n","\n").replace("\r","\n"))
            self.editor.setLineWrapMode(QPlainTextEdit.WidgetWidth)
            layout.addWidget(self.editor, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_types(self):
        return [self.segment_table.cellWidget(i,2).currentData()
                for i in range(self.segment_table.rowCount())
                if self.segment_table.item(i,1).text().strip()]

    def _resize_segment_rows(self, _item=None):
        if not self.segmented:
            return
        self.segment_table.resizeRowsToContents()
        for i in range(self.segment_table.rowCount()):
            self.segment_table.setRowHeight(
                i,
                max(48, min(self.segment_table.rowHeight(i) + 8, 150))
            )

    def value(self):
        if self.segmented:
            lines = []
            for row in range(self.segment_table.rowCount()):
                item = self.segment_table.item(row, 1)
                text = item.text().strip() if item else ""
                if text:
                    lines.append(text)
            return "\n".join(lines)
        return self.editor.toPlainText().replace("\r\n","\n").replace("\r","\n")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        init_db()
        work_dates.reset()
        # Date isolation is authoritative: startup opens today only. Historical unfinished
        # Flow work must never pull the whole Studio back to another date automatically.
        # When the user selects a date, every production scan operates only on that date.
        self._last_today=work_dates.today()
        self.settings = QSettings("OpenAIProject", "AIVideoStudio")
        # Keep the GUI line-length preference available to non-Qt production services too.
        # Existing installations keep their current QSettings value (for example 80).
        repo.set_setting("default_wrap", str(self.settings.value("default_wrap", "18")).strip() or "18")
        self.current_recipient_id = None
        self.current_host_id = None
        self.host_table = None
        self.host_meta = None
        self.setWindowTitle("Flow Studio V0.13.5.106")
        self.local_bridge = get_bridge()
        try:
            self.local_bridge.start()
        except OSError as exc:
            msg = str(exc)
            if getattr(exc, "errno", None) in (48, 98, 10048):
                QMessageBox.warning(
                    self,
                    "Flow Studio Bridge 已被占用",
                    "检测到当前 Bridge 端口已有正在运行的服务。\n\n"
                    "如果你刚刚关闭旧版 Flow Studio，请等待约 1 秒再重新打开；"
                    "如果另一个 Flow Studio 窗口仍然开着，请先关闭它。\n\n"
                    f"详细信息：{msg}"
                )
            else:
                QMessageBox.warning(
                    self,
                    "Flow Studio Bridge",
                    f"本地 Bridge 端口启动失败：{exc}\n\n"
                    "Flow Studio 其他功能仍可使用。"
                )
        # V0.5.2: safely migrate the old built-in single-segment core prompt.
        saved_core = repo.get_setting("core_prompt", "")
        if (not saved_core) or (
            "当前每次 API 请求只处理一个明确的 Flow 小片段" in saved_core
            and "Flow Studio API 核心生成指令" in saved_core
        ):
            repo.set_setting("core_prompt", DEFAULT_CORE_PROMPT)
        if not repo.get_setting("image_detail", ""):
            repo.set_setting("image_detail", "low")
        # Navigation performance state only. Pages themselves remain single-instance.
        self._active_nav_key = None
        self._nav_refresh_tokens = {}
        self._nav_request_serial = 0

        self.resize(1380, 860)
        # Responsive desktop window: the redesigned pages must remain usable on
        # narrower screens instead of forcing the old 1400px minimum width.
        self.setMinimumSize(900, 620)
        saved_geometry = self.settings.value("window_geometry")
        if saved_geometry:
            try:
                self.restoreGeometry(saved_geometry)
            except Exception:
                pass
        self.build()
        self.apply_saved_theme()
        # All production pages already perform their initial load in their constructors.
        # Mark that snapshot as current so the first sidebar visit does not rebuild it again.
        initial_token = self._navigation_data_token()
        for key in ("intake", "prompt", "flow", "qc", "davinci", "stats"):
            self._nav_refresh_tokens[key] = initial_token
        # Task Center is now the production home. The old overview dashboard is kept
        # only as an internal compatibility page for legacy calls.
        self.show_task_intake()
        self.date_timer=QTimer(self); self.date_timer.timeout.connect(self.check_work_day); self.date_timer.start(30000)
        
        # --- Background QC Reconcile ---
        self.qc_reconcile_timer = QTimer(self)
        self.qc_reconcile_timer.timeout.connect(self._background_qc_tick)
        self.qc_reconcile_timer.start(15000)
        QTimer.singleShot(2000, self._background_qc_tick)
        # --- End Background QC ---
        # Startup also scans today's selected workspace immediately instead of waiting
        # for the first Flow-page timer tick or a plugin completion event.
        QTimer.singleShot(500, self.flow_task_center.auto_dispatch_tick)

    def build(self):
        base = QWidget(objectName="appRoot")
        self.setCentralWidget(base)
        root = QHBoxLayout(base)
        root.setContentsMargins(0,0,0,0)
        root.setSpacing(0)

        sidebar = QFrame(objectName="sidebar")
        sidebar.setFixedWidth(204)
        self.sidebar = sidebar
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(14,14,14,14)
        side.setSpacing(5)

        brand = QLabel("▶  Flow Studio", objectName="brand")
        side.addWidget(brand)
        sub = QLabel("AI 口播视频批量制作工作台", objectName="brandSub")
        side.addWidget(sub)
        side.addSpacing(14)

        self.nav_buttons = {}

        nav_items = [
            ("⇩  任务中心", "intake"),
            ("✦  GPT 提示词", "prompt"),
            ("⤨  Flow 生成", "flow"),
            ("✓  视频质检", "qc"),
            ("✂  自动剪辑", "davinci"),
            ("▣  视频包装", "packaging"),
            ("▥  数据统计", "stats"),
            ("⚙  系统设置", "settings"),
        ]
        for label, action in nav_items:
            b = QPushButton(label, objectName="nav")
            if action == "intake":
                b.clicked.connect(self.show_task_intake)
                self.nav_buttons["intake"] = b
            elif action == "prompt":
                b.clicked.connect(self.show_prompt_center)
                self.nav_buttons["prompt"] = b
            elif action == "flow":
                b.clicked.connect(self.show_flow_task_center)
                self.nav_buttons["flow"] = b
            elif action == "qc":
                b.clicked.connect(self.show_qc_page)
                self.nav_buttons["qc"] = b
            elif action == "davinci":
                b.clicked.connect(self.show_davinci_page)
                self.nav_buttons["davinci"] = b
            elif action == "packaging":
                b.clicked.connect(self.show_packaging_page)
                self.nav_buttons["packaging"] = b
            elif action == "stats":
                b.clicked.connect(self.show_stats_page)
                self.nav_buttons["stats"] = b
            elif action == "settings":
                b.clicked.connect(self.open_settings)
                self.nav_buttons["settings"] = b
            side.addWidget(b)

        side.addStretch(1)

        footer = QFrame(objectName="sideDateCard")
        fv = QVBoxLayout(footer)
        fv.setContentsMargins(12,10,12,10)
        today = QDate.currentDate().toString("yyyy-MM-dd")
        fl1 = QLabel("任务日历", objectName="sideDateTitle")
        self.work_date_button=QPushButton(work_dates.active(),objectName="dateBtn")
        self.work_date_button.clicked.connect(self.open_work_calendar)
        fl2 = self.work_date_button
        fv.addWidget(fl1)
        fv.addWidget(fl2)
        side.addWidget(footer)

        theme_label = QLabel("主题")
        side.addWidget(theme_label)
        theme_row = QHBoxLayout()
        theme_row.setSpacing(5)
        self.theme_group = QButtonGroup(self)
        self.theme_group.setExclusive(True)
        self.theme_buttons = {}
        for key, label in [("浅色","浅色"),("深色","深色"),("跟随系统","系统")]:
            b = QPushButton(label, objectName="themeBtn")
            b.setCheckable(True)
            b.clicked.connect(lambda checked=False, k=key: self.change_theme(k))
            self.theme_group.addButton(b)
            self.theme_buttons[key] = b
            theme_row.addWidget(b)
        side.addLayout(theme_row)

        root.addWidget(sidebar)

        self.stack = QStackedWidget()
        workspace=QWidget(); content=QVBoxLayout(workspace); content.setContentsMargins(0,0,0,0); content.setSpacing(0)
        content.addWidget(self.stack,1)
        root.addWidget(workspace, 1)
        self.dashboard = QWidget(objectName="pageRoot")
        self.recipient_page = QWidget(objectName="pageRoot")
        self.host_page = QWidget(objectName="pageRoot")
        self.task_intake_page = TaskIntakePage(self)
        self.prompt_center = PromptCenterPage(self)
        self.flow_task_center = FlowBatchCenterPage(self)
        self.qc_page = VideoQCPage(self)
        self.davinci_page = DaVinciPage(self)
        self.packaging_page = PackagingPage(self)
        self.stats_page = StatisticsPage(self)
        self.stack.addWidget(self.dashboard)
        self.stack.addWidget(self.recipient_page)
        self.stack.addWidget(self.host_page)
        self.stack.addWidget(self.task_intake_page)
        self.stack.addWidget(self.prompt_center)
        self.stack.addWidget(self.flow_task_center)
        self.stack.addWidget(self.qc_page)
        self.stack.addWidget(self.davinci_page)
        self.stack.addWidget(self.packaging_page)
        self.stack.addWidget(self.stats_page)
        self.stack.setMinimumWidth(0)
        for page in (self.dashboard, self.recipient_page, self.host_page, self.task_intake_page,
                     self.prompt_center, self.flow_task_center, self.qc_page, self.davinci_page,
                     self.packaging_page, self.stats_page):
            page.setMinimumWidth(0)
            page.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)

    def open_work_calendar(self):
        dialog=CalendarDialog(QDate.fromString(work_dates.active(),'yyyy-MM-dd'),self,workspace=True)
        if dialog.exec():
            self.set_work_date(work_dates.LEGACY if dialog.legacy_selected else dialog.selected_date().toString('yyyy-MM-dd'))

    def _background_qc_tick(self):
        from app.services.workflow import run_background_qc_reconcile
        run_background_qc_reconcile()

    def check_work_day(self):
        current=work_dates.today()
        if current!=self._last_today:
            previous_today=self._last_today
            self._last_today=current
            # Preserve the original date-isolation rule: only a window that was simply
            # following "today" rolls forward at midnight. An explicitly selected
            # historical date is never replaced because another date has unfinished work.
            if work_dates.active()==previous_today:
                self.set_work_date(current,automatic=True)

    def set_work_date(self, day, automatic=False):
        work_dates.select(day)
        self.work_date_button.setText('历史未分类' if day==work_dates.LEGACY else work_dates.active())
        current=self.stack.currentWidget()
        self.current_recipient_id=None;self.current_host_id=None
        self.task_intake_page.selected_recipient='';self.task_intake_page.selected_group_key=''
        self.flow_task_center.scope_key=None;self.flow_task_center.page_index=0
        self.qc_page.qc_page_index=0;self.qc_page._rows_signature=None
        self.qc_page._pending_video_source=None;self.qc_page.current_output=''
        if self.qc_page.player:
            self.qc_page.player.stop();self.qc_page.player.setSource(QUrl())
        for page in (self.prompt_center,self.flow_task_center):page.checked_ids.clear()
        # Explicit read refresh: no imports, job preparation, scans, or production calls.
        for page,method in ((self.task_intake_page,'refresh'),(self.prompt_center,'reload_filters'),(self.flow_task_center,'reload_filters'),(self.qc_page,'reload'),(self.davinci_page,'reload'),(self.stats_page,'reload')):
            page._date_view_refresh=True
            try:getattr(page,method)()
            finally:page._date_view_refresh=False
        refreshed_token = self._navigation_data_token()
        for key in ("intake", "prompt", "flow", "qc", "davinci", "stats"):
            self._nav_refresh_tokens[key] = refreshed_token
        # Switching the workspace date must immediately kick the Flow watchdog for
        # that exact date.  The regular 2-second timer remains as the continuous fallback.
        QTimer.singleShot(0, self.flow_task_center.auto_dispatch_tick)
        if current in (self.dashboard,self.recipient_page,self.host_page):self.show_dashboard()

    def _new_scroll_page_layout(self, page, min_width=760, margins=(24,20,24,20), spacing=12):
        """Create a top-aligned responsive page shell without changing page data logic."""
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0,0,0,0)
        outer.setSpacing(0)
        scroll = QScrollArea(objectName="pageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        content = QWidget(objectName="pageScrollContent")
        content.setMinimumWidth(min_width)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(*margins)
        layout.setSpacing(spacing)
        layout.setAlignment(Qt.AlignTop)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        return layout, scroll, content

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Keep navigation usable while giving small windows enough workspace.
        if hasattr(self, 'sidebar'):
            w=self.width()
            target=204 if w>=1280 else (184 if w>=1050 else 168)
            if self.sidebar.width()!=target:
                self.sidebar.setFixedWidth(target)

    def apply_saved_theme(self):
        name = str(self.settings.value("theme", "浅色"))
        if name not in ("浅色", "深色", "跟随系统"):
            name = "浅色"
        self.set_theme_button_state(name)
        self.apply_theme(name)

    def set_theme_button_state(self, name):
        if hasattr(self, "theme_buttons"):
            for key, btn in self.theme_buttons.items():
                btn.blockSignals(True)
                btn.setChecked(key == name)
                btn.blockSignals(False)

    def global_creator(self):
        return repo.default_creator().strip() or str(self.settings.value("creator", "")).strip()

    def default_code(self):
        return str(self.settings.value("default_code", "ZB")).strip() or "ZB"

    def default_wrap(self):
        return str(self.settings.value("default_wrap", "18")).strip() or "18"

    def open_settings(self):
        d = SettingsDialog(self.settings, self)
        if d.exec():
            d.save()
            if self.stack.currentWidget() is self.dashboard:
                self.show_dashboard()
            elif self.stack.currentWidget() is self.task_intake_page:
                self.task_intake_page.refresh()
            elif self.stack.currentWidget() is self.prompt_center:
                self.prompt_center.reload_filters()
            elif self.current_recipient_id and self.stack.currentWidget() is self.recipient_page:
                self.show_recipient(self.current_recipient_id)
            elif self.current_host_id and self.stack.currentWidget() is self.host_page:
                host_id = self.current_host_id
                self.show_host(host_id)
                # A changed system default is immediately applied to the visible host copy.
                QTimer.singleShot(0, lambda: self.auto_wrap_foreign(silent=True))

    def change_theme(self, name):
        self.settings.setValue("theme", name)
        self.set_theme_button_state(name)
        self.apply_theme(name)

    def apply_theme(self, name):
        if name == "深色":
            sheet = DARK
        elif name == "跟随系统":
            hints = QApplication.styleHints()
            try:
                dark = hints.colorScheme() == Qt.ColorScheme.Dark
            except Exception:
                dark = False
            sheet = DARK if dark else LIGHT
        else:
            sheet = LIGHT

        app = QApplication.instance()
        if app:
            app.setStyleSheet(sheet)
        self.setStyleSheet("")
        self.style().unpolish(self)
        self.style().polish(self)
        for child in self.findChildren(QWidget):
            try:
                child.style().unpolish(child)
                child.style().polish(child)
                child.update()
            except Exception:
                pass
        self.update()

    def _clear_layout_recursive(self, layout):
        """递归移除布局中的控件和子布局。"""
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)

            child_widget = item.widget()
            if child_widget is not None:
                child_widget.hide()
                child_widget.setParent(None)
                child_widget.deleteLater()
                continue

            child_layout = item.layout()
            if child_layout is not None:
                self._clear_layout_recursive(child_layout)

    def clear_layout(self, widget):
        """
        安全替换页面布局：
        先递归清空旧内容，再把旧 layout 转移给临时 QWidget，
        由 Qt 正常释放。避免直接 deleteLater(layout) 后立刻给同一
        QWidget 设置新 layout 引发 Qt 生命周期问题。
        """
        old = widget.layout()
        if old is None:
            return

        self._clear_layout_recursive(old)

        holder = QWidget()
        holder.setLayout(old)
        holder.deleteLater()

    def page_header(self, title, subtitle=""):
        box = QVBoxLayout()
        t = QLabel(title); t.setStyleSheet("font-size:26px;font-weight:700;")
        box.addWidget(t)
        if subtitle:
            s = QLabel(subtitle, objectName="muted"); s.setContentsMargins(0,0,0,8)
            box.addWidget(s)
        return box

    def set_active_nav(self, key):
        """Update only the old/new sidebar buttons; do not repolish every button per click."""
        old_key = getattr(self, "_active_nav_key", None)
        if old_key == key:
            return
        buttons = getattr(self, "nav_buttons", {})
        for nav_key in (old_key, key):
            btn = buttons.get(nav_key)
            if btn is None:
                continue
            btn.setObjectName("navActive" if nav_key == key else "nav")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.update()
        self._active_nav_key = key

    def _navigation_data_token(self):
        """Cheap change token for navigation refresh decisions; no business queries are executed."""
        app_root = Path(__file__).resolve().parents[2]
        studio = Path(DB_PATH)
        intake = app_root / "data" / "pre_gpt_pipeline.sqlite3"
        paths = (
            studio, Path(str(studio) + "-wal"),
            intake, Path(str(intake) + "-wal"),
        )
        stamps = []
        for path in paths:
            try:
                stat = path.stat()
                stamps.append((str(path), int(stat.st_mtime_ns), int(stat.st_size)))
            except OSError:
                stamps.append((str(path), 0, 0))
        return (work_dates.active(), tuple(stamps))

    def _navigation_key_for_widget(self, widget):
        mapping = {
            # Recipient/host editor pages are Task Center sub-pages, not separate sidebar destinations.
            getattr(self, "dashboard", None): "intake",
            getattr(self, "recipient_page", None): "intake",
            getattr(self, "host_page", None): "intake",
            getattr(self, "task_intake_page", None): "intake",
            getattr(self, "prompt_center", None): "prompt",
            getattr(self, "flow_task_center", None): "flow",
            getattr(self, "qc_page", None): "qc",
            getattr(self, "davinci_page", None): "davinci",
            getattr(self, "packaging_page", None): "packaging",
            getattr(self, "stats_page", None): "stats",
        }
        return mapping.get(widget, "detail")

    @staticmethod
    def _capture_scroll_state(page):
        state = []
        for area in page.findChildren(QScrollArea):
            try:
                state.append((area.verticalScrollBar().value(), area.horizontalScrollBar().value()))
            except Exception:
                pass
        return state

    @staticmethod
    def _restore_scroll_state(page, state):
        for area, values in zip(page.findChildren(QScrollArea), state):
            vertical, horizontal = values
            try:
                area.verticalScrollBar().setValue(vertical)
                area.horizontalScrollBar().setValue(horizontal)
            except RuntimeError:
                pass

    def _navigate(self, key, page, refresh=None, refresh_name="refresh"):
        """Show first, then refresh only when backing data changed."""
        started = time.perf_counter()
        source = self._navigation_key_for_widget(self.stack.currentWidget())
        self.set_active_nav(key)
        if self.stack.currentWidget() is not page:
            self.stack.setCurrentWidget(page)
        display_ms = int((time.perf_counter() - started) * 1000)
        runtime_log.log(
            "navigation", level="WARNING" if display_ms > 100 else "INFO",
            message=f"[NAV] {source} -> {key}: {display_ms}ms",
            source=source, target=key, elapsed_ms=display_ms, phase="display",
            slow_step="display" if display_ms > 100 else "",
        )

        if refresh is None:
            return
        current_token = self._navigation_data_token()
        if self._nav_refresh_tokens.get(key) == current_token:
            return

        self._nav_request_serial += 1
        request_serial = self._nav_request_serial
        scroll_state = self._capture_scroll_state(page)

        def run_refresh():
            # Rapid page switching must not leave old pages doing expensive hidden refreshes.
            if request_serial != self._nav_request_serial or self.stack.currentWidget() is not page:
                return
            refresh_started = time.perf_counter()
            try:
                refresh()
                self._nav_refresh_tokens[key] = self._navigation_data_token()
            finally:
                refresh_ms = int((time.perf_counter() - refresh_started) * 1000)
                self._restore_scroll_state(page, scroll_state)
                level = "WARNING" if refresh_ms > 100 else "INFO"
                runtime_log.log(
                    "navigation_refresh", level=level,
                    message=f"[NAV] {source} -> {key}: {refresh_ms}ms ({refresh_name})",
                    source=source, target=key, elapsed_ms=refresh_ms,
                    phase="refresh", slow_step=refresh_name if refresh_ms > 100 else "",
                )

        # Let Qt paint the selected page before any database/UI refresh work begins.
        QTimer.singleShot(0, run_refresh)

    def show_flow_task_center(self):
        self._navigate("flow", self.flow_task_center, self.flow_task_center.reload_filters, "reload_filters")

    def show_task_intake(self):
        self._navigate("intake", self.task_intake_page, self.task_intake_page.refresh, "refresh")

    def show_prompt_center(self):
        self._navigate("prompt", self.prompt_center, self.prompt_center.reload_filters, "reload_filters")


    def closeEvent(self, event):
        dialog=getattr(self,'_reflow_rules_dialog',None)
        if dialog is not None and dialog.worker is not None:
            self.statusBar().showMessage('自动断行正在保存，请完成后关闭。',3000);event.ignore();return
        center=getattr(self,'flow_task_center',None)
        lane=getattr(center,'_production_lane',None)
        if lane is not None:
            lane.close()
            if lane.running or lane.in_manual:
                self.statusBar().showMessage('正在完成当前后台操作，完成后自动关闭…',3000)
                event.ignore();QTimer.singleShot(200,self.close);return
        try:
            self.settings.setValue("window_geometry", self.saveGeometry())
        except Exception:
            pass
        try:
            if hasattr(self, "local_bridge"):
                self.local_bridge.stop()
        except Exception:
            pass
        super().closeEvent(event)

    def show_qc_page(self):
        self._navigate(
            "qc", self.qc_page,
            lambda: self.qc_page._refresh_qc_data(force=False, preserve_player=True),
            "qc_signature_refresh",
        )

    def show_davinci_page(self):
        self._navigate("davinci", self.davinci_page, self.davinci_page.refresh_queue_if_changed, "queue_signature_refresh")

    def show_packaging_page(self):
        # UI-only incremental page: switching here performs no DB / Flow / Resolve refresh.
        self._navigate("packaging", self.packaging_page)

    def show_stats_page(self):
        self._navigate("stats", self.stats_page, lambda: self.stats_page.reload(force=False), "analytics_refresh")

    def future_feature(self, name):
        QMessageBox.information(self, "下一阶段", f"{name} 已预留入口。\n\nV0.13.1 已升级为全局通道池调度：统一配置 CH 通道、R1 高速返工、精确任务命名、通道文件夹监听与详细日志。")

    def make_stat_card(self, title, value, subtitle=""):
        card = QFrame(objectName="statCard")
        card.setFixedHeight(150)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        v = QVBoxLayout(card)
        v.setContentsMargins(20,18,20,18)
        v.setSpacing(6)

        # 所有卡片使用完全相同的三层结构，保证标题、数字、小字水平对齐。
        title_label = QLabel(title, objectName="statTitle")
        title_label.setFixedHeight(24)
        title_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        value_label = QLabel(value, objectName="statValue")
        value_label.setFixedHeight(48)
        value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        subtitle_label = QLabel(subtitle or " ", objectName="statSubtitle")
        subtitle_label.setFixedHeight(24)
        subtitle_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        v.addWidget(title_label)
        v.addWidget(value_label)
        v.addWidget(subtitle_label)
        v.addStretch(1)
        return card

    def show_dashboard(self):
        """Legacy compatibility entry: Task Center has replaced Home as the production landing page."""
        self.show_task_intake()

    def _render_dashboard(self):
        """Production cockpit: overview only; management lives in downstream pages."""
        self.set_active_nav("dashboard")
        self.stack.setCurrentWidget(self.dashboard)
        self.clear_layout(self.dashboard)

        outer, _dash_scroll, _dash_content = self._new_scroll_page_layout(self.dashboard, 760, (24,20,24,20), 14)

        # Header
        header = QHBoxLayout()
        left = QVBoxLayout()
        title = QLabel("首页", objectName="pageTitle")
        subtitle = QLabel("所选日期生产总览", objectName="pageSubtitle")
        left.addWidget(title); left.addWidget(subtitle)
        header.addLayout(left); header.addStretch(1)
        today = work_dates.active()
        header.addWidget(QLabel(today, objectName="muted"))
        outer.addLayout(header)

        metrics = repo.global_dashboard(work_date=work_dates.active())
        pipe = repo.pipeline_queue_counts(work_date=work_dates.active())
        report = repo.daily_production_report(work_date=work_dates.active())
        quality_today = repo.quality_summary(1, work_date=work_dates.active())
        completed = int(quality_today.get("final_outputs", 0) or 0)
        total_videos = int(metrics.get("videos", 0) or 0)
        pct = int(completed / max(total_videos, 1) * 100) if total_videos else int(metrics.get("overall_progress",0) or 0)

        # Compact core metrics: no duplicate progress concepts.
        stats = QHBoxLayout(); stats.setSpacing(10)
        for label, value, sub in [
            ("当日任务", f'{metrics.get("recipients",0)} 接收人', ""),
            ("AI主播", str(metrics.get("hosts",0)), ""),
            ("待生产视频", str(max(total_videos-completed,0)), ""),
            ("已完成视频", str(completed), ""),
            ("当日完成率", f"{pct}%", ""),
        ]:
            card=self.make_stat_card(label,value,sub); card.setFixedHeight(104); stats.addWidget(card,1)
        outer.addLayout(stats)

        body = QSplitter(Qt.Horizontal)
        body.setChildrenCollapsible(False)
        body.setHandleWidth(8)

        # Left: today tasks.
        tasks_card=QFrame(objectName="pageCard")
        tv=QVBoxLayout(tasks_card); tv.setContentsMargins(16,14,16,14); tv.setSpacing(8)
        th=QHBoxLayout(); th.addWidget(QLabel("当日任务", objectName="sectionTitle")); th.addStretch(1)
        go=QPushButton("进入任务中心 →"); go.clicked.connect(self.show_task_intake); th.addWidget(go); tv.addLayout(th)
        task_scroll=QScrollArea(objectName="cardScroll"); task_scroll.setWidgetResizable(True); task_scroll.setFrameShape(QFrame.NoFrame)
        task_content=QWidget(objectName="scrollContent"); tl=QVBoxLayout(task_content); tl.setContentsMargins(0,0,0,0); tl.setSpacing(6); tl.setAlignment(Qt.AlignTop)
        rows=repo.list_recipients(work_date=work_dates.active())
        if not rows:
            empty=QLabel("暂无任务 · 在任务中心同步 Google Sheet", objectName="muted"); empty.setAlignment(Qt.AlignCenter); tl.addWidget(empty)
        for r in rows:
            d=repo.recipient_dashboard(r["id"], work_date=work_dates.active())
            row=ClickableFrame(objectName="compactCard"); rr=QHBoxLayout(row); rr.setContentsMargins(12,9,12,9)
            initial=QLabel((r["name"] or "?")[:1], objectName="recipientInitial"); initial.setAlignment(Qt.AlignCenter); rr.addWidget(initial)
            info=QVBoxLayout(); name=QLabel(r["name"], objectName="cardTitle"); meta=QLabel(f'{len(d["hosts"])} 主播 · {d["total"]} 视频',objectName="cardMeta"); info.addWidget(name);info.addWidget(meta);rr.addLayout(info,1)
            abnormal=max(0,int(d["total"] or 0)-int(d["ready"] or 0))
            status=QLabel("✓ 准备正常" if abnormal==0 and d["total"] else (f"⚠ {abnormal} 待准备" if abnormal else "等待任务"), objectName="statusGood" if abnormal==0 else "statusWarn")
            rr.addWidget(status); row.clicked.connect(lambda rid=r["id"]: self.show_recipient(rid)); tl.addWidget(row)
        tl.addStretch(1); task_scroll.setWidget(task_content); tv.addWidget(task_scroll,1); body.addWidget(tasks_card)

        # Right: live production dynamics, kept concise.
        live_card=QFrame(objectName="pageCard")
        lv=QVBoxLayout(live_card); lv.setContentsMargins(16,14,16,14); lv.setSpacing(10)
        lv.addWidget(QLabel("生产动态", objectName="sectionTitle"))
        flow_wait=int(pipe.get("flow_waiting",0) or 0); flow_active=int(pipe.get("flow_active",0) or 0)
        qc=int(pipe.get("qc_waiting",0) or 0); edit=int(pipe.get("edit_waiting",0) or 0)
        for icon,title,value,note in [
            ("●","Flow 生成",flow_active,f"等待 {flow_wait}"),
            ("✓","人工质检",qc,"待检查"),
            ("✂","自动剪辑",edit,"等待剪辑"),
        ]:
            line=QFrame(objectName="compactCard"); hr=QHBoxLayout(line);hr.setContentsMargins(12,10,12,10)
            hr.addWidget(QLabel(icon,objectName="statusInfo")); hr.addWidget(QLabel(title,objectName="cardTitle"));hr.addStretch(1);hr.addWidget(QLabel(str(value),objectName="bigNumber"));hr.addWidget(QLabel(note,objectName="muted"));lv.addWidget(line)
        lv.addStretch(1); body.addWidget(live_card); body.setSizes([760,500]); body.setMinimumHeight(330); body.setMaximumHeight(560); outer.addWidget(body)

        # Whole-factory pipeline: counts are navigation, not another percent bar.
        pipeline=QFrame(objectName="topStrip")
        ph=QHBoxLayout(pipeline); ph.setContentsMargins(14,10,14,10); ph.setSpacing(8)
        ph.addWidget(QLabel("生产流水线",objectName="cardTitle"))
        stages=[("任务中心",metrics.get("recipients",0),self.show_task_intake),("GPT提示词",pipe.get("flow_waiting",0),self.show_prompt_center),("Flow生成",flow_active,self.show_flow_task_center),("人工质检",qc,self.show_qc_page),("自动剪辑",edit,self.show_davinci_page)]
        for i,(name,count,fn) in enumerate(stages):
            b=QPushButton(f"{name}  {int(count or 0)}",objectName="chipBtn"); b.clicked.connect(fn);ph.addWidget(b,1)
            if i<len(stages)-1: ph.addWidget(QLabel("→",objectName="muted"))
        outer.addWidget(pipeline)

        # One-line system health.
        health=QFrame(objectName="topStrip"); hh=QHBoxLayout(health);hh.setContentsMargins(14,8,14,8)
        hh.addWidget(QLabel("系统状态",objectName="cardTitle"));hh.addSpacing(12)
        for text in ("🟢 Google Sheet","🟢 Google Drive","🟢 Flow Bridge","🟢 GPT API"):
            hh.addWidget(QLabel(text,objectName="muted"))
        hh.addStretch(1); outer.addWidget(health)

    def dashboard_recipient_card(self, r):
        data = repo.recipient_dashboard(r["id"], work_date=work_dates.active())
        card = QFrame(objectName="projectCard")
        card.setFixedHeight(190)
        main = QHBoxLayout(card)
        main.setContentsMargins(18,14,18,14)
        main.setSpacing(16)

        identity = QVBoxLayout()
        name = QLabel(r["name"], objectName="projectName")
        creator = self.global_creator() or "未设置"
        meta = QLabel(
            f'代码 {r["fixed_code"]}  ·  制作者 {creator}  ·  日期 {r["work_date"]}',
            objectName="muted"
        )
        meta.setWordWrap(False)
        identity.addWidget(name)
        identity.addWidget(meta)
        identity.addStretch(1)
        main.addLayout(identity, 2)

        host_box = QVBoxLayout()
        host_title = QLabel(f'AI 主播（{len(data["hosts"])}个）')
        host_title.setStyleSheet("font-weight:700;")
        host_box.addWidget(host_title)
        host_row = QHBoxLayout()
        host_row.setSpacing(8)

        for h in data["hosts"][:3]:
            mini = QFrame(objectName="hostMiniCard")
            mini.setFixedSize(125, 112)
            mv = QVBoxLayout(mini)
            mv.setContentsMargins(6,6,6,6)
            mv.setSpacing(4)

            thumb = QLabel(objectName="thumb")
            thumb.setFixedSize(111, 68)
            thumb.setAlignment(Qt.AlignCenter)
            thumb_path = h["thumbnail"]
            set_image(thumb, thumb_path)
            mv.addWidget(thumb)

            label = QLabel(f'{h["name"]} · {h["video_count"]}个')
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet("font-size:11px;font-weight:600;")
            mv.addWidget(label)
            host_row.addWidget(mini)

        if len(data["hosts"]) > 3:
            more = QLabel(f'+{len(data["hosts"])-3} 个', objectName="muted")
            host_row.addWidget(more)
        host_row.addStretch(1)
        host_box.addLayout(host_row)
        main.addLayout(host_box, 4)

        progress_box = QVBoxLayout()
        total = data["total"]
        ready = data["ready"]
        pct = data["overall_progress"]
        progress_title = QLabel(f"整体流程进度 · {pct}%")
        progress_title.setStyleSheet("font-weight:700;")
        progress_box.addWidget(progress_title)
        bar = QProgressBar()
        bar.setRange(0,100)
        bar.setValue(pct)
        bar.setTextVisible(False)
        progress_box.addWidget(bar)

        detail = QLabel(
            f'完整视频 {total} · 已齐全 {ready} · 中文 {data["chinese"]} · 外文 {data["foreign"]} · 图片 {data["images"]}',
            objectName="muted"
        )
        detail.setWordWrap(True)
        progress_box.addWidget(detail)

        if data["qa_passed"] and data["flow_segments"] and data["qa_passed"] == data["flow_segments"]:
            stage = "● Flow 片段质检已完成，等待自动剪辑"
        elif data["generated"]:
            stage = "● Flow 生成/质检进行中"
        elif data["prompt_ready"]:
            stage = "● GPT 提示词已开始生成"
        elif total and ready == total:
            stage = "● 资料齐全，等待生成 GPT 提示词"
        elif data["chinese"] or data["foreign"] or data["images"]:
            stage = "● 资料准备中"
        else:
            stage = "● 等待导入文案/图片"
        stage_label = QLabel(stage)
        stage_label.setObjectName("accentText")
        progress_box.addWidget(stage_label)
        main.addLayout(progress_box, 3)

        actions = QVBoxLayout()
        enter = QPushButton("进入项目 →", objectName="primaryBtn")
        enter.clicked.connect(partial(self.show_recipient, r["id"]))
        delete = QPushButton("删除", objectName="dangerBtn")
        delete.clicked.connect(partial(self.remove_recipient, r["id"], r["name"]))
        actions.addWidget(enter)
        actions.addWidget(delete)
        actions.addStretch(1)
        main.addLayout(actions, 1)
        return card

    def add_recipient(self):
        d = AddRecipientDialog(self.default_code(), self)
        if d.exec():
            name, code, work_date = d.values()
            if not name.strip():
                QMessageBox.warning(self, "缺少信息", "请填写接收人。")
                return
            rid = repo.add_recipient(name, code, self.global_creator(), work_date)
            self.show_recipient(rid)

    def remove_recipient(self, rid, name):
        if QMessageBox.question(self, "确认删除", f"删除“{name}”及其全部数据？") == QMessageBox.Yes:
            repo.delete_recipient(rid); self.show_dashboard()

    def show_recipient(self, rid):
        # Kept for compatibility with older actions; this is now a Task Center sub-page.
        self.current_recipient_id = rid
        r = repo.get_recipient(rid)
        self.set_active_nav("intake")
        self.stack.setCurrentWidget(self.recipient_page)
        self.clear_layout(self.recipient_page)

        layout, _recipient_scroll, _recipient_content = self._new_scroll_page_layout(self.recipient_page, 720, (28,24,28,24), 14)

        back = QPushButton("← 返回任务中心")
        back.setMaximumWidth(220)
        back.clicked.connect(self.show_task_intake)
        layout.addWidget(back, 0, Qt.AlignLeft)

        layout.addLayout(self.page_header(
            f'{r["name"]} · AI 主播管理',
            f'固定编号：{r["fixed_code"]}   制作者：{self.global_creator() or "未设置"}   日期：{r["work_date"]}'
        ))

        top = QHBoxLayout()
        top.addStretch(1)
        add = QPushButton("+ 添加 AI 主播", objectName="primaryBtn")
        add.setMinimumWidth(150)
        add.setEnabled(True)
        add.setToolTip(f"新主播将保存到当前工作日期：{work_dates.active()}")
        add.clicked.connect(self.add_host)
        top.addWidget(add)
        layout.addLayout(top)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget(objectName="scrollContent")
        cards = QVBoxLayout(content)
        cards.setContentsMargins(0,0,0,0)
        cards.setSpacing(12)
        cards.setAlignment(Qt.AlignTop)

        hosts = repo.list_hosts(rid, work_date=work_dates.active())
        if not hosts:
            empty = QFrame(objectName="projectCard")
            empty.setFixedHeight(140)
            ev = QVBoxLayout(empty)
            ttl = QLabel("还没有 AI 主播")
            ttl.setAlignment(Qt.AlignCenter)
            ttl.setStyleSheet("font-size:18px;font-weight:700;")
            sub = QLabel("点击右上角“添加 AI 主播”创建第一个主播。", objectName="muted")
            sub.setAlignment(Qt.AlignCenter)
            ev.addWidget(ttl)
            ev.addWidget(sub)
            cards.addWidget(empty)
        else:
            for hrow in hosts:
                card = QFrame(objectName="projectCard")
                card.setFixedHeight(96)
                row = QHBoxLayout(card)
                row.setContentsMargins(16,12,16,12)
                info = QVBoxLayout()
                title = QLabel(hrow["name"])
                title.setStyleSheet("font-size:18px;font-weight:700;")
                sub = QLabel(f'完整视频 {hrow["video_count"]} 个 · 编号 01～{hrow["video_count"]:02d}', objectName="muted")
                info.addWidget(title)
                info.addWidget(sub)
                info.addStretch(1)
                row.addLayout(info, 1)

                manage = QPushButton("管理文案/图片")
                manage.setMinimumWidth(130)
                manage.clicked.connect(partial(self.show_host, hrow["id"]))
                row.addWidget(manage)
                delete = QPushButton("删除主播", objectName="dangerBtn")
                delete.setMinimumWidth(100)
                delete.clicked.connect(partial(self.remove_host, hrow["id"], hrow["name"]))
                row.addWidget(delete)
                cards.addWidget(card)

        cards.addStretch(1)
        scroll.setWidget(content)
        scroll.setMinimumHeight(360); scroll.setMaximumHeight(700); layout.addWidget(scroll)

    def add_host(self):
        d = AddHostDialog(self)
        if d.exec():
            name, count = d.values()
            if not name.strip():
                QMessageBox.warning(self, "缺少信息", "请填写主播名称。")
                return
            try:
                # Historical workspaces are editable, but a write must stay inside
                # the date partition currently selected in the task calendar.
                work_dates.require_recipient_work_date(self.current_recipient_id, work_dates.active())
                repo.add_host(self.current_recipient_id, name, count)
                self.show_recipient(self.current_recipient_id)
            except Exception as exc:
                QMessageBox.critical(
                    self,
                    "添加主播失败",
                    f"添加主播时发生错误：\n\n{type(exc).__name__}: {exc}"
                )
                raise

    def remove_host(self, host_id, name):
        if QMessageBox.question(self,"确认删除",f"删除主播“{name}”及其全部视频？")==QMessageBox.Yes:
            repo.delete_host(host_id); self.show_recipient(self.current_recipient_id)

    def show_host(self, host_id):
        if hasattr(self, "_wrap_reflow_timer"): self._wrap_reflow_timer.stop()
        self.current_host_id = host_id
        host = repo.get_host_with_recipient(host_id)
        if not host:
            QMessageBox.warning(self, "主播管理", "找不到该主播，可能已被删除或属于其他任务日期。")
            self.show_task_intake()
            return
        self.current_recipient_id = int(host["recipient_id"])
        self.host_meta = host
        self.set_active_nav("intake")
        self.stack.setCurrentWidget(self.host_page)
        self.clear_layout(self.host_page)
        layout, _host_scroll, _host_content = self._new_scroll_page_layout(self.host_page, 760, (24,20,24,20), 12)
        back=QPushButton("← 返回任务中心"); back.clicked.connect(self.show_task_intake); layout.addWidget(back)
        layout.addLayout(self.page_header(
            f'任务中心 / {host["recipient_name"]} / {host["name"]}',
            f'主播文案与图片管理 · 共 {host["video_count"]} 条；支持从 Google Sheets 直接复制整块区域后 ⌘V 粘贴。'
        ))

        tools=QHBoxLayout()
        tools.addWidget(QLabel("辅助参考字符数"))
        self.wrap_width=QLineEdit(self.default_wrap())
        self.wrap_width.setFixedWidth(90)
        self.wrap_width.setPlaceholderText("任意正整数")
        self.wrap_width.setToolTip("新版以约 7.5 秒自然斯瓦希里语朗读为主；字符数仅用于同等方案下的节奏微调，不会作为硬拆分条件。没有自然标点时禁止硬拆。")
        tools.addWidget(self.wrap_width)
        # Debounce live changes: changing 80 -> 70 automatically reflows the current host
        # without requiring another button click, while avoiding a DB rewrite on every keypress.
        if not hasattr(self, "_wrap_reflow_timer"):
            self._wrap_reflow_timer = QTimer(self)
            self._wrap_reflow_timer.setSingleShot(True)
            self._wrap_reflow_timer.setInterval(650)
            self._wrap_reflow_timer.timeout.connect(lambda: self.auto_wrap_foreign(silent=True))
        self.wrap_width.textChanged.connect(self._schedule_wrap_width_reflow)
        wrap_btn=QPushButton("⚡ 外语智能断行")
        wrap_btn.clicked.connect(lambda: self.auto_wrap_foreign())
        tools.addWidget(wrap_btn)
        undo_btn=QPushButton("↶ 撤销"); undo_btn.setToolTip("撤销最近一次批量粘贴、自动断行或批量删除（Command+Z）"); undo_btn.clicked.connect(self.undo_table_action); tools.addWidget(undo_btn)
        img_btn=QPushButton("导入编号图片文件夹"); img_btn.clicked.connect(self.import_numbered_images); tools.addWidget(img_btn)
        clear_zh=QPushButton("清空中文"); clear_zh.clicked.connect(self.clear_chinese_column); tools.addWidget(clear_zh)
        clear_foreign=QPushButton("清空外文"); clear_foreign.clicked.connect(self.clear_foreign_column); tools.addWidget(clear_foreign)
        clear_images=QPushButton("清空图片"); clear_images.clicked.connect(self.clear_image_column); tools.addWidget(clear_images)
        rules_btn=QPushButton("自动断行规则"); rules_btn.clicked.connect(self.open_reflow_rules); tools.addWidget(rules_btn)
        tools.addStretch(1)
        layout.addLayout(tools)

        note=QLabel("表格列顺序：编号 ｜ 中文对照 ｜ 外语文案 ｜ 参考图片。最终文件名由后台 Naming Engine 自动生成，不占用表格列。")
        note.setObjectName("muted")
        layout.addWidget(note)

        table=SpreadsheetTable()
        self.host_table=table
        from app.ui.sheet_rich_text import SheetTextDelegate, attach
        from app.services.sheet_style import load_video
        table.setItemDelegateForColumn(1, SheetTextDelegate(table))
        table.setItemDelegateForColumn(2, SheetTextDelegate(table))
        videos=repo.list_videos(host_id, work_date=work_dates.active())
        table.setRowCount(len(videos)); table.setColumnCount(4)
        table.setHorizontalHeaderLabels(["编号","中文对照","外语文案","参考图片"])

        # Google Sheets 风格：所有列都在当前窗口内显示，不需要横向拖动。
        header = table.horizontalHeader()
        header.setStretchLastSection(False)

        header.setSectionResizeMode(0, QHeaderView.Fixed)
        table.setColumnWidth(0, 62)

        header.setSectionResizeMode(1, QHeaderView.Stretch)  # 中文对照
        header.setSectionResizeMode(2, QHeaderView.Stretch)  # 外语文案

        header.setSectionResizeMode(3, QHeaderView.Fixed)
        table.setColumnWidth(3, 92)


        # 中文/外语都允许在单元格内自动换行。
        # 原本真实换行仍然保留；长文本只是在当前列宽下视觉折行。
        table.setWordWrap(True)
        table.setAlternatingRowColors(True)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        table.verticalHeader().setDefaultSectionSize(118)
        table.verticalHeader().setMinimumSectionSize(72)

        for row,v in enumerate(videos):
            n=QTableWidgetItem(f'{v["seq"]:02d}'); n.setFlags(n.flags() & ~Qt.ItemIsEditable); table.setItem(row,0,n)
            source_styles = load_video(v['id'])
            zh_style = source_styles.get('中文内容', {})
            foreign_style = source_styles.get('外文内容', {})
            zh_text = zh_style.get('text', '') if zh_style and not zh_style.get('local_override') else (v['chinese_script'] or '')
            zh=QTableWidgetItem(zh_text); table.setItem(row,1,zh)
            attach(zh, zh_style)
            segment_text = repo.get_flow_segment_text(v["id"])
            foreign_text = segment_text if segment_text.strip() else (v["script"] or "")
            if foreign_style and not foreign_style.get('local_override'):
                foreign_text = foreign_style.get('text', '')
            foreign=QTableWidgetItem(foreign_text); table.setItem(row,2,foreign)
            attach(foreign, foreign_style)
            image=QTableWidgetItem(Path(v["image_path"]).name if v["image_path"] else "未匹配"); image.setFlags(image.flags() & ~Qt.ItemIsEditable); table.setItem(row,3,image)

        table.itemChanged.connect(self.host_item_changed)
        table.itemDoubleClicked.connect(self.open_multiline_cell)
        table.after_bulk_paste = self.after_bulk_paste
        self.ensure_multiline_row_heights()
        table.setMinimumHeight(420); table.setMaximumHeight(900); layout.addWidget(table)

    def ensure_multiline_row_heights(self):
        if not self.host_table:
            return

        # 先让 Qt 根据当前列宽和 word-wrap 计算需要的高度。
        self.host_table.resizeRowsToContents()

        # 保留可读的最小高度，并限制极端长文案不要把一行撑满整个屏幕。
        for row in range(self.host_table.rowCount()):
            natural = self.host_table.rowHeight(row)
            target = max(92, min(natural + 8, 240))
            self.host_table.setRowHeight(row, target)

    def host_item_changed(self, item):
        if item.column() not in (1,2):
            return
        row=item.row()
        videos=repo.list_videos(self.current_host_id, work_date=work_dates.active())
        if row >= len(videos): return
        v=videos[row]
        from app.ui.sheet_rich_text import BASELINE_ROLE
        from app.services.sheet_style import mark_edited
        if item.text() == item.data(BASELINE_ROLE):
            return
        if item.column() == 1:
            repo.update_video_fields(v['id'], chinese=item.text())
            mark_edited(v['id'], '中文内容')
        else:
            lines = [line.strip() for line in item.text().splitlines() if line.strip()]
            if not repo.sync_flow_segments(v['id'], lines, edit_unstarted=True, manual_lock=True):
                self.host_table.blockSignals(True)
                item.setText(item.data(BASELINE_ROLE) or '')
                self.host_table.blockSignals(False)
                return
            repo.update_video_fields(v['id'], foreign=item.text())
            mark_edited(v['id'], '外文内容')
        self.host_table.blockSignals(True)
        item.setData(BASELINE_ROLE, item.text())
        self.host_table.blockSignals(False)
        self.ensure_multiline_row_heights()

    def after_bulk_paste(self):
        self.save_all_host_rows()
        if self.host_table:
            self.ensure_multiline_row_heights()

    def save_all_host_rows(self):
        if not self.host_table: return
        # Only explicit cell edits are saved; displaying a source snapshot must not
        # overwrite prepared production text or change existing segments.
        for row in range(self.host_table.rowCount()):
            for col in (1, 2):
                item = self.host_table.item(row, col)
                if item: self.host_item_changed(item)
        self.ensure_multiline_row_heights()


    def open_reflow_rules(self):
        dialog=getattr(self,'_reflow_rules_dialog',None)
        if dialog is not None:
            dialog.show();dialog.raise_();dialog.activateWindow();return
        from app.ui.reflow_rules_dialog import ReflowRulesDialog
        dialog=ReflowRulesDialog(self);self._reflow_rules_dialog=dialog
        dialog.destroyed.connect(lambda:setattr(self,'_reflow_rules_dialog',None))
        dialog.applied.connect(lambda _:self.show_host(self.current_host_id) if self.current_host_id else None)
        dialog.show()

    def refresh_filename_row(self,row,seq,zh):
        # V0.13.3: final names are generated in the background when needed.
        return

    def _schedule_wrap_width_reflow(self, text):
        raw = str(text or "").strip()
        if raw.isdigit() and int(raw) > 0 and hasattr(self, "_wrap_reflow_timer"):
            self._wrap_reflow_timer.start()

    def auto_wrap_foreign(self, *, silent=False):
        if not self.host_table:
            return
        raw = self.wrap_width.text().strip()
        if not raw.isdigit() or int(raw) <= 0:
            QMessageBox.warning(self, "断行设置", "请输入大于 0 的整数。")
            return
        width = int(raw)
        self.settings.setValue("default_wrap", raw)
        repo.set_setting("default_wrap", raw)

        self.host_table.push_undo_snapshot()
        videos = repo.list_videos(self.current_host_id, work_date=work_dates.active())

        self.host_table.blockSignals(True)
        try:
            for row, v in enumerate(videos):
                item = self.host_table.item(row, 2)
                if not item:
                    continue
                current = item.text()
                # If this row was already auto-prepared, re-use the permanent source original.
                # A genuinely changed cell becomes the new source; existing manual segment locks
                # are still protected by sync_flow_segments below.
                current_key = re.sub(r"\s+", "", current or "")
                production_key = re.sub(r"\s+", "", (v["production_script"] or v["script"] or ""))
                source = (v["original_script"] or "") if (v["original_script"] and current_key == production_key) else current
                prepared = prepare_swahili_speech(source, max_chars=width)
                if not prepared.integrity_ok:
                    if not silent:
                        QMessageBox.warning(self, "断行校验", f"第 {row+1} 条文案完整性校验失败，已保持原状态。")
                    continue
                lines = list(prepared.segments)
                timing_meta = []
                for timing in prepared.timings:
                    meta = dict(timing)
                    if prepared.timing_status == "UNSPLITTABLE" and meta.get("needs_split"):
                        meta["timing_status"] = "UNSPLITTABLE"
                    timing_meta.append(meta)
                from app.services import eye_states, sheet_style
                snapshot = sheet_style.load_video(v['id']).get('外文内容',{})
                color_modes = []
                spoken = prepared.spoken_text
                if snapshot and not snapshot.get('local_override') and ''.join(snapshot.get('text','').split()) == ''.join(source.split()):
                    lines, color_modes, timing_meta, spoken = eye_states.prepare(snapshot,lambda text:prepare_swahili_speech(text,max_chars=width),v['performance_mode'])
                wrapped = "\n".join(lines)
                # Changing the visible max-character setting is an explicit user reflow command.
                # It may replace prior unstarted manual segmentation, but the existing downstream
                # safety checks still block any segment that has entered Prompt/Flow/QC.
                if not repo.sync_flow_segments(v["id"], lines, edit_unstarted=True, manual_lock=True, timing_meta=timing_meta):
                    continue
                if color_modes:
                    eye_states.save_modes(v['id'],lines,color_modes)
                else:
                    item.setText(wrapped)
                repo.update_video_source_text(v["id"], source, spoken)
        finally:
            self.host_table.blockSignals(False)

        self.save_all_host_rows()
        self.host_table.resizeRowsToContents()
        self.statusBar().showMessage("外语已按约 7.5 秒斯瓦希里语规则智能断行。", 2500)

    def open_multiline_cell(self, item):
        if item.column() not in (1, 2):
            return

        row = item.row()
        videos = repo.list_videos(self.current_host_id, work_date=work_dates.active())
        from app.ui.sheet_rich_text import STYLE_ROLE, apply
        source_snapshot = item.data(STYLE_ROLE)
        if source_snapshot and source_snapshot.get('text') != item.text(): source_snapshot = None
        current_value = item.text().replace("\r\n","\n").replace("\r","\n")

        if item.column() == 2 and row < len(videos) and not source_snapshot:
            stored_segments = repo.get_flow_segment_text(videos[row]["id"])
            if stored_segments.strip():
                current_value = stored_segments

        dialog_day=work_dates.active()
        segment_modes=[]
        if item.column()==2 and row<len(videos):
            vid=videos[row]["id"]
            segment_modes=[t['performance_mode'] for t in repo.list_prompt_tasks(host_id=self.current_host_id,work_date=dialog_day) if t['video_id']==vid]
            if not segment_modes:segment_modes=[videos[row]['performance_mode'] or 'TALKING']*len(current_value.splitlines())
        if item.column() == 1 or source_snapshot:
            d = MultilineEditorDialog("编辑中文对照", current_value, self, segmented=False)
        else:
            d = MultilineEditorDialog("编辑外语分段", current_value, self, segmented=True, segment_modes=segment_modes)

        if source_snapshot:
            apply(d.editor.document(), source_snapshot)
        if d.exec():
            value=d.value()
            if work_dates.active()!=dialog_day:
                QMessageBox.warning(self,"保存失败","任务日期已变化，请重新打开编辑窗口。")
                return
            if item.column()==2 and row<len(videos) and not source_snapshot:
                lines=[x.strip() for x in value.splitlines() if x.strip()]
                old_lines=[x.strip() for x in current_value.splitlines() if x.strip()]
                if lines!=old_lines or not repo.get_flow_segment_text(vid).strip():
                    if not repo.sync_flow_segments(vid,lines,edit_unstarted=True,manual_lock=True):
                        QMessageBox.warning(self,"保留生产记录","该视频已进入后续流程，无法覆盖分段。仍可保留原文，仅修改片段类型。")
                        return
                    repo.update_video_production_text(vid," ".join(lines))
                try:
                    from app.services.performance_types import save_segment_types
                    save_segment_types(vid,lines,d.selected_types(),dialog_day)
                except ValueError as exc:
                    QMessageBox.warning(self,"保存失败",str(exc));return
                if lines==old_lines:
                    self.statusBar().showMessage("片段类型已保存，用于下一次 GPT 提示词生成。",4000)
                    return
            self.host_table.push_undo_snapshot()
            self.host_table.blockSignals(True)
            try:item.setText(value)
            finally:self.host_table.blockSignals(False)
            self.save_all_host_rows()
            self.ensure_multiline_row_heights()

    def clear_chinese_column(self):
        if not self.host_table:
            return
        if not confirm_clear(self, "清空中文", "确认清空当前主播全部中文对照？\n外文和图片不会受影响。"):
            return
        self.host_table.push_undo_snapshot()
        self.host_table.blockSignals(True)
        try:
            for row in range(self.host_table.rowCount()):
                item = self.host_table.item(row, 1)
                if item:
                    item.setText("")
        finally:
            self.host_table.blockSignals(False)
        self.save_all_host_rows()

    def clear_foreign_column(self):
        if not self.host_table:
            return
        if not confirm_clear(self, "清空外文", "确认清空当前主播全部外语文案？\n中文和图片不会受影响。"):
            return
        self.host_table.push_undo_snapshot()
        self.host_table.blockSignals(True)
        try:
            for row in range(self.host_table.rowCount()):
                item = self.host_table.item(row, 2)
                if item:
                    item.setText("")
        finally:
            self.host_table.blockSignals(False)
        self.save_all_host_rows()

    def clear_image_column(self):
        if not self.host_table:
            return
        if not confirm_clear(self, "清空图片", "确认解除当前主播全部参考图片的匹配？\n只清除软件中的图片路径，不会删除硬盘上的原始图片。"):
            return
        repo.clear_host_images(self.current_host_id)
        for row in range(self.host_table.rowCount()):
            item = self.host_table.item(row, 3)
            if item:
                item.setText("未匹配")
        self.statusBar().showMessage("图片匹配已清空；硬盘原图未删除。", 3000)

    def undo_table_action(self):
        if not self.host_table:
            return
        if not self.host_table.undo_last():
            QMessageBox.information(self, "撤销", "目前没有可以撤销的批量操作。")

    def import_numbered_images(self):
        folder=QFileDialog.getExistingDirectory(self,"选择编号图片文件夹")
        if not folder: return
        exts={".jpg",".jpeg",".png",".webp"}
        mapping={}
        for p in Path(folder).iterdir():
            if p.suffix.lower() not in exts: continue
            m=re.match(r"^\s*(\d{1,3})", p.stem)
            if m:
                mapping[int(m.group(1))]=str(p)
        repo.bulk_set_images(self.current_host_id,mapping)
        videos=repo.list_videos(self.current_host_id, work_date=work_dates.active())
        matched=0
        for row,v in enumerate(videos):
            name=Path(v["image_path"]).name if v["image_path"] else "未匹配"
            self.host_table.item(row,3).setText(name)
            if v["image_path"]: matched+=1
        QMessageBox.information(self,"图片匹配",f"已匹配 {matched}/{len(videos)} 张图片。\n支持 01.jpg、02.png、03.webp 等编号格式。")
