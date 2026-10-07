#!/usr/bin/env node
// 1NT's current ESEA season from the FACEIT Data API (https://docs.faceit.com/docs/data-api/data),
// written to data/esea.json for the LAURSEN_111 page: record, every match (maps, scores, each
// player's line), map pool and the roster's season stats. Needs a server-side API key in
// FACEIT_API_KEY (developers.faceit.com, free). .github/workflows/esea.yml runs it every 20 minutes
// and commits only when something changed.
//
//   FACEIT_API_KEY=... node scripts/fetch_esea.mjs            # season from data/esea.json or ESEA_SEASON (59)
//   FACEIT_API_KEY=... ESEA_SEASON=60 node scripts/fetch_esea.mjs
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const OUT = path.join(ROOT, 'data', 'esea.json');
const KEY = process.env.FACEIT_API_KEY;
const API = 'https://open.faceit.com/data/v4';
const TEAM_ID = 'a6e9c61b-de50-47d4-9fc8-3f03a13c4d4a';   // 1NT
const PLAYER = 'LAURSEN_111';
const REG_SEASON = 14;   // regular-season matches in ESEA Main (S57: 5-9, S58: 8-6); FACEIT only lists the scheduled ones
const prev = fs.existsSync(OUT) ? JSON.parse(fs.readFileSync(OUT, 'utf8')) : {};
const SEASON = +(process.env.ESEA_SEASON || prev.season || 59);

if (!KEY) { console.log('FACEIT_API_KEY not set: nothing fetched'); process.exit(0); }

