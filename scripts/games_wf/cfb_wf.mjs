// Out-of-sample CFB game predictions, one row per finished FBS game with a closing spread, in the cross-sport
// calibration schema.
//   node cfb_wf.mjs --hist <out.json.gz> [espn_odds_cache.json]
// The live model (runModel history mode, cfb_model.mjs HIST_FIT) on the ESPN history (cfb_espn_md.mjs liveInput):
// every season from 2017 walk-forward, margin and totals weights fit on the seasons before it (fold "fit2016-<S-1>").
// Opening spreads from 2023 (ESPN's core odds feed), moneylines where ESPN carries them.
//   node cfb_wf.mjs <md.json.gz> <out.json.gz> [espn_odds_cache.json]
// The old CFBD-dump version (season-swap CV, as scripts/cfb_game_backtest.mjs):
// The live model is rebuilt as the harness does: P {k 20, eloHome 70, lam 1.5}, live prior (PRIOR_X.pts default),
// extra inputs ['p4','qbRet','aggr'] (data/cfb_model.json report.extra). Margin weights fit on one season predict
// the other (fold "fit2025->2026" / "fit2026->2025"); totals the same (plays x pts/play + weather + FCS side).
// Optional ESPN odds cache (fetched here if missing/incomplete): closing spread prices oH/oA where ESPN's closing
// spread equals L, and moneylines where the dump has none.
import zlib from 'node:zlib';
import fs from 'node:fs';
import { _internals as I, phi, fitBeta } from '../cfb_model.mjs';
import { marketOf } from '../cfb_picks.mjs';

const [mdPath, outPath, espnPath] = process.argv.slice(2);
const SEASON = 2026, LIVE = ['p4', 'qbRet', 'aggr'], P = { k: 20, eloHome: 70, lam: 1.5 };
const mean = xs => xs.reduce((a, b) => a + b, 0) / Math.max(1, xs.length);
const sd = xs => { const m = mean(xs); return Math.sqrt(mean(xs.map(x => (x - m) ** 2))) || 1; };
const dot = I.dot, FCS = 'FCS';

