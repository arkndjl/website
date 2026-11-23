# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Football award races added Nov 23 2026 (pre-registered in scripts/research/awards_nov23/{nfl,cfb}/prereg.md), same
engine and gate as scripts/awards_research.py / awards_more.py: held-out log P(winner) against the null, Holm at .05
over the sport's whole list in data/awards_fit.json, gain > 0 and most seasons won. Passing races are merged into
data/awards_fit.json; failing ones are written too (pass false) so the conviction view can name them.

    python3 scripts/awards_football_more.py nfl           # CPOY, COY, All-Pro, DPOY v2 + the NFL add-on driver tests
    python3 scripts/awards_football_more.py cfb           # Unitas, Hornung, Lombardi, the v2 retries + CFB add-ons
    python3 scripts/awards_football_more.py nfl --dry     # print, write only the research results

Extra history (all free, cached in scripts/.cache/awards): nflverse games (records, coaches, points allowed) and players
(ESPN id -> draft pick), preseason win totals (sportsoddshistory), AP All-Pro first teams (Wikipedia), ESPN AP polls and
conferences by team-season, the CFB board's season-end grades (scripts/data/cfb_alltime_rows.json.gz). numpy."""
import collections, concurrent.futures as cf, gzip, html, json, math, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import awards_engine as E
import awards_football as F
import names as NM
from awards_research import t_sf, holm, summarise, OUT, L2

ROOT = F.ROOT
RES = os.path.join(ROOT, 'scripts', 'research', 'awards_nov23')
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'awards')
SEASONS = range(2005, 2026)
LIVE = {}                # the live race's prior-season inputs, written to the fit's _prev (scripts/awards.py)


# ---------------------------------------------------------------- shared test

def test(races, cols, null, depth=1, k=None):
    """the awards_more.py test: LOSO voter model vs null; races [(season, pool rows, order)]"""
    S = [s for s, _, _ in races]
    rr = lambda cs: [([[r[c] for c in cs] for r in p], o) for _, p, o in races]
    if k:
        full, base = E.loso_k(rr(cols), S, k, l2=L2), E.loso_k(rr(null), S, k, l2=L2)
    else:
        full, base = E.loso(rr(cols), S, l2=L2, depth=depth), E.loso(rr(null), S, l2=L2, depth=depth)
    pr = E.paired(full, base)
    b, mu, sd = E.fit([x for x in rr(cols) if x[1]], l2=L2, depth=k or depth)
    used = [s for (s, _, o) in races if o]
    return {'cols': cols, 'null': null, 'depth': k or depth, 'b': [round(v, 5) for v in b], 'mu': [round(v, 5) for v in mu],
            'sd': [round(v, 5) for v in sd], 'seasons': [min(used), max(used)],
            'test': {'model': summarise(full), 'null': summarise(base), 'gain': pr['gain'], 't': pr['t'],
                     'p': round(t_sf(pr['t'], pr['n'] - 1), 4), 'wins': pr['wins'],
                     'by': [{'s': x['season'], 'pw': round(x['pw'], 3), 'pw0': round(y['pw'], 3), 'hit': x['hit']}
                            for x, y in zip(full, base)]}}, full, base


def addon(races, base_cols, extra, depth=1):
    """a driver as an add-on: held-out log P(winner) of base + extra vs base, same seasons"""
    S = [s for s, _, _ in races]
    rr = lambda cs: [([[r[c] for c in cs] for r in p], o) for _, p, o in races]
    a = E.loso(rr(base_cols + extra), S, l2=L2, depth=depth)
    b = E.loso(rr(base_cols), S, l2=L2, depth=depth)
    pr = E.paired(a, b)
    bb, _, _ = E.fit([x for x in rr(base_cols + extra) if x[1]], l2=L2, depth=depth)
    return {'base': base_cols, 'add': extra, 'n': pr['n'], 'gain': pr['gain'], 't': pr['t'], 'wins': pr['wins'],
            'p': round(t_sf(pr['t'], pr['n'] - 1), 4), 'hit': sum(x['hit'] for x in a), 'hit0': sum(x['hit'] for x in b),
            'll': round(sum(x['ll'] for x in a) / max(len(a), 1), 3), 'll0': round(sum(x['ll'] for x in b) / max(len(b), 1), 3),
            'coef_add': [round(v, 3) for v in bb[len(base_cols):]]}


