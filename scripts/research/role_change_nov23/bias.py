"""ex-ante views: (1) blend bias vs the full-season grade for players picked on what was known that day; (2) realized
NBA FV minus the full-season grade by role growth (is the FV model itself low on risers?)"""
import gzip, os, pickle, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import harness as H
R = pickle.load(gzip.open(os.path.join(HERE, 'rows.pkl.gz')))
I, J, N, MP = R['I'], R['J'], R['N'], R['MP']
M = {k: v[I] for k, v in R['meta'].items()}
NEW = M['new'] > 0.5; YR = M['y'].astype(int); PID = R['pid'][I]
T = R['e_full'][I]; P0 = R['e_pre'][I]; NOW = R['e_proj']
RET = ~NEW
rho = MP / np.maximum(M['prev_mp'], 1.0)
for k in (156, 90, 60):
    w = N / (N + k); BL = (1 - w) * P0 + w * NOW
    # top 300 by the blend itself on each date and season (what the board shows)
    top = np.zeros(len(T), bool)
    for y in set(YR):
        for j in set(J):
            m = (YR == y) & (J == j)
            if m.sum() > 300: top[m] = BL[m] >= np.sort(BL[m])[::-1][299]
    for nm, g in (('risers (mpg x1.5+, 20+ mpg, ret)', RET & (MP >= 20) & (rho >= 1.5)), ('thin prior (<250 prev min, 20+ mpg, ret)', RET & (MP >= 20) & (M['prev_n'] < 250)),
                  ('all returners', RET)):
        for tn, tt in (('all', np.ones(len(T), bool)), ('board top 300', top)):
            m = g & tt
            for jj in (0, 1, 2):
                mm = m & (J == jj)
                print(f'k {k:3d} {nm:42s} {tn:14s} date {jj} n {mm.sum():6d} blend-full {np.mean(BL[mm] - T[mm]):+.3f}  pre-full {np.mean(P0[mm]-T[mm]):+.3f}  now-full {np.mean(NOW[mm]-T[mm]):+.3f}')
# (2) season-end rows: realized outcome minus the full-season grade, 2010-19 returners and newcomers
E_full = R['e_full']; meta = R['meta']; out = meta['out']; y = meta['y']
prev_mp = meta['prev_mp']; full_mp = meta['full_mp']; new = meta['new'] > 0.5
ok = ~np.isnan(out) & (y <= 2019)
r2 = full_mp / np.maximum(prev_mp, 1)
res = out - E_full
print('\nrealized FV - full-season grade (2010-19), by role growth')
for nm, g in (('returners all', ~new), ('ret mpg x<0.75', ~new & (r2 < .75)), ('ret mpg x0.75-1.25', ~new & (r2 >= .75) & (r2 < 1.25)), ('ret x1.25-1.75', ~new & (r2 >= 1.25) & (r2 < 1.75)),
              ('ret x1.75-3', ~new & (r2 >= 1.75) & (r2 < 3)), ('ret x3+', ~new & (r2 >= 3)), ('ret x1.5+ and 20+ mpg', ~new & (r2 >= 1.5) & (full_mp >= 20)),
              ('same, grade 30+', ~new & (r2 >= 1.5) & (full_mp >= 20) & (E_full >= 30)), ('ret 20+ mpg, grade 30+, x<1.5', ~new & (r2 < 1.5) & (full_mp >= 20) & (E_full >= 30))):
    m = ok & g
    d = res[m]
    print(f'{nm:34s} n {m.sum():6d} mean {d.mean():+.3f} se {d.std(ddof=1)/np.sqrt(len(d)):.3f}  grade {E_full[m].mean():.2f} out {out[m].mean():.2f}')
