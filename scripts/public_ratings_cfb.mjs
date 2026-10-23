// Public ratings stacked into the college game model (team model idea 9, Oct 23 2026): ESPN FPI from the snapshot
// published before each kickoff (scripts/public_ratings.py --cfb), as extra margin columns on top of the ESPN-history
// model (scripts/cfb_hist_backtest.mjs, pooled scheme, inputs p4 + aggr), entered on 2017-20, vetoed by 2021-26.
// FPI's weekly archive is sparse before 2023 (2019 has only the preseason run until December), so each column is
// also scored on 2023-26, where every week has a run. Also the closing-line target (harness lam) retest with the
// longer history.
//   ONLYSHIP=1 node scripts/public_ratings_cfb.mjs        # writes data/public_ratings_cfb.json
import zlib from 'node:zlib';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { _internals as I, phi, fitBeta } from './cfb_model.mjs';
import { paired } from './harness.mjs';

process.env.ONLYSHIP = '1';
process.env.BT_OUT ||= path.join(process.env.TMPDIR || '/tmp', 'cfb_hist_bt_scratch.json');
const BT = await import('./cfb_hist_backtest.mjs');
const { SEASONS, chain, walkAll, predict, cmp, split } = BT;
const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const FPI = Object.fromEntries(Object.entries(JSON.parse(zlib.gunzipSync(fs.readFileSync(path.join(ROOT, 'scripts', 'data', 'public_ratings', 'cfb_fpi.json.gz')))))
  .map(([S, v]) => [S, v.map(([lu, r]) => [Date.parse(lu), r])]));
const LAG = 6 * 3600e3;
// latest snapshot published LAG before kickoff, its age in days, and the season's first (preseason) run
function snap(r) {
  const list = FPI[r.S] || [], k = Date.parse(r.date) - LAG;
  let best = null; for (const s of list) if (s[0] <= k) best = s;
  const pre = list[0] && list[0][0] <= k ? list[0][1] : null;
  return { cur: best?.[1], age: best ? (k - best[0]) / 864e5 : null, pre };
}
const diff = (R, r) => R && R[r.h] != null && R[r.a] != null ? R[r.h] - R[r.a] : null;
const COLS = {
  fpi: r => diff(snap(r).cur, r) ?? 0,                                        // the latest run, any age
  fpiFresh: r => { const s = snap(r); return s.age != null && s.age <= 10 ? diff(s.cur, r) ?? 0 : 0; },  // a run from the last 10 days only
  fpiPre: r => diff(snap(r).pre, r) ?? 0,                                     // the preseason run all season
  fpiPreFade: r => (diff(snap(r).pre, r) ?? 0) * Math.max(0, 1 - (r.w - 1) / 8),
};
const T1 = S => S >= 2017 && S <= 2020, H1 = S => S >= 2021, H23 = S => S >= 2023, T21 = S => S >= 2021 && S <= 2022;
const mean = xs => xs.reduce((a, b) => a + b, 0) / Math.max(1, xs.length);
const r4 = x => Math.round(x * 1e4) / 1e4;

// the shipped model (cfb_model.mjs HIST_FIT: p4, aggr, ret with PFN returning production from scripts/cfb_ret_war.mjs)
const P = { k: 20, eloHome: 55, lam: 1.5 };
const RWP = path.join(ROOT, 'scripts', '.cache', 'cfb', 'ret_war.json');
if (!fs.existsSync(RWP)) throw new Error('run node scripts/cfb_ret_war.mjs first');
I.setCtx({}, JSON.parse(fs.readFileSync(RWP, 'utf8')));
I.setExtra(['p4', 'aggr', 'ret']);
const ch = chain('roster', 'pooled'), W = walkAll(ch, P);
I.setExtra([]);
const cover = {};
for (const S of SEASONS) { const ps = W[S] || []; const n = ps.filter(p => snap(p.r).cur && diff(snap(p.r).cur, p.r) != null).length; cover[S] = { games: ps.length, withFpi: n,
  freshShare: r4(ps.filter(p => { const s = snap(p.r); return s.age != null && s.age <= 10; }).length / Math.max(1, ps.length)) }; }
