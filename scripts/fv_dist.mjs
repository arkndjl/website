// FV as a distribution (data/fv_dist.json, fit by scripts/fv_dist_fit.py): for a graded FV and a player's spread
// group, the chance of each outcome tier, the 80% range (10th to 90th percentile) and the expected value on the
// board's own scale. Same rules as fvDist in scripts/fv_dist.py and layouts/partials/fvdist.html.
//   bins: <30, 30-34, 35-39, ... 65-69, 70+ (the outcome FV); tiers: <30, 30s, 40s, 50s, 60+
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

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
  const [b1, b2, b3] = M.loc;
  const mu = b1 * (fv - 40) / 10 + b2 * Math.max(0, fv - 45) / 10 + b3 * Math.max(0, fv - 60) / 10;
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
