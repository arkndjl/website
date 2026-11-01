// Backtest of the ticker's in-game win chance (static/js/livewp.js), Nov 1 2026.
//
//   python3 research/live_wp_fetch.py && node research/live_wp_research.mjs   # -> data/live_wp_research.json
//
// Each game is scored at fixed points (a quarter, half, three quarters, 90% and 97% of regulation; soccer at
// 22.5/45/67.5/80/88 minutes) from the last play before that point. Pregame numbers: the site's own model where it
// logged one (NFL 2026 past, NBA 2026-27 log), otherwise the de-vigged close (nflverse moneylines, NBA history,
// NHL history / ESPN pickcenter, Pinnacle 1X2 + over 2.5 for soccer). Constants are fitted on the earlier seasons
// and scored on the held-out latest one (NFL 2026, NBA/NHL 2026-27, soccer 2025-26). A term ships only if it
// lowers held-out log loss. ESPN's own in-game win probability (NFL, NBA) is the outside benchmark.
import fs from 'node:fs';
import zlib from 'node:zlib';
import path from 'node:path';
import { createRequire } from 'node:module';

const ROOT = path.dirname(path.dirname(new URL(import.meta.url).pathname));
const W = createRequire(import.meta.url)(path.join(ROOT, 'static', 'js', 'livewp.js'));
const C = path.join(ROOT, '.cache', 'live_wp');
const gz = f => JSON.parse(zlib.gunzipSync(fs.readFileSync(f)).toString());
const load = f => JSON.parse(fs.readFileSync(path.join(ROOT, f), 'utf8'));
const devig = (a, b) => { const p = x => x < 0 ? -x / (-x + 100) : 100 / (x + 100); const pa = p(a), pb = p(b); return pa / (pa + pb); };
const ll = (p, y) => { p = Math.min(Math.max(p, 1e-4), 1 - 1e-4); return -(y * Math.log(p) + (1 - y) * Math.log(1 - p)); };
const mean = a => a.reduce((s, x) => s + x, 0) / (a.length || 1);
const r4 = x => Math.round(x * 1e4) / 1e4;
const F = [0.25, 0.5, 0.75, 0.9, 0.97];
const SD = { nfl: load('data/nfl_games.json').sd, nba: load('data/nba_games.json').sd };
const LEN = { nfl: 3600, nba: 2880, nhl: 3600 };

// ---- pregame numbers ---------------------------------------------------------------------------------------
function nflPre(site) {
  const m = {};
  const csv = fs.readFileSync(path.join(C, 'nfl_games.csv'), 'utf8').trim().split('\n'), h = csv[0].split(',');
  const ix = k => h.indexOf(k);
  for (const line of csv.slice(1)) {
    const c = line.split(','); const e = c[ix('espn')], a = +c[ix('away_moneyline')], hm = +c[ix('home_moneyline')];
    if (e && a && hm) m[e] = devig(hm, a);
  }
  if (site) for (const g of load('data/nfl_games.json').past || []) if (g.espn && g.pHome != null) m[g.espn] = g.pHome;   // site model
  return m;
}
function nbaPre(site) {
  const m = {};
  for (const g of gz(path.join(ROOT, 'scripts', 'nba_games_hist.json.gz')).games) if (g.mlH && g.mlA) m[g.id] = devig(g.mlH, g.mlA);
  if (site) for (const [id, x] of Object.entries(load('data/nba_games.json').log || {})) if (x.row?.pHome != null) m[id] = x.row.pHome;
  return m;
}
const NHLAB = { NJ: 'NJD', TB: 'TBL', LA: 'LAK', SJ: 'SJS', UTAH: 'UTA', MON: 'MTL', WAS: 'WSH', CLB: 'CBJ', NAS: 'NSH' };
function nhlPre() {
  const m = {};
  for (const g of gz(path.join(ROOT, 'scripts', 'nhl_games_hist.json.gz'))) if (g.c?.p != null) m[`${g.day}|${g.h}|${g.a}`] = { p: g.c.p, t: g.c.t };
  return m;
}
const etDay = iso => new Date(new Date(iso).getTime() - 5 * 3600e3).toISOString().slice(0, 10);

