#!/usr/bin/env node
// ESEA NA league history for the 1NT model research (scripts/esea_research.py): every match of the
// NA Intermediate/Main/Advanced regular seasons and playoffs, seasons ESEA_FROM..ESEA_TO, from the
// FACEIT Data API: teams, rosters (with each player's skill level at the match), winner, best-of and
// each map's name and round score, plus each player's map line (k, d, a, adr). Written to
// research/esea_matches.json.gz. Needs FACEIT_API_KEY; .github/workflows/esea-research.yml runs it.
//
//   FACEIT_API_KEY=... ESEA_FROM=56 ESEA_TO=59 node scripts/esea_research_fetch.mjs
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const OUT = path.join(ROOT, 'research', 'esea_matches.json.gz');
const KEY = process.env.FACEIT_API_KEY;
const API = 'https://open.faceit.com/data/v4';
const FROM = +(process.env.ESEA_FROM || 56), TO = +(process.env.ESEA_TO || 59);
const DIVS = (process.env.ESEA_DIVS || 'Intermediate,Main,Advanced').split(',');
if (!KEY) { console.log('FACEIT_API_KEY not set'); process.exit(0); }

let calls = 0;
async function api(p) {
  for (let a = 0; a < 5; a++) {
    calls++;
    const r = await fetch(API + p, { headers: { Authorization: `Bearer ${KEY}`, Accept: 'application/json' } }).catch(() => null);
    if (!r || r.status === 429 || r.status >= 500) { await new Promise(s => setTimeout(s, 2000 * (a + 1))); continue; }
    if (r.status === 404) return null;
    if (!r.ok) throw new Error(`${p}: HTTP ${r.status}`);
    return r.json();
  }
  return null;
}
async function pages(p, max = 3000) {
  const out = [];
  for (let off = 0; off < max; off += 100) {
    const j = await api(`${p}${p.includes('?') ? '&' : '?'}offset=${off}&limit=100`);
    const items = j?.items || [];
    out.push(...items);
    if (items.length < 100) break;
  }
  return out;
}
const num = v => (v == null || v === '' ? null : +String(v).replace('%', ''));
// a player's full map line, in fetch_esea.mjs's box-score cache order (boxLines), so its ARK code reads it
const full = x => [num(x.Kills) || 0, num(x['Sniper Kills']) || 0, num(x['Entry Count']) || 0, num(x['Flash Count']) || 0, num(x['Utility Count']) || 0, (num(x['1v1Count']) || 0) + (num(x['1v2Count']) || 0),
  num(x.Deaths) || 0, num(x.Assists) || 0, num(x.ADR) || 0, num(x['Double Kills']) || 0, num(x['Triple Kills']) || 0, num(x['Quadro Kills']) || 0, num(x['Penta Kills']) || 0,
  num(x['Entry Wins']) || 0, num(x['1v1Wins']) || 0, num(x['1v2Wins']) || 0, num(x['Utility Damage']) || 0, num(x['Enemies Flashed']) || 0,
  num(x.MVPs) || 0, num(x['Flash Successes']) || 0, num(x['Utility Successes']) || 0, num(x['Clutch Kills']) || 0, num(x['Pistol Kills']) || 0,
  num(x.Headshots) || 0, num(x['1v1Count']) || 0, num(x['1v2Count']) || 0];

