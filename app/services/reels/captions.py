from __future__ import annotations
import re
from pathlib import Path
from .text_rules import normalize_subtitle_text, normalize_required_capitalization
def parse_srt(srt, language=None):
    blocks = re.split(r"\r?\n\s*\r?\n", srt.strip())
    result = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        timing_index = next((i for i, line in enumerate(lines) if "-->" in line), -1)
        if timing_index < 0: continue
        match = re.match(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)", lines[timing_index])
        if not match: continue
        raw_values = match.groups(); values = [int(value) for value in raw_values]
        start = values[0] * 3600 + values[1] * 60 + values[2] + values[3] / (10 ** len(raw_values[3]))
        end = values[4] * 3600 + values[5] * 60 + values[6] + values[7] / (10 ** len(raw_values[7]))
        # 保留用户手动换行；自由整段字幕需要按输入排版显示全部行。
        # 专名大小写 + 语言包引号/书写规范（希腊 «»、中文标点等）。
        text = normalize_subtitle_text("\n".join(lines[timing_index + 1:]).strip(), language=language)
        if text: result.append((start, max(start + .1, end), text))
    return result

def _format_srt_timestamp(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    seconds %= 3600
    m = int(seconds // 60)
    seconds %= 60
    s = int(seconds)
    ms = int(round((seconds - s) * 1000))
    if ms >= 1000:
        s += 1
        ms -= 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def events_to_srt(events) -> str:
    """(start, end, text) 秒级事件 → SRT 文本。"""
    blocks = []
    for index, item in enumerate(events or [], 1):
        if not item or len(item) < 3:
            continue
        start, end, text = float(item[0]), float(item[1]), str(item[2] or "").strip()
        if not text or end <= start:
            continue
        blocks.append(
            f"{index}\n{_format_srt_timestamp(start)} --> {_format_srt_timestamp(end)}\n{text}"
        )
    return ("\n\n".join(blocks) + ("\n" if blocks else ""))

def fix_srt_overlaps(srt, gap_ms=20, min_duration_ms=80):
    """Fix adjacent SRT overlaps without touching caption text or word timing caches."""
    entries=parse_srt(srt)
    if len(entries) < 2: return srt,0
    entries=[list(item) for item in sorted(entries,key=lambda item:(item[0],item[1]))]
    gap=max(0,int(gap_ms))/1000; minimum=max(20,int(min_duration_ms))/1000
    fixed=0
    for index in range(1,len(entries)):
        previous=entries[index-1]; current=entries[index]
        if current[0] >= previous[1]: continue
        # Subtitle Edit style: normally shorten the previous cue to just before
        # the next cue.  Only move the next start when the previous cue would
        # otherwise become too short to display.
        candidate=current[0]-gap
        if candidate >= previous[0]+minimum:
            previous[1]=candidate
        else:
            previous[1]=previous[0]+minimum
            current[0]=previous[1]+gap
            current[1]=max(current[1],current[0]+minimum)
        fixed+=1
    if not fixed: return srt,0

    def stamp(value):
        milliseconds=max(0,round(float(value)*1000)); hours,remainder=divmod(milliseconds,3600000)
        minutes,remainder=divmod(remainder,60000); seconds,millis=divmod(remainder,1000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

    blocks=[f"{index}\n{stamp(start)} --> {stamp(end)}\n{text}"
            for index,(start,end,text) in enumerate(entries,1)]
    return "\n\n".join(blocks)+"\n",fixed

def align_word_srt_to_phrase_srt(word_srt, phrase_srt, old_phrase_srt=""):
    """Make the word/karaoke track use the same clock as the visible phrase track.

    Recognition providers may return overlapping word timestamps.  The phrase track is
    subsequently repaired and can also be resized on the visual timeline.  Keeping the
    original word cache in either case makes the highlight run on a different clock.
    This routine preserves real word pacing when possible, but fits it monotonically
    inside the current phrase boundaries.  Text corrections that add/remove words are
    redistributed inside that phrase instead of reusing the wrong word by index.
    """
    words = parse_srt(word_srt)
    phrases = parse_srt(phrase_srt)
    old_phrases = parse_srt(old_phrase_srt) if old_phrase_srt else phrases
    if not words or not phrases:
        return word_srt or ""

    result = []
    cursor = 0
    for index, (new_start, new_end, new_text) in enumerate(phrases):
        new_tokens = tokens_for(new_text)
        if not new_tokens or new_end <= new_start:
            continue
        if index < len(old_phrases):
            old_start, old_end, old_text = old_phrases[index]
            consume = max(1, len(tokens_for(old_text)))
        else:
            old_start, old_end = new_start, new_end
            consume = len(new_tokens)
        source_words = words[cursor:cursor + consume]
        cursor += consume
        duration = max(0.04, new_end - new_start)

        if len(source_words) == len(new_tokens):
            # 词数一致：优先保留 ASR 绝对时间（对口型），只有整体漂出句界才等比缩放
            in_bounds = all(
                (new_start - 0.08) <= float(item[0]) and float(item[1]) <= (new_end + 0.08)
                for item in source_words
            )
            if in_bounds:
                raw = [
                    (float(item[0]), float(item[1]), token)
                    for item, token in zip(source_words, new_tokens)
                ]
            elif old_end > old_start + 1e-6:
                scale = duration / (old_end - old_start)
                raw = [
                    (
                        new_start + (item[0] - old_start) * scale,
                        new_start + (item[1] - old_start) * scale,
                        token,
                    )
                    for item, token in zip(source_words, new_tokens)
                ]
            else:
                step = duration / len(new_tokens)
                raw = [
                    (new_start + step * i, new_start + step * (i + 1), token)
                    for i, token in enumerate(new_tokens)
                ]
        else:
            # Keep matching words as timing anchors; estimate only changed runs.
            from difflib import SequenceMatcher
            def norm(token):
                return re.sub(r"[^\w]", "", str(token).casefold())
            scale = duration / max(.001, old_end - old_start)
            anchors = [(new_start + (s - old_start) * scale,
                        new_start + (e - old_start) * scale, text)
                       for s, e, text in source_words]
            matcher = SequenceMatcher(None, [norm(w[2]) for w in anchors],
                                      [norm(t) for t in new_tokens], autojunk=False)
            raw = []
            for tag, i0, i1, j0, j1 in matcher.get_opcodes():
                if tag == "equal":
                    raw.extend((a[0], a[1], t) for a, t in zip(anchors[i0:i1], new_tokens[j0:j1]))
                    continue
                if j0 == j1:
                    continue
                span0 = anchors[i0][0] if i0 < i1 else (anchors[i0 - 1][1] if i0 else new_start)
                span1 = anchors[i1 - 1][1] if i0 < i1 else (anchors[i0][0] if i0 < len(anchors) else new_end)
                span0, span1 = max(new_start, span0), min(new_end, span1)
                weights = [_token_speech_weight(t) for t in new_tokens[j0:j1]]
                total = sum(weights) or len(weights)
                slot_cursor = span0
                for token, weight in zip(new_tokens[j0:j1], weights):
                    end = slot_cursor + max(0., span1 - span0) * weight / total
                    raw.append((slot_cursor, end, token))
                    slot_cursor = end

        # Clamp provider overlaps and rounding drift.  Leave a tiny monotonic slot for
        # every remaining word so no highlight can escape into the adjacent sentence.
        fitted = []
        previous_end = new_start
        count = len(raw)
        for word_index, (start, end, token) in enumerate(raw):
            remaining = count - word_index - 1
            latest_end = new_end - remaining * 0.001
            start = max(new_start, previous_end, min(float(start), latest_end - 0.001))
            end = min(new_end, max(start + 0.001, float(end)))
            if end <= start:
                end = min(new_end, start + 0.001)
            fitted.append((start, end, token))
            previous_end = end
        result.extend(fitted)
    return events_to_srt(result) if result else (word_srt or "")

def group_word_srt(srt, max_chars=36, max_duration=4.6, max_words=999, return_fix_count=False):
    """把词级时间轴合并成便于阅读/编辑的逐句 SRT，保留首尾真实时间。"""
    words = parse_srt(srt)
    if not words: return (srt,0) if return_fix_count else srt
    # 已经是正常句级字幕时不重复合并。
    if len(words) <= 2 or sum(len(tokens_for(text)) for _,_,text in words) > len(words) * 2:
        fixed,count=fix_srt_overlaps(srt)
        return (fixed,count) if return_fix_count else fixed
    phrases=[]; current=[]; start=None; end=None

    def flush():
        nonlocal current, start, end
        if current:
            phrases.append((start or 0, end or (start or 0) + .4, " ".join(current)))
        current=[]; start=end=None

    for w_start,w_end,text in words:
        pause = 0 if end is None else max(0, w_start - end)
        candidate=(" ".join(current+[text])).strip()
        # 长停顿、过长句子和行宽溢出时，在当前词之前切句；避免只显示单个词。
        # 完全根据语音停顿与语义自适应，仅通过 max_chars (字宽限制，最多2行) 作硬切分
        if current and ((pause >= .52 and len(current) >= 2) or len(current) >= max_words or len(candidate) > max_chars
                        or (w_end - (start or w_start)) > max_duration):
            flush()
        if start is None: start=w_start
        current.append(text); end=w_end
        sentence_end=bool(re.search(r"[.!?。！？…][\"'”’)]?$",text))
        if sentence_end and len(current) >= 2:
            flush()
    flush()
    blocks=[]
    for index,(start,end,text) in enumerate(phrases,1):
        def stamp(value):
            ms=max(0,round(value*1000)); h,rem=divmod(ms,3600000); m,rem=divmod(rem,60000); sec,milli=divmod(rem,1000)
            return f"{h:02d}:{m:02d}:{sec:02d},{milli:03d}"
        blocks.append(f"{index}\n{stamp(start)} --> {stamp(end)}\n{text}")
    fixed,count=fix_srt_overlaps("\n\n".join(blocks)+"\n")
    return (fixed,count) if return_fix_count else fixed

def _srt_looks_word_level(srt_text: str) -> bool:
    """粗判 SRT 是否像词级轴（短 cue、少词），用于旁路 .srt 误当句级。"""
    try:
        entries = parse_srt(srt_text or "")
    except Exception:
        return False
    if len(entries) < 4:
        return False
    durations = [max(0.0, float(e[1]) - float(e[0])) for e in entries]
    avg = sum(durations) / max(1, len(durations))
    short = sum(1 for d in durations if d <= 1.25) / len(durations)
    light = sum(1 for e in entries if len(tokens_for(e[2])) <= 2) / len(entries)
    return avg <= 1.35 and short >= 0.55 and light >= 0.55

def _token_speech_weight(token: str) -> float:
    """口型估时权重：汉字按字，拉丁按字母（长词占更久），优于「一词一分」均分。"""
    text = str(token or "").strip()
    if not text:
        return 1.0
    cjk = sum(1 for ch in text if "\u3400" <= ch <= "\u9fff")
    if cjk:
        return float(max(1, cjk))
    letters = sum(1 for ch in text if ch.isalnum())
    return float(max(1, letters))

def expand_phrase_srt_to_estimated_words(phrase_srt: str) -> str:
    """句级 SRT → 词级估时轴（按字长占比切开）。

    无词级 ASR 时的保底。口播常在句首有起音、句尾有停顿：若把 100% 句长塞满词，
    高亮会整体偏快。留出句首/句尾静音垫，降低「字幕抢嘴」感。
    有真词级轴时不要用本函数覆盖。
    """
    events = parse_srt(phrase_srt or "")
    if not events:
        return phrase_srt or ""
    out = []
    for start, end, text in events:
        tokens = tokens_for(text)
        if len(tokens) <= 1:
            out.append((float(start), float(end), str(text or "").strip() or (tokens[0] if tokens else "")))
            continue
        weights = [_token_speech_weight(tok) for tok in tokens]
        total_w = sum(weights) or float(len(tokens))
        dur = max(0.08, float(end) - float(start))
        # 句首起音 + 句尾停顿：避免词窗挤满整句导致跟读偏快
        pad_head = min(0.12, dur * 0.06)
        pad_tail = min(0.20, dur * 0.10)
        if pad_head + pad_tail > dur * 0.35:
            pad_head = dur * 0.05
            pad_tail = dur * 0.08
        speech_dur = max(0.08, dur - pad_head - pad_tail)
        cursor = float(start) + pad_head
        speech_end = float(end) - pad_tail
        for i, tok in enumerate(tokens):
            slot = speech_dur * (weights[i] / total_w)
            te = speech_end if i == len(tokens) - 1 else cursor + slot
            if te <= cursor:
                te = min(speech_end, cursor + 0.04)
            out.append((cursor, te, tok))
            cursor = te
    return events_to_srt(out) if out else (phrase_srt or "")

def ensure_word_level_srt(word_or_phrase_srt: str, phrase_srt: str = "") -> tuple[str, bool]:
    """保证有可用于对口型的词级轴。返回 (word_srt, estimated)。

    estimated=True 表示由句轴按字长估出（非 ASR 真词时），仍优于句内等分。
    """
    candidate = str(word_or_phrase_srt or "").strip()
    phrase = str(phrase_srt or "").strip()
    if candidate and _srt_looks_word_level(candidate):
        return candidate, False
    base = candidate if (candidate and "-->" in candidate) else phrase
    if not base or "-->" not in base:
        return candidate or phrase, False
    if _srt_looks_word_level(base):
        return base, False
    estimated = expand_phrase_srt_to_estimated_words(base)
    if estimated and "-->" in estimated:
        return estimated, True
    return base, False

def tokens_for(text):
    if re.search(r"[\u3400-\u9fff]", text):
        return [char for char in text if not char.isspace()]
    return re.findall(r"\S+", text)

def _srt_stamp(value):
    milliseconds = max(0, round(float(value) * 1000))
    hours, remainder = divmod(milliseconds, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

def _is_cjk_heavy(text):
    sample = str(text or "")
    if not sample:
        return False
    cjk = sum(1 for ch in sample if "\u3400" <= ch <= "\u9fff")
    letters = sum(1 for ch in sample if ch.isalpha() or "\u3400" <= ch <= "\u9fff")
    return letters > 0 and cjk / max(1, letters) > 0.35

def align_source_text_to_srt_cues(events, source_text):
    """Map plain source script onto existing SRT cues. Timestamps stay with events.

    Returns list[str] new cue texts (same length as events).
    """
    from difflib import SequenceMatcher

    if not events:
        return []
    source_text = re.sub(r"\s+", " ", str(source_text or "").strip())
    if not source_text:
        return [text for _s, _e, text in events]

    old_texts = [str(text or "").strip() for _s, _e, text in events]
    # 1) 句/行数恰好相等：一一对应
    # 希腊语问号是 ';'；另含中文/英文句读与间隔号
    chunks = [
        value.strip()
        for value in re.split(r"(?<=[。！？.!?…;；·])\s*|\r?\n+", source_text)
        if value.strip()
    ]
    if len(chunks) == len(events):
        return chunks

    is_cjk = _is_cjk_heavy(source_text + "".join(old_texts))
    sep = "" if is_cjk else " "
    asr_tokens = []
    cue_of = []
    for index, text in enumerate(old_texts):
        toks = tokens_for(text)
        if not toks:
            # 空 cue 仍占位，后续用邻近插入
            continue
        for tok in toks:
            asr_tokens.append(tok)
            cue_of.append(index)
    src_tokens = tokens_for(source_text)
    if not src_tokens:
        return old_texts
    if not asr_tokens:
        # 均匀拆到各 cue
        n = len(events)
        out = [[] for _ in range(n)]
        for i, tok in enumerate(src_tokens):
            out[min(n - 1, i * n // max(1, len(src_tokens)))].append(tok)
        return [sep.join(parts) if parts else old_texts[i] for i, parts in enumerate(out)]

    # 2) 词级对齐：把原文 token 填回各 cue
    cue_tokens = [[] for _ in events]
    sm = SequenceMatcher(a=asr_tokens, b=src_tokens, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for offset, k in enumerate(range(i1, i2)):
                cue_tokens[cue_of[k]].append(src_tokens[j1 + offset])
        elif tag == "replace":
            src_slice = src_tokens[j1:j2]
            if i1 >= i2:
                target = cue_of[min(i1, len(cue_of) - 1)] if cue_of else 0
                cue_tokens[target].extend(src_slice)
            elif not src_slice:
                continue
            else:
                # 按 ASR 段覆盖的 cue 权重分配原文片段
                covered = cue_of[i1:i2]
                # 稳定顺序的 cue 列表
                order = []
                for c in covered:
                    if c not in order:
                        order.append(c)
                weights = [covered.count(c) for c in order]
                total = sum(weights) or len(order)
                pos = 0
                for oi, c in enumerate(order):
                    if oi == len(order) - 1:
                        piece = src_slice[pos:]
                    else:
                        take = max(1, round(len(src_slice) * weights[oi] / total))
                        take = min(take, max(0, len(src_slice) - pos - (len(order) - oi - 1)))
                        piece = src_slice[pos:pos + take]
                        pos += take
                    cue_tokens[c].extend(piece)
        elif tag == "delete":
            # 丢掉识别多出来的词，不写入
            continue
        elif tag == "insert":
            # 原文多出来的词：插到最近 cue
            if i1 < len(cue_of):
                target = cue_of[i1]
            elif cue_of:
                target = cue_of[-1]
            else:
                target = 0
            cue_tokens[target].extend(src_tokens[j1:j2])

    # 3) 空 cue 回退：按比例从原文剩余再填，或保留旧文
    used = sum(len(parts) for parts in cue_tokens)
    if used < len(src_tokens) * 0.5:
        # 对齐失败过多 → 按 ASR 词数权重比例切
        weights = [max(1, len(tokens_for(t))) for t in old_texts]
        total_w = sum(weights) or len(weights)
        pos = 0
        out = []
        for i, w in enumerate(weights):
            if i == len(weights) - 1:
                piece = src_tokens[pos:]
            else:
                take = max(1, round(len(src_tokens) * w / total_w))
                remaining_cues = len(weights) - i - 1
                take = min(take, max(0, len(src_tokens) - pos - remaining_cues))
                take = max(0, take)
                piece = src_tokens[pos:pos + take]
                pos += take
            out.append(sep.join(piece) if piece else old_texts[i])
        return out

    result = []
    for i, parts in enumerate(cue_tokens):
        if parts:
            result.append(sep.join(parts))
        else:
            result.append(old_texts[i])
    return result

def proofread_srt_keep_timestamps(srt, source_text, language=None):
    """Replace cue texts with aligned source script; keep all timestamps.

    Returns (new_srt, changes) where changes is
    [{"index", "start", "end", "old", "new"}, ...].
    """
    events = parse_srt(srt, language=language)
    if not events or not str(source_text or "").strip():
        return srt, []
    cleaned = normalize_subtitle_text(str(source_text).strip(), language=language) if language else str(source_text).strip()
    cleaned = normalize_required_capitalization(cleaned)
    new_texts = align_source_text_to_srt_cues(events, cleaned)
    # 粗检：若校对后大量「极短条」且与识别差很远，多半是合成顺序/文案组对不上
    short_new = sum(1 for t in new_texts if 0 < len(re.sub(r"\s+", "", t or "")) <= 3)
    if short_new >= max(5, len(events) // 4):
        # 仍应用结果，但在 changes 里加标记供 UI 提示
        pass
    changes = []
    blocks = []
    for index, ((start, end, old_text), new_text) in enumerate(zip(events, new_texts), 1):
        new_text = normalize_subtitle_text(str(new_text or "").strip(), language=language) if language else str(new_text or "").strip()
        if not new_text:
            new_text = old_text
        if (old_text or "").strip() != (new_text or "").strip():
            changes.append({
                "index": index,
                "start": start,
                "end": end,
                "old": old_text,
                "new": new_text,
            })
        blocks.append(f"{index}\n{_srt_stamp(start)} --> {_srt_stamp(end)}\n{new_text}")
    return "\n\n".join(blocks) + "\n", changes

def html_word_diff(old_text, new_text):
    """HTML snippet: equal plain, changed/new words in red, deleted struck."""
    from difflib import SequenceMatcher
    import html as html_lib

    old_t = tokens_for(old_text or "")
    new_t = tokens_for(new_text or "")
    is_cjk = _is_cjk_heavy((old_text or "") + (new_text or ""))
    sep = "" if is_cjk else " "
    if not old_t and not new_t:
        return ""
    if old_t == new_t:
        return html_lib.escape(sep.join(new_t))
    sm = SequenceMatcher(a=old_t, b=new_t, autojunk=False)
    parts = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            chunk = sep.join(new_t[j1:j2])
            if chunk:
                parts.append(html_lib.escape(chunk))
        elif tag == "delete":
            chunk = sep.join(old_t[i1:i2])
            if chunk:
                parts.append(
                    f'<span style="color:#f87171;text-decoration:line-through;opacity:.85;">'
                    f"{html_lib.escape(chunk)}</span>"
                )
        elif tag in ("insert", "replace"):
            chunk = sep.join(new_t[j1:j2])
            if chunk:
                parts.append(
                    f'<span style="color:#f87171;font-weight:700;background:rgba(248,113,113,.12);">'
                    f"{html_lib.escape(chunk)}</span>"
                )
            if tag == "replace":
                deleted = sep.join(old_t[i1:i2])
                if deleted and not chunk:
                    parts.append(
                        f'<span style="color:#f87171;text-decoration:line-through;">'
                        f"{html_lib.escape(deleted)}</span>"
                    )
    joiner = "" if is_cjk else " "
    return joiner.join(parts)

def batch_script_paste_assignments(text, rows, mode="order", start=0):
    """Parse Sheets/Excel TSV, including quoted multiline cells, atomically."""
    import csv
    import io
    records = list(csv.reader(io.StringIO(text), delimiter="\t", strict=True))
    while records and not any(cell.strip() for cell in records[-1]):
        records.pop()
    if records and tuple(cell.strip().lower() for cell in records[0]) in (
        ("文案",), ("正文",), ("视频", "文案"), ("文件名", "文案"),
    ):
        records.pop(0)
    if not records:
        raise ValueError("剪贴板没有文案。")
    assignments = []
    used = set()
    for offset, record in enumerate(records):
        if not record and mode == "order":
            record = [""]
        expected = 1 if mode == "order" else 2
        if len(record) != expected:
            raise ValueError(f"第 {offset + 1} 行需要 {expected} 列。请选择正确的粘贴方式；单元格内换行须保留表格复制格式。")
        if mode == "order":
            index = start + offset
            if index >= len(rows):
                raise ValueError("粘贴行数超过剩余视频数，未导入任何文案。")
        else:
            name = record[0].strip().casefold()
            matches = [i for i, row in enumerate(rows) if Path(row["path"]).name.casefold() == name]
            if len(matches) != 1:
                raise ValueError(f"第 {offset + 1} 行文件名未找到或有重名：{record[0]}。请包含扩展名。")
            index = matches[0]
        if index in used:
            raise ValueError("同一个视频出现多次，未导入任何文案。")
        used.add(index)
        if record[-1].strip():
            assignments.append((index, record[-1].strip()))
    if not assignments:
        raise ValueError("文案均为空。空单元格保留原值，不会清空文案。")
    return assignments
