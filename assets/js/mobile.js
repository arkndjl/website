// Phones: every wide table keeps its label column (player, team, matchup...) in view while the numbers scroll.
// Tables with their own pinned column (.cfb__name, .tstick, .cfbrc, ...) are left alone; the rest get
// data-pin="<column>" (static/style.css pins it). Tables built later (lazy tabs, re-sorts) are caught by a
// MutationObserver. A label still wider than about half the screen after wrapping is not pinned.
(function () {
  var mq = window.matchMedia('(max-width: 684px)');
  var LABEL = /^(player|prospect|name|team|club|school|coach|matchup|game|bet|pick|league|lg|staff|recruit|nation|country|conference|conf)\b/i;
  function scroller(t) {
    for (var el = t.parentElement; el && el !== document.body; el = el.parentElement) {
      var o = getComputedStyle(el).overflowX; if (o === 'auto' || o === 'scroll') return el;
    }
    return null;
  }
  function bodyRow(t) {
    var rows = t.tBodies.length ? t.tBodies[0].rows : t.rows;
    for (var i = 0; i < rows.length && i < 12; i++) {
      var r = rows[i], ok = r.cells.length > 2;
      for (var j = 0; ok && j < r.cells.length; j++) if (r.cells[j].colSpan > 1) ok = false;
      if (ok) return r;
    }
    return null;
  }
  function pin(t) {
    if (t.dataset.pin) return;
    if (!t.offsetParent) return;                              // hidden tab: try again when it's shown
    var sc = scroller(t); if (!sc || t.offsetWidth <= sc.clientWidth + 2) return;
    var row = bodyRow(t); if (!row) return;
    for (var j = 0; j < Math.min(4, row.cells.length); j++) if (getComputedStyle(row.cells[j]).position === 'sticky') { t.dataset.pin = 'own'; return; }
    var head = t.tHead && t.tHead.rows.length ? t.tHead.rows[t.tHead.rows.length - 1].cells : null;
    var k = -1;
    if (head && head.length === row.cells.length) {
      for (j = 0; j < Math.min(4, head.length); j++) if (LABEL.test(head[j].textContent.trim())) { k = j; break; }
    }
    // no named label column: the first, or the second when the first is a narrow rank
    if (k < 0) k = row.cells[0].offsetWidth < 48 && /^\s*[#\d.]*\s*$/.test(row.cells[0].textContent) ? 1 : 0;
    // pinned, the cell wraps at 40vw (static/style.css); one still wider than ~half the scroller is left unpinned
    t.dataset.pin = String(k + 1);
    if (row.cells[k].offsetWidth > sc.clientWidth * 0.55) t.dataset.pin = 'none';
  }
  var queued = false;
  function scan() {
    queued = false;
    if (!mq.matches) return;
    document.querySelectorAll('table:not([data-pin])').forEach(pin);
  }
  function soon() { if (!queued) { queued = true; requestAnimationFrame(scan); } }
  function start() {
    scan();
    new MutationObserver(soon).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['class', 'hidden'] });
    document.addEventListener('ark:lazy', soon);
    (mq.addEventListener ? mq.addEventListener('change', soon) : mq.addListener(soon));
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
