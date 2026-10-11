// Picks (data/cfb_picks.json, the picks tab): moneyline and spread bets where the game model, shrunk toward the
// market, still beats the price after the vig. Only rules that held up out of sample are used.
//
//   Predictions  season-swap: the game model's margin weights fit on one season predict the other (the same
//                cross-validation as the model report), so every backtest game is one the weights never saw
//   Shrinkage    spread: P(home covers line L) = Phi(b x (model margin - L)), b fit by log loss on covers;
//                b = 0 is "the line is right", 1/sd is the raw model. Moneyline: the no-vig market win chance
//                and the model's, mixed on the log-odds scale at the weight that scores best (0 = market only)
//   Edge         spread: cover chance minus the break-even at the price (52.4% at -110); moneyline: expected
//                return per unit, P(win) x decimal odds - 1
//   Thresholds   nested: shrinkage and the edge threshold are set on one season's out-of-sample games and
//                scored on the other's. A market is live only when, in both seasons, the threshold set on the
//                other season made money after the vig on 10+ bets, the pooled per-bet t is 1.0 or more, and
//                (spreads) the line moved toward the pick between the bet and the close on average
//   Lines        CFBD: spread open and close (consensus first), closing moneylines. Spreads are scored at the
//                open (the line on the board when picks publish, the week's ratings in) and at the close;
//                moneylines only at the close, since opening moneylines aren't in the data. Moneylines are bet
//                only where the side's no-vig chance is 20-80% (roughly +400 to -400)
// Live picks are logged at the line and price when first flagged, then graded and given their closing line value.

import { phi } from './cfb_model.mjs';

const mean = xs => xs.reduce((a, b) => a + b, 0) / Math.max(1, xs.length);
const sd = xs => { const m = mean(xs); return Math.sqrt(mean(xs.map(x => (x - m) ** 2))); };
const r1 = x => x == null ? null : Math.round(x * 10) / 10, r3 = x => x == null ? null : Math.round(x * 1000) / 1000;
const logit = p => Math.log(p / (1 - p)), expit = x => 1 / (1 + Math.exp(-x));
const clip = p => Math.min(1 - 1e-6, Math.max(1e-6, p));
export const decOdds = a => a > 0 ? 1 + a / 100 : 1 + 100 / -a;
const breakEven = a => 1 / decOdds(a);
const amer = v => { if (v == null) return null; if (typeof v === 'string') { if (/^even$/i.test(v.trim())) return 100; v = +v.replace(/[^\d.+-]/g, ''); }
  return Number.isFinite(v) && Math.abs(v) >= 100 ? v : null; };
const PROV = ['consensus', 'ESPN Bet', 'DraftKings', 'Bovada', 'William Hill (New Jersey)', 'teamrankings', 'numberfire'];
const byProv = ls => [...ls].sort((a, b) => (PROV.indexOf(a.provider) + 1 || 99) - (PROV.indexOf(b.provider) + 1 || 99));
// no-vig home win chance from two American prices; null for a missing or broken pair (overround outside 0-12%)
export function noVig(h, a) {
  if (h == null || a == null) return null;
  const ih = 1 / decOdds(h), ia = 1 / decOdds(a), o = ih + ia;
  return o < 1 || o > 1.12 ? null : ih / o;
}
// one CFBD lines row: market home margins (open, close) and the closing moneyline pair
export function marketOf(row) {
  const ls = byProv(row?.lines || []);
  const c = ls.find(l => l.provider === 'consensus' && l.spread != null) || ls.find(l => l.provider === 'ESPN Bet' && l.spread != null) || ls.find(l => l.spread != null);
  const o = (c?.spreadOpen != null ? c : null) || ls.find(l => l.spreadOpen != null);
  const ml = ls.find(l => noVig(amer(l.homeMoneyline), amer(l.awayMoneyline)) != null);
  return { close: c ? -c.spread : null, open: o ? -o.spreadOpen : null,
    mlH: ml ? amer(ml.homeMoneyline) : null, mlA: ml ? amer(ml.awayMoneyline) : null };
}

