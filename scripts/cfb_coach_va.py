#!/usr/bin/env python3
"""Head-coach value-added: what a coach adds to his team's rating beyond the program he took over and the talent
on the roster, measured where it can be checked: on coaches who changed jobs.

    python3 scripts/cfb_coach_va.py            # pull (cached in scripts/.cache/coachva/), build, test, write
    python3 scripts/cfb_coach_va.py --offline  # rebuild from the cached pulls only

Data (all free):
  games     ESPN scoreboards 2005-25, every game with an FBS team (regular season + bowls). FCS opponents are
            pooled into one team per season.
  rating    SRS per team-season: ridge least squares on scoring margin (capped at 28) with a home edge.
  talent    ESPN recruiting 2006-25 (signed school, grade): each class's points (247-style, 0.915^rank decay over
            the team's signees, grade above 70), the four classes on the roster weighted .15/.25/.30/.30 (seniors to
            freshmen are a guess at snap shares), z-scored within the season.
  coaches   head coach per team-season from the Wikipedia season-page infobox ('<year> <team> football team');
            a season with two head coaches (a mid-season change) is left out of every estimate.

Model. Each team-season's rating SRS_jt is set against what the program and roster alone would give:
    E[SRS_jt] = a + b1 base_j + b2 tal_jt (+ b3 tal_jt x P4)
where base_j is the program's rating before the coach got there (the mean SRS of the three seasons before his
first, shrunk to the league) and tal_jt the roster's talent. A coach's value-added is the mean residual over his
seasons, shrunk empirically (signal variance over noise variance per season). With talent in the expectation it is
on-field value (development and scheme); without it, total value (recruiting included).

Test (pre-registered in the brief): two-way fixed effects (coach + program), identified by movers, judged on held-
out movers. For every coach who took a new FBS head job in season Y, everything is fit on seasons before Y only:
the expectation, his old-job value-added and the shrinkage. His new-job residual (new seasons, new program's prior)
is the target. Pass: slope of new-job residual on the old-job estimate > 0 with t >= 2, and lower squared error
than predicting zero (no coach effect), paired t <= -2. Writes data/cfb_coach_va.json.
"""
import concurrent.futures as cf
import hashlib
import json
import math
import os
import re
import sys
import time
from collections import defaultdict

import numpy as np
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'coachva')
OUT = os.path.join(ROOT, 'data', 'cfb_coach_va.json')
OFFLINE = '--offline' in sys.argv
SITE = 'https://site.api.espn.com/apis/site/v2/sports/football/college-football'
CORE = 'https://sports.core.api.espn.com/v2/sports/football/leagues/college-football'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'
WIKI_UA = 'arkndjl.net ARKBOARD (https://arkndjl.net; site maintenance)'
SEASONS = list(range(2005, 2026))
CLASSES = list(range(2006, 2026))
os.makedirs(CACHE, exist_ok=True)
S = requests.Session(); S.headers['User-Agent'] = UA


def get(url, headers=None):
    """GET JSON, cached on disk by URL forever (past seasons don't change)."""
    f = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest() + '.json')
    if os.path.exists(f):
        with open(f) as h: return json.load(h)
    if OFFLINE: return None
    v = None
    for i in range(5):
        try:
            r = S.get(url, timeout=30, headers=headers)
            if r.status_code == 404: break
            if r.status_code == 429: time.sleep(10 * 2 ** i); continue
            r.raise_for_status(); v = r.json(); break
        except Exception:
            time.sleep(1 + 2 * i)
    else:
        return None
    tmp = f'{f}.{os.getpid()}.{id(v)}'
    with open(tmp, 'w') as h: json.dump(v, h)
    os.replace(tmp, f)   # threads can ask for the same URL (a conference page): never read a half-written file
    return v


def pmap(fn, xs, n=16):
    with cf.ThreadPoolExecutor(n) as ex: return list(ex.map(fn, xs))


def rid(ref): return re.search(r'/(\d+)(?:\?|$)', ref['$ref'] if isinstance(ref, dict) else ref).group(1)