// ---- championships: "S58 NA Main A - Regular Season", "S58 NA Main - Playoffs", ...
const champs = new Map();
const parse = nm => {
  // "S58 NA Main A - Regular Season", "ESEA S54 NA Main Central - Regular Season", "ESEA S53 NA Open9-10 West - Playoffs Bracket A"
  const m = /^(?:ESEA\s+)?S(\d+)\s+NA\s+(Open\s*\d+\s*[-–]\s*\d+|Intermediate|Main|Advanced)\b(?:\s+(Central|West|East|[A-Z]))?\s*-\s*(.+)$/i.exec(String(nm || '').trim());
  return m ? { season: +m[1], div: m[2].replace(/\s+/g, ' '), group: m[3] || null, stage: m[4] } : null;
};
for (let s = FROM; s <= TO; s++) for (const d of DIVS) for (const q of [`S${s} NA ${d}`, ...'ABCD'.split('').map(L => `S${s} NA ${d} ${L} - Regular Season`), `S${s} NA ${d} - Playoffs`]) {
  for (const type of ['all', 'past', 'ongoing']) {
    const r = await api(`/search/championships?name=${encodeURIComponent(q)}&game=cs2&type=${type}&limit=100`);
    for (const x of r?.items || []) {
      const id = x.competition_id || x.championship_id, p = parse(x.name);
      if (id && p && p.season === s && !champs.has(id)) champs.set(id, { id, name: x.name, ...p });
    }
  }
}
// FACEIT's search often misses: seed with the current season's group (data/esea.json), then the
// organizer's list, then crawl players' match histories (each names the league competitions it was in)
const add = (id, nm) => { const p = parse(nm); if (id && p && p.season >= FROM && p.season <= TO && !champs.has(id)) { champs.set(id, { id, name: nm, ...p }); return true; } return false; };
let seed = []; try { seed = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'esea.json'), 'utf8')).championships || []; } catch {}
for (const c of seed) add(c.id, c.name);
// 1NT's own history names its older league competitions (research/esea_1nt_history.json.gz, scripts/esea_1nt_history.mjs)
try { for (const [id, nm] of Object.entries(JSON.parse(zlib.gunzipSync(fs.readFileSync(path.join(ROOT, 'research', 'esea_1nt_history.json.gz')))).comps || {})) add(id, nm); } catch {}
const seedId = seed[0]?.id || [...champs.keys()][0];
const det0 = seedId ? await api(`/championships/${seedId}`) : null;
const org = det0?.organizer_id;
console.log('seed', seedId, 'organizer', org);
if (org) for (const type of ['past', 'ongoing', 'upcoming']) for (let off = 0; off < 20000; off += 100) {
  const r = await api(`/organizers/${org}/championships?type=${type}&offset=${off}&limit=100`);
  const items = r?.items || [];
  if (off === 0) console.log(`organizer ${type}: e.g.`, items.slice(0, 5).map(x => x.name));
  for (const x of items) add(x.championship_id || x.competition_id, x.name);
  if (items.length < 100) break;
}
// history crawl: players in the seed group's matches, then players met in newly found championships
const seenP = new Set(), queue = [];
const MAXP = +(process.env.ESEA_CRAWL ?? 150);
if (seedId) for (const m of await pages(`/championships/${seedId}/matches?type=past`, 2000)) for (const f of ['faction1', 'faction2']) for (const p of m.teams?.[f]?.roster || []) queue.push(p.player_id);
while (queue.length && seenP.size < MAXP) {
  const pid = queue.shift(); if (seenP.has(pid)) continue; seenP.add(pid);
  // history pages stop at offset 1,000: walk back by time instead (to = the oldest match seen)
  let to = Math.floor(Date.now() / 1000);
  for (let pg = 0; pg < 30; pg++) {
    const items = (await api(`/players/${pid}/history?game=cs2&from=0&to=${to}&offset=0&limit=100`).catch(() => null))?.items || [];
    for (const m of items) if (m.competition_type === 'championship') add(m.competition_id, m.competition_name);
    const oldest = Math.min(...items.map(m => m.started_at || m.finished_at || Infinity));
    if (items.length < 100 || !isFinite(oldest) || oldest < 1.70e9) break;
    to = oldest - 1;
  }
}
console.log(`crawled ${seenP.size} players`);
console.log(`${champs.size} championships:\n` + [...champs.values()].map(c => c.name).sort().join('\n'));

