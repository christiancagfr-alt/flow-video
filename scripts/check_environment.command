#!/bin/zsh
cd "$(dirname "$0")/.."
echo "Flow Studio 环境检查"
echo ""
show_py() {
  local label="$1"; local p="$2"
  if [[ -x "$p" ]] || command -v "$p" >/dev/null 2>&1; then
    local real="$p"
    if command -v "$p" >/dev/null 2>&1; then real="$(command -v "$p")"; fi
    echo "$label -> $real"
    "$real" -c 'import sys,ssl; print("   Python", sys.version.split()[0], "|", ssl.OPENSSL_VERSION)' 2>/dev/null || true
  fi
}
for p in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
  show_py "$p" "$p"
done
for v in 3.14 3.13 3.12 3.11 3.10; do
  p="/Library/Frameworks/Python.framework/Versions/$v/bin/python$v"
  [[ -x "$p" ]] && show_py "python.org $v" "$p"
done
if [[ -x .venv/bin/python ]]; then
  echo ""
  echo ".venv -> $(.venv/bin/python -c 'import sys,ssl; print(sys.version.split()[0], "|", ssl.OPENSSL_VERSION)' 2>/dev/null)"
  .venv/bin/python - <<'PY'
mods=['PySide6','googleapiclient','google.auth','google_auth_oauthlib']
import sys
if sys.platform == 'darwin': mods += ['objc','AVFoundation','AVKit','CoreMedia']
for m in mods:
    try:
        mod=__import__(m)
        print('OK  ',m, getattr(mod,'__version__',''))
    except Exception as e:
        print('MISS',m,':',e)
PY
else
  echo ""
  echo ".venv 尚未建立。"
fi
echo ""
read -n 1 -s -r -p "按任意键关闭..."
