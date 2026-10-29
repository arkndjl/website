import os, sys, time, json, multiprocessing as mp
import os
SC = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + '/'
sys.path.insert(0, SC)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import cbb_games as C
import harness as H
from core import walk_stack, OUT
FIT = json.load(open(C.FIT))
P0 = dict(FIT['params'])
TF = list(FIT['tcoef'])
print('tfeats', TF, flush=True)
games, btname, d1s, tprior, avs = C.load_all()
VALS = [None] + [float(v) for v in sys.argv[1:]]

def one(thl):
    P = dict(P0, thl=thl)
    W, rows = C.run_walk(P, games, tprior, btname, d1s, avs)
    D, Xm, y, TX, ty, S, line, tline, d1 = C.matrices(rows, FIT['feats'], TF)
    tp = C.walk_pred(TX, ty, S, d1)
    ids = [g['id'] for g, _, _ in D]
    days = [g['date'][:10] for g, _, _ in D]
    return thl, {'tp': tp.tolist(), 'ty': ty.tolist(), 'S': S.tolist(), 'tline': tline.tolist(), 'd1': d1.tolist(), 'day': days}

with mp.Pool(len(VALS)) as pool:
    res = dict(pool.map(one, VALS))
b = res[None]
ty, S, tl, d1, day = (np.array(b[k]) for k in ('ty', 'S', 'tline', 'd1', 'day'))
tp0 = np.array(b['tp'])
ok = d1 & ~np.isnan(tl) & ~np.isnan(tp0)
out = {}
for v in VALS[1:]:
    tp1 = np.array(res[v]['tp'])
    r = {}
    for nm, m in (('tune', ok & (S <= 2020)), ('held', ok & (S >= 2021))):
        q = H.paired(H.ae(tp1[m], ty[m]), H.ae(tp0[m], ty[m]), day[m])
        r[nm] = {'n': q['n'], 'mae0': round(float(H.ae(tp0[m], ty[m]).mean()), 4), 'mae1': round(float(H.ae(tp1[m], ty[m]).mean()), 4), 't': round(q['t'], 2)}
    # against the close: stack tot ~ T + (model - T)
    for nm0, tp in (('base', tp0), ('cand', tp1)):
        pass
    X0 = np.column_stack([np.ones(len(ty)), tl, tp0 - tl]); X1 = np.column_stack([np.ones(len(ty)), tl, tp1 - tl])
    m = ok
    p0 = walk_stack(np.where(m[:, None], X0, np.nan), ty, S, 2016); p1 = walk_stack(np.where(m[:, None], X1, np.nan), ty, S, 2016)
    for nm, mm in (('closeTune', m & (S <= 2020) & ~np.isnan(p0)), ('closeHeld', m & (S >= 2021) & ~np.isnan(p0))):
        q = H.paired(H.ae(p1[mm], ty[mm]), H.ae(p0[mm], ty[mm]), day[mm])
        r[nm] = {'n': q['n'], 'mae0': round(float(H.ae(p0[mm], ty[mm]).mean()), 4), 'd': round(q['d'], 4), 't': round(q['t'], 2)}
    # close MAE for reference
    r['closeMAE'] = {'tune': round(float(np.abs(tl - ty)[ok & (S <= 2020)].mean()), 4), 'held': round(float(np.abs(tl - ty)[ok & (S >= 2021)].mean()), 4)}
    out[str(v)] = r
    print('thl', v, json.dumps(r), flush=True)
json.dump(out, open(OUT + 'cbb_thl_%s.json' % '_'.join(sys.argv[1:]), 'w'), indent=1)
