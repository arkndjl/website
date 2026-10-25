// Historical comps for the CFB board (audit #41, Oct 25 2026): each graded QB, RB, WR, TE, EDGE, DT and LB's nearest
// players among the 2014-22 FBS seasons the FV backtest rebuilds (scripts/data/cfb_comps_pool.json, written by
// scripts/cfb_comps.py), with what they did in the NFL. Profile within position: production z, 247 pedigree z, years on
// campus, listed height and weight, team strength; weights picked held out (data/cfb_comps.json). A comp is a player: each player's
// nearest season counts once. Display only: the comps' outcome mix failed as an FV outlook term (held-out RPS no better).
//   writeComps(players, file)  players: [{ key, g, z, hs, years, ht, wt, lvl, ath }] -> static/data/cfb-comps.json
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const POOL = path.join(ROOT, 'scripts', 'data', 'cfb_comps_pool.json');
const FEATS = ['z', 'hs', 'years', 'ht', 'wt', 'lvl', 'ath'];
const K = 25;                                  // neighbours behind the outcome mix

// "6-2" / "6' 2\"" / 74 -> inches
export const inches = h => { if (h == null || h === '') return null; if (typeof h === 'number') return h;
  const m = /^(\d)\D+(\d{1,2})/.exec(String(h)); return m ? +m[1] * 12 + +m[2] : null; };

let P = null;
function pool() {
  if (P) return P;
  if (!fs.existsSync(POOL)) return (P = false);
  const d = JSON.parse(fs.readFileSync(POOL, 'utf8')), c = Object.fromEntries(d.cols.map((k, i) => [k, i]));
  const w = FEATS.map(f => d.weights[f] ?? 0), by = {};
  for (const [i, r] of d.rows.entries()) {
    const sz = d.size[r[c.g]];
    const x = [r[c.z], r[c.hs], r[c.years], r[c.ht] ? (r[c.ht] - sz.ht[0]) / sz.ht[1] : null, r[c.wt] ? (r[c.wt] - sz.wt[0]) / sz.wt[1] : null, r[c.lvl], r[c.ath]];
    (by[r[c.g]] ||= []).push({ i, x, key: r[c.name] + '|' + r[c.pick] + '|' + r[c.y], y: r[c.y], pick: r[c.pick] });
  }
  return (P = { d, c, w, by, ws: w.reduce((a, b) => a + b, 0) });
}

// weighted RMS distance over the inputs both have (as scripts/cfb_comps.py dist)
function dist(a, b, w, ws) {
  let s = 0, den = 0;
  for (let j = 0; j < w.length; j++) { if (!w[j] || a[j] == null || b[j] == null) continue; s += w[j] * (a[j] - b[j]) ** 2; den += w[j]; }
  return den ? Math.sqrt(s / den * ws) : Infinity;
}

// one player's comps: the K nearest players, the 3 shown and the outcome mix summary
export function compsOf(p) {
  const Q = pool(); if (!Q) return null;
  const R = Q.by[p.g]; if (!R) return null;
  const sz = Q.d.size[p.g], ht = inches(p.ht), wt = +p.wt || null;
  const x = [p.z, p.hs, p.years, ht ? (ht - sz.ht[0]) / sz.ht[1] : null, wt ? (wt - sz.wt[0]) / sz.wt[1] : null, p.lvl, p.ath];
  if (x[0] == null && x[1] == null) return null;              // no production and no recruiting record: no profile to match
  const ds = R.map(r => [dist(x, r.x, Q.w, Q.ws), r]).filter(a => isFinite(a[0])).sort((a, b) => a[0] - b[0]);
  const seen = new Set(), near = [];
  for (const a of ds) { if (seen.has(a[1].key)) continue; seen.add(a[1].key); near.push(a); if (near.length === K) break; }
  if (near.length < 5) return null;
  // kernel weights as the mix in cfb_comps.py: nearer comps count more
  const h = Math.max(near.map(a => a[0]).sort((a, b) => a - b)[near.length >> 1], 1e-6), kw = near.map(a => Math.exp(-((a[0] / h) ** 2) / 2)), W = kw.reduce((a, b) => a + b, 0);
  const share = f => Math.round(near.reduce((s, a, i) => s + kw[i] * (f(a[1]) ? 1 : 0), 0) / W * 100) / 100;
  return { top: near.slice(0, 3).map(a => [a[1].i, Math.round(a[0] * 100) / 100]),
    mix: [near.length, share(r => r.pick), share(r => r.pick && r.pick <= 32), share(r => r.y >= 50)] };
}

// static/data/cfb-comps.json: the pool rows shown (name, school, season, position, pick, AV a season, All-Pro, Pro
// Bowls) and, by "name|team", [[pool row, distance] x3, [n, drafted, first round, starter (50+ outcome)]]
export function writeComps(players, file) {
  const Q = pool(); if (!Q) { console.log('cfb comps: no pool (scripts/cfb_comps.py)'); return; }
  const { d, c } = Q, used = new Map(), out = {};
  for (const p of players) {
    const r = compsOf(p); if (!r) continue;
    out[p.key] = [...r.top.map(([i, dd]) => { if (!used.has(i)) used.set(i, used.size); return [used.get(i), dd]; }), r.mix];
  }
  const rows = [...used.keys()].map(i => { const r = d.rows[i]; return [r[c.name], r[c.team], r[c.s], r[c.g], r[c.pick], r[c.av], r[c.ap], r[c.pb]]; });
  fs.writeFileSync(file, JSON.stringify({ cols: ['name', 'team', 'season', 'pos', 'pick', 'av', 'ap', 'pb'], k: K, pool: rows, players: out }));
  console.log(`cfb comps: ${Object.keys(out).length} players, ${rows.length} comps`);
}
