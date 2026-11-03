"""Resolve Free daily preparation. All Resolve API calls remain in internal Lua."""
from __future__ import annotations
import json
import os
import re
import shutil
from app.services import quiet_process as subprocess
import sys
import time
import uuid
from datetime import date
from pathlib import Path
from app.core import repository as repo

VERSION = '0.5.0'
SCRIPT = 'FlowStudio_Resolve_Bridge_v0.5.0.lua'
HEARTBEAT_FRESH_SECONDS = 30
IMPORT_DISCONNECT_SECONDS = 45
FPS_VALUES = ('23.976', '24', '25', '29.97', '30', '50', '59.94', '60')
BASE = Path(__file__).resolve().parents[2]


def bridge_root():
    return Path.home() / 'Documents' / 'FlowStudioResolveBridge'


root = bridge_root


def script_dir():
    if sys.platform.startswith('linux'):return Path.home()/'.local/share/DaVinciResolve/Fusion/Scripts/Utility/FlowStudioAuto'
    if os.name == 'nt':
        return Path(os.environ.get('APPDATA', str(Path.home() / 'AppData/Roaming'))) / 'Blackmagic Design/DaVinci Resolve/Support/Fusion/Scripts/Utility/FlowStudioAuto'
    return Path.home() / 'Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/FlowStudioAuto'


def read_pairs(path):
    try:
        return dict(line.split('=', 1) for line in path.read_text(encoding='utf-8').splitlines() if '=' in line)
    except (OSError, UnicodeError):
        return {}


def snapshot(root=None):
    root = root or bridge_root()
    state = read_pairs(root / 'bridge_state.ini')
    try:
        age = time.time() - float(state.get('updated_at', '0'))
        alive = 0 <= age < HEARTBEAT_FRESH_SECONDS and state.get('version') == VERSION and state.get('stage') != 'OFFLINE'
    except ValueError:
        alive = False
    return dict(state, alive=alive, root=str(root))


def heartbeat_age(state):
    try:
        return time.time() - float(state.get('updated_at') or 0)
    except (TypeError, ValueError):
        return 10 ** 9


def atomic_pairs(path, values):
    if os.name == 'nt':
        values = {k:(str(v).replace(chr(92), '/') if isinstance(v, (str, Path)) and len(str(v))>2 and str(v)[1]==':' else v) for k,v in values.items()}
    path.parent.mkdir(parents=True, exist_ok=True)
    for k, v in values.items():
        if any(c in str(v) for c in '\r\n\x00'):
            raise ValueError('任务参数含非法换行：' + k)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(''.join(f'{k}={v}\n' for k, v in values.items()), encoding='utf-8')
    temp.replace(path)


def timeline_name_for_slot(day: str, slot: int = 1) -> str:
    s = max(1, int(slot or 1))
    return f'MAIN-{day}' if s == 1 else f'MAIN-{day}-B{s}'


def slot_from_timeline_name(day: str, timeline_name: str) -> int | None:
    tl = str(timeline_name or '').strip()
    if tl == f'MAIN-{day}':
        return 1
    m = re.fullmatch(rf'MAIN-{re.escape(str(day))}-B(\d+)', tl)
    if m:
        val = int(m.group(1))
        return val if val >= 2 else None
    return None


def is_valid_day_timeline(day: str, timeline_name: str) -> bool:
    return slot_from_timeline_name(day, timeline_name) is not None


def max_timeline_slot(day: str) -> int:
    from app.core import database
    day_s = str(day or '').strip()
    if not day_s:
        return 1
    try:
        saved_max = max(1, int(repo.get_setting(f'davinci_max_slot:{day_s}', '1') or 1))
    except (TypeError, ValueError):
        saved_max = 1
    try:
        active_s = max(1, int(repo.get_setting(f'davinci_active_slot:{day_s}', '1') or 1))
    except (TypeError, ValueError):
        active_s = 1
    hi = max(saved_max, active_s)
    try:
        with database.connect() as con:
            has_tbl = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='davinci_batches'"
            ).fetchone()
            if has_tbl:
                for (tl_name,) in con.execute(
                    'SELECT DISTINCT timeline_name FROM davinci_batches WHERE work_date=?',
                    (day_s,),
                ).fetchall():
                    s = slot_from_timeline_name(day_s, tl_name)
                    if s and s > hi:
                        hi = s
    except Exception:
        pass
    return hi


