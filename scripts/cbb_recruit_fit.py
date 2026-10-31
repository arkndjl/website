#!/usr/bin/env python3
"""College basketball recruit boards: HS classes graded on the CBB board's FV scale, fit on what past recruits became.

    node scripts/cbb_on3.mjs 2027 2028 2029        # the live classes (and 2009-2026 once, for the history)
    python3 scripts/cbb_recruit_fit.py              # link, test, fit, write data/cbb_recruits.json
    python3 scripts/cbb_recruit_fit.py --offline    # refit from scripts/data/cbb_recruit_hist.json.gz (no kit, no pulls)

Outcome: the board's realized FV, the NBA role a career reached (scripts/cbb_link.py TIERS: 20 non-NBA, 30 reached
the NBA ... 50 4+ seasons as a starter, 60 2+ All-Star, 65-80 All-NBA), so a recruit's FV reads like a freshman's on the
board. The headline is the expected FV (the mean outcome). Noah rejected the shared value scale (Oct 26), so the
first version's peak-share target was dropped.

History: On3 industry rankings (the consensus of On3, 247, ESPN and Rivals) for the 2009-2025 classes, every listed
recruit, so the prep-to-pro and overseas routes are in the sample. Each recruit is linked to his NBA career by the
college link (scripts/cbb_link.py: Barttorvik career, On3 consensus rank and class; realized FV from the kit) or by
name through scripts/names.py with a class that fits his NBA age (class = season - age + 17, +-1; role tier from his
games and starts). Classes 2009-2016 train; 2017-2018 are a forward look on careers still running.

Model: hurdle, as the board's. P(reached the NBA) is a logistic; log(FV - 20) given NBA a ridge, its mean from the
residuals (Duan's smearing), so E[FV] = 20 + P x E[FV - 20 | NBA]. Drivers enter only if they help out of sample with
whole classes held out (8 folds): better log loss for P, better RMSE for log(FV - 20), both scored as a paired t across
classes (t >= 2, 6+ of 8 classes).

Board parity with the football recruit tabs (Oct 31 2026): ARK stars (the FV cut at backtested outcome bands, half stars,
5-star+; ark_stars), college years 1-3 (plays D-I, minutes and BPM if he does, college value; NIL-era seasons, path_fit)
and xNIL (college value at the school's NIL price; xnil_price). The history keeps every recruit's D-I seasons and the
On3 recruitment fields tested as drivers (offer interest, prep power, commitment timing), so --offline rebuilds it all.
"""
import csv
import gzip
import json
import math
import os
import sys
from collections import Counter, defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import names as N   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ON3 = os.path.join(ROOT, 'scripts', '.cache', 'cbb', 'on3')
KIT = '/mnt/project-files/cbb'
HIST = os.path.join(ROOT, 'scripts', 'data', 'cbb_recruit_hist.json.gz')
OUT = os.path.join(ROOT, 'data', 'cbb_recruits.json')
OFFLINE = '--offline' in sys.argv
VERBOSE = '-v' in sys.argv

TRAIN = list(range(2009, 2017))
FORWARD = [2017, 2018]
LIVE = [2027, 2028, 2029]
NOW_CLASS = 2026                     # this season's freshmen: the board grades them, the recruit model is checked on them
NBA_LAST = 2026
VORX_K, VORX_REP = 0.030, -1.4        # VORX (cbb/vorx, NBA thread Oct 18)
C_TS = 1 / 280                        # the value map (fv-value-scale)
AGES = (22, 28)
RANK_CAP = 400


def fv_of(t):
    """FV of an outcome measured above the 20 floor (the hurdle models t = realized FV - 20)"""
    return 20 + max(t, 0)


def ts_of(fv):
    return fv - 20


# ---------------------------------------------------------------- college value and xNIL
# A college season's value: share of team minutes x BPM above a replacement level of -3 (about the 25th percentile of
# rotation players outside the top leagues, 2025-26), so a team's five spots sum to its value above a replacement roster.
REP_BPM = -3.0
LEVELS = {'HM': {'ACC', 'B10', 'B12', 'SEC', 'BE'}, 'MM': {'A10', 'MWC', 'WCC', 'Amer', 'MVC', 'P12'}}
# Men's basketball NIL budgets a program, per season (revenue share and collective, 2026-27; an assumption, scaled like
# the football ones in fetch_cfb.mjs XNIL by program strength: x e^(.3 z), normalized within the level)
XNIL = {'HM': 6e6, 'MM': 1.2e6, 'LM': 0.25e6, 'tilt': 0.3}


def college_value(min_per, bpm):
    return min_per / 100 * max(0.0, bpm - REP_BPM)


def level_of(conf):
    return next((k for k, v in LEVELS.items() if conf in v), 'LM')


# ---------------------------------------------------------------- history: On3 classes, NBA careers, the link
def load_on3(cls):
    p = os.path.join(ON3, f'{cls}.json')
    return json.load(open(p)) if os.path.exists(p) else []


def pos_group(p):
    p = (p or '').upper()
    return 'G' if p in ('PG', 'SG', 'CG', 'G') else 'B' if p in ('PF', 'C', 'F/C') else 'W'


def compact(r, cls):
    s = r.get('svc') or {}
    return {'cls': cls, 'key': r['key'], 'name': r['name'], 'pos': r.get('pos'), 'ht': r.get('ht'), 'wt': r.get('wt'),
            'cons': r.get('cons'), 'rk': r.get('consRank'), 'stars': r.get('consStars'), 'fsp': r.get('fiveStarPlus'),
            'state': r.get('state'), 'home': r.get('home'), 'team': r.get('team'),
            'svc': {k: v[1] for k, v in s.items() if v and v[1]}, 'svr': {k: v[0] for k, v in s.items() if v and v[0]},
            'x': {'interest': r.get('interest'), 'hs': r.get('hsSlug'), 'commit': (r.get('commitDate') or '')[:10] or None}}


def nba_careers():
    """bref id -> name, seasons [(year, age, share of a team's VORX)] from the kit (XPM blend by season, bbref ages)"""
    ages = {(r['bref'], r['year']): r['age'] for r in json.load(open(os.path.join(KIT, 'kit', 'bbref_nba_seasons.json')))}
    rows = list(csv.DictReader(open(os.path.join(KIT, 'xpm', 'nba_player_seasons.csv'))))
    tot = defaultdict(float)
    vals = []
    for r in rows:
        if not r['blend'] or not r['year'].isdigit(): continue
        y = int(r['year'])
        v = VORX_K * (float(r['blend']) - VORX_REP) * float(r['mp']) / 48
        tot[y] += v
        vals.append((r['pid'], r['name'], y, ages.get((r['pid'], y)), v))
    car = {}
    for pid, nm, y, age, v in vals:
        c = car.setdefault(pid, {'name': nm, 's': []})
        c['s'].append([y, age, round(v / (tot[y] / 30), 4)])
    return car


def peak_share(seasons, upto=NBA_LAST):
    """mean of the best three seasons' share at ages 22-28 (0 for a season missing or below replacement)"""
    v = sorted((max(0.0, s) for y, a, s in seasons if a is not None and AGES[0] <= a <= AGES[1] and y <= upto), reverse=True)
    v += [0.0] * 3
    return sum(v[:3]) / 3


SEASON_G = {2012: 66, 2020: 70, 2021: 72}


def tier_of(bref, bbs):
    """realized FV for an NBA career the college link misses (prep-to-pro, overseas): the board's role ladder
    (scripts/cbb_link.py TIERS) on games, starts and rotation seasons; none of these 2009-25 careers made an All-NBA
    or All-Star team, so the All-NBA / All-Star rungs don't arise"""
    ss = bbs.get(bref, [])
    g = sum(x['g'] or 0 for x in ss)
    st = sum(1 for x in ss if (x['gs'] or 0) >= 0.5 * SEASON_G.get(x['year'], 82))
    rot = sum(1 for x in ss if (x['mp'] or 0) >= 1000 * SEASON_G.get(x['year'], 82) / 82)
    return 55 if st >= 6 else 50 if st >= 4 else 45 if st >= 2 else 40 if rot >= 3 else 35 if g >= 100 else 30 if g >= 1 else 20