def gate(cur, sport, new, extra_p=()):
    """Holm over the sport's races in the fit file (not replaced here), extra p-values (earlier failed tries that stay
    in the family) and the new ones; sets test.pass and holm_n on the new"""
    old = [(a, v['test']['p']) for a, v in cur.get(sport, {}).items() if a != '_prev' and a not in new and 'test' in v]
    keys = [a for a, _ in old] + [f'_x{i}' for i in range(len(extra_p))] + list(new)
    ok = holm([p for _, p in old] + list(extra_p) + [new[a]['test']['p'] for a in new])
    for a, k in zip(keys, ok):
        if a not in new: continue
        t = new[a]['test']
        t['pass'] = bool(k and t['gain'] > 0 and t['wins'] * 2 > t['model']['n'])
        t['holm_n'] = len(keys)
        print(f"{sport} {new[a]['label']:12s} held-out {t['model']['ll']:.3f} vs null {t['null']['ll']:.3f} gain {t['gain']:+.3f} "
              f"t {t['t']} p {t['p']} wins {t['wins']}/{t['model']['n']} hit {t['model']['hit']} vs {t['null']['hit']} "
              f"(Holm over {len(keys)})  {'PASS' if t['pass'] else 'fail'}", flush=True)


def holm_addons(tests):
    ok = holm([t['p'] for t in tests])
    for t, k in zip(tests, ok):
        t['pass'] = bool(k and t['gain'] > 0 and t['wins'] * 2 > t['n'])
        t['holm_n'] = len(tests)
        print(f"  add-on {t['award']:9s} + {','.join(t['add']):14s} gain {t['gain']:+.4f} t {t['t']} p {t['p']} wins {t['wins']}/{t['n']} "
              f"hit {t['hit']} vs {t['hit0']} coef {t['coef_add']}  {'PASS' if t['pass'] else 'fail'}", flush=True)


def order(pool, names):
    o = F._order(pool, names)
    return [x for x in o if x is not None] if o and o[0] is not None else []


# ---------------------------------------------------------------- NFL extras

ABBR = {'Arizona Cardinals': 'ARI', 'Atlanta Falcons': 'ATL', 'Baltimore Ravens': 'BAL', 'Buffalo Bills': 'BUF',
        'Carolina Panthers': 'CAR', 'Chicago Bears': 'CHI', 'Cincinnati Bengals': 'CIN', 'Cleveland Browns': 'CLE',
        'Dallas Cowboys': 'DAL', 'Denver Broncos': 'DEN', 'Detroit Lions': 'DET', 'Green Bay Packers': 'GB',
        'Houston Texans': 'HOU', 'Indianapolis Colts': 'IND', 'Jacksonville Jaguars': 'JAX', 'Kansas City Chiefs': 'KC',
        'Las Vegas Raiders': 'LV', 'Oakland Raiders': 'LV', 'Los Angeles Chargers': 'LAC', 'San Diego Chargers': 'LAC',
        'Los Angeles Rams': 'LA', 'St. Louis Rams': 'LA', 'St Louis Rams': 'LA', 'Miami Dolphins': 'MIA', 'Minnesota Vikings': 'MIN',
        'New England Patriots': 'NE', 'New Orleans Saints': 'NO', 'New York Giants': 'NYG', 'New York Jets': 'NYJ',
        'Philadelphia Eagles': 'PHI', 'Pittsburgh Steelers': 'PIT', 'San Francisco 49ers': 'SF', 'Seattle Seahawks': 'SEA',
        'Tampa Bay Buccaneers': 'TB', 'Tennessee Titans': 'TEN', 'Washington Commanders': 'WAS', 'Washington Redskins': 'WAS',
        'Washington Football Team': 'WAS', 'Washington': 'WAS'}
