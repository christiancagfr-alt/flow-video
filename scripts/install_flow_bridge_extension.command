#!/bin/bash
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EXT="$ROOT/extension/FlowStudioWebPlugin"

echo "Flow Studio V0.12.23 / Web Plugin v0.5.1"
echo ""
echo "Chrome 安装步骤："
echo "1. 打开 chrome://extensions"
echo "2. 开启右上角‘开发者模式’"
echo "3. 如果旧 Flow Studio / Flow 批量插件仍启用，请先停用，避免冲突"
echo "4. 点击‘加载已解压的扩展程序’"
echo "5. 选择：$EXT"
open "$EXT"
