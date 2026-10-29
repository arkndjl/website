// Fumble-neutral EPA inside the CFB game model (cfb_model.mjs FUMN): the model's own walk-forward on the 2015-26 ESPN
// history (scripts/cfb_hist_backtest.mjs machinery, ESPN-only inputs p4 and aggr, roster prior, pooled fit), raw EPA
// against fumble-neutral EPA, scored on the project split (tune 2017-20, held out 2021-26), paired per game, clustered.
// Pre-registered: ship when tune log loss t <= -1.5 and held out log loss and MAE not worse.
//   node scripts/cfb_fumble_test.mjs [espn_md.json.gz]   (md from `node scripts/cfb_espn_md.mjs 2015 2026`)
// -> data/cfb_fumble_test.json
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
process.env.ONLYSHIP = '1'; process.env.SHIPX = 'p4,aggr';
process.env.BT_OUT = path.join(os.tmpdir(), 'cfb_fumble_bt.json');
const { FUMN, _internals: I } = await import('./cfb_model.mjs');
const B = await import('./cfb_hist_backtest.mjs');
const P = { k: 20, eloHome: 55, lam: 1.5 };
const run = on => { FUMN.on = on; I.setExtra(['p4', 'aggr']); const o = B.predict(B.walkAll(B.chain('roster', 'pooled'), P)); I.setExtra([]); return o; };
const raw = run(false), neu = run(true);
const byS = Object.fromEntries(B.SEASONS.filter(S => S >= 2017).map(S => {
  const a = neu.filter(x => x.S === S), b = raw.filter(x => x.S === S);
  const m = xs => xs.reduce((s, v) => s + v, 0) / xs.length;
  return [S, { ll: Math.round((m(a.map(x => x.ll)) - m(b.map(x => x.ll))) * 1e5) / 1e5, mae: Math.round((m(a.map(x => x.ae)) - m(b.map(x => x.ae))) * 1e3) / 1e3 }];
}));
const res = { asof: new Date().toISOString().slice(0, 10), fumEpa: FUMN.e, raw: B.split(raw), neutral: B.split(neu), ll: B.cmp(neu, raw), mae: B.cmp(neu, raw, 'ae'),
  early: { ll: B.cmp(neu.filter(x => x.w <= 4), raw.filter(x => x.w <= 4)), mae: B.cmp(neu.filter(x => x.w <= 4), raw.filter(x => x.w <= 4), 'ae') }, bySeason: byS };
res.pass = res.ll.tune.t <= -1.5 && res.ll.held.d <= 0 && res.mae.held.d <= 0;
fs.writeFileSync(path.join(ROOT, 'data', 'cfb_fumble_test.json'), JSON.stringify(res, null, 1));
console.log(JSON.stringify(res, null, 1));
