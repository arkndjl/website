#!/usr/bin/env python3
"""B5 (prereg.md): NBA ldft, opponent free-throw luck stripped in the defense ratings only. Patches a copy of
scripts/nba_games.py in memory (no file edit): the defense part of the luck strip reads LWFTD instead of lwft."""
import os, sys, json, types
from multiprocessing import Pool
import numpy as np
SCR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, SCR)
src = open(os.path.join(SCR, 'nba_games.py')).read()
old = "ld = {t: (1 - self.lw3d) * lu[t][0] + (1 - self.lwft) * lu[t][1] for t in (h, a)}"
assert src.count(old) == 1
src = src.replace(old, "ld = {t: (1 - self.lw3d) * lu[t][0] + (1 - (self.lwft if LWFTD is None else LWFTD)) * lu[t][1] for t in (h, a)}")
src = src.replace("\nFIT = ", "\nLWFTD = None\nFIT = ", 1)
mod = types.ModuleType('nba_games'); mod.__file__ = os.path.join(SCR, 'nba_games.py')
sys.modules['nba_games'] = mod
exec(compile(src, mod.__file__, 'exec'), mod.__dict__)
import harness as H
import luck_research as LR
import nba_games_fit as Fit
N = mod
V = [('base', None), ('ldft .5', 0.5), ('ldft 1', 0.0)]   # LWFTD = 1 - w' ... value is the ld FT weight lwft_d


def one(v):
    N.LWFTD = v[1]
    return v[0], LR.nba_design(json.load(open(N.FIT))['params'])


if __name__ == '__main__':
    F = json.load(open(N.FIT))
    with Pool(3) as p:
        res = dict(p.map(one, V))
    b = res['base']
    keep = b['S'] <= 2026
    y, ty, S = b['y'], b['ty'], b['S']
    k1 = keep & (S >= N.SCORE_FROM) & (S < N.HOLD_FROM); k2 = keep & (S >= N.HOLD_FROM)
    ref = Fit.wf(Fit.mat(b['X'], F['feats']), y, S); tref = Fit.wf(b['TX'], ty, S)
    cl = [b['day'], b['team']]
    out = {}
    for lab, _ in V[1:]:
        pr = Fit.wf(Fit.mat(res[lab]['X'], F['feats']), y, S); tp = Fit.wf(res[lab]['TX'], ty, S)
        r = {}
        for kind, p_, r_, yy in (('margin', pr, ref, y), ('total', tp, tref, ty)):
            for nm, k in (('tune', k1), ('held', k2)):
                q = H.paired(np.abs(p_[k] - yy[k]), np.abs(r_[k] - yy[k]), cluster=[c[k] for c in cl])
                r[kind + '_' + nm] = {'n': int(k.sum()), 'mae': round(float(np.abs(p_[k] - yy[k]).mean()), 4),
                                      'base': round(float(np.abs(r_[k] - yy[k]).mean()), 4),
                                      'd': round(q['d'], 4), 't': round(q['t'], 2), 'p': q['p']}
        out[lab] = r
        print(lab, json.dumps(r), flush=True)
    json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'nba_ldft_results.json'), 'w'), indent=1)
