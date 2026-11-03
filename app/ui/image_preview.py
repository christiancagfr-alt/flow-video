"""Byte-bounded thumbnail cache with persistent SSD thumb store and async label loader."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
import threading
from PySide6.QtCore import Qt, QSize, QObject, Signal
from PySide6.QtGui import QPixmap, QImage, QImageReader
from shiboken6 import isValid as _qt_is_valid
from app.core import database
from app.services.image_assets import image_cache_key, ImageAssetError, _macos_sips_decode, MAX_BYTES

_cache = OrderedDict()
_fast_key_map = {}
_cache_bytes = 0
_CACHE_BYTES = 24 * 1024 * 1024
_CACHE_ITEMS = 128
_CACHE_LOCK = threading.RLock()
_THUMB_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="fs-thumb")
_REQ_SEQ = 0
_REQ_LOCK = threading.Lock()


def _next_req_id() -> int:
    global _REQ_SEQ
    with _REQ_LOCK:
        _REQ_SEQ += 1
        return _REQ_SEQ


def _disk_thumb_path(path_str: str, mtime_ns: int, file_size: int, width: int, height: int):
    cache_dir = database.DB_PATH.parent / "image_cache" / "thumbs"
    token = hashlib.sha1(
        f"{path_str}|{mtime_ns}|{file_size}|{width}x{height}".encode("utf-8", "surrogatepass")
    ).hexdigest()[:28]
    return cache_dir, token


def _load_disk_thumb(path_str: str, mtime_ns: int, file_size: int, width: int, height: int):
    try:
        cache_dir, token = _disk_thumb_path(path_str, mtime_ns, file_size, width, height)
        for ext in (".jpg", ".png"):
            p = cache_dir / f"{token}{ext}"
            if p.is_file():
                img = QImage(str(p))
                if not img.isNull():
                    return img
    except Exception:
        pass
    return None


def _save_disk_thumb(image: QImage, path_str: str, mtime_ns: int, file_size: int, width: int, height: int):
    try:
        cache_dir, token = _disk_thumb_path(path_str, mtime_ns, file_size, width, height)
        cache_dir.mkdir(parents=True, exist_ok=True)
        has_alpha = image.hasAlphaChannel()
        ext = ".png" if has_alpha else ".jpg"
        fmt = "PNG" if has_alpha else "JPEG"
        qual = -1 if has_alpha else 88
        target = cache_dir / f"{token}{ext}"
        if target.is_file():
            return
        tmp = cache_dir / f".{token}.{os.urandom(4).hex()}{ext}"
        if image.save(str(tmp), fmt, qual):
            tmp.replace(target)
        else:
            tmp.unlink(missing_ok=True)
    except Exception:
        pass


def _store_in_memory(key, raw_key, image: QImage):
    global _cache_bytes
    cost = image.sizeInBytes()
    with _CACHE_LOCK:
        if key in _cache:
            _cache.move_to_end(key)
            if raw_key is not None:
                _fast_key_map[raw_key] = key
            return _cache[key]
        while _cache and (_cache_bytes + cost > _CACHE_BYTES or len(_cache) >= _CACHE_ITEMS):
            old_key, old = _cache.popitem(last=False)
            _cache_bytes -= old.sizeInBytes()
        _cache[key] = image
        _cache_bytes += cost
        if raw_key is not None:
            if len(_fast_key_map) > 512:
                _fast_key_map.clear()
            _fast_key_map[raw_key] = key
        return image


def _thumbnail(value, size, raw_key=None):
    revision = image_cache_key(value)
    if revision[1] is None:
        raise ImageAssetError('图片不存在或无法读取：' + str(value))
    if revision[2] > MAX_BYTES:
        raise ImageAssetError('图片文件超过 30 MB')
    width, height = max(1, min(size.width(), 1024)), max(1, min(size.height(), 1024))
    key = (*revision, width, height)
    with _CACHE_LOCK:
        if key in _cache:
            _cache.move_to_end(key)
            if raw_key is not None:
                _fast_key_map[raw_key] = key
            return _cache[key]
    cached_disk = _load_disk_thumb(revision[0], revision[1], revision[2], width, height)
    if cached_disk is not None:
        return _store_in_memory(key, raw_key, cached_disk)
    reader = QImageReader(revision[0])
    reader.setDecideFormatFromContent(True)
    reader.setAutoTransform(True)
    original = reader.size()
    if original.isValid():
        # A square decode target also accommodates EXIF axis rotation.
        reader.setScaledSize(original.scaled(QSize(max(width,height), max(width,height)), Qt.KeepAspectRatio))
    image = reader.read()
    if image.isNull():
        image = _macos_sips_decode(*revision)
        if image is None:
            raise ImageAssetError('图片损坏或格式不受支持：' + revision[0])
    image = image.scaled(QSize(width,height), Qt.KeepAspectRatio, Qt.SmoothTransformation)
    _save_disk_thumb(image, revision[0], revision[1], revision[2], width, height)
    return _store_in_memory(key, raw_key, image)


class _AsyncThumbBridge(QObject):
    ready = Signal(object, int, object, str, str)

    def __init__(self):
        super().__init__()
        self.ready.connect(self._apply)

    def _apply(self, label, req_id: int, image, err_text: str, tooltip: str):
        try:
            if label is None or not _qt_is_valid(label):
                return
            if label.property("_img_req_id") != req_id:
                return
            if image is not None and not image.isNull():
                label.setToolTip(tooltip)
                label.setPixmap(QPixmap.fromImage(image))
            else:
                label.clear()
                label.setText(err_text)
                label.setToolTip(tooltip)
        except RuntimeError:
            pass


_BRIDGE = None


def _get_bridge() -> _AsyncThumbBridge:
    global _BRIDGE
    if _BRIDGE is None:
        _BRIDGE = _AsyncThumbBridge()
    return _BRIDGE


def set_image(label, value, size=None):
    req_id = _next_req_id()
    label.setProperty("_img_req_id", req_id)
    target = size or label.size()
    width, height = max(1, min(target.width(), 1024)), max(1, min(target.height(), 1024))
    raw_key = (str(value or ""), width, height)
    try:
        pix = QPixmap.fromImage(_thumbnail(value, QSize(width, height), raw_key=raw_key))
        label.setToolTip(str(value))
        label.setPixmap(pix)
        return True
    except ImageAssetError as exc:
        label.clear(); label.setText('图片加载失败' if value else '无参考图'); label.setToolTip(str(exc))
        return False


def set_image_async(label, value, size=None):
    """Non-blocking thumbnail setter for card grids (zero main-thread disk I/O on cold cache)."""
    req_id = _next_req_id()
    label.setProperty("_img_req_id", req_id)
    if not str(value or "").strip():
        label.clear()
        label.setText('无参考图')
        label.setToolTip('未指定参考图片，请先选择图片')
        return
    target = size or label.size()
    width = max(1, min(target.width() or 180, 1024))
    height = max(1, min(target.height() or 110, 1024))
    raw_key = (str(value), width, height)
    with _CACHE_LOCK:
        mem_key = _fast_key_map.get(raw_key)
        if mem_key is not None and mem_key in _cache:
            _cache.move_to_end(mem_key)
            img = _cache[mem_key]
            label.setToolTip(str(value))
            label.setPixmap(QPixmap.fromImage(img))
            return
    bridge = _get_bridge()
    box = QSize(width, height)
    val_str = str(value)

    def _work():
        try:
            img = _thumbnail(val_str, box, raw_key=raw_key)
            bridge.ready.emit(label, req_id, img, "", val_str)
        except ImageAssetError as exc:
            bridge.ready.emit(label, req_id, None, "图片加载失败" if val_str else "无参考图", str(exc))
        except Exception as exc:
            bridge.ready.emit(label, req_id, None, "图片加载失败", str(exc))

    _THUMB_POOL.submit(_work)


def load_pixmap(value):
    try:return QPixmap.fromImage(_thumbnail(value, QSize(256,256)))
    except ImageAssetError:return QPixmap()
