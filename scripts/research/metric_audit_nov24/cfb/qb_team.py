#!/usr/bin/env python3
"""CFB QB metrics -> team offense, and team ratings (prereg.md), 2019-25 only (lockbox).
QB: value a full share x QB exposure (starter slot, games share) -> offensive rating (ridge on points scored, opponent
defense and home), describe (LOSO slope) / predict (n value x n+1 exposure) / player r. SV rows: scripts/data/sv_hist.json.gz
joined by scripts/names.py. Teams: SRS, margin a game, win %, ESPN FPI (final snapshot) on held-out half of games
(odd/even game id) and next-season SRS.   -> qb_team.json"""
import gzip, json, math, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts')); sys.path.insert(0, HERE)
import names
import harness as H

YEARS = H.YEARS; J = H.J
GAMES = {y: [g for g in J['GAMES'][str(y)]] for y in YEARS}


def ratings(G, fbs, kind='srs'):
    """ridge (2) ratings over FBS teams: srs = capped margin; off = points scored (offense, defense, home)"""
    T = sorted(fbs); ix = {t: i for i, t in enumerate(T)}; n = len(T)
    rows, ys = [], []
    for g in G:
        if g['h'] not in ix or g['a'] not in ix: continue
        if kind == 'srs':
            z = np.zeros(n + 1); z[ix[g['h']]] = 1; z[ix[g['a']]] = -1; z[n] = 0 if g['n'] else 1
            rows.append(z); ys.append(max(-35, min(35, g['hs'] - g['as'])))
        else:
            for o, d, p, home in ((g['h'], g['a'], g['hs'], 1), (g['a'], g['h'], g['as'], -1)):
                z = np.zeros(2 * n + 2); z[ix[o]] = 1; z[n + ix[d]] = 1; z[2 * n] = 0 if g['n'] else home; z[2 * n + 1] = 1
                rows.append(z); ys.append(p)
    X, Y = np.array(rows), np.array(ys); lam = np.full(X.shape[1], 2.0); lam[-1] = 0 if kind != 'srs' else 2.0
    if kind != 'srs': lam[-2] = 0
    else: lam[-1] = 0
    w = np.linalg.solve(X.T @ X + np.diag(lam), X.T @ Y)
    if kind == 'srs': v = w[:n]; return {t: float(v[ix[t]] - v.mean()) for t in T}
    o = w[:n]; return {t: float(o[ix[t]] - o.mean()) for t in T}


OFF = {y: ratings(GAMES[y], J['SRS'][str(y)], 'off') for y in YEARS}

# ---- QB rows ---------------------------------------------------------------------------------------------------------
SV = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'data', 'sv_hist.json.gz'), 'rt'))['cfb']
SVQ = defaultdict(list)
for r in SV:
    if r['g'] == 'QB' and r['y'] in YEARS: SVQ[r['y']].append(r)
MATCH = {y: names.Matcher(SVQ[y], name='n', team='t', pos='g') for y in YEARS}
TNAME = {}
for r in J['rows']: TNAME[(r['season'], r['tid'])] = r['raw'].get('team')
svq, joined = {}, defaultdict(int)
for y in YEARS:
    for pid, r in H.R[y].items():
        if r['pos'] != 'QB': continue
        row = next((x for x in J['rows'] if x['season'] == y and x['id'] + '|QB' == pid), None)
        m, how = MATCH[y].find(row['raw'].get('name'), team=row['raw'].get('team'), pos='QB')
        if m: svq[(y, pid)] = m; joined[y] += 1


def raw(y, pid): return next(x['raw'] for x in J['rows'] if x['season'] == y and x['id'] + '|' + x['pos'] == pid)


RAW = {(y, pid): raw(y, pid) for y in YEARS for pid, r in H.R[y].items() if r['pos'] == 'QB'}


