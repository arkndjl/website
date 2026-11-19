# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Mixture SPRT against the rule monitor's fixed-alternative drift test, by simulation (PREREG.md S2). -> out/msprt.json"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import rule_monitor as M  # noqa: E402

OUT = os.environ.get('METHODS_OUT', os.path.join(HERE, 'out'))
P = M.params()
SD, A, B, MINN = P['sdDefault'], P['drift']['A'], P['drift']['B'], P['drift']['minN']
MU1, PER, CAP, SIMS = 0.03, 10, 3000, 4000
GRID = np.linspace(0, 1, 21)


def cell(r, rng):
    days = CAP // PER
    x = rng.normal(r * MU1, SD, (SIMS, days, PER)).sum(2)
    S = np.cumsum(x, 1)
    n = PER * np.arange(1, days + 1)[None, :]
    live = n >= MINN
    llr = (S - n * MU1 / 2) * MU1 / SD ** 2
    out = {}

    def first(pause, conf, name):
        ip = np.where(pause.any(1), pause.argmax(1), days)
        ic = np.where(conf.any(1), conf.argmax(1), days)
        paused, confirmed = ip < ic, ic < ip
        out[name] = {'paused': round(float(paused.mean()), 4), 'confirmed': round(float(confirmed.mean()), 4),
                     'medianToPause': int(np.median((ip[paused] + 1) * PER)) if paused.any() else None,
                     'medianToConfirm': int(np.median((ic[confirmed] + 1) * PER)) if confirmed.any() else None}
    first((llr <= -math.log(B)) & live, (llr >= math.log(A)) & live, 'wald')
    lp = np.zeros_like(S)
    lc = np.zeros_like(S)
    for g in GRID:
        lp += np.exp(np.clip((MU1 * (g - 1) / SD ** 2) * (S - n * MU1 * (g + 1) / 2), -700, 700))
        lc += np.exp(np.clip((g * MU1 / SD ** 2) * (S - n * g * MU1 / 2), -700, 700))
    lp /= len(GRID); lc /= len(GRID)
    first((lp >= B) & live, (lc >= A) & (S / n > MU1 / 2) & live, 'mixture')
    return out


def main():
    rng = np.random.default_rng(20261119)
    res = {'sd': SD, 'A': A, 'B': B, 'minN': MINN, 'mu1': MU1, 'perDay': PER, 'cap': CAP, 'sims': SIMS, 'cells': {}}
    for r in (-0.69, 0, .25, .5, .75, 1):
        res['cells'][str(r)] = cell(r, rng)
        print(r, json.dumps(res['cells'][str(r)]), flush=True)
    c = res['cells']
    res['pass'] = bool(c['1']['mixture']['paused'] <= .055 and c['0']['mixture']['confirmed'] <= .055
                       and all(c[k]['mixture']['medianToPause'] is not None and c[k]['mixture']['medianToPause'] < c[k]['wald']['medianToPause'] for k in ('-0.69', '0')))
    print('pass', res['pass'])
    os.makedirs(OUT, exist_ok=True)
    json.dump(res, open(os.path.join(OUT, 'msprt.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
