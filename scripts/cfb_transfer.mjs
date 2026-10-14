// Transfer% and the team builder for the College Football ARKBOARD, fed by scripts/fetch_cfb.mjs.
//
// Transfer%: the chance a player is on another FBS or FCS roster next season. A logit fit by
// scripts/cfb_transfer_fit.py (data/cfb_transfer_fit.json) on every 2024 and 2025 FBS/FCS player followed
// to the next season's ESPN rosters; tested out of time on the 2026 portal cycle. features() mirrors the
// fit's features() by name. Drivers: class (sophomores and juniors move most), recruiting rank, playing time
// and production (FBS, PFN), a G5 producer's pull upward, team record, a head-coach change (averaged over
// its chance, fit on record and level), distance from home and home-state school, a transfer who just
// arrived, position. An exit model (out of eligibility, drafted, left) shares the features; Draft% (the
// mock's draftOdds) sets the floor on exit, and stay + transfer are scaled into what's left.
//
// Team builder: each FBS program's offseason plan. Budget = the program's NIL budget (yNIL summed: the
// revenue-share cap plus outside NIL, the same budget the NIL block splits), up 4% with the cap. Held back:
// the next recruiting class (this year's first-year players' yNIL). Retention: every returner at his market
// price (xNIL) x his chance of returning, kept in order of value per dollar (his edge over the next man up)
// until the budget runs out; the rest are "can't keep at market". Space = budget - class - retention.
// Positional strength next season = the starters' FV from Monte Carlo returns (each player back with his
// stay chance; holes at the level's replacement FV, its typical first backup), against the level's contender
// bar (the 67th percentile of this season's units). Targets = players elsewhere likely to move (Transfer%)
// and FCS move-ups who would start, priced at the level's going rate for their position and FV. The plan
// runs as a market: buyers take turns, a target sits on at most a few plans, and each team signs the most
// need-weighted AV per dollar x Transfer% x landing odds (scripts/cfb_landing_fit.py: if he moves, the chance
// he picks this school, from 2024-25 moves) that fits its space. FCS move-ups sign below the going rate.
import fs from 'node:fs';
import path from 'node:path';
import { avOf, STARTERS } from './cfb_teams.mjs';

const r1 = x => Math.round(x * 10) / 10, r2 = x => Math.round(x * 100) / 100, r3 = x => Math.round(x * 1000) / 1000;
const sig = z => 1 / (1 + Math.exp(-z));
const normName = n => String(n || '').toLowerCase().replace(/\b(jr|sr|ii|iii|iv|v)\b\.?/g, '').replace(/[^a-z]/g, '');
const P4_CONF = new Set(['SEC', 'Big Ten', 'Big 12', 'ACC']);
const ND = '87';
export const levelOf = r => r.div === 'FCS' ? 'FCS' : P4_CONF.has(r.conf) || r.tid === ND ? 'P4' : 'G5';

// ---- geography (Census places, schools from ESPN venues: scripts/geo/) -----------------------------------
const STATE_AB = { Alabama: 'AL', Alaska: 'AK', Arizona: 'AZ', Arkansas: 'AR', California: 'CA', Colorado: 'CO', Connecticut: 'CT',
  Delaware: 'DE', 'District of Columbia': 'DC', Florida: 'FL', Georgia: 'GA', Hawaii: 'HI', Idaho: 'ID', Illinois: 'IL', Indiana: 'IN',
  Iowa: 'IA', Kansas: 'KS', Kentucky: 'KY', Louisiana: 'LA', Maine: 'ME', Maryland: 'MD', Massachusetts: 'MA', Michigan: 'MI',
  Minnesota: 'MN', Mississippi: 'MS', Missouri: 'MO', Montana: 'MT', Nebraska: 'NE', Nevada: 'NV', 'New Hampshire': 'NH',
  'New Jersey': 'NJ', 'New Mexico': 'NM', 'New York': 'NY', 'North Carolina': 'NC', 'North Dakota': 'ND', Ohio: 'OH', Oklahoma: 'OK',
  Oregon: 'OR', Pennsylvania: 'PA', 'Rhode Island': 'RI', 'South Carolina': 'SC', 'South Dakota': 'SD', Tennessee: 'TN', Texas: 'TX',
  Utah: 'UT', Vermont: 'VT', Virginia: 'VA', Washington: 'WA', 'West Virginia': 'WV', Wisconsin: 'WI', Wyoming: 'WY', 'Puerto Rico': 'PR' };
