# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NHL award races added Nov 23 2026 (Selke, Lady Byng, All-Star teams, Ted Lindsay, Jack Adams) and the Hockey-Reference
skater lines the driver tests read. Pools and features for scripts/research/awards_nov23/nhl/run.py and scripts/awards.py.
Pre-registration: scripts/research/awards_nov23/nhl/prereg.md.

History: Hockey-Reference award voting (selke_stats, byng_stats, AS_stats on voting-<S>.html), skater lines
(NHL_<S>_skaters.html: +/-, PIM, faceoffs, takeaways), standings; Ted Lindsay and Jack Adams winners from Wikipedia;
head coaches from records.nhl.com (scripts/nhl_breakout.py coach_stints). Stdlib."""
import collections, json, gzip, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import names as NM
import awards_nhl as A
from awards_nba import fetch, table, f, ROOT

PRE0 = 2006                                   # voting pages read for prior-award counts before the first modelled season
AS_K = {'F': 6, 'D': 4, 'G': 2}
SELKE_COLS = ['gd', 'war', 'pts', 'pm', 'fo', 'tk', 'tpct', 'prev_selke']
SELKE_NULL = ['gd']
BYNG_COLS = ['pimpg', 'pts', 'war', 'gfrac', 'tpct', 'dman', 'prev_byng']
BYNG_NULL = ['war']
AS_COLS = ['war', 'pts', 'g', 'gsax', 'tpct', 'gfrac', 'prev_allstar']
AS_NULL = ['war']
LINDSAY_COLS = ['war', 'pts', 'g', 'tpct', 'gfrac', 'goalie', 'prev_lindsay']
LINDSAY_NULL = ['war']
ADAMS_COLS = ['tpct', 'dexp', 'gdpg', 'prev_adams']
ADAMS_NULL = ['tpct']


def hr_page(S):
    return fetch(f'nhl_awards_{S}.html', f'https://www.hockey-reference.com/awards/voting-{S}.html')


def vote_list(S, tid):
    """[(player, team, votes)] by votes, Hockey-Reference table tid"""
    rows = [(r.get('player', ''), A.HR_TM.get(r.get('_tm', ''), r.get('_tm', '')), f(r.get('votes')))
            for r in table(hr_page(S), tid) if r.get('player') and r.get('player') != 'Player']
    return sorted([r for r in rows if r[2] > 0], key=lambda t: -t[2])


def allstar_named(S):
    """{group: [(player, team)] named, first team first}: C/LW/RW top two into F (6), D top four (4), G top two (2)"""
    by = collections.defaultdict(list)
    for r in table(hr_page(S), 'AS_stats'):
        p, v = r.get('pos'), f(r.get('votes'))
        if r.get('player') and p in ('C', 'LW', 'RW', 'D', 'G') and v > 0:
            by[p].append((v, r['player'], A.HR_TM.get(r.get('_tm', ''), r.get('_tm', ''))))
    for p in by: by[p].sort(key=lambda t: -t[0])
    out = {}
    for g, ps, n in (('F', ('C', 'LW', 'RW'), 1), ('D', ('D',), 2), ('G', ('G',), 1)):
        first = sorted([x for p in ps for x in by[p][:n]], key=lambda t: -t[0])
        second = sorted([x for p in ps for x in by[p][n:2 * n]], key=lambda t: -t[0])
        seen, o = set(), []
        for _, nm, tm in first + second:
            if nm not in seen: seen.add(nm); o.append((nm, tm))
        out[g] = o
    return out


def wiki_winners(page):
    """{season end year: (winner, team)} from the award's Wikipedia winners table"""
    import awards_football as F
    h = F.wiki(page)
    out = {}
    for t in re.findall(r'<table class="wikitable.*?</table>', h, re.S):
        rows = [F.cells(tr) for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', t, re.S)]
        if not rows or rows[0][:2] != ['Season', 'Winner']: continue
        for r in rows[1:]:
            m = re.match(r'(\d{4})[–-](\d{2})', r[0])
            if not m or len(r) < 3: continue
            nm = re.sub(r'\s*[\^†*‡]+.*$', '', re.sub(r'\[.*?\]', '', r[1])).strip()
            out[int(m.group(1)) + 1] = (nm, r[2])
    return out


def standings_full(S):
    """{team: {'tpct', 'gf', 'ga', 'gp', 'name'}} from the season page"""
    h = fetch(f'nhl_season_{S}.html', f'https://www.hockey-reference.com/leagues/NHL_{S}.html')
    out = {}
    for tid in ('standings_EAS', 'standings_WES', 'standings'):            # 2020-21: one divisional table
        for r in table(h, tid):
            t = r.get('_tm')
            if t and r.get('points_pct'):
                out[A.HR_TM.get(t, t)] = {'tpct': f(r['points_pct']), 'gf': f(r.get('goals')), 'ga': f(r.get('opp_goals')),
                                          'gp': f(r.get('games')), 'name': r.get('team_name', '').rstrip('*').strip()}
    return out


def hr_skaters(S):
    """one line a Hockey-Reference id: the season total (first row), team = his last club"""
    h = fetch(f'nhl_skaters_{S}.html', f'https://www.hockey-reference.com/leagues/NHL_{S}_skaters.html')
    out = {}
    for r in table(h, 'player_stats'):
        i = r.get('_id')
        if not i: continue
        tm = r.get('_tm') or r.get('team_name_abbr')
        if i in out:
            if r.get('_tm'): out[i]['tm'] = A.HR_TM.get(r['_tm'], r['_tm'])
            continue
        gp = f(r.get('games'))
        fw, fl = f(r.get('faceoff_wins')), f(r.get('faceoff_losses'))
        out[i] = {'n': r.get('name_display') or r.get('player'), 'tm': A.HR_TM.get(tm, tm), 'pos': r.get('pos'), 'gp': gp,
                  'pm': f(r.get('plus_minus')), 'pim': f(r.get('pen_min')), 'fow': fw, 'fol': fl,
                  'tk': f(r.get('takeaways')), 'blk': f(r.get('blocks')), 'hits': f(r.get('hits'))}
    return list(out.values())


def attach_hr(pool, S):
    """+/-, PIM a game, faceoffs, takeaways on each pool row (0 where the line is not found)"""
    hr = hr_skaters(S)
    m = NM.Matcher(hr, name='n', team='tm', pos=None, sport='hockey')
    miss = 0
    for r in pool:
        if '_hr' in r: continue
        x = None
        if r['grp'] != 'G':
            x, _ = m.find(r['n'], team=r['tm'].split('/')[-1])
            if x is None: x, _ = m.find(r['n'])
            if x is None: miss += 1
        x = x or {}
        gp = max(r['gp'], 1)
        fo_n = x.get('fow', 0) + x.get('fol', 0)
        r['_hr'] = bool(x)
        r['pm'] = x.get('pm', 0.0)
        r['pimpg'] = x.get('pim', 0.0) / gp
        r['fo'] = ((x['fow'] / fo_n - .5) if fo_n >= 5 * gp else 0.0) if x else 0.0
        r['tk'] = x.get('tk', 0.0) / gp
        r['dman'] = 1.0 if r['grp'] == 'D' else 0.0
    return miss


def order_of(pool, names_teams):
    m = NM.Matcher(pool, name='n', team=lambda r: r['tm'].split('/')[-1], pos=None, sport='hockey')
    order, miss = [], []
    for n, t in names_teams:
        row, _ = m.find(n, team=t)
        if row is None: row, _ = m.find(n)
        if row is None: miss.append(n); continue
        i = pool.index(row)
        if i not in order: order.append(i)
    return order, miss


def coach_at(CS, tm, S):
    end = {2020: '2020-03-12', 2013: '2013-04-28', 2021: '2021-05-19'}.get(S, f'{S}-04-20')
    st = [c for c in CS.get(tm, []) if c[0] <= end and c[1] >= f'{S - 1}-10-01']
    return max(st)[2] if st else None


def races():
    """{award: [(season, pool, order)]} for selke, byng, lindsay (winner), allstar ([(season, group, pool, order)]),
    adams (team pools); the pools are the Hart pool's rows (awards_nhl.seasons_data) with Hockey-Reference lines"""
    R = A.seasons_data()
    LW = wiki_winners('Ted_Lindsay_Award')
    AW = wiki_winners('Jack_Adams_Award')
    prev = collections.defaultdict(collections.Counter)
    for S in range(PRE0, A.FIRST):
        for aw, tid in (('selke', 'selke_stats'), ('byng', 'byng_stats')):
            v = vote_list(S, tid)
            if v: prev[aw][NM.key(v[0][0])] += 1
        for g, o in allstar_named(S).items():
            for n, _ in o[:AS_K[g] // 2]: prev['allstar'][NM.key(n)] += 1
    for S, (n, _) in LW.items():
        if S < A.FIRST: prev['lindsay'][NM.key(n)] += 1
    for S, (n, _) in AW.items():
        if S < A.FIRST: prev['adams'][NM.key(n)] += 1
    out = {a: [] for a in ('selke', 'byng', 'lindsay', 'allstar', 'adams')}
    import nhl_breakout as B
    CS = B.coach_stints()
    for S, pool, _ in R['hart']:
        miss = attach_hr(pool, S)
        if miss > 40: print('nhl', S, 'skaters without a Hockey-Reference line', miss)
        for r in pool:
            k = NM.key(r['n'])
            for a in ('selke', 'byng', 'allstar', 'lindsay'): r['prev_' + a] = prev[a][k]
        # Selke: forwards 40+ GP; Byng: skaters 40+ GP (2013 and 2021: shortened seasons, 60% of the games)
        ng = max(r['gp'] for r in pool)
        g40 = 40 if ng >= 70 else round(.5 * ng)
        sp = [r for r in pool if r['grp'] == 'F' and r['gp'] >= g40]
        bp = [r for r in pool if r['grp'] != 'G' and r['gp'] >= g40]
        for aw, P, tid in (('selke', sp, 'selke_stats'), ('byng', bp, 'byng_stats')):
            v = vote_list(S, tid)
            o, mi = order_of(P, [(n, t) for n, t, _ in v])
            if any(n in mi for n, _, _ in v[:3]): print('nhl', S, aw, 'top-3 vote-getter outside pool', mi[:3])
            out[aw].append((S, P, o))
            if v: prev[aw][NM.key(v[0][0])] += 1
        named = allstar_named(S)
        for g in ('F', 'D', 'G'):
            P = [r for r in pool if r['grp'] == g and r['gp'] >= (g40 if g != 'G' else round(.3 * ng))]
            o, mi = order_of(P, named.get(g, []))
            if mi: print('nhl', S, 'allstar', g, 'named outside pool', mi)
            out['allstar'].append((S, g, P, o[:AS_K[g]]))
            for n, _ in named.get(g, [])[:AS_K[g] // 2]: prev['allstar'][NM.key(n)] += 1
        if S in LW:
            o, mi = order_of(pool, [LW[S]])
            if mi: print('nhl', S, 'lindsay winner outside pool', mi)
            out['lindsay'].append((S, pool, o[:1]))
            prev['lindsay'][NM.key(LW[S][0])] += 1
        # Jack Adams: one row a team
        st, st0 = standings_full(S), standings_full(S - 1)
        tp = []
        for t, x in st.items():
            c = coach_at(CS, t, S)
            p0 = (st0.get(t) or {}).get('tpct', .5)
            tp.append({'id': t, 'n': c or t, 'tm': t, 'tpct': x['tpct'], 'tpct0': p0, 'dexp': x['tpct'] - p0,
                       'gdpg': (x['gf'] - x['ga']) / max(x['gp'], 1), 'prev_adams': prev['adams'][NM.key(c)] if c else 0})
        o = []
        if S in AW:
            wn, wt = AW[S]
            hit = [i for i, r in enumerate(tp) if st[r['tm']]['name'] == wt] or [i for i, r in enumerate(tp) if NM.same(r['n'], wn)]
            if hit: o = hit[:1]
            else: print('nhl', S, 'adams winner team not found', AW[S])
            prev['adams'][NM.key(wn)] += 1
        out['adams'].append((S, tp, o))
    return out, {a: dict(v) for a, v in prev.items()}
