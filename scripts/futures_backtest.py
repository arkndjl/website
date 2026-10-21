#!/usr/bin/env python3
"""Season-sim win totals backtest (data/futures_fit.json): do our preseason sims beat the closing win-total lines?

    python3 scripts/futures_hist.py         # first: the free lines (scripts/data/futures/win_totals.json)
    python3 scripts/futures_backtest.py     # numpy; NFL pulls nflverse games on a cold cache (a few minutes)
    python3 scripts/futures_backtest.py nba # one sport

  Preseason projection, point in time: each sport's game model frozen before its season's first game (ratings carried
  over the summer, the opening rosters, last season's market ratings; coefficients fit only on earlier seasons), every
  regular-season game priced from that frozen state, then 20,000 seasons simulated with each team's true rating drawn
  once a season (NBA 3.7 pts, NFL 5.0: the season-odds sds) and each game around its margin (the model's sd).
  Nothing learned during the season enters, so no injury or result leaks.
    NBA  2015-16 to 2025-26 (Basketball-Reference lines, graded at -110); 2019-20 left out (season cut short)
    NFL  2015-20 (nflverse lines with their prices; the walk-forward NFL model starts in 2015, the free lines end 2020)
  Each team-season: P(over), P(under), P(push) from the sims; the side with the higher EV at the price is the bet,
  1u flat. Reported for every bet and for EV cuts chosen on tuning seasons (NBA 2016-21, NFL 2015-17) and scored on
  the held-out ones (NBA 2022-26, NFL 2018-20). Also the market test: actual - line = b x (ours - line); b > 0 means our
  projection knows something the line does not. The sim's own centre is shrunk to line + w x (ours - line) with w the
  tuning seasons' b before EVs are taken (w = 1: the raw sim).
  Correlation: bets in one season share league-wide shocks, so t-stats cluster by season (mean return a season, t over
  seasons) beside the naive per-bet t, and effective n = n / (1 + (m - 1) rho) from the within-season return correlation.
  Annualized: money sits from the preseason close to the last regular-season game (NBA ~5.8 months, NFL ~4.2).
"""
import copy
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.dirname(HERE)
HIST = os.path.join(ROOT, 'scripts', 'data', 'futures', 'win_totals.json')
OUT = os.path.join(ROOT, 'data', 'futures_fit.json')
NS = 20000
CUTS = [0.0, 0.02, 0.05, 0.08, 0.12]
MONTHS = {'nba': 5.8, 'nfl': 4.2}
SPLIT = {'nba': (range(2016, 2022), range(2022, 2027)), 'nfl': (range(2015, 2018), range(2018, 2021))}
RSD = {'nba': 3.7, 'nfl': 5.0}


def dec(american):
    return 1 + (american / 100 if american > 0 else 100 / -american)


def sim_wins(teams, games, rsd, sd, seed):
    """games: (home, away, mu). Returns {team: array of NS simulated win totals} (ties count half)."""
    ix = {t: i for i, t in enumerate(teams)}
    h = np.array([ix[g[0]] for g in games]); a = np.array([ix[g[1]] for g in games])
    mu = np.array([g[2] for g in games])
    rs = np.random.default_rng(seed)
    W = np.zeros((NS, len(teams)))
    for lo in range(0, NS, 2000):
        n = min(2000, NS - lo)
        z = rs.standard_normal((n, len(teams))) * rsd
        m = mu[None, :] + z[:, h] - z[:, a] + sd * rs.standard_normal((n, len(mu)))
        hw = (m > 0).astype(float)
        for j in range(len(mu)):
            W[lo:lo + n, h[j]] += hw[:, j]; W[lo:lo + n, a[j]] += 1 - hw[:, j]
    return {t: W[:, i] for t, i in ix.items()}