def norm(s):
    s = (s or '').lower().replace('&', 'and')
    s = re.sub(r'\b(jr|sr|ii|iii|iv)\b\.?', '', s)
    return re.sub(r'[^a-z]', '', s)


# ---- pulls ---------------------------------------------------------------------------------------------
def fbs_teams(season):
    d = get(f'{CORE}/seasons/{season}/types/2/groups/80/teams?limit=400') or {}
    return [rid(x) for x in d.get('items', [])]


def team_meta(season, tid):
    t = get(f'{CORE}/seasons/{season}/teams/{tid}') or {}
    conf = None
    if t.get('groups'):
        g = get(t['groups']['$ref'].replace('http://', 'https://')) or {}
        if g.get('isConference') is False and g.get('parent'): g = get(g['parent']['$ref'].replace('http://', 'https://')) or g
        conf = g.get('shortName') or g.get('abbreviation') or g.get('name')
    return {'name': t.get('location'), 'full': t.get('displayName'), 'conf': conf}


def games(season):
    out = {}
    for st, weeks in ((2, range(1, 17)), (3, [1])):
        for w in weeks:
            d = get(f'{SITE}/scoreboard?dates={season}&seasontype={st}&week={w}&groups=80&limit=500') or {}
            for e in d.get('events', []):
                if not e.get('competitions'): continue
                c = e['competitions'][0]
                if not c.get('status', {}).get('type', {}).get('completed'): continue
                t = {x['homeAway']: x for x in c['competitors']}
                if 'home' not in t or 'away' not in t: continue
                try: hs, as_ = int(t['home']['score']), int(t['away']['score'])
                except (TypeError, ValueError): continue
                out[e['id']] = (t['home']['team']['id'], t['away']['team']['id'], hs, as_, int(bool(c.get('neutralSite'))))
    return list(out.values())


def recruits(year):
    """signed recruits of one class: [(team id, grade)]"""
    first = get(f'{CORE}/recruiting/{year}/athletes?limit=1000&page=1') or {}
    items = list(first.get('items', []))
    for p in range(2, first.get('pageCount', 1) + 1): items += (get(f'{CORE}/recruiting/{year}/athletes?limit=1000&page={p}') or {}).get('items', [])
    out = []
    for it in items:
        g = it.get('grade')
        sc = [x for x in it.get('schools') or [] if (x.get('status') or {}).get('id') == 3 and x.get('team')]
        if g and sc: out.append((rid(sc[0]['team']), float(g)))
    return out


def wiki_hc(titles):
    """head coach(es) in each '<season> <team> football team' infobox: {title: [names]}"""
    out = {}
    for i in range(0, len(titles), 50):
        chunk = titles[i:i + 50]
        url = ('https://en.wikipedia.org/w/api.php?action=query&format=json&prop=revisions&rvprop=content&rvslots=main'
               '&rvsection=0&redirects=1&titles=' + requests.utils.quote('|'.join(chunk)))
        f = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest() + '.json')
        if os.path.exists(f): d = json.load(open(f))
        elif OFFLINE: continue
        else:
            for k in range(12):   # Wikimedia answers bursts with 429 and a Retry-After: wait it out
                r = requests.get(url, headers={'User-Agent': WIKI_UA}, timeout=30)
                if r.status_code != 429: break
                time.sleep(int(r.headers.get('retry-after') or 30) + 2)
            if r.status_code != 200: print('wikipedia', r.status_code); continue
            d = r.json(); json.dump(d, open(f, 'w')); time.sleep(2)
        back = {}
        for n in (d['query'].get('normalized') or []): back[n['to']] = n['from']
        for n in (d['query'].get('redirects') or []): back[n['to']] = back.get(n['from'], n['from'])
        for pg in d['query']['pages'].values():
            rv = pg.get('revisions')
            if not rv: continue
            txt = rv[0]['slots']['main']['*']
            # head_coach, then head_coach2 / head_coach3 for a mid-season change
            ms = re.findall(r'\|\s*head_coach\d?\s*=(.*?)(?=\n\s*\||\n\}\})', txt, re.S)
            if not ms: continue
            v = re.sub(r'<ref.*?(</ref>|/>)', '', '<br>'.join(ms), flags=re.S)
            v = re.sub(r'\{\{(?:sortname|nowrap)\|([^}|]+)\|([^}|]+)[^}]*\}\}', r'[[\1 \2]]', v, flags=re.I)
            names = [re.sub(r'\s*\(.*?\)', '', n).strip() for n in re.findall(r'\[\[([^\]|#]+)', v)]
            if not names: names = [x.strip() for x in re.split(r'<br\s*/?>|,|\(|;', v) if x.strip() and not x.strip().startswith(')')][:2]
            names = [n for n in names if n and not re.search(r'interim|^\d|season', n, re.I)]
            out[back.get(pg['title'], pg['title'])] = names
    return out


