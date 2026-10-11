from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Broad emoji / pictograph ranges. Deliberately avoids ordinary accented Latin letters.
_EMOJI_RANGES = (
    (0x1F1E6, 0x1F1FF),  # flags
    (0x1F300, 0x1FAFF),  # pictographs, transport, symbols, supplemental emoji
    (0x2600, 0x26FF),    # misc symbols
    (0x2700, 0x27BF),    # dingbats
    (0x2300, 0x23FF),    # technical symbols often used as icons
    (0x2B00, 0x2BFF),    # arrows/stars
)

_SENT_END = re.compile(r"(?<=[.!?。！？])\s+")
_CLAUSE_SPLIT = re.compile(r"(?<=[,;:，；：])\s+|\s+(?=(?:and|but|because|so|while|when|if|then|or|e|ma|perché|quindi|mentre|quando|se|oppure|y|pero|porque|entonces|mientras|cuando|si|o|et|mais|parce que|donc|pendant que|quand|si|ou|e|mas|porque|então|enquanto|quando|se|ou)\b)", re.I)


@dataclass(frozen=True)
class SegmentPolicy:
    min_words: int = 5
    target_words: int = 13
    max_words: int = 20
    hard_max_words: int = 26


def strip_decorative_symbols(text: str) -> str:
    """Remove emoji/decorative pictographs while preserving real language characters.

    This intentionally does *not* use an ASCII whitelist, so Italian/Spanish/French accents,
    apostrophes, punctuation and non-Latin scripts survive.
    """
    if not text:
        return ""
    out = []
    for ch in str(text):
        cp = ord(ch)
        if cp in (0xFE0E, 0xFE0F, 0x200D):  # variation selectors / emoji joiner
            continue
        if any(lo <= cp <= hi for lo, hi in _EMOJI_RANGES):
            continue
        # Remove standalone symbol characters that behave like pictograms, but keep currency/math.
        cat = unicodedata.category(ch)
        if cat == "So":
            continue
        out.append(ch)
    cleaned = "".join(out)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r" *\n *", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _words(text: str) -> list[str]:
    return re.findall(r"[^\W_]+(?:['’][^\W_]+)?", text or "", flags=re.UNICODE)


