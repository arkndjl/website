// Process low-poly viewport (layouts/shortcodes/procview.html): a flat-shaded low-poly model drawn into a small canvas,
// dithered to the site palette and scaled up with square pixels. The model follows the open Process group: overview an
// icosahedron, philosophy a cut gem, ARKLOG a 3D bar chart of every test by sport and verdict (data-bars, from
// data/arklog.json), metrics a sphere, models a torus, research a cone, data a stack of disks. No library.
// A box with data-lp-model shows that model instead and follows the attribute when it changes ("your favorites",
// layouts/shortcodes/favorites.html: a heart, and per group a trophy, a star, a book, a record or a screen).
(function () {
  'use strict';
  var box = document.querySelector('[data-lowpoly]');
  if (!box) return;
  var cv = box.querySelector('canvas'), ctx = cv.getContext('2d'), W = cv.width, H = cv.height;
  var label = box.querySelector('[data-lp-label]');
  var css = getComputedStyle(document.documentElement);
  function col(v, d) { var s = (css.getPropertyValue(v) || '').trim(); return /^#[0-9a-f]{6}$/i.test(s) ? s : d; }
  function rgb(h) { return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)]; }
  var BG = rgb(col('--win-dark', '#241a3a'));
  // light ramps, dark to light; a face's shade falls between two steps and is dithered (Bayer 4x4)
  var RAMP = {
    p: ['#241a3a', '#3a2d56', '#57068c', '#b46cff', '#c8c7ff', '#ffffff'].map(rgb),
    t: ['#241a3a', '#1f5c52', '#3fb39a', '#7fffd4', '#d6fff2'].map(rgb),
    m: ['#241a3a', '#57068c', '#8a3fd1', '#b46cff', '#e0c4ff'].map(rgb),
    f: ['#241a3a', '#7a3a63', '#c76a98', '#ff9ec7', '#ffe0ee'].map(rgb),
    w: ['#241a3a', '#3a2d56', '#6d6a9e', '#c8c7ff', '#b9f2ff'].map(rgb)
  };
  var BAYER = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5];

  // ---- meshes: {v: [[x,y,z]], f: [[a,b,c,ramp]]}, faces wound so the normal points out
  function ico() {
    var t = (1 + Math.sqrt(5)) / 2, v = [[-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0], [0, -1, t], [0, 1, t], [0, -1, -t], [0, 1, -t], [t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1]];
    var f = [[0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11], [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8], [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9], [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1]];
    return { v: v.map(function (p) { return p.map(function (c) { return c / 1.9; }); }), f: f.map(function (x, i) { return x.concat(i % 5 ? 'p' : 't'); }) };
  }
  function lathe(prof, n, ramp) {    // prof: [[r, y]] top to bottom; a solid of revolution with n sides
    var v = [], f = [];
    prof.forEach(function (p) { for (var i = 0; i < n; i++) { var a = i / n * Math.PI * 2; v.push([p[0] * Math.cos(a), p[1], p[0] * Math.sin(a)]); } });
    for (var j = 0; j < prof.length - 1; j++) for (var i = 0; i < n; i++) {
      var a = j * n + i, b = j * n + (i + 1) % n, c = (j + 1) * n + i, d = (j + 1) * n + (i + 1) % n, r = typeof ramp === 'function' ? ramp(j, i) : ramp;
      f.push([a, b, d, r]); f.push([a, d, c, r]);
    }
    var top = v.length; v.push([0, prof[0][1], 0]); var bot = v.length; v.push([0, prof[prof.length - 1][1], 0]);
    var L = (prof.length - 1) * n;
    for (var k = 0; k < n; k++) { f.push([top, (k + 1) % n, k, 'w']); f.push([bot, L + k, L + (k + 1) % n, 'w']); }
    return { v: v, f: f };
  }
  function gem() { return lathe([[0.55, 0.62], [1, 0.28], [0, -1.1]], 8, function (j, i) { return j ? (i % 2 ? 'm' : 'p') : 't'; }); }
  function sphere() { var p = []; for (var k = 0; k <= 6; k++) { var a = k / 6 * Math.PI; p.push([Math.sin(a) * 1.05 + 1e-4, Math.cos(a) * 1.05]); } return lathe(p, 10, function (j, i) { return (i + j) % 2 ? 't' : 'p'; }); }
  function cone() { return lathe([[0.02, 1.1], [0.5, 0.2], [1, -0.9]], 7, function (j) { return j ? 'p' : 'm'; }); }
  function disks() {
    var out = { v: [], f: [] };
    [0.5, 0, -0.5].forEach(function (y, k) {
      var m = lathe([[0.8, y + 0.2], [0.8, y - 0.2]], 10, ['t', 'p', 'm'][k]), o = out.v.length;
      m.v.forEach(function (p) { out.v.push(p); }); m.f.forEach(function (x) { out.f.push([x[0] + o, x[1] + o, x[2] + o, x[3]]); });
    });
    return out;
  }
  function torus() {
    var v = [], f = [], N = 12, M = 6, R = 0.82, r = 0.36;
    for (var i = 0; i < N; i++) for (var j = 0; j < M; j++) {
      var a = i / N * Math.PI * 2, b = j / M * Math.PI * 2;
      v.push([(R + r * Math.cos(b)) * Math.cos(a), r * Math.sin(b), (R + r * Math.cos(b)) * Math.sin(a)]);
    }
    for (i = 0; i < N; i++) for (j = 0; j < M; j++) {
      var p = i * M + j, q = ((i + 1) % N) * M + j, s = i * M + (j + 1) % M, u = ((i + 1) % N) * M + (j + 1) % M, rr = i % 3 ? 'p' : 't';
      f.push([p, s, u, rr]); f.push([p, u, q, rr]);
    }
    return { v: v, f: f };
  }
  function box3(x0, x1, y0, y1, z0, z1, rr, out) {
    var o = out.v.length;
    [[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0], [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]].forEach(function (p) { out.v.push(p); });
    [[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4], [3, 7, 6], [3, 6, 2], [0, 4, 7], [0, 7, 3], [1, 2, 6], [1, 6, 5]]
      .forEach(function (x) { out.f.push([x[0] + o, x[1] + o, x[2] + o, rr]); });
  }
  function bars() {   // every test by sport (x) and verdict (z): shipped, part shipped, failed
    var d = []; try { d = JSON.parse(box.getAttribute('data-bars') || '[]'); } catch (e) {}
    var out = { v: [], f: [] }, n = d.length || 1, mx = 1;
    d.forEach(function (r) { mx = Math.max(mx, r.v[0], r.v[1], r.v[2]); });
    box3(-1.25, 1.25, -1.02, -0.96, -0.55, 0.55, 'w', out);
    d.forEach(function (r, i) {
      var x = -1.15 + i * 2.3 / n, w = 2.3 / n * 0.7;
      ['t', 'm', 'f'].forEach(function (rr, k) {
        var h = r.v[k] / mx * 1.7, z = -0.45 + k * 0.32;
        if (h > 0.01) box3(x, x + w, -0.96, -0.96 + h, z, z + 0.24, rr, out);
      });
    });
    return out;
  }
  function pillow(pts, ramp, rim) {   // a flat outline (star-shaped about 0,0) made solid: a raised centre each side, a rim
    var v = [[0, 0, 0.42], [0, 0, -0.42]], f = [], n = pts.length, d = rim || 0.16;
    pts.forEach(function (p) { v.push([p[0], p[1], d]); v.push([p[0], p[1], -d]); });
    for (var i = 0; i < n; i++) {
      var a = 2 + i * 2, b = 2 + ((i + 1) % n) * 2, r = typeof ramp === 'function' ? ramp(i) : ramp;
      f.push([0, a, b, r]); f.push([1, b + 1, a + 1, r]); f.push([a, a + 1, b + 1, 'w']); f.push([a, b + 1, b, 'w']);
    }
    return { v: v, f: f };
  }
  function heart() {
    var p = [];
    for (var i = 0; i < 28; i++) {
      var t = i / 28 * Math.PI * 2, x = 16 * Math.pow(Math.sin(t), 3), y = 13 * Math.cos(t) - 5 * Math.cos(2 * t) - 2 * Math.cos(3 * t) - Math.cos(4 * t);
      p.push([x / 15, (y + 2) / 15]);
    }
    return pillow(p, function (i) { return i % 2 ? 'w' : 'p'; });
  }
  function star() {
    var p = [];
    for (var i = 0; i < 10; i++) { var a = Math.PI / 2 + i * Math.PI / 5, r = i % 2 ? 0.46 : 1.12; p.push([r * Math.cos(a), r * Math.sin(a) - 0.05]); }
    return pillow(p, function (i) { return i % 2 ? 't' : 'w'; }, 0.12);
  }
  function trophy() {
    var m = lathe([[0.95, 1.0], [0.85, 0.55], [0.5, 0.1], [0.14, -0.15], [0.14, -0.55], [0.6, -0.7], [0.6, -0.95]], 8,
      function (j, i) { return j < 3 ? (i % 2 ? 't' : 'w') : 'p'; });
    return m;
  }
  function record() {
    var out = lathe([[1.15, 0.07], [1.15, -0.07]], 14, function (j, i) { return i % 3 ? 'p' : 'm'; });
    var lab = lathe([[0.42, 0.09], [0.42, 0.075]], 10, 't'), o = out.v.length;
    lab.v.forEach(function (p) { out.v.push(p); }); lab.f.forEach(function (x) { out.f.push([x[0] + o, x[1] + o, x[2] + o, 't']); });
    out.v = out.v.map(function (p) { return [p[0], p[2], p[1]]; });   // stand it up, face to the viewer
    return out;
  }
  function screen() {
    var out = { v: [], f: [] };
    box3(-1.2, 1.2, -0.65, 0.85, -0.45, 0.45, 'p', out);
    box3(-1.02, 1.02, -0.5, 0.7, 0.45, 0.5, 't', out);
    box3(-0.5, 0.5, -1.0, -0.65, -0.3, 0.3, 'm', out);
    return out;
  }
  function book() {
    var out = { v: [], f: [] };
    box3(-0.95, 0.95, -1.15, 1.15, -0.3, 0.3, 'w', out);
    box3(-1.0, 1.0, -1.2, 1.2, 0.3, 0.38, 'p', out);
    box3(-1.0, 1.0, -1.2, 1.2, -0.38, -0.3, 'p', out);
    box3(-1.0, -0.92, -1.2, 1.2, -0.38, 0.38, 'm', out);
    return out;
  }
  var MODELS = { favorites: heart, teams: trophy, players: star, articles: book, songs: record, videos: screen, overview: ico, philosophy: gem, arklog: bars, metrics: sphere, models: torus, research: cone, data: disks };
  var cache = {};
  function model(k) { k = MODELS[k] ? k : 'overview'; return cache[k] || (cache[k] = MODELS[k]()); }

  // ---- raster: painter's order, flat shade, ordered dither between two ramp steps
  var img = ctx.createImageData(W, H), buf = img.data;
  var LIGHT = (function () { var l = [-0.5, 0.75, 0.6], n = Math.hypot(l[0], l[1], l[2]); return l.map(function (c) { return c / n; }); })();
  function tri(a, b, c, ramp, shade) {
    var minx = Math.max(0, Math.floor(Math.min(a[0], b[0], c[0]))), maxx = Math.min(W - 1, Math.ceil(Math.max(a[0], b[0], c[0])));
    var miny = Math.max(0, Math.floor(Math.min(a[1], b[1], c[1]))), maxy = Math.min(H - 1, Math.ceil(Math.max(a[1], b[1], c[1])));
    var ar = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
    if (Math.abs(ar) < 1e-6) return;
    var s = shade * (ramp.length - 1), lo = Math.floor(s), fr = s - lo, hi = Math.min(ramp.length - 1, lo + 1);
    for (var y = miny; y <= maxy; y++) for (var x = minx; x <= maxx; x++) {
      var px = x + 0.5, py = y + 0.5;
      var w0 = (b[0] - a[0]) * (py - a[1]) - (b[1] - a[1]) * (px - a[0]);
      var w1 = (c[0] - b[0]) * (py - b[1]) - (c[1] - b[1]) * (px - b[0]);
      var w2 = (a[0] - c[0]) * (py - c[1]) - (a[1] - c[1]) * (px - c[0]);
      if ((w0 >= 0 && w1 >= 0 && w2 >= 0) || (w0 <= 0 && w1 <= 0 && w2 <= 0)) {
        var k = fr * 16 > BAYER[(y & 3) * 4 + (x & 3)] ? hi : lo, p = ramp[k], o = (y * W + x) * 4;
        buf[o] = p[0]; buf[o + 1] = p[1]; buf[o + 2] = p[2]; buf[o + 3] = 255;
      }
    }
  }
  function draw(m, ay, ax) {
    for (var i = 0; i < buf.length; i += 4) {
      var y = (i / 4 / W) | 0, g = y % 3 === 0 ? 6 : 0;          // scanlines
      buf[i] = BG[0] + g; buf[i + 1] = BG[1] + g; buf[i + 2] = BG[2] + g; buf[i + 3] = 255;
    }
    var cy = Math.cos(ay), sy = Math.sin(ay), cx = Math.cos(ax), sx = Math.sin(ax), S = Math.min(W, H) * 0.36;
    var P = m.v.map(function (p) {
      var x = p[0] * cy + p[2] * sy, z = -p[0] * sy + p[2] * cy, y = p[1] * cx - z * sx; z = p[1] * sx + z * cx;
      var k = 3.4 / (3.4 + z);
      return [W / 2 + x * S * k, H / 2 - y * S * k, z, x, y];
    });
    var F = m.f.map(function (f) {
      var a = P[f[0]], b = P[f[1]], c = P[f[2]];
      var u = [b[3] - a[3], b[4] - a[4], b[2] - a[2]], v = [c[3] - a[3], c[4] - a[4], c[2] - a[2]];
      var n = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]], l = Math.hypot(n[0], n[1], n[2]) || 1;
      return { f: f, z: (a[2] + b[2] + c[2]) / 3, n: [n[0] / l, n[1] / l, n[2] / l] };
    }).map(function (t) { if (t.n[2] > 0) t.n = [-t.n[0], -t.n[1], -t.n[2]]; return t; })   // both sides lit; painter's order hides the back
      .sort(function (p, q) { return q.z - p.z; });
    F.forEach(function (t) {
      var d = -(t.n[0] * LIGHT[0] + t.n[1] * LIGHT[1] - t.n[2] * LIGHT[2]);
      var sh = Math.max(0.12, Math.min(0.98, 0.5 + 0.48 * -d));
      tri(P[t.f[0]], P[t.f[1]], P[t.f[2]], RAMP[t.f[3]] || RAMP.p, sh);
    });
    ctx.putImageData(img, 0, 0);
  }

  // ---- which group is open: the selected tab's group in the side strip
  var cur = box.getAttribute('data-lp-model') || 'overview';
  function group() {
    var fixed = box.getAttribute('data-lp-model');
    if (fixed) { if (fixed !== cur) { cur = fixed; if (label) label.textContent = fixed; } return; }
    var sel = document.querySelector('.libtabs [role="tab"][aria-selected="true"]');
    var g = sel && sel.closest('[data-wingroup]'), name = g ? g.getAttribute('data-wingroup') : '';
    name = (name || 'overview').trim().toLowerCase();
    if (name !== cur) { cur = name; if (label) label.textContent = name; }
  }
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var t0 = performance.now(), last = 0, seen = true;
  if ('IntersectionObserver' in window) new IntersectionObserver(function (e) { seen = e[0].isIntersecting; }).observe(cv);
  function frame(t) {
    if (seen && t - last > 83) {        // 12 frames a second, like a sprite
      last = t; group();
      var a = reduce ? 0.6 : (t - t0) / 1000 * 0.7;
      if (cur === 'arklog') a = 0.45 * Math.sin(a * 0.8);    // the bars sway in front so every verdict row shows
      draw(model(cur), a, cur === 'arklog' ? 0.32 : 0.38 + 0.12 * Math.sin(a * 0.6));
    }
    if (!reduce) requestAnimationFrame(frame); else setTimeout(function () { requestAnimationFrame(frame); }, 400);
  }
  requestAnimationFrame(frame);
})();
