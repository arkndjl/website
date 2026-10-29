// Research (Oct 29 2026, Noah: "players who haven't played enough snaps to qualify should still have the snaps they
// have played feed FV, regressed"). The board's production term already takes every snap (Marcel blend, FV_K 3000
// weighted snaps). The stat terms on top of it, the FV badges (FV_BADGE) and XV parts (FV_XV), are each regressed by
// their own volume k but only computed for players with 100+ snaps: below that the term is 0 (the qualifier mean).
// Test: give the sub-100 players the same regressed z (their rate pulled toward the qualifier mean by n / (n + k),
// standardized on the qualifiers so nobody else moves) and score both on NFL AV a season, leave one final season out.
// Universe as scripts/cfb_badge_backtest.mjs (run scripts/cfb_statplus_backtest.mjs first for the cached PFN boards):
// each player's last PFN season 2019-22 at QB, RB, TE, EDGE, DT and LB.
//   node scripts/cfb_lowsnap_research.mjs [--min=N ...] -> data/cfb_lowsnap_research.json
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { BADGES, badgeSnaps } from './cfb_badges.mjs';
import { NFLPOS } from './cfb_nflpos.mjs';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const CACHE = path.join(ROOT, 'scripts', '.cache', 'statplus');
const OUT = path.join(ROOT, 'data', 'cfb_lowsnap_research.json');
const SPG = { QB: 65, RB: 30, WR: 40, TE: 40, EDGE: 50, DL: 45, LB: 55 };
const NFL_THROUGH = 2025, K = 3000, W = [5, 4, 3], GATE = 100;
const num = v => (typeof v === 'number' && isFinite(v) ? v : null);
const nz = num;
// the shipped weights (scripts/fetch_cfb.mjs)
const FV_BADGE = { w: { QB: { accurate: 0.13, deep: 0.03 }, RB: { catcher: 0.13 }, TE: { catcher: 0.24 }, DL: { runstop: 0.07 }, LB: { tackler: 0.1 } }, cap: 0.3 };
const FV_XV = { LB: { cov: [0.08, r => (nz(r.tgt) && nz(r.rtg) != null ? -nz(r.rtg) : null), r => r.tgt, 400] },
  EDGE: { sk: [0.07, r => (nz(r.sk) != null && badgeSnaps(r) ? nz(r.sk) / badgeSnaps(r) : null), badgeSnaps, 2000] }, cap: 0.2 };
const MINS = (process.argv.find(a => a.startsWith('--min=')) || '--min=1,25,50').slice(6).split(',').map(Number);

const [h, ...pl] = fs.readFileSync(path.join(CACHE, 'draft_picks.csv'), 'utf8').trim().split('\n'), H = h.split(',');
const picks = pl.map(l => { const v = l.split(','); return Object.fromEntries(H.map((k, i) => [k, v[i]])); }).filter(r => +r.season >= 2020 && +r.season <= 2025);
const nm = s => (s || '').toLowerCase().normalize('NFKD').replace(/[^a-z ]/g, '').replace(/\b(jr|sr|ii|iii|iv)\b/g, '').replace(/\s+/g, ' ').trim();
const col = s => nm(s).replace(/\bstate\b/, 'st').replace(/\buniversity\b|\bof\b/g, '').trim();
const mean = xs => xs.reduce((a, b) => a + b, 0) / xs.length;
function ols(X, y) {
  const k = X[0].length + 1, A = [...Array(k)].map(() => Array(k).fill(0)), b = Array(k).fill(0);
  X.forEach((r, i) => { const x = [1, ...r]; for (let p = 0; p < k; p++) { b[p] += x[p] * y[i]; for (let q = 0; q < k; q++) A[p][q] += x[p] * x[q]; } });
  for (let i = 0; i < k; i++) { const piv = A[i][i]; for (let j = i; j < k; j++) A[i][j] /= piv; b[i] /= piv; for (let r = 0; r < k; r++) if (r !== i) { const f = A[r][i]; for (let j = i; j < k; j++) A[r][j] -= f * A[i][j]; b[r] -= f * b[i]; } }
  return b;
}
const r3 = x => x == null || !isFinite(x) ? null : Math.round(x * 1000) / 1000;

// z of one stat per row: regressed by volume toward the qualifiers' mean, standardized on the qualifiers; rows under
// the gate get a z only when their snaps reach `min` (min = Infinity: today's board)
function zs(rows, val, vol, half, min) {
  const out = new Map();
  for (const s of new Set(rows.map(r => r.season))) {
    const all = rows.filter(r => r.season === s).map(r => ({ r, v: num(val(r)), n: Math.max(0, num(vol(r)) ?? 0) })).filter(x => x.v != null);
    const pool = all.filter(x => x.r._v >= GATE);
    if (pool.length < 20) continue;
    const nw = pool.reduce((a, x) => a + x.n, 0), m = nw ? pool.reduce((a, x) => a + x.n * x.v, 0) / nw : mean(pool.map(x => x.v));
    for (const x of all) x.reg = m + (x.v - m) * x.n / (x.n + half);
    const mm = mean(pool.map(x => x.reg)), sd = Math.sqrt(mean(pool.map(x => (x.reg - mm) ** 2))) || 1;
    for (const x of all) if (x.r._v >= GATE || x.r._v >= min) out.set(x.r, (x.reg - mm) / sd);
  }
  return out;
}