def active_timeline_slot(day: str) -> int:
    day_s = str(day or '').strip()
    if not day_s:
        return 1
    try:
        slot = max(1, int(repo.get_setting(f'davinci_active_slot:{day_s}', '1') or 1))
    except (TypeError, ValueError):
        slot = 1
    return slot


def active_timeline_name(day: str) -> str:
    return timeline_name_for_slot(day, active_timeline_slot(day))


def set_active_timeline_slot(day: str, slot: int) -> str:
    day_s = str(day or '').strip()
    s = max(1, int(slot or 1))
    cur_max = max_timeline_slot(day_s)
    repo.set_setting(f'davinci_active_slot:{day_s}', str(s))
    if s > cur_max:
        repo.set_setting(f'davinci_max_slot:{day_s}', str(s))
    return timeline_name_for_slot(day_s, s)


def create_next_timeline_slot(day: str) -> tuple[int, str]:
    day_s = str(day or '').strip()
    nxt = max_timeline_slot(day_s) + 1
    tl = set_active_timeline_slot(day_s, nxt)
    return nxt, tl


def list_timeline_slots(day: str) -> list[dict]:
    day_s = str(day or '').strip()
    total = max_timeline_slot(day_s)
    out = []
    for s in range(1, total + 1):
        tl = timeline_name_for_slot(day_s, s)
        label = f'第 {s} 批（主线）' if s == 1 else f'第 {s} 批（B{s}）'
        out.append({'slot': s, 'timeline_name': tl, 'label': label})
    return out


def reconcile_rebuilt_timeline(day, root=None, timeline_name=None):
    """Archive stale attempts once; queue unfinished videos on THAT timeline without touching other timeline slots."""
    from app.core import database
    from app.services import resolve_autoedit as auto
    root = root or bridge_root()
    candidates = []
    if timeline_name:
        candidates.append(root / 'v0_5_0' / ('rebuild_' + str(timeline_name) + '.ini'))
    for slot_info in list_timeline_slots(day):
        p_cand = root / 'v0_5_0' / ('rebuild_' + slot_info['timeline_name'] + '.ini')
        if p_cand not in candidates:
            candidates.append(p_cand)
    legacy_cand = root / 'v0_5_0' / ('rebuild_' + day + '.ini')
    if legacy_cand not in candidates:
        candidates.append(legacy_cand)

    total_reset = 0
    auto.ensure_schema()
    for rpath in candidates:
        receipt = read_pairs(rpath)
        token = receipt.get('rebuild_id', '')
        tl_rebuilt = receipt.get('timeline', '')
        if (
            not token
            or receipt.get('work_date') != day
            or receipt.get('project') != 'FlowStudio-' + day
            or not is_valid_day_timeline(day, tl_rebuilt)
        ):
            continue
        with database.connect() as con:
            con.execute('CREATE TABLE IF NOT EXISTS davinci_rebuild_receipts (rebuild_id TEXT PRIMARY KEY, work_date TEXT NOT NULL, reset_count INTEGER NOT NULL)')
            con.execute('BEGIN IMMEDIATE')
            if con.execute('SELECT 1 FROM davinci_rebuild_receipts WHERE rebuild_id=?', (token,)).fetchone():
                continue
            batches = [
                row[0]
                for row in con.execute(
                    "SELECT batch_id FROM davinci_batches WHERE work_date=? AND timeline_name=? AND status NOT IN ('COMPLETED','PROJECT_REBUILT')",
                    (day, tl_rebuilt),
                )
            ]
            reset = set()
            for bid in batches:
                run = con.execute('SELECT payload_path FROM davinci_autoedit_runs WHERE batch_id=?', (bid,)).fetchone()
                for row in con.execute('SELECT v.id,v.edit_status,v.edit_output_path FROM videos v JOIN davinci_video_state d ON d.video_id=v.id WHERE d.batch_id=?', (bid,)):
                    out = read_pairs(Path(run['payload_path']).parent / ('export_' + str(row['id']) + '.ini')) if run else {}
                    if out.get('status') == 'COMPLETE' and out.get('video_id') == str(row['id']) and out.get('output_path') and Path(out['output_path']).is_file():
                        con.execute("UPDATE videos SET edit_status='已导出',edit_output_path=? WHERE id=?", (out['output_path'], row['id']))
                        continue
                    if row['edit_status'] in ('已导出', '已完成'):
                        continue
                    reset.add(row['id'])
                con.execute("UPDATE davinci_batches SET status='PROJECT_REBUILT',error_message='对应时间线已重建；旧批次保留，未完成视频回到待剪辑' WHERE batch_id=?", (bid,))
                con.execute("UPDATE davinci_autoedit_runs SET status='PROJECT_REBUILT',error_message='对应时间线已重建，禁止复用旧切点' WHERE batch_id=?", (bid,))
                con.execute('UPDATE davinci_video_state SET timeline_imported=0 WHERE batch_id=?', (bid,))
            con.executemany("UPDATE videos SET edit_status='待剪辑' WHERE id=?", [(vid,) for vid in reset])
            con.execute('INSERT INTO davinci_rebuild_receipts VALUES(?,?,?)', (token, day, len(reset)))
            total_reset += len(reset)
    return total_reset