# Wikipedia's team name where ESPN's display name isn't a title or redirect
WIKI_NAME = {'62': 'Hawaii Rainbow Warriors', '193': 'Miami RedHawks', '2572': 'Southern Miss Golden Eagles', '2229': 'FIU Panthers',
             '2433': 'Louisiana–Monroe Warhawks', '113': 'UMass Minutemen', '2636': 'UTSA Roadrunners', '23': 'San Jose State Spartans',
             '2026': 'Appalachian State Mountaineers'}


def pull():
    teams = {s: fbs_teams(s) for s in SEASONS}
    jobs = [(s, t) for s in SEASONS for t in teams[s]]
    meta = dict(zip(jobs, pmap(lambda j: team_meta(*j), jobs, 16)))
    g = dict(zip(SEASONS, pmap(games, SEASONS, 8)))
    rec = dict(zip(CLASSES, pmap(recruits, CLASSES, 4)))
    titles = {}
    cur = {}
    for (s, t), m in meta.items():
        if m.get('full'): cur.setdefault(t, m['full'])
    for (s, t), m in meta.items():
        full = WIKI_NAME.get(t) or m.get('full') or cur.get(t)
        if full: titles[(s, t)] = f'{s} {full} football team'
    hc = wiki_hc(sorted(set(titles.values())))
    coach = {k: hc.get(v) for k, v in titles.items()}
    print('teams', sum(map(len, teams.values())), 'games', sum(map(len, g.values())), 'recruits', sum(map(len, rec.values())),
          'coached seasons', sum(1 for v in coach.values() if v))
    return teams, meta, g, rec, coach


# ---- ratings and talent ------------------------------------------------------------------------------------
CAP = 28


def srs(gs, fbs):
    """team rating per FBS team (points vs an average FBS team), FCS pooled; ridge so a thin schedule shrinks"""
    ix = {t: i for i, t in enumerate(sorted(fbs))}; F = len(ix)
    rows, y = [], []
    for h, a, hs, as_, neu in gs:
        if h not in ix and a not in ix: continue
        x = np.zeros(F + 2)
        x[ix.get(h, F)] += 1; x[ix.get(a, F)] -= 1; x[F + 1] = 0 if neu else 1
        rows.append(x); y.append(max(-CAP, min(CAP, hs - as_)))
    X, y = np.array(rows), np.array(y, float)
    pen = np.full(F + 2, 0.5); pen[F + 1] = 0
    b = np.linalg.solve(X.T @ X + np.diag(pen), X.T @ y)
    r = b[:F] - b[:F].mean()
    return {t: float(r[i]) for t, i in ix.items()}, float(b[F + 1]), float(b[F] - b[:F].mean())


W_CLASS = [0.30, 0.30, 0.25, 0.15]   # this year's class (freshmen) back to the class four years ago (seniors)


def talent(rec, fbs_by):
    pts = defaultdict(float)
    for y, xs in rec.items():
        by = defaultdict(list)
        for t, g in xs: by[t].append(g)
        for t, gs in by.items():
            gs.sort(reverse=True)
            pts[(y, t)] = sum(max(g - 70, 0) * 0.915 ** i for i, g in enumerate(gs))
    out = {}
    for s, ts in fbs_by.items():
        v = {}
        for t in ts:
            ws = [(w, pts.get((s - k, t), 0.0)) for k, w in enumerate(W_CLASS) if s - k in rec]
            if ws: v[t] = sum(w * p for w, p in ws) / sum(w for w, _ in ws)
        if len(v) < 50: continue
        a = np.array(list(v.values())); mu, sd = a.mean(), a.std()
        for t, x in v.items(): out[(s, t)] = (x - mu) / sd
    return out


