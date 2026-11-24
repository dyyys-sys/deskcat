#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面小猫 —— 统信 UOS / Linux 通用版

和 Windows 版的架构对照
----------------------
Windows 版：透明无边框窗口 + 自己算命中区域，用 SetWindowLongPtr 打 WS_EX_TRANSPARENT
            做穿透，键盘用 WH_KEYBOARD_LL 低级钩子。

Linux 版：思路一样，但手段不同 ——
  · 窗口「完全不吃鼠标」：把 X11 的输入形状置空。
    Qt 5.12+ 用 Qt.WindowTransparentForInput；Qt 5.11（UOS 20 / deepin 20）
    没有这个属性，set_click_through() 用 ctypes 直接调 libXext 做同样的事。
    好处是点击 100% 穿透、永不抢焦点、也不会像开关穿透那样闪烁。
  · 代价是 DOM 再也收不到鼠标事件，所以所有交互都得自己判断：
      - 全局鼠标位置：QCursor.pos() 每 33ms 轮询
      - 全局按键 / 鼠标按钮：X11 XRecord 扩展（UOS 默认 X11 会话，可用）
  · 判定「点在猫身上」之后，再往页面里注入**合成的 DOM 事件**，
    这样 cat.js 的摸猫、双击转圈、按键动画全都不用改。

已知限制
  · Wayland 会话下 XRecord 抓不到原生 Wayland 窗口的按键（UOS 默认 X11，一般没这问题）。
  · 透明背景依赖桌面合成器（DDE 自带，没问题）。
