#!/usr/bin/env python3
"""R2 retest (prereg.md): CFB team special teams rating (scripts/st_teams.py) as a game-model input, against the close and
the walk-forward model's residual, st_teams_research.main's tests with 2026 rows dropped (lockbox) and no write to data/.
    python3 scripts/st_teams.py events cfb   (ESPN pbp 2016-25 cached by scripts/cfb_espn_pbp.py 2016 2025)
    python3 scripts/research/metric_audit_nov24/cfb/retest_st.py  -> retest_st.json"""
import json, math, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import st_teams_research as STR, style_research as SR, penalty_research as PR, harness as Hh  # noqa
ev = [e for e in STR.events('cfb') if e['S'] <= 2025]
rel, n0 = STR.n0s('cfb', ev)
pre = STR.pregame(ev, n0)
rows = [r for r in PR.rows_from_wf('cfb', pre) if r['S'] <= 2025]
print('rows', len(rows), 'seasons', sorted({r['S'] for r in rows}))
SR.zs(rows, STR.STATS)
tune = SR.TUNE['cfb']; out = {}
for k in STR.STATS:
    out[k] = SR.score(rows, PR.mterm(rows, lambda z, k=k: z.get(k)), False, tune, 1)
    x = np.array([(r['st']['h'][k] - r['st']['a'][k]) if r['st']['h'].get(k) is not None and r['st']['a'].get(k) is not None else np.nan for r in rows], float)
    out[k + '_pts'] = SR.score(rows, x, False, tune, 1)
keys = list(out); p = [2 * (1 - 0.5 * (1 + math.erf(abs(out[k]['z']) / math.sqrt(2)))) for k in keys]
for k, pi, q in zip(keys, p, Hh.bh(p)):
    out[k]['p'], out[k]['q'] = round(pi, 5), round(float(q), 4); out[k]['pass'] = bool(out[k]['pass_split'] and q <= .10)
for k in ('st', 'st_pts'):
    o = out[k]; print(k, 'tune', o['tune'], 'held', o['held'], 'seHeld', o['seHeld'], 'model', o.get('model'), 'q', o['q'], 'pass', o['pass'])
json.dump({'n0': n0, 'rows': len(rows), 'rating': out}, open(os.path.join(HERE, 'retest_st.json'), 'w'), indent=1, default=float)
