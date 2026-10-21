#!/usr/bin/env python3
"""Research: player priors for the NBA game model, player level (the game-level test is in nba_roster_research.py).

    python3 scripts/nba_prior_research.py     # writes data/nba_prior_research.json (numpy)

1. Rookies. The model now values last summer's draftees at their slot's rookie XPM and minutes (a + b ln(pick)). Do
   college numbers add to the slot? Candidates, all known on draft night: the college basketball board's preseason
   grade for the draft season (fvx, its expected FV; boards before 2017 graded out of fold), its P(NBA), the final
   college season's Barttorvik BPM and minutes share, career minutes-weighted BPM, height, power conference, age,
   international (no college line). Walk-forward by rookie season, fit only on earlier rookie classes.
   python3 scripts/nba_prior_research.py --write-college   # scripts/nba_rookie_college.json from the CBB kit
2. Aging. A veteran's prior is his last two seasons' XPM, minutes-weighted and shrunk; it has no age term. Delta
   method on players who logged minutes in back-to-back seasons (weight = harmonic mean of the two minutes): the
   change in XPM by age, fit only on earlier season pairs, added to the prior. Scored on next-season XPM, weighted
   by next-season minutes.
Kept by the fit's rule: paired t <= -1.5 on 2015-21 and 2022-26 no worse.
"""
import csv
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nba_games as N

OUT = os.path.join(N.ROOT, 'data', 'nba_prior_research.json')
KIT = os.environ.get('CBB_KIT', '/mnt/project-files/cbb/kit')
POWER = {'ACC', 'B10', 'B12', 'SEC', 'BE', 'P12'}


def xfile(S):
    fn = os.path.join(N.XPM, f'{S}.json')
    return {p['id']: p for p in json.load(open(fn))['players'] if p.get('xpm') is not None} if os.path.exists(fn) else {}


def college():
    """bbref id -> {'last': final college season row, 'seasons': [...]}"""
    out = defaultdict(list)
    with open(f'{KIT}/college_seasons_nba.csv', newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            if r['nba_bref'] and r['nba_draft']:
                out[r['nba_bref']].append(r)
    return out


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def board():
    p = json.load(open(os.path.join(N.ROOT, 'static', 'data', 'cbb-past.json')))
    c = p['cols']
    out = {}
    for r in p['rows']:
        d = dict(zip(c, r))
        out[(N.norm(d['name']), d['season'])] = d
    return out


def paired_t(e, e0):
    d = e - e0
    return float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))) if len(d) > 2 and d.std() > 0 else 0.0


def wls(X, y, w, lam=1e-6):
    A = X.T @ (X * w[:, None]) + lam * np.eye(X.shape[1])
    return np.linalg.solve(A, X.T @ (w * y))


# ---------------------------------------------------------------- rookies
def rookie_rows():
    col, brd = college(), board()
    rows = []
    for d, picks in N.draft().items():
        S = d + 1
        xf = xfile(S)
        if not xf:
            continue
        for pk, bid, nm, _ in picks:
            p = xf.get(bid)
            if not p or not p.get('g'):
                continue
            cs = sorted((r for r in col.get(bid, []) if int(r['year']) <= d), key=lambda r: int(r['year']))
            last = cs[-1] if cs else None
            mins = [(num(r['bpm']), num(r['min_per']) * num(r['gp']) if num(r['min_per']) and num(r['gp']) else 0) for r in cs]
            mins = [(b, m) for b, m in mins if b is not None and m]
            b3 = sum(b * m for b, m in mins) / sum(m for _, m in mins) if mins else None
            bd = brd.get((N.norm(nm), d)) if last else None
            rows.append({'S': S, 'pk': pk, 'id': bid, 'n': nm, 'xpm': p['xpm'], 'mp': p['mp'], 'mpg': p['mp'] / p['g'],
                         'age': p.get('age'), 'intl': 0 if last else 1,
                         'cbpm': num(last['bpm']) if last else None, 'cmin': num(last['min_per']) if last else None,
                         'cbpm3': b3, 'ht': num(last['hti']) if last else None,
                         'power': 1 if last and last['conf'] in POWER else 0,
                         'fvx': bd['fvx'] if bd else None, 'nbaP': bd['nbaP'] if bd else None})
    return rows


