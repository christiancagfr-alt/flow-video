"""Native packaging: Qt caption states + FFmpeg, without Chromium.

The transparent-state approach follows video-toolkit's caption_qt_burn module;
we feed its timed PNG sequence directly, avoiding a second intermediate MOV encode.
"""
import copy
import math
from pathlib import Path
from app.services import quiet_process as process
from app.services.packaging_media import find_ffmpeg, probe_media
from app.services.packaging_overlay import prepare_overlays

IMAGES={'.png','.jpg','.jpeg','.webp','.bmp'}


def resolve_duration(payload):
    if float(payload.get('mainDuration') or 0)>0:return
    duration=probe_media(payload['source'],payload.get('ffmpeg',''))['duration']
    if duration<=0:raise ValueError('无法读取视频时长，已停止此任务。')
    payload['mainDuration']=duration
    payload['totalDuration']=duration+sum(float((payload.get(k) or {}).get('duration',0))
        for k in ('intro','outro') if (payload.get(k) or {}).get('enabled') and (payload.get(k) or {}).get('path'))


def compatibility_reason(payload):
    # Do not silently approximate legacy CSS animation/typography with ASS.
    if payload.get('captions') and not payload.get('reelsStyle'):
        return '原有 CSS 字幕样式；选择 Reels 字幕样式后可使用快速渲染'
    if (payload.get('reelsStyle') or {}).get('free_animation') in ('持续向上滚动', '中间固定滚动'):
        return '连续滚动字幕'
    if (payload.get('watermark') or {}).get('enabled'):
        return '旧版水印'
    return ''


def concat_path(path):
    return "file '"+str(Path(path).resolve()).replace('\\','/').replace("'", "'\\''")+"'"


def caption_sequence(payload, work):
    from PySide6.QtGui import QImage
    from PySide6.QtCore import Qt
    prepared=prepare_overlays(copy.deepcopy(payload),work/'captions')
    layers=prepared.get('captionOverlays') or []
    if not layers:return None
    blank=work/'blank.png';image=QImage(1080,1920,QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent);image.save(str(blank));del image
    fps=int(payload.get('fps',30));end=math.ceil(float(payload['mainDuration'])*fps)
    cursor=0;lines=[];last=blank
    def add(path,frames):
        if frames>0:lines.extend([concat_path(path),'option framerate '+str(fps),f'duration {frames/fps:.9f}'])
    for layer in layers:
        start=max(cursor,int(layer['start']));stop=min(end,int(layer['start']+layer['duration']))
        add(blank,start-cursor);add(layer['path'],stop-start);cursor=stop;last=layer['path']
    if cursor<end:add(blank,end-cursor);last=blank
    lines.extend([concat_path(last),'option framerate '+str(fps)])
    result=work/'captions.ffconcat';result.write_text('\n'.join(lines)+'\n','utf-8')
    return result


def title_image(title, width, height, work):
    from PySide6.QtGui import QImage,QPainter,QColor,QFont,QTextDocument
    from PySide6.QtCore import Qt,QRectF
    import html
    from app.services.packaging_overlay import load_caption_fonts
    load_caption_fonts()
    image=QImage(width,height,QImage.Format_ARGB32_Premultiplied);image.fill(Qt.transparent)
    doc=QTextDocument();font=QFont('Arial');font.setPixelSize(int(title.get('size',58)));font.setBold(True)
    doc.setDefaultFont(font);doc.setDocumentMargin(0);doc.setTextWidth(width*.86-44)
    doc.setHtml('<div align="center" style="color:'+QColor(title.get('color','#FFFFFF')).name()+'">'+html.escape(title.get('text','')).replace('\n','<br>')+'</div>')
    h=doc.size().height()+28;w=doc.textWidth()+44;position=title.get('position','顶部居中')
    x=48 if '左' in position else width-w-48 if '右' in position else (width-w)/2
    y=60 if ('顶' in position or '上' in position) else height-h-80 if ('底' in position or '下' in position) else (height-h)/2
    painter=QPainter(image);painter.setRenderHint(QPainter.Antialiasing)
    if title.get('background'):painter.setPen(Qt.NoPen);painter.setBrush(QColor(0,0,0,133));painter.drawRoundedRect(QRectF(x,y,w,h),18,18)
    painter.translate(x+22,y+14);doc.drawContents(painter);painter.end()
    result=work/'title.png';image.save(str(result));return result


def encoder_args(ffmpeg, codec, hardware=True):
    if codec=='prores':return ['-c:v','prores_ks','-profile:v','3','-pix_fmt','yuv422p10le','-threads','2'],'ProRes HQ'
    if codec=='vp9':return ['-c:v','libvpx-vp9','-crf','18','-b:v','0','-row-mt','1','-threads','2'],'VP9'
    if hardware:
        candidate=['-c:v','h264_nvenc','-preset','p5','-rc','vbr','-cq','16','-b:v','0','-pix_fmt','yuv420p']
        try:
            probe=process.run([ffmpeg,'-v','error','-f','lavfi','-i','color=s=320x180:r=1',
                '-frames:v','1',*candidate,'-f','null','-'],capture_output=True,timeout=15)
            if probe.returncode==0:return candidate,'NVIDIA · CQ16'
        except Exception:pass
    return ['-c:v','libx264','-preset','veryfast','-crf','16','-pix_fmt','yuv420p','-threads','2'],'CPU · CRF16'


