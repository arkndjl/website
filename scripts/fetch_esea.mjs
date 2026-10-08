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
// ---- role from a player's recent FACEIT matches -------------------------------------------------
// Rolling, not lifetime: the player's last ROLE_MAPS maps from the past ROLE_DAYS days (PUGs, scrims
// and league), read from each match's box score (sniper kills, opening duels, flashes and utility
// thrown, 1v1/1v2 setups). Box scores are cached between runs in .cache/esea/matches.json (the
// workflow keeps it with actions/cache), so a match is fetched once for everyone who played in it.
// Shares and rates against typical level-10 values: sniper kills as a share of kills (AWPer at 25%+,
// hybrid at 15%+), opening duels per round (entry), flashes and utility per round minus entry
// (support), 1v1/1v2 setups per round minus entry (lurker: the one left alive late). The highest
// standardized score names the role; nothing a half-SD above normal reads "rifler".
const ROLE_MAPS = 100, ROLE_DAYS = 90, CACHE = path.join(ROOT, '.cache', 'esea', 'matches.json');
const mcache = (() => { try { return JSON.parse(fs.readFileSync(CACHE, 'utf8')); } catch { return {}; } })();
function saveCache() {
  const cut = Date.now() - 150 * 864e5;
  for (const [k, v] of Object.entries(mcache)) if ((v.at || 0) < cut) delete mcache[k];
  fs.mkdirSync(path.dirname(CACHE), { recursive: true }); fs.writeFileSync(CACHE, JSON.stringify(mcache));
}
// cached line: [k, sniper, entries, flashCount, utilCount, clutchSetups, d, a, adr, k2, k3, k4, k5, entryWins, 1v1W, 1v2W, utilDmg, flashed,
//               roundMVPs, flashSuccesses, utilSuccesses, clutchKills, pistolKills, headshots, 1v1Count, 1v2Count]
async function boxLines(mid, at) {
  if (mcache[mid]?.v === 5) return mcache[mid];
  const st = await api(`/matches/${mid}/stats`).catch(() => null);
  const maps = (st?.rounds || []).map(r => {
    const R = n(r.round_stats?.Rounds) || (r.teams || []).reduce((a, t) => a + (n(t.team_stats?.['Final Score']) || 0), 0);
    const L = {}, T = (r.teams || []).map(t => (t.players || []).map(p => p.player_id)), S = (r.teams || []).map(t => n(t.team_stats?.['Final Score']) ?? 0);
    for (const t of r.teams || []) for (const p of t.players || []) {
      const x = p.player_stats || {};
      L[p.player_id] = [n(x.Kills) || 0, n(x['Sniper Kills']) || 0, n(x['Entry Count']) || 0, n(x['Flash Count']) || 0, n(x['Utility Count']) || 0, (n(x['1v1Count']) || 0) + (n(x['1v2Count']) || 0),
        n(x.Deaths) || 0, n(x.Assists) || 0, n(x.ADR) || 0, n(x['Double Kills']) || 0, n(x['Triple Kills']) || 0, n(x['Quadro Kills']) || 0, n(x['Penta Kills']) || 0,
        n(x['Entry Wins']) || 0, n(x['1v1Wins']) || 0, n(x['1v2Wins']) || 0, n(x['Utility Damage']) || 0, n(x['Enemies Flashed']) || 0,
        n(x.MVPs) || 0, n(x['Flash Successes']) || 0, n(x['Utility Successes']) || 0, n(x['Clutch Kills']) || 0, n(x['Pistol Kills']) || 0,
        n(x.Headshots) || 0, n(x['1v1Count']) || 0, n(x['1v2Count']) || 0];
    }
    return { R, L, T, S, map: String(r.round_stats?.Map || '').replace(/^de_/, '') };
  });
  return (mcache[mid] = { v: 5, at, maps });
}
const MEMBER_IDS = new Set();   // 1NT's FACEIT members, for spotting scrims in the rolling window
async function rollingRole(pid, maxMaps = ROLE_MAPS) {
  const j = await api(`/players/${pid}/games/cs2/stats?limit=100`).catch(() => null);
  const cut = Date.now() - ROLE_DAYS * 864e5, ids = [];
  // official = played under a real team name (league, cups, qualifiers); queue teams are "team_<captain>"
  for (const i of j?.items || []) { const s = i.stats || {}, at = n(s['Match Finished At']) || 0; if (at >= cut && !ids.some(x => x.id === s['Match Id'])) ids.push({ id: s['Match Id'], at, official: !/^team_/i.test(String(s.Team || 'team_')) }); }
  const t = { maps: 0, R: 0, k: 0, snip: 0, entry: 0, flash: 0, util: 0, clutch: 0 };
  // the same maps as one ARK-ready stat line (rated later, once the league baseline is known)
  const blankT = () => ({ maps: 0, w: 0, k: 0, d: 0, a: 0, adrSum: 0, rounds: 0, k2: 0, k3: 0, k4: 0, k5: 0, entries: 0, entryWins: 0, c11: 0, c12: 0, util: 0, flashed: 0, snip: 0, flashes: 0, utilN: 0, setups: 0 });
  const tot = blankT(), tot20 = blankT(), B = { official: blankT(), pug: blankT(), scrim: blankT() };
  for (const { id, at, official } of ids) {
    if (t.maps >= maxMaps) break;
    const m = await boxLines(id, at);
    for (const mp of m.maps) {
      const l = mp.L[pid]; if (!l || !mp.R) continue;
      t.maps++; t.R += mp.R; t.k += l[0]; t.snip += l[1]; t.entry += l[2]; t.flash += l[3]; t.util += l[4]; t.clutch += l[5];
      const side = (mp.T || []).find(t => t.includes(pid)) || [];

      const bucket = official ? 'official' : side.filter(x => MEMBER_IDS.has(x)).length >= 5 ? 'scrim' : 'pug';
      for (const q of tot.maps < 20 ? [tot, tot20, B[bucket]] : [tot, B[bucket]]) {
        q.maps++; q.k += l[0]; q.d += l[6]; q.a += l[7]; q.adrSum += l[8] * mp.R; q.rounds += mp.R; q.k2 += l[9]; q.k3 += l[10]; q.k4 += l[11]; q.k5 += l[12];
        q.entries += l[2]; q.entryWins += l[13]; q.c11 += l[14]; q.c12 += l[15]; q.util += l[16]; q.flashed += l[17];
        q.snip += l[1]; q.flashes += l[3]; q.utilN += l[4]; q.setups += l[5];
        q.fsucc = (q.fsucc || 0) + (l[19] ?? 0); q.usucc = (q.usucc || 0) + (l[20] ?? 0); q.pid = pid; (q.refs ||= []).push([id, m.maps.indexOf(mp)]);   // team credit added later (residOf)
        const si = (mp.T || []).findIndex(tm => tm.includes(pid)); if (si >= 0 && mp.S) q.rw = (q.rw || 0) + mp.S[si];
      }
    }
  }
  if (t.R < 200) return null;
  const snip = t.k ? t.snip / t.k : 0, entry = t.entry / t.R, flash = t.flash / t.R, util = t.util / t.R, clutch = t.clutch / t.R;
  const z = { entry: (entry - 0.22) / 0.035, flash: (flash - 0.55) / 0.15, util: (util - 0.5) / 0.12, clutch: (clutch - 0.055) / 0.012 };
  const sc = { entry: z.entry, support: (z.flash + z.util) / 2 - 0.5 * z.entry, lurker: z.clutch - 0.5 * z.entry };
  const top = Object.entries(sc).sort((a, b) => b[1] - a[1])[0];
  const r2 = x => Math.round(x * 100) / 100;
  const out = { sniper: r2(snip), entry: r2(entry), flash: r2(flash), util: r2(util), clutch: Math.round(clutch * 1000) / 1000, maps: t.maps, days: ROLE_DAYS, tot, tot20, buckets: B, ids };
  if (snip >= 0.25) return { role: 'AWPer', ...out };
  const main = top[1] >= 0.5 ? top[0] : 'rifler';
  return { role: snip >= 0.15 ? `hybrid AWP / ${main}` : main, ...out };
}
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
  if (p?.player_id) out.split = await split(p.player_id).catch(e => (console.log('split:', e.message), null));
  const t = await api(`/teams/${TEAM_ID}`).catch(() => null);
  for (const m of t?.members || []) MEMBER_IDS.add(m.user_id);
  for (const m of t?.members || []) {
    const q = await api(`/players/${m.user_id}`).catch(() => null);
    const rl = await rollingRole(m.user_id).catch(() => null);
    out.roster.push({ nickname: q?.nickname || m.nickname, id: m.user_id, country: q?.country || m.country || null, level: q?.games?.cs2?.skill_level ?? m.skill_level ?? null, elo: q?.games?.cs2?.faceit_elo ?? null, avatar: q?.avatar || m.avatar || null, role: rl });
  }
  const ts = await api(`/teams/${TEAM_ID}/stats/cs2`).catch(() => null);
  out.team = ts?.lifetime ? { matches: n(pick(ts.lifetime, 'Matches')), winRate: n(pick(ts.lifetime, 'Win Rate %')), longestStreak: n(pick(ts.lifetime, 'Longest Win Streak')),
    recentResults: (pick(ts.lifetime, 'Recent Results') || []).map(x => (String(x) === '1' ? 'W' : 'L')) } : null;
  out.teamMaps = (ts?.segments || []).filter(x => /map/i.test(x.type || '')).map(x => ({ map: String(x.label || '').toLowerCase().replace(/^de_/, ''),
    matches: n(pick(x.stats, 'Matches')), winRate: n(pick(x.stats, 'Win Rate %')) })).filter(x => x.matches).sort((a, b) => b.matches - a.matches);
  return out;
}
// ---- PUGs vs league matches -------------------------------------------------------------------
// The player's per-match stats (up to the last 1,000) split by what kind of competition each match
// was: FACEIT's match history labels it "matchmaking" (queue PUGs; hubs count as PUGs too) or
// "championship" (ESEA and other leagues/cups: "1NT matches"). Queue/hub matches with five 1NT members
// on his side are scrims. Matches missing from the history fall back on the team name: queue teams are
// named "team_<captain>".
const COMP_NAMES = new Map();   // competition id -> name, from LAURSEN_111's history (filled by split())
async function split(pid) {
  const kind = new Map(), compKind = new Map(), compName = COMP_NAMES, stack = new Map();
  // 1NT members: the FACEIT team's members plus the page's roster (data/cs.json starters and subs)
  const team = await api(`/teams/${TEAM_ID}`).catch(() => null);
  const ids = new Set((team?.members || []).map(m => m.user_id));
  let cs = {}; try { cs = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'cs.json'), 'utf8')); } catch {}
  const nicks = new Set([...(team?.members || []).map(m => m.nickname), ...(cs.roster?.starters || []), ...(cs.roster?.subs || [])]
    .map(x => String(Array.isArray(x) ? x[0] : typeof x === 'string' ? x : x?.nickname || x?.name || '').toLowerCase()).filter(Boolean));
  for (const h of await pages(`/players/${pid}/history?game=cs2&from=1500000000`, 1000)) {
    const league = h.competition_type === 'championship';
    kind.set(h.match_id, league); compKind.set(h.competition_id, league); compName.set(h.competition_id, h.competition_name || null);
    // how many 1NT members were on his side
    for (const f of Object.values(h.teams || {})) {
      const pl = f.players || [];
      if (!pl.some(x => x.player_id === pid)) continue;
      stack.set(h.match_id, pl.filter(x => ids.has(x.player_id) || nicks.has(String(x.nickname || '').toLowerCase())).length);
    }
  }
  // the endpoint stops paging by offset after a few hundred, so walk back by date instead
  const items = [], seenM = new Set();
  let to = null, unit = 1;   // "to" in ms; falls back to seconds if ms brings nothing new
  for (let req = 0; req < 16; req++) {
    const j = await api(`/players/${pid}/games/cs2/stats?limit=100${to ? `&to=${Math.floor(to / unit)}` : ''}`).catch(() => null);
    const got = (j?.items || []).map(i => i.stats || {}).filter(x => !seenM.has(x['Match Id'] + x['Match Round']));
    if (!got.length && to && unit === 1) { unit = 1000; continue; }
    got.forEach(x => seenM.add(x['Match Id'] + x['Match Round'])); items.push(...got);
    const oldest = Math.min(...got.map(x => n(x['Match Finished At']) || Infinity));
    if (got.length < 50 || !isFinite(oldest)) break;
    to = oldest - 1;
  }
  const blank = () => ({ n: 0, w: 0, l: 0, k: 0, d: 0, a: 0, rounds: 0, dmg: 0, hsK: 0, k2: 0, k3: 0, k4: 0, k5: 0, mvp: 0, from: null, to: null, form: [] });
  const add = (q, g) => {
    q.n++; g.win ? q.w++ : q.l++; q.k += g.k; q.d += g.d; q.a += g.a; q.rounds += g.rounds; q.dmg += g.dmg; q.hsK += g.hsK;
    q.k2 += g.k2; q.k3 += g.k3; q.k4 += g.k4; q.k5 += g.k5; q.mvp += g.mvp;
    q.from = Math.min(q.from ?? g.at, g.at); q.to = Math.max(q.to ?? g.at, g.at); if (q.form.length < 10) q.form.push(g.win ? 'W' : 'L');
  };
  const fin = q => q.n ? { matches: q.n, w: q.w, l: q.l, winRate: Math.round(q.w / q.n * 100), k: q.k, d: q.d, a: q.a,
    kd: q.d ? Math.round(q.k / q.d * 100) / 100 : null, kpr: q.rounds ? Math.round(q.k / q.rounds * 100) / 100 : null,
    adr: q.rounds ? Math.round(q.dmg / q.rounds * 10) / 10 : null, hs: q.k ? Math.round(q.hsK / q.k * 100) : null,
    kpm: Math.round(q.k / q.n * 10) / 10, multiPM: Math.round((q.k3 + q.k4 + q.k5) / q.n * 100) / 100, aces: q.k5, mvpPM: Math.round(q.mvp / q.n * 10) / 10,
    hltv: rate(q, q.rounds).rating, impact: rate(q, q.rounds).impact, from: q.from, to: q.to, form: q.form.join('') } : null;
  const B = { pug: blank(), scrim: blank(), league: blank() }, M = { pug: {}, scrim: {}, league: {} }, S = {}, D30 = { pug: blank(), scrim: blank(), league: blank() };
  const now = Date.now(), CUPS = {};
  for (const s of items) {   // newest first
    const g = { at: n(pick(s, 'Match Finished At')) || Date.parse(pick(s, 'Created At')) || 0, win: String(pick(s, 'Result')) === '1',
      k: n(s.Kills) ?? 0, d: n(s.Deaths) ?? 0, a: n(s.Assists) ?? 0, rounds: n(s.Rounds) ?? 0, mvp: n(s.MVPs) ?? 0,
      k2: n(s['Double Kills']) ?? 0, k3: n(s['Triple Kills']) ?? 0, k4: n(s['Quadro Kills']) ?? 0, k5: n(s['Penta Kills']) ?? 0,
      map: String(pick(s, 'Map') || '').replace(/^de_/, '') };
    if (!g.rounds) continue;
    g.dmg = n(s.Damage) ?? (n(s.ADR) ?? 0) * g.rounds; g.hsK = n(s.Headshots) ?? Math.round((n(s['Headshots %']) ?? 0) * g.k / 100);
    const cid = s['Competition Id'], mid = s['Match Id'];
    const league = kind.has(mid) ? kind.get(mid) : compKind.has(cid) ? compKind.get(cid) : !/^team_/i.test(String(s.Team || 'team_'));
    // scrims: queue/hub matches with 5 1NT members on his side
    const b = league ? 'league' : (stack.get(mid) ?? 0) >= 5 ? 'scrim' : 'pug';
    add(B[b], g); if (now - g.at < 30 * 864e5) add(D30[b], g);
    if (g.map) add(M[b][g.map] ||= blank(), g);
    if (league) {
      const name = compName.get(cid) || 'league match', sn = /(?:^|\b)S(?:eason\s*)?(\d{2,3})\b/i.exec(name);
      const esea = sn && !/CCT|Liquid|Lockdown|Clash/i.test(name), key = esea ? `S${sn[1]}` : 'other';
      add((S[key] ||= { ...blank(), name: esea ? `ESEA ${key}` : 'other cups & qualifiers' }), g);
      // every non-ESEA competition on its own, for the results log
      if (!esea && !/^normal/i.test(name)) add((CUPS[name] ||= { ...blank(), name, team: String(s.Team || '') }), g);
    }
  }
  const maps = [...new Set([...Object.keys(M.pug), ...Object.keys(M.scrim), ...Object.keys(M.league)])]
    .map(m => ({ map: m, pug: fin(M.pug[m] || blank()), scrim: fin(M.scrim[m] || blank()), league: fin(M.league[m] || blank()) }))
    .sort((x, y) => ((y.pug?.matches || 0) + (y.scrim?.matches || 0) + (y.league?.matches || 0)) - ((x.pug?.matches || 0) + (x.scrim?.matches || 0) + (x.league?.matches || 0)));
  return { sample: items.length, classified: kind.size, pug: fin(B.pug), scrim: fin(B.scrim), league: fin(B.league), last30: { pug: fin(D30.pug), scrim: fin(D30.scrim), league: fin(D30.league) }, maps,
    cups: Object.values(CUPS).map(q => ({ name: q.name, team: q.team, w: q.w, l: q.l, at: q.to, kd: q.d ? Math.round(q.k / q.d * 100) / 100 : null })).sort((x, y) => y.at - x.at),
    seasons: Object.entries(S).map(([k, q]) => ({ key: k, name: q.name, ...fin(q) })).sort((x, y) => (x.key === 'other') - (y.key === 'other') || (y.to || 0) - (x.to || 0)) };
}
const prof = await profile();
// ---- plus stats: 100 = average, every 10 = one standard deviation (like OPS+) -------------------
// Every player gets every stat. Baselines come from every player in the cached box scores (the last
// 90 days of maps 1NT's players and opponents played, mostly level-10 NA), one row per player with
// 15+ maps; rates are shrunk toward average where a player has few attempts.
//   Entry+   opening duels: success rate (shrunk by 10 duels) and net round value per round
//            (each opening duel ~ +/-0.20 of a round, so volume counts)
//   Duel+    the fights after the opening one: share won (kills vs deaths outside opening duels,
//            shrunk by 20) and kills per round
//   Multi+   multi-kill rounds per round, weighted by size (2k 1, 3k 2, 4k 3, ace 4)
//   Clutch+  1v1/1v2 conversion on the setups faced (shrunk by 10) and clutch value per round
//            (a 1v1 won ~ 0.5 of a round, a 1v2 ~ 0.75)
//   Util+    utility damage per round, enemies flashed per flash thrown, flashes per round
//   AWP+     AWP impact: sniper kills per round and share of kills with the sniper, against everyone
//            (AWPers land well above 100; AWP-vs-AWP duels and deaths holding it need demos)
//   Surv+    deaths per round, inverted
const PLUS = (() => {
  const P = {};
  for (const m of Object.values(mcache)) for (const mp of m.maps || []) for (const [pid, l] of Object.entries(mp.L || {})) {
    if (!mp.R || l.length < 18) continue;
    const q = (P[pid] ||= { maps: 0, rounds: 0, k: 0, d: 0, snip: 0, entries: 0, entryWins: 0, setups: 0, c11: 0, c12: 0, util: 0, flashed: 0, flashes: 0, k2: 0, k3: 0, k4: 0, k5: 0 });
    q.maps++; q.rounds += mp.R; q.k += l[0]; q.d += l[6]; q.snip += l[1]; q.entries += l[2]; q.entryWins += l[13];
    q.setups += l[5]; q.c11 += l[14]; q.c12 += l[15]; q.util += l[16]; q.flashed += l[17]; q.flashes += l[3];
    q.k2 += l[9]; q.k3 += l[10]; q.k4 += l[11]; q.k5 += l[12];
  }
  const rows = Object.values(P).filter(q => q.maps >= 15);
  const sum = k => rows.reduce((a, q) => a + q[k], 0);
  const lgEntry = sum('entryWins') / Math.max(1, sum('entries')) || 0.5;
  const lgClutch = (sum('c11') + sum('c12')) / Math.max(1, sum('setups')) || 0.3;
  const lgDuel = (sum('k') - sum('entryWins')) / Math.max(1, sum('k') - sum('entryWins') + sum('d') - (sum('entries') - sum('entryWins'))) || 0.5;
  const feats = q => {
    const el = Math.max(0, (q.entries || 0) - (q.entryWins || 0)), dk = Math.max(0, q.k - (q.entryWins || 0)), dd = Math.max(0, (q.d || 0) - el);
    return {
      entryPct: ((q.entryWins || 0) + 10 * lgEntry) / ((q.entries || 0) + 10), entryVal: 0.2 * ((q.entryWins || 0) - el) / q.rounds,
      duelPct: (dk + 20 * lgDuel) / (dk + dd + 20), kpr: q.k / q.rounds,
      multi: ((q.k2 || 0) + 2 * (q.k3 || 0) + 3 * (q.k4 || 0) + 4 * (q.k5 || 0)) / q.rounds,
      clutchPct: ((q.c11 || 0) + (q.c12 || 0) + 10 * lgClutch) / ((q.setups || 0) + 10), clutchVal: (0.5 * (q.c11 || 0) + 0.75 * (q.c12 || 0)) / q.rounds,
      udr: (q.util || 0) / q.rounds, fpf: q.flashes ? (q.flashed || 0) / q.flashes : 0, fpr: (q.flashes || 0) / q.rounds,
      snipKpr: (q.snip || 0) / q.rounds, snipShare: q.k ? (q.snip || 0) / q.k : 0, dpr: (q.d || 0) / q.rounds };
  };
  const F = rows.map(feats);
  const ms = k => { const v = F.map(f => f[k]); const m = v.reduce((a, x) => a + x, 0) / (v.length || 1); const sd = Math.sqrt(v.reduce((a, x) => a + (x - m) ** 2, 0) / Math.max(1, v.length - 1)) || 1; return [m, sd]; };
  const B = {}; for (const k of ['entryPct', 'entryVal', 'duelPct', 'kpr', 'multi', 'clutchPct', 'clutchVal', 'udr', 'fpf', 'fpr', 'snipKpr', 'snipShare', 'dpr']) B[k] = ms(k);
  return { feats, B, players: rows.length, awpers: F.filter(f => f.snipShare >= 0.25).length, lgEntry: Math.round(lgEntry * 1000) / 1000, lgClutch: Math.round(lgClutch * 1000) / 1000, lgDuel: Math.round(lgDuel * 1000) / 1000 };
})();
function plus(q) {
  if (!q?.rounds) return {};
  const f = PLUS.feats(q), z = k => (f[k] - PLUS.B[k][0]) / PLUS.B[k][1], P = x => Math.round(100 + 10 * x);
  return { entryPlus: q.entries ? P(0.5 * z('entryPct') + 0.5 * z('entryVal')) : null, duelPlus: P(0.5 * z('duelPct') + 0.5 * z('kpr')), multiPlus: P(z('multi')),
    clutchPlus: q.setups ? P(0.5 * z('clutchPct') + 0.5 * z('clutchVal')) : null, utilPlus: P(0.4 * z('udr') + 0.3 * z('fpf') + 0.3 * z('fpr')),
    awpPlus: P(0.6 * z('snipKpr') + 0.4 * z('snipShare')), survPlus: P(-z('dpr')), entryPct: q.entries ? Math.round(q.entryWins / q.entries * 100) : null };
}
// demo access probe (logs only): can this key reach match demos? (positions/economy need demos)
if (process.env.ESEA_DEMO_PROBE) {
  // where is the other Main group? (search + organizer listings)
  for (const q of [`S${SEASON} NA Main`, `S${SEASON} NA Main B`, 'NA Main B', `Season ${SEASON} Main`]) for (const type of ['all', 'ongoing', 'upcoming', 'past']) {
    const r = await api(`/search/championships?name=${encodeURIComponent(q)}&game=cs2&type=${type}&limit=20`).catch(e => ({ error: e.message }));
    console.log('search', JSON.stringify(q), type, r?.error || (r?.items || []).map(x => `${x.name} [${x.competition_id || x.championship_id}] ${x.organizer_id || ''}`).join(' | ').slice(0, 900));
  }
  const anyM = prev.matches?.find(m => m.id)?.id, room0 = anyM && await api(`/matches/${anyM}`).catch(() => null);
  console.log("organizer of our match:", room0?.organizer_id, room0?.competition_id, room0?.competition_name);
  if (room0?.organizer_id) for (const type of ["ongoing", "upcoming", "past"]) {
    const r = await api(`/organizers/${room0.organizer_id}/championships?type=${type}&limit=100`).catch(e => ({ error: e.message }));
    console.log('organizer champs', type, r?.error || (r?.items || []).filter(x => /S\s*59|Season 59/i.test(x.name || '')).map(x => x.name).join(' | ').slice(0, 1500), 'total', (r?.items || []).length);
  }
  const any = prev.matches?.find(m => m.result)?.id;
  const room = any && await api(`/matches/${any}`).catch(e => ({ error: e.message }));
  const url = room?.demo_url?.[0];
  console.log('demo_url:', url || JSON.stringify(room)?.slice(0, 300));
  if (url) {
    const { execSync } = await import('node:child_process');
    const sh = c => { try { return execSync(c, { encoding: 'utf8', timeout: 30000 }).slice(0, 400); } catch (e) { return 'ERR ' + String(e.stderr || e.message).slice(0, 300); } };
    console.log('curl -I:', sh(`curl -sS -I '${url}'`));
    console.log('curl range:', sh(`curl -sS -r 0-99 -o /dev/null -w '%{http_code} %{size_download}' '${url}'`));
    console.log('dns:', sh(`getent hosts demos-us-east.backblaze.faceit-cdn.net || true`));
    for (const ep of ['https://open.faceit.com/download/v2/demos/download-url', 'https://open.faceit.com/download/v1/demos/download-url']) {
      const r = await fetch(ep, { method: 'POST', headers: { Authorization: `Bearer ${KEY}`, 'Content-Type': 'application/json', Accept: 'application/json' }, body: JSON.stringify({ resource_url: url }) }).catch(e => ({ status: e.message, text: async () => '' }));
      console.log('download API', ep, r.status, (await r.text()).slice(0, 300));
    }
    const h = await fetch(url, { method: 'HEAD' }).catch(e => ({ status: e.message + ' ' + (e.cause?.code || '') }));
    console.log('direct HEAD:', h.status, h.headers?.get?.('content-length'));
    const d = await fetch('https://open.faceit.com/download/v2/demos/download-url', { method: 'POST', headers: { Authorization: `Bearer ${KEY}`, 'Content-Type': 'application/json' }, body: JSON.stringify({ resource_url: url }) }).catch(e => ({ status: e.message }));
    console.log('download API:', d.status, (await d.text?.().catch(() => ''))?.slice(0, 300));
  }
  process.exit(0);
}
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
const ours = [], seen = new Set(), allM = [];
for (const c of champs.values()) {
  const info = c.name ? c : { ...c, name: (await api(`/championships/${c.id}`))?.name || null };
  champs.set(c.id, info);
  for (const m of await pages(`/championships/${c.id}/matches?type=all`, 2000)) {
    allM.push(m);
    if (seen.has(m.match_id) || ![m.teams?.faction1?.faction_id, m.teams?.faction2?.faction_id].includes(TEAM_ID)) continue;
    seen.add(m.match_id); ours.push({ ...m, _stage: stageOf(info.name) });
  }
}
// ---- standings: every leaderboard (group) of the season's championships -------------------------
// FACEIT returns a group's table unranked (position 0, team under "player"). Ranked here by points
// (3 a win), win rate, wins, then round differential, rounds won and the team's average FACEIT elo
// (each team's map scores come from its finished matches' box scores, cached in .cache/esea/rounds.json;
// elo is only looked up for teams still level). Teams level on everything share a rank ("T-#12").
// Main A and Main B are seeded on the overall table, so the regular-season championships of every
// group in the division are pooled ("S59 NA Main A/B - Regular Season", found by FACEIT's search).
const divOf = nm => String(nm || '').replace(/\s+[A-Z]\s*-\s*Regular Season.*$/i, '').trim().toLowerCase();
const regular = new Map([...champs.values()].filter(c => /regular/i.test(c.name || '')).map(c => [c.id, c]));
const myDiv = divOf([...regular.values()][0]?.name);
// FACEIT's search is fuzzy, so ask for each sibling's exact name ("... Main B - Regular Season")
const mine = [...regular.values()][0]?.name || '';
const sibNames = 'ABCD'.split('').map(L => mine.replace(/(\s)[A-Z](\s*-\s*Regular Season)/i, `$1${L}$2`)).filter(x => x !== mine);
if (myDiv) for (const q of sibNames) for (const type of ['all', 'ongoing']) {
  const r = await api(`/search/championships?name=${encodeURIComponent(q)}&game=cs2&type=${type}&limit=50`).catch(() => null);
  for (const x of r?.items || []) { const id = x.competition_id || x.championship_id; if (id && /regular/i.test(x.name || '') && divOf(x.name) === myDiv) regular.set(id, { id, name: x.name }); }
}
// fallback: the organizer's championship list (ESEA's id from any match)
if (regular.size < 2 && myDiv) {
  const org = allM.find(m => m.organizer_id)?.organizer_id;
  if (org) for (const type of ['ongoing', 'upcoming', 'past']) {
    for (let off = 0; off < 3000; off += 100) {
      const r = await api(`/organizers/${org}/championships?type=${type}&offset=${off}&limit=100`).catch(() => null);
      for (const x of r?.items || []) { const id = x.championship_id || x.competition_id; if (id && /regular/i.test(x.name || '') && divOf(x.name) === myDiv) regular.set(id, { id, name: x.name }); }
      if ((r?.items || []).length < 100) break;
    }
    if (regular.size >= 2) break;
  }
}
// manual: data/cs.json "eseaGroups": ["<championship id or faceit.com championship link>", ...]
try {
  const cs = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'cs.json'), 'utf8'));
  for (const g of cs.eseaGroups || []) {
    const id = (/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i.exec(g) || [])[1];
    if (id && !regular.has(id)) regular.set(id, { id, name: (await api(`/championships/${id}`).catch(() => null))?.name || `group ${regular.size + 1}` });
  }
} catch {}
console.log('regular-season groups:', [...regular.values()].map(c => c.name).join(' | '));
for (const c of regular.values()) if (!champs.has(c.id)) for (const m of await pages(`/championships/${c.id}/matches?type=all`, 2000)) allM.push(m);
const RCACHE = path.join(ROOT, '.cache', 'esea', 'rounds.json');
const rcache = (() => { try { return JSON.parse(fs.readFileSync(RCACHE, 'utf8')); } catch { return {}; } })();
rcache.m ||= {}; rcache.elo ||= {}; rcache.P ||= {}; delete rcache.L;   // P: match -> team -> per-map player lines (rankings)
const teamRounds = {};   // team id -> [rounds for, rounds against]
for (const m of allM) {
  if (m.status !== 'FINISHED') continue;
  let e = rcache.m[m.match_id];
  if (!e || !rcache.P[m.match_id]) {
    const st = await api(`/matches/${m.match_id}/stats`).catch(() => null); if (!st) continue;
    e = {}; const L = {};
    for (const r of st.rounds || []) {
      const T = r.teams || [];
      for (const t of T) {
        const o = T.find(x => x !== t); const a = n(t.team_stats?.['Final Score']) || 0, b = n(o?.team_stats?.['Final Score']) || 0; const q = (e[t.team_id] ||= [0, 0]); q[0] += a; q[1] += b;
        // compact lines: [k, d, a, adr, k2, k3, k4, k5, entries, entryWins, 1v1W, 1v2W, utilDmg, flashed, flashSucc, utilSucc, MVPs, rf, ra, nickname, id, country]
        (L[t.team_id] ||= []).push((t.players || []).map(p => { const x = p.player_stats || {}; return [n(x.Kills), n(x.Deaths), n(x.Assists), n(x.ADR), n(x['Double Kills']), n(x['Triple Kills']), n(x['Quadro Kills']), n(x['Penta Kills']),
          n(x['Entry Count']), n(x['Entry Wins']), n(x['1v1Wins']), n(x['1v2Wins']), n(x['Utility Damage']), n(x['Enemies Flashed']), n(x['Flash Successes']), n(x['Utility Successes']), n(x.MVPs), a, b].map(v => v || 0).concat([p.nickname, p.player_id]); }));
      }
    }
    rcache.m[m.match_id] = e; rcache.P[m.match_id] = L;
  }
  for (const [tid, [a, b]] of Object.entries(e)) { const q = (teamRounds[tid] ||= [0, 0]); q[0] += a; q[1] += b; }
}
async function teamElo(tid) {
  const c = rcache.elo[tid]; if (c && Date.now() - c.at < 864e5) return c.elo;
  const t = await api(`/teams/${tid}`).catch(() => null), es = [];
  for (const mb of t?.members || []) { const q = await api(`/players/${mb.user_id}`).catch(() => null); if (q?.games?.cs2?.faceit_elo) es.push(q.games.cs2.faceit_elo); }
  es.sort((a, b) => b - a); const elo = es.length ? Math.round(es.slice(0, 5).reduce((a, x) => a + x, 0) / Math.min(5, es.length)) : 0;
  rcache.elo[tid] = { elo, at: Date.now() }; return elo;
}
const standings = {}, lbSeen = [];
{
  const rows = [], groupOf = {};
  for (const c of regular.values()) {
    const letter = (/\s([A-Z])\s*-\s*Regular/i.exec(c.name || '') || [])[1] || '';
    const lbs = await api(`/leaderboards/championships/${c.id}?limit=50`).catch(e => ({ error: e.message }));
    for (const lb of lbs?.items || []) {
      let nRows = 0;
      for (let off = 0; off < 1000; off += 50) {
        const j = await api(`/leaderboards/${lb.leaderboard_id}?offset=${off}&limit=50`).catch(() => null);
        for (const r of j?.items || []) { rows.push(r); groupOf[r.player?.user_id || r.team?.team_id] = letter ? `Main ${letter}` : (lb.leaderboard_name || null); nRows++; }
        if ((j?.items || []).length < 50) break;
      }
      lbSeen.push({ id: c.id, name: c.name || null, board: lb.leaderboard_name, teams: nRows });
    }
  }
  const lb = { leaderboard_name: [...regular.values()].length > 1 ? 'Main (A + B overall)' : 'Main', group: null };
  {
    const tidOf = r => r.player?.user_id || r.team?.team_id;
    const base = r => { const rr = teamRounds[tidOf(r)] || [0, 0]; return [r.points ?? 0, r.win_rate ?? 0, r.won ?? 0, rr[0] - rr[1], rr[0]]; };
    // elo only for teams still level after the first five keys
    const groups = {}; for (const r of rows) (groups[base(r).join()] ||= []).push(r);
    const elo = {}; for (const g of Object.values(groups)) if (g.length > 1) for (const r of g) elo[tidOf(r)] = await teamElo(tidOf(r));
    const key = r => [...base(r), elo[tidOf(r)] ?? 0];
    const cmp = (a, b) => { const x = key(a), y = key(b); for (let i = 0; i < x.length; i++) if (y[i] !== x[i]) return y[i] - x[i]; return 0; };
    const sorted = [...rows].sort(cmp);
    for (const r of sorted) {
      const tid = tidOf(r); if (!tid) continue;
      const above = sorted.filter(o => cmp(o, r) < 0).length, tied = sorted.filter(o => cmp(o, r) === 0).length > 1;
      const rr = teamRounds[tid] || [0, 0];
      standings[tid] = { name: r.player?.nickname || r.team?.name || null, avatar: r.player?.avatar || r.team?.avatar || null, rank: above + 1, tied, of: sorted.length, points: r.points ?? null, w: r.won ?? null, l: r.lost ?? null, played: r.played ?? null,
        rf: rr[0], ra: rr[1], rd: rr[0] - rr[1], elo: elo[tid] ?? null, streak: r.current_streak ?? null, group: groupOf[tid] ?? null, board: lb.leaderboard_name };
    }
  }
}
fs.mkdirSync(path.dirname(RCACHE), { recursive: true }); fs.writeFileSync(RCACHE, JSON.stringify(rcache));

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
    opp: { id: opp.faction_id, name: opp.name || opp.nickname || 'TBD', avatar: opp.avatar || null, rank: standings[opp.faction_id]?.rank ?? null, tied: standings[opp.faction_id]?.tied ?? false, rec: standings[opp.faction_id] ? `${standings[opp.faction_id].w}-${standings[opp.faction_id].l}` : null },
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
        const ln = { name: p.nickname, pid: p.player_id, k: num(s.Kills), d: num(s.Deaths), a: num(s.Assists), adr: num(s.ADR), hs: num(s['Headshots %']),
          kd: num(s['K/D Ratio']), mvp: num(s.MVPs), k2: num(s['Double Kills']), k3: num(s['Triple Kills']), k4: num(s['Quadro Kills']), k5: num(s['Penta Kills']),
          entries: num(s['Entry Count']), entryWins: num(s['Entry Wins']), c11: num(s['1v1Wins']) ?? 0, c12: num(s['1v2Wins']) ?? 0, setups: (num(s['1v1Count']) ?? 0) + (num(s['1v2Count']) ?? 0),
          snip: num(s['Sniper Kills']) ?? 0, flashes: num(s['Flash Count']) ?? 0, fsucc: num(s['Flash Successes']) ?? 0, usucc: num(s['Utility Successes']) ?? 0,
          clutchK: num(s['Clutch Kills']) ?? 0, pistolK: num(s['Pistol Kills']) ?? 0,
          util: num(s['Utility Damage']), flashed: num(s['Enemies Flashed']), rounds, rw: num(team?.team_stats?.['Final Score']) ?? null };
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

