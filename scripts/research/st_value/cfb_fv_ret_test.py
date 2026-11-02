"""Return production as a CFB FV driver (Nov 2 2026): does it explain NFL outcomes beyond the shipped FV?
    python3 scripts/research/st_value/cfb_fv_ret_test.py   (needs cfb_ret_hist.py's ret_yoe.json)
Rows: scripts/data/cfb_alltime_rows.json.gz, every FBS season 2014-25 at QB-LB graded under the shipped weights; the
player's final college season, drafts 2015-23 (undrafted = 0 AV). Outcome: NFL AV a season. Join: ESPN athlete id
(2014-18 rows carry it), else names.py Matcher on name + team (location name), cross-team none.
Candidates (career to date, every season through the graded one):
  krY / prY   kick / punt return yards over expected a return, shrunk (k = st_returners' KR 36 / PR 20)
  retY        both together, a team game (shrunk rates x his returns / games)
  retP        drive points over expected, both, a team game (shrunk)
  isRet       10+ returns in a season (role flag)
  retS        retY over the seasons he returned in (not every graded season: the 2019+ rows list only graded seasons,
              the 2014-18 ones read back to 2011, so retY's denominator differs by era; the live board knows the former)
  retT / retR career total (yards / 12), and the plain per-return rate (both, shrunk at 28)
  retC        retS clipped to [-2, 4]: SHIPPED for RB and WR (fetch_cfb.mjs, after the mean-outcome step)
Test: AV ~ isotonic(fvx) [+ b x on its residual], fit on 8 draft classes, scored on the 9th (and forward: earlier classes only); fold t on the squared-error gain, classes
improved, Spearman, and AV of each class's top 32 by the prediction. Pooled (QB-LB, x = 0 for non-returners) and RB/WR.
"""
import gzip
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, SCR)
import names as NM  # noqa: E402

ROOT = os.path.dirname(SCR)
RET = json.load(open(os.path.join(ROOT, 'scripts', '.cache', 'fvrefit', 'ret_yoe.json')))['rows']
TEAMS = os.path.join(ROOT, 'scripts', '.cache', 'cfb', 'espn_teams.json')
OUT = os.path.join(ROOT, 'data', 'cfb_fv_returns.json')   # results and the shipped term (fetch_cfb.mjs reads ship)
KK = {'kr': 36, 'pr': 20}
CLIP = [-2, 4]      # retS held to its 3rd-97th percentile band among returners (a few 8-12s are 2-3 return TDs on 20 returns)


def teams():
    if not os.path.exists(TEAMS):
        import urllib.request
        d = json.load(urllib.request.urlopen('https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams?limit=1000'))
        json.dump({t['team']['id']: t['team'].get('location') for t in d['sports'][0]['leagues'][0]['teams']}, open(TEAMS, 'w'))
    return json.load(open(TEAMS))


