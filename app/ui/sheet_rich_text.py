"""Display original Sheets formatting without putting markup in task text."""
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QFont, QTextDocument, QTextCursor, QTextCharFormat, QTextBlockFormat, QPalette
from PySide6.QtWidgets import QApplication, QStyledItemDelegate, QStyleOptionViewItem, QStyle, QTextEdit, QWidget
from app.services.sheet_style import runs, color_rgb

STYLE_ROLE = int(Qt.UserRole) + 71
BASELINE_ROLE = int(Qt.UserRole) + 72
VIDEO_GROUP_START_ROLE = int(Qt.UserRole) + 73


def color(value):
    return QColor.fromRgbF(*(max(0.0, min(1.0, float(value.get(k, 0)))) for k in ('red', 'green', 'blue')), float(value.get('alpha', 1)))


def is_dark_theme(source=None) -> bool:
    pal = None
    if isinstance(source, QPalette):
        pal = source
    elif isinstance(source, QWidget):
        pal = source.palette()
    if pal is not None:
        base_l = pal.color(QPalette.Base).lightness()
        win_l = pal.color(QPalette.Window).lightness()
        if base_l < 128 or win_l < 128:
            return True
        if base_l > 165 and win_l > 165:
            return False
    app = QApplication.instance()
    if app is not None:
        app_pal = app.palette()
        return app_pal.color(QPalette.Window).lightness() < 128 or app_pal.color(QPalette.Base).lightness() < 128
    return False


def adapt_fg_for_theme(qcolor: QColor, dark_mode: bool, default_fg: QColor | None = None) -> QColor:
    if not isinstance(qcolor, QColor):
        qcolor = QColor(qcolor)
    if not dark_mode or not qcolor.isValid():
        return qcolor
    fallback = default_fg if (default_fg is not None and default_fg.isValid()) else QColor('#EDF2F8')
    r, g, b = qcolor.red(), qcolor.green(), qcolor.blue()
    chroma = max(r, g, b) - min(r, g, b)
    sat = qcolor.hslSaturation()
    lum = qcolor.lightness()
    if chroma < 48 or sat < 42:
        if lum < 80:
            return QColor(fallback)
        if lum < 120:
            return QColor('#CBD5E1')
        if lum < 160:
            return QColor('#94A3B8')
        return qcolor
    hue = qcolor.hslHue()
    if hue < 22 or hue >= 338:
        return QColor('#F87171') if lum < 185 else qcolor
    if hue < 75:
        return QColor('#FBBF24') if lum < 185 else qcolor
    if hue < 175:
        return QColor('#4ADE80') if lum < 180 else qcolor
    if hue < 195:
        return QColor('#2DD4BF') if lum < 180 else qcolor
    if hue < 258:
        return QColor('#60A5FA') if lum < 185 else qcolor
    return QColor('#C084FC') if lum < 185 else qcolor


def _adapt_sheet_bg_for_theme(rgb_dict, dark_mode: bool, fallback_bg: QColor) -> QColor:
    if not dark_mode:
        return color(rgb_dict or {'red': 1, 'green': 1, 'blue': 1})
    if not rgb_dict:
        return QColor(fallback_bg)
    c = color(rgb_dict)
    if not c.isValid():
        return QColor(fallback_bg)
    if c.hslSaturation() < 25 and c.lightness() > 215:
        return QColor(fallback_bg)
    if c.lightness() > 115:
        t = 0.22
        return QColor(
            int(fallback_bg.red() * (1.0 - t) + c.red() * t),
            int(fallback_bg.green() * (1.0 - t) + c.green() * t),
            int(fallback_bg.blue() * (1.0 - t) + c.blue() * t),
        )
    return c


