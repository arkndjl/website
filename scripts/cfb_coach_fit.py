#!/usr/bin/env python3
"""Coaching market: what each head coach and coordinator is worth, which jobs open, and who fills them.
Writes data/cfb_coach_fit.json (the fitted models and their out-of-sample evidence) and data/cfb_coach_pay.json
(public pay by coach, the market the value model is priced on). Scoring runs in scripts/cfb_coach.mjs.

    python3 scripts/cfb_coach_fit.py            # pull (cached in scripts/.cache/coach/), build, fit
    python3 scripts/cfb_coach_fit.py --offline  # refit from the cached pulls only

Data:
  pay       USA Today's salary database: head coaches 2006-25 and assistants 2012-24 at public FBS schools
            (private schools don't report), by school and year, and each coach's career page (school and
            Head / Assistant by year), which is how coaches are followed between jobs.
  results   ESPN season records 2005-25 (win%) for every school in the pay data.
  staff     data/cfb_teams.json: this season's staff board (scores, Elo, TvE, zNIL, scheme traits).

Models:
  1. value    log(pay) of a head coach on his staff metrics and his program's level, ridge, every input kept
              only if it lowers leave-one-out error (its weight is what the evidence supports, zero if none).
              The panel fit (2007-25) gives how the market prices results: last season's win%, the two before,
              win% against the program's own 10-year norm, tenure. Coordinators: log(pay) of the two best-paid
              assistants (the coordinators, in practice) on the same terms plus their staff-board score.
  2. vacancy  multinomial logit on every public school-season 2007-24: same coach next season / coach left
              for another head job (poached) / coach out (fired, retired, NFL). Fit on 2007-19, tested out of
              time on 2020-24, refit on all for the live coefficients.
  3. hires    where new head coaches come from (a sitting FBS head coach, an FBS assistant, elsewhere) and,
              for sitting head coaches, a conditional logit over every one of them: pay step up (the job's
              pay over his), his last season's win%, same conference, distance. Fit on the 2008-25 hires.
  4. staff    coordinator turnover: the two best-paid assistants a year later, split by whether the head
              coach changed, and how often they follow a head coach who moved (same school as him the next
              season), measured on the assistant panel.
"""
import concurrent.futures as cf
import hashlib
import html as H
import json
import math
import os
import re
import sys
import time
from collections import Counter, defaultdict

import numpy as np
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'coach')
OUT = os.path.join(ROOT, 'data', 'cfb_coach_fit.json')
PAY_OUT = os.path.join(ROOT, 'data', 'cfb_coach_pay.json')
LOC = os.path.join(ROOT, 'scripts', 'geo', 'team_loc.json')
OFFLINE = '--offline' in sys.argv
UT = 'https://sportsdata.usatoday.com/ncaa/salaries/football'
CORE = 'https://sports.core.api.espn.com/v2/sports/football/leagues/college-football'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'
os.makedirs(CACHE, exist_ok=True)
S = requests.Session(); S.headers['User-Agent'] = UA


def get(url, kind='json'):
    """GET, cached on disk by URL (past seasons and pay records don't change; delete the cache to refresh)."""
    f = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest() + ('.json' if kind == 'json' else '.html'))
    if os.path.exists(f):
        with open(f) as h: return json.load(h) if kind == 'json' else h.read()
    if OFFLINE: return None
    for i in range(5):
        try:
            r = S.get(url, timeout=30)
            if r.status_code == 404: v = None; break
            r.raise_for_status()
            v = r.json() if kind == 'json' else r.text
            break
        except Exception:
            time.sleep(1 + 2 * i)
    else:
        return None
    with open(f, 'w') as h:
        json.dump(v, h) if kind == 'json' else h.write(v or '')
    return v


def money(s):
    s = re.sub(r'[^0-9]', '', s or '')
    return int(s) if s else None


def table(page):
    """The page's table rows as (cells, hrefs)."""
    out = []
    for r in re.findall(r'<tr[^>]*>(.*?)</tr>', page or '', re.S)[1:]:
        cells = [H.unescape(re.sub('<[^>]+>', '', c)).strip() for c in re.findall(r'<td[^>]*>(.*?)</td>', r, re.S)]
        out.append((cells, re.findall(r'href="([^"]+)"', r)))
    return out


def norm(s):
    s = H.unescape(s or '').lower().replace('&', 'and')
    s = re.sub(r'\b(jr|sr|ii|iii|iv)\b\.?', '', s)
    return re.sub(r'[^a-z]', '', s)


# ---- pulls -----------------------------------------------------------------------------------------------
def head_list():
    """2025 head coaches: USA Today coach id, school id, school, conference, pay, buyout."""
    rows = []
    for cells, hrefs in table(get(f'{UT}/coach', 'html')):
        cid = next((h.rsplit('/', 1)[1] for h in hrefs if re.search(r'/coach/\d+$', h)), None)
        sid = next((h.rsplit('/', 1)[1] for h in hrefs if '/coach/team/' in h), None)
        if not sid: continue
        rows.append({'cid': cid, 'sid': sid, 'name': cells[1], 'school': cells[2], 'pay': money(cells[3]), 'conf': cells[4],
                     'buyout': money(cells[8]) if len(cells) > 8 else None, 'estimated': '*' in cells[3]})
    return rows


