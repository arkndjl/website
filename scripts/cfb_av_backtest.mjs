// Backtest for season AV (scripts/cfb_av.mjs): what a college player is worth to his team this season, against
// team results. Run by hand: node scripts/cfb_av_backtest.mjs -> data/cfb_av_backtest.json
// Data: PFN impact rankings (FBS; QB, RB, WR, TE, EDGE, DT, LB since 2019, OL, CB, S since 2024), ESPN results
// 2019-26, nflverse draft picks, and this season's board (static/data/cfb-all.json, data/cfb_teams.json).
//   srs       team margin a game, opponent-adjusted: ridge least squares on FBS-vs-FBS margins capped at 35, with
//             home field
//   features  per team season and position: the players by playing time (games played / team games before
//             2026, snap share in 2026) filling the position's STARTERS slots, sum of share and of share x z (z on
//             the starter pool: the top STARTERS x teams scores at the position that season)
//   weights   SRS ~ sum over positions of w x (Z - zr x T), w ridge toward one common weight; fit on 2024-25
//             (all ten positions), leave one season out for the grid, then tested on 2026 against the board's
//             team talent (summed avOf(fv) of the starters, the AV a season every consumer reads today)
//   inputs    within 2026, each extra input's team sum added to the season-AV sum, 20 x 10-fold cross-validated
//   forward   last season's season AV of each returning player, summed at his new team, against this season's
//             SRS, with and without last season's SRS
//   nfl       final college season (2019-22) against weighted NFL AV a season (undrafted 0), next to Stat+ alone
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { fetchGames } from './cfb_teams.mjs';
import { seasonAv, teamSeasonAv, badgePoints, SAV_W, SAV_REPL, SAV_Q, SAV_PTS } from './cfb_av.mjs';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const CACHE = path.join(ROOT, 'scripts', '.cache', 'av');
const OUT = path.join(ROOT, 'data', 'cfb_av_backtest.json');
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36';
fs.mkdirSync(CACHE, { recursive: true });
const PFN = { QB: 'quarterback', RB: 'running-back', WR: 'wide-receiver', TE: 'tight-end', OL: 'offensive-line', EDGE: 'edge', DL: 'defensive-tackle', LB: 'linebacker', CB: 'cornerback', S: 'safety' };
const POS = Object.keys(PFN);
const STARTERS = { QB: 1, RB: 1, WR: 3, TE: 1, OL: 5, EDGE: 2, DL: 2, LB: 2, CB: 3, S: 2 };
const YEARS = [2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026], FIT = [2024, 2025], TEST = 2026;
const mean = xs => xs.reduce((a, b) => a + b, 0) / Math.max(1, xs.length);
const sd = xs => { const m = mean(xs); return Math.sqrt(mean(xs.map(x => (x - m) ** 2))) || 1; };
const corr = (x, y) => { const mx = mean(x), my = mean(y); let a = 0, b = 0, c = 0; x.forEach((v, i) => { a += (v - mx) * (y[i] - my); b += (v - mx) ** 2; c += (y[i] - my) ** 2; }); return a / Math.sqrt(b * c); };
const r3 = x => Math.round(x * 1000) / 1000;
function solve(A, b) {   // Gaussian elimination with partial pivoting
  const n = b.length, M = A.map((r, i) => [...r, b[i]]);
  for (let c = 0; c < n; c++) {
    let p = c; for (let r = c + 1; r < n; r++) if (Math.abs(M[r][c]) > Math.abs(M[p][c])) p = r;
    [M[c], M[p]] = [M[p], M[c]];
    for (let r = c + 1; r < n; r++) { const f = M[r][c] / M[c][c]; for (let k = c; k <= n; k++) M[r][k] -= f * M[c][k]; }
  }
  const x = Array(n).fill(0);
  for (let r = n - 1; r >= 0; r--) { let s = M[r][n]; for (let k = r + 1; k < n; k++) s -= M[r][k] * x[k]; x[r] = s / M[r][r]; }
  return x;
}
// least squares with an intercept; lam: ridge on the slopes (not the intercept)
function ols(X, y, lam = 0) {
  const k = X[0].length, A = Array.from({ length: k + 1 }, () => Array(k + 1).fill(0)), b = Array(k + 1).fill(0);
  X.forEach((r, i) => { const z = [1, ...r]; for (let a = 0; a <= k; a++) { b[a] += z[a] * y[i]; for (let c = 0; c <= k; c++) A[a][c] += z[a] * z[c]; } });
  for (let a = 1; a <= k; a++) A[a][a] += lam;
  return solve(A, b);
}
const predict = (co, r) => co[0] + r.reduce((a, x, i) => a + co[i + 1] * x, 0);
const r2of = (y, p) => { const m = mean(y); return 1 - y.reduce((a, v, i) => a + (v - p[i]) ** 2, 0) / y.reduce((a, v) => a + (v - m) ** 2, 0); };

