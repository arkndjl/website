#!/usr/bin/env python3
"""International prospects on the College Basketball ARKBOARD: graded on the same 20-80 FV scale (peak XPM) as the
D-I players, from where the draft boards rank them and what they produce in pro leagues, adjusted for league
strength and minutes played.

    sh scripts/cbb_intl_pull.sh       # raw pulls: Basketball-Reference international league totals, Barttorvik seasons
    python3 scripts/cbb_intl.py       # full run: league factors, backtest, fit (scripts/data/cbb_intl_fit.json), grade
    python3 scripts/cbb_intl.py --daily   # in season: re-pull this season's league pages, re-grade with the committed fit

Population: the non-college prospects on the big boards. Training: every international on ESPN's final board or
NBADraft.net's final board for the 2009-2020 drafts (no D-I season that year or the one before, not G League), each
scored on the FV his NBA career earned (peak XPM: best three seasons of .5 BPM + .5 DPM, shrunk to -2 by 500 minutes;
the cuts are the college board's, data/cbb_fit.json xpmCuts; 20 = never played in the NBA). Live: the internationals
on the current 2027 boards (scripts/data/cbb_boards/).

League strength: every stat per 100 possessions (league pace from team totals), then each league's offset against
the EuroLeague from players who played in two leagues, in the same season (EuroLeague or EuroCup plus a domestic
league) or in back-to-back seasons (with a common year-on-year growth term): weighted least squares, weights the
harmonic mean of the two minute totals. A line is translated to EuroLeague level by removing its league's offset.

Minutes: a season's line is shrunk toward replacement by its minutes (k picked by the same out-of-sample test), the
draft season counts in full and the season before at half weight, and playing time itself (minutes per game, at what
level) is a candidate driver.

Model: the college board's (scripts/cbb_fit.py): a continuation-ratio ladder P(30+), P(40+ | 30+), P(50+ | 40+),
P(60+ | 50+), E[FV] = 20 + 10 x P(30+) + 10 x P(40+) + 10 x P(50+) + (mean FV of 60+ careers - 50) x P(60+). Drivers
kept only if they lower out-of-sample deviance with whole players held out (cbb_fit.select). Board rank is the June
consensus in training; the live boards are months earlier, so the live rank enters as the distribution of the June
rank it predicts (No Ceilings' first board of each class 2019-26 against ESPN's final: slope, intercept and spread),
averaged over that spread.

FV: an international's E[FV] sits on the same scale as a D-I player's, so he gets the FV the college board gives
that E[FV] (the preseason board's E[FV] -> FV curve, scripts/cbb_prior.json.gz). The college grades don't move.
"""
import csv, gzip, html, json, math, os, re, subprocess, sys, time, difflib
from collections import defaultdict
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cbb_data as D
import names as N
import cbb_fit as F

DAILY = '--daily' in sys.argv
SEASON = 2027
CACHE = os.path.join(D.CACHE, 'intl')
BOARDS = os.environ.get('CBB_BOARDS', '/mnt/project-files/cbb/boards')
LIVE_BOARDS = os.path.join(D.ROOT, 'scripts', 'data', 'cbb_boards')
NBA_SEASONS = os.environ.get('CBB_NBA', '/mnt/project-files/cbb/xpm/nba_player_seasons.csv')
FIT = os.path.join(D.ROOT, 'scripts', 'data', 'cbb_intl_fit.json')
OUT = os.path.join(D.ROOT, 'static', 'data', 'cbb-intl.json')
SUMMARY = os.path.join(D.ROOT, 'data', 'cbb_intl.json')
TRAIN = range(2009, 2021)
BBREF = 'https://www.basketball-reference.com/international'

# league: (short name, first season pulled). Seasons are Basketball-Reference's (2027 = 2026-27)
LEAGUES = {'euroleague': ('EuroLeague', 2008), 'eurocup': ('EuroCup', 2008), 'spain-liga-acb': ('ACB', 2008),
           'italy-basket-serie-a': ('Serie A', 2008), 'greek-basket-league': ('Greece', 2008), 'france-lnb-pro-a': ('LNB', 2008),
           'nbl-australia': ('NBL', 2012), 'cba-china': ('CBA', 2012), 'turkey-super-league': ('BSL', 2021),
           'israel-super-league': ('Israel', 2021), 'aba-adriatic': ('ABA', 2021), 'vtb-united': ('VTB', 2021)}
BASE = 'euroleague'
STATS = ['g', 'mp', 'fg', 'fga', 'fg3', 'fg3a', 'ft', 'fta', 'orb', 'drb', 'ast', 'stl', 'blk', 'tov', 'pf', 'pts']
RATES = ['pts', 'ast', 'stl', 'blk', 'tov', 'orb', 'drb', 'fta', 'fg3a']     # per 100, translated on the log scale
MIN_PAIR = 200            # minutes in each league for a pair to count
PRIOR_W = 0.5             # the season before the draft season counts at half weight
G_LEAGUE = re.compile(r'ignite|g league|g-league|nbdl|d-league|overtime elite|\bote\b|city reapers|ync|yng|87ers|vipers|mad ants|'
                      r'skyforce|stampede|bayhawks|toros|energy|legends|hustle|drive|swarm|blue|herd|squadron|charge|jam\b|'
                      r'high school|prep|academy|\bhs\b', re.I)


# ---------------------------------------------------------------- raw pulls
def fetch(url, path, sleep=3.5):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    subprocess.run(['curl', '-s', '-m', '60', '-A', D.UA, url, '-o', path], check=False)
    time.sleep(sleep)


def cells(tr):
    out = {}
    for k, v in re.findall(r'data-stat="([a-z_0-9]+)"[^>]*>(.*?)</t[dh]>', tr, re.S):
        out[k] = v
    return out


def text(s): return html.unescape(re.sub(r'<[^>]+>', '', s or '')).strip()


def parse_totals(path):
    """player rows of a league's totals page, summed over the teams a player played for."""
    if not os.path.exists(path): return {}
    s = open(path, encoding='utf-8', errors='replace').read()
    i = s.find('id="totals-stats')
    if i < 0: return {}
    s = s[i:s.find('</table>', i)]
    out = {}
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', s, re.S):
        c = cells(tr)
        m = re.search(r"href='/international/players/([^']+)\.html'", c.get('player', ''))
        if not m: continue
        slug = m.group(1)
        r = out.setdefault(slug, {'slug': slug, 'name': text(c['player']), 'team': text(c.get('team_name')), **{k: 0.0 for k in STATS}})
        for k in STATS: r[k] += D.num(text(c.get(k))) or 0.0
        r['team'] = text(c.get('team_name')) or r['team']
    return out


