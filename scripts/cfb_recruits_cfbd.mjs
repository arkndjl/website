// Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
// 247 composite high-school classes from CFBD (recruiting/players), for the CFB FV harnesses (scripts/cfb_fv_refit.mjs),
// in place of 247Sports' own pages, which now sit behind a bot check. One call a class; classes already in the
// cfbhist cache (scripts/.cache/cfb/hist/recruits-<y>-HighSchool.json) cost nothing. Stops below MIN_LEFT calls (500).
//   CFBD_API_KEY=... node scripts/cfb_recruits_cfbd.mjs [first] [last]  -> scripts/data/cfb_recruits_cfbd.json.gz
// Rows: [name, rating, stars, ranking, committedTo, height in, weight lb], by class, in ranking order.
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import { fileURLToPath } from 'node:url';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const DIR = path.join(ROOT, 'scripts', '.cache', 'cfb', 'hist'), OUT = path.join(ROOT, 'scripts', 'data', 'cfb_recruits_cfbd.json.gz');
const [A = 2009, B = 2025] = process.argv.slice(2).map(Number), MIN_LEFT = +(process.env.MIN_LEFT || 500);
fs.mkdirSync(DIR, { recursive: true });
let left = null, calls = 0;
const out = fs.existsSync(OUT) ? JSON.parse(zlib.gunzipSync(fs.readFileSync(OUT))) : {};
for (let y = A; y <= B; y++) {
  const f = path.join(DIR, `recruits-${y}-HighSchool.json`);
  let v = fs.existsSync(f) ? JSON.parse(fs.readFileSync(f, 'utf8')) : null;
  if (!v) {
    if (left != null && left < MIN_LEFT) { console.log(`skip ${y}: ${left} calls left`); continue; }
    const r = await fetch(`https://api.collegefootballdata.com/recruiting/players?year=${y}&classification=HighSchool`, { headers: { Authorization: `Bearer ${process.env.CFBD_API_KEY}`, accept: 'application/json' } });
    calls++; const h = r.headers.get('x-calllimit-remaining'); if (h != null) left = +h;
    if (!r.ok) { console.log(`${y}: CFBD ${r.status}`); continue; }
    v = await r.json(); fs.writeFileSync(f, JSON.stringify(v));
  }
  out[y] = v.filter(x => x.name && x.rating).sort((p, q) => (p.ranking ?? 1e9) - (q.ranking ?? 1e9))
    .map(x => [x.name, x.rating, x.stars ?? 0, x.ranking ?? null, x.committedTo ?? '', x.height ?? null, x.weight ?? null]);
  console.log(y, out[y].length, `(${left ?? '?'} left)`);
}
fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT, zlib.gzipSync(JSON.stringify(out)));
console.log('wrote', OUT, 'classes', Object.keys(out).length, 'CFBD calls', calls);
