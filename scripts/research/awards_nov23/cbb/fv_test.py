# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Awards -> FV (Nov 23 2026, preregistered in prereg.md): does last season's award-model output add to the CBB FV
model's returner drivers?

    python3 scripts/cbb_careers_kit.py                         # once: scripts/.cache/cbb/careers.json
    python3 scripts/research/awards_nov23/cbb/drivers.py      # scripts/.cache/awards/cbb_heldout_p.json (held-out season-end P(win))
    python3 scripts/research/awards_nov23/cbb/fv_test.py      # -> fv_test.json beside it

Candidates for a returner's board season Y (built from season Y-1 only): awd = ln held-out P(Wooden) (clipped at
1e-4; 1e-4 outside the award pool), awd_any = ln of held-out P(Wooden) + P(his position awards). The award voter
models hold no FV and no board input (bpm, ppg, wp, barthag, mpg, p5), and each season's P comes from a fit that left
that season out. Gate: scripts/cbb_fv_sweep2.py's (cv: 2009-16 boards out of fold under three fold rules, gain in
each, >= 4/5 folds, clustered t >= 2; held: fit 2009-16, the 2017-19 boards on the horizon outcome; fwd: 2020-23),
on top of data/cbb_fit.json's shipped returner drivers. numpy."""
import json, math, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.join(HERE, '..', '..', '..')
sys.path.insert(0, SCR)
import numpy as np
import cbb_data as D
import cbb_fit as F
import cbb_fv_sweep2 as S2

POS = ('cousy', 'west', 'erving', 'malone', 'kareem')


def main():
    HP = json.load(open(os.path.join(SCR, '.cache', 'awards', 'cbb_heldout_p.json')))
    careers = json.load(open(os.path.join(D.CACHE, 'careers.json')))
    thr = F.xpm_scale(careers)
    for c in careers: c['nba']['fvx'] = F.xpm_fv(c, thr)
    F.horizon_fv(careers)
    fitj = json.load(open(os.path.join(D.ROOT, 'data', 'cbb_fit.json')))
    M = fitj['models']['returner']; F.TOP_MEAN = M['topMean']
    rows, hr, hit = [], [], 0
    for c in careers:
        for i, s in enumerate(c['seasons']):
            if not (2009 <= s['year'] <= 2023) or i == 0: continue
            f = F.features(c, i)
            h = HP.get(f"{c['pid']}|{s['year'] - 1}", {})
            hit += bool(h)
            f['awd'] = math.log(max(h.get('wooden', 0.0), 1e-4))
            f['awd_any'] = math.log(max(h.get('wooden', 0.0) + sum(h.get(a, 0.0) for a in POS), 1e-4))
            r = {'pid': c['pid'], 'name': c['name'], 'year': s['year'], 'y': c['nba']['fvx'], 'yh': c['nba']['fvh'],
                 'last': c['last'], 'cls': (c['last'] - 2009) % F.FOLDS, 'f': f}
            if s['year'] in F.TRAIN and c['last'] <= 2020: rows.append(r)
            elif s['year'] >= 2017 and c['nba']['fvh'] is not None: hr.append(r)
    seen = {r['pid'] for r in rows}
    hr = [r for r in hr if r['pid'] not in seen]
    print(f'returner rows: train {len(rows)}, held {len(hr)}; rows with an award P last season {hit}')
    res, cvc, hc = {}, {}, {}
    for cnd in ('awd', 'awd_any'):
        v = np.array([r['f'][cnd] for r in rows]); nba = np.array([r['y'] >= 30 for r in rows])
        print(f'  {cnd}: sd {v.std():.3f}, mean NBA {v[nba].mean():+.3f} vs non {v[~nba].mean():+.3f}')
        a = S2.cv(rows, M['kept'], M['lam'], cnd, cvc)
        b = S2.held(rows, hr, M['kept'], M['lam'], cnd, hc)
        ok_cv = all(x['gain'] > 0 and x['folds'] >= F.MIN_FOLDS and x['t'] >= 2 for x in a.values())
        ok_h = all(b[t]['gain'] > 0 and all(b[t][k][1] >= b[t][k][0] for k in ('top10', 'top25', 'top50', 'corr300'))
                   for t in ('held', 'fwd'))
        res[cnd] = {'cv': a, **b, 'pass': bool(ok_cv and ok_h)}
        print(cnd, json.dumps(res[cnd]), flush=True)
    json.dump(res, open(os.path.join(HERE, 'fv_test.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
