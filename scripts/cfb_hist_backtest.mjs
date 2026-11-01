// The college game model (scripts/cfb_model.mjs) on 2015-26 ESPN history (scripts/cfb_espn_md.mjs): every season
// rated walk-forward exactly as runModel rates one, priors chained season to season, then scored on the project split
// (tune 2016-20, held out 2021-26; 2015 is burn-in), paired per game with clustered errors (game day, home team-season).
//   node scripts/cfb_hist_backtest.mjs [espn_md.json.gz]
// What it answers:
//   1. Fit scheme: the live scheme (prior weights from last season only, margin weights from the last two seasons)
//      against weights pooled over every earlier season (expanding window), on the same inputs.
//   2. Prior: last season's anchor (final Elo, Massey margin, efficiency) and the roster inputs, walk-forward.
//   3. Inputs: each candidate on top of the base, entered on tune and vetoed by held out (scripts/harness.mjs rule).
// Writes data/cfb_hist_backtest.json.
import zlib from 'node:zlib';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { _internals as I, phi, fitBeta, CAND, HIST_FIT } from './cfb_model.mjs';
import { paired } from './harness.mjs';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const mdPath = process.argv[2] || path.join(ROOT, 'scripts', '.cache', 'cfb', 'espn_md.json.gz');
const data = JSON.parse(zlib.gunzipSync(fs.readFileSync(mdPath)));
for (const k of ["talent", "returning", "sp", "pfnRet", "weather"]) data[k] ||= {};
const FIRST = 2015, LAST = 2026, TUNE = [2016, 2020], HOLD = [2021, 2026];
const SEASONS = []; for (let S = FIRST; S <= LAST; S++) if (data.games[S]?.length) SEASONS.push(S);
const mean = xs => xs.reduce((a, b) => a + b, 0) / Math.max(1, xs.length);
const sd = xs => { const m = mean(xs); return Math.sqrt(mean(xs.map(x => (x - m) ** 2))) || 1; };
const r2 = x => Math.round(x * 100) / 100, r3 = x => Math.round(x * 1000) / 1000, r4 = x => Math.round(x * 1e4) / 1e4;
const ll = (p, y) => { p = Math.min(1 - 1e-9, Math.max(1e-9, p)); return -(y * Math.log(p) + (1 - y) * Math.log(1 - p)); };
const FCS = 'FCS';
const inTune = S => S >= TUNE[0] && S <= TUNE[1], inHold = S => S >= HOLD[0] && S <= HOLD[1];

// roster inputs by season (scripts/cfb_roster_prior.py feats, every season when run with --all-feats)
const RPATH = path.join(ROOT, 'scripts', 'data', 'cfb_roster_feats.json');
data.roster = process.env.ROSTER ? JSON.parse(fs.readFileSync(process.env.ROSTER, 'utf8')).feats || {} : fs.existsSync(RPATH) ? JSON.parse(fs.readFileSync(RPATH, 'utf8')).feats || {} : {};

