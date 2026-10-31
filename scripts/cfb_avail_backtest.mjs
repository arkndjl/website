// Fits and backtests the availability model of the college projections tab (scripts/cfb_avail.mjs) on ESPN box
// scores, 2023 on, walk-forward: each season is projected with the P(plays) logistic and the volume elasticities
// fit on the seasons before it only. Writes data/cfb_avail_fit.json (the fit the board uses, the backtest for the page).
//
// Every projection is a player's line per game from his team's earlier games this season (two or more), the
// same per-game rates the tab uses, without the opponent scaling (the same for every variant here):
//   site     totals over team games (the tab before this change: a game he missed counts as a zero)
//   avail    his line per game played x P(plays)
//   share    avail, plus the volume teammates likely to miss leave behind
// against what he scored (PPR; zero when he isn't in the box score). Players new to the box score that week
// aren't projected by any variant.
//
// The college status rates: every designation in the board's availability log (data/cfb_injuries.json, each
// commit of it), matched to the team's next game and the box score, for players with a box score before it. A beta-binomial on the NFL rate (prior
// weight STATUS_K games) gives the rate the board uses.
//
// usage: node scripts/cfb_avail_backtest.mjs   (pulls box scores it doesn't have: ~900 games a season)
import fs from 'node:fs';
import path from 'node:path';
import { execSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { fetchGames, statusOf } from './cfb_teams.mjs';
import { fetchBoxes } from './cfb_box.mjs';
import { timelines, states, feats, pBox, logisticFit, teamLines, PPR, STATS, FEATS, NFL_PLAY } from './cfb_avail.mjs';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const CACHE = path.join(ROOT, 'scripts', '.cache', 'cfb');
const SEASONS = [2023, 2024, 2025, 2026], MIN_K = 2, STATUS_K = 10;
const r3 = x => Math.round(x * 1000) / 1000, r2 = x => Math.round(x * 100) / 100;

const seasonGames = {};
for (const s of SEASONS) {
  const f = path.join(CACHE, `bt_games${s}.json`);
  let g = null; try { g = JSON.parse(fs.readFileSync(f, 'utf8')); } catch {}
  // a past season's schedule is fixed; the current one is pulled again each run
  if (!g || s === Math.max(...SEASONS)) { g = await fetchGames(s); fs.mkdirSync(CACHE, { recursive: true }); fs.writeFileSync(f, JSON.stringify(g)); }
  seasonGames[s] = g;
}
const boxes = {};
for (const s of SEASONS) Object.assign(boxes, await fetchBoxes(seasonGames[s], { log: false }));

// every team game with two or more earlier games: the states before it and who played
const spots = {};
for (const s of SEASONS) {
  const tl = timelines(seasonGames[s], boxes);
  spots[s] = [];
  for (const [tid, list] of Object.entries(tl)) for (let k = MIN_K; k < list.length; k++)
    spots[s].push({ tid, k, date: list[k].date, S: states(list, k), act: list[k].players });
}
console.log(SEASONS.map(s => `${s}: ${spots[s].length} team games`).join(' · '));

const rowsOf = ss => ss.flatMap(s => spots[s].flatMap(sp => Object.entries(sp.S).map(([pid, x]) => [feats(x), sp.act[pid] ? 1 : 0])));
const MS = [0, 0.25, 0.5, 1, 1.5, 2], BETAS = [0, 0.25, 0.5, 0.75, 1, 1.25, 1.5];
const ptsOf = (sp, pid) => sp.act[pid] ? PPR(sp.act[pid]) : 0;
// the states at shrinkage m (the lines per game played over gp + m games)
const atM = (S, m) => Object.fromEntries(Object.entries(S).map(([pid, x]) => [pid, { ...x, v: Object.fromEntries(STATS.map(f => [f, x.tot[f] / (x.gp + m)])) }]));
const pOf = (coef, S) => Object.fromEntries(Object.entries(S).map(([pid, x]) => [pid, pBox(coef, x)]));
// a fresh absence: a player with a role (5+ PPR a game played, two or more games) who played his team's last game and
// isn't in this one's box score. The box scores can't see it coming; an Out on the report can. Standing in for that
// report, the news test lists him Out (P(plays) 0) and asks how much of his work his teammates' lines should pick up.
const fresh = sp => Object.entries(sp.S).filter(([pid, x]) => x.ppg >= 5 && x.gp >= 2 && x.streak === 0 && !sp.act[pid]).map(([pid]) => pid);

function sseAvail(ss, coef, m) {
  let e = 0;
  for (const s of ss) for (const sp of spots[s]) {
    const S = atM(sp.S, m), P = pOf(coef, sp.S);
    for (const [pid, x] of Object.entries(S)) e += (P[pid] * PPR(x.v) - ptsOf(sp, pid)) ** 2;
  }
  return e;
}
function newsLines(sp, coef, m, beta) {
  const S = atM(sp.S, m), P0 = pOf(coef, sp.S), out = new Set(sp.out), P = { ...P0 };
  for (const pid of out) P[pid] = 0;
  return teamLines(S, P, beta, P0);
}
function sseNews(ss, coef, m, beta) {
  let e = 0;
  for (const s of ss) for (const sp of spots[s]) {
    if (!sp.out.length) continue;
    const L = newsLines(sp, coef, m, beta);
    for (const pid of Object.keys(sp.S)) if (!sp.out.includes(pid)) e += (L[pid].pts - ptsOf(sp, pid)) ** 2;
  }
  return e;
}
const argmin = (xs, f) => xs.map(x => [x, f(x)]).sort((a, b) => a[1] - b[1])[0][0];
function fitBeta(ss, coef, m) {
  const beta = { pass: 0, rush: 0, rec: 0 };
  for (let pass = 0; pass < 2; pass++) for (const g of ['pass', 'rush', 'rec']) beta[g] = argmin(BETAS, b => sseNews(ss, coef, m, { ...beta, [g]: b }));
  return beta;
}
for (const s of SEASONS) for (const sp of spots[s]) sp.out = fresh(sp);

// walk-forward
const V = ['site', 'avail'], VN = ['site', 'noShare', 'share'];
const acc = vs => ({ n: 0, vs, ae: Object.fromEntries(vs.map(k => [k, 0])), se: Object.fromEntries(vs.map(k => [k, 0])), e: Object.fromEntries(vs.map(k => [k, 0])) });
const add = (a, y, pr) => { a.n++; for (const [k, v] of Object.entries(pr)) { a.ae[k] += Math.abs(v - y); a.se[k] += (v - y) ** 2; a.e[k] += v - y; } };
const fin = a => ({ n: a.n, ...Object.fromEntries(a.vs.map(k => [k, { mae: r3(a.ae[k] / a.n), rmse: r3(Math.sqrt(a.se[k] / a.n)), bias: r3(a.e[k] / a.n) }])) });
const test = [], calib = {};
for (const s of SEASONS.slice(1)) {
  const train = SEASONS.filter(x => x < s);
  const coef = logisticFit(rowsOf(train)), m = argmin(MS, mm => sseAvail(train, coef, mm)), beta = fitBeta(train, coef, m);
  const A = { all: acc(V), relevant: acc(V), returning: acc(V), missed: acc(V) }, N = { teammates: acc(VN), group: acc(VN) };
  const ll = { box: 0, share: 0, n: 0 };
  for (const sp of spots[s]) {
    const S = atM(sp.S, m), P = pOf(coef, sp.S);
    for (const [pid, x] of Object.entries(S)) {
      const y = ptsOf(sp, pid), played = sp.act[pid] ? 1 : 0;
      const site = PPR(x.tot) / x.k, pr = { site, avail: P[pid] * PPR(x.v) };
      add(A.all, y, pr);
      if (Math.max(site, pr.avail) >= 8) add(A.relevant, y, pr);
      if (x.ppg >= 8 && x.gp < x.k && x.streak === 0) add(A.returning, y, pr);    // back from a missed game
      if (x.ppg >= 8 && x.streak >= 1) add(A.missed, y, pr);                       // missed the last one
      const sh = x.gp / x.k, p = P[pid];
      ll.box -= played ? Math.log(p) : Math.log(1 - p);
      ll.share -= played ? Math.log(Math.min(0.99, Math.max(0.01, sh))) : Math.log(Math.min(0.99, Math.max(0.01, 1 - sh)));
      ll.n++;
      const b = Math.min(9, Math.floor(p * 10)); const c = (calib[b] ||= { n: 0, p: 0, y: 0 }); c.n++; c.p += p; c.y += played;
    }
    // the news test: teammates of a fresh absence listed Out
    if (sp.out.length) {
      const L0 = newsLines(sp, coef, m, {}), L1 = newsLines(sp, coef, m, beta);
      const groups = new Set(sp.out.map(pid => sp.S[pid].qb ? 'pass' : sp.S[pid].v.car > sp.S[pid].v.rec ? 'rush' : 'rec'));
      for (const [pid, x] of Object.entries(sp.S)) {
        if (sp.out.includes(pid)) continue;
        const y = ptsOf(sp, pid), pr = { site: PPR(x.tot) / x.k, noShare: L0[pid].pts, share: L1[pid].pts };
        if (Math.max(pr.site, pr.share) < 3) continue;
        add(N.teammates, y, pr);
        const g = x.qb ? 'pass' : x.v.car > x.v.rec ? 'rush' : 'rec';
        if (groups.has(g)) add(N.group, y, pr);
      }
    }
  }
  test.push({ season: s, train, m, beta, logloss: { box: r3(ll.box / ll.n), share: r3(ll.share / ll.n) },
    ...Object.fromEntries(Object.entries(A).map(([k, a]) => [k, fin(a)])), news: Object.fromEntries(Object.entries(N).map(([k, a]) => [k, fin(a)])) });
  console.log(s, JSON.stringify(test.at(-1)));
}
// the live fit: every season
const cAll = logisticFit(rowsOf(SEASONS)), mAll = argmin(MS, mm => sseAvail(SEASONS, cAll, mm)), bAll = fitBeta(SEASONS, cAll, mAll);

// cells: what the box scores alone say, for the write-up (all seasons): role x games missed in a row
const cells = {};
for (const s of SEASONS) for (const sp of spots[s]) for (const [pid, x] of Object.entries(sp.S)) {
  if (x.ppg < 8) continue;
  const key = `${x.streak >= 3 ? '3+' : x.streak}`;
  const c = (cells[key] ||= { n: 0, played: 0 }); c.n++; c.played += sp.act[pid] ? 1 : 0;
}

// college status rates: each designation in the availability log's history, against the next game's box score
const status = {};
{
  const S26 = timelines(seasonGames[2026], boxes);
  const seen = new Map();
  let revs = [];
  try { revs = execSync('git log --format=%H -- data/cfb_injuries.json', { cwd: ROOT }).toString().trim().split('\n').filter(Boolean); } catch {}
  const versions = revs.map(h => { try { return JSON.parse(execSync(`git show ${h}:data/cfb_injuries.json`, { cwd: ROOT, maxBuffer: 1 << 26 }).toString()); } catch { return null; } });
  try { versions.push(JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'cfb_injuries.json'), 'utf8'))); } catch {}
  // a Rotoballer status read off the blurb rather than the headline is left out: before the parser fix, matchup
  // previews read as Out there
  for (const v of versions) for (const [pid, e] of Object.entries(v?.players || {}))
    if (e.src !== 'rotoballer' || statusOf(e.note)) seen.set(`${pid}|${e.date}`, { pid, ...e });
  // the latest designation before each game
  const last = {};
  for (const e of seen.values()) {
    const list = S26[e.tid]; if (!list) continue;
    const k = list.findIndex(g => g.date > e.date); if (k < 0 || Date.parse(list[k].date) - Date.parse(e.date) > 8 * 864e5) continue;
    const key = `${e.pid}|${k}`; if (!last[key] || last[key].date < e.date) last[key] = { ...e, k };
  }
  for (const e of Object.values(last)) {
    const list = S26[e.tid], S = states(list, e.k), x = S[e.pid];
    if (!x) continue;                        // never in a box score before: no way to tell a miss from a quiet game
    const st = /season/i.test(e.status) ? 'Out (season)' : e.status === 'Questionable' && x.streak >= 1 ? 'Questionable-' : e.status;
    const c = (status[st] ||= { n: 0, played: 0 }); c.n++; c.played += list[e.k].players[e.pid] ? 1 : 0;
  }
  for (const [st, c] of Object.entries(status)) {
    const p0 = NFL_PLAY[st] ?? 0.5;
    c.nfl = p0; c.p = r3((c.played + STATUS_K * p0) / (c.n + STATUS_K));
  }
  for (const [st, p0] of Object.entries(NFL_PLAY)) status[st] ||= { n: 0, played: 0, nfl: p0, p: p0 };
}

