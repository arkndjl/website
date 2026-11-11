// Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
// Pixel bars inside table cells: the column a table is sorted by (th[aria-sort]) and any column whose header
// carries data-vz draw each value's size under the number, so gaps and tiers show without reading every figure.
// Scale: a column that crosses zero is drawn from zero (pink below it); one whose values all sit in the top half
// of their range (ratings, 20-80 grades) runs low to high; anything else runs from zero. Rank columns get no bar.
// Standings tables also colour streaks and differentials by sign. static/style.css draws the bar (td.vz).
(function () {
  if (window.__arkVz) return; window.__arkVz = true;
  var RANK = /^(rk|rank|#|no\.?|pick|seed|pos|±|\+\/-|δ|wk)$/i, SIGNED = /^(diff|gd|\+\/-|strk|streak|net)$/i, MAXROWS = 4000;
  var NUM = /^[+\-−]?\$?(?:\d[\d,]*\.?\d*|\.\d+)(?:%|[kKmM])?$/;
  function headRow(t) { return t.tHead && t.tHead.rows.length ? t.tHead.rows[t.tHead.rows.length - 1] : null; }
  function label(th) { return (th.textContent || '').replace(/[▲▼\s]+/g, ' ').trim(); }
  function val(td) {
    var d = td.getAttribute('data-v'); if (d != null && d !== '' && !isNaN(+d)) return +d;
    var s = (td.textContent || '').trim().split(/\s+/)[0] || ''; if (!NUM.test(s)) return NaN;
    var k = /[kKmM]$/.exec(s), v = parseFloat(s.replace(/−/, '-').replace(/[$,%kKmM]/g, ''));
    return k ? v * (/m/i.test(k[0]) ? 1e6 : 1e3) : v;
  }
  function clear(t) {
    var on = t.querySelectorAll('td.vz');
    for (var i = 0; i < on.length; i++) { on[i].classList.remove('vz', 'vz--neg'); on[i].style.removeProperty('--vz'); }
  }
  function column(t, c, n) {
    var rows = [], vals = [], lo = Infinity, hi = -Infinity, cells = 0;
    for (var b = 0; b < t.tBodies.length; b++) for (var i = 0, R = t.tBodies[b].rows; i < R.length; i++) {
      var r = R[i]; if (r.cells.length !== n) continue;
      var td = r.cells[c]; if (td.tagName !== 'TD') continue;
      cells++; var v = val(td); if (isNaN(v)) continue;
      rows.push(td); vals.push(v); if (v < lo) lo = v; if (v > hi) hi = v;
    }
    if (rows.length < 3 || rows.length < cells * 0.6 || hi === lo) return;
    if (getComputedStyle(rows[0]).position === 'sticky') return;
    var cross = lo < 0 && hi > 0, top = Math.max(Math.abs(lo), Math.abs(hi)), span = !cross && lo > 0 && lo / hi > 0.5;
    for (i = 0; i < rows.length; i++) {
      var f = span ? 0.08 + 0.92 * (vals[i] - lo) / (hi - lo) : Math.abs(vals[i]) / top;
      rows[i].classList.add('vz'); rows[i].classList.toggle('vz--neg', vals[i] < 0);
      rows[i].style.setProperty('--vz', f.toFixed(3));
    }
  }
  function signs(t, c, n) {
    for (var b = 0; b < t.tBodies.length; b++) for (var i = 0, R = t.tBodies[b].rows; i < R.length; i++) {
      var r = R[i]; if (r.cells.length !== n) continue;
      var td = r.cells[c], s = (td.textContent || '').trim();
      td.classList.toggle('vz-up', /^(\+\d|W\d)/.test(s)); td.classList.toggle('vz-dn', /^([\-−]\d|L\d)/.test(s));
    }
  }
  function draw(t) {
    var hr = headRow(t); if (!hr) return;
    var n = 0, i, ths = hr.cells, span = false;
    for (i = 0; i < ths.length; i++) { n += ths[i].colSpan; if (ths[i].colSpan > 1) span = true; }
    clear(t);
    if (span) return;
    var count = 0; for (i = 0; i < t.tBodies.length; i++) count += t.tBodies[i].rows.length;
    if (count > MAXROWS) return;
    var st = t.classList.contains('st-table');
    for (i = 0; i < ths.length; i++) {
      var th = ths[i], name = label(th);
      if (st && SIGNED.test(name)) signs(t, i, n);
      if (th.hasAttribute('data-vz') || (th.hasAttribute('aria-sort') && !RANK.test(name))) column(t, i, n);
    }
  }
  var queue = [], tick = 0;
  function later(t) {
    if (queue.indexOf(t) < 0) queue.push(t);
    if (!tick) tick = requestAnimationFrame(function () { tick = 0; var q = queue; queue = []; q.forEach(draw); });
  }
  function table(node) { for (var el = node; el; el = el.parentElement) if (el.tagName === 'TABLE') return el; return null; }
  function scan(root) { var all = (root || document).querySelectorAll('table'); for (var i = 0; i < all.length; i++) later(all[i]); }
  function init() {
    scan();
    new MutationObserver(function (list) {
      for (var i = 0; i < list.length; i++) {
        var m = list[i];
        if (m.type === 'attributes') { var t = table(m.target); if (t) later(t); continue; }
        var tb = table(m.target); if (tb) { later(tb); continue; }
        for (var j = 0; j < m.addedNodes.length; j++) {
          var a = m.addedNodes[j]; if (a.nodeType !== 1) continue;
          if (a.tagName === 'TABLE') later(a); else if (a.querySelector && a.querySelector('table')) scan(a);
        }
      }
    }).observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ['aria-sort'] });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