const placeNorm = s => (s || '').toLowerCase().replace(/saint /g, 'st ').replace(/st\. /g, 'st ').replace(/mount /g, 'mt ').replace(/fort /g, 'ft ').replace(/[^a-z0-9]/g, '');
export function loadGeo(root) {
  const places = JSON.parse(fs.readFileSync(path.join(root, 'scripts', 'geo', 'us_places.json'), 'utf8'));
  const loc = JSON.parse(fs.readFileSync(path.join(root, 'scripts', 'geo', 'team_loc.json'), 'utf8'));
  const centroid = {};
  for (const [st, d] of Object.entries(places)) if (st !== '_src') {
    const v = Object.values(d); centroid[st] = [v.reduce((a, x) => a + x[0], 0) / v.length, v.reduce((a, x) => a + x[1], 0) / v.length];
  }
  return {
    loc,
    // [lat, lon, state] for a US city; the state's centroid when the city misses; null abroad or unknown
    home(city, state, country) {
      if (country && !/^(USA|United States)$/i.test(country)) return null;
      const st = STATE_AB[state] || state; if (!st || !places[st]) return null;
      const hit = places[st][placeNorm(city)];
      return hit ? [hit[0], hit[1], st] : [...centroid[st], st];
    },
  };
}
export function miles(a, b) {
  if (!a || !b) return null;
  const rad = Math.PI / 180, p1 = a[0] * rad, p2 = b[0] * rad, dl = (b[1] - a[1]) * rad;
  const h = Math.sin((p2 - p1) / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 3958.8 * 2 * Math.asin(Math.sqrt(h));
}

// ---- PFN this season: qualified, score percentile at the position (FBS), depth on the team ---------------
// pfnAll: fetch_cfb.mjs's PFN pull ({group: rows}); resolve: team name -> ESPN id; volume: its volume()
export function pfnIndex(pfnAll, season, resolve, norm, volume) {
  const ix = {};
  for (const [g, rows] of Object.entries(pfnAll)) {
    const cur = rows.filter(r => r.season === season && r.division === 'FBS');
    const sc = cur.map(r => r.score).filter(x => typeof x === 'number').sort((a, b) => a - b);
    const upper = x => { let lo = 0, hi = sc.length; while (lo < hi) { const m = (lo + hi) >> 1; if (sc[m] <= x) lo = m + 1; else hi = m; } return lo; };
    const byTeam = {};
    for (const r of cur) {
      const tid = resolve(r.team); if (!tid) continue;
      const e = { g, tid, key: tid + '|' + norm(r.name), pct: typeof r.score === 'number' ? upper(r.score) / sc.length : 0.5, vol: volume(r, false, g) };
      (byTeam[tid] ||= []).push(e);
    }
    for (const list of Object.values(byTeam)) {
      list.sort((a, b) => b.vol - a.vol).forEach((e, i) => { e.starter = i < (STARTERS[g] ?? 1) ? 1 : 0; });
      for (const e of list) if (!ix[e.key] || ix[e.key].pct < e.pct) ix[e.key] = e;
    }
  }
  return ix;
}

// ---- the fitted features (scripts/cfb_transfer_fit.py features(), by name) -------------------------------
const GROUPS = ['QB', 'RB', 'WR', 'TE', 'OL', 'EDGE', 'DL', 'LB', 'CB', 'S', 'K', 'P', 'LS', 'ATH'];
export function features(p, hc) {
  const e = Math.min(Math.max(p.exp || 1, 1), 6), rz = p.rec ? (p.rec - 80) / 5 : 0, fbs = p.level === 'FCS' ? 0 : 1;
  const q = (p.q || 0) * fbs, pct = (p.pct || 0) * q, st = (p.starter || 0) * fbs, g5 = p.level === 'G5' ? 1 : 0;
  const x = {
    const: 1, exp2: +(e === 2), exp3: +(e === 3), exp4: +(e === 4), exp5: +(e >= 5),
    ranked: p.rec ? 1 : 0, rec: rz, played: p.played ? 1 : 0, rec_dnp: rz * (p.played ? 0 : 1),
    q, pct, starter: st, exp5_starter: (e >= 5 ? 1 : 0) * st,
    g5, fcs: p.level === 'FCS' ? 1 : 0, pct_g5: pct * g5, st_g5: st * g5,
    winp: (p.winp ?? 0.5) - 0.5, hc,
    logdist: p.dist != null ? Math.log1p(p.dist / 100) : 1.6, inState: p.inState ? 1 : 0, abroad: p.abroad ? 1 : 0,
    xfer_in: p.newcomer && e >= 2 ? 1 : 0,
    // playing time: games with a stat line as a share of a full season (fit: ESPN gamesPlayed / 13)
    gp: p.gp ?? 0, gp_g5: (p.gp ?? 0) * g5, gp_fcs: (p.gp ?? 0) * (p.level === 'FCS' ? 1 : 0),
    spot: +((p.gp ?? 0) * 13 >= 1 && (p.gp ?? 0) * 13 <= 7 && e >= 2),
    // program talent (z), and production at a loaded program: its producers rarely move
    tal: p.tal ?? 0, pct_tal: pct * Math.max(p.tal ?? 0, 0),
    qb_left: p.qbLeft && (p.g === 'WR' || p.g === 'TE') ? 1 : 0,
  };
  for (const g of GROUPS.slice(1)) x['pos_' + g] = +(p.g === g);
  return x;
}
const lin = (m, x, extra = {}) => m.names.reduce((s, n, i) => s + m.coef[i] * (x[n] ?? extra[n] ?? 0), 0);

// ctx: { fit, season, geo, pfnIx, norm, roster: {espnId: {years, home: [city, state, country]}},
//        recruits: {espnId: {year, grade}}, winp: {tid: share}, newcomers: Set(tid|norm name) }
export function transferOdds(rows, ctx) {
  const { fit } = ctx, h = fit.hc, latest = { ['s' + fit.latest]: 1 };
  let n = 0;
  const tal = fit.landing?.schools || {};
  // quarterbacks first: a receiver's odds use his starting QB's chance of transferring
  const qbOut = {};
  rows = [...rows.filter(r => r.pos === 'QB'), ...rows.filter(r => r.pos !== 'QB')];
  for (const r of rows) {
    const id = /\/id\/(\d+)/.exec(r.espnl || r.links?.espn || '')?.[1];
    const e = id ? ctx.roster[id] : null, rec = id ? ctx.recruits[id] : null;
    const yrs = rec && ctx.season - rec.year + 1 >= 1 ? ctx.season - rec.year + 1 : null;
    const level = levelOf(r), school = ctx.geo.loc[r.tid] || null;
    const home = e?.home ? ctx.geo.home(...e.home) : null;
    const pf = r.tid ? ctx.pfnIx[r.tid + '|' + ctx.norm(r.name)] : null;
    const p = {
      g: r.pos, level, exp: yrs ?? e?.years ?? r.elig ?? 1, rec: rec?.grade || null,
      played: !!(pf || (r.snaps ?? 0) > 0 || (id && ctx.played?.has(id))),
      q: pf ? 1 : 0, pct: pf?.pct ?? 0, starter: pf?.starter ?? 0,
      winp: ctx.winp[r.tid] ?? 0.5,
      dist: home && school ? miles(home, school) : null, inState: home && school ? home[2] === school[2] : false,
      abroad: !!(e?.home?.[2] && !/^(USA|United States)$/i.test(e.home[2])),
      newcomer: ctx.newcomers.has(r.tid + '|' + ctx.norm(r.name)),
      // games with a stat line so far over his team's games (CFBD box scores); without them, a played player at 60%
      gp: ctx.gp && ctx.teamGames?.[r.tid] ? Math.min(1, ((id && ctx.gp[id]) || 0) / ctx.teamGames[r.tid]) : null,
    };
    if (p.gp == null) p.gp = p.played ? 0.6 : 0;
    p.tal = tal[r.tid]?.[1] ?? 0;
    const q = p.g === 'WR' || p.g === 'TE' ? qbOut[r.tid] || 0 : 0;   // his starting QB's Transfer%
    // a coaching change is unknown until it happens: average over its fitted chance (record, level)
    // (FBS: the coaching market's chance the job opens, data/cfb_coach_market.json, when it has the team)
    const c = ctx.coachOpen?.[r.tid] ?? sig(h.coef[0] + h.coef[1] * (p.winp - 0.5) + h.coef[2] * (level === 'G5') + h.coef[3] * (level === 'FCS'));
    const x0 = features(p, 0), x1 = features(p, 1);
    const at = (x, qb) => sig(lin(fit.transfer, qb ? { ...x, qb_left: 1 } : x, latest));
    const pT = (1 - q) * ((1 - c) * at(x0, 0) + c * at(x1, 0)) + q * ((1 - c) * at(x0, 1) + c * at(x1, 1));
    p.qbP = q;
    const pE = sig(lin(fit.exit, x0));
    // Draft% is the better read on leaving for the NFL: exit is at least it; stay and transfer share the rest
    const exit = Math.max(pE, r.draftP ?? 0), stay0 = Math.max(0.01, 1 - pT - pE), k = (1 - exit) / (stay0 + pT);
    r.transferP = r3(pT * k); r.exitP = r3(exit); r.stayP = r3(stay0 * k);
    if (p.g === 'QB' && p.starter >= 0.5 && r.tid) qbOut[r.tid] = Math.max(qbOut[r.tid] || 0, pT * k);
    r.homeMi = p.dist != null ? Math.round(p.dist) : null; r.inState = p.inState;
    r.hcP = r2(c);
    r.tWhy = why(p, fit, x0, c);
    r._home = home; r._rz = rec?.grade ? (rec.grade - 80) / 5 : -1; r._prod = pf ? pf.pct - 0.5 : 0; r._st = pf?.starter ?? 0;
    // an entrenched starter: a top-quarter producer at a loaded program (talent z 1+) with a steady head coach.
    // In 2024-25, 8.5% of them moved (468), over a third of those after a coach change; one was a quarterback
    r._grade = rec?.grade || null; r._exp = p.exp;
    r._ent = level === 'P4' && (pf?.pct ?? 0) >= 0.75 && p.tal >= 1 && c < 0.3;
    n++;
  }
  return n;
}
// the biggest pushes and pulls on a player's Transfer%, in words, for the scouting report: each group's
// coefficient x (his feature - the training average), on the log-odds scale
const WHY_GROUPS = [
  [['exp2', 'exp3', 'exp4', 'exp5', 'exp5_starter'], (p) => ['', 'first-year', 'second-year', 'third-year', 'fourth-year', 'fifth-year+'][Math.min(Math.max(p.exp || 1, 1), 5)] + ' player'],
  [['ranked', 'rec'], (p, x) => x.ranked ? 'ranked recruit (more options)' : 'unranked recruit'],
  [['played', 'rec_dnp', 'q', 'pct', 'starter', 'pct_g5', 'st_g5'], (p, x) => !x.played ? 'not in the rotation yet' : p.level === 'G5' && x.pct >= 0.5 ? 'G5 producer: Power 4 programs come calling' : x.pct >= 0.5 ? 'producing (players who play stay)' : 'a backup with snaps to chase'],
  [['winp'], (p, x) => x.winp > 0 ? 'winning team' : 'losing team'],
  [['tal', 'pct_tal'], (p, x) => x.pct_tal >= 0.5 ? 'starring at a loaded program' : x.tal > 0.5 ? 'deep, talented program' : 'thin program'],
  [['qb_left'], (p) => `his starting QB may leave (${Math.round((p.qbP || 0) * 100)}%)`],
  [['gp', 'gp_g5', 'gp_fcs', 'spot'], (p, x) => x.spot ? `spot player (~${Math.round(x.gp * 13)} of 13 games)` : x.gp >= 0.7 ? (p.level === 'P4' ? 'plays every week' : 'plays every week: bigger programs notice') : x.gp > 0 ? 'limited playing time' : 'no game action yet'],
  [['hc'], (p, x, c) => `head-coach change odds ${Math.round(c * 100)}%`],
  [['logdist', 'inState', 'abroad'], (p) => p.dist == null ? 'hometown unknown' : p.inState ? `home-state school (${Math.round(p.dist)} mi from home)` : `${Math.round(p.dist)} mi from home`],
  [['xfer_in'], (p, x) => x.xfer_in ? 'just transferred in' : 'not a transfer'],
  [['g5', 'fcs'], (p) => p.level === 'G5' ? 'Group of 5 program' : p.level === 'FCS' ? 'FCS program' : 'Power 4 program'],
];
function why(p, fit, x, c) {
  const m = fit.transfer, mean = m.mean || [];
  const at = n => { const i = m.names.indexOf(n); return i < 0 ? [0, 0] : [m.coef[i], mean[i] ?? 0]; };
  const xx = { ...x, hc: c, qb_left: (p.g === 'WR' || p.g === 'TE') ? p.qbP || 0 : 0 };
  const out = WHY_GROUPS.map(([ns, say]) => [ns.reduce((s, n) => { const [b, mu] = at(n); return s + b * ((xx[n] ?? 0) - mu); }, 0), say(p, x, c)])
    .filter(([v]) => Math.abs(v) >= 0.1);
  return out.sort((a, b) => Math.abs(b[0]) - Math.abs(a[0])).slice(0, 4).map(([v, s]) => (v > 0 ? '+' : '−') + ' ' + s);
}

// ---- team builder ---------------------------------------------------------------------------------------
const CAP_GROWTH = 1.04;                   // the revenue-share cap rises 4% a year
const BAR_Q = 2 / 3;                        // the contender bar: the level's 67th percentile at the position
const SIMS = 400;
const POS_VALUE = { QB: 1, OL: 1, EDGE: 1, WR: 1, CB: 1, DL: 0.7, TE: 0.75, S: 0.75, LB: 0.7, RB: 0.7 };   // FV_POS_VALUE
const TARGET_MIN = { fbs: 0.08, fcs: 0.05 }; // Transfer% to count as a portal target
// the NIL budget is an estimate, not a hard cap: programs go over it (collectives raise more, boosters step in), and
// we only estimate it (yNIL summed). The true budget is taken as normal around the estimate with BUDGET_SD of it (an
// assumption: no program's real number is public). A dollar's cost is the chance it's past the true budget (money
// under it is use-it-or-lose-it), x OVER_COST: a dollar surely over has to buy its market worth (WAR at the
// level's going $ per WAR). So a program keeps or signs a player while his value per market dollar beats that cost
const BUDGET_SD = 0.25, OVER_COST = 1;
const ncdf = z => { const t = 1 / (1 + 0.2316419 * Math.abs(z)), d = 0.3989423 * Math.exp(-z * z / 2);
  const q = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274)))); return z > 0 ? 1 - q : q; };
