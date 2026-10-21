// Backtest: do badges (scripts/cfb_badges.mjs) predict NFL careers beyond production? Run by hand after
// scripts/cfb_statplus_backtest.mjs (it reuses that script's cached PFN boards and nflverse picks):
//   node scripts/cfb_badge_backtest.mjs -> data/cfb_badge_backtest.json
// Universe and outcome as in the Stat+ backtest: each player's last PFN season 2019-22 (QB, RB, WR, TE, EDGE,
// DT, LB; OL, CB and S have no PFN history before 2024), weighted NFL AV a season, undrafted = 0. Each badge's stat
// is measured the way the board measures it: regressed by volume with the badge's own k, then z'd within the
// position and season (100+ snaps). Tests, per badge:
//   partial   correlation with NFL AV holding production (FV's blend: 5/4/3 by snaps, FV_K 3000) fixed
//   oos       out of sample: leave one final season out, fit AV ~ production + badge on the rest, predict the
//             held-out season; the gain in out-of-sample R^2 over production alone (x100, so 1.0 = one point)
// A badge earns FV weight, of either sign, only when both agree (|t| >= 2 and an out-of-sample gain). QB Scrambler
// came closest on the negative side: t -1.95 alone (out-of-sample +0.46), and its beta halves to -.06 once Deep
// Ball and Accurate are in, so it stays out; EDGE Disruptor t -1.88
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { BADGES } from './cfb_badges.mjs';
import { NFLPOS } from './cfb_nflpos.mjs';   // the shared draft-position map (EDGEs listed as LB, Oct 21 2026)

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const CACHE = path.join(ROOT, 'scripts', '.cache', 'statplus');
const OUT = path.join(ROOT, 'data', 'cfb_badge_backtest.json');
const SPG = { QB: 65, RB: 30, WR: 40, TE: 40, EDGE: 50, DL: 45, LB: 55 };
const NFL_THROUGH = 2025, K = 3000, W = [5, 4, 3];
const num = v => (typeof v === 'number' && isFinite(v) ? v : null);
const [h, ...pl] = fs.readFileSync(path.join(CACHE, 'draft_picks.csv'), 'utf8').trim().split('\n'), H = h.split(',');
const picks = pl.map(l => { const v = l.split(','); return Object.fromEntries(H.map((k, i) => [k, v[i]])); }).filter(r => +r.season >= 2020 && +r.season <= 2025);
const nm = s => (s || '').toLowerCase().normalize('NFKD').replace(/[^a-z ]/g, '').replace(/\b(jr|sr|ii|iii|iv)\b/g, '').replace(/\s+/g, ' ').trim();
const col = s => nm(s).replace(/\bstate\b/, 'st').replace(/\buniversity\b|\bof\b/g, '').trim();
const mean = xs => xs.reduce((a, b) => a + b, 0) / xs.length;
const corr = (xs, ys) => { const mx = mean(xs), my = mean(ys); let a = 0, b = 0, c = 0; xs.forEach((x, i) => { a += (x - mx) * (ys[i] - my); b += (x - mx) ** 2; c += (ys[i] - my) ** 2; }); return a / Math.sqrt(b * c); };
const partial = (x, z, y) => { const rxy = corr(x, y), rxz = corr(x, z), rzy = corr(z, y); return (rxy - rxz * rzy) / Math.sqrt((1 - rxz ** 2) * (1 - rzy ** 2)); };
// OLS y ~ 1 + xs, returns coefficients
function ols(X, y) {
  const k = X[0].length + 1, A = [...Array(k)].map(() => Array(k).fill(0)), b = Array(k).fill(0);
  X.forEach((r, i) => { const x = [1, ...r]; for (let p = 0; p < k; p++) { b[p] += x[p] * y[i]; for (let q = 0; q < k; q++) A[p][q] += x[p] * x[q]; } });
  for (let i = 0; i < k; i++) { const piv = A[i][i]; for (let j = i; j < k; j++) A[i][j] /= piv; b[i] /= piv; for (let r = 0; r < k; r++) if (r !== i) { const f = A[r][i]; for (let j = i; j < k; j++) A[r][j] -= f * A[i][j]; b[r] -= f * b[i]; } }
  return b;
}
const r3 = x => x == null || !isFinite(x) ? null : Math.round(x * 1000) / 1000;
const out = { asof: new Date().toISOString().slice(0, 10), method: 'see scripts/cfb_badge_backtest.mjs', positions: {} };
for (const g of Object.keys(SPG)) {
  const rows = JSON.parse(fs.readFileSync(path.join(CACHE, `pfn_${g}.json`))).filter(r => r.division === 'FBS');
  const snaps = r => num(r.snapsQ) ?? num(r.snaps) ?? ((num(r.gp) ?? num(r.gamesQ) ?? 0) * SPG[g]);
  const cz = {}; for (const r of rows) (cz[r.season] ||= []).push(r.score);
  for (const [s, xs] of Object.entries(cz)) { const m = mean(xs); cz[s] = [m, Math.sqrt(mean(xs.map(x => (x - m) ** 2)))]; }
  for (const r of rows) { r._z = (r.score - cz[r.season][0]) / cz[r.season][1]; r._v = snaps(r); }
  // badge z per row: regressed by volume (badge k), z within position-season among 100+ snap rows
  const bz = {};
  for (const [key, , val, vol, half] of BADGES[g]) {
    if (Array.isArray(val)) continue;
    bz[key] = new Map();
    for (const s of Object.keys(cz)) {
      const pool = rows.filter(r => r.season === +s && r._v >= 100).map(r => ({ r, v: num(val(r)), n: Math.max(0, num(vol(r)) ?? 0) })).filter(x => x.v != null);
      if (pool.length < 20) continue;
      const nw = pool.reduce((a, x) => a + x.n, 0), m = nw ? pool.reduce((a, x) => a + x.n * x.v, 0) / nw : mean(pool.map(x => x.v));
      for (const x of pool) x.reg = m + (x.v - m) * x.n / (x.n + half);
      const mm = mean(pool.map(x => x.reg)), sd = Math.sqrt(mean(pool.map(x => (x.reg - mm) ** 2))) || 1;
      for (const x of pool) bz[key].set(x.r, (x.reg - mm) / sd);
    }
  }
  const byId = {}; for (const r of rows) (byId[r.id] ||= {})[r.season] = r;
  const P = [];
  for (const by of Object.values(byId)) {
    const last = Math.max(...Object.keys(by).map(Number)); if (last > 2022) continue;
    const r = by[last], D = last + 1, cand = picks.filter(p => nm(p.pfr_player_name) === nm(r.name) && NFLPOS[g].includes(p.position));
    const pk = cand.find(p => +p.season === D && col(p.college).split(' ')[0] === col(r.team).split(' ')[0]) || cand.find(p => +p.season === D);
    if (!pk && cand.some(p => +p.season > D)) continue;
    let num_ = 0, den = 0; W.forEach((w, k) => { const x = by[last - k]; if (x) { num_ += w * x._v * x._z; den += w * x._v; } });
    P.push({ last, row: r, prod: num_ / (den + K), av: pk ? (+pk.w_av || 0) / (NFL_THROUGH - D + 1) : 0 });
  }
  const res = { n: P.length, badges: {} };
  for (const [key, name] of BADGES[g]) {
    if (!bz[key]) continue;
    const S = P.filter(p => bz[key].has(p.row)).map(p => ({ ...p, b: bz[key].get(p.row) }));
    if (S.length < 60) continue;
    const pr = partial(S.map(p => p.b), S.map(p => p.prod), S.map(p => p.av));
    // leave-one-season-out
    let sse0 = 0, sse1 = 0, sst = 0;
    for (const s of [...new Set(S.map(p => p.last))]) {
      const tr = S.filter(p => p.last !== s), te = S.filter(p => p.last === s), my = mean(tr.map(p => p.av));
      const b0 = ols(tr.map(p => [p.prod]), tr.map(p => p.av)), b1 = ols(tr.map(p => [p.prod, p.b]), tr.map(p => p.av));
      for (const p of te) { sse0 += (p.av - b0[0] - b0[1] * p.prod) ** 2; sse1 += (p.av - b1[0] - b1[1] * p.prod - b1[2] * p.b) ** 2; sst += (p.av - my) ** 2; }
    }
    const t = pr * Math.sqrt((S.length - 3) / (1 - pr * pr));
    // standardized betas with both in: the badge's FV weight is FV_W.pfn x b_badge / b_prod, halved (credibility)
    const zs = xs => { const m = mean(xs), sd = Math.sqrt(mean(xs.map(x => (x - m) ** 2))) || 1; return xs.map(x => (x - m) / sd); };
    const zp = zs(S.map(p => p.prod)), zb = zs(S.map(p => p.b)), za = zs(S.map(p => p.av)), bb = ols(zp.map((x, i) => [x, zb[i]]), za);
    res.badges[key] = { name, n: S.length, r: r3(corr(S.map(p => p.b), S.map(p => p.av))), partial: r3(pr), t: Math.round(t * 100) / 100, oosGain: r3(100 * (sse0 - sse1) / sst), bProd: r3(bb[1]), bBadge: r3(bb[2]), pass: Math.abs(t) >= 2 && sse1 < sse0 };
  }
  // all passing badges together (QB has two that overlap): joint standardized betas set the weights
  const keys = Object.entries(res.badges).filter(([, v]) => v.pass).map(([k]) => k);
  if (keys.length) {
    const S = P.filter(p => keys.every(k => bz[k].has(p.row)));
    const zs = xs => { const m = mean(xs), sd = Math.sqrt(mean(xs.map(x => (x - m) ** 2))) || 1; return xs.map(x => (x - m) / sd); };
    const cols = [zs(S.map(p => p.prod)), ...keys.map(k => zs(S.map(p => bz[k].get(p.row))))], za = zs(S.map(p => p.av));
    const b = ols(S.map((_, i) => cols.map(c => c[i])), za);
    res.joint = { n: S.length, bProd: r3(b[1]), ...Object.fromEntries(keys.map((k, i) => [k, r3(b[i + 2])])) };
  }
  out.positions[g] = res;
  console.log(g, res.n, Object.entries(res.badges).map(([k, v]) => `${k} partial${v.partial} t${v.t} oos${v.oosGain} b${v.bBadge}/${v.bProd}${v.pass ? ' PASS' : ''}`).join(' | '));
}
fs.writeFileSync(OUT, JSON.stringify(out, null, 1) + '\n');
