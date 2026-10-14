// Game-model audit and upgrade tests (scripts/cfb_model.mjs), offline, on the live model's own inputs.
//   node scripts/cfb_game_backtest.mjs <md.json.gz> [qb.json]
// md.json.gz: everything runModel reads (fetch_cfb.mjs writes it with CFB_MD_DUMP=<path>; the "cfb game research"
// workflow uploads it as an artifact, since CFBD's key lives only in GitHub); qb.json: ESPN passing lines
// by game and team ({ gameId: { teamId: [[athleteId, name, cmp, att, yds, td, int], ...] } }), for the QB test.
// The model is rebuilt exactly as runModel builds it (same prior, hyperparameters and inputs), then scored by
// season-swap cross-validation: margin weights fit on one season, every game of the other predicted, both ways.
//   1. Segments: the model's miss against the closing line's, by week, conference tier, division, line size and total
//   2. Candidates: each new input added to the live model, the paired per-game change in out-of-sample log loss
//      (t: mean over its standard error) and in MAE; totals the same on absolute error
// Writes data/cfb_game_backtest.json. Results, Oct 2026 (2025 and 2026 through week 6, 1,380 games):
//   prior without last season's Elo: log loss .4603 -> .4525 (t -3.9), MAE 12.78 -> 12.65; then conference tier (p4):
//   .4493 (t -1.9); totals with an FCS side: MAE 12.59 -> 12.49 (t -2.3). Failed: market ratings from earlier
//   closing spreads and totals, a fading prior, early-season Elo or efficiency, byes, short weeks, early body-clock
//   kickoffs, mismatch size, domes. QB1 out (who started, from box scores, so an oracle) costs ~4 points (t -1.6).
import zlib from 'node:zlib';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { _internals as I, phi, fitBeta } from './cfb_model.mjs';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const [mdPath, qbPath] = process.argv.slice(2);
const data = JSON.parse(zlib.gunzipSync(fs.readFileSync(mdPath)));
const QBG = qbPath && fs.existsSync(qbPath) ? JSON.parse(fs.readFileSync(qbPath, 'utf8')) : null;
const SEASON = 2026, LIVE = ['avRet', 'aggr', 'p4'], P = { k: 25, eloHome: 70, lam: 1.5 };
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
console.log(`live model CV: log loss ${r4(mean(ref.map(x => x.ll)))}, MAE ${r2(mean(ref.map(x => x.ae)))}; close ${r4(mean(mk.map(x => ll(phi(x.r.close / sM), x.y))))}, MAE ${r2(mean(mk.map(x => Math.abs(x.r.m - x.r.close))))}`);

// preseason prior: last season's final Elo in the regression? Elo's spread at season end depends on how the season
// started (2024's Elo began flat, later seasons from a prior), so its weight, fit on one season, doesn't carry to the
// next. Variants: without Elo, or with last season's final margin rating (mass) in its place, which is built the
// same way every season. Scored on every game, and on the out-of-sample season (the prior is fit on 2025 itself)
const PRI = {
  live: null,                                          // SP+, talent, returning production (since Oct 2026)
  before: f => [1, f.elo, f.sp, f.net, f.tal, f.ret],  // the prior until Oct 2026
  noElo: f => [1, f.sp, f.net, f.tal, f.ret],
  mass: f => [1, f.mass, f.sp, f.net, f.tal, f.ret],
  massNoElo: f => [1, f.mass, f.net, f.tal, f.ret],
};
const priorRes = {}, foldOf = (o, S) => o.filter(x => x.r.S === S), wk04 = o => o.filter(x => x.r.w <= 4);
const sumUp = o => ({ n: o.length, logLoss: r4(mean(o.map(x => x.ll))), mae: r2(mean(o.map(x => x.ae))) });
let PRI_DATA = {};
for (const [k, f] of Object.entries(PRI)) {
  const b = buildPriors(f), A2 = walkS(S1, P, b.priors, b.finals), B2 = walkS(SEASON, P, b.priors, b.finals), o = cv(() => [], [A2, B2]);
  PRI_DATA[k] = { A: A2, B: B2, ...b };
  const fb = [...fbsBy[SEASON]], spr = S => r2(sd([...fbsBy[S]].map(t => b.priors[S].pts[t]).filter(v => v != null)));
  priorRes[k] = { weights: b.W[S1].pts.map(r3), sd: { [S1]: spr(S1), [SEASON]: spr(SEASON), target: r2(sd([...fbsBy[S1]].map(t => b.finals[S1].mass[t]).filter(v => v != null))) },
    all: compare(o, ref), [SEASON]: sumUp(foldOf(o, SEASON)), [`${SEASON} wk 0-4`]: sumUp(wk04(foldOf(o, SEASON))), [`${S1} wk 0-4`]: sumUp(wk04(foldOf(o, S1))) };
  console.log('prior', k.padEnd(10), JSON.stringify(priorRes[k]));
}

