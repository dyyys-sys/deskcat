/* 把 Tauri 的 IPC 包装成和 Electron 版一模一样的 window.petAPI，
   这样 glue.js 一行都不用改。 */
(() => {
  const T = window.__TAURI__;
  if (!T) {
    console.error('[cat] 缺少 __TAURI__（withGlobalTauri 没开？）');
    return;
  }
  const invoke = T.core.invoke;
  const listen = T.event.listen;

  let cbPointer = null;
  let cbKeys = null;
  let cbCmd = null;
  let cbButtons = null;

  window.petAPI = {
    onPointer: (cb) => { cbPointer = cb; },
    onKeys: (cb) => { cbKeys = cb; },
    onCmd: (cb) => { cbCmd = cb; },
    onButtons: (cb) => { cbButtons = cb; },
    dragStart: () => invoke('drag_start'),
    dragEnd: () => invoke('drag_end'),
    menu: () => invoke('show_menu'),
    spin: () => invoke('spin_now'),
  };

  listen('pointer', (e) => cbPointer && cbPointer(e.payload));
  listen('keys', (e) => cbKeys && cbKeys(e.payload));
  listen('buttons', (e) => cbButtons && cbButtons(e.payload));
  listen('cmd', (e) => cbCmd && cbCmd(e.payload));

  // 等 glue.js 把监听都注册好、cat.js 也初始化完，再让外壳推配置过来
  setTimeout(() => invoke('ready'), 60);
})();
