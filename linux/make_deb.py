#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
在 Windows 上直接拼一个 Debian 安装包（.deb）。

.deb 就是一个 ar 归档，里面三个成员：
    debian-binary      "2.0\n"
    control.tar.gz     control / postinst / postrm / md5sums
    data.tar.gz        实际装到系统里的文件

不需要 dpkg-deb，纯 Python 组装。打出来是 Architecture: all，
x86_64 和 ARM64（飞腾 / 鲲鹏）通用。
"""

import gzip
import hashlib
import io
import tarfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent          # CatPetUOS/
NAME = "桌面小猫"
VER = "1.0.0"
PKG = "deskcat"
ARCH = "all"          # 纯 Python + JS，架构无关
APP_DIR = "usr/share/deskcat"

OUT = HERE.parent / ("%s_%s_%s.deb" % (NAME, VER, ARCH))

# (源文件, 装到系统里的路径, 权限)
FILES = [
    ("deskcat.py",            APP_DIR + "/deskcat.py",        0o644),
    ("selfcheck.py",          APP_DIR + "/selfcheck.py",      0o755),
    ("run.sh",                APP_DIR + "/run.sh",            0o755),
    ("install.sh",            APP_DIR + "/install.sh",        0o755),
    ("web/index.html",        APP_DIR + "/web/index.html",    0o644),
    ("web/glue.js",           APP_DIR + "/web/glue.js",       0o644),
    ("web/qt-bridge.js",      APP_DIR + "/web/qt-bridge.js",  0o644),
    ("web/src/cat.js",        APP_DIR + "/web/src/cat.js",    0o644),
    ("web/src/three.min.js",  APP_DIR + "/web/src/three.min.js", 0o644),
    ("assets/icon.png",       APP_DIR + "/assets/icon.png",   0o644),
    ("assets/tray.png",       APP_DIR + "/assets/tray.png",   0o644),
    # 文档用 ASCII 文件名：ustar 头里放 UTF-8 字节虽然多数环境能解，
    # 但个别 tar 实现会告警，改名最省事。
    ("使用说明.txt", "usr/share/doc/%s/README.zh_CN.txt" % PKG, 0o644),
]

# 启动器：先查依赖，缺了就用 polkit 弹密码框自动补装，还不行就弹窗告诉用户
LAUNCHER = r"""#!/bin/sh
# 桌面小猫 —— 启动器
# 依赖缺失时会尝试自动补装（polkit 会弹系统密码框），失败则弹窗说明。
APP=/usr/share/deskcat
PY=python3
LOG="${XDG_CACHE_HOME:-$HOME/.cache}/deskcat-install.log"

need() { $PY -c "import PyQt5.QtWebEngineWidgets, Xlib" >/dev/null 2>&1; }

if ! need; then
    mkdir -p "$(dirname "$LOG")" 2>/dev/null || true
    echo "=== $(date) 缺少依赖，尝试补装 ===" >>"$LOG" 2>&1
    if command -v pkexec >/dev/null 2>&1; then
        pkexec sh -c 'apt-get install -y python3-pyqt5.qtwebengine python3-xlib || (apt-get update -qq && apt-get install -y python3-pyqt5.qtwebengine python3-xlib)' >>"$LOG" 2>&1 || true
    fi
fi

if ! need; then
    MSG="桌面小猫启动失败：缺少运行依赖（PyQt5 WebEngine / python-xlib）。

最省事的办法是在终端执行这一行：
    sudo apt install python3-pyqt5.qtwebengine python3-xlib

装完再点一次图标就行。日志：$LOG"
    if command -v zenity >/dev/null 2>&1; then
        zenity --error --title="桌面小猫" --text="$MSG" >/dev/null 2>&1
    elif command -v kdialog >/dev/null 2>&1; then
        kdialog --title="桌面小猫" --error "$MSG" >/dev/null 2>&1
    elif command -v notify-send >/dev/null 2>&1; then
        notify-send "桌面小猫" "缺少依赖：sudo apt install python3-pyqt5.qtwebengine python3-xlib"
    fi
    echo "$MSG" >&2
    exit 1
fi

: "${QTWEBENGINE_CHROMIUM_FLAGS:=--ignore-gpu-blocklist --enable-gpu-rasterization --enable-webgl}"
export QTWEBENGINE_CHROMIUM_FLAGS
exec python3 "$APP/deskcat.py" "$@"
"""

DESKTOP = """[Desktop Entry]
Type=Application
Name=桌面小猫
Name[en_US]=Desk Cat
Comment=会跟着你敲键盘的桌面猫
Comment[en_US]=A desk cat that types along with you
Exec=/usr/bin/deskcat
Icon=deskcat
Terminal=false
Categories=Utility;Amusement;
StartupNotify=false
"""

# 装完收尾。注意：这里不能调 apt —— postinst 执行期间 dpkg 还占着锁，
# 任何 apt/dpkg 调用都会失败。补装依赖交给启动器（那时锁已释放）。
POSTINST = r"""#!/bin/sh
set -e
LOG=/var/log/deskcat-install.log

chmod +x /usr/share/deskcat/run.sh /usr/share/deskcat/install.sh 2>/dev/null || true
rm -rf /usr/share/deskcat/__pycache__ 2>/dev/null || true

{
    echo "=== $(date) 安装完成 ==="
    if python3 -c "import PyQt5.QtWebEngineWidgets, Xlib" 2>/dev/null; then
        echo "依赖齐全，可直接运行"
    else
        echo "依赖不齐（启动器会自动尝试补装）"
    fi
} >> "$LOG" 2>&1

