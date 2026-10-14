// History for the game-model backtest (scripts/cfb_game_backtest.mjs): CFBD seasons the live model doesn't pull
// (games, advanced box scores, drives, lines, talent, returning production, SP+, recruiting classes) and per-game
// passing lines (who started at QB). Each file is pulled once into scripts/.cache/cfb/hist/. Needs CFBD_API_KEY.
//   node scripts/cfb_game_history.mjs [first season] [last season]
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { slimDrives } from './cfb_model.mjs';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const DIR = path.join(ROOT, 'scripts', '.cache', 'cfb', 'hist');
fs.mkdirSync(DIR, { recursive: true });
const [A = 2015, B = 2026] = process.argv.slice(2).map(Number);
const QB_FROM = +(process.env.QB_FROM || 2022), MIN_LEFT = +(process.env.MIN_LEFT || 300);
let left = null, calls = 0;
async function cfbd(q) {
  const r = await fetch(`https://api.collegefootballdata.com/${q}`, { headers: { Authorization: `Bearer ${process.env.CFBD_API_KEY}`, accept: 'application/json' } });
  calls++; const h = r.headers.get('x-calllimit-remaining'); if (h != null) left = +h;
  if (!r.ok) throw new Error(`CFBD ${r.status} ${q}`);
  return r.json();
}
async function once(name, q, f = x => x) {
  const p = path.join(DIR, name);
  if (fs.existsSync(p)) return JSON.parse(fs.readFileSync(p, 'utf8'));
  if (left != null && left < MIN_LEFT) { console.log(`skip ${name}: ${left} calls left`); return null; }
  try { const v = f(await cfbd(q)); fs.writeFileSync(p, JSON.stringify(v)); console.log(`${name} ${Array.isArray(v) ? v.length : ''} (${left ?? '?'} left)`); return v; }
  catch (e) { console.log(`${name}: ${e.message}`); return null; }
}
await once(`venues.json`, 'venues');
for (let S = A; S <= B; S++) {
  const games = await once(`games${S}.json`, `games?year=${S}&seasonType=both`);
  if (S < 2026) {
    await once(`adv${S}.json`, `stats/game/advanced?year=${S}&excludeGarbageTime=true`);
    await once(`drives${S}.json`, `drives?year=${S}`, slimDrives);
    await once(`lines${S}.json`, `lines?year=${S}`);
    await once(`sp${S}.json`, `ratings/sp?year=${S}`);
  }
  await once(`talent${S}.json`, `talent?year=${S}`);
  await once(`returning${S}.json`, `player/returning?year=${S}`);
  await once(`recruit${S}.json`, `recruiting/teams?year=${S}`);
  // per-game passing lines (C/ATT, yards, TD, INT by passer), a week at a time
  if (S >= QB_FROM && games) {
    const weeks = [...new Set(games.filter(g => g.completed).map(g => `${g.seasonType}|${g.week}`))];
    for (const k of weeks) { const [t, w] = k.split('|'); if (S === 2026) continue; await once(`pass${S}${t[0]}${w}.json`, `games/players?year=${S}&week=${w}&seasonType=${t}&category=passing`); }
  }
}
for (let S = A - 4; S < A; S++) await once(`recruit${S}.json`, `recruiting/teams?year=${S}`);
console.log(`${calls} calls, ${left ?? '?'} left this month`);