// ---- ARK Rating 2: weights fitted on round outcomes ----------------------------------------------
// HLTV Rating 3.0 blends an eco-adjusted 2.1 base (kills, damage, survival, KAST, multi-kills) with Round
// Swing, on hand-set weights (60/40 output vs cost). ARK fits its weights instead, sabermetric-style:
// over every cached map (both teams' full box scores, last 90 days, mostly level-10 NA), each team's
// round share is regressed on its players' per-round stats minus the other team's. Each coefficient
// is then "rounds won per unit" (like wOBA weights from run values) and a player's value is the rounds
// he adds per round over an average player. Inputs: kills, deaths, damage, multi-kill rounds, opening
// duels (Entry +/-), clutches won, assists, enemies flashed, utility damage, flash and utility
// successes. Ridge-regularised, signs constrained (deaths can only hurt, the rest only help).
// Outcome credit (KAST-style): a share of the team's round share over .500 goes to its five, half
// equally and half by round MVPs, so a quiet 9-9 in a 13-3 win reads as a solid game. Weights are
// shrunk toward priors (an opening duel = half a kill on top of the kill; clutches capped, since they
// only happen in won rounds).
// Scale: 1.00 = the average player line in our matches; spread matched to HLTV Rating 1.0's.
const ARK_FEATS = ['kpr', 'dpr', 'adr', 'mks', 'entry', 'clutch', 'apr', 'fpr', 'udr', 'fsr', 'usr'];
const ARK_SIGN = { kpr: 1, dpr: -1, adr: 1, mks: 1, entry: 1, clutch: 1, apr: 1, fpr: 1, udr: 1, fsr: 1, usr: 1 };
// prior weights (rounds per unit, in this fit's scale): the fit is shrunk toward these rather than toward
// zero, so stats the data can't separate keep sensible value. An opening duel is worth half a kill on
// top of the kill itself (HLTV's ~20-point swing); clutches are capped because they only happen in won
// rounds (partly the outcome itself).
const ARK_PRIOR = { kpr: 0.12, dpr: -0.12, adr: 0.05, mks: 0.04, entry: 0.06, clutch: 0.12, apr: 0.02, fpr: 0.005, udr: 0.03, fsr: 0.02, usr: 0.01 };
const ARK_CAP = { clutch: 0.20 };
const ARK_FALLBACK = ARK_PRIOR;
// per-round features of a line (single map or totals); totals of 3+ maps use shrunk entry/clutch rates
function arkFeats(l) {
  const R = l.rounds || 0; if (!R || l.k == null) return null;
  const agg = (l.maps ?? 1) >= 3;
  let ew = l.entryWins ?? 0, el = Math.max(0, (l.entries ?? 0) - ew), c11 = l.c11 ?? 0, c12 = l.c12 ?? 0;
  if (agg && l.entries) { const p = (ew + 10 * PLUS.lgEntry) / (l.entries + 10); ew = l.entries * p; el = l.entries * (1 - p); }
  if (agg && l.setups) { const won = c11 + c12, p = (won + 10 * PLUS.lgClutch) / (l.setups + 10), f = won ? p * l.setups / won : 1; c11 *= f; c12 *= f; }
  return { kpr: l.k / R, dpr: (l.d ?? 0) / R, adr: (l.adr ?? 0) / 100, mks: ((l.k2 ?? 0) + 2 * (l.k3 ?? 0) + 3 * (l.k4 ?? 0) + 4 * (l.k5 ?? 0)) / R,
    entry: (ew - el) / R, clutch: (c11 + 1.5 * c12) / R, apr: (l.a ?? 0) / R, fpr: (l.flashed ?? 0) / R, udr: (l.util ?? 0) / 100 / R,
    fsr: (l.fsucc ?? 0) / R, usr: (l.usucc ?? 0) / R };
}
const lineFromCache = (q, R, rw) => ({ k: q[0], d: q[6], a: q[7], adr: q[8], k2: q[9], k3: q[10], k4: q[11], k5: q[12], entries: q[2], entryWins: q[13],
  c11: q[14], c12: q[15], util: q[16], flashed: q[17], flashes: q[3], snip: q[1], mvp: q[18] ?? 0, fsucc: q[19] ?? 0, usucc: q[20] ?? 0,
  setups: (q[24] ?? 0) + (q[25] ?? 0) || q[5], rounds: R, rw });
