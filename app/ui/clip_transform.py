from PySide6.QtCore import Qt, QRectF, QEvent, QLocale, QPoint
from PySide6.QtGui import QPainter, QImage, QColor, QPen, QBrush
from PySide6.QtWidgets import (
    QWidget,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QDoubleSpinBox,
    QComboBox,
    QLabel,
    QPushButton,
    QDialogButtonBox,
    QMessageBox,
    QSlider,
    QFrame,
)
from PySide6.QtMultimedia import QVideoSink
from app.services import clip_transform as transforms


class TransformVideoWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._sink = QVideoSink(self)
        self._sink.videoFrameChanged.connect(self.frame_changed)
        self.image = QImage()
        self.values = dict(transforms.DEFAULT)

    def videoSink(self):
        return self._sink

    def setAspectRatioMode(self, *args):
        pass

    def frame_changed(self, frame):
        self.image = frame.toImage()
        self.update()

    def set_transform(self, values):
        self.values = transforms.validate(values)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor('#0F172A'))
        v = self.values
        is_transformed = (abs(float(v.get('ZoomX', 1.0)) - 1.0) > 1e-4 or abs(float(v.get('Pan', 0.0))) > 1e-2 or abs(float(v.get('Tilt', 0.0))) > 1e-2)
        if is_transformed:
            p.setPen(QPen(QColor(148, 163, 184, 70), 1, Qt.DashLine))
            p.drawLine(0, self.height() // 2, self.width(), self.height() // 2)
            p.drawLine(self.width() // 2, 0, self.width() // 2, self.height())
        if not self.image.isNull():
            scale = min(self.width() / self.image.width(), self.height() / self.image.height()) * v['ZoomX']
            w, h = self.image.width() * scale, self.image.height() * scale
            x = (self.width() - w) / 2 + v['Pan'] * self.width() / v['width']
            y = (self.height() - h) / 2 - v['Tilt'] * self.height() / v['height']
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            img_rect = QRectF(x, y, w, h)
            p.drawImage(img_rect, self.image)
            if is_transformed:
                p.setPen(QPen(QColor('#38BDF8'), 1.5, Qt.SolidLine))
                p.setBrush(Qt.NoBrush)
                p.drawRect(img_rect)
        # Always draw crisp 9:16 output boundary border
        p.setPen(QPen(QColor('#3B82F6'), 2))
        p.setBrush(Qt.NoBrush)
        p.drawRect(self.rect().adjusted(1, 1, -1, -1))


class ScrubDoubleSpinBox(QDoubleSpinBox):
    """Number input that supports direct horizontal/vertical mouse drag scrubbing as well as keyboard typing."""

    def __init__(self, scrub_step=0.005, parent=None):
        super().__init__(parent)
        self.setLocale(QLocale(QLocale.C))
        self.scrub_step = float(scrub_step)
        self._pressing = False
        self._dragging = False
        self._start_pos = QPoint()
        self._start_val = 0.0
        self.setCursor(Qt.SizeHorCursor)
        self.setToolTip('💡 按住数字左右拖动可快速调节（按住 Shift 精细微调，滚轮也可调节，单击可直接输入数字）')
        le = self.lineEdit()
        if le is not None:
            le.setCursor(Qt.SizeHorCursor)
            le.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self.lineEdit():
            et = event.type()
            if et == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._pressing = True
                self._dragging = False
                self._start_pos = event.globalPosition().toPoint()
                self._start_val = self.value()
                return False
            elif et == QEvent.MouseMove and self._pressing:
                cur = event.globalPosition().toPoint()
                dx = cur.x() - self._start_pos.x()
                dy = self._start_pos.y() - cur.y()
                delta_px = dx if abs(dx) >= abs(dy) else dy
                if not self._dragging and abs(delta_px) >= 3:
                    self._dragging = True
                    if self.lineEdit():
                        self.lineEdit().deselect()
                if self._dragging:
                    mult = 0.2 if (event.modifiers() & Qt.ShiftModifier) else (3.0 if (event.modifiers() & Qt.AltModifier) else 1.0)
                    new_val = self._start_val + delta_px * self.scrub_step * mult
                    self.setValue(max(self.minimum(), min(self.maximum(), new_val)))
                    return True
            elif et == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                was_dragging = self._dragging
                self._pressing = False
                self._dragging = False
                if was_dragging:
                    return True
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._pressing = True
            self._dragging = False
            self._start_pos = event.globalPosition().toPoint()
            self._start_val = self.value()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pressing:
            cur = event.globalPosition().toPoint()
            dx = cur.x() - self._start_pos.x()
            dy = self._start_pos.y() - cur.y()
            delta_px = dx if abs(dx) >= abs(dy) else dy
            if not self._dragging and abs(delta_px) >= 3:
                self._dragging = True
            if self._dragging:
                mult = 0.2 if (event.modifiers() & Qt.ShiftModifier) else (3.0 if (event.modifiers() & Qt.AltModifier) else 1.0)
                new_val = self._start_val + delta_px * self.scrub_step * mult
                self.setValue(max(self.minimum(), min(self.maximum(), new_val)))
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._pressing = False
        self._dragging = False
        super().mouseReleaseEvent(event)


class ScrubLabel(QLabel):
    """Label that also scrubs its paired spinbox when dragged left/right."""

    def __init__(self, text: str, spin: ScrubDoubleSpinBox, parent=None):
        super().__init__(text, parent)
        self.spin = spin
        self._pressing = False
        self._start_pos = QPoint()
        self._start_val = 0.0
        self.setCursor(Qt.SizeHorCursor)
        self.setToolTip('💡 按住标签或右侧数字左右拖动即可快速调节数值')

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._pressing = True
            self._start_pos = event.globalPosition().toPoint()
            self._start_val = self.spin.value()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pressing:
            cur = event.globalPosition().toPoint()
            dx = cur.x() - self._start_pos.x()
            dy = self._start_pos.y() - cur.y()
            delta_px = dx if abs(dx) >= abs(dy) else dy
            mult = 0.2 if (event.modifiers() & Qt.ShiftModifier) else (3.0 if (event.modifiers() & Qt.AltModifier) else 1.0)
            new_val = self._start_val + delta_px * self.spin.scrub_step * mult
            self.spin.setValue(max(self.spin.minimum(), min(self.spin.maximum(), new_val)))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._pressing = False
        super().mouseReleaseEvent(event)


class _InteractiveTransformPad(QFrame):
    """2D drag & wheel pad for simultaneous Pan X / Tilt Y dragging and wheel zooming."""

    def __init__(self, dialog: "ClipTransformDialog", parent=None):
        super().__init__(parent)
        self.dialog = dialog
        self.setFixedHeight(96)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip('在此区域按住鼠标直接拖动画面位置（X / Y），滚动鼠标滚轮直接缩放大小，双击居中恢复')
        self._dragging = False
        self._start_pt = QPoint()
        self._start_pan = 0.0
        self._start_tilt = 0.0

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self.setCursor(Qt.ClosedHandCursor)
            self._start_pt = event.globalPosition().toPoint()
            self._start_pan = self.dialog.fields['Pan'].value()
            self._start_tilt = self.dialog.fields['Tilt'].value()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            cur = event.globalPosition().toPoint()
            dx = cur.x() - self._start_pt.x()
            dy = self._start_pt.y() - cur.y()
            mult = 0.4 if (event.modifiers() & Qt.ShiftModifier) else 3.5
            self.dialog.fields['Pan'].setValue(self._start_pan + dx * mult)
            self.dialog.fields['Tilt'].setValue(self._start_tilt + dy * mult)
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._dragging = False
        self.setCursor(Qt.OpenHandCursor)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dialog.reset()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event):
        angle = event.angleDelta().y()
        if angle != 0:
            step = 0.02 if not (event.modifiers() & Qt.ShiftModifier) else 0.005
            delta = (angle / 120.0) * step
            z_spin = self.dialog.fields['ZoomX']
            z_spin.setValue(max(z_spin.minimum(), min(z_spin.maximum(), z_spin.value() + delta)))
            self.update()
            event.accept()
            return
        super().wheelEvent(event)

    def paintEvent(self, event):
        from app.ui.sheet_rich_text import is_dark_theme
        dark = is_dark_theme(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        p.setPen(QPen(QColor('#364355' if dark else '#CBD5E1'), 1))
        p.setBrush(QBrush(QColor('#1A222D' if dark else '#F8FAFC')))
        p.drawRoundedRect(rect, 8, 8)

        v = self.dialog.values()
        zoom = float(v.get('ZoomX', 1.0))
        pan = float(v.get('Pan', 0.0))
        tilt = float(v.get('Tilt', 0.0))

        # Right-side mini 9:16 viewport box
        stage = QRectF(rect.right() - 128, rect.top() + 8, 116, rect.height() - 16)
        p.setPen(QPen(QColor('#364355' if dark else '#CBD5E1'), 1))
        p.setBrush(QBrush(QColor('#111720' if dark else '#FFFFFF')))
        p.drawRoundedRect(stage, 6, 6)

        cx, cy = stage.center().x(), stage.center().y()
        p.setPen(QPen(QColor('#283344' if dark else '#E2E8F0'), 1, Qt.DashLine))
        p.drawLine(int(stage.left() + 6), int(cy), int(stage.right() - 6), int(cy))
        p.drawLine(int(cx), int(stage.top() + 6), int(cx), int(stage.bottom() - 6))

        p.save()
        p.setClipRect(stage.adjusted(2, 2, -2, -2))
        base_w, base_h = 36.0, 62.0
        bound_rect = QRectF(cx - base_w / 2.0, cy - base_h / 2.0, base_w, base_h)
        # 1. Fixed 9:16 video output boundary backdrop
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(226, 232, 240, 22) if dark else QColor(15, 23, 42, 18)))
        p.drawRoundedRect(bound_rect, 3, 3)

        # 2. Moved / zoomed video frame (blue)
        fw = max(14.0, min(stage.width() * 2.2, base_w * min(zoom, 2.5)))
        fh = max(24.0, min(stage.height() * 2.2, base_h * min(zoom, 2.5)))
        tw = float(v.get('width', 720) or 720)
        th = float(v.get('height', 1280) or 1280)
        ox = cx - fw / 2.0 + (pan / tw) * base_w
        oy = cy - fh / 2.0 - (tilt / th) * base_h
        p.setPen(QPen(QColor('#60A5FA' if dark else '#2563EB'), 1.8))
        p.setBrush(QBrush(QColor(59, 130, 246, 56) if dark else QColor(37, 99, 235, 42)))
        p.drawRoundedRect(QRectF(ox, oy, fw, fh), 3, 3)

        # 3. Fixed 9:16 video output boundary outline drawn on top so it is NEVER lost when panning/zooming
        p.setPen(QPen(QColor('#F87171' if dark else '#DC2626'), 1.5, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(bound_rect, 3, 3)
        p.restore()

        # Left-side instructions & live readout
        text_rect = rect.adjusted(14, 10, -140, -8)
        p.setPen(QColor('#F1F5F9' if dark else '#1E293B'))
        f = p.font()
        f.setPointSize(12)
        f.setBold(True)
        p.setFont(f)
        p.drawText(text_rect, Qt.AlignLeft | Qt.AlignTop, '✥ 2D 触控板（按住拖画面 · 滚轮缩放）')

        f.setPointSize(11)
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor('#94A3B8' if dark else '#64748B'))
        p.drawText(
            text_rect.adjusted(0, 22, 0, 0),
            Qt.AlignLeft | Qt.AlignTop,
            f'红虚线框 = 视频边界  ·  蓝框 = 当前画面（双击归零）\n当前：{zoom:.3f}x   |   X: {pan:+.1f}   |   Y: {tilt:+.1f}',
        )


class ClipTransformDialog(QDialog):
    def __init__(self, output_id, preview, parent=None, extra_previews=None):
        super().__init__(parent)
        self.output_id = output_id
        self.preview = preview
        self._all_previews = [p for p in ([preview] + list(extra_previews or [])) if p is not None and hasattr(p, 'set_transform')]
        self.original = transforms.get(output_id)
        self.setWindowTitle('当前片段 · 画面调整')
        self.setModal(True)
        self.resize(520, 440)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        note = QLabel(
            '仅调整当前片段预览与达芬奇导入参数，不修改原视频文件。\n'
            '💡 直接【按住数字左右拖动】、【拉动滑杆】或在下方【触控板拖拽/滚轮】即可高速调节！',
            objectName='clipTransformNote',
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        self.fields = {}
        self.sliders = {}
        self._syncing_controls = False

        form = QFormLayout()
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(12)
        layout.addLayout(form)

        specs = [
            ('ZoomX', '缩放 ↔', 0.1, 10.0, 0.01, 3, 0.005, 500, 2500, 1000.0, 1.0),
            ('Pan', '位置 X ↔', -4320.0, 4320.0, 10.0, 1, 2.0, -720, 720, 1.0, 0.0),
            ('Tilt', '位置 Y ↔', -7680.0, 7680.0, 10.0, 1, 2.0, -1280, 1280, 1.0, 0.0),
        ]

        for key, label_txt, lo, hi, step, dec, scrub_step, s_min, s_max, s_scale, default_val in specs:
            spin = ScrubDoubleSpinBox(scrub_step=scrub_step)
            spin.setRange(lo, hi)
            spin.setDecimals(dec)
            spin.setSingleStep(step)
            spin.setValue(self.original[key])
            spin.setMinimumWidth(98)
            spin.setFixedHeight(32)
            self.fields[key] = spin

            slider = QSlider(Qt.Horizontal)
            slider.setRange(s_min, s_max)
            slider.setValue(int(round(self.original[key] * s_scale)))
            slider.setCursor(Qt.PointingHandCursor)
            self.sliders[key] = (slider, s_scale)

            reset_one = QPushButton('重置', objectName='clipTransformResetBtn')
            reset_one.setFixedSize(46, 28)
            reset_one.setCursor(Qt.PointingHandCursor)
            reset_one.setToolTip(f'重置 {label_txt.replace(" ↔", "")} 为默认值 ({default_val})')
            reset_one.clicked.connect(lambda _=False, k=key, dv=default_val: self.fields[k].setValue(dv))

            row_w = QWidget()
            row_l = QHBoxLayout(row_w)
            row_l.setContentsMargins(0, 0, 0, 0)
            row_l.setSpacing(8)
            row_l.addWidget(spin)
            row_l.addWidget(slider, 1)
            row_l.addWidget(reset_one)

            lbl_widget = ScrubLabel(label_txt, spin)
            lbl_widget.setObjectName('clipTransformFieldLbl')
            form.addRow(lbl_widget, row_w)

            spin.valueChanged.connect(lambda val, k=key: self._on_spin_changed(k, val))
            slider.valueChanged.connect(lambda sval, k=key: self._on_slider_changed(k, sval))

        # Quick Zoom preset pills
        preset_row = QHBoxLayout()
        preset_row.setSpacing(6)
        preset_lbl = QLabel('快捷缩放', objectName='clipTransformPresetLbl')
        preset_row.addWidget(preset_lbl)
        for z_preset in (1.0, 1.05, 1.10, 1.15, 1.20, 1.30, 1.50):
            pbtn = QPushButton(f'{z_preset:.2f}x'.rstrip('0').rstrip('.') + ('x' if f'{z_preset:.2f}'.endswith('00') else ''), objectName='clipTransformPresetBtn')
            pbtn.setText(f'{z_preset:g}x' if z_preset in (1.0, 1.1, 1.2, 1.3, 1.5) else f'{z_preset:.2f}x')
            pbtn.setFixedHeight(26)
            pbtn.setCursor(Qt.PointingHandCursor)
            pbtn.clicked.connect(lambda _=False, zv=z_preset: self.fields['ZoomX'].setValue(zv))
            preset_row.addWidget(pbtn)
        preset_row.addStretch(1)
        layout.addLayout(preset_row)

        # 2D Interactive drag pad
        self.touch_pad = _InteractiveTransformPad(self)
        layout.addWidget(self.touch_pad)

        # Timeline resolution selector
        tl_form = QFormLayout()
        tl_form.setHorizontalSpacing(12)
        self.size = QComboBox()
        self.size.addItem('720 × 1280（自动剪辑默认）', (720, 1280))
        self.size.addItem('1080 × 1920', (1080, 1920))
        self.size.setCurrentIndex(0 if self.original['width'] == 720 else 1)
        tl_form.addRow('达芬奇时间线', self.size)
        self.size.currentIndexChanged.connect(self.changed)
        layout.addLayout(tl_form)

        reset = QPushButton('恢复原始画面 (1.0x · 居中)')
        reset.setCursor(Qt.PointingHandCursor)
        reset.clicked.connect(self.reset)
        layout.addWidget(reset)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText('保存')
        buttons.button(QDialogButtonBox.Cancel).setText('取消')
        buttons.accepted.connect(self.store)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_spin_changed(self, key: str, val: float):
        if not self._syncing_controls and key in self.sliders:
            slider, scale = self.sliders[key]
            self._syncing_controls = True
            try:
                sval = int(round(val * scale))
                sval = max(slider.minimum(), min(slider.maximum(), sval))
                slider.setValue(sval)
            finally:
                self._syncing_controls = False
        self.changed()

    def _on_slider_changed(self, key: str, sval: int):
        if self._syncing_controls or key not in self.fields:
            return
        _slider, scale = self.sliders[key]
        self._syncing_controls = True
        try:
            self.fields[key].setValue(float(sval) / float(scale))
        finally:
            self._syncing_controls = False
        self.changed()

    def values(self):
        w, h = self.size.currentData()
        return dict(
            ZoomX=self.fields['ZoomX'].value(),
            Pan=self.fields['Pan'].value(),
            Tilt=self.fields['Tilt'].value(),
            width=w,
            height=h,
        )

    def _apply_to_previews(self, vals):
        for p in self._all_previews:
            try:
                p.set_transform(vals)
            except Exception:
                pass

    def changed(self, *args):
        if hasattr(self, 'size'):
            w, h = self.size.currentData()
            self.fields['Pan'].setRange(-4 * w, 4 * w)
            self.fields['Tilt'].setRange(-4 * h, 4 * h)
            if 'Pan' in self.sliders:
                self.sliders['Pan'][0].setRange(-w, w)
            if 'Tilt' in self.sliders:
                self.sliders['Tilt'][0].setRange(-h, h)
            self._apply_to_previews(self.values())
            if hasattr(self, 'touch_pad'):
                self.touch_pad.update()

    def reset(self):
        for k, s in self.fields.items():
            s.setValue(transforms.DEFAULT[k])

    def store(self):
        try:
            transforms.save(self.output_id, self.values())
        except Exception as exc:
            QMessageBox.warning(self, '未保存', str(exc))
            return
        self.accept()

    def reject(self):
        self._apply_to_previews(self.original)
        super().reject()