// the rest runs on the chosen prior (PRIOR=<variant> to change it); live: the model as it runs now
const PICK = process.env.PRIOR || 'live', refLive = ref;
({ A, B, priors, finals } = PRI_DATA[PICK]);
ref = cv(); mk = ref.filter(x => x.r.close != null);
console.log(`prior ${PICK}: CV log loss ${r4(mean(ref.map(x => x.ll)))}, MAE ${r2(mean(ref.map(x => x.ae)))}`);

// ---- 1. segments ---------------------------------------------------------------------------------------------
const P4 = new Set(['SEC', 'Big Ten', 'Big 12', 'ACC']);
const tierOf = r => {
  const t = (c, cl, id) => cl !== 'fbs' ? 'FCS' : P4.has(c) || id === '87' ? 'P4' : 'G5';   // Notre Dame (87) plays a P4 schedule
  const [x, y] = [t(r.hconf, r.hc, r.h), t(r.aconf, r.ac, r.a)].sort();
  return x === 'FCS' || y === 'FCS' ? 'vs FCS' : `${x}-${y}`;
};
const weekOf = r => r.w >= 20 ? 'bowls' : r.w <= 2 ? 'wk 0-2' : r.w <= 4 ? 'wk 3-4' : r.w <= 8 ? 'wk 5-8' : 'wk 9+';
const lineOf = r => { const a = Math.abs(r.close); return a < 3.5 ? '0-3' : a < 7.5 ? '3.5-7' : a < 14.5 ? '7.5-14' : a < 21.5 ? '14.5-21' : '21.5+'; };
// per segment: n, MAE (model, close), log loss (model, close), the model's lean against the close (favorite's side),
// and the slope of (result - close) on (model - close): 0 means the model's disagreements are noise, 1 that they're
// fully right; the best blend puts that weight on the model
function seg(list, key) {
  const by = {};
  for (const x of list) (by[key(x.r)] ||= []).push(x);
  return Object.fromEntries(Object.entries(by).sort().map(([k, xs]) => {
    const d = xs.map(x => x.m - x.r.close), c = xs.map(x => x.r.m - x.r.close), md = mean(d), mc = mean(c);
    const slope = d.reduce((a, v, i) => a + (v - md) * (c[i] - mc), 0) / Math.max(1e-9, d.reduce((a, v) => a + (v - md) ** 2, 0));
    const fav = xs.map(x => Math.sign(x.r.close || 1) * (x.m - x.r.close));
    return [k, { n: xs.length, maeModel: r2(mean(xs.map(x => x.ae))), maeClose: r2(mean(c.map(Math.abs))), llModel: r4(mean(xs.map(x => x.ll))),
      llClose: r4(mean(xs.map(x => ll(phi(x.r.close / sM), x.y)))), favLean: r2(mean(fav)), favCover: r2(mean(xs.map(x => Math.sign(x.r.close || 1) * (x.r.m - x.r.close)))),
      sdDiff: r2(sd(d)), slope: r2(slope) }];
  }));
}
const segments = { week: seg(mk, weekOf), tier: seg(mk, tierOf), line: seg(mk, lineOf), season: seg(mk, r => String(r.S)) };