// tiny linear algebra for the fit
function solve(A, b) {
  const n = b.length, M = A.map((r, i) => [...r, b[i]]);
  for (let c = 0; c < n; c++) {
    let p = c; for (let r = c + 1; r < n; r++) if (Math.abs(M[r][c]) > Math.abs(M[p][c])) p = r;
    [M[c], M[p]] = [M[p], M[c]]; if (Math.abs(M[c][c]) < 1e-12) return null;
    for (let r = 0; r < n; r++) if (r !== c) { const f = M[r][c] / M[c][c]; for (let k = c; k <= n; k++) M[r][k] -= f * M[c][k]; }
  }
  return M.map((r, i) => r[n] / r[i]);
}
// one observation per team-map: y = round share - .5, X = (sum of its five's features - the other five's)/2
const ARK_MAPS = [];
for (const m of Object.values(mcache)) for (const mp of m.maps || []) {
  if (!mp.R || (mp.T || []).length !== 2 || (mp.S || []).length !== 2) continue;
  const sides = mp.T.map((t, i) => t.map(pid => (mp.L[pid] && mp.L[pid].length >= 26 ? { pid, ...lineFromCache(mp.L[pid], mp.R, mp.S[i]) } : null)));
  if (sides.some(t => t.length !== 5 || t.some(x => !x))) continue;
  ARK_MAPS.push({ R: mp.R, S: mp.S, sides });
}
const ARK_MODEL = (() => {
  const F = ARK_FEATS, pop = ARK_MAPS.flatMap(m => m.sides.flat().map(arkFeats)).filter(Boolean);
  const mu = Object.fromEntries(F.map(k => [k, pop.length ? pop.reduce((a, f) => a + f[k], 0) / pop.length : 0]));
  if (ARK_MAPS.length < 150) return { beta: ARK_FALLBACK, mu, n: ARK_MAPS.length, r2: null, fitted: false };
  const X = [], y = [];
  for (const m of ARK_MAPS) for (let t = 0; t < 2; t++) {
    const sum = side => F.map(k => side.reduce((a, l) => a + arkFeats(l)[k], 0));
    const a = sum(m.sides[t]), b = sum(m.sides[1 - t]);
    X.push(F.map((_, i) => (a[i] - b[i]) / 2)); y.push((m.S[t] - m.S[1 - t]) / (2 * m.R));
  }
  const sd = F.map((_, i) => Math.sqrt(X.reduce((a, r) => a + r[i] ** 2, 0) / X.length) || 1);
  let on = F.map((_, i) => i), beta = null;
  // ridge toward the prior on standardised columns: solve for the deviation from the prior; any weight
  // with the wrong sign is pinned to 0 and the rest refit; caps applied last
  const pinned = new Set();
  for (let it = 0; it < F.length; it++) {
    on = F.map((_, i) => i).filter(i => !pinned.has(i));
    const yp = y.map((v, n) => v - on.reduce((a, i) => a + ARK_PRIOR[F[i]] * X[n][i], 0));   // pinned weights are 0
    const Z = X.map(r => on.map(i => r[i] / sd[i])), lam = 0.15 * X.length;
    const A = on.map((_, a) => on.map((_, b) => Z.reduce((s, r) => s + r[a] * r[b], 0) + (a === b ? lam : 0)));
    const bb = on.map((_, a) => Z.reduce((s, r, n) => s + r[a] * yp[n], 0));
    const w = solve(A, bb); if (!w) break;
    beta = Object.fromEntries(F.map(k => [k, 0])); on.forEach((i, a) => { beta[F[i]] = ARK_PRIOR[F[i]] + w[a] / sd[i]; });
    const bad = on.filter(i => Math.sign(beta[F[i]]) !== ARK_SIGN[F[i]] && beta[F[i]] !== 0);
    if (!bad.length) break;
    bad.forEach(i => pinned.add(i));
  }
  if (beta) for (const [k, c] of Object.entries(ARK_CAP)) beta[k] = Math.min(beta[k], c);
  if (!beta) return { beta: ARK_FALLBACK, mu, n: ARK_MAPS.length, r2: null, fitted: false };
  const pred = X.map(r => F.reduce((a, k, i) => a + beta[k] * r[i], 0)), my = y.reduce((a, v) => a + v, 0) / y.length;
  const r2 = 1 - pred.reduce((a, p, i) => a + (y[i] - p) ** 2, 0) / y.reduce((a, v) => a + (v - my) ** 2, 0);
  return { beta, mu, n: ARK_MAPS.length, r2: Math.round(r2 * 1000) / 1000, fitted: true };
})();
// a line's stat value: rounds added per round over the average player
const arkValue = l => { const f = arkFeats(l); return f ? ARK_FEATS.reduce((a, k) => a + ARK_MODEL.beta[k] * (f[k] - ARK_MODEL.mu[k]), 0) : null; };
// team-result credit for one map: lines of both teams (each with rounds/rw), returns per-line credit
// (rounds per round) for team t's lines
// KAST-style outcome credit: half the team's round share over .500 is shared by its five, half equally
// and half by round MVPs (the losing side takes the mirror share); OUT_W sets its weight
const OUT_W = 0.5;
function mapCredit(team, opp, R, rf, ra) {
  if (!R || !team.length) return team.map(() => 0);
  const e = OUT_W * (rf - ra) / (2 * R), mv = team.reduce((a, l) => a + (l.mvp ?? 0), 0);
  return team.map(l => e * (0.5 / team.length + 0.5 * ((l.mvp ?? 0) + 0.5) / (mv + 0.5 * team.length)));
}
// rolling totals carry [match id, map index] refs into the cache; their team-result credit is summed here
function residOf(q) {
  if (!q || q.residR != null || !q.refs) return q;
  let r = 0;
  for (const [mid, mi] of q.refs) {
    const mp = mcache[mid]?.maps?.[mi]; if (!mp || mp.T?.length !== 2 || mp.S?.length !== 2) continue;
    if (!mp.T.every(t => t.length === 5 && t.every(x => mp.L[x]?.length >= 26))) continue;
    const ti = mp.T.findIndex(t => t.includes(q.pid)); if (ti < 0) continue;
    const mk = t => mp.T[t].map(x => lineFromCache(mp.L[x], mp.R, mp.S[t]));
    r += (mapCredit(mk(ti), mk(1 - ti), mp.R, mp.S[ti], mp.S[1 - ti])[mp.T[ti].indexOf(q.pid)] || 0) * mp.R;
  }
  q.residR = r; return q;
}
// a line's rating: stat value + team-result credit (resid: per round on a single map, residR summed
// over a total's rounds), centred and stretched
function arkTotal(l) {
  const v = arkValue(l); if (v == null) return null;
  return v + (l.residR != null ? l.residR / (l.rounds || 1) : (l.resid ?? 0));
}
let ARK_MU = 0, ARK_K = 10;
function ark(l) {
  const t = arkTotal(l); if (t == null) return null;
  const f = arkFeats(l), parts = Object.fromEntries(ARK_FEATS.map(k => [k, Math.round(ARK_MODEL.beta[k] * (f[k] - ARK_MODEL.mu[k]) * 1000) / 10]));
  parts.team = Math.round((t - arkValue(l)) * 1000) / 10;
  return { rating: Math.round((1 + ARK_K * (t - ARK_MU)) * 100) / 100, swing: Math.round((t - ARK_MU) * 1000) / 10, parts };   // swing / parts: % of a round per round
}
// team-result credit on our box scores, then the scale: centre on the average line in our matches
// (round-weighted, shrunk to the population's 0 by 600 rounds) and stretch to HLTV Rating 1.0's spread
// over every cached player-map
for (const m of matches) for (const x of m.maps) if (x.players?.length && x.opp?.length) {
  const R = (x.rf ?? 0) + (x.ra ?? 0), ct = mapCredit(x.players, x.opp, R, x.rf, x.ra), co = mapCredit(x.opp, x.players, R, x.ra, x.rf);
  x.players.forEach((p, i) => { p.resid = ct[i]; }); x.opp.forEach((p, i) => { p.resid = co[i]; });
}
{
  const ts = [], hs = [];
  for (const mp of ARK_MAPS) for (let t = 0; t < 2; t++) {
    const cr = mapCredit(mp.sides[t], mp.sides[1 - t], mp.R, mp.S[t], mp.S[1 - t]);
    mp.sides[t].forEach((l, i) => { const v = arkValue(l); if (v != null) { ts.push(v + cr[i]); hs.push(rate(l, mp.R).rating); } });
  }
  const sd = v => { const m = v.reduce((a, x) => a + x, 0) / v.length; return Math.sqrt(v.reduce((a, x) => a + (x - m) ** 2, 0) / Math.max(1, v.length - 1)); };
  if (ts.length >= 200) ARK_K = sd(hs) / sd(ts);
  const ours = matches.flatMap(m => m.maps.flatMap(x => [...(x.players || []), ...(x.opp || [])])).map(l => [arkTotal(l), l.rounds || 0]).filter(([t, w]) => t != null && w), W = ours.reduce((a, [, w]) => a + w, 0);
  ARK_MU = ours.reduce((a, [t, w]) => a + t * w, 0) / (W + 600);
  console.log(`ARK 2: ${ARK_MODEL.fitted ? `fitted on ${ARK_MODEL.n} maps, R² ${ARK_MODEL.r2}` : `fallback weights (${ARK_MODEL.n} maps)`}; centre ${ARK_MU.toFixed(4)}, stretch ${ARK_K.toFixed(2)}`);
  console.log('ARK 2 weights (rounds per unit):', JSON.stringify(Object.fromEntries(Object.entries(ARK_MODEL.beta).map(([k, v]) => [k, Math.round(v * 1000) / 1000]))));
}
// ---- S59 rankings: every team in the division ------------------------------------------------
// Standing (points, win rate, wins, round diff, rounds won, elo), round differential, team ARK
// (round-weighted mean of its players' ARK on every finished map, team-result credit included), FACEIT
// elo (top-5 average, cached a day) and talent stars (the five's mean star, from team ARK and elo the
// way player stars are: 3 + .7 z(ARK) + .3 z(elo)). Power rank blends, across teams, z of round
// differential per map (.40), team ARK (.35) and elo (.25).
async function rankings() {
  const ids = Object.keys(standings); if (!ids.length) return null;
  const toLine = (q, R) => ({ k: q[0], d: q[1], a: q[2], adr: q[3], k2: q[4], k3: q[5], k4: q[6], k5: q[7], entries: q[8], entryWins: q[9], c11: q[10], c12: q[11],
    util: q[12], flashed: q[13], fsucc: q[14], usucc: q[15], mvp: q[16], rounds: R, rw: q[17] });
  const tark = {};
  const pl = {};   // player id -> season totals across every finished map in the division
  for (const [mid, L] of Object.entries(rcache.P || {})) {
    const tids = Object.keys(L); if (tids.length !== 2) continue;
    const [A, B] = tids;
    for (let mi = 0; mi < (L[A] || []).length; mi++) {
      const la = L[A][mi], lb = L[B]?.[mi]; if (!la?.length || !lb?.length) continue;
      const R = la[0][17] + la[0][18]; if (!R) continue;
      const ta = la.map(q => toLine(q, R)), tb = lb.map(q => toLine(q, R));
      for (const [tid, mine, theirs, rf, ra] of [[A, ta, tb, la[0][17], la[0][18]], [B, tb, ta, lb[0][17], lb[0][18]]]) {
        const cr = mapCredit(mine, theirs, R, rf, ra);
        const q = (tark[tid] ||= { sum: 0, w: 0, maps: 0 }); q.maps++;
        mine.forEach((l, i) => {
          const v = arkValue(l); if (v == null) return;
          const r = 1 + ARK_K * (v + cr[i] - ARK_MU); q.sum += r * R; q.w += R;
          const src = (tid === A ? la : lb)[i], pid = src[20] || src[19];
          const P = (pl[pid] ||= { id: src[20], name: src[19], tid, maps: 0, rounds: 0, k: 0, d: 0, a: 0, dmg: 0, ew: 0, en: 0, cl: 0, mvp: 0, rsum: 0, games: [] });
          P.tid = tid; P.name = src[19] || P.name; P.maps++; P.rounds += R; P.k += l.k; P.d += l.d; P.a += l.a; P.dmg += l.adr * R; P.ew += l.entryWins; P.en += l.entries;
          P.cl += l.c11 + l.c12; P.mvp += l.mvp; P.rsum += r * R; P.games.push(Math.round(r * 100) / 100);
        });
      }
    }
  }
  const rows = [];
  for (const tid of ids) {
    const st = standings[tid], a = tark[tid];
    const elo = st.elo ?? await teamElo(tid);
    rows.push({ id: tid, name: st.name || null, avatar: st.avatar || null, rank: st.rank, tied: st.tied, group: st.group, w: st.w ?? 0, l: st.l ?? 0, pts: st.points ?? 0,
      rd: st.rd ?? 0, maps: a?.maps || 0, ark: a?.w ? Math.round(a.sum / a.w * 100) / 100 : null, elo: elo || null });
  }
  const zs = k => { const v = rows.map(r => r[k]).filter(x => x != null); const m = v.reduce((s, x) => s + x, 0) / (v.length || 1); const sd = Math.sqrt(v.reduce((s, x) => s + (x - m) ** 2, 0) / Math.max(1, v.length - 1)) || 1; return r => (r[k] == null ? 0 : (r[k] - m) / sd); };
  for (const r of rows) r.rdpm = r.maps ? r.rd / r.maps : 0;
  const zr = zs('rdpm'), za = zs('ark'), ze = zs('elo');
  for (const r of rows) {
    const st = 3 + 0.7 * (r.ark != null ? (r.ark - 1) / 0.12 : 0) + 0.3 * (r.elo ? (r.elo - 2400) / 350 : 0);
    r.talent = { exact: Math.round(Math.max(1, Math.min(5, st)) * 100) / 100, stars: Math.round(Math.max(1, Math.min(5, st)) * 2) / 2 };
    r.power = Math.round((0.40 * zr(r) + 0.35 * za(r) + 0.25 * ze(r)) * 100) / 100;
  }
  [...rows].sort((a, b) => b.power - a.power).forEach((r, i) => { r.powerRank = i + 1; });
  // player rankings: qualified = 80% of the most maps any team has played (rounded up)
  const maxMaps = Math.max(0, ...rows.map(r => r.maps)), need = Math.max(1, Math.ceil(0.8 * maxMaps));
  const teamName = Object.fromEntries(rows.map(r => [r.id, r.name]));
  const players = Object.values(pl).filter(p => p.maps >= need).map(p => ({ id: p.id, name: p.name, team: teamName[p.tid] || null, tid: p.tid,
    maps: p.maps, ark: Math.round(p.rsum / p.rounds * 100) / 100, kd: p.d ? Math.round(p.k / p.d * 100) / 100 : null, adr: Math.round(p.dmg / p.rounds * 10) / 10,
    kpr: Math.round(p.k / p.rounds * 100) / 100, entryPM: p.ew - (p.en - p.ew), clutch: p.cl, mvpPR: Math.round(p.mvp / p.rounds * 100) / 100, games: p.games }))
    .sort((a, b) => b.ark - a.ark);
  players.forEach((p, i) => { p.rank = i + 1; });
  return { teams: rows.sort((a, b) => a.rank - b.rank || b.power - a.power), players, need, maxMaps, pool: Object.keys(pl).length };
}
const RANKINGS = await rankings().catch(e => (console.log('rankings:', e.message), null));
fs.writeFileSync(RCACHE, JSON.stringify(rcache));   // elo lookups made for the rankings

