"""P3: the 1Y / 3Y (H4, XPM given he plays) with the prior seasons' season-only descriptive value: A = the history terms
d1 / d2 on rXPM (txpm) in place of the box blend, B = H4 + the two prior seasons' VORX per 82 team games. Leave one season
out with the harness's buffer, 1,000+ window minutes.  -> p3_1y_desc.json"""
import json, os
import numpy as np
import common as C
import nba_proj3y_research as R, nba_proj3y_star_research as SR, nba_proj3y_play_research as PR

rows = SR.add_history(R.load())
for r in rows:
    for j in (1, 2):
        p = C.F.get(r['S'] - j, {}).get('p', {}).get(r['id'])
        r[f't{j}'] = (p.get('txpm', p['xpm']) if p else 0.0)
        r[f'v{j}'] = (p['vorx'] * 82 / max(C.F[r['S'] - j]['g'], 1) if p else 0.0)


def run(f):
    rng = np.random.default_rng(20261103)
    SR.inputs_with_mp(rows, f, rng)
    n, proj, prior, age, lm, M = R.inputs(rows, f, rng)
    rep = lambda k: np.repeat(np.array([r[k] for r in rows], float), n)
    S, ids = rep('S'), np.repeat([r['id'] for r in rows], n)
    rel = lambda x, m: (x + 2) * m / (m + 1000)
    lc = np.log1p(SR.MPF[0] + rep('m1') + rep('m2'))
    X0 = SR.design(PR.FORM, proj, prior, age, lm, rel(rep('x1'), rep('m1')), rel(rep('x2'), rep('m2')), lc)
    XA = SR.design(PR.FORM, proj, prior, age, lm, rel(rep('t1'), rep('m1')), rel(rep('t2'), rep('m2')), lc)
    XB = np.column_stack([X0, rep('v1'), rep('v2')])
    FM = np.repeat(np.array([r['fmp'] for r in rows], float), n, axis=0); FX = np.repeat(np.array([r['fx'] for r in rows], float), n, axis=0)
    w3 = FM.sum(1); a3 = np.where(w3 > 0, (FX * FM).sum(1) / np.maximum(w3, 1e-9), np.nan)
    out = {}
    for tn, act, w, buf, last in (('y1', np.where(FM[:, 0] > 0, FX[:, 0], np.nan), FM[:, 0], 1, 2025), ('y3y', a3, w3, 3, 2023)):
        ok = S <= last; sc = ok & (w >= PR.MINW); P = {}
        for lab, X in (('live', X0), ('A', XA), ('B', XB)):
            p = np.zeros_like(act)
            for c in sorted(set(S[ok].astype(int))):
                tr = ok & (np.abs(S - c) > buf) & (w > 0); te = ok & (S == c)
                p[te] = X[te] @ PR.wfit(X[tr], act[tr], w[tr])
            P[lab] = p
        ws = w[sc]; e0 = (P['live'] - act)[sc] ** 2; ss = sorted(set(S[sc].astype(int)))
        for lab in ('A', 'B'):
            e = (P[lab] - act)[sc] ** 2
            won = sum(np.average(e[S[sc] == c], weights=ws[S[sc] == c]) < np.average(e0[S[sc] == c], weights=ws[S[sc] == c]) for c in ss)
            out[f'{tn} {lab}'] = {'rmse': [round(float(np.sqrt(np.average(e0, weights=ws))), 4), round(float(np.sqrt(np.average(e, weights=ws))), 4)],
                                  't': round(-R.tstat(ws * (e - e0), ids[sc]), 2), 'seasons': f'{won}/{len(ss)}'}
    return out


res = {}
for f in (0.1, 0.2, 0.35, 0.5, 0.75, 1.0):
    res[str(f)] = run(f); print(f, json.dumps(res[str(f)]), flush=True)
json.dump(res, open(os.path.join(C.HERE, 'p3_1y_desc.json'), 'w'), indent=1)
