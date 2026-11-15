// Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
// League-wide forward log of the 1NT preview model: every ESEA match the run can price gets one line in
// scripts/data/esea_league_log.jsonl, repriced each run until its start time, frozen from then on, and filled with
// the result when final. Logging only; scripts/esea_league_score.py scores it into data/esea_league_log.json.
//   line: { id, div, at, t1, t2, n1, n2, f1, f2 (who each side was priced as: [[player id, weight]]),
//           in: { elo, tal, rwa, known, pelo, lf, rw }, p (faction1 wins), v (model version), logged,
//           res: null | { w, score, started, maps }, void? }
//   node scripts/esea_league_log.mjs --test
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const LOG = path.join(path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..'), 'scripts', 'data', 'esea_league_log.jsonl');
const LIVE = new Set(['ONGOING', 'READY', 'CONFIGURING', 'VOTING', 'CAPTAIN_PICK', 'PAUSED']);
const DEAD = new Set(['CANCELLED', 'ABORTED']);
const r3 = x => (x == null || !Number.isFinite(x) ? null : Math.round(x * 1000) / 1000);
const lg = p => Math.log(p / (1 - p)), ex = x => 1 / (1 + Math.exp(-x));
const clamp = p => Math.min(0.97, Math.max(0.03, p));

// the preview logit on team-level inputs: a x logit(elo .8 / talent .2 blend) + b x RWA gap
//   s1, s2: { elo, tal, rwa (sum of the priced five), known (weight with a rating), pelo }
export function price(s1, s2, W) {
  const pElo = s1.elo && s2.elo ? 1 / (1 + 10 ** (-(s1.elo - s2.elo) / W.eloScale)) : null;
  const parts = [];
  if (pElo != null) parts.push([W.elo, pElo]);
  if (pElo != null && s1.tal != null && s2.tal != null) parts.push([W.rating, ex((s1.tal - s2.tal) * W.star)]);
  const tw = parts.reduce((a, x) => a + x[0], 0);
  const lf = tw ? lg(clamp(ex(parts.reduce((a, x) => a + x[0] * lg(clamp(x[1])), 0) / tw))) : 0;
  if (s1.rwa == null || s2.rwa == null) return null;
  const rw = (s1.rwa - s2.rwa) / 100;
  return { p: ex(W.a * lf + W.b * rw), lf, rw, face: pElo != null };
}
export function readLog(file = LOG) {
  try { const by = new Map(); for (const l of fs.readFileSync(file, 'utf8').split('\n')) { if (!l.trim()) continue; try { const x = JSON.parse(l); by.set(x.id, x); } catch {} }   // a repeated id: the last line stands
    return [...by.values()]; } catch { return []; }
}
export function writeLog(lines, file = LOG) {
  lines.sort((a, b) => (a.at || 0) - (b.at || 0) || (a.id < b.id ? -1 : 1));
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, lines.map(l => JSON.stringify(l)).join('\n') + (lines.length ? '\n' : ''));
}
// feed: [{ id, div, status, at (scheduled, s), started (s), t1, t2, n1, n2, winner ('faction1' | 'faction2' | null),
//          score: [a, b] | null, maps: maps played (null = not known yet) }]
// quote(m) -> { f1, f2, in, p, v } | null for a match that can be priced now. now in seconds.
export function merge(lines, feed, quote, now, horizon = 3 * 86400) {
  const by = new Map(lines.map(l => [l.id, { ...l, res: l.res ? { ...l.res } : l.res }]));
  const stats = { priced: 0, frozen: 0, filled: 0, dropped: 0 };
  for (const m of feed) {
    const cur = by.get(m.id);
    if (DEAD.has(m.status)) { if (cur && !cur.res) { by.delete(m.id); stats.dropped++; } continue; }
    if (m.status === 'FINISHED') {
      if (!cur) continue;
      if (!cur.res) {
        if (!m.winner) continue;
        cur.res = { w: m.winner === 'faction1' ? 1 : 0, score: m.score || null, started: m.started || null, maps: m.maps ?? null };
        if (!m.started || !(cur.logged < m.started)) cur.void = 'late';
        stats.filled++;
      } else if (cur.res.maps == null && m.maps != null) cur.res.maps = m.maps;
      continue;
    }
    if (LIVE.has(m.status) || m.started || !(m.at > now)) { if (cur) stats.frozen++; continue; }
    if (m.at - now > horizon) { if (cur && !cur.res) by.delete(m.id); continue; }   // moved out of the window
    let q = null; try { q = quote(m); } catch { q = null; }
    if (!q) continue;   // an earlier line stays as it was
    by.set(m.id, { id: m.id, div: m.div, at: m.at, t1: m.t1, t2: m.t2, n1: m.n1 || null, n2: m.n2 || null,
      f1: q.f1.map(([a, w]) => [a, r3(w)]), f2: q.f2.map(([a, w]) => [a, r3(w)]), in: q.in, p: Math.round(q.p * 1e4) / 1e4, v: q.v, logged: now, res: null });
    stats.priced++;
  }
  return { lines: [...by.values()], stats };
}
// the Advanced regular season that sits above a Main group: same season and region, whatever the group word or
// prefix ("S59 NA Main A - Regular Season" -> "S59 NA Advanced - Regular Season", "ESEA S59 NA Advanced Central -
// Regular Season", "ESEA Season 59 North America Advanced Regular Season")
export function advKey(mine) {
  const m = /\bS(?:eason)?\s*0*(\d+)\s+(.*?)\s*\bMain\b/i.exec(String(mine || ''));
  return m ? { season: +m[1], region: m[2].trim().toLowerCase() } : null;
}
const REGION = { na: ['na', 'north america'], eu: ['eu', 'europe'], sa: ['sa', 'south america'], oce: ['oce', 'oceania', 'au', 'anz'] };
export function isAdvanced(name, key) {
  const nm = String(name || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
  if (!key || !/\badvanced\b/.test(nm) || !/\bregular\b/.test(nm)) return false;
  if (!new RegExp(`\\bs(?:eason)? ?0*${key.season}\\b`).test(nm)) return false;
  const want = REGION[key.region] || (key.region ? [key.region] : []);
  return !want.length || want.some(w => new RegExp(`\\b${w.replace(/[^a-z0-9]+/g, ' ')}\\b`).test(nm));
}
// a line is unchanged between runs when only `logged` moved: keep the old stamp so the file stays put
export function settle(prev, next) {
  const old = new Map(prev.map(l => [l.id, l]));
  return next.map(l => { const o = old.get(l.id); if (!o || l.res || o.res) return l;
    const strip = x => JSON.stringify({ ...x, logged: 0 }); return strip(o) === strip(l) ? o : l; });
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url) && process.argv.includes('--test')) {
  const W = { a: 0.316, b: 14.2, elo: 0.8, rating: 0.2, star: 0.48, eloScale: 600 };
  const q = () => ({ f1: [['a', 1]], f2: [['b', 1]], in: {}, p: 0.61234, v: 't' });
  const mk = (id, o) => ({ id, div: 'main', status: 'SCHEDULED', at: 2000, started: null, t1: 'x', t2: 'y', winner: null, score: null, maps: null, ...o });
  let L = merge([], [mk('m1'), mk('m2', { at: 900 }), mk('m3', { at: 1e9 })], q, 1000).lines;
  const checks = [];
  checks.push(['prices only matches ahead inside the window', L.length === 1 && L[0].id === 'm1' && L[0].p === 0.6123 && L[0].logged === 1000]);
  let L2 = merge(L, [mk('m1', { status: 'ONGOING', started: 1990 })], () => ({ ...q(), p: 0.9 }), 1995).lines;
  checks.push(['freezes at the start', L2[0].p === 0.6123 && L2[0].logged === 1000]);
  let L3 = merge(L2, [mk('m1', { status: 'FINISHED', started: 1990, winner: 'faction2', score: [9, 13], maps: 1 })], q, 5000).lines;
  checks.push(['fills the result', L3[0].res.w === 0 && L3[0].res.maps === 1 && !L3[0].void]);
  let L4 = merge(L, [mk('m1', { status: 'FINISHED', started: 950, winner: 'faction1' })], q, 5000).lines;
  checks.push(['a match played before its line is void', L4[0].void === 'late']);
  checks.push(['cancelled drops out', merge(L, [mk('m1', { status: 'CANCELLED' })], q, 1500).lines.length === 0]);
  checks.push(['a moved match is repriced', merge(L, [mk('m1', { at: 9000 })], () => ({ ...q(), p: 0.5 }), 1500).lines[0].p === 0.5]);
  checks.push(['never backfills a finished match', merge([], [mk('m9', { status: 'FINISHED', started: 10, winner: 'faction1' })], q, 5000).lines.length === 0]);
  const a = price({ elo: 2600, tal: 3.5, rwa: 2 }, { elo: 2500, tal: 3, rwa: -3 }, W), b = price({ elo: null, rwa: 2 }, { elo: 2500, rwa: -3 }, W);
  const pe = 1 / (1 + 10 ** (-100 / 600)), lf = lg(ex(0.8 * lg(pe) + 0.2 * lg(ex(0.24))));
  checks.push(['price is the preview logit', Math.abs(a.p - ex(0.316 * lf + 14.2 * 0.05)) < 1e-12 && Math.abs(b.p - ex(14.2 * 0.05)) < 1e-12 && !b.face]);
  checks.push(['no rating, no price', price({ elo: 1, rwa: null }, { elo: 1, rwa: 0 }, W) === null]);
  const s = settle(L, merge(L, [mk('m1')], q, 1200).lines);
  checks.push(['an unchanged line keeps its stamp', s[0].logged === 1000]);
  const K = advKey('S59 NA Main A - Regular Season');
  checks.push(['advanced key from the Main name', K && K.season === 59 && K.region === 'na' && advKey('ESEA S54 NA Main Central - Regular Season').season === 54 && advKey('x') === null]);
  checks.push(['advanced names match', ['S59 NA Advanced - Regular Season', 'S59 NA Advanced A - Regular Season', 'ESEA S59 NA Advanced Central - Regular Season',
    'ESEA Season 59 North America Advanced: Regular Season', 's59 na advanced regular season'].every(x => isAdvanced(x, K))]);
  checks.push(['other seasons, regions, stages and divisions do not', !['S58 NA Advanced - Regular Season', 'S59 EU Advanced - Regular Season', 'S59 NA Advanced - Playoffs',
    'S59 NA Main B - Regular Season', 'S590 NA Advanced - Regular Season', 'S59 SA Advanced - Regular Season', ''].some(x => isAdvanced(x, K))]);
  let bad = 0; for (const [n, ok] of checks) if (!ok) { bad++; console.log('FAIL', n); }
  console.log(bad ? `${bad} failed` : `esea_league_log: ${checks.length} checks ok`);
  process.exit(bad ? 1 : 0);
}