# ---- panel -----------------------------------------------------------------------------------------------
P4_NAMES = {'SEC', 'Big Ten', 'Big 12', 'ACC', 'Pac-12'}   # power conferences of the season (Pac-12 through 2023)


def panel(teams, meta, g, rec, coach):
    ng = defaultdict(int)
    for s in SEASONS:
        for h, a, *_ in g[s]: ng[(s, h)] += 1; ng[(s, a)] += 1
    teams = {s: [t for t in ts if ng[(s, t)] >= 6] for s, ts in teams.items()}   # all-star exhibition teams sit in ESPN's FBS group
    rat, home = {}, {}
    for s in SEASONS:
        r, hf, fcs = srs(g[s], teams[s]); home[s] = round(hf, 2)
        for t, v in r.items(): rat[(s, t)] = v
    tal = talent(rec, teams)
    rows = []
    for s in SEASONS:
        for t in teams[s]:
            m = meta.get((s, t)) or {}
            hcs = coach.get((s, t)) or []
            conf = m.get('conf') or ''
            p4 = int(conf in P4_NAMES and not (conf == 'Pac-12' and s >= 2024)) or int(t == '87')
            rows.append({'s': s, 't': t, 'name': m.get('name'), 'conf': conf, 'p4': p4, 'srs': rat.get((s, t)), 'tal': tal.get((s, t)),
                         'hc': [norm(h) for h in hcs], 'hcName': hcs})
    return rows, home


def tenures(rows):
    """per (team, coach) stint: first season, seasons; a coach's career in order"""
    by_t = defaultdict(dict)
    for r in rows: by_t[r['t']][r['s']] = r
    for t, ss in by_t.items():
        for s in sorted(ss):
            r = ss[s]
            r['sole'] = r['hc'][0] if len(r['hc']) == 1 else None
            # stint start: walk back while the same coach is listed (alone or as one of two in a split season)
            c = r['sole']
            if not c: continue
            k = s
            while (k - 1) in ss and c in ss[k - 1]['hc']: k -= 1
            r['start'] = k; r['yr'] = s - k + 1
            # the program before him: the three seasons before his first (other coaches)
            pre = [ss[k - j]['srs'] for j in (1, 2, 3) if (k - j) in ss and ss[k - j]['srs'] is not None]
            r['base'] = float(np.mean(pre)) if pre else None
            r['baseN'] = len(pre)
            pt = [ss[k - j]['tal'] for j in (1, 2, 3) if (k - j) in ss and ss[k - j].get('tal') is not None]
            r['baseTal'] = float(np.mean(pt)) if pt else None
    return by_t


# ---- value-added -----------------------------------------------------------------------------------------
def design(r, total):
    """the expectation's inputs for one team-season: program before the coach, talent (on-field) or the talent he
    inherited (total value: recruiting counts as his)"""
    tal = r['baseTal'] if total else r['tal']
    return [1.0, r['base'], tal if tal is not None else 0.0, float(tal is None), r['p4']]


def usable(r): return r.get('sole') and r.get('base') is not None and r['srs'] is not None and r.get('baseN', 0) >= 2


def ols(X, y, lam=1e-6):
    X, y = np.array(X), np.array(y)
    return np.linalg.solve(X.T @ X + lam * np.eye(X.shape[1]), X.T @ y)


def shrink_k(res_by_coach):
    """noise-to-signal ratio k for VA = sum(res) / (n + k): coach signal is the covariance of his residual means on
    odd and even seasons (split half), noise the within-coach variance"""
    a, b, within = [], [], []
    for xs in res_by_coach.values():
        if len(xs) >= 4:
            a.append(np.mean(xs[0::2])); b.append(np.mean(xs[1::2]))
        if len(xs) >= 2: within.append(np.var(xs, ddof=1))
    sig_c = max(float(np.cov(a, b)[0, 1]), 1e-3) if len(a) > 10 else 1.0
    return float(np.mean(within)) / sig_c, sig_c, float(np.mean(within))


