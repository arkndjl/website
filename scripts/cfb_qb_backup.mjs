// Backup QBs in the college game model: how much a QB1 absence costs, and how to value the backup, on 2015-26 ESPN
// history (free; scripts/cfb_espn_pbp.py caches, scripts/cfb_espn_md.mjs history). The live charge (scripts/cfb_teams.mjs
// side()): P(out) x (backup EPA a play - starter's) x 38 plays, each QB's season EPA a play shrunk toward replacement
// (-0.05) by 150 plays (scripts/cfb_model.mjs qbTable), so a backup with few plays sits at replacement whoever he is.
//   node scripts/cfb_qb_backup.mjs build [first] [last]   # QB EPA by game from ESPN play-by-play -> scripts/.cache/cfb/qb_epa.json.gz
//   node scripts/cfb_qb_backup.mjs test [espn_md.json.gz]  # the backtest -> data/cfb_qb_backup.json
//   node scripts/cfb_qb_backup.mjs check <cfbd md.json.gz> # ESPN QB EPA against CFBD's season QB PPA (same ids)
//   node scripts/cfb_qb_backup.mjs fv                      # each QB's prior moved by his 247 composite (recruit FV input;
//                                                          # python3 scripts/fv_games_research.py qb247 first) -> data/fv_games_research.json
// The test: each team's QB1 before the game (most QB plays in its earlier games this season, 60 or more) and whether
// he started (most QB plays in this one; so an oracle, as the live charge is P(out) x cost). The cost goes onto the
// walk-forward model's margin (ESPN-only, pooled: scripts/cfb_hist_backtest.mjs) as the live charge does, at weight 1;
// tune 2016-20, held out 2021-26, paired per game with clustered errors.
import zlib from 'node:zlib';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadSeason, loadGame, qbPlays } from './cfb_espn_md.mjs';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const BOX = path.join(ROOT, 'scripts', '.cache', 'cfb', 'espn_hist', 'box');
const QBP = path.join(ROOT, 'scripts', '.cache', 'cfb', 'qb_epa.json.gz');
const mode = process.argv[2];

if (mode === 'build') {
  const [A = 2015, B = 2026] = process.argv.slice(3).map(Number);
  const W = JSON.parse(zlib.gunzipSync(fs.readFileSync(path.join(ROOT, 'scripts', 'data', 'cfb_hist_md.json.gz')))).ep;
  const out = { ep: 'cfb_hist_md.json.gz', games: {}, names: {} };
  for (let S = A; S <= B; S++) {
    let n = 0;
    for (const g of loadSeason(S)) {
      if (!g.done || g.grp !== 'fbs') continue;
      const G = loadGame(g.id), bp = path.join(BOX, `${g.id}.json`);
      if (!G?.drives?.length || !fs.existsSync(bp)) continue;
      const box = JSON.parse(fs.readFileSync(bp, 'utf8'));
      const q = qbPlays(G, box, W);
      for (const P of Object.values(box)) for (const [aid, s] of Object.entries(P)) if (s.att > 0) out.names[aid] = s.n;
      out.games[g.id] = { S, date: g.date, q: Object.fromEntries(Object.entries(q).map(([t, P]) => [t, Object.fromEntries(Object.entries(P).map(([a, v]) => [a, [v[0], Math.round(v[1] * 1000) / 1000]]))])) };
      n++;
    }
    console.log(S, n, 'games');
  }
  fs.writeFileSync(QBP, zlib.gzipSync(JSON.stringify(out)));
  console.log('wrote', QBP);
  process.exit(0);
}

const mean = xs => xs.reduce((a, b) => a + b, 0) / Math.max(1, xs.length);
const r2 = x => Math.round(x * 100) / 100, r3 = x => Math.round(x * 1000) / 1000, r4 = x => Math.round(x * 1e4) / 1e4;

