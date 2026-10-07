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

// ---- standings: every leaderboard (group) of the season's championships, rank by team id ----------
const standings = {}, lbSeen = [];
for (const c of champs.values()) {
  const lbs = await api(`/leaderboards/championships/${c.id}?limit=100`).catch(e => ({ error: e.message }));
  lbSeen.push({ id: c.id, n: lbs?.items?.length ?? 0, error: lbs?.error || null, board: lbs?.items?.[0] || null });
  for (const lb of lbs?.items || []) {
    const rows = await pages(`/leaderboards/${lb.leaderboard_id}`, 600).catch(() => []);
    lbSeen.at(-1).sample = rows[0] || null; lbSeen.at(-1).rows = rows.length;
    for (const it of rows) {
      const tid = it.team?.team_id || it.team?.faction_id || it.team?.id || it.team_id || it.player?.player_id; if (!tid) continue;
      standings[tid] = { rank: it.position ?? null, of: rows.length, points: it.points ?? null, w: it.won ?? null, l: it.lost ?? null,
        played: it.played ?? null, group: lb.group ?? null, board: lb.leaderboard_name || null };
    }
  }
}

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

const matches = [], statKeys = new Set(), allLines = [];
// FACEIT's own Rating and Swing aren't in the public Data API, so: HLTV's published Rating 1.0
// (kills, survival and multi-kill rounds, each against its average), and the common Rating 2.0
// impact approximation (2.13 KPR + 0.42 APR - 0.41). Computed from the box score, rounds = map rounds.
function rate(p, rounds) {
  if (!rounds || p.k == null) return { rating: null, impact: null };
  const k2 = p.k2 ?? 0, k3 = p.k3 ?? 0, k4 = p.k4 ?? 0, k5 = p.k5 ?? 0;
  const k1 = Math.max(0, p.k - 2 * k2 - 3 * k3 - 4 * k4 - 5 * k5);
  const kill = p.k / rounds / 0.679, surv = (rounds - (p.d ?? 0)) / rounds / 0.317;
  const multi = (k1 + 4 * k2 + 9 * k3 + 16 * k4 + 25 * k5) / rounds / 1.277;
  return { rating: Math.round((kill + 0.7 * surv + multi) / 2.7 * 100) / 100,
    impact: Math.round((2.13 * p.k / rounds + 0.42 * (p.a ?? 0) / rounds - 0.41) * 100) / 100 };
}
for (const m of ours.sort((a, b) => (a.scheduled_at || a.started_at || 0) - (b.scheduled_at || b.started_at || 0))) {
  const us = side(m), them = other(us), opp = m.teams[them] || {};
  const row = {
    id: m.match_id, url: (m.faceit_url || '').replace('{lang}', 'en'), round: m.round ?? null, group: m.group ?? null, stage: m._stage || null,
    status: m.status, at: (m.started_at || m.scheduled_at || 0) * 1000 || null,
    opp: { id: opp.faction_id, name: opp.name || opp.nickname || 'TBD', avatar: opp.avatar || null, rank: standings[opp.faction_id]?.rank ?? null },
    rank: standings[TEAM_ID]?.rank ?? null,
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
      const rounds = num(ts['Final Score']) + num(os['Final Score']);
      const lines = team => (team?.players || []).map(p => {
        const s = p.player_stats || {};
        for (const k of Object.keys(s)) statKeys.add(k);
        const ln = { name: p.nickname, k: num(s.Kills), d: num(s.Deaths), a: num(s.Assists), adr: num(s.ADR), hs: num(s['Headshots %']),
          kd: num(s['K/D Ratio']), mvp: num(s.MVPs), k2: num(s['Double Kills']), k3: num(s['Triple Kills']), k4: num(s['Quadro Kills']), k5: num(s['Penta Kills']),
          entries: num(s['Entry Count']), entryWins: num(s['Entry Wins']), c11: num(s['1v1Wins']) ?? 0, c12: num(s['1v2Wins']) ?? 0,
          util: num(s['Utility Damage']), flashed: num(s['Enemies Flashed']), rounds };
        ln.clutch = ln.c11 + ln.c12;
        allLines.push(ln);
        return { ...ln, hltv: rate(ln, rounds).rating, impact: rate(ln, rounds).impact };
      });
      row.maps.push({
        map: (r.round_stats?.Map || '').replace(/^de_/, ''), rf: num(ts['Final Score']), ra: num(os['Final Score']),
        win: ts['Team Win'] === '1' || num(ts['Final Score']) > num(os['Final Score']),
        players: lines(mine), opp: lines(theirs),
      });
    }
  } else if (m.voting?.map?.pick?.length) {
    row.maps = m.voting.map.pick.map(x => ({ map: String(x).replace(/^de_/, '') }));
  }
  matches.push(row);
}