async function api(p) {
  for (let a = 0; a < 4; a++) {
    const r = await fetch(API + p, { headers: { Authorization: `Bearer ${KEY}`, Accept: 'application/json' } });
    if (r.status === 429 || r.status >= 500) { await new Promise(s => setTimeout(s, 2000 * (a + 1))); continue; }
    if (r.status === 404) return null;
    if (!r.ok) throw new Error(`${p}: HTTP ${r.status}`);
    return r.json();
  }
  throw new Error(`${p}: gave up after retries`);
}
async function pages(p, max = 400) {
  const out = [];
  for (let off = 0; off < max; off += 100) {
    const j = await api(`${p}${p.includes('?') ? '&' : '?'}offset=${off}&limit=100`);
    const items = j?.items || [];
    out.push(...items);
    if (items.length < 100) break;
  }
  return out;
}
// ESEA_DEBUG=1: print what the API returns for 1NT (public data only), to see how a season is named
if (process.env.ESEA_DEBUG) {
  const sa = p => api(p).catch(e => ({ error: e.message }));
  const show = (k, v) => console.log(`--- ${k}\n${JSON.stringify(v, null, 1).slice(0, 4000)}`);
  const t = await sa(`/teams/${TEAM_ID}`); show('team', t && { name: t.name, game: t.game, members: (t.members || []).map(m => m.nickname) });
  const p = await sa(`/players?nickname=${encodeURIComponent(PLAYER)}`); show('player', p && { id: p.player_id, games: Object.keys(p.games || {}) });
  if (p?.player_id) {
    const h = await sa(`/players/${p.player_id}/history?game=cs2&limit=40`);
    show('history', (h?.items || []).map(m => ({ type: m.competition_type, name: m.competition_name, cid: m.competition_id, at: m.started_at, f1: m.teams?.faction1?.nickname, f2: m.teams?.faction2?.nickname, f1id: m.teams?.faction1?.team_id })));
  }
  show('team tournaments', (await sa(`/teams/${TEAM_ID}/tournaments?limit=20`))?.items?.map(x => ({ name: x.name, id: x.tournament_id || x.championship_id, type: x.type })));
  show('team stats keys', Object.keys((await sa(`/teams/${TEAM_ID}/stats/cs2`)) || {}));
  show('ESEA league', await sa('/leagues/a14b8616-45b9-4581-8637-4dfd0b5f6af8'));
  if (p?.player_id) {
    const st = await sa(`/players/${p.player_id}/stats/cs2`); show('player stats lifetime', st?.lifetime); show('player stats segment[0]', st?.segments?.[0]);
    const g = await sa(`/players/${p.player_id}/games/cs2/stats?limit=2`); show('games stats item[0]', g?.items?.[0]);
  }
  show('team members[0]', t?.members?.[0]);
  const tst = await sa(`/teams/${TEAM_ID}/stats/cs2`); show('team stats lifetime', tst?.lifetime); show('team stats segment[0]', tst?.segments?.[0]);
  for (const q of ['ESEA', 'Season 59', 'S59']) show(`search championships "${q}"`, (await sa(`/search/championships?name=${encodeURIComponent(q)}&game=cs2&type=ongoing&limit=20`))?.items?.map(x => ({ name: x.name, id: x.competition_id || x.championship_id, region: x.region, status: x.status })));
  process.exit(0);
}
// ---- FACEIT profile data (independent of the league season) -------------------------------------
// keys in FACEIT's stats objects are display labels ("Average K/D Ratio", "Win Rate %"); pick the
// first one present so a renamed label blanks a number instead of breaking the run
const pick = (o, ...ks) => { for (const k of ks) if (o && o[k] != null && o[k] !== '') return o[k]; return null; };
const n = v => (v == null || v === '' || isNaN(+String(v).replace(/[%,]/g, '')) ? null : +String(v).replace(/[%,]/g, ''));
async function profile() {
  const out = { me: null, roster: [], teamMaps: [], recent: [] };
  const p = await api(`/players?nickname=${encodeURIComponent(PLAYER)}`).catch(() => null);
  if (p?.player_id) {
    const cs = p.games?.cs2 || {};
    const st = await api(`/players/${p.player_id}/stats/cs2`).catch(() => null), L = st?.lifetime || {};
    out.me = { id: p.player_id, nickname: p.nickname, avatar: p.avatar || null, country: p.country || null, level: cs.skill_level ?? null, elo: cs.faceit_elo ?? null,
      matches: n(pick(L, 'Matches', 'Total Matches')), wins: n(pick(L, 'Wins')), winRate: n(pick(L, 'Win Rate %', 'Win Rate')),
      kd: n(pick(L, 'Average K/D Ratio', 'K/D Ratio')), hs: n(pick(L, 'Average Headshots %', 'Headshots %')), adr: n(pick(L, 'ADR', 'Average ADR')),
      longestStreak: n(pick(L, 'Longest Win Streak')), currentStreak: n(pick(L, 'Current Win Streak')),
      recentResults: (pick(L, 'Recent Results') || []).map(x => (String(x) === '1' ? 'W' : 'L')),
      maps: (st?.segments || []).filter(x => /map/i.test(x.type || '') && /5v5/i.test(x.mode || '5v5')).map(x => ({
        map: String(x.label || '').toLowerCase().replace(/^de_/, ''), matches: n(pick(x.stats, 'Matches')), winRate: n(pick(x.stats, 'Win Rate %')),
        kd: n(pick(x.stats, 'Average K/D Ratio', 'K/D Ratio')), adr: n(pick(x.stats, 'ADR', 'Average ADR')), hs: n(pick(x.stats, 'Average Headshots %')) }))
        .filter(x => x.matches).sort((a, b) => b.matches - a.matches) };
    // the last 20 FACEIT matches, one line each (K, D, K/D, ADR, result, map)
    const g = await api(`/players/${p.player_id}/games/cs2/stats?limit=20`).catch(() => null);
    out.recent = (g?.items || []).map(i => i.stats || {}).map(s => ({
      at: n(pick(s, 'Match Finished At', 'Updated At', 'Created At')), map: String(pick(s, 'Map') || '').replace(/^de_/, ''),
      result: String(pick(s, 'Result')) === '1' ? 'W' : String(pick(s, 'Result')) === '0' ? 'L' : null, score: pick(s, 'Score'),
      k: n(pick(s, 'Kills')), d: n(pick(s, 'Deaths')), kd: n(pick(s, 'K/D Ratio')), adr: n(pick(s, 'ADR')), hs: n(pick(s, 'Headshots %')),
      comp: pick(s, 'Competition Name', 'Game Mode') })).filter(x => x.k != null);
  }
  const t = await api(`/teams/${TEAM_ID}`).catch(() => null);
  for (const m of t?.members || []) {
    const q = await api(`/players/${m.user_id}`).catch(() => null);
    out.roster.push({ nickname: q?.nickname || m.nickname, country: q?.country || m.country || null, level: q?.games?.cs2?.skill_level ?? m.skill_level ?? null, elo: q?.games?.cs2?.faceit_elo ?? null, avatar: q?.avatar || m.avatar || null });
  }
  const ts = await api(`/teams/${TEAM_ID}/stats/cs2`).catch(() => null);
  out.team = ts?.lifetime ? { matches: n(pick(ts.lifetime, 'Matches')), winRate: n(pick(ts.lifetime, 'Win Rate %')), longestStreak: n(pick(ts.lifetime, 'Longest Win Streak')),
    recentResults: (pick(ts.lifetime, 'Recent Results') || []).map(x => (String(x) === '1' ? 'W' : 'L')) } : null;
  out.teamMaps = (ts?.segments || []).filter(x => /map/i.test(x.type || '')).map(x => ({ map: String(x.label || '').toLowerCase().replace(/^de_/, ''),
    matches: n(pick(x.stats, 'Matches')), winRate: n(pick(x.stats, 'Win Rate %')) })).filter(x => x.matches).sort((a, b) => b.matches - a.matches);
  return out;
}
const prof = await profile();
const writeOut = o => {
  const strip = x => JSON.stringify({ ...x, asof: null });
  if (fs.existsSync(OUT) && strip(prev) === strip(o)) { console.log('ESEA: no change'); return; }
  fs.writeFileSync(OUT, JSON.stringify(o, null, 1) + '\n');
  console.log(`wrote ${path.relative(ROOT, OUT)}: ${o.record ? `${o.record.w}-${o.record.l}` : 'no season yet'}, profile ${o.profile?.me ? `${o.profile.me.elo} elo` : 'none'}, roster ${o.profile?.roster?.length ?? 0}`);
};

