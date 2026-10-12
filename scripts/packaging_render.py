"""Prepare exact Reels overlays off the UI thread, then invoke local Remotion."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json
import os
import queue
import threading
import time
if sys.stdout:sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr:sys.stderr.reconfigure(encoding='utf-8')
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from app.services.packaging_overlay import prepare_overlays
from app.services.remotion_renderer import RemotionRenderer
from app.services import quiet_process as subprocess
from app.services.app_paths import data_dir

def wait_for_memory(timeout=300, lightweight=False):
    import psutil
    started=time.monotonic()
    while True:
        memory=psutil.virtual_memory()
        required=min((.5 if lightweight else 4)*1024**3,int(memory.total*.15))
        if memory.available>=required:return
        if time.monotonic()-started>=timeout:
            raise RuntimeError('可用内存持续不足，已跳过本项；关闭不需要的软件后可重新渲染。')
        print(f'内存不足，等待释放资源：可用 {memory.available/1024**3:.1f} GB，需要 {required/1024**3:.1f} GB。可点击停止。',flush=True)
        time.sleep(10)

def run_render(command, cwd, idle_timeout=900, duration=None):
    """Bound silent hangs and terminate Chromium/FFmpeg descendants on failure."""
    process = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
    lines = queue.Queue()
    def read():
        try:
            for line in process.stdout: lines.put(line)
        finally: lines.put(None)
    reader = threading.Thread(target=read, daemon=True); reader.start()
    last_output = time.monotonic()
    try:
        while True:
            try: line = lines.get(timeout=1)
            except queue.Empty:
                if time.monotonic()-last_output > idle_timeout:
                    raise RuntimeError('渲染长时间没有进度输出，已终止卡住的任务（默认 15 分钟）。')
                continue
            if line is None: return process.wait(timeout=30)
            last_output = time.monotonic()
            if duration and line.startswith('out_time_us='):
                try:print(f'渲染进度 {max(0,min(99,int(float(line.split("=",1)[1])/1e6/duration*100)))}%',flush=True)
                except ValueError:pass
            elif not duration or '=' not in line:print(line, end='', flush=True)
    finally:
        if process.poll() is None:
            import psutil
            try:
                for child in psutil.Process(process.pid).children(recursive=True):
                    try: child.kill()
                    except psutil.Error: pass
            except psutil.Error: pass
            process.kill(); process.wait(timeout=10)
        reader.join(timeout=2)
        process.stdout.close()


def main():
    from app.services.bundled_components import restore
    try:
        import psutil
        psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if os.name=='nt' else 10)
    except Exception: pass
    app=QApplication([])
    job_path=Path(sys.argv[1])
    try:
        job=json.loads(job_path.read_text(encoding='utf-8'))
        from app.services.packaging_ffmpeg import compatibility_reason,encoder_args,build_command
        from app.services.packaging_media import find_ffmpeg,probe_media
        mode=job['payload'].get('renderMode','自动（优先 FFmpeg）')
        reason=compatibility_reason(job['payload'])
        restore(('ffmpeg-libs',) if mode!='Remotion 兼容' and not reason else ('ffmpeg-libs','node','remotion'))
        from app.services.packaging_ffmpeg import resolve_duration
        resolve_duration(job['payload'])
        if mode!='Remotion 兼容' and not reason:
            import tempfile
            wait_for_memory(lightweight=True)
            output=Path(job['output']);output.parent.mkdir(parents=True,exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='flowstudio-render-') as folder:
                encoding,label=encoder_args(find_ffmpeg(job['payload'].get('ffmpeg','')),job['payload'].get('codec','h264'),mode!='FFmpeg CPU')
                print('渲染方式：FFmpeg · '+label,flush=True)
                command,duration=build_command(job['payload'],str(output),Path(folder),encoding,job.get('preview_frame'))
                code=run_render(command,folder,duration=duration)
                if code and label.startswith('NVIDIA'):
                    print('硬件编码未完成，改用 CPU 高画质重试本项。',flush=True)
                    encoding,_=encoder_args(find_ffmpeg(job['payload'].get('ffmpeg','')),job['payload'].get('codec','h264'),False)
                    command,duration=build_command(job['payload'],str(output),Path(folder),encoding,job.get('preview_frame'))
                    code=run_render(command,folder,duration=duration)
                return code
        if mode.startswith('FFmpeg') and reason:
            raise ValueError('此效果需要兼容模式：'+reason+'。请选自动或 Remotion 兼容。')
        print('渲染方式：Remotion 兼容 · '+(reason or '手动选择'),flush=True)
        wait_for_memory()
        payload=prepare_overlays(job['payload'],data_dir()/'packaging/overlays')
        payload['_reels_prepared']=True
        command,cwd=RemotionRenderer(job['project']).render_flowstudio_command(payload,job['output'],job.get('preview_frame'))
        return run_render(command,cwd)
    finally:
        job_path.unlink(missing_ok=True)

if __name__=='__main__':
    try:sys.exit(main())
    except Exception as exc:
        print('包装失败：'+str(exc),flush=True);sys.exit(1)