def parse_pace(path):
    """possessions per 40 minutes per team (FGA + .44 FTA - ORB + TOV over team games)."""
    if not os.path.exists(path): return None
    s = open(path, encoding='utf-8', errors='replace').read()
    i = s.find('id="team_stats_totals"')
    if i < 0: return None
    s = s[i:s.find('</table>', i)]
    poss = g = 0.0
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', s, re.S):
        c = {k: D.num(text(v)) for k, v in cells(tr).items() if k != 'team_name'}
        if not c.get('g'): continue
        poss += (c.get('fga') or 0) + 0.44 * (c.get('fta') or 0) - (c.get('orb') or 0) + (c.get('tov') or 0); g += c['g']
    return poss / g if g else None


def load_leagues(years=None):
    """{(league, season): {'pace': .., 'players': {slug: row}}} from the cache."""
    out = {}
    for lg, (_, y0) in LEAGUES.items():
        for y in range(y0, SEASON + 1):
            if years and y not in years: continue
            pl = parse_totals(os.path.join(CACHE, f'{lg}-{y}.html'))
            if not pl: continue
            pace = parse_pace(os.path.join(CACHE, f'{lg}-{y}-teams.html')) or 72.0
            out[(lg, y)] = {'pace': pace, 'players': pl}
    return out


def per100(r, pace):
    """a line per 100 possessions, Game Score per 100 and true shooting."""
    poss = max(r['mp'], 1) / 40 * pace
    x = {k: r[k] / poss * 100 for k in RATES}
    x['gmsc'] = (r['pts'] + 0.4 * r['fg'] - 0.7 * r['fga'] - 0.4 * (r['fta'] - r['ft']) + 0.7 * r['orb'] + 0.3 * r['drb'] + r['stl']
                 + 0.7 * r['ast'] + 0.7 * r['blk'] - 0.4 * r['pf'] - r['tov']) / poss * 100
    tsa = r['fga'] + 0.44 * r['fta']
    x['ts'] = r['pts'] / (2 * tsa) if tsa > 0 else None
    x['ft'] = r['ft'] / r['fta'] if r['fta'] > 0 else None
    return x


# ---------------------------------------------------------------- league strength
def league_factors(L):
    """each league's offset against the EuroLeague, per stat, from players in two leagues (same season or back to back)."""
    by = defaultdict(dict)   # slug -> {(lg, y): (minutes, per100)}
    for (lg, y), d in L.items():
        for slug, r in d['players'].items():
            if r['mp'] >= MIN_PAIR: by[slug][(lg, y)] = (r['mp'], per100(r, d['pace']))
    lgs = sorted(LEAGUES)
    col = {lg: j for j, lg in enumerate(l for l in lgs if l != BASE)}
    keys = ['gmsc', 'ts'] + RATES
    out, npairs = {}, defaultdict(int)
    pairs = []
    for slug, ss in by.items():
        items = sorted(ss.items(), key=lambda t: (t[0][1], t[0][0]))
        for i, ((l1, y1), (m1, x1)) in enumerate(items):
            for (l2, y2), (m2, x2) in items[i + 1:]:
                if y2 - y1 > 1 or (l1 == l2 and y1 == y2): continue
                pairs.append((l1, y1, m1, x1, l2, y2, m2, x2))
                if l1 != l2: npairs[(min(l1, l2), max(l1, l2))] += 1
    for k in keys:
        A, b, w = [], [], []
        for l1, y1, m1, x1, l2, y2, m2, x2 in pairs:
            if x1.get(k) is None or x2.get(k) is None: continue
            v1, v2 = (x1[k], x2[k]) if k in ("gmsc", "ts") else (math.log(max(x1[k], 0) + 0.5), math.log(max(x2[k], 0) + 0.5))
            row = np.zeros(len(col) + 1)
            if l2 != BASE: row[col[l2]] += 1
            if l1 != BASE: row[col[l1]] -= 1
            row[-1] = y2 - y1            # a year older: the common growth term
            if not row.any(): continue
            A.append(row); b.append(v2 - v1); w.append(2 / (1 / m1 + 1 / m2))
        A, b, w = np.array(A), np.array(b), np.array(w) / 1000
        P = np.eye(A.shape[1]) * 0.5     # a league with few links stays near the EuroLeague's level
        beta = np.linalg.solve((A * w[:, None]).T @ A + P, (A * w[:, None]).T @ b)
        e = b - A @ beta
        cov = np.linalg.inv((A * w[:, None]).T @ A + P) * float((w * e ** 2).sum() / max(1, w.sum() - A.shape[1]))
        out[k] = {lg: (0.0 if lg == BASE else round(float(beta[col[lg]]), 4)) for lg in lgs}
        out[k]['_growth'] = round(float(beta[-1]), 4)
        out[k]['_se'] = {lg: (0.0 if lg == BASE else round(float(math.sqrt(cov[col[lg], col[lg]])), 4)) for lg in lgs}
        out[k]['_n'] = len(b)
    out['_pairs'] = {f'{a}|{b}': n for (a, b), n in sorted(npairs.items(), key=lambda t: -t[1])}
    return out


def growth_of_prospects(rows, lines, LF):
    """a board prospect's year-on-year change at EuroLeague level (draft season minus the season before, 300+
    minutes in each, weighted by the harmonic mean of the minutes): what the season before is aged by. The leagues'
    own growth term is every player's, veterans' decline included."""
    seen = set(); acc = defaultdict(lambda: [0.0, 0.0]); n = 0
    for r in rows:
        ss = lines.get(r['slug']) if r['slug'] else None
        if not ss or (r['slug'], r['year']) in seen: continue
        seen.add((r['slug'], r['year']))
        a, b = ss.get(r['year'], []), ss.get(r['year'] - 1, [])
        ma, mb = sum(s['mp'] for s in a), sum(s['mp'] for s in b)
        if ma < 300 or mb < 300: continue
        n += 1; w = 2 / (1 / ma + 1 / mb)
        for k in ['gmsc', 'ts'] + RATES:
            va = sum(s['mp'] * s['tr'][k] for s in a if s['tr'].get(k) is not None) / ma
            vb = sum(s['mp'] * s['tr'][k] for s in b if s['tr'].get(k) is not None) / mb
            d = va - vb if k in ('gmsc', 'ts') else math.log(va + 0.5) - math.log(vb + 0.5)
            acc[k][0] += w * d; acc[k][1] += w
    for k, (num, den) in acc.items():
        LF[k]['_leagueGrowth'] = LF[k]['_growth']; LF[k]['_growth'] = round(num / den, 4)
    LF['_growthN'] = n


