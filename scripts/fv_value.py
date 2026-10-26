#!/usr/bin/env python3
"""FV on one value scale (Noah, Oct 26 2026): FV is Future Value, the expected PEAK surplus over replacement, measured
the same way in every sport, so a 55 is worth the same in college football, college basketball, hockey and soccer.

    python3 scripts/fv_value.py --fit     # realized peak shares by sport -> data/fv_value.json, and binShare /
                                          # shareCurve into data/fv_dist.json (the CFB and CBB outlooks read them)
    python3 scripts/fv_value.py --test    # the map's round trips

Peak      The mean of a player's best three seasons at ages 22-28, missing seasons counted as 0 (one window for every
          sport; hockey's old seven seasons after the draft ended at 25 and cut a best-of-class peak from 29% of a
          team to 11%).
Surplus   Each sport's own wins-above-replacement, as a share of an average team's surplus that season (TS), so a
          sport's roster size and replacement level come out in the division:
            NFL     WAR (scripts/nfl_war.py: team WAR sums to wins - 3, so 5.5 a team over 17 games); first seven
                    NFL seasons (drafted at ~22)
            NBA     VORX (scripts/nba_xpm.py, wins over replacement on XPM; ~18 a team)
            NHL     descriptive WAR (static/data/nhl-war; ~23 a team); goalies at the skater share of the same rarity
                    among goalies, after GOALIE_GP games, as the hockey board ranks them
            soccer  the prospect board's GAR (scripts/soccer_prospects.py), over the season's mean big-five club total
          A team's surplus is what its cap or wage budget buys, so TS is the player's cap share at market prices.
Map       FV = 20 + 30 ln(1 + TS/C) / ln 15, C = 1/280, capped at 80: 20 = replacement, 50 = 5% of a team (an
          average regular on a 20-man roster), 80 = 80% (an MVP peak, about one NBA player every two classes).
          Each step of 10 multiplies TS + C by 2.47. TS at each FV: 30 0.5%, 35 1.0%, 40 1.8%, 45 3.1%, 50 5%,
          55 8.1%, 60 12.9%, 65 20.4%, 70 32.2%, 75 50.8%, 80 80%.
Headline  The FV of the expected peak share, E[TS] (no Jensen gap: a wide range is worth its mean value, not the mean
          of its grades). The old rarity outcome of each board stays the model's target; shareCurve maps it to TS.
"""
import csv, gzip, json, math, os, sys
from collections import defaultdict
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
OUT = os.path.join(ROOT, 'data', 'fv_value.json')
DIST = os.path.join(ROOT, 'data', 'fv_dist.json')
C = 1 / 280
BASE = 15.0
PEAK_AGES = (22, 28)
EDGES = [30, 35, 40, 45, 50, 55, 60, 65, 70]          # the outlook bins (scripts/fv_dist_fit.py)


def fv_of_share(ts):
    """FV of a peak team share (scalar or array), 20-80"""
    t = np.maximum(np.asarray(ts, dtype=float), 0)
    f = np.minimum(80.0, 20 + 30 * np.log1p(t / C) / math.log(BASE))
    return float(f) if f.ndim == 0 else f


def share_of_fv(fv):
    f = np.clip(np.asarray(fv, dtype=float), 20, 80)
    t = C * (BASE ** ((f - 20) / 30) - 1)
    return float(t) if t.ndim == 0 else t


_FIT = None


def fit():
    global _FIT
    if _FIT is None:
        try:
            _FIT = json.load(open(OUT))
        except (OSError, ValueError):
            _FIT = {}
    return _FIT


def share_of_old(sport, fv_old):
    """E[TS] of a career that earned fv_old on the sport's old outcome ladder (data/fv_value.json shareCurve)"""
    k = np.array(fit()[sport]['curve'])
    return float(np.interp(fv_old, k[:, 0], k[:, 1]))


def peak3(v):
    v = sorted(v, reverse=True) + [0.0, 0.0, 0.0]
    return sum(v[:3]) / 3


