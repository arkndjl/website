#!/usr/bin/env python3
"""Fit Recruit FV (data/cfb_recruit_fit.json): what FV a high school recruit grows into, from past classes.

    python3 scripts/cfb_recruit_fit.py            # pull ESPN's classes (cached in scripts/.cache/recruit/), fit
    python3 scripts/cfb_recruit_fit.py --offline  # refit from the cached pulls only

Sample: ESPN's recruiting classes 2022-2026 (every ranked and unranked signee it lists), each followed to
this season's board (static/data/cfb-all.json, FBS + FCS) by ESPN athlete id. Year k = season - class + 1,
so the 2026 class is in year 1, the 2025 class in year 2, and so on. This is one season seen across five
cohorts (a pseudo-panel): each class shows what a recruit of that profile is at year k.

Outcome, two parts (a hurdle model):
  on:  is the player on the board this season (he has PFN snaps, FBS or FCS, at any school)?
  fv:  his FV if he is.
A recruit who is off the board (buried on the depth chart, hurt, out of football) counts at the board floor
(FLOOR) in the expected FV: E[FV] = P(on) * FV(on) + (1 - P(on)) * FLOOR.

Inputs, each kept only if it improves out-of-sample fit (5-fold CV; folds hold out whole schools so the
program terms are tested on programs the fit never saw): ESPN grade (a hinge at 80, the four-star line),
national rank, position rank, position, year, the grade-by-year slope, height and weight against the
position's recruits, the signing program's level (Power 4 / Group of Five / FCS) and strength (Elo), and a
program development effect (each school's shrunk average over- or under-shoot of the recruit baseline,
computed out of fold). Weights are ridge fits; the penalty is picked by the same CV.

Censoring: players drafted after three seasons leave the year-4 and year-5 cohorts, so k >= 4 under-states
the best recruits. The roster projection only needs year 1 and 2; the path reports k 1-3.
"""
import concurrent.futures as cf
import hashlib
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
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'recruit')
OUT = os.path.join(ROOT, 'data', 'cfb_recruit_fit.json')
ALL = os.path.join(ROOT, 'static', 'data', 'cfb-all.json')
TEAMS = os.path.join(ROOT, 'data', 'cfb_teams.json')
OFFLINE = '--offline' in sys.argv
CORE = 'https://sports.core.api.espn.com/v2/sports/football/leagues/college-football'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'
os.makedirs(CACHE, exist_ok=True)
S = requests.Session(); S.headers['User-Agent'] = UA


def get(url, ttl=None):
    """GET JSON, cached on disk by URL forever (past classes don't change) or for ttl seconds."""
    f = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest() + '.json')
    if os.path.exists(f) and (ttl is None or time.time() - os.path.getmtime(f) < ttl or OFFLINE):
        try:
            with open(f) as h: return json.load(h)
        except ValueError: pass   # a write cut off mid-file: pull it again
    if OFFLINE: return None
    for i in range(5):
        try:
            r = S.get(url, timeout=30)
            if r.status_code == 404: v = None; break
            r.raise_for_status(); v = r.json(); break
        except Exception as e:
            if i == 4: print('fail', url, e); return None
            time.sleep(2 ** i)
    with open(f + '.tmp', 'w') as h: json.dump(v, h)
    os.replace(f + '.tmp', f)
    return v


def rid(ref):
    return re.search(r'/teams/(\d+)', ref).group(1)


def short(s):
    """'last name + first initial' key, for nicknames (Daylan / Hollywood aside, Samuel -> Sam, Desmond -> Dezz)"""
    w = [x for x in re.sub(r'\b(jr|sr|ii|iii|iv|v)\b\.?', '', (s or '').lower()).replace('.', '').split() if x]
    return '~' + re.sub(r'[^a-z]', '', ''.join(w[1:])) + (w[0][:1] if w else '') if len(w) > 1 else '~'


def norm(s):
    s = (s or '').lower()
    s = re.sub(r'\b(jr|sr|ii|iii|iv|v)\b\.?', '', s)
    return re.sub(r'[^a-z]', '', s)


# ESPN recruiting positions -> board groups (ATH and the two-way tags go by size later; see group())
POS = {'QB': 'QB', 'QB-DT': 'QB', 'QB-PP': 'QB', 'RB': 'RB', 'APB': 'RB', 'WR': 'WR', 'TE': 'TE', 'TE-Y': 'TE', 'TE-H': 'TE',
       'OT': 'OL', 'OG': 'OL', 'OC': 'OL', 'IOL': 'OL', 'OL': 'OL', 'C': 'OL', 'G': 'OL', 'T': 'OL',
       'DE': 'EDGE', 'WDE': 'EDGE', 'SDE': 'EDGE', 'EDGE': 'EDGE', 'DT': 'DL', 'DL': 'DL',
       'LB': 'LB', 'ILB': 'LB', 'OLB': 'LB', 'CB': 'CB', 'S': 'S', 'SAF': 'S', 'DB': 'S'}


def group(pos, ht, wt):
    g = POS.get(pos)
    if g: return g
    if pos in ('ATH', None, ''):
        if wt and wt >= 240: return 'EDGE'
        return 'ATH'
    return None


def recruit_class(y, ttl=None):
    """ESPN's class y: id (college athlete id once enrolled), name, position, size, grade, ranks, signed school."""
    d = get(f'{CORE}/recruiting/{y}/athletes?limit=1000&page=1', ttl) or {}
    items = list(d.get('items', []))
    for p in range(2, d.get('pageCount', 1) + 1): items += (get(f'{CORE}/recruiting/{y}/athletes?limit=1000&page={p}', ttl) or {}).get('items', [])
    out = []
    for it in items:
        a = it.get('athlete') or {}
        at = {x.get('name'): x.get('value') for x in it.get('attributes', [])}
        sch = [(s['status']['description'], rid(s['team']['$ref'])) for s in it.get('schools', []) if s.get('status', {}).get('id') and s.get('team')]
        school = next((t for st, t in sch if st in ('Signed', 'Enrolled', 'Verbal', 'Committed')), None)
        ht, wt = a.get('height'), a.get('weight')
        # the schools in his recruitment (ESPN lists the programs that offered or pursued him, with official visits)
        offs = [rid(s['team']['$ref']) for s in it.get('schools', []) if s.get('team')]
        out.append({'rid': a.get('id'), 'id': a.get('alternateId'), 'name': a.get('fullName'), 'pos': (a.get('position') or {}).get('abbreviation'),
                    'ht': ht or None, 'wt': wt or None, 'grade': float(it.get('grade') or 0), 'rank': at.get('rank'), 'posRank': at.get('positionRank'),
                    'stRank': at.get('stateRank'), 'hs': ((a.get('highSchool') or {}).get('id')),
                    'state': ((a.get('hometown') or {}).get('stateAbbreviation')) or (((a.get('highSchool') or {}).get('address') or {}).get('stateAbbreviation')),
                    'status': (it.get('status') or {}).get('description'), 'tid': school, 'year': y,
                    'offers': offs, 'visits': sum(1 for s in it.get('schools', []) if s.get('visit'))})
    return out


def get_html(url):
    """GET a page's text, cached on disk by URL (ttl: a day for classes still being recruited)."""
    f = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest() + '.html')
    if os.path.exists(f) and (OFFLINE or time.time() - os.path.getmtime(f) < 86400 or '-football/' in url and int(re.search(r'(\d{4})-football', url).group(1)) < 2027):
        return open(f).read()
    if OFFLINE: return ''
    import subprocess   # curl: 247 turns away Python's HTTP client
    for i in range(4):
        r = subprocess.run(['curl', '-sS', '-f', '-A', 'Mozilla/5.0', url], capture_output=True, text=True)
        if r.returncode == 0: v = r.stdout; break
        if i == 3: print('fail', url, r.stderr.strip()); return ''
        time.sleep(2 ** i)
    open(f, 'w').write(v)
    return v