def translate(x, lg, LF):
    """a per-100 line at EuroLeague level."""
    t = {}
    for k, v in x.items():
        if v is None or k not in LF: t[k] = v; continue
        t[k] = v - LF[k][lg] if k in ('gmsc', 'ts', 'ft') else math.exp(math.log(max(v, 0.0) + 0.5) - LF[k][lg]) - 0.5
    return t


# ---------------------------------------------------------------- players
def season_lines(L, LF):
    """slug -> season -> [(league, minutes, games, per100 raw, per100 translated)]"""
    out = defaultdict(lambda: defaultdict(list))
    for (lg, y), d in L.items():
        for slug, r in d['players'].items():
            if r['mp'] <= 0: continue
            x = per100(r, d['pace'])
            out[slug][y].append({'lg': lg, 'mp': r['mp'], 'g': r['g'], 'team': r['team'], 'raw': x, 'tr': translate(x, lg, LF), 'tot': r})
    return out


def pooled(lines, y, LF, k, growth=True):
    """the draft-season line pooled with the season before (half weight, aged a year by the leagues' growth term),
    each stat shrunk toward replacement by minutes. Returns features, or None when he has no line in either season."""
    ss = [(1.0, 0, s) for s in lines.get(y, [])] + [(PRIOR_W, 1, s) for s in lines.get(y - 1, [])]
    if not ss: return None
    f = {}
    rep = {'gmsc': -4.0, 'ts': 0.50, 'pts': 14.0, 'ast': 3.0, 'stl': 1.2, 'blk': 0.8, 'tov': 3.5, 'orb': 2.5, 'drb': 6.5, 'fta': 4.0, 'fg3a': 6.0, 'ft': 0.68}
    neff = sum(w * s['mp'] for w, _, s in ss)
    for key in ('gmsc', 'ts', 'ft') + tuple(RATES):
        for src in ('tr', 'raw'):
            num = den = 0.0
            for w, back, s in ss:
                v = s[src].get(key)
                if v is None: continue
                if growth and back and src == 'tr' and key in LF: v = v + LF[key]['_growth'] if key in ('gmsc', 'ts') else v * math.exp(LF[key]['_growth'])
                wt = w * (s['tot']['fta'] if key == 'ft' else s['mp'])
                num += wt * v; den += wt
            kk = 40 if key == 'ft' else k
            f[(key if src == 'tr' else key + '_raw')] = (num + rep[key] * kk) / (den + kk) if den else rep[key]
    cur = lines.get(y, [])
    mp = sum(s['mp'] for s in cur); g = max([s['g'] for s in cur] or [0])
    f['lmin'] = math.log1p(neff)
    f['mpg'] = (mp / g if g else 0.0)
    # level: the strength of where his minutes came from (EuroLeague 0, a weaker league below it), Game Score scale
    f['lvl'] = -sum(w * s['mp'] * LF['gmsc'][s['lg']] for w, _, s in ss) / max(1, neff)
    f['el'] = sum(s['mp'] for w, b, s in ss if s['lg'] in ('euroleague', 'eurocup') and not b) / max(1, mp)
    f['nostat'] = 0.0
    return f


# ---------------------------------------------------------------- boards and outcomes
def read_csv(p):
    with open(p, newline='', encoding='utf-8') as fh: return list(csv.DictReader(fh))


def college_names():
    """(norm name, season) for every D-I player season (Barttorvik), 2008 on."""
    out = set(); teams = set()
    for y in range(2008, SEASON + 1):
        for r in (D.load_bt(y) if os.path.exists(os.path.join(D.CACHE, 'bt', f'adv{y}.csv')) else []):
            out.add((r['key'], y)); teams.add(D.norm(r['team']).replace('st', 'state'))
    return out, teams


def is_college_school(s, teams):
    k = D.norm(s).replace('st', 'state')
    return bool(k) and (k in teams or any(t.startswith(k) or k.startswith(t) for t in teams if len(t) > 4 and len(k) > 4))


def same_person(a, b):
    """two spellings of one name: names that fit by the shared rules (scripts/names.py: Nik / Nikolas, accents,
    a one-letter typo), or a near match for transliterations (Riethauser / Reithauser)."""
    if not a.split() or not b.split(): return False
    if N.strength(a, b) >= 1: return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.85


def board_population(years, coll, teams):
    """{(year, key): {'name', 'school', 'pos', 'ranks': {board: rank}}} for the non-college prospects of each class,
    on ESPN's final board (blank school) or NBADraft.net's final board (a club)."""
    es = defaultdict(list); nd = defaultdict(list)
    for r in read_csv(os.path.join(BOARDS, 'espn.csv')):
        if r['rank'] and int(r['draft_year']) in years: es[int(r['draft_year'])].append(r)
    for r in read_csv(os.path.join(BOARDS, 'nbadraftnet.csv')):
        if int(r['draft_year']) in years: nd[int(r['draft_year'])].append(r)
    pop, depth = {}, {}
    for y in years:
        depth[y] = {'espn': max([int(r['rank']) for r in es[y]] or [100]), 'ndn': max([int(r['rank']) for r in nd[y]] or [100])}
        ndk = {D.norm(r['name']): r for r in nd[y]}
        for src, rows in (('espn', es[y]), ('ndn', nd[y])):
            for r in rows:
                k = D.norm(r['name'])
                if (k, y) in coll or (k, y - 1) in coll: continue
                school = r['school'] or (ndk.get(k) or {}).get('school', '')
                if src == 'espn' and r['school']: continue                    # ESPN names a school for college and G League players
                if G_LEAGUE.search(school or '') or (school and is_college_school(school, teams)): continue
                hit = next((q for q in pop if q[0] == y and (q[1] == k or same_person(q[1], k))), None)
                p = pop.setdefault(hit or (y, k), {'name': r['name'], 'school': '', 'pos': r['pos'], 'ranks': {}, 'year': y})
                p['ranks'][src] = int(r['rank'])
                if src == 'ndn': p['school'] = r['school'] or p['school']; p['pos'] = p['pos'] or r['pos']
    for p in pop.values():
        d = depth[p['year']]
        lr = [-math.log(p['ranks'].get(s, 1.5 * d[s])) for s in ('espn', 'ndn')]
        p['lr'] = float(np.mean(lr)); p['nb'] = len(p['ranks'])
    return pop