"""

import json
import os
import sys
import threading
import time
from pathlib import Path

# ---- QtWebEngine 的参数必须在 import Qt 之前设好 ----
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--ignore-gpu-blocklist --enable-gpu-rasterization --enable-webgl",
)
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")

DEBUG = os.environ.get("CATPET_DEBUG", "")

try:
    from PyQt5.QtCore import QObject, QPoint, QTimer, Qt, QUrl, pyqtSignal
    from PyQt5.QtGui import QColor, QCursor, QIcon
    from PyQt5.QtWidgets import (
        QAction,
        QApplication,
        QMenu,
        QSystemTrayIcon,
        QWidget,
    )
    from PyQt5.QtWebEngineWidgets import QWebEngineView
except ImportError as exc:
    sys.stderr.write(
        "缺少依赖：%s\n\n"
        "请先执行（需要联网）：\n"
        "    sudo apt install -y python3-pyqt5.qtwebengine python3-xlib\n\n"
        "或者直接运行本目录下的 install.sh\n" % exc
    )
    sys.exit(1)

try:
    from Xlib import X, XK, display as xdisplay
    from Xlib.ext import record as xrecord
    from Xlib.protocol import rq as xrq
    HAVE_XLIB = True
except ImportError:
    HAVE_XLIB = False

BASE_W, BASE_H = 400, 340

# 窗口标志：Qt 5.12+ 有 WindowTransparentForInput（直接把输入形状置空），
# 但 UOS 20 / deepin 20 自带的是 Qt 5.11，没有这个枚举值 —— 直接写会在启动时
# 抛 AttributeError。所以这里按版本探测，没有就退到 set_click_through()。
WINDOW_FLAGS = (
    Qt.FramelessWindowHint
    | Qt.WindowStaysOnTopHint
    | Qt.Tool
    | Qt.NoDropShadowWindowHint
)
HAS_QT_TRANSPARENT = hasattr(Qt, "WindowTransparentForInput")
if HAS_QT_TRANSPARENT:
    WINDOW_FLAGS |= Qt.WindowTransparentForInput


def set_click_through(win_id):
    """把 X11 窗口的「输入形状」清空 —— 之后鼠标完全穿过去，也不抢焦点。

    Qt 5.11 没有 WindowTransparentForInput，只能自己调 Shape 扩展：
        XShapeCombineRectangles(dpy, win, ShapeInput=2, 0, 0, NULL, 0,
                                ShapeSet=0, Unsorted=0)
    矩形列表为空 + ShapeSet = 输入区域变成空集，等价于 Qt 后来封装的属性。
    返回 True 表示设置成功。
    """
    try:
        import ctypes

        class XRectangle(ctypes.Structure):
            _fields_ = [
                ("x", ctypes.c_short),
                ("y", ctypes.c_short),
                ("width", ctypes.c_ushort),
                ("height", ctypes.c_ushort),
            ]

        x11 = ctypes.CDLL("libX11.so.6")
        xext = ctypes.CDLL("libXext.so.6")
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XFlush.argtypes = [ctypes.c_void_p]
        xext.XShapeCombineRectangles.argtypes = [
            ctypes.c_void_p,   # Display*
            ctypes.c_ulong,    # Window
            ctypes.c_int,      # destKind  (ShapeInput = 2)
            ctypes.c_int,      # xOffset
            ctypes.c_int,      # yOffset
            ctypes.c_void_p,   # XRectangle*  (NULL = 空集合)
            ctypes.c_int,      # n_rects
            ctypes.c_int,      # op        (ShapeSet = 0)
            ctypes.c_int,      # ordering  (Unsorted = 0)
        ]

        dpy = x11.XOpenDisplay(None)
        if not dpy:
            log("打不开 X display，跳过穿透设置")
            return False
        xext.XShapeCombineRectangles(dpy, ctypes.c_ulong(win_id), 2, 0, 0,
                                     None, 0, 0, 0)
        x11.XFlush(dpy)
        return True
    except Exception as exc:
        log("设置输入穿透失败", exc)
        return False


ROOT = Path(__file__).resolve().parent
INDEX = ROOT / "web" / "index.html"
CFG_DIR = Path(os.path.expanduser("~/.config/deskcat"))
CFG_PATH = CFG_DIR / "config.json"
AUTOSTART = Path(os.path.expanduser("~/.config/autostart/deskcat.desktop"))

DEFAULT_CFG = {
    "x": None,
    "y": None,
    "scale": 1.0,
    "coat": "tuxedo",
    "sleepMinutes": 15.0,
    "leftMouse": False,
    "locked": False,
}

COATS = [
    ("tuxedo", "奶牛猫"),
    ("orange", "橘猫"),
    ("tabby", "狸花猫"),
    ("calico", "三花猫"),
    ("white", "白猫"),
    ("blue", "蓝灰猫"),
]
SIZES = [(0.8, "小 (80%)"), (1.0, "中 (100%)"), (1.25, "大 (125%)"), (1.5, "超大 (150%)")]
SLEEPS = [(1.0, "1 分钟"), (2.0, "2 分钟"), (5.0, "5 分钟"), (15.0, "15 分钟"), (120.0, "几乎不睡")]


def log(*a):
    if DEBUG:
        print("[cat]", *a, flush=True)


# ---------------------------------------------------------------- 配置

def load_cfg():
    cfg = dict(DEFAULT_CFG)
    try:
        cfg.update(json.loads(CFG_PATH.read_text(encoding="utf-8")))
    except Exception:
        pass
    return cfg


def save_cfg(cfg):
    try:
        CFG_DIR.mkdir(parents=True, exist_ok=True)
        CFG_PATH.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as exc:
        log("保存配置失败", exc)


# ---------------------------------------------------------------- 按键映射

# X11 keysym 名字 → 浏览器 KeyboardEvent.code
SPECIAL = {
    "Return": "Enter",
    "KP_Enter": "Enter",
    "BackSpace": "Backspace",
    "Tab": "Tab",
    "Escape": "Escape",
    "Delete": "Delete",
    "Insert": "Insert",
    "Home": "Home",
    "End": "End",
    "Prior": "PageUp",
    "Next": "PageDown",
    "Left": "ArrowLeft",
    "Right": "ArrowRight",
    "Up": "ArrowUp",
    "Down": "ArrowDown",
    "Shift_L": "ShiftLeft",
    "Shift_R": "ShiftRight",
    "Control_L": "ControlLeft",
    "Control_R": "ControlRight",
    "Alt_L": "AltLeft",
    "Alt_R": "AltRight",
    "Meta_L": "MetaLeft",
    "Super_L": "MetaLeft",
    "Meta_R": "MetaRight",
    "Super_R": "MetaRight",
    "Caps_Lock": "CapsLock",
    "space": "Space",
    "minus": "Minus",
    "equal": "Equal",
    "bracketleft": "BracketLeft",
    "bracketright": "BracketRight",
    "backslash": "Backslash",
    "semicolon": "Semicolon",
    "apostrophe": "Quote",
    "grave": "Backquote",
    "comma": "Comma",
    "period": "Period",
    "slash": "Slash",
    "KP_0": "Digit0",
    "KP_1": "Digit1",
    "KP_2": "Digit2",
    "KP_3": "Digit3",
    "KP_4": "Digit4",
    "KP_5": "Digit5",
    "KP_6": "Digit6",
    "KP_7": "Digit7",
    "KP_8": "Digit8",
    "KP_9": "Digit9",
    "KP_Decimal": "Period",
    "KP_Add": "Equal",
    "KP_Subtract": "Minus",
    "KP_Multiply": "KeyX",
    "KP_Divide": "Slash",
}


def build_keymap():
    """X11 keycode → DOM code。默认布局下取 shift level 0 即可。"""
    m = {}
    if not HAVE_XLIB:
        return m
    try:
        d = xdisplay.Display()
    except Exception as exc:
        log("连不上 X11：", exc)
        return m

    names = {}
    for n in dir(XK):
        if n.startswith("XK_"):
            try:
                names.setdefault(getattr(XK, n), n[3:])
            except Exception:
                pass

    for kc in range(8, 256):
        try:
            ks = d.keycode_to_keysym(kc, 0)
        except Exception:
            continue
        if not ks:
            continue
        name = names.get(ks)
        code = SPECIAL.get(name) if name else None
        if code is None:
            ch = None
            if name and len(name) == 1:
                ch = name
            else:
                try:
                    s = XK.keysym_to_string(ks)
                    if s and len(s) == 1:
                        ch = s
                except Exception:
                    pass
            if ch:
                if ch.isalpha():
                    code = "Key" + ch.upper()
                elif ch.isdigit():
                    code = "Digit" + ch
        if code:
            m[kc] = code
    d.close()
    log("键位映射条数", len(m))
    return m


# ---------------------------------------------------------------- XRecord

class XRecorder(QObject):
    """在后台线程里监听全局按键和鼠标按钮，通过信号回到 Qt 主线程。"""

    key = pyqtSignal(int, bool)              # keycode, 是否按下
    button = pyqtSignal(int, bool, int, int)  # 按钮号, 是否按下, 屏幕 x, 屏幕 y
    failed = pyqtSignal(str)

    def __init__(self):
        super().__init__()

    def start(self):
        if not HAVE_XLIB:
            self.failed.emit("没有 python-xlib，键盘鼠标监听不可用")
            return
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            d = xdisplay.Display()
        except Exception as exc:
            self.failed.emit("连不上 X11：%s" % exc)
            return
        if not d.has_extension("RECORD"):
            self.failed.emit("X11 没有 RECORD 扩展")
            return

        # 只要这两个，事件量最小
        ranges = [
            {
                "core_requests": (0, 0),
                "core_replies": (0, 0),
                "ext_requests": (0, 0, 0, 0),
                "ext_replies": (0, 0, 0, 0),
                "delivered_events": (0, 0),
                "device_events": (X.KeyPress, X.ButtonRelease),
                "errors": (0, 0),
                "client_started": False,
                "client_died": False,
            }
        ]

        def handler(reply):
            if reply.category != xrecord.FromServer:
                return
            if reply.client_swapped:
                return
            data = reply.data
            if not data or data[0] < 2:
                return
            while len(data):
                try:
                    ev, data = xrq.EventField(None).parse_binary_value(
                        data, d.display, None, None
                    )
                except Exception:
                    return
                if ev.type in (X.KeyPress, X.KeyRelease):
                    self.key.emit(ev.detail, ev.type == X.KeyPress)
                elif ev.type in (X.ButtonPress, X.ButtonRelease):
                    self.button.emit(
                        ev.detail, ev.type == X.ButtonPress, ev.root_x, ev.root_y
                    )

        try:
            ctx = d.record_create_context(
                0, [xrecord.AllClients], ranges
            )
            d.record_enable_context(ctx, handler)
            d.record_free_context(ctx)
        except Exception as exc:
            self.failed.emit("启动 XRecord 失败：%s" % exc)


# ---------------------------------------------------------------- 主窗口

class Pet(QWidget):
    def __init__(self, cfg):
        super().__init__(None, WINDOW_FLAGS)
        self.cfg = cfg
        self.keymap = build_keymap()
        self.held = set()
        self.last_pointer = None
        self.guard = None            # (时间, x, y)：睡觉静默期
        self.down = False
        self.press_at = None
        self.maybe_drag = False
        self.dragging = False
        self.grab_off = QPoint()
        self.last_click_at = 0.0

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)

        self.view = QWebEngineView(self)
        self.view.setAttribute(Qt.WA_TranslucentBackground, True)
        self.view.setStyleSheet("background: transparent;")
        self.view.page().setBackgroundColor(QColor(0, 0, 0, 0))
        self.view.setContextMenuPolicy(Qt.NoContextMenu)
        self.view.load(QUrl.fromLocalFile(str(INDEX)))
        self.view.loadFinished.connect(self.on_loaded)

        self.apply_geometry()

        # 33ms ≈ 30Hz，和 Windows 版一致
        self.tick = QTimer(self)
        self.tick.timeout.connect(self.on_tick)
        self.tick.start(33)

        self.rec = XRecorder()
        self.rec.key.connect(self.on_key)
        self.rec.button.connect(self.on_button)
        self.rec.failed.connect(lambda m: log("XRecord:", m))
        self.rec.start()

    # ---------------- 窗口尺寸与位置

    def pet_size(self):
        s = float(self.cfg.get("scale") or 1.0)
        return int(BASE_W * s), int(BASE_H * s)

    def apply_geometry(self):
        w, h = self.pet_size()
        self.resize(w, h)
        self.view.resize(w, h)
        self.view.move(0, 0)
        g = QApplication.primaryScreen().availableGeometry()
        x, y = self.cfg.get("x"), self.cfg.get("y")
        if x is None or y is None:
            self.move(g.right() - w - 48, g.bottom() - h - 24)
        else:
            # 换过显示器或改过分辨率后，别让猫跑到屏幕外面去
            x = min(max(int(x), g.left() - w + 80), g.right() - 80)
            y = min(max(int(y), g.top()), g.bottom() - 60)
            self.move(x, y)

    # ---------------- 显示

    def showEvent(self, e):
        super().showEvent(e)
        # Qt 5.11 没有 WindowTransparentForInput，show 之后手动把输入形状置空。
        # winId() 必须等窗口真正建出来才有效，所以放在这里而不是 __init__。
        if not HAS_QT_TRANSPARENT and not getattr(self, "_ct_done", False):
            self._ct_done = set_click_through(int(self.winId()))
            log("Qt 5.11 兜底穿透:", self._ct_done)

    # ---------------- 页面通信

    def js(self, code):
        self.view.page().runJavaScript(code)

    def cmd(self, kind, value=None):
        payload = {"type": kind}
        if value is not None:
            payload["value"] = value
        self.js("window.__qt && window.__qt.cmd(%s)" % json.dumps(payload))

    def emit_config(self):
        self.js(
            "window.__qt && window.__qt.cmd(%s)"
            % json.dumps({"type": "config", "cfg": self.cfg})
        )

    def on_loaded(self, ok):
        log("页面加载完成", ok)
        # 给 cat.js 一点初始化时间，再推配置（glue.js 收到 config 才会 createCat）
        QTimer.singleShot(400, self.emit_config)

    # ---------------- 命中测试

    def hit(self, x, y):
        """屏幕坐标 → 是否落在猫身上（猫身椭圆 + 键盘横条，和 Windows 版同一套参数）"""
        if self.cfg.get("locked"):
            return False
        w, h = self.width(), self.height()
        lx, ly = x - self.x(), y - self.y()
        if lx < 0 or ly < 0 or lx > w or ly > h:
            return False
        nx, ny = lx / max(w, 1), ly / max(h, 1)
        cx, cy, rx, ry = 0.5, 0.44, 0.235, 0.33
        if ((nx - cx) / rx) ** 2 + ((ny - cy) / ry) ** 2 <= 1.0:
            return True
        return 0.15 < nx < 0.85 and 0.60 < ny < 0.80

    def in_head(self, x, y):
        """头部区域留给「摸猫」，不要用来拖窗口"""
        w, h = self.width(), self.height()
        nx = (x - self.x()) / max(w, 1)
        ny = (y - self.y()) / max(h, 1)
        return 0.30 < nx < 0.70 and 0.02 < ny < 0.42

    # ---------------- 定时轮询

    def on_tick(self):
        pos = QCursor.pos()
        pt = (pos.x(), pos.y())

        # 睡觉静默期：期间不喂指针（否则 cat.js 的 wake() 会把猫叫醒）
        muted = False
        if self.guard:
            t0, gx, gy = self.guard
            far = (pt[0] - gx) ** 2 + (pt[1] - gy) ** 2 > 200 * 200
            if time.monotonic() - t0 < 30 and not far:
                muted = True
            else:
                self.guard = None

        if self.down and self.maybe_drag and not self.dragging:
            if (pos - self.press_at).manhattanLength() > 6:
                self.dragging = True
                self.grab_off = pos - self.pos()
                log("开始拖动")

        if self.dragging:
            self.move(pos - self.grab_off)
            return

        if muted or pt == self.last_pointer:
            return
        self.last_pointer = pt
        lx, ly = pt[0] - self.x(), pt[1] - self.y()
        self.js("window.__qt && window.__qt.pointer(%d, %d)" % (lx, ly))

    # ---------------- 键盘

    def on_key(self, keycode, is_down):
        code = self.keymap.get(keycode)
        if not code:
            return
        if is_down:
            if code in self.held:
                return
            self.held.add(code)
        else:
            if code not in self.held:
                return
            self.held.discard(code)
        self.js("window.__qt && window.__qt.keys(%s)" % json.dumps(list(self.held)))

    # ---------------- 鼠标按钮

    def on_button(self, button, is_down, rx, ry):
        # XRecord 给的是 X11 物理像素，Qt 的几何是逻辑像素；2 倍屏上直接用会整体偏移。
        # 按钮事件和光标位置在同一时刻，直接问 Qt 要逻辑坐标最稳。
        pos = QCursor.pos()
        x, y = pos.x(), pos.y()
        if button == 3:                      # 右键
            if is_down and self.hit(x, y):
                self.show_menu(pos)
            return
        if button != 1:
            return

        if is_down:
            if not self.hit(x, y):
                return
            now = time.monotonic()
            if now - self.last_click_at < 0.34:   # 双击 = 转一圈
                self.last_click_at = 0.0
                self.cmd("spin")
                return
            self.last_click_at = now
            self.down = True
            self.press_at = pos
            self.dragging = False
            self.maybe_drag = not self.in_head(x, y)
            # 注入合成事件，让 cat.js 自己判断是不是在摸头
            self.synth_pointer("pointerdown", x, y, 1)
        else:
            if not self.down:
                return
            self.down = False
            self.maybe_drag = False
            if self.dragging:
                self.dragging = False
                self.cfg["x"] = self.x()
                self.cfg["y"] = self.y()
                save_cfg(self.cfg)
                log("拖动结束", self.x(), self.y())
            self.synth_pointer("pointerup", x, y, 0)

    def synth_pointer(self, kind, x, y, buttons):
        lx, ly = x - self.x(), y - self.y()
        self.js(
            "(()=>{const st=document.getElementById('stage');if(!st)return;"
            "st.dispatchEvent(new PointerEvent('%s',{clientX:%d,clientY:%d,"
            "button:0,buttons:%d,pointerType:'mouse',bubbles:true,isPrimary:true}));})()"
            % (kind, lx, ly, buttons)
        )

    # ---------------- 菜单

    def show_menu(self, pos):
        m = QMenu()
        size = m.addMenu("大小")
        for v, label in SIZES:
            a = size.addAction(label)
            a.setCheckable(True)
            a.setChecked(abs(float(self.cfg.get("scale", 1.0)) - v) < 0.01)
            a.triggered.connect(lambda _=False, v=v: self.set_scale(v))
        coat = m.addMenu("毛色")
        for cid, label in COATS:
            a = coat.addAction(label)
            a.setCheckable(True)
            a.setChecked(self.cfg.get("coat") == cid)
            a.triggered.connect(lambda _=False, c=cid: self.set_coat(c))
        sleep = m.addMenu("多久睡着")
        for v, label in SLEEPS:
            a = sleep.addAction(label)
            a.setCheckable(True)
            a.setChecked(abs(float(self.cfg.get("sleepMinutes", 15.0)) - v) < 0.01)
            a.triggered.connect(lambda _=False, v=v: self.set_sleep(v))
        m.addSeparator()
        m.addAction("转一圈", lambda: self.cmd("spin"))
        m.addAction("去睡觉", self.sleep_now)
        perf = m.addMenu("让它表演一个")
        for act, label in (("roll", "打个滚"), ("stretch", "伸懒腰"), ("groom", "洗脸洗手"),
                           ("chase", "追自己的尾巴"), ("wave", "抬爪打招呼"), ("peek", "探头看看"),
                           ("scratch", "挠耳朵"), ("hop", "原地蹦一下"), ("sneeze", "打喷嚏"),
                           ("yawn", "打哈欠"), ("loaf", "趴一会儿")):
            perf.addAction(label, lambda _=False, a=act: self.cmd("act", a))
        m.addSeparator()
        auto = m.addAction("开机自动启动")
        auto.setCheckable(True)
        auto.setChecked(AUTOSTART.exists())
        auto.triggered.connect(self.toggle_autostart)
        lock = m.addAction("锁定位置（鼠标穿透）")
        lock.setCheckable(True)
        lock.setChecked(bool(self.cfg.get("locked")))
        lock.triggered.connect(self.toggle_lock)
        m.addSeparator()
        m.addAction("退出小猫", QApplication.quit)
        notice = m.addAction("软件均是免费开源，切勿商用买卖")   # 只是声明，点了不动
        notice.setEnabled(False)
        m.exec_(pos)

    def set_scale(self, v):
        self.cfg["scale"] = v
        save_cfg(self.cfg)
        self.apply_geometry()
        self.emit_config()

    def set_coat(self, cid):
        self.cfg["coat"] = cid
        save_cfg(self.cfg)
        self.cmd("coat", cid)

    def set_sleep(self, v):
        self.cfg["sleepMinutes"] = v
        save_cfg(self.cfg)
        self.cmd("sleepMinutes", v)

    def sleep_now(self):
        pos = QCursor.pos()
        self.guard = (time.monotonic(), pos.x(), pos.y())
        self.cmd("sleepNow")

    def toggle_lock(self):
        self.cfg["locked"] = not bool(self.cfg.get("locked"))
        save_cfg(self.cfg)

    def toggle_autostart(self):
        try:
            if AUTOSTART.exists():
                AUTOSTART.unlink()
            else:
                AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
                # 装成 deb 之后优先用系统启动器（/usr/bin/deskcat），
                # 否则用当前目录下的 run.sh
                launcher = Path("/usr/bin/deskcat")
                exe = str(launcher) if launcher.exists() else str(ROOT / "run.sh")
                AUTOSTART.write_text(
                    "[Desktop Entry]\n"
                    "Type=Application\n"
                    "Name=桌面小猫\n"
                    "Exec=%s\n"
                    "Terminal=false\n"
                    "X-GNOME-Autostart-enabled=true\n" % exe,
                    encoding="utf-8",
                )
        except Exception as exc:
            log("改开机自启失败", exc)


# ---------------------------------------------------------------- 入口

def main():
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    cfg = load_cfg()
    pet = Pet(cfg)
    pet.show()
    # 保证在最上层：某些窗管会在 show 之后重排层级
    pet.raise_()

    # 托盘（DDE 有托盘，失败也不影响用）
    tray = None
    if QSystemTrayIcon.isSystemTrayAvailable():
        icon_path = ROOT / "assets" / "tray.png"
        tray = QSystemTrayIcon(QIcon(str(icon_path)), app)
        tray.setToolTip("桌面小猫")
        tm = QMenu()
        tm.addAction("转一圈", lambda: pet.cmd("spin"))
        tm.addAction("去睡觉", pet.sleep_now)
        tm.addSeparator()
        tm.addAction("退出小猫", app.quit)
        tm_notice = tm.addAction("软件均是免费开源，切勿商用买卖")
        tm_notice.setEnabled(False)
        tray.setContextMenu(tm)
        tray.show()

    log("启动完成，窗口", pet.geometry())
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
