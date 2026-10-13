"""Display original Sheets formatting without putting markup in task text."""
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QFont, QTextDocument, QTextCursor, QTextCharFormat, QTextBlockFormat, QPalette
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QStyle, QTextEdit
from app.services.sheet_style import runs, color_rgb

STYLE_ROLE = int(Qt.UserRole) + 71
BASELINE_ROLE = int(Qt.UserRole) + 72


def color(value):
    return QColor.fromRgbF(*(max(0.0, min(1.0, float(value.get(k, 0)))) for k in ('red', 'green', 'blue')), float(value.get('alpha', 1)))


def apply(document, snapshot, min_point_size=0):
    cell_format = dict(snapshot.get('defaults', {}))
    cell_format.update(snapshot.get('cell', {}).get('effectiveFormat', snapshot.get('cell', {}).get('userEnteredFormat', {})))
    alignments = {'LEFT':Qt.AlignLeft, 'CENTER':Qt.AlignHCenter, 'RIGHT':Qt.AlignRight}
    if cell_format.get('horizontalAlignment') in alignments:
        cursor=QTextCursor(document);cursor.select(QTextCursor.Document)
        block=QTextBlockFormat();block.setAlignment(alignments[cell_format['horizontalAlignment']]);cursor.mergeBlockFormat(block)
    floor = float(min_point_size or 0)
    # QTextCursor positions, like Sheets textFormatRuns, count UTF-16 code units.
    for start, end, fmt in runs(snapshot):
        cursor = QTextCursor(document)
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.KeepAnchor)
        style = QTextCharFormat()
        rgb = color_rgb(fmt, snapshot.get('theme', {}))
        style.setForeground(color(rgb or {}))
        style.setFontWeight(QFont.Bold if fmt.get('bold') else QFont.Normal)
        style.setFontItalic(bool(fmt.get('italic')))
        style.setFontUnderline(bool(fmt.get('underline')))
        style.setFontStrikeOut(bool(fmt.get('strikethrough')))
        if fmt.get('fontFamily'): style.setFontFamilies([fmt['fontFamily']])
        size = float(fmt['fontSize']) if fmt.get('fontSize') else 0
        if floor:
            size = max(size, floor)
        if size:
            style.setFontPointSize(size)
        cursor.setCharFormat(style)


def attach(item, snapshot):
    if snapshot and item.text() == snapshot.get('text'):
        item.setData(STYLE_ROLE, snapshot)
    item.setData(BASELINE_ROLE, item.text())


class SheetTextDelegate(QStyledItemDelegate):
    def __init__(self, parent=None, min_point_size=0):
        super().__init__(parent)
        self.min_point_size = float(min_point_size or 0)

    def _readable_font(self, font):
        if self.min_point_size <= 0:
            return font
        sized = QFont(font)
        current = sized.pointSizeF()
        if current <= 0 and sized.pixelSize() > 0:
            current = sized.pixelSize() * 72 / 96
        if current < self.min_point_size:
            sized.setPointSizeF(self.min_point_size)
        return sized

    def _snapshot(self, index):
        value = index.data(STYLE_ROLE)
        return value if value and value.get('text') == index.data(Qt.DisplayRole) else None

    def _document(self, index, font, width):
        doc = QTextDocument()
        font = self._readable_font(font)
        doc.setDefaultFont(font)
        doc.setDocumentMargin(4)
        doc.setPlainText(index.data(Qt.DisplayRole) or '')
        snapshot = self._snapshot(index)
        if snapshot:
            apply(doc, snapshot, self.min_point_size)
        doc.setTextWidth(max(20, width))
        return doc

    def paint(self, painter, option, index):
        snapshot = self._snapshot(index)
        if not snapshot:
            return super().paint(painter, option, index)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ''
        style = opt.widget.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)
        doc = self._document(index, opt.font, opt.rect.width())
        painter.save()
        painter.setClipRect(opt.rect)
        painter.translate(opt.rect.topLeft())
        cell_format = snapshot.get('cell', {}).get('effectiveFormat', snapshot.get('defaults', {}))
        background = color_rgb(cell_format, snapshot.get('theme', {}), 'backgroundColor')
        painter.fillRect(0, 0, opt.rect.width(), opt.rect.height(), color(background or {'red':1,'green':1,'blue':1}))
        vertical = cell_format.get('verticalAlignment', 'TOP')
        shift = max(0, opt.rect.height() - doc.size().height())
        painter.save()
        if vertical == 'MIDDLE': painter.translate(0, shift/2)
        elif vertical == 'BOTTOM': painter.translate(0, shift)
        doc.drawContents(painter)
        painter.restore()
        if opt.state & QStyle.State_Selected:
            pen = painter.pen(); pen.setColor(opt.palette.color(QPalette.Highlight)); pen.setWidth(2)
            painter.setPen(pen); painter.drawRect(1, 1, opt.rect.width()-2, opt.rect.height()-2)
        painter.restore()

    def sizeHint(self, option, index):
        if not self._snapshot(index):
            return super().sizeHint(option, index)
        doc = self._document(index, option.font, option.rect.width())
        return QSize(int(doc.idealWidth()) + 8, int(doc.size().height()) + 8)

    def createEditor(self, parent, option, index):
        editor = QTextEdit(parent)
        editor.setAcceptRichText(False)
        editor.setFont(self._readable_font(option.font))
        return editor

    def setEditorData(self, editor, index):
        editor.setPlainText(index.data(Qt.EditRole) or '')
        snapshot = self._snapshot(index)
        if snapshot: apply(editor.document(), snapshot, self.min_point_size)

    def setModelData(self, editor, model, index):
        text = editor.toPlainText()
        if text != index.data(Qt.EditRole):
            model.setData(index, text, Qt.EditRole)