def composite(y, pages=80, kind='composite'):
    """247Sports' composite for class y (the average of the services, 247's own rank beside it): composite score
    (0-1), composite rank, 247's own rank, stars, position, size, home state and committed school.
    kind='own': 247's own rankings instead (score 0-100), which start a class earlier than the composite."""
    import html as H
    out = []
    path = 'compositerecruitrankings' if kind == 'composite' else 'recruitrankings'
    for pg in range(1, pages + 1):
        h = get_html(f'https://247sports.com/season/{y}-football/{path}/?ViewPath=~/Views/SkyNet/PlayerSportRanking/_SimpleSetForSeason.ascx&Page={pg}')
        items = h.split('rankings-page__list-item"')[1:]
        if not items: break
        for x in items:
            g = lambda p: (re.search(p, x, re.S) or [None, None])[1]
            meta = g(r'class="meta">\s*([^<]*?)\s*</span>') or ''
            st = re.search(r',\s*([A-Z]{2})\)\s*$', meta)
            sc = g(r'class="score">([\d.]+)')
            if not sc: continue
            out.append({'name': H.unescape(g(r'name-link"[^>]*>([^<]*)') or ''), 'state': st.group(1) if st else None, 'pos': (g(r'class="position">\s*([^<]*?)\s*</div>') or '').strip(),
                        'comp': float(sc), 'cRank': int(g(r'class="primary">\s*(\d+)') or 0) or None, 'r247': int(g(r'class="other">\s*(\d+)') or 0) or None,
                        'school': H.unescape(g(r'class="img-link"[^>]*>\s*<img alt="([^"]*)"') or '') or None})
        if len(items) < 50: break
    return out


def parse_rank_page(h):
    """One archived 247 composite page: name, home state, composite score."""
    import html as H
    out = []
    for x in h.split('rankings-page__list-item"')[1:]:
        g = lambda p: (re.search(p, x, re.S) or [None, None])[1]
        meta = g(r'class="meta">\s*([^<]*?)\s*</span>') or ''; st = re.search(r',\s*([A-Z]{2})\)\s*$', meta); sc = g(r'class="score">([\d.]+)')
        if sc: out.append({'name': H.unescape(g(r'name-link"[^>]*>([^<]*)') or ''), 'state': st.group(1) if st else None, 'comp': float(sc)})
    return out


def attach_composite(cl, comp):
    """The 247 composite row for each ESPN recruit: name + home state, else last name + first initial + state."""
    by = defaultdict(list)
    for c in comp: by[(norm(c['name']), c['state'])].append(c); by[(short(c['name']), c['state'])].append(c)
    for r in cl:
        m = by.get((norm(r['name']), r['state'])) or by.get((short(r['name']), r['state'])) or []
        r['comp'] = m[0]['comp'] if len(m) == 1 else None
        r['cRank'] = m[0]['cRank'] if len(m) == 1 else None
        r['r247'] = m[0]['r247'] if len(m) == 1 else None
    return cl


# ---- this season's board (FBS + FCS) and the programs ---------------------------------------------------
P4 = {'SEC', 'Big Ten', 'Big 12', 'ACC'}
FLOOR = 20   # the board's floor: an off-board player counts here in the expected FV
GROUPS = ['QB', 'RB', 'WR', 'TE', 'OL', 'EDGE', 'DL', 'LB', 'CB', 'S', 'ATH']


def board():
    d = json.load(open(ALL))
    rows = [dict(zip(d['cols'], r)) for r in d['rows']]
    by_id, by_nt, by_n, div = {}, {}, defaultdict(list), {}
    for r in rows:
        if r['pos'] in ('K', 'P') or r.get('fv') is None: continue
        m = re.search(r'/id/(\d+)', r.get('espnl') or ''); t = re.search(r'/logos/(\d+)\.png', r.get('logo') or '')
        r['tid'] = t.group(1) if t else None
        if r['tid'] and r.get('div'): div[r['tid']] = r['div']
        if m: by_id[m.group(1)] = r
        by_nt[(norm(r['name']), r['tid'])] = r; by_n[norm(r['name'])].append(r); by_n[short(r['name'])].append(r)
    return rows, by_id, by_nt, by_n, div


def programs(div):
    t = json.load(open(TEAMS))['teams']
    elo = {x['tid']: x['elo'] for x in t}
    m = np.mean(list(elo.values())); s = np.std(list(elo.values()))
    out = {}
    for x in t: out[x['tid']] = {'level': 'P4' if x['conf'] in P4 or x['tid'] == '87' else 'G5', 'eloZ': (x['elo'] - m) / s, 'team': x['team']}
    for tid, dv in div.items():
        if tid not in out and dv == 'FCS': out[tid] = {'level': 'FCS', 'eloZ': 0.0, 'team': None}
    return out


def link(rec, by_id, by_nt, by_n):
    """The recruit's board row: by athlete id, else name + signing school, else a name unique on the board and in the class."""
    r = by_id.get(rec['id']) if rec['id'] else None
    if r: return r, 'id'
    r = by_nt.get((norm(rec['name']), rec['tid']))
    if r: return r, 'school'
    c = by_n.get(norm(rec['name']), [])
    if len(c) == 1 and rec.get('_uniq'): return c[0], 'name'
    c = by_n.get(short(rec['name']), [])
    if len(c) == 1 and rec.get('_uniqS'): return c[0], 'short'
    return None, None


TOP_STATES = ['TX', 'FL', 'GA', 'CA', 'AL', 'LA', 'OH']   # the deepest recruiting states (the rest are the base)
HS_YEARS = range(2020, 2030)


def hs_talent():
    """Rated recruits (ESPN 70+) each high school produced across the 2020-29 classes: a read on the level of
    competition a recruit faced and the program that coached him (his own entry is taken out when scored)."""
    n = Counter()
    for y in HS_YEARS:
        for r in recruit_class(y):
            if r.get('hs') and r['grade'] >= 70: n[r['hs']] += 1
    return n


def enrich(cl, prog, hsn):
    """Candidate drivers: the programs in his recruitment (count, official visits, their strength), the 247
    composite (and its gap to ESPN's grade and to 247's own rank), his high school's output, and home state."""
    attach_composite(cl, composite(cl[0]['year']) if cl else [])
    for r in cl:
        offs = [prog[t] for t in set(r.get('offers') or []) if t in prog]
        fbs = [o for o in offs if o['level'] != 'FCS']
        r['nOff'] = len(offs); r['nVis'] = r.get('visits') or 0
        r['offElo'] = float(np.mean([o['eloZ'] for o in fbs])) if fbs else None
        r['offTop'] = float(max(o['eloZ'] for o in fbs)) if fbs else None
        r['offP4'] = sum(o['level'] == 'P4' for o in offs)
        r['hsN'] = max(0, hsn.get(r.get('hs'), 0) - (1 if r['grade'] >= 70 else 0)) if r.get('hs') else None
    # ESPN tracks offers more fully in some classes than others (a 4-star lists 14 in 2025, 22 in 2027), and a
    # class still being recruited lists fewer: so the offer counts enter as each recruit's residual on his grade
    # within his own class (more offers than his grade's typical count, in that class's SDs)
    for key, src in (('offRes', lambda r: math.log1p(r['nOff'])), ('p4Res', lambda r: math.log1p(r['offP4']))):
        for r, v in zip(cl, class_resid(cl, src)): r[key] = v
    return cl


