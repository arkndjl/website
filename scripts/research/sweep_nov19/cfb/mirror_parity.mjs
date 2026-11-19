// Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
// Lead 1 parity: mirror plays (weeks 1-10) through the board's own reducers against the CFBD-built board files of the
// week-10 run. node mirror_parity.mjs <ref dir with cfb-all.json, cfb-detail.json, cfb_teams.json>
import fs from 'node:fs';
import path from 'node:path';
import { pbpByGame, pbpKey } from '../../../cfb_pbp.mjs';
import { mirrorPlays, mirrorIndex } from '../../../cfb_mirror.mjs';
import { teamKey } from '../../../names.mjs';
const REF = process.argv[2], S = 2026;
const all = JSON.parse(fs.readFileSync(path.join(REF, 'cfb-all.json'))), det = JSON.parse(fs.readFileSync(path.join(REF, 'cfb-detail.json')));
const teams = JSON.parse(fs.readFileSync(path.join(REF, 'cfb_teams.json')));
const raw = [];
for (let w = 1; w <= 10; w++) raw.push(...(mirrorPlays(S, 'regular', w) || []));
const plays = raw.map(p => ({ g: p.gameId, o: p.offense, d: p.defense, h: p.home, q: p.period, ytg: p.yardsToGoal, dn: p.down, ds: p.distance, y: p.yardsGained, t: p.playType, x: p.playText, ppa: p.ppa, sc: p.scoring,
  sm: p.offenseScore != null && p.defenseScore != null ? p.offenseScore - p.defenseScore : null }));