def rfeats(rows):
    """candidate columns; a missing college value sits at the training mean (0 after centring) with its flag"""
    def col(k, fill):
        v = np.array([r[k] if r[k] is not None else np.nan for r in rows], float)
        return np.where(np.isnan(v), fill, v), np.isnan(v).astype(float)
    X = {'lp': np.log([r['pk'] for r in rows])}
    X['intl'] = np.array([r['intl'] for r in rows], float)
    X['age'], _ = col('age', 21.0)
    X['power'] = np.array([r['power'] for r in rows], float)
    for k, fill in (('cbpm', 5.0), ('cmin', 60.0), ('cbpm3', 4.0), ('ht', 79.0)):
        X[k], _ = col(k, fill)
        X[k] = X[k] * (1 - X['intl'])          # college values only for college players
    X['fvx'], miss = col('fvx', 28.0)          # off the board (top 300) or international: the board's floor
    X['nofv'] = miss * (1 - X['intl'])
    X['nbaP'], _ = col('nbaP', 0.0)
    return X


def wf_rookie(rows, X, feats, target):
    S = np.array([r['S'] for r in rows])
    y = np.array([r[target] for r in rows], float)
    w = np.array([r['mp'] for r in rows], float) if target == 'xpm' else np.ones(len(rows))
    M = np.column_stack([np.ones(len(rows))] + [X[f] for f in feats])
    pr = np.full(len(rows), np.nan)
    for s in sorted(set(S)):
        tr, te = S < s, S == s
        if tr.sum() < 60:
            continue
        b = wls(M[tr], y[tr], w[tr])
        pr[te] = M[te] @ b
    return pr, y, w, S


def score_rookie(rows, X, feats, target, ref=None):
    pr, y, w, S = wf_rookie(rows, X, feats, target)
    out = {'feats': feats}
    for nm, k in (('2015_21', (S >= 2015) & (S < 2022)), ('2022_26', S >= 2022)):
        k = k & ~np.isnan(pr)
        e = w[k] * (pr[k] - y[k]) ** 2 / w[k].mean()
        out[nm] = {'n': int(k.sum()), 'rmse': round(float(math.sqrt(e.mean())), 3)}
        if ref is not None:
            e0 = w[k] * (ref[k] - y[k]) ** 2 / w[k].mean()
            out[nm]['d'] = round(float(math.sqrt(e.mean()) - math.sqrt(e0.mean())), 3)
            out[nm]['t'] = round(paired_t(e, e0), 2)
    return out, pr


def rookies():
    rows = rookie_rows()
    X = rfeats(rows)
    cands = ['fvx', 'nofv', 'nbaP', 'cbpm', 'cbpm3', 'cmin', 'age', 'intl', 'power', 'ht']
    res = {'n': len(rows)}
    for target in ('xpm', 'mpg'):
        base = ['lp']
        b0, ref = score_rookie(rows, X, base, target)
        steps = [b0]
        while True:
            best = None
            for c in cands:
                if c in base:
                    continue
                s, pr = score_rookie(rows, X, base + [c], target, ref)
                if s['2015_21']['t'] <= -1.5 and s['2022_26']['d'] <= 0 and (best is None or s['2015_21']['t'] < best[0]['2015_21']['t']):
                    best = (s, pr, c)
            if not best:
                break
            base.append(best[2]); ref = best[1]; steps.append({**best[0], 'added': best[2]})
        final, _ = score_rookie(rows, X, base, target, score_rookie(rows, X, ['lp'], target)[1])
        allf = {c: score_rookie(rows, X, ['lp', c], target, score_rookie(rows, X, ['lp'], target)[1])[0] for c in cands}
        res[target] = {'kept': base, 'steps': steps, 'vsSlot': final, 'single': allf}
        print(target, 'kept', base, json.dumps(final))
        for c, s in allf.items():
            print('  ', c, s['2015_21'], s['2022_26'])
    # the shipped form: college draftees on their own fit (slot + final college BPM), everyone else on the slot curve,
    # so a draftee with no college line never reads as a zero BPM
    pr0, y, w, S = wf_rookie(rows, X, ['lp'], 'xpm')
    col = np.array([1 - r['intl'] for r in rows], bool)
    sub = [r for r in rows if not r['intl']]
    p2, _, _, _ = wf_rookie(sub, rfeats(sub), ['lp', 'cbpm'], 'xpm')
    pr = pr0.copy(); pr[col] = p2
    out = {}
    for nm, k in (('2015_21', (S >= 2015) & (S < 2022)), ('2022_26', S >= 2022)):
        k = k & ~np.isnan(pr) & ~np.isnan(pr0)
        e, e0 = w[k] * (pr[k] - y[k]) ** 2 / w[k].mean(), w[k] * (pr0[k] - y[k]) ** 2 / w[k].mean()
        out[nm] = {'n': int(k.sum()), 'rmse': round(math.sqrt(e.mean()), 3), 'rmseSlot': round(math.sqrt(e0.mean()), 3), 't': round(paired_t(e, e0), 2)}
    res['shipped'] = out
    print('shipped (college fit + slot fallback)', out)
    return res


