#!/usr/bin/env python3
"""College basketball recruit boards: HS classes graded on the shared FV value scale, fit on what past recruits became.

    node scripts/cbb_on3.mjs 2027 2028 2029        # the live classes (and 2009-2026 once, for the history)
    python3 scripts/cbb_recruit_fit.py              # link, test, fit, write data/cbb_recruits.json
    python3 scripts/cbb_recruit_fit.py --offline    # refit from scripts/data/cbb_recruit_hist.json.gz (no kit, no pulls)

Outcome (the shared value scale, thread "Rebuild FV on a shared value scale", Oct 26): FV = expected PEAK surplus
over replacement. Peak = mean of the best three NBA seasons at ages 22-28, a missing season counts 0; each season is
VORX (0.030 x (XPM + 1.4) x MP / 48, XPM = the 50/50 BPM + DPM blend) as a share of that season's average team VORX
(about 18). FV = 20 + 30 ln(1 + TS/c) / ln 15, c = 1/280: 20 replacement, 50 = 5% of a team, 80 = 80% (MVP peak).
The headline is FV of the expected share (E[TS]), not the mean of FVs.

History: On3 industry rankings (the consensus of On3, 247, ESPN and Rivals) for the 2009-2025 classes, every listed
recruit, so the prep-to-pro, G League Ignite, Overtime Elite and overseas routes are in the sample (a college-only
sample would drop Jalen Green, Scoot Henderson, the Thompson twins). Each recruit is linked to his NBA career by the
college link (scripts/cbb_link.py: Barttorvik career, On3 consensus rank and class) or by name through
scripts/names.py with a class that fits his NBA age (class = season - age + 17, +-1). Classes 2009-2017 train (age 22
falls in 2022 for the 2017 class, so their windows are observed through age 26 or more); 2018-2019 are a forward look
on the partial window.

Model: hurdle on the share. P(peak > 0) is a logistic, log share given > 0 a ridge with its residual SD, so
E[TS] = P x exp(mu + s^2 / 2). Drivers enter only if they help out of sample with whole classes held out (9 folds):
better log loss for P, better RMSE for log share, both scored as a paired t across classes (t >= 2, 6+ of 9 classes).
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

TRAIN = list(range(2009, 2018))
FORWARD = [2018, 2019]
LIVE = [2027, 2028, 2029]
NOW_CLASS = 2026                     # this season's freshmen: the board grades them, the recruit model is checked on them
NBA_LAST = 2026
VORX_K, VORX_REP = 0.030, -1.4        # VORX (cbb/vorx, NBA thread Oct 18)
C_TS = 1 / 280                        # the value map (fv-value-scale)
AGES = (22, 28)
RANK_CAP = 400


def fv_of(ts):
    """FV of a share of a team's surplus (the shared value map)"""
    return 20 + 30 * math.log(1 + max(ts, 0) / C_TS) / math.log(15)


def ts_of(fv):
    return C_TS * (15 ** ((fv - 20) / 30) - 1)


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
            'svc': {k: v[1] for k, v in s.items() if v and v[1]}, 'svr': {k: v[0] for k, v in s.items() if v and v[0]}}


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


def build_history():
    """the 2009-2025 On3 classes with each recruit's NBA peak share and first college team (scripts/data cache)"""
    car = nba_careers()
    # the college link: kit rows carry the On3 consensus rank and class (cbb_link.py), the Barttorvik career and bref id
    kit = {}
    first = {}
    net = defaultdict(float)        # team strength by season: minutes-weighted BPM summed over the roster
    for r in csv.DictReader(open(os.path.join(KIT, 'kit', 'college_seasons_nba.csv'))):
        if r['bpm'] and r['min_per']: net[(int(r['year']), r['team'])] += float(r['bpm']) * float(r['min_per']) / 100
        if not r['rec_class'] or not r['on3rk']: continue
        k = (int(r['rec_class']), int(float(r['on3rk'])))
        y = int(r['year'])
        if k not in first or y < first[k][0]:
            first[k] = (y, r['team'], r['conf'], r['name'], r['nba_bref'] or None, r['dob'] or None)
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
            out.append(row)
    print('linked to NBA careers:', dict(how), 'of', len(out), 'recruits')
    # program strength, z-scored within each season (the season before a recruit arrives is what he chose on)
    teams = {}
    for y in sorted({y for y, _ in net}):
        v = {t: x for (yy, t), x in net.items() if yy == y}
        m, sd = np.mean(list(v.values())), np.std(list(v.values()))
        teams[str(y)] = {t: round((x - m) / sd, 3) for t, x in v.items()}
    H = {'recruits': out, 'teams': teams}
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


CANDS = ['lrk2', 'lsvc', 'top25', 'top5', 'cons', 'fsp', 'svc_sd', 'n_svc', 'espn_gap', 'g247_gap', 'on3_gap', 'ht_pos', 'wt_ht', 'guard', 'big',
         'intl', 'prog', 'hm', 'old']
