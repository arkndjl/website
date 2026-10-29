// The college game model's inputs (runModel in scripts/cfb_model.mjs: games, advanced box, lines, drives, situational
// splits) rebuilt from free ESPN data for any season, so the model can be fit on 2015 on and the CFBD quota stops
// mattering. Reads the caches of scripts/cfb_espn_hist.py (scoreboards, closing lines) and scripts/cfb_espn_pbp.py
// (play-by-play and drives), and data/cfb_venues.json (venue and team-home coordinates; ESPN ids).
//   node scripts/cfb_espn_md.mjs [first season] [last season] [out.json.gz]    # default 2015-2026, scripts/.cache/cfb/espn_md.json.gz
//   node scripts/cfb_espn_md.mjs --check <espn_md.json.gz> <cfbd md.json.gz>  # agreement with CFBD -> data/cfb_espn_md.json
// Efficiency is EPA per play on our own expected-points curve (next score in the half by down, distance and yards to
// goal, fit on 2015-20 plays), with CFBD's garbage-time cut (more than 38 points in the 2nd quarter, 28 in the 3rd, 22 in the 4th). Success rate,
// explosiveness (EPA of successful plays), stuff rate and line yards follow CFBD's definitions. Agreement with CFBD's
// own advanced box on the same games (2024-26) is in data/cfb_espn_md.json.
import zlib from 'node:zlib';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { sitByGame, _internals as I } from './cfb_model.mjs';
import { pbpKey } from './cfb_pbp.mjs';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const HIST = path.join(ROOT, 'scripts', '.cache', 'cfb', 'espn_hist'), PBP = path.join(ROOT, 'scripts', '.cache', 'cfb', 'espn_pbp');
const CONF = { 1: 'ACC', 4: 'Big 12', 5: 'Big Ten', 8: 'SEC', 9: 'Pac-12', 12: 'Conference USA', 15: 'Mid-American', 17: 'Mountain West',
  18: 'FBS Independents', 37: 'Sun Belt', 151: 'American Athletic' };
const EP_SEASONS = [2015, 2020];
const GARBAGE = { 2: 38, 3: 28, 4: 22 };
const median = xs => { const s = [...xs].sort((a, b) => a - b), n = s.length; return n ? (n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2) : null; };
const mean = xs => xs.reduce((a, b) => a + b, 0) / Math.max(1, xs.length);
const r4 = x => x == null || !isFinite(x) ? null : Math.round(x * 1e4) / 1e4;

export function loadSeason(S) {
  const f = path.join(HIST, `games${S}.json`);
  return fs.existsSync(f) ? JSON.parse(fs.readFileSync(f, 'utf8')) : [];
}
export function loadGame(id) {
  const f = path.join(PBP, `${id}.json.gz`);
  return fs.existsSync(f) ? JSON.parse(zlib.gunzipSync(fs.readFileSync(f))) : null;
}
// FBS teams: four or more games on ESPN's FBS boards (FCS teams play one or two FBS games; 2020's short Pac-12 and
// MAC seasons had five or six), as scripts/cfb_elo_research.py
export function fbsOf(games) {
  const n = {};
  for (const g of games) if (g.grp === 'fbs') { n[g.h] = (n[g.h] || 0) + 1; n[g.a] = (n[g.a] || 0) + 1; }
  return new Set(Object.keys(n).filter(t => n[t] >= 4));
}
// home closing margin and total: the median over named books (ESPN's consensus row is often stale), the consensus row
// only when it is all there is; in-game feeds leak the result (as cfb_elo_research.py close_of)
export function closeOf(lines) {
  const ok = (lines || []).filter(l => !/Live/.test(l.prov || ''));
  let books = ok.filter(l => l.prov !== 'consensus' && l.spread != null);
  if (!books.length) books = ok.filter(l => l.spread != null && l.details && l.details !== 'EVEN');
  const tots = ok.filter(l => l.ou != null && l.ou > 20);
  // the opening spread (core odds feed, 2023 on) and a moneyline pair from one book
  const opens = ok.filter(l => l.h_open != null && isFinite(+l.h_open)), ml = ok.find(l => l.hml != null && l.aml != null && isFinite(+l.hml) && isFinite(+l.aml));
  return { spread: books.length ? median(books.map(l => +l.spread)) : null, ou: tots.length ? median(tots.map(l => +l.ou)) : null,
    open: opens.length ? median(opens.map(l => +l.h_open)) : null, mlH: ml ? +ml.hml : null, mlA: ml ? +ml.aml : null };
}

