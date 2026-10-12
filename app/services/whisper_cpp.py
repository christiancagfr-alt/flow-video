"""Find or install the whisper.cpp command used by automatic editing.

The OpenAI Python package's whisper.exe is a different program and is never accepted.
Automatic download is limited to the published Windows x64 build.
"""
from __future__ import annotations

import hashlib
import os
import platform
import shutil
import time
import urllib.request
from pathlib import Path

VERSION = "1.8.7"
WIN_ZIP_URL = "https://github.com/ggml-org/whisper.cpp/releases/download/v1.8.7/whisper-bin-x64.zip"
WIN_ZIP_SHA256 = "d9627486e1c34a03745880485593473e047294260ce9a3cb0aa8deaf15b99af6"
WIN_ZIP_SIZE = 4386743
MODEL_NAME = "ggml-base.bin"
MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin"
# SHA published in ggml-org/whisper.cpp models/README.md for the multilingual base model.
MODEL_SHA1 = "465707469ff3a37a2b9b8d8f89f2f99de7299dac"
MODEL_MIN_BYTES = 20 * 1024 * 1024
_CLI_NAMES = {"whisper-cli", "whisper-cli.exe"}
_MODEL_PREFERENCE = ("ggml-base.bin", "ggml-small.bin", "ggml-medium.bin", "ggml-large-v3.bin", "ggml-tiny.bin")


def install_root():
    from app.services.app_paths import data_dir
    return data_dir() / "whisper.cpp"


def _magic_ok(path: Path) -> bool:
    try:
        head = path.read_bytes()[:4]
    except OSError:
        return False
    return head in (b"ggml", b"GGUF", b"lmgg")


def _cli_ok(path: Path) -> bool:
    name = path.name.lower()
    if name == "whisper.exe" or not path.is_file():
        return False
    if name in _CLI_NAMES:
        return True
    return name == "main.exe" and "whisper" in str(path).lower()


def _model_ok(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() == ".bin" and path.name.lower().startswith("ggml-") and _magic_ok(path)


def _walk(root: Path):
    if not root.exists():
        return
    if root.is_file():
        yield root
        return
    for current, dirnames, filenames in os.walk(root):
        if len(Path(current).relative_to(root).parts) > 4:
            dirnames.clear()
            continue
        for name in filenames:
            yield Path(current) / name


def _search_roots(extra=None):
    roots = list(extra or [])
    roots.append(install_root())
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        roots.append(Path(local) / "whisper.cpp")
    roots.append(Path.home() / "whisper.cpp")
    if os.name == "nt":
        roots.append(Path("C:/whisper.cpp"))
    else:
        roots.extend([Path("/opt/homebrew/bin"), Path("/usr/local/bin"), Path.home() / ".local/bin"])
    unique = []
    seen = set()
    for root in roots:
        key = str(root)
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def _first_cli(roots):
    for root in roots:
        for path in _walk(root):
            if _cli_ok(path):
                return path.resolve()
    return None


def _first_model(roots):
    found = []
    for root in roots:
        for path in _walk(root):
            if _model_ok(path):
                found.append(path.resolve())
    if not found:
        return None
    rank = {name: index for index, name in enumerate(_MODEL_PREFERENCE)}
    found.sort(key=lambda path: (rank.get(path.name.lower(), len(rank)), str(path)))
    return found[0]


def discover(cli_setting="", model_setting="", roots=None, include_defaults=True):
    """Return usable absolute paths. A saved path wins when the file is still valid."""
    cli = Path(cli_setting).expanduser() if str(cli_setting or "").strip() else None
    model = Path(model_setting).expanduser() if str(model_setting or "").strip() else None
    search = _search_roots(roots) if include_defaults else [Path(item) for item in (roots or [])]
    if cli is None or not _cli_ok(cli):
        which = ""
        if include_defaults:
            for name in ("whisper-cli", "whisper-cli.exe"):
                which = shutil.which(name) or ""
                if which and _cli_ok(Path(which)):
                    break
                which = ""
        cli = Path(which).resolve() if which else _first_cli(search)
    else:
        cli = cli.resolve()
    near = [cli.parent, cli.parent / "models"] if cli else []
    if model is None or not _model_ok(model):
        model = _first_model(near + search)
    else:
        model = model.resolve()
    return {"cli": str(cli) if cli else "", "model": str(model) if model else ""}


def remember(found):
    from app.core import repository as repo
    if found.get("cli"):
        repo.set_setting("whisper_cli_path", found["cli"])
    if found.get("model"):
        repo.set_setting("whisper_model_path", found["model"])
    return found


def resolve_paths():
    from app.core import repository as repo
    return remember(discover(repo.get_setting("whisper_cli_path", ""), repo.get_setting("whisper_model_path", "")))


def _download(url, dest: Path, expected_sha="", expected_sha1="", expected_size=0, min_size=1):
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_suffix(dest.suffix + ".part")
    last = None
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "FlowStudio/1.0"})
            with urllib.request.urlopen(request, timeout=60) as response, temp.open("wb") as output:
                total = int(response.headers.get("Content-Length") or 0)
                digest = hashlib.sha256()
                digest1 = hashlib.sha1()
                written = 0
                next_report = 8 * 1024 * 1024
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                    digest.update(chunk)
                    digest1.update(chunk)
                    written += len(chunk)
                    if written >= next_report:
                        print(f"已下载 {written // (1024 * 1024)} MB", flush=True)
                        next_report += 8 * 1024 * 1024
            if expected_size and written != expected_size:
                raise ValueError("下载大小与发布文件不一致")
            if total and written != total:
                raise ValueError("下载未完成")
            if written < min_size:
                raise ValueError("下载结果过小")
            if expected_sha and digest.hexdigest() != expected_sha:
                raise ValueError("下载校验失败")
            if expected_sha1 and digest1.hexdigest() != expected_sha1:
                raise ValueError("模型校验与 whisper.cpp 公布的 SHA 不一致")
            temp.replace(dest)
            return dest
        except Exception as exc:
            last = exc
            temp.unlink(missing_ok=True)
            if attempt == 2:
                break
            print(f"下载中断，{3 * (attempt + 1)} 秒后重试（{attempt + 2}/3）。", flush=True)
            time.sleep(3 * (attempt + 1))
    raise RuntimeError("下载失败：" + str(last))