AFC = {'BAL', 'BUF', 'CIN', 'CLE', 'DEN', 'HOU', 'IND', 'JAX', 'KC', 'LV', 'LAC', 'MIA', 'NE', 'NYJ', 'PIT', 'TEN'}
ESPN_ABBR = {'WSH': 'WAS', 'LAR': 'LA', 'OAK': 'LV', 'SD': 'LAC', 'STL': 'LA'}


def win_totals():
    """{season: {nflverse abbr: preseason win total}} from the cached sportsoddshistory pages (fetched by hand with
    curl, 2 s apart: scripts/.cache/awards/wintot/w<year>.html)"""
    out = {}
    for S in range(2004, 2027):
        p = os.path.join(CACHE, 'wintot', f'w{S}.html')
        if not os.path.exists(p): continue
        h = open(p, encoding='utf-8', errors='replace').read()
        for t in re.findall(r'<table.*?</table>', h, re.S)[:1]:
            for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', t, re.S)[1:]:
                c = F.cells(tr)
                if len(c) >= 2 and c[0] in ABBR:
                    try: out.setdefault(S, {})[ABBR[c[0]]] = float(c[1])
                    except ValueError: pass
    return out


def nfl_teams():
    """{season: {abbr: {'w', 'pa', 'drank', 'coach', 'first', 'bye'}}} from nflverse games (regular season)"""
    import awards_nflverse as V
    G = V.nfl_file('games.csv', 'https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv')
    T = collections.defaultdict(lambda: collections.defaultdict(lambda: {'w': 0.0, 'g': 0, 'pa': 0, 'co': collections.Counter()}))
    for g in G:
        if g['game_type'] != 'REG' or not g['home_score'] or g['home_score'] == 'NA': continue
        S = int(g['season'])
        hs, as_ = int(g['home_score']), int(g['away_score'])
        for tm, me, op, co in ((g['home_team'], hs, as_, g['home_coach']), (g['away_team'], as_, hs, g['away_coach'])):
            tm = V.TEAM_FIX.get(tm, tm)
            x = T[S][tm]
            x['w'] += 1 if me > op else .5 if me == op else 0
            x['g'] += 1; x['pa'] += op; x['co'][co] += 1
    out = {}
    for S, d in T.items():
        ranks = {t: i + 1 for i, t in enumerate(sorted(d, key=lambda t: d[t]['pa'] / max(d[t]['g'], 1)))}
        out[S] = {}
        for conf in (AFC, set(d) - AFC):
            top = sorted([t for t in d if t in conf], key=lambda t: -d[t]['w'])[:2]
            for t in d:
                if t in conf:
                    out[S][t] = {'w': d[t]['w'], 'pa': d[t]['pa'], 'drank': 33 - ranks[t], 'coach': d[t]['co'].most_common(1)[0][0],
                                 'bye': 1.0 if t in top else 0.0}
    for S in out:
        for t, x in out[S].items():
            x['first'] = 0.0 if (out.get(S - 1, {}).get(t, {}).get('coach') == x['coach']) else 1.0
            x['wprev'] = out.get(S - 1, {}).get(t, {}).get('w')
    return out


def espn_abbr():
    """{ESPN team id: nflverse abbr}"""
    d = F.get('https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams', 'nfl/teams.json')
    out = {}
    for t in d['sports'][0]['leagues'][0]['teams']:
        a = t['team']['abbreviation']
        out[t['team']['id']] = ESPN_ABBR.get(a, a)
    return out


def allpro_hist():
    """{season: {group: [names]}} 2000-25 and {season: {name key: first-team count before that season}}"""
    A = {S: F.allpro(S) for S in range(2000, 2026)}
    fix = {}
    for S in range(2000, 2026):
        if not any(A[S].get(g) for g in ('IDL',)) and A[S]:
            print('allpro', S, 'no interior line parsed', list(A[S]))
        fix[S] = A[S]
    prev, run = {}, collections.Counter()
    for S in range(2000, 2027):
        prev[S] = dict(run)
        for v in fix.get(S, {}).values():
            for n in v: run[NM.key(n)] += 1
    return fix, prev


