// Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
// Term hovers: one popover for every acronym and metric label on the site (data/terms.json: what it stands for, one
// line on what it is, the Process glossary entry it links to). Hover or keyboard focus on desktop, tap on phones.
// Looked up on the fly, so tables built later (lazy tabs, boards drawn by script) need nothing:
//   <th>           its text is the term ("XPM", "TS%"; "O XPM" falls back to the one known word in it)
//   [data-term]    names the term for any other element (data-term="FV"); metric chips and legend keys (SEL) by their text
//   .tick, .nws…   running text: known site metrics are wrapped as they appear (INLINE below)
// A header's own title="" (the table's note on that column) is shown under the definition, and on phones too.
// data/terms.json "by" holds a page's own reading of a term (WAR on the NFL page is NFL WAR).
(function () {
  var D = {{ site.Data.terms | jsonify | safeJS }};
  var T = D.terms || {}, AL = D.alias || {}, GR = D.groups || {}, LOW = {}, k;
  for (k in T) if (!(k.toLowerCase() in LOW)) LOW[k.toLowerCase()] = k;
  var PROC = {{ "process/" | relURL | jsonify | safeJS }};
  var page = (location.pathname.replace(/\/+$/, '').split('/').pop() || 'home').toLowerCase();
  var SEL = '[data-term], th, .term, .cfb__chip';   // labels read as terms by their text
  var INLINE = '.tick__g, .nws__main, [data-terms]';

  function one(s) { if (AL[s]) s = AL[s]; return T[s] ? s : LOW[s.toLowerCase()] || null; }
  function key(s) {
    s = String(s || '').replace(/[▲▼↑↓⇅↕]/g, '').replace(/\s+/g, ' ').trim().replace(/\.$/, '');
    if (!s || s.length > 28) return null;
    var k = one(s); if (k) return k;
    var at = /^(.+?)@\d+$/.exec(s); if (at) return one(at[1]);   // "TS%@25": the stat at a workload tier
    // "XPM NOW", "St WAR/1k", "GSAx/G": the one known word in the label (words first, then the parts of a rate)
    var seps = [/[\s·]+/, /[\s·\/]+/];
    for (var i = 0; i < seps.length; i++) {
      var hit = null, n = 0;
      s.split(seps[i]).forEach(function (w) { var m = w && one(w); if (m && T[m].part !== false) { if (m !== hit) n++; hit = m; } });
      if (n === 1) return hit;
      if (n > 1) return null;
    }
    return null;
  }
  function entry(k, el, note) {
    var e = T[k]; if (!e || (e.only && e.only.indexOf(page) < 0)) return null;
    var by = e.by || {}, ctx = null, n = el;
    // the sport: a data-term-ctx on an ancestor (multi-sport pages), else the page
    while (n && n.getAttribute) { var c = n.getAttribute('data-term-ctx') || n.getAttribute('data-sport'); if (c && by[c.toLowerCase()]) { ctx = c.toLowerCase(); break; } n = n.parentNode; }
    var o = by[ctx || page] || {};
    // the header's own note picks the reading where one label means two things (G: games or goals)
    if (note && e.when) for (var i = 0; i < e.when.length; i++) if (new RegExp(e.when[i].m, 'i').test(note)) { o = e.when[i]; break; }
    // a page's reading may move the term to another glossary entry (g) or to an abbreviation group (a)
    var g = o.g !== undefined ? o.g : o.a ? '' : e.g || '', a = o.a || e.a || '';
    return { k: k, n: o.n || e.n || '', d: o.d || e.d || '', to: g || (GR[a] || {}).term || '', own: !!g };
  }
  function href(e) { return PROC + '#g-' + e.to.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''); }

  var tip, cur, hideT, showT;
  function box() {
    if (tip) return tip;
    tip = document.createElement('div'); tip.className = 'termtip'; tip.setAttribute('role', 'tooltip'); tip.id = 'termtip'; tip.hidden = true;
    tip.addEventListener('mouseenter', function () { clearTimeout(hideT); });
    tip.addEventListener('mouseleave', function () { hide(120); });
    document.body.appendChild(tip);
    return tip;
  }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function find(t) {
    if (!t || !t.closest) return null;
    var el = t.closest(SEL);
    if (!el || (tip && tip.contains(el))) return null;
    return el;
  }
  function info(el) {
    if (el.__term !== undefined) return el.__term;
    var note = el.getAttribute('title');
    if (note != null && !el.hasAttribute('data-term-keep')) { el.removeAttribute('title'); el.setAttribute('data-note', note); }   // no second, native tooltip
    note = el.getAttribute('data-note') || '';
    var k = el.getAttribute('data-term') || key(el.textContent);
    var e = k ? entry(T[k] ? k : key(k), el, note) : null;
    // a chip is a term only as a metric with its own note and glossary entry (EDGE, OT and SF are also positions)
    if (e && el.tagName !== 'TH' && !el.hasAttribute('data-term') && !el.classList.contains('term') && !(note && e.own)) e = null;
    if (e && note && (note.toLowerCase() === e.n.toLowerCase() || note === e.d)) note = '';
    return (el.__term = e || note ? { e: e, note: note } : null);
  }
  function show(el) {
    var r = info(el); if (!r) return;
    clearTimeout(hideT);
    var b = box(), e = r.e, h = '';
    if (e) {
      h += '<p class="termtip__h"><b>' + esc(e.k) + '</b>' + (e.n && e.n.toLowerCase() !== e.k.toLowerCase() ? '<span>' + esc(e.n) + '</span>' : '') + '</p>';
      if (e.d) h += '<p class="termtip__d">' + esc(e.d) + '</p>';
    }
    if (r.note) h += '<p class="termtip__n">' + esc(r.note) + '</p>';
    if (e && e.to) h += '<a class="termtip__a" href="' + esc(href(e)) + '">process</a>';
    b.innerHTML = h; b.hidden = false; cur = el;
    el.setAttribute('aria-describedby', 'termtip');
    place(el);
  }
  function place(el) {
    var b = tip, r = el.getBoundingClientRect(), vw = document.documentElement.clientWidth, vh = window.innerHeight;
    b.style.left = '0px'; b.style.top = '0px';
    var w = b.offsetWidth, h = b.offsetHeight;
    var x = Math.max(6, Math.min(vw - w - 6, r.left + r.width / 2 - w / 2));
    var y = r.bottom + 6; if (y + h > vh - 6 && r.top - h - 6 > 0) y = r.top - h - 6;
    b.style.left = Math.round(x) + 'px'; b.style.top = Math.round(Math.max(6, y)) + 'px';
  }
  function hide(ms) {
    clearTimeout(showT); clearTimeout(hideT);
    hideT = setTimeout(function () { if (tip) tip.hidden = true; if (cur) cur.removeAttribute('aria-describedby'); cur = null; }, ms || 0);
  }

  // hover and focus with a mouse or keyboard; a tap on phones (a sortable header still sorts); a tap elsewhere closes
  var touch = false;
  document.addEventListener('pointerdown', function (e) { touch = e.pointerType === 'touch' || e.pointerType === 'pen'; }, true);
  document.addEventListener('pointerover', function (e) {
    if (e.pointerType !== 'mouse') return;
    var el = find(e.target); if (!el) return;
    if (el === cur) { clearTimeout(hideT); return; }
    if (!info(el)) return;
    clearTimeout(showT); showT = setTimeout(function () { show(el); }, 140);
  });
  document.addEventListener('pointerout', function (e) {
    if (e.pointerType !== 'mouse') return;
    var el = find(e.target); if (!el) return;
    if (e.relatedTarget && (el.contains(e.relatedTarget) || (tip && tip.contains(e.relatedTarget)))) return;
    clearTimeout(showT); if (el === cur) hide(160);
  });
  document.addEventListener('focusin', function (e) { var el = find(e.target); if (el && !touch && e.target === el && info(el)) show(el); });
  document.addEventListener('focusout', function (e) { if (cur && find(e.target) === cur && !(tip && tip.contains(e.relatedTarget))) hide(160); });
  document.addEventListener('click', function (e) {
    if (tip && tip.contains(e.target)) return;
    var el = touch ? find(e.target) : null;
    if (el && !e.target.closest('a[href], input, select') && info(el)) {
      if (cur === el && tip && !tip.hidden) hide(); else show(el);
      return;
    }
    if (cur) hide();
  });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && cur) hide(); });
  window.addEventListener('scroll', function (e) { if (!cur || (tip && e.target && e.target.nodeType === 1 && tip.contains(e.target))) return; if (document.contains(cur)) place(cur); else hide(); }, { passive: true, capture: true });
  window.addEventListener('resize', function () { if (cur) hide(); });

  // running text (ticker cells, news rows): the site's own metrics become terms
  var words = Object.keys(T).filter(function (w) { return T[w].inline; }).sort(function (a, b) { return b.length - a.length; });
  var RX = words.length ? new RegExp('(^|[^A-Za-z0-9+%])(' + words.map(function (w) { return w.replace(/[.*+?^${}()|[\]\\\/]/g, '\\$&'); }).join('|') + ')(?![A-Za-z0-9+%])') : null;
  function wrap(root) {
    if (!RX || root.__terms) return; root.__terms = true;
    var tw = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null), nodes = [], n;
    while ((n = tw.nextNode())) if (n.nodeValue.length > 1 && !n.parentNode.closest('.term, [data-term], script, style')) nodes.push(n);
    nodes.forEach(function (t) {
      var m, guard = 0;
      while (t && (m = RX.exec(t.nodeValue)) && guard++ < 8) {
        var at = m.index + m[1].length, mid = t.splitText(at), rest = mid.splitText(m[2].length);
        var s = document.createElement('span'); s.className = 'term'; s.textContent = m[2];
        mid.parentNode.replaceChild(s, mid); t = rest;
      }
    });
  }
  var queued = false;
  function scan() { queued = false; [].forEach.call(document.querySelectorAll(INLINE), wrap); }
  function soon() { if (!queued) { queued = true; requestAnimationFrame(scan); } }
  function start() {
    scan();
    new MutationObserver(soon).observe(document.body, { childList: true, subtree: true });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
  window.__arkTerm = { key: key, entry: entry };
})();