// ---- setup, as runModel ------------------------------------------------------------------------------------
const nameId = {};
for (const S of SEASONS) for (const g of data.games[S]) { nameId[g.homeTeam] = String(g.homeId); nameId[g.awayTeam] = String(g.awayId); g.homeId = String(g.homeId); g.awayId = String(g.awayId); }
const fbsBy = {};
for (const S of SEASONS) { fbsBy[S] = new Set(); for (const g of data.games[S]) { if (g.homeClassification === 'fbs') fbsBy[S].add(g.homeId); if (g.awayClassification === 'fbs') fbsBy[S].add(g.awayId); } }
const allGames = SEASONS.flatMap(S => data.games[S]);
const geo = I.places(data.venues, data.teamsFbs, allGames);
const rows = I.prepare(SEASONS, data, geo);
const gameById = Object.fromEntries(rows.map(r => [r.id, r]));
I.setExtra([]);
const effBy = Object.fromEntries(SEASONS.map(S => [S, I.effObs(data.adv[S], nameId, gameById, fbsBy[S], I.rzByGame(data.drives?.[S]), data.sit?.[S])]));
for (const S of SEASONS) I.decisions(effBy[S]);
const stBy = {}, stPrior = {};
for (const S of SEASONS) {
  // special-teams curves from the seasons up to this one (no peeking at later kicking)
  const C = I.stCurves(SEASONS.filter(s => s <= S).flatMap(s => data.drives?.[s] || []));
  stBy[S] = I.stObs(data.drives?.[S], nameId, gameById, fbsBy[S], C);
  const last = stBy[S - 1] ? I.stAt(stBy[S - 1], 99) : {};
  stPrior[S] = Object.fromEntries(Object.entries(last).map(([t, v]) => [t, 0.5 * v]));
}
// P4 by season: Pac-12 counts through 2023
const P4C = new Set(['SEC', 'Big Ten', 'Big 12', 'ACC']);
const isP4 = (conf, cls, t, S) => cls === 'fbs' && (P4C.has(conf) || (conf === 'Pac-12' && S <= 2023) || t === '87') ? 1 : 0;
const P4T = {}; for (const r of rows) { const T = (P4T[r.S] ||= {}); T[r.h] = isP4(r.hconf, r.hc, r.h, r.S); T[r.a] = isP4(r.aconf, r.ac, r.a, r.S); }
I.setCtx(data.weather || {}, Object.fromEntries(SEASONS.map(S => [S, Object.fromEntries(Object.entries(data.roster?.[S] || {}).map(([t, f]) => [t, { qb: f.qbRet ?? 0, rest: f.offRet ?? 0 }]))])));
console.log(`${rows.length} games, ${SEASONS[0]}-${SEASONS.at(-1)}; roster feats for ${Object.keys(data.roster).length} seasons`);

// ---- priors, chained -----------------------------------------------------------------------------------
// pts: the regression for a team's season-end Massey margin on its features; PRI picks the features. W for season S
// from seasons in win(S) (live: S-1 only; pooled: every season from 2016 to S-1), 2016 from itself (burn-in)
const P0 = { k: 20, eloHome: 55, lam: 3 };
const PRI = {
  roster: f => [1, f.sp, f.tal247, f.offRet, f.qbRetE, f.offIn],               // live features; sp falls back to last final Elo
  rosterMass: f => [1, f.mass, f.tal247, f.offRet, f.qbRetE, f.offIn],
  rosterMassElo: f => [1, f.mass, f.sp, f.tal247, f.offRet, f.qbRetE, f.offIn],
  rosterMassNet: f => [1, f.mass, f.net, f.tal247, f.offRet, f.qbRetE, f.offIn],
  anchorOnly: f => [1, f.mass],
  // returning college WAR from PFN (2020 on; scripts/cfb_ret_war.mjs), every position and every position but QB
  rosterAv: f => [1, f.sp, f.tal247, f.offRet, f.qbRetE, f.offIn, f.av],
  rosterAvRest: f => [1, f.sp, f.tal247, f.offRet, f.qbRetE, f.offIn, f.avRest],
  // transfer level jump (scripts/cfb_roster_prior.py --jump): transfers in from stronger S-1 teams, and the signed jump
  rosterJDn: f => [1, f.sp, f.tal247, f.offRet, f.qbRetE, f.offIn, f.jDn ?? 0],
  rosterJump: f => [1, f.sp, f.tal247, f.offRet, f.qbRetE, f.offIn, f.jump ?? 0],
};
function pooledFit(list) {
  // list of [F, final]: merge with season-prefixed keys
  const F = {}, fin = { mass: {}, eff: { ppa: { O: {}, D: {} }, ppp: { O: {}, D: {} }, pace: { O: {}, D: {} } } };
  list.forEach(([f, x], i) => {
    for (const [t, v] of Object.entries(f)) {
      const k = i + '|' + t; F[k] = v;
      if (x.mass[t] != null) fin.mass[k] = x.mass[t];
      for (const a of ['ppa', 'ppp', 'pace']) for (const s of ['O', 'D']) if (x.eff[a][s][t] != null) fin.eff[a][s][k] = x.eff[a][s][t];
    }
  });
  return I.fitPrior(F, fin);
}
// PFN returning production by season (scripts/cfb_ret_war.mjs; 2020 on)
const RWP = process.env.RETWAR || path.join(ROOT, 'scripts', '.cache', 'cfb', 'ret_war.json');
const RW = fs.existsSync(RWP) ? JSON.parse(fs.readFileSync(RWP, 'utf8')) : {};
function chain(priKey, win = 'pooled', P = P0, minFit = SEASONS[0] + 1) {
  const keep = I.PRIOR_X.pts; I.PRIOR_X.pts = PRI[priKey];
  const finals = {}, priors = {}, W = {}, Fs = {}, raw = {};
  const S0 = SEASONS[0];
  priors[S0] = { pts: {}, ppa: {}, ppp: {}, pace: {} };
  finals[S0] = I.finalOf(S0, rows, effBy[S0], fbsBy[S0], null, P);
  for (const S of SEASONS.slice(1)) {
    const F = I.priorFeatures(S, data, fbsBy[S], nameId, finals);
    const f = finals[S - 1];
    for (const x of Object.values(F)) x.mass = NaN;
    for (const [t, x] of Object.entries(F)) { x.mass = f?.mass[t] ?? f?.mass[FCS] ?? -15; const w = RW[S]?.[t]; x.av = w?.av ?? 0; x.avRest = w?.avRest ?? 0; x.qbW = w?.qb ?? 0; }
    Fs[S] = F;
    raw[S] = I.finalOf(S, rows, effBy[S], fbsBy[S], null, P, finals);   // the target (Massey needs no prior)
    const from = SEASONS.filter(s => s >= minFit && s < S && (win === 'pooled' || s === S - 1));
    W[S] = pooledFit((from.length ? from : [S]).map(s => [Fs[s], raw[s]]));
    priors[S] = I.applyPrior(F, W[S]);
    finals[S] = { ...I.finalOf(S, rows, effBy[S], fbsBy[S], priors[S], P, finals), mass: raw[S].mass };
  }
  I.PRIOR_X.pts = keep;
  return { finals, priors, W };
}