def isotonic(x, y, width=2.5, nmin=25):
    """monotone mean of y on x: bins of x pooled until increasing (as soccer_prospects.isotonic)"""
    o = np.argsort(x); x, y = np.asarray(x, float)[o], np.asarray(y, float)[o]
    bins, cur = [], []
    edge = math.floor(x[0] / width) * width
    for a, b in zip(x, y):
        if a >= edge + width and len(cur) >= nmin:
            bins.append(cur); cur = []; edge = math.floor(a / width) * width
        cur.append((a, b))
    if cur:
        if len(cur) < nmin and bins: bins[-1] += cur
        else: bins.append(cur)
    out = []
    for b in bins:
        out.append([np.mean([a for a, _ in b]), np.mean([c for _, c in b]), len(b)])
        while len(out) > 1 and out[-2][1] >= out[-1][1]:
            b2, b1 = out.pop(), out.pop(); n = b1[2] + b2[2]
            out.append([(b1[0] * b1[2] + b2[0] * b2[2]) / n, (b1[1] * b1[2] + b2[1] * b2[2]) / n, n])
    return out


def curve(old, ts, lo=20.0, hi=80.0):
    """knots [[old FV, mean TS]] from 20 to 80: isotonic blocks, the floor at its own mean, the top carried on by the
    top blocks' slope in log share"""
    old, ts = np.asarray(old, float), np.asarray(ts, float)
    fl = old <= 20.0001
    k = [[20.0, float(ts[fl].mean()) if fl.any() else 0.0]]
    for a, b, n in isotonic(old[~fl], ts[~fl]):
        if b > k[-1][1]: k.append([float(a), float(b)])
    if k[-1][0] < hi and len(k) >= 3:
        (x1, y1), (x2, y2) = k[-3], k[-1]
        g = (math.log(y2) - math.log(max(y1, 1e-6))) / max(x2 - x1, 1e-6)
        k.append([hi, float(y2 * math.exp(g * (hi - x2)))])
    return [[round(a, 2), round(b, 5)] for a, b in k]


def vmap(knots, x):
    """FV of the expected peak share at a board's old-scale grade x (knots from curve(grades, realized shares))"""
    k = np.asarray(knots, float)
    return fv_of_share(np.interp(x, k[:, 0], k[:, 1]))


def cv_vmap(x, ts, groups):
    """the grade -> expected share map, each group's rows mapped by a fit on the other groups (held out)"""
    x, ts, out = np.asarray(x, float), np.asarray(ts, float), np.zeros(len(x))
    for g in sorted(set(groups)):
        m = groups == g
        k = np.array(curve(x[~m], ts[~m]))
        out[m] = np.interp(x[m], k[:, 0], k[:, 1])
    return out


def logit_fit(x, y):
    """P(y) = 1 / (1 + exp(-(a + b x))) by Newton"""
    X = np.column_stack([np.ones(len(x)), np.asarray(x, float)]); w = np.zeros(2)
    for _ in range(60):
        q = 1 / (1 + np.exp(-X @ w))
        H = (X * (q * (1 - q))[:, None]).T @ X + 1e-6 * np.eye(2)
        w = w + np.linalg.solve(H, X.T @ (y - q))
    return [round(float(v), 4) for v in w]


def bin_share(old, ts):
    """mean TS of the careers in each outlook bin (<30, 30-34, ... 70+)"""
    b = np.searchsorted(EDGES, old, side='right')
    out = []
    for j in range(len(EDGES) + 1):
        m = b == j
        out.append(round(float(ts[m].mean()), 5) if m.any() else None)
    for j in range(len(out)):                 # an empty bin takes its neighbours' mean
        if out[j] is None:
            nb = [v for v in (out[j - 1] if j else None, out[j + 1] if j + 1 < len(out) else None) if v is not None]
            out[j] = round(sum(nb) / len(nb), 5) if nb else 0.0
    return out


