// The Node port of scripts/harness.py's scoring rules, paired test and multiple-testing control, for the CFB models
// (cfb_model.mjs, cfb_fv_refit.mjs, the .mjs backtests). Same rules, same numbers: `node scripts/harness.mjs --test`
// checks the expect values that `python3 scripts/harness.py --test` wrote to scripts/data/harness_fixture.json.
// The ledger (data/model_ledger.json) and the re-scoring runs live on the Python side; a .mjs backtest that wants
// its terms in the ledger writes its rows with record() and passes them to harness_rescore.py (--rows <file>).
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const Q_KEEP = 0.10;

// ---------------------------------------------------------------- scoring rules (per row; lower is better)
const erf = (x) => {
  // Abramowitz-Stegun 7.1.26 is too coarse for the fixture; use the series / continued fraction split
  const t = Math.abs(x);
  if (t < 2.5) {
    let sum = t, term = t;
    for (let n = 1; n < 200; n++) {
      term *= -t * t / n;
      const add = term / (2 * n + 1);
      sum += add;
      if (Math.abs(add) < 1e-17) break;
    }
    return Math.sign(x) * 2 / Math.sqrt(Math.PI) * sum;
  }
  // erfc continued fraction (Lentz)
  let f = t, C = t, D = 0;
  for (let i = 1; i < 300; i++) {
    const a = i / 2;
    D = t + a * D; D = D === 0 ? 1e-300 : 1 / D;
    C = t + a / C; if (C === 0) C = 1e-300;
    const del = C * D;
    f *= del;
    if (Math.abs(del - 1) < 1e-16) break;
  }
  const erfc = Math.exp(-t * t) / Math.sqrt(Math.PI) / f;
  return Math.sign(x) * (1 - erfc);
};
export const Phi = (z) => 0.5 * (1 + erf(z / Math.SQRT2));
const phi = (z) => Math.exp(-0.5 * z * z) / Math.sqrt(2 * Math.PI);
export const ae = (p, y) => p.map((v, i) => Math.abs(v - y[i]));
export const se = (p, y) => p.map((v, i) => (v - y[i]) ** 2);
export const brier = se;
export const logloss = (p, y, eps = 1e-6) => p.map((v, i) => {
  const q = Math.min(Math.max(v, eps), 1 - eps);
  return -(y[i] * Math.log(q) + (1 - y[i]) * Math.log(1 - q));
});
export const crpsNormal = (mu, sd, y) => mu.map((m, i) => {
  const z = (y[i] - m) / sd[i];
  return sd[i] * (z * (2 * Phi(z) - 1) + 2 * phi(z) - 1 / Math.sqrt(Math.PI));
});
export const rps = (probs, k) => probs.map((row, i) => {
  let c = 0, s = 0;
  for (let j = 0; j < row.length - 1; j++) { c += row[j]; s += (c - (j >= k[i] ? 1 : 0)) ** 2; }
  return s / Math.max(row.length - 1, 1);
});
export const pinball = (q, tau, y) => q.map((v, i) => { const d = y[i] - v; return Math.max(tau * d, (tau - 1) * d); });

