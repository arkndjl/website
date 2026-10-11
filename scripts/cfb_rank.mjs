// Team rankings for the ARKBOARD (data/cfb_rank.json): the AP Top 25, the AFCA Coaches Poll (and the CFP
// committee's rankings once they are out), from ESPN, next to our own ranking of every FBS team.
//
// Our ranking is a power ranking: the margin each team would be expected to win by against an average FBS team
// on a neutral field. It reads the game model (scripts/cfb_model.mjs) rather than refitting it, so the inputs are
// weighted by how well they predicted games the model had not seen yet: each week of the last two seasons is rated
// only on the weeks before it, and the margin regression on those predictions sets the weights.
//   Elo          results and margins, from a preseason prior
//   Efficiency   opponent-adjusted EPA per play, offense minus defense (garbage time out)
//   Talent       roster talent (the board's FV starters live, the 247 composite in the backtest)
//   Special teams, situational   field goals, punts, kickoffs; the situational stats the model kept (success rate...)
//   Staff        head coach and coordinator scores (scripts/cfb_teams.mjs staffModels), tested here on what the
//                model missed this season, holding today's Elo and talent fixed (the scores are built on them);
//                they enter only with a positive weight at t >= 2
// The evidence: each input alone and the model without it, scored out of sample (weights fit on last season,
// scored on this one), and how often our ranking, the AP and the Coaches Poll picked the winner when they ranked
// the two teams differently (CFBD's weekly polls: the latest poll out before kickoff).

import { CAND } from './cfb_model.mjs';

const mean = xs => xs.reduce((a, b) => a + b, 0) / Math.max(1, xs.length);
const sd = xs => { const m = mean(xs); return Math.sqrt(mean(xs.map(x => (x - m) ** 2))) || 1; };
const r1 = x => Math.round(x * 10) / 10, r2 = x => Math.round(x * 100) / 100, r3 = x => Math.round(x * 1000) / 1000, r4 = x => Math.round(x * 1e4) / 1e4;
const dot = (a, b) => a.reduce((s, v, i) => s + v * b[i], 0);
function phi(z) {
  const t = 1 / (1 + 0.2316419 * Math.abs(z)), d = 0.3989423 * Math.exp(-z * z / 2);
  const p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))));
  return z > 0 ? 1 - p : p;
}
// least squares, no intercept (home field is its own column), a light ridge
function ols(X, y, ridge = 1) {
  const k = X[0].length, A = Array.from({ length: k }, () => Array(k).fill(0)), b = Array(k).fill(0);
  X.forEach((x, n) => { for (let i = 0; i < k; i++) { b[i] += x[i] * y[n]; for (let j = 0; j < k; j++) A[i][j] += x[i] * x[j]; } });
  for (let i = 0; i < k; i++) A[i][i] += ridge;
  for (let i = 0; i < k; i++) {
    let p = i; for (let r = i + 1; r < k; r++) if (Math.abs(A[r][i]) > Math.abs(A[p][i])) p = r;
    [A[i], A[p]] = [A[p], A[i]]; [b[i], b[p]] = [b[p], b[i]];
    for (let r = 0; r < k; r++) if (r !== i) { const f = A[r][i] / A[i][i]; for (let c = i; c < k; c++) A[r][c] -= f * A[i][c]; b[r] -= f * b[i]; }
  }
  return b.map((v, i) => v / A[i][i]);
}
const CAP = 45;
// first coefficient of a least-squares fit (no intercept) and its t
function coef(X, y) {
  const k = X[0].length, A = Array.from({ length: k }, () => Array(k + 1).fill(0));
  X.forEach((x, n) => { for (let i = 0; i < k; i++) { A[i][k] += x[i] * y[n]; for (let j = 0; j < k; j++) A[i][j] += x[i] * x[j]; } });
  if (!A[0][0]) return null;
  for (let i = 1; i < k; i++) A[i][i] += 1e-6;   // a control with no spread drops out
  // (X'X)^-1 by Gauss-Jordan on [X'X | I], then b = (X'X)^-1 X'y
  const M = A.map((r, i) => [...r.slice(0, k), ...Array.from({ length: k }, (_, j) => +(i === j))]);
  for (let i = 0; i < k; i++) {
    let p = i; for (let r = i + 1; r < k; r++) if (Math.abs(M[r][i]) > Math.abs(M[p][i])) p = r;
    [M[i], M[p]] = [M[p], M[i]];
    if (!M[i][i]) return null;
    const f0 = M[i][i]; for (let c = 0; c < 2 * k; c++) M[i][c] /= f0;
    for (let r = 0; r < k; r++) if (r !== i) { const f = M[r][i]; for (let c = 0; c < 2 * k; c++) M[r][c] -= f * M[i][c]; }
  }
  const inv = M.map(r => r.slice(k)), xy = A.map(r => r[k]), b = inv.map(r => dot(r, xy));
  const e = X.map((x, n) => y[n] - dot(b, x)), s2 = e.reduce((a, v) => a + v * v, 0) / Math.max(1, X.length - k);
  return { b: b[0], t: b[0] / Math.sqrt(s2 * inv[0][0]) };
}   // blowouts capped, as in the game model

