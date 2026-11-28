// Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
// "your favorites" (/favorites/, layouts/shortcodes/favorites.html) and the star buttons that feed it: ST. CLAIRE songs
// (layouts/shortcodes/arkndjlmusic.html, [data-fav-song]) and the home video.exe (layouts/partials/home-video.html,
// [data-fav-video]). No login: everything lives in this browser's local storage.
//   ark-favs  {slug: 1}            articles, written by the post star (assets/js/poststats.js; counted by the Worker)
//   ark-favx  {s: {slug: t}, y: {id: {t, n, k, d, at}}, f: {id: {b, k, n, s, i, u, p, at}}}   songs, videos, teams and players
// A share code carries all of it to another browser. Followed teams and players read static/data/favs/<sport>.json
// (scripts/favorites_track.py): ARK Ranking, record, the last result, the next game, and the player's board numbers.
(function () {
  if (window.arkFav) return;
  var KEY = 'ark-favx', AKEY = 'ark-favs';
  function get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function put(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  function parse(s) { try { return JSON.parse(s || '{}') || {}; } catch (e) { return {}; } }
  function read() { var o = parse(get(KEY)); o.s = o.s || {}; o.y = o.y || {}; o.f = o.f || {}; return o; }
  var st = read(), subs = [];
  function fire() { subs.forEach(function (f) { f(); }); }
  function save() { put(KEY, JSON.stringify(st)); fire(); }
  window.addEventListener('storage', function (e) { if (e.key === KEY || e.key === AKEY) { st = read(); fire(); } });
  function now() { return Date.now(); }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function slug(s) { return String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''); }
  function vid() {   // the browser's own random id, the same one the post star sends (assets/js/poststats.js)
    var id = get('ark-vid');
    if (!/^[a-f0-9]{16,32}$/.test(id || '')) {
      var b = new Uint8Array(12); (window.crypto && crypto.getRandomValues) ? crypto.getRandomValues(b) : b.forEach(function (_, i) { b[i] = Math.random() * 256; });
      id = [].map.call(b, function (x) { return ('0' + x.toString(16)).slice(-2); }).join(''); put('ark-vid', id);
    }
    return id;
  }
  var api = window.arkFav = {
    on: function (f) { subs.push(f); },
    song: function (s) { return !!st.s[s]; },
    video: function (id) { return !!st.y[id]; },
    item: function (id) { return !!st.f[id]; },
    articles: function () { return parse(get(AKEY)); },
    toggleSong: function (s) { if (st.s[s]) delete st.s[s]; else st.s[s] = now(); save(); return !!st.s[s]; },
    toggleVideo: function (id, m) { if (st.y[id]) delete st.y[id]; else st.y[id] = { t: m.t, n: m.n, k: m.k, d: m.d, at: now() }; save(); return !!st.y[id]; },
    toggleItem: function (id, m) { if (st.f[id]) delete st.f[id]; else { m.at = now(); st.f[id] = m; } save(); return !!st.f[id]; },
    // an article: the same call the post star makes, so the article's count stays right
    toggleArticle: function (s, on) {
      var a = api.articles(); if (on) a[s] = 1; else delete a[s]; put(AKEY, JSON.stringify(a)); fire();
      return fetch('/api/posts/' + encodeURIComponent(s) + '/fav', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ id: vid(), on: on }) })
        .then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; });
    },
    state: function () { return st; }
  };
  function itemId(m) { return [m.b, m.k, m.n, m.p || m.s].join('|'); }
  api.itemId = itemId;

  // ---- share code: "ARK1-" + base64url(JSON) ----
  function b64(s) { var u = new TextEncoder().encode(s), b = ''; u.forEach(function (x) { b += String.fromCharCode(x); }); return btoa(b).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, ''); }
  function unb64(s) { s = s.replace(/-/g, '+').replace(/_/g, '/'); while (s.length % 4) s += '='; var b = atob(s), u = new Uint8Array(b.length); for (var i = 0; i < b.length; i++) u[i] = b.charCodeAt(i); return new TextDecoder().decode(u); }
  api.code = function () {
    var o = { a: Object.keys(api.articles()), s: Object.keys(st.s), y: [], f: [] };
    Object.keys(st.y).forEach(function (id) { var v = st.y[id]; o.y.push([id, v.t || '', v.n || '', v.k || '', v.d || '']); });
    Object.keys(st.f).forEach(function (id) { var v = st.f[id]; o.f.push([v.b, v.k, v.n, v.s || '', v.i || '', v.u || '', v.p || '']); });
    return 'ARK1-' + b64(JSON.stringify(o));
  };
  api.load = function (code) {   // merges; returns how many were new, or -1 for a code that does not read
    var m = /ARK1-([A-Za-z0-9_-]+)/.exec(String(code || '')), o;
    if (!m) return -1;
    try { o = JSON.parse(unb64(m[1])); } catch (e) { return -1; }
    var n = 0, t = now(), arts = api.articles(), newArts = [];
    (o.s || []).forEach(function (s) { if (typeof s === 'string' && !st.s[s]) { st.s[s] = t; n++; } });
    (o.y || []).forEach(function (r) { if (r && /^[\w-]{6,20}$/.test(r[0]) && !st.y[r[0]]) { st.y[r[0]] = { t: r[1], n: r[2], k: r[3], d: r[4], at: t }; n++; } });
    (o.f || []).forEach(function (r) {
      if (!r || !r[0] || !r[2] || (r[1] !== 'p' && r[1] !== 't')) return;
      var v = { b: r[0], k: r[1], n: r[2], s: r[3], i: r[4], u: /^\/(?![/\\])/.test(r[5] || '') ? r[5] : '', p: r[6], at: t }, id = itemId(v);
      if (!st.f[id]) { st.f[id] = v; n++; }
    });
    (o.a || []).forEach(function (s) { if (typeof s === 'string' && /^[\w.-]+$/.test(s) && !arts[s]) { newArts.push(s); n++; } });
    save();
    newArts.forEach(function (s) { api.toggleArticle(s, true); });
    return n;
  };

  // ---- the star button (songs, videos, cards): .favb, pressed when saved ----
  function paintBtn(b, on, name) {
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
    b.classList.toggle('is-on', on);
    b.title = on ? 'remove from your favs' : 'add to your favs';
    b.setAttribute('aria-label', (on ? 'remove ' : 'favorite ') + (name || ''));
  }
  api.paintBtn = paintBtn;

  // songs on the ST. CLAIRE music page
  function songs() {
    var bs = [].slice.call(document.querySelectorAll('[data-fav-song]')); if (!bs.length) return;
    function paint() { bs.forEach(function (b) { paintBtn(b, api.song(b.getAttribute('data-fav-song')), b.getAttribute('data-name')); }); }
    bs.forEach(function (b) { b.addEventListener('click', function (e) { e.stopPropagation(); api.toggleSong(b.getAttribute('data-fav-song')); }); });
    api.on(paint); paint();
  }
  // the home video.exe: the star saves the video on screen; saved rows in the list carry a small star
  function videos() {
    var w = document.getElementById('video'), b = w && w.querySelector('[data-fav-video]'); if (!b) return;
    function cur() { return w.querySelector('.hvid__list a.is-on') || w.querySelector('.hvid__list a[data-vid]'); }
    function paint() {
      var a = cur(); if (!a) return;
      paintBtn(b, api.video(a.getAttribute('data-vid')), (a.querySelector('.hvid__t') || {}).textContent);
      w.querySelectorAll('.hvid__list a[data-vid]').forEach(function (x) { x.classList.toggle('is-fav', api.video(x.getAttribute('data-vid'))); });
    }
    b.addEventListener('click', function () {
      var a = cur(); if (!a) return;
      api.toggleVideo(a.getAttribute('data-vid'), { t: (a.querySelector('.hvid__t') || {}).textContent || '', n: a.getAttribute('data-n'), k: a.getAttribute('data-k'), d: a.getAttribute('data-d') });
    });
    // the list and the transport move the current video: repaint after they run
    w.addEventListener('click', function () { setTimeout(paint, 0); });
    w.addEventListener('hvid:load', paint);   // a track change with no click (auto-advance)
    new MutationObserver(function () { paint(); }).observe(w.querySelector('.hvid__list'), { subtree: true, attributes: true, attributeFilter: ['class'] });
    api.on(paint); paint();
  }

  // ---- the favorites page ----
  var SPORT = { 'arkboard-college-football': ['cfb', 'CFB'], 'arkboard-college-basketball': ['cbb', 'CBB'], 'arkboard-nfl': ['nfl', 'NFL'], 'arkboard-nba': ['nba', 'NBA'],
    'arkboard-nhl': ['nhl', 'NHL'], 'arkboard-soccer': ['soccer', 'soccer'], 'arkboard-soccer-prospects': ['socp', 'soccer prospects'],
    'arkboard-hockey-prospects': ['hkp', 'hockey prospects'], 'arkboard-tennis': ['tennis', 'tennis'], 'arkboard-tennis-prospects': ['tnp', 'tennis prospects'],
    'arkboard-counter-strike': ['cs2', 'CS2'], 'arkboard-baseball': ['', 'baseball'] };
  function shard(k, n) { var h = 0; for (var i = 0; i < k.length; i++) h = (Math.imul(h, 31) + k.charCodeAt(i)) >>> 0; return h % n; }
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function day(d) { var m = /^(\d{4})-(\d\d)-(\d\d)/.exec(d || ''); return m ? MON[+m[2] - 1] + ' ' + (+m[3]) : (d || ''); }
  function today() { var d = new Date(); return d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2) + '-' + ('0' + d.getDate()).slice(-2); }
  function starBtn(attrs, on, name) {
    return '<button type="button" class="favb' + (on ? ' is-on' : '') + '" ' + attrs + ' aria-pressed="' + on + '" title="' + (on ? 'remove from your favs' : 'add to your favs') + '" aria-label="' + (on ? 'remove ' : 'favorite ') + esc(name) + '"><i></i></button>';
  }

  function page(root) {
    var D = {}; try { D = JSON.parse(root.querySelector('[data-fv-data]').textContent); } catch (e) {}
    var BASE = root.getAttribute('data-base'), VER = D.ver || {}, POSTS = D.posts || {}, SONGS = D.songs || {};
    var out = root.querySelector('[data-fv-out]'), chips = root.querySelector('[data-fv-chips]'), lp = root.querySelector('[data-lowpoly]');
    var only = 'all', files = {}, ghosts = { teams: {}, players: {}, articles: {}, songs: {}, videos: {} };
    try { var h = /^#(teams|players|articles|songs|videos)$/.exec(location.hash); if (h) only = h[1]; } catch (e) {}

    function file(name) {
      if (!files[name]) files[name] = fetch(BASE + name + '.json' + (VER[name] ? '?v=' + VER[name] : '')).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; });
      return files[name];
    }
    function track(m) {   // -> Promise of {team, player, file}
      var sp = (SPORT[m.b] || [''])[0]; if (!sp) return Promise.resolve(null);
      return file(sp).then(function (F) {
        if (!F) return null;
        var key = slug(m.n);
        if (m.k === 't') return { team: (F.t || {})[key], F: F };
        var got = F.ps > 1 ? file(sp + '-p' + shard(key, F.ps)) : Promise.resolve(F);
        return got.then(function (P) {
          // the saved line is "POS · Team · Page": the row whose team is one of its parts (same-name players stay apart)
          var rows = ((P || {}).p || {})[key] || [], parts = String(m.s || '').toLowerCase().split(' · '), r = null;
          rows.forEach(function (x) { if (!r && parts.indexOf(String(x[0]).toLowerCase()) >= 0) r = x; });
          if (!r && rows.length === 1) r = rows[0];
          return { player: r, team: r && r[2] ? (F.t || {})[r[2]] : null, F: F };
        });
      });
    }

    function games(t, isTeam) {
      if (!t) return '';
      var h = '', sch = t.sch || [], td = today(), last = null, next = null;
      sch.forEach(function (r) {
        var dated = /^\d{4}-/.test(r[0]);
        if (r[3] != null) { if (!dated || r[0] <= td) last = r; }
        else if (!next && (!dated || r[0] >= td)) next = r;
      });
      function opp(r) { return (r[2] === '@' ? '@ ' : 'vs ') + esc(r[1]); }
      if (last) {
        var res = last[3] > last[4] ? 'W' : last[3] < last[4] ? 'L' : 'D';
        h += '<div class="fv__g"><span class="fv__gk">last</span><b class="fv__res fv__res--' + res + '">' + res + ' ' + last[3] + '-' + last[4] + '</b><span class="fv__go">' + opp(last) + '</span><span class="fv__gd">' + esc(day(last[0])) + '</span></div>';
      }
      if (next) h += '<div class="fv__g"><span class="fv__gk">next</span><span class="fv__go">' + opp(next) + '</span><span class="fv__gd">' + esc(day(next[0])) + '</span>' + (next[5] != null ? '<b class="fv__pw" title="chance to win">' + Math.round(next[5] * 100) + '%</b>' : '') + '</div>';
      if (!last && !next && t.last) h += '<div class="fv__g"><span class="fv__gk">last</span><span class="fv__go">' + esc(day(t.last)) + '</span></div>';
      if (!isTeam && h) h = '<div class="fv__gt">' + esc(t.n) + '</div>' + h;
      return h;
    }
    function chipRow(cs) {
      return cs && cs.length ? '<div class="fv__cs">' + cs.map(function (c) {
        if (c[0] === 'form') return '<span class="fv__c fv__c--form" data-term="form"><i>form</i><b>' + String(c[1]).split('').map(function (x) { return '<em class="fv__f' + x + '">' + x + '</em>'; }).join('') + '</b></span>';
        return '<span class="fv__c"><i data-term="' + esc(c[0]) + '">' + esc(c[0]) + '</i><b>' + esc(c[1]) + '</b></span>';
      }).join('') + '</div>' : '';
    }
    function img(src, cls) { return src ? '<img class="' + cls + '" src="' + esc(src) + '" alt="" width="40" height="40" loading="lazy" onerror="this.style.visibility=\'hidden\'">' : '<span class="' + cls + ' fv__noimg" aria-hidden="true"></span>'; }

    function itemCard(id, m, gone) {
      var sp = SPORT[m.b] || ['', ''];
      return '<article class="fv__card fv__card--' + (m.k === 't' ? 'team' : 'player') + (gone ? ' is-gone' : '') + '" data-id="' + esc(id) + '">' +
        '<div class="fv__ch">' + img(m.i, 'fv__logo') + '<div class="fv__nm"><a href="' + esc(m.u || '#') + '">' + esc(m.n) + '</a><span class="fv__sub">' + esc(m.s) + '</span></div>' +
        starBtn('data-fv-item="' + esc(id) + '"', !gone, m.n) + '</div>' +
        '<div class="fv__tr" data-tr><span class="fv__wait">' + (sp[0] ? '…' : '') + '</span></div></article>';
    }
    function fillTrack(card, m) {
      track(m).then(function (r) {
        var box = card.querySelector('[data-tr]'); if (!box) return;
        if (!r || (!r.team && !r.player)) { box.innerHTML = ''; return; }
        var h = '';
        if (m.k === 't') {
          var t = r.team;
          h += '<div class="fv__rk">' + (t.rk ? '<span class="fv__rkn" data-term="ARK Ranking">#' + t.rk + '</span>' : '') + (t.rec ? '<span class="fv__rec">' + esc(t.rec) + '</span>' : '') + '</div>';
          h += chipRow(t.c) + games(t, true);
        } else h += chipRow(r.player && r.player[1]) + games(r.team, false);
        box.innerHTML = h;
        if (r.F && r.F.asof) asof(r.F.asof);
      });
    }
    var newest = '';
    function asof(a) { if (a > newest) { newest = a; var d = new Date(a); root.querySelector('[data-fv-asof]').textContent = isNaN(d) ? a : 'updated ' + MON[d.getMonth()] + ' ' + d.getDate() + ' ' + d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }); } }

    function articleCard(s, gone) {
      var p = POSTS[s]; if (!p) return '';
      return '<article class="fv__card fv__card--art' + (gone ? ' is-gone' : '') + '"><div class="fv__ch"><span class="fv__ax" aria-hidden="true"></span><div class="fv__nm"><a href="' + esc(p[2]) + '">' + esc(p[0]) + '</a><span class="fv__sub">' + esc(p[1]) + '</span></div>' +
        starBtn('data-fv-art="' + esc(s) + '"', !gone, p[0]) + '</div></article>';
    }
    function songCard(s, gone) {
      var t = SONGS[s]; if (!t) return '';
      return '<article class="fv__card fv__card--song' + (gone ? ' is-gone' : '') + '"><div class="fv__ch"><button type="button" class="fv__play" data-fv-play="' + esc(s) + '" aria-label="play ' + esc(t.t) + '"><svg aria-hidden="true"><use href="#icon-play"/></svg></button>' +
        '<div class="fv__nm"><a href="' + esc(root.getAttribute('data-music')) + '">' + esc(t.t) + '</a><span class="fv__sub">ARKNDJL<span class="fv__dur" data-fv-dur="' + esc(s) + '"></span></span></div>' +
        (t.sc ? '<a class="fv__ext" href="' + esc(t.sc) + '" target="_blank" rel="noopener" aria-label="' + esc(t.t) + ' on SoundCloud"><svg aria-hidden="true"><use href="#icon-soundcloud"/></svg></a>' : '') +
        starBtn('data-fv-song="' + esc(s) + '"', !gone, t.t) + '</div><i class="fv__bar" data-fv-bar="' + esc(s) + '"></i></article>';
    }
    function videoCard(id, v, gone) {
      return '<article class="fv__card fv__card--vid' + (gone ? ' is-gone' : '') + '"><a class="fv__thumb" href="https://www.youtube.com/watch?v=' + esc(id) + '" target="_blank" rel="noopener"><img src="https://i.ytimg.com/vi/' + esc(id) + '/mqdefault.jpg" alt="" width="320" height="180" loading="lazy"><svg aria-hidden="true"><use href="#icon-play"/></svg></a>' +
        '<div class="fv__ch"><div class="fv__nm"><a href="https://www.youtube.com/watch?v=' + esc(id) + '" target="_blank" rel="noopener">' + esc(v.t) + '</a><span class="fv__sub">' + (v.k ? '<b class="hvid__ch hvid__ch--' + esc(v.k) + '">' + esc(v.n) + '</b> ' : '') + esc(v.d || '') + '</span></div>' +
        starBtn('data-fv-vid="' + esc(id) + '"', !gone, v.t) + '</div></article>';
    }

    function byAt(o) { return Object.keys(o).sort(function (a, b) { return ((o[b] && o[b].at) || o[b] || 0) - ((o[a] && o[a].at) || o[a] || 0); }); }
    function lists() {
      var f = st.f, arts = api.articles();
      var teams = byAt(f).filter(function (id) { return f[id].k === 't'; }), players = byAt(f).filter(function (id) { return f[id].k === 'p'; });
      return {
        teams: teams, players: players,
        articles: Object.keys(arts).filter(function (s) { return POSTS[s]; }).sort(function (a, b) { return POSTS[a][3] < POSTS[b][3] ? 1 : -1; }),
        songs: byAt(st.s).filter(function (s) { return SONGS[s]; }), videos: byAt(st.y)
      };
    }
    var drawn = {};
    function draw() {
      var L = lists(), total = 0;
      ['teams', 'players', 'articles', 'songs', 'videos'].forEach(function (g) {
        var ids = L[g], n = ids.length; total += n;
        Object.keys(ghosts[g]).forEach(function (id) { if (ids.indexOf(id) < 0) ids = ids.concat(id); else delete ghosts[g][id]; });
        var sec = out.querySelector('[data-grp="' + g + '"]'), cards = sec.querySelector('[data-cards]');
        root.querySelector('[data-fv-counts] [data-g="' + g + '"] dd').textContent = n;
        chips.querySelector('[data-g="' + g + '"] b').textContent = n;
        sec.querySelector('[data-gn]').textContent = n + (n === 1 ? ' ' + g.replace(/s$/, '') : ' ' + g);
        sec.hidden = !(ids.length && (only === 'all' || only === g));
        var sig = ids.join('\n') + '#' + Object.keys(ghosts[g]).join(',');
        if (drawn[g] === sig) return;
        drawn[g] = sig;
        cards.innerHTML = ids.map(function (id) {
          var gone = !!ghosts[g][id];
          if (g === 'teams' || g === 'players') return itemCard(id, gone ? ghosts[g][id] : st.f[id], gone);
          if (g === 'articles') return articleCard(id, gone);
          if (g === 'songs') return songCard(id, gone);
          return videoCard(id, gone ? ghosts[g][id] : st.y[id], gone);
        }).join('');
        if (g === 'teams' || g === 'players') cards.querySelectorAll('.fv__card').forEach(function (c) { var id = c.getAttribute('data-id'); fillTrack(c, st.f[id] || ghosts[g][id]); });
        if (g === 'songs') durations(cards);
      });
      chips.querySelector('[data-g="all"] b').textContent = total;
      root.querySelector('[data-fv-none]').hidden = !!total;
      var on = only === 'all' ? 'favs' : only;
      if (lp) lp.setAttribute('data-lp-model', on);
    }
    // a star taken back stays on the page, unpressed, until the next visit: one more click puts it back
    out.addEventListener('click', function (e) {
      var b = e.target.closest('.favb'); if (!b) return;
      var id;
      if ((id = b.getAttribute('data-fv-item'))) {
        var m = st.f[id] || ghosts.teams[id] || ghosts.players[id], g = m.k === 't' ? 'teams' : 'players';
        if (st.f[id]) ghosts[g][id] = m; else delete ghosts[g][id];
        api.toggleItem(id, m);
      } else if ((id = b.getAttribute('data-fv-art'))) {
        var on = !api.articles()[id]; if (!on) ghosts.articles[id] = 1; else delete ghosts.articles[id];
        api.toggleArticle(id, on);
      } else if ((id = b.getAttribute('data-fv-song'))) {
        if (st.s[id]) ghosts.songs[id] = 1; else delete ghosts.songs[id];
        api.toggleSong(id);
      } else if ((id = b.getAttribute('data-fv-vid'))) {
        var v = st.y[id] || ghosts.videos[id]; if (st.y[id]) ghosts.videos[id] = v; else delete ghosts.videos[id];
        api.toggleVideo(id, v);
      }
    });
    chips.addEventListener('click', function (e) {
      var b = e.target.closest('[data-g]'); if (!b) return;
      only = b.getAttribute('data-g');
      chips.querySelectorAll('[data-g]').forEach(function (x) { var on = x === b; x.classList.toggle('is-on', on); x.setAttribute('aria-selected', on); });
      try { history.replaceState(null, '', only === 'all' ? location.pathname : '#' + only); } catch (x) {}
      drawn = {}; draw();
    });
    chips.querySelectorAll('[data-g]').forEach(function (x) { var on = x.getAttribute('data-g') === only; x.classList.toggle('is-on', on); x.setAttribute('aria-selected', on); });

    // songs play here; a play start counts like one on the music page (the Worker keeps one a visitor a song in 10 minutes)
    var audio = null, playing = '';
    function durations(cards) {
      cards.querySelectorAll('[data-fv-dur]').forEach(function (el) {
        var s = el.getAttribute('data-fv-dur'), a = new Audio(); a.preload = 'metadata'; a.src = SONGS[s].src;
        a.addEventListener('loadedmetadata', function () { var t = Math.round(a.duration); el.textContent = ' · ' + Math.floor(t / 60) + ':' + ('0' + t % 60).slice(-2); });
      });
    }
    function paintPlay() {
      out.querySelectorAll('[data-fv-play]').forEach(function (b) {
        var on = b.getAttribute('data-fv-play') === playing && audio && !audio.paused;
        b.querySelector('use').setAttribute('href', on ? '#icon-pause' : '#icon-play'); b.classList.toggle('is-on', on);
        b.setAttribute('aria-label', (on ? 'pause ' : 'play ') + (SONGS[b.getAttribute('data-fv-play')] || {}).t);
      });
    }
    out.addEventListener('click', function (e) {
      var b = e.target.closest('[data-fv-play]'); if (!b) return;
      var s = b.getAttribute('data-fv-play');
      if (!audio) {
        audio = new Audio();
        ['play', 'pause', 'ended'].forEach(function (ev) { audio.addEventListener(ev, paintPlay); });
        audio.addEventListener('timeupdate', function () { var bar = out.querySelector('[data-fv-bar="' + playing + '"]'); if (bar && audio.duration) bar.style.width = (audio.currentTime / audio.duration * 100) + '%'; });
      }
      if (playing === s && !audio.paused) { audio.pause(); return; }
      if (playing !== s) {
        out.querySelectorAll('[data-fv-bar]').forEach(function (x) { x.style.width = '0'; });
        playing = s; audio.src = SONGS[s].src;
        fetch('/api/plays/' + encodeURIComponent(s), { method: 'POST', keepalive: true }).catch(function () {});
      }
      audio.play().catch(function () {});
    });

    // ---- add: the site search over every board's players and teams ----
    var q = root.querySelector('[data-fv-q]'), drop = root.querySelector('[data-fv-drop]'), hits = [], sel = -1, timer, shown = '';
    function closeDrop() { drop.hidden = true; sel = -1; q.setAttribute('aria-expanded', 'false'); }
    function meta(it) { return { b: it.x.b, k: it.g, n: it.t, s: it.s, i: it.i || '', u: it.u, p: it.x.pid || '' }; }
    function drawDrop() {
      var v = q.value.trim();
      if (!v) { closeDrop(); return Promise.resolve(); }
      if (!window.arkSearch) { drop.innerHTML = '<span class="srch__none">…</span>'; drop.hidden = false; return Promise.resolve(); }
      shown = '';
      return window.arkSearch.load().then(function () {
        if (q.value.trim() !== v) return;
        hits = window.arkSearch.find(v).filter(function (h) { return (h[1].g === 'p' || h[1].g === 't') && h[1].x; }).slice(0, 8).map(function (h) { return h[1]; });
        drop.innerHTML = hits.length ? hits.map(function (it, i) {
          var m = meta(it), id = itemId(m), on = api.item(id);
          return '<div class="fv__hit' + (i === sel ? ' is-sel' : '') + (on ? ' is-on' : '') + '" role="option" aria-selected="' + on + '" data-i="' + i + '">' +
            (it.i ? '<img class="srch__img" src="' + esc(it.i) + '" alt="" width="24" height="24" loading="lazy">' : '<svg class="srch__ico" aria-hidden="true"><use href="#icon-' + (it.g === 't' ? 'standings' : 'pointer') + '"/></svg>') +
            '<span class="srch__txt"><span class="srch__t">' + esc(it.t) + '</span><span class="srch__s">' + esc(it.s) + '</span></span><span class="srch__g">' + (it.g === 't' ? 'team' : 'player') + '</span>' +
            starBtn('tabindex="-1"', on, it.t) + '</div>';
        }).join('') : '<span class="srch__none">0 results</span>';
        drop.hidden = false; q.setAttribute('aria-expanded', 'true'); shown = v;
      }).catch(function () { drop.innerHTML = '<span class="srch__none">load failed</span>'; drop.hidden = false; });
    }
    function pick(i) {
      var it = hits[i]; if (!it) return;
      var m = meta(it), id = itemId(m), g = m.k === 't' ? 'teams' : 'players';
      delete ghosts[g][id];
      api.toggleItem(id, m); drawDrop();
    }
    q.addEventListener('input', function () { sel = -1; clearTimeout(timer); timer = setTimeout(drawDrop, 70); });
    q.addEventListener('focus', function () { if (window.arkSearch) window.arkSearch.load(); if (q.value) drawDrop(); });
    q.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); if (!hits.length) return; sel = (sel + (e.key === 'ArrowDown' ? 1 : -1) + hits.length) % hits.length; drop.querySelectorAll('.fv__hit').forEach(function (r, i) { r.classList.toggle('is-sel', i === sel); }); }
      else if (e.key === 'Enter') {   // the list for what is typed now, not the one a keystroke ago
        e.preventDefault(); clearTimeout(timer);
        if (shown === q.value.trim()) pick(sel < 0 ? 0 : sel); else { var p0 = drawDrop(); if (p0) p0.then(function () { pick(0); }); }
      }
      else if (e.key === 'Escape') closeDrop();
    });
    drop.addEventListener('mousedown', function (e) { e.preventDefault(); });
    drop.addEventListener('click', function (e) { var r = e.target.closest('[data-i]'); if (r) pick(+r.getAttribute('data-i')); });
    document.addEventListener('click', function (e) { if (!root.querySelector('.fv__find').contains(e.target)) closeDrop(); });

    // ---- share code ----
    var codeBox = root.querySelector('[data-fv-code]'), text = root.querySelector('[data-fv-text]'), msg = root.querySelector('[data-fv-msg]'), mode = '';
    function openCode(m, v) {
      mode = m; codeBox.hidden = false; codeBox.setAttribute('data-mode', m); msg.textContent = '';
      text.value = v || ''; text.readOnly = m === 'export';
      if (m === 'export') text.select(); else text.focus();
    }
    function copy(s) { (navigator.clipboard ? navigator.clipboard.writeText(s) : Promise.reject()).then(function () { msg.textContent = 'copied'; }, function () { text.select(); msg.textContent = 'select and copy'; }); }
    root.querySelector('.fv__head').addEventListener('click', function (e) {
      var b = e.target.closest('[data-fv-act]'); if (!b) return;
      var a = b.getAttribute('data-fv-act');
      if (a === 'export') openCode('export', api.code());
      else if (a === 'import') openCode('import', '');
      else if (a === 'close') { codeBox.hidden = true; mode = ''; }
      else if (a === 'copy') copy(text.value);
      else if (a === 'link') copy(location.origin + location.pathname + '#code=' + (mode === 'export' ? text.value : api.code()));
      else if (a === 'add') { var n = api.load(text.value); msg.textContent = n < 0 ? 'code not read' : n + ' added'; }
    });
    var hc = /[#&]code=(ARK1-[A-Za-z0-9_-]+)/.exec(location.hash);
    if (hc) { openCode('import', hc[1]); try { history.replaceState(null, '', location.pathname); } catch (x) {} }

    api.on(function () { draw(); paintPlay(); });
    draw();
  }

  function init() {
    songs(); videos();
    var p = document.querySelector('[data-favs]'); if (p) page(p);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