# ---------------------------------------------------------------- NBA
def nba_preseason():
    import nba_games as N
    import nba_games_fit as NF
    F = json.load(open(N.FIT))
    games, names = N.load_hist()
    m = N.Model(names, F['P'], inj=NF.load_inj(), **F['params'])
    feats = F['feats']
    pre, rows = {}, []
    by = defaultdict(list)
    for g in games:
        by[g['S']].append(g)
    for g in games:
        if g['S'] != m.season:
            m.new_season(g['S'])
            fz = copy.deepcopy(m); fz.inj = {}
            pre[g['S']] = [(r, fz.feats(r)[0]) for r in by[g['S']] if r['t'] == 2]
        x, _ = m.feats(g)
        if g.get('fin'):
            rows.append((g['S'], [x[f] for f in feats], g['hs'] - g['as']))
        m.update(g)
    S = np.array([r[0] for r in rows]); X = np.array([r[1] for r in rows]); y = np.array([r[2] for r in rows], float)
    out = {}
    for s in range(2016, int(S.max()) + 1):
        tr = (S < s) & (S >= N.FIRST + 1)
        b = np.linalg.lstsq(X[tr], y[tr], rcond=None)[0]
        res = defaultdict(float)
        for r, _ in pre[s]:
            if r.get('fin'):
                res[r['h']] += r['hs'] > r['as']; res[r['a']] += r['as'] > r['hs']
        gm = [(r['h'], r['a'], float(np.dot([x[f] for f in feats], b))) for r, x in pre[s]]
        teams = sorted({t for g_ in gm for t in g_[:2]})
        W = sim_wins(teams, gm, RSD['nba'], F['sd'], 7 * s)
        out[s] = {t: {'W': W[t], 'act': res[t], 'n': sum(1 for g_ in gm if t in g_[:2])} for t in teams}
    return out


# ---------------------------------------------------------------- NFL
def nfl_preseason():
    import nfl_games as N
    import nfl_season_backtest as NB
    NB.WEEKS = (1,)
    F = json.load(open(N.FIT))
    G, box, qbs = N.load(2025)
    N.index_qbs(qbs, G); N.load_qb_teams(2025)
    inj = N.injury_history(G, range(N.INJ_FIRST, 2026))
    data, snaps = NB.walk(G, box, qbs, F['params'], inj)
    B = NB.coefs(data)[0]
    games = list(N.rows(N.get('games.csv', N.GAMES)))
    rest = lambda x: max(-7, min(7, N.num(x, 7) - 7))
    out = {}
    for s in range(2015, 2026):
        sg, res = N.season_results(games, s)
        b = B[s]
        R = {t: sum(b[f] * v[f] for f in ('elo', 'epa', 'qb', 'mkt')) for t, v in snaps[(s, 1)].items()}
        gm = [(N.team(g['home_team']), N.team(g['away_team']),
               R[N.team(g['home_team'])] - R[N.team(g['away_team'])] + (b['home'] if g['location'] != 'Neutral' else 0)
               + b['rest'] * (rest(g['home_rest']) - rest(g['away_rest']))) for g in sg]
        act = defaultdict(float)
        for (h, a, _), r in zip(gm, res):
            if r is not None:
                act[h] += r; act[a] += 1 - r
        teams = sorted(R)
        W = sim_wins(teams, gm, RSD['nfl'], F['sd'], 11 * s)
        out[s] = {t: {'W': W[t], 'act': act[t], 'n': sum(1 for g_ in gm if t in g_[:2])} for t in teams}
    return out


# ---------------------------------------------------------------- scoring
def probs(W, line, shift=0.0, k=1.0):
    """P(over), P(under) from the sims, the centre moved by shift and the spread scaled by k around it"""
    if shift or k != 1.0:
        c = W.mean()
        W = np.round((c + shift + k * (W - c)) * 2) / 2   # keep the support on whole and half wins
    return float(np.mean(W > line)), float(np.mean(W < line))


def tstat(v):
    v = np.asarray(v, float)
    if len(v) < 2 or v.std(ddof=1) == 0:
        return None
    return round(float(v.mean() / (v.std(ddof=1) / math.sqrt(len(v)))), 2)


def rho_within(bets):
    """Mean pairwise correlation of bet returns within a season, from the season sums: Var(sum) = n s2 (1 + (n-1) rho)."""
    by = defaultdict(list)
    for b in bets:
        by[b['S']].append(b['ret'])
    allr = np.array([b['ret'] for b in bets]); s2 = allr.var()
    if s2 == 0 or len(by) < 3:
        return None
    mu = allr.mean()
    num = sum((sum(v) - len(v) * mu) ** 2 - len(v) * s2 for v in by.values())
    den = sum(len(v) * (len(v) - 1) * s2 for v in by.values())
    return round(float(num / den), 3) if den else None


def summary(bets, months):
    if not bets:
        return {'n': 0}
    r = np.array([b['ret'] for b in bets])
    dec_ = [b for b in bets if b['res'] != 'push']
    by = defaultdict(list)
    for b in bets:
        by[b['S']].append(b['ret'])
    rho = rho_within(bets)
    m = len(bets) / len(by)
    roi = float(r.mean())
    return {'n': len(bets), 'won': sum(b['res'] == 'win' for b in bets), 'lost': sum(b['res'] == 'loss' for b in bets),
            'push': sum(b['res'] == 'push' for b in bets),
            'hit': round(sum(b['res'] == 'win' for b in dec_) / len(dec_), 3) if dec_ else None,
            'roi': round(roi, 4), 'ev': round(float(np.mean([b['ev'] for b in bets])), 4), 't': tstat(r),
            'tSeason': tstat([np.mean(v) for v in by.values()]), 'seasons': len(by), 'rho': rho,
            'nEff': round(min(len(bets), len(bets) / (1 + (m - 1) * rho)), 1) if rho is not None and rho > -1 / max(m - 1, 1) else None,
            'annual': round((1 + roi) ** (12 / months) - 1, 4) if roi > -1 else None}