def school_heads(sid):
    """Head coach by year at one school: [(year, coach id, name, pay)]."""
    out = []
    for cells, hrefs in table(get(f'{UT}/coach/team/{sid}', 'html')):
        cid = next((h.rsplit('/', 1)[1] for h in hrefs if re.search(r'/coach/\d+$', h)), None)
        if cells and cells[0].isdigit(): out.append((int(cells[0]), cid, cells[1], money(cells[2])))
    return out


def school_assts(sid):
    out = []
    for cells, hrefs in table(get(f'{UT}/assistant/team/{sid}', 'html')):
        aid = next((h.rsplit('/', 1)[1] for h in hrefs if re.search(r'/assistant/\d+$', h)), None)
        if cells and cells[0].isdigit(): out.append((int(cells[0]), aid, cells[1], money(cells[2])))
    return out


def career(cid, kind='coach'):
    """A coach's career page: [(year, school, Head/Assistant, pay)]."""
    return [(int(c[0]), c[1], c[2], money(c[3])) for c, _ in table(get(f'{UT}/{kind}/{cid}', 'html')) if c and c[0].isdigit()]


def espn_teams():
    """School name variants -> ESPN team id: this season's FBS teams first (data/cfb_teams.json), then ESPN's list."""
    idx = {}
    for t in json.load(open(os.path.join(ROOT, 'data', 'cfb_teams.json')))['teams']:
        for k in ('team', 'full', 'abbr'): idx.setdefault(norm(t.get(k)), t['tid'])
    d = get('https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams?limit=1000') or {}
    for t in d.get('sports', [{}])[0].get('leagues', [{}])[0].get('teams', []):
        t = t['team']
        for k in ('location', 'shortDisplayName', 'displayName', 'abbreviation'):
            if t.get(k): idx.setdefault(norm(t[k]), t['id'])
    return idx


ALIAS = {'miamifl': 'miami', 'armywestpoint': 'army', 'ulm': 'ulmonroe', 'miamioh': 'miamioh', 'southernmississippi': 'southernmiss', 'centralflorida': 'ucf',
         'louisianalafayette': 'louisiana', 'louisianamonroe': 'ulmonroe', 'texassanantonio': 'utsa', 'appalachianstate': 'appstate',
         'floridainternational': 'fiu', 'nevadalasvegas': 'unlv', 'texaselpaso': 'utep', 'alabamabirmingham': 'uab',
         'hawaii': 'hawaii', 'sanjosestate': 'sanjosstate', 'massachusetts': 'massachusetts', 'connecticut': 'uconn',
         'middletennesseestate': 'middletennessee', 'samhoustonstate': 'samhouston', 'olemiss': 'olemiss', 'mississippi': 'olemiss',
         'pittsburgh': 'pittsburgh', 'northcarolinastate': 'ncstate', 'southflorida': 'southflorida'}


def record(season, tid):
    d = get(f'{CORE}/seasons/{season}/types/2/teams/{tid}/record') or {}
    for it in d.get('items', []):
        if it.get('type') == 'total':
            m = re.match(r'(\d+)-(\d+)', it.get('summary', ''))
            if m: return int(m.group(1)), int(m.group(2))
    return None


def conf_of(season, tid):
    t = get(f'{CORE}/seasons/{season}/teams/{tid}') or {}
    if not t.get('groups'): return None
    g = get(t['groups']['$ref'].replace('http://', 'https://')) or {}
    if g.get('isConference') is False and g.get('parent'):
        g = get(g['parent']['$ref'].replace('http://', 'https://')) or g
    return g.get('shortName') or g.get('abbreviation') or g.get('name')


def pull():
    heads = head_list()
    print('2025 head coaches', len(heads))
    idx = espn_teams()
    for h in heads:
        k = norm(h['school']); h['tid'] = idx.get(ALIAS.get(k, k)) or idx.get(k)
    miss = [h['school'] for h in heads if not h['tid']]
    if miss: print('no ESPN id for', miss)
    with cf.ThreadPoolExecutor(12) as ex:
        hs = dict(zip([h['sid'] for h in heads], ex.map(school_heads, [h['sid'] for h in heads])))
        asst = dict(zip([h['sid'] for h in heads], ex.map(school_assts, [h['sid'] for h in heads])))
    cids = sorted({c for v in hs.values() for _, c, _, _ in v if c})
    with cf.ThreadPoolExecutor(12) as ex:
        car = dict(zip(cids, ex.map(career, cids)))
    board = [t['tid'] for t in json.load(open(os.path.join(ROOT, 'data', 'cfb_teams.json')))['teams']]
    jobs = [(s, t) for t in sorted({h['tid'] for h in heads if h['tid']} | set(board)) for s in range(2005, 2027)]
    with cf.ThreadPoolExecutor(16) as ex:
        recs = dict(zip(jobs, ex.map(lambda j: record(*j), jobs)))
        confs = dict(zip(jobs, ex.map(lambda j: conf_of(*j), jobs)))
    print('pulled', len(hs), 'schools,', len(cids), 'head coach careers,', sum(1 for v in recs.values() if v), 'team records')
    return heads, hs, asst, car, recs, confs