def apply(
    document,
    snapshot,
    min_point_size=0,
    max_point_size=0,
    keep_alignment=True,
    allow_bold=True,
    dark_mode=False,
    default_fg: QColor | None = None,
):
    fg_base = default_fg if (default_fg is not None and default_fg.isValid()) else (
        QColor('#EDF2F8') if dark_mode else QColor('#182235')
    )
    cell_format = dict(snapshot.get('defaults', {}))
    cell_format.update(snapshot.get('cell', {}).get('effectiveFormat', snapshot.get('cell', {}).get('userEnteredFormat', {})))
    alignments = {'LEFT':Qt.AlignLeft, 'CENTER':Qt.AlignHCenter, 'RIGHT':Qt.AlignRight}
    if keep_alignment and cell_format.get('horizontalAlignment') in alignments:
        cursor=QTextCursor(document);cursor.select(QTextCursor.Document)
        block=QTextBlockFormat();block.setAlignment(alignments[cell_format['horizontalAlignment']]);cursor.mergeBlockFormat(block)
    floor = float(min_point_size or 0)
    ceiling = float(max_point_size or 0)
    # QTextCursor positions, like Sheets textFormatRuns, count UTF-16 code units.
    for start, end, fmt in runs(snapshot):
        cursor = QTextCursor(document)
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.KeepAnchor)
        style = QTextCharFormat()
        rgb = color_rgb(fmt, snapshot.get('theme', {}))
        if rgb:
            fg = adapt_fg_for_theme(color(rgb), dark_mode, fg_base)
        else:
            fg = QColor(fg_base) if dark_mode else color({})
        style.setForeground(fg)
        style.setFontWeight(QFont.Bold if (allow_bold and fmt.get('bold')) else QFont.Normal)
        style.setFontItalic(bool(fmt.get('italic')))
        style.setFontUnderline(bool(fmt.get('underline')))
        style.setFontStrikeOut(bool(fmt.get('strikethrough')))
        if fmt.get('fontFamily'): style.setFontFamilies([fmt['fontFamily']])
        size = float(fmt['fontSize']) if fmt.get('fontSize') else 0
        if floor:
            size = max(size, floor)
        if ceiling:
            size = min(size, ceiling) if size else ceiling
        if size:
            style.setFontPointSize(size)
        cursor.setCharFormat(style)


def attach(item, snapshot):
    if snapshot and item.text() == snapshot.get('text'):
        item.setData(STYLE_ROLE, snapshot)
    item.setData(BASELINE_ROLE, item.text())


class _SegmentCellEditor(QTextEdit):
    """Inline table editor where pressing Enter splits the text after the cursor to the next row."""
    def __init__(self, delegate, parent=None):
        super().__init__(parent)
        self._delegate = delegate

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (event.modifiers() & Qt.ControlModifier):
            cursor = self.textCursor()
            full_text = self.toPlainText()
            pos = cursor.selectionStart()
            before = ' '.join(full_text[:pos].split())
            after = ' '.join(full_text[cursor.selectionEnd():].split())
            if before and after:
                self.setPlainText(before + '\n' + after)
            self._delegate.commitData.emit(self)
            self._delegate.closeEditor.emit(self, QStyledItemDelegate.NoHint)
            event.accept()
            return
        super().keyPressEvent(event)


