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
    [/arkboard\/predictions/, 'picks'], [/arkboard\/arklist/, 'arklist'], [/./, 'arkboard']].filter(function (x) { return x[0].test(location.pathname); })[0][1]);
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
  function capHead(h) { return /^x[A-Z]/.test(h) ? h : h.toUpperCase(); }   // xNIL keeps its x
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
  var ROWS_DEFAULT = 30, ROWS_OPTS = [10, 15, 20, 25, 30, 40, 50, 60];
  function rowsWanted(win, btn) {
    var sel = btn.parentNode && btn.parentNode.querySelector('.gfx-rows select');
    if (btn.hasAttribute('data-gfx-all')) return Infinity;   // every row (the week's picks)
    return +(sel && sel.value) || ROWS_DEFAULT;
  }
  function filterSummary(win) {
    var bits = [], bar = win.querySelector('form');
    if (bar) {
      var chip = bar.querySelector('.cfb__chip.is-on[data-pos]'); if (chip && chip.dataset.pos) bits.push(chip.dataset.pos);
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
    var all = [].slice.call(table.tBodies[0].rows).filter(function (r) { return !r.hidden && getComputedStyle(r).display !== 'none' && !r.classList.contains('cfb__detail') && r.cells.length > 2; });
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
        var c = r.cells[i], chip = c && c.querySelector('.fv-chip'), img = c && c.querySelector('img.cfb__logo, img:not(.pxframe img)');
        // text only: the board's marks (ARKLIST star, riser arrow, injury and RB role tags, photos) stay off
        var cc = c && c.cloneNode(true); if (cc) cc.querySelectorAll('.gfx-off, .cfb__star, .cfb__carried, .cfb__warin, .cfb__riser, .cfb__injchip, .cfb__rbrole, .cfb__medals, .cfb__upchip, .cfb__movechip, .cfb__multichip, .cfb__valuechip, .cfb__reachchip, .cfb__divtag, .pxframe, .cfbst__more, .nflwar__col, .nflwar__tm, .nflwar__rook').forEach(function (e) { e.remove(); });
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
        var col = c && (c.querySelector('.cfb__up, .cfb__down') || (c.classList.contains('cfb__up') || c.classList.contains('cfb__down') ? c : null));
        if (col && !ark) cell.color = col.classList.contains('cfb__up') ? C.teal : C.down;
        return cell;
      }));
    }));
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
    var cnt = win.querySelector('[data-cfb-count], [data-cbb-count], [data-tf-count]'), total = cnt ? (/([\d,]+)\s*(?:of\s*([\d,]+))?/.exec(txt(cnt)) || []) : [];
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
        cdata.forEach(function (row) { var c = row[k]; m = Math.max(m, g.measureText(c.t).width + (c.img ? sz * 0.95 + 10 : 0) + (c.chip ? 24 : 0) + tagsW(c, sz)); g.font = sz + 'px ' + FONT; });
        return m + sz * 0.7;
      });
    }
    // largest crisp size that fits the row height and width; if even 24 px doesn't fit, drop the rightmost column
    var size, colW;
    // 48, 40 or 32 px; when none fits the width, the rightmost column goes; 24 px only as a last resort
    for (;;) {
      var ok = false;
      for (var sizes = [48, 40, 32], si = 0; si < sizes.length; si++) {
        size = sizes[si]; if (rowH < size * 1.35) continue;
        colW = widths(size); if (sum(colW) <= gw) { ok = true; break; }
      }
      if (ok) break;
      if (cols.length <= 4) { size = rowH >= 32 * 1.35 && sum(widths(32)) <= gw ? 32 : 24; colW = widths(size); break; }
      cols.pop(); cdata.forEach(function (r) { r.pop(); });
    }
    var spare = gw - sum(colW);
    if (spare > 0) { var nameK = cols.findIndex(function (ci) { return /player|team|coach|matchup/i.test(heads[ci]); }); if (nameK < 0) nameK = 1; colW[Math.min(nameK, colW.length - 1)] += spare; }
    g.font = size + 'px ' + FONT;
    for (var gi = 0; gi < groups; gi++) {
      var x0 = ix + PADI + gi * (gw + 40), y0 = iy + PADI;
      g.fillStyle = C.face; g.fillRect(x0, y0, gw, rowH - 6); bevel(g, x0, y0, gw, rowH - 6, true, 3);
      var cx = x0;
      g.font = Math.max(24, size - 8) + 'px ' + FONT;
      cols.forEach(function (ci, k) { g.fillStyle = C.lilac; g.fillText(capHead(heads[ci]), cx + size * 0.45, y0 + (rowH - 6) / 2); cx += colW[k]; });
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
            g.fillStyle = c.color || (k === 0 ? C.lilac : k === 1 ? C.white : C.teal);
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
      var opts = ROWS_OPTS.indexOf(def) < 0 ? ROWS_OPTS.concat([def]).sort(function (a, b) { return a - b; }) : ROWS_OPTS;
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
    g.fillText(fit(g, [r.pos + (r.spot ? ' · ' + r.spot : ''), r.team, r.conf, r.cls].filter(Boolean).join(' · '), w - px), x + px, y);
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
    var parts = r.parts || [], labels = ['talent', 'production', 'age', 'breakout', 'stats', 'pedigree', 'schedule+team', 'frame'];
    // two columns of four bars
    var barsH = parts.length ? 110 + 4 * 60 : 0, bottom = F.y + F.h - 40 - barsH, half2 = (w - 60) / 2;
    list('+ strengths', rep.plus, C.teal, x, half2, bottom);
    list('− concerns', rep.minus, C.down, x + half2 + 60, half2, bottom);
    if (parts.length) {
      var by = F.y + F.h - barsH - 10, cw2 = (w - 80) / 2;
      g.fillStyle = C.dark; g.fillRect(x, by - 30, w, 3);
      g.font = '48px ' + FONT; g.fillStyle = C.lilac; g.fillText('grade components: weighted pull on composite', x, by + 30);
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
    var bh = 96, pd = d.pD || 0, pa = d.pA != null ? d.pA : 1 - d.p;
    g.font = '40px ' + FONT; g.fillStyle = C.lilac; g.fillText(pd ? 'WIN / DRAW / WIN' : 'WIN PROBABILITY', x, y + 8);
    y += 44;
    g.fillStyle = C.dark; g.fillRect(x, y, w, bh);
    g.fillStyle = C.lilac; g.fillRect(x, y, w * pa, bh);
    if (pd) { g.fillStyle = C.title; g.fillRect(x + w * pa, y, w * pd, bh); }
    g.fillStyle = C.teal; g.fillRect(x + w * (pa + pd), y, w * d.p, bh);
    g.font = '52px ' + FONT; g.fillStyle = C.dark;
    var la = d.a.n + ' ' + Math.round(pa * 100) + '%', lh = Math.round(d.p * 100) + '% ' + d.h.n;
    if (pa > 0.12) g.fillText(fit(g, la, w * pa - 40), x + 20, y + bh / 2);
    if (d.p > 0.12) { var lt = fit(g, lh, w * d.p - 40); g.fillText(lt, x + w - 20 - g.measureText(lt).width, y + bh / 2); }
    if (pd > 0.1) { g.fillStyle = C.white; var ld = fit(g, 'draw ' + Math.round(pd * 100) + '%', w * pd - 30); g.fillText(ld, x + w * pa + (w * pd - g.measureText(ld).width) / 2, y + bh / 2); }
    y += bh + 40;
    // the pick tag (upset or favorite), when the game is one
    var tagH = d.pick ? 120 : 0, bottom = F.y + F.h - (tagH ? tagH + gap : 0);
    // tiles, two to a row, filling what's left
    var tiles = d.tiles || [], rowsN = Math.ceil(tiles.length / 2) || 1, tw = (w - gap) / 2, tH = Math.min(380, (bottom - y - (rowsN - 1) * gap) / rowsN);
    y += (bottom - y - rowsN * tH - (rowsN - 1) * gap) / 2;   // spare height splits above and below the tiles
    tiles.forEach(function (t, i) {
      var tx = x + (i % 2) * (tw + gap), ty = y + Math.floor(i / 2) * (tH + gap);
      var tw2 = tiles.length % 2 && i === tiles.length - 1 ? w : tw;   // an odd last tile spans the row
      well(g, tx, ty, tw2, tH);
      g.font = '40px ' + FONT; g.fillStyle = C.lilac; g.fillText(t.l, tx + pad, ty + tH * 0.22);
      var vs = 68; do { g.font = vs + 'px ' + FONT; } while (g.measureText(t.v).width > tw2 - 2 * pad && (vs -= 4) >= 40);   // long values step down before they clip
      g.fillStyle = C.white; g.fillText(fit(g, t.v, tw2 - 2 * pad), tx + pad, ty + tH * 0.52);
      g.font = '44px ' + FONT; g.fillStyle = C.teal; g.fillText(fit(g, t.s || '', tw2 - 2 * pad), tx + pad, ty + tH * 0.8);
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
    if (p.form != null) { g.font = Math.round(size * 0.62) + 'px ' + FONT; g.fillStyle = p.form >= 1 ? C.teal : C.down; g.fillText(p.form.toFixed(2), cx, cy); }
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
      var nw = half - 130 - (logos[k] ? LS + 36 : 0), fs = 120;   // a long name steps the size down before it's cut
      g.textAlign = al; g.font = fs + 'px ' + FONT; while (fs > 72 && g.measureText(t[0].name).width > nw) { fs -= 8; g.font = fs + 'px ' + FONT; }
      g.fillStyle = C.white; g.fillText(fit(g, t[0].name, nw), tx, hy);
      g.font = '52px ' + FONT; g.fillStyle = C.teal; g.fillText((t[0].rank || '') + (t[0].rec ? ' · ' + t[0].rec : ''), tx, hy + 110);
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
      g.font = '72px ' + FONT; g.fillStyle = C.white; g.fillText(fit(g, t[1], tw - 48), tx + 24, ty + 62);
    });
    // lineups
    var ly = ty + 220;
    for (var k = 0; k < 2; k++) {
      var L = k ? d.theirFive : d.five, label = (k ? d.opp : '1NT').toUpperCase() + ' · PROJECTED FIVE';
      g.font = '48px ' + FONT; g.fillStyle = k ? C.down : C.teal; g.fillText(label, bx, ly);
      g.font = '32px ' + FONT; g.fillStyle = C.lilac; g.fillText('ROLE', bx + 12 + (bw - 24) * 0.5, ly); g.fillText('TALENT · FORM ARK', bx + 12 + (bw - 24) * 0.74, ly);
      ly += 90;
      for (var i = 0; i < L.length; i++) { if (i % 2) { g.fillStyle = 'rgba(36,26,58,0.35)'; g.fillRect(bx, ly - 42, bw, 84); } await teamRow(g, bx + 12, ly, bw - 24, L[i], 52); ly += 88; }
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
  async function buildTeam(win, btn) {
    var d = pvData(btn); if (!d) return null;
    var F = await frame(2160, 2700, '1NT vs ' + d.opp + ' :: game plan', btn.getAttribute('data-gfx-date'));
    var g = F.g, x = F.x + 48, y = F.y + 70, w = F.w - 96;
    well(g, F.x, F.y, F.w, F.h);
    if (d.us.logo || d.them.logo) {   // the two teams, logo + name
      var LS = 150, ly = y - 30, lx = x;
      for (var k = 0; k < 2; k++) {
        var t = k ? d.them : d.us;
        if (teamLogo(g, t.logo ? await loadImg(t.logo) : null, lx, ly, LS)) lx += LS + 28;
        g.font = '80px ' + FONT; g.fillStyle = k ? C.down : C.teal; var nm = fit(g, t.name, w / 2 - LS - 160); g.fillText(nm, lx, ly + LS / 2); lx += g.measureText(nm).width + 50;
        if (!k) { g.fillStyle = C.lilac; g.font = '56px ' + FONT; g.fillText('VS', lx, ly + LS / 2); lx += g.measureText('VS').width + 50; }
      }
      y += LS + 40;
    }
    g.font = '64px ' + FONT; g.fillStyle = C.white; g.fillText(fit(g, d.line + ' · ' + d.win + '% · proj. ' + d.score + ' · talent ' + d.talentUs + ' v ' + d.talentThem + ' stars', w), x, y); y += 100;
    // veto, both orders
    var cw = (w - 40) / 2;
    d.vetoes.forEach(function (v, k) {
      var vx = x + k * (cw + 40), vy = y;
      g.font = '40px ' + FONT; g.fillStyle = C.lilac; g.fillText(('BO1 VETO · ' + (v.weStart ? '1NT' : d.opp) + ' BANS FIRST').toUpperCase(), vx, vy); vy += 64;
      v.bans.forEach(function (b, i) {
        g.font = '40px ' + FONT; g.fillStyle = b.by === 'us' ? C.teal : C.down; g.fillText((i + 1) + '. ' + (b.by === 'us' ? '1NT' : d.opp) + ' ban', vx, vy);
        g.fillStyle = C.white; g.fillText(b.map, vx + cw * 0.6, vy); vy += 56;
      });
      g.fillStyle = C.white; g.font = '44px ' + FONT; g.fillText('7. decider ' + v.decider + ' (' + (v.edge >= 0 ? '+' : '') + v.edge + ')', vx, vy);
    });
    y += 64 + 56 * 6 + 90;
    // map edges
    g.font = '40px ' + FONT; g.fillStyle = C.lilac; g.fillText('MAP · 1NT · ' + d.opp.toUpperCase() + ' · EDGE · 1NT WIN', x, y); y += 60;
    d.maps.forEach(function (m, i) {
      if (i % 2) { g.fillStyle = 'rgba(36,26,58,0.35)'; g.fillRect(x - 12, y - 30, w + 24, 60); }
      g.font = '40px ' + FONT; g.fillStyle = m.map === d.vetoes[0].decider ? C.white : C.lilac; g.fillText(m.map, x, y);
      g.fillStyle = C.teal; g.fillText((m.us.wr != null ? m.us.wr + '%' : '—') + ' (' + m.us.n + ')', x + w * 0.22, y);
      g.fillStyle = C.down; g.fillText((m.them.wr != null ? m.them.wr + '%' : '—') + ' (' + m.them.n + ')', x + w * 0.44, y);
      g.fillStyle = m.edge >= 0 ? C.teal : C.down; g.fillText((m.edge >= 0 ? '+' : '') + m.edge.toFixed(1), x + w * 0.66, y);
      g.fillStyle = C.white; g.fillText(m.p + '%', x + w * 0.84, y); y += 60;
    });
    y += 50;
    // matchups
    g.font = '40px ' + FONT; g.fillStyle = C.lilac; g.fillText('MATCHUPS · TALENT (STARS) · EDGE', x, y); y += 66;
    for (var i = 0; i < (d.matchups || []).length; i++) {
      var m = d.matchups[i];
      g.font = '40px ' + FONT; g.fillStyle = C.lilac; g.fillText(fit(g, (m.us && m.us.role) || '', w * 0.2), x, y);
      g.fillStyle = C.teal; g.fillText(fit(g, m.us ? m.us.name + (m.us.sub ? ' (sub)' : '') + ' ' + (m.us.stars ?? '—') : '—', w * 0.3), x + w * 0.2, y);
      g.fillStyle = C.down; g.fillText(fit(g, m.them ? 'v ' + m.them.name + ' ' + (m.them.stars ?? '—') : '', w * 0.32), x + w * 0.52, y);
      if (m.edge != null) { g.fillStyle = m.edge >= 0 ? C.teal : C.down; g.fillText((m.edge >= 0 ? '+' : '') + m.edge.toFixed(2), x + w * 0.88, y); }
      if (m.stat && m.statUs != null && m.statThem != null) { y += 46; g.font = '32px ' + FONT; g.fillStyle = C.lilac; g.fillText(m.stat + ' ' + m.statUs + ' v ' + m.statThem, x + w * 0.2, y); g.fillStyle = m.statEdge >= 0 ? C.teal : C.down; g.fillText((m.statEdge >= 0 ? '+' : '') + m.statEdge, x + w * 0.88, y); }
      y += 60;
    }
    y += 40;
    // game plan
    g.font = '40px ' + FONT; g.fillStyle = C.lilac; g.fillText('GAME PLAN', x, y); y += 64;
    g.font = '38px ' + FONT;
    (d.plan || []).forEach(function (p) {
      wrap(g, p, w - 50).forEach(function (l, j) { if (y > F.y + F.h - 40) return; g.fillStyle = j ? C.lilac : C.white; if (!j) g.fillText('›', x, y); g.fillText(l, x + 40, y); y += 52; });
      y += 10;
    });
    return F.canvas;
  }

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
      var canvas = mode === 'card' ? await buildCard(win, btn) : mode === 'builder' ? await buildBuilder(win, btn) : mode === 'coach' ? await buildCoach(win, btn) : mode === 'games' ? await buildGames(win, btn) : mode === 'game' ? await buildGame(win, btn) : mode === 'method' ? await buildMethod(win, btn) : mode === 'rank' ? await buildRank(win, btn)
        : mode === 'esea-box' ? await buildEseaBox(win, btn) : mode === 'esea-season' ? await buildEseaSeason(win, btn)
        : mode === 'esea-fan' ? await buildFan(win, btn) : mode === 'esea-team' ? await buildTeam(win, btn) : await build(win, btn);
      if (canvas) {
        var pre = SITE === 'arkndjl.net/1nt' ? '1nt-' : 'arkboard-';
        if (/^esea-/.test(mode || '')) { preview(canvas, pre + (btn.getAttribute('data-gfx-title') || mode).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 60)); return; }
        var name = mode === 'rank' ? (JSON.parse(win.getAttribute('data-gfx-rank') || '{}').name || 'arkboard-ark-top-25') : mode === 'builder' ? 'arkboard-plan-' + ((window.__arkBuilder || {}).current || {}).team.toLowerCase().replace(/[^a-z0-9]+/g, '-') : mode === 'coach' ? 'arkboard-coach-' + ((window.__arkCoaches || [])[+btn.getAttribute('data-gfx-i')] || {}).name.toLowerCase().replace(/[^a-z0-9]+/g, '-') : mode === 'card' || mode === 'game' || mode === 'method' ? 'arkboard-' + (btn.getAttribute('data-gfx-name') || 'player').toLowerCase().replace(/[^a-z0-9]+/g, '-') : pre + (btn.hasAttribute('data-gfx-top') ? 'top-' + rowsWanted(win, btn) + '-' : '') + txt(win.querySelector('.win__title-text')).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 60);
        preview(canvas, name);
      }
    } finally { btn.disabled = false; btn.textContent = label; }
  });
})();
