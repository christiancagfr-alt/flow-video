from __future__ import annotations
import json, os, re, shutil, threading, time
from pathlib import Path
import requests
from app.services import quiet_process as subprocess
from .text_rules import normalize_subtitle_text, normalize_required_capitalization, filter_asr_junk_srt, is_asr_junk_caption
from .captions import parse_srt
from urllib.parse import urlsplit

def allow_https_host(url, hosts):
    p = urlsplit(url)
    if p.scheme != 'https' or p.hostname not in hosts or p.username or p.password or p.port not in (None,443):
        raise ValueError('识别服务返回的地址不安全')
    return url

def response_error(resp):
    # Do not echo API responses: providers can reflect submitted credentials.
    return f'识别服务请求失败（HTTP {resp.status_code}），请检查密钥、模型和额度。'

def write_app_log(*args):
    pass

def rename_natural_key(value):
    return [int(x) if x.isdigit() else x.casefold() for x in re.split(r'(\d+)', str(value))]

def video_duration(ffmpeg, path):
    from app.services.packaging_media import probe_media
    return probe_media(path, ffmpeg)['duration']
LOCAL_PROVIDER = "本地 Whisper（无需密钥）"
DEFAULT_MODELS = {
    # 本地默认 medium：比 small 更懂语境/词形，比 large-v3 更快
    LOCAL_PROVIDER: "medium",
    # turbo 在部分希腊语/宗教口播上会幻觉成「Υπότιτλοι AUTHORWAVE」；large-v3 更稳
    "Groq": "whisper-large-v3",
    # gemini-2.0-flash 已于 2026-06-01 关停；字幕多模态用 3.6 Flash（稳定）
    "Gemini": "gemini-3.6-flash",
    "ElevenLabs": "scribe_v2",
    "Gladia": "default",
    "Luma": "default",
    "Kling": "default",
}
LOCAL_WHISPER_MODEL_OPTIONS = [
    ("base", "base · 最快（口型可用，语义略弱）"),
    ("small", "small · 快 / 准确度中上（推荐提速）"),
    ("medium", "medium · 语义更稳 / 更慢"),
    ("large-v3", "large-v3 · 最准 / 很慢很吃显存"),
]
_MODEL_MIGRATIONS = {
    "Groq": {
        "whisper-large-v3-turbo": "whisper-large-v3",
        "whisper-large-v3-turbo-latest": "whisper-large-v3",
    },
    "Gemini": {
        # 1.x / 2.0 系列已关停 → 3.6 Flash
        "gemini-1.5-flash": "gemini-3.6-flash",
        "gemini-1.5-flash-latest": "gemini-3.6-flash",
        "gemini-1.5-pro": "gemini-3.6-flash",
        "gemini-2.0-flash": "gemini-3.6-flash",
        "gemini-2.0-flash-001": "gemini-3.6-flash",
        "gemini-2.0-flash-lite": "gemini-3.1-flash-lite",
        "gemini-2.0-flash-lite-001": "gemini-3.1-flash-lite",
        "gemini-2.5-flash": "gemini-3.6-flash",
        "gemini-2.5-flash-lite": "gemini-3.1-flash-lite",
        "gemini-3.5-flash": "gemini-3.6-flash",  # 旧默认别名，升到现行稳定 Flash
    },
    "ElevenLabs": {
        "scribe_v1": "scribe_v2",
        "scribe_v1_experimental": "scribe_v2",
    },
}

def atomic_write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)

def read_json_file(path: Path, default=None):
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded
    except (OSError, ValueError, TypeError):
        return {} if default is None else default

