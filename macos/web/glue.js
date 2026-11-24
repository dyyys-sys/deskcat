'use strict';
/**
 * 渲染进程桥接：把主进程采集到的全局键鼠喂给 cat.js，
 * 并把桌面上的点击 / 拖拽 / 右键菜单接起来。
 */
(() => {
  const stage = document.getElementById('stage');
  let cat = null;
  let cfg = { coat: 'tuxedo', sleepMinutes: 15, leftMouse: false };
  let spinBtn = null;
  let sleepBtn = null;
  let spinCount = 0;
  let deskCmd = true;
  let held = new Set();
  let buttons = new Set();      // 页面自己按下的（用于拖动判定）
  let gButtons = new Set();     // 系统级真实按键状态（全局轮询来的）
  let dragArmed = false;
  let downX = 0, downY = 0, dragging = false, down = false;

  /* cat.js 把「转一圈 / 去睡觉」做成了不挂到页面上的隐藏按钮（stub）。
     注意：stub 是「懒创建 + 永久缓存」的，重建 cat 时复用旧元素，
     所以收集必须是常驻的，否则换毛色/改设置后就再也抓不到它们。 */
  const buttonPool = [];
  const origCreateElement = document.createElement.bind(document);
  document.createElement = function (tag, ...rest) {
    const el = origCreateElement(tag, ...rest);
    if (String(tag).toLowerCase() === 'button') buttonPool.push(el);
    return el;
  };

  function findButton(needle) {
    for (let i = buttonPool.length - 1; i >= 0; i--) {
      const el = buttonPool[i];
      if (typeof el.onclick === 'function' && el.onclick.toString().includes(needle)) return el;
    }
    return null;
  }

  // 页面内的按键 + 系统级按键，合成一份给 cat.js：猫爪子按小老鼠靠这个
  function pushInput() {
    if (!cat) return;
    cat.setInput(held, new Set([...buttons, ...gButtons]));
  }

  function boot() {
    if (cat) {
      try { cat.destroy(); } catch (e) { /* 忽略 */ }
      cat = null;
    }
    stage.innerHTML = '';
    const result = window.createCat(stage, {
      coat: cfg.coat,
      sleepMinutes: cfg.sleepMinutes,
    });
    cat = result;
    spinBtn = findButton('spinning');
    sleepBtn = findButton('sleepAt');
    if (!cat) {
      console.error('[catpet] WebGL 初始化失败');
      return;
    }
    cat.setOptions({
      showKeyboard: true,
      showMouse: true,
      followKeys: true,
      leftMouse: !!cfg.leftMouse,
    });
    held = new Set();
    buttons = new Set();
    pushInput();
  }

  /* ---------------- 全局鼠标位置：合成 pointermove 给 cat.js ---------------- */
  let lastP = null;
  window.petAPI.onPointer((p) => {
    if (!cat) return;
    lastP = p;
    window.dispatchEvent(new PointerEvent('pointermove', {
      clientX: p.x, clientY: p.y, pointerType: 'mouse', bubbles: true,
    }));
  });

  /* cat.js 空闲超过 2.5s 会隔帧渲染省电，此时做动作会变成半速+卡顿。
     轻轻抖一下光标位置，既把它唤醒也让它回到满帧。 */
  function wakeFullRate() {
    if (!lastP) return;
    const ev = (dx) => window.dispatchEvent(new PointerEvent('pointermove', {
      clientX: lastP.x + dx, clientY: lastP.y, pointerType: 'mouse', bubbles: true,
    }));
    ev(0); ev(4); ev(0);
  }

  /* ---------------- 全局鼠标按键（左/右/中） ---------------- */
  // 只认「光标在猫身上按下去」的话，桌面别处点鼠标它是没反应的，所以走系统级按键。
  if (window.petAPI.onButtons) {
    window.petAPI.onButtons((b) => {
      b = b || {};
      gButtons = new Set();
      if (b.left) gButtons.add('left');
      if (b.right) gButtons.add('right');
      if (b.middle) gButtons.add('middle');
      pushInput();
    });
  }

  /* ---------------- 全局键盘 ---------------- */
  window.petAPI.onKeys((list) => {
    held = new Set(list);
    pushInput();
  });

  /* ---------------- 主进程指令 ---------------- */
  window.petAPI.onCmd((c) => {
    if (!c) return;
    switch (c.type) {
      case 'config':
        cfg = Object.assign(cfg, c.cfg || {});
        boot();
        break;
      case 'coat':
        cfg.coat = c.value;
        if (cat) cat.setOptions({ coat: c.value });
        break;
      case 'sleepMinutes':
        cfg.sleepMinutes = c.value;
        if (cat) cat.setOptions({ sleepMinutes: c.value });
        break;
      case 'spin':
        spinCount += 1;
        wakeFullRate();
        if (spinBtn && spinBtn.onclick) spinBtn.onclick();
        break;
      case 'act':
        // 注意：不要在这里 wakeFullRate()。它靠伪造 pointermove 来顶帧率，
        // 会顺手把「鼠标刚动过」也置上，猫会伸一只爪子去按小老鼠——
        // 伸懒腰就变成单手了。play() 里已经用 fullUntil 顶满帧率。
        if (cat) cat.play(c.value);
        break;
      case 'sleepNow':
        wakeFullRate();
        if (sleepBtn && sleepBtn.onclick) sleepBtn.onclick();
        else if (cat) cat.fastForwardToSleep();
        break;
      case 'desk':
        deskCmd = !!c.value;
        if (cat) cat.setOptions({ showKeyboard: deskCmd, showMouse: deskCmd });
        break;
      case 'leftMouse':
        cfg.leftMouse = c.value;
        if (cat) cat.setOptions({ leftMouse: c.value });
        break;
      default:
        break;
    }
  });

  /* ---------------- 点击 / 拖拽 / 菜单 ---------------- */
  let pressTimer = null;
  let lastPressAt = 0;

  stage.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    down = true;
    buttons.add('left');
    pushInput();
    // 必须用 clientX/clientY：合成出来的 pointermove 只有这两个字段，
    // 用 screenX 会比到一个恒为 0 的值，一点就误判成拖动。
    downX = e.clientX; downY = e.clientY;
    dragging = false;
    dragArmed = false;

    // 双击 = 转一圈
    const now = performance.now();
    if (now - lastPressAt < 340) {
      lastPressAt = 0;
      clearTimeout(pressTimer);
      return window.petAPI.spin();
    }
    lastPressAt = now;

    // 按在猫头上是摸猫（cat.js 自己会处理），按在别处才能拖动
    clearTimeout(pressTimer);
    pressTimer = setTimeout(() => {
      if (!down) return;                       // 已经松手了就别再武装拖动
      if (!cat || cat.state() !== 'petting') dragArmed = true;
    }, 70);
  });

  window.addEventListener('pointermove', (e) => {
    if (!down || !dragArmed || dragging) return;
    if (Math.abs(e.clientX - downX) + Math.abs(e.clientY - downY) > 6) {
      dragging = true;
      window.petAPI.dragStart();
    }
  });

  window.addEventListener('pointerup', () => {
    down = false;
    clearTimeout(pressTimer);
    buttons.clear();
    pushInput();
    dragArmed = false;
    if (dragging) { dragging = false; window.petAPI.dragEnd(); }
  });

  window.addEventListener('blur', () => {
    buttons.clear();
    pushInput();
  });

  window.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    window.petAPI.menu();
  });

  // 供外壳查询当前状态：睡着 / 摸头 / 打字 / 鼠标 / 空闲
  window.__catState = () => (cat ? cat.state() : 'none');
  window.__catDiag = () => {
    if (!cat) return 'none';
    return `state=${cat.state()} chips=${document.querySelectorAll('.chip').length}`
      + ` held=${held.size} spin=${!!spinBtn} spinN=${spinCount} sleep=${!!sleepBtn} deskCmd=${deskCmd ? 1 : 0}`;
  };
  window.__cat = () => cat;

  /* ---- 气泡兜底 ----
     cat.js 的气泡不是按下就建，而是等爪子落地那一刻才建；而它的 keyUp 在
     「自己那边没有这个键按下」时会直接 return，连气泡都不清。
     宿主与渲染层只要有一次事件错位，就会留下一个永远不淡出的气泡。
     正常气泡最长约 1.6 秒（cat.js 自己 1.4 秒强制松键 + 落地延迟），
     所以这里 2.2 秒还没走的一律移走，不会误伤。 */
  const chipBorn = new WeakMap();
  setInterval(() => {
    const now = performance.now();
    document.querySelectorAll('.chip').forEach((el) => {
      const born = chipBorn.get(el);
      if (born === undefined) { chipBorn.set(el, now); return; }
      if (now - born > 2200) { chipBorn.delete(el); el.remove(); }
    });
  }, 400);
})();
