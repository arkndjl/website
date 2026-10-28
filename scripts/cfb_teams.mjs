// Team-level models for the College Football ARKBOARD, fed by scripts/fetch_cfb.mjs:
//   Elo        team ratings from games (ESPN scoreboard), starting from a preseason prior
//   Talent     each team's projected starting 22 from our player grades, as expected NFL value
//   TvE        talent vs Elo: Elo above or below what the roster's recruited talent predicts
//   xNIL       each roster's expected NIL (xNIL), summed
//   Games      the coming week: win probability and spread from Elo, top prospects, playstyle, injuries
//   Staff      head coaches credited with team results, coordinators with their side's
//              position groups: production above talent, and development since high school
//   Mock       a 2027 mock draft: projected order (ESPN standings), needs (NFL position rooms: contracts + draft slots), FV + positional value
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { variant } from './cfb_names.mjs';
import { teamSeasonAv, teamWar, starterReplWar, cwar, CWAR_PER_AV } from './cfb_av.mjs';
import { teamAvailability, statusPlay } from './cfb_avail.mjs';
import { compact } from './names.mjs';
import { fvDist, cfbZ } from './fv_dist.mjs';
// the grade a prospect was graded at (fvg; the headline fv is the mean outcome since Oct 21 2026): the mock's draft
// value, its FV-tier rounds and Draft% were set on the grade's scale, so they keep reading it
const grade = p => p.fvg ?? p.fv, gradeX = p => p.fvg ?? p.fvx ?? p.fv;
const meanAt = (p, g) => fvDist('cfb', g, cfbZ({ pos: p.pos === 'DT' ? 'DL' : p.pos, cls: p.cls, cons: p.consRk != null, fv: g }))?.mean ?? g;
const SEASON = 2026;
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const mean = xs => xs.reduce((a, b) => a + b, 0) / Math.max(1, xs.length);
const sd = xs => { const m = mean(xs); return Math.sqrt(mean(xs.map(x => (x - m) ** 2))) || 1; };
const zs = xs => { const m = mean(xs), s = sd(xs); return xs.map(x => (x - m) / s); };
const r1 = x => Math.round(x * 10) / 10, r2 = x => Math.round(x * 100) / 100, r3 = x => Math.round(x * 1000) / 1000;
function phiN(z) {
  const t = 1 / (1 + 0.2316419 * Math.abs(z)), d = 0.3989423 * Math.exp(-z * z / 2);
  const p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))));
  return z > 0 ? 1 - p : p;
}
// inverse normal CDF (Acklam)
function probit(p) {
  p = Math.min(Math.max(p, 1e-4), 1 - 1e-4);
  const a = [-39.6968302866538, 220.946098424521, -275.928510446969, 138.357751867269, -30.6647980661472, 2.50662827745924];
  const b = [-54.4760987982241, 161.585836858041, -155.698979859887, 66.8013118877197, -13.2806815528857];
  const c = [-0.00778489400243029, -0.322396458041136, -2.40075827716184, -2.54973253934373, 4.37466414146497, 2.93816398269878];
  const d = [0.00778469570904146, 0.32246712907004, 2.445134137143, 3.75440866190742];
  if (p < 0.02425) { const q = Math.sqrt(-2 * Math.log(p)); return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1); }
  if (p > 0.97575) { const q = Math.sqrt(-2 * Math.log(1 - p)); return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1); }
  const q = p - 0.5, r = q * q;
  return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1);
}

export const STARTERS = { QB: 1, RB: 1, WR: 3, TE: 1, OL: 5, EDGE: 2, DL: 2, LB: 2, CB: 3, S: 2 };
const OFFENSE = ['QB', 'RB', 'WR', 'TE', 'OL'], DEFENSE = ['EDGE', 'DL', 'LB', 'CB', 'S'];

// expected NFL value per season by FV: mean AV per season active, by tier, measured on the 2010-19
// drafts (nflverse): 80 -> 10.1, 75 -> 8.1, 70 -> 7.2, 65 -> 6.3, 60 -> 5.0, 50 -> 3.7, 40 -> 1.7, 30 -> 0.4; in
// between, linear. The 65-80 points follow the 2026-10-16 ladder (80 = 5+ All-Pro, 75 = 3+, 70 = 2, 65 = All-Pro or
// 3+ Pro Bowls; tier means 9.6, 7.7, 6.9, 6.0 x 1.05, the ratio the 60 and old 80 points carry over their tier means)
const AV_BY_FV = [[20, 0], [30, 0.4], [40, 1.7], [50, 3.7], [60, 5.0], [65, 6.3], [70, 7.2], [75, 8.1], [80, 10.1]];
export function avOf(fv) {
  if (fv == null) return 0;
  for (let i = 1; i < AV_BY_FV.length; i++) {
    const [f0, a0] = AV_BY_FV[i - 1], [f1, a1] = AV_BY_FV[i];
    if (fv <= f1) return a0 + (a1 - a0) * Math.max(0, fv - f0) / (f1 - f0);
  }
  return AV_BY_FV.at(-1)[1];
}

// ---- games and Elo -----------------------------------------------------------------------------
const espnJson = async u => {
  for (let i = 0; i < 4; i++) {
    try { const r = await fetch(u, { headers: { 'user-agent': UA } }); if (r.ok) return await r.json(); } catch {}
    await sleep(1500 * 2 ** i);
  }
  return null;
};
// Novig's main lines at its asks (Noah, Oct 27 2026: "switch everything to Novig"), written by `python3 scripts/novig.py
// --live cfb` before the board runs; a game Novig doesn't list keeps ESPN's DraftKings numbers
let NOVIG = null;
function novigLive() {
  if (NOVIG) return NOVIG;
  try {
    const d = JSON.parse(fs.readFileSync(new URL('./data/novig_live/cfb.json', import.meta.url)));
    NOVIG = Date.now() - Date.parse(d.asof) < 12 * 3600e3 ? d.games : {};
  } catch { NOVIG = {}; }
  return NOVIG;
}
function novigOver(r) {
  const px = !r.done && novigLive()[r.id];
  if (!px) return r;
  const L = px.L, fav = L > 0 ? r.homeAbbr : r.awayAbbr;
  return { ...r, book: 'Novig',
    line: L == null ? r.line : L === 0 ? 'EVEN' : `${fav} -${Math.abs(L)}`, spread: L == null ? r.spread : -L, total: px.T ?? r.total,
    ml: px.mlH != null ? { home: px.mlH > 0 ? `+${px.mlH}` : `${px.mlH}`, away: px.mlA > 0 ? `+${px.mlA}` : `${px.mlA}` } : r.ml,
    spreadOdds: px.oH != null ? { home: px.oH > 0 ? `+${px.oH}` : `${px.oH}`, away: px.oA > 0 ? `+${px.oA}` : `${px.oA}` } : r.spreadOdds };
}
function gameRow(e, wk) { return novigOver(gameRow0(e, wk)); }
function gameRow0(e, wk) {
  const c = e.competitions?.[0];
  const h = c.competitors.find(t => t.homeAway === 'home'), a = c.competitors.find(t => t.homeAway === 'away');
  const odds = c.odds?.[0];
  return { id: e.id, week: wk, date: new Date(e.date).toISOString(), neutral: !!c.neutralSite, done: !!c.status?.type?.completed,
    home: h.team.id, away: a.team.id, homeName: h.team.location, awayName: a.team.location, homeAbbr: h.team.abbreviation || null, awayAbbr: a.team.abbreviation || null, hs: +h.score, as: +a.score,
    homeRank: h.curatedRank?.current < 99 ? h.curatedRank.current : null, awayRank: a.curatedRank?.current < 99 ? a.curatedRank.current : null,
    venue: c.venue?.fullName || null, tv: c.broadcasts?.[0]?.names?.[0] || null, note: c.notes?.[0]?.headline || null,
    line: odds?.details || null, total: odds?.overUnder ?? null, spread: isFinite(odds?.spread) ? +odds.spread : null,   // home side, negative = favored; the close once final
    // prices (the picks tab): moneylines and spread prices, current where ESPN has them
    ml: odds ? { home: odds.homeTeamOdds?.moneyLine ?? odds.moneyline?.home?.close?.odds ?? null, away: odds.awayTeamOdds?.moneyLine ?? odds.moneyline?.away?.close?.odds ?? null } : null,
    spreadOdds: odds ? { home: odds.homeTeamOdds?.spreadOdds ?? odds.pointSpread?.home?.close?.odds ?? null, away: odds.awayTeamOdds?.spreadOdds ?? odds.pointSpread?.away?.close?.odds ?? null } : null };
}
// each team's offensive regulars this regular season (ESPN box scores, scripts/cfb_box.mjs): share of the team's
// passing, rushing and receiving yards, for players with a stat in 2+ games, one of them in the team's last three, and
// at least minShare of the yards (the bowl opt-out term, scripts/cfb_optout.py season())
export function yardShares(games, boxes, minShare = 0.05) {
  const agg = {}, tg = {};
  for (const g of [...games].filter(g => g.done && g.week < 17).sort((a, b) => a.date.localeCompare(b.date))) {
    const b = boxes[g.id]; if (!b) continue;
    for (const [t, P] of Object.entries(b.teams || {})) {
      const k = (tg[t] = (tg[t] || 0) + 1), A = (agg[t] ||= {});
      for (const [aid, r] of Object.entries(P)) { const a = (A[aid] ||= { g: 0, y: 0, last: 0 }); a.g++; a.y += (r.passYds || 0) + (r.rushYds || 0) + (r.recYds || 0); a.last = k; }
    }
  }
  const out = {};
  for (const [t, A] of Object.entries(agg)) {
    const tot = Object.values(A).reduce((s, a) => s + a.y, 0) || 1;
    for (const [aid, a] of Object.entries(A)) if (a.g >= 2 && a.last >= tg[t] - 2 && a.y / tot >= minShare) (out[t] ||= {})[aid] = a.y / tot;
  }
  return out;
}
// every FBS game of a season (regular season and postseason); done = completed
export async function fetchGames(season = SEASON) {
  const games = [];
  for (const [type, weeks] of [[2, 16], [3, 1]]) {
    for (let wk = 1; wk <= weeks; wk++) {
      const d = await espnJson(`https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?dates=${season}&seasontype=${type}&week=${wk}&groups=80&limit=400`);
      for (const e of d?.events || []) if (e.competitions?.[0]) games.push({ ...gameRow(e, type === 3 ? 17 : wk), season });
      await sleep(150);
    }
  }
  const seen = new Set();
  return games.filter(g => !seen.has(g.id) && seen.add(g.id)).sort((x, y) => x.date.localeCompare(y.date));
}

// Availability: the chance a player listed with a status plays (how designations have played out in the
// NFL's reports, which college availability reports now mirror): out 0, doubtful ~.25, questionable ~.6,
// probable ~.9. A season-ending injury takes the player off the depth chart altogether. The game model's injury
// term uses the projections tab's measured rates instead (gamesModel pPlay, cfb_avail.mjs statusPlay); these are
// the fallback without the availability fit.
export const PLAY_PROB = { 'Out (season)': 0, Out: 0, Doubtful: 0.25, Questionable: 0.6, Probable: 0.9, Active: 1 };
export const playProb = st => PLAY_PROB[st] ?? (/season/i.test(st || '') ? 0 : /out/i.test(st || '') ? 0 : /doubt/i.test(st || '') ? 0.25 : /quest/i.test(st || '') ? 0.6 : /prob/i.test(st || '') ? 0.9 : 1);
export const seasonOut = st => /season/i.test(st || '');
const SEASON_ABSORB = 3;   // games a team plays without a season-out player before its ratings carry the loss (see gamesModel)
const QB_CAP = 6;      // most points a QB1 absence moves a margin (see side())
// status from one clause of a news headline (or, failing that, the blurb's first sentence): the most serious
// reading wins; null = not availability news. strict (the blurb): no bare "out", which matchup write-ups use
// ("broke out", "out-gained"): in week 6 it listed Bo Jackson, Jadan Baugh and Caleb Komolafe Out off their
// matchup previews, and all three played
export function statusOf(text, strict = false) {
  const t = (text || '').toLowerCase();
  if (/season-ending|out for (the )?(rest of the |remainder of the )?(season|year)|(rest|remainder) of the (season|year|20\d\d season)|miss the (rest|remainder)|out indefinitely|torn acl|achilles|medical redshirt|career-ending|medically retire|likely out for season/.test(t)) return 'Out (season)';
  if (/doubtful|unlikely to play/.test(t)) return 'Doubtful';
  const out = /\bruled out|\bwill miss|\bto miss|\bmiss(es)? time|\bwon't play|\bwill not play|\bnot expected to play|\bis out\b|\bsidelined|\binactive|\bwill sit|\bnot dress|\bout for a (week|month)/;
  if (out.test(t) || !strict && /\bout\b(?! of)/.test(t)) return 'Out';
  if (/questionable|game-time decision|day-to-day|uncertain to play|status (is )?uncertain|limited in practice/.test(t)) return 'Questionable';
  if (/probable|expected to play|on track to (play|return)|\bcleared|\bavailable|will play|good to go|returns? to (practice|action|the lineup)|back in the lineup|set to return|will return|to start\b|will start|making his return|off injury report|expected to start/.test(t)) return 'Active';
  return null;
}
// a headline's clauses ("X Out, Y to Start", "A, B Questionable for Saturday"): each with its own status; a
// clause with none takes the next one's (a list of names sharing one status)
export function headlineClauses(title) {
  const cl = (title || '').split(/,\s*|\s+and\s+|;\s*/).map(c => ({ text: c, status: statusOf(c) }));
  for (let i = cl.length - 2; i >= 0; i--) if (!cl[i].status) cl[i].status = cl[i + 1].status;
  return cl;
}
// Rotoballer's college football news (~5 days, 15 items a page): headline, time, blurb
const RB_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36';
export async function fetchRotoballer(pages = 12) {
  const items = [], seen = new Set();
  for (let p = 1; p <= pages; p++) {
    const u = p === 1 ? 'https://www.rotoballer.com/player-news?sport=cfb' : `https://www.rotoballer.com/player-news/page/${p}?sport=cfb`;
    let h = null;
    try { const r = await fetch(u, { headers: { 'user-agent': RB_UA } }); if (r.ok) h = await r.text(); } catch {}
    if (!h) break;
    let fresh = 0;
    for (const c of h.split('<div class="rb-news-card').slice(1)) {
      const title = /title="Permanent Link to ([^"]+)"/.exec(c)?.[1]?.replace(/&#0?39;|&#8217;/g, "'").replace(/&amp;/g, '&');
      const ts = +(/data-ts="(\d+)"/.exec(c)?.[1] || 0);
      if (!title || seen.has(title + ts)) continue;
      seen.add(title + ts); fresh++;
      const i = c.indexOf("class='post-time'");
      const body = (i > 0 ? c.slice(i) : '').replace(/<span class='newsByline'.*$/s, '').replace(/<[^>]+>/g, ' ')
        .replace(/&#0?39;|&#8217;/g, "'").replace(/&amp;/g, '&').replace(/\s+/g, ' ').replace(/^[^A-Z]*?ET\s*/, '').trim();
      items.push({ title, date: new Date(ts * 1000).toISOString(), body: body.slice(0, 700) });
    }
    if (!fresh) break;    // past the end: the site repeats its last page
    await sleep(400);
  }
  if (!items.length) throw new Error('rotoballer: no news items (layout changed?)');
  return items;
}

// ESPN's college QBR: schedule-adjusted QBR (opponent defenses accounted for) and points added, by ESPN
// athlete id, for qualifying FBS quarterbacks
export async function fetchQbr(season = SEASON) {
  const d = await espnJson(`https://sports.core.api.espn.com/v2/sports/football/leagues/college-football/seasons/${season}/types/2/groups/80/qbr/0?limit=400`);
  const out = {};
  for (const it of d?.items || []) {
    const id = /athletes\/(\d+)/.exec(it.athlete?.$ref || '')?.[1]; if (!id) continue;
    const st = Object.fromEntries((it.splits?.categories || []).flatMap(c => c.stats).map(x => [x.name, x.value]));
    out[id] = { qbr: st.schedAdjQBR ?? st.qbr, raw: st.qbr, paa: st.qbpaa, plays: st.actionPlays };
  }
  if (Object.keys(out).length < 50) throw new Error(`QBR: only ${Object.keys(out).length} quarterbacks`);
  return out;
}

// ESPN's league-wide college injury report: team -> [{name, status, detail}]
export async function fetchInjuries() {
  const d = await espnJson('https://site.api.espn.com/apis/site/v2/sports/football/college-football/injuries');
  const out = {};
  for (const t of d?.injuries || []) {
    out[t.id] = (t.injuries || []).map(i => ({ name: i.athlete?.displayName, pos: i.athlete?.position?.abbreviation,
      status: i.status || i.type?.description || null, detail: i.shortComment || i.details?.type || null, date: i.date }))
      .filter(i => i.name && i.date >= `${SEASON}-07-01`);     // the feed keeps years-old entries
  }
  return out;
}

// CollegeFootballData (key in CFBD_API_KEY; free tier ~1,000 calls a month, ~20 a board run). A pull younger than
// CFBD_TTL_H hours (default 6) is reused instead of called again: in Oct 2026 the board ran a dozen times a day, by
// hand as well as on schedule, and every call was refused (429) from the 13th to the month's end. CFBD's data moves
// when games finish, so a rerun within hours loses nothing.
const COVER = (() => { try { return JSON.parse(fs.readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'data', 'cover_fit.json'), 'utf8')).sports.cfb || {}; } catch { return {}; } })();
const CFBD_MEMO = path.join(path.dirname(fileURLToPath(import.meta.url)), '.cache', 'cfb', 'cfbd');
export async function cfbd(pathq) {
  const key = process.env.CFBD_API_KEY;
  if (!key) throw new Error('CFBD_API_KEY not set');
  const memo = path.join(CFBD_MEMO, pathq.replace(/[^\w=&.-]+/g, '_') + '.json'), ttl = +(process.env.CFBD_TTL_H ?? 6) * 36e5;
  try { const m = JSON.parse(fs.readFileSync(memo, 'utf8')); if (Date.now() - m.at < ttl) return m.data; } catch {}
  const r = await fetch(`https://api.collegefootballdata.com/${pathq}`, { headers: { Authorization: `Bearer ${key}`, accept: 'application/json' } });
  if (!r.ok) throw new Error(`CFBD ${r.status} ${pathq}`);
  const data = await r.json();
  try { fs.mkdirSync(CFBD_MEMO, { recursive: true }); fs.writeFileSync(memo, JSON.stringify({ at: Date.now(), data })); } catch {}
  return data;
}

