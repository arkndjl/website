/* Pixel YouTube player. A video starts as a facade (thumbnail + pixel play button, no iframe); a click loads the
   YouTube IFrame API and the player with YouTube's own controls off (controls=0), and the pixel bar under the screen
   drives it: play/pause, time, seek, volume, fullscreen. YouTube's branding inside the player is left as it is.
   Markup: layouts/partials/ytp.html (.ytp). The home video.exe uses YTPix.Player with its own transport. */
(function () {
  var HOST = 'https://www.youtube-nocookie.com', waiting = [], asked = false;
  function api(cb) {
    if (window.YT && window.YT.Player) return cb();
    waiting.push(cb); if (asked) return; asked = true;
    var prev = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = function () { if (prev) try { prev(); } catch (e) {} waiting.splice(0).forEach(function (f) { f(); }); };
    var s = document.createElement('script'); s.src = 'https://www.youtube.com/iframe_api'; s.async = true; document.head.appendChild(s);
  }
  function getVol() { try { var v = JSON.parse(localStorage.getItem('ytpix-vol')); if (v && v.v >= 0) return v; } catch (e) {} return { v: 75, m: false }; }
  function putVol(v) { try { localStorage.setItem('ytpix-vol', JSON.stringify(v)); } catch (e) {} }
  function fmt(s) { if (!isFinite(s) || s < 0) return '-:--'; s = Math.floor(s); var h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, x = ('0' + s % 60).slice(-2); return h ? h + ':' + ('0' + m).slice(-2) + ':' + x : m + ':' + x; }
  function fsEl() { return document.fullscreenElement || document.webkitFullscreenElement || null; }

  /* screen: the 16:9 box holding the facade (.ytp__face). o: onstate(state), ontick(t, d, loaded), onend(), onvol(v) */
  function Player(screen, id, title, o) {
    this.sc = screen; this.id = id; this.title = title || ''; this.o = o || {}; this.p = null; this.ready = false;
    this.s = -1; this.t = 0; this.d = 0; this.vol = getVol(); this.q = null;
    var me = this, face = screen.querySelector('.ytp__face');
    if (face) {
      face.addEventListener('click', function (e) { if (e.metaKey || e.ctrlKey || e.shiftKey) return; e.preventDefault(); me.load(me.id, true); });
      ['pointerenter', 'touchstart', 'focus'].forEach(function (k) { face.addEventListener(k, function () { api(function () {}); }, { passive: true, once: true }); });
    }
  }
  Player.prototype.started = function () { return !!this.p; };
  Player.prototype.load = function (id, auto, title) {
    var me = this; this.id = id; if (title != null) this.title = title;
    this.t = 0; this.d = 0;
    if (!this.p) {
      if (!auto) { this.cue(); return; }
      this.sc.classList.add('is-loading');
      var host = document.createElement('div'); host.className = 'ytp__frame'; this.sc.appendChild(host);
      this.p = 1;
      api(function () {
        me.p = new YT.Player(host, {
          host: HOST, videoId: me.id, width: '100%', height: '100%',
          playerVars: { autoplay: 1, controls: 0, playsinline: 1, rel: 0, iv_load_policy: 3, fs: 0, disablekb: 1, origin: location.origin },
          events: {
            onReady: function () {
              me.ready = true; var f = me.p.getIframe(); f.title = me.title; f.setAttribute('allow', 'autoplay; encrypted-media; picture-in-picture; fullscreen');
              me.setVol(me.vol.v, me.vol.m); if (me.q) { me.load(me.q, true); me.q = null; } else me.p.playVideo();
              var face = me.sc.querySelector('.ytp__face'); if (face) face.remove();
              me.sc.classList.remove('is-loading'); me.sc.classList.add('is-on');
              me.tick(); setInterval(function () { if (me.s === 1 || me.s === 3) me.tick(); }, 250);
            },
            onStateChange: function (e) {
              var was = me.s; me.s = e.data; me.tick();
              if (me.o.onstate) me.o.onstate(me.s);
              if (e.data === 0 && was !== 0 && me.o.onend) me.o.onend();
            }
          }
        });
      });
      return;
    }
    if (!this.ready) { this.q = id; return; }
    this.s = -1;
    if (auto) this.p.loadVideoById(id); else this.p.cueVideoById(id);
    this.p.getIframe().title = this.title; this.tick();
  };
  Player.prototype.cue = function () {
    var img = this.sc.querySelector('.ytp__face img'), a = this.sc.querySelector('.ytp__face');
    if (img) img.src = 'https://i.ytimg.com/vi/' + this.id + '/hqdefault.jpg';
    if (a) { a.href = 'https://www.youtube.com/watch?v=' + this.id; a.setAttribute('aria-label', 'play ' + this.title); }
    if (this.o.ontick) this.o.ontick(0, 0, 0);
  };
  Player.prototype.tick = function () {
    if (!this.ready) return;
    try { this.t = this.p.getCurrentTime() || 0; this.d = this.p.getDuration() || 0; var l = this.p.getVideoLoadedFraction() || 0; } catch (e) { return; }
    if (this.o.ontick) this.o.ontick(this.t, this.d, l);
  };
  Player.prototype.playing = function () { return this.s === 1 || this.s === 3; };
  Player.prototype.play = function () { if (!this.p) this.load(this.id, true); else if (this.ready) this.p.playVideo(); };
  Player.prototype.pause = function () { if (this.ready) this.p.pauseVideo(); };
  Player.prototype.toggle = function () { if (this.playing()) this.pause(); else this.play(); };
  Player.prototype.stop = function () { if (!this.ready) return; this.p.pauseVideo(); this.p.seekTo(0, true); this.t = 0; this.tick(); };
  Player.prototype.seek = function (t) { if (!this.ready || !this.d) return; this.t = Math.max(0, Math.min(this.d, t)); this.p.seekTo(this.t, true); this.tick(); };
  Player.prototype.setVol = function (v, m) {
    this.vol = { v: Math.max(0, Math.min(100, Math.round(v))), m: !!m }; putVol(this.vol);
    if (this.ready) { this.p.setVolume(this.vol.v); if (this.vol.m || !this.vol.v) this.p.mute(); else this.p.unMute(); }
    if (this.o.onvol) this.o.onvol(this.vol);
  };
  Player.prototype.mute = function () { this.setVol(this.vol.v || 50, !(this.vol.m || !this.vol.v)); };
  /* fullscreen on the whole window (screen + controls); phones without element fullscreen get a full-page view */
  Player.full = function (el) {
    if (el.classList.contains('is-max')) { el.classList.remove('is-max'); document.documentElement.classList.remove('ytp-max'); return false; }
    if (fsEl()) { (document.exitFullscreen || document.webkitExitFullscreen).call(document); return false; }
    var rq = el.requestFullscreen || el.webkitRequestFullscreen;
    if (rq) { var r = rq.call(el); if (r && r.catch) r.catch(function () { el.classList.add('is-max'); document.documentElement.classList.add('ytp-max'); }); return true; }
    el.classList.add('is-max'); document.documentElement.classList.add('ytp-max'); return true;
  };
  Player.fmt = fmt; Player.fsEl = fsEl;

  /* a pixel slider: role=slider element, value 0..1 from a pointer x; drag works too */
  function slide(el, cb) {
    function at(x) { var r = el.getBoundingClientRect(); return Math.max(0, Math.min(1, (x - r.left) / r.width)); }
    el.addEventListener('pointerdown', function (e) {
      if (e.button) return; e.preventDefault(); el.focus(); cb(at(e.clientX), false);
      function mv(ev) { cb(at(ev.clientX), true); }
      function up(ev) { document.removeEventListener('pointermove', mv); document.removeEventListener('pointerup', up); cb(at(ev.clientX), false); }
      document.addEventListener('pointermove', mv); document.addEventListener('pointerup', up);
    });
  }
  Player.slide = slide;

  /* a vol meter: 8 stepped blocks */
  function paintVol(el, v) {
    var n = v.m ? 0 : Math.round(v.v / 12.5);
    el.querySelectorAll('i').forEach(function (b, i) { b.classList.toggle('is-on', i < n); });
    el.setAttribute('aria-valuenow', v.m ? 0 : v.v);
  }
  Player.paintVol = paintVol;

  /* standalone .ytp players (video shortcode, vods wall) */
  function mount(w) {
    if (w._ytp) return w._ytp;
    var sc = w.querySelector('.ytp__screen'), bar = w.querySelector('.ytp__bar');
    var seek = w.querySelector('.ytp__seek'), fill = w.querySelector('.ytp__fill'), buf = w.querySelector('.ytp__buf'), head = w.querySelector('.ytp__head');
    var tEl = w.querySelector('.ytp__time'), playB = w.querySelector('[data-yp="play"]'), volB = w.querySelector('[data-yp="mute"]'), vm = w.querySelector('.ytp__vol'), fsB = w.querySelector('[data-yp="full"]');
    var dragging = false;
    function draw(t, d, l) {
      var p = d ? Math.min(1, t / d) : 0;
      fill.style.width = (p * 100) + '%'; buf.style.width = (Math.min(1, l || 0) * 100) + '%'; head.style.left = (p * 100) + '%';
      seek.setAttribute('aria-valuenow', Math.round(p * 100)); seek.setAttribute('aria-valuetext', fmt(t) + ' of ' + fmt(d));
      tEl.textContent = fmt(t) + ' / ' + (d ? fmt(d) : '-:--');
    }
    function state() {
      var on = pl.playing(); w.classList.toggle('is-play', on);
      playB.setAttribute('aria-label', on ? 'pause' : 'play'); playB.querySelector('use').setAttribute('href', on ? '#icon-pause' : '#icon-play');
    }
    function vol(v) { paintVol(vm, v); var m = v.m || !v.v; volB.setAttribute('aria-label', m ? 'unmute' : 'mute'); volB.querySelector('use').setAttribute('href', m ? '#icon-mute' : '#icon-vol'); }
    var pl = new Player(sc, w.getAttribute('data-vid'), w.getAttribute('data-title'), {
      ontick: function (t, d, l) { if (!dragging) draw(t, d, l); },
      onstate: state, onvol: vol,
      onend: function () { w.dispatchEvent(new CustomEvent('ytp:end', { bubbles: true })); }
    });
    w._ytp = pl;
    bar.addEventListener('click', function (e) {
      var b = e.target.closest('[data-yp]'); if (!b) return; var k = b.getAttribute('data-yp');
      if (k === 'play') pl.toggle();
      else if (k === 'mute') pl.mute();
      else if (k === 'full') fsB.querySelector('use').setAttribute('href', Player.full(w) ? '#icon-unfull' : '#icon-full');
    });
    slide(seek, function (p, drag) { if (!pl.d) return; dragging = drag; draw(p * pl.d, pl.d, 0); if (!drag) pl.seek(p * pl.d); });
    seek.addEventListener('keydown', function (e) { var k = { ArrowRight: 5, ArrowLeft: -5, PageUp: 30, PageDown: -30 }[e.key]; if (k == null) return; e.preventDefault(); pl.seek(pl.t + k); });
    slide(vm, function (p) { pl.setVol(Math.ceil(p * 8) * 12.5, false); });
    vm.addEventListener('keydown', function (e) { var k = { ArrowRight: 12.5, ArrowUp: 12.5, ArrowLeft: -12.5, ArrowDown: -12.5 }[e.key]; if (k == null) return; e.preventDefault(); pl.setVol((pl.vol.m ? 0 : pl.vol.v) + k, false); });
    w.addEventListener('keydown', function (e) {
      if (e.target.closest('input,textarea,[role="slider"]')) return;
      if (e.key === 'k' || (e.key === ' ' && e.target === w)) { e.preventDefault(); pl.toggle(); }
      else if (e.key === 'm') pl.mute(); else if (e.key === 'f') Player.full(w);
    });
    vol(pl.vol); draw(0, 0, 0);
    return pl;
  }
  function fsSync() { var f = fsEl(); document.querySelectorAll('.ytp [data-yp="full"] use, .hvid [data-hv="full"] use').forEach(function (u) { u.setAttribute('href', f && f.contains(u) ? '#icon-unfull' : '#icon-full'); }); }
  document.addEventListener('fullscreenchange', fsSync); document.addEventListener('webkitfullscreenchange', fsSync);
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') document.querySelectorAll('.is-max').forEach(function (el) { Player.full(el); fsSync(); }); });

  window.YTPix = { Player: Player, mount: mount };
  document.querySelectorAll('.ytp').forEach(mount);
})();
