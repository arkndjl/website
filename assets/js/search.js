// Site search (search.exe): the header bar on every page (partials/search-bar.html) and the results page
// (/search/, shortcodes/search.html). The index loads on first use: /search/index.json (pages, tabs, Process,
// ARKLIBRARY, ST. CLAIRE, 1NT, LAURSEN_111, articles; written by Hugo each build) and /data/search-players.json
// (every ARKBOARD player and team; scripts/search_index.py). Matching: exact > prefix > word prefix > substring >
// every word anywhere > one-typo words; ties go to the row's standing on its own board (w, 0-99).
(function () {
  if (window.__arkSearch) return;
  var SITE = '{{ "search/index.json" | relURL }}';   // no build stamp: the file is served max-age=0 + ETag, and a stamp here renamed this script on every build
  var PLAY = '{{ "data/search-players.json" | relURL }}?v={{ with os.ReadFile "static/data/search-players.json" }}{{ . | md5 | truncate 8 "" }}{{ end }}';
  var PAGE = '{{ "search/" | relURL }}';
  var GROUPS = { p: 'players', t: 'teams', b: 'ARKBOARD', x: 'Process', l: 'ARKLIBRARY', s: 'ST. CLAIRE', n: '1NT', z: 'LAURSEN_111', a: 'articles', o: 'pages' };
  var GICON = { p: 'pointer', t: 'standings', b: 'arkboard', x: 'process', l: 'arklibrary', s: 'arkndjl', n: 'cs', z: 'note', a: 'library', o: 'arkboard' };
  var GW = { b: 30, x: 15, l: 20, s: 25, n: 25, z: 10, a: 20, o: 20, p: 0, t: 25 };   // a page or tab outranks a player of equal match

  var LET = { 'ø': 'o', 'ł': 'l', 'đ': 'd', 'ð': 'd', 'þ': 'th', 'ß': 'ss', 'æ': 'ae', 'œ': 'oe', 'ı': 'i' };
  function fold(s) {
    return String(s == null ? '' : s).toLowerCase().replace(/[øłđðþßæœı]/g, function (c) { return LET[c]; })
      .normalize('NFKD').replace(/[̀-ͯ]/g, '').replace(/['’`.]/g, '').replace(/[^a-z0-9]+/g, ' ').trim();
  }
  function slug(s) { return String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''); }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function abs(p) { return !p || p[0] === '/' || p[0] === '#' || /^https?:/.test(p) ? p : '/' + p; }

  // ---- index ----
  var ITEMS = null, loading = null, nPlayers = 0;
  function add(g, t, s, u, i, w, x) {
    var k = fold(t);
    ITEMS.push({ g: g, t: t, s: s || '', u: u, i: abs(i || ''), w: w || 0, k: k, ws: k.split(' '), ks: fold(s), x: x });
  }
  function load() {
    if (loading) return loading;
    ITEMS = []; nPlayers = 0;
    var site = fetch(SITE).then(function (r) { if (!r.ok) throw new Error('index ' + r.status); return r.json(); });
    var play = fetch(PLAY).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; });
    loading = site.then(function (S) {
      S.rows.forEach(function (r) { add(r.g, r.t, r.s, r.u, r.i, 50); });
      return play.then(function (P) {
        if (!P) return;
        var pages = S.pages || {};
        P.rows.forEach(function (r) {
          var b = P.boards[r[0]], pg = b && pages[b[0]]; if (!pg) return;   // a page that no longer exists (or a draft) drops its rows
          var q = 'q=' + encodeURIComponent(r[6] || r[1]) + (r[5] ? '&p=' + encodeURIComponent(r[5]) : '');
          add(b[2] === 't' ? 't' : 'p', r[1], (r[2] ? r[2] + ' · ' : '') + pg[1], pg[0] + '#' + slug(b[1]) + ':' + q, r[3] >= 0 ? P.imgs[r[3]] : pg[2], r[4],
            { b: b[0], sub: r[2] || '', pid: r[5] || '' });   // the board row itself, for "your favorites" (assets/js/favs.js)
          nPlayers++;
        });
      });
    }).then(function () { return ITEMS; });
    // a failed load (offline, a deploy in flight) is not kept: the next keystroke fetches the index again
    loading.catch(function () { loading = null; ITEMS = null; });
    return loading;
  }

  // ---- matching ----
  function near(a, b) {   // edit distance <= 1 (<= 2 for long words), a = typed word
    if (a.length < 4) return false;
    var lim = a.length >= 9 ? 2 : 1;
    if (Math.abs(a.length - b.length) > lim) return false;
    if (b.length > a.length + lim) return false;
    var prev = [], cur, i, j;
    for (j = 0; j <= b.length; j++) prev[j] = j;
    for (i = 1; i <= a.length; i++) {
      cur = [i]; var best = i;
      for (j = 1; j <= b.length; j++) {
        cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
        if (cur[j] < best) best = cur[j];
      }
      if (best > lim) return false;
      prev = cur;
    }
    return prev[b.length] <= lim;
  }
  function score(it, q, toks, fuzzy) {
    var k = it.k, base = 0;
    if (k === q) base = 1000;
    else if (k.indexOf(q) === 0) base = 800;
    else {
      var allPre = toks.every(function (t) { return it.ws.some(function (w) { return w.indexOf(t) === 0; }); });
      if (allPre) base = 620;
      else if (k.indexOf(q) >= 0) base = 470;
      else {
        var hay = k + ' ' + it.ks;
        if (toks.every(function (t) { return (' ' + hay).indexOf(' ' + t) >= 0; })) base = 320;
        else if (toks.every(function (t) { return hay.indexOf(t) >= 0; })) base = 220;
        else if (fuzzy && toks.every(function (t) { return it.ws.some(function (w) { return w.indexOf(t) === 0 || near(t, w); }); })) base = 140;
      }
    }
    if (!base) return 0;
    return base + (it.w || 0) * 0.9 + GW[it.g] - Math.min(40, k.length * 0.4);
  }
  function search(raw) {
    var q = fold(raw); if (!q) return [];
    var toks = q.split(' '), out = [];
    for (var i = 0; i < ITEMS.length; i++) { var s = score(ITEMS[i], q, toks, false); if (s) out.push([s, ITEMS[i]]); }
    // a typo pass only when the words found little: one wrong letter (two in a 9+ letter word)
    if (out.length < 8) {
      var got = new Set(out.map(function (o) { return o[1]; }));
      for (i = 0; i < ITEMS.length; i++) { if (got.has(ITEMS[i])) continue; s = score(ITEMS[i], q, toks, true); if (s) out.push([s, ITEMS[i]]); }
    }
    out.sort(function (a, b) { return b[0] - a[0]; });
    return out;
  }

  // ---- rendering ----
  function mark(t, raw) {
    var toks = fold(raw).split(' ').filter(Boolean), lo = t.toLowerCase();
    if (!toks.length || lo.length !== t.length) return esc(t);
    var on = [];
    toks.forEach(function (w) {
      var re = new RegExp('(^|[^a-z0-9])(' + w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'g'), m;
      while ((m = re.exec(lo))) { for (var j = m.index + m[1].length; j < m.index + m[0].length; j++) on[j] = 1; if (re.lastIndex === m.index) re.lastIndex++; }
    });
    var h = '', o = false;
    for (var i = 0; i < t.length; i++) { if (on[i] && !o) { h += '<mark>'; o = true; } if (!on[i] && o) { h += '</mark>'; o = false; } h += esc(t[i]); }
    return h + (o ? '</mark>' : '');
  }
  function pic(it) {
    if (it.i && it.i[0] === '#') return '<svg class="srch__ico" aria-hidden="true"><use href="' + esc(it.i) + '"/></svg>';
    if (it.i) return '<img class="srch__img" src="' + esc(it.i) + '" alt="" width="24" height="24" loading="lazy" onerror="this.outerHTML=\'<svg class=&quot;srch__ico&quot; aria-hidden=&quot;true&quot;><use href=&quot;#icon-' + GICON[it.g] + '&quot;/></svg>\'">';
    return '<svg class="srch__ico" aria-hidden="true"><use href="#icon-' + GICON[it.g] + '"/></svg>';
  }
  function row(it, raw, tag) {
    return '<a class="srch__row" href="' + esc(it.u) + '">' + pic(it) + '<span class="srch__txt"><span class="srch__t">' + mark(it.t, raw) + '</span>' +
      (it.s ? '<span class="srch__s">' + esc(it.s) + '</span>' : '') + '</span>' + (tag ? '<span class="srch__g">' + GROUPS[it.g] + '</span>' : '') + '</a>';
  }
  function go(q) { location.href = PAGE + '?q=' + encodeURIComponent(q.trim()); }

  // ---- header bar ----
  function bar(form) {
    var input = form.querySelector('input'), list = form.querySelector('[data-srch-drop]'), sel = -1, timer, last = '';
    function close() { list.hidden = true; sel = -1; input.setAttribute('aria-expanded', 'false'); }
    function draw() {
      var v = input.value; if (v === last && !list.hidden) return; last = v;
      if (!fold(v)) { close(); return; }
      load().then(function () {
        if (input.value !== v) return;
        var hits = search(v), top = hits.slice(0, 8);
        list.innerHTML = (top.length ? top.map(function (h) { return row(h[1], v, true); }).join('') : '<span class="srch__none">0 results</span>') +
          '<a class="srch__row srch__all" href="' + PAGE + '?q=' + encodeURIComponent(v.trim()) + '"><svg class="srch__ico" aria-hidden="true"><use href="#icon-search"/></svg><span class="srch__txt"><span class="srch__t">all results</span></span><span class="srch__g">' + hits.length.toLocaleString() + '</span></a>';
        list.hidden = false; sel = -1; input.setAttribute('aria-expanded', 'true');
      }).catch(function () { last = ''; });
    }
    input.addEventListener('focus', function () { load(); if (input.value) { last = ''; draw(); } });
    input.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(draw, 70); });
    input.addEventListener('keydown', function (e) {
      var rows = list.hidden ? [] : [].slice.call(list.querySelectorAll('.srch__row'));
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        if (!rows.length) return; e.preventDefault();
        if (e.key === 'ArrowDown') sel = sel + 1 >= rows.length ? -1 : sel + 1;
        else sel = sel - 1 < -1 ? rows.length - 1 : sel - 1;
        rows.forEach(function (r, i) { r.classList.toggle('is-sel', i === sel); });
      } else if (e.key === 'Escape') { close(); input.blur(); }
    });
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var r = sel >= 0 && list.querySelectorAll('.srch__row')[sel];
      if (r) location.href = r.href; else if (input.value.trim()) go(input.value);
    });
    document.addEventListener('click', function (e) { if (!form.contains(e.target)) close(); });
    // the link a result opens can be on this same page (a tab): close the list, let the hash open it
    list.addEventListener('click', function (e) { if (e.target.closest('.srch__row')) setTimeout(close, 0); });
  }

  // ---- results page ----
  function page(root) {
    var input = root.querySelector('[data-srch-q]'), out = root.querySelector('[data-srch-out]'), chips = root.querySelector('[data-srch-chips]'),
        status = root.querySelector('[data-srch-status]'), params = new URLSearchParams(location.search), only = params.get('g') || '', more = {}, timer;
    input.value = params.get('q') || '';
    function save() {
      var p = new URLSearchParams(); if (input.value.trim()) p.set('q', input.value.trim()); if (only) p.set('g', only);
      history.replaceState(null, '', location.pathname + (p.toString() ? '?' + p : ''));
    }
    function failed() { status.textContent = 'load failed; type again to retry.'; }
    function draw() {
      var v = input.value;
      if (!ITEMS) { status.textContent = 'loading index'; load().then(draw, failed); return; }
      if (!fold(v)) { out.innerHTML = ''; chips.innerHTML = ''; status.textContent = ITEMS.length.toLocaleString() + ' indexed'; save(); return; }
      var hits = search(v), by = {}, order = [];
      hits.forEach(function (h) { var g = h[1].g; if (!by[g]) { by[g] = []; order.push(g); } by[g].push(h[1]); });
      if (only && !by[only]) only = '';
      chips.innerHTML = '<button type="button" class="srch__chip' + (only ? '' : ' is-on') + '" data-g="">all <b>' + hits.length.toLocaleString() + '</b></button>' +
        order.map(function (g) { return '<button type="button" class="srch__chip' + (only === g ? ' is-on' : '') + '" data-g="' + g + '"><svg class="srch__ico" aria-hidden="true"><use href="#icon-' + GICON[g] + '"/></svg>' + GROUPS[g] + ' <b>' + by[g].length.toLocaleString() + '</b></button>'; }).join('');
      out.innerHTML = (only ? [only] : order).map(function (g) {
        var list = by[g], n = more[g] || (only ? 50 : 8);
        return '<section class="win srch__grp" data-g="' + g + '"><div class="win__title"><span class="win__title-text"><svg class="win__icon" aria-hidden="true"><use href="#icon-' + GICON[g] + '"/></svg>' +
          esc(GROUPS[g].toLowerCase().replace(/[^a-z0-9]+/g, '_')) + '.exe<span class="win__cursor" aria-hidden="true">_</span></span><span class="win__title-btns" aria-hidden="true"><span>_</span><span>□</span><span>×</span></span></div>' +
          '<div class="srch__rows">' + list.slice(0, n).map(function (it) { return row(it, v, false); }).join('') + '</div>' +
          '<div class="win__status"><span>' + Math.min(n, list.length) + ' of ' + list.length.toLocaleString() + '</span>' +
          (list.length > n ? '<button type="button" class="cfb__btn srch__more" data-more="' + g + '">more</button>' : '<span class="win__blocks" aria-hidden="true"><i></i><i></i><i></i><i></i></span>') + '</div></section>';
      }).join('') || '<section class="win srch__grp"><div class="srch__none">0 results</div></section>';
      status.textContent = hits.length.toLocaleString() + ' results';
      save();
    }
    chips.addEventListener('click', function (e) { var b = e.target.closest('[data-g]'); if (!b) return; only = b.getAttribute('data-g'); more = {}; draw(); });
    out.addEventListener('click', function (e) { var b = e.target.closest('[data-more]'); if (!b) return; var g = b.getAttribute('data-more'); more[g] = (more[g] || (only ? 50 : 8)) + 50; draw(); });
    input.addEventListener('input', function () { clearTimeout(timer); more = {}; timer = setTimeout(draw, 90); });
    root.querySelector('form').addEventListener('submit', function (e) { e.preventDefault(); clearTimeout(timer); draw(); input.blur(); });
    status.textContent = 'loading index';
    load().then(draw, failed);
    if (!input.value) input.focus();
  }

  // the same index and matching for "your favorites" (assets/js/favs.js): load() then find(q) -> [[score, item]]
  window.arkSearch = { load: load, find: search, fold: fold };

  function init() {
    window.__arkSearch = true;
    [].forEach.call(document.querySelectorAll('[data-srch-bar]'), bar);
    var p = document.querySelector('[data-srch-page]'); if (p) page(p);
    // phones: the header's magnifier tile opens the bar
    var t = document.querySelector('[data-srch-toggle]');
    if (t) t.addEventListener('click', function () {
      var f = document.querySelector('[data-srch-bar]'), on = !f.classList.contains('is-open');
      f.classList.toggle('is-open', on); t.setAttribute('aria-expanded', on); if (on) f.querySelector('input').focus();
    });
    // "/" focuses the bar from anywhere (not while typing)
    document.addEventListener('keydown', function (e) {
      if (e.key !== '/' || e.ctrlKey || e.metaKey || /^(input|textarea|select)$/i.test((e.target.tagName || '')) || e.target.isContentEditable) return;
      var i = document.querySelector('[data-srch-page] input') || document.querySelector('[data-srch-bar] input');
      if (!i) return; e.preventDefault();
      var f = i.closest('[data-srch-bar]'); if (f) f.classList.add('is-open');
      i.focus();
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