// countries for the box-score flags: one /players lookup per new player, cached in data/esea.json
const countries = { ...(prev.countries || {}) };
for (const m of matches) for (const x of m.maps) for (const side of ['players', 'opp']) for (const p of x[side] || []) {
  if (p.pid && !(p.pid in countries)) countries[p.pid] = (await api(`/players/${p.pid}`).catch(() => null))?.country?.toLowerCase() || null;
}
for (const m of matches) for (const x of m.maps) for (const side of ['players', 'opp']) if (x[side]) {
  x[side] = x[side].map(({ pid, ...p }) => ({ ...p, country: countries[pid] || null, ...ark(p) })).sort((a, b) => (b.rating ?? 0) - (a.rating ?? 0) || (b.k ?? 0) - (a.k ?? 0));
}
// map MVP: the best ARK Rating on 1NT's side of the map (ties: more kills)
for (const m of matches) for (const x of m.maps) {
  const all = [...(x.players || [])].filter(p => p.rating != null).sort((a, b) => b.rating - a.rating || (b.k ?? 0) - (a.k ?? 0));
  if (all[0]) { all[0].mapMvp = true; x.mvp = all[0].name; }
}

// ---- season summary ---------------------------------------------------------------------------
const done = matches.filter(m => m.result);
const maps = done.flatMap(m => m.maps.filter(x => x.rf != null));
const pool = {};
for (const x of maps) { const p = (pool[x.map] ||= { map: x.map, w: 0, l: 0, rf: 0, ra: 0 }); x.win ? p.w++ : p.l++; p.rf += x.rf; p.ra += x.ra; }
const ppl = {};
for (const x of maps) for (const p of x.players) {
  const q = (ppl[p.name] ||= { country: p.country || null, name: p.name, maps: 0, k: 0, d: 0, a: 0, adrSum: 0, hsSum: 0, rounds: 0, k2: 0, k3: 0, k4: 0, k5: 0, mvp: 0, entries: 0, entryWins: 0, clutch: 0, util: 0, flashed: 0, mapMvps: 0, games: [] });
  q.c11 = (q.c11 || 0) + (p.c11 ?? 0); q.c12 = (q.c12 || 0) + (p.c12 ?? 0); q.rw = (q.rw || 0) + (p.rw ?? 0);
  q.residR = (q.residR || 0) + (p.resid ?? 0) * ((x.rf ?? 0) + (x.ra ?? 0)); q.fsucc = (q.fsucc || 0) + (p.fsucc ?? 0); q.usucc = (q.usucc || 0) + (p.usucc ?? 0); q.mvpR = (q.mvpR || 0) + (p.mvp ?? 0); q.setups = (q.setups || 0) + (p.setups ?? 0); q.snip = (q.snip || 0) + (p.snip ?? 0); q.flashes = (q.flashes || 0) + (p.flashes ?? 0);
  q.k2 += p.k2 ?? 0; q.entries += p.entries ?? 0; q.entryWins += p.entryWins ?? 0; q.clutch += p.clutch ?? 0; q.util += p.util ?? 0; q.flashed += p.flashed ?? 0; if (p.mapMvp) q.mapMvps++;
  q.games.push({ map: x.map, rf: x.rf, ra: x.ra, win: x.win, k: p.k, d: p.d, adr: p.adr, rating: p.rating });
  const rounds = (x.rf ?? 0) + (x.ra ?? 0);
  q.maps++; q.k += p.k ?? 0; q.d += p.d ?? 0; q.a += p.a ?? 0; q.adrSum += (p.adr ?? 0) * rounds; q.rounds += rounds;
  q.hsSum += (p.hs ?? 0) * (p.k ?? 0); q.k3 += p.k3 ?? 0; q.k4 += p.k4 ?? 0; q.k5 += p.k5 ?? 0; q.mvp += p.mvp ?? 0;
}
const r2 = x => Math.round(x * 100) / 100, r1 = x => Math.round(x * 10) / 10;
const players = Object.values(ppl).map(q => ({ name: q.name, country: q.country, maps: q.maps, k: q.k, d: q.d, a: q.a, kd: q.d ? r2(q.k / q.d) : null,
  adr: q.rounds ? r1(q.adrSum / q.rounds) : null, hs: q.k ? Math.round(q.hsSum / q.k) : null, kpr: q.rounds ? r2(q.k / q.rounds) : null,
  multi: q.k3 + q.k4 + q.k5, aces: q.k5, mvp: q.mvp, mapMvps: q.mapMvps, hltv: rate(q, q.rounds).rating, impact: rate(q, q.rounds).impact,
  ...ark({ ...q, adr: q.rounds ? q.adrSum / q.rounds : 0 }),
  entryPM: q.entryWins - (q.entries - q.entryWins), entries: q.entries, clutch: q.clutch, utilPR: q.rounds ? r1(q.util / q.rounds) : null, flashPR: q.rounds ? r2(q.flashed / q.rounds) : null,
  best: [...q.games].sort((a, b) => (b.rating ?? 0) - (a.rating ?? 0))[0] || null, games: q.games.map(g => g.rating), ...plus(q) }))
  .sort((a, b) => (b.rating ?? 0) - (a.rating ?? 0));
