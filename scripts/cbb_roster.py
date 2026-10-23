#!/usr/bin/env python3
"""College basketball preseason prior: roster terms built player by player (Oct 21 2026)

Each player gets a projected BPM and minutes for the coming season, fit walk-forward on earlier seasons only:
returners and transfers from last season's line (transfers with the strength of the team they left and the one they
joined, the league factor), freshmen from recruiting rank, other newcomers (juco, international, pro) from the
newcomer mean. Minutes are normalised to the team's 500 and the roster rating is sum(share x BPM), the scale of team
efficiency margin. Coaching changes come from Sports Reference's season coach pages.

Candidates go into the prior regression on top of (or in place of) the BPM terms and run through the full game walk,
judged like fv_test: 2016-20 margin error paired t <= -1.5, 2021-26 not worse (forward selection). Kept: rret (the
returners' projected sum, in place of ret), newmin (minutes share projected for newcomers with no D-I line last season
who aren't freshmen: juco, international, sit-outs) and tenure (head coach's seasons at the school / 10, capped at 1).
Not kept: the whole roster sum (rost, alone or for ret/tr/fr), transfers or freshmen rebuilt (rtr, rfr), a new-coach
flag or the new coach's record. Age and board E[FV] inside the returner projection add nothing (class is the curve):
off by default, --age / --fv to retest.
    python3 scripts/cbb_roster.py --test [--coaches DIR] [--eval f1,f2,..]   research (DIR: Sports Reference
        /cbb/seasons/men/{y}-coaches.html pages) -> scripts/.cache/cbb/roster_test.json
    python3 scripts/cbb_roster.py --prior [--coaches DIR]   adds the kept terms to scripts/data/cbb_team_prior.json,
        history and the coming season (live rosters from scripts/cbb_prior.json.gz, coaches from ESPN)
"""
import csv
import json
import math
import os
import re
import sys
from collections import defaultdict

import numpy as np

import cbb_games as C

SRC = '/mnt/project-files/cbb/backtest/research_seasons.csv'
COACHES = os.path.join(C.HERE, 'data', 'cbb_coaches.json')
REPL = -4.0
AGE = '--age' in sys.argv              # age curve in the returner/transfer projection (failed, Oct 21 2026)
FVIN = '--fv' in sys.argv              # board E[FV] in it (failed)
KEPT = ('rret', 'newmin', 'tenure')
# players back from a lost season (Oct 23 2026, the NBA's PR #347; scripts/cbb_returners_research.py): no D-I line last
# season or under LOWMIN% of the team's minutes, and HMIN%+ in one of the two seasons before (injury, a transfer's
# sit-out year). They were newcomers (height and recruiting rank) or projected off a few minutes; now they get their own
# projection off the healthy line ('back': returner BPM error 2.72 -> 2.14 on 2016-20, t -7.5; 2.61 -> 2.25 held out)
# and count in rret: game margin 2016-20 MAE 9.3698 -> 9.3632 (t -3.7), 2021-26 9.7193 -> 9.7182 (t -0.9), lined
# 2021-26 9.1918 -> 9.1885 (t -2.6). As their own term (rback) t -3.4 / -0.9: not kept
HMIN, LOWMIN = float(os.environ.get('CBB_HMIN', 30)), 10.0
BACK = os.environ.get('CBB_BACK', '1') != '0'


def f(x, d=None):
    try:
        v = float(x)
        return d if math.isnan(v) else v
    except (TypeError, ValueError):
        return d


def load_seasons():
    by = defaultdict(dict)
    for r in csv.DictReader(open(SRC)):
        by[int(r['year'])][r['pid']] = r
    return by


def team_strength(by):
    """year -> team -> sum(minutes share x BPM), the team's box-score margin"""
    out = defaultdict(lambda: defaultdict(float))
    for y, rows in by.items():
        for r in rows.values():
            out[y][r['team']] += f(r['min_per'], 0) / 100 * f(r['bpm'], 0)
    return out


def kind(r, p, h=None):
    if h is not None:
        return 'back'
    if p is not None and f(p['min_per']):
        return 'ret' if p['team'] == r['team'] else 'tr'
    return 'fr' if r['yr'] == 'Fr' else 'new'