if (mode === 'check') {
  // season EPA a play by QB, ESPN against CFBD (excludeGarbageTime), by athlete id
  const cf = JSON.parse(zlib.gunzipSync(fs.readFileSync(process.argv[3]))).ppaqb || [];
  const Q = JSON.parse(zlib.gunzipSync(fs.readFileSync(QBP)));
  const S = cf[0]?.season, acc = {};
  for (const g of Object.values(Q.games)) if (g.S === S) for (const P of Object.values(g.q)) for (const [a, v] of Object.entries(P)) { const o = (acc[a] ||= [0, 0]); o[0] += v[0]; o[1] += v[1]; }
  const pairs = [];
  const seen = new Set();
  for (const q of cf) {
    if (seen.has(q.id)) continue; seen.add(q.id);
    const e = acc[q.id], avg = q.averagePPA?.all, tot = q.totalPPA?.all;
    if (!e || !avg || tot == null) continue;
    const n = Math.round(tot / avg);
    if (n >= 100 && e[0] >= 100) pairs.push([avg, e[1] / e[0], n, e[0]]);
  }
  const corr = (a, b) => { const ma = mean(a), mb = mean(b); let sab = 0, sa = 0, sb = 0; a.forEach((x, i) => { sab += (x - ma) * (b[i] - mb); sa += (x - ma) ** 2; sb += (b[i] - mb) ** 2; }); return sab / Math.sqrt(sa * sb); };
  const res = { season: S, qbs: pairs.length, rEpa: r3(corr(pairs.map(p => p[0]), pairs.map(p => p[1]))), rPlays: r3(corr(pairs.map(p => p[2]), pairs.map(p => p[3]))),
    meanCfbd: r3(mean(pairs.map(p => p[0]))), meanEspn: r3(mean(pairs.map(p => p[1]))), playsRatio: r3(mean(pairs.map(p => p[3] / p[2]))) };
  console.log(JSON.stringify(res));
  const f = path.join(ROOT, 'data', 'cfb_qb_backup.json'), j = fs.existsSync(f) ? JSON.parse(fs.readFileSync(f, 'utf8')) : {};
  j.check = res; fs.writeFileSync(f, JSON.stringify(j, null, 1));
  process.exit(0);
}

if (mode !== 'test' && mode !== 'fv') { console.log('usage: build | test | check | fv'); process.exit(1); }

// ---- the test --------------------------------------------------------------------------------------------
process.env.ONLYSHIP = '1';
process.env.BT_OUT ||= path.join(ROOT, 'scripts', '.cache', 'cfb', 'hist_bt_scratch.json');
process.argv.splice(2, 1);   // cfb_hist_backtest.mjs reads its md path from argv[2]
const BT = await import('./cfb_hist_backtest.mjs');
const { _internals: I, phi } = await import('./cfb_model.mjs');
const { paired } = await import('./harness.mjs');
const { rows, chain, walkAll, predict, SEASONS } = BT;
const Q = JSON.parse(zlib.gunzipSync(fs.readFileSync(QBP)));
const ROSTER = JSON.parse(fs.readFileSync(path.join(ROOT, 'scripts', 'data', 'cfb_roster_feats.json'), 'utf8')).feats || {};
const inTune = S => S >= 2016 && S <= 2020, inHold = S => S >= 2021;

I.setExtra(['p4', 'aggr']);
const base = predict(walkAll(chain('roster', 'pooled')));
I.setExtra([]);
const byId = Object.fromEntries(rows.map(r => [String(r.id), r]));

