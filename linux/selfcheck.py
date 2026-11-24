#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
环境自检 —— 不出画面时先跑这个，把输出留着，能直接看出卡在哪一步。
    python3 selfcheck.py
"""

import os
import platform
import shutil
import subprocess
import sys

OK = "  [ok]  "
NO = "  [!!]  "
WARN = "  [--]  "

problems = []


def line(tag, msg, hint=None):
    print(tag + msg)
    if hint:
        print("         → " + hint)
    if tag == NO:
        problems.append(msg)


print("=" * 60)
print("桌面小猫 环境自检")
print("=" * 60)

# 1. 系统
print("\n[系统]")
line(OK, "Python %s" % platform.python_version())
if sys.version_info < (3, 6):
    line(NO, "Python 版本过低（需要 3.6+）", "UOS 自带的就够，别用很老的解释器")
try:
    with open("/etc/os-release", encoding="utf-8") as f:
        pretty = [l for l in f if l.startswith("PRETTY_NAME")][0].split("=", 1)[1].strip()
    line(OK, "系统 %s" % pretty)
except Exception:
    line(WARN, "读不到 /etc/os-release")
line(OK, "架构 %s" % platform.machine())

# 2. 会话类型（决定能不能抓全局按键）
print("\n[显示会话]")
sess = os.environ.get("XDG_SESSION_TYPE", "?")
line(OK if sess.lower() == "x11" else WARN, "会话类型 %s" % sess)
if sess.lower() == "x11":
    line(OK, "DISPLAY=%s" % os.environ.get("DISPLAY", "?"))
elif sess.lower() == "wayland":
    line(NO, "当前是 Wayland 会话",
         "Wayland 下抓不到全局按键。登录界面选「X11 会话」再进，猫才能跟着你敲键盘")
    print("         （只有鼠标跟随的话 Wayland 也能用，键盘不动是正常的）")

# 3. Python 依赖
print("\n[Python 依赖]")
try:
    from PyQt5.QtCore import QT_VERSION_STR
    line(OK, "PyQt5，Qt %s" % QT_VERSION_STR)
except Exception as e:
    line(NO, "PyQt5 不可用：%s" % e, "sudo apt install -y python3-pyqt5.qtwebengine")

try:
    from PyQt5.QtWebEngineWidgets import QWebEngineView  # noqa: F401
    line(OK, "QtWebEngine（渲染猫的那个内核）")
except Exception as e:
    line(NO, "QtWebEngine 不可用：%s" % e, "sudo apt install -y python3-pyqt5.qtwebengine")

try:
    from Xlib import display as xdisplay
    line(OK, "python-xlib（抓全局按键用）")
    HAVE_XLIB = True
except Exception as e:
    line(NO, "python-xlib 不可用：%s" % e, "sudo apt install -y python3-xlib")
    HAVE_XLIB = False

# 4. X11 能力
if HAVE_XLIB:
    print("\n[X11 能力]")
    try:
        d = xdisplay.Display()
    except Exception as e:
        line(NO, "连不上 X11：%s" % e)
        d = None
    if d:
        if d.has_extension("RECORD"):
            line(OK, "RECORD 扩展（全局键盘/鼠标监听）")
        else:
            line(NO, "没有 RECORD 扩展", "键盘和点击都不会有反应，换 X11 会话试试")
        owner = d.get_selection_owner(d.intern_atom("_NET_WM_CM_S0"))
        if owner and owner != 0:
            line(OK, "桌面合成器在运行（窗口透明靠它）")
        else:
            line(NO, "没有桌面合成器", "窗口背景会变成黑块。DDE 下一般不会，若出现请换个窗管试试")
        try:
            scr = d.screen()
            geo = scr.root.get_geometry()
            line(OK, "屏幕 %d×%d" % (geo.width, geo.height))
        except Exception:
            pass
        d.close()

# 5. 字体（字符气泡要用）
print("\n[字体]")
try:
    out = subprocess.run(["fc-list", ":lang=zh"], capture_output=True, timeout=8)
    n = len(out.stdout.decode("utf-8", "ignore").strip().splitlines())
    if n > 0:
        line(OK, "中文字体 %d 个" % n)
    else:
        line(NO, "没有中文字体", "sudo apt install -y fonts-noto-cjk")
except Exception:
    line(WARN, "没有 fc-list，跳过字体检查")

# 6. 显卡
print("\n[显卡]")
if shutil.which("glxinfo"):
    try:
        out = subprocess.run(
            ["glxinfo", "-B"], capture_output=True, timeout=8
        ).stdout.decode("utf-8", "ignore")
        for key in ("OpenGL renderer", "OpenGL version"):
            for l in out.splitlines():
                if l.strip().startswith(key):
                    line(OK, l.strip())
    except Exception:
        line(WARN, "glxinfo 跑不起来")
else:
    line(WARN, "没装 glxinfo（不影响使用，只是看不到显卡信息）",
         "sudo apt install -y mesa-utils")

# 汇总
print("\n" + "=" * 60)
if not problems:
    print("自检通过，可以直接运行：./run.sh")
else:
    print("发现 %d 个问题，按上面的提示处理：" % len(problems))
    for p in problems:
        print("  · " + p)
print("=" * 60)
