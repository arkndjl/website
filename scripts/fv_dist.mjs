// FV as a distribution (data/fv_dist.json, fit by scripts/fv_dist_fit.py): for a graded FV and a player's spread
// group, the chance of each outcome tier, the 80% range (10th to 90th percentile) and the expected value on the
// board's own scale. Same rules as fv_dist in scripts/fv_dist.py; layouts/partials/fvoutlook.html draws the result.
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

// the shared value scale (scripts/fv_value.py, Oct 26 2026): FV of a peak team share; 20 = replacement, 50 = 5% of a
// team, 80 = 80%. Same constants as fv_dist.py and fv_value.py
const SHARE_C = 1 / 280, SHARE_BASE = 15;
export const fvOfShare = ts => Math.min(80, 20 + 30 * Math.log1p(Math.max(0, ts) / SHARE_C) / Math.log(SHARE_BASE));
export const shareOfFv = fv => SHARE_C * Math.expm1((Math.max(20, fv) - 20) * Math.log(SHARE_BASE) / 30);
const interp = (x, xs, ys) => { if (x <= xs[0]) return ys[0]; for (let i = 1; i < xs.length; i++) if (x <= xs[i]) return ys[i - 1] + (ys[i] - ys[i - 1]) * (x - xs[i - 1]) / Math.max(1e-12, xs[i] - xs[i - 1]); return ys[ys.length - 1]; };
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
  const out = { p, tiers, p10: q(0.1), p50: q(0.5), p90: q(0.9),
    mean: p.reduce((a, v, j) => a + v * M.binMean[j], 0), ev: M.binValue ? p.reduce((a, v, j) => a + v * M.binValue[j], 0) : null };
  if (M.binShare && M.shareCurve) {
    // the value scale: the headline (vfv) is the FV of the expected peak share (each bin's mean share among past
    // careers); range and tier odds are the old ladder's read through the share curve (monotone, so quantiles carry)
    const xs = M.shareCurve.map(k => k[0]), ys = M.shareCurve.map(k => fvOfShare(k[1])), K = x => interp(x, xs, ys);
    const cdf = y => {   // P(old outcome < y), the inverse of q
      if (y <= 20) return 0;
      if (y < lo[1]) return p[0] * fl + p[0] * (1 - fl) * (y - 20) / 10;
      let c = p[0];
      for (let j = 1; j < p.length; j++) { if (y < hi[j] || j === p.length - 1) return Math.min(1, c + p[j] * Math.min(1, (y - lo[j]) / Math.max(1e-12, hi[j] - lo[j]))); c += p[j]; }
      return 1;
    };
    // each bin's careers that reached each value tier when the fit has them (they pile at the top bin's cap)
    const cuts = M.binTiers ? [0, ...[0, 1, 2, 3].map(k => 1 - p.reduce((a, v, j) => a + v * M.binTiers[j][k], 0)), 1]
      : [0, ...[30, 40, 50, 60].map(t => t > ys[0] ? cdf(interp(t, ys, xs)) : 0), 1];
    out.share = p.reduce((a, v, j) => a + v * M.binShare[j], 0);
    out.vfv = fvOfShare(out.share);
    out.tiersV = [0, 1, 2, 3, 4].map(j => Math.max(0, cuts[j + 1] - cuts[j]));
    out.p10v = K(out.p10); out.p50v = K(out.p50); out.p90v = K(out.p90);
  }
  return out;
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
// the headline FV at the mean outcome (Noah, Oct 21 2026: FV means the mean outcome on both boards; Oct 26: the mean
// VALUE, the FV of the expected peak team share, scripts/fv_value.py). The grade
// (r.fvg, the scarcity grade the distribution reads) stays on the row; fvx and fv become the distribution's mean, exact
// and in steps of 1. Idempotent: a row that already has fvg is left alone. K and P (outside the fit) take the map at
// the neutral spread terms.
export function atMean(r, z) {
  if (r.fvg != null || r.fvx == null) return r;
  const d = fvDist('cfb', r.fvx, z);
  r.fvg = Math.round(r.fvx * 100) / 100;
  if (d) { r.fvx = Math.round(Math.max(20, Math.min(80, headOf(d))) * 100) / 100; r.fv = Math.round(r.fvx); }
  return r;
}
// the old outcome ladder's FV for a value-scale FV (the share curve read backwards): for the models whose constants
// were set on that ladder (cfb_teams.mjs avOf, the NFL AV a season by FV tier), so they keep reading it
export function rarityOf(board, v) {
  const M = fvDistFit()[board]; if (v == null || !M?.shareCurve) return v;
  const xs = M.shareCurve.map(k => k[0]), ys = M.shareCurve.map(k => fvOfShare(k[1]));
  return interp(v, ys, xs);
}
// the headline of a distribution: the value-scale FV when the fit has it, else the old ladder's mean
export const headOf = d => d.vfv ?? d.mean;
// a past season's grade at its mean outcome (static/data/cfb-past.json): position and years on campus that season
// (scale 'rarity': the old ladder's mean, for the game-model tests whose terms were fit on it)
export const pastAtMean = (fv, g, years, scale = 'value') => { const d = fvDist('cfb', fv, cfbZ({ pos: g, years: Math.max(1, years), fv })); return d ? (scale === 'rarity' ? d.mean : headOf(d)) : fv; };
// the board's compact field: [P <30, P 30s, P 40s, P 50s, P 60+, 10th pct, 90th pct]
// (on the value scale when the fit has it)
export const fvdOf = d => d ? (d.tiersV ? [...d.tiersV.map(x => Math.round(x * 1000) / 1000), Math.round(d.p10v * 10) / 10, Math.round(d.p90v * 10) / 10]
  : [...d.tiers.map(x => Math.round(x * 1000) / 1000), Math.round(d.p10 * 10) / 10, Math.round(d.p90 * 10) / 10]) : null;