def nfl_rows():
    """{season: [feature rows]} of the NFL history pool with the Nov 23 extras"""
    P = json.load(open(F.POOL % 'nfl'))
    import awards_nflverse as V
    PL = {r['espn_id']: r for r in V.nfl_file('players.csv', V.NFLV + 'players/players.csv') if r.get('espn_id')}
    TM, WT, AB = nfl_teams(), win_totals(), espn_abbr()
    _, AP = allpro_hist()
    dp = F.nfl_winners('dpoy')
    out = {}
    for s in sorted(P, key=int):
        S = int(s)
        pd_ = collections.Counter(NM.key(n) for y, ns in dp.items() if y < S for n in ns[:1])
        rows = []
        for v in P[s].values():
            r = F.features(v)
            pv = F.features({'id': v['id'], 'n': v['n'], 'st': v.get('prev') or {}, 'pos': v.get('pos')})
            st = v.get('st') or {}
            r['prev_gp'] = float((v.get('prev') or {}).get('gene.gamesPlayed') or 0)
            r['prev_yds'] = pv['yds']
            r['prev_def'] = pv['sacks'] + pv['dint']
            r['prev_ap'] = float(AP.get(S, {}).get(NM.key(r['n']), 0))
            r['prev_dpoy'] = float(pd_.get(NM.key(r['n']), 0))
            ab = AB.get(str(r['tid']))
            tm = TM.get(S, {}).get(ab, {})
            r['ab'] = ab
            r['drank'] = float(tm.get('drank', 16))
            r['tot'] = WT.get(S, {}).get(ab, 8.5)
            pl = PL.get(str(v['id'])) or {}
            r['rookie'] = (str(pl.get('rookie_season')) == str(S)) if pl.get('rookie_season') else r['debut'] == S
            pk = int(pl['draft_pick']) if (pl.get('draft_pick') or '').isdigit() else None
            r['pick'] = -math.log(pk if pk else 260)
            rows.append(r)
        out[S] = rows
    return out, TM, WT


