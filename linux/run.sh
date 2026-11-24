#!/bin/sh
# 启动桌面小猫
HERE=$(cd "$(dirname "$0")" && pwd)

# ARM64 上的 Mali/软渲染有时会被 Chromium 拉黑，这里放开
export QTWEBENGINE_CHROMIUM_FLAGS="${QTWEBENGINE_CHROMIUM_FLAGS:---ignore-gpu-blocklist --enable-gpu-rasterization --enable-webgl}"
# 有些驱动下 GPU 进程会崩，崩了就自动退回软件渲染
export QT_QUICK_BACKEND="${QT_QUICK_BACKEND:-}"

exec python3 "$HERE/deskcat.py" "$@"
