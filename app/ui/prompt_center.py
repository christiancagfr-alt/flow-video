
from __future__ import annotations
from pathlib import Path
import copy
import re
import uuid

from PySide6.QtCore import Qt, QThread, Signal, QSize, QRect, QPoint, QTimer
from PySide6.QtGui import QPixmap, QIcon, QFont, QColor, QShortcut, QKeySequence
from app.ui.image_preview import set_image, set_image_async, load_pixmap
from app.ui.confirmation import confirm_clear
from app.services.image_assets import resolve_path, ImageAssetError
from PySide6.QtWidgets import (
    QInputDialog, QMenu, QLayout, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QDialog, QDialogButtonBox, QFormLayout, QPlainTextEdit, QLineEdit, QMessageBox, QProgressBar, QSplitter, QFrame, QCheckBox, QListWidget, QListWidgetItem, QGroupBox, QApplication, QButtonGroup, QTabWidget, QScrollArea, QGridLayout, QSizePolicy, QSlider
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


class HorizontalOnlyScrollArea(QScrollArea):
    """Horizontal-only scroll area that routes wheel deltas to horizontal scrolling and strictly prevents vertical scrolling."""

    def wheelEvent(self, event):
        delta = event.angleDelta().y() or event.angleDelta().x()
        if delta:
            sb = self.horizontalScrollBar()
            if sb and sb.isEnabled() and sb.maximum() > 0:
                sb.setValue(sb.value() - delta)
                event.accept()
                return
        event.ignore()


_anchor_thumb_cache: dict[int, str] = {}


def resolve_anchor_thumbnail(host_id):
    hid = int(host_id)
    cached = _anchor_thumb_cache.get(hid)
    if cached and Path(cached).exists():
        return cached
    for candidate in repo.anchor_thumbnail_candidates(hid):
        if candidate and not load_pixmap(candidate).isNull():
            path_str = str(candidate)
            _anchor_thumb_cache[hid] = path_str
            return path_str
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

    MAX_SEGMENTS_PER_GROUP = 8

    def __init__(self, segment_ids, model, core_prompt, image_detail="low", max_workers=4, preloaded_tasks=None, parent=None):
        super().__init__(parent)
        import concurrent.futures
        import queue
        import threading
        self.segment_ids = []
        self.model = model
        self.core_prompt = core_prompt
        self.image_detail = image_detail
        self.max_workers = max(1, min(8, int(max_workers or 4)))
        self._lock = threading.Lock()
        self._db_lock = threading.Lock()
        self._work_queue = queue.Queue()
        self._queued_segment_ids = set()
        self._pending_segment_ids = set()
        # Runtime diagnostics: successful API requests and actual HTTP attempts are
        # deliberately tracked separately. A failed request must never be shown as
        # “API请求 0”, which previously hid the real failure reason.
        self.attempted_requests = 0
        self.completed_requests = 0
        self.planned_requests = 0
        self.active_requests = 0
        self.ok = 0
        self.failed = 0
        self.cost = 0.0
        self.total_input = 0
        self.total_cached = 0
        self.total_output = 0
        self.last_error = ""
        if segment_ids:
            self.enqueue_segments(segment_ids, preloaded_tasks=preloaded_tasks)

    def pending_segment_ids(self) -> set[int]:
        with self._lock:
            return set(self._pending_segment_ids)

    @classmethod
    def _build_groups_for_ids(cls, segment_ids, preloaded_tasks=None):
        groups = {}
        if preloaded_tasks is not None:
            task_map = {int(t["segment_id"]): dict(t) for t in preloaded_tasks if t}
            tasks = [task_map[int(sid)] for sid in segment_ids if int(sid) in task_map]
        else:
            tasks = [dict(t) for t in repo.get_prompt_tasks_by_ids(segment_ids) if t]

        for task in tasks:
            vid = task.get("video_id")
            host_id = task.get("host_id")
            host_name = str(task.get("host_name") or "").strip()

            group_key = (host_id, vid, task.get("image_path") or "NO_IMAGE")

            if group_key not in groups:
                groups[group_key] = {
                    "image_path": task.get("image_path") or "NO_IMAGE",
                    "host_id": host_id,
                    "host_name": host_name,
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

        from app.services import broll_presets
        final_groups = []
        max_chunk = cls.MAX_SEGMENTS_PER_GROUP
        for g in groups.values():
            segs = g["segments"]
            total_len = len(segs)
            vid = int(g.get("video_id") or 0)
            enh = broll_presets.get_video_enhancement(vid) or {} if vid else {}
            keep_whole = bool(enh.get("camera_enabled") and int(enh.get("camera_limit") or 0) > 0)
            if keep_whole or total_len <= max_chunk:
                g["seg_offset"] = 0
                g["video_total_segments"] = total_len
                final_groups.append(g)
            else:
                import math
                num_chunks = math.ceil(total_len / max_chunk)
                chunk_size = math.ceil(total_len / num_chunks)
                for idx, start in enumerate(range(0, total_len, chunk_size), 1):
                    sub = dict(g)
                    sub["segments"] = segs[start:start + chunk_size]
                    sub["seg_offset"] = start
                    sub["video_total_segments"] = total_len
                    sub["chunk_index"] = idx
                    sub["chunk_total"] = num_chunks
                    final_groups.append(sub)
        return final_groups

    def enqueue_segments(self, segment_ids, preloaded_tasks=None) -> tuple[int, int]:
        with self._lock:
            new_ids = []
            for sid in segment_ids or []:
                sid_int = int(sid)
                if sid_int not in self._queued_segment_ids:
                    self._queued_segment_ids.add(sid_int)
                    self._pending_segment_ids.add(sid_int)
                    self.segment_ids.append(sid_int)
                    new_ids.append(sid_int)
        if not new_ids:
            return 0, 0
        groups = self._build_groups_for_ids(new_ids, preloaded_tasks=preloaded_tasks)
        if not groups:
            with self._lock:
                for sid_int in new_ids:
                    self._pending_segment_ids.discard(sid_int)
            return 0, 0
        with self._lock:
            self.planned_requests += len(groups)
            for group in groups:
                host_prefix = f'{group.get("host_name")} · ' if group.get("host_name") else ""
                chunk_tag = (
                    f' ({group["chunk_index"]}/{group["chunk_total"]})'
                    if int(group.get("chunk_total") or 1) > 1 else ""
                )
                label = f'{host_prefix}视频{group["video_seq"]:02d}{chunk_tag} · {len(group["segments"])} 个片段'
                self._work_queue.put((group, label, True))
        return len(new_ids), len(groups)

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

    def _emit_live_progress(self, label: str = ""):
        with self._lock:
            comp = self.completed_requests
            plan = max(self.planned_requests, comp, 1)
            active = self.active_requests
            pending_segs = len(self._pending_segment_ids)
        status = f"运行中 {active} · 待完成片段 {pending_segs}"
        if label:
            status += f" · {label}"
        self.progress.emit(comp, plan, status)

    def _run_queue(self):
        import concurrent.futures

        def prepare_group(group):
            import json
            from app.core.persona import active_camera_catalog, active_camera_pool, rule_text, active_action_presets, normalize
            from app.services import flow_master_v8
            if (repo.get_setting(flow_master_v8.SETTING_KEY, flow_master_v8.SOURCE_PERSONA) or "") == flow_master_v8.SOURCE:
                return flow_master_v8.configure_group(group)

            segments = group.get("segments", [])
            modes_present = set(str(s.get("performance_mode") or "").upper() == "PRAYING" and "PRAYING" or "TALKING" for s in segments)

            combined_host_rules = []
            combined_action_presets = {}
            combined_camera_presets = {}
            auto_action = True

            for m in sorted(list(modes_present)):
                persona_raw = repo.get_setting(f"host_persona_{int(group.get('host_id') or 0)}_{m.lower()}", "")
                persona = normalize(json.loads(persona_raw) if persona_raw else {}, m)

                hr = rule_text(persona, m)
                combined_host_rules.append(f"对于 {m} 片段，请遵守以下人物设定：\n{hr}")

                if not persona.get('auto_action_match', True):
                    auto_action = False

                for ap in active_action_presets(persona, mode=m):
                    combined_action_presets[ap['id']] = ap
                for cp in active_camera_catalog(persona, mode=m):
                    combined_camera_presets[cp['id']] = cp

            group['host_rule'] = "\n\n".join(combined_host_rules)
            group['auto_action_match'] = auto_action
            group['action_presets'] = list(combined_action_presets.values())
            group['camera_presets'] = list(combined_camera_presets.values())

            effective_core = self.core_prompt.strip()
            return effective_core

        def save_result(result):
            with self._db_lock:
                repo.save_prompt_batch_results(
                    result["prompts"], self.model,
                    result["input_tokens"], result["cached_tokens"],
                    result["output_tokens"], result["cost_usd"],
                    original_prompt_map=result.get("ai_prompts") or {},
                )
            with self._lock:
                group_ok = len(result["prompts"])
                self.ok += group_ok
                self.cost += result["cost_usd"]
                self.total_input += result["input_tokens"]
                self.total_cached += result["cached_tokens"]
                self.total_output += result["output_tokens"]
                self.completed_requests += 1
                for sid in result["prompts"]:
                    self._pending_segment_ids.discard(int(sid))
            for sid in result["prompts"]:
                self.item_done.emit(int(sid), True, "")

        def request_group(group, label, allow_fallback=True):
            with self._lock:
                self.active_requests += 1
            self._emit_live_progress(label)
            try:
                with self._db_lock:
                    effective_core = prepare_group(group)
                segments = list(group.get("segments") or [])
                request_timeout = max(180, min(480, 180 + 5 * len(segments)))

                def note_request(_meta=None):
                    with self._lock:
                        self.attempted_requests += 1

                from app.services import broll_presets
                from app.services import flow_master_v8
                with self._db_lock:
                    config = broll_presets.get_video_enhancement(int(group.get('video_id') or 0)) or {}
                if group.get("instruction_source") != flow_master_v8.SOURCE and config.get('camera_enabled') and int(config.get('camera_limit') or 0) > 0:
                    result = openai_service.generate_enhanced_prompts(
                        model=self.model, core_prompt=effective_core, group=group,
                        config=config, preset_snapshot={}, image_detail=self.image_detail,
                        timeout=request_timeout, on_request=note_request,
                    )
                    plan = result['data']
                    with self._db_lock:
                        broll_presets.save_video_plan(str(group['video_id']), plan['VIDEO_PLAN'], plan.get('IMAGE_PLAN') or [], [], config)
                        repo.create_image_plan_segments(int(group['video_id']), plan.get('IMAGE_PLAN') or [], self.model)
                else:
                    result = openai_service.generate_prompts_for_image(
                        model=self.model, core_prompt=effective_core, group=group,
                        image_detail=self.image_detail, timeout=request_timeout, on_request=note_request,
                    )
                save_result(result)
                return
            except Exception as exc:
                segments = list(group.get("segments") or [])
                with self._lock:
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
                if allow_fallback and len(segments) >= 16 and self._large_batch_retryable(exc):
                    midpoint = (len(segments) + 1) // 2
                    halves = [segments[:midpoint], segments[midpoint:]]
                    host_prefix = f'{group.get("host_name")} · ' if group.get("host_name") else ""
                    with self._lock:
                        self.planned_requests += 1
                        for i, half in enumerate(halves, 1):
                            sub = dict(group)
                            sub["segments"] = half
                            sub_label = f'{host_prefix}视频{group["video_seq"]:02d} · 自动降级 {i}/2 ({len(half)}段)'
                            self._work_queue.put((sub, sub_label, False))
                    return
                with self._db_lock:
                    for seg in segments:
                        repo.mark_prompt_failed(int(seg["segment_id"]), self.model)
                with self._lock:
                    self.completed_requests += 1
                    for seg in segments:
                        sid_int = int(seg["segment_id"])
                        self._pending_segment_ids.discard(sid_int)
                        self.failed += 1
                for seg in segments:
                    self.item_done.emit(int(seg["segment_id"]), False, str(exc))
            finally:
                with self._lock:
                    self.active_requests = max(0, self.active_requests - 1)
                self._emit_live_progress(label)

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = set()
            while True:
                while not self._work_queue.empty():
                    try:
                        group, label, allow_fallback = self._work_queue.get_nowait()
                    except Exception:
                        break
                    futures.add(executor.submit(request_group, group, label, allow_fallback))
                if not futures and self._work_queue.empty():
                    break
                done, futures = concurrent.futures.wait(
                    futures, timeout=0.15, return_when=concurrent.futures.FIRST_COMPLETED
                )

        self.finished_summary.emit(
            self.ok, self.failed, self.cost, self.completed_requests,
            self.total_input, self.total_cached, self.total_output
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


class _CenterJobLabel(QLabel):
    """Status label that drives the inline live progress & completion banner inside pcActionBar."""

    def __init__(self, text: str = "", owner=None, objectName: str = "pcCenterJobText"):
        super().__init__(text, objectName=objectName)
        self._owner = owner

    def minimumSizeHint(self):
        sh = super().minimumSizeHint()
        return QSize(60, sh.height())

    def paintEvent(self, event):
        txt = self.text()
        rect = self.contentsRect()
        fm = self.fontMetrics()
        if txt and rect.width() > 8 and fm.horizontalAdvance(txt) > rect.width():
            from PySide6.QtGui import QPainter
            painter = QPainter(self)
            painter.setFont(self.font())
            painter.setPen(self.palette().color(self.foregroundRole()))
            elided = fm.elidedText(txt, Qt.ElideRight, rect.width())
            painter.drawText(rect, int(Qt.AlignLeft | Qt.AlignVCenter), elided)
            painter.end()
            return
        super().paintEvent(event)

    def setText(self, text: str):
        super().setText(text)
        clean = (text or "").strip()
        super().setToolTip(clean if (clean and clean != "就绪") else "")
        if self._owner is not None:
            self._owner._sync_center_job_banner(text)


class _CenterProgressBar(QProgressBar):
    """Progress bar inside the centered status banner that keeps its container & % label synced."""

    def __init__(self, owner=None, objectName: str = "pcCenterProgress"):
        super().__init__(objectName=objectName)
        self._owner = owner

    def setValue(self, value: int):
        super().setValue(value)
        if self._owner is not None:
            self._owner._sync_center_progress_ui()

    def setRange(self, minimum: int, maximum: int):
        super().setRange(minimum, maximum)
        if self._owner is not None:
            self._owner._sync_center_progress_ui()

    def setVisible(self, visible: bool):
        super().setVisible(visible)
        if self._owner is not None:
            self._owner._sync_center_progress_visibility(bool(visible))


class _ClickableThumbLabel(QLabel):
    """Reference-image thumbnail frame that opens a high-resolution preview dialog on click."""

    clicked = Signal()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class _AdaptiveEditorImage(QFrame):
    """Responsive high-DPI studio preview frame that scales the reference image to fill available panel space."""

    clicked = Signal()

    def __init__(self, placeholder: str = "参考图\n(单击左侧任务预览)"):
        super().__init__(objectName="pcEditorThumb")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(144, 150)
        self._qimg = None
        self._placeholder = placeholder
        self._hovered = False
        self._resizing = False
        self._fast_pix = None
        self._settled_pix = None
        self._settled_key = None
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.timeout.connect(self._on_resize_settled)

    def _invalidate_scaled_cache(self):
        self._fast_pix = None
        self._settled_pix = None
        self._settled_key = None

    def set_qimage(self, qimg, placeholder: str | None = None):
        self._qimg = qimg if (qimg is not None and not qimg.isNull()) else None
        self._invalidate_scaled_cache()
        if placeholder is not None:
            self._placeholder = placeholder
        self.update()

    def setPixmap(self, pixmap: QPixmap):
        if pixmap is None or pixmap.isNull():
            self._qimg = None
        else:
            self._qimg = pixmap.toImage()
        self._invalidate_scaled_cache()
        self.update()

    def setText(self, text: str):
        if text:
            self._placeholder = text
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if (
            self._qimg is not None
            and not self._qimg.isNull()
            and event.oldSize().isValid()
            and event.size() != event.oldSize()
        ):
            self._resizing = True
            self._settle_timer.start(85)

    def _on_resize_settled(self):
        if self._resizing:
            self._resizing = False
            self.update()

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QPainter, QPainterPath
        r = self.contentsRect().adjusted(5, 5, -5, -5)
        if r.width() <= 8 or r.height() <= 8:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        if self._qimg is None or self._qimg.isNull():
            painter.setPen(self.palette().color(self.foregroundRole()))
            f = painter.font()
            f.setPointSize(12)
            f.setBold(True)
            painter.setFont(f)
            painter.drawText(r, Qt.AlignCenter, self._placeholder)
            painter.end()
            return

        iw, ih = max(1, self._qimg.width()), max(1, self._qimg.height())
        scale = min(r.width() / iw, r.height() / ih)
        dw, dh = iw * scale, ih * scale
        dx = r.x() + (r.width() - dw) / 2.0
        dy = r.y() + (r.height() - dh) / 2.0
        target = QRectF(dx, dy, dw, dh)

        clip = QPainterPath()
        clip.addRoundedRect(target, 7.0, 7.0)
        painter.save()
        painter.setClipPath(clip)
        if self._resizing:
            if self._fast_pix is None:
                if max(iw, ih) > 560:
                    fast_img = self._qimg.scaled(560, 560, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                else:
                    fast_img = self._qimg
                self._fast_pix = QPixmap.fromImage(fast_img)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
            painter.drawPixmap(target, self._fast_pix, QRectF(0, 0, self._fast_pix.width(), self._fast_pix.height()))
        else:
            dpr = max(1.0, float(self.devicePixelRatioF() or 1.0))
            pw, ph = max(1, round(dw * dpr)), max(1, round(dh * dpr))
            skey = (id(self._qimg), pw, ph)
            if self._settled_pix is None or self._settled_key != skey:
                scaled_img = self._qimg.scaled(pw, ph, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                self._settled_pix = QPixmap.fromImage(scaled_img)
                self._settled_key = skey
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            painter.drawPixmap(target, self._settled_pix, QRectF(0, 0, self._settled_pix.width(), self._settled_pix.height()))
        painter.restore()

        if dw >= 86 and dh >= 48:
            bw, bh = 74.0, 21.0
            badge = QRectF(target.right() - bw - 6.0, target.bottom() - bh - 6.0, bw, bh)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(37, 99, 235, 220) if self._hovered else QColor(15, 23, 42, 150))
            painter.drawRoundedRect(badge, 6.0, 6.0)
            painter.setPen(QColor("#FFFFFF"))
            bf = painter.font()
            bf.setPointSize(10)
            bf.setBold(True)
            painter.setFont(bf)
            painter.drawText(badge, Qt.AlignCenter, "🔍 点击放大")
        painter.end()


class _ClickableHostCard(QFrame):
    """Host card container where clicking anywhere outside child buttons selects the host."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, objectName="hostCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        self._press_inside = False

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self._press_inside = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        was_pressed = self._press_inside
        self._press_inside = False
        if was_pressed and event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class _SinglePillModeToggle(GenerationModeToggle):
    """Compact single-pill FRAME / MATERIAL / Omini toggle for the GPT task table."""

    def __init__(self, mode="FRAME", parent=None, video_model=""):
        QWidget.__init__(self, parent)
        self._mode = "FRAME"
        self._video_model = ""
        self._compact = True
        self._block = False
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addStretch(1)
        self.pill_btn = QPushButton("帧", objectName="pcModePill")
        self.pill_btn.setCursor(Qt.PointingHandCursor)
        self.pill_btn.setFixedWidth(56)
        self.pill_btn.clicked.connect(self._on_pill_clicked)
        row.addWidget(self.pill_btn)
        row.addStretch(1)
        # Keep dummy handles in case any external helper inspects them.
        self.frame_btn = self.pill_btn
        self.material_btn = self.pill_btn
        self.setMode(mode, emit=False, video_model=video_model)

    def _on_pill_clicked(self):
        if self.is_omini(self._video_model):
            self.setMode("FRAME", emit=True, video_model="", force_emit=True)
            return
        next_mode = "MATERIAL" if self._mode == "FRAME" else "FRAME"
        self.setMode(next_mode, emit=True, video_model="")

    def _refresh_visuals(self):
        if self.is_omini(self._video_model):
            state = "omini"
            text = "Omini"
            tip = "当前：Omini 模型（默认 8 秒）· 点击切回帧模式"
        elif self._mode == "MATERIAL":
            state = "material"
            text = "素材"
            tip = "当前：素材模式 · 点击切换为帧模式"
        else:
            state = "frame"
            text = "帧"
            tip = "当前：帧模式 · 点击切换为素材模式"
        self.pill_btn.setText(text)
        if self.pill_btn.property("modeState") != state:
            self.pill_btn.setProperty("modeState", state)
            self.pill_btn.style().unpolish(self.pill_btn)
            self.pill_btn.style().polish(self.pill_btn)
        self.setToolTip(tip)
        self.pill_btn.setToolTip(tip)

    def setMode(self, mode, emit=False, video_model=None, force_emit=False):
        mode = self.normalize(mode)
        changed = mode != self._mode
        self._mode = mode
        if video_model is not None:
            new_vm = "flow_omni" if self.is_omini(video_model) else ""
            if new_vm != self._video_model:
                changed = True
            self._video_model = new_vm
        self._refresh_visuals()
        if emit and (changed or force_emit) and not self._block:
            self.modeChanged.emit(mode)


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
        self._editor_prompt_full_mode = False
        self._editor_prompt_suffix_body = ""
        self._current_editor_image_path = ""
        self._image_preview_cache = {}
        self._copy_undo_stacks: dict[tuple[str, int], list[dict]] = {}
        self._copy_redo_stacks: dict[tuple[str, int], list[dict]] = {}
        self.build()
        self.reload_filters()

    @staticmethod
    def _set_prop(widget, name, value):
        if widget is None:
            return
        widget.setProperty(name, value)
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def build(self):
        # The prompt center is a dense production workspace. Keep the entire page inside
        # a real scroll area so shrinking the main window never makes controls overlap
        # or disappear. This is UI-only and does not change task/data behavior.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.page_content = QWidget(objectName="promptPageContent")
        self.page_content.setMinimumSize(0, 0)
        self.page_content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(self.page_content)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(6)
        outer.addWidget(self.page_content, 1)

        # ── 1. Header: title + model chip on the left; 4 stat chips + AI settings on the right ──
        # Button hierarchy on this page:
        #   L1 = solid blue (generate) / solid green (submit), only ONE prominent action per area
        #   L2 = white with coloured outline, secondary action of an area
        #   L3 = light grey tool buttons
        #   L4 = low-frequency / destructive actions live in ▾ menus, right-click menu or selection bar
        top = QHBoxLayout()
        top.setSpacing(8)
        title = QLabel("GPT 提示词中心")
        title.setStyleSheet("font-size:21px;font-weight:800;")
        top.addWidget(title)
        self.api_status = QLabel("", objectName="tcChip")
        self.api_status.setProperty("tone", "info")
        top.addWidget(self.api_status)
        self.cost_label = QLabel("💰 今日累计 $0.0000", objectName="pcCostChip")
        top.addWidget(self.cost_label)
        top.addStretch(1)

        # Backwards-compatible raw number labels (never shown)
        self.stat_hosts = QLabel("0"); self.stat_hosts.hide()
        self.stat_pending = QLabel("0"); self.stat_pending.hide()
        self.stat_generated = QLabel("0"); self.stat_generated.hide()
        self.stat_failed = QLabel("0"); self.stat_failed.hide()
        self.stat_hosts_chip = QLabel("主播 0", objectName="tcStatChip"); self.stat_hosts_chip.hide()

        self.stat_pending_chip = QLabel("0 待生成", objectName="tcStatChip")
        self.stat_generated_chip = QLabel("✓ 0 已生成", objectName="tcStatChip")
        self.stat_submitted_chip = QLabel("🚀 0 已提交", objectName="tcStatChip")
        self.stat_failed_chip = QLabel("⚠ 0 失败", objectName="tcStatChip")
        for chip in (self.stat_pending_chip, self.stat_generated_chip, self.stat_submitted_chip, self.stat_failed_chip):
            top.addWidget(chip)

        ai_settings = self._pc_button("⚙ AI设置", "l3", 34, "模型、图像精度、API Key 与核心规则设置")
        ai_settings.clicked.connect(self.open_ai_settings)
        top.addWidget(ai_settings)
        layout.addLayout(top)

        # ── 2. Step guide (kept hidden for backwards compatibility; UI uses clean workspace bar) ──
        self.guide_card = QFrame(self, objectName="tcGuide")
        gv = QVBoxLayout(self.guide_card)
        gv.setContentsMargins(12, 7, 12, 7)
        gv.setSpacing(4)
        guide_row = QHBoxLayout()
        guide_row.setSpacing(6)
        self.step_labels = []
        for idx, step_text in enumerate(("① 选主播 / 整理时长", "② 生成提示词", "③ 检查并提交 Flow")):
            if idx:
                guide_row.addWidget(QLabel("›", objectName="tcArrow"))
            slab = QLabel(step_text, objectName="tcStep")
            slab.setProperty("state", "todo")
            self.step_labels.append(slab)
            guide_row.addWidget(slab)
        guide_row.addWidget(QFrame(objectName="pcDividerV"))
        self.guide_hint = QLabel("", objectName="tcGuideHint")
        self.guide_hint.setWordWrap(False)
        guide_row.addWidget(self.guide_hint, 1)
        gv.addLayout(guide_row)
        self.guide_card.hide()

        self.task_count = QLabel("任务：0"); self.task_count.hide()
        self.request_count = QLabel("预计请求：0"); self.request_count.hide()
        self.generated_count = QLabel("已生成：0"); self.generated_count.hide()
        self.input_label = QLabel("输入：0"); self.input_label.hide()
        self.cache_label = QLabel("缓存：0"); self.cache_label.hide()
        self.output_label = QLabel("输出：0"); self.output_label.hide()

        # ── 3. Recipient & AI host navigator (hidden entirely when there is nothing to pick) ──
        self.nav_card = QFrame(objectName="pcNavCard")
        nav_v = QVBoxLayout(self.nav_card)
        nav_v.setContentsMargins(10, 6, 10, 6)
        nav_v.setSpacing(5)
        self.nav_empty_bar = QLabel("", objectName="pcEmptyNav")
        self.nav_empty_bar.hide()
        nav_v.addWidget(self.nav_empty_bar)

        self.recipient_row_widget = QWidget()
        rec_row = QHBoxLayout(self.recipient_row_widget)
        rec_row.setContentsMargins(0, 0, 0, 0)
        rec_row.setSpacing(8)
        rec_row.addWidget(QLabel("接收人", objectName="pcGroupLabel"))
        self.recipient_scroll = QScrollArea(objectName="cardScroll")
        self.recipient_scroll.setWidgetResizable(True)
        self.recipient_scroll.setFrameShape(QFrame.NoFrame)
        self.recipient_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.recipient_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.recipient_scroll.setFixedHeight(36)
        self.recipient_card_content = QWidget(objectName="scrollContent")
        self.recipient_cards = QHBoxLayout(self.recipient_card_content)
        self.recipient_cards.setContentsMargins(0, 0, 0, 0)
        self.recipient_cards.setSpacing(8)
        self.recipient_cards.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.recipient_scroll.setWidget(self.recipient_card_content)
        rec_row.addWidget(self.recipient_scroll, 1)
        self.host_section_title = QLabel("AI 主播", objectName="pcGroupLabel")
        rec_row.addWidget(self.host_section_title)
        nav_v.addWidget(self.recipient_row_widget)

        self.host_scroll = HorizontalOnlyScrollArea(objectName="cardScroll")
        self.host_scroll.setWidgetResizable(True)
        self.host_scroll.setFrameShape(QFrame.NoFrame)
        self.host_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.host_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.host_scroll.setFixedHeight(98)
        self.host_card_content = QWidget(objectName="scrollContent")
        self.host_cards = QHBoxLayout(self.host_card_content)
        self.host_cards.setContentsMargins(0, 0, 0, 0)
        self.host_cards.setSpacing(9)
        self.host_cards.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.host_scroll.setWidget(self.host_card_content)
        nav_v.addWidget(self.host_scroll)
        layout.addWidget(self.nav_card)

        # ── 4. Control bar (two rows, nothing collapsed) ──
        #   Row 1: filters on the left · "作用于…" scope chip on the right
        #   Row 2: 生成 group · 提交 group — every button visible; labels carry the count they act on
        filters = QFrame(objectName="pcActionBar")
        filters.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        fv = QVBoxLayout(filters)
        fv.setContentsMargins(12, 8, 12, 8)
        fv.setSpacing(8)
        f = QHBoxLayout()
        f.setSpacing(8)
        fv.addLayout(f)

        self.recipient = CleanComboBox(); self.recipient.hide()
        self.recipient.currentIndexChanged.connect(self.recipient_changed)
        self.host = CleanComboBox(); self.host.hide()
        self.host.currentIndexChanged.connect(self.host_changed)

        # Workspace: segmented toggle; the hidden combo stays the single source of truth.
        self.review_filter = CleanComboBox(); self.review_filter.hide()
        self.review_filter.addItems(["当前任务", "提交历史"])
        self.review_filter.currentIndexChanged.connect(self.reload_tasks)
        self.ws_current_btn = self._pc_seg_button("当前任务", "left")
        self.ws_history_btn = self._pc_seg_button("提交历史", "right")
        self.ws_current_btn.setChecked(True)
        self._ws_group = QButtonGroup(self)
        self._ws_group.setExclusive(True)
        self._ws_group.addButton(self.ws_current_btn, 0)
        self._ws_group.addButton(self.ws_history_btn, 1)
        self.ws_current_btn.clicked.connect(lambda: self.review_filter.setCurrentIndex(0))
        self.ws_history_btn.clicked.connect(lambda: self.review_filter.setCurrentIndex(1))
        f.addWidget(QLabel("工作区", objectName="pcGroupLabel"))
        ws_box = QWidget(); ws_l = QHBoxLayout(ws_box); ws_l.setContentsMargins(0, 0, 0, 0); ws_l.setSpacing(0)
        ws_l.addWidget(self.ws_current_btn); ws_l.addWidget(self.ws_history_btn)
        f.addWidget(ws_box)

        # Hidden status_filter handle kept at "全部" so reload_tasks() stays 100% compatible.
        self.status_filter = CleanComboBox(self)
        self.status_filter.addItems(["全部", "未生成", "已生成", "已自定义", "失败"])
        self.status_filter.currentIndexChanged.connect(self.reload_tasks)
        self.status_filter.hide()

        f.addWidget(QFrame(objectName="pcDividerV"))
        self._build_prompt_source_bar(f)
        f.addStretch(1)
        self.scope_label = QLabel("", objectName="pcScope")
        f.addWidget(self.scope_label)
        self.scope_clear_btn = QPushButton("✕ 取消勾选", objectName="pcLink")
        self.scope_clear_btn.setCursor(Qt.PointingHandCursor)
        self.scope_clear_btn.clicked.connect(self._clear_all_checks)
        self.scope_clear_btn.hide()
        f.addWidget(self.scope_clear_btn)

        a = QHBoxLayout()
        a.setSpacing(8)
        fv.addLayout(a)

        # Primary generate & submit actions + clean "更多 ▾" menu for low-frequency batch tools
        self.header_generate = self._pc_button(
            "✨ GPT 生成", "l1blue", 36,
            "仅针对当前选中 AI 主播进行多通道并行生成：有勾选时只生成勾选项，否则只生成当前主播列表中未填写/文案已改/失败的任务（绝不会生成其他主播）。\n"
            "正在生成时若需同时跑另一个主播，可手动切换到该主播后再点追加。"
        )
        self.header_generate.setMinimumWidth(148)
        self.header_generate.clicked.connect(lambda: self.start_generation("checked_pending"))
        a.addWidget(self.header_generate)

        self.retry_failed = self._pc_button("↻ 重试失败", "l3danger", 34, "只重新生成当前列表里生成失败的任务（有失败时才出现）")
        self.retry_failed.clicked.connect(lambda: self.start_generation("failed"))
        a.addWidget(self.retry_failed)

        self.submit_host = self._pc_button(
            "🚀 提交到 Flow", "l1green", 36,
            "有勾选：提交勾选项；没勾选：提交当前主播全部已填写、未提交的任务。"
        )
        self.submit_host.setMinimumWidth(164)
        self.submit_host.clicked.connect(self._primary_submit)
        a.addWidget(self.submit_host)

        self.resubmit_selected = self._pc_button("🔁 重新提交选中", "l1green", 36, "仅替换勾选片段：旧批次作废，使用当前已保存提示词重新排队。")
        self.resubmit_selected.clicked.connect(self.resubmit_selected_to_flow)
        a.addWidget(self.resubmit_selected)

        self.withdraw_flow = self._pc_button(
            "⚠️ 撤回 Flow 排队", "l3danger", 35,
            "⚠️ 高危操作：将勾选的已提交任务从 Flow 等待队列中撤回，退回至「当前任务（未提交）」列表，停止排队生成。\n点击后会弹出确认提示（已在 Flow 执行中或已完成的片段会自动保护跳过）。"
        )
        self.withdraw_flow.clicked.connect(self.withdraw_selected_from_flow)
        a.addWidget(self.withdraw_flow)

        # Low-frequency tools kept alive as hidden buttons + exposed via clean "更多 ▾" menu
        self.template_prompts_btn = self._pc_button("📄 模板套用", "l3", 34, "用本地通用模板填写提示词（不调用 API）：有勾选时只填勾选项，否则填当前列表全部")
        self.template_prompts_btn.setParent(self)
        self.template_prompts_btn.clicked.connect(lambda: self.local_fill_prompts(True))
        self.template_prompts_btn.hide()
        self.paste_prompts_btn = self._pc_button("✍ 手动填写", "l3", 34, "手动批量粘贴提示词（不调用 API）：有勾选时只填勾选项，否则填当前列表全部")
        self.paste_prompts_btn.setParent(self)
        self.paste_prompts_btn.clicked.connect(self.batch_paste_prompts)
        self.paste_prompts_btn.hide()
        self.clear_prompts_btn = self._pc_button("🧹 清空提示词", "l3danger", 34, "只清空勾选任务的最终提示词，文案/图片/规则都保留（需要先勾选）")
        self.clear_prompts_btn.setParent(self)
        self.clear_prompts_btn.clicked.connect(self.clear_selected_prompts)
        self.clear_prompts_btn.hide()

        self.more_prompt_ops_btn = self._pc_button(
            "更多 ▾", "l3", 34,
            "低频批量操作：通用模板套用、手动批量粘贴提示词、清空选中提示词"
        )
        self.more_prompt_ops_btn.clicked.connect(self._open_more_prompt_ops_menu)
        a.addWidget(self.more_prompt_ops_btn)

        # Inline live processing progress & completion feedback capsule inside pcActionBar Row 2
        self.job_banner_wrap = QWidget(objectName="pcCenterStatusWrap")
        self.job_banner_wrap.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        job_wrap_row = QHBoxLayout(self.job_banner_wrap)
        job_wrap_row.setContentsMargins(10, 0, 0, 0)
        job_wrap_row.setSpacing(0)

        self.job_banner = QFrame(objectName="pcCenterStatusCard")
        self.job_banner.setProperty("tone", "info")
        self.job_banner.setProperty("flash", "false")
        self.job_banner.setMinimumWidth(260)
        self.job_banner.setMaximumWidth(1180)
        self.job_banner.setFixedHeight(36)
        self.job_banner.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        jb_row = QHBoxLayout(self.job_banner)
        jb_row.setContentsMargins(10, 3, 8, 3)
        jb_row.setSpacing(8)

        self.job_state_badge = QLabel("处理完成", objectName="pcCenterStateBadge")
        self.job_state_badge.setAlignment(Qt.AlignCenter)
        self.job_state_badge.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        jb_row.addWidget(self.job_state_badge)

        self.current_job = _CenterJobLabel("", owner=None, objectName="pcCenterJobText")
        self.current_job.setWordWrap(False)
        self.current_job.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        jb_row.addWidget(self.current_job, 1)

        self.progress_box = QWidget(objectName="pcCenterProgressBox")
        pb_row = QHBoxLayout(self.progress_box)
        pb_row.setContentsMargins(2, 0, 2, 0)
        pb_row.setSpacing(6)
        self.progress = _CenterProgressBar(owner=None, objectName="pcCenterProgress")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedSize(160, 8)
        self.progress_pct_label = QLabel("0%", objectName="pcCenterProgressPct")
        self.progress_pct_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.progress_pct_label.setMinimumWidth(36)
        pb_row.addWidget(self.progress)
        pb_row.addWidget(self.progress_pct_label)
        self.progress.hide()
        self.progress_box.hide()
        jb_row.addWidget(self.progress_box)

        self.job_time_label = QLabel("", objectName="pcCenterTimeLabel")
        self.job_time_label.hide()
        jb_row.addWidget(self.job_time_label)

        self.job_dismiss_btn = QPushButton("✕", objectName="pcCenterDismissBtn")
        self.job_dismiss_btn.setCursor(Qt.PointingHandCursor)
        self.job_dismiss_btn.setFixedSize(20, 20)
        self.job_dismiss_btn.setToolTip("收起当前状态提示")
        self.job_dismiss_btn.clicked.connect(self._dismiss_center_job_banner)
        jb_row.addWidget(self.job_dismiss_btn)

        job_wrap_row.addWidget(self.job_banner)
        self.job_banner_wrap.hide()
        a.addWidget(self.job_banner_wrap)
        a.addStretch(1)

        # Legacy handles kept so every original attribute / slot still exists.
        self.generate_empty = QPushButton("批量生成未填"); self.generate_empty.clicked.connect(lambda: self.start_generation("empty"))
        self.generate_selected = QPushButton("重试选中项"); self.generate_selected.clicked.connect(lambda: self.start_generation("selected"))
        self.submit_flow = QPushButton("提交选中项到 Flow"); self.submit_flow.clicked.connect(self.submit_selected_to_flow)

        filter_scroll = HorizontalOnlyScrollArea()
        filter_scroll.setObjectName("filterScrollArea")
        filter_scroll.setWidgetResizable(True)
        filter_scroll.setFrameShape(QFrame.NoFrame)
        filter_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        filter_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        filter_scroll.verticalScrollBar().setEnabled(False)
        filter_scroll.verticalScrollBar().setRange(0, 0)
        filters.setFixedHeight(96)
        filter_scroll.setFixedHeight(102)
        filter_scroll.setWidget(filters)
        layout.addWidget(filter_scroll)

        self._progress_hide_timer = QTimer(self)
        self._progress_hide_timer.setSingleShot(True)
        self._progress_hide_timer.timeout.connect(self._hide_progress_if_idle)
        self._banner_flash_timer = QTimer(self)
        self._banner_flash_timer.setSingleShot(True)
        self._banner_flash_timer.timeout.connect(self._clear_banner_flash)
        self.progress._owner = self
        self.current_job._owner = self
        self.current_job.setText("就绪")

        self.table = QTableWidget(objectName="promptTaskTable")
        # V0.12.6+: compact task navigator with single-pill toggles and status dot indicators.
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels([
            "☐", "任务ID", "参考图", "类型", "文案", "时长", "模式", "提示词", "成本"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(False)
        self.table.setWordWrap(True)
        self.table.verticalHeader().setVisible(False)
        # Keep a comfortable compact row height for 13pt copy text.
        self.table.verticalHeader().setDefaultSectionSize(84)
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
        self.table.setColumnWidth(0, 48)
        self.table.setColumnWidth(1, 70)
        self.table.setColumnWidth(2, 118)
        self.table.setColumnWidth(3, 76)
        self.table.setColumnWidth(5, 68)
        self.table.setColumnWidth(6, 72)
        self.table.setColumnWidth(7, 58)
        self.table.setColumnWidth(8, 76)
        # Reference image and API cost live in the right-hand detail area / history;
        # Column 5 is visible right beside the copy to show estimated speech duration.
        self.table.setColumnHidden(2, True)
        self.table.setColumnHidden(5, False)
        self.table.setColumnHidden(8, True)

        self._shift_anchor_row = None
        self._last_table_press_modifiers = Qt.NoModifier
        self._hydrated_rows = set()
        self._table_hydrate_timer = QTimer(self)
        self._table_hydrate_timer.setSingleShot(True)
        self._table_hydrate_timer.timeout.connect(self._hydrate_visible_table_widgets)
        self.table.viewport().installEventFilter(self)
        self.table.verticalScrollBar().valueChanged.connect(lambda *_: self._hydrate_visible_table_widgets())
        self.table.verticalScrollBar().rangeChanged.connect(lambda *_: self._hydrate_visible_table_widgets())
        self.table.cellClicked.connect(self._on_table_cell_clicked)
        self.table.itemSelectionChanged.connect(self.load_inline_editor_from_selection)
        self.table.horizontalHeader().sectionClicked.connect(self.header_clicked)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_table_context_menu)

        # ── 5. Workspace: task list (left) + quick editor (right) ──
        split = QSplitter(Qt.Horizontal, objectName="pcWorkspaceSplitter")
        split.setChildrenCollapsible(False)
        split.setHandleWidth(8)

        task_card = QFrame(objectName="workspacePanel")
        task_v = QVBoxLayout(task_card)
        task_v.setContentsMargins(12, 10, 12, 10)
        task_v.setSpacing(8)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)
        self.task_panel_title = QLabel("文案列表", objectName="workspaceTitle")
        title_row.addWidget(self.task_panel_title)
        self.table_summary_badge = QLabel("", objectName="tcChip")
        title_row.addWidget(self.table_summary_badge)

        self.undo_copy_btn = self._pc_button(
            "↩ 撤销", "l3", 30,
            "暂无可撤销的文案操作（支持撤销文案修改、回车切分、合并、删除、AI自动整理、睁闭眼与模式切换 · 快捷键 ⌘Z）"
        )
        self.undo_copy_btn.setEnabled(False)
        self.undo_copy_btn.clicked.connect(self.undo_copy_operation)
        title_row.addWidget(self.undo_copy_btn)

        self.redo_copy_btn = self._pc_button(
            "↪", "l3", 30,
            "暂无可重做的文案操作（快捷键 ⇧⌘Z）"
        )
        self.redo_copy_btn.setFixedWidth(32)
        self.redo_copy_btn.setProperty("compact", True)
        self.redo_copy_btn.setEnabled(False)
        self.redo_copy_btn.clicked.connect(self.redo_copy_operation)
        title_row.addWidget(self.redo_copy_btn)

        title_row.addStretch(1)
        self.task_search_input = QLineEdit(objectName="pcSearchInput")
        self.task_search_input.setPlaceholderText("🔍 搜索文案 / 编号…")
        self.task_search_input.setClearButtonEnabled(True)
        self.task_search_input.setFixedWidth(164)
        self.task_search_input.setFixedHeight(30)
        self.task_search_input.textChanged.connect(self._apply_task_search)
        title_row.addWidget(self.task_search_input)
        try:
            saved_pt = max(10, min(24, int(repo.get_setting("prompt_copy_font_size", "13") or 13)))
        except Exception:
            saved_pt = 13
        font_capsule = QFrame(objectName="pcFontCapsule")
        font_capsule.setFixedHeight(30)
        fc_row = QHBoxLayout(font_capsule)
        fc_row.setContentsMargins(4, 2, 4, 2)
        fc_row.setSpacing(4)
        font_minus_btn = QPushButton("A-", objectName="pcFontStepBtn")
        font_minus_btn.setCursor(Qt.PointingHandCursor)
        font_minus_btn.setToolTip("缩小文案列表字号")
        self.copy_font_slider = QSlider(Qt.Horizontal, objectName="pcFontSlider")
        self.copy_font_slider.setRange(10, 24)
        self.copy_font_slider.setValue(saved_pt)
        self.copy_font_slider.setFixedWidth(68)
        self.copy_font_slider.setToolTip(f"文案字号：{saved_pt}pt（拖动实时缩放 10pt ~ 24pt）")
        font_plus_btn = QPushButton("A+", objectName="pcFontStepBtn")
        font_plus_btn.setCursor(Qt.PointingHandCursor)
        font_plus_btn.setToolTip("放大文案列表字号")
        self.copy_font_label = QLabel(f"{saved_pt}pt", self, objectName="muted")
        self.copy_font_label.hide()
        font_minus_btn.clicked.connect(lambda: self.copy_font_slider.setValue(max(10, self.copy_font_slider.value() - 1)))
        font_plus_btn.clicked.connect(lambda: self.copy_font_slider.setValue(min(24, self.copy_font_slider.value() + 1)))
        self.copy_font_slider.valueChanged.connect(self._on_copy_font_size_changed)
        fc_row.addWidget(font_minus_btn)
        fc_row.addWidget(self.copy_font_slider)
        fc_row.addWidget(font_plus_btn)
        title_row.addWidget(font_capsule)

        help_tip = (
            "💡 列表快捷操作提示：\n"
            "· 按住 Shift 单击可连选多行；按住勾选框右下角小圆点拖动可批量勾选\n"
            "· 单击「类型」胶囊直接切换 睁眼 ↔ 闭眼；单击「模式」胶囊直接切换 帧 ↔ 素材\n"
            "· 双击文案可直接修改，在光标处按回车（Enter）自动把后半句切分为下一行新片段\n"
            "· 右键任意行可合并上/下一片或删除片段；按 ⌘Z 随时多步撤销"
        )
        self.table_help_btn = QPushButton("?", objectName="pcHelpBtn")
        self.table_help_btn.setCursor(Qt.PointingHandCursor)
        self.table_help_btn.setToolTip(help_tip)
        self.table_help_btn.clicked.connect(
            lambda: QMessageBox.information(self, "文案列表快捷操作说明", help_tip)
        )
        title_row.addWidget(self.table_help_btn)
        task_v.addLayout(title_row)

        # Tool row (all flat & 1-click accessible): AI整理 + 比例 · 模式胶囊组 · 勾选胶囊组
        task_tools = QHBoxLayout()
        task_tools.setSpacing(6)
        self.ai_reorganize_btn = self._pc_button(
            "✨ AI自动整理", "l2", 30,
            "不改动原文案任何一字，自动按语义与标点智能断行/合并，将每段时长均衡在 7 秒左右（不超过 8 秒）"
        )
        self.ai_reorganize_btn.clicked.connect(self._ai_reorganize_scripts)
        self.host_aspect_ratio_btn = self._pc_button("9:16", "l3", 30)
        self.host_aspect_ratio_btn.setMinimumWidth(50)
        self.host_aspect_ratio_btn.clicked.connect(self._toggle_selected_host_aspect_ratio)
        task_tools.addWidget(self.ai_reorganize_btn)
        task_tools.addWidget(self.host_aspect_ratio_btn)

        mode_seg = QFrame(objectName="pcSegGroup")
        mode_seg.setFixedHeight(30)
        ms_row = QHBoxLayout(mode_seg)
        ms_row.setContentsMargins(3, 1, 3, 1)
        ms_row.setSpacing(1)
        self.mode_all_frame_btn = self._pc_group_button("全帧", "当前列表全部片段设为帧模式")
        self.mode_first_material_btn = self._pc_group_button("首片素材", "每个完整视频的第一片设为素材模式")
        self.mode_selected_material_btn = self._pc_group_button("→素材", "将勾选的片段设为素材模式")
        self.mode_selected_omini_btn = self._pc_group_button("→Omini", "将勾选的片段改用 Omini 模型生成（默认 8 秒）")
        self.mode_all_frame_btn.clicked.connect(lambda: self._batch_set_generation_mode("all_frame"))
        self.mode_first_material_btn.clicked.connect(lambda: self._batch_set_generation_mode("first_material"))
        self.mode_selected_material_btn.clicked.connect(lambda: self._batch_set_generation_mode("selected_material"))
        self.mode_selected_omini_btn.clicked.connect(lambda: self._batch_set_generation_mode("selected_omini"))
        for idx_b, b in enumerate((
            self.mode_all_frame_btn,
            self.mode_first_material_btn,
            self.mode_selected_material_btn,
            self.mode_selected_omini_btn,
        )):
            if idx_b:
                ms_row.addWidget(QFrame(objectName="pcSegSep"))
            ms_row.addWidget(b)
        task_tools.addWidget(mode_seg)

        sel_seg = QFrame(objectName="pcSegGroup")
        sel_seg.setFixedHeight(30)
        ss_row = QHBoxLayout(sel_seg)
        ss_row.setContentsMargins(3, 1, 3, 1)
        ss_row.setSpacing(1)
        self.select_all_visible_btn = self._pc_group_button("全选", "勾选当前列表全部可见行")
        self.select_all_visible_btn.clicked.connect(self._select_all_visible)
        self.pending_btn = self._pc_group_button("未填", "只勾选还没有生成提示词的行")
        self.pending_btn.clicked.connect(self.select_pending_rows)
        ss_row.addWidget(self.select_all_visible_btn)
        ss_row.addWidget(QFrame(objectName="pcSegSep"))
        ss_row.addWidget(self.pending_btn)
        task_tools.addWidget(sel_seg)
        task_tools.addStretch(1)
        task_v.addLayout(task_tools)

        # Segment operations (merge / delete) live in the right-click menu; type is toggled in the 类型 cell.
        self.delete_segment_btn = QPushButton("删除片段"); self.delete_segment_btn.clicked.connect(self._delete_selected_prompt_segment)
        self.merge_prev_btn = QPushButton("合并到上一片"); self.merge_prev_btn.clicked.connect(lambda: self._merge_selected_prompt_segment("prev"))
        self.merge_next_btn = QPushButton("合并到下一片"); self.merge_next_btn.clicked.connect(lambda: self._merge_selected_prompt_segment("next"))

        task_v.addWidget(self.table, 1)

        self.table_hint = QLabel("💡 按住 Shift 连选多行 · 点「类型」切睁/闭眼 · 右键行可合并/删除 · 双击改文案（回车切分）· 支持点「↩ 撤销」或 ⌘Z 回退操作", self, objectName="tcHint")
        self.table_hint.hide()
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
        ev.setContentsMargins(14, 10, 14, 10)
        ev.setSpacing(7)
        self.editor_scroll.setWidget(editor_content)
        editor_outer.addWidget(self.editor_scroll, 1)

        ed_hdr = QHBoxLayout()
        ed_hdr.setSpacing(8)
        self.editor_title = QLabel("快速编辑")
        self.editor_title.setStyleSheet("font-size:15.5px;font-weight:800;")
        ed_hdr.addWidget(self.editor_title)
        ed_hdr.addStretch(1)
        self.editor_prompt_state = QLabel("", objectName="tcChip")
        self.editor_prompt_state.hide()
        ed_hdr.addWidget(self.editor_prompt_state)
        ev.addLayout(ed_hdr)

        meta_row = QHBoxLayout()
        meta_row.setSpacing(8)
        self.editor_meta = QLabel("单击左侧任务预览参考图与提示词", objectName="muted")
        self.editor_meta.setWordWrap(False)
        self.editor_meta.setStyleSheet("font-size:12px;")
        meta_row.addWidget(self.editor_meta, 1)
        self.editor_duration_label = QLabel("", objectName="pcDurationLabel")
        self.editor_duration_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.editor_duration_label.hide()
        meta_row.addWidget(self.editor_duration_label)
        ev.addLayout(meta_row)

        # Keep an unmounted QPlainTextEdit handle for backwards compatibility; copy editing lives in self.table.
        self.editor_dialogue = QPlainTextEdit(self)
        self.editor_dialogue.hide()

        # Top compact rule strip: 2 permanent side-by-side rule boxes (never folded!)
        rules_row = QHBoxLayout()
        rules_row.setSpacing(10)

        img_rule_col = QVBoxLayout()
        img_rule_col.setSpacing(3)
        img_rule_lbl = QLabel("整图要求", objectName="pcEditorFieldLabel")
        img_rule_lbl.setToolTip("图片全局要求：作用于该参考图下的全部片段")
        img_rule_col.addWidget(img_rule_lbl)
        self.editor_image_rule = QPlainTextEdit(objectName="pcCompactRuleEdit")
        self.editor_image_rule.setPlaceholderText("作用于本图全部片段…")
        self.editor_image_rule.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.editor_image_rule.document().setDocumentMargin(2)
        self.editor_image_rule.setFixedHeight(52)
        img_rule_col.addWidget(self.editor_image_rule)
        rules_row.addLayout(img_rule_col, 1)

        seg_rule_col = QVBoxLayout()
        seg_rule_col.setSpacing(3)
        seg_rule_lbl = QLabel("单段要求", objectName="pcEditorFieldLabel")
        seg_rule_lbl.setToolTip("单条特殊要求：仅作用于当前选中的 Flow 小片段")
        seg_rule_col.addWidget(seg_rule_lbl)
        self.editor_segment_rule = QPlainTextEdit(objectName="pcCompactRuleEdit")
        self.editor_segment_rule.setPlaceholderText("仅作用于当前片段…")
        self.editor_segment_rule.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.editor_segment_rule.document().setDocumentMargin(2)
        self.editor_segment_rule.setFixedHeight(52)
        seg_rule_col.addWidget(self.editor_segment_rule)
        rules_row.addLayout(seg_rule_col, 1)
        ev.addLayout(rules_row)

        # Main full-height 2-column workspace: Left = Large Adaptive Reference Image · Right = Final Flow Prompt
        workspace_body = QHBoxLayout()
        workspace_body.setSpacing(12)

        img_col = QVBoxLayout()
        img_col.setContentsMargins(0, 0, 0, 0)
        img_col.setSpacing(4)
        img_hdr_widget = QWidget()
        img_hdr_widget.setFixedHeight(22)
        img_hdr = QHBoxLayout(img_hdr_widget)
        img_hdr.setContentsMargins(0, 0, 0, 0)
        img_hdr.setSpacing(6)
        img_hdr.addWidget(QLabel("参考图", objectName="pcEditorFieldLabel"))
        img_hdr.addStretch(1)
        self.editor_image_dim_label = QLabel("", objectName="muted")
        self.editor_image_dim_label.setStyleSheet("font-size:11px;")
        img_hdr.addWidget(self.editor_image_dim_label)
        img_col.addWidget(img_hdr_widget)

        self.editor_image = _AdaptiveEditorImage("参考图\n(单击左侧任务预览)")
        self.editor_image.setProperty("hasImage", "false")
        self.editor_image.clicked.connect(self._open_editor_image_zoom)
        img_col.addWidget(self.editor_image, 1)
        workspace_body.addLayout(img_col, 48)

        prompt_col = QVBoxLayout()
        prompt_col.setContentsMargins(0, 0, 0, 0)
        prompt_col.setSpacing(4)
        prompt_hdr_widget = QWidget()
        prompt_hdr_widget.setFixedHeight(22)
        prompt_hdr = QHBoxLayout(prompt_hdr_widget)
        prompt_hdr.setContentsMargins(0, 0, 0, 0)
        prompt_hdr.setSpacing(6)
        self.editor_prompt_header_label = QLabel("核心提示词", objectName="pcEditorFieldLabel")
        prompt_hdr.addWidget(self.editor_prompt_header_label)
        prompt_hdr.addStretch(1)
        self.editor_prompt_mode_btn = QPushButton("完整指令 ▾", objectName="pcMiniToggleBtn")
        self.editor_prompt_mode_btn.setCheckable(True)
        self.editor_prompt_mode_btn.setChecked(False)
        self.editor_prompt_mode_btn.setCursor(Qt.PointingHandCursor)
        self.editor_prompt_mode_btn.setToolTip(
            "默认仅显示核心镜头/动作/情绪描述（自动折叠下方固定文案与防穿帮套话，保存与提交时自动完整拼接）。\n点击可切换展开完整指令"
        )
        self.editor_prompt_mode_btn.toggled.connect(self._on_editor_prompt_mode_toggled)
        prompt_hdr.addWidget(self.editor_prompt_mode_btn)
        self.editor_copy_prompt_btn = QPushButton("📋 复制", objectName="pcMiniCopyBtn")
        self.editor_copy_prompt_btn.setCursor(Qt.PointingHandCursor)
        self.editor_copy_prompt_btn.setToolTip("复制当前片段的完整最终 Flow 提示词")
        self.editor_copy_prompt_btn.clicked.connect(self._copy_editor_final_prompt)
        prompt_hdr.addWidget(self.editor_copy_prompt_btn)
        prompt_col.addWidget(prompt_hdr_widget)

        self.editor_final_prompt = QPlainTextEdit(objectName="pcFinalPromptEdit")
        self.editor_final_prompt.setPlaceholderText("在此填写或微调本段核心镜头、动作与表情提示词（固定后缀已自动折叠保护）…")
        self.editor_final_prompt.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.editor_final_prompt.document().setDocumentMargin(2)
        self.editor_final_prompt.setMinimumHeight(150)
        self.editor_final_prompt.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        prompt_col.addWidget(self.editor_final_prompt, 1)
        workspace_body.addLayout(prompt_col, 52)

        ev.addLayout(workspace_body, 1)

        # Bottom action bar utilizing full panel height cleanly
        action = QHBoxLayout()
        action.setContentsMargins(0, 2, 0, 0)
        action.setSpacing(8)
        self.editor_save = self._pc_button("💾 保存", "l1blue", 35, "保存当前片段（⌘S）")
        self.editor_save.setMinimumWidth(92)
        self.editor_save.clicked.connect(self.save_inline_editor)
        action.addWidget(self.editor_save)
        self.editor_save_next = self._pc_button("保存并下一条 ↵", "l2", 35, "保存并跳到下一条（⌘↵）")
        self.editor_save_next.clicked.connect(self.save_and_next)
        action.addWidget(self.editor_save_next)
        action.addStretch(1)
        self.editor_reload = QPushButton("撤销未保存修改", objectName="pcLink")
        self.editor_reload.setCursor(Qt.PointingHandCursor)
        self.editor_reload.clicked.connect(self.reload_inline_editor)
        action.addWidget(self.editor_reload)
        ev.addLayout(action)

        for seq, slot in (("Ctrl+S", self.save_inline_editor), ("Ctrl+Return", self.save_and_next), ("Ctrl+Enter", self.save_and_next)):
            sc = QShortcut(QKeySequence(seq), editor_card)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(slot)

        self._undo_copy_shortcut = QShortcut(QKeySequence.StandardKey.Undo, self)
        self._undo_copy_shortcut.setContext(Qt.WindowShortcut)
        self._undo_copy_shortcut.activated.connect(self._shortcut_undo_copy)
        self._redo_copy_shortcut = QShortcut(QKeySequence.StandardKey.Redo, self)
        self._redo_copy_shortcut.setContext(Qt.WindowShortcut)
        self._redo_copy_shortcut.activated.connect(self._shortcut_redo_copy)

        for editor in (self.editor_image_rule, self.editor_segment_rule, self.editor_final_prompt):
            editor.textChanged.connect(self.mark_editor_dirty)

        editor_card.setMinimumWidth(380)
        split.addWidget(editor_card)
        split.setStretchFactor(0, 13)
        split.setStretchFactor(1, 7)
        self.workspace_splitter = split
        saved_split = str(repo.get_setting("prompt_center_splitter_sizes_v3", "") or "").strip()
        try:
            sizes = [max(160, int(x)) for x in saved_split.split(",")[:2]]
            if len(sizes) != 2:
                raise ValueError
        except Exception:
            sizes = [920, 495]
        split.setSizes(sizes)
        split.splitterMoved.connect(self._save_workspace_splitter)
        self._table_loading = False
        self.table.itemChanged.connect(self._prompt_table_item_changed)
        self._refresh_host_aspect_ratio_btn()
        layout.addWidget(split, 1)

    # ── Centered live status & progress banner helpers ─────────────────────
    def _classify_job_tone(self, text: str) -> str:
        t = (text or "").strip()
        if not t or t == "就绪":
            return "idle"
        if t.startswith("⚡") or any(k in t for k in ("正在", "生成中", "并行队列", "已排队")):
            return "running"
        if t.startswith(("⚠", "❌")) or any(k in t for k in ("有任务失败", "异常", "失败：")):
            return "warn"
        if "本批完成" in t and "失败" in t and "失败 0" not in t:
            return "warn"
        if t.startswith(("✅", "✨", "🚀", "✓", "🧹", "↩")) or any(
            k in t for k in ("完成", "已更新", "已保存", "已设为", "已切换", "已提交", "已撤回", "已清空", "已合并", "已删除")
        ):
            return "done"
        return "info"

    def _sync_center_job_banner(self, text: str):
        if not hasattr(self, "job_banner_wrap"):
            return
        t = (text or "").strip()
        worker_running = bool(self.worker and self.worker.isRunning())
        prog_vis = hasattr(self, "progress") and not self.progress.isHidden()
        tone = self._classify_job_tone(t)

        if tone == "idle" and not worker_running and not prog_vis:
            self.job_banner_wrap.hide()
            return

        if tone == "idle":
            tone = "running" if (worker_running or prog_vis) else "info"

        badge_map = {
            "running": "正在处理",
            "done": "处理完成",
            "warn": "异常提示",
            "info": "操作反馈",
        }
        self.job_state_badge.setText(badge_map.get(tone, "状态提示"))
        for w in (self.job_banner, self.job_state_badge, self.current_job, self.progress, self.progress_pct_label):
            self._set_prop(w, "tone", tone)

        is_running = (tone == "running")
        self.job_dismiss_btn.setVisible(not is_running)
        if is_running:
            self.job_time_label.hide()
        else:
            from datetime import datetime
            self.job_time_label.setText(datetime.now().strftime("%H:%M:%S"))
            self.job_time_label.show()

        self.job_banner_wrap.show()
        self.current_job.updateGeometry()
        self.job_banner.updateGeometry()
        self.job_banner_wrap.updateGeometry()
        if self.job_banner_wrap.layout() is not None:
            self.job_banner_wrap.layout().activate()
        parent = self.job_banner_wrap.parentWidget()
        if parent is not None and parent.layout() is not None:
            parent.layout().activate()

        if not is_running and hasattr(self, "_banner_flash_timer"):
            self._set_prop(self.job_banner, "flash", "true")
            self._banner_flash_timer.start(340)

    def _clear_banner_flash(self):
        if hasattr(self, "job_banner"):
            self._set_prop(self.job_banner, "flash", "false")

    def _sync_center_progress_ui(self):
        if not hasattr(self, "progress_pct_label") or not hasattr(self, "progress"):
            return
        mn, mx = self.progress.minimum(), self.progress.maximum()
        if mx <= mn:
            self.progress_pct_label.setText("…")
        else:
            pct = max(0, min(100, int(round((self.progress.value() - mn) * 100.0 / max(1, mx - mn)))))
            self.progress_pct_label.setText(f"{pct}%")

    def _sync_center_progress_visibility(self, visible: bool):
        if not hasattr(self, "progress_box"):
            return
        self.progress_box.setVisible(bool(visible))
        if visible and hasattr(self, "job_banner_wrap"):
            self._sync_center_progress_ui()
            self.job_banner_wrap.show()
        if hasattr(self, "job_banner"):
            self.job_banner.updateGeometry()
            self.job_banner_wrap.updateGeometry()
            if self.job_banner_wrap.layout() is not None:
                self.job_banner_wrap.layout().activate()
            parent = self.job_banner_wrap.parentWidget()
            if parent is not None and parent.layout() is not None:
                parent.layout().activate()

    def _hide_progress_if_idle(self):
        if self.worker and self.worker.isRunning():
            return
        if hasattr(self, "progress"):
            self.progress.hide()

    def _dismiss_center_job_banner(self):
        if self.worker and self.worker.isRunning():
            return
        if hasattr(self, "_progress_hide_timer"):
            self._progress_hide_timer.stop()
        if hasattr(self, "progress"):
            self.progress.hide()
        self.current_job.setText("就绪")

    # ── Button hierarchy helpers (UI only) ─────────────────────────────────
    def _pc_button(self, text, tier="l3", height=34, tip=""):
        b = QPushButton(text, objectName="pcBtn")
        b.setProperty("tier", tier)
        b.setFixedHeight(height)
        b.setCursor(Qt.PointingHandCursor)
        if tip:
            b.setToolTip(tip)
        return b

    def _pc_group_button(self, text: str, tip: str = "") -> QPushButton:
        b = QPushButton(text, objectName="pcGroupBtn")
        b.setFixedHeight(26)
        b.setCursor(Qt.PointingHandCursor)
        if tip:
            b.setToolTip(tip)
        return b

    def _open_more_prompt_ops_menu(self):
        menu = QMenu(self)
        menu.setObjectName("pcMenu")
        menu.setWindowFlags(menu.windowFlags() | Qt.FramelessWindowHint)
        menu.setAttribute(Qt.WA_TranslucentBackground, True)
        menu.setAttribute(Qt.WA_DeleteOnClose, True)
        menu.setToolTipsVisible(True)
        entries = (
            (self.template_prompts_btn, lambda: self.local_fill_prompts(True)),
            (self.paste_prompts_btn, self.batch_paste_prompts),
            None,
            (self.clear_prompts_btn, self.clear_selected_prompts),
        )
        for item in entries:
            if item is None:
                menu.addSeparator()
                continue
            src_btn, slot = item
            act = menu.addAction(src_btn.text())
            act.setEnabled(src_btn.isEnabled())
            act.setToolTip(src_btn.toolTip())
            act.triggered.connect(lambda _=False, fn=slot: fn())
        pos = self.more_prompt_ops_btn.mapToGlobal(QPoint(0, self.more_prompt_ops_btn.height() + 4))
        menu.popup(pos)

    def _pc_seg_button(self, text, pos):
        b = QPushButton(text, objectName="pcSeg")
        b.setProperty("pos", pos)
        b.setCheckable(True)
        b.setFixedHeight(34)
        b.setCursor(Qt.PointingHandCursor)
        return b

    def _set_tier(self, btn, tier):
        if btn is not None and btn.property("tier") != tier:
            self._set_prop(btn, "tier", tier)
            btn.updateGeometry()

    def _pc_menu(self, entries):
        menu = QMenu(self)
        menu.setObjectName("pcMenu")
        menu.setWindowFlags(menu.windowFlags() | Qt.FramelessWindowHint)
        menu.setAttribute(Qt.WA_TranslucentBackground, True)
        menu.setToolTipsVisible(True)
        for entry in entries:
            if entry is None:
                menu.addSeparator()
                continue
            act = menu.addAction(entry[0])
            act.triggered.connect(lambda _=False, fn=entry[1]: fn())
        return menu

    def _split_button(self, main_btn, menu, arrow_tip=""):
        arrow = self._pc_button("▾", main_btn.property("tier"), main_btn.height(), arrow_tip)
        arrow.setFixedWidth(30)
        arrow.setProperty("split", "arrow")
        main_btn.setProperty("split", "main")
        arrow.setMenu(menu)
        box = QWidget()
        hl = QHBoxLayout(box)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(0)
        hl.addWidget(main_btn)
        hl.addWidget(arrow)
        return box, arrow

    def _segment_menu_entries(self):
        return [
            ("⤒ 合并到上一片", lambda: self._merge_selected_prompt_segment("prev")),
            ("⤓ 合并到下一片", lambda: self._merge_selected_prompt_segment("next")),
            None,
            ("🗑 删除片段", self._delete_selected_prompt_segment),
        ]

    def _show_table_context_menu(self, pos):
        row = self.table.rowAt(pos.y())
        undo_entries = self._copy_undo_menu_entries()
        if row < 0 or row >= len(self.task_rows):
            if not undo_entries:
                return
            entries = undo_entries
        else:
            self.table.selectRow(row)
            sid = int(self.task_rows[row]["segment_id"])
            checked = sid in self.checked_ids

            def toggle_check():
                cell = self._cell_check(row)
                if cell is not None:
                    cell.setChecked(not checked, block=True)
                self.on_row_check_changed(sid, not checked)

            entries = [("☐ 取消勾选此行" if checked else "☑ 勾选此行", toggle_check), None]
            entries += self._segment_menu_entries()
            if undo_entries:
                entries += [None] + undo_entries
        old = getattr(self, "_ctx_menu", None)
        if old is not None:
            try:
                old.close()
            except RuntimeError:
                pass
        menu = self._pc_menu(entries)
        menu.setAttribute(Qt.WA_DeleteOnClose, True)
        # Watch the open menu so a right-click on another row re-opens it right there
        # (by default the first click outside a popup is swallowed just to close it).
        menu.installEventFilter(self)
        self._ctx_menu = menu
        menu.popup(self.table.viewport().mapToGlobal(pos))

    def _clear_all_checks(self):
        self._shift_anchor_row = None
        for row, task in enumerate(self.task_rows):
            cell = self._cell_check(row)
            if cell is not None:
                try:
                    cell.setChecked(False, block=True)
                except Exception:
                    pass
        self.checked_ids.clear()
        self.update_header_check()

    def _current_host_task_rows(self, visible_only=True):
        hid = self.host.currentData() if hasattr(self, "host") else None
        if not hid:
            return []
        target_hid = int(hid)
        return [
            t for row, t in enumerate(self.task_rows)
            if int(t["host_id"] or 0) == target_hid
            and (not visible_only or not self.table.isRowHidden(row))
        ]

    def _sync_checked_host_scope(self):
        cur_hid = int(self.host.currentData() or 0) if hasattr(self, "host") else 0
        prev_hid = getattr(self, "_active_checked_host_id", 0)
        if cur_hid != prev_hid:
            self.checked_ids.clear()
            self._shift_anchor_row = None
            self._active_checked_host_id = cur_hid

    def _is_history_workspace(self):
        return hasattr(self, "review_filter") and self.review_filter.currentIndex() == 1

    def _primary_submit(self):
        if self._is_history_workspace():
            self.resubmit_selected_to_flow()
        elif self.selected_segment_ids():
            self.submit_selected_to_flow()
        elif self.host.currentData():
            self.submit_current_host_to_flow()
        else:
            self.submit_selected_to_flow()

    def _selection_submit(self):
        if self._is_history_workspace():
            self.resubmit_selected_to_flow()
        else:
            self.submit_selected_to_flow()

    def _refresh_selection_bar(self):
        """Scope chip: concise indicator of what action buttons currently act on."""
        if not hasattr(self, "scope_label"):
            return
        hid = self.host.currentData() if hasattr(self, "host") else None
        host_rows = self._current_host_task_rows(visible_only=True)
        n = len(self.selected_segment_ids())
        if not hid:
            self.scope_label.setText("请先选择主播")
            self._set_prop(self.scope_label, "active", False)
        elif n:
            self.scope_label.setText(f"☑ 已勾选 {n} 条")
            self._set_prop(self.scope_label, "active", True)
        else:
            unfilled = sum(1 for t in host_rows if not (t["prompt"] or "").strip())
            if not host_rows:
                self.scope_label.setText("当前 0 条")
            elif unfilled > 0:
                self.scope_label.setText(f"当前 {len(host_rows)} 条 · 待生成 {unfilled} 条")
            else:
                self.scope_label.setText(f"当前 {len(host_rows)} 条 · 全部已生成")
            self._set_prop(self.scope_label, "active", False)
        self.scope_clear_btn.setVisible(n > 0)
        self.clear_prompts_btn.setEnabled(n > 0)
        self.mode_selected_material_btn.setEnabled(n > 0)
        self.mode_selected_omini_btn.setEnabled(n > 0)

    def _refresh_primary_actions(self):
        """Exactly one solid (L1) action: generate while anything is unfilled, otherwise submit."""
        if not hasattr(self, "submit_host"):
            return
        if hasattr(self, "ws_history_btn"):
            want = self.ws_history_btn if self._is_history_workspace() else self.ws_current_btn
            if not want.isChecked():
                want.setChecked(True)
        history = self._is_history_workspace()
        running = bool(self.worker and self.worker.isRunning())
        pending_ids = (
            self.worker.pending_segment_ids()
            if (running and hasattr(self.worker, "pending_segment_ids")) else set()
        )
        hid = self.host.currentData() if hasattr(self, "host") else None
        hname = str(self.host.currentText() or "").strip() if hid else ""
        host_rows = self._current_host_task_rows(visible_only=True)
        checked_all = [int(s) for s in self.selected_segment_ids()]
        checked = [sid for sid in checked_all if sid not in pending_ids]
        unfilled = [
            t for t in host_rows
            if int(t["segment_id"]) not in pending_ids
            and (not (t["prompt"] or "").strip() or str(t["status"] or "") in ("待处理", "失败", "文案已改"))
        ]
        if checked_all:
            gen_n = len(checked)
        else:
            gen_n = len(unfilled)
        if gen_n:
            gen_text = f"{'⚡ 追加生成' if running else '✨ GPT 生成'} {gen_n} 条"
        else:
            gen_text = "⚡ 生成中…" if running else "✨ GPT 生成"
        self.header_generate.setText(gen_text)
        self.header_generate.setEnabled(bool(hid) and gen_n > 0)
        if hid and hname:
            self.header_generate.setToolTip(
                f"仅针对当前主播【{hname}】生成提示词（本次 {gen_n} 条），绝不会改动其他主播。\n"
                "正在生成时若需同时跑另一个主播，可手动切换到该主播后再点追加。"
            )

        fill_n = len(checked_all) if checked_all else len(host_rows)
        self.template_prompts_btn.setText(f"📄 模板套用 {fill_n} 条" if fill_n else "📄 模板套用")
        self.paste_prompts_btn.setText(f"✍ 手动填写 {fill_n} 条" if fill_n else "✍ 手动填写")
        self.template_prompts_btn.setEnabled(bool(hid) and fill_n > 0)
        self.paste_prompts_btn.setEnabled(bool(hid) and fill_n > 0)

        failed_n = sum(1 for t in host_rows if str(t["status"] or "") == "失败" and int(t["segment_id"]) not in pending_ids)
        self.retry_failed.setText(f"↻ 重试失败 {failed_n} 条")
        self.retry_failed.setVisible(bool(hid) and failed_n > 0)

        n_checked = len(checked_all)
        self.submit_host.setVisible(not history)
        self.resubmit_selected.setVisible(history)
        self.withdraw_flow.setVisible(history)
        if history:
            self.resubmit_selected.setText(f"🔁 重新提交 {n_checked} 条" if n_checked else "🔁 重新提交选中")
            self.resubmit_selected.setEnabled(bool(hid) and n_checked > 0)
            self.withdraw_flow.setText(f"⚠️ 撤回 Flow 排队 ({n_checked} 条)" if n_checked else "⚠️ 撤回 Flow 排队")
            self.withdraw_flow.setEnabled(bool(hid) and n_checked > 0)
            sub_n = n_checked
        else:
            if n_checked:
                sub_n = n_checked
            elif hid:
                sub_n = sum(1 for t in host_rows if (t["prompt"] or "").strip())
            else:
                sub_n = 0
            self.submit_host.setText(f"🚀 提交 {sub_n} 条到 Flow" if sub_n else "🚀 提交到 Flow")
            self.submit_host.setEnabled(bool(hid) and sub_n > 0)

        gen_primary = gen_n > 0 and not running and not history
        self._set_tier(self.header_generate, "l1blue" if gen_primary else "l2blue")
        sub_tier = "l1green" if (not gen_primary and sub_n > 0) else "l2green"
        self._set_tier(self.submit_host, sub_tier)
        self._set_tier(self.resubmit_selected, sub_tier)

    # ── Inline single-pill 睁眼 / 闭眼 type toggle in the 类型 column ─────────
    def _make_type_toggle(self, row, sid, mode, classified):
        box = QWidget()
        hl = QHBoxLayout(box)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(0)
        hl.addStretch(1)
        pill = QPushButton(objectName="pcEyePill")
        pill.setCursor(Qt.PointingHandCursor)
        pill.setFixedWidth(58)
        if not classified:
            pill.setText("待识别")
            pill.setProperty("eyeState", "unclassified")
            tip = "尚未识别类型 · 点击设为睁眼（再点可切换闭眼）"
            next_mode = "TALKING"
        elif mode == "PRAYING":
            pill.setText("闭眼")
            pill.setProperty("eyeState", "closed")
            tip = "当前：闭眼祷告 · 点击切换为睁眼说话"
            next_mode = "TALKING"
        else:
            pill.setText("睁眼")
            pill.setProperty("eyeState", "open")
            tip = "当前：睁眼说话 · 点击切换为闭眼祷告"
            next_mode = "PRAYING"
        pill.setToolTip(tip)
        box.setToolTip(tip)
        pill.clicked.connect(lambda _=False, s=int(sid), m=next_mode, w=box: self._set_inline_segment_type(s, m, w))
        hl.addWidget(pill)
        hl.addStretch(1)
        box._pill_btn = pill
        return box

    def _set_inline_segment_type(self, sid, mode, widget=None):
        current = next((t for t in self.task_rows if int(t["segment_id"]) == int(sid)), None)
        if current is not None and current["segment_type_source"] != "unclassified":
            cur_mode = "PRAYING" if str(current["performance_mode"] or "").upper() == "PRAYING" else "TALKING"
            if cur_mode == mode:
                return
        if getattr(self, "_editor_dirty", False):
            self._persist_inline_editor(show_message=False)
        task_info = current or repo.get_prompt_task(int(sid))
        vid = int(task_info["video_id"]) if (task_info and task_info["video_id"] is not None) else 0
        tid = self._format_task_seq_label(task_info, sid)
        pre_snap = repo.snapshot_video_copy_state([vid]) if vid else None
        prev_checked = set(self.checked_ids)
        prev_hist = set(getattr(self, "_history_editing_ids", set()))
        try:
            repo.set_prompt_segment_type(int(sid), mode)
        except Exception as exc:
            QMessageBox.warning(self, "片段类型", str(exc))
            self.reload_tasks()
            return
        eye_txt = "闭眼" if mode == "PRAYING" else "睁眼"
        if vid and pre_snap:
            self._record_copy_undo(
                f"设为{eye_txt} {tid}",
                [vid],
                pre_snap,
                prev_editor_sid=int(sid),
                prev_checked=prev_checked,
                prev_history_ids=prev_hist,
            )
        scroll = self.table.verticalScrollBar().value()
        self.reload_tasks()
        QTimer.singleShot(0, lambda v=scroll: self.table.verticalScrollBar().setValue(v))
        self.current_job.setText(f"✅ 已设为{eye_txt}（{tid}）")

    def _resolve_target_host_for_aspect_ratio(self):
        hid = self.host.currentData() if hasattr(self, "host") else None
        if hid:
            return int(hid), str(self.host.currentText() or "当前主播")
        unique_hosts = {}
        for t in getattr(self, "task_rows", []) or []:
            thid = int(t["host_id"] or 0) if "host_id" in t.keys() else 0
            if thid > 0:
                unique_hosts[thid] = str(t["host_name"] or "当前主播") if "host_name" in t.keys() else "当前主播"
        if len(unique_hosts) == 1:
            return next(iter(unique_hosts.items()))
        rid = self.recipient.currentData() if hasattr(self, "recipient") else None
        if rid:
            hosts = list(repo.list_hosts(rid, work_date=work_dates.active()))
            if len(hosts) == 1:
                return int(hosts[0]["id"]), str(hosts[0]["name"] or "当前主播")
        if getattr(self, "editor_segment_id", None):
            for t in getattr(self, "task_rows", []) or []:
                if int(t["segment_id"]) == int(self.editor_segment_id) and int(t["host_id"] or 0) > 0:
                    return int(t["host_id"]), str(t["host_name"] or "当前主播")
        return None, ""

    def _refresh_host_aspect_ratio_btn(self):
        if not hasattr(self, "host_aspect_ratio_btn"):
            return
        hid, hname = self._resolve_target_host_for_aspect_ratio()
        ratio = repo.get_host_aspect_ratio(hid, work_date=work_dates.active()) if hid else "9:16"
        if ratio == "16:9":
            self.host_aspect_ratio_btn.setText("16:9")
            self._set_tier(self.host_aspect_ratio_btn, "l3on")
        else:
            self.host_aspect_ratio_btn.setText("9:16")
            self._set_tier(self.host_aspect_ratio_btn, "l3")
        tip_host = f"（当前主播：{hname}）" if hname else ""
        self.host_aspect_ratio_btn.setToolTip(f"当前生成比例：{ratio}{tip_host}，点击切换 9:16 ↔ 16:9 并同步至网页插件")

    def _toggle_selected_host_aspect_ratio(self):
        hid, hname = self._resolve_target_host_for_aspect_ratio()
        if not hid:
            QMessageBox.information(
                self,
                "切换主播生成比例",
                "请先在上方点击选择一个 AI 主播（或在列表中点击该主播的任务），\n9:16 / 16:9 生成模式仅针对选中的主播生效。",
            )
            return
        current_ratio = repo.get_host_aspect_ratio(hid, work_date=work_dates.active())
        new_ratio = "16:9" if current_ratio == "9:16" else "9:16"
        repo.set_host_aspect_ratio(hid, new_ratio)
        try:
            from app.services.local_bridge import get_bridge
            get_bridge().update_host_aspect_ratio(hid, new_ratio)
        except Exception:
            pass
        self._refresh_host_aspect_ratio_btn()
        card_refs = getattr(self, "_host_card_widgets", {}).get(int(hid))
        if card_refs and card_refs.get("ratio_tag") is not None:
            rtag = card_refs["ratio_tag"]
            rtag.setText("16:9" if new_ratio == "16:9" else "9:16")
            if new_ratio == "16:9":
                rtag.setStyleSheet("background:#2563EB;color:#FFFFFF;border-radius:4px;padding:1px 6px;font-size:11px;font-weight:700;")
            else:
                rtag.setStyleSheet("")
            rtag.style().unpolish(rtag)
            rtag.style().polish(rtag)
        else:
            self._rebuild_host_cards()
        self.current_job.setText(f"✅ 主播「{hname}」生成模式已切换为 {new_ratio}，已同步至网页插件")

    def _save_workspace_splitter(self, *_):
        t = getattr(self, "_splitter_save_timer", None)
        if t is None:
            t = QTimer(self)
            t.setSingleShot(True)
            t.timeout.connect(self._flush_workspace_splitter_save)
            self._splitter_save_timer = t
        t.start(160)

    def _flush_workspace_splitter_save(self):
        if not hasattr(self,"workspace_splitter"): return
        sizes=self.workspace_splitter.sizes()
        if len(sizes)>=2 and all(int(x)>0 for x in sizes[:2]):
            repo.set_setting("prompt_center_splitter_sizes_v3",f"{int(sizes[0])},{int(sizes[1])}")

    def _current_copy_font_size(self) -> int:
        if hasattr(self, "copy_font_slider"):
            return max(10, min(24, int(self.copy_font_slider.value())))
        try:
            return max(10, min(24, int(repo.get_setting("prompt_copy_font_size", "13") or 13)))
        except Exception:
            return 13

    def _on_copy_font_size_changed(self, value: int):
        pt = max(10, min(24, int(value or 13)))
        if hasattr(self, "copy_font_label"):
            self.copy_font_label.setText(f"{pt}pt")
        if hasattr(self, "copy_font_slider"):
            self.copy_font_slider.setToolTip(f"文案字号：{pt}pt（拖动实时缩放 10pt ~ 24pt）")
        ft = getattr(self, "_font_save_timer", None)
        if ft is None:
            ft = QTimer(self)
            ft.setSingleShot(True)
            ft.timeout.connect(lambda: repo.set_setting("prompt_copy_font_size", str(self._current_copy_font_size())))
            self._font_save_timer = ft
        ft.start(160)
        if hasattr(self, "_sheet_delegate"):
            self._sheet_delegate.set_point_size(pt)
        self.table.verticalHeader().setDefaultSectionSize(max(68, int(pt * 6.6)))
        self._table_loading = True
        try:
            copy_font = QFont(self.table.font())
            copy_font.setPointSize(pt)
            for r in range(self.table.rowCount()):
                item = self.table.item(r, 4)
                if item is not None:
                    item.setFont(copy_font)
        finally:
            self._table_loading = False
        self._hydrate_visible_table_widgets()
        self.table.viewport().update()

    @staticmethod
    def _estimate_copy_duration_info(text: str):
        from app.services.speech_preparation import _instruction_speech_seconds
        from app.services.text_processing import _words
        clean = ' '.join(str(text or '').split())
        if not clean:
            return 0.0, 0, "0.0s", "空文案", "#64748b"
        sec = float(_instruction_speech_seconds(clean))
        cjk = re.findall(r"[\u3400-\u9fff\u3040-\u30ff]", clean)
        if cjk and not _words(re.sub(r"[\u3400-\u9fff\u3040-\u30ff]", " ", clean)):
            sec = round(len(cjk) / 4.2, 1)
        wcount = len(_words(clean))
        unit_str = f"{wcount}词" if wcount else f"{len(clean)}字"
        if sec > 7.8:
            cell_text = f"⚠ {sec:.1f}s\n{unit_str}"
            color = "#dc2626"
            tip = f"估算说话时长：约 {sec:.1f} 秒（{unit_str} · {len(clean)} 字符）\n⚠️ 已接近或超过 8 秒上限，建议在标点或停顿处按回车切分到下一行！"
        elif sec > 7.0:
            cell_text = f"{sec:.1f}s\n{unit_str}"
            color = "#d97706"
            tip = f"估算说话时长：约 {sec:.1f} 秒（{unit_str} · {len(clean)} 字符）\n提示：接近 7.5 秒自然朗读上限，可按回车将后半段切分到下一行。"
        else:
            cell_text = f"{sec:.1f}s\n{unit_str}"
            color = "#15803d" if sec >= 2.0 else "#475569"
            tip = f"估算说话时长：约 {sec:.1f} 秒（{unit_str} · {len(clean)} 字符）\n✓ 在 8 秒安全朗读范围内（编辑文案时按回车可将光标后内容切到下一行）"
        return sec, wcount, cell_text, tip, color

    def _update_editor_duration_label(self, text: str | None = None):
        if not hasattr(self, "editor_duration_label"):
            return
        if text is None:
            text = getattr(self, "_loaded_dialogue", "") or (
                self.editor_dialogue.toPlainText() if hasattr(self, "editor_dialogue") else ""
            )
        sec, wcount, _, tip, color = self._estimate_copy_duration_info(text)
        clean = ' '.join(str(text or '').split())
        if not clean:
            self.editor_duration_label.clear()
            self.editor_duration_label.hide()
            return
        unit_str = f"{wcount}词" if wcount else f"{len(clean)}字"
        warn_prefix = "⚠ " if sec > 7.8 else ""
        self.editor_duration_label.setText(f"{warn_prefix}约 {sec:.1f}s ({unit_str})")
        dur_tone = "danger" if sec > 7.8 else ("warn" if sec > 7.0 else ("good" if sec >= 2.0 else "muted"))
        self._set_prop(self.editor_duration_label, "tone", dur_tone)
        self.editor_duration_label.setToolTip(tip)
        self.editor_duration_label.show()

    def _set_editor_thumb(self, image_path: str):
        path = str(image_path or "").strip()
        self._current_editor_image_path = ""
        if hasattr(self, "editor_image_dim_label"):
            self.editor_image_dim_label.setText("")
        if not path:
            self.editor_image.set_qimage(None, "无参考图")
            self.editor_image.setToolTip("当前片段未关联参考图片")
            self.editor_image.setCursor(Qt.ArrowCursor)
            self._set_prop(self.editor_image, "hasImage", "false")
            return
        from collections import OrderedDict
        from PySide6.QtGui import QImageReader
        from app.ui.image_preview import _thumbnail
        try:
            try:
                resolved = str(resolve_path(path))
            except Exception:
                resolved = path
            st = Path(resolved).stat()
            cache_key = (resolved, int(st.st_mtime_ns), int(st.st_size))
            hires_cache = getattr(self, "_editor_hires_cache", None)
            if hires_cache is None:
                hires_cache = OrderedDict()
                self._editor_hires_cache = hires_cache
            if cache_key in hires_cache:
                hires_cache.move_to_end(cache_key)
                qimg, orig_w, orig_h = hires_cache[cache_key]
            else:
                reader = QImageReader(resolved)
                reader.setDecideFormatFromContent(True)
                reader.setAutoTransform(True)
                orig = reader.size()
                orig_w, orig_h = (orig.width(), orig.height()) if orig.isValid() else (0, 0)
                if orig.isValid():
                    reader.setScaledSize(orig.scaled(QSize(920, 1480), Qt.KeepAspectRatio))
                qimg = reader.read()
                if qimg.isNull():
                    qimg = _thumbnail(resolved, QSize(900, 900))
                    orig_w, orig_h = qimg.width(), qimg.height()
                hires_cache[cache_key] = (qimg, orig_w, orig_h)
                while len(hires_cache) > 8:
                    hires_cache.popitem(last=False)

            self._current_editor_image_path = resolved
            self.editor_image.set_qimage(qimg, "")
            self.editor_image.setToolTip(f"🔍 点击放大查看高清参考原图\n{resolved}")
            self.editor_image.setCursor(Qt.PointingHandCursor)
            self._set_prop(self.editor_image, "hasImage", "true")
            if hasattr(self, "editor_image_dim_label") and orig_w > 0 and orig_h > 0:
                ratio_str = "9:16" if orig_h > orig_w * 1.15 else ("16:9" if orig_w > orig_h * 1.15 else "1:1")
                self.editor_image_dim_label.setText(f"{orig_w}×{orig_h} · {ratio_str}")
        except Exception as exc:
            self.editor_image.set_qimage(None, "图片加载失败")
            self.editor_image.setToolTip(str(exc))
            self.editor_image.setCursor(Qt.ArrowCursor)
            self._set_prop(self.editor_image, "hasImage", "false")

    def _open_editor_image_zoom(self):
        raw_path = str(getattr(self, "_current_editor_image_path", "") or "").strip()
        if not raw_path:
            return
        try:
            resolved = str(resolve_path(raw_path))
        except Exception:
            resolved = raw_path
        if not Path(resolved).exists():
            return
        from PySide6.QtGui import QImageReader
        from app.ui.image_preview import _thumbnail
        dlg = QDialog(self, objectName="pcImageZoomDialog")
        dlg.setWindowTitle(f"参考原图预览 · {Path(resolved).name}")
        dlg.setModal(True)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(10)

        reader = QImageReader(resolved)
        reader.setDecideFormatFromContent(True)
        reader.setAutoTransform(True)
        orig_sz = reader.size()
        screen = dlg.screen() or QApplication.primaryScreen()
        avail = screen.availableGeometry().size() if screen else QSize(1440, 900)
        max_w = max(360, min(920, int(avail.width() * 0.65)))
        max_h = max(420, min(780, int(avail.height() * 0.78)))
        dpr = 2
        if orig_sz.isValid():
            reader.setScaledSize(orig_sz.scaled(QSize(max_w * dpr, max_h * dpr), Qt.KeepAspectRatio))
        qimg = reader.read()
        if qimg.isNull():
            try:
                qimg = _thumbnail(resolved, QSize(min(1024, max_w * dpr), min(1024, max_h * dpr)))
            except Exception:
                return
        pix = QPixmap.fromImage(qimg)
        pix.setDevicePixelRatio(float(dpr))

        img_lbl = _ClickableThumbLabel()
        img_lbl.setAlignment(Qt.AlignCenter)
        img_lbl.setPixmap(pix)
        img_lbl.setCursor(Qt.PointingHandCursor)
        img_lbl.setToolTip("点击图片或按 Esc 关闭预览")
        img_lbl.clicked.connect(dlg.accept)
        v.addWidget(img_lbl, 1, Qt.AlignCenter)

        foot = QHBoxLayout()
        dim_txt = f"{orig_sz.width()} × {orig_sz.height()} px · " if orig_sz.isValid() else ""
        meta = QLabel(f"{dim_txt}{Path(resolved).name}", objectName="muted")
        foot.addWidget(meta)
        foot.addStretch(1)
        close_btn = self._pc_button("关闭 (Esc)", "l2", 32)
        close_btn.clicked.connect(dlg.accept)
        foot.addWidget(close_btn)
        v.addLayout(foot)
        dlg.exec()

    # ── Core vs. Full Flow Prompt view helpers (lossless suffix folding) ───
    _PROMPT_SUFFIX_SPLIT_RE = re.compile(
        r"(?m)^(?:文案\s*[:：]|【(?:自动匹配人物动作预设|参考图动作安全约束|Studio\s*固定执行约束)】)"
    )

    @classmethod
    def _split_prompt_core_and_suffix(cls, full_text: str) -> tuple[str, str]:
        raw = str(full_text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not raw:
            return "", ""
        m = cls._PROMPT_SUFFIX_SPLIT_RE.search(raw)
        if not m or m.start() <= 0:
            return raw, ""
        core = raw[: m.start()].rstrip()
        suffix = raw[m.start() :].strip()
        if not core:
            return raw, ""
        return core, suffix

    def _refresh_editor_prompt_mode_btn(self):
        if not hasattr(self, "editor_prompt_mode_btn"):
            return
        full_mode = bool(getattr(self, "_editor_prompt_full_mode", False))
        has_suffix = bool(getattr(self, "_editor_prompt_suffix_body", "").strip())
        if hasattr(self, "editor_prompt_header_label"):
            self.editor_prompt_header_label.setText("最终 Flow 提示词" if full_mode else "核心提示词")
        self.editor_prompt_mode_btn.blockSignals(True)
        self.editor_prompt_mode_btn.setChecked(full_mode)
        self.editor_prompt_mode_btn.blockSignals(False)
        if full_mode:
            self.editor_prompt_mode_btn.setText("仅看核心 ▴")
            self.editor_prompt_mode_btn.setToolTip(
                "当前显示完整最终 Flow 提示词（含文案与固定防穿帮后缀）。\n点击切回「仅看核心」清爽视图"
            )
            if hasattr(self, "editor_final_prompt"):
                self.editor_final_prompt.setPlaceholderText("在此填写或微调完整最终 Flow 提示词…")
        else:
            self.editor_prompt_mode_btn.setText("完整指令 ▾")
            if has_suffix:
                self.editor_prompt_mode_btn.setToolTip(
                    "已自动折叠下方固定文案与防穿帮套话（保存、复制与提交时 100% 自动完整拼接）。\n点击可展开完整指令"
                )
            else:
                self.editor_prompt_mode_btn.setToolTip(
                    "默认仅显示核心镜头/动作/情绪描述（固定后缀自动折叠保护）。\n点击可切换完整指令视图"
                )
            if hasattr(self, "editor_final_prompt"):
                self.editor_final_prompt.setPlaceholderText(
                    "在此填写或微调本段核心镜头、动作与表情提示词（固定后缀已自动折叠保护）…"
                )

    def _compose_editor_full_prompt(self) -> str:
        if not hasattr(self, "editor_final_prompt"):
            return ""
        typed = self.editor_final_prompt.toPlainText().replace("\r\n", "\n").replace("\r", "\n").strip()
        suffix = str(getattr(self, "_editor_prompt_suffix_body", "") or "").strip()
        if getattr(self, "_editor_prompt_full_mode", False) or not suffix:
            return typed
        if not typed:
            return ""
        if self._PROMPT_SUFFIX_SPLIT_RE.search(typed):
            return typed
        return f"{typed}\n{suffix}"

    def _set_editor_prompt_full_text(self, full_text: str):
        raw = str(full_text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        core, suffix = self._split_prompt_core_and_suffix(raw)
        self._editor_prompt_suffix_body = suffix
        if hasattr(self, "editor_final_prompt"):
            display_txt = raw if (getattr(self, "_editor_prompt_full_mode", False) or not suffix) else core
            self.editor_final_prompt.blockSignals(True)
            self.editor_final_prompt.setPlainText(display_txt)
            self.editor_final_prompt.blockSignals(False)
        self._refresh_editor_prompt_mode_btn()

    def _on_editor_prompt_mode_toggled(self, checked: bool):
        current_full = self._compose_editor_full_prompt()
        was_dirty = getattr(self, "_editor_dirty", False)
        was_loading = getattr(self, "_editor_loading", False)
        self._editor_loading = True
        try:
            self._editor_prompt_full_mode = bool(checked)
            self._set_editor_prompt_full_text(current_full)
        finally:
            self._editor_loading = was_loading
            self._editor_dirty = was_dirty

    def _copy_editor_final_prompt(self):
        txt = self._compose_editor_full_prompt().strip()
        if not txt:
            self.current_job.setText("ℹ️ 当前片段暂无可复制的最终 Flow 提示词")
            return
        QApplication.clipboard().setText(txt)
        self.current_job.setText("✅ 已复制当前片段的完整最终 Flow 提示词")

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if obj is self.table.viewport():
            et = event.type()
            if et == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._last_table_press_modifiers = event.modifiers()
            elif et == QEvent.Resize:
                if hasattr(self, "_table_hydrate_timer"):
                    self._table_hydrate_timer.start(60)
            elif et == QEvent.Show:
                QTimer.singleShot(0, self._hydrate_visible_table_widgets)
        if (
            obj is getattr(self, "_ctx_menu", None)
            and event.type() == QEvent.MouseButtonPress
            and event.button() == Qt.RightButton
        ):
            gp = event.globalPosition().toPoint()
            if not obj.rect().contains(obj.mapFromGlobal(gp)):
                vp = self.table.viewport()
                lp = vp.mapFromGlobal(gp)
                obj.close()
                if vp.rect().contains(lp):
                    QTimer.singleShot(0, lambda p=lp: self._show_table_context_menu(p))
                return True
        if obj is getattr(self, "editor_dialogue", None) and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (event.modifiers() & Qt.ControlModifier):
                cursor = self.editor_dialogue.textCursor()
                full_text = self.editor_dialogue.toPlainText()
                before = ' '.join(full_text[:cursor.selectionStart()].split())
                after = ' '.join(full_text[cursor.selectionEnd():].split())
                if before and after and self.editor_segment_id:
                    self._split_current_dialogue_at_cursor(before, after)
                event.accept()
                return True
        return super().eventFilter(obj, event)

    # ── Copy List Undo / Redo Stack (文案列表多步撤销与重做) ───────────────
    @staticmethod
    def _format_task_seq_label(task, fallback_sid=0) -> str:
        if task:
            try:
                return f"{int(task['video_seq']):02d}-{int(task['seg_seq']):02d}"
            except Exception:
                pass
        return f"#{int(fallback_sid)}" if fallback_sid else ""

    def _copy_undo_scope_key(self) -> tuple[str, int] | None:
        hid = self.host.currentData() if hasattr(self, "host") else None
        if not hid:
            return None
        return (str(work_dates.active() or ""), int(hid))

    def _can_undo_copy(self) -> bool:
        key = self._copy_undo_scope_key()
        return bool(key and self._copy_undo_stacks.get(key))

    def _can_redo_copy(self) -> bool:
        key = self._copy_undo_scope_key()
        return bool(key and self._copy_redo_stacks.get(key))

    def _copy_undo_menu_entries(self):
        key = self._copy_undo_scope_key()
        if not key:
            return []
        out = []
        ustack = self._copy_undo_stacks.get(key) or []
        rstack = self._copy_redo_stacks.get(key) or []
        if ustack:
            out.append((f"↩ 撤销：{ustack[-1]['label']} (⌘Z)", self.undo_copy_operation))
        if rstack:
            out.append((f"↪ 重做：{rstack[-1]['label']} (⇧⌘Z)", self.redo_copy_operation))
        return out

    def _record_copy_undo(
        self,
        label: str,
        video_ids,
        pre_snap: dict | None,
        *,
        prev_editor_sid=None,
        prev_checked=None,
        prev_history_ids=None,
    ):
        key = self._copy_undo_scope_key()
        vids = sorted({int(v) for v in (video_ids or []) if v})
        if not key or not vids or not pre_snap or not (pre_snap.get("videos") or {}):
            return
        stack = self._copy_undo_stacks.setdefault(key, [])
        stack.append({
            "label": str(label or "文案操作"),
            "video_ids": vids,
            "db_state": pre_snap,
            "editor_segment_id": int(prev_editor_sid) if prev_editor_sid else None,
            "checked_ids": set(prev_checked if prev_checked is not None else self.checked_ids),
            "history_editing_ids": set(
                prev_history_ids if prev_history_ids is not None else getattr(self, "_history_editing_ids", set())
            ),
            "scroll_val": self.table.verticalScrollBar().value() if hasattr(self, "table") else 0,
            "review_idx": self.review_filter.currentIndex() if hasattr(self, "review_filter") else 0,
        })
        while len(stack) > 30:
            stack.pop(0)
        self._copy_redo_stacks[key] = []
        self._refresh_copy_undo_ui()

    def _refresh_copy_undo_ui(self):
        if not hasattr(self, "undo_copy_btn"):
            return
        key = self._copy_undo_scope_key()
        ustack = (self._copy_undo_stacks.get(key) or []) if key else []
        rstack = (self._copy_redo_stacks.get(key) or []) if key else []
        if ustack:
            n = len(ustack)
            top = ustack[-1]["label"]
            recent = " → ".join(e["label"] for e in reversed(ustack[-3:]))
            self.undo_copy_btn.setText(f"↩ 撤销 ({n})")
            self.undo_copy_btn.setEnabled(True)
            self._set_tier(self.undo_copy_btn, "l2blue")
            self.undo_copy_btn.setToolTip(
                f"点击撤销上一步：{top}（快捷键 ⌘Z）\n当前主播可连续撤销 {n} 步：{recent}"
            )
        else:
            self.undo_copy_btn.setText("↩ 撤销")
            self.undo_copy_btn.setEnabled(False)
            self._set_tier(self.undo_copy_btn, "l3")
            self.undo_copy_btn.setToolTip(
                "暂无可撤销的文案操作（支持撤销文案修改、回车切分、合并、删除、AI自动整理、睁闭眼与模式切换 · 快捷键 ⌘Z）"
            )
        if hasattr(self, "redo_copy_btn"):
            if rstack:
                rtop = rstack[-1]["label"]
                self.redo_copy_btn.setEnabled(True)
                self._set_tier(self.redo_copy_btn, "l2")
                self.redo_copy_btn.setToolTip(f"重做上一步已撤销操作：{rtop}（快捷键 ⇧⌘Z）")
            else:
                self.redo_copy_btn.setEnabled(False)
                self._set_tier(self.redo_copy_btn, "l3")
                self.redo_copy_btn.setToolTip("暂无可重做的文案操作（快捷键 ⇧⌘Z）")

    def _shortcut_undo_copy(self):
        from PySide6.QtWidgets import QTextEdit
        fw = QApplication.focusWidget()
        if isinstance(fw, (QLineEdit, QPlainTextEdit, QTextEdit)):
            return
        if self._can_undo_copy():
            self.undo_copy_operation()

    def _shortcut_redo_copy(self):
        from PySide6.QtWidgets import QTextEdit
        fw = QApplication.focusWidget()
        if isinstance(fw, (QLineEdit, QPlainTextEdit, QTextEdit)):
            return
        if self._can_redo_copy():
            self.redo_copy_operation()

    def _apply_copy_history_transition(self, source_stack: list[dict], dest_stack: list[dict], *, is_redo: bool = False):
        if not source_stack:
            return
        entry = source_stack[-1]
        vids = list(entry.get("video_ids") or [])
        if self.worker and self.worker.isRunning() and hasattr(self.worker, "pending_segment_ids"):
            pending_sids = self.worker.pending_segment_ids()
            if pending_sids:
                busy_vid = any(
                    int(t["video_id"]) in set(vids) and int(t["segment_id"]) in pending_sids
                    for t in self.task_rows
                    if t["video_id"] is not None
                )
                if busy_vid:
                    QMessageBox.information(
                        self,
                        "正在生成提示词",
                        "该视频正在由 GPT 生成提示词，请等待几秒生成完成后再执行撤销/重做。",
                    )
                    return

        if getattr(self, "_editor_dirty", False) and getattr(self, "editor_segment_id", None):
            self._persist_inline_editor(show_message=False)

        counter_snap = repo.snapshot_video_copy_state(vids)
        counter_entry = {
            "label": entry["label"],
            "video_ids": vids,
            "db_state": counter_snap,
            "editor_segment_id": int(self.editor_segment_id) if self.editor_segment_id else None,
            "checked_ids": set(self.checked_ids),
            "history_editing_ids": set(getattr(self, "_history_editing_ids", set())),
            "scroll_val": self.table.verticalScrollBar().value(),
            "review_idx": self.review_filter.currentIndex() if hasattr(self, "review_filter") else 0,
        }
        try:
            res = repo.restore_video_copy_state(entry["db_state"])
        except Exception as exc:
            QMessageBox.warning(self, "重做文案操作" if is_redo else "撤销文案操作", str(exc))
            return

        source_stack.pop()
        dest_stack.append(counter_entry)
        while len(dest_stack) > 30:
            dest_stack.pop(0)

        self._editor_dirty = False
        self.checked_ids = set(entry.get("checked_ids") or set())
        self._history_editing_ids = set(entry.get("history_editing_ids") or set())
        want_rev = entry.get("review_idx")
        if hasattr(self, "review_filter") and want_rev in (0, 1) and self.review_filter.currentIndex() != want_rev:
            self.review_filter.blockSignals(True)
            self.review_filter.setCurrentIndex(want_rev)
            self.review_filter.blockSignals(False)

        target_sid = entry.get("editor_segment_id")
        if not target_sid and res.get("segment_ids"):
            target_sid = int(res["segment_ids"][0])
        self.editor_segment_id = int(target_sid) if target_sid else None

        self.reload_tasks()
        self._rebuild_host_cards()

        scroll_val = int(entry.get("scroll_val") or 0)
        if self.editor_segment_id:
            for r_idx, t in enumerate(self.task_rows):
                if int(t["segment_id"]) == int(self.editor_segment_id):
                    self.table.blockSignals(True)
                    self.table.selectRow(r_idx)
                    self.table.blockSignals(False)
                    break
        QTimer.singleShot(0, lambda v=scroll_val: self.table.verticalScrollBar().setValue(v))
        self._refresh_copy_undo_ui()

        if is_redo:
            self.current_job.setText(f"↪ 已重做：{entry['label']}")
        else:
            rem = len(source_stack)
            tail = f"（还可继续撤销 {rem} 步 · 点 ↪ 可重做）" if rem > 0 else "（点 ↪ 可重做）"
            self.current_job.setText(f"↩ 已撤销：{entry['label']}{tail}")

    def undo_copy_operation(self):
        key = self._copy_undo_scope_key()
        if not key:
            return
        ustack = self._copy_undo_stacks.setdefault(key, [])
        rstack = self._copy_redo_stacks.setdefault(key, [])
        if not ustack:
            self.current_job.setText("ℹ️ 当前主播暂无可撤销的文案操作")
            return
        self._apply_copy_history_transition(ustack, rstack, is_redo=False)

    def redo_copy_operation(self):
        key = self._copy_undo_scope_key()
        if not key:
            return
        ustack = self._copy_undo_stacks.setdefault(key, [])
        rstack = self._copy_redo_stacks.setdefault(key, [])
        if not rstack:
            return
        self._apply_copy_history_transition(rstack, ustack, is_redo=True)

    def _split_current_dialogue_at_cursor(self, before, after):
        if not self.editor_segment_id:
            return
        sid = int(self.editor_segment_id)
        was_checked = sid in self.checked_ids
        prev_checked = set(self.checked_ids)
        prev_hist = set(getattr(self, "_history_editing_ids", set()))
        if not hasattr(self, "_history_editing_ids"):
            self._history_editing_ids = set()
        self._history_editing_ids.add(sid)
        task = repo.get_prompt_task(sid)
        vid = int(task["video_id"]) if (task and task["video_id"] is not None) else 0
        tid = self._format_task_seq_label(task, sid)
        pre_snap = None
        try:
            if task:
                repo.set_video_special_requirements(
                    int(task["video_id"]), self.editor_image_rule.toPlainText().strip()
                )
                repo.update_segment_rule(
                    sid, self.editor_segment_rule.toPlainText().strip()
                )
                pre_snap = repo.snapshot_video_copy_state([vid]) if vid else None
            res = repo.edit_prompt_segment_text(sid, before + "\n" + after)
        except Exception as exc:
            QMessageBox.warning(self, "切分文案", str(exc))
            return
        if vid and pre_snap:
            self._record_copy_undo(
                f"切分文案 {tid}",
                [vid],
                pre_snap,
                prev_editor_sid=sid,
                prev_checked=prev_checked,
                prev_history_ids=prev_hist,
            )
        next_sid = res.get("next_segment_id") if isinstance(res, dict) else sid
        if isinstance(res, dict):
            for cid in (res.get("segment_ids") or []):
                self._history_editing_ids.add(int(cid))
                if was_checked:
                    self.checked_ids.add(int(cid))
        self._editor_dirty = False
        self.editor_segment_id = int(next_sid or sid)
        self.reload_tasks()
        self.current_job.setText("✂️ 已在光标处将后半段文案切换到下一行新片段（可按 ⌘Z 撤销）")

    def _dialogue_text_changed(self):
        self._update_editor_duration_label()
        if self._editor_loading or not self.editor_segment_id: return
        current=' '.join(self.editor_dialogue.toPlainText().split())
        loaded=getattr(self,'_loaded_dialogue','')
        if current != loaded:
            cur_prompt = self._compose_editor_full_prompt().strip()
            if cur_prompt:
                synced = repo.sync_dialogue_into_prompt(cur_prompt, loaded, current)
                if synced != cur_prompt:
                    self._set_editor_prompt_full_text(synced)
                self._loaded_dialogue = current
                self.editor_prompt_state.setText("● 文案已同步更新到提示词")
            else:
                self.editor_prompt_state.setText("● 文案已修改 · 待生成")

    def _set_one_generation_mode(self, segment_id, mode):
        task_info = next((t for t in self.task_rows if int(t["segment_id"]) == int(segment_id)), None) or repo.get_prompt_task(int(segment_id))
        vid = int(task_info["video_id"]) if (task_info and task_info["video_id"] is not None) else 0
        tid = self._format_task_seq_label(task_info, segment_id)
        pre_snap = repo.snapshot_video_copy_state([vid]) if vid else None
        prev_checked = set(self.checked_ids)
        prev_hist = set(getattr(self, "_history_editing_ids", set()))
        try:
            repo.set_segment_generation_mode(int(segment_id),mode,allow_active_rework=False,force_silent=True,clear_video_model=True)
            for i,t in enumerate(self.task_rows):
                if int(t['segment_id'])==int(segment_id):
                    fresh=repo.get_prompt_task(int(segment_id))
                    if fresh: self.task_rows[i]=fresh
                    break
            if vid and pre_snap:
                mode_zh = "帧模式" if str(mode).upper() == "FRAME" else "素材模式"
                self._record_copy_undo(
                    f"设为{mode_zh} {tid}",
                    [vid],
                    pre_snap,
                    prev_editor_sid=int(segment_id),
                    prev_checked=prev_checked,
                    prev_history_ids=prev_hist,
                )
        except Exception as exc:
            QMessageBox.warning(self,"切换模式",str(exc)); self.reload_tasks()

    def _batch_set_generation_mode(self, action):
        hid = self.host.currentData()
        if not hid:
            QMessageBox.information(self, "选择主播", "请先在上方选择一个具体的 AI 主播。")
            return
        host_rows = self._current_host_task_rows(visible_only=True)
        prev_checked = set(self.checked_ids)
        prev_hist = set(getattr(self, "_history_editing_ids", set()))
        if action=='selected_omini':
            ids=self.selected_segment_ids()
            if not ids:
                sid=self._selected_prompt_segment_id()
                if sid and any(int(t['segment_id']) == int(sid) for t in host_rows):
                    ids=[sid]
            if not ids:
                QMessageBox.information(self,"选中设为omini","请先勾选（或单击选中）需要设为 omini 模型生成的片段。"); return
            id_set = {int(x) for x in ids}
            cand_vids = sorted({int(t['video_id']) for t in host_rows if int(t['segment_id']) in id_set and t['video_id'] is not None})
            pre_snap = repo.snapshot_video_copy_state(cand_vids) if cand_vids else None
            result=repo.set_video_model_for_segments(ids,'flow_omni',duration_seconds=8,force_silent=True)
            changed_ids=set(result.get('changed_ids') or [])
            if changed_ids:
                for row, task in enumerate(self.task_rows):
                    if int(task['segment_id']) in changed_ids:
                        updated = dict(task)
                        updated['video_model'] = 'flow_omni'
                        updated['flow_duration_seconds'] = 8
                        self.task_rows[row] = updated
                        w = self.table.cellWidget(row, 6)
                        if isinstance(w, GenerationModeToggle):
                            w.setVideoModel('flow_omni')
                        m_item = self.table.item(row, 6)
                        if m_item is not None:
                            m_item.setToolTip("Omini")
                if cand_vids and pre_snap:
                    self._record_copy_undo(
                        f"设为 Omini（{len(changed_ids)}条）",
                        cand_vids,
                        pre_snap,
                        prev_editor_sid=self.editor_segment_id,
                        prev_checked=prev_checked,
                        prev_history_ids=prev_hist,
                    )
            self.current_job.setText(f"✅ 已将 {result.get('changed',0)} 条选中任务设为 Omini 模型生成视频（默认 8 秒）")
            return
        clear_vmodel = (action == 'all_frame')
        if action=='all_frame':
            target_mode = 'FRAME'
            cand_vids = sorted({int(t['video_id']) for t in host_rows if t['video_id'] is not None})
            pre_snap = repo.snapshot_video_copy_state(cand_vids) if cand_vids else None
            ids=[int(t['segment_id']) for t in host_rows]; result=repo.set_generation_mode_for_segments(ids,'FRAME',force_silent=True,clear_video_model=True)
            undo_lbl = f"全部设为帧（{result.get('changed', 0)}条）"
        elif action=='first_material':
            target_mode = 'MATERIAL'
            cand_vids = sorted({int(t['video_id']) for t in host_rows if t['video_id'] is not None})
            pre_snap = repo.snapshot_video_copy_state(cand_vids) if cand_vids else None
            result=repo.set_first_segment_mode_for_videos(set(cand_vids),'MATERIAL',force_silent=True)
            undo_lbl = f"首片设素材（{result.get('changed', 0)}条）"
        else:
            target_mode = 'MATERIAL'
            ids=self.selected_segment_ids()
            if not ids:
                QMessageBox.information(self,"设置素材模式","请先勾选需要设为素材的片段。"); return
            id_set = {int(x) for x in ids}
            cand_vids = sorted({int(t['video_id']) for t in host_rows if int(t['segment_id']) in id_set and t['video_id'] is not None})
            pre_snap = repo.snapshot_video_copy_state(cand_vids) if cand_vids else None
            result=repo.set_generation_mode_for_segments(ids,'MATERIAL',force_silent=True)
            undo_lbl = f"勾选设素材（{result.get('changed', 0)}条）"
        if int(result.get('changed', 0) or 0) > 0 and cand_vids and pre_snap:
            self._record_copy_undo(
                undo_lbl,
                cand_vids,
                pre_snap,
                prev_editor_sid=self.editor_segment_id,
                prev_checked=prev_checked,
                prev_history_ids=prev_hist,
            )
        self.current_job.setText(f"✅ 模式已更新：{result.get('changed',0)} 条；跳过/锁定 {result.get('blocked',0)} 条")
        changed_ids = set(result.get('changed_ids') or [])
        if changed_ids:
            for row, task in enumerate(self.task_rows):
                if int(task['segment_id']) in changed_ids:
                    updated = dict(task)
                    updated['generation_mode'] = target_mode
                    if clear_vmodel:
                        updated['video_model'] = ''
                    self.task_rows[row] = updated
                    w = self.table.cellWidget(row, 6)
                    if isinstance(w, GenerationModeToggle):
                        w.setMode(target_mode, emit=False, video_model=("" if clear_vmodel else None))
                    m_item = self.table.item(row, 6)
                    if m_item is not None:
                        vmod_now = str(updated.get("video_model") or "")
                        m_item.setToolTip("Omini" if vmod_now == "flow_omni" else ("素材" if target_mode == "MATERIAL" else "帧"))
        elif result.get('changed', 0) > 0:
            self.reload_tasks()

    def _selected_prompt_segment_id(self):
        rows=sorted({idx.row() for idx in self.table.selectionModel().selectedRows()})
        return int(self.task_rows[rows[0]]['segment_id']) if rows and 0<=rows[0]<len(self.task_rows) else 0

    def _delete_selected_prompt_segment(self):
        sid=self._selected_prompt_segment_id()
        if not sid: return
        if QMessageBox.question(self,"删除片段","删除当前 Flow 片段？同一完整视频后续片段会顺序补位，其他完整视频编号不会变化（删除后可点「↩ 撤销」恢复）。")!=QMessageBox.Yes: return
        if getattr(self, "_editor_dirty", False) and getattr(self, "editor_segment_id", None):
            self._persist_inline_editor(show_message=False)
        task_info = next((t for t in self.task_rows if int(t["segment_id"]) == int(sid)), None) or repo.get_prompt_task(int(sid))
        vid = int(task_info["video_id"]) if (task_info and task_info["video_id"] is not None) else 0
        tid = self._format_task_seq_label(task_info, sid)
        pre_snap = repo.snapshot_video_copy_state([vid]) if vid else None
        prev_checked = set(self.checked_ids)
        prev_hist = set(getattr(self, "_history_editing_ids", set()))
        try: repo.edit_prompt_segment_text(sid,'')
        except Exception as exc: QMessageBox.warning(self,"删除片段",str(exc)); return
        if vid and pre_snap:
            self._record_copy_undo(
                f"删除片段 {tid}",
                [vid],
                pre_snap,
                prev_editor_sid=int(sid),
                prev_checked=prev_checked,
                prev_history_ids=prev_hist,
            )
        self.checked_ids.discard(sid); self.editor_segment_id=None; self.reload_tasks()
        self.current_job.setText(f"✅ 已删除片段 {tid}，后续序号已自动顺延（可点「↩ 撤销」或 ⌘Z 恢复）")

    def _set_selected_prompt_type(self):
        sid=self._selected_prompt_segment_id()
        if not sid:return
        label,ok=QInputDialog.getItem(self,'片段类型','手动选择类型',['睁眼说话','闭眼祷告'],0,False)
        if not ok:return
        if getattr(self, "_editor_dirty", False) and getattr(self, "editor_segment_id", None):
            self._persist_inline_editor(show_message=False)
        task_info = next((t for t in self.task_rows if int(t["segment_id"]) == int(sid)), None) or repo.get_prompt_task(int(sid))
        vid = int(task_info["video_id"]) if (task_info and task_info["video_id"] is not None) else 0
        tid = self._format_task_seq_label(task_info, sid)
        pre_snap = repo.snapshot_video_copy_state([vid]) if vid else None
        prev_checked = set(self.checked_ids)
        prev_hist = set(getattr(self, "_history_editing_ids", set()))
        try:repo.set_prompt_segment_type(sid,'TALKING' if label=='睁眼说话' else 'PRAYING')
        except Exception as exc:QMessageBox.warning(self,'片段类型',str(exc));return
        eye_txt = '睁眼' if label == '睁眼说话' else '闭眼'
        if vid and pre_snap:
            self._record_copy_undo(
                f"设为{eye_txt} {tid}",
                [vid],
                pre_snap,
                prev_editor_sid=int(sid),
                prev_checked=prev_checked,
                prev_history_ids=prev_hist,
            )
        self.editor_segment_id=None;self.reload_tasks()
        self.current_job.setText(f"✅ 已设为{eye_txt}（{tid}）")

    def _merge_selected_prompt_segment(self, direction):
        sid=self._selected_prompt_segment_id()
        if not sid: return
        label,ok=QInputDialog.getItem(self,'合并文案','合并后的片段类型',['睁眼说话','闭眼祷告'],0,False)
        if not ok:return
        if getattr(self, "_editor_dirty", False) and getattr(self, "editor_segment_id", None):
            self._persist_inline_editor(show_message=False)
        task_info = next((t for t in self.task_rows if int(t["segment_id"]) == int(sid)), None) or repo.get_prompt_task(int(sid))
        vid = int(task_info["video_id"]) if (task_info and task_info["video_id"] is not None) else 0
        tid = self._format_task_seq_label(task_info, sid)
        pre_snap = repo.snapshot_video_copy_state([vid]) if vid else None
        prev_checked = set(self.checked_ids)
        prev_hist = set(getattr(self, "_history_editing_ids", set()))
        try: repo.merge_prompt_segment(sid,direction,'TALKING' if label=='睁眼说话' else 'PRAYING')
        except Exception as exc: QMessageBox.warning(self,"合并文案",str(exc)); return
        if vid and pre_snap:
            dir_zh = "合并到上一片" if str(direction).lower() == "prev" else "合并到下一片"
            self._record_copy_undo(
                f"{dir_zh} {tid}",
                [vid],
                pre_snap,
                prev_editor_sid=int(sid),
                prev_checked=prev_checked,
                prev_history_ids=prev_hist,
            )
        self.checked_ids.discard(sid); self.editor_segment_id=None; self.reload_tasks()
        self.current_job.setText(f"✅ 已合并相邻片段文案并重算时长（可点「↩ 撤销」或 ⌘Z 恢复）")

    def _ai_reorganize_scripts(self):
        hid = self.host.currentData()
        if not hid:
            QMessageBox.information(self, "AI自动整理", "请先在上方选择一个具体的 AI 主播。")
            return
        if getattr(self, "_editor_dirty", False):
            self._persist_inline_editor(show_message=False)

        host_rows = self._current_host_task_rows(visible_only=True)
        checked_sids = set(self.selected_segment_ids())
        if checked_sids:
            target_vids = sorted({
                int(t["video_id"]) for t in host_rows
                if int(t["segment_id"]) in checked_sids and t["video_id"] is not None
            })
            scope_desc = f"已勾选的 {len(target_vids)} 个完整视频"
        else:
            target_vids = sorted({
                int(t["video_id"]) for t in host_rows
                if t["video_id"] is not None
            })
            scope_desc = f"当前列表中的 {len(target_vids)} 个完整视频"

        if not target_vids:
            QMessageBox.information(self, "AI自动整理", "当前文案列表中没有可整理的任务。")
            return

        pending_sids = (
            self.worker.pending_segment_ids()
            if (self.worker and self.worker.isRunning() and hasattr(self.worker, "pending_segment_ids"))
            else set()
        )
        if pending_sids:
            busy_vids = {
                int(t["video_id"]) for t in host_rows
                if int(t["segment_id"]) in pending_sids and t["video_id"] is not None
            }
            if any(vid in busy_vids for vid in target_vids):
                target_vids = [vid for vid in target_vids if vid not in busy_vids]
                if not target_vids:
                    QMessageBox.information(
                        self,
                        "AI自动整理",
                        "当前视频正在使用 GPT API 写提示词，不能直接整理。\n请等待该视频提示词生成完成，或切换到其他未在生成提示词的主播/视频。",
                    )
                    return
                scope_desc = f"未在生成提示词的 {len(target_vids)} 个完整视频（已跳过正在用 GPT 生成的视频）"

        prev_checked = set(self.checked_ids)
        prev_hist = set(getattr(self, "_history_editing_ids", set()))
        prev_ed_sid = self.editor_segment_id
        pre_snap = repo.snapshot_video_copy_state(target_vids)

        self._progress_hide_timer.stop()
        self.progress.setRange(0, 0)
        self.progress.show()
        self.current_job.setText(f"⚡ 正在 AI自动整理（{scope_desc}）…")
        QApplication.processEvents()

        try:
            res = repo.ai_reorganize_video_segments(
                target_vids,
                target_sec=7.0,
                max_sec=7.8,
                hard_max_sec=8.0,
            )
        except Exception as exc:
            self.progress.setRange(0, 100)
            self.progress.hide()
            self.current_job.setText(f"⚠ AI自动整理失败：{str(exc)[:100]}")
            QMessageBox.warning(self, "AI自动整理失败", str(exc))
            return

        v_chg = int(res.get("videos_changed") or 0)
        if v_chg > 0 and pre_snap:
            self._record_copy_undo(
                f"AI自动整理（{v_chg}个视频）",
                target_vids,
                pre_snap,
                prev_editor_sid=prev_ed_sid,
                prev_checked=prev_checked,
                prev_history_ids=prev_hist,
            )

        changed_sids = res.get("changed_segment_ids") or []
        if not hasattr(self, "_history_editing_ids"):
            self._history_editing_ids = set()
        for csid in changed_sids:
            self._history_editing_ids.add(int(csid))
            if checked_sids:
                self.checked_ids.add(int(csid))

        self._editor_dirty = False
        self.editor_segment_id = None
        self.reload_tasks()
        self._rebuild_host_cards()

        v_proc = int(res.get("videos_processed") or 0)
        v_skip = int(res.get("videos_skipped_locked") or 0)
        old_cnt = int(res.get("old_segments") or 0)
        new_cnt = int(res.get("new_segments") or 0)
        avg_s = float(res.get("avg_seconds") or 0.0)
        max_s = float(res.get("max_seconds") or 0.0)
        skip_note = f"（已自动保护跳过 {v_skip} 个已生成/已提交视频）" if v_skip > 0 else ""
        summary_msg = (
            f"✨ AI自动整理完成（{scope_desc}）：已调整 {v_chg}/{v_proc} 个视频{skip_note}，"
            f"片段 {old_cnt} → {new_cnt} 条，平均约 {avg_s:.1f}s（最高 {max_s:.1f}s），原文分字未改"
        )
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self._progress_hide_timer.start(1600)
        self.current_job.setText(summary_msg)

    def _prompt_table_item_changed(self, item):
        if getattr(self,'_table_loading',False) or item.column()!=4: return
        row=item.row()
        if row<0 or row>=len(self.task_rows): return
        task_row = self.task_rows[row]
        sid=int(task_row['segment_id'])
        old=' '.join(str(task_row['foreign_text'] or '').split())
        raw_text=str(item.text() or '').replace('\r\n','\n').replace('\r','\n')
        parts=[' '.join(line.split()) for line in raw_text.split('\n') if ' '.join(line.split())]
        if len(parts)==1 and parts[0]==old: return
        if getattr(self, "_editor_dirty", False) and getattr(self, "editor_segment_id", None):
            self._persist_inline_editor(show_message=False)
        vid = int(task_row['video_id']) if task_row['video_id'] is not None else 0
        tid = self._format_task_seq_label(task_row, sid)
        pre_snap = repo.snapshot_video_copy_state([vid]) if vid else None
        prev_checked = set(self.checked_ids)
        prev_hist = set(getattr(self, "_history_editing_ids", set()))
        was_checked=sid in self.checked_ids
        if not hasattr(self, "_history_editing_ids"):
            self._history_editing_ids = set()
        self._history_editing_ids.add(sid)
        try:
            res=repo.edit_prompt_segment_text(sid, '\n'.join(parts))
        except Exception as exc:
            QMessageBox.warning(self,"修改文案",str(exc))
            QTimer.singleShot(0, self.reload_tasks)
            return
        if vid and pre_snap:
            if not parts:
                undo_lbl = f"清空删除片段 {tid}"
            elif len(parts) > 1:
                undo_lbl = f"回车切分文案 {tid}"
            else:
                undo_lbl = f"修改文案 {tid}"
            self._record_copy_undo(
                undo_lbl,
                [vid],
                pre_snap,
                prev_editor_sid=sid,
                prev_checked=prev_checked,
                prev_history_ids=prev_hist,
            )
        if not parts:
            self.checked_ids.discard(sid)
            self._history_editing_ids.discard(sid)
            self.editor_segment_id=None
            self.current_job.setText(f"🗑 已清空并删除片段 {tid}（可点「↩ 撤销」或 ⌘Z 恢复）")
        else:
            if isinstance(res, dict):
                for cid in (res.get('segment_ids') or []):
                    self._history_editing_ids.add(int(cid))
                    if was_checked:
                        self.checked_ids.add(int(cid))
            next_sid=res.get('next_segment_id') if isinstance(res, dict) else sid
            self.editor_segment_id=int(next_sid or sid)
            if len(parts)>1:
                self.current_job.setText(f"✂️ 已按回车拆分 {tid}，后半段已切到下一行新片段（可按 ⌘Z 撤销）")
            else:
                self.current_job.setText(f"✏️ 文案 {tid} 已修改并自动同步到提示词（可按 ⌘Z 撤销）")
        self._editor_dirty=False
        QTimer.singleShot(0, self.reload_tasks)

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
        self._hydrate_visible_table_widgets()

    def _select_all_visible(self):
        for row, task in enumerate(self.task_rows):
            if self.table.isRowHidden(row):
                continue
            sid = int(task["segment_id"])
            self.checked_ids.add(sid)
            cell = self._cell_check(row)
            if cell is not None:
                try:
                    cell.setChecked(True, block=True)
                except Exception:
                    pass
        self.update_header_check()

    def _clear_card_layout(self, layout):
        while layout.count():
            item=layout.takeAt(0); w=item.widget()
            if w: w.deleteLater()

    def _rebuild_recipient_cards(self):
        if not hasattr(self, "recipient_cards"):
            return
        self._clear_card_layout(self.recipient_cards)
        current = self.recipient.currentData()
        recipients = list(repo.list_recipients(work_date=work_dates.active()))

        def add_recipient_card(title, subtitle, rid=None):
            selected = (current is None and rid is None) or (rid is not None and current == rid)
            card = QFrame(objectName="recipientCard")
            card.setProperty("selected", selected)
            card.setFixedSize(168, 32)
            box = QHBoxLayout(card)
            box.setContentsMargins(10, 2, 10, 2)
            box.setSpacing(6)
            name = QLabel(title)
            name.setStyleSheet("font-weight:750; font-size:13px;")
            box.addWidget(name)
            box.addStretch(1)
            meta = QLabel(subtitle, objectName="muted")
            meta.setStyleSheet("font-size:11.5px;")
            box.addWidget(meta)
            hit = QPushButton(card)
            hit.setObjectName("transparentHit")
            hit.setCursor(Qt.PointingHandCursor)
            hit.setGeometry(card.rect())
            hit.clicked.connect(
                lambda _=False, x=rid: self.recipient.setCurrentIndex(0) if x is None else self._select_recipient_id(x)
            )
            self.recipient_cards.addWidget(card)

        for r in recipients:
            rid = int(r["id"])
            name = str(r["name"] or "未命名")
            count = int(r["host_count"] or 0)
            add_recipient_card(name, f"{count} 主播", rid)
        self.recipient_cards.addStretch(1)

    def _select_recipient_id(self, rid):
        i = self.recipient.findData(rid)
        if i >= 0:
            self.recipient.setCurrentIndex(i)

    def _select_host_id(self, hid):
        i = self.host.findData(hid)
        if i >= 0:
            self.host.setCurrentIndex(i)

    @staticmethod
    def _sort_hosts_unsubmitted_first(hosts: list, tasks_by_host: dict[int, list]) -> list:
        """Keep unsubmitted/partially-submitted hosts at the front and move fully submitted ('✓ 已提交') hosts to the end."""
        def _sort_key(indexed_host):
            idx, h = indexed_host
            ts = tasks_by_host.get(int(h["id"]), [])
            total = len(ts)
            submitted = sum(1 for t in ts if str(t["prompt_review_status"] or "") == "已提交")
            fully_submitted = (total > 0 and submitted >= total)
            return (1 if fully_submitted else 0, idx)

        return [h for _, h in sorted(enumerate(hosts), key=_sort_key)]

    def _ensure_host_card_visible(self, card_widget):
        try:
            if card_widget is not None and hasattr(self, "host_scroll"):
                self.host_scroll.ensureWidgetVisible(card_widget, 16, 0)
        except RuntimeError:
            pass

    def _post_submit_advance_host(self, submitted_hid: int | None, pre_order: list[int]) -> tuple[int | None, str, bool]:
        """Rebuild sorted host cards after Flow submission and auto-advance to the next unsubmitted host if current host finished.

        Returns (next_hid, next_host_name, all_hosts_submitted).
        """
        rid = self.recipient.currentData()
        if not rid or not submitted_hid:
            self.reload_tasks()
            self._rebuild_host_cards()
            return None, "", False

        raw_hosts = list(repo.list_hosts(rid, work_date=work_dates.active()))
        tasks_by_host: dict[int, list] = {}
        for t in repo.list_prompt_tasks(rid, None, "全部", work_date=work_dates.active()):
            tasks_by_host.setdefault(int(t["host_id"]), []).append(t)

        cur_tasks = tasks_by_host.get(int(submitted_hid), [])
        cur_unsubmitted = sum(1 for t in cur_tasks if str(t["prompt_review_status"] or "") != "已提交")
        if cur_unsubmitted > 0 or self._is_history_workspace():
            # Current host still has unsubmitted segments (or user is editing history) -> stay on current host.
            self._rebuild_host_cards()
            self.reload_tasks()
            return None, "", False

        host_name_by_id = {int(h["id"]): str(h["name"] or "未命名主播") for h in raw_hosts}
        order = [int(x) for x in (pre_order or []) if int(x) in host_name_by_id]
        for h in raw_hosts:
            hid = int(h["id"])
            if hid not in order:
                order.append(hid)

        if int(submitted_hid) in order:
            pos = order.index(int(submitted_hid))
            candidates = order[pos + 1:] + order[:pos]
        else:
            candidates = [hid for hid in order if hid != int(submitted_hid)]

        next_hid = None
        for cand in candidates:
            ts = tasks_by_host.get(int(cand), [])
            if ts and any(str(t["prompt_review_status"] or "") != "已提交" for t in ts):
                next_hid = int(cand)
                break

        # Rebuild host cards first so the newly '✓ 已提交' host moves to the end of the queue and self.host order syncs.
        self._rebuild_host_cards()
        if next_hid is not None and next_hid != int(submitted_hid):
            idx = self.host.findData(next_hid)
            if idx >= 0:
                if self.host.currentIndex() != idx:
                    self.host.setCurrentIndex(idx)
                else:
                    self.host_changed()
            return next_hid, host_name_by_id.get(next_hid, ""), False

        self.reload_tasks()
        all_done = bool(raw_hosts) and all(
            len(tasks_by_host.get(int(h["id"]), [])) > 0
            and all(str(t["prompt_review_status"] or "") == "已提交" for t in tasks_by_host.get(int(h["id"]), []))
            for h in raw_hosts
        )
        return None, "", all_done

    def _rebuild_host_cards(self):
        if not hasattr(self, "host_cards"):
            return
        self._clear_card_layout(self.host_cards)
        self._host_card_widgets = {}
        rid = self.recipient.currentData()
        current = self.host.currentData()
        self._host_cards_rid = rid
        all_recs = list(repo.list_recipients(work_date=work_dates.active()))
        any_hosts = any(int(r["host_count"] or 0) > 0 for r in all_recs)
        if hasattr(self, "nav_card"):
            # No hosts anywhere today → hide the whole navigator; the guide bar already explains what to do.
            self.nav_card.setVisible(any_hosts)
        if not rid:
            self._ordered_host_ids = []
            self.host_section_title.setText("AI 主播 · 暂无接收人")
            if hasattr(self, "recipient_row_widget"):
                self.recipient_row_widget.setVisible(bool(all_recs))
            if hasattr(self, "host_scroll"):
                self.host_scroll.setVisible(False)
            return

        rec = repo.get_recipient(rid)
        hosts = list(repo.list_hosts(rid, work_date=work_dates.active()))
        self.host_section_title.setText(f"AI 主播 ({len(hosts)})")

        if hasattr(self, "recipient_row_widget"):
            self.recipient_row_widget.setVisible(True)
        if hasattr(self, "host_scroll"):
            self.host_scroll.setVisible(bool(hosts))
        if not hosts:
            self._ordered_host_ids = []
            return

        tasks_by_host: dict[int, list] = {}
        for t in repo.list_prompt_tasks(rid, None, "全部", work_date=work_dates.active()):
            tasks_by_host.setdefault(int(t["host_id"]), []).append(t)

        hosts = self._sort_hosts_unsubmitted_first(hosts, tasks_by_host)
        self._ordered_host_ids = [int(h["id"]) for h in hosts]

        # Keep self.host combo items ordered identically to the visual host card queue.
        self.host.blockSignals(True)
        self.host.clear()
        self.host.addItem("全部", None)
        for h in hosts:
            self.host.addItem(h["name"], h["id"])
        cur_idx = self.host.findData(current) if current else -1
        if cur_idx > 0:
            self.host.setCurrentIndex(cur_idx)
        elif self.host.count() > 1:
            self.host.setCurrentIndex(1)
        self.host.blockSignals(False)
        current = self.host.currentData()

        selected_card_widget = None
        for h in hosts:
            hid = int(h["id"])
            tasks = tasks_by_host.get(hid, [])
            generated = sum(1 for t in tasks if str(t["prompt"] or "").strip())
            total = len(tasks)
            submitted = sum(1 for t in tasks if str(t["prompt_review_status"] or "") == "已提交")
            talking = sum(
                1
                for t in tasks
                if t["segment_type_source"] != "unclassified" and str(t["performance_mode"] or "").upper() != "PRAYING"
            )
            praying = sum(
                1
                for t in tasks
                if t["segment_type_source"] != "unclassified" and str(t["performance_mode"] or "").upper() == "PRAYING"
            )
            selected = current == hid
            card = _ClickableHostCard()
            card.setProperty("selected", selected)
            card.setFixedSize(236, 86)
            card.setToolTip(f"点击切换到主播：{h['name'] or '未命名主播'}")
            card.clicked.connect(lambda x=hid: self._select_host_id(x))
            row = QHBoxLayout(card)
            row.setContentsMargins(7, 5, 7, 5)
            row.setSpacing(8)
            image_label = QLabel(objectName="hostThumb")
            image_label.setFixedSize(50, 68)
            image_label.setAlignment(Qt.AlignCenter)
            image_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            image = resolve_anchor_thumbnail(hid)
            set_image_async(image_label, image, QSize(50, 68))
            row.addWidget(image_label)
            right = QVBoxLayout()
            right.setSpacing(2)
            title_row = QHBoxLayout()
            title_row.setContentsMargins(0, 0, 0, 0)
            title_row.setSpacing(5)
            title = QLabel(str(h["name"] or "未命名主播"), objectName="hostName")
            title.setStyleSheet("font-size:14.5px; font-weight:800;")
            title.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            title_row.addWidget(title)
            if total > 0 and submitted > 0:
                sub_text = "✓" if submitted >= total else f"✓ {submitted}/{total}"
                sub_badge = QLabel(sub_text, objectName="miniTagSubmitted")
                sub_badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                title_row.addWidget(sub_badge)
            elif total > 0 and generated > 0:
                gen_badge = QLabel(f"{generated}/{total}", objectName="miniTag")
                gen_badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                title_row.addWidget(gen_badge)
            title_row.addStretch(1)
            right.addLayout(title_row)
            chips = QHBoxLayout()
            chips.setSpacing(4)
            if talking > 0:
                a = QLabel(f"睁眼 {talking}", objectName="miniTag")
                a.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                chips.addWidget(a)
            if praying > 0:
                b = QLabel(f"闭眼 {praying}", objectName="miniTagAlt")
                b.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                chips.addWidget(b)
            raw_ratio = (
                h["aspect_ratio"]
                if "aspect_ratio" in h.keys() and h["aspect_ratio"]
                else (h["flow_aspect_ratio"] if "flow_aspect_ratio" in h.keys() and h["flow_aspect_ratio"] else "")
            )
            host_ratio = (
                repo.normalize_aspect_ratio(raw_ratio)
                if str(raw_ratio or "").strip()
                else repo.get_host_aspect_ratio(hid, work_date=work_dates.active())
            )
            if host_ratio not in ("9:16", "16:9"):
                host_ratio = "9:16"
            ratio_tag = QLabel("16:9" if host_ratio == "16:9" else "9:16", objectName="miniTag")
            ratio_tag.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            if host_ratio == "16:9":
                ratio_tag.setStyleSheet(
                    "background:#2563EB;color:#FFFFFF;border-radius:4px;padding:1px 6px;font-size:11px;font-weight:700;"
                )
            chips.addWidget(ratio_tag)
            chips.addStretch(1)
            right.addLayout(chips)
            actions = QHBoxLayout()
            actions.setSpacing(0)
            actions.setContentsMargins(0, 1, 0, 0)
            settings_btn = QPushButton("⚙ 人物设置", objectName="pcHostPersonaBtn")
            settings_btn.setCursor(Qt.PointingHandCursor)
            settings_btn.setFixedHeight(28)
            settings_btn.setProperty("hostSelected", selected)
            settings_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            settings_btn.setToolTip("设置该主播的人物表演、动作与镜头预设")
            settings_btn.clicked.connect(lambda _=False, x=hid: self._open_generation_rules_for_host(x))
            actions.addWidget(settings_btn, 1)
            right.addLayout(actions)
            row.addLayout(right, 1)
            self.host_cards.addWidget(card)
            if selected:
                selected_card_widget = card
            self._host_card_widgets[hid] = {
                "card": card,
                "settings_btn": settings_btn,
                "ratio_tag": ratio_tag,
            }
        self.host_cards.addStretch(1)
        total_cards_w = len(hosts) * 236 + max(0, len(hosts) - 1) * 9
        self.host_card_content.setMinimumSize(total_cards_w, 88)
        if selected_card_widget is not None:
            QTimer.singleShot(0, lambda w=selected_card_widget: self._ensure_host_card_visible(w))

    def _open_generation_rules_for_host(self, hid):
        i=self.host.findData(hid)
        if i>=0:
            self.host.setCurrentIndex(i)
        self.open_generation_rules()

    def host_changed(self):
        if not self.host.currentData() and self.host.count() > 1:
            self.host.blockSignals(True)
            self.host.setCurrentIndex(1)
            self.host.blockSignals(False)
        self._sync_checked_host_scope()
        rid = self.recipient.currentData()
        current = self.host.currentData()
        card_map = getattr(self, '_host_card_widgets', None)
        if card_map and getattr(self, '_host_cards_rid', None) == rid:
            selected_card_widget = None
            for hid, refs in card_map.items():
                selected = (current == hid)
                card = refs.get('card')
                sbtn = refs.get('settings_btn')
                if selected and card is not None:
                    selected_card_widget = card
                if card is not None and bool(card.property('selected')) != selected:
                    card.setProperty('selected', selected)
                    card.style().unpolish(card)
                    card.style().polish(card)
                    card.update()
                if sbtn is not None and bool(sbtn.property('hostSelected')) != selected:
                    self._set_prop(sbtn, 'hostSelected', selected)
            if selected_card_widget is not None:
                QTimer.singleShot(0, lambda w=selected_card_widget: self._ensure_host_card_visible(w))
        else:
            self._rebuild_host_cards()
        self.reload_tasks()
        # Propagate host selection to child tabs ONLY if we are not currently in that tab




    def reload_filters(self):
        worker_busy = bool(self.worker and self.worker.isRunning())
        if not worker_busy:
            from app.services.eye_states import reconcile_saved_colors
            reconcile_saved_colors(work_dates.active())
            try:
                repo.auto_merge_ungenerated_short_segments(work_date=work_dates.active(), max_words=24)
            except Exception:
                pass
        previous_recipient=self.recipient.currentData()
        self.recipient.blockSignals(True)
        self.recipient.clear()
        for r in repo.list_recipients(work_date=work_dates.active()):
            self.recipient.addItem(r["name"], r["id"])
        previous_index=self.recipient.findData(previous_recipient)
        if previous_index>=0:
            self.recipient.setCurrentIndex(previous_index)
        elif self.recipient.count()>0:
            self.recipient.setCurrentIndex(0)
        self.recipient.blockSignals(False)
        self._rebuild_recipient_cards()
        # auto_merge already ran above; do not run the same pass twice per refresh.
        self._skip_auto_merge_once = True
        try:
            self.recipient_changed()
        finally:
            self._skip_auto_merge_once = False
        self.refresh_api_status()
        try:
            self._nav_data_sig = self._navigation_signature()
        except Exception:
            self._nav_data_sig = None

    def _navigation_signature(self):
        """Cheap fingerprint of everything this page renders from the database.

        Plugin heartbeats and Flow scheduling touch the SQLite WAL every second, so the
        file timestamp cannot tell whether GPT-page data really changed.
        """
        import hashlib
        day = work_dates.active()
        parts = [day]
        for r in repo.list_recipients(work_date=day):
            parts.append(tuple(r))
            for h in repo.list_hosts(r["id"], work_date=day):
                parts.append(tuple(h))
        for t in repo.list_prompt_tasks(None, None, "全部", work_date=day):
            parts.append(tuple(t))
        return hashlib.sha1(repr(parts).encode("utf-8", "surrogatepass")).hexdigest()

    def refresh_if_changed(self):
        """Navigation refresh: keep the already-rendered page when its data is unchanged."""
        if not (self.worker and self.worker.isRunning()):
            from app.services.eye_states import reconcile_saved_colors
            reconcile_saved_colors(work_dates.active())
            try:
                repo.auto_merge_ungenerated_short_segments(work_date=work_dates.active(), max_words=24)
            except Exception:
                pass
        try:
            sig = self._navigation_signature()
        except Exception:
            sig = None
        if sig is not None and sig == getattr(self, "_nav_data_sig", None):
            return
        self.reload_filters()

    def refresh_api_status(self):
        model = repo.get_setting("openai_model", "gpt-5.6-luna")
        detail = repo.get_setting("image_detail", "low") or "low"
        detail_name = {"low":"低成本图像", "auto":"自动图像", "high":"高细节图像"}.get(detail, detail)
        key = "已连接钥匙串" if openai_service.get_api_key() else "未设置API Key"
        self.api_status.setText(f"{model} · {detail_name} · {key}")

    def _refresh_daily_cost_chip(self, work_summary=None, visible_video_count: int | None = None):
        if not hasattr(self, "cost_label"):
            return
        from datetime import datetime
        today_str = datetime.now().strftime("%Y-%m-%d")
        active_wd = str(work_dates.active() or today_str)
        target_day = active_wd if (len(active_wd) == 10 and active_wd[4] == "-") else today_str
        is_today = (target_day == today_str)
        try:
            day_stat = repo.daily_api_usage_breakdown(target_day)
        except Exception:
            day_stat = {"day": target_day, "input_tokens": 0, "cached_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "request_count": 0}
        if work_summary is None:
            try:
                work_summary = repo.prompt_usage_breakdown(work_date=work_dates.active())
            except Exception:
                work_summary = day_stat

        day_cost = float(day_stat.get("cost_usd") or 0.0)
        day_reqs = int(day_stat.get("request_count") or 0)
        day_in = int(day_stat.get("input_tokens") or 0)
        day_cached = int(day_stat.get("cached_tokens") or 0)
        day_out = int(day_stat.get("output_tokens") or 0)
        cache_pct = (100.0 * day_cached / day_in) if day_in > 0 else 0.0

        prefix = "💰 今日累计" if is_today else f"💰 当日累计({target_day[5:]})"
        self.cost_label.setText(f"{prefix} ${day_cost:.4f}")

        tip_lines = [
            f"{'今日' if is_today else target_day} GPT API 实时累计（本地自然日）：${day_cost:.4f}（{day_reqs} 次请求）",
            f"· 输入 tokens：{day_in:,}",
            f"· 缓存命中 tokens：{day_cached:,}（命中率 {cache_pct:.1f}%，享 90% 折扣）",
            f"· 输出 tokens：{day_out:,}",
        ]
        ws_cost = float((work_summary or {}).get("cost_usd") or 0.0)
        if abs(ws_cost - day_cost) >= 0.0001:
            tip_lines.append(f"· 当前工作区（{active_wd}）任务关联成本：${ws_cost:.4f}")
        if visible_video_count is not None:
            tip_lines.append(f"· 当前列表按参考图合并后预计请求：{visible_video_count} 次")
        tip_text = "\n".join(tip_lines)
        self.cost_label.setToolTip(tip_text)
        self.api_status.setToolTip(tip_text)

    def recipient_changed(self):
        rid = self.recipient.currentData()
        previous_host = self.host.currentData()
        worker_busy = bool(self.worker and self.worker.isRunning())
        raw_hosts = []
        if rid:
            raw_hosts = list(repo.list_hosts(rid, work_date=work_dates.active()))
            for h in raw_hosts:
                if not getattr(self,"_date_view_refresh",False) and not worker_busy:
                    repo.ensure_flow_segments_for_host(h["id"])
        else:
            for r in repo.list_recipients(work_date=work_dates.active()):
                for h in repo.list_hosts(r["id"], work_date=work_dates.active()):
                    if not getattr(self,"_date_view_refresh",False) and not worker_busy:
                        repo.ensure_flow_segments_for_host(h["id"])

        if not worker_busy and not getattr(self, "_skip_auto_merge_once", False):
            try:
                repo.auto_merge_ungenerated_short_segments(work_date=work_dates.active(), max_words=24)
            except Exception:
                pass

        ordered_hosts = []
        if rid and raw_hosts:
            tasks_by_host: dict[int, list] = {}
            for t in repo.list_prompt_tasks(rid, None, "全部", work_date=work_dates.active()):
                tasks_by_host.setdefault(int(t["host_id"]), []).append(t)
            ordered_hosts = self._sort_hosts_unsubmitted_first(raw_hosts, tasks_by_host)

        self.host.blockSignals(True)
        self.host.clear()
        self.host.addItem("全部", None)
        for h in ordered_hosts:
            self.host.addItem(h["name"], h["id"])

        previous_host_index = self.host.findData(previous_host) if previous_host else -1
        if previous_host_index > 0:
            self.host.setCurrentIndex(previous_host_index)
        elif self.host.count() > 1:
            # Default: strictly select the first unsubmitted concrete host at the head of the queue.
            self.host.setCurrentIndex(1)

        self.host.blockSignals(False)
        self._sync_checked_host_scope()
        self._rebuild_recipient_cards()
        self._rebuild_host_cards()
        self.reload_tasks()

    def _apply_prompt_state_item(self, item: QTableWidgetItem | None, state_key: str, prompt_text: str = ""):
        if item is None:
            return
        ptxt = str(prompt_text or "").strip()
        dot_font = getattr(self, "_prompt_dot_font", None)
        if dot_font is None:
            dot_font = QFont(self.table.font())
            dot_font.setPointSize(13)
            dot_font.setBold(True)
            self._prompt_dot_font = dot_font
        item.setFont(dot_font)
        item.setTextAlignment(Qt.AlignCenter)
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        if state_key == "生成中…":
            item.setText("⚡")
            item.setForeground(QColor("#2563EB"))
            item.setToolTip("⚡ 生成中…" + (f"\n\n{ptxt}" if ptxt else ""))
        elif state_key == "文案已改":
            item.setText("●")
            item.setForeground(QColor("#D97706"))
            item.setToolTip(
                "● 文案已改（新文案已自动同步至提示词；可直接提交或重新生成）"
                + (f"\n\n{ptxt}" if ptxt else "")
            )
        elif state_key == "失败":
            item.setText("✕")
            item.setForeground(QColor("#DC2626"))
            item.setToolTip("✕ 生成失败" + (f"\n\n{ptxt}" if ptxt else ""))
        elif state_key == "已填":
            item.setText("●")
            item.setForeground(QColor("#16A34A"))
            item.setToolTip("✓ 已填提示词" + (f"\n\n{ptxt}" if ptxt else ""))
        else:
            item.setText("○")
            item.setForeground(QColor("#94A3B8"))
            item.setToolTip("○ 未填提示词")

    def reload_tasks(self):
        rid = self.recipient.currentData()
        hid = self.host.currentData()
        if not hid and self.host.count() > 1:
            self.host.blockSignals(True)
            self.host.setCurrentIndex(1)
            self.host.blockSignals(False)
            hid = self.host.currentData()
        self._sync_checked_host_scope()
        status = self.status_filter.currentText()
        if hid and not getattr(self,"_date_view_refresh",False):
            repo.ensure_flow_segments_for_host(hid)
        # Never fall back to querying across all hosts when no concrete host is selected.
        rows = list(repo.list_prompt_tasks(rid, hid, status, work_date=work_dates.active())) if hid else []
        gate = self.review_filter.currentText() if hasattr(self, "review_filter") else "当前任务"
        history_edited = getattr(self, "_history_editing_ids", set())
        if gate in ("已提交", "提交历史"):
            self.task_rows = [
                r for r in rows
                if str(r["prompt_review_status"] or "待检查") == "已提交"
                or int(r["segment_id"]) in history_edited
            ]
        else:
            self.task_rows = [r for r in rows if str(r["prompt_review_status"] or "待检查") != "已提交"]
        if hasattr(self, "task_panel_title"):
            host_name = str(self.host.currentText() or "").strip() if hid else ""
            self.task_panel_title.setText(f"{host_name} ({len(self.task_rows)})" if host_name else "文案列表")
        self._refresh_host_aspect_ratio_btn()

        self._shift_anchor_row = None
        self._table_loading=True
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(0)
        self._hydrated_rows = set()
        self.table.setRowCount(len(self.task_rows))
        self.table.horizontalHeaderItem(0).setText("☐")
        generated = 0
        copy_pt = self._current_copy_font_size()
        self.table.verticalHeader().setDefaultSectionSize(max(68, int(copy_pt * 6.6)))
        from app.services.sheet_style import segment_snapshots_for_videos
        from app.ui.sheet_rich_text import SheetTextDelegate, CleanItemColorDelegate, VIDEO_GROUP_START_ROLE, attach
        if not hasattr(self, '_sheet_delegate'):
            self._sheet_delegate = SheetTextDelegate(self.table, min_point_size=copy_pt, max_point_size=copy_pt, split_on_enter=True, clean_background=True)
            self.table.setItemDelegateForColumn(4, self._sheet_delegate)
            self._color_delegate = CleanItemColorDelegate(self.table, clean_background=True)
            for col in (0, 1, 2, 3, 5, 6, 7, 8):
                self.table.setItemDelegateForColumn(col, self._color_delegate)
        else:
            self._sheet_delegate.set_point_size(copy_pt)
        self._segment_styles = segment_snapshots_for_videos({t['video_id'] for t in self.task_rows})

        copy_font = QFont(self.table.font())
        copy_font.setPointSize(copy_pt)
        dur_font = QFont(self.table.font())
        dur_font.setPointSize(11)
        dur_font.setBold(False)
        id_head_font = QFont(self.table.font())
        id_head_font.setPointSize(12)
        id_head_font.setBold(True)
        id_sub_font = QFont(self.table.font())
        id_sub_font.setPointSize(12)
        id_sub_font.setBold(False)
        pending_worker_ids = (
            self.worker.pending_segment_ids()
            if (self.worker and self.worker.isRunning() and hasattr(self.worker, "pending_segment_ids"))
            else set()
        )

        for row, task in enumerate(self.task_rows):
            sid = task["segment_id"]
            is_group_first = (row == 0) or (task["video_id"] != self.task_rows[row - 1]["video_id"])
            is_new_video_divider = (row > 0) and is_group_first

            chk_item = QTableWidgetItem("")
            chk_item.setFlags(chk_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 0, chk_item)

            task_id = f'{task["video_seq"]:02d}-{task["seg_seq"]:02d}'
            id_item = QTableWidgetItem(task_id)
            id_item.setTextAlignment(Qt.AlignCenter)
            id_item.setFlags(id_item.flags() & ~Qt.ItemIsEditable)
            if is_group_first or int(task["seg_seq"]) == 1:
                id_item.setFont(id_head_font)
                id_item.setForeground(QColor("#2563EB"))
            else:
                id_item.setFont(id_sub_font)
                id_item.setForeground(QColor("#64748B"))
            self.table.setItem(row, 1, id_item)

            image_item = QTableWidgetItem(
                Path(task["image_path"]).name if task["image_path"] else "无图片"
            )
            self.table.setItem(row, 2, image_item)

            is_image = int(task["seg_seq"]) >= 1000 and str(task["foreign_text"] or "").startswith("[LEGACY_AUX]")
            mode = "图片" if is_image else ("PRAYING" if str(task["performance_mode"] or "").upper() == "PRAYING" else "TALKING")
            source = task['segment_type_source']
            if is_image:
                type_item = QTableWidgetItem("图片")
                type_item.setFlags(type_item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, 3, type_item)
            else:
                classified = source != 'unclassified'
                label = ('闭眼' if mode == 'PRAYING' else '睁眼') if classified else '待识别'
                # Text stays empty (the toggle draws on top); tooltip keeps the label searchable.
                type_item = QTableWidgetItem("")
                type_item.setFlags(type_item.flags() & ~Qt.ItemIsEditable)
                type_item.setToolTip(label)
                self.table.setItem(row, 3, type_item)

            content = ((task["foreign_text"] or "") + "\n" + (task["prompt"] or "待填写图片提示词")) if is_image else (task["foreign_text"] or "")
            foreign = QTableWidgetItem(content)
            foreign.setFont(copy_font)
            foreign.setToolTip(content + ("" if is_image else "\n\n💡 双击编辑文案时，在光标处按回车（Enter）即可把后面的文案切换到下一行新片段"))
            if is_image: foreign.setFlags(foreign.flags() & ~Qt.ItemIsEditable)
            attach(foreign, self._segment_styles.get(sid))
            self.table.setItem(row, 4, foreign)

            if is_image:
                dur_item = QTableWidgetItem("图片")
                dur_item.setForeground(QColor("#64748b"))
            else:
                sec, wcount, dur_text, dur_tip, dur_color = self._estimate_copy_duration_info(task["foreign_text"] or "")
                dur_item = QTableWidgetItem(dur_text)
                dur_item.setToolTip(dur_tip)
                dur_item.setForeground(QColor(dur_color))
                dur_item.setFont(dur_font)
            dur_item.setTextAlignment(Qt.AlignCenter)
            dur_item.setFlags(dur_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 5, dur_item)

            if (task["prompt"] or "").strip():
                generated += 1
            if is_image:
                mode_item=QTableWidgetItem("图片")
                mode_item.setFlags(mode_item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, 6, mode_item)
            else:
                vmodel = str(task["video_model"] or "") if "video_model" in task.keys() else ""
                gmode = str(task["generation_mode"] or "FRAME").upper()
                mode_tip = "Omini" if vmodel == "flow_omni" else ("素材" if gmode == "MATERIAL" else "帧")
                mode_item = QTableWidgetItem("")
                mode_item.setFlags(mode_item.flags() & ~Qt.ItemIsEditable)
                mode_item.setToolTip(mode_tip)
                self.table.setItem(row, 6, mode_item)

            if int(sid) in pending_worker_ids:
                prompt_state = "生成中…"
            elif str(task["status"] or "") == "文案已改":
                prompt_state = "文案已改"
            else:
                prompt_state = ("失败" if str(task["status"] or "")=="失败" else ("已填" if (task["prompt"] or "").strip() else "未填"))
            prompt_item = QTableWidgetItem("")
            self._apply_prompt_state_item(prompt_item, prompt_state, task["prompt"] or "")
            self.table.setItem(row, 7, prompt_item)

            cost_item = QTableWidgetItem(
                f'${float(task["cost_usd"] or 0):.4f}' if task["cost_usd"] else ""
            )
            self.table.setItem(row, 8, cost_item)

            if is_new_video_divider:
                for c_idx in range(9):
                    c_it = self.table.item(row, c_idx)
                    if c_it is not None:
                        c_it.setData(VIDEO_GROUP_START_ROLE, True)

        self._hydrate_visible_table_widgets()
        self.update_header_check()
        self.table.setUpdatesEnabled(True)
        self._table_loading=False
        if self.editor_segment_id:
            visible = [t["segment_id"] for t in self.task_rows]
            if self.editor_segment_id in visible:
                self.reload_inline_editor()
            elif self.task_rows:
                self.load_inline_editor(0, 1, force=True)
            else:
                self._clear_inline_editor_empty(has_submitted=bool(rows))
        elif self.task_rows:
            self.load_inline_editor(0, 1, force=True)
        else:
            self._clear_inline_editor_empty(has_submitted=bool(rows))
        self._hydrate_visible_table_widgets()

        summary = repo.prompt_usage_breakdown(work_date=work_dates.active())
        h_cnt = p_cnt = g_cnt = f_cnt = 0
        try:
            gstats = repo.prompt_global_stats(work_date=work_dates.active())
            h_cnt = int(gstats.get("hosts", gstats.get("all_hosts", 0)) or 0)
            p_cnt = int(gstats.get("pending", gstats.get("pending_all", 0)) or 0)
            g_cnt = int(gstats.get("generated", gstats.get("generated_all", 0)) or 0)
            f_cnt = int(gstats.get("failed", gstats.get("failed_all", 0)) or 0)
            self.stat_hosts.setText(str(h_cnt))
            self.stat_pending.setText(str(p_cnt))
            self.stat_generated.setText(str(g_cnt))
            self.stat_failed.setText(str(f_cnt))
        except Exception:
            pass

        visible_video_ids = {task["video_id"] for task in self.task_rows}
        self.task_count.setText(f"任务：{len(self.task_rows)}")
        self.request_count.setText(f"按图片合并后请求：{len(visible_video_ids)}")
        gates = repo.prompt_gate_counts(work_date=work_dates.active())
        sub_cnt = int(gates.get("submitted", 0) or 0)
        self.generated_count.setText(f"已生成：{generated} · 已提交 {sub_cnt}")
        self.input_label.setText(f'输入：{summary["input_tokens"]:,}')
        self.cache_label.setText(f'缓存：{summary["cached_tokens"]:,}')
        self.output_label.setText(f'输出：{summary["output_tokens"]:,}')
        if hasattr(self, "stat_hosts_chip"):
            self.stat_hosts_chip.setText(f"{h_cnt} 主播")
            self.stat_pending_chip.setText(f"{p_cnt} 待生成")
            self._set_prop(self.stat_pending_chip, "tone", "warn" if p_cnt > 0 else "")
            self.stat_generated_chip.setText(f"✓ {g_cnt} 已生成")
            self._set_prop(self.stat_generated_chip, "tone", "good" if g_cnt > 0 else "")
            self.stat_submitted_chip.setText(f"🚀 {sub_cnt} 已提交")
            self._set_prop(self.stat_submitted_chip, "tone", "info" if sub_cnt > 0 else "")
            self.stat_failed_chip.setText(f"⚠ {f_cnt} 失败")
            self._set_prop(self.stat_failed_chip, "tone", "bad" if f_cnt > 0 else "")

        if hasattr(self, "table_summary_badge"):
            self.table_summary_badge.setText(f"已生成 {generated}/{len(self.task_rows)}")
            self._set_prop(
                self.table_summary_badge,
                "tone",
                "good" if (len(self.task_rows) > 0 and generated >= len(self.task_rows)) else "",
            )

        if hasattr(self, "step_labels") and hasattr(self, "guide_hint"):
            unfilled_visible = max(0, len(self.task_rows) - generated)
            if h_cnt == 0 and len(self.task_rows) == 0 and sub_cnt == 0:
                states = ("active", "todo", "todo")
                hint = "👉 第 1 步：当前日期暂无任务，请先从左侧「任务中心」同步今日任务。"
            elif len(self.task_rows) == 0 and sub_cnt > 0 and gate not in ("已提交", "提交历史"):
                states = ("done", "done", "done")
                hint = f"✅ 当前视图的任务已全部提交到 Flow（共 {sub_cnt} 条）。如需查看或修改，请切换到「提交历史」。"
            elif unfilled_visible > 0:
                states = ("done", "active", "todo")
                hint = f"👉 第 2 步：还有 {unfilled_visible} 条待生成 —— 可先「AI自动整理」均衡时长，再点右侧蓝色「✨ 生成」。"
            elif len(self.task_rows) > 0:
                states = ("done", "done", "active")
                hint = f"👉 第 3 步：{len(self.task_rows)} 条提示词已就绪 —— 单击列表在右侧检查微调，确认后点绿色「🚀 提交到 Flow」。"
            else:
                states = ("active", "todo", "todo")
                hint = "👉 请在上方选择接收人与 AI 主播，或调整筛选条件查看文案列表。"
            for lab, st in zip(self.step_labels, states):
                self._set_prop(lab, "state", st)
            self.guide_hint.setText(hint)

        self.refresh_api_status()
        self._refresh_daily_cost_chip(work_summary=summary, visible_video_count=len(visible_video_ids))
        self._refresh_primary_actions()
        self._refresh_copy_undo_ui()

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
        if getattr(self, "_editor_dirty", False):
            self._persist_inline_editor(show_message=False)
        from app.services import selected_resubmission
        ids=self.selected_segment_ids()
        if not ids:
            sel_sid=self._selected_prompt_segment_id() or getattr(self,'editor_segment_id',None)
            if sel_sid and any(int(t['segment_id'])==int(sel_sid) for t in self.task_rows):
                ids=[int(sel_sid)]
        if not ids:
            QMessageBox.information(self,'重新提交','请先勾选（或单击选中）需要替换的任务。')
            return
        sid=getattr(self,'editor_segment_id',None)
        edits={int(sid):self._compose_editor_full_prompt()} if sid and int(sid) in ids and hasattr(self,'editor_final_prompt') else {}
        self.current_job.setText(f"⚡ 正在重新提交所选 {len(ids)} 条任务到 Flow 队列…")
        QApplication.processEvents()
        try:result=selected_resubmission.replace(ids,work_dates.active(),prompt_overrides=edits)
        except Exception as exc:
            self.current_job.setText(f"⚠ 重新提交失败：{str(exc)[:100]}")
            QMessageBox.warning(self,'重新提交失败',str(exc));return
        self.checked_ids.difference_update(ids)
        if hasattr(self, "_history_editing_ids"):
            self._history_editing_ids.difference_update(ids)
        self._wake_flow_scheduler()
        self._refresh_after_host_overwrite()
        self.reload_tasks()
        self._rebuild_host_cards()
        self.current_job.setText(
            f"🚀 已重新提交并替换所选 {result.get('submitted', 0)} 条任务（清理旧视频 {result.get('deleted_files', 0)} 个）"
        )
        QMessageBox.information(
            self,
            '已重新提交选中任务',
            f"已单独提交/替换所选的 {result['submitted']} 条任务（删除该片段旧视频 {result['deleted_files']} 个）。\n"
            "未勾选的其他已生成视频均完整保留，不会受任何影响。"
            + (f"\n{len(result['delete_failures'])} 个文件暂未删除，请检查文件占用。" if result['delete_failures'] else '')
        )

    def submit_selected_to_flow(self):
        if getattr(self, "_editor_dirty", False):
            self._persist_inline_editor(show_message=False)
        ids=self.selected_segment_ids()
        if not ids:
            sel_sid=self._selected_prompt_segment_id() or getattr(self,'editor_segment_id',None)
            if sel_sid and any(int(t['segment_id'])==int(sel_sid) for t in self.task_rows):
                ids=[int(sel_sid)]
        if not ids:
            QMessageBox.information(self,"提交到 Flow","请先勾选需要提交的提示词任务。")
            return
        # Strictly submit/replace ONLY the selected segment IDs.
        # NEVER call replace_host_prompt_submission here, so unselected videos of the host are never touched or deleted.
        from app.services import selected_resubmission
        submitted_hid = int(self.host.currentData()) if self.host.currentData() else None
        submitted_hname = str(self.host.currentText() or "").strip()
        pre_order = list(getattr(self, "_ordered_host_ids", []) or [])
        sid=getattr(self,'editor_segment_id',None)
        edits={int(sid):self._compose_editor_full_prompt()} if sid and int(sid) in ids and hasattr(self,'editor_final_prompt') else {}
        self.current_job.setText(f"⚡ 正在提交所选 {len(ids)} 条任务到 Flow 队列…")
        QApplication.processEvents()
        try:
            result=selected_resubmission.replace(ids,work_dates.active(),prompt_overrides=edits)
        except Exception as exc:
            self.current_job.setText(f"⚠ 提交到 Flow 失败：{str(exc)[:100]}")
            QMessageBox.warning(self,"提交到 Flow 失败",str(exc))
            return
        if result.get('submitted'):
            self._wake_flow_scheduler()
        self.checked_ids.difference_update(ids)
        if hasattr(self, "_history_editing_ids"):
            self._history_editing_ids.difference_update(ids)
        self._refresh_after_host_overwrite()
        next_hid, next_hname, all_done = self._post_submit_advance_host(submitted_hid, pre_order)
        replaced = int(result.get('replaced', 0))
        new_sub = int(result.get('new_submitted', 0))
        deleted = int(result.get('deleted_files', 0))
        sub_total = int(result.get('submitted', 0))
        host_tag = f"【{submitted_hname}】" if submitted_hname else ""
        jump_suffix = (
            f" · 已自动切换到【{next_hname}】"
            if next_hid and next_hname
            else (" · 当前接收人全部主播均已提交" if all_done else "")
        )
        self.current_job.setText(
            f"🚀 {host_tag}已提交 {sub_total} 条任务到 Flow 等待队列"
            + (f"（含单独替换 {replaced} 条）" if replaced > 0 else "")
            + jump_suffix
        )
        if replaced > 0 and new_sub > 0:
            msg = (
                f"本次共提交所选 {sub_total} 条任务（新增 {new_sub} 条，单独替换重做 {replaced} 条，清理对应旧片段 {deleted} 个）。\n"
                "未勾选的其他已生成视频均完整保留，不受影响。"
            )
        elif replaced > 0:
            msg = (
                f"已单独重新提交并替换所选的 {replaced} 条任务（清理对应旧片段 {deleted} 个）。\n"
                "未勾选的其他已生成视频均完整保留，不受影响。"
            )
        else:
            msg = f"{host_tag}已提交所选 {sub_total} 条任务到 Flow。\nFlow 调度器会自动领取已提交任务。"
        if next_hid and next_hname:
            msg += f"\n\n👉 【{submitted_hname}】已移至主播队列末尾，并已自动切换到下一位待处理主播：【{next_hname}】。"
        elif all_done:
            msg += "\n\n🎉 当前接收人名下全部主播均已提交到 Flow！"
        if result.get('delete_failures'):
            msg += f"\n另有 {len(result['delete_failures'])} 个旧文件暂未删除，请检查文件占用。"
        QMessageBox.information(self,"已提交到 Flow",msg)

    def submit_current_host_to_flow(self):
        if getattr(self, "_editor_dirty", False):
            self._persist_inline_editor(show_message=False)
        hid=self.host.currentData()
        if not hid:
            QMessageBox.information(self,"提交到 Flow","请先选择一个具体 AI 主播。")
            return
        submitted_hid = int(hid)
        submitted_hname = str(self.host.currentText() or "").strip()
        pre_order = list(getattr(self, "_ordered_host_ids", []) or [])
        rows=list(repo.list_prompt_tasks(self.recipient.currentData(),hid,"全部", work_date=work_dates.active()))
        ids=[int(r['segment_id']) for r in rows if str(r['prompt'] or '').strip() and str(r['prompt_review_status'] or '待检查')!='已提交']
        if not ids:
            QMessageBox.information(self,"提交到 Flow","当前主播没有待提交的新增或已修改提示词（已提交的其他视频均保留不变）。")
            return
        # Submit/replace ONLY the unsubmitted/modified segments (ids) of this host,
        # never wiping out other segments of this host that are already '已提交'.
        from app.services import selected_resubmission
        self.current_job.setText(f"⚡ 正在提交【{submitted_hname}】{len(ids)} 条待提交任务到 Flow 队列…")
        QApplication.processEvents()
        try:
            result=selected_resubmission.replace(ids,work_dates.active())
        except Exception as exc:
            self.current_job.setText(f"⚠ 提交到 Flow 失败：{str(exc)[:100]}")
            QMessageBox.warning(self,"提交到 Flow 失败",str(exc))
            return
        if result.get('submitted'):
            self._wake_flow_scheduler()
        if hasattr(self, "_history_editing_ids"):
            self._history_editing_ids.difference_update(ids)
        self._refresh_after_host_overwrite()
        next_hid, next_hname, all_done = self._post_submit_advance_host(submitted_hid, pre_order)
        replaced = int(result.get('replaced', 0))
        deleted = int(result.get('deleted_files', 0))
        sub_total = int(result.get('submitted', 0))
        jump_suffix = (
            f" · 已自动切换到【{next_hname}】"
            if next_hid and next_hname
            else (" · 当前接收人全部主播均已提交" if all_done else "")
        )
        self.current_job.setText(
            f"🚀 【{submitted_hname}】已提交 {sub_total} 条任务到 Flow 等待队列"
            + (f"（含替换修改片段 {replaced} 条）" if replaced > 0 else "")
            + jump_suffix
        )
        if replaced > 0:
            msg = (
                f"【{submitted_hname}】已提交 {sub_total} 条待提交任务（其中单独替换已修改片段 {replaced} 条，清理对应旧片段 {deleted} 个）。\n"
                "其余未修改的已生成视频均完整保留，不受影响。"
            )
        else:
            msg = f"【{submitted_hname}】已提交 {sub_total} 条待提交任务到 Flow 等待队列。"
        if next_hid and next_hname:
            msg += f"\n\n👉 【{submitted_hname}】已移至主播队列末尾，并已自动切换到下一位待处理主播：【{next_hname}】。"
        elif all_done:
            msg += "\n\n🎉 当前接收人名下全部主播均已提交到 Flow！"
        QMessageBox.information(self,"已提交到 Flow",msg)

    def _confirm_withdraw_from_flow(self, ids) -> bool:
        dlg = QDialog(self, objectName="pcWithdrawDialog")
        dlg.setWindowTitle("⚠️ 确认从 Flow 队列撤回任务（高危操作）")
        dlg.setMinimumSize(520, 350)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(12)

        title = QLabel(f"⚠️ 即将从 Flow 队列撤回已勾选的 {len(ids)} 条任务", objectName="pcWithdrawTitle")
        title.setWordWrap(True)
        lay.addWidget(title)

        desc = QLabel(
            "请确认您了解「撤回 Flow 排队」的具体含义与影响：\n\n"
            "1. 【退回未提交列表】：撤回后，这些片段会从「提交历史（Flow 排队队列）」退回到「当前任务（未提交）」列表中。\n"
            "2. 【停止自动生成】：撤回后，Flow 插件将不再自动领取和生成这些视频片段。\n"
            "3. 【需重新提交】：如果之后还需要生成这些片段，必须再次点击「🚀 提交到 Flow」。\n"
            "4. 【安全保护】：已经在 Flow 网页端开始执行或已生成完成的片段会自动跳过，不会被破坏。",
            objectName="pcWithdrawDesc",
        )
        desc.setWordWrap(True)
        desc.setMinimumHeight(185)
        lay.addWidget(desc)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch(1)

        abort_btn = QPushButton("放弃", objectName="pcWithdrawAbortBtn")
        abort_btn.setCursor(Qt.PointingHandCursor)
        abort_btn.setFixedHeight(38)
        abort_btn.setMinimumWidth(120)
        abort_btn.clicked.connect(dlg.reject)

        confirm_btn = QPushButton("哼！俺就要撤回")
        confirm_btn.setCursor(Qt.PointingHandCursor)
        confirm_btn.setFixedHeight(38)
        confirm_btn.setMinimumWidth(168)
        confirm_btn.setStyleSheet(
            "QPushButton { background:#DC2626; color:#FFFFFF; border:1.5px solid #B91C1C; "
            "border-radius:9px; padding:0 18px; font-size:13.5px; font-weight:800; }"
            "QPushButton:hover { background:#B91C1C; }"
        )

        def _trigger_boom_and_accept():
            if getattr(dlg, "_boom_running", False):
                return
            dlg._boom_running = True
            abort_btn.setEnabled(False)
            confirm_btn.setText("💥 轰！撤回中…")
            self._play_withdraw_explosion(dlg, confirm_btn, dlg.accept)

        confirm_btn.clicked.connect(_trigger_boom_and_accept)

        btn_row.addWidget(abort_btn)
        btn_row.addWidget(confirm_btn)
        lay.addLayout(btn_row)
        abort_btn.setDefault(True)
        return dlg.exec() == QDialog.Accepted

    def _play_withdraw_explosion(self, dlg: QDialog, btn: QPushButton, on_finished):
        import math
        import random
        from PySide6.QtGui import QPainter, QPen, QBrush, QRadialGradient
        from PySide6.QtCore import QPointF

        class _ExplosionOverlay(QWidget):
            def __init__(self, parent_dlg: QDialog, origin: QPointF, done_cb):
                super().__init__(parent_dlg)
                self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                self.setAttribute(Qt.WA_NoSystemBackground, True)
                self.setAttribute(Qt.WA_TranslucentBackground, True)
                self.setGeometry(parent_dlg.rect())
                self.origin = origin
                self.done_cb = done_cb
                self.frame_idx = 0
                self.total_frames = 22
                self.base_dlg_pos = parent_dlg.pos()
                rng = random.Random(42)
                palette = [
                    QColor("#EF4444"),
                    QColor("#F97316"),
                    QColor("#FACC15"),
                    QColor("#FEF08A"),
                    QColor("#FB7185"),
                    QColor("#FFFFFF"),
                ]
                self.particles = []
                for i in range(32):
                    angle = (2 * math.pi * i / 32.0) + rng.uniform(-0.12, 0.12)
                    speed = rng.uniform(4.5, 13.5)
                    self.particles.append({
                        "x": origin.x(),
                        "y": origin.y(),
                        "vx": math.cos(angle) * speed,
                        "vy": math.sin(angle) * speed - rng.uniform(1.0, 3.5),
                        "r": rng.uniform(3.5, 8.0),
                        "color": QColor(rng.choice(palette)),
                        "spark": (i % 3 == 0),
                    })
                self.timer = QTimer(self)
                self.timer.setInterval(16)
                self.timer.timeout.connect(self._step)
                self.show()
                self.raise_()
                self.timer.start()

            def _step(self):
                self.frame_idx += 1
                parent_dlg = self.parentWidget()
                if parent_dlg is not None:
                    if self.frame_idx <= 6:
                        dx = (-5 if self.frame_idx % 2 == 0 else 5) * (7 - self.frame_idx) // 3
                        dy = (3 if (self.frame_idx // 2) % 2 == 0 else -3)
                        parent_dlg.move(self.base_dlg_pos.x() + dx, self.base_dlg_pos.y() + dy)
                    elif self.frame_idx == 7:
                        parent_dlg.move(self.base_dlg_pos)
                for p in self.particles:
                    p["x"] += p["vx"]
                    p["y"] += p["vy"]
                    p["vy"] += 0.42  # gravity
                    p["vx"] *= 0.95
                self.update()
                if self.frame_idx >= self.total_frames:
                    self.timer.stop()
                    self.hide()
                    self.deleteLater()
                    self.done_cb()

            def paintEvent(self, _event):
                t = self.frame_idx / float(self.total_frames)
                alpha = max(0.0, 1.0 - t * t)
                painter = QPainter(self)
                painter.setRenderHint(QPainter.Antialiasing, True)

                # 1. Central fiery glow flash (early frames)
                if t < 0.55:
                    flash_r = 18.0 + t * 120.0
                    grad = QRadialGradient(self.origin, flash_r)
                    c0 = QColor(255, 250, 210, int(230 * (1.0 - t / 0.55)))
                    c1 = QColor(249, 115, 22, int(170 * (1.0 - t / 0.55)))
                    c2 = QColor(220, 38, 38, 0)
                    grad.setColorAt(0.0, c0)
                    grad.setColorAt(0.45, c1)
                    grad.setColorAt(1.0, c2)
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QBrush(grad))
                    painter.drawEllipse(self.origin, flash_r, flash_r)

                # 2. Expanding shockwave ring
                ring_r = 12.0 + t * 135.0
                ring_col = QColor(239, 68, 68, int(220 * alpha))
                pen = QPen(ring_col, max(1.5, 6.0 * (1.0 - t)))
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawEllipse(self.origin, ring_r, ring_r)

                # 3. Flying sparks & embers
                for p in self.particles:
                    col = QColor(p["color"])
                    col.setAlpha(int(255 * alpha))
                    r = max(1.2, p["r"] * (1.0 - 0.55 * t))
                    if p["spark"]:
                        spark_pen = QPen(col, max(1.5, r * 0.55))
                        spark_pen.setCapStyle(Qt.RoundCap)
                        painter.setPen(spark_pen)
                        painter.drawLine(
                            QPointF(p["x"] - p["vx"] * 1.4, p["y"] - p["vy"] * 1.4),
                            QPointF(p["x"], p["y"]),
                        )
                    else:
                        painter.setPen(Qt.NoPen)
                        painter.setBrush(col)
                        painter.drawEllipse(QPointF(p["x"], p["y"]), r, r)

                # 4. Central "💥 BOOM!" pop text
                if t < 0.75:
                    f = painter.font()
                    f.setPointSize(int(18 + 10 * math.sin(min(1.0, t * 2.2) * math.pi / 2)))
                    f.setBold(True)
                    painter.setFont(f)
                    txt_col = QColor(220, 38, 38, int(255 * (1.0 - t / 0.75)))
                    painter.setPen(txt_col)
                    painter.drawText(
                        int(self.origin.x() - 60),
                        int(self.origin.y() - 36 - t * 26),
                        120,
                        40,
                        Qt.AlignCenter,
                        "💥 BOOM!",
                    )
                painter.end()

        center_pt = btn.mapTo(dlg, btn.rect().center())
        dlg._explosion_overlay = _ExplosionOverlay(dlg, QPointF(center_pt.x(), center_pt.y()), on_finished)

    def withdraw_selected_from_flow(self):
        ids=self.selected_segment_ids()
        if not ids:
            QMessageBox.information(self,"撤回 Flow 排队","请先在「提交历史」工作区勾选需要撤回的任务。")
            return
        if not self._confirm_withdraw_from_flow(ids):
            return
        result=repo.withdraw_prompt_segments_from_flow(ids)
        self.checked_ids.difference_update(ids)
        self.reload_tasks()
        self._rebuild_host_cards()
        self.current_job.setText(
            f"↩️ 已从 Flow 队列撤回 {result.get('withdrawn', 0)} 条任务（退回当前任务列表）"
            + (f"，跳过进行中/已完成 {result.get('blocked', 0)} 条" if result.get("blocked") else "")
        )
        QMessageBox.information(
            self,
            "撤回结果",
            f"已成功从 Flow 队列撤回 {result.get('withdrawn',0)} 条任务（已退回至「当前任务」列表）；\n"
            f"另有 {result.get('blocked',0)} 条已在 Flow 执行中或已完成，已自动保护跳过。"
        )

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

    def _hydrate_table_row(self, row: int):
        if row < 0 or row >= len(self.task_rows) or row >= self.table.rowCount():
            return
        hydrated = getattr(self, "_hydrated_rows", None)
        if hydrated is None:
            hydrated = set()
            self._hydrated_rows = hydrated
        if row in hydrated:
            return
        hydrated.add(row)
        task = self.task_rows[row]
        sid = task["segment_id"]
        check = CheckCell(sid in self.checked_ids)
        check.changed.connect(
            lambda checked, segment_id=sid, source_row=row: self.on_row_check_changed(segment_id, checked, source_row)
        )
        check.drag_started.connect(
            lambda state, source_row=row: self.start_fill_drag(source_row, state)
        )
        check.drag_moved_global.connect(self.update_fill_drag)
        check.drag_finished.connect(self.finish_fill_drag)
        self.table.setCellWidget(row, 0, check)

        is_image = int(task["seg_seq"]) >= 1000 and str(task["foreign_text"] or "").startswith("[LEGACY_AUX]")
        if not is_image:
            mode = "PRAYING" if str(task["performance_mode"] or "").upper() == "PRAYING" else "TALKING"
            classified = task["segment_type_source"] != "unclassified"
            self.table.setCellWidget(row, 3, self._make_type_toggle(row, sid, mode, classified))
            vmodel = task["video_model"] if "video_model" in task.keys() else ""
            mode_toggle = _SinglePillModeToggle(task["generation_mode"] or "FRAME", None, video_model=vmodel)
            mode_toggle.modeChanged.connect(lambda m, segment_id=int(sid): self._set_one_generation_mode(segment_id, m))
            self.table.setCellWidget(row, 6, mode_toggle)

    def _hydrate_visible_table_widgets(self):
        n = len(self.task_rows)
        if n == 0 or self.table.rowCount() != n:
            return
        hydrated = getattr(self, "_hydrated_rows", None)
        if hydrated is not None and len(hydrated) >= n:
            return
        vp_h = max(960, self.table.viewport().height())
        row_h = max(48, self.table.verticalHeader().defaultSectionSize())
        first_vis = self.table.rowAt(0)
        if first_vis < 0:
            first_vis = 0
            while first_vis < n and self.table.isRowHidden(first_vis):
                first_vis += 1
            if first_vis >= n:
                return
        start_row = first_vis
        back = 0
        while start_row > 0 and back < 8:
            start_row -= 1
            if not self.table.isRowHidden(start_row):
                back += 1
        quota = (vp_h // row_h) + 20
        vis_seen = 0
        was_loading = getattr(self, "_table_loading", False)
        self._table_loading = True
        try:
            for r in range(start_row, n):
                if self.table.isRowHidden(r):
                    continue
                if hydrated is None or r not in hydrated:
                    self._hydrate_table_row(r)
                vis_seen += 1
                if vis_seen >= quota:
                    break
        finally:
            self._table_loading = was_loading

    def _cell_check(self, row):
        cell = self.table.cellWidget(row, 0)
        return cell if isinstance(cell, CheckCell) else None

    def _apply_shift_range_check(self, target_row: int, target_state: bool = True):
        if target_row < 0 or target_row >= len(self.task_rows):
            return
        anchor = getattr(self, "_shift_anchor_row", None)
        if anchor is None or anchor < 0 or anchor >= len(self.task_rows):
            anchor = target_row
        lo = min(anchor, target_row)
        hi = max(anchor, target_row)
        for r in range(lo, hi + 1):
            if r >= len(self.task_rows) or self.table.isRowHidden(r):
                continue
            sid = self.task_rows[r]["segment_id"]
            cell = self._cell_check(r)
            if cell is not None:
                cell.setChecked(target_state, block=True)
            if target_state:
                self.checked_ids.add(sid)
            else:
                self.checked_ids.discard(sid)
        self._shift_anchor_row = target_row
        self.update_header_check()

    def _on_table_cell_clicked(self, row: int, col: int = 0):
        if row < 0 or row >= len(self.task_rows):
            return
        mods = QApplication.keyboardModifiers() | getattr(self, "_last_table_press_modifiers", Qt.NoModifier)
        self._last_table_press_modifiers = Qt.NoModifier
        if (mods & Qt.ShiftModifier) and getattr(self, "_shift_anchor_row", None) is not None:
            self._apply_shift_range_check(row, True)
        else:
            self._shift_anchor_row = row
        self.load_inline_editor(row, col)

    def on_row_check_changed(self, segment_id, checked, row=None):
        if row is None or row < 0 or row >= len(self.task_rows) or int(self.task_rows[row]["segment_id"]) != int(segment_id):
            row = next((i for i, t in enumerate(self.task_rows) if int(t["segment_id"]) == int(segment_id)), None)
        cell = self._cell_check(row) if row is not None else None
        cell_mods = cell.consume_modifiers() if (cell is not None and hasattr(cell, "consume_modifiers")) else Qt.NoModifier
        mods = QApplication.keyboardModifiers() | cell_mods | getattr(self, "_last_table_press_modifiers", Qt.NoModifier)
        self._last_table_press_modifiers = Qt.NoModifier
        if (mods & Qt.ShiftModifier) and row is not None and getattr(self, "_shift_anchor_row", None) is not None:
            self._apply_shift_range_check(row, bool(checked))
            return
        if row is not None:
            self._shift_anchor_row = row
        if checked:
            self.checked_ids.add(segment_id)
        else:
            self.checked_ids.discard(segment_id)
        self.update_header_check()

    def update_header_check(self):
        if not self.task_rows:
            self.table.horizontalHeaderItem(0).setText("☐")
        else:
            visible_ids = [task["segment_id"] for task in self.task_rows]
            all_checked = all(sid in self.checked_ids for sid in visible_ids)
            self.table.horizontalHeaderItem(0).setText("☑" if all_checked else "☐")
        self._refresh_selection_bar()
        self._refresh_primary_actions()

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
            for task in self._current_host_task_rows(visible_only=True)
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
        self.current_job.setText(f"🧹 已清空 {len(ids)} 条选中任务的最终提示词")
        QMessageBox.information(self, "清空完成", f"已清空 {len(ids)} 条提示词。")

    def batch_paste_prompts(self):
        self.local_fill_prompts(False)

    def local_fill_prompts(self, template=False):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self,'正在生成','请等待当前 GPT 批量生成结束后再填写提示词。');return
        hid = self.host.currentData()
        if not hid:
            QMessageBox.information(self,'选择主播','请先在上方选择一个具体的 AI 主播。');return
        host_rows = self._current_host_task_rows(visible_only=True)
        ids=set(self.selected_segment_ids())
        tasks=[t for t in host_rows if not ids or t['segment_id'] in ids]
        if not tasks:
            QMessageBox.information(self,'填写提示词','当前主播列表没有任务。');return
        from app.ui.local_prompt_dialog import LocalPromptDialog
        dialog=LocalPromptDialog(tasks,work_dates.active(),template,self,'当前主播勾选的任务' if ids else '当前主播列表全部任务')
        if dialog.exec()==QDialog.Accepted:
            self.reload_tasks();self._rebuild_host_cards()
            self.current_job.setText(f"✅ 本地填写完成：已保存 {dialog.saved_count} 条提示词（未调用 API）")
            QMessageBox.information(self,'保存完成',f'已保存 {dialog.saved_count} 条提示词，可检查后提交到 Flow。本次未调用 GPT API。')


    def _build_prompt_source_bar(self, box):
        from app.services import flow_master_v8
        label = QLabel("来源", objectName="pcGroupLabel")
        box.addWidget(label)
        self.source_persona = self._pc_seg_button("人物设置", "left")
        self.source_v8 = self._pc_seg_button("防穿帮指令", "right")
        self.source_persona.setToolTip("生成时使用当前主播的人物设置：表演、动作和镜头。")
        self.source_v8.setToolTip("生成时不读取人物设置。按参考图自动匹配防穿帮指令。")
        self._source_group = QButtonGroup(self)
        self._source_group.setExclusive(True)
        self._source_group.addButton(self.source_persona)
        self._source_group.addButton(self.source_v8)
        saved = repo.get_setting(flow_master_v8.SETTING_KEY, flow_master_v8.SOURCE_PERSONA) or flow_master_v8.SOURCE_PERSONA
        self.source_v8.setChecked(saved == flow_master_v8.SOURCE)
        self.source_persona.setChecked(saved != flow_master_v8.SOURCE)
        self._source_group.buttonClicked.connect(self._prompt_source_clicked)
        src_box = QWidget(); src_l = QHBoxLayout(src_box); src_l.setContentsMargins(0, 0, 0, 0); src_l.setSpacing(0)
        src_l.addWidget(self.source_persona); src_l.addWidget(self.source_v8)
        box.addWidget(src_box)
        self.source_hint = QLabel(objectName="muted")
        self.source_hint.hide()
        self.v8_open_file = self._pc_button("打开指令文件", "l3", 34, "用记事本修改防穿帮指令。保存后，下一次生成会读取这个文件。")
        self.v8_open_file.clicked.connect(self._open_v8_file)
        box.addWidget(self.v8_open_file)
        self.v8_clear_voice = self._pc_button("清声纹", "l3", 34, "清除后，下次用防穿帮指令生成时会按参考图重新锁定这个主播的声纹。")
        self.v8_clear_voice.clicked.connect(self._clear_v8_voice)
        box.addWidget(self.v8_clear_voice)
        self._sync_prompt_source_hint()

    def _prompt_source_clicked(self, button):
        from app.services import flow_master_v8
        source = flow_master_v8.SOURCE if button is self.source_v8 else flow_master_v8.SOURCE_PERSONA
        repo.set_setting(flow_master_v8.SETTING_KEY, source)
        self._sync_prompt_source_hint()

    def _sync_prompt_source_hint(self):
        from app.services import flow_master_v8
        if self.source_v8.isChecked():
            path = flow_master_v8.ensure_instruction_file()
            tip_text = f"已分开：本次不读人物设置。修改后保存，下次生成会读取：{path}"
            self.source_hint.setText(tip_text)
            self.source_hint.setToolTip(str(path))
            self.source_v8.setToolTip(tip_text)
            self.v8_clear_voice.setVisible(True)
            self.v8_open_file.setVisible(True)
        else:
            tip_text = "当前使用人物设置里的表演、动作和镜头。"
            self.source_hint.setText(tip_text)
            self.source_persona.setToolTip(tip_text)
            self.v8_clear_voice.setVisible(False)
            self.v8_open_file.setVisible(False)

    def _open_v8_file(self):
        from app.services import flow_master_v8
        try:
            path = flow_master_v8.open_instruction_file()
        except OSError as exc:
            QMessageBox.warning(self, "指令文件", f"没有打开指令文件：{exc}")
            return
        self.source_hint.setText(f"已分开：本次不读人物设置。修改后保存，下次生成会读取：{path}")
        self.source_hint.setToolTip(str(path))

    def _clear_v8_voice(self):
        from app.services import flow_master_v8
        hid = self.host.currentData()
        if not hid:
            QMessageBox.information(self, "声纹", "请先选择一个主播。")
            return
        flow_master_v8.clear_voice(hid)
        QMessageBox.information(self, "声纹", "已清除当前主播的声纹锁。下次生成会按参考图重新判断。")

    def start_generation(self, mode):
        if not openai_service.get_api_key():
            QMessageBox.warning(self, "API Key", "请先点击“AI设置”保存 OpenAI API Key。")
            return

        hid = self.host.currentData()
        if not hid:
            QMessageBox.information(self, "选择主播", "请先在上方选择一个具体的 AI 主播。")
            return
        target_hid = int(hid)

        if getattr(self, "_editor_dirty", False):
            self._persist_inline_editor(show_message=False)

        worker_running = bool(self.worker and self.worker.isRunning())
        pending_ids = (
            self.worker.pending_segment_ids()
            if (worker_running and hasattr(self.worker, "pending_segment_ids"))
            else set()
        )

        # Strictly scope candidate rows to the currently selected AI host ONLY.
        # Never query or generate tasks belonging to any other host.
        host_rows = self._current_host_task_rows(visible_only=True)
        checked_here = [int(sid) for sid in self.selected_segment_ids()]
        checked_set = set(checked_here)

        if mode == 'checked_pending':
            if checked_here:
                ids = [
                    int(t['segment_id']) for t in host_rows
                    if int(t['segment_id']) in checked_set
                    and int(t['segment_id']) not in pending_ids
                    and (not (t['prompt'] or '').strip() or str(t['status'] or '') in ('待处理', '失败', '文案已改'))
                ]
                # If user explicitly checked already-filled rows on this host, regenerate those checked rows.
                if not ids:
                    ids = [sid for sid in checked_here if sid not in pending_ids]
            else:
                ids = [
                    int(t["segment_id"]) for t in host_rows
                    if int(t["segment_id"]) not in pending_ids
                    and (not (t["prompt"] or "").strip() or str(t["status"] or "") in ("待处理", "失败", "文案已改"))
                ]
        elif mode == "selected":
            ids = [sid for sid in checked_here if sid not in pending_ids]
            if not ids:
                selected_rows = sorted({index.row() for index in self.table.selectionModel().selectedIndexes()})
                ids = [
                    int(self.task_rows[row]['segment_id'])
                    for row in selected_rows
                    if 0 <= row < len(self.task_rows)
                    and int(self.task_rows[row]['host_id'] or 0) == target_hid
                    and int(self.task_rows[row]['segment_id']) not in pending_ids
                ]
        elif mode == "failed":
            ids = [
                int(t["segment_id"]) for t in host_rows
                if (t["status"] or "") == "失败" and int(t["segment_id"]) not in pending_ids
            ]
        else:
            ids = [
                int(t["segment_id"]) for t in host_rows
                if (not (t["prompt"] or "").strip() or str(t["status"] or "") in ("待处理", "文案已改"))
                and int(t["segment_id"]) not in pending_ids
            ]
            if not ids:
                ids = [sid for sid in checked_here if sid not in pending_ids]

        if not ids:
            if worker_running:
                QMessageBox.information(self, "已在并行队列中", "当前主播所选任务已经在并行生成队列中；如需同时生成其他主播，请手动切换到对应主播后再点击追加。")
            else:
                QMessageBox.information(self, "没有任务", "当前主播没有符合条件的待生成任务。")
            return

        # Hard database-level host verification: never allow any segment from another host through.
        selected_tasks = [
            t for t in repo.get_prompt_tasks_by_ids(ids)
            if t and int(t["host_id"] or 0) == target_hid
        ]
        ids = [int(t["segment_id"]) for t in selected_tasks]
        if not ids:
            QMessageBox.information(self, "没有任务", "当前主播没有符合条件的待生成任务。")
            return
        from app.services import flow_master_v8
        use_v8 = (repo.get_setting(flow_master_v8.SETTING_KEY, flow_master_v8.SOURCE_PERSONA) or "") == flow_master_v8.SOURCE

        model = repo.get_setting("openai_model", "gpt-5.6-luna")
        image_detail = repo.get_setting("image_detail", "low") or "low"
        core = repo.get_setting("core_prompt", DEFAULT_CORE_PROMPT) or DEFAULT_CORE_PROMPT
        try:
            from app.services import credential_pool
            active_key_count = max(1, len(credential_pool.active_openai_keys()))
        except Exception:
            active_key_count = 1
        channels = min(16, max(4, active_key_count * 4))

        # If a batch worker is already running, dynamically append the new host/tasks into the parallel pool!
        if worker_running and self.worker is not None:
            added_segs, added_groups = self.worker.enqueue_segments(ids, preloaded_tasks=selected_tasks)
            if added_segs <= 0:
                QMessageBox.information(self, "已在队列中", "所选任务已在当前并行生成队列中。")
                return
            self._mark_rows_generating(ids)
            self.current_job.setText(
                f"⚡ 已追加 {added_segs} 个片段（{added_groups} 个视频组）进入并行队列，后台自动多通道同时生成中…"
            )
            return

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
            + (
                "本次使用防穿帮指令，不读取人物设置、基础模板和核心提示词。\n"
                "GPT 按参考图自动匹配外观、手部、眼睛、声纹和上下条接缝；真实文案仍由软件接上。\n\n开始吗？"
                if use_v8 else
                "GPT 只生成每段动态动作/镜头，并保留‘文案： ’占位；真实文案、基础模板、人物设置和固定底层限制由 Studio 本地拼接。\n"
                "这样最终 Flow 提示词仍然完整，但不会让 GPT 为每个片段重复输出相同规则。\n"
                "固定前缀仍会使用 Prompt Cache。\n\n开始吗？"
            )
        )
        if answer != QMessageBox.Yes:
            return

        self._progress_hide_timer.stop()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.show()
        self._mark_rows_generating(ids)
        self.current_job.setText(
            f"⚡ 已排队 {len(ids)} 个片段（{image_requests} 个视频组），后台多通道并行生成中…"
        )

        self.worker = GenerateWorker(ids, model, core, image_detail, max_workers=channels, preloaded_tasks=selected_tasks, parent=self)
        self.worker.progress.connect(self.on_progress)
        self.worker.item_done.connect(self.on_item_done)
        self.worker.finished_summary.connect(self.on_finished)
        self.worker.finished.connect(self._release_generate_worker)
        self.worker.start()

    def _mark_rows_generating(self, segment_ids):
        target_set = {int(sid) for sid in (segment_ids or [])}
        if not target_set:
            return
        for row, task in enumerate(self.task_rows):
            if int(task["segment_id"]) in target_set:
                item = self.table.item(row, 7)
                if item is not None:
                    self._apply_prompt_state_item(item, "生成中…", task["prompt"] or "")

    def _release_generate_worker(self):
        worker = self.sender()
        if self.worker is worker:
            self.worker = None
            self.generate_empty.setEnabled(True)
            self.generate_selected.setEnabled(True)
            self.retry_failed.setEnabled(True)
            self._refresh_primary_actions()
        worker.deleteLater()

    def on_progress(self, current, total, task_id):
        pct = int(current / max(total, 1) * 100)
        self._progress_hide_timer.stop()
        self.progress.setRange(0, 100)
        self.progress.show()
        self.progress.setValue(pct)
        self.current_job.setText(f"⚡ 正在并行生成 {current}/{total} · {task_id}")
        if current > 0:
            self._refresh_daily_cost_chip()

    def on_item_done(self, segment_id, ok, error):
        if not ok and error:
            self.current_job.setText("⚠ 有任务失败：" + error[:120])
        sid_int = int(segment_id)
        for row, task in enumerate(self.task_rows):
            if int(task["segment_id"]) == sid_int:
                prompt_item = self.table.item(row, 7)
                if prompt_item is not None:
                    self._apply_prompt_state_item(prompt_item, "已填" if ok else "失败", task["prompt"] or "")
                break

    def on_finished(self, ok, failed, cost, requests, input_tokens, cached_tokens, output_tokens):
        self.generate_empty.setEnabled(True)
        self.generate_selected.setEnabled(True)
        self.retry_failed.setEnabled(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.progress.show()
        self._progress_hide_timer.start(2500)
        attempted = int(getattr(self.worker, "attempted_requests", requests) or 0)
        last_error = str(getattr(self.worker, "last_error", "") or "").strip()
        prefix = "⚠" if failed else "✅"
        short_summary = f"{prefix} 本批完成：成功 {ok} · 失败 {failed} · 成本 ${cost:.4f}"
        full_summary = (
            f"本批完成：提示词 {ok} · 失败 {failed} · API成功 {requests} / 尝试 {attempted} · "
            f"输入 {input_tokens:,} · 缓存 {cached_tokens:,} · 输出 {output_tokens:,} · "
            f"成本约 ${cost:.4f}"
        )
        if failed and last_error:
            full_summary += "\n失败原因：" + last_error[:260]
        self.current_job.setText(short_summary)
        self.current_job.setToolTip(full_summary)
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
        self._set_prop(self.editor_prompt_state, "tone", "warn")
        self.editor_prompt_state.show()

    def _persist_inline_editor(self, show_message=False):
        if not self.editor_segment_id:
            return False
        task = repo.get_prompt_task(self.editor_segment_id)
        if not task:
            return False
        repo.set_video_special_requirements(
            int(task["video_id"]), self.editor_image_rule.toPlainText().strip()
        )
        repo.update_segment_rule(
            int(task["segment_id"]), self.editor_segment_rule.toPlainText().strip()
        )
        final_prompt_text = self._compose_editor_full_prompt().strip()
        repo.save_manual_prompt_result(
            int(task["segment_id"]), final_prompt_text
        )
        self._editor_dirty = False
        self.editor_prompt_state.setText("✓ 已保存")
        self._set_prop(self.editor_prompt_state, "tone", "good" if final_prompt_text else "")
        if show_message:
            self.current_job.setText(
                f'✅ 已保存 {int(task["video_seq"]):02d}-{int(task["seg_seq"]):02d}'
            )
        return True

    def _clear_inline_editor_empty(self, has_submitted: bool = False):
        self._editor_loading = True
        try:
            self.editor_segment_id = None
            self._editor_dirty = False
            self._editor_prompt_suffix_body = ""
            self._current_editor_image_path = ""
            if has_submitted:
                self.editor_title.setText("当前任务已全部提交")
                self.editor_meta.setText("如需查看或修改已提交片段，请切换至上方「提交历史」")
            else:
                self.editor_title.setText("快速编辑")
                self.editor_meta.setText("单击左侧片段查看参考大图、设置要求或微调提示词")
            self.editor_dialogue.clear()
            self.editor_image_rule.clear()
            self.editor_segment_rule.clear()
            self.editor_final_prompt.clear()
            self._refresh_editor_prompt_mode_btn()
            self.editor_prompt_state.setText("")
            self.editor_prompt_state.hide()
            self.editor_duration_label.clear()
            self.editor_duration_label.hide()
            if hasattr(self, "editor_image_dim_label"):
                self.editor_image_dim_label.setText("")
            self.editor_image.set_qimage(None, "参考图\n(单击左侧任务预览)")
            self.editor_image.setToolTip("")
            self.editor_image.setCursor(Qt.ArrowCursor)
            self._set_prop(self.editor_image, "hasImage", "false")
        finally:
            self._editor_loading = False

    def load_inline_editor_from_selection(self):
        rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()})
        if rows:
            self.load_inline_editor(rows[0], 0)

    def load_inline_editor(self, row, col=0, *, force=False):
        if row < 0 or row >= len(self.task_rows):
            return
        sid = int(self.task_rows[row]["segment_id"])
        if not force and self.editor_segment_id and sid == int(self.editor_segment_id) and not getattr(self, "_editor_dirty", False):
            return
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
            self.editor_title.setText(f'{task["host_name"]} · {task_id}')
            self.editor_meta.setText(
                f'{task["recipient_name"]} · 视频 {int(task["video_seq"]):02d}'
            )
            self._loaded_dialogue = ' '.join(str(task["foreign_text"] or '').split())
            self.editor_dialogue.setPlainText(task["foreign_text"] or "")
            self._update_editor_duration_label(self._loaded_dialogue)
            self.editor_image_rule.setPlainText(task["special_requirements"] or "")
            self.editor_segment_rule.setPlainText(task["segment_rule"] or "")
            self._set_editor_prompt_full_text(task["prompt"] or "")
            for editor in (self.editor_image_rule, self.editor_segment_rule, self.editor_final_prompt):
                editor.setReadOnly(False)
            self.editor_save.setEnabled(True)
            self.editor_save_next.setEnabled(True)
            state_txt = "已提交 · 可改重提" if submitted else ("✓ 已保存" if (task["prompt"] or "").strip() else "未填写")
            self.editor_prompt_state.setText(state_txt)
            self._set_prop(
                self.editor_prompt_state,
                "tone",
                "info" if submitted else ("good" if (task["prompt"] or "").strip() else ""),
            )
            self.editor_prompt_state.show()

            self._set_editor_thumb(str(task["image_path"] or ""))
            self._editor_dirty = False

        finally:
            self._editor_loading = False
            self._refresh_host_aspect_ratio_btn()

    def reload_inline_editor(self):
        if not self.editor_segment_id:
            return
        # Explicit undo: discard only the unsaved UI state and reload DB values.
        self._editor_dirty = False
        for row, task in enumerate(self.task_rows):
            if int(task["segment_id"]) == int(self.editor_segment_id):
                self.table.blockSignals(True)
                self.table.selectRow(row)
                item = self.table.item(row, 1)
                if item is not None:
                    self.table.scrollToItem(item)
                self.table.blockSignals(False)
                self.load_inline_editor(row, 1, force=True)
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
                        if self.table.item(row, 4):
                            self.table.blockSignals(True)
                            self.table.item(row, 4).setText(fresh["foreign_text"] or "")
                            self.table.blockSignals(False)
                        if self.table.item(row, 5):
                            sec, _, dur_text, dur_tip, dur_color = self._estimate_copy_duration_info(fresh["foreign_text"] or "")
                            self.table.item(row, 5).setText(dur_text)
                            self.table.item(row, 5).setToolTip(dur_tip)
                            self.table.item(row, 5).setForeground(QColor(dur_color))
                        p_state = (
                            "文案已改"
                            if str(fresh["status"] or "") == "文案已改"
                            else ("失败" if str(fresh["status"] or "") == "失败" else ("已填" if (fresh["prompt"] or "").strip() else "未填"))
                        )
                        self._apply_prompt_state_item(self.table.item(row, 7), p_state, fresh["prompt"] or "")
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

