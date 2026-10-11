from PySide6.QtCore import Qt,QRectF
from PySide6.QtGui import QPainter,QImage
from PySide6.QtWidgets import QWidget,QDialog,QVBoxLayout,QFormLayout,QDoubleSpinBox,QComboBox,QLabel,QPushButton,QDialogButtonBox,QMessageBox
from PySide6.QtMultimedia import QVideoSink
from app.services import clip_transform as transforms

class TransformVideoWidget(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent);self._sink=QVideoSink(self);self._sink.videoFrameChanged.connect(self.frame_changed)
        self.image=QImage();self.values=dict(transforms.DEFAULT)
    def videoSink(self):return self._sink
    def setAspectRatioMode(self,*args):pass
    def frame_changed(self,frame):
        self.image=frame.toImage();self.update()
    def set_transform(self,values):self.values=transforms.validate(values);self.update()
    def paintEvent(self,event):
        p=QPainter(self);p.fillRect(self.rect(),Qt.black)
        if self.image.isNull():return
        v=self.values;scale=min(self.width()/self.image.width(),self.height()/self.image.height())*v['ZoomX']
        w,h=self.image.width()*scale,self.image.height()*scale
        x=(self.width()-w)/2+v['Pan']*self.width()/v['width']
        y=(self.height()-h)/2-v['Tilt']*self.height()/v['height']
        p.setRenderHint(QPainter.SmoothPixmapTransform);p.drawImage(QRectF(x,y,w,h),self.image)

class ClipTransformDialog(QDialog):
    def __init__(self,output_id,preview,parent=None):
        super().__init__(parent);self.output_id=output_id;self.preview=preview;self.original=transforms.get(output_id)
        self.setWindowTitle('当前片段 · 画面调整');self.setModal(True);self.resize(340,300)
        layout=QVBoxLayout(self);note=QLabel('仅调整当前片段预览，不修改原视频。\n缩放 1.000 = 原大小；X 正数向右，Y 正数向上。');note.setWordWrap(True);layout.addWidget(note)
        form=QFormLayout();layout.addLayout(form);self.fields={}
        for key,label,lo,hi,step,dec in [('ZoomX','缩放',.1,10,.01,3),('Pan','位置 X',-4320,4320,10,1),('Tilt','位置 Y',-7680,7680,10,1)]:
            spin=QDoubleSpinBox();spin.setRange(lo,hi);spin.setDecimals(dec);spin.setSingleStep(step);spin.setValue(self.original[key]);self.fields[key]=spin;form.addRow(label,spin);spin.valueChanged.connect(self.changed)
        self.size=QComboBox();self.size.addItem('720 × 1280（自动剪辑默认）',(720,1280));self.size.addItem('1080 × 1920',(1080,1920));self.size.setCurrentIndex(0 if self.original['width']==720 else 1);form.addRow('达芬奇时间线',self.size);self.size.currentIndexChanged.connect(self.changed)
        reset=QPushButton('恢复原始画面');reset.clicked.connect(self.reset);layout.addWidget(reset)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);buttons.button(QDialogButtonBox.Save).setText('保存');buttons.button(QDialogButtonBox.Cancel).setText('取消');buttons.accepted.connect(self.store);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
    def values(self):
        w,h=self.size.currentData();return dict(ZoomX=self.fields['ZoomX'].value(),Pan=self.fields['Pan'].value(),Tilt=self.fields['Tilt'].value(),width=w,height=h)
    def changed(self,*args):
        if hasattr(self,'size'):
            w,h=self.size.currentData()
            self.fields['Pan'].setRange(-4*w,4*w);self.fields['Tilt'].setRange(-4*h,4*h)
            self.preview.set_transform(self.values())
    def reset(self):
        for k,s in self.fields.items():s.setValue(transforms.DEFAULT[k])
    def store(self):
        try:transforms.save(self.output_id,self.values())
        except Exception as exc:QMessageBox.warning(self,'未保存',str(exc));return
        self.accept()
    def reject(self):self.preview.set_transform(self.original);super().reject()