def fit_va(rows, total, before=None):
    """expectation + shrunk coach VA on seasons before `before`. Returns (coef, k, va: coach -> (va, n), res)"""
    tr = [r for r in rows if usable(r) and (before is None or r['s'] < before)]
    b = ols([design(r, total) for r in tr], [r['srs'] for r in tr])
    res = defaultdict(list)
    for r in sorted(tr, key=lambda r: r['s']): res[r['sole']].append(r['srs'] - float(np.dot(b, design(r, total))))
    k, sig_c, sig_e = shrink_k(res)
    va = {c: (sum(xs) / (len(xs) + k), len(xs)) for c, xs in res.items()}
    return b, k, va, sig_c, sig_e


def hand_score(rows, before, c):
    """the live HC score's analog on the old job: .5 team strength z (Elo) + .5 results over talent (TvE)"""
    xs = [r for r in rows if r.get('sole') == c and r['s'] < before and r['srs'] is not None and r['tal'] is not None]
    return xs


def akm(rows, before, total, lam_c, lam_p=1.0):
    """two-way fixed effects: srs = program + coach + talent (+ P4) on sole-coach seasons before `before`;
    ridge on both sets of effects (coach effects shrink to zero, a program's to the league)"""
    tr = [r for r in rows if r.get('sole') and r['srs'] is not None and r['s'] < before]
    P = sorted({r['t'] for r in tr}); C = sorted({r['sole'] for r in tr})
    pi = {p: i for i, p in enumerate(P)}; ci = {c: i for i, c in enumerate(C)}
    k0 = 3
    X = np.zeros((len(tr), k0 + len(P) + len(C))); y = np.zeros(len(tr))
    for n, r in enumerate(tr):
        tal = (r.get('baseTal') if total else r['tal'])
        X[n, 0] = 1; X[n, 1] = tal if tal is not None else 0.0; X[n, 2] = r['p4']
        X[n, k0 + pi[r['t']]] = 1; X[n, k0 + len(P) + ci[r['sole']]] = 1; y[n] = r['srs']
    pen = np.r_[np.zeros(k0), np.full(len(P), lam_p), np.full(len(C), lam_c)]
    b = np.linalg.solve(X.T @ X + np.diag(pen + 1e-8), X.T @ y)
    return b[:k0], {p: b[k0 + i] for p, i in pi.items()}, {c: b[k0 + len(P) + i] for c, i in ci.items()}


def movers(rows):
    """coaches who took an FBS head job after holding one: (coach, new team, first season, old teams)"""
    stints = defaultdict(dict)
    for r in rows:
        if r.get('sole'): stints[r['sole']].setdefault(r['t'], []).append(r['s'])
    out = []
    for c, ts in stints.items():
        order = sorted(ts.items(), key=lambda kv: min(kv[1]))
        for i in range(1, len(order)):
            t, ss = order[i]
            Y = min(ss)
            old = [o for o, s2 in order[:i] if min(s2) < Y]
            if old: out.append((c, t, Y, old))
    return out


def stats(pred, y):
    pred, y = np.array(pred), np.array(y)
    X = np.c_[np.ones(len(pred)), pred]
    b = np.linalg.lstsq(X, y, rcond=None)[0]; e = y - X @ b
    # heteroskedasticity-robust (HC1) standard error of the slope
    XtXi = np.linalg.inv(X.T @ X); meat = (X * e[:, None] ** 2).T @ X
    se = math.sqrt((XtXi @ meat @ XtXi)[1, 1] * len(y) / (len(y) - 2))
    d = (y - pred) ** 2 - y ** 2   # squared error vs predicting no coach effect
    return {'n': len(y), 'slope': round(float(b[1]), 3), 'slopeT': round(float(b[1] / se), 2), 'corr': round(float(np.corrcoef(pred, y)[0, 1]), 3),
            'mse': round(float(np.mean((y - pred) ** 2)), 2), 'mse0': round(float(np.mean(y ** 2)), 2),
            'gainT': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2)}


