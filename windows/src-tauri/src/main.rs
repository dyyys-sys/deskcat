#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

//! 桌面小猫 —— Tauri 外壳
//! 前端（cat.js / Three.js）完全复用，这里只重写窗口、全局键鼠、托盘菜单。

use std::collections::HashMap;
use std::fs;
use std::os::windows::process::CommandExt;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Mutex, OnceLock};
use std::thread;
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use tauri::image::Image;
use tauri::menu::{CheckMenuItem, Menu, MenuBuilder, MenuItem, SubmenuBuilder};
use tauri::tray::TrayIconBuilder;
use tauri::{AppHandle, Emitter, LogicalSize, Manager, Position, Size, WebviewWindow};

use windows::Win32::Foundation::{HWND, LPARAM, LRESULT, POINT, WPARAM};
use windows::Win32::UI::Input::KeyboardAndMouse::GetAsyncKeyState;
use windows::Win32::UI::WindowsAndMessaging::{
    CallNextHookEx, GetCursorPos, GetMessageW, SetWindowLongPtrW, SetWindowsHookExW,
    KBDLLHOOKSTRUCT, MSG, WH_KEYBOARD_LL, WM_KEYDOWN, WM_SYSKEYDOWN, WM_SYSKEYUP,
};

const BASE_W: f64 = 400.0;
const BASE_H: f64 = 340.0;
const TRAY_PNG: &[u8] = include_bytes!("../icons/tray.png");

static APP: OnceLock<AppHandle> = OnceLock::new();
static CFG: OnceLock<Mutex<Cfg>> = OnceLock::new();
static HELD: OnceLock<Mutex<HashMap<String, Instant>>> = OnceLock::new();
/// 右键菜单弹出期间必须保活，否则 Menu 被 drop 后原生菜单会失效
static LAST_MENU: OnceLock<Mutex<Option<Menu<tauri::Wry>>>> = OnceLock::new();
/// 正在拖动窗口。用来兜底：万一收不到 pointerup，也不会一直黏着鼠标
static DRAGGING: AtomicBool = AtomicBool::new(false);
/// 拖拽时「光标 - 窗口左上角」的偏移，保证窗口跟着手走而不是跳到光标下
static GRAB: OnceLock<Mutex<(i32, i32)>> = OnceLock::new();
/// 被要求睡觉后的静默期：(起始时刻, 光标 x, y, 解除半径)。
/// 期间不推送 pointer，否则 cat.js 的 wake() 会立刻清掉 sleepAt，猫永远睡不着。
static SLEEP_GUARD: OnceLock<Mutex<Option<(Instant, i32, i32, i32)>>> = OnceLock::new();

/// 让猫睡着并进入静默期；光标移动超过 200 逻辑像素才解除
fn sleep_now(app: &AppHandle) {
    let mut p = POINT::default();
    let _ = unsafe { GetCursorPos(&mut p) };
    let radius = 200;
    *SLEEP_GUARD
        .get_or_init(|| Mutex::new(None))
        .lock()
        .unwrap() = Some((Instant::now(), p.x, p.y, radius));
    emit_cmd(app, "sleepNow", serde_json::Value::Null);
}

/* ------------------------------------------------------------------ 配置 */

#[derive(Serialize, Deserialize, Clone, Debug)]
#[serde(rename_all = "camelCase", default)]
struct Cfg {
    x: Option<f64>,
    y: Option<f64>,
    scale: f64,
    coat: String,
    sleep_minutes: f64,
    left_mouse: bool,
    auto_launch: bool,
    locked: bool,
}

impl Default for Cfg {
    fn default() -> Self {
        Self {
            x: None,
            y: None,
            scale: 1.0,
            coat: "tuxedo".into(),
            sleep_minutes: 15.0,
            left_mouse: false,
            auto_launch: false,
            locked: false,
        }
    }
}

fn cfg_path(app: &AppHandle) -> PathBuf {
    let dir = app
        .path()
        .app_config_dir()
        .unwrap_or_else(|_| PathBuf::from("."));
    let _ = fs::create_dir_all(&dir);
    dir.join("config.json")
}