def healthy(lines, y):
    """lines: {year: research row} for one player. A returner's last healthy line before y and its year, else None"""
    p = lines.get(y - 1)
    if not BACK or (p is not None and f(p['min_per'], 0) >= LOWMIN):
        return None
    for k in (2, 3):
        q = lines.get(y - k)
        if q is not None and f(q['min_per'], 0) >= HMIN:
            return q, y - k
    return None


CLS = {'Fr': 1, 'So': 2, 'Jr': 3, 'Sr': 4}


def xrow(k, r, p, ts, y):
    """player inputs for season y (nothing from season y but roster membership and class)"""
    lr = f(r.get('rg_lrk'))
    lr = lr if lr is not None and f(r.get('unranked'), 1) == 0 else -math.log(600)
    if k in ('ret', 'tr'):
        b = f(p['bpm'], REPL); b3 = f(p['bpm3'], b); m = f(p['min_per'], 0) / 100
        c = CLS.get(p['yr'], 3)
        old = ts[y - 1].get(p['team'], 0.0); new = ts[y - 1].get(r['team'], 0.0)
        tr = 1.0 if k == 'tr' else 0.0
        a = f(p.get('age'))
        a = a + 1 if a else 21.0
        fv = C.player_fv(C.research_feats(p, r['team']), 'returner') - 20 if FVIN else 0.0
        x = [1.0, b, b3, m, b * m, 1.0 if c == 1 else 0.0, 1.0 if c == 2 else 0.0, tr, tr * old, tr * new, tr * b, lr]
        return x + ([a - 21, (a - 21) ** 2] if AGE else []) + ([fv] if FVIN else [])
    if k == 'back':
        # p = (healthy line, its year): the same inputs off that line, plus the years lost and whether he played a
        # few minutes last season; the class dummies are his class then, the move is from that line's team
        q, hy = p
        b = f(q['bpm'], REPL); b3 = f(q['bpm3'], b); m = f(q['min_per'], 0) / 100
        c = CLS.get(q['yr'], 3)
        tr = 1.0 if q['team'] != r['team'] else 0.0
        return [1.0, b, b3, m, b * m, 1.0 if c == 1 else 0.0, tr, tr * b, y - 1 - hy, lr]
    if k == 'fr':
        return [1.0, lr, max(0.0, lr + math.log(25)), max(0.0, lr + math.log(100))]
    return [1.0, f(r.get('hti'), 78) - 78, lr + math.log(600)]


def wls(X, y, w, lam=1.0):
    X, y, w = np.array(X), np.array(y), np.array(w)
    A = (X * w[:, None]).T @ X + lam * np.eye(X.shape[1]); A[0, 0] -= lam
    return np.linalg.solve(A, (X * w[:, None]).T @ y)


def build(by, ts, first=2014, last=2026):
    """year -> team -> roster terms, every player model fit on target years before the year; also the models"""
    pairs = defaultdict(list)            # year -> [(kind, x, bpm, min_per)]
    for y in sorted(by):
        if y - 1 not in by:
            continue
        for pid, r in by[y].items():
            p = by[y - 1].get(pid)
            h = healthy({y - k: by[y - k][pid] for k in (1, 2, 3) if y - k in by and pid in by[y - k]}, y)
            k = kind(r, p, h)
            pairs[y].append((k, xrow(k, r, h if h else p, ts, y), f(r['bpm'], REPL), f(r['min_per'], 0), r['team']))
    out, coefs, models = {}, {}, {}
    for y in range(first, last + 1):
        tr = [q for yy in pairs if yy < y for q in pairs[yy]]
        M = {}
        for k in ('ret', 'tr', 'fr', 'new', 'back'):
            Q = [q for q in tr if q[0] == k]
            if not Q:
                continue
            # BPM weighted by the minutes he went on to play (a 2-minute line is noise); minutes unweighted
            bw = wls([q[1] for q in Q], [max(-15, min(15, q[2])) for q in Q], [q[3] / 100 + 0.02 for q in Q])
            mw = wls([q[1] for q in Q], [q[3] for q in Q], [1.0] * len(Q))
            M[k] = (bw, mw)
        models[y] = M
        coefs[y] = {k: {'bpm': [round(float(v), 3) for v in M[k][0]], 'min': [round(float(v), 3) for v in M[k][1]]} for k in M}
        out[y] = terms([(team, k, x) for k, x, _, _, team in pairs[y]], M)
    return out, coefs, models


