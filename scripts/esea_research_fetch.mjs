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

// ---- championships: "S58 NA Main A - Regular Season", "S58 NA Main - Playoffs", ...
const champs = new Map();
const parse = nm => {
  const m = /^S(\d+)\s+NA\s+(Open(?:\s*\d+\s*[-–]\s*\d+)?|Intermediate|Main|Advanced)\b(?:\s+([A-Z]))?\s*-\s*(.+)$/i.exec(String(nm || '').trim());
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
// fallback: the organizer's list (from any found championship)
const anyId = [...champs.keys()][0];
if (anyId) {
  const org = (await api(`/championships/${anyId}`))?.organizer_id;
  if (org) for (const type of ['past', 'ongoing']) for (let off = 0; off < 5000; off += 100) {
    const r = await api(`/organizers/${org}/championships?type=${type}&offset=${off}&limit=100`);
    for (const x of r?.items || []) { const id = x.championship_id || x.competition_id, p = parse(x.name); if (id && p && p.season >= FROM && p.season <= TO && !champs.has(id)) champs.set(id, { id, name: x.name, ...p }); }
    if ((r?.items || []).length < 100) break;
  }
}
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
        mp['p' + sd] = (t.players || []).map(p => { const x = p.player_stats || {}; return [p.player_id, num(x.Kills) || 0, num(x.Deaths) || 0, num(x.Assists) || 0, num(x.ADR) || 0]; });
      }
      row.maps.push(mp);
    }
    rows.push(row);
  }
}
fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT, zlib.gzipSync(JSON.stringify({ asof: new Date().toISOString(), from: FROM, to: TO, champs: [...champs.values()], matches: rows })));
console.log(`wrote ${path.relative(ROOT, OUT)}: ${rows.length} matches, ${calls} API calls`);
