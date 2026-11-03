"""Owned whisper.cpp or Cloud ASR subprocess and WAV validation; no Resolve API access."""
import argparse
import array
import os
from pathlib import Path
import re
import signal
import sys
import tempfile
import time
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import quiet_process as subprocess


def atomic_text(path, text):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(str(text), encoding='utf-8')
    temp.replace(path)


def _find_ffmpeg_bin() -> str | None:
    import platform
    import shutil
    app_root = Path(__file__).resolve().parents[1]
    mach = platform.machine().lower()
    arch_tok = 'aarch64' if mach in ('arm64', 'aarch64') else 'x86_64'
    bundled_bins = app_root / 'bundled-components/packaging/ffmpeg-libs/imageio_ffmpeg/binaries'
    bundled_match = None
    if bundled_bins.is_dir():
        for f in sorted(bundled_bins.glob('ffmpeg-*')):
            if arch_tok in f.name.lower() and f.is_file():
                bundled_match = str(f)
                break
    for cand in (
        shutil.which('ffmpeg'),
        '/opt/homebrew/bin/ffmpeg',
        '/usr/local/bin/ffmpeg',
        bundled_match,
        str(app_root / 'ffmpeg/ffmpeg'),
        str(app_root / 'ffmpeg/bin/ffmpeg.exe'),
    ):
        if cand and Path(cand).is_file():
            return str(cand)
    return None