# ---- panel -----------------------------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cfb_transfer_fit import softmax_fit, probs, auc   # noqa: E402  (multinomial ridge logit, Newton)

FBS_CONF = {'SEC', 'Big Ten', 'Big 12', 'ACC', 'Pac-12', 'Big East', 'American', 'Mountain West', 'CUSA', 'MAC', 'Sun Belt', 'WAC', 'FBS Indep.'}
P4_CONF = {'SEC', 'Big Ten', 'Big 12', 'ACC', 'Pac-12', 'Big East'}   # Big East: an automatic-qualifier league through 2012
P4_IND = {'87'}   # Notre Dame


def miles(a, b):
    if not a or not b: return None
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 3959 * 2 * math.asin(math.sqrt(h))


class Panel:
    """Who coached where, results and levels, by school (ESPN team id) and season."""
    def __init__(self, heads, hs, asst, car, recs, confs):
        self.idx = espn_teams()
        self.tid = {}
        for h in heads:
            k = norm(h['school']); h['tid'] = self.idx.get(ALIAS.get(k, k)) or self.idx.get(k); self.tid[h['sid']] = h['tid']
        self.heads, self.car = heads, car
        self.school = {h['tid']: h['school'] for h in heads}
        self.win = {(t, y): v[0] / (v[0] + v[1]) for (y, t), v in recs.items() if v and v[0] + v[1] >= 4}
        self.conf = {(t, y): v for (y, t), v in confs.items() if v}
        self.coach, self.pay, self.cname = {}, {}, {}   # (tid, season) -> coach id, pay; coach id -> name
        for sid, rows in hs.items():
            t = self.tid.get(sid)
            if not t: continue
            for y, cid, name, pay in reversed(rows):   # oldest first; a season with two rows keeps the coach listed first
                self.coach[(t, y)] = cid; self.pay[(t, y)] = pay; self.cname[cid] = name
        # 2008 is missing from the pay pages: a coach on both sides of it coached it
        for t in set(k[0] for k in self.coach):
            if (t, 2008) not in self.coach and self.coach.get((t, 2007)) and self.coach.get((t, 2007)) == self.coach.get((t, 2009)):
                self.coach[(t, 2008)] = self.coach[(t, 2007)]
        self.ast = defaultdict(list)   # (tid, season) -> [(pay, assistant id, name)], best paid first
        for sid, rows in asst.items():
            t = self.tid.get(sid)
            for y, aid, name, pay in rows:
                if t and pay: self.ast[(t, y)].append((pay, aid, name))
        for v in self.ast.values(): v.sort(reverse=True)
        self.loc = json.load(open(LOC))
        # where each head coach was each season (career pages): (cid, season) -> (school tid or name, Head/Assistant)
        self.where = {}
        for cid, rows in car.items():
            for y, school, pos, pay in rows:
                k = norm(school); self.where[(cid, y)] = (self.idx.get(ALIAS.get(k, k)) or self.idx.get(k) or school, pos, pay)

    def level(self, t, y):
        c = self.conf.get((t, y))
        if c is None: return None
        p4 = (c in P4_CONF and not (c == 'Pac-12' and y >= 2024) and not (c == 'Big East' and y >= 2013)) or t in P4_IND
        return 'P4' if p4 else 'G5' if c in FBS_CONF else 'FCS'

    def tenure(self, t, y):
        c, n = self.coach.get((t, y)), 0
        while c and self.coach.get((t, y - n)) == c: n += 1
        return n, (t, y - n) not in self.coach   # (seasons in the job through y, censored: the data starts mid-tenure)

    def norm_win(self, t, y, n=10):
        w = [self.win[(t, s)] for s in range(y - n, y) if (t, s) in self.win]
        return sum(w) / len(w) if len(w) >= 3 else None

    def pay_rel(self, t, y):
        """log pay against the median head coach at the level that season (public schools)"""
        p, lv = self.pay.get((t, y)), self.level(t, y)
        if not p: return None
        peers = [v for (t2, y2), v in self.pay.items() if y2 == y and v and self.level(t2, y2) == lv]
        return math.log(p / float(np.median(peers))) if len(peers) >= 10 else None


