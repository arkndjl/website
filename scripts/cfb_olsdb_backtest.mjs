// Backtest for the efficiency stats FV weighted at OL, CB and S on trust until Oct 2026 (FV_STATS in fetch_cfb.mjs): do
// they add anything to production? PFN has lines there from 2024 only, so the outcome is draft capital, not an
// NFL career: the 2025 and 2026 drafts (nflverse), each pick as the AV a season that slot returned in the
// 2010-19 drafts (a log fit), undrafted as pick 275. Run by hand after scripts/cfb_move_backtest.mjs (which
// caches the OL, CB and S boards): node scripts/cfb_olsdb_backtest.mjs -> data/cfb_olsdb_backtest.json
// Universe: FBS players whose last PFN season is 2024 or 2025 (left college), 100+ snaps. Production is FV's
// term (each season's score as a z on that season's curve, blended 5/4 by snaps, regressed with K 3000). Each
// stat is a z within the position and season among 60+ snap players, signed as FV signs it. Tests:
//   partial  correlation with draft capital holding production fixed (t from it)
//   oos      fit capital ~ production (+ stat) on one draft, predict the other, both ways: gain in R^2 x100
// A stat keeps FV weight only when both agree (|t| >= 2, the sign FV gives it, and an out-of-sample gain).
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const CACHE = path.join(ROOT, 'scripts', '.cache', 'statplus');
const OUT = path.join(ROOT, 'data', 'cfb_olsdb_backtest.json');
const nz = v => (typeof v === 'number' && isFinite(v) ? v : null);
// the weights FV gave them (LIVE: the composite it used), plus the PFN fields a badge or a scout would look at
const STATS = {
  OL: [['prsRate', -1], ['skAllwd', -0.5], ['pbScore', 1], ['rbScore', 1]],
  CB: [['fi', 1], ['catchAllowed', -0.7, r => nz(r.catch)], ['rtg', -0.5], ['pbu', 1], ['int', 1], ['mt', -1]],
  S: [['fi', 1], ['tacklePct', 0.5, r => nz(r.mt) != null ? 100 - r.mt : null], ['rtg', -0.5], ['pbu', 1], ['int', 1]],
};
const LIVE = { OL: ['prsRate', 'skAllwd'], CB: ['fi', 'catchAllowed', 'rtg'], S: ['fi', 'tacklePct', 'rtg'] };
const NFLPOS = { OL: ['OL', 'OT', 'T', 'G', 'OG', 'C'], CB: ['CB', 'DB'], S: ['S', 'SAF', 'FS', 'SS', 'DB'] };
const K = 3000, W = [5, 4];

const [h, ...pl] = fs.readFileSync(path.join(CACHE, 'draft_picks.csv'), 'utf8').trim().split('\n'), H = h.split(',');
const allPicks = pl.map(l => { const v = l.split(','); return Object.fromEntries(H.map((k, i) => [k, v[i]])); });
const nm = s => (s || '').toLowerCase().normalize('NFKD').replace(/[^a-z ]/g, '').replace(/\b(jr|sr|ii|iii|iv)\b/g, '').replace(/\s+/g, ' ').trim();
const col = s => nm(s).replace(/\bstate\b/, 'st').replace(/\buniversity\b|\bof\b/g, '').trim().split(' ')[0];
const mean = xs => xs.reduce((a, b) => a + b, 0) / xs.length;
const corr = (xs, ys) => { const mx = mean(xs), my = mean(ys); let a = 0, b = 0, c = 0; xs.forEach((x, i) => { a += (x - mx) * (ys[i] - my); b += (x - mx) ** 2; c += (ys[i] - my) ** 2; }); return a / Math.sqrt(b * c); };
const partial = (x, z, y) => { const rxy = corr(x, y), rxz = corr(x, z), rzy = corr(z, y); return (rxy - rxz * rzy) / Math.sqrt((1 - rxz ** 2) * (1 - rzy ** 2)); };
function ols(X, y) {
  const k = X[0].length + 1, A = [...Array(k)].map(() => Array(k).fill(0)), b = Array(k).fill(0);
  X.forEach((r, i) => { const x = [1, ...r]; for (let p = 0; p < k; p++) { b[p] += x[p] * y[i]; for (let q = 0; q < k; q++) A[p][q] += x[p] * x[q]; } });
  for (let i = 0; i < k; i++) { const piv = A[i][i]; for (let j = i; j < k; j++) A[i][j] /= piv; b[i] /= piv; for (let r = 0; r < k; r++) if (r !== i) { const f = A[r][i]; for (let j = i; j < k; j++) A[r][j] -= f * A[i][j]; b[r] -= f * b[i]; } }
  return b;
}
const pred = (b, x) => b[0] + x.reduce((a, v, i) => a + b[i + 1] * v, 0);
const r3 = x => x == null || !isFinite(x) ? null : Math.round(x * 1000) / 1000;