// totals: the live totals model (raw plays x points per play, then wind, rain and cold), fit one season and scored
// on the other, against the closing total
const WXv = (r, x) => [...I.WX(r.dome ? null : wx[r.id]), x[7] !== 0 ? 1 : 0];   // weather, FCS side (live)
function cvTot(extra = () => [], folds = [A, B]) {
  const ok = ps => ps.filter(p => p.t.tot > 0 && isFinite(p.t.tot));
  const X = p => [1, p.t.tot, ...WXv(p.r, p.x), ...extra(p)], out = [];
  const [a, b] = folds.map(ok);
  for (const [fit, on] of [[a, b], [b, a]]) {
    const w = I.ols(fit.map(X), fit.map(p => p.r.tot), 1);
    for (const p of on) { const t = dot(w, X(p)); out.push({ r: p.r, t, ae: Math.abs(p.r.tot - t) }); }
  }
  return out;
}
const refT = cvTot();
const segT = (list, key) => { const by = {}; for (const x of list) (by[key(x.r)] ||= []).push(x);
  return Object.fromEntries(Object.entries(by).sort().map(([k, xs]) => [k, { n: xs.length, maeModel: r2(mean(xs.map(x => x.ae))), maeClose: r2(mean(xs.map(x => Math.abs(x.r.tot - x.r.closeTot)))),
    lean: r2(mean(xs.map(x => x.t - x.r.closeTot))), over: r2(mean(xs.map(x => x.r.tot - x.r.closeTot))) }])); };
const mkT = refT.filter(x => x.r.closeTot != null);
const totBand = r => r.closeTot < 45 ? '<45' : r.closeTot < 52 ? '45-51.5' : r.closeTot < 60 ? '52-59.5' : '60+';
segments.totals = { week: segT(mkT, weekOf), tier: segT(mkT, tierOf), total: segT(mkT, totBand), all: segT(mkT, () => 'all').all };

