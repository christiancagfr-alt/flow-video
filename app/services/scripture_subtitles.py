from __future__ import annotations
import json
import re
import wave
from pathlib import Path
from difflib import SequenceMatcher
from app.services.reels.captions import parse_srt, events_to_srt
from app.core import database
import shutil

FPS = 25.0
TIMELINE_START_FRAME = 90000  # 01:00:00:00 in DaVinci Resolve
MAX_LINES_PER_SUBTITLE = 3     # Strict 3-line limit for background box fitting

_FW_MODEL = None


def _get_fw_model():
    """Lazy-load bundled faster-whisper base model for fallback when cloud ASR drops words."""
    global _FW_MODEL
    if _FW_MODEL is not None:
        return _FW_MODEL
    try:
        import platform
        import sys
        app_root = Path(__file__).resolve().parents[2]
        is_x86_mac = (platform.system() == "Darwin" and platform.machine().lower() == "x86_64")
        asr_sub = "bundled-components/packaging/asr-libs-x86_64" if is_x86_mac and (app_root / "bundled-components/packaging/asr-libs-x86_64").exists() else "bundled-components/packaging/asr-libs"
        asr_libs = app_root / asr_sub
        if not asr_libs.exists():
            asr_libs = Path("/Applications/Flow Studio.app/Contents/Resources/bundled-components/packaging/asr-libs")
        if asr_libs.exists() and str(asr_libs) not in sys.path:
            sys.path.insert(0, str(asr_libs))
        from faster_whisper import WhisperModel
        model_root = app_root / "bundled-components/packaging/models/hub/models--Systran--faster-whisper-base/snapshots"
        if not model_root.exists():
            model_root = Path("/Applications/Flow Studio.app/Contents/Resources/bundled-components/packaging/models/hub/models--Systran--faster-whisper-base/snapshots")
        snaps = list(model_root.glob("*")) if model_root.exists() else []
        if snaps:
            _FW_MODEL = WhisperModel(str(snaps[0]), device="cpu", compute_type="int8")
    except Exception:
        _FW_MODEL = False
    return _FW_MODEL


def _transcribe_wav_slice(wav_path: Path, start_sec: float, end_sec: float) -> list[tuple[float, float, str]]:
    """Transcribe [start_sec, end_sec] of a 48kHz WAV file using local faster-whisper."""
    model = _get_fw_model()
    if not model:
        return []
    try:
        import numpy as np
        with wave.open(str(wav_path), "rb") as wf:
            sr = wf.getframerate()
            ch = wf.getnchannels()
            n_frames = wf.getnframes()
            s_frame = max(0, int(start_sec * sr))
            e_frame = min(n_frames, int(end_sec * sr))
            if e_frame <= s_frame:
                return []
            wf.setpos(s_frame)
            raw = wf.readframes(e_frame - s_frame)
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if ch > 1:
            audio = audio.reshape(-1, ch).mean(axis=1)
        if sr == 48000:
            audio = audio[::3]
        elif sr != 16000:
            idx = np.round(np.arange(0, len(audio), sr / 16000.0)).astype(int)
            idx = idx[idx < len(audio)]
            audio = audio[idx]
        segs, _ = model.transcribe(audio, language="sw", word_timestamps=True, vad_filter=True)
        words = []
        for s in segs:
            for w in (s.words or []):
                words.append((round(start_sec + float(w.start), 3), round(start_sec + float(w.end), 3), w.word.strip()))
        return words
    except Exception:
        return []


def parse_ini(path: Path) -> dict[str, str]:
    d = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip()
    return d


def clean_word(w: str) -> str:
    return re.sub(r"[^\w]", "", str(w)).lower()


def line_wrap_scripture(quote_text: str, max_len: int = 28) -> str:
    """Break scripture text into balanced lines for 9:16 vertical video.
    
    Target format: “<quote>” (SUV)
    Strictly ensures no line exceeds max_len (default 28 chars for 9:16 screen).
    """
    clean_quote = re.sub(r"([,;:])(?=[A-Za-z])", r"\1 ", quote_text)
    clean_quote = re.sub(r"\s+([.,;:!?])", r"\1", clean_quote)
    clean_quote = re.sub(r"\s+", " ", clean_quote).strip()
    clean_quote = re.sub(r'^[“”"\'\s]+|[“”"\'\s]+$', "", clean_quote).strip()
    
    words = clean_quote.split()
    if not words:
        return f'“{clean_quote}” (SUV)'
        
    lines = []
    cur_words = []
    
    def cur_str(words_list, is_first=False, is_last=False):
        s = " ".join(words_list)
        if is_first:
            s = "“" + s
        if is_last:
            s = s + "” (SUV)"
        return s

    i = 0
    while i < len(words):
        cur_words.append(words[i])
        is_first = (len(lines) == 0)
        is_last = (i == len(words) - 1)
        
        current_len = len(cur_str(cur_words, is_first, is_last))
        
        if i + 1 < len(words):
            next_is_last = (i + 1 == len(words) - 1)
            next_len = len(cur_str(cur_words + [words[i+1]], is_first, next_is_last))
            
            w = words[i]
            ends_punct = w[-1] in ",;:!?"
            
            if next_len > max_len:
                lines.append(cur_str(cur_words, is_first, False))
                cur_words = []
            elif ends_punct and current_len >= 16:
                lines.append(cur_str(cur_words, is_first, False))
                cur_words = []
        else:
            if current_len > max_len and len(cur_words) > 1:
                last_w = cur_words.pop()
                lines.append(cur_str(cur_words, is_first, False))
                lines.append(cur_str([last_w], False, True))
            else:
                lines.append(cur_str(cur_words, is_first, True))
            cur_words = []
        i += 1
        
    return "\n".join(lines)


def split_lines_into_balanced_chunks(lines: list[str], max_lines: int = 3) -> list[list[str]]:
    """Split wrapped scripture lines so each chunk never exceeds max_lines (default 3)."""
    total = len(lines)
    if total <= max_lines:
        return [lines]
    chunks = []
    i = 0
    rem = total
    while rem > 0:
        if rem == 4:
            take = 2
        elif rem >= 3:
            take = 3
        else:
            take = rem
        chunks.append(lines[i : i + take])
        i += take
        rem -= take
    return chunks