const dollarCost = (spend, budget) => budget > 0 ? OVER_COST * ncdf((spend - budget) / (BUDGET_SD * budget)) : OVER_COST;
// flexible spots: when a room has an empty starting spot after the plan, its best spare player (past his own
// room's starters, 50%+ to be there) from a neighbouring room takes it: a DL slides out to edge, a safety to nickel
const FLEX = { EDGE: ['DL', 'LB'], DL: ['EDGE'], LB: ['S', 'EDGE'], S: ['CB', 'LB'], CB: ['S'], WR: ['TE', 'RB'], TE: ['WR'], RB: ['WR'], OL: [], QB: [] };
const UNKEPT_STAY = 0.25;                   // a player the budget can't keep at market still stays this often (loyalty, no offer)
const FCS_DISCOUNT = 0.6;                   // assumption: an FCS move-up's price against the level's going rate
const OPEN_RETOOL = 5;                     // open starting spots after the plan that make a team at least retool
// let-walk: a $150K+ returner, two at most, worth at most 1.5 AV over his backup; the target has to add twice what
// he's worth (a signing isn't certain) and a net 0.5 AV
const WALK_MIN = 1.5e5, WALK_MAX = 2, WALK_NET = 0.5, WALK_MARGIN = 2, WALK_MAX_LOSS = 1.5;
// receivers who left with their quarterback: in 2024-25, 8.5% of WR movers whose team also lost a QB to the
// portal landed at his school, 7.2x what chance gives (TE 5.7x; OL 3.9x and defenders 3.4-4.3x, the teammate base)
const QB_LINK = { WR: 7.2, TE: 5.7 };
const MIN_GAIN = 0.5;                       // AV a season at the Power 4: a signing has to be a real upgrade to the room (starter or depth);
                                            // scaled to each level by its contender bar (a G5 room's AV is ~1/4 a P4 room's, so 0.5 AV shut G5 plans out)
// a long shot: a target whose landing odds here are under twice a random school's (2 in 264) stays off the board and
// the plan. The landing model is weak (out of time, the actual school's median rank is 49 of 264), so below that line
// the odds are mostly noise, and a plan that pencils in a 1-in-264 signing isn't one a staff would run
const LAND_FLOOR = 2;

function rng(seed) { let s = seed >>> 0; return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; }; }
// the depth chart: each position's snap share by depth rank (players ranked by snaps, 2026 FBS through week 7,
// a missing player counted as 0), kept to ranks that average 8%+ and scaled so the shares sum to the starters.
// A backup is worth the snaps he plays, from rotation and injuries: a thin room costs AV a season
const DEPTH_W = { QB: [0.91, 0.09], RB: [0.54, 0.31, 0.15], WR: [0.99, 0.84, 0.64, 0.36, 0.17], TE: [0.55, 0.31, 0.14],
  OL: [0.97, 0.96, 0.93, 0.85, 0.7, 0.39, 0.2], EDGE: [0.68, 0.55, 0.38, 0.25, 0.14], DL: [0.59, 0.5, 0.37, 0.28, 0.18, 0.08],
  LB: [0.79, 0.64, 0.38, 0.2], CB: [0.93, 0.8, 0.6, 0.37, 0.2, 0.1], S: [0.85, 0.71, 0.33, 0.11] };