def build_history():
    """the 2009-2025 On3 classes with each recruit's NBA peak share and first college team (scripts/data cache)"""
    car = nba_careers()
    bbs = defaultdict(list)
    for x in json.load(open(os.path.join(KIT, 'kit', 'bbref_nba_seasons.json'))): bbs[x['bref']].append(x)
    # the college link: kit rows carry the On3 consensus rank and class (cbb_link.py), the Barttorvik career and bref id
    kit = {}
    first = {}
    kitfv = {}                      # bref -> realized FV (the board's NBA role tier, scripts/cbb_link.py TIERS)
    net = defaultdict(float)        # team strength by season: minutes-weighted BPM summed over the roster
    tval = defaultdict(float)       # team college value by season (the xNIL split, college_value)
    tconf = {}
    col = defaultdict(dict)         # (class, On3 rank) -> {season: [games, minutes %, BPM]}, every D-I season (the college path)
    for r in csv.DictReader(open(os.path.join(KIT, 'kit', 'college_seasons_nba.csv'))):
        if r['bpm'] and r['min_per']:
            net[(int(r['year']), r['team'])] += float(r['bpm']) * float(r['min_per']) / 100
            tval[(int(r['year']), r['team'])] += college_value(float(r['min_per']), float(r['bpm']))
            tconf[(int(r['year']), r['team'])] = r['conf']
        if not r['rec_class'] or not r['on3rk']: continue
        k = (int(r['rec_class']), int(float(r['on3rk'])))
        y = int(r['year'])
        if r['bpm'] and r['min_per']:
            g, mp = float(r['gp'] or 0), float(r['min_per'])
            prev = col[k].get(y)
            if prev is None or g * mp > prev[0] * prev[1]: col[k][y] = [g, mp, round(float(r['bpm']), 2)]
        if k not in first or y < first[k][0]:
            first[k] = (y, r['team'], r['conf'], r['name'], r['nba_bref'] or None, r['dob'] or None)
        if r['nba_bref'] and r['realized_fv']: kitfv[r['nba_bref']] = int(float(r['realized_fv']))
    for (c, rk), (y, team, conf, nm, bref, dob) in first.items():
        kit[(c, rk)] = kit[(c, N.key(nm))] = {'name': nm, 'team': team, 'conf': conf, 'y1': y, 'bref': bref, 'dob': dob}
    # NBA players by name, with the class their age implies
    bp = []
    for pid, c in car.items():
        s0 = min((s for s in c['s'] if s[1] is not None), key=lambda s: s[0], default=None)
        if s0: bp.append({'id': pid, 'name': c['name'], 'cls': s0[0] - s0[1] + 17})
    M = N.Matcher(bp, name='name', team=None, pos=None, cls='cls', sport='basketball')
    out, how = [], Counter()
    used = set()
    for cls in range(2009, 2026):
        for r in load_on3(cls):
            row = compact(r, cls)
            k = kit.get((cls, row['rk']))
            if k and not N.same(k['name'], row['name']): k = None
            k = k or kit.get((cls, N.key(row['name'])))
            bref = k['bref'] if k else None
            if bref: how['college'] += 1
            else:
                m, h = M.find(row['name'], cls=lambda c, cls=cls: abs(c - cls) <= 1)
                if m and m['id'] not in used:
                    bref = m['id']; how['name'] += 1
            if bref: used.add(bref)
            row['bref'] = bref
            row['college'] = {'team': k['team'], 'conf': k['conf'], 'y1': k['y1']} if k else None
            # old for the class: 18 or older on Oct 26 of the senior year, the date and whole-year age On3 shows live
            if k and k.get('dob'):
                b = k['dob'][:10]
                row['old'] = 1 if (cls - 1 - int(b[:4]) - (b[5:] > '10-26')) >= 18 else 0
            row['nba'] = [s for s in car[bref]['s']] if bref in car else []
            row['rfv'] = kitfv.get(bref) or (tier_of(bref, bbs) if bref else 20)
            row['col'] = {str(y): v for y, v in sorted(col.get((cls, row['rk']), {}).items())}
            out.append(row)
    print('linked to NBA careers:', dict(how), 'of', len(out), 'recruits')
    # program strength, z-scored within each season (the season before a recruit arrives is what he chose on)
    teams = {}
    for y in sorted({y for y, _ in net}):
        v = {t: x for (yy, t), x in net.items() if yy == y}
        m, sd = np.mean(list(v.values())), np.std(list(v.values()))
        teams[str(y)] = {t: round((x - m) / sd, 3) for t, x in v.items()}
    # team college value by level, latest season (the xNIL split): mean roster value at each level
    ly = max(y for y, _ in tval)
    lv = defaultdict(list)
    for (y, t), v in tval.items():
        if y == ly: lv[level_of(tconf[(y, t)])].append(v)
    H = {'recruits': out, 'teams': teams, 'nilRef': {'season': ly, 'value': {k: round(float(np.mean(v)), 3) for k, v in lv.items()},
                                                    'n': {k: len(v) for k, v in lv.items()},
                                                    'conf': {t: c for (y, t), c in tconf.items() if y == ly}}}
    os.makedirs(os.path.dirname(HIST), exist_ok=True)
    with gzip.open(HIST, 'wt') as f: json.dump(H, f, separators=(',', ':'))
    return H


def history():
    if OFFLINE or not os.path.exists(os.path.join(KIT, 'kit', 'bbref_nba_seasons.json')):
        return json.load(gzip.open(HIST, 'rt'))
    return build_history()


# ---------------------------------------------------------------- drivers
US = set('AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR '
         'PA RI SC SD TN TX UT VT VA WA WV WI WY'.split())
CA_PROV = {'ON', 'QC', 'BC', 'AB', 'MB', 'SK', 'NS', 'NB', 'NL', 'PE'}
HIGH = {'ACC', 'B10', 'B12', 'SEC', 'BE', 'P12'}


def slug_map(H):
    """On3 school slug -> Barttorvik team, learned from recruits whose college career the kit links (most common pair)"""
    pairs = defaultdict(Counter)
    for r in H['recruits']:
        if r.get('team') and r.get('college'): pairs[r['team']][r['college']['team']] += 1
    # 3+ recruits agreeing (a single pair can be a recruit who signed with one school and enrolled at another)
    return {s: c.most_common(1)[0][0] for s, c in pairs.items() if c.most_common(1)[0][1] >= 3}


def lr(x): return -math.log(min(x, RANK_CAP)) if x else -math.log(RANK_CAP)


def raw_feats(r, prog, hm):
    rk = r['rk'] or RANK_CAP
    s = r.get('svc') or {}
    lk = [lr(v) for v in s.values() if v]
    g = pos_group(r['pos'])
    return {
        'lrk': lr(rk),
        'lrk2': lr(rk) ** 2,
        'lsvc': float(np.mean(lk)) if lk else lr(rk),
        'top25': max(0.0, math.log(25) - math.log(rk)),
        'top5': max(0.0, math.log(5) - math.log(rk)),
        'cons': r['cons'] or 80.0,
        'fsp': 1.0 if r.get('fsp') else 0.0,
        'svc_sd': float(np.std(lk)) if len(lk) >= 2 else 0.0,
        'n_svc': float(len(lk)),
        'espn_gap': lr(s['espn']) - lr(rk) if s.get('espn') else 0.0,
        'g247_gap': lr(s['247']) - lr(rk) if s.get('247') else 0.0,
        'on3_gap': lr(s['on3']) - lr(rk) if s.get('on3') else 0.0,
        'ht': float(r['ht']) if r.get('ht') else None,
        'wt': float(r['wt']) if r.get('wt') else None,
        'guard': 1.0 if g == 'G' else 0.0,
        'big': 1.0 if g == 'B' else 0.0,
        'intl': 0.0 if (r.get('state') in US) else 1.0,
        'old': r.get('old'),
        'prog': prog,
        'hm': hm,
    }


