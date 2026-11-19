#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""T1a: Polymarket lower-level closes placed in the market memory (same constants as live). T1b: the live pick rule
entered at Polymarket's price a day out, judged at the close an hour before the start (paper)."""
import pickle, math
from tcommon import *
import pm, pm_join
from tennis_data import is_qual
FLOORS = (0, 1000, 5000)
J = pm_join.build(); H = pm.load_hist()
rows, players, tn = load_rows()
P = live_P()


def close(j, lead=3600):
    h = H.get((j['tok'], 'ml'))
    if not h: return None
    v = [p for t, p in h if t <= j['t0'] - lead and .02 < p < .98]
    return v[-1] if v else None


def entry(j):
    h = H.get((j['tok'], 'ml'))
    if not h: return None
    t_in = max(h[0][0], j['t0'] - 24 * 3600)
    if t_in > j['t0'] - 6 * 3600: return None
    v = [p for t, p in h if t <= t_in and .02 < p < .98]
    return v[-1] if v else None


def rec_of(R, name):
    p = os.path.join(CACHE, name + '.pkl')
    if os.path.exists(p): return pickle.load(open(p, 'rb'))
    _, rec = M.run(R, P, score=lambda r: M.scored(r, 2012 - M.WIN, 2100), cm_lag=M.CM_LAG)
    pickle.dump(rec, open(p, 'wb'))
    return rec


def t1a():
    pulled = [(j, close(j)) for j in J if (j['tok'], 'ml') in H]
    low = [(j, c) for j, c in pulled if c is not None and rows[j['ri']][14] is None]
    print('paths pulled', len(pulled), 'usable lower-level closes', len(low), flush=True)
    base = rec_of(rows, 't1_base')
    Fb, mb = arrays(base); zb = wf_logit(Fb[:, LIVE], mb)
    d8, y, tid = mb['d'], mb['y'], mb['tid']
    win = d8 >= 20251001; tune = win & (d8 <= 20260531); held = d8 >= 20260601
    out = {'paths_pulled': len(pulled), 'lower_level_closes': len(low), 'min_event_volume_pulled': round(min((j['vol'] for j, _ in low), default=0)),
           'n_tune': int(tune.sum()), 'n_held': int(held.sum()), 'floors': {}}
    Z = {}
    for fl in FLOORS:
        put = {j['ri']: (c if not j['flip'] else 1 - c) for j, c in low if j['vol'] >= fl}
        R = [(r[:14] + [min(max(put[i], .01), .99)] + r[15:]) if i in put else r for i, r in enumerate(rows)]
        rec = rec_of(R, f't1_fl{fl}_{len(put)}')
        F, m = arrays(rec); assert m['key'] == mb['key']
        Z[fl] = wf_logit(F[:, LIVE], m)
        out['floors'][fl] = {'closes': len(put), 'tune_d1e4': round(float((nll(Z[fl]) - nll(zb))[tune].mean() * 1e4), 3),
                             'rows_cm_changed': int((np.abs(F[:, 7] - Fb[:, 7]) > 1e-9)[win].sum())}
        print(fl, out['floors'][fl], flush=True)
    best = min(FLOORS, key=lambda f: nll(Z[f][tune]).mean())
    d = nll(Z[best]) - nll(zb)
    out['best_floor'] = best
    out['tune'] = tclust(d[tune], tid[tune]); out['held'] = tclust(d[held], tid[held])
    mon = d8 // 100
    out['months'] = {int(m_): round(float(d[held & (mon == m_)].mean() * 1e4), 2) for m_ in sorted(set(mon[held]))}
    out['months_better'] = sum(v < 0 for v in out['months'].values())
    hc = held & ~np.isnan(mb['pc'])
    out['held_rows_with_feed_close'] = tclust(d[hc], tid[hc])
    ch = held & (np.abs(d) > 1e-12)
    out['held_changed_rows'] = tclust(d[ch], tid[ch]) if ch.sum() > 10 else None
    out['ll_held'] = {'base': round(float(nll(zb[held]).mean()), 5), 'cand': round(float(nll(Z[best][held]).mean()), 5)}
    out['pass'] = bool(out['held'] and out['held']['t'] <= -2 and out['tune']['d1e4'] < 0 and out['months_better'] > len(out['months']) / 2
                       and (out['held_rows_with_feed_close'] or {'d1e4': 0})['d1e4'] <= 0)
    print(json.dumps(out, indent=1)); save('t1a_results', out)
    pickle.dump({'key': mb['key'], 'z': zb}, open(os.path.join(CACHE, 't1_base_z.pkl'), 'wb'))


