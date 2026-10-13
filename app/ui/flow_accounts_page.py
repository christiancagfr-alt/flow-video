"""Manage Flow accounts and show how many videos each one can still generate."""
import threading
import datetime as _dt
import time

from PySide6.QtCore import Qt, QTimer, QSize, QRect, Signal
from PySide6.QtGui import QColor, QIcon, QPainterPath, QPalette, QPixmap
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QDialog, QFormLayout, QDialogButtonBox,
    QSpinBox, QCheckBox, QComboBox, QStyledItemDelegate, QStyle, QStyleOptionViewItem,
)

from app.services import flow_accounts
from app.services.credential_file import CredentialStoreError

_READY_ROLE = Qt.UserRole + 1
_AVATAR_ROLE = Qt.UserRole + 2


class _PresenceDelegate(QStyledItemDelegate):
    """Draw ready rows in color. The app stylesheet otherwise forces one text color."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmaps = {}

    def _avatar(self, path):
        path = str(path or '')
        if not path:
            return QPixmap()
        pixmap = self._pixmaps.get(path)
        if pixmap is None:
            pixmap = QPixmap(path)
            self._pixmaps[path] = pixmap
        return pixmap

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        opt.text = ''
        opt.icon = QIcon()
        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()
        painter.save()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, widget)
        painter.restore()
        ready = bool(index.data(_READY_ROLE))
        dark = opt.palette.color(QPalette.Base).lightness() < 128
        color = QColor('#7DCEA0' if dark else '#0E7A45') if ready else QColor('#9AA0A6' if dark else '#6B7280')
        painter.save()
        painter.setClipping(False)
        painter.setPen(color)
        rect = opt.rect.adjusted(8, 0, -6, 0)
        pixmap = self._avatar(index.data(_AVATAR_ROLE))
        if not pixmap.isNull():
            side = min(32, max(16, opt.rect.height() - 8))
            icon_rect = QRect(opt.rect.left() + 8, opt.rect.top() + max(0, (opt.rect.height() - side) // 2), side, side)
            scaled = pixmap.scaled(side, side, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            clip = QPainterPath()
            clip.addEllipse(icon_rect)
            painter.save()
            painter.setClipPath(clip)
            painter.drawPixmap(icon_rect, scaled)
            painter.restore()
            rect = rect.adjusted(side + 8, 0, 0, 0)
        shown = painter.fontMetrics().elidedText(text, Qt.ElideRight, max(1, rect.width()))
        painter.drawText(rect, int(Qt.AlignVCenter | Qt.AlignLeft), shown)
        painter.restore()


class AddAccountDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('添加 Flow 账号')
        self.resize(460, 220)
        form = QFormLayout(self)
        self.email = QLineEdit()
        self.email.setPlaceholderText('name@gmail.com')
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.secret = QLineEdit()
        self.secret.setPlaceholderText('可选。没有二步验证就留空')
        form.addRow('邮箱', self.email)
        form.addRow('密码', self.password)
        form.addRow('二步验证', self.secret)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self):
        return self.email.text().strip(), self.password.text(), self.secret.text().strip()


class FlowAccountsPage(QWidget):
    _chrome_profiles_ready = Signal(object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('pageRoot')
        self._busy = False
        self._result = None
        self._profiles = {}
        self._profile_list = []
        self._row_payload = []
        self._chrome_loaded = False
        self._chrome_loading = False
        self._legacy_cleared = False
        self._avatar_cache = {}
        self._table_signature = None
        self._chrome_profiles_ready.connect(self._apply_chrome_profiles)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(8)
        title = QLabel('账号管理')
        title.setObjectName('pageTitle')
        root.addWidget(title)
        note = QLabel('勾选后加入换号。每一行只认自己的邮箱：这个 Chrome 用户自己的 Flow 窗口读到它，这一行才是就绪。')
        note.setWordWrap(True)
        note.setObjectName('muted')
        root.addWidget(note)

        sheet_row = QHBoxLayout()
        self.sheet = QLineEdit()
        self.sheet.setPlaceholderText('Google 表格链接。导入的账号会出现在下面，勾选后可参与换号。')
        import_button = QPushButton('从表格导入')
        import_button.clicked.connect(self.import_sheet)
        add_button = QPushButton('手动添加')
        add_button.clicked.connect(self.add_account)
        reload_chrome = QPushButton('读取 Chrome 用户')
        reload_chrome.clicked.connect(self.load_chrome_users)
        sheet_row.addWidget(self.sheet, 1)
        sheet_row.addWidget(import_button)
        sheet_row.addWidget(add_button)
        sheet_row.addWidget(reload_chrome)
        root.addLayout(sheet_row)

        option_row = QHBoxLayout()
        option_row.addWidget(QLabel('每条视频消耗点数'))
        self.cost = QSpinBox()
        self.cost.setRange(1, 500)
        self.cost.valueChanged.connect(self._save_cost)
        option_row.addWidget(self.cost)
        self.rotation = QCheckBox('提交视频时按点数换号')
        self.rotation.toggled.connect(self._save_rotation)
        option_row.addWidget(self.rotation)
        self.only_flow = QCheckBox('只显示已登录 Flow')
        self.only_flow.toggled.connect(self._save_only_flow)
        option_row.addWidget(self.only_flow)
        option_row.addWidget(QLabel('排序'))
        self.sort_mode = QComboBox()
        self.sort_mode.addItem('就绪优先', 'ready')
        self.sort_mode.addItem('点数从多到少', 'points_desc')
        self.sort_mode.addItem('点数从少到多', 'points_asc')
        self.sort_mode.addItem('按用户名', 'name')
        self.sort_mode.addItem('原始顺序', 'default')
        self.sort_mode.currentIndexChanged.connect(self._save_sort)
        option_row.addWidget(self.sort_mode)
        self.summary = QLabel('还没有导入账号。')
        self.summary.setWordWrap(True)
        option_row.addWidget(self.summary, 1)
        root.addLayout(option_row)

        self.detail = QLabel('')
        self.detail.setWordWrap(True)
        self.detail.setObjectName('muted')
        root.addWidget(self.detail)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(['使用', '用户', '头像', '邮箱', '状态', '剩余点数', '还能生成', '说明'])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(7, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 52)
        self.table.setColumnWidth(2, 64)
        self.table.setColumnWidth(4, 118)
        self.table.setColumnWidth(5, 78)
        self.table.setColumnWidth(6, 78)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setIconSize(QSize(32, 32))
        self.table.verticalHeader().setDefaultSectionSize(46)
        self.table.setItemDelegate(_PresenceDelegate(self.table))
        self.table.itemChanged.connect(self._row_toggled)
        root.addWidget(self.table, 1)

        actions = QHBoxLayout()
        login = QPushButton('打开所选 Chrome 的 Flow')
        login.clicked.connect(self.login_selected)
        check = QPushButton('检查页面点数')
        check.clicked.connect(self.check_selected)
        correct = QPushButton('修正剩余点数')
        correct.clicked.connect(self.correct_selected)
        remove = QPushButton('删除选中')
        remove.clicked.connect(self.delete_selected)
        actions.addWidget(login)
        actions.addWidget(check)
        actions.addWidget(correct)
        actions.addWidget(remove)
        actions.addStretch(1)
        root.addLayout(actions)
        self.status = QLabel('')
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self.timer = QTimer(self)
        self.timer.setInterval(3000)
        self.timer.timeout.connect(self.refresh)
        self._loading = False

    def showEvent(self, event):
        super().showEvent(event)
        self.timer.start()
        if not self._chrome_loaded and not self._chrome_loading:
            self.load_chrome_users()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def refresh(self):
        if self._loading:
            return
        self._loading = True
        try:
            if not self._legacy_cleared:
                flow_accounts.clear_legacy_login_errors()
                self._legacy_cleared = True
            self.sheet.blockSignals(True)
            if not self.sheet.hasFocus():
                self.sheet.setText(flow_accounts.sheet_url())
            self.sheet.blockSignals(False)
            self.cost.blockSignals(True)
            cost = flow_accounts.credit_cost() or 10
            self.cost.setValue(max(1, cost))
            self.cost.blockSignals(False)
            self.rotation.blockSignals(True)
            self.rotation.setChecked(flow_accounts.rotation_enabled())
            self.rotation.blockSignals(False)
            self.only_flow.blockSignals(True)
            self.only_flow.setChecked(flow_accounts.only_logged_flow())
            self.only_flow.blockSignals(False)
            self.sort_mode.blockSignals(True)
            sort_index = self.sort_mode.findData(flow_accounts.account_sort_mode())
            if sort_index >= 0:
                self.sort_mode.setCurrentIndex(sort_index)
            self.sort_mode.blockSignals(False)
            accounts = flow_accounts.list_accounts()
            waiting_count = 0
            try:
                from app.core import repository as repo
                from app.core import work_dates
                waiting_count = repo.count_waiting_flow_submissions(work_dates.active())
            except Exception:
                waiting_count = 0
            enabled = [account for account in accounts if int(account.get('enabled', 1))]
            plan = flow_accounts.plan_submission(enabled, waiting_count, 1, max(1, cost), _dt.date.today().isoformat())
            summary = (
                f'等待提交 {waiting_count} 条。按每条 {plan["cost"]} 点数、每个账号每天 {flow_accounts.DAILY_QUOTA} 点数估算，'
                f'这次需要 {plan["accounts_needed"]} 个账号。'
                + (f' 还差 {plan["shortfall"]} 次生成。' if plan['shortfall'] else '')
            )
            if summary != self.summary.text():
                self.summary.setText(summary)
            seen = flow_accounts.observed_pages()
            self._fill_accounts(accounts, seen, plan, flow_accounts.connection_summary(accounts, seen))
            result = self._result
            self._result = None
            if result:
                kind, payload = result
                self._busy = False
                if kind == 'ok':
                    skipped = payload.get('skipped') or []
                    self.status.setText(f'已导入 {payload.get("imported", 0)} 个账号。' + (f' 跳过 {len(skipped)} 行。' if skipped else ''))
                    if skipped:
                        QMessageBox.information(self, '导入完成', '已导入账号。\n' + '\n'.join(skipped[:8]))
                else:
                    self.status.setText(payload)
                    QMessageBox.warning(self, '导入失败', payload)
        except Exception as exc:
            self.sheet.blockSignals(False)
            self.cost.blockSignals(False)
            self.rotation.blockSignals(False)
            self.only_flow.blockSignals(False)
            self.sort_mode.blockSignals(False)
            self.status.setText(f'账号管理暂时无法刷新：{exc}')
        finally:
            self._loading = False

    def _fill_accounts(self, accounts, seen, plan, summary=''):
        today = _dt.date.today().isoformat()
        combined, logged_count = flow_accounts.arrange_account_rows(
            flow_accounts.account_rows(self._profile_list, accounts),
            seen,
            only_logged=self.only_flow.isChecked(),
            sort_mode=str(self.sort_mode.currentData() or 'ready'),
            today=today,
        )
        if self.only_flow.isChecked():
            extra = f'当前只显示已登录 Flow 的 {logged_count} 个账号。'
        else:
            extra = f'已登录 Flow {logged_count} 个，其余 Chrome 用户仍在表里。'
        detail = (summary + ' ' + extra).strip()
        if detail != self.detail.text():
            self.detail.setText(detail)
        signature = self._account_signature(combined, seen, plan, today)
        if signature == self._table_signature and self.table.rowCount() == len(combined):
            return
        self._table_signature = signature
        current = self.table.currentRow()
        current_key = ''
        if 0 <= current < len(self._row_payload):
            current_key = self._row_payload[current].get('key') or ''
        scroll = self.table.verticalScrollBar().value()
        self.table.blockSignals(True)
        self.table.setRowCount(len(combined))
        self._row_payload = []
        restore = 0
        for index, row in enumerate(combined):
            account = row.get('account')
            profile = row.get('profile') or {}
            email = row.get('email') or (account or {}).get('email') or ''
            key = str(profile.get('directory') or '') or ('sheet:' + email.lower())
            if key == current_key:
                restore = index
            ready = bool(account) and flow_accounts.row_ready(account, seen)
            if account:
                credits, estimated = flow_accounts.usable_credits(account, today)
                capacity = '—' if plan['cost'] <= 0 else str(credits // plan['cost'])
                status = flow_accounts.display_status(account, seen)
                note = flow_accounts.display_note(account, seen, estimated)
                if row['kind'] == 'sheet':
                    note = '表格账号 · ' + note
            else:
                credits = '—'
                capacity = '—'
                status = '未连接'
                state = str(profile.get('state') or '可打开 Flow')
                note = f'{state}。勾选后可以参与换号。'
            avatar = self._avatar_path(account or {'chrome_profile': profile.get('directory') or '', 'email': email})
            check = QTableWidgetItem('')
            check.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            checked = bool(account and int(account.get('enabled', 1)) and email)
            check.setCheckState(Qt.Checked if checked else Qt.Unchecked)
            check.setData(Qt.UserRole, int(account['id']) if account else 0)
            check.setData(_READY_ROLE, ready)
            values = [check, row.get('name') or '', '', email or '未登录 Google', status, str(credits), str(capacity), note]
            for column, value in enumerate(values):
                item = value if isinstance(value, QTableWidgetItem) else QTableWidgetItem(value)
                item.setData(_READY_ROLE, ready)
                if column == 2 and avatar:
                    item.setData(_AVATAR_ROLE, avatar)
                self.table.setItem(index, column, item)
            self._row_payload.append({'key': key, 'account': account, 'profile': profile or None, 'kind': row['kind']})
        self.table.blockSignals(False)
        if self.table.rowCount():
            self.table.selectRow(min(restore, self.table.rowCount() - 1))
            self.table.verticalScrollBar().setValue(scroll)

    def _account_signature(self, combined, seen, plan, today):
        seen_key = []
        for item in seen or []:
            if isinstance(item, dict):
                credits = item.get('credits')
                seen_key.append((
                    str(item.get('email') or '').lower(),
                    '' if credits is None else str(credits),
                    str(item.get('at') or ''),
                ))
            else:
                seen_key.append((str(item or '').lower(), '', ''))
        seen_key.sort()
        rows = []
        for row in combined:
            account = row.get('account') or {}
            profile = row.get('profile') or {}
            rows.append((
                row.get('kind'),
                row.get('name'),
                row.get('email'),
                str(profile.get('directory') or ''),
                str(profile.get('state') or ''),
                account.get('id'),
                account.get('enabled'),
                account.get('status'),
                account.get('credits_remaining'),
                str(account.get('credits_checked_at') or '')[:10],
                account.get('chrome_profile'),
                account.get('last_error'),
                account.get('daily_quota'),
            ))
        return (
            today,
            int(plan.get('cost') or 0),
            bool(self.only_flow.isChecked()),
            str(self.sort_mode.currentData() or 'ready'),
            tuple(seen_key),
            tuple(rows),
        )

    def _current_row(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._row_payload):
            return None
        return self._row_payload[row]

    def _selected_id(self):
        payload = self._current_row()
        account = (payload or {}).get('account')
        if not account:
            QMessageBox.information(self, '账号管理', '请先勾选并选中一个账号。')
            return None
        return int(account['id'])

    def _avatar_path(self, account):
        from app.services.chrome_profiles import profile_avatar_file
        directory = str((account or {}).get('chrome_profile') or '').strip()
        email = str((account or {}).get('email') or '').strip().lower()
        key = directory or email
        if key and key in self._avatar_cache:
            return self._avatar_cache[key]
        found = ''
        if directory:
            found = profile_avatar_file(directory) or ''
        if not found and email:
            for profile in self._profiles.values():
                if str(profile.get('email') or '').strip().lower() == email:
                    found = profile_avatar_file(profile.get('path') or profile.get('directory') or '') or ''
                    break
        if key:
            self._avatar_cache[key] = found
        return found

    def _save_cost(self, value):
        if self._loading:
            return
        flow_accounts.set_credit_cost(value)
        self.refresh()

    def _save_rotation(self, checked):
        if self._loading:
            return
        flow_accounts.set_rotation_enabled(checked)

    def _save_only_flow(self, checked):
        if self._loading:
            return
        flow_accounts.set_only_logged_flow(checked)
        self.refresh()

    def _save_sort(self, _index):
        if self._loading:
            return
        flow_accounts.set_account_sort_mode(str(self.sort_mode.currentData() or 'ready'))
        self.refresh()

    def import_sheet(self):
        if self._busy:
            return
        url = self.sheet.text().strip()
        self._busy = True
        self.status.setText('正在读取表格…')

        def work():
            try:
                self._result = ('ok', flow_accounts.import_sheet(url))
            except (ValueError, CredentialStoreError, OSError) as exc:
                self._result = ('err', str(exc))
            except Exception as exc:
                self._result = ('err', f'读取表格失败：{exc}')

        threading.Thread(target=work, daemon=True).start()

    def add_account(self):
        dialog = AddAccountDialog(self)
        if not dialog.exec():
            return
        email, password, secret = dialog.values()
        try:
            flow_accounts.add_account(email, password, secret)
        except (ValueError, CredentialStoreError) as exc:
            QMessageBox.warning(self, '无法添加', str(exc))
            return
        self.status.setText(f'已添加 {email}')
        self.refresh()

    def _checked_payloads(self):
        chosen = []
        for index, payload in enumerate(self._row_payload):
            item = self.table.item(index, 0)
            if item is not None and item.checkState() == Qt.Checked:
                chosen.append(payload)
        return chosen

    def login_selected(self):
        payloads = self._checked_payloads()
        if not payloads:
            current = self._current_row()
            if current:
                payloads = [current]
        if not payloads:
            QMessageBox.information(self, '账号管理', '请先勾选要打开的 Chrome 用户。')
            return
        opened = []
        errors = []
        seen = set()
        for payload in payloads:
            account = payload.get('account')
            profile = payload.get('profile') or {}
            target = account or {'email': profile.get('email') or '', 'chrome_profile': profile.get('directory') or ''}
            directory = str((account or {}).get('chrome_profile') or profile.get('directory') or '')
            if directory and directory in seen:
                continue
            try:
                directory = flow_accounts.open_account_browser(target)
            except ValueError as exc:
                errors.append(str(exc))
                continue
            seen.add(directory)
            opened.append(directory)
        if opened:
            shown = '、'.join(opened[:6])
            suffix = f' 等 {len(opened)} 个用户' if len(opened) > 6 else ''
            self.status.setText(f'已分别打开 {shown}{suffix} 的 Flow。每个窗口只上报自己当前登录的账号。')
        if errors and not opened:
            QMessageBox.warning(self, '账号管理', '\n'.join(errors[:6]))
        elif errors:
            self.status.setText(self.status.text() + f' 另有 {len(errors)} 个没有对应的 Chrome 用户。')
        self.refresh()

    def load_chrome_users(self):
        if self._chrome_loading:
            self.status.setText('正在读取 Chrome 用户…')
            return
        self._chrome_loading = True
        self.status.setText('正在读取 Chrome 用户…')
        threading.Thread(target=self._read_chrome_users, name='chrome-profiles', daemon=True).start()

    def _read_chrome_users(self):
        error = ''
        profiles = []
        try:
            profiles = flow_accounts.list_chrome_profiles()
        except Exception as exc:
            error = str(exc)
        self._chrome_profiles_ready.emit(profiles, error)

    def _apply_chrome_profiles(self, profiles, error):
        self._chrome_loading = False
        if error:
            self._chrome_loaded = False
            self.status.setText(f'没有读到 Chrome 用户：{error}')
            return
        self._chrome_loaded = True
        self._profile_list = list(profiles or [])
        self._profiles = {item['directory']: item for item in self._profile_list}
        self._avatar_cache = {}
        self._table_signature = None
        ready = sum(1 for item in self._profile_list if item['state'] != '未登录')
        self.status.setText(f'读到 {len(self._profile_list)} 个 Chrome 用户，其中 {ready} 个已登录 Flow 或可以直接打开。勾选后加入换号。')
        # A navigation refresh may still be on the stack. Fill the table on the next turn.
        QTimer.singleShot(0, self.refresh)

    def _row_toggled(self, item):
        if self._loading or item.column() != 0:
            return
        row = item.row()
        if row < 0 or row >= len(self._row_payload):
            return
        payload = self._row_payload[row]
        profile = payload.get('profile')
        account = payload.get('account')
        try:
            if item.checkState() == Qt.Checked:
                if profile:
                    flow_accounts.use_chrome_profile(profile)
                    self.status.setText(f'已勾选 {profile["name"]}：{profile["state"]}')
                elif account:
                    flow_accounts.set_enabled(account['id'], True)
                    self.status.setText(f'已勾选表格账号 {account["email"]}')
            elif profile:
                flow_accounts.disable_chrome_profile(profile)
                self.status.setText(f'已取消 {profile["name"]}')
            elif account:
                flow_accounts.set_enabled(account['id'], False)
                self.status.setText(f'已取消表格账号 {account["email"]}')
        except ValueError as exc:
            self.table.blockSignals(True)
            item.setCheckState(Qt.Unchecked)
            self.table.blockSignals(False)
            self.status.setText(str(exc))
            return
        self.refresh()

    def check_selected(self):
        account_id = self._selected_id()
        if not account_id:
            return
        account = flow_accounts.get_account(account_id)
        try:
            flow_accounts.request_point_read(account['email'])
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self._point_wait = {
            'id': account_id,
            'email': account['email'],
            'started': time.time(),
            'until': time.time() + 8,
        }
        self.status.setText('正在读取这一行的 Flow 页面点数…')
        QTimer.singleShot(800, self._finish_point_read)

    def _finish_point_read(self):
        wait = getattr(self, '_point_wait', None)
        if not wait:
            return
        page = flow_accounts.seen_page(wait['email'])
        fresh = bool(page) and page.get('credits') not in (None, '') and float(page.get('at') or 0) >= wait['started'] - 1
        if not fresh and time.time() < wait['until']:
            QTimer.singleShot(700, self._finish_point_read)
            return
        self._point_wait = None
        try:
            _account, message = flow_accounts.read_page_credits(wait['id'])
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self.status.setText(message)
        self.refresh()

    def correct_selected(self):
        account_id = self._selected_id()
        if not account_id:
            return
        account = flow_accounts.get_account(account_id)
        dialog = QDialog(self)
        dialog.setWindowTitle('修正剩余点数')
        form = QFormLayout(dialog)
        spin = QSpinBox()
        spin.setRange(0, 100000)
        today = _dt.date.today().isoformat()
        credits, _estimated = flow_accounts.usable_credits(account, today)
        spin.setValue(credits)
        form.addRow(account['email'], spin)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec():
            flow_accounts.set_remaining(account_id, spin.value())
            self.refresh()

    def delete_selected(self):
        account_id = self._selected_id()
        if not account_id:
            return
        account = flow_accounts.get_account(account_id)
        if QMessageBox.question(self, '删除账号', f'删除 {account["email"]} 及其保存的登录信息？') != QMessageBox.Yes:
            return
        flow_accounts.delete_account(account_id)
        self.refresh()