// ---- plays ----------------------------------------------------------------------------------------------
const SCRIM = /^(Rush|Pass|Sack)|Rushing Touchdown|Passing Touchdown|Interception|Fumble|^Safety$/;
const isScrim = p => p.dn >= 1 && p.dn <= 4 && p.ds > 0 && p.yl > 0 && p.yl < 100 && SCRIM.test(p.t || '') &&
  !(/Punt|Kickoff|Field Goal/i.test(p.t || '')) && !(/punt|kickoff|field goal/i.test(p.x || '') && !/ run | pass |sacked/i.test(p.x || ''));
const isRush = p => /^Rush|Rushing Touchdown/.test(p.t) || (/Fumble|Safety/.test(p.t) && / run /i.test(p.x || '') && !/pass|sacked/i.test(p.x || ''));
// every play of a game in order, with the offense's score margin before it and the points it put up (offense side +)
function flat(G) {
  const home = G.teams.find(t => t.ha === 'home')?.id, out = [];
  let hs = 0, as = 0;
  for (const dr of G.drives) for (const p of dr.plays) {
    // ESPN's running score can lag a play (a kickoff after a touchdown may carry the score before it); scores never fall
    const nh = Math.max(hs, p.hs ?? hs), na = Math.max(as, p.as ?? as), dh = nh - hs, da = na - as;
    const off = p.st, offHome = off === home;
    out.push({ ...p, drive: dr.n, home, sm: off ? (offHome ? hs - as : as - hs) : null, ptsOff: off ? (offHome ? dh - da : da - dh) : 0, dh, da });
    hs = nh; as = na;
  }
  return out;
}
// the next score in the half from each play on (offense side +): 7 a touchdown, 3 a field goal, 2 a safety; PATs and
// two-point tries ride with their touchdown
function nextScores(F) {
  const half = q => q <= 2 ? 1 : q <= 4 ? 2 : 3;
  const ev = F.map((p, i) => {
    const d = Math.max(p.dh, p.da); if (d <= 0) return null;
    const v = d >= 6 ? 7 : d === 3 ? 3 : d === 2 && /safety/i.test((p.t || '') + ' ' + (p.x || '')) ? 2 : null;
    if (v == null) return null;
    return { i, v, homeScored: p.dh > p.da, h: half(p.q) };
  });
  const out = Array(F.length).fill(0);
  let next = null;
  for (let i = F.length - 1; i >= 0; i--) {
    if (ev[i]) next = ev[i];
    if (next && half(F[i].q) !== next.h) next = null;
    if (next && F[i].st) out[i] = (F[i].st === F[i].home) === next.homeScored ? next.v : -next.v;
  }
  return out;
}
// expected points: per down, OLS on hinges in yards to goal, distance and goal-to-go
const KN = [5, 10, 20, 35, 50, 65, 80, 90];
const epX = (yl, ds) => { const d = Math.min(ds, 30); return [1, yl / 10, ...KN.map(k => Math.max(0, yl - k) / 10), Math.log(d), d / 10, ds >= yl ? 1 : 0]; };
export function fitEP(plays) {
  const W = {};
  for (const dn of [1, 2, 3, 4]) {
    const P = plays.filter(p => p.dn === dn);
    W[dn] = I.ols(P.map(p => epX(p.yl, p.ds)), P.map(p => p.ns), 1, 0);
  }
  return W;
}
export const epOf = (W, dn, ds, yl) => I.dot(W[Math.min(4, Math.max(1, dn))], epX(Math.min(99, Math.max(1, yl)), Math.max(1, ds)));
// one play's EPA (offense side): a touchdown 7 less the start, a defensive score the points against, a change of
// possession the other side's expected points at its spot, else the change in expected points (the next play's start
// when ESPN's end spot is missing)
function epa(W, p, nx) {
  const e0 = epOf(W, p.dn, p.ds, p.yl);
  if (p.ptsOff >= 6) return 7 - e0;
  if (p.ptsOff <= -6) return -7 - e0;
  if (p.ptsOff === -2) return -2 - e0;
  let et = p.et, dn = p.edn, ds = p.eds, yl = p.eyl;
  if (!(dn >= 1 && ds > 0 && yl > 0 && yl < 100) && nx) { et = nx.st; dn = nx.dn; ds = nx.ds; yl = nx.yl; }
  if (!(dn >= 1 && ds > 0 && yl > 0 && yl < 100)) return null;
  return et && et !== p.st ? -epOf(W, 1, 10, yl) - e0 : epOf(W, dn, ds, yl) - e0;
}
const succ = p => {
  if (p.ptsOff >= 6) return 1;
  if (p.to || /Interception|Fumble Recovery \(Opponent\)|Return Touchdown|Safety/.test(p.t)) return 0;
  const need = p.dn === 1 ? 0.5 * p.ds : p.dn === 2 ? 0.7 * p.ds : p.ds;
  return (p.y ?? 0) >= need ? 1 : 0;
};
const lineYds = y => y < 0 ? 1.2 * y : y <= 4 ? y : y <= 10 ? 4 + 0.5 * (y - 4) : 7;

