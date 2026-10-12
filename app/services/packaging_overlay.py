"""Use Reels' original Qt painter for both preview and exported overlays."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
from app.services.packaging_media import captions_to_srt
from app.services.reels.caption_qt_burn import paint_caption_overlay_image, collect_caption_cut_times
from functools import lru_cache


@lru_cache(maxsize=1)
def load_caption_fonts():
    # Qt's offscreen platform on Windows does not enumerate system fonts itself.
    import os,sys
    from PySide6.QtGui import QFontDatabase
    if sys.platform=='win32':
        root=Path(os.environ.get('WINDIR',r'C:\Windows'))/'Fonts'
        for name in ('arial.ttf','arialbd.ttf','ariblk.ttf','segoeui.ttf','segoeuib.ttf','msyh.ttc'):
            path=root/name
            if path.is_file():QFontDatabase.addApplicationFont(str(path))


def paint_settings(raw):
    settings=dict(raw)
    for old,new in [('text','text_color'),('outline','outline_color'),('highlight','highlight_color'),
                    ('background','background_color'),('active_text','active_text_color')]:
        if old in raw:settings[new]=raw[old]
    return settings


def paint_at(captions,style,time):
    load_caption_fonts()
    if style.get('free_animation')=='持续向上滚动' and captions:
        from PySide6.QtGui import QImage,QPainter
        from PySide6.QtCore import Qt
        text='\n'.join(c['text'] for c in captions)
        scroll=scroll_image(text,json.dumps(style,sort_keys=True))
        start=float(captions[0]['start']);end=float(captions[-1]['end'])
        canvas=QImage(1080,1920,QImage.Format_ARGB32_Premultiplied);canvas.fill(Qt.transparent)
        if start<=time<end:
            y=1920-(1920+scroll.height())*((time-start)/max(.001,end-start))
            painter=QPainter(canvas);painter.drawImage(0,int(y),scroll);painter.end()
        return canvas
    return paint_caption_overlay_image(paint_settings(style),captions_to_srt(captions),
                                      captions_to_srt(captions,True),time)


@lru_cache(maxsize=4)
def scroll_image(text,style_json):
    from PySide6.QtGui import QImage,QPainter,QPainterPath,QPen,QColor
    from PySide6.QtCore import Qt
    from app.services.reels.layout import caption_layout_context,caption_wrapped_lines
    style=paint_settings(json.loads(style_json));font,metrics,gap,line_gap,_=caption_layout_context(style)
    lines=caption_wrapped_lines(text,style)
    height=max(100,math.ceil(line_gap*len(lines)+100))
    image=QImage(1080,height,QImage.Format_ARGB32_Premultiplied);image.fill(Qt.transparent)
    painter=QPainter(image);painter.setRenderHint(QPainter.Antialiasing,True)
    for i,line in enumerate(lines):
        text=' '.join(line);width=metrics.horizontalAdvance(text)
        path=QPainterPath();path.addText((1080-width)/2,50+metrics.ascent()+i*line_gap,font,text)
        painter.setPen(QPen(QColor(style.get('outline_color','#111111')),2*float(style.get('outline_width',3)),Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin))
        painter.setBrush(QColor(style.get('text_color','#FFFFFF')));painter.drawPath(path)
    painter.end();return image


def prepare_overlays(payload,root):
    load_caption_fonts()
    captions=payload.get('captions') or []
    style=payload.get('reelsStyle') or {}
    if not captions or not style:return payload
    fps=int(payload.get('fps',30));duration=float(payload['mainDuration'])
    settings=paint_settings(style)
    phrase=captions_to_srt(captions);words=captions_to_srt(captions,True)
    cuts=collect_caption_cut_times(phrase,words,duration,settings)
    frames=sorted({max(0,min(math.ceil(duration*fps),math.ceil(t*fps-1e-7))) for t in cuts})
    key=hashlib.sha256(json.dumps([3,style,captions,fps],ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:24]
    directory=Path(root)/key;directory.mkdir(parents=True,exist_ok=True)
    if style.get('free_animation')=='持续向上滚动':
        image=scroll_image('\n'.join(c['text'] for c in captions),json.dumps(style,sort_keys=True))
        path=directory/'scroll.png'
        if not image.save(str(path),'PNG'):raise RuntimeError('无法保存滚动字幕')
        start=max(0,math.ceil(float(captions[0]['start'])*fps));end=min(math.ceil(duration*fps),math.ceil(float(captions[-1]['end'])*fps))
        payload['captionOverlays']=[{'path':str(path),'start':start,'duration':max(1,end-start),'scroll':True,'imageHeight':image.height()}]
        payload['captions']=[];payload['_reels_prepared']=True;return payload
    layers=[]
    for index,(start,end) in enumerate(zip(frames,frames[1:])):
        if end<=start:continue
        t=start/fps+.00001
        if not any(c['start']<=t<c['end'] for c in captions):continue
        path=directory/f'{start}-{end}.png'
        if not path.is_file():
            image=paint_caption_overlay_image(settings,phrase,words,t)
            if not image.save(str(path),'PNG'):raise RuntimeError('无法写入字幕效果图片。')
        layers.append({'path':str(path),'start':start,'duration':end-start})
        if index%25==0:print(f'准备字幕效果 {index+1}/{len(frames)-1}',flush=True)
    payload['captionOverlays']=layers
    payload['captions']=[]
    payload['_reels_prepared']=True
    return payload