// ---- the two bet types ---------------------------------------------------------------------------------
// each returns, for a game and fitted shrinkage, the side it would take and its edge; grade() scores it
const spreadBet = (g, b, L, price = [-110, -110]) => {
  const p = phi(b * (g.m - L)), home = p >= 0.5, ps = home ? p : 1 - p, odds = home ? price[0] : price[1];
  return { side: home ? 'home' : 'away', p: ps, edge: ps - breakEven(odds), odds, L };
};
const ML_BAND = [0.2, 0.8];
const mlBet = (g, a, mlH, mlA) => {
  const q = noVig(mlH, mlA); if (q == null) return null;
  const p = expit(logit(clip(q)) + a * (logit(clip(phi(g.m / g.sigma))) - logit(clip(q))));
  const evH = p * decOdds(mlH) - 1, evA = (1 - p) * decOdds(mlA) - 1, home = evH >= evA;
  // no long shots or heavy favourites: the side's market chance stays within ML_BAND, where a normal miss holds up
  const qs = home ? q : 1 - q; if (qs < ML_BAND[0] || qs > ML_BAND[1]) return null;
  return { side: home ? 'home' : 'away', p: home ? p : 1 - p, q: home ? q : 1 - q, edge: home ? evH : evA, odds: home ? mlH : mlA };
};
// profit per unit staked; null result = push
function grade(bet, res, kind) {
  if (kind === 'ml') { const won = bet.side === 'home' ? res > 0 : res < 0; return res === 0 ? 0 : won ? decOdds(bet.odds) - 1 : -1; }
  const d = res - bet.L; if (d === 0) return 0;
  return (bet.side === 'home') === (d > 0) ? decOdds(bet.odds) - 1 : -1;
}
// closing line value in points: how far the spread moved toward the pick between the bet and the close
const clvPts = (side, at, close) => at == null || close == null ? null : side === 'home' ? close - at : at - close;

// ---- fitting ---------------------------------------------------------------------------------------------
function fitCover(rows, key) {
  const xs = rows.filter(g => g[key] != null && g.res !== g[key]);
  let best = 0, bl = Infinity;
  for (let b = 0; b <= 0.1; b += 0.001) {
    const l = -xs.reduce((s, g) => s + Math.log(clip(phi((g.res > g[key] ? 1 : -1) * b * (g.m - g[key])))), 0);
    if (l < bl) { bl = l; best = b; }
  }
  return Math.min(best, 1 / mean(xs.map(g => g.sigma)));      // never more sure than the raw model
}
function fitMl(rows) {
  const xs = rows.filter(g => g.mlH != null && g.res !== 0);
  let best = 0, bl = Infinity;
  for (let a = 0; a <= 1.0001; a += 0.02) {
    const l = xs.reduce((s, g) => { const q = clip(noVig(g.mlH, g.mlA)), p = expit(logit(q) + a * (logit(clip(phi(g.m / g.sigma))) - logit(q)));
      return s - (g.res > 0 ? Math.log(p) : Math.log(1 - p)); }, 0);
    if (l < bl) { bl = l; best = a; }
  }
  return best;
}

// the three backtested markets: spreads at the open, spreads at the close, moneylines at the close
const MARKETS = {
  spreadOpen: { kind: 'spread', key: 'open', grid: [0.01, 0.015, 0.02, 0.025, 0.03, 0.04, 0.05, 0.06, 0.08, 0.1] },
  spreadClose: { kind: 'spread', key: 'close', grid: [0.01, 0.015, 0.02, 0.025, 0.03, 0.04, 0.05, 0.06, 0.08, 0.1] },
  ml: { kind: 'ml', key: 'ml', grid: [0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.1, 0.12, 0.15, 0.2, 0.25] },
};
const MIN_FIT_BETS = 20, MIN_FOLD_BETS = 10, MIN_T = 1.0;
const fitOf = (M, rows) => M.kind === 'ml' ? fitMl(rows) : fitCover(rows, M.key);
function bets(M, rows, w) {
  const out = [];
  for (const g of rows) {
    const wg = typeof w === 'function' ? w(g) : w;
    const bet = M.kind === 'ml' ? (g.mlH != null ? mlBet(g, wg, g.mlH, g.mlA) : null) : g[M.key] != null ? spreadBet(g, wg, g[M.key]) : null;
    if (!bet) continue;
    out.push({ g, bet, edge: bet.edge, profit: grade(bet, g.res, M.kind), clv: clvPts(bet.side, g.open, g.close) });
  }
  return out;
}
function summ(bs) {
  const n = bs.length, pr = bs.map(b => b.profit), units = pr.reduce((a, b) => a + b, 0), s = sd(pr);
  const cl = bs.map(b => b.clv).filter(x => x != null);
  return { n, w: pr.filter(x => x > 0).length, l: pr.filter(x => x < 0).length, p: pr.filter(x => x === 0).length,
    units: r1(units), roi: n ? r3(units / n) : null, t: n > 1 && s ? Math.round(units / n / (s / Math.sqrt(n)) * 100) / 100 : null,
    clv: cl.length ? Math.round(mean(cl) * 100) / 100 : null, clvPos: cl.length ? r3(cl.filter(x => x > 0).length / cl.length) : null };
}
// the threshold a season's games would pick: the most units won on MIN_FIT_BETS+ bets, if any make money
function chooseT(M, rows, w) {
  const bs = bets(M, rows, w);
  let best = null;
  for (const t of M.grid) { const s = summ(bs.filter(b => b.edge >= t)); if (s.n >= MIN_FIT_BETS && s.units > 0 && (!best || s.units > best.s.units)) best = { t, s }; }
  return best?.t ?? null;
}