def char_dp_align_chunks(
    chunks: list[list[str]],
    cand_words: list[tuple[float, float, str]],
) -> tuple[float, float, float, list[tuple[float, float]]]:
    """Align each split subtitle chunk to exact spoken timestamps using character-level semi-global DP.
    
    Immune to ASR word-boundary merges/splits and never steps backward into previous sentences.
    Returns (char_coverage, normalized_score, max_matched_word_dur, chunk_start_end_list).
    """
    chunk_clean_strs = []
    for c in chunks:
        c_raw = " ".join(c)
        c_raw = re.sub(r"\(SUV\)\s*$", "", c_raw).strip()
        w_list = [clean_word(w) for w in c_raw.split() if clean_word(w)]
        chunk_clean_strs.append("".join(w_list))
    q_str = "".join(chunk_clean_strs)
    M = len(q_str)
    if M == 0 or not cand_words:
        return 0.0, 0.0, 99.0, []

    cand_chars = []
    for w_i, (ws, we, wtxt) in enumerate(cand_words):
        cw = clean_word(wtxt)
        if not cw:
            continue
        L = len(cw)
        for k, ch in enumerate(cw):
            cs = ws + (we - ws) * (k / L)
            ce = ws + (we - ws) * ((k + 1) / L)
            cand_chars.append((ch, cs, ce, w_i))
    N = len(cand_chars)
    if N == 0:
        return 0.0, 0.0, 99.0, []

    INF = -1e9
    dp = [[INF] * (N + 1) for _ in range(M + 1)]
    back = [[0] * (N + 1) for _ in range(M + 1)]  # 1=diag, 2=up(skip q), 3=left(skip cand)
    for j in range(N + 1):
        dp[0][j] = 0.0

    for i in range(1, M + 1):
        qc = q_str[i - 1]
        dp_i = dp[i]
        dp_prev = dp[i - 1]
        back_i = back[i]
        for j in range(1, N + 1):
            cc, cs, ce, wi = cand_chars[j - 1]
            if qc == cc:
                m_score = 2.0
            elif (
                (qc in "dz" and cc in "dz")
                or (qc in "lr" and cc in "lr")
                or (qc in "ie" and cc in "ie")
                or (qc in "uo" and cc in "uo")
                or (qc in "jg" and cc in "jg")
            ):
                m_score = 1.2
            else:
                m_score = -1.0

            gap_pen = 0.0
            if i > 1 and j > 1:
                dt = cs - cand_chars[j - 2][2]
                if dt > 1.2:
                    gap_pen = (dt - 1.2) * 2.5

            v_diag = dp_prev[j - 1] + m_score - gap_pen
            v_up = dp_prev[j] - 0.8
            v_left = dp_i[j - 1] - (0.9 + gap_pen)

            if v_diag >= v_up and v_diag >= v_left:
                dp_i[j] = v_diag
                back_i[j] = 1
            elif v_up >= v_left:
                dp_i[j] = v_up
                back_i[j] = 2
            else:
                dp_i[j] = v_left
                back_i[j] = 3

    best_j = max(range(1, N + 1), key=lambda j: dp[M][j])
    best_score = dp[M][best_j]

    q_to_cand = [None] * M
    matched_chars = 0
    matched_word_idxs = set()
    i, j = M, best_j
    while i > 0 and j > 0:
        b = back[i][j]
        if b == 1:
            q_to_cand[i - 1] = j - 1
            matched_word_idxs.add(cand_chars[j - 1][3])
            if q_str[i - 1] == cand_chars[j - 1][0]:
                matched_chars += 1
            i -= 1
            j -= 1
        elif b == 2:
            q_to_cand[i - 1] = j - 1
            i -= 1
        else:
            j -= 1

    char_cov = matched_chars / max(1, M)
    max_w_dur = max((cand_words[wi][1] - cand_words[wi][0] for wi in matched_word_idxs), default=0.0)

    chunk_times = []
    offset = 0
    for c_str in chunk_clean_strs:
        c_len = len(c_str)
        c_indices = [q_to_cand[k] for k in range(offset, offset + c_len) if q_to_cand[k] is not None]
        offset += c_len
        if c_indices:
            first_ci = c_indices[0]
            last_ci = c_indices[-1]
            w_first = cand_chars[first_ci][3]
            w_last = cand_chars[last_ci][3]
            t_s = cand_words[w_first][0] if (first_ci == 0 or cand_chars[first_ci - 1][3] != w_first) else cand_chars[first_ci][1]
            t_e = cand_words[w_last][1] if (last_ci == N - 1 or cand_chars[last_ci + 1][3] != w_last) else cand_chars[last_ci][2]
            chunk_times.append((t_s, t_e))
        else:
            chunk_times.append((0.0, 0.0))

    # Seamless handoff between consecutive chunks of the same scripture
    for k in range(len(chunk_times) - 1):
        if chunk_times[k][1] > chunk_times[k + 1][0]:
            mid = (chunk_times[k][1] + chunk_times[k + 1][0]) / 2.0
            chunk_times[k] = (chunk_times[k][0], mid)
            chunk_times[k + 1] = (mid, chunk_times[k + 1][1])
        elif chunk_times[k + 1][0] - chunk_times[k][1] <= 0.6:
            chunk_times[k] = (chunk_times[k][0], chunk_times[k + 1][0])

    return char_cov, best_score / max(1, M), max_w_dur, chunk_times


_SPEAKER_INTRO_RE = re.compile(
    r"^(?:[,，\s]*(?:Maandiko(?:\s+Matakatifu)?|Biblia|Neno(?:\s+la\s+Mungu)?|Bwana(?:\s+Yesu(?:\s+Kristo)?)?|Yesu(?:\s+Kristo)?|Mungu|Mtume\s+\w+|Paulo|Petro|Yakobo|Yohana|Daudi|Nabii\s+\w+|Mithali|Zaburi)?\s*"
    r"(?:inasema|yanasema|anasema|alisema|walisema|inatuambia|anatuambia|inatukumbusha|anatukumbusha|akisema|aliandika|imeandikwa|alieleza)(?:\s+hivi|\s+kwamba|\s+ya\s+kwamba)?\s*[:：,，]\s*)+",
    flags=re.IGNORECASE,
)


def _strip_trailing_bible_citation(seg: str) -> str:
    """Strip a trailing Bible book + chapter:verse reference right before `(SUV)`.

    Handles forms such as:
      - `” — Mathayo 24:44`
      - `!” — Mathayo 25:6`
      - `. — 1 Petro 5:6.`
      - `. Mithali 3:5.`
      - `” (Yohana 3:16-17)`
    while preserving any closing quote or period of the scripture text itself.
    """
    s = seg.rstrip()
    # 1. Parenthesized reference at tail: `(Mathayo 24:44)` / `（约翰福音 3:16）`
    s = re.sub(
        r"\s*[\(（][^\)）\r\n]{1,50}?\b\d{1,3}\s*[:：]\s*\d{1,3}(?:\s*[-–—~]\s*\d{1,3})?[^\)）\r\n]*[\)）][\s—–\-−.,，。;；]*$",
        "",
        s,
    )
    # 2. Dash-prefixed reference at tail: `— Mathayo 24:44`, `-- 1 Petro 5:6.`
    s = re.sub(
        r"\s*(?:[—–−]+|--+|(?<=\s)-)\s*(?:[1-3I]{1,3}\s+)?[^\d:：\r\n\"“”]{1,40}?\b\d{1,3}\s*[:：]\s*\d{1,3}(?:\s*[-–—~]\s*\d{1,3})?[a-zA-Z]?[\s—–\-−.,，。;；]*$",
        "",
        s,
    )
    # 3. Reference directly after closing quote without dash: `” Mathayo 24:44`
    s = re.sub(
        r"(?<=[”\"“」』])\s*(?:[1-3I]{1,3}\s+)?(?:[A-Za-zÀ-ÿ\u4e00-\u9fff]+\s+){1,4}\d{1,3}\s*[:：]\s*\d{1,3}(?:\s*[-–—~]\s*\d{1,3})?[a-zA-Z]?[\s—–\-−.,，。;；]*$",
        "",
        s,
    )
    # 4. Reference after sentence-ending punctuation on unquoted verse: `. Mithali 3:5.`
    s = re.sub(
        r"(?<=[.!?。！？\n])\s*(?:[1-3I]{1,3}\s+)?[A-ZÀ-Ý\u4e00-\u9fff][A-Za-zÀ-ÿ\u4e00-\u9fff]*(?:\s+(?:wa\s+|ya\s+|la\s+|Ulio\s+)?[A-ZÀ-Ý\u4e00-\u9fff][A-Za-zÀ-ÿ\u4e00-\u9fff]*){0,2}\s+\d{1,3}\s*[:：]\s*\d{1,3}(?:\s*[-–—~]\s*\d{1,3})?[a-zA-Z]?[\s—–\-−.,，。;；]*$",
        "",
        s,
    )
    return s.rstrip()