let streak = null;
for (const m of [...done].reverse()) { if (!streak) streak = { t: m.result, n: 1 }; else if (m.result === streak.t) streak.n++; else break; }
const next = matches.find(m => !m.result && m.status !== 'CANCELLED' && m.at && m.at > Date.now() - 3 * 3600e3) || null;

// ---- match preview: the next opponent, and a map veto ------------------------------------------
// Map strength per team: FACEIT team map win rate (all its league maps), shrunk toward 50% by 8 maps
// of .500, so a 2-0 map doesn't read as a lock. Edge = ours - theirs, in win-rate points; log5 turns
// the pair into a map win probability. Bo1 veto (regular season): six alternating bans, the last map
// is played. 1NT always bans Inferno, then Mirage; every other ban is a minimax: each side bans the
// map that leaves the decider best for it, assuming the other does the same. Shown for both orders.
const POOL_DEFAULT = ['ancient', 'anubis', 'dust2', 'inferno', 'mirage', 'nuke', 'overpass'];
const FIXED_BANS = ['inferno', 'mirage'];
const SHRINK = 8;
const shrunk = (wr, n) => Math.round(((wr ?? 50) * (n || 0) + 50 * SHRINK) / ((n || 0) + SHRINK) * 10) / 10;
const log5 = (a, b) => { a /= 100; b /= 100; const x = a * (1 - b), y = b * (1 - a); return x + y ? x / (x + y) : 0.5; };
function veto(pool, edge, weStart) {
  // returns the ban order and the decider; edge(m) > 0 favours 1NT
  const fixed = [...FIXED_BANS].filter(m => pool.includes(m));
  const order = []; for (let i = 0; i < pool.length - 1; i++) order.push((i % 2 === 0) === weStart ? 'us' : 'them');
  const best = (left, turn, fx) => {   // value = edge of the decider under best play
    if (left.length === 1) return { v: edge(left[0]), seq: [] };
    const who = order[turn];
    if (who === 'us' && fx.length) { const m = fx[0]; const r = best(left.filter(x => x !== m), turn + 1, fx.slice(1)); return { v: r.v, seq: [{ by: 'us', map: m, fixed: true }, ...r.seq] }; }
    let out = null;
    for (const m of left) {
      if (who === 'them' && fx.includes(m)) continue;   // they won't spend a ban on a map 1NT bans anyway
      const r = best(left.filter(x => x !== m), turn + 1, fx);
      if (!out || (who === 'us' ? r.v > out.v : r.v < out.v)) out = { v: r.v, seq: [{ by: who, map: m }, ...r.seq] };
    }
    if (!out) { const m = left[0]; const r = best(left.slice(1), turn + 1, fx); out = { v: r.v, seq: [{ by: who, map: m }, ...r.seq] }; }
    return out;
  };
  const r = best(pool, 0, fixed);
  const decider = pool.find(m => !r.seq.some(x => x.map === m));
  return { weStart, bans: r.seq, decider, edge: Math.round(r.v * 10) / 10 };
}
// ---- round spread: a CS2 map is a race to 13 (MR12), 12-12 goes to MR3 overtime (first to 4 of 6,
// repeated). race(q) gives, for a per-round win chance q, the chance of winning the map, the expected
// round differential and the most likely final score; spread() inverts it from a map win chance.
function race(q) {
  const memo = new Map(), dist = new Map();   // dist: "a-b" final score -> probability
  const add = (k, p) => dist.set(k, (dist.get(k) || 0) + p);
  // overtime: each MR3 period is first to 4 of 6; 3-3 starts another (geometric), scores +3 per tie
  const ot = (p0, base) => {
    let carry = p0;
    for (let n = 0; n < 6 && carry > 1e-9; n++) {
      const pa = []; // final score within a period
      const f = (a, b, pr) => { if (a === 4) return add(`${base + n * 3 + 4}-${base + n * 3 + b}`, pr * carry); if (b === 4) return add(`${base + n * 3 + a}-${base + n * 3 + 4}`, pr * carry); if (a === 3 && b === 3) { pa.push(pr); return; } f(a + 1, b, pr * q); f(a, b + 1, pr * (1 - q)); };
      f(0, 0, 1); carry *= pa.reduce((x, y) => x + y, 0);
    }
  };
  const go = (a, b, pr) => {
    if (pr < 1e-12) return;
    if (a === 13) return add(`13-${b}`, pr); if (b === 13) return add(`${a}-13`, pr);
    if (a === 12 && b === 12) return ot(pr, 12);
    const k = `${a},${b}`; memo.set(k, (memo.get(k) || 0) + pr);
  };
  // walk the regulation grid in order of rounds played, so each cell is complete before it moves on
  memo.set('0,0', 1);
  for (let t = 0; t < 24; t++) for (let a = 0; a <= t; a++) {
    const b = t - a, k = `${a},${b}`, pr = memo.get(k); if (!pr) continue; memo.delete(k);
    go(a + 1, b, pr * q); go(a, b + 1, pr * (1 - q));
  }
  let pWin = 0, ed = 0, best = null;
  for (const [k, p] of dist) { const [a, b] = k.split('-').map(Number); if (a > b) pWin += p; ed += p * (a - b); if (!best || p > best[1]) best = [k, p]; }
  // most likely score on the favoured side
  let fav = null;
  for (const [k, p] of dist) { const [a, b] = k.split('-').map(Number); if ((a > b) === (pWin >= 0.5) && (!fav || p > fav[1])) fav = [k, p]; }
  // the line: the half-point hook where the favourite covers closest to 50% (like a market line)
  const diffs = [...dist].map(([k, p]) => { const [a, b] = k.split('-').map(Number); return [a - b, p]; });
  const side = ed >= 0 ? 1 : -1;
  let line = side * 0.5, cover = 0.5, gap = 1;
  for (let L = 0.5; L <= 13.5; L += 1) {
    const c = diffs.reduce((acc, [d, p]) => acc + (d * side > L ? p : 0), 0);
    if (Math.abs(c - 0.5) < gap) { gap = Math.abs(c - 0.5); line = side * L; cover = c; }
  }
  return { pWin, ed, score: fav?.[0] || best?.[0], line, cover };
}
function spread(pMap) {
  let lo = 0.2, hi = 0.8;
  for (let i = 0; i < 40; i++) { const m = (lo + hi) / 2; race(m).pWin < pMap ? (lo = m) : (hi = m); }
  const r = race((lo + hi) / 2);
  return { q: Math.round((lo + hi) / 2 * 1000) / 1000, rounds: Math.round(r.ed * 10) / 10, line: r.line, cover: Math.round(r.cover * 100), score: r.score };
}
// role matchups: our five against theirs, same role first (AWPer, entry, support, lurker, rifler), the
// rest by talent order; edge = our stars minus theirs (exact)
const ROLE_ORDER = ['AWP', 'entry', 'support', 'lurker', 'rifler'];
function pairUp(ours, theirs) {
  const rl = r => (typeof r.role === 'string' ? r.role : r.role?.role) || 'rifler';
  const left = [...theirs], out = [];
  const take = (pred) => { const i = left.findIndex(pred); return i < 0 ? null : left.splice(i, 1)[0]; };
  const sorted = [...ours].sort((a, b) => ROLE_ORDER.findIndex(k => rl(a).includes(k)) - ROLE_ORDER.findIndex(k => rl(b).includes(k)));
  for (const u of sorted) out.push([u, take(t => ROLE_ORDER.find(k => rl(t).includes(k)) === ROLE_ORDER.find(k => rl(u).includes(k)))]);
  left.sort((a, b) => (b.talent?.exact ?? 0) - (a.talent?.exact ?? 0));
  for (const m of out) if (!m[1]) m[1] = left.shift() || null;
  const side = r => r && { name: r.nickname, country: r.country ?? null, role: rl(r), stars: r.talent?.stars ?? null, exact: r.talent?.exact ?? null, form: r.form ?? null, plus: r.plus || {} };
  // the stat that matters for the role: AWP+ for AWPers, Entry+ for entries, Util+ for supports, Clutch+ for lurkers
  const key = r => (/AWP/.test(r) ? 'awpPlus' : /entry/.test(r) ? 'entryPlus' : /support/.test(r) ? 'utilPlus' : /lurker/.test(r) ? 'clutchPlus' : null);
  return out.map(([u, t]) => { const k = u && key(rl(u)), a = k && u.plus?.[k], b = k && t?.plus?.[k];
    return { us: side(u), them: side(t), edge: u?.talent && t?.talent ? Math.round((u.talent.exact - t.talent.exact) * 100) / 100 : null,
      stat: k ? k.replace('Plus', '+').replace('awp', 'AWP').replace(/^./, c => c.toUpperCase()) : null, statUs: a ?? null, statThem: b ?? null, statEdge: a != null && b != null ? a - b : null }; });
}
async function preview(nx) {
  if (!nx?.opp?.id) return null;
  const oid = nx.opp.id;
  const [ot, os] = await Promise.all([api(`/teams/${oid}`).catch(() => null), api(`/teams/${oid}/stats/cs2`).catch(() => null)]);
  // the map pool from a match room's veto, else the active-duty default
  let pool = null;
  for (const m of allM) { const e = m.voting?.map?.entities; if (e?.length) { pool = e.map(x => String(x.game_map_id || x.class_name || x.name || '').toLowerCase().replace(/^de_/, '')).filter(Boolean); break; } }
  if (!pool?.length) { const room = await api(`/matches/${nx.id}`).catch(() => null); const e = room?.voting?.map?.entities; if (e?.length) pool = e.map(x => String(x.game_map_id || x.class_name || x.name || '').toLowerCase().replace(/^de_/, '')); }
  pool = [...new Set(pool?.length ? pool : POOL_DEFAULT)];
  const segMaps = st => Object.fromEntries((st?.segments || []).filter(x => /map/i.test(x.type || '')).map(x => [String(x.label || '').toLowerCase().replace(/^de_/, ''), { n: n(pick(x.stats, 'Matches')) || 0, wr: n(pick(x.stats, 'Win Rate %')) }]));
  const usM = Object.fromEntries((prof.teamMaps || []).map(x => [x.map, { n: x.matches || 0, wr: x.winRate }])), themM = segMaps(os);
  const maps = pool.map(m => {
    const u = usM[m] || { n: 0, wr: null }, t = themM[m] || { n: 0, wr: null };
    const us = shrunk(u.wr, u.n), them = shrunk(t.wr, t.n);
    return { map: m, us: { n: u.n, wr: u.wr, adj: us }, them: { n: t.n, wr: t.wr, adj: them }, edge: Math.round((us - them) * 10) / 10, p: Math.round(log5(us, them) * 100) };
  }).sort((a, b) => b.edge - a.edge);
  const E = Object.fromEntries(maps.map(x => [x.map, x.edge]));
  const vetoes = [veto(pool, m => E[m] ?? 0, true), veto(pool, m => E[m] ?? 0, false)];
  // their roster: level and elo now, and their S59 box-score lines (ARK Rating on the league baseline)
  const roster = [], oppOfficial = new Set(), oppIds = new Set((ot?.members || []).map(m => m.user_id));
  for (const mb of ot?.members || []) {
    const q = await api(`/players/${mb.user_id}`).catch(() => null);
    const rl = await rollingRole(mb.user_id, 60).catch(() => null);
    for (const x of rl?.ids || []) if (x.official) oppOfficial.add(x.id);
    roster.push({ id: mb.user_id, nickname: q?.nickname || mb.nickname, country: q?.country?.toLowerCase() || null, level: q?.games?.cs2?.skill_level ?? null, elo: q?.games?.cs2?.faceit_elo ?? null, role: rl?.role || null, roleMaps: rl?.maps ?? null, form: formARK(rl?.tot), formMaps: rl?.maps ?? 0, plus: plus(rl?.tot) });
  }
  const theirs = allM.filter(m => [m.teams?.faction1?.faction_id, m.teams?.faction2?.faction_id].includes(oid));
  const res = [], lines = {};
  for (const m of theirs.filter(m => m.status === 'FINISHED')) {
    const f = m.teams.faction1.faction_id === oid ? 'faction1' : 'faction2', o = f === 'faction1' ? 'faction2' : 'faction1';
    res.push({ at: (m.started_at || 0) * 1000, opp: m.teams[o]?.name || '?', result: m.results?.winner === f ? 'W' : 'L', score: [m.results?.score?.[f], m.results?.score?.[o]] });
    const st = await api(`/matches/${m.match_id}/stats`).catch(() => null);
    for (const r of st?.rounds || []) {
      const T = r.teams || [], me = T.find(t => t.team_id === oid), ot2 = T.find(t => t !== me); if (!me) continue;
      const R = (num(me.team_stats?.['Final Score']) || 0) + (num(ot2?.team_stats?.['Final Score']) || 0);
      res[res.length - 1].map = (r.round_stats?.Map || '').replace(/^de_/, ''); res[res.length - 1].rounds = [num(me.team_stats?.['Final Score']), num(ot2?.team_stats?.['Final Score'])];
      // team-result credit on this map, from both teams' box scores
      const sl = (t, rw) => (t?.players || []).map(p => { const x = p.player_stats || {}; return { k: num(x.Kills) || 0, d: num(x.Deaths) || 0, a: num(x.Assists) || 0,
        adr: num(x.ADR) || 0, k2: num(x['Double Kills']) || 0, k3: num(x['Triple Kills']) || 0, k4: num(x['Quadro Kills']) || 0, k5: num(x['Penta Kills']) || 0,
        entries: num(x['Entry Count']) || 0, entryWins: num(x['Entry Wins']) || 0, c11: num(x['1v1Wins']) || 0, c12: num(x['1v2Wins']) || 0,
        util: num(x['Utility Damage']) || 0, flashed: num(x['Enemies Flashed']) || 0, fsucc: num(x['Flash Successes']) || 0, usucc: num(x['Utility Successes']) || 0,
        mvp: num(x.MVPs) || 0, rounds: R, rw }; });
      const rfm = num(me.team_stats?.['Final Score']) || 0, ram = num(ot2?.team_stats?.['Final Score']) || 0;
      const cred = mapCredit(sl(me, rfm), sl(ot2, ram), R, rfm, ram);
      for (const [pi, p] of (me.players || []).entries()) {
        const s2 = p.player_stats || {}, q = (lines[p.nickname] ||= { name: p.nickname, maps: 0, k: 0, d: 0, a: 0, adrSum: 0, rounds: 0, k2: 0, k3: 0, k4: 0, k5: 0, entries: 0, entryWins: 0, c11: 0, c12: 0, util: 0, flashed: 0 });
        q.maps++; q.rounds += R; q.k += num(s2.Kills) || 0; q.d += num(s2.Deaths) || 0; q.a += num(s2.Assists) || 0; q.adrSum += (num(s2.ADR) || 0) * R;
        q.k2 += num(s2['Double Kills']) || 0; q.k3 += num(s2['Triple Kills']) || 0; q.k4 += num(s2['Quadro Kills']) || 0; q.k5 += num(s2['Penta Kills']) || 0;
        q.entries += num(s2['Entry Count']) || 0; q.entryWins += num(s2['Entry Wins']) || 0; q.c11 += num(s2['1v1Wins']) || 0; q.c12 += num(s2['1v2Wins']) || 0;
        q.util += num(s2['Utility Damage']) || 0; q.flashed += num(s2['Enemies Flashed']) || 0; q.rw = (q.rw || 0) + (num(me.team_stats?.['Final Score']) || 0);
        q.fsucc = (q.fsucc || 0) + (num(s2['Flash Successes']) || 0); q.usucc = (q.usucc || 0) + (num(s2['Utility Successes']) || 0); q.residR = (q.residR || 0) + (cred[pi] || 0) * R;
      }
    }
  }
  const watch0 = Object.values(lines).map(q => ({ name: q.name, maps: q.maps, kd: q.d ? Math.round(q.k / q.d * 100) / 100 : null, adr: q.rounds ? Math.round(q.adrSum / q.rounds * 10) / 10 : null,
    ...ark({ ...q, adr: q.rounds ? q.adrSum / q.rounds : 0 }) })).sort((a, b) => (b.rating ?? 0) - (a.rating ?? 0));
  const watch = watch0;
  // their map history: every official map in the cache (league, cups, qualifiers, 90 days) where 3+ of
  // their players shared a side: what they actually play, and how it goes
  const om = {}, apps = {};   // apps: member id -> weighted official maps played (last 30 days count double)
  for (const mid of oppOfficial) for (const mp of mcache[mid]?.maps || []) {
    const i = (mp.T || []).findIndex(t => t.filter(x => oppIds.has(x)).length >= 3); if (i < 0 || !mp.map || (mp.S || []).length < 2) continue;
    const wt = Date.now() - (mcache[mid].at || 0) < 30 * 864e5 ? 2 : 1;
    for (const x of mp.T[i]) if (oppIds.has(x)) apps[x] = (apps[x] || 0) + wt;
    const q = (om[mp.map] ||= { map: mp.map, w: 0, l: 0, rd: 0 }); mp.S[i] > mp.S[1 - i] ? q.w++ : q.l++; q.rd += mp.S[i] - mp.S[1 - i];
  }
  const oppMaps = Object.values(om).sort((a, b) => (b.w + b.l) - (a.w + a.l) || b.w - a.w);

  for (const r of roster) r.talent = grade({ form: r.form, formMaps: r.formMaps, elo: r.elo });
  const avg = a => { const v = a.filter(x => x != null); return v.length ? Math.round(v.reduce((x, y) => x + y, 0) / v.length) : null; };
  const top5 = r => avg([...r].sort((a, b) => (b.elo ?? 0) - (a.elo ?? 0)).slice(0, 5).map(x => x.elo));
  const ourElo = top5(prof.roster || []), theirElo = top5(roster);
  // win probability: half FACEIT elo (top-5 average, elo formula), half the expected decider's log5
  const pElo = ourElo && theirElo ? 1 / (1 + 10 ** (-(ourElo - theirElo) / 400)) : 0.5;
  const dec = maps.find(x => x.map === vetoes[0].decider), pMap = dec ? dec.p / 100 : 0.5;
  // team talent: the mean star rating of each side's likely five (ours: the page's starting five;
  // theirs: whoever played their S59 maps, else their five highest-elo players). One star of the
  // five-man mean ~ 0.48 log-odds, about what 0.10 of team ARK Rating is worth.
  let cs = {}; try { cs = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'cs.json'), 'utf8')); } catch {}
  // a one-match lineup (data/cs.json matchLineups, by match id) beats the regular starting five
  const ml = cs.matchLineups?.[nx.id];
  const five = (ml?.five || (cs.roster?.starters || []).map(x => (Array.isArray(x) ? x[0] : x))).map(x => talentBy[String(x).toLowerCase()]).filter(Boolean);
  // their five: who actually plays their official maps (90 days, last 30 count double; this season's
  // box scores add 3 a map), not the FACEIT roster order; elo breaks ties and fills gaps
  for (const w of watch) { const r = roster.find(x => x.nickname.toLowerCase() === w.name.toLowerCase()); if (r) apps[r.id] = (apps[r.id] || 0) + 3 * (w.maps || 1); }
  for (const r of roster) r.apps = apps[r.id] || 0;
  const theirFive = [...roster].sort((a, b) => b.apps - a.apps || (b.elo ?? 0) - (a.elo ?? 0)).slice(0, 5);
  const tAvg = a => { const v = a.map(r => r.talent?.exact).filter(x => x != null); return v.length ? Math.round(v.reduce((x, y) => x + y, 0) / v.length * 100) / 100 : null; };
  const ourT = tAvg(five), theirT = tAvg(theirFive);
  const lg = p => Math.log(p / (1 - p)), ex = x => 1 / (1 + Math.exp(-x));
  // role matchups: the mean role-stat gap (plus points, 10 = one SD) across the paired roles, at a
  // third of the talent term's weight per SD since it overlaps it
  const mu = pairUp(five, theirFive.length >= 5 ? theirFive : [...new Set([...theirFive, ...roster])].slice(0, 5));
  // bench players in our five get the sub mark (data/cs.json roster subs)
  const subs = new Set((cs.roster?.subs || []).map(x => String(Array.isArray(x) ? x[0] : x).toLowerCase()));
  for (const m of mu) if (m.us) m.us.sub = subs.has(m.us.name.toLowerCase());
  const gaps = mu.map(m => m.statEdge).filter(x => x != null), muZ = gaps.length ? gaps.reduce((a, x) => a + x, 0) / gaps.length / 10 : null;
  const parts = [{ k: 'elo', w: 0.25, p: pElo }, { k: 'map', w: 0.25, p: pMap }];
  if (ourT != null && theirT != null) parts.push({ k: 'rating', w: 0.35, p: ex((ourT - theirT) * 0.48) });
  if (muZ != null) parts.push({ k: 'matchup', w: 0.15, p: ex(muZ * 0.3) });
  const W = parts.reduce((a, x) => a + x.w, 0), pAll = ex(parts.reduce((a, x) => a + x.w * lg(Math.min(0.97, Math.max(0.03, x.p))), 0) / W);
  const sp = spread(pAll);
  // ---- game plan: plain notes from the numbers above (no round-level data here, see the demo probe)
  const plan = [];
  if (oppMaps.length) plan.push(`what they actually play (official, 90 days): ${oppMaps.slice(0, 4).map(m => `${m.map} ${m.w}-${m.l}`).join(', ')}.`);
  const byRole = (rs, rl) => rs.filter(r => (typeof r.role === 'string' ? r.role : r.role?.role || '').includes(rl));
  const nm = r => r.nickname, tg = r => (r.talent ? r.talent.stars + '★' : '—');
  const ourAwp = byRole(five, 'AWP')[0], theirAwp = byRole(theirFive, 'AWP')[0] || byRole(roster, 'AWP')[0];
  if (ourAwp && theirAwp) plan.push(`awp duel: ${nm(ourAwp)} (${tg(ourAwp)}) vs ${nm(theirAwp)} (${tg(theirAwp)}). ${(ourAwp.talent?.exact ?? 0) >= (theirAwp.talent?.exact ?? 0) ? 'we have the better awper, take the long fights' : 'their awper grades higher, don\'t peek him dry: flash or trade'}.`);
  else if (theirAwp) plan.push(`${nm(theirAwp)} is their awper (${tg(theirAwp)}).`);
  const theirStar = [...(theirFive.length ? theirFive : roster)].sort((a, b) => (b.talent?.exact ?? 0) - (a.talent?.exact ?? 0))[0];
  if (theirStar) plan.push(`their best player is ${nm(theirStar)} (${tg(theirStar)}, ${typeof theirStar.role === 'string' ? theirStar.role : 'rifler'}${theirStar.form != null ? `, ${theirStar.form.toFixed(2)} ARK over his last ${theirStar.formMaps} maps` : ''}). find where he plays and stack/util it.`);
  const theirEntry = byRole(theirFive.length ? theirFive : roster, 'entry')[0];
  if (theirEntry) plan.push(`${nm(theirEntry)} takes their opening duels. play for the trade on CT, don't give him a free first kill.`);
  if (ourT != null && theirT != null) plan.push(`talent: our five averages ${ourT.toFixed(2)}★ to their ${theirT.toFixed(2)}★ (${ourT >= theirT ? '+' : ''}${(ourT - theirT).toFixed(2)}).`);
  const worst = [...maps].sort((a, b) => a.them.adj - b.them.adj)[0], best = [...maps].sort((a, b) => b.them.adj - a.them.adj)[0];
  if (worst) plan.push(`their weakest map is ${worst.map} (${worst.them.wr ?? '—'}% over ${worst.them.n}); their best is ${best.map} (${best.them.wr ?? '—'}% over ${best.them.n}), expect them to keep it.`);
  plan.push(`veto: ban ${FIXED_BANS.join(', ')}, then ${vetoes[0].bans.find(b => b.by === 'us' && !b.fixed)?.map}. most likely decider ${vetoes[0].decider} (${maps.find(m => m.map === vetoes[0].decider)?.p}% for us).`);
  if (res.length) { const rd = res.reduce((a, r) => a + ((r.rounds?.[0] ?? 0) - (r.rounds?.[1] ?? 0)), 0); plan.push(`their S59 so far: ${res.filter(r => r.result === 'W').length}-${res.filter(r => r.result === 'L').length}, ${rd >= 0 ? '+' : ''}${rd} rounds.`); }
  const ts = os?.lifetime || {};
  const room = matches.find(m => m.id === nx.id);
  return { id: nx.id, at: nx.at, url: nx.url, bestOf: room?.best_of ?? 1, stage: room?.stage || null, opp: { ...nx.opp, avatar: ot?.avatar || nx.opp.avatar, matches: n(pick(ts, 'Matches')), winRate: n(pick(ts, 'Win Rate %')),
      streak: standings[oid]?.streak ?? null, points: standings[oid]?.points ?? null, roster, elo: theirElo, results: res.sort((a, b) => b.at - a.at), watch },
    us: { elo: ourElo, rank: standings[TEAM_ID]?.rank ?? null, tied: standings[TEAM_ID]?.tied ?? false, rec: standings[TEAM_ID] ? `${standings[TEAM_ID].w}-${standings[TEAM_ID].l}` : null },
    pool, fixedBans: FIXED_BANS, maps, vetoes, p: { elo: Math.round(pElo * 100), map: Math.round(pMap * 100), rating: parts.find(x => x.k === 'rating') ? Math.round(parts.find(x => x.k === 'rating').p * 100) : null, matchup: parts.find(x => x.k === 'matchup') ? Math.round(parts.find(x => x.k === 'matchup').p * 100) : null, win: Math.round(pAll * 100) },
    lineupNote: ml?.note || null, plan, oppMaps, matchups: mu, talent: { us: ourT, them: theirT, five: five.map(r => r.nickname), theirFive: theirFive.map(r => r.nickname) }, spread: sp, shrink: SHRINK };
}