def nba_outcomes(cuts):
    """norm name -> {'first', 'mp', 'peakXpm', 'fv'} from Basketball-Reference NBA seasons 2009-26 (the xpm research set)."""
    by = defaultdict(list)
    for r in read_csv(NBA_SEASONS):
        mp = D.num(r['mp']) or 0; bl = D.num(r['blend']); bp = D.num(r['bpm'])
        v = bl if bl is not None else bp
        if v is None: continue
        by[(D.norm(r['name']), r['pid'])].append((int(r['year']), mp, v))
    ts = sorted(int(k) for k in cuts)
    out = {}
    for (k, pid), ss in by.items():
        xv = sorted(((mp * v + 500 * -2.0) / (mp + 500) for _, mp, v in ss), reverse=True) + [-2.5] * 3
        px = sum(xv[:3]) / 3
        o = {'pid': pid, 'first': min(y for y, _, _ in ss), 'mp': sum(mp for _, mp, _ in ss), 'peakXpm': round(px, 2),
             'fv': round(float(np.interp(px, [cuts[str(t)] for t in ts], ts)), 2)}
        if k not in out or out[k]['mp'] < o['mp']: out[k] = o
    return out


def outcome_of(p, nba):
    k = D.norm(p['name'])
    o = nba.get(k)
    if not o:
        cand = [q for q in nba if same_person(q, k)]
        o = nba[cand[0]] if len(cand) == 1 else None
    if o and o['first'] >= p['year'] + 1: return o
    return None


def player_page(slug):
    """birth date and height from a Basketball-Reference international player page (cached)."""
    path = os.path.join(CACHE, 'players', slug + '.html')
    if not os.path.exists(path) and not os.environ.get('CBB_NO_FETCH'): fetch(f'{BBREF}/players/{slug}.html', path)
    s = open(path, encoding='utf-8', errors='replace').read() if os.path.exists(path) else ''
    dob = re.search(r'data-birth="(\d{4}-\d\d-\d\d)"', s)
    cm = re.search(r'(\d{3})cm', s)
    return {'dob': dob.group(1) if dob else None, 'hti': round(int(cm.group(1)) / 2.54, 1) if cm else None}


def link_slug(name, y, lines_by_name):
    """the Basketball-Reference international player for a board name, by seasons y and y - 1."""
    k = D.norm(name)
    c = {s for s, yrs in lines_by_name.get(k, {}).items() if yrs & {y, y - 1}}
    if len(c) == 1: return c.pop()
    if c: return None
    near = {s for q, d in lines_by_name.items() if q.split() and k.split() and q.split()[-1] == k.split()[-1] and same_person(q, k)
            for s, yrs in d.items() if yrs & {y, y - 1}}
    return near.pop() if len(near) == 1 else None


POS = {'PG': 'G', 'SG': 'G', 'G': 'G', 'SF': 'F', 'PF': 'F', 'F': 'F', 'C': 'C'}


def pos_of(s):
    t = re.split(r'[/\- ]', (s or '').upper())[0]
    return POS.get(t, 'F')


def features(p, lines, LF, k, info):
    y = p['year']
    f = pooled(lines, y, LF, k) if lines is not None else None
    if f is None:
        f = {'nostat': 1.0}
    f['lr'] = p['lr']
    f['top'] = max(0.0, p['lr'] + math.log(10))      # inside the top 10
    a = D.age_on(info.get('dob'), y, 6, 25) if info.get('dob') else None
    f['age'] = a if a else 20.3
    f['age_known'] = 1.0 if a else 0.0
    f['age2'] = (f['age'] - 20.5) ** 2
    pos = pos_of(p.get('pos'))
    f['big'] = 1.0 if pos == 'C' else 0.0
    f['guard'] = 1.0 if pos == 'G' else 0.0
    f['ht'] = info.get('hti') or {'G': 76.5, 'F': 80.0, 'C': 83.0}[pos]
    f['ht_g'] = f['ht'] - {'G': 76.5, 'F': 80.0, 'C': 83.0}[pos]
    if 'gmsc' in f:
        f['gmsc_x_age'] = f['gmsc'] * (20.5 - f['age'])
    return f


CANDS = ['lr', 'top', 'gmsc', 'ts', 'ft', 'pts', 'ast', 'stl', 'blk', 'tov', 'orb', 'drb', 'fta', 'fg3a', 'lvl', 'el',
         'lmin', 'mpg', 'nostat', 'age', 'age2', 'gmsc_x_age', 'ht', 'ht_g', 'big', 'guard']


# ---------------------------------------------------------------- fit
GRID = (1, 3, 10, 30, 100, 300, 1000)


def lam_for(rows, X, idx):
    """per-rung penalty, the out-of-sample best of the grid (as cbb_fit.select picks it)."""
    y = np.array([r['y'] for r in rows], float)
    folds = np.array([F.fold_of(r['pid']) for r in rows])
    devs = []
    for g in GRID:
        P = np.zeros((len(rows), len(F.LADDER)))
        for k in range(F.FOLDS):
            tr, te = folds != k, folds == k
            P[te] = F.predict(F.fit([r for r, t in zip(rows, tr) if t], X[tr], idx, g), X[te])[1]
        devs.append(F.rung_dev(P, y))
    return [GRID[int(np.argmin([d[j] for d in devs]))] for j in range(len(F.LADDER))]


def oos(rows, cols):
    X = F.matrix(rows, cols); idx = list(range(len(cols)))
    lam = lam_for(rows, X, idx)
    err, ferr, e = F.cv_error(rows, X, idx, lam)
    y = np.array([r['y'] for r in rows], float)
    P = None
    return {'drivers': cols, 'pseudoR2': round(1 - err, 4), 'auc_nba': round(F.auc(e, y >= 30), 3),
            'auc_starter': round(F.auc(e, y >= 45), 3), 'corr': round(float(np.corrcoef(e, y)[0, 1]), 3)}, e


