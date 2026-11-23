#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""All-time head-coach rankings, CFB and CBB: data/coach_alltime.json from scripts/data/coach_alltime_src.json.gz
(scripts/coach_alltime_pull.py pull + build). NBA and NHL: the same method on scripts/data/coach_alltime_pro_src.json.gz
(scripts/coach_alltime_pro.py): the rating is Sports Reference SRS, the standard season 82 games, the "program" the
franchise, the national title the league title and the conference title a place in the Finals / Stanley Cup Final.
NFL: scripts/data/coach_alltime_nfl_src.json.gz (scripts/coach_alltime_nfl.py): the rating is the all-time teams' ridge points a
game, the standard season 17 games, the conference title a title-game season.

    python3 scripts/coach_alltime.py            # fit, tests, write data/coach_alltime.json

Score, in wins:
  WAx    per season, wins over the program's expectation on a standard season (12 CFB games, 30 CBB):
         G x [Phi(r / s) - Phi(e / s)], r = the team's rating (CFB: ridge SRS from every game since 1900; CBB: Sports
         Reference SRS from 1950, a win%-and-conference estimate 1939-49), s = the decade's points-to-wins probit scale,
         e = the program's expectation: its other coaches' seasons within 15 years (weight exp(-gap / 6); the 2 seasons
         after he leaves skipped, his roster), shrunk 1 season toward the conference's other members that year.
  cWAR   WAx + R a season; R = minus the mean WAx season of coaches with two or fewer seasons (replacement level).
  NT/CT  national / conference title shares (ties split), weighted by difficulty: log2(1 + sum exp(z / t)) over the field
         (z = rating z-score in the season, t fit by maximum likelihood on who won national titles), divided by the mean.
  Score  cWAR + lamN NT + lamC CT (+ CFB coordinator wins x w). lamN, lamC from a logistic fit of Hall of Fame
         selection on cWAR, NT, CT (coaches done by 2019, 8+ seasons): the ratio of each title coefficient to cWAR's.
  Coord  (CFB) unit points over the program's expectation as OC or DC (Wikipedia infoboxes 1990-2025) in wins,
         x w = the slope of a coordinator's later head-coaching WAx rate on his coordinator wins rate (0-1).