// ---------------------------------------------------------------- distributions
const lgamma = (x) => {
  const g = 7, c = [0.99999999999980993, 676.5203681218851, -1259.1392167224028, 771.32342877765313, -176.61502916214059,
    12.507343278686905, -0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7];
  if (x < 0.5) return Math.log(Math.PI / Math.abs(Math.sin(Math.PI * x))) - lgamma(1 - x);
  x -= 1;
  let a = c[0];
  const t = x + g + 0.5;
  for (let i = 1; i < g + 2; i++) a += c[i] / (x + i);
  return 0.5 * Math.log(2 * Math.PI) + (x + 0.5) * Math.log(t) - t + Math.log(a);
};
const tiny = (v) => (Math.abs(v) > 1e-300 ? v : 1e-300);
function betacf(a, b, x) {
  const qab = a + b, qap = a + 1, qam = a - 1;
  let c = 1, d = 1 / tiny(1 - qab * x / qap), h = d;
  for (let m = 1; m < 300; m++) {
    const m2 = 2 * m;
    let aa = m * (b - m) * x / ((qam + m2) * (a + m2));
    d = 1 / tiny(1 + aa * d); c = tiny(1 + aa / c); h *= d * c;
    aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2));
    d = 1 / tiny(1 + aa * d); c = tiny(1 + aa / c);
    const de = d * c; h *= de;
    if (Math.abs(de - 1) < 1e-12) break;
  }
  return h;
}
function ibeta(a, b, x) {
  if (x <= 0) return 0;
  if (x >= 1) return 1;
  const lb = lgamma(a + b) - lgamma(a) - lgamma(b) + a * Math.log(x) + b * Math.log(1 - x);
  return x < (a + 1) / (a + b + 2) ? Math.exp(lb) * betacf(a, b, x) / a : 1 - Math.exp(lb) * betacf(b, a, 1 - x) / b;
}
export function tCdf(t, df) {
  if (!Number.isFinite(t)) return t < 0 ? 0 : 1;
  if (df > 1000) return Phi(t);
  const tail = 0.5 * ibeta(df / 2, 0.5, df / (df + t * t));
  return t < 0 ? tail : 1 - tail;
}
export function zOfP(p) {
  p = Math.min(Math.max(p, 1e-15), 1 - 1e-15);
  const a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00];
  const b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01, -1.328068155288572e+01];
  const c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00];
  const d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00];
  let x;
  const tailF = (q) => (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
  if (p < 0.02425) x = tailF(Math.sqrt(-2 * Math.log(p)));
  else if (p > 1 - 0.02425) x = -tailF(Math.sqrt(-2 * Math.log(1 - p)));
  else {
    const q = p - 0.5, r = q * q;
    x = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
  }
  const e = Phi(x) - p;
  return x - e * Math.sqrt(2 * Math.PI) * Math.exp(x * x / 2);
}

// ---------------------------------------------------------------- paired test
function crVar(d, g, mean) {
  const s = new Map();
  d.forEach((v, i) => s.set(g[i], (s.get(g[i]) || 0) + v - mean));
  let ss = 0;
  for (const v of s.values()) ss += v * v;
  const G = s.size, n = d.length;
  return [ss / n ** 2 * G / Math.max(G - 1, 1), G];
}
// new minus base loss, row by row (d < 0: the candidate is better); cluster: keys, or an array of key arrays (multiway)
export function paired(nw, base, cluster = null) {
  const idx = nw.map((v, i) => i).filter((i) => !Number.isNaN(nw[i]) && !Number.isNaN(base[i]));
  const d = idx.map((i) => nw[i] - base[i]);
  const n = d.length;
  if (n < 3) return { d: 0, se: null, t: 0, p: 0.5, n, G: n, deff: 1 };
  const mean = d.reduce((a, b) => a + b, 0) / n;
  const vIid = d.reduce((a, b) => a + (b - mean) ** 2, 0) / (n - 1) / n;
  let v = vIid, G = n;
  if (cluster) {
    const ks = (Array.isArray(cluster[0]) ? cluster : [cluster]).map((k) => idx.map((i) => k[i]));
    if (ks.length === 1) [v, G] = crVar(d, ks[0], mean);
    else {
      v = 0;
      const m = ks.length;
      for (let mask = 1; mask < 1 << m; mask++) {
        const sub = [...Array(m).keys()].filter((j) => mask & (1 << j));
        const key = sub.length > 1 ? d.map((_, i) => sub.map((j) => String(ks[j][i])).join('|')) : ks[sub[0]];
        const [vi, gi] = crVar(d, key, mean);
        v += (sub.length % 2 ? 1 : -1) * vi;
        if (sub.length === 1) G = Math.min(G, gi);
      }
      v = Math.max(v, ...ks.map((k) => crVar(d, k, mean)[0]));
    }
  }
  const sev = v > 0 ? Math.sqrt(v) : NaN;
  const t = sev > 0 ? mean / sev : 0;
  return { d: mean, se: sev, t, p: G > 1 ? tCdf(t, G - 1) : 0.5, n, G, deff: vIid > 0 ? Math.round(v / vIid * 100) / 100 : 1 };
}

