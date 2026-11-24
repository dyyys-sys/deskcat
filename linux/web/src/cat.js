/**
 * 桌面小猫 —— 猫本体（three.js）
 *
 * 几何、材质、动作、表情全在这一个文件里，没有贴图也没有模型文件。
 * 它不依赖任何外壳，Windows / macOS / Linux 三个版本共用同一份；
 * 改的时候三处 web/src/cat.js 要一起改。
 */
window.createCat = function (host, options = {}) {
const stageEl = host, hintEl = document.createElement('div');
// 页面控件由外壳提供；这里用占位元素顶上，绘制代码不去依赖具体 DOM。
const stubs = {}, $ = id => stubs[id] || (stubs[id] = document.createElement(id.startsWith('btn') ? 'button' : 'div'));
const offs = [], on = (type, fn, opt) => { window.addEventListener(type, fn, opt); offs.push(() => window.removeEventListener(type, fn, opt)); };
let dead = false, raf = 0, followKeys = false, lastStrikeAt = -1e9, halfRate = false;
const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
const clamp = (v, a, b) => Math.max(a, Math.min(b, v)), mix = (a, b, t) => a + (b - a) * t, rnd = (a, b) => a + Math.random() * (b - a);
const V = (x, y, z) => new THREE.Vector3(x, y, z);

let renderer;
try { renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true }); }
catch (e) { return null; }
renderer.setPixelRatio(Math.min(2, devicePixelRatio || 1));
stageEl.appendChild(renderer.domElement);
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(29, 1, 0.1, 100);
const CAM = V(0, 5.0, 10.2), LOOK = V(0, 1.35, 0.45);
const VIEW = new URLSearchParams(location.search);
const flat = color => new THREE.MeshBasicMaterial({ color });
const back = color => new THREE.MeshBasicMaterial({ color, side: THREE.BackSide });

/* ---------- materials that a coat preset recolours ---------- */
const onFace = (color, k) => new THREE.MeshBasicMaterial({ color, polygonOffset: true, polygonOffsetFactor: -4 * k, polygonOffsetUnits: -4 * k });
const M = { lid: onFace('#101010', 3), blush: flat('#f08f9c'), shut: onFace('#8b8f86', 1), fur: flat('#101010'), patch: flat('#101010'), line: back('#8b8f86'), eye: onFace('#b9d36b', 1), pupil: onFace('#0b0b0b', 2), whisker: flat('#f4f4ee'), whiskerOut: flat('#101010'), stripe: onFace('#101010', 1), inner: flat('#101010') };

/* ---------- desk, keyboard, mouse ---------- */
const deskMat = flat('#e9ebb6'), deskEdge = flat('#1c1d1a');
const desk = new THREE.Mesh(new THREE.BoxGeometry(40, 0.4, 7), deskMat); desk.position.set(0, -0.2, 1.2); scene.add(desk); desk.visible = false;
const horizon = new THREE.Mesh(new THREE.BoxGeometry(40, 0.05, 0.05), deskEdge); horizon.position.set(0, 0.0, -2.3); scene.add(horizon); horizon.visible = false;

const ROWS = [
  [['Backquote',1,'`'],['Digit1',1,'1'],['Digit2',1,'2'],['Digit3',1,'3'],['Digit4',1,'4'],['Digit5',1,'5'],['Digit6',1,'6'],['Digit7',1,'7'],['Digit8',1,'8'],['Digit9',1,'9'],['Digit0',1,'0'],['Minus',1,'-'],['Equal',1,'='],['Backspace',2,'⌫']],
  [['Tab',1.5,'⇥'],['KeyQ',1,'Q'],['KeyW',1,'W'],['KeyE',1,'E'],['KeyR',1,'R'],['KeyT',1,'T'],['KeyY',1,'Y'],['KeyU',1,'U'],['KeyI',1,'I'],['KeyO',1,'O'],['KeyP',1,'P'],['BracketLeft',1,'['],['BracketRight',1,']'],['Backslash',1.5,'\\']],
  [['CapsLock',1.75,'⇪'],['KeyA',1,'A'],['KeyS',1,'S'],['KeyD',1,'D'],['KeyF',1,'F'],['KeyG',1,'G'],['KeyH',1,'H'],['KeyJ',1,'J'],['KeyK',1,'K'],['KeyL',1,'L'],['Semicolon',1,';'],['Quote',1,"'"],['Enter',2.25,'⏎']],
  [['ShiftLeft',2.25,'⇧'],['KeyZ',1,'Z'],['KeyX',1,'X'],['KeyC',1,'C'],['KeyV',1,'V'],['KeyB',1,'B'],['KeyN',1,'N'],['KeyM',1,'M'],['Comma',1,','],['Period',1,'.'],['Slash',1,'/'],['ShiftRight',2.75,'⇧']],
  [['ControlLeft',1.25,'⌃'],['AltLeft',1.25,'⌥'],['MetaLeft',1.25,'⌘'],['Space',7.5,'space'],['MetaRight',1.25,'⌘'],['AltRight',1.25,'⌥'],['ControlRight',1.25,'⌃']]
];
const KB = { unit: 0.18, z0: 0.92, x0: 0 }, KEY_TOP = 0.2;
const DESK_DX = 0.2825;                                  // keyboard + mouse together are centred on the cat
const board = new THREE.Group(); scene.add(board);
const roundedSlab = (w, d, r, hgt) => { const sh = new THREE.Shape(), x = w / 2, y = d / 2; sh.moveTo(-x + r, -y); sh.lineTo(x - r, -y); sh.quadraticCurveTo(x, -y, x, -y + r); sh.lineTo(x, y - r); sh.quadraticCurveTo(x, y, x - r, y); sh.lineTo(-x + r, y); sh.quadraticCurveTo(-x, y, -x, y - r); sh.lineTo(-x, -y + r); sh.quadraticCurveTo(-x, -y, -x + r, -y);
  const g = new THREE.ExtrudeGeometry(sh, { depth: hgt, bevelEnabled: false, curveSegments: 6 }); g.rotateX(-Math.PI / 2); return g; };
const boardBase = new THREE.Mesh(roundedSlab(15 * KB.unit + 0.2, 5 * KB.unit + 0.2, 0.11, 0.1), flat('#22231f')); boardBase.position.set(DESK_DX, 0, KB.z0 + 2.5 * KB.unit); board.add(boardBase);
const KEYCAP = { plain: new THREE.Color('#fbfbf3'), mod: new THREE.Color('#e3dfce'), accent: new THREE.Color('#f2b25c') };
const keys = new Map(), capColor = new THREE.Color('#fbfbf3'), hitColor = new THREE.Color('#b9d36b');
ROWS.forEach((row, r) => { let x = 0; row.forEach(([code, w, label]) => {
  // The keyboard faces the cat: the cat's left hand is on screen right, the number row is nearest the viewer.
  const wx = DESK_DX + (7.5 - (x + w / 2)) * KB.unit, wz = KB.z0 + (4 - r + 0.5) * KB.unit;
  const base = code === 'Enter' || code === 'Backquote' ? KEYCAP.accent : (w > 1 && code !== 'Space') || /^(Alt|Meta|Control)/.test(code) ? KEYCAP.mod : KEYCAP.plain;
  const mesh = new THREE.Mesh(roundedSlab(w * KB.unit - 0.03, KB.unit - 0.03, 0.035, 0.09), flat('#fbfbf3')); mesh.geometry.translate(0, -0.045, 0);
  mesh.position.set(wx, 0.145, wz); board.add(mesh);
  keys.set(code, { code, label, mesh, base, ox: wx - DESK_DX, x: wx, z: wz, down: false, glow: 0 }); x += w;
}); });
const MOUSE_AT = V(-1.795 + DESK_DX, 0, 1.08);
const mouseGroup = new THREE.Group(); mouseGroup.position.copy(MOUSE_AT); scene.add(mouseGroup);
// Which paw works the mouse, and which way the desk set is laid out. The picture mirrors its owner: a mouse in the owner's right
// hand sits on the left of the picture. For a left-handed mouse the keyboard and mouse swap sides, still centred on the cat together.
let MOUSE_PAW = 'L', DESK_DIR = 1;
function setHanded(leftMouse) {
  DESK_DIR = leftMouse ? -1 : 1; MOUSE_PAW = leftMouse ? 'R' : 'L';
  boardBase.position.x = DESK_DX * DESK_DIR; keys.forEach(k => { k.x = DESK_DX * DESK_DIR + k.ox; k.mesh.position.x = k.x; });
  MOUSE_AT.x = (-1.795 + DESK_DX) * DESK_DIR;
}
// Touch-typing hands: these keys belong to the left hand, everything else to the right. The keyboard faces the cat, so the
// owner's left hand is the paw on the right of the picture.
const LEFT_HAND = new Set(['Escape', 'F1', 'F2', 'F3', 'F4', 'F5', 'Backquote', 'Digit1', 'Digit2', 'Digit3', 'Digit4', 'Digit5', 'Tab', 'KeyQ', 'KeyW', 'KeyE', 'KeyR', 'KeyT', 'CapsLock', 'KeyA', 'KeyS', 'KeyD', 'KeyF', 'KeyG', 'ShiftLeft', 'KeyZ', 'KeyX', 'KeyC', 'KeyV', 'KeyB', 'ControlLeft', 'AltLeft', 'MetaLeft']);
const pawFor = code => LEFT_HAND.has(code) ? 'R' : 'L';
const mouseBody = new THREE.Mesh(new THREE.SphereGeometry(0.3, 24, 16), flat('#fbfbf3')); mouseBody.scale.set(0.7, 0.42, 1.2); mouseBody.position.y = 0.1; mouseGroup.add(mouseBody);
const mouseRim = new THREE.Mesh(mouseBody.geometry, back('#1c1d1a')); mouseRim.scale.set(0.77, 0.47, 1.27); mouseRim.position.y = 0.1; mouseGroup.add(mouseRim);
const mouseBtn = new THREE.Mesh(new THREE.BoxGeometry(0.018, 0.02, 0.16), flat('#1c1d1a')); mouseBtn.position.set(0, 0.215, 0.24); mouseGroup.add(mouseBtn);
const mouseWheel = new THREE.Mesh(new THREE.BoxGeometry(0.04, 0.03, 0.09), flat('#f2b25c')); mouseWheel.position.set(0, 0.222, 0.16); mouseGroup.add(mouseWheel);

