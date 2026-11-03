#!/usr/bin/env python3
"""Projected NBA position for college players (Nov 3 2026; Noah: "positional change projections for CBB like we do for
CFB"). Display only: the board shows each player's odds at PG / SG / SF / PF / C and flags a likely position change.

    python3 scripts/cbb_careers_kit.py   # once: scripts/.cache/cbb/careers.json
    python3 scripts/cbb_nbapos.py --fit  # -> data/cbb_nbapos.json (needs scripts/data/nba_pos_est.json.gz)
    import cbb_nbapos; cbb_nbapos.describe(seasons, pos)   # cbb_live.py / fetch_cbb.py: one player's projection

Outcome: where NBA teams played him, the share of his minutes at each position (Basketball-Reference play-by-play
position estimates, 2009-26, frozen in scripts/data/nba_pos_est.json.gz by scripts/research/nbapos/bbref_pos.py),
over his first six NBA seasons; college players who reached 500 NBA minutes (846, classes 2008-25).
Model: multinomial logit on the minutes shares (soft targets), L2, on his college line pooled over every season so far
by minutes: height (Barttorvik listing) and its square, assist rate, usage, 3PA share of shots, offensive and defensive
rebound rates, block and steal rates, rim share of shots, dunk attempts a 40, FT%. Picked by backward elimination on
classes 2008-19 (turnover rate, foul rate, mid-range share, FT rate, 3P% and 3PA a 100 add nothing).
Scored with each draft class held out (scripts/research/nbapos/): cross-entropy .881 against .941 for height plus
Barttorvik's college role (t 4.4 on players with a role, 12 of 16 classes) and .999 for height alone; modal position
right 71% (role + height 64%); fit on 2008-19 and graded on 2020-25 classes, still ahead (.952 vs .972 vs 1.030).
Position change: the flag is the NBA group (G = PG + SG, F = SF + PF, C) at 50%+ when it isn't his board position.
Against Barttorvik's college position (G / F / C) held out: 139 flags, 93 right (67%), 93 of the 172 changes found;
at 70%+ 40 of 50 right. Most changes are college bigs who play the 4 and big college guards who play on the wing.
Height against the projected position's NBA players (in place of height for his college role, ht_g) failed the FV
gate in every form (scripts/research/nbapos/nbapos_fv.py; scripts/data/cbb_nbapos_fv*.json), so FV doesn't read it."""
import csv, gzip, json, math, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'cbb_nbapos.json')
EST = os.path.join(HERE, 'data', 'nba_pos_est.json.gz')
COMBINE = os.environ.get('CBB_COMBINE', '/mnt/project-files/cbb/frame/combine_linked.csv')
POS = ['PG', 'SG', 'SF', 'PF', 'C']
GRP = {'G': (0, 1), 'F': (2, 3), 'C': (4,)}
SKILL = ['ast', 'usg', 'tp_sh', 'orb', 'drb', 'blk', 'stl', 'rim_sh', 'dunk40', 'ft']
LAM, NBA_SEASONS, MIN_NBA_MP, MIN_COL_MPT = 0.3, 6, 500, 150
FLAG = 0.5
_FIT = None


def _shrink(x, n, prior, k):
    if x is None or not n: return prior
    return (x * n + prior * k) / (n + k)


def season_feats(s):
    """one college season's line, rates shrunk to the D-I mean by minutes / attempts (as cbb_fit.season_line)"""
    g = lambda k: s.get(k)
    mpt = (g('mp') or 0) * (g('gp') or 0)
    fga = (g('tpa') or 0) + (g('twopa') or 0)
    return {'ht': g('hti') or 77.0, 'mpt': mpt,
            'ast': _shrink(g('ast'), mpt, 10, 300), 'usg': _shrink(g('usg'), mpt, 16, 300), 'orb': _shrink(g('orb'), mpt, 5, 300),
            'drb': _shrink(g('drb'), mpt, 13, 300), 'blk': _shrink(g('blk'), mpt, 1.5, 400), 'stl': _shrink(g('stl'), mpt, 1.4, 400),
            'ft': _shrink(g('ft'), g('fta'), 0.69, 40),
            'tp_sh': _shrink((g('tpa') or 0) / fga if fga else None, fga, 0.33, 60),
            'rim_sh': _shrink((g('rima') or 0) / fga if fga else None, fga, 0.35, 60),
            'dunk40': math.log1p((g('dunka') or 0) / max(40, mpt) * 40)}


