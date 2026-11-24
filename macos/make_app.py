#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
在 Windows 上拼 macOS 的 .app（外加一个发给别人用的 zip）。

设计目标：**傻瓜安装** —— 解压，把「桌面小猫.app」拖进「应用程序」，双击。
不需要终端、不需要 pip 命令、不需要安装脚本。

.app 里有什么
    Contents/
        Info.plist
        PkgInfo
        MacOS/deskcat            启动器（bash，0755，用户看不见）
        Resources/
            icon.icns
            app/src.dat          脚本压缩块（base85 + zlib，不是可读源码）
            app/web/...          网页与 3D 模型
            app/assets/...       图标

启动器第一次运行会做三件事：
    1. 找 python3（系统自带 / 命令行工具 / Homebrew 都行）
    2. 没有运行环境就在后台建 venv + 从清华镜像装 PyObjC，
       同时弹一个「正在准备」的窗口，装完自己关掉
    3. 把 src.dat 解开、按本机 Python 版本编译成字节码，之后直接跑字节码

为什么发压缩块而不是 .py：
  · 包里不该是一堆可读的 Python 文件
  · 字节码和 Python 版本强绑定，必须在**目标机**上编译，不能在这边预先编好
"""

import base64
import io
import plistlib
import struct
import time
import zipfile
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "dist"
APP_NAME = "桌面小猫"
APP = OUT_DIR / (APP_NAME + ".app")
VER = "1.0.2"
BUNDLE_ID = "com.deskcat.pet"
ZIP = HERE.parent / ("CatPetMac-%s.zip" % VER)
TGZ = HERE.parent / ("桌面小猫-mac-%s.tar.gz" % VER)

WEB = [
    "web/index.html",
    "web/mac-bridge.js",
    "web/glue.js",
    "web/src/cat.js",
    "web/src/three.min.js",
    "assets/icon.png",
    "assets/tray.png",
]

FIRST_RUN_NAME = "首次打开.command"
FIRST_RUN = r"""#!/bin/bash
# 桌面小猫 —— 首次打开助手（双击运行）
# 苹果对「从网上下载、又没有签名证书的 app」会拦一道，报「无法验证开发者」。
# 这个脚本做两件事：清掉下载标记（quarantine）、给 app 做一次本地临时签名，然后启动。
# 它不动你的任何文件，只处理这一个 app。

cd "$(dirname "$0")" || exit 1
echo "桌面小猫 · 首次打开"
echo "----------------------------------------"

APP=""
for p in "$(pwd)/桌面小猫.app" "/Applications/桌面小猫.app" "$HOME/Applications/桌面小猫.app"; do
  if [ -d "$p" ]; then APP="$p"; break; fi
done

if [ -z "$APP" ]; then
  echo "✗ 没找到「桌面小猫.app」。"
  echo "  请把这个脚本和 app 放在同一个文件夹里，或者先把 app 拖进「应用程序」，再双击本脚本。"
  echo
  read -n 1 -s -r -p "按任意键关闭…"
  exit 1
fi
echo "找到：$APP"

# 0) 常见故障：解压后启动器丢了执行权限，双击只会说「无法打开」
EXE="$APP/Contents/MacOS/deskcat"
if [ -x "$EXE" ]; then
  echo "✓ 启动器有执行权限"
else
  if chmod +x "$EXE" 2>/dev/null; then
    echo "✓ 启动器丢了执行权限，已补上（这就是「无法打开」的常见原因）"
  else
    echo "✗ 补执行权限失败：$EXE"
  fi
fi

if xattr -cr "$APP" 2>/dev/null; then
  echo "✓ 已清除「从网上下载」标记"
else
  echo "· 下载标记本来就没有（或已清除）"
fi

if command -v codesign >/dev/null 2>&1; then
  if codesign --force --deep --sign - "$APP" 2>/dev/null; then
    echo "✓ 已做本地临时签名"
  else
    echo "· 本地签名跳过（一般不影响使用）"
  fi
fi

echo "-------------------- 诊断信息 -------------------"
echo "系统: $(sw_vers -productVersion 2>/dev/null)  芯片: $(uname -m)"
if command -v spctl >/dev/null 2>&1; then
  spctl --assess --type execute -vv "$APP" 2>&1 | head -3 | sed 's/^/  /'
