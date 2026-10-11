from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from app.services import quiet_process as subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from app.core import repository as repo
from app.services import runtime_log


def file_sha256(path: str | Path) -> str:
    p = Path(path)
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _run_json(cmd: list[str], timeout: int = 30) -> dict[str, Any]:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or "command failed")[-1600:])
    return json.loads(p.stdout or "{}")


def ffprobe_video(path: str) -> dict[str, Any]:
    exe = shutil.which("ffprobe")
    if not exe:
        return {"available": False, "error": "ffprobe not found"}
    data = _run_json([
        exe, "-v", "error", "-show_streams", "-show_format", "-of", "json", path
    ])
    streams = data.get("streams") or []
    video = next((x for x in streams if x.get("codec_type") == "video"), {})
    audio = next((x for x in streams if x.get("codec_type") == "audio"), {})
    duration = float((data.get("format") or {}).get("duration") or video.get("duration") or 0)
    return {
        "available": True,
        "duration": duration,
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "video_codec": video.get("codec_name") or "",
        "audio_codec": audio.get("codec_name") or "",
        "has_video": bool(video),
        "has_audio": bool(audio),
        "sample_rate": int(audio.get("sample_rate") or 0) if audio else 0,
    }


def audio_quality(path: str, start: float | None = None, end: float | None = None) -> dict[str, Any]:
    """Cheap local audio checks inside the final Whisper QC interval when supplied.

    Intro/outro that DaVinci will trim away must not make the usable speech fail QC.
    """
    exe = shutil.which("ffmpeg")
    if not exe:
        return {"available": False, "error": "ffmpeg not found"}
    # volumedetect is inexpensive and gives mean/max volume; enough for silence/clipping hints.
    cmd=[exe, "-hide_banner", "-nostats"]
    if start is not None and end is not None and float(end) > float(start):
        cmd += ["-ss", f"{float(start):.3f}", "-t", f"{float(end)-float(start):.3f}"]
    cmd += ["-i", path, "-vn", "-af", "volumedetect", "-f", "null", "-"]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
    text = (p.stderr or "")[-12000:]
    def _db(name: str):
        m = re.search(rf"{name}:\s*(-?inf|[-\d.]+)\s*dB", text)
        if not m:
            return None
        return -999.0 if m.group(1) == "-inf" else float(m.group(1))
    mean = _db("mean_volume")
    maxv = _db("max_volume")
    return {
        "available": True,
        "mean_db": mean,
        "max_db": maxv,
        "silent": mean is not None and mean < -48,
        "very_quiet": mean is not None and -48 <= mean < -32,
        "clipping_risk": maxv is not None and maxv > -0.2,
        "scope_start": start, "scope_end": end,
    }




def visual_technical_quality(path: str, start: float | None = None, end: float | None = None) -> dict[str, Any]:
    """Cheap ffmpeg black/freeze scan. Advisory unless a large portion is affected."""
    exe=shutil.which('ffmpeg')
    if not exe:return {'available':False,'error':'ffmpeg not found'}
    cmd=[exe,'-hide_banner','-nostats']
    if start is not None and end is not None and float(end)>float(start):
        cmd += ['-ss',f'{float(start):.3f}','-t',f'{float(end)-float(start):.3f}']
    cmd += ['-i',path,'-vf','blackdetect=d=0.25:pix_th=0.10,freezedetect=n=-50dB:d=0.7','-an','-f','null','-']
    p=subprocess.run(cmd,capture_output=True,text=True,timeout=45)
    text=(p.stderr or '')[-30000:]
    blacks=[]; freezes=[]
    for m in re.finditer(r'black_start:([\d.]+)\s+black_end:([\d.]+)\s+black_duration:([\d.]+)',text):
        blacks.append({'start':float(m.group(1)),'end':float(m.group(2)),'duration':float(m.group(3))})
    starts=[float(x) for x in re.findall(r'freeze_start:\s*([\d.]+)',text)]
    ends=[float(x) for x in re.findall(r'freeze_end:\s*([\d.]+)',text)]
    for i,st in enumerate(starts):
        en=ends[i] if i<len(ends) else None
        freezes.append({'start':st,'end':en,'duration':(en-st if en is not None else None)})
    return {'available':True,'black_intervals':blacks,'freeze_intervals':freezes,'scope_start':start,'scope_end':end}