def class_resid(cl, src):
    """src(r) less its fitted value on grade within the class (rated: a line in grade; unrated: their mean), in SDs."""
    rt = [x for x in cl if x['grade'] >= 60]; un = [x for x in cl if x['grade'] < 60]
    fit = um = None
    if len(rt) > 20:
        g = np.array([x['grade'] for x in rt]); v = np.array([src(x) for x in rt]); A = np.c_[np.ones(len(g)), g]
        b = np.linalg.lstsq(A, v, rcond=None)[0]; fit = (b, float(np.std(v - A @ b)) or 1.0)
    if len(un) > 20: um = (float(np.mean([src(x) for x in un])), float(np.std([src(x) for x in un])) or 1.0)
    out = []
    for r in cl:
        if r['grade'] >= 60: out.append(float((src(r) - fit[0][0] - fit[0][1] * r['grade']) / fit[1]) if fit else 0.0)
        else: out.append(float((src(r) - um[0]) / um[1]) if um else 0.0)
    return out


def dataset(season, classes):
    rows, by_id, by_nt, by_n, div = board()
    prog = programs(div)
    hsn = hs_talent()
    data, how = [], Counter()
    for y in classes:
        cl = enrich(recruit_class(y), prog, hsn)
        n = Counter(norm(r['name']) for r in cl); ns = Counter(short(r['name']) for r in cl)
        for r in cl:
            if not r['tid'] or r['tid'] not in prog: continue
            g = group(r['pos'], r['ht'], r['wt'])
            if g is None: continue
            r['_uniq'] = n[norm(r['name'])] == 1; r['_uniqS'] = ns[short(r['name'])] == 1
            b, h = link(r, by_id, by_nt, by_n)
            how[(y, h)] += 1
            data.append({**r, 'g': g, 'k': season - y + 1, 'on': b is not None, 'fv': b['fv'] if b else None, 'now': b['team'] if b else None, 'nowTid': b['tid'] if b else None, **prog[r['tid']]})
    return data, how, prog


# ---- features ---------------------------------------------------------------------------------------------
# Blocks enter or leave the model together; each is kept only if it lowers the out-of-sample loss.
KMAX = 4   # years 1-4 (year 5 is mostly players who were never drafted: censored)


def size_norms(data):
    """Height and weight mean / SD by recruit group, from every class (the scorer uses the same norms)."""
    out = {}
    for g in GROUPS:
        h = [r['ht'] for r in data if r['g'] == g and r['ht']]; w = [r['wt'] for r in data if r['g'] == g and r['wt']]
        out[g] = [float(np.mean(h)), float(np.std(h) or 1), float(np.mean(w)), float(np.std(w) or 1)]
    bm = {}
    for g in GROUPS:
        b = [703 * r['wt'] / r['ht'] ** 2 for r in data if r['g'] == g and r['ht'] and r['wt']]
        bm[g] = [float(np.mean(b)), float(np.std(b) or 1)]
    out['bmi'] = bm
    return out


def bmiz(r, sz):
    """BMI against the position's recruits (703 x lb / in^2)."""
    if not (r['ht'] and r['wt']): return 0.0
    m, sd = sz.get('bmi', {}).get(r['g'], (None, None))
    return 0.0 if not m else (703 * r['wt'] / r['ht'] ** 2 - m) / sd


def blocks(r, sz):
    """Feature blocks for one recruit at year k: {block: {name: value}}."""
    gr, k = r['grade'], r['k']
    rated = gr >= 60
    g = (gr - 75) / 5 if rated else 0.0
    hm, hs, wm, ws = sz[r['g']]
    rk = r['rank'] or 0; pr = r['posRank'] or 0
    return {
        'grade': {'g': g, 'unrated': 0.0 if rated else 1.0},
        'hinge': {'g80': max(0.0, gr - 80) / 5 if rated else 0.0, 'g85': max(0.0, gr - 85) / 5 if rated else 0.0},
        'rank': {'lrank': (math.log(400) - math.log(rk)) if rk else 0.0},
        'posrank': {'lpos': (math.log(100) - math.log(min(pr, 100))) if pr else 0.0},
        'pos': {f'p_{p}': 1.0 if r['g'] == p else 0.0 for p in GROUPS if p != 'WR'},
        'year': {f'k{j}': 1.0 if k == j else 0.0 for j in range(2, KMAX + 1)},
        'grade_year': {'g_k': g * (k - 1), 'g80_k': (max(0.0, gr - 80) / 5 if rated else 0.0) * (k - 1)},
        'pos_year1': {f'p1_{p}': 1.0 if r['g'] == p and k == 1 else 0.0 for p in GROUPS if p != 'WR'},
        'size': {'htz': ((r['ht'] - hm) / hs) if r['ht'] else 0.0, 'wtz': ((r['wt'] - wm) / ws) if r['wt'] else 0.0},
        'level': {'G5': 1.0 if r['level'] == 'G5' else 0.0, 'FCS': 1.0 if r['level'] == 'FCS' else 0.0},
        'elo': {'eloZ': r['eloZ'], 'elo_k1': r['eloZ'] * (k == 1)},
        'elo_grade': {'elo_g': r['eloZ'] * g},
        'dev': {'dev': r.get('_dev', 0.0)},
        # ---- round-2 candidates (each tested by adding it to the kept model: see drivers()) ----
        'bmi': {'bmiz': bmiz(r, sz)},
        'frame': {'htz2': min(9.0, ((r['ht'] - hm) / hs) ** 2) if r['ht'] else 0.0, 'wtz2': min(9.0, ((r['wt'] - wm) / ws) ** 2) if r['wt'] else 0.0},
        'offers': {'offRes': r.get('offRes') or 0.0},
        'offer_q': {'offElo': r['offElo'] if r.get('offElo') is not None else 0.0, 'offTop': r['offTop'] if r.get('offTop') is not None else 0.0,
                    'p4Res': r.get('p4Res') or 0.0, 'noOff': 0.0 if r.get('offElo') is not None else 1.0},
        'comp': {'compz': (r['comp'] - 0.87) / 0.04 if r.get('comp') else 0.0, 'noComp': 0.0 if r.get('comp') else 1.0},
        'gap': {'gapEspn': ((r['comp'] - 0.87) / 0.04 - g) if r.get('comp') and rated else 0.0,
                'gap247': (math.log(r['cRank']) - math.log(r['r247'])) if r.get('cRank') and r.get('r247') else 0.0},
        'hs': {'lHs': math.log1p(r['hsN']) if r.get('hsN') is not None else 0.0},
        'state': {f's_{x}': 1.0 if r.get('state') == x else 0.0 for x in TOP_STATES},
        'grade_k4': {'g_k4': g * (k == 4), 'g80_k4': (max(0.0, gr - 80) / 5 if rated else 0.0) * (k == 4)},
    }


ALL_BLOCKS = ['grade', 'hinge', 'rank', 'posrank', 'pos', 'year', 'grade_year', 'pos_year1', 'size', 'level', 'elo', 'elo_grade', 'dev']
CORE_BLOCKS = {'grade', 'year'}   # always in: the baseline the others are tested against


def design(data, use, sz):
    names = None; X = []
    for r in data:
        if '_bc' not in r: r['_bc'] = blocks(r, sz)   # every block but the fold-dependent program effect
        b = r['_bc']; b['dev'] = {'dev': r.get('_dev', 0.0)}; row = {}
        for u in use: row.update(b[u])
        if names is None: names = list(row)
        X.append([row[n] for n in names])
    return np.array(X, float), names


