"""Resolve Free daily preparation. All Resolve API calls remain in internal Lua."""
from __future__ import annotations
import json
import os
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
FPS_VALUES = ('23.976', '24', '25', '29.97', '30', '50', '59.94', '60')
BASE = Path(__file__).resolve().parents[2]


def bridge_root():
    return Path.home() / 'Documents' / 'FlowStudioResolveBridge'


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
        alive = 0 <= age < 8 and state.get('version') == VERSION and state.get('stage') != 'OFFLINE'
    except ValueError:
        alive = False
    return dict(state, alive=alive, root=str(root))


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


def reconcile_rebuilt_timeline(day, root=None):
    """Archive stale attempts once; queue unfinished videos without deleting history."""
    from app.core import database
    from app.services import resolve_autoedit as auto
    root = root or bridge_root()
    receipt = read_pairs(root / 'v0_5_0' / ('rebuild_' + day + '.ini'))
    token = receipt.get('rebuild_id', '')
    if not token or receipt.get('work_date') != day or receipt.get('project') != 'FlowStudio-' + day or receipt.get('timeline') != 'MAIN-' + day:
        return 0
    auto.ensure_schema()
    with database.connect() as con:
        con.execute('CREATE TABLE IF NOT EXISTS davinci_rebuild_receipts (rebuild_id TEXT PRIMARY KEY, work_date TEXT NOT NULL, reset_count INTEGER NOT NULL)')
        con.execute('BEGIN IMMEDIATE')
        if con.execute('SELECT 1 FROM davinci_rebuild_receipts WHERE rebuild_id=?',(token,)).fetchone():
            return 0
        batches=[row[0] for row in con.execute("SELECT batch_id FROM davinci_batches WHERE work_date=? AND status NOT IN ('COMPLETED','PROJECT_REBUILT')",(day,))]
        reset=set()
        for bid in batches:
            run=con.execute('SELECT payload_path FROM davinci_autoedit_runs WHERE batch_id=?',(bid,)).fetchone()
            for row in con.execute('SELECT v.id,v.edit_status,v.edit_output_path FROM videos v JOIN davinci_video_state d ON d.video_id=v.id WHERE d.batch_id=?',(bid,)):
                # Preserve confirmed success; an arbitrary leftover file is not a completion receipt.
                out=read_pairs(Path(run['payload_path']).parent / ('export_'+str(row['id'])+'.ini')) if run else {}
                if out.get('status')=='COMPLETE' and out.get('video_id')==str(row['id']) and out.get('output_path') and Path(out['output_path']).is_file():
                    con.execute("UPDATE videos SET edit_status='已导出',edit_output_path=? WHERE id=?",(out['output_path'],row['id']))
                    continue
                if row['edit_status'] in ('已导出','已完成'):
                    continue
                reset.add(row['id'])
            con.execute("UPDATE davinci_batches SET status='PROJECT_REBUILT',error_message='对应时间线已重建；旧批次保留，未完成视频回到待剪辑' WHERE batch_id=?",(bid,))
            con.execute("UPDATE davinci_autoedit_runs SET status='PROJECT_REBUILT',error_message='对应时间线已重建，禁止复用旧切点' WHERE batch_id=?",(bid,))
            con.execute('UPDATE davinci_video_state SET timeline_imported=0 WHERE batch_id=?',(bid,))
        con.executemany("UPDATE videos SET edit_status='待剪辑' WHERE id=?",[(vid,) for vid in reset])
        con.execute('INSERT INTO davinci_rebuild_receipts VALUES(?,?,?)',(token,day,len(reset)))
    return len(reset)


def install_bridge():
    """Install just the new bridge; never quit Resolve or replace legacy scripts."""
    sources = [BASE / 'davinci_autoedit_v0_5_0' / name for name in (SCRIPT, 'FlowStudio_Import_Batch.lua', 'Autoediting_V1.7_FlowStudio.lua', 'FlowStudio_Finish_Batch.lua', 'FlowStudio_Platform.lua')]
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
    config = {'python':Path(sys.executable).with_name('python.exe').as_posix(), 'helper':(bridge_root()/'runtime/windows_resolve_runtime.py').as_posix()} if os.name == 'nt' else {}
    config_changed = bool(config and read_pairs(script_dir()/'windows-runtime.ini') != config)
    if not changed and not config_changed:
        return False
    if snapshot().get('alive'):
        raise RuntimeError('新版 Bridge 正在运行，请先停止 Bridge，再更新。')
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
    return subprocess.run(args, capture_output=True, text=True, timeout=15, **kwargs)