def install_bridge():
    """Install just the new bridge; never quit Resolve or replace legacy scripts."""
    sources = [BASE / 'davinci_autoedit_v0_5_0' / name for name in (SCRIPT, 'FlowStudio_Idle_Monitor.lua', 'FlowStudio_Import_Batch.lua', 'Autoediting_V1.7_FlowStudio.lua', 'FlowStudio_Finish_Batch.lua', 'FlowStudio_Platform.lua')]
    if os.name == 'nt':
        sources.append(BASE / 'scripts/windows_resolve_runtime.py')
    for source in sources:
        if not source.is_file():
            raise RuntimeError('安装文件缺失：' + str(source))
    def destination(source):
        if source.name == 'windows_resolve_runtime.py':
            return bridge_root() / 'runtime' / source.name
        return script_dir() / source.name
    changed = [source for source in sources if not destination(source).is_file() or destination(source).read_bytes()!=source.read_bytes()]
    config = {'python':windows_python().as_posix(), 'helper':(bridge_root()/'runtime/windows_resolve_runtime.py').as_posix()} if os.name == 'nt' else {}
    config_changed = bool(config and read_pairs(script_dir()/'windows-runtime.ini') != config)
    if not changed and not config_changed:
        return False
    script_dir().mkdir(parents=True, exist_ok=True)
    # Install the module first and the calling bridge last.
    for source in reversed(changed):
        dest=destination(source)
        dest.parent.mkdir(parents=True,exist_ok=True)
        temp=dest.with_suffix('.tmp')
        shutil.copyfile(source,temp)
        temp.replace(dest)
    if os.name == 'nt':
        atomic_pairs(script_dir()/'windows-runtime.ini', config)
        # Remove only our former internal helper entry from Resolve's menu.
        (script_dir()/'windows_resolve_runtime.py').unlink(missing_ok=True)
    return True


def _run(args, **kwargs):
    return subprocess.run(args, capture_output=True, text=True, timeout=12, **kwargs)


def grant_foreground():
    """Let the menu helper take focus. Only works while Flow Studio itself is the foreground process."""
    if os.name != 'nt':
        return
    try:
        import ctypes
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        user32.AllowSetForegroundWindow.argtypes = [ctypes.c_ulong]
        user32.AllowSetForegroundWindow(0xFFFFFFFF)
    except Exception:
        return