// ---- checkpoints ---------------------------------------------------------------------------------------------
function rows(sport, site = true) {
  const games = gz(path.join(C, `${sport}.json.gz`)), out = [];
  const pre = sport === 'nfl' ? nflPre(site) : sport === 'nba' ? nbaPre(site) : nhlPre();
  for (const g of games) {
    if (g.fh === g.fa && sport === 'nfl') continue;   // ties
    let p0 = null, total = null;
    if (sport === 'nhl') {
      if (g.pre.mlH && g.pre.mlA) { p0 = devig(g.pre.mlH, g.pre.mlA); total = g.pre.total; }
      else { const x = pre[`${etDay(g.date)}|${NHLAB[g.h] || g.h}|${NHLAB[g.a] || g.a}`]; if (x) { p0 = x.p; total = x.t; } }
    } else {
      p0 = pre[g.id] ?? (g.pre.mlH && g.pre.mlA ? devig(g.pre.mlH, g.pre.mlA) : null);
    }
    if (p0 == null) continue;
    const test = g.date >= '2026-08';
    const y = g.fh > g.fa ? 1 : 0;
    for (const f of F) {
      const t = f * LEN[sport];
      let s = null;
      for (const x of g.st) { if (x[0] <= t) s = x; else break; }
      if (!s) continue;
      out.push({ sport, test, y, p0, total, f, r: 1 - t / LEN[sport], lead: s[1] - s[2], espn: s[3], pos: s[4] || 0, ytez: s[5] });
    }
  }
  return out;
}
function soccerRows() {
  const out = [];
  for (const g of gz(path.join(C, 'soccer.json.gz'))) {
    const inv = g.pc.map(x => 1 / x), s = inv[0] + inv[1] + inv[2];
    const po = g.ouc ? (1 / g.ouc[0]) / (1 / g.ouc[0] + 1 / g.ouc[1]) : null;
    const [lh, la] = W.soccerRates(inv[0] / s, inv[2] / s, po);
    const test = g.date >= '2025-08';
    const res = g.fh > g.fa ? 0 : g.fh === g.fa ? 1 : 2;
    for (const mn of [22.5, 45, 67.5, 80, 88]) {
      let lead = 0, redH = 0, redA = 0;
      for (const [m, k, side] of g.ev) { if (m > mn) break; if (k === 'g') lead += side; else if (side > 0) redH++; else redA++; }
      out.push({ sport: 'soccer', test, res, p0: [inv[0] / s, inv[1] / s, inv[2] / s], lh, la, min: mn, f: mn, lead, redH, redA });
    }
  }
  return out;
}

// ---- scoring -----------------------------------------------------------------------------------------------
const pr = (x, kk) => x.sport === 'nhl' ? W.nhl({ p0: x.p0, total: x.total || 6, lead: x.lead, r: x.r }, kk)
  : W.margin(x.sport, { p0: x.p0, sd: SD[x.sport], lead: x.lead, r: x.r, pos: x.pos, ytez: x.ytez }, kk);
const ll3 = (p, res) => -Math.log(Math.max(p[res], 1e-4));
function score(R, f) { return mean(R.map(f)); }
function grid(R, base, keys) {   // every combination of the listed values
  let best = null;
  const combos = keys.reduce((acc, [k, vals]) => acc.flatMap(c => vals.map(v => ({ ...c, [k]: v }))), [{ ...base }]);
  for (const kk of combos) {
    const s = R[0].sport === 'soccer' ? score(R, x => ll3(W.soccer(x, kk), x.res)) : score(R, x => ll(pr(x, kk), x.y));
    if (!best || s < best.s) best = { s, kk };
  }
  return best.kk;
}