console.log('coverage', JSON.stringify(cover));
const base = predict(W);
const out = { asof: new Date().toISOString().slice(0, 10), note: 'FPI columns on top of the shipped ESPN-history model (HIST_FIT: p4, aggr, ret); tune 2017-20, held 2021-26; also 2023-26 (weekly FPI runs)',
  coverage: cover, base: split(base), cols: {} };
const res = {};
for (const [k, f] of Object.entries(COLS)) {
  const o = predict(W, { extra: p => [f(p.r)] });
  res[k] = o;
  const w = fitBeta(SEASONS.filter(S => S >= 2016 && S <= 2025).flatMap(S => W[S].map(p => ({ r: p.r, x: [...p.x, f(p.r)] })))).beta.at(-1);
  out.cols[k] = { ll: cmp(o, base), mae: cmp(o, base, 'ae'), ll2326: cmp(o, base, 'll', T21, H23), mae2326: cmp(o, base, 'ae', T21, H23), weight2016to25: r4(w) };
  console.log(k, JSON.stringify(out.cols[k]));
}
// FPI runs before 2023 can't be trusted as point-in-time: several "preseason" runs carry the final values (2019's
// Aug 24 run has Ohio State 33.4 and LSU 27.6, the December numbers; Jul 30 had Ohio State 14.1), and the any-age
// column gains 1.7 points of MAE on 2017-20, which only a leak does. From 2023 every week has a fresh run that moves
// plausibly. So the clean test: stack the base model's walk-forward margin with the FPI gap, weights fit on 2023 to
// S-1, scored on S = 2024, 2025, 2026 (base: the same games, the model alone)
const CLEAN = 2023;
function stack(cols, fitSeasons, S, ridge = 0) {
  const pred = new Map(base.map(o => [o.id, o]));
  const rowsOf = s => W[s].map(p => ({ p, o: pred.get(p.r.id), f: cols.map(c => c(p.r)) })).filter(z => z.o && z.f.every(v => v != null));
  const tr = fitSeasons.flatMap(rowsOf);
  const X = tr.map(z => [z.o.m, ...z.f]), y = tr.map(z => Math.max(-45, Math.min(45, z.p.r.m)));
  const k = X[0].length, A = Array.from({ length: k }, (_, i) => Array.from({ length: k }, (_, j) => X.reduce((a, x) => a + x[i] * x[j], 0) + (i === j && i > 0 ? ridge : 0))),
    b = Array.from({ length: k }, (_, i) => X.reduce((a, x, n) => a + x[i] * y[n], 0));
  const beta = solve(A, b);
  const res = tr.map((z, n) => y[n] - I.dot(beta, X[n])), sM = Math.sqrt(res.reduce((a, v) => a + v * v, 0) / res.length);
  // win chance sd fit on the training games' outcomes, as fitBeta does
  const llAt = (sg, zs) => zs.reduce((a, z) => { const q = Math.min(1 - 1e-9, Math.max(1e-9, phi(I.dot(beta, [z.o.m, ...z.f]) / sg))), yy = z.p.r.m > 0 ? 1 : z.p.r.m < 0 ? 0 : 0.5; return a - yy * Math.log(q) - (1 - yy) * Math.log(1 - q); }, 0);
  let sg = sM; for (let f = 0.5; f <= 1.2001; f += 0.02) if (llAt(sM * f, tr) < llAt(sg, tr)) sg = sM * f;
  return { beta, rows: rowsOf(S).map(z => { const m = I.dot(beta, [z.o.m, ...z.f]), ph = phi(m / sg), yy = z.p.r.m > 0 ? 1 : z.p.r.m < 0 ? 0 : 0.5;
    return { id: z.p.r.id, S, m, ll: -(yy * Math.log(Math.max(1e-9, ph)) + (1 - yy) * Math.log(Math.max(1e-9, 1 - ph))), ae: Math.abs(z.p.r.m - m), day: z.p.r.date.slice(0, 10), ht: z.p.r.h + '|' + S, close: z.p.r.close, res: z.p.r.m }; }) };
}
function solve(A, b) {
  const n = b.length, M = A.map((r, i) => [...r, b[i]]);
  for (let i = 0; i < n; i++) { let p = i; for (let j = i + 1; j < n; j++) if (Math.abs(M[j][i]) > Math.abs(M[p][i])) p = j; [M[i], M[p]] = [M[p], M[i]];
    for (let j = i + 1; j < n; j++) { const f = M[j][i] / M[i][i]; for (let k = i; k <= n; k++) M[j][k] -= f * M[i][k]; } }
  const x = Array(n).fill(0); for (let i = n - 1; i >= 0; i--) { let s = M[i][n]; for (let k = i + 1; k < n; k++) s -= M[i][k] * x[k]; x[i] = s / M[i][i]; } return x;
}
const fpiClean = r => { if (r.S < CLEAN) return null; const s = snap(r); return s.cur ? diff(s.cur, r) : null; };
const fpiCleanFresh = r => { if (r.S < CLEAN) return null; const s = snap(r); return s.cur && s.age <= 10 ? diff(s.cur, r) : null; };
out.clean = {};
const pt = (a, b, k) => { const x = paired(a.map(z => z[k]), b.map(z => z[k]), [b.map(z => z.day), b.map(z => z.ht)]); return { d: r4(x.d), t: Math.round(x.t * 100) / 100, n: x.n }; };
for (const [name, cols] of Object.entries({ fpi: [fpiClean], fpiFresh: [fpiCleanFresh] })) {
  const A = [], B = [], wts = {};
  for (const S of [2024, 2025, 2026]) {
    const fit = SEASONS.filter(s => s >= CLEAN && s < S);
    const st = stack(cols, fit, S), b0 = stack([], fit, S);
    const ids = new Set(st.rows.map(z => z.id));
    A.push(...st.rows); B.push(...b0.rows.filter(z => ids.has(z.id))); wts[S] = st.beta.map(r4);
  }
  const lined = z => z.close != null;
  const T = z => z.S === 2024, Hh = z => z.S >= 2025;
  out.clean[name] = { ll: pt(A, B, 'll'), mae: pt(A, B, 'ae'), tune2024: { ll: pt(A.filter(T), B.filter(T), 'll'), mae: pt(A.filter(T), B.filter(T), 'ae') },
    held2025to26: { ll: pt(A.filter(Hh), B.filter(Hh), 'll'), mae: pt(A.filter(Hh), B.filter(Hh), 'ae') }, ll2026: pt(A.filter(z => z.S === 2026), B.filter(z => z.S === 2026), 'll'),
    weights: wts, maeStack: r4(mean(A.map(z => z.ae))), maeBase: r4(mean(B.map(z => z.ae))), maeClose: r4(mean(A.filter(lined).map(z => Math.abs(z.res - z.close)))) };
  console.log('clean', name, JSON.stringify(out.clean[name]));
}
// the same gap as a column inside the margin fit (0 before 2023 and where a side has no run), weights pooled from 2016
{
  const o = predict(W, { extra: p => [fpiClean(p.r) ?? 0] }), bb = base;
  const ids = new Set(o.filter(z => z.S >= 2024).map(z => z.id));
  const A = o.filter(z => z.S >= 2024), B = bb.filter(z => z.S >= 2024 && ids.has(z.id));
  const T = z => z.S === 2024, Hh = z => z.S >= 2025;
  out.column = { ll: pt(A, B, 'll'), mae: pt(A, B, 'ae'), tune2024: { ll: pt(A.filter(T), B.filter(T), 'll'), mae: pt(A.filter(T), B.filter(T), 'ae') },
    held2025to26: { ll: pt(A.filter(Hh), B.filter(Hh), 'll'), mae: pt(A.filter(Hh), B.filter(Hh), 'ae') } };
  console.log('column', JSON.stringify(out.column));
}
// the closing-line target (PR #349's CFB near miss, season-swap CV only then): fitBeta lam on the pooled margin fit,
// home calibrated, now walk-forward on 2017-20 / 2021-26
out.closeTarget = [];
const home = I.BASE_FEATS.indexOf('home');
for (const lam of [0.25, 0.5, 1, 2, Infinity]) for (const calib of [[], [home]]) {
  const o = predict(W, { fit: { lam, calib } });
  const row = { lam: isFinite(lam) ? lam : 'inf', calib: calib.length ? 'home' : 'scale', ll: cmp(o, base), mae: cmp(o, base, 'ae'), ...split(o) };
  out.closeTarget.push(row); console.log('close', JSON.stringify(row));
}
fs.writeFileSync(path.join(ROOT, 'data', 'public_ratings_cfb.json'), JSON.stringify(out, null, 1));
