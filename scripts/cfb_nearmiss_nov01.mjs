// Retest of the college game model's near misses (memory cfb-game-model-audit) once CFBD's 2015-25 history was pulled
// (Nov 1 2026, cfb game research workflow): every test walk-forward on the 2015-26 ESPN history, scored with the
// project's paired clustered t (scripts/harness.mjs via cfb_hist_backtest.mjs cmp).
//   1. Returning college WAR (PFN, 2020 on) in the preseason prior, with and in place of nothing else (rosterAv, rosterAvRest)
//   2. The prior refit: pooled out-of-sample prior vs last-season-only (the Oct 14 ask), and CFBD SP+ alongside Elo (rosterSpx)
//   3. Market ratings on totals: each team's offense and defense points implied by earlier closes (spread and total),
//      as an input to the totals regression next to the model's plays x points per play
//   HIST=<dir of CFBD hist cache: sp*.json, lines*.json> node scripts/cfb_nearmiss_nov01.mjs
// Writes data/cfb_nearmiss_nov01.json.
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import { fileURLToPath } from 'node:url';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
process.env.ONLYSHIP = '1';
process.env.BT_OUT = path.join(ROOT, 'scripts', '.cache', 'cfb', 'hist_backtest_scratch.json');
const B = await import('./cfb_hist_backtest.mjs');
const { _internals: I, HIST_FIT } = await import('./cfb_model.mjs');
const { paired } = await import('./harness.mjs');
const HIST = process.env.HIST || path.join(ROOT, 'scripts', '.cache', 'cfb', 'hist');
const OUT = path.join(ROOT, 'data', 'cfb_nearmiss_nov01.json');
const P = B.report.ship.P, P0 = { k: 20, eloHome: 55, lam: 3 };
const T2 = S => S >= 2021 && S <= 2022, H2 = S => S >= 2023;
const RWP = process.env.RETWAR || path.join(ROOT, 'scripts', '.cache', 'cfb', 'ret_war.json');
I.setCtx({}, JSON.parse(fs.readFileSync(RWP, 'utf8')));
const shipX = HIST_FIT.extra, SHIPFIT = HIST_FIT.fit || {};
const r2 = x => Math.round(x * 100) / 100, r3 = x => Math.round(x * 1000) / 1000, r4 = x => Math.round(x * 1e4) / 1e4;
const mean = xs => xs.reduce((a, b) => a + b, 0) / Math.max(1, xs.length);
const out0 = process.env.ONLYTOTALS && fs.existsSync(OUT) ? JSON.parse(fs.readFileSync(OUT, 'utf8')) : {};
const out = { ...out0, asof: new Date().toISOString().slice(0, 10), P, shipX, note: 'shipped inputs and margin fit (from 2020, tune 2021-22, held 2023-26) unless noted' };
const save = () => fs.writeFileSync(OUT, JSON.stringify(out, null, 1));
const both = (a, b, t = T2, h = H2) => ({ ll: B.cmp(a, b, 'll', t, h), mae: B.cmp(a, b, 'ae', t, h),
  wk1to4: { ll: B.cmp(a.filter(x => x.w <= 4), b.filter(x => x.w <= 4), 'll', t, h), mae: B.cmp(a.filter(x => x.w <= 4), b.filter(x => x.w <= 4), 'ae', t, h) } });
const run = (ch, first = 2020, extra = shipX, fit = SHIPFIT) => { I.setExtra(extra); const o = B.predict(B.walkAll(ch, P), { first, fit }); I.setExtra([]); return o; };
console.log('shipped inputs', shipX.join(','));

