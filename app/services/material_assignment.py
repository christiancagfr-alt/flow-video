"""Stable, same-eye-state reference assignments and picture-folder resolution."""
from pathlib import Path
import random


def material_folder(raw):
    folder = Path(raw).expanduser()
    pictures = folder / '素材'
    return pictures if pictures.is_dir() else folder


def image_mode(path, recorded=None, default='TALKING'):
    name = Path(path).stem
    if '闭眼' in name: return 'PRAYING'
    if '睁眼' in name: return 'TALKING'
    return recorded if recorded in ('PRAYING', 'TALKING') else default


def assign(tasks, files, modes, previous, random_fill=False):
    """Use each available image once first; reuse only on explicit request."""
    assigned, used = {}, set()
    for task in tasks:
        path = previous.get(task['id'])
        if path in files and modes[path] == task.get('mode', 'TALKING'):
            assigned[task['id']] = path
            used.add(path)
    for task in tasks:
        if task['id'] in assigned: continue
        pool = [p for p in files if modes[p] == task.get('mode', 'TALKING')]
        fresh = [p for p in pool if p not in used]
        path = fresh[0] if fresh else (random.choice(pool) if random_fill and pool else None)
        if path is not None:
            assigned[task['id']] = path
            used.add(path)
    return assigned


def reference_tasks(tasks, modes):
    # With only prayer pictures, TALKING needs a derived open-eye image in Flow.
    # The original binding still belongs to the PRAYING pool and is never relabelled.
    available = set(modes.values())
    return [{**t, 'mode': 'PRAYING' if t.get('mode') == 'TALKING' and
             'TALKING' not in available and 'PRAYING' in available else t.get('mode','TALKING')}
            for t in tasks]