def features(P, t, y, wp0=None):
    """End-of-season features for school t's head coach in season y. wp0 overrides the season's win% (a projection)."""
    lv = P.level(t, y)
    w0 = wp0 if wp0 is not None else P.win.get((t, y))
    if w0 is None or lv not in ('P4', 'G5'): return None
    w1, w2 = P.win.get((t, y - 1)), P.win.get((t, y - 2))
    nw = P.norm_win(t, y)
    ten, cens = P.tenure(t, y)
    pr = P.pay_rel(t, y)
    prev = w1 if w1 is not None else w0
    return {
        'wp': w0 - 0.5, 'wpPrev': ((w1 if w1 is not None else w0) + (w2 if w2 is not None else prev)) / 2 - 0.5,
        'vsNorm': w0 - (nw if nw is not None else 0.5), 'yr1': float(ten == 1), 'yr2': float(ten == 2),
        'longTen': math.log(min(ten, 12)) if not cens or ten >= 5 else math.log(5), 'g5': float(lv == 'G5'),
        'g5wp': float(lv == 'G5') * (w0 - 0.5), 'payRel': pr if pr is not None else 0.0, 'payMiss': float(pr is None),
    }


VAC_X = ['wp', 'wpPrev', 'vsNorm', 'yr1', 'yr2', 'longTen', 'g5', 'g5wp', 'payRel', 'payMiss']


def vacancy_rows(P):
    """School-seasons with the outcome next season: 0 same coach, 1 left for another head job (moved), 2 out
    (fired, retired, NFL). 2010 on, so the program's 10-year norm and tenure have history behind them."""
    rows = []
    for (t, y), c in P.coach.items():
        if y < 2010 or y > 2025: continue
        c1 = P.coach.get((t, y + 1))
        if not c1: continue
        x = features(P, t, y)
        if not x: continue
        if c1 == c: out = 0
        else:
            w = P.where.get((c, y + 1))
            out = 1 if w and w[1] == 'Head' and w[0] != t else 2
        rows.append({'t': t, 'y': y, 'cid': c, 'x': x, 'out': out})
    return rows


def add_board(P, D):
    """This season's head coaches (data/cfb_teams.json) as season 2026: the same coach id when he coached the
    school in 2025, his 2025 id when he moved from another school, a new id otherwise."""
    by_name = {}
    for (t, y), c in P.coach.items():
        if y == 2025: by_name[norm(P.cname[c])] = (c, t)
    for t in D['teams']:
        if not t.get('hc'): continue
        n = norm(t['hc']); c, t0 = by_name.get(n, (None, None))
        if c is None:
            c = 'new:' + n; P.cname[c] = t['hc']
        P.coach[(t['tid'], 2026)] = c
        if t0 and t0 != t['tid']: P.where[(c, 2026)] = (t['tid'], 'Head', None)
        elif t0 == t['tid']: P.where[(c, 2026)] = (t0, 'Head', None)


# ---- fitting helpers ---------------------------------------------------------------------------------------
def mlogloss(p, y): return float(-np.mean(np.log(p[np.arange(len(y)), y])))


def mat(rows, names): return np.array([[1.0] + [r['x'][k] for k in names] for r in rows])


def onehot(rows): return np.eye(3)[[r['out'] for r in rows]]


def clogit(groups, lam=1.0, iters=200):
    """conditional logit over choice sets: groups = [(candidates x features, chosen row)], L2 ridge, damped Newton"""
    k = groups[0][0].shape[1]; b = np.zeros(k)
    for _ in range(iters):
        g = -lam * b; Hs = -lam * np.eye(k)
        for X, c in groups:
            z = X @ b; p = np.exp(z - z.max()); p /= p.sum(); xm = p @ X
            g += X[c] - xm; Hs -= (X * p[:, None]).T @ X - np.outer(xm, xm)
        st = np.linalg.solve(Hs, g); st /= max(1.0, np.abs(st).max()); b -= st
        if np.abs(st).max() < 1e-8: break
    return b, np.sqrt(np.diag(np.linalg.inv(-Hs)))


def cll(groups, b):
    """mean negative log-likelihood of the chosen candidate"""
    out = []
    for X, c in groups:
        z = X @ b; mx = z.max(); out.append(-(z[c] - mx) + math.log(np.exp(z - mx).sum()))
    return float(np.mean(out))


def hits(groups, b, n):
    return float(np.mean([(np.argsort(-(X @ b))[:n] == c).any() for X, c in groups]))


def ridge_loo(rows, ys, names, lam):
    """leave-one-out squared error of a ridge on standardized inputs"""
    X = np.array([[r[k] for k in names] for r in rows]); err = []
    for i in range(len(rows)):
        mk = np.arange(len(rows)) != i; mu = X[mk].mean(0); sd = X[mk].std(0) + 1e-9
        A = np.c_[np.ones(mk.sum()), (X[mk] - mu) / sd]; pen = lam * np.eye(A.shape[1]); pen[0, 0] = 0
        b = np.linalg.solve(A.T @ A + pen, A.T @ ys[mk]); err.append(ys[i] - np.r_[1, (X[i] - mu) / sd] @ b)
    return float(np.mean(np.square(err)))