// for QB-level EPA (scripts/cfb_qb_backup.mjs)
export { flat, epa, isScrim, isRush, GARBAGE };
// a week's plays in the slim shape fetch_cfb.mjs keeps from CFBD's plays endpoint (offense, defense, home by name;
// EPA from our own EP curve as ppa), for the weeks CFBD can't serve (spent monthly quota): ids are ESPN event ids,
// nameOf maps an ESPN team id to the name the board resolves. Games not in the play-by-play cache are skipped
export function espnPlays(ids, nameOf, epW) {
  epW ||= JSON.parse(zlib.gunzipSync(fs.readFileSync(HIST_MD))).ep;
  const out = [];
  for (const id of ids) {
    const G = loadGame(id); if (!G?.drives?.length) continue;
    const F = flat(G), ts = G.teams.map(t => t.id);
    F.forEach((p, i) => {
      if (!p.st) return;
      const d = ts.find(t => t !== p.st), nx = F.slice(i + 1, i + 4).find(q => q.dn >= 1 && q.st);
      out.push({ g: +id, o: nameOf(p.st), d: nameOf(d), h: nameOf(p.home), q: p.q, ytg: p.yl, dn: p.dn, ds: p.ds, y: p.y, t: p.t, x: p.x,
        ppa: isScrim(p) ? epa(epW, p, nx) : null, sc: !!p.sc, sm: p.sm });
    });
  }
  return out;
}

