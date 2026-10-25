// "updated" stamps that know when they're stale (layouts/partials/fresh.html, audit #29). Each .ark-fresh carries its
// feed's asof and sport; past the sport's threshold (data/freshness.json: inHours in season, offHours outside it) it
// gets .is-stale and a "stale" tag, so a feed that stopped updating says so even when nothing rebuilds the page.
// window.__arkFresh(el) marks a stamp a script filled in later (it sets data-asof and data-sport first).
(function () {
  if (window.__arkFresh) return;
  var R = {{ with site.Data.freshness }}{{ dict "inHours" .inHours "sports" .sports | jsonify | safeJS }}{{ else }}{"inHours": 36, "sports": {}}{{ end }};
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function inSeason(s, d) {
    if (!s.season) return true;
    var md = pad(d.getMonth() + 1) + '-' + pad(d.getDate()), a = s.season[0], b = s.season[1];
    return a <= b ? md >= a && md <= b : md >= a || md <= b;
  }
  // a date-only asof counts from the end of that day (UTC), a timestamp as is
  function at(a) { return /^\d{4}-\d{2}-\d{2}$/.test(a) ? Date.parse(a + 'T23:59:59Z') : Date.parse(a); }
  function limit(sport, now) { var s = R.sports[sport]; return !s ? R.inHours : inSeason(s, now) ? R.inHours : (s.offHours || R.inHours); }
  function ago(h) { return h < 1 ? 'under an hour ago' : h < 48 ? Math.round(h) + ' h ago' : Math.round(h / 24) + ' days ago'; }
  function mark(el) {
    var a = el.getAttribute('data-asof'), t = a && at(a); if (!t) return;
    var now = new Date(), h = (now - t) / 3.6e6, lim = limit(el.getAttribute('data-sport'), now);
    el.title = 'updated ' + ago(Math.max(h, 0)) + ' · stale past ' + lim + ' h';
    var stale = h > lim;
    el.classList.toggle('is-stale', stale);
    var tag = el.querySelector('.ark-fresh__tag');
    if (stale && !tag) { tag = document.createElement('b'); tag.className = 'ark-fresh__tag'; tag.textContent = 'stale'; el.appendChild(document.createTextNode(' ')); el.appendChild(tag); }
    if (!stale && tag) tag.remove();
  }
  function all(root) { var els = (root || document).querySelectorAll('.ark-fresh[data-asof]'); for (var i = 0; i < els.length; i++) mark(els[i]); }
  window.__arkFresh = function (el) { if (el) mark(el); else all(); };
  // a stamp a script rewrites: on = this is live data (the current season), else it is history and never stale
  window.__arkFreshSet = function (el, asof, sport, on) {
    if (!el) return;
    el.classList.toggle('ark-fresh', !!on);
    if (on) { el.setAttribute('data-asof', asof); if (sport) el.setAttribute('data-sport', sport); mark(el); }
    else { el.classList.remove('is-stale'); el.removeAttribute('title'); }
  };
  all();
  document.addEventListener('ark:lazy', function (e) { all(e.detail || document); });
  setInterval(all, 10 * 60 * 1000);   // a tab left open goes stale too
})();