fi
if command -v codesign >/dev/null 2>&1; then
  codesign -dv "$APP" 2>&1 | grep -E "Signature|Identifier|flags" | head -3 | sed 's/^/  /'
fi
echo "-------------------------------------------------------------------------"
echo "正在启动…"
if open "$APP"; then
  echo "✓ 已启动。首次会先弹「正在准备运行环境」，约一分钟，需要联网。"
else
  echo "✗ 启动失败。请到「系统设置 → 隐私与安全性」，拉到底点「仍要打开」。"
fi
echo
echo "如果系统还弹窗：系统设置 → 隐私与安全性 → 拉到底 → 仍要打开。"
read -n 1 -s -r -p "按任意键关闭这个窗口…"
"""

LAUNCHER = r"""#!/bin/bash
# 桌面小猫 —— 启动器（Finder 双击走这里，全程不出现终端）
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
RES="$HERE/../Resources"
APP="$RES/app"
DATA="$HOME/Library/Application Support/DeskCat"
RUN="$DATA/run"
VENV="$DATA/venv"
PY="$VENV/bin/python3"
PYC="$RUN/deskcat.pyc"
MARK="$RUN/pyver"
LOG="$HOME/Library/Logs/DesktopCat.log"

mkdir -p "$RUN" "$(dirname "$LOG")" 2>/dev/null
echo "=== $(date '+%F %T') 启动 ===" >>"$LOG"

say_err() {  # 标题 / 正文
    /usr/bin/osascript -e "display alert \"$1\" message \"$2\" as critical" >/dev/null 2>&1
}

# ---------- 1. 找 python3 ----------
SYS_PY=""
for c in "$(command -v python3 2>/dev/null || true)" /usr/bin/python3 \
         /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    if [ -n "$c" ] && [ -x "$c" ]; then SYS_PY="$c"; break; fi
done

if [ -z "$SYS_PY" ]; then
    PICK="$(/usr/bin/osascript -e 'button returned of (display dialog "这台 Mac 还没有 Python 运行环境。点「去安装」会打开 Apple 官方的「命令行工具」安装窗口，装完（几分钟）再双击一次小猫就行。" buttons {"取消", "去安装"} default button 2 with title "桌面小猫" with icon caution)' 2>/dev/null || true)"
    if [ "$PICK" = "去安装" ]; then
        /usr/bin/xcode-select --install >/dev/null 2>&1 || true
    fi
    exit 1
fi
echo "python: $SYS_PY" >>"$LOG"

# ---------- 2. 准备独立环境（只有第一次） ----------
need=0
[ -x "$PY" ] || need=1
if [ "$need" = "0" ] && ! "$PY" -c "import objc, AppKit, WebKit, Quartz, ApplicationServices" >/dev/null 2>&1; then
    need=1
fi

if [ "$need" = "1" ]; then
    # 先挂一个「正在准备」的窗口，装完 kill 掉它，窗口就消失了
    /usr/bin/osascript -e 'display dialog "首次启动，正在准备运行环境。大约一分钟，需要联网。弄好之后这个窗口会自己关掉，小猫就出来了。" with title "桌面小猫" buttons {"请稍等"} default button 1 with icon note giving up after 900' >/dev/null 2>&1 &
    DLG=$!

    {
        echo "--- 准备环境 $(date '+%F %T')  源=$SYS_PY"
        if [ ! -x "$PY" ]; then
            "$SYS_PY" -m venv "$VENV" || echo "!! venv 创建失败"
        fi
        if [ -x "$PY" ]; then
            "$PY" -m pip install --upgrade pip -q 2>&1 | tail -3
            "$PY" -m pip install -q -i https://pypi.tuna.tsinghua.edu.cn/simple \
                pyobjc-framework-Cocoa pyobjc-framework-WebKit \
                pyobjc-framework-Quartz pyobjc-framework-ApplicationServices 2>&1 | tail -6
            if ! "$PY" -c "import objc" >/dev/null 2>&1; then
                echo "--- 镜像失败，换官方源"
                "$PY" -m pip install -q \
                    pyobjc-framework-Cocoa pyobjc-framework-WebKit \
                    pyobjc-framework-Quartz pyobjc-framework-ApplicationServices 2>&1 | tail -6
            fi
        fi
    } >>"$LOG" 2>&1

    kill "$DLG" 2>/dev/null

    if ! "$PY" -c "import objc, AppKit, WebKit, Quartz, ApplicationServices" >/dev/null 2>&1; then
        say_err "准备失败" "运行环境没装好，多半是连不上网。详情已写进日志，点菜单里的「打开日志文件」，把那个文件留着就行。"
        /usr/bin/open -R "$LOG" >/dev/null 2>&1 || true
        exit 1
    fi
