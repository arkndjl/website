// Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
// Who is priced in a 1NT / ESEA match. The page cannot know the five who will play, so a side is priced as a
// weighted set of players (scripts/esea_standin_research.py predicted_fives is the same code in Python;
// `python3 scripts/esea_five_research.py --parity` checks the two agree):
//   live      top 5 by the team's league maps in the prior 90 days, last 30 double, equal weights
//   expected  top 7 by the same counts, weighted by share
//   sharp     top 7 by same-season maps, the team's latest map x3, weighted by share (under 5 players: expected)
// Held S58-S59 on the RWA gap (n 2,066, by match day): expected vs live -.0029 (t -2.7), sharp vs expected
// -.0062 (t -3.2); the five who actually played still beats sharp by .012, which no preview can have.
//   node scripts/esea_five.mjs --test      # self-test on a toy history
//   node scripts/esea_five.mjs --parity N  # the last N archive matches as JSON (fives, weighted player Elo gap)
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import { fileURLToPath } from 'node:url';

const DAY = 86400;
export const FIVE_V = 'sharp7';
export const PELO = { K: 128, Kmin: 26, n0: 50, span: 0.5, muNew: -100, gap: 100, a: 0.75, b: 4.8 };
export const PELO_DIV = { 'open9-10': -2, 'open1-8': -2, open: -2, intermediate: -1, main: 0, advanced: 1 };

function weightsOf(apps, last, top, share) {
  const order = [...apps.keys()].sort((a, b) => apps.get(b) - apps.get(a) || last.get(b) - last.get(a) || (a < b ? -1 : a > b ? 1 : 0)).slice(0, top);
  if (!share) return order.map(q => [q, 1 / order.length]);
  const tot = order.reduce((s, q) => s + apps.get(q), 0);
  return order.map(q => [q, apps.get(q) / tot]);
}
// hist: the team's prior league maps in time order, [{ at (s), season, five: [player ids] }]; at = the match time (s)
export function fiveWeights(hist, at, season) {
  const apps = new Map(), last = new Map(), sapps = new Map(), slast = new Map();
  const ssn = hist.filter(x => x.season === season);
  hist.forEach((x, j) => {
    if (at - x.at > 90 * DAY) return;
    const w = at - x.at <= 30 * DAY ? 2 : 1;
    for (const q of x.five) { apps.set(q, (apps.get(q) || 0) + w); last.set(q, j); }
  });
  ssn.forEach((x, j) => {
    const w = j === ssn.length - 1 ? 3 : 1;
    for (const q of x.five) { sapps.set(q, (sapps.get(q) || 0) + w); slast.set(q, j); }
  });
  const ok = apps.size >= 5;
  const live = apps.size ? weightsOf(apps, last, 5, false) : null;
  const expected = ok ? weightsOf(apps, last, 7, true) : live;
  const sharp = sapps.size >= 5 ? weightsOf(sapps, slast, 7, true) : expected;
  return { ok, live, expected, sharp };
}
// keep only allowed players (a current roster) and renormalise; null when fewer than `min` are left
export function restrict(ws, allowed, min = 4) {
  const v = (ws || []).filter(([q]) => allowed.has(q)); if (v.length < min) return null;
  const tot = v.reduce((s, [, w]) => s + w, 0);
  return v.map(([q, w]) => [q, w / tot]);
}
export const wmean = (ws, f) => ws.reduce((s, [q, w]) => s + w * f(q), 0);