let data, A, B, S1, wx, pred = {};
const HISTM = mdPath === '--hist';
if (HISTM) {
  const { liveInput } = await import('../cfb_espn_md.mjs');
  const { runModel, HIST_FIT } = await import('../cfb_model.mjs');
  const ROOT = new URL('../../', import.meta.url).pathname;
  data = liveInput(SEASON);
  data.roster = JSON.parse(fs.readFileSync(ROOT + 'scripts/data/cfb_roster_feats.json', 'utf8')).feats;
  const rw = ROOT + 'scripts/.cache/cfb/ret_war.json';     // PFN returning production (scripts/cfb_ret_war.mjs)
  data.pfnRet = fs.existsSync(rw) ? JSON.parse(fs.readFileSync(rw, 'utf8')) : {};
  data.weather = {};
  const ff = ROOT + 'scripts/data/public_ratings/cfb_fpi.json.gz';     // ESPN FPI runs (scripts/public_ratings.py --cfb)
  data.fpi = fs.existsSync(ff) ? JSON.parse(zlib.gunzipSync(fs.readFileSync(ff))) : null;
  const mdl = await runModel(data, SEASON, { hist: { ...HIST_FIT, wf: true }, sim: false });
  wx = data.weather; S1 = HIST_FIT.first + 1;
  A = mdl.wf.map(q => ({ r: q.r })); B = [];
  for (const q of mdl.wf) pred[q.r.id] = { m: q.m, sigma: q.sigma, fold: q.fold, tm: q.tm };
  console.error(`history walk-forward: ${A.length} games ${S1}-${SEASON}`);
} else {
// ---- harness setup, verbatim in substance ----
data = JSON.parse(zlib.gunzipSync(fs.readFileSync(mdPath)));
const seasons = [SEASON - 2, SEASON - 1, SEASON];
const nameId = {};
for (const S of seasons) for (const g of data.games[S]) { nameId[g.homeTeam] = String(g.homeId); nameId[g.awayTeam] = String(g.awayId); }
for (const S of seasons) for (const g of data.games[S]) { g.homeId = String(g.homeId); g.awayId = String(g.awayId); }
const fbsBy = {};
for (const S of seasons) { fbsBy[S] = new Set(); for (const g of data.games[S]) { if (g.homeClassification === 'fbs') fbsBy[S].add(g.homeId); if (g.awayClassification === 'fbs') fbsBy[S].add(g.awayId); } }
const allGames = seasons.flatMap(S => data.games[S]);
const geo = I.places(data.venues, data.teamsFbs, allGames);
const rows = I.prepare(seasons, data, geo);
const gameById = Object.fromEntries(rows.map(r => [r.id, r]));
I.setExtra([]);
const effBy = Object.fromEntries(seasons.map(S => [S, I.effObs(data.adv[S], nameId, gameById, fbsBy[S], I.rzByGame(data.drives?.[S]), data.sit?.[S])]));
for (const S of seasons) I.decisions(effBy[S]);
const stC = I.stCurves(seasons.flatMap(S => data.drives?.[S] || []));
const stBy = {}, stPrior = {};
for (const S of seasons) {
  stBy[S] = I.stObs(data.drives?.[S], nameId, gameById, fbsBy[S], stC);
  const last = stBy[S - 1] ? I.stAt(stBy[S - 1], 99) : {};
  stPrior[S] = Object.fromEntries(Object.entries(last).map(([t, v]) => [t, 0.5 * v]));
}
const talBy = {};
for (const S of seasons) {
  const list = (data.talent?.[S] || []).map(x => [nameId[x.team], x.talent]).filter(([t, v]) => t && fbsBy[S].has(t) && v != null);
  const m = mean(list.map(x => x[1])), s0 = sd(list.map(x => x[1]));
  talBy[S] = Object.fromEntries(list.map(([t, v]) => [t, (v - m) / s0]));
}
const P0 = { k: 20, eloHome: 55, lam: 3 };
const S0 = seasons[0]; S1 = seasons[1];
const finals = {}, priors = {}, W = {};
const withMass = (F, S) => { const f = finals[S - 1]; for (const [t, x] of Object.entries(F)) x.mass = f?.mass[t] ?? f?.mass[FCS] ?? -15; return F; };
priors[S0] = { pts: {}, ppa: {}, ppp: {}, pace: {} };
finals[S0] = I.finalOf(S0, rows, effBy[S0], fbsBy[S0], null, P0);
const F1 = withMass(I.priorFeatures(S1, data, fbsBy[S1], nameId, finals), S1);
finals[S1] = I.finalOf(S1, rows, effBy[S1], fbsBy[S1], null, P0, finals);
W[S1] = I.fitPrior(F1, finals[S1]);
priors[S1] = I.applyPrior(F1, W[S1]);
const mass1 = finals[S1].mass;
finals[S1] = { ...I.finalOf(S1, rows, effBy[S1], fbsBy[S1], priors[S1], P0, finals), mass: mass1 };
const F2 = withMass(I.priorFeatures(SEASON, data, fbsBy[SEASON], nameId, finals), SEASON);
priors[SEASON] = I.applyPrior(F2, W[S1]);
wx = data.weather || {};
I.setCtx(wx, data.pfnRet || {});
I.setExtra(LIVE);
const walkS = S => I.walk(rows, effBy, fbsBy, priors, P, [S], finals, talBy, stBy, stPrior).filter(p => p.r.done && p.r.fbsGame);
A = walkS(S1); B = walkS(SEASON);
console.error(`walk: ${A.length} games ${S1}, ${B.length} ${SEASON}`);

// margins: season swap
for (const [fit, on, fold] of [[A, B, `fit${S1}->${SEASON}`], [B, A, `fit${SEASON}->${S1}`]]) {
  const { beta, sigma } = fitBeta(fit);
  for (const p of on) pred[p.r.id] = { m: dot(beta, [1, ...p.x]), sigma, fold };
}
// totals: season swap (harness cvTot)
const WXv = (r, x) => [...I.WX(r.dome ? null : wx[r.id]), x[7] !== 0 ? 1 : 0];
const okT = ps => ps.filter(p => p.t.tot > 0 && isFinite(p.t.tot));
const XT = p => [1, p.t.tot, ...WXv(p.r, p.x)];
for (const [fit, on] of [[okT(A), okT(B)], [okT(B), okT(A)]]) {
  const w = I.ols(fit.map(XT), fit.map(p => p.r.tot), 1);
  for (const p of on) pred[p.r.id].tm = dot(w, XT(p));
}
}

