from pathlib import Path
import sys,codecs,time,json
from PySide6.QtCore import QProcess,QTimer
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QComboBox,QPlainTextEdit,QScrollArea,QProgressBar,QTabWidget,QFormLayout,QToolButton,QLineEdit,QMessageBox,QFileDialog
from app.services.app_paths import data_dir
from app.services.reels.recognition_engine import LOCAL_PROVIDER


class PackagingComponentsPage(QWidget):
    def __init__(self,packaging,parent=None):
        super().__init__(parent);self.packaging=packaging;self.process=None
        self.setObjectName("pageRoot")
        self.setStyleSheet('QPushButton{min-width:0px;min-height:26px;padding:4px 10px;} QLineEdit,QComboBox{min-height:26px;padding:3px 6px;} QLabel#pageTitle{font-size:24px;}')
        outer=QVBoxLayout(self);outer.setContentsMargins(16,12,16,12);outer.setSpacing(12)
        header=QHBoxLayout();header.addWidget(QLabel('组件管理',objectName='pageTitle'));header.addStretch()
        check=QPushButton('检查全部');check.clicked.connect(lambda:self.run('check'));header.addWidget(check);outer.addLayout(header)
        self.status=QLabel('选择下方分类，安装组件或配置密钥。');self.status.setWordWrap(True)
        status_row=QHBoxLayout();status_row.addWidget(self.status,1)
        self.progress=QProgressBar();self.progress.setRange(0,1);self.progress.setValue(0);self.progress.setMaximumWidth(200);self.progress.setMaximumHeight(10);self.progress.setTextVisible(False);status_row.addWidget(self.progress)
        self.cancel=QPushButton('停止');self.cancel.setEnabled(False);self.cancel.clicked.connect(self.stop);status_row.addWidget(self.cancel);outer.addLayout(status_row)
        self.timer=QTimer(self);self.timer.setInterval(1000);self.timer.timeout.connect(self.tick)
        self.action_buttons=[check,packaging.engine_check_btn,packaging.engine_install_btn]
        packaging.asr_install_btn.clicked.disconnect();packaging.asr_install_btn.clicked.connect(lambda:self.run('asr'))
        packaging.engine_check_btn.clicked.disconnect();packaging.engine_check_btn.clicked.connect(lambda:self.run('check'))
        packaging.engine_install_btn.clicked.connect(lambda:self.run('remotion'))
        tabs=QTabWidget();outer.addWidget(tabs,1)
        def section(title):
            page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(18,18,18,18);layout.setSpacing(12)
            scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(page);tabs.addTab(scroll,title)
            return layout
        basic=section('渲染 / FFmpeg')
        hint=QLabel('常规 Reels 字幕使用 FFmpeg 渲染，无需启动浏览器。显卡编码可用时自动启用；也可在下方选择 CPU。');hint.setWordWrap(True);basic.addWidget(hint)
        form=QFormLayout();form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow);basic.addLayout(form)
        form.addRow('默认渲染方式',packaging.render_mode);packaging.render_mode.show()
        row=QHBoxLayout();row.addWidget(packaging.asr_ffmpeg,1);browse=QPushButton('选择文件');browse.clicked.connect(packaging._pick_ffmpeg);row.addWidget(browse);form.addRow('FFmpeg 路径',row)
        row=QHBoxLayout();install=QPushButton('安装 / 修复 FFmpeg');install.clicked.connect(lambda:self.run('ffmpeg'));row.addWidget(install);self.action_buttons.append(install);row.addStretch();basic.addLayout(row);basic.addStretch()
        local=section('字幕识别')
        service_form=QFormLayout();service_form.addRow('默认识别服务',packaging.asr_provider);service_form.addRow('识别模型',packaging.asr_model);local.addLayout(service_form);packaging.asr_provider.show();packaging.asr_model.show()
        label=QLabel('先安装识别组件，再下载模型。base 体积较小；较大的模型需要更多内存和下载时间。');label.setWordWrap(True);local.addWidget(label)
        row=QHBoxLayout();row.addWidget(packaging.asr_install_btn);row.addStretch();local.addLayout(row)
        row=QHBoxLayout();self.model=QComboBox();self.model.addItems(['base','small','medium','large-v3']);self.model.setMaximumWidth(250);row.addWidget(self.model)
        self.download=QPushButton('下载 / 重试模型');self.download.clicked.connect(lambda:self.run('model'));row.addWidget(self.download);row.addStretch();local.addLayout(row);self.action_buttons.append(self.download)
        # Automatic editing reads these paths. Fill them when a real whisper.cpp install is already present.
        from app.core import repository as repo
        from app.services.whisper_cpp import discover
        saved_cli=repo.get_setting('whisper_cli_path','');saved_model=repo.get_setting('whisper_model_path','')
        found=discover(saved_cli,saved_model)
        if found['cli']:repo.set_setting('whisper_cli_path',found['cli'])
        if found['model']:repo.set_setting('whisper_model_path',found['model'])
        paths=QFormLayout();paths.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow);local.addLayout(paths)
        def path_row(title,key,value,browse_filter):
            field=QLineEdit(value);field.setPlaceholderText('尚未找到，请点击下方“检测 / 安装”')
            field.editingFinished.connect(lambda field=field,key=key:repo.set_setting(key,field.text().strip()))
            line=QHBoxLayout();line.addWidget(field,1)
            browse=QPushButton('选择文件')
            def pick(field=field,key=key,browse_filter=browse_filter,title=title):
                chosen,_=QFileDialog.getOpenFileName(self,'选择'+title,'',browse_filter)
                if chosen:field.setText(chosen);repo.set_setting(key,chosen)
            browse.clicked.connect(pick);line.addWidget(browse);paths.addRow(title,line)
            return field
        self.whisper_cli=path_row('whisper.cpp 命令','whisper_cli_path',found['cli'] or saved_cli,'可执行文件 (whisper-cli.exe whisper-cli);;所有文件 (*)')
        self.whisper_model=path_row('whisper.cpp 模型','whisper_model_path',found['model'] or saved_model,'模型 (*.bin);;所有文件 (*)')
        row=QHBoxLayout();whisper_btn=QPushButton('检测 / 安装 whisper.cpp');whisper_btn.clicked.connect(lambda:self.run('whisper'))
        row.addWidget(whisper_btn);row.addStretch();local.addLayout(row);self.action_buttons.append(whisper_btn)
        if not (found['cli'] and found['model']):
            self.status.setText('未找到可用的 whisper.cpp。请在“字幕识别”里点击“检测 / 安装 whisper.cpp”。')
        local.addStretch()
        templates=section('提示词模板')
        for label,key in [('睁眼基础模板','talking_base_prompt'),('闭眼基础模板','praying_base_prompt')]:
            templates.addWidget(QLabel(label));field=QPlainTextEdit(repo.get_setting(key,''));field.setMaximumHeight(120);templates.addWidget(field)
            field.textChanged.connect(lambda field=field,key=key:repo.set_setting(key,field.toPlainText().strip()))
        templates.addStretch()
        keys=section('API 密钥')
        from app.ui.credential_pool_dialog import edit_pool
        gpt=QPushButton('GPT 提示词 · 批量密钥 / 轮询');gpt.clicked.connect(lambda:edit_pool(self,'com.flowstudio.openai','FlowStudio'))
        row=QHBoxLayout();row.addWidget(gpt);row.addStretch();keys.addLayout(row)
        keys.addWidget(QLabel('云端字幕识别服务'))
        provider=QComboBox();provider.addItems(['Groq','ElevenLabs','Gladia','Gemini']);provider.setMaximumWidth(300)
        if packaging.asr_provider.currentText()!=LOCAL_PROVIDER:provider.setCurrentText(packaging.asr_provider.currentText())
        keys.addWidget(provider)
        entry=QLineEdit();entry.setEchoMode(QLineEdit.Password);entry.setPlaceholderText('填写当前服务的密钥，或点击批量 / 轮询')
        provider.currentTextChanged.connect(lambda _:entry.clear())
        def save_key():
            from app.services.credential_pool import save
            try:
                save('com.flowstudio.asr',provider.currentText(),entry.text());entry.clear();packaging.component_feedback.setText(provider.currentText()+' 密钥已保存到系统凭据库。')
            except Exception:QMessageBox.warning(self,'保存密钥','请填写有效密钥，并确认系统凭据库已解锁。')
        row=QHBoxLayout();row.addWidget(entry,1)
        save=QPushButton('保存单个');save.clicked.connect(save_key);row.addWidget(save)
        bulk=QPushButton('批量 / 轮询');bulk.clicked.connect(lambda:edit_pool(self,'com.flowstudio.asr',provider.currentText()));row.addWidget(bulk);keys.addLayout(row)
        keys.addWidget(packaging.component_feedback);keys.addStretch()
        engine=section('兼容引擎')
        note=QLabel('Remotion 用于原有 CSS 字幕、连续滚动等兼容效果。使用常规 Reels 样式时不需要此引擎。');note.setWordWrap(True);engine.addWidget(note)
        engine.addWidget(packaging.component_engine);engine.addStretch()
        packaging.component_asr.setParent(self);packaging.component_asr.hide()
        self.details=QToolButton();self.details.setText('查看操作详情');self.details.setCheckable(True);outer.addWidget(self.details)
        self.log=QPlainTextEdit();self.log.setReadOnly(True);self.log.setMaximumBlockCount(500);self.log.setMaximumHeight(140);self.log.hide();outer.addWidget(self.log)
        self.details.toggled.connect(self.log.setVisible)

    def run(self,action):
        p=self.packaging
        if self.process or p._asr_process or p._asr_install_process or p._render_process or p._preview_process:
            self.status.setText('请等待当前识别、安装或渲染任务结束。');return
        executable=Path(sys.executable)
        if executable.name.lower()=='pythonw.exe':executable=executable.with_name('python.exe')
        self.cancelled=False;self.started=time.monotonic();self.action=action
        proc=QProcess(self);self.process=proc;p._asr_install_process=proc
        self.decoder=codecs.getincrementaldecoder('utf-8')('replace');self.log.clear()
        proc.setProgram(str(executable));proc.setArguments(['-X','utf8',str(Path(__file__).resolve().parents[2]/'scripts/packaging_components.py'),action,self.model.currentText(),p.remotion_dir.text().strip()])
        proc.setProcessChannelMode(QProcess.MergedChannels)
        def read():
            text=self.decoder.decode(bytes(proc.readAllStandardOutput()))
            if text:self.log.insertPlainText(text);self.log.ensureCursorVisible()
        def done(code,*args):
            if self.process is not proc:return
            read();self.process=None;p._asr_install_process=None
            if code:self.details.setChecked(True)
            self.timer.stop();self.cancel.setEnabled(False);self.progress.setRange(0,1);self.progress.setValue(int(code==0))
            for button in self.action_buttons:button.setEnabled(True)
            p.asr_install_btn.setEnabled(True)
            self.status.setText('已停止；已下载的缓存保留，可重试。' if self.cancelled else ('检查结束，请查看上方各组件结果。' if action=='check' and code==0 else ('操作完成' if code==0 else '未完成，请查看上方原因后重试。')))
            if code==0 and action=='remotion':
                folder=str(data_dir()/'packaging/remotion');p.remotion_dir.setText(folder);p._settings.setValue('packaging/remotion_project_dir',folder);p._engine_ok=True;p._update_engine_badge();p.remotion_status.setText('✓ 渲染引擎和浏览器安装完成')
            if code==0 and action=='check':
                for line in self.log.toPlainText().splitlines():
                    if line.startswith('FLOW_ENGINE='):
                        try:
                            result=json.loads(line.split('=',1)[1]);p._engine_ok=result['ok'];p._update_engine_badge();p.remotion_status.setText(('✓ ' if result['ok'] else '⚠ ')+result['message'])
                            if result['ok']:
                                p.remotion_dir.setText(result['path']);p._settings.setValue('packaging/remotion_project_dir',result['path'])
                        except (ValueError,KeyError):pass
            if code==0 and action=='model' and p.asr_provider.currentText()==LOCAL_PROVIDER:p.asr_model.setCurrentText(self.model.currentText())
            if action=='whisper':self._apply_whisper_output(self.log.toPlainText())
            proc.deleteLater()
        proc.readyReadStandardOutput.connect(read);proc.finished.connect(done)
        def failed(err):
            if err==QProcess.FailedToStart:
                self.log.appendPlainText('进程启动失败：'+proc.errorString());done(1)
        proc.errorOccurred.connect(failed)
        for button in self.action_buttons:button.setEnabled(False)
        p.asr_install_btn.setEnabled(False)
        self.status.setText('正在检查…' if action=='check' else '正在下载 / 安装，请稍候…')
        self.log.appendPlainText('已启动：'+action+'。网络下载期间可停止后重试。')
        self.cancel.setEnabled(True);self.progress.setRange(0,0);self.timer.start()
        proc.start()

    def _apply_whisper_output(self,text):
        for line in text.splitlines():
            if line.startswith('WHISPER_CLI='):self.whisper_cli.setText(line.split('=',1)[1].strip())
            elif line.startswith('WHISPER_MODEL='):self.whisper_model.setText(line.split('=',1)[1].strip())
        cli=self.whisper_cli.text().strip();model=self.whisper_model.text().strip()
        if cli and model:self.status.setText('whisper.cpp 路径已填入，自动剪辑可以使用。')
        elif cli:self.status.setText('whisper.cpp 命令已填入。模型还没有下载成功，可重试，或点“选择文件”指定 ggml-base.bin。')

    def tick(self):
        elapsed=int(time.monotonic()-self.started)
        self.status.setText(f'正在执行 {self.action} · 已用时 {elapsed} 秒；详情见下方。')
        if self.action=='check' and elapsed>90:
            self.log.appendPlainText('检测超时，已停止。请检查 Node / 引擎目录。');self.stop()

    def stop(self):
        proc=self.process
        if proc is None:return
        self.cancelled=True
        try:
            import psutil
            for child in psutil.Process(int(proc.processId())).children(recursive=True):
                try:child.kill()
                except psutil.Error:pass
        except (psutil.Error,ValueError):pass
        proc.kill()
