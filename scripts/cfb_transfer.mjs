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
// need-weighted AV per dollar (x Transfer% x the measured pull of home) that fits its space.
import fs from 'node:fs';
import path from 'node:path';
import { avOf, STARTERS } from './cfb_teams.mjs';

const r1 = x => Math.round(x * 10) / 10, r2 = x => Math.round(x * 100) / 100, r3 = x => Math.round(x * 1000) / 1000;
const sig = z => 1 / (1 + Math.exp(-z));
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
    };
    // a coaching change is unknown until it happens: average over its fitted chance (record, level)
    const c = sig(h.coef[0] + h.coef[1] * (p.winp - 0.5) + h.coef[2] * (level === 'G5') + h.coef[3] * (level === 'FCS'));
    const x0 = features(p, 0), x1 = features(p, 1);
    const pT = (1 - c) * sig(lin(fit.transfer, x0, latest)) + c * sig(lin(fit.transfer, x1, latest));
    const pE = sig(lin(fit.exit, x0));
    // Draft% is the better read on leaving for the NFL: exit is at least it; stay and transfer share the rest
    const exit = Math.max(pE, r.draftP ?? 0), stay0 = Math.max(0.01, 1 - pT - pE), k = (1 - exit) / (stay0 + pT);
    r.transferP = r3(pT * k); r.exitP = r3(exit); r.stayP = r3(stay0 * k);
    r.homeMi = p.dist != null ? Math.round(p.dist) : null; r.inState = p.inState;
    r.hcP = r2(c);
    r.tWhy = why(p, fit, x0, c);
    r._home = home;
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
  [['hc'], (p, x, c) => `head-coach change odds ${Math.round(c * 100)}%`],
  [['logdist', 'inState', 'abroad'], (p) => p.dist == null ? 'hometown unknown' : p.inState ? `home-state school (${Math.round(p.dist)} mi from home)` : `${Math.round(p.dist)} mi from home`],
  [['xfer_in'], (p, x) => x.xfer_in ? 'just transferred in' : 'not a transfer'],
  [['g5', 'fcs'], (p) => p.level === 'G5' ? 'Group of 5 program' : p.level === 'FCS' ? 'FCS program' : 'Power 4 program'],
];
function why(p, fit, x, c) {
  const m = fit.transfer, mean = m.mean || [];
  const at = n => { const i = m.names.indexOf(n); return i < 0 ? [0, 0] : [m.coef[i], mean[i] ?? 0]; };
  const xx = { ...x, hc: c };
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
const UNKEPT_STAY = 0.25;                   // a player the budget can't keep at market still stays this often (loyalty, no offer)
const BENCH_SHARE = 0.15;                   // a backup's worth to the team, as a share of a starter's edge over replacement
const MIN_GAIN = 0.5;                       // AV a season: a signing has to be a real upgrade on the weakest starter

function rng(seed) { let s = seed >>> 0; return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; }; }
// expected FV at each starting slot next season: each player back with his stay chance, holes at replacement
function slots(players, n, repl, rand, sims = SIMS) {
  const acc = new Array(n).fill(0); let avAcc = 0;
  for (let s = 0; s < sims; s++) {
    const back = []; for (const p of players) if (rand() < p.stay) back.push(p.fv);
    back.sort((a, b) => b - a);
    for (let k = 0; k < n; k++) { const f = Math.max(back[k] ?? repl, repl); acc[k] += f; avAcc += avOf(f); }
  }
  return { fv: acc.map(x => x / sims), av: avAcc / sims };
}

// pull of home on where transfers land: measured share within each distance band over a random school's share
function pullOf(fit, mi) {
  const bands = fit.home?.moves?.pull; if (!bands || mi == null) return 1;
  for (const b of bands) { const [lo, hi] = b.miles.split(/[-+]/).map(Number); if (mi >= lo && (!hi || mi < hi)) return b.ratio; }
  return 1;
}
const median = xs => { const v = xs.slice().sort((a, b) => a - b); return v.length ? v[Math.floor(v.length / 2)] : null; };

