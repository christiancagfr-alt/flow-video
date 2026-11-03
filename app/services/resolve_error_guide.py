"""Human-readable Chinese translation, root-cause analysis, and recovery guide for DaVinci Resolve auto-editing errors.

Design invariants:
- Never mutate machine-readable `.ini` state files (`finish.ini`, `state.ini`, `bridge_state.ini`) or
  `resolve_daily.connection_status_text()` return contracts expected by unit tests.
- Translate every Lua / Bridge / Whisper / Cloud ASR / OS / Python error surfaced in the UI into natural Chinese,
  enriching raw IDs (`video=19`, `frame=100447`) with real recipient/host/video names and timeline timecodes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
import time
from typing import Callable

from app.core import database

_LUA_TRACE_RE = re.compile(r'(?:\.\.\.|[A-Za-z]:[/\\]|/)[^\s:]*\.lua:\d+:\s*')
_PY_TRACE_RE = re.compile(r'File "[^"]+", line \d+, in [^\n]+')
_CODE_TOKEN_RE = re.compile(r'\b([A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+)\b')
_ASCII_HEAVY_RE = re.compile(r'[A-Za-z_]{4,}')

# Benign status phrases that are NOT errors even if they appear in status labels
_BENIGN_PREFIXES = (
    '✓', '✅', '⟳', '🔵', '🟢', '🟡', '○',
    '等待任务', '等待可剪辑素材', 'DaVinci：等待任务', 'DaVinci：自动剪辑阶段',
    'DaVinci：正在启动', 'DaVinci：正在建立', 'DaVinci：正在启动“', 'DaVinci：✅',
    'DaVinci：已发送', 'DaVinci：已标记',
    '正在唤醒', '正在检查', '正在核对', '正在重新识别', '正在重新读取',
    '正在剪辑', '正在达芬奇中渲染', '正在后台并行识别', '正在并行识别',
    '正在提交', '正在按最新主播绑定', '正在重新导出',
    '达芬奇已就绪', 'Bridge 在线', '已导入', '已完成', '已重建时间线',
    '已挂载', '已刷新当前时间线', '全部可剪辑视频均已完成导出',
    '请点击上方', '质检通过并素材齐全后', '当前选中时间线为',
    '点击任意一行勾选', '用户手动确认结束', '用户手动跳过',
    '对应时间线已重建',
)

_NON_ERROR_CODES = frozenset({
    'IMPORT_BATCH', 'START_AUTOEDIT', 'FINISH_BATCH', 'PREPARE_DAILY',
    'IMPORT_SCRIPTURES', 'WAITING_USER_REVIEW', 'AUTOEDIT_QUEUED',
    'AUDIO_RENDERING', 'WHISPER_RUNNING', 'TEXT_ALIGNING', 'PREPARING_EXPORT',
    'CLEANED_READY', 'PROJECT_REBUILT', 'READY_TO_EDIT', 'WAITING_MATERIAL',
    'BRIDGE_STARTING', 'PREPARING_PROJECT', 'READY', 'IDLE', 'COMPLETED',
    'IMPORTED', 'IMPORTING', 'CUTTING', 'CLEANING', 'RENDERING', 'SKIPPED',
    'VIDEO_COMPLETE', 'WM_PLAN_READY', 'WM_DURATIONS_SYNCED', 'WM_DURATIONS_NOOP',
    'SUBCLIPS_SYNCED', 'SUBCLIPS_NOOP', 'STYLE_UPDATED', 'STYLE_OK', 'REUSED_WAV',
    'VIDEO_SOURCE_MISSING_SKIPPED', 'VIDEO_SOURCE_MISSING_AFTER_CLEANUP_SKIPPED',
    'RECOVERY_VIDEO_SOURCE_MISSING_SKIPPED', 'SPEECH_PROTECTED_AUDIO_AND_TEXT',
})

_ACTIVE_RUNNING_STAGES = frozenset({
    'IMPORTING', 'AUTOEDIT_QUEUED', 'AUDIO_RENDERING', 'WHISPER_RUNNING',
    'TEXT_ALIGNING', 'CUTTING', 'CLEANING', 'PREPARING_EXPORT', 'RENDERING',
    'BRIDGE_STARTING', 'PREPARING_PROJECT', 'LAUNCHING',
})

_ERROR_BATCH_STATUSES = frozenset({
    'IMPORT_ERROR', 'ANALYSIS_ERROR', 'CUTTING_ERROR', 'CLEANING_ERROR', 'EXPORT_ERROR', 'ERROR',
})

_VIDEO_CACHE: dict[int, tuple[float, str, str]] = {}
_FPS_CACHE: tuple[float, int] = (0.0, 25)


@dataclass(frozen=True)
class EditingErrorInfo:
    code: str
    stage_label: str
    title: str
    inline_text: str
    cause: str
    location_items: list[tuple[str, str]] = field(default_factory=list)
    solutions: list[str] = field(default_factory=list)
    raw_error: str = ''


def strip_lua_prefixes(raw: str) -> str:
    text = str(raw or '').strip()
    prev = None
    while text != prev:
        prev = text
        text = _LUA_TRACE_RE.sub('', text).strip()
    return re.sub(r'\s+', ' ', text).strip()


def _current_fps() -> int:
    global _FPS_CACHE
    now = time.monotonic()
    if now - _FPS_CACHE[0] < 15.0:
        return _FPS_CACHE[1]
    fps = 25
    try:
        with database.connect() as con:
            row = con.execute("SELECT value FROM app_settings WHERE key='timeline_fps'").fetchone()
        if row and str(row['value'] or '').strip().isdigit():
            val = int(str(row['value']).strip())
            if 10 <= val <= 120:
                fps = val
    except Exception:
        fps = 25
    _FPS_CACHE = (now, fps)
    return fps


def frame_to_timecode(frame: int, fps: int | None = None) -> str:
    f_rate = max(1, int(fps or _current_fps()))
    total_f = max(0, int(frame))
    ff = total_f % f_rate
    total_sec = total_f // f_rate
    ss = total_sec % 60
    mm = (total_sec // 60) % 60
    hh = total_sec // 3600
    return f'{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}'


def lookup_video_names(video_id: int) -> tuple[str, str]:
    """Return ``(short_label, detailed_label)`` for ``video_id`` in Chinese."""
    vid = int(video_id)
    now = time.monotonic()
    cached = _VIDEO_CACHE.get(vid)
    if cached and now - cached[0] < 20.0:
        return cached[1], cached[2]

    short_lbl = f'视频（编号 {vid}）'
    full_lbl = f'视频（内部编号 {vid}）'
    try:
        with database.connect() as con:
            row = con.execute(
                """SELECT v.seq, COALESCE(h.name, '') AS host_name, COALESCE(r.name, '') AS recipient_name
                   FROM videos v
                   LEFT JOIN hosts h ON h.id = v.host_id
                   LEFT JOIN recipients r ON r.id = h.recipient_id
                   WHERE v.id = ?""",
                (vid,),
            ).fetchone()
        if row:
            seq = int(row['seq'] or 0)
            host = str(row['host_name'] or '').strip()
            rec = str(row['recipient_name'] or '').strip()
            seq_part = f'视频 #{seq:02d}' if seq > 0 else f'视频 #{vid}'
            if rec and host:
                short_lbl = f'「{rec} / {host} · {seq_part}」'
                full_lbl = f'{rec} / {host} · {seq_part}（内部编号 {vid}）'
            elif host:
                short_lbl = f'「{host} · {seq_part}」'
                full_lbl = f'{host} · {seq_part}（内部编号 {vid}）'
            else:
                short_lbl = f'「{seq_part}」'
                full_lbl = f'{seq_part}（内部编号 {vid}）'
    except Exception:
        pass
    _VIDEO_CACHE[vid] = (now, short_lbl, full_lbl)
    return short_lbl, full_lbl


def _extract_context(clean_text: str) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """Extract video_id, frame, timecode range, counts, and file path from raw error text."""
    ctx: dict[str, str] = {}
    locs: list[tuple[str, str]] = []

    m_vid = re.search(r'(?:video(?:_id)?\s*=\s*|视频\s*)(\d+)', clean_text, flags=re.IGNORECASE)
    if m_vid:
        vid = int(m_vid.group(1))
        short_v, full_v = lookup_video_names(vid)
        ctx['video_id'] = str(vid)
        ctx['video_short'] = short_v
        ctx['video_full'] = full_v
        locs.append(('涉及视频', full_v))

    m_frame = re.search(r'(?:timeline_frame|原frame|frame)\s*=\s*(\d+)', clean_text, flags=re.IGNORECASE)
    if m_frame:
        fr = int(m_frame.group(1))
        tc = frame_to_timecode(fr)
        ctx['frame'] = str(fr)
        ctx['timecode'] = tc
        locs.append(('时间线位置', f'{tc}（帧号 {fr}）'))

    m_range = re.search(r'(\d{2}:\d{2}:\d{2}:\d{2}\s*-\s*\d{2}:\d{2}:\d{2}:\d{2})', clean_text)
    if m_range:
        rng = m_range.group(1).strip()
        ctx['tc_range'] = rng
        locs.append(('时间线区间', rng))
    else:
        m_pos = re.search(r'位置\s*=\s*(\d{2}:\d{2}:\d{2}:\d{2})', clean_text)
        if m_pos and 'timecode' not in ctx:
            ctx['timecode'] = m_pos.group(1)
            locs.append(('时间线位置', m_pos.group(1)))

    m_trk = re.search(r'\btrack\s*=\s*([A-Za-z0-9_]+)', clean_text, flags=re.IGNORECASE)
    if m_trk:
        trk = m_trk.group(1)
        ctx['track'] = trk
        locs.append(('所在轨道', f'轨道 {trk}'))

    m_path = re.search(r'((?:/Users/|/Volumes/|/Applications/|/tmp/|[A-Za-z]:[/\\])[^\s；;，,]+)', clean_text)
    if m_path:
        p_str = m_path.group(1).rstrip(')）\'"')
        ctx['path'] = p_str
        locs.append(('涉及文件', p_str))

    return ctx, locs


def _extract_primary_code(clean_text: str) -> str:
    for m in _CODE_TOKEN_RE.finditer(clean_text):
        tok = m.group(1)
        if tok not in _NON_ERROR_CODES:
            return tok
    return ''


def is_editing_error(raw_text: str, batch_status: str = '', stage: str = '') -> bool:
    """Return True if ``raw_text`` (given optional batch/bridge stage) represents an error/warning."""
    text = str(raw_text or '').strip()
    if not text:
        return False

    b_stat = str(batch_status or '').strip().upper()
    s_stat = str(stage or '').strip().upper()

    # Explicit non-error status prefixes
    if text.startswith(('✓', '✅', '⟳', '🔵', '🟢', '🟡', '○')):
        return False
    for bp in _BENIGN_PREFIXES:
        if text.startswith(bp):
            return False

    # Re-export summary without failures is benign ("重新导出完成：成功 3 个")
    if text.startswith('重新导出完成：') and '失败' not in text:
        return False

    # Normal completion / progress lines that contain words like "失败已跳过 0 个" or "中断后不会重复删除"
    if ('识别失败已跳过 0 个' in text) and b_stat not in _ERROR_BATCH_STATUSES:
        return False
    if text.startswith(('仅清理 V1 主轨', '开始后台极速子片段切分', '可识别视频开始切刀', '检测到上次中断缺口，正在自动恢复', '批量渲染完成', '所有视频已导出', '本批次导出已结束', '已完成清理', '已启动一键纠偏', '已重新识别', '已开始分析', '已提交')):
        return False
    if (b_stat in _ACTIVE_RUNNING_STAGES or s_stat in _ACTIVE_RUNNING_STAGES) and b_stat not in _ERROR_BATCH_STATUSES and s_stat not in _ERROR_BATCH_STATUSES and not text.startswith(('⚠', 'DaVinci：⚠')):
        return False

    if b_stat in _ERROR_BATCH_STATUSES or s_stat in _ERROR_BATCH_STATUSES:
        return True

    if text.startswith(('⚠', 'DaVinci：⚠', '错误', '失败')):
        return True

    clean = strip_lua_prefixes(text)
    code = _extract_primary_code(clean)
    if code:
        return True

    low = clean.lower()
    if any(k in low for k in (
        'attempt to call', 'attempt to index', 'attempt to concatenate', 'attempt to perform',
        'traceback', 'exception', 'errno', 'permission denied', 'no such file',
        'timed out', 'timeout', 'connection refused', 'ssl:', 'http ', 'sqlite',
        'err:', '-1719', '-1743', 'not authorized', 'not allowed', 'cancelled', 'failed',
    )):
        return True

    if any(k in clean for k in (
        '失败', '异常', '超时', '未连接', '连接中断', '未找到', '找不到', '缺失', '不存在',
        '不匹配', '冲突', '损坏', '中断', '拒绝', '无权限', '辅助功能', '无法', '不能',
        '尚未开启', '没有配置', '未配置', '正在运行', '尚未结束', '请先停止', '未确认',
    )):
        return True

    return False


# ---------------------------------------------------------------------------
# Comprehensive Error Catalog (grouped by workflow stage)
# ---------------------------------------------------------------------------

def _build_specific_info(
    code: str,
    clean: str,
    raw: str,
    ctx: dict[str, str],
    locs: list[tuple[str, str]],
) -> EditingErrorInfo | None:
    vid_s = ctx.get('video_short', '当前视频')
    tc_s = f"（约 {ctx['timecode']}）" if ctx.get('timecode') else ''

    # ── Category A: Cleanup / Watermark / Export (`FlowStudio_Finish_Batch.lua` & `resolve_finish.py`) ──
    if code == 'EXPORT_RANGE_FOREIGN_CLIP':
        return EditingErrorInfo(
            code=code,
            stage_label='④ 清理与导出阶段',
            title=f'{vid_s} 的时间线区间内混入了其他视频片段',
            inline_text=f'⚠ 导出暂停：{vid_s} 在 V1 主轨的区间内混入了其他视频或贴片片段',
            cause=(
                f'程序在扫描达芬奇 V1 主视频轨时发现，{vid_s} 的首个片段与最后一个片段之间，'
                '夹杂了不属于该视频的其他片段（常见原因：手动拖动剪辑时把相邻视频拖进了它中间，'
                '或把图片 / 水印 / B-Roll 误放到了 V1 主轨而不是 V2 及以上叠加轨）。'
                '为防止导出的成片串片，系统已自动暂停并完整保留时间线现场。'
            ),
            location_items=locs,
            solutions=[
                f'切到达芬奇「剪辑（Edit）」页面，在 V1 主视频轨找到 {vid_s} 所在的片段组；',
                '检查该视频开头与结尾之间是否夹入了其他视频片段，或误放在 V1 轨的图片/水印（叠加素材请上移到 V2 / V3 轨道，保持 V1 只放主视频）；',
                '如果该视频的某个小片段被误拖到了其他视频后面，请拖回原位或删除多余碎片段，确保同一条视频的片段在 V1 轨上连续排列；',
                '整理好后无需重新导入，直接回到本页面再次点击「确认清理」或「批量导出」即可继续。',
            ],
            raw_error=raw,
        )

    if code == 'VIDEO_OVERLAP':
        return EditingErrorInfo(
            code=code,
            stage_label='④ 清理与导出阶段',
            title='时间线上不同完整视频的区间发生交叉重叠',
            inline_text='⚠ 清理暂停：V1 主轨上两条不同视频的片段顺序交叉重叠，请整理后重试',
            cause='V1 主视频轨上两条不同完整视频的片段相互穿插（例如视频 A 的片段插到了视频 B 中间），系统无法安全划分每条视频的独立导出首尾范围。',
            location_items=locs,
            solutions=[
                '在达芬奇「剪辑（Edit）」页面检查 V1 主轨，确保每条完整视频的片段各自连续成组、不与相邻视频穿插；',
                '将误拖乱位置的片段移回对应视频位置或删除多余碎片段；',
                '确认无误后回到本页面点击「确认清理」或「批量导出」重试。',
            ],
            raw_error=raw,
        )

    if code in ('RECOVERY_NON_V1_VIDEO_FOUND',):
        return EditingErrorInfo(
            code=code,
            stage_label='④ 清理与导出阶段',
            title=f'{vid_s} 的主视频片段被移到了非 V1 轨道',
            inline_text=f'⚠ 清理暂停：{vid_s}{tc_s} 的主视频片段不在 V1 主轨上',
            cause='本批次的主播视频片段必须保留在 V1 主视频轨上（V2 及以上轨道专门用于放置 AI 水印与叠加贴片），检测到主视频片段被拖到了上层视频轨。',
            location_items=locs,
            solutions=[
                f'在达芬奇时间线{tc_s}找到被移到 V2/V3 的主视频片段，将其拖回 V1 主视频轨；',
                '确保 V2 及以上轨道只放水印或叠加图片，然后点击「确认清理」或「批量导出」重试。',
            ],
            raw_error=raw,
        )

    if code == 'RECOVERY_V1_GAP_OR_OVERLAP':
        return EditingErrorInfo(
            code=code,
            stage_label='④ 清理与导出阶段',
            title=f'{vid_s} 在 V1 轨道上存在黑场空隙或片段重叠',
            inline_text=f'⚠ 清理暂停：{vid_s}{tc_s} 片段之间存在未闭合空隙或重叠',
            cause='手动删除或移动片段时使用了普通删除（Backspace）而非波纹删除，导致同一条视频的片段之间留下了黑屏空隙，或前后片段发生了帧重叠。',
            location_items=locs,
            solutions=[
                f'在达芬奇时间线跳转到 {ctx.get("timecode", "报错位置")}，点击片段之间的空白间隙按 Delete（波纹删除）闭合黑场；',
                '检查前后片段紧贴无空隙后，回到 Flow Studio 点击「确认清理」或「批量导出」继续。',
            ],
            raw_error=raw,
        )

    if code == 'BATCH_RENDER_INCOMPLETE':
        cancelled_n = len(re.findall(r'\bCancelled\b', clean))
        failed_n = len(re.findall(r'\bFailed\b', clean))
        m_unconf = re.search(r'(\d+)\s*个未确认', clean)
        unconf_n = int(m_unconf.group(1)) if m_unconf else (cancelled_n + failed_n)
        parts = []
        if failed_n:
            parts.append(f'失败 {failed_n} 条')
        if cancelled_n:
            parts.append(f'手动取消 {cancelled_n} 条')
        if not parts and unconf_n:
            parts.append(f'未完成 {unconf_n} 条')
        stat_desc = '，'.join(parts) if parts else '部分视频未完成渲染'
        return EditingErrorInfo(
            code=code,
            stage_label='④ 批量渲染导出',
            title=f'批量导出未全部完成（{stat_desc}）',
            inline_text=f'⚠ 批量导出中断（{stat_desc}）；已导出的成品已安全保存，可直接点「重试批量导出」',
            cause=(
                f'达芬奇交付页在渲染过程中有 {unconf_n or "部分"} 条视频被取消或渲染失败'
                '（例如在达芬奇交付页点击了停止渲染、磁盘剩余空间不足、或单个片段解码失败）。'
                '已成功渲染的视频已自动登记保存，不会重复渲染。'
            ),
            location_items=locs,
            solutions=[
                '直接点击上方绿色的「重试批量导出」按钮，系统会自动跳过已成功导出的视频，只补导剩余未完成的部分；',
                '若多次渲染失败，请检查导出磁盘剩余空间是否充足，并切换到「交付（Deliver）」页面查看具体哪一条任务报错；',
                '渲染进行期间请尽量不要在达芬奇内切换项目或点击停止。',
            ],
            raw_error=raw,
        )

    if code == 'FINISH_CANCELLED':
        return EditingErrorInfo(
            code=code,
            stage_label='④ 清理与导出阶段',
            title='已取消本次清理或导出操作',
            inline_text='⚠ 操作已取消：未改动时间线，也未启动导出',
            cause='在达芬奇确认弹窗中点击了取消，本次未删除任何片段、也未启动渲染。',
            location_items=locs,
            solutions=[
                '如需继续，请直接在上方操作栏重新点击「确认清理」或「批量导出」。',
            ],
            raw_error=raw,
        )

    if code == 'REVIEW_REQUIRED':
        return EditingErrorInfo(
            code=code,
            stage_label='④ 清理与导出阶段',
            title='当前批次尚未完成自动剪辑识别，暂不能直接清理',
            inline_text='⚠ 尚未完成识别切刀：请先执行「③ 开始自动剪辑」进入待检查状态后再点确认清理',
            cause='当前批次还没有生成有效的自动切刀计划（或状态不在「等待人工检查」），因此无法执行红标废片清理。',
            location_items=locs,
            solutions=[
                '请先点击上方「③ 开始自动剪辑」，等待语音识别与自动切刀标红完成；',
                '检查时间线红标无误后，再点击「④ 确认清理」与「批量导出」。',
            ],
            raw_error=raw,
        )

    if code in ('VIDEO_MARKER_MISSING', 'COMPLETE_MARKER_FAILED'):
        return EditingErrorInfo(
            code=code,
            stage_label='④ 清理与导出阶段',
            title=f'{vid_s} 缺少完整视频分界标记',
            inline_text=f'⚠ 标记缺失：{vid_s}{tc_s} 在时间线上缺少分界标记，请检查是否被误删',
            cause='清理或导出校验时未找到该完整视频对应的分界 Marker（可能在手动修剪时间线时不小心把时间线标记一并删除了）。',
            location_items=locs,
            solutions=[
                '如果当前时间线还未手动大改，可点击「↻ 重新识别」让程序重新分析并补齐标记；',
                '如果已在达芬奇内手动剪好导出，可点击「⋯ → ✓ 手动标记本批已完成」结束批次；',
                '如需重头再来，可点击「➕ 剪辑下一批」新建干净时间线重新导入。',
            ],
            raw_error=raw,
        )

    if code in ('AMBIGUOUS_BLUE_MARKER', 'BLUE_MARKER_FRAME_INVALID', 'EXTRA_BLUE_DELETE_FAILED'):
        return EditingErrorInfo(
            code=code,
            stage_label='④ 清理人工蓝标',
            title='人工蓝色删除标记位置不明确，已停止误删',
            inline_text='⚠ 蓝标位置异常：人工添加的蓝色标记没有对准单个要删除的小片段开头',
            cause='蓝色标记用于指定“需要额外删除的单个碎片段”。当蓝标打在空白处、跨多个片段或不在 V1 片段上时，系统为防止误删正片会自动停下。',
            location_items=locs,
            solutions=[
                '在达芬奇时间线上检查自己手动打的蓝色标记（Blue Marker），确保每个蓝标精准打在需要删除的那一小段 V1 片段内部或开头；',
                '删掉打偏的多余蓝标（或直接在达芬奇里手动波纹删除该碎片段），然后再次点击「确认清理」。',
            ],
            raw_error=raw,
        )

    if code in ('DELETE_FAILED', 'DELETE_NOT_CONFIRMED', 'UNEXPECTED_CLIP_REMOVED', 'RIPPLE_RANGE_MISMATCH', 'CLEANUP_INTERRUPTED', 'CLEANUP_RECOVERY_INTENT_MISSING'):
        return EditingErrorInfo(
            code=code,
            stage_label='④ 清理时间线废片',
            title='清理红标/蓝标废片时达芬奇未能确认波纹删除结果',
            inline_text='⚠ 清理废片中断：达芬奇未能完成波纹删除（可能有轨道被锁定或音画未对齐），现场已保留',
            cause='执行波纹删除（Ripple Delete）时，达芬奇拒绝了删除或删除后的片段数量与预期不符，常见于轨道加锁、A1 音频与 V1 视频未对齐、或存在跨切点的长音频。',
            location_items=locs,
            solutions=[
                '检查达芬奇时间线左侧轨道头，确认 V1 视频轨和 A1 音频轨均未锁定（锁头图标未点亮）；',
                '查看是否有背景音乐或外部音频放在了 A1 轨（外部音乐请移到 A2/A3 轨，保持 A1 仅放原视频同步人声）；',
                '确认时间线正常后，点击上方「继续清理」重试；若已手动删好废片，也可直接点「批量导出」。',
            ],
            raw_error=raw,
        )

    if code in ('UPPER_VIDEO_TRACK_PROTECT_FAILED', 'UPPER_VIDEO_TRACK_RESTORE_FAILED'):
        return EditingErrorInfo(
            code=code,
            stage_label='④ 清理与轨道保护',
            title='保护或恢复上层视频轨（V2+）锁定状态失败',
            inline_text='⚠ 轨道状态异常：清理时无法自动锁定或恢复 V2 及以上叠加轨道',
            cause='清理 V1 主轨废片前，程序会自动临时锁定 V2+ 轨道防止波纹错位，但达芬奇未允许修改上层轨道锁状态。',
            location_items=locs,
            solutions=[
                '确保达芬奇处于「剪辑（Edit）」页面且未处于播放或弹窗状态；',
                '手动检查 V2 及以上轨道状态后，点击「继续清理」重试。',
            ],
            raw_error=raw,
        )

    if code in (
        'ADD_WATERMARK_VIDEO_TRACK_FAILED', 'WM_MEDIA_POOL_UNAVAILABLE', 'WM_MEDIA_ROOT_UNAVAILABLE',
        'WM_SET_ROOT_FAILED', 'WM_CREATE_BIN_FAILED', 'WM_SET_BIN_FAILED', 'WATERMARK_PNG_MISSING',
        'WATERMARK_IMPORT_FAILED', 'WATERMARK_IMPORT_EMPTY', 'WATERMARK_APPEND_FAILED',
        'WATERMARK_CLIP_NOT_RETURNED', 'WATERMARK_OLD_DELETE_FAILED',
        'SAVE_WATERMARK_PRE_SYNC_FAILED', 'RELOAD_WATERMARK_PROJECT_FAILED',
        'RELOAD_WATERMARK_TIMELINE_MISSING', 'SAVE_WATERMARK_PROJECT_FAILED',
    ):
        return EditingErrorInfo(
            code=code,
            stage_label='④ AI 水印挂载',
            title='自动挂载或刷新 AI 水印时遇到问题',
            inline_text='⚠ 水印挂载异常：未能将 AI 水印图片写入达芬奇轨道或同步时长',
            cause='生成的水印 PNG 文件缺失、达芬奇媒体池被占用、或上层水印轨道被手动加锁导致无法放置/替换水印片段。',
            location_items=locs,
            solutions=[
                '检查达芬奇 V2 / V3 水印轨道是否被手动上了锁（如有加锁请先解锁）；',
                '点击顶部「💧 AI水印」打开设置，确认主水印样式与主播绑定正常并点击保存；',
                '随后直接点击操作栏的「💧 刷新水印」即可重新生成并挂载全段水印。',
            ],
            raw_error=raw,
        )

    if code in ('OUTPUT_ALREADY_EXISTS', 'FAILED_BACKUP_EXISTS', 'PRESERVE_FAILED_OUTPUT_FAILED', 'COMPLETED_OUTPUT_MISSING'):
        return EditingErrorInfo(
            code=code,
            stage_label='④ 批量渲染导出',
            title='导出目标文件冲突或成品文件校验未通过',
            inline_text='⚠ 导出文件冲突：目标文件夹已存在同名未确认文件，或渲染后未生成有效 MP4',
            cause='导出目录中已有同名半成品/备份文件且为安全起见不允许静默覆盖，或渲染完成后目标路径下找不到大于 0 字节的 MP4 文件。',
            location_items=locs,
            solutions=[
                '检查导出目录（可点队列右上角「📂 导出目录」）是否存在 0KB 损坏文件或残留 `.bak` 文件，如有可移走或删除；',
                '确认磁盘空间充足、文件夹有写入权限；',
                '如需全部覆盖重导，可点击操作栏右侧「⋯ → ⚠️ 删除旧成品并重新导出全部」。',
            ],
            raw_error=raw,
        )

    if code in (
        'MP4_H264_UNAVAILABLE', 'EXPORT_SETTINGS_FAILED', 'SINGLE_CLIP_MODE_FAILED',
        'RENDER_SINGLE_CLIP_MODE_FAILED', 'SUBTITLE_BURNIN_SETTINGS_FAILED',
        'ADD_RENDER_FAILED', 'START_RENDER_FAILED', 'RENDER_TIMEOUT',
    ):
        return EditingErrorInfo(
            code=code,
            stage_label='④ 批量渲染导出',
            title='达芬奇渲染参数设置或启动导出任务失败',
            inline_text='⚠ 启动导出失败：达芬奇未能添加 MP4 (H.264) 渲染任务或渲染超时',
            cause='达芬奇当前处于弹窗阻塞状态、导出路径所在的移动硬盘/网络盘未挂载、分辨率超出了免费版限制，或单条渲染耗时超过安全上限。',
            location_items=locs,
            solutions=[
                '在「系统设置」中检查「剪辑路径根目录」所在的磁盘是否已连接且可正常写入；',
                '切到达芬奇「交付（Deliver）」页面，关闭任何阻塞弹窗，清理渲染队列中卡死的旧任务；',
                '点击「唤醒达芬奇」刷新状态后，再点击「重试批量导出」。',
            ],
            raw_error=raw,
        )

    if code in ('EMPTY_OR_INCOMPLETE_VIDEO', 'RECOVERY_VIDEO_EMPTY', 'RECOVERY_VIDEO_SOURCE_MISSING'):
        return EditingErrorInfo(
            code=code,
            stage_label='④ 清理与导出阶段',
            title=f'{vid_s} 在时间线上已无有效保留片段',
            inline_text=f'⚠ 片段缺失：{vid_s} 的片段在时间线上已被全部删空或离线缺失',
            cause='该视频的所有片段都被标红/标蓝删除了，或者对应的原始 MP4 素材文件已被移动/删除导致媒体离线。',
            location_items=locs,
            solutions=[
                '切到达芬奇时间线查看该视频是否被误删光（若是刚刚误删，可在达芬奇内按 Cmd+Z 撤销）；',
                '检查媒体池中是否有红色的「Media Offline（媒体离线）」片段；',
                '若确认不需要导出该条视频，可在队列右键「🚫 放弃该视频任务」或点「⋯ → 手动标记本批已完成」。',
            ],
            raw_error=raw,
        )

    # ── Category B: Cutting / Markers / Subclip Sync (`Autoediting_V1.7_FlowStudio.lua`) ──
    if code in ('CUT_NOT_CONFIRMED', 'AUDIO_CUT_NOT_CONFIRMED', 'AUDIO_CUT_MISMATCH', 'CUT_CROSSING_REMAINED', 'BLADE_COMMAND_FAILED'):
        return EditingErrorInfo(
            code=code,
            stage_label='③ 自动切刀阶段',
            title=f'达芬奇未响应切刀指令{tc_s}，已保护现场暂停',
            inline_text=f'⚠ 自动切刀暂停：在 {ctx.get("timecode", "当前帧")} 处切刀未生效（达芬奇窗口可能失去焦点或快捷键冲突）',
            cause=(
                '自动切刀需要将时间线播放头定位到目标帧并触发达芬奇分割片段快捷键（Cmd+B / Ctrl+B）。'
                '如果切刀瞬间你点击了其他软件窗口、达芬奇弹出了提示框、轨道被锁定，或达芬奇内修改了默认分割快捷键，'
                '素材个数不会增加，系统会立即停下避免乱切。'
            ),
            location_items=locs,
            solutions=[
                '先确保达芬奇处于「剪辑（Edit）」页面、V1 与 A1 轨道未加锁，且没有打开任何设置弹窗；',
                '点击上方蓝色的「继续未完成切刀」按钮，并在切刀运行的几秒钟内保持达芬奇窗口在最前台，暂时不要操作鼠标键盘；',
                '若反复在同一位置停下，请检查达芬奇顶部菜单「DaVinci Resolve → 键盘自定义」中「分割片段（Split Clip）」是否仍绑定默认的 Cmd+B（Windows 为 Ctrl+B）。',
            ],
            raw_error=raw,
        )

    if code in ('PLAYHEAD_NOT_READY', 'OPEN_EDIT_PAGE_FAILED', 'EDIT_PAGE_NOT_READY', 'EDIT_PAGE_CHANGED', 'TIMELINE_FOCUS_FAILED', 'TIMELINE_REFOCUS_FAILED', 'PIPE_INIT_FAILED', 'PIPE_LOST'):
        return EditingErrorInfo(
            code=code,
            stage_label='③ 自动切刀阶段',
            title='无法切入达芬奇「剪辑」页面或聚焦时间线',
            inline_text='⚠ 切刀准备暂停：达芬奇未能打开「剪辑」页面或时间线未获得焦点',
            cause='自动切刀必须在达芬奇的「剪辑（Edit）」页面且时间线面板处于激活状态才能精准下刀，当前页面被切换或辅助控制通道被拦截。',
            location_items=locs,
            solutions=[
                '手动在达芬奇底部导航栏点击切换到「剪辑（Edit）」页面，并在时间线空白处点一下鼠标激活时间线；',
                '回到 Flow Studio 点击「继续未完成切刀」或「开始自动剪辑」，执行期间不要切换达芬奇页面。',
            ],
            raw_error=raw,
        )

    if code in ('TRACK_LOCKED', 'TRACK_READ_FAILED', 'V1_VIDEO_TRACK_MISSING', 'UNRELATED_AUDIO_OVERLAP'):
        return EditingErrorInfo(
            code=code,
            stage_label='③ 轨道安全检查',
            title='时间线主轨道被锁定或存在干扰片段',
            inline_text='⚠ 轨道检查未通过：V1/A1 轨道被加锁，或 A1 轨混入了非同步音频',
            cause='V1 视频轨或 A1 音频轨处于锁定状态，或者 A1 轨道上放置了跨视频的背景音乐/音效，继续切刀会切坏无关音频。',
            location_items=locs,
            solutions=[
                '在达芬奇时间线左侧解锁 V1 和 A1 轨道；',
                '若添加了背景音乐或音效，请将其移到 A2 / A3 轨道，确保 A1 轨道只保留与 V1 视频一一对应的原声；',
                '处理后点击「继续未完成切刀」或「开始自动剪辑」。',
            ],
            raw_error=raw,
        )

    if code in (
        'SUBCLIP_DB_SYNC_FAILED', 'CLOSE_BEFORE_SUBCLIP_SYNC_FAILED', 'SWITCH_BEFORE_SUBCLIP_SYNC_FAILED',
        'SAVE_BEFORE_SUBCLIP_SYNC_FAILED', 'RELOAD_AFTER_SUBCLIP_SYNC_FAILED', 'RELOAD_SUBCLIP_TIMELINE_MISSING',
        'SUBCLIP_APPEND_GROUP_FAILED', 'SUBCLIP_APPEND_SINGLE_FAILED', 'SUBCLIP_NEW_VIDEO_COUNT_MISMATCH',
        'SUBCLIP_NEW_AUDIO_COUNT_MISMATCH', 'SUBCLIP_TRANSFORM_SET_FAILED',
    ):
        return EditingErrorInfo(
            code=code,
            stage_label='③ 高速切刀同步',
            title='高速子片段同步或重新挂载时间线时失败',
            inline_text='⚠ 切刀同步中断：写入切点并刷新达芬奇项目时未成功确认，请重新唤醒后重试',
            cause='高速切刀在后台保存项目并同步子片段切点时，达芬奇项目未能正常关闭或重新加载（例如项目有未保存弹窗、或媒体池存在特殊离线片段）。',
            location_items=locs,
            solutions=[
                '先切到达芬奇看是否有「保存更改」等提示弹窗，如有请先确认关闭；',
                '回到本页面先点一次「① 唤醒达芬奇」重新对齐今日项目与当前时间线；',
                '随后点击「重试整批分析」或「↻ 重新识别」即可恢复。',
            ],
            raw_error=raw,
        )

    if code in (
        'CLIP_RANGE_CHANGED', 'VIDEO_RANGE_INCOMPLETE', 'BATCH_RANGE_MISMATCH', 'BATCH_SCOPE_INCOMPLETE',
        'AMBIGUOUS_VIDEO_RANGE', 'INVALID_VIDEO_RANGE', 'EXPECTED_VIDEO_COUNT_MISMATCH',
        'RESUME_BATCH_SCOPE_CHANGED', 'RESUME_IMPORT_RANGE_CHANGED', 'RESUME_IMPORT_LOG_MISSING',
        'RESUME_IMPORT_LOG_AMBIGUOUS', 'RESUME_PLAN_MISSING', 'RESUME_PLAN_ID_MISMATCH',
        'RESUME_PLAN_VIDEO_MISMATCH', 'RESUME_PLAN_RANGE_INVALID', 'RESUME_SOURCE_CHANGED',
        'RESUME_SOURCE_ID_MISSING', 'RESUME_SOURCE_OFFSET_CHANGED', 'CUT_CLIP_MEDIAPOOL_MISSING',
    ):
        return EditingErrorInfo(
            code=code,
            stage_label='③ 时间线范围校验',
            title='时间线上的片段已被改动，与导入时的记录不一致',
            inline_text='⚠ 时间线已变动：当前时间线片段位置或数量与导入清单不符，无法直接续切旧切点',
            cause='在导入完成之后、自动切刀结束之前，达芬奇时间线上的片段被手动删减、移动或替换了，继续套用旧的时间轴切点会切错位置。',
            location_items=locs,
            solutions=[
                '如果时间线只是轻微改动且仍保留原视频，可尝试点击「↻ 重新识别」（若按钮可用）；',
                '最稳妥的做法：点击操作栏「➕ 剪辑下一批」新建一条干净时间线（或点「⋯ → 跳过当前批次」退回待剪辑），然后重新点击「导入剪辑素材」→「开始自动剪辑」。',
            ],
            raw_error=raw,
        )

    if code in (
        'CANDIDATE_MARKER_FAILED', 'CANDIDATE_MARKER_RANGE_INVALID', 'CANDIDATE_MARKER_UPDATE_FAILED',
        'CANDIDATE_RANGE_NOT_CONFIRMED', 'CANDIDATE_CLIP_MISSING', 'CANDIDATE_IDENTITY_MISSING',
        'CANDIDATE_IDENTITY_MISMATCH', 'CANDIDATE_VIDEO_MISMATCH', 'DUPLICATE_CANDIDATE_MARKER',
        'NO_FREE_CANDIDATE_MARKER', 'NO_FREE_MANUAL_MARKER', 'MANUAL_MARKER_FAILED',
        'MANUAL_MARKER_UPDATE_FAILED', 'MARKERS_UNAVAILABLE', 'REANALYZE_MARKER_CLEAR_FAILED',
        'REANALYZE_NO_REMAINING_V1_CLIPS', 'SAVE_REANALYZE_MARKERS_FAILED',
    ):
        return EditingErrorInfo(
            code=code,
            stage_label='③ 静音标红与标记',
            title='在时间线上写入红色/橙色检查标记时失败',
            inline_text='⚠ 标记写入异常：无法在达芬奇时间线上更新自动标红标记',
            cause='目标帧位置已有冲突的手动标记，或者时间线上的 V1 片段已被清空，导致无法打上静音待删红标。',
            location_items=locs,
            solutions=[
                '检查达芬奇时间线标尺上是否有密集重叠的旧标记，可清理多余手工标记后点击「↻ 重新识别」；',
                '若该批次片段已被清空，请点击「⋯ → 跳过当前批次」重新导入。',
            ],
            raw_error=raw,
        )

    # ── Category C: Audio Export / Whisper / Cloud ASR / Script Alignment ──
    if code == 'ALIGNMENT_SIZE_LIMIT':
        return EditingErrorInfo(
            code=code,
            stage_label='② 文案与语音核对',
            title='本批次单次核对的音频词数或文案过长，超出安全上限',
            inline_text='⚠ 文案核对超限：本批视频总时长或文案字数过多，建议分批导入剪辑',
            cause='当前同一条时间线一次性塞入了过多视频或超长文案，全局词序列与台词对齐矩阵超出了内存保护上限。',
            location_items=locs,
            solutions=[
                '点击上方「⋯ → 跳过当前批次（退回待剪辑）」解除当前批次锁；',
                '点击「➕ 剪辑下一批」分批处理（例如每次导入 15～30 条完整视频），即可快速稳定完成识别对齐。',
            ],
            raw_error=raw,
        )

    if code in ('TEXT_ALIGNMENT_FAILED', 'AUDIO_BATCH_TEXT_MAP_MISMATCH', 'AUDIO_BATCH_NOT_ASSIGNED', 'AUDIO_BATCH_RANGE_INVALID', 'AUDIO_BATCH_VIDEO_OUT_OF_RANGE'):
        return EditingErrorInfo(
            code=code,
            stage_label='② 文案与语音核对',
            title='语音识别结果与视频台词文案未能对齐',
            inline_text='⚠ 文案对齐未通过：识别出的语音内容与表格台词差异较大或语种设置不符',
            cause='视频实际口播语言与当前设置的识别语种不一致、音频无有效人声、或导入的视频顺序与台词不对应。',
            location_items=locs,
            solutions=[
                '点击顶部「🎙 识别模型」胶囊按钮，检查识别语种（如英语 / 斯瓦希里语 / 自动检测）是否与主播实际说的语言一致；',
                '推荐切换识别度更高的模型（如云端 ElevenLabs Scribe / OpenAI Whisper）后，点击「重试整批分析」或「↻ 重新识别」。',
            ],
            raw_error=raw,
        )

    if code in ('CLOUD_ASR_NO_KEY', 'WHISPER_CONFIG_MISSING', 'WHISPER_RUNNER_NOT_SET'):
        return EditingErrorInfo(
            code=code,
            stage_label='② 语音识别配置',
            title='尚未配置语音识别所需的密钥或本地模型组件',
            inline_text='⚠ 缺少识别配置：请先配置云端识别 API 密钥或在组件管理中安装本地 Whisper',
            cause='当前选用了云端语音识别但密钥池中没有可用 API Key，或者选用了本地 whisper.cpp 但尚未安装模型文件。',
            location_items=locs,
            solutions=[
                '点击自动剪辑页顶部的「🎙 识别模型」按钮；',
                '若使用云端识别（ElevenLabs / OpenAI / Groq 等），点击「配置密钥 / 轮询」填入有效 API Key；',
                '若使用本地免费识别，请切换到本地 `whisper.cpp` 并在「系统设置 / 组件管理」中检测安装模型后重试。',
            ],
            raw_error=raw,
        )

    if code in (
        'WHISPER_FAILED', 'WHISPER_BATCH_FAILED', 'WHISPER_BATCH_NO_WORDS', 'WHISPER_RETRY_FAILED',
        'WHISPER_RETRY_EMPTY', 'WHISPER_TIMEOUT', 'WHISPER_LANGUAGE_ERROR', 'WHISPER_LANGUAGE_INVALID',
        'NO_ACTIVITY', 'SILENCE_PROBE_FAILED', 'SILENCE_PROBE_INVALID_OUTPUT', 'AUDIO_PROBE_FAILED',
    ):
        return EditingErrorInfo(
            code=code,
            stage_label='② 语音识别阶段',
            title='音频语音识别失败或未检测到人声',
            inline_text='⚠ 语音识别未通过：识别超时、API 额度受限，或导出的音频中没有检测到人声',
            cause='可能是云端 ASR 接口网络波动 / Key 余额不足，或者达芬奇 A1 音频轨被静音导致导出的 WAV 音频全是静音。',
            location_items=locs,
            solutions=[
                '先检查达芬奇时间线左侧 A1 音频轨是否被点了静音（M 按钮亮起），确保播放时间线能听到主播声音；',
                '若使用云端模型，点顶部「🎙 识别模型」检查 API Key 可用数量或临时切换到其他识别通道；',
                '确认无误后点击上方「重试整批分析」重新运行。',
            ],
            raw_error=raw,
        )

    if code == 'WAV_OUTPUT_ALREADY_EXISTS':
        return EditingErrorInfo(
            code=code,
            stage_label='② 导出分析音频',
            title='旧的分析音频文件已存在，需重新发起分析任务',
            inline_text='⚠ 音频缓存冲突：上次分析留下的 WAV 文件已存在，请点击「重试整批分析」新建任务',
            cause='复用旧请求重试时检测到上一次的 `timeline.wav` 已经存在，为防止读取串批音频被安全拦截。',
            location_items=locs,
            solutions=[
                '直接回到 Flow Studio 页面点击「开始自动剪辑 / 重试整批分析」（会自动分配全新分析目录），不要在达芬奇脚本菜单手动重跑旧任务。',
            ],
            raw_error=raw,
        )

    if code in (
        'WAV_AUDIO_ONLY_SETTINGS_FAILED', 'WAV_PRESET_AUTO_SETUP_FAILED', 'WAV_RENDER_SETTINGS_FAILED',
        'ADD_WAV_RENDER_FAILED', 'START_WAV_RENDER_FAILED', 'WAV_RENDER_FAILED',
        'WAV_RENDER_NOT_COMPLETE', 'WAV_RENDER_TIMEOUT', 'WAV_OUTPUT_MISSING',
        'WAV_OUTPUT_EMPTY', 'WAV_FORMAT_ERROR', 'WAV_DURATION_MISMATCH', 'WAV_RANGE_ERROR',
        'WAV_PATH_MISSING', 'COMPRESSED_WAV_NOT_SUPPORTED',
        'TIMELINE_WAV_PATH_MISSING', 'TIMELINE_WAV_PATH_MISMATCH',
        'TIMELINE_WHISPER_PATH_MISSING', 'TIMELINE_WHISPER_PATH_MISMATCH',
    ):
        return EditingErrorInfo(
            code=code,
            stage_label='② 导出分析音频',
            title='达芬奇导出时间线识别音频（WAV）失败',
            inline_text='⚠ 音频导出失败：达芬奇未能渲染用于语音识别的 WAV 音频文件',
            cause='自动剪辑第一步需要先将时间线音频渲染成未压缩 WAV 供模型识别，但达芬奇交付页未能创建或完成该音频渲染任务（常见于交付页正忙、A1 无音频或磁盘满）。',
            location_items=locs,
            solutions=[
                '检查达芬奇「交付（Deliver）」页面是否有未结束的渲染任务或报错弹窗；',
                '确认时间线 A1 轨道上有正常音频波形且未静音，电脑本地磁盘剩余空间充足；',
                '点击「唤醒达芬奇」对齐状态后，再点击「重试整批分析」。',
            ],
            raw_error=raw,
        )

    # ── Category D: Import Stage (`FlowStudio_Import_Batch.lua` & `resolve_batches.py`) ──
    if code == 'IMPORT_UNCERTAIN':
        return EditingErrorInfo(
            code=code,
            stage_label='① 素材导入阶段',
            title='上一次导入中途中断，为防止重复导入已暂停',
            inline_text='⚠ 导入需确认：上次导入未正常结束，请先检查达芬奇时间线是否已有部分片段',
            cause='上一次批量导入过程中达芬奇无响应或被中断，系统不确定最后几段素材是否已经落入时间线，因此自动暂停避免同一批视频被重复追加两遍。',
            location_items=locs,
            solutions=[
                '最简单稳妥的办法：直接点击上方操作栏的「➕ 剪辑下一批」，自动新建一条干净的独立时间线（如 B2），再点击「导入剪辑素材」；',
                '或者先点击「⋯ → 跳过当前批次（退回待剪辑）」，清空当前时间线残留片段后再重新导入。',
            ],
            raw_error=raw,
        )

    if code in ('SOURCE_NOT_READABLE', 'SOURCE_EMPTY', 'FILE_MISSING', 'MISSING_SEGMENT_PATH', 'MEDIA_IMPORT_FAILED', 'MEDIA_IMPORT_COUNT_MISMATCH'):
        return EditingErrorInfo(
            code=code,
            stage_label='① 素材导入阶段',
            title='待导入的本地视频片段缺失、损坏或无法读取',
            inline_text='⚠ 素材文件异常：部分视频片段文件不存在、大小为 0 或达芬奇无法解码',
            cause='Flow 下载到本地的某个片段文件被移动、删除、体积为 0 字节，或者文件尚未写完就被尝试导入。',
            location_items=locs,
            solutions=[
                '查看「涉及文件」路径是否存在且能正常播放；',
                '若某个片段损坏缺失，可回到「Flow 生成中心 → 下载完成（绿色数字）」勾选对应视频点击「重新下载」，质检通过后再重新导入。',
            ],
            raw_error=raw,
        )

    if code in (
        'TRANSFORM_TIMELINE_SIZE_MISMATCH', 'TRANSFORM_SET_FAILED', 'TRANSFORM_VERIFY_FAILED',
        'TRANSFORM_VIDEO_CLIP_NOT_FOUND', 'INVALID_INTEGER', 'INVALID_NUMBER',
        'APPEND_FAILED', 'INSERT_LENGTH_INVALID', 'INSERT_POSITION_MISMATCH',
        'TIMELINE_CLIP_COUNT_MISMATCH', 'GROUP_GAP_MUST_BE_50_FRAMES',
        'HEAL_APPEND_SINGLE_FAILED', 'HEAL_DELETE_PARTIAL_FAILED',
        'HEAL_MEDIAPOOL_ITEM_MISSING', 'HEAL_TRANSFORM_FAILED', 'HEAL_VIDEO_COUNT_MISMATCH',
    ):
        return EditingErrorInfo(
            code=code,
            stage_label='① 素材导入与画面参数',
            title='导入片段到时间线或同步画面缩放位移参数时失败',
            inline_text='⚠ 导入写入异常：达芬奇未能返回新片段位置或质检缩放参数同步失败',
            cause=(
                '将视频追加到时间线并写入质检阶段的画面位移/缩放参数时，达芬奇 API 返回了空值（nil）或时间线尺寸不一致'
                '（通常发生在导入瞬间切换了时间线、轨道被锁、或达芬奇刚启动尚未完全就绪）。'
            ),
            location_items=locs,
            solutions=[
                '确认达芬奇当前时间线的 V1 和 A1 轨道未加锁，且导入期间不要点击切换其他时间线；',
                '点击「① 唤醒达芬奇」重新确认项目与时间线分辨率后，点击「重试原批次导入」（若提示上次导入未完成，点「➕ 剪辑下一批」新建时间线导入即可）。',
            ],
            raw_error=raw,
        )

    if code in ('EMPTY_BATCH', 'EMPTY_VIDEO', 'DUPLICATE_VIDEO_ID_IN_CURRENT_BATCH', 'DUPLICATE_SEGMENT_ID_IN_CURRENT_BATCH', 'MEDIA_POOL_UNAVAILABLE', 'MEDIA_ROOT_UNAVAILABLE', 'MEDIA_FOLDERS_UNAVAILABLE', 'CREATE_MEDIA_FOLDER_FAILED', 'SET_MEDIA_FOLDER_FAILED'):
        return EditingErrorInfo(
            code=code,
            stage_label='① 素材导入阶段',
            title='待导入批次清单为空或达芬奇媒体池暂不可用',
            inline_text='⚠ 无法导入素材：当前没有齐套待剪辑视频，或达芬奇媒体池尚未就绪',
            cause='当前没有全部片段质检通过的待剪辑视频，或者达芬奇媒体池目录树正处于锁定/未打开项目状态。',
            location_items=locs,
            solutions=[
                '确认下方队列中有状态为「▣ 待剪辑」的完整视频；',
                '先点击「① 唤醒达芬奇」等待右上角显示「🟢 达芬奇已就绪」，再点击「导入剪辑素材」。',
            ],
            raw_error=raw,
        )

    # ── Category E: Connection / Wake / Project / Timeline / Locks (`resolve_daily.py` & Bridge) ──
    if code in ('PIPELINE_LOCKED', 'BRIDGE_LOCKED', 'RENDER_ALREADY_RUNNING', 'RENDER_STILL_RUNNING'):
        return EditingErrorInfo(
            code=code,
            stage_label='达芬奇连接与队列锁',
            title='当前已有正在执行的批次或渲染任务尚未结束',
            inline_text='⚠ 任务占用中：当前批次尚未结束或达芬奇正在渲染，请等待完成或跳过旧批次',
            cause='同一时间只能安全运行一个达芬奇剪辑/导出任务；当前存在未结束的批次锁，或者达芬奇交付页正在渲染视频。',
            location_items=locs,
            solutions=[
                '如果达芬奇正在导入、切刀或渲染，请耐心等待进度条走完；',
                '如果上一批其实已经人工处理完或卡住不再需要，请点击操作栏右侧「⋯」按钮，选择「✓ 手动标记本批已完成」或「⏭ 跳过当前批次」即可立即解锁！',
            ],
            raw_error=raw,
        )

    if code in ('RESOLVE_NOT_READY', 'RESOLVE_MAIN_WINDOW_NOT_READY', 'PROJECT_MANAGER_UNAVAILABLE', 'PROJECT_LIST_UNAVAILABLE', 'PROJECT_ROOT_UNAVAILABLE'):
        return EditingErrorInfo(
            code=code,
            stage_label='① 唤醒达芬奇',
            title='达芬奇尚未初始化完成（停留在启动画面或项目库弹窗）',
            inline_text='⚠ 达芬奇未就绪：请等待达芬奇主界面完全打开（若停在项目管理器请随便进一个项目）后再唤醒',
            cause='DaVinci Resolve 还在加载启动界面、卡在首次欢迎向导/许可弹窗，导致脚本接口还拿不到项目管理器。',
            location_items=locs,
            solutions=[
                '切到 DaVinci Resolve 窗口，确认它已经走完启动加载（如果停留在「项目管理器」小窗口，可双击打开任意项目进入主界面，并关闭任何升级/报错提示框）；',
                '随后回到本页面再次点击「① 唤醒达芬奇」。',
            ],
            raw_error=raw,
        )

    if code in ('RESOLVE_FOCUS_LOST', 'NEED_FOCUS'):
        return EditingErrorInfo(
            code=code,
            stage_label='① 唤醒达芬奇',
            title='唤醒期间达芬奇失去了前台窗口焦点',
            inline_text='⚠ 唤醒中断：达芬奇窗口未拿到最前台焦点，请点击重试并短暂保持不切窗口',
            cause='系统在自动点击达芬奇顶部「工作区 → 脚本」菜单启动 Bridge 时，达芬奇窗口被切到了后台或被其他窗口遮挡。',
            location_items=locs,
            solutions=[
                '点击「① 唤醒达芬奇」后，在达芬奇跳到前台的 2～3 秒内暂时不要点击鼠标切换窗口，等右上角变成「🟢 达芬奇已就绪」即可自由操作。',
            ],
            raw_error=raw,
        )

    if code in ('RESOLVE_MENU_NOT_FOUND',):
        return EditingErrorInfo(
            code=code,
            stage_label='① 唤醒达芬奇',
            title='未在达芬奇菜单中找到 Bridge 脚本项',
            inline_text='⚠ 菜单未找到：首次安装更新 Bridge 后需重启一次达芬奇以刷新脚本菜单',
            cause='达芬奇只在启动时扫描一次脚本文件夹；如果刚刚首次安装了新版 Bridge，或者达芬奇全屏/最小化隐藏了菜单栏，就会找不到脚本入口。',
            location_items=locs,
            solutions=[
                '确保达芬奇主窗口处于正常显示状态（未最小化到程序坞）；',
                '如果是刚安装或更新后第一次使用，请完全退出（Cmd+Q）并重新打开一次 DaVinci Resolve，然后再点「① 唤醒达芬奇」；',
                '也可展开「高级调试 ▸」点击一次「安装 / 更新新版 Bridge」确认脚本已写入。',
            ],
            raw_error=raw,
        )

    if code == 'LEGACY_BRIDGE_RUNNING':
        return EditingErrorInfo(
            code=code,
            stage_label='① 唤醒达芬奇',
            title='检测到旧版 Bridge 脚本仍在后台运行',
            inline_text='⚠ 版本冲突：旧版 Bridge 仍在运行，请重启一次达芬奇后再点击唤醒',
            cause='达芬奇内部仍挂着旧版本的 Bridge 进程，为防止新旧两个脚本同时抢指令导致错乱，系统已阻止并发启动。',
            location_items=locs,
            solutions=[
                '保存当前达芬奇项目后，完全退出并重新打开 DaVinci Resolve；',
                '重新打开后直接点击本页面的「① 唤醒达芬奇」即可自动启用新版 Bridge。',
            ],
            raw_error=raw,
        )

    if code == 'UNSAVED_PROJECT':
        return EditingErrorInfo(
            code=code,
            stage_label='① 项目切换保护',
            title='达芬奇当前打开的其他项目有未保存修改',
            inline_text='⚠ 未保存保护：达芬奇当前项目有未保存内容，请先在达芬奇按 Cmd+S 保存后再唤醒',
            cause='达芬奇当前打开的是另一个项目且存在未保存改动；为保护你的剪辑成果不丢失，系统不会强行关闭未保存的项目。',
            location_items=locs,
            solutions=[
                '切换到 DaVinci Resolve 按 `Cmd + S`（Windows 按 `Ctrl + S`）保存当前项目；',
                '回到本页面再次点击「① 唤醒达芬奇」，即可安全切换到今日项目。',
            ],
            raw_error=raw,
        )

    if code in (
        'SAVE_PROJECT_FAILED', 'SAVE_BATCH_FAILED', 'SAVE_CLEANUP_FAILED', 'SAVE_CLEANUP_RECOVERY_FAILED',
        'LOAD_PROJECT_FAILED', 'CREATE_PROJECT_FAILED', 'PROJECT_UNAVAILABLE', 'PROJECT_NOT_OPEN',
        'PROJECT_MISMATCH', 'PROJECT_SWITCH_NOT_CONFIRMED', 'PROJECT_SETTING_FAILED',
    ):
        return EditingErrorInfo(
            code=code,
            stage_label='① 项目加载与保存',
            title='达芬奇创建、切换或保存项目失败',
            inline_text='⚠ 项目操作失败：达芬奇未能加载或保存当天项目，请检查达芬奇是否有弹窗阻塞',
            cause='达芬奇数据库磁盘空间不足、权限受限，或达芬奇界面正弹出模态对话框导致无法创建/切换/保存 `FlowStudio-日期` 项目。',
            location_items=locs,
            solutions=[
                '切到达芬奇窗口检查是否有未关闭的提示框，手动按一次 `Cmd + S` 测试能否正常保存；',
                '确认正常后回到本页面点击「① 唤醒达芬奇」重新连接。',
            ],
            raw_error=raw,
        )

    if code in (
        'SET_TIMELINE_FAILED', 'CREATE_TIMELINE_FAILED', 'TIMELINE_UNAVAILABLE', 'TIMELINE_NOT_OPEN',
        'TIMELINE_MISMATCH', 'ACTIVE_TIMELINE_CHANGED', 'TIMELINE_CHANGED_DURING_ANALYSIS',
        'TIMELINE_CHANGED_BEFORE_CUTTING', 'TARGET_CHANGED_DURING_IMPORT', 'TARGET_NAME_MISMATCH',
        'DAILY_NAME_MISMATCH', 'DUPLICATE_MAIN_TIMELINE', 'TIMELINE_READ_FAILED',
        'TIMELINE_END_UNAVAILABLE', 'TIMELINE_CUSTOM_SETTINGS_FAILED',
        'TIMELINE_RESOLUTION_FAILED', 'TIMELINE_RESOLUTION_NOT_CONFIRMED', 'INVALID_TIMELINE_NAME',
    ):
        return EditingErrorInfo(
            code=code,
            stage_label='① 时间线同步',
            title='达芬奇当前打开的时间线与所选批次不一致或切换失败',
            inline_text='⚠ 时间线未对齐：达芬奇当前时间线与本页选中的批次不一致，请点「① 唤醒达芬奇」自动切换',
            cause='在达芬奇内手动切换了其他时间线、媒体池中存在重名时间线冲突，或者时间线尚未打开。',
            location_items=locs,
            solutions=[
                '直接点击上方蓝色的「① 唤醒达芬奇」按钮，程序会自动在达芬奇中定位并切换到本页下拉框选中的时间线；',
                '如果媒体池中有多条重名冲突的时间线，可点击「➕ 剪辑下一批」切换到新的独立时间线槽位（如 B2 / B3）。',
            ],
            raw_error=raw,
        )

    if code in ('FPS_MISMATCH', 'FPS_UNAVAILABLE', 'INVALID_FPS', 'DROP_FRAME_NOT_SUPPORTED'):
        return EditingErrorInfo(
            code=code,
            stage_label='① 帧率设置检查',
            title='达芬奇时间线帧率与系统设置不一致（或开启了丢帧时间码）',
            inline_text='⚠ 帧率不匹配：当前达芬奇项目/时间线帧率与 Flow Studio 设置不一致',
            cause='已创建的今日项目帧率（例如 24fps）与后续修改的系统设置帧率（例如 25fps）不同，或时间线开启了 Drop-Frame（丢帧）模式，达芬奇不允许在已有时间线上强改帧率。',
            location_items=locs,
            solutions=[
                '打开 Flow Studio「系统设置」，将「时间线帧率」改回与当前达芬奇项目一致的帧率（常用 25 或 24），或点击「➕ 剪辑下一批」新建时间线；',
                '若在达芬奇手动改过项目设置，请关闭「使用丢帧时间码（Drop frame timecode）」后重试。',
            ],
            raw_error=raw,
        )

    if code in (
        'TASK_ID_MISMATCH', 'PAYLOAD_PATH_MISMATCH', 'INVALID_REQUEST_ID', 'INVALID_BATCH_ID',
        'INVALID_ATTEMPT_ID', 'INVALID_VIDEO_ID', 'INVALID_ID', 'INVALID_DATE', 'INVALID_FINISH_MODE',
        'INVALID_DURATION', 'BATCH_IDENTITY_MISMATCH', 'IDENTITY_MISMATCH', 'BATCH_DATE_MISMATCH',
        'HISTORY_DATE_PROTECTED', 'CUT_PLAN_MISSING', 'CUT_PLAN_IDENTITY_MISMATCH',
        'IMPORT_MANIFEST_MISSING', 'MANIFEST_PATH_MISMATCH', 'MANUSCRIPT_PATH_MISMATCH',
        'TASK_JSON_BATCH_MISMATCH', 'TASK_JSON_ID_MISMATCH', 'TASK_JSON_LANGUAGE_MISMATCH',
        'TASK_JSON_PATH_MISMATCH', 'BATCH_ID_REQUIRED', 'ARCHIVE_OLD_PIPELINE_FAILED',
    ):
        return EditingErrorInfo(
            code=code,
            stage_label='批次状态同步',
            title='批次任务标识或清单文件已过期不匹配',
            inline_text='⚠ 批次状态过期：指令与当前活动批次不一致，请刷新状态或重新发起操作',
            cause='通常是因为切换了工作日期、重建过时间线，或重复发送了已被新批次取代的旧指令，安全校验拦截了跨批次误操作。',
            location_items=locs,
            solutions=[
                '先检查顶部「工作日期」和时间线下拉框是否为你要操作的那一批；',
                '点击一次「① 唤醒达芬奇」同步最新状态后，再重新点击对应的导入 / 自动剪辑 / 导出按钮；',
                '若旧批次已废弃，可点击「⋯ → 跳过当前批次」清理旧锁后重新开始。',
            ],
            raw_error=raw,
        )

    if code in (
        'AUTOEDIT_MODULE_MISSING', 'IMPORT_MODULE_MISSING', 'PYTHON_PATH_MISSING',
        'WINDOWS_RUNTIME_NOT_INSTALLED', 'WINDOWS_RUNTIME_CONFIG_MISSING',
        'WINDOWS_HELPER_START_FAILED', 'WINDOWS_HELPER_TIMEOUT', 'WINDOWS_WRITE_PIPE_UNSUPPORTED',
        'UNSUPPORTED_ACTION', 'UNSUPPORTED_BACKGROUND_COMMAND', 'UNSUPPORTED_WINDOWS_BRIDGE_COMMAND',
        'RESOLVE_PROCESS_MISMATCH', 'PROCESS_ID_REUSED',
    ):
        return EditingErrorInfo(
            code=code,
            stage_label='Bridge 组件环境',
            title='达芬奇 Bridge 插件脚本缺失或版本不一致',
            inline_text='⚠ 插件组件异常：Bridge 脚本模块缺失或版本未同步，请点「安装 / 更新新版 Bridge」',
            cause='达芬奇脚本目录中的某个子模块文件被清理或版本不配套。',
            location_items=locs,
            solutions=[
                '点击本页右上角「高级调试 ▸」，点击「安装 / 更新新版 Bridge」一键补齐最新脚本；',
                '重启一次 DaVinci Resolve 后点击「① 唤醒达芬奇」即可恢复。',
            ],
            raw_error=raw,
        )

    if code in ('WRITE_FAILED', 'PUBLISH_FAILED', 'MKDIR_FAILED', 'RENAME_FAILED'):
        return EditingErrorInfo(
            code=code,
            stage_label='本地磁盘读写',
            title='写入本地缓存、状态文件或导出目录失败',
            inline_text='⚠ 文件写入失败：请检查磁盘剩余空间与导出文件夹写入权限',
            cause='目标磁盘已满、外接硬盘断开连接、文件正在被其他播放器占用，或系统文件夹无写入权限。',
            location_items=locs,
            solutions=[
                '检查电脑磁盘及外接存储剩余空间是否充足、连接是否正常；',
                '关闭正在播放目标 MP4 的播放器窗口后重试。',
            ],
            raw_error=raw,
        )

    return None


def _diagnose_pattern_or_chinese(clean: str, raw: str, ctx: dict[str, str], locs: list[tuple[str, str]], batch_status: str, stage: str) -> EditingErrorInfo:
    low = clean.lower()

    # 1. Re-export wrapper prefix ("重新导出完成：成功 0 个，失败 1 个 · <inner>")
    if clean.startswith('重新导出完成：') and '失败' in clean:
        parts = clean.split(' · ', 1)
        head = parts[0].strip()
        tail = parts[1].strip() if len(parts) > 1 else ''
        if tail:
            inner = diagnose_editing_error(tail, batch_status='EXPORT_ERROR', stage=stage)
            if inner is not None:
                clean_tail = inner.inline_text.lstrip('⚠ ').strip()
                return EditingErrorInfo(
                    code=inner.code,
                    stage_label='④ 重新导出成品',
                    title=f'{head}（{inner.title}）',
                    inline_text=f'⚠ {head} · {clean_tail}',
                    cause=inner.cause,
                    location_items=inner.location_items or locs,
                    solutions=inner.solutions,
                    raw_error=raw,
                )
        return EditingErrorInfo(
            code='REEXPORT_FAILED',
            stage_label='④ 重新导出成品',
            title=head,
            inline_text=f'⚠ {clean}',
            cause='重新导出选中视频时，达芬奇未能完成渲染或时间线上已找不到对应视频片段（原旧成品已自动保护恢复）。',
            location_items=locs,
            solutions=[
                '确认达芬奇已打开当天项目，并且切换到了该视频原本所在的时间线（如 MAIN-日期 或 B2）；',
                '切到达芬奇时间线确认该视频片段未被手动删空，再重新勾选点击「重新导出选中视频」。',
            ],
            raw_error=raw,
        )

    # 1b. Partial autoedit skip with orange markers ("自动剪辑完成；识别失败已跳过 2 个，橙色 Marker 请手动剪辑")
    m_orange = re.search(r'识别失败已跳过\s*(\d+)\s*个', clean)
    if m_orange and int(m_orange.group(1)) > 0:
        skip_n = int(m_orange.group(1))
        inline_cn = clean.replace('Marker', '标记').lstrip('⚠ ').strip()
        return EditingErrorInfo(
            code='PARTIAL_RECOGNITION_SKIPPED',
            stage_label='③ 待人工检查提醒',
            title=f'已完成自动切刀，其中 {skip_n} 条视频需人工检查橙色标记',
            inline_text=f'⚠ {inline_cn}',
            cause=(
                f'本批其余视频已自动切刀标红，但有 {skip_n} 条视频因口播语音与表格文案差异较大（或发音含糊），'
                '系统为避免误切正片，自动保留了它们的完整原片并在时间线上打上了「橙色标记」。'
            ),
            location_items=locs,
            solutions=[
                '可先点击顶部「🎙 识别模型」切换到识别率更高的云端模型（如 ElevenLabs），然后点「↻ 重新识别」自动重算切点；',
                '或者直接在达芬奇时间线上找到「橙色标记」对应的视频，手动修剪首尾静音（或给要删的小片段打蓝色标记），随后正常点击「④ 确认清理」与「批量导出」。',
            ],
            raw_error=raw,
        )

    # 2. macOS Accessibility / Automation permissions
    if any(t in low for t in ('-1719', '-1743', 'assistive', 'not authorized', 'not allowed', '辅助功能', '自动化权限')):
        return EditingErrorInfo(
            code='MACOS_PERMISSION',
            stage_label='系统权限检查',
            title='缺少 macOS「辅助功能」或「自动化」控制权限',
            inline_text='⚠ 缺少系统权限：请在 macOS「系统设置 → 隐私与安全性 → 辅助功能」中勾选允许 Flow Studio',
            cause='Flow Studio 需要通过 macOS 辅助功能自动点击达芬奇脚本菜单并控制切刀快捷键，当前系统拦截了该控制请求。',
            location_items=locs,
            solutions=[
                '打开苹果菜单「系统设置 → 隐私与安全性 → 辅助功能」，找到 `Flow Studio`（如已有但刚更新过应用，请先点减号移除再重新添加打开开关）；',
                '再检查「隐私与安全性 → 自动化」，确保 `Flow Studio` 下方的 `System Events` 与 `DaVinci Resolve` 开关已开启；',
                '开启后回到本页面点击「① 唤醒达芬奇」即可正常联动。',
            ],
            raw_error=raw,
        )

    # 3. Lua runtime nil / method errors (e.g. "attempt to call method 'GetRenderJobStatus' (a nil value)")
    if any(t in low for t in ('attempt to call', 'attempt to index', 'attempt to concatenate', 'attempt to perform')):
        m_sym = re.search(r"'([^']+)'", clean)
        sym = m_sym.group(1) if m_sym else ''
        if sym == 'GetRenderJobStatus':
            return EditingErrorInfo(
                code='LUA_RENDER_API_COMPAT',
                stage_label='④ 批量渲染导出',
                title='达芬奇渲染状态查询接口未响应或脚本待更新',
                inline_text='⚠ 渲染状态读取异常：请先更新新版 Bridge 脚本或唤醒达芬奇后重试导出',
                cause='旧版 Bridge 脚本调用了当前达芬奇版本不支持的渲染状态方法，或项目对象在渲染切换时短暂失效。',
                location_items=locs,
                solutions=[
                    '展开右上角「高级调试 ▸」，点击一次「安装 / 更新新版 Bridge」（或直接点击「① 唤醒达芬奇」自动覆盖最新脚本）；',
                    '随后点击「重试批量导出」，已完成导出的视频会自动跳过不重导。',
                ],
                raw_error=raw,
            )
        return EditingErrorInfo(
            code='LUA_RUNTIME_ERROR',
            stage_label='达芬奇脚本执行',
            title='达芬奇内部自动化脚本遇到空对象或接口异常',
            inline_text='⚠ 达芬奇脚本执行异常：项目/时间线对象短暂失效，请重新唤醒达芬奇后重试',
            cause=(
                '达芬奇内部 Lua 脚本在读取时间线片段或项目属性时拿到了空值'
                + (f'（内部字段 `{sym}`）' if sym else '')
                + '，常见于达芬奇正在切换页面、媒体离线，或 Bridge 脚本尚未更新到最新版。'
            ),
            location_items=locs,
            solutions=[
                '先点击「① 唤醒达芬奇」自动更新 Bridge 脚本并重新对齐当前时间线；',
                '确认达芬奇处于「剪辑（Edit）」页面且无离线报错弹窗后，重新点击刚才的操作按钮；',
                '如仍复现，可点击下方「📋 复制详情」或「📂 查看本批日志」排查具体片段。',
            ],
            raw_error=raw,
        )

    # 4. Bridge disconnected / wake timeout
    if any(t in clean for t in ('Resolve Bridge 连接中断', 'Bridge 未连接', '启动超时', '准备项目超时', '没有找到正在运行的达芬奇', '菜单栏还没准备好', '没有找到 Bridge')):
        return EditingErrorInfo(
            code='BRIDGE_DISCONNECTED',
            stage_label='① 达芬奇连接',
            title='达芬奇 Bridge 连接中断或唤醒超时',
            inline_text=f'⚠ {clean.lstrip("⚠ ").strip()}',
            cause='达芬奇已关闭、正在繁忙渲染无暇响应心跳、首次安装脚本后尚未重启达芬奇刷新菜单，或达芬奇停留在欢迎/弹窗界面。',
            location_items=locs,
            solutions=[
                '确认 DaVinci Resolve 已打开并进入主工作界面（没有停留在小窗口的项目列表或系统弹窗）；',
                '点击「① 唤醒达芬奇」，并在唤醒的几秒内让达芬奇保持在屏幕最前方；',
                '若是首次安装 Bridge 后一直找不到菜单，请完全退出并重开一次 DaVinci Resolve。',
            ],
            raw_error=raw,
        )

    # 5. Cloud ASR / HTTP / Network / API Key errors
    if any(t in low for t in ('401', '403', '429', 'quota', 'rate limit', 'unauthorized', 'invalid api key', 'api_key', 'elevenlabs', 'openai', 'groq', 'deepgram', 'httpsconnectionpool', 'ssl', 'timed out', 'connectionError'.lower())):
        return EditingErrorInfo(
            code='ASR_NETWORK_OR_KEY',
            stage_label='② 云端语音识别',
            title='云端语音识别接口请求失败（网络波动或密钥受限）',
            inline_text='⚠ 语音识别请求失败：云端 API 密钥失效/额度不足或网络连接超时',
            cause='调用云端语音识别服务时返回了鉴权失败（401/403）、并发限流/余额不足（429/Quota）或网络连接超时。',
            location_items=locs,
            solutions=[
                '点击顶部「🎙 识别模型」按钮，检查当前云端模型的 API Key 是否有效、额度是否充足；',
                '可以添加多个备用 Key 开启自动轮询，或临时切换到其他识别模型（如本地 `whisper.cpp`）；',
                '检查代理/网络连接正常后，点击「重试整批分析」或「↻ 重新识别」。',
            ],
            raw_error=raw,
        )

    # 6. Scripture subtitle alignment / mounting messages
    if '经文' in clean or '(SUV)' in clean or 'subtitle' in low:
        return EditingErrorInfo(
            code='SCRIPTURE_SUBTITLE_WARN',
            stage_label='② 经文字幕挂载',
            title='经文字幕识别或挂载未完成',
            inline_text=f'⚠ {clean.lstrip("⚠ ").strip()}' if not _ASCII_HEAVY_RE.search(clean) else '⚠ 经文字幕识别对齐失败：请检查语音识别配置与时间线状态后重试',
            cause='当前批次文案中没有带 `(SUV)` 标记的经文、音频识别接口调用失败，或者达芬奇时间线尚未导入该批视频。',
            location_items=locs,
            solutions=[
                '确认文案中包含标准的 `(SUV)` 经文引用标记，且已点击「② 导入剪辑素材」将视频导入当前时间线；',
                '检查顶部「🎙 识别模型」密钥或本地模型可用后，再次点击「📖 导入经文」。',
            ],
            raw_error=raw,
        )

    # 7. Google Sheets / Material source rescan errors
    if '读取表格失败' in clean or '素材来源' in clean or 'google' in low or 'spreadsheet' in low:
        return EditingErrorInfo(
            code='SHEET_RESCAN_ERROR',
            stage_label='表格素材来源同步',
            title='重新读取 Google 表格「素材来源」列失败',
            inline_text='⚠ 读取 Google 表格「素材来源」失败：请检查网络连接或表格链接权限后重试',
            cause='访问 Google 表格时网络连接超时、代理不稳定，或当前日期尚未绑定有效的在线表格数据源。',
            location_items=locs,
            solutions=[
                '检查当前网络是否能正常访问 Google 表格，稍等几秒后再次点击「↻ 重读素材来源」；',
                '也可直接点击顶部「💧 AI水印」手动为指定主播选择或输入副水印名字，保存后点「💧 刷新水印」立即生效。',
            ],
            raw_error=raw,
        )

    # 8. Python OS / File / Permission / Disk errors
    if any(t in low for t in ('no such file', 'filenotfounderror', 'permissionerror', 'permission denied', 'no space left', 'errno 28', 'errno 13', 'errno 2', 'isadirectoryerror', 'oserror')):
        return EditingErrorInfo(
            code='OS_FILE_ERROR',
            stage_label='本地文件与磁盘',
            title='本地文件读写失败（文件不存在、权限受限或磁盘已满）',
            inline_text='⚠ 本地文件读写异常：找不到目标文件、缺少文件夹权限或磁盘空间不足',
            cause='操作涉及的视频素材、临时音频或导出目录不存在，或者磁盘空间已满 / 外接移动硬盘已断开。',
            location_items=locs,
            solutions=[
                '检查「涉及文件」所在目录是否存在、外接硬盘是否正常挂载且剩余空间充足；',
                '在「系统设置」核对「剪辑路径根目录」设置无误后重试。',
            ],
            raw_error=raw,
        )

    # 9. Already natural Chinese validation/business error (e.g., from ValueError / RuntimeError in Python services)
    # Strip any residual English tokens if mixed, or keep pure Chinese message intact while still giving tailored solutions!
    has_cjk = bool(re.search(r'[\u4e00-\u9fff]', clean))
    english_words = re.findall(r'[A-Za-z_]{4,}', clean)
    allowed_brand_words = {'davinci', 'resolve', 'bridge', 'flow', 'studio', 'whisper', 'main', 'flowstudio', 'elevenlabs', 'openai', 'groq'}
    non_brand_en = [w for w in english_words if w.lower() not in allowed_brand_words]

    stage_by_batch = {
        'IMPORT_ERROR': '① 素材导入阶段',
        'ANALYSIS_ERROR': '② 语音识别与核对',
        'CUTTING_ERROR': '③ 自动切刀阶段',
        'CLEANING_ERROR': '④ 清理与水印阶段',
        'EXPORT_ERROR': '④ 批量导出阶段',
    }.get(str(batch_status or '').upper(), '自动剪辑诊断')

    if has_cjk and not non_brand_en:
        clean_disp = clean.lstrip('⚠ ').strip()
        # Craft context-aware solutions for Chinese business prompts
        sols: list[str] = []
        if '时间线' in clean_disp or '唤醒' in clean_disp:
            sols.append('确认顶部时间线下拉框已选对目标批次，然后点击「① 唤醒达芬奇」自动打开对应项目与时间线；')
        if '正在执行' in clean_disp or '还在进行' in clean_disp or '等待当前操作' in clean_disp or '正在渲染' in clean_disp:
            sols.append('等待当前正在运行的导入、剪辑或渲染任务完成后再提交；若旧批次已卡死，可点「⋯ → 跳过当前批次」解锁；')
        if 'whisper' in clean_disp.lower() or '识别' in clean_disp or '密钥' in clean_disp:
            sols.append('点击顶部「🎙 识别模型」检查识别通道与 API 密钥，或在系统设置中检测本地 whisper.cpp 组件；')
        if '找不到对应的已完成剪辑批次' in clean_disp or '不在批次清单中' in clean_disp:
            sols.append('该视频可能是手动绑定成品或旧批次已被重建，可使用「剪辑记录 / 重新剪辑」重新导入达芬奇剪辑导出；')
        if not sols:
            sols = [
                '请先点击「① 唤醒达芬奇」确认右上角状态变为「🟢 达芬奇已就绪」；',
                '按提示核对当前时间线与素材状态后重试；如需跳过卡住的当前批次，可点操作栏右侧「⋯ → 跳过当前批次」。',
            ]
        return EditingErrorInfo(
            code='WORKFLOW_NOTICE',
            stage_label=stage_by_batch,
            title=clean_disp[:42] + ('…' if len(clean_disp) > 42 else ''),
            inline_text=f'⚠ {clean_disp}',
            cause=clean_disp,
            location_items=locs,
            solutions=sols,
            raw_error=raw,
        )

    # 10. Guaranteed Zero-English Fallback: even for any unforeseen raw English exception/code!
    fallback_inline_map = {
        'IMPORT_ERROR': '⚠ 素材导入遇到异常：部分片段未能正常导入时间线，请查看详情处理',
        'ANALYSIS_ERROR': '⚠ 自动剪辑分析未通过：音频导出或语音文案核对异常，请查看详情处理',
        'CUTTING_ERROR': '⚠ 自动切刀中途暂停：时间线状态已保护保留，请查看详情处理',
        'CLEANING_ERROR': '⚠ 清理废片或挂载水印中断：时间线现场已保护保留，请查看详情处理',
        'EXPORT_ERROR': '⚠ 批量导出遇到异常：已完成成品已保存，请查看详情处理',
    }
    inline_cn = fallback_inline_map.get(
        str(batch_status or '').upper(),
        '⚠ 剪辑操作遇到异常，已自动保护当前现场（点击右侧「查看详情」获取解决办法）',
    )
    if ctx.get('video_short'):
        inline_cn = f"{inline_cn.rstrip('）')} · {ctx['video_short']}"

    return EditingErrorInfo(
        code='UNCLASSIFIED_EDIT_ERROR',
        stage_label=stage_by_batch,
        title='剪辑流程遇到未预期的运行异常（已保护时间线现场）',
        inline_text=inline_cn,
        cause='达芬奇或后台辅助组件返回了一条底层技术异常，系统已立即停止后续改动以保护当前时间线不被破坏。可展开下方「原始技术信息」复制排查。',
        location_items=locs,
        solutions=[
            '先切到 DaVinci Resolve 查看是否有未关闭的弹窗、轨道加锁或红色离线片段（Media Offline）；',
            '回到本页面点击「① 唤醒达芬奇」刷新连接状态后，再点击当前阶段的「重试 / 继续」按钮；',
            '如果当前时间线批次反复异常，可点击「➕ 剪辑下一批」切换到全新时间线继续工作，互不干扰。',
        ],
        raw_error=raw,
    )


def diagnose_editing_error(raw_text: str, batch_status: str = '', stage: str = '') -> EditingErrorInfo | None:
    """Parse ``raw_text`` and return a complete Chinese ``EditingErrorInfo``, or ``None`` if not an error."""
    raw = str(raw_text or '').strip()
    if not raw:
        return None
    if not is_editing_error(raw, batch_status=batch_status, stage=stage):
        return None

    clean = strip_lua_prefixes(raw)
    clean_no_warn = re.sub(r'^(?:DaVinci：\s*)?⚠\s*', '', clean).strip()

    # Handle compound re-export summary ("重新导出完成：成功 X 个，失败 Y 个 · <inner_error>") first
    if clean_no_warn.startswith('重新导出完成：') and '失败' in clean_no_warn:
        ctx_r, locs_r = _extract_context(clean_no_warn)
        return _diagnose_pattern_or_chinese(clean_no_warn, raw, ctx_r, locs_r, batch_status, stage)

    # Unwrap common Chinese prefixes while preserving context
    for pfx in ('识别对齐经文失败：', '准备失败：', '清理旧文件失败:', '清理旧文件失败：', '读取表格失败：', '重新识别素材来源失败：'):
        if clean_no_warn.startswith(pfx):
            inner_str = clean_no_warn[len(pfx):].strip()
            if inner_str:
                clean_no_warn = inner_str
            break

    ctx, locs = _extract_context(clean_no_warn)
    code = _extract_primary_code(clean_no_warn)
    if code:
        specific = _build_specific_info(code, clean_no_warn, raw, ctx, locs)
        if specific is not None:
            return specific

    return _diagnose_pattern_or_chinese(clean_no_warn, raw, ctx, locs, batch_status, stage)


def format_inline_editing_text(
    raw_text: str,
    *,
    batch_status: str = '',
    stage: str = '',
    max_len: int = 115,
) -> tuple[str, EditingErrorInfo | None]:
    """Return ``(chinese_display_text, error_info_or_None)``.

    - If ``raw_text`` is an error/warning, returns concise pure-Chinese ``info.inline_text`` + ``info``.
    - Otherwise returns cleaned ``raw_text`` + ``None``.
    """
    raw = str(raw_text or '').strip()
    if not raw:
        return '', None
    info = diagnose_editing_error(raw, batch_status=batch_status, stage=stage)
    if info is None:
        disp = strip_lua_prefixes(raw)
        disp = disp.replace('VIDEO_SOURCE_MISSING_SKIPPED', '原素材缺失已跳过')
        disp = disp.replace('VIDEO_SOURCE_MISSING_AFTER_CLEANUP_SKIPPED', '原素材缺失已跳过')
        disp = disp.replace('COMPLETE Marker', '分界标记').replace('Marker', '标记')
        if max_len > 16 and len(disp) > max_len:
            disp = disp[: max_len - 1].rstrip('；;，, ') + '…'
        return disp, None
    disp = info.inline_text
    if max_len > 16 and len(disp) > max_len:
        disp = disp[: max_len - 1].rstrip('；;，, ') + '…'
    return disp, info