// ---- matches
const rows = [];
let shown = false;
for (const c of champs.values()) {
  const ms = await pages(`/championships/${c.id}/matches?type=past`, 5000);
  console.log(`${c.name}: ${ms.length} matches (calls so far ${calls})`);
  for (const m of ms) {
    if (m.status !== 'FINISHED' || !m.teams?.faction1 || !m.teams?.faction2) continue;
    const T = f => ({ id: m.teams[f].faction_id, name: m.teams[f].name, roster: (m.teams[f].roster || []).map(p => [p.player_id, p.game_skill_level ?? null]) });
    const row = { id: m.match_id, champ: c.id, season: c.season, div: c.div, group: c.group, stage: c.stage, at: m.started_at || m.scheduled_at || null, bo: m.best_of || 1,
      round: m.round ?? null, f1: T('faction1'), f2: T('faction2'), winner: m.results?.winner || null, score: m.results?.score || null, maps: [] };
    if (!shown) { shown = true; const det = await api(`/matches/${m.match_id}`); console.log('match detail keys:', JSON.stringify({ keys: Object.keys(det || {}), f1: Object.keys(det?.teams?.faction1 || {}), stats: det?.teams?.faction1?.stats ?? null, roster0: det?.teams?.faction1?.roster?.[0] ?? null })); }
    const st = await api(`/matches/${m.match_id}/stats`);
    for (const r of st?.rounds || []) {
      const ts = r.teams || [];
      const side = t => (t.team_id === row.f1.id ? 1 : t.team_id === row.f2.id ? 2 : 0);
      const mp = { map: String(r.round_stats?.Map || '').replace(/^de_/, ''), s1: null, s2: null, p1: [], p2: [] };
      for (const t of ts) {
        const sd = side(t); if (!sd) continue;
        mp['s' + sd] = num(t.team_stats?.['Final Score']);
        mp['p' + sd] = (t.players || []).map(p => { const x = p.player_stats || {}; return [p.player_id, num(x.Kills) || 0, num(x.Deaths) || 0, num(x.Assists) || 0, num(x.ADR) || 0, full(x)]; });
      }
      row.maps.push(mp);
    }
    rows.push(row);
  }
}
// lifetime map splits (every FACEIT match: PUGs, hubs, leagues) for every player and team seen: the bigger
// map samples the veto research tests against one season's league maps
const segs = st => Object.fromEntries((st?.segments || []).filter(x => /map/i.test(x.type || '')).map(x => [String(x.label || '').toLowerCase().replace(/^de_/, ''),
  [num(x.stats?.Matches) || 0, num(x.stats?.['Win Rate %']), num(x.stats?.['Average K/D Ratio']) ?? num(x.stats?.['K/D Ratio'])]]));
const playerMaps = {}, teamMaps = {};
const pids = new Set(), tids = new Set();
for (const r of rows) { tids.add(r.f1.id); tids.add(r.f2.id); for (const mp of r.maps) for (const q of [...mp.p1, ...mp.p2]) pids.add(q[0]); }
if (!process.env.ESEA_NO_SPLITS) {
  for (const pid of pids) { const st = await api(`/players/${pid}/stats/cs2`); if (st) playerMaps[pid] = { life: [num(st.lifetime?.Matches) || 0, num(st.lifetime?.['Win Rate %'])], maps: segs(st) }; }
  for (const tid of tids) { const st = await api(`/teams/${tid}/stats/cs2`); if (st) teamMaps[tid] = { life: [num(st.lifetime?.Matches) || 0, num(st.lifetime?.['Win Rate %'])], maps: segs(st) }; }
  console.log(`map splits: ${Object.keys(playerMaps).length} players, ${Object.keys(teamMaps).length} teams`);
}
fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT, zlib.gzipSync(JSON.stringify({ asof: new Date().toISOString(), from: FROM, to: TO, champs: [...champs.values()], matches: rows, playerMaps, teamMaps })));
console.log(`wrote ${path.relative(ROOT, OUT)}: ${rows.length} matches, ${calls} API calls`);