// the QB on a play: the passer (pass, sack, interception, passing touchdown) or the runner when he threw in this game.
// Old play text names him in full ("Jake Coker pass complete to ..."), 2025 on by number and initial ("(12:10) Shotgun
// #16 R.Gagliano pass complete ..."); both are matched to the box score by the shared first-initial key (pbpKey)
const bare = x => x.replace(/^\(\d+:\d+\)\s*/, '').replace(/^[A-Za-z -]*?(?:Shotgun|Huddle|Pistol|Formation)\s+/, '').replace(/#\d+\s+/g, '');
const passer = x => /pass from (.+?)(?: \(|,|$)/i.exec(x)?.[1] || /^(.+?) (?:pass|sacked|incomplete|intercepted)/i.exec(x)?.[1] || null;
const runner = x => /^(.+?) (?:run |rush |\d+ Yd Run|scrambles?)/i.exec(x)?.[1] || null;
export function qbPlays(G, box, W) {
  const F = flat(G), out = {};
  const qbs = {};
  for (const [t, P] of Object.entries(box || {})) for (const [aid, s] of Object.entries(P)) if (s.att > 0) (qbs[t] ||= {})[pbpKey(s.n)] = aid;
  F.forEach((p, i) => {
    if (!isScrim(p) || !p.st || !qbs[p.st]) return;
    if (p.sm != null && Math.abs(p.sm) > (GARBAGE[p.q] ?? 99)) return;
    const x = bare(p.x || ''), nm = isRush(p) ? runner(x) : passer(x), aid = nm && qbs[p.st][pbpKey(nm)];
    if (!aid) return;
    const nx = F.slice(i + 1, i + 4).find(q => q.dn >= 1 && q.st), v = epa(W, p, nx);
    if (v == null) return;
    const o = ((out[p.st] ||= {})[aid] ||= [0, 0]); o[0]++; o[1] += v;
  });
  return out;
}

// a season's QB table in the shape of CFBD's ppa/players/season (QB, garbage time out) from the play-by-play and box
// score caches: the live QB charge's input (scripts/cfb_model.mjs qbTable) without CFBD calls. ids: ESPN event ids
export function espnQbPpa(ids, nameOf, epW) {
  epW ||= JSON.parse(zlib.gunzipSync(fs.readFileSync(HIST_MD))).ep;
  const acc = {};
  for (const id of ids) {
    const G = loadGame(id), bp = path.join(HIST, 'box', `${id}.json`);
    if (!G?.drives?.length || !fs.existsSync(bp)) continue;
    const box = JSON.parse(fs.readFileSync(bp, 'utf8'));
    for (const [t, P] of Object.entries(qbPlays(G, box, epW))) for (const [aid, [n, e]] of Object.entries(P)) {
      const a = (acc[aid + '|' + t] ||= { id: aid, team: t, name: box[t]?.[aid]?.n, n: 0, e: 0 }); a.n += n; a.e += e;
    }
  }
  return Object.values(acc).filter(a => a.n > 0).map(a => ({ id: a.id, name: a.name, position: 'QB', team: nameOf(a.team),
    averagePPA: { all: Math.round(a.e / a.n * 1000) / 1000 }, totalPPA: { all: Math.round(a.e * 1000) / 1000 } }));
}

// ---- build ----------------------------------------------------------------------------------------------
export function build(seasons, { venues, epW } = {}) {
  const md = { games: {}, adv: {}, lines: {}, drives: {}, sit: {}, venues: venues?.venues || [], teamsFbs: venues?.teamsFbs || [],
    sp: {}, talent: {}, returning: {}, weather: {}, pfnRet: {}, conf: {} };
  const raw = {};
  for (const S of seasons) {
    const gs = loadSeason(S), fbs = fbsOf(gs);
    raw[S] = { gs, fbs };
  }
  // the expected-points fit (on EP_SEASONS plays unless handed one, or the one saved in data/cfb_espn_md.json)
  if (!epW && !seasons.includes(EP_SEASONS[0])) epW = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'cfb_espn_md.json'), 'utf8')).ep;
  if (!epW) {
    const fitPlays = [];
    for (const S of seasons) if (S >= EP_SEASONS[0] && S <= EP_SEASONS[1]) for (const g of raw[S].gs) {
      if (!g.done || g.grp !== 'fbs') continue;
      const G = loadGame(g.id); if (!G?.drives?.length) continue;
      const F = flat(G), ns = nextScores(F);
      F.forEach((p, i) => { if (isScrim(p) && p.q <= 4) fitPlays.push({ dn: p.dn, ds: p.ds, yl: p.yl, ns: ns[i] }); });
    }
    epW = fitEP(fitPlays);
    md.epN = fitPlays.length;
  }
  md.ep = epW;
  for (const S of seasons) {
    const { gs, fbs } = raw[S];
    // team names: CFBD's school name for today's FBS teams (what the board's other inputs key on: QB EPA, kicking
    // units), ESPN's display name for the rest; ids are shared
    const school = Object.fromEntries((md.teamsFbs || []).map(t => [String(t.id), t.school]));
    const name = {};
    for (const g of gs) { name[g.h] = school[g.h] || g.hn || g.h; name[g.a] = school[g.a] || g.an || g.a; }
    const cls = t => fbs.has(t) ? 'fbs' : 'fcs';
    const games = [], lines = [], adv = [], drives = [], plays = [];
    for (const g of gs) {
      const G = g.done && g.grp === 'fbs' ? loadGame(g.id) : null;
      const C = closeOf(g.lines);
      games.push({ id: +g.id, season: S, week: g.w >= 20 ? g.w - 20 : g.w, seasonType: g.w >= 20 ? 'postseason' : 'regular', startDate: g.date.length === 17 ? g.date.replace('Z', ':00.000Z') : g.date,
        completed: !!g.done && g.hp != null, neutralSite: !!g.n, conferenceGame: !!g.conf, venueId: G?.venue?.id ? +G.venue.id : null,
        homeId: +g.h, homeTeam: name[g.h], homeClassification: cls(g.h), homeConference: CONF[g.hcf] || null, homePoints: g.hp,
        awayId: +g.a, awayTeam: name[g.a], awayClassification: cls(g.a), awayConference: CONF[g.acf] || null, awayPoints: g.ap, notes: g.note || null });
      if (C.spread != null || C.ou != null) lines.push({ id: +g.id, lines: [{ provider: 'consensus', spread: C.spread, overUnder: C.ou, spreadOpen: C.open, homeMoneyline: C.mlH, awayMoneyline: C.mlA }] });
      if (!G?.drives?.length) continue;
      const F = flat(G), off = {};
      F.forEach((p, i) => {
        // situational plays (sitByGame's slim shape: punts and kicks too, for 4th-down decisions and field goals) keep
        // garbage time; sitByGame cuts it itself
        if (p.st && p.dn >= 1 && p.dn <= 4 && !/Penalty|Timeout|End |Kickoff/.test(p.t || '')) plays.push({ g: +g.id, o: name[p.st], q: p.q, ytg: p.yl, dn: p.dn, ds: p.ds, y: p.y, t: p.t, sm: p.sm });
        if (!isScrim(p) || !p.st) return;
        if (p.sm != null && Math.abs(p.sm) > (GARBAGE[p.q] ?? 99)) return;
        const nx = F.slice(i + 1, i + 4).find(q => q.dn >= 1 && q.st);
        const v = epa(epW, p, nx), s = succ(p), o = (off[p.st] ||= { n: 0, e: 0, ne: 0, s: 0, xs: 0, xn: 0, ru: 0, stuff: 0, ly: 0 });
        o.n++; o.s += s;
        if (v != null) { o.e += v; o.ne++; if (s) { o.xs += v; o.xn++; } }
        if (isRush(p)) { o.ru++; if ((p.y ?? 0) <= 0) o.stuff++; o.ly += lineYds(p.y ?? 0); }
      });
      const ids = G.teams.map(t => t.id);
      for (const t of ids) {
        const o = off[t]; if (!o) continue;
        const opp = ids.find(u => u !== t);
        adv.push({ gameId: +g.id, season: S, week: g.w, team: name[t], opponent: name[opp], offense: { plays: o.n, ppa: o.ne ? o.e / o.ne : null,
          successRate: o.s / o.n, explosiveness: o.xn ? o.xs / o.xn : null, stuffRate: o.ru ? o.stuff / o.ru : null, lineYards: o.ru ? o.ly / o.ru : null,
          drives: G.drives.filter(d => d.tm === t).length } });
      }
      // drive spots: ESPN's drive yard line counts from the away team's goal line, so a home offense's is 100 less
      // its yards to goal; a drive's start comes from its first snap where there is one (touchbacks can read 0)
      const home = G.teams.find(t => t.ha === 'home')?.id;
      for (const d of G.drives) {
        const o = d.tm, dd = ids.find(u => u !== o); if (!o || !dd) continue;
        const ytg = v => v == null ? null : o === home ? 100 - v : v;
        const snap = d.plays.find(p => p.st === o && p.dn >= 1 && p.yl > 0 && p.yl < 100 && !/Kickoff|Penalty|Timeout/.test(p.t || ''));
        drives.push({ g: +g.id, n: d.n, o: name[o], d: name[dd], s: snap ? snap.yl : ytg(d.s), e: ytg(d.e), res: d.res, p: d.sq });
      }
    }
    md.games[S] = games; md.lines[S] = lines; md.adv[S] = adv; md.drives[S] = drives;
    md.sit[S] = sitByGame(plays);
    md.conf[S] = Object.fromEntries([...fbs].map(t => [t, CONF[gs.find(g => g.h === t)?.hcf || gs.find(g => g.a === t)?.acf] || null]));
    console.log(S, `${games.length} games, ${adv.length / 2 | 0} with plays, ${lines.length} lines, ${drives.length} drives, ${fbs.size} FBS`);
  }
  return md;
}