update-desktop-database -q /usr/share/applications 2>/dev/null || true
gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor 2>/dev/null || true
exit 0
"""

POSTRM = r"""#!/bin/sh
set -e
update-desktop-database -q /usr/share/applications 2>/dev/null || true
gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor 2>/dev/null || true
exit 0
"""


def ar_member(name: str, data: bytes, mtime: int) -> bytes:
    """ar 归档的一个成员：60 字节头 + 数据（奇数长度补一个换行）"""
    if len(name) > 15:
        raise ValueError("ar 成员名过长: " + name)
    header = "%-16s%-12d%-6d%-6d%-8s%-10d`\n" % (
        name, mtime, 0, 0, "100644", len(data)
    )
    out = header.encode("ascii") + data
    if len(data) % 2:
        out += b"\n"
    return out


def tar_gz(members, mtime: int) -> bytes:
    """members: [(归档内路径, bytes|None, mode, is_dir)]"""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        for name, data, mode, is_dir in members:
            ti = tarfile.TarInfo(name)
            ti.mtime = mtime
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = "root"
            ti.mode = mode
            if is_dir:
                ti.type = tarfile.DIRTYPE
                ti.size = 0
                tf.addfile(ti)
            else:
                ti.type = tarfile.REGTYPE
                ti.size = len(data)
                tf.addfile(ti, io.BytesIO(data))
    return gzip.compress(raw.getvalue(), 9, mtime=mtime)


def main():
    mtime = int(time.time())
    if OUT.exists():
        OUT.unlink()

    entries = []          # (归档内路径, 数据, 权限, 是否目录)
    dirs = set()
    md5_lines = []
    total = 0

    def add_dir(path):
        """把 path 的所有父目录补齐（dpkg 自己也会建，但显式列出来更清楚）"""
        parts = path.strip("/").split("/")
        for i in range(1, len(parts) + 1):
            d = "/".join(parts[:i])
            if d and d not in dirs:
                dirs.add(d)
                entries.append(("./" + d, None, 0o755, True))

    def add_file(dest, data, mode):
        nonlocal total
        add_dir("/".join(dest.split("/")[:-1]))
        entries.append(("./" + dest, data, mode, False))
        md5_lines.append("%s  %s" % (hashlib.md5(data).hexdigest(), dest))
        total += len(data)

    # ---------- 程序文件 ----------
    for rel, dest, mode in FILES:
        src = HERE / rel
        if not src.exists():
            raise SystemExit("缺文件: " + rel)
        add_file(dest, src.read_bytes(), mode)

    # ---------- 启动器 / 菜单项 / 图标 ----------
    add_file("usr/bin/deskcat", LAUNCHER.encode("utf-8"), 0o755)
    add_file("usr/share/applications/deskcat.desktop", DESKTOP.encode("utf-8"), 0o644)
    add_file(
        "usr/share/icons/hicolor/256x256/apps/deskcat.png",
        (HERE / "assets" / "icon.png").read_bytes(),
        0o644,
    )
    add_file("usr/share/doc/%s/copyright" % PKG, b"MIT License\n", 0o644)

    data_tar = tar_gz(entries, mtime)

    # ---------- control ----------
    installed_kb = max(1, (total + len(data_tar)) // 1024)
    control = (
        "Package: %s\n"
        "Version: %s\n"
        "Section: utils\n"
        "Priority: optional\n"
        "Architecture: %s\n"
        "Depends: python3 (>= 3.6), python3-xlib, python3-pyqt5.qtwebengine\n"
        "Recommends: fonts-noto-cjk\n"
        "Installed-Size: %d\n"
        "Maintainer: deskcat <deskcat@localhost>\n"
        "Description: 桌面小猫\n"
        " 一只悬浮在桌面上的 3D 小猫：你敲键盘它跟着敲并弹出字符，\n"
        " 你动鼠标它盯着看，闲着会舔毛打哈欠，久了会睡着。\n"
        " .\n"
        " 点击穿透、不抢焦点，支持毛色 / 大小 / 睡眠时间调节。\n"
    ) % (PKG, VER, ARCH, installed_kb)

    ctl_entries = [
        ("./control", control.encode("utf-8"), 0o644, False),
        ("./md5sums", ("\n".join(md5_lines) + "\n").encode("utf-8"), 0o644, False),
        ("./postinst", POSTINST.encode("utf-8"), 0o755, False),
        ("./postrm", POSTRM.encode("utf-8"), 0o755, False),
    ]
    control_tar = tar_gz(ctl_entries, mtime)

    # ---------- 组装 ar ----------
    blob = b"!<arch>\n"
    blob += ar_member("debian-binary", b"2.0\n", mtime)
    blob += ar_member("control.tar.gz", control_tar, mtime)
    blob += ar_member("data.tar.gz", data_tar, mtime)
    OUT.write_bytes(blob)

    print("生成:", OUT)
    print("  体积: %.1f KB" % (len(blob) / 1024))
    print("  data.tar.gz: %.1f KB   control.tar.gz: %.1f KB"
          % (len(data_tar) / 1024, len(control_tar) / 1024))
    print("  文件数: %d  安装后占用: 约 %d KB" % (len(md5_lines), installed_kb))
    print("  架构: %s（纯 Python + JS，x86_64 / ARM64 通用）" % ARCH)


if __name__ == "__main__":
    main()
