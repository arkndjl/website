#!/usr/bin/env python3
"""In-season player values for the NBA game model (team model idea 4, Oct 23 2026).

nba_games.values() freezes every player at his XPM from the two seasons before. Here each player's value moves
through the season: a box-score estimate of his XPM from this season's games to date (games before tip only) is
the data, his opening value the prior, and the posterior is a minutes-weighted blend

    value = (prior x k + box XPM to date x minutes) / (k + minutes)

with k (prior minutes) tuned on 2015-21 and a separate kr for players with no NBA seasons behind them (rookies,
newcomers: a weak prior). The box XPM: season XPM regressed on per-48 box rates (points, shots, free throws,
threes, rebounds, assists, steals, blocks, turnovers, fouls, on-court plus-minus), minutes-weighted, fit each
season only on the seasons before it.

    python3 scripts/nba_inseason.py --pull          # ESPN box lines for every game in nba_games_hist -> BOX
    python3 scripts/nba_inseason.py --players       # player level: prior vs posterior on rest-of-season box XPM
    python3 scripts/nba_inseason.py --games [--only i,j]   # game model walks with ik / ikr, paired t on margin error

Results -> data/nba_inseason_research.json. BOX (4 MB, 2013-26) is not in the repo: --pull rebuilds it from ESPN in
~10 min, and a copy sits in the project files (team-models/nba_box_hist.json.gz).

Result (Oct 23 2026): FAILED for the game model, not shipped (ik/ikr/ib stay off in nba_games.Model).
- Player level it works: the posterior (k ~750 min for veterans, ~250-500 for newcomers) cuts rest-of-season error
  7-12% against the opening value by a player's 10th-20th game.
- Games: every k from 1,000 to 5,000, newcomers only (kr 300/800), and with the lineup baseline at today's values
  (ib) is flat or worse: tune t -0.5 to +0.7, held out +0.002 to +0.010 MAE. Early season (first fifth) it hurts
  (+.02), mid/late it is zero.
- Ceiling: season-end XPM (or season-end box XPM) leaked in as the value helps .03-.04 (t -4/-3.5), but the gain is
  almost all in the first fifth of the season: knowledge of how players will play, which no to-date estimate has.
  Mid-season, team ratings and the closing spread already carry what this season's box scores say.
"""
import gzip
import json
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.dirname(HERE)
BOX = os.path.join(HERE, 'nba_box_hist.json.gz')       # outside data/: Hugo would load it on every build
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'nba', 'pbox')
OUT = os.path.join(ROOT, 'data', 'nba_inseason_research.json')
# a box line: ESPN athlete id, then minutes, pts, fgm, fga, 3pm, 3pa, ftm, fta, oreb, dreb, ast, stl, blk, tov, pf, +/-
COLS = ['min', 'pts', 'fgm', 'fga', 'fg3m', 'fg3a', 'ftm', 'fta', 'oreb', 'dreb', 'ast', 'stl', 'blk', 'tov', 'pf', 'pm']
RATES = ['pts', 'fga', 'fta', 'fg3m', 'oreb', 'dreb', 'ast', 'stl', 'blk', 'tov', 'pf', 'pm']


def _sp(s):
    try:
        a, b = s.split('-')
        return [int(a), int(b)]
    except (ValueError, AttributeError):
        return [0, 0]


def _n(s):
    try:
        return int(str(s).replace('+', ''))
    except (TypeError, ValueError):
        return 0


def lines_of(j):
    """ESPN summary json -> {team: [box line]} (players who played)"""
    import nba_espn as E
    out = {}
    for t in (j.get('boxscore') or {}).get('players', []):
        ab = E.team(t['team']['abbreviation'])
        rows = []
        for st in t.get('statistics', [])[:1]:
            names = st.get('names') or []
            for p in st.get('athletes', []):
                d = dict(zip(names, p.get('stats', [])))
                mn = _n(d.get('MIN'))
                if not mn:
                    continue
                rows.append([p.get('athlete', {}).get('id'), mn, _n(d.get('PTS')), *_sp(d.get('FG', '')),
                             *_sp(d.get('3PT', '')), *_sp(d.get('FT', '')), _n(d.get('OREB')), _n(d.get('DREB')),
                             _n(d.get('AST')), _n(d.get('STL')), _n(d.get('BLK')), _n(d.get('TO')), _n(d.get('PF')),
                             _n(d.get('+/-'))])
        out[ab] = rows
    return out