// ---- walk and fit --------------------------------------------------------------------------------------
const P = { k: 20, eloHome: 70, lam: 1.5 };
function walkAll(ch, p = P) {
  const out = {};
  for (const S of SEASONS.slice(1)) out[S] = I.walk(rows, effBy, fbsBy, ch.priors, p, [S], ch.finals, {}, stBy, stPrior).filter(q => q.r.done && q.r.fbsGame);
  return out;
}
// margin weights for season S's games: from the walk predictions of seasons in the window (live: S-2 and S-1;
// pooled: 2016 to S-1); extra(p) adds candidate columns
function predict(W, { win = 'pooled', extra = () => [], cols = null, first = TUNE[0], fit = {} } = {}) {
  const sub = ps => ps.map(p => { const x = cols ? cols.map(i => p.x[i]) : p.x; return { r: p.r, x: [...x, ...extra(p)] }; });
  const out = [];
  for (const S of SEASONS.filter(S => S >= first + 1)) {
    const from = SEASONS.filter(s => s >= first && s < S && (win === 'pooled' || s >= S - 2));
    const { beta, sigma } = fitBeta(from.flatMap(s => sub(W[s])), fit);
    for (const p of sub(W[S])) {
      const m = I.dot(beta, [1, ...p.x]), ph = phi(m / sigma), y = p.r.m > 0 ? 1 : p.r.m < 0 ? 0 : 0.5;
      out.push({ id: p.r.id, S, w: p.r.w, m, ph, y, ll: ll(ph, y), ae: Math.abs(p.r.m - m), close: p.r.close, res: p.r.m, day: p.r.date.slice(0, 10), ht: p.r.h + '|' + S });
    }
  }
  return out;
}
const sumUp = o => ({ n: o.length, logLoss: r4(mean(o.map(x => x.ll))), mae: r2(mean(o.map(x => x.ae))) });
function cmp(a, b, key = 'll', tune = inTune, hold = inHold) {
  const side = f => { const A = a.filter(x => f(x.S)), B = b.filter(x => f(x.S)); const t = paired(A.map(x => x[key]), B.map(x => x[key]), [A.map(x => x.day), A.map(x => x.ht)]);
    return { d: r4(t.d), t: r2(t.t), n: t.n }; };
  // 2016 has no earlier walk season to fit on, so tune is scored on 2017-20
  return { tune: side(tune), held: side(hold) };
}
const split = o => ({ tune: sumUp(o.filter(x => inTune(x.S))), held: sumUp(o.filter(x => inHold(x.S))) });
const vsClose = o => { const mk = o.filter(x => x.close != null), sM = sd(mk.map(x => x.res - x.close));
  return { n: mk.length, model: r4(mean(mk.map(x => x.ll))), close: r4(mean(mk.map(x => ll(phi(x.close / sM), x.y)))), maeModel: r2(mean(mk.map(x => x.ae))), maeClose: r2(mean(mk.map(x => Math.abs(x.res - x.close)))) }; };