def eff(y, pid):
    r = RAW[(y, pid)]; a = r.get('att') or 0
    if a < 20: return None
    return (8.4 * (r.get('pyds') or 0) + 330 * (r.get('ptd') or 0) + 100 * (r.get('cmp') or 0) - 200 * (r.get('int') or 0)) / a


def svrate(y, pid):
    m = svq.get((y, pid)); return None if not m or not m['pl'] else 60 * m['tot'] / m['pl']


QB_MEAN = {}
for y in YEARS:
    t = sum(r['tot'] for r in SVQ[y]); p = sum(r['pl'] for r in SVQ[y]); QB_MEAN[y] = t / p if p else 0


def psv(y, pid):
    """pSV/60 as shipped (cfb_season_value.py): seasons y, y-1, y-2 plays 1/.7/.5, shrunk to the QB mean a play by 650"""
    m = svq.get((y, pid))
    if not m: return None
    P = S = 0.0
    for i, w in enumerate((1, .7, .5)):
        yy = y - i
        h = m if i == 0 else next((r for r in SV if r['y'] == yy and r['g'] == 'QB' and r['id'] == m['id']), None)
        if h: P += w * h['tot']; S += w * h['pl']
    mu = np.mean([QB_MEAN[x] for x in YEARS if x <= y])
    return 60 * (P + 650 * mu) / (S + 650)


QM = {'pfn_qb_z': lambda y, p: H.R[y][p]['z'], 'xv_qb': lambda y, p: H.R[y][p]['xq'],
      'nypa': lambda y, p: RAW[(y, p)].get('nypa'), 'pass_eff': eff, 'sv60': svrate, 'psv60': psv}


def qb_score(fn, label, target=None):
    # describe: QB sum vs offense rating; LOSO slope
    def F(y, val):
        x = defaultdict(float)
        for pid, t, e in H.PARTS[(y, 7)]:
            if not pid.endswith('|QB'): continue
            v = val(y, pid)
            x[t] += (v if v is not None else 0.0) * e
        return x
    def std_t(y, f):
        vs = {p: f(y, p) for p in H.R[y] if p.endswith('|QB')}
        ok = [v for v in vs.values() if v is not None]; m, s = np.mean(ok), np.std(ok) or 1
        return {p: ((v - m) / s if v is not None else None) for p, v in vs.items()}
    # common fill: a QB with no value takes the season's low-exposure mean; values standardised within season
    def std(y):
        vs = {p: fn(y, p) for p in H.R[y] if p.endswith('|QB')}
        ok = [v for v in vs.values() if v is not None]; m, s = np.mean(ok), np.std(ok) or 1
        fl = np.mean([(vs[p] - m) / s for p in vs if vs[p] is not None and H.R[y][p]['sh'] < .3] or [0])
        return {p: ((v - m) / s if v is not None else fl) for p, v in vs.items()}
    Z = {y: std(y) for y in YEARS}
    TZ = {y: std(y) for y in YEARS} if target is None else {y: (lambda f: {p: v for p, v in f.items()})(std_t(y, target)) for y in YEARS}
    desc = {y: H.centre({t: np.array([v]) for t, v in F(y, lambda yy, p: Z[yy][p]).items()}, OFF[y]) for y in YEARS}
    d, sqd = H.score_rows(desc)
    prows, pl = {}, []
    for n in YEARS[:-1]:
        x = defaultdict(float)
        for pid, t, e in H.PARTS[(n + 1, 7)]:
            if not pid.endswith('|QB'): continue
            x[t] += Z[n].get(pid, min(Z[n].values())) * e if pid in Z[n] else 0.0
        prows[n] = H.centre({t: np.array([v]) for t, v in x.items()}, OFF[n + 1])
        for pid, r in H.R[n + 1].items():
            if pid.endswith('|QB') and r['sh'] >= .4 and pid in Z[n] and fn(n, pid) is not None and TZ[n + 1].get(pid) is not None:
                pl.append((Z[n][pid], TZ[n + 1][pid], r['sh']))
    p, sqp = H.score_rows(prows)
    px, py, pw = zip(*pl)
    return dict(label=label, describeIns=d['ins'], describeOOS=d['oos'], describeCI=d['oosCI'], predictTeam=p['ins'],
                predictOOS=p['oos'], predictCI=p['insCI'], playerR=round(H.core.wcorr(px, py, pw), 4), nPlayers=len(pl)), sqd, sqp


