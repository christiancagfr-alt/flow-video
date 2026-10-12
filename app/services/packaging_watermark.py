from __future__ import annotations
import hashlib
from pathlib import Path
from PIL import Image, ImageSequence
from app.services.app_paths import data_dir


def prepare_knockout(source):
    path=Path(source).resolve(strict=True)
    if path.suffix.lower() not in ('.png','.jpg','.jpeg','.webp','.gif','.bmp'):
        raise ValueError('自动去黑白底适用于图片或 GIF；视频水印请使用已经透明的视频。')
    key=hashlib.sha256(f'{path}:{path.stat().st_mtime_ns}:{path.stat().st_size}'.encode()).hexdigest()[:24]
    directory=data_dir()/'packaging/watermarks';directory.mkdir(parents=True,exist_ok=True)
    with Image.open(path) as original:
        animated=bool(getattr(original,'is_animated',False))
        destination=directory/(key+('.gif' if animated else '.png'))
        if destination.is_file():return str(destination)
        frames=[];durations=[]
        for frame in ImageSequence.Iterator(original):
            image=frame.convert('RGBA')
            if image.getchannel('A').getextrema()[0]==255:
                pixels=[(r,g,b,0 if (max(r,g,b)<=28 or min(r,g,b)>=250) else a) for r,g,b,a in image.getdata()]
                image.putdata(pixels)
            frames.append(image);durations.append(frame.info.get('duration',100))
        if animated:frames[0].save(destination,save_all=True,append_images=frames[1:],duration=durations,loop=0,disposal=2)
        else:frames[0].save(destination)
    return str(destination)


def gif_frames(source):
    path=Path(source).resolve(strict=True)
    key=hashlib.sha256(f'{path}:{path.stat().st_mtime_ns}:{path.stat().st_size}'.encode()).hexdigest()[:24]
    folder=data_dir()/'packaging/watermarks'/key;folder.mkdir(parents=True,exist_ok=True)
    frames=[];cursor=0.
    with Image.open(path) as image:
        for index,frame in enumerate(ImageSequence.Iterator(image)):
            target=folder/f'{index}.png'
            if not target.exists():frame.convert('RGBA').save(target)
            duration=max(.02,float(frame.info.get('duration',100))/1000)
            frames.append({'path':str(target),'start':cursor,'end':cursor+duration})
            cursor+=duration
    return frames,cursor