// ---- sources ------------------------------------------------------------------------------------------------
function jsonEnd(s, i) { let d = 0, q = false; for (let k = i; k < s.length; k++) { const c = s[k]; if (q) { if (c === '\\') k++; else if (c === '"') q = false; continue; } if (c === '"') q = true; else if (c === '{' || c === '[') d++; else if (c === '}' || c === ']') { d--; if (!d) return k + 1; } } }
async function pfn(g) {
  const f = path.join(CACHE, `pfn_${g}.json`); if (fs.existsSync(f)) return JSON.parse(fs.readFileSync(f));
  const html = await (await fetch(`https://www.profootballnetwork.com/cfb-hq/impact-rankings/${PFN[g]}`, { headers: { 'user-agent': UA } })).text();
  const s = [...html.matchAll(/self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)/g)].map(m => JSON.parse(m[1])).find(c => c.includes('"packed":'));
  const i = s.indexOf('"packed":') + 9, packed = JSON.parse(s.slice(i, jsonEnd(s, i)));
  const rows = packed.rows.map(r => Object.fromEntries(packed.cols.map((c, k) => [c, r[k]])));
  fs.writeFileSync(f, JSON.stringify(rows)); return rows;
}
async function games(y) {
  const f = path.join(CACHE, `games${y}.json`); if (fs.existsSync(f) && y < TEST) return JSON.parse(fs.readFileSync(f));
  const g = await fetchGames(y); fs.writeFileSync(f, JSON.stringify(g)); return g;
}
const norm = s => (s || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/&/g, 'and').replace(/[^a-z0-9 ]/g, '').replace(/\s+/g, ' ').trim();
const ALIAS = { 'miami fl': 'miami', mississippi: 'ole miss', usf: 'south florida', 'north carolina state': 'nc state', 'appalachian state': 'app state',
  connecticut: 'uconn', louisianamonroe: 'ul monroe', 'sam houston state': 'sam houston' };

// ---- team margin: SRS ----------------------------------------------------------------------------------------
const SRS = {}, TG = {}, nameId = {};
for (const y of YEARS) {
  const G = (await games(y)).filter(g => g.done), cnt = {};
  for (const g of G) { for (const t of [g.home, g.away]) cnt[t] = (cnt[t] || 0) + 1; nameId[norm(g.homeName)] = g.home; nameId[norm(g.awayName)] = g.away; }
  const fbs = Object.keys(cnt).filter(t => cnt[t] >= (y === 2020 ? 3 : 5)), ix = Object.fromEntries(fbs.map((t, i) => [t, i])), n = fbs.length;
  const A = Array.from({ length: n + 1 }, () => Array(n + 1).fill(0)), b = Array(n + 1).fill(0);
  for (const g of G) {
    if (ix[g.home] == null || ix[g.away] == null) continue;
    const z = Array(n + 1).fill(0); z[ix[g.home]] = 1; z[ix[g.away]] = -1; z[n] = g.neutral ? 0 : 1;
    const m = Math.max(-35, Math.min(35, g.hs - g.as)), nz = [ix[g.home], ix[g.away], n];
    for (const a of nz) { b[a] += z[a] * m; for (const c of nz) A[a][c] += z[a] * z[c]; }
  }
  for (let i = 0; i < n; i++) A[i][i] += 2;
  const x = solve(A, b), m = mean(x.slice(0, n));
  SRS[y] = Object.fromEntries(fbs.map((t, i) => [t, x[i] - m])); TG[y] = Object.fromEntries(fbs.map(t => [t, cnt[t]]));
}