def bin_tiers(old, ts, tiers=(30, 40, 50, 60)):
    """per outlook bin, the share of its careers whose peak share reached each value tier (the tier odds the board
    shows; a bin's careers aren't spread evenly over it, the top bin's pile at the cap)"""
    b = np.searchsorted(EDGES, old, side='right'); v = np.array([fv_of_share(x) for x in ts]); out = []
    for j in range(len(EDGES) + 1):
        m = b == j
        out.append([round(float((v[m] >= t).mean()), 4) for t in tiers] if m.sum() >= 5 else None)
    for j in range(len(out)):                 # a thin bin takes its neighbours'
        if out[j] is None:
            nb = [x for x in (out[j - 1] if j else None, out[j + 1] if j + 1 < len(out) else None) if x is not None]
            out[j] = [round(sum(c) / len(nb), 4) for c in zip(*nb)] if nb else [0.0] * len(tiers)
    for j in range(1, len(out)):              # never below the bin under it
        out[j] = [max(a, c) for a, c in zip(out[j], out[j - 1])]
    return out


def per_class(ts, ncls):
    """how many players a class reach each FV on the shared map"""
    f = fv_of_share(np.asarray(ts))
    return {str(v): round(float((f >= v).sum()) / ncls, 2) for v in (80, 75, 70, 65, 60, 55, 50, 45, 40)}


def ranked(ts, ncls, ks=(0.25, 0.5, 1, 2, 5, 10, 20, 30, 45)):
    v = np.sort(np.asarray(ts))[::-1]
    return {str(k): [round(float(v[max(1, int(round(k * ncls))) - 1]), 4), round(fv_of_share(v[max(1, int(round(k * ncls))) - 1]), 1)] for k in ks}


# ---------------------------------------------------------------- NHL (hockey board)
TEAM = {'cfb': 5.5}   # a mean team's surplus a season in each sport's unit (NFL WAR a 17-game season; set by the pulls)


def nhl():
    import hockey_prospects as HP
    W = HP.war_tables()
    tw = {}
    for S, d in W.items():
        t = defaultdict(float)
        for p in d.values(): t[p['tm']] += p.get('war') or 0
        tw[S] = sum(t.values()) / len(t)
    TEAM['nhl'] = round(float(np.mean(list(tw.values()))), 1)
    rows = HP.read_rows(W)
    sc = HP.outcome_scale(rows)
    out = []
    for r in rows:
        if not (HP.FIRST <= r['year'] <= 2016) or not r.get('birth'): continue    # age 28 by 2026-27
        by, bm = int(r['birth'][:4]), int(r['birth'][5:7])
        v, gx, gp = [], [], 0
        for S in sorted(W):
            age = S - 1 - by - (1 if bm >= 10 else 0)        # age on Oct 1 of the season
            if PEAK_AGES[0] <= age <= PEAK_AGES[1]:
                q = W[S].get(r['id'])
                v.append((q.get('war') or 0) / tw[S] if q else 0.0)
                gx.append((q.get('gsax') or 0) * 82 / max(1, q.get('gp') or 1) if q and r['G'] else 0.0)
                gp += (q.get('gp') or 0) if q else 0
        out.append({'year': r['year'], 'name': r['name'], 'G': r['G'], 'old': HP.fv_of(r, sc), 'ts': peak3(v),
                    'gts': peak3([x / 82 for x in gx]) if r['G'] else 0.0, 'gp': gp})
    sk = np.sort([o['ts'] for o in out if not o['G']])[::-1]
    gk = np.sort([o['ts'] for o in out if o['G'] and o['gp'] >= HP.GOALIE_GP])[::-1]
    ng = sum(1 for o in out if o['G'])
    for o in out:
        if o['G']:
            if o['gp'] < HP.GOALIE_GP:
                o['ts'] = 0.0
            else:   # a goalie at the skater share of the same rarity among all drafted goalies
                q = (gk > o['ts']).sum() / max(ng, 1)
                o['ts'] = float(sk[min(int(q * len(sk)), len(sk) - 1)])
    return out, 2016 - HP.FIRST + 1


