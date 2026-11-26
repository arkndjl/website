// Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
(function () {
  if (window.__arkGfx) return; window.__arkGfx = true;
  var W, H, PAD = 60;
  var C = { bg: '#4a3b6b', face: '#4a3b6b', well: '#3a2d56', light: '#c8c7ff', dark: '#241a3a', title: '#57068c', teal: '#7fffd4', lilac: '#c8c7ff', white: '#ffffff', down: '#ff9ec7' };
  var FONT = '"MS PGothic Pixel", "MS PGothic", monospace';
  // college WAR a season per AV (scripts/cfb_av.mjs): team-builder values are AV at FV, drawn as WAR
  var WARK = {{ with site.Data.cfb_war_backtest }}{{ .constants.cwarPerAv }}{{ else }}0.0953{{ end }};
  // the sport's short link (static/_redirects): /cfb -> /arkboard/college-football/, the hash carried through
  var SITE = 'arkndjl.net/' + ([[/^\/1nt/i, '1nt'], [/^\/laursen_111/i, 'laursen_111'], [/college-football/, 'cfb'], [/college-basketball/, 'cbb'], [/arkboard\/nfl/, 'nfl'], [/arkboard\/nba/, 'nba'],
    [/arkboard\/nhl/, 'nhl'], [/hockey-prospects/, 'hockey'], [/soccer-prospects/, 'u22'], [/arkboard\/soccer/, 'soccer'], [/arkboard\/baseball/, 'baseball'], [/arkboard\/counter-strike/, 'cs2'],
    [/arkboard\/predictions/, 'picks'], [/arkboard\/arklist/, 'arklist'], [/arkboard\/process/, 'process'], [/./, 'arkboard']].filter(function (x) { return x[0].test(location.pathname); })[0][1]);
  // the short link a graphic prints: the sport's short path plus the tab it came from (#<tab>), or a player (#<board>:p=<key>)
  function tabLink(win) { var t = win && win.closest('[data-tab]'); t = t && t.getAttribute('data-tab'); return SITE + (t && !/(1nt|laursen_111)$/.test(SITE) ? '#' + String(t).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') : ''); }
  function txt(el) { return (el && el.textContent || '').replace(/\s+/g, ' ').trim(); }
  // a photo from another site (ESPN, Wikimedia) loads with CORS so the canvas can still be saved
  // On3 recruit photos come through the site's own /api/photo (worker/site.js): On3's CDN sends CORS headers unreliably
  function loadPhoto(src) {
    if (src) src = src.replace(/^https:\/\/on3static\.com\/(?=cdn-cgi\/image\/)/, '/api/photo/');
    return new Promise(function (res) { if (!src) return res(null); var i = new Image(); i.crossOrigin = 'anonymous'; i.onload = function () { res(i); }; i.onerror = function () { res(null); }; i.src = src; });
  }
  // an on-theme picture frame: raised bevel, a dark inner line, the photo cover-cropped from the top
  function photoFrame(g, img, x, y, w, h) {
    g.fillStyle = C.face; g.fillRect(x, y, w, h); bevel(g, x, y, w, h, true, 6);
    g.fillStyle = C.dark; g.fillRect(x + 12, y + 12, w - 24, h - 24);
    g.fillStyle = C.well; g.fillRect(x + 15, y + 15, w - 30, h - 30);
    if (img) {
      var iw = w - 30, ih = h - 30, s = Math.max(iw / img.width, ih / img.height), sw = iw / s, sh = ih / s;
      g.drawImage(img, (img.width - sw) / 2, 0, sw, sh, x + 15, y + 15, iw, ih);
    } else {   // the site's face.svg silhouette, drawn as its 16x16 pixel grid
      var u = Math.floor(Math.min(w - 30, h - 30) / 16), ox = x + (w - 16 * u) / 2, oy = y + h - 15 - 16 * u;
      g.fillStyle = 'rgba(154,140,196,0.55)';
      [[3, 6, 9], [4, 5, 10], [5, 5, 10], [6, 5, 10], [7, 5, 10], [8, 6, 9], [9, 7, 8], [10, 6, 9], [11, 4, 11], [12, 3, 12], [13, 3, 12], [14, 3, 12], [15, 3, 12]]
        .forEach(function (r) { g.fillRect(ox + r[1] * u, oy + r[0] * u, (r[2] - r[1] + 1) * u, u); });
    }
    // pixel corner studs
    g.fillStyle = C.teal; [[x + 4, y + 4], [x + w - 10, y + 4], [x + 4, y + h - 10], [x + w - 10, y + h - 10]].forEach(function (p) { g.fillRect(p[0], p[1], 6, 6); });
  }
  // team logos are drawn smooth at full resolution, as served; the rest of the card stays pixel-sharp
  function drawLogo(g, img, x, y, w, h) {
    var sm = g.imageSmoothingEnabled;
    g.imageSmoothingEnabled = true; g.imageSmoothingQuality = 'high';
    g.drawImage(img, x, y, w, h);
    g.imageSmoothingEnabled = sm;
  }
  // an image from another site loads with CORS, so a hotlinked logo can't taint the canvas and block the save (no CORS: no logo)
  function loadImg(src) {
    return new Promise(function (res) { if (!src) return res(null); var i = new Image(); if (new URL(src, location.href).origin !== location.origin) i.crossOrigin = 'anonymous'; i.onload = function () { res(i); }; i.onerror = function () { res(null); }; i.src = src; });
  }
  function capHead(h) { return /^x[A-Z]/.test(h) || /^NHLe$/.test(h) ? h : h.toUpperCase(); }   // xNIL keeps its x, NHLe its e
  function bevel(g, x, y, w, h, raised, t) {
    t = t || 3;
    g.fillStyle = raised ? C.light : C.dark; g.fillRect(x, y, w, t); g.fillRect(x, y, t, h);
    g.fillStyle = raised ? C.dark : C.light; g.fillRect(x, y + h - t, w, t); g.fillRect(x + w - t, y, t, h);
  }

  // mock draft trade tags, drawn after the team: a pick already traded is a solid lilac tag ("via GB"), a
  // projected trade a dashed teal outline ("⇅ NYJ"). Tag text is a step below the row's text.
  function tagSz(sz) { return sz >= 48 ? 32 : 24; }
  function tagsW(c, sz) {
    if (!c.tags) return 0; var f = g0font(sz), w = 0;
    c.tags.forEach(function (t) { w += 12 + f.measure(t.t) + 16; }); return w;
  }
  var mctx = document.createElement('canvas').getContext('2d');
  function g0font(sz) { mctx.font = tagSz(sz) + 'px ' + FONT; return { measure: function (t) { return mctx.measureText(t).width; } }; }
  function tagBox(g, t, x, cy, ts) {
    var w = g.measureText(t.t).width + 16, h = Math.round(ts * 1.25), y = Math.round(cy - h / 2);
    if (t.real || t.kind === 'value' || t.kind === 'lilac') {        // solid: lilac (traded pick, NBA contract) or teal (value, two-way)
      g.fillStyle = C.title; g.fillRect(x + 3, y + 3, w, h);        // pixel drop shadow
      g.fillStyle = t.real || t.kind === 'lilac' ? C.lilac : C.teal; g.fillRect(x, y, w, h);
      g.fillStyle = C.dark; g.fillText(t.t, x + 8, cy);
    } else if (t.kind === 'reach') {                                 // pink outline on dark, as on the site
      g.fillStyle = C.title; g.fillRect(x + 3, y + 3, w, h);
      g.fillStyle = C.dark; g.fillRect(x, y, w, h);
      g.fillStyle = C.down; g.fillRect(x, y, w, 3); g.fillRect(x, y + h - 3, w, 3); g.fillRect(x, y, 3, h); g.fillRect(x + w - 3, y, 3, h);
      g.fillText(t.t, x + 8, cy);
    } else {
      g.fillStyle = C.teal;                                          // dashed outline, 3 px pixels
      for (var dx = 0; dx < w; dx += 9) { g.fillRect(x + dx, y, Math.min(5, w - dx), 3); g.fillRect(x + dx, y + h - 3, Math.min(5, w - dx), 3); }
      for (var dy = 0; dy < h; dy += 9) { g.fillRect(x, y + dy, 3, Math.min(5, h - dy)); g.fillRect(x + w - 3, y + dy, 3, Math.min(5, h - dy)); }
      g.fillText(t.t, x + 8, cy);
    }
    return w;
  }
  function drawTags(g, tags, x, cy, sz) {
    var f = g.font; g.font = tagSz(sz) + 'px ' + FONT; x += 12;
    tags.forEach(function (t) { x += tagBox(g, t, x, cy, tagSz(sz)) + 16; });
    g.font = f;
  }
  // the key, right-aligned in the subtitle strip; returns its width
  function legend(g, right, cy, real, proj) {
    g.font = '32px ' + FONT;
    var items = [], x;
    if (real) items.push([{ t: 'via', real: true }, 'real trade']);
    if (proj) items.push([{ t: '⇅', real: false }, 'projected']);
    var w = items.reduce(function (a, it) { return a + g.measureText(it[0].t).width + 16 + 12 + g.measureText(it[1]).width + 28; }, 0);
    x = right - w;
    items.forEach(function (it) {
      x += tagBox(g, it[0], x, cy, 32) + 12;
      g.fillStyle = C.lilac; g.fillText(it[1], x, cy); x += g.measureText(it[1]).width + 28;
    });
    return w + 24;
  }

  // ---- table graphics -----------------------------------------------------------------------------------
  // What's on screen (filters and sort included), as many rows as the "rows" picker next to the GFX button
  // asks for (default 30). Layout by count: up to 13 rows one column at 16:9; 14-34 one column on a 4:5
  // portrait (34: a full mock round); 35-60 two columns on the portrait. Rows fill the canvas; text never drops below 24 px, so
  // the least important columns (rightmost) drop before the text shrinks. A subtitle says what's shown:
  // how many, the filters in force and the sort.
  // The mock draft adds a round picker (a whole round, whatever the filters) and a trade list under the table.
  // A league table (one row per team: NHL/NFL 32, NBA 30, a soccer league 18-20) starts at "all", so every team is on it.
  var ROWS_DEFAULT = 30, ROWS_MAX = 60, ROWS_OPTS = [10, 15, 20, 25, 30, 40, 50, 60];
  function rowsWanted(win, btn) {
    var sel = btn.parentNode && btn.parentNode.querySelector('.gfx-rows select');
    if (btn.hasAttribute('data-gfx-all')) return Infinity;   // every row (the week's picks)
    if (sel && sel.value === 'all') return ROWS_MAX;
    return +(sel && sel.value) || ROWS_DEFAULT;
  }
  // name, position, class, team, FV and the sorted column stay on every graphic: when columns have to go for width, these go last
  var NAME_COL = /^(player|recruit|goalie|coach|qb|team|club|matchup|match|game|bet|lineup|unit)$/i, POS_COL = /^(pos|position)$/i, CLASS_COL = /^(class|yr|year)$/i, TEAM_COL = /^(team|school|club|org)$/i, FV_COL = /^x?fv$/i;
  function isTeamTable(heads) {
    var key = heads.filter(function (h) { return !/^(rk|#|spot|lg)$/i.test(h.replace(/!$/, '')); })[0] || '';
    return /^(team|club)$/i.test(key);
  }
  // rookie and prospect boards (college, prospects pages, mocks, draft, rookie and recruit tabs): age sits beside the
  // name and position and is never dropped
  var AGE_COL = /^age$/i;
  function isYouth(win) {
    if (win.closest('[data-rookies], .cfbm, [data-cfb], [data-cbb], .rookies') || win.matches('[data-rookies], .cfbm, [data-cfb], [data-cbb], .rookies')) return true;
    if (/college-|prospects/.test(location.pathname)) return true;
    var t = txt(win.querySelector('.win__title-text')), tab = win.getAttribute('data-tab') || '';
    return /rookie|fresh|first-year|mock|draft|prospect|recruit|redshirt|young|under-2\d|class/i.test(t + ' ' + tab);
  }
  function filterSummary(win) {
    var bits = [], bar = win.querySelector('form');
    if (bar) {
      var chip = bar.querySelector('.cfb__chip.is-on[data-pos]'); if (chip && chip.dataset.pos) bits.push(chip.dataset.pos);
      // a view chip that changes what the rows are (lineups: 5-man, trios, pairs) names itself on the subtitle
      [].slice.call(bar.querySelectorAll('.cfb__chip.is-on[data-gfx-chip]')).forEach(function (c) { bits.push(c.getAttribute('data-gfx-chip') || txt(c)); });
      [].slice.call(bar.elements).forEach(function (el) {
        if (!el.name || el.type === 'button' || el.type === 'reset') return;
        if (el.type === 'checkbox') { if (el.checked) { var l = el.closest('label'); bits.push(l ? txt(l) : el.name); } return; }
        if (!el.value || el.hasAttribute('data-gfx-season')) return;   // a past season goes in the title, not the subtitle
        var lab = el.closest('label'), name = lab ? txt(lab.querySelector('span')).toLowerCase() : el.name;
        if (el.type === 'search') bits.push('"' + el.value + '"');
        else if (el.tagName === 'SELECT') { var o = el.options[el.selectedIndex]; bits.push((/≤|≥/.test(name) ? name + ' ' : '') + (o ? o.text : el.value)); }
      });
    }
    var th = win.querySelector('th[aria-sort]'), sort = th ? txt(th).toLowerCase() : '';
    var tf = win.querySelector('th.is-sorted, th[data-sorted]'); if (!th && tf) sort = txt(tf).toLowerCase();
    return { filters: bits, sort: sort && sort !== 'rk' ? 'sorted by ' + sort + (th && th.getAttribute('aria-sort') === 'ascending' ? ' ↑' : '') : '' };
  }

  // index (in hcells) of the column the rows are ordered by, or -1 for the board's own order. A sort on RK means the board's
  // order, unless a "rank by" view drives it: then the view's column, marked is-key in the rows (VORX, XPM, WAR ...).
  function sortedCol(table, hcells) {
    var th = hcells.find(function (h) { return h.hasAttribute('aria-sort'); }) || hcells.find(function (h) { return h.matches('.is-sorted, [data-sorted]'); });
    var i = th ? hcells.indexOf(th) : -1;
    if (i >= 0 && !/^(rk|#|spot|pick)$/i.test(txt(th))) return i;
    var r = [].slice.call(table.tBodies[0].rows).find(function (r) { return !r.classList.contains('cfb__detail') && r.cells.length > 2; });
    var kc = r && [].slice.call(r.cells).findIndex(function (c) { return c.classList.contains('is-key'); });
    return kc >= 0 && r.cells.length === hcells.length ? kc : -1;
  }

  // index (in hcells) of the weekly move column, or -1: a ± / Δ header whose cells are weekly move cells (cfb__wk) or whose
  // hover says it counts from last week / the last post / a date (not a standard error, a pick delta or an outcome gap)
  function weekCol(table, hcells) {
    var r = [].slice.call(table.tBodies[0].rows).find(function (r) { return !r.classList.contains('cfb__detail') && r.cells.length === hcells.length; });
    return hcells.findIndex(function (h, i) {
      if (h.hidden || !/^[±Δ]$/.test(txt(h))) return false;
      if (r && r.cells[i] && r.cells[i].classList.contains('cfb__wk')) return true;
      return /since|last (week|7 days)|over the last week/i.test(h.getAttribute('title') || '');
    });
  }

  async function build(win, btn) {
    var table = win.querySelector('table'); if (!table) return null;
    var hcells = [].slice.call(table.tHead.rows[0].cells), vis = hcells.filter(function (h) { return !h.hidden; });
    // a board that renders only its shown columns (the basketball board swaps xBPM/Age for Outcome on past seasons): headers by what's shown
    var row0 = [].slice.call(table.tBodies[0].rows).find(function (r) { return !r.classList.contains('cfb__detail') && r.cells.length > 2; });
    if (row0 && vis.length < hcells.length && row0.cells.length === vis.length) hcells = vis;
    var heads = hcells.map(txt);
    // a column name ending in "!" draws only its logo; "name=Label" draws that column under another header
    var iconOnly = {}, relabel = {};
    var want = (win.getAttribute('data-gfx-cols') || '').split(',').map(function (s) { s = s.trim(); var e = s.indexOf('=');
                 if (e > 0) { relabel[s.slice(0, e).trim().toLowerCase()] = s.slice(e + 1).trim(); s = s.slice(0, e).trim(); } return s.toLowerCase(); }).filter(Boolean);
    heads = heads.map(function (h) { return relabel[h.toLowerCase()] || h; });
    want = want.map(function (n) { return (relabel[n.replace(/!$/, '')] || n.replace(/!$/, '')).toLowerCase() + (/!$/.test(n) ? '!' : ''); });
    var idx = want.length ? want.map(function (n) { var io = /!$/.test(n); n = n.replace(/!$/, '');
                              var i = heads.findIndex(function (h) { return h.toLowerCase() === n; }); if (io) iconOnly[i] = 1; return i; }).filter(function (i) { return i >= 0; })
                          : heads.slice(0, 6).map(function (_, i) { return i; });
    // the board's position, class, team and FV columns join the graphic beside the name when the preset leaves them out
    var nameAt = idx.findIndex(function (i) { return NAME_COL.test(heads[i]); });
    if (nameAt >= 0 && !/^(team|club|matchup|match|game|bet)$/i.test(heads[idx[nameAt]])) {
      [POS_COL, CLASS_COL, TEAM_COL, FV_COL].forEach(function (re) {
        if (idx.some(function (i) { return re.test(heads[i]); })) return;
        var j = heads.findIndex(function (h) { return re.test(h); }); if (j < 0) return;
        // only a column the board fills in: at least half of the first rows carry a value
        var body = [].slice.call(table.tBodies[0].rows).filter(function (r) { return r.cells.length > j && !r.classList.contains('cfb__detail'); }).slice(0, 30);
        var filled = body.filter(function (r) { return /[\w\d]/.test(txt(r.cells[j]).replace(/^[-–—]$/, '')); }).length;
        if (body.length && filled * 2 >= body.length) idx.splice(++nameAt, 0, j);
      });
    }
    var youth = isYouth(win), ageI = youth ? heads.findIndex(function (h) { return AGE_COL.test(h); }) : -1;
    if (ageI >= 0 && nameAt >= 0) {
      var ageBody = [].slice.call(table.tBodies[0].rows).filter(function (r) { return r.cells.length > ageI && !r.classList.contains('cfb__detail'); }).slice(0, 30);
      var ageFilled = ageBody.filter(function (r) { return /\d/.test(txt(r.cells[ageI])); }).length;
      if (ageBody.length && ageFilled * 2 >= ageBody.length) {
        var ak = idx.indexOf(ageI); if (ak >= 0) { idx.splice(ak, 1); if (ak < nameAt) nameAt--; }
        var aAt = nameAt + 1;
        while (aAt < idx.length && (FV_COL.test(heads[idx[aAt]]) || POS_COL.test(heads[idx[aAt]]))) aAt++;
        idx.splice(aAt, 0, ageI);
      } else ageI = -1;
    } else ageI = -1;
    // the column the table is sorted by (a header click, or the "rank by" view when the order is RK) is on every graphic and
    // never auto-dropped, like FV: added after the name's columns when the preset leaves it out
    var sortI = sortedCol(table, hcells), sortDir = sortI >= 0 && hcells[sortI] ? hcells[sortI].getAttribute('aria-sort') : null;
    if (sortI >= 0 && idx.indexOf(sortI) < 0) {
      var fvAt = idx.findIndex(function (i) { return FV_COL.test(heads[i]); });
      var at0 = fvAt >= 0 ? fvAt + 1 : nameAt >= 0 ? nameAt + 1 : idx.length;
      while (at0 < idx.length && ([POS_COL, CLASS_COL, TEAM_COL, FV_COL].some(function (re) { return re.test(heads[idx[at0]]); }) || idx[at0] === ageI)) at0++;
      idx.splice(at0, 0, sortI);
    }
    // the weekly move column (± rank change / Δ FV change since the last post day, scripts/board_moves.py; ± on the ARK
    // Rankings) rides beside the sorted column on every graphic and is never auto-dropped
    var wkI = weekCol(table, hcells);
    if (wkI >= 0 && idx.indexOf(wkI) < 0) {
      var wAt = sortI >= 0 ? idx.indexOf(sortI) + 1 : nameAt >= 0 ? nameAt + 1 : idx.length;
      while (sortI < 0 && wAt < idx.length && ([POS_COL, CLASS_COL, TEAM_COL, FV_COL].some(function (re) { return re.test(heads[idx[wAt]]); }) || idx[wAt] === ageI)) wAt++;
      idx.splice(wAt, 0, wkI);
    }
    var teamK = idx.findIndex(function (i) { return TEAM_COL.test(heads[i]); });
    var all =[].slice.call(table.tBodies[0].rows).filter(function (r) { return !r.hidden && getComputedStyle(r).display !== 'none' && !r.classList.contains('cfb__detail') && r.cells.length > 2; });
    var rows = all.slice(0, rowsWanted(win, btn));
    // the round picker (tables with an Rd column, e.g. the mock draft): every pick of that round, whatever the filters
    var rdPick = btn.parentNode && btn.parentNode.querySelector('.gfx-round select'), rdWant = rdPick && rdPick.value;
    if (rdWant) {
      var rdC = heads.findIndex(function (h) { return h.toLowerCase() === 'rd'; });
      rows = [].slice.call(table.tBodies[0].rows).filter(function (r) { return !r.classList.contains('cfb__detail') && r.cells.length > 2 && txt(r.cells[rdC]) === rdWant; })
        .sort(function (a, b) { return parseFloat(txt(a.cells[0])) - parseFloat(txt(b.cells[0])); });
    }
    // trade list under the table (mock draft): one line per trade among the rows shown, real first, by pick
    var deals = [], seenDeal = {};
    rows.forEach(function (r) { [].slice.call(r.querySelectorAll('.cfbm__trade[data-gd]')).forEach(function (e) {
      var k = e.getAttribute('data-gk'), t = e.getAttribute('data-gd'); if (!t || seenDeal[k]) return; seenDeal[k] = 1;
      deals.push({ real: e.classList.contains('is-real'), t: t, at: parseInt(k.slice(1), 10) });
    }); });
    deals.sort(function (a, b) { return (b.real - a.real) || a.at - b.at; });
    if (!rows.length) return null;
    var data = await Promise.all(rows.map(async function (r) {
      return Promise.all(idx.map(async function (i) {
        var c = r.cells[i], chip = c && c.querySelector('.fv-chip'), img = c && c.querySelector('img.cfb__logo:not(.gfx-off), img:not(.pxframe img):not(.flag):not(.gfx-off)');
        // text only: the board's marks (ARKLIST star, riser arrow, injury and RB role tags, photos) stay off
        var cc = c && c.cloneNode(true); if (cc) cc.querySelectorAll('.gfx-off, .cfb__star, .cfb__carried, .cfb__warin, .cfb__riser, .cfb__injchip, .injtag, .cfb__rbrole, .cfb__medals, .cfb__upchip, .cfb__movechip, .cfb__multichip, .cfb__valuechip, .cfb__reachchip, .cfb__divtag, .pxframe, .cfbst__more, .nflwar__col, .nflwar__tm, .nflwar__rook, .esea-flag, .nbaxpm__tm, .nbaxpm__od, .brk__meta').forEach(function (e) { e.remove(); });
        var cell = { t: txt(cc).replace(/[▾▴▸★↗]/g, '').trim() };
        // ARK stars (recruit tabs): pixel stars, 5-star+ in lilac with a plus
        var ark = c && c.querySelector('.cfbrc__ark[data-n]');
        if (ark) { var an = +ark.getAttribute('data-n'); cell.t = new Array(Math.floor(Math.min(an, 5)) + 1).join('✦') + (an % 1 ? '✧' : '') + (an > 5 ? '+' : ''); cell.color = C.teal; cell.glow = an > 5; }
        // mock draft trade tags: a pick already traded (solid) or a projected trade (dashed, ⇅)
        var tags = c ? [].slice.call(c.querySelectorAll('.cfbm__trade[data-g], .nbagl__ct[data-g]')) : [];
        // G League contract tags: two-way teal, NBA contract lilac (solid, no legend)
        if (tags.length) cell.tags = tags.map(function (e) { var g = e.getAttribute('data-g'); return e.classList.contains('nbagl__ct') ? { t: g, kind: g === 'TW' ? 'value' : 'lilac' } : { t: g, real: e.classList.contains('is-real') }; });
        if (img) cell.t = cell.t.replace(/ State$/, ' St.').replace(/^Mississippi /, 'Miss. ');
        if (iconOnly[i] && img) cell.t = '';
        if (chip) { var cs = getComputedStyle(chip); cell.chip = cs.backgroundColor; cell.ink = cs.color; }
        if (img) cell.img = await loadImg(img.currentSrc || img.src);
        // nationality flag beside the name: a pixel sprite (hockey, CS, tennis) or the small flag image (soccer)
        var fl = c && c.querySelector('svg.esea-flag'), fi = c && c.querySelector('img.flag');
        if (fl) cell.flag = await flagImg((fl.getAttribute('aria-label') || '').toLowerCase());
        else if (fi) cell.flag = await loadImg(fi.currentSrc || fi.src);
        var col = c && (c.querySelector('.cfb__up, .cfb__down') || (c.classList.contains('cfb__up') || c.classList.contains('cfb__down') ? c : null));
        if (col && !ark) cell.color = col.classList.contains('cfb__up') ? C.teal : C.down;
        return cell;
      })).then(async function (cells) {
        // every row carries its team logo: a logo elsewhere in the row, or the window's logo path for the team's code
        if (cells.some(function (c) { return c.img; })) return cells;
        var lg = [].slice.call(r.querySelectorAll('img.cfb__logo')).find(function (e) { return !e.closest('.pxframe'); }), src = lg && (lg.currentSrc || lg.src);
        var tpl = win.getAttribute('data-gfx-logo'), tc = teamK >= 0 ? cells[teamK] : null;
        var sp = r.querySelector('.nbaxpm__tm, .nflwar__tm'), code = tc && tc.t ? tc.t : sp ? txt(sp).split(/[\s·]/)[0] : '';
        if (!src && tpl && code) src = tpl.replace('{}', code.split('/').pop().trim().toLowerCase());
        var at = tc || cells[Math.max(0, nameAt)];
        if (src && at && !at.chip) at.img = await loadImg(src);
        return cells;
      });
    }));
    // one logo per row: when the team column carries it, the name goes without
    var nameK = idx.findIndex(function (i) { return NAME_COL.test(heads[i]) && !TEAM_COL.test(heads[i]); });
    if (teamK >= 0 && nameK >= 0 && nameK !== teamK) data.forEach(function (r) { if (r[teamK].img && r[nameK].img) delete r[nameK].img; });
    try { await document.fonts.load('48px "MS PGothic Pixel"'); } catch (e) {}   // draw only once the site face is in; never a fallback face
    await document.fonts.ready;
    var logo = await loadImg('{{ "img/logo-glyph-lilac.svg" | relURL }}');
    var title = txt(win.querySelector('.win__title-text')).replace(/_$/, '').trim(), base = title.split('::')[0].trim();
    // a board showing a past season (the basketball board's season select): that season in the title
    var seas = win.querySelector('select[data-gfx-season]');
    if (seas && seas.value) { var st = seas.options[seas.selectedIndex].text; base = /\d{4}-\d{2}/.test(base) ? base.replace(/\d{4}-\d{2}/, st) : base + ' ' + st; title = title.replace(/^[^:]*/, base + ' '); }
    // title by what it shows: "top 30", "top 14 QB" filtered to one position, or the mock draft's round(s)
    var posCol = heads.findIndex(function (h) { return h.toLowerCase() === 'pos'; });
    var poss = posCol < 0 ? [] : rows.map(function (r) { return (txt(r.cells[posCol]).match(/^[A-Z\/]+/) || [''])[0]; }).filter(function (v, i, a) { return v && a.indexOf(v) === i; });
    if (btn.hasAttribute('data-gfx-top')) title = base + ' :: top ' + rows.length + (poss.length === 1 ? ' ' + poss[0] : '');
    var rdCol = heads.findIndex(function (h) { return h.toLowerCase() === 'rd'; });
    if (rdCol >= 0) { var rds = rows.map(function (r) { return txt(r.cells[rdCol]); }).filter(function (v, i, a) { return a.indexOf(v) === i; });
      title = base + ' :: round' + (rds.length > 1 ? 's ' + rds[0] + '-' + rds[rds.length - 1] : ' ' + rds[0]); }
    var fs = rdWant ? { filters: [], sort: '' } : filterSummary(win);
    var cnt = win.querySelector('[data-cfb-count], [data-cbb-count], [data-tf-count], [data-gfx-count]'), total = cnt ? (/([\d,]+)\s*(?:of\s*([\d,]+))?/.exec(txt(cnt)) || []) : [];
    var tot = total[2] || total[1], noun = win.hasAttribute('data-gfx-noun') ? ' ' + win.getAttribute('data-gfx-noun') : cnt && /players/.test(txt(cnt)) ? ' players' : '';
    var sub = [rows.length + (tot && +String(tot).replace(/,/g, '') > rows.length ? ' of ' + tot + noun : noun)].concat(fs.filters).concat(fs.sort ? [fs.sort] : []).join(' · ');

    // layout
    var n = data.length, groups = n > 34 ? 2 : 1, per = Math.ceil(n / groups);
    W = n <= 13 ? 2400 : 2160; var portrait = n > 13;
    var HEAD = 96, SUB = 72, FOOT = 64, PADI = 24;
    var rowTarget = portrait ? (groups === 2 ? 72 : 76) : 80;
    var tableH = (per + 1) * rowTarget;
    H = portrait ? Math.min(2700, Math.max(1600, 2 * PAD + HEAD + SUB + tableH + 2 * PADI + FOOT)) : 1350;
    var DL = 46, DETH = deals.length ? 40 + 56 + deals.length * DL : 0;   // the trade list's height
    H += DETH;
    var canvas = document.createElement('canvas'); canvas.width = W; canvas.height = H;
    var g = pixelGlyphs(canvas.getContext('2d')); g.imageSmoothingEnabled = false; g.textBaseline = 'middle';
    // backdrop: pixel grid and a lilac border band
    g.fillStyle = C.bg; g.fillRect(0, 0, W, H);
    g.fillStyle = 'rgba(200,199,255,0.06)';
    for (var gx = 0; gx < W; gx += 16) for (var gy = 0; gy < H; gy += 16) g.fillRect(gx, gy, 2, 2);
    // window with title bar
    var wx = PAD, wy = PAD, ww = W - 2 * PAD, wh = H - 2 * PAD - FOOT;
    g.fillStyle = C.face; g.fillRect(wx, wy, ww, wh); bevel(g, wx, wy, ww, wh, true);
    g.fillStyle = C.title; g.fillRect(wx + 6, wy + 6, ww - 12, HEAD - 20);
    g.font = '48px ' + FONT; g.fillStyle = C.white;
    if (logo) g.drawImage(logo, wx + 22, wy + 18, 52, 52);
    var wkW = weekTag(g, wx, wy, ww, seas && seas.value && seas.selectedIndex > 0 ? '' : seasonWeek());
    g.fillText(fit(g, title, ww - 300 - wkW) + '_', wx + 92, wy + 45);
    for (var b = 0; b < 3; b++) { var bx = wx + ww - 170 + b * 52; g.fillStyle = C.face; g.fillRect(bx, wy + 24, 40, 40); bevel(g, bx, wy + 24, 40, 40, true, 3); }
    // subtitle strip: what is shown
    var hasReal = data.some(function (r) { return r.some(function (c) { return (c.tags || []).some(function (t) { return t.real; }); }); }),
        hasProj = data.some(function (r) { return r.some(function (c) { return (c.tags || []).some(function (t) { return !t.real && !t.kind; }); }); });
    var legW = hasReal || hasProj ? legend(g, wx + ww - 28, wy + HEAD + SUB / 2 - 8, hasReal, hasProj) : 0;
    g.font = '40px ' + FONT; g.fillStyle = C.teal; g.fillText(fit(g, sub, ww - 60 - legW), wx + 28, wy + HEAD + SUB / 2 - 8);
    // the table well
    var ix = wx + 24, iy = wy + HEAD + SUB, iw = ww - 48, ih = wh - HEAD - SUB - 24 - DETH;
    if (deals.length) {   // trades: a header, then each deal behind its tag (solid: already traded, dashed: projected)
      var dy0 = iy + ih + 40, dx0 = ix + 8;
      g.font = '32px ' + FONT; g.fillStyle = C.lilac; g.fillText('TRADES', dx0, dy0 + 20);
      deals.forEach(function (d, i) {
        var cy = dy0 + 56 + i * DL + DL / 2;
        g.font = '24px ' + FONT;
        var tw = tagBox(g, { t: d.real ? 'real' : '⇅ proj', real: d.real }, dx0, cy, 24);
        g.font = '32px ' + FONT; g.fillStyle = d.real ? C.white : C.teal;
        g.fillText(fit(g, d.t, iw - Math.max(136, tw + 24) - 24), dx0 + Math.max(136, tw + 24), cy);
      });
    }
    g.fillStyle = C.well; g.fillRect(ix, iy, iw, ih); bevel(g, ix, iy, iw, ih, false);
    var gw = (iw - 2 * PADI - (groups - 1) * 40) / groups, rowH = Math.min(groups === 1 && !portrait ? 92 : 104, (ih - 2 * PADI) / (per + 1));
    var cols = idx.slice(), cdata = data.map(function (r) { return r.slice(); });
    var sum = function (a) { return a.reduce(function (x, y) { return x + y; }, 0); };
    function widths(sz) {
      g.font = sz + 'px ' + FONT;
      return cols.map(function (ci, k) {
        var m = g.measureText(capHead(heads[ci])).width;
        cdata.forEach(function (row) { var c = row[k]; m = Math.max(m, g.measureText(c.t).width + (c.img ? sz * 0.95 + 10 : 0) + (c.flag ? sz + 10 : 0) + (c.chip ? 24 : 0) + tagsW(c, sz)); g.font = sz + 'px ' + FONT; });
        return m + sz * 0.7;
      });
    }
    // the largest size (64 down to 32 px, steps of 8) that fits the row height and the width. When none fits, the rightmost
    // column goes, but never the rank, name, position, class, team or FV (or any column with logos). With nothing left to
    // drop: first names to initials, then the team as its logo alone, then 24 px; text is cut short only past all of that.
    var keep = function (k) { var h = heads[cols[k]]; return k === 0 || cols[k] === sortI || cols[k] === wkI || (ageI >= 0 && cols[k] === ageI) || NAME_COL.test(h) || POS_COL.test(h) || CLASS_COL.test(h) || TEAM_COL.test(h) || FV_COL.test(h) || cdata.some(function (r) { return r[k].img; }); };
    var size, colW, SIZES = [64, 56, 48, 40, 32];
    var fits = function (sizes) {
      for (var si = 0; si < sizes.length; si++) { size = sizes[si]; if (rowH < size * 1.3) continue; colW = widths(size); if (sum(colW) <= gw) return true; }
      return false;
    };
    var squeezes = [
      function () {   // "Connor McDavid" -> "C. McDavid"
        var k = cols.findIndex(function (ci) { return NAME_COL.test(heads[ci]) && !/^(team|club|matchup|match|game|bet|lineup|unit)$/i.test(heads[ci]); });
        if (k >= 0) cdata.forEach(function (r) { r[k].t = r[k].t.replace(/^([A-Z])[\w'’.-]*\s+(?=\S)/, '$1. '); });
      },
      function () { cdata.forEach(function (r) { r.forEach(function (c, k) { if (c.img && TEAM_COL.test(heads[cols[k]])) c.t = ''; }); }); },
      function () { cdata.forEach(function (r) { r.forEach(function (c) { delete c.flag; }); }); }   // flags go last, before 24 px
    ];
    for (;;) {
      if (fits(SIZES)) break;
      var drop = -1; for (var dk = cols.length - 1; dk >= 0; dk--) if (!keep(dk)) { drop = dk; break; }
      if (cols.length > 4 && drop >= 0) { cols.splice(drop, 1); cdata.forEach(function (r) { r.splice(drop, 1); }); continue; }
      var done = false;
      for (var q = 0; q < squeezes.length && !done; q++) { squeezes[q](); done = fits(SIZES); }
      if (!done && !fits([24])) { size = 24; colW = widths(24); }
      break;
    }
    // what's left over spreads evenly between the columns, so the table runs edge to edge without one wide gap
    var spare = gw - sum(colW);
    if (spare > 0 && colW.length > 1) colW = colW.map(function (w, k) { return k < colW.length - 1 ? w + spare / (colW.length - 1) : w; });
    else if (spare > 0) colW[0] += spare;
    g.font = size + 'px ' + FONT;
    for (var gi = 0; gi < groups; gi++) {
      var x0 = ix + PADI + gi * (gw + 40), y0 = iy + PADI;
      g.fillStyle = C.face; g.fillRect(x0, y0, gw, rowH - 6); bevel(g, x0, y0, gw, rowH - 6, true, 3);
      var cx = x0;
      g.font = Math.max(24, size - 8) + 'px ' + FONT;
      var sk = cols.indexOf(sortI), sx = x0 + sum(colW.slice(0, Math.max(0, sk)));
      cols.forEach(function (ci, k) {
        var hy = y0 + (rowH - 6) / 2, hx = cx + size * 0.45;
        g.fillStyle = k === sk && k > 0 ? C.teal : C.lilac; g.fillText(capHead(heads[ci]), hx, hy);
        if (k === sk && k > 0) { var ax = hx + g.measureText(capHead(heads[ci])).width + 10, u = Math.max(3, Math.round(size / 16)), up = sortDir === 'ascending';
          for (var ar = 0; ar < 3; ar++) g.fillRect(ax + ar * u, hy + (up ? 1 - ar : ar - 1) * u - u / 2, (5 - 2 * ar) * u, u); }   // pixel arrow: the sort's direction
        cx += colW[k]; });
      if (sk > 0) { g.fillStyle = 'rgba(127,255,212,0.06)'; g.fillRect(sx, y0 + rowH - 6, colW[sk], rowH * Math.min(per, cdata.length - gi * per) + 6); }
      g.font = size + 'px ' + FONT;
      cdata.slice(gi * per, gi * per + per).forEach(function (row, r) {
        var y = y0 + rowH * (r + 1);
        if (r % 2) { g.fillStyle = 'rgba(36,26,58,0.45)'; g.fillRect(x0, y, gw, rowH); }
        g.fillStyle = 'rgba(200,199,255,0.08)'; g.fillRect(x0, y + rowH - 2, gw, 2);
        var x = x0;
        row.forEach(function (c, k) {
          var tx = x + size * 0.45, cy = y + rowH / 2;
          if (c.chip) {
            var tw = g.measureText(c.t).width + 24;
            g.fillStyle = c.chip; g.fillRect(tx - 12, cy - size * 0.6, tw, size * 1.2);
            g.fillStyle = 'rgba(0,0,0,0.35)'; g.fillRect(tx - 12, cy + size * 0.6 - 3, tw, 3);
            g.fillStyle = c.ink; g.fillText(c.t, tx, cy);
          } else {
            if (c.img) { var s = size * 0.95; drawLogo(g, c.img, tx, cy - s / 2, s, s); tx += s + 10; }
            if (c.flag) { var fh = Math.round(size * 0.69); g.save(); g.imageSmoothingEnabled = false; g.drawImage(c.flag, tx, Math.round(cy - fh / 2), size, fh); g.restore(); tx += size + 10; }
            // the sorted column in white, a value below zero in pink
            g.fillStyle = c.color || (k === 0 ? C.lilac : k === 1 || k === sk ? C.white : /^[−-]\d/.test(c.t) && !c.img ? C.down : C.teal);
            var tw0 = tagsW(c, size), ft = fit(g, c.t, colW[k] - (tx - x) - 2 - tw0);
            if (c.glow) {   // 5-star+: white pixel outline, teal glow, teal stars on top
              g.save(); g.fillStyle = C.white; [[-2, 0], [2, 0], [0, -2], [0, 2]].forEach(function (d) { g.fillText(ft, tx + d[0], cy + d[1]); });
              g.shadowColor = C.teal; g.shadowBlur = 14; g.fillStyle = C.teal; g.fillText(ft, tx, cy); g.restore();
            }
            g.fillText(ft, tx, cy);
            if (tw0) drawTags(g, c.tags, tx + g.measureText(c.t).width, cy, size);
          }
          x += colW[k];
        });
      });
    }
    // footer
    g.font = '32px ' + FONT; g.fillStyle = C.lilac;
    g.fillText(tabLink(win), PAD, H - PAD - 16);
    var stamp = win.getAttribute('data-gfx-date') || '';
    var right = '@ARKNDJL' + (stamp ? ' · ' + stamp : '');
    g.fillText(right, W - PAD - g.measureText(right).width, H - PAD - 16);
    return canvas;
  }
  // the rows picker beside each table GFX button (graphics of a table, not cards or match graphics)
  function addPickers() {
    document.querySelectorAll('[data-gfx]').forEach(function (btn) {
      if (btn.getAttribute('data-gfx-mode') || btn.hasAttribute('data-gfx-all') || btn.dataset.gfxPicker) return;
      var win = btn.closest('.win'); if (!win || !win.querySelector('table')) return;
      btn.dataset.gfxPicker = '1';
      // a table with a round column (the mock draft) starts at its data-gfx-max (32: all of round 1)
      var heads0 = [].slice.call(win.querySelector('table').tHead.rows[0].cells).map(function (c) { return txt(c).toLowerCase(); });
      var gmax = +win.getAttribute('data-gfx-max'), def = heads0.indexOf('rd') >= 0 && gmax ? gmax : ROWS_DEFAULT;
      // a league table (up to 40 teams, or not built yet) starts at all of it
      var wantH = (win.getAttribute('data-gfx-cols') || '').split(',').map(function (s) { return s.trim(); }).filter(Boolean);
      var nBody = win.querySelector('table').tBodies[0].rows.length;
      if (isTeamTable(wantH.length ? wantH : heads0) && nBody <= 40) def = 'all';
      var opts = ROWS_OPTS.indexOf(def) < 0 ? ROWS_OPTS.concat([def]).sort(function (a, b) { return (a === 'all') - (b === 'all') || a - b; }) : ROWS_OPTS;
      var lab = document.createElement('label'); lab.className = 'cfb__field gfx-rows'; lab.title = 'rows on the graphic';
      lab.innerHTML = '<span>rows</span><select>' + opts.map(function (o) { return '<option' + (o === def ? ' selected' : '') + '>' + o + '</option>'; }).join('') + '</select>';
      btn.insertAdjacentElement('afterend', lab);
      // tables with a round column (the mock draft): pick a round to draw all of it
      var rdI = [].slice.call(win.querySelector('table').tHead.rows[0].cells).findIndex(function (c) { return txt(c).toLowerCase() === 'rd'; });
      if (rdI < 0) return;
      var rds = {}; [].slice.call(win.querySelector('table').tBodies[0].rows).forEach(function (r) { var c = r.cells[rdI]; if (c && /^\d+$/.test(txt(c))) rds[txt(c)] = 1; });
      var rl = document.createElement('label'); rl.className = 'cfb__field gfx-round'; rl.title = 'one full round on the graphic';
      rl.innerHTML = '<span>round</span><select><option value="">on screen</option>' + Object.keys(rds).sort(function (a, b) { return a - b; }).map(function (o) { return '<option>' + o + '</option>'; }).join('') + '</select>';
      lab.insertAdjacentElement('afterend', rl);
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', addPickers); else addPickers();
  document.addEventListener('ark:lazy', addPickers);   // a tab built on first open (lazytab.html)

  // no emoji on the graphics: icon glyphs (riser arrow, star, triangles, arrows) are drawn as 7x7 pixel sprites in the
  // text's colour, sized to the font, wherever they appear in a string a graphic draws (pixelGlyphs wraps fillText)
  var GLYPH = {
    '▲': ['.......', '...#...', '..###..', '.#####.', '#######', '.......', '.......'],
    '▼': ['.......', '.......', '#######', '.#####.', '..###..', '...#...', '.......'],
    '★': ['...#...', '...#...', '#######', '.#####.', '..###..', '.##.##.', '#.....#'],
    '⟁': ['...#...', '..###..', '.##.##.', '#######', '.#.#.#.', '#..#..#', '##.#.##'],   // the site glyph: the ARKLIST mark
    '↗': ['...####', '.....##', '....#.#', '...#..#', '..#....', '.#.....', '#......'],
    '⇄': ['..#....', '.######', '..#....', '.......', '....#..', '######.', '....#..'],
    '→': ['.......', '....#..', '.....#.', '#######', '.....#.', '....#..', '.......'],
    '↑': ['...#...', '..###..', '.#.#.#.', '...#...', '...#...', '...#...', '...#...'],
    '›': ['.......', '..#....', '...#...', '....#..', '...#...', '..#....', '.......'],
    '◆': ['...#...', '..###..', '.#####.', '#######', '.#####.', '..###..', '...#...'],
    '◇': ['...#...', '..#.#..', '.#...#.', '#.....#', '.#...#.', '..#.#..', '...#...'],
    '⇅': ['.#...#.', '###..#.', '.#...#.', '.#...#.', '.#...#.', '.#..###', '.#...#.']
  };
  GLYPH['▴'] = GLYPH['▲']; GLYPH['▾'] = GLYPH['▼']; GLYPH['✦'] = GLYPH['★']; GLYPH['✧'] = GLYPH['★'].map(function (r) { return r.slice(0, 4) + '...'; });   // ARK half star
  var GLYPH_RE = /[▲▼★↗⇄⇅◆◇→↑›▴▾✦✧⟁]/;
  function pixelGlyphs(g) {
    var fill = g.fillText.bind(g);
    g.fillText = function (t, x, y, max) {
      t = String(t);
      if (!GLYPH_RE.test(t)) return fill(t, x, y, max);
      var al = g.textAlign, w = g.measureText(t).width, px = parseFloat((/(\d+(?:\.\d+)?)px/.exec(g.font) || [0, 40])[1]);
      var cx = al === 'center' ? x - w / 2 : al === 'right' || al === 'end' ? x - w : x;
      g.textAlign = 'left';
      t.split(/([▲▼★↗⇄⇅◆◇→↑›▴▾✦✧⟁])/).forEach(function (seg) {
        if (!seg) return;
        var sw = g.measureText(seg).width, sp = GLYPH[seg];
        if (!sp) { fill(seg, cx, y); cx += sw; return; }
        var u = Math.max(1, Math.floor(Math.min(sw, px * 0.75) / 7)), ox = cx + (sw - 7 * u) / 2, oy = y - 3.5 * u;
        sp.forEach(function (row, j) { for (var i = 0; i < 7; i++) if (row[i] === '#') g.fillRect(Math.round(ox + i * u), Math.round(oy + j * u), u, u); });
        cx += sw;
      });
      g.textAlign = al;
    };
    return g;
  }

  // ---- shared frame for the custom graphics: backdrop, window with title bar, footer ----
  // the week of the season a graphic is made in (New York date), by the page's sport: CFB/NFL official weeks
  // (Tue-Mon, week 1 holds Labor Day / its Thursday), the rest Mon-Sun weeks from the season's first week;
  // outside the season a preseason / postseason / offseason tag. Multi-sport pages get none.
  function seasonWeek() {
    var p = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date()).split('-');
    var y = +p[0], t = Date.UTC(y, +p[1] - 1, +p[2]), DAY = 864e5;
    function d(yy, m, dd) { return Date.UTC(yy, m - 1, dd); }
    function on(yy, m, dd, wd) { var x = d(yy, m, dd); return x + ((wd - new Date(x).getUTCDay() + 7) % 7) * DAY; }   // first weekday wd on/after
    function mon(x) { return x - ((new Date(x).getUTCDay() + 6) % 7) * DAY; }   // that week's Monday
    function wk(x0) { return Math.floor((t - x0) / (7 * DAY)) + 1; }
    function W(n) { return 'WEEK ' + n; }
    var sp = /college-football|cfb/.test(location.pathname) ? 'cfb' : /arkboard\/nfl/.test(location.pathname) ? 'nfl'
      : /college-basketball/.test(location.pathname) ? 'cbb' : /arkboard\/nba/.test(location.pathname) ? 'nba'
      : /arkboard\/nhl|hockey-prospects/.test(location.pathname) ? 'nhl' : /arkboard\/soccer/.test(location.pathname) ? 'soccer'
      : /arkboard\/tennis/.test(location.pathname) ? 'tennis' : /arkboard\/(cs2|counter)/.test(location.pathname) ? 'cs2'
      : /arkboard\/baseball/.test(location.pathname) ? 'mlb' : '';
    if (sp === 'cfb' || sp === 'nfl') {
      var s = t < d(y, 3, 1) ? y - 1 : y, ld = on(s, 9, 1, 1);   // Labor Day
      if (sp === 'cfb') { var w0 = ld - 6 * DAY, n = Math.floor((t - w0) / (7 * DAY)) + 1;
        return t < w0 - 14 * DAY ? (t >= d(s, 8, 1) ? 'PRESEASON' : 'OFFSEASON') : n <= 0 ? 'WEEK 0' : n <= 15 ? W(n) : t < d(s + 1, 1, 25) ? 'POSTSEASON' : 'OFFSEASON'; }
      var n2 = Math.floor((t - (ld + DAY)) / (7 * DAY)) + 1;
      return n2 < 1 ? (t >= d(s, 7, 25) ? 'PRESEASON' : 'OFFSEASON') : n2 <= 18 ? W(n2) : ['WILD CARD', 'DIVISIONAL', 'CONF CHAMPIONSHIPS', 'SUPER BOWL', 'SUPER BOWL'][n2 - 19] || 'OFFSEASON';
    }
    if (sp === 'tennis' || sp === 'cs2') {   // calendar weeks: week 1 = the Mon-Sun week holding Jan 1
      var a = mon(d(y + 1, 1, 1)), x1 = t >= a ? a : mon(d(y, 1, 1));
      if (sp === 'tennis' && t >= d(y, 11, 30) && t < a) return 'OFFSEASON';
      return W(wk(x1));
    }
    // fall-to-spring seasons: [opener(season year), last regular week, postseason tag, postseason end (month, day)]
    var C2 = { cbb: [function (s) { return on(s, 11, 1, 1); }, function (s) { return on(s + 1, 3, 8, 0) + DAY; }, 'NCAA TOURNAMENT', [4, 10]],
      nba: [function (s) { return on(s, 10, 20, 2); }, function (s) { return on(s + 1, 4, 10, 1); }, 'PLAYOFFS', [6, 25]],
      nhl: [function (s) { return on(s, 10, 6, 2); }, function (s) { return on(s + 1, 4, 13, 1); }, 'PLAYOFFS', [6, 25]],
      soccer: [function (s) { return mon(on(s, 8, 15, 6)); }, function (s) { return d(s + 1, 6, 1); }, '', [6, 1]] }[sp];
    if (C2) {
      var s2 = t < d(y, 7, 15) ? y - 1 : y, o = C2[0](s2);
      if (t < mon(o)) return t >= o - 30 * DAY ? 'PRESEASON' : 'OFFSEASON';
      if (t < C2[1](s2)) return W(wk(mon(o)));
      return C2[2] && t < d(s2 + 1, C2[3][0], C2[3][1]) ? C2[2] : 'OFFSEASON';
    }
    if (sp === 'mlb') {
      var od = on(y, 3, 25, 4);
      return t < mon(od) ? (t >= d(y, 2, 20) ? 'SPRING TRAINING' : 'OFFSEASON') : t < d(y, 9, 30) ? W(wk(mon(od))) : t < d(y, 11, 5) ? 'POSTSEASON' : 'OFFSEASON';
    }
    return '';
  }
  // the season week as a teal tab at the right of a title bar, left of the window buttons; returns its width
  function weekTag(g, wx, wy, ww, lab) {
    if (!lab) return 0;
    g.font = '40px ' + FONT; var tw = g.measureText(lab).width + 36, tx = wx + ww - 190 - tw;
    g.fillStyle = C.well; g.fillRect(tx, wy + 20, tw, 48); bevel(g, tx, wy + 20, tw, 48, false, 3);
    g.fillStyle = C.teal; g.fillText(lab, tx + 18, wy + 45);
    g.font = '48px ' + FONT; g.fillStyle = C.white;
    return tw + 20;
  }
  async function frame(w, h, title, stamp, link) {
    W = w; H = h;
    try { await document.fonts.load('48px "MS PGothic Pixel"'); } catch (e) {}   // draw only once the site face is in; never a fallback face
    await document.fonts.ready;
    var logo = await loadImg('{{ "img/logo-glyph-lilac.svg" | relURL }}');
    var canvas = document.createElement('canvas'); canvas.width = W; canvas.height = H;
    var g = pixelGlyphs(canvas.getContext('2d')); g.imageSmoothingEnabled = false; g.textBaseline = 'middle';
    g.fillStyle = C.bg; g.fillRect(0, 0, W, H);
    g.fillStyle = 'rgba(200,199,255,0.06)';
    for (var gx = 0; gx < W; gx += 16) for (var gy = 0; gy < H; gy += 16) g.fillRect(gx, gy, 2, 2);
    var wx = PAD, wy = PAD, ww = W - 2 * PAD, wh = H - 2 * PAD - 56;
    g.fillStyle = C.face; g.fillRect(wx, wy, ww, wh); bevel(g, wx, wy, ww, wh, true);
    g.fillStyle = C.title; g.fillRect(wx + 6, wy + 6, ww - 12, 76);
    g.font = '48px ' + FONT; g.fillStyle = C.white;
    if (logo) g.drawImage(logo, wx + 22, wy + 18, 52, 52);
    var wkW = weekTag(g, wx, wy, ww, seasonWeek());
    g.fillText(fit(g, title, ww - 300 - wkW) + '_', wx + 92, wy + 45);
    for (var b = 0; b < 3; b++) { var bx = wx + ww - 170 + b * 52; g.fillStyle = C.face; g.fillRect(bx, wy + 24, 40, 40); bevel(g, bx, wy + 24, 40, 40, true, 3); }
    g.font = '32px ' + FONT; g.fillStyle = C.lilac;
    g.fillText(link || SITE, PAD, H - PAD - 8);
    var right = '@ARKNDJL' + (stamp ? ' · ' + stamp : '');
    g.fillText(right, W - PAD - g.measureText(right).width, H - PAD - 8);
    return { canvas: canvas, g: g, x: wx + 24, y: wy + 100, w: ww - 48, h: wh - 124 };
  }
  function fit(g, t, max) { t = String(t); if (g.measureText(t).width <= max) return t; while (t.length > 1 && g.measureText(t + '…').width > max) t = t.slice(0, -1); return t + '…'; }
  function wrap(g, t, max) {
    var words = String(t).split(' '), lines = [], cur = '';
    words.forEach(function (w) { var n = cur ? cur + ' ' + w : w; if (g.measureText(n).width > max && cur) { lines.push(cur); cur = w; } else cur = n; });
    if (cur) lines.push(cur); return lines;
  }
  function well(g, x, y, w, h) { g.fillStyle = C.well; g.fillRect(x, y, w, h); bevel(g, x, y, w, h, false); }
  function chip(g, x, cy, t, size, fv) {   // an FV chip in the site's colours (read from a live chip)
    var probe = document.createElement('span'); probe.className = 'fv-chip'; probe.setAttribute('data-fv', String(Math.floor(fv / 5) * 5)); probe.style.position = 'absolute'; probe.style.left = '-999px';
    document.body.appendChild(probe); var cs = getComputedStyle(probe), bg = cs.backgroundColor, ink = cs.color; probe.remove();
    g.font = size + 'px ' + FONT; var tw = g.measureText(t).width + size * 0.6;
    g.fillStyle = bg; g.fillRect(x, cy - size * 0.65, tw, size * 1.3);
    g.fillStyle = C.dark; g.fillRect(x, cy + size * 0.65 - 3, tw, 3);
    g.fillStyle = ink; g.fillText(t, x + size * 0.3, cy);
    return tw;
  }
  function money(n) { return n >= 1e6 ? '$' + (n / 1e6).toFixed(n >= 1e7 ? 0 : 1) + 'M' : '$' + Math.round(n / 1e3) + 'K'; }

  // ---- player card: from a scouting report (button carries data-gfx-i, the record index) ----
  // ---- coach card: photo, role and team, score, the role's numbers and scheme percentiles (staff tab) ----
  async function buildCoach(win, btn) {
    var c = (window.__arkCoaches || [])[+btn.getAttribute('data-gfx-i')]; if (!c) return null;
    var F = await frame(2160, 2700, 'staff :: ' + c.name, win.getAttribute('data-gfx-date'));
    var g = F.g, x = F.x + 40, y = F.y + 70, w = F.w - 80, s = c.scheme || {}, d = c.detail || {};
    well(g, F.x, F.y, F.w, F.h);
    var photo = await loadPhoto(c.photo), logo = await loadImg(c.logo);
    photoFrame(g, photo, x, y - 30, 560, 680);
    if (!photo && logo) drawLogo(g, logo, x + 120, y + 130, 320, 320);
    var tx = x + 600, tw = w - 600;
    if (logo) drawLogo(g, logo, tx, y, 96, 96);
    g.font = '96px ' + FONT; g.fillStyle = C.white; wrap(g, c.name, tw).slice(0, 2).forEach(function (l, i) { g.fillText(l, tx, y + 190 + i * 110); });
    var yy = y + 190 + (wrap(g, c.name, tw).length > 1 ? 220 : 110);
    g.font = '56px ' + FONT; g.fillStyle = C.teal; g.fillText(fit(g, [c.role, c.team, c.conf].filter(Boolean).join(' · '), tw), tx, yy); yy += 120;
    g.font = '40px ' + FONT; g.fillStyle = C.lilac; g.fillText('SCORE (100 = AVERAGE ' + c.role + ')', tx, yy); yy += 120;
    g.font = '144px ' + FONT; g.fillStyle = c.score >= 100 ? C.teal : C.down; g.fillText(String(c.score), tx, yy);
    g.font = '56px ' + FONT; g.fillStyle = C.lilac; g.fillText('#' + c.rk + ' ' + c.role, tx + g.measureText(String(c.score)).width * 2.6 + 40, yy);
    y += 720;
    var tiles = c.role === 'HC' ? [['ELO', (d.elo || '—') + (d.eloRk ? ' #' + d.eloRk : '')], ['TvE', d.tve == null ? '—' : (d.tve > 0 ? '+' : '') + d.tve.toFixed(2)], ['RECORD', d.rec ? d.rec.w + '-' + d.rec.l : '—']]
      : [['OVER TALENT', c.over == null ? '—' : (c.over > 0 ? '+' : '') + c.over.toFixed(2)], ['DEVELOPMENT', c.dev == null ? '—' : (c.dev > 0 ? '+' : '') + c.dev.toFixed(1)], ['GROUPS', (c.groups || []).join(' ')]];
    var cw = (w - 48) / 3, th = 210;
    tiles.forEach(function (t, i) { var bx = x + i * (cw + 24); g.fillStyle = C.face; g.fillRect(bx, y, cw, th); bevel(g, bx, y, cw, th, true, 3);
      g.font = '40px ' + FONT; g.fillStyle = C.lilac; g.fillText(t[0], bx + 24, y + 56); g.font = '80px ' + FONT; g.fillStyle = C.white; g.fillText(fit(g, t[1], cw - 48), bx + 24, y + 150); });
    y += th + 90;
    var bars = c.role === 'HC' ? [['4th-down go rate', s.go == null ? '—' : Math.round(s.go * 100) + '%', s.goP]]
      : c.role === 'OC' ? [['tempo', s.tempo ? s.tempo + ' plays/g' : '—', s.tempoP], ['run rate', s.run == null ? '—' : Math.round(s.run * 100) + '%', s.runP]]
      : [['havoc', s.havoc == null ? '—' : Math.round(s.havoc * 100) + '%', s.havocP], ['stuff rate', s.stuff == null ? '—' : Math.round(s.stuff * 100) + '%', s.stuffP], ['explosiveness allowed', s.xpl == null ? '—' : s.xpl.toFixed(2), s.xplP]];
    g.font = '56px ' + FONT; g.fillStyle = C.teal; g.fillText('scheme · FBS percentile', x, y); y += 100;
    bars.forEach(function (b) {
      g.font = '48px ' + FONT; g.fillStyle = C.lilac; g.fillText(b[0], x, y);
      g.fillStyle = C.white; g.fillText(b[1], x + 620, y);
      g.fillStyle = C.dark; g.fillRect(x + 1000, y - 34, w - 1180, 40);
      if (b[2] != null) { g.fillStyle = C.teal; g.fillRect(x + 1000, y - 34, (w - 1180) * b[2] / 100, 40); g.fillStyle = C.lilac; g.fillText(String(b[2]), x + w - 140, y); }
      y += 90;
    });
    if ((c.risers || []).length) {
      y += 40; g.font = '56px ' + FONT; g.fillStyle = C.teal; g.fillText('risers (HS grade → now)', x, y); y += 90;
      g.font = '48px ' + FONT;
      c.risers.slice(0, 6).forEach(function (r) { if (y > F.y + F.h - 60) return; g.fillStyle = C.white; g.fillText(r.name, x, y); g.fillStyle = C.lilac; g.fillText(r.pos + '  ' + r.hs + ' → ' + r.now, x + 760, y); y += 72; });
    }
    return F.canvas;
  }
  // ---- team builder plan, college basketball (cbbbuilder.html sets window.__arkCbbBuilder): the program's offseason on a
  // 4:5 card: header, team rating now / returning / after the plan, the NIL budget bar, next season's rotation by BPM
  // (FR class, NEW signing, KEEP tags), the signings with where they come from, and who leaves and why
  async function buildCbbPlan(win) {
    var B = window.__arkCbbBuilder, T = B && B.current, D = B && B.data; if (!T) return null;
    var nxt = D.season + '-' + String(D.season + 1).slice(2);
    var F = await frame(2160, 2700, 'team builder :: ' + T.t + ' ' + nxt, B.stamp || '', SITE + '#builder:' + encodeURIComponent(T.t));
    var g = F.g, x = F.x + 32, y = F.y + 40, w = F.w - 64, i;
    well(g, F.x, F.y, F.w, F.h);
    var lg = await loadImg(T.logo);
    if (lg) drawLogo(g, lg, x, y, 160, 160);
    g.font = '96px ' + FONT; g.fillStyle = C.white; g.fillText(fit(g, T.t, w - 200), x + 192, y + 56);
    g.font = '48px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, [T.conf, T.coach, 'ARK #' + T.rk].filter(Boolean).join(' · '), w - 200), x + 192, y + 136);
    y += 208;
    // three rating tiles: now, returning (no adds), after the plan
    var tiles = [['RATING NOW', T.now, ''], ['RETURNING', T.ret, ''], ['AFTER PLAN', T.after, (T.after - T.ret >= 0 ? '+' : '−') + Math.abs(T.after - T.ret).toFixed(1) + ' signed']];
    var tw = Math.floor((w - 2 * 24) / 3), th = 184;
    tiles.forEach(function (t, k) {
      var tx = x + k * (tw + 24);
      g.fillStyle = C.face; g.fillRect(tx, y, tw, th); bevel(g, tx, y, tw, th, true, 4);
      if (k === 2) { g.fillStyle = C.teal; g.fillRect(tx, y, tw, 6); }
      g.font = '36px ' + FONT; g.fillStyle = C.lilac; g.fillText(t[0], tx + 24, y + 40);
      g.font = '88px ' + FONT; g.fillStyle = k === 2 ? C.teal : C.white; var v = (t[1] >= 0 ? '+' : '−') + Math.abs(t[1]).toFixed(1); g.fillText(v, tx + 24, y + 116);
      if (t[2]) { var vw = g.measureText(v).width; g.font = '36px ' + FONT; g.fillStyle = C.teal; g.fillText(t[2], tx + 24 + vw + 24, y + 124); }
    });
    y += th + 56;
    // budget bar: spend against the budget
    g.font = '44px ' + FONT; g.fillStyle = C.teal; g.fillText('NIL BUDGET ' + money(T.budget), x, y);
    g.font = '36px ' + FONT; g.fillStyle = C.lilac; var sp = 'spend ' + money(T.spend) + ' · ' + Math.round(100 * T.spend / Math.max(1, T.budget)) + '%'; g.fillText(sp, x + w - g.measureText(sp).width, y);
    y += 40;
    var bh = 56, fr = Math.max(0, Math.min(1, T.spend / Math.max(1, T.budget)));
    g.fillStyle = C.dark; g.fillRect(x, y, w, bh);
    g.fillStyle = C.teal; g.fillRect(x, y, Math.round(w * fr), bh);
    g.fillStyle = 'rgba(0,0,0,0.3)'; for (var q = x + 14; q < x + w * fr; q += 16) g.fillRect(q, y, 2, bh);
    bevel(g, x, y, w, bh, false, 4);
    y += bh + 64;
    function head(t, hx, hy, hw) {
      g.font = '40px ' + FONT; g.fillStyle = C.lilac; g.fillText(t, hx, hy);
      var lw = g.measureText(t).width + 20; g.fillStyle = C.dark; g.fillRect(hx + lw, hy - 2, Math.max(0, hw - lw), 3);
    }
    function sg(v) { return (v >= 0 ? '+' : '−') + Math.abs(v).toFixed(1); }
    function tag(t, tx, cy, col) {
      g.font = '26px ' + FONT; var ww = g.measureText(t).width + 16;
      g.fillStyle = col; g.fillRect(tx, cy - 17, ww, 34); g.fillStyle = C.dark; g.fillText(t, tx + 8, cy + 1); return ww;
    }
    var colW = Math.floor((w - 48) / 2), lx = x, rx = x + colW + 48, top = y, bottom = F.y + F.h - 32;
    // rows as tall as the space allows (62-88 px), so a short plan still fills the card
    var nRot = T.back.length + (T.commits || []).length + T.plan.length, nRight = Math.max(1, T.plan.length) + Math.max(1, T.leave.length);
    var RH = Math.max(62, Math.min(88, Math.floor(Math.min((bottom - top - 96) / Math.max(1, nRot), (bottom - top - 152) / nRight))));
    // left: next season's rotation, best BPM first
    var rot = T.back.map(function (p) { return { n: p.name, pos: p.pos, fv: p.fv, bpm: p.bpm, k: '' }; })
      .concat((T.commits || []).map(function (c) { return { n: c.name, pos: c.pos, fv: c.fv, bpm: c.bpm, k: 'FR' }; }))
      .concat(T.plan.map(function (s) { return { n: s.name, pos: s.pos, fv: s.fv, bpm: s.bpm, k: s.kind === 'keep' ? 'KEEP' : 'NEW' }; }))
      .sort(function (a, b) { return b.bpm - a.bpm; });
    head('NEXT SEASON · ' + rot.length + ' OF ' + D.roster, lx, y, colW);
    y += 56;
    g.font = '28px ' + FONT; g.fillStyle = C.lilac;
    [['POS', 470], ['FV', 580], ['BPM', 690]].forEach(function (h) { g.fillText(h[0], lx + h[1], y); }); y += 40;
    var maxRot = Math.min(rot.length, Math.floor((bottom - y) / RH));
    for (i = 0; i < maxRot; i++) {
      var o = rot[i], cy = y + RH / 2;
      if (i % 2) { g.fillStyle = 'rgba(36,26,58,0.45)'; g.fillRect(lx, y, colW, RH); }
      if (i === 5) { g.fillStyle = C.teal; g.fillRect(lx, y - 1, colW, 3); }   // the five above the line start
      g.font = '36px ' + FONT; g.fillStyle = C.lilac; g.fillText(String(i + 1), lx + 8, cy);
      g.fillStyle = C.white; g.fillText(fit(g, o.n, 390), lx + 64, cy);
      g.fillStyle = C.lilac; g.fillText(o.pos || '', lx + 470, cy);
      if (o.fv != null) chip(g, lx + 580, cy, String(Math.round(o.fv)), 32, o.fv);
      g.font = '36px ' + FONT; g.fillStyle = o.bpm >= 0 ? C.teal : C.down; g.fillText(sg(o.bpm), lx + 690, cy);
      if (o.k) tag(o.k, lx + 820, cy, o.k === 'NEW' ? C.teal : o.k === 'FR' ? C.lilac : '#ffd34d');
      y += RH;
    }
    // right: the plan, then who leaves
    y = top;
    var nk = T.plan.filter(function (s) { return s.kind === 'keep'; }).length, ns = T.plan.length - nk;
    head('THE PLAN · ' + ns + ' SIGNING' + (ns === 1 ? '' : 'S') + (nk ? ' · ' + nk + ' KEPT' : ''), rx, y, colW);
    y += 56;
    if (!T.plan.length) { g.font = '36px ' + FONT; g.fillStyle = C.lilac; g.fillText('no signings', rx, y + RH / 2); y += RH; }
    var logos = await Promise.all(T.plan.map(function (s) { return s.kind === 'keep' ? null : loadImg(s.logo); }));
    var maxPlan = Math.min(T.plan.length, Math.max(1, Math.floor((bottom - y - 56 - 2 * RH) / RH)));
    for (i = 0; i < maxPlan; i++) {
      var s = T.plan[i], cy2 = y + RH / 2, nx = rx;
      if (i % 2) { g.fillStyle = 'rgba(36,26,58,0.45)'; g.fillRect(rx, y, colW, RH); }
      if (logos[i]) drawLogo(g, logos[i], rx + 4, cy2 - 22, 44, 44); else tag('KEEP', rx, cy2, '#ffd34d');
      nx = rx + 96;
      g.font = '36px ' + FONT; g.fillStyle = C.white; g.fillText(fit(g, s.name, colW - 96 - 330), nx, cy2);
      g.fillStyle = C.lilac; g.fillText(s.pos || '', rx + colW - 320, cy2);
      g.fillStyle = C.teal; var gn = '+' + s.gain.toFixed(1); g.fillText(gn, rx + colW - 230, cy2);
      g.font = '30px ' + FONT; g.fillStyle = C.lilac; var cs = money(s.cost); g.fillText(cs, rx + colW - g.measureText(cs).width - 8, cy2);
      y += RH;
    }
    y += 40;
    head('LEAVING · ' + T.leave.length, rx, y, colW);
    y += 56;
    var WHYC = { draft: C.teal, eligibility: C.lilac, transfer: C.down, 'leaves D-I': '#ffd34d' };
    var maxL = Math.min(T.leave.length, Math.floor((bottom - y) / RH));
    for (i = 0; i < maxL; i++) {
      var p = T.leave[i], cy3 = y + RH / 2;
      if (i % 2) { g.fillStyle = 'rgba(36,26,58,0.45)'; g.fillRect(rx, y, colW, RH); }
      g.font = '36px ' + FONT; g.fillStyle = C.white; g.fillText(fit(g, p.name, colW - 330), rx + 8, cy3);
      if (p.fv != null) chip(g, rx + colW - 300, cy3, String(Math.round(p.fv)), 32, p.fv);
      g.font = '26px ' + FONT; var wt = String(p.why).toUpperCase(), ww2 = g.measureText(wt).width + 16;
      tag(wt, rx + colW - ww2 - 8, cy3, WHYC[p.why] || C.lilac);
      y += RH;
    }
    if (!T.leave.length) { g.font = '36px ' + FONT; g.fillStyle = C.lilac; g.fillText('no departures', rx, y + RH / 2); }
    return F.canvas;
  }
  // ---- team builder plan (cfbbuilder.html): the selected program's whole offseason on one 4:5 card ----
  // header and mode, the budget bar, next season's 22 on a pixel field (returning, signing, open), the
  // signings, who's leaving and why, and value now / with no adds / with the plan
  function surname(n) { var w = String(n).split(' ').filter(function (x) { return !/^(jr\.?|sr\.?|ii|iii|iv|v)$/i.test(x); }); return w[w.length - 1] || n; }
  async function buildBuilder(win, btn) {
    var B = window.__arkBuilder, T = B && B.current; if (!T) return null;
    var F = await frame(2160, 2700, 'team builder :: ' + T.team + ' ' + B.data.next + ' offseason', win.querySelector('[data-tb-asof]') ? txt(win.querySelector('[data-tb-asof]')) : '');
    var g = F.g, x = F.x + 32, y = F.y + 40, w = F.w - 64, M = B.mode[T.mode];
    well(g, F.x, F.y, F.w, F.h);
    var lg = await loadImg(T.logo);
    if (lg) drawLogo(g, lg, x, y, 160, 160);
    g.font = '96px ' + FONT; g.fillStyle = C.white; g.fillText(fit(g, T.full || T.team, w - 640), x + 192, y + 56);
    g.font = '48px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, [T.conf, T.level, T.hc, T.rec ? T.rec.w + '-' + T.rec.l : null].filter(Boolean).join(' · '), w - 640), x + 192, y + 136);
    // the mode as a raised pixel plaque
    var modeCol = { squeeze: C.down, reload: '#ffd34d', retool: C.lilac, reinforce: C.teal }[T.mode];
    g.font = '64px ' + FONT; var mw = g.measureText(M[0]).width + 64;
    g.fillStyle = modeCol; g.fillRect(x + w - mw, y + 16, mw, 112); bevel(g, x + w - mw, y + 16, mw, 112, true, 6);
    g.fillStyle = C.dark; g.fillText(M[0], x + w - mw + 32, y + 74);
    if (T.buyer) { g.font = '32px ' + FONT; g.fillStyle = C.teal; g.fillText('BUYER: 40%+ OPEN', x + w - mw, y + 160); }
    y += 208;
    // budget bar
    g.font = '48px ' + FONT; g.fillStyle = C.teal; g.fillText('NIL BUDGET ' + money(T.budget), x, y);
    g.font = '32px ' + FONT; g.fillStyle = C.lilac; var mv = 'roster market value ' + money(T.market); g.fillText(mv, x + w - g.measureText(mv).width, y);
    y += 48;
    var tot = Math.max(T.budget, T.reserve + T.keepCost + Math.max(0, T.spend) + Math.max(0, T.left)) || 1, bx = x, bh = 72;
    g.fillStyle = C.dark; g.fillRect(x, y, w, bh);
    [[T.reserve, C.lilac, 'CLASS'], [T.keepCost, C.title, 'KEEP'], [T.spend, C.teal, 'SIGN'], [T.left, C.well, 'LEFT']].forEach(function (s) {
      var sw = Math.max(0, s[0]) / tot * w; if (sw < 1) return;
      g.fillStyle = s[1]; g.fillRect(bx, y, sw, bh);
      g.fillStyle = 'rgba(0,0,0,0.3)'; for (var q = bx + 14; q < bx + sw; q += 16) g.fillRect(q, y, 2, bh);
      bx += sw;
    });
    bevel(g, x, y, w, bh, false, 4);
    y += bh + 40;
    g.font = '34px ' + FONT; var lx = x;
    [[C.lilac, 'class ' + money(T.reserve)], [C.title, 'keep ' + money(T.keepCost)], [C.teal, 'sign ' + money(T.spend)], [C.well, 'left ' + money(T.left)]].forEach(function (s) {
      g.fillStyle = s[0]; g.fillRect(lx, y - 16, 32, 32); bevel(g, lx, y - 16, 32, 32, true, 2); g.fillStyle = C.white; g.fillText(s[1], lx + 48, y); lx += g.measureText(s[1]).width + 96;
    });
    y += 48;
    // the field: defense on top, offense below, each starter a pixel tile with his full name, filled in the
    // depth chart's FV ramp (B.tier) with the FV large in the corner; signings get a teal frame and a NEW tab,
    // open spots a dashed pink frame. Names wrap to two lines (three for the longest), the font stepping down
    var fh = 1000, fx = x, fw = w;
    g.fillStyle = '#2f2550'; g.fillRect(fx, y, fw, fh); bevel(g, fx, y, fw, fh, false, 4);
    g.fillStyle = 'rgba(200,199,255,0.16)'; for (var yl = y + 40; yl < y + fh; yl += 80) g.fillRect(fx + 8, yl, fw - 16, 3);
    g.fillStyle = C.teal; g.fillRect(fx + 8, y + Math.round(fh * 0.495) - 3, fw - 16, 6);   // line of scrimmage
    var P = {}; T.positions.forEach(function (p) { P[p.g] = B.lineup(T, p); });
    // seven columns across (the five OL plus a WR each side), rows in field units (0-1 down)
    var bw = Math.floor((fw - 40 - 6 * 14) / 7), bhh = 100, tier = B.tier || function () { return [0, C.lilac, C.dark]; };
    var X = [0, 1, 2, 3, 4, 5, 6].map(function (i) { return (20 + bw / 2 + i * (bw + 14)) / fw; });
    var L = { CB: [[X[0], 0.095], [X[6], 0.095], [X[6], 0.26]], S: [[X[2], 0.095], [X[4], 0.095]], LB: [[X[2], 0.26], [X[4], 0.26]], EDGE: [[X[1], 0.415], [X[5], 0.415]], DL: [[X[2], 0.415], [X[4], 0.415]],
              OL: [[X[1], 0.57], [X[2], 0.57], [X[3], 0.57], [X[4], 0.57], [X[5], 0.57]], WR: [[X[0], 0.57], [X[6], 0.57], [X[1], 0.715]], TE: [[X[5], 0.715]], QB: [[X[3], 0.715]], RB: [[X[3], 0.86]] };
    function nameFit(n) {
      n = String(n).replace(/\s*["\u201c][^"\u201d]*["\u201d]\s*/g, ' ').trim();   // a quoted nickname gives way to the name
      var tw = bw - 20, hy = n.replace(/-/g, '- ');   // a hyphenated surname may break after the hyphen
      for (var pass = 1; pass <= 2; pass++) for (var fs = 32; fs >= 22; fs -= 2) {
        g.font = fs + 'px ' + FONT;
        for (var v = 0; v < 2; v++) {
          var t = v ? hy : n;
          if (t.split(' ').some(function (wd) { return g.measureText(wd).width > tw; })) continue;
          var ls = wrap(g, t, tw).map(function (l) { return l.replace(/- /g, '-'); }); if (ls.length <= pass) return { fs: fs, ls: ls };
        }
      }
      g.font = '22px ' + FONT; return { fs: 22, ls: wrap(g, n, tw).slice(0, 2).map(function (l) { return fit(g, l, tw); }) };
    }
    // the second string: next season's chart (returners, the class, redshirts) past the starters, one under each tile
    var Q = {}; T.positions.forEach(function (p) {
      var on = (P[p.g] || []).map(function (o) { return o.name; });
      Q[p.g] = (p.chart || []).filter(function (o) { return o.kind !== 'open' && o.kind !== 'new' && (o.p == null || o.p >= 0.5) && on.indexOf(o.name) < 0; });
    });
    var lab = B.lab || function (g) { return g; }, was = B.was || function () { return ''; }, OLS = ['LT', 'LG', 'C', 'RG', 'RT'];
    Object.keys(L).forEach(function (pos) { (P[pos] || []).forEach(function (o, i) {
      var at = L[pos][o.at ? OLS.indexOf(o.at) : i]; if (!at) return;
      var cx = Math.round(fx + at[0] * fw - bw / 2), cy = Math.round(y + at[1] * fh - bhh / 2), q;
      var t = tier(o.fv), ink = o.kind === 'open' ? C.down : t[2];
      if (o.kind === 'open') {
        g.fillStyle = C.dark; g.fillRect(cx, cy, bw, bhh); g.fillStyle = C.down;
        for (q = 0; q < bw; q += 16) { g.fillRect(cx + q, cy, 8, 4); g.fillRect(cx + q, cy + bhh - 4, 8, 4); }
        for (q = 0; q < bhh; q += 16) { g.fillRect(cx, cy + q, 4, 8); g.fillRect(cx + bw - 4, cy + q, 4, 8); }
      } else {
        if (o.kind === 'new') { g.fillStyle = C.teal; g.fillRect(cx - 6, cy - 6, bw + 12, bhh + 12); }
        g.fillStyle = C.dark; g.fillRect(cx - 2, cy - 2, bw + 4, bhh + 4);
        g.fillStyle = t[1]; g.fillRect(cx, cy, bw, bhh); bevel(g, cx, cy, bw, bhh, true, 3);
      }
      g.font = '24px ' + FONT; g.fillStyle = ink; g.fillText(o.at || lab(pos), cx + 10, cy + 28);
      var wz = o.kind !== 'new' && o.kind !== 'open' ? was(o) : '';
      if (wz) {   // a moved starter: a FROM tab on the tile's top edge (a position change, a slide on the line, a spare filling in)
        g.font = '20px ' + FONT; var zw = g.measureText('FROM ' + wz).width + 12;
        g.fillStyle = C.dark; g.fillRect(cx + bw - zw - 12, cy - 16, zw + 4, 26); g.fillStyle = C.lilac; g.fillRect(cx + bw - zw - 10, cy - 14, zw, 22);
        g.fillStyle = C.dark; g.fillText('FROM ' + wz, cx + bw - zw - 4, cy - 3);
      }
      if (o.kind === 'new') {   // a NEW tab on the tile's top edge, over the teal frame
        g.font = '20px ' + FONT; var nw = g.measureText('NEW').width + 12;
        g.fillStyle = C.dark; g.fillRect(cx + bw - nw - 12, cy - 16, nw + 4, 26); g.fillStyle = C.teal; g.fillRect(cx + bw - nw - 10, cy - 14, nw, 22);
        g.fillStyle = C.dark; g.fillText('NEW', cx + bw - nw - 4, cy - 3);
      }
      g.font = '44px ' + FONT; g.fillStyle = ink; var fvs = String(Math.round(o.fv)); g.fillText(fvs, cx + bw - 10 - g.measureText(fvs).width, cy + 44);
      var nf = o.kind === 'open' ? { fs: 28, ls: ['OPEN'] } : nameFit(o.name), lh = nf.fs + (nf.ls.length > 1 ? 0 : 4);
      g.font = nf.fs + 'px ' + FONT; g.fillStyle = ink;   // middle baseline: centre the lines in the space under the label
      var ny = cy + 56 + (bhh - 58 - nf.ls.length * lh) / 2 + lh / 2;
      nf.ls.forEach(function (l, k) { g.fillText(l, cx + 10, ny + k * lh); });
      var b2 = (Q[pos] || [])[i];   // his backup: a dark strip under the tile, full name and FV in its tier colour
      if (b2) {
        var by = cy + bhh + 4, nm2 = String(b2.name).replace(/\s*["\u201c][^"\u201d]*["\u201d]\s*/g, ' ').trim(), t2 = tier(b2.fv);
        g.fillStyle = C.dark; g.fillRect(cx, by, bw, 30);
        g.font = '22px ' + FONT; var f2 = String(Math.round(b2.fv)), fw2 = g.measureText(f2).width + 12;
        g.fillStyle = t2[1]; g.fillRect(cx + bw - fw2 - 2, by + 2, fw2, 26); g.fillStyle = t2[2]; g.fillText(f2, cx + bw - fw2 + 4, by + 16);
        g.fillStyle = C.lilac; g.fillText(fit(g, '2 ' + nm2 + (b2.kind === 'recruit' ? ' FR' : ''), bw - fw2 - 16), cx + 8, by + 16);
      }
    }); });
    // the tile key along the field's bottom edge, under the back: the FV ramp, then returning / signing / open
    var TS = B.tiers || [], sw = 66, ky = y + fh - 34, kx = fx + 24;
    g.font = '28px ' + FONT; g.fillStyle = C.teal; g.fillText('FV', kx, ky); kx += 52;
    TS.forEach(function (t, i) {
      g.fillStyle = t[1]; g.fillRect(kx + i * sw, ky - 22, sw, 44);
      g.font = '24px ' + FONT; g.fillStyle = t[2]; var lab = (i ? String(t[0]) : '<' + TS[1][0]) + (i === TS.length - 1 ? '+' : '');
      g.fillText(lab, kx + i * sw + (sw - g.measureText(lab).width) / 2, ky);
    });
    bevel(g, kx, ky - 22, sw * TS.length, 44, false, 3);
    g.font = '26px ' + FONT; var kw = 0;
    var KEY = [['back', 'returning'], ['new', 'signing'], ['open', 'open'], ['two', 'backup']];
    KEY.forEach(function (k) { kw += 44 + g.measureText(k[1]).width; }); kw += 28 * (KEY.length - 1);
    kx = fx + fw - 24 - kw;
    KEY.forEach(function (k) {
      if (k[0] === 'new') { g.fillStyle = C.teal; g.fillRect(kx - 4, ky - 18, 36, 36); }
      if (k[0] === 'two') { g.fillStyle = C.dark; g.fillRect(kx, ky - 8, 28, 16); g.fillStyle = C.lilac; g.fillRect(kx + 4, ky - 2, 12, 4); }
      else if (k[0] === 'open') { g.fillStyle = C.down; for (var q = 0; q < 28; q += 8) { g.fillRect(kx + q, ky - 14, 4, 3); g.fillRect(kx + q, ky + 11, 4, 3); g.fillRect(kx, ky - 14 + q, 3, 4); g.fillRect(kx + 25, ky - 14 + q, 3, 4); } }
      else { g.fillStyle = C.dark; g.fillRect(kx - 1, ky - 15, 30, 30); g.fillStyle = C.lilac; g.fillRect(kx + 1, ky - 13, 26, 26); }
      g.fillStyle = k[0] === 'open' ? C.down : k[0] === 'new' ? C.teal : C.white; g.fillText(k[1], kx + 44, ky); kx += 44 + g.measureText(k[1]).width + 28;
    });
    // right of the field: value by position against the bar, then value now -> plan
    // under the field: each unit against the contender bar in one row, then WAR a season now / no adds / plan
    var uy = y + fh + 56;
    g.font = '40px ' + FONT; g.fillStyle = C.teal; g.fillText('UNITS VS BAR', x, uy);
    var uw = g.measureText('UNITS VS BAR').width; g.font = '26px ' + FONT; g.fillStyle = C.lilac; g.fillText('(tick = contender bar)', x + uw + 20, uy);
    var wl = [['now', T.av26, C.lilac], T.avExp != null ? ['expected', T.avExp, C.white] : ['no adds', T.av27, C.down], ['plan', T.avPlan, C.teal]], wx = x + w;
    g.font = '32px ' + FONT;
    wl.slice().reverse().forEach(function (b, k) {
      var s1 = (b[1] * WARK).toFixed(2); g.fillStyle = b[2]; wx -= g.measureText(s1).width; g.fillText(s1, wx, uy);
      g.fillStyle = C.lilac; wx -= g.measureText(b[0] + ' ').width; g.fillText(b[0] + ' ', wx, uy); wx -= 36;
    });
    g.fillStyle = C.teal; wx -= g.measureText('WAR A SEASON ').width; g.fillText('WAR A SEASON ', wx, uy);
    var cwu = w / T.positions.length;
    T.positions.forEach(function (p, k) {
      var after = p.nextAv + (T.plan || []).filter(function (s) { return s.slot === p.g; }).reduce(function (a, s) { return a + s.gain; }, 0);
      var f = Math.min(1, after / Math.max(p.bar, 0.1) * 0.5), col = after >= p.bar ? C.teal : after >= p.bar * 0.7 ? C.lilac : C.down;
      var ux = x + k * cwu, bwu = cwu - 24;
      g.font = '28px ' + FONT; g.fillStyle = C.white; g.fillText(lab(p.g), ux, uy + 64); var lw = 76; bwu -= lw;
      g.fillStyle = C.dark; g.fillRect(ux + lw, uy + 50, bwu, 28);
      g.fillStyle = col; g.fillRect(ux + lw, uy + 50, bwu * f, 28);
      g.fillStyle = C.white; g.fillRect(ux + lw + bwu * 0.5 - 2, uy + 44, 4, 40);
    });
    y += fh + 56 + 84 + 72;
    // signings and departures, side by side
    var cw = (w - 48) / 2;
    function list(lx, title, rows, line) {
      var ly = y; g.font = '48px ' + FONT; g.fillStyle = C.teal; g.fillText(title, lx, ly); ly += 72;
      if (!rows.length) { g.font = '32px ' + FONT; g.fillStyle = C.lilac; g.fillText('none', lx, ly); return; }
      rows.forEach(function (p) { if (ly > F.y + F.h - 300) return; line(p, lx, ly); ly += 84; });
    }
    var nl = 2;   // the target board takes the room under the lists
    list(x, 'SIGN ' + T.plan.length + ' · ' + money(T.spend) + (T.plan.length > nl ? ' · TOP ' + nl : ''), T.plan.slice().sort(function (a, b) { return b.gain - a.gain; }).slice(0, nl), function (p, lx, ly) {
      var cwid = chip(g, lx, ly, String(Math.round(p.fv)), 32, p.fv);
      g.font = '40px ' + FONT; g.fillStyle = C.white; g.fillText(fit(g, (p.as ? lab(p.pos) + '>' + lab(p.as) : lab(p.pos)) + ' ' + p.name, cw - cwid - 24), lx + cwid + 16, ly);
      g.font = '32px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, p.team + (p.div ? ' (FCS)' : '') + ' · ' + money(p.cost) + ' · +' + (p.gain * WARK).toFixed(2) + ' WAR · ' + ((p.real || [])[0] || (p.mi != null ? p.mi + ' mi from home' : '')), cw - 16), lx, ly + 44);
    });
    list(x + cw + 48, 'LEAVING', T.leaving.slice(0, nl), function (p, lx, ly) {
      var cwid = chip(g, lx, ly, String(Math.round(p.fv)), 32, p.fv);
      g.font = '40px ' + FONT; g.fillStyle = C.white; g.fillText(fit(g, lab(p.pos) + ' ' + p.name, cw - cwid - 24), lx + cwid + 16, ly);
      var wc = { draft: '#ffd34d', transfer: C.down, eligibility: C.lilac, 'priced out': C.teal }[p.why] || C.lilac;
      g.font = '32px ' + FONT; var tw = g.measureText(p.why.toUpperCase()).width + 16;
      g.fillStyle = wc; g.fillRect(lx, ly + 26, tw, 36); g.fillStyle = C.dark; g.fillText(p.why.toUpperCase(), lx + 8, ly + 45);
      g.fillStyle = C.lilac; g.fillText(Math.round(p.gone * 100) + '% gone', lx + tw + 16, ly + 45);
    });
    // the target board: at each need (then the other units), the best realistic target the plan doesn't sign,
    // one line each: FV, position and name, school, xNIL, landing odds, the short reason he fits
    var ty = y + 72 + nl * 84 + 24, signed = {}; (T.plan || []).forEach(function (p) { signed[p.name + '|' + p.team] = 1; });
    var tg = [], order = (T.needs || []).concat(T.positions.map(function (p) { return p.g; }).filter(function (g) { return (T.needs || []).indexOf(g) < 0; }));
    order.forEach(function (gp) { var c = (T.targets[gp] || []).filter(function (p) { return !signed[p.name + '|' + p.team]; })[0]; if (c && tg.length < 6) tg.push([gp, c]); });
    // then second choices at the needs, so the board has rows to show when few units have a target
    (T.needs || []).forEach(function (gp) { var c = (T.targets[gp] || []).filter(function (p) { return !signed[p.name + '|' + p.team]; })[1]; if (c && tg.length < 6) tg.push([gp, c]); });
    // the foot: walk (one line), keep (one line), then the plan's summary in two
    var olMv = ((T.positions.filter(function (p) { return p.g === 'OL'; })[0] || {}).lineup || []).filter(function (o) { return o.shift && o.name; });
    var mvs = (T.moves || []).map(function (m) { return lab(m.pos) + ' ' + m.name + ' to ' + lab(m.to); }).concat(olMv.map(function (o) { return o.shift + ' ' + o.name + ' to ' + o.at; }));
    var footN = ((T.walk || []).length ? 1 : 0) + ((T.keep || []).length ? 1 : 0) + (mvs.length ? 1 : 0), fy0 = F.y + F.h - 150 - 46 * (footN - 1);
    g.font = '48px ' + FONT; g.fillStyle = C.teal; g.fillText('TARGET BOARD', x, ty);
    g.font = '28px ' + FONT; g.fillStyle = C.lilac;
    var tcol = [0, 96, 760, 1180, 1370, 1530];   // chip, name, school, xNIL, land, why
    [['SCHOOL', 2], ['xNIL', 3], ['LAND%', 4], ['WHY HE FITS', 5]].forEach(function (h) { g.fillText(h[0], x + tcol[h[1]], ty + 4); });
    if (!tg.length) { g.font = '32px ' + FONT; g.fillText('no target in reach', x, ty + 60); }
    var foot = footN ? fy0 - 56 : F.y + F.h - 140;   // above the WALK / KEEP lines, else the summary
    tg.forEach(function (e, i) {
      var p = e[1], ry2 = ty + 60 + i * 48; if (ry2 > foot) return;
      chip(g, x, ry2, String(Math.round(p.fv)), 28, p.fv);
      g.font = '34px ' + FONT; g.fillStyle = C.white; g.fillText(fit(g, (p.as ? lab(p.pos) + '>' : '') + lab(e[0]) + ' ' + p.name, tcol[2] - tcol[1] - 24), x + tcol[1], ry2);
      g.font = '30px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, p.team + (p.div ? ' (FCS)' : ''), tcol[3] - tcol[2] - 24), x + tcol[2], ry2);
      g.fillStyle = C.white; g.fillText(money(p.xnil || p.cost), x + tcol[3], ry2);
      g.fillStyle = C.teal; g.fillText(p.land != null ? (p.land < 0.01 ? '<1%' : Math.round(p.land * 100) + '%') : '-', x + tcol[4], ry2);
      g.fillStyle = C.lilac; g.fillText(fit(g, ((p.real || [])[0] || (p.mi != null ? p.mi + ' mi from home' : '')), w - tcol[5]), x + tcol[5], ry2);
    });
    // let walk, retention priorities, then the plan in a line, at the foot
    T.walk = T.walk || [];
    if (T.walk.length) {
      g.font = '40px ' + FONT; g.fillStyle = C.down; g.fillText('WALK', x, fy0);
      g.font = '32px ' + FONT; g.fillStyle = C.white;
      g.fillText(fit(g, T.walk.slice(0, 2).map(function (wk) { return lab(wk.pos) + ' ' + wk.name + ' for ' + lab(wk.forPos) + ' ' + wk.for + ' (frees ' + money(wk.freed) + ')'; }).join('  ·  '), w - 140), x + 120, fy0);
    }
    if ((T.keep || []).length) {
      var ky = fy0 + (T.walk.length ? 46 : 0);
      g.font = '40px ' + FONT; g.fillStyle = C.teal; g.fillText('KEEP', x, ky);
      g.font = '32px ' + FONT; g.fillStyle = C.white;
      g.fillText(fit(g, T.keep.slice(0, 3).map(function (p) { return lab(p.pos) + ' ' + p.name + ' (' + Math.round(p.tp * 100) + '% xfer' + (p.raise ? ', +' + money(p.raise) : '') + ')'; }).join('  ·  '), w - 140), x + 120, ky);
    }
    if (mvs.length) {
      var my = fy0 + (T.walk.length ? 46 : 0) + ((T.keep || []).length ? 46 : 0);
      g.font = '40px ' + FONT; g.fillStyle = C.lilac; g.fillText('MOVE', x, my);
      g.font = '32px ' + FONT; g.fillStyle = C.white; g.fillText(fit(g, mvs.slice(0, 3).join('  ·  '), w - 140), x + 120, my);
    }
    var s = B.summary(T, B.data), last = s[s.length - 1];
    g.font = '32px ' + FONT; g.fillStyle = C.lilac;
    wrap(g, last, w).slice(0, 2).forEach(function (l, i) { g.fillText(l, x, F.y + F.h - 96 + i * 44); });
    return F.canvas;
  }
  // player badges as pixel-art medals: a purple-and-teal ribbon over a medal in the tier's colour, one
  // fillRect per pixel (o outline, h/m/s the tier's highlight, base and shade; r ribbon, t its teal stripe)
  var MEDAL = ['rrt.....trr', '.rrt...trr.', '..rrt.trr..', '...rrtrr...', '...ooooo...', '..ohhmmmo..', '.ohhmmmmso.',
               '.ohmmmmmso.', '.ommmmmmso.', '.ommmmmsso.', '..omsssso..', '...ooooo...'];
  var TIERS = { b: ['BRONZE', '#f0b27a', '#cd7f32', '#8a5222'], s: ['SILVER', '#ffffff', '#c9d1d9', '#8b93a6'],
                g: ['GOLD', '#fff1a8', '#ffd34d', '#c99a1c'], p: ['PLATINUM', '#ffffff', '#b9f2ff', '#5fb8d6'] };
  function medal(g, x, y, tier, u) {
    var t = TIERS[tier], col = { o: C.dark, h: t[1], m: t[2], s: t[3], r: C.title, t: C.teal };
    MEDAL.forEach(function (row, j) { for (var i = 0; i < row.length; i++) { var c = col[row[i]]; if (c) { g.fillStyle = c; g.fillRect(x + i * u, y + j * u, u, u); } } });
    if (tier === 'p') { g.fillStyle = C.white; [[10, 4], [9, 5], [11, 5], [10, 6], [0, 9]].forEach(function (q) { g.fillRect(x + q[0] * u, y + q[1] * u, u, u); }); }
  }
  // the top three badges in a row: medal, then tier over name
  function badgeRows(g, badges, x, y, w) {
    var list = (badges || []).slice(0, 3), cw = w / 3, u = 8;
    list.forEach(function (b, i) {
      var bx = x + (i % 3) * cw, by = y + Math.floor(i / 3) * 130;
      medal(g, bx, by, b[1], u);
      g.font = '36px ' + FONT; g.fillStyle = TIERS[b[1]][2]; g.fillText(TIERS[b[1]][0], bx + 12 * u + 20, by + 30);
      g.font = '44px ' + FONT; g.fillStyle = C.white; g.fillText(fit(g, b[0].toUpperCase(), cw - 12 * u - 40), bx + 12 * u + 20, by + 76);
    });
    return list.length ? Math.ceil(list.length / 3) * 130 + 20 : 0;
  }
  async function buildCard(win, btn) {
    if (window.__arkCfbDetail) await window.__arkCfbDetail();   // role, strengths, concerns and FV inputs (cfb-detail.json)
    var r = (window.__arkCfbRecs || [])[+btn.getAttribute('data-gfx-i')]; if (!r) return null;
    var head = txt(win.querySelector('.win__title-text')).replace(/_$/, '').split('::')[0].trim();
    var F = await frame(2160, 2700, head + ' :: ' + r.name, win.getAttribute('data-gfx-date'),
      window.__arkCfbPid && win.getAttribute('data-cfb') ? SITE + '#' + win.getAttribute('data-cfb') + ':p=' + window.__arkCfbPid(r) : SITE);
    var g = F.g, x = F.x + 40, y = F.y + 70, w = F.w - 80, rep = r.report || {};
    well(g, F.x, F.y, F.w, F.h);
    // photo (framed) at the left, the name line (logo, name), the FV plaque with his place on the board at the right
    var photo = await loadPhoto(r.photo ? 'https://a.espncdn.com/combiner/i?img=' + encodeURIComponent(r.photo.replace(/^https?:\/\/a\.espncdn\.com/, '')) + '&w=700&h=509&scale=crop' : null);
    var px = 400, top = y, PW = 350, PH = 290, tcol = w - px - (r.fv != null ? PW + 36 : 0), bottom = F.y + F.h - 30, dash = '—';
    photoFrame(g, photo, x, y - 60, 370, 400);
    var all = window.__arkCfbRecs || [], peers = all.filter(function (o) { return o.pos === r.pos && o.div === r.div; });
    if (r.fv != null) fvPlaque(g, x + w - PW, y - 60, PW, PH, String(r.fv) + (r.plus ? '+' : ''), r.fv, ['#' + r.ovr + ' of ' + all.length, r.posRank ? r.pos + ' #' + r.posRank + ' of ' + peers.length : '']);
    if (r.fv != null) movePill(g, x + w - PW / 2, y - 60 + PH + 14, typeof r.delta === 'number' ? r.delta : null, PW);
    var logo = await loadImg(r.logo);
    if (logo) drawLogo(g, logo, x + px, y - 48, 96, 96);
    var nx = x + px + (logo ? 120 : 0), ns = 96, nroom = x + px + tcol - nx;
    g.font = ns + 'px ' + FONT; while (ns > 68 && g.measureText(r.name).width > nroom) { ns -= 4; g.font = ns + 'px ' + FONT; }
    g.fillStyle = C.white; g.fillText(fit(g, r.name, nroom), nx, y);
    y += 110;
    g.font = '48px ' + FONT; g.fillStyle = C.teal;
    var ageS = r.age != null ? 'age ' + r.age.toFixed(1) : r.ageEst != null ? 'age ~' + r.ageEst.toFixed(1) : null;
    g.fillText(fit(g, [r.pos + (r.spot ? ' · ' + r.spot : ''), ageS, r.team, r.conf, r.cls].filter(Boolean).join(' · '), tcol), x + px, y);
    y += 76;
    // size and snaps: a fact strip (label lilac, value white)
    var facts = [['HT / WT', r.ht || r.wt ? (r.ht || dash) + ' / ' + (r.wt || dash) : null], ['BMI', r.bmi ? r.bmi.toFixed(1) : null], ['SNAPS', r.snaps ? String(r.snaps) : null],
                 ['SHARE', r.snapShare != null ? Math.round(Math.min(1, r.snapShare) * 100) + '%' : null], ['DRAFT', r.draft27 ? '2027' : null]].filter(function (f) { return f[1]; });
    g.font = '44px ' + FONT; var ix0 = x + px;
    facts.forEach(function (f) {
      var lw = g.measureText(f[0] + ' ').width, vw = g.measureText(f[1]).width; if (ix0 + lw + vw > x + px + tcol) return;
      g.fillStyle = C.lilac; g.fillText(f[0], ix0, y); g.fillStyle = C.white; g.fillText(f[1], ix0 + lw, y); ix0 += lw + vw + 48;
    });
    if (facts.length) y += 66;
    if (rep.role) { g.font = '40px ' + FONT; g.fillStyle = C.lilac; wrap(g, rep.role + (r.arch ? ' · ' + r.arch : ''), tcol).slice(0, 2).forEach(function (l) { g.fillText(l, x + px, y); y += 54; }); }
    // flags: RB role, ARKLIST, riser, availability, position change, FCS move-up, as outlined pills
    var ROLE = { every: 'EVERY DOWN BACK', early: 'EARLY DOWN BACK', third: '3RD DOWN BACK' };
    var multi = (r.multi || []).filter(function (m) { return m.pos !== r.move && !(r.move === 'IOL' && (m.pos === 'G' || m.pos === 'C')); }).map(function (m) { return m.pos; });
    var flags = [[ROLE[r.rbRole], C.teal], [r.star && '⟁ ARKLIST', C.teal], [r.riser && '↗ RISER', '#7dffb0'], [r.inj && r.inj.toUpperCase(), C.down],
                 [r.move && '⇄ ' + r.move, C.lilac], [multi.length && '+ ' + multi.join('/'), C.teal], [r.moveUp && '▲ FBS ' + Math.round(r.up * 100) + '%', C.teal]].filter(function (f) { return f[0]; });
    if (flags.length && y + 30 < top + 340) {
      g.font = '36px ' + FONT; var fx = x + px; y += 6;
      flags.forEach(function (f) { var fw = g.measureText(f[0]).width + 32; if (fx + fw > x + px + tcol) return;
        g.strokeStyle = f[1]; g.lineWidth = 3; g.strokeRect(fx + 1.5, y - 26, fw - 3, 52); g.fillStyle = f[1]; g.fillText(f[0], fx + 16, y + 2); fx += fw + 16; });
    }
    y = top + 360 + 34;
    // the numbers in bands of cells; value columns carry his percentile among the board's players at his position
    function pp(k, v) {
      if (v == null) return { pct: null, good: null };
      var vals = peers.map(function (o) { return o[k]; }).filter(function (q) { return q != null && isFinite(q); }); if (vals.length < 5) return { pct: null, good: null };
      var p = pcPct(vals, v); return { pct: p, good: p };
    }
    function cell(h, t, k, v, sub, color) { var q = k ? pp(k, v) : { pct: null, good: null }; return { h: h, t: t, sub: sub || '', color: color || null, pct: q.pct, good: q.good }; }
    var sg = function (n, dgt) { return (n > 0 ? '+' : n < 0 ? '−' : '') + Math.abs(n).toFixed(dgt); }, pc = function (p) { return Math.round(p * 100) + '%'; };
    var zm = function (n) { return (n < 0 ? '−' : '+') + money(Math.abs(n)); };
    var bands = [
      ['VALUE', [r.statPlus != null && cell('Stat+', String(r.statPlus), 'statPlus', r.statPlus, r.pfn != null ? (r.pfnLabel || 'PFN') + ' ' + r.pfn.toFixed(1) : ''),
                 r.war != null && cell('WAR', (+r.war).toFixed(2), 'war', r.war), r.waa != null && cell('WAA', sg(+r.waa, 2), 'waa', r.waa), r.xv != null && cell('XV', (+r.xv).toFixed(2), 'xv', r.xv)]],
      ['OUTLOOK', [r.on3 != null && cell('On3', String(r.on3), 'on3', r.on3), r.cons != null && cell('Consensus', '#' + r.consRk, null, null, 'avg ' + r.cons.toFixed(1) + ' · ' + r.consN + ' of 10'),
                   r.draftP != null && pcProb(cell('Draft%', pc(r.draftP))), r.transferP != null && pcProb(cell('Xfer%', pc(r.transferP)))]],
      ['NIL', [r.xnil ? cell('xNIL', money(r.xnil), 'xnil', r.xnil) : null, r.ynil != null && cell('yNIL', money(r.ynil)), r.znil != null && cell('zNIL', zm(r.znil), null, null, '', r.znil >= 0 ? C.teal : C.down)]]
    ].map(function (b) { return [b[0], b[1].filter(Boolean)]; }).filter(function (b) { return b[1].length; });
    // what the bottom holds: position change, badges, strengths and concerns, FV inputs
    // the composite's seven feeders, as in the dropdown (the 8th part, frame, is a step in FV, not in the composite);
    // ESPN backups and K/P have no composite
    var comp = r.parts && r.src !== 'espn' && r.pos !== 'K' && r.pos !== 'P';
    var labels = [r.div === 'FCS' ? 'level' : 'talent', 'production', 'age + class', 'breakout', 'stats', 'pedigree', 'context'];
    var parts = comp ? r.parts.slice(0, 7).map(function (v, i) { return [labels[i], v || 0]; }) : [];
    var steps = window.__arkCfbSteps ? window.__arkCfbSteps(r) : null, partsH = inputBarsH(parts.length), half2 = (w - 60) / 2;
    var moveOn = r.move && r.moveWhy, bdg = r.badges && r.badges.length;
    function listH(items) { g.font = '40px ' + FONT; var n = 0; (items || []).forEach(function (it) { n += wrap(g, it, half2 - 56).length * 54 + 14; }); return n; }
    var repH = 86 + Math.min(520, Math.max(listH(rep.plus), listH(rep.minus), 54)) + 10;
    var room = bottom - y - partsH - repH - (moveOn ? 230 : 0) - (bdg ? 200 : 0), U = Math.max(150, Math.min(250, Math.floor((room - bands.length * 80) / Math.max(1, bands.length))));
    var legend = false;
    bands.forEach(function (b) {
      var lg = !legend && b[1].some(function (it) { return it.pct != null; }); if (lg) legend = true;
      cardRule(g, x, y, w, b[0], lg ? 'PCTL OF ' + peers.length + ' ' + (r.div === 'FCS' ? 'FCS ' : '') + r.pos : ''); y += 50;
      y += cellGrid(g, b[1], x, y, w, b[1].length, U, 20) + 30;
    });
    // position change: the projected spot and the model's reason, in a panel under the numbers
    if (moveOn) {
      cardRule(g, x, y, w, 'POSITION CHANGE'); y += 44;
      g.font = '72px ' + FONT; var lab = r.pos + ' → ' + r.move, tx2 = x + 24 + g.measureText(lab).width + 48;
      g.font = '36px ' + FONT;
      var why = wrap(g, r.moveWhy.charAt(0).toUpperCase() + r.moveWhy.slice(1) + '.', x + w - 24 - tx2).slice(0, 3), ph = Math.max(120, 48 + why.length * 48);
      g.fillStyle = C.face; g.fillRect(x, y, w, ph); bevel(g, x, y, w, ph, true, 3);
      g.font = '72px ' + FONT; g.fillStyle = C.white; g.fillText(r.pos, x + 24, y + ph / 2);
      var aw = g.measureText(r.pos + ' ').width; g.fillStyle = C.teal; g.fillText('→ ' + r.move, x + 24 + aw, y + ph / 2);
      g.font = '36px ' + FONT; g.fillStyle = C.lilac;
      why.forEach(function (l, i) { g.fillText(l, tx2, y + ph / 2 - (why.length - 1) * 24 + i * 48); });
      y += ph + 36;
    }
    if (bdg) { cardRule(g, x, y, w, 'BADGES'); y += 50; y += badgeRows(g, r.badges, x, y, w); }
    // strengths and concerns, side by side
    function list(label, items, color, lx, cw, lim) {
      var ly = y + 10;
      g.font = '52px ' + FONT; g.fillStyle = color; g.fillText(label, lx, ly); ly += 72;
      g.font = '40px ' + FONT;
      (items || []).forEach(function (it) {
        var lines = wrap(g, it, cw - 56); if (ly + lines.length * 54 > lim) return;
        g.fillStyle = color; g.fillText(label[0], lx + 4, ly);
        g.fillStyle = C.lilac; lines.forEach(function (l) { g.fillText(l, lx + 56, ly); ly += 54; }); ly += 14;
      });
      if (!(items || []).length) { g.fillStyle = C.lilac; g.fillText('none', lx + 56, ly); }
    }
    list('+ strengths', rep.plus, C.teal, x, half2, bottom - partsH);
    list('− concerns', rep.minus, C.down, x + half2 + 60, half2, bottom - partsH);
    // what drives the grade: each feeder's weighted pull on the composite, pinned to the bottom; at the right the grade
    // the composite gives and the headline after the steps (frame, years, consensus, injury, mean outcome, returns, scale)
    if (parts.length) inputBars(g, x, bottom - partsH + 40, w, 'FV INPUTS', steps && steps.length ? 'GRADE ' + (+steps[0][1]).toFixed(0) + ' → FV ' + r.fv : '', parts, 2, 2, 300);
    return F.canvas;
  }

  // ---- player card for any board (every sport but the CFB board, which has its own): read from the player's table row
  // and, where the board has one, its dropdown (photo, role lines, strengths and concerns, FV inputs, badges). The header
  // carries photo, logo, flag, name, position, team, class and FV; the sorted column is the featured tile with the player's
  // place in the view; every other column is a tile with where the value sits among the rows in view (pNN, 0 = lowest).
  // context columns a card shows as a fact strip under the name (no percentile tile)
  var PC_INFO = /^(age|g|gp|gs|mp|min|toi|snaps|ht|wt|ht \/ wt|yrs|salary|contract|nhl gp|wt\. gp|starts|w-l)$/i;
  // a percentile bar in pixel blocks: 20 cells of 5 points, lit to the value
  function pxBar(g, x, y, w, h, pct, col) {
    var n = 20, gap = Math.max(3, Math.round(h / 4)), cw = (w - (n - 1) * gap) / n, lit = Math.round(pct / 5);
    for (var k = 0; k < n; k++) { g.fillStyle = k < lit ? col : C.dark; g.fillRect(Math.round(x + k * (cw + gap)), y, Math.ceil(cw), h); }
  }
  // percentile tiers, judged the good way round (lower-is-better columns flipped): 90+, 70-89, 30-69, 10-29, under 10.
  // Neutral columns (age, minutes, contract) have no tier: lilac bar, no accent
  var PTIER = [[90, '#7fffd4'], [70, '#3fc6a0'], [30, '#c8c7ff'], [10, '#d887b4'], [0, '#ff9ec7']];
  function tierCol(good) { if (good == null) return null; for (var k = 0; k < PTIER.length; k++) if (good >= PTIER[k][0]) return PTIER[k][1]; return PTIER[PTIER.length - 1][1]; }
  function tierAcc(good) { return good == null || (good >= 30 && good < 70) ? null : tierCol(good); }
  // never on a player card: GAP / xGAP (value minus market or starter, read as noise on a card) and the weekly move
  var PC_DROP = /^(gap|xgap|±|\+\/-|δ|Δ)$/i;
  var PC_SKIP = /^(rk|#|pick|spot|tm)$/i, PC_SUB = /^(pos|position|team|school|club|org|league|lg|conf|class|yr|year|season|plays|tag|stage)$/i;
  var PC_NOPCT = /^(rank|cons|xslot|vrs|ht|wt|ht \/ wt|range|w-l|rec|season line|plays|tag|contract|yrs|last|form|roster|stage)$/i;
  var PC_MARKS = '.gfx-off, .cfb__star, .cfb__carried, .cfb__warin, .cfb__riser, .cfb__injchip, .injtag, .cfb__rbrole, .cfb__medals, .cfb__upchip, .cfb__movechip, .cfb__multichip, .cfb__valuechip, .cfb__reachchip, .cfb__divtag, .pxframe, .cfbst__more, .nflwar__col, .nflwar__tm, .nflwar__rook, .esea-flag, .nbaxpm__tm, svg, img';
  function pcRows(table) { return [].slice.call(table.tBodies[0].rows).filter(function (r) { return !r.hidden && getComputedStyle(r).display !== 'none' && !r.classList.contains('cfb__detail') && r.cells.length > 2; }); }
  // boards that render one page of a longer list hand over every filtered row (table.__gfxAll, built off the page by the
  // board's shortcode) so percentiles and "#k of N" read the whole view, not the 50 rows on screen
  function pcAll(table) { try { if (table.__gfxAll) { var a = table.__gfxAll().filter(function (r) { return !r.classList.contains('cfb__detail') && r.cells.length > 2; }); if (a.length) return a; } } catch (e) {} return pcRows(table); }
  function pcAt(table, rows, row) { var i = pcRows(table).indexOf(row); return table.__gfxAll && i >= 0 && rows.length > pcRows(table).length ? (table.__gfxOff || 0) + i : rows.indexOf(row) >= 0 ? rows.indexOf(row) : i; }
  // share of the other rows below a value, ties at their middle rank
  function pcPct(vals, n) { var b = 0, t = 0; vals.forEach(function (v) { if (v < n) b++; else if (v === n) t++; }); return Math.round(100 * (b + 0.5 * Math.max(0, t - 1)) / Math.max(1, vals.length - 1)); }
  function pcHeads(table) {
    var hc = [].slice.call(table.tHead.rows[0].cells), vis = hc.filter(function (h) { return !h.hidden; }), r0 = pcRows(table)[0];
    return r0 && vis.length < hc.length && r0.cells.length === vis.length ? vis : hc;
  }
  function pcNameAt(heads) { return heads.findIndex(function (h) { return /^(player|goalie|qb|recruit|prospect|name)$/i.test(h); }); }
  // a cell's main text and its small print (the dim splits: raw XPM, 80% range, position rank)
  function pcCell(c) {
    if (!c) return { t: '', sub: '' };
    var cc = c.cloneNode(true); cc.querySelectorAll(PC_MARKS).forEach(function (e) { e.remove(); });
    var subs = [].slice.call(cc.querySelectorAll('.nbaxpm__od, .cfb__dim')).map(function (e) { var s = txt(e); e.remove(); return s; }).filter(Boolean);
    var t = txt(cc).replace(/[▾▴▸★↗]/g, '').trim(), sub = subs.join(' · ');
    if (!t && sub) { t = sub; sub = ''; }
    var col = c.querySelector('.cfb__up, .cfb__down') || (c.classList.contains('cfb__up') || c.classList.contains('cfb__down') ? c : null);
    return { t: t || '—', sub: sub, color: col ? (col.classList.contains('cfb__up') ? C.teal : C.down) : null };
  }
  function pcNum(c, t) {
    var v = c && c.getAttribute('data-v');
    if (v != null && v !== '' && isFinite(+v)) return +v;
    if (!t || /\d\s*-\s*\d/.test(t)) return null;
    var m = String(t).replace(/−/g, '-').replace(/,/g, '').match(/[-+]?\d+(\.\d+)?/); if (!m) return null;
    var n = +m[0], s = String(t).toLowerCase();
    if (/\d\s*m\b/.test(s)) n *= 1e6; else if (/\d\s*k\b/.test(s)) n *= 1e3;
    return n;
  }
  // a bigger copy of a row thumbnail: ESPN combiner, NFL Cloudinary, Transfermarkt, Wikimedia
  function pcBig(src) {
    if (!src || /\/img\/face\.svg/.test(src)) return null;
    if (/on3static\.com\/cdn-cgi\/image\//.test(src)) return src.replace(/\/cdn-cgi\/image\/[^/]+\//, '/cdn-cgi/image/height=640,width=560,quality=85,fit=cover,gravity=top,format=auto/');   // On3 recruit photos: portrait crop at card size
    return src.replace(/([?&])w=\d+&h=\d+/, '$1w=700&h=509').replace(/\/w_\d+\//, '/w_600/').replace(/\/portrait\/(medium|small)\//, '/portrait/big/').replace(/([?&])width=\d+/, '$1width=600');
  }
  function pcBadges(els) {
    var out = [], seen = {};
    els.forEach(function (el) {
      if (!el) return;
      // [[name, tier]] on the row (data-badges), or the dropdown's chips (span.cfb__bdg--<tier>, name in data-n)
      var raw = el.getAttribute && el.getAttribute('data-badges');
      if (raw) { try { JSON.parse(raw).forEach(function (b) { if (!seen[b[0]]) { seen[b[0]] = 1; out.push([b[0], b[1]]); } }); } catch (e) {} }
      [].slice.call(el.querySelectorAll('.cfb__bdg')).forEach(function (s) {
        var m = s.className.match(/cfb__bdg--([bsgp])\b/); if (!m) return;
        var n = s.getAttribute('data-n') || txt(s).replace(/^\S+\s+/, ''); if (n && !seen[n]) { seen[n] = 1; out.push([n, m[1]]); }
      });
    });
    var rank = { p: 0, g: 1, s: 2, b: 3 };
    return out.sort(function (a, b) { return rank[a[1]] - rank[b[1]]; });
  }
  // the row's dropdown: open it for the card when it is closed (the name button toggles it), and close it after
  function isDet(el) { return !!el && /(^|\s)\w+__detail(\s|$)/.test(el.className); }
  async function pcDetail(row) {
    var nx = row.nextElementSibling, table = row.closest('table');
    if (isDet(nx)) return { el: nx, opened: false };
    if (!pdOwn(table)) { var el = pdOpen(row); return { el: el, opened: true, close: function () { el.remove(); } }; }
    var who = row.querySelector('button.cfb__who');
    if (!who && table.matches('.cfbm:not(.cbbm), .cfbrc')) who = row.cells[1];   // the mock and recruit tables open on a row click
    if (!who) return { el: null };
    who.click();
    for (var k = 0; k < 40; k++) { nx = row.nextElementSibling; if (isDet(nx)) break; await new Promise(function (r) { setTimeout(r, 50); }); }
    return isDet(nx) ? { el: nx, opened: true, close: function () { if (row.nextElementSibling === nx) who.click(); } } : { el: null };
  }
  var NBAX = null;
  function nbaXpm(w) { return NBAX || (NBAX = fetch(w.getAttribute('data-src') + w.getAttribute('data-cur') + '.json').then(function (r) { return r.json(); }).catch(function () { NBAX = null; return null; })); }
  // ---- a sparse card's spare room: the season line as stat cells, the player's row on the page's other tables, FV outlook
  // a stat in a line of text: "1793 pass yds", "25 mpg" (number, label) or "BPM +2.0 (−0.4 O, +2.3 D)", "3P 33.3% on 3"
  var PC_NUMS = '[-+−~]?\\d[\\d,]*(?:\\.\\d+)?%?';
  var PC_ST1 = new RegExp('^(' + PC_NUMS + ')\\s+([A-Za-z][A-Za-z/%+.\' -]{0,15})$');
  var PC_ST2 = new RegExp('^([A-Za-z0-9][\\w/%+.\'-]{0,11}(?: [A-Za-z/%+.-]{1,8})?)\\s+(' + PC_NUMS + ')(?:\\s+(.{1,24}))?$');
  var PC_STNO = /^(age|lbs?|in|cm|kg)$|\bno\.?$/i;   // size and age are in the header already; "No. 1" is a rank in prose
  function pcStats(s) {
    var prot = String(s).replace(/\([^)]*\)/g, function (m) { return m.replace(/,/g, '\u0001'); });
    var parts = prot.split(/(\s+·\s+|,\s+|;\s+)/), items = [], keep = [], run = '', back = function (t) { return String(t || '').replace(/\u0001/g, ','); };
    for (var i = 0; i < parts.length; i += 2) {
      var p = parts[i].trim(), m1 = p.match(PC_ST1), m2 = !m1 && p.match(PC_ST2), it = null;
      if (m1 && !PC_STNO.test(m1[2].trim())) it = { h: m1[2].trim(), t: m1[1] };
      else if (m2 && /[a-z]/i.test(m2[1]) && !PC_STNO.test(m2[1])) it = { h: m2[1], t: m2[2], sub: back(m2[3]).replace(/^\((.*)\)$/, '$1') };
      if (it) { items.push(it); if (run) { keep.push(back(run)); run = ''; } }
      else if (p) run += (run ? parts[i - 1] : '') + parts[i];
    }
    if (run) keep.push(back(run));
    return { items: items, rest: keep.join(' · ') };
  }
  // the first sentence of a line that reads as three or more stats: a group of cells, and what is left of the line
  function pcStatText(text, title) {
    var ss = String(text || '').split(/\.\s+/), sen = [];
    ss.forEach(function (s) { if (sen.length && /\bNo$/i.test(sen[sen.length - 1])) sen[sen.length - 1] += '. ' + s; else sen.push(s); });
    var group = null, rest = [];
    sen.forEach(function (s) {
      s = s.replace(/\.$/, '');
      if (!group) {
        var m = s.match(/^([^:·]{2,40}):\s+(.+)$/), st = pcStats(m ? m[2] : s);
        if (st.items.length >= 3) { group = { title: m ? m[1] : title || 'stats', items: st.items }; if (st.rest) rest.push(st.rest); return; }
      }
      if (s) rest.push(s);
    });
    return { group: group, rest: rest.length ? rest.join('. ') + (/\.\s*$/.test(text) ? '.' : '') : '' };
  }
  var PC_XSKIP = /mock|backup|arklist|breakout|standout|next up|past|^v\d+$|game|ranking|odds|lineup|on\/off|fv model/i;
  // the player's row on the page's other player tables (same name by the shared rules, same team): its columns the card lacks
  function pcXGroups(table, name, team, pos, shown) {
    var nk = window.arkName ? window.arkName.key : pdNorm, key = nk(name), tk = function (s) { return String(s || '').toUpperCase().split('/').map(function (x) { return x.trim(); }).filter(Boolean); };
    var mine = tk(team), seen = {}, out = [];
    if (!key) return out;
    document.querySelectorAll('.win table').forEach(function (t) {
      if (t === table || !t.tHead || !t.tHead.rows[0] || !t.tBodies[0]) return;
      var w2 = t.closest('.win'), tab = (t.closest('[data-tab]') || w2 || { getAttribute: function () { return ''; } }).getAttribute('data-tab') || '';
      var title = txt(w2 && w2.querySelector('.win__title-text')).replace(/_$/, '').split('::')[0].trim();
      if (PC_XSKIP.test(tab) || PC_XSKIP.test(title) || !title || seen[title]) return;
      var hc = pcHeads(t), hs = hc.map(txt), k = pcNameAt(hs); if (k < 0) return;
      var rs = pcRows(t), r = rs.find(function (x) { return nk(pcName(x, k)) === key; }); if (!r) return;
      var ti = hs.findIndex(function (h) { return TEAM_COL.test(h); });
      if (ti >= 0 && mine.length) { var th = tk(pcCell(r.cells[ti]).t); if (th.length && !th.some(function (x) { return mine.indexOf(x) >= 0; })) return; }
      var items = [];
      hs.forEach(function (h, i) {
        var lc = h.toLowerCase();
        if (i === k || i === ti || !h || shown[lc] || PC_SKIP.test(h) || PC_DROP.test(h) || PC_SUB.test(h) || FV_COL.test(h) || (hc[i] && hc[i].hidden) || !r.cells[i] || r.cells[i].hidden) return;
        var c = pcCell(r.cells[i]); if (c.t === '—' || c.t.length > 12) return;
        var n = PC_NOPCT.test(h) || PC_INFO.test(h) ? null : pcNum(r.cells[i], c.t), pct = null;
        if (n != null) {
          var vals = pcAll(t).map(function (x) { var cc = x.cells[i]; return cc ? pcNum(cc, pcCell(cc).t) : null; }).filter(function (v) { return v != null; });
          if (vals.length >= 5) pct = pcPct(vals, n);
        }
        items.push({ h: h, t: c.t, color: c.color, pct: pct, good: pct == null || PD_NEUTRAL.test(h) ? null : PD_LOWER.test(h) ? 100 - pct : pct });
      });
      if (items.length < 2) return;
      items.forEach(function (it) { shown[it.h.toLowerCase()] = 1; });
      // a table named for his position (QB value, goalies) comes first
      var pk = String(pos || '').replace(/[^A-Z]/g, ''), pw = pk && new RegExp('(^|[^A-Z])' + pk + '([^A-Z]|$)');
      seen[title] = 1; out.push({ title: title, items: items, pri: pw && (pw.test(hs[k]) || pw.test(title)) ? 1 : 0 });
    });
    return out;
  }
  // the dropdown's FV outlook (fvoutlook.html): 80% range, then each tier's odds
  function pcFvo(d) {
    var f = d && d.querySelector('.fvo'); if (!f) return null;
    var items = [], rg = f.querySelector('.fvo__head b');
    if (rg) items.push({ h: '80% range', t: txt(rg) });
    [].slice.call(f.querySelectorAll('.fvo__key li')).forEach(function (li) {
      var b = txt(li.querySelector('b')), lab = txt(li).replace(b, '').trim().split(' '), p = parseFloat(b.replace(/[<>]/g, ''));
      items.push({ h: lab[0], t: b, sub: lab.slice(1).join(' '), pct: isFinite(p) ? p : null });
    });
    return items.length >= 3 ? { title: 'FV outlook', items: items } : null;
  }
  // ---- pieces the player, CFB and team cards share ----
  // a band's rule: label, a dark line, a small label at the right end
  function cardRule(g, x, y, w, label, right) {
    var lw = 0, rw = 0;
    if (label) { g.font = '40px ' + FONT; g.fillStyle = C.lilac; g.fillText(label, x, y); lw = g.measureText(label).width + 24; }
    if (right) { g.font = '28px ' + FONT; g.fillStyle = C.lilac; rw = g.measureText(right).width + 24; g.fillText(right, x + w - rw + 24, y); }
    g.fillStyle = C.dark; g.fillRect(x + lw, y - 1, w - lw - rw, 3);
  }
  // a diverging bar in pixel blocks: n cells each side of the middle, lit outward to |v| / max
  function pxDiv(g, x, cy, w, h, v, max, n) {
    n = n || 10; var gap = 4, mid = Math.round(x + w / 2), cw = (w / 2 - 8 - (n - 1) * gap) / n, lit = v ? Math.max(1, Math.round(Math.min(1, Math.abs(v) / (max || 1)) * n)) : 0, top = Math.round(cy - h / 2);
    for (var k = 0; k < n; k++) {
      g.fillStyle = v < 0 && k < lit ? C.down : C.dark; g.fillRect(Math.round(mid - 8 - (k + 1) * cw - k * gap), top, Math.ceil(cw), h);
      g.fillStyle = v > 0 && k < lit ? C.teal : C.dark; g.fillRect(Math.round(mid + 8 + k * (cw + gap)), top, Math.ceil(cw), h);
    }
    g.fillStyle = C.lilac; g.fillRect(mid - 2, top - 6, 4, h + 12);
  }
  // inputs (FV drivers, rating inputs): label, diverging pixel bar, signed value, in two columns under a rule
  function inputBars(g, x, by, w, title, right, ps, max, dec, labW) {
    var cw2 = (w - 80) / 2, perCol = Math.ceil(ps.length / 2);
    cardRule(g, x, by, w, title, right);
    ps.forEach(function (p, i) {
      var cx = x + Math.floor(i / perCol) * (cw2 + 80), yy = by + 76 + (i % perCol) * 60, v = p[1];
      g.font = '36px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, p[0], labW - 20), cx, yy);
      pxDiv(g, cx + labW, yy, cw2 - labW - 150, 24, v, max);
      var lab = (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(dec); g.fillStyle = v < 0 ? C.down : v > 0 ? C.white : C.lilac; g.fillText(lab, cx + cw2 - g.measureText(lab).width, yy);
    });
  }
  function inputBarsH(n) { return n ? 96 + Math.ceil(n / 2) * 60 : 0; }
  // one stat cell: label (pNN at its right, in the tier's colour), value, small print, a pixel bar. A probability column
  // (it.prob) draws its own value on the bar, in lilac; the sorted column (it.key) is outlined teal.
  function statCell(g, it, x, y, w, h) {
    var s = Math.max(0.6, Math.min(1.5, h / 200)), pad = Math.round(20 + 4 * Math.min(1, s)), tc = tierCol(it.good) || C.lilac;
    g.fillStyle = C.face; g.fillRect(x, y, w, h); bevel(g, x, y, w, h, true, 3);
    if (it.key) { g.strokeStyle = C.teal; g.lineWidth = 4; g.strokeRect(x + 6, y + 6, w - 12, h - 12); }
    var ls = Math.round(Math.max(26, 34 * Math.min(s, 1.15))), pw = 0; g.font = ls + 'px ' + FONT;
    if (it.pct != null && it.prob == null) { var pt = 'p' + it.pct; pw = g.measureText(pt).width + 16; g.fillStyle = tc; g.fillText(pt, x + w - pad - pw + 16, y + pad + ls / 2); }
    g.fillStyle = it.key ? C.teal : C.lilac; g.fillText(fit(g, capHead(it.h), w - 2 * pad - pw), x + pad, y + pad + ls / 2);
    var bar = it.pct != null || it.prob != null, bh = bar ? Math.max(10, Math.round(14 * s)) : 0, ss = it.sub ? Math.round(Math.max(24, 28 * Math.min(s, 1.15))) : 0;
    var top = y + pad + ls + 4, bot = y + h - pad - (bar ? bh + 8 : 0) - (ss ? ss + 6 : 0) - (it.reserve || 0), vs = Math.max(30, Math.min(Math.round(84 * s), Math.round((bot - top) * 0.95)));
    g.font = vs + 'px ' + FONT; while (vs > 30 && g.measureText(it.t).width > w - 2 * pad) { vs -= 4; g.font = vs + 'px ' + FONT; }
    g.fillStyle = it.color || C.white; g.fillText(fit(g, it.t, w - 2 * pad), x + pad, Math.round((top + bot) / 2) + 2);
    if (ss) { g.font = ss + 'px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, it.sub, w - 2 * pad), x + pad, bot + ss / 2 + 4); }
    if (bar) pxBar(g, x + pad, y + h - pad - bh, w - 2 * pad, bh, it.prob != null ? it.prob : it.pct, it.prob != null ? C.lilac : tc);
  }
  // a row-major grid of stat cells: the last row's cells widen to fill it
  function cellGrid(g, items, x, y, w, cols, h, gap) {
    var rows = Math.ceil(items.length / cols);
    items.forEach(function (it, k) {
      var r = Math.floor(k / cols), n = r === rows - 1 ? items.length - r * cols : cols, cw = (w - (n - 1) * gap) / n;
      statCell(g, it, Math.round(x + (k % cols) * (cw + gap)), y + r * (h + gap), Math.round(cw), h);
    });
    return rows * (h + gap) - gap;
  }
  // FV outlook: the 80% range, then each tier's odds as a column of pixel blocks (the likeliest tier teal)
  function fvoBand(g, gp, x, y, w, h) {
    var rg = gp.items[0] && /range/i.test(gp.items[0].h) ? gp.items[0] : null, tiers = rg ? gp.items.slice(1) : gp.items, lw = rg ? Math.round(w * 0.2) : 0;
    if (rg) statCell(g, { h: rg.h, t: rg.t }, x, y, lw - 16, h);
    var n = tiers.length, cw = (w - lw - (n - 1) * 16) / n, top = Math.max.apply(null, tiers.map(function (t) { return t.pct || 0; })) || 1, mx = Math.max(top, gp.max || 0), NB = gp.max ? 8 : 6;
    tiers.forEach(function (t, k) {
      var cx = Math.round(x + lw + k * (cw + 16)), hot = (t.pct || 0) === top, pad = 22, cwi = Math.round(cw);
      g.fillStyle = C.face; g.fillRect(cx, y, cwi, h); bevel(g, cx, y, cwi, h, true, 3);
      g.font = '32px ' + FONT; g.fillStyle = C.lilac; g.fillText(capHead(t.h), cx + pad, y + pad + 16);
      g.font = '44px ' + FONT; g.fillStyle = hot ? C.teal : C.white; g.fillText(t.t, cx + cwi - pad - g.measureText(t.t).width, y + pad + 18);
      var sy = y + pad + 52, sb = y + h - pad - (t.sub ? 38 : 0), bh = Math.floor((sb - sy - (NB - 1) * 5) / NB), lit = t.pct ? Math.max(1, Math.round(t.pct / mx * NB)) : 0;
      for (var b = 0; b < NB; b++) { g.fillStyle = NB - b <= lit ? (hot ? C.teal : C.lilac) : C.dark; g.fillRect(cx + pad, sy + b * (bh + 5), cwi - 2 * pad, bh); }
      if (t.sub) { g.font = '26px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, t.sub, cwi - 2 * pad), cx + pad, y + h - pad - 10); }
    });
  }
  // the FV plaque at a card's top right: the chip in the site's colours, then up to two small lines (place on the board)
  function fvPlaque(g, qx, qy, PW, PH, fvT, fvN, ls) {
    var qc = qx + PW / 2; ls = ls.filter(Boolean);
    g.fillStyle = C.face; g.fillRect(qx, qy, PW, PH); bevel(g, qx, qy, PW, PH, true, 6);
    g.textAlign = 'center'; g.font = '36px ' + FONT; g.fillStyle = C.lilac; g.fillText('FV', qc, qy + 40);
    g.textAlign = 'left'; g.font = '104px ' + FONT; var cw0 = g.measureText(fvT).width + 104 * 0.6; chip(g, Math.round(qc - cw0 / 2), qy + 134, fvT, 104, fvN);
    g.textAlign = 'center'; g.font = '32px ' + FONT; g.fillStyle = C.lilac;
    ls.slice(0, 2).forEach(function (l, i) { g.fillText(fit(g, l, PW - 30), qc, qy + (ls.length > 1 ? 226 + i * 36 : 240)); });
    g.textAlign = 'left';
  }
  // the weekly move under a plaque: a raised tab with a pixel arrow, teal up, pink down; nothing without a prior snapshot or a change
  function movePill(g, cx, y, d, pw) {
    if (typeof d !== 'number' || !isFinite(d) || !d) return;
    var up = d > 0, col = up ? C.teal : C.down, n = String(Math.abs(d)), u = 7, ph = 68, qx = Math.round(cx - pw / 2);
    g.fillStyle = C.face; g.fillRect(qx, y, pw, ph); bevel(g, qx, y, pw, ph, true, 6);
    g.font = '52px ' + FONT; var nw = g.measureText(n).width, cw = 7 * u + 16 + nw, ax = Math.round(cx - cw / 2), ay = y + Math.round((ph - 4 * u) / 2);
    g.fillStyle = col;
    for (var i = 0; i < 4; i++) { var k = up ? i : 3 - i; g.fillRect(ax + (3 - k) * u, ay + i * u, (2 * k + 1) * u, u); }
    var ta = g.textAlign; g.textAlign = 'left'; g.fillText(n, ax + 7 * u + 16, y + ph / 2 + 3); g.textAlign = ta;
  }
  // a board row's weekly move (scripts/board_moves.py, partials/wkfv.html / wkrk.html: the ± or Δ cell's data-v); null when the
  // column is hidden (past seasons), the player is new or the board has no week yet
  function pcMove(row) {
    var t = row && row.closest('table'); if (!t || !t.tHead) return null;
    var hc = pcHeads(t), i = hc.findIndex(function (h) { return !h.hidden && /^(±|Δ)$/.test(txt(h)); }), c = i >= 0 && row.cells[i];
    if (!c || c.hidden) return null;
    var v = c.getAttribute('data-v'); return v != null && v !== '' && isFinite(+v) && +v ? +v : null;
  }
  // a bare dash is an empty cell; a probability column ("NBA%": 99%) is its own bar
  var PC_ORD = /^(rd|round|blend|conv|pred|pick|str|role)$/i;   // picks, rounds and depth-chart strings: no percentile
  function pcDash(t) { return /^[—–−-]$/.test(String(t).trim()); }
  function pcProb(it) { if (/%$/.test(it.h) && /^[<>~]?\d+(\.\d+)?%$/.test(it.t)) { it.prob = parseFloat(it.t.replace(/[<>~]/g, '')); it.good = null; } return it; }
  // a card's tiles in bands by what they measure; a column no band claims stays in the board's own band
  var PC_CATS = [['VALUE', /^(war|waa|war\/17|vorx|gar|par|tgar|xv|av|st|ark|elo|rank|13wk|peak|[rp]?xpm|x?bpm|dpm|hpm|\/90|[rp]xp\/60|gar\/90|war\/1k|nhle|stat\+|pts \/ gsax|gsax\/gp|pts\/g|rating|epa\/play|on xgd|waa\/fs|gar\/60|p\/90|r?pa|raa)$/i],
                 ['SPLITS', /^(o-xpm|d-xpm|off|def|hard|clay|grass|spw\+|rpw\+)$/i], ['PROJECTION', /^(proj|1y|3y|pwar|next|6m)$/i],
                 ['ODDS', /%$/], ['MARKET', /^(salary|xaav|surplus|apy|cap hit|xmv|tm|value|xnil|ynil|znil|contract|yrs)$/i]];
  function pcBands(tiles) {
    var by = {}, rest = [];
    tiles.forEach(function (t) { var c = PC_CATS.find(function (c) { return c[1].test(t.h) && (c[0] !== 'ODDS' || t.prob != null); }); if (c) (by[c[0]] = by[c[0]] || []).push(t); else rest.push(t); });
    var out = [];
    PC_CATS.forEach(function (c) { var l = by[c[0]]; if (!l) return; if (l.length < 2) rest = rest.concat(l); else out.push({ title: c[0], items: l, wgt: 1 }); });
    if (!out.length) return rest.length ? [{ title: '', items: tiles, wgt: 1 }] : [];
    if (rest.length === 1) { out[0].items = out[0].items.concat(rest); rest = []; }
    if (rest.length) { rest.sort(function (a, b) { return a.i - b.i; }); out.push({ title: '', items: rest, wgt: 1 }); }
    return out;
  }
  function pcCols(n, compact) { return compact ? (n <= 6 ? Math.max(n, 3) : n <= 8 ? 4 : 6) : n <= 5 ? n : n === 6 ? 3 : n <= 8 ? 4 : n <= 10 ? 5 : 6; }
  // a subset table's own columns (pick, drafting team, salary ...) as cells, with their place among its rows
  function pcOwn(row, shown) {
    var t = row.closest('table'), hc = pcHeads(t), hs = hc.map(txt), k = pcNameAt(hs), items = [], two = hs.some(function (h) { return /^(school|club|org)$/i.test(h); });
    hs.forEach(function (h, i) {
      var lc = h.toLowerCase(), isTeam = /^team$/i.test(h) && two;
      if (i === k || !h || (shown[lc] && !isTeam) || /^(rk|#|tm)$/i.test(h) || PC_DROP.test(h) || (PC_SUB.test(h) && !isTeam) || FV_COL.test(h) || (hc[i] && hc[i].hidden) || !row.cells[i] || row.cells[i].hidden) return;
      var c = pcCell(row.cells[i]); if (c.t === '—' || pcDash(c.t) || c.t.length > 16) return;
      var n = PC_NOPCT.test(h) || PC_INFO.test(h) || PC_SKIP.test(h) || PC_ORD.test(h) || isTeam ? null : pcNum(row.cells[i], c.t), pct = null;
      if (n != null) {
        var vals = pcAll(t).map(function (x) { var cc = x.cells[i]; return cc ? pcNum(cc, pcCell(cc).t) : null; }).filter(function (v) { return v != null; });
        if (vals.length >= 5) pct = pcPct(vals, n);
      }
      items.push(pcProb({ i: i, h: h, t: c.t, sub: /\d/.test(c.sub) && c.sub.length <= 18 ? c.sub : '', color: c.color, pct: pct, good: pct == null || PD_NEUTRAL.test(h) ? null : PD_LOWER.test(h) ? 100 - pct : pct }));
    });
    return items;
  }
  // numbers a line of text carries, for telling when it only repeats what the card already shows
  function pcNumsIn(s) { return (String(s).replace(/−/g, '-').match(/\d[\d,]*(?:\.\d+)?/g) || []).map(function (n) { return String(parseFloat(n.replace(/,/g, ''))); }); }
  // CBB comps (cbb.js fillComps, static/data/cbb-comps.json; internationals cbb-comps-intl.json): the 100-nearest mix and the 3 nearest who reached the NBA
  async function pcComps(win, d) {
    var el = d && d.querySelector('[data-comps]'), src = win.getAttribute('data-cbb-src'); if (!el || !src || !window.__arkJson) return null;
    var cd = await window.__arkJson(src.replace(/cbb-all\.json.*$/, el.hasAttribute('data-comps-intl') ? 'cbb-comps-intl.json' : 'cbb-comps.json')).catch(function () { return null; });
    var e = cd && cd.players[el.getAttribute('data-comps')]; if (!e || !e.length) return null;
    var lg = {}; (window.__arkCbbRecs || []).forEach(function (r) { if (r.logo && r.team && !lg[r.team]) lg[r.team] = r.logo; });
    var near = e.slice(0, -1).map(function (x) { return cd.pool[x[0]]; }).filter(Boolean).slice(0, 3);
    var logos = await Promise.all(near.map(function (c) { return lg[c[1]] ? loadImg(lg[c[1]]) : null; }));
    return { mix: e[e.length - 1], near: near, logos: logos };
  }
  var COMP_H = 156, COMP_ROLE = { 'reached the NBA': 'NBA', 'bench, 100+ games': 'bench', 'rotation, 3+ seasons': 'rotation', '2+ seasons as a starter': 'starter', '4+ seasons as a starter': 'starter 4+', 'All-Star or 6+ seasons as a starter': 'All-Star' };
  function pcCompsH(cp) { return cp ? 50 + COMP_H + 30 : 0; }
  // the comps strip: three share cells (NBA, starter FV 45+, All-Star level FV 60+), then the nearest NBA comps
  function compStrip(g, cp, x, y, w) {
    var m = cp.mix, gap = 20, h = COMP_H, sw = 200, shares = [['NBA', m[1]], ['FV 45+', m[2]], ['FV 60+', m[3]]];
    cardRule(g, x, y, w, 'COMPS', m[0] + ' NEAREST'); y += 50;
    shares.forEach(function (s, k) { var v = Math.round(s[1] * 100); statCell(g, { h: s[0], t: v + '%', prob: v }, x + k * (sw + gap), y, sw, h); });
    var cx0 = x + 3 * (sw + gap), n = cp.near.length; if (!n) return;
    var cw = Math.floor((x + w - cx0 - (n - 1) * gap) / n);
    cp.near.forEach(function (c, k) {
      var cx = cx0 + k * (cw + gap), pad = 22, img = cp.logos[k], tx = cx + pad + (img ? 84 : 0), tw = cx + cw - pad - tx;
      g.fillStyle = C.face; g.fillRect(cx, y, cw, h); bevel(g, cx, y, cw, h, true, 3);
      if (img) drawLogo(g, img, cx + pad, y + pad, 64, 64);
      g.font = '40px ' + FONT; g.fillStyle = C.white; g.fillText(fit(g, c[0], tw), tx, y + pad + 18);
      g.font = '28px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, [c[1], String(c[2] - 1).slice(2) + '-' + String(c[2]).slice(2), c[3]].filter(Boolean).join(' '), tw), tx, y + 76);
      var by = y + h - 40, fvT = String(Math.round(c[4])); g.font = '40px ' + FONT; var chw = chip(g, cx + pad, by, fvT, 40, c[4]), rx = cx + pad + chw + 16;
      var pk = c[6] ? '#' + c[6] + " '" + String(c[7]).slice(2) : 'undrafted'; g.font = '32px ' + FONT; g.fillStyle = C.white; g.fillText(pk, rx, by); rx += g.measureText(pk).width + 16;
      g.font = '28px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, COMP_ROLE[c[5]] || c[5], cx + cw - pad - rx), rx, by);
    });
  }
  // recruit card: ARK stars, industry stars and the destination calls (On3/Rivals expert picks, ARK lean, CBB On3 RPM)
  // from the row's data-rc (layouts/partials/rcgfx.html)
  var RC_H = 210;   // the STARS · PICKS band's height: fixed, so a full card squeezes the other bands, not this one
  var STAR7 = ['...#...', '...#...', '#######', '.#####.', '..###..', '.##.##.', '.#...#.'];
  function pxStar(g, x, y, sz, fill, col) {   // fill: 0 empty, .5 left half, 1 full
    var u = Math.max(2, Math.floor(sz / 7));
    STAR7.forEach(function (r, j) { for (var i = 0; i < 7; i++) if (r[i] === '#') { g.fillStyle = fill >= 1 || (fill > 0 && i < 4) ? col : C.dark; g.fillRect(x + i * u, y + j * u, u, u); } });
    return 7 * u;
  }
  async function rcItems(rc) {
    if (!rc) return null;
    var items = [], logo = function (id) { return id ? loadImg('{{ "img/cfb/logos/" | relURL }}' + id + '.png') : Promise.resolve(null); };
    if (rc.a) items.push({ h: 'ARK', stars: rc.a, col: C.teal });
    items.push({ h: 'INDUSTRY', stars: rc.s || 0, plus: !!rc.p, col: C.lilac });
    if (rc.e) items.push({ h: 'EXPERTS', t: rc.e[0], sub: rc.e[1] + ' of ' + rc.e[2], prob: rc.e[1] / rc.e[2] * 100, img: await logo(rc.e[3]) });
    else if (rc.r) items.push({ h: 'ON3 RPM', t: rc.r[0], sub: Math.round(rc.r[1]) + '%', prob: rc.r[1] });
    if (rc.l) items.push({ h: 'ARK LEAN', t: rc.l[0], sub: rc.l[1] + '%', prob: rc.l[1], img: await logo(rc.l[2]) });
    return items;
  }
  function rcBand(g, items, x, y, w, h, gap) {
    var n = items.length, cw = (w - (n - 1) * gap) / n;
    items.forEach(function (it, k) {
      var cx = Math.round(x + k * (cw + gap)), cwi = Math.round(cw), pad = 22;
      g.fillStyle = C.face; g.fillRect(cx, y, cwi, h); bevel(g, cx, y, cwi, h, true, 3);
      g.font = '34px ' + FONT; g.fillStyle = C.lilac; g.fillText(it.h, cx + pad, y + pad + 17);
      if (it.stars != null) {
        var five = Math.min(it.stars, 5), plus = it.stars > 5 || it.plus, room = cwi - 2 * pad - (plus ? 40 : 0);
        var sz = Math.min(Math.floor((room - 4 * 10) / 5 / 7) * 7, Math.floor((h - 2 * pad - 50) / 7) * 7, 70), sy = Math.round(y + 50 + (h - 50 - sz) / 2);
        if (!it.stars) { g.font = Math.min(84, h - 90) + 'px ' + FONT; g.fillStyle = C.lilac; g.fillText('NR', cx + pad, sy + sz / 2); return; }
        for (var i = 0; i < 5; i++) pxStar(g, cx + pad + i * (sz + 10), sy, sz, five - i >= 1 ? 1 : five - i > 0 ? 0.5 : 0, it.col);
        if (plus) { g.font = Math.round(sz * 1.1) + 'px ' + FONT; g.fillStyle = C.lilac; g.fillText('+', cx + pad + 5 * (sz + 10) - 2, sy + sz / 2 + 2); }
        return;
      }
      var bh = 14, ly = y + h - pad - bh, lz = Math.min(96, h - 2 * pad - 50 - bh - 50), tx = cx + pad;
      if (it.img && lz >= 40) { drawLogo(g, it.img, tx, y + 50 + (ly - 44 - y - 50 - lz) / 2, lz, lz); tx += lz + 18; }
      var vs = Math.min(64, Math.max(34, lz)); g.font = vs + 'px ' + FONT; while (vs > 34 && g.measureText(it.t).width > cx + cwi - pad - tx) { vs -= 4; g.font = vs + 'px ' + FONT; }
      g.fillStyle = C.white; g.fillText(fit(g, it.t, cx + cwi - pad - tx), tx, y + 50 + (ly - 44 - y - 50) / 2);
      g.font = '36px ' + FONT; g.fillStyle = C.teal; g.fillText(it.sub, cx + pad, ly - 26);
      pxBar(g, cx + pad, ly, cwi - 2 * pad, bh, it.prob, C.lilac);
    });
  }
  // ---- moves (scripts/player_moves.py -> static/data/moves/<sport>.json): commitments, flips, visits, portal moves and pro
  // transactions, fetched on the first card. A recruit keeps the rows of his class; anyone else the chain of teams ending at his.
  var MV_DATA = {}, MV_SPORT = { cfb: 'cfb', cbb: 'cbb', nfl: 'nfl', nba: 'nba', nhl: 'nhl', hockey: 'nhl', soccer: 'soccer', u22: 'soccer' };
  var MV_H = 190, MV_MON = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];
  var MV_LAB = { commit: ['COMMIT', 'teal'], decommit: ['DECOMMIT', 'down'], flip: ['FLIP', 'white'], sign: ['SIGNED', 'teal'], resign: ['RE-SIGNED', 'teal'], extend: ['EXTENSION', 'teal'], reclass: ['RECLASS', 'lilac'],
                 visit: ['OFFICIAL VISIT', 'lilac'], unofficial: ['VISIT', 'lilac'], portal: ['PORTAL', 'down'], transfer: ['TRANSFER', 'white'], trade: ['TRADE', 'white'], release: ['RELEASED', 'down'], claim: ['CLAIMED', 'teal'] };
  function mvDate(d) { var m = String(d || '').match(/^(\d{4})(?:-(\d\d)-(\d\d))?/); return !m ? '' : m[2] ? MV_MON[+m[2] - 1] + ' ' + (+m[3]) + ' \'' + m[1].slice(2) : m[1]; }
  async function pcMoves(win, name, o) {
    var sp = MV_SPORT[SITE.split('/').pop()], nk = window.arkName; if (!sp || !nk || !name) return [];
    var d = await (MV_DATA[sp] || (MV_DATA[sp] = fetch('{{ "data/moves/" | relURL }}' + sp + '.json').then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; })));
    var ev = d && d.p && d.p[nk.key(name)]; if (!ev) return [];
    var tk = function (i) { return i >= 0 ? nk.teamKey(d.t[i]) : ''; }, vis = /^(visit|unofficial)$/, out = [];
    if (o.cls) {
      var from = (o.cls - 4) + '-01-01';
      out = ev.filter(function (e) { return (e[4] ? e[4] === o.cls : /^(commit|decommit|flip|sign|reclass)$/.test(e[1]) && (e[0] || '') >= from) && (o.open || !vis.test(e[1])); });
      if (out.some(function (e) { return e[1] === 'visit'; })) out = out.filter(function (e) { return e[1] !== 'unofficial'; });   // officials when he has taken any
    } else if (o.team) {
      var cur = nk.teamKey(String(o.team).split('/').pop().trim());
      for (var i = ev.length - 1; i >= 0 && cur; i--) {
        var e = ev[i]; if (vis.test(e[1])) continue;
        if (e[3] >= 0 && tk(e[3]) === cur) { out.unshift(e); cur = e[2] >= 0 ? tk(e[2]) : e[1] === 'commit' ? '' : cur; }
        else if (e[3] < 0 && e[2] >= 0 && tk(e[2]) === cur) out.unshift(e);
      }
    }
    out = out.slice(-6);
    var tpl = win.getAttribute('data-gfx-logo'), side = async function (i) {
      if (i < 0) return null; var n = d.t[i], src = d.l[i] || (tpl && /^[A-Za-z]{2,4}$/.test(n) ? tpl.replace('{}', n.toLowerCase()) : '');
      return { n: n, img: src ? await loadImg(src) : null };
    };
    return Promise.all(out.map(async function (e) { return { d: e[0], k: e[1], fr: await side(e[2]), to: await side(e[3]) }; }));
  }
  function pcMovesH(mv) { return mv && mv.length ? 50 + MV_H + 30 : 0; }
  // the strip: one chip a move, oldest at the left: kind, date, then the logos (from, a pixel arrow, to) or the school's name
  function movesStrip(g, mv, x, y, w) {
    cardRule(g, x, y, w, mv.every(function (e) { return /visit|unofficial/.test(e.k); }) ? 'VISITS' : 'MOVES'); y += 50;
    var n = Math.max(mv.length, 3), gap = 20, cw = Math.floor((w - (n - 1) * gap) / n), pad = 20, lz = 64;
    mv.forEach(function (e, k) {
      var cx = x + k * (cw + gap), L = MV_LAB[e.k] || [String(e.k).toUpperCase(), 'lilac'], room = cw - 2 * pad;
      g.fillStyle = C.face; g.fillRect(cx, y, cw, MV_H); bevel(g, cx, y, cw, MV_H, true, 3);
      g.font = '34px ' + FONT; g.fillStyle = C[L[1]]; g.fillText(fit(g, L[0], room), cx + pad, y + pad + 17);
      g.font = '28px ' + FONT; g.fillStyle = C.lilac; g.fillText(mvDate(e.d), cx + pad, y + 76);
      var ly = y + 102, cy = ly + lz / 2, tx = cx + pad, end = cx + cw - pad, both = e.fr && e.to;
      var put = function (s, max) {
        if (s.img) { drawLogo(g, s.img, tx, ly, lz, lz); tx += lz + 14; return true; }
        g.font = '34px ' + FONT; g.fillStyle = C.white; var t = fit(g, s.n, max); g.fillText(t, tx, cy); tx += g.measureText(t).width + 14; return false;
      };
      if (both) {
        put(e.fr, (room - 64) / 2);
        g.fillStyle = C.lilac; g.fillRect(tx, cy - 3, 18, 6); g.fillRect(tx + 18, cy - 9, 6, 18); g.fillRect(tx + 24, cy - 6, 6, 12); g.fillRect(tx + 30, cy - 3, 6, 6); tx += 50;
        if (put(e.to, end - tx) && end - tx >= 110) { g.font = '34px ' + FONT; g.fillStyle = C.white; g.fillText(fit(g, e.to.n, end - tx), tx, cy); }
      } else {
        var s = e.to || e.fr; if (!s) return;
        if (put(s, room) && end - tx >= 60) { g.font = '34px ' + FONT; g.fillStyle = e.to ? C.white : C.lilac; g.fillText(fit(g, s.n, end - tx), tx, cy); }
      }
    });
  }
  // ---- recruit card (CFB and CBB class tabs: rows with a class year in data-rc). A projection card, so every band is
  // what he is expected to become: grades (ARK and industry stars, each service's rank), the FV scale (10th-90th range,
  // FV and the year-1 or NBA-conditional FV), the path (CFB years 1-3; CBB the odds of each NBA role), year-1 college
  // odds and xNIL, the destination calls while he is uncommitted, his moves or visits, and the FV inputs.
  function rcScale(g, x, y, w, h, o) {
    var pad = 28, tx = x + pad, n = 61, bw = (w - 2 * pad) / n, ty = y + 112, th = 40, at = function (v) { return Math.round(tx + (Math.max(20, Math.min(80, Math.round(v))) - 20) * bw); };
    g.fillStyle = C.face; g.fillRect(x, y, w, h); bevel(g, x, y, w, h, true, 3);
    g.font = '32px ' + FONT; g.fillStyle = C.lilac; g.fillText('10TH-90TH', tx, y + 42);
    var lw = g.measureText('10TH-90TH  ').width; g.fillStyle = C.white; g.fillText(Math.round(o.lo) + '-' + Math.round(o.hi), tx + lw, y + 42);
    for (var v = 20; v <= 80; v++) { g.fillStyle = v >= Math.round(o.lo) && v <= Math.round(o.hi) ? C.lilac : C.dark; g.fillRect(at(v), ty, Math.max(4, Math.floor(bw) - 4), th); }
    var bwi = Math.max(4, Math.floor(bw) - 4), same = o.alt && Math.round(o.alt[1]) === Math.round(o.fv);
    if (o.alt && !same) { g.fillStyle = C.white; g.fillRect(at(o.alt[1]), ty - 12, bwi, th + 24); }
    g.fillStyle = C.teal; g.fillRect(at(o.fv), ty - 12, bwi, th + 24);
    g.font = '40px ' + FONT;
    var ft = 'FV ' + Math.round(o.fv), fw = g.measureText(ft).width, fx = Math.max(tx + lw + 200 > at(o.fv) + bwi - fw ? tx : tx, Math.min(at(o.fv) + bwi - fw, x + w - pad - fw));
    if (fx < tx) fx = tx;
    g.fillStyle = C.teal; g.fillText(ft, fx, y + 84);
    if (o.alt) { var t2 = o.alt[0] + ' ' + Math.round(o.alt[1]), w2 = g.measureText(t2).width, ax = Math.max(at(o.alt[1]), fx + fw + 28); if (ax + w2 > x + w - pad) ax = x + w - pad - w2; g.fillStyle = C.white; g.fillText(t2, ax, y + 84); }
    g.font = '28px ' + FONT; g.fillStyle = C.lilac; g.textAlign = 'center';
    for (var t = 20; t <= 80; t += 10) g.fillText(String(t), at(t) + bwi / 2, y + h - pad - 8);
    g.textAlign = 'left';
  }
  async function buildRCard(win, row, rc) {
    var table = row.closest('table'), hcells = pcHeads(table), heads = hcells.map(txt), cells = [].slice.call(row.cells);
    var rows = pcAll(table), at = pcAt(table, rows, row), nameI = pcNameAt(heads);
    var gi = function (re) { return heads.findIndex(function (h) { return re.test(h); }); };
    var cv = function (re) { var i = gi(re), c = i >= 0 && cells[i]; return c && !c.hidden && !(hcells[i] && hcells[i].hidden) ? c : null; };
    var ct = function (re) { var c = cv(re), t = c ? pcCell(c).t : ''; return t === '—' || pcDash(t) ? '' : t; };
    var cn = function (re) { var c = cv(re), v = c ? parseFloat(c.getAttribute('data-v')) : NaN; return isFinite(v) ? v : null; };
    var D = null, why = null; try { D = JSON.parse(row.getAttribute('data-d') || 'null'); why = D ? D.why : JSON.parse(row.getAttribute('data-why') || 'null'); } catch (e) {}
    var cbb = !!D, open = !!rc.o, nameC = cells[nameI >= 0 ? nameI : 1], name = nameC && nameC.querySelector('button.cfb__who, b') ? pcName(row, nameI >= 0 ? nameI : 1) : nameC ? pcCell(nameC).t : '';
    var posI = gi(POS_COL), pOf = function (r) { var c = r.cells[posI]; if (!c) return ''; c = c.cloneNode(true); c.querySelectorAll('.cfb__dim, span').forEach(function (e) { e.remove(); }); return txt(c); };
    var posT = posI >= 0 ? pOf(row) : '', team = open ? '' : ct(TEAM_COL), conf = open ? '' : ct(/^conf$/i);
    var fv = cbb ? D.fv : cn(/^xfv/i), alt = cbb ? (D.fvIf != null ? ['IF NBA', D.fvIf] : null) : (cn(/^y1 fv$/i) != null ? ['Y1 FV', cn(/^y1 fv$/i)] : null);
    if (fv == null) return null;
    var lo = cbb ? D.q10 : rc.g && rc.g[0], hi = cbb ? D.ceil : rc.g && rc.g[1];
    var home = (cbb ? D.home : ct(/^home$/i)) || '', hs = cbb && D.hs ? D.hs : '', age = rc.ag != null ? rc.ag : cbb ? D.age : null, ar = typeof rc.ar === 'number' ? rc.ar : null;
    var th0 = row.querySelector('.pxframe img'), photo = await loadPhoto(pcBig(th0 && (th0.currentSrc || th0.src)));
    var lg = [].slice.call(row.querySelectorAll('img.cfb__logo')).find(function (e) { return !e.closest('.pxframe'); }), logo = open ? null : await loadImg(lg && (lg.currentSrc || lg.src));
    var fi = row.querySelector('img.flag'), flag = fi ? await loadImg(fi.currentSrc || fi.src) : null;
    var items = await rcItems(rc), starI = items.filter(function (it) { return it.stars != null; }), destI = items.filter(function (it) { return it.stars == null; });
    var mv = await pcMoves(win, name, { cls: rc.c, open: open, team: team });
    // each service's rank
    var rk = function (h, v, sub, raw) { return v == null || v === '' ? null : { h: h, t: !raw && /^\d+$/.test(String(v)) ? '#' + v : String(v), sub: sub || '' }; }, ranks;
    if (cbb) ranks = [rk('CONS', D.rk), rk('ON3', D.svc && D.svc.on3), rk('247', D.svc && D.svc['247']), rk('ESPN', D.svc && D.svc.espn), rk('RIVALS', D.svc && D.svc.rivals)];
    else { var gr = ct(/^grade$/i), src = ct(/^source$/i), nat = ct(/^nat$/i); ranks = [nat ? rk('ESPN', nat, gr ? 'grade ' + gr : '') : rk(src && src !== 'ESPN' ? 'GRADE, ' + src.toUpperCase() : 'ESPN GRADE', gr, '', true), rk('247 COMP', ct(/^247$/), '', true), rk('RIVALS', ct(/^riv$/i))]; }
    ranks = ranks.filter(Boolean);
    // the path: CFB xFV in years 1-3, CBB the odds of each NBA role
    var pp = function (x) { return x < 0.005 ? '<1%' : Math.min(99, Math.round(x * 100)) + '%'; }, cols, stats, y1 = cbb && D.path && D.path[0];
    if (cbb) {
      cols = [['NBA', D.p, 'played a game'], ['40+', D.p40, 'rotation'], ['50+', D.p50, 'starter'], ['60+', D.p60, 'All-Star']].filter(function (c) { return c[1] != null; }).map(function (c) { return { h: c[0], t: pp(c[1]), pct: Math.max(0.5, c[1] * 100), sub: c[2] }; });
      stats = y1 ? [{ h: 'D-I% Y1', t: pp(y1.on), prob: y1.on * 100 }, { h: 'MIN% Y1', t: String(Math.round(y1.min)), prob: y1.min }, { h: 'BPM Y1', t: (y1.bpm > 0 ? '+' : y1.bpm < 0 ? '−' : '') + Math.abs(y1.bpm).toFixed(1) }] : [];
      if (D.xnil) stats.push({ h: 'xNIL Y1', t: ct(/^xnil$/i) });
    } else {
      cols = (rc.y || []).map(function (v, k) { return { h: 'Y' + (k + 1), t: String(Math.round(v)), pct: Math.max(0.5, v - 20), sub: rc.c ? String(rc.c + k) : '' }; });
      var on = cn(/^on%$/i), pc = cn(/^pct$/i); stats = [];
      if (on != null) stats.push({ h: 'ON% Y1', t: Math.round(on * 100) + '%', prob: on * 100 });
      if (pc != null) stats.push({ h: 'Y1 BOARD PCTL', t: String(pc), prob: pc });
      if (ct(/^xnil$/i)) stats.push({ h: 'xNIL Y1', t: ct(/^xnil$/i) });
    }
    var parts = why && why.rows ? why.rows.map(function (r) { return [r[0], +r[1]]; }).filter(function (p) { return p[0] && isFinite(p[1]) && Math.abs(p[1]) >= 0.05; }).sort(function (a, b) { return Math.abs(b[1]) - Math.abs(a[1]); }).slice(0, 10) : [];
    var wt = txt(win.querySelector('.win__title-text')).replace(/_$/, '').trim(), base = wt.split('::')[0].trim(); if (/^[a-z0-9]/.test(base)) base = SITE.split('/').pop().toUpperCase() + ' ' + base;
    var F = await frame(2160, 2700, base + ' :: ' + name, win.getAttribute('data-gfx-date'), tabLink(win));
    var g = F.g, x = F.x + 40, y = F.y + 70, w = F.w - 80, top = y, bottom = F.y + F.h - 30;
    well(g, F.x, F.y, F.w, F.h);
    var px = 400, PW = 350, PH = 400, tcol = w - px - PW - 36, qx = x + w - PW, qy = y - 60, qc = qx + PW / 2;
    photoFrame(g, photo, x, y - 60, 370, 400);
    // the plaque: FV to the whole number, the year-1 (CFB) or NBA-conditional (CBB) FV under it, then his place
    var place = '#' + (at + 1) + ' of ' + rows.length, posPlace = '';
    if (posT && at >= 0) { var pk0 = 0, pn = 0; rows.forEach(function (r, k) { if (pOf(r) === posT) { pn++; if (k < at) pk0++; } }); if (pn >= 3 && pn < rows.length) posPlace = posT + ' #' + (pk0 + 1) + ' of ' + pn; }
    g.fillStyle = C.face; g.fillRect(qx, qy, PW, PH); bevel(g, qx, qy, PW, PH, true, 6);
    g.textAlign = 'center'; g.font = '36px ' + FONT; g.fillStyle = C.lilac; g.fillText('FV', qc, qy + 40);
    var fvT = String(Math.round(fv)); g.textAlign = 'left'; g.font = '104px ' + FONT; var cw0 = g.measureText(fvT).width + 104 * 0.6; chip(g, Math.round(qc - cw0 / 2), qy + 134, fvT, 104, Math.round(fv));
    if (alt) {
      g.font = '44px ' + FONT; var a1 = alt[0] + ' ', a2 = String(Math.round(alt[1])), aw = g.measureText(a1 + a2).width, ax = Math.round(qc - aw / 2);
      g.fillStyle = C.lilac; g.fillText(a1, ax, qy + 244); g.fillStyle = C.white; g.fillText(a2, ax + g.measureText(a1).width, qy + 244);
    }
    g.fillStyle = C.dark; g.fillRect(qx + 30, qy + 284, PW - 60, 3);
    g.textAlign = 'center'; g.font = '32px ' + FONT; g.fillStyle = C.lilac;
    [place, posPlace].filter(Boolean).forEach(function (l, i, a) { g.fillText(fit(g, l, PW - 30), qc, qy + (a.length > 1 ? 322 + i * 38 : 340)); });
    g.textAlign = 'left';
    // name, the line under it, then facts: size and age, home (high school), age against the class
    if (logo) drawLogo(g, logo, x + px, y - 48, 96, 96);
    var nx = x + px + (logo ? 120 : 0);
    if (flag) { g.imageSmoothingEnabled = false; g.drawImage(flag, nx, y - 33, 96, 66); nx += 120; }
    var ns = 96, nroom = x + px + tcol - nx; g.font = ns + 'px ' + FONT; while (ns > 64 && g.measureText(name).width > nroom) { ns -= 4; g.font = ns + 'px ' + FONT; }
    g.fillStyle = C.white; g.fillText(fit(g, name, nroom), nx, y); y += 110;
    var st = cbb ? (D.signed ? 'signed' : '') : /signed|enrolled/i.test(ct(/^status$/i)) ? ct(/^status$/i) : '';
    g.font = '48px ' + FONT; g.fillStyle = C.teal; g.fillText(fit(g, [posT, open ? 'uncommitted' : team || (cbb && D.school) || '', conf, st].filter(Boolean).join(' · '), tcol), x + px, y); y += 74;
    var facts = function (list, size) {
      g.font = size + 'px ' + FONT; var ix = x + px, any = false;
      list.forEach(function (f) { if (!f[1]) return; var lw = g.measureText(f[0] + ' ').width, vw = g.measureText(f[1]).width; if (ix + lw + vw > x + px + tcol) { if (any) return; f[1] = fit(g, f[1], tcol - lw); vw = g.measureText(f[1]).width; }
        g.fillStyle = C.lilac; g.fillText(f[0], ix, y); g.fillStyle = C.white; g.fillText(f[1], ix + lw, y); ix += lw + vw + 52; any = true; });
      if (any) y += size + 22;
    };
    var size = cbb ? [D.ht, D.wt].filter(Boolean).join(', ') : ct(/^size$/i);
    facts([['CLASS', rc.c ? String(rc.c) : ''], ['SIZE', size], ['AGE', age != null ? (Math.round(age * 10) / 10).toString() : '']], 44);
    facts([['HOME', home + (hs ? ' (' + hs + ')' : '')]], 44);
    if (ar != null) {   // years against the class median: young at the right in teal, old at the left in pink
      g.font = '44px ' + FONT; g.fillStyle = C.lilac; g.fillText('AGE FOR CLASS', x + px, y); var lw0 = g.measureText('AGE FOR CLASS  ').width;
      pxDiv(g, x + px + lw0, y, 360, 24, -ar, 1.5, 8);
      var at0 = Math.abs(ar) < 0.05 ? 'median' : Math.abs(ar).toFixed(1) + ' yr ' + (ar < 0 ? 'young' : 'old');
      g.fillStyle = Math.abs(ar) < 0.05 ? C.lilac : ar < 0 ? C.teal : C.down; g.fillText(fit(g, at0, tcol - lw0 - 384), x + px + lw0 + 384, y);
    }
    // the bands: room left by the fixed ones goes to the projection
    var gap = 20, GH = 210, SH = 230, partsH = inputBarsH(parts.length), mvH = pcMovesH(mv), destH = destI.length ? 50 + RC_H + 30 : 0, yb = top + 394;
    var room = bottom - yb - partsH - mvH - destH - (50 + GH + 30), hasScale = lo != null && hi != null;
    var colsH = Math.max(220, Math.min(560, room - 80 - (hasScale ? SH + gap : 0))), projH = 80 + (hasScale ? SH + gap : 0) + colsH;
    var slack = Math.max(0, room - projH), nb = 2 + (destH ? 1 : 0) + (mvH ? 1 : 0) + (partsH ? 1 : 0), lead = Math.min(64, Math.floor(slack / nb));
    y = yb + lead;
    cardRule(g, x, y, w, 'GRADES'); y += 50;
    var sw = ranks.length ? Math.round(w * (ranks.length >= 4 ? 0.44 : 0.56)) : w;
    rcBand(g, starI, x, y, sw, GH, gap);
    if (ranks.length) cellGrid(g, ranks, x + sw + gap, y, w - sw - gap, ranks.length, GH, gap);
    y += GH + 30 + lead;
    cardRule(g, x, y, w, 'PROJECTION'); y += 50;
    if (hasScale) { rcScale(g, x, y, w, SH, { lo: lo, hi: hi, fv: fv, alt: alt }); y += SH + gap; }
    var lw2 = stats.length ? Math.round(w * 0.56) : w;
    if (cols.length) fvoBand(g, { items: cols, max: cbb ? 100 : Math.max(20, (hi || 40) - 20) }, x, y, lw2, colsH);
    if (stats.length) { var sc = stats.length > 2 ? 2 : 1, sr = Math.ceil(stats.length / sc); cellGrid(g, stats, cols.length ? x + lw2 + gap : x, y, cols.length ? w - lw2 - gap : w, sc, Math.floor((colsH - (sr - 1) * gap) / sr), gap); }
    y += colsH + 30 + lead;
    if (destH) { cardRule(g, x, y, w, 'PREDICTIONS'); y += 50; rcBand(g, destI, x, y, w, RC_H, gap); y += RC_H + 30 + lead; }
    if (mvH) { movesStrip(g, mv, x, y, w); y += mvH + lead; }
    if (parts.length) inputBars(g, x, bottom - partsH + 40, w, 'FV INPUTS', '', parts, Math.max(1, Math.max.apply(null, parts.map(function (p) { return Math.abs(p[1]); }))), 1, 470);
    return F.canvas;
  }
  async function buildPCard(win, row) {
    var table = row.closest('table'); if (!table) return null;
    var rc0 = null; try { rc0 = JSON.parse(row.getAttribute('data-rc') || 'null'); } catch (e) {}
    if (rc0 && rc0.c && !pcMain(row)) { var rcv = await buildRCard(win, row, rc0); if (rcv) return rcv; }
    var mainR = pcMain(row), subRow = mainR ? row : null, mv = pcMove(mainR || row);
    if (mv == null && mainR) mv = pcMove(row);
    if (mainR) { row = mainR; table = row.closest('table'); }
    var hcells = pcHeads(table), heads = hcells.map(txt), cells = [].slice.call(row.cells);
    var rows = pcAll(table), at = pcAt(table, rows, row), nameI = pcNameAt(heads);
    var det = await pcDetail(row), d = det.el;
    var comps = await pcComps(win, d), compH = pcCompsH(comps), mvs = [];   // the comps strip adds its own height, so no band gives way
    var gi = function (re) { return heads.findIndex(function (h) { return re.test(h); }); };
    var nameC = cells[nameI >= 0 ? nameI : 1];
    var name = nameC && nameC.querySelector('button.cfb__who, b') ? pcName(row, nameI >= 0 ? nameI : 1) : nameC ? pcCell(nameC).t : txt(d && d.querySelector('.cfb__dhead b'));
    var teamI = gi(TEAM_COL), posI = gi(POS_COL), clsI = gi(CLASS_COL), fvI = gi(FV_COL), lgI = gi(/^(league|lg|conf)$/i);
    var tm = row.querySelector('.nbaxpm__tm, .nflwar__tm');
    var team = teamI >= 0 ? pcCell(cells[teamI]).t : tm ? txt(tm).split('·')[0].trim() : '';
    var rc = null; try { rc = JSON.parse(row.getAttribute('data-rc') || 'null'); } catch (e) {}
    if (rc && rc.o) team = 'uncommitted';   // the team cell holds a lean, which the STARS · PICKS band draws
    var rcI = await rcItems(rc);
    var posC = posI >= 0 && cells[posI] && cells[posI].cloneNode(true); if (posC) posC.querySelectorAll('.cfb__dim, span').forEach(function (e) { e.remove(); });
    var ageI = isYouth(win) ? gi(AGE_COL) : -1, ageT = ageI >= 0 && cells[ageI] ? pcCell(cells[ageI]).t : '';
    if (!/\d/.test(ageT)) { ageI = -1; ageT = ''; }
    var playsI = gi(/^plays$/i);
    var sub = [posC ? txt(posC) : '', ageT ? 'age ' + ageT : '', team, lgI >= 0 ? pcCell(cells[lgI]).t : tm ? (txt(tm).split('·')[1] || '').trim() : '', clsI >= 0 ? pcCell(cells[clsI]).t : '', playsI >= 0 && !/\d/.test(pcCell(cells[playsI]).t) ? pcCell(cells[playsI]).t : ''].filter(function (s) { return s && s !== '—'; });
    var fvChip = fvI >= 0 && cells[fvI] && cells[fvI].querySelector('.fv-chip'), fvT = fvI >= 0 ? pcCell(cells[fvI]).t : '';
    var fvN = fvChip ? parseFloat(fvChip.getAttribute('data-fv')) : parseFloat(fvT);
    // photo: the dropdown's card photo, else the row thumbnail upsized; logo: the row's team logo or the window's path
    var ph = d && d.querySelector('.pxframe--card img'), th0 = row.querySelector('.pxframe img');
    var photo = await loadPhoto(pcBig(ph && (ph.currentSrc || ph.src)) || pcBig(th0 && (th0.currentSrc || th0.src)));
    if (!photo && ph) photo = await loadPhoto(ph.currentSrc || ph.src);
    var lg = [].slice.call(row.querySelectorAll('img.cfb__logo')).find(function (e) { return !e.closest('.pxframe'); }), lsrc = lg && (lg.currentSrc || lg.src);
    var tpl = win.getAttribute('data-gfx-logo'); if (!lsrc && tpl && team) lsrc = tpl.replace('{}', team.split('/').pop().trim().toLowerCase());
    var logo = rc && rc.o ? null : await loadImg(lsrc);
    var fl = row.querySelector('svg.esea-flag'), fi = row.querySelector('img.flag');
    var flag = fl ? await flagImg((fl.getAttribute('aria-label') || '').toLowerCase()) : fi ? await loadImg(fi.currentSrc || fi.src) : null;
    // the featured stat: the sorted column (or the rank-by view's key column), else the first number after the name
    var sortI = sortedCol(table, hcells), desc = (hcells[sortI] || { getAttribute: function () {} }).getAttribute('aria-sort') !== 'ascending';
    var tiles = [], lines = [], info = [], rateI = gi(/^pxp\/60$/i);
    heads.forEach(function (h, i) {
      if (i === nameI || i === fvI || i === ageI || (rc && /^(ark|stars)$/i.test(h)) || (rc && rc.o && /^status$/i.test(h)) || PC_SKIP.test(h) || PC_DROP.test(h) || PC_SUB.test(h) || !h || (hcells[i] && hcells[i].hidden) || !cells[i] || cells[i].hidden) return;
      var c = pcCell(cells[i]); if ((c.t === '—' || pcDash(c.t)) && !c.sub) return;
      if (/^pct$/i.test(h) && rateI >= 0) return;   // the percentile of the column beside it, which draws its own
      if (c.t.length > 18) { lines.push([h, c.t + (c.sub ? ' · ' + c.sub : '')]); return; }
      var n = PC_NOPCT.test(h) || PC_ORD.test(h) ? null : pcNum(cells[i], c.t), pct = null;
      if (n != null) {
        var vals = rows.map(function (r) { var cc = r.cells[i]; return cc ? pcNum(cc, pcCell(cc).t) : null; }).filter(function (v) { return v != null; });
        if (vals.length >= 5) pct = pcPct(vals, n);
      }
      // context columns (age, games, minutes, size, contract) are facts, not grades: a strip under the name, no percentile
      if (PC_INFO.test(h)) { info.push([capHead(h), c.t]); return; }
      var good = pct == null || PD_NEUTRAL.test(h) ? null : PD_LOWER.test(h) ? 100 - pct : pct;
      tiles.push(pcProb({ i: i, h: h, t: c.t, sub: c.sub, color: c.color, pct: pct, good: good, tip: hcells[i] ? hcells[i].getAttribute('title') : '' }));
    });
    // NBA: every player card carries VORX; tables without the column borrow it from the XPM board's current season
    var xw = document.querySelector('[data-nbaxpm][data-src][data-cur]');
    if (xw && !heads.some(function (h) { return /^vorx$/i.test(h); })) {
      var xd = await nbaXpm(xw), nm = pdNorm(name), tmU = (team.split('/').pop() || '').trim().toUpperCase();
      var hits = xd ? xd.players.filter(function (p) { return pdNorm(p.n) === nm; }) : [];
      var xp = hits.length > 1 && tmU ? hits.find(function (p) { return p.tm === tmU; }) || hits[0] : hits[0];
      if (xp && xp.vorx != null) {
        var vs = xd.players.filter(function (p) { return p.mp >= 100 && p.vorx != null; }).map(function (p) { return p.vorx; });
        var vp = vs.length >= 5 ? pcPct(vs, xp.vorx) : null;
        tiles.unshift({ i: -1, h: 'VORX', t: xp.vorx.toFixed(1), pct: vp, good: vp, tip: 'wins over replacement on XPM, ' + xd.label });
      }
    }
    // the headline: the board's FV, else the sorted column (or the first graded number), in a plaque at the top right
    var hasFv = !!(fvT && fvT !== '—');
    var feat = tiles.find(function (t) { return t.i === sortI; }) || (!hasFv ? tiles.find(function (t) { return t.pct != null && t.prob == null; }) : null);
    if (feat && !hasFv) tiles.splice(tiles.indexOf(feat), 1); else if (feat) feat.key = true;
    var wt = txt(win.querySelector('.win__title-text')).replace(/_$/, '').trim();
    var base = wt.split('::')[0].trim(); if (/^[a-z0-9]/.test(base)) base = SITE.split('/').pop().toUpperCase() + ' ' + base;
    var pk = row.getAttribute('data-pk'), link = tabLink(win);
    if (pk && /#/.test(link)) link += ':p=' + pk;
    else if (win.getAttribute('data-cbb') && window.__arkCbbPid && row.hasAttribute('data-i') && window.__arkCbbRecs) { var rec = window.__arkCbbRecs[+row.getAttribute('data-i')]; if (rec) link = SITE + '#' + win.getAttribute('data-cbb') + ':p=' + window.__arkCbbPid(rec); }
    mvs = await pcMoves(win, name, { team: rc && rc.o ? '' : team }); var mvH = pcMovesH(mvs); compH += mvH;
    var F = await frame(2160, 2700 + compH, base + ' :: ' + name, win.getAttribute('data-gfx-date'), link);
    var g = F.g, x = F.x + 40, y = F.y + 70, w = F.w - 80, top = y, bottom = F.y + F.h - 30;
    well(g, F.x, F.y, F.w, F.h);
    var px = 400, PW = 350, PH = 290, plq = hasFv || !!feat, tcol = w - px - (plq ? PW + 36 : 0);
    photoFrame(g, photo, x, y - 60, 370, 400);   // no headshot: the frame keeps its place with the pixel silhouette
    // his place in the view, and among the rows at his position
    var posT = posC ? txt(posC) : '', place = '#' + (at + 1) + ' of ' + rows.length, posPlace = '';
    if (posT && posI >= 0 && rows.length <= 3000 && at >= 0) {
      var pk0 = 0, pn = 0, pOf = function (r) { var c = r.cells[posI]; if (!c) return ''; c = c.cloneNode(true); c.querySelectorAll('.cfb__dim, span').forEach(function (e) { e.remove(); }); return txt(c); };
      rows.forEach(function (r, k) { if (pOf(r) === posT) { pn++; if (k < at) pk0++; } });
      if (pn >= 3 && pn < rows.length) posPlace = posT + ' #' + (pk0 + 1) + ' of ' + pn;
    }
    if (plq) {
      var qx = x + w - PW, qy = y - 60, qc = qx + PW / 2;
      g.textAlign = 'center';
      if (hasFv) {
        g.textAlign = 'left'; fvPlaque(g, qx, qy, PW, PH, fvT, isFinite(fvN) ? fvN : 20, [place, posPlace]); g.textAlign = 'center';
      } else {
        g.fillStyle = C.teal; g.fillRect(qx, qy, PW, PH); bevel(g, qx, qy, PW, PH, true, 6);
        g.fillStyle = C.dark; g.font = '36px ' + FONT; g.fillText(fit(g, capHead(feat.h), PW - 40), qc, qy + 44);
        var fs = 124; g.font = fs + 'px ' + FONT; while (fs > 56 && g.measureText(feat.t).width > PW - 44) { fs -= 4; g.font = fs + 'px ' + FONT; }
        g.fillText(feat.t, qc, qy + 132);
        g.font = '32px ' + FONT; g.fillText(place, qc, qy + (posPlace ? 216 : 236)); if (posPlace) g.fillText(fit(g, posPlace, PW - 30), qc, qy + 256);
      }
      movePill(g, qc, qy + PH + 14, mv, PW);
      g.textAlign = 'left';
    }
    if (logo) drawLogo(g, logo, x + px, y - 48, 96, 96);
    var nx = x + px + (logo ? 120 : 0);
    if (flag) { g.imageSmoothingEnabled = false; g.drawImage(flag, nx, y - 33, 96, 66); nx += 120; }
    var ns = 96, nroom = x + px + tcol - nx; g.font = ns + 'px ' + FONT; while (ns > 68 && g.measureText(name).width > nroom) { ns -= 4; g.font = ns + 'px ' + FONT; }
    g.fillStyle = C.white; g.fillText(fit(g, name, nroom), nx, y);
    y += 110;
    g.font = '48px ' + FONT; g.fillStyle = C.teal; g.fillText(fit(g, sub.join(' · '), tcol), x + px, y); y += 76;
    // the dropdown's role / outlook lines, a few, under the name
    // a built dropdown's lines (place in view, ranges, season line) repeat the tiles below
    var auto = !!(d && d.classList.contains('pd__auto'));
    var roles = d && !auto ? [].slice.call(d.querySelectorAll('.cfb__role')).map(txt).filter(Boolean) : [];
    info = info.filter(function (f) { return !new RegExp('(^|[ ·])' + f[1].replace(/[.*+?^${}()|[\]\\\/]/g, '\\$&') + ' ').test(sub.join(' · ') + ' '); });   // "250 MP", "415 min" already in the line above
    // the reserve at the bottom for the dropdown (badges, strengths and concerns, FV inputs)
    var plus = d && !auto ? [].slice.call(d.querySelectorAll('.cfb__report li.is-plus')).map(txt) : [], minus = d && !auto ? [].slice.call(d.querySelectorAll('.cfb__report li.is-minus')).map(txt) : [];
    var parts = d ? [].slice.call(d.querySelectorAll('.cfb__parts:not(.pd__pct) li:not(.cfb__step)')).map(function (li) { return [txt(li.querySelector('.cfb__bk')), parseFloat(txt(li.querySelector('.cfb__bv')).replace(/−/g, '-'))]; }).filter(function (p) { return p[0] && isFinite(p[1]); }).slice(0, 10) : [];
    var badges = pcBadges([row, d]);
    if (!badges.length) { var med = row.querySelector('.cfb__medals'), TT = { Platinum: 'p', Gold: 'g', Silver: 's', Bronze: 'b' };
      if (med) (med.getAttribute('title') || '').split('\n').forEach(function (l) { var m = l.match(/^(Platinum|Gold|Silver|Bronze) (.+?):/); if (m) badges.push([m[2], TT[m[1]]]); }); }
    // the bands, in order: the subset table's own columns, the row's tiles by what they measure, the FV outlook, the
    // stat lines the text carries (season line), the player's row on the page's other tables
    var shown = {};
    heads.concat(['player', 'team', 'pos']).forEach(function (h) { shown[h.toLowerCase()] = 1; });
    var bands = [];
    if (subRow) {
      var own = pcOwn(subRow, shown), st = subRow.closest('table'), tabN = ((st.closest('[data-tab]') || st.closest('.win')).getAttribute('data-tab') || '').toUpperCase();
      if (own.length) { own.forEach(function (it) { shown[it.h.toLowerCase()] = 1; }); bands.push({ title: tabN, items: own, wgt: 1 }); }
    }
    if (rcI) { bands.push({ title: 'STARS · PICKS', items: rcI, wgt: 0.9, rc: true }); rcI.forEach(function (it) { shown[it.h.toLowerCase()] = 1; }); }
    bands = bands.concat(pcBands(tiles));
    var fvo = pcFvo(d && !auto ? d : null); if (fvo) bands.push({ title: 'FV OUTLOOK', items: fvo.items, wgt: 1.3, fvo: true });
    roles.forEach(function (r, i) { var s = pcStatText(r, ''); if (s.group) bands.push({ title: capHead(s.group.title), items: s.group.items, wgt: 0.78, compact: true, src: ['r', i, s.rest] }); });
    lines.forEach(function (l, i) { var s = pcStatText(l[1], l[0]); if (s.group) bands.push({ title: capHead(s.group.title), items: s.group.items, wgt: 0.78, compact: true, src: ['l', i, s.rest] }); });
    bands.forEach(function (b) { b.items.forEach(function (it) { shown[String(it.h).toLowerCase()] = 1; }); });
    pcXGroups(table, name, team, posT, shown).sort(function (a, b) { return b.pri - a.pri; }).forEach(function (gp) { bands.push({ title: capHead(gp.title), items: gp.items.map(pcProb), wgt: 0.78, compact: true }); });
    // a band's cell that an earlier band already shows (same label and value, or the same value under a longer label:
    // "XPM (proj)" beside "Proj") goes; games, minutes and age from another table join the fact strip
    var had = {}, words = function (h) { return String(h).toLowerCase().replace(/[()]/g, ' ').split(/\s+/).filter(Boolean); };
    if (feat) had[feat.h.toLowerCase() + '|' + feat.t] = 1;
    bands.forEach(function (b, bi) {
      if (b.fvo || b.rc) return;
      b.items = b.items.filter(function (it) {
        if (pcDash(it.t)) return false;
        var ks = words(it.h).map(function (q) { return q + '|' + it.t; }); ks.push(String(it.h).toLowerCase() + '|' + it.t);
        if (ks.some(function (q) { return had[q]; })) return false;
        if (b.compact && !b.src && (PC_INFO.test(it.h) || /^pct$/i.test(it.h))) { if (PC_INFO.test(it.h) && !info.some(function (f) { return f[0] === capHead(it.h); })) info.push([capHead(it.h), it.t]); return false; }
        ks.forEach(function (q) { had[q] = 1; }); return true;
      });
      // shares of one whole (NBA position: PF 46%, SF 37% ...): each cell's bar is its share
      var ps = b.items.map(function (it) { return /^\d+(\.\d+)?%$/.test(it.t) ? parseFloat(it.t) : NaN; }), tot = ps.reduce(function (a, v) { return a + v; }, 0);
      if (b.items.length >= 2 && (tot >= 95 && tot <= 105 || /position/i.test(b.title) && ps.every(isFinite) && tot <= 105)) b.items.forEach(function (it, k) { it.prob = ps[k]; it.pct = null; it.good = null; });
    });
    bands = bands.filter(function (b) { return b.items.length >= (b.compact && !b.src ? 2 : 1); });
    bands.forEach(function (b) { b.cols = b.fvo ? 1 : b.rc ? b.items.length : pcCols(b.items.length, b.compact); b.rows = b.fvo ? 1 : Math.ceil(b.items.length / b.cols); });
    // strengths and concerns: an item that only repeats numbers the card shows keeps its label alone ("production")
    function seen() {
      var s = {}, add = function (t) { pcNumsIn(t).forEach(function (n) { s[n] = 1; }); };
      add(sub.join(' ')); add(fvT); info.forEach(function (f) { add(f[1]); }); if (feat) add(feat.t);
      bands.forEach(function (b) { b.items.forEach(function (it) { add(it.t); add(it.sub || ''); }); });
      return s;
    }
    function fresh(t, s) { var ns = pcNumsIn(t); return !ns.length || ns.some(function (n) { return !s[n]; }); }
    function used() {   // role lines and long cells, less the text the bands took and the bits that repeat the card
      var rs = roles.slice(), ls = lines.slice(), s = seen();
      bands.concat(gone).forEach(function (b) { var c = b.src; if (!c) return; if (c[0] === 'r') rs[c[1]] = c[2]; else ls[c[1]] = c[2] ? [ls[c[1]][0], c[2]] : null; });
      rs = rs.map(function (r) { return String(r || '').replace(/\.$/, '').split(/\s+·\s+/).filter(function (q) { return q && fresh(q, s); }).join(' · '); }).filter(Boolean);
      return { rs: rs, ls: ls.filter(Boolean) };
    }
    var gap = 20, UMIN = 168, yb = top + 360 + 34, gone = [];
    function tidy(list, s) { return list.map(function (it) { var m = it.match(/^([^:]{2,30}):\s+\S/); return m && !fresh(it, s) ? m[1] : it; }); }
    function repRows(list) { g.font = '40px ' + FONT; var n = 0; list.forEach(function (it) { n += wrap(g, it, (w - 60) / 2 - 56).length * 54 + 12; }); return n; }
    var partsH = inputBarsH(parts.length), bdgH = badges.length ? 196 : 0, repH = 0, u, U = 0;
    function budget() {
      var s = seen(); u = used();
      var p2 = tidy(plus, s), m2 = tidy(minus, s);
      repH = plus.length || minus.length ? 96 + Math.min(430, Math.max(repRows(p2), repRows(m2), 54)) + 20 : 0;
      var room = bottom - yb - partsH - repH - bdgH - compH - (u.ls.length ? Math.min(u.ls.length, 3) * 64 + 20 : 0);
      var fixed = 0, wsum = 0; bands.forEach(function (b) { if (b.rc) { fixed += 50 + RC_H + 30; return; } fixed += 50 + (b.rows - 1) * gap + 30; wsum += b.rows * b.wgt; });
      U = wsum ? (room - fixed) / wsum : 0; return { p: p2, m: m2 };
    }
    var rep = budget();
    // too tight: the last band loses a row, then goes
    while (bands.length && U < UMIN) {
      var lb = bands[bands.length - 1];
      if (lb.rows > 1) { lb.rows--; lb.items = lb.items.slice(0, lb.rows * lb.cols); } else { if (bands.length === 1) break; gone.push(bands.pop()); }
      rep = budget();
    }
    var nrow = bands.reduce(function (a, b) { return a + (b.rc ? 0 : b.rows); }, 0);
    U = Math.floor(Math.min(U, nrow <= 2 ? 380 : nrow <= 4 ? 320 : 280));
    if (info.length) {   // AGE 27.9  G 7  MP 250: label lilac, value white
      g.font = '44px ' + FONT; var ix0 = x + px;
      info.forEach(function (f) {
        var lw = g.measureText(f[0] + ' ').width, vw = g.measureText(f[1]).width; if (ix0 + lw + vw > x + px + tcol) return;
        g.fillStyle = C.lilac; g.fillText(f[0], ix0, y); g.fillStyle = C.white; g.fillText(f[1], ix0 + lw, y); ix0 += lw + vw + 56;
      });
      y += 68;
    }
    g.font = '40px ' + FONT; g.fillStyle = C.lilac;
    var rl = []; u.rs.forEach(function (r) { wrap(g, r, tcol).forEach(function (l) { rl.push(l); }); });
    rl.slice(0, Math.max(0, Math.floor((top + 350 - y) / 54))).forEach(function (l) { g.fillText(l, x + px, y); y += 54; });
    y = yb;
    var legend = false;
    bands.forEach(function (b) {
      var h = Math.round(b.fvo ? Math.min(U * b.wgt, 300) : U * b.wgt), lg = !legend && b.items.some(function (it) { return it.pct != null && it.prob == null; });
      if (lg) legend = true;
      cardRule(g, x, y, w, b.title, lg ? 'PCTL OF ' + rows.length + ' IN VIEW' : ''); y += 50;
      if (b.fvo) { fvoBand(g, b, x, y, w, h); y += h; } else if (b.rc) { rcBand(g, b.items, x, y, w, RC_H, gap); y += RC_H; } else y += cellGrid(g, b.items, x, y, w, b.cols, h, gap);
      y += 30;
    });
    if (u.ls.length) {
      u.ls.slice(0, 3).forEach(function (l) {
        g.font = '40px ' + FONT; g.fillStyle = C.lilac; var lw = g.measureText(l[0].toUpperCase() + '  ').width; g.fillText(l[0].toUpperCase(), x, y + 10);
        g.fillStyle = C.white; g.fillText(fit(g, l[1], w - lw), x + lw, y + 10); y += 64;
      });
      y += 20;
    }
    if (comps) { compStrip(g, comps, x, y, w); y += compH - mvH; }
    if (mvH) { movesStrip(g, mvs, x, y, w); y += mvH; }
    // badges: the slot for the board's predictive badges (only badges that pass a held-out test are on a board)
    if (badges.length) { y += 6; cardRule(g, x, y, w, 'BADGES'); y += 50; y += badgeRows(g, badges, x, y, w); }
    if (repH) {
      y += 16; var half = (w - 60) / 2, lim = bottom - partsH - 10;
      [['+ strengths', rep.p, C.teal, x], ['− concerns', rep.m, C.down, x + half + 60]].forEach(function (L) {
        var ly = y; g.font = '52px ' + FONT; g.fillStyle = L[2]; g.fillText(L[0], L[3], ly); ly += 72; g.font = '40px ' + FONT;
        (L[1].length ? L[1] : ['none']).forEach(function (it) {
          var ls = wrap(g, it, half - 56); if (ly + ls.length * 54 > lim) return;
          g.fillStyle = L[2]; g.fillText(L[0][0], L[3] + 4, ly); g.fillStyle = C.lilac; ls.forEach(function (l) { g.fillText(l, L[3] + 56, ly); ly += 54; }); ly += 12;
        });
      });
    }
    // FV inputs: each driver's push on the grade, two columns of pixel bars pinned to the bottom
    if (parts.length) inputBars(g, x, bottom - partsH + 40, w, 'FV INPUTS', '', parts, Math.max(1, Math.max.apply(null, parts.map(function (p) { return Math.abs(p[1]); }))), 2, 470);
    if (det.opened && det.close) det.close();
    return F.canvas;
  }
  // ---- a dropdown for every player table that has none (pro boards, mocks, backup watch, ARKLIST ...): the CFB layout
  // built from the row itself. Strengths and concerns are the columns where he sits in the top or bottom fifth of the
  // rows in view (direction-aware: lower is better for ranks, usage and age columns are not judged), the role line carries
  // his place in the view, the ranges a cell carries (80% range, raw value) and the FV chip's note, then the badges and a
  // percentile breakdown of every number. Template text only.
  var PD_NEUTRAL = /^(str|age|g|gp|mp|min|toi|snaps|plays|share|wt\. gp|ht|wt|ht \/ wt|class|yr|yrs|salary|contract|season|gap|xgap|starter|st .*|w-l|rec|range|tag|stage|last|form|roster|pick|rd|vs cons|nhl gp|peak|out|value|tm|xmv|sh|kp|g-xg)$/i;
  var PD_LOWER = /^(rank|cons|xslot|vrs|ga|gaa|riv|nat)$/i;   // riv, nat: recruit national ranks
  function pdOwn(table) {   // a table that builds its own dropdown
    return table.matches('.cfbm:not(.cbbm), .cfbrc, [data-pd-kind], [data-td-kind]') || !!table.closest('[data-cfb], [data-cbb], [data-esea]') ||
      !!table.querySelector('tbody .cfb__who, tbody .cfbst__more');
  }
  function ord(n) { var m = n % 100, d = n % 10; return n + (m >= 11 && m <= 13 ? 'th' : d === 1 ? 'st' : d === 2 ? 'nd' : d === 3 ? 'rd' : 'th'); }
  function esc2(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function pdHtml(win, table, row, extra, span) {
    var hc = pcHeads(table), heads = hc.map(txt), cells = [].slice.call(row.cells), rows = pcAll(table), N = rows.length, at = pcAt(table, rows, row);
    var ni = pcNameAt(heads), name = pcName(row, ni), gi = function (re) { return heads.findIndex(function (h) { return re.test(h); }); };
    var teamI = gi(TEAM_COL), posI = gi(POS_COL), lgI = gi(/^(league|lg|conf)$/i), fvI = gi(FV_COL), tm = row.querySelector('.nbaxpm__tm, .nflwar__tm');
    var posC = posI >= 0 && cells[posI] && cells[posI].cloneNode(true); if (posC) posC.querySelectorAll('span').forEach(function (e) { e.remove(); });
    var team = teamI >= 0 ? pcCell(cells[teamI]).t : tm ? txt(tm).split('·')[0].trim() : '';
    var head = [posC ? txt(posC) : '', team, lgI >= 0 ? pcCell(cells[lgI]).t : ''].filter(function (s) { return s && s !== '—'; });
    var fvC = fvI >= 0 ? cells[fvI] : null, fvT = fvC ? pcCell(fvC).t : '', chip = fvC && fvC.querySelector('.fv-chip');
    var sortI = sortedCol(table, hc), stats = [], lines = [], ranges = [];
    heads.forEach(function (h, i) {
      if (i === ni || i === fvI || i === teamI || i === posI || i === lgI || PC_SKIP.test(h) || !h || !cells[i] || cells[i].hidden || (hc[i] && hc[i].hidden)) return;
      var c = pcCell(cells[i]); if (c.t === '—' && !c.sub) return;
      if (c.t.length > 18) { lines.push(h.toLowerCase() + ': ' + c.t + (c.sub ? ' (' + c.sub + ')' : '')); return; }
      if (c.sub && /\d\s*[–-]\s*[−-]?\d/.test(c.sub) && !/^(w-l|rec|range)$/i.test(h)) ranges.push(h + ' ' + c.t + ', range ' + c.sub);
      else if (c.sub && /^raw /.test(c.sub)) ranges.push(h + ' ' + c.t + ' (' + c.sub + ')');
      var n = PC_NOPCT.test(h) && !PD_LOWER.test(h) ? null : pcNum(cells[i], c.t), p = null;
      if (n != null) {
        var vals = rows.map(function (r) { var cc = r.cells[i]; return cc ? pcNum(cc, pcCell(cc).t) : null; }).filter(function (v) { return v != null; });
        if (vals.length >= 5) p = pcPct(vals, n);
      }
      var judge = p == null || PD_NEUTRAL.test(h) ? null : PD_LOWER.test(h) ? 100 - p : p;
      stats.push({ h: h, t: c.t, sub: c.sub, p: p, good: judge, tip: hc[i] ? hc[i].getAttribute('title') || '' : '' });
    });
    var say = function (s) { return s.h + ' ' + s.t + ': ' + ord(s.p) + ' percentile of the ' + N + ' in view' + (PD_LOWER.test(s.h) ? ' (lower is better)' : ''); };
    var plus = stats.filter(function (s) { return s.good != null && s.good >= 80; }).sort(function (a, b) { return b.good - a.good; }).slice(0, 4).map(say);
    var minus = stats.filter(function (s) { return s.good != null && s.good <= 20; }).sort(function (a, b) { return a.good - b.good; }).slice(0, 4).map(say);
    var sh = sortI >= 0 ? heads[sortI] : '';
    var role = ['#' + (at + 1) + ' of ' + N + ' in view' + (sh && !/^rk$/i.test(sh) ? ' by ' + sh : '')];
    if (fvT && fvT !== '—') role.push('FV ' + fvT + (chip && chip.title ? ' (' + chip.title + ')' : ''));
    var role2 = ranges.concat(lines);
    // badges: the row's medals, their names and percentiles from the medal strip's tooltip
    var med = row.querySelector('.cfb__medals'), T = { Platinum: 'p', Gold: 'g', Silver: 's', Bronze: 'b' }, bdg = [];
    if (med) (med.getAttribute('title') || '').split('\n').forEach(function (l) { var m = l.match(/^(Platinum|Gold|Silver|Bronze) (.+?): (.*)$/); if (m) bdg.push([m[2], T[m[1]], l]); });
    var th0 = row.querySelector('.pxframe img'), big = pcBig(th0 && (th0.currentSrc || th0.src));
    var li = function (xs, cls) { return xs.map(function (x) { return '<li class="' + cls + '">' + esc2(x) + '</li>'; }).join(''); };
    var bars = stats.filter(function (s) { return s.p != null; }).map(function (s) {
      return '<li title="' + esc2(s.tip) + '"><span class="cfb__bk" style="width:16ch">' + esc2(s.h) + ' <span class="cfb__dim">' + esc2(s.t) + '</span></span><span class="cfb__meter"><i style="left:0;width:' + s.p + '%"' + (s.good != null && s.good <= 20 ? ' class="is-neg"' : '') + '></i></span><span class="cfb__bv">p' + s.p + '</span></li>';
    }).join('');
    var sc = table.closest('.wintable__scroll') || table.parentElement;
    if (extra) role2.unshift(extra);
    return '<tr class="cfb__detail pd__auto"><td colspan="' + (span || cells.length) + '"><div class="cfb__dwrap" style="width:' + Math.max(260, sc.clientWidth - 30) + 'px">' +
      (big ? '<span class="pxframe pxframe--card"><img src="' + esc2(big) + '" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.parentNode.remove()"></span>' : '') +
      '<p class="cfb__dhead"><b>' + esc2(name) + '</b>' + (head.length ? ' · ' + esc2(head.join(' · ')) : '') + (fvT && fvT !== '—' ? ' · FV ' + esc2(fvT) : '') +
      ' <button type="button" class="cfb__btn cfb__cardbtn" data-gfx data-gfx-mode="pcard" title="player card graphic (4:5)">GFX card</button></p>' +
      '<p class="cfb__role">' + esc2(role.join(' · ')) + '.</p>' +
      (role2.length ? '<p class="cfb__role">' + esc2(role2.join(' · ')) + '.</p>' : '') +
      (bdg.length ? '<p class="cfb__badges">' + bdg.map(function (b) { return '<span class="cfb__bdg cfb__bdg--' + b[1] + '" data-n="' + esc2(b[0]) + '" title="' + esc2(b[2]) + '">' + esc2(b[2].split(':')[0]) + '</span>'; }).join('') + '</p>' : '') +
      '<div class="cfb__report"><div><h4>+ strengths</h4><ul>' + (li(plus, 'is-plus') || '<li class="cfb__dim">none</li>') + '</ul></div>' +
      '<div><h4>− concerns</h4><ul>' + (li(minus, 'is-minus') || '<li class="cfb__dim">none</li>') + '</ul></div></div>' +
      (bars ? '<details class="cfb__nums"><summary>percentiles in view</summary><ul class="cfb__parts pd__pct" style="grid-template-columns:repeat(auto-fill,minmax(280px,1fr))">' + bars + '</ul><p class="cfb__dim">pNN: share of the ' + N +
        ' players in view (filters and season as set) below him on each column. Strengths and concerns: the top and bottom fifth; usage, age and contract columns are not judged.</p></details>' : '') +
      '</div></td></tr>';
  }
  // a subset table (mock, backup watch, ARKLIST, rookies ...) borrows the player's row on the sport's main board, where
  // his full line and the board's percentiles are; its own columns go in a line at the top
  var PD_SUBSET = /mock|backup|arklist|rookie|first-year|freshm|projection|past|contract/i;
  function pdNorm(s) { return String(s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim(); }
  function pcMain(row) {
    var table = row.closest('table'), win = table.closest('.win'), tab = (table.closest('[data-tab]') || win || {}).getAttribute && (table.closest('[data-tab]') || win).getAttribute('data-tab') || '';
    if (!PD_SUBSET.test(tab)) return null;
    var nm = pdNorm(pcName(row, pcNameAt(pcHeads(table).map(txt)))); if (!nm) return null;
    var best = null, bs = -1;
    document.querySelectorAll('.win table').forEach(function (t) {
      if (t === table || !t.tHead || !t.tBodies[0] || t.closest('.win') === win) return;
      var tt = (t.closest('[data-tab]') || {}).getAttribute ? t.closest('[data-tab]').getAttribute('data-tab') : '';
      if (PD_SUBSET.test(tt || '')) return;
      var hs = pcHeads(t).map(txt), k = pcNameAt(hs); if (k < 0) return;
      var r = pcRows(t).find(function (x) { return pdNorm(pcName(x, k)) === nm; }); if (!r) return;
      var sc = (hs.some(function (h) { return FV_COL.test(h); }) ? 1000 : 0) + hs.length;
      if (sc > bs) { bs = sc; best = r; }
    });
    return best;
  }
  function pdExtra(row) {   // the subset table's own columns, one line
    var table = row.closest('table'), hs = pcHeads(table).map(txt), ni = pcNameAt(hs), tab = (table.closest('[data-tab]') || {}).getAttribute ? table.closest('[data-tab]').getAttribute('data-tab') : '';
    var bits = hs.map(function (h, i) { if (i === ni || !h || FV_COL.test(h) || /^rk$/i.test(h)) return ''; var c = pcCell(row.cells[i]); return c.t && c.t !== '—' ? h + ' ' + c.t : ''; }).filter(Boolean);
    return (tab ? tab + ': ' : '') + bits.join(' · ');
  }
  function pdClose(table) { table.querySelectorAll('tr.pd__auto').forEach(function (d) { d.remove(); }); }
  function pdOpen(row) {
    var table = row.closest('table'), win = row.closest('.win'); pdClose(table);
    var m = pcMain(row);
    row.insertAdjacentHTML('afterend', m ? pdHtml(m.closest('.win'), m.closest('table'), m, pdExtra(row), row.cells.length) : pdHtml(win, table, row)); return row.nextElementSibling;
  }
  document.addEventListener('click', function (e) {
    if (/(1nt|laursen_111)$/.test(SITE)) return;
    var t = e.target; if (!t.closest) return;
    var table = t.closest('table'); if (!table || !table.tHead || !table.tBodies[0]) return;
    if (t.closest('thead')) { pdClose(table); return; }
    if (t.closest('a, button, input, select, label, summary, details, tr.cfb__detail')) return;
    var row = t.closest('tbody tr'); if (!row || row.cells.length < 3 || !table.closest('.win') || pdOwn(table)) return;
    if (pcNameAt(pcHeads(table).map(txt)) < 0) return;
    var was = row.nextElementSibling && row.nextElementSibling.classList.contains('pd__auto');
    pdClose(table); if (!was) pdOpen(row);
  });
  document.addEventListener('input', function (e) { var w = e.target.closest && e.target.closest('.win'); if (w) w.querySelectorAll('table').forEach(pdClose); });

  // the card picker beside a player table's GFX button (the players in view, in the table's order), and a "GFX card"
  // button in every dropdown that has none (the CFB board draws its own card)
  function pcName(r, ni) { var c = r.cells[ni]; if (!c) return ''; c = (c.querySelector('button.cfb__who, b') || c).cloneNode(true); c.querySelectorAll('svg, .gfx-off, .cfb__dim').forEach(function (e) { e.remove(); }); return txt(c); }
  function addCardPickers() {
    if (/(1nt|laursen_111)$/.test(SITE)) return;
    document.querySelectorAll('[data-gfx]').forEach(function (btn) {
      if (btn.getAttribute('data-gfx-mode') || btn.dataset.gfxCard) return;
      var win = btn.closest('.win'), table = win && win.querySelector('table'); if (!table || !table.tHead || win.hasAttribute('data-cfb')) return;
      var ni = pcNameAt(pcHeads(table).map(txt)); if (ni < 0) return;
      btn.dataset.gfxCard = '1';
      var lab = document.createElement('label'); lab.className = 'cfb__field gfx-card'; lab.title = 'one player\'s card graphic (4:5)';
      lab.innerHTML = '<span>card</span><select><option value="">player</option></select>';
      var anchor = btn.parentNode.querySelector('.gfx-round') || btn.parentNode.querySelector('.gfx-rows') || btn;
      anchor.insertAdjacentElement('afterend', lab);
      var sel = lab.querySelector('select');
      function fill() {
        var t = win.querySelector('table'), hs = pcHeads(t).map(txt), k = pcNameAt(hs); if (k < 0) return;
        sel.innerHTML = '<option value="">player</option>' + pcRows(t).slice(0, 300).map(function (r, i) {
          return '<option value="' + i + '">' + (i + 1) + '. ' + pcName(r, k).replace(/[<&"]/g, '') + '</option>'; }).join('');
      }
      sel.addEventListener('focus', fill); sel.addEventListener('mousedown', fill); sel.addEventListener('touchstart', fill, { passive: true });
      sel.addEventListener('change', async function () {
        if (sel.value === '') return;
        var t = win.querySelector('table'), r = pcRows(t)[+sel.value], k = pcNameAt(pcHeads(t).map(txt)); sel.value = ''; if (!r) return;
        sel.disabled = true;
        try { var cv = await buildPCard(win, r); if (cv) preview(cv, 'arkboard-' + pcName(r, k).toLowerCase().replace(/[^a-z0-9]+/g, '-')); } finally { sel.disabled = false; }
      });
    });
  }
  function addCardButtons() {
    if (/(1nt|laursen_111)$/.test(SITE)) return;
    document.querySelectorAll('tr.cfb__detail, tr.cfbm__detail, tr.cfbrc__detail').forEach(function (d) {
      if (d.querySelector('[data-gfx]') || d.closest('[data-cfb]')) return;
      var row = d.previousElementSibling, table = d.closest('table'); if (!row || !table || pcNameAt(pcHeads(table).map(txt)) < 0) return;
      var host = d.querySelector('.cfb__dhead') || d.querySelector('.cfb__dwrap, [class$="__dwrap"]') || d.cells[0]; if (!host) return;
      var b = document.createElement('button'); b.type = 'button'; b.className = 'cfb__btn cfb__cardbtn'; b.textContent = 'GFX card'; b.title = 'player card graphic (4:5)';
      b.setAttribute('data-gfx', ''); b.setAttribute('data-gfx-mode', 'pcard');
      host.appendChild(document.createTextNode(' ')); host.appendChild(b);
    });
  }
  document.addEventListener('click', function () { setTimeout(addCardButtons, 0); });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { setTimeout(addCardPickers, 0); }); else setTimeout(addCardPickers, 0);
  document.addEventListener('ark:lazy', function () { setTimeout(addCardPickers, 0); });
  // a board that builds its table after load (lineups, on/off) calls this once its rows are in, for the rows and card pickers
  window.__arkGfxScan = function () { addPickers(); addCardPickers(); };
  // ---- team card: from a team breakdown on an ARK Ranking (teamjs.html stores window.__arkTeamGfx[data-gfx-i]) ----
  // logo, rank and rating, season odds, next games, key players, strengths and concerns, the rating's inputs
  async function buildTeamCard(win, btn) {
    var d = (window.__arkTeamGfx || [])[+btn.getAttribute('data-gfx-i')]; if (!d) return null;
    var LG = { cfb: 'CFB', cbb: 'CBB', nfl: 'NFL', nba: 'NBA', nhl: 'NHL', soccer: 'soccer', soccerintl: 'soccer' };
    var F = await frame(2160, 2700, (LG[d.sport] || '') + ' :: ' + d.name, win.getAttribute('data-gfx-date'), SITE + (d.sport === 'soccerintl' ? '#world-ranking' : '#ark-ranking'));
    var g = F.g, x = F.x + 40, y = F.y + 70, w = F.w - 80, dash = '—', gap = 20;
    well(g, F.x, F.y, F.w, F.h);
    // the logo in a raised frame at the left (full colour, smoothed), then name and line; the rank plaque at the right,
    // in the colour of the rank's percentile tier
    var logo = await loadImg(d.logo), LS = 360, lx = x, ly = y - 60;
    g.fillStyle = C.face; g.fillRect(lx, ly, LS, LS); bevel(g, lx, ly, LS, LS, true, 6);
    g.fillStyle = C.dark; g.fillRect(lx + 12, ly + 12, LS - 24, LS - 24);
    if (logo) { var lr = Math.min(272 / logo.width, 272 / logo.height), lw = logo.width * lr, lh = logo.height * lr; drawLogo(g, logo, lx + (LS - lw) / 2, ly + (LS - lh) / 2, lw, lh); }
    else { g.font = '96px ' + FONT; g.fillStyle = C.lilac; g.textAlign = 'center'; g.fillText(String(d.short).slice(0, 4).toUpperCase(), lx + LS / 2, ly + LS / 2); g.textAlign = 'left'; }
    var tx = x + LS + 40, pw = 350, ph = 290, tw = w - LS - 40 - pw - 36;
    var rkGood = d.N > 1 ? Math.round(100 * (d.N - d.rk) / (d.N - 1)) : null, rkCol = tierCol(rkGood) || C.teal;
    g.fillStyle = rkCol; g.fillRect(x + w - pw, ly, pw, ph); bevel(g, x + w - pw, ly, pw, ph, true, 6);
    g.fillStyle = C.dark; g.font = '36px ' + FONT; g.textAlign = 'center'; g.fillText('ARK RANK', x + w - pw / 2, ly + 44);
    g.font = '124px ' + FONT; g.fillText('#' + d.rk, x + w - pw / 2, ly + 136);
    g.font = '32px ' + FONT; g.fillText('of ' + d.N, x + w - pw / 2, ly + 238); g.textAlign = 'left';
    movePill(g, x + w - pw / 2, ly + ph + 12, d.prev ? d.prev - d.rk : null, pw);
    var ns = 96; g.font = ns + 'px ' + FONT; while (ns > 72 && g.measureText(d.name).width > tw) { ns -= 4; g.font = ns + 'px ' + FONT; }
    g.fillStyle = C.white;
    var nl = wrap(g, d.name, tw); if (nl.length > 2) nl = [nl[0], fit(g, nl.slice(1).join(' '), tw)];
    nl.forEach(function (l, i) { g.fillText(fit(g, l, tw), tx, y + i * 110); });
    y += nl.length * 110;
    // the line under the name, less the record (its own tile below)
    var head = d.head.map(function (h) { return d.rec && h.indexOf(d.rec) === 0 ? h.slice(d.rec.length).replace(/^[ ,]+/, '').replace(/^\((.*)\)$/, '$1') : h; }).filter(Boolean);
    g.font = '48px ' + FONT; g.fillStyle = C.teal;
    wrap(g, head.join(' · '), tw).slice(0, 3).forEach(function (l) { g.fillText(l, tx, y); y += 64; });
    y = ly + LS + 44;
    // what the rating is made of: each input's push, pixel bars from the middle, pinned to the bottom
    var parts = d.parts.slice().sort(function (a, b) { return Math.abs(b[1]) - Math.abs(a[1]); }).slice(0, 8);
    var barsH = inputBarsH(parts.length), bottom = F.y + F.h - 30 - barsH;
    // the bands under the lists are reserved before the lists fill: team badges, the unit line (WAR by unit) as cells
    var bdgs = (d.badges || []).filter(function (b) { return b && TIERS[b[1]]; }).slice(0, 4), bdgH = bdgs.length ? 176 : 0;
    var gm = String(d.group || '').match(/^([^:]+):\s*(.+)$/), units = gm ? gm[2].split(/\s+·\s+/).map(function (q) { var m = q.match(/^(.+?)\s+([+−-]?[\d.]+)$/); return m ? { h: m[1], t: m[2], color: /^[−-]/.test(m[2]) ? C.down : null } : null; }).filter(Boolean) : [];
    var unitH = units.length >= 2 ? 50 + 150 + 30 : 0, lbot = bottom - bdgH - unitH;
    var keyN = {}; d.pl.forEach(function (p) { keyN[p[0]] = 1; });
    var yg = (d.yg || []).filter(function (p) { return !keyN[p[0]]; });   // young talent already among the key players is not listed twice
    // spare room under the lists goes to taller tiles
    var oddsN = Math.min(d.odds.length, 8), oRows = oddsN ? (oddsN <= 4 ? 1 : 2) : 0, plH = function (l) { return 76 + l.reduce(function (a, p) { return a + (p[3] ? 94 : 68); }, 0); };
    var listsH = Math.max(d.pl.length ? plH(d.pl) : 0, (d.next.length ? 76 + Math.min(d.next.length, yg.length ? 3 : 5) * 66 : 0) + (yg.length ? 30 + plH(yg) : 0));
    var spare = lbot - (y + 50 + 210 + 30 + (oRows ? 50 + oRows * 196 + 10 : 0) + listsH + 80), grow = Math.max(0, Math.min(70, Math.floor(spare / (1 + oRows))));
    function rule(label, right) { cardRule(g, x, y, w, label, right); y += 50; }
    // ARK RANKING: the rating, the 80% rank range on a strip of the league, the record with the last games as squares
    rule('ARK RANKING');
    var th = 210 + grow, c3 = (w - 2 * gap) / 3, neg = /^[−-]/.test(d.rating);
    statCell(g, { h: 'rating', t: d.rating, sub: d.unit + ' vs average', reserve: 8, color: tierCol(rkGood) || (neg ? C.down : C.teal) }, x, y, Math.round(c3), th);
    var rx = Math.round(x + c3 + gap), rcw = Math.round(c3);
    statCell(g, { h: '80% range', t: d.rkLo ? '#' + d.rkLo + (d.rkHi !== d.rkLo ? '-' + d.rkHi : '') : dash, reserve: d.rkLo ? 44 : 0 }, rx, y, rcw, th);
    if (d.rkLo && d.N > 1) {   // the league as a strip of blocks, best at the left: the range lit, the rank white
      var nb = Math.min(d.N, 32), sx = rx + 24, sw = rcw - 48, bw2 = (sw - (nb - 1) * 4) / nb, at = function (r) { return Math.min(nb - 1, Math.floor((r - 1) / d.N * nb)); };
      for (var k = 0; k < nb; k++) { g.fillStyle = k === at(d.rk) ? C.white : k >= at(d.rkLo) && k <= at(d.rkHi || d.rkLo) ? rkCol : C.dark; g.fillRect(Math.round(sx + k * (bw2 + 4)), y + th - 46, Math.max(2, Math.floor(bw2)), 22); }
    }
    var qx = Math.round(x + 2 * (c3 + gap)), res = d.last ? d.last.split(' ') : [];
    statCell(g, { h: 'record', t: d.rec || dash, reserve: res.length ? 44 : 0 }, qx, y, Math.round(c3), th);
    res.forEach(function (r, i) {   // last games, oldest first: win teal, loss pink, draw or tie lilac
      var s = 34, bx = qx + 24 + i * (s + 8), by = y + th - 24 - s;
      g.fillStyle = r === 'W' ? C.teal : r === 'L' ? C.down : C.lilac; g.fillRect(bx, by, s, s);
      g.fillStyle = C.dark; g.font = '26px ' + FONT; g.textAlign = 'center'; g.fillText(r, bx + s / 2, by + s / 2 + 2); g.textAlign = 'left';
    });
    y += th + 30;
    // SEASON ODDS: each probability on a pixel bar
    if (d.odds.length) {
      rule('SEASON ODDS');
      var od = d.odds.slice(0, 8).map(function (o) { return pcProb({ h: o[0] + '%', t: o[1] }); });
      od.forEach(function (o, i) { o.h = d.odds[i][0]; if (o.prob == null && /^[<>]\d+%$/.test(o.t)) o.prob = /^</.test(o.t) ? 0.5 : 99.5; });
      y += cellGrid(g, od, x, y, w, od.length <= 4 ? od.length : Math.ceil(od.length / 2), 176 + grow, gap) + 30;
    }
    // next games beside key players
    var half = (w - 60) / 2, cy0 = y;
    function colHead(cx, cw, label, sub) {
      g.font = '40px ' + FONT; g.fillStyle = C.lilac; g.fillText(label, cx, y);
      var lw = g.measureText(label).width + 24, rw = 0;
      if (sub) { g.font = '28px ' + FONT; rw = g.measureText(sub).width + 24; g.fillText(sub, cx + cw - rw + 24, y); }
      g.fillStyle = C.dark; g.fillRect(cx + lw, y - 1, cw - lw - rw, 3);
    }
    var gy = y, py2 = y;
    if (d.next.length || d.last) {
      var pct = function (p) { return p == null ? dash : p < 0.005 ? '<1%' : p >= 0.995 ? '>99%' : Math.round(p * 100) + '%'; };
      colHead(x, half, 'NEXT GAMES', d.left ? d.left + ' LEFT · ' + d.xw.toFixed(1) + (d.draws ? ' xPTS' : ' xW') : '');
      gy += 76;
      var logos = await Promise.all(d.next.map(function (n) { return loadImg(n.logo); }));
      d.next.forEach(function (n, i) {
        if (gy + 40 > lbot - 60 || (yg.length && i >= 3)) return;
        g.font = '36px ' + FONT; g.fillStyle = C.lilac; g.fillText(n.day, x, gy);
        var ox = x + 180; g.fillText(n.at, ox, gy); ox += 64;
        if (logos[i]) { drawLogo(g, logos[i], ox, gy - 26, 52, 52); ox += 68; }
        var pv = pct(n.p); g.font = '44px ' + FONT; var pvw = g.measureText(pv).width;
        g.fillStyle = n.p == null ? C.lilac : tierCol(Math.round(n.p * 100)); g.fillText(pv, x + half - pvw, gy);
        var rk = n.rk ? ' #' + n.rk : ''; g.font = '40px ' + FONT; g.fillStyle = C.white;
        var room = x + half - pvw - 24 - ox, nm = fit(g, n.n, room - (rk ? 90 : 0)); g.fillText(nm, ox, gy);
        if (rk) { var nw = g.measureText(nm).width; g.font = '30px ' + FONT; g.fillStyle = C.lilac; g.fillText(rk, ox + nw + 8, gy + 2); }
        gy += 66;
      });
    }
    // a player list (key players, young talent): name, position, metric at the right, the note under it
    function plist(px, py, pwid, label, sub, list, metric) {
      y = py; colHead(px, pwid, label, sub);
      py += 76;
      list.forEach(function (p) {
        if (py + 40 > lbot - 60) return;
        var val = typeof p[2] === 'string' || metric === 'FV' ? String(p[2]) : (p[2] > 0 ? '+' : p[2] < 0 ? '−' : '') + Math.abs(+p[2]).toFixed(2);
        g.font = '44px ' + FONT; var vw = g.measureText(val).width; g.fillStyle = p[2] < 0 ? C.down : C.teal; g.fillText(val, px + pwid - vw, py);
        g.font = '30px ' + FONT; var pos = String(p[1] || ''), posw = pos ? g.measureText(pos).width + 16 : 0;
        g.font = '40px ' + FONT; g.fillStyle = C.white; var pn = fit(g, p[0], pwid - vw - 32 - posw); g.fillText(pn, px, py);
        var pnw = g.measureText(pn).width;
        if (pos) { g.font = '30px ' + FONT; g.fillStyle = C.lilac; g.fillText(pos, px + pnw + 16, py + 2); }
        if (p[3]) { g.font = '30px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, p[3], pwid), px, py + 40); py += 94; } else py += 68;
      });
      return py;
    }
    var two = d.next.length || d.last, up = function (s) { return String(s || '').toUpperCase(); };
    if (d.pl.length) py2 = plist(two ? x + half + 60 : x, py2, two ? half : w, 'KEY PLAYERS', up(d.pm), d.pl, d.pm);
    // elite young talent: under the next games (or beside key players when there is no schedule)
    if (yg.length) {
      if (two) gy = plist(x, gy + 30, half, 'YOUNG TALENT', up(d.yd), yg, d.ym);
      else py2 = plist(x, py2 + 24, w, 'YOUNG TALENT', up(d.yd), yg, d.ym);
    }
    y = Math.max(gy, py2, cy0) + 20;
    // team badges ([[name, tier, pct, line]]): medal, tier and percentile, name; four in a row in the reserved band
    if (bdgs.length) {
      rule('BADGES'); y -= 6;
      var bw = w / 4, bu = 6;
      bdgs.forEach(function (b, i) {
        var bx = x + i * bw;
        medal(g, bx, y, b[1], bu);
        g.font = '28px ' + FONT; g.fillStyle = TIERS[b[1]][2];
        g.fillText(fit(g, TIERS[b[1]][0] + (b[2] != null ? ' · P' + b[2] : ''), bw - 12 * bu - 28), bx + 12 * bu + 16, y + 26);
        g.font = '34px ' + FONT; g.fillStyle = C.white; g.fillText(fit(g, String(b[0]).toUpperCase(), bw - 12 * bu - 28), bx + 12 * bu + 16, y + 64);
      });
      y += 12 * bu + 44;
    }
    if (unitH) { rule(up(gm[1])); cellGrid(g, units.slice(0, 10), x, y, w, Math.min(units.length, 10), 150, 16); y += 180; }
    // strengths and concerns only where the card has no input bars (they are the largest inputs, in words)
    if (!parts.length && (d.plus.length || d.minus.length) && y + 130 < bottom) {
      y += 8;
      [[ '+ strengths', d.plus, C.teal, x ], [ '− concerns', d.minus, C.down, x + half + 60 ]].forEach(function (L) {
        var yy = y; g.font = '52px ' + FONT; g.fillStyle = L[2]; g.fillText(L[0], L[3], yy); yy += 72;
        g.font = '38px ' + FONT;
        if (!L[1].length) { g.fillStyle = C.lilac; g.fillText('none', L[3] + 52, yy); }
        L[1].forEach(function (it) {
          var lines = wrap(g, it, half - 52); if (yy + lines.length * 50 > bottom) return;
          g.fillStyle = L[2]; g.fillText(L[0][0], L[3] + 4, yy);
          g.fillStyle = C.lilac; lines.forEach(function (l) { g.fillText(l, L[3] + 52, yy); yy += 50; }); yy += 12;
        });
      });
    }
    if (parts.length) {
      var sum = d.parts.reduce(function (s_, p) { return s_ + p[1]; }, 0);
      inputBars(g, x, bottom + 40, w, 'RATING INPUTS', up(d.unit) + ' · SUM ' + (sum > 0 ? '+' : sum < 0 ? '−' : '') + Math.abs(sum).toFixed(d.d), parts, d.scale, d.d, 300);
    }
    return F.canvas;
  }

  // ---- games: the matchups on screen (cards carry data-gfx-game) ----
  async function buildGames(win, btn) {
    var cards = [].slice.call(win.querySelectorAll('[data-gfx-game]')).filter(function (c) { return !c.hidden; }).slice(0, 8);
    if (!cards.length) return null;
    var games = cards.map(function (c) { return JSON.parse(c.getAttribute('data-gfx-game')); });
    var title = txt(win.querySelector('.win__title-text')).replace(/_$/, '').trim();
    var F = await frame(2160, 2700, title + (win.getAttribute('data-gfx-order') === 'soon' ? ' :: up next' : ' :: top games'), win.getAttribute('data-gfx-date'));
    var g = F.g, n = games.length, cols = n > 4 ? 2 : 1, rowsN = Math.ceil(n / cols), gap = 24;
    var tw = (F.w - (cols - 1) * gap) / cols, th = (F.h - (rowsN - 1) * gap) / rowsN;
    for (var i = 0; i < n; i++) {
      var d = games[i], tx = F.x + (i % cols) * (tw + gap), ty = F.y + Math.floor(i / cols) * (th + gap), pad = 28;
      well(g, tx, ty, tw, th);
      // type scales to the card: the content is ~9 lines of sz, so the card fills instead of leaving a gap
      var sz = Math.max(40, Math.min(cols === 2 ? 64 : 80, Math.floor((th - 2 * pad) / 9))), y = ty + pad + sz;
      for (var k = 0; k < 2; k++) {
        var t = k ? d.h : d.a, img = await loadImg(t.l), lx = tx + pad;
        if (img) { drawLogo(g, img, lx, y - sz * 0.6, sz * 1.2, sz * 1.2); lx += sz * 1.2 + 16; }
        g.font = sz + 'px ' + FONT; g.fillStyle = C.white;
        var nm = (k ? '@ ' : '') + (t.r ? '#' + t.r + ' ' : '') + t.n;
        g.fillText(fit(g, nm, tw - 2 * pad - sz * 1.4 - 140), lx, y);
        g.font = (sz * 0.7) + 'px ' + FONT; g.fillStyle = C.lilac; var rc = t.rec || '';
        g.fillText(rc, tx + tw - pad - g.measureText(rc).width, y);
        y += sz * 1.5;
      }
      // win probability bar: away share left, home right
      var bx = tx + pad, bw = tw - 2 * pad, bh = sz * 0.9, pa = 1 - d.p;
      g.fillStyle = C.lilac; g.fillRect(bx, y - bh / 2, bw * pa, bh);
      g.fillStyle = C.teal; g.fillRect(bx + bw * pa, y - bh / 2, bw * d.p, bh);
      g.font = (sz * 0.65) + 'px ' + FONT; g.fillStyle = C.dark;
      g.fillText(Math.round(pa * 100) + '%', bx + 10, y); var ph = Math.round(d.p * 100) + '%'; g.fillText(ph, bx + bw - 10 - g.measureText(ph).width, y);
      y += sz * 1.3;
      if (d.k) { g.font = Math.round(sz * 0.7) + 'px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, d.k, bw), bx, y); y += sz * 1.0; }
      g.font = Math.round(sz * 0.78) + 'px ' + FONT; g.fillStyle = C.teal;
      g.fillText(fit(g, 'model ' + d.m + (d.line ? ' · market ' + d.line : ''), bw), bx, y);
      y += sz * 1.1;
      // each side's best prospect
      g.font = Math.round(sz * 0.75) + 'px ' + FONT;
      var logos = [await loadImg(d.a.l), await loadImg(d.h.l)];
      [d.ta, d.th].forEach(function (p, s) {
        if (!p || !p.name || y > ty + th - pad) return;
        var px = bx, ls = sz * 0.75;
        if (logos[s]) { drawLogo(g, logos[s], px, y - ls / 2, ls, ls); px += ls + 12; }
        var cw = chip(g, px, y, String(p.fv), Math.round(sz * 0.75), p.fv);
        g.font = Math.round(sz * 0.75) + 'px ' + FONT; g.fillStyle = C.white;
        g.fillText(fit(g, p.name + ' · ' + p.pos, bw - cw - (px - bx) - 20), px + cw + 16, y);
        y += sz * 1.15;
      });
    }
    return F.canvas;
  }

  // ---- one game (cfbgames.html / nflgames.html data-gfx-one): both sides, kickoff, win probability, the model against the market ----
  async function buildGame(win, btn) {
    var card = btn.closest('[data-gfx-one]'); if (!card) return null;
    var d = JSON.parse(card.getAttribute('data-gfx-one'));
    var F = await frame(2160, 2700, d.lg + ' :: ' + d.a.n + ' at ' + d.h.n, win.getAttribute('data-gfx-date') || d.date);
    var g = F.g, x = F.x, y = F.y, w = F.w, gap = 24, pad = 40;
    // the two sides: logo, ARK rank, name, record; "at" between
    var th = 700, half = (w - gap) / 2, logos = [await loadImg(d.a.l), await loadImg(d.h.l)];
    [d.a, d.h].forEach(function (t, k) {
      var tx = x + k * (half + gap), cx = tx + half / 2;
      well(g, tx, y, half, th);
      var ls = 300; if (logos[k]) drawLogo(g, logos[k], cx - ls / 2, y + pad, ls, ls);
      var ty = y + pad + ls + 70;
      g.font = '56px ' + FONT; g.fillStyle = C.teal;
      var rk = t.r ? 'ARK #' + t.r : 'unranked'; g.fillText(rk, cx - g.measureText(rk).width / 2, ty);
      g.font = '80px ' + FONT; g.fillStyle = C.white;
      var nm = fit(g, t.n, half - 2 * pad); g.fillText(nm, cx - g.measureText(nm).width / 2, ty + 110);
      g.font = '48px ' + FONT; g.fillStyle = C.lilac;
      var rc = t.rec || ''; g.fillText(rc, cx - g.measureText(rc).width / 2, ty + 210);
    });
    g.font = '56px ' + FONT; var at = 'at', aw = g.measureText(at).width + 32;
    g.fillStyle = C.title; g.fillRect(x + w / 2 - aw / 2, y + th / 2 - 44, aw, 88);
    g.fillStyle = C.white; g.fillText(at, x + w / 2 - aw / 2 + 16, y + th / 2);
    y += th + 56;
    // kickoff
    g.font = '48px ' + FONT; g.fillStyle = C.lilac;
    var k = fit(g, d.k || '', w); g.fillText(k, x + (w - g.measureText(k).width) / 2, y);
    y += 64;
    // win probability: away share left (lilac), home right (teal)
    // soccer cards carry a draw chance (pD) and the away win (pA): the draw sits between the two in violet
    // the two chances big over the bar, the favourite's in teal; the bar in 50 pixel blocks of 2 points each
    var bh = 72, pd = d.pD || 0, pa = d.pA != null ? d.pA : 1 - d.p;
    g.font = '40px ' + FONT; g.fillStyle = C.lilac; var wl = pd ? 'WIN / DRAW / WIN' : 'WIN PROBABILITY'; g.fillText(wl, x + (w - g.measureText(wl).width) / 2, y + 8);
    y += 100;
    var fav = d.p >= pa ? 'h' : 'a', ta = Math.round(pa * 100) + '%', th2 = Math.round(d.p * 100) + '%';
    g.font = '140px ' + FONT;
    g.fillStyle = fav === 'a' ? C.teal : C.lilac; g.fillText(ta, x, y);
    g.fillStyle = fav === 'h' ? C.teal : C.lilac; g.fillText(th2, x + w - g.measureText(th2).width, y);
    if (pd) { g.font = '64px ' + FONT; g.fillStyle = C.white; var dr = 'draw ' + Math.round(pd * 100) + '%'; g.fillText(dr, x + (w - g.measureText(dr).width) / 2, y + 10); }
    g.font = '48px ' + FONT; g.fillStyle = C.lilac;
    var an = d.a.n, hn = d.h.n; g.fillText(fit(g, an, w / 3), x, y + 96); g.fillText(fit(g, hn, w / 3), x + w - g.measureText(fit(g, hn, w / 3)).width, y + 96);
    y += 150;
    var NB = 50, bg = 6, bw1 = (w - (NB - 1) * bg) / NB, na = Math.round(pa * NB), nd = Math.round(pd * NB);
    for (var bi = 0; bi < NB; bi++) { g.fillStyle = bi < na ? (fav === 'a' ? C.teal : C.lilac) : bi < na + nd ? C.title : (fav === 'h' ? C.teal : C.lilac); g.fillRect(Math.round(x + bi * (bw1 + bg)), y, Math.ceil(bw1), bh); }
    g.fillStyle = 'rgba(0,0,0,0.35)'; g.fillRect(x, y + bh - 6, w, 6);
    y += bh + 56;
    // the pick tag (upset or favorite), when the game is one
    var tagH = d.pick ? 120 : 0, bottom = F.y + F.h - (tagH ? tagH + gap : 0);
    // tiles, two to a row, filling what's left
    var tiles = d.tiles || [], rowsN = Math.ceil(tiles.length / 2) || 1, tw = (w - gap) / 2, tH = Math.min(600, (bottom - y - (rowsN - 1) * gap) / rowsN), tk = Math.max(1, Math.min(1.4, tH / 380));
    y += (bottom - y - rowsN * tH - (rowsN - 1) * gap) / 2;   // spare height splits above and below the tiles
    tiles.forEach(function (t, i) {
      var tx = x + (i % 2) * (tw + gap), ty = y + Math.floor(i / 2) * (tH + gap);
      var tw2 = tiles.length % 2 && i === tiles.length - 1 ? w : tw;   // an odd last tile spans the row
      well(g, tx, ty, tw2, tH);
      g.font = Math.round(40 * tk) + 'px ' + FONT; g.fillStyle = C.lilac; g.fillText(t.l, tx + pad, ty + tH * 0.22);
      var vs = Math.round(68 * tk); do { g.font = vs + 'px ' + FONT; } while (g.measureText(t.v).width > tw2 - 2 * pad && (vs -= 4) >= 40);   // long values step down before they clip
      g.fillStyle = C.white; g.fillText(fit(g, t.v, tw2 - 2 * pad), tx + pad, ty + tH * 0.52);
      g.font = Math.round(44 * tk) + 'px ' + FONT; g.fillStyle = C.teal; g.fillText(fit(g, t.s || '', tw2 - 2 * pad), tx + pad, ty + tH * 0.8);
    });
    if (d.pick) {
      var py = bottom + gap;
      g.fillStyle = C.teal; g.fillRect(x, py, w, tagH);
      g.fillStyle = 'rgba(0,0,0,0.35)'; g.fillRect(x, py + tagH - 6, w, 6);
      g.font = '56px ' + FONT; g.fillStyle = C.dark;
      var pt = fit(g, d.pick, w - 2 * pad); g.fillText(pt, x + (w - g.measureText(pt).width) / 2, py + tagH / 2 - 2);
    }
    return F.canvas;
  }

  // ---- a method sheet (cfbmock.html, data/cfb_mock_method.json): numbered sections of formula lines ----
  async function buildMethod(win, btn) {
    var d = JSON.parse(btn.getAttribute('data-gfx-method') || '{}'), secs = d.sections || [];
    if (!secs.length) return null;
    var F = await frame(2160, 2700, d.title || 'method', win.getAttribute('data-gfx-date'));
    var g = F.g, pad = 36, gap = 20;
    var nLines = secs.reduce(function (a, s) { return a + s.l.length; }, 0);
    // one size for every line: the largest that fits the height and the longest line
    var longest = secs.reduce(function (a, s) { return s.l.concat([s.h]).reduce(function (b, t) { return t.length > b.length ? t : b; }, a); }, '');
    var sz = 48;
    for (; sz > 28; sz -= 2) {
      g.font = sz + 'px ' + FONT;
      var h = secs.length * (2 * pad + sz * 1.5) + nLines * sz * 1.45 + (secs.length - 1) * gap;
      if (h <= F.h && g.measureText(longest).width <= F.w - 2 * pad - sz) break;
    }
    var lh = sz * 1.45, y = F.y, spare = (F.h - (secs.length * (2 * pad + sz * 1.5) + nLines * lh + (secs.length - 1) * gap)) / secs.length;
    secs.forEach(function (s) {
      var bh = 2 * pad + sz * 1.5 + s.l.length * lh + spare;
      well(g, F.x, y, F.w, bh);
      g.font = Math.round(sz * 0.85) + 'px ' + FONT; g.fillStyle = C.lilac;
      g.fillText(s.h, F.x + pad, y + pad + sz * 0.5);
      g.font = sz + 'px ' + FONT;
      s.l.forEach(function (t, i) {
        g.fillStyle = /=/.test(t) ? C.teal : C.white;       // formulas teal, conditions and lists white
        g.fillText(fit(g, t, F.w - 2 * pad - sz), F.x + pad + sz, y + pad + sz * 1.5 + lh * (i + 0.5) + spare / 2);
      });
      y += bh + gap;
    });
    return F.canvas;
  }

  // ---- ARK Top 25 (cfbrank.html): two columns of ranks, each team's score as a bar against #1 ----
  async function buildRank(win, btn) {
    var d = JSON.parse(win.getAttribute('data-gfx-rank') || '{}'), teams = (d.teams || []).slice(0, 25);
    if (!teams.length) return null;
    var F = await frame(2160, 2700, d.title || 'ARK Top 25 :: week ' + d.week, win.getAttribute('data-gfx-date'));   // d.title/foot/name: other sports (CBB)
    var g = F.g, gap = 24, per = Math.ceil(teams.length / 2), foot = 96;
    var cw = (F.w - gap) / 2, rh = (F.h - foot - (per - 1) * 12) / per, pad = 18;
    var top = Math.max.apply(null, teams.map(function (t) { return t.s; }).concat([1]));
    var logos = await Promise.all(teams.map(function (t) { return loadImg(t.l); }));
    var hasAp = teams.some(function (t) { return t.ap; }), hasC = teams.some(function (t) { return t.c; });
    function pollTxt(t) { return [hasAp ? 'AP ' + (t.ap || '–') : '', hasC ? 'Coaches ' + (t.c || '–') : ''].filter(Boolean).join(' · '); }   // only polls that are out
    teams.forEach(function (t, i) {
      var cx = F.x + Math.floor(i / per) * (cw + gap), cy = F.y + (i % per) * (rh + 12);
      well(g, cx, cy, cw, rh);
      var sz = Math.min(56, Math.floor(rh * 0.34)), y1 = cy + pad + sz * 0.55, y2 = cy + rh - pad - sz * 0.32;
      // rank, big and teal
      g.font = Math.round(sz * 1.35) + 'px ' + FONT; g.fillStyle = C.teal;
      var rk = String(t.rk); g.fillText(rk, cx + pad + (sz * 1.6 - g.measureText(rk).width) / 2, cy + rh / 2);
      var x = cx + pad + sz * 1.6 + 14, ls = rh - 2 * pad;
      if (logos[i]) { drawLogo(g, logos[i], x, cy + pad, ls, ls); }
      x += ls + 16;
      var right = cx + cw - pad;
      // record and movement, right-aligned on the name line
      g.font = Math.round(sz * 0.7) + 'px ' + FONT;
      var mv = t.prev ? (t.prev > t.rk ? '▲' + (t.prev - t.rk) : t.prev < t.rk ? '▼' + (t.rk - t.prev) : '–') : '';
      var rec = t.rec || '', rw = g.measureText(rec).width;
      g.fillStyle = C.lilac; g.fillText(rec, right - rw, y1);
      var mw = 0;
      if (mv) { mw = g.measureText(mv).width + 18; g.fillStyle = t.prev > t.rk ? C.teal : t.prev < t.rk ? C.down : C.lilac; g.fillText(mv, right - rw - mw, y1); }
      g.font = sz + 'px ' + FONT; g.fillStyle = C.white;
      g.fillText(fit(g, t.n, right - rw - mw - 20 - x), x, y1);
      // score bar against #1, the score, and where the polls have them
      g.font = Math.round(sz * 0.62) + 'px ' + FONT;
      var polls = pollTxt(t), pw = g.measureText(polls).width, pwMax = Math.max.apply(null, teams.map(function (u) { return g.measureText(pollTxt(u)).width; }));
      g.fillStyle = C.lilac; g.fillText(polls, right - pw, y2);
      var sc = (t.s > 0 ? '+' : '') + t.s.toFixed(1); g.font = Math.round(sz * 0.8) + 'px ' + FONT;
      var sw = g.measureText('+00.0').width, bw = right - pwMax - 28 - sw - 14 - x, bh = Math.round(sz * 0.36);
      g.fillStyle = C.dark; g.fillRect(x, y2 - bh / 2, bw, bh);
      g.fillStyle = C.teal; g.fillRect(x, y2 - bh / 2, Math.max(4, Math.round(bw * Math.max(0, t.s) / top)), bh);
      g.fillStyle = C.teal; g.fillText(sc, x + bw + 14, y2);
    });
    // the empty slot under the shorter column, down through the footer: the next ten, our "others receiving votes"
    var more = (d.more || []).slice(0, 10), slot = teams.length, boxed = more.length && slot < 2 * per;
    if (boxed) {
      var ox = F.x + Math.floor(slot / per) * (cw + gap), oy = F.y + (slot % per) * (rh + 12), op = 18, bh = F.y + F.h - oy;
      well(g, ox, oy, cw, bh);
      var hs = 30, ncol = 2, nrow = Math.ceil(more.length / ncol);
      g.font = hs + 'px ' + FONT; g.fillStyle = C.lilac;
      g.fillText('ALSO RECEIVING VOTES', ox + op, oy + op + hs / 2);
      var lh = (bh - 2 * op - hs - 8) / nrow, colw = (cw - 2 * op) / ncol, es = Math.min(40, Math.floor(lh * 0.8));
      more.forEach(function (t, j) {
        var ex = ox + op + Math.floor(j / nrow) * colw, ey = oy + op + hs + 8 + (j % nrow) * lh + lh / 2;
        g.font = es + 'px ' + FONT; g.fillStyle = C.teal;
        var rk = String(t.rk); g.fillText(rk, ex, ey); var x = ex + g.measureText('00').width + 10;
        var sc = (t.s > 0 ? '+' : '') + t.s.toFixed(1), scw = g.measureText(sc).width;
        g.fillStyle = C.white; g.fillText(fit(g, t.n, colw - (x - ex) - scw - 22), x, ey);
        g.fillStyle = C.lilac; g.fillText(sc, ex + colw - 20 - scw, ey);
      });
    }
    g.font = (boxed ? 30 : 36) + 'px ' + FONT; g.fillStyle = C.lilac;   // beside the box, under the long column
    var ft = d.foot || ['score = margin vs avg FBS team, neutral field', 'score = expected margin vs average FBS team, neutral field · bar vs #1'];
    g.fillText(fit(g, boxed ? ft[0] : ft[1], boxed ? cw : F.w), F.x, F.y + F.h - foot / 2 + 8);
    return F.canvas;
  }

  // ---- 1NT: a pixel flag from the page's sprite sheet, as an image ----
  var flagCache = {};
  function flagImg(code) {
    if (code in flagCache) return flagCache[code];
    var sym = document.getElementById('px-flag-' + code);
    if (!sym) return (flagCache[code] = Promise.resolve(null));
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 11" shape-rendering="crispEdges">' + sym.innerHTML + '</svg>';
    return (flagCache[code] = loadImg('data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg)));
  }

  // ---- 1NT box score: both teams' tables for one map ----
  async function buildEseaBox(win, btn) {
    var box = btn.closest('.esea-m__box'); if (!box) return null;
    var tables = [].slice.call(box.querySelectorAll('table')); if (!tables.length) return null;
    var F = await frame(2400, 1350, btn.getAttribute('data-gfx-title') || 'box score', btn.getAttribute('data-gfx-date'));
    var g = F.g; well(g, F.x, F.y, F.w, F.h);
    // optional stat tiles across the top (data-gfx-tiles: [{l: label, v: value, t: tone}, ...]; tone up/down colours the value)
    var tiles = null, top = 0; try { tiles = JSON.parse(btn.getAttribute('data-gfx-tiles') || 'null'); } catch (e) { tiles = null; }
    if (tiles && tiles.length) {
      var tw = (F.w - 24 - 12 * (tiles.length - 1)) / tiles.length, th = 200;
      tiles.forEach(function (t, i) {
        var tx = F.x + 12 + i * (tw + 12), ty = F.y + 12;
        g.fillStyle = C.face; g.fillRect(tx, ty, tw, th); bevel(g, tx, ty, tw, th, true, 2);
        g.font = '96px ' + FONT; g.fillStyle = t.t === 'up' ? C.teal : t.t === 'down' ? C.down : C.white; g.fillText(fit(g, String(t.v), tw - 40), tx + 24, ty + 84);
        g.font = '32px ' + FONT; g.fillStyle = C.lilac; g.fillText(String(t.l).toUpperCase(), tx + 24, ty + 160);
      });
      top = th + 24;
    }
    var heads = [].slice.call(tables[0].tHead.rows[0].cells).map(txt);
    var nRows = tables.reduce(function (a, t) { return a + t.tBodies[0].rows.length + 1; }, 0);
    var rowH = Math.min(78, (F.h - top - 24 - 24 * (tables.length - 1)) / nRows), size = rowH >= 64 ? 32 : 24;
    g.font = size + 'px ' + FONT;
    // column widths from the widest cell; the name column also holds a flag
    var colW = heads.map(function (h, i) {
      var m = g.measureText(i ? h.toUpperCase() : 'PLAYER').width;
      tables.forEach(function (t) { m = Math.max(m, g.measureText(i ? txt(t.tHead.rows[0].cells[i]) : '').width); [].forEach.call(t.tBodies[0].rows, function (r) { m = Math.max(m, g.measureText(txt(r.cells[i])).width + (i ? 0 : 40)); }); });
      return m + size * 0.7;
    });
    var tot = colW.reduce(function (a, b) { return a + b; }, 0), gw = F.w - 24;
    if (tot < gw) colW = colW.map(function (w) { return w + (gw - tot) / colW.length; });
    else if (tot > gw) { size = Math.floor(size * gw / tot); g.font = size + 'px ' + FONT; colW = colW.map(function (w) { return w * gw / tot; }); }
    var y = F.y + 12 + top;
    for (var ti = 0; ti < tables.length; ti++) {
      var t = tables[ti], x0 = F.x + 12, hx = x0, opp = t.classList.contains('esea-box--opp');
      g.fillStyle = C.face; g.fillRect(x0, y, gw, rowH - 4); bevel(g, x0, y, gw, rowH - 4, true, 2);
      heads.forEach(function (h, i) { g.fillStyle = i ? C.lilac : (opp ? C.down : C.teal); g.fillText(i ? capHead(h) : txt(t.tHead.rows[0].cells[0]).toUpperCase(), hx + size * 0.4, y + (rowH - 4) / 2); hx += colW[i]; });
      y += rowH;
      var rows = [].slice.call(t.tBodies[0].rows);
      for (var r = 0; r < rows.length; r++) {
        if (r % 2) { g.fillStyle = 'rgba(36,26,58,0.35)'; g.fillRect(x0, y, gw, rowH); }
        var x = x0, cells = rows[r].cells;
        for (var i = 0; i < heads.length; i++) {
          var c = cells[i], tx = x + size * 0.4, cy = y + rowH / 2, cl = c.cloneNode(true);
          cl.querySelectorAll('svg, .esea-flag--cc').forEach(function (e) { e.remove(); });
          var s0 = txt(cl), isSub = !!c.querySelector('svg.esea-sub');
          if (i === 0) {
            var fl = c.querySelector('svg.esea-flag'), code = fl ? (fl.getAttribute('aria-label') || '').toLowerCase() : '';
            var img = code ? await flagImg(code) : null;
            if (img) { g.drawImage(img, tx, cy - size * 0.34, size, size * 0.69); tx += size + 10; }
            else { var cc = c.querySelector('.esea-flag--cc'); if (cc) { g.fillStyle = C.lilac; g.fillRect(tx, cy - size * 0.34, size, size * 0.69); g.font = Math.round(size * 0.5) + 'px ' + FONT; g.fillStyle = C.dark; g.fillText(txt(cc), tx + 3, cy); g.font = size + 'px ' + FONT; tx += size + 10; } }
            var mvp = /★/.test(s0); s0 = s0.replace(/★\s*MVP/, '').trim();
            var lg = c.querySelector('.lzd__tag');   // ESEA League row: a filled badge, set apart from PUG rows
            if (lg) {
              s0 = s0.replace(/^(\S+\s*[AP]M)\s*ESEA/, '$1').trim();
              var bw = g.measureText('ESEA').width + size * 0.6;
              g.fillStyle = C.title; g.fillRect(tx, cy - size * 0.55, bw, size * 1.1); bevel(g, tx, cy - size * 0.55, bw, size * 1.1, true, 2);
              g.fillStyle = C.teal; g.fillText('ESEA', tx + size * 0.3, cy); tx += bw + size * 0.4;
            }
            g.fillStyle = rows[r].classList.contains('is-me') ? C.white : C.lilac; g.fillText(s0, tx, cy);
            var mw = g.measureText(s0).width;
            if (isSub) { g.fillStyle = '#ffd166'; g.fillText(' SUB', tx + mw, cy); mw += g.measureText(' SUB').width; }
            if (mvp) { g.fillStyle = C.teal; g.fillText(' MVP', tx + mw, cy); }
          } else {
            var col = c.querySelector('.cfb__up, .cfb__down') || (c.classList.contains('cfb__up') || c.classList.contains('cfb__down') ? c : null);
            g.fillStyle = col ? (col.classList.contains('cfb__up') ? C.teal : C.down) : i === 1 ? C.white : C.teal;
            g.fillText(s0, tx, cy);
          }
          x += colW[i];
        }
        y += rowH;
      }
      y += 24;
    }
    return F.canvas;
  }

  // ---- LAURSEN_111 social data: count, change, pace, goal progress bars, latest milestone per network ----
  async function buildSocial(win, btn) {
    var d; try { d = JSON.parse(btn.getAttribute('data-gfx-social')); } catch (e) { return null; }
    if (!d || !d.length) return null;
    var F = await frame(2400, 1350, btn.getAttribute('data-gfx-title') || 'LAURSEN_111 :: SOCIAL DATA', btn.getAttribute('data-gfx-date'));
    var g = F.g, gap = 24, cw = (F.w - gap * (d.length - 1)) / d.length;
    function bar(x, y, w, h, f, m) {
      var n = 20, cg = 4, bw = (w - cg * (n - 1)) / n, on = Math.floor(Math.max(0, Math.min(1, f)) * n), mk = m == null || m < 0 ? -1 : Math.min(n - 1, Math.floor(m * n));
      for (var i = 0; i < n; i++) {
        var bx = x + i * (bw + cg);
        g.fillStyle = i < on ? (mk >= 0 && on < mk ? C.lilac : C.teal) : C.dark; g.fillRect(bx, y, bw, h);
        if (i === mk) { g.fillStyle = C.white; g.fillRect(bx, y - 6, bw, 4); g.fillRect(bx, y + h + 2, bw, 4); }
      }
    }
    d.forEach(function (n, k) {
      var x = F.x + k * (cw + gap), y = F.y; well(g, x, y, cw, F.h);
      var px = x + 32, pw = cw - 64, yy = y + 70;
      g.font = '44px ' + FONT; g.fillStyle = C.lilac; g.fillText(String(n.n).toUpperCase(), px, yy);
      yy += 150; g.font = '150px ' + FONT; g.fillStyle = C.white; g.fillText(fit(g, n.c, pw), px, yy);
      yy += 110; g.font = '40px ' + FONT; g.fillStyle = C.teal; g.fillText(fit(g, '+' + n.pace + ' / MO' + (n.sub ? '  ·  ' + n.sub : ''), pw), px, yy);
      yy += 50;
      (n.goals || []).forEach(function (q) {
        yy += 70; g.font = '36px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, String(q.l).toUpperCase(), pw * 0.5), px, yy);
        g.fillStyle = C.white; var vt = String(q.v); g.font = '44px ' + FONT; var vw = g.measureText(vt).width; g.fillText(vt, px + pw - vw - (q.p != null ? 130 : 0), yy);
        if (q.p != null) { g.font = '32px ' + FONT; g.fillStyle = C.teal; var pt = q.p; g.fillText(pt, px + pw - g.measureText(pt).width, yy); }
        yy += 30; bar(px, yy, pw, 28, q.f, q.m); yy += 40;
      });
      if (n.last) { g.font = '30px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, n.last, pw), px, y + F.h - 40); }
    });
    return F.canvas;
  }

  // ---- 1NT season overview: record, rank, odds, ratings, map pool, results ----
  async function buildEseaSeason(win, btn) {
    var d; try { d = JSON.parse(btn.getAttribute('data-gfx-season')); } catch (e) { return null; }
    var F = await frame(2400, 1350, '1NT :: ESEA S' + d.season, btn.getAttribute('data-gfx-date'));
    var g = F.g, gap = 24, lw = 760, rx = F.x + lw + gap, rw = F.w - lw - gap;
    well(g, F.x, F.y, lw, F.h); well(g, rx, F.y, rw, F.h);
    var logo = document.getElementById('px-1nt');
    var x = F.x + 40, y = F.y + 60;
    if (logo) { var li = await loadImg('data:image/svg+xml;charset=utf-8,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="' + (logo.getAttribute('viewBox') || '0 0 32 32') + '" shape-rendering="crispEdges">' + logo.innerHTML + '</svg>')); if (li) g.drawImage(li, x, y - 20, 128, 128); }
    g.font = '40px ' + FONT; g.fillStyle = C.lilac; g.fillText('S' + d.season + ' RECORD', x + 160, y + 4);
    g.font = '176px ' + FONT; g.fillStyle = C.white; g.fillText(d.w + '-' + d.l, x + 156, y + 120);
    y += 230;
    g.font = '44px ' + FONT;
    if (d.rank) { g.fillStyle = C.teal; g.fillText(d.rank + (d.pts != null ? ' · ' + d.pts + ' pts' : ''), x, y); y += 60; g.font = '36px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, d.board || '', lw - 80), x, y); y += 70; }
    // tiles
    var tiles = [['MAPS', d.mapsW + '-' + d.mapsL], ['ROUNDS', d.rf + '-' + d.ra], ['PLAYOFFS', d.pPo != null ? d.pPo + '%' : '—'], ['STAY IN MAIN', d.pSafe != null ? d.pSafe + '%' : '—']];
    var tw = (lw - 80 - 24) / 2, th = 150;
    tiles.forEach(function (t, i) {
      var tx = x + (i % 2) * (tw + 24), ty = y + Math.floor(i / 2) * (th + 24);
      g.fillStyle = C.face; g.fillRect(tx, ty, tw, th); bevel(g, tx, ty, tw, th, true, 3);
      g.font = '32px ' + FONT; g.fillStyle = C.lilac; g.fillText(t[0], tx + 20, ty + 42);
      g.font = '72px ' + FONT; g.fillStyle = C.white; g.fillText(t[1], tx + 20, ty + 105);
    });
    y += 2 * (th + 24) + 30;
    // results strip
    g.font = '32px ' + FONT;
    (d.results || []).slice(-6).forEach(function (r) {
      if (y > F.y + F.h - 90) return;
      g.fillStyle = r.r === 'W' ? C.teal : C.down; g.fillText(r.r, x, y);
      g.fillStyle = C.lilac; g.fillText(fit(g, (r.s ? r.s[0] + '-' + r.s[1] + ' ' : '') + 'vs ' + r.o + (r.m ? ' (' + r.m + ')' : ''), lw - 140), x + 50, y); y += 46;
    });
    if (d.next) { g.fillStyle = C.white; g.fillText(fit(g, 'next: vs ' + d.next, lw - 80), x, F.y + F.h - 40); }
    // right: ARK Rating bars
    var bx = rx + 40, by = F.y + 60, bw = rw - 80;
    g.font = '40px ' + FONT; g.fillStyle = C.lilac; g.fillText('ARK RATING · K/D · ADR · MVPs', bx, by); by += 60;
    var pl = (d.players || []).slice(0, 7), maxR = Math.max(1.4, Math.max.apply(null, pl.map(function (p) { return p.r || 0; })) + 0.05);
    var nameW = 300, statW = 420, barW = bw - nameW - statW, rowH = 74;
    pl.forEach(function (p) {
      var cy = by + rowH / 2, len = barW * (p.r || 0) / maxR;
      g.font = '36px ' + FONT; g.fillStyle = C.white; g.fillText(fit(g, p.n, nameW - 20), bx, cy);
      g.fillStyle = C.dark; g.fillRect(bx + nameW, cy - 22, barW, 44);
      g.fillStyle = (p.r || 0) >= 1 ? C.teal : C.down; g.fillRect(bx + nameW, cy - 18, len, 36);
      var one = bx + nameW + barW / maxR; g.fillStyle = C.white; g.fillRect(one - 1, cy - 28, 3, 56);
      g.fillStyle = C.dark; g.font = '32px ' + FONT; if (len > 110) g.fillText((p.r || 0).toFixed(2), bx + nameW + 12, cy);
      g.fillStyle = C.lilac; g.fillText(fit(g, (p.kd != null ? p.kd.toFixed(2) : '—') + ' · ' + (p.adr != null ? p.adr.toFixed(1) : '—') + ' · ' + (p.mvp || 0) + ' MVP', statW - 20), bx + nameW + barW + 20, cy);
      by += rowH;
    });
    // map pool
    by += 30; g.font = '40px ' + FONT; g.fillStyle = C.lilac; g.fillText('MAP POOL', bx, by); by += 56;
    (d.pool || []).slice(0, Math.max(1, Math.floor((F.y + F.h - by - 20) / 60))).forEach(function (m) {
      var n = m.w + m.l, cy = by + 26;
      g.font = '36px ' + FONT; g.fillStyle = C.white; g.fillText(m.m, bx, cy);
      g.fillStyle = C.dark; g.fillRect(bx + nameW, cy - 18, barW, 36);
      g.fillStyle = C.teal; g.fillRect(bx + nameW, cy - 14, n ? barW * m.w / n : 0, 28);
      g.fillStyle = C.lilac; g.font = '32px ' + FONT; g.fillText(m.w + '-' + m.l + ' · ' + (m.rd > 0 ? '+' : '') + m.rd, bx + nameW + barW + 20, cy);
      by += 60;
    });
    return F.canvas;
  }

  // ---- 1NT season summary (n1season.html, data/esea_seasons.json): summary card + round diff card ----
  async function n1Logo(g, x, y, size) {
    var logo = document.getElementById('px-1nt'); if (!logo) return;
    var li = await loadImg('data:image/svg+xml;charset=utf-8,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="' + (logo.getAttribute('viewBox') || '0 0 32 32') + '" shape-rendering="crispEdges">' + logo.innerHTML + '</svg>'));
    if (li) g.drawImage(li, x, y, size, size);
  }
  function sgn(v) { return (v > 0 ? '+' : '') + v; }
  function n1Tiles(g, x, y, w, tiles, cols, th) {
    var gp = 24, tw = (w - gp * (cols - 1)) / cols;
    tiles.forEach(function (t, i) {
      var tx = x + (i % cols) * (tw + gp), ty = y + Math.floor(i / cols) * (th + gp);
      g.fillStyle = C.face; g.fillRect(tx, ty, tw, th); bevel(g, tx, ty, tw, th, true, 3);
      g.font = '32px ' + FONT; g.fillStyle = C.lilac; g.fillText(t[0], tx + 20, ty + 40);
      var vf = Math.min(64, th - 72); g.font = vf + 'px ' + FONT; while (vf > 36 && g.measureText(t[1]).width > tw - 40) { vf -= 4; g.font = vf + 'px ' + FONT; }
      g.fillStyle = t[2] || C.white; g.fillText(fit(g, t[1], tw - 40), tx + 20, ty + th - 20 - vf / 2);
    });
    return Math.ceil(tiles.length / cols) * (th + gp);
  }
  function sumData(btn) { try { return JSON.parse(btn.getAttribute('data-gfx-sum')); } catch (e) { return null; } }
  // one 4:5 card per season: record + tiles, round diff by match (bars, W/L + opponent under each) with the
  // cumulative line, round diff by map + round tiles, every player's line that season
  async function buildEseaSummary(win, btn) {
    var d = sumData(btn); if (!d) return null;
    var F = await frame(2160, 2700, '1NT :: ESEA S' + d.season + ' SUMMARY', btn.getAttribute('data-gfx-date'));
    var g = F.g, gap = 24, ms = d.matches || [], rd = d.rf - d.ra, y0 = F.y;
    // 1. header: logo, division, record; tiles right
    var hh = 360; well(g, F.x, y0, F.w, hh);
    var x = F.x + 40, y = y0 + 40;
    await n1Logo(g, x, y + 40, 200);
    var dv = 'S' + d.season + ' · ' + (d.div || '').toUpperCase(); g.font = '44px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, dv, 760), x + 240, y + 40);
    g.font = '200px ' + FONT; g.fillStyle = C.white; g.fillText(d.w + '-' + d.l, x + 232, y + 190);
    var tx = F.x + 1060, tw = F.x + F.w - 40 - tx;
    n1Tiles(g, tx, y, tw, [['MAPS', d.mapsW + '-' + d.mapsL], ['ROUND DIFF', sgn(rd), rd >= 0 ? C.teal : C.down], ['ROUNDS', d.rf + '-' + d.ra],
      d.current ? ['PLAYED', ms.length + '/' + (d.total || ms.length)] : ['PLAYOFFS', d.playoffs ? 'YES' : 'NO']], 2, 136);
    y0 += hh + gap;
    // 2. round diff by match + cumulative; playoffs on a faint band
    var ch = 700; well(g, F.x, y0, F.w, ch);
    var x0 = F.x + 90, w0 = F.w - 130 - 230, top = y0 + 80, ph = ch - 80 - 130, mid = top + ph / 2, n = Math.max(ms.length, 1), slot = w0 / n;
    var M = 5; ms.forEach(function (m) { if (m.rd != null) M = Math.max(M, Math.abs(m.rd)); M = Math.max(M, Math.abs(m.cum || 0)); });
    var Y = function (v) { return Math.round(mid - v / M * (ph / 2 - 6)); };
    g.font = '36px ' + FONT; g.fillStyle = C.lilac; g.fillText('ROUND DIFF · BY MATCH · CUMULATIVE', F.x + 40, y0 + 40);
    ms.forEach(function (m, i) { if (m.po) { g.fillStyle = 'rgba(200,199,255,0.10)'; g.fillRect(x0 + i * slot, top, slot, ph); } });
    g.fillStyle = C.lilac; g.fillRect(x0, mid - 1, w0, 3);
    g.font = '28px ' + FONT; [M, -M].forEach(function (v) { g.fillText(sgn(v), x0 - 16 - g.measureText(sgn(v)).width, Y(v)); });
    var bwid = Math.max(8, Math.floor(slot * 0.6)), pts = [];
    ms.forEach(function (m, i) {
      var cx = x0 + i * slot + slot / 2, bxp = Math.round(cx - bwid / 2);
      if (m.ff) { g.fillStyle = C.lilac; g.fillRect(bxp, mid - 5, bwid, 10); }
      else { var y1 = Y(m.rd); g.fillStyle = m.rd >= 0 ? C.teal : C.down; g.fillRect(bxp, Math.min(y1, mid), bwid, Math.max(4, Math.abs(y1 - mid))); }
      pts.push([cx, Y(m.cum || 0)]);
      var cs = Math.min(64, Math.floor(slot - 10)), cy = top + ph + 20;   // W/L cell
      g.fillStyle = m.res === 'W' ? C.teal : C.down; g.fillRect(cx - cs / 2, cy, cs, cs); bevel(g, cx - cs / 2, cy, cs, cs, true, 3);
      g.font = Math.round(cs * 0.5) + 'px ' + FONT; g.fillStyle = C.dark; var lab = m.ff ? 'FF' : m.res; g.fillText(lab, cx - g.measureText(lab).width / 2, cy + cs * 0.48);
      g.font = Math.min(24, Math.round(slot * 0.2)) + 'px ' + FONT; g.fillStyle = C.lilac; var o = fit(g, m.opp, slot - 6); g.fillText(o, cx - g.measureText(o).width / 2, cy + cs + 28);
    });
    g.fillStyle = C.white;
    for (var i = 0; i < pts.length; i++) {
      var p = pts[i]; g.fillRect(p[0] - 9, p[1] - 9, 18, 18);
      if (i) { var q = pts[i - 1]; g.fillRect(q[0], q[1] - 3, p[0] - q[0], 6); g.fillRect(p[0] - 3, Math.min(p[1], q[1]), 6, Math.abs(p[1] - q[1])); }
    }
    var last = ms.length ? ms[ms.length - 1].cum || 0 : 0, rx0 = x0 + w0 + 40;
    g.font = '30px ' + FONT; g.fillStyle = C.lilac; g.fillText('TOTAL', rx0, top + 20);
    g.font = '88px ' + FONT; g.fillStyle = last >= 0 ? C.teal : C.down; g.fillText(sgn(last), rx0, top + 96);
    y0 += ch + gap;
    // 3. round diff by map (diverging bars) | round tiles
    var mh = 500, lw = Math.round(F.w * 0.52), rx = F.x + lw + gap, rw = F.w - lw - gap;
    well(g, F.x, y0, lw, mh); well(g, rx, y0, rw, mh);
    g.font = '36px ' + FONT; g.fillStyle = C.lilac; g.fillText('ROUND DIFF · BY MAP', F.x + 40, y0 + 40);
    var mp = (d.maps || []).slice(0, 7), mm = 1; mp.forEach(function (m) { mm = Math.max(mm, Math.abs(m.rf - m.ra)); });
    var mx = F.x + 40, mw = lw - 80, rowH = Math.min(60, Math.floor((mh - 90) / Math.max(mp.length, 1))), nameW = 200, recW = 230, barW = mw - nameW - recW, bmid = mx + nameW + barW / 2, ry = y0 + 76;
    mp.forEach(function (m) {
      var cy = ry + rowH / 2, r = m.rf - m.ra, len = barW / 2 * Math.abs(r) / mm;
      g.font = Math.min(36, rowH - 20) + 'px ' + FONT; g.fillStyle = C.white; g.fillText(m.map, mx, cy);
      g.fillStyle = C.dark; g.fillRect(mx + nameW, cy - 16, barW, 32);
      g.fillStyle = r >= 0 ? C.teal : C.down; g.fillRect(r >= 0 ? bmid : bmid - len, cy - 12, Math.max(len, 3), 24);
      g.fillStyle = C.lilac; g.fillRect(bmid - 1, cy - 22, 3, 44);
      g.fillText(m.w + '-' + m.l, mx + nameW + barW + 24, cy);
      var t = sgn(r); g.fillStyle = r >= 0 ? C.teal : C.down; g.fillText(t, mx + mw - g.measureText(t).width, cy);
      ry += rowH;
    });
    var all = []; ms.forEach(function (m) { (m.maps || []).forEach(function (x) { all.push(x); }); });
    var close = all.filter(function (x) { return Math.abs(x.rf - x.ra) <= 3; }), cw = close.filter(function (x) { return x.rf > x.ra; }).length;
    var byd = mp.slice().sort(function (a, b) { return (b.rf - b.ra) - (a.rf - a.ra); }), best = byd[0], worst = byd[byd.length - 1];
    var per = all.length ? rd / all.length : 0;
    n1Tiles(g, rx + 30, y0 + 30, rw - 60, [['PER MAP', (per > 0 ? '+' : '') + per.toFixed(1), per >= 0 ? C.teal : C.down], ['WITHIN 3 RDS', cw + '-' + (close.length - cw)],
      ['BEST MAP', best ? best.map + ' ' + sgn(best.rf - best.ra) : '—'], ['WORST MAP', worst && worst !== best ? worst.map + ' ' + sgn(worst.rf - worst.ra) : '—']], 2, Math.floor((mh - 60 - 24) / 2));
    y0 += mh + gap;
    // 4. players, this season only
    var ph2 = F.y + F.h - y0; well(g, F.x, y0, F.w, ph2);
    var bx = F.x + 40, bw = F.w - 80, by = y0 + 44;
    var cols2 = [['PLAYER', 0, 'l'], ['MAPS', 0.36, 'r'], ['RWA', 0.47, 'r'], ['ARK', 0.57, 'r'], ['RATING', 0.68, 'r'], ['K/D', 0.77, 'r'], ['ADR', 0.86, 'r'], ['HS%', 0.95, 'r']];
    var colX = function (c) { return bx + bw * (c[2] === 'r' ? c[1] + 0.05 : c[1]); };
    g.font = '30px ' + FONT; g.fillStyle = C.lilac;
    cols2.forEach(function (c) { var cx = colX(c); g.fillText(c[0], c[2] === 'r' ? cx - g.measureText(c[0]).width : cx, by); });
    by += 28; g.fillStyle = C.dark; g.fillRect(bx, by, bw, 3); by += 10;
    var pl = (d.players || []).slice(0, 10), rowP = Math.min(80, Math.floor((y0 + ph2 - 20 - by) / Math.max(pl.length, 1))), fs = Math.min(42, Math.round(rowP * 0.52));
    for (var j = 0; j < pl.length; j++) {
      var P = pl[j], cy2 = by + rowP / 2;
      if (j % 2) { g.fillStyle = 'rgba(36,26,58,0.35)'; g.fillRect(bx - 12, by, bw + 24, rowP); }
      var img = P.country ? await flagImg(String(P.country).toLowerCase()) : null, nx = bx;
      if (img) { g.drawImage(img, nx, cy2 - fs * 0.38, fs * 1.1, fs * 0.76); nx += fs * 1.1 + 16; }
      g.font = fs + 'px ' + FONT; g.fillStyle = C.white; g.fillText(fit(g, P.name, bw * 0.33 - (nx - bx)), nx, cy2);
      var vals = [String(P.maps), P.rwa != null ? (P.rwa > 0 ? '+' : '') + Number(P.rwa).toFixed(1) : '—', P.rating != null ? Number(P.rating).toFixed(2) : '—', P.hltv != null ? Number(P.hltv).toFixed(2) : '—', P.kd != null ? Number(P.kd).toFixed(2) : '—', P.adr != null ? Number(P.adr).toFixed(1) : '—', P.hs != null ? String(P.hs) : '—'];
      vals.forEach(function (v, k) {
        var c = cols2[k + 1], cx = colX(c);
        g.fillStyle = k === 1 && P.rwa != null ? (P.rwa >= 0 ? C.teal : C.down) : k === 2 && P.rating != null ? (P.rating >= 1 ? C.teal : C.down) : C.white;
        g.font = (k === 1 ? fs : fs - 6) + 'px ' + FONT; g.fillText(v, cx - g.measureText(v).width, cy2);
      });
      by += rowP;
    }
    return F.canvas;
  }

  // ---- 1NT next match: fanGFX (for fans) and teamGFX (for us) ----
  function drawStars(g, x, cy, n, size) {   // 1-5 stars in half steps, pixel style
    var pts = [[4,0],[5,3],[9,3],[6,5],[7,9],[4,7],[1,9],[2,5],[-1,3],[3,3]], u = size / 10, w = 0;
    for (var i = 0; i < 5; i++) {
      var sx = x + i * (size + 6), lit = n >= i + 1 ? 1 : n >= i + 0.5 ? 0.5 : 0;
      g.save(); g.beginPath(); pts.forEach(function (p, k) { g[k ? 'lineTo' : 'moveTo'](sx + (p[0] + 1) * u * 0.9, cy - size / 2 + p[1] * u); }); g.closePath();
      g.fillStyle = '#5b4a80'; g.fill(); if (lit) { g.clip(); g.fillStyle = '#ffd166'; g.fillRect(sx, cy - size / 2, size * lit, size); }
      g.restore(); w = sx + size - x;
    }
    return w;
  }
  // a team logo in a sunken square (full colour, smoothed: logos aren't pixelated); 1NT's SVG, the opponent's FACEIT avatar
  function teamLogo(g, img, x, y, size) {
    if (!img) return false;
    g.fillStyle = C.dark; g.fillRect(x, y, size, size); bevel(g, x, y, size, size, false, 4);
    var r = Math.min((size - 16) / img.width, (size - 16) / img.height), lw = img.width * r, lh = img.height * r;
    drawLogo(g, img, x + (size - lw) / 2, y + (size - lh) / 2, lw, lh);
    return true;
  }
  function pvData(btn) { try { return JSON.parse(btn.getAttribute('data-gfx-pv')); } catch (e) { return null; } }
  async function teamRow(g, x, cy, w, p, size, right) {   // flag, name, role, grade chip, form ARK
    if (!p) return;
    var img = p.country ? await flagImg(String(p.country).toLowerCase()) : null, tx = x;
    if (img) { g.drawImage(img, tx, cy - size * 0.36, size * 1.1, size * 0.76); tx += size * 1.1 + 14; }
    g.font = size + 'px ' + FONT; g.fillStyle = C.white; var nm = fit(g, p.name, w * 0.42 - (p.sub ? size * 1.9 : 0)); g.fillText(nm, tx, cy);
    if (p.sub) {   // the sub chip: yellow, like the box-score icon
      var sx = tx + g.measureText(nm).width + 16, fs = Math.round(size * 0.5); g.font = fs + 'px ' + FONT; var sw = g.measureText('SUB').width + 16;
      g.fillStyle = '#ffd166'; g.fillRect(sx, cy - fs * 0.75, sw, fs * 1.5); g.fillStyle = '#b8860b'; g.fillRect(sx, cy + fs * 0.75 - 3, sw, 3);
      g.fillStyle = C.dark; g.fillText('SUB', sx + 8, cy);
    }
    g.font = Math.round(size * 0.62) + 'px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, p.role || '', w * 0.22), x + w * 0.5, cy);
    var cx = x + w * 0.74;
    if (p.stars != null) cx += drawStars(g, cx, cy, p.stars, Math.round(size * 0.6)) + 18;
    g.font = Math.round(size * 0.62) + 'px ' + FONT;
    if (p.rwa != null) {   // RWA headlines (round win % added per round; beat ARK Rating held out), form ARK after it, smaller
      var rv = (p.rwa > 0 ? '+' : '') + Number(p.rwa).toFixed(1); g.fillStyle = p.rwa >= 0 ? C.teal : C.down; g.fillText(rv, cx, cy); cx += g.measureText(rv).width + 18;
      if (p.form != null) { g.font = Math.round(size * 0.46) + 'px ' + FONT; g.fillStyle = C.lilac; g.fillText(p.form.toFixed(2), cx, cy); }
    } else if (p.form != null) { g.fillStyle = p.form >= 1 ? C.teal : C.down; g.fillText(p.form.toFixed(2), cx, cy); } else if (p.stars != null) { g.fillStyle = C.lilac; g.fillText('—', cx, cy); }
  }
  async function buildFan(win, btn) {
    var d = pvData(btn); if (!d) return null;
    var F = await frame(2160, 2700, '1NT vs ' + d.opp + ' :: match day', btn.getAttribute('data-gfx-date'));
    var g = F.g, x = F.x, y = F.y, w = F.w;
    well(g, x, y, w, F.h);
    // header: logos, names, VS with the time and event under it (names stop short of the centre column)
    var hy = y + 120, cw = 560;
    var LS = 240, logos = await Promise.all([d.us, d.them].map(function (t) { return t.logo ? loadImg(t.logo) : null; }));
    for (var k = 0; k < 2; k++) teamLogo(g, logos[k], k ? x + w - 60 - LS : x + 60, hy - 60, LS);
    [[d.us, 'left'], [d.them, 'right']].forEach(function (t, k) {
      var tx = k ? x + w - 60 - (logos[k] ? LS + 36 : 0) : x + 60 + (logos[k] ? LS + 36 : 0), al = k ? 'right' : 'left';
      var nw = w / 2 - cw / 2 - 60 - (logos[k] ? LS + 36 : 0), fs = 120, tn = (t[0].rank ? t[0].rank + ' ' : '') + t[0].name;   // headline rank = ARK Ranking; a long name steps down before it's cut
      g.textAlign = al; g.font = fs + 'px ' + FONT; while (fs > 48 && g.measureText(tn).width > nw) { fs -= 8; g.font = fs + 'px ' + FONT; }
      g.fillStyle = C.white; g.fillText(fit(g, tn, nw), tx, hy + 40);
      if (t[0].rank) { g.font = '40px ' + FONT; g.fillStyle = C.teal; g.fillText(fit(g, 'ARK RANKING' + (t[0].tier ? ' · ' + t[0].tier : ''), nw), tx, hy + 140); }
    });
    g.textAlign = 'center'; g.font = '96px ' + FONT; g.fillStyle = C.lilac; g.fillText('VS', x + w / 2, hy + 20);
    g.font = '38px ' + FONT; g.fillStyle = C.white; g.fillText(fit(g, d.when, cw), x + w / 2, hy + 110);
    g.fillStyle = C.lilac; g.fillText(fit(g, d.event, cw), x + w / 2, hy + 160);
    // tale of the tape: one labelled row per number, 1NT left of the label, the opponent right of it
    var rows = [['STANDINGS', d.us.std, d.them.std], ['RECORD', d.us.rec, d.them.rec], ['TALENT', d.us.talent, d.them.talent]]
      .filter(function (r) { return r[1] != null && r[1] !== '' || r[2] != null && r[2] !== ''; });
    var ry = hy + 260, RR = 58, lx = x + w / 2 - 250, rx = x + w / 2 + 250, bx = x + 60, bw = w - 120;
    rows.forEach(function (r, i) {
      var cy = ry + i * RR; if (i % 2 === 0) { g.fillStyle = 'rgba(36,26,58,0.35)'; g.fillRect(bx, cy - RR / 2 + 3, bw, RR - 6); }
      g.textAlign = 'center'; g.font = '34px ' + FONT; g.fillStyle = C.lilac; g.fillText(r[0], x + w / 2, cy);
      [1, 2].forEach(function (s) {
        var v = r[s]; if (v == null || v === '') return;
        if (r[0] === 'TALENT') {   // the five's mean, drawn as stars (half steps) with the number outside them
          var sw = 5 * (40 + 6) - 6, sx = s === 1 ? lx - sw : rx; drawStars(g, sx, cy, Math.round(v * 2) / 2, 40);
          g.font = '36px ' + FONT; g.fillStyle = C.white; g.textAlign = s === 1 ? 'right' : 'left'; g.fillText(Number(v).toFixed(2), s === 1 ? sx - 18 : sx + sw + 18, cy); return;
        }
        g.font = '48px ' + FONT; g.fillStyle = C.white; g.textAlign = s === 1 ? 'right' : 'left'; g.fillText(String(v), s === 1 ? lx : rx, cy);
      });
    });
    g.textAlign = 'left';
    // prediction band
    var by = ry + rows.length * RR + 20, bh = 90;
    g.fillStyle = C.down; g.fillRect(bx, by, bw, bh); g.fillStyle = C.teal; g.fillRect(bx, by, bw * d.win / 100, bh);
    g.font = '52px ' + FONT; g.fillStyle = C.dark; g.fillText('1NT ' + d.win + '%', bx + 24, by + bh / 2);
    var r = (100 - d.win) + '% ' + d.opp; g.fillText(r, bx + bw - 24 - g.measureText(r).width, by + bh / 2);
    // tiles: a Bo3 is called as a series (spread in maps, series score), a Bo1 in rounds
    var ty = by + bh + 110, tw = (bw - 48) / 3, TH = 190;
    var tiles = d.series ? [['SERIES SPREAD', d.series.line, d.series.lineSub], ['PROJECTED SERIES', d.series.score, d.series.scoreSub], ['FORMAT', d.bo, d.series.mapsSub]]
      : [['SPREAD', d.line, ''], ['PROJECTED', d.score, ''], ['FORMAT', d.bo, '']];
    tiles.forEach(function (t, i) {
      var tx = bx + i * (tw + 24); g.fillStyle = C.face; g.fillRect(tx, ty - 60, tw, TH); bevel(g, tx, ty - 60, tw, TH, true, 3);
      g.font = '34px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, t[0], tw - 48), tx + 24, ty - 18);
      var tf = 68; g.font = tf + 'px ' + FONT; while (tf > 40 && g.measureText(t[1]).width > tw - 48) { tf -= 4; g.font = tf + 'px ' + FONT; }
      g.fillStyle = C.white; g.fillText(fit(g, t[1], tw - 48), tx + 24, ty + 48);
      if (t[2]) { g.font = '32px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, t[2], tw - 48), tx + 24, ty + 104); }
    });
    ty += TH - 60;
    // Bo3: the three maps the veto leads to, each with 1NT's map win chance
    if (d.series && d.series.maps && d.series.maps.length) {
      var my = ty + 120, mw = (bw - 48) / 3, MH = 160;
      d.series.maps.forEach(function (m, i) {
        var mx = bx + i * (mw + 24); g.fillStyle = C.well; g.fillRect(mx, my - MH / 2, mw, MH); bevel(g, mx, my - MH / 2, mw, MH, false, 3);
        g.font = '30px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, 'MAP ' + (i + 1) + ' · ' + m.by, mw - 40), mx + 20, my - 46);
        g.font = '50px ' + FONT; g.fillStyle = C.white; g.fillText(fit(g, m.map, mw - 200), mx + 20, my + 2);
        g.textAlign = 'right'; g.fillStyle = m.p >= 50 ? C.teal : C.down; g.fillText(m.p + '%', mx + mw - 20, my + 2); g.textAlign = 'left';
        if (m.score) { g.font = '32px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, 'proj. ' + m.score, mw - 40), mx + 20, my + 50); }
      });
      ty = my + MH / 2;
    }
    // lineups
    var ly = ty + 100, nL = (d.five || []).length + (d.theirFive || []).length, room = (F.y + F.h - 130) - ly - 2 * 160 - (d.lineupNote ? 30 : 0);
    var RH = Math.max(64, Math.min(128, Math.floor(room / Math.max(1, nL)))), RS = Math.min(60, Math.round(RH * 0.62));
    for (var k = 0; k < 2; k++) {
      var L = k ? d.theirFive : d.five, label = (k ? d.opp : '1NT').toUpperCase() + ' · PROJECTED FIVE';
      g.font = '48px ' + FONT; g.fillStyle = k ? C.down : C.teal; g.fillText(label, bx, ly);
      g.font = '32px ' + FONT; g.fillStyle = C.lilac; g.fillText('ROLE', bx + 12 + (bw - 24) * 0.5, ly); var hd = L.some(function (q) { return q.rwa != null; }) ? 'TALENT · CAREER RWA · ARK' : 'TALENT · FORM ARK', hf = 32;   // preview RWA = career league maps
      while (hf > 20 && g.measureText(hd).width > (bw - 24) * 0.26) { hf--; g.font = hf + 'px ' + FONT; }
      g.fillText(hd, bx + 12 + (bw - 24) * 0.74, ly);
      ly += 90;
      for (var i = 0; i < L.length; i++) { if (i % 2) { g.fillStyle = 'rgba(36,26,58,0.35)'; g.fillRect(bx, ly - RH / 2 + 2, bw, RH - 4); } await teamRow(g, bx + 12, ly, bw - 24, L[i], RS); ly += RH; }
      if (!k && d.lineupNote) { g.font = '34px ' + FONT; g.fillStyle = '#ffd166'; g.fillText(fit(g, 'SUB · ' + d.lineupNote, bw - 24), bx + 12, ly - 14); ly += 30; }
      ly += 70;
    }
    // where to watch
    if (d.watch && d.watch.length) {
      var wy = F.y + F.h - 80; g.font = '48px ' + FONT; g.fillStyle = C.teal; g.fillText('WATCH LIVE', bx, wy);
      g.fillStyle = C.white; g.fillText(fit(g, d.watch.map(function (h) { return 'twitch.tv/' + h; }).join('  ·  '), bw - 340), bx + 320, wy);
    }
    return F.canvas;
  }
  // ---- teamGFX: pick/ban tree. 1NT's move = best expected map win (expectimax); at each opponent move two branches:
  // HABIT (ban the map they have played least in 90 days, pick the one they play most: held-out decider log loss -1.61
  // vs -1.95 uniform on ESEA S53-S59 Bo1s) and EDGE (minimax on the player map edges). Expected line = habit.
  // HABIT_W = the chance a ban is HABIT, fit by likelihood on the played map (scripts/esea_veto_research.py: S53-S57
  // fit, S58-S59 played-map log loss 1.685 -> 1.632 vs the habit softmax, t -4.6 by day; the minimax decider alone
  // is the played map 16% of the time, the habit line 37%).
  var HABIT_W = 0.9;
  // Knife side: map win % of the team starting T on that map (ARKBOARD Research cs2-side-first, bo3.gg pro maps).
  function vetoTree(d, weStart) {
    var bo = +d.bon === 3 ? 3 : 1, P = {}, E = {}, N = {};
    (d.maps || []).forEach(function (m) { P[m.map] = m.p / 100; E[m.map] = m.edge; });
    (d.oppMaps || []).forEach(function (m) { N[m.map] = (m.w || 0) + (m.l || 0); });
    var pool = (d.pool && d.pool.length ? d.pool : Object.keys(P)).filter(function (m) { return m in P; });
    var A = weStart ? 'us' : 'them', B = weStart ? 'them' : 'us';
    var S = bo === 3 ? [[A, 'ban'], [B, 'ban'], [A, 'pick'], [B, 'pick'], [A, 'ban'], [B, 'ban']] : [[A, 'ban'], [B, 'ban'], [A, 'ban'], [B, 'ban'], [A, 'ban'], [B, 'ban']];
    S = S.slice(0, pool.length - 1);
    function val(pk, dec) {
      if (bo !== 3) return P[dec];
      var a = P[pk[0]], b = P[pk[1]], c = P[dec];
      return a * b + a * (1 - b) * c + (1 - a) * b * c;
    }
    function nxt(left, pk, t, m) { return [left.filter(function (x) { return x !== m; }), S[t][1] === 'pick' ? pk.concat(m) : pk]; }
    function mm(left, pk, t) {
      if (t === S.length) return val(pk, left[0]);
      var us = S[t][0] === 'us', best = null;
      left.forEach(function (m) { var n = nxt(left, pk, t, m), v = mm(n[0], n[1], t + 1); if (best == null || (us ? v > best : v < best)) best = v; });
      return best;
    }
    function oppMoves(left, pk, t) {
      var act = S[t][1], h = left.slice().sort(function (a, b) { return act === 'ban' ? ((N[a] || 0) - (N[b] || 0) || E[b] - E[a]) : ((N[b] || 0) - (N[a] || 0) || E[a] - E[b]); })[0];
      var em = null, ev = null;
      left.forEach(function (m) { var n = nxt(left, pk, t, m), v = mm(n[0], n[1], t + 1); if (ev == null || v < ev) { ev = v; em = m; } });
      return h === em ? [[h, 1, '']] : [[h, HABIT_W, 'HABIT'], [em, 1 - HABIT_W, 'EDGE']];
    }
    var memo = {};
    function ex(left, pk, t) {
      if (t === S.length) return val(pk, left[0]);
      var k = left.join() + '|' + pk.join() + '|' + t; if (k in memo) return memo[k];
      var v;
      if (S[t][0] === 'us') v = Math.max.apply(null, left.map(function (m) { var n = nxt(left, pk, t, m); return ex(n[0], n[1], t + 1); }));
      else v = oppMoves(left, pk, t).reduce(function (a, o) { var n = nxt(left, pk, t, o[0]); return a + o[1] * ex(n[0], n[1], t + 1); }, 0);
      return (memo[k] = v);
    }
    function build(left, pk, t, hab) {
      if (t === S.length) return { leaf: true, map: left[0], p: val(pk, left[0]), hab: hab };
      if (S[t][0] === 'us') {
        var bm = null, bv = -1;
        left.forEach(function (m) { var n = nxt(left, pk, t, m), v = ex(n[0], n[1], t + 1); if (v > bv + 1e-12) { bv = v; bm = m; } });
        var n = nxt(left, pk, t, bm);
        return { who: 'us', act: S[t][1], map: bm, kid: build(n[0], n[1], t + 1, hab) };
      }
      return { who: 'them', act: S[t][1], opts: oppMoves(left, pk, t).map(function (o) { var n = nxt(left, pk, t, o[0]);
        return { map: o[0], tag: o[2], kid: build(n[0], n[1], t + 1, hab && o[2] !== 'EDGE') }; }) };
    }
    return { bo: bo, ev: ex(pool, [], 0), root: build(pool, [], 0, true) };
  }
  // flatten a tree into rows: one row per opponent move, carrying 1NT's reply and, at the end, the decider
  function treeRows(node, depth, out) {
    out = out || [];
    function tail(r, n) {   // 1NT's reply and the decider, if they follow this move directly
      if (n && !n.leaf && n.who === 'us') { r.reply = n.map; r.act2 = n.act; n = n.kid; }
      if (n && n.leaf) { r.leaf = n; return null; }
      return n;
    }
    if (node && !node.leaf && node.who === 'us') { var r0 = { d: depth, who: 'us', act: node.act, map: node.map }; out.push(r0); node = node.kid; }
    if (!node || node.leaf) return out;
    node.opts.forEach(function (o, i) {
      var br = node.opts.length > 1, r = { d: depth, who: 'them', act: node.act, map: o.map, tag: o.tag, br: br, last: i === node.opts.length - 1 };
      out.push(r);
      var rest = tail(r, o.kid);
      if (rest) treeRows(rest, depth + (br ? 1 : 0), out);
    });
    return out;
  }
  // knife side: pro T-first map win %, each map shrunk toward the all-map rate (empirical Bayes on the map-to-map spread)
  function knife(d, map) {
    var S = d.sides || {}, ks = Object.keys(S).filter(function (k) { return S[k] && S[k].n > 0; }), s = S[map];
    if (!s || !ks.length) return null;
    var nT = 0, kT = 0; ks.forEach(function (k) { nT += S[k].n; kT += S[k].t * S[k].n; });
    var mu = kT / nT, v = function (k) { return S[k].t * (1 - S[k].t) / S[k].n; };
    var tau2 = Math.max(1e-6, ks.reduce(function (a, k) { return a + Math.pow(S[k].t - mu, 2) - v(k); }, 0) / ks.length);
    var w = tau2 / (tau2 + v(map)), est = mu + w * (s.t - mu), se = Math.sqrt(1 / (1 / tau2 + 1 / v(map)));
    var t = est >= 0.5;
    return { side: t ? 'T' : 'CT', pct: Math.round((t ? est : 1 - est) * 1000) / 10, sure: est - 1.96 * se > 0.5 || est + 1.96 * se < 0.5 };
  }
  async function buildTeam(win, btn) {
    var d = pvData(btn); if (!d) return null;
    var F = await frame(2160, 2700, '1NT vs ' + d.opp + ' :: pick/ban', btn.getAttribute('data-gfx-date'));
    var g = F.g, x = F.x + 48, y = F.y + 60, w = F.w - 96, bottom = F.y + F.h - 40;
    well(g, F.x, F.y, F.w, F.h);
    // header: logos, names, format and win chance
    var LS = 150, lx = x;
    for (var k = 0; k < 2; k++) {
      var t = k ? d.them : d.us;
      if (teamLogo(g, t.logo ? await loadImg(t.logo) : null, lx, y - 20, LS)) lx += LS + 28;
      var nf = 76, nt = (t.rank ? t.rank + ' ' : '') + t.name; g.font = nf + 'px ' + FONT; while (nf > 48 && g.measureText(nt).width > w / 2 - LS - 160) { nf -= 4; g.font = nf + 'px ' + FONT; }   // a long name steps down before it's cut
      g.fillStyle = k ? C.down : C.teal; var nm = fit(g, nt, w / 2 - LS - 160), nx0 = lx, sw0 = 0; g.fillText(nm, lx, y - 20 + LS / 2 - 18);
      if (t.std || t.rec) { g.font = '36px ' + FONT; g.fillStyle = C.lilac; var sl = [t.std ? 'STANDINGS ' + t.std : '', t.rec].filter(Boolean).join(' · '); g.fillText(sl, nx0, y - 20 + LS / 2 + 44); sw0 = g.measureText(sl).width; g.font = nf + 'px ' + FONT; }
      lx += Math.max(g.measureText(nm).width, sw0 || 0) + 44;
      if (!k) { g.fillStyle = C.lilac; g.font = '52px ' + FONT; g.fillText('VS', lx, y - 20 + LS / 2); lx += g.measureText('VS').width + 44; }
    }
    y += LS + 30;
    var trees = [vetoTree(d, true), vetoTree(d, false)], bo = trees[0].bo, SR = bo === 3 && d.series, SK = SR && d.stakes;
    g.font = '48px ' + FONT; g.fillStyle = C.lilac;
    g.fillText(fit(g, SR ? ['BO3', SK ? SK.slot : '', d.when].filter(Boolean).join(' · ') : 'BO' + bo + ' · 1NT ' + d.win + '% · ' + d.when, w), x, y); y += 70;
    if (SR) {   // a Bo3 is called as a series: series win %, spread in maps, likeliest score, the three maps the veto leads to
      var bh = 80; g.fillStyle = C.down; g.fillRect(x, y, w, bh); g.fillStyle = C.teal; g.fillRect(x, y, w * d.win / 100, bh);
      g.font = '48px ' + FONT; g.fillStyle = C.dark; g.fillText('1NT ' + d.win + '% SERIES', x + 24, y + bh / 2);
      var rr = (100 - d.win) + '% ' + d.opp; g.textAlign = 'right'; g.fillText(fit(g, rr, w * 0.4), x + w - 24, y + bh / 2); g.textAlign = 'left';
      y += bh + 24;
      var tw = (w - 48) / 3, TH = 160, tiles = [['SERIES SPREAD', d.series.line, d.series.lineSub], ['PROJECTED SERIES', d.series.score, d.series.scoreSub], ['FORMAT', 'Bo3', d.series.mapsSub]];
      tiles.forEach(function (t, i) {
        var tx = x + i * (tw + 24); g.fillStyle = C.face; g.fillRect(tx, y, tw, TH); bevel(g, tx, y, tw, TH, true, 3);
        g.font = '32px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, t[0], tw - 40), tx + 20, y + 34);
        var tf = 60; g.font = tf + 'px ' + FONT; while (tf > 36 && g.measureText(t[1]).width > tw - 40) { tf -= 4; g.font = tf + 'px ' + FONT; }
        g.fillStyle = C.white; g.fillText(fit(g, t[1], tw - 40), tx + 20, y + 88);
        if (t[2]) { g.font = '30px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, t[2], tw - 40), tx + 20, y + 134); }
      });
      y += TH + 24;
      var mps = d.series.maps || [], MH = 170;
      mps.forEach(function (m, i) {   // side: the team that did not pick a map chooses its side; the decider goes to a knife
        var mx = x + i * (tw + 24), kn = knife(d, m.map), dec = m.by === 'decider', ourPick = /^1NT/.test(m.by);
        g.fillStyle = C.well; g.fillRect(mx, y, tw, MH); bevel(g, mx, y, tw, MH, false, 3);
        g.font = '30px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, 'MAP ' + (i + 1) + ' · ' + m.by, tw - 40), mx + 20, y + 32);
        g.font = '50px ' + FONT; g.fillStyle = C.white; g.fillText(fit(g, m.map, tw - 170), mx + 20, y + 86);
        g.textAlign = 'right'; g.fillStyle = m.p >= 50 ? C.teal : C.down; g.fillText(m.p + '%', mx + tw - 20, y + 86); g.textAlign = 'left';
        g.font = '30px ' + FONT;
        var sd = ourPick ? 'OPP CHOOSES SIDE' : kn ? (dec ? 'WIN KNIFE: START ' : '1NT START ') + kn.side : dec ? 'KNIFE' : '1NT CHOOSES SIDE';
        g.fillStyle = !ourPick && kn && kn.sure ? C.teal : C.lilac; g.fillText(fit(g, sd, tw - 40), mx + 20, y + 140);
      });
      if (mps.length) y += MH + 40;
    }
    var rows = trees.map(function (T) { return treeRows(T.root, 0); });
    // expected map (habit line, 1NT bans first) and its knife side, at the bottom; a playoff Bo3 shows where a win or a loss goes instead
    var expLeaf = null;   // the habit line's decider, 1NT banning first (set while drawing)
    var BOXH = SK ? 280 : SR ? 0 : 300, boxY = bottom - BOXH, avail = boxY - 40 - y;
    var nrows = rows[0].length + rows[1].length, rh = Math.max(56, Math.min(100, Math.floor((avail - 2 * 150) / nrows))), fs = Math.min(52, Math.round(rh * 0.56));
    var ind = 64, cTag = x + w * 0.37, cRep = x + w * 0.47, cDec = x + w * 0.68;
    rows.forEach(function (R, ti) {
      g.font = '48px ' + FONT; g.fillStyle = C.white; g.fillText((ti ? d.opp.toUpperCase() : '1NT') + ' BANS FIRST', x, y + 24);
      g.font = '36px ' + FONT; g.fillStyle = C.lilac; g.textAlign = 'right';
      if (!SR) g.fillText('EXP. ' + (bo === 3 ? 'SERIES ' : 'MAP ') + Math.round(trees[ti].ev * 100) + '%', x + w, y + 24); g.textAlign = 'left';   // a Bo3 headlines the series call above
      y += 74;
      g.font = '32px ' + FONT; g.fillStyle = C.lilac;
      g.fillText('1NT REPLY', cRep, y); g.fillText('DECIDER', cDec, y); g.textAlign = 'right'; g.fillText('KNIFE', x + w - 8, y); g.textAlign = 'left';
      y += 30;
      var bars = {};
      R.forEach(function (r, i) {
        var cy = y + rh / 2, rx = x + 16 + r.d * ind;
        if (i % 2) { g.fillStyle = 'rgba(36,26,58,0.35)'; g.fillRect(x, y + 2, w, rh - 4); }
        if (r.br) {   // branch connector: a pixel elbow down from the parent row
          var bx = x + 24 + r.d * ind;
          if (bars[r.d] == null) bars[r.d] = y - 6;
          g.fillStyle = C.light; g.fillRect(bx, bars[r.d], 4, cy - bars[r.d] + 2); g.fillRect(bx, cy, 30, 4);
          bars[r.d] = cy; rx = bx + 44;
          if (r.last) delete bars[r.d];
        }
        var us = r.who === 'us';
        g.font = fs + 'px ' + FONT; g.fillStyle = us ? C.teal : C.down; var lab = (us ? '1NT ' : 'OPP ') + r.act.toUpperCase() + ' ';
        g.fillText(lab, rx, cy); g.fillStyle = C.white; g.fillText(fit(g, r.map, cTag - rx - g.measureText(lab).width - 12), rx + g.measureText(lab).width, cy);
        if (r.tag) {   // the branch chip
          var cs = Math.round(fs * 0.6); g.font = cs + 'px ' + FONT; var cw = g.measureText(r.tag).width + 20;
          g.fillStyle = r.tag === 'HABIT' ? C.lilac : C.down; g.fillRect(cTag, cy - cs * 0.8, cw, cs * 1.6);
          g.fillStyle = C.dark; g.fillText(r.tag, cTag + 10, cy);
        }
        g.font = fs + 'px ' + FONT;
        if (r.reply) { g.fillStyle = C.teal; g.fillText((r.act2 === 'pick' ? 'PICK ' : 'BAN ') + r.reply, cRep, cy); }
        if (r.leaf) {
          var L = r.leaf, kn = knife(d, L.map), on = L.hab;
          if (on) { g.fillStyle = C.teal; g.fillRect(cDec - 20, y + 6, 8, rh - 12); }
          g.fillStyle = on ? C.white : C.lilac; g.fillText(L.map, cDec, cy);
          g.fillStyle = L.p >= 0.5 ? C.teal : C.down; g.fillText(Math.round(L.p * 100) + '%', cDec + fs * 4.4, cy);
          if (kn) { g.fillStyle = kn.sure ? C.teal : C.lilac; g.textAlign = 'right'; g.fillText(kn.side, x + w - 8, cy); g.textAlign = 'left'; }
          if (on) expLeaf = expLeaf || L;
        }
        y += rh;
      });
      y += 40;
    });
    // playoff stakes: where a series win and a loss send 1NT (upper / lower bracket), and 1NT's chance at each reward
    if (SK) {
      var pc = function (q) { return q == null ? '' : q >= 0.995 ? '>99%' : q < 0.001 ? '<0.1%' : q < 0.1 ? (q * 100).toFixed(1) + '%' : Math.round(q * 100) + '%'; };
      var nm = function (o) { if (!o) return ''; var q = /^(winner|loser) of (\S+)$/i.exec(o.opp || ''); return o.n + (o.opp ? ' vs ' + (q ? q[2] + ' ' + q[1].toUpperCase() : o.opp) : ''); };
      g.fillStyle = C.face; g.fillRect(x, boxY, w, BOXH); bevel(g, x, boxY, w, BOXH, true, 4);
      var cw2 = (w - 48) / 2;
      [['WIN', SK.win, C.teal], ['LOSE', SK.lose, C.down]].forEach(function (t, i) {
        var tx = x + 24 + i * cw2;
        g.font = '38px ' + FONT; g.fillStyle = t[2]; g.fillText(t[0] + (t[1] ? (/^UB/.test(t[1].n) ? ' · UPPER' : ' · LOWER') : ''), tx + 12, boxY + 60);
        g.font = '60px ' + FONT; g.fillStyle = C.white; g.fillText(fit(g, t[1] ? nm(t[1]) : 'OUT', cw2 - 36), tx + 12, boxY + 130);
      });
      var cx2 = x + 36, cy2 = boxY + 220;
      (SK.rewards || []).forEach(function (r) {   // reward chips, as on the bracket GFX
        g.font = '34px ' + FONT; var t = 'TOP ' + r.top + ': ' + String(r.s).toUpperCase(), p = pc(r.p), tw2 = g.measureText(t).width + 24;
        g.fillStyle = C.title; g.fillRect(cx2, cy2 - 26, tw2, 52); bevel(g, cx2, cy2 - 26, tw2, 52, true, 2);
        g.fillStyle = C.white; g.fillText(t, cx2 + 12, cy2); cx2 += tw2 + 16;
        if (p) { g.fillStyle = C.teal; g.fillText('1NT ' + p, cx2, cy2); cx2 += g.measureText('1NT ' + p).width + 48; }
      });
    }
    // the expected map box
    if (expLeaf && !SR) {
      var kn = knife(d, expLeaf.map), bx = x, bw = w;
      g.fillStyle = C.face; g.fillRect(bx, boxY, bw, BOXH); bevel(g, bx, boxY, bw, BOXH, true, 4);
      var cw = (bw - 48) / 3, tiles = [['EXPECTED MAP', expLeaf.map, C.white], [bo === 3 ? '1NT SERIES' : '1NT WIN', Math.round(expLeaf.p * 100) + '%', expLeaf.p >= 0.5 ? C.teal : C.down],
        ['WIN KNIFE: START', kn ? kn.side : '—', kn && kn.sure ? C.teal : C.lilac]];
      tiles.forEach(function (t, i) {
        var tx = bx + 24 + i * cw;
        g.font = '38px ' + FONT; g.fillStyle = C.lilac; g.fillText(t[0], tx + 12, boxY + 70);
        g.font = '104px ' + FONT; g.fillStyle = t[2]; g.fillText(fit(g, t[1], cw - 24), tx + 12, boxY + 170);
      });
      if (kn) { g.font = '36px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, kn.side + '-first ' + kn.pct + '% · pro maps', cw - 24), bx + 36 + 2 * cw, boxY + 250); }
    }
    return F.canvas;
  }

  // ---- research card (layouts/shortcodes/rq.html): question, one-line answer, key number and/or bars, 16:9 for X ----
  // ---- projected bracket (layouts/shortcodes/bracket.html): every section's rounds as columns, games spread over
  // the section's height, the projected winner bright, % = P(reach that round); one section or all, stacked ----
  async function buildBracket(win, btn) {
    var D; try { D = JSON.parse(btn.getAttribute('data-gfx-bk') || '{}'); } catch (e) { return null; }
    var sel = win.querySelector('.bk-gsel'), pick = sel && sel.value !== 'all' ? +sel.value : null;
    var secs = (D.sections || []).filter(function (s, i) { return pick === null || i === pick; });
    if (!secs.length) return null;
    var T = D.teams || {}, BOX = 132, GAP = 20, COLW = 380, CG = 28, LAB = 56, SECH = 72;
    var cols = function (s) { return s.rounds.length + (s.champ ? 1 : 0); };
    var ng = function (s) { return Math.max.apply(null, s.rounds.map(function (r) { return r.games.length; })); };
    var maxC = Math.max.apply(null, secs.map(cols));
    var W0 = Math.max(1350, 2 * PAD + 48 + maxC * COLW + (maxC - 1) * CG);
    var bodyH = secs.reduce(function (a, s) { return a + SECH + LAB + ng(s) * (BOX + GAP) + 24; }, 0);
    var title = (D.title || txt(win.querySelector('.win__title-text')).replace(/_$/, '')) + (pick !== null ? ' :: ' + secs[0].name : '');
    var stamp = D.asof ? new Date(D.asof + 'T12:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' }).toLowerCase() : '';
    var F = await frame(W0, Math.max(1080, bodyH + 2 * PAD + 56 + 124 + 24), title.toUpperCase(), stamp);
    var g = F.g, x0 = F.x, y = F.y;
    var ids = {}; secs.forEach(function (s) { s.rounds.forEach(function (r) { r.games.forEach(function (gm) { [gm.a, gm.b].forEach(function (t) { if (t) ids[t.t] = 1; }); }); }); if (s.champ) ids[s.champ.t] = 1; });
    var imgs = {}; await Promise.all(Object.keys(ids).map(function (id) { return loadImg((T[id] || {}).logo).then(function (im) { imgs[id] = im; }); }));
    var pct = function (p) { return p >= 0.995 ? '>99%' : p > 0 && p < 0.005 ? '<1%' : Math.round(p * 100) + '%'; };
    function row(t, x, cy, w, win_, big) {
      var tm = T[t.t] || { n: t.t }, sz = big ? 48 : 40;
      g.font = '32px ' + FONT; g.fillStyle = C.lilac;
      var sx = x + 14; if (t.seed != null && t.seed !== '') g.fillText(String(t.seed), sx, cy);
      var lx = x + 74; if (imgs[t.t]) drawLogo(g, imgs[t.t], lx, cy - 22, 44, 44);
      g.font = sz + 'px ' + FONT; g.fillStyle = win_ ? C.teal : C.lilac;
      var ps = pct(t.p); var pw = (g.font = '36px ' + FONT, g.measureText(ps).width);
      g.font = sz + 'px ' + FONT; g.fillText(fit(g, tm.a || tm.n, w - 74 - 56 - pw - 36), lx + 56, cy);
      g.font = '36px ' + FONT; g.fillStyle = win_ ? C.white : C.lilac; g.fillText(ps, x + w - pw - 14, cy);
    }
    secs.forEach(function (s) {
      g.font = '48px ' + FONT; g.fillStyle = C.white; g.fillText(String(s.name).toUpperCase(), x0, y + 32); y += SECH;
      var n = ng(s), hgt = n * (BOX + GAP), c = 0;
      s.rounds.forEach(function (r) {
        var cx = x0 + c * (COLW + CG);
        g.font = '32px ' + FONT; g.fillStyle = C.teal; g.fillText(fit(g, String(r.name).toUpperCase(), COLW), cx, y + 20);
        r.games.forEach(function (gm, i) {
          var cy = y + LAB + (i + 0.5) * hgt / r.games.length - BOX / 2;
          well(g, cx, cy, COLW, BOX);
          if (gm.a) row(gm.a, cx, cy + BOX * 0.27, COLW, gm.w === gm.a.t);
          if (gm.b) row(gm.b, cx, cy + BOX * 0.73, COLW, gm.w === gm.b.t);
          else { g.font = '32px ' + FONT; g.fillStyle = C.lilac; g.fillText('bye', cx + 74, cy + BOX * 0.73); }
        });
        c++;
      });
      if (s.champ) {
        var cx = x0 + c * (COLW + CG), cy = y + LAB + hgt / 2 - BOX / 2;
        g.font = '32px ' + FONT; g.fillStyle = C.teal; g.fillText('CHAMPION', cx, y + 20);
        g.fillStyle = C.title; g.fillRect(cx, cy, COLW, BOX); bevel(g, cx, cy, COLW, BOX, true);
        row({ t: s.champ.t, seed: '', p: s.champ.p }, cx, cy + BOX / 2, COLW, true, true);
      }
      y += LAB + hgt + 24;
    });
    return F.canvas;
  }

  // ESEA playoff bracket (layouts/shortcodes/esea.html bracket part, data/esea.json bracket.gfx): 1NT's corner of the
  // upper bracket with pixel connectors, its one lower slot per round, the grand final; reward chips where a finish is locked in
  async function buildEseaBracket(win, btn) {
    var D; try { D = JSON.parse(btn.getAttribute('data-gfx-br') || '{}'); } catch (e) { return null; }
    if (!D.ub || !D.ub.length) return null;
    var US = 'a6e9c61b-de50-47d4-9fc8-3f03a13c4d4a';
    var F = await frame(2560, 1440, String(D.title || '1NT :: playoffs').toUpperCase(), btn.getAttribute('data-gfx-date'));
    var g = F.g, x0 = F.x, y0 = F.y, w = F.w, h = F.h;
    var LINE = '#8a5cc2', HOT = C.teal;
    var pct = function (p) { return p >= 0.995 ? '>99%' : p > 0 && p < 0.005 ? '<1%' : Math.round(p * 100) + '%'; };
    var et = function (t) { if (!t) return ''; var d = new Date(t); return d.toLocaleDateString('en-US', { timeZone: 'America/New_York', month: 'numeric', day: 'numeric' }) + ' ' + d.toLocaleTimeString('en-US', { timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit' }).replace(':00', '').replace(' ', ''); };
    var short = function (n) { var q = /^(winner|loser) of (\S+)$/i.exec(n); return q ? q[2] + ' ' + q[1].toUpperCase() : n; };   // "LB34 WINNER" when the long form won't fit
    var isUs = function (m) { return m.a.id === US || m.b.id === US || m.reach != null; };
    var BW, BH = 118, RWH = 34;
    // one match box: label line (slot, date, 1NT reach), two team rows (seed, name, score or win %), reward chip under it
    function box(m, x, y, bw) {
      var us = isUs(m);
      well(g, x, y, bw, BH);
      if (us) { g.fillStyle = HOT; g.fillRect(x, y, bw, 3); g.fillRect(x, y + BH - 3, bw, 3); g.fillRect(x, y, 3, BH); g.fillRect(x + bw - 3, y, 3, BH); }
      g.textAlign = 'left'; g.font = '24px ' + FONT; g.fillStyle = C.lilac;
      var lab = m.n + (m.bye ? ' · BYE' : m.at ? ' · ' + et(m.at) : '');
      var rs = m.reach != null && m.reach < 0.995 ? '1NT ' + pct(m.reach) : '';
      if (rs && g.measureText(lab + '  ' + rs).width > bw - 24) rs = pct(m.reach);   // cramped: the teal % alone, then the date without its time
      if (m.at && !m.bye && g.measureText(lab + '  ' + rs).width > bw - 24) lab = m.n + ' · ' + et(m.at).split(' ')[0];
      var rw = rs ? (g.measureText(rs).width) : 0;
      g.fillText(fit(g, lab, bw - 24 - (rw ? rw + 12 : 0)), x + 12, y + 20);
      if (rs) { g.fillStyle = HOT; g.textAlign = 'right'; g.fillText(rs, x + bw - 12, y + 20); g.textAlign = 'left'; }
      [m.a, m.b].forEach(function (t, k) {
        var cy = y + 56 + k * 40, won = m.w === k + 1 || (m.bye && t.n !== 'BYE'), lost = (m.w && !won) || (m.bye && t.n === 'BYE');
        if (k) { g.fillStyle = C.dark; g.fillRect(x + 8, cy - 21, bw - 16, 2); }
        g.font = '24px ' + FONT; g.fillStyle = C.lilac; g.textAlign = 'right';
        if (t.seed != null) g.fillText(String(t.seed), x + 46, cy);
        var v = m.bye ? '' : m.s ? String(m.s[k]) : m.p != null ? pct(k ? 1 - m.p : m.p) : '';
        g.font = '30px ' + FONT; var vw = v ? g.measureText(v).width : 0;
        g.fillStyle = won ? HOT : C.white; if (v) g.fillText(v, x + bw - 12, cy);
        g.textAlign = 'left';
        g.fillStyle = t.id === US ? HOT : t.tbd ? C.lilac : lost ? C.lilac : C.white;
        g.font = (t.tbd ? '24px ' : '30px ') + FONT;
        var room = bw - 60 - 12 - (vw ? vw + 14 : 0), nm = t.n === 'BYE' ? 'bye' : t.tbd ? String(t.n).toUpperCase() : t.n;
        if (t.tbd && g.measureText(nm).width > room) nm = short(t.n).toUpperCase();
        g.fillText(fit(g, nm, room), x + 58, cy);
      });
      if (m.rw) {
        g.font = '24px ' + FONT; var t = 'WIN: ' + String(m.rw.s).toUpperCase(), tw = g.measureText(t).width + 24;
        g.fillStyle = C.title; g.fillRect(x, y + BH + 6, tw, RWH - 6); bevel(g, x, y + BH + 6, tw, RWH - 6, true, 2);
        g.fillStyle = C.white; g.fillText(t, x + 12, y + BH + 6 + (RWH - 6) / 2);
      }
    }
    function hline(xa, xb, y, hot) { g.fillStyle = hot ? HOT : LINE; g.fillRect(Math.min(xa, xb), y - 2, Math.abs(xb - xa), 4); }
    function vline(x, ya, yb, hot) { g.fillStyle = hot ? HOT : LINE; g.fillRect(x - 2, Math.min(ya, yb), 4, Math.abs(yb - ya) + 2); }
    // ---- upper: one column per round + the final
    var cols = D.ub.length + (D.gf ? 1 : 0), CG = 44;
    BW = Math.floor((w - (cols - 1) * CG) / cols);
    var UY = y0 + 110, UH = Math.round(h * 0.58) - 110;
    g.textAlign = 'left'; g.font = '40px ' + FONT; g.fillStyle = C.white; g.fillText('UPPER', x0, y0 + 18);
    var centers = [];
    D.ub.forEach(function (rd, c) {
      var cx = x0 + c * (BW + CG), n = rd.m.length;
      g.font = '26px ' + FONT; g.fillStyle = C.teal; g.textAlign = 'left';
      g.fillText('ROUND ' + rd.r, cx, UY - 14);
      centers[c] = rd.m.map(function (m, i) { var cy = UY + (i + 0.5) * UH / n; box(m, cx, cy - BH / 2, BW); return cy; });
    });
    // connectors: pairs fold into the next round's slot; single slots run straight
    D.ub.forEach(function (rd, c) {
      if (c === D.ub.length - 1) return;
      var xa = x0 + c * (BW + CG) + BW, xm = xa + CG / 2, xb = xa + CG, nx = D.ub[c + 1].m.length;
      rd.m.forEach(function (m, i) {
        var j = rd.m.length === 2 * nx ? Math.floor(i / 2) : rd.m.length === nx ? i : 0, ty = centers[c + 1][j], hot = isUs(m) && isUs(D.ub[c + 1].m[j]);
        hline(xa, xm, centers[c][i], hot); vline(xm, centers[c][i], ty, hot); hline(xm, xb, ty, hot);
      });
    });
    var gfX = null, gfY = null;
    if (D.gf) {
      var c = D.ub.length, cx = x0 + c * (BW + CG), last = centers[c - 1][0];
      g.font = '26px ' + FONT; g.fillStyle = C.teal; g.fillText('GRAND FINAL', cx, UY - 14);
      box(D.gf, cx, last - BH / 2, BW); gfX = cx + BW / 2; gfY = last + BH / 2;
      hline(cx - CG, cx, last, D.gf.reach != null);
    }
    // ---- lower: 1NT's slot in each lower round, left to right
    var LY = y0 + Math.round(h * 0.58) + 90;
    g.font = '40px ' + FONT; g.fillStyle = C.white; g.textAlign = 'left'; g.fillText('LOWER', x0, LY - 34);
    var lb = D.lb || [], LG = 28, LW = lb.length ? Math.floor((w - (lb.length - 1) * LG) / lb.length) : 0, lcy = LY + 40 + BH / 2;
    lb.forEach(function (m, i) {
      var lx = x0 + i * (LW + LG);
      g.font = '24px ' + FONT; g.fillStyle = C.teal; g.fillText('ROUND ' + m.r, lx, LY + 14);
      box(m, lx, LY + 40, LW);
      if (i) hline(lx - LG, lx, lcy, isUs(m) && isUs(lb[i - 1]));
    });
    if (gfX != null && lb.length) {   // the lower final feeds the grand final
      var lxe = x0 + (lb.length - 1) * (LW + LG) + LW / 2, hot = D.gf.reach != null;
      var ym = LY - 60; vline(gfX, gfY + (D.gf.rw ? RWH : 0) + 4, ym, hot); hline(lxe, gfX, ym, hot); vline(lxe, ym, LY + 40, hot);
    }
    // footer line: title odds and what each chip means
    var fy = y0 + h - 18;
    g.font = '30px ' + FONT; g.textAlign = 'left';
    var fx = x0;
    if (D.title_p !== '' && D.title_p != null) { g.fillStyle = C.lilac; g.fillText('1NT TITLE', fx, fy); fx += g.measureText('1NT TITLE ').width; g.fillStyle = HOT; var tp = D.title_p < 0.001 ? '<0.1%' : (D.title_p * 100).toFixed(1) + '%'; g.fillText(tp, fx, fy); fx += g.measureText(tp).width + 40; }
    (D.rewards || []).forEach(function (t) { g.fillStyle = C.lilac; var s1 = String(t.s).toUpperCase() + ' = TOP ' + t.top; g.fillText(s1, fx, fy); fx += g.measureText(s1).width + 40; });
    g.textAlign = 'left';
    return F.canvas;
  }

  // CS2 Major Pick'Em (layouts/shortcodes/cs2pickem.html): coin chances, then 3-0 / 0-3 picks left and 3-1 / 3-2 right,
  // or the playoff bracket picks (QF, SF, champion) once the Swiss stages are done
  async function buildPickem(win, btn) {
    var D; try { D = JSON.parse(btn.getAttribute('data-gfx-pk') || '{}'); } catch (e) { return null; }
    var P = D.picks || {}, B = D.bracket || {}, sw = (P['30'] || []).length > 0, br = !sw && (B.picks || []).length > 0;
    if (!sw && !br) return null;
    var W0 = 2400, H0 = 1350;
    var stamp = D.asof ? new Date(D.asof).toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'America/New_York' }).toLowerCase() : '';
    var F = await frame(W0, H0, (String(D.event || '') + ' :: ' + (sw ? D.stage : 'playoffs') + " pick'em").toUpperCase(), stamp, tabLink(win));
    var g = F.g, x0 = F.x, y = F.y + 8, w = F.w;
    var rows = sw ? [].concat(P['30'], P.adv || [], P['03'] || []) : B.picks;
    var imgs = await Promise.all(rows.map(function (r) { return loadImg(r.logo); }));
    var im = function (r) { return imgs[rows.indexOf(r)]; };
    var pct = function (p) { return p >= 0.995 ? '>99%' : p > 0 && p < 0.005 ? '<1%' : Math.round(p * 100) + '%'; };
    // coin strip: SILVER / GOLD / DIAMOND chance, then the stage line
    var CH = 116, coins = [['SILVER', '#b9b8d8'], ['GOLD', '#eec35e'], ['DIAMOND', '#9eeadf']], cw = sw ? (w - 3 * 24) / 4 : (w - 2 * 24) / 3;
    coins.forEach(function (c, i) {
      var cx = x0 + i * (cw + 24); well(g, cx, y, cw, CH);
      var s = 44, sx = cx + 24, sy = y + CH / 2 - s / 2;   // a pixel coin
      g.fillStyle = c[1]; g.fillRect(sx + 8, sy, s - 16, s); g.fillRect(sx, sy + 8, s, s - 16);
      g.fillStyle = C.dark; g.fillRect(sx + 16, sy + 12, s - 32, s - 24);
      g.font = '44px ' + FONT; g.fillStyle = c[1]; g.fillText(c[0], sx + s + 20, y + CH / 2);
      var v = pct(((D.coin || {})[c[0].charAt(0) + c[0].slice(1).toLowerCase()]) || 0);
      g.font = '64px ' + FONT; g.fillStyle = C.white; g.fillText(v, cx + cw - 24 - g.measureText(v).width, y + CH / 2);
    });
    if (sw) {
      var cx = x0 + 3 * (cw + 24); well(g, cx, y, cw, CH);
      g.font = '44px ' + FONT; g.fillStyle = C.teal; g.fillText('5+ / 10', cx + 24, y + CH / 2);
      var v = pct(D.pPass || 0); g.font = '64px ' + FONT; g.fillStyle = C.white; g.fillText(v, cx + cw - 24 - g.measureText(v).width, y + CH / 2);
    }
    y += CH + 36;
    var bot = F.y + F.h, GAP = 36;
    // one slot: heading, then a well of rows (logo, name, chance)
    function slot(label, col, list, x, top, sw_, hgt, cols) {
      g.font = '44px ' + FONT; g.fillStyle = col; g.fillText(label, x, top + 22);
      var wy = top + 56, wh = hgt - 56; well(g, x, wy, sw_, wh);
      cols = cols || 1; var per = Math.ceil(list.length / cols), rh = wh / per, cwid = sw_ / cols;
      list.forEach(function (r, i) {
        var c = Math.floor(i / per), rx = x + c * cwid, cy = wy + (i % per + 0.5) * rh, ls = Math.min(72, rh * 0.62);
        if (c) { g.fillStyle = C.dark; g.fillRect(rx, wy + 10, 3, wh - 20); }
        if (im(r)) drawLogo(g, im(r), rx + 24, cy - ls / 2, ls, ls);
        var ps = r.p != null ? pct(r.p) : ''; g.font = '56px ' + FONT; var pw = ps ? g.measureText(ps).width : 0;
        g.font = '52px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, r.n, cwid - 24 - ls - 24 - pw - 48), rx + 24 + ls + 24, cy);
        if (ps) { g.font = '56px ' + FONT; g.fillStyle = col; g.fillText(ps, rx + cwid - 24 - pw, cy); }
      });
    }
    if (sw) {
      var lw = (w - GAP) * 0.4, rw = w - GAP - lw, hh = (bot - y - GAP) / 2;
      slot('3-0', C.teal, P['30'], x0, y, lw, hh);
      slot('0-3', C.down, P['03'] || [], x0, y + hh + GAP, lw, hh);
      slot('3-1 / 3-2', C.white, P.adv || [], x0 + lw + GAP, y, rw, bot - y);
    } else {
      var k = B.picks, colw = (w - 2 * GAP) / 3, hb = bot - y - 80;
      slot('QF', C.lilac, k.slice(0, 4), x0, y, colw, hb);
      slot('SF', C.teal, k.slice(4, 6), x0 + colw + GAP, y, colw, hb);
      slot('CHAMPION', C.white, k.slice(6, 7), x0 + 2 * (colw + GAP), y, colw, hb);
      var line = (B.pk || []).map(function (p, i) { return (i + 1) + '+ ' + pct(p); }).join('   ');
      g.font = '44px ' + FONT; g.fillStyle = C.lilac; g.fillText(line, x0, bot - 24);
    }
    return F.canvas;
  }

  async function buildRQ(win, btn) {
    var d; try { d = JSON.parse(btn.getAttribute('data-gfx-rq') || '{}'); } catch (e) { return null; }
    if (!d.q || !d.a) return null;
    var bars = (d.bars || []).map(function (b) { return Array.isArray(b) ? b : b && [b.l, b.v]; }).filter(function (b) { return b && b.length >= 2 && isFinite(+b[1]); }).slice(0, 8);
    var F = await frame(2400, 1350, 'ARKBOARD RESEARCH' + (d.sport ? ' :: ' + String(d.sport).toUpperCase() : ''), d.date || '',
      'arkndjl.net/process' + (d.id ? '#rq-' + d.id : ''));
    var g = F.g, x = F.x, y = F.y, w = F.w, h = F.h, pad = 36;
    // the question: the largest of 80/64/48 px that fits three lines
    var qs = 80, ql;
    for (; qs >= 48; qs -= 16) { g.font = qs + 'px ' + FONT; ql = wrap(g, d.q, w - 2 * pad - qs); if (ql.length <= 3) break; }
    if (qs < 48) { qs = 48; g.font = qs + 'px ' + FONT; ql = wrap(g, d.q, w - 2 * pad - qs).slice(0, 3); }
    var qh = 2 * pad + ql.length * qs * 1.3;
    well(g, x, y, w, qh);
    g.fillStyle = C.lilac; g.font = qs + 'px ' + FONT; g.fillText('Q', x + pad, y + pad + qs * 0.65);
    g.fillStyle = C.white;
    ql.forEach(function (t, i) { g.fillText(t, x + pad + qs * 1.1, y + pad + qs * 0.65 + i * qs * 1.3); });
    var top = y + qh + 24, bh = y + h - top;
    // right panel: the key number, the bars, or both
    var side = d.n || bars.length, sw = side ? Math.round(w * (bars.length ? 0.46 : 0.36)) : 0, lw = w - sw - (side ? 24 : 0);
    // answer: the largest of 96/80/64/48 px that fits the left panel (note line kept free at the bottom)
    var noteH = d.note ? 64 : 0, as = 96, al;
    for (; as >= 48; as -= 16) { g.font = as + 'px ' + FONT; al = wrap(g, d.a, lw - 2 * pad); if (al.length * as * 1.3 <= bh - 2 * pad - noteH) break; }
    if (as < 48) { as = 48; g.font = as + 'px ' + FONT; al = wrap(g, d.a, lw - 2 * pad); }
    g.fillStyle = C.lilac; g.font = '48px ' + FONT; g.fillText('A', x + pad, top + 40);
    g.font = as + 'px ' + FONT; g.fillStyle = C.teal;
    var ay = top + 40 + 48 + as * 0.65;
    al.forEach(function (t, i) { g.fillText(fit(g, t, lw - 2 * pad), x + pad, ay + i * as * 1.3); });
    if (d.note) { g.font = '40px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, d.note, lw - 2 * pad), x + pad, top + bh - 28); }
    if (!side) return F.canvas;
    var sx = x + lw + 24, sy = top;
    well(g, sx, sy, sw, bh);
    var cy = sy + pad;
    if (d.n) {
      var ns = bars.length ? 128 : 192; g.font = ns + 'px ' + FONT;
      while (ns > 64 && g.measureText(String(d.n)).width > sw - 2 * pad) { ns -= 16; g.font = ns + 'px ' + FONT; }
      var nl = d.nl ? (g.font = '40px ' + FONT, wrap(g, d.nl, sw - 2 * pad).slice(0, bars.length ? 1 : 3)) : [];
      var block = ns + nl.length * 52;
      if (!bars.length) cy = sy + (bh - block) / 2;
      g.textAlign = 'center'; g.font = ns + 'px ' + FONT; g.fillStyle = C.teal;
      g.fillText(String(d.n), sx + sw / 2, cy + ns * 0.5);
      g.font = '40px ' + FONT; g.fillStyle = C.lilac;
      nl.forEach(function (t, i) { g.fillText(t, sx + sw / 2, cy + ns + 26 + i * 52); });
      g.textAlign = 'left';
      cy += block + 32;
    }
    if (bars.length) {
      var avail = sy + bh - pad - cy, rh = Math.min(96, avail / bars.length), fs = rh >= 80 ? 48 : 40;
      g.font = fs + 'px ' + FONT;
      var unit = d.unit ? ' ' + d.unit : '', neg = bars.some(function (b) { return +b[1] < 0; });
      var lw0 = function () { return Math.max.apply(null, bars.map(function (b) { return g.measureText(String(b[0])).width; })) + 16; };
      while (fs > 32 && lw0() > sw * 0.48) { fs -= 8; g.font = fs + 'px ' + FONT; }
      var lab = Math.min(sw * 0.48, lw0());
      cy += Math.max(0, (avail - rh * bars.length) / 2);   // the chart sits in the middle of the space left
      var vals = bars.map(function (b) { var v = +b[1], s = (Math.abs(v) >= 100 ? Math.round(v) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2).replace(/0$/, '')); return (neg && v > 0 ? '+' : '') + s + unit; });
      var vw = Math.max.apply(null, vals.map(function (t) { return g.measureText(t).width; })) + 16;
      var bx = sx + pad + lab, bw = sw - 2 * pad - lab - vw;
      var mx = Math.max.apply(null, bars.map(function (b) { return Math.abs(+b[1]); })) || 1;
      var lo = neg ? Math.min.apply(null, bars.map(function (b) { return Math.min(0, +b[1]); })) : 0, hi = Math.max.apply(null, bars.map(function (b) { return Math.max(0, +b[1]); }));
      var span = (hi - lo) || mx, zx = bx + bw * (-lo / span);
      bars.forEach(function (b, i) {
        var v = +b[1], ry = cy + i * rh, mid = ry + rh / 2, bhh = Math.max(16, Math.round(rh * 0.5 / 8) * 8);
        g.fillStyle = C.white; g.fillText(fit(g, String(b[0]), lab - 16), sx + pad, mid);
        var len = Math.max(8, Math.round(bw * Math.abs(v) / span / 8) * 8), x0 = v < 0 ? zx - len : zx;
        g.fillStyle = v < 0 ? C.down : C.teal; g.fillRect(Math.round(x0), Math.round(mid - bhh / 2), len, bhh);
        g.fillStyle = C.dark; g.fillRect(Math.round(x0), Math.round(mid + bhh / 2) - 4, len, 4);
        g.fillStyle = v < 0 ? C.down : C.teal; g.fillText(vals[i], bx + bw + 16, mid);
      });
      if (neg) { g.fillStyle = C.lilac; g.fillRect(Math.round(zx) - 2, cy, 4, rh * bars.length); }
    }
    return F.canvas;
  }
  // a glossary term (Process > Glossary/Methodology): the term, its formula, and one picture of its scale
  // (data/glossary_gfx.json: ab, name, f lines, scale {lo,hi,ticks,mark}, parts [[label,w]], bars [[label,v]] + unit + bl, n + nl)
  // explainer card (portrait 3:4, data/glossary_gfx.json entries with x: 1, built by scripts/glossary_gfx.py):
  // head (term + what it stands for + sports), WHAT / USE lines, formula, held-out test vs similar metrics,
  // a picture (distribution, calibration, bars or scale), top 10, footnote
  async function buildExplain(d) {
    var F = await frame(1800, 2400, 'ARKBOARD PROCESS :: GLOSSARY', '', 'arkndjl.net/process' + (d.id ? '#' + d.id : ''));
    var g = F.g, x = F.x, y = F.y, w = F.w, h = F.h, pad = 32, gap = 20, cy = y;
    var num = function (v, dec, sign, unit) {
      if (typeof v === 'string') return v;
      v = +v; var s = dec == null ? (Math.abs(v) >= 10 ? (Math.round(v * 10) / 10).toString() : (Math.round(v * 1000) / 1000).toString()) : v.toFixed(dec);
      s = s.replace(/^(-?)0\./, '$1.').replace('-', '−');
      if (sign && v > 0) s = '+' + s;
      return unit === '%' ? s + '%' : s;
    };
    var cap = function (t, X, Y, col) { g.font = '32px ' + FONT; g.fillStyle = col || C.lilac; g.fillText(String(t).toUpperCase(), X, Y); };
    // head
    var ab = d.ab || String(d.t).replace(/\s*\(.*$/, ''), sp = (d.sp || []).slice(0, 6), HH = 300;
    well(g, x, cy, w, HH);
    g.font = '40px ' + FONT; var tagW = 0; sp.forEach(function (s) { tagW = Math.max(tagW, g.measureText(String(s).toUpperCase()).width + 36); });
    var tagsW = sp.length ? (sp.length > 3 ? 2 * tagW + 12 : tagW) : 0, room = w - 2 * pad - (tagsW ? tagsW + 32 : 0), as = 176;
    for (; as > 80; as -= 16) { g.font = as + 'px ' + FONT; if (g.measureText(ab).width <= room) break; }
    g.fillStyle = C.teal; g.font = as + 'px ' + FONT; g.fillText(ab, x + pad, cy + 40 + as * 0.5);
    g.font = '48px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, String(d.stands || '').toUpperCase(), room), x + pad, cy + HH - 40);
    sp.forEach(function (s, i) {
      var two = sp.length > 3, c = two ? i % 2 : 0, r = two ? Math.floor(i / 2) : i;
      var tx = x + w - pad - tagsW + c * (tagW + 12), ty = cy + pad + r * 72;
      g.fillStyle = C.title; g.fillRect(tx, ty, tagW, 58); bevel(g, tx, ty, tagW, 58, true, 4);
      g.font = '40px ' + FONT; g.fillStyle = C.white; g.textAlign = 'center'; g.fillText(String(s).toUpperCase(), tx + tagW / 2, ty + 30); g.textAlign = 'left';
    });
    cy += HH + gap;
    // WHAT / USE
    var LW = 150, tw = w - 2 * pad - LW, lines = [];
    g.font = '40px ' + FONT;
    [['what', d.what], ['use', d.use]].forEach(function (r) { if (r[1]) lines.push([r[0], wrap(g, r[1], tw).slice(0, 2)]); });
    var lh = 54, bh = 2 * pad - 12 + lines.reduce(function (a, r) { return a + r[1].length * lh + 14; }, -14);
    well(g, x, cy, w, bh);
    var ly = cy + pad + 20;
    lines.forEach(function (r) {
      cap(r[0], x + pad, ly);
      g.font = '40px ' + FONT; g.fillStyle = C.white;
      r[1].forEach(function (t, i) { g.fillText(t, x + pad + LW, ly + i * lh); });
      ly += r[1].length * lh + 14;
    });
    cy += bh + gap;
    // formula (+ split bar of the blend's weights)
    var fl = d.f || [], parts = d.parts || [], fs = 52;
    g.font = fs + 'px ' + FONT;
    while (fs > 36 && fl.some(function (t) { return g.measureText(t).width > w - 2 * pad; })) { fs -= 4; g.font = fs + 'px ' + FONT; }
    var fh = 2 * pad + 40 + fl.length * fs * 1.3 + (parts.length ? 130 : 0);
    well(g, x, cy, w, fh);
    cap('formula', x + pad, cy + pad + 10);
    g.font = fs + 'px ' + FONT; g.fillStyle = C.white;
    fl.forEach(function (t, i) { g.fillText(t, x + pad, cy + pad + 40 + fs * 0.75 + i * fs * 1.3); });
    if (parts.length) {
      var px = x + pad, pw = w - 2 * pad, tot = parts.reduce(function (a, p) { return a + (+p[1]); }, 0) || 1, py = cy + fh - pad - 104, PC = [C.teal, C.lilac, '#9a8cc4', C.white];
      parts.forEach(function (p, i) {
        var ww = i === parts.length - 1 ? x + pad + pw - px : Math.round(pw * (+p[1]) / tot / 8) * 8, inner = ww - (i < parts.length - 1 ? 8 : 0);
        g.fillStyle = PC[i % PC.length]; g.fillRect(px, py, inner, 56);
        g.fillStyle = C.dark; g.fillRect(px, py + 52, inner, 4);
        g.font = '36px ' + FONT; g.fillStyle = C.dark; g.fillText(num(p[1], 2).replace(/0$/, ''), px + 12, py + 30);
        g.font = '32px ' + FONT; g.fillStyle = PC[i % PC.length]; g.fillText(fit(g, p[0], inner - 8), px, py + 88);
        px += ww;
      });
    }
    cy += fh + gap;
    // test (left) + picture (right)
    var rowsH = (d.top && d.top.rows && d.top.rows.length) ? 560 : Math.max(560, y + h - cy - (d.foot ? 52 : 0)), lw2 = Math.round((w - gap) * 0.54), rw = w - gap - lw2, rx = x + lw2 + gap;
    var T = d.test;
    well(g, x, cy, lw2, rowsH);
    if (T && T.tiles) {
      cap('test', x + pad, cy + pad + 10, C.teal);
      g.font = '32px ' + FONT; g.fillStyle = C.lilac;
      var tl0 = wrap(g, T.t, lw2 - 2 * pad).slice(0, 2); tl0.forEach(function (t, i) { g.fillText(t, x + pad, cy + pad + 56 + i * 40); });
      var tt = T.tiles, ty0 = cy + pad + 56 + tl0.length * 40 + 16, th = (cy + rowsH - pad - (T.n ? 56 : 0) - ty0) / tt.length;
      tt.forEach(function (r, i) {
        var my = ty0 + i * th + th / 2;
        g.font = '32px ' + FONT; g.fillStyle = C.lilac; g.fillText(String(r[0]).toUpperCase(), x + pad, my - 22);
        if (r[2]) g.fillText(r[2], x + pad, my + 22);
        g.font = '88px ' + FONT; g.fillStyle = C.teal; g.textAlign = 'right'; g.fillText(String(r[1]).replace('-', '−'), x + lw2 - pad, my); g.textAlign = 'left';
      });
      if (T.n) { g.font = '28px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, T.n, lw2 - 2 * pad), x + pad, cy + rowsH - pad - 8); }
    } else if (T) {
      cap('test · ' + (T.lo ? 'lower is better' : 'higher is better'), x + pad, cy + pad + 10, C.teal);
      g.font = '32px ' + FONT; g.fillStyle = C.lilac;
      var tl = wrap(g, T.t, lw2 - 2 * pad).slice(0, 2); tl.forEach(function (t, i) { g.fillText(t, x + pad, cy + pad + 56 + i * 40); });
      var R = T.rows || [], top0 = cy + pad + 56 + tl.length * 40 + 16, foot = T.n ? 56 : 0, avail = cy + rowsH - pad - foot - top0, rh = Math.min(100, avail / Math.max(1, R.length));
      var fsz = rh >= 88 ? 48 : rh >= 64 ? 40 : 32; g.font = fsz + 'px ' + FONT;
      var labW = Math.min((lw2 - 2 * pad) * 0.5, Math.max.apply(null, R.map(function (r) { return g.measureText(r[0]).width; }).concat([0])) + 20);
      var vals = R.map(function (r) { return num(r[1], Math.abs(+r[1]) < 1 ? 3 : null, false, T.unit); }), valW = Math.max.apply(null, vals.map(function (t) { return g.measureText(t).width; }).concat([0])) + 20;
      var bx = x + pad + labW, bw = lw2 - 2 * pad - labW - valW, mx = Math.max.apply(null, R.map(function (r) { return Math.abs(+r[1]); }).concat([1e-9]));
      var mn = T.lo ? Math.min.apply(null, R.map(function (r) { return +r[1]; })) * 0.9 : 0;   // lower is better: bars from 90% of the best, so gaps show
      R.forEach(function (r, i) {
        var mid = top0 + i * rh + rh / 2, v = +r[1], len = Math.max(8, Math.round(bw * (Math.abs(v) - mn) / (mx - mn || 1) / 8) * 8), col = r[2] ? C.teal : '#9a8cc4';
        g.font = fsz + 'px ' + FONT; g.fillStyle = r[2] ? C.white : C.lilac; g.fillText(fit(g, r[0], labW - 12), x + pad, mid);
        g.fillStyle = col; g.fillRect(bx, Math.round(mid - rh * 0.22), len, Math.round(rh * 0.44));
        g.fillStyle = C.dark; g.fillRect(bx, Math.round(mid + rh * 0.22) - 4, len, 4);
        g.fillStyle = r[2] ? C.teal : C.lilac; g.fillText(vals[i], bx + len + 14, mid);
      });
      if (T.n) { g.font = '28px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, T.n, lw2 - 2 * pad), x + pad, cy + rowsH - pad - 8); }
    }
    well(g, rx, cy, rw, rowsH);
    var V = d.viz;
    if (V) {
      cap(V.t || '', rx + pad, cy + pad + 10);
      var vx = rx + pad, vw = rw - 2 * pad, vy = cy + pad + 50, vh = rowsH - 2 * pad - 50;
      if (V.kind === 'dist') {
        var B = V.bins, n = B.length, step = n > 1 ? B[1][0] - B[0][0] : 1, lo = B[0][0], hi = B[n - 1][0] + step, mxc = Math.max.apply(null, B.map(function (b) { return b[1]; })) || 1;
        var bw2 = Math.floor(vw / n), base = vy + vh - 130, hh = vh - 150;
        var X = function (v) { return vx + (v - lo) / (hi - lo) * bw2 * n; };
        B.forEach(function (b, i) {
          var bh2 = Math.max(b[1] ? 8 : 0, Math.round(hh * b[1] / mxc / 8) * 8), x0 = vx + i * bw2;
          g.fillStyle = b[0] + step / 2 >= (V.mark != null ? V.mark : -1e9) ? C.teal : '#9a8cc4';
          g.fillRect(x0 + 2, base - bh2, bw2 - 6, bh2);
        });
        g.fillStyle = C.lilac; g.fillRect(vx, base, bw2 * n, 4);
        g.font = '32px ' + FONT; g.fillStyle = C.white;
        var ax = function (v) { return String(+v.toFixed(3)).replace('-', '−'); };
        g.textAlign = 'left'; g.fillText(ax(lo), vx, base + 116); g.textAlign = 'right'; g.fillText(ax(hi), vx + bw2 * n, base + 116); g.textAlign = 'left';
        var mEnd = -1e9;
        (V.marks || []).forEach(function (m) {   // a mark: a pixel post under the axis, its label below (a second row when they touch)
          var mx2 = Math.round(X(m[0])); g.font = '28px ' + FONT; var mw = g.measureText(m[1]).width, row = mx2 - mw / 2 < mEnd + 12 ? 1 : 0;
          g.fillStyle = C.white; g.fillRect(mx2 - 2, base + 4, 4, 16 + row * 36);
          g.textAlign = 'center'; g.fillText(m[1], mx2, base + 44 + row * 36); g.textAlign = 'left';
          if (!row) mEnd = mx2 + mw / 2;
        });
      } else if (V.kind === 'cal') {
        var lo2 = V.lo, hi2 = V.hi, sz = Math.min(vw, vh - 40), ox = vx + (vw - sz) / 2 + 20, oy = vy + 10, s2 = sz - 40;
        var P = function (v) { return (v - lo2) / (hi2 - lo2) * s2; };
        g.fillStyle = C.dark; g.fillRect(ox, oy, s2, s2);
        for (var k = 0; k <= s2; k += 8) { g.fillStyle = 'rgba(200,199,255,0.45)'; g.fillRect(ox + k, oy + s2 - k - 4, 4, 4); }   // the exact line, in pixels
        V.rows.forEach(function (r) {
          var px2 = ox + P(r[0]), py2 = oy + s2 - P(r[1]), rr = Math.max(8, Math.min(24, Math.round(Math.sqrt(r[2]) / 2 / 4) * 4));
          g.fillStyle = C.teal; g.fillRect(Math.round(px2 - rr / 2), Math.round(py2 - rr / 2), rr, rr);
        });
        g.font = '28px ' + FONT; g.fillStyle = C.lilac;
        var lab = function (v) { return V.pct ? Math.round(v * 100) + '%' : String(v); };
        g.fillText(lab(lo2), ox, oy + s2 + 28); g.textAlign = 'right'; g.fillText(lab(hi2), ox + s2, oy + s2 + 28);
        g.fillText('given →', ox + s2, oy + s2 + 60); g.textAlign = 'left'; g.fillText('became ↑', ox - 20, oy - 6 < cy + pad + 40 ? oy + 24 : oy - 6);
      } else if (V.kind === 'bars') {
        var VR = V.rows, rh2 = Math.min(84, vh / VR.length), fz = rh2 >= 72 ? 40 : 32; g.font = fz + 'px ' + FONT;
        var lw3 = Math.max.apply(null, VR.map(function (r) { return g.measureText(r[0]).width; })) + 20;
        var vv = VR.map(function (r) { return num(r[1], null, false, V.unit); }), vw3 = Math.max.apply(null, vv.map(function (t) { return g.measureText(t).width; })) + 16;
        var bx3 = vx + lw3, bw3 = vw - lw3 - (V.txt ? 0 : vw3), mx3 = Math.max.apply(null, VR.map(function (r) { return +r[1] || 0; })) || 1;
        VR.forEach(function (r, i) {
          var mid = vy + i * rh2 + rh2 / 2; g.font = fz + 'px ' + FONT; g.fillStyle = C.white; g.fillText(r[0], vx, mid);
          if (V.txt) { g.fillStyle = C.teal; g.fillText(fit(g, String(r[1]), bw3), bx3, mid); return; }
          var len = Math.max(8, Math.round(bw3 * (+r[1]) / mx3 / 8) * 8);
          g.fillStyle = C.teal; g.fillRect(bx3, Math.round(mid - rh2 * 0.22), len, Math.round(rh2 * 0.44));
          g.fillStyle = C.teal; g.fillText(vv[i], bx3 + len + 12, mid);
        });
      } else if (V.kind === 'scale') {
        var lo4 = V.lo, hi4 = V.hi, ry = vy + vh / 2 - 30, X4 = function (v) { return vx + Math.round((v - lo4) / (hi4 - lo4) * vw / 8) * 8; };
        for (var q = 0; q < 10; q++) { var t4 = q / 9; g.fillStyle = t4 < .5 ? 'rgba(200,199,255,' + (.25 + t4 * 1.3).toFixed(2) + ')' : 'rgba(127,255,212,' + (.35 + (t4 - .5) * 1.3).toFixed(2) + ')'; g.fillRect(vx + Math.round(vw * q / 10), ry, Math.round(vw / 10) - 4, 60); }
        (V.ticks || []).forEach(function (tk, i) {
          var tx4 = X4(tk[0]), L = i === V.ticks.length - 1, F0 = i === 0; g.fillStyle = C.white; g.fillRect(tx4 - (L ? 8 : F0 ? 0 : 4), ry - 14, 8, 88);
          g.textAlign = F0 ? 'left' : L ? 'right' : 'center'; g.font = '40px ' + FONT; g.fillText(num(tk[0]), tx4, ry + 116);
          g.font = '32px ' + FONT; g.fillStyle = +tk[0] === +V.mark ? C.teal : C.lilac; g.fillText(tk[1], tx4, ry - 44); g.textAlign = 'left';
        });
      }
    }
    cy += rowsH + gap;
    // top 10
    var TP = d.top;
    var left = y + h - cy - (d.foot ? 52 : 0);
    if (TP && TP.rows && TP.rows.length && left > 200) {
      well(g, x, cy, w, left);
      cap(TP.t, x + pad, cy + pad + 10, C.teal);
      var TR = TP.rows, t0 = cy + pad + 48, trh = Math.min(64, (left - (t0 - cy) - pad) / TR.length), tfz = trh >= 60 ? 40 : 32;
      var tv = TR.map(function (r) { return num(r[3], TP.dec, TP.sign, TP.unit); }), tmax = Math.max.apply(null, TR.map(function (r) { return Math.abs(+r[3]) || 0; })) || 1;
      g.font = tfz + 'px ' + FONT;
      var valCol = Math.max.apply(null, tv.map(function (t) { return g.measureText(t).width; })) + 24;
      g.font = '32px ' + FONT; var subCol = Math.max.apply(null, TR.map(function (r) { return r[4] ? g.measureText(r[4]).width + 32 : 0; })); g.font = tfz + 'px ' + FONT;
      var cRk = x + pad, cNm = cRk + 72, cSe = x + Math.round(w * 0.42), cTm = x + Math.round(w * 0.55), cBar = x + Math.round(w * 0.68), cVal = x + w - pad;
      TR.forEach(function (r, i) {
        var mid = t0 + i * trh + trh / 2;
        if (i % 2 === 0) { g.fillStyle = 'rgba(200,199,255,0.06)'; g.fillRect(x + 8, Math.round(mid - trh / 2), w - 16, Math.round(trh)); }
        g.font = tfz + 'px ' + FONT;
        g.fillStyle = C.lilac; g.fillText(String(i + 1), cRk, mid);
        g.fillStyle = C.white; g.fillText(fit(g, r[0], cSe - cNm - 16), cNm, mid);
        g.fillStyle = C.lilac; g.fillText(fit(g, r[1], cTm - cSe - 12), cSe, mid);
        g.fillText(fit(g, String(r[2]) + (r[4] ? '' : ''), cBar - cTm - 12), cTm, mid);
        var bmax = cVal - valCol - subCol - cBar, len = Math.max(8, Math.round(bmax * Math.abs(+r[3]) / tmax / 8) * 8);
        if (r[4]) { g.font = '32px ' + FONT; g.fillStyle = C.lilac; g.fillText(r[4], cVal - valCol - subCol + 16, mid); g.font = tfz + 'px ' + FONT; }
        g.fillStyle = i === 0 ? C.teal : '#5fd9b4'; g.fillRect(cBar, Math.round(mid - trh * 0.2), len, Math.round(trh * 0.4));
        g.textAlign = 'right'; g.fillStyle = C.teal; g.fillText(tv[i], cVal, mid); g.textAlign = 'left';
      });
      cy += left;
    }
    if (d.foot) { g.font = '28px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, d.foot, w), x, y + h - 18); }
    return F.canvas;
  }
  async function buildTerm(win, btn) {
    var d; try { d = JSON.parse(btn.getAttribute('data-gfx-term') || '{}'); } catch (e) { return null; }
    if (!d.t) return null;
    if (d.x) return buildExplain(d);
    var F = await frame(2400, 1350, 'ARKBOARD PROCESS :: GLOSSARY', '', 'arkndjl.net/process' + (d.id ? '#' + d.id : ''));
    var g = F.g, x = F.x, y = F.y, w = F.w, h = F.h, pad = 40;
    var ab = d.ab || String(d.t).replace(/\s*\(.*$/, ''), name = d.name || ((/\(([^)]*)\)/.exec(d.t) || [])[1]) || '';
    var num = function (v, unit) {
      v = +v; var s = Math.abs(v) >= 10 ? (Math.round(v * 10) / 10).toString() : (Math.round(v * 100) / 100).toString();
      s = s.replace(/^(-?)0\./, '$1.');
      return unit === '%' ? s + '%' : unit === '$M' ? '$' + s + 'M' : s;
    };
    // head: the term large in teal, its name under it in lilac, sports as pixel tags on the right
    var sp = (d.sp || []).slice(0, 6), tagW = 0;
    g.font = '40px ' + FONT;
    sp.forEach(function (s) { tagW = Math.max(tagW, g.measureText(String(s).toUpperCase()).width + 40); });
    var cols = sp.length > 3 ? 2 : 1, tagsW = sp.length ? cols * tagW + (cols - 1) * 16 : 0;
    var HH = 400; well(g, x, y, w, HH);
    var room = w - 2 * pad - (tagsW ? tagsW + 48 : 0), as = 240;
    for (; as > 96; as -= 16) { g.font = as + 'px ' + FONT; if (g.measureText(ab).width <= room) break; }
    g.fillStyle = C.teal; g.font = as + 'px ' + FONT; g.fillText(fit(g, ab, room), x + pad, y + pad + as * 0.55);
    if (name) { g.font = '64px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, String(name).toUpperCase(), room), x + pad, y + HH - pad - 16); }
    sp.forEach(function (s, i) {
      var c = cols === 2 ? i % 2 : 0, r = cols === 2 ? Math.floor(i / 2) : i;
      var tx = x + w - pad - tagsW + c * (tagW + 16), ty = y + pad + r * 80;
      g.fillStyle = C.title; g.fillRect(tx, ty, tagW, 64); bevel(g, tx, ty, tagW, 64, true, 4);
      g.font = '40px ' + FONT; g.fillStyle = C.white; g.textAlign = 'center'; g.fillText(String(s).toUpperCase(), tx + tagW / 2, ty + 33); g.textAlign = 'left';
    });
    var top = y + HH + 24, bh = y + h - top;
    var vis = !!(d.scale || (d.parts && d.parts.length) || (d.bars && d.bars.length) || d.n != null);
    var lines = (d.f && d.f.length) ? d.f : [d.s || ''];
    var lw = vis ? Math.round(w * 0.5) : w;
    // left: the formula (white), or the one-line definition when there is none
    well(g, x, top, lw, bh);
    var fs = 96, fl;
    var layout = function () { g.font = fs + 'px ' + FONT; fl = []; lines.forEach(function (t) { fl = fl.concat(wrap(g, t, lw - 2 * pad)); }); };
    for (; fs >= 40; fs -= 8) { layout(); if (fl.length * fs * 1.35 <= bh - 2 * pad) break; }
    if (fs < 40) { fs = 40; layout(); }
    g.fillStyle = (d.f && d.f.length) ? C.white : C.teal; g.font = fs + 'px ' + FONT;
    var fy = top + (bh - fl.length * fs * 1.35) / 2 + fs * 0.65;
    fl.forEach(function (t, i) { g.fillText(fit(g, t, lw - 2 * pad), x + pad, fy + i * fs * 1.35); });
    if (!vis) return F.canvas;
    // right: split bar (blends), scale ruler, bars or a key number, stacked
    var sx = x + lw + 24, sw = w - lw - 24, cx0 = sx + pad, cw = sw - 2 * pad;
    well(g, sx, top, sw, bh);
    var blocks = [];
    if (d.parts && d.parts.length) blocks.push(['parts', 230]);
    if (d.scale) blocks.push(['scale', 300]);
    if (d.bars && d.bars.length) blocks.push(['bars', Math.min(bh - 2 * pad, 120 + 96 * d.bars.length)]);
    if (d.n != null && !(d.bars && d.bars.length)) blocks.push(['n', 320]);
    var used = blocks.reduce(function (a, b) { return a + b[1]; }, 0), gap = blocks.length > 1 ? 40 : 0;
    var by = top + Math.max(pad, (bh - used - gap * (blocks.length - 1)) / 2);
    var COLS = [C.teal, C.lilac, C.white, C.down];
    blocks.forEach(function (b) {
      var kind = b[0], bhh = b[1];
      if (kind === 'parts') {
        var tot = d.parts.reduce(function (a, p) { return a + (+p[1]); }, 0) || 1, px = cx0;
        d.parts.forEach(function (p, i) {
          var pw = i === d.parts.length - 1 ? cx0 + cw - px : Math.round(cw * (+p[1]) / tot / 8) * 8;
          g.fillStyle = COLS[i % COLS.length]; g.fillRect(px, by + 20, pw - (i < d.parts.length - 1 ? 8 : 0), 96);
          g.fillStyle = C.dark; g.fillRect(px, by + 108, pw - (i < d.parts.length - 1 ? 8 : 0), 8);
          g.font = '64px ' + FONT; g.fillStyle = C.dark; g.fillText(num(p[1]), px + 20, by + 66);
          g.font = '40px ' + FONT; g.fillStyle = COLS[i % COLS.length]; g.fillText(fit(g, p[0], pw - 16), px, by + 168);
          px += pw;
        });
      } else if (kind === 'scale') {
        var S = d.scale, lo = +S.lo, hi = +S.hi, span = (hi - lo) || 1, ry = by + 110, rh = 64;
        var X = function (v) { return cx0 + Math.round(cw * (v - lo) / span / 8) * 8; };
        var seg = 12;   // stepped pixel ramp: dark well -> lilac -> teal
        for (var k = 0; k < seg; k++) {
          var t = k / (seg - 1), a = Math.round(cx0 + cw * k / seg), bb = Math.round(cx0 + cw * (k + 1) / seg);
          g.fillStyle = t < 0.5 ? 'rgba(200,199,255,' + (0.25 + t * 1.3).toFixed(2) + ')' : 'rgba(127,255,212,' + (0.35 + (t - 0.5) * 1.3).toFixed(2) + ')';
          g.fillRect(a, ry, bb - a - 4, rh);
        }
        g.fillStyle = C.dark; g.fillRect(cx0, ry + rh - 8, cw, 8);
        var wordEnd = -1e9;   // a word that would touch the one before it goes up a row
        (S.ticks || []).forEach(function (tk, i) {
          var tx = X(+tk[0]), last = i === S.ticks.length - 1, first = i === 0;
          g.fillStyle = C.white; g.fillRect(tx - (last ? 8 : first ? 0 : 4), ry - 16, 8, rh + 32);
          g.textAlign = first ? 'left' : last ? 'right' : 'center';
          g.font = '48px ' + FONT; g.fillStyle = C.white; g.fillText(num(tk[0]), tx, ry + rh + 64);
          if (tk[1] && String(tk[1]) !== num(tk[0])) {
            g.font = '40px ' + FONT; g.fillStyle = +tk[0] === +S.mark ? C.teal : C.lilac;
            var ww = g.measureText(String(tk[1])).width, wl = first ? tx : last ? tx - ww : tx - ww / 2, up = wl < wordEnd + 24;
            if (up) { g.fillRect(tx - 2, ry - 88, 4, 56); }
            g.fillText(String(tk[1]), tx, ry - (up ? 116 : 52)); if (!up) wordEnd = wl + ww;
          }
          g.textAlign = 'left';
        });
        if (S.mark != null) { var mx = X(+S.mark); g.fillStyle = C.teal; g.fillRect(mx - 12, ry - 28, 24, 16); g.fillRect(mx - 12, ry + rh + 12, 24, 16); }
      } else if (kind === 'bars') {
        var B = d.bars, unit = d.unit || '', ry0 = by;
        if (d.bl) { g.font = '40px ' + FONT; g.fillStyle = C.lilac; g.fillText(String(d.bl).toUpperCase(), cx0, by + 24); ry0 += 72; }
        var rowH = Math.min(96, (bhh - (ry0 - by)) / B.length), bf = rowH >= 80 ? 48 : 40;
        g.font = bf + 'px ' + FONT;
        var vals = B.map(function (r) { return num(r[1], unit); });
        var labW = Math.min(cw * 0.36, Math.max.apply(null, B.map(function (r) { return g.measureText(String(r[0])).width; })) + 24);
        var valW = Math.max.apply(null, vals.map(function (t) { return g.measureText(t).width; })) + 24;
        var bx = cx0 + labW, bw = cw - labW - valW;
        var lo2 = Math.min(0, Math.min.apply(null, B.map(function (r) { return +r[1]; }))), hi2 = Math.max(0, Math.max.apply(null, B.map(function (r) { return +r[1]; })));
        var span2 = (hi2 - lo2) || 1, zx = bx + Math.round(bw * (-lo2 / span2));
        B.forEach(function (r, i) {
          var v = +r[1], mid = ry0 + i * rowH + rowH / 2, hb = Math.max(16, Math.round(rowH * 0.5 / 8) * 8);
          var len = v === 0 ? 8 : Math.max(8, Math.round(bw * Math.abs(v) / span2 / 8) * 8), x0 = v < 0 ? zx - len : zx;
          g.fillStyle = C.white; g.fillText(fit(g, String(r[0]), labW - 16), cx0, mid);
          g.fillStyle = v < 0 ? C.down : C.teal; g.fillRect(x0, Math.round(mid - hb / 2), len, hb);
          g.fillStyle = C.dark; g.fillRect(x0, Math.round(mid + hb / 2) - 4, len, 4);
          g.fillStyle = v < 0 ? C.down : C.teal; g.fillText(vals[i], bx + bw + 16, mid);
        });
        if (lo2 < 0) { g.fillStyle = C.lilac; g.fillRect(zx - 2, ry0, 4, rowH * B.length); }
      } else if (kind === 'n') {
        var ns = 192; g.font = ns + 'px ' + FONT;
        while (ns > 64 && g.measureText(String(d.n)).width > cw) { ns -= 16; g.font = ns + 'px ' + FONT; }
        g.textAlign = 'center'; g.fillStyle = C.teal; g.fillText(String(d.n), sx + sw / 2, by + ns * 0.6);
        if (d.nl) { g.font = '48px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, String(d.nl).toUpperCase(), cw), sx + sw / 2, by + ns + 80); }
        g.textAlign = 'left';
      }
      by += bhh + gap;
    });
    return F.canvas;
  }
  // a #rq-<id> (research) or #g-<term> (glossary) link: open the tabs around it, then scroll to it
  function rqFromHash() {
    var h = location.hash.slice(1); try { h = decodeURIComponent(h); } catch (e) {} if (!/^(rq|g)-/.test(h)) return;
    var el = document.getElementById(h);
    if (!el && /^g-/.test(h)) {   // a glossary term in a closed lazy tab: open that tab (below), scroll once it has loaded
      var ix = document.getElementById('libgidx'), tab; try { tab = JSON.parse(ix.textContent)[h]; } catch (e) { tab = null; }
      el = tab && [].filter.call(document.querySelectorAll('[data-tab]'), function (x) { return x.getAttribute('data-tab') === tab; })[0];
      if (!el) return;
      document.addEventListener('ark:lazy', function once() { var t = document.getElementById(h); if (t) { document.removeEventListener('ark:lazy', once); setTimeout(function () { t.scrollIntoView({ block: 'start' }); }, 30); } });
    }
    if (!el) return;
    var slug = function (s) { return String(s).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''); };
    var p = [], n = el;
    while (n && n !== document.body) { if (n.hasAttribute && n.hasAttribute('data-tab')) p.unshift(n.getAttribute('data-tab')); n = n.parentElement; }
    p.forEach(function (t) { var b = [].filter.call(document.querySelectorAll('[data-wintab]'), function (x) { return slug(x.getAttribute('data-wintab')) === slug(t); })[0]; if (b && b.getAttribute('aria-selected') !== 'true') b.click(); });
    if (location.hash !== '#' + h) history.replaceState(null, '', '#' + h);
    setTimeout(function () { el.scrollIntoView({ block: 'start' }); }, 30);
  }
  setTimeout(rqFromHash, 60); window.addEventListener('hashchange', rqFromHash);

  function preview(canvas, name) {
    var url = canvas.toDataURL('image/png');
    var box = document.createElement('div'); box.className = 'gfx'; box.setAttribute('role', 'dialog'); box.setAttribute('aria-label', 'graphic preview');
    box.innerHTML = '<div class="win gfx__win"><div class="win__title"><span class="win__title-text">gfx.exe<span class="win__cursor">_</span></span>' +
      '<button type="button" class="gfx__x" aria-label="close">×</button></div><div class="gfx__body"><img alt="graphic preview"></div>' +
      '<div class="gfx__bar"><a class="cfb__btn" download>save PNG</a><button type="button" class="cfb__btn" data-copy hidden>copy</button><button type="button" class="cfb__btn" data-share hidden>share</button>' +
      '<button type="button" class="cfb__btn" data-close>close</button></div></div>';
    box.querySelector('img').src = url;
    var a = box.querySelector('a'); a.href = url; a.download = name + '.png';
    function close() { box.remove(); document.removeEventListener('keydown', esc); }
    function esc(e) { if (e.key === 'Escape') close(); }
    box.addEventListener('click', function (e) { if (e.target === box || e.target.closest('[data-close], .gfx__x')) close(); });
    document.addEventListener('keydown', esc);
    // copy: the PNG straight to the clipboard. Safari needs the ClipboardItem made inside the tap, with
    // the image as a promise, so the blob is made up front and handed over that way.
    var blobP = new Promise(function (res) { canvas.toBlob(res, 'image/png'); });
    var cp = box.querySelector('[data-copy]');
    if (navigator.clipboard && window.ClipboardItem) {
      cp.hidden = false;
      cp.addEventListener('click', function () {
        navigator.clipboard.write([new ClipboardItem({ 'image/png': blobP })])
          .then(function () { cp.textContent = 'copied'; setTimeout(function () { cp.textContent = 'copy'; }, 1600); })
          .catch(function () { cp.textContent = 'copy failed: use save'; });
      });
    }
    blobP.then(function (blob) {
      var file = new File([blob], name + '.png', { type: 'image/png' }), sh = box.querySelector('[data-share]');
      // the file alone, so the share sheet's "Copy" copies the picture (with text it copies the text)
      if (navigator.canShare && navigator.canShare({ files: [file] })) {
        sh.hidden = false;
        sh.addEventListener('click', function () { navigator.share({ files: [file] }).catch(function () {}); });
      }
    });
    document.body.appendChild(box);
    box.querySelector('[data-close]').focus();
  }

  // ---- ARKLIST performances (arklistperf.html): one sport's ARKLIST players on one day, a tile each with photo, team,
  // the game (opponent, result or live clock) and the statline as pixel cells, the first three stats in teal ----
  async function buildPerf(win, btn) {
    var P = win.__arkPerf; if (!P || !P.data) return null;
    var pick = window.__arkPerfPick, SP = window.__arkPerfSport || {}, ps = P.data.players || [];
    var sport = P.sport, day = P.day;
    // no sport chosen: the sport of the newest game on the day (or overall); no day: that sport's newest game day
    if (!sport) { var best = null; ps.forEach(function (p) { var g = pick(p, day); if (g && (!best || g.d > best.g.d)) best = { p: p, g: g }; }); if (!best) return null; sport = best.p.s; }
    if (!day) { ps.forEach(function (p) { if (p.s === sport && p.g && p.g[0] && (!day || p.g[0].day > day)) day = p.g[0].day; }); if (!day) return null; }
    var rows = ps.filter(function (p) { return p.s === sport; }).map(function (p) { return { p: p, g: pick(p, day) }; }).filter(function (o) { return o.g; });
    if (!rows.length) return null;
    // the biggest night first: first stat (PTS, G+A, yards) high to low
    function lead(o) { var st = o.g.st || []; if (!st.length) return -1; var v = parseFloat(String(st[0][1]).split(/[\/-]/)[0]); return isNaN(v) ? 0 : v; }
    rows.sort(function (a, b) { return lead(b) - lead(a); });
    var dTxt = new Date(day + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' });
    var F = await frame(2160, 2700, 'ARKLIST :: ' + (SP[sport] || sport) + ' :: ' + dTxt, '', 'arkndjl.net/arklist#performances');
    var g = F.g, n = rows.length, cols = n > 7 ? 2 : 1, rn = Math.ceil(n / cols), gap = 20;
    var tw = (F.w - (cols - 1) * gap) / cols, th = Math.min(cols === 1 ? 640 : 420, (F.h - (rn - 1) * gap) / rn);
    var y0 = F.y + Math.max(0, (F.h - (rn * th + (rn - 1) * gap)) / 2);
    for (var i = 0; i < n; i++) {
      var o = rows[i], p = o.p, gm = o.g, tx = F.x + (i % cols) * (tw + gap), ty = y0 + Math.floor(i / cols) * (th + gap), pad = Math.round(th * 0.07);
      well(g, tx, ty, tw, th);
      var phH = th - 2 * pad, phW = Math.round(phH * 0.82), photo = await loadPhoto(p.ph);
      photoFrame(g, photo, tx + pad, ty + pad, phW, phH);
      var x = tx + pad + phW + pad, w = tx + tw - pad - x, sz = Math.max(26, Math.round(th * (cols === 1 ? 0.105 : 0.12))), y = ty + pad + sz * 0.6;
      // name, then team logo + team and the game: @ / vs, opponent logo, result or the live clock
      g.font = sz + 'px ' + FONT; g.fillStyle = C.white; g.fillText(fit(g, p.n, w), x, y);
      y += sz * 1.25;
      var s2 = Math.round(sz * 0.7), lx = x, tl = await loadImg(p.lo), ol = await loadImg(gm.ol);
      g.font = s2 + 'px ' + FONT;
      if (tl) { drawLogo(g, tl, lx, y - s2 * 0.6, s2 * 1.2, s2 * 1.2); lx += s2 * 1.2 + 10; }
      g.fillStyle = C.lilac; var t1 = (p.pos ? p.pos + ' · ' : '') + p.t + ' ' + gm.ha + ' '; t1 = fit(g, t1, w * 0.6); g.fillText(t1, lx, y); lx += g.measureText(t1).width;
      if (ol) { drawLogo(g, ol, lx, y - s2 * 0.6, s2 * 1.2, s2 * 1.2); lx += s2 * 1.2 + 10; }
      g.fillStyle = C.white; var t2 = (gm.o || '') + '  '; g.fillText(t2, lx, y); lx += g.measureText(t2).width;
      var rs = gm.live ? 'LIVE ' + gm.live : ((gm.r || '') + ' ' + (gm.sc || '')).trim();
      g.fillStyle = gm.live || gm.r === 'W' ? C.teal : gm.r === 'L' ? C.down : C.lilac; g.fillText(fit(g, rs, Math.max(40, x + w - lx)), lx, y);
      y += s2 * 1.1;
      // statline cells: as many to a row as fit, the rows sharing what height is left
      var st = gm.st || [], top = y, avail = ty + th - pad - top;
      if (!st.length) { g.font = sz + 'px ' + FONT; g.fillStyle = C.lilac; g.fillText('DNP', x, top + avail / 2); continue; }
      var minW = Math.max(110, sz * 2.6), per = Math.max(1, Math.min(st.length, Math.floor((w + 10) / minW))), lines = Math.ceil(st.length / per);
      per = Math.ceil(st.length / lines);
      var cw = (w - (per - 1) * 10) / per, ch = Math.min(sz * 3.6, (avail - (lines - 1) * 10) / lines);
      for (var k = 0; k < st.length; k++) {
        var cx = x + (k % per) * (cw + 10), cy = top + Math.floor(k / per) * (ch + 10);
        g.fillStyle = C.dark; g.fillRect(cx, cy, cw, ch); bevel(g, cx, cy, cw, ch, false, 3);
        var vs = Math.round(Math.min(ch * 0.5, cw * 0.32)), ls = Math.round(Math.max(16, vs * 0.45));
        g.font = vs + 'px ' + FONT; g.fillStyle = k < 3 ? C.teal : C.white;
        var v = fit(g, String(st[k][1]), cw - 12); g.fillText(v, cx + (cw - g.measureText(v).width) / 2, cy + ch * 0.42);
        g.font = ls + 'px ' + FONT; g.fillStyle = C.lilac;
        var lb = fit(g, st[k][0], cw - 12); g.fillText(lb, cx + (cw - g.measureText(lb).width) / 2, cy + ch * 0.8);
      }
    }
    return F.canvas;
  }

  // ---- depth chart card: one team's chart (layouts/shortcodes/depthchart.html), each player's headline stats
  // (scripts/depth_stats.py) coloured by percentile tier among every team's charted players. Injured starters stay
  // on top with their tag; the player standing in carries FILL-IN. Slots pack into the column count that gives the
  // biggest type, in chart order.
  var DC_LG = { cfb: 'CFB', cbb: 'CBB', nfl: 'NFL', nba: 'NBA', nhl: 'NHL', soccer: 'SOCCER' };
  var DC_INJ = { out: 'O', doubtful: 'D', questionable: 'Q', probable: 'P', 'injured reserve': 'IR', suspension: 'SUSP', 'day-to-day': 'DTD' };
  function dcNum(v, f) {
    if (v == null) return '—';
    if (f === 'i') return String(Math.round(v));
    var dp = +String(f).slice(1) || 1, r = +Math.abs(v).toFixed(dp);
    return (r === 0 ? '' : v > 0 ? '+' : '−') + r.toFixed(dp);
  }
  function dcPack(slots, cols) {   // chart order, column by column, the tallest column as short as it can be
    var tot = slots.reduce(function (a, s) { return a + s.n; }, 0), tgt = Math.ceil(tot / cols);
    for (;; tgt++) {
      var out = [[]], h = 0, ok = true;
      for (var i = 0; i < slots.length; i++) {
        if (h && h + slots[i].n > tgt) { if (out.length === cols) { ok = false; break; } out.push([]); h = 0; }
        out[out.length - 1].push(slots[i]); h += slots[i].n;
      }
      if (ok) return { cols: out, h: Math.max.apply(null, out.map(function (c) { return c.reduce(function (a, s) { return a + s.n; }, 0); })) };
    }
  }
  async function buildDepth(win, btn) {
    var D = win.__dcData, T = win.__dcTeam; if (!D || !T) return null;
    var sport = win.getAttribute('data-dc'), us = win.querySelector('[data-dc-unit]'), only = us && !us.closest('label').hidden ? us.value : '';
    var units = T.units.filter(function (u) { return !only || u.u === only; }), ST = D.stats || [], ns = ST.length;
    var stamp = D.week ? 'week ' + D.week : D.label || '';
    var F = await frame(2160, 2700, (DC_LG[sport] || '') + ' :: depth chart' + (only ? ' :: ' + only : ''), stamp, tabLink(win));
    var g = F.g, x = F.x + 32, y = F.y + 32, w = F.w - 64, gap = 24;
    well(g, F.x, F.y, F.w, F.h);
    // logo in a raised frame, the team name and its group beside it
    var LS = 220, logo = T.logo ? await loadImg(T.logo) : null;
    g.fillStyle = C.face; g.fillRect(x, y, LS, LS); bevel(g, x, y, LS, LS, true, 6);
    g.fillStyle = C.dark; g.fillRect(x + 10, y + 10, LS - 20, LS - 20);
    if (logo) { var lr = Math.min(168 / logo.width, 168 / logo.height), lw = logo.width * lr, lh = logo.height * lr; drawLogo(g, logo, x + (LS - lw) / 2, y + (LS - lh) / 2, lw, lh); }
    var tx = x + LS + 40, tw = w - LS - 40, nsz = 96;
    g.font = nsz + 'px ' + FONT; while (nsz > 60 && g.measureText(T.n).width > tw) { nsz -= 4; g.font = nsz + 'px ' + FONT; }
    g.fillStyle = C.white; g.fillText(fit(g, T.n, tw), tx, y + (T.grp ? 80 : LS / 2));
    if (T.grp) { g.font = '48px ' + FONT; g.fillStyle = C.teal; g.fillText(fit(g, T.grp + (T.div ? ' · ' + T.div : ''), tw), tx, y + 164); }
    var top = y + LS + 44, bottom = F.y + F.h - 24, avail = bottom - top;
    // slots: a header line, then a line a player; half a line between slots in a column
    var U = units.map(function (u) { return { u: u.u, slots: u.s.map(function (s) { return { s: s, n: s[1].length + 1.5 }; }) }; });
    var ruleH = function (u) { return u.u && units.length > 1 ? 64 : 0; }, best = null, cands = [];
    for (var cols = 1; cols <= 4; cols++) {
      var packs = U.map(function (u) { return dcPack(u.slots, cols); }), lines = packs.reduce(function (a, p) { return a + p.h; }, 0);
      var fixed = U.reduce(function (a, u) { return a + ruleH(u) + 16; }, 0), lineH = Math.min(128, (avail - fixed) / lines);
      var colW = (w - (cols - 1) * gap) / cols, font = Math.floor(Math.min(72, lineH * 0.6, colW / (8.5 + 2.9 * ns)));
      var waste = packs.reduce(function (a, pk, i) { var tot = U[i].slots.reduce(function (b, q) { return b + q.n; }, 0); return a + (pk.cols.length < cols ? 1 : 0) + (cols * pk.h - tot) / (cols * pk.h); }, 0);
      cands.push({ cols: cols, packs: packs, lineH: lineH, colW: colW, font: font, waste: waste });
    }
    // the biggest type, unless a layout within 15% of it leaves fewer holes (NHL lines side by side)
    var top1 = Math.max.apply(null, cands.map(function (c) { return c.font; }));
    cands.filter(function (c) { return c.font >= top1 * 0.85; }).forEach(function (c) { if (!best || c.waste < best.waste - 0.05 || (Math.abs(c.waste - best.waste) <= 0.05 && c.font > best.font)) best = c; });
    var fs = best.font, LH = best.lineH, CW = best.colW, sw = Math.round(fs * 2.9), ss = Math.max(24, Math.round(fs * 0.55));
    var cy = top;
    U.forEach(function (u, ui) {
      if (ruleH(u)) { cardRule(g, x, cy + 20, w, u.u.toUpperCase()); cy += ruleH(u); }
      best.packs[ui].cols.forEach(function (col, ci) {
        var cx = x + ci * (CW + gap), ry = cy;
        col.forEach(function (sl) {
          var s = sl.s, bh = Math.round((sl.n - 0.5) * LH);
          g.fillStyle = C.dark; g.fillRect(cx, ry, CW, bh); bevel(g, cx, ry, CW, bh, false, 3);
          // header: slot in teal, stat labels over their columns
          var hy = ry + LH / 2;
          g.font = fs + 'px ' + FONT; g.fillStyle = C.teal; g.fillText(fit(g, String(s[0]).toUpperCase(), CW - 24 - ns * sw), cx + 18, hy);
          g.font = ss + 'px ' + FONT; g.fillStyle = C.lilac; g.textAlign = 'right';
          ST.forEach(function (st, k) { g.fillText(st[0], cx + CW - 18 - (ns - 1 - k) * sw, hy); });
          g.textAlign = 'left';
          s[1].forEach(function (p, i) {
            var py = ry + (i + 1) * LH, my = py + LH / 2, starter = i === 0 || (sport === 'cbb' && s[0] === 'starters');
            if (starter) { g.fillStyle = 'rgba(200,199,255,0.10)'; g.fillRect(cx + 6, py + 4, CW - 12, LH - 8); }
            g.font = ss + 'px ' + FONT; g.fillStyle = C.lilac; g.fillText(String(i + 1), cx + 18, my);
            var nx = cx + 18 + fs * 0.9, room = CW - 18 - ns * sw - (nx - cx) - 12;
            // tags right after the name: injury (pink), fill-in (teal)
            var tags = [], inj = p[3] ? DC_INJ[String(p[3]).toLowerCase()] || String(p[3]).toUpperCase() : '';
            if (inj) tags.push([inj, C.down]);
            if (p[4] === 'fill-in') tags.push(['FILL-IN', C.teal]);
            g.font = ss + 'px ' + FONT; var tagW = tags.reduce(function (a, t) { return a + g.measureText(t[0]).width + ss * 0.6 + 10; }, 0);
            g.font = fs + 'px ' + FONT; g.fillStyle = starter ? C.white : C.light;
            var nroom = Math.max(fs * 3, room - tagW), nm = p[0];
            if (g.measureText(nm).width > nroom) { var pw = String(nm).split(' '); if (pw.length > 1) nm = pw[0][0] + '. ' + surname(nm); }   // C. Beck before a cut name
            nm = fit(g, nm, nroom); g.fillText(nm, nx, my);
            var tgx = nx + g.measureText(nm).width + 12;
            g.font = ss + 'px ' + FONT;
            tags.forEach(function (t) {
              var tw2 = g.measureText(t[0]).width + ss * 0.6;
              if (tgx + tw2 > cx + CW - 18 - ns * sw) return;
              g.fillStyle = t[1]; g.fillRect(tgx, my - ss * 0.62, tw2, ss * 1.24);
              g.fillStyle = C.dark; g.fillText(t[0], tgx + ss * 0.3, my + 1); tgx += tw2 + 10;
            });
            // stats, right-aligned, in tier colours
            g.font = fs + 'px ' + FONT; g.textAlign = 'right';
            ST.forEach(function (st, k) {
              var v = p[6] && p[6][k], val = v ? v[0] : null;
              g.fillStyle = v ? tierCol(v[1]) : C.face;
              g.fillText(dcNum(val, st[1]), cx + CW - 18 - (ns - 1 - k) * sw, my);
            });
            g.textAlign = 'left';
          });
          ry += Math.round(sl.n * LH);
        });
      });
      cy += best.packs[ui].h * LH + 16;
    });
    return F.canvas;
  }


  // ---- daily news roundup (/news/, layouts/shortcodes/news.html): one ET day's heaviest items (the day's `top` ids from
  // scripts/news.py: by weight, capped per category), the lead as a hero tile, the rest as rows; category icons are the
  // 11x11 bitmaps of data/news_icons.json, the weight five pips ----
  function nwIcon(g, rows, x, y, u, col) {
    if (!rows) return; g.fillStyle = col;
    rows.forEach(function (r, j) { for (var i = 0; i < r.length; i++) if (r[i] === '#') g.fillRect(x + i * u, y + j * u, u, u); });
  }
  function nwPips(g, w, right, cy, u) {
    var n = w >= 86 ? 5 : w >= 72 ? 4 : w >= 60 ? 3 : w >= 48 ? 2 : 1, pw = 2 * u, gap = Math.round(u * 0.75), x = right - 5 * pw - 4 * gap;
    for (var i = 0; i < 5; i++) { g.fillStyle = i < n ? (n >= 4 ? C.teal : C.lilac) : C.dark; g.fillRect(x + i * (pw + gap), cy - 2 * u, pw, 4 * u); }
    return 5 * pw + 4 * gap;
  }
  function nwTag(g, t, x, cy, sz) {
    g.font = sz + 'px ' + FONT; var w = g.measureText(t).width + sz, h = Math.round(sz * 1.5);
    g.fillStyle = '#000'; g.fillRect(x + 4, cy - h / 2 + 4, w, h);
    g.fillStyle = C.dark; g.fillRect(x, cy - h / 2, w, h);
    g.fillStyle = C.teal; g.fillText(t, x + sz / 2, cy + 1);
    return w;
  }
  async function buildNews(win, btn) {
    var D; try { D = JSON.parse(document.getElementById('nws-data').textContent); } catch (e) { return null; }
    var day = btn.getAttribute('data-gfx-day'), dy = (D.days || []).filter(function (x) { return x.d === day; })[0]; if (!dy) return null;
    var by = {}; D.items.forEach(function (i) { by[i.id] = i; });
    var top = (dy.top || []).map(function (id) { return by[id]; }).filter(Boolean); if (!top.length) return null;
    var dTxt = new Date(day + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' });
    var F = await frame(2160, 2700, 'NEWS :: ' + dTxt, '', 'arkndjl.net/news');
    var g = F.g, IC = D.icons || {};
    var imgs = await Promise.all(top.map(function (it) { return Promise.all([it.logo ? loadImg(it.logo) : null, it.logo2 ? loadImg(it.logo2) : null]); }));
    // counts strip: the day by section
    var SEC = [['stclaire', 'ST. CLAIRE'], ['arkboard', 'ARKBOARD'], ['1nt', '1NT'], ['laursen', 'LAURSEN_111']], dayItems = D.items.filter(function (i) { return i.d === day; });
    var sh = 112, sy = F.y + F.h - sh, sw = (F.w - 3 * 16) / 4;
    SEC.forEach(function (s, k) {
      var n = dayItems.filter(function (i) { return i.sec === s[0]; }).length, x = F.x + k * (sw + 16);
      well(g, x, sy, sw, sh);
      g.font = '64px ' + FONT; g.fillStyle = n ? C.teal : C.lilac; g.globalAlpha = n ? 1 : 0.45; g.fillText(String(n), x + 24, sy + sh / 2 + 2);
      var nw = g.measureText(String(n)).width;
      g.font = '32px ' + FONT; g.fillStyle = C.lilac; g.fillText(s[1], x + 24 + nw + 20, sy + sh / 2 + 2); g.globalAlpha = 1;
    });
    var bodyH = F.h - sh - 20;
    // the lead: a hero tile
    var L = top[0], rest = top.slice(1), gap = 12, HMIN = 560;
    var rh = rest.length ? Math.min(236, Math.floor((bodyH - HMIN - 20 - gap * (rest.length - 1)) / rest.length)) : 0;
    var hh = rest.length ? Math.min(960, bodyH - 20 - rest.length * rh - gap * (rest.length - 1)) : Math.min(bodyH, 1200);
    well(g, F.x, F.y, F.w, hh);
    g.fillStyle = 'rgba(200,199,255,0.05)'; for (var ly = F.y + 8; ly < F.y + hh - 4; ly += 8) g.fillRect(F.x + 4, ly, F.w - 8, 2);
    var iu = 12, ix = F.x + 40, iy = F.y + 40;
    g.fillStyle = C.dark; g.fillRect(ix - 16, iy - 16, 11 * iu + 32, 11 * iu + 32); bevel(g, ix - 16, iy - 16, 11 * iu + 32, 11 * iu + 32, true, 3);
    nwIcon(g, IC[L.cat], ix, iy, iu, C.teal);
    var hx = ix + 11 * iu + 48, tagW = nwTag(g, L.tag, hx, F.y + 76, 48);
    g.font = '40px ' + FONT; g.fillStyle = C.lilac; g.fillText(String(L.cat).toUpperCase(), hx + tagW + 28, F.y + 78);
    nwPips(g, L.w, F.x + F.w - 40, F.y + 76, 12);
    var lg = imgs[0].filter(Boolean), lgS = 176, lgW = lg.length ? lg.length * (lgS + 20) + 20 : 0;
    lg.forEach(function (im, k) { drawLogo(g, im, F.x + F.w - 40 - lgW + 20 + k * (lgS + 20), F.y + hh - 40 - lgS - (L.s ? 0 : 0), lgS, lgS); });
    var tx = F.x + 40, tw = F.w - 80 - lgW, lines, sz = 112;
    for (;;) { g.font = sz + 'px ' + FONT; lines = wrap(g, L.t, tw); if (lines.length <= 2 || sz <= 64) break; sz -= 16; }
    lines = lines.slice(0, 2); if (lines.length === 2) lines[1] = fit(g, lines[1], tw);
    var subH = L.s ? 72 : 0, blockH = lines.length * sz * 1.12 + subH, by0 = F.y + 40 + 11 * iu + 32, ty = by0 + Math.max(0, (F.y + hh - 28 - by0 - blockH) / 2) + sz * 0.56;
    g.fillStyle = C.white; lines.forEach(function (ln, k) { g.fillText(ln, tx, ty + k * sz * 1.12); });
    if (L.s) { g.font = '48px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, L.s, tw), tx, ty + (lines.length - 1) * sz * 1.12 + sz * 0.56 + 44); }
    // the rest: one row each
    if (rest.length) {
      var ry0 = F.y + hh + 20;
      var big = rh >= 170, ts = big ? 56 : 48, ss = big ? 40 : 32, u = big ? 8 : 6;
      rest.forEach(function (it, k) {
        var y = ry0 + k * (rh + gap), cy = y + rh / 2;
        g.fillStyle = C.face; g.fillRect(F.x, y, F.w, rh); bevel(g, F.x, y, F.w, rh, true, 3);
        var bx = F.x + 20, bs = 11 * u + 2 * u * 2;
        g.fillStyle = C.well; g.fillRect(bx, cy - bs / 2, bs, bs); bevel(g, bx, cy - bs / 2, bs, bs, false, 3);
        nwIcon(g, IC[it.cat], bx + 2 * u, cy - 5.5 * u, u, it.w >= 60 ? C.teal : C.lilac);
        var x = bx + bs + 28, right = F.x + F.w - 28;
        right -= nwPips(g, it.w, right, cy, big ? 9 : 8) + 28;
        var ls = imgs[k + 1].filter(Boolean), S = Math.min(rh - 48, 128);
        ls.slice().reverse().forEach(function (im) { right -= S; drawLogo(g, im, right, cy - S / 2, S, S); right -= 16; });
        var l1 = cy - (it.s ? ss * 0.7 : 0), l2 = cy + ts * 0.62;
        var tgw = nwTag(g, it.tag, x, l1, big ? 36 : 32);
        var tmax = right - x - tgw - 28 - 12; g.font = ts + 'px ' + FONT; if (g.measureText(it.t).width > tmax) g.font = (ts - 8) + 'px ' + FONT;
        g.fillStyle = C.white; g.fillText(fit(g, it.t, tmax), x + tgw + 28, l1 + 2);
        if (it.s) { g.font = ss + 'px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, it.s, right - x - 12), x, l2); }
      });
    }
    return F.canvas;
  }

  // ---- games to watch (Standings, layouts/shortcodes/watch.html): the week's top games across sports, one row each:
  // rank, sport tag, start (ET), both sides with full-colour logos, W with its five parts as pixel bars ----
  async function buildWatch(win, btn) {
    var D; try { D = JSON.parse(btn.getAttribute('data-gfx-watch')); } catch (e) { return null; }
    var G = (D.games || []).slice(0, 15); if (!G.length) return null;
    var F = await frame(2160, 2700, 'GAMES TO WATCH :: ' + D.span, '', 'arkndjl.net/arkboard/standings#games-to-watch');
    var g = F.g, n = G.length, gap = 12, rh = Math.min(240, Math.floor((F.h - gap * (n - 1)) / n));
    var imgs = await Promise.all(G.map(function (r) { return Promise.all([r.a.l ? loadImg(r.a.l) : null, r.h.l ? loadImg(r.h.l) : null]); }));
    var big = rh >= 190, ns = big ? 64 : rh >= 160 ? 54 : 44, ss = Math.round(ns * 0.62), ls = Math.round(ns * 1.25);
    var PARTS = [['q', 'Q'], ['c', 'C'], ['s', 'S'], ['l', 'L'], ['t', 'T']];
    G.forEach(function (r, k) {
      var y = F.y + k * (rh + gap), cy = y + rh / 2;
      g.fillStyle = k === 0 ? C.well : C.face; g.fillRect(F.x, y, F.w, rh); bevel(g, F.x, y, F.w, rh, k !== 0, 3);
      // rank
      var rw = Math.round(ns * 1.9);
      g.fillStyle = C.dark; g.fillRect(F.x + 14, y + 14, rw, rh - 28); bevel(g, F.x + 14, y + 14, rw, rh - 28, false, 3);
      g.font = Math.round(ns * 1.1) + 'px ' + FONT; g.fillStyle = k < 3 ? C.teal : C.lilac; g.textAlign = 'center';
      g.fillText(String(r.rk), F.x + 14 + rw / 2, cy + 2); g.textAlign = 'left';
      // W and its parts on the right
      var bw = Math.round(ss * 1.3), bgap = Math.round(ss * 0.35), partsW = PARTS.length * bw + (PARTS.length - 1) * bgap;
      var right = F.x + F.w - 28, px0 = right - partsW, bh = rh - 28 - ss * 1.6;
      PARTS.forEach(function (pp, i) {
        var v = Math.max(0, Math.min(100, +((r.p || {})[pp[0]] || 0))), bx = px0 + i * (bw + bgap), by = y + 16;
        g.fillStyle = C.dark; g.fillRect(bx, by, bw, bh);
        var fh = Math.round(bh * v / 100 / 6) * 6;   // 6px steps: pixel bars
        g.fillStyle = v >= 75 ? C.teal : C.lilac; g.fillRect(bx, by + bh - fh, bw, fh);
        g.font = ss + 'px ' + FONT; g.fillStyle = C.lilac; g.textAlign = 'center'; g.fillText(pp[1], bx + bw / 2, y + rh - 14 - ss * 0.5); g.textAlign = 'left';
      });
      var ws = Math.round(ns * 1.45), wt = String(Math.round(r.w));
      g.font = ws + 'px ' + FONT; var wW = g.measureText('100').width, wx = px0 - 36 - wW;
      g.fillStyle = C.teal; g.textAlign = 'right'; g.fillText(wt, px0 - 36, cy + 2); g.textAlign = 'left';
      // sport tag + start on the top line, the matchup below
      var x = F.x + 14 + rw + 28, room = wx - 24 - x, l1 = y + 14 + ss * 0.9, l2 = y + rh - 18 - ls / 2;
      var tgw = nwTag(g, r.lab, x, l1, ss);
      g.font = ss + 'px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, r.et + ' ET', room - tgw - 20), x + tgw + 20, l1 + 1);
      var sides = [r.a, r.h], sep = r.at === false ? 'v' : '@';
      var label = function (t, short) { return (t.r ? '#' + t.r + ' ' : '') + (short && t.ab ? t.ab : t.n); };
      g.font = ns + 'px ' + FONT; g.fillStyle = C.white;
      var short = false, sepW = g.measureText(' ' + sep + ' ').width + 24, logoW = ls + 14;
      var need = function (sh) { return sides.reduce(function (a, t, i) { return a + (imgs[k][i] ? logoW : 0) + g.measureText(label(t, sh)).width; }, 0) + sepW; };
      if (need(false) > room) short = true;
      var each = (room - sepW) / 2, mx = x;
      sides.forEach(function (t, i) {
        if (i) { g.font = ns + 'px ' + FONT; g.fillStyle = C.lilac; g.fillText(' ' + sep + ' ', mx + 6, l2); mx += sepW; }
        var im = imgs[k][i]; if (im) { drawLogo(g, im, mx, l2 - ls / 2, ls, ls); mx += logoW; }
        g.font = ns + 'px ' + FONT; g.fillStyle = C.white;
        var txt0 = fit(g, label(t, short), short ? each - (im ? logoW : 0) : room);
        g.fillText(txt0, mx, l2); mx += g.measureText(txt0).width;
      });
    });
    return F.canvas;
  }

  document.addEventListener('click', async function (e) {
    var btn = e.target.closest('[data-gfx]'); if (!btn) return;
    var win = btn.closest('.win'); if (!win) return;
    btn.disabled = true; var label = btn.textContent; btn.textContent = '…';
    try {
      var mode = btn.getAttribute('data-gfx-mode');
      if (mode === 'news') { var nc = await buildNews(win, btn); if (nc) preview(nc, 'arkndjl-news-' + btn.getAttribute('data-gfx-day')); return; }
      if (mode === 'watch') { var wc = await buildWatch(win, btn); if (wc) preview(wc, 'arkboard-games-to-watch'); return; }
      var canvas = mode === 'term' ? await buildTerm(win, btn) : mode === 'pcard' ? await buildPCard(win, btn.closest('tr[class*="__detail"]').previousElementSibling) : mode === 'card' ? await buildCard(win, btn) : mode === 'team' ? await buildTeamCard(win, btn) : mode === 'builder' ? await buildBuilder(win, btn) : mode === 'cbbplan' ? await buildCbbPlan(win, btn) : mode === 'coach' ? await buildCoach(win, btn) : mode === 'games' ? await buildGames(win, btn) : mode === 'game' ? await buildGame(win, btn) : mode === 'method' ? await buildMethod(win, btn) : mode === 'rank' ? await buildRank(win, btn) : mode === 'rq' ? await buildRQ(win, btn) : mode === 'bracket' ? await buildBracket(win, btn) : mode === 'pickem' ? await buildPickem(win, btn) : mode === 'perf' ? await buildPerf(win, btn) : mode === 'depth' ? await buildDepth(win, btn)
        : mode === 'lz-social' ? await buildSocial(win, btn) : mode === 'esea-box' ? await buildEseaBox(win, btn) : mode === 'esea-season' ? await buildEseaSeason(win, btn)
        : mode === 'esea-summary' ? await buildEseaSummary(win, btn)
        : mode === 'esea-bracket' ? await buildEseaBracket(win, btn)
        : mode === 'esea-fan' ? await buildFan(win, btn) : mode === 'esea-team' ? await buildTeam(win, btn) : await build(win, btn);
      if (canvas) {
        var pre = SITE === 'arkndjl.net/1nt' ? '1nt-' : SITE === 'arkndjl.net/laursen_111' ? 'laursen-111-' : 'arkboard-';
        if (/^esea-/.test(mode || '')) { preview(canvas, pre + (btn.getAttribute('data-gfx-title') || mode).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 60)); return; }
        if (mode === 'term') { preview(canvas, 'arkboard-process-' + ((JSON.parse(btn.getAttribute('data-gfx-term') || '{}').t) || 'term').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 60)); return; }
        if (mode === 'rq') { preview(canvas, 'arkboard-research-' + ((JSON.parse(btn.getAttribute('data-gfx-rq') || '{}').id) || 'card').toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 60)); return; }
        var name = mode === 'depth' ? 'arkboard-depth-' + (((win.__dcTeam || {}).n) || 'team').toLowerCase().replace(/[^a-z0-9]+/g, '-') : mode === 'perf' ? 'arkboard-arklist-' + ((win.__arkPerf || {}).sport || 'all').replace(/^college-/, '') + '-' + ((win.__arkPerf || {}).day || 'latest') : mode === 'rank' ? (JSON.parse(win.getAttribute('data-gfx-rank') || '{}').name || 'arkboard-ark-top-25') : mode === 'cbbplan' ? 'arkboard-cbb-plan-' + (((window.__arkCbbBuilder || {}).current || {}).t || 'team').toLowerCase().replace(/[^a-z0-9]+/g, '-') : mode === 'builder' ? 'arkboard-plan-' + ((window.__arkBuilder || {}).current || {}).team.toLowerCase().replace(/[^a-z0-9]+/g, '-') : mode === 'coach' ? 'arkboard-coach-' + ((window.__arkCoaches || [])[+btn.getAttribute('data-gfx-i')] || {}).name.toLowerCase().replace(/[^a-z0-9]+/g, '-') : mode === 'pcard' ? 'arkboard-' + ((btn.closest('tr[class*="__detail"]').querySelector('.cfb__dhead b, b') || {}).textContent || 'player').toLowerCase().replace(/[^a-z0-9]+/g, '-') : mode === 'team' ? 'arkboard-team-' + (btn.getAttribute('data-gfx-name') || 'team').toLowerCase().replace(/[^a-z0-9]+/g, '-') : mode === 'card' || mode === 'game' || mode === 'method' || mode === 'bracket' || mode === 'pickem' ? 'arkboard-' + (btn.getAttribute('data-gfx-name') || 'player').toLowerCase().replace(/[^a-z0-9]+/g, '-') : pre + (btn.hasAttribute('data-gfx-top') ? (rowsWanted(win, btn) === ROWS_MAX && (btn.parentNode.querySelector('.gfx-rows select') || {}).value === 'all' ? 'all-' : 'top-' + rowsWanted(win, btn) + '-') : '') + txt(win.querySelector('.win__title-text')).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 60);
        preview(canvas, name);
      }
    } catch (err) {
      console.error('gfx', mode, err); btn.disabled = false; btn.textContent = 'GFX failed'; setTimeout(function () { btn.textContent = label; }, 2500); return;
    } finally { if (btn.textContent === '…') { btn.disabled = false; btn.textContent = label; } }
  });
})();