// the research archive as games in time order (the filters of scripts/esea_standin_research.py load())
export function archiveGames(arch) {
  const games = [];
  for (const m of arch?.matches || []) {
    if (!m.at || !['faction1', 'faction2'].includes(m.winner)) continue;
    const maps = (m.maps || []).filter(mp => mp.s1 != null && mp.s2 != null && mp.p1?.length && mp.p2?.length);
    if (!maps.length) continue;
    games.push({ id: m.id, at: m.at, season: m.season, dr: PELO_DIV[String(m.div).toLowerCase()] ?? 0, t1: m.f1?.id, t2: m.f2?.id,
      maps: maps.map(mp => ({ a: mp.p1.map(x => x[0]), b: mp.p2.map(x => x[0]), s1: mp.s1, s2: mp.s2 })) });
  }
  return games;
}
// round-share player Elo played forward over games (sorted here); before(g, peek) runs ahead of each game's update
export function replayElo(games, before = null) {
  const r = new Map(), n = new Map();
  games.sort((x, y) => x.at - y.at);
  const get = (q, g) => { if (!r.has(q)) r.set(q, PELO.gap * g.dr + PELO.muNew); return r.get(q); };
  const team = (ids, g) => ids.reduce((s, q) => s + get(q, g), 0) / (ids.length || 1);
  for (const g of games) {
    if (before) before(g, q => (r.has(q) ? r.get(q) : PELO.gap * g.dr + PELO.muNew));
    for (const mp of g.maps) {
      if (!mp.a.length || !mp.b.length) continue;
      const e = 1 / (1 + 10 ** (-(team(mp.a, g) - team(mp.b, g)) / 400));
      const rs = mp.s1 / ((mp.s1 + mp.s2) || 24), sc = Math.min(1, Math.max(0, (rs - 0.5) / PELO.span * 0.5 + 0.5));
      for (const [ids, sg] of [[mp.a, 1], [mp.b, -1]]) for (const q of ids) {
        const k = PELO.Kmin + (PELO.K - PELO.Kmin) * Math.exp(-(n.get(q) || 0) / PELO.n0);
        r.set(q, get(q, g) + sg * k * (sc - e));
      }
      for (const q of [...mp.a, ...mp.b]) n.set(q, (n.get(q) || 0) + 1);
    }
  }
  return { r, n, maps: games.reduce((s, g) => s + g.maps.length, 0) };
}
// team id -> its league maps in time order, from games (sorted by at)
export function teamHistory(games) {
  const h = new Map();
  for (const g of [...games].sort((x, y) => x.at - y.at)) for (const mp of g.maps) {
    if (g.t1) { if (!h.has(g.t1)) h.set(g.t1, []); h.get(g.t1).push({ at: g.at, season: g.season, five: mp.a.slice(0, 5) }); }
    if (g.t2) { if (!h.has(g.t2)) h.set(g.t2, []); h.get(g.t2).push({ at: g.at, season: g.season, five: mp.b.slice(0, 5) }); }
  }
  return h;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
  if (process.argv.includes('--parity')) {
    const N = +process.argv[process.argv.indexOf('--parity') + 1] || 300;
    const games = archiveGames(JSON.parse(zlib.gunzipSync(fs.readFileSync(path.join(ROOT, 'research', 'esea_matches.json.gz')))));
    games.sort((x, y) => x.at - y.at);
    const keep = new Set(games.slice(-N).map(g => g.id)), hist = new Map(), out = {};
    const H = t => { if (!hist.has(t)) hist.set(t, []); return hist.get(t); };
    const E = replayElo(games, (g, peek) => {
      if (keep.has(g.id)) {
        const a = fiveWeights(H(g.t1), g.at, g.season), b = fiveWeights(H(g.t2), g.at, g.season);
        out[g.id] = { ok: a.ok && b.ok, live: [a.live, b.live], expected: [a.expected, b.expected], sharp: [a.sharp, b.sharp],
          gap: a.sharp && b.sharp ? (wmean(a.sharp, peek) - wmean(b.sharp, peek)) / 400 : null };
      }
      for (const mp of g.maps) { H(g.t1).push({ at: g.at, season: g.season, five: mp.a.slice(0, 5) }); H(g.t2).push({ at: g.at, season: g.season, five: mp.b.slice(0, 5) }); }
    });
    let sum = 0; for (const v of E.r.values()) sum += v;
    process.stdout.write(JSON.stringify({ matches: out, players: E.r.size, eloSum: sum }));
  } else {
    const h = [];
    const add = (at, season, five) => h.push({ at, season, five });
    for (let i = 0; i < 6; i++) add(i * 7 * DAY, 1, ['a', 'b', 'c', 'd', i % 2 ? 'e' : 'f']);
    add(50 * DAY, 2, ['a', 'b', 'c', 'd', 'g']);
    const w = fiveWeights(h, 60 * DAY, 2), w1 = fiveWeights(h, 45 * DAY, 1);
    const near = (x, y) => Math.abs(x - y) < 1e-12, sum = ws => ws.reduce((s, [, x]) => s + x, 0);
    const checks = [
      ['live is five equal weights', w.live.length === 5 && w.live.every(([, x]) => near(x, 0.2))],
      ['expected sums to 1 over at most 7', near(sum(w.expected), 1) && w.expected.length === 7],
      ['sharp falls back with under 5 same-season players... has 5 here', w.sharp.length === 5 && near(sum(w.sharp), 1)],
      ['latest map counts triple', near(w1.sharp.find(([q]) => q === 'e').at(1), (2 + 3) / (4 * 8 + 3 + 5))],
      ['restrict renormalises', near(sum(restrict(w.expected, new Set(['a', 'b', 'c', 'd']))), 1)],
      ['restrict needs four', restrict(w.expected, new Set(['a', 'b'])) === null],
      ['no history', fiveWeights([], 0, 1).live === null],
    ];
    let bad = 0;
    for (const [name, ok] of checks) { if (!ok) { bad++; console.log('FAIL', name); } }
    console.log(bad ? `${bad} failed` : `esea_five: ${checks.length} checks ok`);
    process.exit(bad ? 1 : 0);
  }
}