# ---------------------------------------------------------------- NBA (college basketball board)
def nba_seasons():
    seas, age, nm, tw = defaultdict(dict), {}, {}, {}
    d0 = os.path.join(ROOT, 'static', 'data', 'nba-xpm')
    for fn in sorted(os.listdir(d0)):
        if not fn[:4].isdigit(): continue
        y = int(fn[:4]); d = json.load(open(os.path.join(d0, fn)))
        t = defaultdict(float)
        for p in d['players']:
            seas[p['id']][y] = seas[p['id']].get(y, 0) + (p.get('vorx') or 0)
            t[p['tm']] += p.get('vorx') or 0
            if p.get('age') is not None: age.setdefault(p['id'], (y, p['age']))
            nm[p['id']] = p['n']
        if y < 2027: tw[y] = sum(t.values()) / 30       # 2026-27 has barely started
    return seas, age, nm, tw


def nba_ts(pid, seas, age, tw):
    y0, a0 = age[pid]
    v = [seas[pid].get(y, 0) / tw[y] for y in range(y0 + PEAK_AGES[0] - a0, y0 + PEAK_AGES[1] - a0 + 1) if y in tw]
    return peak3(v)


def cbb():
    import names as NM
    seas, age, nm, tw = nba_seasons()
    TEAM['cbb'] = round(float(np.mean(list(tw.values()))), 1)
    first = {pid: min(s) for pid, s in seas.items()}
    by = defaultdict(list)
    for pid in seas:
        if pid in age: by[NM.key(nm[pid])].append(pid)
    d = json.load(open(os.path.join(ROOT, 'static', 'data', 'cbb-past.json')))
    c = {k: i for i, k in enumerate(d['cols'])}
    out, miss = [], 0
    for r in d['rows']:
        if r[c['season']] > 2016 or r[c['outcome']] is None: continue
        y = float(r[c['outcome']]); ts = 0.0
        if y > 20:
            cand = [p for p in by.get(NM.key(r[c['name']]), []) if first[p] > r[c['season']]]
            if len(cand) > 1 and r[c['draft']]:
                cand = [p for p in cand if abs(first[p] - (r[c['draft']] + 1)) <= 1] or cand
            if cand:
                ts = nba_ts(min(cand, key=lambda p: first[p]), seas, age, tw)
            else:
                miss += 1; continue
        out.append({'season': r[c['season']], 'name': r[c['name']], 'old': y, 'ts': ts})
    return out, miss


def nba_cohorts():
    """every NBA player aged 22 in 2010-19, best three seasons at 22-28 (the per-class table)"""
    seas, age, nm, tw = nba_seasons()
    v = []
    for pid in seas:
        if pid not in age: continue
        y0, a0 = age[pid]
        if 2010 <= y0 + PEAK_AGES[0] - a0 <= 2019: v.append(nba_ts(pid, seas, age, tw))
    return v, 10


# ---------------------------------------------------------------- NFL (college football board)
AV_BY_FV = [[20, 0], [30, 0.4], [40, 1.7], [50, 3.7], [60, 5.0], [65, 6.3], [70, 7.2], [75, 8.1], [80, 10.1]]   # cfb_teams.mjs
PFR_AV = 1.05          # PFR weighted AV over the NFL WAR model's season AV, drafts 2016-18 (r .97)


