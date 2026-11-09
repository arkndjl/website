// Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
// Returning production from PFN for every season PFN covers (2020 on: PFN starts in 2019), the same function
// fetch_cfb.mjs builds MD.pfnRet with for the live game model: each team's returning players valued at their S-1 PFN
// line, QB (the team's best) and everyone else as z across FBS, and returning college WAR (season AV weights,
// scripts/cfb_av.mjs) for every position and every position but QB. For the ESPN-history game backtest
// (scripts/cfb_hist_backtest.mjs RETWAR=...) and the walk-forward (scripts/games_wf/cfb_wf.mjs). OL, CB and S lines
// exist from 2024 only, so av before 2025 is partial.
// Who returns is what was known in August (Nov 5 2026, the leakage sweep's "ret sees whole season"): a team's S-1 PFN
// players, less those drafted that April (nflverse) and those who turn up on another team's PFN rows in S (a move made
// in the portal before the season). Until then membership came from PFN's season-S rows, PFN's qualified players, so
// a game in week 1 already knew who would go on to play a full season for the team (a returning starter hurt in
// August or benched by October dropped out of every game's feature). Transfers in are not counted: PFN only shows a
// newcomer once he has qualified for the new team, which is the same look-ahead.
//   node scripts/cfb_ret_war.mjs [out.json]      # default scripts/.cache/cfb/ret_war.json
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { compact as norm, Matcher } from './names.mjs';
import { SAV_W, SAV_REPL } from './cfb_av.mjs';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const SP = path.join(ROOT, 'scripts', '.cache', 'statplus');
const DRAFT_URL = 'https://github.com/nflverse/nflverse-data/releases/download/draft_picks/draft_picks.csv';
const POS = { QB: 'quarterback', RB: 'running-back', WR: 'wide-receiver', TE: 'tight-end', OL: 'offensive-line', EDGE: 'edge', DL: 'defensive-tackle',
  LB: 'linebacker', CB: 'cornerback', S: 'safety' };
const AV_STARTERS = { QB: 1, RB: 1, WR: 3, TE: 1, OL: 5, EDGE: 2, DL: 2, LB: 2, CB: 3, S: 2 };
const SNAPS_PER_GAME = { QB: 65, RB: 30, WR: 40, TE: 40, CB: 55, S: 55, OL: 65, EDGE: 50, DL: 45, LB: 55 };
// PFN school names ESPN's location doesn't carry
const ALIAS = { miamifl: 'Miami', miamioh: 'Miami (OH)', olemiss: 'Ole Miss', uconn: 'UConn', ucf: 'UCF', usf: 'South Florida', fiu: 'Florida International',
  fau: 'Florida Atlantic', utsa: 'UTSA', utep: 'UTEP', uab: 'UAB', smu: 'SMU', tcu: 'TCU', byu: 'BYU', lsu: 'LSU', unlv: 'UNLV', ulm: 'UL Monroe',
  louisianamonroe: 'UL Monroe', appstate: 'App State', appalachianstate: 'App State', southernmiss: 'Southern Miss', ncstate: 'NC State',
  hawaii: "Hawai'i", sanjosestate: 'San José State', umass: 'Massachusetts', mississippi: 'Ole Miss', northcarolinastate: 'NC State', connecticut: 'UConn', fresnost: 'Fresno State', pittsburgh: 'Pittsburgh',
  sjsu: 'San José State', louisianalafayette: 'Louisiana', ullafayette: 'Louisiana', kentstate: 'Kent State', jacksonvillestate: 'Jacksonville State',
  samhoustonstate: 'Sam Houston', samhouston: 'Sam Houston', southernmississippi: 'Southern Miss', texasam: 'Texas A&M', floridaam: 'Florida A&M' };

async function pfnLines(g) {
  const f = path.join(SP, `pfn_${g}.json`);
  if (!fs.existsSync(f)) {      // as scripts/cfb_statplus_backtest.mjs and cfb_fv_refit.mjs cache it
    fs.mkdirSync(SP, { recursive: true });
    const html = await (await fetch(`https://www.profootballnetwork.com/cfb-hq/impact-rankings/${POS[g]}`, { headers: { 'user-agent': 'Mozilla/5.0' } })).text();
    const s = [...html.matchAll(/self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)/g)].map(m => JSON.parse(m[1])).find(c => c.includes('"packed":'));
    const i = s.indexOf('"packed":') + 9; let d = 0, q = false, k = i;
    for (; k < s.length; k++) { const c = s[k]; if (q) { if (c === '\\') k++; else if (c === '"') q = false; continue; } if (c === '"') q = true; else if (c === '{' || c === '[') d++; else if (c === '}' || c === ']') { d--; if (!d) break; } }
    const packed = JSON.parse(s.slice(i, k + 1));
    fs.writeFileSync(f, JSON.stringify(packed.rows.map(r => Object.fromEntries(packed.cols.map((c, j) => [c, r[j]])))));
  }
  return JSON.parse(fs.readFileSync(f));
}
function volume(r, g) {
  const n = v => (typeof v === 'number' && isFinite(v) ? v : null);
  const sn = n(r.snapsQ) ?? n(r.snaps);
  return sn ?? (n(r.gp) ?? n(r.gamesQ) ?? 0) * (SNAPS_PER_GAME[g] ?? 55);
}