def local_precheck(path: str, speech_start: float | None = None, speech_end: float | None = None) -> dict[str, Any]:
    """Local technical QC.

    File/stream integrity is checked on the whole media. Audio quality + black/freeze anomaly checks
    are *only* evaluated inside Whisper's aligned target-speech interval. This intentionally ignores
    unstable Flow intro/outro frames that will be cut away later.
    """
    p = Path(path)
    result: dict[str, Any] = {
        "path": str(p), "ok": True, "issues": [], "checked_at": time.time(),
        "quality_scope": None,
    }
    if not p.is_file():
        return {**result, "ok": False, "issues": ["文件不存在"]}
    size = p.stat().st_size
    result["size"] = size
    if size <= 1024:
        result["ok"] = False; result["issues"].append("视频文件过小/疑似损坏")
    try:
        probe = ffprobe_video(str(p))
        result["probe"] = probe
        if probe.get("available"):
            if not probe.get("has_video"):
                result["ok"] = False; result["issues"].append("没有视频轨")
            if not probe.get("has_audio"):
                result["ok"] = False; result["issues"].append("没有音频轨")
            dur = float(probe.get("duration") or 0)
            if dur < 1.0:
                result["ok"] = False; result["issues"].append(f"时长异常：{dur:.2f}s")
    except Exception as exc:
        result["ok"] = False; result["issues"].append("视频解码/探测失败")
        result["probe_error"] = str(exc)

    scoped = speech_start is not None and speech_end is not None and float(speech_end) > float(speech_start)
    if not scoped:
        result["quality_scope"] = "等待Whisper有效区间"
        return result

    st,en=float(speech_start),float(speech_end)
    result["quality_scope"]={"speech_start":st,"speech_end":en,"rule":"strict_whisper_range"}
    try:
        aq = audio_quality(str(p),st,en); result["audio"] = aq
        if aq.get("silent"):
            result["ok"] = False; result["issues"].append("有效语音区间音频接近静音")
        elif aq.get("very_quiet"):
            result["issues"].append("有效语音区间人声音量偏低")
        if aq.get("clipping_risk"):
            result["issues"].append("有效语音区间存在爆音/削波风险")
    except Exception as exc:
        result["audio_error"] = str(exc)
    try:
        vq=visual_technical_quality(str(p),st,en); result["visual_technical"]=vq
        black_total=sum(float(x.get("duration") or 0) for x in (vq.get("black_intervals") or []))
        freeze_total=sum(float(x.get("duration") or 0) for x in (vq.get("freeze_intervals") or []))
        scoped_duration=max(0.001,en-st)
        if black_total/scoped_duration>0.45:
            result["ok"]=False; result["issues"].append("有效语音区间大面积黑屏")
        elif black_total>0.5: result["issues"].append("有效语音区间检测到短暂黑屏")
        if freeze_total/scoped_duration>0.55:
            result["ok"]=False; result["issues"].append("有效语音区间长时间冻结")
        elif freeze_total>0.7: result["issues"].append("有效语音区间检测到冻结画面")
    except Exception as exc:
        result["visual_technical_error"]=str(exc)
    return result


def _extract_audio_wav(video_path: str, wav_path: str) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("找不到 ffmpeg")
    p = subprocess.run([
        ffmpeg, "-y", "-i", video_path, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav_path
    ], capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or "")[-1600:])


def _parse_srt(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"\n\s*\n", text.strip())
    words: list[dict[str, Any]] = []
    def ts(v: str) -> float:
        h,m,rest = v.split(":"); s,ms = rest.split(",")
        return int(h)*3600 + int(m)*60 + int(s) + int(ms)/1000
    for b in blocks:
        lines = [x.strip() for x in b.splitlines() if x.strip()]
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        a,btime = [x.strip() for x in lines[1].split("-->",1)]
        st,en = ts(a), ts(btime)
        toks = re.findall(r"[^\W_]+(?:['’][^\W_]+)?", " ".join(lines[2:]), re.UNICODE)
        if not toks:
            continue
        dur = max(0.001, en-st)
        for i,tok in enumerate(toks):
            words.append({"text": tok, "start": st + dur*i/len(toks), "end": st + dur*(i+1)/len(toks)})
    return words


