#!/bin/zsh
set -u
cd "$(dirname "$0")/.."

APP_VERSION="V0.13.5.105 强运镜与辅助图闭环"
VENV_DIR=".venv"
VENV_PY="$VENV_DIR/bin/python"
LOG_DIR="data/logs"
BOOT_LOG="$LOG_DIR/startup-bootstrap.log"
mkdir -p "$LOG_DIR"

log() {
  echo "$1"
  printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" >> "$BOOT_LOG"
}

pause_exit() {
  local code="${1:-1}"
  echo ""
  read -k 1 -s "reply?按任意键关闭..."
  echo ""
  exit "$code"
}

python_ok() {
  local bin="$1"
  [[ -x "$bin" || "$(command -v "$bin" 2>/dev/null)" != "" ]] || return 1
  "$bin" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if (3,10) <= sys.version_info[:2] < (3,15) else 1)
PY
}

find_python() {
  local p candidate_path
  # 1) PATH 中的明确版本，优先用户现有的 3.14。
  for p in python3.14 python3.13 python3.12 python3.11 python3.10; do
    if command -v "$p" >/dev/null 2>&1 && python_ok "$p"; then
      command -v "$p"
      return 0
    fi
  done

  # 2) python.org 官方 macOS Framework 安装路径。
  for p in 3.14 3.13 3.12 3.11 3.10; do
    candidate_path="/Library/Frameworks/Python.framework/Versions/$p/bin/python$p"
    if [[ -x "$candidate_path" ]] && python_ok "$candidate_path"; then
      echo "$candidate_path"
      return 0
    fi
  done

  # 3) 常见 Homebrew 路径，仅检测，不会自动安装 Homebrew。
  for candidate_path in \
    /opt/homebrew/bin/python3.14 /usr/local/bin/python3.14 \
    /opt/homebrew/bin/python3.13 /usr/local/bin/python3.13 \
    /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12 \
    /opt/homebrew/bin/python3.11 /usr/local/bin/python3.11 \
    /opt/homebrew/bin/python3.10 /usr/local/bin/python3.10; do
    if [[ -x "$candidate_path" ]] && python_ok "$candidate_path"; then
      echo "$candidate_path"
      return 0
    fi
  done

  # 4) 最后尝试 python3，但必须是 3.10~3.14。
  if command -v python3 >/dev/null 2>&1 && python_ok "$(command -v python3)"; then
    command -v python3
    return 0
  fi
  return 1
}

check_deps() {
  "$VENV_PY" - <<'PY' >/dev/null 2>&1
import sys
assert (3,10) <= sys.version_info[:2] < (3,15)
import shiboken6
import PySide6
from PySide6.QtWidgets import QApplication
import os
import stat
from pathlib import Path
from PySide6.QtCore import QLibraryInfo, QDir
plugin_root = Path(QLibraryInfo.path(QLibraryInfo.PluginsPath))
if sys.platform == 'darwin':
    for entry in [plugin_root, *plugin_root.rglob('*')]:
        flags = entry.stat().st_flags
        if flags & stat.UF_HIDDEN:
            os.chflags(entry, flags & ~stat.UF_HIDDEN)
    assert 'libqcocoa.dylib' in QDir(str(plugin_root / 'platforms')).entryList(QDir.Files), 'macOS cocoa plugin missing or invisible'
import googleapiclient.discovery
import google.oauth2.credentials
import google_auth_oauthlib.flow
if sys.platform == 'darwin':
    import objc
    import AVFoundation
    import AVKit
    import CoreMedia
PY
}

log "===================================================="
log "Flow Studio $APP_VERSION 启动"
log "项目目录：$(pwd)"

