# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Lead 1b (PREREG.md): DARKO first-week DPM next to the board's preseason prior for season XPM.

    python3 darko_prior_test.py DARKO_DIR     # -> impl/nba/darko_prior.json

Rows: 500+ MP player-seasons 2016-2026 matched in the first-week snapshot. a + b prior vs a + b prior + c DPM, leave
one season out; squared error against the season's XPM, paired, clustered by season. XPM is half DPM: upper bound."""
import json, os, sys
import numpy as np
import common as C
import nba_xpm as X
import nba_proj as P


def main():
    rows = []
    for S in range(2016, 2027):
        d = '2020-12-27' if S == 2021 else f'{S - 1}-11-01'
        snap = json.load(open(os.path.join(sys.argv[1], f'dpm_{d}.json')))
        board = [p for p in P.load(S)['players'] if p.get('xpm') is not None and not p.get('pr') and p['mp'] >= 500]
        find = C.matcher([(p['id'], p['n']) for p in board])
        dk = {}
        for nid, v in snap.items():
            pid = find(v[0])
            if pid: dk[pid] = v[2]
        prior = X.prior_xpm(S)
        for p in board:
            if p['id'] in dk:
                rows.append((S, prior(p['id'])[0], dk[p['id']], p['xpm']))
        print(S, len(board), sum(p['id'] in dk for p in board), flush=True)
    A = np.array(rows, float); S, pr, dk, y = A[:, 0], A[:, 1], A[:, 2], A[:, 3]
    one = np.ones(len(y))
    e0, e1 = np.zeros(len(y)), np.zeros(len(y))
    for s in sorted(set(S)):
        tr, te = S != s, S == s
        for X_, e in ((np.column_stack([one, pr]), e0), (np.column_stack([one, pr, dk]), e1)):
            e[te] = (X_[te] @ np.linalg.lstsq(X_[tr], y[tr], rcond=None)[0] - y[te]) ** 2
    d = e1 - e0
    res = {'n': len(y), 'coefAll': [round(float(v), 3) for v in np.linalg.lstsq(np.column_stack([one, pr, dk]), y, rcond=None)[0]]}
    for nm, k in (('tune', S <= 2021), ('held', S >= 2022)):
        p = C.paired(d[k], S[k]); ss = sorted(set(S[k]))
        res[nm] = {'n': int(k.sum()), 'rmse0': round(float(np.sqrt(e0[k].mean())), 4), 'rmse1': round(float(np.sqrt(e1[k].mean())), 4), 'd': round(p['d'], 4), 't': round(p['t'], 2),
                   'seasonsLower': int(sum(d[S == s].mean() < 0 for s in ss)), 'seasons': len(ss)}
    res['p'] = C.p2(res['held']['t']) if res['held']['t'] < 0 else 1.0
    res['pass_pre_holm'] = bool(res['held']['t'] <= -2 and res['tune']['d'] < 0 and res['held']['seasonsLower'] * 2 > res['held']['seasons'])
    print(json.dumps(res, indent=1))
    json.dump(res, open(os.path.join(C.IMPL, 'darko_prior.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