def pooled(seasons):
    """the line pooled over every season with minutes, weighted by minutes; height from the latest listing"""
    L = [season_feats(s) for s in seasons]
    ht = next((s.get('hti') for s in reversed(seasons) if s.get('hti')), None) or 77.0
    use = [x for x in L if x['mpt'] > 0] or L[-1:]
    w = sum(max(1.0, x['mpt']) for x in use)
    f = {k: sum(x[k] * max(1.0, x['mpt']) for x in use) / w for k in SKILL}
    f['ht'] = ht
    return f


def design(rows):
    return np.array([[f['ht'], (f['ht'] - 78) ** 2] + [f[k] for k in SKILL] for f in rows], float)


def softmax(Z):
    Z = Z - Z.max(1, keepdims=True); E = np.exp(Z)
    return E / E.sum(1, keepdims=True)


def fit_mnl(X, Y, w, lam):
    """multinomial logit, class 0 the reference, soft targets, row weights, L2 on slopes; Newton steps"""
    n, d = X.shape; K = Y.shape[1]; m = d + 1
    Xb = np.hstack([np.ones((n, 1)), X]); B = np.zeros((m, K))
    reg = np.full(m, lam); reg[0] = 1e-6
    for _ in range(60):
        P = softmax(Xb @ B)
        G = Xb.T @ ((P - Y) * w[:, None]); G[:, 1:] += reg[:, None] * B[:, 1:]
        H = np.zeros((m * (K - 1), m * (K - 1)))
        for a in range(1, K):
            for b in range(a, K):
                h = (Xb * (w * P[:, a] * ((a == b) - P[:, b]))[:, None]).T @ Xb
                if a == b: h += np.diag(reg)
                H[(a - 1) * m:a * m, (b - 1) * m:b * m] = h
                if a != b: H[(b - 1) * m:b * m, (a - 1) * m:a * m] = h
        step = np.linalg.solve(H + 1e-9 * np.eye(len(H)), np.concatenate([G[:, a] for a in range(1, K)]))
        for a in range(1, K): B[:, a] -= step[(a - 1) * m:a * m]
        if np.abs(step).max() < 1e-7: break
    return B


def load_fit():
    global _FIT
    if _FIT is None:
        try: _FIT = json.load(open(OUT))
        except (OSError, ValueError): _FIT = {}
    return _FIT


def project(seasons):
    """odds at PG, SG, SF, PF, C for a career's seasons so far (None without a fit)"""
    m = load_fit()
    if not m: return None
    x = (design([pooled(seasons)]) - np.array(m['mu'])) / np.array(m['sd'])
    return softmax(np.hstack([np.ones((1, 1)), x]) @ np.array(m['B']))[0]


def describe(seasons, pos=None):
    """[odds at PG..C (2 decimals), expected position 1-5, move group or None, move odds or None] for the board"""
    p = project(seasons)
    if p is None: return None
    g = {k: float(sum(p[i] for i in ix)) for k, ix in GRP.items()}
    to = max(g, key=g.get)
    # the flag needs a college line (150+ D-I minutes): a newcomer's odds are his height and the D-I mean line
    played = sum((s.get('mp') or 0) * (s.get('gp') or 0) for s in seasons)
    mv = to if pos in GRP and to != pos and g[to] >= FLAG and played >= MIN_COL_MPT else None
    return [[round(float(v), 2) for v in p], round(float(p @ np.arange(1, 6)), 2), mv, round(g[to], 2) if mv else None]