def evaluate(sport, pre, lines):
    months = MONTHS[sport]
    tune, held = SPLIT[sport]
    L = {(r['S'], r['t']): r for r in lines}
    rows = []
    for s, teams in sorted(pre.items()):
        if sport == 'nba' and s == 2020:
            continue
        for t, d in teams.items():
            ln = L.get((s, t))
            if not ln:
                continue
            xw = float(d['W'].mean())
            rows.append({'S': s, 't': t, 'line': ln['line'], 'xW': round(xw, 2), 'act': d['act'],
                         'over': ln.get('over', -110), 'under': ln.get('under', -110), 'W': d['W']})
            if rows[-1]['over'] is None:
                rows[-1]['bet'] = False
    mk = lambda f: np.array([f(r) for r in rows], float)
    ours, line, act = mk(lambda r: r['xW']), mk(lambda r: r['line']), mk(lambda r: r['act'])
    S = mk(lambda r: r['S'])
    acc = {}
    for nm, k in (('all', np.ones(len(rows), bool)), ('tune', np.isin(S, list(tune))), ('held', np.isin(S, list(held)))):
        if not k.any():
            continue
        d, e = ours[k] - line[k], act[k] - line[k]
        b = float(np.dot(d, e) / np.dot(d, d))
        # cluster the slope's SE by season
        sc = [float(np.sum(d[(S[k] == s)] * (e[(S[k] == s)] - b * d[(S[k] == s)]))) for s in sorted(set(S[k]))]
        se = math.sqrt(sum(v * v for v in sc)) / float(np.dot(d, d))
        acc[nm] = {'n': int(k.sum()), 'maeOurs': round(float(np.mean(np.abs(ours[k] - act[k]))), 3),
                   'maeLine': round(float(np.mean(np.abs(line[k] - act[k]))), 3),
                   'rmseOurs': round(float(np.sqrt(np.mean((ours[k] - act[k]) ** 2))), 3),
                   'rmseLine': round(float(np.sqrt(np.mean((line[k] - act[k]) ** 2))), 3),
                   'corr': round(float(np.corrcoef(ours[k], line[k])[0, 1]), 3),
                   'gapSd': round(float(np.std(d)), 2), 'b': round(b, 3), 'bSe': round(se, 3), 'bT': round(b / se, 2) if se else None,
                   'simSd': round(float(np.mean([r['W'].std() for r, kk in zip(rows, k) if kk])), 2),
                   'residSd': round(float(np.std(act[k] - ours[k])), 2)}
    w = max(0.0, min(1.0, acc['tune']['b']))
    # the shrunk sim's spread: the tuning seasons' miss of line + w x gap, over the sims' own sd
    kt = np.isin(S, list(tune))
    ksd = float(np.std((act - line - w * (ours - line))[kt]) / acc['tune']['simSd'])

    def bets_at(wt, cut, seasons, k=None):
        k = (1.0 if wt == 1.0 else ksd) if k is None else k
        out = []
        for r in rows:
            if r['S'] not in seasons or r.get('bet') is False:
                continue
            po, pu = probs(r['W'], r['line'], -(1 - wt) * (r['xW'] - r['line']), k)
            eo = po * (dec(r['over']) - 1) - pu
            eu = pu * (dec(r['under']) - 1) - po
            side, ev, price = ('over', eo, r['over']) if eo >= eu else ('under', eu, r['under'])
            if ev < cut:
                continue
            a = r['act']
            res = 'push' if a == r['line'] else ('win' if (a > r['line']) == (side == 'over') else 'loss')
            ret = dec(price) - 1 if res == 'win' else (0.0 if res == 'push' else -1.0)
            out.append({'S': r['S'], 't': r['t'], 'side': side, 'line': r['line'], 'price': price, 'xW': r['xW'],
                        'p': round(po if side == 'over' else pu, 3), 'ev': round(ev, 4), 'act': a, 'res': res, 'ret': ret})
        return out

    allS = sorted({r['S'] for r in rows})
    grid = {}
    for wt, nm in ((1.0, 'raw'), (w, 'shrunk')):
        grid[nm] = {'w': round(wt, 3), 'cuts': []}
        for c in CUTS:
            grid[nm]['cuts'].append({'cut': c, 'tune': summary(bets_at(wt, c, tune), months),
                                     'held': summary(bets_at(wt, c, held), months), 'all': summary(bets_at(wt, c, allS), months)})
    # the cut: best tuning ROI with 20+ bets, on the shrunk sim
    ok = [c for c in grid['shrunk']['cuts'] if c['tune']['n'] >= 20]
    pick = max(ok, key=lambda c: c['tune']['roi']) if ok else grid['shrunk']['cuts'][0]
    chosen = bets_at(w, pick['cut'], allS)
    seasons = {}
    for s in allS:
        bs = [b for b in bets_at(w, 0.0, [s])]
        ch = [b for b in chosen if b['S'] == s]
        rr = [r for r in rows if r['S'] == s]
        seasons[str(s)] = {'teams': len(rr), 'maeOurs': round(float(np.mean([abs(r['xW'] - r['act']) for r in rr])), 2),
                           'maeLine': round(float(np.mean([abs(r['line'] - r['act']) for r in rr])), 2),
                           'every': summary(bs, months), 'rule': summary(ch, months)}
    # calibration of the chosen side's chance (all bets at the shrunk sim)
    cal = []
    every = [b for b in bets_at(w, 0.0, allS) if b['res'] != 'push']
    for lo, hi in ((0.5, 0.55), (0.55, 0.6), (0.6, 0.65), (0.65, 0.7), (0.7, 1.01)):
        k = [b for b in every if lo <= b['p'] < hi]
        if k:
            cal.append({'p': f'{lo:.2f}-{min(hi, 1):.2f}', 'n': len(k), 'pred': round(float(np.mean([b['p'] for b in k])), 3),
                        'hit': round(sum(b['res'] == 'win' for b in k) / len(k), 3)})
    return {'seasons': [min(allS), max(allS)], 'tune': [min(tune), max(tune)], 'held': [min(held), max(held)],
            'teamSeasons': len(rows), 'months': months, 'ratingSd': RSD[sport], 'accuracy': acc, 'w': round(w, 3), 'k': round(ksd, 3),
            'grid': grid, 'cut': pick['cut'], 'rule': {'tune': pick['tune'], 'held': pick['held'], 'all': summary(chosen, months)},
            'bySeason': seasons, 'calib': cal,
            'bets': [{k: v for k, v in b.items()} for b in chosen]}