// per team-game: QB1 before the game, the starter, QB2 before the game, and each one's plays and EPA so far (this
// season and last season, with any team) for the valuation specs
const ctx = {};
{
  const cur = {}, teamPlays = {};   // season|aid -> [plays, EPA]; season|team -> aid -> plays
  const games = Object.entries(Q.games).sort((a, b) => a[1].date.localeCompare(b[1].date));
  for (const [id, g] of games) {
    for (const [t, P] of Object.entries(g.q)) {
      const tp = (teamPlays[g.S + '|' + t] ||= {});
      const order = Object.entries(tp).sort((a, b) => b[1] - a[1]);
      const q1 = order[0]?.[0], q2 = order[1]?.[0];
      const st = Object.entries(P).sort((a, b) => b[1][0] - a[1][0])[0]?.[0];
      const snap = a => a && { aid: a, cur: [...(cur[g.S + '|' + a] || [0, 0])], prev: [...(cur[(g.S - 1) + '|' + a] || [0, 0])] };
      if (q1 && st && (tp[q1] || 0) >= 60) ctx[id + '|' + t] = { S: g.S, t, out: st !== q1, q1: snap(q1), st: snap(st), q2: q2 ? snap(q2) : null, stIsQ2: st === q2 };
      for (const [a, v] of Object.entries(P)) {
        tp[a] = (tp[a] || 0) + v[0];
        const c = (cur[g.S + '|' + a] ||= [0, 0]); c[0] += v[0]; c[1] += v[1];
      }
    }
  }
}
const outs = Object.values(ctx).filter(c => c.out);
console.log(`${Object.keys(ctx).length} team-games with a QB1 (60+ plays), ${outs.length} with QB1 not starting (${outs.filter(c => c.stIsQ2).length} by QB2)`);

// a QB's value: (EPA this season + w x last season's + k x prior) / (plays this season + w x last season's + k)
// fv mode: plus b x (his 247 composite - .85), unrated recruits at sp.u
const C247 = mode === 'fv' ? JSON.parse(fs.readFileSync(path.join(ROOT, 'scripts', '.cache', 'cfb', 'qb247.json'), 'utf8')) : {};
const val = (x, sp, tal) => {
  if (!x) return sp.repl;
  const pr = sp.repl + (sp.tal || 0) * (tal ?? 0) + (sp.b || 0) * ((C247[x.aid] ?? sp.u ?? 0.85) - 0.85), w = sp.prevW || 0;
  return (x.cur[1] + w * x.prev[1] + sp.k * pr) / (x.cur[0] + w * x.prev[0] + sp.k);
};
// the cost for one side, in points (negative when the starter is worse than QB1): backup = the man who started
// (oracle) or QB2 before the game (what the live table names)
const cost = (c, sp, who = 'st') => {
  if (!c?.out) return 0;
  const tal = ROSTER[c.S]?.[c.t]?.tal247 ?? 0;
  const vb = Math.max(val(c[who], sp, tal), sp.floor ?? -0.25), v1 = val(c.q1, sp, tal);
  return Math.max(-(sp.cap ?? 6), (vb - v1) * (sp.plays ?? 38)) * (sp.scale ?? 1);
};
// sigma per season from the base predictions (m / Phi^-1(ph)) so the charge moves win probability as live
const ninv = p => { // Acklam
  const a = [-39.6968302866538, 220.946098424521, -275.928510446969, 138.357751867269, -30.6647980661472, 2.50662827745924],
    b = [-54.4760987982241, 161.585836858041, -155.698979859887, 66.8013118877197, -13.2806815528857],
    c = [-0.00778489400243029, -0.322396458041136, -2.40075827716184, -2.54973253934373, 4.37466414146497, 2.93816398269878],
    d = [0.00778469570904146, 0.32246712907004, 2.445134137143, 3.75440866190742];
  const q = p < 0.02425 ? Math.sqrt(-2 * Math.log(p)) : p > 1 - 0.02425 ? Math.sqrt(-2 * Math.log(1 - p)) : null;
  if (q != null) { const v = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1); return p < 0.5 ? v : -v; }
  const r = p - 0.5, s = r * r; return (((((a[0] * s + a[1]) * s + a[2]) * s + a[3]) * s + a[4]) * s + a[5]) * r / (((((b[0] * s + b[1]) * s + b[2]) * s + b[3]) * s + b[4]) * s + 1);
};
const sig = {};
for (const S of new Set(base.map(x => x.S))) { const xs = base.filter(x => x.S === S && Math.abs(x.m) > 3 && x.ph > 0.01 && x.ph < 0.99).map(x => x.m / ninv(x.ph)); sig[S] = xs.sort((a, b) => a - b)[xs.length >> 1]; }
const ll = (p, y) => { p = Math.min(1 - 1e-9, Math.max(1e-9, p)); return -(y * Math.log(p) + (1 - y) * Math.log(1 - p)); };
const apply = (sp, who) => base.map(x => {
  const r = byId[x.id]; if (!r) return x;
  const g = cost(ctx[x.id + '|' + r.h], sp, who) - cost(ctx[x.id + '|' + r.a], sp, who);
  if (!g) return { ...x, g: 0 };
  const m = x.m + g, ph = phi(m / sig[x.S]);
  return { ...x, g, m, ph, ll: ll(ph, x.y), ae: Math.abs(x.res - m) };
});
const cmp = (a, b, key, f) => { const A = a.filter(x => f(x.S)), B = b.filter(x => f(x.S)); const t = paired(A.map(x => x[key]), B.map(x => x[key]), [A.map(x => x.day), A.map(x => x.ht)]); return { d: r4(t.d), t: r2(t.t) }; };
const both = (a, b) => ({ ll: { tune: cmp(a, b, 'll', inTune), held: cmp(a, b, 'll', inHold) }, mae: { tune: cmp(a, b, 'ae', inTune), held: cmp(a, b, 'ae', inHold) } });
// the miss on games with a QB1 out, against the model without any charge: the slope of (result - model) on the cost
const slope = (o, f) => { const xs = o.filter(x => f(x.S) && x.g); const sxx = xs.reduce((a, x) => a + x.g * x.g, 0), sxy = xs.reduce((a, x) => a + x.g * (x.res - (x.m - x.g)), 0); return { n: xs.length, b: r2(sxy / sxx), meanCost: r2(mean(xs.map(x => Math.abs(x.g)))) }; };