// ---- ARK Rating: built on HLTV Rating 3.0's structure ------------------------------------------
// Rating 3.0 rates kills, deaths, damage, multi-kills and Round Swing (win probability a player adds),
// each against the average player. FACEIT's API has no per-round data, so there's no economy
// adjustment and Swing is estimated from the round-deciding events it does record: an opening duel
// moves a round's win probability ~20 points (+0.20 won, -0.20 lost), a 1v1 clutch win ~+0.50, a 1v2
// ~+0.75, an assist ~+0.05. Baselines are the averages of every player in these matches (both teams),
// shrunk toward standard values (30 player-maps) while the season is young, so 1.00 = league average.
const ARK_W = { kill: 0.25, surv: 0.15, dmg: 0.25, multi: 0.10, swing: 0.25 };
const comp = l => {
  const R = l.rounds || 0; if (!R || l.k == null) return null;
  const k2 = l.k2 ?? 0, k3 = l.k3 ?? 0, k4 = l.k4 ?? 0, k5 = l.k5 ?? 0, k1 = Math.max(0, l.k - 2 * k2 - 3 * k3 - 4 * k4 - 5 * k5);
  const ew = l.entryWins ?? 0, el = Math.max(0, (l.entries ?? 0) - ew);
  return { kpr: l.k / R, dpr: (l.d ?? 0) / R, adr: l.adr ?? 0, mks: (k1 + 4 * k2 + 9 * k3 + 16 * k4 + 25 * k5) / R,
    swing: (0.20 * (ew - el) + 0.50 * (l.c11 ?? 0) + 0.75 * (l.c12 ?? 0) + 0.05 * (l.a ?? 0)) / R };
};
const PRIOR = { kpr: 0.68, dpr: 0.68, adr: 76, mks: 1.27, swing: 0.03, swingSd: 0.05 }, PW = 30;
const cs = allLines.map(comp).filter(Boolean);
const bl = k => (PRIOR[k] * PW + cs.reduce((a, c) => a + c[k], 0)) / (PW + cs.length);
const BASE = { kpr: bl('kpr'), dpr: bl('dpr'), adr: bl('adr'), mks: bl('mks'), swing: bl('swing') };
BASE.swingSd = Math.sqrt((PRIOR.swingSd ** 2 * PW + cs.reduce((a, c) => a + (c.swing - BASE.swing) ** 2, 0)) / (PW + cs.length));
function ark(l) {
  const c = comp(l); if (!c) return null;
  const parts = { kill: c.kpr / BASE.kpr, surv: (1 - c.dpr) / (1 - BASE.dpr), dmg: c.adr / BASE.adr, multi: c.mks / BASE.mks,
    swing: 1 + (c.swing - BASE.swing) / BASE.swingSd * 0.25 };
  const rating = Object.entries(ARK_W).reduce((a, [k, w]) => a + w * parts[k], 0);
  return { rating: Math.round(rating * 100) / 100, swing: Math.round((c.swing - BASE.swing) * 1000) / 10,   // swing: % of a round per round vs average
    parts: Object.fromEntries(Object.entries(parts).map(([k, v]) => [k, Math.round(v * 100) / 100])) };
}
for (const m of matches) for (const x of m.maps) for (const side of ['players', 'opp']) if (x[side]) {
  x[side] = x[side].map(p => ({ ...p, ...ark(p) })).sort((a, b) => (b.rating ?? 0) - (a.rating ?? 0) || (b.k ?? 0) - (a.k ?? 0));
}

