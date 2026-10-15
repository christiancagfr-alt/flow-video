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


FULL_SCROLL = '持续向上滚动'
BAND_SCROLL = '中间固定滚动'
CUSTOM_SCROLL = '自定义区域滚动'
SCROLL_ANIMATIONS = (FULL_SCROLL, BAND_SCROLL, CUSTOM_SCROLL)


def scroll_band(style, canvas_h=1920):
    """Fixed middle window. Text is clipped here and does not travel off the frame."""
    style = style or {}
    animation = style.get('free_animation')
    if animation == CUSTOM_SCROLL:
        top_pct = max(0.0, min(99.0, float(style.get('scroll_area_top', 20))))
        bottom_pct = max(1.0, min(100.0, float(style.get('scroll_area_bottom', 80))))
        if bottom_pct <= top_pct:
            bottom_pct = min(100.0, top_pct + 1.0)
        top = int(round(int(canvas_h) * top_pct / 100.0))
        bottom = int(round(int(canvas_h) * bottom_pct / 100.0))
        height = max(1, bottom - top)
        return {'top': top, 'height': height, 'fade': max(1, int(round(height * 0.08)))}
    if animation != BAND_SCROLL:
        return None
    height = int(round(canvas_h * 0.42))
    height = max(360, min(int(canvas_h) - 200, height))
    top = (int(canvas_h) - height) // 2
    fade = max(36, int(round(height * 0.08)))
    return {'top': top, 'height': height, 'fade': fade}


def scroll_positions(style, canvas_h=1920, image_h=0):
    """Return the custom scroll image's starting and ending Y positions in canvas pixels."""
    style = style or {}
    start = int(round(int(canvas_h) * float(style.get('scroll_start_y', 100)) / 100.0))
    if style.get('scroll_end_auto', True):
        end = -max(1, int(image_h))
    else:
        end = int(round(int(canvas_h) * float(style.get('scroll_end_y', -100)) / 100.0))
    return start, end


def scroll_offset(progress, view_h, image_h):
    progress = max(0.0, min(1.0, float(progress)))
    return view_h - (view_h + image_h) * progress


def paint_at(captions,style,time):
    load_caption_fonts()
    if style.get('free_animation') in SCROLL_ANIMATIONS and captions:
        from PySide6.QtGui import QImage,QPainter,QLinearGradient,QColor
        from PySide6.QtCore import Qt
        text='\n'.join(c['text'] for c in captions)
        scroll=scroll_image(text,json.dumps(style,sort_keys=True))
        start=float(captions[0]['start']);end=float(captions[-1]['end'])
        canvas=QImage(1080,1920,QImage.Format_ARGB32_Premultiplied);canvas.fill(Qt.transparent)
        if start<=time<end:
            progress=(time-start)/max(.001,end-start)
            band=scroll_band(style)
            painter=QPainter(canvas);painter.setRenderHint(QPainter.Antialiasing,True)
            if band:
                if style.get('free_animation') == CUSTOM_SCROLL:
                    start_y,end_y=scroll_positions(style,1920,scroll.height())
                    y=start_y+(end_y-start_y)*max(0.0,min(1.0,float(progress)))
                else:
                    y=band['top']+scroll_offset(progress,band['height'],scroll.height())
                painter.setClipRect(0,band['top'],1080,band['height'])
                painter.drawImage(0,int(y),scroll)
                fade=QImage(1080,band['height'],QImage.Format_ARGB32_Premultiplied);fade.fill(Qt.transparent)
                fade_painter=QPainter(fade)
                gradient=QLinearGradient(0,0,0,band['height'])
                edge=min(band['fade'],band['height']//3)/band['height']
                gradient.setColorAt(0,QColor(0,0,0,0))
                gradient.setColorAt(edge,QColor(0,0,0,255))
                gradient.setColorAt(1-edge,QColor(0,0,0,255))
                gradient.setColorAt(1,QColor(0,0,0,0))
                fade_painter.fillRect(0,0,1080,band['height'],gradient);fade_painter.end()
                painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
                painter.drawImage(0,band['top'],fade)
            else:
                y=scroll_offset(progress,1920,scroll.height())
                painter.drawImage(0,int(y),scroll)
            painter.end()
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
    if style.get('free_animation') in SCROLL_ANIMATIONS:
        image=scroll_image('\n'.join(c['text'] for c in captions),json.dumps(style,sort_keys=True))
        path=directory/'scroll.png'
        if not image.save(str(path),'PNG'):raise RuntimeError('无法保存滚动字幕')
        start=max(0,math.ceil(float(captions[0]['start'])*fps));end=min(math.ceil(duration*fps),math.ceil(float(captions[-1]['end'])*fps))
        layer={'path':str(path),'start':start,'duration':max(1,end-start),'scroll':True,'imageHeight':image.height()}
        band=scroll_band(style)
        if band:layer['scrollBand']=band
        if style.get('free_animation') == CUSTOM_SCROLL:
            start_y,end_y=scroll_positions(style,1920,image.height())
            layer['scrollPath']={'startY':start_y,'endY':end_y}
        payload['captionOverlays']=[layer]
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
