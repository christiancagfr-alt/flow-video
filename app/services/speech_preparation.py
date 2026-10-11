from __future__ import annotations

"""Incremental spoken-text preparation for Flow Studio.

This module deliberately sits *beside* the existing segmentation/production pipeline.
It never submits Flow work and never touches downstream state.  Its responsibilities are:

1) ignore pasted line breaks and reflow from the actual Swahili text;
2) localize safe spoken Arabic numerals to natural Swahili words;
3) target about 7.5 seconds of natural Swahili speech, with 14-22 words as guidance only;
4) split overlong text only at punctuation already present in the source;
5) never hard-split punctuation-free text merely to hit a length target;
6) merge short/adjacent clips whenever the merged speech still fits the 7.5-second envelope;
7) preserve ordinary spoken punctuation rather than rewriting every line ending to a period.
"""

from dataclasses import dataclass
import re
from typing import Iterable

from app.services.text_processing import (
    _words,
    estimate_speech_seconds,
    flow_timing,
    smart_segment,
    strip_decorative_symbols,
)


ONES = {
    0: "sifuri", 1: "moja", 2: "mbili", 3: "tatu", 4: "nne",
    5: "tano", 6: "sita", 7: "saba", 8: "nane", 9: "tisa",
}
TENS = {
    10: "kumi", 20: "ishirini", 30: "thelathini", 40: "arobaini",
    50: "hamsini", 60: "sitini", 70: "sabini", 80: "themanini", 90: "tisini",
}

# Things that are identifiers or have a context-sensitive pronunciation are protected by default.
_PROTECTED_PATTERNS = [
    re.compile(r"(?:https?://|www\.)\S+", re.I),
    re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b"),
    re.compile(r"(?<!\w)@[A-Za-z0-9_.-]+"),
    re.compile(r"\b[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[1-5][0-9A-Fa-f]{3}-[89ABab][0-9A-Fa-f]{3}-[0-9A-Fa-f]{12}\b"),
    re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    re.compile(r"(?:^|\s)(?:/[^\s]+)+"),
    re.compile(r"\b[A-Za-z]:\\[^\s]+"),
    re.compile(r"\b\d{1,4}[-/]\d{1,2}(?:[-/]\d{1,4})?\b"),
    re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b"),
    # Alphanumeric identifiers: CH01, GPT5, X200, Task123, filenames without path, etc.
    re.compile(r"\b(?=[A-Za-z0-9_.-]*[A-Za-z])(?=[A-Za-z0-9_.-]*\d)[A-Za-z0-9_.-]+\b"),
    # Phone-like grouped digit sequences.
    re.compile(r"(?<!\w)\+?\d[\d\s().-]{6,}\d(?!\w)"),
]

_IDENTIFIER_HINT = re.compile(
    r"(?:\b(?:pin|otp|code|id|task|user|order|file|filename|path|url|email|ip|version|ver|model|"
    r"token|key|api|uuid|session|hash|serial|sku|sn|parameter|param|username|account|channel|ch)\b|编号|任务|文件|版本|型号|验证码|令牌|密钥|哈希)",
    re.I,
)
_YEAR_HINT = re.compile(r"(?:\bmwaka\b|\byear\b)", re.I)
_CONTEXT_PREFIX = r"(?:asilimia|sekunde|dakika|saa|miaka|umri(?:\s+wa)?|shilingi|tsh|ksh|usd|eur|dola|euro|kilomita|mita|sentimita|milimita|kilo|gramu|lita|nyuzi)"
_CONTEXT_SUFFIX = r"(?:kg|g|mg|km|cm|mm|ml|l|°c|°f|celsius|fahrenheit|tsh|ksh|usd|eur|dola|euro|sekunde|dakika|saa|miaka)"
_NUMBER_WORDS = {
    "sifuri", "moja", "mbili", "tatu", "nne", "tano", "sita", "saba", "nane", "tisa",
    "kumi", "ishirini", "thelathini", "arobaini", "hamsini", "sitini", "sabini", "themanini", "tisini",
    "mia", "elfu", "laki", "milioni", "bilioni",
}


@dataclass(frozen=True)
class ReflowPolicy:
    sentence_marks: str = ".!?。！？"
    clause_marks: str = ",;:，；："
    preserve_newlines: bool = False
    min_tail_words: int = 3
    swahili_boundaries: bool = True


@dataclass(frozen=True)
class NumberDecision:
    source: str
    replacement: str
    category: str
    start: int
    end: int


@dataclass(frozen=True)
class SpeechPreparation:
    original_text: str
    spoken_text: str
    segments: tuple[str, ...]
    timings: tuple[dict, ...]
    timing_status: str
    integrity_ok: bool
    number_decisions: tuple[NumberDecision, ...]

    @property
    def unsplittable(self) -> bool:
        return self.timing_status == "UNSPLITTABLE"


