// History for the game-model backtest (scripts/cfb_game_backtest.mjs): CFBD seasons the live model doesn't pull
// (games, advanced box scores, drives, lines, talent, returning production, SP+, recruiting classes) and per-game
// passing lines (who started at QB). Each file is pulled once into scripts/.cache/cfb/hist/. Needs CFBD_API_KEY.
// EXTRA=1 also pulls player-level history for the FV and transfer models (one call a season each): player PPA, usage,
// season stats, opponent-adjusted EPA (WEPA), draft picks, portal, older recruit classes, and the coach list; SIT_FROM
// (e.g. 2021) adds CFBD play-by-play reduced to situational splits (sit2-*, as fetch_cfb.mjs builds) back to that season.
// Stops once fewer than MIN_LEFT calls remain (default 500: the rest of the month's board runs need ~15 a full run).
//   node scripts/cfb_game_history.mjs [first season] [last season]
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { slimDrives, sitByGame } from './cfb_model.mjs';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const DIR = path.join(ROOT, 'scripts', '.cache', 'cfb', 'hist');
fs.mkdirSync(DIR, { recursive: true });
const [A = 2015, B = 2026] = process.argv.slice(2).map(Number);
const QB_FROM = +(process.env.QB_FROM || 2022), MIN_LEFT = +(process.env.MIN_LEFT || 500);
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
async function info() {
  try { const r = await fetch('https://api.collegefootballdata.com/info', { headers: { Authorization: `Bearer ${process.env.CFBD_API_KEY}`, accept: 'application/json' } });
    const v = await r.json(); if (v?.remainingCalls != null) left = v.remainingCalls; return v; } catch (e) { return { error: e.message }; }
}
console.log('CFBD info at start', JSON.stringify(await info()));
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
if (process.env.EXTRA) {
  await once('coaches.json', 'coaches?minYear=2000');
  for (let S = A; S <= B; S++) {
    const done = S < 2026;
    if (done) {
      await once(`ppaplayers${S}.json`, `ppa/players/season?year=${S}&excludeGarbageTime=true`);
      await once(`usage${S}.json`, `player/usage?year=${S}&excludeGarbageTime=true`);
      await once(`pstats${S}.json`, `stats/player/season?year=${S}`);
      for (const k of ['passing', 'rushing']) await once(`wepa${k}${S}.json`, `wepa/players/${k}?year=${S}`);
      if (S >= 2021) await once(`portal${S}.json`, `player/portal?year=${S}`);
    }
    await once(`draft${S}.json`, `draft/picks?year=${S}`);
  }
  // high school classes before fetch_cfb.mjs's eight-year window (players on the 2019-23 boards)
  for (let y = A - 4; y < 2019; y++) await once(`recruits-${y}-HighSchool.json`, `recruiting/players?year=${y}&classification=HighSchool`);
}
const SIT_FROM = +(process.env.SIT_FROM || 0);
if (SIT_FROM) for (let S = SIT_FROM; S <= Math.min(B, 2024); S++) {
  const f = path.join(DIR, `games${S}.json`), games = fs.existsSync(f) ? JSON.parse(fs.readFileSync(f, 'utf8')) : [];
  const weeks = [...new Set(games.filter(g => g.completed).map(g => `${g.seasonType}|${g.week}`))].map(k => k.split('|'));
  for (const [t, w] of weeks) await once(`sit2-${S}${t === 'postseason' ? 'p' : 'w'}${w}.json`, `plays?year=${S}&week=${w}&seasonType=${t}&classification=fbs`,
    v => sitByGame(v.map(p => ({ g: p.gameId, o: p.offense, q: p.period, ytg: p.yardsToGoal, dn: p.down, ds: p.distance, y: p.yardsGained, t: p.playType,
      sm: p.offenseScore != null && p.defenseScore != null ? p.offenseScore - p.defenseScore : null }))));
}
console.log('CFBD info at end', JSON.stringify(await info()));
console.log(`${calls} calls, ${left ?? '?'} left this month`);