def attenuation():
    """the June consensus rank a preseason board rank predicts: -ln(ESPN final rank) on -ln(No Ceilings' first board
    rank), 2019-2026 classes (a player off the final board sits at 1.5 x its depth)."""
    nc = defaultdict(lambda: defaultdict(dict))
    for r in read_csv(os.path.join(BOARDS, 'noceilings.csv')): nc[int(r['draft_year'])][r['board_date']][D.norm(r['name'])] = int(r['rank'])
    es = defaultdict(dict)
    for r in read_csv(os.path.join(BOARDS, 'espn.csv')):
        if r['rank']: es[int(r['draft_year'])][D.norm(r['name'])] = int(r['rank'])
    X, Y = [], []
    for y in range(2019, SEASON):
        if y not in nc or not es.get(y): continue
        b = nc[y][min(nc[y])]; dep = max(es[y].values())
        for k, rk in b.items():
            X.append(-math.log(rk)); Y.append(-math.log(es[y].get(k, 1.5 * dep)))
    X, Y = np.array(X), np.array(Y)
    b, a = np.polyfit(X, Y, 1)
    s = float(np.std(Y - (a + b * X), ddof=2))
    return {'a': round(float(a), 4), 'b': round(float(b), 4), 'sd': round(s, 4), 'n': len(X), 'r': round(float(np.corrcoef(X, Y)[0, 1]), 3)}


GH = np.polynomial.hermite_e.hermegauss(9)   # nodes and weights for an average over a normal


def ev_model(m, f, att=None):
    """E[FV], P(NBA), parts for a feature dict; with att, the rank enters as the June rank it predicts (averaged over
    its spread)."""
    mu, sd, W = np.array(m['mean']), np.array(m['sd']), [np.array(w) for w in m['w']]

    def at(ff):
        x = np.array([ff.get(k) if ff.get(k) is not None else np.nan for k in m['kept']], float)
        z = np.clip(np.nan_to_num((x - mu) / sd), -4, 4)
        cs = [1 / (1 + math.exp(-max(-30, min(30, w[0] + w[1:] @ z)))) for w in W]
        ps = list(np.cumprod(cs))
        return ps[0], F.FLOOR + 10 * (ps[0] + ps[1] + ps[2]) + (m['topMean'] - 50) * ps[3], x, z

    def avg(ff):
        if not att: p, e, _, _ = at(ff); return p, e
        lr0 = att['a'] + att['b'] * ff['lr_board']
        pe = np.zeros(2)
        for node, wt in zip(*GH):
            g = dict(ff); g['lr'] = lr0 + att['sd'] * node; g['top'] = max(0.0, g['lr'] + math.log(10))
            p, e, _, _ = at(g); pe += wt * np.array([p, e])
        return tuple(pe / GH[1].sum())
    p, e = avg(f)
    g = dict(f)
    if att: g['lr'] = att['a'] + att['b'] * f['lr_board']; g['top'] = max(0.0, g['lr'] + math.log(10))
    _, e_mid, x, z = at(g)
    parts = []
    for j, k in enumerate(m['kept']):
        h = dict(g); h[k] = mu[j]
        if k == 'lr': h['top'] = max(0.0, mu[j] + math.log(10))
        parts.append((k, e_mid - at(h)[1], x[j]))
    return e, p, parts


def college_curve():
    """the D-I board's grade scale as knots (FV -> FV): an international is placed by expected outcome against the
    D-I grades themselves (outcome_map), so the board's own E[FV] scale (model plus board stage) doesn't enter."""
    return [[float(v), float(v)] for v in range(20, 81)]


def outcome_map(curve):
    """the D-I board's E[FV] -> expected realized FV: at each graded FV, the E[FV] today's board gives it (curve)
    against the mean FV the players graded there went on to (out of fold, 2009-16 boards: data/cbb_fit.json calib;
    the 60-70 grades pooled, 24 players)."""
    cal = json.load(open(F.OUT))['calib']
    E = np.array([c[0] for c in curve]); V = np.array([c[1] for c in curve])
    pts = [(20.0, 20.0)]
    for t in (30, 35, 40, 45, 50, 55):
        pts.append((float(np.interp(t + 2.5, V, E)), cal[str(t)]['meanFv']))
    top = [cal[str(t)] for t in (60, 65, 70)]
    pts.append((float(np.interp(65, V, E)), sum(c['meanFv'] * c['n'] for c in top) / sum(c['n'] for c in top)))
    out = [pts[0]]
    for e, r in pts[1:]:
        if e > out[-1][0] and r > out[-1][1]: out.append((e, r))
    return [[round(e, 3), round(r, 2)] for e, r in out]


def fv_of(e_intl, fit):
    """an international's FV: his E[FV] -> the realized FV it predicts (his model's out-of-fold calibration, a line
    through the floor) -> the D-I E[FV] that predicts the same -> the FV the board gives that E[FV]."""
    r = F.FLOOR + fit['beta'] * (e_intl - F.FLOOR)
    M = fit['omap']; Me = np.array([m[0] for m in M]); Mr = np.array([m[1] for m in M])
    if r <= Mr[-1]: e = float(np.interp(r, Mr, Me))
    else: e = Me[-1] + (r - Mr[-1]) * (Me[-1] - Me[-2]) / (Mr[-1] - Mr[-2])
    return fv_curve(e, fit['curve'])


def fv_curve(e, curve):
    E = np.array([c[0] for c in curve]); V = np.array([c[1] for c in curve])
    if e <= E[-1]: return float(np.interp(e, E, V))
    # past the board's top E[FV]: the slope of its top 20 players, capped at 80
    j = max(0, len(E) - 20)
    s = (V[-1] - V[j]) / max(1e-6, E[-1] - E[j])
    return float(min(80.0, V[-1] + s * (e - E[-1])))