LABEL = {'lrk': 'consensus rank', 'lrk2': 'consensus rank, curve', 'lsvc': 'mean service rank', 'top25': 'top-25 recruit', 'top5': 'top-5 recruit', 'cons': 'consensus rating',
         'fsp': '5-star+', 'svc_sd': 'services disagree', 'n_svc': 'services ranking him', 'espn_gap': 'ESPN vs consensus',
         'g247_gap': '247 vs consensus', 'on3_gap': 'On3 vs consensus', 'ht_pos': 'height for position',
         'wt_ht': 'weight for height', 'guard': 'guard', 'big': 'big', 'intl': 'from abroad', 'prog': 'program strength',
         'hm': 'high-major program', 'old': 'old for the class'}


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
    for f in out:
        g = 'guard' if f['guard'] else 'big' if f['big'] else 'wing'
        m, sd = ref['ht_' + g]
        f['ht_pos'] = (f['ht'] - m) / sd if f['ht'] else 0.0
        f['wt_ht'] = (f['wt'] - np.polyval(ref['wt'], f['ht'])) / 15 if f['ht'] and f['wt'] else 0.0
        # no school yet (uncommitted, or never enrolled at a D-I school): the program a recruit of his rank lands at
        if f['prog'] is None: f['prog'] = float(np.polyval(ref['prog'], f['lrk']))
        if f['hm'] is None: f['hm'] = float(min(1, max(0, np.polyval(ref['hm'], f['lrk']))))
        if f['old'] is None: f['old'] = ref['old']
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
                if t <= -2 and w >= 6 and (best is None or t < best[2]): best = (c, d, t, w, a, b)
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
    smap = slug_map(H)
    teams = H['teams']
    rows = [r for r in H['recruits'] if r['cls'] in TRAIN + FORWARD]
    for r in rows: r['ts'] = peak_share(r['nba'])
    F, ref = frame(rows, smap, teams)
    cls = np.array([r['cls'] for r in rows])
    ts = np.array([r['ts'] for r in rows])
    tr = np.isin(cls, TRAIN)
    Ftr = [F[i] for i in np.where(tr)[0]]
    print('train', tr.sum(), 'recruits;', int((ts[tr] > 0).sum()), 'with NBA value at 22-28;',
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
    print(f'held-out Spearman with the peak share: rank only {r0:.3f}, model {r1:.3f} (t {tt:.2f}, {(d > 0).sum()}/{len(d)})')
    M = Hurdle(cp, cv_).fit(Ftr, ts[tr])
    return H, smap, teams, rows, F, ref, cls, ts, tr, M, cp, cv_, evid, tests, (r0, r1, tt, int((d > 0).sum()), rr0, rr1, E1)


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
                    'ceil': round(fv_of(M.quantile(pi, mi, 0.9))), 'q75': round(fv_of(M.quantile(pi, mi, 0.75)))})
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
        recs = []
        for (r, row, tm), f, g in zip(lst, Fl, G):
            rpm = (r.get('rpm') or [[None, None]])[0]
            lead = team_of(rpm[0], smap, bt) if rpm and rpm[0] else None
            recs.append({'name': row['name'], 'pos': row['pos'], 'ht': r.get('htf'), 'wt': row['wt'], 'home': row['home'],
                         'hs': r.get('hs'), 'rk': row['rk'], 'stars': row['stars'], 'fsp': bool(row['fsp']),
                         'svc': {k: v for k, v in row['svc'].items()}, 'age': r.get('age'),
                         'team': tm, 'logo': bt[tm]['logo'] if tm else None, 'conf': bt[tm]['conf'] if tm else None,
                         'school': ' '.join(row['team'].split('-')[:-1]).title() if row['team'] and not tm else None, 'signed': bool(r.get('signed')),
                         'lead': [lead, rpm[1]] if lead and not row['team'] else None,
                         'nat': row['nat'], 'img': r.get('img'), 'on3': f"https://www.on3.com/db/{r['slug']}/" if r.get('slug') else None,
                         'nil': r.get('nil'), 'why': why(M, f, avg), **g})
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
                      'top': [[x['name'], x['pos'], x['fv']] for x in xs[:3]], 'best': min(x['rk'] or 999 for x in xs)})
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
                  'forward': {str(k): v for k, v in fwd.items()}, 'calib': calib, 'bands': bands},
        'classes': out_classes, 'teams': trows,
    }
    json.dump(res, open(OUT, 'w'), separators=(',', ':'), allow_nan=False)
    print('wrote', OUT, {x['year']: (x['n'], x['committed'], x['reliability']['shrink']) for x in out_classes})
    return res


if __name__ == '__main__':
    write()
