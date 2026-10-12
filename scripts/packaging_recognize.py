"""Isolated, cancellable ASR process. Credentials arrive via stdin, never argv/files."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json
import os
import tempfile
from app.services.app_paths import data_dir
from app.services.bundled_components import restore
restore()
libraries=data_dir()/'packaging/asr-libs'
if libraries.is_dir():sys.path.insert(0,str(libraries))
from app.services import quiet_process as subprocess
from app.services.packaging_media import find_ffmpeg, recognition_result, probe_media
from app.services.reels.recognition_engine import TranscribeWorker, LOCAL_PROVIDER
os.environ.setdefault('HF_HOME',str(data_dir()/'packaging/models'))
if sys.stdout:sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr:sys.stderr.reconfigure(encoding='utf-8')


def main():
    from app.services.bundled_components import restore
    restore()
    config = json.loads(sys.stdin.readline())
    provider = config['provider']
    source = Path(config['source']).resolve(strict=True)
    ffmpeg = find_ffmpeg(config.get('ffmpeg',''))
    metadata=probe_media(source,ffmpeg)
    if not metadata['audio'] or metadata['duration']<=0:
        raise ValueError('素材没有有效音轨，无法识别字幕。')
    worker = TranscribeWorker(provider, config['model'], config.get('language','auto'), ffmpeg)
    with tempfile.TemporaryDirectory(prefix='flowstudio-asr-') as folder:
        temp = Path(folder)
        if provider == LOCAL_PROVIDER:
            srt, _, raw = worker._local_whisper(source)
        else:
            key = config.get('key','').strip()
            if not key:
                raise ValueError('请先设置此识别服务的 API 密钥。')
            audio = temp / 'audio.wav'
            if provider == 'Groq':
                srt, _, raw = worker._groq(source, key, temp)
            else:
                cp = subprocess.run([ffmpeg,'-y','-v','error','-i',str(source),'-map','0:a:0',
                    '-vn','-ac','1','-ar','16000',str(audio)],capture_output=True,timeout=600)
                if cp.returncode:
                    raise ValueError('无法提取音轨，请确认视频含有声音且文件可正常播放。')
                method = {'Gemini':worker._gemini,'ElevenLabs':worker._elevenlabs,'Gladia':worker._gladia}[provider]
                srt, _, raw = method(audio,key)
        captions, estimated = recognition_result(srt,raw,int(config.get('max_words',7)))
        print(json.dumps({'captions':captions,'estimated':estimated,'warnings':raw.get('warnings',[]) if isinstance(raw,dict) else []},ensure_ascii=False),flush=True)

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        message = str(exc)
        if any(x in message for x in ('10054','ConnectError','snapshot','Hub')):
            message = '语音模型下载连接中断，本地尚无完整缓存。请打开侧边栏“组件管理”，检查网络后点击“下载 / 重试模型”；无需重新导入视频。'
        # Do not include credential-bearing network exceptions or traceback locals.
        if 'https://' in message:
            message = '识别服务连接失败，请检查网络后重试。'
        print(json.dumps({'error':message},ensure_ascii=False),flush=True)
        sys.exit(1)