def t1b():
    B = pickle.load(open(os.path.join(CACHE, 't1_base_z.pkl'), 'rb'))
    zi = {k: z for k, z in zip(B['key'], B['z'])}
    X = []
    for j in J:
        r = rows[j['ri']]
        if not (r[2] in M.TOUR_LV and not is_qual(r[4])): continue
        z = zi.get((r[0], r[6], r[7], r[8], r[4]))
        if z is None or np.isnan(z): continue
        e, c = entry(j), close(j)
        if e is None or c is None: continue
        pw = 1 / (1 + math.exp(-z))
        q = pw if not j['flip'] else 1 - pw
        won = 0 if j['flip'] else 1
        md = dt_of(j['t0'])
        X.append((md, r[6], q, e, c, won))
    lg = lambda p: math.log(p / (1 - p))  # noqa: E731
    out = {'rows': len(X)}
    for nm, sel in (('tune', lambda d: d <= 20260430), ('held', lambda d: d >= 20260501)):
        S = [x for x in X if sel(x[0])]
        a = np.array([lg(x[2]) - lg(x[3]) for x in S]); b = np.array([lg(x[4]) - lg(x[3]) for x in S])
        k = float(a @ b / (a @ a)) if len(S) else None
        clv, ret, g = [], [], []
        for d, tid, q, e, c, won in S:
            for s in (0, 1):
                qs, es, cs, ws = (q, e, c, won) if s == 0 else (1 - q, 1 - e, 1 - c, 1 - won)
                if qs - es >= .04 and .25 <= es <= .75:
                    cost = .03 * es * (1 - es) + .005
                    clv.append(cs - es - cost); ret.append((1 - (es + cost)) / (es + cost) if ws else -1.0); g.append(tid)
        o = {'matches': len(S), 'k': None if k is None else round(k, 3), 'picks': len(clv)}
        if len(clv) > 10:
            t = tclust(np.array(clv), g); tr = tclust(np.array(ret), g)
            o.update(clv_pts=round(float(np.mean(clv)) * 100, 2), clv_t=t['t'], ret_pct=round(float(np.mean(ret)) * 100, 2), ret_t=tr['t'],
                     model_ll=round(float(np.mean([-math.log(q if w else 1 - q) for _, _, q, e, c, w in S])), 4),
                     entry_ll=round(float(np.mean([-math.log(e if w else 1 - e) for _, _, q, e, c, w in S])), 4),
                     close_ll=round(float(np.mean([-math.log(c if w else 1 - c) for _, _, q, e, c, w in S])), 4))
        out[nm] = o
    h, t = out['held'], out['tune']
    out['pass'] = bool(h.get('clv_t') is not None and h['clv_pts'] > 0 and h['clv_t'] >= 2 and t.get('clv_pts', -1) > 0 and h['ret_pct'] >= 0)
    print(json.dumps(out, indent=1)); save('t1b_results', out)


def dt_of(ts):
    import datetime as dt
    d = dt.datetime.fromtimestamp(ts, dt.timezone.utc)
    return d.year * 10000 + d.month * 100 + d.day


if __name__ == '__main__':
    if 'b' in sys.argv[1:]: t1b()
    else: t1a(); t1b()