// FiveThirtyEight-style Elo: K 20, home field 55, margin multiplier ln(|MOV|+1) * 2.2 / (0.001 * winner
// Elo edge + 2.2) so blowouts by favourites count less. Non-FBS teams start at 1200.
const ELO = { k: 20, home: 55, fbs: 1500, other: 1200 };
export function elo(games, fbsIds, start = {}) {
  const r = {}, rec = {};
  const get = id => (r[id] ??= start[id] ?? (fbsIds.has(id) ? ELO.fbs : ELO.other));
  for (const g of games) {
    if (!g.done) continue;
    const hr = get(g.home) + (g.neutral ? 0 : ELO.home), ar = get(g.away);
    const exp = 1 / (1 + 10 ** ((ar - hr) / 400)), res = g.hs > g.as ? 1 : g.hs < g.as ? 0 : 0.5;
    const mov = Math.abs(g.hs - g.as), edge = res === 1 ? hr - ar : ar - hr;
    const mult = Math.log(mov + 1) * 2.2 / (0.001 * edge + 2.2);
    const shift = ELO.k * mult * (res - exp);
    r[g.home] += shift; r[g.away] -= shift;
    for (const [id, w] of [[g.home, res], [g.away, 1 - res]]) {
      const x = (rec[id] ??= { w: 0, l: 0, pf: 0, pa: 0 });
      if (w === 1) x.w++; else if (w === 0) x.l++;
      x.pf += id === g.home ? g.hs : g.as; x.pa += id === g.home ? g.as : g.hs;
    }
  }
  return { rating: r, record: rec };
}

// Preseason prior, so five games can't overturn a program: last season's final Elo regressed a third
// toward average, blended half-and-half with last season's SP+ (25 Elo per point, also regressed),
// plus this year's recruited talent (On3 talent of the projected starters, 40 Elo per SD).
export function eloPrior(lastGames, fbsIds, spLast, recruitedZ) {
  const last = elo(lastGames, fbsIds).rating, prior = {};
  for (const id of fbsIds) {
    const e = last[id] != null ? (last[id] - 1500) * (2 / 3) : 0;
    const sp = spLast?.[id] != null ? spLast[id] * 25 * (2 / 3) : e;
    prior[id] = Math.round(1500 + 0.5 * e + 0.5 * sp + 40 * (recruitedZ?.[id] ?? 0));
  }
  return prior;
}

// ---- teams: talent, Elo, TvE, xNIL -----------------------------------------------------------------
// rows: every graded player (fetch_cfb.mjs build().all); teams: ESPN team map; games: this season's;
// opts: { lastGames (last season, for the Elo prior), sp ({ESPN id: last season SP+}), adv (CFBD
// advanced season stats by ESPN id) }
export function teamModels(rows, teams, games, fbsIds, opts = {}) {
  const byTeam = {};
  // opts.gone: board keys (name|team|pos) of players out for the season, off the projected starting 22
  for (const p of rows) if (p.tid && fbsIds.has(p.tid) && !opts.gone?.has(`${p.name}|${p.team}|${p.pos}`)) (byTeam[p.tid] ||= []).push(p);
  // recruited talent: On3 talent z of the projected starters (by talent), the input for the Elo prior
  // and for TvE. FV also carries this season's production, so it would partly predict the results.
  const recruited = {};
  for (const [tid, ps] of Object.entries(byTeam)) {
    const st = [];
    for (const [g, n] of Object.entries(STARTERS)) st.push(...ps.filter(p => p.pos === g).sort((a, b) => b.talentZ - a.talentZ).slice(0, n));
    recruited[tid] = mean(st.map(p => p.talentZ));
  }
  const rz = zs(Object.values(recruited)), recZ = Object.fromEntries(Object.keys(recruited).map((k, i) => [k, rz[i]]));
  const prior = opts.lastGames?.length ? eloPrior(opts.lastGames, fbsIds, opts.sp, recZ) : {};
  const { rating, record } = elo(games, fbsIds, prior);
  const out = [];
  for (const [tid, ps] of Object.entries(byTeam)) {
    const starters = [];
    for (const [g, n] of Object.entries(STARTERS)) {
      starters.push(...ps.filter(p => p.pos === g && p.fv != null).sort((a, b) => b.fv - a.fv || (b.fvx ?? b.fv) - (a.fvx ?? a.fv) || b.comp - a.comp).slice(0, n));
    }
    const side = list => r1(list.reduce((a, p) => a + avOf(grade(p)), 0));   // AV on the grade: talent's SRS test (r .68) read it
    // the same starters in college WAR: AV at FV at the college rate, plus each starter's move to the WAR replacement line
    const sideWar = list => Math.round((cwar(side(list)) + list.reduce((a, p) => a + starterReplWar(p.pos), 0)) * 100) / 100;
    const t = teams[tid] || {}, adv = opts.adv?.[tid];
    out.push({
      tid, team: t.name, full: t.full, abbr: t.abbr, logo: ps.find(p => p.logo)?.logo || t.logo, color: t.color ? `#${t.color}` : null,
      conf: mode(ps.map(p => p.conf).filter(Boolean)),
      talent: side(starters), off: side(starters.filter(p => OFFENSE.includes(p.pos))), def: side(starters.filter(p => DEFENSE.includes(p.pos))),
      // season AV (scripts/cfb_av.mjs): the starters by snap share, worth this season to the team, AV a season;
      // war: the starters in college WAR a season (scripts/cfb_av.mjs teamWar). talentWar, offWar, defWar: talent, off
      // and def (AV at FV of the projected starters) as college WAR
      value: ps.some(p => p.savQ != null) ? teamSeasonAv(ps) : null,
      war: ps.some(p => p.savQ != null) ? teamWar(ps) : null, talentWar: sideWar(starters),
      offWar: sideWar(starters.filter(p => OFFENSE.includes(p.pos))), defWar: sideWar(starters.filter(p => DEFENSE.includes(p.pos))),
      n50: ps.filter(p => (p.fv ?? 0) >= 50).length, n60: ps.filter(p => (p.fv ?? 0) >= 60).length,
      top: ps.filter(p => p.fv != null).sort((a, b) => b.fv - a.fv).slice(0, 3).map(p => ({ name: p.name, pos: p.pos, fv: p.fv })),
      recruited: r2(recruited[tid]), prior: prior[tid] ?? null,
      elo: rating[tid] != null ? Math.round(rating[tid]) : prior[tid] ?? null, rec: record[tid] || { w: 0, l: 0, pf: 0, pa: 0 },
      xnil: Math.round(ps.reduce((a, p) => a + (p.xnil || 0), 0)), ynil: Math.round(ps.reduce((a, p) => a + (p.ynil || 0), 0)),
      znil: Math.round(ps.reduce((a, p) => a + (p.znil || 0), 0)),
      znilTop: ps.filter(p => p.znil > 0).sort((a, b) => b.znil - a.znil).slice(0, 3).map(p => ({ name: p.name, pos: p.pos, znil: p.znil })),
      style: adv ? { run: r2(adv.offense?.rushingPlays?.rate ?? NaN), osr: r2(adv.offense?.successRate), oepa: r2(adv.offense?.ppa),
        dsr: r2(adv.defense?.successRate), depa: r2(adv.defense?.ppa), xpl: r2(adv.offense?.explosiveness), havoc: r2(adv.defense?.havoc?.total ?? NaN) } : null,
      hc: t.coach || null,
    });
  }
  rank(out, 'talent', 'talentRk'); rank(out.filter(t => t.value != null), 'value', 'valueRk'); rank(out, 'recruited', 'recruitedRk'); rank(out.filter(t => t.elo != null), 'elo', 'eloRk');
  // TvE: current Elo against the Elo a team's recruited talent predicts (least squares across FBS),
  // in standard deviations of that residual: above zero = winning more than the roster's talent says
  const withElo = out.filter(t => t.elo != null);
  {
    const xs = withElo.map(t => t.recruited), ys = withElo.map(t => t.elo), mx = mean(xs), my = mean(ys);
    const b = xs.reduce((a, x, i) => a + (x - mx) * (ys[i] - my), 0) / xs.reduce((a, x) => a + (x - mx) ** 2, 0);
    const res = withElo.map((t, i) => ys[i] - (my + b * (xs[i] - mx))), s = sd(res);
    withElo.forEach((t, i) => { t.tve = r2(res[i] / s); t.eloExp = Math.round(my + b * (xs[i] - mx)); });
    const ez = zs(ys); withElo.forEach((t, i) => { t.eloZ = r2(ez[i]); });
  }
  rank(out, 'xnil', 'xnilRk'); rank(out, 'znil', 'znilRk');
  out.sort((a, b) => b.talent - a.talent);
  return out;
}

function rank(list, key, as) { [...list].sort((a, b) => b[key] - a[key]).forEach((t, i) => { t[as] = i + 1; }); }
function mode(xs) { const c = {}; let best = null; for (const x of xs) { c[x] = (c[x] || 0) + 1; if (!best || c[x] > c[best]) best = x; } return best; }


// ---- projected top performers ---------------------------------------------------------------------
// Raw production, not FV: each player's per-game line this season (CFBD season stats / team games
// played, FBS and FCS games alike), scaled by the opponent: offensive stats by how many EPA per play the opponent's defense
// allows on that play type (pass or rush), defensive stats by how many plays and how much success
// the opponent's offense runs (tackles) and how much havoc it allows (TFLs, sacks, hurries);
// e^(.12 z) either way, z across FBS. Ranked by production points
// (PPR fantasy scoring on offense: pass yd .04, pass TD 4, INT -2, rush/rec yd .1, TD 6, catch 1; tackles 1, TFL 2, sacks 3, hurries 1, PDs 2, INTs 5 on defense).
// Each line is an expectation over whether he plays (scripts/cfb_avail.mjs): per game played x P(plays), plus the
// work of teammates listed out.
const OFF_PTS = p => 0.04 * p.passYds + 4 * p.passTd - 2 * p.int + 0.1 * p.rushYds + 6 * p.rushTd + 1 * p.rec + 0.1 * p.recYds + 6 * p.recTd;
const DEF_PTS = p => p.tot + 2 * p.tfl + 3 * p.sacks + p.hur + 2 * p.pd + 5 * p.ints + 6 * p.dtd;
// gp: completed games by team id. It must count an FCS team's games against FCS opponents too: counted off the
// FBS schedule alone, an FCS team two games into the FBS slate had its season totals read as two games' worth.
export function playerRates(pstats, resolve, gp) {
  const by = {};
  const K = { passing: { YDS: 'passYds', TD: 'passTd', INT: 'int', ATT: 'att' }, rushing: { YDS: 'rushYds', TD: 'rushTd', CAR: 'car' },
    receiving: { REC: 'rec', YDS: 'recYds', TD: 'recTd' }, defensive: { TOT: 'tot', TFL: 'tfl', SACKS: 'sacks', 'QB HUR': 'hur', PD: 'pd', TD: 'dtd' },
    interceptions: { INT: 'ints' } };
  for (const r of pstats || []) {
    const f = K[r.category]?.[r.statType]; if (!f) continue;
    const tid = resolve(r.team); if (!tid) continue;
    const p = (by[r.playerId] ||= { id: r.playerId, name: r.player, pos: r.position, tid });
    p[f] = (p[f] || 0) + (+r.stat || 0);
  }
  const out = {};
  for (const p of Object.values(by)) {
    const n = gp[p.tid]; if (!n) continue;
    for (const f of ['passYds', 'passTd', 'int', 'att', 'rushYds', 'rushTd', 'car', 'rec', 'recYds', 'recTd', 'tot', 'tfl', 'sacks', 'hur', 'pd', 'dtd', 'ints']) p[f] = (p[f] || 0) / n;
    (out[p.tid] ||= []).push(p);
  }
  return out;
}
// av (scripts/cfb_avail.mjs teamAvailability): each offensive player's chance to play and his line per game played,
// with the work teammates listed out leave behind. The offensive line is per game played x P(plays) x that share;
// a player with no box score this season keeps the old rule (listed Out or Doubtful: no projection).
function projectSide(list, oppAdv, Z, inj, fvOf, k = 1, av = {}) {
  const mp = k * Math.exp(0.12 * Z.dPass(oppAdv)), mr = k * Math.exp(0.12 * Z.dRush(oppAdv));
  const mt = Math.exp(0.12 * Z.oPlays(oppAdv)), mh = Math.exp(0.12 * Z.oHavoc(oppAdv));   // tackle volume; TFL/sack chances
  const r1 = x => Math.round(x * 10) / 10;
  const off = [], def = [];
  for (const p of list || []) {
    const a = av[p.id], st = inj[normName(p.name)]?.status || a?.status || null;
    if (a ? a.p < 0.03 : playProb(st) < 0.5) continue;     // out, out for the season
    const e = g => a ? a.p * a.scale * a.mult[g] : 1;
    const ep = e('pass'), er = e('rush'), ec = e('rec'), pl = a ? a.p : 1;
    const q = { passYds: p.passYds * mp * ep, passTd: p.passTd * mp * ep, int: p.int / (mp / k) * ep, rushYds: p.rushYds * mr * er, rushTd: p.rushTd * mr * er,
      rec: p.rec * mp * ec, recYds: p.recYds * mp * ec, recTd: p.recTd * mp * ec,
      tot: p.tot * mt * pl, tfl: p.tfl * mh * pl, sacks: p.sacks * mh * pl, hur: p.hur * mh * pl, pd: p.pd / (mp / k) * pl, ints: p.ints / (mp / k) * pl, dtd: p.dtd * pl };
    const o = OFF_PTS(q), d = DEF_PTS(q), bp = fvOf(p);
    // play: his chance to play (a status's rate, else the box scores'); st: the listed status; more: the work he
    // picks up from teammates listed out (1.25 = 25% more carries, catches or throws than usual); miss: his team's
    // games he has missed in a row
    const base = { name: bp?.name || p.name, pos: bp?.pos || p.pos, fv: bp?.fv ?? null,
      ...(a ? { play: r2(a.p), st: st && st !== 'Active' ? st : null, more: r2(a.mult[a.main]), miss: a.streak } : st ? { st } : {}) };
    if (o >= 3 && o >= d) {
      const line = p.att * ep >= 5 ? `${Math.round(q.passYds)} pass yds · ${r1(q.passTd)} pass TD` + (q.rushYds + q.recYds >= 20 ? ` · ${Math.round(q.rushYds + q.recYds)} yds · ${r1(q.rushTd + q.recTd)} TD` : '')
        : `${Math.round(q.rushYds + q.recYds)} yds` + (q.rec >= 1 ? ` · ${r1(q.rec)} rec` : '') + ` · ${r1(q.rushTd + q.recTd)} TD`;   // rushing + receiving together
      off.push({ ...base, pts: r1(o), line, ppg: r1(a ? a.ppg : OFF_PTS(p)), proj: Object.fromEntries(['passYds', 'passTd', 'int', 'rushYds', 'rushTd', 'rec', 'recYds', 'recTd'].map(k => [k, r1(q[k])])) });
    } else if (d >= 2) {
      const bits = [`${r1(q.tot)} tkl`]; if (q.tfl >= 0.2) bits.push(`${r1(q.tfl)} TFL`); if (q.sacks >= 0.2) bits.push(`${r1(q.sacks)} sk`); if (q.pd >= 0.3) bits.push(`${r1(q.pd)} PD`);
      def.push({ ...base, pts: r1(d), line: bits.join(' · ') });
    }
  }
  off.sort((a, b) => b.pts - a.pts); def.sort((a, b) => b.pts - a.pts);
  return { all: off, off: off.slice(0, 3).map(({ proj, ppg, ...x }) => x), def: def.slice(0, 3) };
}
// opponent z-scores across FBS from CFBD advanced stats
function advZ(adv, gp = {}) {
  const vals = Object.entries(adv || {}).map(([tid, a]) => ({ ...a, _g: gp[tid] || 0 }));
  const mk = f => { const xs = vals.map(f).filter(x => x != null && !isNaN(x)), m = mean(xs), s = sd(xs); return a => { const v = a ? f(a) : null; return v == null || isNaN(v) ? 0 : (v - m) / s; }; };
  return { dPass: mk(a => a.defense?.passingPlays?.ppa), dRush: mk(a => a.defense?.rushingPlays?.ppa),
    oPlays: mk(a => a._g ? (a.offense?.plays ?? NaN) / a._g : NaN), oHavoc: mk(a => a.offense?.havoc?.total) };
}

// market spread from the home side: "ALA -1.5" (favorite's abbreviation, then the points)
function marketHome(line, h, a) {
  if (!line) return null;
  if (/^even|pk|pick/i.test(line)) return 0;
  const m = /^(\S+)\s+(-?[\d.]+)/.exec(line); if (!m) return null;
  const v = +m[2];
  if (h?.abbr && m[1] === h.abbr) return v;
  if (a?.abbr && m[1] === a.abbr) return -v;
  return null;
}

