
from app.services.perf_diagnostics import measured
from PySide6.QtCore import Qt,QTimer,QEvent
from PySide6.QtWidgets import QTableView,QApplication,QDialog,QVBoxLayout,QHBoxLayout,QLabel,QTableWidget,QTableWidgetItem,QHeaderView,QPushButton,QMessageBox,QInputDialog,QAbstractItemView,QComboBox,QPlainTextEdit,QDialogButtonBox
from app.core import repository as repo
from app.core import work_dates
from app.core.database import connect
from app.services import task_recovery
from app.ui.read_snapshot import SnapshotReader
from app.ui.task_error_view import error_view, needs_prompt, upload_skipped
from app.ui.runtime_task_model import RuntimeTaskModel, ChannelDelegate, RetryDelegate

class RuntimeTasksDialog(QDialog):
    def __init__(self,owner):
        super().__init__(owner);self.owner=owner;self.setWindowTitle('运行任务与失败重试');self.resize(1080,620)
        layout=QVBoxLayout(self);note=QLabel(f'仅显示当前工作日期 {work_dates.active()} 的未完成任务。MAIN_ENGINE_TIMEOUT/提交未确认只会后台核对，不算失败；只有确认的生成/下载错误才保留错误原因并由你人工重试。');note.setWordWrap(True);layout.addWidget(note)
        batch_row=QHBoxLayout();self.batch_hint=QLabel('批量重试仅处理“失败 / 下载失败”；需修改提示词、图片上传失败已跳过、运行中、已提交、生成中任务会自动跳过（图片上传失败的请单独点该任务重试）。');self.batch_hint.setObjectName('muted');batch_row.addWidget(self.batch_hint,1)
        self.batch_retry_btn=QPushButton('批量重试',objectName='primaryBtn');self.batch_retry_btn.setToolTip('批量重置当前列表中确认失败、且不需要先修改提示词的任务');self.batch_retry_btn.clicked.connect(self.batch_retry);batch_row.addWidget(self.batch_retry_btn);layout.addLayout(batch_row)
        self.channel_choices={};self._tasks={};self._states={};self._queued_snapshot=None;self._view_day=None;self._retry_busy=False
        self.table=QTableView()
        self.model=RuntimeTaskModel(self.channel_choices,self)
        self.table.setModel(self.model)
        self.table.setItemDelegateForColumn(3,ChannelDelegate(self.table))
        self.table.setItemDelegateForColumn(7,RetryDelegate(self.table))
        self.model.retry_requested.connect(self._retry_current)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(48)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.table.setEditTriggers(QAbstractItemView.SelectedClicked|QAbstractItemView.DoubleClicked)
        self.table.setWordWrap(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(6,QHeaderView.Stretch)
        for col,width in ((0,76),(1,190),(2,95),(3,125),(4,110),(5,80),(7,174)):self.table.setColumnWidth(col,width)
        layout.addWidget(self.table)
        tools=QHBoxLayout()
        for text,callback in [('查看失败详情',self.show_details),('修改提示词并重试',self.edit_selected_prompt),('放弃选中任务',self.abandon_selected)]:
            button=QPushButton(text);button.clicked.connect(callback);tools.addWidget(button)
        tools.addStretch(1);layout.addLayout(tools)
        self.table.doubleClicked.connect(lambda index:self.show_details() if index.column()!=3 else None)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.reader=SnapshotReader(self,self._read_rows);self.reader.ready.connect(self._snapshot_ready)
        self.scroll_timer=QTimer(self);self.scroll_timer.setSingleShot(True);self.scroll_timer.setInterval(400);self.scroll_timer.timeout.connect(lambda: None)
        for bar in (self.table.verticalScrollBar(),self.table.horizontalScrollBar()):
            bar.valueChanged.connect(self._scrolling)
            bar.sliderReleased.connect(self._scrolling)
        self.table.viewport().installEventFilter(self)
        self.visual_timer=QTimer(self);self.visual_timer.setInterval(750);self.visual_timer.timeout.connect(self._flush_snapshot)
        self.timer=QTimer(self);self.timer.timeout.connect(self.refresh);self.timer.setInterval(2000)
        self.finished.connect(lambda _:self.timer.stop())
        self.refresh()

    @staticmethod
    @measured('task_list_refresh')
    def _read_rows(day):
        rows=[dict(r) for r in repo.list_flow_tasks(work_date=day) if r['flow_status']!='已完成' and (r['flow_status'] in ('失败','下载失败') or r['generation_command'] or r['flow_error'] or int(r['flow_retry_count'] or 0)>0)]
        ids={r['segment_id'] for r in rows}
        with connect() as con:states={r['segment_id']:dict(r) for r in con.execute('SELECT * FROM flow_recovery') if r['segment_id'] in ids}
        channels=[dict(c) for c in repo.list_channel_pool(enabled_only=True) if c['collection_url']]
        with connect() as con:
            errors={}
            for r in con.execute("SELECT segment_id,error FROM flow_dispatches WHERE coalesce(error,'')<>'' ORDER BY id"):
                if r['segment_id'] in ids:errors[r['segment_id']]=r['error']
            for row in rows:
                if not row.get('flow_error') and row['flow_status'] in ('失败','下载失败'):
                    row['flow_error']=errors.get(row['segment_id'],'')
        records=[]
        for row in rows:
            sid=row['segment_id'];label,count,reason,detail=error_view(row,states.get(sid,{}))
            records.append(dict(sid=sid,channel=str(row['flow_channel_key'] or ''),detail=detail,values=(str(sid),
                f"{row['recipient_name']} / {row['host_name']}",f"{row['video_seq']} / {row['seg_seq']}",'',label,str(count),reason,
                '修改提示词并重试' if needs_prompt(row) else '重置并重试')))
        retry_count=sum(row['flow_status'] in ('失败','下载失败') and not needs_prompt(row) and not upload_skipped(row) for row in rows)
        return rows,states,channels,records,retry_count

    def showEvent(self,event):
        super().showEvent(event);self.timer.start();self.visual_timer.start();self.refresh()

    def hideEvent(self,event):
        self.timer.stop();self.visual_timer.stop();self.scroll_timer.stop();super().hideEvent(event)

    def eventFilter(self,obj,event):
        if obj is self.table.viewport() and event.type()==QEvent.Wheel:self._scrolling()
        return super().eventFilter(obj,event)

    def _scrolling(self,*args):
        if not getattr(self,'_applying',False):self.scroll_timer.start()

    def refresh(self):
        day=work_dates.active()
        if self._view_day!=day:
            self.model.apply([],());self._tasks.clear();self._queued_snapshot=None;self._view_day=day
            self.batch_retry_btn.setEnabled(False)
        self.reader.request(day)

    def _snapshot_ready(self,day,result,error):
        if error or day!=work_dates.active():return
        self._queued_snapshot=(day,result)

    @measured('task_list_refresh')
    def _flush_snapshot(self):
        if not self._queued_snapshot or not self.isVisible() or self.scroll_timer.isActive():return
        if QApplication.activePopupWidget() is not None:
            self.scroll_timer.start();return
        if self.table.verticalScrollBar().isSliderDown() or self.table.horizontalScrollBar().isSliderDown():
            self.scroll_timer.start();return
        day,(rows,states,channels,records,count)=self._queued_snapshot;self._queued_snapshot=None
        if day!=work_dates.active():return
        self._applying=True
        try:
            self._tasks={r['segment_id']:r for r in rows};self._states=states
            self.model.apply(records,[str(c['channel_key']) for c in channels])
            self.batch_retry_btn.setEnabled(count>0 and not self._retry_busy)
            self.batch_retry_btn.setText(f'批量重试 ({count})' if count else '批量重试')
        finally:self._applying=False

    def selected_task(self):
        index=self.table.currentIndex()
        if not index.isValid():
            QMessageBox.information(self,'选择任务','请先点选一条任务。');return None
        if self._view_day!=work_dates.active():self.refresh();return None
        return self._tasks.get(int(index.data(Qt.UserRole)))

    def show_details(self):
        task=self.selected_task()
        if not task:return
        sid=task['segment_id'];label,count,reason,raw=error_view(task,self._states.get(sid,{}))
        with connect() as con:
            attempts=[dict(r) for r in con.execute('SELECT command_id,status,error FROM flow_dispatches WHERE segment_id=? ORDER BY id DESC LIMIT 8',(sid,))]
        text=f"任务：{sid} · {task['host_name']} · {task['video_seq']}/{task['seg_seq']}\n状态：{label}\n原因：{reason}\n\n完整错误：\n{raw}\n\n图片：{task['image_path']}\n\n当前提示词：\n{task['prompt']}\n\n最近派发：\n"
        text+='\n'.join(f"{a['command_id']} | {a['status']} | {a['error'] or '未返回错误说明'}" for a in attempts) or '无派发记录'
        dialog=QDialog(self);dialog.setWindowTitle('任务失败详情');dialog.resize(820,580)
        layout=QVBoxLayout(dialog);editor=QPlainTextEdit(text);editor.setReadOnly(True);layout.addWidget(editor)
        copy=QPushButton('复制详情');copy.clicked.connect(lambda:QApplication.clipboard().setText(text));layout.addWidget(copy)
        buttons=QDialogButtonBox(QDialogButtonBox.Close);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons);dialog.exec()

    def edit_selected_prompt(self):
        task=self.selected_task()
        if task:
            if task['flow_status'] not in ('失败','下载失败','待生成'):
                QMessageBox.information(self,'修改提示词','请等待当前运行结束；运行中的任务请使用“重置并重试”。');return
            self.retry(task,True)

    def abandon_selected(self):
        if self._retry_busy:return
        task=self.selected_task()
        if not task:return
        if QMessageBox.question(self,'放弃任务','放弃后此任务不再自动生成，保留原图片、提示词和错误记录。网页已经提交的生成无法撤销，旧结果不会重新加入任务。是否放弃？')!=QMessageBox.Yes:return
        day=self._view_day;sid=task['segment_id'];self._busy(True)
        def execute(_):
            if day!=work_dates.active():raise ValueError('工作日期已变化')
            return task_recovery.abandon_task(sid,self.owner.bridge,day)
        def finished(result,error):
            self._busy(False)
            if error:QMessageBox.warning(self,'未放弃',error)
            else:self.refresh();self.owner.auto_dispatch_tick()
        self.owner._production_lane.submit(('abandon',sid),execute,None,finished)

    def _retry_current(self,sid):
        if self._view_day!=work_dates.active():self.refresh();return
        task=self._tasks.get(sid)
        if task:self.retry(task,needs_prompt(task))

    def _busy(self,value):
        self._retry_busy=value;self.model.busy=value
        self.batch_retry_btn.setEnabled(not value)
        self.table.viewport().update()

    def batch_retry(self):
        if self._retry_busy:return
        self._busy(True)
        day=work_dates.active();choices=dict(self.channel_choices)
        def prepare(_):
            rows,states,channels,_,_=self._read_rows(day)
            available={str(c['channel_key']) for c in channels};candidates=[];skipped=0
            for task in rows:
                if task['flow_status'] not in ('失败','下载失败'):continue
                sid=task['segment_id']
                preferred=str(choices.get(sid) or task.get('flow_channel_key') or states.get(sid,{}).get('preferred_channel') or '')
                if needs_prompt(task) or upload_skipped(task) or preferred not in available:skipped+=1;continue
                candidates.append((sid,preferred,None))
            return candidates,skipped
        def ready(result,error):
            if error or day!=work_dates.active():
                self._busy(False)
                if error:QMessageBox.warning(self,'批量重试',error)
                return
            candidates,skipped=result
            if not candidates:
                self._busy(False);QMessageBox.information(self,'批量重试','没有可以批量重试的失败任务。');return
            if QMessageBox.question(self,'批量重试',f'将 {len(candidates)} 个失败任务加入重试队列？\n跳过 {skipped} 个需单独处理的任务。',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:
                self._busy(False);return
            self._submit_retries(day,candidates,True)
        self.owner._production_lane.submit(('retry-read',id(self)),prepare,None,ready)

    def _submit_retries(self,day,candidates,batch=False):
        bridge=self.owner.bridge
        def execute(_):
            if day!=work_dates.active():raise ValueError('工作日期已改变，请重新选择任务')
            valid={int(t['segment_id']):dict(t) for t in repo.list_flow_tasks(work_date=day)}
            ok=[];errors=[]
            for sid,channel,prompt in candidates:
                try:
                    task=valid.get(sid)
                    if not task:raise ValueError('任务不属于本次工作日期或已移除')
                    if batch and (task['flow_status'] not in ('失败','下载失败') or needs_prompt(task) or upload_skipped(task)):
                        raise ValueError('任务状态已变化，已跳过')
                    task_recovery.reset_task(sid,bridge,prompt,preferred_channel=channel)
                    ok.append(sid)
                except Exception as exc:errors.append(f'{sid}: {exc}')
            return ok,errors
        def finished(result,error):
            self._busy(False)
            if error:QMessageBox.warning(self,'重试',error);return
            ok,errors=result
            if ok:
                bridge.request_progress_scan();self.owner.dispatch_redo();self.owner.auto_dispatch_tick();self.refresh()
            message=f'已将 {len(ok)} 个任务加入重试队列。'
            if errors:message+='\n'+ '\n'.join(errors[:8])
            QMessageBox.information(self,'重试结果',message)
        self.owner._production_lane.submit(('retry-write',id(self)),execute,None,finished)

    def retry(self,task,blocked):
        if self._retry_busy:return
        day=work_dates.active()
        channel=self.channel_choices.get(task['segment_id']) or task['flow_channel_key']
        if not channel:
            QMessageBox.warning(self,'重试','请先配置并选择通道');return
        prompt=None
        if blocked:
            dialog=QDialog(self);dialog.setWindowTitle('修改提示词');dialog.resize(760,520)
            layout=QVBoxLayout(dialog);layout.addWidget(QLabel('修改后会重新检查通道图片并生成：'))
            editor=QPlainTextEdit(str(task['prompt'] or ''));editor.setLineWrapMode(QPlainTextEdit.WidgetWidth)
            from PySide6.QtGui import QTextOption
            editor.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
            editor.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff);layout.addWidget(editor)
            buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
            buttons.button(QDialogButtonBox.Ok).setText('保存并重试');buttons.button(QDialogButtonBox.Cancel).setText('取消')
            buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
            ok=dialog.exec()==QDialog.Accepted;prompt=editor.toPlainText()
            if not ok:return
            if not prompt.strip() or prompt.strip()==str(task['prompt']).strip():
                QMessageBox.warning(self,'重试','请先修改提示词再重试');return
        elif upload_skipped(task):
            if QMessageBox.question(self,'重新上传图片并重试','该任务的参考图片在网页插件中上传 3 次失败已被跳过。\n重试会重新上传这张图片并生成，确定继续？')!=QMessageBox.Yes:return
        elif task['flow_status'] in ('已提交','生成中','下载中'):
            if QMessageBox.question(self,'重置运行任务','网页上已提交的生成无法撤回。重置会放弃旧结果并再次生成，可能产生额外用量。确定该任务已卡住并重试？')!=QMessageBox.Yes:return
        self._busy(True)
        self._submit_retries(day,[(task['segment_id'],channel,prompt)])