// the value of a slot: AV a season by pick in the 2010-19 drafts, AV/season = a + b ln(pick)
const hist = allPicks.filter(p => +p.season >= 2010 && +p.season <= 2019 && +p.pick > 0);
const fitV = ols(hist.map(p => [Math.log(+p.pick)]), hist.map(p => (+p.w_av || 0) / (2025 - +p.season + 1)));
const slotValue = pick => Math.max(0, pred(fitV, [Math.log(Math.min(pick, 275))]));
const picks = allPicks.filter(p => +p.season === 2025 || +p.season === 2026);

const out = { asof: new Date().toISOString().slice(0, 10), slotCurve: { a: r3(fitV[0]), b: r3(fitV[1]) }, positions: {} };
for (const g of Object.keys(STATS)) {
  const rows = JSON.parse(fs.readFileSync(path.join(CACHE, `pfn_${g}.json`), 'utf8')).filter(r => r.division === 'FBS');
  const vol = r => nz(r.snapsQ) ?? nz(r.snaps) ?? (nz(r.gp) ?? 0) * 55;
  const cz = {}; for (const r of rows) (cz[r.season] ||= []).push(r.score);
  for (const [s, xs] of Object.entries(cz)) { const m = mean(xs); cz[s] = [m, Math.sqrt(mean(xs.map(x => (x - m) ** 2)))]; }
  for (const r of rows) { r._z = (r.score - cz[r.season][0]) / cz[r.season][1]; r._v = vol(r); }
  // stat z within position-season, 60+ snaps, signed so + is what FV rewards
  const sz = {};
  for (const [f, w, get] of STATS[g]) {
    sz[f] = new Map();
    for (const s of Object.keys(cz)) {
      const pool = rows.filter(r => r.season === +s && r._v >= 60).map(r => ({ r, v: get ? get(r) : nz(r[f]) })).filter(x => x.v != null);
      if (pool.length < 30) continue;
      const m = mean(pool.map(x => x.v)), sd = Math.sqrt(mean(pool.map(x => (x.v - m) ** 2))) || 1;
      for (const x of pool) sz[f].set(x.r, Math.sign(w) * (x.v - m) / sd);
    }
  }
  const byId = {}; for (const r of rows) (byId[r.id] ||= {})[r.season] = r;
  const P = [];
  for (const by of Object.values(byId)) {
    const last = Math.max(...Object.keys(by).map(Number)); if (last > 2025 || last < 2024) continue;
    const r = by[last]; if (r._v < 100) continue;
    const D = last + 1, cand = picks.filter(p => nm(p.pfr_player_name) === nm(r.name) && NFLPOS[g].includes(p.position));
    const pk = cand.find(p => +p.season === D && col(p.college) === col(r.team)) || cand.find(p => +p.season === D);
    let a = 0, d = 0; W.forEach((w, k) => { const x = by[last - k]; if (x) { a += w * x._v * x._z; d += w * x._v; } });
    // the live composite: FV_STATS weights over the stats a player has
    let cs = 0, cw = 0; for (const [f, w] of STATS[g].filter(([f]) => LIVE[g].includes(f))) { const z = sz[f].get(r); if (z != null) { cs += Math.abs(w) * z; cw += Math.abs(w); } }
    P.push({ D, row: r, prod: a / (d + K), y: pk ? slotValue(+pk.pick) : slotValue(275), drafted: !!pk, comp: cw ? cs / cw : null });
  }
  const res = { n: P.length, drafted: P.filter(p => p.drafted).length, stats: {} };
  const test = (key, get) => {
    const S = P.map(p => ({ ...p, b: get(p) })).filter(p => p.b != null); if (S.length < 60) return;
    const pr = partial(S.map(p => p.b), S.map(p => p.prod), S.map(p => p.y)), t = pr * Math.sqrt((S.length - 3) / (1 - pr * pr));
    let sse0 = 0, sse1 = 0, sst = 0;
    for (const D of [2025, 2026]) {
      const tr = S.filter(p => p.D !== D), te = S.filter(p => p.D === D); if (!tr.length || !te.length) continue;
      const my = mean(tr.map(p => p.y)), b0 = ols(tr.map(p => [p.prod]), tr.map(p => p.y)), b1 = ols(tr.map(p => [p.prod, p.b]), tr.map(p => p.y));
      for (const p of te) { sse0 += (p.y - pred(b0, [p.prod])) ** 2; sse1 += (p.y - pred(b1, [p.prod, p.b])) ** 2; sst += (p.y - my) ** 2; }
    }
    res.stats[key] = { n: S.length, r: r3(corr(S.map(p => p.b), S.map(p => p.y))), partial: r3(pr), t: Math.round(t * 100) / 100, oosGain: r3(100 * (sse0 - sse1) / sst),
      pass: t >= 2 && sse1 < sse0 };
  };
  test('production', p => p.prod);
  test('live composite', p => p.comp);
  for (const [f] of STATS[g]) test(f, p => sz[f].get(p.row) ?? null);
  out.positions[g] = res;
  console.log(g, `n ${res.n}, drafted ${res.drafted}`);
  console.table(res.stats);
}
fs.writeFileSync(OUT, JSON.stringify(out, null, 1) + '\n');