// ---- games: the coming week ------------------------------------------------------------------------
// Win probability from a game rating: Elo + roster talent + home field (55, none at neutral sites) +
// injuries. Talent is the projected starters' expected NFL value by FV (the team-talent number), as z
// across FBS, worth TALENT_ELO per SD: fitted on this season's played games (log loss .418 -> .365,
// best near 170 Elo per SD) and halved, since FV already carries this season's production. Each
// projected starter listed Out or Doubtful costs his college WAR (scripts/cfb_av.mjs) x ELO_PER_WAR; without one,
// his expected college WAR at his FV, a QB double. Spread: ELO_PER_POINT. Shown next to the market line where ESPN has one.
const TALENT_ELO = 80;
// spread: 19 Elo per point. This season's margins fit best near 16 (in sample; MAE 14.3 vs 15.8 at the
// NFL-style 25), and 19 puts model spreads on the market's scale (slope .97 against the lines), so an
// edge is a disagreement about the teams rather than about how many points a rating gap is worth
const ELO_PER_POINT = 19;
// a missing starter's cost: his college WAR a season (scripts/cfb_av.mjs: season AV x .095), else his expected college
// WAR at his FV when he has no season AV (no PFN score or snaps yet). One WAR is 12 x .0189 win% a game, 4.4 points a
// game, 84 Elo at 19 per point (the 8 Elo per AV this charged before, in WAR units)
const ELO_PER_WAR = 8 / CWAR_PER_AV;
const worth = p => (p.sav ?? avOf(grade(p))) * CWAR_PER_AV;   // the grade, the scale the injury charge was set on
const normName = compact;   // the shared name key (scripts/names.mjs)
// With opts.model (scripts/cfb_model.mjs) the margin is the game model's (Elo + opponent-adjusted efficiency +
// situation, fit walk-forward) plus injuries in points, and probabilities come from its normal miss (sd
// ~ 15): win = Phi(m / sd), cover = Phi((m + market) / sd). Without it, the Elo + talent model below.
export function gamesModel(upcoming, teamList, rows, injuries = {}, opts = {}) {
  const T = Object.fromEntries(teamList.map(t => [t.tid, t]));
  const tl = teamList.map(t => t.talent), tm = mean(tl), tsd = sd(tl) || 1;
  const Z = advZ(opts.adv, opts.gp), rates = opts.rates || {};
  // board players by ESPN athlete id (CFBD uses the same ids; names change, e.g. Ryan Williams ->
  // Ryan Coleman-Williams), else by team and name
  const byId = {}, byName = {};
  for (const p of rows) if (p.tid && p.fv != null) {
    const id = /\/id\/(\d+)/.exec(p.links?.espn || '')?.[1]; if (id) byId[id] = p;
    byName[p.tid + '|' + normName(p.name)] = p;
  }
  const teamRows = {}; for (const p of rows) if (p.tid && p.fv != null) (teamRows[p.tid] ||= []).push(p);
  // a stat line or injury under another spelling of the name ("Samuel" vs "Sammy"): same team, one match
  const findP = (tid, name) => byName[tid + '|' + normName(name)] || variant(teamRows[tid], name);
  const injOf = tid => Object.fromEntries((injuries[tid] || []).flatMap(i => { const bp = findP(tid, i.name); return [[normName(i.name), i], ...(bp ? [[normName(bp.name), i]] : [])]; }));
  // availability (scripts/cfb_avail.mjs): FBS teams with box scores this season (opts.avail: { fit, tl })
  const avOf = tid => {
    if (!T[tid] || !opts.avail?.tl?.[tid]) return {};
    const inj = injOf(tid);
    return teamAvailability(opts.avail.fit, opts.avail.tl[tid], n => inj[normName(n)]?.status || null);
  };
  // a listed status's chance to play, the same rate the projections tab uses (scripts/cfb_avail.mjs statusPlay: the
  // NFL report's 2016-25 rates updated by the board's college log; questionable is lower for a player who missed his
  // team's last game), else the old constants. Active is 1: a starter cleared to play isn't charged
  const avCache = {}, avTeam = tid => (avCache[tid] ||= avOf(tid));
  const espnId = p => /\/id\/(\d+)/.exec(p?.links?.espn || '')?.[1];
  const avRow = (tid, p, name) => { const A = avTeam(tid); return A[espnId(p)] || Object.values(A).find(x => normName(x.n) === normName(name || p?.name)) || null; };
  const missedLast = (tid, p, name) => (avRow(tid, p, name)?.streak ?? 0) >= 1;
  // a season-ending injury is in the team's ratings only once it has played SEASON_ABSORB games without him: until then
  // he is charged as out (Oct 28 2026: Julian Sayin, out indefinitely after the Oct 18 game, had dropped off Ohio State's
  // line and ranking). A player with no games this season, or a team with no box scores, counts as absorbed
  const absorbed = (tid, p, name) => { if (!Object.keys(avTeam(tid)).length) return true; const a = avRow(tid, p, name); return !a || a.streak >= SEASON_ABSORB; };
  const pPlay = (st, tid, p, name) => !st || /active/i.test(st) ? 1 : statusPlay(opts.avail?.fit, st, missedLast(tid, p, name)) ?? playProb(st);
  const stars = (tid, oppTid, k = 1) => projectSide(rates[tid], k === 1 ? opts.adv?.[oppTid] : null, Z, injOf(tid),
    q => byId[q.id] || findP(tid, q.name) || null, k, avOf(tid));
  const talentAdj = t => t ? Math.round(TALENT_ELO * (t.talent - tm) / tsd) : -Math.round(TALENT_ELO * 1.5);   // non-FBS: well below
  const byTeam = {};
  for (const p of rows) if (p.tid) (byTeam[p.tid] ||= []).push(p);
  const side = (tid) => {
    const all = (byTeam[tid] || []).filter(p => p.fv != null);
    const inj = Object.fromEntries((injuries[tid] || []).map(i => [normName(variant(all, i.name)?.name || i.name), i]));
    const st = p => inj[normName(p.name)]?.status || null;
    // a season-ending injury takes the player off the depth chart once the team's ratings carry the games without him
    // (absorbed); a recent one is charged like any player out
    const ps = all.filter(p => !seasonOut(st(p)) || !absorbed(tid, p));
    const tag = p => ({ name: p.name, pos: p.pos, fv: p.fv, plus: p.plus, star: p.star, riser: p.riser, logo: p.logo, cls: p.cls, inj: st(p) });
    const top = groups => ps.filter(p => groups.includes(p.pos)).sort((a, b) => b.fv - a.fv || (b.fvx ?? b.fv) - (a.fvx ?? a.fv) || b.comp - a.comp).slice(0, 5).map(tag);
    // starters, each missing with 1 - P(plays) by his designation (out, doubtful, questionable, probable)
    const starters = [];
    for (const [g, n] of Object.entries(STARTERS)) starters.push(...ps.filter(p => p.pos === g).sort((a, b) => b.fv - a.fv).slice(0, n));
    const out = starters.map(p => ({ p, miss: 1 - pPlay(st(p), tid, p) })).filter(x => x.miss > 0);
    const adj = -Math.round(out.reduce((a, { p, miss }) => a + miss * (p.sav != null ? worth(p) : worth(p) * (p.pos === 'QB' ? 2 : 1)) * ELO_PER_WAR, 0));
    // with the game model, a QB is priced by EPA instead: his EPA per play against his backup's (both shrunk
    // toward replacement) over a game's QB plays; the rest of the starters keep the WAR cost, in points
    const nonQb = -out.filter(x => x.p.pos !== 'QB').reduce((a, { p, miss }) => a + miss * worth(p) * ELO_PER_WAR, 0) / ELO_PER_POINT;
    const qbs = M?.qb?.[tid] || [], q1 = qbs[0];
    const qst = q1 ? (injuries[tid] || []).find(i => normName(i.name) === normName(q1.name) || variant([{ name: q1.name }], i.name))?.status || null : null;
    const qmiss = 1 - pPlay(qst, tid, null, q1?.name);
    // a QB out for the season is off the depth chart like anyone else once absorbed (above), and
    // the charge is held to QB_CAP points: a QB1 absence measures ~4 pts (t -1.6, cfb_game_backtest.mjs), while a
    // backup with no plays at replacement priced some at 8-9 (Oct 21 2026 audit)
    const qbOut = q1 && q1.plays >= 60 && qmiss > 0 && !(seasonOut(qst) && absorbed(tid, null, q1.name)) ? { name: q1.name, backup: qbs[1]?.name || null, status: qst,
      pts: r1(qmiss * Math.max(-QB_CAP, (Math.max(qbs[1]?.val ?? -0.05, -0.25) - q1.val) * 38)) } : null;
    // the primary kicker out: his field goals over expected per game, at the game model's special-teams weight
    const k = opts.kickers?.[tid], kst = k ? (injuries[tid] || []).find(i => normName(i.name) === normName(k.name))?.status : null;
    const kp = kst ? pPlay(kst, tid, null, k.name) : 1;
    const kOut = k && kst && kp < 1 && k.poeG > 0 ? { name: k.name, status: kst, pts: r1(-(1 - kp) * k.poeG * (M?.stBeta ?? 0.65)) } : null;
    if (kOut) out.push({ p: { name: k.name, pos: 'K', fv: null }, miss: 1 - kp });
    return { off: top(OFFENSE), def: top(DEFENSE), injAdj: adj, injPts: r1(nonQb + (qbOut?.pts ?? 0) + (kOut?.pts ?? 0)), qbOut, kOut,
      out: out.map(({ p, miss }) => ({ name: p.name, pos: p.pos, fv: p.fv, status: st(p), miss: r2(miss) })),
      seasonOut: all.filter(p => seasonOut(st(p)) && absorbed(tid, p)).sort((a, b) => b.fv - a.fv).slice(0, 4).map(p => ({ name: p.name, pos: p.pos, fv: p.fv })) };
  };
  const M = opts.model || null;
  // bowls (not the CFP): expected opt-outs and a coaching change (data/cfb_optout.json, scripts/cfb_optout.py). Each
  // offensive regular's share of his team's yards x his excess chance to sit over the baseline, from his Transfer% and,
  // for a draft-eligible prospect, Draft% at his consensus rank's tier; the head coach changed when ESPN's current
  // coach isn't one on the season-start infobox (scripts/data/cfb_hc_start.json). pts = b x (away - home)
  const OPT = opts.optout, optSide = tid => {
    const F = OPT.fit, R = F.rates, c = k => R.cell[k] ?? R.tier[k.split('|')[0]] ?? R.base;
    const tierOf = rk => rk == null ? 0 : 1 + R.tiers.slice(1).filter(x => rk > x).length;
    const share = OPT.share[tid] || {}, byId = {};
    for (const p of byTeam[tid] || []) { const id = /\/id\/(\d+)/.exec(p.espnl || '')?.[1]; if (id) byId[id] = p; }
    let opt = 0; const who = [];
    for (const [aid, sh] of Object.entries(share)) {
      const p = byId[aid], tp = p?.transferP ?? 0, rk = p?.draft27 && p?.consRk ? p.consRk : null, dp = rk ? (p.draftP ?? 1) : 0;
      const P = tp * c('0|1') + dp * c(`${tierOf(rk)}|0`) + Math.max(0, 1 - tp - dp) * c('0|0'), ex = Math.max(0, P - R.base);
      opt += sh * ex;
      if (p && ex >= 0.15) who.push({ name: p.name, pos: p.pos, fv: p.fv, sit: r2(P), why: dp >= tp ? 'draft' : 'transfer' });
    }
    const last = n => String(n || '').toLowerCase().replace(/[^a-z ]/g, '').split(/\s+/).filter(w => w && !/^(jr|sr|ii|iii|iv)$/.test(w)).pop(), cur = OPT.coach?.[tid], start = OPT.start?.[tid];
    const hc = cur && start?.length ? (start.some(n => last(n) === last(cur)) ? 0 : 1) : 0;
    return { opt, hc, who: who.sort((a, b) => b.sit - a.sit).slice(0, 4), coach: hc ? cur : null };
  };
  const isBowl = g => g.week === 17 && !/CFP|PLAYOFF|NATIONAL CHAMPIONSHIP/i.test(g.note || '');
  const games = [];
  const players = [];   // every projected offensive player this week (the projections tab)
  for (const g of upcoming) {
    const h = T[g.home], a = T[g.away];
    if (!h && !a) continue;
    const hs = side(g.home), as = side(g.away);
    hs.talentAdj = talentAdj(h); as.talentAdj = talentAdj(a);
    const he = (h?.elo ?? 1200) + hs.talentAdj + hs.injAdj, ae = (a?.elo ?? 1200) + as.talentAdj + as.injAdj;
    const pred = M?.predict(g.id);
    let diff = he + (g.neutral ? 0 : 55) - ae, pHome = 1 / (1 + 10 ** (-diff / 400)), proj = null;
    let bowl = null;
    if (OPT?.fit && isBowl(g)) {
      const oh = optSide(g.home), oa = optSide(g.away), b = OPT.fit.b;
      bowl = { opt: r1(b.opt * (oa.opt - oh.opt)), hc: r1(b.hc * (oa.hc - oh.hc)) };
      hs.optOut = { share: r3(oh.opt), who: oh.who, coach: oh.coach }; as.optOut = { share: r3(oa.opt), who: oa.who, coach: oa.coach };
    }
    if (pred) {
      const bw = bowl ? bowl.opt + bowl.hc : 0, m = pred.margin + hs.injPts - as.injPts + bw;
      diff = m * ELO_PER_POINT; pHome = phiN(m / (pred.sigma || M.sigma));
      proj = { margin: r1(m), total: r1(pred.total), home: Math.round(pred.home + (hs.injPts - as.injPts + bw) / 2), away: Math.round(pred.away - (hs.injPts - as.injPts + bw) / 2),
        parts: { ...pred.parts, inj: r1(hs.injPts - as.injPts), ...(bowl || {}) }, wx: pred.wx, sim: pred.sim || null };
    }
    const team = (t, id, name, rank, sd) => ({ id, name: t?.team || name, logo: t?.logo || null, color: t?.color || null, rank, elo: t?.elo ?? null,
      rec: t ? `${t.rec.w}-${t.rec.l}` : null, talentRk: t?.talentRk ?? null, style: t?.style || null, ...sd });
    // the shown spread is the nearest half point, whole numbers included (-3, -3.5, -4); the edge uses the exact line
    const line = -diff / ELO_PER_POINT, spread = Math.round(line * 2) / 2, mkt = marketHome(g.line, h, a);
    // edge: model minus market, home perspective in points; who the model likes more than the market
    const edge = mkt == null ? null : { pts: r1(Math.abs(mkt - line)), side: mkt - line > 0 ? 'home' : mkt - line < 0 ? 'away' : null };
    // cover: the chance the model's side of the market line covers; total: over/under the market total
    // as the line leaves them (scripts/cover.py: the result over the close regressed on the model's gap), not the
    // model as the truth; the old sigmas only without that fit
    if (proj && mkt != null) { const c = COVER.spread, pc = phiN(c ? c.b * (proj.margin + mkt) / c.sd : (proj.margin + mkt) / (pred.sigma || M.sigma)); edge.cover = r2(edge.side === 'away' ? 1 - pc : pc); }
    if (proj && g.total != null) { const c = COVER.total, po = phiN(c ? c.b * (proj.total - g.total) / c.sd : (proj.total - g.total) / (M.report?.params?.totalSigma || 16)); proj.over = r2(po); }
    // a game with an FCS side: the FBS opponent-defense z means nothing across divisions (an FCS offense's per-game line
    // came off FCS defenses), so each side's line scales by its projected points in this game over its points a game
    // this season (both divisions' games). Without the model's points or the season scoring, the FCS side doesn't project.
    const cross = !h || !a, ppg = opts.ppg || {};
    const kOf = (t, pts) => !cross ? 1 : proj && ppg[t] ? Math.min(1.6, Math.max(0.25, pts / ppg[t])) : T[t] ? 1 : 0;
    const kh = kOf(g.home, proj?.home), ka = kOf(g.away, proj?.away);
    hs.stars = kh ? stars(g.home, g.away, kh) : { all: [], off: [], def: [] }; as.stars = ka ? stars(g.away, g.home, ka) : { all: [], off: [], def: [] };
    // the game's top three on each side of the ball, both teams together
    const tag = (t, list) => list.map(p => ({ ...p, team: t?.abbr || null, logo: t?.logo || null }));
    for (const [t, o, sd, home] of [[a, h, as, false], [h, a, hs, true]]) for (const p of sd.stars.all) players.push({ ...p, team: t?.team || (home ? g.homeName : g.awayName) || null,
      abbr: t?.abbr || (home ? g.homeAbbr : g.awayAbbr) || null, logo: t?.logo || null,   // an FCS side has no team model: ESPN's name
      opp: o?.abbr || o?.team || (home ? g.awayAbbr || g.awayName : g.homeAbbr || g.homeName) || null, oppLogo: o?.logo || null, home, kick: g.date, game: g.id });
    delete hs.stars.all; delete as.stars.all;
    const top3 = k => [...tag(a, as.stars[k]), ...tag(h, hs.stars[k])].sort((x, y) => y.pts - x.pts).slice(0, 3);
    games.push({ id: g.id, date: g.date, venue: g.venue, tv: g.tv, neutral: g.neutral, line: g.line, total: g.total, market: mkt, edge, ml: g.ml || null, spreadOdds: g.spreadOdds || null,
      home: team(h, g.home, g.homeName, g.homeRank, hs), away: team(a, g.away, g.awayName, g.awayRank, as),
      pHome: r2(pHome), spread, proj, stars: { off: top3('off'), def: top3('def') },
      // marquee: both teams good and the game close, plus prospect firepower
      score: r2((h?.eloZ ?? -1) + (a?.eloZ ?? -1) - Math.abs(pHome - 0.5) * 2 + [...hs.off, ...hs.def, ...as.off, ...as.def].reduce((x, p) => x + (p.fv >= 60 ? 0.1 : 0), 0)) });
  }
  const out = games.sort((x, y) => y.score - x.score);
  out.players = players.sort((x, y) => y.pts - x.pts);
  // every FBS team's injury charge today, in points on a neutral field (the ARK Ranking's Inj column)
  out.inj = M ? Object.fromEntries(teamList.map(t => [String(t.tid), side(t.tid).injPts]).filter(([, v]) => v)) : {};
  return out;
}

// ---- top performers: a week's best at each position ---------------------------------------------------
// CFBD box scores (games/players), each line scored on one scale per side of the ball: offense in PPR
// fantasy points, defense as tackles + 2 TFL + 3 sacks + 2 PD + 1 QB hurry + 5 INT + 6 TD, kickers 3 a
// field goal + 1 an extra point. Positions from our board (EDGE vs DL), else ESPN's roster.
const ESPN_G = { DE: 'EDGE', DT: 'DL', NT: 'DL', DL: 'DL', OLB: 'LB', ILB: 'LB', MLB: 'LB', LB: 'LB', CB: 'CB', DB: 'CB', S: 'S', FS: 'S', SS: 'S',
  QB: 'QB', RB: 'RB', FB: 'RB', WR: 'WR', TE: 'TE', PK: 'K', K: 'K', P: 'P' };
export const TOP_GROUPS = ['QB', 'RB', 'WR', 'TE', 'EDGE', 'DL', 'LB', 'CB', 'S', 'K'];
export function topPerformers(boxes, posOf, teamOf, n = 3) {
  const P = {};
  for (const g of boxes || []) {
    const [A, B] = g.teams || []; if (!A || !B) continue;
    for (const [t, o] of [[A, B], [B, A]]) for (const c of t.categories || []) for (const ty of c.types || []) for (const a of ty.athletes || []) {
      const k = a.id + '|' + g.id, x = (P[k] ||= { id: String(a.id), name: a.name, team: t.team, opp: o.team, home: t.homeAway === 'home', game: g.id, s: {} });
      x.s[`${c.name}.${ty.name}`] = a.stat;
    }
  }
  const num = v => { const n = parseFloat(v); return isFinite(n) ? n : 0; };
  const out = Object.fromEntries(TOP_GROUPS.map(g => [g, []]));
  for (const x of Object.values(P)) {
    const s = x.s, g = posOf(x.id, x.name, x.team); if (!g || !out[g]) continue;
    const [cmp, att] = String(s['passing.C/ATT'] || '0/0').split('/').map(num), [fgm, fga] = String(s['kicking.FG'] || '0/0').split('/').map(num), [xpm] = String(s['kicking.XP'] || '0/0').split('/').map(num);
    const py = num(s['passing.YDS']), ptd = num(s['passing.TD']), pint = num(s['passing.INT']), ry = num(s['rushing.YDS']), rtd = num(s['rushing.TD']), car = num(s['rushing.CAR']);
    const rec = num(s['receiving.REC']), recy = num(s['receiving.YDS']), rectd = num(s['receiving.TD']);
    const tkl = num(s['defensive.TOT']), sk = num(s['defensive.SACKS']), tfl = num(s['defensive.TFL']), pd = num(s['defensive.PD']), hur = num(s['defensive.QB HUR']),
      dtd = num(s['defensive.TD']), ints = num(s['interceptions.INT']);
    let pts = 0, line = '';
    if (g === 'K') { pts = 3 * fgm + xpm; line = `${fgm}/${fga} FG, ${xpm} XP`; }
    else if (['EDGE', 'DL', 'LB', 'CB', 'S'].includes(g)) {
      pts = tkl + 2 * tfl + 3 * sk + 2 * pd + hur + 5 * ints + 6 * dtd;
      line = [`${tkl} tkl`, tfl && `${tfl} TFL`, sk && `${sk} sk`, pd && `${pd} PD`, ints && `${ints} INT`, hur && `${hur} hur`, dtd && `${dtd} TD`].filter(Boolean).join(' · ');
    } else {
      pts = 0.04 * py + 4 * ptd - 2 * pint + 0.1 * ry + 6 * rtd + rec + 0.1 * recy + 6 * rectd;
      line = g === 'QB' ? `${cmp}/${att}, ${py} yds, ${ptd} TD${pint ? `, ${pint} INT` : ''}` + (ry >= 20 || rtd ? ` · ${car} car, ${ry} yds${rtd ? `, ${rtd} TD` : ''}` : '')
        : [car && `${car} car, ${ry} yds${rtd ? `, ${rtd} TD` : ''}`, rec && `${rec} rec, ${recy} yds${rectd ? `, ${rectd} TD` : ''}`].filter(Boolean).join(' · ');
    }
    if (pts > 0) out[g].push({ ...teamOf(x), name: x.name, id: x.id, opp: x.opp, home: x.home, pts: r1(pts), line });
  }
  for (const g of TOP_GROUPS) out[g] = out[g].sort((a, b) => b.pts - a.pts).slice(0, n);
  return out;
}