def pull(workers=16):
    import nba_espn as E
    import nba_games as N
    from concurrent.futures import ThreadPoolExecutor
    os.makedirs(CACHE, exist_ok=True)
    games, _ = N.load_hist()

    def one(gid):
        fn = os.path.join(CACHE, f'{gid}.json')
        if not os.path.exists(fn):
            j = E.get(f'{E.SITE}/summary?event={gid}')
            E.save(fn, lines_of(j) if j and 'boxscore' in j else None)
    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, [g['id'] for g in games]))
    out = {}
    for g in games:
        fn = os.path.join(CACHE, f"{g['id']}.json")
        b = json.load(open(fn)) if os.path.exists(fn) else None
        if b and all(sum(r[1] for r in b.get(t, [])) > 150 for t in (g['h'], g['a'])):
            out[g['id']] = b
    with gzip.open(BOX, 'wt') as f:
        json.dump(out, f, separators=(',', ':'))
    print(len(out), 'of', len(games), 'games with box lines')


_BX = {}


def load_box():
    if not _BX:
        try:
            with gzip.open(BOX, 'rt') as f:
                _BX.update(json.load(f))
        except OSError:
            pass
    return _BX


IX = [COLS.index(c) for c in RATES]


def feats(v, lg):
    """per-48 rates of a summed box line (minutes first, as in COLS) over the league's rates (lg: the league's summed
    line over the same stretch), so scoring's drift across seasons doesn't move the estimate"""
    m = v[0]
    return np.append((v[IX] / m - lg[IX] / lg[0]) * 48.0, 1.0) if m > 0 else None


_CF = {}


def season_lines(S):
    """{ESPN id: summed regular-season box line} for season S, from the history file"""
    import nba_games as N
    games, _ = _hist()
    bx = load_box()
    tot = defaultdict(lambda: np.zeros(len(COLS)))
    for g in games:
        if g['S'] != S or g['t'] != 2 or g['id'] not in bx:
            continue
        for t, rows in bx[g['id']].items():
            for r in rows:
                if r[0]:
                    tot[r[0]] += np.array(r[1:], float)
    return tot


def league(lines):
    return np.sum(list(lines.values()), 0)


_H = {}


def _hist():
    import nba_games as N
    if not _H:
        _H['g'] = N.load_hist()
    return _H['g']


def coef(S, ridge=50.0, mn=250):
    """box -> XPM weights fit on the seasons before S (minutes-weighted ridge, intercept free); None before 2014"""
    if S in _CF:
        return _CF[S]
    import nba_games as N
    _, names = _hist()
    X, y, w = [], [], []
    for s in range(2013, S):
        sl = season_lines(s); lg = league(sl)
        for pid, v in sl.items():
            if v[0] < mn:
                continue
            r = N.lookup(s, names.get(pid, ''))
            if not r or r[1] < mn:
                continue
            X.append(feats(v, lg)); y.append(r[0]); w.append(min(v[0], r[1]))
    if len(y) < 200:
        _CF[S] = None
        return None
    X, y, w = np.array(X), np.array(y), np.array(w)
    sw = np.sqrt(w)[:, None]
    mu = (X[:, :-1] * w[:, None]).sum(0) / w.sum()
    Z = X.copy(); Z[:, :-1] -= mu
    R = np.eye(X.shape[1]) * ridge; R[-1, -1] = 0
    b = np.linalg.solve((Z * sw).T @ (Z * sw) + R, (Z * sw).T @ (y * np.sqrt(w)))
    b[-1] -= mu @ b[:-1]                                    # back to raw rates
    _CF[S] = b
    return b


def box_xpm(v, b, lg):
    return float(feats(v, lg) @ b)


# ---------------------------------------------------------------- research
def save(key, rows):
    try:
        d = json.load(open(OUT))
    except (OSError, ValueError):
        d = {}
    d[key] = rows
    with open(OUT, 'w') as f:
        json.dump(d, f, indent=1)


