// Backtest for college WAR by position (scripts/cfb_av.mjs CWAR_V, CWAR_QB_OWN). Run by hand:
// node scripts/cfb_war_pos_backtest.mjs -> data/cfb_war_pos_backtest.json
// Data: PFN impact rankings and ESPN results (as scripts/cfb_av_backtest.mjs), ESPN box scores of every FBS-vs-FBS game
// 2019-25 (who recorded a stat; cached slim in scripts/.cache/av/box<season>.json), this season's board.
//   missed    regular-season game margin (capped 35) on team-season ratings (home minus away, ridge 2) + home field +
//             each side's absent regulars (the top STARTERS by games at each position, half a season or more): per
//             position the count absent and the count x his z. A QB is absent when he threw under 10% of the team's
//             passes (he didn't play, as known before kickoff); anyone else when he has no stat line in that game and
//             the one before or after (a single quiet game is usually a game played without a stat). Bowls are left
//             out: opt-outs leave many starters home at once, and box scores can't see most of them, so the QB's absence
//             took their cost (5.24 with bowls and partial games as fractions; 4.68 without bowls). Counting a QB pulled
//             mid-game as partly absent tied his absence to the score (benched when losing, rested in blowouts), which
//             turned a better QB's absence into a cheaper one (-.92 a SD). Linemen never show in a box score, and most
//             defensive box scores before 2024 carry no tackles, so those games count nobody absent. drop@z0 = what an
//             average regular's absence costs in points; slope = how much more a better one's costs
//   zt        team margin on each position's summed share x z and its filled share (a graded player's games
//             against an ungraded fill-in's), 2019-25: the share coefficient over the z one is the implied line
//   forward   the QB credit split: each player-season's value with the QB's slope at beta and the rest of SAV_W.QB x
//             his z x share spread over his graded offensive teammates by share; returning players' summed value at
//             their new team against this season's margin, 2020-25 (R^2, alone and with last season's SRS)
//   subBlend  each sub-position's line (CWAR_SUB_V): precision-weighted blend of the missed-game drop, the NFL's lineup
//             share (data/nfl_war_pos.json) scaled to the college lineup (SD 40% of the mean of the two priors), and 2 SD x
//             SAV_W (SD 50%); QB from the first two; non-QB rescaled so the lineup total stays where it was
//   board     this season's leaderboard: top 100 by WAR and by WAA, by position, at the 2 SD line and now
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { fetchGames } from './cfb_teams.mjs';
import { seasonAv, SAV_W, CWAR_V, CWAR_SUB_V, CWAR_QB_OWN, CWAR_PER_PT } from './cfb_av.mjs';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const CACHE = path.join(ROOT, 'scripts', '.cache', 'av');
const OUT = path.join(ROOT, 'data', 'cfb_war_pos_backtest.json');
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
for (const y of YEARS) F[y] = feats(rows.filter(r => r.season === y), p => p.sh, p => p.z);
const SEAS = [2019, 2020, 2021, 2022, 2023, 2024, 2025];
const r2d = x => Math.round(x * 100) / 100;

// ---- box scores ----------------------------------------------------------------------------------------------
async function boxOne(id) {
  for (let k = 0; k < 4; k++) {
    try {
      const r = await fetch(`https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary?event=${id}`, { headers: { 'user-agent': UA } });
      if (!r.ok) throw new Error(r.status);
      const d = await r.json(), out = {};
      for (const t of d.boxscore?.players || []) {
        const o = out[t.team.id] = {};
        for (const s of t.statistics) if (['passing', 'rushing', 'receiving', 'defensive'].includes(s.name))
          o[s.name] = s.athletes.map(a => [a.athlete.id, a.athlete.displayName, s.name === 'passing' ? +String(a.stats[0]).split('/')[1] || 0 : +a.stats[0] || 0]);
      }
      return out;
    } catch { await new Promise(r => setTimeout(r, 1000 * (k + 1))); }
  }
  return null;
}
async function boxes(y) {
  const f = path.join(CACHE, `box${y}.json`), have = fs.existsSync(f) ? JSON.parse(fs.readFileSync(f)) : {};
  const todo = (await games(y)).filter(g => g.done && SRS[y][g.home] != null && SRS[y][g.away] != null && !have[g.id]).map(g => g.id);
  let i = 0;
  await Promise.all(Array.from({ length: 8 }, async () => { while (i < todo.length) { const id = todo[i++], b = await boxOne(id); if (b) have[id] = b; } }));
  if (todo.length) fs.writeFileSync(f, JSON.stringify(have));
  return have;
}