def nfl_main(cur, dry):
    R, TM, WT = nfl_rows()
    res = {'awards': {}, 'addons': []}
    new, extra_p = {}, []
    off = lambda rows: [r for r in rows if not r['def'] and r['yds'] >= 400]
    dfn = lambda rows: [r for r in rows if r['def'] and (r['tackles'] >= 30 or r['sacks'] >= 4 or r['dint'] >= 3)]
    # 1 CPOY
    W = F.nfl_winners('cpoy')
    races = []
    for S in SEASONS:
        pool = [r for r in off(R[S]) + dfn(R[S]) if not r['rookie']]
        o = order(pool, W.get(S, [])[:1])
        if not o: print('nfl', S, 'cpoy winner outside pool', W.get(S))
        races.append((S, pool, o[:1]))
    CP_COLS = ['yds', 'td', 'sacks', 'dint', 'wp', 'qb', 'def', 'prev_gp', 'prev_yds', 'prev_def', 'prev_ap']
    r, _, _ = test(races, CP_COLS, ['yds', 'td'])
    new['cpoy'] = dict(r, award='cpoy', label='CPOY', more=True)
    # 2 COY
    W = F.nfl_winners('coy')
    races, blocked = [], not WT
    for S in SEASONS:
        pool = [dict(t, n=t['coach'], id=a, ab=a, dtot=t['w'] - WT.get(S, {}).get(a, 8.5),
                     dprev=t['w'] - (t['wprev'] if t['wprev'] is not None else 8.5)) for a, t in TM[S].items()]
        names = [re.sub(r'[~*]', '', n).strip() for n in W.get(S, [])[:1]]
        o = order(pool, names)
        if not o: print('nfl', S, 'coy winner outside pool', names)
        races.append((S, pool, o[:1]))
    COY_COLS = ['w', 'dprev', 'first', 'bye'] + ([] if blocked else ['dtot'])
    r, _, _ = test(races, COY_COLS, ['w'])
    new['coy'] = dict(r, award='coy', label='Coach of the Year', more=True, blocked_dtot=blocked)
    res['coy_wintot_seasons'] = sorted(WT)
    # 3 All-Pro joint
    A, _ = allpro_hist()
    groups = F.AP_GROUPS
    AP_K, per = {}, {}
    for g, (f, ag, cols, null) in groups.items():
        counts = [sum(len(A.get(S, {}).get(x, [])) for x in ag) for S in SEASONS]
        k = min(c for c in counts if c) if any(counts) else 1
        races = []
        for S in SEASONS:
            pool = [r for r in R[S] if f(r)]
            names = [n for x in ag for n in A.get(S, {}).get(x, [])]
            o = [x for x in F._order(pool, names) if x is not None]
            miss = len(names) - len(o)
            if miss: print('nfl', S, 'all-pro', g, miss, 'named outside pool')
            races.append((S, pool, o[:k] if len(o) >= k else []))
        AP_K[g] = k
        r, full, base = test(races, cols, null, k=k)
        per[g] = (r, full, base)
        print(f"  all-pro {g} k{k} ll {r['test']['model']['ll']} vs {r['test']['null']['ll']} t {r['test']['t']} hit {r['test']['model']['hit']} vs {r['test']['null']['hit']}")
    byS = collections.defaultdict(lambda: [0.0, 0.0, 0, 0])
    for g, (r, full, base) in per.items():
        for x, y in zip(full, base):
            b = byS[x['season']]; b[0] += x['ll']; b[1] += y['ll']; b[2] += x['hit']; b[3] += y['hit']
    d = [b[0] - b[1] for b in byS.values()]
    n = len(d); m = sum(d) / n; v = sum((x - m) ** 2 for x in d) / (n - 1)
    tt = round(m / math.sqrt(v / n), 2)
    ap = {'award': 'allpro', 'label': 'All-Pro', 'more': True, 'k': AP_K, 'races': {g: per[g][0] for g in per},
          'seasons': [min(byS), max(byS)], 'cols': [], 'null': [],
          'test': {'model': {'n': n, 'll': round(sum(b[0] for b in byS.values()) / n, 3), 'hit': sum(b[2] for b in byS.values())},
                   'null': {'n': n, 'll': round(sum(b[1] for b in byS.values()) / n, 3), 'hit': sum(b[3] for b in byS.values())},
                   'gain': round(m, 4), 't': tt, 'p': round(t_sf(tt, n - 1), 4), 'wins': sum(x > 0 for x in d)}}
    new['allpro'] = ap
    # 4 DPOY v2
    W = F.nfl_winners('dpoy')
    races = []
    for S in SEASONS:
        pool = dfn(R[S])
        o = order(pool, W.get(S, [])[:1])
        races.append((S, pool, o[:1]))
    r, _, _ = test(races, ['sacks', 'dint', 'tfl', 'pd', 'ff', 'wp', 'qbh', 'drank', 'prev_dpoy', 'prev_ap'], ['sacks', 'dint'])
    new['dpoy2'] = dict(r, award='dpoy2', label='DPOY v2', more=True)
    extra_p = []
    gate(cur, 'nfl', new, extra_p)
    _, AP = allpro_hist()
    dpw = collections.Counter(NM.key(n) for ns in F.nfl_winners('dpoy').values() for n in ns[:1])
    LIVE.update({'allpro': AP[2026], 'dpoy_wins': dict(dpw), 'wintot': {str(S): WT[S] for S in WT if S >= 2025}})
    res['awards'] = new
    # 5-14 add-ons on the passing models (their own pools, as awards_football.nfl_races / awards_more.droy_races)
    mv = {}
    for a in ('mvp', 'opoy', 'oroy'):
        Wa = F.nfl_winners(a)
        races = []
        for S in SEASONS:
            rows = R[S]
            pool = off(rows) if a != 'oroy' else [x for x in off(rows) if x['rookie']]
            o = order(pool, Wa.get(S, [])[:1])
            races.append((S, pool, o[:1]))
        mv[a] = races
    # prev_mvp as awards_football.nfl_races builds it (MVP wins before the season)
    mvps = dict(F.PRE_MVP); Wm = F.nfl_winners('mvp')
    for S in SEASONS:
        for x in R[S]: x['prev_mvp'] = mvps.get(NM.key(x['n']), 0)
        for n in Wm.get(S, [])[:1]: mvps[NM.key(n)] = mvps.get(NM.key(n), 0) + 1
    import awards_more as AM
    import awards_nflverse as V
    PL = {r['gsis_id']: r for r in V.nfl_file('players.csv', V.NFLV + 'players/players.csv')}
    droy = AM.droy_races()
    for S, pool, _ in droy:
        for x in pool:
            pk = PL.get(x['id'], {}).get('draft_pick') or ''
            x['pick'] = -math.log(int(pk) if pk.isdigit() else 260)
            tm = V.TEAM_FIX.get(x.get('tid'), x.get('tid'))
            x['tot'] = WT.get(S, {}).get(tm, 8.5)
    base = {a: cur['nfl'][a]['cols'] for a in ('mvp', 'opoy', 'oroy', 'droy')}
    plan = [('mvp', ['prev_yds']), ('mvp', ['tot']), ('mvp', ['prev_ap']), ('opoy', ['prev_yds']), ('opoy', ['tot']),
            ('opoy', ['prev_ap']), ('oroy', ['pick']), ('oroy', ['tot']), ('droy', ['pick']), ('droy', ['tot'])]
    tests = []
    for a, ex in plan:
        races = droy if a == 'droy' else mv[a]
        tests.append(dict(addon(races, base[a], ex), award=a))
    holm_addons(tests)
    res['addons'] = tests
    res['droy_pool_note'] = 'DROY add-ons use the ESPN history pool (rookie defenders it holds), not the nflverse pool of awards_more.py'
    return new, res


