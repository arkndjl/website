"""Walk-forward NFL margin + total predictions (live model in scripts/nfl_games.py) in the cross-sport schema.
Each season s >= 2015 is predicted by least squares fit on seasons 2012..s-1 (same as nfl_games.fit / nfl_picks.backtest)."""
import sys, os, json, gzip
import numpy as np
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, 'scripts'))
import nfl_games as N

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'games_wf', 'nfl.json.gz')


def odds(x):
    v = N.num(x, None)
    return None if v is None or v == 0 else v


def main():
    F = json.load(open(N.FIT))
    allg = list(N.rows(N.get('games.csv', N.GAMES)))
    last = max(int(g['season']) for g in allg if g['home_score'] not in ('', 'NA'))
    games, box, qbs = N.load(last)
    N.index_qbs(qbs, games); N.load_qb_teams(last)
    yrs = range(N.INJ_FIRST, last + 1)
    inj = N.injury_history(games, yrs, live=last if last > 2025 else None)
    _, data = N.walk(games, box, qbs, F['params'])
    D = []
    for g, x, tx in data:
        if g['home_score'] in ('', 'NA') or int(g['season']) < 2012:
            continue
        r = inj.get(g['game_id'])
        if r:
            x['inj'] = (r[2] + r[3]) - (r[0] + r[1])
        D.append((g, x, tx))
    X = np.array([[x[f] for f in N.FEATS] for _, x, _ in D]); y = np.array([N.num(g['result']) for g, _, _ in D])
    TX = np.array([[tx[f] for f in N.TFEATS] for _, _, tx in D]); ty = np.array([N.num(g['total']) for g, _, _ in D])
    S = np.array([int(g['season']) for g, _, _ in D])
    pred = np.full(len(y), np.nan); tpred = np.full(len(y), np.nan)
    for s in range(2015, last + 1):
        tr, te = S < s, S == s
        pred[te] = X[te] @ np.linalg.lstsq(X[tr], y[tr], rcond=None)[0]
        tpred[te] = TX[te] @ np.linalg.lstsq(TX[tr], ty[tr], rcond=None)[0]
    out = []
    for (g, _, _), m, tm, s in zip(D, pred, tpred, S):
        L = N.num(g['spread_line'], None)
        if s < 2015 or L is None:
            continue
        T = N.num(g['total_line'], None)
        out.append({'sport': 'nfl', 'S': int(s), 'id': g['game_id'], 'date': g['gameday'], 'home': g['home_team'],
                    'away': g['away_team'], 'wk': int(g['week']), 'm': round(float(m), 3), 'L': L, 'Lo': None,
                    'res': N.num(g['result']), 'mlH': odds(g['home_moneyline']), 'mlA': odds(g['away_moneyline']),
                    'oH': odds(g['home_spread_odds']), 'oA': odds(g['away_spread_odds']),
                    'tm': round(float(tm), 3), 'T': T, 'To': None, 'tot': N.num(g['total']),
                    'oO': odds(g['over_odds']), 'oU': odds(g['under_odds']), 'po': int(g['game_type'] != 'REG')})
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with gzip.open(OUT, 'wt') as f:
        json.dump(out, f)
    # report
    from collections import Counter
    print('rows by season', dict(sorted(Counter(r['S'] for r in out).items())), 'total', len(out))
    a = lambda k, f: np.array([r[k] for r in out if f(r)], float)
    ho = lambda r: 2021 <= r['S'] <= 2025
    m, L, res = a('m', ho), a('L', ho), a('res', ho)
    print('2021-25 n', len(m), 'MAE m', round(np.mean(np.abs(m - res)), 3), 'MAE L', round(np.mean(np.abs(L - res)), 3))
    ht = lambda r: ho(r) and r['T'] is not None
    tm, T, tot = a('tm', ht), a('T', ht), a('tot', ht)
    print('2021-25 totals n', len(tm), 'MAE tm', round(np.mean(np.abs(tm - tot)), 3), 'MAE T', round(np.mean(np.abs(T - tot)), 3),
          'mean|tm-T|', round(np.mean(np.abs(tm - T)), 3))
    allm, allL, allr = a('m', lambda r: True), a('L', lambda r: True), a('res', lambda r: True)
    tt = lambda r: r['T'] is not None
    print('sd(m-res) 2015-25', round(float(np.std((allm - allr)[np.array([r['S'] <= 2025 for r in out])])), 3), 'fit sd', F['sd'], 'tsd', F['tsd'])
    print('corr(L,res)', round(np.corrcoef(allL, allr)[0, 1], 3), 'corr(m,L)', round(np.corrcoef(allm, allL)[0, 1], 3),
          'corr(tm,T)', round(np.corrcoef(a('tm', tt), a('T', tt))[0, 1], 3))
    k26 = [r for r in out if r['S'] == 2026]
    if k26:
        mm, ll, rr = (np.array([r[k] for r in k26]) for k in ('m', 'L', 'res'))
        print('2026 n', len(k26), 'MAE m', round(np.mean(np.abs(mm - rr)), 3), 'MAE L', round(np.mean(np.abs(ll - rr)), 3))
    nulls = {k: sum(r[k] is None for r in out) for k in ('mlH', 'mlA', 'oH', 'oA', 'T', 'oO', 'oU')}
    print('nulls', nulls)


main()