// transfer level jump, portal era only (JUMP=1; Oct 26 2026): prior weights pooled from 2021, margin weights from 2021,
// tune 2022-23, held out 2024 on. Needs roster feats with jDn / jump (ROSTER=...). Oct 26 2026 (p4, aggr; 2015-25 history):
// jDn LL tune t -0.8, held +0.23; jump -0.08 / +0.99. Both fail; not in the live prior
if (process.env.JUMP) {
  data.talent ||= {}; data.returning ||= {}; data.sp ||= {};
  const X = (process.env.SHIPX || 'p4,aggr').split(','), T = S => S >= 2022 && S <= 2023, H = S => S >= 2024;
  I.setExtra(X);
  const base = predict(walkAll(chain('roster', 'pooled', P0, 2021)), { first: 2021 });
  const out = { extra: X, base: { tune: sumUp(base.filter(x => T(x.S))), held: sumUp(base.filter(x => H(x.S))) } };
  for (const k of ['rosterJDn', 'rosterJump']) {
    const ch = chain(k, 'pooled', P0, 2021), o = predict(walkAll(ch), { first: 2021 });
    out[k] = { ll: cmp(o, base, 'll', T, H), mae: cmp(o, base, 'ae', T, H), w: ch.W[SEASONS.at(-1)]?.pts.map(r3) };
    console.log('jump', k, JSON.stringify(out[k]));
  }
  console.log('jump base', JSON.stringify(out.base));
  process.exit(0);
}
const report = { asof: new Date().toISOString().slice(0, 10), seasons: [SEASONS[0], SEASONS.at(-1)], tune: TUNE, held: HOLD };
// 1. fit scheme on the live prior features
const chLive = chain('roster', 'last'), chPool = chain('roster', 'pooled');
const WL = walkAll(chLive), WP = walkAll(chPool);
const live = predict(WL, { win: 'last2' }), poolBeta = predict(WL, { win: 'pooled' }), poolBoth = predict(WP, { win: 'pooled' });
report.scheme = {
  live: { ...split(live), close: vsClose(live.filter(x => inHold(x.S))) },
  pooledMargin: { ...split(poolBeta), vsLive: cmp(poolBeta, live), vsLiveMae: cmp(poolBeta, live, 'ae') },
  pooledBoth: { ...split(poolBoth), vsLive: cmp(poolBoth, live), vsLiveMae: cmp(poolBoth, live, 'ae'), close: vsClose(poolBoth.filter(x => inHold(x.S))) },
};
console.log('scheme', JSON.stringify(report.scheme));
fs.writeFileSync(process.env.BT_OUT || path.join(ROOT, 'data', 'cfb_hist_backtest.json'), JSON.stringify(report, null, 1));

// sections 2-5 are skipped with ONLYSHIP=1 (the ship comparison alone, at the grid's pick)
const T2 = S => S >= 2021 && S <= 2022, H2 = S => S >= 2023;
let bestP = { k: 20, eloHome: 55, lam: 1.5 }, bestLL;