// ---- missed games --------------------------------------------------------------------------------------------
const nk = s => norm(s).replace(/\b(jr|sr|ii|iii|iv|v)\b/g, '').replace(/\s+/g, ' ').trim();
const DEF = new Set(['EDGE', 'DL', 'LB', 'CB', 'S']);
async function missed(seasons) {
  const eqs = [], fe = {}, EFF = POS.flatMap(g => [g + ':n', g + ':z']), ne = EFF.length, seen = {};
  let nfe = 0; const feOf = k => fe[k] ??= nfe++;
  for (const g of POS) seen[g] = { abs: 0, games: 0 };
  for (const y of seasons) {
    const box = await boxes(y), G = (await games(y)).filter(g => g.done && g.week !== 17 && box[g.id] && SRS[y][g.home] != null && SRS[y][g.away] != null);
    const reg = {};
    for (const r of rows.filter(r => r.season === y && r.z != null)) (reg[r.tid] ||= []).push(r);
    for (const t of Object.keys(reg)) reg[t] = POS.flatMap(g => reg[t].filter(r => r.pos === g).sort((a, b) => b.sh - a.sh).slice(0, STARTERS[g]).filter(r => r.sh >= 0.5));
    const pres = {}, order = {};
    for (const g of G) for (const t of [g.home, g.away]) {
      const b = box[g.id][t]; if (!b) continue;
      const on = new Set(), pa = {}; let patt = 0;
      for (const [k, list] of Object.entries(b)) for (const [, nm, v] of list) { on.add(nk(nm)); if (k === 'passing') { pa[nk(nm)] = v; patt += v; } }
      const hasDef = (b.defensive || []).length >= 8;
      (order[t] ||= []).push(g.id);
      for (const r of reg[t] || []) (pres[t + '|' + r.id + r.pos] ||= {})[g.id] = r.pos === 'QB' ? Math.min(1, (pa[nk(r.name)] || 0) / Math.max(1, patt))
        : r.pos === 'OL' || (DEF.has(r.pos) && !hasDef) ? null : on.has(nk(r.name)) ? 1 : 0;
    }
    const absent = (t, r, gid) => {
      const P = pres[t + '|' + r.id + r.pos] || {}, v = P[gid]; if (v == null) return null;
      if (r.pos === 'QB') return v < 0.1 ? 1 : 0;
      if (v) return 0;
      const o = order[t], i = o.indexOf(gid);
      return [P[o[i - 1]], P[o[i + 1]]].some(x => x === 0) ? 1 : 0;
    };
    for (const g of G) {
      if (!box[g.id][g.home] || !box[g.id][g.away]) continue;
      const x = new Array(ne).fill(0);
      for (const [t, sgn] of [[g.home, 1], [g.away, -1]]) for (const r of reg[t] || []) {
        const a = absent(t, r, g.id); if (a == null) continue;
        const i = POS.indexOf(r.pos); x[2 * i] += sgn * a; x[2 * i + 1] += sgn * a * r.z; seen[r.pos].abs += a; seen[r.pos].games++;
      }
      eqs.push({ h: feOf(y + '|' + g.home), a: feOf(y + '|' + g.away), hfa: g.neutral ? 0 : 1, x, m: Math.max(-35, Math.min(35, g.hs - g.as)) });
    }
  }
  const np = nfe + 1 + ne, A = Array.from({ length: np }, () => new Float64Array(np)), bb = new Float64Array(np);
  for (const e of eqs) {
    const idx = [e.h, e.a, nfe, ...EFF.map((_, j) => nfe + 1 + j)], val = [1, -1, e.hfa, ...e.x];
    for (let p = 0; p < idx.length; p++) { if (!val[p]) continue; bb[idx[p]] += val[p] * e.m; for (let q = 0; q < idx.length; q++) if (val[q]) A[idx[p]][idx[q]] += val[p] * val[q]; }
  }
  for (let i = 0; i < nfe; i++) A[i][i] += 2;
  for (let j = 0; j < ne; j++) A[nfe + 1 + j][nfe + 1 + j] += 1;
  const M = A.map(r => Array.from(r)), sol = solve(M.map(r => [...r]), Array.from(bb));
  let sse = 0;
  for (const e of eqs) sse += (e.m - (sol[e.h] - sol[e.a] + sol[nfe] * e.hfa + e.x.reduce((a, v, j) => a + v * sol[nfe + 1 + j], 0))) ** 2;
  const s2 = sse / (eqs.length - np), se = j => { const u = Array(np).fill(0); u[nfe + 1 + j] = 1; return Math.sqrt(s2 * solve(M.map(r => [...r]), u)[nfe + 1 + j]); };
  const by = {};
  POS.forEach((g, i) => {
    if (!seen[g].games) return;
    by[g] = { regularGames: seen[g].games, absentRate: r3(seen[g].abs / seen[g].games), dropAtZ0: r2d(-sol[nfe + 1 + 2 * i]), se: r2d(se(2 * i)),
      slopePerZ: r2d(-sol[nfe + 1 + 2 * i + 1]), slopeSe: r2d(se(2 * i + 1)), line2sd: r2d(2 * SAV_W[g]) };
  });
  return { seasons: [seasons[0], seasons.at(-1)], games: eqs.length, homeField: r2d(sol[nfe]), rmse: r2d(Math.sqrt(sse / eqs.length)), byPosition: by };
}
const missedAll = await missed(SEAS), missedEarly = await missed(SEAS.filter(y => y <= 2022)), missedLate = await missed(SEAS.filter(y => y >= 2023));