const DEPTH_N = g => Math.max(DEPTH_W[g].length, 3);   // spots shown on the chart (three deep at least)
const CHART_MIN = 0.15;                     // a player under a 15% chance of being there next season is left off the chart
const FILL = 20;                            // an empty backup spot: an ungraded player (the graded pool's floor)
// a room's AV a season from its FVs, best first: a starting spot never below replacement (the level's typical first
// backup), a backup spot as it is (FILL when empty), each weighted by its snap share
function roomAv(fvs, g, repl) {
  const W = DEPTH_W[g], n = STARTERS[g]; let a = 0;
  for (let k = 0; k < W.length; k++) a += W[k] * avOf(k < n ? Math.max(fvs[k] ?? repl, repl) : fvs[k] ?? FILL);
  return a;
}
const withFv = (fvs, f) => fvs.concat(f).sort((a, b) => b - a);
// next season's room by Monte Carlo: each player there with his chance (a returner's stay chance, a recruit's or
// redshirt's chance of being on the field here), the expected FV at each depth spot, the room's AV a season, and each
// player's expected depth rank (the chart order; absent counts as one past the chart)
function slots(players, g, repl, rand, sims = SIMS) {
  const n = STARTERS[g], D = DEPTH_N(g), acc = new Array(D).fill(0), rk = new Array(players.length).fill(0); let avAcc = 0;
  for (let s = 0; s < sims; s++) {
    const back = []; players.forEach((p, i) => { if (rand() < p.stay) back.push(i); else rk[i] += D; });
    back.sort((a, b) => players[b].fv - players[a].fv);
    back.forEach((i, k) => { rk[i] += Math.min(k, D); });
    const f = back.map(i => players[i].fv);
    for (let k = 0; k < D; k++) acc[k] += k < n ? Math.max(f[k] ?? repl, repl) : f[k] ?? FILL;
    avAcc += roomAv(f, g, repl);
  }
  return { fv: acc.map(x => x / sims), av: avAcc / sims, rank: rk.map(x => x / sims) };
}

// pull of home on where transfers land: measured share within each distance band over a random school's share
function pullOf(fit, mi) {
  const bands = fit.home?.moves?.pull; if (!bands || mi == null) return 1;
  for (const b of bands) { const [lo, hi] = b.miles.split(/[-+]/).map(Number); if (mi >= lo && (!hi || mi < hi)) return b.ratio; }
  return 1;
}
// landing odds (scripts/cfb_landing_fit.py, `landing` in the fit): if a player moves, the chance he picks each
// school, from a conditional logit on 2024-25 moves (level step, program talent and the prestige gap, record,
// playing time open at his position, miles from home and a home-state school). Each school's utility is
// computed against every FBS and FCS school, so a share is his odds of landing there, given he moves.
const SPOT = { QB: 'quarterback', RB: 'running back', WR: 'receiver', TE: 'tight end', OL: 'line', EDGE: 'edge', DL: 'D-line', LB: 'linebacker', CB: 'corner', S: 'safety' };
const LVL_RANK = { P4: 2, G5: 1, FCS: 0 };
const LAND_GROUPS = [
  [['dP4_oP4', 'dP4_oG5', 'dP4_oFCS', 'dG5_oP4', 'dG5_oG5', 'dG5_oFCS', 'down_rec', 'down_prod', 'down_st', 'up_prod'], (r, t) => r._lvl === 'FCS' && t.level === 'G5' ? 'FCS players move up to the G5 far more than to the P4'
    : r._lvl === t.level ? `a common ${t.level}-to-${t.level} move` : r._lvl === 'P4' ? 'P4 players drop to the G5 for a bigger role' : `a ${r._lvl}-to-${t.level} step up`],
  [['tal', 'tal_from', 'tal_rec', 'tal_prod'], () => 'program talent fits his level'],
  [['open'], (r) => `a starting ${SPOT[r.pos] || r.pos} job is opening`],
  [['logdist', 'inState'], (r, t, x) => x.inState ? `home-state school (${x.mi} mi)` : `${x.mi} mi from home`],
  [['winp'], () => 'a rebuilding program, more snaps'],
];
function landingModel(fit, geo, rows, teamList) {
  const L = fit.landing; if (!L) return null;
  const ix = Object.fromEntries(L.names.map((n, i) => [n, i])), b = L.coef;
  const winp = {}; for (const t of teamList) { const g = (t.rec?.w ?? 0) + (t.rec?.l ?? 0); if (g) winp[t.tid] = t.rec.w / g; }
  // playing time open: the share of each school's players at the position likely gone (1 - stay)
  const open = {}, openAll = {};
  for (const r of rows) if (r.tid && r.stayP != null) { const k = r.tid + '|' + r.pos; (open[k] ||= [0, 0]); open[k][0] += 1 - r.stayP; open[k][1]++;
    (openAll[r.pos] ||= [0, 0]); openAll[r.pos][0] += 1 - r.stayP; openAll[r.pos][1]++; }
  const schools = Object.entries(L.schools).filter(([j]) => geo.loc[j]).map(([j, [level, tal]]) => ({ tid: j, level, tal, loc: geo.loc[j], winp: winp[j] ?? 0.5 }));
  const feats = (r, s) => {
    const o = r._lvl, dn = +(LVL_RANK[s.level] < LVL_RANK[o]), up = +(LVL_RANK[s.level] > LVL_RANK[o]), mi = r._home ? miles(r._home, s.loc) : 600, tf = L.schools[r.tid]?.[1] ?? 0;
    const k = open[s.tid + '|' + r.pos], op = k && k[1] >= 2 ? k[0] / k[1] : (openAll[r.pos] ? openAll[r.pos][0] / openAll[r.pos][1] : 0.3);
    return { dP4_oP4: +(s.level === 'P4' && o === 'P4'), dP4_oG5: +(s.level === 'P4' && o === 'G5'), dP4_oFCS: +(s.level === 'P4' && o === 'FCS'),
      dG5_oP4: +(s.level === 'G5' && o === 'P4'), dG5_oG5: +(s.level === 'G5' && o === 'G5'), dG5_oFCS: +(s.level === 'G5' && o === 'FCS'),
      tal: s.tal, tal_from: s.tal * tf, tal_rec: s.tal * (r._rz ?? -1), tal_prod: s.tal * (r._prod ?? 0), winp: s.winp - 0.5, open: op,
      logdist: Math.log1p(mi / 100), inState: +(!!r._home && r._home[2] === s.loc[2]), mi: Math.round(mi),
      // his role by direction: a blue-chip or a starter rarely drops a level; a producer moves up
      down_rec: dn * Math.max(r._rz ?? -1, -1), down_prod: dn * (r._prod ?? 0), down_st: dn * (r._st ?? 0), up_prod: up * (r._prod ?? 0) };
  };
  const u = x => L.names.reduce((a, n) => a + b[ix[n]] * (x[n] ?? 0), 0);
  const cache = new Map();
  // {share: tid -> P(lands there | moves), why(tid): the two biggest reasons it's realistic}
  return r => {
    if (cache.has(r)) return cache.get(r);
    r._lvl ||= L.schools[r.tid]?.[0] || levelOf(r);   // the school's level (a row's conference can be missing)
    const xs = schools.filter(s => s.tid !== r.tid && !r._past?.has(s.tid)).map(s => [s, feats(r, s)]), us = xs.map(([, x]) => u(x)), m = Math.max(...us);
    const e = us.map(v => Math.exp(v - m)), z = e.reduce((a, v) => a + v, 0);
    const share = {}, X = {}; xs.forEach(([s, x], i) => { share[s.tid] = e[i] / z; X[s.tid] = x; });
    const mean = {}; for (const n of L.names) mean[n] = xs.reduce((a, [, x], i) => a + x[n] * e[i] / z, 0);
    const why = (tid, team) => { const x = X[tid]; if (!x) return [];
      return LAND_GROUPS.map(([ns, say]) => [ns.reduce((a, n) => a + b[ix[n]] * (x[n] - mean[n]), 0), say(r, team, x)]).filter(([v]) => v > 0.15)
        .sort((a, c) => c[0] - a[0]).slice(0, 2).map(([, w]) => w); };
    // fbs: his share for FBS schools combined (to condition on a move up, for an FCS player)
    const fbs = xs.reduce((a, [sc], i) => a + (sc.level !== 'FCS' ? e[i] / z : 0), 0);
    const out = { share, why, fbs }; cache.set(r, out); return out;
  };
}
const median = xs => { const v = xs.slice().sort((a, b) => a - b); return v.length ? v[Math.floor(v.length / 2)] : null; };

