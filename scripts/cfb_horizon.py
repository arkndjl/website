# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""One outcome horizon for every draft class (Python twin of scripts/cfb_horizon.mjs; same rule, see there).
h(class) = actual / slot-expected AV a season elapsed, cubic in seasons elapsed, mean 1 over the 2020-23 drafts.
  python3 scripts/cfb_horizon.py --test   prints h by class and checks it against the Node twin
  python3 scripts/cfb_horizon.py --write  data/cfb_horizon.json (read by scripts/fv_alltime.py for rows built before the fix)"""
import csv, json, math, os, subprocess, sys
import numpy as np

REF = (2020, 2021, 2022, 2023)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'cfb_horizon.json')


def saved():
    """season -> h from data/cfb_horizon.json (1 where missing)"""
    h = {int(k): v for k, v in json.load(open(OUT))['h'].items()}
    return lambda season: h.get(int(season), 1.0)


def horizon(picks, through):
    P = [r for r in picks if 2012 <= int(r['season']) <= through and int(r['pick'] or 0) > 0]
    av = lambda r: float(r['w_av'] or 0) / (through - int(r['season']) + 1)
    S = [r for r in P if int(r['season']) <= through - 2]
    x = np.log([int(r['pick']) for r in S]); y = np.array([av(r) for r in S])
    b = float(((x - x.mean()) * (y - y.mean())).sum() / ((x - x.mean()) ** 2).sum()); a = float(y.mean() - b * x.mean())
    cls = sorted({int(r['season']) for r in P})
    ratio = [sum(av(r) for r in P if int(r['season']) == s) / sum(max(0.0, a + b * math.log(int(r['pick']))) for r in P if int(r['season']) == s) for s in cls]
    e = np.array([through - s + 1 for s in cls], float)
    c = np.linalg.lstsq(np.vstack([e ** 0, e, e ** 2, e ** 3]).T, np.array(ratio), rcond=None)[0]
    f = lambda v: float(c[0] + c[1] * v + c[2] * v * v + c[3] * v ** 3)
    ref = sum(f(through - s + 1) for s in REF) / len(REF)
    h = {s: f(through - s + 1) / ref for s in cls}
    return lambda season: h.get(int(season), 1.0)


if __name__ == '__main__' and '--test' in sys.argv:
    rows = list(csv.DictReader(open(os.path.join(ROOT, 'scripts', '.cache', 'statplus', 'draft_picks.csv'))))
    h = horizon(rows, 2025)
    py = {s: round(h(s), 4) for s in range(2012, 2026)}
    js = {int(k): v for k, v in json.loads(subprocess.check_output(['node', os.path.join(ROOT, 'scripts', 'cfb_horizon.mjs'), '--print'], text=True)).items()}
    print('py', py); print('js', js)
    bad = [s for s in py if abs(py[s] - js[s]) > 1e-3]
    print('parity', 'OK' if not bad else f'FAIL {bad}'); sys.exit(1 if bad else 0)


if __name__ == '__main__' and '--write' in sys.argv:
    rows = list(csv.DictReader(open(os.path.join(ROOT, 'scripts', '.cache', 'statplus', 'draft_picks.csv'))))
    h = horizon(rows, 2025)
    json.dump({'through': 2025, 'ref': list(REF), 'h': {str(s): round(h(s), 4) for s in range(2012, 2026)}}, open(OUT, 'w'), indent=1)
    print('wrote', OUT)
