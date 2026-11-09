# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""All-time FV lists by position, and how the grades turned out (Noah, Nov 1 2026).

Every prospect board's history, graded the way that board grades today, ranked within position:
  cfb     every FBS season 2014-25 at QB, RB, WR, TE, EDGE, DT and LB (scripts/cfb_fv_refit.mjs --alltime: the board at the
          end of each season under the shipped weights, box-score stand-ins for 2014-18, PFN from 2019; no consensus), each
          last season then graded at the draft with the combine in (cfb_combine). Outcome = NFL AV a season through 2025 read back onto the FV scale
          (the board's AV_BY_FV map), drafts 2015-23 only; later drafts show the pick, outcome pending.
  cbb     each player's draft-day grade, his last college season 2009-26 with the June boards (scripts/cbb_draftday.py,
          out of sample to 2016, forward after; still in college: his latest season's end), outcome = peak NBA value FV
          (college exits through 2020, six NBA seasons or more)
  hockey  every 2008-19 pick's draft-day grade, fit without his class (data/hockey.json past), outcome = peak NHL WAR FV
  soccer  past seasons 2013-20, listed players (data/soccer_prospects.json past), outcome = peak GAR FV (best three seasons, 22-26)
  tennis  each player once, at his last October as a prospect (data/tennis_prospects_fit.json alltime, held out by birth
          year), ATP and WTA, outcome = peak ranking FV
A player shows once: CFB and CBB at the draft that followed his last season (Nov 3 2026: a best season ran hot and
missed the final season and the combine), the other boards at his best season's grade. The headline is the mean outcome (stretched above each board's knot,
data/fv_scale.json); fvx is the exact mean, and the check compares it with what the careers became.

    python3 scripts/fv_alltime.py [--cfb-rows=<file from cfb_fv_refit.mjs --alltime>] [--cfb-combine] -> data/fv_alltime.json
