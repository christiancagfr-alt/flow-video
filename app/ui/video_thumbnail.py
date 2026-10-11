"""Bounded asynchronous video thumbnails; video playback is never blocked by extraction."""
import hashlib,logging,shutil
from app.services import quiet_process as subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from PySide6.QtCore import Qt,QSize,QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QToolButton
from app.core import database
from app.ui.image_preview import load_pixmap

_pool=ThreadPoolExecutor(max_workers=2,thread_name_prefix='qc-thumbnail')
log=logging.getLogger('flowstudio.video_thumbnail')

@lru_cache(maxsize=200)
def _frame(path,mtime,size):
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg:raise ValueError('未安装 ffmpeg，显示参考图')
    root=database.DB_PATH.parent/'video_thumbnails';root.mkdir(parents=True,exist_ok=True)
    dest=root/(hashlib.sha256(f'{path}:{mtime}:{size}'.encode()).hexdigest()+'.jpg')
    if not dest.is_file():
        result=subprocess.run([ffmpeg,'-v','error','-y','-i',path,'-frames:v','1','-vf','scale=96:160:force_original_aspect_ratio=decrease',str(dest)],capture_output=True,timeout=10)
        if result.returncode or not dest.is_file():raise ValueError('视频缩略图提取失败')
    return str(dest)

class VideoThumbnailButton(QToolButton):
    def __init__(self,text,path,reference,parent=None):
        super().__init__(parent);self.setText(text);self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon);self.setIconSize(QSize(64,80));self.setMinimumSize(68,110)
        pix=load_pixmap(reference) if reference else None
        if pix and not pix.isNull():self.setIcon(QIcon(pix));self.setToolTip('当前显示参考图；点击播放视频')
        else:self.setToolTip('缩略图不可用；点击播放视频')
        self._future=None
        try:
            p=Path(path).expanduser().resolve();st=p.stat()
            if not shutil.which('ffmpeg'):return
            self._future=_pool.submit(_frame,str(p),st.st_mtime_ns,st.st_size)
            self._timer=QTimer(self);self._timer.setInterval(150);self._timer.timeout.connect(self._poll);self._timer.start()
        except OSError:log.warning('[VIDEO_THUMBNAIL] path=%s exists=false; reference fallback',path)
    def _poll(self):
        if not self._future.done():return
        self._timer.stop()
        try:
            path=self._future.result();pix=load_pixmap(path)
            if pix.isNull():raise ValueError('缩略图无法显示')
            self.setIcon(QIcon(pix));self.setToolTip('视频首帧；点击播放视频')
        except Exception as exc:log.warning('[VIDEO_THUMBNAIL] %s',type(exc).__name__)
        finally:self._future=None