# not 'n_svc' (services ranking him): early lists are ranked by fewer services (2029: On3 alone), so it would mark
# down a live class for when it was ranked, not for the player
CANDS = ['lrk2', 'lsvc', 'top25', 'top5', 'cons', 'fsp', 'svc_sd', 'espn_gap', 'g247_gap', 'on3_gap', 'ht_pos', 'wt_ht', 'guard', 'big',
         'intl', 'prog', 'hm', 'old', 'interest', 'prep', 'commit_m', 'commit_nov']
LABEL = {'lrk': 'consensus rank', 'lrk2': 'consensus rank, curve', 'lsvc': 'mean service rank', 'top25': 'top-25 recruit', 'top5': 'top-5 recruit', 'cons': 'consensus rating',
         'fsp': '5-star+', 'svc_sd': 'services disagree', 'n_svc': 'services ranking him', 'espn_gap': 'ESPN vs consensus',
         'g247_gap': '247 vs consensus', 'on3_gap': 'On3 vs consensus', 'ht_pos': 'height for position',
         'wt_ht': 'weight for height', 'guard': 'guard', 'big': 'big', 'intl': 'from abroad', 'prog': 'program strength',
         'hm': 'high-major program', 'old': 'old for the class', 'interest': 'schools recruiting him (vs rank)',
         'prep': 'prep power (ranked recruits from his school, 5 prior classes)', 'commit_m': 'months committed before senior Nov 1',
         'commit_nov': 'committed by senior Nov 1'}
HS_BY = defaultdict(Counter)        # class -> On3 high-school slug -> ranked recruits (prep power), set in main()


def extras(rows, out):
    """the On3 recruitment fields (Oct 31 2026 tests): schools recruiting him as a residual on log rank within his class
    (counts run higher in later classes), ranked recruits from his school in the five prior classes, and when he
    committed against November 1 of his senior year. A class whose senior November is still ahead gets the
    training mean for the commit terms (not yet known)."""
    today = __import__('datetime').date.today()
    by = defaultdict(list)
    for r, f in zip(rows, out):
        x = r.get('x') or {}
        f['interest'] = math.log1p(x.get('interest') or 0)
        f['prep'] = math.log1p(sum(HS_BY[y][x['hs']] for y in range(r['cls'] - 5, r['cls'])) if x.get('hs') else 0)
        nov1 = __import__('datetime').date(r['cls'] - 1, 11, 1)
        if nov1 > today: f['commit_m'] = f['commit_nov'] = None
        elif x.get('commit'):
            d = __import__('datetime').date.fromisoformat(x['commit'])
            f['commit_m'] = max(-6.0, min(18.0, (nov1 - d).days / 30.4)); f['commit_nov'] = 1.0 if d <= nov1 else 0.0
        else: f['commit_m'], f['commit_nov'] = -6.0, 0.0
        by[r['cls']].append(f)
    for fs in by.values():
        b = np.polyfit([f['lrk'] for f in fs], [f['interest'] for f in fs], 1) if len(fs) > 10 else [0.0, float(np.mean([f['interest'] for f in fs]))]
        for f in fs: f['interest'] -= float(np.polyval(b, f['lrk']))


def frame(rows, smap, teams, ref=None):
    """feature dicts for rows; ref holds the position height means and the program imputation (from the training pool)"""
    out = []
    for r in rows:
        prog = hm = None
        tm = (r.get('college') or {}).get('team') or smap.get(r.get('team'))
        y = (r.get('college') or {}).get('y1', r['cls'] + 1) - 1
        if tm:
            tz = teams.get(str(min(y, max(int(k) for k in teams))), {})
            prog = tz.get(tm)
            conf = (r.get('college') or {}).get('conf')
            hm = 1.0 if conf in HIGH else (0.0 if conf else None)
        out.append(raw_feats(r, prog, hm))
    extras(rows, out)
    if ref is None:
        ref = {}
        for g in ('guard', 'big', 'wing'):
            hs = [f['ht'] for f in out if f['ht'] and (f[g] if g != 'wing' else not (f['guard'] or f['big']))]
            ref['ht_' + g] = (float(np.mean(hs)), float(np.std(hs)) or 1.0)
        pts = [(f['lrk'], f['prog']) for f in out if f['prog'] is not None]
        b = np.polyfit([p[0] for p in pts], [p[1] for p in pts], 1)
        ref['prog'] = [float(b[0]), float(b[1])]
        hh = [(f['lrk'], f['hm']) for f in out if f['hm'] is not None]
        b = np.polyfit([p[0] for p in hh], [p[1] for p in hh], 1)
        ref['hm'] = [float(b[0]), float(b[1])]
        wh = [(f['ht'], f['wt']) for f in out if f['ht'] and f['wt']]
        ref['wt'] = [float(x) for x in np.polyfit([p[0] for p in wh], [p[1] for p in wh], 1)]
        ref['old'] = float(np.mean([f['old'] for f in out if f['old'] is not None]))
        for c in ('commit_m', 'commit_nov'): ref[c] = float(np.mean([f[c] for f in out if f[c] is not None]))
    for f in out:
        g = 'guard' if f['guard'] else 'big' if f['big'] else 'wing'
        m, sd = ref['ht_' + g]
        f['ht_pos'] = (f['ht'] - m) / sd if f['ht'] else 0.0
        f['wt_ht'] = (f['wt'] - np.polyval(ref['wt'], f['ht'])) / 15 if f['ht'] and f['wt'] else 0.0
        # no school yet (uncommitted, or never enrolled at a D-I school): the program a recruit of his rank lands at
        if f['prog'] is None: f['prog'] = float(np.polyval(ref['prog'], f['lrk']))
        if f['hm'] is None: f['hm'] = float(min(1, max(0, np.polyval(ref['hm'], f['lrk']))))
        if f['old'] is None: f['old'] = ref['old']
        for c in ('commit_m', 'commit_nov'):
            if f[c] is None: f[c] = ref[c]
    return out, ref


# ---------------------------------------------------------------- the hurdle
def std_fit(X):
    m, s = X.mean(0), X.std(0)
    s[s == 0] = 1
    return m, s


def logit_fit(X, y, lam=1.0):
    Xb = np.c_[np.ones(len(X)), X]
    b = np.zeros(Xb.shape[1])
    pen = np.r_[0, np.full(X.shape[1], lam)]
    for _ in range(50):
        p = 1 / (1 + np.exp(-Xb @ b))
        W = p * (1 - p)
        H = Xb.T @ (Xb * W[:, None]) + np.diag(pen)
        g = Xb.T @ (y - p) - pen * b
        d = np.linalg.solve(H, g)
        b += d
        if np.abs(d).max() < 1e-8: break
    return b


def ridge_fit(X, y, lam=1.0):
    Xb = np.c_[np.ones(len(X)), X]
    pen = np.diag(np.r_[0, np.full(X.shape[1], lam)])
    b = np.linalg.solve(Xb.T @ Xb + pen, Xb.T @ y)
    return b, float(np.sqrt(np.mean((y - Xb @ b) ** 2)))


