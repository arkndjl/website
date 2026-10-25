#!/usr/bin/env python3
"""Stay-or-declare for college basketball (audit #31): who on the mock's pool actually leaves school after this season.

    python3 scripts/cbb_declare.py     # -> data/cbb_declare_fit.json (read by scripts/cbb_mock.py live_pool)

Rows: every Barttorvik D-I season 2010-26 (research kit /mnt/project-files/cbb/kit/college_seasons_nba.csv) by a
freshman, sophomore or junior who is a prospect by what was known that June: 30%+ of the minutes and a BPM of 3+, or
a top-60 recruit. Outcome: he left college basketball, no later Barttorvik season under the same id (ids follow
transfers); the 2025 and 2026 seasons also check today's roster (static/data/cbb-all.json, through scripts/names.py).
Seniors are out of eligibility and leave (the COVID year ran out with the 2024-25 season), as the mock already has it.
Terms, each a candidate on top of the base (class and era):
  bpm      the season's BPM, shrunk toward 0 by minutes share (bpm x min/(min+20))
  rank     recruiting rank, -ln(min(rank, 300)) (On3 / 247, whichever is better)
  age      age on draft night (June 25)
  ht       height in inches
  era      nil (2022+ seasons, the transfer portal and NIL era); covid (the 2021 season: the free year kept people in)
  nil x    the era terms crossed with bpm and rank (NIL money keeps the fringe prospect, not the lottery pick)
Stage A test: walk forward over the held-out seasons 2023-26 (each scored by a fit on the seasons before it, so the
NIL era is learned from 2022 on), per row log loss against the base, t on the paired difference, seasons won.
Forward selection keeps a term only when it improves the held-out loss (t -1 or better) in 3+ of the 4 seasons.
Stage B, the board: No Ceilings' midseason board (its last before March 1, 2022-26 drafts; /mnt/project-files/cbb/
boards/all_boards.csv), -ln rank, unranked at 100, on top of stage A's logit; leave one draft out over the NIL-era
drafts it covers, gated the same way. The mock's pool is board-listed players, so this is the one the mock reads
when it passes; stage A covers the rest.
"""
import csv, json, math, os, sys
from collections import defaultdict
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import names as N

KIT = os.environ.get('CBB_KIT', '/mnt/project-files/cbb/kit')
OUT = os.path.join(ROOT, 'data', 'cbb_declare_fit.json')
CLS = ('Fr', 'So', 'Jr')
TERMS = ['bpm', 'rank', 'age', 'ht']
HOLD = (2023, 2024, 2025, 2026)
BOARDS = os.environ.get('CBB_BOARDS', '/mnt/project-files/cbb/boards')
BOARD_DEPTH = 100


def num(x):
    try: return float(x)
    except (TypeError, ValueError): return None


def age_on(dob, year):
    try:
        y, m, d = map(int, dob.split('-'))
    except (AttributeError, ValueError): return None
    return year - y + (6 - m) / 12 + (25 - d) / 365.25


def feats(bpm, mins, rank, age, ht):
    """the same transform live (cbb_mock.py) and here"""
    return {'bpm': (max(-8.0, min(15.0, bpm)) * mins / (mins + 20)) if bpm is not None and mins is not None else 0.0,
            'rank': -math.log(min(rank, 300)) if rank else -math.log(300), 'age': age, 'ht': ht}


def logit(X, y, l2=1.0):
    b = np.zeros(X.shape[1]); pen = np.full(X.shape[1], l2); pen[0] = 0
    for _ in range(100):
        p = 1 / (1 + np.exp(-X @ b))
        H = (X * (p * (1 - p))[:, None]).T @ X + np.diag(pen)
        s = np.linalg.solve(H, X.T @ (y - p) - pen * b); b += s
        if np.abs(s).max() < 1e-8: break
    return b