// ---- player seasons ------------------------------------------------------------------------------------------
const rows = [];
for (const g of POS) for (const r of await pfn(g)) {
  if (r.division !== 'FBS') continue;
  const k = norm(r.team), tid = nameId[ALIAS[k] || k]; if (!tid || !SRS[r.season]?.[tid]) continue;
  rows.push({ id: r.id, name: r.name, pos: g, season: r.season, tid, score: r.score, sh: Math.min(1, (+r.gp || 0) / TG[r.season][tid]) });
}
for (const y of YEARS) for (const g of POS) {
  const list = rows.filter(r => r.season === y && r.pos === g); if (!list.length) continue;
  const pool = list.map(r => r.score).sort((a, b) => b - a).slice(0, STARTERS[g] * Object.keys(SRS[y]).length), m = mean(pool), s = sd(pool);
  for (const r of list) r.z = (r.score - m) / s;
}
// [T, Z] per position, the team's players by playing time filling the starter slots
function feats(list, share, q) {
  const by = {};
  for (const p of list) (by[p.tid] ||= []).push(p);
  const F = {};
  for (const [tid, ps] of Object.entries(by)) F[tid] = POS.flatMap(g => {
    let T = 0, Z = 0;
    for (const p of ps.filter(p => p.pos === g).sort((a, b) => share(b) - share(a))) { const s = Math.min(share(p), STARTERS[g] - T); if (s <= 0) break; T += s; Z += s * q(p); }
    return [T, Z];
  });
  return F;
}
const F = {};
for (const y of YEARS.filter(y => y < TEST)) F[y] = feats(rows.filter(r => r.season === y), p => p.sh, p => p.z);
const XY = (ys, zr) => { const X = [], Y = []; for (const y of ys) for (const [t, s] of Object.entries(SRS[y])) { const f = F[y][t] || Array(20).fill(0); X.push(POS.map((g, i) => f[2 * i + 1] - zr * f[2 * i])); Y.push(s); } return [X, Y]; };
// w = common weight + ridge deviation
function fitW(X, Y, lam) {
  const tot = X.map(r => r.reduce((a, b) => a + b, 0)), c0 = ols(tot.map(x => [x]), Y), w0 = c0[1];
  const dev = ols(X, Y.map((y, i) => y - c0[0] - w0 * tot[i]), lam);
  return { w: dev.slice(1).map(d => w0 + d), c: c0[0] + dev[0] };
}
const grid = [];
for (const zr of [-2, -1.5, -1, -0.5, 0]) for (const lam of [10, 50, 200]) {
  const ys = [], ps = [];
  for (const y of FIT) { const [X, Y] = XY(FIT.filter(x => x !== y), zr), m = fitW(X, Y, lam), [Xt, Yt] = XY([y], zr); ys.push(...Yt); ps.push(...Xt.map(r => m.c + r.reduce((a, x, i) => a + m.w[i] * x, 0))); }
  grid.push({ zr, lam, oosR2: r3(r2of(ys, ps)) });
}
const [Xf, Yf] = XY(FIT, SAV_REPL), fit = fitW(Xf, Yf, 50);

// ---- 2026: season AV against summed avOf(fv) -----------------------------------------------------------------
const all = JSON.parse(fs.readFileSync(path.join(ROOT, 'static', 'data', 'cfb-all.json'), 'utf8'));
const board = all.rows.map(r => Object.fromEntries(all.cols.map((c, i) => [c, r[i]]))).filter(p => p.div === 'FBS')
  .map(p => ({ ...p, tid: /\/(\d+)\.png/.exec(p.logo || '')?.[1] || null }));