// ---- subBlend: the lines by sub-position ----------------------------------------------------------------------
const SUBS = { QB: ['QB', 1], RB: ['RB', 1], WR: ['WR', 2], SWR: ['WR', 1], TE: ['TE', 1], OT: ['OL', 2], IOL: ['OL', 3], EDGE: ['EDGE', 2], DL: ['DL', 2], LB: ['LB', 2], CB: ['CB', 2], NCB: ['CB', 1], S: ['S', 2] };
const nflShare = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'nfl_war_pos.json'), 'utf8')).share;
// the lineup total is the replacement team's: 2 SD (CWAR_REPL) x SAV_W at every spot, the QB's included
const gradeLine = k => 2 * SAV_W[SUBS[k][0]];
const lineupTotal = Object.entries(SUBS).reduce((a, [k, [, n]]) => a + n * gradeLine(k), 0);
const subBlend = {};
for (const [k, [g, n]] of Object.entries(SUBS)) {
  const nfl = nflShare[k === 'DL' ? 'DT' : k] * lineupTotal / n, grade = gradeLine(k), m = (nfl + grade) / 2, mis = missedAll.byPosition[g];
  const src = [[nfl, 0.4 * m]];
  if (k !== 'QB') src.push([grade, 0.5 * m]);
  if (mis && mis.dropAtZ0 != null && g !== 'OL') src.push([mis.dropAtZ0, mis.se]);
  const w = src.map(([, se]) => 1 / se ** 2), v = Math.max(0, src.reduce((a, [x], i) => a + w[i] * x, 0) / w.reduce((a, b) => a + b, 0));
  subBlend[k] = { nfl: r2d(nfl), grade: r2d(grade), missed: mis && g !== 'OL' ? mis.dropAtZ0 : null, raw: v, slots: n };
}
{ const rest = lineupTotal - subBlend.QB.raw, z = rest / Object.entries(subBlend).filter(([k]) => k !== 'QB').reduce((a, [, b]) => a + b.slots * b.raw, 0);
  for (const [k, b] of Object.entries(subBlend)) { b.value = r2d(k === 'QB' ? b.raw : b.raw * z); delete b.raw; } }
const offShare = r3(Object.entries(subBlend).filter(([k]) => ['QB', 'RB', 'WR', 'SWR', 'TE', 'OT', 'IOL'].includes(k)).reduce((a, [, b]) => a + b.slots * b.value, 0) / lineupTotal);

// ---- zt: the filled-share term ------------------------------------------------------------------------------
const zt = {};
{
  const P7 = ['QB', 'RB', 'WR', 'TE', 'EDGE', 'DL', 'LB'], X = [], Y = [];
  for (const y of SEAS) for (const [t, s] of Object.entries(SRS[y])) { const f = F[y][t]; if (!f) continue; X.push(P7.flatMap(g => { const i = POS.indexOf(g); return [f[2 * i + 1], f[2 * i]]; })); Y.push(s); }
  const co = ols(X, Y, 1);
  P7.forEach((g, i) => { zt[g] = { perZ: r2d(co[1 + 2 * i]), perShare: r2d(co[2 + 2 * i]), impliedLine: r2d(-co[2 + 2 * i] / co[1 + 2 * i]) }; });
}

