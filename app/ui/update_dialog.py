from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QDialog,QVBoxLayout,QLabel,QPushButton,QProgressBar,QMessageBox
from app.services import updater
from app.version import VERSION

class UpdateWorker(QThread):
    result=Signal(object);error=Signal(str);progress=Signal(int)
    def __init__(self,release=None,parent=None):super().__init__(parent);self.release=release
    def run(self):
        try:
            result=updater.download(self.release,self.progress.emit,self.isInterruptionRequested) if self.release else updater.check()
            self.result.emit(result)
        except Exception as exc:self.error.emit(str(exc))

class UpdateDialog(QDialog):
    def __init__(self,parent):
        super().__init__(parent);self.setWindowTitle('版本与更新');self.resize(430,240)
        self.worker=None;self.release=None;self.path=None
        layout=QVBoxLayout(self);layout.addWidget(QLabel('Flow Studio  '+VERSION))
        self.status=QLabel('从官方 GitHub 发布页检查适合当前系统的版本。');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.bar=QProgressBar();self.bar.hide();layout.addWidget(self.bar)
        self.button=QPushButton('检查更新');self.button.clicked.connect(self.action);layout.addWidget(self.button)
        self.cancel=QPushButton('关闭');self.cancel.clicked.connect(self.reject);layout.addWidget(self.cancel)
    def action(self):
        if self.path:
            prompt='安装前将退出软件，请先完成或暂停当前任务。'
            import sys
            if sys.platform=='darwin':prompt+=' 随后打开 DMG，将应用拖入 Applications 替换旧版。'
            elif sys.platform.startswith('linux'):prompt+=' 随后打开系统软件安装器，按提示确认安装。'
            if QMessageBox.question(self,'退出并安装',prompt)!=QMessageBox.StandardButton.Yes:return
            updater.verify(self.path,self.release)
            self.parent()._pending_update=(self.path,self.release)
            self.accept();self.parent().close();return
        self.button.setEnabled(False);self.cancel.setText('取消下载' if self.release else '关闭')
        self.status.setText('正在下载并校验安装包…' if self.release else '正在检查更新…')
        self.worker=UpdateWorker(self.release,self);self.worker.progress.connect(self.bar.setValue)
        self.worker.result.connect(self.completed);self.worker.error.connect(self.failed)
        self.worker.finished.connect(self.worker_done)
        if self.release:self.bar.show()
        self.worker.start()
    def worker_done(self):
        worker=self.worker;self.worker=None
        if worker:worker.deleteLater()
        self.button.setEnabled(True);self.cancel.setText('关闭')
    def completed(self,result):
        if self.release:
            self.path=result;self.status.setText('下载完成，SHA-256 校验通过。');self.button.setText('退出并安装')
        elif result:
            self.release=result;self.status.setText('发现新版本 '+result['version']+'，点击下载后可退出安装。');self.button.setText('下载安装包')
        else:self.status.setText('当前已是最新正式版本。')
    def failed(self,message):self.status.setText(message)
    def reject(self):
        if self.worker is not None:
            self.worker.requestInterruption();self.status.setText('正在停止，请稍候…');return
        super().reject()
    def closeEvent(self,event):
        if self.worker is not None:self.worker.requestInterruption();event.ignore()
        else:super().closeEvent(event)