// SP+ history in the prior (SPDIR=dir of CFBD ratings/sp files sp<S>.json, pulled by cfb_game_history.mjs): last
// season's final SP+ in place of last season's final Elo (sp falls back to Elo for teams SP+ doesn't rate), and next
// to it, on the shipped setting (pooled weights, inputs p4, aggr, ret). Scored on the project split and on 2021-26.
// Nov 1 2026 (SP+ 2015-25 from the cfb-research artifact, 1432 of 1438 team-seasons matched; RETWAR from
// cfb_ret_war.mjs; data/cfb_sp_prior_test.json): log loss, the CFB gate, fails on tune for both forms (SP+ for Elo
// t +0.53, held -0.63; SP+ next to Elo t -0.11, held -0.98). MAE: SP+ next to Elo t -1.97 tune, -1.50 held (13.07 ->
// 13.02, 12.67 -> 12.64). Not shipped: the live prior stays on last season's Elo
if (process.env.SPDIR) {
  const X = (process.env.SHIPX || 'p4,aggr,ret').split(',');
  I.setCtx({}, RW); I.setExtra(X);
  PRI.rosterEloSp = f => [1, f.elo, f.sp, f.tal247, f.offRet, f.qbRetE, f.offIn];
  const run = k => predict(walkAll(chain(k, 'pooled'), bestP), { fit: HIST_FIT.fit });
  data.sp = {};
  const base = run('roster');
  let hit = 0, all = 0;
  for (const S of SEASONS) {
    const p = path.join(process.env.SPDIR, `sp${S}.json`);
    if (!fs.existsSync(p)) continue;
    data.sp[S] = JSON.parse(fs.readFileSync(p, 'utf8')).filter(x => x.team !== 'nationalAverages');
    for (const x of data.sp[S]) { all++; if (nameId[x.team] && fbsBy[S].has(nameId[x.team])) hit++; }
  }
  const out = { extra: X, P: bestP, spSeasons: Object.keys(data.sp), matched: `${hit}/${all}`, base: { ...split(base), all: sumUp(base.filter(x => x.S >= 2021)) } };
  for (const k of ['roster', 'rosterEloSp']) {
    const o = run(k);
    out[k === 'roster' ? 'spForElo' : 'spAndElo'] = { ...split(o), ll: cmp(o, base), mae: cmp(o, base, 'ae'), ll2: cmp(o, base, 'll', T2, H2), close: vsClose(o.filter(x => x.S >= 2021)) };
  }
  console.log('sp', JSON.stringify(out, null, 1));
  fs.writeFileSync(process.env.BT_OUT || path.join(ROOT, 'data', 'cfb_sp_prior_test.json'), JSON.stringify(out, null, 1));
  process.exit(0);
}
if (!process.env.ONLYSHIP) {
// 2. prior features (pooled scheme)
report.prior = {};
const priorW = {};
for (const k of Object.keys(PRI)) {
  const ch = k === 'roster' ? chPool : chain(k, 'pooled'), W = k === 'roster' ? WP : walkAll(ch), o = k === 'roster' ? poolBoth : predict(W);
  priorW[k] = { ch, W, o };
  report.prior[k] = { ...split(o), vsRoster: cmp(o, poolBoth), wk1to4: cmp(o.filter(x => x.w <= 4), poolBoth.filter(x => x.w <= 4)), weights2026: ch.W[2026]?.pts.map(r3) };
  console.log('prior', k, JSON.stringify(report.prior[k]));
}
fs.writeFileSync(process.env.BT_OUT || path.join(ROOT, 'data', 'cfb_hist_backtest.json'), JSON.stringify(report, null, 1));

// 3. hyperparameters (Elo K and home field, efficiency shrink), on the tuning seasons
report.grid = [];
bestLL = Infinity;
for (const k of [15, 20, 25, 30]) for (const eloHome of [55, 70, 85]) for (const lam of [1.5, 3]) {
  const p = { k, eloHome, lam }, o = predict(walkAll(chPool, p)), t = sumUp(o.filter(x => inTune(x.S)));
  report.grid.push({ ...p, tune: t.logLoss, held: sumUp(o.filter(x => inHold(x.S))).logLoss });
  if (t.logLoss < bestLL) { bestLL = t.logLoss; bestP = p; }
}
report.bestP = bestP;
console.log('grid best', JSON.stringify(bestP), bestLL);

// 4. inputs: forward selection on the tuning seasons (paired clustered t <= -1.5, every weight the right sign), held
// out reported and veto; PFN returning production (2020 on) separately below
const POOL = Object.keys(CAND).filter(k => !CAND[k].sit && !['wxc', 'qbRet', 'ret', 'avRet', 'avRest'].includes(k));
I.setExtra(POOL);
const WX = walkAll(chPool, bestP);
I.setExtra([]);
const nb = I.BASE_FEATS.length, base = I.BASE_FEATS.map((_, i) => i), colOf = k => nb + POOL.indexOf(k);
const tuneRows = WX => SEASONS.filter(inTune).flatMap(S => WX[S]);
const signOk = (W, keys) => { const w = fitBeta(tuneRows(W).map(p => ({ r: p.r, x: [...base, ...keys.map(colOf)].map(i => p.x[i]) }))).beta.slice(1 + nb);
  return w.every((v, i) => v * (CAND[keys[i]].sign ?? 1) > 0); };
const baseO = predict(WX, { cols: base });
report.inputs = { pool: POOL, base: split(baseO), alone: {}, steps: [] };
for (const k of POOL) { const o = predict(WX, { cols: [...base, colOf(k)] }); report.inputs.alone[k] = { ...cmp(o, baseO), mae: cmp(o, baseO, 'ae') }; }
console.log('alone', JSON.stringify(report.inputs.alone));
let chosen = [], refO = baseO;
for (;;) {
  const tries = POOL.filter(k => !chosen.includes(k)).map(k => { const o = predict(WX, { cols: [...base, ...[...chosen, k].map(colOf)] }); return { k, o, c: cmp(o, refO) }; })
    .filter(x => signOk(WX, [...chosen, x.k])).sort((a, b) => a.c.tune.t - b.c.tune.t);
  const b = tries[0];
  if (!b || b.c.tune.t > -1.5) { report.inputs.steps.push({ add: null, best: b?.k, ...b?.c }); break; }
  chosen.push(b.k); report.inputs.steps.push({ add: b.k, ...b.c, mae: cmp(b.o, refO, 'ae') }); refO = b.o;
  console.log('add', b.k, JSON.stringify(b.c));
}
report.inputs.chosen = chosen;
report.inputs.final = { ...split(refO), vsBase: cmp(refO, baseO), vsBaseMae: cmp(refO, baseO, 'ae'), close: vsClose(refO.filter(x => inHold(x.S))) };
// the live inputs (p4, qbRet, aggr): p4 and aggr here; qbRet with the PFN block
report.inputs.liveSet = (() => { const ks = ['p4', 'aggr'], o = predict(WX, { cols: [...base, ...ks.map(colOf)] }); return { keys: ks, ...split(o), vsChosen: cmp(o, refO) }; })();
fs.writeFileSync(process.env.BT_OUT || path.join(ROOT, 'data', 'cfb_hist_backtest.json'), JSON.stringify(report, null, 1));

// 5. PFN returning production, 2020 on: as inputs on top of the chosen model (fit from 2020, tune 2021-22, held
// 2023-26), and returning WAR in the preseason prior (prior weights pooled from 2020)
I.setCtx({}, RW);
const PF = ['qbRet', 'ret', 'avRet', 'avRest'];
I.setExtra([...chosen, ...PF]);
const WR = walkAll(chPool, bestP);
I.setExtra([]);
const nc = nb + chosen.length, cOf = k => nc + PF.indexOf(k), baseR = [...base, ...chosen.map((_, i) => nb + i)];
const refR = predict(WR, { cols: baseR, first: 2020 });
report.pfn = { note: 'fit from 2020, tune 2021-22, held out 2023-26', inputs: {} };
for (const k of PF) { const o = predict(WR, { cols: [...baseR, cOf(k)], first: 2020 }); report.pfn.inputs[k] = { ...cmp(o, refR, 'll', T2, H2), mae: cmp(o, refR, 'ae', T2, H2) }; }
console.log('pfn inputs', JSON.stringify(report.pfn.inputs));
const PRI2 = {
  roster: PRI.roster,
  rosterAv: f => [1, f.sp, f.tal247, f.offRet, f.qbRetE, f.offIn, f.av],
  rosterAvRest: f => [1, f.sp, f.tal247, f.offRet, f.qbRetE, f.offIn, f.avRest],
  avForRoster: f => [1, f.sp, f.tal247, f.av, f.offIn],
};
report.pfn.prior = {};
I.setExtra(chosen);
let pr0 = null;
for (const [k, fx] of Object.entries(PRI2)) {
  PRI[k] = fx;
  const ch = chain(k, 'pooled', P0, 2020), o = predict(walkAll(ch, bestP), { first: 2020 });
  if (!pr0) pr0 = o;
  report.pfn.prior[k] = { ...cmp(o, pr0, 'll', T2, H2), mae: cmp(o, pr0, 'ae', T2, H2), wk1to4: cmp(o.filter(x => x.w <= 4), pr0.filter(x => x.w <= 4), 'll', T2, H2), weights2026: ch.W[2026]?.pts.map(r3) };
  console.log('pfn prior', k, JSON.stringify(report.pfn.prior[k]));
}
I.setExtra([]);
fs.writeFileSync(process.env.BT_OUT || path.join(ROOT, 'data', 'cfb_hist_backtest.json'), JSON.stringify(report, null, 1));

}