/* ---------- the cat: one flowing body, an oval head, oval-ended legs, and a tail that grows out of the hip ---------- */
const cat = new THREE.Group(); cat.position.set(0, 0, 0.08); scene.add(cat);
const ball = (r, mat, sx = 1, sy = 1, sz = 1) => { const m = new THREE.Mesh(new THREE.SphereGeometry(r, 40, 28), mat); m.scale.set(sx, sy, sz); return m; };
const add = (parent, mesh, x, y, z) => { mesh.position.set(x, y, z); parent.add(mesh); return mesh; };
const spline = pts => { const c = new THREE.SplineCurve(pts.map(([a, b]) => new THREE.Vector2(a, b))); const table = c.getPoints(120); return y => { let k = 0; while (k < table.length - 2 && table[k + 1].x < y) k++; const a = table[k], b = table[k + 1], f = clamp((y - a.x) / Math.max(1e-6, b.x - a.x), 0, 1); return a.y + (b.y - a.y) * f; }; };
// The body is a single lofted surface: at each height an ellipse with its own width, depth and forward offset.
const BODY_H = 2.5;                                   // the neck continues up inside the head, so no gap can open behind it
const halfW = spline([[0, 0.86], [0.07, 0.9], [0.3, 1.0], [0.62, 1.03], [0.95, 0.93], [1.3, 0.75], [1.6, 0.58], [1.85, 0.47], [2.02, 0.41], [BODY_H, 0.37]]);
// Front and back outlines seen from the side: an upright chest and a full, rounded back down to the rump.
const frontZ = spline([[0, 0.4], [0.07, 0.43], [0.3, 0.5], [0.6, 0.54], [0.95, 0.52], [1.3, 0.48], [1.6, 0.46], [1.9, 0.42], [2.02, 0.4], [BODY_H, 0.36]]);
const backZ = spline([[0, -1.14], [0.07, -1.19], [0.3, -1.32], [0.6, -1.38], [0.95, -1.24], [1.3, -1.0], [1.6, -0.76], [1.9, -0.56], [2.02, -0.5], [BODY_H, -0.44]]);
const halfD = y => (frontZ(y) - backZ(y)) / 2, midZ = y => (frontZ(y) + backZ(y)) / 2;
const upper = new THREE.Group(); cat.add(upper);            // chest and head lean; the feet and tail stay put
const torso = new THREE.Group(); upper.add(torso);
let NECK_W = 1, SHOULDER_W = 1, builtNeck = -1;
const bodyMesh = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial({ color: 0x101010, side: THREE.DoubleSide })); torso.add(bodyMesh); M.body = bodyMesh.material;
function buildBody() {
  if (builtNeck === NECK_W + SHOULDER_W * 100) return; builtNeck = NECK_W + SHOULDER_W * 100; bodyMesh.geometry.dispose();
  bodyMesh.geometry = new THREE.ParametricGeometry((u, v, out) => { const y = v * BODY_H, a = u * Math.PI * 2, close = Math.sqrt(1 - (1 - Math.min(1, y / 0.12)) ** 2), f = (1 + (NECK_W - 1) * smooth(1.15, 1.95, y)) * (1 + (SHOULDER_W - 1) * smooth(0.55, 1.4, y) * (1 - smooth(1.6, 2.25, y))) * (1 + 0.34 * smooth(1.72, 2.2, y)), g = 1 + (f / (1 + 0.34 * smooth(1.72, 2.2, y)) - 1) * 0.3; const top = 1 - 0.8 * smooth(2.17, 2.46, y);   /* the hidden top of the neck narrows to a point so it can never poke out of the head */ out.set(Math.cos(a) * halfW(y) * f * close * top, y, midZ(y) + 0.1 * (1 - top) + Math.sin(a) * halfD(y) * g * close * top); }, 56, 44);
}
const chest = add(torso, ball(1, M.patch, 0.3, 0.5, 0.16), 0, 1.22, 0.4);
const hindFeet = [-1, 1].map(s => { const g = new THREE.Group(); g.position.set(s * 0.6, 0.1, 0.25); cat.add(g); const rim = add(g, ball(1, M.line, 0.216, 0.118, 0.325), 0, -0.012, 0.022); const foot = add(g, ball(1, M.patch, 0.2, 0.11, 0.31), 0, 0, 0); foot.renderOrder = 1; rim.renderOrder = 0; return g; });

const HEAD_R = [0.86, 0.66, 0.7];
upper.matrixAutoUpdate = false;                              // the chest leans by shearing, so its base never leaves the desk
const headFix = new THREE.Group(); headFix.matrixAutoUpdate = false; upper.add(headFix);   // undoes the shear so the head keeps its shape
const head = new THREE.Group(); head.position.set(0, 2.3, 0.1); headFix.add(head);
const TEX = 256, mkTex = () => { const c = document.createElement('canvas'); c.width = c.height = TEX; return { g: c.getContext('2d'), t: new THREE.CanvasTexture(c) }; };
const bodyTex = mkTex(), headTex = mkTex(); M.body.map = bodyTex.t; M.head = new THREE.MeshBasicMaterial({ map: headTex.t }); M.tail = flat('#101010');
// u runs round the cat (0.25 = facing the viewer, 0.75 = the back), v runs bottom to top
const blob = (g, u, v, ru, rv, color, rot = 0) => { g.fillStyle = color; for (const du of [-1, 0, 1]) { g.beginPath(); g.ellipse((u + du) * TEX, (1 - v) * TEX, ru * TEX, rv * TEX, rot, 0, 7); g.fill(); } };
function paintCoat(c) {
  const b = bodyTex.g, h = headTex.g, pat = c.pattern || '';
  for (const g of [b, h]) { g.fillStyle = c.fur; g.fillRect(0, 0, TEX, TEX); }
  if (pat.includes('tabby')) {
    // a leaf-shaped mark from (u0,v0) to (u1,v1): fat in the middle, pointed at both ends
    const leaf = (g, u0, v0, u1, v1, th) => { g.fillStyle = c.stripe; for (const du of [-1, 0, 1]) { const x0 = (u0 + du) * TEX, y0 = (1 - v0) * TEX, x1 = (u1 + du) * TEX, y1 = (1 - v1) * TEX, mx = (x0 + x1) / 2, my = (y0 + y1) / 2, len = Math.hypot(x1 - x0, y1 - y0), nx = -(y1 - y0) / len * th * TEX, ny = (x1 - x0) / len * th * TEX;
      g.beginPath(); g.moveTo(x0, y0); g.quadraticCurveTo(mx + nx, my + ny, x1, y1); g.quadraticCurveTo(mx - nx * 0.9, my - ny * 0.9, x0, y0); g.fill(); } };
    const marks = [[0.2, 0.17, 0.05], [0.285, 0.1, 0.03], [0.37, 0.19, 0.06], [0.455, 0.12, 0.035], [0.54, 0.16, 0.05], [0.62, 0.09, 0.03]];   // height, length, how far it droops
    for (const [v, len, droop] of marks) { leaf(b, 0.86, v + 0.02, 0.86 + len + 0.12, v - droop, 0.02); leaf(b, 0.64, v + 0.02, 0.64 - len - 0.12, v - droop, 0.02); }
    leaf(b, 0.75, 0.12, 0.75, 0.7, 0.02);                             // spine
    leaf(h, 0.75, 0.35, 0.75, 0.85, 0.022); leaf(h, 0.68, 0.45, 0.62, 0.72, 0.016); leaf(h, 0.82, 0.45, 0.88, 0.72, 0.016);   // back of the head
  }
  if (pat.includes('calico')) {
    blob(b, 0.04, 0.42, 0.15, 0.2, c.patchA); blob(b, 0.56, 0.22, 0.13, 0.13, c.patchB); blob(b, 0.78, 0.5, 0.16, 0.22, c.patchB); blob(b, 0.5, 0.56, 0.1, 0.12, c.patchA);
    blob(h, 0.11, 0.7, 0.13, 0.24, c.patchA, 0.3); blob(h, 0.42, 0.72, 0.11, 0.22, c.patchB, -0.3); blob(h, 0.75, 0.5, 0.2, 0.3, c.patchB);
  }
    bodyTex.t.needsUpdate = headTex.t.needsUpdate = true; M.tail.color.set(c.tail || c.fur);
}
add(head, ball(1, M.head, HEAD_R[0], HEAD_R[1], HEAD_R[2]), 0, 0, 0);
const tongue = add(head, ball(1, new THREE.MeshBasicMaterial({ color: '#f08a98' }), 0.06, 0.085, 0.04), 0.02, -0.36, 0.6); tongue.visible = false;
const muzzle = add(head, ball(1, M.patch, 0.13, 0.08, 0.1), 0, -0.4, 0.5);
for (const k of ['eye', 'pupil', 'stripe', 'inner']) M[k].side = THREE.DoubleSide;

// Ears: a solid rounded form whose base sits inside the head, so the outline runs from head to ear without a step.
const earR = spline([[0, 0.3], [0.12, 0.285], [0.32, 0.22], [0.48, 0.13], [0.56, 0.062], [0.588, 0]]), EAR_H = 0.588, EAR_T = 0.5;
const earGeo = new THREE.LatheGeometry(Array.from({ length: 29 }, (_, i) => new THREE.Vector2(Math.max(0, earR(i / 28 * EAR_H)), i / 28 * EAR_H)), 32);
// The inner marking is a strip of the ear's own front surface, lifted a hair so it never floats.
const earInnerGeo = new THREE.ParametricGeometry((u, v, out) => { const y = mix(0.1, 0.47, v), r = earR(y), a = (u - 0.5) * 2 * 0.72 * Math.sqrt(Math.max(0, 1 - v ** 5)) * (0.72 + 0.28 * Math.min(1, v * 6)); out.set(r * Math.sin(a), y, r * Math.cos(a) * EAR_T + 0.007); }, 20, 28);
const ears = [-1, 1].map(s => { const g = new THREE.Group(); g.position.set(s * 0.46, 0.3, -0.04); g.rotation.z = -s * 0.24; head.add(g);
  M.ear = M.ear || new THREE.MeshBasicMaterial({ color: 0x101010, side: THREE.DoubleSide }); const ear = new THREE.Mesh(earGeo, M.ear); ear.scale.z = EAR_T; g.add(ear);
  const inner = new THREE.Mesh(earInnerGeo, M.inner); inner.renderOrder = 3; g.add(inner); return g; });

// A patch is a small ellipse wrapped onto the head's surface, so eyes and markings sit on the face from every angle.
const PR = 6, PS = 32;
function makePatch(mat, order) {
  const geo = new THREE.BufferGeometry(), index = [];
  geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array((1 + PR * PS) * 3), 3));
  for (let k = 0; k < PS; k++) index.push(0, 1 + k, 1 + (k + 1) % PS);
  for (let r = 0; r < PR - 1; r++) for (let k = 0; k < PS; k++) { const a = 1 + r * PS + k, b = 1 + r * PS + (k + 1) % PS, c = a + PS, d = b + PS; index.push(a, c, b, b, c, d); }
  geo.setIndex(index); const mesh = new THREE.Mesh(geo, mat); mesh.renderOrder = order; mesh.frustumCulled = false; head.add(mesh); return mesh;
}
const onHead = (x, y, z, lift, out, n) => { const k = 1 / Math.sqrt((x / HEAD_R[0]) ** 2 + (y / HEAD_R[1]) ** 2 + (z / HEAD_R[2]) ** 2); x *= k; y *= k; z *= k;
  const nx = x / HEAD_R[0] ** 2, ny = y / HEAD_R[1] ** 2, nz = z / HEAD_R[2] ** 2, nl = Math.hypot(nx, ny, nz); out.setXYZ(n, x + nx / nl * lift, y + ny / nl * lift, z + nz / nl * lift); };