# ---- ridge fits -------------------------------------------------------------------------------------------
def ridge(X, y, lam, w=None):
    mu = X.mean(0); sd = X.std(0); sd[sd == 0] = 1
    Z = (X - mu) / sd; n, p = Z.shape
    A = np.c_[np.ones(n), Z]; P = np.eye(p + 1) * lam; P[0, 0] = 0
    b = np.linalg.solve(A.T @ A + P, A.T @ y)
    return b[0] - (b[1:] * mu / sd).sum(), b[1:] / sd


def logit(X, y, lam, iters=30):
    mu = X.mean(0); sd = X.std(0); sd[sd == 0] = 1
    Z = (X - mu) / sd; n, p = Z.shape
    A = np.c_[np.ones(n), Z]; b = np.zeros(p + 1); b[0] = math.log(y.mean() / (1 - y.mean()))
    P = np.eye(p + 1) * lam; P[0, 0] = 0
    for _ in range(iters):
        q = 1 / (1 + np.exp(-(A @ b))); W = q * (1 - q)
        H = A.T @ (A * W[:, None]) + P; gr = A.T @ (q - y) + P @ b
        st = np.linalg.solve(H, gr); b -= st
        if np.abs(st).max() < 1e-7: break
    return b[0] - (b[1:] * mu / sd).sum(), b[1:] / sd


def sig(x): return 1 / (1 + np.exp(-x))


def auc(p, y):
    o = np.argsort(p); r = np.empty(len(p)); r[o] = np.arange(1, len(p) + 1)
    n1 = y.sum(); n0 = len(y) - n1
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def dev_effect(train, k0):
    """Each school's shrunk mean residual (FV on board minus the no-program baseline), from the training rows only.
    A player's own class is left out of his school's effect, so the effect is an out-of-time read on the program."""
    acc = defaultdict(lambda: defaultdict(lambda: [0.0, 0]))
    for r in train:
        if r['on']: x = acc[r['tid']][r['year']]; x[0] += r['_res']; x[1] += 1
    def eff(tid, year):
        s = sum(v[0] for y, v in acc[tid].items() if y != year); n = sum(v[1] for y, v in acc[tid].items() if y != year)
        return s / (n + k0)
    return eff


def folds(data, n=5, by='school', seed=7):
    rng = np.random.default_rng(seed)
    if by == 'school':
        ts = sorted({r['tid'] for r in data}); rng.shuffle(ts); f = {t: i % n for i, t in enumerate(ts)}
        return np.array([f[r['tid']] for r in data])
    return rng.integers(0, n, len(data))


def cv(data, use_on, use_fv, sz, lam_on, lam_fv, k0=20, by='school', k_eval=None):
    """Out-of-fold P(on) and FV(on) for every row (scored at year k_eval instead of his own, when given)."""
    fo = folds(data, by=by); p_on = np.zeros(len(data)); p_fv = np.zeros(len(data))
    use_nd = [u for u in use_fv if u != 'dev']
    for f in range(5):
        tr = [r for r, x in zip(data, fo) if x != f]; te_i = np.where(fo == f)[0]; te = [data[i] for i in te_i]
        if 'dev' in use_on or 'dev' in use_fv:
            # baseline residuals inside the training fold, then the program effect for train and test rows
            Xb, _ = design([r for r in tr if r['on']], use_nd, sz); yb = np.array([r['fv'] for r in tr if r['on']])
            a, b = ridge(Xb, yb, lam_fv)
            for r in tr: r['_res'] = (r['fv'] - (a + design([r], use_nd, sz)[0][0] @ b)) if r['on'] else 0.0
            eff = dev_effect(tr, k0)
            for r in tr + te: r['_dev'] = eff(r['tid'], r['year'])
        if k_eval: te = [{**{x: v for x, v in r.items() if x != '_bc'}, 'k': k_eval} for r in te]
        X, _ = design(tr, use_on, sz); y = np.array([r['on'] for r in tr], float)
        a, b = logit(X, y, lam_on); Xt, _ = design(te, use_on, sz); p_on[te_i] = sig(a + Xt @ b)
        on = [r for r in tr if r['on']]; X1, _ = design(on, use_fv, sz); y1 = np.array([r['fv'] for r in on])
        a, b = ridge(X1, y1, lam_fv); Xt, _ = design(te, use_fv, sz); p_fv[te_i] = a + Xt @ b
    return p_on, p_fv


def score(data, p_on, p_fv):
    y = np.array([r['on'] for r in data], float); fv = np.array([r['fv'] if r['on'] else FLOOR for r in data], float)
    ll = -float(np.mean(y * np.log(np.clip(p_on, 1e-6, 1)) + (1 - y) * np.log(np.clip(1 - p_on, 1e-6, 1))))
    m = y == 1; e1 = fv[m] - p_fv[m]
    ex = p_on * np.maximum(p_fv, FLOOR) + (1 - p_on) * FLOOR; e = fv - ex
    return {'ll': ll, 'auc': auc(p_on, y), 'rmse_on': float(np.sqrt(np.mean(e1 ** 2))), 'r2_on': float(1 - e1.var() / fv[m].var()),
            'rmse': float(np.sqrt(np.mean(e ** 2))), 'r2': float(1 - np.mean(e ** 2) / fv.var()), 'r': float(np.corrcoef(ex, fv)[0, 1])}


def select(data, sz, lam_on, lam_fv):
    """Backward elimination by block, separately for P(on) (log loss) and FV(on) (squared error), on
    school-held-out CV. A block stays only if dropping it raises the out-of-sample loss with t >= 2 (paired
    over recruits), the test the badge and Stat+ backtests use. Returns the kept blocks and each block's gain."""
    use = {'on': [b for b in ALL_BLOCKS if b != 'dev'], 'fv': list(ALL_BLOCKS)}
    y = np.array([r['on'] for r in data], float); m = y == 1; fv = np.array([r['fv'] or 0 for r in data], float)
    def losses(part, u):
        uo, uf = (u, use['fv']) if part == 'on' else (use['on'], u)
        po, pf = cv(data, uo, uf, sz, lam_on, lam_fv)
        if part == 'on': return -(y * np.log(np.clip(po, 1e-6, 1)) + (1 - y) * np.log(np.clip(1 - po, 1e-6, 1)))
        return (fv[m] - pf[m]) ** 2
    gains = {}
    for part in ('on', 'fv'):
        while True:
            base = losses(part, use[part]); trial = {}
            for b in use[part]:
                if b in CORE_BLOCKS: continue
                d = losses(part, [x for x in use[part] if x != b]) - base
                trial[b] = (float(d.mean()), float(d.mean() / (d.std() / math.sqrt(len(d)) or 1)))
            gains[part] = {b: {'gain': round(g, 5), 't': round(t, 2)} for b, (g, t) in trial.items()}
            worst = min(trial, key=lambda b: trial[b][1]) if trial else None
            print(part, round(float(base.mean()), 5), sorted(((b, round(t, 2)) for b, (g, t) in trial.items()), key=lambda x: x[1]))
            if worst is None or trial[worst][1] >= 2: break
            use[part] = [x for x in use[part] if x != worst]
    return use, gains, {'on': 'log loss', 'fv': 'squared error (FV on board)'}


# ---- round 2: new drivers, each added to the kept model and tested on held-out programs ----------------
CANDIDATES = ['bmi', 'frame', 'offers', 'offer_q', 'comp', 'gap', 'hs', 'state', 'grade_k4']


