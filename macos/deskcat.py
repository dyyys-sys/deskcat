#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面小猫 —— macOS 版

和另外两个版本的对照
--------------------
Windows：Tauri(Rust) + WebView2，透明无边框窗口 + SetWindowLongPtr 打 WS_EX_TRANSPARENT，
         键盘用 WH_KEYBOARD_LL 低级钩子。
Linux  ：PyQt5 + QtWebEngine，WindowTransparentForInput 把 X11 输入形状置空，
         键盘用 X11 RECORD 扩展。
macOS  ：PyObjC + WKWebView，窗口 setIgnoresMouseEvents:YES 直接不吃鼠标，
         键盘用 CGEventTap（ListenOnly，只旁听不拦截）。

三版的猫是同一套（web/src/cat.js，一行没改），换的只是外壳。

和 Windows/Linux 一样的取舍
  · 窗口「完全不吃鼠标」：点击 100% 穿透，永不抢焦点，也不会闪。
    代价是 DOM 收不到鼠标事件，所以：
      - 光标位置：NSEvent.mouseLocation() 每 33ms 问一次
      - 按键 / 鼠标按钮：CGEventTap 全局旁听（需要「辅助功能」权限）
      - 判定「点在猫身上」之后，把合成的 DOM 事件注入页面，
        让 cat.js 自己走摸猫 / 按键那套逻辑。

macOS 独有的一步：辅助功能权限
  CGEventTap 抓键盘必须有「系统设置 → 隐私与安全性 → 辅助功能」授权，
  否则 tap 创建失败、猫不会跟着敲键盘（鼠标跟随不受影响）。
  首次启动会弹窗引导，也可以用右键菜单里那项打开设置。

线程模型
  CGEventTap 的回调必须挂在有 run loop 的线程上，且绝不能在里面碰 WebKit
  （WKWebView 只能在主线程用，跨线程调用会直接崩）。
  所以：tap 在自己的线程里把事件塞进 deque，主线程 33ms 定时器排空后再去调 JS。