def terms(players, M):
    """[(team, kind, inputs)] -> team -> roster terms: projected minutes normalised to the team's 500"""
    T = defaultdict(list)
    for team, k, x in players:
        bw, mw = M[k]
        T[team].append((k, float(np.dot(bw, x)), max(0.5, float(np.dot(mw, x)))))
    out = {}
    for team, L in T.items():
        tot = sum(m for _, _, m in L)
        sh = [(k, b, 500 * m / tot) for k, b, m in L]
        g = lambda ks: sum(s / 100 * b for k, b, s in sh if k in ks)
        out[team] = {'rost': round(g({'ret', 'tr', 'fr', 'new', 'back'}), 3), 'rret': round(g({'ret', 'back'}), 3), 'rtr': round(g({'tr'}), 3),
                     'rfr': round(g({'fr'}), 3), 'rnew': round(g({'new'}), 3), 'rback': round(g({'back'}), 3),
                     'newmin': round(sum(s for k, _, s in sh if k == 'new') / 500, 3)}
    return out


def live_players(season, ts):
    """the coming season's rosters from the board's frozen prior (scripts/cbb_prior.json.gz), as build() inputs: the
    same research columns rebuilt from each career's Barttorvik lines (3-season BPM as team_fv_live builds it)"""
    import gzip
    d = json.load(gzip.open(os.path.join(C.HERE, 'cbb_prior.json.gz')))
    K = {k: i for i, k in enumerate(d['keep'])}
    ci = {k: i for i, k in enumerate(d['cols'])}
    out = []
    for row, c in zip(d['rows'], d['careers']):
        m = re.search(r'/(\d+)\.png', row[ci['logo']] or '')
        team = c.get('bt')
        if not team:
            continue
        g = c.get('rec') or {}
        rk = [float(v) for v in (g.get('on3rk'), g.get('rk247')) if v]
        r = {'team': team, 'yr': row[ci['cls']], 'rg_lrk': sum(-math.log(min(v, 500)) for v in rk) / len(rk) if rk else None,
             'unranked': 0.0 if rk else 1.0, 'hti': None}
        ht = re.match(r"(\d+)' (\d+)", row[ci['ht']] or '')
        if ht:
            r['hti'] = int(ht[1]) * 12 + int(ht[2])
        prev = [dict(zip(d['keep'], x)) for x in c['seasons'] if x[K['year']] < season]

        def line(i):
            # season i of prev with the 3-season BPM through it (the research column)
            q = dict(prev[i])
            num = den = 0.0
            for w, z in zip((5, 4, 3), reversed(prev[max(0, i - 2):i + 1])):
                mm = (z['mp'] or 0) * (z['gp'] or 0)
                if z['bpm'] is not None:
                    num += w * mm * z['bpm']; den += w * mm
            q['bpm3'] = ((num / den) * den / 5 + -4.0 * 300) / (den / 5 + 300) if den else -4.0
            return q
        p = line(len(prev) - 1) if prev and prev[-1]['year'] == season - 1 and prev[-1]['min_per'] else None
        h = healthy({q['year']: line(i) for i, q in enumerate(prev)}, season) if prev else None
        k = kind(r, p, h)
        out.append((team, k, xrow(k, r, h if h else p, ts, season)))
    return out


