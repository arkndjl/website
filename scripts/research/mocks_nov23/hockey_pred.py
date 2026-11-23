"""F5 (prereg.md): where among the drafted a hockey prospect goes, beyond Central Scouting's final rank. Drafted players
2008-26 with a CSS final rank (scripts/data/hockey_rows.json.gz), ln pick on ln CSS rank and its square by category,
each driver added alone, leave one draft out; loss = squared ln pick error.

    python3 scripts/research/mocks_nov23/hockey_pred.py   -> scripts/research/mocks_nov23/hockey_pred.json"""
import gzip, json, math, os
import numpy as np
from common import ROOT, OUT, paired, holm

CATS = [('NA', 'S'), ('INT', 'S'), ('NA', 'G'), ('INT', 'G')]


def rows():
    R = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'data', 'hockey_rows.json.gz')))
    chl = json.load(open(os.path.join(ROOT, 'scripts', 'data', 'hockey_chl_priority.json')))
    out = []
    for r in R:
        c = r.get('css') or {}
        if not c.get('final') or (c.get('reg'), c.get('kind')) not in CATS: continue
        d0, dm = r.get('d0') or {}, r.get('dm1') or {}
        g = d0.get('grp')
        n0 = d0.get('nhle') if d0.get('nhle') and d0['nhle'] > 0 else None
        n1 = dm.get('nhle') if dm.get('nhle') and dm['nhle'] > 0 else None
        cp = chl.get(str(r['id'])) or []
        out.append(dict(year=r['year'], pick=r['pick'], y=math.log(r['pick']), cat=(c['reg'], c['kind']), lr=math.log(c['final']),
                        age=r.get('age'), ht=r.get('ht'), nhle=math.log(1 + n0) if n0 is not None else None,
                        chl=1.0 if g == 'chl' else 0.0, us=1.0 if g in ('usjr', 'ncaa') else 0.0, eu=1.0 if g in ('ejr', 'epro') else 0.0,
                        D=float(r.get('D') or 0), chl1=1.0 if cp and cp[1] == 1 else 0.0,
                        trend=(math.log(1 + n0) - math.log(1 + n1)) if n0 is not None and n1 is not None else None))
    for k in ('age', 'ht', 'nhle', 'trend'):
        v = [r[k] for r in out if r[k] is not None]; m = float(np.mean(v))
        for r in out: r[k + '_c'] = (r[k] - m) if r[k] is not None else 0.0
    return out


def feats(r, extra):
    f = []
    for c in CATS:
        on = 1.0 if r['cat'] == c else 0.0
        f += [on, on * r['lr'], on * r['lr'] ** 2]
    for k in extra:
        if k == 'lg': f += [r['us'], r['eu']]
        else: f.append(r[k])
    return f


def lodo(R, extra):
    yrs = sorted({r['year'] for r in R}); loss = np.zeros(len(R))
    for t in yrs:
        tr = [r for r in R if r['year'] != t]
        b = np.linalg.lstsq(np.array([feats(r, extra) for r in tr]), np.array([r['y'] for r in tr]), rcond=None)[0]
        for i, r in enumerate(R):
            if r['year'] == t: loss[i] = (min(float(np.dot(feats(r, extra), b)), math.log(230)) - r['y']) ** 2
    return loss


def main():
    R = rows(); l0 = lodo(R, []); tests = []
    cover = {'n': len(R), 'years': f"{min(r['year'] for r in R)}-{max(r['year'] for r in R)}", 'age': sum(r['age'] is not None for r in R),
             'ht': sum(r['ht'] is not None for r in R), 'nhle': sum(r['nhle'] is not None for r in R), 'trend': sum(r['trend'] is not None for r in R),
             'chl1': sum(r['chl1'] for r in R), 'D': sum(r['D'] for r in R)}
    for d in ['age_c', 'ht_c', 'nhle_c', 'lg', 'D', 'chl1', 'trend_c']:
        l1 = lodo(R, [d])
        b = np.linalg.lstsq(np.array([feats(r, [d]) for r in R]), np.array([r['y'] for r in R]), rcond=None)[0]
        res = paired(l0, l1, [r['year'] for r in R])
        res.update({'model': 'F5', 'driver': d, 'coef': [round(float(x), 4) for x in b[12:]], 'n': len(R),
                    'lnErr2': [round(float(l0.mean()), 4), round(float(l1.mean()), 4)]})
        tests.append(res)
    holm(tests)
    for t in tests: t['pass'] = bool(t['holm'] and t['gain'] > 0 and t['won'] >= 10)
    json.dump({'_readme': 'prereg.md F5: hockey pick beyond the CSS final rank (drafted players only), LODO, squared ln pick error; coef = ln pick per unit.',
               'coverage': cover, 'tests': tests}, open(os.path.join(OUT, 'hockey_pred.json'), 'w'), indent=1)
    print(json.dumps(cover))
    for t in tests:
        print(f"{t['driver']:8} coef {t['coef']} gain {t['gain']:+.5f} t {t['t']:+.2f} p {t['p']:.5f} won {t['won']}/{t['of']} err {t['lnErr2']} holm {t['holm']} pass {t['pass']}")


if __name__ == '__main__':
    main()