"""

import json
import os
import subprocess
import sys
import threading
import time
import traceback
from collections import deque
from pathlib import Path

DEBUG = os.environ.get("CATPET_DEBUG", "")

# 日志必须常开：这个包不带终端，出事时用户唯一能给我的东西就是这个文件
LOG_PATH = Path.home() / "Library" / "Logs" / "DesktopCat.log"


def log(*a):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), " ".join(str(x) for x in a))
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    if DEBUG:
        print("[cat]", *a, flush=True)


def alert(title, body):
    """没有终端，出错只能靠系统弹窗"""
    try:
        subprocess.run(
            ["/usr/bin/osascript", "-e",
             'display alert "%s" message "%s" as critical' % (title, body)],
            capture_output=True, timeout=120,
        )
    except Exception:
        pass


def _crash_hook(tp, val, tb):
    text = "".join(traceback.format_exception(tp, val, tb))
    log("!!! 未捕获异常:\n" + text)
    alert("小猫出错了", "详情已写进 ~/Library/Logs/DesktopCat.log。")


sys.excepthook = _crash_hook


# ---------------------------------------------------------------- 依赖

try:
    import objc
    import AppKit
    import CoreFoundation
    import Foundation
    import Quartz
    import WebKit
    import ApplicationServices
except ImportError as exc:
    sys.stderr.write(
        "缺少依赖：%s\n\n"
        "macOS 版需要 PyObjC。正常双击「安装.command」会自动装好；\n"
        "手动装的话：\n"
        "    python3 -m venv ~/Library/Application\\ Support/DeskCat/venv\n"
        "    ~/Library/Application\\ Support/DeskCat/venv/bin/pip install \\\n"
        "        pyobjc-framework-Cocoa pyobjc-framework-WebKit \\\n"
        "        pyobjc-framework-Quartz pyobjc-framework-ApplicationServices\n" % exc
    )
    sys.exit(1)


# PyObjC 里有一部分名字其实是 C 的 #define 宏（不是 enum），框架不一定导出。
# 直接 from xxx import yyy 的话，少一个名字整个程序都起不来，
# 所以这里逐个取：必须有的记进 _MISSING，可有可无的给默认值。
_MISSING = []


def _need(mod, name):
    v = getattr(mod, name, None)
    if v is None:
        _MISSING.append("%s.%s" % (mod.__name__, name))
    return v


def _opt(mod, name, default):
    return getattr(mod, name, default)


# ---- AppKit ----
NSAlert = _need(AppKit, "NSAlert")
NSApplication = _need(AppKit, "NSApplication")
NSApplicationActivationPolicyAccessory = _need(AppKit, "NSApplicationActivationPolicyAccessory")
NSBackingStoreBuffered = _need(AppKit, "NSBackingStoreBuffered")
NSColor = _need(AppKit, "NSColor")
NSImage = _need(AppKit, "NSImage")
NSMenu = _need(AppKit, "NSMenu")
NSMenuItem = _need(AppKit, "NSMenuItem")
NSEvent = _need(AppKit, "NSEvent")
NSScreen = _need(AppKit, "NSScreen")
NSStatusBar = _need(AppKit, "NSStatusBar")
NSWindow = _need(AppKit, "NSWindow")
NSWindowStyleMaskBorderless = _need(AppKit, "NSWindowStyleMaskBorderless")
NSWindowCollectionBehaviorCanJoinAllSpaces = _need(AppKit, "NSWindowCollectionBehaviorCanJoinAllSpaces")
NSWindowCollectionBehaviorFullScreenAuxiliary = _need(AppKit, "NSWindowCollectionBehaviorFullScreenAuxiliary")
NSWindowCollectionBehaviorStationary = _need(AppKit, "NSWindowCollectionBehaviorStationary")
NSWorkspace = _need(AppKit, "NSWorkspace")
# 这两个在头文件里是 static const / #define，值分别是 3 和 -1
NSFloatingWindowLevel = _opt(AppKit, "NSFloatingWindowLevel", 3)
NSVariableStatusItemLength = _opt(AppKit, "NSVariableStatusItemLength", -1.0)

# ---- Foundation ----
NSObject = _need(Foundation, "NSObject")
NSPoint = _need(Foundation, "NSPoint")
NSMakeRect = _need(Foundation, "NSMakeRect")
NSURL = _need(Foundation, "NSURL")
NSTimer = _need(Foundation, "NSTimer")

# ---- WebKit ----
WKWebView = _need(WebKit, "WKWebView")
WKWebViewConfiguration = _need(WebKit, "WKWebViewConfiguration")

# ---- CoreFoundation ----
CFMachPortCreateRunLoopSource = _need(CoreFoundation, "CFMachPortCreateRunLoopSource")
CFRunLoopAddSource = _need(CoreFoundation, "CFRunLoopAddSource")
CFRunLoopGetCurrent = _need(CoreFoundation, "CFRunLoopGetCurrent")
CFRunLoopRun = _need(CoreFoundation, "CFRunLoopRun")
kCFRunLoopCommonModes = _need(CoreFoundation, "kCFRunLoopCommonModes")

# ---- Quartz ----
CGEventGetFlags = _need(Quartz, "CGEventGetFlags")
CGEventGetIntegerValueField = _need(Quartz, "CGEventGetIntegerValueField")
CGEventTapCreate = _need(Quartz, "CGEventTapCreate")
CGEventTapEnable = _need(Quartz, "CGEventTapEnable")
kCGEventFlagsChanged = _need(Quartz, "kCGEventFlagsChanged")
kCGEventKeyDown = _need(Quartz, "kCGEventKeyDown")
kCGEventKeyUp = _need(Quartz, "kCGEventKeyUp")
kCGEventLeftMouseDown = _need(Quartz, "kCGEventLeftMouseDown")
kCGEventLeftMouseUp = _need(Quartz, "kCGEventLeftMouseUp")
kCGEventRightMouseDown = _need(Quartz, "kCGEventRightMouseDown")
kCGEventRightMouseUp = _need(Quartz, "kCGEventRightMouseUp")
kCGEventOtherMouseDown = _need(Quartz, "kCGEventOtherMouseDown")
kCGEventOtherMouseUp = _need(Quartz, "kCGEventOtherMouseUp")
kCGEventTapOptionListenOnly = _need(Quartz, "kCGEventTapOptionListenOnly")
kCGHeadInsertEventTap = _need(Quartz, "kCGHeadInsertEventTap")
kCGKeyboardEventKeycode = _need(Quartz, "kCGKeyboardEventKeycode")
kCGSessionEventTap = _need(Quartz, "kCGSessionEventTap")
# 这两个是 #define，不是 enum，PyObjC 常常没有导出
kCGEventTapDisabledByTimeout = _opt(Quartz, "kCGEventTapDisabledByTimeout", -2)
kCGEventTapDisabledByUserInput = _opt(Quartz, "kCGEventTapDisabledByUserInput", -1)

# ---- ApplicationServices ----
AXIsProcessTrusted = _need(ApplicationServices, "AXIsProcessTrusted")
AXIsProcessTrustedWithOptions = _need(ApplicationServices, "AXIsProcessTrustedWithOptions")
kAXTrustedCheckOptionPrompt = _opt(
    ApplicationServices, "kAXTrustedCheckOptionPrompt", "AXTrustedCheckOptionPrompt"
)

if _MISSING:
    sys.stderr.write(
        "PyObjC 版本不匹配，缺这些符号：\n  %s\n\n"
        "试试升级：\n"
        "    pip install -U pyobjc-framework-Cocoa pyobjc-framework-WebKit "
        "pyobjc-framework-Quartz pyobjc-framework-ApplicationServices\n"
        "（完整报错一并贴出来更好定位）\n" % "\n  ".join(_MISSING)
    )
    sys.exit(1)


# ---------------------------------------------------------------- 常量

BASE_W, BASE_H = 400, 340

# 打包后 .pyc 会被编译到 ~/Library/Application Support/DeskCat/run/，
# 而网页和图标还在 app 包里，所以资源目录由启动器通过环境变量指定。
ROOT = Path(os.environ.get("DESKCAT_ASSETS") or Path(__file__).resolve().parent)
INDEX = ROOT / "web" / "index.html"
TRAY_PNG = ROOT / "assets" / "tray.png"

CFG_DIR = Path.home() / "Library" / "Application Support" / "DeskCat"
CFG_PATH = CFG_DIR / "config.json"
AGENT_PATH = Path.home() / "Library" / "LaunchAgents" / "com.deskcat.pet.plist"

DEFAULT_CFG = {
    "x": None,
    "y": None,
    "scale": 1.0,
    "coat": "tuxedo",
    "sleepMinutes": 15.0,
    "leftMouse": False,
    "locked": False,
    "axPrompted": False,
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

# macOS 虚拟键码（Carbon kVK_*）→ DOM KeyboardEvent.code
# cat.js 画的是标准 ANSI 布局（没有 F 行、没有方向键、没有数字键区），
# 所以小键盘按键在这里映射到主键盘的数字/符号键，和 Linux 版保持一致。
MAC_VK = {
    0: "KeyA", 1: "KeyS", 2: "KeyD", 3: "KeyF", 4: "KeyH", 5: "KeyG",
    6: "KeyZ", 7: "KeyX", 8: "KeyC", 9: "KeyV", 11: "KeyB",
    12: "KeyQ", 13: "KeyW", 14: "KeyE", 15: "KeyR", 16: "KeyY", 17: "KeyT",
    18: "Digit1", 19: "Digit2", 20: "Digit3", 21: "Digit4", 22: "Digit6",
    23: "Digit5", 24: "Equal", 25: "Digit9", 26: "Digit7", 27: "Minus",
    28: "Digit8", 29: "Digit0",
    30: "BracketRight", 31: "KeyO", 32: "KeyU", 33: "BracketLeft",
    34: "KeyI", 35: "KeyP", 36: "Enter", 37: "KeyL", 38: "KeyJ",
    39: "Quote", 40: "KeyK", 41: "Semicolon", 42: "Backslash",
    43: "Comma", 44: "Slash", 45: "KeyN", 46: "KeyM", 47: "Period",
    48: "Tab", 49: "Space", 50: "Backquote", 51: "Backspace", 53: "Escape",
    54: "MetaRight", 55: "MetaLeft",
    56: "ShiftLeft", 57: "CapsLock", 58: "AltLeft", 59: "ControlLeft",
    60: "ShiftRight", 61: "AltRight", 62: "ControlRight",
    # 小键盘
    65: "Period", 67: "KeyX", 69: "Equal", 75: "Slash", 76: "Enter",
    78: "Minus",
    82: "Digit0", 83: "Digit1", 84: "Digit2", 85: "Digit3", 86: "Digit4",
    87: "Digit5", 88: "Digit6", 89: "Digit7", 91: "Digit8", 92: "Digit9",
}

# 修饰键在 macOS 上走 FlagsChanged，不是 KeyDown/KeyUp，得按 flag 位判断按下还是松开
MOD_FLAGS = {
    56: 0x00020000, 60: 0x00020000,   # Shift
    59: 0x00040000, 62: 0x00040000,   # Control
    58: 0x00080000, 61: 0x00080000,   # Option
    55: 0x00100000, 54: 0x00100000,   # Command
    57: 0x00010000,                   # CapsLock
}

HOLD_MAX = 2.0        # 超过 2 秒没等到 keyUp 就强行松开，防止爪子卡住


def primary_screen_size():
    """主屏尺寸（逻辑点）。拿不到就给个兜底值 —— 无头环境 / 远程登录时别崩。"""
    try:
        scr = NSScreen.screens()
        if scr:
            s = scr[0].frame().size
            return float(s.width), float(s.height)
    except Exception as exc:
        log("读屏幕尺寸失败", exc)
    return 1440.0, 900.0


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
        log("存配置失败", exc)


# ---------------------------------------------------------------- 全局事件捕获

class KeyTap(threading.Thread):
    """CGEventTap 旁听线程。ListenOnly：不拦截、不改写任何事件。"""

    def __init__(self, q):
        super().__init__(daemon=True)
        self.q = q
        self.error = None
        self.tap = None
        self.ready = threading.Event()

    def _callback(self, proxy, type_, event, refcon):
        try:
            if type_ in (kCGEventTapDisabledByTimeout, kCGEventTapDisabledByUserInput,
                         -2, 0xFFFFFFFE):
                # 回调太慢会被系统关掉，重新打开
                if self.tap:
                    CGEventTapEnable(self.tap, True)
                return event

            if type_ in (kCGEventKeyDown, kCGEventKeyUp, kCGEventFlagsChanged):
                kc = int(CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode))
                code = MAC_VK.get(kc)
                if not code:
                    return event
                if type_ == kCGEventFlagsChanged:
                    mask = MOD_FLAGS.get(kc)
                    if not mask:
                        return event
                    down = bool(int(CGEventGetFlags(event)) & mask)
                else:
                    down = (type_ == kCGEventKeyDown)
                self.q.append(("key", code, down))
            elif type_ in (kCGEventLeftMouseDown, kCGEventLeftMouseUp):
                self.q.append(("btn", 1, type_ == kCGEventLeftMouseDown))
            elif type_ in (kCGEventRightMouseDown, kCGEventRightMouseUp):
                self.q.append(("btn", 3, type_ == kCGEventRightMouseDown))
            elif type_ in (kCGEventOtherMouseDown, kCGEventOtherMouseUp):
                self.q.append(("btn", 2, type_ == kCGEventOtherMouseDown))
        except Exception as exc:            # 回调里绝不能抛
            log("tap 回调异常", exc)
        return event

    def run(self):
        try:
            mask = 0
            for t in (kCGEventKeyDown, kCGEventKeyUp, kCGEventFlagsChanged,
                      kCGEventLeftMouseDown, kCGEventLeftMouseUp,
                      kCGEventRightMouseDown, kCGEventRightMouseUp,
                      kCGEventOtherMouseDown, kCGEventOtherMouseUp):
                mask |= (1 << t)

            self.tap = CGEventTapCreate(
                kCGSessionEventTap, kCGHeadInsertEventTap,
                kCGEventTapOptionListenOnly, mask, self._callback, None,
            )
            if not self.tap:
                self.error = ("创建事件监听失败。通常是没给「辅助功能」权限，"
                              "或终端 / 桌面小猫没有加到列表里。")
                self.ready.set()
                return

            src = CFMachPortCreateRunLoopSource(None, self.tap, 0)
            CFRunLoopAddSource(CFRunLoopGetCurrent(), src, kCFRunLoopCommonModes)
            CGEventTapEnable(self.tap, True)
            self.ready.set()
            CFRunLoopRun()
        except Exception as exc:
            self.error = "事件监听线程异常：%s" % exc
            self.ready.set()


# ---------------------------------------------------------------- 页面回调

class NavDelegate(NSObject):
    """页面加载完成回调（WKWebView 必须靠 delegate 才能知道加载完了）"""

    def initWithOwner_(self, owner):
        self = objc.super(NavDelegate, self).init()
        if self is None:
            return None
        self.owner = owner
        return self

    def webView_didFinishNavigation_(self, webview, nav):
        try:
            self.owner.on_page_loaded()
        except Exception as exc:
            log("didFinish 异常", exc)

    def webView_webContentProcessDidTerminate_(self, webview):
        log("WebContent 进程挂了")
        try:
            self.owner.js("location.reload()")
        except Exception:
            pass


class MenuTarget(NSObject):
    """NSMenu 的 action 目标。NSMenuItem 不好带 Python 闭包，用 tag 查表。

    tag 按「菜单项标题」固定分配，不随重建变化 —— 否则菜单栏那个菜单
    在别处重建之后 tag 就会指错人。"""

    def init(self):
        self = objc.super(MenuTarget, self).init()
        if self is None:
            return None
        self._by_tag = {}
        self._tag_of = {}
        self._seq = 0
        return self

    def add(self, key, cb):
        tag = self._tag_of.get(key)
        if tag is None:
            self._seq += 1
            tag = self._seq
            self._tag_of[key] = tag
        self._by_tag[tag] = cb
        return tag

    def menuAction_(self, sender):
        cb = self._by_tag.get(int(sender.tag()))
        if cb:
            try:
                cb()
            except Exception as exc:
                log("菜单回调异常", exc)


# ---------------------------------------------------------------- 主窗口

class Pet:
    def __init__(self, cfg):
        self.cfg = cfg
        self.held = {}              # code -> 按下时间
        self.keys_dirty = False
        self.buttons = set()
        self.q = deque()
        self.last_pointer = None
        self.guard = None           # (时间, x, y)：睡觉静默期
        self.down = False
        self.press_at = None
        self.maybe_drag = False
        self.dragging = False
        self.grab_off = (0.0, 0.0)
        self.last_click_at = 0.0
        self.pos = None             # 窗口左上角（屏幕坐标，y 向下）
        self.ax_alerted = False

        self.menu_target = MenuTarget.alloc().init()

        self.screen_h = primary_screen_size()[1]

        w, h = self.pet_size()
        x, y = self.init_position(w, h)
        self.pos = [x, y]

        self.win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, self.screen_h - y - h, w, h),
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False,
        )
        self.win.setOpaque_(False)
        self.win.setBackgroundColor_(NSColor.clearColor())
        self.win.setHasShadow_(False)
        self.win.setLevel_(NSFloatingWindowLevel)
        # ★ 关键：整个窗口不吃鼠标。等效于 Linux 的输入形状置空 / Windows 的 WS_EX_TRANSPARENT，
        #   但更彻底 —— 连 hover 都不会触发，也永远不会成为 key window。
        self.win.setIgnoresMouseEvents_(True)
        self.win.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        self.win.setReleasedWhenClosed_(False)

        cv = self.win.contentView()
        try:
            cv.setWantsLayer_(True)
            cv.layer().setBackgroundColor_(NSColor.clearColor().CGColor())
        except Exception as exc:
            log("contentView 透明失败", exc)

        # ---- WKWebView ----
        conf = WKWebViewConfiguration.alloc().init()
        self.web = WKWebView.alloc().initWithFrame_configuration_(
            NSMakeRect(0, 0, w, h), conf
        )
        self.web.setOpaque_(False)
        # WKWebView 的透明背景没有公开 API，业界通行做法是 KVC 打私有属性
        for key, val in (("_drawsTransparentBackground", True), ("drawsBackground", False)):
            try:
                self.web.setValue_forKey_(val, key)
            except Exception as exc:
                log("KVC 失败", key, exc)
        for fn in ("setUnderPageBackgroundColor_",):
            try:
                getattr(self.web, fn)(NSColor.clearColor())
            except Exception:
                pass
        try:
            self.web.setWantsLayer_(True)
            self.web.layer().setBackgroundColor_(NSColor.clearColor().CGColor())
        except Exception as exc:
            log("webview 图层透明失败", exc)

        self.nav = NavDelegate.alloc().initWithOwner_(self)
        self.web.setNavigationDelegate_(self.nav)
        cv.addSubview_(self.web)

        self.web.loadFileURL_allowingReadAccessToURL_(
            NSURL.fileURLWithPath_(str(INDEX)),
            NSURL.fileURLWithPath_(str(ROOT)),
        )

    # ---------------- 尺寸 / 位置

    def pet_size(self):
        s = float(self.cfg.get("scale") or 1.0)
        return int(BASE_W * s), int(BASE_H * s)

    def init_position(self, w, h):
        scr_w, scr_h = primary_screen_size()
        x, y = self.cfg.get("x"), self.cfg.get("y")
        if x is None or y is None:
            return int(scr_w - w - 48), int(scr_h - h - 24)
        # 换过显示器 / 改过分辨率后别让猫跑到屏幕外面
        x = min(max(int(x), -w + 80), int(scr_w) - 80)
        y = min(max(int(y), 0), int(scr_h) - 60)
        return x, y

    def apply_geometry(self):
        w, h = self.pet_size()
        x, y = self.pos
        self.win.setFrame_display_(((x, self.screen_h - y - h), (w, h)), True)
        self.web.setFrame_(((0, 0), (w, h)))
        self.pos = [x, y]

    def move_to(self, x, y):
        w, h = self.pet_size()
        self.win.setFrameOrigin_((x, self.screen_h - y - h))
        self.pos = [x, y]

    def screen_point(self):
        """当前光标位置，换算成「左上角原点、y 向下」的屏幕坐标"""
        p = NSEvent.mouseLocation()
        return float(p.x), self.screen_h - float(p.y)

    # ---------------- 页面通信

    def js(self, code):
        try:
            self.web.evaluateJavaScript_completionHandler_(code, None)
        except Exception as exc:
            log("evaluateJavaScript 失败", exc)

    def cmd(self, kind, value=None):
        payload = {"type": kind}
        if value is not None:
            payload["value"] = value
        self.js("window.__mac && window.__mac.cmd(%s)" % json.dumps(payload))

    def emit_config(self):
        self.js("window.__mac && window.__mac.cmd(%s)"
                % json.dumps({"type": "config", "cfg": self.cfg}))

    def on_page_loaded(self):
        log("页面加载完成")
        # 给 cat.js 一点初始化时间，再推配置（glue.js 收到 config 才会 createCat）
        NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
            0.4, False, lambda t: self.emit_config()
        )

    # ---------------- 命中测试

    def hit(self, x, y):
        if self.cfg.get("locked"):
            return False
        w, h = self.pet_size()
        wx, wy = self.pos
        lx, ly = x - wx, y - wy
        if lx < 0 or ly < 0 or lx > w or ly > h:
            return False
        nx, ny = lx / max(w, 1), ly / max(h, 1)
        cx, cy, rx, ry = 0.5, 0.44, 0.235, 0.33
        if ((nx - cx) / rx) ** 2 + ((ny - cy) / ry) ** 2 <= 1.0:
            return True
        return 0.15 < nx < 0.85 and 0.60 < ny < 0.80

    def in_head(self, x, y):
        w, h = self.pet_size()
        wx, wy = self.pos
        nx = (x - wx) / max(w, 1)
        ny = (y - wy) / max(h, 1)
        return 0.30 < nx < 0.70 and 0.02 < ny < 0.42

    # ---------------- 主循环

    def tick(self):
        # 定时器回调不能把异常抛回 ObjC，否则一次 JS 报错就等于停表
        try:
            self._tick()
        except Exception as exc:
            log("tick 异常", exc)

    def _tick(self):
        # 1) 排空事件队列（tap 线程只往这里塞，绝不直接碰 WebKit）
        while True:
            try:
                ev = self.q.popleft()
            except IndexError:
                break
            if ev[0] == "key":
                self.on_key(ev[1], ev[2])
            else:
                self.on_button(ev[1], ev[2])

        # 卡键兜底：tap 偶尔会漏掉 keyUp（比如权限中途被撤销）
        now = time.monotonic()
        stale = [c for c, t in self.held.items() if now - t > HOLD_MAX]
        if stale:
            for c in stale:
                self.held.pop(c, None)
            self.keys_dirty = True

        if self.keys_dirty:
            self.keys_dirty = False
            self.js("window.__mac && window.__mac.keys(%s)"
                    % json.dumps(list(self.held.keys())))

        # 2) 睡觉静默期：期间不喂指针（否则 cat.js 的 wake() 会把猫叫醒）
        pt = self.screen_point()
        muted = False
        if self.guard:
            t0, gx, gy = self.guard
            far = (pt[0] - gx) ** 2 + (pt[1] - gy) ** 2 > 200 * 200
            if time.monotonic() - t0 < 30 and not far:
                muted = True
            else:
                self.guard = None

        # 3) 拖动
        if self.down and self.maybe_drag and not self.dragging:
            dx = pt[0] - self.press_at[0]
            dy = pt[1] - self.press_at[1]
            if abs(dx) + abs(dy) > 6:
                self.dragging = True
                self.grab_off = (pt[0] - self.pos[0], pt[1] - self.pos[1])
                log("开始拖动")

        if self.dragging:
            self.move_to(pt[0] - self.grab_off[0], pt[1] - self.grab_off[1])
            return

        # 4) 光标喂给 cat.js（位置没变就不发，省 CPU）
        if muted or pt == self.last_pointer:
            return
        self.last_pointer = pt
        self.js("window.__mac && window.__mac.pointer(%d, %d)"
                % (int(pt[0] - self.pos[0]), int(pt[1] - self.pos[1])))

    # ---------------- 键盘

    def on_key(self, code, is_down):
        if is_down:
            if code in self.held and time.monotonic() - self.held[code] < 0.03:
                return                       # 系统自动重复，忽略
            self.held[code] = time.monotonic()
        else:
            if code not in self.held:
                return
            self.held.pop(code, None)
        self.keys_dirty = True

    # ---------------- 鼠标按钮

    def on_button(self, button, is_down):
        x, y = self.screen_point()
        if button == 3:
            if is_down and self.hit(x, y):
                self.show_menu(x, y)
            return
        if button != 1:
            return

        if is_down:
            self.buttons.add("left")
            if not self.hit(x, y):
                self.keys_dirty = True
                return
            now = time.monotonic()
            if now - self.last_click_at < 0.34:      # 双击 = 转一圈
                self.last_click_at = 0.0
                self.cmd("spin")
                return
            self.last_click_at = now
            self.down = True
            self.press_at = (x, y)
            self.dragging = False
            self.maybe_drag = not self.in_head(x, y)
            self.synth_pointer("pointerdown", x, y, 1)
        else:
            self.buttons.discard("left")
            if not self.down:
                self.keys_dirty = True
                return
            self.down = False
            self.maybe_drag = False
            if self.dragging:
                self.dragging = False
                self.cfg["x"], self.cfg["y"] = int(self.pos[0]), int(self.pos[1])
                save_cfg(self.cfg)
                log("拖动结束", self.pos)
            self.synth_pointer("pointerup", x, y, 0)
            self.keys_dirty = True

    def synth_pointer(self, kind, x, y, buttons):
        wx, wy = self.pos
        self.js(
            "(()=>{const st=document.getElementById('stage');if(!st)return;"
            "st.dispatchEvent(new PointerEvent('%s',{clientX:%d,clientY:%d,"
            "button:0,buttons:%d,pointerType:'mouse',bubbles:true,isPrimary:true}));})()"
            % (kind, int(x - wx), int(y - wy), buttons)
        )

    # ---------------- 菜单

    def _item(self, menu, title, cb, checked=None, submenu=None):
        it = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            title, "menuAction:", ""
        )
        if submenu is not None:          # 带子菜单的那一项自己不接动作
            it.setSubmenu_(submenu)
            menu.addItem_(it)
            return it
        it.setTarget_(self.menu_target)
        it.setTag_(self.menu_target.add(title, cb))
        if checked is not None:
            it.setState_(1 if checked else 0)
        menu.addItem_(it)
        return it

    @staticmethod
    def _submenu_item(title, submenu):
        """只有子菜单、自己不执行动作的父项"""
        it = NSMenuItem.alloc().init()
        it.setTitle_(title)
        it.setSubmenu_(submenu)
        return it

    @staticmethod
    def _notice(menu, title):
        """一行不可点的声明：灰着放在最底下，点了也没反应"""
        it = NSMenuItem.alloc().init()
        it.setTitle_(title)
        it.setEnabled_(False)
        menu.addItem_(it)
        return it

    def build_menu(self):
        m = NSMenu.alloc().initWithTitle_("")

        if not AXIsProcessTrusted():
            self._item(m, "⚠️ 没拿到辅助功能权限，点这里去开", self.open_ax_settings)
            m.addItem_(NSMenuItem.separatorItem())

        size = NSMenu.alloc().initWithTitle_("大小")
        for v, label in SIZES:
            self._item(size, label, lambda v=v: self.set_scale(v),
                       abs(float(self.cfg.get("scale", 1.0)) - v) < 0.01)
        m.addItem_(self._submenu_item("大小", size))

        coat = NSMenu.alloc().initWithTitle_("毛色")
        for cid, label in COATS:
            self._item(coat, label, lambda c=cid: self.set_coat(c),
                       self.cfg.get("coat") == cid)
        m.addItem_(self._submenu_item("毛色", coat))

        sleep = NSMenu.alloc().initWithTitle_("多久睡着")
        for v, label in SLEEPS:
            self._item(sleep, label, lambda v=v: self.set_sleep(v),
                       abs(float(self.cfg.get("sleepMinutes", 15.0)) - v) < 0.01)
        m.addItem_(self._submenu_item("多久睡着", sleep))

        m.addItem_(NSMenuItem.separatorItem())
        self._item(m, "转一圈", lambda: self.cmd("spin"))
        self._item(m, "去睡觉", self.sleep_now)
        perf = NSMenu.alloc().init()
        for act, label in (("roll", "打个滚"), ("stretch", "伸懒腰"), ("groom", "洗脸洗手"),
                           ("chase", "追自己的尾巴"), ("wave", "抬爪打招呼"), ("peek", "探头看看"),
                           ("scratch", "挠耳朵"), ("hop", "原地蹦一下"), ("sneeze", "打喷嚏"),
                           ("yawn", "打哈欠"), ("loaf", "趴一会儿")):
            self._item(perf, label, lambda a=act: self.cmd("act", a))
        self._item(m, "让它表演一个", None, submenu=perf)
        m.addItem_(NSMenuItem.separatorItem())
        self._item(m, "开机自动启动", self.toggle_autostart, AGENT_PATH.exists())
        self._item(m, "锁定位置（鼠标穿透）", self.toggle_lock, bool(self.cfg.get("locked")))
        self._item(m, "打开配置文件所在文件夹", self.reveal_config)
        self._item(m, "打开日志文件", self.open_log)
        m.addItem_(NSMenuItem.separatorItem())
        self._item(m, "退出小猫", self.quit)
        self._notice(m, "软件均是免费开源，切勿商用买卖")
        return m

    def show_menu(self, x, y):
        m = self.build_menu()
        # view 传 nil 时坐标是屏幕坐标系（原点在左上角），正好和我们的一致
        m.popUpMenuPositioningItem_atLocation_inView_(None, NSPoint(x, y), None)
        # 保持引用，别在弹出过程中被回收
        self._menu_ref = m

    # ---------------- 动作

    def refresh_tray(self):
        """菜单栏那个菜单是常驻的，改完设置要重建一次，勾选状态才对"""
        item = getattr(self, "status_item", None)
        if item is not None:
            try:
                item.setMenu_(self.build_menu())
            except Exception as exc:
                log("刷新菜单栏菜单失败", exc)

    def set_scale(self, v):
        self.cfg["scale"] = v
        save_cfg(self.cfg)
        self.apply_geometry()
        self.emit_config()
        self.refresh_tray()

    def set_coat(self, cid):
        self.cfg["coat"] = cid
        save_cfg(self.cfg)
        self.cmd("coat", cid)
        self.refresh_tray()

    def set_sleep(self, v):
        self.cfg["sleepMinutes"] = v
        save_cfg(self.cfg)
        self.cmd("sleepMinutes", v)
        self.refresh_tray()

    def sleep_now(self):
        x, y = self.screen_point()
        self.guard = (time.monotonic(), x, y)
        self.cmd("sleepNow")

    def toggle_lock(self):
        self.cfg["locked"] = not bool(self.cfg.get("locked"))
        save_cfg(self.cfg)
        self.refresh_tray()

    def reveal_config(self):
        CFG_DIR.mkdir(parents=True, exist_ok=True)
        NSWorkspace.sharedWorkspace().openURL_(
            NSURL.fileURLWithPath_(str(CFG_DIR))
        )

    def open_log(self):
        """出问题时要的东西：把日志文件在访达里选中"""
        try:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            if not LOG_PATH.exists():
                LOG_PATH.write_text("", encoding="utf-8")
            subprocess.run(["/usr/bin/open", "-R", str(LOG_PATH)],
                           capture_output=True)
        except Exception as exc:
            log("打开日志失败", exc)

    def quit(self):
        try:
            self.cfg["x"], self.cfg["y"] = int(self.pos[0]), int(self.pos[1])
            save_cfg(self.cfg)
        except Exception:
            pass
        NSApplication.sharedApplication().terminate_(None)

    # ---------------- 辅助功能权限

    def check_accessibility(self, prompt=True):
        try:
            if AXIsProcessTrusted():
                return True
            if prompt:
                AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
        except Exception as exc:
            log("检查辅助功能权限失败", exc)
        return False

    def open_ax_settings(self):
        url = ("x-apple.systempreferences:com.apple.preference.security"
               "?Privacy_Accessibility")
        NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(url))

    def late_ax_alert(self):
        """系统那个授权框用户可能点了「拒绝」，这里再补一段人话说明"""
        try:
            if AXIsProcessTrusted():
                return
        except Exception:
            pass
        self.ax_alert()

    def ax_alert(self):
        """首次没权限时弹一次，说清楚要做什么"""
        if self.ax_alerted:
            return
        self.ax_alerted = True
        a = NSAlert.alloc().init()
        a.setMessageText_("小猫还差一个权限")
        a.setInformativeText_(
            "猫已经出来了，鼠标跟随也能用，但要「跟着你敲键盘」需要辅助功能权限。\n\n"
            "系统设置 → 隐私与安全性 → 辅助功能，把「桌面小猫」那一项打开勾。\n"
            "点下面按钮可以直接跳过去。\n\n"
            "打开之后不用重启小猫，最多等 3 秒它会自己接上。"
        )
        a.addButtonWithTitle_("打开系统设置")
        a.addButtonWithTitle_("以后再说")
        try:
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        except Exception:
            pass
        if a.runModal() == 1000:
            self.open_ax_settings()

    def ensure_tap(self):
        """建（或重建）全局事件监听。

        没授权时 CGEventTapCreate 会返回空，线程直接结束。用户去系统设置
        打开权限后，我们希望猫**当场**就能跟着敲键盘，而不是必须重启，
        所以这里做成可重试的：线程死了就再拉一个。"""
        t = getattr(self, "tap", None)
        if t is not None and t.is_alive():
            return
        nt = KeyTap(self.q)
        nt.start()
        nt.ready.wait(1.5)
        self.tap = nt
        if nt.error:
            log("KeyTap:", nt.error)
            sys.stderr.write("[cat] %s\n" % nt.error)
        else:
            log("事件监听已建立")

    # ---------------- 开机自启

    def toggle_autostart(self):
        try:
            if AGENT_PATH.exists():
                subprocess.run(["launchctl", "unload", str(AGENT_PATH)],
                               capture_output=True)
                AGENT_PATH.unlink()
                log("取消开机自启")
            else:
                AGENT_PATH.parent.mkdir(parents=True, exist_ok=True)
                exe = Path(sys.executable)
                script = ROOT / "deskcat.py"
                AGENT_PATH.write_text(
                    '<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                    '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                    '<plist version="1.0">\n'
                    "<dict>\n"
                    "  <key>Label</key><string>com.deskcat.pet</string>\n"
                    "  <key>ProgramArguments</key>\n"
                    "  <array>\n"
                    "    <string>%s</string>\n"
                    "    <string>%s</string>\n"
                    "  </array>\n"
                    "  <key>RunAtLoad</key><true/>\n"
                    "  <key>KeepAlive</key><false/>\n"
                    "  <key>WorkingDirectory</key><string>%s</string>\n"
                    "</dict>\n"
                    "</plist>\n" % (exe, script, ROOT),
                    encoding="utf-8",
                )
                subprocess.run(["launchctl", "load", str(AGENT_PATH)], capture_output=True)
                log("设置开机自启")
        except Exception as exc:
            log("改开机自启失败", exc)
        self.refresh_tray()


# ---------------------------------------------------------------- 入口

def diagnostics():
    """--diag：把环境情况打出来，出问题让用户贴这个"""
    import platform

    print("=== 桌面小猫 macOS 诊断 ===")
    print("macOS:", platform.mac_ver()[0], platform.machine())
    print("Python:", sys.version.split()[0], sys.executable)

    for mod in ("objc", "AppKit", "WebKit", "Quartz", "ApplicationServices"):
        try:
            __import__(mod)
            print("  %-18s OK" % mod)
        except Exception as exc:
            print("  %-18s 缺失 (%s)" % (mod, exc))

    try:
        trusted = AXIsProcessTrusted()
        print("辅助功能权限:", "已授权" if trusted else "未授权（键盘不会跟随）")
    except Exception as exc:
        print("辅助功能权限: 查不了", exc)

    try:
        for i, s in enumerate(NSScreen.screens()):
            f = s.frame().size
            print("屏幕 %d: %.0f x %.0f  缩放 %.1f"
                  % (i, f.width, f.height, s.backingScaleFactor()))
    except Exception as exc:
        print("读屏幕失败", exc)

    print("会话类型:", os.environ.get("XDG_SESSION_TYPE") or "macOS 原生")
    print("页面:", INDEX, "存在" if INDEX.exists() else "缺失！")
    print("配置:", CFG_PATH, "存在" if CFG_PATH.exists() else "还没有")
    print("开机自启:", "已开" if AGENT_PATH.exists() else "关")
    return 0


def main():
    if "--diag" in sys.argv:
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            diagnostics()
        text = buf.getvalue()
        print(text)
        log("=== 诊断 ===\n" + text)
        return 0

    log("=== 启动 ===", "python", sys.version.split()[0])

    app = NSApplication.sharedApplication()
    # 不在 Dock 里显示图标，纯后台 + 菜单栏图标
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    cfg = load_cfg()
    pet = Pet(cfg)

    # 菜单栏图标
    try:
        bar = NSStatusBar.systemStatusBar()
        item = bar.statusItemWithLength_(NSVariableStatusItemLength)
        img = NSImage.alloc().initWithContentsOfFile_(str(TRAY_PNG))
        if img is not None:
            img.setSize_((18.0, 18.0))
            item.button().setImage_(img)
        item.button().setToolTip_("桌面小猫")
        item.setMenu_(pet.build_menu())
        pet.status_item = item
    except Exception as exc:
        log("菜单栏图标失败", exc)

    pet.win.orderFrontRegardless()      # 不激活 App，也就不会抢焦点

    # 全局键盘 / 鼠标按钮（没权限就先空跑，下面的重试会接上）
    pet.ensure_tap()

    def after_launch(t):
        """等 App 真正跑起来再做这些：模态框在 run() 之前弹容易出怪问题。
        先让系统弹它自己的授权框（这一步同时会把小猫登记进辅助功能列表），
        6 秒后还没拿到权限，再补我们这段说明。"""
        if not pet.check_accessibility(prompt=True):
            NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
                6.0, False, lambda t2: pet.late_ax_alert()
            )
        pet.ensure_tap()

    NSTimer.scheduledTimerWithTimeInterval_repeats_block_(1.0, False, after_launch)

    # 权限是用户随时去系统设置里打开的，所以每 3 秒兜一次，
    # 一旦监听建立成功这个回调就什么都不做了
    NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
        3.0, True, lambda t: pet.ensure_tap()
    )

    # 33ms ≈ 30Hz，和另外两版一致
    NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
        0.033, True, lambda t: pet.tick()
    )

    log("启动完成，窗口", pet.pos)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