def windows_python():
    current = Path(sys.executable)
    if os.name != 'nt':
        return current
    sibling = current.with_name('python.exe')
    return sibling if sibling.is_file() else current


def menu_attempt_due(clicked_at, now, offline):
    if offline or clicked_at is None:
        return True
    return now - clicked_at >= 8


def menu_failure_text(detail):
    """Turn a menu-helper failure into a short status line.

    The macOS helper reports ``output`` (for example ``ERR:not_found:undefined``)
    rather than ``error``. Showing that JSON makes the wake button look stuck.
    """
    raw = str(detail or '').strip()
    low = raw.lower()
    if any(token in low for token in ('-1719', '-1743', 'assistive', 'not authorized', 'not allowed', '辅助', '不允许')):
        return raw
    if 'err:not_found:undefined' in low or 'err:missing_target' in low:
        return '唤醒没有拿到要运行的达芬奇脚本名称。请更新 Flow Studio 后再唤醒。'
    if 'err:not_found:' in low:
        return '达芬奇的「工作区 → 脚本」里没有找到 Bridge。请让达芬奇主窗口显示在前台；首次安装后重新打开达芬奇，让脚本菜单刷新后再唤醒。'
    if 'err:no_process' in low:
        return '没有找到正在运行的达芬奇。请先打开 DaVinci Resolve，再点唤醒。'
    if 'workspace_not_found' in low or 'no_menu_bar' in low:
        return '达芬奇菜单栏还没准备好。请让达芬奇主窗口显示在前台，然后重试。'
    if raw.startswith('ERR:'):
        return '唤醒达芬奇失败：' + raw[4:]
    return raw


def interpret_menu_output(stdout, stderr):
    text = ((stdout or '') + ('\n' + stderr if stderr else '')).strip()
    try:
        payload = json.loads(text.splitlines()[-1])
    except (ValueError, IndexError, AttributeError):
        return False, menu_failure_text(text)[-180:]
    if payload.get('ok'):
        return True, ''
    detail = payload.get('error')
    if not detail:
        detail = payload.get('output') or text
    return False, menu_failure_text(str(detail))[-180:]


_LUA_TRACE_PREFIX_RE = re.compile(r'(?:\.\.\.|/)[^\s:]*\.lua:\d+:\s*')


def compact_bridge_detail(raw: str, max_len: int = 92) -> str:
    """Strip noisy Lua file/line prefixes and collapse verbose per-video lists into 1 concise line."""
    text = _LUA_TRACE_PREFIX_RE.sub('', str(raw or '')).strip()
    text = re.sub(r'\s+', ' ', text)
    if 'BATCH_RENDER_INCOMPLETE' in text:
        cancelled_n = len(re.findall(r'\bCancelled\b', text))
        failed_n = len(re.findall(r'\bFailed\b', text))
        m_unconf = re.search(r'(\d+)\s*个未确认', text)
        if m_unconf and (cancelled_n > 0 or failed_n > 0):
            parts = []
            if failed_n > 0:
                parts.append(f'失败 {failed_n} 条')
            if cancelled_n > 0:
                parts.append(f'已取消 {cancelled_n} 条')
            text = f"导出已中断（{'，'.join(parts)}）；已完成成品已保存，可重试导出"
        else:
            text = re.sub(r'^BATCH_RENDER_INCOMPLETE:\s*', '', text)
    if max_len > 12 and len(text) > max_len:
        text = text[: max_len - 1].rstrip('；;，, ') + '…'
    return text


_ACTIVE_LIVE_STAGES = frozenset({
    'IMPORTING', 'AUDIO_RENDERING', 'WHISPER_RUNNING', 'TEXT_ALIGNING',
    'CUTTING', 'CLEANING', 'PREPARING_EXPORT', 'RENDERING',
})