def board_ranks(seas):
    """(pid, year) -> No Ceilings midseason rank, matched to that season's Barttorvik rows by name and school"""
    B = defaultdict(list)
    with open(os.path.join(BOARDS, 'all_boards.csv'), newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            if r['source'] != 'noceilings': continue
            name, school = r['name'], r['school']
            if not school and name.count(',') >= 2: name, _, school = [x.strip() for x in name.split(',', 2)]
            B[int(r['draft_year'])].append((r['board_date'], int(r['rank']), name, school))
    out = {}
    for y, rs in B.items():
        mid = [d for d, *_ in rs if d <= f'{y}-02-28']
        if not mid: continue
        d = max(mid)
        M = N.Matcher([{'name': s[y]['name'], 'team': s[y]['team'], 'pid': pid} for pid, s in seas.items() if y in s])
        for dd, rk, name, school in rs:
            if dd != d: continue
            h = M.find(name, team=school)[0]
            if h: out[(h['pid'], y)] = rk
    return out


def rows_from_kit():
    seas = defaultdict(dict)
    with open(os.path.join(KIT, 'college_seasons_nba.csv'), newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f): seas[r['pid']][int(r['year'])] = r
    cur = json.load(open(os.path.join(ROOT, 'static', 'data', 'cbb-all.json')))
    ci = {k: i for i, k in enumerate(cur['cols'])}
    roster = N.Matcher([{'name': r[ci['name']], 'team': r[ci['team']]} for r in cur['rows']])
    brd = board_ranks(seas)
    out = []
    for pid, by in seas.items():
        for y, r in by.items():
            if y < 2010 or r['yr'] not in CLS: continue
            mins, bpm = num(r['min_per']), num(r['bpm'])
            rk = [x for x in (num(r['on3rk']), num(r['rk247'])) if x]
            rank = min(rk) if rk else None
            b = brd.get((pid, y))
            if not ((mins or 0) >= 30 and (bpm or -99) >= 3) and not (rank and rank <= 60) and b is None: continue
            later = any(yy > y for yy in by)
            if not later and y >= 2025:   # 2026-27 roster: back at the same school or anywhere (unique name)
                later = roster.find(r['name'], team=r['team'])[0] is not None
            a = age_on(r['dob'], y)
            out.append({'pid': pid, 'name': r['name'], 'year': y, 'cls': r['yr'], 'left': int(not later), 'nb': b,
                        'drafted': int(num(r['nba_draft']) == y), **feats(bpm, mins, rank, a, num(r['hti']))})
    # missing age / height: the class mean
    for k in ('age', 'ht'):
        for c in CLS:
            v = [r[k] for r in out if r['cls'] == c and r[k] is not None]; m = float(np.mean(v))
            for r in out:
                if r['cls'] == c and r[k] is None: r[k] = m
    for r in out: r['board'] = -math.log(min(r['nb'], BOARD_DEPTH)) if r['nb'] else -math.log(BOARD_DEPTH)
    return out


def design(rows, terms, mu, sd):
    def x(r, k):
        if k.startswith('nil_'): return (r['year'] >= 2022) * (r[k[4:]] - mu[k[4:]]) / sd[k[4:]]
        return (r[k] - mu[k]) / sd[k]
    return np.array([[1, r['cls'] == 'So', r['cls'] == 'Jr', r['year'] >= 2022, r['year'] == 2021] + [x(r, k) for k in terms] for r in rows], float)


def ll(p, y):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def main():
    rows = sorted(rows_from_kit(), key=lambda r: r['year'])   # season order: walk() returns rows season by season
    mu = {k: float(np.mean([r[k] for r in rows])) for k in TERMS}; sd = {k: float(np.std([r[k] for r in rows])) for k in TERMS}
    te = [r for r in rows if r['year'] in HOLD]; yte = np.array([r['left'] for r in te], float)
    yrs = np.array([r['year'] for r in te])

    def walk(terms, years=HOLD, pool=rows):
        """walk forward: each season scored by a fit on the seasons before it -> (p, z) in the order of pool rows in years"""
        P, Z = [], []
        for y in years:
            tr = [r for r in pool if r['year'] < y]; ts = [r for r in pool if r['year'] == y]
            b = logit(design(tr, terms, mu, sd), np.array([r['left'] for r in tr], float))
            z = design(ts, terms, mu, sd) @ b; Z += list(z); P += list(1 / (1 + np.exp(-z)))
        return np.array(P), np.array(Z)

    def cmp(L, Lref, yy=yrs, years=HOLD):
        d = L - Lref
        return {'logLoss': round(float(L.mean()), 4), 'vsRef': round(float(d.mean()), 4), 't': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2),
                'seasonsWon': int(sum(d[yy == y].mean() < 0 for y in years)), 'of': len(years)}
    p0, _ = walk([]); L0 = ll(p0, yte)
    CANDS = TERMS + ['nil_bpm', 'nil_rank']
    steps, kept, Lcur = [], [], L0
    while True:
        best = None
        for k in CANDS:
            if k in kept or (k.startswith('nil_') and k[4:] not in kept): continue
            L = ll(walk(kept + [k])[0], yte); c = cmp(L, Lcur)
            if c['vsRef'] < 0 and c['t'] <= -1 and c['seasonsWon'] >= 3 and (best is None or c['vsRef'] < best[1]['vsRef']): best = (k, c, L)
        if not best: break
        kept.append(best[0]); Lcur = best[2]; steps.append({'add': best[0], **best[1]})
        print('add', best[0], best[1])
    singles = {k: cmp(ll(walk([k])[0], yte), L0) for k in TERMS}
    p, _ = walk(kept); L = ll(p, yte)
    final = cmp(L, L0)
    e = [0, .2, .4, .6, .8, 1.01]
    def calib(p, y):
        return [{'pred': f'{a:.1f}-{c:.1f}', 'n': int(((p >= a) & (p < c)).sum()), 'mean': round(float(p[(p >= a) & (p < c)].mean()), 3),
                 'actual': round(float(y[(p >= a) & (p < c)].mean()), 3)} for a, c in zip(e, e[1:]) if ((p >= a) & (p < c)).sum()]
    dr = np.array([r['drafted'] for r in te], bool)

    # stage B: the midseason board on top of stage A, leave one draft out over the board's drafts
    BY = sorted({r['year'] for r in rows if r['nb']})
    sub = [r for r in rows if r['year'] in BY]
    _, zA = walk(kept, BY)
    ysub = np.array([r['left'] for r in sub], float); ysy = np.array([r['year'] for r in sub])
    LA = ll(1 / (1 + np.exp(-zA)), ysub)
    XB = np.column_stack([np.ones(len(sub)), zA, [r['board'] for r in sub], [r['nb'] is not None for r in sub]])
    pB = np.zeros(len(sub))
    for y in BY:
        m = ysy == y
        bB = logit(XB[~m], ysub[~m], l2=0.1); pB[m] = 1 / (1 + np.exp(-XB[m] @ bB))
    LB = ll(pB, ysub)
    stageB = {'drafts': BY, 'n': len(sub), 'ranked': int(sum(r['nb'] is not None for r in sub)), 'A': round(float(LA.mean()), 4), **cmp(LB, LA, ysy, BY)}
    rk = np.array([r['nb'] is not None for r in sub])
    stageB['rankedOnly'] = {'n': int(rk.sum()), 'stay': round(1 - float(ysub[rk].mean()), 3), 'A': round(float(LA[rk].mean()), 4), 'B': round(float(LB[rk].mean()), 4),
                            'calibB': calib(pB[rk], ysub[rk]), 'calibA': calib(1 / (1 + np.exp(-zA[rk])), ysub[rk])}
    print('stage B', json.dumps(stageB))
    bB_all = logit(XB, ysub, l2=0.1)

    # shipped fits use every season (2010-26), same terms
    b_all = logit(design(rows, kept, mu, sd), np.array([r['left'] for r in rows], float))
    out = {'_readme': __doc__.split('\n\n')[1].strip(), 'n': len(rows), 'nHeld': len(te),
           'leftRate': {str(y): round(float(np.mean([r['left'] for r in rows if r['year'] == y])), 3) for y in range(2010, 2027)},
           'base': {'logLoss': round(float(L0.mean()), 4)}, 'singles': singles, 'steps': steps, 'kept': kept, 'held': final, 'calib': calib(p, yte),
           'drafted': {'n': int(dr.sum()), 'base': round(float(p0[dr].mean()), 3), 'model': round(float(p[dr].mean()), 3)},
           'returned': {'n': int((yte == 0).sum()), 'base': round(float(p0[yte == 0].mean()), 3), 'model': round(float(p[yte == 0].mean()), 3)},
           'stageB': stageB,
           'fit': {'cols': ['const', 'So', 'Jr', 'nil', 'covid'] + kept, 'b': [round(float(x), 4) for x in b_all],
                   'mu': {k: round(v, 4) for k, v in mu.items()}, 'sd': {k: round(v, 4) for k, v in sd.items()}},
           'board': {'cols': ['const', 'zA', 'board', 'ranked'], 'b': [round(float(x), 4) for x in bB_all], 'depth': BOARD_DEPTH,
                     'ship': bool(stageB['vsRef'] < 0 and stageB['seasonsWon'] >= 3 and stageB['t'] <= -2)}}
    print(json.dumps({k: out[k] for k in ('n', 'nHeld', 'base', 'singles', 'kept', 'held', 'calib', 'drafted', 'returned', 'fit', 'board', 'leftRate')}))
    json.dump(out, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
