// FV as a distribution (data/fv_dist.json, fit by scripts/fv_dist_fit.py): for a graded FV and a player's spread
// group, the chance of each outcome tier, the 80% range (10th to 90th percentile) and the expected value on the
// board's own scale. Same rules as fv_dist in scripts/fv_dist.py; layouts/partials/fvoutlook.html draws the result.
//   bins: <30, 30-34, 35-39, ... 65-69, 70+ (the outcome FV); tiers: <30, 30s, 40s, 50s, 60+
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { fvOf } from './fv_scale.mjs';
import { readCfbAll, writeCfbAll } from './cfb_all.mjs';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
let FIT = null;
export function fvDistFit() {
  if (FIT === null) { try { FIT = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'fv_dist.json'), 'utf8')); } catch { FIT = {}; } }
  return FIT;
}

const ncdf = x => { const z = x / Math.SQRT2, a = Math.abs(z), t = 1 / (1 + 0.3275911 * a);
  const e = 1 - t * (0.254829592 + t * (-0.284496736 + t * (1.421413741 + t * (-1.453152027 + t * 1.061405429)))) * Math.exp(-a * a);
  return 0.5 * (1 + Math.sign(z) * e); };

// z: { term: value } for the board's kept spread terms (missing terms count 0)
export function fvDist(board, fv, z = {}) {
  const M = fvDistFit()[board];
  if (!M || fv == null) return null;
  const H = M.hinges || [45, 60];   // the location: the grade per 10 points from 40, plus a slope change at each hinge
  const mu = M.loc.reduce((a, c, i) => a + c * (i ? Math.max(0, fv - H[i - 1]) : fv - 40) / 10, 0);
  let ls = 0; for (const [k, g] of Object.entries(M.scale || {})) ls += g * (z[k] ?? 0);
  const s = Math.exp(Math.max(-3, Math.min(3, ls)));
  const F = M.cuts.map(c => ncdf((c - mu) / s)), p = [];
  for (let k = 0; k <= F.length; k++) p.push(Math.max(0, (k < F.length ? F[k] : 1) - (k ? F[k - 1] : 0)));
  const edges = M.edges, lo = [20, ...edges], hi = [...edges, 80], fl = M.floorShare;
  const q = x => {   // the quantile function (bottom bin: a point mass at 20 of share fl, then flat to 30)
    if (x <= p[0] * fl) return 20;
    if (x <= p[0]) return 20 + 10 * (x / p[0] - fl) / Math.max(1e-9, 1 - fl);
    let c = p[0];
    for (let j = 1; j < p.length; j++) { if (x <= c + p[j] || j === p.length - 1) return lo[j] + (hi[j] - lo[j]) * Math.min(1, (x - c) / Math.max(1e-12, p[j])); c += p[j]; }
    return 80;
  };
  const tiers = [0, 0, 0, 0, 0];
  p.forEach((v, j) => { tiers[Math.min(4, Math.max(0, Math.floor((lo[j] - 20) / 10)))] += v; });
  return { p, tiers, p10: q(0.1), p50: q(0.5), p90: q(0.9),
    mean: p.reduce((a, v, j) => a + v * M.binMean[j], 0), ev: M.binValue ? p.reduce((a, v, j) => a + v * M.binValue[j], 0) : null };
}