// ---------------------------------------------------------------- multiple testing
export function bh(p) {
  const m = p.length, o = p.map((v, i) => i).sort((a, b) => p[a] - p[b]), q = new Array(m);
  let run = 1;
  for (let i = m - 1; i >= 0; i--) { run = Math.min(run, p[o[i]] * m / (i + 1)); q[o[i]] = run; }
  return q;
}
export function holm(p) {
  const m = p.length, o = p.map((v, i) => i).sort((a, b) => p[a] - p[b]), a = new Array(m);
  let run = 0;
  o.forEach((j, i) => { run = Math.max(run, Math.min(1, (m - i) * p[j])); a[j] = run; });
  return a;
}
export const stouffer = (zs, w = null) => {
  w = w || zs.map(() => 1);
  return zs.reduce((s, z, i) => s + w[i] * z, 0) / Math.sqrt(w.reduce((s, x) => s + x * x, 0));
};
export const pOfZ = (z) => Phi(-z);

// one ledger row from two paired tests of (with the term) minus (without it): t < 0 means the term helps
const r5 = (x, k = 5) => Math.round(x * 10 ** k) / 10 ** k;
export function record(term, tune, held, core = false, extra = {}) {
  const side = (s) => ({ d: r5(-s.d), t: r5(s.t, 2), p: r5(s.p, 4), n: s.n, G: s.G, deff: s.deff });
  return { term, core, tune: side(tune), held: side(held), ...extra };
}
// verdicts on one BH family, the same rule as harness.py judge()
export function judge(rows, qKeep = Q_KEEP) {
  rows.forEach((r) => { r.z = r5(stouffer([r.tune, r.held].filter(Boolean).map((s) => -s.t)), 2); r.p = pOfZ(r.z); });
  const q = bh(rows.map((r) => r.p));
  rows.forEach((r, i) => {
    r.q = r5(q[i], 4); r.p = r5(r.p, 4);
    // no held-out split (CV evidence only): never free to remove
    const worse = !r.held ? true : r.held.d != null ? r.held.d > 0 : r.held.t < 0;
    r.verdict = r.q <= qKeep ? 'keep' : r.core ? 'core' : worse ? 'watch' : 'drop';
  });
  return rows;
}

// ---------------------------------------------------------------- self-test
function close(a, b, tol = 1e-6) {
  if (Array.isArray(a)) return a.length === b.length && a.every((x, i) => close(x, b[i], tol));
  if (a && typeof a === 'object') return Object.keys(a).length === Object.keys(b).length && Object.keys(a).every((k) => close(a[k], b[k], tol));
  if (typeof a === 'number') return Math.abs(a - b) <= tol * Math.max(1, Math.abs(b));
  return a === b;
}
if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1]) && process.argv.includes('--test')) {
  const F = JSON.parse(fs.readFileSync(path.join(HERE, 'data', 'harness_fixture.json'), 'utf8'));
  const R8 = (x) => Math.round(x * 1e8) / 1e8;
  const pr = (o) => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, typeof v === 'number' && !Number.isInteger(v) ? R8(v) : v]));
  const R = {
    t_cdf: F.tdf.map(([t, df]) => R8(tCdf(t, df))), z_of_p: F.ps.map((p) => R8(zOfP(p))),
    bh: bh(F.ps).map(R8), holm: holm(F.ps).map(R8),
    iid: pr(paired(F.a, F.b)), cr1: pr(paired(F.a, F.b, F.c1)), cr2: pr(paired(F.a, F.b, [F.c1, F.c2])),
    crps: crpsNormal([0, 1, -2], [1, 2, 3], [0.5, -1, 4]).map(R8),
    rps: rps([[0.2, 0.5, 0.3], [0.6, 0.3, 0.1]], [2, 0]).map(R8),
    logloss: logloss([0.2, 0.9], [0, 1]).map(R8), stouffer: R8(stouffer([1, 2])),
  };
  const bad = Object.keys(F.expect).filter((k) => !close(R[k], F.expect[k]));
  if (bad.length) {
    for (const k of bad) console.log(k, 'node', JSON.stringify(R[k]), 'python', JSON.stringify(F.expect[k]));
    process.exit(1);
  }
  console.log('harness.mjs: all tests pass (matches harness.py on the fixture)');
}