The CFB rows are kept in scripts/data/cfb_alltime_rows.json.gz, so the other boards refresh without the CFB rebuild;
--cfb-rows and --cfb-combine add each last season's combine (nflverse) to them (cfb_combine).
"""
import datetime
import gzip
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fv_scale import fv_of

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = lambda *a: os.path.join(ROOT, *a)
OUT = P('data', 'fv_alltime.json')
CFB_ROWS = P('scripts', 'data', 'cfb_alltime_rows.json.gz')
CBB_ROWS = P('scripts', 'data', 'cbb_draftday.json.gz')   # scripts/cbb_draftday.py
TOP = 50            # players listed per position
TOPCHK = 25         # the all-time top that the check follows, per position
AV_BY_FV = [[20, 0], [30, 0.4], [40, 1.7], [50, 3.7], [60, 5.0], [65, 6.3], [70, 7.2], [75, 8.1], [80, 10.1]]   # as cfb_teams.mjs
CFB_MATURE = 2023   # last draft with three NFL seasons in (AV through 2025)
CFB_POS = {'DL': 'DT'}
# the past lists of hockey, soccer and tennis also carry players picked for their outcome; only the part listed on the
# grade alone is complete, so the lists and the check read that part only
HK_ALL = lambda r: (r['pick'] or 999) <= 64 or r['fvx'] >= 35
SOC_ALL = lambda r: r['fvx'] >= 49.5
TN_ALL = lambda r: r['fvx'] >= 45


def fv_from_av(av):
    if av is None: return None
    if av <= 0: return 20.0
    f, a = zip(*AV_BY_FV)
    return float(np.interp(av, a, f))


def r1(x): return None if x is None else round(float(x), 1)


def best_per_player(rows, key):
    """one row per player: his best season by the exact mean"""
    best = {}
    for r in rows:
        k = key(r)
        if k not in best or r['fvx'] > best[k]['fvx']: best[k] = r
    return list(best.values())


def check(rows, peaks, groups, grp, complete=lambda r: True):
    """bands of the exact mean against the outcome (every graded row with an outcome), and the all-time top by position"""
    R = [r for r in rows if r.get('out') is not None and complete(r)]
    x, y = np.array([r['fvx'] for r in R]), np.array([r['out'] for r in R])
    edges = [-1, 30, 35, 40, 45, 50, 55, 60, 65, 99]
    bands = []
    for lo, hi in zip(edges, edges[1:]):
        m = (x >= lo) & (x < hi)
        if m.sum() < 5: continue
        bands.append({'lo': max(lo, 20), 'hi': hi if hi < 99 else None, 'n': int(m.sum()), 'given': r1(x[m].mean()), 'became': r1(y[m].mean()),
                      'se': r1(y[m].std(ddof=1) / np.sqrt(m.sum())) if m.sum() > 1 else None})
    # merge a thin top band into the one below
    while len(bands) > 2 and bands[-1]['n'] < 15:
        a, b = bands[-2], bands.pop()
        m = (x >= a['lo']) if a['lo'] > 20 else np.ones(len(x), bool)
        a.update(hi=None, n=int(m.sum()), given=r1(x[m].mean()), became=r1(y[m].mean()), se=r1(y[m].std(ddof=1) / np.sqrt(m.sum())))
    slope = float(np.polyfit(x, y, 1)[0]) if len(R) > 10 else None
    top = []
    for g in groups:
        S = sorted([r for r in peaks if grp(r) == g and r.get('out') is not None and complete(r)], key=lambda r: -r['fvx'])[:TOPCHK]
        if len(S) < 5: continue
        gv, bc = np.array([r['fvx'] for r in S]), np.array([r['out'] for r in S])
        top.append({'pos': g, 'n': len(S), 'given': r1(gv.mean()), 'became': r1(bc.mean()), 'se': r1(bc.std(ddof=1) / np.sqrt(len(S))),
                    'hit': int((bc >= gv).sum())})
    return {'n': len(R), 'bias': r1((y - x).mean()), 'slope': None if slope is None else round(slope, 2), 'bands': bands, 'top': top}


# the list shows a player only once he has left college, drafted or not (Noah, Nov 3 2026); grades are untouched
GONE = lambda r: r.get('status') != 'college'


def listed(peaks, groups, grp, complete=lambda r: True):
    out = []
    for g in groups:
        S = sorted([r for r in peaks if grp(r) == g and complete(r)], key=lambda r: -r['fvx'])[:TOP]
        for i, r in enumerate(S): out.append({**r, 'prk': i + 1})
    return sorted(out, key=lambda r: -r['fvx'])


# ---- boards ---------------------------------------------------------------------------------------------------------

NFLVERSE = 'https://github.com/nflverse/nflverse-data/releases/download/'
COMBINE_GRP = {'QB': 'QB', 'RB': 'RB', 'FB': 'RB', 'WR': 'WR', 'TE': 'TE', 'DE': 'EDGE', 'EDGE': 'EDGE', 'OLB': 'EDGE', 'DT': 'DL', 'DL': 'DL', 'NT': 'DL',
               'ILB': 'LB', 'LB': 'LB'}
CFB_FAM = {'QB': {'QB'}, 'RB': {'RB', 'WR', 'TE'}, 'WR': {'RB', 'WR', 'TE'}, 'TE': {'RB', 'WR', 'TE'}, 'EDGE': {'EDGE', 'DL', 'LB'}, 'DL': {'EDGE', 'DL', 'LB'},
           'LB': {'EDGE', 'DL', 'LB'}}
OL = {'OL', 'T', 'G', 'C', 'OT', 'OG'}
# 2021: no combine (COVID); nflverse lists pro-day testers instead (464, missing invitees who skipped pro days: DeVonta
# Smith, Najee Harris), so the list isn't an invite list that year
NO_COMBINE = {2021}


def nflverse(name):
    import csv, io, subprocess
    txt = subprocess.run(['curl', '-sSL', '-m', '120', NFLVERSE + name], capture_output=True, text=True, check=True).stdout
    return list(csv.DictReader(io.StringIO(txt)))


def cfb_combine(src):
    """each last season's combine at the draft that followed (nflverse): invited (on the combine list) and the athletic
    composite of the live board (fetch_cfb.mjs FV_ATH / cfb_teams.mjs fetchCombine: speed score, vertical, broad, 3-cone
    and shuttle reversed, each a z against every 2010+ invitee at the group, the mean of 2+, centred on the testers),
    capped at 2 SD. Also drops a pick a running back or receiver got only by sharing an offensive lineman's name (the
    --alltime family match let UAB RB Spencer Brown take Northern Iowa OT Spencer Brown's career)."""
    import names as N
    C = nflverse('combine/combine.csv'); picks = {(int(r['season']), int(r['pick'])): r for r in nflverse('draft_picks/draft_picks.csv') if r['pick']}
    num = lambda x: float(x) if x not in ('', 'NA', None) else None
    met = lambda p: {'spd': num(p['wt']) * 200 / num(p['forty']) ** 4 if num(p['forty']) and num(p['wt']) else None, 'vert': num(p['vertical']),
                     'broad': num(p['broad_jump']), 'cone': -num(p['cone']) if num(p['cone']) else None, 'shut': -num(p['shuttle']) if num(p['shuttle']) else None}
    pool = {}
    for p in C:
        g = COMBINE_GRP.get(p['pos'])
        if g and int(p['season']) >= 2010:
            for k, v in met(p).items():
                if v is not None: pool.setdefault(g + k, []).append(v)
    ms = {k: (float(np.mean(v)), float(np.std(v))) for k, v in pool.items()}
    def ath(p, g):
        zs = [(v - ms[g + k][0]) / ms[g + k][1] for k, v in met(p).items() if v is not None and g + k in ms]
        return float(np.mean(zs)) if len(zs) >= 2 else None
    tm = {}
    for p in C:
        g = COMBINE_GRP.get(p['pos']); a = ath(p, g) if g and int(p['season']) >= 2010 else None
        if a is not None: tm.setdefault(g, []).append(a)
    tm = {g: float(np.mean(v)) for g, v in tm.items()}
    by = {}
    for p in C: by.setdefault((int(p['season']), N.key(p['player_name'])), []).append(p)
    nfix = 0
    for r in src:
        r['inv'] = r['ath'] = None
        if not r['final']: continue
        pk = picks.get((r['draft'], r['pick'])) if r['pick'] else None
        if pk and r['g'] in ('RB', 'WR') and pk['position'] in OL:
            r.update(pick=None, draft=None, av=0, ap=0, pb=0); nfix += 1
        D = r['draft'] or r['last'] + 1
        cand = [p for p in by.get((D, N.key(r['name'])), []) if COMBINE_GRP.get(p['pos']) in CFB_FAM[r['g']]]
        if len(cand) > 1: cand = [p for p in cand if N.same_team(p['school'], r['team'])] or cand[:1]
        if D > max(int(p['season']) for p in C): continue          # that combine isn't held yet
        if D in NO_COMBINE: continue
        r['inv'] = 0
        if not cand: continue
        g = COMBINE_GRP[cand[0]['pos']]; a = ath(cand[0], g)
        r['inv'] = 1; r['ath'] = None if a is None else round(max(-2.0, min(2.0, a - tm[g])), 3)
    print('cfb combine: finals', sum(r['final'] for r in src), 'invited', sum(r.get('inv') == 1 for r in src), 'tested', sum(r.get('ath') is not None for r in src),
          'OL name matches dropped', nfix)
    return src