def main():
    want = [a for a in sys.argv[1:] if a in ('nba', 'nfl')] or ['nba', 'nfl']
    H = json.load(open(HIST))
    res = json.load(open(OUT)) if os.path.exists(OUT) else {}
    import pickle
    os.makedirs(os.path.join(ROOT, 'scripts', '.cache'), exist_ok=True)
    for sp in want:
        cp = os.path.join(ROOT, 'scripts', '.cache', f'futures_pre_{sp}.pkl')
        if os.path.exists(cp) and '--fresh' not in sys.argv:
            pre = pickle.load(open(cp, 'rb'))
        else:
            pre = nba_preseason() if sp == 'nba' else nfl_preseason()
            pickle.dump(pre, open(cp, 'wb'))
        if sp == 'nfl':
            # model-only accuracy for the seasons past the free lines (2021-25)
            res['nflModelOnly'] = {str(s): round(float(np.mean([abs(d['W'].mean() - d['act']) for d in pre[s].values()])), 3)
                                   for s in range(2021, 2026)}
        res[sp] = evaluate(sp, pre, H[sp])
        r = res[sp]
        print(sp, json.dumps(r['accuracy'], indent=0))
        print(sp, 'w', r['w'], 'k', r['k'], 'cut', r['cut'], json.dumps(r['rule'], indent=0))
        for nm in ('raw', 'shrunk'):
            for c in r['grid'][nm]['cuts']:
                print(sp, nm, c['cut'], 'tune', c['tune'].get('n'), c['tune'].get('roi'), c['tune'].get('tSeason'),
                      '| held', c['held'].get('n'), c['held'].get('roi'), c['held'].get('tSeason'))
    res['asof'] = H['asof']
    res['excluded'] = {'cfb': 'no free win-total history (sportsoddshistory/covers and Pro-Football-Reference block bots; Kalshi college win markets start in 2026)',
                       'cbb': 'no free win-total history'}
    with open(OUT, 'w') as f:
        json.dump(res, f, separators=(',', ':'))


if __name__ == '__main__':
    main()
