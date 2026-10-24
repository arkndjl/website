#!/usr/bin/env python3
"""Round-2 research harness (Oct 24 2026): do pbpstats player fields (shot-zone mix, assisted share, fouls drawn, shot
quality, on/off) improve next-season per-minute NBA player stats over this season's rates?  Also an XPM sanity check.

    python3 scripts/nba_pbpstats_backtest.py --pull DIR        # api.pbpstats.com/get-totals/nba Type=Player, 2000-01..2025-26
    python3 scripts/nba_pbpstats_backtest.py DIR               # backtest (needs static/data/nba-xpm for age/position)

Test (a): target = season s+1 per-36 PTS / REB / AST of players with 500+ minutes in both seasons, baseline = ridge on
this season's rate, last season's rate (when there), age, minutes; candidate blocks add pbpstats fields. Walk-forward
by target season (train on earlier pairs), error weighted by next-season minutes. Tune = targets 2014-20, held 2021-26.
Test (b): XPM against pbpstats on/off and shot-quality fields."""
import json, math, os, subprocess, sys, time
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
D = sys.argv[-1]


def pull():
    for y in range(2001, 2027):
        f = os.path.join(D, 'p%d.json' % y)
        if os.path.exists(f) and os.path.getsize(f) > 1000:
            continue
        s = '%d-%02d' % (y - 1, y % 100)
        subprocess.run(['curl', '-s', '-m', '90', '-o', f, 'https://api.pbpstats.com/get-totals/nba?Season=%s&SeasonType=Regular%%20Season&Type=Player' % s])
        time.sleep(1)


if '--pull' in sys.argv:
    os.makedirs(D, exist_ok=True)
    pull()
    sys.exit()

import names
XP = {}
for y in range(2010, 2027):
    p = os.path.join(HERE, '..', 'static', 'data', 'nba-xpm', '%d.json' % y)
    if os.path.exists(p):
        for r in json.load(open(p))['players']:
            k = (y, names.key(r['n']))
            if k not in XP or r['mp'] > XP[k]['mp']:
                XP[k] = r

# ---- load
P = {}   # (season, entity) -> row
for y in range(2001, 2027):
    f = os.path.join(D, 'p%d.json' % y)
    if not os.path.exists(f):
        continue
    for r in json.load(open(f))['multi_row_table_data']:
        r['_y'] = y
        P[(y, r['EntityId'])] = r


def g(r, k):
    v = r.get(k)
    return float(v) if v is not None else 0.0


def per36(r, k):
    return 36 * g(r, k) / max(g(r, 'Minutes'), 1)


STATS = {'PTS': 'Points', 'REB': 'Rebounds', 'AST': 'Assists'}
ZONE = ['AtRimFrequency', 'ShortMidRangeFrequency', 'LongMidRangeFrequency', 'Corner3Frequency', 'Arc3Frequency']


def feats(r):
    """candidate blocks (all from season s)"""
    m = max(g(r, 'Minutes'), 1)
    fga = max(g(r, 'FG2A') + g(r, 'FG3A'), 1)
    out = {}
    out['zone'] = [g(r, k) for k in ZONE] + [g(r, 'Avg2ptShotDistance'), g(r, 'Avg3ptShotDistance')]
    out['zacc'] = [g(r, 'AtRimAccuracy'), g(r, 'Corner3Accuracy') , g(r, 'Arc3Accuracy')]
    out['asst'] = [g(r, 'Assisted2sPct'), g(r, 'Assisted3sPct'), g(r, 'AtRimPctAssisted'),
                   g(r, 'PtsUnassisted2s') / max(g(r, 'Points'), 1), g(r, 'PtsUnassisted3s') / max(g(r, 'Points'), 1)]
    out['fouls'] = [36 * g(r, 'FoulsDrawn') / m, g(r, 'ShootingFoulsDrawnPct'), 36 * g(r, 'FTA') / m,
                    g(r, 'FTA') / fga]
    out['shotq'] = [g(r, 'ShotQualityAvg'), g(r, 'TsPct') - 0.0, g(r, 'EfgPct')]
    out['onoff'] = [g(r, 'OnOffRtg') * m / (m + 800), g(r, 'OnDefRtg') * m / (m + 800)]
    out['usage'] = [g(r, 'Usage'), 36 * g(r, 'Turnovers') / m]
    out['reb'] = [g(r, 'OffFGReboundPct'), g(r, 'DefFGReboundPct'), g(r, 'DefAtRimReboundPct'), g(r, 'OffAtRimReboundPct')]
    out['stocks'] = [36 * g(r, 'Steals') / m, 36 * g(r, 'Blocks') / m]
    return out


