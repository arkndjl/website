"""F4 (prereg.md): add-ons to the CBB conviction fit (scripts/cbb_mock.py fit_conv: lnpick, bpm3, age on career peak
XPM, 2017-23 imputed), leave one draft out with the script's own functions.

    python3 scripts/research/mocks_nov23/cbb_conv.py   -> scripts/research/mocks_nov23/cbb_conv.json"""
import json, math, os
import numpy as np
from common import OUT, paired, holm
import cbb_data as D
import cbb_mock as M
import cbb_conv_backtest as CB
import cbb_feats as CF

BASE = ['lnpick', 'bpm3', 'age']
ADD = ['aa', 'poy', 'cpoy', 'trend', 'hm', 'ht', 'comb']


def main():
    rows = CB.rows_with_targets()
    tg = CB.impute(rows, ['age'])
    for r in rows: r['y'] = tg(r)
    cs = {c['name'] + '|' + str((c['nba'] or {}).get('draft')): c for c in CF.careers()}
    miss = 0
    for r in rows:
        c = cs.get(r['name'] + '|' + str(r['year']))
        ss = [s for s in (c or {}).get('seasons', []) if s['year'] <= r['year']]
        if not ss: miss += 1; continue
        L = ss[-1]; p = {'name': c['name'], 'school': L['team']}
        CF.attach(p, L['year'], final_season=True)
        for k in ADD: r['f'][k] = p.get(k, 0.0)
    for r in rows:
        for k in ADD: r['f'].setdefault(k, 0.0)
    rm0, per0, e0 = M.lodo_rmse(rows, BASE)
    s0 = M.lodo_slot(rows, e0)
    cover = {'n': len(rows), 'unmatched': miss} | {k: int(sum(1 for r in rows if r['f'][k])) for k in ADD}
    tests = []
    for k in ADD:
        rm, per, e = M.lodo_rmse(rows, BASE + [k])
        res = paired(e0 ** 2, e ** 2, [r['year'] for r in rows])
        X, mu, sd = M.design(rows, BASE + [k]); b, se = CB.clustered(X, M.centred(rows), np.array([r['year'] for r in rows]))
        res.update({'model': 'F4', 'driver': k, 'rmse': [round(rm0, 4), round(rm, 4)], 'slotErr': [round(s0, 4), round(M.lodo_slot(rows, e), 4)],
                    'perSd': round(float(b[-1]), 3), 'tClustered': round(float(b[-1] / se[-1]), 2),
                    'winsRmse': int(sum(per[y] < per0[y] for y in per0)), 'of': len(per0)})
        tests.append(res)
    holm(tests)
    for t in tests:
        t['scriptGate'] = bool(t['rmse'][1] < t['rmse'][0] - 1e-4 and t['winsRmse'] >= 9 and t['slotErr'][1] <= t['slotErr'][0])
        t['pass'] = bool(t['pass'] and t['scriptGate'])
    json.dump({'_readme': 'prereg.md F4: CBB conviction add-ons over lnpick+bpm3+age; paired t on squared error per row; '
                          'scriptGate = fit_conv rule (RMSE lower, 9+/15 drafts, redraft slot error not worse).',
               'coverage': cover, 'tests': tests}, open(os.path.join(OUT, 'cbb_conv.json'), 'w'), indent=1)
    print(json.dumps(cover))
    for t in tests:
        print(f"{t['driver']:6} perSd {t['perSd']:+.3f} (t_cl {t['tClustered']:+.2f}) gain {t['gain']:+.5f} t {t['t']:+.2f} p {t['p']:.4f} "
              f"rmse {t['rmse']} slot {t['slotErr']} wins {t['winsRmse']}/{t['of']} gate {t['scriptGate']} pass {t['pass']}")


if __name__ == '__main__':
    main()