def extract_scriptures_from_text(orig: str, allow_any_quote: bool = False) -> list[dict]:
    """Extract `(SUV)` / `（SUV）` scripture quotes from manuscript text and wrap them into 9:16 3-line subtitle chunks.

    Supports:
    1. Quoted scriptures with or without trailing citation before `(SUV)`:
       `“...” (SUV)`, `“...” — Mathayo 24:44（SUV）`, `“...” (1 Petro 5:8,SUV)`
    2. Unquoted scriptures (or missing opening quote) with prefix or trailing citation:
       `Waefeso 6:18 kwa sala zote... (SUV)`
       `Biblia inasema: Mtumaini BWANA... Mithali 3:5.（SUV）`
       `Na kukawa na kelele...!” — Mathayo 25:6(SUV)`
    """
    text = str(orig or "").strip()
    if not text:
        return []
    quotes: list[str] = []
    if "SUV" in text or "（SUV）" in text:
        suv_matches = list(re.finditer(r"[\(（][^\)）]*?SUV[^\)）]*?[\)）]", text))
        for idx, suv_m in enumerate(suv_matches):
            seg_start = suv_matches[idx - 1].end() if idx > 0 else 0
            raw_seg = text[seg_start : suv_m.start()]
            seg = _strip_trailing_bible_citation(raw_seg)
            q_txt = ""

            # 1. Try explicit paired quotes right at the end of `seg`
            q_m = list(re.finditer(r'[“\"「『]([^“\"”「」『』\r\n]+?)[”\"“」』][\s—–\-−:;,.，。]*$', seg))
            if not q_m:
                q_m = list(re.finditer(r'[“\"「『]([^“\"”「」『』]+?)[”\"“」』][\s—–\-−:;,.，。]*$', seg))
            if q_m:
                cand = q_m[-1].group(1).strip()
                if not re.search(r"\b\d{1,3}\s*[:：]\s*\d{1,3}\b", cand):
                    q_txt = cand

            # 2. If unquoted (or opening quote was omitted), check the last 1-3 lines for a prefix `chapter:verse`
            non_empty_lines = [ln.strip() for ln in seg.splitlines() if ln.strip()]
            tail_seg = "\n".join(non_empty_lines[-3:]) if non_empty_lines else seg
            intro_pat = re.compile(
                r"(?:Biblia|Maandiko|Neno(?:\s+la\s+Mungu)?|Bwana(?:\s+Yesu)?|Yesu|Mungu|alisema|anasema|inasema|yanasema|inatuambia|inatukumbusha|imeandikwa|hivi)[^:：\r\n]{0,24}[:：]\s*",
                flags=re.IGNORECASE,
            )
            if not q_txt:
                cv_m = list(
                    re.finditer(
                        r"\b\d{1,3}\s*[:：]\s*\d{1,3}(?:\s*[-–—]\s*\d{1,3})?[.,，\s]*",
                        tail_seg,
                        flags=re.IGNORECASE,
                    )
                )
                if cv_m:
                    after_cv = tail_seg[cv_m[-1].end() :].strip()
                    after_cv = _SPEAKER_INTRO_RE.sub("", after_cv).strip()
                    later_intros = list(intro_pat.finditer(after_cv))
                    if later_intros:
                        after_cv = after_cv[later_intros[-1].end() :].strip()
                    after_cv = re.sub(r'^[“”"\'\s]+|[“”"\'\s]+$', "", after_cv).strip()
                    if after_cv and not re.fullmatch(r"[\d\W]+", after_cv):
                        q_txt = after_cv

            # 3. Fallback: check the last line before (SUV) for the last speaker intro colon or unquoted sentence
            if not q_txt and non_empty_lines:
                last_line = non_empty_lines[-1]
                intro_matches = list(intro_pat.finditer(last_line))
                if intro_matches:
                    cand = last_line[intro_matches[-1].end() :].strip()
                elif ":" in last_line or "：" in last_line:
                    # Split only on non-chapter:verse colons
                    parts = re.split(r"(?<!\d)[:：](?!\d)", last_line)
                    cand = parts[-1].strip() if len(parts) > 1 else last_line
                else:
                    cand = last_line
                cand = _SPEAKER_INTRO_RE.sub("", cand).strip()
                cand = re.sub(r'^[“”"\'\s]+|[“”"\'\s]+$', "", cand).strip()
                if cand and not re.fullmatch(r"[\d\W]+", cand):
                    q_txt = cand

            if q_txt:
                q_txt = _SPEAKER_INTRO_RE.sub("", q_txt).strip()
                q_txt = re.sub(r'^[“”"\'\s]+|[“”"\'\s]+$', "", q_txt).strip()
                if q_txt and not re.fullmatch(r"[\d\W]+", q_txt):
                    quotes.append(q_txt)

    results = []
    for q_txt in quotes:
        wrapped = line_wrap_scripture(q_txt)
        lines = [ln.strip() for ln in wrapped.split("\n") if ln.strip()]
        chunks = split_lines_into_balanced_chunks(lines, max_lines=MAX_LINES_PER_SUBTITLE)
        results.append({
            "quote": q_txt,
            "wrapped": wrapped,
            "lines": lines,
            "chunks": chunks,
        })
    return results


def _write_scripture_videos_ini(target_dir: Path, batch_id: str, video_ids: list[int] | set[int]) -> None:
    """Persist the exact video_ids that Flow Studio generated scripture subtitles for."""
    from app.services import resolve_daily as daily
    sorted_ids = sorted({int(v) for v in (video_ids or ()) if int(v) > 0})
    daily.atomic_pairs(target_dir / "scripture_videos.ini", {
        "batch_id": str(batch_id or ""),
        "subtitle_video_ids": ",".join(str(v) for v in sorted_ids),
        "count": str(len(sorted_ids)),
    })


def resolve_batch_subtitle_video_ids(
    batch_id: str,
    attempt_dir: Path | None = None,
    video_ids: list[int] | None = None,
) -> list[int]:
    """Return the exact video_ids in this batch for which Flow Studio imported scripture subtitles.

    Uses the persisted `scripture_videos.ini` written at subtitle-generation time (O(1), zero Resolve scanning),
    with a one-time DB fallback for historical batches that already generated a `.srt` before `scripture_videos.ini` existed.
    """
    from app.services import resolve_daily as daily
    b_root = daily.bridge_root() / "v0_5_0" / "batches" / str(batch_id)
    cand_inis = []
    if attempt_dir:
        cand_inis.append(Path(attempt_dir) / "scripture_videos.ini")
    cand_inis.append(b_root / "scripture_videos.ini")

    allowed = {int(v) for v in video_ids} if video_ids is not None else None
    for ini_p in cand_inis:
        if ini_p.is_file():
            info = daily.read_pairs(ini_p)
            raw = str(info.get("subtitle_video_ids") or "").strip()
            out = [int(tok) for tok in raw.split(",") if tok.strip().isdigit()]
            if allowed is not None:
                out = [v for v in out if v in allowed]
            return sorted(set(out))

    # Historical fallback: only if Flow Studio actually generated a scripture .srt for this batch
    has_srt = False
    if attempt_dir and any(Path(attempt_dir).glob("scriptures_*.srt")):
        has_srt = True
    elif b_root.is_dir() and (any(b_root.glob("经文字幕_*.srt")) or any(b_root.glob("autoedit/*/scriptures_*.srt"))):
        has_srt = True
    if not has_srt:
        return []

    check_ids = sorted(allowed) if allowed is not None else []
    if not check_ids:
        manifest = daily.read_pairs(b_root / "manifest.ini")
        check_ids = [
            int(manifest[f"v{i}_id"])
            for i in range(1, int(manifest.get("video_count") or 0) + 1)
            if str(manifest.get(f"v{i}_id") or "").isdigit()
        ]
    if not check_ids:
        return []

    matched: list[int] = []
    with database.connect() as con:
        rows = con.execute(
            f"SELECT id, original_script, script, source_task_id FROM videos WHERE id IN ({','.join('?' * len(check_ids))})",
            check_ids,
        ).fetchall()
    for r in rows:
        orig = (r["original_script"] or r["script"] or "").strip()
        is_custom = str(r["source_task_id"] or "") == "CUSTOM_TASK"
        if extract_scriptures_from_text(orig, allow_any_quote=is_custom):
            matched.append(int(r["id"]))
    matched.sort()
    try:
        if attempt_dir and Path(attempt_dir).is_dir():
            _write_scripture_videos_ini(Path(attempt_dir), batch_id, matched)
        if b_root.is_dir():
            _write_scripture_videos_ini(b_root, batch_id, matched)
    except OSError:
        pass
    return matched