// backtest rows: every FBS game with a result, the model's out-of-sample margin and the market
export function backtestRows(model, lines, fitBeta) {
  const { train = [], test = [] } = model._debug || {};
  const done = ps => ps.filter(p => p.r.done && p.r.fbsGame);
  const A = done(train), B = done(test);
  if (!A.length || !B.length) return [];
  const rows = [];
  for (const [fit, on] of [[A, B], [B, A]]) {
    const { beta, sigma } = fitBeta(fit);
    for (const p of on) {
      const mk = marketOf(lines[p.r.S]?.[p.r.id]);
      if (mk.close == null && mk.mlH == null) continue;
      rows.push({ S: p.r.S, id: p.r.id, w: p.r.w, m: beta.reduce((s, v, i) => s + v * (i ? p.x[i - 1] : 1), 0), sigma, res: p.r.m, ...mk });
    }
  }
  return rows;
}

export function backtest(rows) {
  const seasons = [...new Set(rows.map(g => g.S))].sort();
  const out = { seasons, games: rows.length, markets: {} };
  for (const [name, M] of Object.entries(MARKETS)) {
    const has = rows.filter(g => M.kind === 'ml' ? g.mlH != null : g[M.key] != null);
    const folds = seasons.map(E => {
      const C = has.filter(g => g.S !== E), on = has.filter(g => g.S === E), w = fitOf(M, C), t = chooseT(M, C, w);
      const bs = t == null ? [] : bets(M, on, w).filter(b => b.edge >= t);
      return { season: E, games: on.length, ...summ(bs), shrink: r3(w), thr: t, _bs: bs };
    });
    const pooled = summ(folds.flatMap(f => f._bs));
    // by threshold, each season scored with shrinkage fit on the other (no threshold choice involved)
    const byT = M.grid.map(t => ({ thr: t, ...summ(seasons.flatMap(E => { const w = fitOf(M, has.filter(g => g.S !== E)); return bets(M, has.filter(g => g.S === E), w).filter(b => b.edge >= t); })) }));
    // the raw model for contrast: every game it disagrees on, unshrunk
    const raw = summ(bets(M, has, M.kind === 'ml' ? 1 : g => 1 / g.sigma).filter(b => b.edge > 0));
    const pass = folds.every(f => f.thr != null && f.n >= MIN_FOLD_BETS && f.units > 0) && pooled.t != null && pooled.t >= MIN_T &&
      (M.key !== 'open' || (pooled.clv ?? -1) > 0);
    const w = fitOf(M, has), t = pass ? chooseT(M, has, w) : null;
    out.markets[name] = { games: has.length, folds: folds.map(({ _bs, ...f }) => f), pooled, byT, raw, pass: pass && t != null, live: pass && t != null ? { w, t } : null,
      shrink: r3(w) };
  }
  return out;
}
// ---- live ------------------------------------------------------------------------------------------------
// slate: gamesModel output (proj.margin home, market = home spread, ml {home, away}, spreadOdds {home, away});
// cfbdNow: this season's CFBD lines by id (moneyline fallback)
export function livePicks(slate, bt, sigma, cfbdNow = {}) {
  const out = [], now = Date.now();
  for (const g of slate) {
    if (!g.proj || Date.parse(g.date) <= now) continue;
    const row = { m: g.proj.margin, sigma };
    const so = bt.markets.spreadOpen?.live;
    if (so && g.market != null) {
      const L = -g.market, price = [amer(g.spreadOdds?.home) ?? -110, amer(g.spreadOdds?.away) ?? -110], bet = spreadBet(row, so.w, L, price);
      if (bet.edge >= so.t) out.push({ id: g.id, type: 'spread', side: bet.side, line: bet.side === 'home' ? g.market : -g.market, odds: bet.odds, p: r3(bet.p), edge: r3(bet.edge), model: r1(g.proj.margin), g });
    }
    const ml = bt.markets.ml?.live;
    let mlH = amer(g.ml?.home), mlA = amer(g.ml?.away);
    if (noVig(mlH, mlA) == null) { const mk = marketOf(cfbdNow[g.id]); mlH = mk.mlH; mlA = mk.mlA; }
    if (ml && noVig(mlH, mlA) != null) {
      const bet = mlBet(row, ml.w, mlH, mlA);
      if (bet.edge >= ml.t) out.push({ id: g.id, type: 'ml', side: bet.side, odds: bet.odds, p: r3(bet.p), q: r3(bet.q), edge: r3(bet.edge), model: r1(g.proj.margin), g });
    }
  }
  return out;
}