class Hurdle:
    def __init__(self, cols_p, cols_v):
        self.cp, self.cv = cols_p, cols_v

    def fit(self, F, ts):
        y = (ts > 0).astype(float)
        Xp = np.array([[f[c] for c in self.cp] for f in F])
        self.mp, self.sp = std_fit(Xp)
        self.bp = logit_fit(np.clip((Xp - self.mp) / self.sp, -4, 4), y)
        pos = ts > 0
        Xv = np.array([[f[c] for c in self.cv] for f in F])[pos]
        self.mv, self.sv = std_fit(Xv)
        Z = np.clip((Xv - self.mv) / self.sv, -4, 4)
        self.bv, self.s = ridge_fit(Z, np.log(ts[pos]), lam=2.0)
        # the log share's residuals are skewed left (a few minutes above replacement is a tiny share), so the mean and
        # the quantiles come from the residuals themselves (Duan's smearing), not a normal: exp(s^2/2) is 9.5, smearing 3.8
        self.res = np.sort(np.log(ts[pos]) - (self.bv[0] + Z @ self.bv[1:]))
        self.smear = float(np.mean(np.exp(self.res)))
        return self

    def parts(self, F, shrink=1.0):
        Xp = np.clip((np.array([[f[c] for c in self.cp] for f in F]) - self.mp) / self.sp, -4, 4)
        Xv = np.clip((np.array([[f[c] for c in self.cv] for f in F]) - self.mv) / self.sv, -4, 4)
        p = 1 / (1 + np.exp(-(self.bp[0] + shrink * (Xp @ self.bp[1:]))))
        mu = self.bv[0] + shrink * (Xv @ self.bv[1:])
        return p, mu

    def ets(self, F, shrink=1.0):
        p, mu = self.parts(F, shrink)
        return p * np.exp(mu) * self.smear

    def above(self, p, mu, ts):
        """P(share >= ts) for one recruit"""
        return p * float(np.mean(self.res >= math.log(ts) - mu))

    def quantile(self, p, mu, q):
        """the q-quantile share (0 below the no-value mass)"""
        if q <= 1 - p: return 0.0
        return math.exp(mu + float(np.quantile(self.res, (q - (1 - p)) / p)))


def rankdata(a):
    """ranks with ties averaged (most recruits tie at 0 NBA value)"""
    a = np.asarray(a, float)
    o = np.argsort(a, kind='mergesort')
    r = np.empty(len(a))
    r[o] = np.arange(len(a))
    for v in np.unique(a):
        m = a == v
        if m.sum() > 1: r[m] = r[m].mean()
    return r


def spearman(a, b):
    return float(np.corrcoef(rankdata(a), rankdata(b))[0, 1])


def cv(F, ts, cls, cp, cv_, folds):
    """held-out class predictions: P, mu (log share given > 0), E[TS]"""
    P, MU, E = np.zeros(len(F)), np.zeros(len(F)), np.zeros(len(F))
    for c in folds:
        tr = cls != c; te = cls == c
        m = Hurdle(cp, cv_).fit([F[i] for i in np.where(tr)[0]], ts[tr])
        Ft = [F[i] for i in np.where(te)[0]]
        p, mu = m.parts(Ft)
        P[te], MU[te], E[te] = p, mu, p * np.exp(mu) * m.smear
    return P, MU, E


def paired(a, b, cls, folds):
    """per-class mean of (a - b), its t across classes and the classes where a < b (lower is better)"""
    d = np.array([np.mean(a[cls == c] - b[cls == c]) for c in folds])
    t = d.mean() / (d.std(ddof=1) / math.sqrt(len(d))) if d.std(ddof=1) > 0 else 0.0
    return float(d.mean()), float(t), int((d < 0).sum())


def select(F, ts, cls, folds):
    """forward selection, each part on its own loss, from the consensus rank alone"""
    y = (ts > 0).astype(float)
    pos = ts > 0
    lts = np.log(np.where(pos, ts, 1))

    def losses(cp, cv_):
        P, MU, _ = cv(F, ts, cls, cp, cv_, folds)
        P = np.clip(P, 1e-6, 1 - 1e-6)
        return -(y * np.log(P) + (1 - y) * np.log(1 - P)), np.where(pos, (lts - MU) ** 2, 0.0)

    cp, cv_ = ['lrk'], ['lrk']
    lp, lv = losses(cp, cv_)
    evid, tests = [], []
    for part in ('p', 'v'):
        rnd = 0
        while True:
            rnd += 1
            best = None
            for c in CANDS:
                if c in (cp if part == 'p' else cv_): continue
                tp, tv = (cp + [c], cv_) if part == 'p' else (cp, cv_ + [c])
                a, b = losses(tp, tv)
                if part == 'p': d, t, w = paired(a, lp, cls, folds)
                else:
                    m = pos
                    d, t, w = paired(np.where(m, b, 0), np.where(m, lv, 0), cls, folds)
                if VERBOSE: print(f'    {part} +{c:9s} gain {-d:+.5f} t {-t:+.2f} {w}/{len(folds)}')
                if rnd == 1: tests.append({'part': part, 'driver': LABEL[c], 't': round(-t, 2), 'classes': w})
                if t <= -2 and w >= math.ceil(0.7 * len(folds)) and (best is None or t < best[2]): best = (c, d, t, w, a, b)
            if not best: break
            c, d, t, w, a, b = best
            evid.append({'part': part, 'driver': LABEL[c], 'key': c, 'gain': round(-d, 5), 't': round(-t, 2), 'classes': w})
            print(f'  keep {part} {c}: gain {-d:.5f} t {-t:.2f} {w}/{len(folds)}')
            if part == 'p': cp.append(c); lp = a
            else: cv_.append(c); lv = b
    return cp, cv_, evid, tests


def summary(E, ts, cls, folds):
    rho = [spearman(E[cls == c], ts[cls == c]) for c in folds]
    return float(np.mean(rho)), rho


def main():
    H = history()
    for r in H['recruits']:
        if (r.get('x') or {}).get('hs'): HS_BY[r['cls']][r['x']['hs']] += 1
    for c in [NOW_CLASS] + LIVE:
        for r in load_on3(c):
            if r.get('hsSlug'): HS_BY[c][r['hsSlug']] += 1
    smap = slug_map(H)
    teams = H['teams']
    rows = [r for r in H['recruits'] if r['cls'] in TRAIN + FORWARD]
    for r in rows: r['ts'] = float(r['rfv'] - 20)
    F, ref = frame(rows, smap, teams)
    cls = np.array([r['cls'] for r in rows])
    ts = np.array([r['ts'] for r in rows])
    tr = np.isin(cls, TRAIN)
    Ftr = [F[i] for i in np.where(tr)[0]]
    print('train', tr.sum(), 'recruits;', int((ts[tr] > 0).sum()), 'reached the NBA;',
          'by class', {c: int((ts[cls == c] > 0).sum()) for c in TRAIN + FORWARD})
    cp, cv_, evid, tests = select(Ftr, ts[tr], cls[tr], TRAIN)
    print('kept P:', cp, 'kept value:', cv_)

    # held-out scoring: the kept model vs the consensus rank alone (both hurdles, same folds)
    _, _, E0 = cv(Ftr, ts[tr], cls[tr], ['lrk'], ['lrk'], TRAIN)
    _, _, E1 = cv(Ftr, ts[tr], cls[tr], cp, cv_, TRAIN)
    r0, rr0 = summary(E0, ts[tr], cls[tr], TRAIN)
    r1, rr1 = summary(E1, ts[tr], cls[tr], TRAIN)
    d = np.array(rr1) - np.array(rr0)
    tt = float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))) if d.std(ddof=1) > 0 else 0.0
    print(f'held-out Spearman with the realized FV: rank only {r0:.3f}, model {r1:.3f} (t {tt:.2f}, {(d > 0).sum()}/{len(d)})')
    M = Hurdle(cp, cv_).fit(Ftr, ts[tr])
    return H, smap, teams, rows, F, ref, cls, ts, tr, M, cp, cv_, evid, tests, (r0, r1, tt, int((d > 0).sum()), rr0, rr1, E1)


# ---------------------------------------------------------------- college path: years 1-3 in D-I
# What a recruit does in college before the NBA question settles: per college year k (1-3), the chance he plays D-I
# that season (5+ games, any school), his share of team minutes and BPM if he does, and his college value (minutes x
# BPM above replacement; the xNIL split). NIL-era seasons only (2021-22 on), as the transfer model: the portal moved
# freshman minutes (ranks 51-150 played 31% of minutes as freshmen through 2019, 21% since). Drivers enter as the FV
# model's do (classes held out, t >= 2, 70% of classes). 'old' is a candidate only given he plays: his birth date comes
# from his college line, so it is missing for most recruits who never play D-I and would leak P(plays).
PATH_ERA = 2022
PATH_K = (1, 2, 3)
PATH_BASE = ['top25', 'lrk2', 'big', 'guard', 'ht_pos', 'prog', 'hm', 'intl']
PATH_CANDS = {'on': PATH_BASE, 'min': PATH_BASE + ['old'], 'bpm': PATH_BASE + ['old'], 'v': PATH_BASE}


