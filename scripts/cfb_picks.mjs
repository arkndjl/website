// Picks (data/cfb_picks.json, the picks tab). Since Oct 14 2026 the tab lists only upset picks (Noah's rule, see
// upsetBacktest below). The gated markets described here (backtest, livePicks) are kept for reference but not run:
// moneyline and spread bets where the game model, shrunk toward the market, still beats the price after the vig.
//
//   Predictions  season-swap: the game model's margin weights fit on one season predict the other (the same
//                cross-validation as the model report), so every backtest game is one the weights never saw
//   Margins      spreads are priced on whole-number final margins, not a smooth curve: a normal around the
//                expected margin, reweighted by how often each margin size actually happens against a normal
//                around the closing line (key numbers: 3, 7, 10, 14 land far more often than their neighbours;
//                ties never). So a whole-number line carries its push chance and a half point off 3 or 7 is
//                worth what it is
//   Shrinkage    spread: expected margin = line + k x (model margin - line), k fit by log loss on covers (pushes
//                out); k = 0 is "the line is right", 1 the raw model. Moneyline: the no-vig market win chance
//                and the model's, mixed on the log-odds scale at the weight that scores best (0 = market only)
//   Edge         expected return per unit at the price: P(win) x (decimal odds - 1) - P(loss), pushes refunded
//   Thresholds   nested: shrinkage and the edge threshold are set on one season's out-of-sample games and
//                scored on the other's. A market is live only when, in both seasons, the threshold set on the
//                other season made money after the vig on 10+ bets with a per-bet t of 0.5 or more, bet no more
//                than a quarter of the games, the pooled t is 1.5 or more, and (bets at the open) the close moved
//                toward the picks on average and for at least half of them
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
// key numbers: each final margin size's frequency over what a normal around the closing line expects
// (KA games of prior weight toward 1; a tie can't happen)
const KMAX = 70, KA = 10;
export function keyTable(rows) {
  const xs = rows.filter(g => g.close != null), s = sd(xs.map(g => g.res - g.close)) || 15;
  const obs = Array(KMAX + 1).fill(0), ex = Array(KMAX + 1).fill(0);
  for (const g of xs) {
    obs[Math.min(KMAX, Math.abs(g.res))]++;
    for (let k = -KMAX; k <= KMAX; k++) ex[Math.abs(k)] += phi((k + 0.5 - g.close) / s) - phi((k - 0.5 - g.close) / s);
  }
  return { s, n: xs.length, w: obs.map((o, d) => d === 0 ? 0 : (o + KA) / (ex[d] + KA)), obs, ex };
}
// P(home margin above, on, below line L) for an expected margin mu
export function marginProbs(mu, K, L) {
  let hi = 0, eq = 0, lo = 0;
  for (let k = -KMAX; k <= KMAX; k++) {
    const p = (phi((k + 0.5 - mu) / K.s) - phi((k - 0.5 - mu) / K.s)) * K.w[Math.abs(k)];
    if (k > L) hi += p; else if (k === L) eq += p; else lo += p;
  }
  const t = hi + eq + lo; return [hi / t, eq / t, lo / t];
}
const spreadBet = (g, P, L, price = [-110, -110]) => {
  const [hi, eq, lo] = marginProbs(L + P.k * (g.m - L), P, L);
  const evH = hi * (decOdds(price[0]) - 1) - lo, evA = lo * (decOdds(price[1]) - 1) - hi, home = evH >= evA;
  return { side: home ? 'home' : 'away', p: home ? hi : lo, push: eq, edge: home ? evH : evA, odds: home ? price[0] : price[1], L };
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
  const K = keyTable(rows), xs = rows.filter(g => g[key] != null && g.res !== g[key]);
  let best = 0, bl = Infinity;
  for (let k = 0; k <= 1.0001; k += 0.02) {
    const l = -xs.reduce((s, g) => { const [hi, , lo] = marginProbs(g[key] + k * (g.m - g[key]), K, g[key]);
      return s + Math.log(clip((g.res > g[key] ? hi : lo) / (hi + lo))); }, 0);
    if (l < bl) { bl = l; best = k; }
  }
  return { k: Math.round(best * 100) / 100, s: K.s, w: K.w };
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

// the backtested markets: spreads at the open, spreads at the close, moneylines at the close, and the model's side
// against the open within a band of disagreement (gap, points; no shrinkage: small gaps have covered, large ones
// haven't, which a single shrink weight can't express). For gap the threshold is the band [lo, hi)
const GAPS = [];
for (const lo of [0.5, 1, 2, 3, 4]) for (const hi of [3, 4, 5, 7, 10, 99]) if (hi > lo + 1) GAPS.push([lo, hi]);
const MARKETS = {
  spreadOpen: { kind: 'spread', key: 'open', grid: [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.1, 0.12, 0.15] },
  spreadClose: { kind: 'spread', key: 'close', grid: [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.1, 0.12, 0.15] },
  gapOpen: { kind: 'gap', key: 'open', grid: GAPS },
  ml: { kind: 'ml', key: 'ml', grid: [0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.1, 0.12, 0.15, 0.2, 0.25] },
};
const MIN_FIT_BETS = 20, MIN_FOLD_BETS = 10, MIN_FOLD_T = 0.5, MIN_T = 1.5, MAX_SHARE = 0.25;
const fitOf = (M, rows) => M.kind === 'ml' ? fitMl(rows) : M.kind === 'gap' ? null : fitCover(rows, M.key);
const sel = (M, t) => M.kind === 'gap' ? b => b.edge >= t[0] && b.edge < t[1] : b => b.edge >= t;
const gapBet = (g, L, price = [-110, -110]) => { const d = g.m - L, home = d >= 0;
  return { side: home ? 'home' : 'away', edge: Math.abs(d), odds: home ? price[0] : price[1], L }; };
function bets(M, rows, w) {
  const out = [];
  for (const g of rows) {
    const wg = typeof w === 'function' ? w(g) : w;
    const bet = M.kind === 'ml' ? (g.mlH != null ? mlBet(g, wg, g.mlH, g.mlA) : null) : g[M.key] == null ? null
      : M.kind === 'gap' ? gapBet(g, g[M.key]) : spreadBet(g, wg, g[M.key]);
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
// the threshold a season's games would pick: the most units won on MIN_FIT_BETS+ bets and no more than MAX_SHARE of
// the games, if any make money
function chooseT(M, rows, w) {
  const bs = bets(M, rows, w);
  let best = null;
  for (const t of M.grid) { const s = summ(bs.filter(sel(M, t))); if (s.n >= MIN_FIT_BETS && s.n <= MAX_SHARE * rows.length && s.units > 0 && (!best || s.units > best.s.units)) best = { t, s }; }
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
  const K = keyTable(rows);
  // the key numbers, for the page: share of games ending on each margin size against the smooth normal's
  const keys = [1, 2, 3, 4, 6, 7, 8, 10, 14, 17, 21].map(d => ({ d, share: r3(K.obs[d] / Math.max(1, K.n)), normal: r3(K.ex[d] / Math.max(1, K.n)), w: r3(K.w[d]) }));
  const out = { seasons, games: rows.length, keys, sd: r1(K.s), markets: {} };
  const shrinkOf = w => w == null ? null : typeof w === 'number' ? r3(w) : w.k;
  for (const [name, M] of Object.entries(MARKETS)) {
    const has = rows.filter(g => M.kind === 'ml' ? g.mlH != null : g[M.key] != null);
    const fitBy = Object.fromEntries(seasons.map(E => [E, fitOf(M, has.filter(g => g.S !== E))]));   // fit on the other season
    const folds = seasons.map(E => {
      const C = has.filter(g => g.S !== E), on = has.filter(g => g.S === E), w = fitBy[E], t = chooseT(M, C, w);
      const bs = t == null ? [] : bets(M, on, w).filter(sel(M, t));
      return { season: E, games: on.length, ...summ(bs), shrink: shrinkOf(w), thr: t, _bs: bs };
    });
    const pooled = summ(folds.flatMap(f => f._bs));
    // by threshold, each season scored with shrinkage fit on the other (no threshold choice involved)
    const all = seasons.flatMap(E => bets(M, has.filter(g => g.S === E), fitBy[E]));
    const byT = M.grid.map(t => ({ thr: t, ...summ(all.filter(sel(M, t))) }));
    // the raw model for contrast: every game where it sees value, unshrunk
    const rawBs = M.kind === 'gap' ? [] : bets(M, has, M.kind === 'ml' ? 1 : { k: 1, s: K.s, w: K.w }).filter(b => b.edge > 0);
    const raw = M.kind === 'gap' ? null : { ...summ(rawBs), bySeason: seasons.map(E => ({ season: E, ...summ(rawBs.filter(b => b.g.S === E)) })) };
    const gates = {
      folds: folds.every(f => f.thr != null && f.n >= MIN_FOLD_BETS && f.units > 0 && (f.t ?? 0) >= MIN_FOLD_T),
      picky: folds.every(f => f.n <= MAX_SHARE * f.games),
      pooled: pooled.t != null && pooled.t >= MIN_T,
      clv: M.key !== 'open' || ((pooled.clv ?? -1) > 0 && (pooled.clvPos ?? 0) >= 0.5),
    };
    const pass = Object.values(gates).every(Boolean);
    const w = fitOf(M, has), t = pass ? chooseT(M, has, w) : null;
    out.markets[name] = { games: has.length, folds: folds.map(({ _bs, ...f }) => f), pooled, byT, raw, gates, pass: pass && t != null,
      live: pass && t != null ? { w, t } : null, shrink: shrinkOf(w) };
  }
  return out;
}
// ---- upset picks (Noah's rule, Oct 2026) -------------------------------------------------------------------
// Not gated: every game where the model picks the market underdog to win outright (its margin and the line on opposite
// sides of zero) by more than UPSET_EDGE points against the line. Backtested on the same season-swap predictions as
// the markets above, betting the underdog three ways: moneyline at the close (the only moneylines in the data), and
// the points at the open and at the close. A fixed rule, so nothing is fit and every season is out of sample.
export const UPSET_EDGE = 4;
const upsetSide = (m, L) => L == null || L === 0 || Math.sign(m) === Math.sign(L) || Math.abs(m - L) <= UPSET_EDGE ? null : L > 0 ? 'away' : 'home';
// Sizing (Noah, Oct 14 2026): units in proportion to the Kelly stake at the model's own chance against the price (win
// chance on the moneyline, cover chance on the points; normal around the model margin, sigma from the fit), scaled so
// the backtest's average pick is 1 unit, from KELLY_MIN to KELLY_CAP. Literal quarter Kelly on a 100-unit bankroll
// puts the cap on nearly every pick: the model's raw chance on these games runs ~62% where the dogs won ~44%
export const KELLY_MIN = 0.25, KELLY_CAP = 3;
export const kelly = (p, odds) => { const b = decOdds(odds) - 1; return (p * b - (1 - p)) / b; };
// the model's chance for the underdog: winning outright (ml) or covering `pts` points
const dogChance = (side, m, sigma, pts = 0) => phi(((side === 'home' ? m : -m) + pts) / sigma);
const stakeOf = (f, scale) => scale ? Math.min(KELLY_CAP, Math.max(KELLY_MIN, f / scale)) : 1;
export function upsetBacktest(rows) {
  const seasons = [...new Set(rows.map(g => g.S))].sort(), by = { ml: [], open: [], close: [] };
  for (const g of rows) {
    const L = g.open ?? g.close, side = upsetSide(g.m, L);   // the rule fires on the line when picks publish (the open)
    if (!side) continue;
    if (g.mlH != null && g.mlA != null) { const odds = side === 'home' ? g.mlH : g.mlA;
      by.ml.push({ g, profit: grade({ side, odds }, g.res, 'ml'), clv: null, f: kelly(dogChance(side, g.m, g.sigma), odds) }); }
    for (const key of ['open', 'close']) if (g[key] != null && g.res !== g[key])
      by[key].push({ g, profit: grade({ side, L: g[key], odds: -110 }, g.res, 'spread'), clv: clvPts(side, g.open, g.close),
        f: kelly(dogChance(side, g.m, g.sigma, side === 'home' ? -g[key] : g[key]), -110) });
  }
  const out = { edge: UPSET_EDGE, games: rows.length, seasons, kelly: { min: KELLY_MIN, cap: KELLY_CAP } };
  // sized: each season's stakes scaled by the other season's average Kelly stake (out of sample, like the predictions)
  const sized = bs => { const risked = bs.reduce((a, b) => a + b.stake, 0), u = bs.reduce((a, b) => a + b.stake * b.profit, 0);
    return { risked: r1(risked), units: r1(u), roi: risked ? r3(u / risked) : null, big: bs.filter(b => b.stake >= 2).length }; };
  for (const [k, bs] of Object.entries(by)) {
    const scaleBy = Object.fromEntries(seasons.map(S => [S, mean(bs.filter(b => b.g.S !== S).map(b => b.f))]));
    for (const b of bs) b.stake = stakeOf(b.f, scaleBy[b.g.S]);
    out[k] = { ...summ(bs), sized: sized(bs), bySeason: seasons.map(S => ({ season: S, ...summ(bs.filter(b => b.g.S === S)), sized: sized(bs.filter(b => b.g.S === S)) })),
      won: bs.length ? r3(bs.filter(b => b.g.res !== 0 && (b.g.res > 0) === ((b.g.open ?? b.g.close) < 0)).length / bs.length) : null,
      scale: r3(mean(bs.map(b => b.f))) };
  }
  return out;
}
// live: sigma, the model's miss (the backtest's); bt, upsetBacktest's output (its average Kelly stakes set the scale)
export function liveUpsets(slate, sigma, bt) {
  const out = [], now = Date.now();
  for (const g of slate) {
    if (!g.proj || g.market == null || Date.parse(g.date) <= now) continue;
    const L = -g.market, side = upsetSide(g.proj.margin, L); if (!side) continue;
    const odds = amer(side === 'home' ? g.ml?.home : g.ml?.away), line = side === 'home' ? g.market : -g.market;
    // sized on the moneyline when there is one (graded on it too), else on the points
    const p = sigma ? dogChance(side, g.proj.margin, sigma, odds != null ? 0 : line) : null, f = p == null ? null : kelly(p, odds ?? -110);
    const scale = odds != null ? bt?.ml?.scale : bt?.open?.scale;
    out.push({ id: g.id, type: 'upset', side, line, odds: odds ?? -110, ml: odds, edge: r1(Math.abs(g.proj.margin - L)), model: r1(g.proj.margin),
      p: p == null ? null : r3(p), units: f == null || !scale ? 1 : Math.round(stakeOf(f, scale) * 4) / 4, g });
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
      if (bet.edge >= so.t) out.push({ id: g.id, type: 'spread', side: bet.side, line: bet.side === 'home' ? g.market : -g.market, odds: bet.odds, p: r3(bet.p), push: r3(bet.push), edge: r3(bet.edge), model: r1(g.proj.margin), g });
    }
    // the gap rule: the model's side of the current line when the disagreement sits in the band that held up; its
    // chance and edge are the band's backtest cover rate and return
    const gp = bt.markets.gapOpen?.live;
    if (gp && g.market != null && !out.some(p => p.id === g.id && p.type === 'spread')) {
      const L = -g.market, price = [amer(g.spreadOdds?.home) ?? -110, amer(g.spreadOdds?.away) ?? -110], bet = gapBet(row, L, price);
      const b = bt.markets.gapOpen.byT.find(x => x.thr[0] === gp.t[0] && x.thr[1] === gp.t[1]);
      if (bet.edge >= gp.t[0] && bet.edge < gp.t[1]) out.push({ id: g.id, type: 'spread', rule: 'gap', side: bet.side, line: bet.side === 'home' ? g.market : -g.market, odds: bet.odds,
        p: b && b.w + b.l ? r3(b.w / (b.w + b.l)) : null, edge: b?.roi ?? null, gap: r1(bet.edge), model: r1(g.proj.margin), g });
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
    // picks flagged before sizing (Oct 14 2026) take the stake at the current price
    if (log[k]) { if (p.type === 'upset' && log[k].stake == null && !log[k].result) log[k].stake = p.units ?? 1; continue; }
    const g = p.g, team = p.side === 'home' ? g.home : g.away;
    log[k] = { id: p.id, type: p.type, week, date: g.date, flagged: asof, home: g.home.name, away: g.away.name, homeLogo: g.home.logo || null, awayLogo: g.away.logo || null, team: team.name, logo: team.logo || null,
      side: p.side, rule: p.rule || null, gap: p.gap ?? null, line: p.line ?? null, odds: p.odds, ml: p.ml ?? null, stake: p.type === 'upset' ? p.units ?? 1 : null, p: p.p ?? null, push: p.push ?? null, q: p.q ?? null, edge: p.edge, model: p.model };
  }
  for (const e of Object.values(log)) {
    const c = cfbdNow[e.id]; if (!c || c.homeScore == null || c.awayScore == null || e.result) continue;
    const res = c.homeScore - c.awayScore, mk = marketOf(c);
    e.result = `${c.awayScore}-${c.homeScore}`;
    if (e.type === 'upset') {
      const L = e.side === 'home' ? -e.line : e.line;
      const ats = grade({ side: e.side, L, odds: -110 }, res, 'spread');
      e.ats = ats > 0 ? 'W' : ats < 0 ? 'L' : 'P';
      e.won = res === 0 ? null : (e.side === 'home') === (res > 0);
      e.units = r3(e.ml != null ? grade({ side: e.side, odds: e.ml }, res, 'ml') : ats);
      e.close = mk.close == null ? null : e.side === 'home' ? -mk.close : mk.close;
      e.clv = r1(clvPts(e.side, L, mk.close));
    } else if (e.type === 'spread') {
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
  for (const type of ['spread', 'ml', 'upset']) {
    const xs = Object.values(log).filter(e => e.type === type && e.ats), cl = xs.map(e => e.clv).filter(x => x != null);
    const u = xs.reduce((a, e) => a + e.units, 0);
    if (type === 'upset') { const risked = xs.reduce((a, e) => a + (e.stake ?? 1), 0), su = xs.reduce((a, e) => a + (e.stake ?? 1) * e.units, 0);
      rec.upset = { n: xs.length, won: xs.filter(e => e.won).length, w: xs.filter(e => e.ats === 'W').length, l: xs.filter(e => e.ats === 'L').length,
      p: xs.filter(e => e.ats === 'P').length, units: r1(u), roi: xs.length ? r3(u / xs.length) : null, clv: cl.length ? Math.round(mean(cl) * 100) / 100 : null,
      sized: { risked: r1(risked), units: r1(su), roi: risked ? r3(su / risked) : null } }; continue; }
    rec[type] = { w: xs.filter(e => e.ats === 'W').length, l: xs.filter(e => e.ats === 'L').length, p: xs.filter(e => e.ats === 'P').length,
      units: r1(u), roi: xs.length ? r3(u / xs.length) : null, clv: cl.length ? Math.round(mean(cl) * 1000) / 1000 : null };
  }
  return rec;
}
