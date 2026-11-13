// Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
// season-end opponent-adjusted EPA a play by team (offense, defense), every history season: node unit_dump.mjs out.json
import zlib from 'node:zlib'; import fs from 'node:fs';
import { _internals as I } from '../../cfb_model.mjs';
const ROOT = new URL('../../../', import.meta.url).pathname;
const data = JSON.parse(zlib.gunzipSync(fs.readFileSync(ROOT + 'scripts/data/cfb_hist_md.json.gz')));
const venues = JSON.parse(fs.readFileSync(ROOT + 'data/cfb_venues.json', 'utf8'));
const out = {};
for (const S of data.seasons) {
  const nameId = {}, fbs = new Set(), name = {};
  for (const g of data.games[S]) { g.homeId = String(g.homeId); g.awayId = String(g.awayId); nameId[g.homeTeam] = g.homeId; nameId[g.awayTeam] = g.awayId; name[g.homeId] = g.homeTeam; name[g.awayId] = g.awayTeam;
    if (g.homeClassification === 'fbs') fbs.add(g.homeId); if (g.awayClassification === 'fbs') fbs.add(g.awayId); }
  const geo = I.places(venues.venues, venues.teamsFbs, data.games[S]);
  const rows = I.prepare([S], data, geo), gameById = Object.fromEntries(rows.map(r => [r.id, r]));
  const eff = I.effObs(data.adv[S], nameId, gameById, fbs, {}, {});
  const obs = eff.filter(r => r.plays > 0 && r.ppa != null).map(r => ({ o: r.t, d: r.opp, y: r.ppa, w: r.plays / 65, s: r.s }));
  const A = I.adjust(obs, {}, 1.5);
  out[S] = Object.fromEntries([...fbs].map(t => [name[t], { o: A.O[t] ?? 0, d: -(A.D[t] ?? 0) }]));
}
fs.writeFileSync(process.argv[2], JSON.stringify(out));
console.log(Object.keys(out).map(S => S + ':' + Object.keys(out[S]).length).join(' '));
