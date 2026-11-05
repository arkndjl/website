"""(copied unchanged in method from the Nov 4 sweep's soc_gk.py, md5 a423b02b; only paths changed and the row build
limited to the Oct 24 snapshot, which fit() grades independently of the other snapshots)
Soccer pre-registered tests S1-S2 (prereg.md): keeper top slope / keeper location on the board's cohort-out
calibrated grade, nested cohort-out, Oct 24 rows. Runs the board's fit() row build with the shipped kept list
(selection skipped), captures the held-out grades, restores data/soccer_prospects_fit.json afterwards.
    python3 soc_gk.py   (repo root, after the dump + feeder/academy games + profiles are cached)"""
import sys, os, json, math, pickle, shutil
sys.path.insert(0, 'scripts')
import numpy as np, pandas as pd
import soccer_prospects as SP
import fv_scorecard

HERE = os.path.dirname(os.path.abspath(__file__))
CAP = os.path.join(SP.CACHE, 'soc_gk_rows.pkl')
OUTJ = os.path.join(SP.ROOT, 'data', 'soc_gk_research.json')


def tsf(t, df):
    x = np.linspace(t, t + 60, 200001)
    c = math.gamma((df + 1) / 2) / (math.sqrt(df * math.pi) * math.gamma(df / 2))
    return float(np.trapezoid(c * (1 + x * x / df) ** (-(df + 1) / 2), x))


LOADC = os.path.join(SP.CACHE, 'soc_gk_load.pkl')   # load() takes ~5 min; cache it so the fit fits a foreground run
_load = SP.load
def load(live_only=False):
    if os.path.exists(LOADC):
        return pickle.load(open(LOADC, 'rb'))
    r = _load(live_only)
    pickle.dump(r, open(LOADC, 'wb'), protocol=4)
    return r
SP.load = load
if '--load-only' in sys.argv:
    load(); sys.exit()

if not os.path.exists(CAP):
    shipped = json.load(open(SP.FIT))
    kept = shipped['kept']
    frames, got = [], {}
    _design = SP.design
    def design(X):
        frames.append(X); return _design(X)
    SP.design = design
    SP.select = lambda F, y, t: (list(kept), {}, [])
    SP.SNAPS = [SP.SEL_SNAP]
    def card(p, y, cls=None, **kw):
        got.update(p=np.array(p), y=np.array(y), co=np.array(cls)); return {'summary': {}}
    fv_scorecard.card = card
    bak = SP.FIT + '.bak'
    shutil.copy(SP.FIT, bak)
    try:
        SP.fit(scorecard=True)
    finally:
        shutil.copy(bak, SP.FIT); os.remove(bak)
    S = next(f for f in frames if len(f) == len(got['p']))
    pickle.dump(dict(S=S, kept=kept, **got), open(CAP, 'wb'))

D = pickle.load(open(CAP, 'rb'))
S, kept, p, y, co = D['S'], D['kept'], D['p'], D['y'], D['co']
F = SP.design(S)
G = (S.grp.values == 'G').astype(float)
print('rows', len(y), 'keepers', int(G.sum()), 'shipped mse', round(float(((p - y) ** 2).mean()), 3))


def calib_out(m):
    """the board's held-out grade for rows in m, fit on m only: cohort-out OLS, then the cohort-out isotonic map"""
    _, pp = SP.loso(F[m], y[m], co[m], kept)
    pc = np.zeros(m.sum())
    cm, ym = co[m], y[m]
    for s in np.unique(cm):
        k = cm == s
        top = pp[~k] >= 50
        kn = {'k': SP.isotonic(pp[~k], ym[~k]), 'slope': round(float(np.polyfit(pp[~k][top], ym[~k][top], 1)[0]), 3)}
        pc[k] = SP.calibrate(pp[k], kn)
    out = np.zeros(len(y)); out[m] = pc
    return out


def Z(pp, g, form): return (g * np.maximum(pp - 40, 0))[:, None] if form == 'S1' else g[:, None]


