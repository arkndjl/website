// Availability for the college projections tab: the chance each player plays this week, and who picks up the
// work of the players who don't. Fit and backtested by scripts/cfb_avail_backtest.mjs on ESPN box scores
// (scripts/cfb_box.mjs), written to data/cfb_avail_fit.json; scripts/cfb_teams.mjs reads the fit through availability().
//
//   P(plays)   a logistic on what the box scores say before kickoff: how often he has played his team's games
//              (shrunk), whether he missed the last one, two or three in a row, and his role (PPR a game when he
//              plays). A starter who missed last week is usually hurt; a backup missing from a box score usually
//              just didn't touch the ball.
//   status     a listed status (Rotoballer news, ESPN, manual) replaces the box-score odds with the rate measured
//              for that status: the NFL game status report's 2016-25 rates, updated by the college designations
//              the board has logged (data/cfb_avail_fit.json status, beta-binomial).
//   line       his line per game played (shrunk by m games toward zero) times P(plays). Volume a status takes
//              away (carries, catches, pass attempts) goes to the rest of the group in proportion to their shares,
//              at the backtest's elasticity: x (group volume before the statuses / after)^beta.
export const PPR = p => 0.04 * (p.passYds || 0) + 4 * (p.passTd || 0) - 2 * (p.int || 0) + 0.1 * (p.rushYds || 0) + 6 * (p.rushTd || 0)
  + (p.rec || 0) + 0.1 * (p.recYds || 0) + 6 * (p.recTd || 0);
export const STATS = ['att', 'cmp', 'passYds', 'passTd', 'int', 'car', 'rushYds', 'rushTd', 'rec', 'recYds', 'recTd'];
// volume groups: what each stat scales with when a teammate is out
export const GROUP = { att: 'pass', cmp: 'pass', passYds: 'pass', passTd: 'pass', int: 'pass', car: 'rush', rushYds: 'rush', rushTd: 'rush', rec: 'rec', recYds: 'rec', recTd: 'rec' };
const VOL = { pass: 'att', rush: 'car', rec: 'rec' };
export const QB_ATT = 5;      // pass attempts a game played that make a passer: his runs stay out of the carries pool

// the NFL game status report, 2016-25 (scripts/nfl_games.py): the share of players with each designation who played
export const NFL_PLAY = { Out: 0, 'Out (season)': 0, Doubtful: 0.02, Questionable: 0.75, 'Questionable-': 0.5, Probable: 0.95, Active: 0.95 };

const sig = z => 1 / (1 + Math.exp(-z));
const logit = p => Math.log(p / (1 - p));

// each team's finished games in order, with its box: tid -> [{ gid, date, players }]
export function timelines(games, boxes) {
  const tl = {};
  for (const g of [...games].filter(g => g.done && boxes[g.id]).sort((a, b) => a.date.localeCompare(b.date)))
    for (const tid of [g.home, g.away]) {
      const players = boxes[g.id].teams[tid]; if (!players) continue;
      (tl[tid] ||= []).push({ gid: g.id, date: g.date, week: g.week, players });
    }
  return tl;
}

// every player's record before a team's game k (its first k games): pid -> { n, gp, k, streak, tot, v, ppg }.
// v: his line per game played, shrunk toward zero by m games (a line from one or two games runs hot); ppg: PPR a
// game played, unshrunk (the P(plays) role feature)
export function states(list, k, m = 0) {
  const S = {};
  for (let j = 0; j < k; j++) for (const [pid, s] of Object.entries(list[j].players)) {
    const x = (S[pid] ||= { n: s.n, gp: 0, k, streak: 0, last: -1, tot: Object.fromEntries(STATS.map(f => [f, 0])) });
    x.gp++; x.last = j; x.n = s.n;
    for (const f of STATS) x.tot[f] += s[f] || 0;
  }
  for (const x of Object.values(S)) {
    x.streak = k - 1 - x.last;
    x.v = Object.fromEntries(STATS.map(f => [f, x.tot[f] / (x.gp + m)]));
    x.ppg = PPR(x.tot) / x.gp;
    x.qb = x.tot.att / x.gp >= QB_ATT;
  }
  return S;
}

// P(plays) features
export function feats(x) {
  const a = (x.gp + 1.4) / (x.k + 2), role = Math.log1p(Math.max(0, x.ppg));
  const m1 = x.streak >= 1 ? 1 : 0;
  return [1, logit(a), m1, x.streak >= 2 ? 1 : 0, x.streak >= 3 ? 1 : 0, role, m1 * role];
}
export const FEATS = ['const', 'logit share of games played', 'missed last', 'missed 2 straight', 'missed 3 straight', 'log(1 + PPR a game)', 'missed last x role'];
export const pBox = (coef, x) => sig(feats(x).reduce((s, f, i) => s + f * coef[i], 0));