seasonAv(board);
const T26 = Object.fromEntries(JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'cfb_teams.json'), 'utf8')).teams.map(t => [t.tid, t]));
const byTeam = {}; for (const p of board) if (p.tid) (byTeam[p.tid] ||= []).push(p);
const tids = Object.keys(SRS[TEST]).filter(t => T26[t] && byTeam[t]), Y26 = tids.map(t => SRS[TEST][t]);
const sav26 = tids.map(t => teamSeasonAv(byTeam[t])), tal26 = tids.map(t => T26[t].talent), pri26 = tids.map(t => T26[t].prior ?? 1500);
const r2c = cols => r2of(Y26, (co => tids.map((t, i) => predict(co, cols.map(c => c[i]))))(ols(tids.map((t, i) => cols.map(c => c[i])), Y26)));
// Stat+ alone (no badges, no FV), with the fitted weights
const live = board.filter(p => p.savQ != null), zOnly = new Map();
{ const by = {}; for (const p of live) (by[p.pos] ||= []).push(p); const nT = new Set(live.map(p => p.tid)).size;
  for (const [g, ps] of Object.entries(by)) { const pool = ps.map(p => p.pfn).sort((a, b) => b - a).slice(0, STARTERS[g] * nT), m = mean(pool), s = sd(pool); for (const p of ps) zOnly.set(p, (p.pfn - m) / s); } }
const sumWith = q => { const f = feats(live, p => p.snapShare, q); return tids.map(t => POS.reduce((a, g, i) => a + SAV_W[g] * ((f[t]?.[2 * i + 1] ?? 0) - SAV_REPL * (f[t]?.[2 * i] ?? 0)), 0)); };
const stat26 = sumWith(p => zOnly.get(p));
// extra inputs, cross-validated on 2026 team sums
function cv(cols, base) {
  let sse0 = 0, sse1 = 0, sst = 0, seed = 7;
  const rand = () => (seed = (seed * 16807) % 2147483647) / 2147483647, n = tids.length;
  for (let rep = 0; rep < 20; rep++) {
    const idx = [...Array(n).keys()].map(i => [rand(), i]).sort((a, b) => a[0] - b[0]).map(x => x[1]);
    for (let f = 0; f < 10; f++) {
      const te = new Set(idx.filter((_, k) => k % 10 === f)), tr = idx.filter(i => !te.has(i)), ym = mean(tr.map(i => Y26[i]));
      const c0 = ols(tr.map(i => [base[i]]), tr.map(i => Y26[i])), c1 = ols(tr.map(i => [base[i], ...cols.map(c => c[i])]), tr.map(i => Y26[i]));
      for (const i of te) { sse0 += (Y26[i] - predict(c0, [base[i]])) ** 2; sse1 += (Y26[i] - predict(c1, [base[i], ...cols.map(c => c[i])])) ** 2; sst += (Y26[i] - ym) ** 2; }
    }
  }
  return { base: r3(1 - sse0 / sst), with: r3(1 - sse1 / sst) };
}
const zOf = f => { const by = {}, out = new Map(), nT = new Set(live.map(p => p.tid)).size; for (const p of live) (by[p.pos] ||= []).push(p);
  for (const [g, ps] of Object.entries(by)) { const v = ps.map(f), pool = [...v].sort((a, b) => b - a).slice(0, STARTERS[g] * nT), m = mean(pool), s = sd(pool); ps.forEach((p, i) => out.set(p, (v[i] - m) / s)); } return out; };
const INPUTS = { badges: zOf(badgePoints), fv: zOf(p => p.fv), statsBar: zOf(p => p.parts?.[4] ?? 0), context: zOf(p => p.parts?.[6] ?? 0), recruiting: zOf(p => p.parts?.[0] ?? 0) };
const inputs = {};
for (const [k, z] of Object.entries(INPUTS)) {
  const s = sumWith(p => z.get(p)).map((v, i) => v - sumWith(() => 0)[i]), co = ols(tids.map((t, i) => [stat26[i], s[i]]), Y26);
  inputs[k] = { ...cv([s], stat26), gammaPerZ: r3(co[2] / co[1]) };
}

