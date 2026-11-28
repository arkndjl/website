// ARKLOG (layouts/shortcodes/arklog.html): rows from /data/arklog.json (scripts/arklog.py).
// Chips filter by verdict, site section, sport and area; the find box by words; a row opens to the numbered lines of its record.
// "#log-<n>" opens the log tab and that row, "#log:<sport>" the sport's rows. The windows sit in a lazy tab, so setup
// runs at load and again on "ark:lazy".
(function () {
  if (window.__arkLog) return; window.__arkLog = true;
  var VL = { s: 'shipped', m: 'part shipped', f: 'failed', w: 'weak evidence', study: 'study' };
  var AR = { fv: 'FV', value: 'player value', players: 'player odds', teams: 'team ratings', games: 'game models', drafts: 'drafts and mocks', data: 'data', site: 'site', research: 'research' };
  var PAGE = 60, data = null, loading = null;
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function day(d) { try { return new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'America/New_York' }); } catch (e) { return d.slice(5, 10); } }
  function stamp(d) { try { return new Date(d).toLocaleString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York' }) + ' ET'; } catch (e) { return d; } }
  function eff(r) { return r.k === 'study' ? (r.a || '') : (r.x || ''); }
  function key(r) { return r.k === 'study' || r.k === 'content' ? r.id : String(r.n); }
  function load(src) {
    if (!loading) loading = fetch(src).then(function (x) { if (!x.ok) throw x.status; return x.json(); }).then(function (j) {
      data = j.rows || [];
      data.forEach(function (r) { r._h = (r.t + ' ' + (r.sec || '') + ' ' + (r.sp || []).join(' ') + ' ' + (AR[r.ar] || '') + ' ' + (r.a || '') + ' ' + (r.l || []).map(function (x) { return x[1]; }).join(' ')).toLowerCase(); });
      return data;
    });
    return loading;
  }
  function setup(win) {
    if (win.__pl) return; win.__pl = true;
    var list = win.querySelector('[data-pl-rows]'), q = win.querySelector('[data-pl-q]'), more = win.querySelector('[data-pl-more]'), count = win.querySelector('[data-pl-count]');
    var st = { v: 't', mo: '', sec: '', sp: '', ar: '', n: PAGE, open: null }, repo = win.getAttribute('data-repo');
    function match(r) {
      var test = r.k !== 'study' && (r.v === 's' || r.v === 'm' || r.v === 'f');
      if (st.v === 't' && !test) return false;
      if ((st.v === 's' || st.v === 'm' || st.v === 'f') && !(test && r.v === st.v)) return false;
      if (st.v === 'study' && r.k !== 'study') return false;
      if (st.v === 'o' && (test || r.k === 'study' || r.k === 'content')) return false;
      if (st.v === 'c' && r.k !== 'content') return false;
      if (st.mo && r.d.slice(0, 7) !== st.mo) return false;
      if (st.sec && r.sec !== st.sec) return false;
      if (st.sp && (r.sp || []).indexOf(st.sp) < 0) return false;
      if (st.ar && r.ar !== st.ar) return false;
      var s = q.value.trim().toLowerCase();
      return !s || s.split(/\s+/).every(function (w) { return r._h.indexOf(w) !== -1; });
    }
    function card(r) {   // what the 16:9 card draws (gfx.js buildLog)
      return { n: r.n, id: r.id, k: r.k, t: r.t, d: stamp(r.d), sec: r.sec || '', sp: r.sp || [], ar: AR[r.ar] || '', v: r.v, e: r.e, tt: r.tt, x: r.x, a: r.a,
        l: (r.l || []).slice(0, 4) };
    }
    function row(r) {
      var study = r.k === 'study', li = el('li', 'plrow plrow--' + (study ? 'study' : r.k === 'content' ? 'content' : r.v || 'o')); li.id = 'log-' + key(r);
      var b = el('button', 'plrow__head'); b.type = 'button'; b.setAttribute('aria-expanded', 'false');
      b.appendChild(el('span', 'plrow__date', day(r.d)));
      var tg = el('span', 'plrow__tags'); (r.sp && r.sp.length ? r.sp : r.sec && r.sec !== 'ARKBOARD' ? [r.sec] : []).slice(0, 4).forEach(function (s) { tg.appendChild(el('i', '', s)); }); b.appendChild(tg);
      b.appendChild(el('span', 'plrow__title', r.t));
      b.appendChild(el('span', 'plrow__eff' + (r.e && r.e[3] === 0 ? ' is-down' : ''), eff(r)));
      b.appendChild(el('span', 'plrow__v', r.k === 'content' ? r.c : study ? (r.v === 'w' ? 'study · weak' : 'study') : VL[r.v] || (r.sec && r.sec !== 'ARKBOARD' ? r.sec : AR[r.ar]) || ''));
      li.appendChild(b);
      b.addEventListener('click', function () { toggle(li, r); });
      return li;
    }
    function toggle(li, r, force) {
      var b = li.querySelector('.plrow__head'), box = li.querySelector('.plrow__more'), on = force != null ? force : b.getAttribute('aria-expanded') !== 'true';
      b.setAttribute('aria-expanded', on ? 'true' : 'false'); li.classList.toggle('is-open', on);
      if (!on) { if (box) box.hidden = true; return; }
      if (!box) {
        box = el('div', 'plrow__more');
        var meta = el('p', 'plrow__meta', stamp(r.d) + (r.sec ? ' · ' + r.sec : '') + (AR[r.ar] && r.sec === 'ARKBOARD' ? ' · ' + AR[r.ar] : '') + (r.k === 'study' && r.nn ? ' · n ' + Number(r.nn).toLocaleString('en-US') : ''));
        box.appendChild(meta);
        if (r.l && r.l.length) {
          var ul = el('ul', 'plrow__lines');
          r.l.forEach(function (x) { var i = el('li', x[0] ? 'is-' + x[0] : '', x[1]); if (x[0]) i.setAttribute('data-v', VL[x[0]]); ul.appendChild(i); });
          box.appendChild(ul);
        }
        var bar = el('p', 'rq__bar libstudy__bar');
        var g = el('button', 'cfb__btn', 'GFX card'); g.type = 'button'; g.setAttribute('data-gfx', ''); g.setAttribute('data-gfx-mode', 'log'); g.setAttribute('data-gfx-log', JSON.stringify(card(r))); g.title = 'log card PNG, 16:9 for X';
        bar.appendChild(g);
        var a = el('a', 'cfb__btn rq__link', 'link'); a.href = '#log-' + key(r); bar.appendChild(a);
        if (r.k === 'study') { var s = el('a', 'cfb__btn rq__link', 'study'); s.href = '#rq-' + r.id; bar.appendChild(s); }
        if (r.u) { var o = el('a', 'cfb__btn rq__link', r.c === 'article' ? 'read' : r.c === 'match' ? 'match room' : r.c === 'release' ? 'listen' : 'watch'); o.href = r.u; if (!/^\//.test(r.u)) { o.target = '_blank'; o.rel = 'noopener'; } bar.appendChild(o); }
        if (r.rec && repo) { var rc = el('a', 'cfb__btn rq__link', 'research record'); rc.href = repo + '/tree/main/scripts/research/' + r.rec; rc.target = '_blank'; rc.rel = 'noopener'; bar.appendChild(rc); }
        if (r.n && repo) { var pr = el('a', 'cfb__btn rq__link', '#' + r.n); pr.href = repo + '/pull/' + r.n; pr.target = '_blank'; pr.rel = 'noopener'; pr.title = 'the change on GitHub'; bar.appendChild(pr); }
        box.appendChild(bar); li.appendChild(box);
      }
      box.hidden = false;
    }
    function draw() {
      if (!data) return;
      var hits = data.filter(match); list.innerHTML = '';
      hits.slice(0, st.n).forEach(function (r) { list.appendChild(row(r)); });
      if (!hits.length) list.appendChild(el('li', 'cfb__dim', 'no match.'));
      more.hidden = hits.length <= st.n; more.textContent = 'more (' + (hits.length - st.n) + ')';
      var t = hits.filter(function (r) { return r.k !== 'study' && (r.v === 's' || r.v === 'm' || r.v === 'f'); });
      count.textContent = hits.length.toLocaleString('en-US') + ' rows' + (t.length ? ' · ' + t.filter(function (r) { return r.v === 's'; }).length + ' shipped · ' + t.filter(function (r) { return r.v === 'm'; }).length + ' part · ' + t.filter(function (r) { return r.v === 'f'; }).length + ' failed' : '');
    }
    function chips(sel, attr, k) {
      var box = win.querySelector(sel); if (!box) return;
      box.addEventListener('click', function (e) {
        var b = e.target.closest('.cfb__chip'); if (!b) return;
        st[k] = b.getAttribute(attr); st.n = PAGE;
        [].forEach.call(box.querySelectorAll('.cfb__chip'), function (c) { var on = c === b; c.classList.toggle('is-on', on); c.setAttribute('aria-pressed', on ? 'true' : 'false'); });
        draw();
      });
    }
    function pick(sel, attr, val) { var b = [].filter.call(win.querySelectorAll(sel + ' .cfb__chip'), function (c) { return c.getAttribute(attr) === val; })[0]; if (b && !b.classList.contains('is-on')) b.click(); return !!b; }
    chips('[data-pl-v]', 'data-v', 'v'); chips('[data-pl-sec]', 'data-sec', 'sec'); chips('[data-pl-sp]', 'data-sp', 'sp'); chips('[data-pl-ar]', 'data-ar', 'ar');
    q.addEventListener('input', function () { st.n = PAGE; draw(); });
    var mos = win.querySelector('[data-pl-mo]'); if (mos) mos.addEventListener('change', function () { st.mo = mos.value; st.n = PAGE; draw(); });
    more.addEventListener('click', function () { st.n += PAGE * 2; draw(); });
    // #log-<key>: show that row whatever the chips say; #log:<sport>: that sport's rows
    win.__plGo = function (h) {
      var m = /^log:(.+)$/.exec(h);
      if (m && /^\d{4}-\d{2}$/.test(m[1])) { var mo = win.querySelector('[data-pl-mo]'); if (mo) { mo.value = m[1]; st.mo = mo.value; } pick('[data-pl-v]', 'data-v', ''); st.n = PAGE; draw(); win.scrollIntoView({ block: 'start' }); return; }
      if (m) { pick('[data-pl-v]', 'data-v', 't'); pick('[data-pl-sp]', 'data-sp', m[1]); return; }
      m = /^log-(.+)$/.exec(h); if (!m || !data) return;
      var r = data.filter(function (x) { return key(x) === m[1]; })[0]; if (!r) return;
      if (!match(r)) { q.value = ''; pick('[data-pl-sec]', 'data-sec', ''); pick('[data-pl-sp]', 'data-sp', ''); pick('[data-pl-ar]', 'data-ar', ''); pick('[data-pl-v]', 'data-v', ''); }
      var i = data.filter(match).indexOf(r); if (i >= st.n) { st.n = i + 10; draw(); }
      var li = document.getElementById('log-' + m[1]); if (!li) return;
      toggle(li, r, true); setTimeout(function () { li.scrollIntoView({ block: 'start' }); }, 40);
    };
    load(win.getAttribute('data-proclog')).then(function () { draw(); go(); }).catch(function () { list.innerHTML = ''; list.appendChild(el('li', 'cfb__dim', 'load failed. open the tab again to retry.')); win.__pl = false; loading = null; });
  }
  function hash() { var h = location.hash.slice(1); try { h = decodeURIComponent(h); } catch (e) {} return h; }
  // a log link: open the log tab (its windows load on first open), then hand the hash to the window
  function go() {
    var h = hash(); if (!/^log[-:]/.test(h)) return;
    var win = document.querySelector('[data-proclog]');
    if (!win) {
      var tab = [].filter.call(document.querySelectorAll('[data-wintab]'), function (t) { return t.getAttribute('data-wintab') === 'log'; })[0];
      if (tab && tab.getAttribute('aria-selected') !== 'true') { var keep = location.hash; tab.click(); try { history.replaceState(null, '', keep); } catch (e) {} }
      return;   // setup runs on ark:lazy and calls go() again once the rows are in
    }
    var panel = win.closest('[data-tab]'), tb = panel && [].filter.call(document.querySelectorAll('[data-wintab]'), function (t) { return t.getAttribute('data-wintab') === panel.getAttribute('data-tab'); })[0];
    if (tb && tb.getAttribute('aria-selected') !== 'true') { var k2 = location.hash; tb.click(); try { history.replaceState(null, '', k2); } catch (e) {} }
    if (win.__plGo) win.__plGo(h);
  }
  function init() { [].forEach.call(document.querySelectorAll('[data-proclog]'), setup); }
  document.addEventListener('ark:lazy', init);
  window.addEventListener('hashchange', go);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { init(); setTimeout(go, 80); }); else { init(); setTimeout(go, 80); }
})();