// the rating inputs, by group; everything else in the model (home field, rest, travel, FCS) is game context
const GROUPS = [
  { key: 'elo', name: 'Elo', feats: ['elo'] },
  { key: 'eff', name: 'Efficiency (EPA/play)', feats: ['net'] },
  { key: 'talent', name: 'Roster talent', feats: ['talent', 'talentLate'] },
  { key: 'st', name: 'Special teams', feats: ['st'] },
  { key: 'results', name: 'Record and margin (unadjusted)', feats: ['wpct', 'mov'] },   // only if the model kept them
  { key: 'situ', name: 'Situational', feats: null },   // the model's other kept extras (report.extra)
];
const RESULTS = ['wpct', 'mov'];
const CONTEXT = ['home', 'rest', 'tz', 'dist', 'alt', 'fcs'];

// fit on one set of walk-forward predictions, score another: log loss on the winner, winner picked, margin MAE
function fitScore(fit, on, cols) {
  const X = p => cols.map(i => p.x[i]);
  const b = ols(fit.map(X), fit.map(p => Math.max(-CAP, Math.min(CAP, p.r.m))));
  const sig = sd(fit.map(p => p.r.m - dot(b, X(p))));
  const per = on.map(p => {
    const m = dot(b, X(p)), ph = Math.min(1 - 1e-9, Math.max(1e-9, phi(m / sig))), y = p.r.m > 0 ? 1 : p.r.m < 0 ? 0 : 0.5;
    return { ll: -(y * Math.log(ph) + (1 - y) * Math.log(1 - ph)), hit: y === 0.5 ? 0.5 : (m > 0) === (y === 1) ? 1 : 0, ae: Math.abs(p.r.m - m) };
  });
  return { b, sig, per, logLoss: mean(per.map(x => x.ll)), acc: mean(per.map(x => x.hit)), mae: mean(per.map(x => x.ae)) };
}
const paired = (a, b) => { const d = a.map((x, i) => x.ll - b[i].ll), se = sd(d) / Math.sqrt(d.length); return { d: mean(d), t: mean(d) / se }; };

// polls by season and week from CFBD's rankings endpoint: { [S]: [{ week, polls: { ap: {tid: rank}, coaches: {...} } }] }
function pollWeeks(raw, resolve) {
  const out = [];
  for (const w of raw || []) {
    if (w.seasonType && w.seasonType !== 'regular') continue;
    const polls = {};
    for (const p of w.polls || []) {
      const key = /^AP/i.test(p.poll) ? 'ap' : /coaches/i.test(p.poll) && !/FCS|II/i.test(p.poll) ? 'coaches' : null;
      if (!key) continue;
      polls[key] = Object.fromEntries((p.ranks || []).map(r => [String(r.teamId ?? resolve?.(r.school) ?? ''), r.rank]).filter(([t]) => t));
    }
    out.push({ week: w.week, polls });
  }
  return out.sort((a, b) => a.week - b.week);
}