# ---------------------------------------------------------------- CFB extras

P5 = {'Atlantic Coast Conference', 'Big 12 Conference', 'Big East Conference', 'Big Ten Conference', 'Pac-12 Conference',
      'Pacific-10 Conference', 'Southeastern Conference'}
CORE = 'https://sports.core.api.espn.com/v2/sports/football/leagues/college-football'


def cfb_conf(S, tid):
    """the team-season's conference name (ESPN groups, divisions walked up to their conference)"""
    d = F.get(f'{CORE}/seasons/{S}/teams/{tid}', f'cfb/conf/t{S}_{tid}.json')
    ref = ((d or {}).get('groups') or {}).get('$ref')
    name = None
    for _ in range(4):
        if not ref: return name
        m = re.search(r'types/(\d+)/groups/(\d+)', ref)
        if m.group(2) in ('80', '81'): return name                  # FBS / FCS: the step below was the conference
        g = F.get(ref.replace('http://', 'https://'), f'cfb/conf/g{S}_{m.group(1)}_{m.group(2)}.json')
        if not g: return name
        name = g.get('name')
        ref = (g.get('parent') or {}).get('$ref')
    return name


def ap_polls(S):
    """({team id: preseason AP score}, {team id: AP score after the last regular-season week}); score (26 - rank) / 25"""
    wk = F.get(f'{CORE}/seasons/{S}/types/2/weeks', f'cfb/ap/weeks{S}.json')
    last = wk.get('count') or 15
    out = []
    for w in (1, last):
        d = F.get(f'{CORE}/seasons/{S}/types/2/weeks/{w}/rankings/1', f'cfb/ap/r{S}_{w}.json')
        if not d.get('ranks') and w == last:
            d = F.get(f'{CORE}/seasons/{S}/types/2/weeks/{w - 1}/rankings/1', f'cfb/ap/r{S}_{w - 1}.json')
        sc = {}
        for x in d.get('ranks', []):
            m = re.search(r'/teams/(\d+)', x['team']['$ref'])
            if m: sc[m.group(1)] = (26 - x['current']) / 25
        out.append(sc)
    return out


def alltime_matcher():
    rows = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'data', 'cfb_alltime_rows.json.gz')))
    by = collections.defaultdict(list)
    for r in rows: by[r['s']].append(r)
    return {S: NM.Matcher(v, name='name', team='team', pos=lambda r: {'DL': 'DT'}.get(r['g'], r['g'])) for S, v in by.items()}