// ---- season summary ---------------------------------------------------------------------------
const done = matches.filter(m => m.result);
const maps = done.flatMap(m => m.maps.filter(x => x.rf != null));
const pool = {};
for (const x of maps) { const p = (pool[x.map] ||= { map: x.map, w: 0, l: 0, rf: 0, ra: 0 }); x.win ? p.w++ : p.l++; p.rf += x.rf; p.ra += x.ra; }
const ppl = {};
for (const x of maps) for (const p of x.players) {
  const q = (ppl[p.name] ||= { name: p.name, maps: 0, k: 0, d: 0, a: 0, adrSum: 0, hsSum: 0, rounds: 0, k2: 0, k3: 0, k4: 0, k5: 0, mvp: 0, entries: 0, entryWins: 0, clutch: 0, util: 0, games: [] });
  q.c11 = (q.c11 || 0) + (p.c11 ?? 0); q.c12 = (q.c12 || 0) + (p.c12 ?? 0);
  q.k2 += p.k2 ?? 0; q.entries += p.entries ?? 0; q.entryWins += p.entryWins ?? 0; q.clutch += p.clutch ?? 0; q.util += p.util ?? 0;
  q.games.push({ map: x.map, rf: x.rf, ra: x.ra, win: x.win, k: p.k, d: p.d, adr: p.adr, rating: p.rating });
  const rounds = (x.rf ?? 0) + (x.ra ?? 0);
  q.maps++; q.k += p.k ?? 0; q.d += p.d ?? 0; q.a += p.a ?? 0; q.adrSum += (p.adr ?? 0) * rounds; q.rounds += rounds;
  q.hsSum += (p.hs ?? 0) * (p.k ?? 0); q.k3 += p.k3 ?? 0; q.k4 += p.k4 ?? 0; q.k5 += p.k5 ?? 0; q.mvp += p.mvp ?? 0;
}
const r2 = x => Math.round(x * 100) / 100, r1 = x => Math.round(x * 10) / 10;
const players = Object.values(ppl).map(q => ({ name: q.name, maps: q.maps, k: q.k, d: q.d, a: q.a, kd: q.d ? r2(q.k / q.d) : null,
  adr: q.rounds ? r1(q.adrSum / q.rounds) : null, hs: q.k ? Math.round(q.hsSum / q.k) : null, kpr: q.rounds ? r2(q.k / q.rounds) : null,
  multi: q.k3 + q.k4 + q.k5, aces: q.k5, mvp: q.mvp, hltv: rate(q, q.rounds).rating, impact: rate(q, q.rounds).impact,
  ...ark({ ...q, adr: q.rounds ? q.adrSum / q.rounds : 0 }),
  entryPM: q.entryWins - (q.entries - q.entryWins), entries: q.entries, clutch: q.clutch, utilPR: q.rounds ? r1(q.util / q.rounds) : null,
  best: [...q.games].sort((a, b) => (b.rating ?? 0) - (a.rating ?? 0))[0] || null, games: q.games.map(g => g.rating) }))
  .sort((a, b) => (b.rating ?? 0) - (a.rating ?? 0));
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
  standing: standings[TEAM_ID] || null, leaderboards: lbSeen,
  statKeys: [...statKeys].sort(), ratingBase: Object.fromEntries(Object.entries(BASE).map(([k, v]) => [k, Math.round(v * 1000) / 1000])), ratingSample: cs.length, matches, pool: Object.values(pool).sort((a, b) => (b.w + b.l) - (a.w + a.l) || b.w - a.w), players, profile: prof,
};
writeOut(out);   // only rewrites when the content changed (the workflow commits on change)