// node scripts/fv_dist.mjs --annotate: refresh the fvd column of static/data/cfb-all.json in place from the board's
// fields (after a refit, without a full board run; the recruiting record isn't in the file, so walk-ons read as
// recruited until the next fetch_cfb.mjs run)
if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1]) && process.argv.includes('--annotate')) {
  const f = path.join(ROOT, 'static', 'data', 'cfb-all.json'), A = JSON.parse(fs.readFileSync(f, 'utf8'));
  if (!A.cols.includes('fvd')) { A.cols.push('fvd'); for (const r of A.rows) r.push(null); }
  const ci = Object.fromEntries(A.cols.map((c, i) => [c, i]));
  let n = 0;
  for (const r of A.rows) {
    const pos = r[ci.pos], fv = ci.fvg != null && r[ci.fvg] != null ? r[ci.fvg] : r[ci.fvx];   // the odds come off the grade
    const z = cfbZ({ pos, cls: r[ci.cls], cons: r[ci.consRk] != null, fv });
    r[ci.fvd] = fv != null && pos !== 'K' && pos !== 'P' ? fvdOf(fvDist('cfb', fv, z)) : null;
    if (ci.fvg != null && r[ci.fvg] != null) { const d = fvDist('cfb', fv, z); if (d) { r[ci.fvx] = Math.round(Math.max(20, Math.min(80, headOf(d))) * 100) / 100; r[ci.fv] = Math.round(r[ci.fvx]); } }
    if (r[ci.fvd]) n++;
  }
  fs.writeFileSync(f, JSON.stringify(A));
  console.log('fvd on', n, 'of', A.rows.length, 'rows');
}
// node scripts/fv_dist.mjs --past: put static/data/cfb-past.json's grades at their mean outcome once (a file written
// before the mean headline; cfb_fv_refit.mjs --past writes them that way since), years from the board's class now
if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1]) && process.argv.includes('--past')) {
  const f = path.join(ROOT, 'static', 'data', 'cfb-past.json'), P = JSON.parse(fs.readFileSync(f, 'utf8'));
  if (P.scale === 'mean' || P.scale === 'value') { console.log('cfb-past: already restated (' + P.scale + '); rerun cfb_fv_refit.mjs --past'); process.exit(0); }
  const A = JSON.parse(fs.readFileSync(path.join(ROOT, 'static', 'data', 'cfb-all.json'), 'utf8')), ci = Object.fromEntries(A.cols.map((c, i) => [c, i]));
  const elig = {}; for (const r of A.rows) elig[r[ci.name] + '|' + r[ci.team]] = r[ci.elig];
  const now = Math.max(...P.seasons) + 1, G = { DT: 'DL', OT: 'OL', G: 'OL', C: 'OL', IOL: 'OL' };
  for (const [k, list] of Object.entries(P.players)) for (const x of list) x[1] = Math.round(pastAtMean(x[1], G[x[2]] || x[2], (elig[k] ?? 3) - (now - x[0])));
  P.scale = 'mean';
  fs.writeFileSync(f, JSON.stringify(P));
  console.log('cfb-past: restated', Object.keys(P.players).length, 'players');
}
