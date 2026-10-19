// Weight audit for the game model (scripts/cfb_model.mjs), offline, on the live model's own inputs (the dump
// scripts/cfb_game_backtest.mjs reads):  W8=<tal|prior|scale|ridge|all> node scripts/cfb_weight_audit.mjs <md.json.gz>
// Season-swap CV as in cfb_game_backtest.mjs. Oct 2026 (2025 + 2026 through week 6, 1,380 games), on the model before
// this audit (in-season talent + talent from week 5, Elo 19 a prior point, ridge 1): CV log loss .4484, MAE 12.66
//   tal    in-season talent, every form, on top of the prior: none .4437 (t -2.8, MAE -0.07); all season .4503;
//          early weeks .4464; fading over 5/8 weeks .4451/.4461; by week group .4466 (bowls -3.8: opt-outs?).
//          Late-season talent fits a negative weight. Shipped: none (talent stays in the prior)
//   prior  talent out of the prior costs MAE +0.04 (t 2.1), 2026 log loss +.0025; returning WAR for returning PPA
//          -.0013 (t -0.8; 2026 alone -.0041, t -1.5): near miss; usage, pass/rush/receiving split, tal x ret,
//          returning QB WAR: noise; FV team talent in the 2026 prior -.0009 (leaks: FV is built mid-season)
//   scale  the prior's points into Elo's start: 0.6-0.9x best, 0.8x -.0016 (t -2.1). Shipped: 19 -> 15 Elo a point
//   ridge  on the margin weights: 5 -.0012 (t -2.3, MAE -0.02), 20 -.0023 (t -1.5, MAE worse in 2026). Shipped: 5
// The selection then keeps p4, qbRet, aggr: CV log loss .4483 -> .4418, MAE 12.63 -> 12.57 (runModel's report).
// Oct 19 rerun (current model, dump through week 7; CFBD quota still spent, so no new box scores or lines): returning
//   WAR for returning PPA 2026 -.0035 (t -1.5), pooled t -1.1; FV talent in the 2026 prior -.0022 (leaks). Only 2026
//   tests the prior out of sample (2025's prior is fit on 2025), so neither ships until 2015-23 history is pulled.
// Rerun on the current model, its baselines are the shipped settings, so the talent forms are added to it.
import zlib from 'node:zlib';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { _internals as I, phi, fitBeta } from './cfb_model.mjs';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const [mdPath, qbPath] = process.argv.slice(2);
const data = JSON.parse(zlib.gunzipSync(fs.readFileSync(mdPath)));
const QBG = qbPath && fs.existsSync(qbPath) ? JSON.parse(fs.readFileSync(qbPath, 'utf8')) : null;
const SEASON = 2026, LIVE = ['p4', 'qbRet', 'aggr'], P = { k: 20, eloHome: 70, lam: 1.5 };
const mean = xs => xs.reduce((a, b) => a + b, 0) / Math.max(1, xs.length);
const sd = xs => { const m = mean(xs); return Math.sqrt(mean(xs.map(x => (x - m) ** 2))) || 1; };
const r2 = x => Math.round(x * 100) / 100, r3 = x => Math.round(x * 1000) / 1000, r4 = x => Math.round(x * 1e4) / 1e4;
const dot = I.dot;
const ll = (p, y) => { p = Math.min(1 - 1e-9, Math.max(1e-9, p)); return -(y * Math.log(p) + (1 - y) * Math.log(1 - p)); };
const FCS = 'FCS';

