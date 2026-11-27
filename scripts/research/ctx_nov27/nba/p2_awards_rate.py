"""P2: the award races' games-left rate (awards.py nba_races: the Nov 4 shrink, c['sx']) vs the pXPM form on the to-date
line. The as-of harness's own inputs (in-repo boxes, the 'box' stand-in for XPM to date); target = the rest-of-season
stand-in XPM.  -> p2_awards_rate.json"""
import gzip, json, math, os
import numpy as np
import common as C
import awards_asof as AA, awards_nba as A
X = C.X
P = json.load(gzip.open(os.path.join(C.ROOT, 'scripts', 'nba_pbox_hist.json.gz')))
G = [g for g in json.load(gzip.open(os.path.join(C.ROOT, 'scripts', 'nba_games_hist.json.gz')))['games']
     if g['t'] == 2 and g.get('fin') and g['S'] <= C.LAST and g['id'] in P and g['tip'][:10] <= AA.NBA_END.get(g['S'], '9')]
seasons = sorted({g['S'] for g in G}); seasons = [s for s in seasons if sum(g['S'] == s for g in G) > 900]
days = {S: sorted(g['tip'][:10] for g in G if g['S'] == S) for S in seasons}
xpm = {S: A.xpm(S) for S in range(2010, C.LAST + 1)}
idmap, full = {}, {}
for S in seasons:
    L, T = AA.nba_lines(G, P, S, days[S][-1]); full[S] = (L, T)
    m = AA.NM.Matcher(list(xpm[S].values()), name='n', team=None, pos=None)
    for e, r in L.items():
        hit, _ = m.find(r['n'])
        if hit is not None: idmap[(S, e)] = hit['id']


def standin(S):
    Xm, y, yd, w = [], [], [], []
    for T_ in seasons:
        if T_ == S: continue
        L, T = full[T_]
        for e, r in L.items():
            x = xpm[T_].get(idmap.get((T_, e)))
            if not x or r['mp'] < 300 or x.get('xpm') is None or x.get('pr'): continue
            Xm.append(AA.nba_x(r, T)); y.append(x['xpm']); yd.append(x['dxpm']); w.append(r['mp'])
    return AA.ridge(Xm, y, w), AA.ridge(Xm, yd, w)


def pform(pid, S, mp, xo, xd, tg, aging):
    lm = math.log(1 + mp * 82 / max(tg, 1) / 100)
    rows = [(1.0, mp, xo, xd)] + [(w, q['mp'], q['oxpm'], q['dxpm']) for w, q in ((X.PXPM_W[1], C.F.get(S - 1, {}).get('p', {}).get(pid)), (X.PXPM_W[2], C.F.get(S - 2, {}).get('p', {}).get(pid))) if q]
    out = []
    for i, side in ((2, 'o'), (3, 'd')):
        a, b = X.PXPM_MU[side]; num, den = X.PXPM_K * (a + b * lm), X.PXPM_K
        for r in rows: num += r[0] * r[1] * r[i]; den += r[0] * r[1]
        out.append(num / den)
    cv = C.N.aging_curve(S) if aging else None            # pairs ending before S
    age = (xpm[S].get(pid) or {}).get('age')
    ag = cv(age + 1) if cv and age else 0.0
    return out[0] + out[1] + ag, out[1] + .25 * ag


rec = []
for S in seasons:
    bx, bd = standin(S); pri = X.shrink_prior(S); Lf, Tf = full[S]
    for share in AA.SHARES:
        day = days[S][int(len(days[S]) * share) - 1]
        L, T = AA.nba_lines(G, P, S, day)
        for e, r in L.items():
            pid = idmap.get((S, e)); f = Lf.get(e)
            if not pid or not f or f['mp'] - r['mp'] < 200 or f['tm'] != r['tm']: continue
            v = np.array(AA.nba_x(r, T)); xv, dv = float(v @ bx), float(v @ bd)
            rest = {k: f[k] - r[k] for k in AA.BOX_K}; rest.update(mp=f['mp'] - r['mp'], g=max(f['g'] - r['g'], 1), tm=r['tm'])
            wr, gr, mr = Tf[r['tm']]; w0, g0, m0 = T[r['tm']]
            vr = np.array(AA.nba_x(rest, {r['tm']: (wr - w0, max(gr - g0, 1), mr - m0)})); yv, yd = float(vr @ bx), float(vr @ bd)
            sh = X.shrink({'id': pid, 'mp': r['mp'], 'xpm': xv, 'oxpm': xv - dv, 'dxpm': dv}, max(T[r['tm']][1], 1), pri)
            a = pform(pid, S, r['mp'], xv - dv, dv, T[r['tm']][1], True); b = pform(pid, S, r['mp'], xv - dv, dv, T[r['tm']][1], False)
            rec.append((S, share, f'{pid}{S}', rest['mp'], yv, yd, sh['sxpm'], sh['sdxpm'], a[0], a[1], b[0], b[1]))
R = np.array([r[3:] for r in rec], float); Ss = np.array([r[0] for r in rec]); sh_ = np.array([r[1] for r in rec]); ids = [r[2] for r in rec]
w = R[:, 0]


def cmp(base, cand, y, m):
    ea, eb = (R[m, base] - R[m, y]) ** 2, (R[m, cand] - R[m, y]) ** 2; ww = w[m]
    d = {}
    for i, v in zip(np.array(ids)[m], ww * (ea - eb)): d[i] = d.get(i, 0) + v
    d = np.array(list(d.values())); ss = sorted(set(Ss[m]))
    won = sum(np.average(eb[Ss[m] == s], weights=ww[Ss[m] == s]) < np.average(ea[Ss[m] == s], weights=ww[Ss[m] == s]) for s in ss)
    return {'n': int(m.sum()), 'rmse': [round(float(np.sqrt(np.average(ea, weights=ww))), 4), round(float(np.sqrt(np.average(eb, weights=ww))), 4)],
            't': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2), 'seasons': f'{won}/{len(ss)}'}


res = {'seasons': [int(s) for s in seasons]}
allm = np.ones(len(R), bool)
for lab, (ct, cd) in (('A pXPM form', (5, 6)), ('B pXPM form, no aging', (7, 8))):
    res[lab] = {'total': cmp(3, ct, 1, allm), 'defense': cmp(4, cd, 2, allm), **{f'total at {s}': cmp(3, ct, 1, sh_ == s) for s in AA.SHARES}}
    print(lab, json.dumps(res[lab]), flush=True)
json.dump(res, open(os.path.join(C.HERE, 'p2_awards_rate.json'), 'w'), indent=1)
