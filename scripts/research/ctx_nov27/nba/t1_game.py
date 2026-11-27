"""T1: the game model's player value (nba_games.values: two seasons, n0 300 to -2) vs pXPM of the season before
(A: with aging, B: without). The fit's own walk-forward on the live feature list; rule t <= -1.5 on 2015-21 and
2022-26 no worse.  -> t1_game.json"""
import json, os, sys, time
import numpy as np
import common as C
N = C.N
import nba_games_fit as Fit

F = json.load(open(N.FIT)); P, feats, base = F['P'], F['feats'], F['params']
games, names = N.load_hist()
games = [g for g in games if g['S'] <= C.LAST]
inj = Fit.load_inj()
LIVE = N.values
_ROWS = {}


def rows(S):
    if S not in _ROWS:
        d = {}
        for p in C.F.get(S, {}).get('p', {}).values():
            k = N.norm(p['n'])
            if k not in d or d[k]['mp'] < p['mp']: d[k] = p
        _ROWS[S] = d
    return _ROWS[S]


def get(S, nm):
    r = rows(S).get(N.norm(nm))
    if r or S not in C.F: return r
    h, _ = N.xpm_season(S)[1].find(nm)
    return rows(S).get(N.norm(h['n'])) if h else None


def make(aging):
    def values(S, nms, n0=600.0, rook=-2.0, w2=0.5, age=0, ret=0):
        out = LIVE(S, nms, n0, rook, w2, age, ret)
        if S - 1 not in C.F: return out
        for pid, nm in nms.items():
            a = get(S - 1, nm)
            if a: out[pid] = C.pxpm_row(a, C.F[S - 1]['g'], [get(S - 2, nm), get(S - 3, nm)], S - 1, aging)
        return out
    return values


def design(vf):
    N.values = vf
    _, data = N.walk(games, names, P, base, inj=inj)
    D = [(g, x) for g, x, _ in data if g.get('fin') and g['S'] >= N.FIRST + 1]
    X = {f: np.array([x[f] for _, x in D], float) for f in feats}
    y = np.array([g['hs'] - g['as'] for g, _ in D], float); S = np.array([g['S'] for g, _ in D])
    return Fit.wf(Fit.mat(X, feats), y, S), y, S


t0 = time.time()
ref, y, S = design(LIVE); print('live walk', round(time.time() - t0), 's', flush=True)
k1 = (S >= N.SCORE_FROM) & (S < N.HOLD_FROM); k2 = S >= N.HOLD_FROM
res = {'live': {nm: round(float(np.abs(ref[k] - y[k]).mean()), 4) for nm, k in (('2015_21', k1), ('2022_26', k2))}}
for lab, ag in (('A pXPM', True), ('B pXPM no aging', False)):
    pr, _, _ = design(make(ag)); r = {}
    for nm, k in (('2015_21', k1), ('2022_26', k2)):
        e, e0 = np.abs(pr[k] - y[k]), np.abs(ref[k] - y[k])
        ss = sorted(set(S[k]))
        r[nm] = {'n': int(k.sum()), 'mae': round(float(e.mean()), 4), 'd': round(float(e.mean() - e0.mean()), 4), 't': round(Fit.paired_t(e, e0), 2),
                 'seasons': f"{sum(e[S[k] == s].mean() < e0[S[k] == s].mean() for s in ss)}/{len(ss)}"}
    r['pass'] = bool(r['2015_21']['t'] <= -1.5 and r['2022_26']['d'] <= 0)
    res[lab] = r; print(lab, json.dumps(r), flush=True)
json.dump(res, open(os.path.join(C.HERE, 't1_game.json'), 'w'), indent=1)