// nflverse draft picks by draft year: [{ name, college, pos }] (cached as the other CFB scripts keep it)
export async function draftsBy(first = 2020) {
  const f = path.join(SP, 'draft_picks.csv');
  if (!fs.existsSync(f)) {
    try { const r = await fetch(DRAFT_URL); if (!r.ok) throw new Error(r.status); fs.mkdirSync(SP, { recursive: true }); fs.writeFileSync(f, await r.text()); }
    catch (e) { console.log(`nflverse draft picks unavailable (${e.message}): returning production without draft departures`); return {}; }
  }
  const row = l => { const o = []; let c = '', q = false; for (const ch of l) { if (ch === '"') q = !q; else if (ch === ',' && !q) { o.push(c); c = ''; } else c += ch; } o.push(c); return o; };
  const [h, ...ls] = fs.readFileSync(f, 'utf8').trim().split('\n'), H = row(h), ix = k => H.indexOf(k);
  const out = {};
  for (const l of ls) { const r = row(l), S = +r[ix('season')]; if (S >= first) (out[S] ||= []).push({ name: r[ix('pfr_player_name')], college: r[ix('college')].replace(/ Col\.$/, ' College'), pos: r[ix('position')] }); }
  return out;
}

// pfn {group: rows}; resolve(PFN school) -> ESPN team id or null; volume(row, group) -> snaps; drafted from draftsBy.
// -> {S: {team id: {qb, rest, av, avRest}}}, z across the FBS teams of season S (teams with PFN rows that season)
export function returning(pfn, { resolve, volume, drafted = {}, first = 2020, last }) {
  const res = {};
  for (let S = first; S <= last; S++) {
    const T = {}, pm = {}, ps = {}, seen = {};
    for (const rows of Object.values(pfn)) for (const r of rows) if (r.season === S) {
      const tid = resolve(r.team);
      if (tid && r.division === 'FBS') T[tid] ||= { qb: null, rest: 0, av: 0, avRest: 0 };
      (seen[r.id] ||= new Set()).add(tid ?? 'other:' + r.team);
    }
    // S-1 players (any group) drafted in April of S, by name and school
    const prevAll = Object.values(pfn).flatMap(rows => rows.filter(r => r.season === S - 1));
    const M = new Matcher(prevAll, { name: 'name', team: 'team', pos: null }), gone = new Set();
    for (const d of drafted[S] || []) { const [q] = M.find(d.name, { team: d.college, crossTeam: 'none' }); if (q) gone.add(q.id); }
    for (const [g, rows] of Object.entries(pfn)) {
      const prev = rows.filter(r => r.season === S - 1 && r.division === 'FBS');
      if (!prev.length) continue;
      const m = prev.reduce((a, r) => a + r.score, 0) / prev.length, sd = Math.sqrt(prev.reduce((a, r) => a + (r.score - m) ** 2, 0) / prev.length) || 1;
      { const pool = prev.map(r => r.score).sort((a, b) => b - a).slice(0, AV_STARTERS[g] * 134), pm0 = pool.reduce((a, b) => a + b, 0) / pool.length;
        pm[g] = pm0; ps[g] = Math.sqrt(pool.reduce((a, b) => a + (b - pm0) ** 2, 0) / pool.length) || 1; }
      for (const q of rows) if (q.season === S - 1) {
        const tid = resolve(q.team), t = tid && T[tid];
        if (!t || gone.has(q.id) || (seen[q.id] && !seen[q.id].has(tid))) continue;
        const vol = volume(q, g) || 0;
        const v = (q.score - m) / sd * Math.min(1.3, vol / 700);
        if (g === 'QB') t.qb = Math.max(t.qb ?? -Infinity, v); else t.rest += v;
        const a = Math.min(1, vol / 700) * SAV_W[g] * ((q.score - pm[g]) / ps[g] - SAV_REPL);
        t.av += a; if (g !== 'QB') t.avRest += a;
      }
    }
    const z = k => { const xs = Object.values(T).map(t => t[k] ?? 0), mm = xs.reduce((a, b) => a + b, 0) / Math.max(1, xs.length);
      const ss = Math.sqrt(xs.reduce((a, b) => a + (b - mm) ** 2, 0) / Math.max(1, xs.length)) || 1; return t => ((t[k] ?? 0) - mm) / ss; };
    const zq = z('qb'), zr = z('rest'), za = z('av'), zar = z('avRest'), r2 = x => Math.round(x * 100) / 100;
    res[S] = Object.fromEntries(Object.entries(T).map(([tid, t]) => [tid, { qb: r2(zq(t)), rest: r2(zr(t)), av: r2(za(t)), avRest: r2(zar(t)) }]));
  }
  return res;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
const out = process.argv[2] || path.join(ROOT, 'scripts', '.cache', 'cfb', 'ret_war.json');
const teams = (await (await fetch('https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams?limit=1000')).json()).sports[0].leagues[0].teams.map(t => t.team);
const byLoc = {}; for (const t of teams) { (byLoc[norm(t.location)] ||= []).push(t); byLoc[norm(t.displayName)] ||= [t]; byLoc[norm(t.abbreviation)] ||= [t]; }
const miss = {};
const resolve = name => { const n = norm(name || ''), a = ALIAS[n]; const hit = byLoc[a ? norm(a) : n]; if (!hit) { miss[name] = (miss[name] || 0) + 1; return null; } return [...hit].sort((x, y) => x.id - y.id)[0].id; };
const pfn = {}; for (const g of Object.keys(POS)) pfn[g] = await pfnLines(g);
const res = returning(pfn, { resolve, volume, drafted: await draftsBy(), last: 2026 });
for (const [S, R] of Object.entries(res)) console.log(S, Object.keys(R).length, 'teams');
console.log('unresolved PFN schools:', JSON.stringify(Object.entries(miss).sort((a, b) => b[1] - a[1]).slice(0, 25)));
fs.writeFileSync(out, JSON.stringify(res));
}