// ---- 2. candidate inputs ------------------------------------------------------------------------------------
const id = (S, t) => fbsBy[S].has(t) ? t : FCS;
// market ratings: each team's rating implied by this season's closing spreads before the week (home margin =
// R[home] - R[away] + home field), each team shrunk toward its preseason prior by lamM games; non-FBS teams toward
// one shared non-FBS level, fit with the rest. The same from closing totals: total = mu + T[home] + T[away]
const mkCache = {};
function marketAt(S, w, lamM = 2) {
  const key = `${S}|${w}|${lamM}`; if (mkCache[key]) return mkCache[key];
  const gs = rows.filter(r => r.S === S && r.w < w && r.close != null && (r.fbsGame));
  const pr = t => fbsBy[S].has(t) ? priors[S].pts[t] ?? 0 : null;
  const R = {}, T = {}, by = {};
  for (const g of gs) for (const t of [g.h, g.a]) { (by[t] ||= []).push(g); R[t] = pr(t) ?? -20; T[t] = 0; }
  let hfa = 2.5, fcs = -20, mu = 55;
  for (let it = 0; it < 40; it++) {
    const hs = gs.filter(g => !g.n); hfa = hs.length ? mean(hs.map(g => g.close - R[g.h] + R[g.a])) : 2.5;
    const nf = Object.keys(R).filter(t => !fbsBy[S].has(t)); if (nf.length) fcs = mean(nf.map(t => R[t]));
    const tg = gs.filter(g => g.closeTot != null); if (tg.length) mu = mean(tg.map(g => g.closeTot - T[g.h] - T[g.a]));
    for (const [t, list] of Object.entries(by)) {
      const p0 = pr(t) ?? fcs;
      let n = lamM * p0, wt = lamM, nt = 0, wtt = lamM;
      for (const g of list) {
        const e = g.close - (g.n ? 0 : hfa); n += g.h === t ? e + R[g.a] : R[g.h] - e; wt++;
        if (g.closeTot != null) { nt += g.closeTot - mu - T[g.h === t ? g.a : g.h]; wtt++; }
      }
      R[t] = n / wt; T[t] = nt / wtt;
    }
  }
  return (mkCache[key] = { R: t => R[t] ?? pr(t) ?? fcs, T: t => T[t] ?? 0, mu, n: gs.length });
}
// QB: each team's QB1 before the game (most attempts in its earlier games this season) and whether he started
// (the most attempts in this one); value = adjusted net yards an attempt ((yds + 20 TD - 45 INT) / att) shrunk toward
// replacement (5.0) by 100 attempts, this season before the game plus last season's
const QBK = { k: 100, repl: 5.0, att: 30 };
let qbInfo = null;
if (QBG) {
  qbInfo = {};
  const bySeasonTeam = {};
  const games = rows.filter(r => r.done && QBG[r.id]).sort((a, b) => a.date.localeCompare(b.date));
  const acc = {};   // athlete -> season -> [att, val]
  for (const r of games) {
    for (const t of [r.h, r.a]) {
      const lines = QBG[r.id][t] || [];
      const hist = (bySeasonTeam[r.S + '|' + t] ||= {});
      const q1 = Object.entries(hist).sort((a, b) => b[1] - a[1])[0]?.[0];
      const top = [...lines].sort((a, b) => b[3] - a[3])[0];
      const vOf = aid => { const c = acc[aid] || {}, cur = c[r.S] || [0, 0], prev = c[r.S - 1] || [0, 0];
        return (cur[1] + prev[1] + QBK.k * QBK.repl) / (cur[0] + prev[0] + QBK.k); };
      if (q1 && top) qbInfo[r.id + '|' + t] = { q1, out: top[0] !== q1 && (hist[q1] || 0) >= 40, v1: vOf(q1), vTop: vOf(top[0]), name: top[1] };
      for (const l of lines) { hist[l[0]] = (hist[l[0]] || 0) + l[3]; const c = ((acc[l[0]] ||= {})[r.S] ||= [0, 0]); c[0] += l[3]; c[1] += l[4] + 20 * l[5] - 45 * l[6]; }
    }
  }
}
const qbCost = (r, t) => { const q = qbInfo?.[r.id + '|' + t]; return q?.out ? (q.vTop - q.v1) * QBK.att / 10 : 0; };   // in ANY/A x 3 (per 10 yards a game)
const qbOutFlag = (r, t) => qbInfo?.[r.id + '|' + t]?.out ? 1 : 0;
// rest and travel by team: days since its last game, and kickoff hour on its home clock
const lastBy = {}, restBy = {};
for (const r of [...rows].sort((a, b) => a.date.localeCompare(b.date))) {
  for (const t of [r.h, r.a]) { const l = lastBy[r.S + '|' + t]; restBy[r.id + '|' + t] = l ? (Date.parse(r.date) - l) / 864e5 : null; }
  if (r.done) for (const t of [r.h, r.a]) lastBy[r.S + '|' + t] = Date.parse(r.date);
}
const hourAt = (tz, date) => { try { return +new Intl.DateTimeFormat('en-US', { timeZone: tz, hour: 'numeric', hour12: false }).format(new Date(date)) % 24; } catch { return null; } };
const early = (r, t) => { const h = geo.home[t]?.tz && hourAt(geo.home[t].tz, r.date); return h != null && h < 11 && h >= 5 ? 1 : 0; };
const bye = (r, t) => { const d = restBy[r.id + '|' + t]; return d != null && d >= 12.5 && d < 30 ? 1 : 0; };
const shortWk = (r, t) => { const d = restBy[r.id + '|' + t]; return d != null && d < 6 ? 1 : 0; };
const pdiff = r => (priors[r.S].pts[r.h] ?? -15) - (priors[r.S].pts[r.a] ?? -15);

