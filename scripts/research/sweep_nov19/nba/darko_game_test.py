# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Lead 1a (PREREG.md): DARKO as-of DPM mixed into the game model's player values at the sampled dates.

    python3 darko_game_test.py DARKO_DIR    # -> impl/nba/darko_game.json

From the day after each sample date each matched player's value = (1 - w) x opening value + w x DPM on the value
scale (mean and sd matched on the matched players); lineup baselines are revalued with the same table (the model's
ib switch). Walk-forward refit of the shipped margin coefficients; tune 2016-21 picks w, held 2022-26."""
import datetime as dt, glob, json, os, sys
import numpy as np
import common as C
import nba_games as N
import nba_games_fit as Fit
import harness as H


def snapshots(folder):
    out = {}
    for fn in sorted(glob.glob(os.path.join(folder, 'dpm_*.json'))):
        d = dt.date.fromisoformat(os.path.basename(fn)[4:-5])
        out[d] = json.load(open(fn))
    return out


def main():
    F = json.load(open(N.FIT))
    G, names = N.load_hist()
    inj = Fit.load_inj()
    P, feats, base = F['P'], F['feats'], F['params']
    snaps = snapshots(sys.argv[1])
    dates = sorted(snaps)
    pool = {}
    for g in G:
        for t, L in (g.get('pl') or {}).items():
            for pid, _ in L: pool.setdefault(g['S'], set()).add(pid)

    def design(params, w=None):
        m = N.Model(names, P, inj=inj, **params)
        data, S0, val0, nxt, maps = [], None, None, 0, {}
        for g in G:
            x, tx = m.feats(g) if w is None else (None, None)
            if w is not None:
                day = N.gday(N.tipdt(g))
                # m.feats starts the season: peek the season first so the opening table is the shipped one
                if g['S'] != S0:
                    x, tx = m.feats(g); S0 = g['S']; val0 = dict(m.val)
                    while nxt < len(dates) and dates[nxt] < day - dt.timedelta(days=200): nxt += 1
                else:
                    moved = False
                    while nxt < len(dates) and dates[nxt] < day:
                        cur = dates[nxt]; nxt += 1; moved = True
                    if moved and (day - cur).days < 120:
                        if cur not in maps:
                            find = C.matcher([(pid, names[pid]) for pid in pool.get(g['S'], ()) if pid in names])
                            maps[cur] = {pid: v[2] for nid, v in snaps[cur].items() for pid in [find(v[0])] if pid}
                        dv = {p: v for p, v in maps[cur].items() if p in val0}
                        if len(dv) >= 100:
                            xs = np.array(list(dv.values())); ys = np.array([val0[p] for p in dv])
                            mx, sx, my, sy = xs.mean(), xs.std(), ys.mean(), ys.std()
                            for p, v in dv.items():
                                m.val[p] = (1 - w) * val0[p] + w * (my + (v - mx) * sy / sx)
                    x, tx = m.feats(g)
            data.append((g, x, tx))
            m.update(g)
        D = [(g, x) for g, x, _ in data if g.get('fin') and g['S'] >= N.FIRST + 1]
        X = {f: np.array([x[f] for _, x in D], float) for f in D[0][1]}
        meta = dict(y=np.array([g['hs'] - g['as'] for g, _ in D], float), S=np.array([g['S'] for g, _ in D]),
                    L=np.array([g['L'] if g.get('L') is not None else np.nan for g, _ in D]),
                    day=np.array([g['tip'][:10] for g, _ in D]), hts=np.array([f"{g['h']}{g['S']}" for g, _ in D]))
        return X, meta

    X0, M = design(base)
    y, S, L = M['y'], M['S'], M['L']
    ref = Fit.wf(Fit.mat(X0, feats), y, S)
    Xi, _ = design({**base, 'ib': 1})
    refi = Fit.wf(Fit.mat(Xi, feats), y, S)
    lined = ~np.isnan(L)
    k1 = (S >= 2016) & (S <= 2021) & lined; k2 = (S >= 2022) & lined
    sd = float(F['sd']); Phi = np.vectorize(N.phi)
    res = {'n': {'tune': int(k1.sum()), 'held': int(k2.sum())}, 'ibOnly': {}, 'w': {}}

    def score(pr, k):
        e, e0 = np.abs(pr[k] - y[k]), np.abs(ref[k] - y[k])
        pd_ = H.paired(e, e0, cluster=[M['day'][k], M['hts'][k]])
        win = (y[k] > 0).astype(float)
        ll = lambda mm: -(win * np.log(Phi(mm / sd)) + (1 - win) * np.log(1 - Phi(mm / sd)))
        pl = H.paired(ll(pr[k]), ll(ref[k]), cluster=[M['day'][k], M['hts'][k]])
        return {'mae': round(float(e.mean()), 4), 'mae0': round(float(e0.mean()), 4), 'close': round(float(np.abs(L[k] - y[k]).mean()), 4),
                'd': round(float(pd_['d']), 4), 't': round(float(pd_['t']), 2), 'dLL': round(float(pl['d']), 5), 'tLL': round(float(pl['t']), 2),
                'seasonsLower': int(sum((np.abs(pr - y) - np.abs(ref - y))[k & (S == s)].mean() < 0 for s in sorted(set(S[k])))), 'seasons': int(len(set(S[k])))}
    res['ibOnly'] = {'tune': score(refi, k1), 'held': score(refi, k2)}
    print('ib only', res['ibOnly'], flush=True)
    for w in (0.25, 0.5, 0.75):
        X, _ = design({**base, 'ib': 1}, w)
        pr = Fit.wf(Fit.mat(X, feats), y, S)
        res['w'][str(w)] = {'tune': score(pr, k1), 'held': score(pr, k2)}
        print(w, res['w'][str(w)], flush=True)
    pick = min(res['w'], key=lambda k: res['w'][k]['tune']['mae'])
    r = res['w'][pick]
    res['pick'] = pick
    res['pass'] = bool(r['tune']['t'] <= -1.5 and r['held']['t'] <= -2 and r['held']['seasonsLower'] >= 3)
    res['pHeld'] = C.p2(r['held']['t']) if r['held']['t'] < 0 else 1.0
    print('pick', pick, 'pass', res['pass'])
    json.dump(res, open(os.path.join(C.IMPL, 'darko_game.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
