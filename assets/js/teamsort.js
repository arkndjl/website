/* Every team dropdown on the site lists its teams A to Z (Noah, Nov 28). A team dropdown is a <select> with name or
   aria-label "team", a data-*-team attribute, or a label whose caption reads team, teams or school. Options with no
   value or reading any / all / loading stay on top; optgroups sort inside themselves. The build gate checks that every
   team dropdown in layouts/ matches (scripts/check_build.py team_selects). */
(function () {
  var HEAD = /^(any|all|every|loading|none|-|–|—)/i;
  function isTeam(s) {
    if (/^teams?$/i.test(s.name || '') || /^teams?$/i.test(s.getAttribute('aria-label') || '')) return true;
    for (var i = 0; i < s.attributes.length; i++) if (/^data-[a-z0-9]+-team$/.test(s.attributes[i].name)) return true;
    var l = s.closest('label'), c = l && l.querySelector('span');
    return !!(c && /^(teams?|school)$/i.test(c.textContent.trim()));
  }
  var cmp = function (a, b) { return a.textContent.trim().localeCompare(b.textContent.trim(), 'en', { sensitivity: 'base', numeric: true }); };
  function sortBox(box) {
    var kids = Array.prototype.filter.call(box.children, function (o) { return o.tagName === 'OPTION'; });
    var body = kids.filter(function (o) { return o.value !== '' && !HEAD.test(o.textContent.trim()); });
    var want = body.slice().sort(cmp), same = want.every(function (o, i) { return o === body[i]; });
    if (!same) { var ref = body[body.length - 1].nextSibling; want.forEach(function (o) { box.insertBefore(o, ref); }); }   // ref sits after every team, so each lands in order
    return !same;
  }
  function sortSel(s) {
    var v = s.value, moved = sortBox(s);
    Array.prototype.forEach.call(s.querySelectorAll('optgroup'), function (g) { moved = sortBox(g) || moved; });
    if (moved && s.value !== v) s.value = v;
  }
  function scan(root) {
    Array.prototype.forEach.call((root || document).querySelectorAll('select'), function (s) {
      if (s.__ts || !isTeam(s)) return;
      s.__ts = 1; sortSel(s);
      new MutationObserver(function () { sortSel(s); }).observe(s, { childList: true, subtree: true });
    });
  }
  scan();
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { scan(); });
  new MutationObserver(function (ms) { ms.forEach(function (m) { m.addedNodes.forEach(function (n) { if (n.nodeType === 1 && (n.tagName === 'SELECT' || n.getElementsByTagName('select').length)) scan(n.tagName === 'SELECT' ? n.parentNode : n); }); }); })
    .observe(document.documentElement, { childList: true, subtree: true });
})();
