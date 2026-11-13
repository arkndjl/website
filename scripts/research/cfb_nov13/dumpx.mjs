// Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
// dump every walk-forward game's inputs and margins (research): node dumpx.mjs out.json
import zlib from 'node:zlib'; import fs from 'node:fs';
import { liveInput } from '../../cfb_espn_md.mjs';
import { runModel, HIST_FIT } from '../../cfb_model.mjs';
const ROOT = new URL('../../../', import.meta.url).pathname;
const data = liveInput(2026);
data.roster = JSON.parse(fs.readFileSync(ROOT + 'scripts/data/cfb_roster_feats.json', 'utf8')).feats;
data.pfnRet = JSON.parse(fs.readFileSync(ROOT + 'scripts/.cache/cfb/ret_war.json', 'utf8'));
data.weather = {};
data.fpi = JSON.parse(zlib.gunzipSync(fs.readFileSync(ROOT + 'scripts/data/public_ratings/cfb_fpi.json.gz')));
const mdl = await runModel(data, 2026, { hist: { ...HIST_FIT, wf: true }, sim: false });
const out = mdl.wf.map(q => ({ id: q.r.id, S: q.r.S, w: q.r.w, date: q.r.date, h: q.r.h, a: q.r.a, hn: q.r.hn, an: q.r.an, hc: q.r.hc, ac: q.r.ac, n: q.r.n, conf: q.r.conf, hconf: q.r.hconf, aconf: q.r.aconf, res: q.r.m, tot: q.r.tot, L: q.r.close, T: q.r.closeTot, Lo: q.r.open,
  x: q.x.map(v => +v.toFixed(4)), g: q.g, m: q.m, m0: q.m0, ek: q.ek, ld: q.ld, sigma: q.sigma, tm: q.tm, tmr: q.tmr }));
fs.writeFileSync(process.argv[2], JSON.stringify({ feats: ['elo', 'net', 'home', 'rest', 'tz', 'dist', 'alt', 'fcs', 'st', ...HIST_FIT.extra], rows: out, beta: mdl.report?.beta || null }));
console.log(out.length, HIST_FIT.extra);