def residual(rows, b, total):
    return {(r['s'], r['t']): r['srs'] - float(np.dot(b, design(r, total))) for r in rows if usable(r)}


def mover_test(rows, total, max_new=4):
    """held-out movers: everything fit on seasons before the move; target = mean residual of his first max_new
    seasons at the new job. Predictors: shrunk old-job VA (residual model), two-way FE coach effect, and the live
    hand-weighted score's analog (.5 team-strength z + .5 results over talent, his old-job mean)"""
    mv = movers(rows)
    by = defaultdict(list)
    for c, t, Y, old in mv: by[Y].append((c, t))
    P = defaultdict(list)
    for Y in sorted(by):
        if Y < 2009: continue
        b, k, va, _, _ = fit_va(rows, total, before=Y)
        bt, prog, ceff = akm(rows, Y, total, lam_c=AKM_LAM)
        # hand score parts on seasons before Y: SRS z within season, results over talent (SRS on talent, pooled)
        tr = [r for r in rows if r['s'] < Y and r['srs'] is not None and r['tal'] is not None]
        g = ols([[1, r['tal']] for r in tr], [r['srs'] for r in tr])
        sd = np.std([r['srs'] for r in tr])
        allres = residual(rows, b, total)
        for c, t in by[Y]:
            new = [r for r in rows if r['t'] == t and r.get('sole') == c and Y <= r['s'] < Y + max_new and usable(r)]
            if not new or c not in va: continue
            y = float(np.mean([allres[(r['s'], r['t'])] for r in new]))
            olds = [r for r in rows if r.get('sole') == c and r['s'] < Y and r['srs'] is not None and r['tal'] is not None]
            hand = float(np.mean([0.5 * r['srs'] / sd + 0.5 * (r['srs'] - g[0] - g[1] * r['tal']) / sd for r in olds])) if olds else 0.0
            # two-way FE target: new seasons over the new program's effect and talent (program effect from his predecessors)
            y2 = None
            if t in prog:
                y2 = float(np.mean([r['srs'] - bt[0] - bt[1] * ((r.get('baseTal') if total else r['tal']) or 0.0) - bt[2] * r['p4'] - prog[t] for r in new]))
            P['va'].append((va[c][0], y)); P['hand'].append((hand, y)); P['n'].append(va[c][1])
            if y2 is not None and c in ceff: P['akm'].append((ceff[c], y2))
            P['rows'].append({'coach': c, 'to': t, 'Y': Y, 'va': round(va[c][0], 2), 'nOld': va[c][1], 'hand': round(hand, 2), 'y': round(y, 2), 'nNew': len(new)})
    out = {m: stats(*zip(*P[m])) for m in ('va', 'akm', 'hand') if len(P[m]) > 10}
    # the hand score is a z, not points: its slope is the scale, so judge it by correlation (and by the VA's gain on top)
    return out, P['rows']


AKM_LAM = 4.0