def value_fit(rows, cands, label):
    """log(pay) on the candidate inputs: forward selection by leave-one-out error, an input kept only when it
    cuts the error by 1%+; then each input's evidence (LOO error with it removed from the final set, or added)."""
    ys = np.array([r['y'] for r in rows]); var = float(ys.var() * len(ys) / (len(ys) - 1))
    lams = (0.5, 2, 8)
    sel, best = [], var
    while True:
        tries = [(min(ridge_loo(rows, ys, sel + [k], l) for l in lams), k) for k in cands if k not in sel]
        if not tries: break
        e, k = min(tries)
        if e > best * 0.99: break
        best, sel = e, sel + [k]
    lam = min(lams, key=lambda l: ridge_loo(rows, ys, sel, l))
    X = np.array([[r[k] for k in sel] for r in rows]); mu = X.mean(0); sd = X.std(0) + 1e-9
    A = np.c_[np.ones(len(X)), (X - mu) / sd]; pen = lam * np.eye(A.shape[1]); pen[0, 0] = 0
    b = np.linalg.solve(A.T @ A + pen, A.T @ ys)
    resid = float(np.sqrt(np.mean((ys - A @ b) ** 2)))
    ev = {}
    for k in cands:
        alt = [j for j in sel if j != k] if k in sel else sel + [k]
        e = ridge_loo(rows, ys, alt, lam) if alt else var
        ev[k] = {'kept': k in sel, 'r': round(float(np.corrcoef([r[k] for r in rows], ys)[0, 1]), 3),
                 'looGain': round(1 - best / e, 4) if k in sel else round(1 - e / best, 4)}   # share of LOO error it removes (kept) or would remove (dropped)
    print(label, 'n', len(rows), 'kept', sel, 'LOO R2', round(1 - best / var, 3))
    return {'n': len(rows), 'names': sel, 'mu': [round(float(x), 5) for x in mu], 'sd': [round(float(x), 5) for x in sd],
            'coef': [round(float(x), 5) for x in b], 'lam': lam, 'looR2': round(1 - best / var, 3), 'resid': round(resid, 4), 'evidence': ev}