// ---- lines ----
const lineRow = {};
for (const S of Object.keys(data.lines || {})) for (const l of data.lines[S]) lineRow[l.id] = l;
const gameRaw = {}; for (const S of Object.keys(data.games)) for (const g of data.games[S]) gameRaw[g.id] = g;
const amer = v => (Number.isFinite(+v) && Math.abs(+v) >= 100 ? +v : null);

// ---- optional ESPN closing prices ----
const games = [...A, ...B].filter(p => p.r.close != null);
let espn = {};
if (espnPath) {
  if (fs.existsSync(espnPath)) espn = JSON.parse(fs.readFileSync(espnPath, 'utf8'));
  // entries cached before opens were kept are pulled again from 2023 (ESPN has no opens before)
  const todo = games.filter(p => !(String(p.r.id) in espn) || (p.r.S >= 2023 && espn[String(p.r.id)].length && !espn[String(p.r.id)].some(e => 'po' in e))).map(p => String(p.r.id));
  const get = async id => {
    const u = `https://sports.core.api.espn.com/v2/sports/football/leagues/college-football/events/${id}/competitions/${id}/odds`;
    for (let k = 0; k < 3; k++) {
      try { const r = await fetch(u); if (r.status === 404) return []; if (!r.ok) throw new Error(r.status); const d = await r.json();
        return (d.items || []).map(it => { const side = s => { const o = it[s] || {}, c = o.close || {};
            return { ml: amer(c.moneyLine?.american ?? o.moneyLine), so: amer(c.spread?.american ?? o.spreadOdds), ps: c.pointSpread?.american != null ? +c.pointSpread.american : null }; };
          // the open (2023 on): home point spread and total, pre-game books only
          const live = /Live/.test(it.provider?.name || ''), po = live ? null : it.homeTeamOdds?.open?.pointSpread?.american, to = live ? null : it.open?.total?.american;
          return { prov: it.provider?.name, spread: it.spread, h: side('homeTeamOdds'), a: side('awayTeamOdds'), po: po != null && isFinite(+po) ? +po : null, to: to != null && isFinite(+to) ? +to : null }; });
      } catch (e) { await new Promise(r => setTimeout(r, 500 * (k + 1))); }
    }
    return null;
  };
  for (let i = 0; i < todo.length; i += 12) {
    const ids = todo.slice(i, i + 12), res = await Promise.all(ids.map(get));
    ids.forEach((id, j) => { if (res[j] != null) espn[id] = res[j]; });
    if (i % 240 === 0) console.error(`espn ${i}/${todo.length}`);
  }
  fs.writeFileSync(espnPath, JSON.stringify(espn));
}

