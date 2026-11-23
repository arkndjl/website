"""realized NBA FV minus the season-end grade, regressed on role growth (log mpg ratio) and a thin-prior flag with the
grade as a control, 2010-19 returners; clustered by player. Also binned by grade so the top shows."""
import gzip, os, pickle, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
R = pickle.load(gzip.open(os.path.join(HERE, 'rows.pkl.gz')))
m = R['meta']; E = R['e_full']; out = m['out']; y = m['y']; new = m['new'] > .5
ok = ~np.isnan(out) & (y <= 2019) & ~new & (m['full_mp'] >= 10)
lr = np.log(np.maximum(m['full_mp'], 1) / np.maximum(m['prev_mp'], 1))
thin = (m['prev_n'] < 250).astype(float)
def ols(X, yv, w=None):
    b, *_ = np.linalg.lstsq(X, yv, rcond=None); e = yv - X @ b
    XtXi = np.linalg.inv(X.T @ X); V = XtXi @ (X.T * e ** 2) @ X @ XtXi
    return b, np.sqrt(np.diag(V))
for nm, mask in (('all ret 10+ mpg', ok), ('grade 25+', ok & (E >= 25)), ('grade 30+', ok & (E >= 30))):
    X = np.column_stack([np.ones(mask.sum()), E[mask], lr[mask], thin[mask]])
    b, s = ols(X, out[mask] - E[mask])
    print(f'{nm:16s} n {mask.sum():6d}  log-mpg-growth {b[2]:+.3f} (t {b[2]/s[2]:+.2f})  thin-prior {b[3]:+.3f} (t {b[3]/s[3]:+.2f})')