const isP4 = (r, s) => (s === 'h' ? r.hc : r.ac) === 'fbs' && (P4.has(s === 'h' ? r.hconf : r.aconf) || (s === 'h' ? r.h : r.a) === '87') ? 1 : 0;
const CANDS = {
  mkt:    { name: 'market rating from earlier closing spreads (this season)', f: p => { const M = marketAt(p.r.S, p.r.w); return [M.R(p.r.h) - M.R(p.r.a)]; } },
  mkt4:   { name: 'market rating, shrunk harder (4 games)', f: p => { const M = marketAt(p.r.S, p.r.w, 4); return [M.R(p.r.h) - M.R(p.r.a)]; } },
  prior:  { name: 'preseason prior, fading over 4 weeks', f: p => [pdiff(p.r) * Math.max(0, 1 - (p.r.w - 1) / 4)] },
  priorAll: { name: 'preseason prior, all season', f: p => [pdiff(p.r)] },
  earlyNet: { name: 'efficiency x early season (weeks 0-3)', f: p => [p.r.w <= 3 ? p.x[1] : 0] },
  earlyElo: { name: 'Elo x early season (weeks 0-3)', f: p => [p.r.w <= 3 ? p.x[0] : 0] },
  bye:    { name: 'off a bye (home minus away)', f: p => [bye(p.r, p.r.h) - bye(p.r, p.r.a)] },
  short:  { name: 'short week, under 6 days (home minus away)', f: p => [shortWk(p.r, p.r.h) - shortWk(p.r, p.r.a)] },
  clock:  { name: 'kickoff before 11 a.m. on the team\'s home clock (away minus home)', f: p => [early(p.r, p.r.a) - early(p.r, p.r.h)] },
  qb:     { name: 'QB1 out: backup minus starter ANY/A (oracle: who started)', f: p => [qbCost(p.r, p.r.h) - qbCost(p.r, p.r.a)], qb: true },
  qbFlag: { name: 'QB1 out (oracle), flag', f: p => [qbOutFlag(p.r, p.r.h) - qbOutFlag(p.r, p.r.a)], qb: true },
};
const res = {};
for (const [k, c] of Object.entries(CANDS)) {
  if (c.qb && !qbInfo) continue;
  const o = cv(c.f), w = fitAll(c.f).beta.slice(-1)[0];
  res[k] = { name: c.name, weight: r3(w), ...compare(o, ref) };
  console.log(k.padEnd(9), JSON.stringify(res[k]));
}
// the market rating on top of everything (it carries the most): what's left for the rest
const withMkt = p => CANDS.mkt.f(p);
const refM = cv(withMkt), resM = {};
for (const [k, c] of Object.entries(CANDS)) {
  if (k.startsWith('mkt') || (c.qb && !qbInfo)) continue;
  const f = p => [...withMkt(p), ...c.f(p)];
  resM[k] = { ...compare(cv(f), refM), weight: r3(fitAll(f).beta.slice(-1)[0]) };
}

// totals candidates
const TC = {
  mktTot: { name: 'market total rating from earlier closing totals', f: p => { const M = marketAt(p.r.S, p.r.w); return [M.mu + M.T(p.r.h) + M.T(p.r.a)]; } },
  gap:    { name: 'size of the mismatch (|Elo gap|)', f: p => [Math.abs(p.x[0])] },
  dome:   { name: 'dome', f: p => [p.r.dome ? 1 : 0] },
  pace:   { name: 'plays and points per play, separately', f: p => { const S = p.r.S; return [p.t.hp + p.t.ap]; } },
};
const resT = {};
for (const [k, c] of Object.entries(TC)) {
  const o = cvTot(c.f), e = o.map((x, i) => x.ae - refT[i].ae);
  resT[k] = { name: c.name, mae: r2(mean(o.map(x => x.ae))), dMae: r3(mean(e)), t: r2(mean(e) / (sd(e) / Math.sqrt(e.length))) };
  console.log(k.padEnd(9), JSON.stringify(resT[k]));
}

const report = {
  asof: new Date().toISOString().slice(0, 10), folds: [S1, SEASON], n: ref.length, nMarket: mk.length,
  prior: PICK, live: { inputs: LIVE, logLoss: r4(mean(refLive.map(x => x.ll))), mae: r2(mean(refLive.map(x => x.ae))), new: { logLoss: r4(mean(ref.map(x => x.ll))), mae: r2(mean(ref.map(x => x.ae))) }, closeLogLoss: r4(mean(mk.map(x => ll(phi(x.r.close / sM), x.y)))),
    closeMae: r2(mean(mk.map(x => Math.abs(x.r.m - x.r.close)))), totMae: r2(mean(refT.map(x => x.ae))), totMaeClose: r2(mean(mkT.map(x => Math.abs(x.r.tot - x.r.closeTot)))) },
  segments, candidates: res, onTopOfMarket: resM, totals: resT, priors: priorRes,
  qb: qbInfo ? { games: Object.values(qbInfo).filter(q => q.out).length, of: Object.keys(qbInfo).length } : null,
};
fs.writeFileSync(process.env.BT_OUT || path.join(ROOT, 'data', 'cfb_game_backtest.json'), JSON.stringify(report, null, 1));
console.log(JSON.stringify(segments, null, 0));
console.log(JSON.stringify(resM));