// the frozen history (finished seasons), committed so the live model needs no history pulls: the model's inputs with
// the situational splits cut to what it reads (4th-down decisions and the counts; pass rates and kicks are research)
export const HIST_MD = path.join(ROOT, 'scripts', 'data', 'cfb_hist_md.json.gz');
function slimSit(sit) {
  const out = {};
  for (const [k, v] of Object.entries(sit || {})) out[k] = { ed: v.ed, edS: v.edS, td: v.td, tdC: v.tdC, rz: v.rz, rzS: v.rzS, fb: v.fb };
  return out;
}
export function writeHistory(last) {
  const venues = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'cfb_venues.json'), 'utf8'));
  const seasons = []; for (let S = 2015; S <= last; S++) seasons.push(S);
  const md = build(seasons, { venues });
  const out = { seasons, ep: md.ep, games: md.games, adv: md.adv, lines: md.lines, drives: md.drives, sit: Object.fromEntries(Object.entries(md.sit).map(([S, x]) => [S, slimSit(x)])) };
  fs.mkdirSync(path.dirname(HIST_MD), { recursive: true });
  fs.writeFileSync(HIST_MD, zlib.gzipSync(JSON.stringify(out)));
  return out;
}
// the game model's input from ESPN alone: the committed history plus this season from the play-by-play cache
// (scripts/cfb_espn_pbp.py --current). Null when this season's scoreboards aren't cached.
export function liveInput(SEASON) {
  if (!fs.existsSync(HIST_MD) || !loadSeason(SEASON).length) return null;
  const H = JSON.parse(zlib.gunzipSync(fs.readFileSync(HIST_MD)));
  const venues = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'cfb_venues.json'), 'utf8'));
  const live = []; for (let S = H.seasons.at(-1) + 1; S <= SEASON; S++) live.push(S);     // normally this season alone
  const cur = build(live, { venues, epW: H.ep });
  const md = { ...cur, histSeasons: H.seasons };
  for (const k of ['games', 'adv', 'lines', 'drives', 'sit']) md[k] = { ...H[k], ...cur[k] };
  return md;
}