def path_rows(rows, F, k):
    D = []
    for r, f in zip(rows, F):
        y = r['cls'] + k
        if y < PATH_ERA or y > NBA_LAST: continue
        s = (r.get('col') or {}).get(str(y))
        on = bool(s and s[0] >= 5)
        D.append({'cls': r['cls'], 'f': f, 'on': 1.0 if on else 0.0, 'min': s[1] if on else 0.0, 'bpm': s[2] if on else 0.0,
                  'v': college_value(s[1], s[2]) if on else 0.0})
    return D


class PathPart:
    """one part of the path: 'on' logistic, 'min' / 'bpm' ridge given he plays, 'v' Poisson (log link) on value"""
    def __init__(self, part, cols): self.part, self.cols = part, cols

    def fit(self, D):
        X = np.array([[d['f'][c] for c in self.cols] for d in D])
        self.m, self.s = std_fit(X)
        Z = np.clip((X - self.m) / self.s, -4, 4)
        if self.part == 'on': self.b = logit_fit(Z, np.array([d['on'] for d in D]))
        elif self.part in ('min', 'bpm'):
            on = np.array([d['on'] for d in D]) > 0
            self.b, _ = ridge_fit(Z[on], np.array([d[self.part] for d in D])[on], lam=2.0)
        else:
            y = np.array([d['v'] for d in D]); Xb = np.c_[np.ones(len(Z)), Z]
            b = np.zeros(Xb.shape[1]); b[0] = math.log(y.mean())
            pen = np.r_[0, np.ones(len(b) - 1)]
            for _ in range(60):
                mu = np.exp(Xb @ b)
                d = np.linalg.solve(Xb.T @ (Xb * mu[:, None]) + np.diag(pen), Xb.T @ (y - mu) - pen * b)
                b += d
                if np.abs(d).max() < 1e-8: break
            self.b = b
        return self

    def predict(self, F):
        Z = np.clip((np.array([[f[c] for c in self.cols] for f in F]) - self.m) / self.s, -4, 4)
        x = self.b[0] + Z @ self.b[1:]
        return 1 / (1 + np.exp(-x)) if self.part == 'on' else np.exp(x) if self.part == 'v' else x


def path_loss(D, pred, part):
    if part == 'on':
        y = np.array([d['on'] for d in D]); p = np.clip(pred, 1e-6, 1 - 1e-6)
        return -(y * np.log(p) + (1 - y) * np.log(1 - p))
    if part in ('min', 'bpm'):
        on = np.array([d['on'] for d in D]) > 0
        return np.where(on, (np.array([d[part] for d in D]) - pred) ** 2, 0.0)
    y = np.array([d['v'] for d in D]); m = np.maximum(pred, 1e-9)
    return 2 * (np.where(y > 0, y * np.log(np.maximum(y, 1e-12) / m), 0.0) - (y - m))


def path_cv(D, part, cols):
    cl = np.array([d['cls'] for d in D]); pred = np.zeros(len(D))
    for c in sorted(set(cl)):
        te = np.where(cl == c)[0]
        pred[te] = PathPart(part, cols).fit([d for d, x in zip(D, cl) if x != c]).predict([D[i]['f'] for i in te])
    return pred, cl


def path_fit(rows, F):
    """per year: forward selection for each part from the consensus rank, held-out tests, final fits on all NIL-era rows"""
    models, tests = {}, {}
    for k in PATH_K:
        D = path_rows(rows, F, k)
        folds = sorted(set(d['cls'] for d in D))
        models[k], tests[k] = {}, {'n': len(D), 'plays': round(float(np.mean([d['on'] for d in D])), 3), 'classes': [folds[0], folds[-1]], 'parts': {}}
        for part in ('on', 'min', 'bpm', 'v'):
            cols = ['lrk']
            pred, cl = path_cv(D, part, cols)
            base = path_loss(D, pred, part)
            # the null (class mean) for the record: how much the rank alone tells
            null = path_loss(D, np.full(len(D), (np.mean([d[part] for d in D if d['on']]) if part in ('min', 'bpm') else np.mean([d[part] for d in D]))), part)
            rank_only = base.copy()
            kept = []
            while True:
                best = None
                for c in PATH_CANDS[part]:
                    if c in cols: continue
                    pr, _ = path_cv(D, part, cols + [c])
                    l = path_loss(D, pr, part)
                    d_, t, w = paired(l, base, cl, folds)
                    if t <= -2 and w >= math.ceil(0.7 * len(folds)) and (best is None or t < best[1]): best = (c, t, w, l, pr)
                if not best: break
                cols.append(best[0]); base = best[3]; pred = best[4]
                kept.append({'driver': LABEL[best[0]], 't': round(-best[1], 2), 'classes': best[2]})
            on = np.array([d['on'] for d in D]) > 0
            n = on.sum() if part in ('min', 'bpm') else len(D)
            t0 = {'kept': kept, 'cols': cols, 'null': round(float(null.sum() / n), 4), 'rank': round(float(rank_only.sum() / n), 4),
                  'model': round(float(base.sum() / n), 4)}
            if part == 'on':
                y = np.array([d['on'] for d in D]); o = np.argsort(pred); rr = np.empty(len(y)); rr[o] = np.arange(1, len(y) + 1)
                t0['auc'] = round(float((rr[y > 0].sum() - y.sum() * (y.sum() + 1) / 2) / (y.sum() * (len(y) - y.sum()))), 3)
            if part in ('min', 'bpm'):
                for kk in ('null', 'rank', 'model'): t0[kk] = round(math.sqrt(t0[kk]), 2)   # RMSE
            tests[k]['parts'][part] = t0
            models[k][part] = PathPart(part, cols).fit(D)
        print(f'  path year {k}: n {len(D)}, kept', {p: tests[k]['parts'][p]['cols'] for p in tests[k]['parts']})
    return models, tests


def path_of(models, F):
    """per recruit, years 1-3: P(plays D-I), minutes % and BPM if he plays, expected value"""
    out = [[] for _ in F]
    for k in PATH_K:
        m = models[k]
        p, mn, bp, v = (m[x].predict(F) for x in ('on', 'min', 'bpm', 'v'))
        for i in range(len(F)):
            out[i].append({'on': round(float(p[i]), 3), 'min': round(float(np.clip(mn[i], 0, 100)), 1), 'bpm': round(float(bp[i]), 1),
                           'v': round(float(v[i]), 3)})
    return out


# ---------------------------------------------------------------- xNIL
def xnil_price(H, teams, tm, conf, f, ref):
    """dollars a unit of college value draws at his school: the level's program budget (tilted by program strength,
    normalized within the level) over the level's mean roster value. No school yet: the levels mixed by the chance a
    recruit of his rank lands at a high-major, at the program strength a recruit of his rank lands at."""
    nr = H['nilRef']; ly = str(nr['season'])
    tz = teams.get(ly, {})
    norm = {}
    for L in ('HM', 'MM', 'LM'):
        zs = [z for t, z in tz.items() if level_of(nr.get('conf', {}).get(t)) == L] if nr.get('conf') else []
        norm[L] = float(np.mean(np.exp(XNIL['tilt'] * np.array(zs)))) if zs else 1.0
    def at(L, z): return XNIL[L] * math.exp(XNIL['tilt'] * z) / norm[L] / nr['value'][L]
    if tm: return at(level_of(conf), tz.get(tm, 0.0))
    return f['hm'] * at('HM', f['prog']) + (1 - f['hm']) * at('MM', 0.0)