// ---- 1 + 2: priors -----------------------------------------------------------------------------------------
// SP+ by season, CFBD school name -> ESPN id (the games' own names)
const SPX = {}; let spMiss = 0, spN = 0;
for (let S = 2015; S <= 2025; S++) {
  const f = path.join(HIST, `sp${S}.json`); if (!fs.existsSync(f)) continue;
  for (const x of JSON.parse(fs.readFileSync(f, 'utf8'))) { if (x.rating == null || x.team === 'nationalAverages') continue; const id = B.nameId[x.team]; spN++; if (!id) { spMiss++; continue; } (SPX[S] ||= {})[id] = x.rating; }
}
out.spCoverage = { rows: spN, unmatched: spMiss };
const chBase = B.chain('roster', 'pooled', P0);
if (!process.env.ONLYTOTALS) {
const oBase = run(chBase);
out.base = B.split(oBase);
// refit prior out of sample: last season's weights only vs pooled over every earlier season (walk-forward)
const oLast = run(B.chain('roster', 'last', P0));
out.priorScheme = { pooledVsLast: both(oBase, oLast) };
console.log('prior scheme', JSON.stringify(out.priorScheme)); save();
out.prior = {};
for (const [k, minFit] of [['rosterAvRest', 2016], ['rosterAv', 2016], ['rosterAvRest', 2020], ['rosterAv', 2020], ['rosterSpx', 2016]]) {
  if (k === 'rosterSpx') { const { setSpx } = await import('./cfb_hist_backtest.mjs'); setSpx(SPX); }
  const ch = B.chain(k, 'pooled', P0, minFit);
  const base = minFit === 2016 ? oBase : run(B.chain('roster', 'pooled', P0, minFit));
  const o = run(ch);
  out.prior[`${k}@${minFit}`] = { ...both(o, base), weights2026: ch.W[2026]?.pts.map(r3) };
  console.log('prior', k, minFit, JSON.stringify(out.prior[`${k}@${minFit}`])); save();
}
// also in the ESPN-only pooled model (tune 2017-20, held 2021-26), SP+ alongside Elo, which has the longer record
{
  const espnX = shipX.filter(k => k !== 'ret');
  const oE0 = run(chBase, 2016, espnX, {}), oE1 = run(B.chain('rosterSpx', 'pooled', P0), 2016, espnX, {});
  out.prior['rosterSpx@espnOnly'] = both(oE1, oE0, S => S >= 2017 && S <= 2020, S => S >= 2021);
  console.log('prior spx espn-only', JSON.stringify(out.prior['rosterSpx@espnOnly'])); save();
}

}
// ---- 3: market ratings on totals ---------------------------------------------------------------------------
// every finished FBS game's walk row (shipped prior), with its total projection; closing spread + total from the
// ESPN pickcenter, CFBD lines (consensus, else the median book) filling games ESPN lacks
const md = JSON.parse(zlib.gunzipSync(fs.readFileSync(path.join(ROOT, 'scripts', '.cache', 'cfb', 'espn_md.json.gz'))));
const wx = md.weather || {};
const cl = {};
for (let S = 2015; S <= 2025; S++) {
  const f = path.join(HIST, `lines${S}.json`); if (!fs.existsSync(f)) continue;
  for (const g of JSON.parse(fs.readFileSync(f, 'utf8'))) {
    const ls = (g.lines || []).filter(l => l.spread != null && l.overUnder != null);
    if (!ls.length) continue;
    const c = ls.find(l => l.provider === 'consensus');
    const med = xs => { const s = [...xs].sort((a, b) => a - b); return s[(s.length - 1) >> 1]; };
    cl[String(g.id)] = { m: -(c ? c.spread : med(ls.map(l => l.spread))), t: c ? c.overUnder : med(ls.map(l => l.overUnder)) };
  }
}
for (const r of B.rows) { const c = cl[String(r.id)]; r.mkM = r.close ?? c?.m ?? null; r.mkT = r.closeTot ?? c?.t ?? null; }
out.totalsCoverage = Object.fromEntries(B.SEASONS.map(S => { const g = B.rows.filter(r => r.S === S && r.done && r.fbsGame); return [S, { games: g.length, espnClose: g.filter(r => r.closeTot != null).length, withCfbd: g.filter(r => r.mkT != null).length }]; }));
I.setExtra(shipX); const WS = B.walkAll(chBase, P); I.setExtra([]);
// market ratings at week w of season S: ridge on implied team points (home = (T + M) / 2, away = (T - M) / 2) of games
// before w: pts = mu + O[off] + D[def] + h x site; FCS teams pooled. carry: last season's final ratings x c as the ridge's centre
const FCS = 'FCS';
function mktRatings(games, prev, c, lam) {
  const obs = [];
  for (const r of games) { const h = (r.mkT + r.mkM) / 2, a = (r.mkT - r.mkM) / 2, s = r.n ? 0 : 1;
    const H = r.hc === 'fbs' ? r.h : FCS, A = r.ac === 'fbs' ? r.a : FCS;
    obs.push([H, A, s, h], [A, H, -s, a]); }
  const O = {}, D = {}; let mu = obs.length ? mean(obs.map(o => o[3])) : 28, hh = 0;
  for (const t of new Set(obs.flatMap(o => [o[0], o[1]]))) { O[t] = c * (prev?.O[t] ?? 0); D[t] = c * (prev?.D[t] ?? 0); }
  const cO = { ...O }, cD = { ...D };
  for (let it = 0; it < 30; it++) {
    const so = {}, no = {}, sd = {}, nd = {};
    let sm = 0, sh = 0, nh = 0;
    for (const [o, d, s, y] of obs) { const e = y - mu - O[o] - D[d] - hh * s; sm += e; if (s) { sh += e * s; nh++; }
      so[o] = (so[o] || 0) + y - mu - D[d] - hh * s; no[o] = (no[o] || 0) + 1; }
    mu += sm / Math.max(1, obs.length); hh += nh ? sh / nh : 0;
    for (const t in O) O[t] = (so[t] + lam * cO[t]) / (no[t] + lam);
    for (const [o, d, s, y] of obs) { sd[d] = (sd[d] || 0) + y - mu - O[o] - hh * s; nd[d] = (nd[d] || 0) + 1; }
    for (const t in D) D[t] = ((sd[t] || 0) + lam * cD[t]) / ((nd[t] || 0) + lam);
  }
  return { mu, h: hh, O, D, n: obs.length };
}
function mktTotals(c, lam) {
  const res = {}; let prev = null;
  for (const S of B.SEASONS) {
    const g = B.rows.filter(r => r.S === S && r.mkT != null && r.mkM != null);
    const weeks = [...new Set(B.rows.filter(r => r.S === S).map(r => r.w))].sort((a, b) => a - b);
    for (const w of weeks) {
      const R = mktRatings(g.filter(r => r.w < w), prev, c, lam);
      for (const r of B.rows.filter(r => r.S === S && r.w === w)) {
        const H = r.hc === 'fbs' ? r.h : FCS, A = r.ac === 'fbs' ? r.a : FCS, s = r.n ? 0 : 1;
        if (R.n < 100 && !prev) { res[r.id] = null; continue; }
        const mu = R.n >= 100 ? R.mu : prev.mu;
        res[r.id] = 2 * mu + (R.O[H] ?? 0) + (R.D[A] ?? 0) + (R.O[A] ?? 0) + (R.D[H] ?? 0);
      }
    }
    prev = mktRatings(g, prev, c, lam);
  }
  return res;
}
const TXr = p => [...I.WX(p.r.dome ? null : wx[p.r.id]), p.x[7] !== 0 ? 1 : 0];
const tRows = B.SEASONS.flatMap(S => WS[S] || []).filter(p => p.r.done && p.t.tot > 0 && isFinite(p.t.tot));
function totalsWF(xf) {
  const o = [];
  for (const S of B.SEASONS.filter(S => S >= 2017)) {
    const tr = tRows.filter(p => p.r.S >= 2016 && p.r.S < S), te = tRows.filter(p => p.r.S === S);
    const b = I.ols(tr.map(xf), tr.map(p => p.r.tot), 1);
    for (const p of te) { const m = I.dot(b, xf(p)); o.push({ S, w: p.r.w, ae: Math.abs(p.r.tot - m), m, close: p.r.mkT, y: p.r.tot, day: p.r.date.slice(0, 10), ht: p.r.h + '|' + S }); }
  }
  return o;
}
const tcmp = (a, b, f) => { const A = a.filter(x => f(x.S)), Bb = b.filter(x => f(x.S)); const t = paired(A.map(x => x.ae), Bb.map(x => x.ae), [A.map(x => x.day), A.map(x => x.ht)]); return { d: r4(t.d), t: r2(t.t), n: t.n }; };
const T1 = S => S >= 2017 && S <= 2020, H1 = S => S >= 2021;
const tb = totalsWF(p => [1, p.t.tot, ...TXr(p)]);
const gap = o => { const k = o.filter(x => x.close != null); return { n: k.length, model: r2(mean(k.map(x => x.ae))), close: r2(mean(k.map(x => Math.abs(x.y - x.close)))),
  ouHit: r3(mean(k.filter(x => Math.abs(x.m - x.close) >= 3 && x.y !== x.close).map(x => Math.sign(x.m - x.close) === Math.sign(x.y - x.close) ? 1 : 0))) }; };
out.totals = { base: { tune: r2(mean(tb.filter(x => T1(x.S)).map(x => x.ae))), held: r2(mean(tb.filter(x => H1(x.S)).map(x => x.ae))), vsClose: gap(tb.filter(x => H1(x.S))) }, variants: {} };
for (const [c, lam] of [[0, 3], [0.5, 3], [0.5, 8], [0.75, 8], [0.75, 20]]) {
  const M = mktTotals(c, lam);
  const oc = totalsWF(p => { const v = M[p.r.id]; return [1, p.t.tot, ...TXr(p), v == null ? 0 : v - p.t.tot]; });
  out.totals.variants[`c${c}_lam${lam}`] = { tune: tcmp(oc, tb, T1), held: tcmp(oc, tb, H1), wk1to4: { tune: tcmp(oc.filter(x => x.w <= 4), tb.filter(x => x.w <= 4), T1), held: tcmp(oc.filter(x => x.w <= 4), tb.filter(x => x.w <= 4), H1) },
    vsClose: gap(oc.filter(x => H1(x.S))) };
  console.log('totals', c, lam, JSON.stringify(out.totals.variants[`c${c}_lam${lam}`])); save();
}
save();
console.log('written', OUT);