def main():
    loc = teams()
    by_s = defaultdict(list)
    for r in RET:
        r['team'] = loc.get(r['tid'], '')
        by_s[r['s']].append(r)
    M = {s: NM.Matcher(rs, name='name', team='team', pos=None) for s, rs in by_s.items()}
    by_aid = defaultdict(list)
    for r in RET:
        by_aid[(r['s'], r['aid'])].append(r)
    rows = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'data', 'cfb_alltime_rows.json.gz'), 'rt'))
    # every season row of a player, to build career-to-date lines
    hist = defaultdict(list)
    for r in rows:
        hist[r['id']].append(r)
    hit = tot = 0

    def ret_of(r):
        nonlocal hit, tot
        tot += 1
        if r['id'].startswith('espn-'):
            x = by_aid.get((r['s'], r['id'][5:]))
        else:
            m = M.get(r['s'])
            f, _ = m.find(r['name'], team=r['team'], cross_team='none') if m else (None, None)
            x = [f] if f else None
        if x:
            hit += 1
        return x or []
    final = [r for r in rows if r['final'] and r['last'] <= 2022 and (r['draft'] is None or r['draft'] <= 2023)]
    data = []
    for r in final:
        ss = sorted(hist[r['id']], key=lambda h: h['s'])
        # seasons before 2014 have no graded row: read the return lines by the same ESPN id / name back to 2011
        acc = {'kr': 0, 'kryoe': 0.0, 'krpoe': 0.0, 'pr': 0, 'pryoe': 0.0, 'prpoe': 0.0}
        seasons = 0; isret = 0; rs = set()
        for h in ss:
            got = ret_of(h)
            seasons += 1
            if got:
                rs.add(h['s'])
            n = 0
            for x in got:
                for k in acc:
                    acc[k] += x[k]
                n += x['kr'] + x['pr']
            isret = max(isret, int(n >= 10))
        if r['id'].startswith('espn-'):
            for s in range(2011, ss[0]['s']):
                for x in by_aid.get((s, r['id'][5:]), []):
                    rs.add(s)
                    for k in acc:
                        acc[k] += x[k]
                    seasons += 1
                    isret = max(isret, int(x['kr'] + x['pr'] >= 10))
        g = 12 * max(1, seasons)
        krY = acc['kryoe'] / (acc['kr'] + KK['kr'])
        prY = acc['pryoe'] / (acc['pr'] + KK['pr'])
        retY = (krY * acc['kr'] + prY * acc['pr']) / g
        retP = (acc['krpoe'] / (acc['kr'] + KK['kr']) * acc['kr'] + acc['prpoe'] / (acc['pr'] + KK['pr']) * acc['pr']) / g
        tot = krY * acc['kr'] + prY * acc['pr']
        retS = tot / (12 * max(1, len(rs)))
        data.append({'retS': retS, 'retT': tot / 12, 'retR': (acc['kryoe'] + acc['pryoe']) / (acc['kr'] + acc['pr'] + 28),'cls': r['draft'] or (r['last'] + 1), 'g': r['g'], 'fvx': r['fvx'], 'av': r['av'] or 0.0, 'name': r['name'],
                     'krY': krY, 'prY': prY, 'retY': retY, 'retP': retP, 'isRet': isret, 'nret': acc['kr'] + acc['pr']})
    print('final rows', len(data), 'season rows joined', hit, 'of', tot, '| returners (10+ in a season)', sum(d['isRet'] for d in data))
    return data


def pav(x, y):
    """isotonic (non-decreasing) fit of y on x: returns a step function"""
    o = np.argsort(x); xs, ys = x[o], y[o].astype(float)
    blocks = []                      # [sum, n, xmax]
    for xi, yi in zip(xs, ys):
        blocks.append([yi, 1, xi])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            a = blocks.pop(); blocks[-1][0] += a[0]; blocks[-1][1] += a[1]; blocks[-1][2] = a[2]
    xm = np.array([b[2] for b in blocks]); vm = np.array([b[0] / b[1] for b in blocks])
    return lambda z: vm[np.minimum(np.searchsorted(xm, z), len(vm) - 1)]


def avgrank(a):
    a = np.asarray(a, float); o = np.argsort(a, kind='mergesort'); r = np.empty(len(a)); sa = a[o]; i = 0
    while i < len(a):
        j = i
        while j + 1 < len(a) and sa[j + 1] == sa[i]:
            j += 1
        r[o[i:j + 1]] = (i + j) / 2; i = j + 1
    return r


def spear(a, b):
    return np.corrcoef(avgrank(a), avgrank(b))[0, 1]


def fitpred(D, cand, tr, te):
    """baseline: isotonic AV on fvx; candidate: + b x on the baseline's residual (fit on the training classes)"""
    f = np.array([d['fvx'] for d in D]); y = np.array([d['av'] for d in D])
    g = pav(f[tr], y[tr]); b0 = g(f)
    if not cand:
        return b0[te], 0.0
    x = np.array([d[cand] for d in D], float)
    xc = x - x[tr].mean()
    b = float(((y[tr] - b0[tr]) * xc[tr]).sum() / (xc[tr] ** 2).sum())
    return b0[te] + b * xc[te], b