def run(form):
    new = p.copy(); cs = []
    for c in np.unique(co):
        m = co != c
        pi = calib_out(m)
        b = np.linalg.lstsq(Z(pi[m], G[m], form), (y - pi)[m], rcond=None)[0]; cs.append(b)
        te = co == c
        new[te] = np.clip(p[te] + Z(p[te], G[te], form) @ b, 20, 80)
    e0, e1 = (p - y) ** 2, (new - y) ** 2
    g = np.array([e0[co == c].mean() - e1[co == c].mean() for c in np.unique(co)])
    t = g.mean() / (g.std(ddof=1) / math.sqrt(len(g)))
    d = pd.Series(e0 - e1).groupby(S.player_id.values).mean()
    tp = d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))
    T = pd.DataFrame(dict(t=S.t.values, y=y, h0=p, h1=new))
    def top(col, k):
        o = T.sort_values(col, ascending=False).groupby('t').head(k)
        return round(float(((o[col] - o.y) ** 2).mean()), 2), round(float(o.y.mean()), 2)
    # forward: fit on cohorts <= 2017, grade later cohorts
    trm = co <= 2017
    pi = calib_out(trm)
    bf = np.linalg.lstsq(Z(pi[trm], G[trm], form), (y - pi)[trm], rcond=None)[0]
    b_ = SP.ols(F[trm], y[trm], kept)
    raw = SP.pred(F[~trm], kept, b_)
    tt = trm
    top_ = pi[tt] >= 50
    _, ppt = SP.loso(F[trm], y[trm], co[trm], kept)
    kn = {'k': SP.isotonic(ppt, y[trm]), 'slope': round(float(np.polyfit(ppt[ppt >= 50], y[trm][ppt >= 50], 1)[0]), 3)}
    pf = SP.calibrate(raw, kn)
    pf1 = np.clip(pf + Z(pf, G[~trm], form) @ bf, 20, 80)
    yf = y[~trm]
    gk50 = (G == 1) & (p >= 50)
    res = dict(test=form, n=int(len(y)), mse0=round(float(e0.mean()), 4), mse1=round(float(e1.mean()), 4), gain=round(float(g.mean()), 4),
               t=round(float(t), 2), p=tsf(t, len(g) - 1), wins=int((g > 0).sum()), of=len(g), tPlayers=round(float(tp), 2),
               top25=[top('h0', 25), top('h1', 25)], top50=[top('h0', 50), top('h1', 50)],
               fwdMse=[round(float(((pf - yf) ** 2).mean()), 4), round(float(((pf1 - yf) ** 2).mean()), 4)],
               coefMean=np.round(np.mean(cs, 0), 4).tolist(), coefFwd=np.round(bf, 4).tolist(),
               gk50=[int(gk50.sum()), round(float(p[gk50].mean()), 2), round(float(new[gk50].mean()), 2), round(float(y[gk50].mean()), 2)])
    return res


# diagnosis: keepers by band on the full held-out history
for lo, hi in [(20, 30), (30, 40), (40, 45), (45, 50), (50, 55), (55, 60), (60, 99)]:
    for g in (1, 0):
        m = (G == g) & (p >= lo) & (p < hi)
        if m.sum() >= 3:
            r = y[m] - p[m]
            print('G' if g else 'out', f'{lo}-{hi} n {m.sum()} given {p[m].mean():.1f} became {y[m].mean():.1f} resid {r.mean():+.2f} se {r.std(ddof=1)/math.sqrt(m.sum()):.2f} players {S.player_id[m].nunique()}')
out = [run('S1'), run('S2')]
ps = sorted(range(2), key=lambda i: out[i]['p'])
ok = True
for j, i in enumerate(ps):
    out[i]['holmAlpha'] = .05 / (2 - j); out[i]['holm'] = bool(ok and out[i]['p'] <= out[i]['holmAlpha']); ok = out[i]['holm']
for r in out: print(json.dumps(r))
gate = {r['test']: dict(holm=r['holm'], wins23=r['wins'] * 3 >= 2 * r['of'], tPlayers=r['tPlayers'] > 0,
                        pooled=r['mse1'] < r['mse0'], top25=r['top25'][1][0] <= r['top25'][0][0],
                        top50=r['top50'][1][1] >= r['top50'][0][1], fwd=r['fwdMse'][1] <= r['fwdMse'][0]) for r in out}
for r in out:
    r['p'] = round(r['p'], 4)
json.dump({'asof': pd.Timestamp.today().strftime('%Y-%m-%d'),
           'prereg': 'FV sweep Nov 4 2026 (intl prereg.md), tests S1-S2, Holm k = 2, alpha .05, one-sided fold t',
           'rows': 'Oct 24 snapshot, seasons 2013-20, cohort-out calibrated grade; folds = birth cohorts',
           'n': int(len(y)), 'keepers': int(G.sum()), 'shipped': [k for k, g in gate.items() if all(g.values())],
           'gate': gate, 'tests': out}, open(OUTJ, 'w'), indent=1)
