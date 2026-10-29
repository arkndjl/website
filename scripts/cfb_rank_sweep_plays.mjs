// Team-game play stats for the CFB ARK Ranking sweep (scripts/cfb_rank_sweep.py), from the ESPN play-by-play cache
// (scripts/cfb_espn_pbp.py) on the model's own EP curve (scripts/data/cfb_hist_md.json.gz ep). One row per team-game
// (the offense's view): scrimmage plays with and without garbage time, pass and rush EPA, fumbles and interceptions
// (count, EPA, lost), havoc allowed (tackles for loss, sacks, takeaways), and EPA weighted by leverage (4 wp (1 - wp)
// from score and clock alone, as scripts/espn_control.py).
//   node scripts/cfb_rank_sweep_plays.mjs [first] [last]    -> scripts/.cache/cfb/rank_sweep_plays.json.gz
import zlib from 'node:zlib';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadSeason, loadGame, flat, epa, isScrim, isRush, GARBAGE } from './cfb_espn_md.mjs';
import { phi } from './cfb_model.mjs';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const W = JSON.parse(zlib.gunzipSync(fs.readFileSync(path.join(ROOT, 'scripts', 'data', 'cfb_hist_md.json.gz')))).ep;
const [a = 2015, b = 2026] = process.argv.slice(2).map(Number);
const left = p => {
  const [m, s] = String(p.c || '0:00').split(':').map(Number), q = Math.min(4, p.q || 1);
  return Math.max(0, ((4 - q) * 900 + (m || 0) * 60 + (s || 0)) / 3600);
};
const out = [];
for (let S = a; S <= b; S++) {
  let n = 0;
  for (const g of loadSeason(S)) {
    if (!g.done || g.grp !== 'fbs' || g.hp == null) continue;
    const G = loadGame(g.id); if (!G?.drives?.length) continue;
    const F = flat(G), T = {};
    const row = t => (T[t] ||= { g: g.id, S, date: g.date, t, d: t === g.h ? g.a : g.h, s: g.n ? 0 : t === g.h ? 1 : -1, pts: t === g.h ? g.hp : g.ap,
      n: 0, e: 0, nAll: 0, eAll: 0, pn: 0, pe: 0, rn: 0, re: 0, fum: 0, fumE: 0, fumL: 0, int: 0, intE: 0, tfl: 0, sack: 0, lw: 0, lwE: 0, sr: 0 });
    F.forEach((p, i) => {
      if (!p.st || !isScrim(p) || (p.st !== g.h && p.st !== g.a)) return;
      const nx = F.slice(i + 1, i + 4).find(q => q.dn >= 1 && q.st), v = epa(W, p, nx);
      if (v == null) return;
      const r = row(p.st), txt = (p.t || '') + ' ' + (p.x || '');
      r.nAll++; r.eAll += v;
      const L = left(p), wp = phi((p.sm ?? 0) / (16 * Math.sqrt(Math.max(0.02, L)))), lw = Math.max(0.05, 4 * wp * (1 - wp));
      r.lw += lw; r.lwE += lw * v;
      if (p.sm != null && Math.abs(p.sm) > (GARBAGE[p.q] ?? 99)) return;
      r.n++; r.e += v;
      const rush = isRush(p), sack = /sack/i.test(txt);
      if (rush) { r.rn++; r.re += v; } else { r.pn++; r.pe += v; }
      if (/fumble/i.test(txt)) { r.fum++; r.fumE += v; if (p.to || /Fumble Recovery \(Opponent\)/.test(p.t || '')) r.fumL++; }
      if (/Interception/i.test(p.t || '') || /intercepted/i.test(p.x || '')) { r.int++; r.intE += v; }
      if (sack) r.sack++; else if (rush && (p.y ?? 0) < 0) r.tfl++;
      const need = p.dn === 1 ? 0.5 * p.ds : p.dn === 2 ? 0.7 * p.ds : p.ds;
      if (p.ptsOff >= 6 || (!p.to && (p.y ?? 0) >= need)) r.sr++;
    });
    for (const r of Object.values(T)) { for (const k of ['e', 'eAll', 'pe', 're', 'fumE', 'intE', 'lw', 'lwE']) r[k] = Math.round(r[k] * 1e3) / 1e3; out.push(r); }
    n++;
  }
  console.log(S, n, 'games');
}
const f = path.join(ROOT, 'scripts', '.cache', 'cfb', 'rank_sweep_plays.json.gz');
fs.writeFileSync(f, zlib.gzipSync(JSON.stringify(out)));
console.log(out.length, 'team-games ->', f);