# ---------------------------------------------------------------- ARK stars
# Our 1-5 stars for a recruit: his FV (the held-out expected outcome) cut at outcome bands, as the football ARK stars
# (scripts/cfb_recruit_fit.py ark_stars). Bands: 5 = 2+ seasons as an NBA starter (FV 45+), 4 = reached the NBA (30+),
# 3 = a D-I season as a starter (60%+ of minutes, 10+ games) at BPM +3 or better, 2 = played D-I (5+ games), 1 = never
# played D-I; 5-star+ on top (FV 55+: All-Star or 6+ seasons as a starter). Two cut rules, backtested with whole classes
# held out: 'share' gives each star the industry's share of the ranked pool; 'band' fits the cuts to the bands
# (quadratic weighted kappa). The rule with the higher R2 of realized FV on star is used.
PLUS_HOLD = 0.03   # 5-star+ count a class: the most whose held-out hit rate on FV 55+ stays within 3 points of the rarest cut's


def cut(s, c): return 1 + np.searchsorted(np.asarray(c), s, side='right')


def qwk(a, b, n=5):
    O = np.zeros((n, n))
    for x, y in zip(a, b): O[x - 1, y - 1] += 1
    W = np.array([[(i - j) ** 2 for j in range(n)] for i in range(n)]) / (n - 1) ** 2
    E = np.outer(O.sum(1), O.sum(0)) / O.sum()
    return float(1 - (W * O).sum() / (W * E).sum())


def fit_band(s, band, n=5):
    qs = np.quantile(s, np.linspace(0.01, 0.995, 200))
    c = list(np.quantile(s, [1 - np.mean(band >= t) for t in range(2, n + 1)]))
    best = qwk(cut(s, c), band, n)
    for _ in range(4):
        for i in range(n - 1):
            lo = c[i - 1] if i else -np.inf; hi = c[i + 1] if i < n - 2 else np.inf
            for q in qs:
                if not lo < q < hi: continue
                t = c[:i] + [q] + c[i + 1:]; v = qwk(cut(s, t), band, n)
                if v > best: best, c = v, t
    return c


def band_of(r):
    if r['rfv'] >= 55: return 6
    if r['rfv'] >= 45: return 5
    if r['rfv'] >= 30: return 4
    ss = (r.get('col') or {}).values()
    if any(x[0] >= 10 and x[1] >= 60 and x[2] >= 3 for x in ss): return 3
    if any(x[0] >= 5 for x in ss): return 2
    return 1


def ark_stars(rows, E, cls, folds):
    """rows: training recruits; E: their held-out expected FV"""
    s = np.asarray(E, float); real = np.array([float(r['rfv']) for r in rows])
    band6 = np.array([band_of(r) for r in rows]); band = np.minimum(band6, 5)
    ind = np.array([max(1, min(5, r['stars'] or 1)) for r in rows])
    share = [float(np.mean(ind == t)) for t in (1, 2, 3, 4, 5)]
    def cuts(i, scheme): return list(np.quantile(s[i], np.cumsum(share)[:4])) if scheme == 'share' else fit_band(s[i], band[i])
    def r2_of(st):
        sse = sst = 0.0; rho = []
        for c in folds:
            a = cls == c
            mu = {t: real[~a][st[~a] == t].mean() for t in set(st[~a])}
            pred = np.array([mu.get(t, real[~a].mean()) for t in st[a]])
            sse += float(((real[a] - pred) ** 2).sum()); sst += float(((real[a] - real[a].mean()) ** 2).sum())
            rho.append(spearman(st[a], real[a]))
        return round(1 - sse / sst, 4), round(float(np.mean(rho)), 4)
    def held(fn):
        st = np.zeros(len(rows), float)
        for c in folds:
            te = np.where(cls == c)[0]; tr = np.where(cls != c)[0]
            st[te] = fn(tr, te)
        return st
    out = {'bands': {str(b): round(float(np.mean(band6 == b)), 4) for b in range(1, 7)}, 'share': [round(x, 4) for x in share], 'schemes': {}}
    for scheme in ('industry', 'share', 'band'):
        st = held(lambda tr, te: ind[te] if scheme == 'industry' else cut(s[te], cuts(tr, scheme))).astype(int)
        r2, rho = r2_of(st)
        tiers = []
        for t in (5, 4, 3, 2, 1):
            i = st == t
            tiers.append({'stars': t, 'n': int(i.sum()), 'share': round(float(i.mean()), 4), 'fv': round(float(real[i].mean()), 1) if i.any() else None,
                          'nba': round(float(np.mean(band[i] >= 4)), 3) if i.any() else None, 'd1': round(float(np.mean(band[i] >= 2)), 3) if i.any() else None,
                          'starter': round(float(np.mean(band[i] >= 5)), 3) if i.any() else None})
        out['schemes'][scheme] = {'r2': r2, 'rho': rho, 'qwk': round(qwk(st, band), 4), 'tiers': tiers}
    pick = max(('share', 'band'), key=lambda x: out['schemes'][x]['r2'])
    out['pick'] = pick
    c5 = [float(x) for x in cuts(np.arange(len(rows)), pick)]
    # 5-star+: the top cut moved to a given number of recruits a class, scored the same way; its hit rate on FV 55+
    per_cls = len(rows) / len(folds)
    sweep = []
    for per in (1, 2, 3, 5, 8, 12):
        st = held(lambda tr, te: cut(s[te], cuts(tr, pick) + [max(float(np.quantile(s[tr], 1 - per / per_cls)), cuts(tr, pick)[-1] + 1e-6)])).astype(int)
        j = st == 6
        sweep.append({'perClass': per, 'r2': r2_of(st)[0], 'n': int(j.sum()), 'elite': round(float(np.mean(band6[j] == 6)), 3) if j.any() else None,
                      'starter': round(float(np.mean(band6[j] >= 5)), 3) if j.any() else None, 'fv': round(float(real[j].mean()), 1) if j.any() else None,
                      'cut': round(float(np.quantile(s, 1 - per / per_cls)), 2)})
    out['plusSweep'] = sweep
    PLUS_PER = max(x['perClass'] for x in sweep if x['elite'] is not None and x['elite'] >= sweep[0]['elite'] - PLUS_HOLD)
    out['plusPer'] = PLUS_PER
    c6 = c5 + [max(next(x['cut'] for x in sweep if x['perClass'] == PLUS_PER), c5[-1] + 1e-6)]
    out['cuts'] = [round(x, 2) for x in c6]
    # half stars (1.5-4.5): inside each tier, where a monotone fit of realized FV on score passes the midpoint between
    # the tier's mean FV and the next tier's (kept inside the tier's middle half)
    def halves(i, c):
        st = cut(s[i], c[:4]); mu = [real[i][st == t].mean() if (st == t).any() else np.nan for t in (1, 2, 3, 4, 5)]
        o = np.argsort(s[i]); xs = s[i][o]; ys = real[i][o]
        bins = np.array_split(np.arange(len(xs)), 40); bx = np.array([xs[b].mean() for b in bins]); by = np.maximum.accumulate([ys[b].mean() for b in bins])
        h = []
        for t in range(4):
            lo = c[t - 1] if t else xs[0]; hi = c[t]
            goal = (mu[t] + mu[t + 1]) / 2 if not (np.isnan(mu[t]) or np.isnan(mu[t + 1])) else None
            x = float(np.interp(goal, by + np.arange(len(by)) * 1e-9, bx)) if goal is not None else (lo + hi) / 2
            h.append(min(max(x, lo + 0.25 * (hi - lo)), lo + 0.75 * (hi - lo)))
        return h
    def rate(x, c, h): t = cut(x, c); return t + 0.5 * ((t <= 4) & (x >= np.asarray(h + [np.inf] * 2)[np.clip(t - 1, 0, 5)]))
    def c6_of(tr): c = cuts(tr, pick); return c + [max(float(np.quantile(s[tr], 1 - PLUS_PER / per_cls)), c[-1] + 1e-6)]
    whole = held(lambda tr, te: cut(s[te], c6_of(tr)))
    half = held(lambda tr, te: rate(s[te], c6_of(tr), halves(tr, c6_of(tr))))
    out['half'] = [round(x, 2) for x in halves(np.arange(len(rows)), c6)]
    lv = []
    for v in sorted(set(half)):
        j = half == v
        lv.append({'stars': float(v), 'share': round(float(np.mean(j)), 4), 'fv': round(float(real[j].mean()), 1), 'nba': round(float(np.mean(band[j] >= 4)), 3)})
    out['halfTest'] = {'r2Whole': r2_of(whole.astype(int))[0], 'r2Half': r2_of(half)[0], 'levels': lv}
    return out