def tenure_live(co, season, tprior_teams):
    # tprior_teams: the prior file (season -> Barttorvik team -> terms), for the Sports Reference name join
    """tenure for the coming season: last season's coach (Sports Reference) still in charge per ESPN's roster feed
    -> his tenure + 1, else 1 (a new coach)"""
    import gzip
    import subprocess
    from concurrent.futures import ThreadPoolExecutor
    d = json.load(gzip.open(os.path.join(C.HERE, 'cbb_prior.json.gz')))
    ci = {k: i for i, k in enumerate(d['cols'])}
    ids = {}
    for row, c in zip(d['rows'], d['careers']):
        m = re.search(r'/(\d+)\.png', row[ci['logo']] or '')
        if m and c.get('bt'):
            ids[m[1]] = c['bt']

    def get(i):
        url = f'https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/teams/{i}/roster'
        try:
            j = json.loads(subprocess.run(['curl', '-s', '-m', '30', url], capture_output=True, text=True).stdout)
            return i, (j.get('coach') or [None])[0]
        except Exception:
            return i, None
    with ThreadPoolExecutor(8) as ex:
        now = dict(ex.map(get, sorted(ids)))
    last = coach_feats(co, tprior_teams, raw=True).get(season - 1, {})
    out = {}
    for i, team in ids.items():
        L, c = last.get(team), now.get(i)
        if not L or not c:
            continue
        same = (c.get('lastName') or '').lower().replace(' ', '-') in L['coach']
        out[team] = {'tenure': min(10, L['ten'] + 1) / 10 if same else 0.1}      # a first season counts 1, as in history
    return out


# ---------------------------------------------------------------- coaches
FIXSR = {'Albany (NY)': 'Albany', 'California Baptist': 'Cal Baptist', 'College of Charleston': 'Charleston', 'UConn': 'Connecticut',
         'ETSU': 'East Tennessee St.', 'FDU': 'Fairleigh Dickinson', 'Florida International': 'FIU', 'Grambling': 'Grambling St.',
         'UIC': 'Illinois Chicago', 'IU Indianapolis': 'IU Indy', 'IUPUI': 'IUPUI', 'Loyola (IL)': 'Loyola Chicago', 'UMass': 'Massachusetts',
         'McNeese': 'McNeese St.', 'Ole Miss': 'Mississippi', 'Kansas City': 'UMKC', 'Omaha': 'Nebraska Omaha', 'UNC': 'North Carolina',
         'Pitt': 'Pittsburgh', 'Queens (NC)': 'Queens', 'Saint Francis (PA)': 'Saint Francis', 'Sam Houston': 'Sam Houston St.',
         'St. Francis Brooklyn': 'St. Francis NY', "St. John's (NY)": "St. John's", 'UT Martin': 'Tennessee Martin',
         'Texas A&M–Corpus Christi': 'Texas A&M Corpus Chris', 'Texas–Rio Grande Valley': 'UT Rio Grande Valley'}


def nz(s):
    s = s.replace('–', ' ').replace('-', ' ').replace('State', 'St.').replace('(', '').replace(')', '').replace('.', '').replace("'", '').lower()
    return re.sub(r'\s+', ' ', s).strip()


def parse_coaches(d):
    """Sports Reference /cbb/seasons/men/{y}-coaches.html pages in d -> {year: [{school, name, coach, g, since, wpre, lpre}]}"""
    out = {}
    for fn in sorted(os.listdir(d)):
        y = int(fn[:4]); L = []
        for row in re.findall(r'<tr ><th[^>]*data-stat="coach".*?</tr>', open(os.path.join(d, fn)).read(), re.S):
            x = dict(re.findall(r'data-stat="(\w+)"[^>]*>(.*?)</t[dh]>', row))
            g = lambda k: re.sub('<[^>]+>', '', x.get(k, ''))
            m = re.search(r'/schools/([^/]+)/', x['school']); c = re.search(r'/coaches/([^.]+)\.html', x['coach'])
            if not m:
                continue
            w, l = int(g('wins_seas') or 0), int(g('losses_seas') or 0)
            L.append({'school': m[1], 'name': g('school'), 'coach': c[1] if c else g('coach'), 'g': w + l, 'since': g('since'),
                      'wpre': int(g('wins_car') or 0) - w, 'lpre': int(g('losses_car') or 0) - l})
        if L:
            out[y] = L
    return out