def nfl():
    """drafts 2016-19: TS over the first seven NFL seasons, and the CFB outlook's outcome (weighted AV a season) as it
    reads after 3-6 seasons (the --dist rows' drafts 2020-23 have 3-6 seasons through 2025), one row per window"""
    T = json.load(open(os.path.join(ROOT, 'scripts', '.cache', 'fvrefit', 'nfl_targets.json')))
    f, a = zip(*AV_BY_FV)
    out, ts7 = [], []
    for pid, v in T.items():
        D = v['draft']
        if not 2016 <= D <= 2019: continue
        S = lambda y, i: (v['seasons'].get(str(y)) or [0, 0])[i]
        w = [S(y, 1) / (5.18 if y <= 2020 else 5.5) for y in range(D, D + 7)]     # 16-game seasons: 8 - 2.8 wins
        ts = peak3(w); ts7.append(ts)
        for k in (3, 4, 5, 6):
            av = sorted([S(y, 0) for y in range(D, D + k)], reverse=True)
            x = PFR_AV * sum(q * max(0, 1 - .05 * i) for i, q in enumerate(av)) / k
            out.append({'draft': D, 'k': k, 'old': float(np.interp(x, a, f)), 'ts': ts})
    return out, ts7, 4


# ---------------------------------------------------------------- fit
def main_fit():
    res = json.load(open(OUT)) if os.path.exists(OUT) else {}
    res.update({'asof': __import__('datetime').date.today().isoformat(), 'method': 'scripts/fv_value.py',
                'map': {'C': C, 'base': BASE, 'peakAges': list(PEAK_AGES),
                        'ts': {str(v): round(share_of_fv(v), 4) for v in range(20, 81, 5)}}})
    dist = json.load(open(DIST))
    # hockey
    H, nh = nhl()
    old, ts = np.array([o['old'] for o in H]), np.array([o['ts'] for o in H])
    res['nhl'] = {'unit': 'NHL WAR / mean team WAR', 'classes': [2008, 2016], 'n': len(H), 'curve': curve(old, ts),
                  'perClass': per_class(ts, nh), 'ranked': ranked(ts, nh),
                  'top': [[o['name'], o['year'], round(o['ts'], 3)] for o in sorted(H, key=lambda o: -o['ts'])[:10]]}
    print('NHL', res['nhl']['ranked'], res['nhl']['perClass'])
    # basketball
    B, miss = cbb()
    old, ts = np.array([o['old'] for o in B]), np.array([o['ts'] for o in B])
    v, nc = nba_cohorts()
    res['cbb'] = {'unit': 'NBA VORX / mean team VORX', 'rows': 'static/data/cbb-past.json 2010-16 boards, top 300', 'n': len(B),
                  'unlinked': miss, 'curve': curve(old, ts), 'binShare': bin_share(old, ts), 'binTiers': bin_tiers(old, ts),
                  'perClass': per_class(v, nc), 'ranked': ranked(v, nc)}
    print('CBB rows', len(B), 'unlinked', miss, res['cbb']['binShare'], res['cbb']['perClass'])
    # football
    N, ts7, nf = nfl()
    old, ts = np.array([o['old'] for o in N]), np.array([o['ts'] for o in N])
    res['cfb'] = {'unit': 'NFL WAR / team surplus (5.5 a 17-game season)', 'rows': 'drafts 2016-19, AV a season after 3-6 seasons',
                  'n': len(N), 'curve': curve(old, ts), 'binShare': bin_share(old, ts), 'binTiers': bin_tiers(old, ts),
                  'perClass': per_class(ts7, nf), 'ranked': ranked(ts7, nf)}
    print('CFB', res['cfb']['binShare'], res['cfb']['perClass'])
    for b in ('nhl', 'cbb', 'cfb'): res[b]['team'] = TEAM.get(b)
    for b in ('cfb', 'cbb'):
        dist[b]['binShare'] = res[b]['binShare']
        dist[b]['shareCurve'] = res[b]['curve']
        dist[b]['binTiers'] = res[b]['binTiers']
    json.dump(res, open(OUT, 'w'), indent=1)
    json.dump(dist, open(DIST, 'w'), indent=1)


# ---------------------------------------------------------------- held-out: the value headline against the old one
def avg_rank(a):
    """ranks with ties at their average (most careers tie at the replacement share)"""
    a = np.asarray(a, float); r = np.empty(len(a)); r[np.argsort(a, kind='mergesort')] = np.arange(len(a))
    _, inv = np.unique(a, return_inverse=True)
    return (np.bincount(inv, r) / np.bincount(inv))[inv]