// ---- all-time with 1NT: every player's maps for the team -------------------------------------
// Each player's FACEIT match stats name the team they played for ("Team": "1NT"), so a player's
// maps for 1NT are his stats filtered to that team. Totals are cached in data/esea.json and only
// newer matches are fetched on later runs (the first run walks back up to 1,500 maps per player).
// a player's 1NT events: ESEA seasons as "S58", other cups by name, newest season first
function events(comps) {
  const seasons = new Set(), other = new Set();
  for (const cid of Object.keys(comps || {})) {
    const nm = COMP_NAMES.get(cid); if (!nm) continue;
    const sn = /(?:^|\b)S(?:eason\s*)?(\d{2,3})\b/i.exec(nm);
    if (sn && !/CCT|Liquid|Lockdown|Clash/i.test(nm)) seasons.add(+sn[1]); else if (!/^normal/i.test(nm)) other.add(nm.replace(/\s*[-|]\s*\d+$/, ''));
  }
  return { seasons: [...seasons].sort((a, b) => b - a), other: [...other] };
}
async function allTime() {
  const cache = prev.allTime?.cache || {};
  const tname = team?.name || '1NT';
  let cs = {}; try { cs = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'cs.json'), 'utf8')); } catch {}
  const who = new Map((team?.members || []).map(m => [m.user_id, m.nickname]));
  for (const x of [...(cs.roster?.starters || []), ...(cs.roster?.subs || [])]) {
    const nk = Array.isArray(x) ? x[0] : x;
    if ([...who.values()].some(v => v.toLowerCase() === String(nk).toLowerCase())) continue;
    const q = await api(`/players?nickname=${encodeURIComponent(nk)}`).catch(() => null);
    if (q?.player_id) who.set(q.player_id, q.nickname);
  }
  for (const [pid, nick] of who) {
    const c = (cache[pid] ||= { nick, last: 0, seen: [], t: { maps: 0, w: 0, l: 0, k: 0, d: 0, a: 0, rounds: 0, dmg: 0, hsK: 0, k2: 0, k3: 0, k4: 0, k5: 0, mvp: 0, first: null } });
    c.nick = nick; c.t.comps ||= {};
    let to = null, unit = 1, newest = c.last;
    for (let req = 0; req < (c.last ? 3 : 15); req++) {
      const j = await api(`/players/${pid}/games/cs2/stats?limit=100${to ? `&to=${Math.floor(to / unit)}` : ''}`).catch(() => null);
      const got = (j?.items || []).map(i => i.stats || {});
      if (!got.length && to && unit === 1) { unit = 1000; continue; }
      let done = false;
      for (const st of got) {
        const at = n(st['Match Finished At']) || 0, key = st['Match Id'] + '/' + st['Match Round'];
        if (at <= c.last) { done = true; break; }
        newest = Math.max(newest, at);
        if (String(st.Team || '') !== tname || c.seen.includes(key)) continue;
        const R = n(st.Rounds) || 0; if (!R) continue;
        const t = c.t, k = n(st.Kills) || 0;
        t.maps++; String(st.Result) === '1' ? t.w++ : t.l++; t.k += k; t.d += n(st.Deaths) || 0; t.a += n(st.Assists) || 0; t.rounds += R;
        t.dmg += n(st.Damage) ?? (n(st.ADR) || 0) * R; t.hsK += n(st.Headshots) ?? Math.round((n(st['Headshots %']) || 0) * k / 100);
        t.k2 += n(st['Double Kills']) || 0; t.k3 += n(st['Triple Kills']) || 0; t.k4 += n(st['Quadro Kills']) || 0; t.k5 += n(st['Penta Kills']) || 0; t.mvp += n(st.MVPs) || 0;
        t.first = Math.min(t.first ?? at, at); t.lastAt = Math.max(t.lastAt ?? at, at); c.seen.push(key);
        const cid = st['Competition Id']; if (cid) t.comps[cid] = (t.comps[cid] || 0) + 1;
      }
      const oldest = Math.min(...got.map(x => n(x['Match Finished At']) || Infinity));
      if (done || got.length < 50 || !isFinite(oldest)) break;
      to = oldest - 1;
    }
    c.last = newest; c.seen = c.seen.slice(-60);   // only the newest keys are needed to skip repeats
  }
  const rows = Object.entries(cache).filter(([, c]) => c.t.maps).map(([pid, c]) => { const t = c.t; return {
    name: c.nick, country: countries[pid] || null, maps: t.maps, w: t.w, l: t.l, winRate: Math.round(t.w / t.maps * 100),
    k: t.k, d: t.d, kd: t.d ? Math.round(t.k / t.d * 100) / 100 : null, kpr: Math.round(t.k / t.rounds * 100) / 100,
    adr: Math.round(t.dmg / t.rounds * 10) / 10, hs: t.k ? Math.round(t.hsK / t.k * 100) : null, multi: t.k3 + t.k4 + t.k5, aces: t.k5,
    hltv: rate(t, t.rounds).rating, since: t.first, lastAt: t.lastAt ?? null, events: events(t.comps) }; }).sort((a, b) => b.maps - a.maps);
  return { team: tname, rows, cache };
}
// countries for everyone on the team page (roster, all-time), same cache as the box scores
for (const m of team?.members || []) if (!(m.user_id in countries)) countries[m.user_id] = (await api(`/players/${m.user_id}`).catch(() => null))?.country?.toLowerCase() || null;
const allT = await allTime().catch(e => (console.log('all-time:', e.message), null));