def extract_zip(archive: Path, dest: Path):
    import zipfile
    from pathlib import PurePosixPath
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            parts = PurePosixPath(member.filename.replace("\\", "/")).parts
            if not parts or ".." in parts or any(":" in part or part.startswith("/") for part in parts):
                raise ValueError("非法压缩包路径")
            if member.is_dir():
                continue
            target = dest.joinpath(*parts).resolve()
            if not target.is_relative_to(dest.resolve()):
                raise ValueError("非法压缩包路径")
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def _install_windows_cli():
    if platform.machine().lower() not in ("amd64", "x86_64"):
        raise RuntimeError("自动安装只提供 Windows x64 的 whisper.cpp。请手动选择 whisper-cli。")
    dest = install_root() / ("v" + VERSION)
    existing = _first_cli([dest])
    if existing:
        print("whisper.cpp 命令已存在：" + str(existing), flush=True)
        return existing
    archive = install_root() / "downloads" / "whisper-bin-x64.zip"
    print("正在下载 whisper.cpp " + VERSION + " Windows x64…", flush=True)
    _download(WIN_ZIP_URL, archive, expected_sha=WIN_ZIP_SHA256, expected_size=WIN_ZIP_SIZE)
    extract_zip(archive, dest)
    found = _first_cli([dest])
    if not found:
        raise RuntimeError("压缩包已校验，但其中没有 whisper-cli.exe。")
    print("whisper.cpp 命令已安装：" + str(found), flush=True)
    return found


def _install_model():
    dest = install_root() / "models" / MODEL_NAME
    if _model_ok(dest):
        print("whisper.cpp 模型已存在：" + str(dest), flush=True)
        return dest.resolve()
    print("正在下载 ggml-base 模型…", flush=True)
    _download(MODEL_URL, dest, expected_sha1=MODEL_SHA1, min_size=MODEL_MIN_BYTES)
    if not _model_ok(dest):
        dest.unlink(missing_ok=True)
        raise RuntimeError("模型文件不是 ggml 格式，已删除下载结果。")
    print("whisper.cpp 模型已安装：" + str(dest), flush=True)
    return dest.resolve()


def install():
    from app.core import repository as repo
    found = discover(repo.get_setting("whisper_cli_path", ""), repo.get_setting("whisper_model_path", ""))
    if os.name != "nt" and (not found["cli"] or not found["model"]):
        raise RuntimeError("当前系统不会自动下载 whisper.cpp。请在组件管理中选择本机的 whisper-cli 和 ggml 模型。")
    if not found["cli"]:
        found["cli"] = str(_install_windows_cli())
        remember(found)
    if found["cli"]:
        print("WHISPER_CLI=" + found["cli"], flush=True)
    if not found["model"]:
        try:
            found["model"] = str(_install_model())
        except Exception as exc:
            raise RuntimeError("whisper.cpp 命令已就绪。模型下载失败：" + str(exc) + "。可稍后重试，或在组件管理中选择本机的 ggml-base.bin。") from exc
    remember(found)
    print("WHISPER_MODEL=" + found["model"], flush=True)
    return found
