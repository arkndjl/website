/* In-game win chance for the homepage ticker (Noah, Nov 1 2026). One file for the browser and the backtest
   (research/live_wp_research.mjs), so the page and the test run the same numbers.

   Every model starts from the site's own pregame number and moves it with the score and the time left:
   - NFL / NBA: the final margin drifts like a random walk around the pregame margin. Home leads by L with a share
     r of the game left: P(home) = Phi((L + mu*r) / (sd*k*r^(a/2))), mu = sd*Phi^-1(p0) so r = 1 gives back p0 (k = 1).
     a < 1: more of the variance is still to come late in a game than a plain random walk says (fitted).
     NFL adds the value of having the ball (pos points, more near the goal line).
   - NHL / soccer: the goals still to come are Poisson at the pregame rates times r. NHL ties go to OT/shootout at
     the pregame edge, shrunk toward a coin flip; soccer returns win/draw/loss. A red card cuts that side's rate.
   - CS2 (1NT): a series of maps at each map's veto win chance; a map in play is a race to 13 rounds (MR12, OT
     first to 4 of 6) at the per-round chance q.
   Constants (K) are the backtest fits in data/live_wp_research.json. */
(function (root) {
  var K = {   // held-out fits, research/live_wp_research.mjs (Nov 1 2026)
    nfl: { k: 1, a: 0.7, pos: 0, posYd: 4 },
    nba: { k: 1, a: 0.6 },
    nhl: { ot: 1, en: 0.5 },
    soccer: { len: 102, red: 0.5, redOpp: 1.15 }
  };

  function erf(x) {   // Abramowitz-Stegun 7.1.26, |err| < 1.5e-7
    var s = x < 0 ? -1 : 1; x = Math.abs(x);
    var t = 1 / (1 + 0.3275911 * x);
    var y = 1 - ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x);
    return s * y;
  }
  function phi(z) { return 0.5 * (1 + erf(z / Math.SQRT2)); }
  function phiInv(p) {   // Acklam
    p = Math.min(Math.max(p, 1e-9), 1 - 1e-9);
    var a = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.357751867269, -30.66479806614716, 2.506628277459239],
        b = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572],
        c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783],
        d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416], q, r;
    if (p < 0.02425) { q = Math.sqrt(-2 * Math.log(p)); return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1); }
    if (p > 1 - 0.02425) { q = Math.sqrt(-2 * Math.log(1 - p)); return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1); }
    q = p - 0.5; r = q * q;
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
  }

  // ---- NFL / NBA: margin random walk -------------------------------------------------------------------
  // s: { p0, sd, lead (home minus away), r (share of regulation left, 0..1), pos (+1 home ball, -1 away, 0), ytez }
  function margin(sport, s, kk) {
    var c = kk || K[sport], mu = s.sd * phiInv(s.p0), L = s.lead;
    if (sport === 'nfl' && s.pos) L += s.pos * (c.pos + c.posYd * (1 - Math.min(Math.max((s.ytez == null ? 70 : s.ytez) / 100, 0), 1)));
    var r = Math.max(s.r, 0);
    if (r < 0.004) {   // the end of regulation: a tie plays on at the pregame edge over a short extra period
      if (Math.abs(L) > 0.5) return L > 0 ? 1 : 0;
      r = 0.1;
    }
    return phi((L + mu * r) / (s.sd * c.k * Math.pow(r, (c.a || 1) / 2)));
  }

  // ---- Poisson goals -----------------------------------------------------------------------------------
  function pois(l, n) { var out = [], p = Math.exp(-l); for (var i = 0; i <= n; i++) { out.push(p); p = p * l / (i + 1); } return out; }
  // P(final diff > 0), P(= 0), P(< 0) when home leads by `lead` and goals still to come are Poisson(lh), Poisson(la)
  function race(lead, lh, la) {
    var N = 15, ph = pois(lh, N), pa = pois(la, N), w = 0, d = 0, l = 0;
    for (var i = 0; i <= N; i++) for (var j = 0; j <= N; j++) {
      var p = ph[i] * pa[j], x = lead + i - j;
      if (x > 0) w += p; else if (x === 0) d += p; else l += p;
    }
    var t = w + d + l; return [w / t, d / t, l / t];
  }
  // NHL: split the pregame total T so that regulation + OT reproduces p0. s: { p0, total, lead, r, ot (in OT) }
  function nhlSplit(p0, T, c) {
    var lo = 0.05, hi = 0.95;
    for (var i = 0; i < 40; i++) {
      var m = (lo + hi) / 2, x = race(0, T * m, T * (1 - m)), q = 0.5 + (m - 0.5) * c.ot;
      if (x[0] + x[1] * q < p0) lo = m; else hi = m;
    }
    return (lo + hi) / 2;
  }
  function nhl(s, kk) {
    var c = kk || K.nhl, T = s.total || 6, m = nhlSplit(s.p0, T, c), q = 0.5 + (m - 0.5) * c.ot;
    if (s.ot) return s.lead > 0 ? 1 : s.lead < 0 ? 0 : q;
    var r = Math.max(s.r, 0), boost = 1;
    if (c.en && Math.abs(s.lead) >= 1 && Math.abs(s.lead) <= 2 && r * 60 < 3) boost = 1 + c.en;   // pulled goalie
    var x = race(s.lead, T * m * r * boost, T * (1 - m) * r * boost);
    return x[0] + x[1] * q;
  }
  // soccer: s: { lh, la (pregame expected goals), lead, min (minutes played), redH, redA } -> [win, draw, loss] for home
  function soccer(s, kk) {
    var c = kk || K.soccer, r = Math.max(c.len - s.min, 0) / c.len;
    var fh = Math.pow(c.red, s.redH || 0) * Math.pow(c.redOpp, s.redA || 0),
        fa = Math.pow(c.red, s.redA || 0) * Math.pow(c.redOpp, s.redH || 0);
    return race(s.lead, s.lh * r * fh, s.la * r * fa);
  }
  // expected goals from 1X2 probabilities and an over-2.5 chance (used by the backtest with closing prices)
  function soccerRates(pw, pl, po) {
    var best = null;
    for (var T = 1.4; T <= 4.4; T += 0.02) for (var m = 0.15; m <= 0.85; m += 0.005) {
      var x = race(0, T * m, T * (1 - m)), u = pois(T, 2), over = 1 - u[0] - u[1] - u[2];
      var e = Math.pow(x[0] - pw, 2) + Math.pow(x[2] - pl, 2) + (po == null ? 0 : 0.5 * Math.pow(over - po, 2));
      if (!best || e < best[0]) best = [e, T * m, T * (1 - m)];
    }
    return [best[1], best[2]];
  }

  // ---- CS2 -------------------------------------------------------------------------------------------------
  // a map: P(win) from (us, them) rounds at per-round chance q. MR12: first to 13; 12-12 goes to OT halves of 6
  // (first to 4), repeating at 3-3.
  function csMap(us, them, q) {
    var memo = {}, bs = null;
    function blockStart() {   // P(win an OT block from 0-0, first to 4 of 6, replayed at 3-3) = w / (w + l)
      if (bs !== null) return bs;
      var w = 0, l = 0, P = { '0,0': 1 };
      for (var n = 0; n < 7; n++) for (var x = 0; x <= n; x++) {
        var y = n - x, p = P[x + ',' + y]; if (!p) continue;
        if (x === 4) { w += p; continue; } if (y === 4) { l += p; continue; } if (x === 3 && y === 3) continue;
        P[(x + 1) + ',' + y] = (P[(x + 1) + ',' + y] || 0) + p * q;
        P[x + ',' + (y + 1)] = (P[x + ',' + (y + 1)] || 0) + p * (1 - q);
      }
      bs = w / (w + l); return bs;
    }
    function f(a, b) {
      var k = a + ',' + b; if (k in memo) return memo[k];
      var v;
      if (a < 12 || b < 12) {   // regulation
        if (a >= 13) v = 1; else if (b >= 13) v = 0; else v = q * f(a + 1, b) + (1 - q) * f(a, b + 1);
      } else {                  // overtime: the current block of 6 started at 12 + 3n each
        var base = a === b ? a : 12 + 3 * Math.floor((Math.min(a, b) - 12) / 3), x = a - base, y = b - base;
        if (a === b && a >= 12 && a % 3 === 0) v = blockStart();   // 12-12, 15-15, ...: a fresh block
        else if (x >= 4) v = 1; else if (y >= 4) v = 0;
        else v = q * f(a + 1, b) + (1 - q) * f(a, b + 1);
      }
      memo[k] = v; return v;
    }
    return f(us, them);
  }
  // per-round chance that gives a map win chance pm (inverse of csMap from 0-0)
  function csRound(pm) {
    var lo = 0.2, hi = 0.8;
    for (var i = 0; i < 40; i++) { var m = (lo + hi) / 2; if (csMap(0, 0, m) < pm) lo = m; else hi = m; }
    return (lo + hi) / 2;
  }
  // a series: maps = per-map win chances in play order (null = not known yet -> pAvg); won/lost = maps so far;
  // cur = chance on the map in play (or null). First to ceil(bo/2).
  function csSeries(bo, won, lost, maps, cur, pAvg) {
    var need = Math.ceil(bo / 2);
    function g(w, l, i, first) {
      if (w >= need) return 1; if (l >= need) return 0;
      var p = first && cur != null ? cur : (maps[i] != null ? maps[i] : pAvg);
      return p * g(w + 1, l, i + 1, false) + (1 - p) * g(w, l + 1, i + 1, false);
    }
    return g(won, lost, won + lost, true);
  }

  var api = { K: K, phi: phi, phiInv: phiInv, margin: margin, nhl: nhl, soccer: soccer, soccerRates: soccerRates,
              race: race, csMap: csMap, csRound: csRound, csSeries: csSeries };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.LiveWP = api;
})(this);
