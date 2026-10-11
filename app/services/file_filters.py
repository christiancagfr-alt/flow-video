"""Local image-file filtering shared by Flow Studio image scanners.

Ignore macOS AppleDouble/resource-fork metadata and other hidden filesystem
artifacts before they can enter task matching, closed-eye classification,
previews, GPT requests, or Flow upload queues.
"""
from pathlib import Path

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.heic', '.heif', '.bmp', '.tif', '.tiff'}


def is_ignored_system_path(value) -> bool:
    path = Path(value)
    # AppleDouble resource-fork sidecars such as ._闭眼5.png are not images.
    # __MACOSX is created by macOS zip tooling; .DS_Store and any dot-file
    # should never be treated as production media.
    for part in path.parts:
        if part == '__MACOSX' or part == '.DS_Store' or part.startswith('._'):
            return True
    return bool(path.name.startswith('.'))


def is_valid_local_image(value, require_file: bool = True) -> bool:
    path = Path(value)
    if is_ignored_system_path(path):
        return False
    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        return False
    if require_file and (not path.is_file() or path.is_symlink()):
        return False
    return True
