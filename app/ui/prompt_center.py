
from __future__ import annotations
from pathlib import Path
import copy
import uuid

from PySide6.QtCore import Qt, QThread, Signal, QSize, QRect, QPoint, QTimer
from PySide6.QtGui import QPixmap, QIcon
from app.ui.image_preview import set_image, load_pixmap
from app.ui.confirmation import confirm_clear
from app.services.image_assets import resolve_path, ImageAssetError
from PySide6.QtWidgets import (
    QInputDialog, QLayout, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QDialog, QDialogButtonBox, QFormLayout, QPlainTextEdit, QLineEdit, QMessageBox, QProgressBar, QSplitter, QFrame, QCheckBox, QListWidget, QListWidgetItem, QGroupBox, QApplication, QButtonGroup, QTabWidget, QScrollArea, QGridLayout, QSizePolicy
)

from app.core import repository as repo
from app.core import work_dates
from app.core.default_prompt import DEFAULT_CORE_PROMPT
from app.core.persona import (CAMERA_DEFINITIONS, PERFORMANCE, ACTIONS, normalize, active_camera_pool, active_action_presets, rule_text,
    load_preset_library, save_preset_library, normalize_library, preset_names, preset_prompt,
    save_persona_default, load_persona_default,
    save_preset_library_default, load_preset_library_default)
from app.services import openai_service
from app.ui.task_controls import CleanComboBox, CheckCell, GenerationModeToggle


class CameraChipLayout(QLayout):
    """Wrap the shared camera buttons to the available editor width."""
    def __init__(self, parent=None):
        super().__init__(parent); self.items=[]; self.setSpacing(6)
    def addItem(self, item): self.items.append(item)
    def count(self): return len(self.items)
    def itemAt(self, index): return self.items[index] if 0<=index<len(self.items) else None
    def takeAt(self, index): return self.items.pop(index) if 0<=index<len(self.items) else None
    def expandingDirections(self): return Qt.Orientations(0)
    def hasHeightForWidth(self): return True
    def heightForWidth(self, width): return self._arrange(QRect(0,0,width,0),True)
    def setGeometry(self, rect): super().setGeometry(rect); self._arrange(rect,False)
    def sizeHint(self): return self.minimumSize()
    def minimumSize(self):
        size=QSize()
        for item in self.items: size=size.expandedTo(item.minimumSize())
        margins=self.contentsMargins()
        return size+QSize(margins.left()+margins.right(),margins.top()+margins.bottom())
    def _arrange(self, rect, test):
        margins=self.contentsMargins(); area=rect.adjusted(margins.left(),margins.top(),-margins.right(),-margins.bottom())
        x=area.x(); y=area.y(); height=0
        for item in self.items:
            size=item.sizeHint()
            if x+size.width()>area.right()+1 and height:
                x=area.x(); y+=height+self.spacing(); height=0
            if not test: item.setGeometry(QRect(QPoint(x,y),size))
            x+=size.width()+self.spacing(); height=max(height,size.height())
        return y+height-rect.y()+margins.bottom()


def resolve_anchor_thumbnail(host_id):
    for candidate in repo.anchor_thumbnail_candidates(host_id):
        if candidate and not load_pixmap(candidate).isNull():
            return str(candidate)
    return ''


class APISettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI 设置")
        self.resize(760, 720)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.model = QComboBox()
        self.model.addItems(["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"])
        saved_model = repo.get_setting("openai_model", "gpt-5.6-luna")
        idx = self.model.findText(saved_model)
        if idx >= 0:
            self.model.setCurrentIndex(idx)

        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.Password)
        self.api_key.setPlaceholderText(
            "已保存到系统凭据库"
            if openai_service.get_api_key()
            else "粘贴 OpenAI API Key"
        )

        self.image_detail = QComboBox()
        self.image_detail.addItem("低成本（推荐）", "low")
        self.image_detail.addItem("自动", "auto")
        self.image_detail.addItem("高细节", "high")
        saved_detail = repo.get_setting("image_detail", "low")
        detail_index = self.image_detail.findData(saved_detail)
        if detail_index >= 0:
            self.image_detail.setCurrentIndex(detail_index)

        form.addRow("默认模型", self.model)
        form.addRow("图像理解精度", self.image_detail)
        form.addRow("OpenAI API Key", self.api_key)
        from app.ui.credential_pool_dialog import edit_pool
        bulk_keys = QPushButton('批量密钥 / 轮询设置')
        bulk_keys.clicked.connect(lambda: edit_pool(self, openai_service.KEYCHAIN_SERVICE, openai_service.KEYCHAIN_ACCOUNT))
        form.addRow('', bulk_keys)
        layout.addLayout(form)

        core_title = QLabel("Flow 提示词核心规则")
        core_title.setStyleSheet("font-weight:700;")
        layout.addWidget(core_title)

        hint = QLabel(
            "这里保存的是全局底层规则。平时自动使用，以后可直接修改。"
            "图像理解精度默认“低成本”：更省输入 tokens、通常也更快；"
            "遇到需要识别细小表情/眼睛状态的图片，可改为“自动”或“高细节”。",
            objectName="muted"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.core_prompt = QPlainTextEdit()
        self.core_prompt.setMinimumHeight(220)
        self.core_prompt.setPlaceholderText("填写全局 Flow 提示词核心规则…")
        self.core_prompt.setPlainText(
            repo.get_setting("core_prompt", DEFAULT_CORE_PROMPT) or DEFAULT_CORE_PROMPT
        )
        layout.addWidget(self.core_prompt, 1)

        reset_core = QPushButton("恢复默认核心规则")
        reset_core.clicked.connect(
            lambda: self.core_prompt.setPlainText(DEFAULT_CORE_PROMPT)
        )
        layout.addWidget(reset_core)

        price = QLabel(
            "当前计费（每百万文本 tokens）：\n"
            "Luna：输入 $0.20 · 缓存输入 $0.02 · 输出 $1.20\n"
            "Terra：输入 $2.00 · 缓存输入 $0.20 · 输出 $12.00\n"
            "Sol：输入 $4.00 · 缓存输入 $0.40 · 输出 $20.00",
            objectName="muted"
        )
        price.setWordWrap(True)
        layout.addWidget(price)

        row = QHBoxLayout()
        remove_key = QPushButton("删除钥匙串 API Key")
        remove_key.clicked.connect(self.remove_key)
        row.addWidget(remove_key)
        row.addStretch(1)
        layout.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def remove_key(self):
        openai_service.delete_api_key()
        self.api_key.clear()
        self.api_key.setPlaceholderText("未保存 API Key")
        QMessageBox.information(self, "API Key", "已从系统凭据库删除全部密钥。")

    def save(self):
        if self.api_key.text().strip():
            try:
                openai_service.save_api_key_to_keychain(self.api_key.text().strip())
            except Exception as exc:
                QMessageBox.critical(self, "保存失败", str(exc))
                return

        repo.set_setting("openai_model", self.model.currentText())
        repo.set_setting("image_detail", self.image_detail.currentData() or "low")

        core_text = self.core_prompt.toPlainText().strip()
        repo.set_setting("core_prompt", core_text or DEFAULT_CORE_PROMPT)
        self.accept()




class PersonaPresetItemDialog(QDialog):
    """Edit one button's visible label and the instruction sent to GPT."""
    def __init__(self, section, item=None, parent=None):
        super().__init__(parent)
        self.section = section
        self.original = copy.deepcopy(item or {})
        labels = {
            'performance': '表演风格预设',
            'actions': '人物动作预设',
            'camera_shots': '镜头预设',
        }
        self.setWindowTitle(('编辑' if item else '新增') + labels.get(section, '预设'))
        self.resize(560, 360)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit(str(self.original.get('name') or ''))
        self.name_edit.setPlaceholderText('按钮上显示的文字')
        form.addRow('按钮文字', self.name_edit)
        root.addLayout(form)

        hint = QLabel('下面内容是实际发送给 GPT 的默认要求；按钮文字可以短一些，提示内容可以写得更完整。', objectName='muted')
        hint.setWordWrap(True)
        root.addWidget(hint)
        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setPlaceholderText('填写这个预设实际发送给 GPT 的要求……')
        self.prompt_edit.setPlainText(str(self.original.get('prompt') or self.original.get('name') or ''))
        root.addWidget(self.prompt_edit, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.result_item = None

    def _save(self):
        name = self.name_edit.text().strip()
        prompt = self.prompt_edit.toPlainText().strip()
        if not name:
            QMessageBox.warning(self, '无法保存', '按钮文字不能为空。')
            return
        if name == '自定义':
            QMessageBox.warning(self, '无法保存', '“自定义”是系统保留按钮，请换一个名称。')
            return
        if not prompt:
            QMessageBox.warning(self, '无法保存', 'GPT 提示内容不能为空。')
            return
        aliases = list(self.original.get('aliases') or [])
        old_name = str(self.original.get('name') or '').strip()
        if old_name and old_name != name and old_name not in aliases:
            aliases.append(old_name)
        self.result_item = {
            'id': str(self.original.get('id') or f'{self.section}_{uuid.uuid4().hex}'),
            'name': name,
            'prompt': prompt,
            'aliases': aliases,
        }
        self.accept()


class PersonaCameraStrategyDialog(QDialog):
    """Edit one camera strategy with the same multi-select chip UI as the camera pool."""
    def __init__(self, shots, item=None, parent=None):
        super().__init__(parent)
        self.shots = copy.deepcopy(shots)
        self.original = copy.deepcopy(item or {})
        self.setWindowTitle(('编辑' if item else '新增') + '镜头调度策略')
        self.resize(640, 520)
        root = QVBoxLayout(self)

        form = QFormLayout()
        self.name_edit = QLineEdit(str(self.original.get('name') or ''))
        self.name_edit.setPlaceholderText('例如：稳重讲述 / 轻微动态 / 新闻采访')
        form.addRow('按钮文字', self.name_edit)
        root.addLayout(form)

        root.addWidget(QLabel('策略内部规则（发送给 GPT）', objectName='cardTitle'))
        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setPlaceholderText('例如：优先根据人物动作匹配镜头，不为变化而变化；每段只选1种主运镜，必要时最多1次 hard cut。')
        self.prompt_edit.setPlainText(str(self.original.get('prompt') or ''))
        self.prompt_edit.setMaximumHeight(110)
        root.addWidget(self.prompt_edit)

        tip = QLabel('点击镜头按钮即可多选。绿色文字 = 当前策略允许 GPT 使用；再次点击即可取消。', objectName='muted')
        tip.setWordWrap(True)
        root.addWidget(tip)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        chip_host = QWidget()
        chip_layout = CameraChipLayout(chip_host)
        chip_layout.setContentsMargins(2, 2, 2, 2)
        self.shot_buttons = []
        selected = set(self.original.get('shot_ids') or [])
        for shot in self.shots:
            button = QPushButton(shot['name'], objectName='personaPoolChip')
            button.setCheckable(True)
            button.setChecked(shot['id'] in selected)
            button.setProperty('shot_id', shot['id'])
            button.toggled.connect(self._update_selected_count)
            chip_layout.addWidget(button)
            self.shot_buttons.append(button)
        scroll.setWidget(chip_host)
        root.addWidget(scroll, 1)

        self.selected_label = QLabel('', objectName='muted')
        root.addWidget(self.selected_label)
        self._update_selected_count()

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.result_item = None

    def _update_selected_count(self, *_):
        count = sum(1 for button in self.shot_buttons if button.isChecked())
        self.selected_label.setText(f'已选择 {count} 个镜头 · 支持多选')

    def _save(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, '无法保存', '按钮文字不能为空。')
            return
        if name == '自定义':
            QMessageBox.warning(self, '无法保存', '“自定义”是系统保留按钮，请换一个名称。')
            return
        shot_ids = [str(button.property('shot_id')) for button in self.shot_buttons if button.isChecked()]
        if not shot_ids:
            QMessageBox.warning(self, '无法保存', '镜头调度策略至少要包含一个镜头预设。')
            return
        aliases = list(self.original.get('aliases') or [])
        old_name = str(self.original.get('name') or '').strip()
        if old_name and old_name != name and old_name not in aliases:
            aliases.append(old_name)
        self.result_item = {
            'id': str(self.original.get('id') or f'strategy_{uuid.uuid4().hex}'),
            'name': name,
            'shot_ids': shot_ids,
            'prompt': self.prompt_edit.toPlainText().strip(),
            'aliases': aliases,
        }
        self.accept()


class PersonaPresetLibraryDialog(QDialog):
    """Global persistent button library for the persona editor."""
    SECTIONS = (
        ('performance', '表演风格'),
        ('actions', '人物动作'),
        ('camera_shots', '镜头预设'),
        ('camera_strategies', '镜头调度策略'),
    )

    def __init__(self, parent=None, start_section='camera_shots', mode='TALKING'):
        super().__init__(parent)
        self.mode = 'PRAYING' if str(mode or '').upper() == 'PRAYING' else 'TALKING'
        mode_label = '闭眼祷告' if self.mode == 'PRAYING' else '睁眼说话'
        self.setWindowTitle(f'人物设置 · {mode_label} · 自定义预设库')
        self.setObjectName('personaPresetDialog')
        self.resize(760, 620)
        self.library = copy.deepcopy(load_preset_library(self.mode))
        self.lists = {}

        root = QVBoxLayout(self)
        head = QLabel('完全自定义人物设置按钮', objectName='pageTitle')
        root.addWidget(head)
        tip = QLabel(
            f'当前正在编辑【{mode_label}】独立预设库：可以新增、改名、修改实际 GPT 内容、删除和排序。'
            f'这里只影响 {self.mode}，不会修改另一种模式；保存后永久保留，并应用到所有主播的当前模式。',
            objectName='muted'
        )
        tip.setWordWrap(True)
        root.addWidget(tip)

        self.tabs = QTabWidget(objectName='presetLibraryTabs')
        root.addWidget(self.tabs, 1)
        for section, label in self.SECTIONS:
            page = QWidget(objectName='personaTabPage')
            pv = QVBoxLayout(page)
            lst = QListWidget()
            lst.setAlternatingRowColors(False)
            lst.itemDoubleClicked.connect(lambda _item, s=section: self._edit(s))
            pv.addWidget(lst, 1)
            self.lists[section] = lst

            row = QHBoxLayout()
            add = QPushButton('＋ 新增', objectName='softBtn')
            edit = QPushButton('✎ 编辑', objectName='softBtn')
            delete = QPushButton('删除', objectName='softBtn')
            up = QPushButton('↑ 上移', objectName='softBtn')
            down = QPushButton('↓ 下移', objectName='softBtn')
            add.clicked.connect(lambda _=False, s=section: self._add(s))
            edit.clicked.connect(lambda _=False, s=section: self._edit(s))
            delete.clicked.connect(lambda _=False, s=section: self._delete(s))
            up.clicked.connect(lambda _=False, s=section: self._move(s, -1))
            down.clicked.connect(lambda _=False, s=section: self._move(s, 1))
            for b in (add, edit, delete, up, down):
                row.addWidget(b)
            row.addStretch(1)
            pv.addLayout(row)
            self.tabs.addTab(page, label)
            self._refresh(section)

        index = next((i for i, x in enumerate(self.SECTIONS) if x[0] == start_section), 0)
        self.tabs.setCurrentIndex(index)

        bottom = QHBoxLayout()
        self.set_library_default_btn = QPushButton('★ 设为默认', objectName='softBtn')
        self.set_library_default_btn.setToolTip(
            '把当前模式整套自定义预设库保存成恢复点。以后误改后可用“恢复默认预设库”一键恢复。'
        )
        self.set_library_default_btn.clicked.connect(self._set_library_default)
        bottom.addWidget(self.set_library_default_btn)
        reset = QPushButton('↻ 恢复默认预设库', objectName='softBtn')
        reset.setToolTip('恢复到最后一次“设为默认”保存的整套预设库；若从未设置，则恢复软件出厂默认。')
        reset.clicked.connect(self._reset_all)
        bottom.addWidget(reset)
        bottom.addStretch(1)
        cancel = QPushButton('取消', objectName='softBtn')
        save = QPushButton('保存预设库', objectName='primaryBtn')
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self._save_all)
        bottom.addWidget(cancel)
        bottom.addWidget(save)
        root.addLayout(bottom)

    def _items(self, section):
        return self.library.get(section, [])

    def _refresh(self, section, select_row=None):
        lst = self.lists[section]
        current = lst.currentRow() if select_row is None else select_row
        lst.clear()
        for item in self._items(section):
            if section == 'camera_strategies':
                count = len(item.get('shot_ids') or [])
                text = f"{item['name']}    · {count} 个镜头"
            else:
                prompt = str(item.get('prompt') or '').replace('\n', ' ')
                if len(prompt) > 54:
                    prompt = prompt[:54] + '…'
                text = f"{item['name']}    · {prompt}"
            row = QListWidgetItem(text)
            row.setData(Qt.UserRole, item['id'])
            lst.addItem(row)
        if lst.count():
            lst.setCurrentRow(max(0, min(current, lst.count()-1)))

    def _selected_index(self, section):
        row = self.lists[section].currentRow()
        if row < 0 and self._items(section):
            row = 0
        return row

    def _name_conflicts(self, section, name, ignore_id=None):
        name = str(name or '').strip()
        return any(x['name'] == name and x.get('id') != ignore_id for x in self._items(section))

    def _add(self, section):
        if section == 'camera_strategies':
            dlg = PersonaCameraStrategyDialog(self.library['camera_shots'], parent=self)
        else:
            dlg = PersonaPresetItemDialog(section, parent=self)
        if not dlg.exec():
            return
        item = dlg.result_item
        if self._name_conflicts(section, item['name']):
            QMessageBox.warning(self, '名称重复', '同一类预设里不能存在两个同名按钮。')
            return
        self._items(section).append(item)
        self._refresh(section, len(self._items(section))-1)
        self._library_changed()

    def _edit(self, section):
        row = self._selected_index(section)
        if row < 0:
            return
        old = self._items(section)[row]
        if section == 'camera_strategies':
            dlg = PersonaCameraStrategyDialog(self.library['camera_shots'], old, self)
        else:
            dlg = PersonaPresetItemDialog(section, old, self)
        if not dlg.exec():
            return
        item = dlg.result_item
        if self._name_conflicts(section, item['name'], old.get('id')):
            QMessageBox.warning(self, '名称重复', '同一类预设里不能存在两个同名按钮。')
            return
        self._items(section)[row] = item
        self._refresh(section, row)
        self._library_changed()

    def _delete(self, section):
        items = self._items(section)
        row = self._selected_index(section)
        if row < 0:
            return
        if len(items) <= 1:
            QMessageBox.warning(self, '不能删除', '每一类至少保留一个预设。')
            return
        name = items[row]['name']
        if QMessageBox.question(
            self, '删除预设', f'确定删除“{name}”吗？\n已有主播使用这个预设时会自动迁移到可用设置。'
        ) != QMessageBox.Yes:
            return
        removed = items.pop(row)
        if section == 'camera_shots':
            rid = removed['id']
            fallback = self.library['camera_shots'][0]['id']
            for strategy in self.library['camera_strategies']:
                strategy['shot_ids'] = [x for x in strategy.get('shot_ids', []) if x != rid]
                if not strategy['shot_ids']:
                    strategy['shot_ids'] = [fallback]
            self._refresh('camera_strategies')
        self._refresh(section, min(row, len(items)-1))
        self._library_changed()

    def _move(self, section, delta):
        items = self._items(section)
        row = self._selected_index(section)
        target = row + delta
        if row < 0 or target < 0 or target >= len(items):
            return
        items[row], items[target] = items[target], items[row]
        self._refresh(section, target)
        self._library_changed()

    def _library_changed(self):
        """Clear the success state when the in-dialog library changes again."""
        if not getattr(self, '_library_default_feedback', False):
            return
        self._library_default_feedback = False
        if hasattr(self, 'set_library_default_btn'):
            self.set_library_default_btn.setText('★ 设为默认')
            self.set_library_default_btn.setProperty('successState', False)
            self.set_library_default_btn.style().unpolish(self.set_library_default_btn)
            self.set_library_default_btn.style().polish(self.set_library_default_btn)

    def _set_library_default(self):
        # “设为默认” means the library currently visible in this dialog becomes
        # both the active GPT library and the restore baseline.  Previously this
        # only saved the restore snapshot, so closing the dialog without pressing
        # “保存预设库” could leave GPT using stale action/camera prompts.
        self.library = normalize_library(self.library)
        self.library = save_preset_library(self.library, self.mode)
        save_preset_library_default(self.library, self.mode)
        self._library_default_feedback = True
        self.set_library_default_btn.setText('✓ 已设为默认')
        self.set_library_default_btn.setProperty('successState', True)
        self.set_library_default_btn.style().unpolish(self.set_library_default_btn)
        self.set_library_default_btn.style().polish(self.set_library_default_btn)

    def _reset_all(self):
        if QMessageBox.question(
            self, '恢复默认',
            f'确定恢复 {self.mode} 的默认预设库吗？\n'
            '将恢复到最后一次点击“设为默认”保存的整套内容；若从未设置则使用软件出厂默认。\n'
            '只会替换当前模式，不影响另一种模式。'
        ) != QMessageBox.Yes:
            return
        self.library = copy.deepcopy(load_preset_library_default(self.mode))
        for section, _ in self.SECTIONS:
            self._refresh(section, 0)
        self._library_changed()

    def _save_all(self):
        # normalize_library also performs structural safety checks/fallbacks.
        self.library = normalize_library(self.library)
        save_preset_library(self.library, self.mode)
        self.accept()



class GenerationRulesDialog(QDialog):
    """Host persona editor backed by a fully editable persistent global preset library."""
    PRESETS_CHANGED = 2

    def __init__(self, host_id, parent=None, initial_data=None):
        super().__init__(parent)
        self.host_id = int(host_id)
        self.initial_data = copy.deepcopy(initial_data or {})
        self.pending_persona = None
        self.host = repo.get_host_with_recipient(host_id)
        self.libraries = {m: load_preset_library(m) for m in ('TALKING','PRAYING')}
        self.setWindowTitle(f'{self.host["name"]} · 人物提示词设置')
        self.setObjectName('personaDialog')
        self.resize(1120, 800)
        self.setMinimumSize(820, 640)
        self.mode_controls = {}

        outer=QVBoxLayout(self); outer.setContentsMargins(0,0,0,0); outer.setSpacing(0)
        scroll=QScrollArea(objectName='personaScroll'); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded); scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        content=QWidget(objectName='personaContent'); content.setMinimumWidth(780); root=QVBoxLayout(content); root.setContentsMargins(22,18,22,18); root.setSpacing(12)
        scroll.setWidget(content); outer.addWidget(scroll)

        head=QHBoxLayout(); title=QLabel(f'{self.host["name"]} · 人物提示词设置'); title.setStyleSheet('font-size:22px;font-weight:800;'); head.addWidget(title)
        self.badge=QLabel('已保存' if all(repo.get_setting(self._key(m),'') for m in ('TALKING','PRAYING')) else '尚未保存', objectName='muted'); head.addWidget(self.badge); head.addStretch(1)
        manage_all=QPushButton('⚙ 管理当前模式预设',objectName='softBtn'); manage_all.clicked.connect(lambda:self._edit_presets('camera_shots', self._current_mode())); head.addWidget(manage_all)
        root.addLayout(head)
        tip=QLabel('TALKING 与 PRAYING 使用两套完全独立的预设库。当前标签页只显示和编辑当前模式；两边可分别新增、改名、修改、删除、排序并永久保存。',objectName='muted'); tip.setWordWrap(True); root.addWidget(tip)

        body=QSplitter(Qt.Horizontal); body.setChildrenCollapsible(False); body.setHandleWidth(6)
        left=QFrame(objectName='pageCard'); lv=QVBoxLayout(left); lv.setContentsMargins(14,14,14,14); lv.setSpacing(8)
        img=QLabel(objectName='hostThumb'); img.setAlignment(Qt.AlignCenter); img.setMinimumSize(170,170); img.setMaximumHeight(220)
        set_image(img, resolve_anchor_thumbnail(self.host_id)); lv.addWidget(img)
        lv.addWidget(QLabel(str(self.host['name'] or '未命名主播'),objectName='pageTitle'))
        rec_name=str(self.host['recipient_name'] or '') if self.host and 'recipient_name' in self.host.keys() else ''
        lv.addWidget(QLabel(rec_name,objectName='cardMeta'))
        try: total=len(list(repo.list_prompt_tasks(self.host['recipient_id'],self.host_id,'全部', work_date=work_dates.active())))
        except Exception: total=0
        lv.addWidget(QLabel(f'{total} 条文案',objectName='cardMeta')); lv.addSpacing(6)
        for mode in ('TALKING','PRAYING'):
            lv.addWidget(QLabel(mode+(' · 已保存' if repo.get_setting(self._key(mode),'') else ' · 默认设置'),objectName='cardMeta'))
        lv.addStretch(1); body.addWidget(left)

        middle=QFrame(objectName='pageCard'); mv=QVBoxLayout(middle); mv.setContentsMargins(12,12,12,12); mv.setSpacing(8)
        self.tabs=QTabWidget(objectName='personaTabs'); mv.addWidget(self.tabs,1)
        for mode,label in (("TALKING","TALKING · 睁眼说话"),("PRAYING","PRAYING · 闭眼祷告")):
            lib=self.libraries[mode]
            page=QWidget(objectName='personaTabPage'); pv=QVBoxLayout(page); pv.setContentsMargins(10,10,10,10); pv.setSpacing(12); controls={}

            row_title=QHBoxLayout(); row_title.addWidget(QLabel('1. 表演风格',objectName='cardTitle')); row_title.addStretch(1)
            edit=QPushButton('✎ 编辑预设',objectName='softBtn'); edit.clicked.connect(lambda _=False,m=mode:self._edit_presets('performance',m)); row_title.addWidget(edit); pv.addLayout(row_title)
            style_group=QButtonGroup(page); style_group.setExclusive(True); style_grid=QGridLayout(); style_grid.setSpacing(6)
            for i,item in enumerate(lib['performance']):
                b=QPushButton(item['name'],objectName='chipBtn'); b.setCheckable(True); b.setProperty('preset_id',item['id']); style_group.addButton(b); style_grid.addWidget(b,i//4,i%4)
            custom_style=QPushButton('自定义',objectName='chipBtn'); custom_style.setCheckable(True); custom_style.setProperty('preset_id','custom'); style_group.addButton(custom_style); i=len(lib['performance']); style_grid.addWidget(custom_style,i//4,i%4)
            pv.addLayout(style_grid); controls['style_group']=style_group; controls['style_buttons']=style_group.buttons(); controls['custom_style']=custom_style; controls['style_grid']=style_grid
            pv.addWidget(QLabel('当前主播专属要求（修改按钮名称/全局默认内容请点“编辑预设”）',objectName='muted'))
            performance_edit=QPlainTextEdit(); performance_edit.setMaximumHeight(85); performance_edit.setPlaceholderText('请输入这个主播的表演要求……'); pv.addWidget(performance_edit); controls['performance_edit']=performance_edit

            row_title=QHBoxLayout(); row_title.addWidget(QLabel('2. 人物动作',objectName='cardTitle')); row_title.addStretch(1)
            edit=QPushButton('✎ 编辑预设',objectName='softBtn'); edit.clicked.connect(lambda _=False,m=mode:self._edit_presets('actions',m)); row_title.addWidget(edit); pv.addLayout(row_title)
            auto_action_match=QCheckBox('根据参考图自动匹配已选动作预设（推荐）')
            auto_action_match.setToolTip('勾选后：下方多选动作作为候选池；GPT 在同一次图片请求里只识别一次参考图，并自动选择安全且合适的预设，不会把全部动作同时套上。')
            pv.addWidget(auto_action_match); controls['auto_action_match']=auto_action_match
            move_grid=QGridLayout(); move_grid.setSpacing(6); move_buttons=[]
            for i,item in enumerate(lib['actions']):
                b=QPushButton(item['name'],objectName='chipBtn'); b.setCheckable(True); b.setProperty('preset_id',item['id']); move_grid.addWidget(b,i//3,i%3); move_buttons.append(b)
            move_custom=QPushButton('自定义',objectName='chipBtn'); move_custom.setCheckable(True); move_custom.setProperty('preset_id','custom'); i=len(lib['actions']); move_grid.addWidget(move_custom,i//3,i%3); pv.addLayout(move_grid)
            controls['move_buttons']=move_buttons; controls['move_custom']=move_custom; controls['move_grid']=move_grid
            action_hint=QLabel('动作可多选。开启自动匹配后，这些按钮是候选池：GPT 会按参考图的坐/站、手部占用、拿物/做事状态自动选择合适预设；双手占用或不确定时优先安全动作。',objectName='muted'); action_hint.setWordWrap(True); pv.addWidget(action_hint)
            action_edit=QPlainTextEdit(); action_edit.setMaximumHeight(85); action_edit.setPlaceholderText('点击上方动作按钮后，在这里直接编辑当前动作内容……'); pv.addWidget(action_edit); controls['action_edit']=action_edit
            controls['editing_action']=''

            row_title=QHBoxLayout(); row_title.addWidget(QLabel('3. 镜头调度策略',objectName='cardTitle')); row_title.addStretch(1)
            edit=QPushButton('✎ 编辑镜头/策略',objectName='softBtn'); edit.clicked.connect(lambda _=False,m=mode:self._edit_presets('camera_shots',m)); row_title.addWidget(edit); pv.addLayout(row_title)
            cam_group=QButtonGroup(page); cam_group.setExclusive(True); cam_grid=QGridLayout(); cam_grid.setSpacing(7)
            for i,item in enumerate(lib['camera_strategies']):
                text=item['name'] + ('  推荐' if item['id']=='strategy_natural' else '')
                box=QPushButton(text,objectName='chipBtn'); box.setCheckable(True); box.setMinimumHeight(50); box.setProperty('preset_id',item['id']); cam_group.addButton(box); cam_grid.addWidget(box,i//3,i%3)
            custom_camera=QPushButton('自定义',objectName='chipBtn'); custom_camera.setCheckable(True); custom_camera.setMinimumHeight(50); custom_camera.setProperty('preset_id','custom'); cam_group.addButton(custom_camera); i=len(lib['camera_strategies']); cam_grid.addWidget(custom_camera,i//3,i%3)
            pv.addLayout(cam_grid); controls['camera_group']=cam_group; controls['custom_camera']=custom_camera; controls['cam_grid']=cam_grid
            pool_box=QWidget(); pool_layout=CameraChipLayout(pool_box); pool_layout.setContentsMargins(0,0,0,0); controls['pool_box']=pool_box; controls['pool_buttons']=[]
            for item in lib['camera_shots']:
                chip=QPushButton(item['name'],objectName='personaPoolChip'); chip.setCheckable(True); chip.setProperty('preset_id',item['id'])
                pool_layout.addWidget(chip); controls['pool_buttons'].append(chip)
            controls['pool_layout']=pool_layout
            pv.addWidget(pool_box)

            pv.addWidget(QLabel('4. 自定义总体要求',objectName='cardTitle'))
            custom=QPlainTextEdit(); custom.setPlaceholderText('例如：人物始终站在原地，表情亲和温柔，翅膀保持轻微动态……'); custom.setMaximumHeight(110); pv.addWidget(custom); controls['custom']=custom
            pv.addStretch(1); self.tabs.addTab(page,label); self.mode_controls[mode]=controls; self._load_mode(mode, self.initial_data.get(mode) if mode in self.initial_data else None)
        body.addWidget(middle)

        right=QFrame(objectName='detailPanel'); rv=QVBoxLayout(right); rv.setContentsMargins(12,12,12,12); rv.setSpacing(8)
        rv.addWidget(QLabel('镜头池预览',objectName='sectionTitle'))
        preview_tip=QLabel('绿色 = 当前策略允许 GPT 使用。镜头按钮和实际提示内容都可以在“编辑镜头/策略”里自定义。',objectName='muted'); preview_tip.setWordWrap(True); rv.addWidget(preview_tip)
        preview_scroll=QScrollArea(objectName='personaPreviewScroll'); preview_scroll.setWidgetResizable(True); preview_scroll.setFrameShape(QFrame.NoFrame)
        preview_content=QWidget(objectName='personaPreviewContent'); preview_v=QVBoxLayout(preview_content); preview_v.setContentsMargins(0,0,0,0); preview_v.setSpacing(5)
        self.preview_lines={}
        self.preview_v=preview_v
        preview_names=[]
        for m in ('TALKING','PRAYING'):
            for item in self.libraries[m]['camera_shots']:
                if item['name'] not in preview_names:
                    preview_names.append(item['name'])
        for name in preview_names:
            line=QLabel(name,objectName='personaPreviewLine'); line.setMinimumHeight(28); line.setWordWrap(True); preview_v.addWidget(line); self.preview_lines[name]=line
        preview_v.addStretch(1); preview_scroll.setWidget(preview_content); rv.addWidget(preview_scroll,1)
        self.tabs.currentChanged.connect(self._refresh_preview)
        self.tabs.currentChanged.connect(self._default_mode_tab_changed)
        self._refresh_preview()
        body.addWidget(right); body.setSizes([220,610,270]); root.addWidget(body,1)

        footer=QWidget(objectName='personaFooter'); foot=QHBoxLayout(footer); foot.setContentsMargins(22,10,22,14); self.set_default_btn=QPushButton('★ 设为预设',objectName='softBtn'); self.set_default_btn.setToolTip('把当前标签页的表演风格、人物动作、镜头调度策略、镜头池和自定义要求保存为该模式默认。'); self.set_default_btn.clicked.connect(self._set_current_mode_default); foot.addWidget(self.set_default_btn)
        reset=QPushButton('↻ 恢复当前主播默认设置',objectName='softBtn'); reset.clicked.connect(self._reset_defaults); foot.addWidget(reset); foot.addStretch(1)
        cancel=QPushButton('取消'); cancel.setStyleSheet('QPushButton{background:#E5484D;color:white;border:none;border-radius:10px;font-weight:650;}QPushButton:hover{background:#D63C41;}QPushButton:pressed{background:#C23439;}'); cancel.clicked.connect(self.reject); save=QPushButton('保存设置',objectName='primaryBtn'); save.clicked.connect(self.save_all)
        for _b in (cancel,save): _b.setFixedSize(104,38)
        foot.addWidget(cancel); foot.addWidget(save); outer.addWidget(footer)
        self._tab_pages=[self.tabs.widget(i) for i in range(self.tabs.count())]
        self.tabs.currentChanged.connect(self._shrink_tab_pages); self._shrink_tab_pages()

    def _shrink_tab_pages(self, *_):
        cur=self.tabs.currentIndex()
        for i,pg in enumerate(self._tab_pages):
            pol=QSizePolicy.Preferred if i==cur else QSizePolicy.Ignored
            pg.setSizePolicy(pol,pol)
        self.tabs.updateGeometry()

    def _key(self, mode): return f'host_persona_{self.host_id}_{mode.lower()}'

    def _load_mode(self, mode, data=None):
        import json
        c=self.mode_controls[mode]
        if data is None:
            try: data=json.loads(repo.get_setting(self._key(mode),'') or '{}')
            except (ValueError,TypeError): data={}
        lib=self.libraries[mode]
        c['data']=normalize(data,mode,lib)
        d=c['data']; c['loading']=True
        for b in c['style_buttons']: b.setChecked(b.text()==d['style'])
        if not any(b.isChecked() for b in c['style_buttons']): c['style_buttons'][-1].setChecked(True)
        c['auto_action_match'].setChecked(bool(d.get('auto_action_match', True)))
        for b in c['move_buttons']: b.setChecked(b.text() in d['moves'])
        c['move_custom'].setChecked('自定义' in d['moves'])
        for b in c['camera_group'].buttons(): b.setChecked(b.text().replace('  推荐','')==d['camera'])
        if not any(b.isChecked() for b in c['camera_group'].buttons()):
            first=next((b for b in c['camera_group'].buttons() if b.property('preset_id')=='strategy_natural'), c['camera_group'].buttons()[0])
            first.setChecked(True)
        for b in c['pool_buttons']: b.setChecked(b.text() in d['custom_camera_pool'])
        c['custom'].setPlainText(d['custom'])
        if not c.get('connected'):
            c['style_group'].buttonClicked.connect(lambda _,m=mode:self._style_changed(m))
            c['performance_edit'].textChanged.connect(lambda m=mode:self._edit_performance(m))
            c['action_edit'].textChanged.connect(lambda m=mode:self._edit_action(m))
            c['auto_action_match'].toggled.connect(lambda _=False,m=mode:self._changed(m))
            for b in c['move_buttons']+[c['move_custom']]:
                b.clicked.connect(lambda checked,m=mode,button=b:self._move_changed(m,button,checked))
            for b in c['camera_group'].buttons()+c['pool_buttons']:
                b.toggled.connect(lambda _,m=mode:self._changed(m))
            c['custom'].textChanged.connect(lambda m=mode:self._changed(m))
            c['connected']=True
        c['editing_action']=next((b.text() for b in c['move_buttons'] if b.isChecked()), '自定义' if c['move_custom'].isChecked() else '')
        self._style_changed(mode); self._action_changed(mode)
        c['loading']=False
        self._sync_visibility(mode)

    def _style_changed(self, mode):
        c=self.mode_controls[mode]; d=c['data']
        style=next((b.text() for b in c['style_buttons'] if b.isChecked()),'自定义')
        c['editing_style']=style
        text=d['performance_custom'] if style=='自定义' else d['performance_prompts'].get(style,preset_prompt('performance',style,self.libraries[mode],style))
        c['performance_edit'].blockSignals(True); c['performance_edit'].setPlainText(text); c['performance_edit'].blockSignals(False)
        self._changed(mode)

    def _edit_performance(self, mode):
        c=self.mode_controls[mode]; style=c['editing_style']; text=c['performance_edit'].toPlainText()
        if style=='自定义': c['data']['performance_custom']=text
        else: c['data']['performance_prompts'][style]=text
        self._changed(mode)

    def _action_changed(self, mode, button=None):
        c=self.mode_controls[mode]
        if button is not None:
            name = '自定义' if button is c['move_custom'] else button.text()
            c['editing_action'] = name
        name = c.get('editing_action') or ''
        if not name:
            selected = next((b.text() for b in c['move_buttons'] if b.isChecked()), None)
            name = selected or ('自定义' if c['move_custom'].isChecked() else (c['move_buttons'][0].text() if c['move_buttons'] else ''))
            c['editing_action'] = name
        if name == '自定义':
            text = c['data'].get('action_custom', '')
        else:
            default = preset_prompt('actions', name, self.libraries[mode], name)
            text = c['data']['action_prompts'].get(name, default)
        c['action_edit'].blockSignals(True)
        c['action_edit'].setPlainText(text)
        c['action_edit'].blockSignals(False)

    def _edit_action(self, mode):
        c=self.mode_controls[mode]
        name=c.get('editing_action') or ''
        if name == '自定义':
            c['data']['action_custom']=c['action_edit'].toPlainText()
        elif name:
            c['data']['action_prompts'][name]=c['action_edit'].toPlainText()
        self._changed(mode)

    def _move_changed(self, mode, button, checked):
        # Preserve the original useful exclusivity even if the user renames those default buttons.
        conflicts={'action_01':'action_03','action_03':'action_01','action_04':'action_05','action_05':'action_04'}
        if checked:
            conflict=conflicts.get(str(button.property('preset_id') or ''))
            if conflict:
                for b in self.mode_controls[mode]['move_buttons']:
                    if str(b.property('preset_id') or '')==conflict:
                        b.setChecked(False)
        # The last clicked action becomes the editor target, regardless of multi-select state.
        self._action_changed(mode, button)
        self._changed(mode)

    def _serialize(self, mode):
        c=self.mode_controls[mode]; d=dict(c['data'])
        d.update(
            style=next((b.text() for b in c['style_buttons'] if b.isChecked()),'自定义'),
            auto_action_match=bool(c['auto_action_match'].isChecked()),
            moves=[b.text() for b in c['move_buttons']+[c['move_custom']] if b.isChecked()],
            camera=next((b.text().replace('  推荐','') for b in c['camera_group'].buttons() if b.isChecked()), self.libraries[mode]['camera_strategies'][0]['name']),
            custom=c['custom'].toPlainText().strip(),
            custom_camera_pool=[b.text() for b in c['pool_buttons'] if b.isChecked()]
        )
        return normalize(d,mode,self.libraries[mode])

    def _sync_visibility(self, mode):
        c=self.mode_controls[mode]
        is_custom = self._serialize(mode)['camera']=='自定义'
        if c['pool_box'].isVisible() != is_custom:
            c['pool_box'].setVisible(is_custom)

    def _changed(self, mode):
        if self.mode_controls[mode].get('loading'): return
        if self.badge.text() != '有未保存的修改':
            self.badge.setText('有未保存的修改')
        if getattr(self, '_default_feedback_mode', None) == mode:
            self._default_feedback_mode = None
            if hasattr(self, 'set_default_btn'):
                self.set_default_btn.setText('★ 设为预设')
                self.set_default_btn.setProperty('successState', False)
                self.set_default_btn.style().unpolish(self.set_default_btn)
                self.set_default_btn.style().polish(self.set_default_btn)
        self._sync_visibility(mode); self._refresh_preview()

    def _refresh_preview(self, *_):
        if not hasattr(self,'preview_lines'): return
        mode=('TALKING','PRAYING')[max(0,self.tabs.currentIndex())]
        lib=self.libraries[mode]
        pool=active_camera_pool(self._serialize(mode),lib,mode)
        visible_names={x['name'] for x in lib['camera_shots']}
        for name,line in self.preview_lines.items():
            line.setVisible(name in visible_names)
            was_allowed = line.property('allowed')
            is_allowed = name in pool
            if was_allowed != is_allowed:
                line.setProperty('allowed', is_allowed)
                line.style().unpolish(line)
                line.style().polish(line)

    def _rule_text(self, mode, data):
        return rule_text(data,mode,self.libraries[mode])

    def _current_mode(self):
        return ('TALKING','PRAYING')[max(0, self.tabs.currentIndex())]

    def _default_mode_tab_changed(self, *_):
        if not hasattr(self, 'set_default_btn'):
            return
        mode=self._current_mode()
        if getattr(self, '_default_feedback_mode', None) == mode:
            self.set_default_btn.setText('✓ 已设为预设')
            self.set_default_btn.setProperty('successState', True)
            self.set_default_btn.style().unpolish(self.set_default_btn)
            self.set_default_btn.style().polish(self.set_default_btn)
        else:
            self.set_default_btn.setText('★ 设为预设')
            self.set_default_btn.setProperty('successState', False)
            self.set_default_btn.style().unpolish(self.set_default_btn)
            self.set_default_btn.style().polish(self.set_default_btn)

    def _set_current_mode_default(self):
        mode=self._current_mode()
        current=self._serialize(mode)
        save_persona_default(current, mode, self.libraries[mode])
        # Keep the current host and the newly saved mode-default on the same
        # effective settings immediately.  This avoids an older per-host persona
        # silently winning over the new default during GPT generation.
        repo.save_host_persona_mode(self.host_id, mode, current)
        self.mode_controls[mode]['data'] = normalize(current, mode, self.libraries[mode])
        label='闭眼祷告' if mode=='PRAYING' else '睁眼说话'
        self.badge.setText(f'{label} · 已设为默认')
        self._default_feedback_mode = mode
        if hasattr(self, 'set_default_btn'):
            self.set_default_btn.setText('✓ 已设为预设')
            self.set_default_btn.setProperty('successState', True)
            self.set_default_btn.style().unpolish(self.set_default_btn)
            self.set_default_btn.style().polish(self.set_default_btn)

    def _reset_defaults(self):
        mode=('TALKING','PRAYING')[self.tabs.currentIndex()]
        self._load_mode(mode, load_persona_default(mode, self.libraries[mode]))
        self._changed(mode)

    @staticmethod
    def _clear_layout_widgets(layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()

    def _rebuild_preview_lines(self):
        if not hasattr(self, 'preview_v'):
            return
        for line in list(getattr(self, 'preview_lines', {}).values()):
            self.preview_v.removeWidget(line)
            line.deleteLater()
        self.preview_lines = {}
        preview_names = []
        for mode in ('TALKING', 'PRAYING'):
            for item in self.libraries[mode]['camera_shots']:
                if item['name'] not in preview_names:
                    preview_names.append(item['name'])
        for name in preview_names:
            line = QLabel(name, objectName='personaPreviewLine')
            line.setMinimumHeight(28)
            line.setWordWrap(True)
            self.preview_v.insertWidget(max(0, self.preview_v.count()-1), line)
            self.preview_lines[name] = line

    def _reload_mode_presets_in_place(self, mode, data):
        """Reload one saved preset namespace without closing/reopening the host dialog."""
        c = self.mode_controls[mode]
        c['loading'] = True
        self.libraries[mode] = load_preset_library(mode)
        lib = self.libraries[mode]

        # 1. Performance chips: reuse the existing button group so its signal connection survives.
        for button in list(c['style_group'].buttons()):
            c['style_group'].removeButton(button)
        self._clear_layout_widgets(c['style_grid'])
        c['style_buttons'] = []
        for i, item in enumerate(lib['performance']):
            button = QPushButton(item['name'], objectName='chipBtn')
            button.setCheckable(True)
            button.setProperty('preset_id', item['id'])
            c['style_group'].addButton(button)
            c['style_grid'].addWidget(button, i//4, i%4)
            c['style_buttons'].append(button)
        custom_style = QPushButton('自定义', objectName='chipBtn')
        custom_style.setCheckable(True)
        custom_style.setProperty('preset_id', 'custom')
        c['style_group'].addButton(custom_style)
        i = len(lib['performance'])
        c['style_grid'].addWidget(custom_style, i//4, i%4)
        c['style_buttons'].append(custom_style)
        c['custom_style'] = custom_style

        # 2. Action chips; the last clicked chip directly controls the editor below.
        self._clear_layout_widgets(c['move_grid'])
        c['move_buttons'] = []
        for i, item in enumerate(lib['actions']):
            button = QPushButton(item['name'], objectName='chipBtn')
            button.setCheckable(True)
            button.setProperty('preset_id', item['id'])
            button.clicked.connect(lambda checked, m=mode, b=button: self._move_changed(m, b, checked))
            c['move_grid'].addWidget(button, i//3, i%3)
            c['move_buttons'].append(button)
        move_custom = QPushButton('自定义', objectName='chipBtn')
        move_custom.setCheckable(True)
        move_custom.setProperty('preset_id', 'custom')
        move_custom.clicked.connect(lambda checked, m=mode, b=move_custom: self._move_changed(m, b, checked))
        i = len(lib['actions'])
        c['move_grid'].addWidget(move_custom, i//3, i%3)
        c['move_custom'] = move_custom
        # 3. Camera strategy chips and custom camera pool.
        for button in list(c['camera_group'].buttons()):
            c['camera_group'].removeButton(button)
        self._clear_layout_widgets(c['cam_grid'])
        for i, item in enumerate(lib['camera_strategies']):
            text = item['name'] + ('  推荐' if item['id'] == 'strategy_natural' else '')
            button = QPushButton(text, objectName='chipBtn')
            button.setCheckable(True)
            button.setMinimumHeight(50)
            button.setProperty('preset_id', item['id'])
            button.toggled.connect(lambda _, m=mode: self._changed(m))
            c['camera_group'].addButton(button)
            c['cam_grid'].addWidget(button, i//3, i%3)
        custom_camera = QPushButton('自定义', objectName='chipBtn')
        custom_camera.setCheckable(True)
        custom_camera.setMinimumHeight(50)
        custom_camera.setProperty('preset_id', 'custom')
        custom_camera.toggled.connect(lambda _, m=mode: self._changed(m))
        c['camera_group'].addButton(custom_camera)
        i = len(lib['camera_strategies'])
        c['cam_grid'].addWidget(custom_camera, i//3, i%3)
        c['custom_camera'] = custom_camera

        self._clear_layout_widgets(c['pool_layout'])
        c['pool_buttons'] = []
        for item in lib['camera_shots']:
            chip = QPushButton(item['name'], objectName='personaPoolChip')
            chip.setCheckable(True)
            chip.setProperty('preset_id', item['id'])
            chip.toggled.connect(lambda _, m=mode: self._changed(m))
            c['pool_layout'].addWidget(chip)
            c['pool_buttons'].append(chip)

        c['loading'] = False
        self._load_mode(mode, data)
        self._rebuild_preview_lines()
        self._refresh_preview()
        self.badge.setText('预设已保存')

    def _edit_presets(self, section='camera_shots', mode=None):
        # Save the global preset library, then update only this mode in-place.
        # This avoids closing/reopening the whole persona window (visible flash).
        mode = mode or self._current_mode()
        pending = {'TALKING': self._serialize('TALKING'), 'PRAYING': self._serialize('PRAYING')}
        dlg = PersonaPresetLibraryDialog(self, section, mode)
        if dlg.exec():
            self._reload_mode_presets_in_place(mode, pending[mode])

    def save_all(self):
        talk=self._serialize('TALKING'); pray=self._serialize('PRAYING')
        try:
            repo.save_host_personas(self.host_id,talk,pray)
        except Exception as exc:
            QMessageBox.warning(self,'保存失败',str(exc)); return
        self.accept()


class HostRuleDialog(QDialog):
    def __init__(self, host_id, current_rule, parent=None):
        super().__init__(parent)
        self.host_id = host_id
        self.setWindowTitle("主播默认规则")
        self.resize(680, 500)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "这个规则会自动应用到该主播的全部图片/Flow片段；单张图片特殊要求仍可覆盖。",
            objectName="muted"
        ))
        self.editor = QPlainTextEdit()
        self.editor.setPlainText(current_rule or "")
        layout.addWidget(self.editor, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def save(self):
        repo.set_host_prompt_rule(self.host_id, self.editor.toPlainText().strip())
        self.accept()



class GenerateWorker(QThread):
    progress = Signal(int, int, str)
    item_done = Signal(int, bool, str)
    finished_summary = Signal(int, int, float, int, int, int, int)

    def __init__(self, segment_ids, model, core_prompt, image_detail="low", parent=None):
        super().__init__(parent)
        self.segment_ids = list(segment_ids)
        self.model = model
        self.core_prompt = core_prompt
        self.image_detail = image_detail
        # Runtime diagnostics: successful API requests and actual HTTP attempts are
        # deliberately tracked separately. A failed request must never be shown as
        # “API请求 0”, which previously hid the real failure reason.
        self.attempted_requests = 0
        self.last_error = ""

    # Prefer one API request for all selected segments sharing the same image.
    # GPT-5.6 models used by Flow Studio have ample output headroom; splitting is
    # a recovery path only, not the normal path.
    def _build_groups(self):
        groups = {}
        for sid in self.segment_ids:
            task = repo.get_prompt_task(sid)
            if not task: continue
            task = dict(task)
            vid = task.get("video_id")
            host_id = task.get("host_id")
            
            group_key = (host_id, vid, task.get("image_path") or "NO_IMAGE")
            
            if group_key not in groups:
                groups[group_key] = {
                    "image_path": task.get("image_path") or "NO_IMAGE",
                    "host_id": host_id,
                    "host_rule": task.get("host_rule", ""),
                    "image_rule": task.get("image_rule", ""),
                    "performance_mode": task.get("performance_mode"),
                    "template_snapshot": task.get("template_snapshot"),
                    "segment_type_manual": task.get("segment_type_manual"),
                    "video_id": vid,
                    "video_seq": task.get("video_seq", 0),
                    "segments": [],
                }
            groups[group_key]["segments"].append(task)
        return list(groups.values())

    @staticmethod
    def _large_batch_retryable(exc):
        text = str(exc or "").lower()
        markers = (
            "max_output_tokens", "context_length", "context window",
            "too long", "length", "incomplete", "truncated",
            "没有读取到批量提示词结果", "不是可解析的结构化批量结果",
            "批量结果缺少片段",
            # A large one-shot response can legitimately take longer than the old
            # 180 second socket timeout. Treat transport/temporary server failures
            # as recoverable so the existing two-half fallback can actually run.
            "超时", "timeout", "timed out", "http 408", "http 429",
            "http 500", "http 502", "http 503", "http 504",
            "server_error", "rate_limit", "rate limit",
            "connection reset", "remote end closed",
        )
        return any(marker in text for marker in markers)


    def run(self):
        try:
            self._run_queue()
        except Exception as exc:
            self.last_error = str(exc)
            self.finished_summary.emit(0, len(self.segment_ids), 0.0, 0, 0, 0, 0)

    def _run_queue(self):
        ok = 0
        failed = 0
        cost = 0.0
        total_input = 0
        total_cached = 0
        total_output = 0
        groups = self._build_groups()
        completed_requests = 0
        planned_requests = len(groups)

        def prepare_group(group):
            import json
            from app.core.persona import active_camera_catalog, active_camera_pool, rule_text, active_action_presets, normalize
            
            segments = group.get("segments", [])
            modes_present = set(str(s.get("performance_mode") or "").upper() == "PRAYING" and "PRAYING" or "TALKING" for s in segments)
            
            combined_templates = []
            combined_host_rules = []
            combined_action_presets = {}
            combined_camera_presets = {}
            auto_action = True
            
            for m in sorted(list(modes_present)):
                key = "praying_base_prompt" if m == "PRAYING" else "talking_base_prompt"
                template = (repo.get_setting(key, "") or "").strip()
                if not template: raise RuntimeError(f"{m} 基础模板尚未设置")
                combined_templates.append(f"【{m}片段基础模板】\n{template}")
                
                persona_raw = repo.get_setting(f"host_persona_{int(group.get('host_id') or 0)}_{m.lower()}", "")
                persona = normalize(json.loads(persona_raw) if persona_raw else {}, m)
                
                hr = rule_text(persona, m)
                combined_host_rules.append(f"对于 {m} 片段，请遵守以下人物设定：\n{hr}")
                
                if not persona.get('auto_action_match', True): auto_action = False
                
                for ap in active_action_presets(persona, mode=m):
                    combined_action_presets[ap['id']] = ap
                for cp in active_camera_catalog(persona, mode=m):
                    combined_camera_presets[cp['id']] = cp
            
            group['host_rule'] = "\n\n".join(combined_host_rules)
            previous_rule = group.get('host_rule', '')  # Note: previous_rule is usually empty, but kept for compat
            group['auto_action_match'] = auto_action
            group['action_presets'] = list(combined_action_presets.values())
            group['camera_presets'] = list(combined_camera_presets.values())
            
            effective_core = self.core_prompt.strip() + "\n\n" + "\n\n".join(combined_templates)
            return effective_core

        def save_result(result):
            nonlocal ok, cost, total_input, total_cached, total_output, completed_requests
            repo.save_prompt_batch_results(
                result["prompts"], self.model,
                result["input_tokens"], result["cached_tokens"],
                result["output_tokens"], result["cost_usd"],
                original_prompt_map=result.get("ai_prompts") or {},
            )
            group_ok = len(result["prompts"])
            ok += group_ok
            cost += result["cost_usd"]
            total_input += result["input_tokens"]
            total_cached += result["cached_tokens"]
            total_output += result["output_tokens"]
            completed_requests += 1
            for sid in result["prompts"]:
                self.item_done.emit(int(sid), True, "")

        def request_group(group, label, allow_fallback=True):
            nonlocal failed, planned_requests
            self.progress.emit(completed_requests + 1, max(planned_requests, completed_requests + 1), label)
            try:
                effective_core = prepare_group(group)
                segments = list(group.get("segments") or [])
                # Large, complete prompts take substantially longer than the old
                # 180 s timeout. Keep one-shot as the normal path, but give it a
                # realistic wait window instead of falsely failing a healthy call.
                request_timeout = max(180, min(480, 180 + 5 * len(segments)))
                def note_request(_meta=None):
                    self.attempted_requests += 1

                from app.services import broll_presets
                config=broll_presets.get_video_enhancement(int(group.get('video_id') or 0)) or {}
                if config.get('camera_enabled') and int(config.get('camera_limit') or 0)>0:
                    result=openai_service.generate_enhanced_prompts(model=self.model,core_prompt=effective_core,group=group,
                        config=config,preset_snapshot={},image_detail=self.image_detail,timeout=request_timeout,on_request=note_request)
                    plan=result['data']
                    broll_presets.save_video_plan(str(group['video_id']),plan['VIDEO_PLAN'],plan.get('IMAGE_PLAN') or [],[],config)
                    repo.create_image_plan_segments(int(group['video_id']),plan.get('IMAGE_PLAN') or [],self.model)
                else:
                    result = openai_service.generate_prompts_for_image(
                        model=self.model,core_prompt=effective_core,group=group,
                        image_detail=self.image_detail,timeout=request_timeout,on_request=note_request)
                save_result(result)
                return
            except Exception as exc:
                segments = list(group.get("segments") or [])
                self.last_error = str(exc)
                try:
                    from app.services.runtime_log import log
                    log(
                        "GPT_BATCH_REQUEST_FAILED",
                        video_id=group.get("video_id"), host_id=group.get("host_id"),
                        segment_count=len(segments), attempted_requests=self.attempted_requests,
                        allow_fallback=bool(allow_fallback), error=self.last_error[:1200],
                    )
                except Exception:
                    pass
                # Normal path is always one request. Only a genuine large-response
                # failure falls back once to two large halves. Never pre-split to
                # tiny 8-item requests.
                if allow_fallback and len(segments) >= 16 and self._large_batch_retryable(exc):
                    midpoint = (len(segments) + 1) // 2
                    halves = [segments[:midpoint], segments[midpoint:]]
                    planned_requests += 2
                    for i, half in enumerate(halves, 1):
                        sub = dict(group)
                        sub["segments"] = half
                        request_group(
                            sub,
                            f'{group["video_seq"]:02d} · 大批量自动降级 {i}/2 · {len(half)} 个片段',
                            allow_fallback=False,
                        )
                    return
                for seg in segments:
                    repo.mark_prompt_failed(seg["segment_id"], self.model)
                    self.item_done.emit(seg["segment_id"], False, str(exc))
                    failed += 1

        for group in groups:
            label = f'{group["video_seq"]:02d} · {len(group["segments"])} 个片段 · 单次生成'
            request_group(group, label, allow_fallback=True)

        self.finished_summary.emit(
            ok, failed, cost, completed_requests,
            total_input, total_cached, total_output
        )



class BatchPromptPasteDialog(QDialog):
    def __init__(self, target_count, parent=None):
        super().__init__(parent)
        self.target_count = int(target_count or 0)
        self.setWindowTitle("批量粘贴最终提示词")
        self.resize(820, 620)

        layout = QVBoxLayout(self)

        title = QLabel("批量粘贴最终提示词")
        title.setStyleSheet("font-size:20px;font-weight:800;")
        layout.addWidget(title)

        hint = QLabel(
            f"当前目标任务：{self.target_count} 个。"
            "可从 Google Sheets / Excel 复制一整列后直接粘贴；一行对应一个任务。"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        sub = QLabel(
            "有勾选任务时，只按勾选任务的表格顺序填充；没有勾选时，"
            "按当前筛选结果从上到下填充。手动结果标记为“已自定义”，API费用为0。",
            objectName="muted"
        )
        sub.setWordWrap(True)
        layout.addWidget(sub)

        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText(
            "在这里粘贴提示词整列…\n"
            "第1行 → 第1个任务\n第2行 → 第2个任务\n第3行 → 第3个任务"
        )
        self.editor.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        layout.addWidget(self.editor, 1)

        bar = QHBoxLayout()
        paste_btn = QPushButton("从剪贴板粘贴")
        paste_btn.clicked.connect(
            lambda: self.editor.setPlainText(QApplication.clipboard().text())
        )
        bar.addWidget(paste_btn)

        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(lambda:self.editor.clear() if confirm_clear(self,"清空","清空当前编辑框内容？") else None)
        bar.addWidget(clear_btn)
        bar.addStretch(1)

        self.count_label = QLabel("", objectName="muted")
        bar.addWidget(self.count_label)
        layout.addLayout(bar)

        self.editor.textChanged.connect(self.refresh_count)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Save)
        buttons.button(QDialogButtonBox.Save).setText("保存到表格")
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.validate_and_accept)
        layout.addWidget(buttons)

        self.refresh_count()

    def parsed_prompts(self):
        # Intended for one-column spreadsheet paste.
        return [line.strip() for line in self.editor.toPlainText().splitlines() if line.strip()]

    def refresh_count(self):
        self.count_label.setText(
            f"已识别 {len(self.parsed_prompts())} 条 / 目标 {self.target_count} 条"
        )

    def validate_and_accept(self):
        prompts = self.parsed_prompts()
        if not prompts:
            QMessageBox.information(self, "批量粘贴", "没有识别到提示词。")
            return
        if len(prompts) > self.target_count:
            ans = QMessageBox.question(
                self,
                "数量超过目标",
                f"粘贴了 {len(prompts)} 条，但当前目标只有 {self.target_count} 个。\n"
                f"将只保存前 {self.target_count} 条，继续吗？"
            )
            if ans != QMessageBox.Yes:
                return
        self.accept()


class PromptCenterPage(QWidget):
    def __init__(self, parent_window=None):
        super().__init__()
        self.parent_window = parent_window
        self.worker = None
        self.task_rows = []
        self.checked_ids = set()
        self._fill_source_row = None
        self._fill_target_state = None
        self.editor_segment_id = None
        self._editor_loading = False
        self._editor_dirty = False
        self._image_preview_cache = {}
        self.build()
        self.reload_filters()

    def build(self):
        # The prompt center is a dense production workspace. Keep the entire page inside
        # a real scroll area so shrinking the main window never makes controls overlap
        # or disappear. This is UI-only and does not change task/data behavior.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # V0.13.5.97: 5-tab structure wrapping the original content.
        

        # ── Tab 1: 提示词任务（原有全部内容） ──
        # Fixed one-screen workspace: the page itself never scrolls.  Scrolling is
        # intentionally confined to the left task table and the right quick editor.
        self.page_content = QWidget(objectName="promptPageContent")
        self.page_content.setMinimumSize(0, 0)
        self.page_content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(self.page_content)
        layout.setContentsMargins(14,8,14,10)
        layout.setSpacing(5)
        outer.addWidget(self.page_content, 1)

        # ── Tab 2–5: 新增标签页 ──


        top = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("GPT 提示词中心")
        title.setStyleSheet("font-size:20px;font-weight:700;")
        sub = QLabel("批量生成、人工检查并提交到 Flow", objectName="muted")
        title_box.addWidget(title)
        sub.hide()
        top.addLayout(title_box)
        top.addStretch(1)

        self.api_status = QLabel("", objectName="muted")
        top.addWidget(self.api_status)
        ai_settings = QPushButton("⚙ AI设置")
        ai_settings.clicked.connect(self.open_ai_settings)
        top.addWidget(ai_settings)
        # Prominent batch action stays in the header like the confirmed design.
        self.header_generate = QPushButton("① GPT API 生成", objectName="primaryBtn")
        self.header_generate.setFixedHeight(34)
        self.header_generate.clicked.connect(lambda: self.start_generation("checked_pending"))
        self.header_generate.setToolTip("按顺序生成已勾选且尚无提示词的任务；跳过已生成任务，单项失败后继续下一项。")
        top.addWidget(self.header_generate)
        layout.addLayout(top)

        stats=QHBoxLayout(); stats.setSpacing(10)
        def stat_card(title,tone="info"):
            card=QFrame(); box=QHBoxLayout(card); box.setContentsMargins(8,2,8,2)
            lab=QLabel(title,objectName="muted"); val=QLabel("0")
            val.setStyleSheet("font-size:14px;font-weight:600;")
            box.addWidget(lab); box.addWidget(val); box.addStretch(1)
            card.setFixedHeight(28); stats.addWidget(card,1); return val
        self.stat_hosts=stat_card("全部主播","info"); self.stat_pending=stat_card("待生成","warn"); self.stat_generated=stat_card("已生成","good"); self.stat_failed=stat_card("生成失败","bad")
        layout.addLayout(stats)

        # Recipient and host cards are the primary navigator. The original combo boxes remain
        # hidden underneath as stable state holders so no core task logic changes.

        self.recipient_scroll=QScrollArea(objectName="cardScroll"); self.recipient_scroll.setWidgetResizable(True); self.recipient_scroll.setFrameShape(QFrame.NoFrame); self.recipient_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded); self.recipient_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff); self.recipient_scroll.setFixedHeight(44)
        self.recipient_card_content=QWidget(objectName="scrollContent"); self.recipient_cards=QHBoxLayout(self.recipient_card_content); self.recipient_cards.setContentsMargins(0,0,0,0); self.recipient_cards.setSpacing(8); self.recipient_cards.setAlignment(Qt.AlignLeft); self.recipient_scroll.setWidget(self.recipient_card_content); layout.addWidget(self.recipient_scroll)
        self.host_section_title=QLabel("AI 主播",objectName="muted"); layout.addWidget(self.host_section_title)
        self.host_scroll=QScrollArea(objectName="cardScroll"); self.host_scroll.setWidgetResizable(True); self.host_scroll.setFrameShape(QFrame.NoFrame); self.host_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded); self.host_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # Host cards are a horizontal-only strip.  Keep the viewport tall enough for the
        # complete card plus the optional horizontal scrollbar so trackpad/wheel input
        # can never create a hidden vertical scroll range.
        self.host_scroll.setFixedHeight(112)
        self.host_card_content=QWidget(objectName="scrollContent"); self.host_card_content.setMinimumHeight(92); self.host_card_content.setMaximumHeight(92)
        self.host_cards=QHBoxLayout(self.host_card_content); self.host_cards.setContentsMargins(0,0,0,0); self.host_cards.setSpacing(9); self.host_cards.setAlignment(Qt.AlignLeft | Qt.AlignTop); self.host_scroll.setWidget(self.host_card_content); layout.addWidget(self.host_scroll)

        filters = QFrame(objectName="card")
        f = QHBoxLayout(filters)
        self.recipient = CleanComboBox(); self.recipient.hide()
        self.recipient.currentIndexChanged.connect(self.recipient_changed)
        f.addWidget(self.recipient)
        self.host = CleanComboBox(); self.host.hide()
        self.host.currentIndexChanged.connect(self.host_changed)
        f.addWidget(self.host)

        f.addWidget(QLabel("状态"))
        self.status_filter = CleanComboBox()
        self.status_filter.addItems(["全部", "未生成", "已生成", "已自定义", "失败"])
        self.status_filter.currentIndexChanged.connect(self.reload_tasks)
        f.addWidget(self.status_filter)

        f.addWidget(QLabel("工作区"))
        self.review_filter = CleanComboBox()
        self.review_filter.addItems(["当前任务", "待检查", "提交历史"])
        self.review_filter.currentIndexChanged.connect(self.reload_tasks)
        f.addWidget(self.review_filter)

        f.addStretch(1)

        self.paste_prompts_btn = QPushButton("② 手动批量填写")
        self.paste_prompts_btn.setObjectName("softBtn")
        self.paste_prompts_btn.clicked.connect(self.batch_paste_prompts)
        top.addWidget(self.paste_prompts_btn)
        self.template_prompts_btn=QPushButton("③ 通用模板套用",objectName="softBtn")
        self.template_prompts_btn.setFixedHeight(38)
        self.template_prompts_btn.clicked.connect(lambda:self.local_fill_prompts(True))
        top.addWidget(self.template_prompts_btn)

        self.clear_prompts_btn = QPushButton("清空选中提示词")
        self.clear_prompts_btn.setObjectName("softBtn")
        self.clear_prompts_btn.setToolTip("只清空当前勾选任务的最终提示词，不删除人物文案、图片或生成规则")
        self.clear_prompts_btn.clicked.connect(self.clear_selected_prompts)
        f.addWidget(self.clear_prompts_btn)

        self.pending_btn = QPushButton("仅选未生成")
        self.pending_btn.setObjectName("softBtn")
        self.pending_btn.clicked.connect(self.select_pending_rows)
        f.addWidget(self.pending_btn)

        self.retry_failed = QPushButton("仅重试失败项")
        self.retry_failed.clicked.connect(lambda: self.start_generation("failed"))
        f.addWidget(self.retry_failed)

        self.generate_selected = QPushButton("重试选中项")
        self.generate_selected.clicked.connect(lambda: self.start_generation("selected"))
        f.addWidget(self.generate_selected)

        self.generate_empty = QPushButton("用 GPT 批量生成提示词", objectName="primaryBtn")
        self.generate_empty.clicked.connect(lambda: self.start_generation("empty"))
        f.addWidget(self.generate_empty)
        
        
        

        self.submit_flow = QPushButton("提交选中项到 Flow", objectName="primaryBtn")
        self.submit_flow.clicked.connect(self.submit_selected_to_flow)
        f.addWidget(self.submit_flow)
        self.resubmit_selected = QPushButton("重新提交选中任务")
        self.resubmit_selected.clicked.connect(self.resubmit_selected_to_flow)
        self.resubmit_selected.setToolTip("仅替换勾选片段：旧批次作废，使用当前已保存提示词重新排队。")
        f.addWidget(self.resubmit_selected)
        self.submit_host = QPushButton("提交当前主播全部到 Flow")
        self.submit_host.clicked.connect(self.submit_current_host_to_flow)
        f.addWidget(self.submit_host)
        self.withdraw_flow = QPushButton("撤回选中项")
        self.withdraw_flow.clicked.connect(self.withdraw_selected_from_flow)
        f.addWidget(self.withdraw_flow)

        # Keep the existing layout, but normalize the production-action controls.
        for button in (self.paste_prompts_btn, self.clear_prompts_btn, self.pending_btn, self.retry_failed, self.generate_selected, self.generate_empty, self.submit_flow, self.resubmit_selected, self.submit_host, self.withdraw_flow):
            button.setMinimumWidth(0)
            button.setFixedHeight(38)
        # Rare maintenance actions stay available in code but do not crowd the daily workspace.

        self.clear_prompts_btn.hide()
        self.pending_btn.hide()
        self.withdraw_flow.hide()
        for button in (self.header_generate,self.paste_prompts_btn,self.template_prompts_btn):
            button.setStyleSheet('QPushButton {min-height:0px; padding:3px 8px;}')
            button.setFixedHeight(34)
        filter_scroll = QScrollArea()
        filter_scroll.setWidgetResizable(True)
        filter_scroll.setFrameShape(QFrame.NoFrame)
        filter_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        filter_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        filter_scroll.setFixedHeight(52)
        filter_scroll.setWidget(filters)
        layout.addWidget(filter_scroll)

        usage = QHBoxLayout()
        self.task_count = QLabel("任务：0")
        self.request_count = QLabel("预计请求：0")
        self.generated_count = QLabel("已生成：0")
        self.input_label = QLabel("输入：0")
        self.cache_label = QLabel("缓存：0")
        self.output_label = QLabel("输出：0")
        self.cost_label = QLabel("API累计：$0.0000")
        usage.addWidget(self.task_count)
        usage.addWidget(self.generated_count)
        usage.addWidget(self.cost_label)
        usage.addStretch(1)
        layout.addLayout(usage)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)
        layout.addWidget(self.progress)

        self.current_job = QLabel("就绪", objectName="muted")
        layout.addWidget(self.current_job)

        self.table = QTableWidget()
        # V0.12.6: the left side is now a compact task navigator. Long prompt text
        # is edited on the right, so it no longer squeezes the checkbox column.
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels([
            "☐", "任务ID", "参考图", "类型", "文案 / 图片提示词", "规则", "模式", "提示词", "成本"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(82)
        self.table.setMinimumWidth(0)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)

        h = self.table.horizontalHeader()
        h.setMinimumSectionSize(44)
        h.setSectionResizeMode(0, QHeaderView.Fixed)
        h.setSectionResizeMode(1, QHeaderView.Fixed)
        h.setSectionResizeMode(2, QHeaderView.Fixed)
        h.setSectionResizeMode(3, QHeaderView.Fixed)
        h.setSectionResizeMode(4, QHeaderView.Stretch)
        h.setSectionResizeMode(5, QHeaderView.Fixed)
        h.setSectionResizeMode(6, QHeaderView.Fixed)
        h.setSectionResizeMode(7, QHeaderView.Fixed)
        h.setSectionResizeMode(8, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 60)
        self.table.setColumnWidth(1, 82)
        self.table.setColumnWidth(2, 118)
        self.table.setColumnWidth(3, 112)
        self.table.setColumnWidth(5, 78)
        self.table.setColumnWidth(6, 132)
        self.table.setColumnWidth(7, 74)
        self.table.setColumnWidth(8, 76)
        # The confirmed UI uses a compact navigator. Reference image, rule and API cost
        # live in the right-hand detail area / history rather than as permanent columns.
        self.table.setColumnHidden(2, True)
        self.table.setColumnHidden(5, True)
        self.table.setColumnHidden(8, True)

        self.table.cellClicked.connect(self.load_inline_editor)
        self.table.itemSelectionChanged.connect(self.load_inline_editor_from_selection)
        self.table.horizontalHeader().sectionClicked.connect(self.header_clicked)

        # Single-click inline editor: no modal window is needed for normal editing.
        # The left side is now a real "文案列表" card, matching the confirmed visual
        # reference instead of looking like a raw spreadsheet dropped on the page.
        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(6)

        task_card = QFrame(objectName="workspacePanel")
        task_v = QVBoxLayout(task_card)
        task_v.setContentsMargins(12, 10, 12, 10)
        task_v.setSpacing(8)
        self.task_panel_title = QLabel("文案列表", objectName="workspaceTitle")
        task_v.addWidget(self.task_panel_title)
        task_tools = QHBoxLayout()
        task_tools.setSpacing(6)
        self.mode_all_frame_btn = QPushButton("全部设为帧模式", objectName="softBtn")
        self.mode_first_material_btn = QPushButton("每个完整视频首片设为素材", objectName="softBtn")
        self.mode_selected_material_btn = QPushButton("选中项设为素材", objectName="softBtn")
        self.mode_all_frame_btn.clicked.connect(lambda: self._batch_set_generation_mode("all_frame"))
        self.mode_first_material_btn.clicked.connect(lambda: self._batch_set_generation_mode("first_material"))
        self.mode_selected_material_btn.clicked.connect(lambda: self._batch_set_generation_mode("selected_material"))
        task_tools.addWidget(self.mode_all_frame_btn)
        task_tools.addWidget(self.mode_first_material_btn)
        task_tools.addWidget(self.mode_selected_material_btn)
        task_tools.addStretch(1)
        task_v.addLayout(task_tools)
        task_v.addWidget(self.table, 1)
        task_actions = QHBoxLayout()
        task_actions.setSpacing(6)
        self.select_all_visible_btn = QPushButton("全选", objectName="softBtn")
        self.select_all_visible_btn.clicked.connect(self._select_all_visible)
        task_actions.addWidget(self.select_all_visible_btn)
        self.delete_segment_btn = QPushButton("删除片段", objectName="softBtn")
        self.merge_prev_btn = QPushButton("合并到上一片", objectName="softBtn")
        self.merge_next_btn = QPushButton("合并到下一片", objectName="softBtn")
        self.delete_segment_btn.clicked.connect(self._delete_selected_prompt_segment)
        self.merge_prev_btn.clicked.connect(lambda: self._merge_selected_prompt_segment("prev"))
        self.merge_next_btn.clicked.connect(lambda: self._merge_selected_prompt_segment("next"))
        task_actions.addWidget(self.delete_segment_btn)
        task_actions.addWidget(self.merge_prev_btn)
        task_actions.addWidget(self.merge_next_btn)
        change_type=QPushButton('设置类型',objectName='softBtn');change_type.clicked.connect(self._set_selected_prompt_type);task_actions.addWidget(change_type)
        task_actions.addWidget(self.generate_selected)
        task_actions.addStretch(1)
        task_v.addLayout(task_actions)
        split.addWidget(task_card)

        editor_card = QFrame(objectName="workspacePanel")
        editor_outer = QVBoxLayout(editor_card)
        editor_outer.setContentsMargins(0, 0, 0, 0)
        editor_outer.setSpacing(0)
        self.editor_scroll = QScrollArea(objectName="promptEditorScroll")
        self.editor_scroll.setWidgetResizable(True)
        self.editor_scroll.setFrameShape(QFrame.NoFrame)
        self.editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.editor_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        editor_content = QWidget(objectName="promptEditorContent")
        ev = QVBoxLayout(editor_content)
        ev.setContentsMargins(14, 14, 14, 14)
        ev.setSpacing(8)
        self.editor_scroll.setWidget(editor_content)
        editor_outer.addWidget(self.editor_scroll, 1)
        self.editor_title = QLabel("快速编辑 · 单击左侧任务即可")
        self.editor_title.setStyleSheet("font-size:17px;font-weight:750;")
        ev.addWidget(self.editor_title)
        self.editor_meta = QLabel("直接在这里修改；切换任务时会自动保存已改内容，也可以按“保存并下一条”。", objectName="muted")
        self.editor_meta.setWordWrap(True)
        ev.addWidget(self.editor_meta)

        preview_row = QHBoxLayout()
        self.editor_image = QLabel("参考图")
        self.editor_image.setObjectName("thumb")
        self.editor_image.setFixedSize(118,118)
        self.editor_image.setAlignment(Qt.AlignCenter)
        preview_row.addWidget(self.editor_image)
        dialogue_box = QVBoxLayout()
        dialogue_box.addWidget(QLabel("人物文案（可直接编辑）"))
        self.editor_dialogue = QPlainTextEdit()
        self.editor_dialogue.setReadOnly(False)
        self.editor_dialogue.setMaximumHeight(92)
        dialogue_box.addWidget(self.editor_dialogue)
        preview_row.addLayout(dialogue_box,1)
        ev.addLayout(preview_row)

        ev.addWidget(QLabel("人物 / 图片特殊要求"))
        self.editor_image_rule = QPlainTextEdit()
        self.editor_image_rule.setPlaceholderText("例如：全程闭眼祈祷；禁止正面拍摄。作用于这张图片的全部片段。")
        self.editor_image_rule.setMaximumHeight(92)
        ev.addWidget(self.editor_image_rule)

        ev.addWidget(QLabel("单条特殊要求"))
        self.editor_segment_rule = QPlainTextEdit()
        self.editor_segment_rule.setPlaceholderText("只作用于当前这个 Flow 小片段；没有可留空。")
        self.editor_segment_rule.setMaximumHeight(80)
        ev.addWidget(self.editor_segment_rule)

        final_row = QHBoxLayout()
        final_row.addWidget(QLabel("最终 Flow 提示词"))
        final_row.addStretch(1)
        self.editor_prompt_state = QLabel("", objectName="muted")
        final_row.addWidget(self.editor_prompt_state)
        ev.addLayout(final_row)
        self.editor_final_prompt = QPlainTextEdit()
        self.editor_final_prompt.setPlaceholderText("可以直接在这里填写或修改最终 Flow 提示词。")
        self.editor_final_prompt.setMinimumHeight(180)
        ev.addWidget(self.editor_final_prompt,1)

        action = QHBoxLayout()
        self.editor_save = QPushButton("保存", objectName="primaryBtn")
        self.editor_save.clicked.connect(self.save_inline_editor)
        action.addWidget(self.editor_save)
        self.editor_save_next = QPushButton("保存并下一条")
        self.editor_save_next.clicked.connect(self.save_and_next)
        action.addWidget(self.editor_save_next)
        self.editor_reload = QPushButton("撤销未保存修改")
        self.editor_reload.clicked.connect(self.reload_inline_editor)
        action.addWidget(self.editor_reload)
        action.addStretch(1)
        ev.addLayout(action)

        for editor in (self.editor_dialogue, self.editor_image_rule, self.editor_segment_rule, self.editor_final_prompt):
            editor.textChanged.connect(self.mark_editor_dirty)
        self.editor_dialogue.textChanged.connect(self._dialogue_text_changed)

        editor_card.setMinimumWidth(280)
        split.addWidget(editor_card)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        self.workspace_splitter = split
        saved_split = str(repo.get_setting("prompt_center_splitter_sizes_v1", "") or "").strip()
        try:
            sizes=[max(120,int(x)) for x in saved_split.split(',')[:2]]
            if len(sizes)!=2: raise ValueError
        except Exception:
            sizes=[820,500]
        split.setSizes(sizes)
        split.splitterMoved.connect(self._save_workspace_splitter)
        self._table_loading=False
        self.table.itemChanged.connect(self._prompt_table_item_changed)
        for button in (self.mode_all_frame_btn,self.mode_first_material_btn,self.mode_selected_material_btn,self.select_all_visible_btn,self.delete_segment_btn,self.merge_prev_btn,self.merge_next_btn,self.generate_selected):
            button.setStyleSheet('QPushButton {min-height:0px; padding:3px 8px;}')
            button.setFixedHeight(30)
        layout.addWidget(split, 1)

    def _save_workspace_splitter(self, *_):
        if not hasattr(self,"workspace_splitter"): return
        sizes=self.workspace_splitter.sizes()
        if len(sizes)>=2 and all(int(x)>0 for x in sizes[:2]):
            repo.set_setting("prompt_center_splitter_sizes_v1",f"{int(sizes[0])},{int(sizes[1])}")

    def _dialogue_text_changed(self):
        if self._editor_loading or not self.editor_segment_id: return
        current=' '.join(self.editor_dialogue.toPlainText().split())
        loaded=getattr(self,'_loaded_dialogue','')
        if current != loaded and self.editor_final_prompt.toPlainText().strip():
            # Copy changed => the old AI prompt is no longer authoritative. Never call GPT
            # automatically; simply clear the UI prompt so the user chooses when to regenerate.
            self.editor_final_prompt.blockSignals(True)
            self.editor_final_prompt.clear()
            self.editor_final_prompt.blockSignals(False)
            self.editor_prompt_state.setText("文案已修改 · Prompt需重新生成/手填")

    def _set_one_generation_mode(self, segment_id, mode):
        try:
            repo.set_segment_generation_mode(int(segment_id),mode,allow_active_rework=False,force_silent=True)
            for i,t in enumerate(self.task_rows):
                if int(t['segment_id'])==int(segment_id):
                    fresh=repo.get_prompt_task(int(segment_id))
                    if fresh: self.task_rows[i]=fresh
                    break
        except Exception as exc:
            QMessageBox.warning(self,"切换模式",str(exc)); self.reload_tasks()

    def _batch_set_generation_mode(self, action):
        if action=='all_frame':
            ids=[int(t['segment_id']) for t in self.task_rows]; result=repo.set_generation_mode_for_segments(ids,'FRAME',force_silent=True)
        elif action=='first_material':
            result=repo.set_first_segment_mode_for_videos({int(t['video_id']) for t in self.task_rows},'MATERIAL',force_silent=True)
        else:
            ids=self.selected_segment_ids()
            if not ids:
                QMessageBox.information(self,"设置素材模式","请先勾选需要设为素材的片段。"); return
            result=repo.set_generation_mode_for_segments(ids,'MATERIAL',force_silent=True)
        self.current_job.setText(f"模式已更新：{result.get('changed',0)} 条；跳过/锁定 {result.get('blocked',0)} 条")
        self.reload_tasks()

    def _selected_prompt_segment_id(self):
        rows=sorted({idx.row() for idx in self.table.selectionModel().selectedRows()})
        return int(self.task_rows[rows[0]]['segment_id']) if rows and 0<=rows[0]<len(self.task_rows) else 0

    def _delete_selected_prompt_segment(self):
        sid=self._selected_prompt_segment_id()
        if not sid: return
        if QMessageBox.question(self,"删除片段","删除当前 Flow 片段？同一完整视频后续片段会顺序补位，其他完整视频编号不会变化。")!=QMessageBox.Yes: return
        try: repo.edit_prompt_segment_text(sid,'')
        except Exception as exc: QMessageBox.warning(self,"删除片段",str(exc)); return
        self.checked_ids.discard(sid); self.editor_segment_id=None; self.reload_tasks()

    def _set_selected_prompt_type(self):
        sid=self._selected_prompt_segment_id()
        if not sid:return
        label,ok=QInputDialog.getItem(self,'片段类型','手动选择类型',['睁眼说话','闭眼祷告'],0,False)
        if not ok:return
        try:repo.set_prompt_segment_type(sid,'TALKING' if label=='睁眼说话' else 'PRAYING')
        except Exception as exc:QMessageBox.warning(self,'片段类型',str(exc));return
        self.editor_segment_id=None;self.reload_tasks()

    def _merge_selected_prompt_segment(self, direction):
        sid=self._selected_prompt_segment_id()
        if not sid: return
        label,ok=QInputDialog.getItem(self,'合并文案','合并后的片段类型',['睁眼说话','闭眼祷告'],0,False)
        if not ok:return
        try: repo.merge_prompt_segment(sid,direction,'TALKING' if label=='睁眼说话' else 'PRAYING')
        except Exception as exc: QMessageBox.warning(self,"合并文案",str(exc)); return
        self.checked_ids.discard(sid); self.editor_segment_id=None; self.reload_tasks()

    def _prompt_table_item_changed(self, item):
        if getattr(self,'_table_loading',False) or item.column()!=4: return
        row=item.row()
        if row<0 or row>=len(self.task_rows): return
        sid=int(self.task_rows[row]['segment_id'])
        old=' '.join(str(self.task_rows[row]['foreign_text'] or '').split())
        new=' '.join(str(item.text() or '').split())
        if new==old: return
        try:
            repo.edit_prompt_segment_text(sid,new)
        except Exception as exc:
            QMessageBox.warning(self,"修改文案",str(exc)); self.reload_tasks(); return
        if not new: self.checked_ids.discard(sid)
        self.editor_segment_id=None
        self.reload_tasks()

    def _apply_task_search(self, text):
        """Local visual filtering only; underlying task data is untouched."""
        needle = (text or "").strip().lower()
        for row in range(self.table.rowCount()):
            if not needle:
                self.table.setRowHidden(row, False)
                continue
            hay = []
            for col in (1, 3, 4, 6, 7):
                item = self.table.item(row, col)
                if item:
                    hay.append(item.text())
                    hay.append(item.toolTip())
            self.table.setRowHidden(row, needle not in " ".join(hay).lower())

    def _select_all_visible(self):
        for row, task in enumerate(self.task_rows):
            if self.table.isRowHidden(row):
                continue
            sid = int(task["segment_id"])
            self.checked_ids.add(sid)
            cell = self._cell_check(row)
            if cell is not None:
                try:
                    cell.setChecked(True)
                except Exception:
                    pass
        self.update_header_check()

    def _clear_card_layout(self, layout):
        while layout.count():
            item=layout.takeAt(0); w=item.widget()
            if w: w.deleteLater()

    def _rebuild_recipient_cards(self):
        if not hasattr(self,'recipient_cards'): return
        self._clear_card_layout(self.recipient_cards)
        current=self.recipient.currentData()

        def add_recipient_card(title, subtitle, rid=None, initial="全"):
            selected = (current is None and rid is None) or (rid is not None and current == rid)
            card = QFrame(objectName="recipientCard")
            card.setProperty("selected", selected)
            card.setFixedSize(176, 32)
            box = QHBoxLayout(card); box.setContentsMargins(8,2,8,2); box.setSpacing(6)
            name = QLabel(title); box.addWidget(name)
            meta = QLabel(subtitle, objectName="muted"); box.addWidget(meta)
            hit = QPushButton(card); hit.setObjectName("transparentHit"); hit.setGeometry(card.rect())
            hit.clicked.connect(lambda _=False, x=rid: self.recipient.setCurrentIndex(0) if x is None else self._select_recipient_id(x))
            self.recipient_cards.addWidget(card)

        for r in repo.list_recipients(work_date=work_dates.active()):
            rid=int(r['id']); name=str(r['name'] or '未命名'); count=int(r['host_count'] or 0)
            add_recipient_card(name, f"{count} 个主播", rid, name[:1])
        self.recipient_cards.addStretch(1)

    def _select_recipient_id(self, rid):
        i=self.recipient.findData(rid)
        if i>=0: self.recipient.setCurrentIndex(i)

    def _select_host_id(self, hid):
        i=self.host.findData(hid)
        if i>=0: self.host.setCurrentIndex(i)

    def _rebuild_host_cards(self):
        if not hasattr(self,'host_cards'): return
        self._clear_card_layout(self.host_cards)
        rid=self.recipient.currentData(); current=self.host.currentData()
        if not rid:
            self.host_section_title.setText('AI 主播 · 先选择一个接收人')
            empty=QFrame(objectName='workspacePanel'); empty.setFixedSize(360,90)
            eb=QVBoxLayout(empty); msg=QLabel('选择上方接收人后，这里会自动显示该接收人的 AI 主播。',objectName='muted'); msg.setWordWrap(True); eb.addStretch(1); eb.addWidget(msg,0,Qt.AlignCenter); eb.addStretch(1)
            self.host_cards.addWidget(empty); self.host_cards.addStretch(1); return
        rec=repo.get_recipient(rid); hosts=list(repo.list_hosts(rid, work_date=work_dates.active())); self.host_section_title.setText(f'{rec["name"] if rec else ""} 的 AI 主播 ({len(hosts)})')

        for h in hosts:
            hid=int(h['id']); tasks=list(repo.list_prompt_tasks(rid,hid,'全部', work_date=work_dates.active()))
            generated=sum(1 for t in tasks if str(t['prompt'] or '').strip()); total=len(tasks)
            talking=sum(1 for t in tasks if t['segment_type_source']!='unclassified' and str(t['performance_mode'] or '').upper()!='PRAYING')
            praying=sum(1 for t in tasks if t['segment_type_source']!='unclassified' and str(t['performance_mode'] or '').upper()=='PRAYING')
            selected=(current==hid)
            card=QFrame(objectName='hostCard'); card.setProperty('selected',selected); card.setFixedSize(370,92)
            row=QHBoxLayout(card); row.setContentsMargins(7,5,7,5); row.setSpacing(8)
            image_label=QLabel(objectName='hostThumb'); image_label.setFixedSize(54,72); image_label.setAlignment(Qt.AlignCenter)
            image=resolve_anchor_thumbnail(hid)
            set_image(image_label, image)
            row.addWidget(image_label)
            right=QVBoxLayout(); right.setSpacing(1)
            title=QLabel(str(h['name'] or '未命名主播'),objectName='hostName'); right.addWidget(title)
            meta=QLabel(f'{total} 条文案',objectName='cardMeta'); meta.hide()
            prog=QLabel(f'{generated} / {total} 已生成', objectName='muted'); prog.hide()
            bar=QProgressBar(); bar.setRange(0,max(1,total)); bar.setValue(generated); bar.setTextVisible(False); bar.setFixedHeight(3); bar.hide()
            chips=QHBoxLayout(); chips.setSpacing(4)
            a=QLabel(f'睁眼 {talking}',objectName='miniTag'); b=QLabel(f'闭眼 {praying}',objectName='miniTagAlt'); chips.addWidget(a); chips.addWidget(b); chips.addStretch(1); right.addLayout(chips)
            actions=QHBoxLayout(); actions.setSpacing(6); actions.setContentsMargins(0,2,0,0)
            select_btn=QPushButton('已选择' if selected else '选择主播', objectName='primaryBtn' if selected else 'softBtn'); select_btn.setFixedHeight(30); select_btn.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed); select_btn.clicked.connect(lambda _=False,x=hid:self._select_host_id(x)); actions.addWidget(select_btn,1)
            settings_btn=QPushButton('⚙ 人物设置', objectName='softBtn'); settings_btn.setFixedHeight(30); settings_btn.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed)
            settings_btn.clicked.connect(lambda _=False,x=hid:self._open_generation_rules_for_host(x)); actions.addWidget(settings_btn,1)
            for button in (select_btn,settings_btn):
                button.setStyleSheet('QPushButton {min-height:0px; padding:2px 6px;}')
                button.setFixedHeight(26)
            right.addLayout(actions); row.addLayout(right,1)
            self.host_cards.addWidget(card)
        self.host_cards.addStretch(1)

    def _open_generation_rules_for_host(self, hid):
        i=self.host.findData(hid)
        if i>=0:
            self.host.setCurrentIndex(i)
        self.open_generation_rules()

    def host_changed(self):
        self._rebuild_host_cards()
        self.reload_tasks()
        # Propagate host selection to child tabs ONLY if we are not currently in that tab




    def reload_filters(self):
        from app.services.eye_states import reconcile_saved_colors
        reconcile_saved_colors(work_dates.active())
        previous_recipient=self.recipient.currentData()
        self.recipient.blockSignals(True)
        self.recipient.clear()
        for r in repo.list_recipients(work_date=work_dates.active()):
            self.recipient.addItem(r["name"], r["id"])
        previous_index=self.recipient.findData(previous_recipient)
        if previous_index>=0: self.recipient.setCurrentIndex(previous_index)
        self.recipient.blockSignals(False)
        self._rebuild_recipient_cards()
        self.recipient_changed()
        self.refresh_api_status()

    def refresh_api_status(self):
        model = repo.get_setting("openai_model", "gpt-5.6-luna")
        detail = repo.get_setting("image_detail", "low") or "low"
        detail_name = {"low":"低成本图像", "auto":"自动图像", "high":"高细节图像"}.get(detail, detail)
        key = "已连接钥匙串" if openai_service.get_api_key() else "未设置API Key"
        self.api_status.setText(f"{model} · {detail_name} · {key}")

    def recipient_changed(self):
        rid = self.recipient.currentData()
        previous_host = self.host.currentData()
        self.host.blockSignals(True)
        self.host.clear()
        self.host.addItem("全部", None)
        if rid:
            for h in repo.list_hosts(rid, work_date=work_dates.active()):
                if not getattr(self,"_date_view_refresh",False): repo.ensure_flow_segments_for_host(h["id"])
                self.host.addItem(h["name"], h["id"])
        else:
            for r in repo.list_recipients(work_date=work_dates.active()):
                for h in repo.list_hosts(r["id"], work_date=work_dates.active()):
                    if not getattr(self,"_date_view_refresh",False): repo.ensure_flow_segments_for_host(h["id"])
                    
        previous_host_index = self.host.findData(previous_host)
        if previous_host_index >= 0:
            self.host.setCurrentIndex(previous_host_index)
            
        self.host.blockSignals(False)
        self._rebuild_recipient_cards()
        self._rebuild_host_cards()
        self.reload_tasks()

    def reload_tasks(self):
        rid = self.recipient.currentData()
        hid = self.host.currentData()
        status = self.status_filter.currentText()
        if hid and not getattr(self,"_date_view_refresh",False):
            repo.ensure_flow_segments_for_host(hid)
        rows = list(repo.list_prompt_tasks(rid, hid, status, work_date=work_dates.active()))
        if hasattr(self, "task_panel_title"):
            host_name = self.host.currentText() if hid else "全部主播"
            self.task_panel_title.setText(f"{host_name} · 文案列表 ({len(rows)})")
        gate = self.review_filter.currentText() if hasattr(self, "review_filter") else "当前任务"
        if gate in ("已提交", "提交历史"):
            self.task_rows = [r for r in rows if str(r["prompt_review_status"] or "待检查") == "已提交"]
        elif gate == "待检查":
            self.task_rows = [r for r in rows if str(r["prompt_review_status"] or "待检查") != "已提交" and str(r["prompt"] or "").strip()]
        else:
            # Default work queue: hide already submitted items.
            self.task_rows = [r for r in rows if str(r["prompt_review_status"] or "待检查") != "已提交"]

        self._table_loading=True
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(self.task_rows))
        self.table.horizontalHeaderItem(0).setText("☐")
        generated = 0
        from app.services.sheet_style import segment_snapshots
        from app.ui.sheet_rich_text import SheetTextDelegate, attach
        if not hasattr(self, '_sheet_delegate'):
            self._sheet_delegate = SheetTextDelegate(self.table)
            self.table.setItemDelegateForColumn(4, self._sheet_delegate)
        self._segment_styles = {}
        for vid in {t['video_id'] for t in self.task_rows}:
            self._segment_styles.update(segment_snapshots(vid))

        for row, task in enumerate(self.task_rows):
            sid = task["segment_id"]
            check = CheckCell(sid in self.checked_ids)
            check.changed.connect(
                lambda checked, segment_id=sid: self.on_row_check_changed(segment_id, checked)
            )
            check.drag_started.connect(
                lambda state, source_row=row: self.start_fill_drag(source_row, state)
            )
            check.drag_moved_global.connect(self.update_fill_drag)
            check.drag_finished.connect(self.finish_fill_drag)
            self.table.setCellWidget(row, 0, check)

            task_id = f'{task["video_seq"]:02d}-{task["seg_seq"]:02d}'
            self.table.setItem(row, 1, QTableWidgetItem(task_id))

            image_item = QTableWidgetItem(
                Path(task["image_path"]).name if task["image_path"] else "无图片"
            )
            self.table.setItem(row, 2, image_item)

            is_image = int(task["seg_seq"]) >= 1000 and str(task["foreign_text"] or "").startswith("[LEGACY_AUX]")
            mode = "图片" if is_image else ("PRAYING" if str(task["performance_mode"] or "").upper() == "PRAYING" else "TALKING")
            source = task['segment_type_source']
            label = mode if is_image else (('闭眼' if mode == 'PRAYING' else '睁眼') +
                (' · 黑字' if mode == 'PRAYING' else ' · 红字') if source == 'sheet_color' else
                (('闭眼' if mode == 'PRAYING' else '睁眼') + ' · 手动' if source == 'manual' else '待识别'))
            type_item = QTableWidgetItem(label)
            type_item.setFlags(type_item.flags() & ~Qt.ItemIsEditable)
            type_item.setToolTip('按同步文案的原始字体颜色自动分配：红字睁眼，黑字闭眼。' if source == 'sheet_color' else
                                ('使用已保存的手动分类。' if source == 'manual' else '未找到可应用的颜色分类；请同步表格样式。已开始生产的任务保持原状态。'))
            self.table.setItem(row, 3, type_item)

            content = ((task["foreign_text"] or "") + "\n" + (task["prompt"] or "待填写图片提示词")) if is_image else (task["foreign_text"] or "")
            foreign = QTableWidgetItem(content)
            foreign.setToolTip(content)
            if is_image: foreign.setFlags(foreign.flags() & ~Qt.ItemIsEditable)
            attach(foreign, self._segment_styles.get(sid))
            self.table.setItem(row, 4, foreign)

            custom = bool((task["special_requirements"] or "").strip() or
                          (task["segment_rule"] or "").strip())
            rule_item = QTableWidgetItem("已自定义" if custom else "默认")
            self.table.setItem(row, 5, rule_item)

            if task["prompt"]:
                generated += 1
            if is_image:
                self.table.removeCellWidget(row, 6)
                mode_item=QTableWidgetItem("图片")
                mode_item.setFlags(mode_item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, 6, mode_item)
            else:
                mode_toggle=GenerationModeToggle(task["generation_mode"] or "FRAME", self.table)
                mode_toggle.modeChanged.connect(lambda mode, segment_id=int(sid): self._set_one_generation_mode(segment_id, mode))
                self.table.setCellWidget(row, 6, mode_toggle)

            prompt_state = ("失败" if str(task["status"] or "")=="失败" else ("已填" if (task["prompt"] or "").strip() else "未填"))
            prompt_item = QTableWidgetItem(prompt_state)
            prompt_item.setToolTip(task["prompt"] or "")
            self.table.setItem(row, 7, prompt_item)

            self.table.setItem(row, 8, QTableWidgetItem(
                f'${float(task["cost_usd"] or 0):.4f}' if task["cost_usd"] else ""
            ))

        self.update_header_check()
        self.table.setUpdatesEnabled(True)
        self._table_loading=False
        if self.editor_segment_id:
            visible = [t["segment_id"] for t in self.task_rows]
            if self.editor_segment_id in visible:
                self.reload_inline_editor()
            elif self.task_rows:
                self.load_inline_editor(0, 1)
        elif self.task_rows:
            self.load_inline_editor(0, 1)

        summary = repo.prompt_usage_breakdown(work_date=work_dates.active())
        try:
            all_tasks=list(repo.list_prompt_tasks(None,None,"全部", work_date=work_dates.active())); all_hosts=sum(len(repo.list_hosts(int(r["id"]), work_date=work_dates.active())) for r in repo.list_recipients(work_date=work_dates.active())); pending_all=sum(1 for t in all_tasks if not str(t["prompt"] or "").strip() and str(t["status"] or "")!="失败"); generated_all=sum(1 for t in all_tasks if str(t["prompt"] or "").strip()); failed_all=sum(1 for t in all_tasks if str(t["status"] or "")=="失败")
            self.stat_hosts.setText(str(all_hosts)); self.stat_pending.setText(str(pending_all)); self.stat_generated.setText(str(generated_all)); self.stat_failed.setText(str(failed_all))
        except Exception:
            pass

        visible_video_ids = {task["video_id"] for task in self.task_rows}
        self.task_count.setText(f"任务：{len(self.task_rows)}")
        self.request_count.setText(f"按图片合并后请求：{len(visible_video_ids)}")
        gates = repo.prompt_gate_counts(work_date=work_dates.active())
        self.generated_count.setText(f"已生成：{generated} · 待检查 {gates.get('pending',0)} · 已提交 {gates.get('submitted',0)}")
        self.input_label.setText(f'输入：{summary["input_tokens"]:,}')
        self.cache_label.setText(f'缓存：{summary["cached_tokens"]:,}')
        self.output_label.setText(f'输出：{summary["output_tokens"]:,}')
        self.cost_label.setText(f'API累计：${summary["cost_usd"]:.4f}')
        self.refresh_api_status()

    def _wake_flow_scheduler(self):
        center=getattr(self.parent_window,'flow_task_center',None)
        if center is not None:
            # Defer to the existing scheduler, including its pause and ownership gates.
            QTimer.singleShot(0,center.auto_dispatch_tick)

    def _confirm_host_overwrite(self, host_names):
        names='、'.join(str(x) for x in host_names if x) or '当前主播'
        box=QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle('覆盖重建主播任务')
        box.setText(f'检测到 {names} 已经存在 Flow / 质检 / 返工 / 剪辑下游任务。')
        box.setInformativeText(
            '继续后将以当前新提示词作为唯一有效版本：旧 Flow 任务与返工会移除，本地已下载的旧 Flow 视频片段会删除，'
            '旧片段会从质检中心和待剪辑链路移出；仍在云端运行的旧结果以后回来也会自动作废。\n\n'
            '接收人、主播、图片、文案、编号和人物设置不会改变。'
        )
        yes=box.addButton('确认覆盖重建',QMessageBox.AcceptRole)
        box.addButton('取消',QMessageBox.RejectRole)
        box.exec()
        return box.clickedButton() is yes

    def _cancel_obsolete_bridge_commands(self, result):
        commands=list((result or {}).get('old_command_ids') or [])
        if not commands: return
        owner=getattr(self,'parent_window',None)
        flow=getattr(owner,'flow_task_center',None)
        bridge=getattr(flow,'bridge',None)
        try:
            if bridge is not None and hasattr(bridge,'cancel_host_commands'):
                bridge.cancel_host_commands(commands)
        except Exception:
            pass

    def _refresh_after_host_overwrite(self):
        owner=getattr(self,'parent_window',None)
        flow=getattr(owner,'flow_task_center',None)
        qc=getattr(owner,'qc_page',None)
        davinci=getattr(owner,'davinci_page',None)
        try:
            if flow is not None: flow.reload_filters()
        except Exception: pass
        try:
            if qc is not None: qc.reload()
        except Exception: pass
        try:
            if davinci is not None: davinci.reload()
        except Exception: pass

    def resubmit_selected_to_flow(self):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self,'重新提交','请等待本次 GPT 提示词生成结束后，再检查并重新提交。')
            return
        from app.services import selected_resubmission
        ids=self.selected_segment_ids()
        if not ids:
            QMessageBox.information(self,'重新提交','请先勾选需要替换的任务，可在提交历史中勾选。')
            return
        # Save current edited prompt before submitting; never regenerate paid prompts here.
        sid=getattr(self,'editor_segment_id',None)
        edits={sid:self.editor_final_prompt.toPlainText()} if sid in ids and hasattr(self,'editor_final_prompt') else {}
        try:result=selected_resubmission.replace(ids,work_dates.active(),prompt_overrides=edits)
        except Exception as exc:
            QMessageBox.warning(self,'重新提交失败',str(exc));return
        self._wake_flow_scheduler()
        self._refresh_after_host_overwrite()
        self.reload_tasks()
        QMessageBox.information(self,'已重新提交',f"已替换 {result['submitted']} 条任务，删除旧视频 {result['deleted_files']} 个。旧批次迟到结果将作废。" +
            (f"\n{len(result['delete_failures'])} 个文件暂未删除，请检查文件占用。" if result['delete_failures'] else ''))

    def submit_selected_to_flow(self):
        ids=self.selected_segment_ids()
        if not ids:
            QMessageBox.information(self,"提交到 Flow","请先勾选已经检查完成的提示词。")
            return
        # A regenerated prompt has prompt_review_status=待检查 even if an older
        # revision already went downstream.  Never layer the new revision on top of
        # that old host chain: selected submission follows the same full-host replace
        # rule after explicit confirmation.
        tasks=[repo.get_prompt_task(sid) for sid in ids]
        host_ids=sorted({int(t['host_id']) for t in tasks if t})
        replace_hosts=[]; names=[]
        for hid in host_ids:
            info=repo.host_downstream_replacement_info(hid,work_date=work_dates.active())
            if info.get('has_downstream'):
                replace_hosts.append(hid)
                host=repo.get_host_with_recipient(hid); names.append(host['name'] if host else str(hid))
        if replace_hosts:
            if not self._confirm_host_overwrite(names): return
            submitted=deleted=0; failures=[]
            for hid in replace_hosts:
                result=repo.replace_host_prompt_submission(hid,work_date=work_dates.active())
                self._cancel_obsolete_bridge_commands(result)
                submitted+=int(result.get('submitted',0)); deleted+=int(result.get('deleted_files',0)); failures.extend(result.get('delete_failures') or [])
            normal_ids=[int(t['segment_id']) for t in tasks if t and int(t['host_id']) not in set(replace_hosts)]
            if normal_ids:
                normal=repo.submit_prompt_segments_to_flow(normal_ids)
                submitted+=int(normal.get('submitted',0))
            if submitted:self._wake_flow_scheduler()
            self.checked_ids.difference_update(ids)
            self.reload_tasks(); self._refresh_after_host_overwrite()
            extra=f'；本地旧视频已删除 {deleted} 个'
            if failures: extra+=f'；有 {len(failures)} 个旧文件删除失败，请查看运行日志'
            QMessageBox.information(self,'已覆盖重建',f'已替换 {len(replace_hosts)} 个主播的旧生产链，本次共提交 {submitted} 条{extra}。')
            return
        result=repo.submit_prompt_segments_to_flow(ids)
        if result.get('submitted'):self._wake_flow_scheduler()
        self.checked_ids.difference_update(ids)
        self.reload_tasks()
        QMessageBox.information(self,"已提交到 Flow",f"已提交 {result.get('submitted',0)} 条；跳过 {result.get('skipped',0)} 条。\nFlow 调度器会自动领取已提交任务。")

    def submit_current_host_to_flow(self):
        hid=self.host.currentData()
        if not hid:
            QMessageBox.information(self,"提交到 Flow","请先选择一个具体 AI 主播。")
            return
        rows=list(repo.list_prompt_tasks(self.recipient.currentData(),hid,"全部", work_date=work_dates.active()))
        ids=[int(r['segment_id']) for r in rows if str(r['prompt'] or '').strip() and str(r['prompt_review_status'] or '待检查')!='已提交']
        if not ids:
            QMessageBox.information(self,"提交到 Flow","当前主播没有待提交的已生成提示词。")
            return
        info=repo.host_downstream_replacement_info(hid,work_date=work_dates.active())
        if info.get('has_downstream'):
            host=repo.get_host_with_recipient(hid)
            if not self._confirm_host_overwrite([host['name'] if host else str(hid)]): return
            result=repo.replace_host_prompt_submission(hid,work_date=work_dates.active())
            self._cancel_obsolete_bridge_commands(result)
            if result.get('submitted'):self._wake_flow_scheduler()
            self.reload_tasks(); self._refresh_after_host_overwrite()
            msg=(f"当前主播旧生产链已移除，新提示词已提交 {result.get('submitted',0)} 条。\n"
                 f"已删除本地旧 Flow 视频片段 {result.get('deleted_files',0)} 个；旧云端结果晚到会自动作废。")
            if result.get('delete_failures'):
                msg+=f"\n另有 {len(result['delete_failures'])} 个旧文件未能删除，请检查文件是否被其他程序占用。"
            QMessageBox.information(self,"已覆盖重建",msg)
            return
        result=repo.submit_prompt_segments_to_flow(ids)
        if result.get('submitted'):self._wake_flow_scheduler()
        self.reload_tasks()
        QMessageBox.information(self,"已提交到 Flow",f"当前主播已提交 {result.get('submitted',0)} 条到 Flow 等待队列。")

    def withdraw_selected_from_flow(self):
        ids=self.selected_segment_ids()
        if not ids:
            QMessageBox.information(self,"撤回","请先在“已提交”工作区勾选任务。")
            return
        result=repo.withdraw_prompt_segments_from_flow(ids)
        self.checked_ids.difference_update(ids)
        self.reload_tasks()
        QMessageBox.information(self,"撤回结果",f"成功撤回 {result.get('withdrawn',0)} 条；已有 Flow 执行记录、无法安全撤回 {result.get('blocked',0)} 条。")

    def open_generation_rules(self):
        hid = self.host.currentData()
        if not hid:
            QMessageBox.information(self, "生成要求", "请先在“AI主播”筛选中选择一个具体主播。")
            return
        pending = None
        while True:
            dlg = GenerationRulesDialog(hid, self, initial_data=pending)
            result = dlg.exec()
            if result == GenerationRulesDialog.PRESETS_CHANGED:
                # Global library was saved; reopen immediately and keep unsaved host edits.
                pending = getattr(dlg, 'pending_persona', None)
                continue
            if result:
                self.reload_tasks()
            break

    def _cell_check(self, row):
        cell = self.table.cellWidget(row, 0)
        return cell if isinstance(cell, CheckCell) else None

    def on_row_check_changed(self, segment_id, checked):
        if checked:
            self.checked_ids.add(segment_id)
        else:
            self.checked_ids.discard(segment_id)
        self.update_header_check()

    def update_header_check(self):
        if not self.task_rows:
            self.table.horizontalHeaderItem(0).setText("☐")
            return
        visible_ids = [task["segment_id"] for task in self.task_rows]
        all_checked = all(sid in self.checked_ids for sid in visible_ids)
        self.table.horizontalHeaderItem(0).setText("☑" if all_checked else "☐")

    def header_clicked(self, section):
        if section != 0:
            return
        visible_ids = [task["segment_id"] for task in self.task_rows]
        all_checked = bool(visible_ids) and all(sid in self.checked_ids for sid in visible_ids)
        target = not all_checked
        for row, task in enumerate(self.task_rows):
            cell = self._cell_check(row)
            if cell:
                cell.setChecked(target, block=True)
            if target:
                self.checked_ids.add(task["segment_id"])
            else:
                self.checked_ids.discard(task["segment_id"])
        self.update_header_check()

    def select_pending_rows(self):
        for row, task in enumerate(self.task_rows):
            pending = not (task["prompt"] or "").strip()
            cell = self._cell_check(row)
            if cell:
                cell.setChecked(pending, block=True)
            if pending:
                self.checked_ids.add(task["segment_id"])
            else:
                self.checked_ids.discard(task["segment_id"])
        self.update_header_check()

    def start_fill_drag(self, source_row, state):
        self._fill_source_row = source_row
        self._fill_target_state = bool(state)

    def update_fill_drag(self, global_pos):
        if self._fill_source_row is None:
            return
        viewport_pos = self.table.viewport().mapFromGlobal(global_pos)
        target_row = self.table.rowAt(viewport_pos.y())
        if target_row < 0:
            if viewport_pos.y() < 0:
                target_row = 0
            else:
                target_row = self.table.rowCount() - 1
        lo = min(self._fill_source_row, target_row)
        hi = max(self._fill_source_row, target_row)
        for row in range(lo, hi + 1):
            if row >= len(self.task_rows):
                continue
            sid = self.task_rows[row]["segment_id"]
            cell = self._cell_check(row)
            if cell:
                cell.setChecked(self._fill_target_state, block=True)
            if self._fill_target_state:
                self.checked_ids.add(sid)
            else:
                self.checked_ids.discard(sid)
        self.update_header_check()

    def finish_fill_drag(self):
        self._fill_source_row = None
        self._fill_target_state = None

    def selected_segment_ids(self):
        return [
            task["segment_id"]
            for task in self.task_rows
            if task["segment_id"] in self.checked_ids
        ]

    def clear_selected_prompts(self):
        ids = self.selected_segment_ids()
        if not ids:
            QMessageBox.information(self, "清空提示词", "请先勾选需要清空提示词的任务。")
            return
        if not confirm_clear(
            self, "清空提示词",
            f"确认清空已选中的 {len(ids)} 条最终提示词？\n人物文案、参考图和生成规则都会保留。"
        ):
            return
        try:repo.clear_prompt_results(ids)
        except ValueError as exc:
            QMessageBox.warning(self,"保留生产记录",str(exc));return
        self.checked_ids.difference_update(ids)
        self.reload_tasks()
        QMessageBox.information(self, "清空完成", f"已清空 {len(ids)} 条提示词。")

    def batch_paste_prompts(self):
        self.local_fill_prompts(False)

    def local_fill_prompts(self, template=False):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self,'正在生成','请等待当前 GPT 批量生成结束后再填写提示词。');return
        ids=set(self.selected_segment_ids())
        tasks=[t for t in self.task_rows if not ids or t['segment_id'] in ids]
        if not tasks:
            QMessageBox.information(self,'填写提示词','当前列表没有任务。');return
        from app.ui.local_prompt_dialog import LocalPromptDialog
        dialog=LocalPromptDialog(tasks,work_dates.active(),template,self,'当前列表中勾选的任务' if ids else '当前列表全部任务')
        if dialog.exec()==QDialog.Accepted:
            self.reload_tasks();self._rebuild_host_cards()
            QMessageBox.information(self,'保存完成',f'已保存 {dialog.saved_count} 条提示词，可检查后提交到 Flow。本次未调用 GPT API。')


    def start_generation(self, mode):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "正在生成", "当前批量任务还没有结束。")
            return

        if not openai_service.get_api_key():
            QMessageBox.warning(self, "API Key", "请先点击“AI设置”保存 OpenAI API Key。")
            return

        if mode == 'checked_pending':
            # Include checked rows from other filters/hosts, but never another date.
            rows = repo.list_prompt_tasks(work_date=work_dates.active())
            ids = [t['segment_id'] for t in rows if t['segment_id'] in self.checked_ids
                   and not (t['prompt'] or '').strip() and str(t['prompt_review_status'] or '') != '已提交']
        elif mode == "selected":
            ids = self.selected_segment_ids()
            if not ids:
                selected_rows=sorted({index.row() for index in self.table.selectionModel().selectedIndexes()})
                ids=[self.task_rows[row]['segment_id'] for row in selected_rows if 0<=row<len(self.task_rows)]
        elif mode == "failed":
            ids = [t["segment_id"] for t in self.task_rows if (t["status"] or "") == "失败"]
        else:
            ids = [
                t["segment_id"] for t in self.task_rows
                if not (t["prompt"] or "").strip()
            ]

        if not ids:
            QMessageBox.information(self, "没有任务", "当前没有符合条件的待生成任务。")
            return

        selected_tasks = [repo.get_prompt_task(sid) for sid in ids]
        modes = {
            "PRAYING" if str(t["performance_mode"] or "").upper() == "PRAYING" else "TALKING"
            for t in selected_tasks if t
        }
        missing = []
        if "TALKING" in modes and not (repo.get_setting("talking_base_prompt", "") or "").strip():
            missing.append("TALKING｜睁眼说话基础模板")
        if "PRAYING" in modes and not (repo.get_setting("praying_base_prompt", "") or "").strip():
            missing.append("PRAYING｜闭眼祷告基础模板")
        if missing:
            box = QMessageBox(self)
            box.setWindowTitle("GPT 基础提示词尚未设置完整")
            box.setText("当前批次缺少：\n" + "\n".join("• " + x for x in missing))
            box.setInformativeText("请先完成基础模板设置，再进行批量生成。")
            go = box.addButton("前往", QMessageBox.AcceptRole)
            box.addButton("取消", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is go:
                w = self.window()
                if hasattr(w, "open_settings"):
                    w.open_settings()
            return

        model = repo.get_setting("openai_model", "gpt-5.6-luna")
        image_detail = repo.get_setting("image_detail", "low") or "low"
        core = repo.get_setting("core_prompt", DEFAULT_CORE_PROMPT) or DEFAULT_CORE_PROMPT

        image_requests = len({
            (task["video_id"], task["image_path"] or "")
            for task in selected_tasks if task
        })

        answer = QMessageBox.Yes if mode == 'checked_pending' else QMessageBox.question(
            self,
            "开始批量生成",
            f"即将生成 {len(ids)} 个 Flow 提示词。\n"
            f"模型：{model}\n"
            f"图像精度：{image_detail}\n"
            f"按参考图合并后只需要 {image_requests} 次 API 请求。\n\n"
            "同一张图片的多个 Flow 片段会一次发送并一次返回。\n"
            "GPT 只生成每段动态动作/镜头，并保留‘文案： ’占位；真实文案、基础模板、人物设置和固定底层限制由 Studio 本地拼接。\n"
            "这样最终 Flow 提示词仍然完整，但不会让 GPT 为每个片段重复输出相同规则。\n"
            "固定前缀仍会使用 Prompt Cache。\n\n开始吗？"
        )
        if answer != QMessageBox.Yes:
            return

        self.progress.setValue(0)
        self.header_generate.setEnabled(False)
        self.current_job.setText(f"已排队 {len(ids)} 个勾选任务，正在依次生成…")
        self.generate_empty.setEnabled(False)
        self.generate_selected.setEnabled(False)
        self.retry_failed.setEnabled(False)

        self.worker = GenerateWorker(ids, model, core, image_detail, self)
        self.worker.progress.connect(self.on_progress)
        self.worker.item_done.connect(self.on_item_done)
        self.worker.finished_summary.connect(self.on_finished)
        self.worker.finished.connect(self._release_generate_worker)
        self.worker.start()

    def _release_generate_worker(self):
        worker = self.sender()
        if self.worker is worker:
            self.worker = None
            self.header_generate.setEnabled(True)
            self.generate_empty.setEnabled(True)
            self.generate_selected.setEnabled(True)
            self.retry_failed.setEnabled(True)
        worker.deleteLater()

    def on_progress(self, current, total, task_id):
        pct = int(current / max(total, 1) * 100)
        self.progress.setValue(pct)
        self.current_job.setText(f"正在请求 {current}/{total} · 图片任务 {task_id}")

    def on_item_done(self, segment_id, ok, error):
        if not ok and error:
            self.current_job.setText("有任务失败：" + error[:180])

    def on_finished(self, ok, failed, cost, requests, input_tokens, cached_tokens, output_tokens):
        self.generate_empty.setEnabled(True)
        self.generate_selected.setEnabled(True)
        self.retry_failed.setEnabled(True)
        self.progress.setValue(100)
        attempted = int(getattr(self.worker, "attempted_requests", requests) or 0)
        last_error = str(getattr(self.worker, "last_error", "") or "").strip()
        summary = (
            f"本批完成：提示词 {ok} · 失败 {failed} · API成功 {requests} / 尝试 {attempted} · "
            f"输入 {input_tokens:,} · 缓存 {cached_tokens:,} · 输出 {output_tokens:,} · "
            f"成本约 ${cost:.4f}"
        )
        if failed and last_error:
            summary += "\n失败原因：" + last_error[:260]
        self.current_job.setText(summary)
        self.current_job.setToolTip(last_error if last_error else "")
        self.reload_tasks()

    def open_ai_settings(self):
        d = APISettingsDialog(self)
        if d.exec():
            self.refresh_api_status()

    def edit_host_rule(self):
        hid = self.host.currentData()
        if not hid:
            QMessageBox.information(self, "主播规则", "请先选择一个具体 AI 主播。")
            return
        host = next((h for h in repo.list_hosts(self.recipient.currentData(), work_date=work_dates.active()) if h["id"] == hid), None)
        if not host:
            return
        d = HostRuleDialog(hid, host["prompt_rule"] if "prompt_rule" in host.keys() else "", self)
        if d.exec():
            self.reload_tasks()

    def mark_editor_dirty(self):
        if self._editor_loading or not self.editor_segment_id:
            return
        self._editor_dirty = True
        self.editor_prompt_state.setText("● 有未保存修改")

    def _persist_inline_editor(self, show_message=False):
        if not self.editor_segment_id:
            return False
        task = repo.get_prompt_task(self.editor_segment_id)
        if not task:
            return False
        new_dialogue=' '.join(self.editor_dialogue.toPlainText().split())
        old_dialogue=' '.join(str(task["foreign_text"] or '').split())
        if new_dialogue != old_dialogue:
            repo.edit_prompt_segment_text(int(task["segment_id"]), new_dialogue)
            if not new_dialogue:
                self.editor_segment_id=None
                self.reload_tasks()
                return True
            task=repo.get_prompt_task(int(task["segment_id"]))
            if not task:
                self.editor_segment_id=None
                self.reload_tasks()
                return True
        repo.set_video_special_requirements(
            int(task["video_id"]), self.editor_image_rule.toPlainText().strip()
        )
        repo.update_segment_rule(
            int(task["segment_id"]), self.editor_segment_rule.toPlainText().strip()
        )
        repo.save_manual_prompt_result(
            int(task["segment_id"]), self.editor_final_prompt.toPlainText().strip()
        )
        self._editor_dirty = False
        self.editor_prompt_state.setText("✓ 已保存")
        if show_message:
            self.current_job.setText(
                f'✅ 已保存 {int(task["video_seq"]):02d}-{int(task["seg_seq"]):02d}'
            )
        return True

    def load_inline_editor_from_selection(self):
        rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()})
        if rows:
            self.load_inline_editor(rows[0], 0)

    def load_inline_editor(self, row, col=0):
        if row < 0 or row >= len(self.task_rows):
            return
        sid = int(self.task_rows[row]["segment_id"])
        if self.editor_segment_id and sid != int(self.editor_segment_id) and self._editor_dirty:
            # Switching tasks should never silently discard typed text.
            self._persist_inline_editor(show_message=False)

        task = repo.get_prompt_task(sid)
        if not task:
            return
        task = dict(task)
        submitted = str(task["prompt_review_status"] or "") == "已提交"
        self.editor_segment_id = sid
        self._editor_loading = True
        try:
            task_id = f'{int(task["video_seq"]):02d}-{int(task["seg_seq"]):02d}'
            self.editor_title.setText(f'快速编辑 · {task["host_name"]} / {task_id}')
            self.editor_meta.setText(
                f'接收人：{task["recipient_name"]} · 完整视频：{int(task["video_seq"]):02d} · '
                f'状态：{task["status"] or "未生成"}'
            )
            self._loaded_dialogue = ' '.join(str(task["foreign_text"] or '').split())
            self.editor_dialogue.setPlainText(task["foreign_text"] or "")
            snapshot = getattr(self, '_segment_styles', {}).get(sid)
            if snapshot and snapshot.get('text') == (task['foreign_text'] or ''):
                from app.ui.sheet_rich_text import apply
                apply(self.editor_dialogue.document(), snapshot)
            self.editor_image_rule.setPlainText(task["special_requirements"] or "")
            self.editor_segment_rule.setPlainText(task["segment_rule"] or "")
            self.editor_final_prompt.setPlainText(task["prompt"] or "")
            for editor in (self.editor_image_rule,self.editor_segment_rule,self.editor_final_prompt):
                editor.setReadOnly(False)
            self.editor_save.setEnabled(not submitted)
            self.editor_save_next.setEnabled(not submitted)
            self.editor_prompt_state.setText(("提交历史 · 可修改并重新提交" if submitted else ("✓ 已保存" if (task["prompt"] or "").strip() else "未填写")))

            image = str(task["image_path"] or "")
            set_image(self.editor_image, image)
            self._editor_dirty = False

        finally:
            self._editor_loading = False

    def reload_inline_editor(self):
        if not self.editor_segment_id:
            return
        # Explicit undo: discard only the unsaved UI state and reload DB values.
        self._editor_dirty = False
        for row, task in enumerate(self.task_rows):
            if int(task["segment_id"]) == int(self.editor_segment_id):
                self.load_inline_editor(row, 1)
                return

    def save_inline_editor(self):
        if not self.editor_segment_id:
            QMessageBox.information(self, "快速编辑", "请先单击左侧任务。")
            return
        if self._persist_inline_editor(show_message=True):
            current = int(self.editor_segment_id)
            for row, task in enumerate(self.task_rows):
                if int(task["segment_id"]) == current:
                    fresh = repo.get_prompt_task(current)
                    if fresh:
                        self.task_rows[row] = fresh
                        self.table.item(row,5).setText("已自定义" if ((fresh["special_requirements"] or "").strip() or (fresh["segment_rule"] or "").strip()) else "默认")
                        self.table.item(row,7).setText("已填" if (fresh["prompt"] or "").strip() else "未填")
                        self.table.item(row,7).setToolTip(fresh["prompt"] or "")
                    self.table.selectRow(row)
                    break

    def save_and_next(self):
        if not self.editor_segment_id:
            QMessageBox.information(self, "快速编辑", "请先单击左侧任务。")
            return
        current_row = next((i for i, t in enumerate(self.task_rows)
                            if int(t["segment_id"]) == int(self.editor_segment_id)), -1)
        if not self._persist_inline_editor(show_message=True):
            return
        self.reload_tasks()
        if self.task_rows:
            next_row = min(max(current_row + 1, 0), len(self.task_rows) - 1)
            self.table.selectRow(next_row)
            self.load_inline_editor(next_row, 0)

