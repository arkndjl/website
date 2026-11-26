"""Which picks change hands on draft night, and who gets them. Drafts 2008-26 (parse.py), held out by draft.

Stage A: P(pick traded on draft night) = logit on the pick and its holder, all known before the draft.
Stage B: given a traded pick, which of the 29 other teams gets it: conditional logit on each team's picks."""
import json, math, os, sys, collections
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parse as PA
P = json.load(open(os.path.join(PA.C, 'picks.json')))
TEAMS = sorted({p['holder'] for p in P} | {p['orig'] for p in P})
by = collections.defaultdict(list)
for p in P: by[p['y']].append(p)
YRS = sorted(by)


def quality(L):
    """team -> 0 (worst record) .. 1 (best): its own second-round slot (no lottery there), else its own first"""
    q = {}
    for p in L:
        if p['rd'] == 2: q.setdefault(p['orig'], (p['pick'] - 31) / 29)
    for p in L:
        if p['rd'] == 1 and p['orig'] not in q: q[p['orig']] = (p['pick'] - 1) / 29
    return q


def feats_pick(p, L, q):
    held = [x['pick'] for x in L if x['holder'] == p['holder']]
    return dict(lnpick=math.log(p['pick']), r2=float(p['rd'] == 2), npk=math.log(len(held)),
                qual=q.get(p['holder'], .5), via=float(p['orig'] != p['holder']),
                later=float(any(h > p['pick'] for h in held)), late1=float(p['rd'] == 1 and p['pick'] >= 20),
                yr=(p['y'] - 2017) / 10, sameRd=float(sum(1 for h in held if (h > 30) == (p['pick'] > 30)) > 1))


def logit_fit(X, y, l2=1e-4, w=None):
    b = np.zeros(X.shape[1])
    w = np.ones(len(y)) if w is None else w
    for _ in range(50):
        z = X @ b; pr = 1 / (1 + np.exp(-z))
        g = X.T @ (w * (y - pr)) - l2 * b
        H = (X * (w * pr * (1 - pr))[:, None]).T @ X + l2 * np.eye(X.shape[1])
        st = np.linalg.solve(H, g); b += st
        if np.abs(st).max() < 1e-8: break
    return b


def rows_A():
    R = []
    for y in YRS:
        L = by[y]; q = quality(L)
        for p in L: R.append((y, feats_pick(p, L, q), float(bool(p['acq']))))
    return R


def lodo_A(R, keys):
    ll, per = [], {}
    for y in YRS:
        tr = [r for r in R if r[0] != y]; te = [r for r in R if r[0] == y]
        X = np.array([[1] + [r[1][k] for k in keys] for r in tr]); Y = np.array([r[2] for r in tr])
        b = logit_fit(X, Y)
        Xt = np.array([[1] + [r[1][k] for k in keys] for r in te]); Yt = np.array([r[2] for r in te])
        pr = np.clip(1 / (1 + np.exp(-Xt @ b)), 1e-6, 1 - 1e-6)
        l = -(Yt * np.log(pr) + (1 - Yt) * np.log(1 - pr))
        ll += list(l); per[y] = l.mean()
    return np.array(ll), per


def clustered_t(a, b, R):
    d = a - b; ys = np.array([r[0] for r in R])
    g = np.array([d[ys == y].sum() for y in YRS])
    se = math.sqrt(len(g)) * g.std(ddof=1) / len(d)
    return d.mean() / se


# ---------------------------------------------------------------- stage B
def feats_team(t, p, L, q):
    held = [x['pick'] for x in L if x['holder'] == t]
    lat = [h for h in held if h > p['pick']]
    gap = (min(lat) - p['pick']) if lat else 0
    return dict(any=float(bool(held)), later=float(bool(lat)), lngap=math.log(1 + gap) if lat else 0.0,
                npk=math.log(1 + len(held)), qual=q.get(t, .5), sameRd=float(any((h > 30) == (p['pick'] > 30) for h in lat)),
                orig=float(t == p['orig'] and t != p['holder']))