const LIVE = { k: 150, repl: -0.05, plays: 38, cap: 6, floor: -0.25 };
const report = { asof: new Date().toISOString().slice(0, 10), seasons: [SEASONS[0], SEASONS.at(-1)], tune: [2016, 2020], held: [2021, 2026],
  teamGames: Object.keys(ctx).length, qb1Out: outs.length, qb1OutByQb2: outs.filter(c => c.stIsQ2).length, specs: {} };
const none = base.map(x => ({ ...x, g: 0 }));
const liveO = apply(LIVE, 'st'), liveQ2 = apply(LIVE, 'q2');
report.live = { oracle: { ...both(liveO, none), slope: { tune: slope(liveO, inTune), held: slope(liveO, inHold) } }, q2: { ...both(liveQ2, none), slope: { tune: slope(liveQ2, inTune), held: slope(liveQ2, inHold) } } };
console.log('live', JSON.stringify(report.live));
if (mode === 'fv') {
  // shipped charge, each QB's prior moved by his recruit grade; grid on tune (b per 1.0 of composite, unrated level u,
  // replacement re-centred), scored against the shipped charge
  const SHIP = { ...LIVE, k: 500, repl: -0.2, cap: 10 };
  const shipO = apply(SHIP, 'st'), shipQ2 = apply(SHIP, 'q2');
  const st = outs.filter(c => c.st?.aid), cov = st.filter(c => C247[c.st.aid] != null).length;
  const res = { note: 'CFB backup QB when QB1 (60+ plays) does not start: each QB valued (EPA this season + k x prior)/(plays + k), prior = repl + b x (247 composite - .85), unrated at u; against the shipped charge (b 0). Oracle starter; tune 2016-20, held 2021-26, t clustered by day x home team (negative helps)',
    qb1Out: outs.length, startersRated: cov, grid: [] };
  const g = [];
  for (const b of [0, 1, 2, 3, 4]) for (const u of [0.8, 0.84, 0.86]) for (const repl of [-0.25, -0.2, -0.15]) {
    if (!b && u !== 0.84) continue;
    const sp = { ...SHIP, b, u, repl }, o = apply(sp, 'st');
    g.push({ sp, tune: mean(o.filter(x => inTune(x.S)).map(x => x.ll)), held: mean(o.filter(x => inHold(x.S)).map(x => x.ll)) });
  }
  g.sort((a, b) => a.tune - b.tune);
  res.grid = g.slice(0, 10).map(x => ({ b: x.sp.b, u: x.sp.u, repl: x.sp.repl, tune: r4(x.tune), held: r4(x.held) }));
  const best = g.find(x => x.sp.b > 0).sp;
  const o = apply(best, 'st'), q = apply(best, 'q2');
  res.best = { sp: best, oracle: { vsShip: both(o, shipO), slope: { tune: slope(o, inTune), held: slope(o, inHold) } }, q2: { vsShip: both(q, shipQ2) } };
  for (const b of [1, 2, 3]) { const oo = apply({ ...SHIP, b, u: 0.84 }, 'st'); res['b' + b] = both(oo, shipO); }
  console.log(JSON.stringify(res, null, 1));
  const f = path.join(ROOT, 'data', 'fv_games_research.json'), j = fs.existsSync(f) ? JSON.parse(fs.readFileSync(f, 'utf8')) : {};
  j.cfbQbBackup = res; fs.writeFileSync(f, JSON.stringify(j, null, 1));
  process.exit(0);
}
// grid on tune: replacement level, shrink, last season's weight, roster talent in the backup's prior, cap, scale
const grid = [];
for (const repl of [-0.25, -0.2, -0.15, -0.1, -0.05, 0]) for (const k of [75, 150, 300, 500, 800]) for (const prevW of [0, 0.5]) for (const tal of [0, 0.03]) for (const cap of [6, 10]) for (const scale of [0.75, 1]) {
  const sp = { ...LIVE, repl, k, prevW, tal, cap, scale }, o = apply(sp, 'st');
  const tune = mean(o.filter(x => inTune(x.S)).map(x => x.ll)), held = mean(o.filter(x => inHold(x.S)).map(x => x.ll));
  grid.push({ sp, tune, held });
}
grid.sort((a, b) => a.tune - b.tune);
const best = grid[0].sp;
report.grid = grid.slice(0, 12).map(g => ({ ...g.sp, tune: r4(g.tune), held: r4(g.held) }));
const bestO = apply(best, 'st'), bestQ2 = apply(best, 'q2');
report.best = { sp: best, oracle: { vsLive: both(bestO, liveO), vsNone: both(bestO, none), slope: { tune: slope(bestO, inTune), held: slope(bestO, inHold) } },
  q2: { vsLive: both(bestQ2, liveQ2), vsNone: both(bestQ2, none) } };