def _norm_token(s: str) -> str:
    return re.sub(r"[^\wÀ-ÖØ-öø-ÿ'’]+", "", (s or "").lower(), flags=re.UNICODE).replace("’", "'")


def _target_tokens(text: str) -> list[str]:
    return [x for x in (_norm_token(x) for x in re.findall(r"\S+", text or "")) if x]


def _levenshtein(a: list[str], b: list[str]) -> int:
    prev = list(range(len(b)+1))
    for i,ca in enumerate(a,1):
        cur = [i]
        for j,cb in enumerate(b,1):
            cur.append(min(cur[-1]+1, prev[j]+1, prev[j-1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _align_summary(target_text: str, words: list[dict[str, Any]]) -> dict[str, Any]:
    """Align known target text to Whisper output and return the target-speaking interval.

    Flow may contain usable/unusable intro/outro speech/noise. QC must use the interval belonging to
    the user's target copy, not blindly the entire media duration. A small best-window search removes
    common Whisper extras before/after the target while preserving the full transcript for audit.
    """
    target = _target_tokens(target_text)
    indexed=[(i,_norm_token(w.get('text',''))) for i,w in enumerate(words)]
    indexed=[x for x in indexed if x[1]]
    recog=[x[1] for x in indexed]
    if not target or not recog:
        return {"match_score": 0.0, "coverage": 0.0, "recognized_text": " ".join(recog), "speech_start": None, "speech_end": None,
                "aligned_word_start":None,"aligned_word_end":None}
    n=len(target); m=len(recog)
    # Most generated clips differ by only a few ASR tokens. Search windows around target length.
    min_len=max(1,n-max(4,int(n*0.25)))
    max_len=min(m,n+max(5,int(n*0.30)))
    candidates=[]
    # Always search candidate sub-windows, even when the full transcript is only a little longer
    # than the target. This is what removes short Flow intro/outro speech and makes the resulting
    # speech_start/speech_end suitable as the *only* visual-QC interval.
    for length in range(min_len,max_len+1):
        for st in range(0,m-length+1):
            candidates.append((st,st+length))
    best=None
    for st,en in candidates or [(0,m)]:
        seq=recog[st:en];dist=_levenshtein(target,seq)
        score=max(0.0,1.0-dist/max(len(target),len(seq),1))
        # Prefer higher language match, then a window length closer to target.
        rank=(score,-abs(len(seq)-n),-st)
        if best is None or rank>best[0]: best=(rank,st,en,score,dist)
    _,st,en,score,dist=best
    orig_start=indexed[st][0];orig_end=indexed[en-1][0]
    aligned=words[orig_start:orig_end+1]
    matched_coverage=max(0.0,1.0-dist/max(len(target),1))
    return {
        "match_score": round(score, 4),
        "coverage": round(min(1.0,matched_coverage), 4),
        "recognized_text": " ".join(w["text"] for w in words),
        "aligned_text": " ".join(w["text"] for w in aligned),
        "speech_start": float(aligned[0]["start"]),
        "speech_end": float(aligned[-1]["end"]),
        "aligned_word_start": int(orig_start),
        "aligned_word_end": int(orig_end),
        "target_words": len(target),
        "recognized_words": len(recog),
    }


def speech_cache_path(video_path: str) -> Path:
    p = Path(video_path)
    return p.with_suffix(p.suffix + ".speech.json")


def analyze_speech(segment_id: int, video_path: str, target_text: str, force: bool = False) -> dict[str, Any]:
    """Run whisper.cpp once, cache the result, and share it with QC + DaVinci.

    Cache validity is tied to the source video SHA-256. A Flow redo automatically invalidates it.
    """
    p = Path(video_path)
    if not p.is_file():
        raise FileNotFoundError(video_path)
    digest = file_sha256(p)
    cached = repo.get_speech_analysis(segment_id)
    if cached and not force and cached["video_hash"] == digest:
        try:
            payload = json.loads(cached["analysis_json"] or "{}")
            if payload:
                return payload
        except Exception:
            pass

    cli = _find_whisper_cli(); model = _find_whisper_model()
    if not cli:
        raise RuntimeError("未找到 whisper-cli；请在系统设置填写 whisper-cli 路径，或安装到 /opt/homebrew/bin/whisper-cli")
    if not model:
        raise RuntimeError("未设置 Whisper 模型路径；Studio 不会自动下载模型")

    with tempfile.TemporaryDirectory(prefix="flowstudio-whisper-") as td:
        td = Path(td); wav = td/"audio.wav"; outbase = td/"whisper"
        _extract_audio_wav(str(p), str(wav))
        lang = str(repo.get_setting("whisper_language", "auto") or "auto").strip()
        cmd = [cli, "-m", model, "-f", str(wav), "-osrt", "-of", str(outbase)]
        if lang and lang != "auto":
            cmd += ["-l", lang]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        srt = Path(str(outbase)+".srt")
        if proc.returncode != 0 or not srt.exists():
            raise RuntimeError("Whisper 识别失败：" + (proc.stderr or proc.stdout or "")[-1600:])
        words = _parse_srt(srt)

    align = _align_summary(target_text, words)
    payload = {
        "segment_id": int(segment_id),
        "video_path": str(p),
        "video_hash": digest,
        "target_text": target_text or "",
        "words": words,
        "created_at": time.time(),
        **align,
    }
    sidecar = speech_cache_path(str(p))
    try:
        sidecar.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        sidecar = Path("")
    repo.save_speech_analysis(segment_id, digest, str(sidecar) if str(sidecar) else "", payload)
    runtime_log.log("speech_analysis_saved", segment_id=segment_id, match_score=payload.get("match_score"), speech_start=payload.get("speech_start"), speech_end=payload.get("speech_end"))
    return payload


def four_qc_frame_positions(speech_start: float, speech_end: float) -> list[float]:
    """Return the *fixed four* AI-QC sample times inside Whisper's effective speech interval.

    V0.13.3 deliberately has no adaptive frame expansion: every video sends exactly four frames
    to AI QC. Intro/outro outside the aligned target speech interval are never sampled.
    """
    if speech_start is None or speech_end is None or speech_end <= speech_start:
        raise ValueError("Whisper 没有提供有效说话区间")
    dur = float(speech_end) - float(speech_start)
    return [float(speech_start) + dur*x for x in (0.08, 0.36, 0.64, 0.92)]


def extract_four_qc_frames(video_path: str, speech_start: float, speech_end: float, out_dir: str | Path) -> list[dict[str, Any]]:
    """Exactly four AI-QC frames, strictly inside Whisper's effective speech range."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("找不到 ffmpeg")
    positions = four_qc_frame_positions(speech_start, speech_end)
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    frames = []
    for idx,sec in enumerate(positions,1):
        dst = out/f"qc_{idx:02d}_{sec:.3f}.jpg"
        p = subprocess.run([ffmpeg, "-y", "-ss", f"{sec:.3f}", "-i", video_path, "-frames:v", "1", "-q:v", "3", str(dst)], capture_output=True, text=True, timeout=30)
        if p.returncode != 0 or not dst.is_file():
            raise RuntimeError("抽帧失败：" + (p.stderr or "")[-800:])
        frames.append({"index": idx, "time": round(sec,3), "path": str(dst)})
    return frames


def run_local_qc(segment_id: int, video_path: str, target_text: str) -> dict[str, Any]:
    # Stage 1: whole-file integrity only. Stage 2: Whisper fixes the only usable QC interval.
    # Stage 3: local audio/black/freeze checks run strictly inside that interval.
    pre = local_precheck(video_path)
    speech = None; speech_error = ""
    if pre.get("ok"):
        try:
            speech = analyze_speech(segment_id, video_path, target_text)
            if speech.get('speech_start') is not None and speech.get('speech_end') is not None:
                pre = local_precheck(video_path, speech.get('speech_start'), speech.get('speech_end'))
        except Exception as exc:
            speech_error = str(exc)
    result = {"precheck": pre, "speech": speech, "speech_error": speech_error, "checked_at": time.time(),
              "qc_scope_rule":"strict_whisper_range"}
    repo.save_local_qc_result(segment_id, result)
    return result