def full():
    print('league pages ...')
    L = load_leagues()
    print(f'{len(L)} league seasons, {sum(len(d["players"]) for d in L.values())} player lines')
    LF = league_factors(L)
    print('league offsets vs EuroLeague, Game Score per 100:', {LEAGUES[k][0]: v for k, v in LF['gmsc'].items() if not k.startswith('_')},
          'growth', LF['gmsc']['_growth'], 'pairs', LF['gmsc']['_n'])
    coll, teams = college_names()
    pop = board_population(TRAIN, coll, teams)
    fit_cbb = json.load(open(F.OUT))
    F.TOP_MEAN = 67.0
    nba = nba_outcomes(fit_cbb['xpmCuts'])
    # the TOP_MEAN the college model uses (mean FV of 60+ careers), so E[FV] sits on its scale
    F.TOP_MEAN = fit_cbb['models']['returner']['topMean']
    names = defaultdict(lambda: defaultdict(set))
    for (lg, y), d in L.items():
        for slug, r in d['players'].items(): names[D.norm(r['name'])][slug].add(y)
    rows = []
    infos = {}
    for (y, k), p in sorted(pop.items()):
        slug = link_slug(p['name'], y, names)
        info = infos.setdefault(slug, player_page(slug)) if slug else {}
        o = outcome_of(p, nba)
        rows.append({'pid': D.norm(p['name']), 'name': p['name'], 'year': y, 'slug': slug, 'p': p, 'info': info,
                     'y': o['fv'] if o else float(F.FLOOR), 'xpm': o['peakXpm'] if o else None})
    print(f'training population: {len(rows)} board rows ({len({r["pid"] for r in rows})} players), '
          f'{sum(1 for r in rows if r["slug"])} with league lines, {sum(1 for r in rows if r["y"] >= 30)} reached the NBA')
    lines = season_lines(L, LF)
    growth_of_prospects(rows, lines, LF)
    print('a year of growth for a board prospect (EuroLeague-level Game Score per 100):', LF['gmsc']['_growth'], LF['_growthN'])

    def build(k):
        for r in rows: r['f'] = features(r['p'], lines.get(r['slug']) if r['slug'] else None, LF, k, r['info'])
    # minutes shrink: k by out-of-sample deviance of rank + translated production + minutes
    kr = {}
    for k in (100, 250, 500, 1000, 2000):
        build(k); kr[k] = oos(rows, ['lr', 'top', 'age', 'gmsc', 'lmin', 'nostat'])[0]['pseudoR2']
    K = max(kr, key=kr.get)
    print('minutes shrink k -> OOS pseudo-R2:', kr, 'picked', K)
    build(K)
    ladder = {}
    for name, cols in (('rank', ['lr', 'top']), ('rank + age', ['lr', 'top', 'age', 'age2']),
                       ('+ raw production', ['lr', 'top', 'age', 'age2', 'gmsc_raw', 'nostat']),
                       ('+ league-adjusted production', ['lr', 'top', 'age', 'age2', 'gmsc', 'nostat']),
                       ('+ minutes and level', ['lr', 'top', 'age', 'age2', 'gmsc', 'nostat', 'lmin', 'mpg', 'lvl']),
                       ('production only (no rank)', ['age', 'age2', 'gmsc', 'nostat', 'lmin', 'mpg', 'lvl'])):
        ladder[name] = oos(rows, cols)[0]
        print(f'  {name:32s}', ladder[name])
    sel = F.select(rows, CANDS, 'international')
    X = F.matrix(rows, sel['kept'])
    m = F.fit(rows, X, list(range(len(sel['kept']))), sel['lam'])
    res, e_oof = oos(rows, sel['kept'])
    print('selected:', res)
    # calibration: out-of-fold E[FV] bands against what they became
    cal = []
    y = np.array([r['y'] for r in rows])
    for lo, hi in ((20, 25), (25, 30), (30, 35), (35, 40), (40, 45), (45, 80)):
        ix = (e_oof >= lo) & (e_oof < hi)
        if ix.sum(): cal.append({'e': f'{lo}-{hi}', 'n': int(ix.sum()), 'meanE': round(float(e_oof[ix].mean()), 1), 'meanFv': round(float(y[ix].mean()), 1),
                                 'nba': round(float((y[ix] >= 30).mean()), 3), 'starter': round(float((y[ix] >= 45).mean()), 3)})
    print('calibration:', cal)
    att = attenuation()
    print('preseason rank -> June rank:', att)
    model = F.model_json(sel, m)
    model['topMean'] = F.TOP_MEAN
    curve = college_curve()
    omap = outcome_map(curve)
    beta = float(((e_oof - F.FLOOR) * (y - F.FLOOR)).sum() / ((e_oof - F.FLOOR) ** 2).sum())
    print('out-of-fold calibration: realized - 20 =', round(beta, 3), 'x (E[FV] - 20); D-I E[FV] -> realized:', omap)
    tmp = {'beta': beta, 'omap': omap, 'curve': curve}
    # the training rows as graded out of fold (what each became), for the method note
    hist = sorted(({'year': r['year'], 'name': r['name'], 'e': round(float(e), 2), 'fv': int(fv_of(float(e), tmp)), 'outcome': r['y'], 'xpm': r['xpm']}
                   for r, e in zip(rows, e_oof)), key=lambda h: -h['e'])
    fit = {'asof': time.strftime('%Y-%m-%d'), 'train': f'{TRAIN[0]}-{TRAIN[-1]}', 'rows': len(rows), 'nba': int((y >= 30).sum()), 'k': K, 'kTest': kr,
           'leagues': {lg: v[0] for lg, v in LEAGUES.items()}, 'factors': LF, 'model': model, 'ladder': ladder, 'selected': res,
           'calib': cal, 'att': att, 'curve': curve, 'omap': omap, 'beta': round(beta, 4), 'topOof': hist[:40],
           'pace': {lg: round(L[(lg, SEASON - 1)]['pace'], 2) for lg in LEAGUES if (lg, SEASON - 1) in L}}
    # live: the 2027 boards' internationals, their league lines (the season before is kept here for the daily job)
    live = live_population(teams)
    names_now = defaultdict(lambda: defaultdict(set))
    for (lg, yy), d in L.items():
        if yy >= SEASON - 2:
            for slug, r in d['players'].items(): names_now[D.norm(r['name'])][slug].add(yy)
    for p in live:
        p['slug'] = link_slug(p['name'], SEASON, names_now)
        p['info'] = player_page(p['slug']) if p['slug'] else {}
    fit['live'] = [{'name': p['name'], 'school': p['school'], 'pos': p['pos'], 'lr_board': p['lr_board'], 'cons': p['cons'], 'nb': p['nb'],
                    'ranks': p['ranks'], 'slug': p['slug'], 'info': p['info'],
                    'prev': [dict(s, raw=None, tr=None) for s in lines.get(p['slug'], {}).get(SEASON - 1, [])] if p['slug'] else []} for p in live]
    fit['overseas'] = overseas_lines(L, LF, names_now)
    print(len(fit['overseas']), 'D-I players with an overseas line from the last two seasons (shown in the report, not in the FV)')
    os.makedirs(os.path.dirname(FIT), exist_ok=True)
    json.dump(fit, open(FIT, 'w'), separators=(',', ':'))
    print('wrote', FIT)
    grade_live(fit, L)


