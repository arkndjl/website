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
const OUT = path.join(ROOT, process.env.ESEA_OUT || path.join('research', 'esea_regions.json.gz'));   // ESEA_OUT: early seasons go to their own file
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
console.log('seed', seed[0]?.id, JSON.stringify(det0)?.slice(0, 600));
if (process.env.ESEA_PROBE) {
  const mm = await api(`/championships/${seed[0].id}/matches?type=past&offset=0&limit=2`);
  console.log('seed matches', JSON.stringify(mm)?.slice(0, 800));
  const pid = mm?.items?.[0]?.teams?.faction1?.roster?.[0]?.player_id;
  if (pid) { const h = await api(`/players/${pid}/history?game=cs2&offset=0&limit=100`); console.log('history comps', JSON.stringify([...new Set((h?.items || []).map(m => m.competition_type + ' | ' + m.competition_name + ' | ' + m.competition_id + ' | ' + m.organizer_id))]).slice(0, 3000)); }
  for (const q of ['S58 EU Main', 'S58 EU Main - Regular Season', 'S58 EU Main A - Regular Season', 'ESEA S58 EU Main', 'ESEA Season 58 Europe Main', 'S58 EU Advanced - Regular Season', 'S58 NA Main A - Regular Season', 'ESEA EU Main', 'S59 EU Main'])
    for (const type of ['past', 'all', 'ongoing']) console.log('Q', q, type, JSON.stringify(((await api(`/search/championships?name=${encodeURIComponent(q)}&game=cs2&type=${type}&limit=20`))?.items || []).map(x => x.name + ' / ' + x.organizer_name)));
  process.exit(0);
}
console.log('search sample', JSON.stringify(await api(`/search/championships?name=${encodeURIComponent('S58 EU Main')}&game=cs2&type=past&limit=5`))?.slice(0, 1500));
// ESEA's FACEIT organizer (every league match names it; the championship detail call returns nothing for league groups)
const org = det0?.organizer_id || '08b06cfc-74d0-454b-9a51-feda4b6b18da';
console.log('organizer', org);
if (org) for (const type of ['past', 'ongoing']) for (let off = 0; off < 50000; off += 100) {
  const items = (await api(`/organizers/${org}/championships?type=${type}&offset=${off}&limit=100`))?.items || [];
  for (const x of items) add(x.championship_id || x.competition_id, x.name);
  if (off === 0) console.log(`organizer ${type}:`, items.length, items.slice(0, 8).map(x => x.name));
  if (items.length < 100) break;
}
console.log('after organizer list', champs.size);
// FACEIT's league API: each season lists regions > divisions > stages > conferences, each with a championship id
const LG = 'a14b8616-45b9-4581-8637-4dfd0b5f6af8';
const lg = await api(`/leagues/${LG}`);
console.log('league', JSON.stringify(lg)?.slice(0, 200));
const walk = (o, ctx, s) => {
  if (!o || typeof o !== 'object') return;
  if (Array.isArray(o)) { for (const x of o) walk(x, ctx, s); return; }
  const nm = o.name || o.region_name || o.division_name || o.stage_name || o.conference_name;
  const c2 = nm ? [...ctx, String(nm)] : ctx;
  const id = o.championship_id || o.competition_id;
  if (id) {
    const full = `S${s} ` + c2.join(' ');
    const reg = (c2.find(x => /^(NA|EU|SA|OCE|AS|ASIA|MENA|North America|Europe|South America|Oceania)$/i.test(x)) || c2[0] || '').toUpperCase()
      .replace('NORTH AMERICA', 'NA').replace('EUROPE', 'EU').replace('SOUTH AMERICA', 'SA').replace('OCEANIA', 'OCE').replace('ASIA', 'AS');
    const dv = c2.find(x => DIVS.test(x.trim()));
    if (dv && !champs.has(id)) champs.set(id, { id, name: full, season: s, region: reg, div: dv[0].toUpperCase() + dv.slice(1).toLowerCase(), group: null,
      stage: /playoff/i.test(full) ? 'Playoffs' : 'Regular Season' });
  }
  for (const v of Object.values(o)) if (v && typeof v === 'object') walk(v, c2, s);
};
for (let s = FROM; s <= TO; s++) {
  const ls = await api(`/leagues/${LG}/seasons/${s}`);
  
  walk(ls, [], s);
}
console.log('after league API', champs.size);
// FACEIT's organizer list can stop short: name searches per season x region x division fill gaps
for (let s = FROM; s <= TO; s++) for (const R of ['NA', 'EU', 'SA', 'OCE', 'AS', 'MENA']) for (const d of ['Advanced', 'Main', 'Intermediate'])
  for (const type of ['past', 'ongoing']) {
    const r = await api(`/search/championships?name=${encodeURIComponent(`S${s} ${R} ${d}`)}&game=cs2&type=${type}&limit=100`);
    for (const x of r?.items || []) add(x.competition_id || x.championship_id, x.name);
  }
// history crawl (the reliable route): players from ESEA qualifiers in each region and from the groups found so far;
// each player's match history names the league championships they played (competition_name)
const seeds = new Set([...champs.keys()].slice(0, 40));
for (const q of ['ESEA League EU Main', 'ESEA League EU Advanced', 'ESEA League EU Intermediate', 'ESEA League NA Main', 'ESEA League NA Advanced',
  'ESEA League SA Main', 'ESEA League SA Advanced', 'ESEA League OCE Main', 'ESEA League Asia Main', 'ESEA League MENA Main'])
  for (const type of ['past', 'all']) for (const x of (await api(`/search/championships?name=${encodeURIComponent(q)}&game=cs2&type=${type}&limit=100`))?.items || [])
    if (/^ESEA League /i.test(x.name || '') && x.organizer_id === org) seeds.add(x.competition_id || x.championship_id);
if (seed[0]) seeds.add(seed[0].id);
console.log('crawl seeds', seeds.size);
const queue = [], seenP = new Set();
for (const id of seeds) {
  const ms = (await api(`/championships/${id}/matches?type=past&offset=0&limit=100`))?.items || [];
  for (const m of ms.slice(0, 60)) for (const f of ['faction1', 'faction2']) for (const p of (m.teams?.[f]?.roster || []).slice(0, 2)) queue.push(p.player_id);
}
const MAXP = +(process.env.ESEA_CRAWL ?? 900), T0 = (process.env.ESEA_T0 ? Date.parse(process.env.ESEA_T0) : Date.UTC(2025, 2, 1)) / 1000;
for (let i = queue.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [queue[i], queue[j]] = [queue[j], queue[i]]; }
while (queue.length && seenP.size < MAXP) {
  const pid = queue.shift(); if (!pid || seenP.has(pid)) continue; seenP.add(pid);
  let to = Math.floor(Date.now() / 1000);
  for (let pg = 0; pg < 6; pg++) {
    const items = (await api(`/players/${pid}/history?game=cs2&from=${T0}&to=${to}&offset=0&limit=100`))?.items || [];
    for (const m of items) if (m.competition_type === 'championship' && m.organizer_id === org) {
      const before = champs.size; add(m.competition_id, m.competition_name);
      if (champs.size > before) for (const f of ['faction1', 'faction2']) for (const p of (m.teams?.[f]?.players || []).slice(0, 2)) queue.push(p.player_id);
    }
    const oldest = Math.min(...items.map(m => m.started_at || m.finished_at || Infinity));
    if (items.length < 100 || !isFinite(oldest) || oldest < T0) break;
    to = oldest - 1;
  }
  if (seenP.size % 100 === 0) console.log(`crawled ${seenP.size}, championships ${champs.size}, calls ${calls}`);
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