PYTHON_BIN=$(find_python || true)
if [[ -z "${PYTHON_BIN:-}" ]]; then
  OLD_VER=$(python3 -c 'import sys; print(".".join(map(str,sys.version_info[:3])))' 2>/dev/null || echo "未找到")
  log "未找到可用的 Python 3.10~3.14。当前 python3：$OLD_VER"
  log "Flow Studio 不会自动安装或修改系统 Python。"
  log "如果你已安装 Python 3.14/3.13/3.12，请运行 scripts/check_environment.command 查看检测路径。"
  pause_exit 1
fi

PYVER=$($PYTHON_BIN -c 'import sys; print(".".join(map(str,sys.version_info[:3])))')
PYSSL=$($PYTHON_BIN -c 'import ssl; print(ssl.OPENSSL_VERSION)' 2>/dev/null || echo "SSL未知")
log "选择运行 Python：$PYTHON_BIN ($PYVER)"
log "SSL：$PYSSL"

need_recreate=0
if [[ ! -x "$VENV_PY" ]]; then
  need_recreate=1
else
  VENV_VER=$($VENV_PY -c 'import sys; print(".".join(map(str,sys.version_info[:2])))' 2>/dev/null || echo bad)
  BASE_VER=$($PYTHON_BIN -c 'import sys; print(".".join(map(str,sys.version_info[:2])))')
  if [[ "$VENV_VER" != "$BASE_VER" ]]; then
    log "现有 .venv Python=$VENV_VER，与当前选定 Python=$BASE_VER 不一致，将重建。"
    need_recreate=1
  elif ! "$VENV_PY" -c 'import sys; print(sys.executable)' >/dev/null 2>&1; then
    need_recreate=1
  fi
fi

if [[ "$need_recreate" -eq 1 ]]; then
  echo ""
  echo "Flow Studio 需要创建独立运行环境。"
  echo "将只在当前项目的 .venv 中安装以下白名单依赖："
  echo "  PySide6 6.11.2 / PySide6-Essentials 6.11.2 / PySide6-Addons 6.11.2 / shiboken6 6.11.2"
  echo "  google-api-python-client / google-auth / google-auth-oauthlib"
  echo "来源固定：https://pypi.org/simple"
  echo "不会安装 Homebrew、Chrome、DaVinci、Whisper、FFmpeg、Pillow 或系统后台服务。"
  echo ""
  read "answer?输入 YES 允许创建/重建 .venv： "
  if [[ "$answer" != "YES" ]]; then
    log "用户取消环境创建。"
    exit 0
  fi
  rm -rf "$VENV_DIR"
  log "正在使用 $PYTHON_BIN 创建独立 .venv ..."
  if ! "$PYTHON_BIN" -m venv "$VENV_DIR" >>"$BOOT_LOG" 2>&1; then
    log "创建 .venv 失败，详情见 $BOOT_LOG"
    pause_exit 1
  fi
fi

if ! check_deps; then
  echo ""
  echo "检测到 .venv 缺少运行依赖。"
  echo "将仅从官方 PyPI 按 requirements.txt 补齐白名单依赖。"
  read "answer?输入 YES 允许补齐： "
  if [[ "$answer" != "YES" ]]; then
    log "用户取消依赖补齐。"
    exit 0
  fi
  log "正在补齐依赖..."
  if ! "$VENV_PY" -m pip install \
      --index-url https://pypi.org/simple \
      --disable-pip-version-check \
      --only-binary=:all: \
      -r requirements.txt >>"$BOOT_LOG" 2>&1; then
    log "依赖安装失败。请查看 $BOOT_LOG"
    log "如果是 Python 3.14，请把日志中 pip 的最后 30 行发给我。"
    pause_exit 1
  fi
fi

if ! check_deps; then
  log "环境检查仍未通过。请查看 $BOOT_LOG"
  pause_exit 1
fi

log "环境检查通过，正在启动 Flow Studio..."
"$VENV_PY" main.py
code=$?
if [[ "$code" -ne 0 ]]; then
  log "Flow Studio 异常退出，退出码：$code"
  log "请提供 $BOOT_LOG 与终端截图。"
  pause_exit "$code"
fi