# ---- the fit ---------------------------------------------------------------------------------------------
def fit(P, D):
    add_board(P, D)
    T = {t['tid']: t for t in D['teams']}
    out = {'asof': time.strftime('%Y-%m-%d'), 'source': 'USA Today NCAA salaries (head coaches 2006-25, assistants 2009-24), ESPN records'}

    # 1. vacancies ---------------------------------------------------------------------------------------
    R = vacancy_rows(P)
    tr = [r for r in R if r['y'] <= 2019]; te = [r for r in R if r['y'] >= 2020]
    LAM = 1.0

    def cv(names):   # rolling origin inside the training years: fit through y-1, score y (2014-19)
        ll = []
        for y in range(2014, 2020):
            a = [r for r in tr if r['y'] < y]; b = [r for r in tr if r['y'] == y]
            B, _ = softmax_fit(mat(a, names), onehot(a), LAM); ll.append(mlogloss(probs(mat(b, names), B), [r['out'] for r in b]) * len(b))
        return sum(ll) / sum(1 for r in tr if 2014 <= r['y'] <= 2019)
    names = list(VAC_X); cur = cv(names)
    while len(names) > 1:   # backward: drop the input whose removal helps most, while any does
        tries = [(cv([k for k in names if k != d]), d) for d in names]
        e, d = min(tries)
        if e >= cur: break
        cur, names = e, [k for k in names if k != d]
    B, _ = softmax_fit(mat(tr, names), onehot(tr), LAM)
    pt = probs(mat(te, names), B); yt = np.array([r['out'] for r in te])
    base = onehot(tr).mean(0)
    test = {'n': len(te), 'seasons': '2020-25', 'logLoss': round(mlogloss(pt, yt), 4), 'logLossBase': round(mlogloss(np.tile(base, (len(te), 1)), yt), 4),
            'aucChange': round(auc(1 - pt[:, 0], yt > 0), 3), 'aucMoved': round(auc(pt[:, 1], yt == 1), 3), 'aucOut': round(auc(pt[:, 2], yt == 2), 3),
            'rate': [round(float(x), 3) for x in np.bincount(yt, minlength=3) / len(yt)],
            'calib': [[round(float(pt[d, 1:].sum(1).mean()), 3), round(float((yt[d] > 0).mean()), 3)] for d in np.array_split(np.argsort(1 - pt[:, 0]), 5)]}
    test['skill'] = round(1 - test['logLoss'] / test['logLossBase'], 3)
    drop = {}
    for k in VAC_X:   # evidence per input on the test seasons: log loss with it out (kept) or in (dropped)
        alt = [j for j in names if j != k] if k in names else names + [k]
        B2, _ = softmax_fit(mat(tr, alt), onehot(tr), LAM)
        drop[k] = {'kept': k in names, 'dLogLoss': round(mlogloss(probs(mat(te, alt), B2), yt) - test['logLoss'], 4)}
    Bf, se = softmax_fit(mat(R, names), onehot(R), LAM)
    print('vacancy', len(R), 'rows, kept', names, 'test', test)
    out['vacancy'] = {'names': ['const'] + names, 'coef': [[round(float(x), 4) for x in row] for row in Bf], 'se': [[round(float(x), 4) for x in row] for row in se],
                      'classes': ['stay', 'moved', 'out'], 'n': len(R), 'test': test, 'evidence': drop,
                      'counts': [int(x) for x in np.bincount([r['out'] for r in R], minlength=3)]}

    # 2. hires ----------------------------------------------------------------------------------------------
    anames = {}
    for (t, y), v in P.ast.items():
        for i, (pay, aid, name) in enumerate(v): anames.setdefault((norm(name), y), []).append((t, i))
    ev = []
    for (t, y), c in P.coach.items():
        c1 = P.coach.get((t, y + 1))
        if not c1 or c1 == c or y < 2009 or y > 2025: continue
        w = P.where.get((c1, y)); n = norm(P.cname[c1])
        if w and w[1] == 'Head': o = 'hc' if w[0] != t else 'other'   # the school's own interim counts as other
        elif w and w[1] == 'Assistant':
            a = anames.get((n, y)); o = 'coord' if a and a[0][1] < 2 else 'other'
        else: o = 'other'
        ev.append((t, y, c1, o))
    share = {}   # by the job's level; 2025's assistants aren't published yet
    for lv in ('P4', 'G5'):
        pools = Counter(e[3] for e in ev if e[1] <= 2024 and P.level(e[0], e[1]) == lv)
        share[lv] = {k: round(v / sum(pools.values()), 3) for k, v in pools.items()}; share[lv]['n'] = sum(pools.values())
    print('hire pools', share)

    def hc_cands(t, y):
        jl = P.level(t, y); jp = P.pay.get((t, y)) or level_median(P, y, jl); res = []
        for (j, yy), c in P.coach.items():
            if yy != y or j == t: continue
            x = features(P, j, y)
            if not x: continue
            cl = P.level(j, y); cp = P.pay.get((j, y)) or level_median(P, y, cl)
            res.append((c, hc_x(x, jp, cp, jl, cl, P.conf.get((t, y)) == P.conf.get((j, y)), miles(P.loc.get(t), P.loc.get(j)))))
        return res
    G = []
    for t, y, c1, o in ev:
        if o != 'hc': continue
        cs = hc_cands(t, y); ids = [c for c, _ in cs]
        if c1 in ids: G.append((np.array([x for _, x in cs]), ids.index(c1), y))
    gtr = [(X, c) for X, c, y in G if y <= 2018]; gte = [(X, c) for X, c, y in G if y > 2018]
    b, _ = clogit(gtr)
    hc_test = {'n': len(gte), 'seasons': '2019-25', 'logLik': round(-cll(gte, b), 3), 'logLikUniform': round(-float(np.mean([math.log(len(X)) for X, _ in gte])), 3),
               'top5': round(hits(gte, b, 5), 3), 'top10': round(hits(gte, b, 10), 3), 'top10Uniform': round(float(np.mean([10 / len(X) for X, _ in gte])), 3)}
    bh, sh = clogit([(X, c) for X, c, _ in G])
    print('hires from head jobs', len(G), hc_test, dict(zip(HC_X, np.round(bh, 2))))

    def a_cands(t, y):
        jl = P.level(t, y); med = top2_median(P, y); res = []
        for (j, yy), aa in P.ast.items():
            if yy != y or P.level(j, y) not in ('P4', 'G5'): continue
            for pay, aid, name in aa[:2]:
                res.append((norm(name), coord_x(pay / med, P.win.get((j, y)), P.level(j, y), P.conf.get((t, y)) == P.conf.get((j, y)),
                                                0 if j == t else miles(P.loc.get(t), P.loc.get(j)), j == t, jl)))
        return res
    GA = []
    for t, y, c1, o in ev:
        if o != 'coord': continue
        cs = a_cands(t, y); ids = [c for c, _ in cs]; n = norm(P.cname[c1])
        if n in ids: GA.append((np.array([x for _, x in cs]), ids.index(n), y))
    atr = [(X, c) for X, c, y in GA if y <= 2018]; ate = [(X, c) for X, c, y in GA if y > 2018]
    b, _ = clogit(atr)
    a_test = {'n': len(ate), 'seasons': '2019-24', 'logLik': round(-cll(ate, b), 3), 'logLikUniform': round(-float(np.mean([math.log(len(X)) for X, _ in ate])), 3),
              'top5': round(hits(ate, b, 5), 3), 'top10': round(hits(ate, b, 10), 3), 'top10Uniform': round(float(np.mean([10 / len(X) for X, _ in ate])), 3)}
    ba, sa = clogit([(X, c) for X, c, _ in GA])
    print('hires from coordinators', len(GA), a_test, dict(zip(COORD_X, np.round(ba, 2))))
    out['hire'] = {'share': share,
                   'hc': {'names': HC_X, 'coef': [round(float(x), 4) for x in bh], 'se': [round(float(x), 4) for x in sh], 'n': len(G), 'test': hc_test},
                   'coord': {'names': COORD_X, 'coef': [round(float(x), 4) for x in ba], 'se': [round(float(x), 4) for x in sa], 'n': len(GA), 'test': a_test}}

    # 3. coordinator turnover: the two best-paid assistants a year on, by what happened to the head coach ------
    at_ = {}
    for (t, y), aa in P.ast.items():
        for pay, aid, name in aa: at_[(norm(name), y)] = t
    head_at = {(norm(P.cname[c]), y): t for (t, y), c in P.coach.items()}
    C = Counter()
    for (t, y), aa in P.ast.items():
        if y < 2010 or y > 2023 or y == 2019 or not P.ast.get((t, y + 1)): continue   # 2020's assistant list is half filled
        c, c1 = P.coach.get((t, y)), P.coach.get((t, y + 1))
        if not c or not c1: continue
        w = P.where.get((c, y + 1)); k = 0 if c1 == c else 1 if w and w[1] == 'Head' and w[0] != t else 2
        for pay, aid, name in aa[:2]:
            n = norm(name); t1 = at_.get((n, y + 1))
            o = 'promoted' if (n, y + 1) in head_at else 'stay' if t1 == t else 'follow' if k == 1 and t1 == w[0] else 'left'
            C[(k, o)] += 1
    turn = {}
    for k, lab in enumerate(('stay', 'moved', 'out')):
        n = sum(v for (kk, _), v in C.items() if kk == k)
        turn[lab] = {'n': n, **{o: round(C[(k, o)] / n, 4) for o in ('stay', 'follow', 'promoted', 'left')}}
    print('coordinator turnover by head coach outcome', turn)
    out['turnover'] = turn

    # 4. market value -----------------------------------------------------------------------------------------
    rows = []
    for c in D['coaches']:
        if c['role'] != 'HC': continue
        t = c['tid']; cid = P.coach.get((t, 2025)); pay = P.pay.get((t, 2025))
        if not cid or not pay or norm(P.cname[cid]) != norm(c['name']): continue
        rows.append({'y': math.log(pay), **hc_value_x(c, T[t], [P.win.get((t, y)) for y in (2023, 2024, 2025)], P.level(t, 2025))})
    out['valueHC'] = value_fit(rows, VALUE_HC, 'value HC')
    apay = latest_assistant_pay(P)
    rows = []
    for c in D['coaches']:
        if c['role'] == 'HC': continue
        names = c['name'].split(' / ')
        for n in names:
            h = apay.get(norm(n))
            if not h or h['tid'] != c['tid'] or h['year'] < 2024: continue
            hp = P.pay.get((c['tid'], 2025))
            if not hp: continue
            rows.append({'y': math.log(h['pay']), **coord_value_x(c, T[c['tid']], hp, len(names), P.level(c['tid'], 2025))})
    out['valueCoord'] = value_fit(rows, VALUE_COORD, 'value coordinators')
    return out


