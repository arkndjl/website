// Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
// Article views and favorites (layouts/partials/poststats.html; counts in worker/site.js PostStats, /api/posts).
// The article page posts its view (the Worker keeps one a visitor a day) and lists read every count in one GET.
// The platinum star toggles a favorite: one per browser, kept in local storage with the browser's own random id, so the
// Worker can take it back later. Nothing shows until the counts load.
(function () {
  var els = [].slice.call(document.querySelectorAll('.pst[data-post]'));
  if (!els.length || !window.fetch) return;
  var API = '/api/posts';
  function get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  var favs = {};
  try { favs = JSON.parse(get('ark-favs') || '{}') || {}; } catch (e) { favs = {}; }
  var id = get('ark-vid');
  if (!/^[a-f0-9]{16,32}$/.test(id || '')) {
    var b = new Uint8Array(12);
    (window.crypto || {}).getRandomValues ? crypto.getRandomValues(b) : b.forEach(function (_, i) { b[i] = Math.random() * 256; });
    id = [].map.call(b, function (x) { return ('0' + x.toString(16)).slice(-2); }).join('');
    set('ark-vid', id);
  }
  function fmt(n) { return Number(n || 0).toLocaleString('en-US'); }
  function paint(el, d) {
    if (!d) d = { v: 0, f: 0 };
    var s = el.getAttribute('data-post'), on = !!favs[s], btn = el.querySelector('.pst__fav');
    el.querySelector('.pst__v b').textContent = fmt(d.v);
    el.querySelector('.pst__v span').textContent = d.v === 1 ? 'view' : 'views';
    btn.querySelector('b').textContent = fmt(d.f);
    btn.querySelector('.pst__l').textContent = on ? 'favorited' : 'favorite';
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    btn.setAttribute('aria-label', (on ? 'favorited' : 'favorite') + ', ' + fmt(d.f));
    btn.title = on ? 'take back your favorite' : 'favorite this article';
    btn.classList.toggle('is-on', on);
    el.hidden = false;
  }
  function post(path, body) {
    return fetch(API + '/' + path, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body || {}) })
      .then(function (r) { if (!r.ok) throw r.status; return r.json(); });
  }
  // favoriting: a pixel burst around the star (skipped under reduced motion) and a short 8-bit blip, square-wave notes
  // made on the spot with WebAudio, quiet. Taking a favorite back plays nothing.
  var RM = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches, AC = null;
  function blip() {
    try {
      AC = AC || new (window.AudioContext || window.webkitAudioContext)();
      if (AC.state === 'suspended') AC.resume();
      var t = AC.currentTime + 0.01, g = AC.createGain();
      g.connect(AC.destination);
      g.gain.setValueAtTime(0.0001, t);
      [988, 1319, 1976].forEach(function (f, i) {   // B5, E6, B6: a coin-style step up
        var o = AC.createOscillator(), at = t + i * 0.06;
        o.type = 'square'; o.frequency.setValueAtTime(f, at);
        o.connect(g); o.start(at); o.stop(at + 0.06);
        g.gain.setValueAtTime(0.045, at);
        g.gain.exponentialRampToValueAtTime(0.004, at + 0.055);
      });
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.24);
    } catch (e) {}
  }
  var COL = ['#b9f2ff', '#fff', '#7fffd4', '#c8c7ff', '#b9f2ff', '#fff', '#7fffd4', '#c8c7ff'];
  function burst(btn) {
    btn.classList.remove('is-pop'); void btn.offsetWidth; btn.classList.add('is-pop');
    if (RM) return;
    var s = btn.querySelector('.pst__s'), b = document.createElement('span');
    b.className = 'pst__burst'; b.setAttribute('aria-hidden', 'true');
    for (var i = 0; i < 8; i++) {
      var a = i * Math.PI / 4, r = i % 2 ? 20 : 30, p = document.createElement('u');
      p.style.setProperty('--dx', Math.round(Math.cos(a) * r / 2) * 2 + 'px');
      p.style.setProperty('--dy', Math.round(Math.sin(a) * r / 2) * 2 + 'px');
      p.style.background = COL[i];
      if (i % 2 === 0) p.className = 'is-x';
      b.appendChild(p);
    }
    s.appendChild(b);
    setTimeout(function () { if (b.parentNode) b.parentNode.removeChild(b); }, 700);
  }
  var cache = {};
  // the list strip (assets/js/postbar.js) sorts and filters on these counts
  function shared() { window.__arkPostStats = cache; try { window.dispatchEvent(new Event('arkposts')); } catch (e) {} }
  function bySlug(s) { return els.filter(function (e) { return e.getAttribute('data-post') === s; }); }
  els.forEach(function (el) {
    var s = el.getAttribute('data-post'), btn = el.querySelector('.pst__fav');
    btn.addEventListener('click', function () {
      if (btn.disabled) return;
      var on = !favs[s], d = cache[s] || { v: 0, f: 0 };
      btn.disabled = true;
      // drawn at once, then set to what the Worker says
      if (on) { favs[s] = 1; burst(btn); blip(); } else delete favs[s];
      cache[s] = { v: d.v, f: Math.max(0, d.f + (on ? 1 : -1)) };
      bySlug(s).forEach(function (e) { paint(e, cache[s]); });
      post(encodeURIComponent(s) + '/fav', { id: id, on: on }).then(function (r) {
        if (r.on) favs[s] = 1; else delete favs[s];
        cache[s] = { v: r.v, f: r.f };
      }).catch(function () {
        if (on) delete favs[s]; else favs[s] = 1;
        cache[s] = d;
      }).then(function () {
        set('ark-favs', JSON.stringify(favs));
        bySlug(s).forEach(function (e) { paint(e, cache[s]); });
        shared();
        btn.disabled = false;
      });
    });
  });
  function go() {
    var mine = els.filter(function (e) { return e.hasAttribute('data-count'); })[0];
    var load = mine
      ? post(encodeURIComponent(mine.getAttribute('data-post')) + '/view').then(function (r) { cache[mine.getAttribute('data-post')] = r; })
      : fetch(API).then(function (r) { if (!r.ok) throw r.status; return r.json(); }).then(function (all) { cache = all || {}; });
    load.then(function () { els.forEach(function (e) { paint(e, cache[e.getAttribute('data-post')]); }); shared(); }).catch(function () {});
  }
  // a page the browser renders ahead of a click is not a view until it is shown
  if (document.prerendering) document.addEventListener('prerenderingchange', go, { once: true });
  else go();
})();