def rank_corr(a, b):
    return float(np.corrcoef(avg_rank(a), avg_rank(b))[0, 1])


def compare_heads(label, ts, heads, folds, groups=None, top=(10, 30)):
    """heads: name -> held-out predicted TS. MSE on the realized peak share, paired by fold (t, wins), rank correlation,
    calibration by predicted FV band (in FV: the band's mean predicted share vs its mean realized share) and the realized
    share of each group's top N"""
    ts = np.asarray(ts, float); out = {}
    base = next(iter(heads))
    for name, pr in heads.items():
        pr = np.asarray(pr, float)
        e = (pr - ts) ** 2
        r = {'mse': round(float(e.mean()) * 1e4, 3), 'rank': round(rank_corr(pr, ts), 4), 'meanPred': round(float(pr.mean()), 4), 'meanReal': round(float(ts.mean()), 4)}
        if name != base:
            d = np.array([((np.asarray(heads[base])[folds == f] - ts[folds == f]) ** 2).mean() - e[folds == f].mean() for f in sorted(set(folds))])
            r['vsBase'] = {'gain': round(float(d.mean()) * 1e4, 4), 't': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)) + 1e-15)), 2), 'wins': int((d > 0).sum()), 'of': len(d)}
        f = fv_of_share(pr); cal = []
        for lo in range(20, 80, 5):
            m = (f >= lo) & (f < lo + 5)
            if m.sum() >= 10: cal.append([lo, int(m.sum()), round(fv_of_share(pr[m].mean()), 1), round(fv_of_share(ts[m].mean()), 1)])
        r['calib'] = cal
        # calibration: the band-size-weighted miss in FV (band given vs reached) and the mean miss's t over the folds
        r['calErr'] = round(sum(c[1] * abs(c[2] - c[3]) for c in cal) / max(1, sum(c[1] for c in cal)), 2)
        b = np.array([(ts[folds == f] - pr[folds == f]).mean() for f in sorted(set(folds))])
        r['biasT'] = round(float(b.mean() / (b.std(ddof=1) / math.sqrt(len(b)) + 1e-15)), 2)
        if groups is not None:
            for n in top:
                v = []
                for g in sorted(set(groups)):
                    ix = np.where(groups == g)[0]
                    v.append(ts[ix[np.argsort(-pr[ix])[:n]]].mean())
                r[f'top{n}'] = round(fv_of_share(float(np.mean(v))), 2)
        out[name] = r
        print(label, name, {k: v for k, v in r.items() if k != 'calib'})
    return out


def backtest_cbb():
    import hashlib
    import fv_dist_fit as DF
    dist = json.load(open(DIST))
    DF.HINGES = tuple(dist['cbb']['hinges'])
    rows = DF.cbb_rows()
    B, _ = cbb()
    tsk = {(o['season'], o['name']): o['ts'] for o in B}
    rows = [r for r in rows if (r['season'], r['name']) in tsk]
    ts = np.array([tsk[(r['season'], r['name'])] for r in rows])
    base, extra = DF.cbb_terms()
    terms = [t for t in base + extra if t[0] in dist['cbb']['kept']]
    folds = np.array([int(hashlib.md5(r['name'].encode()).hexdigest(), 16) % 5 for r in rows])
    P = DF.held_out(rows, folds, [('m', terms)])['m']
    ys = np.array([r['y'] for r in rows]); x = np.array([r['x'] for r in rows])
    A, Bv, G = np.zeros(len(rows)), np.zeros(len(rows)), np.zeros(len(rows))
    for f in sorted(set(folds)):
        tr, te = folds != f, folds == f
        k = np.array(curve(ys[tr], ts[tr]))
        bm = np.array(DF.bin_stats(ys[tr])[0])
        A[te] = np.interp(P[te] @ bm, k[:, 0], k[:, 1])          # today's headline (mean of the old ladder), as a share
        Bv[te] = P[te] @ np.array(bin_share(ys[tr], ts[tr]))     # the value headline
        G[te] = np.interp(x[te], k[:, 0], k[:, 1])               # the grade, as a share
    seasons = np.array([r['season'] for r in rows])
    return compare_heads('cbb', ts, {'mean of the old ladder': A, 'grade': G, 'expected share': Bv}, folds, seasons)