// FACEIT names a season's competitions "S59 NA Main A - Regular Season", "S59 NA Main A - Playoffs", ...
const isSeason = name => new RegExp(`(^|\\b)(S|Season\\s*)${SEASON}\\b`, 'i').test(name || '');
const stageOf = name => (String(name || '').split(' - ')[1] || null);

// ---- which championship is this season's ------------------------------------------------------
const team = await api(`/teams/${TEAM_ID}`);
const me = await api(`/players?nickname=${encodeURIComponent(PLAYER)}`);
// every championship of the season: the regular season, then playoffs once they start (each is its
// own FACEIT competition). Found in the player's match history; remembered between runs.
const champs = new Map((prev.season === SEASON ? prev.championships || [] : []).map(c => [c.id, c]));
if (process.env.ESEA_CHAMPIONSHIP) champs.set(process.env.ESEA_CHAMPIONSHIP, { id: process.env.ESEA_CHAMPIONSHIP });
if (me?.player_id) {
  const hist = await pages(`/players/${me.player_id}/history?game=cs2`, 300);
  for (const m of hist) if (m.competition_type === 'championship' && isSeason(m.competition_name)) champs.set(m.competition_id, { id: m.competition_id, name: m.competition_name });
}
let champId = [...champs.values()].find(c => /regular/i.test(c.name || ''))?.id || [...champs.keys()][0] || null;
if (!champId) {
  // nothing played yet: the team's championships
  const list = await pages(`/teams/${TEAM_ID}/tournaments`, 200).catch(() => []);
  champId = list.find(t => isSeason(t.name))?.championship_id || list.find(t => isSeason(t.name))?.tournament_id || null;
}
if (champId && !champs.has(champId)) champs.set(champId, { id: champId });
if (!champId) { console.log(`ESEA S${SEASON}: no championship found for 1NT yet`); writeOut({ season: SEASON, asof: new Date().toISOString(), matches: [], profile: prof }); process.exit(0); }
const champ = await api(`/championships/${champId}`);

// ---- 1NT's matches, across the season's championships ------------------------------------------
const ours = [], seen = new Set();
for (const c of champs.values()) {
  const info = c.name ? c : { ...c, name: (await api(`/championships/${c.id}`))?.name || null };
  champs.set(c.id, info);
  for (const m of await pages(`/championships/${c.id}/matches?type=all`, 2000)) {
    if (seen.has(m.match_id) || ![m.teams?.faction1?.faction_id, m.teams?.faction2?.faction_id].includes(TEAM_ID)) continue;
    seen.add(m.match_id); ours.push({ ...m, _stage: stageOf(info.name) });
  }
}
const side = m => (m.teams.faction1.faction_id === TEAM_ID ? 'faction1' : 'faction2');
const other = s => (s === 'faction1' ? 'faction2' : 'faction1');
const num = v => (v == null || v === '' ? null : +String(v).replace('%', ''));