fn read_cfg(app: &AppHandle) -> Cfg {
    fs::read_to_string(cfg_path(app))
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or_default()
}

fn save_cfg(app: &AppHandle, cfg: &Cfg) {
    if let Ok(s) = serde_json::to_string_pretty(cfg) {
        let _ = fs::write(cfg_path(app), s);
    }
}

fn with_cfg<R>(f: impl FnOnce(&mut Cfg) -> R) -> R {
    let m = CFG.get_or_init(|| Mutex::new(Cfg::default()));
    let mut g = m.lock().unwrap();
    f(&mut g)
}

fn cfg_snapshot() -> Cfg {
    CFG.get_or_init(|| Mutex::new(Cfg::default()))
        .lock()
        .unwrap()
        .clone()
}

/* ------------------------------------------------------------------ 给前端的指令 */

#[derive(Serialize, Clone)]
struct ConfigCmd {
    #[serde(rename = "type")]
    kind: String,
    cfg: Cfg,
}

#[derive(Serialize, Clone)]
struct ValueCmd {
    #[serde(rename = "type")]
    kind: String,
    value: serde_json::Value,
}

fn emit_config(app: &AppHandle) {
    let _ = app.emit(
        "cmd",
        ConfigCmd {
            kind: "config".into(),
            cfg: cfg_snapshot(),
        },
    );
}

fn emit_cmd(app: &AppHandle, kind: &str, value: serde_json::Value) {
    let _ = app.emit(
        "cmd",
        ValueCmd {
            kind: kind.into(),
            value,
        },
    );
}

/* ------------------------------------------------------------------ 窗口 */

fn apply_window(app: &AppHandle) {
    let Some(win) = app.get_webview_window("main") else {
        return;
    };
    let (scale, sx, sy) = with_cfg(|c| (c.scale, c.x, c.y));
    let w = BASE_W * scale;
    let h = BASE_H * scale;
    let _ = win.set_size(Size::Logical(LogicalSize {
        width: w,
        height: h,
    }));
    if let (Some(x), Some(y)) = (sx, sy) {
        let sf = win.scale_factor().unwrap_or(1.0);
        let _ = win.set_position(Position::Physical(tauri::PhysicalPosition {
            x: (x * sf) as i32,
            y: (y * sf) as i32,
        }));
    } else if let Ok(Some(mon)) = win.current_monitor() {
        let sf = mon.scale_factor();
        let (mw, mh) = (mon.size().width as f64 / sf, mon.size().height as f64 / sf);
        let _ = win.set_position(Position::Physical(tauri::PhysicalPosition {
            x: ((mw - w - 48.0) * sf) as i32,
            y: ((mh - h - 24.0) * sf) as i32,
        }));
    }
    let _ = win.set_always_on_top(true);
}

/// 让窗口被点击时不抢焦点（等价 Electron 的 focusable:false）
fn make_no_activate(win: &WebviewWindow) {
    if let Ok(h) = win.hwnd() {
        let raw = h.0 as isize;
        unsafe {
            let hwnd = HWND(raw as *mut core::ffi::c_void);
            let ex = windows::Win32::UI::WindowsAndMessaging::GetWindowLongPtrW(
                hwnd,
                windows::Win32::UI::WindowsAndMessaging::GWL_EXSTYLE,
            );
            let noact = 0x0800_0000isize; // WS_EX_NOACTIVATE
            let tool = 0x0000_0080isize; // WS_EX_TOOLWINDOW
            let appwin = 0x0004_0000isize; // WS_EX_APPWINDOW（别进 Alt-Tab）
            SetWindowLongPtrW(
                hwnd,
                windows::Win32::UI::WindowsAndMessaging::GWL_EXSTYLE,
                (ex & !appwin) | noact | tool,
            );
        }
    }
}

/* ------------------------------------------------------------------ 命中测试 */

