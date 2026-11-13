// Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
// The live model's current ratings and the next FBS-FCS games, to compare two settings: node live_check.mjs out.json
import zlib from 'node:zlib'; import fs from 'node:fs';
import { liveInput } from '../../cfb_espn_md.mjs';
import { runModel, HIST_FIT } from '../../cfb_model.mjs';
const ROOT = new URL('../../../', import.meta.url).pathname;
const data = liveInput(2026);
data.roster = JSON.parse(fs.readFileSync(ROOT + 'scripts/data/cfb_roster_feats.json', 'utf8')).feats;
data.pfnRet = JSON.parse(fs.readFileSync(ROOT + 'scripts/.cache/cfb/ret_war.json', 'utf8'));
data.weather = {};
data.fpi = JSON.parse(zlib.gunzipSync(fs.readFileSync(ROOT + 'scripts/data/public_ratings/cfb_fpi.json.gz')));
const mdl = await runModel(data, 2026, { hist: HIST_FIT, sim: false });
const name = {}; for (const g of data.games[2026]) { name[g.homeId] = g.homeTeam; name[g.awayId] = g.awayTeam; }
const rk = Object.entries(mdl.rating).sort((a, b) => b[1] - a[1]).map(([t, v], i) => ({ rank: i + 1, team: name[t], rating: +v.toFixed(2) }));
const up = data.games[2026].filter(g => !g.completed && (g.homeClassification === 'fcs') !== (g.awayClassification === 'fcs')).slice(0, 12)
  .map(g => { const p = mdl.predict(g.id); return { g: g.awayTeam + ' at ' + g.homeTeam, m: p && +p.margin.toFixed(1), parts: p && p.parts }; });
fs.writeFileSync(process.argv[2], JSON.stringify({ extra: mdl.report.extra, beta: mdl.report.beta, rk, up }));
console.log(mdl.report.extra, JSON.stringify(mdl.report.beta), JSON.stringify(up.slice(0, 3)));