// ---- 1a player strings
const G = pbpByGame(plays), P = {};
const F = ['car', 'ry', 'rEpa', 'rExp', 'rzCar', 'rTd', 'tgt', 'rec', 'recY', 'cEpa', 'cExp', 'rzTgt', 'cTd'];
for (const [k, a] of Object.entries(G)) { const t = {}; for (const f of F) t[f] = 0; for (const x of Object.values(a._byGame)) for (const f of F) t[f] += x[f]; P[teamKey(a.team) + '|' + a.key] = t; }
const sg = (x, d) => (x >= 0 ? '+' : '') + x.toFixed(d);
const ai = Object.fromEntries(all.cols.map((c, i) => [c, i])), di = Object.fromEntries(det.cols.map((c, i) => [c, i]));
const out = { rb: { n: 0, same: 0, epaOnly: 0, miss: 0, bad: [] }, wr: { n: 0, same: 0, miss: 0, bad: [] } };
all.rows.forEach((r, i) => {
  const rep = det.rows[i][di.report]; if (!rep || r[ai.div] === 'FCS') return;
  const lines = [...(rep.plus || []), ...(rep.minus || [])];
  const rb = lines.find(s => /^EPA\/carry /.test(s)), wr = lines.find(s => /^20\+ yd catch /.test(s));
  if (!rb && !wr) return;
  const pb = P[teamKey(r[ai.team]) + '|' + pbpKey(r[ai.name])];
  if (rb) { const o = out.rb; o.n++;
    if (!pb || !pb.car) { o.miss++; o.bad.push([r[ai.name], r[ai.team], rb, null]); return; }
    const mine = `EPA/carry ${sg(pb.rEpa / pb.car, 2)}; 15+ yd ${Math.round(100 * pb.rExp / pb.car)}%; ${pb.rTd} TD (${pb.rzCar} RZ car)`;
    const tail = s => s.replace(/^EPA\/carry \S+; /, ''), e = s => +s.match(/^EPA\/carry (\S+);/)[1];
    if (mine === rb) o.same++; else if (tail(mine) === tail(rb) && Math.abs(e(mine) - e(rb)) <= 0.0101) { o.same++; o.epaOnly++; } else o.bad.push([r[ai.name], r[ai.team], rb, mine]); }
  if (wr) { const o = out.wr; o.n++;
    if (!pb || !pb.tgt) { o.miss++; o.bad.push([r[ai.name], r[ai.team], wr, null]); return; }
    const mine = `20+ yd catch ${Math.round(100 * pb.cExp / pb.tgt)}% of tgt; ${pb.cTd} TD (${pb.rzTgt} RZ tgt)`;
    if (mine === wr) o.same++; else o.bad.push([r[ai.name], r[ai.team], wr, mine]); }
});
for (const o of Object.values(out)) { o.pct = +(100 * o.same / o.n).toFixed(2); o.bad = o.bad.slice(0, 12); }
// ---- 1b team style (CFBD season advanced, garbage time out)
const GARB = { 2: 38, 3: 28, 4: 22 };
const T = {};
const get = t => (T[teamKey(t)] ||= { o: { n: 0, s: 0, ppa: 0, pn: 0, ex: 0, exn: 0, rush: 0, pass: 0 }, d: { n: 0, s: 0, ppa: 0, pn: 0 } });
for (const p of plays) {
  const t = p.t || '';
  const rush = /^Rush|Rushing Touchdown/.test(t), pass = /^Pass|Passing Touchdown|^Sack|Interception/.test(t);
  if (!rush && !pass) continue;
  if (!(p.dn >= 1 && p.dn <= 4)) continue;
  if (p.sm != null && Math.abs(p.sm) > (GARB[p.q] ?? 99)) continue;
  if (typeof p.ppa !== 'number') continue;
  const need = p.dn === 1 ? 0.5 * p.ds : p.dn === 2 ? 0.7 * p.ds : p.ds;
  const ok = (p.sc && /Touchdown/.test(t) && !/Interception|Fumble/.test(t)) || (p.y ?? 0) >= need ? 1 : 0;
  const o = get(p.o).o, d = get(p.d).d;
  o.n++; o.s += ok; o.ppa += p.ppa; if (ok) { o.ex += p.ppa; o.exn++; } if (rush) o.rush++; else o.pass++;
  d.n++; d.s += ok; d.ppa += p.ppa;
}
const fields = { run: x => x.o.rush / (x.o.rush + x.o.pass), osr: x => x.o.s / x.o.n, oepa: x => x.o.ppa / x.o.n, dsr: x => x.d.s / x.d.n, depa: x => x.d.ppa / x.d.n, xpl: x => x.o.ex / x.o.exn };
const st = Object.fromEntries(Object.keys(fields).map(f => [f, { n: 0, within: 0, maxDiff: 0, meanDiff: 0, r: null, xs: [], ys: [] }]));
for (const t of teams.teams) {
  if (!t.style) continue;
  const m = T[teamKey(t.team)] || T[teamKey(t.full)]; if (!m) { for (const f of Object.keys(fields)) st[f].n++; continue; }
  for (const [f, fn] of Object.entries(fields)) { const a = fn(m), b = t.style[f]; if (b == null || !isFinite(b)) continue; const s = st[f]; s.n++; const d = Math.abs(a - b); if (d <= 0.0101) s.within++; s.maxDiff = Math.max(s.maxDiff, d); s.meanDiff += a - b; s.xs.push(a); s.ys.push(b); }
}
const corr = (x, y) => { const n = x.length, mx = x.reduce((a, b) => a + b, 0) / n, my = y.reduce((a, b) => a + b, 0) / n; let sxy = 0, sxx = 0, syy = 0; x.forEach((v, i) => { sxy += (v - mx) * (y[i] - my); sxx += (v - mx) ** 2; syy += (y[i] - my) ** 2; }); return sxy / Math.sqrt(sxx * syy); };
for (const s of Object.values(st)) { s.pct = +(100 * s.within / s.n).toFixed(1); s.meanDiff = +(s.meanDiff / s.xs.length).toFixed(4); s.maxDiff = +s.maxDiff.toFixed(3); s.r = +corr(s.xs, s.ys).toFixed(4); delete s.xs; delete s.ys; }
// ---- 1d coverage
const ix = mirrorIndex()[S].weeks; let games = 0; for (let w = 1; w <= 10; w++) games += ix[`regular|${w}`].games.length;
const res = { plays: plays.length, mirrorGames: games, refGames: teams.games, strings: out, style: st };
console.log(JSON.stringify(res, null, 1));
if (process.argv[3]) fs.writeFileSync(process.argv[3], JSON.stringify(res, null, 1));
