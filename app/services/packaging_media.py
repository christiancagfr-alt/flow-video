"""Packaging output rules shared by preview, project persistence and rendering."""
from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
from pathlib import Path
from app.services import quiet_process as subprocess
from app.services.reels.captions import parse_srt, events_to_srt, group_word_srt


def find_ffmpeg(configured=''):
    path = Path(configured).expanduser() if configured else None
    if path and path.is_file():
        return str(path.resolve())
    result = shutil.which('ffmpeg')
    if result:
        return result
    from app.services.app_paths import data_dir
    folder=data_dir()/'packaging/ffmpeg-libs/imageio_ffmpeg/binaries'
    for candidate in folder.glob('ffmpeg-*'):
        if candidate.is_file() and candidate.suffix not in ('.txt','.md'):return str(candidate)
    raise ValueError('请在侧边栏“组件管理”中安装或选择 FFmpeg。')


def probe_media(path, ffmpeg=''):
    ffmpeg = find_ffmpeg(ffmpeg)
    sibling = Path(ffmpeg).with_name('ffprobe.exe' if Path(ffmpeg).suffix == '.exe' else 'ffprobe')
    probe = str(sibling) if sibling.is_file() else shutil.which('ffprobe')
    if not probe:
        cp=subprocess.run([ffmpeg,'-hide_banner','-i',str(Path(path).resolve())],capture_output=True,
            text=True,encoding='utf-8',errors='replace',timeout=30)
        detail=cp.stderr or ''
        duration=re.search(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)',detail)
        video_line=next((line for line in detail.splitlines() if 'Video:' in line),'')
        size=re.search(r'\b(\d{2,5})x(\d{2,5})\b',video_line)
        if not duration:raise ValueError('无法读取媒体时长，请检查文件或安装 FFprobe。')
        return {'width':int(size[1]) if size else 1080,'height':int(size[2]) if size else 1920,
            'duration':int(duration[1])*3600+int(duration[2])*60+float(duration[3]),'audio':'Audio:' in detail}
    cp = subprocess.run([probe, '-v', 'error', '-show_streams', '-show_format', '-of', 'json',
                         str(Path(path).resolve())], capture_output=True, text=True, encoding='utf-8',
                        timeout=30, check=True)
    data = json.loads(cp.stdout)
    video = next((s for s in data.get('streams', []) if s.get('codec_type') == 'video'), {})
    duration = float(data.get('format', {}).get('duration') or video.get('duration') or 0)
    return {'width': int(video.get('width') or 1080), 'height': int(video.get('height') or 1920),
            'duration': duration, 'audio': any(s.get('codec_type') == 'audio' for s in data.get('streams', []))}


def output_size(ratio='9:16', resolution='1080p', source=(1080, 1920)):
    w, h = source
    if ratio != '原始比例':
        ratios = {'9:16': (9,16), '16:9': (16,9), '1:1': (1,1), '4:5': (4,5), '4:3': (4,3)}
        w, h = ratios.get(ratio, (9,16))
    if resolution == '默认最高':
        short = min(source)
    else:
        short = {'720p':720, '1080p':1080, '2K':1440, '4K':2160}.get(resolution,1080)
    scale = short / max(1, min(w,h))
    return max(2,round(w*scale/2)*2), max(2,round(h*scale/2)*2)


def clean_name(text):
    text = re.sub(r'[\x00-\x1f<>:"/\\|?*]', '_', str(text)).strip(' .')
    if re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', text):
        text = '_' + text
    return text


def output_basename(source, params, index=0, caption=''):
    if not params.get('rename_enabled'):
        return clean_name(Path(source).stem) + '_packaged'
    titles = str(params.get('rename_titles') or '').splitlines()
    title = titles[index].strip() if index < len(titles) else ''
    title = title or caption.splitlines()[0] if caption else title
    title = title or Path(source).stem
    number = max(0,int(params.get('rename_start',1))) + index
    padding = max(1,min(12,int(params.get('rename_padding',3))))
    parts = [str(number).zfill(padding), params.get('rename_prefix',''), title,
             params.get('rename_date','') if params.get('rename_date_enabled') else '',
             params.get('rename_suffix','') if params.get('rename_suffix_enabled') else '']
    name = '-'.join(clean_name(x).strip('-') for x in parts if clean_name(x).strip('-'))
    if len(name) > 150:
        name = name[:137].rstrip(' .') + '-' + hashlib.sha256(name.encode()).hexdigest()[:12]
    return name


def available_output(directory, basename, extension, reserved=()):
    root = Path(directory).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    extension = extension if extension in ('mp4','mov','webm') else 'mp4'
    used = {str(Path(p).resolve()).casefold() for p in reserved}
    for number in range(100000):
        tail = '' if number == 0 else f'_{number+1}'
        path = root / f'{clean_name(basename)}{tail}.{extension}'
        if not path.exists() and str(path).casefold() not in used:
            return str(path)
    raise ValueError('输出目录存在太多同名文件，请更换命名规则。')


def captions_to_srt(captions, words=False):
    rows = [w for c in captions for w in c.get('words', [])] if words else captions
    return events_to_srt([(float(c['start']),float(c['end']),c['text']) for c in rows])


def captions_from_srt(srt, word_srt=''):
    words = parse_srt(word_srt) if word_srt else []
    return [dict(start=s,end=e,text=t,words=[dict(start=max(s,ws),end=min(e,we),text=wt)
            for ws,we,wt in words if ws < e and we > s]) for s,e,t in parse_srt(srt)]


def validate_captions(captions):
    last = 0.
    for i,c in enumerate(captions,1):
        start,end = float(c['start']),float(c['end'])
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
            raise ValueError(f'第 {i} 条字幕时间无效，请检查开始和结束时间。')
        if start < last - .001:
            raise ValueError(f'第 {i} 条字幕与上一条重叠，请先校对时间。')
        last = end


def recognition_result(srt, raw, max_words=7):
    words = raw.get('words') or (raw.get('response') or {}).get('words') or []
    if not words:
        utterances = (raw.get('response') or {}).get('result', {}).get('transcription', {}).get('utterances', [])
        words = [w for u in utterances for w in u.get('words', [])]
    timed = []
    for w in words:
        text = str(w.get('text') or w.get('word') or '').strip()
        if text and w.get('start') is not None and w.get('end') is not None:
            timed.append((float(w['start']),float(w['end']),text))
    from app.services.reels.captions import ensure_word_level_srt, align_word_srt_to_phrase_srt
    if timed:
        word_srt,estimated=events_to_srt(timed),False
    else:
        word_srt,estimated=ensure_word_level_srt(srt,srt)
    phrases = group_word_srt(word_srt, max_chars=42, max_duration=4.6, max_words=max_words)
    word_srt = align_word_srt_to_phrase_srt(word_srt, phrases)
    captions = captions_from_srt(phrases, word_srt)
    validate_captions(captions)
    if not captions:
        raise ValueError('没有识别到有效字幕，请检查音轨、语言或更换识别模型。')
    return captions, estimated or not bool(timed)
