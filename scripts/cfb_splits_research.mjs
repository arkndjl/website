// Down-and-distance and kicking splits as CFB game-model inputs (CAND entries marked sit in cfb_model.mjs), on the
// live model's own selection (runModel: season-swap CV log loss, forward selection at t <= -1.5).
//   node scripts/cfb_espn_plays.mjs md.json.gz plays.json.gz     # ESPN play-by-play, free (no CFBD quota)
//   node scripts/cfb_splits_research.mjs md.json.gz plays.json.gz # writes data/cfb_splits_research.json
// md.json.gz is the "cfb game research" workflow's dump. ESPN's plays run through the same sitByGame as CFBD's
// (3rd downs match CFBD's to 0.2%), and only the new counts (cb, kb) are merged in, so the base model is unchanged.
// Results, Oct 18 2026 (2025 and 2026 through week 7, 1,370 games): see the file; nothing new was selected.
import zlib from 'node:zlib';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { sitByGame, runModel } from './cfb_model.mjs';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const [mdPath, playsPath] = process.argv.slice(2);
const md = JSON.parse(zlib.gunzipSync(fs.readFileSync(mdPath)));
const pl = JSON.parse(zlib.gunzipSync(fs.readFileSync(playsPath)));
for (const S of Object.keys(md.sit)) { const e = sitByGame(pl[S]); for (const k in md.sit[S]) if (e[k]) Object.assign(md.sit[S][k], { cb: e[k].cb, kb: e[k].kb }); }
const tl = md.fvTalent, v = Object.values(tl), m = v.reduce((a, b) => a + b, 0) / v.length, s = Math.sqrt(v.reduce((a, b) => a + (b - m) ** 2, 0) / v.length);
const model = await runModel(md, 2026, { sitTest: true, talentZ: Object.fromEntries(Object.entries(tl).map(([k, x]) => [k, (x - m) / s])) });
const X = model.report.extraTest;
const { alone, steps, chosen, baseLogLoss, baseMae, final, market, n } = X;
fs.writeFileSync(path.join(ROOT, 'data', 'cfb_splits_research.json'), JSON.stringify({ n, baseLogLoss, baseMae, chosen, steps, final, market, alone }, null, 1));
console.log('chosen', chosen, JSON.stringify(steps));
for (const [k, a] of Object.entries(alone)) console.log(k.padEnd(7), a.t, a.dLogLoss, a.name);