// rows: every graded FBS + FCS player with transferP etc.; teamList: teamModels output; price: $ per unit
// of worth in each NIL market ({p4, g5, fcs}, from the NIL block), to reprice a player in a new market
export function teamBuilder(rows, teamList, { fit, geo, price, season }) {
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
  const costAt = (r, lvl) => Math.round(Math.max(r.xnil || 0, rate[lvl + 'pos'][r.pos] * (avOf(r.fv) + avOf(30))) / 1000) * 1000;
  // the contender bar per position and level: 67th percentile of this season's starters (AV a season)
  const nowAv = (ps, g, n, rp) => { const f = ps.filter(r => r.pos === g).map(r => r.fv).sort((a, b) => b - a).slice(0, n); while (f.length < n) f.push(rp); return f.reduce((a, x) => a + avOf(x), 0); };
  const bar = { P4: {}, G5: {} };
  for (const lvl of ['P4', 'G5']) for (const [g, n] of Object.entries(STARTERS)) {
    const v = teamList.filter(t => lvlOfTeam(t) === lvl).map(t => nowAv(byTeam[t.tid] || [], g, n, repl[lvl][g])).sort((a, b) => a - b);
    bar[lvl][g] = v.length ? v[Math.min(v.length - 1, Math.floor(BAR_Q * v.length))] : 0;
  }
  // the market: everyone likely to move, by position
  const pool = {};
  for (const r of rows) if (r.fv != null && STARTERS[r.pos] && r.xnil > 0 && (r.transferP ?? 0) >= (r.div === 'FCS' ? TARGET_MIN.fcs : TARGET_MIN.fbs))
    (pool[r.pos] ||= []).push(r);
  const card = r => ({ name: r.name, pos: r.pos, team: r.team, logo: r.logo, fv: r.fv, cls: r.cls, photo: r.photo || null, div: r.div === 'FCS' ? 'FCS' : null,
    xnil: r.xnil || null, ynil: r.ynil ?? null, znil: r.znil ?? null, tp: r.transferP, dp: r.draftP ?? null, stay: r.stayP, star: r.star || null });
  const out = [];
  for (const t of teamList) {
    const ps = byTeam[t.tid] || [], lvl = lvlOfTeam(t), R = rate[lvl], Rg = rate[lvl + 'pos'], school = geo.loc[t.tid], rand = rng(+t.tid * 7919);
    const budget = Math.round((t.ynil || 0) * CAP_GROWTH / 1e4) * 1e4;
    // next year's freshman class costs about what this year's did: held back from the portal money
    const reserve = Math.round(ps.filter(r => r.elig === 1).reduce((a, r) => a + (r.ynil || 0), 0) * CAP_GROWTH / 1e4) * 1e4;
    // retention: each returner's edge over the next man up (AV a season; backups a share of it) per dollar of his
    // market price; keep the best value first until the budget (less the class reserve) runs out
    const edge = new Map();
    for (const [g, n] of Object.entries(STARTERS)) {
      const list = ps.filter(r => r.pos === g).sort((a, b) => b.fv - a.fv), next = list[n]?.fv ?? repl[lvl][g];
      list.forEach((r, i) => edge.set(r, Math.max(0, avOf(r.fv) - avOf(Math.max(next, repl[lvl][g]))) * (i < n ? 1 : BENCH_SHARE)));
    }
    const order = ps.filter(r => (r.stayP ?? 1) > 0.02).map(r => ({ r, cost: (r.stayP ?? 1) * (r.xnil || 0), v: edge.get(r) * R / Math.max(2e4, r.xnil || 0) }))
      .sort((a, b) => b.v - a.v);
    let kept = 0; const unkept = [];
    for (const o of order) { if (kept + o.cost <= budget - reserve || o.cost < 1e3) kept += o.cost; else unkept.push(o); }
    const keepCost = Math.round(kept), space = budget - reserve - kept;
    const stayOf = r => unkept.some(o => o.r === r) ? Math.min(r.stayP ?? 1, UNKEPT_STAY) : (r.stayP ?? 1);
    // next season, before any moves: Monte Carlo returns
    const P = {};
    for (const [g, n] of Object.entries(STARTERS)) {
      const list = ps.filter(r => r.pos === g).map(r => ({ fv: r.fv, stay: stayOf(r) }));
      const nv = nowAv(ps, g, n, repl[lvl][g]);
      P[g] = { n, nowAv: nv, next: slots(list, n, repl[lvl][g], rand),
        now: ps.filter(r => r.pos === g).sort((a, b) => b.fv - a.fv).slice(0, n).map(r => ({ name: r.name, fv: r.fv, stay: r2(stayOf(r)) })),
        depth: ps.filter(r => r.pos === g).map(r => ({ name: r.name, fv: r.fv, stay: r2(stayOf(r)), cls: r.cls })).sort((a, b) => b.fv * b.stay - a.fv * a.stay).slice(0, n + 1) };
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
    const positions = Object.entries(P).map(([g, x]) => ({ g, n: x.n, now: x.now, depth: x.depth, next: x.next.fv.map(r1), nowAv: r1(x.nowAv), nextAv: r1(x.next.av),
      bar: r1(bar[lvl][g]), repl: repl[lvl][g], need: r2((bar[lvl][g] - x.next.av) * (POS_VALUE[g] ?? 1)) }));
    // targets: for each position, players elsewhere who'd start here, by expected surplus
    const targets = {};
    for (const p of positions) {
      const weakest = Math.min(...P[p.g].next.fv);
      const cands = (pool[p.g] || []).filter(r => r.tid !== t.tid && r.fv >= weakest + 2 && (lvl === 'P4' || levelOf(r) !== 'P4' || r.transferP >= 0.25));
      targets[p.g] = cands.map(r => {
        const gain = avOf(r.fv) - avOf(weakest), cost = costAt(r, lvl), mi = r._home && school ? Math.round(miles(r._home, school)) : null;
        const surplus = gain * Rg[p.g] - cost, pull = pullOf(fit, mi);
        return { r, gain, cost, mi, pull, surplus, score: gain * r.transferP * Math.sqrt(pull) / Math.sqrt(Math.max(cost, 5e4)) };
      }).filter(c => c.gain >= MIN_GAIN).sort((a, b) => b.score - a.score).slice(0, 40)
        .map(c => ({ ...card(c.r), gain: r2(c.gain), cost: c.cost, surplus: Math.round(c.surplus), mi: c.mi, pull: c.pull }));
    }
    const needs = positions.filter(p => p.need > 0).sort((a, b) => b.need - a.need).map(p => p.g);
    const lossPct = av26 > 0 ? (av26 - av27) / av26 : 0;
    const fcs = Object.values(targets).flat().filter(x => x.div === 'FCS' && x.cost <= Math.max(space, 0)).sort((a, b) => b.surplus - a.surplus)[0] || null;
    out.push({
      tid: t.tid, team: t.team, full: t.full, abbr: t.abbr, logo: t.logo, color: t.color, conf: t.conf, level: lvl, hc: t.hc || null, rec: t.rec,
      budget, reserve, payroll: t.ynil, market: t.xnil, keepCost, space, rate: Math.round(R),
      av26: r1(av26), av27: r1(av27), lossPct: r2(lossPct), needs: needs.slice(0, 4),
      positions, leaving, keep, priced, targets, fcs, _P: P, _R: Rg, _space: space, _bar: bar[lvl],
    });
  }
  // the plan, as a market: a player can sit on at most SUITORS plans (a top portal player draws a few serious
  // suitors, not 30), and buyers take turns. Each team takes the biggest gap to the contender bar
  // first, its best expected surplus that fits the space; once the holes are filled, up to two best-value
  // signings that would start anywhere
  const demand = new Map(), SUITORS = 4, MAX_SIGN = 6;
  const buyers = out.slice().sort((a, b) => b._space - a._space);
  for (const T of buyers) Object.assign(T, { plan: [], _left: T._space, avPlan: T.av27, _have: Object.fromEntries(T.positions.map(p => [p.g, T._P[p.g].next.fv.slice()])), _done: false });
  // round robin, like a draft: every buyer makes one move a round, richest first
  for (let round = 0; round < MAX_SIGN; round++) for (const T of buyers) {
    if (T._done || T._left <= 0) continue;
    const { _R: R, _bar: B, _have: have, plan } = T;
    let best = null;
    for (const p of T.positions) {
      const sl = have[p.g], weakest = Math.min(...sl), wi = sl.indexOf(weakest);
      const gapAv = (B[p.g] - sl.reduce((a, f) => a + avOf(f), 0)) * (POS_VALUE[p.g] ?? 1);
      for (const c of T.targets[p.g] || []) {
        const k = c.name + '|' + c.team;
        if (plan.some(x => x.k === k) || (demand.get(k) || 0) >= SUITORS || c.cost > T._left || c.fv < weakest + 2) continue;
        // the budget is use-it-or-lose-it, so a signing needn't beat the market rate, only the team's other
        // uses of the money: expected AV added (need-weighted, x Transfer%, x the pull of home) per root dollar
        const gain = avOf(c.fv) - avOf(weakest);
        if (gain < MIN_GAIN) continue;
        const v = gain * c.tp * c.pull * (gapAv > 0 ? 1 + gapAv : 0.25) / Math.sqrt(Math.max(c.cost, 5e4));
        if (!best || v > best.v) best = { v, c, k, g: p.g, wi, gain, fill: gapAv > 0 };
      }
    }
    if (!best || (!best.fill && plan.filter(x => !x.fill).length >= 2)) { T._done = true; continue; }
    demand.set(best.k, (demand.get(best.k) || 0) + 1); T._left -= best.c.cost; T.avPlan += best.gain;
    have[best.g][best.wi] = best.c.fv;
    plan.push({ ...best.c, k: best.k, gain: r2(best.gain), slot: best.g, fill: best.fill });
  }
  for (const T of buyers) {
    Object.assign(T, { left: Math.round(T._left), spend: Math.round(T._space - T._left), avPlan: r1(T.avPlan) });
    delete T._left; delete T._have; delete T._done;
  }
  for (const T of out) for (const x of T.plan) x.rivals = out.filter(o => o !== T && o.plan.some(y => y.k === x.k)).map(o => o.team);
  for (const T of out) for (const x of T.plan) delete x.k;
  // modes: squeeze if starters walk for money; otherwise by how much of this season's value leaves, in thirds
  const qs = out.map(t => t.lossPct).sort((a, b) => a - b), hi = qs[Math.floor(qs.length * 2 / 3)], lo = qs[Math.floor(qs.length / 3)];
  for (const T of out) {
    for (const g in T.targets) T.targets[g] = T.targets[g].slice(0, 3).map(({ photo, ynil, znil, dp, stay, star, ...c }) => c);
    T.mode = T.priced.some(x => x.edge >= 1) ? 'squeeze' : T.lossPct >= hi ? 'reload' : T.lossPct >= lo ? 'retool' : 'reinforce';
    T.buyer = T.space >= 0.4 * T.budget;
    T.space = Math.round(T.space); delete T._P; delete T._R; delete T._space; delete T._bar;
  }
  out.sort((a, b) => a.team.localeCompare(b.team));
  return { season, next: season + 1, suitors: SUITORS, lossBands: [r2(lo), r2(hi)], capGrowth: CAP_GROWTH, barQ: BAR_Q, repl, bar, rate: Object.fromEntries(Object.entries(rate).map(([k, v]) => [k, typeof v === 'number' ? Math.round(v) : Object.fromEntries(Object.entries(v).map(([g, x]) => [g, Math.round(x)]))])), teams: out };
}