def menu_error(output):
    if any(x in output.lower() for x in ('-1719', '-1743', 'assistive', 'not authorized', 'not allowed', '辅助', '不允许')):
        return '缺少 macOS 辅助功能或自动化权限：请在系统设置 → 隐私与安全性中允许 Flow Studio / Python 控制 DaVinci Resolve。'
    return ''


class DailyWake:
    def __init__(self, fps='25', root=None, day=None):
        self.day = date.fromisoformat(day or date.today().isoformat()).isoformat()
        if str(fps) not in FPS_VALUES:
            raise ValueError('无效时间线帧率，请检查系统设置。')
        self.fps = str(fps)
        self.root = root or bridge_root()
        self.stage = 'LAUNCHING'
        self.detail = '正在唤醒达芬奇'
        self.request_id = ''

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
        if not state['alive'] and state.get('version') != VERSION and heartbeat.exists() and time.time() - heartbeat.stat().st_mtime < 8:
            raise RuntimeError('检测到旧版 Resolve Bridge 正在运行。请先停止旧 Bridge；旧版本文件会保留。')
        installed = install_bridge()
        # open -a reuses a running application and brings it to the front.
        from app.services.davinci_workflow import launch_resolve
        launch_resolve()
        if not state['alive']:
            self.progress('BRIDGE_STARTING', '等待达芬奇初始化并启动 Bridge')
            deadline = time.monotonic() + 120
            clicked = False
            last = ''
            while time.monotonic() < deadline:
                observed = snapshot(self.root)
                if observed['alive']:
                    break
                if observed.get('stage') == 'OFFLINE':
                    clicked = False
                if not clicked:
                    p = _run([str(Path(sys.executable).with_name('python.exe')) if os.name == 'nt' else sys.executable, str(BASE / 'scripts/davinci_run_menu.py'), '--script-name', SCRIPT])
                    last = p.stdout + p.stderr
                    permission = menu_error(last)
                    if permission:
                        raise RuntimeError(permission)
                    try:
                        clicked = json.loads(p.stdout.strip().splitlines()[-1]).get('ok', False)
                    except (ValueError, IndexError):
                        clicked = False
                time.sleep(1)
            else:
                hint = '首次安装后，达芬奇可能需要重新打开以刷新脚本菜单。' if installed else ''
                raise RuntimeError('Resolve Bridge 启动超时。' + hint + '请检查 Workspace → Scripts 中的新 Bridge。' + last[-250:])
        state = snapshot(self.root)
        if state.get('stage') not in ('IDLE', 'READY', 'ERROR', 'WAITING_USER_REVIEW'):
            raise RuntimeError('Bridge 当前正在执行任务，请等待当前操作结束：' + state.get('stage', ''))
        self.request_id = uuid.uuid4().hex
        self.progress('PREPARING_PROJECT', '准备当天项目和主时间线')
        day = self.day
        atomic_pairs(self.root / 'v0_5_0/commands' / (self.request_id + '.job'), {
            'action': 'PREPARE_DAILY', 'request_id': self.request_id, 'work_date': day,
            'timeline_fps': self.fps, 'whisper_language': str(repo.get_setting('whisper_language', 'sw')).split(' · ')[-1].strip(),
        })
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            state = snapshot(self.root)
            if not state['alive']:
                raise RuntimeError('Resolve Bridge 连接中断，未继续发送任务。')
            if state.get('request_id') == self.request_id:
                self.stage, self.detail = state.get('stage', ''), state.get('detail', '')
                if self.stage == 'ERROR':
                    raise RuntimeError(self.detail or '准备失败，请查看 Bridge 日志')
                if self.stage == 'READY':
                    if state.get('project') != 'FlowStudio-' + day or state.get('timeline') != 'MAIN-' + day:
                        raise RuntimeError('Bridge 返回的项目或时间线不匹配。')
                    reset=reconcile_rebuilt_timeline(day,self.root)
                    self.progress('READY', ('已重建时间线，'+str(reset)+' 个未完成视频已回到待剪辑') if reset else state.get('warning') or '达芬奇已就绪')
                    return state
            time.sleep(0.5)
        raise RuntimeError('准备项目超时，保留任务状态；请查看 Bridge 日志后再唤醒。')