fi

# ---------- 3. 编译成字节码（按本机 Python 版本，只做一次） ----------
V="$("$PY" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null)"
if [ ! -f "$PYC" ] || [ "$(cat "$MARK" 2>/dev/null)" != "$V" ]; then
    "$PY" -c "
import base64, os, py_compile, sys, zlib
src = zlib.decompress(base64.b85decode(open(sys.argv[1], 'rb').read()))
tmp = sys.argv[3]
open(tmp, 'wb').write(src)
py_compile.compile(tmp, cfile=sys.argv[2], doraise=True)
os.unlink(tmp)
" "$APP/src.dat" "$PYC" "$RUN/_build.py" >>"$LOG" 2>&1

    if [ ! -f "$PYC" ]; then
        say_err "启动失败" "准备脚本时出错了。点菜单里的「打开日志文件」看日志。"
        exit 1
    fi
    printf '%s' "$V" >"$MARK"
    echo "已编译字节码 (python $V)" >>"$LOG"
fi

export DESKCAT_ASSETS="$APP"
exec "$PY" "$PYC" "$@"
"""


def make_icns(src_png: Path, out: Path):
    """PNG → .icns。icns 就是一串 '类型 + 长度 + PNG 数据'，不用 iconutil。"""
    from PIL import Image

    img = Image.open(src_png).convert("RGBA")
    slots = [
        ("icp4", 16), ("ic11", 32),
        ("icp5", 32), ("ic12", 64),
        ("icp6", 64),
        ("ic07", 128), ("ic13", 256),
        ("ic08", 256), ("ic14", 512),
        ("ic09", 512), ("ic10", 1024),
    ]
    body = b""
    for kind, size in slots:
        buf = src_png.parent / ("_tmp_%d.png" % size)
        img.resize((size, size), Image.LANCZOS).save(buf, "PNG")
        data = buf.read_bytes()
        buf.unlink()
        body += kind.encode("ascii") + struct.pack(">I", len(data) + 8) + data
    out.write_bytes(b"icns" + struct.pack(">I", len(body) + 8) + body)


def write_plist(path: Path):
    info = {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleExecutable": "deskcat",
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": VER,
        "CFBundleVersion": VER,
        "CFBundleIconFile": "icon.icns",
        "LSMinimumSystemVersion": "11.0",
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "MIT",
    }
    path.write_bytes(plistlib.dumps(info, fmt=plistlib.FMT_XML, sort_keys=True))


def build_app():
    import shutil

    if APP.exists():
        shutil.rmtree(APP)

    macos = APP / "Contents" / "MacOS"
    res = APP / "Contents" / "Resources"
    appdir = res / "app"
    for d in (macos, res, appdir / "web" / "src", appdir / "assets"):
        d.mkdir(parents=True, exist_ok=True)

    write_plist(APP / "Contents" / "Info.plist")
    (APP / "Contents" / "PkgInfo").write_bytes(b"APPL????")

    exe = macos / "deskcat"
    exe.write_bytes(LAUNCHER.encode("utf-8"))
    exe.chmod(0o755)

    make_icns(HERE / "assets" / "icon.png", res / "icon.icns")

    # 脚本 → base85(zlib(...))，包里看不到 .py
    src = (HERE / "deskcat.py").read_bytes()
    blob = base64.b85encode(zlib.compress(src, 9))
    (appdir / "src.dat").write_bytes(blob)

    total = 0
    for rel in WEB:
        s = HERE / rel
        if not s.exists():
            raise SystemExit("缺文件: " + rel)
        d = appdir / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        d.write_bytes(s.read_bytes())
        total += d.stat().st_size

    print("生成:", APP)
    print("  脚本 %.1f KB → 压缩块 %.1f KB" % (len(src) / 1024, len(blob) / 1024))
    (HERE / FIRST_RUN_NAME).write_bytes(FIRST_RUN.encode("utf-8").replace(b"\r\n", b"\n"))
    print("  首次打开助手:", FIRST_RUN_NAME)

    print("  网页/素材 %.0f KB + 图标 %.0f KB"
          % (total / 1024, (res / "icon.icns").stat().st_size / 1024))


def build_zip():
    if ZIP.exists():
        ZIP.unlink()
    now = time.localtime()[:6]
    root = "桌面小猫-mac"

    def put(zf, arc, data, mode):
        zi = zipfile.ZipInfo(arc, date_time=now)
        # ★ 关键：create_system 必须写 3（Unix）。
        #   写 0（FAT/Windows）的话，解压工具只认低 16 位的 DOS 属性，
        #   高 16 位的 0755 被直接忽略 —— 解出来就是 0644，
        #   于是 macOS 报「应用程序"桌面小猫"无法打开」。
        zi.create_system = 3
        zi.create_version = 30          # Unix, zip 3.0
        zi.external_attr = (mode << 16) | (0x10 if mode & 0o40000 else 0x20)
        zi.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(zi, data)

    def put_dir(zf, arc):
        zi = zipfile.ZipInfo(arc.rstrip("/") + "/", date_time=now)
        zi.create_system = 3
        zi.create_version = 30
        zi.external_attr = (0o40755 << 16) | 0x10
        zi.compress_type = zipfile.ZIP_STORED
        zf.writestr(zi, b"")

    dirs = set()
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        put(zf, "%s/使用说明.txt" % root,
            (HERE / "使用说明.txt").read_bytes(), 0o644)
        put(zf, "%s/%s" % (root, FIRST_RUN_NAME),
            (HERE / FIRST_RUN_NAME).read_bytes(), 0o755)

        for p in sorted(APP.rglob("*")):
            rel = p.relative_to(OUT_DIR).as_posix()
            arc = "%s/%s" % (root, rel)
            if p.is_dir():
                if arc not in dirs:
                    dirs.add(arc)
                    put_dir(zf, arc)
            else:
                # Windows 上 chmod 不改 st_mode，启动器按文件名显式给 0755
                mode = 0o755 if p.name == "deskcat" else 0o644
                put(zf, arc, p.read_bytes(), mode)

    print("生成:", ZIP.name, "%.0f KB" % (ZIP.stat().st_size / 1024))
    print("  包含: 使用说明.txt + %s + 桌面小猫.app（无安装脚本、无可读源码）" % FIRST_RUN_NAME)


def build_tgz():
    """第二份包：zip 元数据被某些解压工具吃掉时的备胎。
    tar 的权限位是格式自带的，Archive Utility 解 tar.gz 一定会还原 0755。"""
    import tarfile

    if TGZ.exists():
        TGZ.unlink()
    root = "桌面小猫-mac"
    now = time.time()

    def ti(name, mode, isdir=False):
        t = tarfile.TarInfo(name)
        t.mode = mode
        t.uid = t.gid = 0
        t.uname = t.gname = ""
        t.mtime = int(now)
        t.type = tarfile.DIRTYPE if isdir else tarfile.REGTYPE
        return t

    def add_dir(tf, name):
        tf.addfile(ti(name, 0o755, True))

    with tarfile.open(TGZ, "w:gz", compresslevel=9, format=tarfile.GNU_FORMAT) as tf:
        add_dir(tf, root + "/")
        buf = (HERE / "使用说明.txt").read_bytes()
        t = ti(root + "/使用说明.txt", 0o644)
        t.size = len(buf)
        tf.addfile(t, io.BytesIO(buf))

        hbuf = (HERE / FIRST_RUN_NAME).read_bytes()
        th = ti(root + "/" + FIRST_RUN_NAME, 0o755)
        th.size = len(hbuf)
        tf.addfile(th, io.BytesIO(hbuf))

        for p in sorted(APP.rglob("*")):
            rel = p.relative_to(OUT_DIR).as_posix()
            name = "%s/%s" % (root, rel)
            if p.is_dir():
                add_dir(tf, name + "/")
            else:
                data = p.read_bytes()
                t = ti(name, 0o755 if p.name == "deskcat" else 0o644)
                t.size = len(data)
                tf.addfile(t, io.BytesIO(data))

    print("生成:", TGZ.name, "%.0f KB" % (TGZ.stat().st_size / 1024))


if __name__ == "__main__":
    OUT_DIR.mkdir(exist_ok=True)
    build_app()
    build_zip()
    build_tgz()