def build_command(payload, output, work, encoding, preview_frame=None):
    """One graph, one final encode; audio is normalized only for concatenation."""
    ffmpeg=find_ffmpeg(payload.get('ffmpeg',''));w=int(payload.get('width',1080));h=int(payload.get('height',1920));fps=int(payload.get('fps',30))
    duration=math.ceil(float(payload['mainDuration'])*fps)/fps
    command=[ffmpeg,'-hide_banner','-loglevel','warning','-y','-filter_complex_threads','1']
    filters=[];index=0
    def source(path,loop=False):
        nonlocal index
        number=index;index+=1
        if Path(path).suffix.lower() in IMAGES:command.extend(['-loop','1','-framerate',str(fps)])
        elif loop:command.extend(['-stream_loop','-1'])
        command.extend(['-threads','1','-i',str(path)]);return number
    def fit(mode):
        return (f'scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,crop={w}:{h}' if mode=='cover'
            else f'scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black')
    def normalized(number,seconds,label,mode='cover'):
        filters.append(f'[{number}:v]setpts=PTS-STARTPTS,{fit(mode)},setsar=1,fps={fps},tpad=stop_mode=clone:stop_duration={seconds},trim=duration={seconds},settb=AVTB[{label}]')
    main=source(payload['source']);normalized(main,duration,'main',payload.get('fit','contain'));current='main';counter=0
    def overlay(video,x='0',y='0',extra=''):
        nonlocal current,counter
        counter+=1;out=f'over{counter}'
        filters.append(f'[{current}][{video}]overlay=x={x}:y={y}:eof_action=pass:format=auto{extra}[{out}]');current=out
    for b in payload.get('broll') or []:
        if not b.get('path'):continue
        start=max(0,float(b.get('start',0)));end=min(duration,float(b.get('end',duration)))
        if end<=start:continue
        number=source(b['path']);label=f'br{number}';normalized(number,end-start,label,b.get('fit','cover'))
        filters.append(f'[{label}]setpts=PTS+{start}/TB[{label}t]');overlay(label+'t',extra=f":enable='gte(t,{start})*lt(t,{end})'")
    for item in payload.get('watermarks') or []:
        if not item.get('enabled',True) or not item.get('path'):continue
        path=item['path']
        if item.get('knockout'):
            from app.services.packaging_watermark import prepare_knockout
            path=prepare_knockout(path)
        number=source(path,True);label=f'wm{number}';margin=max(0,int(item.get('margin',24)))
        if item.get('mode')=='全屏覆盖':
            scale=f'scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos';x='(W-w)/2';y='(H-h)/2'
        else:
            scale=f'scale={max(2,int(w*float(item.get("scale",18))/100))}:-1:flags=lanczos';pos=item.get('position','右上')
            x='(W-w)/2' if pos=='居中' else str(margin) if '左' in pos else f'W-w-{margin}'
            y='(H-h)/2' if pos=='居中' else f'H-h-{margin}' if '下' in pos else str(margin)
        alpha=max(0,min(1,float(item.get('opacity',90))/100))
        filters.append(f'[{number}:v]setpts=PTS-STARTPTS,{scale},format=rgba,colorchannelmixer=aa={alpha}[{label}]');overlay(label,x,y)
    title=payload.get('title') or {}
    if title.get('enabled') and title.get('text'):
        number=source(title_image(title,w,h,work));overlay(f'{number}:v')
    captions=caption_sequence(payload,work)
    if captions:
        number=index;index+=1;command.extend(['-f','concat','-safe','0','-i',str(captions)])
        scale=min(w/1080,h/1920);cw=max(2,round(1080*scale));ch=max(2,round(1920*scale))
        filters.append(f'[{number}:v]setpts=PTS-STARTPTS,scale={cw}:{ch}:flags=lanczos,format=rgba[cap]')
        overlay('cap','(W-w)/2','(H-h)/2')
    pieces=[];audio=[]
    for key in ('intro','main','outro'):
        clip=payload.get(key) or {}
        if key=='main':number=main;seconds=duration;video=current;path=payload['source']
        else:
            if not clip.get('enabled') or not clip.get('path'):continue
            seconds=max(1,round(float(clip.get('duration',2))*fps))/fps;path=clip['path'];number=source(path);video=key;normalized(number,seconds,video)
        alabel=f'a{key}'
        has_audio=Path(path).suffix.lower() not in IMAGES and probe_media(path,ffmpeg)['audio']
        chain=f'[{number}:a]aresample=48000,aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS,apad' if has_audio else 'anullsrc=r=48000:cl=stereo'
        filters.append(f'{chain},atrim=duration={seconds},asetpts=PTS-STARTPTS[{alabel}]')
        pieces.append(f'[{video}][{alabel}]');audio.append(seconds)
    filters.append(''.join(pieces)+f'concat=n={len(pieces)}:v=1:a=1[finalv][finala]')
    graph=work/'graph.txt';graph.write_text(';\n'.join(filters),'utf-8')
    command.extend(['-filter_complex_script',str(graph),'-map','[finalv]'])
    if preview_frame is not None:
        command.extend(['-ss',str(max(0,int(preview_frame))/fps),'-frames:v','1','-update','1','-an','-c:v','png','-threads','1'])
        # An unmapped complex audio output must be explicitly consumed.
        graph.write_text(';\n'.join(filters)+';[finala]anullsink','utf-8')
    else:
        command.extend(['-map','[finala]',*encoding,'-c:a','libopus' if payload.get('codec')=='vp9' else 'aac','-b:a','192k','-t',str(sum(audio))])
        if payload.get('codec','h264')=='h264':command.extend(['-movflags','+faststart'])
    command.extend(['-progress','pipe:1','-nostats',str(output)])
    return command,sum(audio)