def _decode_pcm_to_int16(raw: bytes, sw: int) -> array.array:
    """Convert 8/16/24/32-bit uncompressed integer PCM bytes to signed 16-bit array('h')."""
    if sw == 2:
        arr = array.array('h')
        arr.frombytes(raw)
        if sys.byteorder != 'little':
            arr.byteswap()
        return arr
    if sw == 1:
        return array.array('h', (((b - 128) << 8) for b in raw))
    if sw == 3:
        # 24-bit signed little-endian -> take upper 16 bits (bytes [i+1 : i+3] per sample)
        out = bytearray((len(raw) // 3) * 2)
        out[0::2] = raw[1::3]
        out[1::2] = raw[2::3]
        arr = array.array('h')
        arr.frombytes(out)
        if sys.byteorder != 'little':
            arr.byteswap()
        return arr
    if sw == 4:
        # 32-bit signed little-endian -> take upper 16 bits (bytes [i+2 : i+4] per sample)
        out = bytearray((len(raw) // 4) * 2)
        out[0::2] = raw[2::4]
        out[1::2] = raw[3::4]
        arr = array.array('h')
        arr.frombytes(out)
        if sys.byteorder != 'little':
            arr.byteswap()
        return arr
    raise ValueError(f'Unsupported PCM sample width: {sw}')


def _prepare_mono_16k_wav(src_path: str | Path, dst_path: Path) -> Path:
    """Convert any WAV (8/16/24/32-bit PCM or IEEE Float) to 16kHz 16-bit mono PCM WAV for compact cloud/local ASR."""
    src_path = Path(src_path)
    try:
        with wave.open(str(src_path), 'rb') as wf:
            chans = wf.getnchannels()
            sw = wf.getsampwidth()
            rate = wf.getframerate()
            nframes = wf.getnframes()
            comptype = wf.getcomptype()
            if comptype != 'NONE' or sw not in (1, 2, 3, 4):
                raise wave.Error(f'non-pcm: comptype={comptype} sw={sw}')
            if chans == 1 and sw == 2 and rate == 16000:
                return src_path
            raw = wf.readframes(nframes)
        samples = _decode_pcm_to_int16(raw, sw)
    except (wave.Error, EOFError, ValueError):
        ff = _find_ffmpeg_bin()
        if not ff:
            raise
        proc = subprocess.run(
            [ff, '-nostdin', '-y', '-i', str(src_path), '-vn', '-ac', '1', '-ar', '16000', '-acodec', 'pcm_s16le', str(dst_path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if proc.returncode != 0 or not dst_path.is_file() or dst_path.stat().st_size <= 44:
            raise ValueError('WAV_FORMAT_ERROR: 无法自动转换非常规音频格式为 16-bit PCM WAV')
        return dst_path

    if chans > 1:
        mono = array.array('h', (
            int(sum(samples[i + c] for c in range(chans)) // chans)
            for i in range(0, len(samples) - chans + 1, chans)
        ))
    else:
        mono = samples

    if rate != 16000 and len(mono) > 0:
        target_len = max(1, int(round(len(mono) * 16000.0 / rate)))
        step = rate / 16000.0
        resampled = array.array('h', (mono[min(len(mono) - 1, int(i * step))] for i in range(target_len)))
    else:
        resampled = mono

    with wave.open(str(dst_path), 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(resampled.tobytes())
    return dst_path


def _slice_wav_chunks(wav_path: Path, chunk_dir: Path, chunk_sec: float = 90.0) -> list[tuple[Path, float, float]]:
    """Split a WAV file into lossless chunks, returning [(chunk_path, offset_sec, duration_sec), ...]."""
    out = []
    with wave.open(str(wav_path), 'rb') as wf:
        params = wf.getparams()
        rate = wf.getframerate()
        total_frames = wf.getnframes()
        frames_per_chunk = max(rate, int(round(chunk_sec * rate)))
        pos = 0
        idx = 0
        while pos < total_frames:
            take = min(frames_per_chunk, total_frames - pos)
            wf.setpos(pos)
            data = wf.readframes(take)
            chunk_path = chunk_dir / f'chunk_{idx:03d}.wav'
            with wave.open(str(chunk_path), 'wb') as cf:
                cf.setparams(params)
                cf.writeframes(data)
            offset_sec = pos / float(rate)
            dur_sec = take / float(rate)
            out.append((chunk_path, offset_sec, dur_sec))
            pos += take
            idx += 1
    return out


def _words_to_word_srt(words: list[dict]) -> str:
    from app.services.reels.recognition_engine import timestamp_srt
    blocks = []
    for w in words or []:
        text = str(w.get('text') or w.get('word') or '').strip()
        if not text:
            continue
        start = max(0.0, float(w.get('start') or 0.0))
        end = max(start + 0.02, float(w.get('end') or w.get('finish') or (start + 0.12)))
        blocks.append(f'{len(blocks) + 1}\n{timestamp_srt(start)} --> {timestamp_srt(end)}\n{text}')
    return '\n\n'.join(blocks) + ('\n' if blocks else '')


def _parse_srt_to_words(srt_text: str, offset: float = 0.0) -> list[dict]:
    words = []
    blocks = re.split(r'\n\s*\n', (srt_text or '').replace('\r\n', '\n').strip())
    for block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        time_line = lines[1] if '-->' in lines[1] else (lines[0] if '-->' in lines[0] else '')
        if not time_line:
            continue
        m = re.search(r'(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)', time_line)
        if not m:
            continue
        st = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 1000.0
        en = int(m.group(5)) * 3600 + int(m.group(6)) * 60 + int(m.group(7)) + int(m.group(8)) / 1000.0
        text_lines = lines[2:] if time_line == lines[1] else lines[1:]
        toks = [t for t in re.split(r'\s+', ' '.join(text_lines).strip()) if t]
        if not toks:
            continue
        dur = max(0.02, en - st)
        for k, tok in enumerate(toks):
            w_st = offset + st + dur * (k / len(toks))
            w_en = offset + st + dur * ((k + 1) / len(toks))
            words.append({'start': w_st, 'end': w_en, 'text': tok})
    return words


def _transcribe_cloud_with_key(provider: str, model: str, language: str, wav_path: Path, key: str, log_fn) -> str:
    from app.services.reels.recognition_engine import TranscribeWorker, DEFAULT_MODELS
    used_model = (model or '').strip()
    if not used_model or used_model == 'default' or '/' in used_model or '\\' in used_model:
        used_model = DEFAULT_MODELS.get(provider, 'default')
    worker = TranscribeWorker(provider, used_model, language or 'auto', 'ffmpeg')
    with tempfile.TemporaryDirectory(prefix='flowstudio-autoedit-asr-') as tmp_str:
        tmp_dir = Path(tmp_str)
        mono_wav = _prepare_mono_16k_wav(wav_path, tmp_dir / 'input_16k.wav')
        if provider == 'Groq':
            chunks = _slice_wav_chunks(mono_wav, tmp_dir, chunk_sec=90.0)
            all_words = []
            for idx, (chunk_path, offset_sec, dur_sec) in enumerate(chunks, 1):
                log_fn(f'Groq 正在转写分段 {idx}/{len(chunks)}（模型 {used_model}）…')
                payload = worker._groq_transcribe_file(chunk_path, key, used_model)
                chunk_words = payload.get('words') or []
                if chunk_words:
                    for w in chunk_words:
                        wt = str(w.get('word') or w.get('text') or '').strip()
                        if wt:
                            all_words.append({
                                'start': float(w.get('start') or 0.0) + offset_sec,
                                'end': float(w.get('end') or 0.0) + offset_sec,
                                'text': wt,
                            })
                else:
                    for seg in payload.get('segments') or []:
                        st = float(seg.get('start') or 0.0) + offset_sec
                        en = float(seg.get('end') or (st + 1.0)) + offset_sec
                        toks = [t for t in str(seg.get('text') or '').strip().split() if t]
                        dur = max(0.02, en - st)
                        for k, tok in enumerate(toks):
                            all_words.append({
                                'start': st + dur * (k / len(toks)),
                                'end': st + dur * ((k + 1) / len(toks)),
                                'text': tok,
                            })
            return _words_to_word_srt(all_words)

        if provider == 'ElevenLabs':
            log_fn(f'ElevenLabs 正在转写（模型 {used_model}）…')
            srt, _, raw = worker._elevenlabs(mono_wav, key)
            payload = (raw or {}).get('response') or {}
            words = [
                {
                    'start': float(w.get('start') or 0.0),
                    'end': float(w.get('end') or (float(w.get('start') or 0.0) + 0.12)),
                    'text': str(w.get('text') or w.get('word') or '').strip(),
                }
                for w in (payload.get('words') or [])
                if w.get('type') in (None, 'word') and str(w.get('text') or w.get('word') or '').strip()
            ]
            return _words_to_word_srt(words) if words else srt

        if provider == 'Gladia':
            log_fn('Gladia 正在上传并转写音频 …')
            srt, _, raw = worker._gladia(mono_wav, key)
            payload = (raw or {}).get('response') or {}
            data = payload.get('result') or {}
            transcription = data.get('transcription') or {}
            utterances = transcription.get('utterances') if isinstance(transcription, dict) else []
            words = []
            for utt in (utterances or []):
                if not isinstance(utt, dict):
                    continue
                u_words = utt.get('words') or []
                if u_words:
                    for w in u_words:
                        wt = str(w.get('word') or w.get('text') or '').strip()
                        if wt:
                            words.append({
                                'start': float(w.get('start') or 0.0),
                                'end': float(w.get('end') or (float(w.get('start') or 0.0) + 0.12)),
                                'text': wt,
                            })
                else:
                    toks = [t for t in str(utt.get('text') or '').strip().split() if t]
                    if toks:
                        st = float(utt.get('start') or 0.0)
                        en = float(utt.get('end') or (st + 0.5))
                        dur = max(0.02, en - st)
                        for k, tok in enumerate(toks):
                            words.append({
                                'start': st + dur * (k / len(toks)),
                                'end': st + dur * ((k + 1) / len(toks)),
                                'text': tok,
                            })
            return _words_to_word_srt(words) if words else srt

        if provider == 'Gemini':
            chunks = _slice_wav_chunks(mono_wav, tmp_dir, chunk_sec=120.0)
            all_words = []
            for idx, (chunk_path, offset_sec, _) in enumerate(chunks, 1):
                log_fn(f'Gemini 正在转写分段 {idx}/{len(chunks)}（模型 {used_model}）…')
                srt, _, _ = worker._gemini(chunk_path, key)
                all_words.extend(_parse_srt_to_words(srt, offset=offset_sec))
            return _words_to_word_srt(all_words)

        raise ValueError(f'不支持的云端识别服务：{provider}')


def _run_cloud(args, wav_path: str, output: Path) -> int:
    from app.services import credential_pool
    from app.services.reels.recognition_engine import ApiFailure
    provider = str(args.cli).split(':', 1)[1].strip()
    keys = credential_pool.candidate_keys('com.flowstudio.asr', provider)
    if not keys:
        raise RuntimeError(f'CLOUD_ASR_NO_KEY: {provider} 尚未配置可用的 API 密钥')

    log_path = output.with_suffix('.log')
    def write_log(msg: str):
        with log_path.open('ab') as lf:
            lf.write((f'[{time.strftime("%H:%M:%S")}] {msg}\n').encode('utf-8', 'replace'))
            lf.flush()

    write_log(f'Cloud ASR provider={provider} model={args.model} language={args.language} key_candidates={len(keys)}')
    last_error = None
    for idx, key in enumerate(keys, 1):
        try:
            write_log(f'尝试使用第 {idx}/{len(keys)} 个 {provider} 密钥进行云端识别…')
            srt_text = _transcribe_cloud_with_key(provider, args.model, args.language, Path(wav_path), key, write_log)
            if not srt_text or not srt_text.strip():
                raise RuntimeError(f'{provider} 返回了空的字幕结果')
            credential_pool.mark_key_status('com.flowstudio.asr', provider, key, ok=True)
            srt_path = output.with_suffix('.srt')
            atomic_text(srt_path, srt_text)
            write_log(f'{provider} 识别成功，已生成词级 SRT：{srt_path.name}')
            atomic_text(output.with_suffix('.exit'), '0')
            return 0
        except ApiFailure as exc:
            last_error = exc
            status = getattr(exc, 'status', None)
            write_log(f'{provider} 密钥 {idx}/{len(keys)} 请求失败 (status={status}): {exc}')
            if status in (400, 401, 402, 403, 429) or '配额' in str(exc) or '密钥' in str(exc):
                credential_pool.mark_key_status('com.flowstudio.asr', provider, key, ok=False, reason=f'HTTP {status or "ERR"}')
        except Exception as exc:
            last_error = exc
            write_log(f'{provider} 密钥 {idx}/{len(keys)} 异常: {exc}')

    raise RuntimeError(f'CLOUD_ASR_FAILED ({provider}): {last_error}')


def run(args):
    output=Path(args.output)
    crop = None
    norm_wav = None
    start = getattr(args, "start", None)
    start_value = float(start or 0)
    try:
        if not re.fullmatch(r'[a-z]{2,4}',args.language or ''):raise ValueError('WHISPER_LANGUAGE_ERROR: 无效的语言代码 '+str(args.language))
        src_wav = str(args.wav)
        need_norm = False
        try:
            with wave.open(src_wav,'rb') as audio:
                if audio.getsampwidth()!=2 or audio.getcomptype()!='NONE' or audio.getframerate()<16000:
                    need_norm = True
                elif audio.getnframes()==0:
                    raise ValueError('WAV_FORMAT_ERROR: 导出的 WAV 音频为空（0帧）')
        except wave.Error:
            need_norm = True
        if need_norm:
            norm_wav = output.with_suffix('.pcm16.wav')
            src_wav = str(_prepare_mono_16k_wav(args.wav, norm_wav))
        with wave.open(src_wav,'rb') as audio:
            if audio.getsampwidth()!=2 or audio.getcomptype()!='NONE' or audio.getframerate()<16000 or audio.getnframes()==0:
                raise ValueError('WAV_FORMAT_ERROR: FlowStudio_WAV16 必须输出有效音频，采样率至少16kHz')
            duration=audio.getnframes()/audio.getframerate()
        if start_value < 0 or args.duration <= 0 or start_value + args.duration > duration + max(0.15,2/args.fps):
            raise ValueError('WAV_RANGE_ERROR')
        if start is None and abs(duration-args.duration)>max(0.15,2/args.fps):
            raise ValueError('WAV_DURATION_MISMATCH: WAV时长与当前视频范围不一致')
        wav_path = src_wav
        if start is not None:
            crop = output.with_suffix('.crop.wav')
            with wave.open(src_wav,'rb') as source, wave.open(str(crop),'wb') as target:
                target.setparams(source.getparams())
                source.setpos(round(start_value*source.getframerate()))
                target.writeframes(source.readframes(round(args.duration*source.getframerate())))
            wav_path = str(crop)
        if str(args.cli or '').startswith('CLOUD:'):
            return _run_cloud(args, wav_path, output)
        with output.with_suffix('.log').open('wb') as log:
            log.write(('Whisper language: '+args.language+'\n').encode());log.flush()
            proc=subprocess.Popen([args.cli,'-m',args.model,'-f',wav_path,'-l',args.language,'-osrt','-of',str(output)],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            try:
                code=proc.wait(timeout=args.timeout)
            except subprocess.TimeoutExpired:
                proc.terminate() if os.name == 'nt' else os.killpg(proc.pid,signal.SIGTERM)
                try:proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill() if os.name == 'nt' else os.killpg(proc.pid,signal.SIGKILL);proc.wait()
                raise RuntimeError('WHISPER_TIMEOUT: 识别超时，已停止本次Whisper进程')
        if code!=0:raise RuntimeError('WHISPER_FAILED: 退出码 '+str(code)+'，请查看本视频Whisper日志')
        srt=output.with_suffix('.srt')
        if not srt.is_file() or srt.stat().st_size==0:raise RuntimeError('WHISPER_FAILED: 未生成SRT时间结果')
        atomic_text(output.with_suffix('.exit'),'0')
        return 0
    except Exception as exc:
        atomic_text(output.with_suffix('.error'),str(exc))
        atomic_text(output.with_suffix('.exit'),'1')
        return 1
    finally:
        if crop is not None: crop.unlink(missing_ok=True)
        if norm_wav is not None: norm_wav.unlink(missing_ok=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('cli','model','wav','output','language'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--duration',type=float,required=True);parser.add_argument('--fps',type=float,required=True)
    parser.add_argument('--timeout',type=int,default=600)
    parser.add_argument('--start',type=float,default=None)
    raise SystemExit(run(parser.parse_args()))