function fillPatch(mesh, cx, cy, rx, ry, turn, lift) {
  cx = clamp(cx, -0.78, 0.78); cy = clamp(cy, -0.58, 0.58);
  const pos = mesh.geometry.attributes.position, inside = Math.max(0.03, 1 - (cx / HEAD_R[0]) ** 2 - (cy / HEAD_R[1]) ** 2), cz = HEAD_R[2] * Math.sqrt(inside);
  // tangent directions at the centre: along x and along y on the ellipsoid
  let ax = 1, az = -(cx / HEAD_R[0] ** 2) / (cz / HEAD_R[2] ** 2), al = Math.hypot(ax, az); ax /= al; az /= al;
  let by = 1, bz = -(cy / HEAD_R[1] ** 2) / (cz / HEAD_R[2] ** 2), bl = Math.hypot(by, bz); by /= bl; bz /= bl;
  const co = Math.cos(turn), si = Math.sin(turn);
  onHead(cx, cy, cz, lift, pos, 0);
  for (let r = 1; r <= PR; r++) for (let k = 0; k < PS; k++) { const a = k / PS * Math.PI * 2, u = Math.cos(a) * rx * r / PR, v = Math.sin(a) * ry * r / PR, lx = u * co - v * si, ly = u * si + v * co;
    onHead(cx + ax * lx, cy + by * ly, cz + az * lx + bz * ly, lift, pos, 1 + (r - 1) * PS + k); }
  pos.needsUpdate = true;
}
M.mouth = onFace('#d8667c', 2); const mouth = makePatch(M.mouth, 4); mouth.visible = false;
const eyes = [-1, 1].map(s => ({ s, iris: makePatch(M.eye, 3), pupil: makePatch(M.pupil, 4), lid: makePatch(M.lid, 5), blush: makePatch(M.blush, 2) }));
const stripes = [-0.2, 0, 0.2].map(x => ({ x, mesh: makePatch(M.stripe, 3) }));

// Whiskers: three separate hairs per side, each rooted at its own spot on the cheek; light over the face, coat-dark beyond it.
const whiskers = [];
for (const s of [-1, 1]) for (let i = 0; i < 3; i++) {
  const pivot = new THREE.Group(); head.add(pivot);
  const pts = new THREE.QuadraticBezierCurve3(V(0, 0, 0), V(s * 0.24, 0.005, 0), V(s * 0.44, -0.075, 0)).getPoints(14);
  pivot.add(new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts.slice(0, 7)), 8, 0.008, 5), M.whisker));
  pivot.add(new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts.slice(6)), 10, 0.008, 5), M.whiskerOut));
  whiskers.push({ s, i, pivot });
}