def backtest_cfb():
    """the --dist rows (FBS seasons 2019-22, drafts 2020-23), one draft class held out: each row's outcome read as a
    share through the football curve (fit on the 2016-19 drafts, so no row's own career sets it). Also the Jensen
    check: within a grade band, do seniors and earlier seasons reach what each headline promises?"""
    import fv_dist_fit as DF
    dist = json.load(open(DIST)); M = dist['cfb']
    rows = DF.cfb_rows()
    base, extra = DF.cfb_terms()
    terms = [t for t in base + extra if t[0] in M['kept']]
    folds = np.array([r['last'] for r in rows])
    P = DF.held_out(rows, folds, [('m', terms)])['m']
    ys = np.array([r['y'] for r in rows]); x = np.array([r['x'] for r in rows])
    k = np.array(fit()['cfb']['curve'])
    ts = np.interp(ys, k[:, 0], k[:, 1])
    A, G = np.zeros(len(rows)), np.interp(x, k[:, 0], k[:, 1])
    for f in sorted(set(folds)):
        te = folds == f
        A[te] = np.interp(P[te] @ np.array(DF.bin_stats(ys[folds != f])[0]), k[:, 0], k[:, 1])
    Bv = P @ np.array(M['binShare'])
    out = compare_heads('cfb', ts, {'mean of the old ladder': A, 'grade': G, 'expected share': Bv}, folds, folds)
    fin = np.array([bool(r['final']) for r in rows])
    jg = {}
    for name, pr in (('mean of the old ladder', A), ('expected share', Bv)):
        f = fv_of_share(pr); jg[name] = []
        for lo in range(30, 75, 5):
            row = [lo]
            for grp in (fin, ~fin):
                m = grp & (x >= lo) & (x < lo + 5)
                row += [int(m.sum()), round(fv_of_share(pr[m].mean()), 1) if m.sum() else None, round(fv_of_share(ts[m].mean()), 1) if m.sum() else None]
            jg[name].append(row)
        print('cfb', name, 'by grade band: [lo, n final, given, reached, n earlier, given, reached]', jg[name])
    out['finalVsEarlier'] = jg
    return out


def test():
    for v in (20, 30, 40, 50, 60, 70, 80):
        assert abs(fv_of_share(share_of_fv(v)) - v) < 1e-9, v
    assert abs(fv_of_share(0.05) - 50) < 1e-9 and abs(fv_of_share(0.8) - 80) < 1e-9 and fv_of_share(0) == 20
    import fv_dist as FD   # the stdlib copy the board builds use
    for t in (0, 0.001, 0.01, 0.05, 0.2, 0.8, 2):
        assert abs(FD.fv_of_share(t) - fv_of_share(t)) < 1e-9 and abs(FD.share_of_fv(fv_of_share(t)) - min(t, 0.8)) < 1e-9, t
    print('ok', {v: round(share_of_fv(v), 4) for v in range(20, 81, 10)})


if __name__ == '__main__':
    if '--test' in sys.argv: test()
    elif '--fit' in sys.argv: main_fit()
    elif '--backtest' in sys.argv:
        res = json.load(open(OUT))
        bt = res.setdefault('backtest', {})
        if 'cbb' in sys.argv: bt['cbb'] = backtest_cbb()
        if 'cfb' in sys.argv: bt['cfb'] = backtest_cfb()
        json.dump(res, open(OUT, 'w'), indent=1)
    else: print(__doc__)