// ---- the live model, rebuilt (runModel's setup, minus the grid: P is what the grid picks) ------------------------
const seasons = [SEASON - 2, SEASON - 1, SEASON];
const nameId = {};
for (const S of seasons) for (const g of data.games[S]) { nameId[g.homeTeam] = String(g.homeId); nameId[g.awayTeam] = String(g.awayId); }
for (const S of seasons) for (const g of data.games[S]) { g.homeId = String(g.homeId); g.awayId = String(g.awayId); }
const fbsBy = {};
for (const S of seasons) { fbsBy[S] = new Set(); for (const g of data.games[S]) { if (g.homeClassification === 'fbs') fbsBy[S].add(g.homeId); if (g.awayClassification === 'fbs') fbsBy[S].add(g.awayId); } }
const allGames = seasons.flatMap(S => data.games[S]);
const geo = I.places(data.venues, data.teamsFbs, allGames);
const rows = I.prepare(seasons, data, geo);
const gameById = Object.fromEntries(rows.map(r => [r.id, r]));
I.setExtra([]);
const effBy = Object.fromEntries(seasons.map(S => [S, I.effObs(data.adv[S], nameId, gameById, fbsBy[S], I.rzByGame(data.drives?.[S]), data.sit?.[S])]));
for (const S of seasons) I.decisions(effBy[S]);
const stC = I.stCurves(seasons.flatMap(S => data.drives?.[S] || []));
const stBy = {}, stPrior = {};
for (const S of seasons) {
  stBy[S] = I.stObs(data.drives?.[S], nameId, gameById, fbsBy[S], stC);
  const last = stBy[S - 1] ? I.stAt(stBy[S - 1], 99) : {};
  stPrior[S] = Object.fromEntries(Object.entries(last).map(([t, v]) => [t, 0.5 * v]));
}
const talBy = {};
for (const S of seasons) {
  const list = (data.talent?.[S] || []).map(x => [nameId[x.team], x.talent]).filter(([t, v]) => t && fbsBy[S].has(t) && v != null);
  const m = mean(list.map(x => x[1])), s0 = sd(list.map(x => x[1]));
  talBy[S] = Object.fromEntries(list.map(([t, v]) => [t, (v - m) / s0]));
}
const P0 = { k: 20, eloHome: 55, lam: 3 };
const [S0, S1] = seasons;
// the preseason prior, as runModel builds it; pts: the regression for a team's season-end margin rating (PRIOR_X.pts)
// on its features, which here can also carry mass (last season's final margin rating, built the same way every season)
function buildPriors(pts = null) {
  const keep = I.PRIOR_X.pts; if (pts) I.PRIOR_X.pts = pts;
  const finals = {}, priors = {}, W = {};
  const withMass = (F, S) => { const f = finals[S - 1]; for (const [t, x] of Object.entries(F)) x.mass = f?.mass[t] ?? f?.mass[FCS] ?? -15; return F; };
  priors[S0] = { pts: {}, ppa: {}, ppp: {}, pace: {} };
  finals[S0] = I.finalOf(S0, rows, effBy[S0], fbsBy[S0], null, P0);
  const F1 = withMass(I.priorFeatures(S1, data, fbsBy[S1], nameId, finals), S1);
  finals[S1] = I.finalOf(S1, rows, effBy[S1], fbsBy[S1], null, P0, finals);
  W[S1] = I.fitPrior(F1, finals[S1]);
  priors[S1] = I.applyPrior(F1, W[S1]);
  const mass1 = finals[S1].mass;
  finals[S1] = { ...I.finalOf(S1, rows, effBy[S1], fbsBy[S1], priors[S1], P0, finals), mass: mass1 };
  const F2 = withMass(I.priorFeatures(SEASON, data, fbsBy[SEASON], nameId, finals), SEASON);
  priors[SEASON] = I.applyPrior(F2, W[S1]);
  I.PRIOR_X.pts = keep;
  return { finals, priors, W, F1, F2 };
}
const wx = data.weather || {};
I.setCtx(wx, data.pfnRet || {});
I.setExtra(LIVE);
let { finals, priors, W, F1, F2 } = buildPriors();
const walkS = (S, p = P, pr = priors, fi = finals) => I.walk(rows, effBy, fbsBy, pr, p, [S], fi, talBy, stBy, stPrior).filter(p => p.r.done && p.r.fbsGame);
let A = walkS(S1), B = walkS(SEASON);
console.log(`walk: ${A.length} games ${S1}, ${B.length} ${SEASON}`);

// ---- cross-validation ----------------------------------------------------------------------------------------
// extra(p): candidate columns for one game (known before kickoff). Returns per-game out-of-sample predictions,
// B's games then A's (the order runModel uses)
function cv(extra = () => [], folds = [A, B]) {
  const sub = ps => ps.map(p => ({ r: p.r, x: [...p.x, ...extra(p)], t: p.t }));
  const [a, b] = folds.map(sub), out = [];
  for (const [fit, on] of [[a, b], [b, a]]) {
    const { beta, sigma } = fitBeta(fit);
    for (const p of on) {
      const m = dot(beta, [1, ...p.x]), ph = phi(m / sigma), y = p.r.m > 0 ? 1 : p.r.m < 0 ? 0 : 0.5;
      out.push({ r: p.r, m, ph, y, ll: ll(ph, y), ae: Math.abs(p.r.m - m), sigma });
    }
  }
  return out;
}
const fitAll = extra => fitBeta([...A, ...B].map(p => ({ r: p.r, x: [...p.x, ...extra(p)] })));
function compare(o, ref) {
  const d = o.map((x, i) => x.ll - ref[i].ll), e = o.map((x, i) => x.ae - ref[i].ae);
  return { logLoss: r4(mean(o.map(x => x.ll))), dLogLoss: r4(mean(d)), t: r2(mean(d) / (sd(d) / Math.sqrt(d.length))), mae: r2(mean(o.map(x => x.ae))), dMae: r3(mean(e)), tMae: r2(mean(e) / (sd(e) / Math.sqrt(e.length))) };
}
let ref = cv();
let mk = ref.filter(x => x.r.close != null), sM = sd(mk.map(x => x.r.m - x.r.close));