def cfb(path):
    src = json.load(gzip.open(path) if path.endswith('.gz') else open(path))
    rows = []
    for r in src:
        draft = r['draft'] or r['last'] + 1
        mature = r['av'] is not None and draft <= CFB_MATURE
        status = 'college' if r['last'] >= 2026 else None
        rows.append({'name': r['name'], 'season': r['s'], 'team': r['team'], 'pos': CFB_POS.get(r['g'], r['g']), 'id': r['id'],
                     'fvx': r['fvx'], 'fv': fv_of('cfb', r['fvx']), 'out': r1(fv_from_av(r['av'])) if mature else None,
                     'pick': r['pick'], 'draft': r['draft'], 'pb': r['pb'] or 0, 'ap': r['ap'] or 0, 'av': r1(r['av']) if mature else None,
                     'status': status, 'last': r['last']})
    # box-score era (2014-18): the stand-in line is a noisier read than PFN's, and its grades ran hot above 40 against
    # the NFL (finals 60+: 65.8 given, 55.5 became; PFN-era finals 66.1 -> 71.9). Each box-era mean is put on what
    # such grades became: outcome on (x - 20, max(0, x - 40)), fit on box rows with outcomes, last and earlier seasons
    # apart. Class held out (Nov 1 2026): last seasons MSE t 1.8, 40+ better in 4 of 5 classes; earlier seasons t 2.9,
    # 6 of 8. PFN-era grades (2019+) stay as graded
    X = lambda x: [x - 20, max(0.0, x - 40)]
    boxfit = {}
    for fin in (True, False):
        S = [(r, src) for r, src in zip(rows, src) if r['season'] < 2019 and r['out'] is not None and src['final'] == fin]
        A = np.array([X(r['fvx']) for r, _ in S]); y = np.array([r['out'] - 20 for r, _ in S])
        boxfit[fin] = np.linalg.lstsq(A, y, rcond=None)[0]
    for r, q in zip(rows, src):
        if r['season'] < 2019:
            r['fvxRaw'] = r['fvx']; r['fvx'] = round(max(20.0, 20 + float(np.dot(boxfit[q['final']], X(r['fvx'])))), 2); r['fv'] = fv_of('cfb', r['fvx'])
            r['box'] = True
    # the draft (Noah, Nov 3 2026: misses on the all-time board): each player shows once, at his last season graded
    # the day of the draft, with the combine in: invited or not, and the athletic composite (cfb_combine). Fit on the
    # mature drafts (2015-23), outcome on (x - 20, max(0, x - 40), invited, athletic z); each mature row takes the fit
    # with its own draft class held out, later drafts the full fit; 2021 (no combine) on the line alone. Class held
    # out, last seasons with an outcome and a combine (6,560): MSE 72.5 -> 50.3 (t -12.2, better in 8 of 8 classes),
    # each class's top 32 realized 45.9 -> 48.8. On the list (one row per player, graded or reaching 35+), against
    # each player's best season: MSE 461 -> 310 (t -15.2, 9/9). Tested and not used: athletic z by position, speed
    # score, measured height and weight (+.3 MSE), a position hinge at the top (t -0.0), invited x grade
    # Nov 4 2026, TE top (25 given 51 became 43): a TE own line (t -1.7), TE slope (t -2.0), TE+RB lines (t -1.2), Holm k 3:
    # none pass. Part of the gap is AV (TE Pro Bowlers map to 58 vs 63-75 elsewhere); the rest is a flat TE grade slope (.72)
    Z = lambda r, q: X(r['fvx']) + [float(q.get('inv') or 0), float(q.get('ath') or 0)]
    fin = [(r, q) for r, q in zip(rows, src) if q['final'] and r['last'] < 2026]
    fits = {}
    for comb in (True, False):     # with the combine; without it (2021) on the line alone
        f = (lambda r, q: Z(r, q)) if comb else (lambda r, q: X(r['fvx']))
        M = [(r, q) for r, q in fin if r['out'] is not None and (q.get('inv') is not None or not comb)]
        cls = np.array([r['draft'] or r['last'] + 1 for r, _ in M]); A = np.array([f(r, q) for r, q in M]); y = np.array([r['out'] - 20 for r, _ in M])
        fits[comb] = (f, np.linalg.lstsq(A, y, rcond=None)[0], {})
        for c in sorted(set(cls)):
            b = np.linalg.lstsq(A[cls != c], y[cls != c], rcond=None)[0]
            for (r, q), a in zip([m for m, t in zip(M, cls == c) if t], A[cls == c]): fits[comb][2][id(r)] = float(a @ b)
    for r, q in fin:
        f, b, held = fits[q.get('inv') is not None]
        r['fvxSeason'] = r['fvx']; r['fvx'] = round(min(80.0, max(20.0, 20 + held.get(id(r), float(np.dot(b, f(r, q)))))), 2); r['fv'] = fv_of('cfb', r['fvx'])
        r['comb'] = 'tested' if q.get('ath') is not None else 'invited' if q.get('inv') else 'not invited' if q.get('inv') == 0 else 'no combine'
    draftfit = fits[True][1]
    # one row per player: his draft-day grade once he has left, his latest season while he is in college
    fam = {'QB': 'QB', 'RB': 'O', 'WR': 'O', 'TE': 'O', 'EDGE': 'D', 'DT': 'D', 'LB': 'D'}
    one = {}
    for r in rows:
        k = fam[r['pos']] + '|' + str(r['id'] or r['name'])
        if k not in one or r['season'] > one[k]['season']: one[k] = r
    peaks = list(one.values())
    groups = ['QB', 'RB', 'WR', 'TE', 'EDGE', 'DT', 'LB']
    seasons = sorted({r['season'] for r in rows})
    return {'label': 'CFB', 'seasons': [seasons[0], seasons[-1]], 'groups': groups, 'n': len(rows), 'players': len(peaks),
            'outcome': 'NFL AV a season through 2025 on the FV scale, drafts 2015-23',
            'boxfit': {('last' if k else 'earlier'): [round(float(v), 3) for v in b] for k, b in boxfit.items()},
            'draftfit': [round(float(v), 3) for v in draftfit], 'basis': 'draft',
            'rows': [{k: v for k, v in r.items() if k not in ('id',)} for r in listed(peaks, groups, lambda r: r['pos'], GONE)],
            'check': check(peaks, peaks, groups, lambda r: r['pos'])}


