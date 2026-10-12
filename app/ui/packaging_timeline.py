"""Time-scaled packaging tracks with seeking and subtitle selection."""
from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtWidgets import QWidget


class PackagingTimeline(QWidget):
    seekRequested = Signal(int)
    captionSelected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = {}; self.seconds = 0.; self.zoom = 100; self.hits = []
        self.setMinimumHeight(108)
        self.setMouseTracking(True)

    def set_state(self, state):
        self.state = state or {}
        self.active_tracks=[0,1,2]
        if (self.state.get('title') or {}).get('enabled'):self.active_tracks.append(3)
        if any(w.get('enabled',True) for w in self.state.get('watermarks',[])):self.active_tracks.append(4)
        if self.state.get('broll'):self.active_tracks.append(5)
        if any((self.state.get(k) or {}).get('enabled') for k in ('intro','outro')):self.active_tracks.append(6)
        self.setMinimumHeight(28+26*len(self.active_tracks));self.update()

    def set_position(self, seconds):
        self.seconds = seconds; self.update()

    def set_zoom(self, value):
        self.zoom = value
        self.setMinimumWidth(max(0, int(850*value/100)) if value>100 else 0)
        self.update()

    def paintEvent(self, event):
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing)
        dark=self.palette().window().color().lightness()<128
        p.fillRect(self.rect(),QColor('#171E29' if dark else '#f8faff'))
        left=94; width=max(1,self.width()-left-12); height=26
        main_duration=max(.1,float(self.state.get('duration') or 0),max((float(c.get('end',0)) for c in self.state.get('captions',[])),default=0))
        intro=self.state.get('intro') or {};outro=self.state.get('outro') or {}
        self.offset=float(intro.get('duration',0)) if intro.get('enabled') and intro.get('path') else 0
        tail=float(outro.get('duration',0)) if outro.get('enabled') and outro.get('path') else 0
        duration=self.offset+main_duration+tail
        self.duration=duration;self.track_width=width;self.hits=[]
        labels=['视频','音频','字幕','标题','水印','B-roll','片头 / 片尾']
        p.setPen(QColor('#AFC1DA' if dark else '#526176'))
        for i in range(11):
            x=left+width*i/10;p.drawLine(int(x),22,int(x),self.height())
            sec=duration*i/10;p.drawText(QRectF(x-20,0,50,22),Qt.AlignCenter,f'{int(sec//60):02}:{sec%60:04.1f}')
        active=getattr(self,'active_tracks',[0,1,2])
        for i,track in enumerate(active):
            label=labels[track]
            y=24+i*height
            p.fillRect(QRectF(0,y,left-3,height),QColor('#232D3C' if dark else '#eef3fa'))
            p.setPen(QColor('#EEF3FC' if dark else '#354663'));p.drawText(QRectF(6,y,left-8,height),Qt.AlignVCenter,label)
        def block(track,start,end,text,color,index=None,absolute=False):
            if track not in active:return
            track=active.index(track)
            if not absolute:start+=self.offset;end+=self.offset
            start=max(0,min(duration,float(start)));end=max(start,min(duration,float(end)))
            if end<=start:return
            rect=QRectF(left+start/duration*width,27+track*height,max(3,(end-start)/duration*width-2),20)
            p.setPen(Qt.NoPen);p.setBrush(QColor(color));p.drawRoundedRect(rect,3,3)
            p.setPen(QColor('#ffffff'));p.drawText(rect.adjusted(5,0,-3,0),Qt.AlignVCenter,p.fontMetrics().elidedText(text,Qt.ElideRight,max(1,int(rect.width()-8))))
            self.hits.append((rect,index,text))
        if self.state:
            from pathlib import Path
            block(0,0,main_duration,Path(self.state.get('source','')).name,'#4478bf')
            block(1,0,main_duration,'原视频音轨','#31877d')
            for i,c in enumerate(self.state.get('captions',[])):block(2,c['start'],c['end'],c['text'],'#8965bd',i)
            title=self.state.get('title') or {}
            if title.get('enabled'):block(3,0,main_duration,title.get('text','标题'),'#b78030')
            wm=[w for w in self.state.get('watermarks',[]) if w.get('enabled',True)]
            if wm:block(4,0,main_duration,f'{len(wm)} 层水印','#4f8da2')
            for b in self.state.get('broll',[]):block(5,b.get('start',0),b.get('end',duration),Path(b.get('path','')).name,'#ba7386')
            for key,start in [('intro',0),('outro',max(0,duration-float((self.state.get('outro') or {}).get('duration',0))))]:
                clip=self.state.get(key) or {}
                if clip.get('enabled') and clip.get('path'):block(6,start,start+float(clip.get('duration',0)),('片头' if key=='intro' else '片尾'),'#79849b',absolute=True)
        p.setPen(QPen(QColor('#e84f62'),2));x=left+min(duration,max(0,self.seconds+self.offset))/duration*width
        p.drawLine(int(x),20,int(x),self.height())

    def mousePressEvent(self,event):
        if event.button()!=Qt.LeftButton:return
        for rect,index,text in self.hits:
            if rect.contains(event.position()) and index is not None:self.captionSelected.emit(index);break
        if event.position().x()>=94:
            seconds=max(0,min(1,(event.position().x()-94)/max(1,getattr(self,'track_width',1))))*getattr(self,'duration',0)
            self.seekRequested.emit(int(max(0,seconds-getattr(self,'offset',0))*1000))

    def mouseMoveEvent(self,event):
        self.setToolTip(next((text for rect,index,text in self.hits if rect.contains(event.position())), '点击定位播放位置'))