def test(D, cand, label):
    y = np.array([d['av'] for d in D]); cls = np.array([d['cls'] for d in D])
    gains, top0, top1, imp, coefs, fwd = [], [], [], 0, [], []
    p0all, p1all = np.zeros(len(D)), np.zeros(len(D))
    C = sorted(set(cls))
    for c in C:
        tr, te = cls != c, cls == c
        p0, _ = fitpred(D, None, tr, te); p1, b = fitpred(D, cand, tr, te)
        coefs.append(b); p0all[te], p1all[te] = p0, p1
        g = ((y[te] - p0) ** 2).mean() - ((y[te] - p1) ** 2).mean()
        gains.append(g); imp += g > 0
        k = min(32, int(te.sum()))
        top0.append(y[te][np.argsort(-p0, kind='mergesort')[:k]].mean()); top1.append(y[te][np.argsort(-p1, kind='mergesort')[:k]].mean())
        if c >= C[3]:                    # forward: fit on the classes before c only
            trf = cls < c
            q0, _ = fitpred(D, None, trf, te); q1, _ = fitpred(D, cand, trf, te)
            fwd.append(((y[te] - q0) ** 2).mean() - ((y[te] - q1) ** 2).mean())
    g = np.array(gains); t = g.mean() / (g.std(ddof=1) / math.sqrt(len(g))) if g.std() > 0 else 0
    dt = np.array(top1) - np.array(top0)
    fw = np.array(fwd)
    o = {'cand': cand, 'set': label, 'n': len(D), 'folds': len(g), 'gainT': round(float(t), 2), 'better': int(imp),
         'coef': round(float(np.mean(coefs)), 3), 'spearman': [round(float(spear(p0all, y)), 4), round(float(spear(p1all, y)), 4)],
         'top32': [round(float(np.mean(top0)), 3), round(float(np.mean(top1)), 3)], 'top32Better': int((dt > 0).sum()),
         'top32Worse': int((dt < 0).sum()), 'fwdGain': round(float(fw.mean()), 4), 'fwdBetter': f'{int((fw > 0).sum())}/{len(fw)}'}
    print(o)
    return o


if __name__ == '__main__':
    D = main()
    for d in D:
        d['retC'] = min(CLIP[1], max(CLIP[0], d['retS']))
    res = []
    for cand in ('krY', 'prY', 'retY', 'retS', 'retT', 'retR', 'retP', 'isRet', 'retC'):
        res.append(test(D, cand, 'QB-LB'))
        res.append(test([d for d in D if d['g'] in ('RB', 'WR')], cand, 'RB+WR'))
        res.append(test([d for d in D if d['g'] == 'WR'], cand, 'WR'))
        res.append(test([d for d in D if d['g'] == 'RB'], cand, 'RB'))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    # shipped: retC (retY clipped) on RB and WR, as AV a season on top of the board's mean outcome; beta on all classes
    RW = [d for d in D if d['g'] in ('RB', 'WR')]
    y = np.array([d['av'] for d in RW]); f = np.array([d['fvx'] for d in RW]); x = np.array([d['retC'] for d in RW])
    beta = float(((y - pav(f, y)(f)) * x).sum() / (x ** 2).sum())
    print('shipped beta', round(beta, 3))
    # realized AV a season by FV (RB and WR, window means made monotone) at 20-30: the live board measures the FV a gain
    # of beta x buys on this curve, then the board's own map past 30. The map's floor (0 AV at 20, .4 at 30) runs below
    # what RB/WR at 20-30 realized, and its flat slope there would double the lift of a fringe returner
    knots, last = [], 0.0
    for k in (20, 22, 25, 30):     # above 30 the board's own map (cfb_teams.mjs AV_BY_FV) carries on from here
        w = max(1.0, k / 10)                      # window +-2 FV at the floor, wider up the scale where rows thin out
        m = (f >= k - w) & (f < k + w)
        last = max(last, float(y[m].mean())) if m.sum() >= 15 else last
        knots.append([k, round(last, 3)])
    print('realized AV by FV', knots)
    json.dump({'method': __doc__.strip(), 'results': res,
               'ship': {'pos': ['RB', 'WR'], 'term': 'retC', 'clip': CLIP, 'beta': round(beta, 3), 'k': KK, 'gamesPerSeason': 12, 'avReal': knots}},
              open(OUT, 'w'), indent=1)
