"""Geometry-only helpers for the Flow monitor; no production state or persistence."""
from PySide6.QtCore import Qt, QRect, QSize, QEvent, QTimer
from PySide6.QtWidgets import QLayout, QScrollArea, QFrame, QSizePolicy


class WrappingRow(QLayout):
    def __init__(self, parent=None, spacing=8):
        super().__init__(parent)
        self.items=[]
        self.setContentsMargins(0,0,0,0)
        self.setSpacing(spacing)

    def addItem(self, item): self.items.append(item)
    def count(self): return len(self.items)
    def itemAt(self, i): return self.items[i] if 0<=i<len(self.items) else None
    def takeAt(self, i): return self.items.pop(i) if 0<=i<len(self.items) else None
    def expandingDirections(self): return Qt.Orientation.Horizontal
    def hasHeightForWidth(self): return True
    def heightForWidth(self, width): return self.arrange(QRect(0,0,width,0),False)
    def sizeHint(self):
        m=self.contentsMargins()
        width=sum(item.sizeHint().width() for item in self.items)+max(0,len(self.items)-1)*self.spacing()+m.left()+m.right()
        return QSize(width,self.heightForWidth(width))
    def minimumSize(self):
        return QSize(0,0)
    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.arrange(rect,True)
    def arrange(self, rect, apply):
        m=self.contentsMargins(); area=rect.adjusted(m.left(),m.top(),-m.right(),-m.bottom())
        x=area.x(); y=area.y(); line_height=0
        for item in self.items:
            if item.isEmpty(): continue
            hint=item.sizeHint(); width=min(hint.width(),max(1,area.width()))
            height=item.heightForWidth(width) if item.hasHeightForWidth() else hint.height()
            if x>area.x() and x+width>area.right()+1:
                x=area.x(); y+=line_height+self.spacing(); line_height=0
            if apply: item.setGeometry(QRect(x,y,width,height))
            x+=width+self.spacing(); line_height=max(line_height,height)
        return y+line_height-rect.y()+m.bottom()


class CardGrid(WrappingRow):
    def __init__(self, parent=None, minimum=220, maximum=280, card_height=150):
        super().__init__(parent)
        self.minimum=minimum; self.maximum=maximum; self.card_height=card_height

    def dimensions(self, width):
        columns=max(1,(max(1,width)+self.spacing())//(self.minimum+self.spacing()))
        columns=min(columns,max(1,self.count()))
        card_width=min(self.maximum,max(1,(width-(columns-1)*self.spacing())//columns))
        return columns,card_width

    def arrange(self, rect, apply):
        columns,width=self.dimensions(rect.width())
        for i,item in enumerate(self.items):
            if apply:
                item.setGeometry(QRect(rect.x()+(i%columns)*(width+self.spacing()),rect.y()+(i//columns)*(self.card_height+self.spacing()),width,self.card_height))
        rows=(self.count()+columns-1)//columns
        return rows*self.card_height+max(0,rows-1)*self.spacing()


class ContentScroll(QScrollArea):
    """Use content height until its cap; only then enable internal scrolling."""
    def __init__(self, cap, parent=None):
        super().__init__(parent)
        self.cap=cap; self.pending=False
        self.setObjectName('cardScroll')
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)

    def setWidget(self, widget):
        super().setWidget(widget)
        widget.installEventFilter(self)
        if widget.layout(): widget.layout().setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.schedule()

    def eventFilter(self, obj, event):
        if event.type()==QEvent.Type.LayoutRequest: self.schedule()
        return super().eventFilter(obj,event)

    def resizeEvent(self, event):
        super().resizeEvent(event); self.schedule()

    def schedule(self):
        if not self.pending:
            self.pending=True; QTimer.singleShot(0,self.fit_content)

    def fit_content(self):
        from shiboken6 import isValid
        if not isValid(self):return
        self.pending=False
        widget=self.widget()
        if widget is None or widget.layout() is None: return
        layout=widget.layout(); limit=max(1,int(self.cap()))
        width=max(1,self.contentsRect().width())
        def natural(w):
            return max(0,layout.heightForWidth(w) if layout.hasHeightForWidth() else layout.sizeHint().height())
        needed=natural(width)
        if needed>limit:
            width=max(1,width-self.verticalScrollBar().sizeHint().width())
            needed=natural(width)
        widget.setMinimumHeight(needed)
        self.setFixedHeight(min(limit,needed))
        widget.resize(max(1,self.viewport().width()),max(needed,self.viewport().height()))
        layout.setGeometry(widget.rect())


class ContentPanel(QFrame):
    """Keep wrapping toolbars/sections at their current width's natural height."""
    def __init__(self, *args, floor=0, **kwargs):
        super().__init__(*args, **kwargs)
        self.floor=floor; self.pending=False
        self.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
    def event(self,event):
        result=super().event(event)
        if event.type() in (QEvent.Type.Resize,QEvent.Type.LayoutRequest,QEvent.Type.Show) and not self.pending:
            self.pending=True;QTimer.singleShot(0,self.fit_content)
        return result
    def fit_content(self):
        from shiboken6 import isValid
        if not isValid(self):return
        self.pending=False
        layout=self.layout()
        if layout:
            height=layout.heightForWidth(self.width()) if layout.hasHeightForWidth() else layout.sizeHint().height()
            self.setFixedHeight(max(self.floor,height))