def _ensure_terminal(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    if text[-1] not in ".!?。！？;:；：":
        text += "."
    return text


def _split_long_clause(text: str, policy: SegmentPolicy) -> list[str]:
    text = text.strip()
    if len(_words(text)) <= policy.max_words:
        return [text]

    # 1) Natural clause boundaries first.
    clauses = [x.strip() for x in _CLAUSE_SPLIT.split(text) if x.strip()]
    if len(clauses) > 1:
        out: list[str] = []
        buf = ""
        for clause in clauses:
            candidate = f"{buf} {clause}".strip() if buf else clause
            if buf and len(_words(candidate)) > policy.target_words:
                out.append(_ensure_terminal(buf))
                buf = clause
            else:
                buf = candidate
        if buf:
            out.append(_ensure_terminal(buf))
        # If all generated pieces are now reasonable, use them.
        if all(len(_words(x)) <= policy.hard_max_words for x in out):
            return out

    # 2) A single very long spoken sentence: split near a natural word boundary around target.
    toks = text.split()
    if len(toks) <= policy.hard_max_words:
        pivot = min(max(policy.target_words, 1), len(toks) - 1)
        return [_ensure_terminal(" ".join(toks[:pivot])), _ensure_terminal(" ".join(toks[pivot:]))]

    # 3) Hard fallback: balanced chunks; never cut a word in half.
    chunks = []
    start = 0
    while start < len(toks):
        remain = len(toks) - start
        if remain <= policy.hard_max_words:
            chunks.append(_ensure_terminal(" ".join(toks[start:])))
            break
        take = min(policy.target_words, remain)
        chunks.append(_ensure_terminal(" ".join(toks[start:start + take])))
        start += take
    return chunks


def _legacy_segment(text: str, policy: SegmentPolicy | None = None) -> list[str]:
    """Language-aware production segmentation for Flow speech clips.

    Rules requested by the user:
    - keep original source elsewhere; this returns only production text;
    - remove emoji/icons;
    - split primarily by spoken sentence structure;
    - overlong sentences split at natural speech/clause boundaries;
    - very short segments merge upward into the previous segment whenever safe.
    """
    policy = policy or SegmentPolicy()
    cleaned = strip_decorative_symbols(text)
    if not cleaned:
        return []

    # Normalize line breaks to soft spaces; punctuation remains the semantic boundary.
    cleaned = re.sub(r"\s*\n+\s*", " ", cleaned).strip()
    initial = [x.strip() for x in _SENT_END.split(cleaned) if x.strip()]
    if not initial:
        initial = [cleaned]

    pieces: list[str] = []
    for sentence in initial:
        pieces.extend(_split_long_clause(sentence, policy))

    # Merge short text into previous segment, exactly as requested.
    merged: list[str] = []
    i = 0
    while i < len(pieces):
        cur = pieces[i].strip()
        wc = len(_words(cur))
        if wc < policy.min_words and merged:
            candidate = f"{merged[-1].rstrip()} {cur}".strip()
            if len(_words(candidate)) <= policy.hard_max_words:
                merged[-1] = candidate
                i += 1
                continue
        # If this is the first tiny fragment and there is a next one, merge forward only because
        # there is no previous segment available.
        if wc < policy.min_words and not merged and i + 1 < len(pieces):
            nxt = pieces[i + 1].strip()
            candidate = f"{cur} {nxt}".strip()
            if len(_words(candidate)) <= policy.hard_max_words:
                merged.append(candidate)
                i += 2
                continue
        merged.append(cur)
        i += 1

    # Rebalance any accidental too-long merge.
    final: list[str] = []
    for seg in merged:
        if len(_words(seg)) > policy.hard_max_words:
            final.extend(_split_long_clause(seg, policy))
        else:
            final.append(seg)
    return [_ensure_terminal(x) for x in final if x.strip()]


def estimate_speech_seconds(text: str, words_per_second: float = 2.0) -> float:
    """Approximate natural spoken duration, including punctuation pauses (not measured audio).

    Production uses a conservative 2.0 words/second (~120 wpm) baseline so Flow clips keep
    visible breathing room for lip sync, emotion and natural pauses instead of racing to the end.
    """
    text = str(text or "")
    cjk = re.findall(r"[\u3400-\u9fff\u3040-\u30ff]", text)
    latin = re.sub(r"[\u3400-\u9fff\u3040-\u30ff]", " ", text)
    pauses = len(re.findall(r"[,;:，；：]", text)) * .12 + len(re.findall(r"[.!?。！？]", text)) * .2
    return round(len(_words(latin)) / max(words_per_second, .5) + len(cjk) / 4.2 + pauses, 2)


def _legacy_segment_seconds(text: str) -> float:
    """Speech estimate used by the base smart-segmentation behavior.

    Keep this aligned with the production natural-speech baseline; otherwise the early splitter can
    create clips that the later Flow timing gate considers too dense.
    """
    return estimate_speech_seconds(text, words_per_second=2.0)


def _legacy_segment_needs_split(text: str) -> bool:
    seconds = _legacy_segment_seconds(text)
    # Same final 8-second speech envelope as flow_timing(): leave ~1.7s headroom.
    return bool(seconds and seconds > 6.3)


def flow_timing(text: str) -> dict:
    """Choose a Flow duration with a natural-speech safety margin.

    The clip duration is intentionally *not* filled to the edge.  Rough targets are:
    4s -> <=3.2s spoken, 6s -> <=5.0s, 8s -> <=6.3s.
    At the default natural-speech estimate this is roughly 5-6 / 7-9 / 10-12 Latin words,
    depending on punctuation. Anything denser than the safe 8-second envelope must be
    rebalanced or handled manually instead of being spoken faster.
    """
    seconds = estimate_speech_seconds(text)
    if seconds <= 3.2:
        duration = 4
    elif seconds <= 5.0:
        duration = 6
    else:
        duration = 8
    needs_split = seconds > 6.3
    return {
        "duration": duration,
        "estimated_speech_seconds": seconds,
        "estimated_speech_duration": seconds,
        "safety_margin_seconds": round(max(0.0, duration - seconds), 2),
        "needs_split": needs_split,
        "timing_status": "REBALANCE_REQUIRED" if needs_split else "OK",
    }


def smart_segment(text: str, policy: SegmentPolicy | None = None) -> list[str]:
    """Keep sentence boundaries when possible; balance long speech and short tails."""
    text = re.sub(r"\s+", " ", strip_decorative_symbols(text)).strip()
    if not text:
        return []
    sentences = [s.strip() for s in re.split(r"(?<=[.!?。！？])(?:\s+|(?=[\u3400-\u9fff]))", text) if s.strip()]
    def split(piece):
        piece = _ensure_terminal(piece)
        if not _legacy_segment_needs_split(piece):
            return [piece]
        # Use natural word boundaries; CJK has no spaces, so allow character boundaries there.
        positions = [m.end() for m in re.finditer(r"\s+|(?<=[\u3400-\u9fff\u3040-\u30ff])", piece) if m.end() < len(piece)-1]
        if not positions:
            return [piece]
        midpoint = _legacy_segment_seconds(piece) / 2
        cut = min(positions, key=lambda n: abs(_legacy_segment_seconds(piece[:n])-midpoint))
        return split(piece[:cut].strip()) + split(piece[cut:].strip())
    pieces = [part for sentence in sentences for part in split(sentence)]
    out = []
    for piece in pieces:
        if out and (_legacy_segment_seconds(out[-1]) < 3.2 or _legacy_segment_seconds(piece) < 3.2):
            merged = out[-1] + " " + piece
            if not _legacy_segment_needs_split(merged):
                out[-1] = merged
                continue
        out.append(piece)
    # A one-word tail must stay attached to the preceding text, even if it
    # requires balancing that combined text into two longer clips again.
    fixed=[]
    for piece in out:
        single=len(_words(piece))==1 and not re.search(r"[\u3400-\u9fff\u3040-\u30ff]",piece)
        if single and fixed:
            combined=fixed.pop()+" "+piece
            fixed.extend(split(combined))
        elif fixed and len(_words(fixed[-1]))==1 and not re.search(r"[\u3400-\u9fff\u3040-\u30ff]",fixed[-1]):
            combined=fixed.pop()+" "+piece;fixed.extend(split(combined))
        else:fixed.append(piece)
    return fixed