def groups_B():
    G = []
    for y in YRS:
        L = by[y]; q = quality(L)
        for p in L:
            if not p['acq'] or p['acq'] == p['holder']: continue
            cands = [t for t in TEAMS if t != p['holder']]
            if p['acq'] not in cands: continue
            G.append((y, [feats_team(t, p, L, q) for t in cands], cands.index(p['acq'])))
    return G


def clogit_fit(G, keys, l2=1e-3):
    b = np.zeros(len(keys))
    for _ in range(60):
        g = -l2 * b; H = l2 * np.eye(len(keys))
        for _, F, j in G:
            X = np.array([[f[k] for k in keys] for f in F]); z = X @ b; z -= z.max(); e = np.exp(z); pr = e / e.sum()
            m = pr @ X; g += X[j] - m; H += (X * pr[:, None]).T @ X - np.outer(m, m)
        st = np.linalg.solve(H, g); b += st
        if np.abs(st).max() < 1e-8: break
    return b


def lodo_B(G, keys):
    ll, top1, top3 = [], [], []
    for y in YRS:
        tr = [g for g in G if g[0] != y]; te = [g for g in G if g[0] == y]
        if not te: continue
        b = clogit_fit(tr, keys) if keys else None
        for _, F, j in te:
            if keys:
                X = np.array([[f[k] for k in keys] for f in F]); z = X @ b; z -= z.max(); pr = np.exp(z); pr /= pr.sum()
            else: pr = np.ones(len(F)) / len(F)
            ll.append(-math.log(pr[j])); o = np.argsort(-pr); top1.append(j == o[0]); top3.append(j in o[:3])
    return np.array(ll), np.mean(top1), np.mean(top3)


if __name__ == '__main__':
    R = rows_A()
    base_rate = np.mean([r[2] for r in R])
    print('picks', len(R), 'traded', int(sum(r[2] for r in R)), 'rate %.3f' % base_rate)
    BASE = ['lnpick', 'r2']
    lb, _ = lodo_A(R, BASE)
    print('stage A base (slot) LODO LL %.4f' % lb.mean())
    cand = ['npk', 'qual', 'via', 'later', 'late1', 'yr', 'sameRd']
    keys = list(BASE); cur = lb
    for c in cand:
        l, per = lodo_A(R, BASE + [c])
        print('  + %-7s LL %.4f  t %.2f  drafts better %d/%d' % (c, l.mean(), clustered_t(l, lb, R), sum(per[y] < lodo_A(R, BASE)[1][y] for y in YRS), len(YRS)))
    # forward selection
    while True:
        best = None
        for c in cand:
            if c in keys: continue
            l, _ = lodo_A(R, keys + [c])
            if l.mean() < cur.mean() and (best is None or l.mean() < best[1].mean()): best = (c, l)
        if not best or clustered_t(best[1], cur, R) > -1.0: break
        keys.append(best[0]); cur = best[1]; print('  kept', best[0], '%.4f' % cur.mean())
    _, perb = lodo_A(R, BASE); l, per = lodo_A(R, keys)
    print('stage A final', keys, 'LL %.4f vs slot %.4f, t %.2f, %d/%d drafts' % (l.mean(), lb.mean(), clustered_t(l, lb, R), sum(per[y] < perb[y] for y in YRS), len(YRS)))
    X = np.array([[1] + [r[1][k] for k in keys] for r in R]); Y = np.array([r[2] for r in R]); b = logit_fit(X, Y)
    print('  coef', dict(zip(['const'] + keys, np.round(b, 3))))
    G = groups_B()
    lu, t1u, t3u = lodo_B(G, [])
    print('stage B n', len(G), 'uniform LL %.3f top1 %.3f top3 %.3f' % (lu.mean(), t1u, t3u))
    KB = ['any', 'later', 'lngap', 'npk', 'qual', 'sameRd', 'orig']
    for k in KB:
        l, t1, t3 = lodo_B(G, [k]); print('  only %-6s LL %.3f top1 %.3f top3 %.3f' % (k, l.mean(), t1, t3))
    l, t1, t3 = lodo_B(G, KB)
    print('  all      LL %.3f top1 %.3f top3 %.3f' % (l.mean(), t1, t3))
