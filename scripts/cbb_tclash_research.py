#!/usr/bin/env python3
"""CBB totals: tempo clash inside the game model (Nov 3 2026). Follow-up to scripts/cbb_matchup_research.py, where the
box-score pace product (tempo_T: pace x the opponent's pace, z within season) ran over the close in both splits (tune
t 2.0, held 2.65, against our model 2.5 / 3.2; Holm-significant, held-out SE t -1.47, just short of the -1.5 split rule).
Here the same idea in the model's own terms, one walk, each a totals term (TFEATS) fit walk-forward:
  tclash   the product of the two sides' tempo deviations from the total's tempo solve (Ratings.T2)
  mclash   the product of the two sides' market total ratings (W.tm) / 10
Pass (house bar): totals MAE 2016-20 paired t <= -1.5, 2021-26 not worse; vs the close: the stack close + b (model -
close) [+ c term], fit walk-forward, held-out SE no worse.

    python3 scripts/cbb_tclash_research.py     # -> data/cbb_tclash_research.json
"""
import json
import os
import sys

for _v in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(_v, '1')
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness as H        # noqa: E402
import cbb_games as C      # noqa: E402

OUT = os.path.join(os.path.dirname(HERE), 'data', 'cbb_tclash_research.json')


def main():
    F = json.load(open(C.FIT))
    games, btname, d1s, tprior, avs = C.load_all()
    W, rows = C.run_walk(F['params'], games, tprior, btname, d1s, avs)
    feats = list(F['feats'])
    out = {}
    D, Xm, y, TX0, ty, S, line, tline, d1 = C.matrices(rows, feats)
    day = np.array([g['date'][:10] for g, _, _ in D])
    p0 = C.walk_pred(TX0, ty, S, d1)
    ok = ~np.isnan(p0) & d1
    k1, k2 = ok & (S <= C.TUNE_END), ok & (S > C.TUNE_END)
    lin = ~np.isnan(tline)
    out['base'] = {'tune': round(float(np.abs(p0[k1] - ty[k1]).mean()), 4), 'held': round(float(np.abs(p0[k2] - ty[k2]).mean()), 4)}

    def stack(p, extra=None):
        """walk-forward: total - close on (p - close) [and extra]; returns predictions of the total"""
        X = np.c_[np.ones(len(p)), p - tline] if extra is None else np.c_[np.ones(len(p)), p - tline, extra]
        pr = np.full(len(p), np.nan)
        for s in range(C.SCORE0, C.LAST + 1):
            tr, te = (S < s) & ok & lin, (S == s) & ok & lin
            if tr.sum() < 500 or not te.any():
                continue
            b = np.linalg.lstsq(X[tr], (ty - tline)[tr], rcond=None)[0]
            pr[te] = tline[te] + X[te] @ b
        return pr
    s0 = stack(p0)
    for t in ('tclash', 'mclash'):
        _, _, _, TX, _, _, _, _, _ = C.matrices(rows, feats, C.TFEATS + [t])
        p = C.walk_pred(TX, ty, S, d1)
        r = {'coef': round(float(np.linalg.lstsq(TX[ok & (S <= C.LAST)], ty[ok & (S <= C.LAST)], rcond=None)[0][-1]), 4)}
        for nm, k in (('tune', k1), ('held', k2), ('tuneLined', k1 & lin), ('heldLined', k2 & lin)):
            e, e0 = np.abs(p[k] - ty[k]), np.abs(p0[k] - ty[k])
            pr = H.paired(e, e0, cluster=day[k])
            r[nm] = {'mae': round(float(e.mean()), 4), 'd': round(float(e.mean() - e0.mean()), 4), 't': round(pr['t'], 2)}
        st = stack(p0, np.array([tx[t] for _, _, tx in D]))
        for nm, k in (('closeTune', k1 & lin & ~np.isnan(st)), ('closeHeld', k2 & lin & ~np.isnan(st))):
            pr = H.paired((st[k] - ty[k]) ** 2, (s0[k] - ty[k]) ** 2, cluster=day[k])
            r[nm] = {'dSE': round(float(pr['d']), 4), 't': round(pr['t'], 2)}
        r['pass'] = r['tune']['t'] <= -1.5 and r['held']['d'] <= 0 and r['closeHeld']['dSE'] <= 0
        out[t] = r
        print(t, json.dumps(r), flush=True)
    json.dump(out, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