// ---- talent: 1-5 stars (halves) per player, on the same rolling window as form ARK -------------
// 3 stars = an average player in our league's matches; one star = one standard deviation. A weighted
// mean of z-scores: form ARK over the last 100 maps in 90 days (.70 x maps/(maps+20), sd 0.12) and
// current FACEIT elo (.30, (elo-2400)/350). Rounded to the half star; the exact value rides along.
const formARK = tot => (tot?.rounds ? ark({ ...residOf(tot), adr: tot.adrSum / tot.rounds })?.rating ?? null : null);
function grade({ form, formMaps, elo }) {
  const parts = [];
  if (form != null) parts.push([0.70 * formMaps / (formMaps + 20), (form - 1) / 0.12]);
  if (elo != null) parts.push([0.30, (elo - 2400) / 350]);
  const W = parts.reduce((a, [w]) => a + w, 0); if (!W) return null;
  const st = Math.max(1, Math.min(5, 3 + parts.reduce((a, [w, z]) => a + w * z, 0) / W));
  return { exact: Math.round(st * 100) / 100, stars: Math.round(st * 2) / 2 };
}
// a rolling bucket as a stat line for the tables (All / Official / PUGs / Scrims)
const bucketLine = q => (q?.maps ? { maps: q.maps, ark: formARK(q), kd: q.d ? Math.round(q.k / q.d * 100) / 100 : null, kpr: Math.round(q.k / q.rounds * 100) / 100,
  adr: Math.round(q.adrSum / q.rounds * 10) / 10, entryPM: q.entryWins - (q.entries - q.entryWins), clutch: q.c11 + q.c12, multi: q.k3 + q.k4 + q.k5,
  udr: Math.round(q.util / q.rounds * 10) / 10, fpr: Math.round(q.flashed / q.rounds * 100) / 100, ...plus(q) } : null);