def _load_post_cleanup_frame_mapper(attempt_dir: Path, task: dict):
    """Build a WAV-frame -> post-cleanup timeline-frame mapper when `cleaned.ini` / `cleaned_clips.ini` exist."""
    batch_root = attempt_dir.parent.parent if attempt_dir.parent.name == "autoedit" else attempt_dir
    cleaned_ini = parse_ini(attempt_dir / "cleaned.ini") or parse_ini(batch_root / "cleaned.ini")
    clips_ini = parse_ini(attempt_dir / "cleaned_clips.ini") or parse_ini(batch_root / "cleaned_clips.ini")
    src_map_ini = parse_ini(attempt_dir / "wav_source_map.ini") or parse_ini(batch_root / "wav_source_map.ini")

    wav_base_by_vid_path: dict[tuple[int, str], list[int]] = {}
    try:
        src_cnt = int(src_map_ini.get("count") or 0)
    except (TypeError, ValueError):
        src_cnt = 0
    for idx in range(1, src_cnt + 1):
        sp = f"s{idx}_"
        try:
            svid = int(src_map_ini.get(sp + "video_id") or 0)
            spath = str(src_map_ini.get(sp + "path") or "").strip()
            sbase = int(src_map_ini.get(sp + "wav_base_s") or 0)
            if svid > 0 and spath and sbase > 0:
                wav_base_by_vid_path.setdefault((svid, spath), []).append(sbase)
        except (TypeError, ValueError):
            continue

    skipped_vids: set[int] = set()
    post_video_ranges: dict[int, tuple[int, int]] = {}
    if cleaned_ini:
        try:
            v_cnt = int(cleaned_ini.get("video_count") or 0)
        except (TypeError, ValueError):
            v_cnt = 0
        for idx in range(1, v_cnt + 1):
            pre = f"v{idx}_"
            raw_vid = cleaned_ini.get(pre + "id")
            if not raw_vid or not str(raw_vid).isdigit():
                continue
            vid_i = int(raw_vid)
            if str(cleaned_ini.get(pre + "skip") or "").lower() == "true":
                skipped_vids.add(vid_i)
                continue
            try:
                ps = int(cleaned_ini.get(pre + "start") or 0)
                pe = int(cleaned_ini.get(pre + "end") or 0)
                if pe > ps > 0:
                    post_video_ranges[vid_i] = (ps, pe)
            except (TypeError, ValueError):
                continue

    clips_by_vid: dict[int, list[dict]] = {}
    try:
        c_cnt = int(clips_ini.get("clip_count") or 0)
    except (TypeError, ValueError):
        c_cnt = 0
    used_path_occ: dict[tuple[int, str], int] = {}
    for idx in range(1, c_cnt + 1):
        cp = f"c{idx}_"
        try:
            cvid = int(clips_ini.get(cp + "video_id") or 0)
            post_s = int(clips_ini.get(cp + "post_s") or 0)
            post_e = int(clips_ini.get(cp + "post_e") or 0)
        except (TypeError, ValueError):
            continue
        if cvid <= 0 or post_e <= post_s:
            continue
        dur = post_e - post_s
        cpath = str(clips_ini.get(cp + "path") or "").strip()
        try:
            left_off = int(clips_ini.get(cp + "left_offset") or 0)
        except (TypeError, ValueError):
            left_off = 0
        wav_s = None
        raw_pre_s = clips_ini.get(cp + "pre_s")
        if raw_pre_s is not None and str(raw_pre_s).strip().lstrip("-").isdigit():
            val_pre = int(str(raw_pre_s).strip())
            if val_pre > 0:
                wav_s = val_pre
        if wav_s is None:
            bases = wav_base_by_vid_path.get((cvid, cpath))
            if bases:
                occ = used_path_occ.get((cvid, cpath), 0)
                base_s = bases[min(occ, len(bases) - 1)]
                wav_s = base_s + left_off
        if wav_s is not None and wav_s > 0:
            clips_by_vid.setdefault(cvid, []).append(
                {
                    "wav_s": wav_s,
                    "wav_e": wav_s + dur,
                    "post_s": post_s,
                    "post_e": post_e,
                }
            )
    for cvid, clist in clips_by_vid.items():
        clist.sort(key=lambda x: (x["wav_s"], x["post_s"]))

    def map_frame(vid: int, wav_frame: int, pre_v_start: int, pre_v_end: int) -> int | None:
        if vid in skipped_vids:
            return None
        clist = clips_by_vid.get(vid)
        if clist:
            for cl in clist:
                if cl["wav_s"] <= wav_frame <= cl["wav_e"]:
                    return cl["post_s"] + (wav_frame - cl["wav_s"])
            if wav_frame < clist[0]["wav_s"]:
                return max(clist[0]["post_s"], clist[0]["post_s"] + (wav_frame - clist[0]["wav_s"]))
            for idx_c in range(len(clist) - 1):
                if clist[idx_c]["wav_e"] < wav_frame < clist[idx_c + 1]["wav_s"]:
                    return clist[idx_c]["post_e"]
            return min(clist[-1]["post_e"], clist[-1]["post_e"] + (wav_frame - clist[-1]["wav_e"]))
        v_post = post_video_ranges.get(vid)
        if v_post:
            post_s, post_e = v_post
            pre_dur = max(1, pre_v_end - pre_v_start)
            post_dur = max(1, post_e - post_s)
            rel = max(0.0, min(1.0, (wav_frame - pre_v_start) / float(pre_dur)))
            return int(round(post_s + rel * post_dur))
        return wav_frame

    return map_frame


