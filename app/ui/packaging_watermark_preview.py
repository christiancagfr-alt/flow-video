"""Non-destructive watermark preview using the export geometry."""
from pathlib import Path
from PySide6.QtCore import Qt, QRectF, QUrl
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QWidget
from PySide6.QtMultimedia import QMediaPlayer,QVideoSink

class WatermarkPreview(QWidget):
    def __init__(self,parent):
        super().__init__(parent);self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.layers=[];self.cache={};self.videos={};self.seconds=0;self.output_size=(1080,1920)
    def clear(self):
        self.layers=[]
        for player,sink,image in self.videos.values():player.stop();player.deleteLater();sink.deleteLater()
        self.videos.clear();self.cache.clear();self.update();self.hide()
    def set_layers(self,layers,seconds,size,playing=False):
        self.layers=layers;self.seconds=seconds;self.output_size=size
        paths={str(x.get('path','')) for x in layers if x.get('enabled',True)}
        for path in list(self.videos):
            if path not in paths:
                player,sink,image=self.videos.pop(path);player.stop();player.deleteLater();sink.deleteLater()
        for item in layers:
            path=str(item.get('path',''))
            if not item.get('enabled',True) or not path:continue
            if Path(path).suffix.lower() in ('.mp4','.mov','.webm'):
                if path not in self.videos:
                    player=QMediaPlayer(self);sink=QVideoSink(self);player.setVideoSink(sink)
                    self.videos[path]=[player,sink,QImage()]
                    def frame_changed(frame,p=path):
                        if p in self.videos:self.videos[p][2]=frame.toImage();self.update()
                    sink.videoFrameChanged.connect(frame_changed);player.setSource(QUrl.fromLocalFile(path))
                player=self.videos[path][0];duration=player.duration()
                target=int(seconds*1000)%duration if duration>0 else int(seconds*1000)
                if abs(player.position()-target)>150:player.setPosition(target)
                if playing:player.play()
                else:player.pause()
        self.setVisible(bool(paths));self.update()
    def frame(self,item):
        path=str(item.get('path',''))
        if path in self.videos:return self.videos[path][2]
        try:
            stat=Path(path).stat();key=(path,stat.st_mtime_ns,bool(item.get('knockout')))
            if key not in self.cache:
                source=path
                if item.get('knockout'):
                    from app.services.packaging_watermark import prepare_knockout
                    source=prepare_knockout(path)
                if Path(source).suffix.lower()=='.gif':
                    from app.services.packaging_watermark import gif_frames
                    frames,duration=gif_frames(source)
                    self.cache[key]=([(f,QImage(f['path'])) for f in frames],duration)
                else:self.cache[key]=QImage(source)
            value=self.cache[key]
            if isinstance(value,tuple):
                frames,duration=value;now=self.seconds%max(.02,duration)
                return next((im for f,im in frames if f['start']<=now<f['end']),QImage())
            return value
        except (OSError,ValueError):return QImage()
    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHint(QPainter.SmoothPixmapTransform)
        ow,oh=self.output_size;sx=self.width()/max(1,ow);sy=self.height()/max(1,oh)
        for item in self.layers:
            if not item.get('enabled',True):continue
            image=self.frame(item)
            if image.isNull():continue
            if item.get('mode')=='全屏覆盖':
                scale=min(ow/image.width(),oh/image.height());w=image.width()*scale;h=image.height()*scale;x=(ow-w)/2;y=(oh-h)/2
            else:
                w=max(2,ow*float(item.get('scale',18))/100);h=w*image.height()/image.width()
                margin=max(0,float(item.get('margin',24)));pos=item.get('position','右上')
                x=(ow-w)/2 if pos=='居中' else margin if '左' in pos else ow-w-margin
                y=(oh-h)/2 if pos=='居中' else oh-h-margin if '下' in pos else margin
            painter.setOpacity(max(0,min(1,float(item.get('opacity',90))/100)))
            painter.drawImage(QRectF(x*sx,y*sy,w*sx,h*sy),image)
        painter.end()