// the pick log: first flag kept (line, price, time); graded and given CLV once CFBD has the result and close
export function updateLog(log, picks, cfbdNow, asof, week) {
  for (const p of picks) {
    const k = `${p.id}|${p.type}`;
    if (log[k]) continue;
    const g = p.g, team = p.side === 'home' ? g.home : g.away;
    log[k] = { id: p.id, type: p.type, week, date: g.date, flagged: asof, home: g.home.name, away: g.away.name, homeLogo: g.home.logo || null, awayLogo: g.away.logo || null, team: team.name, logo: team.logo || null,
      side: p.side, line: p.line ?? null, odds: p.odds, p: p.p, q: p.q ?? null, edge: p.edge, model: p.model };
  }
  for (const e of Object.values(log)) {
    const c = cfbdNow[e.id]; if (!c || c.homeScore == null || c.awayScore == null || e.result) continue;
    const res = c.homeScore - c.awayScore, mk = marketOf(c);
    e.result = `${c.awayScore}-${c.homeScore}`;
    if (e.type === 'spread') {
      const L = e.side === 'home' ? -e.line : e.line;           // home margin
      const pr = grade({ side: e.side, L, odds: e.odds }, res, 'spread');
      e.ats = pr > 0 ? 'W' : pr < 0 ? 'L' : 'P'; e.units = r3(pr);
      e.close = mk.close == null ? null : e.side === 'home' ? -mk.close : mk.close;   // the close, in the pick's terms
      e.clv = r1(clvPts(e.side, L, mk.close));
    } else {
      const pr = grade({ side: e.side, odds: e.odds }, res, 'ml');
      e.ats = pr > 0 ? 'W' : 'L'; e.units = r3(pr);
      const q = noVig(mk.mlH, mk.mlA);
      e.closeOdds = mk.mlH == null ? null : e.side === 'home' ? mk.mlH : mk.mlA;
      // CLV in win chance: the close's no-vig chance for the pick minus the flag price's
      e.clv = q == null || e.q == null ? null : r3((e.side === 'home' ? q : 1 - q) - e.q);
    }
  }
  const rec = {};
  for (const type of ['spread', 'ml']) {
    const xs = Object.values(log).filter(e => e.type === type && e.ats), cl = xs.map(e => e.clv).filter(x => x != null);
    const u = xs.reduce((a, e) => a + e.units, 0);
    rec[type] = { w: xs.filter(e => e.ats === 'W').length, l: xs.filter(e => e.ats === 'L').length, p: xs.filter(e => e.ats === 'P').length,
      units: r1(u), roi: xs.length ? r3(u / xs.length) : null, clv: cl.length ? Math.round(mean(cl) * 1000) / 1000 : null };
  }
  return rec;
}
