#!/usr/bin/env python3
"""NBA injury news repricing study (betting plan item 8): does the market under- or over-react when a rotation
player's status changes between the opening line and the close? Research only: writes data/nba_news_fit.json, read
by the NBA picks backtest tab. The game model is not changed here.

    python3 scripts/nba_news_research.py --sbr        # opening/closing spreads 2019-20..2022-23 (SportsbookReviews)
    python3 scripts/nba_news_research.py --reports    # official injury reports at the open and the last before tip
    python3 scripts/nba_news_research.py              # the study (numpy) -> data/nba_news_fit.json

Data (all free): the NBA's official injury reports (hourly from 2021-22, three a day before), ESPN opening and closing
spreads 2023-24 on (scripts/nba_games_hist.json.gz), SportsbookReviews' archive for 2019-20 to 2022-23, box-score
minutes for who actually played, and the game model's lineup term (scripts/nba_games.py: recent minutes x XPM x
P(play), filled to 240 at replacement).

Snapshots per game: the open = the report at 8:30 PM ET the day before (teams file next-day statuses by 5 PM local;
second nights of back-to-backs file by 1 PM game day, so those fall back to the 1:30 PM report); the final report =
the last one stamped at least 15 minutes before tip; actual = who logged minutes.
News, in lineup points (XPM x minutes / 48, home minus away): rep = final report vs open, both priced at the model's
play chances; late = actual vs final report. The market's move is close - open.

Findings (Oct 21 2026, 6,855 games): the close moves .89 per lineup point of report news and results (vs the open)
say .88; what the close missed is ~0 (t -0.0, held out +0.3), in every cell (stars or role players, ruled out or
cleared). The game model prices news at lin + roster = .71, light by about a fifth. Questionable at the open played
55% (62% weighted by value); with the injury known the open priced 60% vs 64% actual. No rule beat the close held
out: fading questionable value at the open moves the line our way (+.5 pts, t 4.9) but clvRet -1.5%; fading late
news at the close went 55.5% ATS 2019-23 (t 3.0) and 54.0% held out (t 0.9), carried by no one kind of news.
"""
import datetime as dt, html, json, math, os, re, subprocess, sys, time, urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nba_espn as E
import nba_games as G

ROOT = os.path.dirname(HERE)
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'nba')
REP_CACHE = os.path.join(CACHE, 'injrep')
SBR = os.path.join(CACHE, 'sbr_odds.json')
REPS = os.path.join(CACHE, 'news_reports.json')
OUT = os.path.join(ROOT, 'data', 'nba_news_fit.json')
ET = ZoneInfo('America/New_York')
URL = 'https://ak-static.cms.nba.com/referee/injury/Injury-Report_{d}_{t}.pdf'
SEASONS = range(2020, 2027)
HOLD_FROM = 2024                 # 2019-20..2022-23 tune, 2023-24..2025-26 held out

# ---------------------------------------------------------------- SportsbookReviews spreads, 2019-20..2022-23
SBR_TEAM = {'Atlanta': 'ATL', 'Boston': 'BOS', 'Brooklyn': 'BKN', 'Charlotte': 'CHA', 'Chicago': 'CHI',
            'Cleveland': 'CLE', 'Dallas': 'DAL', 'Denver': 'DEN', 'Detroit': 'DET', 'GoldenState': 'GS',
            'Houston': 'HOU', 'Indiana': 'IND', 'LAClippers': 'LAC', 'LALakers': 'LAL', 'Memphis': 'MEM',
            'Miami': 'MIA', 'Milwaukee': 'MIL', 'Minnesota': 'MIN', 'NewOrleans': 'NO', 'NewYork': 'NY',
            'OklahomaCity': 'OKC', 'Orlando': 'ORL', 'Philadelphia': 'PHI', 'Phoenix': 'PHX', 'Portland': 'POR',
            'Sacramento': 'SAC', 'SanAntonio': 'SA', 'Toronto': 'TOR', 'Utah': 'UTAH', 'Washington': 'WSH'}


def _f(s):
    s = s.strip().lower()
    if s in ('pk', "pk'"):
        return 0.0
    try:
        return float(s.replace('½', '.5'))
    except ValueError:
        return None