def drivers(data, use, sz, lam_on, lam_fv, cands=CANDIDATES):
    """Forward test: each candidate block is added to the kept model, and it stays only if it lowers the
    out-of-sample loss (school-held-out CV, paired over recruits) with t >= 2; the best passing block is
    added and the rest are tested again on top of it. Returns the new blocks and each candidate's first-round test."""
    y = np.array([r['on'] for r in data], float); m = y == 1; fv = np.array([r['fv'] or 0 for r in data], float)
    use = {k: list(v) for k, v in use.items()}; first = {}

    def losses(part, u):
        uo, uf = (u, use['fv']) if part == 'on' else (use['on'], u)
        po, pf = cv(data, uo, uf, sz, lam_on, lam_fv)
        if part == 'on': return -(y * np.log(np.clip(po, 1e-6, 1)) + (1 - y) * np.log(np.clip(1 - po, 1e-6, 1)))
        return (fv[m] - pf[m]) ** 2
    for part in ('on', 'fv'):
        left = [c for c in cands if c not in use[part]]; first[part] = {}
        while left:
            base = losses(part, use[part]); trial = {}
            for c in left:
                d = base - losses(part, use[part] + [c])
                trial[c] = (float(d.mean()), float(d.mean() / (d.std() / math.sqrt(len(d)) or 1)))
                first[part].setdefault(c, {'gain': round(trial[c][0], 5), 't': round(trial[c][1], 2)})
            print(part, 'drivers', sorted(((c, round(t, 2)) for c, (g, t) in trial.items()), key=lambda x: -x[1]), flush=True)
            best = max(trial, key=lambda c: trial[c][1])
            if trial[best][1] < 2: break
            use[part].append(best); left.remove(best)
            first[part][best]['kept'] = True; first[part][best]['tFinal'] = round(trial[best][1], 2)
    return use, first


# ---- redshirts: who sat out last season, and whether he is on the board this season ----------------------
# A recruit on last season's roster who played four games or fewer (the redshirt line) is the state a
# current redshirt is in. ESPN's season stat lines give games played; offensive linemen have no stat line,
# so they are left out of the fit and take the pooled effect.
def pmap(fn, xs, n=24):
    with cf.ThreadPoolExecutor(n) as ex: return list(ex.map(fn, xs))


def rosters(season):
    out = {}
    for g in (80, 81):
        d = get(f'{CORE}/seasons/{season}/types/2/groups/{g}/teams?limit=400') or {}
        tids = [re.search(r'/teams/(\d+)', x['$ref']).group(1) for x in d.get('items', [])]
        for tid, d2 in zip(tids, pmap(lambda t: get(f'{CORE}/seasons/{season}/teams/{t}/athletes?limit=400'), tids)):
            for x in (d2 or {}).get('items', []): out[re.search(r'/athletes/(\d+)', x['$ref']).group(1)] = tid
    return out


def games_played(season, aid):
    d = get(f'{CORE}/seasons/{season}/types/2/athletes/{aid}/statistics')
    if not d: return 0
    for c in (d.get('splits') or {}).get('categories', []):
        for s in c.get('stats', []):
            if s.get('name') == 'gamesPlayed': return int(s.get('value') or 0)
    return 0


def transitions(season, data):
    """Last season's state for the id-linked recruits of the three classes before this season's freshmen."""
    ros = rosters(season - 1)
    rows = [r for r in data if r['id'] and r['id'] in ros and r['g'] != 'OL' and season - 3 <= r['year'] <= season - 1]
    gp = pmap(lambda r: games_played(season - 1, r['id']), rows)
    for r, n in zip(rows, gp): r['gpLast'] = n; r['tidLast'] = ros[r['id']]
    return rows


# ---- fit, test, write -------------------------------------------------------------------------------------
LAM = 30   # ridge penalty (standardized units); CV is flat from 1 to 100, worse past 300


def final(data, use, sz, k0):
    """Live coefficients on every row, with the program effect from every class."""
    use_nd = [u for u in use['fv'] if u != 'dev']
    on = [r for r in data if r['on']]
    Xb, _ = design(on, use_nd, sz); a, b = ridge(Xb, np.array([r['fv'] for r in on]), LAM)
    for r in data: r['_res'] = (r['fv'] - (a + design([r], use_nd, sz)[0][0] @ b)) if r['on'] else 0.0
    acc = defaultdict(lambda: [0.0, 0])
    for r in on: x = acc[r['tid']]; x[0] += r['_res']; x[1] += 1
    dev = {t: round(s / (n + k0), 3) for t, (s, n) in acc.items()}
    for r in data: r['_dev'] = dev.get(r['tid'], 0.0)
    X, names_on = design(data, use['on'], sz); a_on, b_on = logit(X, np.array([r['on'] for r in data], float), LAM)
    X1, names_fv = design(on, use['fv'], sz); a_fv, b_fv = ridge(X1, np.array([r['fv'] for r in on]), LAM)
    return {'on': {'blocks': use['on'], 'names': names_on, 'b0': round(float(a_on), 5), 'coef': [round(float(x), 5) for x in b_on]},
            'fv': {'blocks': use['fv'], 'names': names_fv, 'b0': round(float(a_fv), 4), 'coef': [round(float(x), 4) for x in b_fv]}, 'dev': dev}


def predict(m, r, sz):
    b = blocks(r, sz)
    def lin(part):
        row = {}
        for u in m[part]['blocks']: row.update(b[u])
        return m[part]['b0'] + sum(row[n] * c for n, c in zip(m[part]['names'], m[part]['coef']))
    p = float(sig(lin('on'))); f = max(FLOOR, lin('fv'))
    return p, f, p * f + (1 - p) * FLOOR


def tiers(data, p_on, p_fv):
    """Calibration by recruit tier: predicted vs actual board rate and expected FV, out of fold."""
    def tier(r):
        g = r['grade']
        return '5-star (90+)' if g >= 90 else '4-star (80-89)' if g >= 80 else '3-star (70-79)' if g >= 70 else 'lower / unrated'
    out = []
    for t in ['5-star (90+)', '4-star (80-89)', '3-star (70-79)', 'lower / unrated']:
        i = [j for j, r in enumerate(data) if tier(r) == t]
        if not i: continue
        y = np.array([data[j]['on'] for j in i], float); fv = np.array([data[j]['fv'] or FLOOR for j in i], float)
        ex = p_on[i] * np.maximum(p_fv[i], FLOOR) + (1 - p_on[i]) * FLOOR
        on = [j for j in i if data[j]['on']]
        out.append({'tier': t, 'n': len(i), 'onAct': round(float(y.mean()), 3), 'onPred': round(float(p_on[i].mean()), 3),
                    'fvAct': round(float(fv.mean()), 1), 'fvPred': round(float(ex.mean()), 1),
                    'fvOnAct': round(float(np.mean([data[j]['fv'] for j in on])), 1) if on else None,
                    'fvOnPred': round(float(np.mean(np.maximum(p_fv[on], FLOOR))), 1) if on else None})
    return out


def baselines(data):
    """Out-of-fold losses for simpler models: position x year means, and stars + year."""
    out = {}
    for name, use in (('pos_year', ['pos', 'year']), ('grade_year', ['grade', 'year'])):
        out[name] = {k: round(v, 4) for k, v in score(data, *cv(data, use, use, SZ, LAM, LAM)).items()}
    return out


# ---- ARK stars: the projection cut into 1-5 stars -------------------------------------------------------
# Each recruit's score is his year-3 xFV (the same horizon for every class). Two ways to cut it, each backtested
# out of fold: 'share' gives each star the industry's share of the pool (ESPN 90+ / 80s / 70s / 60s / unrated);
# 'band' puts each cutoff where the stars best match what recruits became: 5 = top 3% of the board, 4 = top 10%,
# 3 = above the board median, 2 = on the board, 1 = not on the board.
def ind_stars(g): return 5 if g >= 90 else 4 if g >= 80 else 3 if g >= 70 else 2 if g >= 60 else 1