fn hit_test(lx: f64, ly: f64, w: f64, h: f64) -> bool {
    if lx < 0.0 || ly < 0.0 || lx > w || ly > h {
        return false;
    }
    let nx = lx / w;
    let ny = ly / h;
    let (cx, cy, rx, ry) = (0.5f64, 0.44f64, 0.235f64, 0.33f64);
    if ((nx - cx) / rx).powi(2) + ((ny - cy) / ry).powi(2) <= 1.0 {
        return true;
    }
    nx > 0.15 && nx < 0.85 && ny > 0.60 && ny < 0.80
}

/* ------------------------------------------------------------------ 全局键盘钩子 */

fn vk_to_code(vk: u32) -> Option<&'static str> {
    let s = match vk {
        0x41..=0x5A => return Some(["KeyA","KeyB","KeyC","KeyD","KeyE","KeyF","KeyG","KeyH","KeyI","KeyJ","KeyK","KeyL","KeyM","KeyN","KeyO","KeyP","KeyQ","KeyR","KeyS","KeyT","KeyU","KeyV","KeyW","KeyX","KeyY","KeyZ"][(vk - 0x41) as usize]),
        0x30..=0x39 => return Some(["Digit0","Digit1","Digit2","Digit3","Digit4","Digit5","Digit6","Digit7","Digit8","Digit9"][(vk - 0x30) as usize]),
        0x60..=0x69 => return Some(["Digit0","Digit1","Digit2","Digit3","Digit4","Digit5","Digit6","Digit7","Digit8","Digit9"][(vk - 0x60) as usize]),
        0x20 => "Space", 0x0D => "Enter", 0x09 => "Tab", 0x1B => "Escape",
        0x08 => "Backspace", 0x2E => "Delete", 0x2D => "Insert",
        0x24 => "Home", 0x23 => "End", 0x21 => "PageUp", 0x22 => "PageDown",
        0x25 => "ArrowLeft", 0x26 => "ArrowUp", 0x27 => "ArrowRight", 0x28 => "ArrowDown",
        0xA0 => "ShiftLeft", 0xA1 => "ShiftRight", 0xA2 => "ControlLeft", 0xA3 => "ControlRight",
        0xA4 => "AltLeft", 0xA5 => "AltRight", 0x5B => "MetaLeft", 0x5C => "MetaRight",
        0x14 => "CapsLock",
        0xBA => "Semicolon", 0xBB => "Equal", 0xBC => "Comma", 0xBD => "Minus",
        0xBE => "Period", 0xBF => "Slash", 0xC0 => "Backquote", 0xDB => "BracketLeft",
        0xDC => "Backslash", 0xDD => "BracketRight", 0xDE => "Quote",
        0x6A => "KeyX", 0x6B => "Equal", 0x6D => "Minus", 0x6E => "Period", 0x6F => "Slash",
        _ => return None,
    };
    Some(s)
}

/// 改状态和发快照必须在同一把锁里完成。
/// 否则钩子线程和看门狗线程可能交错：先插入、再被删、最后才把「按下」发出去，
/// 渲染层就会先收到「松开」后收到「按下」，多出一个永远等不到松开的爪子（气泡挂着不掉）。
fn emit_held(g: &HashMap<String, Instant>) {
    if let Some(app) = APP.get() {
        let list: Vec<String> = g.keys().cloned().collect();
        let _ = app.emit("keys", list);
    }
}

unsafe extern "system" fn kb_hook(code: i32, w: WPARAM, l: LPARAM) -> LRESULT {
    if code >= 0 {
        let info = &*(l.0 as *const KBDLLHOOKSTRUCT);
        let msg = w.0 as u32;
        let down = msg == WM_KEYDOWN || msg == WM_SYSKEYDOWN;
        let up = msg == windows::Win32::UI::WindowsAndMessaging::WM_KEYUP || msg == WM_SYSKEYUP;
        if (down || up) && vk_to_code(info.vkCode).is_some() {
            let key = vk_to_code(info.vkCode).unwrap().to_string();
            let m = HELD.get_or_init(|| Mutex::new(HashMap::new()));
            let mut g = m.lock().unwrap();
            if down {
                // 自动重复的 keydown 只是刷新时间戳，状态没变就不必再发
                if let Some(t) = g.get_mut(&key) {
                    *t = Instant::now();
                } else {
                    g.insert(key, Instant::now());
                    emit_held(&g);
                }
            } else if g.remove(&key).is_some() {
                emit_held(&g);
            }
        }
    }
    CallNextHookEx(None, code, w, l)
}

