// Nov 23 2026: does CFB FV's production term (5/4/3 by snaps, K 3000) underrate players whose role grew in their last
// season? Universe and outcome as scripts/cfb_statplus_backtest.mjs (last PFN season 2019-22, NFL weighted AV a season).
// Variant: when the last season's snaps are 1.5x+ the earlier seasons' mean, the earlier seasons' weights x d.
// d chosen leave one final season out; score = pooled per-position correlation with AV, and a paired squared-error
// test on a per-position linear fit (AV on the term), clustered by player (one row each).
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { NFLPOS } from '../../cfb_nflpos.mjs';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const CACHE = path.join(ROOT, 'scripts', '.cache', 'statplus');
const SPG = { QB: 65, RB: 30, WR: 40, TE: 40, EDGE: 50, DL: 45, LB: 55 };
const [h, ...pl] = fs.readFileSync(path.join(CACHE, 'draft_picks.csv'), 'utf8').trim().split('\n'), H = h.split(',');
const picks = pl.map(l => { const v = l.split(','); return Object.fromEntries(H.map((k, i) => [k, v[i]])); }).filter(r => +r.season >= 2020 && +r.season <= 2025);
const nm = s => (s || '').toLowerCase().normalize('NFKD').replace(/[^a-z ]/g, '').replace(/\b(jr|sr|ii|iii|iv)\b/g, '').replace(/\s+/g, ' ').trim();
const col = s => nm(s).replace(/\bstate\b/, 'st').replace(/\buniversity\b|\bof\b/g, '').trim();
const data = [];
for (const g of Object.keys(SPG)) {
  const rows = JSON.parse(fs.readFileSync(path.join(CACHE, `pfn_${g}.json`))).filter(r => r.division === 'FBS'), cz = {};
  for (const r of rows) (cz[r.season] ||= []).push(r.score);
  for (const [s, xs] of Object.entries(cz)) { const m = xs.reduce((a, b) => a + b) / xs.length; cz[s] = [m, Math.sqrt(xs.reduce((a, b) => a + (b - m) ** 2, 0) / xs.length)]; }
  const byId = {};
  for (const r of rows) { r.z = (r.score - cz[r.season][0]) / cz[r.season][1]; r.v = (typeof r.snapsQ === 'number' ? r.snapsQ : null) ?? ((r.gp ?? r.gamesQ ?? 0) * SPG[g]); (byId[r.id] ||= {})[r.season] = r; }
  for (const by of Object.values(byId)) {
    const last = Math.max(...Object.keys(by).map(Number)); if (last > 2022) continue;
    const r = by[last], D = last + 1, cand = picks.filter(p => nm(p.pfr_player_name) === nm(r.name) && NFLPOS[g].includes(p.position));
    const pk = cand.find(p => +p.season === D && col(p.college).split(' ')[0] === col(r.team).split(' ')[0]) || cand.find(p => +p.season === D);
    if (!pk && cand.some(p => +p.season > D)) continue;
    const prev = [1, 2].map(k => by[last - k]).filter(Boolean);
    const vp = prev.length ? prev.reduce((a, x) => a + x.v, 0) / prev.length : null;
    data.push({ g, last, by, av: pk ? (+pk.w_av || 0) / (2025 - D + 1) : 0, grow: vp != null && vp > 0 ? r.v / vp : null });
  }
}
const W = [5, 4, 3], K = 3000;
const term = (p, d, thr = 1.5) => { let num = 0, den = 0; W.forEach((wk, k) => { const r = p.by[p.last - k]; if (!r) return; const m = k > 0 && p.grow != null && p.grow >= thr ? d : 1; num += wk * m * r.v * r.z; den += wk * m * r.v; }); return num / (den + K); };
function fitLin(ps, f) { const x = ps.map(f), y = ps.map(p => p.av), n = x.length, mx = x.reduce((a, b) => a + b) / n, my = y.reduce((a, b) => a + b) / n; let sxy = 0, sxx = 0; x.forEach((v, i) => { sxy += (v - mx) * (y[i] - my); sxx += (v - mx) ** 2; }); const b = sxy / sxx; return v => my + b * (v - mx); }
const DS = [1, 0.75, 0.5, 0.25, 0.1];
const gs = Object.keys(SPG);
// leave one final season out: d picked on the other seasons by pooled squared error of the per-position fit
const lossB = [], lossN = [], seasonsBetter = {}; const picked = [];
for (const y of [2019, 2020, 2021, 2022]) {
  const tr = data.filter(p => p.last !== y), te = data.filter(p => p.last === y);
  const sse = d => gs.reduce((s, g) => { const t = tr.filter(p => p.g === g), f = fitLin(t, p => term(p, d)); return s + t.reduce((a, p) => a + (f(term(p, d)) - p.av) ** 2, 0); }, 0);
  const d = DS.reduce((b, x) => (sse(x) < sse(b) ? x : b), 1); picked.push(d);
  let b = 0, n = 0;
  for (const g of gs) {
    const t = tr.filter(p => p.g === g), f1 = fitLin(t, p => term(p, 1)), fd = fitLin(t, p => term(p, d));
    for (const p of te.filter(p => p.g === g)) { const e1 = (f1(term(p, 1)) - p.av) ** 2, ed = (fd(term(p, d)) - p.av) ** 2; lossB.push(e1); lossN.push(ed); b += e1; n += ed; }
  }
  seasonsBetter[y] = n < b;
}
const dd = lossN.map((x, i) => x - lossB[i]), md = dd.reduce((a, b) => a + b) / dd.length, sd = Math.sqrt(dd.reduce((a, b) => a + (b - md) ** 2, 0) / (dd.length - 1));
const grow = data.filter(p => p.grow != null && p.grow >= 1.5);
console.log('players', data.length, 'role grew 1.5x+', grow.length, 'drafted among them', grow.filter(p => p.av > 0).length);
console.log('d picked by fold', picked, 'MSE base', (lossB.reduce((a, b) => a + b) / lossB.length).toFixed(4), 'new', (lossN.reduce((a, b) => a + b) / lossN.length).toFixed(4), 't', (md / (sd / Math.sqrt(dd.length))).toFixed(2), 'seasons better', seasonsBetter);
// residual check: AV minus the per-position fit at the shipped term, growers vs the rest
let rg = [], ro = [];
for (const g of gs) { const t = data.filter(p => p.g === g), f = fitLin(t, p => term(p, 1)); for (const p of t) (p.grow != null && p.grow >= 1.5 ? rg : ro).push(p.av - f(term(p, 1))); }
const mm = a => a.reduce((x, y) => x + y, 0) / a.length, se = a => Math.sqrt(a.reduce((x, y) => x + (y - mm(a)) ** 2, 0) / (a.length - 1) / a.length);
console.log('residual AV/season: grew', mm(rg).toFixed(3), '+-', se(rg).toFixed(3), ' rest (incl. one-season players)', mm(ro).toFixed(3), '+-', se(ro).toFixed(3));
for (const d of DS) console.log('d', d, 'pooled r', gs.map(g => { const t = data.filter(p => p.g === g), x = t.map(p => term(p, d)), y = t.map(p => p.av), n = x.length, mx = mm(x), my = mm(y); let a = 0, b = 0, c = 0; x.forEach((v, i) => { a += (v - mx) * (y[i] - my); b += (v - mx) ** 2; c += (y[i] - my) ** 2; }); return (a / Math.sqrt(b * c)).toFixed(3); }).join(' '));
