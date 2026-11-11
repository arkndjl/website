// Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
(function () {
  if (window.__arkGfx) return; window.__arkGfx = true;
  var W, H, PAD = 60;
  var C = { bg: '#4a3b6b', face: '#4a3b6b', well: '#3a2d56', light: '#c8c7ff', dark: '#241a3a', title: '#57068c', teal: '#7fffd4', lilac: '#c8c7ff', white: '#ffffff', down: '#ff9ec7' };
  var FONT = '"MS PGothic Pixel", "MS PGothic", monospace';
  // college WAR a season per AV (scripts/cfb_av.mjs): team-builder values are AV at FV, drawn as WAR
  var WARK = {{ with site.Data.cfb_war_backtest }}{{ .constants.cwarPerAv }}{{ else }}0.0953{{ end }};
  // the sport's short link (static/_redirects): /cfb -> /arkboard/college-football/, the hash carried through
  var SITE = 'arkndjl.net/' + ([[/^\/laursen_111/i, '1nt'], [/college-football/, 'cfb'], [/college-basketball/, 'cbb'], [/arkboard\/nfl/, 'nfl'], [/arkboard\/nba/, 'nba'],
    [/arkboard\/nhl/, 'nhl'], [/hockey-prospects/, 'hockey'], [/soccer-prospects/, 'u22'], [/arkboard\/soccer/, 'soccer'], [/arkboard\/baseball/, 'baseball'],
    [/arkboard\/predictions/, 'picks'], [/arkboard\/arklist/, 'arklist'], [/arkboard\/reference/, 'reference'], [/./, 'arkboard']].filter(function (x) { return x[0].test(location.pathname); })[0][1]);
  // the short link a graphic prints: the sport's short path plus the tab it came from (#<tab>), or a player (#<board>:p=<key>)
  function tabLink(win) { var t = win && win.closest('[data-tab]'); t = t && t.getAttribute('data-tab'); return SITE + (t && !/1nt$/.test(SITE) ? '#' + String(t).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') : ''); }
  function txt(el) { return (el && el.textContent || '').replace(/\s+/g, ' ').trim(); }
  // a photo from another site (ESPN, Wikimedia) loads with CORS so the canvas can still be saved
  function loadPhoto(src) {
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
    if (t.real || t.kind === 'value') {                              // solid: lilac (traded pick) or teal (value)
      g.fillStyle = C.title; g.fillRect(x + 3, y + 3, w, h);        // pixel drop shadow
      g.fillStyle = t.real ? C.lilac : C.teal; g.fillRect(x, y, w, h);
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

  async function build(win, btn) {
    var table = win.querySelector('table'); if (!table) return null;
    var hcells = [].slice.call(table.tHead.rows[0].cells), vis = hcells.filter(function (h) { return !h.hidden; });
    // a board that renders only its shown columns (the basketball board swaps xBPM/Age for Outcome on past seasons): headers by what's shown
    var row0 = [].slice.call(table.tBodies[0].rows).find(function (r) { return !r.classList.contains('cfb__detail') && r.cells.length > 2; });
    if (row0 && vis.length < hcells.length && row0.cells.length === vis.length) hcells = vis;
    var heads = hcells.map(txt);
    var want = (win.getAttribute('data-gfx-cols') || '').split(',').map(function (s) { return s.trim().toLowerCase(); }).filter(Boolean);
    // a column name ending in "!" draws only its logo
    var iconOnly = {};
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
        var cc = c && c.cloneNode(true); if (cc) cc.querySelectorAll('.gfx-off, .cfb__star, .cfb__carried, .cfb__warin, .cfb__riser, .cfb__injchip, .cfb__rbrole, .cfb__medals, .cfb__upchip, .cfb__movechip, .cfb__multichip, .cfb__valuechip, .cfb__reachchip, .cfb__divtag, .pxframe, .cfbst__more, .nflwar__col, .nflwar__tm, .nflwar__rook, .esea-flag, .nbaxpm__tm, .nbaxpm__od').forEach(function (e) { e.remove(); });
        var cell = { t: txt(cc).replace(/[▾▴▸★↗]/g, '').trim() };
        // ARK stars (recruit tabs): pixel stars, 5-star+ in lilac with a plus
        var ark = c && c.querySelector('.cfbrc__ark[data-n]');
        if (ark) { var an = +ark.getAttribute('data-n'); cell.t = new Array(Math.floor(Math.min(an, 5)) + 1).join('✦') + (an % 1 ? '✧' : '') + (an > 5 ? '+' : ''); cell.color = C.teal; cell.glow = an > 5; }
        // mock draft trade tags: a pick already traded (solid) or a projected trade (dashed, ⇅)
        var tags = c ? [].slice.call(c.querySelectorAll('.cfbm__trade[data-g]')) : [];
        if (tags.length) cell.tags = tags.map(function (e) { return { t: e.getAttribute('data-g'), real: e.classList.contains('is-real') }; });
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
    g.fillText(fit(g, title, ww - 300) + '_', wx + 92, wy + 45);
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
    var keep = function (k) { var h = heads[cols[k]]; return k === 0 || cols[k] === sortI || (ageI >= 0 && cols[k] === ageI) || NAME_COL.test(h) || POS_COL.test(h) || CLASS_COL.test(h) || TEAM_COL.test(h) || FV_COL.test(h) || cdata.some(function (r) { return r[k].img; }); };
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
  async function frame(w, h, title, stamp, link) {
    W = w; H = h;
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
    g.fillText(fit(g, title, ww - 300) + '_', wx + 92, wy + 45);
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
    // photo (framed) at the left, then the name line: logo, name, FV chip
    var photo = await loadPhoto(r.photo ? 'https://a.espncdn.com/combiner/i?img=' + encodeURIComponent(r.photo.replace(/^https?:\/\/a\.espncdn\.com/, '')) + '&w=700&h=509&scale=crop' : null);
    var px = photo ? 400 : 0, top = y;
    if (photo) photoFrame(g, photo, x, y - 60, 370, 400);
    var logo = await loadImg(r.logo);
    if (logo) drawLogo(g, logo, x + px, y - 48, 96, 96);
    g.font = '96px ' + FONT; g.fillStyle = C.white;
    var nx = x + px + (logo ? 120 : 0); g.fillText(fit(g, r.name, w - px - 420), nx, y);
    if (r.fv != null) chip(g, x + w - 260, y, String(r.fv) + (r.plus ? '+' : ''), 112, r.fv);
    y += 110;
    g.font = '48px ' + FONT; g.fillStyle = C.teal;
    var ageS = r.age != null ? 'age ' + r.age.toFixed(1) : r.ageEst != null ? 'age ~' + r.ageEst.toFixed(1) : null;
    g.fillText(fit(g, [r.pos + (r.spot ? ' · ' + r.spot : ''), ageS, r.team, r.conf, r.cls].filter(Boolean).join(' · '), w - px), x + px, y);
    y += 80;
    if (rep.role) { g.font = '48px ' + FONT; g.fillStyle = C.lilac; wrap(g, 'role: ' + rep.role + '.' + (r.arch ? ' type: ' + r.arch : ''), w - px).forEach(function (l) { g.fillText(l, x + px, y); y += 64; }); }
    // flags: RB role, ARKLIST, riser, availability, position change, FCS move-up, as outlined pills
    var ROLE = { every: 'EVERY DOWN BACK', early: 'EARLY DOWN BACK', third: '3RD DOWN BACK' };
    var multi = (r.multi || []).filter(function (m) { return m.pos !== r.move && !(r.move === 'IOL' && (m.pos === 'G' || m.pos === 'C')); }).map(function (m) { return m.pos; });
    var flags = [[ROLE[r.rbRole], C.teal], [r.star && '⟁ ARKLIST', C.teal], [r.riser && '↗ RISER', '#7dffb0'], [r.inj && r.inj.toUpperCase(), C.down],
                 [r.move && '⇄ ' + r.move, C.lilac], [multi.length && '+ ' + multi.join('/'), C.teal], [r.moveUp && '▲ FBS ' + Math.round(r.up * 100) + '%', C.teal]].filter(function (f) { return f[0]; });
    if (flags.length) {
      g.font = '36px ' + FONT; var fx = x + px; y += 6;
      flags.forEach(function (f) { var fw = g.measureText(f[0]).width + 32; if (fx + fw > x + w) return;
        g.strokeStyle = f[1]; g.lineWidth = 3; g.strokeRect(fx + 1.5, y - 26, fw - 3, 52); g.fillStyle = f[1]; g.fillText(f[0], fx + 16, y + 2); fx += fw + 16; });
      y += 60;
    }
    y = Math.max(y, top + 360) + 40;
    // the numbers, in three labelled bands of tiles: label, value, and a small line under it
    function band(label, tiles, cols) {
      g.font = '40px ' + FONT; g.fillStyle = C.lilac; g.fillText(label, x, y);
      var lw = g.measureText(label).width; g.fillStyle = C.dark; g.fillRect(x + lw + 24, y - 1, w - lw - 24, 3);
      y += 44;
      var gap = 24, tw = (w - (cols - 1) * gap) / cols, th = 176;
      tiles.forEach(function (t, i) {
        var tx = x + i * (tw + gap);
        g.fillStyle = C.face; g.fillRect(tx, y, tw, th); bevel(g, tx, y, tw, th, true, 3);
        g.font = '34px ' + FONT; g.fillStyle = C.lilac; g.fillText(t[0], tx + 24, y + 42);
        g.font = '72px ' + FONT; g.fillStyle = t[2] || C.white; g.fillText(fit(g, t[1], tw - 48), tx + 24, y + 104);
        if (t[3]) { g.font = '30px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, t[3], tw - 48), tx + 24, y + 150); }
      });
      y += th + 40;
    }
    var dash = '—', age = r.age != null ? r.age.toFixed(1) : r.ageEst != null ? '~' + r.ageEst.toFixed(1) : dash;
    var zm = function (n) { return (n < 0 ? '−' : '+') + money(Math.abs(n)); }, d = r.delta;
    var moved = d === 'new' ? 'new this week' : typeof d === 'number' && d ? (d > 0 ? '▲' + d : '▼' + (-d)) + ' this week' : null;
    band('PROFILE', [['AGE', age, null, [r.cls, r.draft27 ? '2027 draft eligible' : null].filter(Boolean).join(' · ')],
                     ['HT / WT', (r.ht || dash) + ' / ' + (r.wt || dash), null, r.bmi ? 'BMI ' + r.bmi.toFixed(1) : null],
                     ['SNAP SHARE', r.snapShare != null ? Math.round(r.snapShare * 100) + '%' : dash, null, r.snaps ? r.snaps + ' snaps' : null],
                     ['BOARD', '#' + r.ovr, null, moved]], 4);
    band('GRADE', [['STAT+', r.statPlus == null ? dash : String(r.statPlus), r.statPlus != null && r.statPlus >= 100 ? C.teal : null,
                    '100 = avg' + (r.pfn != null ? ' · ' + (r.pfnLabel || 'PFN') + ' ' + r.pfn.toFixed(1) : '')],
                   ['ON3', r.on3 == null ? dash : String(r.on3), null, 'talent grade'],
                   ['CONSENSUS', r.cons == null ? dash : '#' + r.consRk, null, r.cons == null ? 'unranked' : 'avg ' + r.cons.toFixed(1) + ' · ' + r.consN + ' of 10 boards'],
                   ['POS RK', r.posRank ? r.pos + r.posRank : dash, null, r.arch || null]], 4);
    band('NIL', [['xNIL', r.xnil ? money(r.xnil) : dash, C.teal, 'market value, now'],
                 ['yNIL', r.ynil != null ? money(r.ynil) : dash, null, 'est. preseason pay'],
                 ['zNIL', r.znil != null ? zm(r.znil) : dash, r.znil == null ? null : r.znil >= 0 ? C.teal : C.down, r.znil == null ? null : r.znil >= 0 ? 'xNIL - yNIL, gain' : 'xNIL - yNIL, loss']], 3);
    // position change: the projected spot and the model's reason, in a panel under the numbers
    if (r.move && r.moveWhy) {
      g.font = '40px ' + FONT; g.fillStyle = C.lilac; g.fillText('POSITION CHANGE', x, y);
      var pl = g.measureText('POSITION CHANGE').width; g.fillStyle = C.dark; g.fillRect(x + pl + 24, y - 1, w - pl - 24, 3); y += 44;
      g.font = '72px ' + FONT; var lab = r.pos + ' → ' + r.move, tx2 = x + 24 + g.measureText(lab).width + 48;
      g.font = '36px ' + FONT;
      var why = wrap(g, r.moveWhy.charAt(0).toUpperCase() + r.moveWhy.slice(1) + '.', x + w - 24 - tx2).slice(0, 3), ph = Math.max(120, 48 + why.length * 48);
      g.fillStyle = C.face; g.fillRect(x, y, w, ph); bevel(g, x, y, w, ph, true, 3);
      g.font = '72px ' + FONT; g.fillStyle = C.white; g.fillText(r.pos, x + 24, y + ph / 2);
      var aw = g.measureText(r.pos + ' ').width; g.fillStyle = C.teal; g.fillText('→ ' + r.move, x + 24 + aw, y + ph / 2);
      g.font = '36px ' + FONT; g.fillStyle = C.lilac;
      why.forEach(function (l, i) { g.fillText(l, tx2, y + ph / 2 - (why.length - 1) * 24 + i * 48); });
      y += ph + 40;
    }
    if (r.badges && r.badges.length) {
      g.font = '40px ' + FONT; g.fillStyle = C.lilac; g.fillText('BADGES', x, y);
      var bl = g.measureText('BADGES').width; g.fillStyle = C.dark; g.fillRect(x + bl + 24, y - 1, w - bl - 24, 3); y += 50;
      y += badgeRows(g, r.badges, x, y, w);
    }
    // strengths and concerns, side by side
    function list(label, items, color, lx, cw, room) {
      var ly = y;
      g.font = '56px ' + FONT; g.fillStyle = color; g.fillText(label, lx, ly); ly += 80;
      g.font = '40px ' + FONT;
      (items || []).forEach(function (it) {
        var lines = wrap(g, it, cw - 56); if (ly + lines.length * 54 > room) return;
        g.fillStyle = color; g.fillText(label[0], lx + 4, ly);
        g.fillStyle = C.lilac; lines.forEach(function (l) { g.fillText(l, lx + 56, ly); ly += 54; }); ly += 14;
      });
      if (!(items || []).length) { g.fillStyle = C.lilac; g.fillText('none', lx + 56, ly); }
    }
    // what drives the grade: each feeder's weighted pull on the composite, pinned to the bottom
    // the composite's seven feeders, as in the dropdown (the 8th part, frame, is a step in FV, not in the composite);
    // ESPN backups and K/P have no composite
    var comp = r.parts && r.src !== 'espn' && r.pos !== 'K' && r.pos !== 'P';
    var parts = comp ? r.parts.slice(0, 7) : [], labels = [r.div === 'FCS' ? 'level' : 'talent', 'production', 'age + class', 'breakout', 'stats', 'pedigree', 'context'];
    var steps = window.__arkCfbSteps ? window.__arkCfbSteps(r) : null;
    // two columns of four cells: seven bars and the grade -> FV line
    var barsH = parts.length ? 110 + 4 * 60 : 0, bottom = F.y + F.h - 40 - barsH, half2 = (w - 60) / 2;
    list('+ strengths', rep.plus, C.teal, x, half2, bottom);
    list('− concerns', rep.minus, C.down, x + half2 + 60, half2, bottom);
    if (parts.length) {
      var by = F.y + F.h - barsH - 10, cw2 = (w - 80) / 2;
      g.fillStyle = C.dark; g.fillRect(x, by - 30, w, 3);
      g.font = '48px ' + FONT; g.fillStyle = C.lilac; g.fillText('FV inputs: weighted pull on the composite', x, by + 30);
      g.font = '36px ' + FONT;
      labels.forEach(function (l, i) {
        var cx = x + Math.floor(i / 4) * (cw2 + 80), yy = by + 110 + (i % 4) * 60, bx0 = cx + 270, bwid = cw2 - 270 - 120, mid = bx0 + bwid / 2, half = bwid / 2;
        var v = parts[i] || 0, bw = Math.min(half, Math.abs(v) / 2 * half);
        g.fillStyle = C.lilac; g.fillText(l, cx, yy);
        g.fillStyle = C.well; g.fillRect(bx0, yy - 18, bwid, 36);
        g.fillStyle = C.dark; g.fillRect(mid - 1, yy - 24, 3, 48);
        g.fillStyle = v < 0 ? C.down : C.teal; g.fillRect(v < 0 ? mid - bw : mid + 2, yy - 14, bw, 28);
        var lab = (v > 0 ? '+' : '') + v.toFixed(2); g.fillStyle = C.lilac; g.fillText(lab, cx + cw2 - g.measureText(lab).width, yy);
      });
      // 8th cell: the grade the composite gives, and the headline after the steps (frame, years, consensus, injury,
      // mean outcome, returns, scale)
      if (steps && steps.length) { g.fillStyle = C.lilac; g.fillText('grade ' + (+steps[0][1]).toFixed(0) + ' → FV ' + r.fv, x + cw2 + 80, by + 110 + 3 * 60); }
    }
    return F.canvas;
  }

  // ---- player card for any board (every sport but the CFB board, which has its own): read from the player's table row
  // and, where the board has one, its dropdown (photo, role lines, strengths and concerns, FV inputs, badges). The header
  // carries photo, logo, flag, name, position, team, class and FV; the sorted column is the featured tile with the player's
  // place in the view; every other column is a tile with where the value sits among the rows in view (pNN, 0 = lowest).
  // context columns a card shows as a fact strip under the name (no percentile tile)
  var PC_INFO = /^(age|g|gp|gs|mp|min|toi|snaps|ht|wt|ht \/ wt|yrs|salary|contract|nhl gp|wt\. gp|starts)$/i;
  // a percentile bar in pixel blocks: 20 cells of 5 points, lit to the value
  function pxBar(g, x, y, w, h, pct, col) {
    var n = 20, gap = Math.max(3, Math.round(h / 4)), cw = (w - (n - 1) * gap) / n, lit = Math.round(pct / 5);
    for (var k = 0; k < n; k++) { g.fillStyle = k < lit ? col : C.dark; g.fillRect(Math.round(x + k * (cw + gap)), y, Math.ceil(cw), h); }
  }
  var PC_SKIP = /^(rk|#|pick|spot|tm)$/i, PC_SUB = /^(pos|position|team|school|club|org|league|lg|conf|class|yr|year|season|plays|tag|stage)$/i;
  var PC_NOPCT = /^(rank|cons|xslot|vrs|ht|wt|ht \/ wt|range|w-l|rec|season line|plays|tag|contract|yrs|last|form|roster|stage)$/i;
  var PC_MARKS = '.gfx-off, .cfb__star, .cfb__carried, .cfb__warin, .cfb__riser, .cfb__injchip, .cfb__rbrole, .cfb__medals, .cfb__upchip, .cfb__movechip, .cfb__multichip, .cfb__valuechip, .cfb__reachchip, .cfb__divtag, .pxframe, .cfbst__more, .nflwar__col, .nflwar__tm, .nflwar__rook, .esea-flag, .nbaxpm__tm, svg, img';
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
  var PC_XSKIP = /mock|backup|arklist|breakout|past|^v\d+$|game|ranking|odds|lineup|on\/off|fv model/i;
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
        if (i === k || i === ti || !h || shown[lc] || PC_SKIP.test(h) || PC_SUB.test(h) || FV_COL.test(h) || (hc[i] && hc[i].hidden) || !r.cells[i] || r.cells[i].hidden) return;
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
  function pcGShape(gp) {
    var n = gp.items.length, cols = n <= 6 ? Math.max(n, 3) : n <= 8 ? 4 : 6;
    return { cols: cols, rows: Math.ceil(n / cols), ch: gp.items.some(function (it) { return it.pct != null; }) ? 192 : 148 };
  }
  async function buildPCard(win, row) {
    var table = row.closest('table'); if (!table) return null;
    var mainR = pcMain(row), extraL = mainR ? pdExtra(row) : '';
    if (mainR) { row = mainR; table = row.closest('table'); }
    var hcells = pcHeads(table), heads = hcells.map(txt), cells = [].slice.call(row.cells);
    var rows = pcAll(table), at = pcAt(table, rows, row), nameI = pcNameAt(heads);
    var det = await pcDetail(row), d = det.el;
    var gi = function (re) { return heads.findIndex(function (h) { return re.test(h); }); };
    var nameC = cells[nameI >= 0 ? nameI : 1];
    var name = nameC && nameC.querySelector('button.cfb__who, b') ? pcName(row, nameI >= 0 ? nameI : 1) : nameC ? pcCell(nameC).t : txt(d && d.querySelector('.cfb__dhead b'));
    var teamI = gi(TEAM_COL), posI = gi(POS_COL), clsI = gi(CLASS_COL), fvI = gi(FV_COL), lgI = gi(/^(league|lg|conf)$/i);
    var tm = row.querySelector('.nbaxpm__tm, .nflwar__tm');
    var team = teamI >= 0 ? pcCell(cells[teamI]).t : tm ? txt(tm).split('·')[0].trim() : '';
    var posC = posI >= 0 && cells[posI] && cells[posI].cloneNode(true); if (posC) posC.querySelectorAll('.cfb__dim, span').forEach(function (e) { e.remove(); });
    var ageI = isYouth(win) ? gi(AGE_COL) : -1, ageT = ageI >= 0 && cells[ageI] ? pcCell(cells[ageI]).t : '';
    if (!/\d/.test(ageT)) { ageI = -1; ageT = ''; }
    var sub = [posC ? txt(posC) : '', ageT ? 'age ' + ageT : '', team, lgI >= 0 ? pcCell(cells[lgI]).t : tm ? (txt(tm).split('·')[1] || '').trim() : '', clsI >= 0 ? pcCell(cells[clsI]).t : ''].filter(function (s) { return s && s !== '—'; });
    var fvChip = fvI >= 0 && cells[fvI] && cells[fvI].querySelector('.fv-chip'), fvT = fvI >= 0 ? pcCell(cells[fvI]).t : '';
    var fvN = fvChip ? parseFloat(fvChip.getAttribute('data-fv')) : parseFloat(fvT);
    // photo: the dropdown's card photo, else the row thumbnail upsized; logo: the row's team logo or the window's path
    var ph = d && d.querySelector('.pxframe--card img'), th0 = row.querySelector('.pxframe img');
    var photo = await loadPhoto(pcBig(ph && (ph.currentSrc || ph.src)) || pcBig(th0 && (th0.currentSrc || th0.src)));
    if (!photo && ph) photo = await loadPhoto(ph.currentSrc || ph.src);
    var lg = [].slice.call(row.querySelectorAll('img.cfb__logo')).find(function (e) { return !e.closest('.pxframe'); }), lsrc = lg && (lg.currentSrc || lg.src);
    var tpl = win.getAttribute('data-gfx-logo'); if (!lsrc && tpl && team) lsrc = tpl.replace('{}', team.split('/').pop().trim().toLowerCase());
    var logo = await loadImg(lsrc);
    var fl = row.querySelector('svg.esea-flag'), fi = row.querySelector('img.flag');
    var flag = fl ? await flagImg((fl.getAttribute('aria-label') || '').toLowerCase()) : fi ? await loadImg(fi.currentSrc || fi.src) : null;
    // the featured stat: the sorted column (or the rank-by view's key column), else the first number after the name
    var sortI = sortedCol(table, hcells), desc = (hcells[sortI] || { getAttribute: function () {} }).getAttribute('aria-sort') !== 'ascending';
    var tiles = [], lines = [], info = [];
    heads.forEach(function (h, i) {
      if (i === nameI || i === fvI || i === ageI || PC_SKIP.test(h) || PC_SUB.test(h) || !h || (hcells[i] && hcells[i].hidden) || !cells[i] || cells[i].hidden) return;
      var c = pcCell(cells[i]); if (c.t === '—' && !c.sub) return;
      if (c.t.length > 18) { lines.push([h, c.t + (c.sub ? ' · ' + c.sub : '')]); return; }
      var n = PC_NOPCT.test(h) ? null : pcNum(cells[i], c.t), pct = null;
      if (n != null) {
        var vals = rows.map(function (r) { var cc = r.cells[i]; return cc ? pcNum(cc, pcCell(cc).t) : null; }).filter(function (v) { return v != null; });
        if (vals.length >= 5) pct = pcPct(vals, n);
      }
      // context columns (age, games, minutes, size, contract) are facts, not grades: a strip under the name, no percentile
      if (PC_INFO.test(h)) { info.push([capHead(h), c.t]); return; }
      var good = pct == null || PD_NEUTRAL.test(h) ? null : PD_LOWER.test(h) ? 100 - pct : pct;
      tiles.push({ i: i, h: h, t: c.t, sub: c.sub, color: c.color, pct: pct, good: good, tip: hcells[i] ? hcells[i].getAttribute('title') : '' });
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
    var feat = tiles.find(function (t) { return t.i === sortI; }) || (fvI < 0 ? tiles.find(function (t) { return t.pct != null; }) : null);
    if (feat) tiles.splice(tiles.indexOf(feat), 1);
    var wt = txt(win.querySelector('.win__title-text')).replace(/_$/, '').trim();
    var base = wt.split('::')[0].trim(); if (/^[a-z0-9]/.test(base)) base = SITE.split('/').pop().toUpperCase() + ' ' + base;
    var pk = row.getAttribute('data-pk'), link = tabLink(win);
    if (pk && /#/.test(link)) link += ':p=' + pk;
    else if (win.getAttribute('data-cbb') && window.__arkCbbPid && row.hasAttribute('data-i') && window.__arkCbbRecs) { var rec = window.__arkCbbRecs[+row.getAttribute('data-i')]; if (rec) link = SITE + '#' + win.getAttribute('data-cbb') + ':p=' + window.__arkCbbPid(rec); }
    var F = await frame(2160, 2700, base + ' :: ' + name, win.getAttribute('data-gfx-date'), link);
    var g = F.g, x = F.x + 40, y = F.y + 70, w = F.w - 80, top = y, bottom = F.y + F.h - 30;
    well(g, F.x, F.y, F.w, F.h);
    var px = 400;
    photoFrame(g, photo, x, y - 60, 370, 400);   // no headshot: the frame keeps its place with the pixel silhouette
    if (logo) drawLogo(g, logo, x + px, y - 48, 96, 96);
    var nx = x + px + (logo ? 120 : 0);
    if (flag) { g.imageSmoothingEnabled = false; g.drawImage(flag, nx, y - 33, 96, 66); nx += 120; }
    g.font = '96px ' + FONT; g.fillStyle = C.white; g.fillText(fit(g, name, x + w - nx - (fvT ? 300 : 0)), nx, y);
    if (fvT && fvT !== '—') chip(g, x + w - 260, y, fvT, 112, isFinite(fvN) ? fvN : 20);
    y += 110;
    g.font = '48px ' + FONT; g.fillStyle = C.teal; g.fillText(fit(g, sub.join(' · '), w - px), x + px, y); y += 80;
    // the dropdown's role / outlook lines, a few, under the name
    // a built dropdown's lines (place in view, ranges, season line) repeat the tiles below: only the subset table's own line
    var auto = !!(d && d.classList.contains('pd__auto'));
    var roles = d && !auto ? [].slice.call(d.querySelectorAll('.cfb__role')).map(txt).filter(Boolean) : [];
    if (extraL && roles.indexOf(extraL + '.') < 0) roles.unshift(extraL);
    info = info.filter(function (f) { return !new RegExp('(^|[ ·])' + f[1].replace(/[.*+?^${}()|[\]\\\/]/g, '\\$&') + ' ').test(sub.join(' · ') + ' '); });   // "250 MP", "415 min" already in the line above
    // the reserve at the bottom for the dropdown (badges, strengths and concerns, FV inputs)
    var plus = d && !auto ? [].slice.call(d.querySelectorAll('.cfb__report li.is-plus')).map(txt) : [], minus = d && !auto ? [].slice.call(d.querySelectorAll('.cfb__report li.is-minus')).map(txt) : [];
    var parts = d ? [].slice.call(d.querySelectorAll('.cfb__parts:not(.pd__pct) li')).map(function (li) { return [txt(li.querySelector('.cfb__bk')), parseFloat(txt(li.querySelector('.cfb__bv')).replace(/−/g, '-'))]; }).filter(function (p) { return p[0] && isFinite(p[1]); }) : [];
    var badges = pcBadges([row, d]);
    if (!badges.length) { var med = row.querySelector('.cfb__medals'), TT = { Platinum: 'p', Gold: 'g', Silver: 's', Bronze: 'b' };
      if (med) (med.getAttribute('title') || '').split('\n').forEach(function (l) { var m = l.match(/^(Platinum|Gold|Silver|Bronze) (.+?):/); if (m) badges.push([m[2], TT[m[1]]]); }); }
    var partsH = parts.length ? 130 + Math.ceil(Math.min(parts.length, 10) / 2) * 60 : 0;
    var repH = plus.length || minus.length ? 140 + Math.min(6, Math.max(plus.length, minus.length, 1)) * 70 : 0, bdgH = badges.length ? 200 : 0;
    // the layout as it stands: header lines, the sorted tile, the tiles (four across, as many rows as the room leaves)
    var y1 = y + (info.length ? 72 : 0), featH = feat ? 44 + 230 + 40 : 0;
    function hdrEnd(rs) {
      g.font = '40px ' + FONT; var n = 0; rs.forEach(function (r) { n += wrap(g, r, w - px).length; });
      return Math.max(y1 + Math.min(n, Math.max(0, Math.floor((top + (info.length ? 460 : 330) - y1) / 56))) * 56, top + 360) + 30;
    }
    function roomAt(rs, ls) { return bottom - hdrEnd(rs) - featH - partsH - repH - bdgH - (ls.length ? 60 + Math.min(ls.length, 3) * 64 : 0) - 44; }
    var cols = tiles.length <= 9 ? 3 : 4, gap = 24, tw = (w - (cols - 1) * gap) / cols, th = 200;
    var room = roomAt(roles, lines), maxRows = Math.max(1, Math.floor((room + 40) / (th + 24)));
    // fewer tiles than room: taller tiles and bigger type, so the card fills
    var nRows = Math.ceil(Math.min(tiles.length, maxRows * cols) / cols);
    if (nRows) th = Math.max(200, Math.min(nRows <= 2 ? 520 : nRows === 3 ? 420 : 340, Math.floor((room + 24) / nRows) - 24));
    // what the capped tiles leave empty takes stat cells: a line of text that reads as stats (season line, the dropdown's
    // season), the player's columns on the page's other tables, the FV outlook; the text they come from leaves the card
    var shown = {};
    heads.concat(['player', 'team', 'pos']).forEach(function (h) { shown[h.toLowerCase()] = 1; });
    var cands = [];
    roles.forEach(function (r, i) { var s = pcStatText(r, ''); if (s.group) { s.group.src = ['r', i, s.rest]; cands.push(s.group); } });
    lines.forEach(function (l, i) { var s = pcStatText(l[1], l[0]); if (s.group) { s.group.src = ['l', i, s.rest]; cands.push(s.group); } });
    cands.forEach(function (gp) { gp.items.forEach(function (it) { shown[it.h.toLowerCase()] = 1; }); });
    cands = cands.concat(pcXGroups(table, name, team, posC ? txt(posC) : '', shown).sort(function (a, b) { return b.pri - a.pri; }), [pcFvo(d && !auto ? d : null)].filter(Boolean));
    function used(gs) {   // roles and lines with the picked groups' text taken out
      var rs = roles.slice(), ls = lines.slice();
      gs.forEach(function (p) { var s = p.gp.src; if (!s) return; if (s[0] === 'r') rs[s[1]] = s[2]; else ls[s[1]] = s[2] ? [ls[s[1]][0], s[2]] : null; });
      return { rs: rs.filter(Boolean), ls: ls.filter(Boolean) };
    }
    var fillH = function (p) { return 44 + p.rows * (p.sh.ch + 16) + 20; };
    function pickFill(t) {   // the groups that fit under tiles t px tall, in order, each cut to the rows that fit
      var tu = nRows ? nRows * (t + 24) + 20 : -44, out = [];
      if (!cands.length) return out;
      var all = used(cands.map(function (gp) { return { gp: gp }; })), free = roomAt(all.rs, all.ls) - tu - 24;
      cands.forEach(function (gp) {
        var sh = pcGShape(gp), r = Math.min(sh.rows, Math.floor((free - 64 + 16) / (sh.ch + 16)));
        if (r >= 1) { var p = { gp: gp, sh: sh, rows: r }; out.push(p); free -= fillH(p); }
      });
      // a text group left out keeps its line on the card: take groups off the end until the rest fit again
      while (out.length) {
        var u = used(out), need = out.reduce(function (a, p) { return a + fillH(p); }, 0);
        if (roomAt(u.rs, u.ls) - tu - 24 >= need) break;
        out.pop();
      }
      return out;
    }
    var cnt = function (f) { return f.reduce(function (a, p) { return a + p.rows; }, 0); }, fill = pickFill(th);
    // one or two rows of tiles at full height step down (to 400, then 340) when that seats more stat cells
    if (nRows && nRows <= 2) [400, 340].forEach(function (t) { if (th > t) { var f4 = pickFill(t); if (cnt(f4) > cnt(fill)) { fill = f4; th = t; } } });
    if (fill.length) { var uu = used(fill); roles = uu.rs; lines = uu.ls; }
    if (info.length) {   // AGE 27.9  G 7  MP 250: label lilac, value white
      g.font = '44px ' + FONT; var ix0 = x + px;
      info.forEach(function (f) {
        var lw = g.measureText(f[0] + ' ').width, vw = g.measureText(f[1]).width; if (ix0 + lw + vw > x + w) return;
        g.fillStyle = C.lilac; g.fillText(f[0], ix0, y); g.fillStyle = C.white; g.fillText(f[1], ix0 + lw, y); ix0 += lw + vw + 56;
      });
      y += 72;
    }
    g.font = '40px ' + FONT; g.fillStyle = C.lilac;
    var rl = []; roles.forEach(function (r) { wrap(g, r, w - px).forEach(function (l) { rl.push(l); }); });
    rl.slice(0, Math.max(0, Math.floor((top + (info.length ? 460 : 330) - y) / 56))).forEach(function (l) { g.fillText(l, x + px, y); y += 56; });
    y = Math.max(y, top + 360) + 30;
    function rule(label) {
      g.font = '40px ' + FONT; g.fillStyle = C.lilac; g.fillText(label, x, y);
      var lw = g.measureText(label).width; g.fillStyle = C.dark; g.fillRect(x + lw + 24, y - 1, w - lw - 24, 3); y += 44;
    }
    // the sorted column: big value, place in the view, where it sits in the view's range
    if (feat) {
      rule('SORTED BY ' + capHead(feat.h));
      var fh = 230;
      g.fillStyle = C.face; g.fillRect(x, y, w, fh); bevel(g, x, y, w, fh, true, 3);
      g.strokeStyle = C.teal; g.lineWidth = 6; g.strokeRect(x + 3, y + 3, w - 6, fh - 6);
      g.font = '150px ' + FONT; g.fillStyle = feat.color || C.teal; g.fillText(feat.t, x + 40, y + fh / 2);
      var vx = x + 80 + g.measureText(feat.t).width;
      g.font = '64px ' + FONT; g.fillStyle = C.white; g.fillText('#' + (at + 1) + ' of ' + rows.length + ' in view', vx, y + 78);
      g.font = '36px ' + FONT; g.fillStyle = C.lilac;
      if (feat.sub) g.fillText(fit(g, feat.sub, x + w - vx - 40), vx, y + 140);
      if (feat.pct != null) pxBar(g, vx, y + 172, x + w - vx - 40, 28, feat.pct, feat.good != null && feat.good <= 20 ? C.down : C.teal);
      y += fh + 40;
    }
    var ts = th / 200;
    if (tiles.length) {
      rule(auto ? 'PERCENTILE IN VIEW' : 'NUMBERS');
      tiles.slice(0, maxRows * cols).forEach(function (t, k) {
        var tx = x + (k % cols) * (tw + gap), ty = y + Math.floor(k / cols) * (th + 24);
        var hot = t.good != null && t.good >= 80, cold = t.good != null && t.good <= 20, acc = hot ? C.teal : cold ? C.down : null;
        g.fillStyle = C.face; g.fillRect(tx, ty, tw, th); bevel(g, tx, ty, tw, th, true, 3);
        if (acc) { var u = 8; g.fillStyle = acc; g.fillRect(tx + tw - 5 * u, ty + u, 4 * u, u); g.fillRect(tx + tw - 2 * u, ty + u, u, 4 * u); g.fillRect(tx + tw - 3 * u, ty + 2 * u, u, u); }   // pixel corner: top or bottom fifth
        g.font = Math.round(34 * Math.min(ts, 1.3)) + 'px ' + FONT; g.fillStyle = acc || C.lilac; g.fillText(fit(g, capHead(t.h), tw - 96), tx + 24, ty + 40 * ts);
        var vsz = Math.round(72 * Math.min(ts, 1.6)); g.font = vsz + 'px ' + FONT;
        while (vsz > 40 && g.measureText(t.t).width > tw - 48) { vsz -= 4; g.font = vsz + 'px ' + FONT; }   // long values step down before they clip
        g.fillStyle = t.color || C.white; g.fillText(fit(g, t.t, tw - 48), tx + 24, ty + 102 * ts);
        g.font = Math.round(30 * Math.min(ts, 1.3)) + 'px ' + FONT; g.fillStyle = C.lilac;
        var foot = [t.sub, t.pct != null ? 'p' + t.pct : ''].filter(Boolean).join(' · ');
        if (foot) g.fillText(fit(g, foot, tw - 48), tx + 24, ty + 150 * ts);
        if (t.pct != null) { var bh = Math.round(14 * ts); pxBar(g, tx + 24, ty + th - 28 - bh, tw - 48, bh, t.pct, cold ? C.down : C.teal); }
      });
      y += Math.ceil(Math.min(tiles.length, maxRows * cols) / cols) * (th + 24) + 20;
    }
    if (lines.length) {
      lines.slice(0, 3).forEach(function (l) {
        g.font = '40px ' + FONT; g.fillStyle = C.lilac; var lw = g.measureText(l[0].toUpperCase() + '  ').width; g.fillText(l[0].toUpperCase(), x, y);
        g.fillStyle = C.white; g.fillText(fit(g, l[1], w - lw), x + lw, y); y += 64;
      });
      y += 20;
    }
    // the stat cells in the spare room: label, value, small print or pNN, a pixel bar where there is a percentile
    var fillEnd = bottom - partsH - repH - bdgH;
    fill.forEach(function (p) {
      var sh = p.sh, cw = (w - (sh.cols - 1) * 16) / sh.cols;
      if (y + 44 + sh.ch > fillEnd) return;
      rule(capHead(p.gp.title));
      p.gp.items.slice(0, p.rows * sh.cols).forEach(function (it, k) {
        var cx = x + (k % sh.cols) * (cw + 16), cy = y + Math.floor(k / sh.cols) * (sh.ch + 16);
        if (cy + sh.ch > fillEnd) return;
        var hot = it.good != null && it.good >= 80, cold = it.good != null && it.good <= 20, acc = hot ? C.teal : cold ? C.down : null;
        g.fillStyle = C.face; g.fillRect(cx, cy, cw, sh.ch); bevel(g, cx, cy, cw, sh.ch, true, 3);
        if (acc) { var u = 6; g.fillStyle = acc; g.fillRect(cx + cw - 5 * u, cy + u, 4 * u, u); g.fillRect(cx + cw - 2 * u, cy + u, u, 4 * u); g.fillRect(cx + cw - 3 * u, cy + 2 * u, u, u); }
        g.font = '30px ' + FONT; g.fillStyle = acc || C.lilac; g.fillText(fit(g, capHead(it.h), cw - 64), cx + 20, cy + 36);
        var vs = 60; g.font = vs + 'px ' + FONT;
        while (vs > 32 && g.measureText(it.t).width > cw - 40) { vs -= 4; g.font = vs + 'px ' + FONT; }
        g.fillStyle = it.color || C.white; g.fillText(fit(g, it.t, cw - 40), cx + 20, cy + 90);
        var foot = [it.sub, it.pct != null && p.gp.title !== 'FV outlook' ? 'p' + it.pct : ''].filter(Boolean).join(' · ');
        if (foot) { g.font = '26px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, foot, cw - 40), cx + 20, cy + 134); }
        if (it.pct != null) pxBar(g, cx + 20, cy + sh.ch - 30, cw - 40, 12, it.pct, cold ? C.down : C.teal);
      });
      y += p.rows * (sh.ch + 16) + 20;
    });
    // badges: the slot for the board's predictive badges (only badges that pass a held-out test are on a board)
    if (badges.length) { y += 10; rule('BADGES'); y += 6; y += badgeRows(g, badges, x, y, w); }
    if (repH) {
      y += 20; var half = (w - 60) / 2, lim = bottom - partsH - 20;
      [['+ strengths', plus, C.teal, x], ['− concerns', minus, C.down, x + half + 60]].forEach(function (L) {
        var ly = y; g.font = '56px ' + FONT; g.fillStyle = L[2]; g.fillText(L[0], L[3], ly); ly += 76; g.font = '40px ' + FONT;
        (L[1].length ? L[1] : ['none']).forEach(function (it) {
          var ls = wrap(g, it, half - 56); if (ly + ls.length * 54 > lim) return;
          g.fillStyle = L[2]; g.fillText(L[0][0], L[3] + 4, ly); g.fillStyle = C.lilac; ls.forEach(function (l) { g.fillText(l, L[3] + 56, ly); ly += 54; }); ly += 12;
        });
      });
    }
    // FV inputs: each driver's push on the grade, two columns of bars pinned to the bottom
    if (parts.length) {
      var ps = parts.slice(0, 10), by = bottom - partsH + 20, cw2 = (w - 80) / 2, mx = Math.max(1, Math.max.apply(null, ps.map(function (p) { return Math.abs(p[1]); })));
      g.fillStyle = C.dark; g.fillRect(x, by - 30, w, 3);
      g.font = '48px ' + FONT; g.fillStyle = C.lilac; g.fillText('FV INPUTS', x, by + 30);
      g.font = '36px ' + FONT;
      var perCol = Math.ceil(ps.length / 2);
      ps.forEach(function (p, i) {
        var cx = x + Math.floor(i / perCol) * (cw2 + 80), yy = by + 110 + (i % perCol) * 60, bx0 = cx + 470, bwid = cw2 - 470 - 130, mid = bx0 + bwid / 2, hw = bwid / 2;
        var v = p[1], bw = Math.min(hw, Math.abs(v) / mx * hw);
        g.fillStyle = C.lilac; g.fillText(fit(g, p[0], 450), cx, yy);
        g.fillStyle = C.well; g.fillRect(bx0, yy - 18, bwid, 36); g.fillStyle = C.dark; g.fillRect(mid - 1, yy - 24, 3, 48);
        g.fillStyle = v < 0 ? C.down : C.teal; g.fillRect(v < 0 ? mid - bw : mid + 2, yy - 14, bw, 28);
        var lab = (v > 0 ? '+' : '') + v.toFixed(2); g.fillStyle = C.lilac; g.fillText(lab, cx + cw2 - g.measureText(lab).width, yy);
      });
    }
    if (det.opened && det.close) det.close();
    return F.canvas;
  }
  // ---- a dropdown for every player table that has none (pro boards, mocks, backup watch, ARKLIST ...): the CFB layout
  // built from the row itself. Strengths and concerns are the columns where he sits in the top or bottom fifth of the
  // rows in view (direction-aware: lower is better for ranks, usage and age columns are not judged), the role line carries
  // his place in the view, the ranges a cell carries (80% range, raw value) and the FV chip's note, then the badges and a
  // percentile breakdown of every number. Template text only.
  var PD_NEUTRAL = /^(str|age|g|gp|mp|min|toi|snaps|plays|share|wt\. gp|ht|wt|ht \/ wt|class|yr|yrs|salary|contract|season|gap|xgap|starter|st .*|w-l|rec|range|tag|stage|last|form|roster|pick|rd|vs cons|nhl gp|peak|out|value|tm|xmv|sh|kp|g-xg)$/i;
  var PD_LOWER = /^(rank|cons|xslot|vrs|ga|gaa)$/i;
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
    if (/1nt$/.test(SITE)) return;
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
    if (/1nt$/.test(SITE)) return;
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
    if (/1nt$/.test(SITE)) return;
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
    var LG = { cfb: 'CFB', cbb: 'CBB', nfl: 'NFL', nba: 'NBA', nhl: 'NHL', soccer: 'soccer' };
    var F = await frame(2160, 2700, (LG[d.sport] || '') + ' :: ' + d.name, win.getAttribute('data-gfx-date'), SITE + '#ark-ranking');
    var g = F.g, x = F.x + 40, y = F.y + 70, w = F.w - 80, top = y, dash = '—';
    well(g, F.x, F.y, F.w, F.h);
    // the logo in a raised frame at the left (full colour, smoothed), then name, line, rating sentence; the rank plaque at the right
    var logo = await loadImg(d.logo), LS = 360, lx = x, ly = y - 60;
    g.fillStyle = C.face; g.fillRect(lx, ly, LS, LS); bevel(g, lx, ly, LS, LS, true, 6);
    g.fillStyle = C.dark; g.fillRect(lx + 12, ly + 12, LS - 24, LS - 24);
    if (logo) { var lr = Math.min(272 / logo.width, 272 / logo.height), lw = logo.width * lr, lh = logo.height * lr; drawLogo(g, logo, lx + (LS - lw) / 2, ly + (LS - lh) / 2, lw, lh); }
    else { g.font = '96px ' + FONT; g.fillStyle = C.lilac; g.textAlign = 'center'; g.fillText(String(d.short).slice(0, 4).toUpperCase(), lx + LS / 2, ly + LS / 2); g.textAlign = 'left'; }
    var tx = x + LS + 40, pw = 300, tw = w - LS - 40 - pw - 32;
    // rank plaque: ARK RANK over #n, teal, raised
    var py = ly;
    g.fillStyle = C.teal; g.fillRect(x + w - pw, py, pw, 220); bevel(g, x + w - pw, py, pw, 220, true, 6);
    g.fillStyle = C.dark; g.font = '36px ' + FONT; g.textAlign = 'center'; g.fillText('ARK RANK', x + w - pw / 2, py + 44);
    g.font = '112px ' + FONT; g.fillText('#' + d.rk, x + w - pw / 2, py + 118);
    g.font = '32px ' + FONT; g.fillText('of ' + d.N, x + w - pw / 2, py + 190); g.textAlign = 'left';
    g.font = '96px ' + FONT; g.fillStyle = C.white;
    var nl = wrap(g, d.name, tw); if (nl.length > 2) nl = [nl[0], fit(g, nl.slice(1).join(' '), tw)];
    nl.forEach(function (l, i) { g.fillText(fit(g, l, tw), tx, y + i * 110); });
    y += nl.length * 110;
    g.font = '48px ' + FONT; g.fillStyle = C.teal;
    wrap(g, d.head.join(' · '), tw).slice(0, 2).forEach(function (l) { g.fillText(l, tx, y); y += 64; });
    g.font = '40px ' + FONT; g.fillStyle = C.lilac; y += 8;
    wrap(g, d.rating + ' ' + d.unit + ' a game against ' + d.vs + '.', w - LS - 40).slice(0, 3).forEach(function (l) { g.fillText(l, tx, y); y += 54; });
    y = Math.max(y, ly + LS) + 44;
    // labelled bands of tiles, as on the player card
    function rule(label) {
      g.font = '40px ' + FONT; g.fillStyle = C.lilac; g.fillText(label, x, y);
      var lw = g.measureText(label).width; g.fillStyle = C.dark; g.fillRect(x + lw + 24, y - 1, w - lw - 24, 3);
      y += 52;
    }
    function band(label, tiles, cols, th) {
      rule(label);
      var gap = 24, tw2 = (w - (cols - 1) * gap) / cols;
      th = th || 200;
      tiles.forEach(function (t, i) {
        // label, value, note on fixed rows inside the tile, each clear of the next and of the bevel
        var bx = x + (i % cols) * (tw2 + gap), by = y + Math.floor(i / cols) * (th + gap), sub = th >= 190;
        g.fillStyle = C.face; g.fillRect(bx, by, tw2, th); bevel(g, bx, by, tw2, th, true, 3);
        g.font = '34px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, t[0].toUpperCase(), tw2 - 48), bx + 24, by + 44);
        g.font = (sub ? 72 : 64) + 'px ' + FONT; g.fillStyle = t[2] || C.white; g.fillText(fit(g, t[1], tw2 - 48), bx + 24, by + (sub ? 110 : th - 52));
        if (t[3] && sub) { g.font = '30px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, t[3], tw2 - 48), bx + 24, by + th - 36); }
      });
      var rows = Math.ceil(tiles.length / cols); y += rows * th + (rows - 1) * gap + 64;
    }
    var neg = /^[−-]/.test(d.rating), nlast = d.last ? d.last.split(' ').length : 0;
    band('ARK RANKING', [['rating', d.rating, neg ? C.down : C.teal, d.unit + ' vs average'],
                         ['80% range', d.rkLo ? '#' + d.rkLo + (d.rkHi !== d.rkLo ? '-' + d.rkHi : '') : dash, null, 'rank range'],
                         ['record', d.rec || dash, null, nlast ? 'last ' + nlast + ': ' + d.last : null]], 3);
    if (d.odds.length) { var oc = d.odds.length > 4 ? Math.ceil(d.odds.length / 2) : d.odds.length; band('SEASON ODDS', d.odds.slice(0, 8).map(function (o) { return [o[0], o[1]]; }), Math.max(3, Math.min(4, oc)), 150); }
    // what the rating is made of: each input's push, bars from the middle, pinned to the bottom
    var parts = d.parts.slice().sort(function (a, b) { return Math.abs(b[1]) - Math.abs(a[1]); }).slice(0, 8), prow = Math.ceil(parts.length / 2);
    var barsH = parts.length ? 100 + prow * 60 : 0, bottom = F.y + F.h - 40 - barsH;
    // the team badges' band is reserved before the lists fill, so key players and young talent never push it off
    var bdgs = (d.badges || []).filter(function (b) { return b && TIERS[b[1]]; }).slice(0, 4), bdgH = bdgs.length ? 176 : 0, lbot = bottom - bdgH;
    // next games beside key players
    var half = (w - 60) / 2, cy0 = y, ly2;
    function colHead(cx, label, sub) {
      g.font = '40px ' + FONT; g.fillStyle = C.lilac; g.fillText(label, cx, y);
      var lw = g.measureText(label).width; g.fillStyle = C.dark; g.fillRect(cx + lw + 24, y - 1, half - lw - 24, 3);
      if (sub) { g.font = '30px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, sub, half), cx, y + 46); }
    }
    var gy = y, py2 = y;
    if (d.next.length || d.last) {
      var pct = function (p) { return p == null ? dash : p < 0.005 ? '<1%' : p >= 0.995 ? '>99%' : Math.round(p * 100) + '%'; };
      colHead(x, 'NEXT GAMES', d.left ? d.left + ' left · ' + d.xw.toFixed(1) + ' expected ' + (d.draws ? 'points' : 'wins') : 'season complete');
      gy += 104;
      var logos = await Promise.all(d.next.map(function (n) { return loadImg(n.logo); }));
      d.next.forEach(function (n, i) {
        if (gy + 40 > lbot - 120 || ((d.yg || []).length && i >= 3)) return;
        g.font = '36px ' + FONT; g.fillStyle = C.lilac; g.fillText(n.day, x, gy);
        var ox = x + 180; g.fillText(n.at, ox, gy); ox += 64;
        if (logos[i]) { drawLogo(g, logos[i], ox, gy - 26, 52, 52); ox += 68; }
        var pv = pct(n.p); g.font = '44px ' + FONT; var pvw = g.measureText(pv).width;
        g.fillStyle = n.p == null ? C.lilac : n.p >= 0.5 ? C.teal : C.down; g.fillText(pv, x + half - pvw, gy);
        var rk = n.rk ? ' #' + n.rk : ''; g.font = '40px ' + FONT; g.fillStyle = C.white;
        var room = x + half - pvw - 24 - ox, nm = fit(g, n.n, room - (rk ? 90 : 0)); g.fillText(nm, ox, gy);
        if (rk) { var nw = g.measureText(nm).width; g.font = '30px ' + FONT; g.fillStyle = C.lilac; g.fillText(rk, ox + nw + 8, gy + 2); }
        gy += 66;
      });
      if (d.next.length) { g.font = '28px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, 'win chance from the game model', half), x, gy - 6); gy += 30; }
    }
    // a player list (key players, young talent): name, position, metric at the right, the note under it
    function plist(px, py, pwid, label, sub, list, metric) {
      var hh = half; half = pwid; y = py; colHead(px, label, sub); half = hh;
      py += 104;
      list.forEach(function (p) {
        if (py + 40 > lbot - 120) return;
        var val = metric === 'FV' ? String(p[2]) : (p[2] > 0 ? '+' : p[2] < 0 ? '−' : '') + Math.abs(+p[2]).toFixed(2);
        g.font = '44px ' + FONT; var vw = g.measureText(val).width; g.fillStyle = C.teal; g.fillText(val, px + pwid - vw, py);
        g.font = '30px ' + FONT; var pos = String(p[1] || ''), posw = pos ? g.measureText(pos).width + 16 : 0;
        g.font = '40px ' + FONT; g.fillStyle = C.white; var pn = fit(g, p[0], pwid - vw - 32 - posw); g.fillText(pn, px, py);
        var pnw = g.measureText(pn).width;
        if (pos) { g.font = '30px ' + FONT; g.fillStyle = C.lilac; g.fillText(pos, px + pnw + 16, py + 2); }
        if (p[3]) { g.font = '30px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, p[3], pwid), px, py + 40); py += 94; } else py += 68;
      });
      return py;
    }
    var two = d.next.length || d.last, yg = d.yg || [];
    if (d.pl.length) py2 = plist(two ? x + half + 60 : x, py2, two ? half : w, 'KEY PLAYERS', 'by ' + d.pm, d.pl, d.pm);
    // elite young talent: under the next games (or beside key players when there is no schedule)
    if (yg.length) {
      if (two) gy = plist(x, gy + 40, half, 'YOUNG TALENT', d.yd, yg, d.ym);
      else py2 = plist(x, py2 + 24, w, 'YOUNG TALENT', d.yd, yg, d.ym);
    }
    y = Math.max(gy, py2, cy0) + 40;
    // team badges (when the team file carries them: [[name, tier]]), before the unit line and strengths (both are
    // also in the dropdown; the badges take the room first)
    // team badges ([[name, tier, pct, line]]): medal, tier and percentile, name; four in a row in the reserved band
    if (bdgs.length) {
      y += 4; rule('BADGES'); y -= 10;
      var bw = w / 4, bu = 6;
      bdgs.forEach(function (b, i) {
        var bx = x + i * bw;
        medal(g, bx, y, b[1], bu);
        g.font = '28px ' + FONT; g.fillStyle = TIERS[b[1]][2];
        g.fillText(fit(g, TIERS[b[1]][0] + (b[2] != null ? ' · ' + b[2] + ' PCT' : ''), bw - 12 * bu - 28), bx + 12 * bu + 16, y + 26);
        g.font = '34px ' + FONT; g.fillStyle = C.white; g.fillText(fit(g, String(b[0]).toUpperCase(), bw - 12 * bu - 28), bx + 12 * bu + 16, y + 64);
      });
      y += 12 * bu + 50;
    }
    if (d.group && y + 60 < bottom) { g.fillStyle = C.dark; g.fillRect(x, y - 30, w, 3); g.font = '36px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, d.group, w), x, y + 16); y += 84; }
    // strengths and concerns, side by side, in the room left
    if ((d.plus.length || d.minus.length) && y + 130 < bottom) {
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
      var by = F.y + F.h - barsH - 10, cw2 = (w - 80) / 2, sum = d.parts.reduce(function (s_, p) { return s_ + p[1]; }, 0);
      g.fillStyle = C.dark; g.fillRect(x, by - 30, w, 3);
      g.font = '44px ' + FONT; g.fillStyle = C.lilac;
      g.fillText(fit(g, 'rating inputs: push on the rating, ' + d.unit + ' (sum ' + (sum > 0 ? '+' : sum < 0 ? '−' : '') + Math.abs(sum).toFixed(d.d) + ')', w), x, by + 30);
      g.font = '36px ' + FONT;
      parts.forEach(function (p, i) {
        var cx = x + Math.floor(i / prow) * (cw2 + 80), yy = by + 100 + (i % prow) * 60, bx0 = cx + 300, bwid = cw2 - 300 - 130, mid = bx0 + bwid / 2, hb = bwid / 2;
        var v = p[1], bw = Math.min(hb, Math.abs(v) / d.scale * hb);
        g.fillStyle = C.lilac; g.fillText(fit(g, p[0], 280), cx, yy);
        g.fillStyle = C.well; g.fillRect(bx0, yy - 18, bwid, 36);
        g.fillStyle = C.dark; g.fillRect(mid - 1, yy - 24, 3, 48);
        g.fillStyle = v < 0 ? C.down : C.teal; g.fillRect(v < 0 ? mid - bw : mid + 2, yy - 14, bw, 28);
        var lab = (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(d.d); g.fillStyle = C.lilac; g.fillText(lab, cx + cw2 - g.measureText(lab).width, yy);
      });
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
    var heads = [].slice.call(tables[0].tHead.rows[0].cells).map(txt);
    var nRows = tables.reduce(function (a, t) { return a + t.tBodies[0].rows.length + 1; }, 0);
    var rowH = Math.min(78, (F.h - 24 - 24 * (tables.length - 1)) / nRows), size = rowH >= 64 ? 32 : 24;
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
    var y = F.y + 12;
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
    // header: the two teams
    var hy = y + 120, half = (w - 200) / 2;
    var LS = 240, logos = await Promise.all([d.us, d.them].map(function (t) { return t.logo ? loadImg(t.logo) : null; }));
    for (var k = 0; k < 2; k++) teamLogo(g, logos[k], k ? x + w - 60 - LS : x + 60, hy - 60, LS);
    [[d.us, 'left'], [d.them, 'right']].forEach(function (t, k) {
      var tx = k ? x + w - 60 - (logos[k] ? LS + 36 : 0) : x + 60 + (logos[k] ? LS + 36 : 0), al = k ? 'right' : 'left';
      var nw = half - 90 - (logos[k] ? LS + 36 : 0), fs = 120, tn = (t[0].ark ? t[0].ark + ' ' : '') + t[0].name;   // a long name steps the size down before it's cut
      g.textAlign = al; g.font = fs + 'px ' + FONT; while (fs > 56 && g.measureText(tn).width > nw) { fs -= 8; g.font = fs + 'px ' + FONT; }
      g.fillStyle = C.white; g.fillText(fit(g, tn, nw), tx, hy);
      g.font = '44px ' + FONT; g.fillStyle = C.teal; g.fillText([t[0].std ? 'STANDINGS ' + t[0].std : '', t[0].rec].filter(Boolean).join(' · '), tx, hy + 110);
      if (t[0].talent != null) {   // team talent: the five's mean, drawn as stars (half steps)
        var st = Math.round(t[0].talent * 2) / 2, sw = 5 * (40 + 6) - 6, sx = k ? tx - sw : tx;
        drawStars(g, sx, hy + 180, st, 40);
        g.font = '36px ' + FONT; g.fillStyle = C.lilac; var lab = t[0].talent.toFixed(2); g.fillText(lab, k ? sx - 16 : sx + sw + 16, hy + 182);
      }
    });
    g.textAlign = 'center'; g.font = '96px ' + FONT; g.fillStyle = C.lilac; g.fillText('VS', x + w / 2, hy);
    g.font = '40px ' + FONT; g.fillText(d.when, x + w / 2, hy + 110); g.fillText(d.event, x + w / 2, hy + 170);
    g.textAlign = 'left';
    // prediction band
    var by = hy + 290, bh = 90, bx = x + 60, bw = w - 120;
    g.fillStyle = C.down; g.fillRect(bx, by, bw, bh); g.fillStyle = C.teal; g.fillRect(bx, by, bw * d.win / 100, bh);
    g.font = '52px ' + FONT; g.fillStyle = C.dark; g.fillText('1NT ' + d.win + '%', bx + 24, by + bh / 2);
    var r = (100 - d.win) + '% ' + d.opp; g.fillText(r, bx + bw - 24 - g.measureText(r).width, by + bh / 2);
    var ty = by + bh + 120, tw = (bw - 48) / 3, tiles = [['SPREAD', d.line], ['PROJECTED', d.score], ['FORMAT', d.bo]];
    tiles.forEach(function (t, i) {
      var tx = bx + i * (tw + 24); g.fillStyle = C.face; g.fillRect(tx, ty - 60, tw, 170); bevel(g, tx, ty - 60, tw, 170, true, 3);
      g.font = '36px ' + FONT; g.fillStyle = C.lilac; g.fillText(t[0], tx + 24, ty - 10);
      var tf = 72; g.font = tf + 'px ' + FONT; while (tf > 44 && g.measureText(t[1]).width > tw - 48) { tf -= 4; g.font = tf + 'px ' + FONT; }
      g.fillStyle = C.white; g.fillText(fit(g, t[1], tw - 48), tx + 24, ty + 62);
    });
    // lineups
    var ly = ty + 220, nL = (d.five || []).length + (d.theirFive || []).length, room = (F.y + F.h - 200) - ly - 2 * 160 - (d.lineupNote ? 30 : 0);
    var RH = Math.max(88, Math.min(128, Math.floor(room / Math.max(1, nL)))), RS = Math.min(60, Math.round(RH * 0.59));
    for (var k = 0; k < 2; k++) {
      var L = k ? d.theirFive : d.five, label = (k ? d.opp : '1NT').toUpperCase() + ' · PROJECTED FIVE';
      g.font = '48px ' + FONT; g.fillStyle = k ? C.down : C.teal; g.fillText(label, bx, ly);
      g.font = '32px ' + FONT; g.fillStyle = C.lilac; g.fillText('ROLE', bx + 12 + (bw - 24) * 0.5, ly); g.fillText(L.some(function (q) { return q.rwa != null; }) ? 'TALENT · RWA · ARK' : 'TALENT · FORM ARK', bx + 12 + (bw - 24) * 0.74, ly);
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
      return h === em ? [[h, 1, '']] : [[h, 0.5, 'HABIT'], [em, 0.5, 'EDGE']];
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
      g.font = '76px ' + FONT; g.fillStyle = k ? C.down : C.teal; var nm = fit(g, (t.ark ? t.ark + ' ' : '') + t.name, w / 2 - LS - 160), nx0 = lx, sw0 = 0; g.fillText(nm, lx, y - 20 + LS / 2 - 18);
      if (t.std || t.rec) { g.font = '36px ' + FONT; g.fillStyle = C.lilac; var sl = [t.std ? 'STANDINGS ' + t.std : '', t.rec].filter(Boolean).join(' · '); g.fillText(sl, nx0, y - 20 + LS / 2 + 44); sw0 = g.measureText(sl).width; g.font = '76px ' + FONT; }
      lx += Math.max(g.measureText(nm).width, sw0 || 0) + 44;
      if (!k) { g.fillStyle = C.lilac; g.font = '52px ' + FONT; g.fillText('VS', lx, y - 20 + LS / 2); lx += g.measureText('VS').width + 44; }
    }
    y += LS + 30;
    var trees = [vetoTree(d, true), vetoTree(d, false)], bo = trees[0].bo;
    g.font = '48px ' + FONT; g.fillStyle = C.lilac;
    g.fillText(fit(g, 'BO' + bo + ' · 1NT ' + d.win + '% · ' + d.when, w), x, y); y += 70;
    var rows = trees.map(function (T) { return treeRows(T.root, 0); });
    // expected map (habit line, 1NT bans first) and its knife side, at the bottom
    var expLeaf = null;   // the habit line's decider, 1NT banning first (set while drawing)
    var BOXH = 300, boxY = bottom - BOXH, avail = boxY - 40 - y;
    var nrows = rows[0].length + rows[1].length, rh = Math.max(56, Math.min(100, Math.floor((avail - 2 * 150) / nrows))), fs = Math.min(52, Math.round(rh * 0.56));
    var ind = 64, cTag = x + w * 0.37, cRep = x + w * 0.47, cDec = x + w * 0.68;
    rows.forEach(function (R, ti) {
      g.font = '48px ' + FONT; g.fillStyle = C.white; g.fillText((ti ? d.opp.toUpperCase() : '1NT') + ' BANS FIRST', x, y + 24);
      g.font = '36px ' + FONT; g.fillStyle = C.lilac; g.textAlign = 'right';
      g.fillText('EXP. ' + (bo === 3 ? 'SERIES ' : 'MAP ') + Math.round(trees[ti].ev * 100) + '%', x + w, y + 24); g.textAlign = 'left';
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
    // the expected map box
    if (expLeaf) {
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
  async function buildRQ(win, btn) {
    var d; try { d = JSON.parse(btn.getAttribute('data-gfx-rq') || '{}'); } catch (e) { return null; }
    if (!d.q || !d.a) return null;
    var bars = (d.bars || []).map(function (b) { return Array.isArray(b) ? b : b && [b.l, b.v]; }).filter(function (b) { return b && b.length >= 2 && isFinite(+b[1]); }).slice(0, 8);
    var F = await frame(2400, 1350, 'ARKBOARD RESEARCH' + (d.sport ? ' :: ' + String(d.sport).toUpperCase() : ''), d.date || '',
      'arkndjl.net/reference' + (d.id ? '#rq-' + d.id : ''));
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
  // a #rq-<id> link: open the tabs around that question, then scroll to it
  function rqFromHash() {
    var h = decodeURIComponent(location.hash.slice(1)); if (!/^rq-/.test(h)) return;
    var el = document.getElementById(h); if (!el) return;
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

  document.addEventListener('click', async function (e) {
    var btn = e.target.closest('[data-gfx]'); if (!btn) return;
    var win = btn.closest('.win'); if (!win) return;
    btn.disabled = true; var label = btn.textContent; btn.textContent = '…';
    try {
      var mode = btn.getAttribute('data-gfx-mode');
      var canvas = mode === 'pcard' ? await buildPCard(win, btn.closest('tr[class*="__detail"]').previousElementSibling) : mode === 'card' ? await buildCard(win, btn) : mode === 'team' ? await buildTeamCard(win, btn) : mode === 'builder' ? await buildBuilder(win, btn) : mode === 'cbbplan' ? await buildCbbPlan(win, btn) : mode === 'coach' ? await buildCoach(win, btn) : mode === 'games' ? await buildGames(win, btn) : mode === 'game' ? await buildGame(win, btn) : mode === 'method' ? await buildMethod(win, btn) : mode === 'rank' ? await buildRank(win, btn) : mode === 'rq' ? await buildRQ(win, btn)
        : mode === 'esea-box' ? await buildEseaBox(win, btn) : mode === 'esea-season' ? await buildEseaSeason(win, btn)
        : mode === 'esea-fan' ? await buildFan(win, btn) : mode === 'esea-team' ? await buildTeam(win, btn) : await build(win, btn);
      if (canvas) {
        var pre = SITE === 'arkndjl.net/1nt' ? '1nt-' : 'arkboard-';
        if (/^esea-/.test(mode || '')) { preview(canvas, pre + (btn.getAttribute('data-gfx-title') || mode).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 60)); return; }
        if (mode === 'rq') { preview(canvas, 'arkboard-research-' + ((JSON.parse(btn.getAttribute('data-gfx-rq') || '{}').id) || 'card').toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 60)); return; }
        var name = mode === 'rank' ? (JSON.parse(win.getAttribute('data-gfx-rank') || '{}').name || 'arkboard-ark-top-25') : mode === 'cbbplan' ? 'arkboard-cbb-plan-' + (((window.__arkCbbBuilder || {}).current || {}).t || 'team').toLowerCase().replace(/[^a-z0-9]+/g, '-') : mode === 'builder' ? 'arkboard-plan-' + ((window.__arkBuilder || {}).current || {}).team.toLowerCase().replace(/[^a-z0-9]+/g, '-') : mode === 'coach' ? 'arkboard-coach-' + ((window.__arkCoaches || [])[+btn.getAttribute('data-gfx-i')] || {}).name.toLowerCase().replace(/[^a-z0-9]+/g, '-') : mode === 'pcard' ? 'arkboard-' + ((btn.closest('tr[class*="__detail"]').querySelector('.cfb__dhead b, b') || {}).textContent || 'player').toLowerCase().replace(/[^a-z0-9]+/g, '-') : mode === 'team' ? 'arkboard-team-' + (btn.getAttribute('data-gfx-name') || 'team').toLowerCase().replace(/[^a-z0-9]+/g, '-') : mode === 'card' || mode === 'game' || mode === 'method' ? 'arkboard-' + (btn.getAttribute('data-gfx-name') || 'player').toLowerCase().replace(/[^a-z0-9]+/g, '-') : pre + (btn.hasAttribute('data-gfx-top') ? (rowsWanted(win, btn) === ROWS_MAX && (btn.parentNode.querySelector('.gfx-rows select') || {}).value === 'all' ? 'all-' : 'top-' + rowsWanted(win, btn) + '-') : '') + txt(win.querySelector('.win__title-text')).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 60);
        preview(canvas, name);
      }
    } catch (err) {
      console.error('gfx', mode, err); btn.disabled = false; btn.textContent = 'GFX failed'; setTimeout(function () { btn.textContent = label; }, 2500); return;
    } finally { if (btn.textContent === '…') { btn.disabled = false; btn.textContent = label; } }
  });
})();