// one change at a time from live
for (const [k, sp] of Object.entries({ repl: { ...LIVE, repl: best.repl }, k: { ...LIVE, k: best.k }, prevW: { ...LIVE, prevW: best.prevW }, tal: { ...LIVE, tal: best.tal || 0.03 }, cap: { ...LIVE, cap: best.cap }, scale: { ...LIVE, scale: best.scale }, replK: { ...LIVE, repl: best.repl, k: best.k } })) {
  const o = apply(sp, 'st'); report.specs[k] = { sp, vsLive: both(o, liveO) };
}
// shipped: the tuning grid is flat at its top (log loss within .0001 over k 500-800, replacement -.2 to -.25, scale .75-1),
// so the setting is the interior point of that ridge rather than its corner
const SHIP = { ...LIVE, k: 500, repl: -0.2, cap: 10 };
{ const o = apply(SHIP, 'st'), q = apply(SHIP, 'q2');
  report.ship = { sp: SHIP, oracle: { vsLive: both(o, liveO), vsNone: both(o, none), slope: { tune: slope(o, inTune), held: slope(o, inHold) } }, q2: { vsLive: both(q, liveQ2), vsNone: both(q, none) } };
  console.log('ship', JSON.stringify(report.ship)); }
console.log('best', JSON.stringify(report.best));
console.log('specs', JSON.stringify(report.specs));
const f = path.join(ROOT, 'data', 'cfb_qb_backup.json'), j = fs.existsSync(f) ? JSON.parse(fs.readFileSync(f, 'utf8')) : {};
fs.writeFileSync(f, JSON.stringify({ ...j, ...report }, null, 1));
