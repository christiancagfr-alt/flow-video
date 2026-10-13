"""System settings as a normal page, including the task-sheet column map."""
import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QFormLayout,
    QMessageBox, QFileDialog, QComboBox, QScrollArea, QFrame, QRadioButton,
    QButtonGroup, QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox, QSizePolicy,
)

from app.core import repository as repo
from app.services import sheet_columns

_REAL_GET_SETTING = repo.get_setting


class _ColumnTable(QTableWidget):
    """Keep the column picker inside its cell. The app-wide combo is taller than a row."""

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_column_editors()

    def showEvent(self, event):
        super().showEvent(event)
        self.fit_column_editors()

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        self.fit_column_editors()

    def fit_column_editors(self):
        for row in range(self.rowCount()):
            widget = self.cellWidget(row, 1)
            if widget is None:
                continue
            rect = self.visualRect(self.model().index(row, 1))
            if rect.isValid() and widget.geometry() != rect:
                widget.setGeometry(rect)


_WHISPER_LANGUAGES = [
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
    "爪哇语 (Javanese) · jv", "巽他语 (Sundanese) · su",
]


class SettingsPage(QWidget):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setObjectName('pageRoot')
        self._loading = True
        self._custom_choices = {key: sheet_columns.template_choice(key) for key, *_rest in sheet_columns.FIELDS}
        self._column_boxes = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = QScrollArea(objectName='pageScroll')
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        body = QWidget(objectName='pageScrollContent')
        root = QVBoxLayout(body)
        root.setContentsMargins(24, 20, 24, 24)
        root.setSpacing(12)
        root.setAlignment(Qt.AlignTop)

        title = QLabel('系统设置', objectName='pageTitle')
        root.addWidget(title)
        intro = QLabel('这些设置保存在这台电脑上。改完后点保存，任务中心下次同步会按这里的表格列读取。', objectName='muted')
        intro.setWordWrap(True)
        root.addWidget(intro)

        form_host = QWidget()
        form_host.setMaximumWidth(920)
        form = QFormLayout(form_host)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(10)

        self.creator = QLineEdit()
        self.default_code = QLineEdit()
        self.default_wrap = QLineEdit()
        form.addRow('默认制作人', self.creator)
        form.addRow('默认固定编号', self.default_code)
        form.addRow('默认外语断行字符数', self.default_wrap)

        self.task_sheet = QLineEdit()
        self.task_sheet.setPlaceholderText('每天固定使用的 Google Sheets 链接')
        form.addRow('任务获取表格链接', self.task_sheet)
        form.addRow(self._build_columns())

        asset_wrap = QWidget()
        asset_row = QHBoxLayout(asset_wrap)
        asset_row.setContentsMargins(0, 0, 0, 0)
        self.task_asset_root = QLineEdit()
        self.task_asset_root.setPlaceholderText('主播 Drive 图片下载和任务准备的本地根目录')
        asset_row.addWidget(self.task_asset_root, 1)
        asset_pick = QPushButton('浏览…')
        asset_pick.clicked.connect(lambda: self.pick_folder_into(self.task_asset_root, '选择任务素材本地根目录'))
        asset_row.addWidget(asset_pick)
        form.addRow('任务素材本地根目录', asset_wrap)

        segment_wrap = QWidget()
        segment_row = QHBoxLayout(segment_wrap)
        segment_row.setContentsMargins(0, 0, 0, 0)
        self.segment_output_root = QLineEdit()
        self.segment_output_root.setPlaceholderText('各 Flow 通道下载完成后统一回收成品片段的根目录')
        segment_row.addWidget(self.segment_output_root, 1)
        segment_pick = QPushButton('浏览…')
        segment_pick.clicked.connect(lambda: self.pick_folder_into(self.segment_output_root, '选择成品片段根目录'))
        segment_row.addWidget(segment_pick)
        form.addRow('成品片段根目录', segment_wrap)

        self.drive_upload_root_url = QLineEdit('', self)
        self.drive_upload_root_url.setPlaceholderText('最终成品上传到 Google Drive 的根文件夹链接')
        self.drive_upload_root_url.hide()

        oauth_wrap = QWidget()
        oauth_row = QHBoxLayout(oauth_wrap)
        oauth_row.setContentsMargins(0, 0, 0, 0)
        self.google_oauth_client_path = QLineEdit()
        self.google_oauth_client_path.setPlaceholderText('首次连接 Google 所需的 OAuth Desktop Client JSON')
        oauth_row.addWidget(self.google_oauth_client_path, 1)
        oauth_pick = QPushButton('选择…')
        oauth_pick.clicked.connect(self.pick_oauth_json)
        oauth_row.addWidget(oauth_pick)
        form.addRow('Google OAuth 客户端 JSON', oauth_wrap)

        self.drive_desktop_path = QLineEdit()
        self.drive_desktop_path.setPlaceholderText('留空自动识别Google Drive桌面版；也可选择我的云端硬盘')
        sync_wrap = QWidget(self)
        sync_row = QHBoxLayout(sync_wrap)
        sync_row.setContentsMargins(0, 0, 0, 0)
        sync_row.addWidget(self.drive_desktop_path)
        pick_sync = QPushButton('浏览…')
        pick_sync.clicked.connect(lambda: self.pick_folder_into(self.drive_desktop_path, '选择Google Drive同步目录'))
        sync_row.addWidget(pick_sync)
        sync_wrap.hide()
        self.drive_desktop_folder = QLineEdit('FlowStudio', self)
        self.drive_desktop_folder.hide()

        edit_wrap = QWidget()
        edit_row = QHBoxLayout(edit_wrap)
        edit_row.setContentsMargins(0, 0, 0, 0)
        self.edit_root = QLineEdit()
        self.edit_root.setPlaceholderText('例如 /Volumes/LEONARDO/000/Davinci')
        edit_row.addWidget(self.edit_root, 1)
        browse = QPushButton('浏览…')
        browse.clicked.connect(self.pick_edit_root)
        edit_row.addWidget(browse)
        form.addRow('剪辑路径根目录', edit_wrap)

        self.davinci_executable = QLineEdit()
        self.davinci_executable.setPlaceholderText('留空自动检测；也可选择 Resolve.exe')
        if os.name == 'nt':
            resolve_row = QHBoxLayout()
            resolve_row.addWidget(self.davinci_executable, 1)
            pick = QPushButton('选择…')
            pick.clicked.connect(self.pick_resolve)
            resolve_row.addWidget(pick)
            form.addRow('达芬奇程序', resolve_row)
        else:
            self.davinci_executable.hide()

        from app.services.resolve_daily import FPS_VALUES
        self.timeline_fps = QComboBox()
        self.timeline_fps.addItems(FPS_VALUES)
        form.addRow('达芬奇时间线帧率', self.timeline_fps)

        self.whisper_language = QComboBox()
        self.whisper_language.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.whisper_language.setMinimumContentsLength(16)
        self.whisper_language.addItems(_WHISPER_LANGUAGES)
        form.addRow('自动剪辑口播语言', self.whisper_language)

        tip = QLabel(
            '制作者是整台电脑的全局设置。剪辑根目录用于 DaVinci 的项目媒体、ProxyMedia、CacheClip、.gallery、导入素材与最终导出；'
            '视频质检全部通过后，会自动把源片段从下载目录移动到这个根目录。',
            objectName='muted',
        )
        tip.setWordWrap(True)
        form.addRow(tip)

        actions = QHBoxLayout()
        save_button = QPushButton('保存', objectName='primaryBtn')
        save_button.clicked.connect(self.validate_and_save)
        actions.addWidget(save_button)
        self.status = QLabel('', objectName='muted')
        self.status.setWordWrap(True)
        actions.addWidget(self.status, 1)
        form.addRow(actions)
        root.addWidget(form_host)
        root.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll)
        self.reload()

    def _build_columns(self):
        box = QGroupBox('任务表格列')
        layout = QVBoxLayout(box)
        layout.setSpacing(8)
        note = QLabel(
            '当前表格模板按表头名称读取需求人员、主播名称、中文文案、外文文案和需求说明。'
            '图片链接固定在 J 列。日期不从表格读，新任务使用同步当天。'
            '作者和制作情况按表头回写。任务区间仍然是「批量制作中」到「批量已完成」。',
            objectName='muted',
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        mode_row = QHBoxLayout()
        self.column_mode = QButtonGroup(self)
        self.template_radio = QRadioButton('当前表格模板')
        self.custom_radio = QRadioButton('自定义列')
        self.column_mode.addButton(self.template_radio)
        self.column_mode.addButton(self.custom_radio)
        self.template_radio.toggled.connect(self._apply_column_mode)
        mode_row.addWidget(self.template_radio)
        mode_row.addWidget(self.custom_radio)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        self.column_table = _ColumnTable(len(sheet_columns.FIELDS), 3)
        self.column_table.setObjectName('sheetColumnTable')
        self.column_table.setHorizontalHeaderLabels(['同步数据', '所在列', '说明'])
        self.column_table.verticalHeader().setVisible(False)
        self.column_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.column_table.setSelectionMode(QTableWidget.NoSelection)
        self.column_table.setMinimumHeight(420)
        header = self.column_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        self.column_table.setColumnWidth(1, 168)
        self.column_table.verticalHeader().setDefaultSectionSize(40)
        choices = [('按表头', sheet_columns.CHOICE_HEADER), ('不使用', sheet_columns.CHOICE_UNUSED)]
        for index in range(sheet_columns.MAX_COLUMN + 1):
            choices.append((sheet_columns.index_to_letter(index) + ' 列', str(index)))
        # One model for every column picker. Nine copies of the same 54 entries made this page slow to build and restyle.
        self._column_choice_model = QStandardItemModel(self)
        for text, data in choices:
            item = QStandardItem(text)
            item.setData(data, Qt.UserRole)
            self._column_choice_model.appendRow(item)
        for row, (key, label, _header, field_note) in enumerate(sheet_columns.FIELDS):
            name = QTableWidgetItem(label)
            name.setFlags(name.flags() & ~Qt.ItemIsEditable)
            self.column_table.setItem(row, 0, name)
            combo = QComboBox()
            combo.setObjectName('sheetColumnCombo')
            combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(6)
            combo.setModel(self._column_choice_model)
            combo.currentIndexChanged.connect(lambda _index, field=key, box=combo: self._remember_column(field, box))
            self._column_boxes[key] = combo
            holder = QWidget()
            holder.setObjectName('sheetColumnCell')
            holder_row = QHBoxLayout(holder)
            holder_row.setContentsMargins(8, 4, 8, 4)
            holder_row.setSpacing(0)
            holder_row.addWidget(combo, 0, Qt.AlignVCenter)
            self.column_table.setCellWidget(row, 1, holder)
            detail = QTableWidgetItem(field_note)
            detail.setFlags(detail.flags() & ~Qt.ItemIsEditable)
            self.column_table.setItem(row, 2, detail)
            self.column_table.setRowHeight(row, 40)
        layout.addWidget(self.column_table)
        return box

    def _remember_column(self, key, box):
        if self._loading or self.template_radio.isChecked():
            return
        self._custom_choices[key] = str(box.currentData() or sheet_columns.template_choice(key))
        if hasattr(self, 'status'):
            self.status.setText('')

    def _apply_column_mode(self, _checked=False):
        custom = self.custom_radio.isChecked()
        choices = self._custom_choices if custom else {
            key: sheet_columns.template_choice(key) for key, *_rest in sheet_columns.FIELDS
        }
        for key, box in self._column_boxes.items():
            box.blockSignals(True)
            index = box.findData(choices.get(key, sheet_columns.template_choice(key)))
            box.setCurrentIndex(index if index >= 0 else 0)
            box.setEnabled(custom)
            box.blockSignals(False)
        if not self._loading:
            self.status.setText('')

    def _stored(self, pairs):
        """Read many settings at once. Tests replace get_setting, so that path stays one call per key."""
        if repo.get_setting is not _REAL_GET_SETTING:
            return [repo.get_setting(key, default) for key, default in pairs]
        from app.core.database import connect
        keys = [key for key, _default in pairs]
        with connect() as con:
            rows = con.execute(
                f"SELECT key, value FROM app_settings WHERE key IN ({','.join('?' * len(keys))})",
                keys,
            ).fetchall()
        found = {row['key']: row['value'] for row in rows}
        return [found[key] if key in found else default for key, default in pairs]

    def _settings_snapshot(self):
        creator = repo.default_creator() or str(self.settings.value('creator', ''))
        code = str(self.settings.value('default_code', 'ZB'))
        wrap = str(self.settings.value('default_wrap', '18'))
        edit_fallback = str(self.settings.value('edit_root_path', ''))
        (
            task_sheet, task_asset_root, segment_output_root, drive_upload_root_url,
            google_oauth_client_path, drive_desktop_path, drive_desktop_folder, edit_root,
            davinci_executable, saved_fps, saved_lang,
        ) = self._stored((
            ('task_source_sheet_url', ''),
            ('task_asset_root', ''),
            ('segment_output_root', ''),
            ('drive_upload_root_url', ''),
            ('google_oauth_client_path', ''),
            ('drive_desktop_path', ''),
            ('drive_desktop_folder', 'FlowStudio'),
            ('edit_root_path', edit_fallback),
            ('davinci_executable_path', ''),
            ('timeline_fps', '25'),
            ('whisper_language', '斯瓦西里语 (Swahili) · sw'),
        ))
        spec = sheet_columns.load_spec()
        columns = tuple(
            (key, spec['columns'].get(key, sheet_columns.template_choice(key)))
            for key, _label, _header, _note in sheet_columns.FIELDS
        )
        return (
            creator,
            code,
            wrap,
            task_sheet,
            task_asset_root,
            segment_output_root,
            drive_upload_root_url,
            google_oauth_client_path,
            drive_desktop_path,
            drive_desktop_folder or 'FlowStudio',
            edit_root,
            davinci_executable,
            saved_fps or '25',
            saved_lang,
            spec['mode'],
            columns,
        )

    def reload(self):
        snapshot = self._settings_snapshot()
        # Opening the page again must not rebuild every field and column picker.
        if snapshot == getattr(self, '_source_snapshot', None):
            return
        (
            creator, code, wrap, task_sheet, task_asset_root, segment_output_root,
            drive_upload_root_url, google_oauth_client_path, drive_desktop_path,
            drive_desktop_folder, edit_root, davinci_executable, saved_fps, saved_lang,
            mode, columns,
        ) = snapshot
        self._loading = True
        try:
            self._set_line(self.creator, creator)
            self._set_line(self.default_code, code)
            self._set_line(self.default_wrap, wrap)
            self._set_line(self.task_sheet, task_sheet)
            self._set_line(self.task_asset_root, task_asset_root)
            self._set_line(self.segment_output_root, segment_output_root)
            self._set_line(self.drive_upload_root_url, drive_upload_root_url)
            self._set_line(self.google_oauth_client_path, google_oauth_client_path)
            self._set_line(self.drive_desktop_path, drive_desktop_path)
            self._set_line(self.drive_desktop_folder, drive_desktop_folder)
            self._set_line(self.edit_root, edit_root)
            self._set_line(self.davinci_executable, davinci_executable)
            if self.timeline_fps.currentText() != saved_fps:
                self.timeline_fps.setCurrentText(saved_fps)
            language_index = self.whisper_language.findText(saved_lang)
            if language_index >= 0:
                if self.whisper_language.currentIndex() != language_index:
                    self.whisper_language.setCurrentIndex(language_index)
            elif self.whisper_language.currentText() != '斯瓦西里语 (Swahili) · sw':
                self.whisper_language.setCurrentText('斯瓦西里语 (Swahili) · sw')
            self._custom_choices = dict(columns)
            custom = mode == sheet_columns.MODE_CUSTOM
            self.template_radio.setChecked(not custom)
            self.custom_radio.setChecked(custom)
            self._apply_column_mode()
            self._source_snapshot = snapshot
        finally:
            self._loading = False

    @staticmethod
    def _set_line(widget, value):
        if widget.text() != value:
            widget.setText(value)

    def pick_folder_into(self, line_edit, title):
        start = line_edit.text().strip() or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, title, start)
        if path:
            line_edit.setText(path)

    def pick_oauth_json(self):
        current = self.google_oauth_client_path.text().strip()
        start = str(Path(current).expanduser().parent) if current else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, '选择 Google OAuth Desktop Client JSON', start, 'JSON 文件 (*.json)')
        if path:
            self.google_oauth_client_path.setText(path)

    def pick_edit_root(self):
        start = self.edit_root.text().strip() or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, '选择 DaVinci 剪辑路径根目录', start)
        if path:
            self.edit_root.setText(path)

    def pick_resolve(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择达芬奇程序', self.davinci_executable.text(), 'Resolve (Resolve.exe)')
        if path:
            self.davinci_executable.setText(path)

    def _validate(self):
        wrap = self.default_wrap.text().strip()
        if wrap and (not wrap.isdigit() or int(wrap) <= 0):
            QMessageBox.warning(self, '设置错误', '默认断行字符数必须是大于 0 的整数。')
            return False
        for label, value in (
            ('任务素材根目录', self.task_asset_root.text().strip()),
            ('成品片段根目录', self.segment_output_root.text().strip()),
            ('剪辑路径', self.edit_root.text().strip()),
        ):
            if value:
                try:
                    Path(value).expanduser().mkdir(parents=True, exist_ok=True)
                except Exception as exc:
                    QMessageBox.warning(self, label, f'无法创建/写入目录：{exc}')
                    return False
        oauth = self.google_oauth_client_path.text().strip()
        if oauth and not Path(oauth).expanduser().exists():
            QMessageBox.warning(self, 'Google OAuth', '选择的 OAuth JSON 文件不存在。')
            return False
        if oauth:
            from app.services.google_oauth_config import load_desktop_config
            try:
                load_desktop_config(oauth)
            except ValueError as exc:
                QMessageBox.warning(self, 'Google 授权文件类型错误', str(exc))
                return False
        return True

    def validate_and_save(self):
        if self._loading or not self._validate():
            return
        if self.custom_radio.isChecked():
            for key in sheet_columns.REQUIRED_CUSTOM:
                choice = str(self._custom_choices.get(key) or sheet_columns.CHOICE_UNUSED)
                if choice == sheet_columns.CHOICE_UNUSED:
                    QMessageBox.warning(self, '表格列', f'{sheet_columns.FIELD_LABELS[key]}需要选择一列，或选择按表头。')
                    return
            problems = sheet_columns.duplicate_columns(self._custom_choices)
            if problems:
                QMessageBox.warning(self, '表格列', '这几项选了同一列：\n' + '\n'.join(problems))
                return
        self.save()
        self.status.setText('已保存。任务中心下次同步会使用这里的表格列。')

    def save(self):
        repo.set_setting('davinci_executable_path', self.davinci_executable.text().strip())
        creator = self.creator.text().strip()
        self.settings.setValue('creator', creator)
        repo.set_default_creator(creator)
        repo.set_setting('task_source_sheet_url', self.task_sheet.text().strip())
        repo.set_setting('task_asset_root', self.task_asset_root.text().strip())
        repo.set_setting('segment_output_root', self.segment_output_root.text().strip())
        repo.set_setting('flow_download_root', self.segment_output_root.text().strip())
        repo.set_setting('drive_upload_root_url', self.drive_upload_root_url.text().strip())
        repo.set_setting('google_oauth_client_path', self.google_oauth_client_path.text().strip())
        repo.set_setting('timeline_fps', self.timeline_fps.currentText())
        repo.set_setting('whisper_language', self.whisper_language.currentText())
        repo.set_setting('drive_desktop_path', self.drive_desktop_path.text().strip())
        repo.set_setting('drive_desktop_folder', self.drive_desktop_folder.text().strip() or 'FlowStudio')
        self.settings.setValue('default_code', self.default_code.text().strip() or 'ZB')
        repo.set_setting('default_code', self.default_code.text().strip() or 'ZB')
        wrap_value = self.default_wrap.text().strip() or '18'
        self.settings.setValue('default_wrap', wrap_value)
        repo.set_setting('default_wrap', wrap_value)
        root = self.edit_root.text().strip()
        self.settings.setValue('edit_root_path', root)
        repo.set_setting('edit_root_path', root)
        mode = sheet_columns.MODE_CUSTOM if self.custom_radio.isChecked() else sheet_columns.MODE_TEMPLATE
        sheet_columns.save_spec(mode, self._custom_choices)
        if root:
            try:
                from app.services.davinci_workflow import ensure_root_layout
                ensure_root_layout(Path(root))
            except Exception:
                pass
        self._source_snapshot = self._settings_snapshot()