def cut(s, c): return 1 + np.searchsorted(np.asarray(c), s, side='right')   # c: 4 ascending cutoffs


def qwk(a, b, n=5):
    O = np.zeros((n, n))
    for x, y in zip(a, b): O[x - 1, y - 1] += 1
    W = np.array([[(i - j) ** 2 for j in range(n)] for i in range(n)]) / (n - 1) ** 2
    E = np.outer(O.sum(1), O.sum(0)) / O.sum()
    return float(1 - (W * O).sum() / (W * E).sum())


def fit_band(s, band):
    """Cutoffs on the score that best match the realized bands (quadratic weighted kappa), coordinate search."""
    qs = np.quantile(s, np.linspace(0.01, 0.995, 200))
    c = list(np.quantile(s, [1 - np.mean(band >= t) for t in (2, 3, 4, 5)]))   # start: the bands' own shares
    best = qwk(cut(s, c), band)
    for _ in range(4):
        for i in range(4):
            lo = c[i - 1] if i else -np.inf; hi = c[i + 1] if i < 3 else np.inf
            for q in qs:
                if not lo < q < hi: continue
                t = c[:i] + [q] + c[i + 1:]; v = qwk(cut(s, t), band)
                if v > best: best, c = v, t
    return c


def ark_stars(data, use, sz, k0, board_fv):
    p_on, p_fv = cv(data, use['on'], use['fv'], sz, LAM, LAM, k0=k0, k_eval=3)
    s = p_on * np.maximum(p_fv, FLOOR) + (1 - p_on) * FLOOR
    real = np.array([r['fv'] if r['on'] else FLOOR for r in data], float)
    q50, q90, q97 = np.quantile(board_fv, [0.5, 0.9, 0.97])
    band = np.array([1 if not r['on'] else 5 if r['fv'] >= q97 else 4 if r['fv'] >= q90 else 3 if r['fv'] >= q50 else 2 for r in data])
    ind = np.array([ind_stars(r['grade']) for r in data]); share = [float(np.mean(ind == t)) for t in (1, 2, 3, 4, 5)]
    k = np.array([r['k'] for r in data]); fo = folds(data)
    def cuts(i, scheme):
        if scheme == 'share': return list(np.quantile(s[i], np.cumsum(share)[:4]))
        m = i[k[i] >= 3]   # bands from the classes that have had time to get there
        return fit_band(s[m], band[m])
    def rank(a):
        o = np.argsort(a, kind='stable'); r = np.empty(len(a)); r[o] = np.arange(len(a)); _, inv, c = np.unique(a, return_inverse=True, return_counts=True)
        csum = np.cumsum(c) - c; return (csum + (c - 1) / 2)[inv]
    out = {'q': [round(float(x), 1) for x in (q50, q90, q97)], 'share': [round(x, 4) for x in share], 'schemes': {}}
    for scheme in ('industry', 'share', 'band'):
        st = np.zeros(len(data), int)
        for f in range(5):
            te = np.where(fo == f)[0]; tr = np.where(fo != f)[0]
            st[te] = ind[te] if scheme == 'industry' else cut(s[te], cuts(tr, scheme))
        # how much a recruit's star tells you about what he became: tier means from the other folds, within class
        sse = sst = 0.0; rho = []; ns = []
        for kk in range(1, KMAX + 1):
            i = np.where(k == kk)[0]; pred = np.zeros(len(i))
            for f in range(5):
                a = fo[i] == f; mu = {t: real[i][~a][st[i][~a] == t].mean() for t in set(st[i][~a])}
                pred[a] = [mu.get(t, real[i][~a].mean()) for t in st[i][a]]
            sse += float(((real[i] - pred) ** 2).sum()); sst += float(((real[i] - real[i].mean()) ** 2).sum())
            rho.append(float(np.corrcoef(rank(st[i]), rank(real[i]))[0, 1])); ns.append(len(i))
        m = k >= 3
        rows = []
        for t in (5, 4, 3, 2, 1):
            i = st == t; j = i & m
            rows.append({'stars': t, 'n': int(i.sum()), 'share': round(float(i.mean()), 4), 'on': round(float(np.mean([data[x]['on'] for x in np.where(j)[0]])), 3) if j.any() else None,
                         'fv': round(float(real[j].mean()), 1) if j.any() else None, 'top10': round(float(np.mean(band[j] >= 4)), 3) if j.any() else None})
        out['schemes'][scheme] = {'r2': round(1 - sse / sst, 4), 'rho': round(float(np.average(rho, weights=ns)), 4), 'qwk': round(qwk(st[m], band[m]), 4), 'tiers': rows}
    pick = max(('share', 'band'), key=lambda x: out['schemes'][x]['r2'])
    out['pick'] = pick; out['cuts'] = [round(float(x), 2) for x in cuts(np.arange(len(data)), pick)]
    out['cutsAll'] = {x: [round(float(v), 2) for v in cuts(np.arange(len(data)), x)] for x in ('share', 'band')}
    return out


RS_EXTRA = {   # tested on top of the base score: does anything the recruit model doesn't see tell sitters apart?
    'games': lambda r, b: {'gp14': 1.0 if 1 <= r.get('gpLast', 0) <= 4 else 0.0},   # got on the field a little vs not at all
    'grade': lambda r, b: b['grade'], 'offer_q': lambda r, b: b['offer_q'], 'gap': lambda r, b: b['gap'], 'hs': lambda r, b: b['hs'],
    'bmi': lambda r, b: b['bmi'], 'size': lambda r, b: b['size'],
    'level': lambda r, b: {'p4': 1.0 if r.get('level') == 'P4' else 0.0},
    'moved': lambda r, b: {'moved': 1.0 if r.get('tid') and r.get('tidLast') and r['tidLast'] != r['tid'] else 0.0},   # already left his signing school
}


def rs_X(sat, z, sz, extra):
    return np.c_[z, np.array([[v for u in extra for v in RS_EXTRA[u](r, blocks(r, sz)).values()] for r in sat])] if extra else z[:, None]


def rs_score(sat, z, y, sz, extra):
    """Out-of-fold log loss per row and P for a + b * z (+ extra blocks), 5 folds holding out programs."""
    f = folds(sat); ll = np.zeros(len(sat)); P = np.zeros(len(sat)); X = rs_X(sat, z, sz, extra)
    for i in range(5):
        tr, te = f != i, f == i
        a, b = logit(X[tr], y[tr], 1.0); p = np.clip(sig(a + X[te] @ b), 1e-6, 1 - 1e-6)
        ll[te] = -(y[te] * np.log(p) + (1 - y[te]) * np.log(1 - p)); P[te] = p
    return ll, P


def rs_select(sat, z, y, sz):
    """Forward add, one block at a time: kept when the paired t of the out-of-sample loss drop is 2 or more."""
    use, gains, cur = [], {}, rs_score(sat, z, y, sz, [])[0]
    while True:
        best = None
        for u in RS_EXTRA:
            if u in use: continue
            d = cur - rs_score(sat, z, y, sz, use + [u])[0]; t = float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))
            gains.setdefault(u, {'gain': round(float(d.mean()), 5), 't': round(t, 2)})
            if t >= 2 and (best is None or t > best[1]): best = (u, t, d)
        if not best: return use, gains
        use.append(best[0]); gains[best[0]].update({'kept': True, 'tFinal': round(best[1], 2)}); cur = cur - best[2]


