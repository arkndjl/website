#!/usr/bin/env python3
"""Stay-or-declare as an economic choice (audit #31): does the money on each side beat the board-rank logistic?

    python3 scripts/cfb_declare_econ.py    # needs scripts/cfb_draft_pct_backtest.py's cache; writes data/cfb_declare_econ.json

The live DECLARE (scripts/cfb_teams.mjs) is a logistic in ln xPick per class group, fit on the fall PFF boards of the
NIL-era drafts (2024-25). Here each draft-eligible on those boards also gets:
  rookie   ln expected rookie-contract value: the 2026 slotted four-year totals (OTC), averaged over where he would
           go if he declared (ln slot ~ N(ln xPick, fall sd 1.28)), past pick 257 an undrafted deal (~$1.5M expected)
  nil      ln of the NIL he would draw by staying, from today's board: ln xNIL = a + b ln xPick + QB (ranked
           prospects) with the Group of 5 and FCS gaps at equal FV (all graded players), so the market's level is
           today's and only the shape is applied to past boards
  econ     rookie - nil, the log ratio of the two offers
  age      age on draft day (the board's date plus the days left), centred in his class group (PFF's age is the
           age on the day of the pull, so the board's date is taken off)
  qb, p4   flags
Grads and RS-Sr are out of eligibility and go (the live rule), so they are not fit here.
Test: leave one NIL-era draft out (2024, 2025; the 2026 draft has no fall board: PFF kept only its April board, and
Wayback is blocked), per-row paired log loss against the live two-parameter curve, refit the same way. As a check
on stability, the same models leave one draft out over all five fall boards (2021-25) with an NIL-era flag.
"""
import importlib.util, json, math, os
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location('bt', os.path.join(ROOT, 'scripts', 'cfb_draft_pct_backtest.py'))
bt = importlib.util.module_from_spec(spec); spec.loader.exec_module(bt)
OUT = os.path.join(ROOT, 'data', 'cfb_declare_econ.json')

# 2026 rookie wage scale, four-year totals in $M at anchor picks (OTC); linear in ln pick between anchors
SCALE = [(1, 48.8), (2, 46.7), (5, 37.0), (10, 24.6), (16, 19.0), (24, 15.5), (32, 13.6), (33, 10.0), (48, 8.1), (64, 6.9),
         (65, 6.6), (100, 5.6), (140, 4.9), (180, 4.5), (220, 4.35), (257, 4.2)]
UDFA = 1.5
SD = 1.28
_lp = np.log([p for p, _ in SCALE]); _v = np.array([v for _, v in SCALE])
_z = np.linspace(-3, 3, 61); _w = np.exp(-_z ** 2 / 2); _w /= _w.sum()
def rookie(lx):
    s = lx + SD * _z
    v = np.where(s <= math.log(257), np.interp(s, _lp, _v), UDFA)
    return math.log(float((_w * v).sum()))
# today's xNIL (static/data/cfb-all.json, 2026-10-25): ln xNIL on lnPick(consRk) + QB over the 280 ranked prospects;
# G5 / FCS gaps at equal FV over 11,180 graded players
NIL = {'a': 16.326, 'b': -0.468, 'qb': 0.98, 'g5': -1.677, 'fcs': -2.959}
def nil(lx, qb, p4, fcs):
    return NIL['a'] + NIL['b'] * lx + NIL['qb'] * qb + (NIL['fcs'] if fcs else 0 if p4 else NIL['g5'])


def fit_logit(X, y, l2=1.0):
    b = np.zeros(X.shape[1])
    pen = np.full(X.shape[1], l2); pen[0] = 0
    for _ in range(100):
        p = 1 / (1 + np.exp(-X @ b))
        g = X.T @ (y - p) - pen * b
        H = (X * (p * (1 - p))[:, None]).T @ X + np.diag(pen)
        step = np.linalg.solve(H, g); b += step
        if np.abs(step).max() < 1e-8: break
    return b