def cbb():
    """each player once, at his draft-day grade (scripts/cbb_draftday.py: his last college season, the June boards);
    a player still in college at the end of his latest season"""
    d = json.load(gzip.open(CBB_ROWS))
    R = d['rows']
    peaks = best_per_player(R, lambda r: r['name'] + '|' + r['pos'] + '|' + str(r['season']))
    groups = ['G', 'F', 'C']
    return {'label': 'CBB', 'seasons': [min(r['season'] for r in R), max(r['season'] for r in R)], 'groups': groups, 'n': len(R), 'players': len(peaks),
            'outcome': 'peak NBA value (XPM and role) on the FV scale', 'rows': listed(peaks, groups, lambda r: r['pos'], GONE),
            'check': check(R, peaks, groups, lambda r: r['pos']), 'basis': 'draft'}


def hockey():
    H = json.load(open(P('data', 'hockey.json')))['past']
    grp = lambda r: 'G' if r['pos'] == 'G' else 'D' if r['pos'] == 'D' else 'F'
    R = [{'name': r['name'], 'season': r['year'], 'team': r['team'], 'pos': r['pos'], 'grp': grp(r), 'fvx': r.get('fvx', r['fv']), 'fv': r['fv'], 'out': r['out'],
          'pick': r['pick'], 'draft': r['year'], 'gp': r.get('gp'), 'peak': r.get('peak'), 'gpeak': r.get('gpeak')} for r in H]
    groups = ['F', 'D', 'G']
    return {'label': 'Hockey', 'seasons': [min(r['season'] for r in R), max(r['season'] for r in R)], 'groups': groups, 'n': len(R), 'players': len(R),
            'outcome': 'peak NHL WAR (goalies GSAx) on the FV scale', 'rows': listed(R, groups, lambda r: r['grp'], HK_ALL), 'check': check(R, R, groups, lambda r: r['grp'], HK_ALL),
            'complete': 'every pick in rounds 1-2 and every later pick graded 35+ (the past list also carries later picks who reached 45+, left out here)'}