def write_college():
    """scripts/nba_rookie_college.json: each drafted college player's final college season Barttorvik BPM (the
    season ending in his draft year or before), by Basketball-Reference id"""
    out = {}
    for bid, rs in college().items():
        d = int(float(rs[0]['nba_draft']))
        cs = sorted((r for r in rs if int(r['year']) <= d and num(r['bpm']) is not None), key=lambda r: int(r['year']))
        if cs:
            out[bid] = round(num(cs[-1]['bpm']), 2)
    with open(N.ROOKIE_COLLEGE, 'w') as f:
        json.dump(out, f, separators=(',', ':'), sort_keys=True)
    print('college BPM for', len(out), 'draftees')


# ---------------------------------------------------------------- aging
def aging():
    F = json.load(open(N.FIT))['params']
    n0, rook = F.get('n0', 600.0), F.get('rook', -1.0)
    X = {S: xfile(S) for S in range(2010, 2027)}
    pairs = []          # (S, age in S, delta xpm, weight)
    for S in range(2011, 2027):
        for pid, b in X[S].items():
            a = X[S - 1].get(pid)
            if a and a.get('age') and a['mp'] > 0 and b['mp'] > 0:
                pairs.append((S, a['age'] + 1, b['xpm'] - a['xpm'], 2 / (1 / a['mp'] + 1 / b['mp'])))
    pairs = np.array(pairs, float)

    def curve(S):
        """mean XPM change by age (S-1 age +1), harmonic-minutes weighted, pairs ending before S; ages <=20 and >=36
        pooled, each age shrunk to a quadratic fit of the curve"""
        k = pairs[:, 0] < S
        a, d, w = np.clip(pairs[k, 1], 20, 36), pairs[k, 2], pairs[k, 3]
        M = np.column_stack([np.ones(k.sum()), a - 27, (a - 27) ** 2])
        b = wls(M, d, w)
        return lambda age: float(b[0] + b[1] * (min(max(age, 20), 36) - 27) + b[2] * (min(max(age, 20), 36) - 27) ** 2), b
    rows = []
    for S in range(2012, 2027):
        cv, b = curve(S)
        for pid, p in X[S].items():
            a1, a2 = X[S - 1].get(pid), X[S - 2].get(pid)
            if not a1 or not a1.get('age'):
                continue
            num, den = rook * n0, n0
            num += a1['xpm'] * a1['mp']; den += a1['mp']
            if a2:
                num += a2['xpm'] * a2['mp'] * 0.5; den += a2['mp'] * 0.5
            rows.append((S, p['xpm'], p['mp'], num / den, cv(a1['age'] + 1), a1['age'] + 1, a1['mp']))
    R = np.array(rows, float)
    S, y, w, v, dage, age, mp1 = R.T
    res = {'curve2026': [round(x, 3) for x in curve(2027)[1]],
           'byAge2026': {int(a): round(curve(2027)[0](a), 2) for a in range(20, 37, 2)}}
    print('aging curve (fit through 2026):', res['byAge2026'])
    # the delta adds to the shrunk prior in full (g=1) or scaled by the prior's own reliability (g=den share)
    rel = mp1 / (mp1 + n0)
    for lab, pr in (('none', v), ('full', v + dage), ('reliability', v + dage * rel)):
        e, e0a = w * (pr - y) ** 2 / w.mean(), w * (v - y) ** 2 / w.mean()
        r = {}
        for nm, k in (('2015_21', (S >= 2015) & (S < 2022)), ('2022_26', S >= 2022)):
            ek, e0 = e[k], e0a[k]
            r[nm] = {'n': int(k.sum()), 'rmse': round(float(math.sqrt(ek.mean())), 3),
                     'd': round(float(math.sqrt(ek.mean()) - math.sqrt(e0.mean())), 3), 't': round(paired_t(ek, e0), 2)}
        res[lab] = r
        print('aging', lab, r)
    return res


if __name__ == '__main__':
    if '--write-college' in sys.argv:
        sys.exit(write_college())
    out = {'rookies': rookies(), 'aging': aging()}
    with open(OUT, 'w') as f:
        json.dump(out, f, indent=1)
