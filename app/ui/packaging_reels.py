"""Reels integration for the existing packaging workspace."""
from __future__ import annotations
import copy
import codecs
import json
import os
import sys
from datetime import date
from pathlib import Path
from PySide6.QtCore import Qt, QProcess, QTimer
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QLineEdit,
    QComboBox,QSpinBox,QPushButton,QCheckBox,QPlainTextEdit,QFileDialog,QMessageBox,
    QTableWidget,QTableWidgetItem,QHeaderView,QDialog,QDialogButtonBox,QInputDialog,
    QFontComboBox,QColorDialog,QSizePolicy)
from PySide6.QtGui import QFont,QColor,QPixmap
from app.services.packaging_media import (captions_to_srt,captions_from_srt,output_size,
    output_basename,available_output,find_ffmpeg,validate_captions,probe_media)
from app.services.reels.recognition_engine import LOCAL_PROVIDER, DEFAULT_MODELS
from app.ui.packaging_proofread import BatchScriptProofreadDialog


class PackagingReelsMixin:
    def _build_recognition_tab(self):
        w,b = self._tab()
        self._asr_process = None
        self._asr_install_process = None
        self._preview_process = None
        self._asr_queue = []
        self._asr_path = ''
        self._reels_style = {}
        form = QFormLayout()
        self.asr_provider = QComboBox(); self.asr_provider.addItems([LOCAL_PROVIDER,'Groq','ElevenLabs','Gladia','Gemini'])
        self.asr_model = QComboBox(); self.asr_model.setEditable(True)
        self.asr_provider.currentTextChanged.connect(self._asr_provider_changed)
        self.asr_language = QComboBox(); self.asr_language.setEditable(True)
        for label,code in [('自动检测','auto'),('英语','en'),('葡萄牙语','pt'),('西班牙语','es'),('斯瓦希里语','sw'),('中文','zh'),('希腊语','el'),('阿拉伯语','ar'),('法语','fr'),('马达加斯加语','mg')]:
            self.asr_language.addItem(label,code)
        self.asr_ffmpeg = QLineEdit(self._settings.value('packaging/ffmpeg','',type=str))
        self.asr_ffmpeg.setPlaceholderText('自动检测 FFmpeg；也可选择文件')
        ff = QHBoxLayout(); ff.addWidget(self.asr_ffmpeg)
        choose = QPushButton('选择'); choose.clicked.connect(self._pick_ffmpeg); ff.addWidget(choose)
        self.asr_max_words = QSpinBox(); self.asr_max_words.setRange(1,30); self.asr_max_words.setValue(7)
        form.addRow('识别服务',self.asr_provider); form.addRow('模型',self.asr_model)
        form.addRow('语言 / 语言代码',self.asr_language); form.addRow('每条最多词数',self.asr_max_words)
        b.addLayout(form)
        self.component_asr = QWidget()
        component_layout = QVBoxLayout(self.component_asr)
        component_layout.addWidget(QLabel('FFmpeg 路径（可自动安装，也可选择已有文件）'))
        component_layout.addLayout(ff)
        component_layout.addWidget(QLabel("API 密钥对应识别页当前选择的服务"))
        self.asr_key = QLineEdit(); self.asr_key.setEchoMode(QLineEdit.Password)
        self.asr_key.setPlaceholderText('API 密钥（不会写入工程文件）')
        keys = QHBoxLayout(); keys.addWidget(self.asr_key)
        save = QPushButton('安全保存密钥'); save.clicked.connect(self._save_asr_key); keys.addWidget(save); component_layout.addLayout(keys)
        from app.ui.credential_pool_dialog import edit_pool
        bulk = QPushButton('批量密钥 / 轮询设置')
        bulk.clicked.connect(lambda: edit_pool(self, 'com.flowstudio.asr', self.asr_provider.currentText()) if self.asr_provider.currentText()!=LOCAL_PROVIDER else None)
        component_layout.addWidget(bulk)
        self.component_feedback=QLabel('密钥仅保存到系统凭据库。');self.component_feedback.setWordWrap(True);component_layout.addWidget(self.component_feedback)
        row = QHBoxLayout()
        self.asr_current_btn = QPushButton('识别当前'); self.asr_current_btn.clicked.connect(lambda:self._start_asr([self._current_path]))
        self.asr_all_btn = QPushButton('批量识别全部'); self.asr_all_btn.clicked.connect(lambda:self._start_asr(self._project.get('order',[])))
        self.asr_stop_btn = QPushButton('停止识别'); self.asr_stop_btn.setEnabled(False); self.asr_stop_btn.clicked.connect(self._stop_asr)
        for x in (self.asr_current_btn,self.asr_all_btn,self.asr_stop_btn): row.addWidget(x)
        b.addLayout(row)
        self.asr_install_btn=QPushButton('安装本地识别组件（首次使用）')
        self.asr_install_btn.clicked.connect(self._install_asr_components);component_layout.addWidget(self.asr_install_btn)
        proof = QHBoxLayout()
        for text,fn in [('校对当前',lambda:self._proofread(False)),('批量校对',lambda:self._proofread(True)),('导出 SRT',self._export_srt)]:
            btn=QPushButton(text); btn.clicked.connect(fn); proof.addWidget(btn)
        b.addLayout(proof)
        self.asr_status=QLabel('就绪'); self.asr_status.setWordWrap(True); b.addWidget(self.asr_status)
        self.asr_results=QPlainTextEdit(); self.asr_results.setReadOnly(True); self.asr_results.setMaximumHeight(160); b.addWidget(self.asr_results)
        b.addStretch(1)
        self._asr_provider_changed(self.asr_provider.currentText())
        self.asr_provider.setCurrentText(self._settings.value('packaging/asr_provider',LOCAL_PROVIDER,type=str))
        language=self._settings.value('packaging/asr_language','auto',type=str)
        index=self.asr_language.findData(language)
        if index>=0:self.asr_language.setCurrentIndex(index)
        else:self.asr_language.setEditText(language)
        return w

    def _render_preview_frame(self):
        if self._asr_install_process is not None:
            self.render_status.setText('请等待组件任务完成后预览。');return
        if not self._current_path or self._preview_process is not None:return
        if self._render_process is not None:
            QMessageBox.information(self,'成片预览','请等待当前渲染结束后预览。');return
        from app.services.remotion_renderer import RemotionRenderer
        from app.services.app_paths import data_dir
        import uuid
        try:
            payload=self._payload_for(self._current_path)
            intro=payload.get('intro') or {}
            offset=float(intro.get('duration',0)) if intro.get('enabled') and intro.get('path') else 0
            seconds=(self.player.position()/1000 if self.player else 0)+offset
            output=data_dir()/'packaging/previews'/f'{uuid.uuid4().hex}.png';output.parent.mkdir(parents=True,exist_ok=True)
            command,cwd=RemotionRenderer(self.remotion_dir.text().strip()).render_flowstudio_command(payload,str(output),int(seconds*payload['fps']))
        except Exception as exc:QMessageBox.warning(self,'成片预览',str(exc));return
        proc=QProcess(self);self._preview_process=proc;self._preview_log=''
        proc.setWorkingDirectory(cwd);proc.setProgram(command[0]);proc.setArguments(command[1:]);proc.setProcessChannelMode(QProcess.MergedChannels)
        def read():self._preview_log=(self._preview_log+bytes(proc.readAllStandardOutput()).decode('utf-8',errors='replace'))[-4000:]
        def done(code,*args):
            if self._preview_process is not proc:return
            read();self._preview_process=None;self.full_preview_btn.setEnabled(True);proc.deleteLater()
            if code or not output.exists():QMessageBox.warning(self,'成片预览','预览失败：\n'+self._preview_log);return
            dialog=QDialog(self);dialog.setWindowTitle('成片效果（当前时间点，包含所有包装图层）');layout=QVBoxLayout(dialog)
            label=QLabel();pixmap=QPixmap(str(output));label.setPixmap(pixmap.scaled(850,740,Qt.KeepAspectRatio,Qt.SmoothTransformation));layout.addWidget(label)
            close=QDialogButtonBox(QDialogButtonBox.Close);close.rejected.connect(dialog.reject);layout.addWidget(close);dialog.exec()
        proc.readyReadStandardOutput.connect(read);proc.finished.connect(done)
        proc.errorOccurred.connect(lambda e:done(1) if e==QProcess.FailedToStart else None)
        self.full_preview_btn.setEnabled(False);self.render_status.setText('正在准备成片效果预览…');proc.start()

    def _install_asr_components(self):
        if self._asr_install_process is not None or self._asr_process is not None:return
        executable=Path(sys.executable)
        if executable.name.lower()=='pythonw.exe':executable=executable.with_name('python.exe')
        proc=QProcess(self);self._asr_install_process=proc
        proc.setProgram(str(executable));proc.setArguments(['-X','utf8',str(Path(__file__).resolve().parents[2]/'scripts/install_packaging_asr.py')])
        proc.setProcessChannelMode(QProcess.MergedChannels)
        self._asr_install_log=''
        def read():
            self._asr_install_log=(self._asr_install_log+bytes(proc.readAllStandardOutput()).decode('utf-8',errors='replace'))[-6000:]
        def done(code,*args):
            if self._asr_install_process is not proc:return
            read();self._asr_install_process=None;self.asr_install_btn.setEnabled(True)
            self.asr_current_btn.setEnabled(True);self.asr_all_btn.setEnabled(True)
            self.asr_status.setText('本地识别组件已安装，可以开始识别。' if code==0 else '组件安装未完成，请查看下方原因。')
            self.component_feedback.setText(self.asr_status.text() if code==0 else '组件安装失败：'+self._asr_install_log[-1200:])
            if code:self.asr_results.appendPlainText(self._asr_install_log)
            proc.deleteLater()
        proc.readyReadStandardOutput.connect(read);proc.finished.connect(done)
        proc.errorOccurred.connect(lambda e:done(1) if e==QProcess.FailedToStart else None)
        self.asr_install_btn.setEnabled(False);self.asr_current_btn.setEnabled(False);self.asr_all_btn.setEnabled(False)
        self.asr_status.setText('正在下载并安装本地识别组件，完成后即可使用。');proc.start()

    def _pick_ffmpeg(self):
        path,_=QFileDialog.getOpenFileName(self,'选择 FFmpeg')
        if path:self.asr_ffmpeg.setText(path); self._settings.setValue('packaging/ffmpeg',path)

    def _asr_provider_changed(self,provider):
        self.asr_model.clear()
        self.asr_model.addItems(['base','small','medium','large-v3'] if provider==LOCAL_PROVIDER else [DEFAULT_MODELS[provider]])
        self.asr_model.setCurrentText(self._settings.value('packaging/asr_model/'+provider,DEFAULT_MODELS[provider],type=str))
        if hasattr(self,'asr_key'):self.asr_key.clear(); self.asr_key.setEnabled(provider!=LOCAL_PROVIDER)

    @staticmethod
    def _credential_backend():
        if sys.platform=='win32':
            from keyring.backends.Windows import WinVaultKeyring
            return WinVaultKeyring()
        if sys.platform=='darwin':
            from keyring.backends.macOS import Keyring
            return Keyring()
        from keyring.backends.SecretService import Keyring
        return Keyring()

    def _save_asr_key(self):
        try:
            if not self.asr_key.text().strip():raise ValueError('请先填写密钥。')
            from app.services.credential_pool import save
            save('com.flowstudio.asr',self.asr_provider.currentText(),self.asr_key.text().strip())
            self.asr_key.clear(); self.asr_status.setText('密钥已保存到系统凭据管理器。')
            self.component_feedback.setText('密钥已安全保存：'+self.asr_provider.currentText())
        except Exception as exc:QMessageBox.warning(self,'保存密钥',str(exc))

    def _start_asr(self,paths):
        if self._asr_install_process is not None:
            self.asr_status.setText('请等待组件安装 / 模型下载完成后识别。');return
        if self._asr_process is not None:return
        paths=[p for p in paths if p and p in self._project['videos'] and Path(p).is_file()]
        if not paths:return
        if any(self._project['videos'][p].get('captions') for p in paths):
            if QMessageBox.question(self,'重新识别','识别成功后将替换这些视频现有字幕（包括人工校对）。是否继续？')!=QMessageBox.Yes:return
        try:
            ffmpeg=find_ffmpeg(self.asr_ffmpeg.text().strip())
            provider=self.asr_provider.currentText()
            key=self.asr_key.text().strip() or os.environ.get({'Groq':'GROQ_API_KEY','Gemini':'GEMINI_API_KEY','ElevenLabs':'ELEVENLABS_API_KEY','Gladia':'GLADIA_API_KEY'}.get(provider,''),'')
            from app.services import credential_pool
            keys = [key] if key else ([] if provider==LOCAL_PROVIDER else credential_pool.read('com.flowstudio.asr',provider))
            if provider!=LOCAL_PROVIDER and not keys:raise ValueError('请先填写或保存所选服务的 API 密钥。')
            self._asr_keys=keys
            import re
            if not re.fullmatch(r'[A-Za-z0-9_.:-]+',self.asr_model.currentText().strip()):raise ValueError('模型名称只能包含字母、数字、点、横线、下划线或冒号。')
            language=self.asr_language.currentText().strip()
            if language==self.asr_language.itemText(self.asr_language.currentIndex()):language=self.asr_language.currentData()
            self._asr_config={'provider':provider,'model':self.asr_model.currentText().strip(),'key':key,'ffmpeg':ffmpeg,
                'language':language or 'auto','max_words':self.asr_max_words.value()}
            self._settings.setValue('packaging/asr_provider',provider)
            self._settings.setValue('packaging/asr_model/'+provider,self._asr_config['model'])
            self._settings.setValue('packaging/asr_language',self._asr_config['language'])
            self._settings.setValue('packaging/ffmpeg',ffmpeg)
        except Exception as exc:QMessageBox.warning(self,'字幕识别',str(exc));return
        self._capture_controls(); self._asr_queue=list(paths);self._asr_project=self._project
        self.asr_current_btn.setEnabled(False);self.asr_all_btn.setEnabled(False);self.asr_stop_btn.setEnabled(True)
        self._asr_next()

    def _asr_next(self):
        if getattr(self,'_asr_project',None) is not self._project:self._asr_queue.clear()
        if not self._asr_queue:
            self._asr_process=None; self._asr_config={}; self._asr_keys=[]
            self.asr_current_btn.setEnabled(True);self.asr_all_btn.setEnabled(True);self.asr_stop_btn.setEnabled(False)
            self.asr_status.setText('识别队列已结束；各视频结果见下方。');return
        from app.services.credential_pool import next_key
        self._asr_config['key']=next_key('com.flowstudio.asr',self._asr_config['provider'],getattr(self,'_asr_keys',[]))
        path=self._asr_queue.pop(0);self._asr_path=path
        self._asr_original=copy.deepcopy(self._project['videos'][path].get('captions',[]))
        self._asr_buffer='';self._asr_result=None;self._asr_error='';self._asr_decoder=codecs.getincrementaldecoder('utf-8')('replace')
        self.asr_status.setText('识别中：'+Path(path).name)
        proc=QProcess(self);self._asr_process=proc
        executable=Path(sys.executable)
        if executable.name.lower()=='pythonw.exe':executable=executable.with_name('python.exe')
        proc.setProgram(str(executable));proc.setArguments(['-X','utf8',str(Path(__file__).resolve().parents[2]/'scripts/packaging_recognize.py')])
        proc.setProcessChannelMode(QProcess.SeparateChannels)
        proc.started.connect(lambda: (proc.write((json.dumps(dict(self._asr_config,source=path))+'\n').encode()),proc.closeWriteChannel()))
        proc.readyReadStandardOutput.connect(lambda:self._asr_read(proc))
        proc.readyReadStandardError.connect(lambda:proc.readAllStandardError())
        proc.finished.connect(lambda code,status:self._asr_finished(proc,code,path))
        proc.errorOccurred.connect(lambda err:self._asr_failed_start(proc,err,path))
        proc.start()

    def _asr_failed_start(self,proc,error,path):
        if error==QProcess.FailedToStart:
            self._asr_error='识别进程无法启动：'+proc.errorString();self._asr_finished(proc,1,path)

    def _asr_read(self,proc):
        self._asr_buffer+=self._asr_decoder.decode(bytes(proc.readAllStandardOutput()))
        while '\n' in self._asr_buffer:
            line,self._asr_buffer=self._asr_buffer.split('\n',1)
            try:item=json.loads(line)
            except ValueError:continue
            if 'progress' in item:self.asr_status.setText(str(item['progress']))
            if 'captions' in item:self._asr_result=item
            if 'error' in item:self._asr_error=str(item['error'])

    def _asr_finished(self,proc,code,path):
        if proc is not self._asr_process:return
        self._asr_read(proc);self._asr_process=None;proc.deleteLater()
        state=self._project['videos'].get(path) if self._asr_project is self._project else None
        if path==self._current_path:self._capture_controls()
        if code==0 and self._asr_result and state:
            if state.get('captions',[])!=self._asr_original:
                message='识别期间字幕已编辑，保留人工修改；请重新识别。'
            else:
                state['captions']=self._asr_result['captions'];state['status']='已识别'
                state['captionTimingEstimated']=bool(self._asr_result['estimated'])
                state['recognitionWarnings']=self._asr_result.get('warnings',[])
                if state['recognitionWarnings']:state['status']='字幕待核对'
                if path==self._current_path:self._load_state(state)
                message=f"识别完成：{len(state['captions'])} 条"+('（部分词时间为估计，请试听校对）' if state['captionTimingEstimated'] else '')
                if state['recognitionWarnings']:message=f"识别存在缺口，待核对：{len(state['captions'])} 条\n"+'\n'.join(state['recognitionWarnings'])
        else:message=self._asr_error or '识别失败或已停止，请检查组件、模型与音轨。'
        self.asr_results.appendPlainText(Path(path).name+'：'+message)
        self._rebuild_tree(False);QTimer.singleShot(0,self._asr_next)

    def _stop_asr(self):
        self._asr_queue.clear()
        if self._asr_process is not None:
            # Terminate FFmpeg/model children as well as their owning worker.
            try:
                import psutil
                parent=psutil.Process(int(self._asr_process.processId()))
                for child in parent.children(recursive=True):
                    try:child.kill()
                    except psutil.Error:pass
            except Exception:pass
            self._asr_process.kill()

    def _proofread(self,all_videos=False):
        self._capture_controls()
        paths=self._project['order'] if all_videos else [self._current_path]
        rows=[]
        for path in paths:
            state=self._project['videos'].get(path,{})
            if state.get('captions'):
                rows.append({'path':path,'srt':captions_to_srt(state['captions']),'words':captions_to_srt(state['captions'],True)})
        if not rows:QMessageBox.information(self,'字幕校对','请先识别或导入字幕。');return
        dialog=BatchScriptProofreadDialog(self,rows)
        if dialog.exec()!=QDialog.Accepted:return
        for result in dialog.selected_results:
            state=self._project['videos'][result['path']]
            state['captions']=captions_from_srt(result['corrected'],result['corrected_words'])
            state['captionTimingEstimated']=True;state['status']='已校对'
        if self._current_state():self._load_state(self._current_state())
        self._rebuild_tree(False)

    def _export_srt(self):
        state=self._capture_controls()
        if not state or not state.get('captions'):return
        path,_=QFileDialog.getSaveFileName(self,'导出字幕',Path(self._current_path).stem+'.srt','字幕 (*.srt)')
        if path:
            try:validate_captions(state['captions']);Path(path).write_text(captions_to_srt(state['captions']),encoding='utf-8-sig')
            except Exception as exc:QMessageBox.warning(self,'导出字幕',str(exc))

    def _add_reels_styles(self,layout):
        presets=json.loads((Path(__file__).resolve().parents[1]/'services/reels/presets.json').read_text(encoding='utf-8'))
        self._reels_presets=presets
        try:presets.update(json.loads(self._settings.value('packaging/reels_presets','{}',type=str)))
        except ValueError:pass
        row=QHBoxLayout();self.reels_preset=QComboBox();self.reels_preset.addItems(presets);self.reels_preset.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon);self.reels_preset.setMinimumContentsLength(10)
        row.addWidget(self.reels_preset,1);btn=QPushButton('套用');btn.clicked.connect(self._apply_reels_style);row.addWidget(btn);layout.addLayout(row)
        self.reels_style_hint=QLabel('可使用下方原有样式，或套用 Reels 字幕效果。');self.reels_style_hint.setWordWrap(True);layout.addWidget(self.reels_style_hint)
        buttons=QHBoxLayout()
        edit=QPushButton('调整样式');edit.clicked.connect(self._edit_reels_style);buttons.addWidget(edit)
        save=QPushButton('保存样式');save.clicked.connect(self._save_reels_style);buttons.addWidget(save)
        layout.addLayout(buttons)

    def _save_reels_style(self):
        if not self._reels_style:return
        name,ok=QInputDialog.getText(self,'保存字幕方案','方案名称')
        if not ok or not name.strip():return
        try:presets=json.loads(self._settings.value('packaging/reels_presets','{}',type=str))
        except ValueError:presets={}
        name='自定义 · '+name.strip();presets[name]=copy.deepcopy(self._reels_style)
        self._settings.setValue('packaging/reels_presets',json.dumps(presets,ensure_ascii=False))
        self._reels_presets[name]=presets[name]
        if self.reels_preset.findText(name)<0:self.reels_preset.addItem(name)
        self.reels_preset.setCurrentText(name)

    def _edit_reels_style(self):
        if not self._reels_style:self._apply_reels_style()
        style=copy.deepcopy(self._reels_style)
        dialog=QDialog(self);dialog.setWindowTitle('Reels 字幕效果设置');layout=QVBoxLayout(dialog);form=QFormLayout()
        font=QFontComboBox();font.setCurrentFont(QFont(style.get('font','Arial')));form.addRow('字体',font)
        position=QComboBox();position.addItems(['顶部','画面中间','底部']);position.setCurrentText(style.get('position','底部'));form.addRow('位置',position)
        controls={}
        for key,title,default,low,high in [('font_size','字号',76,18,200),('outline_width','描边宽度',3,0,20),('margin_v','垂直边距',500,0,1800),('line_length','每行字符数',26,4,100),('max_lines','每页行数',2,1,6),('letter_spacing','字间距',0,-10,30),('word_spacing','词间距',0,-30,50),('line_spacing','行距百分比',110,70,180),('highlight_padding','色块水平留白',16,0,80),('highlight_padding_y','色块垂直留白',8,0,80)]:
            spin=QSpinBox();spin.setRange(low,high);spin.setValue(int(style.get(key,default)));controls[key]=spin;form.addRow(title,spin)
        for key,title,default in [('text','文字 / 第一行','#FFFFFF'),('outline','描边 / 第二行','#111111'),('highlight','跟读色','#FACC15'),('background','背景 / 第一行底色','#168AAD'),('active_text','色块文字 / 第三行','#FFFFFF')]:
            button=QPushButton(style.get(key,default));button.setProperty('color',style.get(key,default))
            def choose(checked=False,btn=button):
                color=QColorDialog.getColor(QColor(btn.property('color')),dialog,'选择颜色')
                if color.isValid():btn.setProperty('color',color.name());btn.setText(color.name())
            button.clicked.connect(choose);controls[key]=button;form.addRow(title,button)
        layout.addLayout(form);buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        if dialog.exec()!=QDialog.Accepted:return
        style['font']=font.currentFont().family();style['position']=position.currentText()
        for key,widget in controls.items():style[key]=widget.value() if isinstance(widget,QSpinBox) else widget.property('color')
        self._reels_style=style;self._state_changed()

    def _apply_reels_style(self):
        self._reels_style=copy.deepcopy(self._reels_presets[self.reels_preset.currentText()])
        self.reels_style_hint.setText('当前 Reels 效果：'+self.reels_preset.currentText())
        self._state_changed()

    def _add_output_controls(self,layout):
        form=QFormLayout()
        form.setVerticalSpacing(4)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.render_mode=QComboBox();self.render_mode.addItems(['自动（优先 FFmpeg）','FFmpeg CPU','Remotion 兼容']);self.render_mode.currentTextChanged.connect(self._state_changed)
        form.addRow('渲染方式',self.render_mode)
        self.output_resolution=QComboBox();self.output_resolution.addItems(['默认最高','720p','1080p','2K','4K']);self.output_resolution.setCurrentText('1080p')
        self.output_fps=QComboBox();self.output_fps.addItems(['24','25','30','50','60']);self.output_fps.setCurrentText('30')
        self.output_format=QComboBox();self.output_format.addItems(['MP4 / H.264','MOV / ProRes','WebM / VP9'])
        self.output_fit=QComboBox();self.output_fit.addItems(['完整留边','居中裁满'])
        for title,widget in [('分辨率',self.output_resolution),('帧率',self.output_fps),('格式 / 编码',self.output_format),('画面适配',self.output_fit)]:
            form.addRow(title,widget);widget.currentTextChanged.connect(self._state_changed)
        for widget in (self.render_mode,self.output_resolution,self.output_fps,self.output_format,self.output_fit):
            widget.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            widget.setMinimumContentsLength(6)
            widget.setMinimumWidth(0)
            widget.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed)
            widget.setFixedHeight(30)
        layout.addLayout(form)
        self.naming_dialog=QDialog(self);self.naming_dialog.setWindowTitle('成品命名设置');self.naming_dialog.resize(440,480)
        naming_layout=QVBoxLayout(self.naming_dialog);form=QFormLayout();naming_layout.addLayout(form)
        self.rename_enabled=QCheckBox('自定义成品名称')
        self.rename_enabled.setToolTip('序号-前缀-标题-日期-后缀')
        self.rename_prefix=QLineEdit();self.rename_suffix=QLineEdit();self.rename_date=QLineEdit(date.today().strftime('%Y%m%d'))
        self.rename_date_enabled=QCheckBox('加日期');self.rename_suffix_enabled=QCheckBox('加后缀')
        self.rename_start=QSpinBox();self.rename_start.setRange(0,999999);self.rename_start.setValue(1)
        self.rename_padding=QSpinBox();self.rename_padding.setRange(1,12);self.rename_padding.setValue(3)
        self.rename_titles=QPlainTextEdit();self.rename_titles.setMaximumHeight(100);self.rename_titles.setPlaceholderText('每行一个标题，按左侧视频顺序匹配；空行使用首句字幕，再回退原文件名。')
        for title,widget in [('',self.rename_enabled),('前缀',self.rename_prefix),('',self.rename_date_enabled),('日期',self.rename_date),('',self.rename_suffix_enabled),('后缀',self.rename_suffix),('起始编号',self.rename_start),('编号位数',self.rename_padding),('批量标题',self.rename_titles)]:
            form.addRow(title,widget)
            if isinstance(widget,QCheckBox):widget.toggled.connect(self._state_changed)
            elif isinstance(widget,QSpinBox):widget.valueChanged.connect(self._state_changed)
            else:widget.textChanged.connect(self._state_changed)
        preview=QPushButton('预览全部输出文件名');preview.clicked.connect(self._preview_names);naming_layout.addWidget(preview)
        close=QDialogButtonBox(QDialogButtonBox.Close);close.rejected.connect(self.naming_dialog.reject);naming_layout.addWidget(close)
        self.naming_button=QPushButton('成品命名…');self.naming_button.clicked.connect(lambda:self.naming_dialog.exec())

    def _reels_capture(self,state):
        if not state or not hasattr(self,'output_resolution'):return
        state['reelsStyle']=copy.deepcopy(self._reels_style)
        p=state['params']
        p['render_mode']=self.render_mode.currentText()
        for key in ('output_resolution','output_fps','output_format','output_fit'):
            p[key]=getattr(self,key).currentText()
        for key in ('rename_prefix','rename_suffix','rename_date'):p[key]=getattr(self,key).text()
        for key in ('rename_enabled','rename_date_enabled','rename_suffix_enabled'):p[key]=getattr(self,key).isChecked()
        for key in ('rename_start','rename_padding'):p[key]=getattr(self,key).value()
        p['rename_titles']=self.rename_titles.toPlainText()
        state['watermarks']=self._watermark_rows()

    def _reels_load(self,state):
        self._reels_style=copy.deepcopy(state.get('reelsStyle') or {})
        self.reels_style_hint.setText('Reels 字幕 · FFmpeg 快速渲染' if self._reels_style else '原有字幕 · Remotion 兼容渲染')
        for name,preset in self._reels_presets.items():
            if preset==self._reels_style:self.reels_preset.setCurrentText(name);break
        p=state.get('params') or {}
        self.render_mode.setCurrentText(p.get('render_mode','自动（优先 FFmpeg）'))
        for key,default in [('output_resolution','1080p'),('output_fps','30'),('output_format','MP4 / H.264'),('output_fit','完整留边')]:getattr(self,key).setCurrentText(str(p.get(key,default)))
        for key in ('rename_prefix','rename_suffix','rename_date'):getattr(self,key).setText(str(p.get(key,'')))
        for key in ('rename_enabled','rename_date_enabled','rename_suffix_enabled'):getattr(self,key).setChecked(bool(p.get(key)))
        for key,default in [('rename_start',1),('rename_padding',3)]:getattr(self,key).setValue(int(p.get(key,default)))
        self.rename_titles.setPlainText(str(p.get('rename_titles','')))
        self.watermark_layers.setRowCount(0)
        for item in state.get('watermarks',[]):self._append_watermark(item)

    def _preview_names(self):
        self._capture_controls(); lines=[]
        for index,path in enumerate(self._project['order']):
            state=self._project['videos'][path];p=state.get('params',{})
            name=output_basename(path,p,index,(state.get('captions') or [{}])[0].get('text',''))
            lines.append(Path(path).name+' → '+name+'.'+self._output_extension(p))
        dialog=QDialog(self);dialog.setWindowTitle('输出命名预览（已有同名文件会自动加编号）');dialog.resize(820,500)
        box=QVBoxLayout(dialog);text=QPlainTextEdit('\n'.join(lines));text.setReadOnly(True);box.addWidget(text)
        close=QDialogButtonBox(QDialogButtonBox.Close);close.rejected.connect(dialog.reject);box.addWidget(close);dialog.exec()

    @staticmethod
    def _output_extension(params):
        return {'MOV / ProRes':'mov','WebM / VP9':'webm'}.get(params.get('output_format'),'mp4')

    def _reels_output_for(self,path):
        state=self._project['videos'][path];params=state.get('params') or {}
        index=self._project['order'].index(path)
        name=output_basename(path,params,index,(state.get('captions') or [{}])[0].get('text',''))
        return available_output(params.get('output_dir') or self.output_dir.text(),name,self._output_extension(params))

    def _reels_payload(self,payload,state):
        params=state.get('params') or {}
        meta=state.get('media') or {}
        ratio=params.get('ratio','9:16')
        if ratio=='原始比例' or params.get('output_resolution')=='默认最高':
            if not meta:
                meta=probe_media(state['source'],self.asr_ffmpeg.text().strip());state['media']=meta
        w,h=output_size(ratio,params.get('output_resolution','1080p'),(meta.get('width',1080),meta.get('height',1920)))
        payload.update(renderMode=params.get('render_mode','自动（优先 FFmpeg）'),ffmpeg=self.asr_ffmpeg.text().strip(),width=w,height=h,fps=int(params.get('output_fps','30')),
            codec={'MOV / ProRes':'prores','WebM / VP9':'vp9'}.get(params.get('output_format'),'h264'),
            fit='cover' if params.get('output_fit')=='居中裁满' else 'contain',
            reelsStyle=copy.deepcopy(state.get('reelsStyle',{})),watermarks=copy.deepcopy(state.get('watermarks',[])))
        validate_captions(payload.get('captions',[]))
        return payload

    def _add_watermark_controls(self,layout):
        layout.addWidget(QLabel('图片 / GIF / 视频水印'))
        self.watermark_layers=QTableWidget(0,7)
        self.watermark_layers.setHorizontalHeaderLabels(['启用 / 文件','覆盖方式','位置','宽度%','透明度%','边距','去黑白底'])
        self.watermark_layers.horizontalHeader().setSectionResizeMode(0,QHeaderView.Stretch)
        self.watermark_layers.itemChanged.connect(self._state_changed)
        self.watermark_layers.setMinimumHeight(100)
        self.watermark_layers.setMaximumHeight(180)
        self.watermark_layers.verticalHeader().hide()
        self.watermark_layers.setSelectionBehavior(QTableWidget.SelectRows)
        self.watermark_layers.setSelectionMode(QTableWidget.SingleSelection)
        for column in range(1,7): self.watermark_layers.setColumnHidden(column,True)
        self.watermark_layers.setHorizontalHeaderLabels(['水印文件（勾选启用）','','','','','',''])
        layout.addWidget(self.watermark_layers,1)
        row=QHBoxLayout()
        add=QPushButton('添加水印');add.clicked.connect(self._add_watermarks);row.addWidget(add)
        remove=QPushButton('删除选中');remove.clicked.connect(self._remove_watermarks);row.addWidget(remove);layout.addLayout(row)
        self.watermark_editors={}
        for column,label,choices in [(1,'覆盖方式',['小 Logo','全屏覆盖']),(2,'位置',['左上','右上','左下','右下','居中'])]:
            line=QHBoxLayout();line.addWidget(QLabel(label));editor=QComboBox();editor.addItems(choices);line.addWidget(editor,1);layout.addLayout(line)
            self.watermark_editors[column]=editor
            editor.currentTextChanged.connect(lambda value,c=column:self._edit_watermark(c,value))
        for column,label,low,high in [(3,'宽度 %',1,100),(4,'透明度 %',0,100),(5,'边距',0,1000)]:
            line=QHBoxLayout();line.addWidget(QLabel(label));editor=QSpinBox();editor.setRange(low,high);line.addWidget(editor,1);layout.addLayout(line)
            self.watermark_editors[column]=editor
            editor.valueChanged.connect(lambda value,c=column:self._edit_watermark(c,value))
        editor=QCheckBox('去除图片 / GIF 的黑白背景');layout.addWidget(editor);self.watermark_editors[6]=editor
        editor.toggled.connect(lambda value:self._edit_watermark(6,value))
        self.watermark_layers.itemSelectionChanged.connect(self._select_watermark)
        layout.addStretch(1)
        self._select_watermark()

    def _select_watermark(self):
        row=self.watermark_layers.currentRow()
        for column,editor in self.watermark_editors.items():
            source=self.watermark_layers.cellWidget(row,column) if row>=0 else None
            editor.setEnabled(source is not None and source.isEnabled())
            editor.blockSignals(True)
            if source:
                if column in (1,2):editor.setCurrentText(source.currentText())
                elif column==6:editor.setChecked(source.isChecked())
                else:editor.setValue(source.value())
            editor.blockSignals(False)

    def _edit_watermark(self,column,value):
        row=self.watermark_layers.currentRow()
        source=self.watermark_layers.cellWidget(row,column) if row>=0 else None
        if source:
            if column in (1,2):source.setCurrentText(value)
            elif column==6:source.setChecked(value)
            else:source.setValue(value)

    def _add_watermarks(self):
        paths,_=QFileDialog.getOpenFileNames(self,'添加水印','','水印 (*.png *.jpg *.jpeg *.webp *.gif *.mp4 *.mov *.webm)')
        old=self._loading_state;self._loading_state=True
        try:
            for path in paths:self._append_watermark({'path':path})
        finally:self._loading_state=old
        self._state_changed()

    def _append_watermark(self,item):
        row=self.watermark_layers.rowCount();self.watermark_layers.insertRow(row)
        path=QTableWidgetItem(Path(item.get('path','')).name);path.setData(Qt.UserRole,item.get('path',''));path.setToolTip(item.get('path',''))
        path.setFlags(Qt.ItemIsEnabled|Qt.ItemIsSelectable|Qt.ItemIsUserCheckable);path.setCheckState(Qt.Checked if item.get('enabled',True) else Qt.Unchecked);self.watermark_layers.setItem(row,0,path)
        for col,key,choices,default in [(1,'mode',['小 Logo','全屏覆盖'],'小 Logo'),(2,'position',['左上','右上','左下','右下','居中'],'右上')]:
            combo=QComboBox();combo.addItems(choices);combo.setCurrentText(item.get(key,default));combo.currentTextChanged.connect(self._state_changed);self.watermark_layers.setCellWidget(row,col,combo)
        for col,key,default,low,high in [(3,'scale',18,1,100),(4,'opacity',90,0,100),(5,'margin',24,0,1000)]:
            spin=QSpinBox();spin.setRange(low,high);spin.setValue(int(item.get(key,default)));spin.valueChanged.connect(self._state_changed);self.watermark_layers.setCellWidget(row,col,spin)
        check=QCheckBox()
        image_source=Path(item.get('path','')).suffix.lower() in ('.png','.jpg','.jpeg','.webp','.gif','.bmp')
        check.setEnabled(image_source);check.setChecked(image_source and bool(item.get('knockout',False)))
        check.setToolTip('去除图片或 GIF 的纯黑、纯白背景；视频水印不支持此选项。')
        check.toggled.connect(self._state_changed);self.watermark_layers.setCellWidget(row,6,check)
        self.watermark_layers.selectRow(row)
        self._select_watermark()

    def _remove_watermarks(self):
        for row in sorted({i.row() for i in self.watermark_layers.selectedIndexes()},reverse=True):self.watermark_layers.removeRow(row)
        self._state_changed()

    def _watermark_rows(self):
        result=[]
        for r in range(self.watermark_layers.rowCount()):
            item=self.watermark_layers.item(r,0)
            if not item or any(self.watermark_layers.cellWidget(r,c) is None for c in range(1,7)):continue
            result.append({'path':item.data(Qt.UserRole),'enabled':item.checkState()==Qt.Checked,
                'mode':self.watermark_layers.cellWidget(r,1).currentText(),'position':self.watermark_layers.cellWidget(r,2).currentText(),
                'scale':self.watermark_layers.cellWidget(r,3).value(),'opacity':self.watermark_layers.cellWidget(r,4).value(),
                'margin':self.watermark_layers.cellWidget(r,5).value(),'knockout':self.watermark_layers.cellWidget(r,6).isChecked()})
        return result