const out = { asof: new Date().toISOString().slice(0, 10), method: 'see scripts/cfb_lowsnap_research.mjs', gate: GATE, positions: {}, pooled: {} };
const pooled = {};
for (const g of ['QB', 'RB', 'TE', 'EDGE', 'DL', 'LB']) {
  const rows = JSON.parse(fs.readFileSync(path.join(CACHE, `pfn_${g}.json`))).filter(r => r.division === 'FBS');
  const snaps = r => num(r.snapsQ) ?? num(r.snaps) ?? ((num(r.gp) ?? num(r.gamesQ) ?? 0) * SPG[g]);
  const cz = {}; for (const r of rows) (cz[r.season] ||= []).push(r.score);
  for (const [s, xs] of Object.entries(cz)) { const m = mean(xs); cz[s] = [m, Math.sqrt(mean(xs.map(x => (x - m) ** 2)))]; }
  for (const r of rows) { r._z = (r.score - cz[r.season][0]) / cz[r.season][1]; r._v = snaps(r); }
  const byId = {}; for (const r of rows) (byId[r.id] ||= {})[r.season] = r;
  const P = [];
  for (const by of Object.values(byId)) {
    const last = Math.max(...Object.keys(by).map(Number)); if (last > 2022) continue;
    const r = by[last], D = last + 1, cand = picks.filter(p => nm(p.pfr_player_name) === nm(r.name) && NFLPOS[g].includes(p.position));
    const pk = cand.find(p => +p.season === D && col(p.college).split(' ')[0] === col(r.team).split(' ')[0]) || cand.find(p => +p.season === D);
    if (!pk && cand.some(p => +p.season > D)) continue;
    let a = 0, d = 0; W.forEach((w, k) => { const x = by[last - k]; if (x) { a += w * x._v * x._z; d += w * x._v; } });
    P.push({ last, row: r, prod: a / (d + K), av: pk ? (+pk.w_av || 0) / (NFL_THROUGH - D + 1) : 0, low: r._v < GATE });
  }
  // the stat term at each min (Infinity = today's 100-snap gate)
  const term = min => {
    const parts = [];
    for (const [k, w] of Object.entries(FV_BADGE.w[g] || {})) {
      const b = BADGES[g].find(x => x[0] === k); parts.push([w, zs(rows, b[2], b[3], b[4], min), FV_BADGE.cap, 'b']);
    }
    for (const [, [w, val, vol, half]] of Object.entries(FV_XV[g] || {})) parts.push([w, zs(rows, val, vol, half, min), FV_XV.cap, 'x']);
    return p => {
      let b = 0, x = 0;
      for (const [w, z, , t] of parts) { const v = z.get(p.row); if (v != null) { if (t === 'b') b += w * v; else x += w * v; } }
      return Math.max(-FV_BADGE.cap, Math.min(FV_BADGE.cap, b)) + Math.max(-FV_XV.cap, Math.min(FV_XV.cap, x));
    };
  };
  const res = { n: P.length, low: P.filter(p => p.low).length, lowDrafted: P.filter(p => p.low && p.av > 0).length, runs: {} };
  const err = {};
  for (const min of [Infinity, ...MINS]) {
    const T = term(min), e = new Map();
    for (const s of [...new Set(P.map(p => p.last))]) {
      const tr = P.filter(p => p.last !== s), te = P.filter(p => p.last === s);
      const b = ols(tr.map(p => [p.prod, T(p)]), tr.map(p => p.av));
      for (const p of te) e.set(p, (p.av - b[0] - b[1] * p.prod - b[2] * T(p)) ** 2);
    }
    err[min] = e;
    const lows = P.filter(p => p.low), moved = lows.filter(p => T(p) !== 0).length;
    res.runs[min === Infinity ? 'gate' : `min${min}`] = { sse: r3([...e.values()].reduce((a, b) => a + b, 0)), sseLow: r3(lows.reduce((a, p) => a + e.get(p), 0)), lowWithTerm: moved };
  }
  out.positions[g] = res;
  for (const p of P) for (const min of [Infinity, ...MINS]) ((pooled[min] ||= []).push({ e: err[min].get(p), low: p.low, g, last: p.last }));
  console.log(g, JSON.stringify(res));
}
// pooled: each min against today's gate, paired by player; t over players and the per-season split
const base = pooled[Infinity];
for (const min of MINS) {
  const d = pooled[min].map((x, i) => base[i].e - x.e), m = mean(d), sd = Math.sqrt(mean(d.map(v => (v - m) ** 2)) * d.length / (d.length - 1));
  const dl = d.filter((_, i) => base[i].low), ml = mean(dl), sl = Math.sqrt(mean(dl.map(v => (v - ml) ** 2)) * dl.length / (dl.length - 1));
  const bySeason = {}; d.forEach((v, i) => { const s = base[i].last; bySeason[s] = (bySeason[s] || 0) + v; });
  out.pooled[`min${min}`] = { n: d.length, gain: r3(d.reduce((a, b) => a + b, 0)), t: r3(m / (sd / Math.sqrt(d.length))), lowN: dl.length, lowGain: r3(dl.reduce((a, b) => a + b, 0)),
    lowT: r3(ml / (sl / Math.sqrt(dl.length))), seasonsWon: Object.values(bySeason).filter(v => v > 0).length, bySeason: Object.fromEntries(Object.entries(bySeason).map(([k, v]) => [k, r3(v)])) };
}
console.log(JSON.stringify(out.pooled, null, 1));
fs.writeFileSync(OUT, JSON.stringify(out, null, 1) + '\n');