def connection_status_text(state, wake_error=''):
    """Status line for the auto-edit page. A missing whisper path does not block waking Resolve."""
    alive = bool(state.get('alive'))
    if alive and state.get('stage') in _ACTIVE_LIVE_STAGES:
        return compact_bridge_detail(state.get('detail') or 'Bridge 在线')
    error = compact_bridge_detail(str(wake_error or ''))
    whisper = 'whisper.cpp' in str(wake_error or '')
    if error and not (not alive and whisper):
        return '⚠ ' + error
    if alive:
        if state.get('warning'):
            return '⚠ ' + compact_bridge_detail(state['warning'])
        # Suppress stale ERROR detail if the user already manually closed/skipped that batch.
        bid = str(state.get('batch_id') or '').strip()
        if state.get('stage') == 'ERROR' and bid and (bridge_root() / 'v0_5_0' / 'batches' / bid / 'manual_close.ini').is_file():
            tl = state.get('timeline') or ''
            return f'达芬奇已就绪（{tl}）' if tl else 'Bridge 在线'
        return compact_bridge_detail(state.get('detail') or 'Bridge 在线')
    if state.get('version'):
        text = 'Resolve Bridge 连接中断，请重新唤醒；已保留最近状态。'
        if whisper:
            text += '自动剪辑前请在组件管理中检测或安装 whisper.cpp，这不阻止唤醒。'
        return text
    return ('⚠ ' + error) if error else ''


def menu_error(output):
    if any(x in output.lower() for x in ('-1719', '-1743', 'assistive', 'not authorized', 'not allowed', '辅助', '不允许')):
        return '缺少 macOS 辅助功能或自动化权限：请在系统设置 → 隐私与安全性中允许 Flow Studio / Python 控制 DaVinci Resolve。'
    return ''