# ---- team ratings ----------------------------------------------------------------------------------------------------
FPI = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'data', 'public_ratings', 'cfb_fpi.json.gz'), 'rt'))


def fpi_final(y):
    snaps = FPI.get(str(y)) or []
    return snaps[-1][1] if snaps else None


def team_metric(kind, G, fbs):
    if kind == 'srs': return ratings(G, fbs, 'srs')
    a = defaultdict(lambda: [0.0, 0])
    for g in G:
        for t, m in ((g['h'], g['hs'] - g['as']), (g['a'], g['as'] - g['hs'])):
            if t in fbs: a[t][0] += (m if kind == 'margin' else float(m > 0) - float(m < 0) * 0 if kind == 'win' else m); a[t][1] += 1
    return {t: s / n for t, (s, n) in a.items() if n}


def team_block():
    out = {}
    for kind in ('srs', 'margin', 'win'):
        hx, hy, px, py = [], [], [], []
        for y in YEARS:
            fbs = J['SRS'][str(y)]
            A = team_metric(kind, [g for g in GAMES[y] if int(g['id']) % 2 == 0], fbs)
            B = ratings([g for g in GAMES[y] if int(g['id']) % 2 == 1], fbs, 'srs')
            ts = [t for t in A if t in B]; hx += [A[t] - np.mean([A[u] for u in ts]) for t in ts]; hy += [B[t] for t in ts]
            if y + 1 in YEARS:
                F = team_metric(kind, GAMES[y], fbs); N = J['SRS'][str(y + 1)]
                ts = [t for t in F if t in N]; px += [F[t] for t in ts]; py += [N[t] for t in ts]
        full = [(team_metric(kind, GAMES[y], J['SRS'][str(y)]), J['SRS'][str(y)]) for y in YEARS]
        ins = H.r2([a[t] for a, b in full for t in a if t in b], [b[t] for a, b in full for t in a if t in b])
        out[kind] = dict(describeIns=round(ins, 4), describeHeldHalf=round(H.r2(hx, hy), 4), predictNext=round(H.r2(px, py), 4), n=len(px))
    # FPI: final snapshot, same-season SRS and next-season SRS; held-out half: FPI final vs odd-game SRS (uses all games)
    ix, iy, px, py = [], [], [], []
    for y in YEARS:
        f = fpi_final(y)
        if not f: continue
        S = J['SRS'][str(y)]; ts = [t for t in f if t in S]; ix += [f[t] for t in ts]; iy += [S[t] for t in ts]
        if y + 1 in YEARS:
            N = J['SRS'][str(y + 1)]; ts = [t for t in f if t in N]; px += [f[t] for t in ts]; py += [N[t] for t in ts]
    out['fpi'] = dict(describeIns=round(H.r2(ix, iy), 4), describeHeldHalf=None, predictNext=round(H.r2(px, py), 4), n=len(px),
                      note='ESPN FPI keeps a preseason prior all season, so same-season fit is not a held-out read')
    return out


if __name__ == '__main__':
    print('sv joined', dict(joined), flush=True)
    res = {'qb': {}, 'teams': team_block()}
    for k, v in res['teams'].items(): print('team', k, v)
    for k, fn in QM.items():
        o, _, _ = qb_score(fn, k, svrate if k == 'psv60' else None); res['qb'][k] = o; print('qb', k, o, flush=True)
    json.dump(res, open(os.path.join(HERE, 'qb_team.json'), 'w'), indent=1)
