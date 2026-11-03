// Measured height and weight: the combine-equivalent size from every listing the board has, fit against NFL combine
// and pro day measurements by scripts/cfb_measure.py (data/cfb_measure.json). Sources, by what the fit gives each:
// the ESPN roster listing (r) and the 247 composite listing (hs, with years since the class, j), per coarse position
// group and listing pattern: T = mt + b . (x - mx), so a listing is pulled toward the group's combine mean by its own
// error (an empirical-Bayes shrink) and roster heights lose their inflation (+0.4-0.5 in). On3's listing is shown in
// the source mix but not used: for the board's On3 rows it is the recruiting listing (90% differ from ESPN, 15 lb
// lighter on average), and nothing dates it.
// p: { g, espnPos, espnHt (inches), espnWt, recHt, recWt, recYear, on3Ht, on3Wt }, season: the board's season
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const FILE = path.join(ROOT, 'data', 'cfb_measure.json');
const M = fs.existsSync(FILE) ? JSON.parse(fs.readFileSync(FILE, 'utf8')) : null;
export const MEASURE = M;

const q = x => Math.round(x * 4) / 4;
const ftIn = h => `${Math.floor(h / 12)}-${+(h % 12).toFixed(2)}`;

function one(P, g, f) {
  const pat = f.r != null && f.hs != null ? 'rh' : f.r != null ? 'r' : f.hs != null ? 'h' : null;
  const c = pat && P[pat]?.[g];
  if (!c) return null;
  const ks = M.patterns[pat];
  const v = c.mt + ks.reduce((a, k, i) => a + c.b[i] * (f[k] - c.mx[k]), 0);
  // the implied weights: b on each listing, the rest on the group's combine mean (j is a growth term, not a source)
  const w = Object.fromEntries(ks.filter(k => k !== 'j').map((k, i) => [k, c.b[ks.indexOf(k)]]));
  return { v, sd: c.sd, w, prior: 1 - Object.values(w).reduce((a, b) => a + b, 0), mt: c.mt };
}

export function measureOf(p, season) {
  if (!M) return null;
  const g = M.boardCoarse[p.g];
  if (!g) return null;
  const j = p.recYear ? season + 1 - p.recYear : null;
  const fh = { r: p.espnHt || null, hs: p.recHt || null, j }, fw = { r: p.espnWt || null, hs: p.recWt || null, j };
  if (fh.hs == null) fh.j = null;
  if (fw.hs == null) fw.j = null;
  const H = one(M.params.ht, g, fh), W = one(M.params.wt, g, fw);
  if (!H || !W) return null;
  const ht = q(H.v), wt = Math.round(W.v), bmi = Math.round(703 * W.v / H.v ** 2 * 10) / 10;
  // hover: each source and its weight, the prior, and the fit's error
  const pc = x => `${Math.round(x * 100)}%`, parts = [];
  if (fh.r != null || fw.r != null) parts.push(`ESPN ${fh.r != null ? ftIn(fh.r) : '—'}, ${fw.r ?? '—'} lb (ht ${pc(H.w.r ?? 0)}, wt ${pc(W.w.r ?? 0)})`);
  if (fh.hs != null || fw.hs != null) parts.push(`247 ${p.recYear} ${fh.hs != null ? ftIn(fh.hs) : '—'}, ${fw.hs ?? '—'} lb (ht ${pc(H.w.hs ?? 0)}, wt ${pc(W.w.hs ?? 0)})`);
  parts.push(`${g} combine mean ${ftIn(q(H.mt))}, ${Math.round(W.mt)} lb (ht ${pc(H.prior)}, wt ${pc(W.prior)})`);
  if (p.on3Ht || p.on3Wt) parts.push(`On3 ${p.on3Ht ? ftIn(p.on3Ht) : '—'}, ${p.on3Wt ?? '—'} lb (not used)`);
  const src = `measured ${ftIn(ht)}, ${wt} lb, BMI ${bmi} (combine-equivalent; ±${H.sd.toFixed(1)} in, ±${Math.round(W.sd)} lb) = ${parts.join(' · ')}`;
  // compact row form for the board (assets/js/cfb.js builds the hover from it and measureWeights)
  const mz = [ht, wt, bmi, g, fh.r, fw.r, p.recYear || null, fh.hs, fw.hs, p.on3Ht || null, p.on3Wt || null];
  return { ht, wt, bmi, src, g, mz };
}

// each group's weights on the ESPN listing, the 247 listing and the combine mean, by listing pattern, and the error SD
export function measureWeights() {
  if (!M) return null;
  const out = {};
  for (const g of M.groups) for (const pat of ['r', 'rh', 'h']) {
    const H = M.params.ht[pat]?.[g], W = M.params.wt[pat]?.[g]; if (!H || !W) continue;
    const ks = M.patterns[pat], w = c => { const o = ks.map((k, i) => k === 'j' ? null : [k, c.b[i]]).filter(Boolean); const v = Object.fromEntries(o);
      return [Math.round((v.r ?? 0) * 100), Math.round((v.hs ?? 0) * 100), Math.round((1 - (v.r ?? 0) - (v.hs ?? 0)) * 100)]; };
    (out[g] ||= {})[pat] = { ht: w(H), wt: w(W), sd: [Math.round(H.sd * 10) / 10, Math.round(W.sd)], mean: [Math.round(H.mt * 4) / 4, Math.round(W.mt)] };
  }
  return out;
}