def home_line(v, h):
    """the home side's expected margin from the two rows' numbers (the spread sits on the favorite's row, the total
    on the other)"""
    if v is None or h is None:
        return None
    if v < 100 <= h or (v < 60 and h is not None and h >= 60):
        return -v                                     # visitor favored by v
    if h < 100 <= v or (h < 60 and v >= 60):
        return h
    return None


def write_sbr():
    out = []
    for S in range(2020, 2024):
        u = f'https://www.sportsbookreviewsonline.com/scoresoddsarchives/nba-odds-{S - 1}-{str(S)[2:]}/'
        req = urllib.request.Request(u, headers={'User-Agent': E.UA})
        t = urllib.request.urlopen(req, timeout=60).read().decode('utf-8', 'replace')
        rows = []
        for r in re.findall(r'<tr[^>]*>(.*?)</tr>', t, re.S):
            c = [html.unescape(re.sub(r'<[^>]+>', '', x)).strip() for x in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', r, re.S)]
            if len(c) >= 12 and c[0].isdigit():
                rows.append(c)
        for v, h in zip(rows[0::2], rows[1::2]):
            if v[2] not in ('V', 'N') or h[2] not in ('H', 'N') or v[3] not in SBR_TEAM or h[3] not in SBR_TEAM:
                continue
            md = int(v[0])
            out.append({'S': S, 'md': md, 'a': SBR_TEAM[v[3]], 'h': SBR_TEAM[h[3]], 'as': int(v[8]), 'hs': int(h[8]),
                        'Lo': home_line(_f(v[9]), _f(h[9])), 'L': home_line(_f(v[10]), _f(h[10]))})
        print(S, sum(1 for x in out if x['S'] == S), 'games', flush=True)
    E.save(SBR, out)


def sbr_lines(games):
    """{game id: (open, close)} for 2019-20..2022-23, matched on teams, final score and date within two days"""
    if not os.path.exists(SBR):
        return {}
    idx = defaultdict(list)
    for x in json.load(open(SBR)):
        idx[(x['S'], x['h'], x['a'], x['hs'], x['as'])].append(x)
    out = {}
    for g in games:
        for x in idx.get((g['S'], g['h'], g['a'], g['hs'], g['as']), []):
            d = dt.datetime.fromisoformat(g['tip'].replace('Z', '+00:00')).astimezone(ET).date()
            if d.month * 100 + d.day == x['md'] or abs(d.month * 100 + d.day - x['md']) <= 2:
                out[g['id']] = (x['Lo'], x['L'])
    return out


# ---------------------------------------------------------------- the official injury reports
TEAM_NAME = {'Atlanta Hawks': 'ATL', 'Boston Celtics': 'BOS', 'Brooklyn Nets': 'BKN', 'Charlotte Hornets': 'CHA',
             'Chicago Bulls': 'CHI', 'Cleveland Cavaliers': 'CLE', 'Dallas Mavericks': 'DAL', 'Denver Nuggets': 'DEN',
             'Detroit Pistons': 'DET', 'Golden State Warriors': 'GS', 'Houston Rockets': 'HOU', 'Indiana Pacers': 'IND',
             'LA Clippers': 'LAC', 'Los Angeles Clippers': 'LAC', 'Los Angeles Lakers': 'LAL', 'Memphis Grizzlies': 'MEM',
             'Miami Heat': 'MIA', 'Milwaukee Bucks': 'MIL', 'Minnesota Timberwolves': 'MIN', 'New Orleans Pelicans': 'NO',
             'New York Knicks': 'NY', 'Oklahoma City Thunder': 'OKC', 'Orlando Magic': 'ORL', 'Philadelphia 76ers': 'PHI',
             'Phoenix Suns': 'PHX', 'Portland Trail Blazers': 'POR', 'Sacramento Kings': 'SAC', 'San Antonio Spurs': 'SA',
             'Toronto Raptors': 'TOR', 'Utah Jazz': 'UTAH', 'Washington Wizards': 'WSH'}
TEAM_RE = re.compile('|'.join(sorted(map(re.escape, TEAM_NAME), key=len, reverse=True)))
STATUS = ('Out', 'Doubtful', 'Questionable', 'Probable', 'Available')
LINE = re.compile(r'([A-Z][^,\d]{1,40}?, [^\s].{0,40}?)\s{2,}(' + '|'.join(STATUS) + r')\b')
MATCH = re.compile(r'\b([A-Z]{2,3})@([A-Z]{2,3})\b')
DATE = re.compile(r'^\s*(\d\d)/(\d\d)/(\d{4})\b')


def fetch(d, hour):
    """the report's text for date d at hour (ET, 24h), '' when none was posted then. Three spellings over the years:
    05PM (stamped 5:30), 05_00PM (2025-26, quarter-hourly) and 05_30PM."""
    os.makedirs(REP_CACHE, exist_ok=True)
    fn = os.path.join(REP_CACHE, f'{d}_{hour:02d}.txt')
    if os.path.exists(fn):
        return open(fn).read()
    h12 = hour - 12 if hour > 12 else hour
    ap = 'PM' if hour >= 12 else 'AM'
    txt = ''
    for t in (f'{h12:02d}{ap}', f'{h12:02d}_30{ap}', f'{h12:02d}_00{ap}'):
        got = None
        for i in range(3):
            try:
                req = urllib.request.Request(URL.format(d=d, t=t), headers={'User-Agent': E.UA})
                pdf = urllib.request.urlopen(req, timeout=30).read()
                got = subprocess.run(['pdftotext', '-layout', '-', '-'], input=pdf, capture_output=True).stdout.decode('utf-8', 'replace')
                break
            except urllib.error.HTTPError as e:
                if e.code in (403, 404):
                    got = ''
                    break
                time.sleep(2 * (i + 1))
            except Exception:
                time.sleep(2 * (i + 1))
        if got is None:
            return ''                                  # network trouble: don't cache, try again next run
        if got:
            txt = got
            break
    open(fn, 'w').write(txt)
    return txt


def parse(txt):
    """{'MM/DD/YYYY AWY@HOM': {team: {'First Last': status} or 'NYS'}} (not yet submitted = 'NYS')"""
    out, date, game, team = {}, None, None, None
    for ln in txt.splitlines():
        m = DATE.match(ln)
        if m:
            date = f'{m.group(3)}-{m.group(1)}-{m.group(2)}'
        m = MATCH.search(ln)
        if m:
            game = f'{date} {E.team(m.group(1))}@{E.team(m.group(2))}'
            team = None
        m = TEAM_RE.search(ln)
        if m and game:
            team = TEAM_NAME[m.group(0)]
        if not (game and team):
            continue
        g = out.setdefault(game, {})
        if 'NOT YET SUBMITTED' in ln:
            g[team] = 'NYS'
            continue
        for nm, st in LINE.findall(ln):
            last, first = [x.strip() for x in nm.split(',', 1)]
            last = re.split(r'\s{2,}', last)[-1]
            if g.get(team) == 'NYS' or team not in g:
                g[team] = {}
            g[team][f'{first} {last}'] = st
        g.setdefault(team, {})
    return out


def et(tip):
    return dt.datetime.fromisoformat(tip.replace('Z', '+00:00')).astimezone(ET)


def write_reports(games):
    """for every game: the report at the open and the last report before tip, as {id: {'o': {...}, 'f': {...},
    'oh': hour, 'fh': hour}}"""
    by_day = defaultdict(list)
    for g in games:
        if g['S'] in SEASONS and g.get('fin'):
            by_day[et(g['tip']).date()].append(g)
    jobs = set()
    for d, lst in by_day.items():
        jobs.add(((d - dt.timedelta(days=1)).isoformat(), 20))
        jobs.add((d.isoformat(), 13))
        for g in lst:
            t = et(g['tip']) - dt.timedelta(minutes=45)
            for h in range(min(t.hour, 23), 10, -1):
                jobs.add((d.isoformat(), h))
    jobs = sorted(jobs)
    print(len(jobs), 'report files', flush=True)
    with ThreadPoolExecutor(8) as ex:
        texts = dict(zip(jobs, ex.map(lambda j: fetch(*j), jobs)))
    parsed = {j: parse(t) for j, t in texts.items() if t}
    out = {}
    for d, lst in by_day.items():
        for g in lst:
            key = f'{d.isoformat()} {g["a"]}@{g["h"]}'
            rec = {}
            t = et(g['tip']) - dt.timedelta(minutes=45)
            for h in range(min(t.hour, 23), 10, -1):
                rep = parsed.get((d.isoformat(), h), {}).get(key)
                if rep is not None and all(rep.get(x) != 'NYS' for x in (g['h'], g['a'])):
                    rec['f'], rec['fh'] = rep, h
                    break
            for dd, h in (((d - dt.timedelta(days=1)).isoformat(), 20), (d.isoformat(), 13)):
                rep = parsed.get((dd, h), {}).get(key)
                if rep is not None and all(rep.get(x) != 'NYS' for x in (g['h'], g['a'])):
                    rec['o'], rec['oh'] = rep, (h - 24 if dd != d.isoformat() else h)
                    break
            if rec:
                out[g['id']] = rec
    print(len(out), 'games with a report;', sum(1 for r in out.values() if 'o' in r and 'f' in r), 'with both', flush=True)
    E.save(REPS, out)


# ---------------------------------------------------------------- the study
STAR = 3.0          # a player's full value (lineup points he adds over his replacement-filled absence); ~ +4.5 XPM at 32 min
ROT = 15.0          # rotation player: 15+ recent minutes a game


def lineup(m, t, pfn):
    """the model's lineup value (Model.lineup) with play chances from pfn(pid)"""
    exp = []
    for p in m.roster(t):
        mw, w = m.role[p]
        if w > 0:
            exp.append((p, mw / w * pfn(p)))
    tot = sum(e for _, e in exp)
    sc = 240.0 / tot if tot > 240 else 1.0
    V = sum(m.v(p) * e * sc for p, e in exp) / 48
    if tot < 240:
        V += G.REPL * (240 - tot) / 48
    return V


def kind(s0, s1):
    """the status change open -> final report, by the final status"""
    q = ('Questionable', 'Doubtful')
    if s1 == 'Out':
        return None if s0 == 'Out' else 'toOut'
    if s1 in q:
        return None if s0 in q else 'toQ'
    if s0 in q + ('Out',):                    # cleared: listed at the open, not (or probable/available) at the end
        return 'cleared'
    return None


def collect():
    """one row per game with open and close lines and both reports"""
    games, names = G.load_hist()
    fit = json.load(open(G.FIT))
    P, coef = fit['P'], fit['coef']
    k = coef.get('lin', 0) + coef.get('roster', 0)        # model points per lineup point of news
    reps = json.load(open(REPS))
    sbr = sbr_lines(games)
    m = G.Model(names, P, inj={}, **fit['params'])
    rows = []
    for g in games:
        x, _ = m.feats(g)
        lo, l = (g.get('Lo'), g.get('L')) if g['S'] >= 2024 else sbr.get(g['id'], (None, None))
        r = reps.get(g['id'])
        if g['S'] in SEASONS and lo is not None and l is not None and r and 'o' in r and 'f' in r and g.get('pl') \
                and all(t in g['pl'] for t in (g['h'], g['a'])):
            row = {'id': g['id'], 'S': g['S'], 'Lo': lo, 'L': l, 'y': g['hs'] - g['as'], 'oh': r['oh'], 'fh': r['fh']}
            V = {}
            players = []
            for t, sg in ((g['h'], 1), (g['a'], -1)):
                st = [{G.norm(n): v for n, v in (r[w].get(t) or {}).items()} for w in ('o', 'f')]
                played = {p for p, mn in g['pl'][t] if mn > 0}
                s0 = {p: st[0].get(G.norm(names.get(p, ''))) for p in m.roster(t)}
                s1 = {p: st[1].get(G.norm(names.get(p, ''))) for p in m.roster(t)}
                pr = lambda s: (lambda p: G.play_prob(P, s[p], m.streak[p], True))
                V[t] = (lineup(m, t, pr(s0)), lineup(m, t, pr(s1)), lineup(m, t, lambda p: 1.0 if p in played else 0.0))
                for p in m.roster(t):
                    mw, w = m.role[p]
                    R = mw / w if w else 0
                    if R < ROT:
                        continue
                    p0, p1 = pr(s0)(p), pr(s1)(p)
                    if s0[p] is None and s1[p] is None and p in played:
                        continue                       # nothing happened to him
                    full = lineup(m, t, lambda q: 1.0 if q == p else pr(s1)(q)) - lineup(m, t, lambda q: 0.0 if q == p else pr(s1)(q))
                    players.append({'sg': sg, 'F': round(full, 3), 'R': round(R, 1), 's0': s0[p], 's1': s1[p],
                                    'p0': round(p0, 3), 'p1': round(p1, 3), 'pl': int(p in played), 'st': m.streak[p]})
            h, a = g['h'], g['a']
            row['rep'] = (V[h][1] - V[h][0]) - (V[a][1] - V[a][0])
            row['late'] = (V[h][2] - V[h][1]) - (V[a][2] - V[a][1])
            # the model's margin at the open (open-report statuses), for the bad-opener screen
            lin0 = (V[h][0] - m.rate(m.base, h, 1.0)) - (V[a][0] - m.rate(m.base, a, 1.0))
            x0 = dict(x, lin=lin0, roster=V[h][0] - V[a][0])
            row['m0'] = sum(c * x0[f] for f, c in coef.items())
            row['pl'] = players
            rows.append(row)
        m.update(g)
    return rows, k, fit


def ols(X, y, names_):
    """coefficients with heteroskedasticity-robust (HC1) t-stats"""
    import numpy as np
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    e = y - X @ b
    n, kx = X.shape
    XtXi = np.linalg.pinv(X.T @ X)
    V = XtXi @ (X.T * e ** 2) @ X @ XtXi * n / max(n - kx, 1)
    se = np.sqrt(np.diag(V))
    return {nm: {'b': round(float(bb), 3), 'se': round(float(s), 3), 't': round(float(bb / s), 2) if s > 0 else None}
            for nm, bb, s in zip(names_, b, se)}


def study():
    import numpy as np
    rows, k, fit = collect()
    print(len(rows), 'games with open, close and both reports', flush=True)
    # bad openers: the open more than 3 sd from the model's margin at the open (as in the pick rules)
    gap = np.array([r['Lo'] - r['m0'] for r in rows])
    sd = float(np.std(gap))
    rows = [r for r, gp in zip(rows, gap) if abs(gp - gap.mean()) <= 3 * sd]
    print(len(rows), 'after the bad-opener screen (3 sd =', round(3 * sd, 1), 'pts)', flush=True)
    S = np.array([r['S'] for r in rows])
    M = np.array([r['L'] - r['Lo'] for r in rows])
    Y = np.array([r['y'] for r in rows], float)
    Lo = np.array([r['Lo'] for r in rows]); L = np.array([r['L'] for r in rows])

    def cells(r):
        """news by cell (signed, home minus away, lineup points): status changes open -> final report priced at
        the model's play chances, split star/role and by kind; and late news (final report -> who played)"""
        c = defaultdict(float)
        for p in r['pl']:
            tier = 'star' if p['F'] >= STAR else 'role'
            kd = kind(p['s0'], p['s1'])
            if kd:
                c[f'{kd}_{tier}'] += p['sg'] * p['F'] * (p['p1'] - p['p0'])
            c[f'late_{tier}'] += p['sg'] * p['F'] * (p['pl'] - p['p1'])
        return c
    CELLS = [f'{a}_{b}' for a in ('toOut', 'toQ', 'cleared', 'late') for b in ('star', 'role')]
    C = np.array([[cells(r).get(c, 0.0) for c in CELLS] for r in rows])
    rep = np.array([r['rep'] for r in rows]); late = np.array([r['late'] for r in rows])
    one = np.ones(len(rows))
    out = {'n': len(rows), 'k': round(k, 3), 'screen3sd': round(3 * sd, 2), 'seasons': sorted(set(int(s) for s in S)),
           'holdFrom': HOLD_FROM, 'star': STAR, 'rot': ROT}

    def block(mask):
        """market move, value (result vs open) and what the close missed (result vs close), per lineup point of
        news; a well-priced close has missed ~0"""
        X2 = np.column_stack([rep[mask], late[mask], one[mask]])
        Xc = np.column_stack([C[mask], one[mask]])
        return {'n': int(mask.sum()),
                'move': ols(X2, M[mask], ['rep', 'late', 'c']), 'value': ols(X2, (Y - Lo)[mask], ['rep', 'late', 'c']),
                'missed': ols(X2, (Y - L)[mask], ['rep', 'late', 'c']),
                'cellMove': ols(Xc, M[mask], CELLS + ['c']), 'cellMissed': ols(Xc, (Y - L)[mask], CELLS + ['c']),
                'cellValue': ols(Xc, (Y - Lo)[mask], CELLS + ['c']),
                'nCell': {c: int((np.abs(C[mask][:, i]) > 0.25).sum()) for i, c in enumerate(CELLS)}}
    out['all'] = block(S > 0)
    out['tune'] = block(S < HOLD_FROM)
    out['hold'] = block(S >= HOLD_FROM)

    # questionable at the open: what play chance did the opening line price? Regress the move to the close on the
    # Q player's full value when he played and when he sat; a = beta (1 - p), b = -beta p -> p = -b / (a - b)
    def qblock(mask, status=('Questionable',), pf=lambda p: True):
        xp, xo, oth = np.zeros(len(rows)), np.zeros(len(rows)), np.zeros(len(rows))
        npl, nq, wpl, wq = 0, 0, 0.0, 0.0
        for i, r in enumerate(rows):
            if not mask[i]:
                continue
            for p in r['pl']:
                if p['s0'] in status and pf(p):
                    if p['pl']:
                        xp[i] += p['sg'] * p['F']
                    else:
                        xo[i] += p['sg'] * p['F']
                    nq += 1; npl += p['pl']; wq += p['F']; wpl += p['F'] * p['pl']
                else:
                    oth[i] += p['sg'] * p['F'] * (p['pl'] - p['p0'])
        X = np.column_stack([xp, xo, oth, one])[mask]
        o = ols(X, M[mask], ['played', 'sat', 'other', 'c'])
        a, b = o['played']['b'], o['sat']['b']
        # delta-method se of p = -b/(a-b)
        res = {'n': nq, 'played': round(npl / max(nq, 1), 3), 'playedW': round(wpl / max(wq, 1e-9), 3), 'fit': o}
        if a - b > 0.05:
            pm = -b / (a - b)
            ga, gb = b / (a - b) ** 2, -a / (a - b) ** 2
            sa, sb = o['played']['se'], o['sat']['se']
            res.update({'pMkt': round(pm, 3), 'pSe': round(math.sqrt((ga * sa) ** 2 + (gb * sb) ** 2), 3), 'beta': round(a - b, 3)})
        return res
    allm = S > 0
    out['q'] = {'all': qblock(allm), 'tune': qblock(S < HOLD_FROM), 'hold': qblock(S >= HOLD_FROM),
                'star': None, 'model': {kk: fit['P'].get(kk) for kk in ('Questionable0', 'Questionableall', 'Doubtfulall')}}
    # stars only
    star_rows = np.array([any(p['s0'] == 'Questionable' and p['F'] >= STAR for p in r['pl']) for r in rows])
    out['q']['star'] = qblock(star_rows)
    # timing: injuries the market surely knew at the open (he missed the team's last game) vs fresh ones; and opens
    # off the day-before report vs the game-day 1:30 PM one
    out['q']['known'] = qblock(allm, pf=lambda p: p['st'] >= 1)
    out['q']['fresh'] = qblock(allm, pf=lambda p: p['st'] == 0)
    out['q']['dayBefore'] = qblock(np.array([r['oh'] < 0 for r in rows]))
    out['q']['gameDay'] = qblock(np.array([r['oh'] > 0 for r in rows]))

    # the open rule the play-rate gap suggests: bet against the side with more questionable value at the open
    # (lineup points, full value x 1), judged by the close (clvRet at -110) and by results against the open
    import clv
    out['qRule'] = []
    qv = np.array([sum(p['sg'] * p['F'] for p in r['pl'] if p['s0'] == 'Questionable') for r in rows])
    for X in (1.0, 2.0, 3.0, 4.0):
        for nm, mask in (('tune', S < HOLD_FROM), ('hold', S >= HOLD_FROM), ('all', S > 0)):
            sel = np.where(mask & (np.abs(qv) >= X))[0]
            cr, pt, ats = [], [], []
            for i in sel:
                side = 'away' if qv[i] > 0 else 'home'
                cr.append(clv.ret('nba', 'spread', side, Lo[i], -110, L[i]))
                pt.append(clv.pts('spread', side, Lo[i], L[i]))
                d = (Y[i] - Lo[i]) * (1 if side == 'home' else -1)
                if d != 0:
                    ats.append(d > 0)
            n = len(cr)
            st_ = lambda v: (round(float(np.mean(v)), 4), round(float(np.mean(v) / (np.std(v, ddof=1) / math.sqrt(len(v)))), 2)) if len(v) > 2 else (None, None)
            c_, ct = st_(cr); p_, pt_ = st_(pt)
            w = sum(ats); l_ = len(ats) - w
            out['qRule'].append({'X': X, 'set': nm, 'n': n, 'clvRet': c_, 'clvT': ct, 'clvPts': p_, 'ptsT': pt_,
                                 'beat': round(float(np.mean([x > 0 for x in pt])), 3) if n else None,
                                 'w': int(w), 'l': int(l_), 'roi': round(float((w * 100 / 110 - l_) / max(w + l_, 1)), 3)})

    # the bet: side the news favors when the close moved less than our re-price by X+ points (after the final report,
    # so the late news the market saw counts on the market's side). Graded vs the close at -110 (ATS) and by margin.
    gapN = k * rep - (M - 0)                         # our re-price of the report news minus the market's whole move
    out['rules'] = []
    for X in (1.0, 1.5, 2.0, 3.0):
        for side_name, sg in (('under-reaction', 1), ('over-reaction', -1)):
            for nm, mask in (('tune', S < HOLD_FROM), ('hold', S >= HOLD_FROM)):
                sel = mask & (sg * gapN >= X) & (np.abs(rep) * k >= X)
                d = np.sign(gapN[sel]) * sg              # +1 = home
                res = (Y[sel] - L[sel]) * d
                w = (res > 0).sum(); lo_ = (res < 0).sum()
                n = int(sel.sum())
                out['rules'].append({'X': X, 'side': side_name, 'set': nm, 'n': n, 'w': int(w), 'l': int(lo_),
                                     'ats': round(float(w / max(w + lo_, 1)), 3),
                                     'roi': round(float((w * 100 / 110 - lo_) / max(w + lo_, 1)), 3),
                                     'margin': round(float(res.mean()), 2) if n else None,
                                     't': round(float(res.mean() / (res.std(ddof=1) / math.sqrt(n))), 2) if n > 2 else None})
    # late news (after the final report: who played vs his play chance): the close moves about a third of a lineup
    # point per point and results say ~0, so fade it at the close: bet the side the late news hurt, X+ lineup points
    out['lateRule'] = []
    for X in (1.0, 1.5, 2.0, 3.0):
        for nm, mask in (('tune', S < HOLD_FROM), ('hold', S >= HOLD_FROM), ('all', S > 0)):
            sel = mask & (np.abs(late) >= X)
            d = -np.sign(late[sel])
            res = (Y[sel] - L[sel]) * d
            w = int((res > 0).sum()); lo_ = int((res < 0).sum()); n = int(sel.sum())
            out['lateRule'].append({'X': X, 'set': nm, 'n': n, 'w': w, 'l': lo_, 'ats': round(w / max(w + lo_, 1), 3),
                                    'roi': round((w * 100 / 110 - lo_) / max(w + lo_, 1), 3),
                                    'move': round(float((M[sel] * -d).mean()), 2) if n else None,
                                    'margin': round(float(res.mean()), 2) if n else None,
                                    't': round(float(res.mean() / (res.std(ddof=1) / math.sqrt(n))), 2) if n > 2 else None})
    # timing check: the open report's hour (day before vs game day)
    out['openHour'] = {str(h): int(sum(1 for r in rows if r['oh'] == h)) for h in sorted(set(r['oh'] for r in rows))}
    out['newsShare'] = round(float(np.mean(np.abs(rep) * k >= 1.0)), 3)
    out['moveSd'] = round(float(np.std(M)), 2)
    out['updated'] = dt.date.today().isoformat()
    # the site's table: per lineup point of news, the close's move, the result's (vs the open) and what the close
    # missed (result vs the close); t of the miss pooled and on the held-out seasons
    rowdef = [('all report news', 'two', 'rep'), ('star out', 'cell', 'toOut_star'), ('role out', 'cell', 'toOut_role'),
              ('star cleared', 'cell', 'cleared_star'), ('role cleared', 'cell', 'cleared_role'),
              ('late: who played', 'two', 'late')]
    tab = []
    for lab, src, key in rowdef:
        A, H = out['all'], out['hold']
        mv, vl, ms, mh = ((A['move'], A['value'], A['missed'], H['missed']) if src == 'two' else
                          (A['cellMove'], A['cellValue'], A['cellMissed'], H['cellMissed']))
        tab.append({'label': lab, 'n': A['nCell'].get(key) if src == 'cell' else (
                        int((np.abs(rep) * k >= 0.25).sum()) if key == 'rep' else int((np.abs(late) * k >= 0.25).sum())),
                    'move': mv[key]['b'], 'value': round(vl[key]['b'], 2) + 0.0, 'valueSe': vl[key]['se'], 'missed': ms[key]['b'],
                    'missedT': ms[key]['t'], 'missedTHold': mh[key]['t']})
    q = out['q']
    pick = lambda rs, **kw: [r for r in rs if all(r[a] == b for a, b in kw.items())][0]
    out['site'] = {'table': tab, 'qPlayed': q['all']['played'], 'qPlayedW': q['all']['playedW'],
                   'qModel': fit['P'].get('Questionableall'), 'qKnown': q['known'].get('pMkt'), 'qKnownPlayedW': q['known']['playedW'],
                   'qFresh': q['fresh'].get('pMkt'), 'qFreshPlayedW': q['fresh']['playedW'],
                   'qRule': pick(out['qRule'], X=3.0, set='all'), 'qRuleHold': pick(out['qRule'], X=3.0, set='hold'),
                   'lateTune': pick(out['lateRule'], X=1.0, set='tune'), 'lateHold': pick(out['lateRule'], X=1.0, set='hold'),
                   'gapTune': pick(out['rules'], X=1.0, side='under-reaction', set='tune'),
                   'gapHold': pick(out['rules'], X=1.0, side='under-reaction', set='hold')}
    with open(OUT, 'w') as f:
        json.dump(out, f, indent=1)
    print(json.dumps({kk: out[kk] for kk in ('n', 'k', 'newsShare', 'moveSd')}))
    for nm in ('tune', 'hold'):
        b = out[nm]
        print(nm, 'move', b['move'], '\n   value', b['value'], '\n   missed', b['missed'])
        print('   cells move  ', {c: (v['b'], v['t']) for c, v in b['cellMove'].items()})
        print('   cells value ', {c: (v['b'], v['t']) for c, v in b['cellValue'].items()})
        print('   cells missed', {c: (v['b'], v['t']) for c, v in b['cellMissed'].items()})
        print('   n', b['nCell'])
    print('Q', json.dumps(out['q']))
    for r in out['rules']:
        print(r)
    for kk in ('known', 'fresh', 'dayBefore', 'gameDay', 'star'):
        q = out['q'][kk]
        print('Q', kk, q['n'], 'played', q['played'], q['playedW'], 'pMkt', q.get('pMkt'), q.get('pSe'), 'beta', q.get('beta'))
    for r in out['qRule']:
        print(r)
    for r in out['lateRule']:
        print(r)


if __name__ == '__main__':
    a = sys.argv[1:]
    if a and a[0] == '--sbr':
        write_sbr()
    elif a and a[0] == '--reports':
        write_reports(G.load_hist()[0])
    else:
        study()