// ---- NFL draft order (ESPN) and needs (ESPN + nflverse) ------------------------------------------------------------------
// Projected order: non-playoff teams by record (worst first), then playoff teams by seed, using ESPN's
// current standings and playoff seeds; ties broken by point differential. Compensatory picks aren't public in
// a scriptable, permitted source; traded picks come from applyNflTrades below.
// NFL draft order (the league's rule): teams out of the playoffs first, by win%, then playoff teams by the round
// they went out in (wild card, divisional, conference, Super Bowl loser, champion), by win% within it. Ties break on
// strength of schedule (the combined record of every opponent on the schedule; the weaker schedule picks first),
// then the tiebreakers the league uses for standings, reversed (the team that would win the tie picks later):
// head-to-head (when every tied team played the others), division record (all in one division), common games
// (4+), conference record (all in one conference), strength of victory, then a coin flip (point differential
// here, so the order doesn't flicker run to run). In season, the teams holding playoff seeds go last, by record:
// nothing has eliminated them yet. Games from ESPN's weekly scoreboards; divisions from its standings.
// Backtest: scripts/nfl_order_backtest.mjs (2020-25 first rounds)
export async function nflSeason(season) {
  const st = await espnJson(`https://site.api.espn.com/apis/v2/sports/football/nfl/standings?season=${season}&level=3`);
  const teams = {};
  for (const conf of st?.children || []) for (const div of conf.children || []) for (const e of div.standings?.entries || []) {
    const sx = Object.fromEntries(e.stats.map(x => [x.name, x.value]));
    teams[e.team.abbreviation] = { team: e.team.abbreviation, teamName: e.team.displayName, id: e.team.id, logo: e.team.logos?.[0]?.href || null,
      div: div.name || div.abbreviation, conf: (div.name || '').split(' ')[0], seed: sx.playoffSeed ?? 99 };
  }
  const games = [], post = [];
  for (const [type, weeks] of [[2, 18], [3, 5]]) for (let wk = 1; wk <= weeks; wk++) {
    if (type === 3 && wk === 4) continue;   // the Pro Bowl week
    const sb = await espnJson(`https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates=${season}&seasontype=${type}&week=${wk}`);
    for (const ev of sb?.events || []) {
      if (ev.season?.type !== type || ev.season?.year !== season) continue;
      const c = ev.competitions?.[0], [a, b] = (c?.competitors || []).map(x => ({ t: x.team?.abbreviation, pts: +x.score || 0 }));
      if (!a || !b || !teams[a.t] || !teams[b.t]) continue;
      const g = { a: a.t, b: b.t, pa: a.pts, pb: b.pts, done: !!c.status?.type?.completed, week: wk };
      (type === 2 ? games : post).push(g);
    }
  }
  return { teams, games, post };
}
export function nflDraftOrder({ teams, games, post }) {
  const T = Object.values(teams), done = games.filter(g => g.done);
  const res = (g, t) => g.a === t ? Math.sign(g.pa - g.pb) : Math.sign(g.pb - g.pa);   // 1 win, 0 tie, -1 loss
  const pct = (gs, t) => gs.length ? gs.reduce((s, g) => s + (res(g, t) + 1) / 2, 0) / gs.length : null;
  const mine = t => done.filter(g => g.a === t || g.b === t), opp = (g, t) => g.a === t ? g.b : g.a;
  for (const t of T) {
    const gs = mine(t.team);
    t.w = gs.filter(g => res(g, t.team) > 0).length; t.l = gs.filter(g => res(g, t.team) < 0).length; t.t = gs.length - t.w - t.l;
    t.pct = pct(gs, t.team) ?? 0; t.diff = gs.reduce((s, g) => s + (g.a === t.team ? g.pa - g.pb : g.pb - g.pa), 0);
  }
  const P = Object.fromEntries(T.map(t => [t.team, t])), comb = L => { const g = L.reduce((s, o) => s + o.w + o.l + o.t, 0); return g ? L.reduce((s, o) => s + o.w + 0.5 * o.t, 0) / g : 0.5; };
  for (const t of T) {
    t.sos = comb(games.filter(g => g.a === t.team || g.b === t.team).map(g => P[opp(g, t.team)]));   // the whole schedule
    t.sov = comb(mine(t.team).filter(g => res(g, t.team) > 0).map(g => P[opp(g, t.team)]));
  }
  // a tied group, worst first: each step splits it where it can, and what's still tied goes to the next step
  const steps = [
    grp => grp.map(t => t.sos),
    grp => { const ts = new Set(grp.map(t => t.team)), all = grp.every(t => grp.every(u => u === t || done.some(g => (g.a === t.team && g.b === u.team) || (g.b === t.team && g.a === u.team))));
      return all ? grp.map(t => pct(done.filter(g => (g.a === t.team || g.b === t.team) && ts.has(opp(g, t.team))), t.team) ?? 0.5) : null; },
    grp => new Set(grp.map(t => t.div)).size === 1 ? grp.map(t => pct(mine(t.team).filter(g => P[opp(g, t.team)].div === t.div), t.team)) : null,
    grp => { const sets = grp.map(t => new Set(mine(t.team).map(g => opp(g, t.team)))), common = [...sets[0]].filter(o => sets.every(x => x.has(o)) && !grp.some(t => t.team === o));
      const cg = grp.map(t => mine(t.team).filter(g => common.includes(opp(g, t.team))));
      return cg.every(x => x.length >= 4) ? grp.map((t, i) => pct(cg[i], t.team)) : null; },
    grp => new Set(grp.map(t => t.conf)).size === 1 ? grp.map(t => pct(mine(t.team).filter(g => P[opp(g, t.team)].conf === t.conf), t.team)) : null,
    grp => grp.map(t => t.sov),
    grp => grp.map(t => t.diff),
  ];
  const breakTie = (grp, k = 0) => {
    if (grp.length < 2 || k >= steps.length) return [...grp].sort((a, b) => a.team.localeCompare(b.team));
    const v = steps[k](grp);
    if (!v || new Set(v.map(x => Math.round(x * 1e6))).size === 1) return breakTie(grp, k + 1);
    // the lowest value picks first; one split at a time (the NFL re-runs the steps for what's left)
    const lo = Math.min(...v), first = grp.filter((t, i) => Math.round(v[i] * 1e6) === Math.round(lo * 1e6)), rest = grp.filter(t => !first.includes(t));
    return [...breakTie(first, 0), ...breakTie(rest, 0)];
  };
  const byRecord = list => {
    const out = [], g = {};
    for (const t of list) (g[t.pct.toFixed(6)] ||= []).push(t);
    for (const k of Object.keys(g).sort((a, b) => a - b)) out.push(...breakTie(g[k]));
    return out;
  };
  // the round each playoff team went out in (5 = won it all); in season, the seeded teams with no exit yet
  const exit = {};
  for (const g of post.filter(g => g.done)) { const [w, l] = g.pa > g.pb ? [g.a, g.b] : [g.b, g.a]; exit[l] = g.week === 5 ? 4 : g.week; if (g.week === 5) exit[w] = 5; }
  const started = post.some(g => g.done), inPost = t => started ? (exit[t.team] != null || post.some(g => g.a === t.team || g.b === t.team)) : t.seed <= 7;
  const order = byRecord(T.filter(t => !inPost(t)));
  const pl = T.filter(inPost), rounds = [...new Set(pl.map(t => exit[t.team] ?? 9))].sort((a, b) => a - b);
  for (const r of rounds) order.push(...byRecord(pl.filter(t => (exit[t.team] ?? 9) === r)));
  return order;
}
// In season, the order goes by each team's expected final slot from the NFL game model's season sims (data/nfl_games.json
// power xSlot, scripts/nfl_games.py: the rest of the season and the playoffs played out 10,000 times, League.draft_order).
// Backtest (scripts/nfl_season_backtest.py --order, data/nfl_season_backtest.json orderTest), before weeks 4-14 of 2015-25,
// each team's error to the final order: 4.34 slots vs 4.82 by record to date on 2015-20 (t -3.3, 5 of 6 seasons) and 5.05
// vs 5.33 on 2021-25 (t -1.6, 4 of 5), better at every week. Once the regular season is over, the record order above is
// exact for the clubs out of the playoffs and stands.
const NFL_ESPN = { LA: 'LAR', WAS: 'WSH' };
function nflSimSlots(season) {
  try {
    const d = JSON.parse(fs.readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'data', 'nfl_games.json'), 'utf8'));
    if (d.season !== season || !d.left) return null;
    const xs = Object.fromEntries((d.power || []).filter(r => r.xSlot != null).map(r => [NFL_ESPN[r.t] || r.t, r.xSlot]));
    return Object.keys(xs).length === 32 ? xs : null;
  } catch { return null; }
}
export async function fetchNflOrder(season = SEASON, rounds = 7) {
  const S = await nflSeason(season), xs = S.games.some(g => !g.done) ? nflSimSlots(season) : null;
  let base = nflDraftOrder(S);
  if (xs && base.every(t => xs[t.team] != null)) base = [...base].sort((a, b) => xs[a.team] - xs[b.team]);
  const order = [];
  for (let r = 1; r <= rounds; r++) base.forEach((t, i) => order.push({ pick: (r - 1) * base.length + i + 1, round: r, team: t.team, teamName: t.teamName, espnId: t.id, from: null }));
  return { order, teams: Object.fromEntries(base.map(t => [t.team, { name: t.teamName, espnId: t.id, logo: t.logo, rec: `${t.w}-${t.l}${t.t ? `-${t.t}` : ''}`, sos: Math.round(t.sos * 1000) / 1000, div: t.div, ...(xs ? { xSlot: xs[t.team] } : {}) }])) };
}

// Picks already traded (real trades, made before the draft): Wikipedia's "Trades involving draft picks" list
// for the draft, read from the page source. Each line is "Team A → Team B (PD)" under its round: A's pick in that
// round now belongs to B ("A → B → C": several deals, C holds it). A line can name a pick "whichever is earlier"
// of two the team holds; it takes the earlier in the projected order. Conditional picks count as traded.
const NFL_CITY = { 'Arizona': 'ARI', 'Atlanta': 'ATL', 'Baltimore': 'BAL', 'Buffalo': 'BUF', 'Carolina': 'CAR', 'Chicago': 'CHI',
  'Cincinnati': 'CIN', 'Cleveland': 'CLE', 'Dallas': 'DAL', 'Denver': 'DEN', 'Detroit': 'DET', 'Green Bay': 'GB', 'Houston': 'HOU',
  'Indianapolis': 'IND', 'Jacksonville': 'JAX', 'Kansas City': 'KC', 'Las Vegas': 'LV', 'LA Chargers': 'LAC', 'LA Rams': 'LAR',
  'Miami': 'MIA', 'Minnesota': 'MIN', 'New England': 'NE', 'New Orleans': 'NO', 'NY Giants': 'NYG', 'NY Jets': 'NYJ',
  'Philadelphia': 'PHI', 'Pittsburgh': 'PIT', 'San Francisco': 'SF', 'Seattle': 'SEA', 'Tampa Bay': 'TB', 'Tennessee': 'TEN', 'Washington': 'WSH' };