// ======== weight audit ========================================================================================
const W8 = process.env.W8 || 'all';
// cv with a transform of each game's columns (drop / replace base inputs); xs(p) -> new x
function cvX(xs, folds = [A, B], ridge = null) {
  const sub = ps => ps.map(p => ({ r: p.r, x: xs(p), t: p.t }));
  const [a, b] = folds.map(sub), out = [], ws = [];
  for (const [fit, on] of [[a, b], [b, a]]) {
    const { beta, sigma } = ridge == null ? fitBeta(fit) : fitR(fit, ridge);
    ws.push(beta);
    for (const p of on) {
      const m = dot(beta, [1, ...p.x]), ph = phi(m / sigma), y = p.r.m > 0 ? 1 : p.r.m < 0 ? 0 : 0.5;
      out.push({ r: p.r, m, ph, y, ll: ll(ph, y), ae: Math.abs(p.r.m - m), sigma });
    }
  }
  const all = fitBeta([...a, ...b]).beta.slice(1);
  return { o: out, w: all };
}
function fitR(ps, ridge) {   // fitBeta with another ridge on the margin weights
  const ok = ps;
  const beta = [0, ...I.ols(ok.map(p => p.x), ok.map(p => Math.max(-45, Math.min(45, p.r.m))), ridge, 0)];
  const res = ok.map(p => p.r.m - dot(beta, [1, ...p.x])), sM0 = sd(res);
  const lw = s => ok.reduce((a2, p) => { const q = Math.min(1 - 1e-9, Math.max(1e-9, phi(dot(beta, [1, ...p.x]) / s))), y = p.r.m > 0 ? 1 : p.r.m < 0 ? 0 : 0.5;
    return a2 - y * Math.log(q) - (1 - y) * Math.log(1 - q); }, 0);
  let sigma = sM0; for (let f = 0.5; f <= 1.2001; f += 0.02) if (lw(sM0 * f) < lw(sigma)) sigma = sM0 * f;
  return { beta, sigma };
}
const NAMES = [...I.BASE_FEATS, ...LIVE];
const show = (label, r, ref0 = ref, cols = null) => {
  const c = compare(r.o, ref0), s26 = r.o.filter(x => x.r.S === SEASON), s26r = ref0.filter(x => x.r.S === SEASON);
  const d26 = s26.map((x, i) => x.ll - s26r[i].ll);
  console.log(label.padEnd(34), JSON.stringify({ ...c, ll2026: r4(mean(s26.map(x => x.ll))), d2026: r4(mean(d26)) }), cols ? JSON.stringify(Object.fromEntries(cols.map((n, i) => [n, r3(r.w[i])]))) : '');
  return c;
};
const OUT = {};
const base = cvX(p => p.x);
OUT.live = show('live', base, ref, NAMES);
// ---- 1. in-season talent, every form ---------------------------------------------------------------------------
if (W8 === 'all' || W8 === 'tal') {
  const tz = (S, t) => fbsBy[S].has(t) ? talBy[S]?.[t] ?? 0 : -2, td = p => tz(p.r.S, p.r.h) - tz(p.r.S, p.r.a);   // talent gap (z)
  const drop = (p) => p.x;
  const nm = (ks, add = []) => [...NAMES, ...add];
  const forms = {
    none:      [p => p.x, nm([])],
    live0:     [p => [...p.x, td(p), p.r.w >= 5 ? td(p) : 0], nm([], ['talent', 'talentLate'])],
    allSeason: [p => [...p.x, td(p)], nm([], ['talent'])],
    lateOnly:  [p => [...p.x, p.r.w >= 5 ? td(p) : 0], nm([], ['talentLate'])],
    early4:    [p => [...p.x, p.r.w <= 4 ? td(p) : 0], nm([], ['tal wk<=4'])],
    decay8:    [p => [...p.x, td(p) * Math.max(0, 1 - (p.r.w - 1) / 8)], nm([], ['tal x fade 8wk'])],
    decay5:    [p => [...p.x, td(p) * Math.max(0, 1 - (p.r.w - 1) / 5)], nm([], ['tal x fade 5wk'])],
    linWeek:   [p => [...p.x, td(p), td(p) * Math.min(p.r.w, 15) / 15], nm([], ['tal', 'tal x week/15'])],
    byWeekGrp: [p => [...p.x, p.r.w <= 2 ? td(p) : 0, p.r.w > 2 && p.r.w <= 5 ? td(p) : 0, p.r.w > 5 && p.r.w < 20 ? td(p) : 0, p.r.w >= 20 ? td(p) : 0],
      nm([], ['tal wk0-2', 'tal wk3-5', 'tal wk6+', 'tal bowls'])],
  };
  OUT.talent = {};
  for (const [k, [f, cols]] of Object.entries(forms)) OUT.talent[k] = { ...show('talent ' + k, cvX(f), ref, cols) };
}
// ---- 2. the preseason prior: talent, returning production and returning talent, every form -------------------
// (scale is relative to the live ELO_PT). Each prior is fit on 2025's season-end ratings and applied to 2026,
// so the 2026 fold is clean; the 2025 fold is in-sample for the prior
const noTal = p => p.x;
const zOf = (pairs) => { const v = pairs.map(x => x[1]).filter(x => x != null && isFinite(x)), m = mean(v), s = sd(v); return Object.fromEntries(pairs.filter(x => x[1] != null && isFinite(x[1])).map(([k, x]) => [k, (x - m) / s])); };
function augment(F, S, useFv = false) {
  const rr = Object.fromEntries((data.returning[S] || []).map(x => [nameId[x.team], x]));
  const fbsT = Object.keys(F);
  const zs = k => zOf(fbsT.map(t => [t, rr[t]?.[k]]));
  const pass = zs('percentPassingPPA'), rush = zs('percentRushingPPA'), rec = zs('percentReceivingPPA'), use = zs('usage'), tot = zs('totalPPA');
  const pr = data.pfnRet?.[S] || {}, av = zOf(fbsT.map(t => [t, pr[t]?.av])), qb = zOf(fbsT.map(t => [t, pr[t]?.qb])), avR = zOf(fbsT.map(t => [t, pr[t]?.avRest]));
  const fv = zOf(fbsT.map(t => [t, data.fvTalent?.[t]]));
  for (const t of fbsT) { const f = F[t];
    Object.assign(f, { pass: pass[t] ?? 0, rush: rush[t] ?? 0, rec: rec[t] ?? 0, use: use[t] ?? 0, totPPA: tot[t] ?? 0, av: av[t] ?? 0, qbr: qb[t] ?? 0, avRest: avR[t] ?? 0,
      talRet: f.tal * (f.ret), fv: fv[t] ?? f.tal });
    if (useFv) f.tal = fv[t] ?? f.tal;
  }
  return F;
}
function priorsWith(ptsFn, { scale = 1, fv = false, effTal = true, ridge = 0.5 } = {}) {
  const keep = { ...I.PRIOR_X }; I.PRIOR_X.pts = ptsFn;
  if (!effTal) { I.PRIOR_X.o = f => [1, f.o, f.ret]; I.PRIOR_X.d = f => [1, f.d]; I.PRIOR_X.po = f => [1, f.po, f.ret]; I.PRIOR_X.pd = f => [1, f.pd]; }
  const fin = {}, pri = {};
  pri[S0] = { pts: {}, ppa: {}, ppp: {}, pace: {} };
  fin[S0] = I.finalOf(S0, rows, effBy[S0], fbsBy[S0], null, P0);
  const F1x = augment(I.priorFeatures(S1, data, fbsBy[S1], nameId, fin), S1);
  fin[S1] = I.finalOf(S1, rows, effBy[S1], fbsBy[S1], null, P0, fin);
  const Wx = I.fitPrior(F1x, fin[S1]);
  pri[S1] = I.applyPrior(F1x, Wx);
  const m1 = fin[S1].mass;
  fin[S1] = { ...I.finalOf(S1, rows, effBy[S1], fbsBy[S1], pri[S1], P0, fin), mass: m1 };
  const F2x = augment(I.priorFeatures(SEASON, data, fbsBy[SEASON], nameId, fin), SEASON, fv);
  pri[SEASON] = I.applyPrior(F2x, Wx);
  for (const S of [S1, SEASON]) for (const t of Object.keys(pri[S].pts)) pri[S].pts[t] *= scale;
  Object.assign(I.PRIOR_X, keep);
  return { pri, fin, Wx };
}
if (W8 === 'all' || W8 === 'prior') {
  const runP = (label, fn, opts) => { const { pri, fin, Wx } = priorsWith(fn, opts);
    const a = I.walk(rows, effBy, fbsBy, pri, P, [S1], fin, talBy, stBy, stPrior).filter(p => p.r.done && p.r.fbsGame);
    const b = I.walk(rows, effBy, fbsBy, pri, P, [SEASON], fin, talBy, stBy, stPrior).filter(p => p.r.done && p.r.fbsGame);
    const r = cvX(noTal, [a, b]); const c = show('prior ' + label, r, refNone); console.log('   pts weights', Wx.pts.map(r3)); return { ...c, w: Wx.pts.map(r3) }; };
  const refNone = cvX(noTal).o;
  OUT.prior = {
    live: runP('live [1,sp,tal,ret]', f => [1, f.sp, f.tal, f.ret]),
    noTal: runP('[1,sp,ret]', f => [1, f.sp, f.ret]),
    noRet: runP('[1,sp,tal]', f => [1, f.sp, f.tal]),
    talRet: runP('+ tal x ret', f => [1, f.sp, f.tal, f.ret, f.talRet]),
    split: runP('ret split pass/rush/rec', f => [1, f.sp, f.tal, f.pass, f.rush, f.rec]),
    usage: runP('ret usage', f => [1, f.sp, f.tal, f.use]),
    pass: runP('+ returning passing', f => [1, f.sp, f.tal, f.ret, f.pass]),
    av: runP('ret -> returning WAR (av)', f => [1, f.sp, f.tal, f.av]),
    avPlus: runP('+ returning WAR (av)', f => [1, f.sp, f.tal, f.ret, f.av]),
    qbr: runP('+ returning QB WAR', f => [1, f.sp, f.tal, f.ret, f.qbr]),
    effNoTal: runP('live, no talent in eff priors', f => [1, f.sp, f.tal, f.ret], { effTal: false }),
    fv2026: runP('live, FV talent in 2026 (leaks)', f => [1, f.sp, f.tal, f.ret], { fv: true }),
    s08: runP('live x0.8', f => [1, f.sp, f.tal, f.ret], { scale: 0.8 }),
    s12: runP('live x1.2', f => [1, f.sp, f.tal, f.ret], { scale: 1.2 }),
    s14: runP('live x1.4', f => [1, f.sp, f.tal, f.ret], { scale: 1.4 }),
  };
}
if (W8 === 'scale') {
  const refNone = cvX(noTal).o;
  const t26 = (r) => { const a = r.o.filter(x => x.r.S === SEASON), b = refNone.filter(x => x.r.S === SEASON), d = a.map((x, i) => x.ll - b[i].ll); return r2(mean(d) / (sd(d) / Math.sqrt(d.length))); };
  const runP = (label, fn, opts) => { const { pri, fin, Wx } = priorsWith(fn, opts);
    const a = I.walk(rows, effBy, fbsBy, pri, P, [S1], fin, talBy, stBy, stPrior).filter(p => p.r.done && p.r.fbsGame);
    const b = I.walk(rows, effBy, fbsBy, pri, P, [SEASON], fin, talBy, stBy, stPrior).filter(p => p.r.done && p.r.fbsGame);
    const r = cvX(noTal, [a, b]); show('prior ' + label, r, refNone); console.log('   t2026', t26(r), 'w', Wx.pts.map(r3)); return r; };
  for (const s of [0.5, 0.6, 0.7, 0.8, 0.9]) runP('live x' + s, f => [1, f.sp, f.tal, f.ret], { scale: s });
  for (const s of [0.7, 0.8, 1]) runP('av x' + s, f => [1, f.sp, f.tal, f.av], { scale: s });
  for (const s of [0.7, 0.8, 1]) runP('ret+av x' + s, f => [1, f.sp, f.tal, f.ret, f.av], { scale: s });
}
if (W8 === 'ridge') {
  const refNone = cvX(noTal).o;
  for (const rg of [0, 1, 5, 20, 50, 100, 200]) show('ridge ' + rg, cvX(noTal, [A, B], rg), refNone);
}