def ark_of(st, x):
    """ARK stars for an FV: 1-5 in halves, 6 = 5-star+"""
    c = st['cuts']; t = int(cut(np.array([x]), c)[0])
    if t <= 4 and x >= (st['half'] + [math.inf] * 2)[t - 1]: return t + 0.5
    return t


# held-out checks run Oct 31 2026 (thread "Build detailed CBB recruits board"), not shipped; shown on the model tab
RESEARCH = {
    # the top-5 recruits run under (held-out mean FV 5.8 below realized): an isotonic map of the hurdle's FV, fit inside
    # each training fold (nested), fixes the bias but not the error, so the gate (t <= -2, 6 of 8 classes) holds it back
    'isotonic': {'mse': [59.85, 59.77], 't': -0.12, 'wins': 4, 'top5': [-5.8, -0.6], 'mse10': [59.38, 59.72], 't10': 0.64, 'wins10': 2},
    # other forms for the top: FV-linear value part with a top-25 hinge (best) and an ordered-free kernel on log rank
    'linear_top25': {'mse': [59.85, 59.53], 't': -1.18, 'wins': 6, 'top5': [-5.8, -3.1]},
    'kernel': {'mse': [59.85, 61.56], 't': 2.56, 'wins': 2},
    # On3's age field is a leak (listed for 64% of NBA recruits, 1% of the rest); the kept birth-date term ('old', from the
    # college line) is known for 97% / 89% and holds on the known-only rows (t 2.71, 7 of 8)
    'age_on3': [0.642, 0.012], 'old_known': {'t': 2.71, 'wins': 7, 'n': 1817},
}


# ---------------------------------------------------------------- live classes
def reliability(H):
    """how far a class's ranking has settled: the mean correlation between services' -ln rank on the consensus top 150,
    as a share of the same pairs' correlation in finished classes (2018-25). Errors in the rank attenuate its weight
    by that ratio (errors in variables), so a live class's drivers are scaled by it."""
    def pair_r(rows):
        out = {}
        for a, b in (('247', 'espn'), ('on3', 'espn'), ('247', 'on3')):
            xy = [(lr(r['svc'][a]), lr(r['svc'][b])) for r in rows if (r['rk'] or 999) <= 150 and r['svc'].get(a) and r['svc'].get(b)]
            if len(xy) >= 25: out[a + '|' + b] = float(np.corrcoef(*zip(*xy))[0, 1])
        return out
    fin = defaultdict(list)
    for c in range(2018, 2026):
        for k, v in pair_r([r for r in H['recruits'] if r['cls'] == c]).items(): fin[k].append(v)
    fin = {k: float(np.mean(v)) for k, v in fin.items()}
    rel = {}
    for c in [NOW_CLASS] + LIVE:
        live = pair_r([compact(r, c) for r in load_on3(c)])
        ks = [k for k in live if k in fin]
        rel[c] = {'pairs': {k: [round(live[k], 3), round(fin[k], 3)] for k in ks},
                  'shrink': round(min(1.0, float(np.mean([live[k] / fin[k] for k in ks]))) if ks else 0.6, 3)}
    return rel


def board_teams():
    d = json.load(open(os.path.join(ROOT, 'static', 'data', 'cbb-all.json')))
    i = {c: k for k, c in enumerate(d['cols'])}
    out = {}
    for r in d['rows']:
        out.setdefault(r[i['team']], {'logo': r[i['logo']], 'conf': r[i['conf']]})
    return out


TEAM_SLUG = {'detroit-titans': 'Detroit Mercy', 'albany-great-danes': 'UAlbany', 'ipfw-mastodons': 'Purdue Fort Wayne', 'queens-royals': 'Queens',
             'lindenwood-university-lions': 'Lindenwood'}


def team_of(slug, smap, bt):
    """On3 school slug -> the board's team: the school words of the slug (the mascot dropped), else the learned map"""
    if not slug: return None
    if TEAM_SLUG.get(slug) in bt: return TEAM_SLUG[slug]
    w = slug.split('-')
    for n in range(len(w) - 1, 0, -1):
        k = N.team_key(' '.join(w[:n]))
        for t in bt:
            if N.team_key(t) == k: return t
    if slug in smap and smap[slug] in bt: return smap[slug]
    return None


def why(M, f, ref_f):
    """each kept driver's share of the FV, against the average recruit of the training classes: the FV moves this much
    from the average recruit when the driver alone takes his value (rows add up to his FV minus the average's)"""
    rows = []
    base = dict(ref_f)
    e0 = float(M.ets([base])[0])
    cur = dict(base)
    for c in sorted(set(M.cp + M.cv), key=lambda c: (c != 'lrk', c)):
        nxt = dict(cur); nxt[c] = f[c]
        rows.append([LABEL[c], round(fv_of(float(M.ets([nxt])[0])) - fv_of(float(M.ets([cur])[0])), 1)])
        cur = nxt
    return {'fv0': round(fv_of(e0), 1), 'rows': rows}


def grade(M, F, shrink):
    p, mu = M.parts(F, shrink)
    out = []
    for pi, mi in zip(p, mu):
        pi, mi = float(pi), float(mi)
        e = pi * math.exp(mi) * M.smear
        out.append({'p': round(pi, 3), 'ets': round(e, 5), 'fv': round(fv_of(e)), 'fvx': round(fv_of(e), 1),
                    'fvIf': round(fv_of(math.exp(mi) * M.smear), 1),
                    'p40': round(M.above(pi, mi, ts_of(40)), 3), 'p50': round(M.above(pi, mi, ts_of(50)), 3),
                    'p60': round(M.above(pi, mi, ts_of(60)), 3),
                    # 90th / 75th percentile outcomes (20 when he more likely than not adds no NBA value)
                    'ceil': round(fv_of(M.quantile(pi, mi, 0.9))), 'q75': round(fv_of(M.quantile(pi, mi, 0.75))),
                    'q10': round(fv_of(M.quantile(pi, mi, 0.1)))})
    return out