// a CFB player's spread terms (data/fv_dist.json cfb.scale), from the board's fields. years: years on campus (the
// class label's when the 247 class isn't known); early: not his last college season, the harness's rows graded a year
// or more before the draft (a senior or graduate counts as his last; a draft-eligible player on a consensus board,
// half); walkon: no 247 recruiting record; cons: a consensus draft board ranks him; level: the grade itself
const YEARS = { 'Fr': 1, 'RS-Fr': 2, 'So': 2, 'RS-So': 3, 'Jr': 3, 'RS-Jr': 4, 'Sr': 4, 'RS-Sr': 5, 'Gr': 5, 'RS-Gr': 6 };
export function cfbZ({ pos, years = null, cls = null, noRec = false, cons = false, fv }) {
  const y = years ?? YEARS[cls] ?? 3, last = y >= 4 || /Sr|Gr/.test(cls || '');
  return { pos_QB: +(pos === 'QB'), pos_TE: +(pos === 'TE'), pos_LB: +(pos === 'LB'), pos_RB: +(pos === 'RB'), pos_EDGE: +(pos === 'EDGE'), pos_DL: +(pos === 'DL'),
    under: +(y <= 2.5), early: last ? 0 : cons && y >= 3 ? 0.5 : 1, walkon: +!!noRec, lowsnap: 0, cons: +!!cons, level: (fv - 45) / 10 };
}
// the headline FV at the mean outcome (Noah, Oct 21 2026: FV means the mean outcome on both boards). The grade
// (r.fvg, the scarcity grade the distribution reads) stays on the row; fvx and fv become the distribution's mean, exact
// and in steps of 1. Idempotent: a row that already has fvg is left alone. K and P (outside the fit) take the map at
// the neutral spread terms.
export function atMean(r, z) {
  if (r.fvg != null || r.fvx == null) return r;
  const d = fvDist('cfb', r.fvx, z);
  r.fvg = Math.round(r.fvx * 100) / 100;
  if (d) { r.fvx = Math.round(Math.max(20, Math.min(80, d.mean)) * 100) / 100; r.fv = Math.round(r.fvx); }
  return r;
}
// a past season's grade at its mean outcome (static/data/cfb-past.json): position and years on campus that season
export const pastAtMean = (fv, g, years) => fvDist('cfb', fv, cfbZ({ pos: g, years: Math.max(1, years), fv }))?.mean ?? fv;
// the board's compact field: [P <30, P 30s, P 40s, P 50s, P 60+, 10th pct, 90th pct]
export const fvdOf = d => d ? [...d.tiers.map(x => Math.round(x * 1000) / 1000), Math.round(d.p10 * 10) / 10, Math.round(d.p90 * 10) / 10] : null;

// node scripts/fv_dist.mjs --annotate: refresh the fvd column of static/data/cfb-all.json in place from the board's
// fields (after a refit, without a full board run; the recruiting record isn't in the file, so walk-ons read as
// recruited until the next fetch_cfb.mjs run)
if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1]) && process.argv.includes('--annotate')) {
  const A = readCfbAll(ROOT);   // cfb-all + cfb-detail (where fvd lives) merged
  if (!A.cols.includes('fvd')) { A.cols.push('fvd'); for (const r of A.rows) r.push(null); }
  const ci = Object.fromEntries(A.cols.map((c, i) => [c, i]));
  let n = 0;
  for (const r of A.rows) {
    const pos = r[ci.pos], fv = ci.fvg != null && r[ci.fvg] != null ? r[ci.fvg] : r[ci.fvx];   // the odds come off the grade
    const z = cfbZ({ pos, cls: r[ci.cls], cons: r[ci.consRk] != null, fv });
    r[ci.fvd] = fv != null && pos !== 'K' && pos !== 'P' ? fvdOf(fvDist('cfb', fv, z)) : null;
    if (ci.fvg != null && r[ci.fvg] != null) { const d = fvDist('cfb', fv, z); if (d) { r[ci.fvx] = Math.round(Math.max(20, Math.min(80, d.mean)) * 100) / 100; r[ci.fv] = fvOf('cfb', r[ci.fvx]); } }
    if (r[ci.fvd]) n++;
  }
  writeCfbAll(A, ROOT);
  console.log('fvd on', n, 'of', A.rows.length, 'rows');
}
// node scripts/fv_dist.mjs --past: put static/data/cfb-past.json's grades at their mean outcome once (a file written
// before the mean headline; cfb_fv_refit.mjs --past writes them that way since), years from the board's class now
if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1]) && process.argv.includes('--past')) {
  const f = path.join(ROOT, 'static', 'data', 'cfb-past.json'), P = JSON.parse(fs.readFileSync(f, 'utf8'));
  if (P.scale === 'mean') { console.log('cfb-past: already at the mean'); process.exit(0); }
  const A = JSON.parse(fs.readFileSync(path.join(ROOT, 'static', 'data', 'cfb-all.json'), 'utf8')), ci = Object.fromEntries(A.cols.map((c, i) => [c, i]));
  const elig = {}; for (const r of A.rows) elig[r[ci.name] + '|' + r[ci.team]] = r[ci.elig];
  const now = Math.max(...P.seasons) + 1, G = { DT: 'DL', OT: 'OL', G: 'OL', C: 'OL', IOL: 'OL' };
  for (const [k, list] of Object.entries(P.players)) for (const x of list) x[1] = Math.round(pastAtMean(x[1], G[x[2]] || x[2], (elig[k] ?? 3) - (now - x[0])));
  P.scale = 'mean';
  fs.writeFileSync(f, JSON.stringify(P));
  console.log('cfb-past: restated', Object.keys(P.players).length, 'players');
}