fn start_keyboard_hook() {
    thread::spawn(|| unsafe {
        let hook = SetWindowsHookExW(WH_KEYBOARD_LL, Some(kb_hook), None, 0);
        if hook.is_err() {
            eprintln!("[cat] 键盘钩子安装失败");
            return;
        }
        let mut msg = MSG::default();
        while GetMessageW(&mut msg, HWND::default(), 0, 0).as_bool() {}
    });

    // 卡键看门狗：2.2 秒没松开的键强制放掉（否则字符气泡会一直挂着）
    thread::spawn(|| loop {
        thread::sleep(Duration::from_millis(500));
        let m = HELD.get_or_init(|| Mutex::new(HashMap::new()));
        let mut g = m.lock().unwrap();
        let stale: Vec<String> = g
            .iter()
            .filter(|(_, t)| t.elapsed() > Duration::from_millis(2200))
            .map(|(k, _)| k.clone())
            .collect();
        if !stale.is_empty() {
            for k in &stale {
                g.remove(k);
            }
            emit_held(&g);
        }
    });
}

/* ------------------------------------------------------------------ 鼠标轮询 */

fn start_pointer_loop(app: AppHandle) {
    thread::spawn(move || {
        let mut last_inside: Option<bool> = None;
        let mut last_p: (i32, i32) = (i32::MIN, i32::MIN);
        let mut last_btn: u8 = 0;
        loop {
            thread::sleep(Duration::from_millis(30));
            // 全局鼠标按键：一按下就推给页面，猫爪子才会去按它那只小老鼠。
            // 光标不动时后面会 continue，所以这一步必须放在最前面。
            // （.exe 没有装鼠标钩子，只有键盘钩子；这里用轮询取按键状态就够了）
            {
                let down = |vk: i32| (unsafe { GetAsyncKeyState(vk) } as u16 & 0x8000) != 0;
                let btn = (down(0x01) as u8) | ((down(0x02) as u8) << 1) | ((down(0x04) as u8) << 2);
                if btn != last_btn {
                    last_btn = btn;
                    let _ = app.emit(
                        "buttons",
                        serde_json::json!({
                            "left": btn & 1 != 0,
                            "right": btn & 2 != 0,
                            "middle": btn & 4 != 0,
                        }),
                    );
                }
            }
            let Some(win) = app.get_webview_window("main") else {
                continue;
            };
            let mut p = POINT::default();
            if unsafe { GetCursorPos(&mut p) }.is_err() {
                continue;
            }

            // 光标没动就别推——每秒 33 次无意义事件会把猫一直“唤醒”
            if (p.x, p.y) == last_p && !DRAGGING.load(Ordering::Relaxed) {
                continue;
            }
            last_p = (p.x, p.y);

            // 睡觉静默期
            let mut guard_hit = false;
            {
                let g = SLEEP_GUARD.get_or_init(|| Mutex::new(None));
                let mut slot = g.lock().unwrap();
                if let Some((t0, gx, gy, radius)) = *slot {
                    let dx = (p.x - gx) as f64;
                    let dy = (p.y - gy) as f64;
                    let far = dx * dx + dy * dy > (radius as f64) * (radius as f64);
                    if t0.elapsed() < Duration::from_secs(30) && !far {
                        guard_hit = true;
                    } else {
                        *slot = None;
                    }
                }
            }
            let (Ok(pos), Ok(size)) = (win.outer_position(), win.outer_size()) else {
                continue;
            };
            let sf = win.scale_factor().unwrap_or(1.0);
            let lx = (p.x - pos.x) as f64 / sf;
            let ly = (p.y - pos.y) as f64 / sf;
            let w = size.width as f64 / sf;
            let h = size.height as f64 / sf;

            // 静默期只掐掉 pointer 推送（那是会唤醒猫的），
            // 穿透判定照常更新，免得这 30 秒里窗口挡住底下的点击。
            if !guard_hit {
                let _ = app.emit(
                    "pointer",
                    serde_json::json!({ "x": lx, "y": ly }),
                );
            }

            let locked = with_cfg(|c| c.locked);
            let inside = !locked && hit_test(lx, ly, w, h);

            // 拖动中：窗口跟着光标走，左键一松就收尾
            if DRAGGING.load(Ordering::Relaxed) {
                let left_down = (unsafe { GetAsyncKeyState(0x01) } as u16 & 0x8000) != 0;
                if left_down {
                    let (gx, gy) = *GRAB
                        .get_or_init(|| Mutex::new((0, 0)))
                        .lock()
                        .unwrap();
                    let _ = win.set_position(Position::Physical(tauri::PhysicalPosition {
                        x: p.x - gx,
                        y: p.y - gy,
                    }));
                    continue;
                }
                DRAGGING.store(false, Ordering::Relaxed);
                if let Ok(op) = win.outer_position() {
                    with_cfg(|c| {
                        c.x = Some(op.x as f64 / sf);
                        c.y = Some(op.y as f64 / sf);
                    });
                    let snap = cfg_snapshot();
                    save_cfg(&app, &snap);
                }
                continue;
            }

            if last_inside != Some(inside) {
                last_inside = Some(inside);
                let _ = win.set_ignore_cursor_events(!inside);
                make_no_activate(&win); // 切换穿透会重写扩展样式，补回 NOACTIVATE
            }
        }
    });
}