// every test season together (the tab's footnote): rmse pooled over player-games, bias weighted the same way
const pool = (get, vs) => {
  const n = test.reduce((a, t) => a + get(t).n, 0);
  return { n, ...Object.fromEntries(vs.map(v => [v, { rmse: r3(Math.sqrt(test.reduce((a, t) => a + get(t).n * get(t)[v].rmse ** 2, 0) / n)),
    bias: r3(test.reduce((a, t) => a + get(t).n * get(t)[v].bias, 0) / n) }])) };
};
const pooled = { all: pool(t => t.all, V), relevant: pool(t => t.relevant, V), missed: pool(t => t.missed, V), returning: pool(t => t.returning, V),
  newsGroup: pool(t => t.news.group, VN) };
const out = { asof: new Date().toISOString().slice(0, 10), seasons: SEASONS, minGames: MIN_K, feats: FEATS, coef: cAll.map(x => Math.round(x * 1e4) / 1e4), m: mAll, beta: bAll,
  status, statusPrior: STATUS_K,
  cells: Object.fromEntries(Object.entries(cells).sort().map(([k, c]) => [k, { n: c.n, p: r3(c.played / c.n) }])),
  calib: Object.entries(calib).sort((a, b) => a[0] - b[0]).map(([, c]) => ({ n: c.n, p: r3(c.p / c.n), played: r3(c.y / c.n) })),
  pooled, test };
// the conference reports' fit (scripts/cfb_avail_reports_backtest.mjs) rides along: it fits on the box P(plays) above;
// rerun that script after a refit here
try { const prev = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'cfb_avail_fit.json'), 'utf8')); if (prev.reports) out.reports = prev.reports; } catch {}
fs.writeFileSync(path.join(ROOT, 'data', 'cfb_avail_fit.json'), JSON.stringify(out, null, 1) + '\n');
console.log('fit', JSON.stringify({ coef: out.coef, m: mAll, beta: bAll, status, cells: out.cells }));