// head-to-head: games where at least one team is ranked in the poll; the poll picks the better-ranked team
// (unranked = 26), ours the higher rating on a neutral field (no home field: the polls don't have one either)
function pickTest(preds, rateOf, weeksBy, poll, lag = 0) {
  const t = { n: 0, poll: 0, ours: 0, split: 0, splitOurs: 0 };
  for (const p of preds) {
    const S = p.r.S, wk = (weeksBy[S] || []).filter(x => x.week <= p.r.w - lag && x.polls[poll]).at(-1);
    if (!wk || p.r.m === 0 || p.r.w >= 20) continue;
    const P = wk.polls[poll], rh = P[p.r.h] ?? 26, ra = P[p.r.a] ?? 26;
    if (rh === 26 && ra === 26) continue;
    const homeWon = p.r.m > 0, pollHome = rh < ra, oursHome = rateOf(p) > 0;
    t.n++; if (pollHome === homeWon) t.poll++; if (oursHome === homeWon) t.ours++;
    if (pollHome !== oursHome) { t.split++; if (oursHome === homeWon) t.splitOurs++; }
  }
  return { n: t.n, pollPct: t.n ? r3(t.poll / t.n) : null, oursPct: t.n ? r3(t.ours / t.n) : null, split: t.split, splitOurs: t.splitOurs, splitPoll: t.split - t.splitOurs };
}

// ESPN's current polls: AP, AFCA Coaches, and the CFP committee's rankings when there are any
export function readPolls(espn) {
  const out = {};
  for (const r of espn?.rankings || []) {
    const key = /playoff|cfp/i.test(`${r.name} ${r.type}`) ? 'cfp' : r.type === 'ap' ? 'ap' : r.type === 'usa' || /^AFCA Coaches/i.test(r.name) ? 'coaches' : null;
    if (!key || out[key]) continue;
    out[key] = { name: r.shortName || r.name, date: r.date?.slice(0, 10) || null, week: r.occurrence?.value ?? null,
      ranks: (r.ranks || []).map(x => ({ rk: x.current, prev: x.previous || null, tid: String(x.team?.id ?? ''), team: x.team?.location || x.team?.nickname || '',
        abbr: x.team?.abbreviation || null, logo: x.team?.logos?.[0]?.href || null, rec: x.recordSummary || null, pts: x.points ?? null, fpv: x.firstPlaceVotes || null })) };
  }
  return out;
}