/* ------------------------------------------------------------------ 菜单 */

fn build_menu(app: &AppHandle) -> tauri::Result<Menu<tauri::Wry>> {
    let cfg = cfg_snapshot();
    let mut size = SubmenuBuilder::new(app, "大小");
    for (id, label, v) in [
        ("size_08", "小 (80%)", 0.8),
        ("size_10", "中 (100%)", 1.0),
        ("size_125", "大 (125%)", 1.25),
        ("size_15", "超大 (150%)", 1.5),
    ] {
        let item = CheckMenuItem::with_id(app, id, label, true, (cfg.scale - v).abs() < 0.01, None::<&str>)?;
        size = size.item(&item);
    }
    let mut coat = SubmenuBuilder::new(app, "毛色");
    for (id, label) in [
        ("coat_tuxedo", "奶牛猫"),
        ("coat_orange", "橘猫"),
        ("coat_tabby", "狸花猫"),
        ("coat_calico", "三花猫"),
        ("coat_white", "白猫"),
        ("coat_blue", "蓝灰猫"),
    ] {
        let key = id.trim_start_matches("coat_");
        let item = CheckMenuItem::with_id(app, id, label, true, cfg.coat == key, None::<&str>)?;
        coat = coat.item(&item);
    }
    let mut sleep = SubmenuBuilder::new(app, "多久睡着");
    for (id, label, m) in [
        ("sleep_1", "1 分钟", 1.0),
        ("sleep_2", "2 分钟", 2.0),
        ("sleep_5", "5 分钟", 5.0),
        ("sleep_15", "15 分钟", 15.0),
        ("sleep_120", "几乎不睡", 120.0),
    ] {
        let item = CheckMenuItem::with_id(app, id, label, true, (cfg.sleep_minutes - m).abs() < 0.01, None::<&str>)?;
        sleep = sleep.item(&item);
    }

    let spin = MenuItem::with_id(app, "spin", "转一圈", true, None::<&str>)?;
    let sleep_now = MenuItem::with_id(app, "sleep_now", "去睡觉", true, None::<&str>)?;
    // 互动：点名让它做某个动作（平时它自己也会随机做这些）
    let mut play = SubmenuBuilder::new(app, "让它表演一个");
    for (id, label) in [
        ("act_roll", "打个滚"),
        ("act_stretch", "伸懒腰"),
        ("act_groom", "洗脸洗手"),
        ("act_chase", "追自己的尾巴"),
        ("act_wave", "抬爪打招呼"),
        ("act_peek", "探头看看"),
        ("act_scratch", "挠耳朵"),
        ("act_hop", "原地蹦一下"),
        ("act_sneeze", "打喷嚏"),
        ("act_yawn", "打哈欠"),
        ("act_loaf", "趴一会儿"),
    ] {
        let item = MenuItem::with_id(app, id, label, true, None::<&str>)?;
        play = play.item(&item);
    }
    let auto = CheckMenuItem::with_id(app, "autolaunch", "开机自动启动", true, cfg.auto_launch, None::<&str>)?;
    let lock = CheckMenuItem::with_id(app, "locked", "锁定位置（鼠标穿透）", true, cfg.locked, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "退出小猫", true, None::<&str>)?;
    // 一行不可点的声明：免费开源，别拿去卖
    let notice = MenuItem::with_id(app, "notice", "软件均是免费开源，切勿商用买卖", false, None::<&str>)?;

    MenuBuilder::new(app)
        .item(&size.build()?)
        .item(&coat.build()?)
        .item(&sleep.build()?)
        .separator()
        .item(&spin)
        .item(&sleep_now)
        .item(&play.build()?)
        .separator()
        .item(&auto)
        .item(&lock)
        .separator()
        .item(&quit)
        .item(&notice)
        .build()
}