// agreement with CFBD on the same games: per team-game correlation of each stat, and of the season's
// opponent-adjusted net EPA a play (what the model reads), by season
function check(md, cf) {
  const pr = (xs, ys) => { const mx = mean(xs), my = mean(ys); let a = 0, b = 0, c = 0; xs.forEach((x, i) => { a += (x - mx) * (ys[i] - my); b += (x - mx) ** 2; c += (ys[i] - my) ** 2; }); return a / Math.sqrt(b * c); };
  const out = {};
  for (const S of Object.keys(cf.adv)) {
    if (!md.adv[S]) continue;
    const idOf = {}; for (const g of cf.games[S]) { idOf[g.homeTeam] = String(g.homeId); idOf[g.awayTeam] = String(g.awayId); }
    const eid = {}; for (const g of md.games[S]) { eid[g.homeTeam] = String(g.homeId); eid[g.awayTeam] = String(g.awayId); }
    const E = Object.fromEntries(md.adv[S].map(r => [r.gameId + '|' + eid[r.team], r]));
    const pairs = cf.adv[S].map(r => [r, E[r.gameId + '|' + idOf[r.team]]]).filter(([, e]) => e);
    const res = { n: pairs.length, of: cf.adv[S].length };
    for (const k of ['ppa', 'successRate', 'explosiveness', 'plays', 'stuffRate', 'lineYards']) {
      const ok = pairs.filter(([c, e]) => c.offense?.[k] != null && e.offense[k] != null);
      res[k] = { r: r4(pr(ok.map(([c]) => c.offense[k]), ok.map(([, e]) => e.offense[k]))), meanCfbd: r4(mean(ok.map(([c]) => c.offense[k]))), meanEspn: r4(mean(ok.map(([, e]) => e.offense[k]))) };
    }
    // season ratings: opponent-adjusted net EPA a play from each source's own team-games (same games only)
    const fbs = new Set(md.games[S].flatMap(g => [g.homeClassification === 'fbs' ? String(g.homeId) : null, g.awayClassification === 'fbs' ? String(g.awayId) : null]).filter(Boolean));
    const side = {}; for (const g of md.games[S]) side[g.id] = g;
    const net = get => { const obs = [];
      for (const [c, e] of pairs) { const g = side[c.gameId]; if (!g) continue; const t = String(idOf[c.team]), o = String(idOf[c.opponent]); const v = get(c, e); if (v == null) continue;
        obs.push({ o: fbs.has(t) ? t : 'FCS', d: fbs.has(o) ? o : 'FCS', y: v, w: get === null ? 1 : (c.offense.plays || 0) / 65, s: g.neutralSite ? 0 : String(g.homeId) === t ? 1 : -1 }); }
      const A = I.adjust(obs, {}, 3); return [...fbs].filter(t => A.O[t] != null && A.D[t] != null).map(t => [t, A.O[t] - A.D[t]]); };
    const a = net(c => c.offense?.ppa), b = Object.fromEntries(net((c, e) => e.offense.ppa)), x = a.filter(([t]) => b[t] != null);
    res.seasonNetPpa = { teams: x.length, r: r4(pr(x.map(v => v[1]), x.map(([t]) => b[t]))) };
    const sa = net(c => c.offense?.successRate), sb = Object.fromEntries(net((c, e) => e.offense.successRate)), sx = sa.filter(([t]) => sb[t] != null);
    res.seasonNetSr = { teams: sx.length, r: r4(pr(sx.map(v => v[1]), sx.map(([t]) => sb[t]))) };
    out[S] = res;
  }
  return out;
}

