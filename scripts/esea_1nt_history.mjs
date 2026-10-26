#!/usr/bin/env node
// 1NT's whole FACEIT history (every official match the team has played: ESEA S52 on, cups, qualifiers),
// for the veto, ARK and round-total research. FACEIT's league search only reaches back a season, but each
// player's per-match stats go back years and name the team they played for, so every 1NT player's stats
// (data/esea.json all-time cache, plus the current roster) are walked back and filtered to "1NT"; each match
// found is then read in full: opponent, competition, every map's score and both teams' box scores.
// Written to research/esea_1nt_history.json.gz. Needs FACEIT_API_KEY (the esea research workflow has it).
//
//   FACEIT_API_KEY=... node scripts/esea_1nt_history.mjs
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const OUT = path.join(ROOT, 'research', 'esea_1nt_history.json.gz');
const KEY = process.env.FACEIT_API_KEY;
const API = 'https://open.faceit.com/data/v4';
const TEAM_ID = 'a6e9c61b-de50-47d4-9fc8-3f03a13c4d4a', TEAM = '1NT';
const SINCE = Date.parse(process.env.ESEA_SINCE || '2024-06-01') / 1000;
if (!KEY) { console.log('FACEIT_API_KEY not set'); process.exit(0); }

let calls = 0;
async function api(p) {
  for (let a = 0; a < 5; a++) {
    calls++;
    const r = await fetch(API + p, { headers: { Authorization: `Bearer ${KEY}`, Accept: 'application/json' } }).catch(() => null);
    if (!r || r.status === 429 || r.status >= 500) { await new Promise(s => setTimeout(s, 2000 * (a + 1))); continue; }
    if (!r.ok) return null;
    return r.json();
  }
  return null;
}
const num = v => (v == null || v === '' ? null : +String(v).replace('%', ''));
// a player's full map line, in fetch_esea.mjs's box-score cache order (boxLines)
const full = x => [num(x.Kills) || 0, num(x['Sniper Kills']) || 0, num(x['Entry Count']) || 0, num(x['Flash Count']) || 0, num(x['Utility Count']) || 0, (num(x['1v1Count']) || 0) + (num(x['1v2Count']) || 0),
  num(x.Deaths) || 0, num(x.Assists) || 0, num(x.ADR) || 0, num(x['Double Kills']) || 0, num(x['Triple Kills']) || 0, num(x['Quadro Kills']) || 0, num(x['Penta Kills']) || 0,
  num(x['Entry Wins']) || 0, num(x['1v1Wins']) || 0, num(x['1v2Wins']) || 0, num(x['Utility Damage']) || 0, num(x['Enemies Flashed']) || 0,
  num(x.MVPs) || 0, num(x['Flash Successes']) || 0, num(x['Utility Successes']) || 0, num(x['Clutch Kills']) || 0, num(x['Pistol Kills']) || 0,
  num(x.Headshots) || 0, num(x['1v1Count']) || 0, num(x['1v2Count']) || 0];

// ---- every player who has played for 1NT
const pids = new Set();
try { for (const id of Object.keys(JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'esea.json'), 'utf8')).allTime?.cache || {})) pids.add(id); } catch {}
for (const m of (await api(`/teams/${TEAM_ID}`))?.members || []) pids.add(m.user_id);
console.log(`${pids.size} players`);

// ---- their per-match stats, walked back to SINCE, kept where they played for 1NT
const found = new Map();   // match id -> { comp, at, players: Set }
for (const pid of pids) {
  let to = null, unit = 1, kept = 0;
  for (let req = 0; req < 40; req++) {
    const j = await api(`/players/${pid}/games/cs2/stats?limit=100${to ? `&to=${Math.floor(to / unit)}` : ''}`);
    const got = (j?.items || []).map(i => i.stats || {});
    if (!got.length && to && unit === 1) { unit = 1000; continue; }
    for (const st of got) {
      if (String(st.Team || '') !== TEAM) continue;
      const mid = st['Match Id']; if (!mid) continue;
      const f = found.get(mid) || { comp: st['Competition Id'] || null, compName: st['Competition Name'] || null, at: num(st['Match Finished At']) || null, players: new Set() };
      f.players.add(pid); found.set(mid, f); kept++;
    }
    const oldest = Math.min(...got.map(x => num(x['Match Finished At']) || Infinity));
    if (got.length < 50 || !isFinite(oldest)) break;
    const sec = oldest > 1e12 ? oldest / 1000 : oldest;
    if (sec < SINCE) break;
    to = oldest - 1;
  }
  console.log(`${pid}: ${kept} 1NT maps`);
}
console.log(`${found.size} 1NT matches (calls ${calls})`);

// ---- each match in full
const compNames = new Map();
const rows = [];
for (const [mid, f] of found) {
  const det = await api(`/matches/${mid}`);
  if (!det?.teams) continue;
  const side = det.teams.faction1?.faction_id === TEAM_ID || det.teams.faction1?.name === TEAM ? 'faction1' : 'faction2', opp = side === 'faction1' ? 'faction2' : 'faction1';
  const cid = det.competition_id || f.comp;
  if (cid && !compNames.has(cid)) compNames.set(cid, det.competition_name || (await api(`/championships/${cid}`))?.name || null);
  const st = await api(`/matches/${mid}/stats`);
  const maps = (st?.rounds || []).map(r => {
    const T = r.teams || [], us = T.find(t => t.team_id === det.teams[side].faction_id) || T.find(t => (t.players || []).some(p => f.players.has(p.player_id))), them = T.find(t => t !== us);
    const L = t => (t?.players || []).map(p => [p.player_id, p.nickname, full(p.player_stats || {})]);
    return { map: String(r.round_stats?.Map || '').replace(/^de_/, ''), rf: num(us?.team_stats?.['Final Score']), ra: num(them?.team_stats?.['Final Score']),
      first: num(us?.team_stats?.['First Half Score']), second: num(us?.team_stats?.['Second Half Score']), ot: num(us?.team_stats?.['Overtime score']),
      us: L(us), them: L(them) };
  });
  // the veto, when the room kept it (picks/bans with who made them)
  const vote = det.voting?.map ? { pick: det.voting.map.pick || null } : null;
  rows.push({ id: mid, at: (det.started_at || det.finished_at || f.at || 0) * (det.started_at ? 1000 : 1), comp: cid, compName: compNames.get(cid) || f.compName, type: det.competition_type || null,
    bo: det.best_of || 1, round: det.round ?? null, status: det.status, winner: det.results?.winner === side ? 'us' : det.results?.winner === opp ? 'them' : null,
    opp: { id: det.teams[opp]?.faction_id, name: det.teams[opp]?.name, roster: (det.teams[opp]?.roster || []).map(p => [p.player_id, p.game_skill_level ?? null]) },
    us: { roster: (det.teams[side]?.roster || []).map(p => [p.player_id, p.game_skill_level ?? null]) }, vote, maps });
}
rows.sort((a, b) => a.at - b.at);
fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT, zlib.gzipSync(JSON.stringify({ asof: new Date().toISOString(), team: TEAM_ID, since: SINCE, comps: Object.fromEntries(compNames), matches: rows })));
console.log(`wrote ${path.relative(ROOT, OUT)}: ${rows.length} matches, ${rows.reduce((a, r) => a + r.maps.length, 0)} maps, ${calls} API calls`);