def soccer():
    S = json.load(open(P('data', 'soccer_prospects.json')))['past']
    R = [{'name': r['name'], 'season': r['season'], 'team': r['club'], 'pos': r['pos'], 'fvx': r.get('fvx', r['fv']), 'fv': r['fv'], 'out': r.get('out'),
          'age': r.get('age'), 'nat': r.get('nat')} for r in S]
    peaks = best_per_player(R, lambda r: r['name'])
    groups = ['F', 'M', 'D', 'G']
    return {'label': 'Soccer', 'seasons': [min(r['season'] for r in R), max(r['season'] for r in R)], 'groups': groups, 'n': len(R), 'players': len(peaks),
            'outcome': 'peak GAR (best three seasons, ages 22-26) on the FV scale', 'rows': listed(peaks, groups, lambda r: r['pos'], SOC_ALL), 'check': check(R, peaks, groups, lambda r: r['pos'], SOC_ALL),
            'complete': 'every player graded 50+ at his youngest season (the past list also carries lower grades who reached 55+, left out here)'}


def tennis():
    T = json.load(open(P('data', 'tennis_prospects_fit.json')))
    R = []
    for tour in ('atp', 'wta'):
        for r in T[tour].get('alltime') or T[tour]['past']:
            R.append({'name': r['name'], 'season': r['season'], 'team': r.get('nat', ''), 'pos': tour.upper(), 'fvx': r.get('fvx', r['fv']), 'fv': r['fv'], 'out': r.get('out'),
                      'age': r.get('age'), 'rank': r.get('rank'), 'pkr': r.get('pkr')})
    peaks = best_per_player(R, lambda r: r['pos'] + '|' + r['name'])
    groups = ['ATP', 'WTA']
    return {'label': 'Tennis', 'seasons': [min(r['season'] for r in R), max(r['season'] for r in R)], 'groups': groups, 'n': len(R), 'players': len(peaks),
            'outcome': 'peak ranking on the FV scale', 'rows': listed(peaks, groups, lambda r: r['pos'], TN_ALL), 'check': check(R, peaks, groups, lambda r: r['pos'], TN_ALL),
            'complete': 'every ranked player graded 45+ in his last October as a prospect (the past list also carries lower grades who reached 55+, left out here)'}