// logistic regression by Newton steps (ridge 1e-3), rows [x, y]
export function logisticFit(rows, iters = 25) {
  const d = rows[0][0].length; let b = new Array(d).fill(0);
  for (let it = 0; it < iters; it++) {
    const g = new Array(d).fill(0), H = Array.from({ length: d }, () => new Array(d).fill(0));
    for (const [x, y] of rows) {
      const p = sig(x.reduce((s, v, i) => s + v * b[i], 0)), w = p * (1 - p);
      for (let i = 0; i < d; i++) { g[i] += (y - p) * x[i]; for (let j = 0; j < d; j++) H[i][j] += w * x[i] * x[j]; }
    }
    for (let i = 0; i < d; i++) { g[i] -= 1e-3 * b[i]; H[i][i] += 1e-3; }
    const step = solve(H, g); b = b.map((v, i) => v + step[i]);
    if (Math.max(...step.map(Math.abs)) < 1e-7) break;
  }
  return b;
}
function solve(A, y) {
  const n = y.length, M = A.map((r, i) => [...r, y[i]]);
  for (let c = 0; c < n; c++) {
    let p = c; for (let r = c + 1; r < n; r++) if (Math.abs(M[r][c]) > Math.abs(M[p][c])) p = r;
    [M[c], M[p]] = [M[p], M[c]];
    for (let r = 0; r < n; r++) if (r !== c) { const f = M[r][c] / M[c][c]; for (let j = c; j <= n; j++) M[r][j] -= f * M[c][j]; }
  }
  return M.map((r, i) => r[n] / r[i]);
}

// a listed status's chance of playing: the fit's measured rate when it has one, else the NFL rate
export function statusPlay(fit, status, missedLast) {
  if (!status) return null;
  const st = /season/i.test(status) ? 'Out (season)' : /^out/i.test(status) ? 'Out' : /doubt/i.test(status) ? 'Doubtful'
    : /quest/i.test(status) ? (missedLast ? 'Questionable-' : 'Questionable') : /prob/i.test(status) ? 'Probable' : /active/i.test(status) ? 'Active' : null;
  if (!st) return null;
  return fit?.status?.[st]?.p ?? NFL_PLAY[st];
}

// each player's volume multipliers when teammates may not play: pid -> { pass, rush, rec }. P: pid -> P(plays);
// P0: pid -> P(plays) from the box scores alone, before any status; beta: { pass, rush, rec }. Only what a status
// takes away moves to teammates: an absence the box scores already show (he missed the last two games) is in his
// teammates' lines already (the backtest put the elasticity for box-score absences at zero).
export function groupMult(S, P, P0, beta = {}) {
  const sums = { pass: [0, 0, 0], rush: [0, 0, 0], rec: [0, 0, 0] };   // volume before the statuses, after, the top player's
  const inPool = (x, g) => g === 'pass' ? x.qb : g === 'rush' ? !x.qb : true;
  for (const [pid, x] of Object.entries(S)) for (const g of ['pass', 'rush', 'rec']) {
    if (!inPool(x, g)) continue;
    const v = x.v[VOL[g]];
    sums[g][0] += P0[pid] * v; sums[g][1] += P[pid] * v; sums[g][2] = Math.max(sums[g][2], v);
  }
  const R = Object.fromEntries(Object.entries(sums).map(([g, [u, w]]) => [g, w > 0 ? Math.max(1, u / w) : 1]));
  const out = {};
  for (const [pid, x] of Object.entries(S)) {
    const mult = {};
    for (const g of ['pass', 'rush', 'rec']) {
      let m = inPool(x, g) ? R[g] ** (beta[g] ?? 0) : 1;
      const v = x.v[VOL[g]];
      // nobody expects more than the group's top load: a backup quarterback who rarely gets in (P(plays) .4) with the
      // starter out for the season takes up to the starter's load in expectation, through the multiplier
      if (v > 0 && P[pid] > 0 && P[pid] * v * m > sums[g][2]) m = Math.max(1, sums[g][2] / (P[pid] * v));
      mult[g] = Math.round(m * 1000) / 1000;
    }
    out[pid] = mult;
  }
  return out;
}

// one team's expected lines for its next game from the box scores: pid -> { p, mult, line (expected stats), pts }
export function teamLines(S, P, beta = {}, P0 = P) {
  const M = groupMult(S, P, P0, beta), out = {};
  for (const [pid, x] of Object.entries(S)) {
    const line = Object.fromEntries(STATS.map(f => [f, P[pid] * x.v[f] * M[pid][GROUP[f]]]));
    out[pid] = { p: P[pid], mult: M[pid], line, pts: PPR(line) };
  }
  return out;
}

// the board's read for one team before its next game: pid -> { p, p0, status, scale (his per-team-game line to
// per game played: team games / (games played + m)), mult, ppg (PPR a game played), main (his main volume group) }. games: the team's box scores
// this season, in order (timelines()); statusOf: player name -> listed status or null
export function teamAvailability(fit, games, statusOf) {
  if (!fit?.coef || !games?.length) return {};
  const k = games.length, S = states(games, k, fit.m ?? 0);
  const P0 = {}, P = {}, st = {};
  for (const [pid, x] of Object.entries(S)) {
    P0[pid] = pBox(fit.coef, x); st[pid] = statusOf(x.n) || null;
    P[pid] = statusPlay(fit, st[pid], x.streak >= 1) ?? P0[pid];
  }
  const M = groupMult(S, P, P0, fit.beta), out = {};
  for (const [pid, x] of Object.entries(S))
    out[pid] = { n: x.n, p: P[pid], p0: P0[pid], status: st[pid], scale: k / (x.gp + (fit.m ?? 0)), mult: M[pid], ppg: x.ppg, gp: x.gp, k, streak: x.streak,
      main: x.qb ? 'pass' : 0.1 * x.v.rushYds + 6 * x.v.rushTd >= x.v.rec + 0.1 * x.v.recYds + 6 * x.v.recTd ? 'rush' : 'rec' };
  return out;
}