class SheetTextDelegate(QStyledItemDelegate):
    def __init__(self, parent=None, min_point_size=0, max_point_size=0, split_on_enter=False, clean_background=False):
        super().__init__(parent)
        from collections import OrderedDict
        self.min_point_size = float(min_point_size or 0)
        self.max_point_size = float(max_point_size or 0)
        self.split_on_enter = bool(split_on_enter)
        self.clean_background = bool(clean_background)
        self._doc_cache = OrderedDict()

    def set_point_size(self, pt: float):
        val = float(pt or 0)
        self.min_point_size = val
        self.max_point_size = val
        self._doc_cache.clear()

    def _readable_font(self, font):
        if self.min_point_size <= 0 and self.max_point_size <= 0:
            return font
        sized = QFont(font)
        current = sized.pointSizeF()
        if current <= 0 and sized.pixelSize() > 0:
            current = sized.pixelSize() * 72 / 96
        if self.min_point_size > 0 and current < self.min_point_size:
            current = self.min_point_size
        if self.max_point_size > 0 and (current <= 0 or current > self.max_point_size):
            current = self.max_point_size
        if current > 0:
            sized.setPointSizeF(current)
        return sized

    def _snapshot(self, index):
        value = index.data(STYLE_ROLE)
        return value if value and value.get('text') == index.data(Qt.DisplayRole) else None

    def _document(self, index, font, width, dark_mode=False, default_fg: QColor | None = None):
        text = index.data(Qt.DisplayRole) or ''
        snapshot = self._snapshot(index)
        w = max(20, int(width))
        fg_base = default_fg if (default_fg is not None and default_fg.isValid()) else (
            QColor('#EDF2F8') if dark_mode else QColor('#182235')
        )
        cache_key = (
            id(snapshot),
            text,
            self.min_point_size,
            self.max_point_size,
            font.key(),
            bool(dark_mode),
            int(fg_base.rgba()),
        )
        cached = self._doc_cache.get(cache_key)
        if cached is not None:
            if int(cached.textWidth()) != w:
                cached.setTextWidth(w)
            self._doc_cache.move_to_end(cache_key)
            return cached
        doc = QTextDocument()
        font = self._readable_font(font)
        if self.clean_background:
            font.setBold(False)
            font.setWeight(QFont.Normal)
        doc.setDefaultFont(font)
        doc.setDocumentMargin(4)
        doc.setPlainText(text)
        base_cursor = QTextCursor(doc)
        base_cursor.select(QTextCursor.Document)
        base_fmt = QTextCharFormat()
        base_fmt.setForeground(QColor(fg_base))
        base_cursor.mergeCharFormat(base_fmt)
        if snapshot:
            apply(
                doc,
                snapshot,
                self.min_point_size,
                self.max_point_size,
                keep_alignment=not self.clean_background,
                allow_bold=not self.clean_background,
                dark_mode=dark_mode,
                default_fg=fg_base,
            )
        doc.setTextWidth(w)
        while len(self._doc_cache) >= 256:
            self._doc_cache.popitem(last=False)
        self._doc_cache[cache_key] = doc
        return doc

    def paint(self, painter, option, index):
        snapshot = self._snapshot(index)
        if not snapshot and not self.clean_background:
            return super().paint(painter, option, index)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ''
        dark_mode = is_dark_theme(opt.palette)
        default_fg = QColor('#EDF2F8') if dark_mode else QColor('#182235')
        doc = self._document(index, opt.font, opt.rect.width(), dark_mode=dark_mode, default_fg=default_fg)
        painter.save()
        painter.setClipRect(opt.rect)
        selected = bool(opt.state & QStyle.State_Selected)
        if self.clean_background:
            base_bg = (
                QColor('#223148' if selected else '#1D242E')
                if dark_mode
                else QColor('#EFF6FF' if selected else '#FFFFFF')
            )
            painter.fillRect(opt.rect, base_bg)
            if index.data(VIDEO_GROUP_START_ROLE):
                painter.fillRect(
                    opt.rect.left(),
                    opt.rect.top(),
                    opt.rect.width(),
                    2,
                    QColor('#3E5068' if dark_mode else '#CBD5E1'),
                )
            painter.translate(opt.rect.topLeft())
            shift = max(0, opt.rect.height() - doc.size().height())
            painter.save()
            painter.translate(0, shift / 2)
            doc.drawContents(painter)
            painter.restore()
            if selected:
                pen = painter.pen()
                pen.setColor(QColor('#4B82F1' if dark_mode else '#93C5FD'))
                pen.setWidth(1)
                painter.setPen(pen)
                painter.drawRect(0, 0, opt.rect.width() - 1, opt.rect.height() - 1)
            painter.restore()
            return
        style = opt.widget.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)
        painter.translate(opt.rect.topLeft())
        cell_format = snapshot.get('cell', {}).get('effectiveFormat', snapshot.get('defaults', {}))
        background = color_rgb(cell_format, snapshot.get('theme', {}), 'backgroundColor')
        fallback_bg = QColor('#1D242E' if dark_mode else '#FFFFFF')
        painter.fillRect(0, 0, opt.rect.width(), opt.rect.height(), _adapt_sheet_bg_for_theme(background, dark_mode, fallback_bg))
        vertical = cell_format.get('verticalAlignment', 'TOP')
        shift = max(0, opt.rect.height() - doc.size().height())
        painter.save()
        if vertical == 'MIDDLE': painter.translate(0, shift/2)
        elif vertical == 'BOTTOM': painter.translate(0, shift)
        doc.drawContents(painter)
        painter.restore()
        if selected:
            pen = painter.pen(); pen.setColor(QColor('#4B82F1') if dark_mode else opt.palette.color(QPalette.Highlight)); pen.setWidth(2)
            painter.setPen(pen); painter.drawRect(1, 1, opt.rect.width()-2, opt.rect.height()-2)
        painter.restore()

    def sizeHint(self, option, index):
        if not self._snapshot(index):
            return super().sizeHint(option, index)
        dark_mode = is_dark_theme(option.palette)
        doc = self._document(index, option.font, option.rect.width(), dark_mode=dark_mode)
        return QSize(int(doc.idealWidth()) + 8, int(doc.size().height()) + 8)

    def createEditor(self, parent, option, index):
        editor = _SegmentCellEditor(self, parent) if self.split_on_enter else QTextEdit(parent)
        editor.setAcceptRichText(False)
        editor.setFont(self._readable_font(option.font))
        dark_mode = is_dark_theme(option.palette) or is_dark_theme(parent)
        editor.setProperty('_dark_mode_editor', dark_mode)
        if dark_mode:
            editor.setStyleSheet(
                "QTextEdit { background:#18202B; color:#F1F5F9; border:1.5px solid #4B82F1; "
                "border-radius:4px; padding:2px; selection-background-color:#2563EB; selection-color:#FFFFFF; }"
            )
        elif self.clean_background:
            editor.setStyleSheet(
                "QTextEdit { background:#FFFFFF; color:#182235; border:1.5px solid #3B82F6; "
                "border-radius:4px; padding:2px; selection-background-color:#2563EB; selection-color:#FFFFFF; }"
            )
        return editor

    def setEditorData(self, editor, index):
        editor.setPlainText(index.data(Qt.EditRole) or '')
        dark_mode = bool(editor.property('_dark_mode_editor')) or is_dark_theme(editor)
        default_fg = QColor('#F1F5F9') if dark_mode else QColor('#182235')
        base_cursor = QTextCursor(editor.document())
        base_cursor.select(QTextCursor.Document)
        base_fmt = QTextCharFormat()
        base_fmt.setForeground(default_fg)
        base_cursor.mergeCharFormat(base_fmt)
        snapshot = self._snapshot(index)
        if snapshot:
            apply(
                editor.document(),
                snapshot,
                self.min_point_size,
                self.max_point_size,
                keep_alignment=not self.clean_background,
                allow_bold=not self.clean_background,
                dark_mode=dark_mode,
                default_fg=default_fg,
            )

    def setModelData(self, editor, model, index):
        text = editor.toPlainText()
        if text != index.data(Qt.EditRole):
            model.setData(index, text, Qt.EditRole)