const MAIN = process.argv[1] === fileURLToPath(import.meta.url);
if (MAIN && process.argv[2] === '--check') {
  const [, mdPath, cfPath] = process.argv.slice(2);
  const md = JSON.parse(zlib.gunzipSync(fs.readFileSync(mdPath))), cf = JSON.parse(zlib.gunzipSync(fs.readFileSync(cfPath)));
  const res = { asof: new Date().toISOString().slice(0, 10), note: 'ESPN-built advanced box (this script) against CFBD stats/game/advanced (garbage time out), same team-games', epN: md.epN,
    ep: md.ep, seasons: check(md, cf) };
  const f = path.join(ROOT, 'data', 'cfb_espn_md.json');
  fs.writeFileSync(f, JSON.stringify(res, null, 1));
  console.log(JSON.stringify(res.seasons, null, 1));
} else if (MAIN && process.argv[2] === '--hist') {
  const last = +(process.argv[3] || 2025), h = writeHistory(last);
  console.log('history', h.seasons[0], '-', last, 'written to', HIST_MD, (fs.statSync(HIST_MD).size / 1e6).toFixed(1), 'MB');
} else if (MAIN) {
  const [a = 2015, b = 2026, out = path.join(ROOT, 'scripts', '.cache', 'cfb', 'espn_md.json.gz')] = process.argv.slice(2);
  const venues = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'cfb_venues.json'), 'utf8'));
  const seasons = []; for (let S = +a; S <= +b; S++) seasons.push(S);
  const md = build(seasons, { venues });
  fs.writeFileSync(out, zlib.gzipSync(JSON.stringify(md)));
  console.log('EP weights', JSON.stringify(Object.fromEntries(Object.entries(md.ep).map(([k, w]) => [k, w.map(r4)]))), 'on', md.epN, 'plays');
  console.log('written', out);
}