/* A limb or tail is a "sausage": a tube whose thickness varies along its length and whose end is rounded. */
const SEG = 48, SIDES = 14, CAP = 5, RINGS = SEG + 1 + CAP;
function makeSausage(mat, order) {
  const geo = new THREE.BufferGeometry(), index = [];
  geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(RINGS * SIDES * 3), 3));
  for (let r = 0; r < RINGS - 1; r++) for (let k = 0; k < SIDES; k++) { const a = r * SIDES + k, b = r * SIDES + (k + 1) % SIDES, c = a + SIDES, d = b + SIDES; index.push(a, b, c, b, d, c); }
  geo.setIndex(index); const mesh = new THREE.Mesh(geo, mat); mesh.frustumCulled = false; mesh.renderOrder = order; return mesh;
}
const sP = V(0, 0, 0), sT = V(0, 0, 0), sN = V(0, 0, 0), sB = V(0, 0, 0);
function shapeSausage(mesh, path, radius, ref) {
  const pos = mesh.geometry.attributes.position; let n = 0, endR = 0;
  for (let r = 0; r < RINGS; r++) {
    let rad;
    if (r <= SEG) { const t = r / SEG; path.getPoint(t, sP); path.getTangent(t, sT); rad = radius(t); if (r === SEG) endR = rad; }
    else { const a = (r - SEG) / CAP * Math.PI / 2; path.getPoint(1, sP); path.getTangent(1, sT); sP.addScaledVector(sT, endR * Math.sin(a)); rad = endR * Math.cos(a); }
    sN.copy(ref).addScaledVector(sT, -ref.dot(sT)).normalize(); sB.crossVectors(sT, sN);
    for (let k = 0; k < SIDES; k++) { const a = k / SIDES * Math.PI * 2, c = Math.cos(a) * rad, d = Math.sin(a) * rad; pos.setXYZ(n++, sP.x + sN.x * c + sB.x * d, sP.y + sN.y * c + sB.y * d, sP.z + sN.z * c + sB.z * d); }
  }
  pos.needsUpdate = true;
}
const smooth = (a, b, v) => { const t = clamp((v - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };
const AX = V(1, 0, 0), AZ = V(0, 0, 1);

// Tail: starts inside the hip so it grows out of the body, thick at the root and tapering to a round tip.
const tailCurve = new THREE.CatmullRomCurve3([V(0.3, 0.36, -0.75), V(0.82, 0.2, -0.64), V(1.16, 0.3, -0.5), V(1.3, 0.58, -0.42), V(1.46, 0.8, -0.37), V(1.66, 0.87, -0.35)], false, 'catmullrom', 0.5);
const tail = makeSausage(M.tail, 1); cat.add(tail);
let TAIL_K = 1;
const buildTail = k => { TAIL_K = k; shapeSausage(tail, tailCurve, t => 0.16 * TAIL_K * (1 + 0.7 * (1 - smooth(0, 0.16, t)) ** 2), AZ); };
buildTail(1);
// Asleep, the tail comes down and lies curled on the desk beside the body.
const TAIL_UP = tailCurve.points.map(q => q.clone()), TAIL_DOWN = [V(0.3, 0.36, -0.75), V(0.84, 0.15, -0.62), V(1.22, 0.12, -0.42), V(1.44, 0.12, -0.1), V(1.46, 0.12, 0.26), V(1.3, 0.12, 0.52)];
let tailDown = 0;
let tailWag = 0;
const poseTail = (k, wag = 0) => { if (Math.abs(k - tailDown) < 0.002 && Math.abs(wag - tailWag) < 0.002) return; tailDown = k; tailWag = wag; const e = k * k * (3 - 2 * k), n = tailCurve.points.length; tailCurve.points.forEach((q, i) => { q.lerpVectors(TAIL_UP[i], TAIL_DOWN[i], e); const tip = Math.max(0, (i - (n - 3)) / 2); q.x += wag * 0.22 * tip * tip; q.y += Math.abs(wag) * 0.05 * tip; }); buildTail(TAIL_K); };

/* ---------- forelimbs: oval-ended legs from the shoulder to wherever the paw is ---------- */
const SHOULDER = { L: V(-0.25, 1.5, 0.19), R: V(0.25, 1.5, 0.19) };       // world; L is screen left = the cat's right paw
let LEG_R = 0.16, FOOT = 1;
const REST = { L: V(-0.23, 0.11, 0.76), R: V(0.23, 0.11, 0.76) }, UP = { L: V(-0.46, 1.1, 0.9), R: V(0.46, 1.1, 0.9) };
const paws = {};
// 前爪的几何是用世界坐标直接算的（不挂在 cat 下面），所以单独收进一个组：
// 打滚时给 cat 和 limbsG 施加同一套变换，身体和爪子才不会分开。
const limbsG = new THREE.Group(); scene.add(limbsG);
for (const side of ['L', 'R']) {
  const rim = makeSausage(M.line, 1), core = makeSausage(M.fur, 2); limbsG.add(rim, core);
  const root = ball(1, M.fur); limbsG.add(root);                       // closes the top of the leg inside the chest
  const foot = new THREE.Group(); limbsG.add(foot); const fr = add(foot, ball(1, M.line, 0.216, 0.118, 0.325), 0, -0.012, 0.022), ff = add(foot, ball(1, M.patch, 0.2, 0.11, 0.31), 0, 0, 0); fr.renderOrder = 2; ff.renderOrder = 3;
  paws[side] = { side, rim, core, foot, root, pos: REST[side].clone(), to: REST[side].clone(), from: V(0, 0, 0), tapAt: -1e9, landed: true, landedAt: -1e9, pending: null, held: 0, mode: 'rest' };
}
const tmpC = V(0, 0, 0), curve = new THREE.QuadraticBezierCurve3(V(0, 0, 0), V(0, 0, 0), V(0, 0, 0));
const legRadius = t => LEG_R * mix(1.6, 0.8, smooth(0, 0.8, t)), rimRadius = t => legRadius(t) + RIM_W * smooth(0.3, 0.6, t); let RIM_W = 0.03;
function drawLimb(p, shoulder) {
  // A leg hangs straight when the paw is on the desk below it, and bends at the elbow as the paw lifts or reaches.
  const s = p.side === 'L' ? -1 : 1, tip = tmpC.copy(p.pos); p.foot.position.copy(p.pos); tip.y += 0.05 * FOOT; tip.z -= 0.1 * FOOT;
  const dx = tip.x - shoulder.x, dz = tip.z - shoulder.z, drop = shoulder.y - tip.y, slack = clamp(1 - drop / 1.25, 0, 1), far = Math.hypot(dx, dz);
  curve.v0.copy(shoulder); curve.v2.copy(tip);
  curve.v1.set(shoulder.x + dx * 0.5 + s * (0.1 * slack + 0.04 * far), tip.y + drop * (0.5 - 0.35 * slack) + 0.16 * far, shoulder.z + dz * 0.5 + 0.08 + 0.45 * slack + 0.1 * far);
  // Standing on the desk, the leg bows forward just enough to sit in front of the chest so its outline shows; reaching out, the outline thins.
  const out = smooth(0.6, 1.0, far), lifted = smooth(0.25, 0.7, p.pos.y);   // a lifted paw keeps a full outline
  { const fr = p.foot.children[0]; fr.position.set(0, -0.012 - 0.024 * lifted, 0.022 * (1 - lifted)); fr.scale.set(0.216 - 0.01 * lifted, 0.118, 0.325 - 0.01 * lifted); } curve.v1.z = mix(Math.max(curve.v1.z, tip.z + 0.32), curve.v1.z, Math.max(out, lifted)); RIM_W = mix(0.03, 0.013, Math.max(out, lifted));
  shapeSausage(p.core, curve, legRadius, AX); shapeSausage(p.rim, curve, rimRadius, AX);
  p.root.position.copy(shoulder); p.root.scale.setScalar(legRadius(0) * 1.02);
}

/* ---------- coats and backgrounds ---------- */
const COATS = [
  { id: 'tuxedo', name: '奶牛猫', fur: '#151515', patch: '#f8f6ef', line: '#8b8f86', eye: '#e2b93b', whisker: '#f4f4ee', stripe: '#151515', inner: '#151515' },
  { id: 'orange', name: '橘猫', pattern: 'tabby', fur: '#e9973f', patch: '#fbe8c9', line: '#7a4312', eye: '#5c8a3a', whisker: '#fffaf0', stripe: '#c26a1f', inner: '#e9973f' },
  { id: 'tabby', name: '狸花猫', pattern: 'tabby', fur: '#a08a6c', patch: '#a08a6c', line: '#3f3324', eye: '#8fae4a', whisker: '#f4f0e4', stripe: '#4d3d2b', inner: '#d9a79a' },
  { id: 'calico', name: '三花猫', pattern: 'calico', fur: '#f8f6ef', patch: '#f8f6ef', patchA: '#e9973f', patchB: '#1d1c1a', tail: '#1d1c1a', line: '#8a8676', eye: '#c79a2e', whisker: '#b5b1a2', whiskerOut: '#b5b1a2', stripe: '#f8f6ef', inner: '#f2b9b0' },
  { id: 'white', name: '白猫', fur: '#f8f6ef', patch: '#f8f6ef', line: '#8a8676', eye: '#5aa9c9', whisker: '#b5b1a2', whiskerOut: '#b5b1a2', stripe: '#f8f6ef', inner: '#f2b9b0' },
  { id: 'blue', name: '蓝灰猫', fur: '#8090a0', patch: '#8090a0', line: '#3c4650', eye: '#e0a63a', whisker: '#f4f4ee', stripe: '#667686', inner: '#c59aa0' }
];
const WALLS = [['浅色桌面', 'transparent', '#e9ebb6'], ['深色桌面', '#1f2226', '#454c57'], ['蓝色桌面', '#2f5d8a', '#454c57'], ['照片桌面', 'linear-gradient(135deg,#3b2f4a,#b8693f 55%,#e9c46a)', '#454c57']];
function setCoat(i) { const c = COATS[i]; for (const k of ['fur', 'patch', 'line', 'eye', 'whisker', 'stripe', 'inner']) M[k].color.set(c[k]); M.body.color.set('#ffffff'); M.ear.color.set(c.fur); paintCoat(c); M.lid.color.set(c.fur); whiskers.forEach(w => w.pivot.scale.setScalar(0.78)); { const pale = c.fur === '#f8f6ef', o = pale ? '#b5b1a2' : '#f1eee2', w = pale ? 0.7 : 1; renderer.domElement.style.filter = [[w, 0], [-w, 0], [0, w], [0, -w]].map(([x, y]) => `drop-shadow(${x}px ${y}px 0 ${o})`).join(' '); } M.shut.color.set(c.fur === '#101010' || c.fur === '#151515' ? c.eye : c.line); M.whiskerOut.color.set(c.whiskerOut || c.line); muzzle.visible = false; chest.visible = false; hitColor.set(c.eye); [...stageEl.querySelectorAll('#coats button')].forEach((b, n) => b.setAttribute('aria-pressed', n === i)); }
function setWall(i) { stageEl.style.background = WALLS[i][1]; deskMat.color.set(WALLS[i][2]); [...stageEl.querySelectorAll('#walls button')].forEach((b, n) => b.setAttribute('aria-pressed', n === i)); }
COATS.forEach((c, i) => { const b = document.createElement('button'); b.type = 'button'; b.innerHTML = `<span class="sw" style="background:${c.fur}"></span>${c.name}`; b.onclick = () => setCoat(i); $('coats').appendChild(b); });
WALLS.forEach((w, i) => { const b = document.createElement('button'); b.type = 'button'; b.innerHTML = `<span class="sw" style="background:${w[1]}"></span>${w[0]}`; b.onclick = () => setWall(i); $('walls').appendChild(b); });

/* ---------- body shape: a handful of proportions, the same ones a custom pet would set ---------- */
const SHAPE = [
  ['headSize', '头的大小', 0.75, 1.5, 0.86], ['headW', '头的宽度', 0.8, 1.35, 0.94], ['headH', '头的高度', 0.75, 1.25, 1.01], ['neck', '头的高低', -0.3, 0.3, 0.02], ['neckW', '脖子宽度', 0.8, 2.2, 1.31],
  ['earSize', '耳朵大小', 0.5, 1.6, 1.05], ['earSpread', '耳朵间距', 0.6, 1.4, 0.95], ['eyeSize', '眼睛大小', 0.6, 1.8, 1.2], ['eyeSpread', '眼睛间距', 0.6, 1.5, 0.9], ['eyeY', '眼睛高低', -0.25, 0.4, 0.31], ['eyeTilt', '眼睛角度', -0.7, 0.7, -0.08],
  ['bodyW', '身体宽度', 0.7, 1.5, 0.86], ['bodyH', '身体高度', 0.8, 1.3, 0.98],
  ['legThick', '腿的粗细', 0.5, 1.7, 0.97], ['legGap', '两腿间距', 0.5, 1.8, 1], ['footSize', '脚的大小', 0.6, 1.7, 0.89], ['tailThick', '尾巴粗细', 0.4, 1.7, 0.73], ['shoulderW', '脖子下方宽度', 0.8, 1.6, 1.15], ['whiskY', '胡子高低', -0.15, 0.25, 0.08]
];
const P = {}; SHAPE.forEach(([k, , , , d]) => P[k] = d);
function applyShape() {
  head.scale.set(P.headSize * P.headW, P.headSize * P.headH, P.headSize);
  ears.forEach((g, i) => { const s = i ? 1 : -1; g.position.x = s * 0.46 * P.earSpread; g.scale.setScalar(P.earSize); });
  NECK_W = P.neckW; SHOULDER_W = P.shoulderW; buildBody();
  stripes.forEach(st => fillPatch(st.mesh, st.x * 0.8, clamp(P.eyeY + 0.3, 0.34, 0.5) - Math.abs(st.x) * 0.25, 0.04, 0.09, 0, 0.006));   // forehead marks stay above the eyes
  whiskers.forEach(w => { const x = w.s * 0.4, y = P.eyeY * 0.35 - 0.2 + P.whiskY - w.i * 0.085, z = HEAD_R[2] * Math.sqrt(Math.max(0.03, 1 - (x / HEAD_R[0]) ** 2 - (y / HEAD_R[1]) ** 2));
    w.pivot.position.set(x, y, z + 0.008); w.pivot.rotation.set(0, -w.s * 0.52, w.s * (0.2 - w.i * 0.2)); });
  hindFeet.forEach((g, i) => { g.position.x = (i ? 1 : -1) * 0.6 * P.bodyW; g.scale.setScalar(P.footSize); });
  LEG_R = 0.16 * P.legThick; FOOT = P.footSize; for (const side of ['L', 'R']) paws[side].foot.scale.setScalar(P.footSize);
  for (const side of ['L', 'R']) { const s = side === 'L' ? -1 : 1; SHOULDER[side].x = s * Math.min(0.25 * P.legGap, 0.42 * P.bodyW); SHOULDER[side].y = 1.5 * P.bodyH; REST[side].x = s * 0.23 * P.legGap; UP[side].x = s * 0.46 * P.legGap; UP[side].y = 1.1 * P.bodyH;
  }
  buildTail(P.tailThick);
  $('shapeOut').value = SHAPE.filter(([k, , , , d]) => P[k] !== d).map(([k]) => `${k}=${P[k]}`).join(' ') || '默认';
}
SHAPE.forEach(([k, label, lo, hi, d]) => {
  const wrap = document.createElement('label'); wrap.style.cssText = 'display:flex;flex-direction:column;font-size:13px;color:var(--muted)'; wrap.textContent = label;
  const input = document.createElement('input'); input.type = 'range'; input.id = 'sh-' + k; input.min = lo; input.max = hi; input.step = 0.01; input.value = d;
  input.oninput = () => { P[k] = +input.value; applyShape(); }; wrap.appendChild(input); $('sliders').appendChild(wrap);
});
$('btnResetShape').onclick = () => { SHAPE.forEach(([k, , , , d]) => { P[k] = d; $('sh-' + k).value = d; }); applyShape(); };
$('btnCopy').onclick = () => { const out = $('shapeOut'), note = $('copied'); out.select();
  (navigator.clipboard ? navigator.clipboard.writeText(out.value) : Promise.reject()).then(() => note.textContent = '已复制，发给我就行', () => note.textContent = '请手动复制下面这行'); };

/* ---------- state ---------- */
const RISE = 30, FALL = 46, STRIKE = RISE + FALL;
const S = { last: performance.now(), lastKey: -1e9, lastMouse: -1e9, lastInput: performance.now(), sleepAt: 0, down: new Map(), thump: 0, thumpSide: 0, jolt: -1e9, rate: 0,
  turn: 0, nod: 0, tilt: 0, lid: 0, blinkAt: performance.now() + 2500, blinkUntil: 0, happyUntil: 0, bounceAt: -1e9, act: null, actUntil: 0, nextAct: performance.now() + 6000,
  gazeX: 0, gazeY: 0, pointer: null, phase: 0, lastSide: 'L', alt: 'L', spin: 0, spinning: false, mouseDown: false, wigX: 0, wigZ: 0, lidDir: 1, mouseLean: 0, sx: 0, fwd: 0, fwdGoal: 0, demoMouse: 0, chips: [] };
Object.assign(S, { anger: 0, lastStrike: -1e9, slamAt: -1e9, rollDir: 1, loaf: 0, strikes: [], keyRate: 0 });
const sleeping = t => S.sleepAt && t > S.sleepAt;
if (VIEW.get('eyes') === 'shut') { S.blinkUntil = 1e13; S.blinkAt = 1e14; } if (VIEW.get('eyes') === 'happy') S.happyUntil = 1e13; if (VIEW.get('coat')) setTimeout(() => setCoat(+VIEW.get('coat')), 0); if (VIEW.get('wall')) setTimeout(() => setWall(+VIEW.get('wall')), 0);   // preview switches
let SLEEP_AFTER = VIEW.get('sleep') ? +VIEW.get('sleep') * 1000 : (options.sleepMinutes || 15) * 60000;              // falls asleep by itself after this long without keys or mouse
const zzz = document.createElement('div'); zzz.className = 'zzz'; zzz.innerHTML = '<span>Z</span><span>Z</span><span>Z</span>'; stageEl.appendChild(zzz);
const MARK_SVG = '<svg viewBox="0 0 40 40" style="width:1em;height:1em;display:block" aria-hidden="true">' +
  '<g fill="none" stroke="#e8443a" stroke-width="5" stroke-linecap="round">' +
  '<path d="M20 17.4C22.4 13.6 22.4 10.6 20 6.8"/><path d="M22.6 20C26.4 17.6 29.4 17.6 33.2 20"/>' +
  '<path d="M20 22.6C17.6 26.4 17.6 29.4 20 33.2"/><path d="M17.4 20C13.6 22.4 10.6 22.4 6.8 20"/>' +
  '</g></svg>';
const mkMark = () => { const d = document.createElement('div'); d.className = 'ire'; d.innerHTML = MARK_SVG; stageEl.appendChild(d); return d; };
const ire = mkMark(), ireL = mkMark(), ireR = mkMark();
const aura = document.createElement('div'); aura.className = 'aura'; stageEl.appendChild(aura);
const steam = document.createElement('div'); steam.className = 'steam';
steam.innerHTML = '<span></span><span></span><span></span>'; stageEl.appendChild(steam);
const heart = document.createElement('div'); heart.className = 'zzz heart';
heart.innerHTML = '<span>' + '<svg viewBox="0 0 24 24" style="width:1em;height:1em;display:block" aria-hidden="true">' +
  '<path d="M12 20.6S3.4 15 3.4 9.3A4.9 4.9 0 0 1 12 6a4.9 4.9 0 0 1 8.6 3.3C20.6 15 12 20.6 12 20.6z" fill="#e4556a"/>' +
  '</svg>' + '</span>';
stageEl.appendChild(heart);
const wake = t => {
  if (S.sleepAt) {                                  // 猫被叫醒了
    const slept = t - S.sleepAt;
    S.sleepAt = 0; S.blinkUntil = t + 320; S.blinkAt = t + 620; S.wokeAt = t; S.bounceAt = t + 150;
    // 醒过来先伸个懒腰是猫的天性；要是睡了很久（超过两分钟），再抬爪跟你打个招呼
    S.greet = slept > 120000 ? ['stretch', 'wave'] : ['stretch'];
  }
  S.lastInput = t;
};

function land(p, t) {
  p.landed = true; p.landedAt = t; S.thump = 1; S.thumpSide = p.side === 'L' ? -1 : 1; S.jolt = t;
  const k = p.pending; p.pending = null; if (!k) return;
  k.glow = 1; k.down = S.down.has(k.code); addChip(k); if (!k.down) { const c = S.chips[S.chips.length - 1]; setTimeout(() => c.gone = performance.now(), 160); }
}
function strike(side, x, z, t, key) {
  const p = paws[side]; if (!p.landed) land(p, t);
  if (p.mode === 'up') p.pos.copy(UP[side]);
  p.from.copy(p.pos); p.to.set(x, KEY_TOP + 0.09, z); p.tapAt = p.mode === 'up' ? t - RISE : t; p.landed = false; p.pending = key || null; p.mode = 'key';
  S.lastKey = t; lastStrikeAt = t; S.rate = Math.min(12, S.rate + 1); S.lastSide = side;
  // 烦躁值按每秒敲击次数算，不按单次间隔 —— 单次间隔会把正常速度的打字也记成在锤键盘。
  // 这里留最近 2.4 秒的敲击时间戳，交给 frame 里的速率判定。
  S.lastStrike = t;
  S.strikes.push(t);
  while (S.strikes.length && t - S.strikes[0] > 2400) S.strikes.shift();
}
function keyDown(code, t = performance.now()) {
  if (S.down.has(code)) return; wake(t);
  const k = keys.get(code); let side, x, z;
  side = code === 'Space' && t - S.lastMouse < 1600 ? (MOUSE_PAW === 'L' ? 'R' : 'L') : pawFor(code);
  if (k) { x = k.x; z = k.z; if (code === 'Space') x += (side === 'L' ? -1 : 1) * 0.3; } else { x = (side === 'L' ? -1 : 1) * 0.8; z = KB.z0 + 0.55; }
  S.down.set(code, side); strike(side, x, z, t, k); paws[side].held = 1;
}
function keyUp(code) {
  const side = S.down.get(code); if (!side) return; S.down.delete(code);
  const k = keys.get(code); if (k) k.down = false;
  if (![...S.down.values()].includes(side)) paws[side].held = 0;
  const c = S.chips.find(c => c.code === code && !c.gone); if (c) c.gone = performance.now();
}
function addChip(k) { const el = document.createElement('div'); el.className = 'chip'; el.textContent = k.label; stageEl.appendChild(el); S.chips.push({ el, k, code: k.code, born: performance.now(), gone: 0 }); }

let demo = false;
const stopDemo = () => { if (!demo) return; demo = false; $('btnDemo').textContent = '播放演示'; hintEl.textContent = '正在跟随你的键盘'; [...S.down.keys()].forEach(keyUp); };
let lastPointer = null;
on('pointermove', e => { const r = stageEl.getBoundingClientRect(); S.pointer = { x: (e.clientX - r.left) / r.width * 2 - 1, y: (e.clientY - r.top) / r.height * 2 - 1 };
  if (e.pointerType === 'touch') return;
  if (lastPointer) { const dx = e.clientX - lastPointer.x, dy = e.clientY - lastPointer.y; if (Math.abs(dx) + Math.abs(dy) > 2) { const t = performance.now(); wake(t); S.lastMouse = t; S.wigX = clamp(S.wigX + dx * 0.004, -0.16, 0.16); S.wigZ = clamp(S.wigZ + dy * 0.004, -0.12, 0.12); } }
  lastPointer = { x: e.clientX, y: e.clientY }; });
// Only a press on the head is a pet: the eyes arch shut and the head leans into the hand for as long as it is held.
const petRay = new THREE.Raycaster(), petAt = new THREE.Vector2();
const onHeadAt = e => { if (!stageEl.contains(e.target) || (e.target.closest && e.target.closest('button, input, a'))) return 0; const r = renderer.domElement.getBoundingClientRect(); petAt.set((e.clientX - r.left) / r.width * 2 - 1, -((e.clientY - r.top) / r.height * 2 - 1)); petRay.setFromCamera(petAt, camera);
  if (!petRay.intersectObject(head, true).length) return 0; proj.setFromMatrixPosition(head.matrixWorld).project(camera); return petAt.x > proj.x ? -1 : 1; };
on('pointerdown', e => { const t = performance.now(), side = onHeadAt(e); if (side) { wake(t); S.pet = true; S.petSide = side; S.happyUntil = 1e15; return; }
});
on('pointerout', e => { if (!e.relatedTarget) S.pointer = null; });   // cursor left the window: stop staring at where it was
const endPet = () => { if (S.pet) { S.pet = false; S.happyUntil = performance.now() + 900; } };
on('pointerup', endPet); on('pointercancel', endPet);
$('btnDemo').onclick = () => { if (demo) stopDemo(); else { demo = true; demoI = 0; demoNext = performance.now() + 300; $('btnDemo').textContent = '停止演示'; hintEl.textContent = '演示中，敲任意键接管'; } };
$('btnSleep').onclick = () => { stopDemo(); S.sleepAt = performance.now() + 300; S.lastKey = S.lastMouse = -1e9; };
$('btnSpin').onclick = () => { S.spinning = true; S.spin = 0; };

const DEMO = 'hello deskcat '; let demoI = 0, demoNext = performance.now() + 900, demoHold = null, demoRest = false;
function runDemo(t) {
  if (!demo || t < demoNext) return;
  if (demoHold) { keyUp(demoHold); demoHold = null; demoNext = t + rnd(70, 170); if (demoRest) { demoRest = false; demoNext = t + 6200; S.demoMouse = t + 4600; S.lastMouse = t; } return; }
  const ch = DEMO[demoI++], code = ch === ' ' ? 'Space' : 'Key' + ch.toUpperCase();
  keyDown(code, t); demoHold = code; demoNext = t + rnd(80, 130); if (demoI >= DEMO.length) { demoI = 0; demoRest = true; }
}

/* ---------- 空闲动作怎么挑 ---------- */
// 纯随机抽的话，17 个动作里总有几个永远轮不到。
// 用洗牌袋：一轮里每个动作保证出现一次，抽完再洗，且不会连着两次同一个。
let bag = [], lastAct = '';
function pickAct(t, POOL) {
  // 有一阵子没人管它了：更倾向于探头看看你在不在
  if (t - S.lastInput > 75000 && Math.random() < 0.45) return 'peek';
  if (!bag.length || (bag.length === 1 && bag[0] === lastAct)) {
    bag = POOL.slice();
    for (let i = bag.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); const tmp = bag[i]; bag[i] = bag[j]; bag[j] = tmp; }
  }
  // 别连着两次同一个动作：把队尾换成袋里任意一个不是它的
  if (bag.length > 1 && bag[bag.length - 1] === lastAct) {
    const i = bag.findIndex(a => a !== lastAct);
    if (i >= 0) { const tmp = bag[i]; bag[i] = bag[bag.length - 1]; bag[bag.length - 1] = tmp; }
  }
  lastAct = bag.pop();
  return lastAct;
}

/* ---------- frame ---------- */
const shoulderW = V(0, 0, 0), proj = V(0, 0, 0), tmpGoal = V(0, 0, 0), markV = V(0, 0, 0);
// 任何一帧里出错都不许把整只猫停在半空：包一层，记下来，继续下一帧。
let frameErrs = 0;
function frame() {
  try { frameBody(); } catch (err) {
    if (frameErrs++ < 6) { (window.__catErrs = window.__catErrs || []).push(String((err && err.message) || err)); console.error('[catpet] 动画出错', err); }
    raf = requestAnimationFrame(frame);
  }
}
function frameBody() {
  const t = performance.now(), realDt = Math.min(1, (t - S.last) / 1000), dt = Math.min(0.05, realDt); S.last = t;
  const ease = k => 1 - Math.exp(-dt * k);
  runDemo(t);
  if (!S.sleepAt && !demo && t - S.lastInput > SLEEP_AFTER) S.sleepAt = t;
  if (VIEW.get('pose')) { S.act = VIEW.get('pose'); S.actUntil = t + (+VIEW.get('left') || 900); }   // preview switch: hold one idle action at a chosen moment
  const typing = t - S.lastKey < 3000, hover = VIEW.has('hover') || t - S.lastKey < 900, asleep = sleeping(t);   // hover: paws stay raised only briefly after the last key
  if (demo && t < S.demoMouse) { S.lastMouse = t; S.wigX = Math.sin(t / 170) * 0.12; S.wigZ = Math.cos(t / 230) * 0.08; S.mouseDown = S.demoMouse - t < 900 && S.demoMouse - t > 650; }
  const mouseOn = mouseGroup.visible && t - S.lastMouse < 1600 && !asleep, mousing = mouseGroup.visible && t - S.lastMouse < 2200 && S.lastMouse > S.lastKey && !asleep;   // paw on the mouse / whole attention on the mouse
  S.wigX *= Math.exp(-dt * 5); S.wigZ *= Math.exp(-dt * 5); S.mouseLean += ((mousing ? 1 : 0) - S.mouseLean) * ease(6);
  // 小老鼠跟着真实鼠标：位置跟着晃，按下去会被按扁、染色，右键还会往另一边歪一点
  if (VIEW.has('press')) S.mouseDown = +VIEW.get('press') !== 0;   // URL 参数：直接指定按下 / 松开样子
  S.mousePress = (S.mousePress || 0) + ((S.mouseDown ? 1 : 0) - (S.mousePress || 0)) * ease(S.mouseDown ? 40 : 15);
  if (VIEW.has('press')) S.mousePress = clamp(+VIEW.get('press'), 0, 1);
  const mp = S.mousePress;
  mouseGroup.position.set(MOUSE_AT.x + (DESK_DIR > 0 ? Math.min(S.wigX, 0.05) : Math.max(S.wigX, -0.05)), -0.03 * mp, MOUSE_AT.z + S.wigZ);
  mouseGroup.rotation.z = (S.clickRight ? 1 : -1) * 0.16 * mp;
  mouseBody.material.color.copy(capColor).lerp(hitColor, mp);
  mouseBody.scale.set(0.7 * (1 + 0.1 * mp), 0.42 * (1 - 0.26 * mp), 1.2 * (1 + 0.06 * mp));
  mouseRim.scale.set(0.77 * (1 + 0.1 * mp), 0.47 * (1 - 0.24 * mp), 1.27 * (1 + 0.06 * mp));
  S.rate *= Math.exp(-dt * 1.2);
  // ── 烦躁值 ──
  // 只有「持续锤键盘」才涨：每秒 7 下以内（正常打字、办公、写代码）完全不计。
  // 7~12 下开始涨，越快涨得越猛；手一慢/一停就自己消。
  // 必须按当前时间剪掉过期的敲击记录：只在 strike() 里剪的话，一停手就没有
  // 新的 strike 触发剪枝，keyRate 会停在最后一刻，火气散不掉。
  while (S.strikes.length && t - S.strikes[0] > 2400) S.strikes.shift();
  S.keyRate = S.strikes.length / 2.4;
  const over = S.keyRate - 7;
  if (over > 0) S.anger = Math.min(1, S.anger + dt * over * 0.05);
  else {
    // 停手越久消得越快：正常节流 0.3/s，明显慢下来 0.45/s，彻底不碰键盘 0.8/s
    const rest = t - S.lastKey;
    const decay = (over < -2 ? 0.45 : 0.3) + (rest > 2500 ? 0.35 : 0);
    S.anger = Math.max(0, S.anger - dt * decay);
  }
  const fast = clamp(S.anger, 0, 1);   // 0 = 慢悠悠地打，1 = 快被敲疯了
  S.slamming = t - S.slamAt < 700;
  if (fast > 0.96 && t - S.slamAt > 5000 && !asleep) {              // 忍无可忍：一巴掌拍在键盘上，然后气消一半
    S.slamAt = t; S.anger = 0.52; S.thump = 1.8; S.bounceAt = t - 420; S.jolt = t; S.auraFlash = 1;
    for (const sd of ['L', 'R']) paws[sd].held = 0;
  }
  S.thump *= Math.exp(-dt * 13);

  if (dead) return;
  { const now = performance.now(); if (now - Math.max(S.lastKey, S.lastMouse, S.wokeAt || 0, S.fullUntil || 0) > 2500 && !S.pet && now >= S.happyUntil && (halfRate = !halfRate)) { raf = requestAnimationFrame(frame); return; } }
  const w = stageEl.clientWidth, h = stageEl.clientHeight; if (!w || !h) { raf = requestAnimationFrame(frame); return; }
  zzz.style.fontSize = (w * 0.063) + 'px';
  if (renderer.domElement.width !== Math.round(w * renderer.getPixelRatio()) || renderer.domElement.height !== Math.round(h * renderer.getPixelRatio())) { renderer.setSize(w, h, false); camera.aspect = w / h; camera.fov = w / h < 1 ? 38 : 31; camera.updateProjectionMatrix(); }
  if (VIEW.has('a')) S.spin = +VIEW.get('a');
  if (S.spinning) { S.spin += dt * 2.4; if (S.spin >= Math.PI * 2) { S.spin = 0; S.spinning = false; } }
  camera.position.set(Math.sin(S.spin) * CAM.z, CAM.y, Math.cos(S.spin) * CAM.z + (1 - Math.cos(S.spin)) * LOOK.z); camera.lookAt(LOOK);

  // keys
  const jolt = 0.03 * Math.exp(-(t - S.jolt) / 55) + 0.13 * Math.exp(-(t - S.slamAt) / 190); board.position.y = -jolt;
  keys.forEach(k => { if (!k.down && k.glow > 0) k.glow = Math.max(0, k.glow - dt * 5); k.mesh.position.y = 0.145 - (k.down ? 0.045 : 0); k.mesh.material.color.copy(k.base).lerp(hitColor, k.glow); });

  // body
  S.phase += dt * (asleep ? 0.9 : 1.7 + Math.min(1.4, S.rate * 0.14));
  const breath = reduceMotion ? 0 : Math.sin(S.phase), bounceE = (t - S.bounceAt) / 420, bounce = bounceE < 1 ? Math.sin(Math.PI * bounceE) : 0;
  const reach = (paws.L.pos.z > 0.86 ? paws.L.pos.x - REST.L.x : 0) + (paws.R.pos.z > 0.86 ? paws.R.pos.x - REST.R.x : 0);
  const act0 = S.act, stretching = act0 === 'stretch', licking = act0 === 'lick', yawning = act0 === 'yawn', flicking = act0 === 'tail', pouncing = act0 === 'pounce', rolling = act0 === 'roll', chasing = act0 === 'chase', loafing = act0 === 'loaf',
        grooming = act0 === 'groom', waving = act0 === 'wave', scratching = act0 === 'scratch',
        peeking = act0 === 'peek', sneezing = act0 === 'sneeze', hopping = act0 === 'hop', lookCam = act0 === 'lookCam', actLeft = S.actUntil - t;
  const yawn = yawning ? Math.sin(clamp(1 - actLeft / 1900, 0, 1) * Math.PI) ** 0.7 : 0, crouch = pouncing && actLeft > 520, swat = pouncing && actLeft <= 520 && actLeft > 120;
  const sn = sneezing ? Math.sin(clamp(1 - actLeft / 800, 0, 1) * Math.PI) : 0;      // 打喷嚏：整只猫缩一下
  if (pouncing && actLeft <= 520 && !S.pounced) { S.pounced = true; S.bounceAt = t; } if (!pouncing) S.pounced = false;
  S.loaf += ((loafing ? 1 : 0) - S.loaf) * ease(4.5);
  // 每个动作有自己的「底盘」：洗脸/舔爪/挠痒会先蹲下去一点，不是站着比划
  const STANCE = { groom: 0.92, lick: 0.86, scratch: 0.6, yawn: 0.34, roll: 0.8, chase: 0.3, peek: 0.26, lookCam: 0.18, sneeze: 0.5 };
  // 伸懒腰反着来：身子往上拔（负数 = 比站着还高），不是往下蹲
  const stanceGoal = stretching ? -0.75 : crouch ? 0.7 : (STANCE[act0] || 0);
  S.low = (S.low || 0) + (stanceGoal - (S.low || 0)) * ease(crouch ? 9 : 4.6);
  if (VIEW.has('low')) S.low = clamp(+VIEW.get('low'), 0, 1);   // URL 参数直接指定蹲伏深度
  // 蹲下去要看得见：光靠「头低一点」不像，必须让整个身子矮下来、屁股圆起来。
  // squat 同时压躯干、压肩（肩一低，前腿自动弯），所以是整只猫坐下来，不是被按扁。
  const loaf = S.loaf, squat = 1 - 0.42 * loaf - 0.42 * S.low - 0.16 * sn;       // asleep the cat settles down into a loaf; a stretch dips the chest
  torso.scale.set(P.bodyW * (1 + 0.2 * loaf + 0.17 * S.low + breath * (0.012 + 0.012 * loaf) - bounce * 0.03), P.bodyH * squat * (1 + breath * 0.012 + bounce * 0.05 - S.thump * (0.012 + 0.02 * fast)), 1 + 0.1 * loaf + 0.07 * S.low + breath * 0.02);
  // The body leans toward what the paws are doing, so the arms keep their length instead of stretching.
  let farZ = 0; for (const sd of ['L', 'R']) { const q = paws[sd]; if (q.held || t - q.tapAt < 260) farZ = Math.max(farZ, q.to.z); }
  if (farZ) S.fwdGoal = clamp(0.14 + (farZ - KB.z0) * 0.32, 0.14, 0.42);
  S.fwd += ((asleep ? 0 : mousing ? 0.2 : hover ? S.fwdGoal : 0) - S.fwd) * ease(7);
  S.sx += (clamp(reach * 0.13, -0.2, 0.2) - DESK_DIR * S.mouseLean * 0.24 - S.sx) * ease(9);
  const sx = S.sx + S.thump * S.thumpSide * 0.012 + (crouch ? Math.sin(t / 55) * 0.02 : 0), fwd = S.fwd;
  upper.matrix.set(1, sx, 0, 0,  0, 1 - fwd * fwd * 0.35, 0, 0,  0, fwd, 1, 0,  0, 0, 0, 1);
  const tailGoal = asleep ? 1 : (loafing || grooming || licking || scratching) ? 0.8 : rolling ? 0.5 : 0;
  S.tailDown = (S.tailDown || 0) + (tailGoal - (S.tailDown || 0)) * ease(2.6); poseTail(S.tailDown < 0.003 ? 0 : S.tailDown > 0.997 ? 1 : S.tailDown, flicking ? Math.sin(t / 85) * Math.sin(clamp(1 - actLeft / 1400, 0, 1) * Math.PI) : crouch ? Math.sin(t / 60) * 0.5 : 0);
  tail.rotation.z = Math.sin(t / 900) * 0.05 * (1 - S.tailDown) + (typing ? Math.sin(t / (160 - 70 * fast)) * (0.02 + 0.07 * fast) : 0);
  if (chasing) tail.rotation.z = Math.sin(t / 130) * 0.62 * (1 - S.tailDown);

  // head
  const happy = t < S.happyUntil, calm = !typing && !asleep && !happy && !mousing;
  if (S.wantStretch) { S.wantStretch = false; if (calm && !reduceMotion) { S.act = 'stretch'; S.actUntil = t + 1700; S.nextAct = t + rnd(6000, 12000); } }
  const GREET_DUR = { stretch: 1800, wave: 1500 };
  if (calm && !reduceMotion && S.greet && S.greet.length) {         // 刚睡醒：先伸懒腰，睡很久了再打个招呼
    S.act = S.greet.shift(); S.actManual = false; S.actUntil = t + (GREET_DUR[S.act] || 1500); S.nextAct = t + rnd(5200, 9000);
  } else if (calm && !reduceMotion && t > S.nextAct) {              // 闲下来就随便做点什么
    const POOL = ['lookL', 'lookR', 'tilt', 'ear', 'lick', 'stretch', 'yawn', 'roll', 'chase', 'loaf', 'tail',
      'groom', 'groom', 'peek', 'wave', 'scratch', 'sneeze', 'hop', 'lookCam',
      'lookL', 'tilt', 'stretch', 'groom', 'lookR'];
    const DUR = { lookL: 1700, lookR: 1700, tilt: 1700, ear: 420, lick: 3200, stretch: 1800, yawn: 1900,
      roll: 1500, chase: 2600, loaf: 4200, tail: 1400, groom: 3000, peek: 1400, wave: 1500,
      scratch: 1200, sneeze: 800, hop: 620, lookCam: 1300 };
    S.act = pickAct(t, POOL); S.actManual = false;
    if (S.act === 'roll') S.rollDir = Math.random() < 0.5 ? -1 : 1;
    S.actUntil = t + (DUR[S.act] || 1700); S.nextAct = t + rnd(3200, 7000);
  }
  // 点菜单必然要动鼠标，而 mousing 会让 calm 变 false —— 手动点播的动作因此被秒杀。
  // 所以手动动作只受「打字 / 睡着」打断。
  if (S.act && (t > S.actUntil || (!calm && !(S.actManual && !typing && !asleep)))) { S.act = null; S.actManual = false; }
  const looking = typing && t - S.lastKey < 1000;
  // While the real cursor is moving, the cat watches the cursor itself: direction is measured from the head's place on screen.
  const follow = mousing && S.pointer && !(demo && t < S.demoMouse); let pdx = 0, pdy = 0;
  if (follow) { proj.setFromMatrixPosition(head.matrixWorld).project(camera); pdx = S.pointer.x - proj.x; pdy = S.pointer.y + proj.y; }
  const turnT = asleep ? 0 : chasing ? Math.sin(t / 520) * 0.42 : grooming ? Math.sin(t / 700) * 0.08 : lookCam ? 0 : follow ? clamp(pdx * 0.5, -0.4, 0.4) : mousing ? -0.36 * DESK_DIR : looking ? (S.lastSide === 'L' ? -0.3 : 0.3) : S.act === 'lookL' ? -0.45 : S.act === 'lookR' ? 0.45 : S.pointer && !typing ? clamp(S.pointer.x, -1, 1) * 0.22 : 0;
  const nodT = asleep ? 0.5 : yawning ? -0.3 * yawn : grooming ? 0.32 + Math.sin(t / 120) * 0.06 : scratching ? 0.16 : peeking ? -0.1 : hopping ? -0.12 : sneezing ? 0.55 * sn : crouch ? 0.16 : happy ? -0.12 : licking ? 0.34 + Math.sin(t / 140) * 0.09 : stretching ? -0.18 : looking ? 0.3 : follow ? clamp(pdy * 0.5, -0.28, 0.4) : mousing ? 0.22 : S.pointer && !typing ? clamp(S.pointer.y * 0.2, -0.16, 0.2) : 0, tiltT = asleep ? 0.16 : rolling ? -S.rollDir * 0.18 : licking ? -0.12 : scratching ? -0.2 : waving ? 0.12 : grooming ? Math.sin(t / 500) * 0.06 : S.act === 'tilt' ? 0.2 : happy ? (S.petSide || -1) * 0.1 + Math.sin(t / 330) * 0.06 : 0;
  S.turn += (turnT - S.turn) * ease(7); S.nod += (nodT - S.nod) * ease(6); S.tilt += (tiltT - S.tilt) * ease(rolling ? 9 : 5);
  { const w = (t - (S.wokeAt || -1e9)) / 750; S.shake = w > 0.15 && w < 1 ? Math.sin(w * 26) * 0.16 * (1 - w) : 0; }
  head.rotation.set(S.nod + S.thump * (0.05 + 0.05 * fast), S.turn + S.shake + (fast > 0.55 ? Math.sin(t / 55) * 0.085 * (fast - 0.55) / 0.45 : 0), S.tilt); head.position.z = 0.1 - fwd * 0.5 + 0.3 * loaf + 0.1 * S.low + (peeking ? 0.22 : 0); head.position.y = (2.3 * P.bodyH + P.neck) * (1 - 0.43 * loaf - 0.4 * S.low) + breath * 0.018 + bounce * 0.09 - (asleep ? 0.14 : 0) - S.thump * 0.02;
  { const py = head.position.y; headFix.matrix.set(1, -sx, 0, sx * py,  0, 1, 0, 0,  0, -fwd, 1, fwd * py,  0, 0, 0, 1); }
  const flick = S.act === 'ear' ? Math.sin((S.actUntil - t) / 420 * Math.PI * 2) * 0.28 : sneezing ? Math.sin(t / 30) * 0.34 * sn : scratching ? Math.sin(t / 45) * 0.12 : 0;
  { const relax = S.lidDir < 0 ? 0.2 * smooth(0.5, 1, S.lid) : 0; ears[0].rotation.z = 0.24 + relax + flick; ears[1].rotation.z = -0.24 - relax - flick * 0.5; ears[0].rotation.x = ears[1].rotation.x = -0.62 * fast; }

  // eyes
  if (t > S.blinkAt) { S.blinkUntil = t + 130; S.blinkAt = t + rnd(2600, 5600); }
  S.lidDir = 1;                      // happy: lower lid rises into an arch; blink and sleep: upper lid comes down
  const lidT = asleep || t < S.blinkUntil || happy || licking || grooming || stretching || loafing || yawn > 0.25 ? 1 : 0; S.lid += (lidT - S.lid) * (1 - Math.exp(-realDt * (lidT > S.lid ? 34 : 16)));   // eyelids keep real time even if frames are dropped
  const gx = follow ? clamp(pdx * 2.2, -1, 1) : mousing ? -0.8 * DESK_DIR : looking ? (S.lastSide === 'L' ? -0.5 : 0.5) : S.pointer ? clamp(S.pointer.x * 1.2, -1, 1) : 0, gy = follow ? clamp(pdy * 2.2, -1, 1) : looking || mousing ? 1 : S.pointer ? clamp(S.pointer.y * 1.3, -1, 1) : 0;
  S.gazeX += (gx - S.gazeX) * ease(9); S.gazeY += (gy - S.gazeY) * ease(9);
  const widen = (looking ? 1.25 : pouncing ? 1.9 : 1) * (1 - 0.45 * fast);
  const ex = 0.37 * P.eyeSpread, ey = P.eyeY, er = 0.205 * P.eyeSize, iry = er * 0.74, c = S.lid, dir = S.lidDir || 1;
  for (const e of eyes) {                                           // the eye keeps its shape; a fur-coloured lid slides over it and leaves a soft crescent
    // Closing: the eye squashes flat, then becomes one clean curved line (down-curve for a blink or sleep, arch when happy).
    const pet = dir < 0, shut = c > 0.7, h = iry * mix(1, pet ? 0.7 : 0.3, smooth(0, 0.8, c)), eyc = ey + (dir * h * (pet ? 0.84 : 0.7) - iry) * smooth(0.35, 0.7, c);   // the closed line rests half an eye below the eye's centre
    e.iris.material = shut ? M.shut : M.eye;
    fillPatch(e.iris, e.s * ex, eyc, er * (shut ? (pet ? 0.8 : 0.92) : 1), h, e.s * P.eyeTilt, 0.008);
    const prx = er * 0.3 * widen, dx = clamp(S.gazeX * er * 0.42, -(er * 0.9 - prx), er * 0.9 - prx);
    const room = h * Math.sqrt(Math.max(0, 1 - ((Math.abs(dx) + prx * 0.7) / er) ** 2));   // how tall the eye is where the pupil sits
    const pry = Math.min(er * 0.62, room * 0.68), dy = clamp(-S.gazeY * iry * 0.34, -(room - pry), room - pry);
    fillPatch(e.pupil, e.s * ex + dx, eyc + dy, prx, pry, e.s * P.eyeTilt * 0.5, 0.013);
    e.pupil.visible = c < 0.45; e.lid.visible = shut;
    if (shut) fillPatch(e.lid, e.s * ex, eyc + dir * h * (pet ? 0.32 : 0.6), er * (pet ? 0.8 : 1.08), h, e.s * P.eyeTilt, 0.018);
    const joy = pet ? smooth(0.5, 1, c) : 0;                         // being petted: rosy cheeks appear and the ears relax outward
    e.blush.visible = joy > 0.02; if (e.blush.visible) fillPatch(e.blush, e.s * ex * 1.42, ey - er * 1.3, er * 0.46 * joy, er * 0.25 * joy, 0, 0.007);
  }

  // 打滚：猫打滚是「侧着躺下去、扭两下、再爬起来」，不是原地翻跟头。
  // 所以只倒到 60 度左右，绕脚底转（身体自然侧倒），不绕身体中心。
  if (rolling) {
    const q = clamp(1 - actLeft / 1500, 0, 1);
    const tip = q < 0.26 ? q / 0.26 : q > 0.76 ? 1 - (q - 0.76) / 0.24 : 1;      // 倒下 / 躺着 / 起来
    const e = tip * tip * (3 - 2 * tip);
    const rock = (q > 0.26 && q < 0.76) ? Math.sin((q - 0.26) / 0.5 * Math.PI * 3) * 0.1 * e : 0;
    const an = S.rollDir * (1.48 * e + rock);
    // 绕脚底转会把身子甩到一边去，往回拉一点，再缩一点（猫打滚本来就是蜷起来的），
    // 这样是「就地躺倒」，既不会飘出去，也不会顶到窗口边上被裁掉。
    const sc = 1 - 0.2 * e;
    for (const g of [cat, limbsG]) { g.rotation.z = an; g.position.x = -0.5 * Math.sin(an); g.position.y = 0.04 * e; g.scale.setScalar(sc); }
    // 身子横过去了，头得往回拧一点 —— 猫躺下时脸还是朝着你的，不然看着像整张贴图被转了个角度
    head.rotation.z -= an * 0.78;
  } else if (!hopping && (cat.rotation.z || cat.position.x || cat.position.y || limbsG.rotation.z || Math.abs(cat.scale.x - 1) > 0.001)) {
    const k = ease(14);
    for (const g of [cat, limbsG]) { g.rotation.z += -g.rotation.z * k; g.position.x += -g.position.x * k; g.position.y += -g.position.y * k; }
    const sc2 = cat.scale.x + (1 - cat.scale.x) * k;
    for (const g of [cat, limbsG]) g.scale.setScalar(sc2);
    if (Math.abs(cat.rotation.z) < 0.002) for (const g of [cat, limbsG]) { g.rotation.z = 0; g.position.x = 0; g.position.y = 0; g.scale.setScalar(1); }
  }

  if (hopping) { const q = clamp(1 - actLeft / 620, 0, 1); for (const g of [cat, limbsG]) g.position.y = Math.sin(q * Math.PI) * 0.4; }

  // paws
  for (const side of ['L', 'R']) {
    const p = paws[side], since = t - p.tapAt;
    if (since < STRIKE) {
      const k = 1 - Math.pow(1 - Math.min(1, since / 60), 3); p.pos.lerpVectors(p.from, p.to, k);
      p.pos.y = since < RISE ? mix(p.from.y, Math.max(p.from.y, p.to.y + 0.7), since / RISE) : mix(Math.max(p.from.y, p.to.y + 0.7), p.to.y - 0.03, Math.pow((since - RISE) / FALL, 2));
    } else {
      if (!p.landed) land(p, t);
      if (p.held) { p.pos.x += (p.to.x - p.pos.x) * ease(30); p.pos.z += (p.to.z - p.pos.z) * ease(30); p.pos.y += (p.to.y - 0.04 - p.pos.y) * ease(30); }
      else if (rolling && since > STRIKE + 110) {          // 躺着的时候四脚朝天蹬
        p.mode = 'air'; tmpGoal.copy(UP[side]);
        tmpGoal.y += 0.18 + Math.sin(t / 95 + (side === 'L' ? 0 : Math.PI)) * 0.09;
        tmpGoal.z += 0.12; p.pos.lerp(tmpGoal, ease(15));
      }
      else if (stretching && since > STRIKE + 110) {          // 伸懒腰：两只前爪一起举到耳朵两侧，身子往上拔
        p.mode = 'up';
        const q = clamp(1 - actLeft / 1800, 0, 1);
        const up = Math.sin(clamp(q, 0, 1) * Math.PI);        // 抬起来 → 顶住 → 放下来
        tmpGoal.set((side === 'L' ? -1 : 1) * (0.56 + 0.3 * up), 1.58 + 1.34 * up, 0.42 - 0.16 * up);
        p.pos.lerp(tmpGoal, ease(18));
      }
      else if (licking && side === 'R' && since > STRIKE + 110) { p.mode = 'lick'; head.getWorldPosition(tmpGoal); tmpGoal.x += 0.06; tmpGoal.y += -0.5 * P.headSize - Math.sin(t / 140) * 0.06; tmpGoal.z += 0.66 * P.headSize; p.pos.lerp(tmpGoal, ease(12)); }
      else if (grooming && since > STRIKE + 110) {         // 洗脸：一只爪子一下一下地抹，另一只撑着地（两只一起抬就像糊了个白球）
        p.mode = 'groom';
        const cyc = ((t / 1600) + (side === 'L' ? 0 : 0.5)) % 1;
        if (cyc < 0.5) {
          head.getWorldPosition(tmpGoal);
          const w = Math.sin(cyc / 0.5 * Math.PI);         // 从额角往嘴角抹
          tmpGoal.x += (side === 'L' ? -0.42 : 0.42) * P.headSize;
          tmpGoal.y += (0.1 - 0.46 * w) * P.headSize;
          tmpGoal.z += 0.72 * P.headSize;                  // 必须探到脸外面，不然爪子会陷进头里变成一块白斑
          p.pos.lerp(tmpGoal, ease(22));
        } else { tmpGoal.copy(REST[side]); tmpGoal.z -= 0.1; p.pos.lerp(tmpGoal, ease(11)); }
      }
      else if (waving && side === 'R' && since > STRIKE + 110) {   // 抬爪子打招呼
        p.mode = 'wave'; tmpGoal.set(0.52 + Math.sin(t / 95) * 0.14, 1.62, 0.86); p.pos.lerp(tmpGoal, ease(18));
      }
      else if (scratching && side === 'L' && since > STRIKE + 110) {   // 挠耳朵：爪子要抬到耳朵旁边，别停在脸颊里
        p.mode = 'scratch'; head.getWorldPosition(tmpGoal);
        tmpGoal.x += -0.55 * P.headSize; tmpGoal.y += (0.24 + Math.sin(t / 38) * 0.045) * P.headSize;
        tmpGoal.z += 0.55 * P.headSize; p.pos.lerp(tmpGoal, ease(26));
      }
      else if (side === MOUSE_PAW && mouseOn && since > STRIKE + 110) { p.mode = 'mouse'; tmpGoal.copy(mouseGroup.position); tmpGoal.y = 0.3 - (S.mouseDown ? 0.05 : 0); tmpGoal.z += 0.02; p.pos.lerp(tmpGoal, ease(16)); }
      else if (swat && side === (S.pointer && S.pointer.x > 0 ? 'R' : 'L') && since > STRIKE + 110) { p.mode = 'swat'; tmpGoal.set((side === 'L' ? -1 : 1) * 0.62, 1.25, 1.05); p.pos.lerp(tmpGoal, ease(26)); }
      else if (loaf > 0.05 && since > STRIKE + 110) { p.mode = 'rest'; tmpGoal.copy(REST[side]); tmpGoal.z += 0.2 * loaf; p.pos.lerp(tmpGoal, ease(8)); }
      else if (since > STRIKE + 110) { p.mode = hover ? 'up' : 'rest'; const goal = hover ? tmpGoal.copy(UP[side]) : tmpGoal.copy(REST[side]); if (hover) goal.z += fwd * 0.6; else { goal.z -= 0.16 * S.low; goal.x *= 1 - 0.12 * S.low; } p.pos.lerp(goal, ease(hover ? 20 : 9)); if (hover) p.pos.y += Math.sin(t / 240 + (side === 'L' ? 0 : 1.8)) * 0.004; }
    }
    if (VIEW.has('snap')) p.pos.copy(tmpGoal);   // URL 参数：爪子立刻到位，跳过缓动
    shoulderW.copy(SHOULDER[side]); shoulderW.x += sx * shoulderW.y; shoulderW.z += fwd * shoulderW.y; shoulderW.y = shoulderW.y * (1 - fwd * fwd * 0.35) * squat + breath * 0.02 + bounce * 0.06; drawLimb(p, shoulderW);
  }

  renderer.render(scene, camera);
  // labels above the keys that were hit
  tongue.visible = licking && paws.R.mode === 'lick'; if (tongue.visible) { const k = Math.sin(t / 140); tongue.position.y = -0.38 - 0.05 * k; tongue.scale.set(0.06, 0.085 + 0.03 * k, 0.04); }
  mouth.visible = yawn > 0.04; if (mouth.visible) fillPatch(mouth, 0, -0.29 - 0.05 * yawn, 0.03 + 0.085 * yawn, 0.01 + 0.14 * yawn, 0, 0.012);
  zzz.style.display = asleep ? 'block' : 'none';
  { const petOn = !!S.pet || t < S.happyUntil;                       // 摸头的时候飘爱心
    heart.style.display = petOn ? 'block' : 'none';
    if (petOn) { head.getWorldPosition(proj); proj.x += 0.34; proj.y += 0.52; proj.project(camera);
      heart.style.left = ((proj.x + 1) / 2 * w) + 'px'; heart.style.top = ((1 - proj.y) / 2 * h) + 'px';
      heart.style.fontSize = (w * 0.058) + 'px'; } }
  // 发火：身后的红光 + 头顶三团火气 + 耳朵冒热汽
  S.auraFlash = Math.max(0, (S.auraFlash || 0) - dt * 2.0);
  const heat = clamp((fast - 0.25) / 0.6, 0, 1);
  const auraOn = !asleep && heat > 0.01;
  aura.style.display = auraOn ? 'block' : 'none';
  if (auraOn) {
    aura.style.opacity = String(Math.min(1, (0.3 + 0.7 * heat) * (0.86 + 0.14 * Math.sin(t / 85)) + S.auraFlash * 0.7));
    aura.style.transform = 'translate(-50%,-50%) scale(' + (0.88 + 0.2 * heat + 0.3 * S.auraFlash + 0.035 * Math.sin(t / 70)).toFixed(3) + ')';
  }
  head.getWorldPosition(proj);
  const puff = 1 + 0.18 * Math.sin(t / 95) * (0.3 + 0.7 * fast);
  const putMark = (el, dx, dy, size, rot, on) => {
    el.style.display = on ? 'block' : 'none';
    if (!on) return;
    markV.copy(proj); markV.x += dx; markV.y += dy; markV.project(camera);
    el.style.left = ((markV.x + 1) / 2 * w) + 'px'; el.style.top = ((1 - markV.y) / 2 * h) + 'px';
    el.style.fontSize = (w * size * puff) + 'px';
    el.style.opacity = String(clamp((fast - 0.25) / 0.25, 0, 1));
    el.style.transform = 'translate(-50%,-50%) rotate(' + rot.toFixed(1) + 'deg)';
  };
  const hot = !asleep && fast > 0.25;
  putMark(ire, 0.32, 1.06, 0.165, Math.sin(t / 55) * 13 * fast, hot);
  putMark(ireL, -0.78, 0.82, 0.105, 22 + Math.sin(t / 70) * 15, hot && fast > 0.5);
  putMark(ireR, 0.98, 0.88, 0.105, -22 - Math.sin(t / 62) * 15, hot && fast > 0.5);
  const steamOn = !asleep && fast > 0.62;
  steam.style.display = steamOn ? 'block' : 'none';
  if (steamOn) {
    markV.copy(proj); markV.y += 1.22; markV.project(camera);
    steam.style.left = ((markV.x + 1) / 2 * w) + 'px';
    steam.style.top = Math.max(h * 0.04, (1 - markV.y) / 2 * h) + 'px';
    steam.style.fontSize = (w * 0.075) + 'px';
    steam.style.opacity = String(clamp((fast - 0.62) / 0.25, 0, 1));
  }
  if (asleep) { head.getWorldPosition(proj); proj.x += 0.5; proj.y += 0.5; proj.project(camera); zzz.style.left = ((proj.x + 1) / 2 * w) + 'px'; zzz.style.top = ((1 - proj.y) / 2 * h) + 'px'; }
  S.chips = S.chips.filter(c => { const out = c.gone ? (t - c.gone) / 240 : 0; if (out >= 1) { c.el.remove(); return false; }
    proj.set(c.k.x, 0.75, c.k.z).project(camera); c.el.style.left = ((proj.x + 1) / 2 * w) + 'px'; c.el.style.top = ((1 - proj.y) / 2 * h - out * 8) + 'px'; c.el.style.opacity = String(Math.min(1, (t - c.born) / 80) * (1 - out)); return true; });
  raf = requestAnimationFrame(frame);
}
// A coat is named by its id; an unknown id falls back to the first coat.
const coatIndex = id => Math.max(0, COATS.findIndex(c => c.id === id));
setCoat(coatIndex(options.coat)); applyShape();
raf = requestAnimationFrame(frame);

/* ---------- what the app can ask of the cat ---------- */
// A press whose key is not being shown (privacy mode, or a key off the little keyboard) still gets a paw tap, with no key attached.
// The signal names the owner's hand; the keyboard faces the cat, so the owner's left hand is the paw on the right of the picture.
const plainTap = side => { const t = performance.now(), s = side === 'Left' ? 'R' : 'L'; wake(t); strike(s, (s === 'L' ? -1 : 1) * rnd(0.45, 1.0), KB.z0 + rnd(0.35, 0.7), t, null); };
let shownKeys = new Set(), buttonsDown = 0, buttonsAt = 0;
// The system sometimes never reports a key coming back up (on macOS, any key let go while Command is held). A paw therefore
// lets go by itself after a moment instead of staying planted on a key nobody is pressing.
const HOLD_MAX = 1400, downAt = new Map();
const letGo = setInterval(() => { const t = performance.now();
  for (const [code, at] of downAt) if (t - at > HOLD_MAX) { keyUp(code); downAt.delete(code); }
  if (S.mouseDown && buttonsAt && t - buttonsAt > HOLD_MAX) S.mouseDown = false; }, 200);
return {
  coats: COATS.map(c => c.id),
  setInput(keySet, buttonSet) {
    for (const code of shownKeys) if (!keySet.has(code)) { keyUp(code); downAt.delete(code); }
    for (const code of keySet) if (!shownKeys.has(code)) { keyDown(code); downAt.set(code, performance.now()); }
    shownKeys = new Set(keySet);
    const t = performance.now(), n = buttonSet.size;
    if (n !== buttonsDown) {
      wake(t); S.lastMouse = t; S.mouseDown = n > 0; buttonsDown = n; buttonsAt = n > 0 ? t : 0;
      if (n > 0) S.clickRight = buttonSet.has('right');   // 右键：小老鼠往另一边歪
    }
  },
  tap(side) {
    if (!followKeys) { plainTap(side); return; }
    const at = performance.now(); setTimeout(() => { if (!dead && lastStrikeAt < at && !S.down.size && !shownKeys.size) plainTap(side); }, 45);
  },
  setOptions(o) {
    if ('showKeyboard' in o) board.visible = !!o.showKeyboard;
    if ('showMouse' in o) mouseGroup.visible = !!o.showMouse;
    if ('followKeys' in o) { followKeys = !!o.followKeys; if (!followKeys) { [...S.down.keys()].forEach(keyUp); shownKeys = new Set(); downAt.clear(); } }
    if ('leftMouse' in o) setHanded(!!o.leftMouse);
    if ('coat' in o) setCoat(coatIndex(o.coat));
    if ('sleepMinutes' in o && !VIEW.get('sleep')) SLEEP_AFTER = clamp(+o.sleepMinutes || 15, 1, 120) * 60000;
  },
  // The mouse is being moved somewhere on the system. No position is involved; the paw goes to the mouse and nudges it.
  mouseMoved() { const t = performance.now(); wake(t); S.lastMouse = t; S.wigX = clamp(S.wigX + rnd(-0.07, 0.07), -0.16, 0.16); S.wigZ = clamp(S.wigZ + rnd(-0.06, 0.06), -0.12, 0.12); },
  // 让外部（菜单）点名要一个动作；正在打字时不打断它，返回 false
  play(act) {
    const DUR = { roll: 1500, stretch: 1800, chase: 2600, loaf: 4200, yawn: 1900, lick: 3200, tail: 1400,
      lookL: 1700, lookR: 1700, tilt: 1700, ear: 600, groom: 3000, peek: 1400, wave: 1500,
      scratch: 1200, sneeze: 800, hop: 620, lookCam: 1300 };
    if (!(act in DUR)) return false;
    const t = performance.now(); wake(t);
    if (act === 'roll') S.rollDir = Math.random() < 0.5 ? -1 : 1;
    S.act = act; S.actUntil = t + DUR[act]; S.actManual = true;
    // 顶满帧率：空闲 2.5 秒后 cat.js 会隔帧渲染，动作会卡。
    // 这里用 fullUntil，不要用 wokeAt —— wokeAt 会触发「刚被叫醒」的甩头，看起来就只剩摇头。
    S.fullUntil = S.actUntil + 800;
    S.nextAct = Math.max(S.nextAct, S.actUntil + 2500);
    return true;
  },
  anger() { return Math.round(S.anger * 100); },
  act() { return S.act || ''; },
  clear() { [...S.down.keys()].forEach(keyUp); shownKeys = new Set(); downAt.clear(); buttonsDown = 0; buttonsAt = 0; S.mouseDown = false; },
  state() { const t = performance.now(); return sleeping(t) ? 'sleeping' : S.pet || t < S.happyUntil ? 'petting' : t - S.lastKey < 3000 ? 'typing' : mouseGroup.visible && t - S.lastMouse < 2200 ? 'mouse' : 'idle'; },
  fastForwardToSleep() { S.sleepAt = performance.now(); S.lastKey = S.lastMouse = -1e9; },
  destroy() { dead = true; clearInterval(letGo); cancelAnimationFrame(raf); offs.forEach(f => f()); S.chips.forEach(c => c.el.remove()); zzz.remove(); [ire, ireL, ireR, aura, steam, heart].forEach(e => e.remove()); renderer.domElement.remove(); renderer.dispose(); },
};
};