BLOCKS = ['zone', 'zacc', 'asst', 'fouls', 'shotq', 'onoff', 'usage', 'reb', 'stocks']
rows = []   # one per (player, season s -> s+1)
first = {}
for (y, e), r in sorted(P.items()):
    first.setdefault(e, y)
for (y, e), r in sorted(P.items()):
    n = P.get((y + 1, e))
    if not n or g(r, 'Minutes') < 500 or g(n, 'Minutes') < 500:
        continue
    pr = P.get((y - 1, e))
    xp = XP.get((y, names.key(r['Name'])))
    age = xp['age'] if xp else None
    if age is None:
        continue
    rows.append({'y': y + 1, 'e': e, 'age': age, 'min': g(r, 'Minutes'), 'w': g(n, 'Minutes'),
                 'cur': {k: per36(r, v) for k, v in STATS.items()},
                 'prev': {k: (per36(pr, v) if pr and g(pr, 'Minutes') >= 300 else None) for k, v in STATS.items()},
                 'tgt': {k: per36(n, v) for k, v in STATS.items()}, 'f': feats(r), 'yrs': y - first[e]})
print('pairs', len(rows), 'target seasons', min(r['y'] for r in rows), max(r['y'] for r in rows))


def design(rs, st, blocks, mu=None):
    X = []
    for r in rs:
        c = r['cur'][st]
        pv = r['prev'][st]
        a = (r['age'] - 26) / 4
        x = [1.0, c, (pv if pv is not None else c) * 1.0, 0.0 if pv is not None else 1.0, a, a * a, r['min'] / 2000, min(r['yrs'], 6) / 3]
        for b in blocks:
            x += r['f'][b]
        X.append(x)
    return np.array(X)


def run(st, blocks, ridge=3.0):
    errs = {}
    for ty in range(2008, 2027):
        tr = [r for r in rows if r['y'] < ty]
        te = [r for r in rows if r['y'] == ty]
        if len(tr) < 600 or not te:
            continue
        Xtr = design(tr, st, blocks)
        mu, sd = Xtr.mean(0), Xtr.std(0)
        sd[sd == 0] = 1; mu[0] = 0; sd[0] = 1
        # the baseline's first 8 columns are unpenalised in scale; ridge only on candidate columns
        f = lambda X: (X - mu) / sd
        A = f(Xtr)
        w = np.array([r['w'] for r in tr]); y = np.array([r['tgt'][st] for r in tr])
        pen = np.diag([0.0] * 8 + [ridge * len(tr) / 100] * (A.shape[1] - 8))
        W = np.diag(w / w.mean()) if False else None
        Aw = A * (w / w.mean())[:, None]
        c = np.linalg.solve(A.T @ Aw + pen, Aw.T @ y)
        pt = f(design(te, st, blocks)) @ c
        yt = np.array([r['tgt'][st] for r in te]); wt = np.array([r['w'] for r in te])
        errs[ty] = (np.abs(yt - pt), wt)
    return errs


def wmae(e, ys):
    a = np.concatenate([e[y][0] * e[y][1] for y in ys if y in e]); w = np.concatenate([e[y][1] for y in ys if y in e])
    return a.sum() / w.sum()


def tstat(e0, e1, ys):
    d = np.concatenate([(e1[y][0] - e0[y][0]) * e1[y][1] for y in ys if y in e0]) / np.mean(np.concatenate([e0[y][1] for y in ys if y in e0]))
    return float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))