fn refresh_menus(app: &AppHandle) {
    if let Ok(menu) = build_menu(app) {
        if let Some(tray) = app.tray_by_id("main") {
            let _ = tray.set_menu(Some(menu));
        }
    }
}

fn handle_menu(app: &AppHandle, id: &str) {
    match id {
        "quit" => app.exit(0),
        "spin" => emit_cmd(app, "spin", serde_json::Value::Null),
        "sleep_now" => sleep_now(app),
        "act_roll" | "act_stretch" | "act_groom" | "act_chase" | "act_wave" | "act_peek"
        | "act_scratch" | "act_hop" | "act_sneeze" | "act_yawn" | "act_loaf" => {
            emit_cmd(app, "act", serde_json::json!(id.trim_start_matches("act_")))
        }
        "locked" => {
            let v = with_cfg(|c| {
                c.locked = !c.locked;
                c.locked
            });
            save_cfg(app, &cfg_snapshot());
            refresh_menus(app);
            let _ = v;
        }
        "autolaunch" => {
            let v = with_cfg(|c| {
                c.auto_launch = !c.auto_launch;
                c.auto_launch
            });
            save_cfg(app, &cfg_snapshot());
            set_autolaunch(v);
            refresh_menus(app);
        }
        other => {
            if let Some(v) = other.strip_prefix("size_") {
                let scale = match v {
                    "08" => 0.8,
                    "125" => 1.25,
                    "15" => 1.5,
                    _ => 1.0,
                };
                with_cfg(|c| c.scale = scale);
                save_cfg(app, &cfg_snapshot());
                apply_window(app);
                emit_config(app);
                refresh_menus(app);
            } else if let Some(key) = other.strip_prefix("coat_") {
                with_cfg(|c| c.coat = key.to_string());
                save_cfg(app, &cfg_snapshot());
                emit_cmd(app, "coat", serde_json::json!(key));
                refresh_menus(app);
            } else if let Some(v) = other.strip_prefix("sleep_") {
                let m: f64 = v.parse().unwrap_or(2.0);
                with_cfg(|c| c.sleep_minutes = m);
                save_cfg(app, &cfg_snapshot());
                emit_cmd(app, "sleepMinutes", serde_json::json!(m));
                refresh_menus(app);
            }
        }
    }
}

