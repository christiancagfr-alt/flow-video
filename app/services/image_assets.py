"""One byte-validated asset resolver shared by Qt previews and GPT requests."""
from dataclasses import dataclass
from pathlib import Path
from functools import lru_cache
import base64
import hashlib
import logging
import os
import shutil
from app.services import quiet_process as subprocess
import sys
import urllib.parse
import urllib.request
from PySide6.QtCore import QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QImageReader, QImage
from app.core import database

log = logging.getLogger('flowstudio.image_assets')
MAX_BYTES = 30 * 1024 * 1024

class ImageAssetError(ValueError):
    pass

@dataclass(frozen=True)
class ImageAsset:
    path: Path
    mime: str
    data: bytes
    source_size: int
    def data_url(self):
        return 'data:' + self.mime + ';base64,' + base64.b64encode(self.data).decode('ascii')

def resolve_path(value):
    raw = str(value or '').strip()
    if not raw:
        raise ImageAssetError('未指定参考图片，请先选择图片')
    url = urllib.parse.urlsplit(raw)
    root = database.APP_ROOT
    if url.scheme in ('http','https'):
        cache = database.DB_PATH.parent / 'image_cache'
        cache.mkdir(parents=True, exist_ok=True)
        target = cache / hashlib.sha256(raw.encode()).hexdigest()
        if not target.is_file():
            try:
                from app.services.public_download import download
                data=download(urllib.parse.urlunsplit((url.scheme,url.netloc,urllib.parse.quote(url.path,safe='/%:@'),urllib.parse.quote(url.query,safe='=&%/:?@+'),'')), MAX_BYTES)
                if len(data)>MAX_BYTES:raise ImageAssetError('图片文件超过 30 MB')
                temp=target.with_suffix('.'+os.urandom(6).hex()+'.tmp')
                temp.write_bytes(data);temp.replace(target)
            except Exception as exc:
                raise ImageAssetError('图片 URL 下载失败，请检查链接或重新导入本地图片') from exc
        return target.resolve()
    if url.scheme == 'file':
        if url.netloc not in ('','localhost'):
            raise ImageAssetError('不支持远程 file 主机，请导入本地图片')
        raw=urllib.parse.unquote(url.path)
    path=Path(raw).expanduser()
    candidates=[path] if path.is_absolute() else [root/path,database.DB_PATH.parent/path]
    if not path.is_absolute():candidates.append(Path.cwd()/path)
    # Recover app-local data paths after moving a version directory. Never guess by basename.
    if path.is_absolute() and not path.is_file() and 'data' in path.parts:
        i=path.parts.index('data');candidates.append(database.DB_PATH.parent.joinpath(*path.parts[i+1:]))
    for candidate in candidates:
        if candidate.is_file():return candidate.resolve()
    # Finder renames and material moves preserve an explicit alias, never a
    # speculative filename match that could select the wrong person's picture.
    import sqlite3
    index=database.DB_PATH.parent/'pre_gpt_pipeline.sqlite3'
    if index.is_file():
        with sqlite3.connect(index.resolve().as_uri()+'?mode=ro',uri=True) as con:
            if con.execute("SELECT 1 FROM sqlite_master WHERE name='image_path_aliases'").fetchone():
                current=str(candidates[0].absolute());seen=set()
                while current not in seen:
                    seen.add(current);row=con.execute('SELECT new_path FROM image_path_aliases WHERE old_path=?',(current,)).fetchone()
                    if not row:break
                    current=row[0]
                    if Path(current).is_file():return Path(current).resolve()
    raise ImageAssetError('图片不存在或无法读取：'+str(candidates[0].absolute()))

def _macos_sips_decode(path: str, mtime_ns: int, size: int):
    """Fallback decoder for macOS formats that Qt may not have a plugin for.

    `sips` is part of macOS.  The conversion is cached outside the source folder and
    never modifies the user's original image.  This same decoded result is used by
    previews and GPT image requests, so a format fallback cannot diverge between UI
    and API submission.
    """
    if sys.platform != 'darwin':
        return None
    sips = shutil.which('sips')
    if not sips:
        return None
    cache = database.DB_PATH.parent / 'image_cache' / 'decoded'
    cache.mkdir(parents=True, exist_ok=True)
    token = hashlib.sha256(f'{Path(path).resolve()}|{mtime_ns}|{size}'.encode('utf-8')).hexdigest()[:24]
    target = cache / f'{token}.png'
    if not target.is_file():
        temp = target.with_suffix('.tmp.png')
        try:
            result = subprocess.run(
                [sips, '-s', 'format', 'png', str(path), '--out', str(temp)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, check=False,
            )
            if result.returncode != 0 or not temp.is_file():
                temp.unlink(missing_ok=True)
                return None
            temp.replace(target)
        except Exception:
            temp.unlink(missing_ok=True)
            return None
    data = target.read_bytes()
    image = QImage.fromData(data, 'PNG')
    return image if not image.isNull() else None


@lru_cache(maxsize=0)
def _decode(path, mtime_ns, size):
    if size>MAX_BYTES:raise ImageAssetError('图片文件超过 30 MB')
    data=Path(path).read_bytes()
    buf=QBuffer();buf.setData(QByteArray(data));buf.open(QIODevice.ReadOnly)
    reader=QImageReader(buf);reader.setDecideFormatFromContent(True);reader.setAutoTransform(True)
    image=reader.read()
    fmt=bytes(reader.format()).decode('ascii','replace').lower()
    if image.isNull():
        qt_error=reader.errorString()
        image=_macos_sips_decode(path,mtime_ns,size)
        if image is None:
            raise ImageAssetError('图片损坏或格式不受支持：'+path+' ('+qt_error+')')
        fmt=(Path(path).suffix.lower().lstrip('.') or 'macos')+'-via-sips'
    # Re-encode decoded pixels: fixes orientation and strips metadata.  If Qt lacks
    # a decoder for a macOS-native format, the sips fallback above supplies pixels.
    output=QByteArray();out=QBuffer(output);out.open(QIODevice.WriteOnly)
    kind='PNG' if image.hasAlphaChannel() else 'JPEG'
    if not image.save(out,kind,92):raise ImageAssetError('图片转换失败：'+path)
    return ('image/png' if kind=='PNG' else 'image/jpeg'),bytes(output),fmt

def resolve_image_asset(value, task_id=''):
    path=None
    try:
        path=resolve_path(value);stat=path.stat()
        mime,data,fmt=_decode(str(path),stat.st_mtime_ns,stat.st_size)
        log.info('[IMAGE_READY] task=%s path=%s exists=true source_format=%s mime=%s source_bytes=%d encoded_bytes=%d encoding=ok',task_id,path,fmt,mime,stat.st_size,len(data))
        return ImageAsset(path,mime,data,stat.st_size)
    except Exception as exc:
        log.error('[IMAGE_ERROR] task=%s asset=%s path=%s exists=%s encoding=failed request_contains_image=false error=%s',task_id,hashlib.sha256(str(value).encode()).hexdigest()[:16],path or '<unresolved>',bool(path and path.is_file()),type(exc).__name__)
        if isinstance(exc,ImageAssetError):raise
        raise ImageAssetError('图片无法读取：'+str(path or '<未解析>')) from exc

def image_cache_key(value):
    try:
        path=resolve_path(value);st=path.stat();return str(path),st.st_mtime_ns,st.st_size
    except ImageAssetError:return str(value),None,None

def read_image(value):
    asset=resolve_image_asset(value)
    return QImage.fromData(asset.data)