def players():
    """player level: at each player's 10th/20th/40th game, prior and posterior (grid of k) against the box XPM of
    the rest of his regular season (minutes-weighted squared error; the rest-of-season estimate is noisy but not
    biased toward either side)"""
    import nba_games as N
    games, names = _hist()
    bx = load_box()
    F = json.load(open(N.FIT))
    out = {'fit': {}, 'cut': []}
    # how well the box regression fits season XPM, out of sample
    for S in range(2014, 2027):
        b = coef(S)
        sl = season_lines(S); lg = league(sl)
        e, w = [], []
        for pid, v in sl.items():
            r = N.lookup(S, names.get(pid, ''))
            if v[0] >= 500 and r and r[1] >= 500:
                e.append(box_xpm(v, b, lg) - r[0]); w.append(v[0])
        e, w = np.array(e), np.array(w)
        out['fit'][S] = {'n': len(e), 'rmse': round(float(np.sqrt((e ** 2 * w).sum() / w.sum())), 3),
                         'bias': round(float((e * w).sum() / w.sum()), 3)}
        print(S, out['fit'][S], flush=True)
    KS = [0, 250, 500, 750, 1000, 1500, 2000, 3000, 5000, 1e9]
    acc = defaultdict(lambda: [0.0, 0.0])
    for S in range(2015, 2027):
        b = coef(S)
        val = N.values(S, names, F['params']['n0'], F['params']['rook'], ret=F['params'].get('ret', 0))
        known = {pid for pid, nm in names.items() if N.lookup(S - 1, nm) or N.lookup(S - 2, nm)}
        seq = defaultdict(list)                             # pid -> box lines in game order
        lgs = []                                            # the league's line to date, game by game
        lg = np.zeros(len(COLS))
        for g in games:
            if g['S'] == S and g['t'] == 2 and g['id'] in bx:
                for t, rows in bx[g['id']].items():
                    for r in rows:
                        lg = lg + np.array(r[1:], float)
                        if r[0]:
                            seq[r[0]].append((np.array(r[1:], float), len(lgs)))
                lgs.append(lg)
        lgS = lgs[-1]
        for pid, ls in seq.items():
            ix = [i for _, i in ls]
            ls = [x for x, _ in ls]
            tot = np.sum(ls, 0)
            for c in (10, 20, 40):
                if len(ls) < c + 10:
                    continue
                pre = np.sum(ls[:c], 0); post = tot - pre
                if pre[0] < 100 or post[0] < 300:
                    continue
                tgt, wt = box_xpm(post, b, lgS - lgs[ix[c - 1]]), post[0]
                d, m, pr = box_xpm(pre, b, lgs[ix[c - 1]]), pre[0], val.get(pid, F['params']['rook'])
                grp = 'vet' if pid in known else 'new'
                for k in KS:
                    v = (pr * k + d * m) / (k + m)
                    a = acc[(grp, c, k)]
                    a[0] += wt * (v - tgt) ** 2; a[1] += wt
    for (grp, c, k), (s, w) in sorted(acc.items(), key=lambda x: (x[0][0], x[0][1], x[0][2])):
        out['cut'].append({'grp': grp, 'game': c, 'k': k if k < 1e8 else 'prior', 'rmse': round(float(np.sqrt(s / w)), 4)})
        print(grp, c, k, round(float(np.sqrt(s / w)), 4))
    save('players', out)


def attach(games):
    """each history game gets its box lines ('bx'), for Model.update"""
    bx = load_box()
    for g in games:
        if g['id'] in bx:
            g['bx'] = bx[g['id']]
    return games


V = [('base', {}),
     ('k 1000', {'ik': 1000}), ('k 1500', {'ik': 1500}), ('k 2500', {'ik': 2500}),
     ('k 1500 kr 500', {'ik': 1500, 'ikr': 500}), ('k 2500 kr 750', {'ik': 2500, 'ikr': 750}),
     # 6-: the lineup baseline at today's values (ib)
     ('ib only', {'ib': 1}), ('ib k 1000', {'ik': 1000, 'ib': 1}), ('ib k 2500', {'ik': 2500, 'ib': 1}),
     ('ib k 1000 kr 400', {'ik': 1000, 'ikr': 400, 'ib': 1}), ('ib k 5000', {'ik': 5000, 'ib': 1}),
     # 11-: newcomers only (vets stay at their opening value)
     ('new only kr 300', {'ik': 1e9, 'ikr': 300}), ('new only kr 300 ib', {'ik': 1e9, 'ikr': 300, 'ib': 1}),
     ('new only kr 800', {'ik': 1e9, 'ikr': 800})]


def _one(v):
    import lineup_adj_research as LA
    import nba_games as N
    F = json.load(open(N.FIT))
    if not LA._NBA:
        LA.nba_design(F['params'])                          # loads the history once per worker
    attach(LA._NBA['G'])
    return v[0], LA.nba_design({**F['params'], **v[1]})


def games():
    from multiprocessing import Pool
    import lineup_adj_research as LA
    import nba_games as N
    import nba_games_fit as Fit
    F = json.load(open(N.FIT))
    VV = V
    if '--only' in sys.argv:
        VV = [V[0]] + [V[int(i)] for i in sys.argv[sys.argv.index('--only') + 1].split(',')]
    with Pool(int(os.environ.get('PROCS', 4))) as pool:
        res = dict(pool.map(_one, VV))
    b = res['base']
    y, S, line = b['y'], b['S'], b['line']
    k1 = (S >= N.SCORE_FROM) & (S < N.HOLD_FROM); k2 = S >= N.HOLD_FROM
    ref = Fit.wf(Fit.mat(b['X'], F['feats']), y, S)
    rows = []
    for lab, extra in VV[1:]:
        pr = Fit.wf(Fit.mat(res[lab]['X'], F['feats']), y, S)
        rows.append(LA.score(lab, pr, ref, y, line, k1, k2, [b['day'], b['team']], {'params': extra}))
    try:
        old = json.load(open(OUT)).get('games', [])
    except (OSError, ValueError):
        old = []
    save('games', [r for r in old if r['label'] not in {x['label'] for x in rows}] + rows)


if __name__ == '__main__':
    a = sys.argv[1:]
    if '--pull' in a:
        pull()
    elif '--players' in a:
        players()
    elif '--games' in a:
        games()
