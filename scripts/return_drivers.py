#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Return% (1 - the stay-or-declare odds) for draft-eligible college players, both sports: every driver either
sport's declare model uses, or could use, tried in both (cross-sport rule), with the NIL era split.

    python3 scripts/return_drivers.py      # needs cfb_draft_pct_backtest.py's cache and the CBB kit; -> data/return_drivers.json

Live models (unchanged unless a term here passes):
  CFB  DECLARE in scripts/cfb_teams.mjs: per class group (Sr. vs underclassmen), ln xPick and age on draft day
       (scripts/cfb_declare_econ.py). Rows: each draft's latest fall PFF board (2021-25 drafts), RS Sr. and grads out
       (they go). Test: leave one draft out, the 2024 NIL flag in every model, paired per-row log loss against the
       live model, 10 draft x class cells.
  CBB  scripts/cbb_declare.py: class, era (NIL 2022+, COVID 2021), recruiting rank and BPM shrunk by minutes
       (stage A, walk forward 2023-26), then the midseason No Ceilings board on top (stage B, leave one draft out
       2022-26).
Candidates (each tried alone on top of the live model; the analogue in the other sport in brackets):
  prod     production: PFF's season grade shrunk by snaps, (grade - 70) x snaps / (snaps + 250)   [CBB bpm]
  rec      recruiting rank, -ln(min(rank, 2500)) from the CFBD composite of his high school class [CBB rank]
  ht       height in inches, centred on his position                                       [CBB ht]
  covid    the 2021 draft (fall 2020 board: the free COVID year)                               [CBB covid]
  nil_*    the NIL-era flag (2024+ drafts) crossed with ln xPick, age                           [CBB nil_bpm, nil_rank]
  nil22    an earlier era step, the first NIL decisions (2022+ drafts)                         [CBB e24, 2024+ seasons]
  econ, qb, p4   as in cfb_declare_econ.py                                                       [CBB econ, guard, hm]
  CBB: age_c (age centred on class) [CFB age], hm (high-major conference) [CFB p4], nil_age_c, guard (6-4 and under,
       the ball-handler proxy) [CFB qb], econ (ln expected NBA rookie deal at the board slot - ln NIL by staying,
       today's xNIL shape on board rank and high-major) [CFB econ], in stage B; nil x board can't be tested (every
       board season is NIL era).
Gate, set before running: held-out paired t <= -2 and the term wins 7 of 10 CFB cells, 3 of 4 CBB stage A seasons,
4 of 5 stage B drafts. Baselines reported: the base rate, class only, class + position (CFB) and the live model.
"""
import importlib.util, csv, json, math, os, sys
from collections import defaultdict
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import names as N
import cbb_declare as CD


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, file))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


OUT = os.path.join(ROOT, 'data', 'return_drivers.json')
PRED = os.path.join(HERE, '.cache', 'return_preds.json')     # held-out per-row declare odds, read by return_news.py
PREDS = {'cfb': [], 'cbb': []}
GATE = {'t': -2.0, 'cfb': 7, 'cbbA': 3, 'cbbB': 4}


def ll(p, y):
    p = np.clip(p, 1e-4, 1 - 1e-4); return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def tstat(d): return float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))) if len(d) > 2 and d.std() > 0 else 0.0


def logit(X, y, l2=1.0):
    return CD.logit(np.asarray(X, float), np.asarray(y, float), l2)


# ---------------------------------------------------------------------------------------------------------- CFB
def cfb_rows():
    bt = load('bt', 'cfb_draft_pct_backtest.py'); CE = load('ce', 'cfb_declare_econ.py')
    rows, boards = bt.build_rows()
    latest = {}
    for r in rows:
        if 140 <= r['days'] <= 240 and (r['draft'] not in latest or r['days'] < latest[r['draft']]): latest[r['draft']] = r['days']
    # the board's own player records (grade, height, college) for the latest fall version
    rec_of = {}
    for y, v, date, players in boards:
        for p in players:
            if p.get('pff_rank'): rec_of[(y, date, p['name'])] = p
    fall = [r for r in rows if latest.get(r['draft']) == r['days'] and r['cls'] not in ('RS Sr.', 'G')]
    import gzip
    recs = json.load(gzip.open(os.path.join(HERE, 'data', 'cfb_recruits_cfbd.json.gz')))
    RI = defaultdict(list)
    for yr, L in recs.items():
        for x in L: RI[N.key(x[0])].append((int(yr), x[3], x[4]))
    for r in fall:
        p = rec_of.get((r['draft'], r['date'], r['name']), {})
        r['grp'] = 'sr' if r['cls'] == 'Sr.' else 'under'
        r['lx'] = bt.lnPick(r['rank']); r['qb'] = int(r['pos'] == 'QB')
        r['econ'] = CE.rookie(r['lx']) - CE.nil(r['lx'], r['qb'], r['p4'], r['fcs'])
        g = p.get('grade_1') or {}
        gv, gs = g.get('value') or 0, g.get('snaps') or 0
        r['prod'] = (gv - 70) * gs / (gs + 250) if gv else 0.0
        try:
            ft, inch = p.get('height', '').replace('"', '').split("'"); r['hti'] = int(ft) * 12 + int(inch)
        except (ValueError, AttributeError): r['hti'] = None
        # recruit: same key, high school class 2 to 6 years before the draft; the college breaks a tie
        c = [x for x in RI.get(N.key(r['name']), []) if r['draft'] - 6 <= x[0] <= r['draft'] - 2]
        if len(c) > 1: c = [x for x in c if N.same_team(x[2], p.get('college') or '')] or c[:0]
        r['rk'] = c[0][1] if len(c) == 1 and c[0][1] else None
        r['rec'] = -math.log(min(r['rk'] or 2500, 2500))
        r['covid'] = int(r['draft'] == 2021); r['college'] = p.get('college') or ''
        r['era'] = int(r['draft'] >= 2024); r['nil22'] = int(r['draft'] >= 2022)
    AGE = {}
    for g in ('sr', 'under'):
        a = [r['age'] + r['days'] / 365.25 for r in fall if r['grp'] == g and r['age'] is not None]; AGE[g] = m = float(np.mean(a))
        for r in fall:
            if r['grp'] == g: r['agez'] = (r['age'] + r['days'] / 365.25 - m) if r['age'] is not None else 0.0
    posm = defaultdict(list)
    for r in fall:
        if r['hti']: posm[r['pos']].append(r['hti'])
    for r in fall:
        r['ht'] = (r['hti'] - float(np.mean(posm[r['pos']]))) if r['hti'] else 0.0
        r['nil_lx'] = r['era'] * r['lx']; r['nil_age'] = r['era'] * r['agez']
    return fall, sorted(latest)


CFB_CANDS = ['prod', 'rec', 'ht', 'covid', 'nil22', 'nil_lx', 'nil_age', 'econ', 'qb', 'p4']
POSG = {'QB': 'qb', 'HB': 'skill', 'RB': 'skill', 'WR': 'skill', 'TE': 'skill', 'T': 'ol', 'G': 'ol', 'C': 'ol', 'OT': 'ol', 'IOL': 'ol',
        'ED': 'dl', 'DI': 'dl', 'DL': 'dl', 'LB': 'lb', 'CB': 'db', 'S': 'db'}


def cfb(out):
    fall, drafts = cfb_rows()
    mu = {k: float(np.mean([r[k] for r in fall])) for k in CFB_CANDS}; sd = {k: float(np.std([r[k] for r in fall])) or 1.0 for k in CFB_CANDS}
    def feats(r, terms, base=True):
        f = [r['lx'], r['agez'], r['era']] if base else []
        return f + [(r[k] - mu[k]) / sd[k] for k in terms]
    def lodo(fx, l2=1.0):
        L, C = [], []
        for d in drafts:
            for g in ('sr', 'under'):
                tr = [r for r in fall if r['draft'] != d and r['grp'] == g]; te = [r for r in fall if r['draft'] == d and r['grp'] == g]
                if not te: continue
                b = logit([[1] + fx(r) for r in tr], [r['declared'] for r in tr], l2)
                p = 1 / (1 + np.exp(-np.array([[1] + fx(r) for r in te], float) @ b))
                L += list(ll(p, np.array([r['declared'] for r in te], float))); C += [f'{d}{g}'] * len(te)
        return np.array(L), np.array(C)
    Llive, C = lodo(lambda r: feats(r, []))
    cells = sorted(set(C))
    def cmp(L, Lref):
        d = L - Lref
        return {'logLoss': round(float(L.mean()), 4), 'vsLive': round(float(d.mean()), 4), 't': round(tstat(d), 2),
                'cellsWon': int(sum(d[C == c].mean() < 0 for c in cells)), 'cells': len(cells)}
    # baselines (Return% = 1 - declare): base rate, class, class + position group, live
    Y = np.array([r['declared'] for r in fall], float)
    Lrate = []
    for d in drafts:
        for g in ('sr', 'under'):
            tr = [r['declared'] for r in fall if r['draft'] != d]; n = sum(1 for r in fall if r['draft'] == d and r['grp'] == g)
            Lrate += list(ll(np.full(n, np.mean(tr)), np.array([r['declared'] for r in fall if r['draft'] == d and r['grp'] == g], float)))
    Lrate = np.array(Lrate)
    Lcls, _ = lodo(lambda r: [], 0.0)
    pg = sorted({POSG.get(r['pos'], 'other') for r in fall})
    Lpos, _ = lodo(lambda r: [int(POSG.get(r['pos'], 'other') == g) for g in pg[1:]], 1.0)
    out['cfb'] = {'n': len(fall), 'drafts': drafts, 'returnRate': {g: round(1 - float(np.mean([r['declared'] for r in fall if r['grp'] == g])), 3) for g in ('sr', 'under')},
                  'recMatched': round(float(np.mean([r['rk'] is not None for r in fall])), 3),
                  'prodSeen': round(float(np.mean([r['prod'] != 0 for r in fall])), 3),
                  'baselines': {'rate': round(float(Lrate.mean()), 4), 'class': round(float(Lcls.mean()), 4), 'classPos': round(float(Lpos.mean()), 4),
                                'live': round(float(Llive.mean()), 4), 'liveVsClass': cmp(Llive, Lcls), 'liveVsClassPos': cmp(Llive, Lpos)},
                  'singles': {}}
    for k in CFB_CANDS:
        L, _ = lodo(lambda r, k=k: feats(r, [k]))
        out['cfb']['singles'][k] = c = cmp(L, Llive)
        c['pass'] = bool(c['vsLive'] < 0 and c['t'] <= GATE['t'] and c['cellsWon'] >= GATE['cfb'])
        print('cfb', k, c)
    # NIL-era only (2024-25 drafts, no flag), the live model refit there vs each candidate
    nil = {}
    for k in CFB_CANDS:
        if k.startswith('nil') or k == 'covid': continue
        Ls, Lb, Cs = [], [], []
        for d in (2024, 2025):
            for g in ('sr', 'under'):
                tr = [r for r in fall if r['draft'] in (2024, 2025) and r['draft'] != d and r['grp'] == g]; te = [r for r in fall if r['draft'] == d and r['grp'] == g]
                y = np.array([r['declared'] for r in te], float)
                for fx, acc in ((lambda r: [r['lx'], r['agez']], Lb), (lambda r: [r['lx'], r['agez'], (r[k] - mu[k]) / sd[k]], Ls)):
                    b = logit([[1] + fx(r) for r in tr], [r['declared'] for r in tr], 1.0)
                    acc += list(ll(1 / (1 + np.exp(-np.array([[1] + fx(r) for r in te], float) @ b)), y))
                Cs += [f'{d}{g}'] * len(te)
        dd = np.array(Ls) - np.array(Lb); Cs = np.array(Cs)
        nil[k] = {'vsLive': round(float(dd.mean()), 4), 't': round(tstat(dd), 2), 'cellsWon': int(sum(dd[Cs == c].mean() < 0 for c in set(Cs))), 'cells': len(set(Cs))}
    out['cfb']['nilEraOnly'] = nil
    # the live model's held-out calibration, as Return%
    p = []
    for d in drafts:
        for g in ('sr', 'under'):
            tr = [r for r in fall if r['draft'] != d and r['grp'] == g]; te = [r for r in fall if r['draft'] == d and r['grp'] == g]
            b = logit([[1] + feats(r, []) for r in tr], [r['declared'] for r in tr], 1.0)
            for r, q in zip(te, 1 / (1 + np.exp(-np.array([[1] + feats(r, []) for r in te], float) @ b))):
                p.append((1 - q, 1 - r['declared'])); PREDS['cfb'].append({'name': r['name'], 'team': r['college'], 'pos': r['pos'], 'year': r['draft'],
                                                                           'p': round(float(q), 4), 'y': r['declared'], 'grp': r['grp']})
    out['cfb']['calib'] = calib(np.array([a for a, _ in p]), np.array([b for _, b in p], float))
    return out


def calib(p, y):
    e = [0, .2, .4, .6, .8, 1.01]
    return [{'pred': f'{a:.1f}-{min(c, 1):.1f}', 'n': int(((p >= a) & (p < c)).sum()), 'mean': round(float(p[(p >= a) & (p < c)].mean()), 3),
             'actual': round(float(y[(p >= a) & (p < c)].mean()), 3)} for a, c in zip(e, e[1:]) if ((p >= a) & (p < c)).sum()]


# ---------------------------------------------------------------------------------------------------------- CBB
HM = {'ACC', 'B10', 'B12', 'SEC', 'BE', 'P12'}
# NBA rookie deals, four-year scale totals in $M at anchor picks (2026-27, approx); second round ~ minimum deals
NBA_SCALE = [(1, 58.0), (2, 52.0), (3, 47.0), (5, 38.0), (10, 25.0), (14, 20.0), (20, 15.0), (25, 12.5), (30, 11.0), (31, 4.5), (45, 3.5), (60, 2.5)]
NBA_UNDRAFTED = 1.0
_lp = np.log([p for p, _ in NBA_SCALE]); _v = np.array([v for _, v in NBA_SCALE])
_z = np.linspace(-3, 3, 61); _w = np.exp(-_z ** 2 / 2); _w /= _w.sum()


def nba_rookie(lrank, sd=0.7):
    s = lrank + sd * _z
    return math.log(float((_w * np.where(s <= math.log(60), np.interp(s, _lp, _v), NBA_UNDRAFTED)).sum()))


def cbb_nil_shape():
    """today's ln xNIL (data/cbb_market.json) on ln midseason-style board rank (the 2027 consensus boards' best rank,
    unranked 100) and high-major"""
    m = json.load(open(os.path.join(ROOT, 'data', 'cbb_market.json')))['nil']
    B = {}
    with open(os.path.join(CD.BOARDS, 'all_boards.csv'), newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            if r['draft_year'] == '2027':
                k = N.key(r['name']); B[k] = min(B.get(k, 999), int(r['rank']))
    X, y = [], []
    for p in m:
        if not p.get('x'): continue
        rk = min(B.get(N.key(p['name']), 100), 100)
        X.append([1, math.log(rk), int(p.get('conf') in HM)]); y.append(math.log(p['x']))
    b = np.linalg.lstsq(np.array(X, float), np.array(y), rcond=None)[0]
    return {'a': round(float(b[0]), 3), 'b': round(float(b[1]), 3), 'hm': round(float(b[2]), 3), 'n': len(y)}


def cbb(out):
    rows = sorted(CD.rows_from_kit(), key=lambda r: r['year'])
    conf, team = {}, {}
    with open(os.path.join(CD.KIT, 'college_seasons_nba.csv'), newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f): conf[(r['pid'], int(r['year']))] = r['conf']; team[(r['pid'], int(r['year']))] = r['team']
    cm = {c: float(np.mean([r['age'] for r in rows if r['cls'] == c])) for c in CD.CLS}
    shape = cbb_nil_shape()
    for r in rows:
        r['age_c'] = r['age'] - cm[r['cls']]; r['hm'] = float(conf.get((r['pid'], r['year'])) in HM)
        r['guard'] = float(r['ht'] <= 76); r['e24'] = float(r['year'] >= 2024)
        lr = math.log(min(r['nb'], 100)) if r['nb'] else math.log(100)
        r['econ'] = nba_rookie(lr) - math.log(1e-6 * math.exp(shape['a'] + shape['b'] * lr + shape['hm'] * r['hm']))
    TERMS = CD.TERMS + ['age_c', 'hm', 'guard', 'econ', 'e24']
    mu = {k: float(np.mean([r[k] for r in rows])) for k in TERMS}; sd = {k: float(np.std([r[k] for r in rows])) or 1.0 for k in TERMS}
    LIVE = ['bpm', 'rank']       # before this script; the 2024+ step (e24) passed here and ships in cbb_declare.py
    HOLD = CD.HOLD
    te = [r for r in rows if r['year'] in HOLD]; yte = np.array([r['left'] for r in te], float); yrs = np.array([r['year'] for r in te])

    def design(rs, terms):
        X = CD.design(rs, [k for k in terms if k != 'e24'], mu, sd)     # CD.design carries the 2024+ step in column 5 (shipped)
        return X if 'e24' in terms else np.delete(X, 5, axis=1)
    def walk(terms, years=HOLD):
        Z = []
        for y in years:
            tr = [r for r in rows if r['year'] < y]; ts = [r for r in rows if r['year'] == y]
            b = CD.logit(design(tr, terms), np.array([r['left'] for r in tr], float)); Z += list(design(ts, terms) @ b)
        return np.array(Z)
    sig = lambda z: 1 / (1 + np.exp(-z))

    def cmp(L, Lref, yy, years, gate):
        d = L - Lref
        c = {'logLoss': round(float(L.mean()), 4), 'vsLive': round(float(d.mean()), 4), 't': round(tstat(d), 2),
             'won': int(sum(d[yy == y].mean() < 0 for y in years)), 'of': len(years)}
        c['pass'] = bool(c['vsLive'] < 0 and c['t'] <= GATE['t'] and c['won'] >= gate); return c
    SHIP = LIVE + ['e24']
    Llive = ll(sig(walk(LIVE)), yte); Lship = ll(sig(walk(SHIP)), yte)
    # baselines: base rate (walk forward), class + era, live before and after
    Lrate = np.concatenate([ll(np.full(int((yrs == y).sum()), np.mean([r['left'] for r in rows if r['year'] < y])), yte[yrs == y]) for y in HOLD])
    Lcls = ll(sig(walk([])), yte)
    A = {'n': len(rows), 'nHeld': len(te), 'baselines': {'rate': round(float(Lrate.mean()), 4), 'class': round(float(Lcls.mean()), 4),
                                                          'live': round(float(Llive.mean()), 4), 'shipped': round(float(Lship.mean()), 4)},
         'nilShape': shape, 'singles': {'e24': cmp(Lship, Llive, yrs, HOLD, GATE['cbbA'])}}
    print('cbb A e24', A['singles']['e24'])
    # every other candidate on top of the shipped model (with e24)
    for k in ['age_c', 'age', 'hm', 'ht', 'guard', 'nil_bpm', 'nil_rank', 'nil_age_c']:
        A['singles'][k] = c = cmp(ll(sig(walk(SHIP + [k])), yte), Lship, yrs, HOLD, GATE['cbbA']); print('cbb A', k, c)
    # stage B on top of stage A's logit, leave one draft out (as cbb_declare.py), with candidates
    BY = sorted({r['year'] for r in rows if r['nb']})
    sub = [r for r in rows if r['year'] in BY]
    ys = np.array([r['left'] for r in sub], float); yy = np.array([r['year'] for r in sub])
    def stageB(zA, extra):
        X = np.column_stack([np.ones(len(sub)), zA, [r['board'] for r in sub], [r['nb'] is not None for r in sub]] +
                            [[(r[k] - mu[k]) / sd[k] for r in sub] for k in extra])
        p = np.zeros(len(sub))
        for y in BY:
            m = yy == y; b = CD.logit(X[~m], ys[~m], l2=0.1); p[m] = sig(X[m] @ b)
        return p
    z0, z1 = walk(LIVE, BY), walk(SHIP, BY)
    LB0 = ll(stageB(z0, []), ys); pB = stageB(z1, []); LB = ll(pB, ys); LA = ll(sig(z1), ys); rk = np.array([r['nb'] is not None for r in sub])
    B = {'drafts': BY, 'n': len(sub), 'ranked': int(rk.sum()), 'live': round(float(LB0.mean()), 4), 'shipped': round(float(LB.mean()), 4),
         'liveRanked': round(float(LB0[rk].mean()), 4), 'shippedRanked': round(float(LB[rk].mean()), 4),
         'rateRanked': round(float(ll(np.full(rk.sum(), ys[rk].mean()), ys[rk]).mean()), 4),
         'boardVsA': cmp(LB, LA, yy, BY, GATE['cbbB']), 'e24': cmp(LB, LB0, yy, BY, GATE['cbbB']), 'e24Ranked': cmp(LB[rk], LB0[rk], yy[rk], BY, GATE['cbbB']),
         'singles': {}}
    print('cbb B', {k: B[k] for k in ('boardVsA', 'e24', 'e24Ranked')})
    for k in ['econ', 'age_c', 'hm', 'guard']:
        L = ll(stageB(z1, [k]), ys); c = cmp(L[rk], LB[rk], yy[rk], BY, GATE['cbbB']); B['singles'][k] = c; print('cbb B (ranked)', k, c)
    B['calibRanked'] = calib(1 - pB[rk], 1 - ys[rk])
    for r, q in zip(sub, pB):
        PREDS['cbb'].append({'name': r['name'], 'team': team.get((r['pid'], r['year']), ''), 'year': r['year'], 'p': round(float(q), 4), 'y': r['left'],
                             'cls': r['cls'], 'nb': r['nb']})
    out['cbb'] = {'stageA': A, 'stageB': B}
    return out


def main():
    out = {'_readme': __doc__.split('\n\n')[1].strip(), 'gate': GATE}
    cbb(out)
    cfb(out)
    try: out['news'] = json.load(open(OUT)).get('news')      # scripts/return_news.py's section, kept
    except (OSError, ValueError): pass
    json.dump(out, open(OUT, 'w'), indent=1)
    os.makedirs(os.path.dirname(PRED), exist_ok=True); json.dump(PREDS, open(PRED, 'w'))
    print(json.dumps(out)[:3000])


if __name__ == '__main__':
    main()
