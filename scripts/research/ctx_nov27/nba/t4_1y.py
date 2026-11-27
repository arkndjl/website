"""T4 + the downstream guard of T3: the 1Y / 3Y (H4 form, XPM given he plays; nba_proj3y_play_research) on
(a) the live prior (nba_xpm.prior_xpm), (b) last season's pXPM as the prior (k refit, T3), and (c) pXPM of the season
itself as the 1Y, no fit. Leave one season out with the harness's buffer, scored on 1,000+ window minutes, weighted.
-> t4_1y.json"""
import copy, json, os
import numpy as np
import common as C
import nba_proj3y_research as R, nba_proj3y_star_research as SR, nba_proj3y_play_research as PR

T3 = json.load(open(os.path.join(C.HERE, 't3_prior.json')))['cover']
rows_a = SR.add_history(R.load())
rows_b = copy.deepcopy(rows_a)
for r in rows_b:
    v = C.pxpm(r['id'], r['S'] - 1)
    if v is not None: r['prior'] = v
    r['k'] = T3['new ' + r['g']]['k']                      # the blend's k refit on the new prior; the partial-season noise (s2) as live


def preds(rows, f):
    rng = np.random.default_rng(20261103)                  # the same draws in both arms
    SR.inputs_with_mp(rows, f, rng)
    n, proj, prior, age, lm, M = R.inputs(rows, f, rng)
    rep = lambda k: np.repeat(np.array([r[k] for r in rows], float), n)
    S, ids = rep('S'), np.repeat([r['id'] for r in rows], n)
    d1 = (rep('x1') + 2) * rep('m1') / (rep('m1') + 1000); d2 = (rep('x2') + 2) * rep('m2') / (rep('m2') + 1000)
    lc = np.log1p(SR.MPF[0] + rep('m1') + rep('m2'))
    X = SR.design(PR.FORM, proj, prior, age, lm, d1, d2, lc)
    FM = np.repeat(np.array([r['fmp'] for r in rows], float), n, axis=0); FX = np.repeat(np.array([r['fx'] for r in rows], float), n, axis=0)
    w3 = FM.sum(1); a3 = np.where(w3 > 0, (FX * FM).sum(1) / np.maximum(w3, 1e-9), np.nan)
    out = {}
    for tn, act, w, buf, last in (('y1', np.where(FM[:, 0] > 0, FX[:, 0], np.nan), FM[:, 0], 1, 2025), ('y3y', a3, w3, 3, 2023)):
        ok = S <= last; p = np.zeros_like(act)
        for c in sorted(set(S[ok].astype(int))):
            tr = ok & (np.abs(S - c) > buf) & (w > 0); te = ok & (S == c)
            p[te] = X[te] @ PR.wfit(X[tr], act[tr], w[tr])
        out[tn] = (p, act, w, ok & (w >= PR.MINW), S, ids)
    return out


def cmp(pa, pb, act, w, sc, S, ids):
    ea, eb = (pa - act)[sc] ** 2, (pb - act)[sc] ** 2; ws = w[sc]; ss = sorted(set(S[sc].astype(int)))
    won = sum(np.average(eb[S[sc] == c], weights=ws[S[sc] == c]) < np.average(ea[S[sc] == c], weights=ws[S[sc] == c]) for c in ss)
    return {'rmse': [round(float(np.sqrt(np.average(ea, weights=ws))), 4), round(float(np.sqrt(np.average(eb, weights=ws))), 4)],
            't': round(-R.tstat(ws * (eb - ea), ids[sc]), 2), 'seasons': f'{won}/{len(ss)}'}


res = {}
for f in (0.1, 0.2, 0.35, 0.5, 0.75, 1.0):
    A, B = preds(rows_a, f), preds(rows_b, f)
    res[str(f)] = {tn: cmp(A[tn][0], B[tn][0], *A[tn][1:]) for tn in ('y1', 'y3y')}
    print(f, 'live prior -> pXPM prior', json.dumps(res[str(f)]), flush=True)
    if f == 1.0:
        px = np.array([C.pxpm(r['id'], r['S']) for r in rows_a])
        res['pXPM as the 1Y vs live 1Y (f 1)'] = cmp(A['y1'][0], px, *A['y1'][1:])
        res['pXPM as the 1Y vs 1Y on the pXPM prior (f 1)'] = cmp(B['y1'][0], px, *A['y1'][1:])
        print(json.dumps({k: v for k, v in res.items() if k.startswith('pXPM')}), flush=True)
json.dump(res, open(os.path.join(C.HERE, 't4_1y.json'), 'w'), indent=1)