def timestamp_srt(seconds: float) -> str:
    millis = max(0, round(float(seconds) * 1000))
    hours, rem = divmod(millis, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"

def segments_to_srt(segments, language=None) -> str:
    blocks = []
    for i, seg in enumerate(segments, 1):
        text = normalize_subtitle_text(
            re.sub(r"\s+", " ", str(seg.get("text", ""))).strip(), language=language)
        if not text or is_asr_junk_caption(text):
            continue
        start = seg.get("start", 0)
        end = max(float(seg.get("end", start + 2)), float(start) + 0.2)
        blocks.append(f"{len(blocks)+1}\n{timestamp_srt(start)} --> {timestamp_srt(end)}\n{text}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")

def words_to_segments(words):
    segments, current, start, end = [], [], None, None
    for word in words or []:
        if word.get("type") not in (None, "word"):
            continue
        text = str(word.get("text", "")).strip()
        if not text:
            continue
        w_start = float(word.get("start") or end or 0)
        w_end = float(word.get("end") or (w_start + 0.3))
        if start is None:
            start = w_start
        current.append(text)
        end = w_end
        joined = "".join(current) if any("\u4e00" <= c <= "\u9fff" for c in text) else " ".join(current)
        if end - start >= 6 or len(joined) >= 34 or re.search(r"[。！？.!?]$", text):
            segments.append({"start": start, "end": end, "text": joined})
            current, start, end = [], None, None
    if current:
        joined = "".join(current) if any(any("\u4e00" <= c <= "\u9fff" for c in x) for x in current) else " ".join(current)
        segments.append({"start": start or 0, "end": end or (start or 0) + 2, "text": joined})
    return segments

def clean_model_srt(text: str, language=None) -> str:
    text = re.sub(r"^```(?:srt)?\s*", "", text.strip(), flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    text = text.replace("\r\n", "\n")
    text = normalize_subtitle_text(text, language=language)
    if "-->" not in text:
        body = normalize_subtitle_text(text.strip(), language=language)
        if is_asr_junk_caption(body):
            return ""
        return f"1\n00:00:00,000 --> 99:59:59,000\n{body}\n"
    # 去掉 Whisper 幻觉水印行（如「Υπότιτλοι AUTHORWAVE」）
    return filter_asr_junk_srt(text.strip() + "\n")

class ApiFailure(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status

class _Progress:
    def emit(self, message):
        print(json.dumps({'progress': str(message)}, ensure_ascii=False), flush=True)

class TranscribeWorker:
    _shared_local_lock = threading.Lock()
    _shared_local_model = None
    _shared_local_model_name = None
    _shared_local_device = None

    def __init__(self, provider, model, language, ffmpeg):
        self.provider, self.model, self.language = provider, model, language
        self.ffmpeg_path = ffmpeg
        self.cancelled = False
        self.diarize = False
        self.log = _Progress()

    def _local_whisper(self, audio: Path):
        try:
            import ctranslate2
            if not hasattr(ctranslate2, "StorageView"):
                raise RuntimeError(
                    "本地 Whisper 引擎不完整：ctranslate2 缺少 StorageView。"
                    "常见原因是安装包未正确打入 ctranslate2（请升级到含此修复的版本，"
                    "或在源码环境执行：pip install -U --force-reinstall ctranslate2 faster-whisper）。"
                )
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "缺少本地字幕组件，请运行：pip install -U faster-whisper ctranslate2"
            ) from exc
        model_name = str(self.model or DEFAULT_MODELS[LOCAL_PROVIDER]).strip() or "medium"
        # 兼容界面展示名
        for code, label in LOCAL_WHISPER_MODEL_OPTIONS:
            if model_name == label or model_name.startswith(code):
                model_name = code
                break
        if model_name not in {code for code, _ in LOCAL_WHISPER_MODEL_OPTIONS}:
            self.log.emit(f"未知本地模型「{model_name}」，回退 medium")
            write_app_log(f"未知本地模型「{model_name}」，回退 medium", "WARNING", "字幕识别")
            model_name = "medium"

        # A complete local snapshot must remain usable without a Hub request.
        from faster_whisper.utils import download_model
        try:
            model_source=download_model(model_name,local_files_only=True)
            if not (Path(model_source)/'model.bin').is_file() or not (Path(model_source)/'model.bin').stat().st_size:
                raise ValueError('Incomplete cached model')
        except Exception: model_source=model_name

        def _emit(msg: str) -> None:
            try:
                self.log.emit(msg)
            except Exception:
                pass
            write_app_log(msg, "INFO", "字幕识别")

        # 复用跨 Worker 的共享模型（图文成片每条任务都会新建 Worker）
        with TranscribeWorker._shared_local_lock:
            shared_ok = (
                TranscribeWorker._shared_local_model is not None
                and TranscribeWorker._shared_local_model_name == model_name
            )
            if shared_ok:
                self._local_model = TranscribeWorker._shared_local_model
                self._local_device = TranscribeWorker._shared_local_device or "cpu"
                self._local_model_name = model_name
                _emit(f"复用已加载的本地 Whisper 模型：{model_name}（{self._local_device}）")
            else:
                _emit(
                    f"正在加载本地 Whisper 模型：{model_name}"
                    f"（首次使用会下载；medium/large 在 CPU 上可能需数分钟，并非卡死）…"
                )
                has_cuda = ctranslate2.get_cuda_device_count() > 0
                # CPU 多线程；small 用 int8 更快。不影响词级时间戳准确度的前提下提速加载。
                cpu_threads = max(2, min(16, (os.cpu_count() or 4)))
                try:
                    self._local_model = WhisperModel(
                        model_source,
                        device="cuda" if has_cuda else "cpu",
                        compute_type="float16" if has_cuda else "int8",
                        cpu_threads=cpu_threads,
                        num_workers=1,
                    )
                    self._local_device = "cuda" if has_cuda else "cpu"
                    self._local_model_name = model_name
                except (ValueError, RuntimeError) as exc:
                    if not has_cuda:
                        raise
                    _emit(f"当前 GPU 模式不可用，自动切换 CPU INT8：{exc}")
                    self._local_model = WhisperModel(
                        model_source, device="cpu", compute_type="int8",
                        cpu_threads=cpu_threads, num_workers=1,
                    )
                    self._local_device = "cpu"
                    self._local_model_name = model_name
                TranscribeWorker._shared_local_model = self._local_model
                TranscribeWorker._shared_local_model_name = model_name
                TranscribeWorker._shared_local_device = self._local_device
                _emit(f"本地 Whisper 模型已就绪：{model_name}（{self._local_device}）")

        language = None if not self.language or self.language == "auto" else self.language

        # 先抽 mono 16k WAV：本地 Whisper 解码更快、时间戳更稳（避免直接喂整段 mp4 又慢又容易第一次对不齐）
        asr_audio = Path(audio)
        prep_wav = None
        try:
            import tempfile
            creation = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            prep_dir = Path(tempfile.mkdtemp(prefix="vt_whisper_"))
            prep_wav = prep_dir / "asr_16k.wav"
            _emit(f"本地识别：抽取音轨 {audio.name} → 16k mono …")
            prep = subprocess.run(
                [
                    self.ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error",
                    "-i", str(audio), "-map", "0:a:0", "-vn",
                    "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
                    str(prep_wav),
                ],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                creationflags=creation, text=True, encoding="utf-8", errors="replace",
            )
            if prep.returncode == 0 and prep_wav.is_file() and prep_wav.stat().st_size > 1000:
                asr_audio = prep_wav
            else:
                err = (prep.stderr or "")[-400:]
                _emit(f"16k 抽取未成功，回退源文件识别：{err or 'unknown'}")
                prep_wav = None
        except Exception as prep_exc:
            _emit(f"16k 抽取异常，回退源文件：{prep_exc}")
            prep_wav = None

        audio_dur = 0.0
        try:
            audio_dur = float(video_duration(self.ffmpeg_path, str(asr_audio)) or 0)
        except Exception:
            audio_dur = 0.0
        _emit(f"开始本地识别：{asr_audio.name}（约 {audio_dur:.0f}s）…")

        def collect_segments(stream, info, *, offset=0.0, label=""):
            segments = []
            for item in stream:
                if self.cancelled:
                    raise RuntimeError("任务已取消")
                words = [
                    {
                        "start": float(word.start) + offset,
                        "end": float(word.end) + offset,
                        "text": word.word.strip(),
                    }
                    for word in (getattr(item, "words", None) or []) if word.word.strip()
                ]
                segments.append({
                    "start": float(item.start) + offset,
                    "end": float(item.end) + offset,
                    "text": item.text.strip(),
                    "words": words,
                    "no_speech_prob":float(getattr(item,'no_speech_prob',0)),
                    "avg_logprob":float(getattr(item,'avg_logprob',0)),
                })
                if len(segments) % 5 == 0 or len(segments) == 1:
                    _emit(f"本地识别中{label}：已生成 {len(segments)} 条字幕 …")
            return segments, info

        def transcribe_file(model, path, *, offset=0.0, beam_size=None, use_vad=None, label=""):
            import wave
            import numpy as np
            # FFmpeg already made 16 kHz mono PCM. Pass samples directly instead
            # of coupling recognition to changing PyAV decoding arguments.
            with wave.open(str(path),'rb') as wav:
                if wav.getnchannels()!=1 or wav.getframerate()!=16000 or wav.getsampwidth()!=2:
                    raise RuntimeError('识别音轨必须为 16 kHz 单声道 PCM。')
                samples=np.frombuffer(wav.readframes(wav.getnframes()),dtype=np.int16).astype(np.float32)/32768.0
            try:
                import onnxruntime  # noqa: F401
                vad_default = True
            except ImportError:
                vad_default = False
                if use_vad is None:
                    _emit("未检测到 ONNX Runtime，已自动关闭 VAD 静音过滤并继续识别。")
            if use_vad is None:
                use_vad = vad_default
            if beam_size is None:
                name = str(getattr(self, "_local_model_name", "") or "").lower()
                if self._local_device == "cuda" and "large" in name:
                    beam_size = 2
                else:
                    beam_size = 1
            try:
                stream, info = model.transcribe(
                    samples,
                    language=language,
                    beam_size=beam_size,
                    best_of=1,
                    patience=1.0,
                    temperature=0.0,
                    vad_filter=use_vad,
                    word_timestamps=True,
                    condition_on_previous_text=False,
                    no_speech_threshold=0.6,
                    vad_parameters={
                        "min_silence_duration_ms": 350,
                        "speech_pad_ms": 120,
                    } if use_vad else None,
                )
                return collect_segments(stream, info, offset=offset, label=label)
            except RuntimeError as exc:
                if not use_vad or "onnxruntime" not in str(exc).lower():
                    raise
                _emit("VAD 组件不可用，已关闭静音过滤并自动重试当前片段。")
                stream, info = model.transcribe(
                    samples, language=language, beam_size=1, best_of=1,
                    temperature=0.0, vad_filter=False, word_timestamps=True,
                    condition_on_previous_text=False,
                )
                return collect_segments(stream, info, offset=offset, label=label)

        def _word_density_ok(segs, expect_dur=0.0) -> bool:
            if not segs:
                return False
            n_words = sum(len(s.get("words") or []) for s in segs)
            span = max(0.5, float(segs[-1].get("end") or 0) - float(segs[0].get("start") or 0))
            if n_words < max(3, int(span / 1.6)):
                return False
            # 长视频：词轴覆盖率过低 = 第一次常对不上口型 / 总时长偏短
            if expect_dur >= 90 and n_words > 0:
                last_end = max(float(s.get("end") or 0) for s in segs)
                if last_end < expect_dur * 0.90:
                    return False
            return True

        def _coverage_stats(segs, expect_dur=0.0):
            n_words = sum(len(s.get("words") or []) for s in (segs or []))
            last_end = max((float(s.get("end") or 0) for s in (segs or [])), default=0.0)
            ratio = (last_end / expect_dur) if expect_dur > 1e-3 else 0.0
            return n_words, last_end, ratio

        def _pick_better_segments(current, challenger, expect_dur=0.0):
            if not challenger:
                return current
            if not current:
                return challenger
            if _word_density_ok(challenger, expect_dur) and not _word_density_ok(current, expect_dur):
                return challenger
            _, cur_end, _ = _coverage_stats(current, expect_dur)
            _, new_end, _ = _coverage_stats(challenger, expect_dur)
            cur_n = sum(len(s.get("words") or []) for s in current)
            new_n = sum(len(s.get("words") or []) for s in challenger)
            if new_end > cur_end + 0.4 or (new_end >= cur_end - 0.2 and new_n > cur_n):
                return challenger
            return current

        def _transcribe_long_chunked(model, wav_path, total_dur, *, use_vad=None):
            """≥90s：重叠分段识别再拼时间戳，避免整段截断，也避免无重叠硬切丢边界词。

            旧实现用 ffmpeg segment 无重叠切片，却按 overlap 丢掉下一段开头词，
            会在每 75s 边界制造缺口；合成成品再提取时时间轴更容易看起来「对不齐」。
            """
            import tempfile
            creation = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            chunk_len, overlap = 30.0, 3.0
            step = chunk_len - overlap
            total_dur = max(0.5, float(total_dur or 0.5))
            starts = []
            cursor = 0.0
            while cursor < total_dur - 0.4:
                starts.append(cursor)
                if cursor + chunk_len >= total_dur - 0.2:
                    break
                cursor += step
            if not starts:
                starts = [0.0]
            chunk_dir = Path(tempfile.mkdtemp(prefix="vt_whisper_chunks_"))
            _emit(
                f"长音频（{total_dur:.0f}s）分段识别：每段约 {int(chunk_len)}s，"
                f"重叠 {overlap:.0f}s，共 {len(starts)} 段…"
            )
            all_segs = []
            info = None
            try:
                for i, offset in enumerate(starts):
                    if self.cancelled:
                        raise RuntimeError("任务已取消")
                    this_len = min(chunk_len, max(0.5, total_dur - offset))
                    chunk = chunk_dir / f"c_{i:04d}.wav"
                    cmd = [
                        self.ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error",
                        "-ss", f"{offset:.3f}", "-t", f"{this_len:.3f}",
                        "-i", str(wav_path), "-map", "0:a:0",
                        "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
                        str(chunk),
                    ]
                    proc = subprocess.run(
                        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                        creationflags=creation, text=True, encoding="utf-8", errors="replace",
                    )
                    if proc.returncode != 0 or not chunk.is_file() or chunk.stat().st_size < 1000:
                        err = (proc.stderr or "")[-200:]
                        _emit(f"分段 {i + 1} 抽取失败，回退整段识别：{err or 'unknown'}")
                        return None
                    try:
                        chunk_dur = float(video_duration(self.ffmpeg_path, str(chunk)) or 0)
                    except Exception:
                        chunk_dur = 0.0
                    if chunk_dur <= 0.05:
                        chunk_dur = float(this_len)
                    _emit(
                        f"本地识别分段 {i + 1}/{len(starts)}"
                        f"（起点 {offset:.0f}s，本段约 {chunk_dur:.0f}s）…"
                    )
                    segs, info = transcribe_file(
                        model, chunk, offset=offset, use_vad=use_vad,
                        label=f"[{i + 1}/{len(starts)}]",
                    )
                    from app.services.asr_timing import stitch_segments
                    all_segs=stitch_segments(all_segs,segs,offset+overlap*.5)
            finally:
                try:
                    shutil.rmtree(chunk_dir, ignore_errors=True)
                except Exception:
                    pass
            if not all_segs:
                return None
            return all_segs, info

        try:
            import shutil
            _emit(
                f"本地识别参数：beam=1、VAD 跳过静音、词级时间戳开启"
                f"（设备 {self._local_device}，模型 {getattr(self, '_local_model_name', '?')}）"
            )
            segments, info = None, None
            if audio_dur >= 90 and prep_wav is not None:
                chunked = _transcribe_long_chunked(self._local_model, asr_audio, audio_dur)
                if chunked is not None:
                    segments, info = chunked
            if segments is None:
                segments, info = transcribe_file(self._local_model, asr_audio)
            # 覆盖率/密度不足：先关 VAD 整段补跑；长片仍不足再强制分段识别
            if not _word_density_ok(segments, audio_dur):
                n_words, last_end, ratio = _coverage_stats(segments, audio_dur)
                _emit(
                    f"本地识别覆盖不足（词 {n_words}，末词 {last_end:.1f}s / 音频 {audio_dur:.1f}s，"
                    f"{ratio * 100:.0f}%），关闭 VAD 整段补跑一次…"
                )
                if audio_dur >= 90 and prep_wav is not None:
                    retried = _transcribe_long_chunked(self._local_model, asr_audio, audio_dur, use_vad=False)
                    segments2,info2 = retried if retried else (segments,info)
                else:
                    segments2, info2 = transcribe_file(
                        self._local_model, asr_audio, use_vad=False, label="[补跑]",
                    )
                if _pick_better_segments(segments, segments2, audio_dur) is segments2:
                    segments, info = segments2, info2
                if (
                    audio_dur >= 90
                    and prep_wav is not None
                    and not _word_density_ok(segments, audio_dur)
                ):
                    _emit("关 VAD 后覆盖仍不足，强制再跑一遍分段识别…")
                    chunked3 = _transcribe_long_chunked(
                        self._local_model, asr_audio, audio_dur, use_vad=False,
                    )
                    if chunked3 is not None:
                        segments3, info3 = chunked3
                        if _pick_better_segments(segments, segments3, audio_dur) is segments3:
                            segments, info = segments3, info3
        except RuntimeError as exc:
            if self._local_device != "cuda" or self.cancelled:
                raise
            _emit(f"GPU 长视频识别中断，自动改用 CPU INT8 从当前视频重试：{exc}")
            with TranscribeWorker._shared_local_lock:
                self._local_model = WhisperModel(
                    model_name, device="cpu", compute_type="int8",
                    cpu_threads=max(1, min(8, os.cpu_count() or 4)),
                )
                self._local_device = "cpu"
                self._local_model_name = model_name
                TranscribeWorker._shared_local_model = self._local_model
                TranscribeWorker._shared_local_model_name = model_name
                TranscribeWorker._shared_local_device = "cpu"
            segments, info = transcribe_file(self._local_model, asr_audio)
        # Last word near the end does NOT establish that middle speech was read.
        # Retry audible gaps independently, never replace successful passages.
        from app.services.asr_gaps import audible_gaps, insert_gap_words
        warnings=[]
        if prep_wav is not None:
            gaps=audible_gaps(asr_audio,[w for s in segments for w in s.get('words',[])])
            if gaps:
                import wave
                _emit(f'检测到 {len(gaps)} 处有声但无字幕的区间，正在逐段补识别…')
                with wave.open(str(asr_audio),'rb') as audio_wav:
                    rate=audio_wav.getframerate();pcm=audio_wav.readframes(audio_wav.getnframes())
                additions=[]
                with tempfile.TemporaryDirectory(prefix='flowstudio-gap-') as gap_dir:
                    for index,(start,end) in enumerate(gaps):
                        cursor=start
                        while cursor<end:
                            if self.cancelled:raise RuntimeError('任务已取消')
                            stop=min(end,cursor+20);a=max(0,cursor-1);b=min(audio_dur,stop+1)
                            clip=Path(gap_dir)/'gap.wav'
                            with wave.open(str(clip),'wb') as out:
                                out.setnchannels(1);out.setsampwidth(2);out.setframerate(rate)
                                out.writeframes(pcm[int(a*rate)*2:int(b*rate)*2])
                            _emit(f'补识别 {index+1}/{len(gaps)}：{cursor:.1f}–{stop:.1f}s（关闭静音过滤）')
                            recovered,_=transcribe_file(self._local_model,clip,offset=a,use_vad=False,beam_size=5,label='[缺口补识别]')
                            recovered=[s for s in recovered if s.get('no_speech_prob',0)<.6 and s.get('avg_logprob',0)>-1]
                            clipped=insert_gap_words([],recovered,[(cursor,stop)])
                            additions.extend(clipped);cursor=stop
                segments=insert_gap_words(segments,additions,gaps)
                remaining=audible_gaps(asr_audio,[w for s in segments for w in s.get('words',[])])
                if remaining:
                    intervals='、'.join(f'{a:.1f}–{b:.1f}秒' for a,b in remaining)
                    warnings.append('这些有声区间补识别后仍无字幕，请试听确认（也可能是音乐或噪声）：'+intervals)
                    _emit(warnings[-1])
        detected = getattr(info, "language", None) or language
        plain = "\n".join(
            normalize_subtitle_text(x["text"], language=detected) for x in segments)
        raw = {"provider": "Local Whisper", "model": self.model,
               "language": detected, "segments": segments, "warnings":warnings,
               "words": [word for segment in segments for word in segment.get("words", [])]}
        n_words, last_end, ratio = _coverage_stats(segments, audio_dur)
        cover_note = ""
        if audio_dur >= 15:
            cover_note = f"，末词 {last_end:.1f}s / 音频 {audio_dur:.1f}s"
            if ratio < 0.85:
                _emit(
                    f"⚠ 词轴明显短于音频{cover_note}。若口播未提前结束，请换模型或「重新提取」。"
                )
        _emit(
            f"本地识别完成：{audio.name}（{len(segments)} 段，{n_words} 词{cover_note}）"
        )
        try:
            if prep_wav is not None:
                shutil.rmtree(prep_wav.parent, ignore_errors=True)
        except Exception:
            pass
        return segments_to_srt(segments, language=detected), plain, raw
    def _groq_payload_is_suspicious(self, payload: dict, duration: float) -> str:
        """识别 turbo 等模型在希腊语等语种上的典型幻觉（极短文本 + 水印词）。"""
        text = str(payload.get("text") or "").strip()
        words = payload.get("words") or []
        segments = payload.get("segments") or []
        lower = text.casefold()
        # 已知幻觉：把整段口播压成水印/「字幕」二字
        if "authorwave" in lower or "υπότιτλοι" in lower or "υποτιτλοι" in lower:
            if len(text) < 80:
                return f"疑似幻觉文本：{text[:60]}"
        # 时长 > 12s 却文本/词数明显过少（turbo 幻觉或 large-v3 偶发截断）
        if duration >= 12:
            min_chars = max(60, int(duration * 2.5))
            min_words = max(8, int(duration * 0.6))
            if len(text) < min_chars or (words and len(words) < min_words and len(segments) <= 2):
                return f"结果过稀（{len(text)} 字/{len(words)} 词/{duration:.0f}s）：{text[:60]}"
        return ""
    def _groq_transcribe_file(self, chunk: Path, key: str, model: str) -> dict:
        data = {
            "model": model,
            "response_format": "verbose_json",
            "timestamp_granularities[]": ["word", "segment"],
            "temperature": "0",
        }
        if self.language and self.language != "auto":
            data["language"] = self.language
        with chunk.open("rb") as handle:
            resp = safe_request("POST", 
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {key}"},
                data=data,
                files={"file": (chunk.name, handle, "audio/wav")},
                timeout=900,
            )
        if resp.status_code >= 300:
            raise ApiFailure(response_error(resp), resp.status_code)
        return resp.json()
    def _groq(self, audio: Path, key: str, temp: Path):
        chunks_dir = temp / "chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)
        pattern = chunks_dir / "chunk_%03d.wav"
        creation = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        segment_seconds = 90
        # 统一抽 mono 16k 再分段，体积更小、Groq 更稳
        # 注意：不要用 0:a:0?（可选映射）——无音轨时会生成 0 流输出却仍 return 0，导致「无 stream」
        prepared = temp / "groq_source.wav"
        if not prepared.exists() or prepared.stat().st_size < 1000:
            prep = subprocess.run(
                [self.ffmpeg_path, "-y", "-i", str(audio), "-map", "0:a:0", "-vn",
                 "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(prepared)],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                creationflags=creation, text=True, encoding="utf-8", errors="replace",
            )
            if prep.returncode != 0 or not prepared.exists() or prepared.stat().st_size < 1000:
                err = (prep.stderr or "")[-600:]
                if "Stream map" in err or "does not contain" in err or "matches no streams" in err:
                    raise RuntimeError(
                        "媒体没有可识别的音轨（常见于 TikTok/抖音只下到静音画面）。"
                        "请更新 yt-dlp 后重试链接，或改用含声音的本地视频。\n" + err
                    )
                # 其它错误：回退对源文件分段（仍要求有音轨）
                prepared = audio
        chunks = sorted(chunks_dir.glob("chunk_*.wav"), key=lambda path: rename_natural_key(path.name))
        if not chunks:
            self.log.emit("正在把长音频切成 90 秒无损识别分段 …")
            cmd = [self.ffmpeg_path, "-y", "-i", str(prepared), "-map", "0:a:0", "-vn", "-f", "segment",
                   "-segment_time", str(segment_seconds), "-reset_timestamps", "1",
                   "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(pattern)]
            result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                    creationflags=creation, text=True, encoding="utf-8", errors="replace")
            chunks = sorted(chunks_dir.glob("chunk_*.wav"), key=lambda path: rename_natural_key(path.name))
            if result.returncode != 0 or not chunks:
                err = (result.stderr or "")[-800:]
                if "does not contain any stream" in err or "matches no streams" in err:
                    raise RuntimeError(
                        "无法切分识别音频：文件没有音轨。"
                        "TikTok 等链接请确保下载含声音的版本，或使用本地 mp4。\n" + err
                    )
                raise RuntimeError("Groq 长音频分段失败。\n" + err)
        else:
            self.log.emit(f"断点续接：复用 {len(chunks)} 个长音频分段。")
        cache_path = temp / "groq_chunk_results.json"
        # 模型名变了就丢弃旧缓存（避免 turbo 幻觉结果永久复用）
        cache = read_json_file(cache_path, {})
        if cache.get("_model") != self.model:
            cache = {"_model": self.model}
            atomic_write_json(cache_path, cache)
        all_segments, all_words, texts, raw_items, offset = [], [], [], [], 0.0
        primary_model = self.model or DEFAULT_MODELS["Groq"]
        fallback_models = []
        if "turbo" in primary_model.casefold():
            fallback_models.append("whisper-large-v3")
        elif primary_model != "whisper-large-v3":
            fallback_models.append("whisper-large-v3")
        for number, chunk in enumerate(chunks, 1):
            payload = cache.get(chunk.name)
            try:
                chunk_dur = float(video_duration(self.ffmpeg_path, str(chunk)))
            except Exception:
                chunk_dur = float(segment_seconds)
            if payload and not self._groq_payload_is_suspicious(payload, chunk_dur):
                self.log.emit(f"Groq 断点续接：跳过已完成分段 {number}/{len(chunks)}")
            else:
                if payload:
                    self.log.emit(f"Groq 分段 {number} 缓存结果异常，重新请求 …")
                used_model = primary_model
                self.log.emit(f"Groq 转写分段 {number}/{len(chunks)}（模型 {used_model}）…")
                payload = self._groq_transcribe_file(chunk, key, used_model)
                reason = self._groq_payload_is_suspicious(payload, chunk_dur)
                if reason:
                    for alt in fallback_models:
                        if alt == used_model:
                            continue
                        self.log.emit(f"Groq {used_model} 结果异常（{reason}），改用 {alt} 重试 …")
                        try:
                            payload = self._groq_transcribe_file(chunk, key, alt)
                            used_model = alt
                            if not self._groq_payload_is_suspicious(payload, chunk_dur):
                                break
                        except Exception as exc:
                            self.log.emit(f"Groq 备用模型 {alt} 失败：{exc}")
                    still_bad = self._groq_payload_is_suspicious(payload, chunk_dur)
                    if still_bad:
                        raise RuntimeError(
                            f"Groq 识别结果异常（{still_bad}）。"
                            "建议：设置里把 Groq 模型改为 whisper-large-v3，或改用本地 Whisper。"
                        )
                cache[chunk.name] = payload
                cache["_model"] = used_model
                atomic_write_json(cache_path, cache)
            raw_items.append(payload)
            text = payload.get("text", "").strip()
            texts.append(text)
            local = payload.get("segments") or []
            for seg in local:
                all_segments.append({"start": float(seg.get("start", 0)) + offset,
                                     "end": float(seg.get("end", 0)) + offset,
                                     "text": seg.get("text", "")})
            for word in payload.get("words") or []:
                word_text = str(word.get("word") or word.get("text") or "").strip()
                if word_text:
                    all_words.append({"start": float(word.get("start", 0)) + offset,
                                      "end": float(word.get("end", 0)) + offset, "text": word_text})
            offset += chunk_dur
        if not all_segments:
            all_segments = [{"start": 0, "end": max(2, offset), "text": "\n".join(texts)}]
        lang = None if not self.language or self.language == "auto" else self.language
        plain = "\n".join(normalize_subtitle_text(t, language=lang) for t in texts if t)
        return segments_to_srt(all_segments, language=lang), plain or "\n".join(texts), {
            "provider": "Groq", "chunks": raw_items, "words": all_words, "language": lang}
    def _gemini(self, audio: Path, key: str):
        size = audio.stat().st_size
        mime = "audio/wav"
        headers = {
            "x-goog-api-key": key,
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(size),
            "X-Goog-Upload-Header-Content-Type": mime,
            "Content-Type": "application/json",
        }
        start = safe_request("POST", "https://generativelanguage.googleapis.com/upload/v1beta/files",
                              headers=headers, json={"file": {"display_name": audio.name}}, timeout=60)
        if start.status_code >= 300:
            msg = response_error(start)
            if start.status_code == 429:
                msg = "Gemini 配额已用尽（429）。请到 Google AI Studio 检查额度/账单，或改用 Groq / 本地 Whisper。\n" + msg
            raise ApiFailure(msg, start.status_code)
        upload_url = start.headers.get("x-goog-upload-url")
        if not upload_url:
            raise ApiFailure("Gemini 未返回上传地址")
        try:
            upload_url = allow_https_host(
                upload_url,
                {"generativelanguage.googleapis.com", "googleapis.com"},
            )
        except ValueError as exc:
            raise ApiFailure(str(exc)) from exc
        self.log.emit("上传音频到 Gemini Files API …")
        with audio.open("rb") as handle:
            uploaded = safe_request("POST", upload_url, headers={
                "Content-Length": str(size), "X-Goog-Upload-Offset": "0",
                "X-Goog-Upload-Command": "upload, finalize",
            }, data=handle, timeout=900)
        if uploaded.status_code >= 300:
            msg = response_error(uploaded)
            if uploaded.status_code == 429:
                msg = "Gemini 上传配额已用尽（429）。请检查额度或改用其它识别服务。\n" + msg
            raise ApiFailure(msg, uploaded.status_code)
        file_info = uploaded.json().get("file", {})
        file_uri = file_info.get("uri")
        file_name = file_info.get("name")
        if not file_uri:
            raise ApiFailure("Gemini 文件上传响应缺少 URI")
        # 等待文件进入 ACTIVE，避免刚上传就 generate 失败
        for _ in range(30):
            if self.cancelled:
                raise RuntimeError("任务已取消")
            state = str(file_info.get("state") or "").upper()
            if state in ("ACTIVE", "STATE_ACTIVE", ""):
                if state.startswith("ACTIVE") or state == "STATE_ACTIVE":
                    break
                # 部分响应无 state 字段，直接继续
                if not state:
                    break
            if state in ("FAILED", "STATE_FAILED"):
                raise ApiFailure(f"Gemini 文件处理失败：{file_info}")
            time.sleep(1)
            try:
                meta = safe_request("GET", 
                    f"https://generativelanguage.googleapis.com/v1beta/{file_name}",
                    headers={"x-goog-api-key": key}, timeout=30,
                )
                if meta.status_code < 300:
                    file_info = meta.json()
                    file_uri = file_info.get("uri") or file_uri
                    if str(file_info.get("state") or "").upper() in ("ACTIVE", "STATE_ACTIVE"):
                        break
            except Exception:
                break
        prompt = (
            "请准确转写这段音频，并只输出标准 SRT 字幕（不要 Markdown、不要解释）。\n"
            "硬性要求：\n"
            "1) 保留原语言；\n"
            "2) 必须是【词级】时间轴：每一条 SRT 只写一个词（或一个很短的语气词），"
            "时间码必须对齐该词真实开口与收口，禁止把整句塞进一条；\n"
            "3) 格式：序号 / HH:MM:SS,mmm --> HH:MM:SS,mmm / 正文；\n"
            "4) 词与词之间时间连续、不重叠；静音处不要编造词。\n"
            "若无法做到词级，也请尽量短切（每条≤2个词），时间码仍须贴合口播节奏。"
        )
        if self.language and self.language != "auto":
            prompt += f"\n音频语言代码提示：{self.language}。"
        body = {"contents": [{"parts": [{"text": prompt}, {"file_data": {
            "mime_type": mime, "file_uri": file_uri}}]}],
                "generationConfig": {"temperature": 0.1}}
        try:
            model_name = self.model or DEFAULT_MODELS["Gemini"]
            # 旧模型名热迁移（即使用户配置未重启）
            model_name = model_name
            fallbacks = [model_name]
            payload = None
            used_model = model_name
            last_err = ""
            for try_model in fallbacks:
                self.log.emit(f"Gemini 正在生成带时间码字幕（{try_model}）…")
                resp = safe_request("POST", 
                    f"https://generativelanguage.googleapis.com/v1beta/models/{try_model}:generateContent",
                    headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                    json=body, timeout=1200,
                )
                if resp.status_code < 300:
                    payload = resp.json()
                    used_model = try_model
                    break
                msg = response_error(resp)
                last_err = msg
                # 模型关停 / 不存在：换下一个
                if resp.status_code in (404, 400) and (
                    "not found" in msg.casefold()
                    or "not supported" in msg.casefold()
                    or "is not found" in msg.casefold()
                    or "no longer available" in msg.casefold()
                ):
                    self.log.emit(f"Gemini 模型「{try_model}」不可用，尝试下一型号…")
                    continue
                if resp.status_code == 429:
                    msg = (
                        "Gemini 配额已用尽（429）。免费额度用完后需开通计费，"
                        "或暂时改用「本地 Whisper」/「Groq」。\n" + msg
                    )
                raise ApiFailure(msg, resp.status_code)
            if payload is None:
                raise ApiFailure(
                    f"Gemini 模型均不可用（已试 {', '.join(fallbacks)}）。\n{last_err}",
                    404,
                )
            text = "\n".join(part.get("text", "") for cand in payload.get("candidates", [])
                              for part in cand.get("content", {}).get("parts", []))
            lang = None if not self.language or self.language == "auto" else self.language
            srt = clean_model_srt(text, language=lang)
            plain = re.sub(r"(?m)^\d+\s*$|^\d{2}:\d{2}:\d{2},\d{3} --> .*?$", "", srt)
            plain = re.sub(r"\n{2,}", "\n", plain).strip()
            return srt, plain, {
                "provider": "Gemini", "response": payload, "language": lang, "model": used_model,
            }
        finally:
            if file_name:
                try:
                    safe_request("DELETE", f"https://generativelanguage.googleapis.com/v1beta/{file_name}",
                                    headers={"x-goog-api-key": key}, timeout=20)
                except Exception:
                    pass
    def _elevenlabs(self, audio: Path, key: str):
        model_id = str(self.model or DEFAULT_MODELS["ElevenLabs"] or "scribe_v2").strip()
        model_id = _MODEL_MIGRATIONS.get("ElevenLabs", {}).get(model_id, model_id) or "scribe_v2"
        if not model_id.startswith("scribe"):
            model_id = "scribe_v2"
        data = {"model_id": model_id, "tag_audio_events": "true",
                "diarize": "true" if self.diarize else "false"}
        if self.language and self.language != "auto":
            data["language_code"] = self.language
        self.log.emit(f"ElevenLabs Scribe 正在转写（{model_id}）…")
        with audio.open("rb") as handle:
            resp = safe_request("POST", "https://api.elevenlabs.io/v1/speech-to-text",
                                 headers={"xi-api-key": key}, data=data,
                                 files={"file": (audio.name, handle, "audio/wav")}, timeout=1800)
        if resp.status_code >= 300:
            # scribe_v1 已退役时自动改 scribe_v2 再试一次
            err = response_error(resp)
            if model_id != "scribe_v2" and resp.status_code in (400, 404, 422):
                self.log.emit(f"ElevenLabs 模型「{model_id}」失败，改用 scribe_v2 重试…")
                data["model_id"] = "scribe_v2"
                with audio.open("rb") as handle2:
                    resp = safe_request("POST", 
                        "https://api.elevenlabs.io/v1/speech-to-text",
                        headers={"xi-api-key": key}, data=data,
                        files={"file": (audio.name, handle2, "audio/wav")}, timeout=1800,
                    )
            if resp.status_code >= 300:
                raise ApiFailure(response_error(resp) if resp.status_code >= 300 else err, resp.status_code)
        payload = resp.json()
        segments = words_to_segments(payload.get("words", []))
        text = payload.get("text", "").strip()
        if not segments:
            segments = [{"start": 0, "end": 5, "text": text}]
        lang = None if not self.language or self.language == "auto" else self.language
        plain = normalize_subtitle_text(text, language=lang)
        return segments_to_srt(segments, language=lang), plain, {
            "provider": "ElevenLabs", "response": payload, "language": lang}
    def _gladia(self, audio: Path, key: str):
        headers = {"x-gladia-key": key}
        self.log.emit("上传音频到 Gladia …")
        with audio.open("rb") as handle:
            uploaded = safe_request("POST", "https://api.gladia.io/v2/upload", headers=headers,
                                     files={"audio": (audio.name, handle, "audio/wav")}, timeout=1800)
        if uploaded.status_code >= 300:
            raise ApiFailure(response_error(uploaded), uploaded.status_code)
        audio_url = uploaded.json().get("audio_url")
        body = {"audio_url": audio_url, "subtitles": True,
                "subtitles_config": {"formats": ["srt"]}, "diarization": self.diarize}
        if self.language and self.language != "auto":
            body["language_config"] = {"languages": [self.language], "code_switching": False}
        init = safe_request("POST", "https://api.gladia.io/v2/pre-recorded",
                             headers={**headers, "Content-Type": "application/json"}, json=body, timeout=60)
        if init.status_code >= 300:
            raise ApiFailure(response_error(init), init.status_code)
        job = init.json()
        job_id = job.get("id")
        # 新版返回 result_url（常为 /v2/transcription/{id}）；旧轮询 /v2/pre-recorded/{id} 会接口对不上
        result_url = str(job.get("result_url") or "").strip()
        if not result_url and job_id:
            result_url = f"https://api.gladia.io/v2/transcription/{job_id}"
        try:
            result_url = allow_https_host(result_url, {"api.gladia.io", "gladia.io"})
        except ValueError as exc:
            raise ApiFailure(str(exc)) from exc
        self.log.emit(f"Gladia 任务已提交：{job_id}")
        for _ in range(720):
            if self.cancelled:
                raise RuntimeError("任务已取消")
            result = safe_request("GET", result_url, headers=headers, timeout=30)
            if result.status_code == 404 and job_id and "/transcription/" in result_url:
                # 兼容旧账号仍用 pre-recorded 路径
                result_url = allow_https_host(
                    f"https://api.gladia.io/v2/pre-recorded/{job_id}",
                    {"api.gladia.io", "gladia.io"},
                )
                result = safe_request("GET", result_url, headers=headers, timeout=30)
            if result.status_code >= 300:
                raise ApiFailure(response_error(result), result.status_code)
            payload = result.json()
            status = payload.get("status")
            if status == "done":
                data = payload.get("result") or {}
                transcription = data.get("transcription") or {}
                plain = transcription.get("full_transcript", "") if isinstance(transcription, dict) else str(transcription)
                subtitles = data.get("subtitles") or []
                srt = ""
                if isinstance(subtitles, list):
                    for sub in subtitles:
                        if isinstance(sub, dict) and sub.get("format") == "srt":
                            srt = sub.get("subtitles") or sub.get("content") or ""
                            break
                        if isinstance(sub, str) and "-->" in sub:
                            srt = sub
                            break
                elif isinstance(subtitles, dict):
                    srt = subtitles.get("srt", "")
                lang = None if not self.language or self.language == "auto" else self.language
                if not srt:
                    utterances = transcription.get("utterances", []) if isinstance(transcription, dict) else []
                    srt = (segments_to_srt(utterances, language=lang) if utterances
                           else clean_model_srt(plain, language=lang))
                return clean_model_srt(srt, language=lang), plain, {
                    "provider": "Gladia", "response": payload, "language": lang}
            if status == "error":
                raise ApiFailure(json.dumps(payload, ensure_ascii=False)[:800])
            time.sleep(5)
        raise ApiFailure("Gladia 任务等待超时")

def safe_request(method, url, **kwargs):
    kwargs['allow_redirects'] = False
    return requests.request(method, url, **kwargs)