const matches = [];
for (const m of ours.sort((a, b) => (a.scheduled_at || a.started_at || 0) - (b.scheduled_at || b.started_at || 0))) {
  const us = side(m), them = other(us), opp = m.teams[them] || {};
  const row = {
    id: m.match_id, url: (m.faceit_url || '').replace('{lang}', 'en'), round: m.round ?? null, group: m.group ?? null, stage: m._stage || null,
    status: m.status, at: (m.started_at || m.scheduled_at || 0) * 1000 || null,
    opp: { id: opp.faction_id, name: opp.name || opp.nickname || 'TBD', avatar: opp.avatar || null },
    best_of: m.best_of ?? 1, maps: [], result: null, score: null,
  };
  if (m.status === 'FINISHED') {
    row.result = m.results?.winner === us ? 'W' : m.results?.winner === them ? 'L' : null;
    row.score = [m.results?.score?.[us] ?? null, m.results?.score?.[them] ?? null];
    const st = await api(`/matches/${m.match_id}/stats`);
    for (const r of st?.rounds || []) {
      const T = r.teams || [], mine = T.find(t => t.team_id === TEAM_ID) || T.find(t => (t.players || []).some(p => p.nickname === PLAYER)), theirs = T.find(t => t !== mine);
      if (!mine) continue;
      const ts = mine.team_stats || {}, os = theirs?.team_stats || {};
      row.maps.push({
        map: (r.round_stats?.Map || '').replace(/^de_/, ''), rf: num(ts['Final Score']), ra: num(os['Final Score']),
        win: ts['Team Win'] === '1' || num(ts['Final Score']) > num(os['Final Score']),
        players: (mine.players || []).map(p => {
          const s = p.player_stats || {};
          return { name: p.nickname, k: num(s.Kills), d: num(s.Deaths), a: num(s.Assists), adr: num(s.ADR), hs: num(s['Headshots %']),
            kd: num(s['K/D Ratio']), mvp: num(s.MVPs), k3: num(s['Triple Kills']), k4: num(s['Quadro Kills']), k5: num(s['Penta Kills']) };
        }).sort((a, b) => (b.k ?? 0) - (a.k ?? 0)),
      });
    }
  } else if (m.voting?.map?.pick?.length) {
    row.maps = m.voting.map.pick.map(x => ({ map: String(x).replace(/^de_/, '') }));
  }
  matches.push(row);
}

// ---- season summary ---------------------------------------------------------------------------
const done = matches.filter(m => m.result);
const maps = done.flatMap(m => m.maps.filter(x => x.rf != null));
const pool = {};
for (const x of maps) { const p = (pool[x.map] ||= { map: x.map, w: 0, l: 0, rf: 0, ra: 0 }); x.win ? p.w++ : p.l++; p.rf += x.rf; p.ra += x.ra; }
const ppl = {};
for (const x of maps) for (const p of x.players) {
  const q = (ppl[p.name] ||= { name: p.name, maps: 0, k: 0, d: 0, a: 0, adrSum: 0, hsSum: 0, rounds: 0, k3: 0, k4: 0, k5: 0, mvp: 0 });
  const rounds = (x.rf ?? 0) + (x.ra ?? 0);
  q.maps++; q.k += p.k ?? 0; q.d += p.d ?? 0; q.a += p.a ?? 0; q.adrSum += (p.adr ?? 0) * rounds; q.rounds += rounds;
  q.hsSum += (p.hs ?? 0) * (p.k ?? 0); q.k3 += p.k3 ?? 0; q.k4 += p.k4 ?? 0; q.k5 += p.k5 ?? 0; q.mvp += p.mvp ?? 0;
}
const r2 = x => Math.round(x * 100) / 100, r1 = x => Math.round(x * 10) / 10;
const players = Object.values(ppl).map(q => ({ name: q.name, maps: q.maps, k: q.k, d: q.d, a: q.a, kd: q.d ? r2(q.k / q.d) : null,
  adr: q.rounds ? r1(q.adrSum / q.rounds) : null, hs: q.k ? Math.round(q.hsSum / q.k) : null, kpr: q.rounds ? r2(q.k / q.rounds) : null,
  multi: q.k3 + q.k4 + q.k5, aces: q.k5, mvp: q.mvp })).sort((a, b) => (b.adr ?? 0) - (a.adr ?? 0));
let streak = null;
for (const m of [...done].reverse()) { if (!streak) streak = { t: m.result, n: 1 }; else if (m.result === streak.t) streak.n++; else break; }
const next = matches.find(m => !m.result && m.status !== 'CANCELLED' && m.at && m.at > Date.now() - 3 * 3600e3) || null;

const out = {
  season: SEASON, asof: new Date().toISOString(),
  championship: { id: champId, name: champ?.name || champs.get(champId)?.name || null,
    url: (champ?.faceit_url || '').replace('{lang}', 'en') || `https://www.faceit.com/en/teams/${TEAM_ID}/leagues` },
  championships: [...champs.values()].map(c => ({ id: c.id, name: c.name || null })),
  team: { id: TEAM_ID, name: team?.name || '1NT', avatar: team?.avatar || null },
  record: { w: done.filter(m => m.result === 'W').length, l: done.filter(m => m.result === 'L').length, played: done.length, total: Math.max(matches.length, REG_SEASON),
    mapsW: maps.filter(x => x.win).length, mapsL: maps.filter(x => !x.win).length,
    rf: maps.reduce((a, x) => a + x.rf, 0), ra: maps.reduce((a, x) => a + x.ra, 0),
    streak, form: done.slice(-5).map(m => m.result).join('') },
  next: next && { id: next.id, at: next.at, opp: next.opp, url: next.url, status: next.status },
  matches, pool: Object.values(pool).sort((a, b) => (b.w + b.l) - (a.w + a.l) || b.w - a.w), players, profile: prof,
};
writeOut(out);   // only rewrites when the content changed (the workflow commits on change)