export async function fetchNflTrades(draftYear) {
  const r = await fetch(`https://en.wikipedia.org/w/index.php?title=${draftYear}_NFL_draft&action=raw`, { headers: { 'user-agent': UA } });
  if (!r.ok) throw new Error(`wikipedia ${r.status}`);
  const src = (await r.text()).replace(/<!--[\s\S]*?-->/g, '');
  const sec = src.split(/^==\s*Trades involving draft picks\s*==/m)[1]?.split(/^==[^=]/m)[0];
  if (!sec) throw new Error('no trades section');
  // a deal's players, for the report ("the Micah Parsons trade"): the linked names in its sentence, last first
  const anchors = {}, out = [];
  const players = s => [...s.replace(/<ref[\s\S]*?(<\/ref>|\/>)/g, '').matchAll(/\[\[([^\]|#]+)(?:\|([^\]]+))?\]\]/g)].map(m => (m[2] || m[1]).trim());
  let round = 0;
  for (const line of sec.split('\n')) {
    const h = /^===\s*Round (\d)\s*===/.exec(line); if (h) { round = +h[1]; continue; }
    if (!round || !line.startsWith('*')) continue;
    const head = /'''([^']+?)\.?'''/.exec(line); if (!head) continue;
    const teams = head[1].replace(/\((PD|D)\)/g, '').replace(/\.$/, '').split('→').map(s => NFL_CITY[s.trim().replace(/\.$/, '')]);
    if (teams.length < 2 || teams.some(t => !t)) continue;
    const anc = /\{\{Anchor\|([^}]+)\}\}/i.exec(line)?.[1], see = /\[\[#([^|\]]+)/.exec(line)?.[1];
    const body = line.slice(head.index + head[0].length);
    let who = see ? anchors[see] || [] : players(body);
    if (anc) anchors[anc] = who;
    out.push({ round, from: teams[0], to: teams[teams.length - 1], deal: who.length ? who[who.length - 1] : null,
      cond: /conditional/i.test(body.split(/<ref/)[0]), earlier: /whichever is earlier|earlier of/i.test(body) });
  }
  return out;
}
// The real trades onto the projected order: each pick keeps its original team in `via`; `team` is who holds it.
export function applyNflTrades(order, trades, teams = {}) {
  for (const t of trades || []) {
    const inRound = order.filter(o => o.round === t.round && o.team === t.from);
    const o = t.earlier ? inRound.sort((a, b) => a.pick - b.pick)[0] : (inRound.find(x => (x.via || x.team) === t.from) || inRound[0]);   // its own gone: one it acquired
    if (!o) { t.unmatched = true; continue; }
    o.via ||= o.team; o.team = t.to; o.teamName = teams[t.to]?.name || t.to; o.espnId = teams[t.to]?.espnId ?? o.espnId;
    o.deal = t.deal; o.cond = t.cond; o.dealTo = t.to;
  }
  return order;
}

// Needs from each NFL team's whole position room, not just the depth chart's top line: every player on the
// roster (ESPN rosters: age, experience, this season's salary, contract years left; nflverse rosters: where he
// was drafted) gets a 0-1 quality through next season, the better of
//   draft capital  a player on his rookie deal (4 seasons or fewer), by pick: 1 - .13 ln(pick), so the #1 pick
//                  is 1, #10 .70, #32 .55, #100 .40, an undrafted player .05
//   market price   salary over the top of the position's market (NFL_TOP_PAY): what the league pays him for
// cut for age (QBs 35+, others 30+) and for a veteran whose deal ends after this season. A group's need is
// 1 minus the average quality of its best NFL_STARTERS players (an empty slot is 0): the Raiders, with the
// 2026 #1 pick behind a 38-year-old on a minimum deal, have no QB need. That raw need is then ranked against
// the league at the position (below).
// the line is three rooms, not one: tackles (either side), guards (either side) and center. A team that just
// drafted a guard has filled one of two guard spots, not one of five line spots (2010-25 drafts: a team that took
// a guard in rounds 1-3 took another there the next year 2% of the time, against 11%)
const NFL_STARTERS = { QB: 1, RB: 1, WR: 3, TE: 1, OT: 2, G: 2, C: 1, EDGE: 2, DL: 2, LB: 2, CB: 3, S: 2 };
const NFL_TOP_PAY = { QB: 55e6, RB: 14e6, WR: 33e6, TE: 18e6, OT: 25e6, G: 20e6, C: 18e6, EDGE: 32e6, DL: 30e6, LB: 20e6, CB: 25e6, S: 20e6 };
const DC_GROUP = { qb: 'QB', rb: 'RB', wr: 'WR', te: 'TE', lt: 'OT', lg: 'G', c: 'C', rg: 'G', rt: 'OT',
  ldt: 'DL', rdt: 'DL', dt: 'DL', nt: 'DL', mlb: 'LB', lilb: 'LB', rilb: 'LB', lcb: 'CB', rcb: 'CB', nb: 'CB', ss: 'S', fs: 'S' };
const ROSTER_GROUP = { QB: 'QB', RB: 'RB', FB: 'RB', WR: 'WR', TE: 'TE', OT: 'OT', G: 'G', C: 'C', OL: 'G', DT: 'DL', NT: 'DL', DE: 'EDGE', CB: 'CB', S: 'S', FS: 'S', SS: 'S', DB: 'CB' };
const csvRows = text => {
  const out = []; let row = [], f = '', q = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (q) { if (ch === '"' && text[i + 1] === '"') { f += '"'; i++; } else if (ch === '"') q = false; else f += ch; }
    else if (ch === '"') q = true; else if (ch === ',') { row.push(f); f = ''; } else if (ch === '\n') { row.push(f); out.push(row); row = []; f = ''; } else if (ch !== '\r') f += ch;
  }
  if (f || row.length) { row.push(f); out.push(row); }
  const [h, ...rs] = out; return rs.map(r => Object.fromEntries(h.map((k, i) => [k, r[i]])));
};
export async function fetchNflNeeds(orderTeams, season = SEASON) {
  // draft slot by ESPN id (nflverse rosters)
  const drafted = {};
  try {
    const r = await fetch(`https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_${season}.csv`, { headers: { 'user-agent': UA } });
    // nflverse leaves the ESPN id off about a fifth of recent draftees (51 of the 2026 class, Francis Mauigoa
    // among them), so they also match by name: without it the team's newest picks counted as minimum deals
    for (const p of csvRows(await r.text())) {
      const d = { pick: +p.draft_number || null, year: +p.rookie_year || +p.entry_year || null, dc: p.depth_chart_position };
      if (p.espn_id) drafted[p.espn_id] = d;
      if (d.pick) { const k = 'n:' + nameKey(p.full_name); drafted[k] = drafted[k] && drafted[k].pick !== d.pick ? 'dup' : d; }
    }
  } catch (e) { console.log(`nflverse roster: ${e.message}`); }
  // kickers' field goals, this season (once he has 15 tries) or last (nflverse player stats), for the kicker need
  const fg = {};
  for (const y of [season - 1, season]) {
    try {
      const r = await fetch(`https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_reg_${y}.csv`, { headers: { 'user-agent': UA } });
      if (!r.ok) continue;
      for (const p of csvRows(await r.text())) if (p.position === 'K' && +p.fg_att > 0) { const k = nameKey(p.player_display_name); fg[k] = { ...(fg[k] || {}), [y === season ? 'now' : 'last']: [+p.fg_made, +p.fg_att] }; }
    } catch (e) { console.log(`nflverse kicking ${y}: ${e.message}`); }
  }
  const needs = {};
  for (const [abbr, t] of Object.entries(orderTeams)) {
    const [dc, ro] = await Promise.all([
      espnJson(`https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/${t.espnId}/depthcharts`),
      espnJson(`https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/${t.espnId}/roster`)]);
    // a player's group: his depth-chart slot when he has one (3-4 ends inside, 3-4 OLBs on the edge), else his roster position
    const slotOf = {}, threeFour = (dc?.depthchart || []).some(u => /3-4/.test(u.name || ''));
    let pkId = null;
    for (const unit of dc?.depthchart || []) {
      const tf = /3-4/.test(unit.name || '');
      pkId ||= unit.positions?.pk?.athletes?.[0]?.id ?? null;
      for (const [slot, v] of Object.entries(unit.positions || {})) {
        let g = DC_GROUP[slot];
        if (['lde', 'rde', 'de'].includes(slot)) g = tf ? 'DL' : 'EDGE';
        if (['wlb', 'slb', 'lolb', 'rolb', 'olb'].includes(slot)) g = tf ? 'EDGE' : 'LB';
        if (g) for (const a of v.athletes || []) slotOf[a.id] ||= g;
      }
    }
    const room = {}, kickers = [];
    for (const grp of ro?.athletes || []) {
      if (grp.position === 'practiceSquad') continue;
      for (const a of grp.items || []) {
        if (a.position?.abbreviation === 'PK') kickers.push({ id: a.id, name: a.displayName, age: a.age ?? 30 });
        const pos = a.position?.abbreviation, byName = drafted['n:' + nameKey(a.displayName)], d = drafted[a.id] || (byName !== 'dup' && byName) || {};
        const g = slotOf[a.id] || ROSTER_GROUP[pos] || (pos === 'LB' ? (/OLB/.test(d.dc || '') && threeFour ? 'EDGE' : 'LB') : null);
        if (!g) continue;
        // pay: the deal's yearly average, not this season's cash (a restructure can cut one year's salary in half:
        // Herbert's 2026 is $24M on a ~$50M-a-year deal): cash from two seasons back through the deal's last year
        const c = a.contract || {}, age = a.age ?? 27, exp = a.experience?.years ?? 3, left = c.yearsRemaining ?? null;
        const deal = (a.contracts || []).filter(x => x.salary > 0 && (!x.season || x.season.year >= season - 2)).map(x => x.salary);
        const pay = Math.max(c.salary ?? 0, deal.length ? deal.reduce((p, x) => p + x, 0) / deal.length : 0);
        const rookie = exp <= 4 && d.year && season - d.year <= 3;
        const draftQ = rookie ? (d.pick ? Math.max(0.15, 1 - 0.13 * Math.log(d.pick)) : 0.05) : 0;
        let q = Math.max(draftQ, Math.min(1, pay / NFL_TOP_PAY[g]));
        if (age >= (g === 'QB' ? 35 : 30)) q *= 0.7;
        if (age >= (g === 'QB' ? 38 : 32)) q *= 0.6;
        if (left != null && left <= 0 && exp >= 5) q *= 0.6;           // a veteran whose deal is up: may walk
        // a franchise QB (paid near the top of the market with 2+ years left, under 35) closes the position
        if (g === 'QB' && pay >= 0.7 * NFL_TOP_PAY.QB && (left ?? 0) >= 2 && age < 35) q = Math.max(q, 0.9);
        // so does a first-round QB from the last two drafts: teams give him time before spending another first
        if (g === 'QB' && rookie && d.pick && d.pick <= 32 && season - d.year <= 1) q = Math.max(q, 0.85);
        const why = rookie && d.pick ? `#${d.pick} pick, ${d.year}` : pay ? `$${(pay / 1e6).toFixed(1)}M${left != null ? `, ${left ? `${left} more yr${left > 1 ? 's' : ''}` : 'expiring'}` : ''}` : 'minimum deal';
        (room[g] ||= []).push({ name: a.displayName, q, why: `${why}, ${age}` });
      }
    }
    needs[abbr] = Object.entries(NFL_STARTERS).map(([g, n]) => {
      const top = (room[g] || []).sort((a, b) => b.q - a.q).slice(0, n);
      const qual = top.reduce((s, p) => s + p.q, 0) / n;
      return { group: g, label: g, score: Math.round(100 * (1 - qual)) / 100, room: top.map(p => `${p.name} (${p.why})`) };
    }).sort((a, b) => b.score - a.score);
    // kicker: a need (1) when the starter is 35+ or under 80% on 15+ field goals (this season, else last), else 0
    // (scripts/draft_replay7.py: such teams drafted a kicker 10% of the time, the rest 4%); a team with none needs one
    const k = kickers.find(x => x.id === pkId) || kickers[0];
    if (k) {
      const s = fg[nameKey(k.name)] || {}, [m, a] = s.now?.[1] >= 15 ? s.now : s.last?.[1] >= 15 ? s.last : s.now || s.last || [0, 0];
      const flag = k.age >= 35 || (a >= 15 && m / a < 0.8);
      needs[abbr].push({ group: 'K', label: 'K', score: flag ? 1 : 0, raw: flag ? 1 : 0, room: [`${k.name} (${k.age}${a ? `, ${m}/${a} FG` : ''})`] });
    } else needs[abbr].push({ group: 'K', label: 'K', score: 1, raw: 1, room: [] });
    await sleep(120);
  }
  // positions aren't paid or drafted alike (an average starting guard earns a fraction of an average QB), so the
  // need is half absolute (1 - quality) and half relative: where the room ranks among the 32 (0 best, 1 worst)
  for (const g of Object.keys(NFL_STARTERS)) {
    const list = Object.values(needs).map(ns => ns.find(n => n.group === g)).filter(Boolean).sort((a, b) => a.score - b.score);
    list.forEach((n, i) => { n.raw = n.score; n.score = Math.round(100 * (n.raw + (list.length > 1 ? i / (list.length - 1) : n.raw)) / 2) / 100; });
  }
  for (const ns of Object.values(needs)) ns.sort((a, b) => b.score - a.score || b.raw - a.raw);
  return needs;
}

// ---- staff ------------------------------------------------------------------------------------------
// Coordinators get their side's position groups; head coaches the team. Two signals per group:
//   over:  how far the group's production runs ahead of its talent (PFN z minus On3-based z), the
//          starters weighted by snaps — coaching shows up as players producing above their grade
//   dev:   On3 college grade minus high school grade for the group's ranked players — who got better
//   nil:   zNIL growth, log((xNIL + k) / (yNIL + k)): market value added relative to what the roster was paid,
//          scale-free, and centered within P4 / G5: a G5 roster's yNIL is set by a small budget, so any good
//          G5 player looks underpaid; the staff is credited only for growth beyond its tier's norm
// Scores are indices: 100 = average coordinator, 10 = one standard deviation (+ like OPS+).
export function staffModels(rows, teamList, staff) {
  const byTeam = {};
  for (const p of rows) if (p.tid) (byTeam[p.tid] ||= []).push(p);
  const groupScore = (ps, groups) => {
    const st = [];
    for (const g of groups) st.push(...ps.filter(p => p.pos === g && p.pfn != null).sort((a, b) => b.comp - a.comp).slice(0, STARTERS[g]));
    const w = st.map(p => Math.max(1, p.snaps || 1));
    const over = st.length ? st.reduce((a, p, i) => a + w[i] * (p.prodZ - p.talentZ), 0) / w.reduce((a, b) => a + b, 0) : null;
    const devs = ps.filter(p => groups.includes(p.pos) && p.on3 != null && p.hsGrade != null).map(p => p.on3 - p.hsGrade);
    // zNIL: market value grown in the season (xNIL - yNIL), the side's position groups summed
    const gp = ps.filter(p => groups.includes(p.pos)), sum = k => Math.round(gp.reduce((a, p) => a + (p[k] || 0), 0));
    const znil = sum('znil'), ynil = sum('ynil'), xnil = sum('xnil');
    return { over, dev: devs.length ? mean(devs) : null, devN: devs.length, znil, xnil, ynil, znilTop: nilTop(gp),
      risers: ps.filter(p => groups.includes(p.pos) && p.on3 != null && p.hsGrade != null && p.on3 - p.hsGrade >= 8)
        .sort((a, b) => (b.on3 - b.hsGrade) - (a.on3 - a.hsGrade)).slice(0, 3)
        .map(p => ({ name: p.name, pos: p.pos, hs: Math.round(p.hsGrade), now: p.on3, stars: p.hsStars })) };
  };
  const nilTop = ps => ps.filter(p => p.znil > 0).sort((a, b) => b.znil - a.znil).slice(0, 3).map(p => ({ name: p.name, pos: p.pos, znil: p.znil }));
  const coaches = [];
  for (const t of teamList) {
    const ps = byTeam[t.tid] || [], s = staff?.[t.tid] || {};
    const off = groupScore(ps, OFFENSE), def = groupScore(ps, DEFENSE);
    const base = { tid: t.tid, team: t.team, logo: t.logo, conf: t.conf };
    const hcName = s.hc?.name || t.hc;
    if (hcName) coaches.push({ ...base, role: 'HC', name: hcName, src: s.hc?.src || 'espn', wiki: s.hc?.wiki, raw: t.eloZ == null ? null : t.eloZ * 0.5 + (t.tve ?? 0) * 0.5,
      znil: t.znil ?? null, xnil: t.xnil ?? null, ynil: t.ynil ?? null, znilTop: t.znilTop || nilTop(ps), detail: { elo: t.elo, eloRk: t.eloRk, tve: t.tve, rec: t.rec } });
    for (const [role, side, groups] of [['OC', off, OFFENSE], ['DC', def, DEFENSE]]) {
      const c = s[role.toLowerCase()];
      if (!c?.name) continue;
      coaches.push({ ...base, role, name: c.name, src: c.src, wiki: c.wiki, wikis: c.wikis, groups, raw: null, over: side.over, dev: side.dev, devN: side.devN, znil: side.znil, xnil: side.xnil, ynil: side.ynil, znilTop: side.znilTop, risers: side.risers });
    }
  }
  // zNIL growth (see above), standardized within role x tier (P4 / G5) and capped at 2.5 SD (one breakout
  // can't carry a staff); znilV is that z, znilRk its rank within the role
  const NIL_K = 250e3, P4C = new Set(['SEC', 'Big Ten', 'Big 12', 'ACC']), tier = c => P4C.has(c.conf) || c.team === 'Notre Dame';
  for (const c of coaches) c.nilG = c.ynil ? Math.log(((c.xnil || 0) + NIL_K) / (c.ynil + NIL_K)) : null;
  for (const role of ['HC', 'OC', 'DC']) {
    for (const p4 of [true, false]) {
      const list = coaches.filter(c => c.role === role && c.nilG != null && tier(c) === p4), z = zs(list.map(c => c.nilG));
      list.forEach((c, i) => { c.nilZ = Math.max(-2.5, Math.min(2.5, z[i])); c.znilV = r2(c.nilZ); });
    }
    rank(coaches.filter(c => c.role === role && c.nilZ != null), 'nilZ', 'znilRk');
  }
  // head coach: team results (Elo), results above talent (TvE), roster value grown (zNIL)
  // (hand weights: a fitted coach value-added, scripts/cfb_coach_va.py, didn't carry from old job to new on 118
  // held-out movers, Oct 25 2026, so it doesn't replace them)
  for (const c of coaches) if (c.role === 'HC' && c.raw != null) c.raw = 0.8 * c.raw + 0.2 * (c.nilZ ?? 0);
  // coordinator raw score: production-over-talent, development and zNIL growth, each standardized among coordinators
  const coords = coaches.filter(c => c.role !== 'HC');
  const oz = zs(coords.map(c => c.over ?? 0)), dz = zs(coords.map(c => c.dev ?? 0));
  coords.forEach((c, i) => { c.raw = 0.5 * oz[i] + 0.3 * (c.devN >= 3 ? dz[i] : 0) + 0.2 * (c.nilZ ?? 0); });
  for (const role of ['HC', 'OC', 'DC']) {
    const list = coaches.filter(c => c.role === role && c.raw != null);
    const z = zs(list.map(c => c.raw));
    list.forEach((c, i) => { c.score = Math.round(100 + 10 * z[i]); });
    rank(list, 'score', 'rk');
  }
  for (const c of coaches) { if (c.over != null) c.over = r2(c.over); if (c.dev != null) c.dev = r1(c.dev);
    c.znilG = c.ynil ? r2((c.xnil || 0) / c.ynil - 1) : null; delete c.raw; delete c.nilG; delete c.nilZ; }
  return coaches.filter(c => c.score != null).sort((a, b) => b.score - a.score);
}

// ---- mock draft ------------------------------------------------------------------------------------
// A projection of how the draft will go, not our big board. Each prospect gets an expected pick (xPick), a
// geometric blend of two ranks:
//   market: the industry consensus board's average rank (cons), weighted up with the share of the boards
//           that rank him (MARKET_W). A draft-eligible player no board ranks is priced past the boards' depth
//           (UNRANKED_DEPTH x the deepest average rank): the league hasn't put him in its top ~150 either
//   model:  rank on our board by draft value = FV + positional value for the round he'd go in + frame
//           (a shortfall under NFL size norms costs; a position-change flag is valued at the new spot too,
//           less MOVE_COST FV for the projection risk), with each position's price then set to the market's
//           (mktPosAdj: the league pays for QB, EDGE, CB and OT; our FV alone ranks WR and RB above where
//           boards put them)
// Teams then pick on log(xPick) (pick value falls off like a log: the gap between picks 2 and 4 is worth the
// gap between 20 and 40), plus team need (fetchNflNeeds: 1 minus the quality of the starters the roster already
// has, by draft capital and pay; each pick fills part of it for the team's later picks), with penalties for a team
// doubling up at a position, a team with a set QB taking one early, and a position running past its usual count in the round. A player flagged to
// move can be taken at the new spot when the team needs it there more.
// Three mocks run on the same order, needs and trade rules (mode): predictive (pred, above: consensus and model at the
// backtested weights, how the draft will go), conviction (conv: the model's own board, no consensus, no market
// positional price, no run penalty: the best player for each team by our grade and its fit) and blended (blend: each
// prospect's slot halfway between the two on the log scale, half the run penalty). They grade each other (GRADE_*, mockDrafts).
// Positional values and per-round counts come from data/cfb_draft_priors.json (measured on 2015-25
// drafts) when present; the defaults below are the long-run averages.
const DEFAULT_PRIORS = {
  value: { QB: [6, 3, 1], EDGE: [3, 2, 1], OL: [2, 1.5, 1], WR: [2, 1.5, 1], CB: [2, 1.5, 1], DL: [1, 1, 0.5], TE: [-1.5, -0.5, 0], S: [-2, -0.5, 0], LB: [-2.5, -0.5, 0], RB: [-3, -1, 0] },
  perRound: { QB: [3.5, 2, 1.5], RB: [1.2, 2.5, 3], WR: [4.5, 5, 4.5], TE: [1, 2, 2.5], OL: [6, 6, 6], EDGE: [4.5, 4, 3.5], DL: [3, 3, 3.5], LB: [1.5, 3, 3.5], CB: [4.5, 4.5, 4], S: [1.5, 3, 3] },
};
const MARKET_W = { base: 0.55, perBoard: 0.3, unranked: 0.65 };   // weight on the market rank: base + perBoard x sqrt(share of boards); unranked
const CONS_BOARDS_N = 9;
const UNRANKED_DEPTH = 1.3;
// board rank to draft slot (scripts/draft_backtest.py, data/cfb_draft_backtest.json), fit on 2020-25 (DraftTek's final pre-draft boards, top 200, against nflverse picks;
// undrafted = 290): ln pick = c + a ln rank + b ln^2 rank. Top picks go a little later than their rank and deep
// ones later still (#1 ~1.5, #32 ~36, #100 ~111). Leave-one-draft-out, adding position, class (underclassman),
// conference level (P5 / G5 / FCS) and size against NFL norms did not lower the error: a final board already
// prices them. A missing combine invite (+.17 ln pick, ~19% later) and the 40 time (+.09 per SD slower, within
// the position) did, so they apply once the draft year's combine results are published
const BOARD_PICK = { c: 0.375, a: 0.880, b: 0.0132, noCombine: 0.173, forty: 0.088 };
const lnPickOf = r => { const l = Math.log(Math.max(1, r)); return BOARD_PICK.c + BOARD_PICK.a * l + BOARD_PICK.b * l * l; };
// a lineman's spot as the board shows it: tackle (either side) OT, guard (either side) G, center C
export const olSpot = s => /^(LT|RT|ST|OT|T)$/.test(s || '') ? 'OT' : /^(LG|RG|OG|G)$/.test(s || '') ? 'G' : s;
// the NFL rooms a lineman can fill: his spot's (OT, G, C; an interior lineman either inside room; no spot: any),
// plus the inside rooms for a tackle flagged to move inside, or the tackle room for the reverse (as a move)
const OL_ROOMS = { OT: ['OT'], G: ['G'], C: ['C'], IOL: ['G', 'C'] };
const olRooms = p => {
  const own = OL_ROOMS[olSpot(p.spot)] || ['OT', 'G', 'C'];
  const mv = p.move === 'IOL' ? ['G', 'C'] : p.move === 'OT' ? ['OT'] : [];
  return [...own.map(k => [k, false]), ...mv.filter(k => !own.includes(k)).map(k => [k, true])];
};
export const nameKey = n => compact(n);   // the shared name key (scripts/names.mjs), no spaces
// nflverse combine results for a draft year, keyed like nameKey, with 40-time means by group
export async function fetchCombine(draftYear) {
  const r = await fetch('https://github.com/nflverse/nflverse-data/releases/download/combine/combine.csv', { headers: { 'user-agent': UA } });
  if (!r.ok) throw new Error(`combine ${r.status}`);
  const G = { QB: 'QB', RB: 'RB', FB: 'RB', WR: 'WR', TE: 'TE', OT: 'OL', OG: 'OL', OL: 'OL', C: 'OL', G: 'OL', T: 'OL', DE: 'EDGE', EDGE: 'EDGE', OLB: 'EDGE', DT: 'DL', DL: 'DL', NT: 'DL', ILB: 'LB', LB: 'LB', CB: 'CB', DB: 'CB', S: 'S', SAF: 'S', FS: 'S', SS: 'S' };
  const players = {}, by = {}, rows = csvRows(await r.text());
  // athletic testing (FV_ATH in fetch_cfb.mjs): speed score (weight x 200 / 40^4), vertical, broad, 3-cone and shuttle
  // (both reversed), each a z against every invitee at the position group since 2010; ath = the mean of 2+ of them
  const met = p => ({ spd: +p.forty && +p.wt ? +p.wt * 200 / (+p.forty) ** 4 : null, vert: +p.vertical || null, broad: +p.broad_jump || null, cone: +p.cone ? -p.cone : null, shut: +p.shuttle ? -p.shuttle : null });
  const pool = {};
  for (const p of rows) { const g = G[p.pos]; if (!g || +p.season < 2010) continue; for (const [k, v] of Object.entries(met(p))) if (v != null) (pool[g + k] ||= []).push(v); }
  const ms = Object.fromEntries(Object.entries(pool).map(([k, xs]) => { const m = xs.reduce((a, b) => a + b, 0) / xs.length; return [k, [m, Math.sqrt(xs.reduce((a, x) => a + (x - m) ** 2, 0) / xs.length) || 1]]; }));
  // centred on the mean tester at the group (players who run 2+ drills test above the invitee average), so a prospect
  // who skips the drills is neither helped nor hurt
  const athOf = (p, g) => { const zs = g ? Object.entries(met(p)).filter(([k, v]) => v != null && ms[g + k]).map(([k, v]) => (v - ms[g + k][0]) / ms[g + k][1]) : [];
    return zs.length >= 2 ? zs.reduce((a, b) => a + b, 0) / zs.length : null; };
  const tm = {};
  for (const p of rows) { const g = G[p.pos], a = +p.season >= 2010 ? athOf(p, g) : null; if (a != null) { (tm[g] ||= [0, 0])[0] += a; tm[g][1]++; } }
  for (const p of rows) {
    if (+p.season !== draftYear) continue;
    const g = G[p.pos] || null, forty = +p.forty || null, a = athOf(p, g);
    // measured height (inches) and weight: the position-change odds switch to them (fetch_cfb.mjs, position fit)
    const hm = /^(\d+)-(\d+)/.exec(p.ht || '');
    players[nameKey(p.player_name)] = { g, forty, school: p.school || null, ath: a != null ? Math.round((a - tm[g][0] / tm[g][1]) * 100) / 100 : null,
      ht: hm ? 12 * +hm[1] + +hm[2] : null, wt: +p.wt || null };
    if (g && forty) (by[g] ||= []).push(forty);
  }
  const groups = Object.fromEntries(Object.entries(by).map(([g, xs]) => { const m = xs.reduce((a, b) => a + b, 0) / xs.length; return [g, { mean: m, sd: Math.sqrt(xs.reduce((a, x) => a + (x - m) ** 2, 0) / xs.length) }]; }));
  return { n: Object.keys(players).length, players, groups };
}
const NEED_W = 0.45, NEED_MIN = 0.6;          // log-pick units per point of need (0-1, fetchNflNeeds): the worst room lets a team reach ~35%; a listed need is 0.6+
const QB_DUP_LN = 1.0, DUP_LN = 0.15, QB_BLOCK_LN = 0.8, RUN_LN = 0.15, MOVE_LN = 0.1;
const MOVE_COST = 1.5;                                                      // FV: the risk in a position change
const MOVE_GROUP = { IOL: 'OL', OT: 'OL', DL: 'DL', EDGE: 'EDGE', LB: 'LB', S: 'S', CB: 'CB', TE: 'TE', WR: 'WR' };   // ATH stays put
// Specialists (scripts/draft_replay7.py, nflverse 2010-25): kickers, punters and snappers aren't on the boards the
// mock reads, so they go at the slots history gives them: the i-th kicker taken in a draft goes, at the median, at
// SPEC_SLOT.K[i] (a draft with fewer than i kickers counts as undrafted), and the i-th best on our board (FV, then kick
// points) is the i-th taken. 2010-25: 1.9 kickers, 1.9 punters and .6 snappers a draft, 95% in rounds 4-7. In the
// 2020-25 replay this drafts 2 K and 2 P a year (real: 2.2 and 2.0) where the mock drafted none; long snappers aren't
// graded, and the median draft has none. A kicker need (SPEC_NEED_LN, fetchNflNeeds): teams whose kicker was 35+ or
// made under 80% of 15+ field goals the season before took one 10.5% of the time, the rest 3.4% (2010-25, z 2.9, a
// log ratio of 1.13, taken at .8 to shrink an in-sample fit); a punter 34+ didn't clear noise (9.6% vs 5.2%, z 1.2)
// The need is centred on the kicker takers: 65% of the teams that drafted one were flagged (20 of 31), so a flagged
// team gains SPEC_NEED_LN x .35 and the rest lose x .65, and kickers still go at their historical slots on average.
// The slots scale to the mock's draft (no compensatory picks: 224 of the 255 a draft had in 2015-25)
const SPEC_SLOT = { K: [160, 216.5], P: [172, 228] }, SPEC_NEED_LN = 0.8, SPEC_CENTER = 0.65, HIST_PICKS = 255;
// FCS (scripts/draft_replay7.py): 8.4 FCS players a draft went in 2021-25 (10.8 in 2015-25), 3.2% of the picks, 80%
// of them in rounds 4-7. Our FCS grades sit on a discounted scale (FCS NIL and FV are priced against FBS), so the
// predictive mock drafted none: there every FCS prospect's xPick moves by one common factor until the FCS share of
// the slots the draft fills matches history (FCS_SHARE). Final boards price the level already
// (scripts/draft_backtest.py: conference level adds nothing to a board rank), so the shift fixes our scale, not the
// market's; the conviction mock keeps our own grade. Draft% is left alone: its spread already sums to ~14 FCS
// draftees (the fall SD is wide), above history, so shifting it would overcount
const FCS_SHARE = 0.033;
function fcsShift(pool, n) {
  const fcs = pool.filter(p => p.div === 'FCS');
  const want = Math.round(FCS_SHARE * n);
  if (!fcs.length || !want) return 1;
  const inTop = f => pool.map(p => p.div === 'FCS' ? [p._x / f, 1] : [p._x, 0]).sort((a, b) => a[0] - b[0]).slice(0, n).reduce((c, x) => c + x[1], 0);
  if (inTop(1) >= want) return 1;
  let lo = 1, hi = 1e3;
  for (let i = 0; i < 40; i++) { const m = Math.sqrt(lo * hi); if (inTop(m) >= want) hi = m; else lo = m; }
  for (const p of fcs) p._x /= hi;
  return hi;
}
// the mock's prospect pool and each prospect's xPick (p._x, p._mRk), shared by mockDraft and draftOdds.
// opts.spec: kickers and punters join (the mock; Draft% gives them their own odds); opts.n: the slots the draft fills
function xPickPool(rows, P, mode = 'pred', opts = {}) {
  // blended: the geometric midpoint of the predictive and conviction slots
  if (mode === 'blend') {
    const cx = new Map(xPickPool(rows, P, 'conv', opts).map(p => [p, p._x]));
    const pool = xPickPool(rows, P, 'pred', opts);
    for (const p of pool) p._x = Math.sqrt(p._x * cx.get(p));
    return pool;
  }
  const specs = [];
  if (opts.spec) for (const [pos, slots] of Object.entries(SPEC_SLOT)) {
    const sp = rows.filter(p => p.draft27 && p.pos === pos && p.fv != null && p.elig >= 4).sort((a, b) => grade(b) - grade(a) || (b.kp ?? 0) - (a.kp ?? 0));
    sp.forEach((p, i) => { p._x = slots[i] != null ? slots[i] * (opts.n ?? HIST_PICKS) / HIST_PICKS : 1e4; p._mRk = null; specs.push(p); });
  }
  const done = pool => { if (mode === 'pred' && opts.n) P.fcsShift = fcsShift(pool, opts.n); return specs.length ? pool.concat(specs) : pool; };
  const conv = mode === 'conv';
  const pool = rows.filter(p => p.fv != null && p.draft27 && STARTERS[p.pos] && (p.elig >= 4 || grade(p) >= 45 || p.consRk != null));
  // model rank: draft value at the player's best spot, the round index from his FV tier. The conviction mock
  // (conv) ranks on the model's own grade: FV before the consensus blend (fvModel = fv - consAdj), with no
  // draft-market positional bump (P.value: what teams pay for a QB or EDGE early) and no market positional price
  // (mktPosAdj); positional worth stays in FV itself (FV_POS_VALUE, fetch_cfb.mjs, from NFL outcomes)
  const roundOf = fv => fv >= 60 ? 0 : fv >= 52 ? 1 : 2;
  const fvOf = p => conv ? gradeX(p) - (p.consAdj ?? 0) : grade(p);
  const draftValue = (p, pos, moved) => fvOf(p) + (p.plus ? 1 : 0) + (conv ? 0 : P.value[pos]?.[roundOf(grade(p))] ?? 0)
    + (moved ? -MOVE_COST : Math.min(0, (p.parts?.[7] ?? 0) * 12));
  for (const p of pool) {
    const alt = MOVE_GROUP[p.move];
    p._dv = Math.max(draftValue(p, p.pos, false), alt && alt !== p.pos ? draftValue(p, alt, true) : -Infinity);
  }
  const rank = () => [...pool].sort((a, b) => b._dv - a._dv || (b.comp ?? 0) - (a.comp ?? 0)).forEach((p, i) => { p._mRk = i + 1; });
  rank();
  if (conv) {
    // the model's board alone, through the same board-to-slot curve: consensus weight 0, no combine terms
    for (const p of pool) p._x = Math.exp(lnPickOf(p._mRk));
    return done(pool);
  }
  // positional price from the market: on 2020-25 final boards, position adds nothing to board rank (the league's
  // boards already price QB scarcity and RB discounts; scripts/draft_sim_backtest.py), so a position our model
  // ranks systematically above or below the consensus is our tilt, not information about where he'll go. Each
  // position's draft value is shifted until its consensus-ranked players sit, on average, as far from the
  // consensus in log rank as everyone else does (shrunk to 0 at MKT_POS_K players); FV and within-position order are untouched
  P.posAdj = mktPosAdj(pool, rank);
  return done(finishPool(pool, P));
}
const MKT_POS_K = 6, MKT_POS_TOP = 150, MKT_POS_ITER = 6;
function mktPosAdj(pool, rank) {
  const adj = {}, n = {}, ranked = pool.filter(p => p.consRk != null && p.consRk <= MKT_POS_TOP);
  if (ranked.length < 40) return adj;
  for (let it = 0; it < MKT_POS_ITER; it++) {
    // FV per log rank on the model board (slope of draft value on ln model rank)
    const xs = ranked.map(p => Math.log(p._mRk)), ys = ranked.map(p => p._dv), mx = xs.reduce((a, b) => a + b, 0) / xs.length, my = ys.reduce((a, b) => a + b, 0) / ys.length;
    const slope = -xs.reduce((a, x, i) => a + (x - mx) * (ys[i] - my), 0) / xs.reduce((a, x) => a + (x - mx) ** 2, 0);
    const gap = {}, all = ranked.map(p => Math.log(p._mRk / p.consRk)), mean = all.reduce((a, b) => a + b, 0) / all.length;
    ranked.forEach((p, i) => (gap[p.pos] ||= []).push(all[i] - mean));
    for (const [g, L] of Object.entries(gap)) {
      const d = slope * L.reduce((a, b) => a + b, 0) / L.length;
      adj[g] = (adj[g] || 0) + d; n[g] = L.length;
      for (const p of pool) if (p.pos === g) p._dv += d;
    }
    rank();
  }
  // the full shift closes the gap; small groups keep only their share of it
  for (const g of Object.keys(adj)) {
    const keep = n[g] / (n[g] + MKT_POS_K);
    for (const p of pool) if (p.pos === g) p._dv -= (1 - keep) * adj[g];
    adj[g] *= keep;
  }
  rank();
  return Object.fromEntries(Object.entries(adj).map(([g, v]) => [g, Math.round(v * 10) / 10]));
}
function finishPool(pool, P) {
  // both ranks are boards, so both go through the board-to-pick curve (BOARD_PICK); unranked players sit past
  // the consensus board's depth. The model's share is backtested: on the rebuilt 2020-23 boards (scripts/cfb_fv_refit.mjs
  // --mock, data/cfb_mock_weight_backtest.json), blending the model's order into DraftTek's final board cut the slot
  // error |ln pick - ln xPick| from .452 (board alone) to .433, best at a board weight of .75-.85 (chosen .80, .80,
  // .80, .75 leaving each draft out; every draft improved), which MARKET_W gives a fully covered prospect (.85)
  const depth = Math.max(50, ...pool.filter(p => p.consRk != null).map(p => p.consRk)) * UNRANKED_DEPTH;
  const lnPick = lnPickOf;
  // after the combine (nflverse combine.csv for the draft year, P.combine): no invite and 40 time, per the backtest
  const cmb = P.combine?.n >= 100 ? P.combine : null;
  for (const p of pool) {
    const ranked = p.consRk != null;
    const w = ranked ? MARKET_W.base + MARKET_W.perBoard * Math.sqrt(Math.min(1, (p.consN || 1) / CONS_BOARDS_N)) : MARKET_W.unranked;
    let l = w * lnPick(ranked ? p.consRk : Math.max(depth, p._mRk)) + (1 - w) * lnPick(p._mRk);
    if (cmb && ranked) {
      const c = cmb.players[nameKey(p.name)], g = c && cmb.groups[c.g];
      if (!c) l += BOARD_PICK.noCombine;
      else if (c.forty && g?.sd) l += BOARD_PICK.forty * (c.forty - g.mean) / g.sd;
    }
    p._x = Math.exp(l);
  }
  return pool;
}

// ---- Draft% ----------------------------------------------------------------------------------------
// The chance a 2027-eligible player is picked in the 2027 draft = P(declares) x P(selected | declares).
// Backtested on PFF's dated big boards (scripts/cfb_draft_pct_backtest.py, data/cfb_draft_pct_backtest.json):
// every version PFF kept for the 2020-26 drafts, September through April, against nflverse picks, with DraftTek's
// final 600-deep boards marking who declared.
//   selected: his real slot scatters around xPick on a log scale: Phi((ln cut - ln xPick) / sd), with the cut and
//     the SD fit on declared prospects by how far out the board was (DRAFT_SD, DRAFT_CUT): fall boards sd 1.28,
//     cut 344; Dec-Feb .72, 260; the final month .56, 265. The old flat .70 with a cut solved near 254 was right
//     for January and too sure in the fall. Ranked prospects (consensus) use the curve; the unranked share the
//     rest of the class's picks on a cutoff solved so the board sums to DRAFT_PICKS (a 257-pick draft less ~3% from
//     D2, D3 and abroad and ~3.8 kickers and punters), never kinder than the ranked one
//   declares: a logistic in ln xPick and age on draft day per class group (DECLARE), fit on the fall boards of the
//     NIL-era drafts (2024-25; scripts/cfb_declare_econ.py, data/cfb_declare_econ.json): ranked underclassmen
//     declared 94%, plain seniors 69%: the boards' class labels are year in school, as a plain Sr is here, and a
//     4th-year with eligibility left often stays now (Klubnik, Allar, Overton in 2025). Age is most of the stay-or-go
//     choice: a year older on draft day is +2.2 on the log odds for a senior (+.85 for an underclassman), the runway
//     the NFL pays for running out. Leave one NIL-era draft out, declare log loss .529 -> .379 (t -5.8, 4/4 draft x
//     class cells; over all five fall boards with an era flag, t -6.8, 10/10). Tested as the economic choice too and
//     failed: the log ratio of his expected rookie deal at xPick to the NIL he would draw by staying (t -.9 alone,
//     nothing over age), QB (t -1.4) and Power 4 (t -2.1 alone, nothing over age). Redshirt seniors and grads are
//     out of eligibility and go (their 51% on those boards was the COVID year, which ended with the 2025 season).
//     The 2026 draft can't be a third fold: PFF kept only its April board for it
//   whole chain, leave one draft out on the 2021-25 fall boards (701 prospects): log loss .474 (.506 without age,
//     .825 before either; t -2.9 for age, 5/5 drafts), Brier .155 (.169, .248)
//   kickers and punters: SPECIALISTS a year (nflverse 2015-26: K 1.83, P 2.0), spread over the draft-eligible
//     seniors at each in FV order on the same log-normal (FV is our grade there; the order, not the total, is untested)
// Draft-eligible players outside the mock's pool (underclassmen under FV 45 with no consensus rank) get 0,
// shown as <1%.
const DRAFT_PICKS = 246, SPECIALISTS = { K: 1.83, P: 2.0 };
// log odds a + b ln xPick + age x (age on draft day - age0), the age gap held to +-2 years; no age: the class mean
const DECLARE = { sr: { a: 5.007, b: -0.819, age: 2.219, age0: 22.42 }, under: { a: 6.91, b: -0.929, age: 0.85, age0: 21.66 } };
const DRAFT_SD = [[10, 0.56], [95, 0.72], [190, 1.28]];     // [days to the draft, SD], linear between, flat outside
const DRAFT_CUT = [[10, 265], [95, 260], [190, 344]];       // [days to the draft, cutoff pick] for ranked prospects
// the draft is the fourth Thursday of April (2024-26 all were)
const draftDay = y => { const d = new Date(Date.UTC(y, 3, 1)); d.setUTCDate(1 + (4 - d.getUTCDay() + 7) % 7 + 21); return d; };
const byDays = K => (asof = new Date(), year) => {
  const t = new Date(asof), y = year ?? (t.getUTCMonth() >= 4 ? t.getUTCFullYear() + 1 : t.getUTCFullYear());
  const days = Math.max(0, (draftDay(y) - t) / 864e5);
  if (days <= K[0][0]) return K[0][1];
  if (days >= K[K.length - 1][0]) return K[K.length - 1][1];
  const i = K.findIndex(k => k[0] > days);
  return K[i - 1][1] + (K[i][1] - K[i - 1][1]) * (days - K[i - 1][0]) / (K[i][0] - K[i - 1][0]);
};
export const draftSd = byDays(DRAFT_SD), draftCut = byDays(DRAFT_CUT);
// a redshirt senior or grad is out of eligibility (the COVID year that kept them in school ran out with the 2025 season)
export const declareOdds = (p, xPick, asof = new Date(), year) => {
  if (p.elig >= 5 || /^RS-Sr|Gr/.test(p.cls || '')) return 1;
  const d = DECLARE[p.elig >= 4 ? 'sr' : 'under'], a = p.age ?? p.ageEst;
  const t = new Date(asof), y = year ?? (t.getUTCMonth() >= 4 ? t.getUTCFullYear() + 1 : t.getUTCFullYear());
  const gap = a != null ? Math.max(-2, Math.min(2, a + Math.max(0, draftDay(y) - t) / 864e5 / 365.25 - d.age0)) : 0;
  return 1 / (1 + Math.exp(-(d.a + d.b * Math.log(xPick) + d.age * gap)));
};
// the likely entrants for a mock: a prospect more likely to stay in school than declare sits out, except that the
// group still sends its expected number (the sum of its odds), the best by xPick, so the class isn't drafted as if
// every 40% junior went back (declareOdds stays the per-player chance for the probabilistic mocks)
export function entrants(pool, P = DEFAULT_PRIORS) {
  const asof = P.asof || new Date();
  const unsure = pool.filter(p => p.draft27 && STARTERS[p.pos] && declareOdds(p, p._x, asof, P.draftYear) < 0.5).sort((a, b) => a._x - b._x);
  const n = Math.round(unsure.reduce((s, p) => s + declareOdds(p, p._x, asof, P.draftYear), 0));
  const back = new Set(unsure.slice(n));
  return back.size ? pool.filter(p => !back.has(p)) : pool;
}
// solve the log cutoff so sum p(lc) = n (p rising in lc)
const solveCut = (f, n) => { let lo = Math.log(1), hi = Math.log(1e5); for (let k = 0; k < 60; k++) { const m = (lo + hi) / 2; if (f(m).reduce((s, x) => s + x, 0) > n) hi = m; else lo = m; } return (lo + hi) / 2; };
export function draftOdds(rows, priors = DEFAULT_PRIORS) {
  const P = { ...DEFAULT_PRIORS, ...(priors || {}) };
  const asof = P.asof || new Date(), sd = draftSd(asof, P.draftYear), cut = draftCut(asof, P.draftYear);
  const pool = xPickPool(rows, P);
  for (const p of rows) if (p.draft27) p.draftP = 0;
  // ranked prospects on the backtested curve (DRAFT_CUT, DRAFT_SD); the rest of the class's picks go to the
  // unranked, on a cutoff solved so the whole board sums to DRAFT_PICKS (never kinder than the ranked one)
  const ranked = pool.filter(p => p.consRk != null), rest = pool.filter(p => p.consRk == null);
  const pr = p => declareOdds(p, p._x, asof, P.draftYear) * phiN((Math.log(cut) - Math.log(p._x)) / sd);
  const rSum = ranked.reduce((s, p) => s + pr(p), 0);
  const odds = lc => rest.map(p => declareOdds(p, p._x, asof, P.draftYear) * phiN((lc - Math.log(p._x)) / sd));
  let lcRest = rSum < DRAFT_PICKS ? solveCut(odds, DRAFT_PICKS - rSum) : -Infinity;
  if (lcRest > Math.log(cut) || !ranked.length) {      // too few ranked to fill the draft: one cutoff for everyone
    const all = lc => pool.map(p => declareOdds(p, p._x, asof, P.draftYear) * phiN((lc - Math.log(p._x)) / sd));
    lcRest = solveCut(all, DRAFT_PICKS);
    all(lcRest).forEach((x, i) => { pool[i].draftP = Math.round(x * 1000) / 1000; });
  } else {
    for (const p of ranked) p.draftP = Math.round(pr(p) * 1000) / 1000;
    odds(lcRest).forEach((x, i) => { rest[i].draftP = Math.round(x * 1000) / 1000; });
  }
  for (const p of pool) { delete p._dv; delete p._mRk; delete p._x; }
  for (const [pos, n] of Object.entries(SPECIALISTS)) {
    const sp = rows.filter(p => p.draft27 && p.pos === pos && p.fv != null && p.elig >= 4).sort((a, b) => grade(b) - grade(a) || (b.kp ?? 0) - (a.kp ?? 0));
    if (!sp.length) continue;
    const f = c => sp.map((p, i) => phiN((c - Math.log(i + 1)) / sd));
    f(solveCut(f, n)).forEach((x, i) => { sp[i].draftP = Math.round(x * 1000) / 1000; });
  }
  return { cut, cutRest: Math.round(Math.exp(lcRest)), sd: Math.round(sd * 100) / 100, ranked: Math.round(rSum) };
}

// the pick explained in scout shorthand: need, slot against market and model, position, traits, and the
// player's own strengths / concerns lines from the board. Every line is a template over the numbers
const TIER_NAME = { p: 'Platinum', g: 'Gold', s: 'Silver', b: 'Bronze' };
const ROLE_NAME = { every: 'every-down back', early: 'early-down back', third: '3rd-down back' };
const ordinal = n => { const t = n % 100 >= 11 && n % 100 <= 13 ? 'th' : ['th', 'st', 'nd', 'rd'][n % 10] || 'th'; return `${n}${t}`; };
function pickReport(k, { p, needs: scored, dup, room: ctxRoom = [] }, conv) {
  const needs = scored.map(([g]) => g), nk = k.group || k.pos, lines = [], ni = needs.indexOf(nk);
  // need: where the position ranks among the team's needs, and who's in the room now
  let need = ni === 0 ? `${nk} #1` : ni > 0 ? `${nk} #${ni + 1} (top: ${needs[0]})`
    : `${nk} not a need${needs.length ? ` (top: ${needs.slice(0, 3).join(', ')})` : ''}; BPA`;
  if (dup > 0) need += `; ${ordinal(dup + 1)} ${k.pos} of the draft`;
  lines.push(['Need', need + '.']);
  // every need the team has left at this pick (NEED_MIN and up), with its weight: 1 = an empty room
  if (scored.length) lines.push(['Needs', scored.map(([g, v]) => `${g} ${v.toFixed(2).replace(/^0/, '')}`).join(', ') + '.']);
  if (ctxRoom.length) lines.push(['Room', ctxRoom.join('; ') + '.']);
  // trade: a move up (the pick and what it cost on the market value chart) or a pick acquired moving down
  const td = k.trade;
  const c3 = x => x >= 0.1 ? x.toFixed(2) : x.toFixed(3);
  if (td?.up) lines.push(['Trade', `Up #${td.gave[0]} to #${k.pick} with ${td.with}; sends ${td.gave.map(x => `#${x}`).join(', ')}${(td.future || []).map(f => `, ${f.year} R${f.round}${f.from !== k.team ? ` (${f.from})` : ''}`).join('')}; chart ${c3(td.chart[1])} for ${c3(td.chart[0])}${k.name === td.target ? '; target' : ''}.`]);
  else if (td) lines.push(['Trade', `Via ${td.with} (trade down from #${td.gave[0]}).`]);
  // a pick already traded (before the draft, a real deal)
  if (k.via) lines.push(['Pick', `${k.via} R${k.round}${k.cond ? ' (conditional)' : ''}; to ${k.viaTo}${k.deal ? `; ${k.deal} trade` : '; pick trade'}.`]);
  // slot: expected pick, market, our board
  let slot = conv ? `model board #${k.mRk} (model FV ${k.fvM}), pick ${k.pick}; cons ${k.cons != null ? `#${k.cons}` : 'unranked'}; BB #${k.bb}`
    : `xPick ${k.xPick}, pick ${k.pick}; cons ${k.cons != null ? `#${k.cons} (${p.consN || 1}/10 boards)` : 'unranked'}; BB #${k.bb}`;
  if (conv) { if (k.pick < k.mRk - 5) slot += `; ${k.mRk - k.pick} ahead of model rank${ni >= 0 ? ' (need)' : ''}`; }
  else if (k.pick < 0.67 * k.xPick && k.pick < k.xPick - 5) slot += `; ${k.xPick - k.pick} ahead of xPick${ni >= 0 ? ' (need)' : ''}`;
  else if (!conv && k.pick > 1.5 * k.xPick && k.pick > k.xPick + 5) slot += `; ${k.pick - k.xPick} past xPick`;
  if (k.cons != null && k.bb >= 2 * k.cons && k.bb - k.cons >= 10) slot += `; cons ${k.bb - k.cons} higher than BB`;
  else if (k.cons != null && k.cons >= 2 * k.bb && k.cons - k.bb >= 10) slot += `; BB ${k.cons - k.bb} higher than cons`;
  lines.push(['Slot', slot + '.']);
  // position
  if (k.movedFrom) lines.push(['Position', `${k.movedFrom} to ${k.pos}: ${k.moveWhy}.`]);
  else if (p.move) lines.push(['Position', `${k.pos}, could move to ${p.move}: ${p.moveWhy}.`]);
  // traits
  const tr = [p.arch ? `${p.arch[0].toUpperCase()}${p.arch.slice(1)}` : null, ROLE_NAME[p.rbRole] ? `${ROLE_NAME[p.rbRole]}` : null,
    p.ht || p.wt ? `${p.ht || '?'}, ${p.wt || '?'} lb${p.wtProj && p.wt && p.wtProj - p.wt >= 3 ? ` (~${p.wtProj} by 22)` : ''}` : null].filter(Boolean);
  if (tr.length) lines.push(['Type', tr.join('. ') + '.']);
  if (p.badges?.length) lines.push(['Badges', p.badges.slice(0, 4).map(b => `${TIER_NAME[b[1]] || ''} ${b[0]} (${ordinal(b[2])} pct, ${b[3]})`.trim()).join('; ') + '.']);
  const rp = p.report || {};
  return { lines, role: rp.role || null, plus: (rp.plus || []).slice(0, 4), minus: (rp.minus || []).slice(0, 3) };
}
// Trades: pick values on Massey & Thaler's market curve, fit to what NFL teams actually paid in pick-for-pick
// trades: v(pick) = exp(-.148 (pick - 1)^.698), so #1 = 1, #10 = .45, #32 = .20, #64 = .07. At each pick, every
// team with a pick up to the round's window (TRADE_WINDOW) later asks what its target (its best player now) is
// worth over its fallback (its best left at its own pick), times the chance a team picking in between takes him:
// each of those teams picks by a logit on its own utilities (TRADE_LOGIT), so a target nobody ahead wants isn't
// worth moving up for, and teams that love a player pay over the chart for him (TRADE_KAPPA; trade-ups lose value
// on the chart, Massey & Thaler). It offers its own pick plus the smallest later pick(s) that cover the chart gap
// plus TRADE_PREMIUM, and when its picks left this year can't, picks in next year's draft at FUTURE_DISC of a
// same-round pick now. Only picks a team holds go: this year's after the real trades (applyNflTrades) and the mock's
// own, next year's after the real trades already made for that draft (P.futureTrades, Wikipedia). The team on the
// clock never moves back from the player it would take itself, and otherwise takes the deal when the extra value
// beats what it loses by moving back, assuming the team moving up takes its target. The trade with the biggest net
// gain, as a share of the pick's value, goes through when it clears the round's bar, at most one trade-up per team
// a round. Division rivals trade with each other about half as often as their share of nearby picks implies
// (nflverse trades, draft-day trade-ups 2010-25: 18 in division vs 45 expected; rounds 1-2, 9 vs 18.6;
// scripts/nfl_trade_history.py), so a deal inside a division counts its gain at TRADE_DIV.
// Every round trades (scripts/draft_replay7.py, nflverse draft-day trade-ups 2015-25, by the round of the pick moved
// up to): 4.9, 6.8, 5.6, 5.5, 4.9, 2.4 and .9 a year (TRADE_PER_ROUND), 31 in all, with a median jump of 5, 7, 11,
// 13.5, 13, 14.5 and 17 slots (the windows reach past the 75th percentile). A quarter of trade-ups send a pick in a
// later draft (90% in round 7, where teams have little left that year); on the chart, a next-year pick was paid as
// .48 of a same-round pick now (median of 70 deals; one round later on the chart is .30-.51), FUTURE_DISC. Through
// PR #222 the mock traded in rounds 1-2 only: the trade model was tuned on first- and second-round history, where
// chart values are reliable, and its bar was an absolute chart margin that late picks (worth .01 or less) never clear.
const mtv = pick => Math.exp(-0.148 * Math.max(0, pick - 1) ** 0.698);
const TRADE_WINDOW = [20, 20, 25, 30, 30, 35, 35], TRADE_PREMIUM = 0.05, TRADE_MARGIN = 0.04, TRADE_EXTRA = [3, 2, 2, 2, 2, 2, 2];   // bar: net gain / the pick's value; extra picks sent at most (2015-25 median: 3 pieces in round 1, 2 later)
const TRADE_DIV = 0.48, TRADE_LOGIT = 6, TRADE_KAPPA = 3, FUTURE_DISC = 0.48;
const futV = r => FUTURE_DISC * mtv(16 + 32 * (r - 1));    // a next-year pick: the round's middle pick, discounted
// the most any team's utility sits above -ln xPick (a need, the kicker need): the best player for a team can't sit
// further down the xPick order than that, so the scans stop there
const MAX_BONUS = Math.max(NEED_W, SPEC_NEED_LN * (1 - SPEC_CENTER)) + 1e-9;
// UDFA signings: after round 7 the best prospects left (by xPick) sign where they can play: each, in order, goes
// to the team with the biggest need left at his room after the draft (the picks fill it as in the mock), less what it
// already added there in the draft and in this list (UDFA_CROWD per signing). A projection from need, not backtested:
// the replay's needs need contract data the public file has only through 2022
const UDFA_N = 32, UDFA_CROWD = 0.25;
function mockDraftOnce(rows, tank, rounds, priors, margins, mode = 'pred', noise = null) {
  const conv = mode === 'conv';
  const P = { ...DEFAULT_PRIORS, ...(priors || {}) };
  const order = tank.order.filter(o => o.round <= rounds).map(o => ({ ...o }));
  // the modal mock drafts the likely entrants (entrants); a simulated draft (mockSims) starts from the whole pool and each
  // prospect declares or stays at his own odds (declareOdds), his xPick moved by a board shock held for the whole
  // draft; kickers and punters keep their slots
  const all = xPickPool(rows, P, mode, { spec: true, n: order.length });
  const pool = noise ? all : entrants(all, P);
  if (noise) for (const p of pool) {
    if (SPEC_SLOT[p.pos]) continue;
    if (noise.rng() > declareOdds(p, p._x, P.asof || new Date(), P.draftYear)) p._x = 1e9;
    else p._x *= Math.exp(noise.sp * noise.normal());
  }
  const byX = [...pool].sort((a, b) => a._x - b._x);
  const taken = new Set(), teamPos = {}, picks = [], roundCount = {}, ctx = [], teamNeed = {}, tradedUp = new Set(), deals = [];
  // next year's picks each team holds: its own seven, less and plus the real trades already made for that draft
  const fut = {};
  for (const t of Object.keys(tank.teams || {})) fut[t] = [1, 2, 3, 4, 5, 6, 7].map(r => ({ round: r, from: t }));
  for (const t of P.futureTrades || []) {
    const i = (fut[t.from] || []).findIndex(x => x.round === t.round && x.from === t.from) ?? -1;
    const j = i >= 0 ? i : (fut[t.from] || []).findIndex(x => x.round === t.round);
    if (j >= 0 && fut[t.to]) fut[t.to].push(fut[t.from].splice(j, 1)[0]);
  }
  const needOf = team => {
    if (teamNeed[team]) return teamNeed[team];
    const tn = Object.fromEntries((tank.needs?.[team] || []).map(n => [n.group, { score: Math.min(1, n.score), room: n.room || [] }]));
    if (tn.OL && !tn.OT) for (const k of ['OT', 'G', 'C']) tn[k] = { ...tn.OL };   // needs pulled before the line was split
    delete tn.OL;
    return teamNeed[team] = tn;
  };
  const needList = tn => Object.entries(tn).filter(([, n]) => n.score >= NEED_MIN).sort((a, b) => b[1].score - a[1].score).map(([g]) => g);
  // a team's utility for a player at a spot, in log-pick units (higher = better)
  // nk: the NFL room the pick fills (the position, or for a lineman OT, G or C)
  const util = (team, round, p, pos, moved, nk = pos) => {
    const tn = needOf(team), pr = P.perRound[pos], ri = Math.min(round, pr?.length || 3) - 1, spec = !!SPEC_SLOT[pos];
    const dup = (teamPos[team] || []).filter(x => x === pos).length * (pos === 'QB' || spec ? QB_DUP_LN : DUP_LN);   // a second QB (or kicker) in one draft is rare
    const exp = pr?.[ri] ?? 3, ran = (roundCount[round]?.[pos] || 0);
    // position runs are market behaviour (boards drain a position): the conviction mock ignores them
    const cap = Math.max(1, Math.round(exp * 1.25)), run = !conv && ran >= cap ? RUN_LN * (mode === 'blend' ? 0.5 : 1) * (ran - cap + 1) : 0;
    const qbBlock = pos === 'QB' && (tn.QB?.score ?? 0) < NEED_MIN ? (round <= 3 ? QB_BLOCK_LN : 0) : 0;   // a set QB room: no early QB
    const need = pos === 'K' ? SPEC_NEED_LN * ((tn.K?.score ?? SPEC_CENTER) - SPEC_CENTER) : spec ? 0 : NEED_W * (tn[nk]?.score ?? 0);
    return -Math.log(p._x) + need - dup - run - qbBlock - (moved ? MOVE_LN : 0);
  };
  // a player's best fit for a team (over his position, a projected move and, for a lineman, the OL rooms)
  const fitFor = (team, round, p) => {
    let best = null;
    const alt = MOVE_GROUP[p.move];
    for (const [pos, moved] of [[p.pos, false], ...(alt && alt !== p.pos ? [[alt, true]] : [])]) {
      for (const [nk, mv] of pos === 'OL' ? olRooms(p).map(([k, m]) => [k, m || moved]) : [[pos, moved]]) {
        const v = util(team, round, p, pos, mv, nk);
        if (!best || v > best.v) best = { p, pos, nk, v, ol: pos === 'OL' && mv && !moved };
      }
    }
    return best;
  };
  // a team's best available player; gone = players assumed taken first (the market's top n before its pick).
  // The scan runs down the xPick order and stops once no player further down can beat the best so far (MAX_BONUS)
  const bestFor = (team, round, gone = null) => {
    let best = null;
    for (const p of byX) {
      if (taken.has(p) || gone?.has(p)) continue;
      if (best && -Math.log(p._x) + MAX_BONUS < best.v) break;
      const f = fitFor(team, round, p);
      if (!best || f.v > best.v) best = f;
    }
    return best;
  };
  // a team's pick as a logit over its utilities (log-pick units, so a player it values at slot 10 is twice as
  // likely as one at slot 20): each player's weight, their sum, and its likeliest pick (which joins `gone`)
  const takeDist = (team, round, gone) => {
    let sum = 0, best = null; const w = new Map();
    for (const p of byX) {
      if (taken.has(p) || gone.has(p)) continue;
      if (best && -Math.log(p._x) + MAX_BONUS < best.v - 2) break;    // e^-12 of the top: nothing
      const f = fitFor(team, round, p), e = Math.exp(TRADE_LOGIT * f.v);
      sum += e; w.set(p, e);
      if (!best || f.v > best.v) best = f;
    }
    return { w, sum, best };
  };
  const slotV = u => mtv(Math.max(1, Math.exp(-u)));    // a utility as the value of the slot it's worth
  const marketTop = n => { const s = new Set(); for (const p of byX) { if (s.size >= n) break; if (!taken.has(p)) s.add(p); } return s; };
  // a simulated pick: every utility plus Gumbel noise at the round's scale (the scan stops where even a large draw,
  // 8 scales, can't lift a player past the best so far)
  const noisyBest = (team, round) => {
    const b = noise.k * noise.beta[round === 1 ? 0 : round <= 3 ? 1 : 2];
    let best = null;
    for (const p of byX) {
      if (taken.has(p)) continue;
      if (best && -Math.log(p._x) + MAX_BONUS + 8 * b < best.v) break;
      const f = fitFor(team, round, p); f.v += b * noise.gumbel();
      if (!best || f.v > best.v) best = f;
    }
    return best;
  };
  for (let i = 0; i < order.length; i++) {
    let o = order[i];
    // trade-up offers for this pick (none in a simulated draft: the sims run on the real order)
    if (!o.trade && !noise) {
      const here = bestFor(o.team, o.round), W = TRADE_WINDOW[o.round - 1] ?? 35;
      // the teams picking from here on, each by its logit, each taking its likeliest player before the next picks
      const dist = [], ahead = new Set();
      for (let k = i; k < order.length && order[k].pick - o.pick <= W; k++) {
        const d = takeDist(order[k].team, order[k].round, ahead); dist.push({ ...d, ahead: new Set(ahead) });
        if (d.best) ahead.add(d.best.p);
      }
      let deal = null;
      for (let j = i + 1; j < order.length && order[j].pick - o.pick <= W; j++) {
        const s = order[j], S = s.team;
        if (S === o.team || s.trade || tradedUp.has(S + '|' + o.round) || deal?.team === S) continue;
        const want = bestFor(S, o.round);
        if (!want) continue;
        // the team on the clock wants the same player: it won't move back and hand him over
        if (here?.p === want.p) continue;
        // S moves up only for the risk that a team picking before s takes its target
        let safe = 1;
        for (let k = i; k < j; k++) {
          const d = dist[k - i]; if (!d || d.ahead.has(want.p)) break;
          safe *= 1 - (d.w.get(want.p) ?? 0) / (d.sum || 1);
        }
        const gone = new Set(dist[j - i]?.ahead ?? []); gone.add(want.p);
        const alt = bestFor(S, s.round, gone);
        if (!alt) continue;
        const gain = TRADE_KAPPA * (1 - safe) * (slotV(want.v) - slotV(alt.v));
        // payment: S's pick plus its smallest later pick(s) this year covering the chart gap plus the premium; when
        // those can't, next year's picks (FUTURE_DISC) join
        const owe = (mtv(o.pick) - mtv(s.pick)) * (1 + TRADE_PREMIUM);
        const later = order.slice(j + 1).filter(x => x.team === S && !x.trade).map(x => ({ o: x, v: mtv(x.pick) }));
        const pay = items => {
          const one = items.filter(x => x.v >= owe).sort((a, b) => a.v - b.v)[0];
          if (one) return [one];
          const sent = []; let sum = 0;
          for (const x of [...items].sort((a, b) => !a.f - !b.f || b.v - a.v)) { if (sum >= owe) break; sent.push(x); sum += x.v; }   // this year's first
          return sum >= owe && sent.length <= (TRADE_EXTRA[o.round - 1] ?? 2) ? sent : null;
        };
        const sent = pay(later) || pay([...later, ...(fut[S] || []).map(f => ({ f, v: futV(f.round) }))]);
        if (!sent) continue;
        const paid = sent.reduce((a, x) => a + x.v, 0);
        // the team on the clock: what it gives up by moving back to s, against what it's paid on top
        // (the picks between go to the market's top players, and S takes its target)
        const mt = marketTop(j - i - 1); mt.add(want.p);
        const tLoss = here ? slotV(here.v) - slotV((bestFor(o.team, s.round, mt) || here).v) : 0;
        const sameDiv = tank.teams?.[S]?.div && tank.teams[S].div === tank.teams?.[o.team]?.div;
        const net = (gain - paid) * (sameDiv ? TRADE_DIV : 1) / mtv(o.pick);
        if (paid - Math.max(0, tLoss) < 0 || net <= (margins[o.round] ?? TRADE_MARGIN)) continue;
        if (!deal || net > deal.net) deal = { team: S, j, sent, net, wantName: want.p.name };
      }
      if (deal) {
        const s = order[deal.j], T = o.team, TName = o.teamName, SName = s.teamName;
        const cur = deal.sent.filter(x => x.o).map(x => x.o), futs = deal.sent.filter(x => x.f).map(x => x.f);
        const give = [s, ...cur];
        tradedUp.add(deal.team + '|' + o.round); deals.push({ round: o.round, net: deal.net });
        for (const x of give) { x.from = x.from || x.team; x.team = T; x.teamName = TName; x.trade = { with: deal.team, up: false, gave: [o.pick] }; }
        for (const f of futs) { fut[deal.team].splice(fut[deal.team].indexOf(f), 1); (fut[T] ||= []).push(f); }
        const fy = (P.draftYear ?? SEASON + 1) + 1;
        o.trade = { with: T, up: true, gave: give.map(x => x.pick), future: futs.map(f => ({ year: fy, round: f.round, from: f.from })),
          chart: [Math.round(1e4 * mtv(o.pick)) / 1e4, Math.round(1e4 * deal.sent.reduce((a, x) => a + x.v, mtv(s.pick))) / 1e4], target: deal.wantName };
        o.from = o.from || T; o.team = deal.team; o.teamName = SName;
      }
    }
    o = order[i];
    const tn = needOf(o.team), needs = needList(tn);
    const best = noise ? noisyBest(o.team, o.round) : bestFor(o.team, o.round);
    if (!best) break;
    const { p: pl, pos: bestPos, nk } = best, ni = needs.indexOf(nk);
    if (noise) {
      taken.add(pl); (teamPos[o.team] ||= []).push(bestPos);
      (roundCount[o.round] ||= {})[bestPos] = (roundCount[o.round][bestPos] || 0) + 1;
      if (tn[nk]) tn[nk].score *= SPEC_SLOT[nk] ? 0 : 1 - Math.max(0.15, 1 - 0.13 * Math.log(o.pick)) / (NFL_STARTERS[nk] || 2);
      picks.push({ pick: o.pick, round: o.round, team: o.team, key: pl.name + '|' + pl.team });
      continue;
    }
    taken.add(pl); (teamPos[o.team] ||= []).push(bestPos);
    (roundCount[o.round] ||= {})[bestPos] = (roundCount[o.round][bestPos] || 0) + 1;
    const moved = bestPos !== pl.pos;
    ctx.push({ p: pl, needs: needs.map(g => [g, tn[g].score]), room: tn[nk]?.room || [], score: tn[nk]?.score ?? null, dup: (teamPos[o.team] || []).filter(x => x === bestPos).length - 1 });
    // the pick joins the room: his draft capital fills part of the need for the team's later picks
    if (tn[nk]) tn[nk].score *= SPEC_SLOT[nk] ? 0 : 1 - Math.max(0.15, 1 - 0.13 * Math.log(o.pick)) / (NFL_STARTERS[nk] || 2);
    picks.push({ pick: o.pick, round: o.round, team: o.team, teamName: o.teamName, from: o.from, comp: o.comp, trade: o.trade || null,
      via: o.via || null, viaTo: o.dealTo || null, deal: o.deal || null, cond: o.cond || null,
      name: pl.name, pos: bestPos, group: nk, spot: moved ? null : best.ol ? nk : olSpot(pl.spot), movedFrom: moved ? pl.pos : null, moveWhy: moved ? pl.moveWhy : null,
      school: pl.team, logo: pl.logo, fv: pl.fv, plus: pl.plus, fcs: pl.div === 'FCS' || null,
      cls: pl.cls, age: pl.age ?? pl.ageEst, ageEst: pl.age == null, ovr: pl.ovr, need: ni >= 0 ? `need #${ni + 1}` : null,
      cons: pl.consRk ?? null, xPick: Math.round(pl._x), ...(conv ? { fvM: Math.round(meanAt(pl, gradeX(pl) - (pl.consAdj ?? 0))), mRk: pl._mRk } : {}) });
  }
  if (noise) { for (const p of pool) { delete p._dv; delete p._mRk; delete p._x; } return { picks }; }
  // UDFA signings: the best left, each to the team with the most room for him (UDFA_*)
  const signed = {}, udfa = [];
  for (const p of byX) {
    if (udfa.length >= UDFA_N) break;
    if (taken.has(p) || p._x >= 1e4 || p.draft27 !== true) continue;
    const pos = p.pos, nk = pos === 'OL' ? olRooms(p)[0]?.[0] || 'G' : pos;
    let best = null;
    for (const t of Object.keys(tank.teams || {})) {
      const tn = needOf(t), drafted = (teamPos[t] || []).filter(x => x === pos).length, adds = (signed[t] || []).filter(x => x === pos).length;
      const v = (tn[nk]?.score ?? 0) - UDFA_CROWD * (drafted + adds) - 0.05 * (signed[t]?.length || 0);
      if (!best || v > best.v) best = { t, v, need: tn[nk]?.score ?? 0, drafted };
    }
    if (!best) break;
    (signed[best.t] ||= []).push(pos);
    const tn = needOf(best.t); if (tn[nk]) tn[nk].score *= 1 - 0.15 / (NFL_STARTERS[nk] || 1);
    udfa.push({ rank: udfa.length + 1, team: best.t, teamName: tank.teams[best.t]?.name || best.t, name: p.name, pos, group: nk, spot: olSpot(p.spot),
      school: p.team, logo: p.logo, fv: p.fv, plus: p.plus, fcs: p.div === 'FCS' || null, cls: p.cls, xPick: Math.round(p._x), cons: p.consRk ?? null,
      why: `${nk} need ${best.need.toFixed(2)}${best.drafted ? `, ${best.drafted} ${pos} drafted` : ', none drafted'}` });
  }
  // where each pick sits on our draft-eligible big board, by FV (positive = taken earlier than we have him);
  // reach and value come from the other mock (mockDrafts)
  const bigBoard = [...pool].sort((a, b) => b.fv - a.fv || (b.fvx ?? b.fv) - (a.fvx ?? a.fv) || (b.comp ?? 0) - (a.comp ?? 0));
  const at = new Map(bigBoard.map((p, i) => [p.name + '|' + p.team, i + 1]));
  for (const k of picks) { k.bb = at.get(k.name + '|' + k.school); k.reach = k.bb - k.pick; }
  // one line per trade for the GFX's trade list (numbers first): a projected trade on every pick in it, keyed by the
  // pick moved up to; a real one (already traded) on its pick
  const byPick = new Map(picks.map(k => [k.pick, k])), cv = x => x >= 0.1 ? x.toFixed(2).replace(/^0/, '') : x.toFixed(3).replace(/^0/, '');
  const futTxt = (t, by) => (t.future || []).map(f => ` + ${f.year} R${f.round}${f.from !== by ? ` (${f.from})` : ''}`).join('');   // (from): a pick it had acquired
  for (const k of picks) {
    if (k.trade) {
      const up = byPick.get(k.trade.up ? k.pick : k.trade.gave[0]), t = up?.trade;
      if (t?.up) {
        k.tradeKey = up.pick;
        k.tradeLine = `#${up.pick} ${up.team} up from #${t.gave[0]} with ${t.with}: sends ${t.gave.map(x => `#${x}`).join(' + ')}${futTxt(t, up.team)} (${cv(t.chart[1])}) for #${up.pick} (${cv(t.chart[0])}); takes ${up.name} ${up.pos}${t.target && t.target !== up.name ? `, target ${t.target}` : ''}`;
      }
    }
    if (k.via) k.viaLine = `#${k.pick} ${k.via} R${k.round} (${cv(mtv(k.pick))}) to ${k.viaTo}${k.cond ? ', conditional' : ''}${k.deal ? `; ${k.deal} trade` : '; pick trade'}${k.viaTo !== k.team ? `; to ${k.team} by projected trade` : ''}; takes ${k.name} ${k.pos}`;
  }
  picks.forEach((k, i) => { k.rep = pickReport(k, ctx[i], conv); });
  // shown as DT: the model keys interior linemen as DL; on the site DL is the whole line (DT + EDGE)
  const dt = x => typeof x === 'string' ? x.replace(/\bDL\b/g, 'DT') : x;
  for (const k of picks) {
    for (const f of ['pos', 'group', 'movedFrom', 'moveWhy', 'need', 'tradeLine', 'viaLine']) k[f] = dt(k[f]);
    k.rep.lines = k.rep.lines.map(([h, t]) => [h, dt(t)]); k.rep.plus = k.rep.plus.map(dt); k.rep.minus = k.rep.minus.map(dt); k.rep.role = dt(k.rep.role);
  }
  for (const k of udfa) for (const f of ['pos', 'group', 'why']) k[f] = dt(k[f]);
  for (const p of pool) { delete p._dv; delete p._mRk; delete p._x; }
  return { picks, deals, udfa };
}
// The trade bar per round: when a board throws up more deals than the draft-day average (TRADE_PER_ROUND,
// 2015-25 trade-ups by round, scripts/draft_replay7.py), the round's bar rises and the mock re-runs, bisecting until
// the count is within one of the average; with fewer, it falls (rounds 1-2 never below TRADE_MARGIN; later rounds as
// low as TRADE_FLOOR, a trade-up that loses up to a third of the pick's value on the chart: late-round players sit
// close together on any board, and teams still move up for the one they want, overpaying on the chart as Massey and
// Thaler found), so the count tracks history however the board shifts.
const TRADE_PER_ROUND = [5, 7, 6, 5, 5, 2, 1], TRADE_FLOOR = -0.33;
export function mockDraft(rows, tank, rounds = 7, priors = DEFAULT_PRIORS, mode = 'pred') {
  const margins = {}, lo = {}, hi = {};
  let out;
  for (let it = 0; it < 10; it++) {
    out = mockDraftOnce(rows, structuredClone(tank), rounds, priors, margins, mode);
    let again = false;
    TRADE_PER_ROUND.slice(0, rounds).forEach((n, ri) => {
      const r = ri + 1, nets = out.deals.filter(d => d.round === r).map(d => d.net).sort((a, b) => b - a), m = margins[r] ?? TRADE_MARGIN;
      if (nets.length > n + 1 || (nets.length > n && margins[r] == null)) {
        lo[r] = m; margins[r] = hi[r] != null ? (m + hi[r]) / 2 : (nets[n - 1] + nets[n]) / 2; again = true;
      } else if (nets.length < n - 1 && (margins[r] != null || r > 2) && m > TRADE_FLOOR + 0.01) {
        hi[r] = m; margins[r] = (m + (lo[r] ?? (r > 2 ? TRADE_FLOOR : TRADE_MARGIN))) / 2; again = true;
      }
    });
    if (!again) break;
  }
  out.picks.udfa = out.udfa;
  return out.picks;
}
// Probabilistic mock (mockSims): the predictive mock run SIMS times with noise, for each prospect's chance to go in
// round 1, his 80% pick range and his likeliest team. Fit on the 2020-25 drafts (scripts/mock_noise_backtest.py,
// data/cfb_mock_noise.json): each team's pick as a logit over its mock utilities (Gumbel noise), the scale by round
// (beta .40 in round 1, .53 in rounds 2-3, .63 later; held out, by round beats one scale, t 5.1, 6/6 drafts, and the
// mock's utilities beat board order alone, t 5.4, 6/6), replayed in the real order with the real picks before each.
// Simulating whole drafts from the final boards, P(round 1) was best with a board shock (each prospect's ln xPick
// moved once a draft, sd .5) and the pick noise at half its scale: log loss .0843 against .0834 for the Draft% curve
// at its final-month sd (t 1.1, a tie; 80% pick ranges held 88% of real picks). Before the final board the shock
// widens by the board's own movement from now to April (DRAFT_SD: sd^2 = .5^2 + draftSd(today)^2 - .56^2, about 1.25
// in October), and each prospect declares at declareOdds, so the sims and Draft% agree on who goes. The sims run on
// the real order (real trades in, no projected ones); the headline mock stays the modal one.
const MOCK_NOISE = { beta: [0.4, 0.525, 0.625], sp: 0.5, k: 0.5, sims: 200 };
const mulberry = seed => () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
export function mockSims(rows, tank, rounds = 7, priors = DEFAULT_PRIORS, sims) {
  const P = { ...DEFAULT_PRIORS, ...(priors || {}) }, M = { ...MOCK_NOISE, ...(P.noise || {}) };
  const rng = mulberry(20270429), n = sims ?? M.sims;
  const normal = () => Math.sqrt(-2 * Math.log(1 - rng())) * Math.cos(2 * Math.PI * rng());
  const gumbel = () => -Math.log(-Math.log(1 - rng() * (1 - 1e-12)));
  const sp = Math.sqrt(M.sp ** 2 + Math.max(0, draftSd(P.asof || new Date(), P.draftYear) ** 2 - DRAFT_SD[0][1] ** 2));
  const noise = { rng, normal, gumbel, sp, beta: M.beta, k: M.k };
  const by = new Map(), R1 = tank.order.filter(o => o.round === 1).length;
  for (let s = 0; s < n; s++) {
    for (const k of mockDraftOnce(rows, tank, rounds, P, {}, 'pred', noise).picks) {
      const e = by.get(k.key) || by.set(k.key, { picks: [], teams: {} }).get(k.key);
      e.picks.push(k.pick); e.teams[k.team] = (e.teams[k.team] || 0) + 1;
    }
  }
  const players = {};
  for (const [key, e] of by) {
    if (e.picks.length < 0.01 * n) continue;
    const ps = e.picks.sort((a, b) => a - b), q = f => { const i = Math.floor(f * n); return i < ps.length ? ps[i] : null; };
    const [tm, c] = Object.entries(e.teams).sort((a, b) => b[1] - a[1])[0];
    players[key] = { r1: Math.round(ps.filter(x => x <= R1).length / n * 100) / 100, dr: Math.round(ps.length / n * 100) / 100,
      lo: q(0.1), hi: q(0.9), tm, tp: Math.round(c / n * 100) / 100 };
  }
  return { sims: n, sp: Math.round(sp * 100) / 100, players };
}
// Cross-grading: a mock's picks are graded by another mock's slot for the same player (undrafted in it: GRADE_UND,
// the backtests' undrafted slot). A pick the other mock makes GRADE_RATIO times later or more, and GRADE_SPOTS or more
// later (half a round, so the top picks aren't flagged on small gaps), is a reach; the mirror, taken that much later
// than the other mock has him, is a value. Predictive and conviction grade each other (low on predictive and high on
// conviction: a reach in the conviction mock and a value in the predictive one; the reverse the other way); the
// blended mock is graded by both, each label naming its grader.
const GRADE_RATIO = 2.5, GRADE_SPOTS = 16, GRADE_UND = 290;
const MOCK_NAME = { pred: 'Predictive', blend: 'Blended', conv: 'Conviction' };
export function mockDrafts(rows, tank, rounds = 7, priors = DEFAULT_PRIORS) {
  const M = Object.fromEntries(['pred', 'blend', 'conv'].map(m => [m, mockDraft(rows, tank, rounds, priors, m)]));
  const key = k => k.name + '|' + k.school;
  const slots = Object.fromEntries(Object.entries(M).map(([m, P]) => [m, new Map(P.map(k => [key(k), k.pick]))]));
  const GRADERS = { pred: ['conv'], conv: ['pred'], blend: ['pred', 'conv'] };
  for (const [m, P] of Object.entries(M)) for (const k of P) {
    k.slots = {}; k.grades = [];
    for (const b of Object.keys(M)) if (b !== m) k.slots[b] = slots[b].get(key(k)) ?? null;
    const lines = [];
    for (const b of GRADERS[m]) {
      const o = k.slots[b], os = o ?? GRADE_UND;
      const g = os >= GRADE_RATIO * k.pick && os - k.pick >= GRADE_SPOTS ? 'reach' : k.pick >= GRADE_RATIO * os && k.pick - os >= GRADE_SPOTS ? 'value' : null;
      if (g) k.grades.push({ g, by: b, o });
      const where = o != null ? `#${o}` : 'undrafted';
      lines.push([g === 'reach' ? 'Reach' : g === 'value' ? 'Value' : 'Grade',
        g === 'reach' ? `${MOCK_NAME[b]} mock ${where}${o != null ? `, ${o - k.pick} picks later there` : ''}.`
          : g === 'value' ? `${MOCK_NAME[b]} mock #${o}, ${k.pick - o} picks earlier there.` : `${MOCK_NAME[b]} mock ${where}.`]);
    }
    const i = k.rep.lines.findIndex(([h]) => h === 'Slot');
    k.rep.lines.splice(i + 1, 0, ...lines);
  }
  return M;
}
