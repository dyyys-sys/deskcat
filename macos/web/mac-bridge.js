/* macOS 宿主（PyObjC）注入的调用，包装成和 Windows 版完全一样的 window.petAPI，
   这样 glue.js / cat.js 一行都不用改。

   Mac 版和 Windows 版最大的区别和 Linux 版一样：
   窗口 setIgnoresMouseEvents:YES，DOM 永远收不到真实的 pointerdown / contextmenu；
   点击、拖拽、右键菜单全部由 Python 那边用全局事件判断后，
   再用 window.__mac.* 把事件「喂」进来。 */
(() => {
  const h = { pointer: null, keys: null, cmd: null };

  window.petAPI = {
    onPointer: (cb) => { h.pointer = cb; },
    onKeys: (cb) => { h.keys = cb; },
    onCmd: (cb) => { h.cmd = cb; },
    // 下面这些在 Mac 版里由宿主直接接管，页面这边留空
    dragStart: () => {},
    dragEnd: () => {},
    menu: () => {},
    spin: () => {},
  };

  window.__mac = {
    pointer: (x, y) => { if (h.pointer) h.pointer({ x: x, y: y }); },
    keys: (arr) => { if (h.keys) h.keys(arr); },
    cmd: (o) => { if (h.cmd) h.cmd(o); },
    // 宿主用它确认前端已经准备好了
    ping: () => 'pong',
  };
})();
