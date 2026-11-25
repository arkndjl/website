"""CS2 metric audit (Nov 24 2026): shared loading for the player harness and the candidate tests.
Maps before the lockbox (2026-11-11) only; months Jan 2024 .. Oct 2026."""
import datetime as dt, gzip, json, math, sys, zlib
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'scripts'))
import cs2_bo3  # noqa: E402
import cs2_players as P  # noqa: E402
import cs2_pstats as PS  # noqa: E402

LOCK = '2026-11-11'
FIRST, LAST = '2024-01', '2026-10'
SHIP = dict(json.loads(P.FIT.read_text())['params'])


def months(a=FIRST, b=LAST):
    out, d = [], dt.date.fromisoformat(a + '-01')
    while d.isoformat()[:7] <= b:
        out.append(d.isoformat()[:7]); d = (d + dt.timedelta(days=32)).replace(day=1)
    return out


def T0(mo): return P.ordd(mo + '-01')


def T1(mo): return P.ordd((dt.date.fromisoformat(mo + '-01') + dt.timedelta(days=32)).replace(day=1).isoformat())


def load():
    bo3 = cs2_bo3.load()
    bo3 = dict(bo3, games=[g for g in bo3['games'] if (g[2] or '9')[:10] < LOCK])
    M = P.Maps(bo3)
    assert max(g[1] for g in M.games) < LOCK
    rt = {}
    for f in sorted(PS.DIR.glob('*.json.gz')):
        if f.name[:7] > LAST: continue
        with gzip.open(f, 'rt') as fh:
            for r in json.load(fh)['rows']:
                rt[(r[0], r[1])] = r[13]
    gid = np.array([g[0] for g in M.games])
    M.rt = np.array([(rt.get((gid[gi], pr)) or 0) / 100 for gi, pr in zip(M.g, M.p_raw)], float)
    # orientation: each map's side A is a hash half (side 0 is always the winner in Maps)
    M.flip = np.array([zlib.crc32(str(g).encode()) % 2 for g in gid]) == 1
    M.half = np.array([(zlib.crc32(('h' + str(g)).encode()) >> 3) % 2 for g in gid])
    M.mapname = np.array([g[7] or '' for g in M.games])
    X = M.X
    kpr, dpr, apr, adr, kast = X[:, 0], X[:, 1], X[:, 2], X[:, 3] * 100, X[:, 4] * 100
    M.pub = {'bo3.gg rating': M.rt, 'HLTV 2.0 (approx.)': 0.0073 * kast + 0.3591 * kpr - 0.5329 * dpr
             + 0.2372 * (2.13 * kpr + 0.42 * apr - 0.41) + 0.0032 * adr + 0.1587,
             'ADR': adr, 'KAST': kast, 'KPR': kpr, 'K-D per round': kpr - dpr}
    return M


def ratings_ex(M, c, T, p, excl=None):
    """cs2_players.ratings with rows in excl left out (held-out half)."""
    m = M.d < T
    if excl is not None: m = m & ~excl
    w = M.R * np.exp(-(T - M.d) * math.log(2) / p['h']) * m
    n = len(M.pids); theta = np.zeros(n); wsum = np.bincount(M.p, w, n)
    lift = p.get('ssg', 0.0) * sa_share_ex(M, T, excl) if p.get('ssg') else 0.0
    for _ in range(6):
        th_row = (theta + lift)[M.p]
        opp = th_row[M.five[M.g, 1 - M.side]].mean(1)
        adj = c + p['opp'] * opp
        pri = 0.0
        if p.get('tp'):
            mate = (theta[M.p][M.five[M.g, M.side]].sum(1) - theta[M.p]) / 4
            pri = p['tp'] * np.bincount(M.p, w * mate, n) / np.maximum(wsum, 1e-9)
        theta = (np.bincount(M.p, w * adj, n) + p['k'] * pri) / (wsum + p['k'])
    return theta + lift, wsum


def sa_share_ex(M, T, excl=None):
    m = (M.d >= T - 365) & (M.d < T)
    if excl is not None: m = m & ~excl
    n = len(M.pids)
    return np.bincount(M.p, M.R * m * (M.tier <= 2), n) / np.maximum(np.bincount(M.p, M.R * m, n), 1)


def weights(M, T, excl_games=None, l2=1e-4):
    g = M.gd < T
    if excl_games is not None: g = g & ~excl_games
    return P.stat_weights(M, g, l2)


def wmean(M, val, mask, lo=100):
    """rounds-weighted mean of a per-row value over rows in mask -> (value per player with fill, rounds)"""
    n = len(M.pids); w = M.R * mask
    r = np.bincount(M.p, w, n); v = np.bincount(M.p, w * val, n) / np.maximum(r, 1e-9)
    low = (r > 0) & (r < lo)
    fill = float(np.average(v[low], weights=r[low])) if low.any() else float(np.average(v[r > 0], weights=r[r > 0]))
    v[r == 0] = fill
    return v, r


def mapxy(M, v, gi):
    """per map: x = A five sum minus B five sum, y = A round share - .5, A = hash side"""
    x = v[M.p[M.five[gi, 0]]].sum(1) - v[M.p[M.five[gi, 1]]].sum(1)
    y = M.y[M.five[gi, 0, 0]] - 0.5
    s = np.where(M.flip[gi], -1.0, 1.0)
    return x * s, y * s


def r2(x, y): return float(np.corrcoef(x, y)[0, 1] ** 2) if len(x) > 2 else float('nan')


def wcorr(x, y, w):
    x, y, w = map(np.asarray, (x, y, w)); mx, my = np.average(x, weights=w), np.average(y, weights=w)
    return float(np.average((x - mx) * (y - my), weights=w) / np.sqrt(np.average((x - mx) ** 2, weights=w) * np.average((y - my) ** 2, weights=w)))


def tby(d):
    d = np.asarray(d, float)
    return float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)) + 1e-12)) if len(d) > 1 else float('nan')


def tcdf(t, df):
    """Student t CDF (numerical integration; scipy is not installed)"""
    x = np.linspace(-60, t, 200001)
    f = np.exp(math.lgamma((df + 1) / 2) - math.lgamma(df / 2)) / math.sqrt(df * math.pi) * (1 + x * x / df) ** (-(df + 1) / 2)
    return float(np.trapezoid(f, x) if hasattr(np, 'trapezoid') else np.trapz(f, x))
