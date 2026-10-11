// Team-level models for the College Football ARKBOARD, fed by scripts/fetch_cfb.mjs:
//   Elo        team ratings from games (ESPN scoreboard), starting from a preseason prior
//   Talent     each team's projected starting 22 from our player grades, as expected NFL value
//   TvE        talent vs Elo: Elo above or below what the roster's recruited talent predicts
//   xNIL       each roster's expected NIL (xNIL), summed
//   Games      the coming week: win probability and spread from Elo, top prospects, playstyle, injuries
//   Staff      head coaches credited with team results, coordinators with their side's
//              position groups: production above talent, and development since high school
//   Mock       a 2027 mock draft: projected order (ESPN standings), needs (depth charts + contracts), FV + positional value
import { variant } from './cfb_names.mjs';
const SEASON = 2026;
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const mean = xs => xs.reduce((a, b) => a + b, 0) / Math.max(1, xs.length);
const sd = xs => { const m = mean(xs); return Math.sqrt(mean(xs.map(x => (x - m) ** 2))) || 1; };
const zs = xs => { const m = mean(xs), s = sd(xs); return xs.map(x => (x - m) / s); };
const r1 = x => Math.round(x * 10) / 10, r2 = x => Math.round(x * 100) / 100;
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
// drafts (nflverse): 80 -> 8.5, 60 -> 5.0, 50 -> 3.7, 40 -> 1.7, 30 -> 0.4; in between, linear
const AV_BY_FV = [[20, 0], [30, 0.4], [40, 1.7], [50, 3.7], [60, 5.0], [70, 6.6], [80, 8.5]];
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
function gameRow(e, wk) {
  const c = e.competitions?.[0];
  const h = c.competitors.find(t => t.homeAway === 'home'), a = c.competitors.find(t => t.homeAway === 'away');
  const odds = c.odds?.[0];
  return { id: e.id, week: wk, date: new Date(e.date).toISOString(), neutral: !!c.neutralSite, done: !!c.status?.type?.completed,
    home: h.team.id, away: a.team.id, homeName: h.team.location, awayName: a.team.location, hs: +h.score, as: +a.score,
    homeRank: h.curatedRank?.current < 99 ? h.curatedRank.current : null, awayRank: a.curatedRank?.current < 99 ? a.curatedRank.current : null,
    venue: c.venue?.fullName || null, tv: c.broadcasts?.[0]?.names?.[0] || null,
    line: odds?.details || null, total: odds?.overUnder ?? null };
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
// probable ~.9. A season-ending injury takes the player off the depth chart altogether.
export const PLAY_PROB = { 'Out (season)': 0, Out: 0, Doubtful: 0.25, Questionable: 0.6, Probable: 0.9, Active: 1 };
export const playProb = st => PLAY_PROB[st] ?? (/season/i.test(st || '') ? 0 : /out/i.test(st || '') ? 0 : /doubt/i.test(st || '') ? 0.25 : /quest/i.test(st || '') ? 0.6 : /prob/i.test(st || '') ? 0.9 : 1);
export const seasonOut = st => /season/i.test(st || '');
// status from one clause of a news headline (or, failing that, the blurb's first sentence): the most serious
// reading wins; null = not availability news
export function statusOf(text) {
  const t = (text || '').toLowerCase();
  if (/season-ending|out for (the )?(rest of the |remainder of the )?(season|year)|(rest|remainder) of the (season|year|20\d\d season)|miss the (rest|remainder)|out indefinitely|torn acl|achilles|medical redshirt|career-ending|medically retire|likely out for season/.test(t)) return 'Out (season)';
  if (/doubtful|unlikely to play/.test(t)) return 'Doubtful';
  if (/\bruled out|\bwill miss|\bto miss|\bmiss(es)? time|\bwon't play|\bwill not play|\bnot expected to play|\bis out\b|\bout\b(?! of)|\bsidelined|\binactive|\bwill sit|\bnot dress|\bout for a (week|month)/.test(t)) return 'Out';
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

// CollegeFootballData (key in CFBD_API_KEY; free tier ~1,000 calls a month, so a few calls per run)
export async function cfbd(pathq) {
  const key = process.env.CFBD_API_KEY;
  if (!key) throw new Error('CFBD_API_KEY not set');
  const r = await fetch(`https://api.collegefootballdata.com/${pathq}`, { headers: { Authorization: `Bearer ${key}`, accept: 'application/json' } });
  if (!r.ok) throw new Error(`CFBD ${r.status} ${pathq}`);
  return r.json();
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
      starters.push(...ps.filter(p => p.pos === g && p.fv != null).sort((a, b) => b.fv - a.fv || b.comp - a.comp).slice(0, n));
    }
    const side = list => r1(list.reduce((a, p) => a + avOf(p.fv), 0));
    const t = teams[tid] || {}, adv = opts.adv?.[tid];
    out.push({
      tid, team: t.name, full: t.full, abbr: t.abbr, logo: ps.find(p => p.logo)?.logo || t.logo, color: t.color ? `#${t.color}` : null,
      conf: mode(ps.map(p => p.conf).filter(Boolean)),
      talent: side(starters), off: side(starters.filter(p => OFFENSE.includes(p.pos))), def: side(starters.filter(p => DEFENSE.includes(p.pos))),
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
  rank(out, 'talent', 'talentRk'); rank(out, 'recruited', 'recruitedRk'); rank(out.filter(t => t.elo != null), 'elo', 'eloRk');
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
// played), scaled by the opponent: offensive stats by how many EPA per play the opponent's defense
// allows on that play type (pass or rush), defensive stats by how many plays and how much success
// the opponent's offense runs (tackles) and how much havoc it allows (TFLs, sacks, hurries);
// e^(.12 z) either way, z across FBS. Ranked by production points
// (PPR fantasy scoring on offense: pass yd .04, pass TD 4, INT -2, rush/rec yd .1, TD 6, catch 1; tackles 1, TFL 2, sacks 3, hurries 1, PDs 2, INTs 5 on defense).
// Players listed Out or Doubtful don't project.
const OFF_PTS = p => 0.04 * p.passYds + 4 * p.passTd - 2 * p.int + 0.1 * p.rushYds + 6 * p.rushTd + 1 * p.rec + 0.1 * p.recYds + 6 * p.recTd;
const DEF_PTS = p => p.tot + 2 * p.tfl + 3 * p.sacks + p.hur + 2 * p.pd + 5 * p.ints + 6 * p.dtd;
export function playerRates(pstats, resolve, games) {
  const gp = {};
  for (const g of games || []) if (g.done) for (const id of [g.home, g.away]) gp[id] = (gp[id] || 0) + 1;
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
function projectSide(list, oppAdv, Z, inj, fvOf) {
  const mp = Math.exp(0.12 * Z.dPass(oppAdv)), mr = Math.exp(0.12 * Z.dRush(oppAdv));
  const mt = Math.exp(0.12 * Z.oPlays(oppAdv)), mh = Math.exp(0.12 * Z.oHavoc(oppAdv));   // tackle volume; TFL/sack chances
  const r1 = x => Math.round(x * 10) / 10;
  const off = [], def = [];
  for (const p of list || []) {
    if (playProb(inj[normName(p.name)]?.status) < 0.5) continue;     // out, doubtful, out for the season
    const q = { passYds: p.passYds * mp, passTd: p.passTd * mp, int: p.int / mp, rushYds: p.rushYds * mr, rushTd: p.rushTd * mr, rec: p.rec * mp, recYds: p.recYds * mp, recTd: p.recTd * mp,
      tot: p.tot * mt, tfl: p.tfl * mh, sacks: p.sacks * mh, hur: p.hur * mh, pd: p.pd / mp, ints: p.ints / mp, dtd: p.dtd };
    const o = OFF_PTS(q), d = DEF_PTS(q), bp = fvOf(p);
    const base = { name: bp?.name || p.name, pos: bp?.pos || p.pos, fv: bp?.fv ?? null };
    if (o >= 3 && o >= d) {
      const line = p.att >= 5 ? `${Math.round(q.passYds)} pass yds · ${r1(q.passTd)} pass TD` + (q.rushYds + q.recYds >= 20 ? ` · ${Math.round(q.rushYds + q.recYds)} yds · ${r1(q.rushTd + q.recTd)} TD` : '')
        : `${Math.round(q.rushYds + q.recYds)} yds` + (q.rec >= 1 ? ` · ${r1(q.rec)} rec` : '') + ` · ${r1(q.rushTd + q.recTd)} TD`;   // rushing + receiving together
      off.push({ ...base, pts: r1(o), line, ppg: r1(OFF_PTS(p)), proj: Object.fromEntries(['passYds', 'passTd', 'int', 'rushYds', 'rushTd', 'rec', 'recYds', 'recTd'].map(k => [k, r1(q[k])])) });
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
// projected starter listed Out or Doubtful costs his expected NFL value (AV/season) x 8 Elo, a QB
// double. Spread: ELO_PER_POINT. Shown next to the market line where ESPN has one.
const TALENT_ELO = 80;
// spread: 19 Elo per point. This season's margins fit best near 16 (in sample; MAE 14.3 vs 15.8 at the
// NFL-style 25), and 19 puts model spreads on the market's scale (slope .97 against the lines), so an
// edge is a disagreement about the teams rather than about how many points a rating gap is worth
const ELO_PER_POINT = 19;
const normName = s => (s || '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/\b(jr|sr|ii|iii|iv)\b\.?/g, '').replace(/[^a-z]/g, '');
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
  const stars = (tid, oppTid) => projectSide(rates[tid], opts.adv?.[oppTid], Z,
    Object.fromEntries((injuries[tid] || []).flatMap(i => { const bp = findP(tid, i.name); return [[normName(i.name), i], ...(bp ? [[normName(bp.name), i]] : [])]; })),
    q => byId[q.id] || findP(tid, q.name) || null);
  const talentAdj = t => t ? Math.round(TALENT_ELO * (t.talent - tm) / tsd) : -Math.round(TALENT_ELO * 1.5);   // non-FBS: well below
  const byTeam = {};
  for (const p of rows) if (p.tid) (byTeam[p.tid] ||= []).push(p);
  const side = (tid) => {
    const all = (byTeam[tid] || []).filter(p => p.fv != null);
    const inj = Object.fromEntries((injuries[tid] || []).map(i => [normName(variant(all, i.name)?.name || i.name), i]));
    const st = p => inj[normName(p.name)]?.status || null;
    // a season-ending injury takes the player off the depth chart: the next man up is the starter, and the
    // team's ratings already carry the games without him
    const ps = all.filter(p => !seasonOut(st(p)));
    const tag = p => ({ name: p.name, pos: p.pos, fv: p.fv, plus: p.plus, star: p.star, riser: p.riser, logo: p.logo, cls: p.cls, inj: st(p) });
    const top = groups => ps.filter(p => groups.includes(p.pos)).sort((a, b) => b.fv - a.fv || b.comp - a.comp).slice(0, 5).map(tag);
    // starters, each missing with 1 - P(plays) by his designation (out, doubtful, questionable, probable)
    const starters = [];
    for (const [g, n] of Object.entries(STARTERS)) starters.push(...ps.filter(p => p.pos === g).sort((a, b) => b.fv - a.fv).slice(0, n));
    const out = starters.map(p => ({ p, miss: 1 - playProb(st(p)) })).filter(x => x.miss > 0);
    const adj = -Math.round(out.reduce((a, { p, miss }) => a + miss * avOf(p.fv) * 8 * (p.pos === 'QB' ? 2 : 1), 0));
    // with the game model, a QB is priced by EPA instead: his EPA per play against his backup's (both shrunk
    // toward replacement) over a game's QB plays; the rest of the starters keep the AV cost, in points
    const nonQb = -out.filter(x => x.p.pos !== 'QB').reduce((a, { p, miss }) => a + miss * avOf(p.fv) * 8, 0) / ELO_PER_POINT;
    const qbs = M?.qb?.[tid] || [], q1 = qbs[0];
    const qst = q1 ? (injuries[tid] || []).find(i => normName(i.name) === normName(q1.name) || variant([{ name: q1.name }], i.name))?.status || null : null;
    const qmiss = 1 - playProb(qst);
    const qbOut = q1 && q1.plays >= 60 && qmiss > 0 ? { name: q1.name, backup: qbs[1]?.name || null, status: qst,
      pts: r1(qmiss * (Math.max(qbs[1]?.val ?? -0.05, -0.25) - q1.val) * 38) } : null;
    // the primary kicker out: his field goals over expected per game, at the game model's special-teams weight
    const k = opts.kickers?.[tid], kst = k ? (injuries[tid] || []).find(i => normName(i.name) === normName(k.name))?.status : null;
    const kOut = k && kst && playProb(kst) < 1 && k.poeG > 0 ? { name: k.name, status: kst, pts: r1(-(1 - playProb(kst)) * k.poeG * (M?.stBeta ?? 0.65)) } : null;
    if (kOut) out.push({ p: { name: k.name, pos: 'K', fv: null }, miss: 1 - playProb(kst) });
    return { off: top(OFFENSE), def: top(DEFENSE), injAdj: adj, injPts: r1(nonQb + (qbOut?.pts ?? 0) + (kOut?.pts ?? 0)), qbOut, kOut,
      out: out.map(({ p, miss }) => ({ name: p.name, pos: p.pos, fv: p.fv, status: st(p), miss: r2(miss) })),
      seasonOut: all.filter(p => seasonOut(st(p))).sort((a, b) => b.fv - a.fv).slice(0, 4).map(p => ({ name: p.name, pos: p.pos, fv: p.fv })) };
  };
  const M = opts.model || null;
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
    if (pred) {
      const m = pred.margin + hs.injPts - as.injPts;
      diff = m * ELO_PER_POINT; pHome = phiN(m / M.sigma);
      proj = { margin: r1(m), total: r1(pred.total), home: Math.round(pred.home + (hs.injPts - as.injPts) / 2), away: Math.round(pred.away - (hs.injPts - as.injPts) / 2),
        parts: { ...pred.parts, inj: r1(hs.injPts - as.injPts) }, wx: pred.wx };
    }
    const team = (t, id, name, rank, sd) => ({ id, name: t?.team || name, logo: t?.logo || null, color: t?.color || null, rank, elo: t?.elo ?? null,
      rec: t ? `${t.rec.w}-${t.rec.l}` : null, talentRk: t?.talentRk ?? null, style: t?.style || null, ...sd });
    const spread = Math.round(-diff / ELO_PER_POINT * 2) / 2, mkt = marketHome(g.line, h, a);
    // edge: model minus market, home perspective in points; who the model likes more than the market
    const edge = mkt == null ? null : { pts: Math.abs(mkt - spread), side: mkt - spread > 0 ? 'home' : mkt - spread < 0 ? 'away' : null };
    // cover: the chance the model's side of the market line covers; total: over/under the market total
    if (proj && mkt != null) { const pc = phiN((proj.margin + mkt) / M.sigma); edge.cover = r2(edge.side === 'away' ? 1 - pc : pc); }
    if (proj && g.total != null) { const po = phiN((proj.total - g.total) / (M.report?.params?.totalSigma || 16)); proj.over = r2(po); }
    hs.stars = stars(g.home, g.away); as.stars = stars(g.away, g.home);
    // the game's top three on each side of the ball, both teams together
    const tag = (t, list) => list.map(p => ({ ...p, team: t?.abbr || null, logo: t?.logo || null }));
    for (const [t, o, sd, home] of [[a, h, as, false], [h, a, hs, true]]) for (const p of sd.stars.all) players.push({ ...p, team: t?.team || null, abbr: t?.abbr || null, logo: t?.logo || null,
      opp: o?.abbr || o?.team || null, oppLogo: o?.logo || null, home, kick: g.date, game: g.id });
    delete hs.stars.all; delete as.stars.all;
    const top3 = k => [...tag(a, as.stars[k]), ...tag(h, hs.stars[k])].sort((x, y) => y.pts - x.pts).slice(0, 3);
    games.push({ id: g.id, date: g.date, venue: g.venue, tv: g.tv, neutral: g.neutral, line: g.line, total: g.total, market: mkt, edge,
      home: team(h, g.home, g.homeName, g.homeRank, hs), away: team(a, g.away, g.awayName, g.awayRank, as),
      pHome: r2(pHome), spread, proj, stars: { off: top3('off'), def: top3('def') },
      // marquee: both teams good and the game close, plus prospect firepower
      score: r2((h?.eloZ ?? -1) + (a?.eloZ ?? -1) - Math.abs(pHome - 0.5) * 2 + [...hs.off, ...hs.def, ...as.off, ...as.def].reduce((x, p) => x + (p.fv >= 60 ? 0.1 : 0), 0)) });
  }
  const out = games.sort((x, y) => y.score - x.score);
  out.players = players.sort((x, y) => y.pts - x.pts);
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

// ---- NFL draft order and needs (ESPN) ------------------------------------------------------------------
// Projected order: non-playoff teams by record (worst first), then playoff teams by seed, using ESPN's
// current standings and playoff seeds; ties broken by point differential. Traded picks and
// compensatory picks aren't public in a scriptable, permitted source, so every team keeps its own.
export async function fetchNflOrder(season = SEASON, rounds = 7) {
  const d = await espnJson(`https://site.api.espn.com/apis/v2/sports/football/nfl/standings?season=${season}`);
  const rows = [];
  const walk = o => {
    if (Array.isArray(o)) return o.forEach(walk);
    if (!o || typeof o !== 'object') return;
    if (o.standings?.entries) for (const e of o.standings.entries) {
      const st = Object.fromEntries(e.stats.map(x => [x.name, x.value]));
      rows.push({ team: e.team.abbreviation, teamName: e.team.displayName, id: e.team.id, pct: st.winPercent ?? 0,
        seed: st.playoffSeed ?? 99, diff: st.pointDifferential ?? 0, logo: e.team.logos?.[0]?.href || null });
    }
    Object.values(o).forEach(walk);
  };
  walk(d);
  const seen = new Set(), teams = rows.filter(r => !seen.has(r.team) && seen.add(r.team));
  const out = teams.filter(t => t.seed > 7).sort((a, b) => a.pct - b.pct || a.diff - b.diff);
  const inn = teams.filter(t => t.seed <= 7).sort((a, b) => a.pct - b.pct || b.seed - a.seed || a.diff - b.diff);
  const base = [...out, ...inn], order = [];
  for (let r = 1; r <= rounds; r++) base.forEach((t, i) => order.push({ pick: (r - 1) * base.length + i + 1, round: r, team: t.team, teamName: t.teamName, espnId: t.id, from: null }));
  return { order, teams: Object.fromEntries(teams.map(t => [t.team, { name: t.teamName, espnId: t.id, logo: t.logo }])) };
}

// Needs from each NFL team's depth chart and roster contracts: a starter slot is a need when the
// starter's deal ends after this season, he's aging (30+, QBs 34+), or he's a cheap veteran
// (replacement level); a starter paid at market rate (QBs $25M+) mostly isn't. Averaged by group.
const DC_GROUP = { qb: 'QB', rb: 'RB', wr: 'WR', te: 'TE', lt: 'OL', lg: 'OL', c: 'OL', rg: 'OL', rt: 'OL',
  ldt: 'DL', rdt: 'DL', dt: 'DL', nt: 'DL', mlb: 'LB', lilb: 'LB', rilb: 'LB', lcb: 'CB', rcb: 'CB', nb: 'CB', ss: 'S', fs: 'S' };
export async function fetchNflNeeds(orderTeams) {
  const needs = {};
  for (const [abbr, t] of Object.entries(orderTeams)) {
    const [dc, ro] = await Promise.all([
      espnJson(`https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/${t.espnId}/depthcharts`),
      espnJson(`https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/${t.espnId}/roster`)]);
    const people = {};
    for (const g of ro?.athletes || []) for (const a of g.items || []) people[a.id] = a;
    const score = {}, slots = {};
    for (const unit of dc?.depthchart || []) {
      const threeFour = /3-4/.test(unit.name || '');
      for (const [slot, v] of Object.entries(unit.positions || {})) {
        let g = DC_GROUP[slot];
        if (['lde', 'rde', 'de'].includes(slot)) g = threeFour ? 'DL' : 'EDGE';
        if (['wlb', 'slb', 'lolb', 'rolb', 'olb'].includes(slot)) g = threeFour ? 'EDGE' : 'LB';
        if (!g) continue;
        const a = people[v.athletes?.[0]?.id] || {};
        const c = a.contract || {}, age = a.age ?? 27, exp = a.experience?.years ?? 3;
        const pay = c.salary ?? 0, paid = pay >= (g === 'QB' ? 25e6 : 12e6) && (c.yearsRemaining ?? 0) >= 1;
        let need = 0;
        if (c.yearsRemaining != null && c.yearsRemaining <= 1 && exp >= 5) need += 0.5;   // young starters get extended
        if (age >= (g === 'QB' ? 34 : 30)) need += 0.4;
        if (age >= (g === 'QB' ? 37 : 33)) need += 0.4;
        if (pay < 2e6 && exp >= 4) need += 0.3;            // cheap veteran: replacement level
        if (g === 'QB' && pay < 5e6 && exp >= 5) need += 0.5; // a QB on a small deal after his rookie contract
        if (paid) need = g === 'QB' && age < 36 ? 0 : need * 0.4;   // a paid starter (a franchise QB) isn't a need
        if (!v.athletes?.length) need += 1;
        score[g] = (score[g] || 0) + need; slots[g] = (slots[g] || 0) + 1;
      }
    }
    needs[abbr] = Object.entries(score).map(([g, x]) => ({ group: g, label: g, score: Math.round(100 * x / slots[g]) / 100 }))
      .filter(n => n.score > 0.15).sort((a, b) => b.score - a.score);
    await sleep(120);
  }
  return needs;
}

// ---- staff ------------------------------------------------------------------------------------------
// Coordinators get their side's position groups; head coaches the team. Two signals per group:
//   over:  how far the group's production runs ahead of its talent (PFN z minus On3-based z), the
//          starters weighted by snaps — coaching shows up as players producing above their grade
//   dev:   On3 college grade minus high school grade for the group's ranked players — who got better
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
    const znil = Math.round(ps.filter(p => groups.includes(p.pos)).reduce((a, p) => a + (p.znil || 0), 0));
    return { over, dev: devs.length ? mean(devs) : null, devN: devs.length, znil,
      risers: ps.filter(p => groups.includes(p.pos) && p.on3 != null && p.hsGrade != null && p.on3 - p.hsGrade >= 8)
        .sort((a, b) => (b.on3 - b.hsGrade) - (a.on3 - a.hsGrade)).slice(0, 3)
        .map(p => ({ name: p.name, pos: p.pos, hs: Math.round(p.hsGrade), now: p.on3, stars: p.hsStars })) };
  };
  const coaches = [];
  for (const t of teamList) {
    const ps = byTeam[t.tid] || [], s = staff?.[t.tid] || {};
    const off = groupScore(ps, OFFENSE), def = groupScore(ps, DEFENSE);
    const base = { tid: t.tid, team: t.team, logo: t.logo, conf: t.conf };
    const hcName = s.hc?.name || t.hc;
    if (hcName) coaches.push({ ...base, role: 'HC', name: hcName, src: s.hc?.src || 'espn', wiki: s.hc?.wiki, raw: t.eloZ == null ? null : t.eloZ * 0.5 + (t.tve ?? 0) * 0.5,
      znil: t.znil ?? null, detail: { elo: t.elo, eloRk: t.eloRk, tve: t.tve, rec: t.rec } });
    for (const [role, side, groups] of [['OC', off, OFFENSE], ['DC', def, DEFENSE]]) {
      const c = s[role.toLowerCase()];
      if (!c?.name) continue;
      coaches.push({ ...base, role, name: c.name, src: c.src, wiki: c.wiki, wikis: c.wikis, groups, raw: null, over: side.over, dev: side.dev, devN: side.devN, znil: side.znil, risers: side.risers });
    }
  }
  // coordinator raw score: production-over-talent and development, each standardized among coordinators
  const coords = coaches.filter(c => c.role !== 'HC');
  const oz = zs(coords.map(c => c.over ?? 0)), dz = zs(coords.map(c => c.dev ?? 0));
  coords.forEach((c, i) => { c.raw = 0.6 * oz[i] + 0.4 * (c.devN >= 3 ? dz[i] : 0); });
  for (const role of ['HC', 'OC', 'DC']) {
    const list = coaches.filter(c => c.role === role && c.raw != null);
    const z = zs(list.map(c => c.raw));
    list.forEach((c, i) => { c.score = Math.round(100 + 10 * z[i]); });
    rank(list, 'score', 'rk');
  }
  for (const c of coaches) { if (c.over != null) c.over = r2(c.over); if (c.dev != null) c.dev = r1(c.dev); delete c.raw; }
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
//           less MOVE_COST FV for the projection risk)
// Teams then pick on log(xPick) (pick value falls off like a log: the gap between picks 2 and 4 is worth the
// gap between 20 and 40), plus team need, with penalties for a team doubling up at a position, a team with a
// paid QB taking one early, and a position running past its usual count in the round. A player flagged to
// move can be taken at the new spot when the team needs it there more.
// Value: a pick whose FV is a tier (VALUE_GAP) or more above the FV our big board has at that slot, and who goes
// VALUE_RATIO times later or more than his big-board rank (so a 74 at #5 isn't a value, a 76 at #36 is).
// Positional values and per-round counts come from data/cfb_draft_priors.json (measured on 2015-25
// drafts) when present; the defaults below are the long-run averages.
const DEFAULT_PRIORS = {
  value: { QB: [6, 3, 1], EDGE: [3, 2, 1], OL: [2, 1.5, 1], WR: [2, 1.5, 1], CB: [2, 1.5, 1], DL: [1, 1, 0.5], TE: [-1.5, -0.5, 0], S: [-2, -0.5, 0], LB: [-2.5, -0.5, 0], RB: [-3, -1, 0] },
  perRound: { QB: [3.5, 2, 1.5], RB: [1.2, 2.5, 3], WR: [4.5, 5, 4.5], TE: [1, 2, 2.5], OL: [6, 6, 6], EDGE: [4.5, 4, 3.5], DL: [3, 3, 3.5], LB: [1.5, 3, 3.5], CB: [4.5, 4.5, 4], S: [1.5, 3, 3] },
};
const MARKET_W = { base: 0.55, perBoard: 0.3, unranked: 0.65 };   // weight on the market rank: base + perBoard x sqrt(share of boards); unranked
const CONS_BOARDS_N = 9;
const UNRANKED_DEPTH = 1.3;
const NEED_LN = [0.35, 0.25, 0.18, 0.12, 0.06];                     // log-pick units: need #1 lets a team reach ~30%
const DUP_LN = 0.3, QB_BLOCK_LN = 0.8, RUN_LN = 0.15, MOVE_LN = 0.1;
const MOVE_COST = 1.5;                                                      // FV: the risk in a position change
const MOVE_GROUP = { IOL: 'OL', OT: 'OL', DL: 'DL', EDGE: 'EDGE', LB: 'LB', S: 'S', CB: 'CB', TE: 'TE', WR: 'WR' };   // ATH stays put
const VALUE_GAP = 5, VALUE_RATIO = 2.5;
export function mockDraft(rows, tank, rounds = 7, priors = DEFAULT_PRIORS) {
  const P = { ...DEFAULT_PRIORS, ...(priors || {}) };
  const pool = rows.filter(p => p.fv != null && p.draft27 && STARTERS[p.pos] && (p.elig >= 4 || p.fv >= 45 || p.consRk != null));
  // model rank: draft value at the player's best spot, the round index from his FV tier
  const roundOf = fv => fv >= 60 ? 0 : fv >= 52 ? 1 : 2;
  const draftValue = (p, pos, moved) => p.fv + (p.plus ? 1 : 0) + (P.value[pos]?.[roundOf(p.fv)] ?? 0)
    + (moved ? -MOVE_COST : Math.min(0, (p.parts?.[7] ?? 0) * 12));
  for (const p of pool) {
    const alt = MOVE_GROUP[p.move];
    p._dv = Math.max(draftValue(p, p.pos, false), alt && alt !== p.pos ? draftValue(p, alt, true) : -Infinity);
  }
  const byModel = [...pool].sort((a, b) => b._dv - a._dv || (b.comp ?? 0) - (a.comp ?? 0));
  byModel.forEach((p, i) => { p._mRk = i + 1; });
  const depth = Math.max(50, ...pool.filter(p => p.cons != null).map(p => p.cons)) * UNRANKED_DEPTH;
  for (const p of pool) {
    const w = p.cons != null ? MARKET_W.base + MARKET_W.perBoard * Math.sqrt(Math.min(1, (p.consN || 1) / CONS_BOARDS_N)) : MARKET_W.unranked;
    const mkt = p.cons != null ? Math.max(1, p.cons) : Math.max(depth, p._mRk);
    p._x = Math.exp(w * Math.log(mkt) + (1 - w) * Math.log(p._mRk));
  }
  const taken = new Set(), teamPos = {}, picks = [], roundCount = {};
  for (const o of tank.order.filter(o => o.round <= rounds)) {
    const ri = Math.min(o.round, 3) - 1;
    const needs = (tank.needs?.[o.team] || []).map(n => n.group);
    const qbSet = !needs.includes('QB');
    let best = null, bestV = -Infinity, why = null, bestPos = null;
    const valueAt = (p, pos, moved) => {
      const ni = needs.indexOf(pos);
      const need = ni >= 0 ? NEED_LN[ni] ?? 0.05 : 0;
      const dup = (teamPos[o.team] || []).filter(x => x === pos).length * DUP_LN;
      const exp = P.perRound[pos]?.[ri] ?? 3, ran = (roundCount[o.round]?.[pos] || 0);
      const cap = Math.max(1, Math.round(exp * 1.25)), run = ran >= cap ? RUN_LN * (ran - cap + 1) : 0;
      const qbBlock = pos === 'QB' && qbSet && o.round <= 2 ? QB_BLOCK_LN : 0;
      return { v: -Math.log(p._x) + need - dup - run - qbBlock - (moved ? MOVE_LN : 0), ni };
    };
    for (const p of pool) {
      if (taken.has(p)) continue;
      const alt = MOVE_GROUP[p.move];
      for (const [pos, moved] of [[p.pos, false], ...(alt && alt !== p.pos ? [[alt, true]] : [])]) {
        const { v, ni } = valueAt(p, pos, moved);
        if (v > bestV) { bestV = v; best = p; bestPos = pos; why = ni >= 0 ? `need #${ni + 1}` : null; }
      }
    }
    if (!best) break;
    taken.add(best); (teamPos[o.team] ||= []).push(bestPos);
    (roundCount[o.round] ||= {})[bestPos] = (roundCount[o.round][bestPos] || 0) + 1;
    const moved = bestPos !== best.pos;
    picks.push({ pick: o.pick, round: o.round, team: o.team, teamName: o.teamName, from: o.from, comp: o.comp,
      name: best.name, pos: bestPos, spot: moved ? null : best.spot, movedFrom: moved ? best.pos : null, moveWhy: moved ? best.moveWhy : null,
      school: best.team, logo: best.logo, fv: best.fv, plus: best.plus,
      cls: best.cls, age: best.age ?? best.ageEst, ageEst: best.age == null, ovr: best.ovr, need: why,
      cons: best.consRk ?? null, xPick: Math.round(best._x) });
  }
  // where each pick sits on our draft-eligible big board, by FV (positive = taken earlier than we have him),
  // and value: FV a tier or more above what the board has at that slot, going well after his board rank
  const bigBoard = [...pool].sort((a, b) => b.fv - a.fv || (b.comp ?? 0) - (a.comp ?? 0));
  const at = new Map(bigBoard.map((p, i) => [p.name + '|' + p.team, i + 1]));
  for (const k of picks) {
    k.bb = at.get(k.name + '|' + k.school); k.reach = k.bb - k.pick;
    const slotFv = bigBoard[Math.min(bigBoard.length, k.pick) - 1]?.fv;
    k.value = slotFv != null && k.fv - slotFv >= VALUE_GAP && k.pick >= VALUE_RATIO * k.bb ? Math.round(k.fv - slotFv) : null;
  }
  for (const p of pool) { delete p._dv; delete p._mRk; delete p._x; }
  return picks;
}