def fit():
    import cbb_data as D
    careers = json.load(open(os.path.join(D.CACHE, 'careers.json')))
    est = defaultdict(list)
    for r in json.load(gzip.open(EST, 'rt')): est[r['bref']].append(r)
    rows, Y, W, last, pids = [], [], [], [], []
    for c in careers:
        b = c['nba'].get('bref')
        if not b or b not in est: continue
        end = c['seasons'][-1]['year']
        ss = sorted((r for r in est[b] if r['year'] > end), key=lambda r: r['year'])[:NBA_SEASONS]
        mp = sum(r['mp'] for r in ss)
        if mp < MIN_NBA_MP: continue
        y = np.array([sum(r['mp'] * r['pct'][k] for r in ss) / mp for k in range(5)]); y /= y.sum()
        seas = [s for s in c['seasons'] if (s['mp'] or 0) * (s['gp'] or 0) >= MIN_COL_MPT and s['hti']]
        if not seas: continue
        for s in seas:
            rows.append(season_feats(s)); Y.append(y); W.append(1.0 / len(seas))
        last.append((y, pooled(seas), seas[-1]['hti'])); pids.append(c['pid'])
    X = design(rows); mu, sd = X.mean(0), X.std(0) + 1e-9
    B = fit_mnl((X - mu) / sd, np.array(Y), np.array(W), LAM)
    Yl = np.array([y for y, _, _ in last])
    # NBA players' size at each position, weighted by minutes there: the college listing (Barttorvik) and the combine
    def norm(vals, Ys):
        v = np.array(vals, float); ok = ~np.isnan(v); v, Ys = v[ok], Ys[ok]
        m_ = (Ys * v[:, None]).sum(0) / Ys.sum(0)
        s_ = np.sqrt((Ys * (v[:, None] - m_) ** 2).sum(0) / Ys.sum(0))
        pool = float(np.sqrt((Ys * (v[:, None] - m_) ** 2).sum() / Ys.sum()))
        return {'mean': [round(float(a), 2) for a in m_], 'sd': [round(float(a), 2) for a in s_], 'pooledSd': round(pool, 2), 'n': int(ok.sum())}
    norms = {'htListed': norm([h for _, _, h in last], Yl)}
    if os.path.exists(COMBINE):
        cm = {}
        for r in csv.DictReader(open(COMBINE, newline='', encoding='utf-8')):
            p = (r.get('pid') or '').split('.')[0]
            if p: cm[p] = r
        num = lambda r, k: float(r[k]) if r and r.get(k) not in (None, '') else float('nan')
        for k, col in (('htCombine', 'HGT'), ('wtCombine', 'WGT'), ('bmiCombine', 'BMI'), ('wingCombine', 'WNGSPN')):
            norms[k] = norm([num(cm.get(p), col) for p in pids], Yl)
    json.dump({'asof': __import__('datetime').date.today().isoformat(), 'pos': POS, 'feats': ['ht', 'ht2'] + SKILL, 'lam': LAM,
               'mu': [round(float(a), 6) for a in mu], 'sd': [round(float(a), 6) for a in sd], 'B': np.round(B, 6).tolist(),
               'n': len(last), 'flag': FLAG, 'norms': norms,
               'cv': {'ce': 0.881, 'ceRoleHt': 0.941, 'ceHt': 0.999, 'acc': 0.71, 'accRoleHt': 0.64,
                      'fwd2020_25': {'ce': 0.952, 'ceRoleHt': 0.972, 'ceHt': 1.030},
                      'flags': {'n': 139, 'right': 93, 'changes': 172, 'at70': [40, 50]}}}, open(OUT, 'w'), indent=1)
    print(f'{len(last)} NBA players; norms', {k: v['mean'] for k, v in norms.items()})


if __name__ == '__main__':
    if '--fit' in sys.argv: fit()
