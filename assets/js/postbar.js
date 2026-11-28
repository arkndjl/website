// Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
// Article list strip (layouts/partials/postbar.html): search over title, summary and tags, type and tag filters, sort by
// newest, views or favorites (the counts assets/js/poststats.js loads, window.__arkPostStats), and a toggle for the articles
// this browser favorited (local storage ark-favs). Articles carry data-post, data-kind, data-tags, data-date and data-q.
(function () {
  var bar = document.querySelector('[data-pbar]'); if (!bar) return;
  var list = document.querySelector('.posts'); if (!list) return;
  var arts = [].slice.call(list.querySelectorAll('article.on-list[data-post]')); if (!arts.length) return;
  var end = arts[arts.length - 1].nextSibling, n = bar.querySelector('[data-pbar-n]'), none = document.querySelector('[data-pbar-none]');
  var favBtn = bar.querySelector('.pbar__fav'), favOnly = false;
  function fold(s) { return String(s || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase(); }
  function favs() { try { return JSON.parse(localStorage.getItem('ark-favs') || '{}') || {}; } catch (e) { return {}; } }
  function stat(a, k) { var s = (window.__arkPostStats || {})[a.getAttribute('data-post')]; return s && s[k] || 0; }
  function apply() {
    var q = fold(bar.q.value).split(/\s+/).filter(Boolean), kind = bar.kind.value, tag = bar.tag.value, sort = bar.sort.value, f = favs(), shown = 0;
    var order = arts.slice().sort(function (a, b) {
      var d = +b.getAttribute('data-date') - +a.getAttribute('data-date');
      return sort === 'new' ? d : (stat(b, sort) - stat(a, sort)) || d;
    });
    order.forEach(function (a) {
      var hay = a.getAttribute('data-q'), tags = (a.getAttribute('data-tags') || '').split('|');
      var ok = q.every(function (w) { return hay.indexOf(w) >= 0; }) && (!kind || a.getAttribute('data-kind') === kind)
        && (!tag || tags.indexOf(tag) >= 0) && (!favOnly || f[a.getAttribute('data-post')]);
      a.hidden = !ok; if (ok) shown++;
      list.insertBefore(a, end);
    });
    n.textContent = shown === arts.length ? arts.length + ' articles' : shown + ' of ' + arts.length;
    none.hidden = shown > 0;
  }
  bar.addEventListener('input', apply);
  bar.addEventListener('change', apply);
  bar.addEventListener('reset', function () { favOnly = false; favBtn.setAttribute('aria-pressed', 'false'); setTimeout(apply, 0); });
  favBtn.addEventListener('click', function () { favOnly = !favOnly; favBtn.setAttribute('aria-pressed', favOnly ? 'true' : 'false'); apply(); });
  window.addEventListener('arkposts', function () { if (bar.sort.value !== 'new' || favOnly) apply(); });
  bar.hidden = false;
  apply();
})();