POS_FV = {'DE': 'EDGE', 'DT': 'DT', 'NT': 'DT', 'DL': 'DT', 'OLB': 'LB', 'ILB': 'LB', 'MLB': 'LB'}


def cfb_rows():
    P = json.load(open(F.POOL % 'cfb'))
    M = alltime_matcher()
    tnames = {}
    out = {}
    for s in sorted(P, key=int):
        S = int(s)
        tids = {v.get('tid') for v in P[s].values() if v.get('tid')}
        with cf.ThreadPoolExecutor(8) as ex:
            conf = dict(zip(tids, ex.map(lambda t: cfb_conf(S, t), tids)))
        pre, end = ap_polls(S)
        rows = []
        for v in P[s].values():
            r = F.features(v)
            st = v.get('st') or {}
            r['conf'] = conf.get(r['tid'])
            r['p5'] = 1.0 if (r['conf'] in P5 or str(r['tid']) == '87') else 0.0
            r['ap_pre'], r['ap_end'] = pre.get(str(r['tid']), 0.0), end.get(str(r['tid']), 0.0)
            r['sr'] = 1.0 if (v.get('exp') or 0) >= 4 else 0.0
            r['ret_y'] = float(st.get('retu.kickReturnYards') or 0) + float(st.get('retu.puntReturnYards') or 0)
            r['ret_td'] = float(st.get('retu.kickReturnTouchdowns') or 0) + float(st.get('retu.puntReturnTouchdowns') or 0)
            r['apy'] = r['rush_y'] + r['rec_y'] + r['ret_y']
            r['two_way'] = 1.0 if (r['rush_y'] + r['rec_y'] + r['pass_y'] >= 100 and (r['tackles'] >= 10 or r['dint'] >= 1)) else 0.0
            tm = (P[s][v['id']].get('tm') or '')
            pos = POS_FV.get(r['pos'], r['pos'])
            fv, stars = None, 0
            if S - 1 in M:
                h, _ = M[S - 1].find(r['n'], team=None, pos=pos)
                if h: fv = h['fm']
            if S in M:
                h, _ = M[S].find(r['n'], team=None, pos=pos)
                if h: stars = h.get('stars') or 0
            r['fv_pre'] = fv if fv is not None else 20.0
            r['fv_na'] = 0.0 if fv is not None else 1.0
            r['stars'] = float(stars)
            rows.append(r)
        out[S] = rows
        print('cfb rows', S, len(rows), 'fv joined', sum(1 for r in rows if not r['fv_na']), flush=True)
    return out


def heis_races(R):
    races, prev = [], set()
    for S in SEASONS:
        pool = [r for r in R[S] if r['yds'] >= 500 or r['tackles'] >= 40 or r['sacks'] >= 6 or r['dint'] >= 4]
        for r in pool: r['prev_top5'] = 1.0 if NM.key(r['n']) in prev else 0.0
        vt = F.heisman_votes(S)
        o = F._order(pool, [n for n, _, _, _ in vt])
        od = [x for x in o if x is not None]
        if o and o[0] is None: od = []
        races.append((S, pool, od))
        prev = {NM.key(n) for n, _, _, _ in vt[:5]}
    return races


def award_races(R, a, elig, big=False):
    page = F.CFB_AWARDS[a][0] if a in F.CFB_AWARDS else a
    W = F.award_winners(page)
    prev = set()
    races = []
    for S in SEASONS:
        vt = F.heisman_votes(S - 1)
        prev = {NM.key(n) for n, _, _, _ in vt[:5]}
        pool = [r for r in R[S] if elig(r)]
        if big: pool = [r for r in pool if r['yds'] >= 500 or r['tackles'] >= 40 or r['sacks'] >= 6 or r['dint'] >= 4]
        pool = [dict(r, prev_top5=1.0 if NM.key(r['n']) in prev else 0.0) for r in pool]
        w = W.get(S)
        if w is None and page == 'Paul_Hornung_Award' and S < 2010: continue
        o = order(pool, [w]) if w else []
        if w and not o: print('cfb', S, a, 'winner outside pool', w)
        races.append((S, pool, o[:1]))
    return races