TUNE, HELD = range(2014, 2021), range(2021, 2027)
if '--b' not in sys.argv:
    for st in STATS:
        base = run(st, [])
        print('\n== %s next-season per-36: base wMAE tune %.3f held %.3f' % (st, wmae(base, TUNE), wmae(base, HELD)))
        combos = [[b] for b in BLOCKS] + [['asst', 'zone'], ['fouls', 'asst', 'zone', 'shotq'], BLOCKS]
        for bl in combos:
            e = run(st, bl)
            ds = [wmae(e, [y]) - wmae(base, [y]) for y in range(2014, 2027)]
            print('%-34s tune %+.4f t%+5.1f | held %+.4f t%+5.1f | folds better %d/13 | %s' % (
                '+'.join(bl) if len(bl) < 5 else 'ALL', wmae(e, TUNE) - wmae(base, TUNE), tstat(base, e, TUNE),
                wmae(e, HELD) - wmae(base, HELD), tstat(base, e, HELD), sum(d < 0 for d in ds), ' '.join('%+.3f' % d for d in ds)))
else:
    # (b) XPM sanity: season-level correlations of XPM / BPM / DPM with pbpstats on/off and shot-quality fields
    for fld in ['OnOffRtg', 'OnDefRtg', 'ShotQualityAvg', 'Usage', 'TsPct']:
        rs = []
        for (y, e), r in P.items():
            xp = XP.get((y, names.key(r['Name'])))
            if xp and g(r, 'Minutes') >= 1000:
                rs.append((xp['xpm'], xp['bpm'], xp['dpm'] if xp.get('dpm') is not None else np.nan, g(r, fld), y))
        a = np.array(rs, float)
        ok = ~np.isnan(a).any(1)
        print('%-15s n %d  r(xpm)=%.2f r(bpm)=%.2f r(dpm)=%.2f' % (fld, ok.sum(), np.corrcoef(a[ok, 0], a[ok, 3])[0, 1], np.corrcoef(a[ok, 1], a[ok, 3])[0, 1], np.corrcoef(a[ok, 2], a[ok, 3])[0, 1]))
    # does pbpstats on/off add to XPM in predicting next season's XPM (min 1000 both seasons, walk-forward, mp-weighted)?
    R = []
    for (y, e), r in P.items():
        n = P.get((y + 1, e))
        a, b = XP.get((y, names.key(r['Name']))), (XP.get((y + 1, names.key(n['Name']))) if n else None)
        if a and b and a['mp'] >= 1000 and b['mp'] >= 1000 and g(r, 'Minutes') >= 1000:
            m = g(r, 'Minutes')
            R.append((y + 1, a['xpm'], g(r, 'OnOffRtg') * m / (m + 800), g(r, 'OnDefRtg') * m / (m + 800), (a['age'] - 26) / 4, b['xpm'], b['mp']))
    R = np.array(R, float)
    for name, cols in [('xpm+age', [1, 4]), ('+onoff', [1, 4, 2]), ('+onoff+ondef', [1, 4, 2, 3])]:
        errs = {}
        for ty in range(2014, 2027):
            tr, te = R[R[:, 0] < ty], R[R[:, 0] == ty]
            if len(tr) < 300 or len(te) == 0:
                continue
            A = np.c_[np.ones(len(tr)), tr[:, cols]]
            c = np.linalg.lstsq(A, tr[:, 5], rcond=None)[0]
            errs[ty] = np.abs(te[:, 5] - np.c_[np.ones(len(te)), te[:, cols]] @ c)
        if name == 'xpm+age':
            base = errs
        d = lambda ys: np.concatenate([errs[y] - base[y] for y in ys if y in errs])
        tune, held = d(range(2014, 2021)), d(range(2021, 2027))
        print('XPM next-season %-14s MAE tune %.3f held %.3f | d tune %+.4f held %+.4f (t %+.1f)' % (
            name, np.concatenate([errs[y] for y in range(2014, 2021)]).mean(), np.concatenate([errs[y] for y in range(2021, 2027)]).mean(),
            tune.mean(), held.mean(), held.mean() / (held.std(ddof=1) / math.sqrt(len(held))) if len(held) > 2 and held.std() > 0 else 0))