// 6. the shipped setting (cfb_model.mjs HIST_FIT) against the live scheme, same inputs where they overlap. Live: prior
// weights from last season, margin weights from the last two, inputs p4, qbRet, aggr; shipped: weights pooled over
// every season since 2016, inputs p4, aggr, ret (PFN returning production, 2020 on), the roster prior. Also the
// ESPN-only candidate (no PFN: p4 and aggr). Scored 2021-26: tune 2021-22, held 2023-26 (PFN inputs fit from 2020).
// Oct 23 2026: shipped vs live log loss .4828 vs .4858 (tune t -1.3, held t -1.1; MAE t -3.0, -2.2), MAE 12.72 vs 12.91. Each part passes on its own: the pooled scheme (t -1.7, -1.7) and ret on top of it (t -1.9, -2.4); returning
// non-QB WAR in the prior (rosterAvRest) and qbRet added nothing on top
const LIVEX = ['p4', 'qbRet', 'aggr'], SHIPX = (process.env.SHIPX || 'p4,aggr,ret').split(','), SHIPPRI = process.env.SHIPPRI || 'roster';
I.setExtra(LIVEX); const oLive = predict(walkAll(chain('roster', 'last', P0), bestP), { win: 'last2', first: 2020 });
const SF = +(process.env.SHIPFIRST || 2016);
I.setCtx({}, RW);
I.setExtra(SHIPX); const chShip = chain(SHIPPRI, 'pooled', P0, SF === 2020 ? 2020 : SEASONS[0] + 1), oShip = predict(walkAll(chShip, bestP), { first: SF });
I.setExtra(['p4', 'aggr']); const oEspn = predict(walkAll(chPool, bestP));
I.setExtra([]);
const A21 = S => S >= 2021;
report.ship = { extra: SHIPX, prior: SHIPPRI, P: bestP, priorWeights2026: chShip.W[2026]?.pts.map(r3),
  live: { tune: sumUp(oLive.filter(x => T2(x.S))), held: sumUp(oLive.filter(x => H2(x.S))), all: sumUp(oLive.filter(x => A21(x.S))) },
  ship: { tune: sumUp(oShip.filter(x => T2(x.S))), held: sumUp(oShip.filter(x => H2(x.S))), all: sumUp(oShip.filter(x => A21(x.S))), close: vsClose(oShip.filter(x => A21(x.S))) },
  vsLive: cmp(oShip, oLive, 'll', T2, H2), vsLiveMae: cmp(oShip, oLive, 'ae', T2, H2), vsEspnOnly: cmp(oShip, oEspn, 'll', T2, H2), vsEspnOnlyMae: cmp(oShip, oEspn, 'ae', T2, H2),
  espnOnly: { all: sumUp(oEspn.filter(x => A21(x.S))), vsLive: cmp(oEspn, oLive, 'll', T2, H2), vsLiveMae: cmp(oEspn, oLive, 'ae', T2, H2) },
  bySeason: Object.fromEntries(SEASONS.filter(A21).map(S => [S, { live: sumUp(oLive.filter(x => x.S === S)), ship: sumUp(oShip.filter(x => x.S === S)) }])) };
console.log('ship', JSON.stringify(report.ship));
fs.writeFileSync(process.env.BT_OUT || path.join(ROOT, 'data', 'cfb_hist_backtest.json'), JSON.stringify(report, null, 1));
export { SEASONS, rows, chain, walkAll, predict, cmp, split, report };
