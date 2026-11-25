// CFB player-season rows for the team-adjustment harness (cfb.py): PFN impact scores (FBS, z on the starter pool, as
// scripts/cfb_av_backtest.mjs), share = games played / team games, ESPN FBS results -> SRS (the same ridge), 2019-26.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { fetchGames } from '../../../cfb_teams.mjs';
import { SAV_W, CWAR_V } from '../../../cfb_av.mjs';
const HERE = path.dirname(fileURLToPath(import.meta.url)), ROOT = path.join(HERE, '..', '..', '..', '..');
const CACHE = path.join(ROOT, 'scripts', '.cache', 'av'); fs.mkdirSync(CACHE, { recursive: true });
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36';
const PFN = { QB: 'quarterback', RB: 'running-back', WR: 'wide-receiver', TE: 'tight-end', OL: 'offensive-line', EDGE: 'edge', DL: 'defensive-tackle', LB: 'linebacker', CB: 'cornerback', S: 'safety' };
const POS = Object.keys(PFN), STARTERS = { QB: 1, RB: 1, WR: 3, TE: 1, OL: 5, EDGE: 2, DL: 2, LB: 2, CB: 3, S: 2 };
const YEARS = [2019, 2020, 2021, 2022, 2023, 2024, 2025];   // lockbox: no 2026
const mean = xs => xs.reduce((a, b) => a + b, 0) / Math.max(1, xs.length);
const sd = xs => { const m = mean(xs); return Math.sqrt(mean(xs.map(x => (x - m) ** 2))) || 1; };
function solve(A, b) { const n = b.length, M = A.map((r, i) => [...r, b[i]]);
  for (let c = 0; c < n; c++) { let p = c; for (let r = c + 1; r < n; r++) if (Math.abs(M[r][c]) > Math.abs(M[p][c])) p = r; [M[c], M[p]] = [M[p], M[c]];
    for (let r = c + 1; r < n; r++) { const f = M[r][c] / M[c][c]; for (let k = c; k <= n; k++) M[r][k] -= f * M[c][k]; } }
  const x = Array(n).fill(0); for (let r = n - 1; r >= 0; r--) { let s = M[r][n]; for (let k = r + 1; k < n; k++) s -= M[r][k] * x[k]; x[r] = s / M[r][r]; } return x; }
function jsonEnd(s, i) { let d = 0, q = false; for (let k = i; k < s.length; k++) { const c = s[k]; if (q) { if (c === '\\') k++; else if (c === '"') q = false; continue; } if (c === '"') q = true; else if (c === '{' || c === '[') d++; else if (c === '}' || c === ']') { d--; if (!d) return k + 1; } } return s.length; }
async function pfn(g) {
  const f = path.join(CACHE, `pfn_${g}.json`); if (fs.existsSync(f)) return JSON.parse(fs.readFileSync(f));
  const html = await (await fetch(`https://www.profootballnetwork.com/cfb-hq/impact-rankings/${PFN[g]}`, { headers: { 'user-agent': UA } })).text();
  const s = [...html.matchAll(/self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)/g)].map(m => JSON.parse(m[1])).find(c => c.includes('"packed":'));
  const i = s.indexOf('"packed":') + 9, packed = JSON.parse(s.slice(i, jsonEnd(s, i)));
  const rows = packed.rows.map(r => Object.fromEntries(packed.cols.map((c, k) => [c, r[k]])));
  fs.writeFileSync(f, JSON.stringify(rows)); return rows;
}
async function games(y) { const f = path.join(CACHE, `games${y}.json`); if (fs.existsSync(f)) return JSON.parse(fs.readFileSync(f)); const g = await fetchGames(y); fs.writeFileSync(f, JSON.stringify(g)); return g; }
const norm = s => (s || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/&/g, 'and').replace(/[^a-z0-9 ]/g, '').replace(/\s+/g, ' ').trim();
const ALIAS = { 'miami fl': 'miami', mississippi: 'ole miss', usf: 'south florida', 'north carolina state': 'nc state', 'appalachian state': 'app state', connecticut: 'uconn', louisianamonroe: 'ul monroe', 'sam houston state': 'sam houston' };
const SRS = {}, TG = {}, nameId = {}, GAMES = {};
for (const y of YEARS) {
  const G = (await games(y)).filter(g => g.done), cnt = {};
  GAMES[y] = G.map(g => ({ id: g.id, w: g.week, d: g.date, h: g.home, a: g.away, hs: g.hs, as: g.as, n: !!g.neutral }));
  for (const g of G) { for (const t of [g.home, g.away]) cnt[t] = (cnt[t] || 0) + 1; nameId[norm(g.homeName)] = g.home; nameId[norm(g.awayName)] = g.away; }
  const fbs = Object.keys(cnt).filter(t => cnt[t] >= (y === 2020 ? 3 : 5)), ix = Object.fromEntries(fbs.map((t, i) => [t, i])), n = fbs.length;
  const A = Array.from({ length: n + 1 }, () => Array(n + 1).fill(0)), b = Array(n + 1).fill(0);
  for (const g of G) { if (ix[g.home] == null || ix[g.away] == null) continue;
    const z = Array(n + 1).fill(0); z[ix[g.home]] = 1; z[ix[g.away]] = -1; z[n] = g.neutral ? 0 : 1;
    const m = Math.max(-35, Math.min(35, g.hs - g.as)), nz = [ix[g.home], ix[g.away], n];
    for (const a of nz) { b[a] += z[a] * m; for (const c of nz) A[a][c] += z[a] * z[c]; } }
  for (let i = 0; i < n; i++) A[i][i] += 2;
  const x = solve(A, b), m = mean(x.slice(0, n));
  SRS[y] = Object.fromEntries(fbs.map((t, i) => [t, x[i] - m])); TG[y] = Object.fromEntries(fbs.map(t => [t, cnt[t]]));
  console.error(y, n, 'teams');
}
const rows = [];
for (const g of POS) for (const r of await pfn(g)) {
  if (r.division !== 'FBS') continue;
  const k = norm(r.team), tid = nameId[ALIAS[k] || k]; if (!tid || SRS[r.season]?.[tid] == null) continue;
  rows.push({ id: String(r.id), name: r.name || r.player, pos: g, season: r.season, tid, score: r.score, gp: +r.gp || 0, raw: r, sh: Math.min(1, (+r.gp || 0) / TG[r.season][tid]) });
}
for (const y of YEARS) for (const g of POS) {
  const list = rows.filter(r => r.season === y && r.pos === g); if (!list.length) continue;
  const pool = list.map(r => r.score).sort((a, b) => b - a).slice(0, STARTERS[g] * Object.keys(SRS[y]).length), m = mean(pool), s = sd(pool);
  for (const r of list) r.z = (r.score - m) / s;
}
fs.writeFileSync(path.join(CACHE, 'metric_audit_cfb.json'), JSON.stringify({ SRS, TG, SAV_W, CWAR_V, rows, GAMES }));
console.error('rows', rows.length, Object.fromEntries(YEARS.map(y => [y, rows.filter(r => r.season === y).length])));