// ---- forward: returning season AV ----------------------------------------------------------------------------
const W = Object.fromEntries(POS.map((g, i) => [g, fit.w[i]]));
for (const r of rows) r.v = r.sh * W[r.pos] * (r.z - SAV_REPL);
const forward = {};
for (const y of [2021, 2022, 2023, 2024, 2025]) {
  const prev = new Map(rows.filter(r => r.season === y - 1).map(r => [r.id + '|' + r.pos, r.v])), ret = {};
  for (const r of rows.filter(r => r.season === y)) { const v = prev.get(r.id + '|' + r.pos); if (v != null) ret[r.tid] = (ret[r.tid] || 0) + v; }
  const ts = Object.keys(SRS[y]).filter(t => SRS[y - 1][t] != null), Y = ts.map(t => SRS[y][t]), L = ts.map(t => SRS[y - 1][t]), R = ts.map(t => ret[t] || 0);
  const r2x = cols => r2of(Y, (co => ts.map((t, i) => predict(co, cols.map(c => c[i]))))(ols(ts.map((t, i) => cols.map(c => c[i])), Y)));
  forward[y] = { lastSrs: r3(r2x([L])), returning: r3(r2x([R])), both: r3(r2x([L, R])) };
}

// ---- NFL: final college season against NFL AV ----------------------------------------------------------------
const picksFile = path.join(CACHE, 'draft_picks.csv');
if (!fs.existsSync(picksFile)) fs.writeFileSync(picksFile, await (await fetch('https://github.com/nflverse/nflverse-data/releases/download/draft_picks/draft_picks.csv')).text());
const [h, ...pl] = fs.readFileSync(picksFile, 'utf8').trim().split('\n'), H = h.split(',');
const picks = pl.map(l => { const v = l.split(','); return Object.fromEntries(H.map((k, i) => [k, v[i]])); }).filter(r => +r.season >= 2020 && +r.season <= 2025);
const nm = s => (s || '').toLowerCase().normalize('NFKD').replace(/[^a-z ]/g, '').replace(/\b(jr|sr|ii|iii|iv)\b/g, '').replace(/\s+/g, ' ').trim();
const NFLPOS = { QB: ['QB'], RB: ['RB', 'FB'], WR: ['WR'], TE: ['TE'], EDGE: ['DE', 'OLB', 'EDGE', 'DL'], DL: ['DT', 'DE', 'DL', 'NT'], LB: ['LB', 'ILB', 'OLB', 'MLB'] };
const nfl = { byPosition: {} }, pooled = { z: [], v: [], av: [] };
for (const g of Object.keys(NFLPOS)) {
  const last = {}; for (const r of rows.filter(r => r.pos === g)) if (!last[r.id] || r.season > last[r.id].season) last[r.id] = r;
  const P = [];
  for (const r of Object.values(last)) {
    if (r.season > 2022) continue;
    const D = r.season + 1, cand = picks.filter(p => nm(p.pfr_player_name) === nm(r.name) && NFLPOS[g].includes(p.position));
    const pk = cand.find(p => +p.season === D); if (!pk && cand.some(p => +p.season > D)) continue;
    P.push({ z: r.z, v: r.v, av: pk ? (+pk.w_av || 0) / (2025 - D + 1) : 0 });
  }
  nfl.byPosition[g] = { n: P.length, statPlus: r3(corr(P.map(p => p.z), P.map(p => p.av))), seasonAv: r3(corr(P.map(p => p.v), P.map(p => p.av))) };
  for (const p of P) { pooled.z.push(p.z); pooled.v.push(p.v); pooled.av.push(p.av); }
}
nfl.pooled = { statPlus: r3(corr(pooled.z, pooled.av)), seasonAv: r3(corr(pooled.v, pooled.av)) };

