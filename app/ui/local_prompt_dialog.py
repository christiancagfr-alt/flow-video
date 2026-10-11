from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QLineEdit,QPlainTextEdit,
    QPushButton,QCheckBox,QTableWidget,QTableWidgetItem,QHeaderView,QDialogButtonBox,QMessageBox)
from app.services import local_prompt_fill as fill


class LocalPromptDialog(QDialog):
    def __init__(self,tasks,day,template=False,parent=None,scope='当前列表'):
        super().__init__(parent)
        self.tasks=[dict(t) for t in tasks];self.day=day;self.template=template;self.mapping={}
        self.setWindowTitle('通用模板套用' if template else '手动批量填写提示词');self.resize(1000,740)
        root=QVBoxLayout(self)
        hint=QLabel(f'范围：{scope}，共 {len(tasks)} 个任务，按列表从上到下对应。保存后进入“待检查”，不会自动提交 Flow。');hint.setWordWrap(True);root.addWidget(hint)
        self.overwrite=QCheckBox('覆盖范围内已有的提示词（已提交任务不可覆盖）');root.addWidget(self.overwrite)
        bar=QHBoxLayout();self.choice=QComboBox();bar.addWidget(self.choice,1)
        if template:
            for t in fill.templates():self.choice.addItem(t['name'],t['body'])
            self.name=QLineEdit();self.name.setPlaceholderText('自定义模板名称');bar.addWidget(self.name)
            save=QPushButton('保存为我的模板');save.clicked.connect(self.save_template);bar.addWidget(save)
        else:
            self.choice.addItems(['逐行填写 / 表格单列粘贴','用单独一行 --- 分隔多行提示词'])
        root.addLayout(bar)
        help_text='支持 {文案}、{主播}、{任务ID}、{类型}、{眼睛要求}；{文案} 必填。按红黑字分类自动代入睁闭眼要求。' if template else '每条提示词对应一个任务。支持复制表格中含换行的单列；也可用 --- 分隔多行内容。数量必须与下方目标一致。'
        help_label=QLabel(help_text);help_label.setWordWrap(True);root.addWidget(help_label)
        self.editor=QPlainTextEdit();self.editor.setPlaceholderText('在此填写提示词…');root.addWidget(self.editor,2)
        self.summary=QLabel();self.summary.setWordWrap(True);root.addWidget(self.summary)
        self.preview=QTableWidget(0,4);self.preview.setHorizontalHeaderLabels(['任务ID','类型','文案','将保存的最终提示词'])
        self.preview.setEditTriggers(QTableWidget.NoEditTriggers);self.preview.horizontalHeader().setSectionResizeMode(2,QHeaderView.Stretch);self.preview.horizontalHeader().setSectionResizeMode(3,QHeaderView.Stretch)
        self.preview.setColumnWidth(0,80);self.preview.setColumnWidth(1,85);self.preview.verticalHeader().setDefaultSectionSize(60);root.addWidget(self.preview,3)
        buttons=QDialogButtonBox(QDialogButtonBox.Cancel|QDialogButtonBox.Save);self.save_button=buttons.button(QDialogButtonBox.Save);self.save_button.setText('保存到任务（不调用 API）');buttons.accepted.connect(self.save);buttons.rejected.connect(self.reject);root.addWidget(buttons)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(180);self.timer.timeout.connect(self.refresh_preview)
        self.editor.textChanged.connect(lambda:self.timer.start());self.overwrite.toggled.connect(self.refresh_preview)
        self.choice.currentIndexChanged.connect(self.choose)
        self.choose()

    def choose(self,*_):
        if self.template:self.editor.setPlainText(self.choice.currentData() or '')
        self.refresh_preview()

    def save_template(self):
        try:fill.save_template(self.name.text(),self.editor.toPlainText())
        except ValueError as exc:QMessageBox.information(self,'模板',str(exc));return
        name=self.name.text().strip();body=self.editor.toPlainText()
        self.choice.blockSignals(True)
        self.choice.clear()
        for t in fill.templates():self.choice.addItem(t['name'],t['body'])
        self.choice.setCurrentText(name);self.choice.blockSignals(False)
        self.summary.setText('模板已保存，可在下次打开时选择。');self.refresh_preview()

    def refresh_preview(self,*_):
        targets=[t for t in self.tasks if self.overwrite.isChecked() or not str(t['prompt'] or '').strip()]
        self.mapping={};self.preview.setRowCount(len(targets));error=''
        try:
            if not targets:raise ValueError('当前范围没有待填写的任务。可勾选覆盖已有提示词，或返回选择其他任务。')
            if self.template:
                prompts=[fill.render(self.editor.toPlainText(),t) for t in targets]
            else:
                prompts=fill.parse_manual(self.editor.toPlainText(),self.choice.currentIndex()==1)
                if len(prompts)!=len(targets):raise ValueError(f'已填写 {len(prompts)} 条，目标 {len(targets)} 条；请补齐或调整任务范围。')
            self.mapping={t['segment_id']:p for t,p in zip(targets,prompts)}
        except ValueError as exc:error=str(exc)
        for i,t in enumerate(targets):
            values=[f"{t['video_seq']:02d}-{t['seg_seq']:02d}",'闭眼' if t['performance_mode']=='PRAYING' else '睁眼',t['foreign_text'],self.mapping.get(t['segment_id'],'')]
            for col,value in enumerate(values):
                item=QTableWidgetItem(value);item.setToolTip(value);self.preview.setItem(i,col,item)
        self.preview.resizeRowsToContents()
        self.summary.setText(error or f'将保存 {len(self.mapping)} 条；跳过已有提示词 {len(self.tasks)-len(targets)} 条。请核对下方对应关系。')
        self.save_button.setEnabled(bool(self.mapping) and not error)

    def save(self):
        self.timer.stop();self.refresh_preview()
        if not self.mapping:return
        from app.core import work_dates
        if work_dates.active()!=self.day:
            QMessageBox.warning(self,'工作日期已变化','请关闭窗口并重新选择任务。');return
        try:
            self.saved_count=fill.save(self.mapping,{t['segment_id']:t for t in self.tasks},self.day,
                                       '模板套用' if self.template else '手动批量',self.choice.currentText() if self.template else '')
        except ValueError as exc:QMessageBox.warning(self,'未保存',str(exc));return
        self.accept()