// model: runModel's result; teamList and coaches: scripts/cfb_teams.mjs; talentZ: the model's live talent input;
// late: the coming week is week 5 or later (the talentLate term applies); polls: readPolls(); hist: CFBD rankings by
// season; resolve: school name -> team id; prev: last run's data/cfb_rank.json; week: weeks played
export function teamRankings({ model, teamList, coaches, talentZ = {}, late = false, polls = {}, hist = {}, resolve, prev = null, week = 0 }) {
  const rep = model.report, FEATS = Object.keys(rep.beta), col = f => FEATS.indexOf(f);
  const groups = GROUPS.map(g => ({ ...g, cols: (g.feats || (rep.extra || []).filter(k => !RESULTS.includes(k))).map(col).filter(i => i >= 0) })).filter(g => g.cols.length);
  const ctx = CONTEXT.map(col).filter(i => i >= 0), rateCols = groups.flatMap(g => g.cols), all = [...ctx, ...rateCols];
  const ok = ps => (ps || []).filter(p => p.r.done && p.r.fbsGame);
  const train = ok(model._debug?.train), test = ok(model._debug?.test);
  const ev = { trainSeason: rep.seasons.train, testSeason: rep.seasons.test, nTrain: train.length, nTest: test.length };

  // 1. each input: alone (with game context) and the model without it, fit on last season, scored on this one
  let full = null;
  if (train.length > 200 && test.length > 50) {
    full = fitScore(train, test, all);
    const base = fitScore(train, test, ctx);
    ev.full = { logLoss: r4(full.logLoss), acc: r3(full.acc), mae: r2(full.mae) };
    ev.context = { logLoss: r4(base.logLoss), acc: r3(base.acc), mae: r2(base.mae) };
    // weight share: each group's spread of the rating, at the live weights (points of rating per SD of the input)
    const B = rep.beta, spread = g => sd([...train, ...test].map(p => g.cols.reduce((a, i) => a + B[FEATS[i]] * p.x[i], 0))) / Math.SQRT2;
    const tot = groups.reduce((a, g) => a + spread(g), 0) || 1;
    ev.inputs = groups.map(g => {
      const alone = fitScore(train, test, [...ctx, ...g.cols]), drop = fitScore(train, test, all.filter(i => !g.cols.includes(i)));
      const pa = paired(alone.per, base.per), pd = paired(drop.per, full.per);
      return { key: g.key, name: g.name, feats: g.cols.map(i => FEATS[i]), weight: g.cols.map(i => r3(B[FEATS[i]])), sdPts: r2(spread(g)), share: r3(spread(g) / tot),
        alone: { logLoss: r4(alone.logLoss), acc: r3(alone.acc), dLogLoss: r4(pa.d), t: r2(pa.t) },
        without: { logLoss: r4(drop.logLoss), acc: r3(drop.acc), dLogLoss: r4(pd.d), t: r2(pd.t) } };
    });
  }

  // 2. staff: does a coach's score explain what the model missed this season? The scores are built on this season's
  // results (a head coach's is mostly his team's Elo now and its Elo against its talent), and today's Elo already
  // contains the games being tested, so the naive fit is circular. The test that counts holds today's Elo and talent
  // fixed: what's left of a coach's score is what he adds beyond them. It enters at t >= 2 with a positive sign.
  const hcZ = {}, coZ = {};
  for (const c of coaches || []) {
    if (c.score == null) continue;
    if (c.role === 'HC') hcZ[c.tid] = (c.score - 100) / 10; else (coZ[c.tid] ||= []).push((c.score - 100) / 10);
  }
  for (const t of Object.keys(coZ)) coZ[t] = mean(coZ[t]);
  const staffIn = {};
  ev.staff = [];
  if (full && test.length > 50) {
    const res = test.map(p => p.r.m - dot(full.b, all.map(j => p.x[j])));
    const eloNow = t => ((model.elo?.[t] ?? 1500) - 1500) / 25, d = (f, p) => f(p.r.h) - f(p.r.a);
    for (const [key, name, Z] of [['hc', 'Head coach score', hcZ], ['coord', 'Coordinator scores', coZ]]) {
      const z = t => Z[t] ?? 0;
      const naive = coef(test.map(p => [d(z, p)]), res);
      const ctl = coef(test.map(p => [d(z, p), d(eloNow, p), d(t => talentZ[t] ?? 0, p)]), res);
      if (!naive) continue;
      const used = !!ctl && ctl.b > 0 && ctl.t >= 2;
      if (used) staffIn[key] = { b: ctl.b, Z };
      ev.staff.push({ key, name, naive: { ptsPerSd: r2(naive.b), t: r2(naive.t) }, ptsPerSd: ctl ? r2(ctl.b) : null, t: ctl ? r2(ctl.t) : null, n: res.length, used });
    }
  }

  // 3. head-to-head with the polls, both seasons; ours uses the weights fit on last season (out of sample this one)
  if (full) {
    const bTr = full.b, rateOf = p => all.reduce((a, j, k) => a + (rateCols.includes(j) ? bTr[k] * p.x[j] : 0), 0);
    const eloOf = p => p.x[col('elo')];
    const weeksBy = Object.fromEntries(Object.entries(hist).map(([S, raw]) => [S, pollWeeks(raw, resolve)]));
    ev.vsPolls = [];
    for (const [S, ps] of [[rep.seasons.train, train], [rep.seasons.test, test]]) {
      if (!weeksBy[S]?.length) continue;
      for (const poll of ['ap', 'coaches']) {
        const x = pickTest(ps.map(p => ({ ...p, r: { ...p.r, S } })), rateOf, weeksBy, poll);
        if (!x.n) continue;
        const elo = pickTest(ps.map(p => ({ ...p, r: { ...p.r, S } })), eloOf, weeksBy, poll);
        // the same with the poll a week staler, to check the week alignment isn't leaking results
        const stale = pickTest(ps.map(p => ({ ...p, r: { ...p.r, S } })), rateOf, weeksBy, poll, 1);
        ev.vsPolls.push({ season: +S, poll, fit: +S === rep.seasons.train ? 'in sample' : 'out of sample', ...x, eloPct: elo.oursPct, pollStalePct: stale.pollPct });
      }
    }
  }

  // 4. the live ranking: the model's rating split into its inputs, plus any staff term that passed
  const B = rep.beta, E = model.eff?.ppa || { O: {}, D: {} };
  const rows = teamList.map(t => {
    const id = String(t.tid), rating = model.rating?.[id];
    if (rating == null) return null;
    const parts = {
      elo: (B.elo || 0) * ((model.elo?.[id] ?? 1500) - 1500) / 25,
      eff: (B.net || 0) * 65 * ((E.O[id] ?? 0) - (E.D[id] ?? 0)),
      talent: ((B.talent || 0) + (late ? B.talentLate || 0 : 0)) * (talentZ[id] ?? 0),
      st: (B.st || 0) * (model.st?.[id] ?? 0),
      results: RESULTS.reduce((a, k) => a + (B[k] || 0) * (model.eff?.ex?.[k]?.O?.[id] ?? 0) * CAND[k].x, 0),
    };
    parts.situ = rating - parts.elo - parts.eff - parts.talent - parts.st - parts.results;
    let staff = 0; for (const s of Object.values(staffIn)) staff += s.b * (s.Z[id] ?? 0);
    parts.staff = staff;
    return { tid: id, team: t.team, abbr: t.abbr, logo: t.logo, color: t.color, conf: t.conf, rec: t.rec ? `${t.rec.w}-${t.rec.l}` : null,
      score: r1(rating + staff), rating: r1(rating), parts: Object.fromEntries(Object.entries(parts).map(([k, v]) => [k, r1(v)])),
      elo: t.elo ?? null, talentRk: t.talentRk ?? null, hc: t.hc || null };
  }).filter(Boolean).sort((a, b) => b.score - a.score);
  rows.forEach((r, i) => { r.rk = i + 1; });

  // movement: against the last ranking from an earlier week (carried until the next week's games are in)
  // (or, with no snapshot from an earlier week, the model's rating as of last week, ranked over the same teams)
  const snap = prev?.history?.[week - 1];
  let prevRk = snap ? { ...snap } : prev && prev.week != null && prev.week < week ? Object.fromEntries((prev.teams || []).map(r => [r.tid, r.rk]))
    : prev?.prevFrom === 'rebuilt' ? {} : prev?.prevRk || {};
  let prevFrom = Object.keys(prevRk).length ? 'snapshot' : null;
  if (!Object.keys(prevRk).length && model.ratingPrev) {
    const R = model.ratingPrev.rating;
    prevRk = Object.fromEntries(rows.filter(r => R[r.tid] != null).sort((a, b) => R[b.tid] - R[a.tid]).map((r, i) => [r.tid, i + 1]));
    prevFrom = 'rebuilt';
  }
  const pollRk = k => Object.fromEntries((polls[k]?.ranks || []).map(r => [r.tid, r.rk]));
  const ap = pollRk('ap'), co = pollRk('coaches'), cfp = pollRk('cfp');
  for (const r of rows) { r.prev = prevRk[r.tid] ?? null; r.ap = ap[r.tid] ?? null; r.coaches = co[r.tid] ?? null; if (polls.cfp) r.cfp = cfp[r.tid] ?? null; }
  const ours = Object.fromEntries(rows.map(r => [r.tid, r.rk]));
  for (const p of Object.values(polls)) for (const r of p.ranks) { r.ours = ours[r.tid] ?? null; const t = rows.find(x => x.tid === r.tid); if (t) { r.logo = t.logo; r.team = t.team; } }

  const history = { ...(prev?.history || {}), [week]: ours };   // every week's final ranking, kept
  return { week, prevRk, prevFrom, history, rk: ours, polls, teams: rows, staffUsed: Object.keys(staffIn), resultsUsed: RESULTS.filter(k => k in B), evidence: ev };
}
