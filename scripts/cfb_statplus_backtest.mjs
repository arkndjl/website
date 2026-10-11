// Backtest for Stat+ (PFN's all-in-one score at the position, the board's Stat+ column) as the FV production
// driver: which blend of seasons and how much regression predict NFL careers best, and how much the score
// predicts at each position. Run by hand: node scripts/cfb_statplus_backtest.mjs -> data/cfb_statplus_backtest.json
// Data: PFN impact rankings (FBS, 2019 on for QB, RB, WR, TE, EDGE, DT, LB; 2024 on for OL, CB, S, so those can't
// be tested yet) and nflverse draft picks. Universe: each player's last PFN season, 2019-22 (drafts 2020-23);
// outcome weighted career AV a season through 2025, undrafted = 0; players who appear in a later draft dropped.
// The production term is FV's: each season's score as a z on that season's FBS curve, blended by season weight x
// snaps and regressed with K weighted snaps, z = sum(w v z) / (sum(w v) + K). Stat+ (100 x score / position mean)
// is a linear rescale of the score within a season, so it ranks players exactly as the z does.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const CACHE = path.join(ROOT, 'scripts', '.cache', 'statplus');
const OUT = path.join(ROOT, 'data', 'cfb_statplus_backtest.json');
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36';
fs.mkdirSync(CACHE, { recursive: true });
const POS = { QB: 'quarterback', RB: 'running-back', WR: 'wide-receiver', TE: 'tight-end', EDGE: 'edge', DL: 'defensive-tackle', LB: 'linebacker' };
const SPG = { QB: 65, RB: 30, WR: 40, TE: 40, EDGE: 50, DL: 45, LB: 55 };     // snaps a game, for seasons with games only
const NFLPOS = { QB: ['QB'], RB: ['RB', 'FB'], WR: ['WR'], TE: ['TE'], EDGE: ['DE', 'OLB', 'EDGE', 'DL'], DL: ['DT', 'DE', 'DL', 'NT'], LB: ['LB', 'ILB', 'OLB', 'MLB'] };
const NFL_THROUGH = 2025;

function jsonEnd(s, i) { let d = 0, q = false; for (let k = i; k < s.length; k++) { const c = s[k]; if (q) { if (c === '\\') k++; else if (c === '"') q = false; continue; } if (c === '"') q = true; else if (c === '{' || c === '[') d++; else if (c === '}' || c === ']') { d--; if (!d) return k + 1; } } }
async function pfn(g) {
  const f = path.join(CACHE, `pfn_${g}.json`); if (fs.existsSync(f)) return JSON.parse(fs.readFileSync(f));
  const html = await (await fetch(`https://www.profootballnetwork.com/cfb-hq/impact-rankings/${POS[g]}`, { headers: { 'user-agent': UA } })).text();
  const s = [...html.matchAll(/self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)/g)].map(m => JSON.parse(m[1])).find(c => c.includes('"packed":'));
  const i = s.indexOf('"packed":') + 9, packed = JSON.parse(s.slice(i, jsonEnd(s, i)));
  const rows = packed.rows.map(r => Object.fromEntries(packed.cols.map((c, k) => [c, r[k]])));
  fs.writeFileSync(f, JSON.stringify(rows)); return rows;
}
const picksFile = path.join(CACHE, 'draft_picks.csv');
if (!fs.existsSync(picksFile)) fs.writeFileSync(picksFile, await (await fetch('https://github.com/nflverse/nflverse-data/releases/download/draft_picks/draft_picks.csv')).text());
const [h, ...pl] = fs.readFileSync(picksFile, 'utf8').trim().split('\n'), H = h.split(',');
const picks = pl.map(l => { const v = l.split(','); return Object.fromEntries(H.map((k, i) => [k, v[i]])); }).filter(r => +r.season >= 2020 && +r.season <= 2025);
const nm = s => (s || '').toLowerCase().normalize('NFKD').replace(/[^a-z ]/g, '').replace(/\b(jr|sr|ii|iii|iv)\b/g, '').replace(/\s+/g, ' ').trim();
const col = s => nm(s).replace(/\bstate\b/, 'st').replace(/\buniversity\b|\bof\b/g, '').trim();
const corr = (xs, ys) => { const n = xs.length, mx = xs.reduce((a, b) => a + b) / n, my = ys.reduce((a, b) => a + b) / n; let a = 0, b = 0, c = 0; xs.forEach((x, i) => { a += (x - mx) * (ys[i] - my); b += (x - mx) ** 2; c += (ys[i] - my) ** 2; }); return a / Math.sqrt(b * c); };
const r3 = x => Math.round(x * 1000) / 1000;