def rs_logit(sat, z, y, sz, extra):
    """a + b * z + coef . extras on raw features (logit() standardizes inside, so undo it)."""
    X = rs_X(sat, z, sz, extra); a, b = logit(X, y, 1.0)
    mu, sd = X.mean(0), X.std(0); sd[sd == 0] = 1; raw = b / sd
    names = [n for u in extra for n in RS_EXTRA[u](sat[0], blocks(sat[0], sz))]
    return {'a': round(float(a - (mu / sd) @ b), 4), 'b': round(float(raw[0]), 4), 'extra': extra, 'names': names, 'coef': [round(float(x), 4) for x in raw[1:]]}


def redshirt_fit(T, m, sz, season, T2=None):
    """P(on the board | on a roster and sat): a + b * logit(base) (+ whatever passes the test), where base is the
    recruit model's score for the year he is moving into. Tested holding out programs, and by class. One season
    on (T: sat last season, on the board now) and two seasons on (T2: sat two seasons ago, on the board now).
    FV if he reaches the board: the base FV plus a shrunk shift, the sitters' mean miss. Where the rest went:
    still on a roster this season (sitting again, same school or new) or off every roster ESPN carries."""
    sat = [r for r in T if r['gpLast'] <= 4]
    lz = lambda rows: np.array([math.log(p / (1 - p)) for p, _, _ in (predict(m, r, sz) for r in rows)])
    z = lz(sat); y = np.array([r['on'] for r in sat], float)
    extra, gains = rs_select(sat, z, y, sz)
    llN, pN = rs_score(sat, z, y, sz, extra); llB, pB = rs_score(sat, z, y, sz, [])
    pr = np.clip(sig(z), 1e-6, 1 - 1e-6); llRaw = -(y * np.log(pr) + (1 - y) * np.log(1 - pr))
    test = []
    for yy in sorted({r['year'] for r in sat}):
        tr = np.array([r['year'] != yy for r in sat]); te = ~tr
        f = rs_logit([r for r, t in zip(sat, tr) if t], z[tr], y[tr], sz, extra); X = rs_X([r for r, t in zip(sat, te) if t], z[te], sz, extra)
        p = np.clip(sig(f['a'] + X[:, 0] * f['b'] + (X[:, 1:] @ np.array(f['coef']) if f['coef'] else 0)), 1e-6, 1 - 1e-6)
        ll = lambda q: -float(np.mean(y[te] * np.log(q) + (1 - y[te]) * np.log(1 - q)))
        test.append({'class': yy, 'n': int(te.sum()), 'rate': round(float(y[te].mean()), 3), 'pred': round(float(p.mean()), 3), 'auc': round(auc(p, y[te]), 3),
                     'll': round(ll(p), 4), 'llBase': round(ll(pr[te]), 4), 'llRate': round(ll(np.full(te.sum(), y[tr].mean())), 4)})
    fit1 = rs_logit(sat, z, y, sz, extra)
    on = [r for r in sat if r['on']]
    shift = float(np.sum([r['fv'] - predict(m, r, sz)[1] for r in on]) / (len(on) + 50))
    played = [r for r in T if r['gpLast'] > 4]
    now = rosters(season)
    fate = {'onSame': np.mean([r['on'] and r['nowTid'] == r['tidLast'] for r in sat]), 'onNew': np.mean([r['on'] and r['nowTid'] != r['tidLast'] for r in sat]),
            'sitSame': np.mean([(not r['on']) and now.get(r['id']) == r['tidLast'] for r in sat]),
            'sitNew': np.mean([(not r['on']) and r['id'] in now and now[r['id']] != r['tidLast'] for r in sat]),
            'gone': np.mean([(not r['on']) and r['id'] not in now for r in sat])}
    out = {'away': round(float(np.mean([r['nowTid'] != r['tidLast'] for r in on])), 3) if on else 0.0, **fit1, 'fvShift': round(shift, 2), 'n': len(sat),
           'rate': round(float(y.mean()), 3), 'playedN': len(played), 'playedRate': round(float(np.mean([r['on'] for r in played])), 3) if played else None,
           'test': test, 'gains': gains, 'll': round(float(llN.mean()), 4), 'llBase': round(float(llB.mean()), 4), 'llRaw': round(float(llRaw.mean()), 4),
           'auc': round(auc(pN, y), 3), 'aucBase': round(auc(pB, y), 3), 'fate': {k: round(float(v), 3) for k, v in fate.items()},
           'fvOnBy': {'same': round(float(np.mean([r['fv'] for r in on if r['nowTid'] == r['tidLast']])), 1), 'new': round(float(np.mean([r['fv'] for r in on if r['nowTid'] != r['tidLast']])), 1)} if on else None}
    if T2:
        s2 = [dict(r, k=min(r['k'], KMAX)) for r in T2]   # scored at the year he is in now, two on from when he sat
        z2 = lz(s2); y2 = np.array([r['on'] for r in s2], float)
        f2 = rs_logit(s2, z2, y2, sz, []); on2 = [r for r in s2 if r['on']]
        out['two'] = {'n': len(s2), 'rate': round(float(y2.mean()), 3), 'pred': round(float(sig(z2).mean()), 3), 'a': f2['a'], 'b': f2['b'],
                      'll': round(float(rs_score(s2, z2, y2, sz, [])[0].mean()), 4), 'fvShift': round(float(np.sum([r['fv'] - predict(m, r, sz)[1] for r in on2]) / (len(on2) + 50)), 2),
                      'away': round(float(np.mean([r['nowTid'] != r['tidLast'] for r in on2])), 3) if on2 else None}
    return out


def transitions2(season, data):
    """Two seasons back: recruits who sat in season - 2 (classes season - 3 and - 2, years 1-2 then); the outcome
    is this season's board, two seasons on, at any school."""
    ros = rosters(season - 2)
    rows = [dict(r) for r in data if r['id'] and r['id'] in ros and r['g'] != 'OL' and season - 3 <= r['year'] <= season - 2]
    gp = pmap(lambda r: games_played(season - 2, r['id']), rows)
    out = []
    for r, n in zip(rows, gp):
        if n <= 4: r['gpLast'] = n; r['tidLast'] = ros[r['id']]; out.append(r)
    return out


def per_year(data, p_on, p_fv):
    out = []
    for k in range(1, KMAX + 1):
        i = [j for j, r in enumerate(data) if r['k'] == k]
        s = score([data[j] for j in i], p_on[i], p_fv[i])
        out.append({'k': k, 'class': data[i[0]]['year'], 'n': len(i), 'on': round(float(np.mean([data[j]['on'] for j in i])), 3), **{x: round(v, 3) for x, v in s.items()}})
    return out


def path(m, sz, data):
    """The development curve: expected FV and board rate at years 1-3 for the recruits of each tier, each scored
    at every year with his own profile (drivers included) and averaged."""
    out = []
    for lab, lo, hi in (('5-star (90+)', 90, 101), ('high 4-star (85-89)', 85, 90), ('4-star (80-84)', 80, 85), ('3-star (75-79)', 75, 80), ('3-star (70-74)', 70, 75), ('unrated', 0, 60)):
        rows = [r for r in data if lo <= r['grade'] < hi]
        row = {'tier': lab, 'n': len(rows), 'k': []}
        for k in (1, 2, 3):
            ps = [predict(m, dict(r, k=k), sz) for r in rows]
            row['k'].append({'on': round(float(np.mean([p[0] for p in ps])), 3), 'fvOn': round(float(np.mean([p[1] for p in ps])), 1), 'fv': round(float(np.mean([p[2] for p in ps])), 1)})
        out.append(row)
    return out


