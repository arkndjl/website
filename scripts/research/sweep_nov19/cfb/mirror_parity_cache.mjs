// Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
// Lead 1 parity where the CFBD pulls exist (the cfb- Actions cache): each cached week of CFBD plays
// (scripts/.cache/cfb/plays<season>w<week>.json, the slim shape fetch_cfb.mjs keeps) against the release mirror
// (scripts/cfb_mirror.py), play by play. No CFBD call. node mirror_parity_cache.mjs [season] [maxWeek]
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { mirrorPlays } from '../../../cfb_mirror.mjs';
import { pbpPlayers } from '../../../cfb_pbp.mjs';
const S = +(process.argv[2] || 2026), MAXW = +(process.argv[3] || 10);
const CACHE = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '.cache', 'cfb');
const slim = p => ({ g: p.gameId, o: p.offense, d: p.defense, h: p.home, q: p.period, ytg: p.yardsToGoal, dn: p.down, ds: p.distance, y: p.yardsGained, t: p.playType, x: p.playText, ppa: p.ppa, sc: p.scoring });
const keyOf = p => `${p.g}|${p.q}|${(p.x || '').replace(/\s+/g, ' ').trim()}`;
const tot = { weeks: 0, cfbd: 0, mirror: 0, both: 0, same: 0, ppaDiff: 0, typeDiff: 0, players: 0, playersSame: 0 };
for (let w = 1; w <= MAXW; w++) {
  const f = path.join(CACHE, `plays${S}w${w}.json`);
  if (!fs.existsSync(f)) { console.log(`week ${w}: no cached CFBD pull`); continue; }
  const a = JSON.parse(fs.readFileSync(f, 'utf8')), m = (mirrorPlays(S, 'regular', w) || []).map(slim);
  if (!m.length) { console.log(`week ${w}: not in the mirror`); continue; }
  const M = new Map(m.map(p => [keyOf(p), p]));
  let both = 0, same = 0, ppa = 0, type = 0;
  for (const p of a) {
    const q = M.get(keyOf(p)); if (!q) continue; both++;
    const okP = (p.ppa == null && q.ppa == null) || Math.abs((p.ppa ?? 0) - (q.ppa ?? 0)) < 5e-4, okT = p.t === q.t;
    if (!okP) ppa++; if (!okT) type++;
    if (okP && okT && p.y === q.y && p.dn === q.dn && p.ds === q.ds && p.ytg === q.ytg && p.o === q.o) same++;
  }
  // the board's own player lines from each feed
  const A = pbpPlayers(a), B = pbpPlayers(m); let np = 0, ns = 0;
  for (const [k, x] of Object.entries(A)) { if (x.car + x.tgt < 5) continue; np++; const y = B[k];
    if (y && x.car === y.car && x.tgt === y.tgt && x.rTd === y.rTd && x.cTd === y.cTd && Math.abs(x.rEpa + x.cEpa - y.rEpa - y.cEpa) < 0.01) ns++; }
  console.log(`week ${w}: CFBD ${a.length} plays, mirror ${m.length}, matched ${both}, identical ${same} (${(100 * same / a.length).toFixed(2)}%), ppa differs ${ppa}, type differs ${type}; player lines identical ${ns}/${np}`);
  tot.weeks++; tot.cfbd += a.length; tot.mirror += m.length; tot.both += both; tot.same += same; tot.ppaDiff += ppa; tot.typeDiff += type; tot.players += np; tot.playersSame += ns;
}
tot.identicalPct = tot.cfbd ? +(100 * tot.same / tot.cfbd).toFixed(2) : null; tot.playerPct = tot.players ? +(100 * tot.playersSame / tot.players).toFixed(2) : null;
tot.pass = tot.identicalPct != null && tot.identicalPct >= 99 && tot.playerPct >= 99;
console.log(JSON.stringify(tot));