// ---- rows ----
const out = [];
let priced = 0, mlFill = 0;
const dec = a => a > 0 ? 1 + a / 100 : 1 + 100 / -a, okPair = (h, a) => { const o = 1 / dec(h) + 1 / dec(a); return o >= 1 && o <= 1.12; };   // same sanity rule as cfb_picks noVig
for (const p of games) {
  const r = p.r, q = pred[r.id], lr = lineRow[r.id], mk = marketOf(lr);
  const ls = lr?.lines || [];
  const pick = ls.find(l => l.provider === 'consensus') || ls.find(l => l.provider === 'ESPN Bet') || ls.find(l => l.spread != null) || null;
  const To = pick?.overUnderOpen ?? ls.find(l => l.overUnderOpen != null)?.overUnderOpen ?? null;
  let mlH = mk.mlH, mlA = mk.mlA, oH = null, oA = null, Lo = r.open ?? mk.open ?? null, To0 = To;
  { const md = xs => { const v = xs.filter(x => x != null).sort((a, b) => a - b); return v.length ? (v.length % 2 ? v[(v.length - 1) / 2] : (v[v.length / 2 - 1] + v[v.length / 2]) / 2) : null; };
    const es = espn[String(r.id)] || [], po = md(es.map(e => e.po)), to = md(es.map(e => e.to));
    if (Lo == null && po != null) Lo = -po;
    if (To0 == null && to != null && to > 20) To0 = to; }
  for (const e of espn[String(r.id)] || []) {
    // ESPN pointSpread is the home side's handicap (negative = home favored), so home expected margin = -ps
    if (oH == null && e.h.ps != null && -e.h.ps === r.close && e.h.so != null && e.a.so != null && okPair(e.h.so, e.a.so)) { oH = e.h.so; oA = e.a.so; priced++; }
    if (mlH == null && e.h.ml != null && e.a.ml != null) { mlH = e.h.ml; mlA = e.a.ml; mlFill++; }
  }
  out.push({
    sport: 'cfb', S: r.S, id: String(r.id), date: new Date(r.date).toISOString(), wk: r.w, home: r.hn, away: r.an, neutral: r.n ? 1 : 0,
    m: +q.m.toFixed(2), L: r.close, Lo, res: r.m,
    mlH: mlH ?? null, mlA: mlA ?? null, oH, oA,
    tm: q.tm != null ? +q.tm.toFixed(2) : null, T: r.closeTot ?? null, To: To0, tot: r.tot,
    fold: q.fold, sigma: +q.sigma.toFixed(2), fcs: r.hc === 'fbs' && r.ac === 'fbs' ? 0 : 1,
  });
}
out.sort((a, b) => a.date.localeCompare(b.date));
fs.writeFileSync(outPath, zlib.gzipSync(JSON.stringify(out)));

// ---- report ----
const corr = (x, y) => { const mx = mean(x), my = mean(y); let a = 0, b = 0, c = 0; x.forEach((v, i) => { a += (v - mx) * (y[i] - my); b += (v - mx) ** 2; c += (y[i] - my) ** 2; }); return a / Math.sqrt(b * c); };
const ll = (p, y) => { p = Math.min(1 - 1e-9, Math.max(1e-9, p)); return -(y * Math.log(p) + (1 - y) * Math.log(1 - p)); };
const rep = xs => {
  const y = g => g.res > 0 ? 1 : g.res < 0 ? 0 : 0.5, sM = sd(xs.map(g => g.res - g.L)), tt = xs.filter(g => g.tm != null && g.T != null);
  return { n: xs.length, maeM: mean(xs.map(g => Math.abs(g.m - g.res))).toFixed(2), maeL: mean(xs.map(g => Math.abs(g.L - g.res))).toFixed(2),
    corrLres: corr(xs.map(g => g.L), xs.map(g => g.res)).toFixed(3), corrmL: corr(xs.map(g => g.m), xs.map(g => g.L)).toFixed(3),
    llModel: mean(xs.map(g => ll(phi(g.m / g.sigma), y(g)))).toFixed(4), llLine: mean(xs.map(g => ll(phi(g.L / sM), y(g)))).toFixed(4),
    nTot: tt.length, maeTmT: mean(tt.map(g => Math.abs(g.tm - g.T))).toFixed(2), maeTmTot: mean(tt.map(g => Math.abs(g.tm - g.tot))).toFixed(2), maeTtot: mean(tt.map(g => Math.abs(g.T - g.tot))).toFixed(2),
    withLo: xs.filter(g => g.Lo != null).length, withML: xs.filter(g => g.mlH != null).length, withPrice: xs.filter(g => g.oH != null).length, withTo: xs.filter(g => g.To != null).length };
};
console.log('all', JSON.stringify(rep(out)));
for (const S of [...new Set(out.map(g => g.S))].sort()) console.log(S, JSON.stringify(rep(out.filter(g => g.S === S))));
console.log('FBS-FBS only', JSON.stringify(rep(out.filter(g => !g.fcs))));
console.log(`espn: prices matched ${priced}, moneylines filled ${mlFill}`);