function report(sport, R, fit, base) {
  const tr = R.filter(x => !x.test), te = R.filter(x => x.test);
  const kk = fit ? grid(tr, base, fit) : base;
  const out = { n: { train: tr.length, test: te.length }, fit: kk, test: {}, byPoint: [] };
  const isS = sport === 'soccer';
  const m = (x, k) => isS ? ll3(W.soccer(x, k), x.res) : ll(pr(x, k), x.y);
  const pre = x => isS ? ll3(x.p0, x.res) : ll(x.p0, x.y);
  out.test.live = r4(score(te, x => m(x, kk)));
  out.test.liveDefault = r4(score(te, x => m(x, base)));
  out.test.pregame = r4(score(te, pre));
  // each fitted term put back to its default: held-out change in log loss (positive = the term helps)
  out.ablation = {};
  for (const k of Object.keys(kk)) if (kk[k] !== base[k]) out.ablation[k] = r4(score(te, x => m(x, { ...kk, [k]: base[k] })) - out.test.live);
  if (!isS) out.test.scoreOnly = r4(score(te, x => m({ ...x, p0: 0.5 }, kk)));
  const ew = te.filter(x => x.espn != null);
  if (!isS && ew.length) out.test.espn = { n: ew.length, espn: r4(score(ew, x => ll(x.espn, x.y))), live: r4(score(ew, x => m(x, kk))) };
  for (const f of [...new Set(R.map(x => x.f))]) {
    const a = te.filter(x => x.f === f); if (!a.length) continue;
    const row = { at: f, n: a.length, live: r4(score(a, x => m(x, kk))), pregame: r4(score(a, pre)) };
    const e = a.filter(x => x.espn != null); if (!isS && e.length) { row.espn = r4(score(e, x => ll(x.espn, x.y))); row.liveOnEspn = r4(score(e, x => m(x, kk))); }
    out.byPoint.push(row);
  }
  if (!isS && sport !== 'nhl') {   // the same held-out games started from the de-vigged close instead of the site model
    const mk = rows(sport, false).filter(x => x.test), me = mk.filter(x => x.espn != null);
    out.test.marketAnchor = { n: mk.length, pregame: r4(score(mk, pre)), live: r4(score(mk, x => m(x, kk))) };
    if (me.length) { out.test.marketAnchor.espn = r4(score(me, x => ll(x.espn, x.y))); out.test.marketAnchor.liveOnEspn = r4(score(me, x => m(x, kk))); }
  }
  if (!isS) {   // calibration of the held-out live numbers, deciles
    const b = Array.from({ length: 10 }, () => [0, 0, 0]);
    for (const x of te) { const p = pr(x, kk), i = Math.min(9, Math.floor(p * 10)); b[i][0]++; b[i][1] += p; b[i][2] += x.y; }
    out.calib = b.map((v, i) => v[0] ? { bin: i / 10, n: v[0], model: r4(v[1] / v[0]), won: r4(v[2] / v[0]) } : null).filter(Boolean);
  }
  return out;
}

const res = { asof: new Date().toISOString().slice(0, 10), note: 'log loss per checkpoint; lower is better; test = held-out latest season', sports: {} };
if (fs.existsSync(path.join(C, 'nfl.json.gz'))) res.sports.nfl = report('nfl', rows('nfl'), [['a', [0.5, 0.6, 0.7, 0.8, 0.9, 1]], ['pos', [0, 0.5, 1, 1.5, 2, 3]], ['posYd', [0, 2, 3, 4, 5, 6, 8]]], { k: 1, a: 1, pos: 0, posYd: 0 });
res.sports.nba = report('nba', rows('nba'), [['a', [0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1]]], { k: 1, a: 1 });
res.sports.nhl = report('nhl', rows('nhl'), [['ot', [0, 0.25, 0.5, 0.75, 1]], ['en', [0, 0.25, 0.5, 0.75, 1, 1.5]]], { ot: 0.5, en: 0 });
if (fs.existsSync(path.join(C, 'soccer.json.gz')))
  res.sports.soccer = report('soccer', soccerRows(), [['len', [93, 96, 99, 102, 105]], ['red', [0.4, 0.5, 0.6, 0.67, 0.75, 0.85, 1]], ['redOpp', [1, 1.15, 1.25, 1.4]]], { len: 96, red: 1, redOpp: 1 });
fs.writeFileSync(path.join(ROOT, 'data', 'live_wp_research.json'), JSON.stringify(res, null, 1) + '\n');
for (const [k, v] of Object.entries(res.sports)) console.log(k, JSON.stringify(v.n), JSON.stringify(v.fit), JSON.stringify(v.test));
