#!/usr/bin/env node
// Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
// 1NT's league divisions, whole: FACEIT's championship match list stops at 600 matches, so the research archive
// (research/esea_matches.json.gz) holds only part of the big regular seasons (S54-S57 Main/Intermediate Central).
// This walks every team's history inside each of 1NT's regular seasons (one or two players per team, the
// season's time window), finds the matches the archive lacks and pulls their detail + map lines in the
// archive's row format -> research/esea_div_backfill.json.gz, read by scripts/esea_milestones.py (division
// ranks + standings). Needs FACEIT_API_KEY; .github/workflows/esea-research.yml (input backfill=1) runs it.
//
//   FACEIT_API_KEY=... node scripts/esea_div_backfill.mjs
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const OUT = path.join(ROOT, 'research', 'esea_div_backfill.json.gz');
const KEY = process.env.FACEIT_API_KEY;
const API = 'https://open.faceit.com/data/v4';
const TEAM = 'a6e9c61b-de50-47d4-9fc8-3f03a13c4d4a';
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
const num = v => (v == null || v === '' ? null : +String(v).replace('%', ''));
// esea_research_fetch.mjs's full map line (fetch_esea.mjs box-score cache order)
const full = x => [num(x.Kills) || 0, num(x['Sniper Kills']) || 0, num(x['Entry Count']) || 0, num(x['Flash Count']) || 0, num(x['Utility Count']) || 0, (num(x['1v1Count']) || 0) + (num(x['1v2Count']) || 0),
  num(x.Deaths) || 0, num(x.Assists) || 0, num(x.ADR) || 0, num(x['Double Kills']) || 0, num(x['Triple Kills']) || 0, num(x['Quadro Kills']) || 0, num(x['Penta Kills']) || 0,
  num(x['Entry Wins']) || 0, num(x['1v1Wins']) || 0, num(x['1v2Wins']) || 0, num(x['Utility Damage']) || 0, num(x['Enemies Flashed']) || 0,
  num(x.MVPs) || 0, num(x['Flash Successes']) || 0, num(x['Utility Successes']) || 0, num(x['Clutch Kills']) || 0, num(x['Pistol Kills']) || 0,
  num(x.Headshots) || 0, num(x['1v1Count']) || 0, num(x['1v2Count']) || 0];
const gz = p => { try { return JSON.parse(zlib.gunzipSync(fs.readFileSync(path.join(ROOT, p)))); } catch { return null; } };

const arc = gz('research/esea_matches.json.gz') || { matches: [], champs: [] };
const hist = gz('research/esea_1nt_history.json.gz') || { comps: {} };
const prev = gz('research/esea_div_backfill.json.gz') || { matches: [] };
let es = {}; try { es = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'esea.json'), 'utf8')); } catch {}
const comps = { ...(hist.comps || {}) };
for (const c of es.championships || []) comps[c.id] = c.name;
const meta = Object.fromEntries((arc.champs || []).map(c => [c.id, c]));
const have = new Set([...arc.matches, ...prev.matches].map(m => m.id));
const rows = [...prev.matches];

for (const [cid, name] of Object.entries(comps)) {
  const sm = /\bS(\d{2})\b/.exec(name || '');
  if (!sm || !/Regular Season/.test(name) || +sm[1] === +es.season) continue;   // this season: esea.yml's cache
  const ms = arc.matches.filter(m => m.champ === cid);
  const at = ms.map(m => m.at).filter(Boolean);
  if (!at.length) { console.log(`${name}: not in the archive, skipped`); continue; }
  // the archive keeps one end of the list, so reach a full season either side of what it holds
  const from = Math.min(...at) - 80 * 86400, to = Math.max(...at) + 80 * 86400;
  const seen = {};   // team -> player -> matches in the archive
  for (const m of ms) for (const f of ['f1', 'f2']) if (m[f].id !== 'bye') for (const [q] of m[f].roster || []) { const t = (seen[m[f].id] ||= {}); t[q] = (t[q] || 0) + 1; }
  const found = new Set();
  let n = 0;
  for (const [tid, cnt] of Object.entries(seen)) {
    // the team's two most-seen players: one history covers the team's matches unless he sat one out
    const two = Object.keys(cnt).sort((a, b) => cnt[b] - cnt[a]).slice(0, 2);
    for (const pid of two) {
      // PUGs share the history: walk back by time, 100 at a time, to the season's start
      let t = to;
      for (let pg = 0; pg < 15; pg++) {
        const items = (await api(`/players/${pid}/history?game=cs2&from=${from}&to=${t}&offset=0&limit=100`))?.items || [];
        for (const it of items) if (it.competition_id === cid && !have.has(it.match_id)) found.add(it.match_id);
        const oldest = Math.min(...items.map(it => it.started_at || it.finished_at || Infinity));
        if (items.length < 100 || !isFinite(oldest) || oldest <= from) break;
        t = oldest - 1;
      }
    }
    if (++n % 25 === 0) console.log(`${name}: ${n}/${Object.keys(seen).length} teams, ${found.size} new (calls ${calls})`);
  }
  const c = meta[cid] || {};
  let added = 0;
  for (const id of found) {
    const m = await api(`/matches/${id}`);
    if (!m || m.status !== 'FINISHED' || !m.teams?.faction1 || !m.teams?.faction2) continue;
    const T = f => ({ id: m.teams[f].faction_id, name: m.teams[f].name, roster: (m.teams[f].roster || []).map(p => [p.player_id, p.game_skill_level ?? null]) });
    const row = { id, champ: cid, season: c.season ?? +sm[1], div: c.div ?? null, group: c.group ?? null, stage: c.stage ?? 'Regular Season',
      at: m.started_at || m.scheduled_at || null, bo: m.best_of || 1, round: m.round ?? null, f1: T('faction1'), f2: T('faction2'),
      winner: m.results?.winner || null, score: m.results?.score || null, maps: [] };
    const st = await api(`/matches/${id}/stats`);
    for (const r of st?.rounds || []) {
      const side = t => (t.team_id === row.f1.id ? 1 : t.team_id === row.f2.id ? 2 : 0);
      const mp = { map: String(r.round_stats?.Map || '').replace(/^de_/, ''), s1: null, s2: null, p1: [], p2: [] };
      for (const t of r.teams || []) {
        const sd = side(t); if (!sd) continue;
        mp['s' + sd] = num(t.team_stats?.['Final Score']);
        mp['p' + sd] = (t.players || []).map(p => { const x = p.player_stats || {}; return [p.player_id, num(x.Kills) || 0, num(x.Deaths) || 0, num(x.Assists) || 0, num(x.ADR) || 0, full(x)]; });
      }
      row.maps.push(mp);
    }
    rows.push(row); have.add(id); added++;
  }
  console.log(`${name}: archive ${ms.length}, added ${added} (1NT ${rows.filter(r => r.champ === cid && (r.f1.id === TEAM || r.f2.id === TEAM)).length}), calls ${calls}`);
}
fs.writeFileSync(OUT, zlib.gzipSync(JSON.stringify({ asof: new Date().toISOString(), matches: rows })));
console.log(`wrote ${path.relative(ROOT, OUT)}: ${rows.length} matches, ${calls} API calls`);