def write():
    H, smap, teams, rows, F, ref, cls, ts, tr, M, cp, cv_, evid, tests, sc = main()
    r0, r1, tt, wins, rr0, rr1, E1 = sc
    bt = board_teams()
    rel = reliability(H)
    # forward look: the 2018-19 classes (windows observed through ages 24-25), fit on 2009-17
    fwd = {}
    for c in FORWARD:
        m = cls == c
        Ff = [F[i] for i in np.where(m)[0]]
        e_rank = Hurdle(['lrk'], ['lrk']).fit([F[i] for i in np.where(tr)[0]], ts[tr]).ets(Ff)
        fwd[c] = {'rank': round(spearman(e_rank, ts[m]), 3), 'model': round(spearman(M.ets(Ff), ts[m]), 3), 'n': int(m.sum()),
                  'nba': int((ts[m] > 0).sum())}
    # calibration, held out (2009-17): realized mean share by predicted FV band, as an FV
    Etr, Ttr = E1, ts[tr]
    calib = []
    for lo, hi in ((20, 25), (25, 30), (30, 35), (35, 40), (40, 45), (45, 50), (50, 81)):
        m = np.array([lo <= fv_of(e) < hi for e in Etr])
        if m.sum() >= 5:
            calib.append({'lo': lo, 'hi': min(hi, 80), 'n': int(m.sum()), 'pred': round(fv_of(float(Etr[m].mean())), 1),
                          'real': round(fv_of(float(Ttr[m].mean())), 1), 'nba': round(float((Ttr[m] > 0).mean()), 3),
                          'p50': round(float((Ttr[m] >= ts_of(50)).mean()), 3)})
    # realized outcomes by consensus rank band (what the scale means for recruits)
    bands = []
    for lo, hi in ((1, 5), (6, 10), (11, 25), (26, 50), (51, 100), (101, 200), (201, 400)):
        m = np.array([lo <= (r['rk'] or 999) <= hi for r in rows]) & tr
        if m.sum():
            bands.append({'lo': lo, 'hi': hi, 'n': int(m.sum()), 'nba': round(float((ts[m] > 0).mean()), 3),
                          'p50': round(float((ts[m] >= ts_of(50)).mean()), 3), 'fv': round(fv_of(float(ts[m].mean())), 1)})
    # the average training recruit, for the why rows
    Ftr = [F[i] for i in np.where(tr)[0]]
    avg = {k: float(np.mean([f[k] for f in Ftr])) for k in set(M.cp + M.cv)}
    # ARK stars, cut on the held-out FV of the training classes
    stars = ark_stars([rows[i] for i in np.where(tr)[0]], 20 + E1, cls[tr], TRAIN)
    print('ARK stars:', stars['pick'], {k: v['r2'] for k, v in stars['schemes'].items()}, 'cuts', stars['cuts'], 'half', stars['half'])
    # the college path, fit on every class's NIL-era seasons
    allr = [r for r in H['recruits']]
    Fa, _ = frame(allr, smap, teams, ref)
    pmods, ptests = path_fit(allr, Fa)
    # the board's FV distribution, for the percentile a recruit's FV would take on it
    bd = json.load(open(os.path.join(ROOT, 'static', 'data', 'cbb-all.json')))
    bi = {c: k for k, c in enumerate(bd['cols'])}
    bfv = np.sort([float(r[bi['fvx']] if r[bi['fvx']] is not None else r[bi['fv']]) for r in bd['rows'] if r[bi['fv']] is not None])
    out_classes = []
    for c in LIVE:
        raw = load_on3(c)
        lst = []
        for r in raw:
            row = compact(r, c)
            tm = team_of(row['team'], smap, bt)
            if tm: row['college'] = {'team': tm, 'conf': bt[tm]['conf'], 'y1': c + 1}
            # flag from the hometown (the state is where he plays: a Canadian prep school, say)
            hm = (r.get('home') or '').split(',')[-1].strip()
            nat = 'au' if hm in ('NSW', 'VIC', 'QLD', 'Canberra', 'Australia') else 'ca' if hm in CA_PROV else None
            row['nat'] = nat
            a = r.get('age')
            if a is not None and 14 <= a <= 21: row['old'] = 1 if a >= 18 - (c - 2027) else 0
            lst.append((r, row, tm))
        Fl, _ = frame([x[1] for x in lst], smap, teams, ref)
        G = grade(M, Fl, rel[c]['shrink'])
        P = path_of(pmods, Fl)
        recs = []
        for (r, row, tm), f, g, pth in zip(lst, Fl, G, P):
            rpm = (r.get('rpm') or [[None, None]])[0]
            lead = team_of(rpm[0], smap, bt) if rpm and rpm[0] else None
            recs.append({'name': row['name'], 'pos': row['pos'], 'ht': r.get('htf'), 'wt': row['wt'], 'home': row['home'],
                         'hs': r.get('hs'), 'rk': row['rk'], 'stars': row['stars'], 'fsp': bool(row['fsp']),
                         'svc': {k: v for k, v in row['svc'].items()}, 'age': r.get('age'),
                         'team': tm, 'logo': bt[tm]['logo'] if tm else None, 'conf': bt[tm]['conf'] if tm else None,
                         'school': ' '.join(row['team'].split('-')[:-1]).title() if row['team'] and not tm else None, 'signed': bool(r.get('signed')),
                         'lead': [lead, rpm[1]] if lead and not row['team'] else None,
                         'nat': row['nat'], 'img': r.get('img'), 'on3': f"https://www.on3.com/db/{r['slug']}/" if r.get('slug') else None,
                         'nil': r.get('nil'), 'why': why(M, f, avg), **g,
                         'ark': ark_of(stars, g['fvx']), 'pct': int(min(99, np.searchsorted(bfv, g['fvx'], side='right') * 100 // len(bfv))),
                         'path': pth, 'xnil': int(round(pth[0]['v'] * xnil_price(H, teams, tm, bt[tm]['conf'] if tm else None, f, ref), -3)),
                         'status': 'signed' if r.get('signed') else 'committed' if row['team'] else 'uncommitted'})
            d = round(g['fvx'] - fv_of(float(M.ets([f])[0])), 1)
            if abs(d) >= 0.1: recs[-1]['why']['rows'].append(['class still settling', d])
        recs.sort(key=lambda x: (-x['ets'], x['rk'] or 999))
        for i, x in enumerate(recs): x['ovr'] = i + 1
        out_classes.append({'year': c, 'n': len(recs), 'committed': sum(1 for x in recs if x['team'] or x['school']),
                            'reliability': rel[c], 'list': recs})
    # class rankings: expected NBA value the class brings (sum of E[share]) per committed school, next class
    nxt = next(x for x in out_classes if x['year'] == LIVE[0])
    by = defaultdict(list)
    for x in nxt['list']:
        if x['team']: by[x['team']].append(x)
    trows = []
    for t, xs in by.items():
        e = sum(x['ets'] for x in xs)
        trows.append({'team': t, 'logo': bt[t]['logo'], 'conf': bt[t]['conf'], 'n': len(xs), 'ets': round(e, 4),
                      'fvSum': round(fv_of(e), 1), 'pNba': round(1 - float(np.prod([1 - x['p'] for x in xs])), 3),
                      'top': [[x['name'], x['pos'], x['fv']] for x in xs[:3]], 'best': min(x['rk'] or 999 for x in xs),
                      'xnil': sum(x['xnil'] for x in xs), 'v1': round(sum(x['path'][0]['v'] for x in xs), 2),
                      'min1': round(sum(x['path'][0]['on'] * x['path'][0]['min'] for x in xs), 1),
                      'ark5': sum(1 for x in xs if x['ark'] >= 5), 'ark4': sum(1 for x in xs if 4 <= x['ark'] < 5)})
    trows.sort(key=lambda x: -x['ets'])
    for i, x in enumerate(trows): x['rk'] = i + 1
    res = {
        'asof': __import__('datetime').date.today().isoformat(),
        'scale': {'c': C_TS, 'ages': list(AGES), 'vorx': [VORX_K, VORX_REP]},
        'model': {'kept': {'p': [LABEL[c] for c in cp], 'value': [LABEL[c] for c in cv_]}, 'evidence': evid, 'tests': tests,
                  'coef': {'p': dict(zip(['const'] + cp, [round(float(x), 3) for x in M.bp])),
                           'value': dict(zip(['const'] + cv_, [round(float(x), 3) for x in M.bv])), 's': round(M.s, 3),
                           'smear': round(M.smear, 3)},
                  'train': {'classes': [TRAIN[0], TRAIN[-1]], 'n': int(tr.sum()), 'nba': int((ts[tr] > 0).sum())},
                  'heldout': {'rank': round(r0, 3), 'model': round(r1, 3), 't': round(tt, 2), 'wins': wins,
                              'byClass': {str(c): [round(a, 3), round(b, 3)] for c, a, b in zip(TRAIN, rr0, rr1)}},
                  'forward': {str(k): v for k, v in fwd.items()}, 'calib': calib, 'bands': bands, 'stars': stars,
                  'path': {str(k): v for k, v in ptests.items()}, 'pathEra': PATH_ERA,
                  'xnil': {'budget': {k: XNIL[k] for k in ('HM', 'MM', 'LM')}, 'tilt': XNIL['tilt'], 'rep': REP_BPM, 'ref': {k: v for k, v in H['nilRef'].items() if k != 'conf'},
                           'levels': {k: sorted(v) for k, v in LEVELS.items()}},
                  'research': RESEARCH},
        'classes': out_classes, 'teams': trows,
    }
    json.dump(res, open(OUT, 'w'), separators=(',', ':'), allow_nan=False)
    print('wrote', OUT, {x['year']: (x['n'], x['committed'], x['reliability']['shrink']) for x in out_classes})
    return res


if __name__ == '__main__':
    write()