def number_to_swahili(value: int) -> str:
    """Natural cardinal Swahili for non-negative integers used in ordinary speech."""
    n = int(value)
    if n < 0:
        return "hasi " + number_to_swahili(abs(n))
    if n < 10:
        return ONES[n]
    if n < 100:
        ten = (n // 10) * 10
        rem = n % 10
        return TENS[ten] if not rem else f"{TENS[ten]} na {ONES[rem]}"
    if n < 1000:
        head = f"mia {ONES[n // 100]}"
        rem = n % 100
        return head if not rem else f"{head} {number_to_swahili(rem)}"
    if n < 100_000:
        head = f"elfu {number_to_swahili(n // 1000)}"
        rem = n % 1000
        return head if not rem else f"{head} {number_to_swahili(rem)}"
    if n < 1_000_000:
        head = f"laki {number_to_swahili(n // 100_000)}"
        rem = n % 100_000
        return head if not rem else f"{head} {number_to_swahili(rem)}"
    if n < 1_000_000_000:
        head = f"milioni {number_to_swahili(n // 1_000_000)}"
        rem = n % 1_000_000
        return head if not rem else f"{head} {number_to_swahili(rem)}"
    if n < 1_000_000_000_000:
        head = f"bilioni {number_to_swahili(n // 1_000_000_000)}"
        rem = n % 1_000_000_000
        return head if not rem else f"{head} {number_to_swahili(rem)}"
    # Very large bare numerals are more likely to be identifiers and should normally be protected.
    return str(n)


def _decimal_to_swahili(token: str) -> str:
    token = token.replace(",", ".")
    whole, frac = token.split(".", 1)
    return f"{number_to_swahili(int(whole))} nukta " + " ".join(ONES[int(ch)] for ch in frac)


def _protected_ranges(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for pattern in _PROTECTED_PATTERNS:
        spans.extend((m.start(), m.end()) for m in pattern.finditer(text))
    return spans


def _overlaps(spans: Iterable[tuple[int, int]], start: int, end: int) -> bool:
    return any(start < b and end > a for a, b in spans)


def _identifier_context(text: str, start: int, end: int) -> bool:
    before = text[max(0, start - 24):start]
    after = text[end:min(len(text), end + 12)]
    return bool(_IDENTIFIER_HINT.search(before) or _IDENTIFIER_HINT.search(after))


def _normalize_spoken(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def localize_swahili_numbers(text: str) -> tuple[str, tuple[NumberDecision, ...]]:
    """Convert only numerals that are safe to interpret as spoken quantities.

    Ambiguous identifier-like content stays unchanged.  This intentionally prefers a false negative
    over a wrong spoken rendering.
    """
    source = str(text or "")
    protected = _protected_ranges(source)
    replacements: list[tuple[int, int, str, str]] = []

    # Percentages are semantically explicit enough to localize, including a decimal percentage.
    for m in re.finditer(r"(?<![\w.])(\d{1,6}(?:[.,]\d+)?)\s*%(?!\w)", source):
        if _overlaps(protected, m.start(), m.end()) or _identifier_context(source, m.start(), m.end()):
            continue
        num = m.group(1)
        spoken = _decimal_to_swahili(num) if "." in num or "," in num else number_to_swahili(int(num))
        before = source[max(0, m.start() - 16):m.start()]
        replacement = spoken if re.search(r"\basilimia\s*$", before, re.I) else f"asilimia {spoken}"
        replacements.append((m.start(), m.end(), replacement, "CONTEXT_CONVERT"))

    # Decimal/context-sensitive values are converted only when an explicit spoken unit/context
    # makes the reading unambiguous. Bare decimals stay untouched (KEEP_ORIGINAL).
    context_patterns = [
        re.compile(rf"(?i)(?P<prefix>\b{_CONTEXT_PREFIX}\s+)(?P<num>\d{{1,6}}(?:[.,]\d+)?)\b"),
        re.compile(rf"(?i)(?<![\w.])(?P<num>\d{{1,6}}(?:[.,]\d+)?)(?P<suffix>\s*{_CONTEXT_SUFFIX}\b)"),
        re.compile(r"(?P<prefix>[$€£]\s*)(?P<num>\d{1,6}(?:[.,]\d+)?)"),
    ]
    occupied = [(a, b) for a, b, _, _ in replacements]
    for pattern in context_patterns:
        for m in pattern.finditer(source):
            ns, ne = m.span('num')
            if _overlaps(protected, ns, ne) or _overlaps(occupied, ns, ne) or _identifier_context(source, ns, ne):
                continue
            num = m.group('num')
            spoken = _decimal_to_swahili(num) if "." in num or "," in num else number_to_swahili(int(num))
            replacements.append((ns, ne, spoken, "CONTEXT_CONVERT"))
            occupied.append((ns, ne))

    occupied = [(a, b) for a, b, _, _ in replacements]
    for m in re.finditer(r"(?<![\w.])(?<!\d,)\d+(?!\w)(?![.,]\d)", source):
        start, end = m.span()
        token = m.group(0)
        if _overlaps(protected, start, end) or _overlaps(occupied, start, end):
            continue
        if _identifier_context(source, start, end):
            continue
        # Long digit strings and leading-zero tokens default to identifier/telephone safety.
        if len(token) >= 7 or (len(token) > 1 and token.startswith('0')):
            continue
        n = int(token)
        # V0.13.5.91: years are spoken numbers too.  An explicit "mwaka" cue is metadata only;
        # it is no longer required before converting a modern year.
        if 1900 <= n <= 2099:
            before = source[max(0, start - 18):start]
            category = "CONTEXT_CONVERT" if _YEAR_HINT.search(before) else "AUTO_CONVERT"
        else:
            category = "AUTO_CONVERT"
        replacements.append((start, end, number_to_swahili(n), category))

    if not replacements:
        return _normalize_spoken(source), ()

    replacements.sort(key=lambda x: (x[0], x[1]))
    filtered: list[tuple[int, int, str, str]] = []
    last_end = -1
    for item in replacements:
        if item[0] < last_end:
            continue
        filtered.append(item)
        last_end = item[1]

    out: list[str] = []
    decisions: list[NumberDecision] = []
    cursor = 0
    for start, end, replacement, category in filtered:
        out.append(source[cursor:start])
        out.append(replacement)
        decisions.append(NumberDecision(source[start:end], replacement, category, start, end))
        cursor = end
    out.append(source[cursor:])
    return _normalize_spoken("".join(out)), tuple(decisions)


def _canonical(text: str) -> str:
    # Segmentation may replace line breaks/spaces, but no non-whitespace dialogue character may change.
    return re.sub(r"\s+", "", str(text or ""))


def _restore_baseline_segments(source: str) -> list[str]:
    """Use existing smart_segment boundaries by word-count, but recover text from source verbatim.

    smart_segment historically adds terminal punctuation in a few fallback cases.  Recovering ranges
    from source preserves the established boundary choices without inventing spoken text.
    """
    source = _normalize_spoken(source)
    if not source:
        return []
    baseline = smart_segment(source) or [source]
    if len(baseline) <= 1:
        return [source]

    word_pattern = re.compile(r"[^\W_]+(?:['’][^\W_]+)?", re.UNICODE)
    spans = list(word_pattern.finditer(source))
    counts = [len(_words(part)) for part in baseline]
    if not spans or sum(counts) != len(spans) or any(c <= 0 for c in counts):
        # Conservative fallback: keep one exact segment; later timing analysis may mark it UNSPLITTABLE.
        return [source]

    chunks: list[str] = []
    start = 0
    consumed = 0
    for count in counts[:-1]:
        consumed += count
        boundary = spans[consumed - 1].end()
        next_start = spans[consumed].start()
        between = source[boundary:next_start]
        # Attach punctuation to the preceding chunk, but leave whitespace as the separator.
        nonspace = len(between.rstrip())
        cut = boundary + nonspace
        chunk = source[start:cut].strip()
        if chunk:
            chunks.append(chunk)
        start = cut
        while start < len(source) and source[start].isspace():
            start += 1
    tail = source[start:].strip()
    if tail:
        chunks.append(tail)
    if _canonical(" ".join(chunks)) != _canonical(source):
        return [source]
    return chunks


def _split_preserving(text: str, pattern: re.Pattern[str]) -> list[str]:
    """Split after matched boundary text while preserving every non-whitespace character."""
    out: list[str] = []
    start = 0
    for m in pattern.finditer(text):
        cut = m.end()
        piece = text[start:cut].strip()
        if piece:
            out.append(piece)
        start = cut
        while start < len(text) and text[start].isspace():
            start += 1
    tail = text[start:].strip()
    if tail:
        out.append(tail)
    return out or [text.strip()]


def _split_at_conjunctions(text: str, include_na: bool = False) -> list[str]:
    words = r"lakini|kwa\s+sababu|hivyo|ikiwa|wakati|ili|kwamba|ambaye|ambalo|ambao|au|kisha|ndipo"
    if include_na:
        words += r"|na"
    matches = list(re.finditer(rf"\s+(?=(?P<conj>{words})\b)", text, re.I))
    if not matches:
        return [text.strip()]
    out: list[str] = []
    start = 0
    for m in matches:
        conj=(m.group('conj') or '').lower()
        if conj == 'na':
            # Never split the fixed numeric phrase created by localization, e.g.
            # ``ishirini na tano`` / ``kumi na mbili``.
            left=re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]+", text[:m.start()].lower())
            right_start=m.end()+len(conj)
            right=re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]+", text[right_start:].lower())
            if left and right and left[-1] in _NUMBER_WORDS and right[0] in _NUMBER_WORDS:
                continue
        piece = text[start:m.start()].strip()
        if piece:
            out.append(piece)
        start = m.end()
    tail = text[start:].strip()
    if tail:
        out.append(tail)
    return out or [text.strip()]


def _safe_semantic_units(text: str) -> list[str] | None:
    """Return semantic units no longer than the safe 8-second speech envelope.

    It progressively uses weaker but still natural boundaries.  It never falls back to an arbitrary
    word-count cut.  If one semantic unit remains too long, return None (UNSPLITTABLE).
    """
    units = [text.strip()]
    boundary_patterns = [
        re.compile(r"[.!?。！？]+[\"'”’)]*"),
        re.compile(r"[;；:：]+"),
        re.compile(r"[,，]+"),
    ]
    for pattern in boundary_patterns:
        next_units: list[str] = []
        changed = False
        for unit in units:
            if not flow_timing(unit)["needs_split"]:
                next_units.append(unit)
                continue
            pieces = _split_preserving(unit, pattern)
            if len(pieces) > 1:
                changed = True
                next_units.extend(pieces)
            else:
                next_units.append(unit)
        units = next_units
        if all(not flow_timing(u)["needs_split"] for u in units):
            return units
        if not changed:
            continue

    for include_na in (False, True):
        next_units = []
        for unit in units:
            if not flow_timing(unit)["needs_split"]:
                next_units.append(unit)
                continue
            pieces = _split_at_conjunctions(unit, include_na=include_na)
            next_units.extend(pieces)
        units = next_units
        if all(not flow_timing(u)["needs_split"] for u in units):
            return units
    return None


def _canonical_boundaries(parts: Iterable[str]) -> set[int]:
    """Cumulative non-whitespace character offsets between parts."""
    cleaned=[_canonical(x) for x in parts if _canonical(x)]
    out=set(); total=0
    for part in cleaned[:-1]:
        total += len(part)
        out.add(total)
    return out


def _baseline_uses_only_semantic_boundaries(baseline: list[str], semantic_units: list[str]) -> bool:
    if _canonical(' '.join(baseline)) != _canonical(' '.join(semantic_units)):
        return False
    return _canonical_boundaries(baseline).issubset(_canonical_boundaries(semantic_units))


def _pack_units(units: list[str]) -> list[str] | None:
    """Pack semantic units without exceeding the safe speech envelope."""
    if any(flow_timing(u)["needs_split"] for u in units):
        return None
    packed: list[str] = []
    buf = ""
    for unit in units:
        candidate = f"{buf} {unit}".strip() if buf else unit
        if buf and flow_timing(candidate)["needs_split"]:
            packed.append(buf)
            buf = unit
        else:
            buf = candidate
    if buf:
        packed.append(buf)
    return packed


def rebalance_segments(segments: Iterable[str]) -> tuple[list[str], str]:
    """Locally rebalance overlong clips; prefer previous capacity, then next capacity.

    The function never changes dialogue order and never hard-cuts a word/fixed phrase by length.
    """
    segs = [str(s or "").strip() for s in segments if str(s or "").strip()]
    if not segs:
        return [], "OK"
    original_canonical = _canonical(" ".join(segs))

    i = 0
    guard = 0
    while i < len(segs) and guard < 100:
        guard += 1
        if not flow_timing(segs[i])["needs_split"]:
            i += 1
            continue
        units = _safe_semantic_units(segs[i])
        if not units or len(units) < 2:
            return segs, "UNSPLITTABLE"

        # 1) Previous segment has room: move the current leading complete semantic unit upward.
        first = units[0]
        remainder = " ".join(units[1:]).strip()
        if i > 0 and remainder:
            prev_candidate = f"{segs[i-1]} {first}".strip()
            if not flow_timing(prev_candidate)["needs_split"]:
                segs[i-1] = prev_candidate
                segs[i] = remainder
                i = max(0, i - 1)
                continue

        # 2) No previous room: move the trailing complete semantic unit to the next segment.
        last = units[-1]
        remainder = " ".join(units[:-1]).strip()
        if i + 1 < len(segs) and remainder:
            next_candidate = f"{last} {segs[i+1]}".strip()
            if not flow_timing(next_candidate)["needs_split"]:
                segs[i] = remainder
                segs[i+1] = next_candidate
                i = max(0, i - 1)
                continue

        # 3) Neither neighbor can absorb it: split only on the safe semantic units.
        packed = _pack_units(units)
        if not packed or len(packed) < 2:
            return segs, "UNSPLITTABLE"
        segs[i:i+1] = packed
        i = max(0, i - 1)

    if any(flow_timing(s)["needs_split"] for s in segs):
        return segs, "UNSPLITTABLE"
    if _canonical(" ".join(segs)) != original_canonical:
        return list(segments), "INTEGRITY_FAILED"
    return segs, "OK"



def _valid_max_chars(max_chars) -> int | None:
    try:
        value = int(max_chars)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _swahili_cut_is_unsafe(text: str, cut: int) -> bool:
    """Reject whitespace cuts that leave a Swahili phrase grammatically hanging.

    This is intentionally conservative: punctuation boundaries are handled before this
    helper.  It only protects the final fallback/semantic cuts inside an over-limit
    sentence, so the configured character cap still remains authoritative.
    """
    left_words = re.findall(r"[^\W_]+(?:['’][^\W_]+)?", text[:cut], re.UNICODE)
    right_words = re.findall(r"[^\W_]+(?:['’][^\W_]+)?", text[cut:], re.UNICODE)
    if not left_words or not right_words:
        return False
    left = left_words[-1].lower()
    right = right_words[0].lower()
    prev = left_words[-2].lower() if len(left_words) >= 2 else ""

    # Do not strand common Swahili relation/preposition words at the end, and do not
    # start the next clip with a genitive connector detached from its noun phrase.
    hanging_left = {
        "kwa", "ya", "wa", "la", "cha", "vya", "za", "katika", "kutoka",
        "bila", "hadi", "juu", "chini", "mbele", "nyuma",
    }
    hanging_right = {"ya", "wa", "la", "cha", "vya", "za"}
    if left in hanging_left or right in hanging_right:
        return True

    # Fixed Christian phrases frequently present in the user's Swahili scripts.
    # Reject *any* cut that falls inside one of these phrases, not only the final pair.
    protected_phrases = (
        r"kwa\s+jina\s+la\s+Yesu\s+Kristo",
        r"Bwana\s+wetu\s+Yesu\s+Kristo",
        r"Yesu\s+Kristo",
        r"Roho\s+Mtakatifu",
        r"neema\s+ya\s+Mungu",
        r"upendo\s+wa\s+Mungu",
        r"nguvu\s+ya\s+Mungu",
        r"amani\s+ya\s+Mungu",
        r"mapenzi\s+ya\s+Mungu",
    )
    for pattern in protected_phrases:
        for match in re.finditer(pattern, text, re.I):
            if match.start() < cut < match.end():
                return True
    if (left, right) in {("yesu", "kristo"), ("roho", "mtakatifu")}:
        return True

    # Keep localized number phrases together, e.g. "ishirini na tano".
    if left == "na" and prev in _NUMBER_WORDS and right in _NUMBER_WORDS:
        return True
    if left in _NUMBER_WORDS and right == "na":
        return True
    return False


def _semantic_cut_positions(text: str, limit: int, rules: ReflowPolicy | None = None) -> dict[str, list[int]]:
    """Candidate boundaries no farther than ``limit`` characters into ``text``."""
    buckets: dict[str, list[int]] = {"sentence": [], "punct": [], "swahili": [], "space": []}

    for m in re.finditer("["+re.escape((rules or ReflowPolicy()).sentence_marks)+r"]+[\"'”’)]*" if (rules or ReflowPolicy()).sentence_marks else r"(?!)", text):
        pos = m.end()
        if 0 < pos <= limit:
            buckets["sentence"].append(pos)
    for m in re.finditer("["+re.escape((rules or ReflowPolicy()).clause_marks)+r"]+[\"'”’)]*" if (rules or ReflowPolicy()).clause_marks else r"(?!)", text):
        pos = m.end()
        if 0 < pos <= limit:
            buckets["punct"].append(pos)

    # Only used after the segment itself exceeds the user cap. These are natural
    # Swahili clause starts, not unconditional split keywords.
    conj = re.compile(
        r"\s+(?=(?:hata\s+hivyo|kwa\s+sababu|kwa\s+hiyo|lakini|ikiwa|wakati|ambapo|ili|kwamba|ingawa|kama|au|kisha|ndipo)\b)",
        re.I,
    )
    for m in (conj.finditer(text) if rules is None or rules.swahili_boundaries else []):
        pos = m.start()
        if 0 < pos <= limit and not _swahili_cut_is_unsafe(text, pos):
            buckets["swahili"].append(pos)

    for m in re.finditer(r"\s+", text):
        pos = m.start()
        if 0 < pos <= limit and not _swahili_cut_is_unsafe(text, pos):
            buckets["space"].append(pos)
    return buckets


def _choose_semantic_cut(text: str, limit: int, rules: ReflowPolicy | None = None) -> int | None:
    """Choose a natural boundary before the cap; hard word cuts are last resort only."""
    buckets = _semantic_cut_positions(text, limit, rules)
    min_tail = rules.min_tail_words if rules else 3
    # A complete sentence has priority, followed by punctuation, then a Swahili
    # clause boundary.  Avoid creating a tiny early fragment merely because a period
    # exists near the start; in that case a later comma is more natural for speech.
    natural_floor = min(max(12, int(limit * 0.35)), max(12, limit - 1))
    for kind in ("sentence", "punct", "swahili"):
        preferred = [p for p in buckets[kind] if p >= natural_floor]
        # Do not choose a late comma/semicolon merely because it is closest to the cap when
        # doing so would leave a 1-2 word tail. Prefer an earlier natural boundary instead.
        balanced = [p for p in preferred if not text[p:].strip() or len(_words(text[p:].strip())) >= min_tail]
        if balanced:
            return max(balanced)
        if preferred and kind == "sentence":
            return max(preferred)
    for kind in ("sentence", "punct", "swahili"):
        candidates = [p for p in buckets[kind] if not text[p:].strip() or len(_words(text[p:].strip())) >= min_tail]
        if candidates:
            return max(candidates)
        if buckets[kind] and kind == "sentence":
            return max(buckets[kind])

    spaces = buckets["space"]
    if not spaces:
        return None

    # If the remainder would otherwise be only 1-2 words, move the fallback cut
    # slightly earlier when possible. This reduces the "long line + tiny tail" case
    # without overriding real punctuation boundaries.
    preferred = []
    for pos in spaces:
        left = text[:pos].strip()
        right = text[pos:].strip()
        if len(_words(left)) < 2:
            continue
        if len(right) <= limit and len(_words(right)) < min_tail:
            continue
        preferred.append(pos)
    return max(preferred or spaces)


def _split_over_limit_semantic_first(text: str, limit: int, rules: ReflowPolicy | None = None) -> list[str]:
    """Split only when needed, preferring sentence/punctuation/Swahili boundaries."""
    rest = re.sub(r"\s+", " ", str(text or "")).strip()
    if not rest:
        return []
    out: list[str] = []
    guard = 0
    while len(rest) > limit and guard < 1000:
        guard += 1
        cut = _choose_semantic_cut(rest, limit, rules)
        if cut is None:
            # One indivisible token may exceed the user's cap; never cut a word in half.
            first_space = re.search(r"\s+", rest)
            if not first_space:
                out.append(rest)
                rest = ""
                break
            cut = first_space.start()
        left = rest[:cut].strip()
        right = rest[cut:].strip()
        if not left or not right:
            # Defensive word-safe fallback.
            spaces = [m.start() for m in re.finditer(r"\s+", rest) if 0 < m.start() <= limit]
            if not spaces:
                out.append(rest)
                rest = ""
                break
            cut = max(spaces)
            left, right = rest[:cut].strip(), rest[cut:].strip()
        out.append(left)
        rest = right
    if rest:
        out.append(rest)
    return out


def split_segments_by_max_chars(segments: Iterable[str], max_chars: int | None, *, rules: ReflowPolicy | None = None) -> list[str]:
    """Apply a hard character ceiling *without treating the ceiling as a target cut*.

    Normal complete sentences/clauses are preserved. Only a segment that actually exceeds
    the configured value is split. The split order is:

      1) sentence-ending punctuation;
      2) comma/semicolon/colon;
      3) natural Swahili clause boundary;
      4) whole-word boundary as the final over-limit fallback.

    This intentionally replaces the older "balance every line toward ~85% of the cap"
    behavior, which could cut a perfectly natural spoken sentence in the middle.
    """
    limit = _valid_max_chars(max_chars)
    clean = [re.sub(r"\s+", " ", str(x or "")).strip() for x in segments if str(x or "").strip()]
    if not limit:
        return clean

    out: list[str] = []
    for segment in clean:
        if len(segment) <= limit:
            out.append(segment)
        else:
            out.extend(_split_over_limit_semantic_first(segment, limit, rules))
    return out


def split_segments_by_safe_word_timing(segments: Iterable[str], max_chars: int | None = None) -> list[str]:
    """Resolve timing density only at natural semantic boundaries.

    With an explicit character cap, a sentence that is *within* that cap is never cut at an
    arbitrary whitespace position merely to satisfy timing. If no punctuation/clause boundary
    can safely resolve an over-8-second clip, the segment is kept intact and the caller marks it
    ``UNSPLITTABLE`` for manual handling. A whole-word fallback is permitted only when the text
    itself exceeds the configured character ceiling.
    """
    limit = _valid_max_chars(max_chars)
    out: list[str] = []
    for raw in segments:
        segment = re.sub(r"\s+", " ", str(raw or "")).strip()
        if not segment:
            continue
        if limit and len(segment) > limit:
            out.extend(_split_over_limit_semantic_first(segment, limit))
            continue
        if not flow_timing(segment)["needs_split"]:
            out.append(segment)
            continue

        units = _safe_semantic_units(segment)
        if not units or len(units) < 2:
            # No safe semantic boundary: preserve the sentence rather than creating
            # the user's reported "half a sentence" clip.
            out.append(segment)
            continue

        buf = ""
        for unit in units:
            candidate = f"{buf} {unit}".strip() if buf else unit
            char_ok = not limit or len(candidate) <= limit
            timing_ok = not flow_timing(candidate)["needs_split"]
            if buf and (not char_ok or not timing_ok):
                out.append(buf)
                buf = unit
            else:
                buf = candidate
        if buf:
            out.append(buf)
    return out


def merge_single_word_segments(segments: Iterable[str], max_chars: int | None = None, *, require_safe_timing: bool = False) -> list[str]:
    """Final segmentation gate: never return a one-word Flow clip when a safe merge exists.

    When a maximum character count is configured it is a hard constraint: a one-word clip is
    merged only if the combined text still fits that limit.
    """
    limit = _valid_max_chars(max_chars)
    segs=[str(x or '').strip() for x in segments if str(x or '').strip()]
    guard=0
    while len(segs)>1 and guard<100:
        guard += 1
        idx=next((i for i,x in enumerate(segs) if len(_words(x))==1),None)
        if idx is None: break
        options=[]
        if idx>0:
            candidate=(segs[idx-1]+' '+segs[idx]).strip()
            if not limit or len(candidate) <= limit:
                t=flow_timing(candidate)
                if not require_safe_timing or not t['needs_split']:
                    options.append((1 if t['needs_split'] else 0,float(t['estimated_speech_seconds']),idx-1,'prev',candidate))
        if idx+1<len(segs):
            candidate=(segs[idx]+' '+segs[idx+1]).strip()
            if not limit or len(candidate) <= limit:
                t=flow_timing(candidate)
                if not require_safe_timing or not t['needs_split']:
                    options.append((1 if t['needs_split'] else 0,float(t['estimated_speech_seconds']),idx,'next',candidate))
        if not options: break
        _,_,target,side,candidate=min(options,key=lambda x:(x[0],x[1],0 if x[3]=='prev' else 1))
        if side=='prev':
            segs[target]=candidate; del segs[idx]
        else:
            segs[target]=candidate; del segs[idx+1]
    return segs


_TERMINAL_PUNCTUATION = ".!?。！？,;:，；：-–—"
_CLOSING_QUOTES = "\"'”’)]】》」』"


def _content_canonical(text: str) -> str:
    """Compare spoken content while allowing the reflow layer to normalize punctuation."""
    value = re.sub(r"\s+", "", str(text or ""))
    return re.sub("[" + re.escape(_TERMINAL_PUNCTUATION) + "]+", "", value)


def _normalize_segment_terminal(text: str) -> str:
    """Force exactly one ASCII period at the end of every output segment.

    Interior punctuation is untouched. If punctuation appears immediately before a closing
    quote/bracket, remove that punctuation and keep the closer, then append the final period.
    """
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if not value:
        return ""
    closer = re.escape(_CLOSING_QUOTES)
    marks = re.escape(_TERMINAL_PUNCTUATION)
    m = re.search(rf"([{marks}]+)([{closer}]*)$", value)
    if m:
        value = (value[:m.start(1)] + m.group(2)).rstrip()
    else:
        value = value.rstrip(_TERMINAL_PUNCTUATION).rstrip()
    return value + "."


def _word_cut_is_unsafe(text: str, cut: int) -> bool:
    """Protect common grammatical units using only a small window around the cut."""
    # Do not rescan the whole script for every candidate boundary. A local window contains all
    # phrases protected by this helper and keeps batch reflow fast on very long scripts.
    window_start = max(0, cut - 96)
    window_end = min(len(text), cut + 96)
    local = text[window_start:window_end]
    local_cut = cut - window_start
    left_words = re.findall(r"[^\W_]+(?:['’][^\W_]+)?", local[:local_cut], re.UNICODE)
    right_words = re.findall(r"[^\W_]+(?:['’][^\W_]+)?", local[local_cut:], re.UNICODE)
    if not left_words or not right_words:
        return False
    left = left_words[-1].lower()
    right = right_words[0].lower()

    # Articles/prepositions/conjunctions and common auxiliaries should stay attached to what
    # follows. This list is intentionally conservative and covers the user's frequent languages.
    hanging_left = {
        # Italian
        "il","lo","la","i","gli","le","un","uno","una","di","a","da","in","con","su","per","tra","fra",
        "e","o","ma","che","perché","perche","se","del","della","dei","degli","delle","al","alla","ai","agli","alle",
        "nel","nella","nei","negli","nelle","sul","sulla","sui","sugli","sulle","è","sono","era","erano","sarà","sara",
        "saranno","sarebbe","sarebbero","ha","hanno","aveva","avevano","avrà","avra","avranno","può","puo","possono",
        "deve","devono","non",
        # English
        "the","a","an","and","or","but","if","because","to","of","in","on","at","for","with","from","is","are","was",
        "were","will","would","can","could","should","must","has","have","had","not",
        # Spanish / French / Portuguese
        "el","los","las","una","unos","unas","de","en","por","para","y","pero","porque","que","si","et","mais","avec",
        "sans","dans","sur","pour","du","des","au","aux","est","sont","sera","seront","serait","seraient","um","uma","os",
        "as","com","sem","em","e","mas","porque","será","serao","serão",
    }
    hanging_right = {
        "di","del","della","dei","degli","delle","a","al","alla","ai","agli","alle","da","in","con","su","per",
        "of","to","for","with","from","de","du","des","au","aux","por","para","com",
    }
    if left in hanging_left or right in hanging_right:
        return True
    return _swahili_cut_is_unsafe(local, local_cut)


def _reference_boundary_positions(text: str, rules: ReflowPolicy | None = None) -> dict[int, float]:
    """Return candidate cut positions and their semantic penalty (lower is better)."""
    policy = rules or ReflowPolicy()
    n = len(text)
    quality: dict[int, float] = {0: 0.0, n: 0.0}

    def add(pos: int, score: float):
        if 0 < pos < n:
            quality[pos] = min(score, quality.get(pos, score))

    if policy.sentence_marks:
        pattern = re.compile("[" + re.escape(policy.sentence_marks) + r"]+[\"'”’)]*")
        for m in pattern.finditer(text):
            add(m.end(), 0.0)
    if policy.clause_marks:
        pattern = re.compile("[" + re.escape(policy.clause_marks) + r"]+[\"'”’)]*")
        for m in pattern.finditer(text):
            add(m.end(), 0.08)

    # Multilingual clause starts used only as a stronger hint than an arbitrary word boundary.
    clause_start = re.compile(
        r"\s+(?=(?:"
        r"hata\s+hivyo|kwa\s+sababu|kwa\s+hiyo|lakini|ikiwa|wakati|ambapo|ili|kwamba|ingawa|kama|au|kisha|ndipo|"
        r"and|but|because|so|while|when|if|then|or|"
        r"e|ma|perché|perche|quindi|mentre|quando|se|oppure|"
        r"y|pero|porque|entonces|mientras|cuando|si|o|"
        r"et|mais|parce\s+que|donc|pendant\s+que|quand|ou|"
        r"mas|então|entao|enquanto"
        r")\b)",
        re.I,
    )
    for m in clause_start.finditer(text):
        pos = m.start()
        if not _word_cut_is_unsafe(text, pos):
            add(pos, 0.20)

    # Whole-word fallback. Never split inside a word or a protected grammatical unit.
    for m in re.finditer(r"\s+", text):
        pos = m.start()
        if not _word_cut_is_unsafe(text, pos):
            add(pos, 0.45)
    return quality


def _reference_reflow(text: str, target: int, rules: ReflowPolicy | None = None) -> list[str]:
    """Balance segments around a *reference* length rather than a hard ceiling.

    Natural punctuation may justify a somewhat longer line; visibly short lines are strongly
    penalized so pasted/manual line breaks do not survive merely because they were already there.
    """
    source = re.sub(r"\s+", " ", str(text or "")).strip()
    if not source:
        return []
    target = max(1, int(target))

    # A single naturally-sized passage does not need an artificial cut.
    if len(source) <= max(target + 8, int(target * 1.28)):
        return [source]

    quality = _reference_boundary_positions(source, rules)
    positions = sorted(quality)
    if len(positions) <= 2:
        # No safe boundary (common for punctuation-free CJK). Keep it intact rather than
        # guessing a word boundary and damaging meaning.
        return [source]

    inf = float("inf")
    dp = [inf] * len(positions)
    prev = [-1] * len(positions)
    dp[0] = 0.0
    max_window = max(target + 32, int(target * 2.15))
    soft_min = max(1.0, target * 0.58)
    soft_max = max(float(target), target * 1.38)

    for j in range(1, len(positions)):
        end = positions[j]
        best_any = None
        for i in range(j - 1, -1, -1):
            if dp[i] == inf:
                continue
            start = positions[i]
            raw_len = end - start
            if raw_len > max_window and i != 0:
                break
            chunk = source[start:end].strip()
            if not chunk:
                continue
            length = len(chunk)
            deviation = (length - target) / max(target, 1)
            cost = dp[i] + 4.50 * (deviation * deviation)
            if length < soft_min:
                cost += 8.5 * ((soft_min - length) / max(target, 1)) ** 1.35
            if length > soft_max:
                cost += 2.4 * ((length - soft_max) / max(target, 1)) ** 1.25
            if end != len(source):
                cost += quality.get(end, 0.45)
            # Prefer fewer segments when two layouts are otherwise very close.
            cost += 0.035
            if best_any is None or cost < best_any[0]:
                best_any = (cost, i)
        if best_any is not None:
            dp[j], prev[j] = best_any

    if prev[-1] < 0:
        return [source]

    chunks: list[str] = []
    idx = len(positions) - 1
    while idx > 0:
        i = prev[idx]
        if i < 0:
            return [source]
        chunk = source[positions[i]:positions[idx]].strip()
        if chunk:
            chunks.append(chunk)
        idx = i
    chunks.reverse()

    # Final short-tail safety net. Merge a conspicuously short piece with the neighbor that
    # lands closest to the reference size. The reference is intentionally allowed to be exceeded.
    guard = 0
    min_tail_words = (rules or ReflowPolicy()).min_tail_words
    while len(chunks) > 1 and guard < 100:
        guard += 1
        short_i = next((
            i for i, seg in enumerate(chunks)
            if len(seg) < target * 0.48
            or (0 < len(_words(seg)) < min_tail_words)
        ), None)
        if short_i is None:
            break
        options = []
        if short_i > 0:
            merged = f"{chunks[short_i-1]} {chunks[short_i]}".strip()
            options.append((abs(len(merged) - target), len(merged), "prev", merged))
        if short_i + 1 < len(chunks):
            merged = f"{chunks[short_i]} {chunks[short_i+1]}".strip()
            options.append((abs(len(merged) - target), len(merged), "next", merged))
        if not options:
            break
        _, merged_len, side, merged = min(options, key=lambda x: (x[0], x[1]))
        # Do not create an extreme monster segment just to eliminate a tiny tail.
        if merged_len > max(target + 45, int(target * 1.72)) and len(chunks[short_i]) >= target * 0.30:
            break
        if side == "prev":
            chunks[short_i-1] = merged
            del chunks[short_i]
        else:
            chunks[short_i] = merged
            del chunks[short_i+1]
    return chunks

def _sentence_units_for_reflow(text: str, rules: ReflowPolicy | None = None) -> list[str]:
    """Return complete sentence units without merging neighboring sentences.

    With a user character ceiling enabled, a full sentence is the primary Flow speech unit.
    This deliberately avoids the legacy smart_segment() behavior that can rebalance a sentence
    at an arbitrary word boundary even when that sentence itself is still under the user's cap.
    """
    source = re.sub(r"\s+", " ", str(text or "")).strip()
    if not source:
        return []
    marks=(rules or ReflowPolicy()).sentence_marks
    return _split_preserving(source, re.compile("["+re.escape(marks)+r"]+[\"'”’)]*")) if marks else [source]


def _reflow_sentence_with_limit(sentence: str, limit: int, rules: ReflowPolicy | None = None) -> tuple[list[str], bool]:
    """Reflow one complete sentence under the user's semantic-first rule.

    A sentence at or below ``limit`` is never cut internally. Only after it exceeds the cap may
    comma/semicolon/colon, Swahili clause boundaries, and finally a whole-word boundary be used.
    If an over-limit sentence is still too dense after the character split, timing repair is
    allowed only at natural semantic boundaries (never an arbitrary whitespace cut).
    """
    sentence = re.sub(r"\s+", " ", str(sentence or "")).strip()
    if not sentence:
        return [], False

    if len(sentence) <= limit:
        # The configured number is a ceiling, not a target. Preserve the natural sentence even if
        # it is close to the limit; a timing warning may still be surfaced to the user below.
        return [sentence], bool(flow_timing(sentence)["needs_split"])

    parts = split_segments_by_max_chars([sentence], limit, rules=rules)
    # Once the over-limit sentence has been split at the best available semantic boundary, do
    # not perform a second timing-only word rebalance. That second pass was the main source of
    # "half a sentence" clips. If a resulting semantic chunk is still dense, keep it intact and
    # surface the existing duration/manual-resolution warning instead of cutting it again.
    unresolved = any(flow_timing(part)["needs_split"] for part in parts)
    return parts, unresolved


_INSTRUCTION_MAX_SECONDS = 7.5
_INSTRUCTION_WORD_SOFT_MIN = 14
_INSTRUCTION_WORD_SOFT_MAX = 22
_INTERNAL_WRAPPERS = "\\\"'‘’“”()[]{}（）【】《》「」『』"
_KNOWN_ACRONYMS = {"AI", "API", "GPT", "SUV", "TV", "SMS", "URL", "USB", "CPU", "GPU", "ID", "OTP"}


def _strip_instruction_wrappers(text: str) -> str:
    """Remove only non-spoken quote/bracket glyphs required by the user's instruction."""
    table = str.maketrans("", "", _INTERNAL_WRAPPERS)
    return str(text or "").translate(table)


def _normalize_uppercase_swahili(text: str) -> str:
    """Normalize ordinary all-caps words while leaving common technical acronyms intact."""
    word_re = re.compile(r"[^\W\d_]+", re.UNICODE)
    def repl(match: re.Match[str]) -> str:
        token = match.group(0)
        if token in _KNOWN_ACRONYMS:
            return token
        letters = [c for c in token if c.isalpha()]
        if len(letters) >= 2 and token == token.upper() and token != token.lower():
            return token[:1].upper() + token[1:].lower()
        return token
    return word_re.sub(repl, str(text or ""))


def _swahili_ordinal_word(n: int) -> str:
    # Natural compact ordinal forms used in common Bible references/ranges.
    special = {
        1: "kwanza", 2: "pili", 3: "tatu", 4: "nne", 5: "tano", 6: "sita",
        7: "saba", 8: "nane", 9: "tisa", 10: "kumi",
    }
    return special.get(int(n), number_to_swahili(int(n)))




def _normalize_date_time_context(text: str) -> str:
    """Convert common numeric date/time forms before generic identifier protection runs."""
    value = str(text or "")

    def ymd(m: re.Match[str]) -> str:
        year, month, day = map(int, m.groups())
        return f"tarehe {number_to_swahili(day)} mwezi wa {number_to_swahili(month)} mwaka {number_to_swahili(year)}"

    def dmy(m: re.Match[str]) -> str:
        day, month, year = map(int, m.groups())
        return f"tarehe {number_to_swahili(day)} mwezi wa {number_to_swahili(month)} mwaka {number_to_swahili(year)}"

    # ISO first so 2026-09-24 cannot be misread as D/M/Y.
    value = re.sub(r"(?:\btarehe\s+)?(?<!\d)(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?!\d)", ymd, value, flags=re.I)
    value = re.sub(r"(?:\btarehe\s+)?(?<!\d)(\d{1,2})[-/](\d{1,2})[-/](\d{4})(?!\d)", dmy, value, flags=re.I)

    def clock(m: re.Match[str]) -> str:
        hour, minute = int(m.group(1)), int(m.group(2))
        base = f"saa {number_to_swahili(hour)}"
        return base if minute == 0 else f"{base} na dakika {number_to_swahili(minute)}"

    # Optional existing "saa" is consumed so it is never duplicated.
    value = re.sub(r"(?:\bsaa\s+)?(\d{1,2}):(\d{2})(?!\d)", clock, value, flags=re.I)
    return value
def _normalize_bible_number_context(text: str) -> str:
    """Handle the context-sensitive Swahili number forms explicitly requested by the user."""
    value = str(text or "")
    # Numbered Bible books: 2 Wafalme -> Wafalme wa Pili.
    books = {
        "Wafalme": "wa", "Wakorintho": "wa", "Wathesalonike": "wa", "Timotheo": "wa",
        "Petro": "wa", "Yohana": "wa", "Samweli": "wa", "Mambo ya Nyakati": "ya",
    }
    names = "|".join(sorted((re.escape(x) for x in books), key=len, reverse=True))
    pattern = re.compile(rf"\b([123])\s+({names})\b", re.I)
    def book_repl(m: re.Match[str]) -> str:
        num = int(m.group(1)); raw_book = m.group(2)
        canonical = next((b for b in books if b.lower() == raw_book.lower()), raw_book)
        return f"{canonical} {books.get(canonical, 'wa')} {_swahili_ordinal_word(num).capitalize()}"
    value = pattern.sub(book_repl, value)

    # Verse ranges use ordinal agreement in the requested form:
    # mistari ya 5 hadi 6 -> mistari ya tano hadi ya sita.
    def verse_range(m: re.Match[str]) -> str:
        a, b = int(m.group(1)), int(m.group(2))
        return f"mistari ya {_swahili_ordinal_word(a)} hadi ya {_swahili_ordinal_word(b)}"
    value = re.sub(r"\bmistari\s+ya\s+(\d{1,4})\s+hadi\s+(\d{1,4})\b", verse_range, value, flags=re.I)
    return value


def _instruction_speech_seconds(text: str) -> float:
    """Estimate natural Swahili speech for the 7.5-second reflow rule.

    The user's 14-22 word band is guidance rather than a fixed limit.  The estimator therefore
    uses a natural Swahili word rate and a small adjustment for average word length/punctuation.
    """
    value = str(text or "")
    words = _words(value)
    if not words:
        return 0.0
    avg_len = sum(len(w) for w in words) / len(words)
    length_factor = min(1.18, max(0.90, 1.0 + (avg_len - 5.5) * 0.035))
    base = (len(words) / 2.75) * length_factor
    pauses = (
        len(re.findall(r"[,，]", value)) * 0.07
        + len(re.findall(r"[;:；：]", value)) * 0.11
        + len(re.findall(r"[.!?。！？]", value)) * 0.15
    )
    return round(base + pauses, 2)


def _punctuation_boundaries(text: str, rules: ReflowPolicy | None = None) -> list[tuple[int, int]]:
    """Return source punctuation boundaries as (cut_position, strength).

    strength 0: period/question/exclamation; 1: semicolon/colon; 2: comma.
    No whitespace/conjunction boundary is ever created here.
    """
    policy = rules or ReflowPolicy()
    sentence = set(policy.sentence_marks or ".!?。！？")
    clause = set(policy.clause_marks or ",;:，；：")
    out: list[tuple[int, int]] = []
    for m in re.finditer(r"[.!?。！？;:；：,，]+", text):
        marks = m.group(0)
        if any(ch in sentence and ch in ".!?。！？" for ch in marks):
            strength = 0
        elif any(ch in ";:；：" for ch in marks):
            strength = 1
        elif any(ch in ",，" for ch in marks):
            strength = 2
        else:
            continue
        out.append((m.end(), strength))
    return out


def _instruction_reflow(text: str, *, reference_chars: int | None = None, rules: ReflowPolicy | None = None) -> tuple[list[str], str]:
    """Apply custom segmentation rules based on user reference character limit and natural punctuation."""
    lines = str(text or "").splitlines()
    all_chunks = []
    overall_status = "OK"
    
    ref = reference_chars if reference_chars else 55

    for line in lines:
        source = line.strip()
        if not source:
            continue
            
        boundaries = _punctuation_boundaries(source, rules)
        positions = [0]
        strengths: dict[int, int] = {}
        for pos, strength in boundaries:
            if 0 < pos < len(source):
                if pos not in strengths:
                    positions.append(pos)
                    strengths[pos] = strength
                else:
                    strengths[pos] = min(strengths[pos], strength)
                    
        # Add dash boundaries
        for m in re.finditer(r"[\-–—]+", source):
            pos = m.end()
            if 0 < pos < len(source):
                if pos not in strengths:
                    positions.append(pos)
                    strengths[pos] = 2
                else:
                    strengths[pos] = min(strengths[pos], 2)

        # Add Swahili conjunction boundaries
        words = r"lakini|kwa\s+sababu|hivyo|ikiwa|wakati|ili|kwamba|ambaye|ambalo|ambao|au|kisha|ndipo|na"
        for m in re.finditer(rf"\s+(?=(?:{words})\b)", source, re.I):
            pos = m.start() + 1
            if 0 < pos < len(source):
                if pos not in strengths:
                    positions.append(pos)
                    strengths[pos] = 3
                else:
                    strengths[pos] = min(strengths[pos], 3)

        # Add space boundaries as last resort
        for m in re.finditer(r"\s+", source):
            pos = m.start() + 1
            if 0 < pos < len(source):
                if pos not in strengths:
                    positions.append(pos)
                    strengths[pos] = 4
                else:
                    strengths[pos] = min(strengths[pos], 4)

        # Add EVERY character boundary for CJK fallback (strength 5)
        for i in range(1, len(source)):
            if i not in strengths:
                positions.append(i)
                strengths[i] = 5

        positions.append(len(source))
        positions = sorted(set(positions))

        inf = None
        best: list[tuple | None] = [inf] * len(positions)
        prev: list[int] = [-1] * len(positions)
        best[0] = (0, 0, 0.0)
        
        for j in range(1, len(positions)):
            end = positions[j]
            winner = None
            winner_i = -1
            for i in range(j - 1, -1, -1):
                if best[i] is None:
                    continue
                start = positions[i]
                # Optimization: if the distance is way beyond our max allowed length,
                # and we know there are internal boundaries (which there always are due to CJK fallback),
                # we can break early instead of continuing to search further back.
                if end - start > ref * 1.5 + 20:  # add small buffer for stripping
                    break
                    
                chunk = source[start:end].strip()
                if not chunk:
                    continue
                    
                length = len(chunk)
                internal_punct = False
                for p in positions[i+1:j]:
                    if strengths[p] < 5:  # has a real word/punct boundary
                        internal_punct = True
                        break
                
                # Avoid overly long segments if we can break them
                if length > ref * 1.5 and internal_punct:
                    continue
                    
                short_penalty = 0.0
                if length < ref * 0.4 and end != len(source):
                    short_penalty = (ref * 0.4 - length) * 0.2
                    
                unavoidable_over = 1 if length > ref else 0
                rhythm_penalty = abs(length - ref) * 0.1
                
                bp_map = {0: 0.0, 1: 0.2, 2: 0.5, 3: 1.0, 4: 2.0, 5: 5.0}
                boundary_penalty = 0.0 if end == len(source) else bp_map.get(strengths.get(end, 5), 5.0)
                
                base = best[i]
                cost = (
                    base[0] + unavoidable_over,
                    base[1] + boundary_penalty + short_penalty,
                    base[2] + rhythm_penalty
                )
                
                if winner is None or cost < winner:
                    winner, winner_i = cost, i
                    
            if winner is not None:
                best[j] = winner
                prev[j] = winner_i

        chunks: list[str] = []
        idx = len(positions) - 1
        while idx > 0:
            i = prev[idx]
            if i < 0:
                chunks = [source]
                break
            chunk = source[positions[i]:positions[idx]].strip()
            if chunk:
                chunks.append(chunk)
            idx = i
        if len(chunks) > 1 and chunks[0] != source:
            chunks.reverse()

        for chunk in chunks:
            if chunk.endswith(','):
                chunk = chunk[:-1] + '.'
            elif chunk.endswith('-') or chunk.endswith('–') or chunk.endswith('—'):
                chunk = re.sub(r'[\-–—]+$', '.', chunk)
            elif not re.search(r'[.!?。！？,;:，；：]\s*$', chunk):
                chunk = chunk + '.'
            all_chunks.append(chunk)
            if len(chunk) > ref * 1.5:
                overall_status = "UNSPLITTABLE"

    if not all_chunks:
        return [], "OK"
    return all_chunks, overall_status

def prepare_swahili_speech(text: str, max_chars: int | None = None, *, rules: ReflowPolicy | None = None) -> SpeechPreparation:
    original = str(text or "")
    cleaned = strip_decorative_symbols(original)
    cleaned = _strip_instruction_wrappers(cleaned)
    cleaned = _normalize_uppercase_swahili(cleaned)
    cleaned = _normalize_date_time_context(cleaned)
    cleaned = _normalize_bible_number_context(cleaned)
    spoken_source, decisions = localize_swahili_numbers(cleaned)

    # V0.13.5.91: pasted line breaks are ignored.  7.5-second natural Swahili speech is the primary
    # segmentation rule; the former character setting is retained only as a weak rhythm tie-breaker.
    balanced, status = _instruction_reflow(spoken_source, reference_chars=max_chars, rules=rules)
    production_spoken = " ".join(balanced).strip()

    # Punctuation is now preserved exactly.  Integrity therefore compares every non-whitespace
    # character after the explicitly allowed preprocessing transformations above.
    
    production_spoken = " ".join(balanced).strip()
    integrity = _content_canonical(production_spoken) == _content_canonical(spoken_source)
    if not integrity:
        balanced = [spoken_source] if spoken_source.strip() else []
        production_spoken = " ".join(balanced).strip()
        status = "INTEGRITY_FAILED"
        integrity = _content_canonical(production_spoken) == _content_canonical(spoken_source)

    # Keep the existing downstream Flow duration metadata unchanged.  Segmentation itself follows
    # the new 7.5-second instruction rather than the older 6.3-second Flow safety heuristic.
    timings = tuple(flow_timing(s) for s in balanced)
    return SpeechPreparation(
        original_text=original,
        spoken_text=production_spoken,
        segments=tuple(balanced),
        timings=timings,
        timing_status=status,
        integrity_ok=integrity,
        number_decisions=decisions,
    )

def timing_metadata(text: str, status: str = "") -> dict:
    result = flow_timing(text)
    return {
        "estimated_speech_duration": float(result["estimated_speech_seconds"]),
        "flow_duration_seconds": int(result["duration"]),
        "timing_status": status or ("UNSPLITTABLE" if result["needs_split"] else "OK"),
    }