// rows: every graded FBS + FCS player with transferP etc.; teamList: teamModels output; price: $ per unit
// of worth in each NIL market ({p4, g5, fcs}, from the NIL block), to reprice a player in a new market
// a first- or second-year player is kept and released on what he projects to be next season, not on his snaps so
// far: the recruit thread's blend of board FV and recruit projection (young[].next, cfb_recruit.mjs) when he has
// one, else the FV his recruiting grade projects to (recruit model, 2026 rosters: grade 80 ~28, 86 ~33, 88 ~36, 90+ ~40)
const REC_FV = [[70, 22], [74, 24], [78, 26.6], [82, 30], [86, 33], [88, 36], [90, 40], [96, 43]];
const recFv = g => { if (!g) return null; if (g <= REC_FV[0][0]) return REC_FV[0][1];
  for (let i = 1; i < REC_FV.length; i++) if (g <= REC_FV[i][0]) { const [x0, y0] = REC_FV[i - 1], [x1, y1] = REC_FV[i]; return y0 + (y1 - y0) * (g - x0) / (x1 - x0); }
  return REC_FV.at(-1)[1]; };
// never let walk: a first-year player (his board FV is mostly priors on a few snaps, and his development years are
// what the program paid for), or a second-year player projecting to 40+ (an NFL rotation player)
const YOUNG_KEEP = 40;
// players follow a head coach who moves: in the 2025-26 cycle, 165 of the 422 transfers from the 15 FBS programs
// whose head coach took another FBS job went with him (39%; chance alone: 7, a 24x lift)
const HC_FOLLOW = 0.39;
// adds: next season's newcomers by team and position, from the recruit thread's last run (cfb-recruits.json): the
// class and the players on a roster with no snaps, each {name, fv (FV once on the field), stay (chance he's on the
// field here)}; the rest of the time he's off the chart
export function teamBuilder(rows, teamList, { fit, geo, price, season, young = {}, coachFlows = [], adds = {} }) {
  const hcFlow = {}; for (const f of coachFlows) if (f.role === 'HC') hcFlow[f.from + '>' + f.to] = (hcFlow[f.from + '>' + f.to] || 0) + f.p;
  const projFv = r => { if (!(r._exp <= 2)) return r.fv; const y = young[r.tid + '|' + r.name], g = recFv(r._grade); return Math.max(r.fv, y ?? g ?? r.fv); };
  const byTeam = {};
  for (const r of rows) if (r.tid && r.fv != null && STARTERS[r.pos]) (byTeam[r.tid] ||= []).push(r);
  const lvlOfTeam = t => P4_CONF.has(t.conf) || t.tid === ND ? 'P4' : 'G5';
  // $ per AV in each market: what the market pays per unit of on-field value (AV a season at his FV, plus the
  // floor every rostered player gets), players with 150+ snaps
  const rate = {};
  for (const m of ['P4', 'G5']) {
    const xs = rows.filter(r => r.div !== 'FCS' && levelOf(r) === m && r.xnil > 0 && (r.snaps ?? 0) >= 150 && r.fv != null);
    rate[m] = xs.reduce((a, r) => a + r.xnil, 0) / Math.max(1, xs.reduce((a, r) => a + avOf(r.fv) + avOf(30), 0));
    // and at each position: the market pays more for a QB's AV than a safety's, so a need is priced at its own rate
    rate[m + 'pos'] = {};
    for (const g of Object.keys(STARTERS)) { const ys = xs.filter(r => r.pos === g);
      rate[m + 'pos'][g] = ys.length >= 20 ? ys.reduce((a, r) => a + r.xnil, 0) / Math.max(1, ys.reduce((a, r) => a + avOf(r.fv) + avOf(30), 0)) : rate[m]; }
  }
  // replacement: the level's typical first backup at each position (FV of the (n+1)th best), the next man up
  // when a starter leaves (the graded pool stops short of walk-ons, so it never drops below 20)
  const repl = { P4: {}, G5: {} };
  for (const lvl of ['P4', 'G5']) for (const [g, n] of Object.entries(STARTERS)) {
    const v = teamList.filter(t => lvlOfTeam(t) === lvl).map(t => (byTeam[t.tid] || []).filter(r => r.pos === g).map(r => r.fv).sort((a, b) => b - a)[n] ?? 20);
    repl[lvl][g] = Math.max(20, median(v) ?? 20);
  }
  const mktOf = r => r.nilMkt || (r.div === 'FCS' ? 'fcs' : levelOf(r) === 'P4' ? 'p4' : 'g5');
  // his price moving to a program at this level: the level's going rate for AV at his position (the market's
  // average price at his FV), never below what he's worth where he is now
  // an FCS move-up signs below the going rate (FCS_DISCOUNT): few programs bid, and he's proving himself a level up
  const costAt = (r, lvl) => Math.round(Math.max(r.xnil || 0, (r.div === 'FCS' ? FCS_DISCOUNT : 1) * rate[lvl + 'pos'][r.pos] * (avOf(r.fv) + avOf(30))) / 1000) * 1000;
  // the contender bar per position and level: 67th percentile of this season's rooms (AV a season, depth by snaps)
  const nowAv = (ps, g, rp) => roomAv(ps.filter(r => r.pos === g).map(r => r.fv).sort((a, b) => b - a), g, rp);
  const bar = { P4: {}, G5: {} };
  for (const lvl of ['P4', 'G5']) for (const g of Object.keys(STARTERS)) {
    const v = teamList.filter(t => lvlOfTeam(t) === lvl).map(t => nowAv(byTeam[t.tid] || [], g, repl[lvl][g])).sort((a, b) => a - b);
    bar[lvl][g] = v.length ? v[Math.min(v.length - 1, Math.floor(BAR_Q * v.length))] : 0;
  }
  // the chance he moves to an FBS program: Transfer%, or for an FCS player his move-up odds (fetch_cfb.mjs FCS_UP: P(on
  // an FBS roster next season), fit on the 2023-26 FCS cycles with their FCS production, out-of-time AUC .73). Transfer%
  // has no FCS production in it (PFN grades FBS only), so it gives a top FCS producer the FCS base rate (~10%) where
  // the move-up model, which sees his production, has him at 50-95%
  const upOf = r => r.div === 'FCS' && r.up != null ? r.up : null, moveP = r => upOf(r) ?? r.transferP ?? 0;
  // the market: everyone likely to move, by position
  const pool = {};
  for (const r of rows) if (r.fv != null && STARTERS[r.pos] && r.xnil > 0 && moveP(r) >= (r.div === 'FCS' ? TARGET_MIN.fcs : TARGET_MIN.fbs) && !r._ent)
    (pool[r.pos] ||= []).push(r);
  const minGain = {}; for (const l of ['P4', 'G5']) minGain[l] = MIN_GAIN * Object.values(bar[l]).reduce((a, x) => a + x, 0) / Math.max(1e-9, Object.values(bar.P4).reduce((a, x) => a + x, 0));
  const land = landingModel(fit, geo, rows, teamList), landMin = LAND_FLOOR / (fit.landing ? Object.keys(fit.landing.schools).length : 264);
  const card = r => ({ name: r.name, pos: r.pos, team: r.team, logo: r.logo, fv: r.fv, cls: r.cls, photo: r.photo || null, div: r.div === 'FCS' ? 'FCS' : null,
    xnil: r.xnil || null, ynil: r.ynil ?? null, znil: r.znil ?? null, tp: r.transferP, dp: r.draftP ?? null, stay: r.stayP, star: r.star || null });
  const out = [];
  for (const t of teamList) {
    const ps = byTeam[t.tid] || [], lvl = lvlOfTeam(t), R = rate[lvl], Rg = rate[lvl + 'pos'], school = geo.loc[t.tid], rand = rng(+t.tid * 7919);
    const budget = Math.round((t.ynil || 0) * CAP_GROWTH / 1e4) * 1e4;
    // next year's freshman class costs about what this year's did: held back from the portal money
    const reserve = Math.round(ps.filter(r => r.elig === 1).reduce((a, r) => a + (r.ynil || 0), 0) * CAP_GROWTH / 1e4) * 1e4;
    // retention: each returner's edge over the next man up per dollar of his market price: the room's AV a season
    // with him less without him (everyone below moves up a spot; snap shares weight the spots, so a backup is worth
    // the snaps he'd play); keep the best value first until the budget (less the class reserve) runs out
    const edge = new Map();
    for (const g of Object.keys(STARTERS)) {
      const list = ps.filter(r => r.pos === g).sort((a, b) => projFv(b) - projFv(a)), fvs = list.map(projFv), full = roomAv(fvs, g, repl[lvl][g]);
      list.forEach((r, i) => edge.set(r, Math.max(0, full - roomAv(fvs.filter((_, j) => j !== i), g, repl[lvl][g]))));
    }
    const order = ps.filter(r => (r.stayP ?? 1) > 0.02).map(r => ({ r, cost: (r.stayP ?? 1) * (r.xnil || 0), v: edge.get(r) * R / Math.max(2e4, r.xnil || 0) }))
      .sort((a, b) => b.v - a.v);
    // keep him while his worth per market dollar beats the cost of the money (dollarCost at the midpoint of his deal)
    let kept = 0; const unkept = [];
    for (const o of order) { if (o.cost < 1e3 || o.v >= dollarCost(reserve + kept + o.cost / 2, budget)) kept += o.cost; else unkept.push(o); }
    const keepCost = Math.round(kept), space = budget - reserve - kept;
    const stayOf = r => unkept.some(o => o.r === r) ? Math.min(r.stayP ?? 1, UNKEPT_STAY) : (r.stayP ?? 1);
    // next season, before any moves: Monte Carlo returns, plus the class and the redshirts (adds)
    const P = {}, onRoster = new Set(ps.map(r => normName(r.name)));
    for (const [g, n] of Object.entries(STARTERS)) {
      const list = ps.filter(r => r.pos === g).map(r => ({ name: r.name, fv: projFv(r), stay: stayOf(r), kind: 'back' }))
        .concat((adds[t.tid]?.[g] || []).filter(a => !onRoster.has(normName(a.name)) && a.fv > FILL).map(a => ({ name: a.name, fv: a.fv, stay: a.stay, kind: a.kind })));
      const nv = nowAv(ps, g, repl[lvl][g]);
      P[g] = { n, nowAv: nv, list, next: slots(list, g, repl[lvl][g], rand),
        now: ps.filter(r => r.pos === g).sort((a, b) => b.fv - a.fv).slice(0, n).map(r => ({ name: r.name, fv: r.fv, stay: r2(stayOf(r)) })),
        depth: ps.filter(r => r.pos === g).map(r => ({ name: r.name, fv: r.fv, stay: r2(stayOf(r)), cls: r.cls })).sort((a, b) => b.fv * b.stay - a.fv * a.stay).slice(0, DEPTH_N(g)) };
    }
    const av26 = Object.values(P).reduce((a, x) => a + x.nowAv, 0), av27 = Object.values(P).reduce((a, x) => a + x.next.av, 0);
    // departures: likely gone and worth noting (a starter now, or 40+), and why
    const starterNow = new Set(Object.values(P).flatMap(x => x.now.map(n => n.name)));
    const leaving = ps.filter(r => 1 - stayOf(r) >= 0.35 && (r.fv >= 40 || starterNow.has(r.name))).map(r => {
      const priced = unkept.some(o => o.r === r) && (r.draftP ?? 0) < 0.3;
      return { ...card(r), gone: r2(1 - stayOf(r)),
        why: priced ? 'priced out' : (r.draftP ?? 0) >= 0.3 && (r.draftP ?? 0) >= r.transferP ? 'draft' : r.transferP >= 0.2 && r.transferP >= r.exitP - (r.draftP ?? 0) ? 'transfer' : 'eligibility' };
    }).sort((a, b) => avOf(b.fv) * b.gone - avOf(a.fv) * a.gone).slice(0, 10);
    // keep list: likely starters next season with real transfer risk, best edge first; raise = pay to his worth
    const keep = ps.filter(r => r.transferP >= 0.12 && (r.draftP ?? 0) < 0.5 && edge.get(r) >= 0.3 && !unkept.some(o => o.r === r))
      .map(r => ({ ...card(r), raise: Math.max(0, (r.xnil || 0) - (r.ynil || 0)), mi: r.homeMi, home: r.inState ? 'home state' : null, edge: r2(edge.get(r)) }))
      .sort((a, b) => b.tp * b.edge - a.tp * a.edge).slice(0, 6);
    // can't keep at market: valuable returners past the budget line
    const priced = unkept.filter(o => edge.get(o.r) >= 0.3).sort((a, b) => edge.get(b.r) - edge.get(a.r)).slice(0, 5)
      .map(o => ({ ...card(o.r), cost: Math.round(o.r.xnil || 0), edge: r2(edge.get(o.r)) }));
    const positions = Object.entries(P).map(([g, x]) => ({ g, n: x.n, now: x.now, depth: x.depth, next: x.next.fv.slice(0, x.n).map(r1), nowAv: r1(x.nowAv), nextAv: r1(x.next.av),
      bar: r1(bar[lvl][g]), repl: repl[lvl][g], need: r2((bar[lvl][g] - x.next.av) * (POS_VALUE[g] ?? 1)) }));
    // targets: for each position, players elsewhere who'd start here, by expected surplus
    // only players the program could plausibly pay: its portal space plus a standard error of the budget
    const targets = {}, reach = Math.max(space, 0) + BUDGET_SD * budget;
    for (const p of positions) {
      // he has to beat the lowest spot that plays real snaps (8%+), then add MIN_GAIN to the room
      const have = P[p.g].next.fv, base = roomAv(have, p.g, p.repl), weakest = have[DEPTH_W[p.g].length - 1];
      const cands = (pool[p.g] || []).filter(r => r.tid !== t.tid && !r._past?.has(t.tid) && r.fv >= weakest + 2);   // never back to a school he left
      // realistic targets: AV he adds per root dollar x the chance he moves x the chance he picks this school
      // (landing odds), so a G5 program's board fills with FCS move-ups and G5 movers it can actually sign
      targets[p.g] = cands.map(r => {
        const gain = roomAv(withFv(have, r.fv), p.g, p.repl) - base, cost = costAt(r, lvl), mi = r._home && school ? Math.round(miles(r._home, school)) : null;
        // an FCS move-up: his landing odds given he moves up (share among FBS schools)
        const L = land ? land(r) : null, raw = L ? L.share[t.tid] ?? 0 : pullOf(fit, mi) / 264, up = upOf(r);
        const share0 = up != null && L && L.fbs > 0 ? raw / L.fbs : raw;
        // his head coach taking this job (the coaching market's odds) pulls him along
        const hcp = hcFlow[r.tid + '>' + t.tid] || 0, share = (1 - hcp) * share0 + hcp * HC_FOLLOW;
        const surplus = gain * Rg[p.g] - cost;
        return { r, gain, cost, mi, share, raw, L, surplus, hcp, pm: moveP(r), score: gain * moveP(r) * share / Math.sqrt(Math.max(cost, 5e4)) };
      }).filter(c => c.gain >= minGain[lvl] && c.cost <= reach && Math.max(c.raw, c.share * (c.r.div === 'FCS' ? 0 : 1)) >= landMin).sort((a, b) => b.score - a.score).slice(0, 40)
        .map(c => ({ ...card(c.r), gain: r2(c.gain), cost: c.cost, surplus: Math.round(c.surplus), mi: c.mi, land: r3(c.share), tp: r3(c.pm), up: upOf(c.r) != null || undefined, odds: r3(c.pm * c.share),
          real: [...(c.hcp * HC_FOLLOW >= c.share / 3 ? ['his head coach could take this job (' + (c.hcp * 100).toFixed(1) + '%)'] : []), ...(c.L ? c.L.why(t.tid, { level: lvl }) : [])].slice(0, 2) }));
    }
    const needs = positions.filter(p => p.need > 0).sort((a, b) => b.need - a.need).map(p => p.g);
    const lossPct = av26 > 0 ? (av26 - av27) / av26 : 0;
    const fcs = Object.values(targets).flat().filter(x => x.div === 'FCS' && x.cost <= Math.max(space, 0)).sort((a, b) => b.gain * b.tp * b.land / b.cost - a.gain * a.tp * a.land / a.cost)[0] || null;
    out.push({
      tid: t.tid, team: t.team, full: t.full, abbr: t.abbr, logo: t.logo, color: t.color, conf: t.conf, level: lvl, hc: t.hc || null, rec: t.rec,
      budget, reserve, payroll: t.ynil, market: t.xnil, keepCost, space, rate: Math.round(R),
      av26: r1(av26), av27: r1(av27), lossPct: r2(lossPct), needs: needs.slice(0, 4),
      positions, leaving, keep, priced, targets, fcs, _P: P,
      _back: Object.fromEntries(Object.entries(STARTERS).map(([g, n]) => [g, Math.min(n, ps.filter(r => r.pos === g && stayOf(r) >= 0.5).length)])), _R: Rg, _space: space, _bar: bar[lvl],
      _budget: budget, _kept: order.filter(o => !unkept.includes(o) && o.cost >= WALK_MIN && !(o.r._exp <= 1 || (o.r._exp <= 2 && projFv(o.r) >= YOUNG_KEEP))).map(o => ({ r: o.r, cost: o.cost, loss: edge.get(o.r) * (o.r.stayP ?? 1) })),
    });
  }
  // the plan, as a market: a player can sit on at most SUITORS plans (a top portal player draws a few serious
  // suitors, not 30), and buyers take turns. Each team takes the biggest gap to the contender bar
  // first, its best expected surplus that fits the space; once the holes are filled, up to two best-value
  // signings that would start anywhere
  const demand = new Map(), SUITORS = 4, MAX_SIGN = 6;
  const buyers = out.slice().sort((a, b) => b._space - a._space);
  for (const T of buyers) Object.assign(T, { plan: [], _left: T._space, avPlan: T.av27, _have: Object.fromEntries(T.positions.map(p => [p.g, T._P[p.g].next.fv.slice()])), _done: false });
  // the money: a signing is worth its WAR at the level's going rate; the budget is soft, so past the estimate he has
  // to be worth what the money costs (dollarCost at the midpoint of his deal). left = estimate - spend (can be < 0)
  const affords = (T, gain, c, g, left) => gain * T._R[g] / Math.max(c.cost, 5e4) >= dollarCost(T._budget - left + c.cost / 2, T._budget);
  // round robin, like a draft: every buyer makes one move a round, richest first
  for (let round = 0; round < MAX_SIGN; round++) for (const T of buyers) {
    if (T._done) continue;
    const { _R: R, _bar: B, _have: have, plan } = T;
    let best = null;
    for (const p of T.positions) {
      const sl = have[p.g], base = roomAv(sl, p.g, p.repl);
      const gapAv = (B[p.g] - base) * (POS_VALUE[p.g] ?? 1);
      for (const c of T.targets[p.g] || []) {
        const k = c.name + '|' + c.team;
        if (plan.some(x => x.k === k) || (demand.get(k) || 0) >= SUITORS) continue;
        // the budget is use-it-or-lose-it, so a signing needn't beat the market rate, only the team's other
        // uses of the money: expected AV added (need-weighted, x Transfer%, x his landing odds here) per root dollar;
        // AV added is the room's, so a backup's worth is the snaps he'd play
        const gain = roomAv(withFv(sl, c.fv), p.g, p.repl) - base;
        if (gain < minGain[T.level] || !affords(T, gain, c, p.g, T._left)) continue;
        // a receiver follows a quarterback this plan already signs from his school
        const qb = QB_LINK[c.pos] ? plan.find(x => x.pos === 'QB' && x.team === c.team) : null;
        const land = qb ? Math.min(0.6, c.land * QB_LINK[c.pos]) : c.land;
        const v = gain * c.tp * land * (gapAv > 0 ? 1 + gapAv : 0.25) / Math.sqrt(Math.max(c.cost, 5e4));
        if (!best || v > best.v) best = { v, c: qb ? { ...c, land: r3(land), odds: r3(c.tp * land), real: ['follows QB ' + qb.name, ...(c.real || [])] } : c, k, g: p.g, gain, fill: gapAv > 0 };
      }
    }
    if (!best || (!best.fill && plan.filter(x => !x.fill).length >= 2)) { T._done = true; continue; }
    demand.set(best.k, (demand.get(best.k) || 0) + 1); T._left -= best.c.cost; T.avPlan += best.gain;
    have[best.g] = withFv(have[best.g], best.c.fv);
    plan.push({ ...best.c, k: best.k, gain: r2(best.gain), slot: best.g, fill: best.fill });
  }
  // letting players walk: a program can release a returner (or not match his market price) to free NIL money.
  // Release him when the money he'd cost (his xNIL x his chance to return), plus what's left, signs a realistic
  // target worth more than him: the target's AV over the weakest starter against his edge over the next man up
  // (AV x stay). Lowest AV per dollar first; see WALK_* for the limits.
  for (const T of buyers) {
    T.walk = [];
    const cands = T._kept.filter(w => w.loss <= WALK_MAX_LOSS).sort((a, b) => a.loss / a.cost - b.loss / b.cost);
    for (const w of cands) {
      if (T.walk.length >= WALK_MAX) break;
      const money = T._left + w.cost; let best = null;
      for (const p of T.positions) {
        const sl = T._have[p.g], base = roomAv(sl, p.g, p.repl);
        for (const c of T.targets[p.g] || []) {
          const k = c.name + '|' + c.team;
          if (T.plan.some(x => x.k === k) || (demand.get(k) || 0) >= SUITORS) continue;
          const gain = roomAv(withFv(sl, c.fv), p.g, p.repl) - base, net = gain - w.loss;
          if (gain < minGain[T.level] || net < WALK_NET * minGain[T.level] / MIN_GAIN || gain < WALK_MARGIN * w.loss) continue;
          // a swap: he's only worth signing with the released player's money
          if (affords(T, gain, c, p.g, T._left) || !affords(T, gain, c, p.g, money)) continue;
          const v = net * c.tp * c.land / Math.sqrt(c.cost);
          if (!best || v > best.v) best = { v, c, k, g: p.g, gain, net };
        }
      }
      if (!best) continue;
      demand.set(best.k, (demand.get(best.k) || 0) + 1);
      T._left = money - best.c.cost; T.avPlan += best.net; T.keepCost = Math.round(T.keepCost - w.cost); T._space += w.cost;
      T._have[best.g] = withFv(T._have[best.g], best.c.fv);
      T.plan.push({ ...best.c, k: best.k, gain: r2(best.gain), slot: best.g, fill: true, swap: w.r.name });
      const pos = T.positions.find(p => p.g === w.r.pos), d = pos && pos.depth.find(x => x.name === w.r.name); if (d) d.stay = 0;
      T.walk.push({ ...card(w.r), freed: Math.round(w.cost), loss: r2(w.loss), for: best.c.name, forPos: best.c.pos, net: r2(best.net) });
    }
    delete T._kept;
  }
  for (const T of buyers) {
    // over: spend past the estimate, and the chance the plan is past the true budget
    Object.assign(T, { left: Math.round(T._left), spend: Math.round(T._space - T._left), avPlan: r1(T.avPlan),
      over: Math.max(0, Math.round(-T._left)), overP: r2(ncdf(-T._left / (BUDGET_SD * T._budget || 1))) });
    delete T._left; delete T._have; delete T._done;
  }
  for (const T of out) for (const x of T.plan) x.rivals = out.filter(o => o !== T && o.plan.some(y => y.k === x.k)).map(o => o.team);
  for (const T of out) for (const x of T.plan) delete x.k;
  const qs = out.map(t => t.lossPct).sort((a, b) => a - b), hi = qs[Math.floor(qs.length * 2 / 3)], lo = qs[Math.floor(qs.length / 3)];
  for (const T of out) {
    for (const g in T.targets) T.targets[g] = T.targets[g].slice(0, 4).map(({ photo, ynil, znil, dp, stay, star, ...c }) => c);
    // open starting spots after the plan (no likely returner, no signing) make it more urgent, whatever the budget
    T.open = T.positions.reduce((a, p) => a + Math.max(0, p.n - T._back[p.g] - T.plan.filter(x => x.slot === p.g).length), 0);
    delete T._back;
  }
  // next season's full depth chart after the plan: returners, the class and redshirts, the signings in, released
  // players out, in expected depth order (absent counts as one past the chart). Its AV a season is the plan's
  for (const T of out) {
    const gone = new Set((T.walk || []).map(w => w.name)), rand = rng(+T.tid * 31);
    for (const p of T.positions) {
      const list = T._P[p.g].list.filter(a => !gone.has(a.name)).concat(T.plan.filter(s => s.slot === p.g).map(s => ({ name: s.name, fv: s.fv, stay: 1, kind: 'new', team: s.team })));
      const sim = slots(list, p.g, p.repl, rand), D = DEPTH_N(p.g);
      p.chart = list.map((a, i) => ({ a, k: sim.rank[i] })).filter(x => x.a.stay >= CHART_MIN).sort((u, v) => u.k - v.k).slice(0, D)
        .map(({ a }) => ({ name: a.name, fv: r1(a.fv), p: r2(a.stay), kind: a.kind, ...(a.team ? { team: a.team } : {}) }));
      while (p.chart.length < D) p.chart.push({ name: null, fv: p.chart.length < p.n ? p.repl : FILL, p: null, kind: 'open' });
      p.snaps = DEPTH_W[p.g]; p.planAv = r1(sim.av);
    }
    T.avPlan = r1(T.positions.reduce((a, p) => a + p.planAv, 0));
    // the lineup: the chart's first n are the starters (an open spot goes to the next man on the chart, whoever he
    // is), then flexible spots are filled from neighbouring rooms' spares; bench = the backups left, 50%+ to be there
    const P = Object.fromEntries(T.positions.map(p => [p.g, p])), used = new Set();
    for (const p of T.positions) {
      p.lineup = p.chart.filter(o => o.kind !== 'open').slice(0, p.n).map(o => ({ ...o }));
      p.lineup.forEach(o => used.add(o.name));
    }
    for (const p of T.positions) while (p.lineup.length < p.n) {
      let pick = null;
      for (const g of FLEX[p.g] || []) for (const o of P[g].chart.slice(P[g].n)) if (o.kind !== 'open' && !used.has(o.name) && (o.p ?? 1) >= 0.5 && (!pick || o.fv > pick.o.fv)) pick = { o, g };
      if (!pick || pick.o.fv < FILL + 2) { p.lineup.push({ name: null, fv: p.repl, p: null, kind: 'open' }); continue; }
      used.add(pick.o.name); p.lineup.push({ ...pick.o, from: pick.g });
    }
    for (const p of T.positions) {
      p.lineup.sort((a, b) => b.fv - a.fv);
      p.bench = p.chart.filter(o => o.kind !== 'open' && !used.has(o.name) && (o.p ?? 1) >= 0.5).slice(0, p.n);
    }
    T.open = T.positions.reduce((a, p) => a + p.lineup.filter(o => o.kind === 'open').length, 0);
  }
  // modes: squeeze if starters walk for money; otherwise by the share of this season's value leaving, in thirds,
  // moved up a step for the top third by open starting spots (and never below retool with OPEN_RETOOL+ open)
  const os = out.map(t => t.open).sort((a, b) => a - b), oHi = Math.max(OPEN_RETOOL, os[Math.floor(os.length * 2 / 3)]);
  const STEP = ['reinforce', 'retool', 'reload'];
  for (const T of out) {
    let k = T.lossPct >= hi ? 2 : T.lossPct >= lo ? 1 : 0;
    if (T.open >= oHi) k = Math.min(2, k + 1); else if (T.open >= OPEN_RETOOL) k = Math.max(k, 1);
    T.mode = T.priced.some(x => x.edge >= 1) ? 'squeeze' : STEP[k];
    T.buyer = T.space >= 0.4 * T.budget;
    T.space = Math.round(T.space); delete T._budget; delete T._P; delete T._R; delete T._space; delete T._bar;
  }
  out.sort((a, b) => a.team.localeCompare(b.team));
  return { season, next: season + 1, suitors: SUITORS, lossBands: [r2(lo), r2(hi)], capGrowth: CAP_GROWTH, barQ: BAR_Q, repl, bar, rate: Object.fromEntries(Object.entries(rate).map(([k, v]) => [k, typeof v === 'number' ? Math.round(v) : Object.fromEntries(Object.entries(v).map(([g, x]) => [g, Math.round(x)]))])), teams: out };
}