def _extract_events_for_attempt(
    attempt_dir: Path,
    fps: float = 25.0,
    matched_video_ids: set[int] | None = None,
) -> list[tuple[float, float, str]]:
    """Extract scripture subtitle events for a single autoedit attempt directory."""
    task_json_path = attempt_dir / "task.json"
    if not task_json_path.exists():
        return []
        
    with open(task_json_path, encoding="utf-8") as f:
        task = json.load(f)
    frame_mapper = _load_post_cleanup_frame_mapper(attempt_dir, task)
        
    parsed_srts_cache: dict[Path, list] = {}

    def get_parsed_srt(srt_path: Path) -> list:
        if srt_path not in parsed_srts_cache:
            if srt_path.exists():
                parsed_srts_cache[srt_path] = parse_srt(srt_path.read_text(encoding="utf-8"))
            else:
                parsed_srts_cache[srt_path] = []
        return parsed_srts_cache[srt_path]

    video_entries = {v["video_id"]: v for v in task.get("videos", [])}
    events = []
    
    with database.connect() as con:
        for vid, v in video_entries.items():
            align_ini = attempt_dir / f"video_{vid}_alignment.ini"
            align_data = parse_ini(align_ini)
            
            row = con.execute("SELECT original_script, script, source_task_id FROM videos WHERE id=?", (vid,)).fetchone()
            orig = (row["original_script"] if row else None) or v.get("script") or ""
            is_custom = bool(row and str(row["source_task_id"] or "") == "CUSTOM_TASK")
            extracted_list = extract_scriptures_from_text(orig, allow_any_quote=is_custom)
            if not extracted_list:
                continue
                
            carried_wav = align_data.get("audio_wav", "")
            wav_attempt_dir = (
                Path(carried_wav).parent.parent
                if (carried_wav and Path(carried_wav).parent.parent.exists())
                else attempt_dir
            )
            wav_whisper_dir = wav_attempt_dir / "whisper"
            audio_part = int(align_data.get("audio_part", 1))

            render_part_ini = wav_attempt_dir / f"timeline_render_part_{audio_part:03d}.ini"
            if not render_part_ini.exists():
                render_part_ini = wav_attempt_dir / "timeline_render.ini"
            part_start_frame = int(
                parse_ini(render_part_ini).get("start", task.get("batch_start_frame", TIMELINE_START_FRAME))
            )

            v_start_sec = (v["timeline_start_frame"] - part_start_frame) / fps
            v_end_sec = (v["timeline_end_frame"] - part_start_frame) / fps

            retry_files = sorted(wav_whisper_dir.glob(f"video_{vid}_retry_*.srt"))
            if retry_files:
                candidate_words = get_parsed_srt(retry_files[-1])
                base_offset_sec = v["timeline_start_frame"] / fps
            else:
                srt_name = "timeline.srt" if audio_part == 1 else f"timeline_part_{audio_part:03d}.srt"
                words = get_parsed_srt(wav_whisper_dir / srt_name)
                base_offset_sec = part_start_frame / fps
                candidate_words = [w for w in words if v_start_sec - 1.0 <= w[0] <= v_end_sec + 1.0]

            fw_cands_cache = None

            for item in extracted_list:
                chunks = item["chunks"]

                cov, score, max_w, chunk_times = char_dp_align_chunks(chunks, candidate_words)
                time_base_sec = base_offset_sec

                # If cloud ASR dropped words or stretched a single token >1.5s, recover exact words via local faster-whisper
                if (cov < 0.82 or score < 1.35 or max_w > 1.5) and carried_wav and Path(carried_wav).exists():
                    if fw_cands_cache is None:
                        fw_cache_file = wav_whisper_dir / f"video_{vid}_fw_words.json"
                        if fw_cache_file.exists():
                            try:
                                fw_cands_cache = [tuple(x) for x in json.loads(fw_cache_file.read_text(encoding="utf-8"))]
                            except Exception:
                                fw_cands_cache = []
                        if not fw_cands_cache:
                            fw_cands_cache = _transcribe_wav_slice(Path(carried_wav), v_start_sec, v_end_sec)
                            if fw_cands_cache:
                                try:
                                    fw_cache_file.write_text(json.dumps(fw_cands_cache, ensure_ascii=False), encoding="utf-8")
                                except Exception:
                                    pass
                    if fw_cands_cache:
                        fw_cov, fw_score, fw_max_w, fw_chunk_times = char_dp_align_chunks(chunks, fw_cands_cache)
                        if fw_score > score or max_w > 1.5:
                            cov, score, max_w, chunk_times = fw_cov, fw_score, fw_max_w, fw_chunk_times
                            time_base_sec = part_start_frame / fps

                if not chunk_times:
                    continue

                for c_i, (c_lines, (m_start, m_end)) in enumerate(zip(chunks, chunk_times)):
                    if m_end <= 0.0 and m_start <= 0.0:
                        continue
                    abs_start_sec = time_base_sec + m_start
                    abs_end_sec = time_base_sec + m_end
                    abs_start_frame = int(round(abs_start_sec * fps))
                    abs_end_frame = int(round(abs_end_sec * fps))

                    mapped_start = frame_mapper(int(vid), abs_start_frame, int(v["timeline_start_frame"]), int(v["timeline_end_frame"]))
                    mapped_end = frame_mapper(int(vid), abs_end_frame, int(v["timeline_start_frame"]), int(v["timeline_end_frame"]))
                    if mapped_start is None or mapped_end is None:
                        continue
                    abs_start_frame = mapped_start
                    abs_end_frame = max(mapped_start, mapped_end)

                    rel_to_tl_start = max(0.0, (abs_start_frame - TIMELINE_START_FRAME) / fps)
                    min_dur = 0.8 if len(chunks) == 1 else 0.5
                    rel_to_tl_end = max(rel_to_tl_start + min_dur, (abs_end_frame - TIMELINE_START_FRAME) / fps)

                    c_text = "\n".join(c_lines)
                    events.append((rel_to_tl_start, rel_to_tl_end, c_text))
                    if matched_video_ids is not None:
                        matched_video_ids.add(int(vid))
                    
    return events


