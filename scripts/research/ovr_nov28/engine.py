# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""OVR research engine (Nov 28 2026): the held-out tests every sport's OVR inputs go through.

A sport loader gives player-season rows
    s season, id, pos, age, P (the sport's predictive rate at season end), D (its descriptive rate this season),
    n (this season's sample), car (career sample before this season), fv (final pre-pro FV, rookies only),
    Y (next season's descriptive rate), Yn (next season's sample), tm / tmN (team this season / next)
and every test is leave one season out: parameters fit on the other seasons, scored on the held-out one. A variant beats
the base when its weighted squared error on next season's rate is lower; t is the paired t over held-out seasons.
Targets scored for every variant: next-season rate (weighted MSE, weights min(Yn, cap)), next-season total value
((Y - repl) x Yn, Pearson r), and team results (sum of rating x next-season sample by team, R2 on the team's realised rate).
Stdlib only."""
import math, statistics as st


def wls(X, y, w, ridge=1e-6):
    """weighted least squares, X rows with an intercept column already in"""
    k = len(X[0]); A = [[0.0] * k for _ in range(k)]; b = [0.0] * k
    for xi, yi, wi in zip(X, y, w):
        for i in range(k):
            b[i] += wi * xi[i] * yi
            for j in range(k): A[i][j] += wi * xi[i] * xi[j]
    for i in range(k): A[i][i] += ridge
    # gaussian elimination
    M = [A[i] + [b[i]] for i in range(k)]
    for c in range(k):
        p = max(range(c, k), key=lambda r: abs(M[r][c])); M[c], M[p] = M[p], M[c]
        if abs(M[c][c]) < 1e-12: continue
        for r in range(k):
            if r != c:
                f = M[r][c] / M[c][c]
                for j in range(c, k + 1): M[r][j] -= f * M[c][j]
    return [M[i][k] / M[i][i] if abs(M[i][i]) > 1e-12 else 0.0 for i in range(k)]


def paired_t(a, b):
    """t of mean(a - b) over seasons (negative: a lower)"""
    d = [x - y for x, y in zip(a, b)]
    if len(d) < 2: return 0.0
    sd = st.pstdev(d) * math.sqrt(len(d) / (len(d) - 1))
    return round(st.mean(d) / (sd / math.sqrt(len(d))), 2) if sd > 0 else 0.0


def pearson(x, y):
    if len(x) < 3: return 0.0
    mx, my = st.mean(x), st.mean(y)
    sx = math.sqrt(sum((a - mx) ** 2 for a in x)); sy = math.sqrt(sum((b - my) ** 2 for b in y))
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy) if sx and sy else 0.0


class Engine:
    def __init__(self, rows, cap, repl, new_val=None, min_yn=None, team_min=None):
        self.rows = [r for r in rows if r.get('Y') is not None and r.get('Yn') and r.get('P') is not None]
        self.cap, self.repl = cap, repl
        self.min_yn = min_yn or 0
        self.seasons = sorted({r['s'] for r in self.rows})
        self.new_val = new_val                  # rating given to next-season players with no row this season (team test)
        self.team_min = team_min

    def w(self, r): return min(r['Yn'], self.cap)

    def score(self, feat, name, fit_cal=True):
        """feat(r, train_rows) -> (callable r -> features list) fit on train; Y ~ features by WLS on train.
        Returns per-season held-out weighted MSE, player value r, team R2 and the pooled held-out predictions"""
        mse, vr, tr2, preds = [], [], [], {}
        for s in self.seasons:
            tr = [r for r in self.rows if r['s'] != s and r['Yn'] >= self.min_yn]
            te = [r for r in self.rows if r['s'] == s and r['Yn'] >= self.min_yn]
            if not te: continue
            f = feat(tr)
            X = [[1.0] + f(r) for r in tr]
            beta = wls(X, [r['Y'] for r in tr], [self.w(r) for r in tr]) if fit_cal else None
            def pr(r):
                x = [1.0] + f(r)
                return sum(b * v for b, v in zip(beta, x))
            p = {id(r): pr(r) for r in te}
            preds.update({(r['s'], r['id']): p[id(r)] for r in te})
            W = sum(self.w(r) for r in te)
            mse.append(sum(self.w(r) * (r['Y'] - p[id(r)]) ** 2 for r in te) / W)
            vr.append(pearson([p[id(r)] for r in te], [(r['Y'] - self.repl(r)) * r['Yn'] for r in te]))
            tr2.append(self.team_r2(s, p, te))
        return {'name': name, 'mse': mse, 'r': vr, 'team': tr2, 'preds': preds,
                'MSE': round(st.mean(mse), 6), 'R': round(st.mean(vr), 3),
                'TEAM': round(st.mean([x for x in tr2 if x is not None]), 3) if any(x is not None for x in tr2) else None}

    def team_r2(self, s, p, te):
        """team's next-season realised rate (sum Y x Yn / sum Yn) against the rating-weighted sum of its returning players
        (players new to the league next season enter at new_val); teams = the team he played for next season"""
        T = {}
        for r in te:
            t = r.get('tmN')
            if not t: continue
            a = T.setdefault(t, [0.0, 0.0, 0.0])
            a[0] += r['Y'] * r['Yn']; a[1] += p[id(r)] * r['Yn']; a[2] += r['Yn']
        if len(T) < 8: return None
        x = [a[1] / a[2] for a in T.values()]; y = [a[0] / a[2] for a in T.values()]
        return pearson(x, y) ** 2

    @staticmethod
    def compare(a, b):
        """a against b: held-out MSE t (negative = a better), seasons a wins, value r and team R2 t"""
        n = min(len(a['mse']), len(b['mse']))
        t = paired_t(a['mse'][:n], b['mse'][:n])
        wins = sum(1 for x, y in zip(a['mse'], b['mse']) if x < y)
        tt = [(x, y) for x, y in zip(a['team'], b['team']) if x is not None and y is not None]
        return {'vs': b['name'], 'mse': a['MSE'], 'base': b['MSE'], 't': t, 'wins': wins, 'of': n,
                'r': a['R'], 'rBase': b['R'], 'tR': paired_t(a['r'], b['r']),
                'team': a['TEAM'], 'teamBase': b['TEAM'], 'tTeam': paired_t([x for x, _ in tt], [y for _, y in tt]) if tt else None}


def passes(c, tmin=2.0):
    """ship gate (t over held-out seasons): better on at least one of the three targets with |t| >= tmin (next-season rate
    error lower, next-season value r higher, team R2 higher) and worse on none past t = 1"""
    tt = c['tTeam'] if c['tTeam'] is not None else 0.0
    better = c['t'] <= -tmin or tt >= tmin or c['tR'] >= tmin
    worse = c['t'] >= 1 or tt <= -1 or c['tR'] <= -1
    return better and not worse


def coverage(rows, preds, band):
    """share of held-out next-season rates inside the band; band(r, pred) -> (lo, hi)"""
    k = n = 0
    for r in rows:
        p = preds.get((r['s'], r['id']))
        if p is None: continue
        lo, hi = band(r, p); n += 1; k += lo <= r['Y'] <= hi
    return round(k / n, 3) if n else None