def overseas_lines(L, LF, names_now):
    """the overseas line of each D-I player who came over in the last two seasons (a newcomer, or a returner with one
    D-I season), matched by name and an age that fits (17-23 at the line): shown in his scouting report only. Too few
    past players took this path to test it as an FV driver (6 newcomers on the 2009-16 boards, 1 reached the NBA)."""
    a = json.load(open(os.path.join(D.ROOT, 'static', 'data', 'cbb-all.json')))
    ci = {c: j for j, c in enumerate(a['cols'])}
    out = {}
    for r in a['rows']:
        last = r[ci['last']]
        if not (r[ci['new']] or (last and last.get('seasons', 9) <= 1)): continue
        k = D.norm(r[ci['name']])
        cand = {s for s, yrs in names_now.get(k, {}).items()}
        if len(cand) != 1: continue
        slug = cand.pop()
        info = player_page(slug)
        best = None
        for (lg, y), d in L.items():
            if y < SEASON - 2 or slug not in d['players']: continue
            t = d['players'][slug]
            age = D.age_on(info.get('dob'), y - 1, 11, 1) if info.get('dob') else None
            if age is None or not 16.5 <= age <= 23.5 or t['mp'] < 50: continue
            if best is None or (y, t['mp']) > (best[1], best[2]['mp']): best = (lg, y, t, d['pace'])
        if not best: continue
        lg, y, t, pace = best
        x = per100(t, pace); tr = translate(x, lg, LF); g = max(1, t['g'])
        out[r[ci['name']]] = {'season': f'{y - 1}-{str(y)[2:]}', 'team': t['team'], 'lg': LEAGUES[lg][0], 'gp': int(t['g']), 'mpg': round(t['mp'] / g, 1),
                              'ppg': round(t['pts'] / g, 1), 'gmsc': round(x['gmsc'], 1), 'gmscEl': round(tr['gmsc'], 1), 'url': f'{BBREF}/players/{slug}.html'}
    return out


def live_population(teams):
    """internationals on the current boards: not on a D-I roster, not at a college or G League team."""
    import cbb_mock as M
    files = sorted(f for f in os.listdir(LIVE_BOARDS) if f.endswith('.csv'))
    boards = [[(r['name'], r['school'], r['pos'], int(r['rank'])) for r in read_csv(os.path.join(LIVE_BOARDS, f))] for f in files]
    ppl = M.consensus(boards)
    a = json.load(open(os.path.join(D.ROOT, 'static', 'data', 'cbb-all.json')))
    ours = {D.norm(r[0]) for r in a['rows']}
    teams = set(teams) | {D.norm(r[1]).replace('st', 'state') for r in a['rows']}
    out = []
    for k, p in ppl.items():
        if k in ours or any(same_person(k, q) for q in ours if q.split() and q.split()[-1] == k.split()[-1]): continue
        if G_LEAGUE.search(p['school'] or '') or is_college_school(p['school'], teams): continue
        out.append({'name': p['name'], 'school': p['school'], 'pos': p['pos'], 'cons': p['cons'], 'nb': p['nboards'],
                    'ranks': {files[b][:-4].replace('_2027', ''): r for b, r in p['ranks'].items()}, 'lr_board': -math.log(p['cons'])})
    # one player under two spellings on different boards (Riethauser / Reithauser): keep the better-ranked entry, pool the boards
    out.sort(key=lambda p: p['cons'])
    merged = []
    for p in out:
        q = next((q for q in merged if same_person(D.norm(q['name']), D.norm(p['name']))), None)
        if q: q['ranks'].update({b: r for b, r in p['ranks'].items() if b not in q['ranks']}); q['nb'] = len(q['ranks'])
        else: merged.append(p)
    return merged


# ---------------------------------------------------------------- grade
CLUB = {'Baskonia (Spain)': 'Baskonia', 'Nanterre': 'Nanterre 92', 'Cedevita': 'Cedevita Olimpija', 'Élan Chalon': 'Chalon'}
LABEL = {'lr': 'draft board rank', 'top': 'top-10 on the boards', 'gmsc': 'production at EuroLeague level', 'ts': 'true shooting',
         'ft': 'FT%', 'pts': 'scoring rate', 'ast': 'assist rate', 'stl': 'steal rate', 'blk': 'block rate', 'tov': 'turnover rate',
         'orb': 'offensive rebounding', 'drb': 'defensive rebounding', 'fta': 'FT attempt rate', 'fg3a': '3PA rate',
         'lvl': 'league level', 'el': 'EuroLeague/EuroCup minutes', 'lmin': 'minutes played', 'mpg': 'minutes a game',
         'nostat': 'no league line', 'age': 'age', 'age2': 'age curve', 'gmsc_x_age': 'production for age', 'ht': 'height',
         'ht_g': 'size for position', 'big': 'big', 'guard': 'guard'}


def ht_str(i):
    if not i: return None
    i = int(round(i)); return f"{i // 12}' {i % 12}\""


