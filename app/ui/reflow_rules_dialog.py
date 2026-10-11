from PySide6.QtCore import Qt,QThread,Signal,QTimer
from PySide6.QtWidgets import QDialog,QWidget,QVBoxLayout,QFormLayout,QSpinBox,QLineEdit,QCheckBox,QPlainTextEdit,QLabel,QPushButton,QHBoxLayout
from app.services import reflow_rules
from app.core import work_dates


class ReflowWorker(QThread):
    progress=Signal(int,int)
    def __init__(self,config,day,parent):
        super().__init__(parent);self.config=config;self.day=day;self.result=None;self.error=''
    def run(self):
        try:self.result=reflow_rules.apply(self.config,self.day,self.progress.emit)
        except Exception as exc:self.error=str(exc)


class ReflowRulesDialog(QDialog):
    applied=Signal(object)
    def __init__(self,owner):
        super().__init__(owner);self.worker=None;self.owner=owner
        self.setWindowTitle('自动断行规则');self.setWindowModality(Qt.WindowModal);self.resize(620,590)
        self.setAttribute(Qt.WA_DeleteOnClose)
        root=QVBoxLayout(self)
        hint=QLabel('保存后自动处理当前工作日期的未提交斯瓦希里语文案。新版以约 7.5 秒自然朗读为第一优先级；14～22 个词仅作动态参考。明显过长时只允许从原文自然标点拆分；没有自然标点禁止硬拆；短段和可安全合并的相邻段会再次合并。已提交或已有下游记录的视频保留原结构。');hint.setWordWrap(True);root.addWidget(hint)
        self.form_widget=QWidget(self);form=QFormLayout(self.form_widget)
        self.width=QSpinBox();self.width.setRange(1,100000);form.addRow('辅助参考字符数（非硬限制）',self.width)
        self.sentence=QLineEdit();form.addRow('句末断句标点',self.sentence)
        self.clause=QLineEdit();form.addRow('超长句优先分句标点',self.clause)
        self.tail=QSpinBox();self.tail.setRange(1,10);form.addRow('尽量保留的句尾最少词数',self.tail)
        self.newlines=QCheckBox('原文换行不锁定（过短行自动合并）');self.newlines.setChecked(False);self.newlines.setEnabled(False);form.addRow(self.newlines)
        self.swahili=QCheckBox('优先使用现有斯瓦希里语分句边界');form.addRow(self.swahili)
        root.addWidget(self.form_widget)
        rule_note=QLabel('固定规则：约 7.5 秒自然斯瓦希里语朗读优先；14～22 词仅参考；拆分优先级为句号/问号/感叹号 ＞ 分号/冒号 ＞ 逗号；无自然标点不硬拆；短段及相邻可合并段优先合并；保留原文正常朗读标点，不再统一改成句号。');rule_note.setWordWrap(True);root.addWidget(rule_note)
        self.sample=QPlainTextEdit();self.sample.setPlaceholderText('在这里输入外文，预览新规则的断行结果');self.sample.setMaximumHeight(90);root.addWidget(self.sample)
        self.preview=QPlainTextEdit();self.preview.setReadOnly(True);self.preview.setMaximumBlockCount(2000);root.addWidget(self.preview)
        self.status=QLabel('');self.status.setWordWrap(True);root.addWidget(self.status)
        row=QHBoxLayout();defaults=QPushButton('恢复默认');defaults.clicked.connect(lambda:self.set_values(reflow_rules.DEFAULTS));row.addWidget(defaults)
        self.defaults=defaults
        self.preview_timer=QTimer(self);self.preview_timer.setSingleShot(True);self.preview_timer.setInterval(200);self.preview_timer.timeout.connect(self.refresh_preview)
        self.save=QPushButton('保存规则并应用未提交文案');self.save.clicked.connect(self.apply_rules);row.addWidget(self.save)
        self.close_btn=QPushButton('关闭');self.close_btn.clicked.connect(self.reject);row.addWidget(self.close_btn);root.addLayout(row)
        for control in (self.width,self.tail):control.valueChanged.connect(self.schedule_preview)
        for control in (self.sentence,self.clause):control.textChanged.connect(self.schedule_preview)
        for control in (self.newlines,self.swahili):control.toggled.connect(self.schedule_preview)
        self.sample.textChanged.connect(self.schedule_preview)
        self.set_values(reflow_rules.load())
    def values(self):
        return dict(max_chars=self.width.value(),sentence_marks=self.sentence.text(),clause_marks=self.clause.text(),min_tail_words=self.tail.value(),preserve_newlines=self.newlines.isChecked(),swahili_boundaries=self.swahili.isChecked())
    def set_values(self,value):
        self.width.setValue(value['max_chars']);self.sentence.setText(value['sentence_marks']);self.clause.setText(value['clause_marks']);self.tail.setValue(value['min_tail_words']);self.newlines.setChecked(False);self.swahili.setChecked(value['swahili_boundaries']);self.refresh_preview()
    def schedule_preview(self,*_):
        self.preview_timer.start()
    def refresh_preview(self,*_):
        try:
            config=reflow_rules.validate(self.values())
            text=self.sample.toPlainText()
            if len(text)>20000:raise ValueError('预览最多 20000 字符；批量应用不受预览长度限制')
            prepared=reflow_rules.prepare_with_rules(text,config)
            self.preview.setPlainText('\n'.join(prepared.segments));self.status.setText('预览不会保存或调用 API')
        except ValueError as exc:self.status.setText(str(exc))
    def apply_rules(self):
        if self.worker is not None:return
        gpt=getattr(getattr(self.owner,'prompt_center',None),'worker',None)
        if gpt and gpt.isRunning():self.status.setText('当前 GPT 任务尚未结束，请结束后应用规则。');return
        try:config=reflow_rules.validate(self.values())
        except ValueError as exc:self.status.setText(str(exc));return
        day=work_dates.active()
        timer=getattr(self.owner,'_wrap_reflow_timer',None)
        if timer:timer.stop()
        self.preview_timer.stop();self.sample.setEnabled(False);self.defaults.setEnabled(False)
        self.form_widget.setEnabled(False);self.save.setEnabled(False);self.close_btn.setEnabled(False)
        self.status.setText('正在应用 '+day+' 的未提交文案…')
        self.worker=ReflowWorker(config,day,self)
        self.worker.progress.connect(lambda done,total:self.status.setText(f'正在应用 {done}/{total}…'))
        self.worker.finished.connect(self.finished_work);self.worker.start()
    def finished_work(self):
        worker=self.worker;self.worker=None
        self.sample.setEnabled(True);self.defaults.setEnabled(True)
        self.form_widget.setEnabled(True);self.save.setEnabled(True);self.close_btn.setEnabled(True)
        if worker.error:self.status.setText('应用未完成：'+worker.error+'；已完成的视频已保存，再次应用会跳过相同结果。')
        else:
            self.owner.settings.setValue('default_wrap',str(worker.config['max_chars']))
            result=worker.result
            self.status.setText(f"已更新 {result['changed']} 条；原样保留 {result['unchanged']} 条；保护跳过 {result['skipped']} 条；重置未提交提示词 {result['reset_prompts']} 条。")
            self.status.setToolTip('\n'.join(result['details']));self.applied.emit(result)
        worker.result=None;worker.deleteLater()
    def reject(self):
        if self.worker is None:super().reject()
    def closeEvent(self,event):
        if self.worker is not None:event.ignore()
        else:super().closeEvent(event)
