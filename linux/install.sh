#!/bin/sh
# 桌面小猫 —— UOS / Linux 安装脚本
# 用法：在终端里 cd 到本目录，执行  sh install.sh
set -e

HERE=$(cd "$(dirname "$0")" && pwd)
DEST="$HOME/.local/share/deskcat"

echo "== 1/3 检查依赖 =="
MISSING=""
python3 -c "import PyQt5.QtWebEngineWidgets" 2>/dev/null || MISSING="$MISSING python3-pyqt5.qtwebengine"
python3 -c "import Xlib" 2>/dev/null || MISSING="$MISSING python3-xlib"

if [ -n "$MISSING" ]; then
    echo "需要安装这些包：$MISSING"
    echo "（会提示输入密码）"
    sudo apt update
    # shellcheck disable=SC2086
    sudo apt install -y $MISSING || true
    # 仓库里没有的话，退回到 pip
    if ! python3 -c "import PyQt5.QtWebEngineWidgets" 2>/dev/null; then
        echo ""
        echo "软件源里没找到，改用 pip 装（可能比较慢）："
        pip3 install PyQt5 PyQtWebEngine python-xlib --break-system-packages \
            || pip3 install PyQt5 PyQtWebEngine python-xlib
    fi
else
    echo "依赖已齐全"
fi

echo "== 2/3 复制到 $DEST =="
mkdir -p "$DEST"
cp -r "$HERE"/web "$HERE"/assets "$HERE"/deskcat.py "$HERE"/run.sh "$HERE"/selfcheck.py "$HERE"/使用说明.txt "$DEST"/
chmod +x "$DEST/run.sh"

echo "== 3/3 建菜单项和命令 =="
mkdir -p "$HOME/.local/share/applications" "$HOME/.local/bin"
cat > "$HOME/.local/share/applications/deskcat.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=桌面小猫
Comment=会跟着你敲键盘的桌面猫
Exec=$DEST/run.sh
Icon=$DEST/assets/icon.png
Terminal=false
Categories=Utility;
EOF
ln -sf "$DEST/run.sh" "$HOME/.local/bin/deskcat"

echo ""
echo "装好了。"
echo "  启动：终端输入  deskcat   或者在启动器里搜「桌面小猫」"
echo "  自检：终端输入  python3 $DEST/selfcheck.py"
echo "  卸载：删掉 $DEST 和 $HOME/.local/share/applications/deskcat.desktop"
