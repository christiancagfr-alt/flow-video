"""Virtual task rows: scrolling paints the viewport and never creates row widgets."""
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, Signal, QEvent
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionButton, QStyle, QApplication, QComboBox

class RuntimeTaskModel(QAbstractTableModel):
    retry_requested = Signal(int)
    headers = ['片段ID','接收人 / 主播','视频 / 片段','通道','状态','连续失败','原因','操作']
    def __init__(self, choices, parent=None):
        super().__init__(parent)
        self.choices = choices
        self.ids = []
        self.records = {}
        self.channels = ()
        self.busy = False
    def rowCount(self, parent=QModelIndex()): return 0 if parent.isValid() else len(self.ids)
    def columnCount(self, parent=QModelIndex()): return 8
    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation==Qt.Horizontal and role==Qt.DisplayRole:return self.headers[section]
    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():return None
        sid=self.ids[index.row()];record=self.records[sid]
        if role==Qt.UserRole:return sid
        if role==Qt.DisplayRole or role==Qt.EditRole:
            if index.column()==3:
                return self.choices.get(sid,record['channel'])
            return record['values'][index.column()]
        if role==Qt.ToolTipRole:return record['detail'] if index.column() in (5,6) else None
    def flags(self, index):
        flags=Qt.ItemIsEnabled|Qt.ItemIsSelectable
        if index.isValid() and index.column()==3 and not self.busy:flags|=Qt.ItemIsEditable
        return flags
    def setData(self,index,value,role=Qt.EditRole):
        if role!=Qt.EditRole or index.column()!=3 or value not in self.channels:return False
        self.choices[self.ids[index.row()]]=value
        self.dataChanged.emit(index,index,[Qt.DisplayRole]);return True
    def apply(self, records, channels):
        wanted={r['sid']:r for r in records}
        # Preserve existing row identities and selection; additions are batched.
        missing=[row for row,sid in enumerate(self.ids) if sid not in wanted]
        ranges=[]
        for row in missing:
            if ranges and row==ranges[-1][1]+1:ranges[-1][1]=row
            else:ranges.append([row,row])
        for first,last in reversed(ranges):
            self.beginRemoveRows(QModelIndex(),first,last)
            for sid in self.ids[first:last+1]:self.records.pop(sid,None);self.choices.pop(sid,None)
            del self.ids[first:last+1]
            self.endRemoveRows()
        old=self.records
        additions=[r['sid'] for r in records if r['sid'] not in old]
        if additions:
            start=len(self.ids);self.beginInsertRows(QModelIndex(),start,start+len(additions)-1)
            self.ids.extend(additions)
            for sid in additions:self.records[sid]=wanted[sid]
            self.endInsertRows()
        channel_changed=tuple(channels)!=self.channels;self.channels=tuple(channels)
        changed=[]
        for row,sid in enumerate(self.ids):
            if self.choices.get(sid) not in self.channels:
                channel=wanted[sid]['channel']
                self.choices[sid]=channel if channel in self.channels else (self.channels[0] if self.channels else '')
            if self.records.get(sid)!=wanted[sid] or channel_changed:changed.append(row)
        self.records=wanted
        # One signal per contiguous dirty range, no full-table reset.
        if changed:
            first=last=changed[0]
            for row in changed[1:]+[len(self.ids)+1]:
                if row==last+1:last=row;continue
                self.dataChanged.emit(self.index(first,0),self.index(last,7),[Qt.DisplayRole,Qt.ToolTipRole])
                first=last=row

class ChannelDelegate(QStyledItemDelegate):
    def createEditor(self,parent,option,index):
        editor=QComboBox(parent)
        editor.addItems(list(index.model().channels))
        editor.activated.connect(lambda _:self.commitData.emit(editor))
        return editor
    def setEditorData(self,editor,index):editor.setCurrentText(str(index.data(Qt.EditRole) or ''))
    def setModelData(self,editor,model,index):model.setData(index,editor.currentText())

class RetryDelegate(QStyledItemDelegate):
    def paint(self,painter,option,index):
        button=QStyleOptionButton();button.rect=option.rect.adjusted(3,3,-3,-3)
        button.text=str(index.data() or '')
        button.state=QStyle.State_Enabled if not index.model().busy else QStyle.State_None
        QApplication.style().drawControl(QStyle.CE_PushButton,button,painter)
    def editorEvent(self,event,model,option,index):
        if event.type()==QEvent.MouseButtonRelease and event.button()==Qt.LeftButton and not model.busy:
            model.retry_requested.emit(int(index.data(Qt.UserRole)));return True
        return False