const data = {};
for (const g of Object.keys(POS)) {
  const rows = (await pfn(g)).filter(r => r.division === 'FBS'), cz = {};
  for (const r of rows) (cz[r.season] ||= []).push(r.score);
  for (const [s, xs] of Object.entries(cz)) { const m = xs.reduce((a, b) => a + b) / xs.length; cz[s] = [m, Math.sqrt(xs.reduce((a, b) => a + (b - m) ** 2, 0) / xs.length)]; }
  const byId = {};
  for (const r of rows) { r.z = (r.score - cz[r.season][0]) / cz[r.season][1]; r.v = (typeof r.snapsQ === 'number' ? r.snapsQ : null) ?? ((r.gp ?? r.gamesQ ?? 0) * SPG[g]); (byId[r.id] ||= {})[r.season] = r; }
  data[g] = [];
  for (const by of Object.values(byId)) {
    const last = Math.max(...Object.keys(by).map(Number)); if (last > 2022) continue;
    const r = by[last], D = last + 1, cand = picks.filter(p => nm(p.pfr_player_name) === nm(r.name) && NFLPOS[g].includes(p.position));
    const pk = cand.find(p => +p.season === D && col(p.college).split(' ')[0] === col(r.team).split(' ')[0]) || cand.find(p => +p.season === D);
    if (!pk && cand.some(p => +p.season > D)) continue;
    data[g].push({ last, by, av: pk ? (+pk.w_av || 0) / (NFL_THROUGH - D + 1) : 0, drafted: !!pk });
  }
}
const blend = (p, w, K) => { let num = 0, den = 0; w.forEach((wk, k) => { const r = p.by[p.last - k]; if (r) { num += wk * r.v * r.z; den += wk * r.v; } }); return num / (den + K); };
const groups = { offense: ['QB', 'RB', 'WR', 'TE'], defense: ['EDGE', 'DL', 'LB'] };
const out = { asof: new Date().toISOString().slice(0, 10), n: Object.fromEntries(Object.entries(data).map(([g, d]) => [g, { players: d.length, drafted: d.filter(p => p.drafted).length }])), grid: {}, byPosition: {} };
for (const [gn, gs] of Object.entries(groups)) {
  const res = [];
  for (const w of [[1], [5, 4, 3], [5, 5, 4], [1, 1, 1], [5, 3, 1], [5, 2, 1]]) for (const K of [0, 1500, 3000, 6000, 12000]) {
    let s = 0, n = 0; const per = {};
    for (const g of gs) { const d = data[g], r = corr(d.map(p => blend(p, w, K)), d.map(p => p.av)); per[g] = r3(r); s += r * d.length; n += d.length; }
    res.push({ weights: w.join('/'), K, r: r3(s / n), per });
  }
  out.grid[gn] = res.sort((a, b) => b.r - a.r);
  console.log(gn, out.grid[gn].slice(0, 4).map(x => `${x.weights} K${x.K} ${x.r}`).join(' | '), '| FV before', res.find(x => x.weights === '5/4/3' && x.K === 1500).r);
}
for (const g of Object.keys(POS)) out.byPosition[g] = r3(corr(data[g].map(p => blend(p, [5, 4, 3], 3000)), data[g].map(p => p.av)));
console.log('validity at 5/4/3 K3000', out.byPosition);
fs.writeFileSync(OUT, JSON.stringify(out, null, 1) + '\n');
