"""Byte-bounded thumbnail cache; full-resolution originals remain on disk."""
from collections import OrderedDict
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap, QImageReader
from app.services.image_assets import image_cache_key, ImageAssetError, _macos_sips_decode, MAX_BYTES

_cache = OrderedDict()
_cache_bytes = 0
_CACHE_BYTES = 24 * 1024 * 1024
_CACHE_ITEMS = 96


def _thumbnail(value, size):
    global _cache_bytes
    revision = image_cache_key(value)
    if revision[1] is None:
        raise ImageAssetError('图片不存在或无法读取：' + str(value))
    if revision[2] > MAX_BYTES:
        raise ImageAssetError('图片文件超过 30 MB')
    width, height = max(1, min(size.width(), 1024)), max(1, min(size.height(), 1024))
    key = (*revision, width, height)
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
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
    cost = image.sizeInBytes()
    while _cache and (_cache_bytes + cost > _CACHE_BYTES or len(_cache) >= _CACHE_ITEMS):
        _, old = _cache.popitem(last=False)
        _cache_bytes -= old.sizeInBytes()
    _cache[key] = image
    _cache_bytes += cost
    return image


def set_image(label, value, size=None):
    try:
        pix = QPixmap.fromImage(_thumbnail(value, size or label.size()))
        label.setToolTip(str(value))
        label.setPixmap(pix)
        return True
    except ImageAssetError as exc:
        label.clear(); label.setText('图片加载失败' if value else '无参考图'); label.setToolTip(str(exc))
        return False


def load_pixmap(value):
    try:return QPixmap.fromImage(_thumbnail(value, QSize(256,256)))
    except ImageAssetError:return QPixmap()