HC_X = ['payStep', 'wp', 'vsNorm', 'up', 'down', 'sameConf', 'logDist', 'yr1']
COORD_X = ['payRel', 'payRelG5', 'wp', 'p4', 'p4G5', 'sameConf', 'logDist', 'internal']
VALUE_HC = ['p4', 'rec', 'elo', 'tve', 'znil', 'score', 'goOe', 'proe', 'w3', 'w1']
VALUE_COORD = ['p4', 'rec', 'hcPay', 'score', 'over', 'dev', 'znil', 'oc', 'co']


def hc_x(x, job_pay, cand_pay, jl, cl, same_conf, dist):
    """a sitting head coach as a candidate for a job: the pay step up, his season, the level step, ties"""
    return [math.log(job_pay / cand_pay), x['wp'], x['vsNorm'], float(cl == 'G5' and jl == 'P4'), float(cl == 'P4' and jl == 'G5'),
            float(same_conf), math.log1p((dist if dist is not None else 800) / 100), x['yr1']]


def coord_x(pay_rel, school_wp, lv, same_conf, dist, internal, job_lv):
    """a coordinator as a candidate: his pay against the median coordinator (and again when the job is in the
    Group of Five, where the best-paid P4 coordinators rarely go), his school's season, level, ties"""
    g5 = float(job_lv == 'G5')
    return [math.log(pay_rel), g5 * math.log(pay_rel), (school_wp if school_wp is not None else 0.5) - 0.5, float(lv == 'P4'), g5 * float(lv == 'P4'),
            float(same_conf), math.log1p((dist if dist is not None else 800) / 100), float(internal)]


def hc_value_x(c, team, wins, lv):
    s = c.get('scheme') or {}; w = [x for x in wins if x is not None] or [0.5]
    return {'p4': float(lv == 'P4'), 'rec': team.get('recruited') or 0.0, 'elo': team.get('eloZ') or 0.0, 'tve': team.get('tve') or 0.0,
            'znil': c.get('znilV') or 0.0, 'score': (c['score'] - 100) / 10, 'goOe': s.get('goOe') or 0.0, 'proe': s.get('proe') or 0.0,
            'w3': float(np.mean(w)) - 0.5, 'w1': (wins[-1] if wins[-1] is not None else w[-1]) - 0.5}