def grade_live(fit, L):
    LF, m, att, K = fit['factors'], fit['model'], fit['att'], fit['k']
    F.TOP_MEAN = m['topMean']
    out = []
    for p in fit['live']:
        lines = defaultdict(list)
        for s in p['prev']:
            d = L.get((s['lg'], SEASON - 1))
            pace = d['pace'] if d else 72.0
            x = per100(s['tot'], pace); lines[SEASON - 1].append(dict(s, raw=x, tr=translate(x, s['lg'], LF)))
        if p['slug']:
            for (lg, y), d in L.items():
                if y == SEASON and p['slug'] in d['players']:
                    r = d['players'][p['slug']]
                    x = per100(r, d['pace']); lines[SEASON].append({'lg': lg, 'mp': r['mp'], 'g': r['g'], 'team': r['team'], 'raw': x, 'tr': translate(x, lg, LF), 'tot': r})
        q = {'year': SEASON, 'lr': att['a'] + att['b'] * p['lr_board'], 'pos': p['pos']}
        f = features(q, lines if p['slug'] and lines else None, LF, K, p['info'])
        f['lr_board'] = p['lr_board']
        e, pn, parts = ev_model(m, f, att)
        fvx = fv_of(e, fit)
        out.append((p, f, e, pn, parts, fvx, lines))
    out.sort(key=lambda t: -t[2])
    cols = ['name', 'team', 'logo', 'conf', 'pos', 'role', 'ovr', 'posRank', 'fv', 'plus', 'fvx', 'nbaP', 'xbpm', 'cls', 'elig', 'age', 'ageEst',
            'ht', 'wt', 'photo', 'new', 'last', 'rec', 'parts', 'report', 'links', 'intl', 'cons', 'boards', 'e']
    rows = []
    for p, f, e, pn, parts, fvx, lines in out:
        info = p['info'] or {}
        age = D.age_on(info['dob'], *time.gmtime()[:3]) if info.get('dob') else None
        lastd = None
        for yy in (SEASON, SEASON - 1):
            ls = lines.get(yy) or []
            if not ls or (yy == SEASON and sum(s['mp'] for s in ls) < 150 and lines.get(SEASON - 1)): continue
            s = max(ls, key=lambda s: s['mp'])
            t = s['tot']; g = max(1, t['g'])
            lastd = {'season': f'{yy - 1}-{str(yy)[2:]}', 'team': s['team'], 'lg': fit['leagues'][s['lg']], 'gp': int(t['g']), 'mpg': round(t['mp'] / g, 1),
                     'ppg': round(t['pts'] / g, 1), 'rpg': round((t['orb'] + t['drb']) / g, 1), 'apg': round(t['ast'] / g, 1),
                     'gmsc': round(s['raw']['gmsc'], 1), 'gmscEl': round(s['tr']['gmsc'], 1), 'ts': round(100 * (s['raw']['ts'] or 0), 1),
                     'tp': round(100 * t['fg3'] / t['fg3a'], 1) if t['fg3a'] else None, 'tpa': int(t['fg3a']),
                     'ft': round(100 * t['ft'] / t['fta'], 1) if t['fta'] else None, 'stl': round(s['raw']['stl'], 1), 'blk': round(s['raw']['blk'], 1),
                     'other': [f"{fit['leagues'][o['lg']]} {int(o['tot']['g'])} G" for o in ls if o is not s], 'seasons': sorted(lines)}
            break
        lab = [[LABEL.get(k, k), round(float(v), 2), None if x != x else round(float(x), 3)] for k, v, x in parts]
        rows.append([p['name'], CLUB.get(p['school'], p['school']), None, lastd['lg'] if lastd else 'Intl', pos_of(p['pos']), None, 0, 0,
                     int(math.floor(fvx + 1e-9)), False, round(fvx, 2), round(pn, 4), None, 'Intl', 0,
                     round(age, 1) if age else None, None if age else round(f['age'] - 0.7, 1), ht_str(info.get('hti')), None, None, 0,
                     lastd, None, lab, report(p, f, parts, lastd, fit), ({'bbref': f"{BBREF}/players/{p['slug']}.html"} if p['slug'] else {}),
                     1, p['cons'], p['nb'], round(e, 3)])
    if os.path.exists(OUT) and DAILY and json.load(open(OUT)).get('rows') == json.loads(json.dumps(rows)):
        print('no new lines: the internationals are unchanged'); return
    json.dump({'cols': cols, 'rows': rows, 'overseas': fit.get('overseas', {}), 'asof': time.strftime('%Y-%m-%d')}, open(OUT, 'w'), separators=(',', ':'))
    json.dump({'asof': time.strftime('%Y-%m-%d'), 'train': fit['train'], 'rows': fit['rows'], 'nba': fit['nba'], 'k': fit['k'],
               'leagues': {fit['leagues'][lg]: {'gmsc': v, 'se': fit['factors']['gmsc']['_se'][lg]} for lg, v in fit['factors']['gmsc'].items() if not lg.startswith('_')},
               'growth': fit['factors']['gmsc']['_growth'], 'beta': fit['beta'], 'pairs': fit['factors']['gmsc']['_n'], 'ladder': [dict(v, name=k) for k, v in fit['ladder'].items()], 'selected': fit['selected'], 'calib': fit['calib'], 'att': fit['att'],
               'kept': [LABEL.get(k, k) for k in fit['model']['kept']], 'evidence': [dict(x, driver=LABEL.get(x['driver'], x['driver'])) for x in fit['model']['evidence']],
               'top': [[r[0], r[1], r[8]] for r in rows]}, open(SUMMARY, 'w'), indent=1)
    for r in rows: print(f"{r[0]:24s} {r[1]:20s} {r[3]:10s} cons {r[27]:3d} FV {r[8]} ({r[10]}) NBA {r[11]:.2f} E {r[29]}")
    print('wrote', OUT)


def report(p, f, parts, L, fit):
    net = {}
    for k, v, x in sorted(parts, key=lambda t: -abs(t[1]))[:8]:
        if abs(v) < 0.15: continue
        if k in ('lr', 'top'):
            line = f"draft boards: consensus No. {p['cons']}, on {p['nb']} of 7 boards"
        elif k in ('age', 'age2', 'gmsc_x_age') and k != 'gmsc_x_age':
            line = f"age: {f['age']:.1f} on draft night"
        elif k in ('gmsc', 'gmsc_x_age') and L:
            line = f"production: {L['gmscEl']:+.1f} Game Score per 100 at EuroLeague level ({L['gmsc']:+.1f} in {L['lg']})"
        elif k in ('lmin', 'mpg') and L:
            line = f"playing time: {L['mpg']} mpg over {L['gp']} games in {L['lg']}"
        elif k in ('lvl', 'el') and L:
            line = f"level: {L['lg']}" + (f" and {', '.join(L['other'])}" if L['other'] else '')
        elif k in ('ht', 'ht_g'):
            line = f"size: {ht_str(f['ht'])} for a {'guard' if f.get('guard') else 'big' if f.get('big') else 'forward'}"
        elif k == 'nostat':
            line = 'no line in the leagues we track (graded on the boards, age and size)'
        elif L and k == 'stl':
            line = f"hands: {L['stl']} steals per 100"
        elif L and k == 'blk':
            line = f"rim protection: {L['blk']} blocks per 100"
        elif L and k in ('ts', 'ft', 'fg3a', 'fta'):
            line = f"shooting: {L['ts']}% TS, {L['ft'] if L['ft'] is not None else '-'}% FT, {L['tpa']} 3PA"
        else:
            line = LABEL.get(k, k)
        net[line] = net.get(line, 0.0) + v
    return {'plus': [k for k, v in net.items() if v > 0][:4], 'minus': [k for k, v in net.items() if v < 0][:4]}


def daily():
    fit = json.load(open(FIT))
    for lg in LEAGUES:
        fetch(f'{BBREF}/{lg}/{SEASON}_totals.html', os.path.join(CACHE, f'{lg}-{SEASON}.html'))
        fetch(f'{BBREF}/{lg}/{SEASON}.html', os.path.join(CACHE, f'{lg}-{SEASON}-teams.html'))
    L = load_leagues({SEASON})
    for lg in LEAGUES:   # last season's pace, for the kept lines
        L.setdefault((lg, SEASON - 1), {'pace': fit.get('pace', {}).get(lg, 72.0), 'players': {}})
    grade_live(fit, L)


if __name__ == '__main__':
    daily() if DAILY else full()
