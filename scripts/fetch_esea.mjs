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
async function boxLines(mid, at) {
  if (mcache[mid]) return mcache[mid];
  const st = await api(`/matches/${mid}/stats`).catch(() => null);
  const maps = (st?.rounds || []).map(r => {
    const R = n(r.round_stats?.Rounds) || (r.teams || []).reduce((a, t) => a + (n(t.team_stats?.['Final Score']) || 0), 0);
    const L = {};
    for (const t of r.teams || []) for (const p of t.players || []) {
      const x = p.player_stats || {};
      L[p.player_id] = [n(x.Kills) || 0, n(x['Sniper Kills']) || 0, n(x['Entry Count']) || 0, n(x['Flash Count']) || 0, n(x['Utility Count']) || 0, (n(x['1v1Count']) || 0) + (n(x['1v2Count']) || 0)];
    }
    return { R, L };
  });
  return (mcache[mid] = { at, maps });
}
async function rollingRole(pid, maxMaps = ROLE_MAPS) {
  const j = await api(`/players/${pid}/games/cs2/stats?limit=100`).catch(() => null);
  const cut = Date.now() - ROLE_DAYS * 864e5, ids = [];
  for (const i of j?.items || []) { const s = i.stats || {}, at = n(s['Match Finished At']) || 0; if (at >= cut && !ids.some(x => x.id === s['Match Id'])) ids.push({ id: s['Match Id'], at }); }
  const t = { maps: 0, R: 0, k: 0, snip: 0, entry: 0, flash: 0, util: 0, clutch: 0 };
  for (const { id, at } of ids) {
    if (t.maps >= maxMaps) break;
    const m = await boxLines(id, at);
    for (const mp of m.maps) { const l = mp.L[pid]; if (!l || !mp.R) continue; t.maps++; t.R += mp.R; t.k += l[0]; t.snip += l[1]; t.entry += l[2]; t.flash += l[3]; t.util += l[4]; t.clutch += l[5]; }
  }
  if (t.R < 200) return null;
  const snip = t.k ? t.snip / t.k : 0, entry = t.entry / t.R, flash = t.flash / t.R, util = t.util / t.R, clutch = t.clutch / t.R;
  const z = { entry: (entry - 0.22) / 0.035, flash: (flash - 0.55) / 0.15, util: (util - 0.5) / 0.12, clutch: (clutch - 0.055) / 0.012 };
  const sc = { entry: z.entry, support: (z.flash + z.util) / 2 - 0.5 * z.entry, lurker: z.clutch - 0.5 * z.entry };
  const top = Object.entries(sc).sort((a, b) => b[1] - a[1])[0];
  const r2 = x => Math.round(x * 100) / 100;
  const out = { sniper: r2(snip), entry: r2(entry), flash: r2(flash), util: r2(util), clutch: Math.round(clutch * 1000) / 1000, maps: t.maps, days: ROLE_DAYS };
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

// ---- standings: every leaderboard (group) of the season's championships -------------------------
// FACEIT returns a group's table unranked (position 0, team under "player"), so rank by points (3 a
// win), then win rate, then wins; teams level on all three share a rank (shown "T-12").
const standings = {}, lbSeen = [];
for (const c of champs.values()) {
  const lbs = await api(`/leaderboards/championships/${c.id}?limit=50`).catch(e => ({ error: e.message }));
  for (const lb of lbs?.items || []) {
    const rows = [];
    for (let off = 0; off < 1000; off += 50) {
      const j = await api(`/leaderboards/${lb.leaderboard_id}?offset=${off}&limit=50`).catch(() => null);
      rows.push(...(j?.items || [])); if ((j?.items || []).length < 50) break;
    }
    const key = r => [r.points ?? 0, r.win_rate ?? 0, r.won ?? 0];
    const sorted = [...rows].sort((a, b) => { const x = key(a), y = key(b); return y[0] - x[0] || y[1] - x[1] || y[2] - x[2]; });
    for (const r of sorted) {
      const tid = r.player?.user_id || r.team?.team_id; if (!tid) continue;
      const k = key(r), above = sorted.filter(o => { const q = key(o); return q[0] > k[0] || (q[0] === k[0] && (q[1] > k[1] || (q[1] === k[1] && q[2] > k[2]))); }).length;
      const tied = sorted.filter(o => key(o).join() === k.join()).length > 1;
      standings[tid] = { rank: above + 1, tied, of: sorted.length, points: r.points ?? null, w: r.won ?? null, l: r.lost ?? null, played: r.played ?? null,
        streak: r.current_streak ?? null, group: lb.group ?? null, board: lb.leaderboard_name || null };
    }
    lbSeen.push({ id: c.id, board: lb.leaderboard_name, teams: sorted.length });
  }
}

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
// Utility is a small sixth part (5%): utility damage and enemies flashed per round, each against
// average and capped at 2.5x, so a support player's nades count without outweighing frags. (ADR
// already holds grenade damage; this credits the flashes and the intent on top.)
const ARK_W = { kill: 0.24, surv: 0.14, dmg: 0.24, multi: 0.10, swing: 0.23, util: 0.05 };
const comp = l => {
  const R = l.rounds || 0; if (!R || l.k == null) return null;
  const k2 = l.k2 ?? 0, k3 = l.k3 ?? 0, k4 = l.k4 ?? 0, k5 = l.k5 ?? 0, k1 = Math.max(0, l.k - 2 * k2 - 3 * k3 - 4 * k4 - 5 * k5);
  const ew = l.entryWins ?? 0, el = Math.max(0, (l.entries ?? 0) - ew);
  return { kpr: l.k / R, dpr: (l.d ?? 0) / R, adr: l.adr ?? 0, mks: (k1 + 4 * k2 + 9 * k3 + 16 * k4 + 25 * k5) / R,
    swing: (0.20 * (ew - el) + 0.50 * (l.c11 ?? 0) + 0.75 * (l.c12 ?? 0) + 0.05 * (l.a ?? 0)) / R,
    udr: (l.util ?? 0) / R, fpr: (l.flashed ?? 0) / R };
};
const PRIOR = { kpr: 0.68, dpr: 0.68, adr: 76, mks: 1.27, swing: 0.03, swingSd: 0.05, udr: 5, fpr: 0.4 }, PW = 30;
const cs = allLines.map(comp).filter(Boolean);
const bl = k => (PRIOR[k] * PW + cs.reduce((a, c) => a + c[k], 0)) / (PW + cs.length);
const BASE = { kpr: bl('kpr'), dpr: bl('dpr'), adr: bl('adr'), mks: bl('mks'), swing: bl('swing'), udr: bl('udr'), fpr: bl('fpr') };
BASE.swingSd = Math.sqrt((PRIOR.swingSd ** 2 * PW + cs.reduce((a, c) => a + (c.swing - BASE.swing) ** 2, 0)) / (PW + cs.length));
function ark(l) {
  const c = comp(l); if (!c) return null;
  const parts = { kill: c.kpr / BASE.kpr, surv: (1 - c.dpr) / (1 - BASE.dpr), dmg: c.adr / BASE.adr, multi: c.mks / BASE.mks,
    swing: 1 + (c.swing - BASE.swing) / BASE.swingSd * 0.25,
    util: (Math.min(2.5, c.udr / BASE.udr) + Math.min(2.5, c.fpr / BASE.fpr)) / 2 };
  const rating = Object.entries(ARK_W).reduce((a, [k, w]) => a + w * parts[k], 0);
  return { rating: Math.round(rating * 100) / 100, swing: Math.round((c.swing - BASE.swing) * 1000) / 10,   // swing: % of a round per round vs average
    parts: Object.fromEntries(Object.entries(parts).map(([k, v]) => [k, Math.round(v * 100) / 100])) };
}
// countries for the box-score flags: one /players lookup per new player, cached in data/esea.json
const countries = { ...(prev.countries || {}) };
for (const m of matches) for (const x of m.maps) for (const side of ['players', 'opp']) for (const p of x[side] || []) {
  if (p.pid && !(p.pid in countries)) countries[p.pid] = (await api(`/players/${p.pid}`).catch(() => null))?.country?.toLowerCase() || null;
}
for (const m of matches) for (const x of m.maps) for (const side of ['players', 'opp']) if (x[side]) {
  x[side] = x[side].map(({ pid, ...p }) => ({ ...p, country: countries[pid] || null, ...ark(p) })).sort((a, b) => (b.rating ?? 0) - (a.rating ?? 0) || (b.k ?? 0) - (a.k ?? 0));
}
// map MVP: the best ARK Rating of the ten players on the map (ties: more kills)
for (const m of matches) for (const x of m.maps) {
  const all = [...(x.players || []), ...(x.opp || [])].filter(p => p.rating != null).sort((a, b) => b.rating - a.rating || (b.k ?? 0) - (a.k ?? 0));
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
  q.c11 = (q.c11 || 0) + (p.c11 ?? 0); q.c12 = (q.c12 || 0) + (p.c12 ?? 0);
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
  best: [...q.games].sort((a, b) => (b.rating ?? 0) - (a.rating ?? 0))[0] || null, games: q.games.map(g => g.rating) }))
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
  return { pWin, ed, score: fav?.[0] || best?.[0] };
}
function spread(pMap) {
  let lo = 0.2, hi = 0.8;
  for (let i = 0; i < 40; i++) { const m = (lo + hi) / 2; race(m).pWin < pMap ? (lo = m) : (hi = m); }
  const r = race((lo + hi) / 2);
  return { q: Math.round((lo + hi) / 2 * 1000) / 1000, rounds: Math.round(r.ed * 10) / 10, line: Math.round(r.ed * 2) / 2, score: r.score };
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
  const roster = [];
  for (const mb of ot?.members || []) {
    const q = await api(`/players/${mb.user_id}`).catch(() => null);
    const rl = await rollingRole(mb.user_id, 60).catch(() => null);
    roster.push({ nickname: q?.nickname || mb.nickname, country: q?.country?.toLowerCase() || null, level: q?.games?.cs2?.skill_level ?? null, elo: q?.games?.cs2?.faceit_elo ?? null, role: rl?.role || null, roleMaps: rl?.maps ?? null });
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
      for (const p of me.players || []) {
        const s2 = p.player_stats || {}, q = (lines[p.nickname] ||= { name: p.nickname, maps: 0, k: 0, d: 0, a: 0, adrSum: 0, rounds: 0, k2: 0, k3: 0, k4: 0, k5: 0, entries: 0, entryWins: 0, c11: 0, c12: 0, util: 0, flashed: 0 });
        q.maps++; q.rounds += R; q.k += num(s2.Kills) || 0; q.d += num(s2.Deaths) || 0; q.a += num(s2.Assists) || 0; q.adrSum += (num(s2.ADR) || 0) * R;
        q.k2 += num(s2['Double Kills']) || 0; q.k3 += num(s2['Triple Kills']) || 0; q.k4 += num(s2['Quadro Kills']) || 0; q.k5 += num(s2['Penta Kills']) || 0;
        q.entries += num(s2['Entry Count']) || 0; q.entryWins += num(s2['Entry Wins']) || 0; q.c11 += num(s2['1v1Wins']) || 0; q.c12 += num(s2['1v2Wins']) || 0;
        q.util += num(s2['Utility Damage']) || 0; q.flashed += num(s2['Enemies Flashed']) || 0;
      }
    }
  }
  const watch = Object.values(lines).map(q => ({ name: q.name, maps: q.maps, kd: q.d ? Math.round(q.k / q.d * 100) / 100 : null, adr: q.rounds ? Math.round(q.adrSum / q.rounds * 10) / 10 : null,
    ...ark({ ...q, adr: q.rounds ? q.adrSum / q.rounds : 0 }) })).sort((a, b) => (b.rating ?? 0) - (a.rating ?? 0));
  const avg = a => { const v = a.filter(x => x != null); return v.length ? Math.round(v.reduce((x, y) => x + y, 0) / v.length) : null; };
  const top5 = r => avg([...r].sort((a, b) => (b.elo ?? 0) - (a.elo ?? 0)).slice(0, 5).map(x => x.elo));
  const ourElo = top5(prof.roster || []), theirElo = top5(roster);
  // win probability: half FACEIT elo (top-5 average, elo formula), half the expected decider's log5
  const pElo = ourElo && theirElo ? 1 / (1 + 10 ** (-(ourElo - theirElo) / 400)) : 0.5;
  const dec = maps.find(x => x.map === vetoes[0].decider), pMap = dec ? dec.p / 100 : 0.5;
  // team quality: average ARK Rating this season, minutes-weighted by maps (ours from the season table,
  // theirs from their box scores), each shrunk toward 1.00 by 3 maps; 0.10 of rating ~ 0.4 log-odds
  const avgR = rows => { const v = rows.filter(r => r.rating != null && r.maps); const m = v.reduce((a, r) => a + r.maps, 0); return m ? { r: (v.reduce((a, r) => a + r.rating * r.maps, 0) + 3 * 5) / (m + 15), maps: m } : null; };
  const ourR = avgR(players), theirR = avgR(watch);
  const lg = p => Math.log(p / (1 - p)), ex = x => 1 / (1 + Math.exp(-x));
  const parts = [{ k: 'elo', w: 0.4, p: pElo }, { k: 'map', w: 0.3, p: pMap }];
  if (ourR && theirR) parts.push({ k: 'rating', w: 0.3, p: ex((ourR.r - theirR.r) * 4) });
  const W = parts.reduce((a, x) => a + x.w, 0), pAll = ex(parts.reduce((a, x) => a + x.w * lg(Math.min(0.97, Math.max(0.03, x.p))), 0) / W);
  const sp = spread(pAll);
  const ts = os?.lifetime || {};
  const room = matches.find(m => m.id === nx.id);
  return { id: nx.id, at: nx.at, url: nx.url, bestOf: room?.best_of ?? 1, stage: room?.stage || null, opp: { ...nx.opp, avatar: ot?.avatar || nx.opp.avatar, matches: n(pick(ts, 'Matches')), winRate: n(pick(ts, 'Win Rate %')),
      streak: standings[oid]?.streak ?? null, points: standings[oid]?.points ?? null, roster, elo: theirElo, results: res.sort((a, b) => b.at - a.at), watch },
    us: { elo: ourElo, rank: standings[TEAM_ID]?.rank ?? null, tied: standings[TEAM_ID]?.tied ?? false, rec: standings[TEAM_ID] ? `${standings[TEAM_ID].w}-${standings[TEAM_ID].l}` : null },
    pool, fixedBans: FIXED_BANS, maps, vetoes, p: { elo: Math.round(pElo * 100), map: Math.round(pMap * 100), rating: parts.find(x => x.k === 'rating') ? Math.round(parts.find(x => x.k === 'rating').p * 100) : null, win: Math.round(pAll * 100) },
    teamRating: { us: ourR && Math.round(ourR.r * 100) / 100, them: theirR && Math.round(theirR.r * 100) / 100 }, spread: sp, shrink: SHRINK };
}
const prev_ = await preview(next).catch(e => (console.log('preview:', e.message), null));

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
const FORMAT = { playoffSpots: 48, safeWins: 4, promote: 4, finals: 2, regSeason: REG_SEASON,
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
  standing: standings[TEAM_ID] || null, leaderboards: lbSeen, format: FORMAT, stakes: stakes(), preview: prev_, countries, allTime: allT, members, memberLog,
  statKeys: [...statKeys].sort(), ratingBase: Object.fromEntries(Object.entries(BASE).map(([k, v]) => [k, Math.round(v * 1000) / 1000])), ratingSample: cs.length, matches, pool: Object.values(pool).sort((a, b) => (b.w + b.l) - (a.w + a.l) || b.w - a.w), players, profile: prof,
};
saveCache();
writeOut(out);   // only rewrites when the content changed (the workflow commits on change)