Tests: split-half (odd/even seasons), movers (old-job WAx rate vs new-job), walk-forward (measures before a cut year
predict the next 10 seasons, against win%), Hall of Fame AUC, and rank stability across expectation settings.
"""
import gzip
import json
import math
import os
import re
import sys
from collections import defaultdict
from datetime import date
from statistics import NormalDist

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import names as N

SRC = os.path.join(HERE, 'data', 'coach_alltime_src.json.gz')
SRC_PRO = os.path.join(HERE, 'data', 'coach_alltime_pro_src.json.gz')
SRC_NFL = os.path.join(HERE, 'data', 'coach_alltime_nfl_src.json.gz')
OUT = os.path.join(ROOT, 'data', 'coach_alltime.json')
PHI = NormalDist().cdf
P = dict(tau=6.0, win=15, k=1.0, skip=2)
GAMES = {'cfb': 12, 'cbb': 30, 'nba': 82, 'nhl': 82, 'nfl': 17}
LAST = {'cfb': 2025, 'cbb': 2026, 'nba': 2026, 'nhl': 2026, 'nfl': 2025}
CUTS = {'cfb': (1980, 1995, 2010)}
TOP = 300
MIN_N = 3
SHORT = {'SouthernCalifornia': 'USC', 'BrighamYoung': 'BYU', 'LouisianaState': 'LSU', 'SouthernMethodist': 'SMU',
         'TexasChristian': 'TCU', 'CentralFlorida': 'UCF', 'Nevada-LasVegas': 'UNLV', 'Texas-ElPaso': 'UTEP',
         'Texas-SanAntonio': 'UTSA', 'Alabama-Birmingham': 'UAB', 'Mississippi': 'Ole Miss', 'Miami(Florida)': 'Miami',
         'Miami(Ohio)': 'Miami (OH)', 'Pennsylvania': 'Penn', 'Pittsburgh': 'Pitt', 'NorthCarolinaState': 'NC State',
         'Connecticut': 'UConn', 'Massachusetts': 'UMass', 'Louisiana-Monroe': 'UL Monroe', 'SouthernMississippi': 'Southern Miss',
         'FloridaInternational': 'FIU', 'FloridaAtlantic': 'FAU', 'VirginiaMilitaryInstitute': 'VMI', 'TexasAM': 'Texas A&M',
         'connecticut': 'UConn', 'north-carolina': 'North Carolina', 'nevada-las-vegas': 'UNLV', 'louisiana-state': 'LSU',
         'brigham-young': 'BYU', 'southern-california': 'USC', 'texas-el-paso': 'UTEP', 'virginia-commonwealth': 'VCU',
         'alabama-birmingham': 'UAB', 'north-carolina-state': 'NC State', 'saint-josephs': "Saint Joseph's",
         'saint-johns-ny': "St. John's", 'massachusetts': 'UMass', 'mississippi': 'Ole Miss', 'pittsburgh': 'Pitt',
         'texas-am': 'Texas A&M', 'miami-fl': 'Miami', 'miami-oh': 'Miami (OH)', 'southern-methodist': 'SMU',
         'texas-christian': 'TCU', 'central-florida': 'UCF', 'pennsylvania': 'Penn', 'california-los-angeles': 'UCLA',
         'ucla': 'UCLA', 'illinois-chicago': 'UIC', 'st-johns-ny': "St. John's", 'saint-marys-ca': "Saint Mary's",
         'mount-st-marys': "Mount St. Mary's", 'st-bonaventure': 'St. Bonaventure', 'st-francis-ny': 'St. Francis (NY)',
         'saint-francis-pa': 'Saint Francis (PA)', 'albany-ny': 'Albany', 'centenary-la': 'Centenary', 'st-thomas-mn': 'St. Thomas',
         'california-davis': 'UC Davis', 'california-irvine': 'UC Irvine', 'california-riverside': 'UC Riverside',
         'california-san-diego': 'UC San Diego', 'california-santa-barbara': 'UC Santa Barbara', 'north-carolina-asheville': 'UNC Asheville',
         'southern-illinois-edwardsville': 'SIUE', 'william-mary': 'William & Mary', 'texas-el-paso': 'UTEP', 'wisconsin-milwaukee': 'Milwaukee', 'detroit-mercy': 'Detroit Mercy'}


def tname(sport, t, teams):
    if t in SHORT: return SHORT[t]
    if sport == 'cbb': return ' '.join(w if w in ('of', 'and') else w.capitalize() for w in t.split('-'))
    return teams.get(t, t)


def expected(rows, rkey='r', ckey='cs'):
    """leave-coach-out program expectation per (team, year, coach)"""
    T = defaultdict(dict); conf = defaultdict(list); ten = defaultdict(set)
    for r in rows:
        T[r['t']][r['y']] = r[rkey]; conf[(r['y'], r['conf'])].append(r)
        for c, sh in r[ckey]: ten[(c, r['t'])].add(r['y'])
    cm = {}
    for (y, c), L in conf.items():
        s = sum(x[rkey] for x in L)
        for x in L: cm[(x['t'], y)] = (s - x[rkey]) / (len(L) - 1) if c and len(L) > 1 else 0.0
    E = {}
    for r in rows:
        for c, sh in r[ckey]:
            mine = ten[(c, r['t'])]; last = max(mine); num = den = 0.0
            for dy in range(-P['win'], P['win'] + 1):
                s = r['y'] + dy
                if s in mine or s not in T[r['t']] or last < s <= last + P['skip']: continue
                w = math.exp(-abs(dy) / P['tau']); num += w * T[r['t']][s]; den += w
            E[(r['t'], r['y'], c)] = (num + P['k'] * cm[(r['t'], r['y'])]) / (den + P['k'])
    return E


class Sport:
    def __init__(self, sport, D):
        self.sp = sport; self.D = D; self.G = GAMES[sport]; self.sig = D['sig']
        self.all = D['rows']; self.rows = [r for r in self.all if r['cs']]
        self.rix = {(r['t'], r['y']): r for r in self.all}
        by = defaultdict(list)
        for r in self.all: by[r['y']].append(r)
        for y, L in by.items():
            v = np.array([x['r'] for x in L]); m, sd = v.mean(), v.std() or 1.0
            for x in L: x['z'] = (x['r'] - m) / sd
        self.temp = self.title_temp()
        nat = defaultdict(float); cf = defaultdict(float)
        for r in self.all:
            e = math.exp(r['z'] / self.temp); nat[r['y']] += e
            if r['conf']: cf[(r['y'], r['conf'])] += e
        self.NB = {y: math.log2(1 + v) for y, v in nat.items()}; self.CB = {k: math.log2(1 + v) for k, v in cf.items()}
        self.NBm = float(np.mean(list(self.NB.values()))); self.CBm = float(np.mean(list(self.CB.values())))

    def s_of(self, y): return self.sig.get(str(max(min(y // 10 * 10, 2020), 1900)), 9.0)

    def title_temp(self):
        by = defaultdict(list)
        for r in self.all: by[r['y']].append(r)
        best = None
        for t in np.arange(.2, 4.01, .05):
            ll = 0.0
            for L in by.values():
                z = np.array([x['z'] for x in L]); w = np.array([x['nt'] for x in L])
                if w.sum() < .99: continue
                ll += float((w * (z / t - (np.log(np.exp((z - z.max()) / t).sum()) + z.max() / t))).sum())
            if best is None or ll > best[1]: best = (float(t), ll)
        return best[0]

    def values(self, cut=None):
        rr = [r for r in self.rows if cut is None or r['y'] < cut]; E = expected(rr); V = []
        for r in rr:
            s = self.s_of(r['y'])
            for c, sh in r['cs']:
                V.append(dict(c=c, t=r['t'], y=r['y'], sh=sh, v=self.G * (PHI(r['r'] / s) - PHI(E[(r['t'], r['y'], c)] / s))))
        return V

    def coord_values(self):
        """CFB: coordinator wins per (coach, season) from his unit over the program's expectation for that unit"""
        out = []
        for role, key in (('oc', 'o'), ('dc', 'd')):
            rr = [dict(t=r['t'], y=r['y'], conf=r['conf'], u=r[key], r=r['r'], cs=[(c, 1 / len(r[role])) for c in r[role]],
                       hc={c for c, _ in r['cs']}) for r in self.all if r.get(role)]
            E = expected(rr, 'u', 'cs')
            for r in rr:
                s = self.s_of(r['y'])
                for c, sh in r['cs']:
                    if c in r['hc']: continue
                    d = r['u'] - E[(r['t'], r['y'], c)]
                    out.append(dict(c=c, t=r['t'], y=r['y'], sh=sh, role=role, v=self.G * (PHI(r['r'] / s) - PHI((r['r'] - d) / s))))
        return out

    def table(self, V):
        C = defaultdict(lambda: dict(n=0.0, va=0.0, teams=defaultdict(float), w=0.0, l=0.0, t=0.0, nt=0.0, ntw=0.0, ct=0.0, ctw=0.0,
                                     first=9999, last=0, vs=[]))
        for v in V:
            c = C[v['c']]; r = self.rix[(v['t'], v['y'])]; sh = v['sh']
            c['n'] += sh; c['va'] += sh * v['v']; c['vs'].append(v); c['teams'][v['t']] += sh
            c['first'] = min(c['first'], v['y']); c['last'] = max(c['last'], v['y'])
            c['w'] += sh * r['wl'][0]; c['l'] += sh * r['wl'][1]; c['t'] += sh * r['wl'][2]
            if r['nt']: c['nt'] += sh * r['nt']; c['ntw'] += sh * r['nt'] * self.NB[r['y']] / self.NBm
            if r['ct'] and r['conf']: c['ct'] += sh * r['ct']; c['ctw'] += sh * r['ct'] * self.CB[(r['y'], r['conf'])] / self.CBm
        return C