def coach_feats(co, tprior, raw=False):
    """year -> Barttorvik team -> newc (new head coach: the season's main coach is not last season's), newq (his win
    share before the hire minus .5, 0 for a first-time head coach), tenure (seasons at the school, capped at 10)"""
    out = {}
    main = {}
    for y, L in co.items():
        by = defaultdict(list)
        for r in L:
            by[r['school']].append(r)
        main[y] = {s: max(v, key=lambda r: r['g']) for s, v in by.items()}
    for y in sorted(main):
        if (y - 1 not in main and not raw) or str(y) not in tprior:
            continue
        bt = {nz(t): t for t in tprior[str(y)]}
        out[y] = {}
        for s, r in main[y].items():
            t = bt.get(nz(FIXSR.get(r['name'], r['name'])))
            if not t:
                continue
            ten = y - int(r['since'][:4]) if r['since'][:4].isdigit() else 0
            if raw:
                out[y][t] = {'coach': r['coach'], 'ten': min(10, ten)}
                continue
            p = main[y - 1].get(s)
            new = 1.0 if p and p['coach'] != r['coach'] else 0.0
            n = r['wpre'] + r['lpre']
            out[y][t] = {'newc': new, 'newq': new * ((r['wpre'] + 5) / (n + 10) - 0.5) if n else 0.0, 'tenure': min(10, ten) / 10}
    return out


def load_coaches():
    """the Sports Reference coach rows (scripts/data/cbb_coaches.json, refreshed with --coaches DIR)"""
    if '--coaches' in sys.argv:
        co = parse_coaches(sys.argv[sys.argv.index('--coaches') + 1])
        with open(COACHES, 'w') as fh:
            json.dump({str(k): v for k, v in co.items()}, fh, separators=(',', ':'))
    return {int(k): v for k, v in json.load(open(COACHES)).items()} if os.path.exists(COACHES) else {}


def add_terms(tprior, keys=KEPT, live=None):
    """roster and coach terms into the prior table (season -> Barttorvik team -> terms), in place: history from the
    research seasons; live = the coming season, from its rosters and ESPN's coaches. Returns the player models."""
    by = load_seasons()
    ts = team_strength(by)
    rost, pcoef, models = build(by, ts, last=live or C.LAST)
    co = load_coaches()
    cf = coach_feats(co, tprior)
    for src in (rost, cf):
        for y, T in src.items():
            for t, v in T.items():
                if str(y) in tprior and t in tprior[str(y)]:
                    tprior[str(y)][t].update({k: v[k] for k in keys if k in v})
    if live:
        T = tprior.setdefault(str(live), {})
        for t, v in terms(live_players(live, ts), models[live]).items():
            T.setdefault(t, {}).update({k: v[k] for k in keys if k in v})
        for t, v in tenure_live(co, live, tprior).items():
            T.setdefault(t, {}).update(v)
    return pcoef


def write_prior():
    tp = C.team_prior_hist()
    add_terms(tp, live=C.LAST + 1)
    with open(C.TPRIOR, 'w') as fh:
        json.dump(tp, fh, separators=(',', ':'))
    T = tp[str(C.LAST + 1)]
    print(len(T), 'teams for', C.LAST + 1, {k: sum(1 for v in T.values() if k in v) for k in KEPT})


