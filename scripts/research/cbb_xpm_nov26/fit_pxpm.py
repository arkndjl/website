#!/usr/bin/env python3
"""cbb_fit.py's own driver selection and nested protocol with pXPM offered as a returner candidate (research; production
uses scripts/cbb_xpm.py).  python3 fit_pxpm.py base|pxpm OUT.json ;  python3 fit_pxpm.py forward a.json b.json"""
import gzip, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import cbb_fit as F
PX = {int(y): v for y, v in json.load(gzip.open(os.path.join(HERE, 'pxpm_loso.json.gz'), 'rt')).items()}
_feat = F.features


def features(c, i):
    f = _feat(c, i)
    if i:
        q = PX.get(int(c['seasons'][i - 1]['year']), {}).get(str(c['pid']))
        f['pxpm'] = q[0] + q[1] if q else None
    return f


F.features = features
if sys.argv[1] == 'forward':
    import cbb_fv_drivers as V
    V.F.features = features
    V.forward(sys.argv[2:])
else:
    if sys.argv[1] == 'pxpm': F.RET_CANDS.append('pxpm')
    F.OUT = sys.argv[2]
    F.main()
