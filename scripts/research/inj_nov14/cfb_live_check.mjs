// Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
// The live CFB model's upcoming margins with their market-disagreement points: node cfb_live_check.mjs (CFB_MDIS=0 off)
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
const up = data.games[2026].filter(g => !g.completed).map(g => { const p = mdl.predict(g.id); return p && { g: g.awayTeam + ' at ' + g.homeTeam, m: +p.margin.toFixed(1), mkt: p.parts?.mkt || 0 }; }).filter(Boolean);
const a = up.map(x => Math.abs(x.mkt));
console.log(up.length, 'games; mean |mkt|', (a.reduce((s, x) => s + x, 0) / a.length).toFixed(2), 'max', Math.max(...a));
console.log(JSON.stringify(up.sort((x, y) => Math.abs(y.mkt) - Math.abs(x.mkt)).slice(0, 8)));