def main():
    games, btname, d1s, tprior, avs = C.load_all()
    pcoef = add_terms(tprior, keys=('rost', 'rret', 'rtr', 'rfr', 'rnew', 'newmin', 'newc', 'newq', 'tenure'))
    co = load_coaches()
    F = json.load(open(C.FIT))
    P, feats = F['params'], F['feats']
    base_pf = list(C.PRIOR_F)

    def run(pf):
        C.PRIOR_F = pf
        W, rows = C.run_walk(P, games, tprior, btname, d1s, avs)
        D, Xm, y, TX, ty, S, line, tline, d1 = C.matrices(rows, feats)
        pred = C.walk_pred(Xm, y, S, d1)
        pr, ph = [], []
        for s in range(C.SCORE0, C.LAST + 1):
            c = W.pcoef.get(s); R = [r for r in W.prior_rows if r[0] == s]
            if c and R:
                e = np.abs(np.array([sum(c[k] * r[2][k] for k in pf) for r in R]) - np.array([r[3] for r in R]))
                (pr if s <= C.TUNE_END else ph).extend(e.tolist())
        return pred, y, S, d1, np.array(pr), np.array(ph), W.prior_coef(C.LAST + 1), D

    C.NOFEAT = False
    b0, y, S, d1, _, _, _, D = run(base_pf)
    C.NOFEAT = True
    b, y, S, d1, bpt, bph, bc, D = run(base_pf)
    ok = ~np.isnan(b) & d1
    tune, held = ok & (S <= C.TUNE_END), ok & (S > C.TUNE_END)
    lined = np.array([g.get('spread') is not None for g, _, _ in D])
    early = np.array([g['date'][5:7] == '11' or (g['date'][5:7] == '12' and int(g['date'][8:10]) < 15) for g, _, _ in D])

    def cmp(p, q):
        e0, e1 = np.abs(q - y), np.abs(p - y)
        return {'t': round(C.paired_t(e1[tune], e0[tune]), 2), 'heldT': round(C.paired_t(e1[held], e0[held]), 2),
                'tuneMae': round(float(e1[tune].mean()), 4), 'heldMae': round(float(e1[held].mean()), 4),
                'baseTune': round(float(e0[tune].mean()), 4), 'baseHeld': round(float(e0[held].mean()), 4),
                'linedHeldMae': round(float(e1[held & lined].mean()), 4), 'baseLinedHeld': round(float(e0[held & lined].mean()), 4),
                'linedHeldT': round(C.paired_t(e1[held & lined], e0[held & lined]), 2),
                'earlyHeldMae': round(float(e1[held & early].mean()), 4), 'baseEarlyHeld': round(float(e0[held & early].mean()), 4),
                'earlyHeldT': round(C.paired_t(e1[held & early], e0[held & early]), 2)}
    out = {'fallback': cmp(b, b0), 'playerModel2026': pcoef[C.LAST], 'age': AGE, 'fv': FVIN, 'rounds': []}
    print('fallback', out['fallback'], flush=True)
    if '--eval' in sys.argv:
        pf = sys.argv[sys.argv.index('--eval') + 1].split(',')
        p, _, _, _, pt, ph, pc, _ = run(pf)
        print('EVAL', {'age': AGE, 'fv': FVIN}, cmp(p, b), round(float(pt.mean()), 3), round(float(ph.mean()), 3), flush=True)
        return
    BPMT = ('ret', 'tr', 'fr')
    groups = {'rost': (['rost'], ()), 'rost for bpm': (['rost'], BPMT), 'parts': (['rret', 'rtr', 'rfr', 'rnew'], ()),
              'parts for bpm': (['rret', 'rtr', 'rfr', 'rnew'], BPMT), 'rnew': (['rnew'], ()), 'newmin': (['newmin'], ()),
              'rtr for tr': (['rtr'], ('tr',)), 'rfr for fr': (['rfr'], ('fr',)), 'rret for ret': (['rret'], ('ret',))}
    if co:
        groups.update({'tenure': (['tenure'], ()), 'newc': (['newc'], ()), 'newc+newq': (['newc', 'newq'], ())})
    cur, curp = list(base_pf), b
    while groups:
        res = []
        for name, (add, drop) in groups.items():
            pf = [k for k in cur if k not in drop] + [k for k in add if k not in cur]
            if pf == cur:
                continue
            p, _, _, _, pt, ph, pc, _ = run(pf)
            r = dict(name=name, feats=pf, **cmp(p, curp), priorMaeTune=round(float(pt.mean()), 3), priorMaeHeld=round(float(ph.mean()), 3),
                     coef={k: round(float(pc[k]), 3) for k in pf})
            print(r, flush=True)
            res.append((r, p))
        out['rounds'].append([r for r, _ in res])
        okr = [(r, p) for r, p in res if r['t'] <= -1.5 and r['heldMae'] <= r['baseHeld']]
        if not okr:
            break
        r, p = min(okr, key=lambda q: q[0]['t'])
        print('KEEP', r['name'], r['t'], r['heldT'], flush=True)
        cur, curp = r['feats'], p
        groups.pop(r['name'])
    out['final'] = cur
    out['vsShipped'] = cmp(curp, b0)
    print('FINAL', cur, out['vsShipped'], flush=True)
    C.PRIOR_F = base_pf
    json.dump(out, open(os.path.join(C.HERE, '.cache', 'cbb', 'roster_test.json'), 'w'), indent=1)


if __name__ == '__main__':
    if '--prior' in sys.argv:
        write_prior()
    elif '--test' in sys.argv:
        main()
    else:
        print(__doc__)