def normalize_resolve_free_resolution(width: int, height: int) -> tuple[int, int]:
    """Clamp export dimensions proportionally to DaVinci Resolve Free limits (3840x2160 / 2160x3840, even-aligned)."""
    w = max(2, int(round(float(width))))
    h = max(2, int(round(float(height))))
    max_w, max_h = (3840, 2160) if w >= h else (2160, 3840)
    if w > max_w or h > max_h:
        scale = min(max_w / float(w), max_h / float(h))
        w = max(2, int(round(w * scale)))
        h = max(2, int(round(h * scale)))
    w = max(2, (w // 2) * 2)
    h = max(2, (h // 2) * 2)
    return w, h


def _parse_mp4_boxes(f, start: int, end: int):
    import struct
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        hdr = f.read(8)
        if len(hdr) < 8:
            break
        size, box_type = struct.unpack('>I4s', hdr)
        hdr_len = 8
        if size == 1:
            ext = f.read(8)
            if len(ext) < 8:
                break
            size = struct.unpack('>Q', ext)[0]
            hdr_len = 16
        elif size == 0:
            size = end - pos
        if size < hdr_len or pos + size > end:
            break
        yield box_type, pos + hdr_len, pos + size
        pos += size


def probe_video_dimensions(path: str | Path) -> tuple[int, int] | None:
    """Read display (width, height) from an MP4/MOV/M4V video header in <0.2ms, falling back to ffprobe."""
    import struct
    p = Path(str(path or '')).expanduser()
    if not p.is_file():
        return None
    try:
        file_size = p.stat().st_size
        if file_size > 32 and p.suffix.lower() in ('.mp4', '.mov', '.m4v'):
            with p.open('rb') as f:
                for btype, bstart, bend in _parse_mp4_boxes(f, 0, file_size):
                    if btype != b'moov':
                        continue
                    for ttype, tstart, tend in _parse_mp4_boxes(f, bstart, bend):
                        if ttype != b'trak':
                            continue
                        for ctype, cstart, cend in _parse_mp4_boxes(f, tstart, tend):
                            if ctype != b'tkhd':
                                continue
                            f.seek(cstart)
                            tkhd = f.read(min(104, cend - cstart))
                            if len(tkhd) < 84:
                                continue
                            ver = tkhd[0]
                            if ver == 1:
                                if len(tkhd) < 96:
                                    continue
                                mat_off, dim_off = 52, 88
                            else:
                                mat_off, dim_off = 40, 76
                            w_fixed, h_fixed = struct.unpack('>II', tkhd[dim_off:dim_off + 8])
                            w_px = int(round(w_fixed / 65536.0))
                            h_px = int(round(h_fixed / 65536.0))
                            if w_px > 0 and h_px > 0:
                                a, b, _u, c, d = struct.unpack('>iiiii', tkhd[mat_off:mat_off + 20])
                                if a == 0 and d == 0 and (b != 0 or c != 0):
                                    w_px, h_px = h_px, w_px
                                return w_px, h_px
    except Exception:
        pass
    ffprobe_exe = shutil.which('ffprobe')
    if ffprobe_exe:
        try:
            cp = subprocess.run(
                [ffprobe_exe, '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'csv=p=0', str(p)],
                capture_output=True, text=True, timeout=4,
            )
            for line in (cp.stdout or '').splitlines():
                parts = [x.strip() for x in line.split(',') if x.strip().isdigit()]
                if len(parts) >= 2:
                    w_px, h_px = int(parts[0]), int(parts[1])
                    if w_px > 0 and h_px > 0:
                        return w_px, h_px
        except Exception:
            pass
    return None


def resolve_video_export_size(
    host_id: int | None = None,
    seg_paths: list[str | Path] | None = None,
    work_date: str | None = None,
) -> tuple[int, int, str]:
    """Determine (export_width, export_height, aspect_ratio) from actual segment media or host aspect ratio."""
    for sp in seg_paths or ():
        dims = probe_video_dimensions(sp)
        if dims:
            w, h = normalize_resolve_free_resolution(dims[0], dims[1])
            return w, h, ('16:9' if w > h else '9:16')
    if host_id:
        try:
            ar = repo.get_host_aspect_ratio(int(host_id), work_date=work_date)
            if ar == '16:9':
                return 1280, 720, '16:9'
        except Exception:
            pass
    return 720, 1280, '9:16'


class DailyWake:
    def __init__(self, fps='25', root=None, day=None, timeline_name=None):
        self.day = date.fromisoformat(day or date.today().isoformat()).isoformat()
        if str(fps) not in FPS_VALUES:
            raise ValueError('无效时间线帧率，请检查系统设置。')
        self.fps = str(fps)
        self.root = root or bridge_root()
        self.timeline_name = str(timeline_name or active_timeline_name(self.day)).strip()
        if not is_valid_day_timeline(self.day, self.timeline_name):
            self.timeline_name = active_timeline_name(self.day)
        self.stage = 'LAUNCHING'
        self.detail = '正在唤醒达芬奇'
        self.request_id = ''

    def _invoke_bridge_menu(self):
        python = windows_python()
        script = BASE / 'scripts/davinci_run_menu.py'
        if not python.is_file() or not script.is_file():
            return False, '找不到唤醒达芬奇所需的 Python 或菜单脚本。'
        try:
            completed = _run([str(python), str(script), '--script-name', SCRIPT])
        except subprocess.TimeoutExpired:
            return False, '达芬奇菜单响应超时，正在重试。请保持达芬奇主界面可见。'
        except OSError as exc:
            return False, '无法启动达芬奇菜单脚本：' + str(exc)[:160]
        return interpret_menu_output(completed.stdout, completed.stderr)

    def progress(self, stage, detail):
        self.stage, self.detail = stage, detail
        from app.services.app_paths import data_dir
        log_dir = data_dir() / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / 'davinci-workflow.log').open('a', encoding='utf-8') as f:
            f.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")} request={self.request_id} stage={stage} detail={detail}\n')

    def run(self):
        try:
            return self._run()
        except Exception as exc:
            self.progress('ERROR', str(exc))
            raise

    def _run(self):
        if sys.platform not in ('darwin', 'win32'):
            raise RuntimeError('DaVinci 自动化支持 Windows 与 macOS。')
        state = snapshot(self.root)
        heartbeat = self.root / 'bridge_heartbeat.txt'
        if not state['alive'] and state.get('version') != VERSION and heartbeat.exists() and time.time() - heartbeat.stat().st_mtime < HEARTBEAT_FRESH_SECONDS:
            raise RuntimeError('检测到旧版 Resolve Bridge 正在运行。请先停止旧 Bridge；旧版本文件会保留。')
        installed = install_bridge()
        # open -a reuses a running application and brings it to the front.
        from app.services.davinci_workflow import launch_resolve
        launch_resolve()
        if not state['alive']:
            self.progress('BRIDGE_STARTING', '等待达芬奇初始化并启动 Bridge')
            deadline = time.monotonic() + 120
            clicked_at = None
            last_message = ''
            while time.monotonic() < deadline:
                observed = snapshot(self.root)
                if observed['alive']:
                    break
                if menu_attempt_due(clicked_at, time.monotonic(), observed.get('stage') == 'OFFLINE'):
                    grant_foreground()
                    ok, message = self._invoke_bridge_menu()
                    clicked_at = time.monotonic() if ok else None
                    permission = menu_error(message)
                    if permission:
                        raise RuntimeError(permission)
                    if message and message != last_message:
                        self.progress('BRIDGE_STARTING', message)
                        last_message = message
                time.sleep(0.4)
            else:
                hint = '首次安装后，达芬奇可能需要重新打开以刷新脚本菜单。' if installed else ''
                detail = last_message or '请检查 Workspace → Scripts 中的新 Bridge。'
                raise RuntimeError('Resolve Bridge 启动超时。' + hint + detail)
        state = snapshot(self.root)
        if state.get('stage') == 'RENDERING':
            raise RuntimeError('达芬奇当前正在渲染导出（' + compact_bridge_detail(state.get('detail') or 'RENDERING') + '），请等待渲染结束或停止后再操作。')
        if state.get('stage') not in ('IDLE', 'READY', 'ERROR', 'WAITING_USER_REVIEW'):
            raise RuntimeError('Bridge 当前正在执行任务，请等待当前操作结束：' + state.get('stage', ''))
        self.request_id = uuid.uuid4().hex
        day = self.day
        self.progress('PREPARING_PROJECT', f'准备当天项目和时间线 {self.timeline_name}')
        atomic_pairs(self.root / 'v0_5_0/commands' / (self.request_id + '.job'), {
            'action': 'PREPARE_DAILY', 'request_id': self.request_id, 'work_date': day,
            'timeline_name': self.timeline_name,
            'timeline_fps': self.fps, 'whisper_language': str(repo.get_setting('whisper_language', 'sw')).split(' · ')[-1].strip(),
        })
        deadline = time.monotonic() + 60
        last_alive = time.monotonic()
        while time.monotonic() < deadline:
            state = snapshot(self.root)
            if state.get('stage') == 'OFFLINE':
                raise RuntimeError('Resolve Bridge 连接中断，未继续发送任务。')
            if state['alive']:
                last_alive = time.monotonic()
            elif time.monotonic() - last_alive > HEARTBEAT_FRESH_SECONDS:
                raise RuntimeError('Resolve Bridge 连接中断，未继续发送任务。')
            if state.get('request_id') == self.request_id:
                self.stage, self.detail = state.get('stage', ''), state.get('detail', '')
                if self.stage == 'ERROR':
                    raise RuntimeError(self.detail or '准备失败，请查看 Bridge 日志')
                if self.stage == 'READY':
                    if state.get('project') != 'FlowStudio-' + day or state.get('timeline') != self.timeline_name:
                        raise RuntimeError('Bridge 返回的项目或时间线不匹配。')
                    reset = reconcile_rebuilt_timeline(day, self.root, timeline_name=self.timeline_name)
                    self.progress('READY', ('已重建时间线，'+str(reset)+' 个未完成视频已回到待剪辑') if reset else state.get('warning') or f'达芬奇已就绪（{self.timeline_name}）')
                    return state
            time.sleep(0.2)
        raise RuntimeError('准备项目超时，保留任务状态；请查看 Bridge 日志后再唤醒。')