// ---- FV test: does season AV add to FV's production term for NFL AV? -----------------------------------------
// FV's production term as cfb_statplus_backtest.mjs measures it: each season's score as a z on that season's FBS
// curve, blended 5/4/3 by snaps (games x snaps a game before 2026) and regressed with K 3000 weighted snaps. The
// final season's season AV (share x position weight x (starter-pool z + 1)) is added: partial r holding the
// production term fixed, its t, and the leave-one-final-season-out R^2 gain. Same bar as FV_BADGE: t >= 2 and an
// out-of-sample gain.
const SPG = { QB: 65, RB: 30, WR: 40, TE: 40, EDGE: 50, DL: 45, LB: 55 }, FV_K = 3000, FV_SW = [5, 4, 3];
const partialR = (x, z, y) => { const a = corr(x, y), b = corr(x, z), c = corr(z, y); return (a - b * c) / Math.sqrt((1 - b * b) * (1 - c * c)); };
const zsd = xs => { const m = mean(xs), s = sd(xs); return xs.map(x => (x - m) / s); };
const fvTest = { byPosition: {} }, poolFv = [];
for (const g of Object.keys(NFLPOS)) {
  const cz = {}; for (const r of rows.filter(r => r.pos === g)) (cz[r.season] ||= []).push(r.score);
  for (const k of Object.keys(cz)) cz[k] = [mean(cz[k]), sd(cz[k])];
  const by = {}; for (const r of rows.filter(r => r.pos === g)) (by[r.id] ||= {})[r.season] = r;
  const P = [];
  for (const sea of Object.values(by)) {
    const last = Math.max(...Object.keys(sea).map(Number)); if (last > 2022) continue;
    const r = sea[last], D = last + 1, cand = picks.filter(p => nm(p.pfr_player_name) === nm(r.name) && NFLPOS[g].includes(p.position));
    const pk = cand.find(p => +p.season === D); if (!pk && cand.some(p => +p.season > D)) continue;
    let num = 0, den = 0;
    FV_SW.forEach((w, k) => { const x = sea[last - k]; if (x) { const v = x.sh * TG[x.season][x.tid] * SPG[g]; num += w * v * (x.score - cz[x.season][0]) / cz[x.season][1]; den += w * v; } });
    P.push({ last, prod: num / (den + FV_K), sav: r.v, av: pk ? (+pk.w_av || 0) / (2025 - D + 1) : 0 });
  }
  const pr = partialR(P.map(p => p.sav), P.map(p => p.prod), P.map(p => p.av)), t = pr * Math.sqrt((P.length - 3) / (1 - pr * pr));
  let sse0 = 0, sse1 = 0, sst = 0;
  for (const s of [...new Set(P.map(p => p.last))]) {
    const tr = P.filter(p => p.last !== s), te = P.filter(p => p.last === s), my = mean(tr.map(p => p.av));
    const b0 = ols(tr.map(p => [p.prod]), tr.map(p => p.av)), b1 = ols(tr.map(p => [p.prod, p.sav]), tr.map(p => p.av));
    for (const p of te) { sse0 += (p.av - predict(b0, [p.prod])) ** 2; sse1 += (p.av - predict(b1, [p.prod, p.sav])) ** 2; sst += (p.av - my) ** 2; }
  }
  fvTest.byPosition[g] = { n: P.length, partial: r3(pr), t: Math.round(t * 100) / 100, oosGain: r3(100 * (sse0 - sse1) / sst), pass: t >= 2 && sse1 < sse0 };
  const zp = zsd(P.map(p => p.prod)), zv = zsd(P.map(p => p.sav)), za = zsd(P.map(p => p.av));
  P.forEach((p, i) => poolFv.push({ last: p.last, prod: zp[i], sav: zv[i], av: za[i] }));
}
{
  const pr = partialR(poolFv.map(p => p.sav), poolFv.map(p => p.prod), poolFv.map(p => p.av)), t = pr * Math.sqrt((poolFv.length - 3) / (1 - pr * pr));
  let sse0 = 0, sse1 = 0, sst = 0;
  for (const s of [...new Set(poolFv.map(p => p.last))]) {
    const tr = poolFv.filter(p => p.last !== s), te = poolFv.filter(p => p.last === s), my = mean(tr.map(p => p.av));
    const b0 = ols(tr.map(p => [p.prod]), tr.map(p => p.av)), b1 = ols(tr.map(p => [p.prod, p.sav]), tr.map(p => p.av));
    for (const p of te) { sse0 += (p.av - predict(b0, [p.prod])) ** 2; sse1 += (p.av - predict(b1, [p.prod, p.sav])) ** 2; sst += (p.av - my) ** 2; }
  }
  fvTest.pooled = { n: poolFv.length, partial: r3(pr), t: Math.round(t * 100) / 100, oosGain: r3(100 * (sse0 - sse1) / sst), pass: t >= 2 && sse1 < sse0 };
}

