from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QPushButton,QTableWidget,QTableWidgetItem,QHeaderView,QAbstractItemView,QMessageBox
from app.services import editing_history,davinci_workflow

class EditingHistoryDialog(QDialog):
    def __init__(self,parent):
        super().__init__(parent);self.setWindowTitle('剪辑记录 / 重新剪辑');self.resize(1100,620)
        layout=QVBoxLayout(self);layout.addWidget(QLabel('显示所有日期的剪辑记录。选中完整视频后，可重新发送到达芬奇；原成品保留。'))
        bar=QHBoxLayout();self.search=QLineEdit();self.search.setPlaceholderText('日期 / 接收人 / 主播');self.search.textChanged.connect(self.render);bar.addWidget(self.search)
        refresh=QPushButton('刷新');refresh.clicked.connect(self.reload);bar.addWidget(refresh)
        self.submit=QPushButton('重新提交选中视频',objectName='primaryBtn');self.submit.clicked.connect(self.resubmit);bar.addWidget(self.submit);layout.addLayout(bar)
        self.table=QTableWidget(0,7);self.table.setHorizontalHeaderLabels(['日期','接收人','主播','完整视频','剪辑状态','提交时间','成品文件'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows);self.table.setSelectionMode(QAbstractItemView.ExtendedSelection);self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents);self.table.horizontalHeader().setSectionResizeMode(6,QHeaderView.Stretch);layout.addWidget(self.table);self.reload()
    def reload(self):self.records=editing_history.rows();self.render()
    def render(self):
        query=self.search.text().strip().lower();rows=[r for r in self.records if query in str(r).lower()]
        self.table.setRowCount(len(rows))
        for i,r in enumerate(rows):
            for j,value in enumerate([r['work_date'],r['recipient_name'],r['host_name'],r['video_seq'],r['status'],r['created_at'],r['output_path']]):
                cell=QTableWidgetItem(str(value or ''));cell.setData(Qt.UserRole,r['video_id']);self.table.setItem(i,j,cell)
    def resubmit(self):
        ids=sorted({int(self.table.item(x.row(),0).data(Qt.UserRole)) for x in self.table.selectionModel().selectedRows()})
        if not ids:QMessageBox.information(self,'重新剪辑','请先选中完整视频');return
        self.submit.setEnabled(False)
        try:
            result=davinci_workflow.submit_autoedit_jobs(ids,reedit=True)
            if not result.get('ok'):raise ValueError(result.get('reason','提交失败'))
            count=result.get('submitted',0)
            QMessageBox.information(self,'重新剪辑',f'已发送 {count} 个完整视频到达芬奇。'+('其余视频正在剪辑/导出，或当前素材尚未全部质检通过，未重复提交。' if count<len(ids) else ''))
            self.reload();self.parent().reload()
        except Exception as exc:QMessageBox.warning(self,'重新剪辑',str(exc))
        finally:self.submit.setEnabled(True)