// ---- forward: the QB credit split ----------------------------------------------------------------------------
const OFFP = ['RB', 'WR', 'TE', 'OL'];
function values(beta) {
  const v = new Map(), byTeam = {};
  for (const r of rows) (byTeam[r.season + '|' + r.tid] ||= []).push(r);
  for (const ps of Object.values(byTeam)) {
    let extra = 0;
    for (const r of ps) {
      if (r.pos === 'QB') { v.set(r, r.sh * (2 * SAV_W.QB + beta * r.z)); extra += r.sh * (SAV_W.QB - beta) * r.z; }
      else v.set(r, r.sh * SAV_W[r.pos] * (r.z + 2));
    }
    const mates = ps.filter(r => OFFP.includes(r.pos)), tot = mates.reduce((a, r) => a + r.sh, 0);
    for (const r of mates) v.set(r, v.get(r) + extra * r.sh / Math.max(tot, 1));
  }
  return v;
}
const forward = {};
for (const beta of [SAV_W.QB, 2.25, 1.75, 1.25, 0.75, 0.25]) {
  const v = values(beta), alone = [], both = [];
  for (const y of SEAS.slice(1)) {
    const prev = new Map(rows.filter(r => r.season === y - 1).map(r => [r.id + '|' + r.pos, r])), ret = {};
    for (const r of rows.filter(r => r.season === y)) { const p = prev.get(r.id + '|' + r.pos); if (p) ret[r.tid] = (ret[r.tid] || 0) + v.get(p); }
    const ts = Object.keys(SRS[y]).filter(t => SRS[y - 1][t] != null), Y = ts.map(t => SRS[y][t]), L = ts.map(t => SRS[y - 1][t]), R = ts.map(t => ret[t] || 0);
    const fit = cols => r2of(Y, (co => ts.map((t, i) => predict(co, cols.map(c => c[i]))))(ols(ts.map((t, i) => cols.map(c => c[i])), Y)));
    alone.push(fit([R])); both.push(fit([L, R]));
  }
  forward[beta] = { returningR2: r3(mean(alone)), withLastSrsR2: r3(mean(both)) };
}

// ---- this season's board -------------------------------------------------------------------------------------
const all = JSON.parse(fs.readFileSync(path.join(ROOT, 'static', 'data', 'cfb-all.json'), 'utf8'));
const board = all.rows.map(r => Object.fromEntries(all.cols.map((c, i) => [c, r[i]]))).filter(p => p.div === 'FBS')
  .map(p => ({ ...p, tid: /\/(\d+)\.png/.exec(p.logo || '')?.[1] || null }));
const live = board.filter(p => SAV_W[p.pos] != null && p.pfn != null && p.snapShare != null);
seasonAv(board);
const old = new Map(live.map(p => [p, Math.max(0, Math.min(1, p.snapShare) * SAV_W[p.pos] * (p.savQ + 2)) * CWAR_PER_PT]));
const mix = f => { const c = {}; for (const p of [...live].sort((a, b) => f(b) - f(a)).slice(0, 100)) c[p.pos] = (c[p.pos] || 0) + 1; return c; };
const top = (f, n = 10) => [...live].sort((a, b) => f(b) - f(a)).slice(0, n).map(p => [p.name, p.pos, r2d(f(p))]);
const boardOut = { top100: { line2sd: mix(p => old.get(p)), war: mix(p => p.war), waa: mix(p => p.waa) },
  topWar: top(p => p.war), topWaa: top(p => p.waa, 25),
  bestByPos: Object.fromEntries(POS.map(g => { const b = live.filter(p => p.pos === g).sort((a, b) => b.war - a.war)[0]; return [g, b ? [b.name, b.war, r2d(old.get(b))] : null]; })) };

const out = { asof: new Date().toISOString().slice(0, 10), constants: { cwarV: CWAR_V, cwarSubV: CWAR_SUB_V, qbOwnPerSd: CWAR_QB_OWN, qbPerSd: SAV_W.QB },
  subBlend, lineupTotal: r2d(lineupTotal), offenseShare: offShare, used: CWAR_SUB_V,
  missed: missedAll, missedSplit: { early: missedEarly.byPosition.QB, late: missedLate.byPosition.QB }, zt, forward, board: boardOut };
fs.writeFileSync(OUT, JSON.stringify(out, null, 1) + '\n');
console.log(JSON.stringify(out, null, 1));