def generate_direct_imported_scripture_subtitles(batch_id: str, work_date: str, fps: float = 25.0, progress_cb=None) -> tuple[Path | None, Path | None, str | None]:
    """Directly align and generate scripture subtitles for an IMPORTED batch without running DaVinci autoedit.

    Returns `(srt_path, autoedit_ini_path, attempt_id)`.
    """
    import subprocess
    import tempfile
    import uuid
    from app.core import repository as repo
    from app.services import resolve_daily as daily, resolve_autoedit, credential_pool, custom_task

    bridge_root = daily.bridge_root()
    batch_dir = bridge_root / "v0_5_0" / "batches" / batch_id
    cache_dir = batch_dir / "direct_scriptures_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    with database.connect() as con:
        b_row = con.execute("SELECT * FROM davinci_batches WHERE batch_id=?", (batch_id,)).fetchone()
        if not b_row:
            return None, None, None
        vs_rows = con.execute(
            "SELECT * FROM davinci_video_state WHERE batch_id=? AND timeline_imported=1 ORDER BY timeline_start_frame ASC, video_id ASC",
            (batch_id,),
        ).fetchall()
        video_tasks = []
        for vr in vs_rows:
            vid = int(vr["video_id"])
            v_info = con.execute("SELECT id, original_script, script, source_task_id FROM videos WHERE id=?", (vid,)).fetchone()
            if not v_info:
                continue
            orig = (v_info["original_script"] or v_info["script"] or "").strip()
            extracted = extract_scriptures_from_text(orig)
            if not extracted:
                continue
            segs = con.execute(
                "SELECT flow_output_path FROM flow_segments WHERE video_id=? ORDER BY seg_seq ASC",
                (vid,),
            ).fetchall()
            media_paths = [str(s["flow_output_path"]) for s in segs if s["flow_output_path"] and Path(s["flow_output_path"]).is_file()]
            if not media_paths:
                continue
            video_tasks.append({
                "video_id": vid,
                "start_frame": int(vr["timeline_start_frame"]),
                "end_frame": int(vr["timeline_end_frame"]),
                "extracted": extracted,
                "media_paths": media_paths,
            })

    if not video_tasks:
        return None, None, None

    # Deduplicate overlapping timeline start frames (e.g. if an earlier test video shares start_frame with newer split videos, prefer the newer split videos)
    if len(video_tasks) > 1:
        filtered = []
        for idx, vt in enumerate(video_tasks):
            # If this task has >1 media_paths and spans the same start_frame as another 1-file task, skip the multi-file test duplicate
            if len(vt["media_paths"]) > 1 and any(
                other["video_id"] != vt["video_id"]
                and len(other["media_paths"]) == 1
                and vt["start_frame"] <= other["start_frame"] < vt["end_frame"]
                for other in video_tasks
            ):
                continue
            filtered.append(vt)
        video_tasks = filtered

    custom_langs = custom_task.languages()
    default_lang = str(repo.get_setting("whisper_language", "sw")).split(" · ")[-1].strip() or "sw"
    asr_provider = resolve_autoedit.get_selected_asr_provider()
    ffmpeg_bin = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"

    def _transcribe_video_words(vt: dict) -> list[tuple[float, float, str]]:
        vid = vt["video_id"]
        cache_file = cache_dir / f"video_{vid}_words.json"
        if cache_file.is_file():
            try:
                cached = json.loads(cache_file.read_text(encoding="utf-8"))
                if cached:
                    return [tuple(x) for x in cached]
            except Exception:
                pass

        lang = custom_langs.get(vid) or default_lang
        all_words: list[tuple[float, float, str]] = []
        offset_sec = 0.0
        with tempfile.TemporaryDirectory(prefix="fs-direct-sc-") as td:
            for m_idx, mp in enumerate(vt["media_paths"]):
                wav_p = Path(td) / f"seg_{m_idx}.wav"
                subprocess.run(
                    [ffmpeg_bin, "-v", "quiet", "-y", "-i", mp, "-ac", "1", "-ar", "16000", str(wav_p)],
                    check=True,
                )
                with wave.open(str(wav_p), "rb") as wf:
                    seg_dur = wf.getnframes() / float(wf.getframerate() or 16000)

                seg_words: list[tuple[float, float, str]] = []
                # Prefer local faster-whisper for fast, zero-upload local word timestamps (~1.5s per video)
                fw_words = _transcribe_wav_slice(wav_p, 0.0, seg_dur + 1.0)
                if fw_words:
                    seg_words = [(round(offset_sec + w[0], 3), round(offset_sec + w[1], 3), w[2]) for w in fw_words]
                elif asr_provider in resolve_autoedit.CLOUD_ASR_PROVIDERS:
                    keys = credential_pool.candidate_keys("com.flowstudio.asr", asr_provider)
                    if keys:
                        from scripts.run_batch_whisper import _transcribe_cloud_with_key
                        for k in keys:
                            try:
                                srt_txt = _transcribe_cloud_with_key(asr_provider, "default", lang, wav_p, k, lambda _m: None)
                                parsed = parse_srt(srt_txt)
                                if parsed:
                                    seg_words = [(round(offset_sec + w[0], 3), round(offset_sec + w[1], 3), w[2]) for w in parsed]
                                    break
                            except Exception:
                                continue

                all_words.extend(seg_words)
                offset_sec += seg_dur

        if all_words:
            try:
                cache_file.write_text(json.dumps(all_words, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass
        return all_words

    all_events: list[tuple[float, float, str]] = []
    seen_keys = set()
    total_v = len(video_tasks)
    words_by_vid: dict[int, list[tuple[float, float, str]]] = {}

    from concurrent.futures import ThreadPoolExecutor, as_completed
    max_workers = min(4, max(1, total_v))
    completed_count = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        fut_to_vt = {pool.submit(_transcribe_video_words, vt): vt for vt in video_tasks}
        for fut in as_completed(fut_to_vt):
            vt = fut_to_vt[fut]
            completed_count += 1
            if progress_cb:
                try:
                    progress_cb(completed_count, total_v, vt["video_id"])
                except Exception:
                    pass
            try:
                words_by_vid[vt["video_id"]] = fut.result() or []
            except Exception:
                words_by_vid[vt["video_id"]] = []

    matched_vids: set[int] = set()
    for vt in video_tasks:
        words = words_by_vid.get(vt["video_id"]) or []
        if not words:
            continue
        base_sec = vt["start_frame"] / fps
        for item in vt["extracted"]:
            chunks = item["chunks"]
            cov, score, max_w, chunk_times = char_dp_align_chunks(chunks, words)
            if not chunk_times:
                continue
            for c_lines, (m_start, m_end) in zip(chunks, chunk_times):
                if m_end <= 0.0 and m_start <= 0.0:
                    continue
                abs_start_frame = int(round((base_sec + m_start) * fps))
                abs_end_frame = int(round((base_sec + m_end) * fps))
                rel_start = max(0.0, (abs_start_frame - TIMELINE_START_FRAME) / fps)
                min_dur = 0.8 if len(chunks) == 1 else 0.5
                rel_end = max(rel_start + min_dur, (abs_end_frame - TIMELINE_START_FRAME) / fps)
                c_text = "\n".join(c_lines)
                key = (round(rel_start, 2), c_text)
                if key not in seen_keys:
                    seen_keys.add(key)
                    all_events.append((rel_start, rel_end, c_text))
                    matched_vids.add(int(vt["video_id"]))

    if not all_events:
        return None, None, None

    all_events.sort(key=lambda x: x[0])
    srt_content = events_to_srt(all_events)

    # Create or reuse an attempt folder so Lua IMPORT_SCRIPTURES and FINISH_BATCH (export) can both run directly!
    attempts = sorted(
        [p for p in (batch_dir / "autoedit").glob("*") if p.is_dir() and (p / "autoedit.ini").exists()],
        key=lambda p: (p / "autoedit.ini").stat().st_mtime,
        reverse=True,
    )
    if attempts:
        attempt_dir = attempts[0]
        attempt_id = attempt_dir.name
        autoedit_ini = attempt_dir / "autoedit.ini"
    else:
        attempt_id = uuid.uuid4().hex
        attempt_dir = batch_dir / "autoedit" / attempt_id
        attempt_dir.mkdir(parents=True, exist_ok=True)
        (attempt_dir / "manuscripts").mkdir(parents=True, exist_ok=True)
        task_json = attempt_dir / "task.json"
        autoedit_ini = attempt_dir / "autoedit.ini"
        manifest = daily.read_pairs(batch_dir / "manifest.ini")
        with database.connect() as con:
            vs_map = {
                int(r["video_id"]): dict(r)
                for r in con.execute(
                    "SELECT * FROM davinci_video_state WHERE batch_id=? AND timeline_imported=1",
                    (batch_id,),
                ).fetchall()
            }
        m_vcount = int(manifest.get("video_count") or 0)
        tl_name = str(manifest.get("timeline_name") or f"MAIN-{work_date}")
        ae_payload = {
            "batch_id": batch_id,
            "attempt_id": attempt_id,
            "task_id": attempt_id,
            "work_date": work_date,
            "project_name": f"FlowStudio-{work_date}",
            "timeline_name": tl_name,
            "whisper_language": default_lang,
            "python_path": __import__("sys").executable,
            "task_json_path": str(task_json),
        }
        export_entries = []
        for idx_m in range(1, m_vcount + 1):
            mpre = f"v{idx_m}_"
            mvid = int(manifest.get(mpre + "id") or 0)
            if mvid not in vs_map:
                continue
            vs_item = vs_map[mvid]
            export_entries.append((mvid, mpre, int(vs_item["timeline_start_frame"]), int(vs_item["timeline_end_frame"])))
        ae_payload["video_count"] = len(export_entries)
        ae_payload["expected_complete_video_count"] = len(export_entries)
        if export_entries:
            ae_payload["batch_start"] = min(x[2] for x in export_entries)
            ae_payload["batch_end"] = max(x[3] for x in export_entries)
        for out_idx, (mvid, mpre, s_fr, e_fr) in enumerate(export_entries, 1):
            p_out = f"v{out_idx}_"
            m_txt = attempt_dir / "manuscripts" / f"video_{mvid}.txt"
            m_txt.write_text("", encoding="utf-8")
            ae_payload[p_out + "id"] = mvid
            ae_payload[p_out + "manuscript_path"] = str(m_txt)
            ae_payload[p_out + "start"] = s_fr
            ae_payload[p_out + "end"] = e_fr
            ae_payload[p_out + "final_filename"] = manifest.get(mpre + "final_filename", f"{out_idx:02d}-video_{mvid}.mp4")
            ae_payload[p_out + "output_dir"] = manifest.get(mpre + "output_dir", "")
            ae_payload[p_out + "no_cut"] = "true"
            ew = manifest.get(mpre + "export_width")
            eh = manifest.get(mpre + "export_height")
            ear = manifest.get(mpre + "aspect_ratio")
            if not (ew and eh):
                s1 = manifest.get(mpre + "s1_path", "")
                ew, eh, ear = daily.resolve_video_export_size(seg_paths=[s1] if s1 else None, work_date=work_date)
            ae_payload[p_out + "export_width"] = int(ew)
            ae_payload[p_out + "export_height"] = int(eh)
            ae_payload[p_out + "aspect_ratio"] = ear or ("16:9" if int(ew) > int(eh) else "9:16")
        task_payload = {
            "schema_version": 1,
            "task_id": attempt_id,
            "batch_id": batch_id,
            "work_date": work_date,
            "project_name": f"FlowStudio-{work_date}",
            "timeline_name": tl_name,
            "language": default_lang,
            "videos": [],
        }
        task_json.write_text(json.dumps(task_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        daily.atomic_pairs(autoedit_ini, ae_payload)
        daily.atomic_pairs(attempt_dir / "state.ini", {
            "batch_id": batch_id,
            "attempt_id": attempt_id,
            "task_id": attempt_id,
            "stage": "WAITING_USER_REVIEW",
            "detail": "直通挂载经文字幕完成（不切刀模式），可直接确认清理并导出",
            "current": len(export_entries),
            "total": len(export_entries),
        })
        daily.atomic_pairs(attempt_dir / "cut_plan.ini", {
            "batch_id": batch_id,
            "attempt_id": attempt_id,
            "task_id": attempt_id,
            "candidate_count": 0,
            "carried_candidate_count": 0,
            "reanalyze": "false",
            "deferred_count": 0,
            "deferred_video_ids": "",
            "scope_start": ae_payload.get("batch_start", TIMELINE_START_FRAME),
            "scope_end": ae_payload.get("batch_end", TIMELINE_START_FRAME),
            "scope_rule": "BATCH_MARKER_TO_TIMELINE_END",
        })
        with database.connect() as con:
            resolve_autoedit.ensure_schema()
            con.execute(
                "UPDATE davinci_batches SET status='WAITING_USER_REVIEW', error_message='', updated_at=CURRENT_TIMESTAMP WHERE batch_id=?",
                (batch_id,),
            )
            con.execute(
                "INSERT INTO davinci_autoedit_runs(batch_id,attempt_id,status,payload_path,current,total,error_message) "
                "VALUES(?,?,'WAITING_USER_REVIEW',?,?,?,'') "
                "ON CONFLICT(batch_id) DO UPDATE SET attempt_id=excluded.attempt_id,status='WAITING_USER_REVIEW',payload_path=excluded.payload_path,current=excluded.current,total=excluded.total,error_message=''",
                (batch_id, attempt_id, str(autoedit_ini), len(export_entries), len(export_entries)),
            )
            for mvid, _, _, _ in export_entries:
                con.execute(
                    "UPDATE davinci_video_state SET autoedit_status='WAITING_USER_REVIEW', whisper_status='DONE', candidate_count=0 WHERE batch_id=? AND video_id=?",
                    (batch_id, mvid),
                )
                con.execute("UPDATE videos SET edit_status='待人工检查' WHERE id=?", (mvid,))

    out_srt_attempt = attempt_dir / f"scriptures_{batch_id}.srt"
    out_srt_attempt.write_text(srt_content, encoding="utf-8")
    out_srt_batch = batch_dir / f"经文字幕_{batch_id}.srt"
    out_srt_batch.write_text(srt_content, encoding="utf-8")
    _write_scripture_videos_ini(attempt_dir, batch_id, matched_vids)
    _write_scripture_videos_ini(batch_dir, batch_id, matched_vids)
    timeline_srt = bridge_root / "v0_5_0" / "batches" / f"经文字幕_timeline_{work_date}.srt"
    timeline_srt.write_text(srt_content, encoding="utf-8")

    return out_srt_attempt, autoedit_ini, attempt_id


def generate_batch_scripture_subtitles(batch_dir: Path | str, fps: float = 25.0) -> Path | None:
    """Scan autoedit attempt directory, find all SUV scriptures across timeline batches, align timecodes, and output master SRT."""
    bpath = Path(batch_dir)
    if not bpath.exists():
        return None
        
    if (bpath / "task.json").exists():
        target_attempt_dir = bpath
    else:
        attempts = sorted(
            [p for p in (bpath / "autoedit").glob("*") if p.is_dir() and (p / "task.json").exists()],
            key=lambda p: (p / "task.json").stat().st_mtime,
            reverse=True,
        )
        if not attempts:
            return None
        target_attempt_dir = attempts[0]
        
    with open(target_attempt_dir / "task.json", encoding="utf-8") as f:
        target_task = json.load(f)
        
    batch_id = target_task.get("batch_id") or target_attempt_dir.parent.parent.name
    work_date = target_task.get("work_date")
    target_tl = str(target_task.get("timeline_name") or (f"MAIN-{work_date}" if work_date else ""))
    
    # Find all batch attempts for this (work_date, timeline_name) so that ALL batches on the same timeline align!
    from app.services import resolve_daily as daily
    bridge_root = daily.bridge_root()
    attempts_to_scan = []
    if work_date:
        with database.connect() as con:
            rows = con.execute(
                "SELECT batch_id, status FROM davinci_batches WHERE work_date=? AND timeline_name=? AND status IN ('WAITING_USER_REVIEW','COMPLETED') ORDER BY batch_start_frame ASC",
                (work_date, target_tl),
            ).fetchall()
            for r in rows:
                b_dir = bridge_root / "v0_5_0" / "batches" / r["batch_id"]
                sub_attempts = sorted(
                    [p for p in (b_dir / "autoedit").glob("*") if p.is_dir() and (p / "task.json").exists()],
                    key=lambda p: (p / "task.json").stat().st_mtime,
                    reverse=True,
                )
                if sub_attempts:
                    attempts_to_scan.append(sub_attempts[0])
                    
    if not attempts_to_scan:
        attempts_to_scan = [target_attempt_dir]
        
    all_events = []
    seen_texts = set()
    target_matched_vids: set[int] = set()
    batch_root = target_attempt_dir.parent.parent
    for att in attempts_to_scan:
        att_vids: set[int] = set()
        att_events = _extract_events_for_attempt(att, fps=fps, matched_video_ids=att_vids)
        att_bid = att.parent.parent.name
        _write_scripture_videos_ini(att, att_bid, att_vids)
        _write_scripture_videos_ini(att.parent.parent, att_bid, att_vids)
        if att.resolve() == target_attempt_dir.resolve():
            target_matched_vids.update(att_vids)
        for ev in att_events:
            # deduplicate if same time and text
            key = (round(ev[0], 2), ev[2])
            if key not in seen_texts:
                seen_texts.add(key)
                all_events.append(ev)
                
    if not all_events:
        _write_scripture_videos_ini(target_attempt_dir, batch_id, set())
        if batch_root != target_attempt_dir and batch_root.is_dir():
            _write_scripture_videos_ini(batch_root, batch_id, set())
        return None
        
    all_events.sort(key=lambda x: x[0])
    srt_content = events_to_srt(all_events)
    
    # Save into target attempt directory
    out_srt_attempt = target_attempt_dir / f"scriptures_{batch_id}.srt"
    out_srt_attempt.write_text(srt_content, encoding="utf-8")
    
    # Save into batch directory
    out_srt_batch = batch_root / f"经文字幕_{batch_id}.srt"
    out_srt_batch.write_text(srt_content, encoding="utf-8")
    _write_scripture_videos_ini(target_attempt_dir, batch_id, target_matched_vids)
    if batch_root != target_attempt_dir and batch_root.is_dir():
        _write_scripture_videos_ini(batch_root, batch_id, target_matched_vids)
    
    # Save master timeline SRT
    if work_date:
        timeline_srt = bridge_root / "v0_5_0" / "batches" / f"经文字幕_timeline_{work_date}.srt"
        timeline_srt.write_text(srt_content, encoding="utf-8")
        
    return out_srt_attempt


# Default DaVinci Resolve Subtitle Track style blob (Open Sans Semibold, White, Size 34, Red Background #B435CE RGB(225,44,0), Radius 0.010, Opacity 100, Width 1.588, Height 0.168)
DEFAULT_SUBTITLE_TRACK_STYLE_BLOB = bytes.fromhex(
    "000000010000000300000012004e0075006d004c00610079006500720073000000020000000000000000"
    "3e004500780063006c0075006400650054007200610063006b00460072006f006d005300650071007500"
    "65006e0063006500430061006300680069006e00670000000100010000001e0045006600660065006300"
    "7400460069006c0074006500720073004200410000000c00000000a800000002000000a08128b52ffd20"
    "afb5040054080a2708880118004a004a004a0808131a040a0208440a830108364a13081b1a0f0a0d320b"
    "01ffffb4ce35b2000000004a004a04081d48004a1e08211a0b0a09117b14ae47e17a843f2248004a0b08"
    "221a050a0308c80148004a09089c011a040a0228014a11081f9cc420b07268f93f48004a1108201b2fdd"
    "240681c53f48004a04081e480005003645b9d5e5082607b90ea39d4c"
)


def _parse_srt_blocks_to_frames(srt_path: Path, fps: float = 25.0, tl_start_frame: int = TIMELINE_START_FRAME) -> list[tuple[int, int, str]]:
    """Parse an `.srt` file into `(abs_start_frame, dur_frames, resolve_name_with_br)` entries."""
    if not srt_path or not srt_path.is_file():
        return []
    raw = srt_path.read_text(encoding="utf-8", errors="ignore").strip()
    if not raw:
        return []
    blocks = [b.strip() for b in re.split(r"\r?\n\r?\n+", raw) if b.strip()]
    tc_re = re.compile(
        r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
    )
    items: list[tuple[int, int, str]] = []
    for blk in blocks:
        lines = [ln.strip() for ln in blk.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        tc_idx = 0 if "-->" in lines[0] else 1
        if tc_idx >= len(lines):
            continue
        m = tc_re.search(lines[tc_idx])
        if not m:
            continue
        h1, m1, s1, ms1, h2, m2, s2, ms2 = (int(x) for x in m.groups())
        t1 = h1 * 3600.0 + m1 * 60.0 + s1 + ms1 / 1000.0
        t2 = h2 * 3600.0 + m2 * 60.0 + s2 + ms2 / 1000.0
        txt_lines = lines[tc_idx + 1 :]
        if not txt_lines:
            continue
        sf = int(round(tl_start_frame + t1 * fps))
        ef = max(sf + 1, int(round(tl_start_frame + t2 * fps)))
        dur = ef - sf
        name_br = "<br>".join(txt_lines)
        items.append((sf, dur, name_br))
    return items


def sync_resolve_project_subtitle_track_items(
    project_name: str,
    timeline_name: str = "",
    srt_path: str | Path | None = None,
    fps: float = 25.0,
    tl_start_frame: int = TIMELINE_START_FRAME,
) -> bool:
    """Ensure the DaVinci Resolve timeline's Subtitle Track (Type=2) contains ONLY the exact
    1:1 subtitle items from `srt_path` at their exact `[Start, Duration)` timeline frames,
    removing any duplicate/shifted items caused by Resolve's `AppendToTimeline` playhead offset.
    """
    import sqlite3
    if not project_name or not srt_path:
        return False
    spath = Path(srt_path).expanduser()
    target_items = _parse_srt_blocks_to_frames(spath, fps=fps, tl_start_frame=tl_start_frame)
    if not target_items:
        return False

    projects_root = (
        Path.home()
        / "Library/Application Support/Blackmagic Design/DaVinci Resolve/Resolve Project Library/Resolve Projects/Users/guest/Projects"
    )
    pdb = projects_root / str(project_name) / "Project.db"
    if not pdb.is_file():
        return False

    try:
        updated = False
        with sqlite3.connect(str(pdb), timeout=10.0) as con:
            seq_id = None
            if timeline_name:
                r = con.execute(
                    "SELECT Sequence FROM Sm2Timeline WHERE Name=? LIMIT 1",
                    (str(timeline_name),),
                ).fetchone()
                if r and r[0]:
                    seq_id = str(r[0])
            if seq_id:
                track_rows = con.execute(
                    "SELECT Sm2TiTrack_id FROM Sm2TiTrack WHERE Sequence=? AND Type=2 ORDER BY Sequence ASC",
                    (seq_id,),
                ).fetchall()
            else:
                track_rows = con.execute(
                    "SELECT Sm2TiTrack_id FROM Sm2TiTrack WHERE Type=2",
                ).fetchall()
            if not track_rows:
                return False

            primary_track_id = str(track_rows[0][0])
            all_track_ids = [str(tr[0]) for tr in track_rows]
            q_marks = ",".join("?" for _ in all_track_ids)

            existing = con.execute(
                f"SELECT Sm2TiItem_id, Sm2TiTrack_id, CAST(Start AS INTEGER) as s, CAST(Duration AS INTEGER) as d, Name "
                f"FROM Sm2TiItem WHERE Sm2TiTrack_id IN ({q_marks}) ORDER BY s ASC, rowid ASC",
                all_track_ids,
            ).fetchall()

            if not existing:
                return False

            # If there are >= len(target_items) existing items, keep the last N (or first N) and delete extras
            n_target = len(target_items)
            if len(existing) >= n_target:
                keep_rows = existing[-n_target:]
                drop_rows = existing[:-n_target]
                if drop_rows:
                    drop_ids = [str(r[0]) for r in drop_rows]
                    dq = ",".join("?" for _ in drop_ids)
                    con.execute(f"DELETE FROM Sm2TiItem_Sm2TiTrack WHERE DbAssociate IN ({dq})", drop_ids)
                    con.execute(f"DELETE FROM Sm2TiItem WHERE Sm2TiItem_id IN ({dq})", drop_ids)
                    updated = True

                for idx, (row, (sf, dur, name_br)) in enumerate(zip(keep_rows, target_items)):
                    item_id, trk_id, cur_s, cur_d, cur_name = str(row[0]), str(row[1]), int(row[2]), int(row[3]), str(row[4] or "")
                    if cur_s != sf or cur_d != dur or cur_name != name_br or trk_id != primary_track_id:
                        con.execute(
                            "UPDATE Sm2TiItem SET Sm2TiTrack_id=?, Start=?, Duration=?, Name=? WHERE Sm2TiItem_id=?",
                            (primary_track_id, str(sf), str(dur), name_br, item_id),
                        )
                        updated = True
                    con.execute(
                        "UPDATE Sm2TiItem_Sm2TiTrack SET DbOwner=?, DbIndex=? WHERE DbAssociate=?",
                        (primary_track_id, idx, item_id),
                    )
            if updated:
                con.commit()
        return updated
    except Exception:
        return False


def ensure_resolve_project_subtitle_track_style(
    project_name: str,
    timeline_name: str = "",
    srt_path: str | Path | None = None,
) -> bool:
    """Ensure the DaVinci Resolve project's Subtitle Track (Type=2) has the user's default track style
    (Font Size 34, White text, Red rounded background box 1.588 x 0.168, Radius 0.010, Opacity 100),
    and when `srt_path` is provided, also sync exact 1:1 subtitle item positions onto `Sm2TiItem`.
    Returns True if updated so the caller knows to reload the project in Resolve.
    """
    import sqlite3
    items_synced = False
    if srt_path:
        items_synced = sync_resolve_project_subtitle_track_items(
            project_name=project_name,
            timeline_name=timeline_name,
            srt_path=srt_path,
        )
    projects_root = (
        Path.home()
        / "Library/Application Support/Blackmagic Design/DaVinci Resolve/Resolve Project Library/Resolve Projects/Users/guest/Projects"
    )
    pdb = projects_root / str(project_name) / "Project.db"
    if not pdb.is_file():
        return items_synced
    try:
        style_blob = DEFAULT_SUBTITLE_TRACK_STYLE_BLOB
        # Prefer copying the latest styled subtitle track from recent FlowStudio projects if the user tweaked it
        for p_dir in sorted(projects_root.glob("FlowStudio-*"), key=lambda p: p.stat().st_mtime, reverse=True):
            cand_db = p_dir / "Project.db"
            if not cand_db.is_file():
                continue
            try:
                with sqlite3.connect(str(cand_db)) as c_con:
                    row = c_con.execute(
                        "SELECT FieldsBlob FROM Sm2TiTrack WHERE Type=2 AND length(FieldsBlob) > 200 LIMIT 1"
                    ).fetchone()
                    if row and row[0] and b"\x28\xb5\x2f\xfd" in row[0]:
                        style_blob = row[0]
                        break
            except Exception:
                continue

        updated = False
        with sqlite3.connect(str(pdb)) as con:
            rows = con.execute("SELECT Sm2TiTrack_id, FieldsBlob FROM Sm2TiTrack WHERE Type=2").fetchall()
            for tid, fb in rows:
                if not fb or len(fb) < 200 or b"\x28\xb5\x2f\xfd" not in fb:
                    con.execute("UPDATE Sm2TiTrack SET FieldsBlob=? WHERE Sm2TiTrack_id=?", (style_blob, tid))
                    updated = True
            if updated:
                con.commit()
        return updated or items_synced
    except Exception:
        return items_synced


# Backward-compatible alias used by combined Lua/CLI callers
style_project_subtitles = ensure_resolve_project_subtitle_track_style


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == "--style-project":
        tl_arg = sys.argv[3] if len(sys.argv) > 3 else ""
        srt_arg = sys.argv[4] if len(sys.argv) > 4 else None
        changed = ensure_resolve_project_subtitle_track_style(sys.argv[2], timeline_name=tl_arg, srt_path=srt_arg)
        print("STYLE_UPDATED" if changed else "STYLE_OK")
        sys.exit(0)
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    res = generate_batch_scripture_subtitles(target)
    if res:
        print(f"SUCCESS: {res}")
    else:
        print("NO_SCRIPTURES_OR_ERROR")