def walk_forward(rows, total, lam=1.0, min_train=25):
    """the fairest version of the question: learn how a coach's old-job record maps to his new-job residual from
    the movers before him (ridge, walk-forward by move year), and score each mover against the movers' mean.
    Old-job features, all on seasons before the move: res (his mean residual, the value-added), lvl (team rating
    z: the live score's Elo half), ot (rating over talent z: its TvE half)"""
    mv = movers(rows); by = defaultdict(list)
    for c, t, Y, _ in mv: by[Y].append((c, t))
    D = []
    for Y in sorted(by):
        if Y < 2009: continue
        b, _, _, _, _ = fit_va(rows, total, before=Y)
        tr = [r for r in rows if r['s'] < Y and r['srs'] is not None and r['tal'] is not None]
        g = ols([[1, r['tal']] for r in tr], [r['srs'] for r in tr]); sd = float(np.std([r['srs'] for r in tr]))
        res = residual(rows, b, total)
        for c, t in by[Y]:
            new = [r for r in rows if r['t'] == t and r.get('sole') == c and Y <= r['s'] < Y + 4 and usable(r)]
            olds = [r for r in rows if r.get('sole') == c and r['s'] < Y and r['srs'] is not None and r['tal'] is not None]
            ores = [res[(r['s'], r['t'])] for r in olds if (r['s'], r['t']) in res]
            if not new or not olds: continue
            D.append({'Y': Y, 'y': float(np.mean([res[(r['s'], r['t'])] for r in new])),
                      'res': float(np.mean(ores)) / sd if ores else 0.0, 'lvl': float(np.mean([r['srs'] for r in olds])) / sd,
                      'ot': float(np.mean([r['srs'] - g[0] - g[1] * r['tal'] for r in olds])) / sd})
    out = {}
    for fs in (['res'], ['lvl'], ['ot'], ['lvl', 'ot'], ['lvl', 'ot', 'res']):
        pred, ys, base = [], [], []
        for d in D:
            tr = [e for e in D if e['Y'] < d['Y']]
            if len(tr) < min_train: continue
            X = np.array([[1.0] + [e[f] for f in fs] for e in tr]); yy = np.array([e['y'] for e in tr])
            bb = np.linalg.solve(X.T @ X + lam * np.diag([0.0] + [1.0] * len(fs)), X.T @ yy)
            pred.append(float(np.dot([1.0] + [d[f] for f in fs], bb))); ys.append(d['y']); base.append(float(yy.mean()))
        pred, ys, base = map(np.array, (pred, ys, base))
        dd = (ys - pred) ** 2 - (ys - base) ** 2
        out['+'.join(fs)] = {'n': len(ys), 'corr': round(float(np.corrcoef(pred, ys)[0, 1]), 3), 'mse': round(float(np.mean((ys - pred) ** 2)), 2),
                             'mseBase': round(float(np.mean((ys - base) ** 2)), 2), 'gainT': round(float(dd.mean() / (dd.std(ddof=1) / math.sqrt(len(dd)))), 2)}
    return out


def main():
    teams, meta, g, rec, coach = pull()
    rows, home = panel(teams, meta, g, rec, coach)
    tenures(rows)
    res = {}
    for total in (False, True):
        key = 'total' if total else 'onField'
        b, k, va, sig_c, sig_e = fit_va(rows, total)
        movers_out, mrows = mover_test(rows, total)
        res[key] = {'expect': dict(zip(['const', 'base', 'talent', 'talentMissing', 'p4'], [round(float(x), 3) for x in b])),
                    'shrinkK': round(k, 2), 'coachSd': round(math.sqrt(sig_c), 2), 'seasonSd': round(math.sqrt(sig_e), 2),
                    'movers': movers_out, 'walkForward': walk_forward(rows, total)}
        print(key, json.dumps(res[key]))
    # pass: the VA (or the two-way FE coach effect) predicts new-job residuals on held-out movers, slope t >= 2,
    # and beats predicting no coach effect, paired t <= -2; and the walk-forward version beats the movers' mean
    ok = {k: any(v['movers'].get(m, {}).get('slopeT', 0) >= 2 and v['movers'].get(m, {}).get('gainT', 0) <= -2 for m in ('va', 'akm'))
          and v['walkForward']['res']['gainT'] <= -2 for k, v in res.items()}
    out = {'asof': time.strftime('%Y-%m-%d'), 'seasons': [SEASONS[0], SEASONS[-1]], 'teamSeasons': len(rows),
           'usable': sum(1 for r in rows if usable(r)), 'movers': len(movers(rows)), 'homeEdge': home, 'results': res, 'pass': ok,
           'shipped': any(ok.values()),
           'note': 'Fails: a head coach\'s value-added at his old job (rating over the program he took over and his roster talent) '
                   'does not carry to his new job. Staff scores keep their hand weights.' if not any(ok.values()) else None}
    with open(OUT, 'w') as h: json.dump(out, h, indent=1)
    print('pass', ok, 'wrote', OUT)


if __name__ == '__main__':
    main()