/* ------------------------------------------------------------------ 开机自启 */

fn set_autolaunch(on: bool) {
    let Ok(exe) = std::env::current_exe() else {
        return;
    };
    let key = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run";
    if on {
        let _ = std::process::Command::new("reg")
            .args(["add", key, "/v", "桌面小猫", "/t", "REG_SZ", "/d", &format!("\"{}\"", exe.display()), "/f"])
            .creation_flags(0x0800_0000)
            .output();
    } else {
        let _ = std::process::Command::new("reg")
            .args(["delete", key, "/v", "桌面小猫", "/f"])
            .creation_flags(0x0800_0000)
            .output();
    }
}

/* ------------------------------------------------------------------ 命令 */

#[tauri::command]
fn ready(win: WebviewWindow) {
    let Some(app) = APP.get().cloned() else {
        return;
    };
    apply_window(&app);
    let cfg = cfg_snapshot();
    let _ = win.set_size(Size::Logical(LogicalSize {
        width: BASE_W * cfg.scale,
        height: BASE_H * cfg.scale,
    }));
    let _ = win.show();
    // 必须在 show() 之后：show 会把窗口样式按 wry 的记录重写一遍，
    // 之前设置的 NOACTIVATE / TOOLWINDOW 会被抹掉。
    make_no_activate(&win);
    emit_config(&app);
    emit_cmd(&app, "desk", serde_json::json!(true));
}

#[tauri::command]
fn show_menu(win: WebviewWindow) -> Result<(), String> {
    let app = win.app_handle();
    let menu = build_menu(app).map_err(|e| e.to_string())?;
    let rc = win.popup_menu(&menu).map_err(|e| e.to_string());
    *LAST_MENU
        .get_or_init(|| Mutex::new(None))
        .lock()
        .unwrap() = Some(menu);
    rc
}

#[tauri::command]
fn drag_start(win: WebviewWindow) {
    let mut p = POINT::default();
    let _ = unsafe { GetCursorPos(&mut p) };
    if let Ok(op) = win.outer_position() {
        *GRAB.get_or_init(|| Mutex::new((0, 0))).lock().unwrap() = (p.x - op.x, p.y - op.y);
        DRAGGING.store(true, Ordering::Relaxed);
    }
}

#[tauri::command]
fn drag_end(win: WebviewWindow) {
    DRAGGING.store(false, Ordering::Relaxed);
    let app = win.app_handle();
    if let (Ok(pos), Ok(sf)) = (win.outer_position(), win.scale_factor()) {
        with_cfg(|c| {
            c.x = Some(pos.x as f64 / sf);
            c.y = Some(pos.y as f64 / sf);
        });
        save_cfg(app, &cfg_snapshot());
    }
}

#[tauri::command]
fn spin_now(app: AppHandle) {
    emit_cmd(&app, "spin", serde_json::Value::Null);
}

/* ------------------------------------------------------------------ main */

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.show();
                let _ = w.set_always_on_top(true);
            }
        }))
        .setup(|app| {
            let handle = app.handle().clone();
            let _ = APP.set(handle.clone());
            let _ = CFG.set(Mutex::new(read_cfg(&handle)));

            // 托盘
            if let Ok(menu) = build_menu(&handle) {
                let tray = TrayIconBuilder::with_id("main")
                    .icon(Image::from_bytes(TRAY_PNG)?)
                    .tooltip("桌面小猫")
                    .menu(&menu)
                    .show_menu_on_left_click(true)
                    .build(app)?;
                let _ = tray.set_icon(Some(Image::from_bytes(TRAY_PNG)?));
            }

            app.on_menu_event(|app, event| {
                handle_menu(app, event.id().as_ref());
            });

            start_keyboard_hook();
            start_pointer_loop(handle.clone());


            // 开机自启状态以注册表为准，避免配置和系统不一致
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.set_ignore_cursor_events(true);
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            ready,
            show_menu,
            drag_start,
            drag_end,
            spin_now
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
