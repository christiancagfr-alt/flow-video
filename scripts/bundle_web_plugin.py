"""Copy the revised 0.9.66 extension as loose files.

Later plugin updates replace these files in place and reload the extension.
Tests, backups and notes are not part of the packaged extension.
"""
import shutil
from pathlib import Path

PLUGIN_REL = Path("extension/FlowStudio_Web_Plugin_v0.9.66_FLOW_SUBMIT_HITTEST_FIX")
RUNTIME_SUFFIXES = {".js", ".css", ".json", ".html", ".png", ".svg", ".woff", ".woff2"}


def iter_plugin_files(root):
    base = Path(root) / PLUGIN_REL
    if not (base / "manifest.json").is_file():
        raise FileNotFoundError(base)
    found = False
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(base)
        if any(part == "tests" or part.startswith("TEST_RESULTS") for part in relative.parts):
            continue
        if path.name.endswith(".bak"):
            continue
        if path.suffix.lower() not in RUNTIME_SUFFIXES and path.name != "REPLACE.txt":
            continue
        found = True
        yield path
    if not found:
        raise FileNotFoundError(base)


def copy_plugin(root, dest_root):
    copied = []
    for source in iter_plugin_files(root):
        target = Path(dest_root) / source.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(target)
    return copied