DL_LB = {'DE', 'DT', 'NT', 'DL', 'LB', 'ILB', 'OLB', 'MLB', 'EDGE'}


def cfb_main(cur, dry):
    R = cfb_rows()
    new = {}
    res = {}
    # 1-3 new awards
    r, _, _ = test(award_races(R, 'Johnny_Unitas_Golden_Arm_Award', lambda r: r['pos'] == 'QB' and r['pass_y'] >= 1000 and r['sr']),
                   ['pass_y', 'ptd', 'int', 'ypa', 'rush_y', 'wp'], ['pass_y', 'ptd'])
    new['unitas'] = dict(r, award='unitas', label='Unitas', more=True)
    r, _, _ = test(award_races(R, 'Paul_Hornung_Award', lambda r: r['apy'] >= 500 or r['two_way']),
                   ['apy', 'ret_y', 'two_way', 'td', 'wp'], ['apy', 'td'])
    new['hornung'] = dict(r, award='hornung', label='Hornung', more=True)
    r, _, _ = test(award_races(R, 'Lombardi_Award', lambda r: r['def'] and r['pos'] in DL_LB),
                   ['sacks', 'dint', 'tfl', 'pd', 'tackles', 'ff', 'wp'], ['sacks', 'tfl'])
    new['lombardi'] = dict(r, award='lombardi', label='Lombardi', more=True)
    # 4-11 retries
    for a in ('doak', 'bilet', 'mackey', 'bednarik', 'nagurski', 'butkus', 'thorpe', 'groza'):
        _, lab, f, cols, null = F.CFB_AWARDS[a]
        r, _, _ = test(award_races(R, a, f), cols + ['p5', 'ap_end', 'prev_top5'], null)
        new[a + '2'] = dict(r, award=a + '2', label=lab + ' v2', more=True)
    gate(cur, 'cfb', new)
    # 12-31 add-ons
    hr = heis_races(R)
    base = {'heisman': cur['cfb']['heisman']['cols'], 'maxwell': cur['cfb']['maxwell']['cols'],
            'camp': cur['cfb']['camp']['cols'], 'obrien': cur['cfb']['obrien']['cols']}
    races = {'heisman': hr, 'maxwell': award_races(R, 'maxwell', lambda r: True, big=True),
             'camp': award_races(R, 'camp', lambda r: True, big=True),
             'obrien': award_races(R, 'obrien', F.CFB_AWARDS['obrien'][2])}
    tests = []
    for ex in (['p5'], ['ap_end'], ['ap_pre'], ['fv_pre', 'fv_na'], ['stars']):
        for a in ('heisman', 'maxwell', 'camp', 'obrien'):
            rc = races[a]
            if ex[0] in ('fv_pre', 'stars'): rc = [x for x in rc if x[0] >= 2015]
            tests.append(dict(addon(rc, base[a], ex, depth=3 if a == 'heisman' else 1), award=a))
    holm_addons(tests)
    res['addons'] = tests
    res['awards'] = new
    res['not_modelled'] = {'outland': '14 of 21 winners 2005-25 are offensive linemen (no free box stats)',
                           'rimington': 'centers: no stats', 'broyles': 'assistant coaches: no free coordinator-unit history',
                           'burlsworth': 'walk-on status not in any free structured source', 'wuerffel': 'community service award'}
    return new, res, R, races


def main(argv):
    sport = argv[0]
    dry = '--dry' in argv
    cur = json.load(open(OUT))
    os.makedirs(os.path.join(RES, sport), exist_ok=True)
    if sport == 'nfl':
        new, res = nfl_main(cur, dry)
    else:
        new, res, _, _ = cfb_main(cur, dry)
    json.dump(res, open(os.path.join(RES, sport, 'results.json'), 'w'), indent=1, sort_keys=True, default=str)
    if dry: return
    cur[sport].update(new)
    if LIVE: cur[sport].setdefault('_prev', {}).update(LIVE)
    json.dump(cur, open(OUT, 'w'), indent=1, sort_keys=True)
    print('wrote', OUT)


if __name__ == '__main__':
    main(sys.argv[1:])
