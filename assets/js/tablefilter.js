(function () {
  if (window.__arkTf) return; window.__arkTf = true;
  function txt(el) { return (el.textContent || '').replace(/\s+/g, ' ').trim(); }
  // search ignores accents and letters with no plain form, so "yildiz" finds Yıldız and "odegaard" Ødegaard (same folds as partials/namekey.html)
  var LET = { 'ø': 'o', 'Ø': 'o', 'ł': 'l', 'Ł': 'l', 'đ': 'd', 'Đ': 'd', 'ð': 'd', 'þ': 'th', 'ß': 'ss', 'æ': 'ae', 'Æ': 'ae', 'œ': 'oe', 'Œ': 'oe', 'ı': 'i', 'ħ': 'h' };
  function fold(s) { return String(s).replace(/[øØłŁđĐðþßæÆœŒıħ]/g, function (c) { return LET[c]; }).normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase(); }
  function num(s, isHt) {   // "#12" -> 12, "45+" -> 45.5, "6'2\"" or "L-6'2/180" -> 74 (height columns), "$1.2M" or "INT/$998k" -> dollars
    var h = isHt && /(\d)['-](\d{1,2}(?:\.\d+)?)/.exec(s); if (h) return h[1] * 12 + +h[2];
    var $ = /\$([\d.]+)\s*([KM]?)/i.exec(s); if ($) return +$[1] * ($[2].toUpperCase() === 'M' ? 1e6 : $[2] ? 1e3 : 1);
    var m = /-?\d+(?:\.\d+)?(?:e[+-]?\d+)?/i.exec(s.replace(/,/g, '')); if (!m) return NaN;   // Hugo writes big floats as 2.2e+08
    return +m[0] + (/\d\+/.test(s) ? 0.5 : 0);
  }
  function init() {
    document.querySelectorAll('[data-tfilter]').forEach(function (w) {
      var bar = w.querySelector('[data-tf-bar]'), table = w.querySelector('table');
      if (!bar || !table || bar.dataset.ready || w.hasAttribute('data-tf-wait')) return; bar.dataset.ready = 1;
      var heads = [].slice.call(table.tHead.rows[0].cells).map(txt),
          body = table.tBodies[0], rows = [].slice.call(body.rows), total = rows.length,
          count = w.querySelector('[data-tf-count]'), reset = bar.querySelector('[type=reset]'),
          want = bar.dataset.cols.split(',').map(function (s) { return s.trim().toLowerCase(); }), sels = [];
      rows.forEach(function (r, i) { r.dataset.i = i; });
      function col(name) { return heads.findIndex(function (h) { return h.toLowerCase() === name; }); }
      want.forEach(function (name) {
        // "label@key" filters on each row's data-key (a value no column shows as text, e.g. nationality behind a flag)
        if (name.indexOf('@') > 0) {
          var at = name.split('@'), ak = at[1], av = {};
          rows.forEach(function (r) { var v = r.getAttribute('data-' + ak); if (v) av[v] = 1; });
          var al = document.createElement('label'); al.className = 'cfb__field';
          al.innerHTML = '<span></span><select><option value="">any</option></select>';
          al.firstChild.textContent = at[0];
          var asel = al.querySelector('select');
          Object.keys(av).sort(function (a, b) { return a.localeCompare(b); }).forEach(function (v) { var o = document.createElement('option'); o.textContent = v; asel.appendChild(o); });
          bar.insertBefore(al, reset); sels.push({ attr: 'data-' + ak, key: ak, el: asel });
          return;
        }
        var c = col(name); if (c < 0) return;
        // a cell's data-o sets its option's place in the dropdown (e.g. days in calendar order)
        var vals = {}; rows.forEach(function (r) { var cell = r.cells[c], v = txt(cell); if (v && !(v in vals)) vals[v] = cell.hasAttribute('data-o') ? +cell.getAttribute('data-o') : null; });
        var list = Object.keys(vals), isNum = list.every(function (v) { return !isNaN(num(v)); }), ord = list.every(function (v) { return vals[v] != null; });
        list.sort(ord ? function (a, b) { return vals[a] - vals[b]; } : isNum ? function (a, b) { return num(b) - num(a); } : function (a, b) { return a.localeCompare(b); });
        var lab = document.createElement('label'); lab.className = 'cfb__field';
        lab.innerHTML = '<span></span><select><option value="">any</option></select>';
        lab.firstChild.textContent = heads[c].toLowerCase();
        var sel = lab.querySelector('select');
        list.forEach(function (v) { var o = document.createElement('option'); o.textContent = v; sel.appendChild(o); });
        bar.insertBefore(lab, reset); sels.push({ c: c, el: sel, fv: name === 'fv' });
      });
      var ageC = col('age'), ageSel = null;
      if (ageC >= 0) {
        var lab = document.createElement('label'); lab.className = 'cfb__field';
        lab.innerHTML = '<span>age ≤</span><select><option value="">any</option>' +
          [18, 19, 20, 21, 22, 23].map(function (a) { return '<option>' + a + '</option>'; }).join('') + '</select>';
        bar.insertBefore(lab, reset); ageSel = lab.querySelector('select');
      }
      // day chips: rows with data-day="YYYY-MM-DD" (ET); today and tomorrow by the clock in New York
      var day = '', chips = [], dset = {};
      rows.forEach(function (r) { if (r.dataset.day) dset[r.dataset.day] = 1; });
      var dlist = Object.keys(dset).sort();
      if (dlist.length) {
        var now = new Date(), et = function (d) { return d.toLocaleDateString('en-CA', { timeZone: 'America/New_York' }); },
            today = et(now), tmrw = et(new Date(now.getTime() + 864e5));
        var grp = document.createElement('p'); grp.className = 'tf__days'; grp.setAttribute('role', 'group'); grp.setAttribute('aria-label', 'day');
        [''].concat(dlist).forEach(function (d) {
          var b = document.createElement('button'), p = d.split('-');
          b.type = 'button'; b.className = 'cfb__btn' + (d ? '' : ' is-on'); b.dataset.day = d;
          b.textContent = !d ? 'all days' : d === today ? 'today' : d === tmrw ? 'tomorrow' :
            new Date(+p[0], p[1] - 1, +p[2]).toLocaleDateString('en-US', { weekday: 'short' }).toLowerCase() + ' ' + +p[1] + '/' + +p[2];
          b.addEventListener('click', function () { day = d; chips.forEach(function (c) { c.classList.toggle('is-on', c === b); }); apply(); openPk = ''; writeHash(); });
          chips.push(b); grp.appendChild(b);
        });
        bar.parentNode.insertBefore(grp, bar);
      }
      // FV dropdown means "at least": 50 keeps 50, 50+, 55…
      function apply() {
        var q = fold(bar.elements.q.value.trim()), n = 0, amax = ageSel ? parseFloat(ageSel.value) : NaN;
        rows.forEach(function (r) {
          var ok = (!q || fold(txt(r)).indexOf(q) >= 0) && (!day || r.dataset.day === day);
          sels.forEach(function (s) {
            if (!ok || !s.el.value) return;
            var v = s.attr ? r.getAttribute(s.attr) || '' : txt(r.cells[s.c]);
            ok = s.fv ? num(v) >= num(s.el.value) : v === s.el.value;
          });
          if (ok && !isNaN(amax)) { var a = num(txt(r.cells[ageC])); ok = !isNaN(a) && a <= amax; }
          r.hidden = !ok; if (ok) n++;
        });
        if (w.hasAttribute('data-tf-rerank')) {   // ranks within the filters, in the table's first order
          var k = 0; rows.slice().sort(function (a, b) { return a.dataset.i - b.dataset.i; }).forEach(function (r) {
            var c = r.querySelector('.cfb__rk'); if (c && !r.hidden) c.textContent = ++k; });
        }
        if (count) count.textContent = (n === total ? total : n + ' of ' + total) + ' ' + (count.dataset.noun || 'rows');
      }
      bar.addEventListener('input', function () { apply(); writeHash(); }); bar.addEventListener('change', function () { apply(); writeHash(); });
      bar.addEventListener('reset', function () { day = ''; chips.forEach(function (c, i) { c.classList.toggle('is-on', !i); }); setTimeout(function () { apply(); writeHash(); }); });
      sels.forEach(function (s) { if (s.fv) s.el.previousElementSibling.textContent = 'FV ≥'; });
      bar.hidden = false;
      var ths = [].slice.call(table.tHead.rows[0].cells), cur = -1, dir = 1;
      ths.forEach(function (th, c) {
        th.tabIndex = 0; th.setAttribute('data-sort', '');
        function key(r) { var cell = r.cells[c]; return cell && cell.hasAttribute('data-v') ? cell.getAttribute('data-v') : txt(cell); }
        function go() {
          var h = heads[c].toLowerCase(), isHt = /(^|\W)(ht|height)\b/.test(h),
              vals = rows.map(key).filter(function (v) { return !/^[-–—]?$/.test(v); }), isNum = vals.length && vals.every(function (v) { return !isNaN(num(v, isHt)); }),
              asc = !isNum || /^(rk|pick|rd|age|bb|#|power|seed)$/.test(h);
          dir = c === cur ? -dir : (asc ? 1 : -1); cur = c;
          rows.sort(function (a, b) {
            var x = key(a), y = key(b);
            if (isNum) { x = num(x, isHt); y = num(y, isHt); if (isNaN(x)) return 1; if (isNaN(y)) return -1; return (x - y) * dir || a.dataset.i - b.dataset.i; }
            return x.localeCompare(y) * dir || a.dataset.i - b.dataset.i;
          });
          rows.forEach(function (r) { body.appendChild(r); });
          ths.forEach(function (t) { t.removeAttribute('aria-sort'); });
          th.setAttribute('aria-sort', dir > 0 ? 'ascending' : 'descending');
        }
        th.__go = go;
        th.addEventListener('click', function () { go(); openPk = ''; writeHash(); });
        th.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); openPk = ''; writeHash(); } });
      });
      // the state in the address, so a link reopens it: #<tab>:s=<column>&d=-1&<filter>=<value>&day=<date>&p=<row key>.
      // p is the row's data-pk (a stable id: NHL, Transfermarkt), and opens its scouting report (partials/prospectjs.html)
      var id = slug(w.getAttribute('data-tab')), openPk = '';
      if (id) {
        var same = [].slice.call(document.querySelectorAll('[data-tfilter][data-tab]')).filter(function (x) { return slug(x.getAttribute('data-tab')) === id; });
        if (same.indexOf(w) > 0) id += '-' + (same.indexOf(w) + 1);
      }
      function writeHash() {
        if (!id) return;
        var s = [], q = bar.elements.q.value.trim();
        if (cur >= 0) s.push('s=' + slug(heads[cur]), 'd=' + dir);
        if (q) s.push('q=' + encodeURIComponent(q));
        sels.forEach(function (x) { if (x.el.value) s.push((x.key || slug(heads[x.c])) + '=' + encodeURIComponent(x.el.value)); });
        if (ageSel && ageSel.value) s.push('age=' + ageSel.value);
        if (day) s.push('day=' + day);
        if (openPk) s.push('p=' + encodeURIComponent(openPk));
        var h = s.length ? '#' + id + ':' + s.join('&') : '#' + id, at = location.hash.split(':')[0] === '#' + id;
        if (s.length || at) { if (h !== location.hash) history.replaceState(null, '', location.pathname + location.search + h); }
      }
      body.addEventListener('click', function (e) {
        if (e.target.closest('a')) return;
        var tr = e.target.closest('tr[data-pk]'); if (!tr) return;
        openPk = openPk === tr.dataset.pk ? '' : tr.dataset.pk; writeHash();
      });
      if (id && location.hash.split(':')[0] === '#' + id && location.hash.indexOf(':') > 0) {
        var want = {};
        location.hash.slice(id.length + 2).split('&').forEach(function (kv) { var i = kv.indexOf('='); if (i > 0) want[kv.slice(0, i)] = decodeURIComponent(kv.slice(i + 1)); });
        if (want.q) bar.elements.q.value = want.q;
        sels.forEach(function (x) { var v = want[(x.key || slug(heads[x.c]))]; if (v != null && [].some.call(x.el.options, function (o) { return o.value === v; })) x.el.value = v; });
        if (ageSel && want.age) ageSel.value = want.age;
        if (want.day) chips.forEach(function (c) { if (c.dataset.day === want.day) c.click(); });
        var sc = heads.map(slug).indexOf(want.s);
        if (sc >= 0) { ths[sc].__go(); if (+want.d !== dir) ths[sc].__go(); }
        apply();
        // the tab itself opens from the hash (wintabs.html reads the part before the colon); a second table in a tab opens it here
        var group = w.parentElement && w.parentElement.closest('[data-wintabs]');
        if (group && group.__show && !w.classList.contains('is-active')) group.__show(w.getAttribute('data-tab'));
        var row = want.p && rows.filter(function (r) { return r.dataset.pk === want.p; })[0];
        writeHash();
        setTimeout(function () {
          if (row && !row.hidden) row.click();
          (row && !row.hidden ? row : w).scrollIntoView({ block: row ? 'center' : 'start' });
        }, 60);
      }
    });
  }
  function slug(s) { return String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''); }
  window.__arkTfInit = init;
  document.addEventListener('ark:lazy', init);   // a tab built on first open (lazytab.html)
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); } else { init(); }
})();