def main():
    a = {k: v for k, _, v in (x.lstrip('-').partition('=') for x in sys.argv[1:])}
    if a.get('cfb-rows') or 'cfb-combine' in a:
        src = json.load(open(a['cfb-rows'])) if a.get('cfb-rows') else json.load(gzip.open(CFB_ROWS))
        src = cfb_combine(src)
        with gzip.open(CFB_ROWS, 'wt') as f: json.dump(src, f, separators=(',', ':'))
    out = {'asof': datetime.date.today().isoformat(), 'method': 'scripts/fv_alltime.py'}
    for k, fn in ((('cfb', lambda: cfb(CFB_ROWS)),) if os.path.exists(CFB_ROWS) else ()) + (('cbb', cbb), ('hockey', hockey), ('soccer', soccer), ('tennis', tennis)):
        out[k] = fn()
        c = out[k]['check']
        print(k, out[k]['n'], 'rows', out[k]['players'], 'players', 'check n', c['n'], 'bias', c['bias'], 'slope', c['slope'])
        for t in c['top']: print('   top', TOPCHK, t)
    s = json.dumps(out, separators=(',', ':'), allow_nan=False)
    open(OUT, 'w').write(s)
    print('wrote', OUT, len(s) // 1024, 'KB')


if __name__ == '__main__':
    main()