// ---- WAR: wins per point -------------------------------------------------------------------------------------
// college: FBS team seasons (8+ games), win% on scoring margin a game (all games, ties half); NFL: nflverse
// regular-season team seasons 2010-24, wins on season point margin
const war = {};
{
  const X = [], Y = [];
  for (const y of YEARS.filter(y => y < TEST)) {
    const G = (await games(y)).filter(g => g.done), cnt = {}, T = {};
    for (const g of G) for (const t of [g.home, g.away]) cnt[t] = (cnt[t] || 0) + 1;
    for (const g of G) for (const [t, pf, pa] of [[g.home, g.hs, g.as], [g.away, g.as, g.hs]]) {
      if (cnt[t] < 8) continue; const x = (T[t] ||= { g: 0, w: 0, m: 0 }); x.g++; x.w += pf > pa ? 1 : pf === pa ? 0.5 : 0; x.m += pf - pa;
    }
    for (const x of Object.values(T)) { X.push([x.m / x.g]); Y.push(x.w / x.g); }
  }
  const c = ols(X, Y); war.college = { teamSeasons: Y.length, winPerPt: Math.round(c[1] * 10000) / 10000, r: r3(corr(X.map(x => x[0]), Y)) };
  const nf = path.join(CACHE, 'nfl_games.csv');
  if (!fs.existsSync(nf)) fs.writeFileSync(nf, await (await fetch('https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv')).text());
  const [hd, ...ls] = fs.readFileSync(nf, 'utf8').trim().split('\n'), HD = hd.split(','), ix = k => HD.indexOf(k), S = {};
  for (const l of ls) {
    const v = l.split(','), season = +v[ix('season')]; if (v[ix('game_type')] !== 'REG' || season < 2010 || season > 2024 || v[ix('result')] === '' || v[ix('result')] === 'NA') continue;
    const hs = +v[ix('home_score')], as = +v[ix('away_score')];
    for (const [t, pf, pa] of [[v[ix('home_team')], hs, as], [v[ix('away_team')], as, hs]]) { const x = (S[season + t] ||= { w: 0, m: 0, pf: 0 }); x.w += pf > pa ? 1 : pf === pa ? 0.5 : 0; x.m += pf - pa; x.pf += pf; }
  }
  const ts = Object.values(S), cn = ols(ts.map(x => [x.m]), ts.map(x => x.w));
  war.nfl = { teamSeasons: ts.length, ptsPerWin: Math.round(10 / cn[1]) / 10, r: r3(corr(ts.map(x => x.m), ts.map(x => x.w))), ptsPerTeamSeason: Math.round(mean(ts.map(x => x.pf))) };
}

const out = {
  asof: new Date().toISOString().slice(0, 10),
  constants: { w: SAV_W, repl: SAV_REPL, q: SAV_Q, ptsPerAv: SAV_PTS },
  fit: { seasons: FIT, teams: Yf.length, w: Object.fromEntries(POS.map((g, i) => [g, Math.round(fit.w[i] * 100) / 100])), grid },
  test2026: { teams: tids.length, r2: { talentFv: r3(r2c([tal26])), statPlus: r3(r2c([stat26])), seasonAv: r3(r2c([sav26])), seasonAvPlusTalent: r3(r2c([sav26, tal26])),
    prior: r3(r2c([pri26])), priorPlusSeasonAv: r3(r2c([pri26, sav26])) }, r: { talentFv: r3(corr(tal26, Y26)), seasonAv: r3(corr(sav26, Y26)) } },
  inputs2026: inputs, forward, nfl, fvTest, war,
};
fs.writeFileSync(OUT, JSON.stringify(out, null, 1) + '\n');
console.log(JSON.stringify(out, null, 1));
