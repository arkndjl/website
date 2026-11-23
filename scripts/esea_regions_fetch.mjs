#!/usr/bin/env node
// Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
// ESEA league results in every region (NA, EU, SA, OCE, Asia...) for the division-to-pro-tier study
// (scripts/esea_tiers_research.py): each finished match of the Advanced / Main / Intermediate regular seasons and
// playoffs, seasons ESEA_FROM..ESEA_TO, from the FACEIT Data API: region, division, both rosters with each player's
// nickname and in-game name (the bridge to bo3.gg's pro nicks) and skill level, winner and score (a Bo1's score is the
// map's round score). No per-map stats calls: ~1 call per 100 matches. Writes research/esea_regions.json.gz.
// Needs FACEIT_API_KEY; .github/workflows/esea-research.yml runs it (input regions=1).
//
//   FACEIT_API_KEY=... ESEA_FROM=53 ESEA_TO=59 node scripts/esea_regions_fetch.mjs
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const OUT = path.join(ROOT, 'research', 'esea_regions.json.gz');
const KEY = process.env.FACEIT_API_KEY;
const API = 'https://open.faceit.com/data/v4';
const FROM = +(process.env.ESEA_FROM || 53), TO = +(process.env.ESEA_TO || 59);
const DIVS = /^(Intermediate|Main|Advanced)$/i;
if (!KEY) { console.log('FACEIT_API_KEY not set'); process.exit(0); }

let calls = 0;
async function api(p) {
  for (let a = 0; a < 5; a++) {
    calls++;
    const r = await fetch(API + p, { headers: { Authorization: `Bearer ${KEY}`, Accept: 'application/json' } }).catch(() => null);
    if (!r || r.status === 429 || r.status >= 500) { await new Promise(s => setTimeout(s, 2000 * (a + 1))); continue; }
    if (r.status === 404 || r.status === 400) return null;
    if (!r.ok) throw new Error(`${p}: HTTP ${r.status}`);
    return r.json();
  }
  return null;
}
async function pages(p, max = 5000) {
  const out = [];
  for (let off = 0; off < max; off += 100) {
    const items = (await api(`${p}${p.includes('?') ? '&' : '?'}offset=${off}&limit=100`))?.items || [];
    out.push(...items);
    if (items.length < 100) break;
  }
  return out;
}
// "S58 EU Main A - Regular Season", "ESEA S54 NA Main Central - Regular Season", "S57 SA Advanced - Playoffs"
const parse = nm => {
  const m = /^(?:ESEA\s+)?S(\d+)\s+([A-Z]{2,4})\s+(Intermediate|Main|Advanced)\b(?:\s+([A-Za-z]+))?\s*-\s*(.+)$/i.exec(String(nm || '').trim());
  return m && DIVS.test(m[3]) ? { season: +m[1], region: m[2].toUpperCase(), div: m[3][0].toUpperCase() + m[3].slice(1).toLowerCase(), group: m[4] || null, stage: m[5] } : null;
};
const champs = new Map();
const add = (id, nm) => { const p = parse(nm); if (id && p && p.season >= FROM && p.season <= TO && !champs.has(id)) champs.set(id, { id, name: nm, ...p }); };
let seed = []; try { seed = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'esea.json'), 'utf8')).championships || []; } catch {}
const det0 = seed[0] ? await api(`/championships/${seed[0].id}`) : null;
const org = det0?.organizer_id;
console.log('organizer', org);
if (org) for (const type of ['past', 'ongoing']) for (let off = 0; off < 50000; off += 100) {
  const items = (await api(`/organizers/${org}/championships?type=${type}&offset=${off}&limit=100`))?.items || [];
  for (const x of items) add(x.championship_id || x.competition_id, x.name);
  if (items.length < 100) break;
}
// FACEIT's organizer list can stop short: name searches per season x region x division fill gaps
for (let s = FROM; s <= TO; s++) for (const R of ['NA', 'EU', 'SA', 'OCE', 'AS', 'MENA']) for (const d of ['Advanced', 'Main', 'Intermediate'])
  for (const type of ['past', 'ongoing']) {
    const r = await api(`/search/championships?name=${encodeURIComponent(`S${s} ${R} ${d}`)}&game=cs2&type=${type}&limit=100`);
    for (const x of r?.items || []) add(x.competition_id || x.championship_id, x.name);
  }
const cnt = {};
for (const c of champs.values()) cnt[`${c.region} ${c.div}`] = (cnt[`${c.region} ${c.div}`] || 0) + 1;
console.log(`${champs.size} championships`, cnt);

const rows = [];
for (const c of champs.values()) {
  const ms = await pages(`/championships/${c.id}/matches?type=past`);
  for (const m of ms) {
    if (m.status !== 'FINISHED' || !m.teams?.faction1 || !m.teams?.faction2) continue;
    const T = f => ({ id: m.teams[f].faction_id, name: m.teams[f].name,
      roster: (m.teams[f].roster || []).map(p => [p.player_id, p.nickname || null, p.game_player_name || null, p.game_skill_level ?? null]) });
    rows.push({ id: m.match_id, season: c.season, region: c.region, div: c.div, stage: c.stage, at: m.started_at || m.scheduled_at || null,
      bo: m.best_of || 1, f1: T('faction1'), f2: T('faction2'), winner: m.results?.winner || null, score: m.results?.score || null });
  }
  console.log(`${c.name}: ${ms.length} (calls ${calls})`);
}
fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT, zlib.gzipSync(JSON.stringify({ asof: new Date().toISOString(), from: FROM, to: TO, champs: [...champs.values()], matches: rows })));
console.log(`wrote ${path.relative(ROOT, OUT)}: ${rows.length} matches, ${calls} API calls`);