def coord_value_x(c, team, hc_pay, n_names, lv):
    return {'p4': float(lv == 'P4'), 'rec': team.get('recruited') or 0.0, 'hcPay': math.log(hc_pay), 'score': (c['score'] - 100) / 10,
            'over': c.get('over') or 0.0, 'dev': (c.get('dev') or 0.0) / 10, 'znil': c.get('znilV') or 0.0, 'oc': float(c['role'] == 'OC'), 'co': float(n_names > 1)}


def level_median(P, y, lv):
    v = [p for (t, yy), p in P.pay.items() if yy == y and p and P.level(t, yy) == lv]
    return float(np.median(v)) if v else 1e6


def top2_median(P, y):
    v = [a[0] for (t, yy), aa in P.ast.items() if yy == y for a in aa[:2]]
    return float(np.median(v)) if v else 5e5


def latest_assistant_pay(P):
    out = {}
    for (t, y), aa in P.ast.items():
        for i, (pay, aid, name) in enumerate(aa):
            n = norm(name)
            if n not in out or y > out[n]['year']: out[n] = {'name': name, 'tid': t, 'year': y, 'pay': pay, 'rank': i}
    return out


# ---- history for the weekly scorer (data/cfb_coach_pay.json) -----------------------------------------------
def history(P, D):
    """What scripts/cfb_coach.mjs needs that the weekly board doesn't have: each school's 2025 coach, his start,
    pay and buyout, its records, its level this season; each 2025 head coach's pay and seasons by name; the
    latest pay of every assistant on a 2023-24 staff."""
    teams = {}
    tids = {t['tid'] for t in D['teams']} | {t for (t, y) in P.coach}
    buy = {h['tid']: h.get('buyout') for h in P.heads}
    for t in sorted(tids):
        c = P.coach.get((t, 2025))
        ten, cens = P.tenure(t, 2025) if c else (None, None)
        teams[t] = {'school': P.school.get(t), 'coach': P.cname.get(c) if c else None, 'start': 2025 - ten + 1 if ten else None, 'censored': bool(cens),
                    'pay': P.pay.get((t, 2025)), 'buyout': buy.get(t), 'level': P.level(t, 2026) or P.level(t, 2025), 'conf': P.conf.get((t, 2026)),
                    'wins': {str(y): round(P.win[(t, y)], 4) for y in range(2014, 2026) if (t, y) in P.win}}
    heads = {}
    for (t, y), c in P.coach.items():
        if y not in (2023, 2024, 2025) or str(c).startswith('new:'): continue
        h = heads.setdefault(norm(P.cname[c]), {'name': P.cname[c], 'wins': {}})
        if (t, y) in P.win: h['wins'][str(y)] = round(P.win[(t, y)], 4)
        if y == 2025: h['tid'], h['pay'] = t, P.pay.get((t, y))
    ast = {n: a for n, a in latest_assistant_pay(P).items() if a['year'] >= 2023}
    return {'asof': time.strftime('%Y-%m-%d'),
            '_readme': 'USA Today NCAA salary database (public schools; private schools report no pay) and ESPN records; built by scripts/cfb_coach_fit.py',
            'medians': {'P4': level_median(P, 2025, 'P4'), 'G5': level_median(P, 2025, 'G5'), 'coord': top2_median(P, 2024)},
            'teams': teams, 'heads': heads, 'assistants': ast}


def main():
    if OFFLINE and os.path.exists(os.path.join(CACHE, 'pull.json')):
        heads, hs, asst, car, recs, confs = load_pull()
    else:
        heads, hs, asst, car, recs, confs = pull(); save_pull(heads, hs, asst, car, recs, confs)
    P = Panel(heads, hs, asst, car, recs, confs)
    D = json.load(open(os.path.join(ROOT, 'data', 'cfb_teams.json')))
    out = fit(P, D)
    json.dump(out, open(OUT, 'w'), indent=1)
    json.dump(history(P, D), open(PAY_OUT, 'w'), separators=(',', ':'))
    print('wrote', OUT, PAY_OUT)


def save_pull(heads, hs, asst, car, recs, confs):
    json.dump({'heads': heads, 'hs': hs, 'asst': asst, 'car': car, 'recs': [[s, t, v] for (s, t), v in recs.items()],
               'confs': [[s, t, v] for (s, t), v in confs.items()]}, open(os.path.join(CACHE, 'pull.json'), 'w'))


def load_pull():
    d = json.load(open(os.path.join(CACHE, 'pull.json')))
    tup = lambda v: {k: [tuple(r) for r in rows] for k, rows in v.items()}
    return (d['heads'], tup(d['hs']), tup(d['asst']), tup(d['car']), {(s, t): (tuple(v) if v else None) for s, t, v in d['recs']},
            {(s, t): v for s, t, v in d['confs']})


if __name__ == '__main__':
    main()