def main():
    rows, _ = bt.build_rows()
    latest = {}
    for r in rows:
        if 140 <= r['days'] <= 240 and (r['draft'] not in latest or r['days'] < latest[r['draft']]): latest[r['draft']] = r['days']
    fall = [r for r in rows if latest.get(r['draft']) == r['days'] and r['cls'] not in ('RS Sr.', 'G')]
    for r in fall:
        r['grp'] = 'sr' if r['cls'] == 'Sr.' else 'under'
        r['lx'] = bt.lnPick(r['rank']); r['qb'] = int(r['pos'] == 'QB')
        r['econ'] = rookie(r['lx']) - nil(r['lx'], r['qb'], r['p4'], r['fcs'])
    AGE = {}
    for g in ('sr', 'under'):
        a = [r['age'] + r['days'] / 365.25 for r in fall if r['grp'] == g and r['age'] is not None]; AGE[g] = m = round(float(np.mean(a)), 2)
        for r in fall:
            if r['grp'] == g: r['agez'] = (r['age'] + r['days'] / 365.25 - m) if r['age'] is not None else 0.0
    print('fall rows', len(fall), {d: sum(1 for r in fall if r['draft'] == d) for d in sorted(latest)})

    MODELS = {
        'base': lambda r: [r['lx']],
        'econ': lambda r: [r['econ']],
        'base+econ': lambda r: [r['lx'], r['econ']],
        'base+age': lambda r: [r['lx'], r['agez']],
        'base+qb': lambda r: [r['lx'], r['qb']],
        'base+p4': lambda r: [r['lx'], r['p4']],
        'base+econ+age': lambda r: [r['lx'], r['econ'], r['agez']],
        'base+age+qb+p4': lambda r: [r['lx'], r['agez'], r['qb'], r['p4']],
    }
    out = {'_readme': __doc__.split('\n\n')[1].strip(), 'nil': NIL, 'scale': SCALE, 'udfa': UDFA, 'tests': {}}

    def lodo(drafts, era):
        res = {}
        for name, f in MODELS.items():
            loss = []
            for d in drafts:
                for g in ('sr', 'under'):
                    tr = [r for r in fall if r['draft'] in drafts and r['draft'] != d and r['grp'] == g]
                    te = [r for r in fall if r['draft'] == d and r['grp'] == g]
                    X = lambda S: np.array([[1] + f(r) + ([int(r['draft'] >= 2024)] if era else []) for r in S], float)
                    b = fit_logit(X(tr), np.array([r['declared'] for r in tr], float), l2=0.0 if name == 'base' else 1.0)
                    p = np.clip(1 / (1 + np.exp(-X(te) @ b)), 1e-4, 1 - 1e-4)
                    for r, q in zip(te, p): loss.append((d, g, -(r['declared'] * math.log(q) + (1 - r['declared']) * math.log(1 - q))))
            res[name] = loss
        base = np.array([x[2] for x in res['base']])
        tab = {}
        for name, loss in res.items():
            L = np.array([x[2] for x in loss]); dlt = L - base
            t = float(dlt.mean() / (dlt.std(ddof=1) / math.sqrt(len(dlt)))) if name != 'base' else 0.0
            byd = {f'{d}{g}': round(float(np.mean([x[2] for x in loss if x[0] == d and x[1] == g]) - np.mean([x[2] for x in res['base'] if x[0] == d and x[1] == g])), 4)
                   for d in drafts for g in ('sr', 'under')}
            tab[name] = {'logLoss': round(float(L.mean()), 4), 'vsBase': round(float(dlt.mean()), 4), 't': round(t, 2),
                         'cellsWon': sum(1 for v in byd.values() if v < 0), 'cells': len(byd), 'byCell': byd}
            print(era, name, tab[name]['logLoss'], tab[name]['vsBase'], tab[name]['t'], f"{tab[name]['cellsWon']}/{len(byd)}")
        return tab

    out['tests']['nil_lodo'] = lodo((2024, 2025), False)
    out['tests']['all_lodo_era'] = lodo(tuple(sorted(latest)), True)
    out['n'] = {'nil': sum(1 for r in fall if r['draft'] >= 2024), 'all': len(fall),
                'stayRate': {g: round(1 - float(np.mean([r['declared'] for r in fall if r['grp'] == g and r['draft'] >= 2024])), 3) for g in ('sr', 'under')}}
    # full NIL-era fit of every model, for the record
    out['fits'] = {}
    for name, f in MODELS.items():
        for g in ('sr', 'under'):
            S = [r for r in fall if r['draft'] >= 2024 and r['grp'] == g]
            b = fit_logit(np.array([[1] + f(r) for r in S], float), np.array([r['declared'] for r in S], float), l2=0.0 if name == 'base' else 1.0)
            out['fits'][f'{name}|{g}'] = [round(float(x), 3) for x in b]
    out['ageMean'] = AGE
    out['ageMissing'] = sum(1 for r in fall if r['age'] is None)

    # the whole Draft% chain (as scripts/cfb_draft_pct_backtest.py part 3): leave one fall board out, selection
    # fit on the other drafts' declared, declare per class group; grads on their own curve as the history had them
    allfall = [r for r in rows if latest.get(r['draft']) == r['days']]
    for r in allfall:
        r.setdefault('grp', 'grad' if r['cls'] in ('RS Sr.', 'G') else 'sr' if r['cls'] == 'Sr.' else 'under')
        r.setdefault('lx', bt.lnPick(r['rank'])); r.setdefault('agez', 0.0)
    chain = {}
    for name, f in (('base', lambda r: [r['lx']]), ('base+age', lambda r: [r['lx']] + ([r['agez']] if r['grp'] != 'grad' else []))):
        P, Y, D = [], [], []
        for d in sorted(latest):
            tr = [r for r in allfall if r['draft'] != d]; te = [r for r in allfall if r['draft'] == d]
            trd = [r for r in tr if r['declared']]
            c, sd = bt.fit_sel(np.array([r['lx'] for r in trd]), np.array([r['drafted'] for r in trd]))
            B = {}
            for g in ('sr', 'under', 'grad'):
                S = [r for r in tr if r['grp'] == g]
                B[g] = fit_logit(np.array([[1] + f(r) for r in S], float), np.array([r['declared'] for r in S], float), l2=0.0 if name == 'base' else 1.0)
            for r in te:
                pd = 1 / (1 + math.exp(-(np.array([1] + f(r)) @ B[r['grp']])))
                P.append(pd * float(bt.Phi((c - r['lx']) / sd))); Y.append(r['drafted']); D.append(d)
        P, Y = np.clip(np.array(P), 1e-6, 1 - 1e-6), np.array(Y)
        L = -(Y * np.log(P) + (1 - Y) * np.log(1 - P))
        chain[name] = {'logLoss': round(float(L.mean()), 4), 'brier': round(float(np.mean((P - Y) ** 2)), 4), '_L': L, '_D': D}
    dl = chain['base+age']['_L'] - chain['base']['_L']; Dd = chain['base']['_D']
    out['chain'] = {k: {kk: vv for kk, vv in v.items() if not kk.startswith('_')} for k, v in chain.items()}
    out['chain']['n'] = len(dl)
    out['chain']['t'] = round(float(dl.mean() / (dl.std(ddof=1) / math.sqrt(len(dl)))), 2)
    out['chain']['draftsWon'] = sum(1 for d in sorted(latest) if np.mean([x for x, dd in zip(dl, Dd) if dd == d]) < 0)
    print('chain', out['chain'])
    json.dump(out, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