def logit(X, y, l2=1e-3):
    X = np.column_stack([np.ones(len(X)), X]); b = np.zeros(X.shape[1])
    for _ in range(100):
        p = 1 / (1 + np.exp(-X @ b)); W = p * (1 - p)
        b += np.linalg.solve(X.T @ (X * W[:, None]) + l2 * np.eye(len(b)), X.T @ (y - p) - l2 * b)
    return b


def auc(s, y):
    s, y = np.array(s, float), np.array(y); pos, neg = s[y == 1], s[y == 0]
    return float((pos[:, None] > neg[None, :]).mean() + .5 * (pos[:, None] == neg[None, :]).mean())


def corr(x, y):
    x, y = np.array(x, float), np.array(y, float); n = len(x)
    r = float(np.corrcoef(x, y)[0, 1]) if n > 2 and x.std() > 0 and y.std() > 0 else 0.0   # no spread (a small league's cut): 0
    r = max(-.9999, min(.9999, r))
    return dict(r=round(r, 3), t=round(r * math.sqrt((n - 2) / (1 - r * r)), 2), n=n)


def spearman(a, b):
    ra = np.argsort(np.argsort(a)); rb = np.argsort(np.argsort(b)); return float(np.corrcoef(ra, rb)[0, 1])


def run(sp):
    S = Sport(sp, SRC_D[sp]); names = S.D['names']
    V = S.values(); C = S.table(V)
    car = defaultdict(float)
    for v in V: car[v['c']] += v['sh']
    R0 = float(np.mean([v['v'] for v in V if car[v['c']] <= 2.0]))
    for c in C.values(): c['war'] = c['va'] - R0 * c['n']
    # coach-rate shrink (signal vs noise per season)
    by = defaultdict(list)
    for v in V: by[v['c']].append(v['v'])
    L = [np.array(x) for x in by.values() if len(x) >= 4]
    within = float(np.mean([x.var(ddof=1) for x in L])); means = np.array([x.mean() for x in L]); nn = np.array([len(x) for x in L])
    tau2 = max(1e-6, float(means.var(ddof=1) - np.mean(within / nn))); kc = within / tau2
    test = dict(signalSD=round(math.sqrt(tau2), 2), noiseSD=round(math.sqrt(within), 2), kc=round(kc, 2), titleTemp=S.temp)
    # coordinators (CFB)
    coordW = 0.0; CO = defaultdict(float)
    if sp == 'cfb':
        CV = S.coord_values(); crate = defaultdict(list)
        for v in CV: CO[v['c']] += v['sh'] * v['v']; crate[v['c']].append(v)
        X, Y = [], []
        for cid, L in crate.items():
            if cid not in C: continue
            first_hc = C[cid]['first']; pre = [v for v in L if v['y'] < first_hc]
            hc = [v for v in C[cid]['vs'] if v['y'] >= first_hc]
            if sum(v['sh'] for v in pre) >= 3 and sum(v['sh'] for v in hc) >= 3:
                X.append(sum(v['sh'] * v['v'] for v in pre) / sum(v['sh'] for v in pre)); Y.append(sum(v['sh'] * v['v'] for v in hc) / sum(v['sh'] for v in hc))
        for role in ('oc', 'dc'):   # by role, for the record
            Xr, Yr = [], []
            for cid, L in crate.items():
                if cid not in C: continue
                pre = [v for v in L if v['y'] < C[cid]['first'] and v['role'] == role]; hc = C[cid]['vs']
                if sum(v['sh'] for v in pre) >= 3 and C[cid]['n'] >= 3:
                    Xr.append(sum(v['sh'] * v['v'] for v in pre) / sum(v['sh'] for v in pre)); Yr.append(C[cid]['va'] / C[cid]['n'])
            if len(Xr) > 10: test['coord_' + role] = dict(corr(Xr, Yr), slope=round(float(np.polyfit(Xr, Yr, 1)[0]), 3))
        if len(X) > 10:
            b = float(np.polyfit(X, Y, 1)[0]); ct = corr(X, Y)
            coordW = float(min(1.0, max(0.0, b)))
            test['coord'] = dict(n=len(X), slope=round(b, 3), r=ct['r'], t=ct['t'], w=round(coordW, 3),
                                 coordSeasons=len(CV), coaches=len(CO))
    # Hall of Fame weights
    hof = set(S.D['hof'])
    key = lambda cid: N.key(re.sub(r'\s*\(.*?\)', '', names.get(cid, cid)))
    skip = set(S.D.get('hofSkip', []))            # honoured for something else (NHL: inducted as players)
    el = [(cid, c) for cid, c in C.items() if c['last'] <= 2019 and c['n'] >= 8 and key(cid) not in skip]
    y = np.array([1 if key(cid) in hof else 0 for cid, _ in el])
    X = np.array([[c['war'], c['ntw'], c['ctw']] for _, c in el]); sd = X.std(0); b = logit(X / sd, y)[1:] / sd
    lamN = max(0.0, b[1] / b[0]); lamC = max(0.0, b[2] / b[0])
    for cid, c in C.items():
        c['co'] = CO.get(cid, 0.0)
        c['score'] = c['war'] + lamN * c['ntw'] + lamC * c['ctw'] + coordW * c['co']
    test.update(R0=round(R0, 3), lamN=round(lamN, 2), lamC=round(lamC, 2), hof=int(y.sum()), hofPool=len(y),
                aucScore=round(auc([c['score'] for _, c in el], y), 3), aucWar=round(auc([c['war'] for _, c in el], y), 3),
                aucWins=round(auc([c['w'] for _, c in el], y), 3), aucTitles=round(auc([c['ntw'] + c['ctw'] for _, c in el], y), 3))
    # split-half (odd / even seasons, 8+ seasons)
    a, bb = [], []
    for cid, c in C.items():
        if c['n'] < 8: continue
        vs = sorted(c['vs'], key=lambda v: v['y']); a.append(np.mean([v['v'] for v in vs[0::2]])); bb.append(np.mean([v['v'] for v in vs[1::2]]))
    r = float(np.corrcoef(a, bb)[0, 1]); test['splitHalf'] = dict(n=len(a), r=round(r, 3), sb=round(2 * r / (1 + r), 3))
    # movers: old-job WAx rate vs new-job (3+ seasons each)
    X, Y = [], []
    for cid, c in C.items():
        st = defaultdict(list)
        for v in c['vs']: st[v['t']].append(v)
        stints = sorted(((min(v['y'] for v in L), L) for L in st.values() if len(L) >= 3), key=lambda s: s[0])
        for i in range(1, len(stints)):
            prior = [v for s in stints[:i] for v in s[1]]
            if stints[i][0] < max(v['y'] for v in prior): continue
            X.append(np.mean([v['v'] for v in prior])); Y.append(np.mean([v['v'] for v in stints[i][1]]))
    test['movers'] = dict(corr(X, Y), slope=round(float(np.polyfit(X, Y, 1)[0]), 3))
    # walk-forward
    full = defaultdict(list)
    for v in V: full[v['c']].append(v)
    wf = []
    for cut in CUTS.get(sp, (1985, 1998, 2010)):
        Cp = S.table(S.values(cut)); X = defaultdict(list); Y = []; YT = []
        for cid, c in Cp.items():
            fut = [v for v in full.get(cid, []) if cut <= v['y'] < cut + 10]; nf = sum(v['sh'] for v in fut)
            if c['n'] < 3 or nf < 3: continue
            g = c['w'] + c['l'] + c['t']
            X['wpct'].append((c['w'] + .5 * c['t']) / max(g, 1)); X['wax'].append(c['va'] / (c['n'] + kc))
            X['titles'].append((lamN * c['ntw'] + lamC * c['ctw']) / c['n'])
            X['score'].append((c['va'] - R0 * c['n'] + lamN * c['ntw'] + lamC * c['ctw']) / (c['n'] + kc))
            Y.append(sum(v['sh'] * v['v'] for v in fut) / nf)
            te = 0.0
            for v in fut:
                rr = S.rix[(v['t'], v['y'])]
                te += v['sh'] * (lamN * rr['nt'] * S.NB[rr['y']] / S.NBm + (lamC * rr['ct'] * S.CB[(rr['y'], rr['conf'])] / S.CBm if rr['ct'] and rr['conf'] else 0))
            YT.append(te / nf)
        wf.append(dict(cut=cut, wax={k: corr(x, Y) for k, x in X.items()}, titles={k: corr(x, YT) for k, x in X.items()}))
    test['walkForward'] = wf
    # rank stability: top 100 under other expectation settings
    base = sorted(C, key=lambda k: -C[k]['score'])[:100]; stab = {}
    global P
    keep = dict(P)
    for name, alt in (('tau3', dict(tau=3.0)), ('tau12', dict(tau=12.0)), ('k3', dict(k=3.0)), ('noskip', dict(skip=0))):
        P = dict(keep, **alt); Ca = S.table(S.values())
        sc = {cid: c['va'] - R0 * c['n'] + lamN * c['ntw'] + lamC * c['ctw'] + coordW * CO.get(cid, 0.0) for cid, c in Ca.items()}
        stab[name] = round(spearman([C[k]['score'] for k in base], [sc.get(k, 0) for k in base]), 3)
    P = keep; test['stability'] = stab
    # rows
    act = {c for r in S.rows if r['y'] == LAST[sp] for c, _ in r['cs']}
    ranked = sorted((kv for kv in C.items() if kv[1]['n'] >= MIN_N), key=lambda kv: -kv[1]['score'])
    rows = []
    for i, (cid, c) in enumerate(ranked):
        if i >= TOP and cid not in act: continue
        sch = sorted(c['teams'].items(), key=lambda kv: -kv[1])
        mid = (c['first'] + c['last']) / 2
        rows.append(dict(c=names.get(cid, cid), s=', '.join(tname(sp, t, S.D['teams']) for t, _ in sch[:3]) + (' +' if len(sch) > 3 else ''),
                         y0=c['first'], y1=c['last'], act=cid in act, era=int(mid // 10 * 10), n=round(c['n'], 1),
                         w=int(round(c['w'])), l=int(round(c['l'])), t=int(round(c['t'])), wax=round(c['va'], 1), war=round(c['war'], 1),
                         nt=round(c['nt'], 2), ct=round(c['ct'], 2), co=round(c['co'], 1), sc=round(c['score'], 1),
                         rt=round(c['score'] / (c['n'] + kc), 2), hof=key(cid) in hof))
    test.update(cut=wf[-1]['cut'], rScore=wf[-1]['wax']['score']['r'], rWpct=wf[-1]['wax']['wpct']['r'])
    test['era'] = era_check([(c['score'], (c['first'] + c['last']) / 2, c['n']) for _, c in ranked])
    test['eraRate'] = era_check([(c['score'] / (c['n'] + kc), (c['first'] + c['last']) / 2, 1) for _, c in ranked])
    first = min(r['y'] for r in S.rows)
    print(sp, json.dumps({k: v for k, v in test.items() if k != 'walkForward'}))
    for w in wf: print(' wf', w['cut'], {k: (v['r'], v['n']) for k, v in w['wax'].items()}, 'titles', {k: v['r'] for k, v in w['titles'].items()})
    for r in rows[:30]: print(' ', r['c'], r['s'], r['y0'], r['y1'], r['n'], r['wax'], r['war'], r['nt'], r['ct'], r['co'], r['sc'])
    return dict(rows=rows, test=test, R0=R0, lamN=lamN, lamC=lamC, coordW=coordW, kc=kc, from_=first, to=LAST[sp],
                minN=MIN_N, top=TOP)


def era_check(SC, n=100):
    """era check of the ranking (Nov 23, as scripts/alltime.py): SC = (score, mid-career year, seasons). KL of the top n
    coaches' mid-career decades vs the ranked coaches' seasons by decade (a career total grows with seasons, so a decade's
    expected share of the top is its share of coached seasons), and the era-blind 95% line (alltime.null95 on that base)"""
    from collections import Counter
    import alltime
    base = Counter()
    for _, m, k in SC: base[int(m // 10 * 10)] += k
    tot = sum(base.values())
    c = Counter(int(m // 10 * 10) for _, m, _ in sorted(SC, key=lambda t: -t[0])[:n])
    return [round(sum((c[d] / n) * math.log((c[d] / n) / (base[d] / tot)) for d in c), 3), round(alltime.null95(base, n), 3),
            {d: c[d] for d in sorted(base)}, {d: round(n * base[d] / tot, 1) for d in sorted(base)}]


def main():
    global SRC_D
    with gzip.open(SRC, 'rt') as f: SRC_D = json.load(f)
    out = dict(asof=date.today().isoformat())
    for p in (SRC_PRO, SRC_NFL):
        if os.path.exists(p):
            with gzip.open(p, 'rt') as f: SRC_D.update(json.load(f))
    for sp in ('cfb', 'cbb', 'nba', 'nhl', 'nfl'):
        if sp not in SRC_D: continue
        o = run(sp); o['from'] = o.pop('from_'); out[sp] = o
    with open(OUT, 'w') as f: json.dump(out, f, separators=(',', ':'), allow_nan=False)
    print('wrote', OUT, os.path.getsize(OUT) // 1024, 'KB')


if __name__ == '__main__':
    main()