# ---- classes still being recruited: 247 snapshot, grade maps, agreement, offer and HS reads ----------
def future_support(season, data, p_on, p_fv):
    """What the scorer needs for the classes it scores: residual SD of FV-if-on by year (for the ranges), maps
    from 247's composite and own scores onto ESPN's grade (fit on the final classes, so a recruit with only a 247
    score gets the ESPN grade his score predicts, already regressed toward the mean), the services' agreement by
    class (on ESPN's top 250, the same range each class), and the high-school counts."""
    sd = []
    for k in range(1, KMAX + 1):
        i = [j for j, r in enumerate(data) if r['k'] == k and r['on']]
        sd.append(round(float(np.std([data[j]['fv'] - p_fv[j] for j in i])), 2))
    def lin(xs, ys):
        A = np.c_[np.ones(len(xs)), xs]; b = np.linalg.lstsq(A, ys, rcond=None)[0]
        return [round(float(b[0]), 3), round(float(b[1]), 3), round(float(np.std(ys - A @ b)), 2), len(xs)]
    snap = {'composite': {}, 'own': {}}; agree = []; pairs = {'composite': [], 'own': []}; ranks = []
    for y in range(season - KMAX + 1, season + 4):
        cl = recruit_class(y)
        for kind in ('composite', 'own'):
            if kind == 'own' and y < season - 1: continue
            c = composite(y, pages=80 if kind == 'composite' else 12, kind=kind)
            if not c: continue
            snap[kind][y] = [[x['name'], x['state'], x['comp'], x['cRank'], x['r247']] for x in c]
            by = defaultdict(list)
            for x in c: by[(norm(x['name']), x['state'])].append(x); by[(short(x['name']), x['state'])].append(x)
            L = []
            for r in cl:
                m = by.get((norm(r['name']), r['state'])) or by.get((short(r['name']), r['state'])) or []
                if len(m) == 1 and r['grade'] >= 60:
                    L.append((r['grade'], m[0]['comp'], r['rank']))
                    if kind == 'own' and y <= season and m[0]['cRank'] and m[0]['cRank'] <= 400: ranks.append((math.log(m[0]['cRank']), r['grade']))
            top = [(g, c2) for g, c2, rk in L if rk and rk <= 250]
            if len(top) >= 30:
                a = np.array(top); agree.append({'class': y, 'kind': kind, 'n': len(top), 'r': round(float(np.corrcoef(a[:, 0], a[:, 1])[0, 1]), 3)})
            if y <= season: pairs[kind] += [(c2, g) for g, c2, rk in L]
    maps = {k: lin(np.array([p[0] for p in v]), np.array([p[1] for p in v])) for k, v in pairs.items() if len(v) > 50}
    # 247 scores a class low early (its 2029 top recruit is a 92; a signed class tops out at 100), so its own list
    # maps by national rank instead: ESPN grade on log 247 rank, in the signed classes
    if len(ranks) > 50: maps['ownRank'] = lin(np.array([p[0] for p in ranks]), np.array([p[1] for p in ranks]))
    hsn = hs_talent()
    return {'sdOn': sd, 'gradeMap': maps, 'agree': agree, 'hsN': {h: n for h, n in hsn.items() if n}}, snap


def main():
    global SZ
    season = json.load(open(ALL))['asof'][:4]; season = int(season)
    data, how, prog = dataset(season, range(season - KMAX + 1, season + 1))
    data = [r for r in data if r['k'] <= KMAX]
    SZ = size_norms(data)
    print('rows', len(data), 'on board', sum(r['on'] for r in data))
    SEL = os.path.join(CACHE, 'select.json')   # --reuse-select: skip the (slow) elimination, reuse its last result
    if '--reuse-select' in sys.argv and os.path.exists(SEL): use, gains, key = json.load(open(SEL))
    elif '--base-from-fit' in sys.argv and os.path.exists(OUT):   # the last fit's kept blocks and their tests
        o = json.load(open(OUT)); use = {p: o['model'][p]['blocks'] for p in ('on', 'fv')}; gains, key = o['gains'], o['gainKeys']
        json.dump([use, gains, key], open(SEL, 'w'))
    else:
        use, gains, key = select(data, SZ, LAM, LAM)
        json.dump([use, gains, key], open(SEL, 'w'))
    # round 2: the new drivers, tested on top of the kept model
    p0 = cv(data, use['on'], use['fv'], SZ, LAM, LAM); before = {k: round(v, 4) for k, v in score(data, *p0).items()}
    DRV = os.path.join(CACHE, 'drivers.json')
    if '--reuse-select' in sys.argv and os.path.exists(DRV): use, drv = json.load(open(DRV))
    else:
        use, drv = drivers(data, use, SZ, LAM, LAM)
        json.dump([use, drv], open(DRV, 'w'))
    K0 = 20
    if 'dev' in use['fv']:
        k0s = {k0: score(data, *cv(data, use['on'], use['fv'], SZ, LAM, LAM, k0=k0))['rmse_on'] for k0 in (5, 10, 20, 40, 80)}
        K0 = min(k0s, key=k0s.get)
    p_on, p_fv = cv(data, use['on'], use['fv'], SZ, LAM, LAM, k0=K0)
    test = {k: round(v, 4) for k, v in score(data, p_on, p_fv).items()}
    test_rand = {k: round(v, 4) for k, v in score(data, *cv(data, use['on'], use['fv'], SZ, LAM, LAM, k0=K0, by='player')).items()}
    base = baselines(data)
    m = final(data, use, SZ, K0)
    T = transitions(season, data)
    rs = redshirt_fit(T, m, SZ, season, transitions2(season, data))
    stars = ark_stars(data, use, SZ, K0, [r['fv'] for r in board()[0] if r.get('fv') is not None and r['pos'] not in ('K', 'P')])
    print(json.dumps(stars, indent=1))
    links = Counter(h for (y, h), n in how.items() for _ in range(n))
    out = {'asof': json.load(open(ALL))['asof'], 'season': season, 'classes': [season - KMAX + 1, season], 'n': len(data), 'onRate': round(float(np.mean([r['on'] for r in data])), 3),
           'floor': FLOOR, 'lam': LAM, 'k0': K0, 'sizeNorms': {g: ({p: [round(x, 3) for x in w] for p, w in v.items()} if g == 'bmi' else [round(x, 2) for x in v]) for g, v in SZ.items()},
           'link': {'id': sum(n for (y, h), n in how.items() if h == 'id'), 'name': sum(n for (y, h), n in how.items() if h in ('school', 'name', 'short')),
                    'none': sum(n for (y, h), n in how.items() if h is None), 'nameRecall': 0.956, 'namePrecision': 0.998},
           'model': m, 'gains': gains, 'gainKeys': key, 'drivers': drv, 'testBefore': before, 'test': test, 'testPlayer': test_rand, 'baseline': base, 'tiers': tiers(data, p_on, p_fv),
           'byYear': per_year(data, p_on, p_fv),
           'away1': round(float(np.mean([r['nowTid'] != r['tid'] for r in data if r['on'] and r['k'] == 1])), 3), 'path': path(m, SZ, data), 'redshirt': rs, 'stars': stars}
    fs_, snap = future_support(season, data, p_on, p_fv)
    out.update(fs_)
    json.dump(snap, open(os.path.join(ROOT, 'scripts', 'cfb_recruit_247.json'), 'w'), separators=(',', ':'))
    json.dump(out, open(OUT, 'w'), indent=1)
    print(json.dumps({k: out[k] for k in ('test', 'testPlayer', 'baseline', 'tiers', 'byYear', 'redshirt', 'gains')}, indent=1))


if __name__ == '__main__':
    main()
