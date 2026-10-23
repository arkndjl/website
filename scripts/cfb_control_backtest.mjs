// Game-control ratings (scripts/control_ratings.py) as an input to the college game model, on the 2015-26 ESPN
// history (scripts/cfb_hist_backtest.mjs walk). The feature is the pregame home-minus-away control rating, by game
// id, from scripts/.cache/cfb/control_feat.json (python3 scripts/control_ratings.py cfbfeat <md> [variant...]).
//   node scripts/cfb_control_backtest.mjs [espn_md.json.gz]
// Scored two ways: on the ESPN-only pooled model (p4, aggr; tune 2017-20, held 2021-26) and on the shipped model
// (HIST_FIT: p4, aggr, ret; tune 2021-22, held 2023-26). Writes data/cfb_control_backtest.json.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
process.env.ONLYSHIP = '1';
process.env.BT_OUT = path.join(ROOT, 'scripts', '.cache', 'cfb', 'hist_backtest_scratch.json');
const B = await import('./cfb_hist_backtest.mjs');
const { CAND, _internals: I, HIST_FIT, fpiGap, fpiStack, phi } = await import('./cfb_model.mjs');
const zlib = await import('node:zlib');
const FEAT = JSON.parse(fs.readFileSync(path.join(ROOT, 'scripts', '.cache', 'cfb', 'control_feat.json'), 'utf8'));
const P = B.report.ship.P;
const T2 = S => S >= 2021 && S <= 2022, H2 = S => S >= 2023;
const out = { asof: new Date().toISOString().slice(0, 10), P, variants: {} };
const chPool = B.chain('roster', 'pooled');
// PFN returning production (scripts/cfb_ret_war.mjs) for the shipped model; without it only the ESPN-only model is scored
const RWP = process.env.RETWAR || path.join(ROOT, 'scripts', '.cache', 'cfb', 'ret_war.json'), HAVE_RW = fs.existsSync(RWP);
if (HAVE_RW) I.setCtx({}, JSON.parse(fs.readFileSync(RWP, 'utf8')));
const shipX = ['p4', 'aggr', 'ret'], espnX = ['p4', 'aggr'];
// the shipped margin fit (HIST_FIT.fit: results + .25 x the close) for the shipped model; ESPN-only stays results-fit
const run = (extra, first, fit = {}) => { I.setExtra(extra); const o = B.predict(B.walkAll(chPool, P), { first, fit }); I.setExtra([]); return o; };
const SHIPFIT = HIST_FIT.fit || {};
const baseE = run(espnX, 2016), baseS = HAVE_RW ? run(shipX, 2020, SHIPFIT) : null;
// ESPN FPI stacked on top (HIST_FIT.fpi, cfb_model.mjs fpiStack), scored 2024-26 where the stack has a season to fit on
const FPIF = path.join(ROOT, 'scripts', 'data', 'public_ratings', 'cfb_fpi.json.gz');
const gap = HIST_FIT.fpi && fs.existsSync(FPIF) ? fpiGap(JSON.parse(zlib.gunzipSync(fs.readFileSync(FPIF))), HIST_FIT.fpi.from) : null;
const byId = Object.fromEntries(B.rows.map(r => [r.id, r]));
const llf = (p, y) => { p = Math.min(1 - 1e-9, Math.max(1e-9, p)); return -(y * Math.log(p) + (1 - y) * Math.log(1 - p)); };
function stacked(o) {
  const rows = o.map(x => ({ r: byId[x.id], m: x.m, x }));
  const out = [];
  for (const S of [2024, 2025, 2026]) {
    const st = fpiStack(rows, gap, S, HIST_FIT.fpi.from);
    for (const q of rows.filter(q => q.r.S === S)) {
      const g = st ? gap(q.r) : null, m = g != null ? st.a * q.m + st.b * g : q.m, sg = g != null ? st.sigma : null;
      const ph = sg ? phi(m / sg) : q.x.ph;
      out.push({ ...q.x, m, ph, ll: llf(ph, q.x.y), ae: Math.abs(q.x.res - m) });
    }
  }
  return out;
}
const T3 = S => S === 2024, H3 = S => S >= 2025;
const ONLY = process.env.VARIANTS ? process.env.VARIANTS.split(',') : null;
for (const [v, map] of Object.entries(FEAT.variants).filter(([v]) => !ONLY || ONLY.includes(v))) {
  CAND.gc = { name: 'game control rating', ctx: r => map[String(r.id)] ?? 0, x: 1 };
  const oE = run([...espnX, 'gc'], 2016), oS = HAVE_RW ? run([...shipX, 'gc'], 2020, SHIPFIT) : null;
  const fS = oS && gap ? stacked(oS) : null, fB = fS ? stacked(baseS) : null;
  out.variants[v] = { params: FEAT.params[v], espnOnly: { ll: B.cmp(oE, baseE), mae: B.cmp(oE, baseE, 'ae') },
    shipped: oS && { ll: B.cmp(oS, baseS, 'll', T2, H2), mae: B.cmp(oS, baseS, 'ae', T2, H2) },
    withFpi: fS && { note: 'FPI stack fit on 2023 to S-1; 2024 / 2025-26', ll: B.cmp(fS, fB, 'll', T3, H3), mae: B.cmp(fS, fB, 'ae', T3, H3) } };
  console.log(v, JSON.stringify(out.variants[v]));
}
// head to head (H2H=a,b): variant a against variant b on the same model, and both columns together against b
if (process.env.H2H) {
  const [a, b] = process.env.H2H.split(','), V = FEAT.variants;
  CAND.gc = { name: 'game control rating', ctx: r => V[a][String(r.id)] ?? 0, x: 1 };
  CAND.gm = { name: 'margin rating, same scheme', ctx: r => V[b][String(r.id)] ?? 0, x: 1 };
  const A = run([...espnX, 'gc'], 2016), Bm = run([...espnX, 'gm'], 2016), AB = run([...espnX, 'gc', 'gm'], 2016);
  const As = HAVE_RW ? run([...shipX, 'gc'], 2020, SHIPFIT) : null, Bs = HAVE_RW ? run([...shipX, 'gm'], 2020, SHIPFIT) : null, ABs = HAVE_RW ? run([...shipX, 'gc', 'gm'], 2020, SHIPFIT) : null;
  out.h2h = { a, b, espnOnly: { aVsB: { ll: B.cmp(A, Bm), mae: B.cmp(A, Bm, 'ae') }, bothVsB: { ll: B.cmp(AB, Bm), mae: B.cmp(AB, Bm, 'ae') }, bothVsA: { ll: B.cmp(AB, A), mae: B.cmp(AB, A, 'ae') } },
    shipped: HAVE_RW && { aVsB: { ll: B.cmp(As, Bs, 'll', T2, H2), mae: B.cmp(As, Bs, 'ae', T2, H2) }, bothVsB: { ll: B.cmp(ABs, Bs, 'll', T2, H2), mae: B.cmp(ABs, Bs, 'ae', T2, H2) },
      bothVsA: { ll: B.cmp(ABs, As, 'll', T2, H2), mae: B.cmp(ABs, As, 'ae', T2, H2) } } };
  console.log('h2h', JSON.stringify(out.h2h));
}
out.base = { espnOnly: B.split(baseE), shipped: baseS && B.split(baseS) };
fs.writeFileSync(path.join(ROOT, 'data', 'cfb_control_backtest.json'), JSON.stringify(out, null, 1));
