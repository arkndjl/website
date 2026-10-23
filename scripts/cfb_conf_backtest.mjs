// Hierarchical conference ratings (team model idea 5, scripts/conf_hier_research.py) as an input to the college game
// model, on the 2015-26 ESPN history (scripts/cfb_hist_backtest.mjs walk). The feature is the pregame home-minus-away
// rating gap by game id from scripts/.cache/cfb/conf_feat.json (python3 scripts/conf_hier_research.py cfbfeat): a ridge
// Massey on capped margins, each team its conference's effect plus its own deviation, both carried across seasons;
// '<v>_c' variants are the conference-effect gap alone (0 in conference games).
//   node scripts/cfb_conf_backtest.mjs
// Each variant on top of the shipped inputs (HIST_FIT.extra: p4, aggr, ret, gc), and in place of p4. Scored on the
// ESPN-only pooled model (tune 2017-20, held 2021-26) and the shipped model (tune 2021-22, held 2023-26), plus weeks
// 1-6 alone. Writes data/cfb_conf_backtest.json.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
process.env.ONLYSHIP = '1';
process.env.BT_OUT = path.join(ROOT, 'scripts', '.cache', 'cfb', 'hist_backtest_scratch.json');
const B = await import('./cfb_hist_backtest.mjs');
const { CAND, _internals: I, HIST_FIT } = await import('./cfb_model.mjs');
const FEAT = JSON.parse(fs.readFileSync(path.join(ROOT, 'scripts', '.cache', 'cfb', 'conf_feat.json'), 'utf8'));
const P = B.report.ship.P;
const T2 = S => S >= 2021 && S <= 2022, H2 = S => S >= 2023;
const RWP = process.env.RETWAR || path.join(ROOT, 'scripts', '.cache', 'cfb', 'ret_war.json');
I.setCtx({}, JSON.parse(fs.readFileSync(RWP, 'utf8')));
const shipX = HIST_FIT.extra, espnX = shipX.filter(k => k !== 'ret');
const chPool = B.chain('roster', 'pooled');
const SHIPFIT = HIST_FIT.fit || {};
const run = (extra, first, fit = {}) => { I.setExtra(extra); const o = B.predict(B.walkAll(chPool, P), { first, fit }); I.setExtra([]); return o; };
const baseE = run(espnX, 2016), baseS = run(shipX, 2020, SHIPFIT);
const early = o => o.filter(x => x.w <= 6);
const both = (a, b, t, h) => ({ ll: B.cmp(a, b, 'll', t, h), mae: B.cmp(a, b, 'ae', t, h), wk1to6: { ll: B.cmp(early(a), early(b), 'll', t, h), mae: B.cmp(early(a), early(b), 'ae', t, h) } });
const out = fs.existsSync(path.join(ROOT, 'data', 'cfb_conf_backtest.json')) ? JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'cfb_conf_backtest.json'), 'utf8')) : {};
Object.assign(out, { asof: new Date().toISOString().slice(0, 10), P, shipX }); out.variants ||= {};
// CORE=cv,cv,...: the hierarchy inside the efficiency ridge itself (cfb_model.mjs adjust, HIER), priors re-chained
if (process.env.CORE) {
  const conf = {};
  for (const r of B.rows) for (const [t, c, k] of [[r.h, r.hconf, r.hc], [r.a, r.aconf, r.ac]]) if (k === 'fbs' && c && !/Independent/.test(c)) (conf[r.S] ||= {})[t] = c;
  out.core = out.core || {};
  for (const cv of process.env.CORE.split(',').map(Number)) {
    I.setHier({ cv, conf });
    const ch = B.chain('roster', 'pooled');
    const go = (extra, first, fit = {}) => { I.setExtra(extra); const o = B.predict(B.walkAll(ch, P), { first, fit }); I.setExtra([]); return o; };
    const oE = go(espnX, 2016), oS = go(shipX, 2020, SHIPFIT), rS = go(shipX.filter(k => k !== 'p4'), 2020, SHIPFIT);
    I.setHier(null);
    out.core[cv] = { espnOnly: both(oE, baseE), shipped: both(oS, baseS, T2, H2), shippedNoP4: both(rS, baseS, T2, H2) };
    console.log('core', cv, JSON.stringify(out.core[cv]));
    fs.writeFileSync(path.join(ROOT, 'data', 'cfb_conf_backtest.json'), JSON.stringify(out, null, 1));
  }
  process.exit(0);
}
const ONLY = process.env.VARIANTS ? process.env.VARIANTS.split(',') : null;
for (const [v, map] of Object.entries(FEAT.variants).filter(([v]) => !ONLY || ONLY.includes(v))) {
  CAND.cf = { name: 'hierarchical conference rating', ctx: r => map[String(r.id)] ?? 0, x: 1 };
  const noP4 = xs => xs.filter(k => k !== 'p4');
  const oE = run([...espnX, 'cf'], 2016), oS = run([...shipX, 'cf'], 2020, SHIPFIT);
  const rE = run([...noP4(espnX), 'cf'], 2016), rS = run([...noP4(shipX), 'cf'], 2020, SHIPFIT);
  out.variants[v] = { params: FEAT.params[v],
    add: { espnOnly: both(oE, baseE), shipped: both(oS, baseS, T2, H2) },
    forP4: { espnOnly: both(rE, baseE), shipped: both(rS, baseS, T2, H2) } };
  console.log(v, JSON.stringify(out.variants[v]));
  fs.writeFileSync(path.join(ROOT, 'data', 'cfb_conf_backtest.json'), JSON.stringify(out, null, 1));
}
out.base = { espnOnly: B.split(baseE), shipped: B.split(baseS) };
fs.writeFileSync(path.join(ROOT, 'data', 'cfb_conf_backtest.json'), JSON.stringify(out, null, 1));