const OFFICIAL = new Map();   // match id -> official? (from every 1NT player's rolling list)
for (const r of prof.roster || []) {
  const tot = r.role?.tot, bk = r.role?.buckets, t20 = r.role?.tot20;
  for (const x of r.role?.ids || []) OFFICIAL.set(x.id, x.official);
  if (r.role) { delete r.role.tot; delete r.role.buckets; delete r.role.tot20; delete r.role.ids; }
  // form trend: ARK over the last 20 maps vs the last 100 (hot/cold at +/-0.08)
  const a20 = formARK(t20), a100 = formARK(tot);
  r.trend = a20 != null && a100 != null && t20.maps >= 10 ? { last20: a20, last100: a100, delta: Math.round((a20 - a100) * 100) / 100, flag: a20 - a100 >= 0.08 ? 'hot' : a20 - a100 <= -0.08 ? 'cold' : null } : null;
  r.form = formARK(tot); r.formMaps = tot ? (r.role?.maps ?? 0) : 0;
  r.talent = grade({ form: r.form, formMaps: r.formMaps, elo: r.elo });
  r.rolling = { all: bucketLine(tot), official: bucketLine(bk?.official), pug: bucketLine(bk?.pug), scrim: bucketLine(bk?.scrim) };
  r.plus = plus(tot);
}
const talentBy = Object.fromEntries((prof.roster || []).map(r => [r.nickname.toLowerCase(), r]));

// ---- lineup combos: every cached map (90 days) where 4+ 1NT members shared a side, grouped by the
// members on it (five-man groups and pairs), official and scrim separately; stand-ins aren't named
function combos() {
  const nick = new Map((prof.roster || []).map(r => [r.id, r.nickname]));
  const out = { official: { fives: {}, pairs: {} }, scrim: { fives: {}, pairs: {} } };
  for (const [mid, m] of Object.entries(mcache)) {
    const kind = OFFICIAL.has(mid) ? (OFFICIAL.get(mid) ? 'official' : 'scrim') : null; if (!kind) continue;
    for (const mp of m.maps || []) {
      const T = mp.T || [], S = mp.S || [];
      const i = T.findIndex(t => t.filter(x => MEMBER_IDS.has(x)).length >= 4); if (i < 0 || S.length < 2) continue;
      if (kind === 'scrim' && T[i].filter(x => MEMBER_IDS.has(x)).length < 5) continue;
      const names = T[i].filter(x => MEMBER_IDS.has(x)).map(x => nick.get(x) || '?').sort((a, b) => a.localeCompare(b));
      const win = S[i] > S[1 - i], rd = S[i] - S[1 - i], g = out[kind];
      const add = (o, key) => { const q = (o[key] ||= { key, maps: 0, w: 0, l: 0, rd: 0 }); q.maps++; win ? q.w++ : q.l++; q.rd += rd; };
      add(g.fives, names.join(' · ') + (names.length < 5 ? ' + stand-in' : ''));
      for (let a = 0; a < names.length; a++) for (let b = a + 1; b < names.length; b++) add(g.pairs, names[a] + ' + ' + names[b]);
    }
  }
  const fin = (o, min) => Object.values(o).filter(q => q.maps >= min).map(q => ({ ...q, winRate: Math.round(q.w / q.maps * 100) })).sort((a, b) => b.maps - a.maps || b.winRate - a.winRate);
  return { official: { fives: fin(out.official.fives, 1).slice(0, 8), pairs: fin(out.official.pairs, 4).sort((a, b) => b.winRate - a.winRate || b.maps - a.maps).slice(0, 12) },
    scrim: { fives: fin(out.scrim.fives, 2).slice(0, 8), pairs: fin(out.scrim.pairs, 8).sort((a, b) => b.winRate - a.winRate || b.maps - a.maps).slice(0, 12) } };
}
const combo = (() => { try { return combos(); } catch (e) { console.log('combos:', e.message); return null; } })();

const prev_ = await preview(next).catch(e => (console.log('preview:', e.message), null));
for (const r of allT?.rows || []) if (!r.country) { const id = Object.keys(allT.cache).find(k => allT.cache[k].nick === r.name); if (id && !(id in countries)) countries[id] = (await api(`/players/${id}`).catch(() => null))?.country?.toLowerCase() || null; r.country = countries[id] || null; }

// ---- lineup: FACEIT team membership changes, detected run to run --------------------------------
const members = (team?.members || []).map(m => ({ id: m.user_id, nick: m.nickname }));
const memberLog = [...(prev.memberLog || [])];
if (prev.members) {
  const was = new Set(prev.members.map(m => m.id)), now = new Set(members.map(m => m.id));
  for (const m of members) if (!was.has(m.id)) memberLog.push({ at: Date.now(), nick: m.nick, change: 'joined the FACEIT team' });
  for (const m of prev.members) if (!now.has(m.id)) memberLog.push({ at: Date.now(), nick: m.nick, change: 'left the FACEIT team' });
}

// ---- what the season is worth, and where 1NT stands ------------------------------------------
// FACEIT's NA rules (S58 playoff schedule and move-up article; S59 prize breakdown): each Main group
// (A/B) sends its top 48 to a Bo3 double-elimination playoff; the top 4 move up to Advanced and the top
// 2 (upper- and lower-bracket winners) go to the Season Finals, a 16-team bracket for prize money and
// ECL wildcard invites. Fewer than 4 wins drops a team's group status. Odds: 1NT's remaining regular-
// season matches as coin flips weighted by its record so far (shrunk toward .500 by 7 games of .500),
// against a cut line projected from every team in the group finishing at .500 from here.
const FORMAT = { playoffSpots: 48 * Math.max(1, regular.size), perGroup: 48, groups: regular.size, safeWins: 4, promote: 4, finals: 2, regSeason: REG_SEASON,
  prizes: [['1st', 15000], ['2nd', 7500], ['3rd–4th', 2000], ['5th–8th', 1000], ['9th–12th', 500], ['13th–16th', 250]],
  sources: ['https://support.faceit.com/hc/en-us/articles/29496103330076-ESEA-League-Season-59-Prize-Breakdown',
    'https://support.faceit.com/hc/en-us/articles/19451574692508-How-does-the-move-up-and-move-down-process-work-in-Season-58'] };
function stakes() {
  const me = standings[TEAM_ID]; if (!me) return null;
  const grp = Object.values(standings).filter(x => x.board === me.board);
  const w = me.w ?? 0, played = me.played ?? (w + (me.l ?? 0)), rem = Math.max(0, REG_SEASON - played);
  const proj = grp.map(x => (x.w ?? 0) + Math.max(0, REG_SEASON - (x.played ?? 0)) * 0.5).sort((a, b) => b - a);
  const cut = proj[Math.min(FORMAT.playoffSpots, proj.length) - 1] ?? null;
  const p = (w + 3.5) / (played + 7);
  const C = (n, k) => { let r = 1; for (let i = 1; i <= k; i++) r = r * (n - k + i) / i; return r; };
  const pct = (x, sure, dead) => (sure ? 100 : dead ? 0 : Math.min(99, Math.max(1, Math.round(x * 100))));
  const atLeast = t => { let s = 0; for (let k = Math.max(0, Math.ceil(t - w)); k <= rem; k++) s += C(rem, k) * p ** k * (1 - p) ** (rem - k); return Math.min(1, s); };
  return { group: me.board, teams: grp.length, rank: me.rank, tied: me.tied, w, l: me.l ?? 0, remaining: rem, pace: Math.round((w + rem * p) * 10) / 10,
    // shown as 99% / 1% until it's actually locked in or out
    cutWins: cut == null ? null : Math.ceil(cut), pSafe: pct(atLeast(FORMAT.safeWins), w >= FORMAT.safeWins, w + rem < FORMAT.safeWins),
    pPlayoffs: cut == null ? null : pct(atLeast(Math.ceil(cut)), false, w + rem < Math.ceil(cut)),
    inPlayoffs: me.rank <= FORMAT.playoffSpots, winsToSafe: Math.max(0, FORMAT.safeWins - w) };
}
// ---- season simulation: the rest of the regular season, 10,000 times ---------------------------
// Each team's remaining matches are coin flips at its own win rate shrunk toward .500 (7 games of
// .500, the same as the stakes odds); teams are ranked by wins, ties broken at random. Gives 1NT's
// seed distribution, playoff (top 48) / top 16 / top 4 odds and the wins the 48th seed ends on.
function simulate(N = 10000) {
  const me = standings[TEAM_ID]; if (!me) return null;
  const grp = Object.entries(standings).filter(([, x]) => x.board === me.board).map(([id, x]) => {
    const w = x.w ?? 0, pl = x.played ?? (w + (x.l ?? 0)); return { id, w, rem: Math.max(0, REG_SEASON - pl), p: (w + 3.5) / (pl + 7) }; });
  const seeds = new Array(grp.length + 1).fill(0), cut = {}; let wins = 0;
  const mi = grp.findIndex(t => t.id === TEAM_ID); if (mi < 0) return null;
  for (let s = 0; s < N; s++) {
    const fin = grp.map(t => { let w = t.w; for (let k = 0; k < t.rem; k++) if (Math.random() < t.p) w++; return w + Math.random() * 0.01; });
    const mine = fin[mi]; let above = 0; for (let i = 0; i < fin.length; i++) if (fin[i] > mine) above++;
    seeds[above + 1]++; wins += Math.floor(mine);
    const sorted = [...fin].sort((a, b) => b - a), c = Math.floor(sorted[Math.min(FORMAT.playoffSpots, sorted.length) - 1]); cut[c] = (cut[c] || 0) + 1;
  }
  const P = k => Math.round(seeds.slice(1, k + 1).reduce((a, x) => a + x, 0) / N * 1000) / 10;
  const q = f => { let acc = 0; for (let i = 1; i < seeds.length; i++) { acc += seeds[i]; if (acc >= f * N) return i; } return seeds.length - 1; };
  const buckets = [[1, 4], [5, 8], [9, 16], [17, 32], [33, 48], [49, grp.length]].map(([a, b]) => ({ range: b >= grp.length ? `${a}+` : `${a}-${b}`, p: Math.round(seeds.slice(a, b + 1).reduce((x, y) => x + y, 0) / N * 1000) / 10 }));
  const cutMode = Object.entries(cut).sort((a, b) => b[1] - a[1])[0];
  return { runs: N, pPlayoffs: P(FORMAT.playoffSpots), pTop16: P(16), pTop4: P(4), seedMedian: q(0.5), seedP10: q(0.1), seedP90: q(0.9), expWins: Math.round(wins / N * 10) / 10,
    cutWins: cutMode ? +cutMode[0] : null, cutDist: Object.fromEntries(Object.entries(cut).map(([k, v]) => [k, Math.round(v / N * 1000) / 10])), buckets };
}

// ---- calibration log: each preview's projection, frozen at kickoff, then scored -------------------
const calibration = [...(prev.calibration || [])];
if (prev_ && next && Date.now() < next.at) {
  const snap = { id: next.id, at: next.at, opp: next.opp?.name, win: prev_.p.win, line: prev_.spread?.line ?? null, score: prev_.spread?.score ?? null, decider: prev_.vetoes?.[0]?.decider ?? null };
  const i = calibration.findIndex(c => c.id === next.id); if (i >= 0) calibration[i] = { ...calibration[i], ...snap }; else calibration.push(snap);
}
for (const c of calibration) {
  if (c.result) continue;
  const m = matches.find(x => x.id === c.id && x.result); if (!m) continue;
  const mp = m.maps.find(x => x.rf != null);
  c.result = m.result; c.map = mp?.map ?? null; c.rounds = mp ? [mp.rf, mp.ra] : null;
  const margin = mp ? mp.rf - mp.ra : null; c.margin = margin;
  c.covered = margin == null || c.line == null ? null : margin > c.line;
}
const scored = calibration.filter(c => c.result);
const calib = scored.length ? { n: scored.length, brier: Math.round(scored.reduce((a, c) => a + (c.win / 100 - (c.result === 'W' ? 1 : 0)) ** 2, 0) / scored.length * 1000) / 1000,
  hits: scored.filter(c => (c.win >= 50) === (c.result === 'W')).length, covers: scored.filter(c => c.covered).length } : null;

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
  standing: standings[TEAM_ID] || null, leaderboards: lbSeen, format: FORMAT, stakes: stakes(), sim: simulate(), calibration, calib, combos: combo, plusBase: { players: PLUS.players, awpers: PLUS.awpers, entry: PLUS.lgEntry, clutch: PLUS.lgClutch }, preview: prev_, countries, allTime: allT, members, memberLog,
  statKeys: [...statKeys].sort(), rankings: RANKINGS, arkModel: { fitted: ARK_MODEL.fitted, maps: ARK_MODEL.n, r2: ARK_MODEL.r2, beta: Object.fromEntries(Object.entries(ARK_MODEL.beta).map(([k, v]) => [k, Math.round(v * 1000) / 1000])), centre: Math.round(ARK_MU * 10000) / 10000, stretch: Math.round(ARK_K * 100) / 100 }, matches, pool: Object.values(pool).sort((a, b) => (b.w + b.l) - (a.w + a.l) || b.w - a.w), players, profile: prof,
};
saveCache();
writeOut(out);   // only rewrites when the content changed (the workflow commits on change)