class CleanItemColorDelegate(QStyledItemDelegate):
    """Preserves QTableWidgetItem foreground color even when row is selected, adapting cleanly to Light/Dark themes."""
    def __init__(self, parent=None, *, clean_background: bool = False):
        super().__init__(parent)
        self.clean_background = bool(clean_background)

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        dark_mode = is_dark_theme(opt.palette)
        selected = bool(option.state & QStyle.State_Selected)
        default_fg = QColor('#EDF2F8') if dark_mode else QColor('#182235')
        fg = index.data(Qt.ForegroundRole)
        if fg is not None:
            color_val = fg.color() if hasattr(fg, 'color') else QColor(fg)
            target_fg = adapt_fg_for_theme(color_val, dark_mode, default_fg)
        else:
            target_fg = default_fg

        painter.save()
        painter.setClipRect(opt.rect)
        if selected:
            painter.fillRect(opt.rect, QColor('#223148' if dark_mode else '#EFF6FF'))
        else:
            bg = index.data(Qt.BackgroundRole)
            if bg is not None:
                bg_col = bg.color() if hasattr(bg, 'color') else QColor(bg)
                if bg_col.isValid():
                    painter.fillRect(opt.rect, bg_col)
            elif self.clean_background:
                painter.fillRect(opt.rect, QColor('#1D242E' if dark_mode else '#FFFFFF'))
        if self.clean_background and index.data(VIDEO_GROUP_START_ROLE):
            painter.fillRect(
                opt.rect.left(),
                opt.rect.top(),
                opt.rect.width(),
                2,
                QColor('#3E5068' if dark_mode else '#CBD5E1'),
            )

        font = QFont(opt.font)
        item_font = index.data(Qt.FontRole)
        want_bold = bool(isinstance(item_font, QFont) and item_font.bold())
        font.setBold(want_bold)
        font.setWeight(QFont.Bold if want_bold else QFont.Normal)
        painter.setFont(font)
        painter.setPen(target_fg)

        text = str(opt.text or '')
        if text:
            align = int(opt.displayAlignment) if opt.displayAlignment else int(Qt.AlignLeft | Qt.AlignVCenter)
            flags = align | (Qt.TextWordWrap if (opt.features & QStyleOptionViewItem.WrapText) else Qt.TextSingleLine)
            text_rect = opt.rect.adjusted(6, 2, -6, -2)
            painter.drawText(text_rect, flags, text)
        painter.restore()
