# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NBA award races (MVP, DPOY, ROY): candidate pools and features for scripts/awards_research.py and scripts/awards.py.

History: Basketball-Reference award voting, per-game stats and standings (scripts/.cache/awards/nba_*_<season>.html,
fetched by fetch()), joined by bbref id to the board's XPM files (static/data/nba-xpm/<season>.json)."""
import html, json, os, re, time, urllib.request

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'awards')
XPM = os.path.join(ROOT, 'static', 'data', 'nba-xpm')
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36'
FIRST, LAST = 2010, 2026


def fetch(fn, url, fresh=False):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, fn)
    if not fresh and os.path.exists(p) and os.path.getsize(p) > 20000:
        return open(p, encoding='utf-8', errors='replace').read()
    for a in range(4):
        try:
            h = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=60).read()
            open(p, 'wb').write(h)
            time.sleep(3.5)
            return h.decode('utf-8', 'replace')
        except Exception as e:
            print(fn, e, flush=True); time.sleep(30 * (a + 1))
    return ''


def cell(s):
    return html.unescape(re.sub(r'<[^>]+>', '', s)).strip()


def table(h, tid):
    h = h.replace('<!--', '').replace('-->', '')
    m = re.search(r'<table[^>]*id="%s".*?</table>' % re.escape(tid), h, re.S)
    if not m: return []
    out = []
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', m.group(0), re.S):
        r = {}
        for tag in re.finditer(r'<(?:td|th)([^>]*)data-stat="([^"]+)"[^>]*>(.*?)</(?:td|th)>', tr, re.S):
            attrs, k, v = tag.group(1) + tag.group(0)[:300], tag.group(2), tag.group(3)
            r[k] = cell(v)
            idm = re.search(r'data-append-csv="([^"]+)"', tag.group(0)[:400])
            if idm: r['_id'] = idm.group(1)
            hm = re.search(r'href=["\']/teams/([A-Z]{3})/', v)
            if hm: r['_tm'] = hm.group(1)
        if r: out.append(r)
    return out


def f(v, d=0.0):
    try: return float(v)
    except (TypeError, ValueError): return d


def votes(season):
    """{award: [(bbref id, share), ...] in voting order}"""
    h = fetch(f'nba_awards_{season}.html', f'https://www.basketball-reference.com/awards/awards_{season}.html')
    out = {}
    for aw in ('mvp', 'dpoy', 'roy', 'smoy', 'mip'):
        rows = [(r['_id'], f(r.get('award_share'))) for r in table(h, aw) if r.get('_id') and r.get('award_share')]
        out[aw] = sorted(rows, key=lambda t: -t[1])
    out['coy'] = sorted([(r['_tm'], f(r.get('award_share'))) for r in table(h, 'coy') if r.get('_tm') and r.get('award_share')],
                        key=lambda t: -t[1])
    return out


def standings(season):
    h = fetch(f'nba_season_{season}.html', f'https://www.basketball-reference.com/leagues/NBA_{season}.html')
    out = {}
    for tid in ('confs_standings_E', 'confs_standings_W'):
        # seasons through 2015 carry only division tables: the conference is the two (or three) divisions together
        rows = [r for r in table(h, tid) if r.get('_tm') and r.get('wins')] or \
            [r for r in table(h, tid.replace('confs', 'divs')) if r.get('_tm') and r.get('wins')]
        rows.sort(key=lambda r: -f(r.get('win_loss_pct')))       # seed = conference rank by record (a stable sort)
        for i, r in enumerate(rows):
            w, l = f(r['wins']), f(r['losses'])
            out[r['_tm']] = {'wp': w / max(w + l, 1), 'seed': i + 1, 'srs': f(r.get('srs'))}
    return out


def per_game(season, fresh=False):
    h = fetch(f'nba_pg_{season}.html', f'https://www.basketball-reference.com/leagues/NBA_{season}_per_game.html', fresh)
    out = {}
    for r in table(h, 'per_game_stats'):
        i = r.get('_id')
        if not i or i in out: continue                       # first row = season total for a traded player
        out[i] = {k: f(r.get(k)) for k in ('games', 'games_started', 'pts_per_g', 'trb_per_g', 'ast_per_g', 'stl_per_g',
                                            'blk_per_g', 'mp_per_g')}
        out[i]['tms'] = []
    for r in table(h, 'per_game_stats'):
        i, t = r.get('_id'), r.get('_tm')
        if i in out and t: out[i]['tms'].append((t, f(r.get('games'))))
    return out


def xpm(season):
    p = os.path.join(XPM, f'{season}.json')
    return {r['id']: r for r in json.load(open(p))['players']} if os.path.exists(p) else {}


# feature columns per award; every race keeps the full row (dict) so research can try subsets
MVP_COLS = ['vorx', 'xpm', 'ppg', 'wp', 'seed1', 'gfrac', 'prev_mvp']
DPOY_COLS = ['dxpm', 'stocks', 'rpg', 'big', 'wp', 'mpg', 'prev_dpoy']
ROY_COLS = ['vorx', 'xpm', 'ppg', 'mpg', 'gfrac', 'wp']


PRE_MVP = {'jamesle01': 1, 'bryanko01': 1, 'nowitdi01': 1, 'nashst01': 2, 'duncati01': 2, 'garneke01': 1}   # 2002-09
PRE_DPOY = {'howardw01': 1, 'garneke01': 1, 'cambyma01': 1, 'wallabe01': 4, 'artesro01': 1}


ROWS, VOTES, STAND, NG = {}, {}, {}, {}      # filled by seasons_data(): every row, the votes, standings a season


def seasons_data():
    """races by award: {award: [(season, rows list of dicts, order list of row indices)]}"""
    seen = set()
    prev = {'mvp': dict(PRE_MVP), 'dpoy': dict(PRE_DPOY)}
    for s in range(FIRST - 1, FIRST):
        seen |= set(xpm(s))
    races = {'mvp': [], 'dpoy': [], 'roy': []}
    for s in range(FIRST, LAST + 1):
        X, pg, st, v = xpm(s), per_game(s), standings(s), votes(s)
        n_games = max((r.get('games', 0) for r in pg.values()), default=82) or 82
        rows = []
        for pid, r in X.items():
            p = pg.get(pid)
            if not p: continue
            tms = [(t, g) for t, g in p['tms'] if t in st] or [(r['tm'], 1)]
            gt = sum(g for _, g in tms) or 1
            wp = sum(st.get(t, {'wp': .5})['wp'] * g for t, g in tms) / gt
            seed1 = max((1.0 if st.get(t, {}).get('seed') == 1 else 0.0) for t, _ in tms)
            row = {'id': pid, 'n': r['n'], 'tm': r['tm'], 'pos': r.get('pos', ''), 'g': p['games'], 'mp': r['mp'],
                   'gs': p.get('games_started', 0), 'age': r.get('age') or 0, 'sxpm': r.get('sx0', r.get('xpm', 0)) or 0,
                   'vorx': r.get('vorx', 0) or 0, 'xpm': r.get('xpm', 0) or 0, 'dxpm': r.get('dxpm', 0) or 0,
                   'ppg': p['pts_per_g'], 'rpg': p['trb_per_g'], 'apg': p['ast_per_g'],
                   'stocks': p['stl_per_g'] + p['blk_per_g'], 'mpg': p['mp_per_g'],
                   'big': 1.0 if r.get('pos', '') in ('C', 'PF') else 0.0,
                   'wp': wp, 'seed1': seed1, 'gfrac': p['games'] / n_games,
                   'prev_mvp': prev['mvp'].get(pid, 0), 'prev_dpoy': prev['dpoy'].get(pid, 0),
                   'rookie': pid not in seen}
            rows.append(row)
        ROWS[s], VOTES[s], STAND[s], NG[s] = rows, v, st, n_games
        for aw, pool_min in (('mvp', 1200), ('dpoy', 1200), ('roy', 500)):
            pool = [r for r in rows if r['mp'] >= pool_min and (aw != 'roy' or r['rookie'])]
            ids = [r['id'] for r in pool]
            order = [ids.index(i) for i, _ in v[aw] if i in ids]
            missing = [i for i, _ in v[aw][:3] if i not in ids]
            if missing: print('nba', s, aw, 'vote-getters outside pool', missing)
            if aw == 'roy' and s < FIRST + 2: continue           # rookie flag needs two seasons of history
            races[aw].append((s, pool, order))
        for aw in ('mvp', 'dpoy'):
            if v[aw]: prev[aw][v[aw][0][0]] = prev[aw].get(v[aw][0][0], 0) + 1
        seen |= set(X)
    return races


# ---------------------------------------------------------------- races added Nov 23 2026 (scripts/awards_bball.py)
SMOY_COLS = ['vorx', 'xpm', 'ppg', 'mpg', 'wp', 'gfrac']
MIP_COLS = ['d_vorx', 'd_ppg', 'vorx', 'ppg', 'd_mpg', 'wp', 'gfrac']
ALLDEF_COLS = ['dxpm', 'stocks', 'rpg', 'big', 'wp', 'mpg', 'gfrac', 'prev_alldef']
ALLROOK_COLS = ['vorx', 'xpm', 'ppg', 'mpg', 'gfrac', 'wp']
COY_COLS = ['wp', 'd_wp', 'ovr', 'seed1']
ALLDEF_K = ALLROOK_K = 10


def named(season, tid, col):
    """bbref ids named to an all-league team (All-Defensive, All-Rookie): first team first, by voting points inside"""
    h = fetch(f'nba_awards_{season}.html', f'https://www.basketball-reference.com/awards/awards_{season}.html')
    rows = [(int((r.get(col) or '9')[0]), -f(r.get('points_won')), r['_id'])
            for r in table(h, tid) if r.get('_id') and (r.get(col) or '')[:1] in '12' and r.get(col)]
    return [i for _, _, i in sorted(rows)]


def preseason_ou(season):
    """{team: preseason over/under wins} from Basketball-Reference's preseason odds page (set before opening night)"""
    h = fetch(f'nba_odds_{season}.html', f'https://www.basketball-reference.com/leagues/NBA_{season}_preseason_odds.html')
    out = {}
    for r in table(h, 'NBA_preseason_odds'):
        t = r.get('_tm')
        ou = re.match(r'\s*([\d.]+)', r.get('over_under') or r.get('wins_ou') or '')
        if t and ou: out[t] = float(ou.group(1))
    return out


def coaches(season):
    """{team: head coach now} (Basketball-Reference's coaches page; the last listed for a team that changed)"""
    h = fetch(f'nba_coaches_{season}.html', f'https://www.basketball-reference.com/leagues/NBA_{season}_coaches.html',
              fresh=True)
    out = {}
    for r in table(h, 'NBA_coaches'):
        if r.get('_tm') and r.get('coach'): out[r['_tm']] = r['coach']
    return out


def _order(pool, ids):
    at = {r['id']: i for i, r in enumerate(pool)}
    return [at[i] for i in ids if i in at]


def annotate(s, rows):
    """last season's line on each row (the driver tests' preseason terms and MIP's baseline): pre_vorx, pre_sxpm,
    pre_dxpm from last season's published XPM file, d_vorx / d_ppg / d_mpg, last season's vote shares"""
    last = xpm(s - 1)
    pg0 = per_game(s - 1)
    sh0 = VOTES.get(s - 1) or votes(s - 1)
    for r in rows:
        q, p0 = last.get(r['id']), pg0.get(r['id'])
        r['has_pre'] = q is not None and p0 is not None
        r['pre_vorx'] = (q or {}).get('vorx', 0) or 0
        r['pre_sxpm'] = (q.get('sx0', q.get('xpm', -2)) or 0) if q else -2.0
        r['pre_dxpm'] = (q or {}).get('dxpm', 0) or 0
        r['d_vorx'] = r['vorx'] - r['pre_vorx']
        r['d_ppg'] = r['ppg'] - (p0 or {}).get('pts_per_g', 0)
        r['d_mpg'] = r['mpg'] - (p0 or {}).get('mp_per_g', 0)
        for aw in ('mvp', 'dpoy', 'smoy'):
            r['prev_share_' + aw] = dict(sh0.get(aw, [])).get(r['id'], 0.0)


def more_races():
    """{award: [(season, pool rows, order)]} for smoy, mip, alldef, allrookie, coy, plus prev counts for alldef. Every
    row carries last season's line (pre_*) and vote shares (prev_share_*) for the driver tests."""
    seasons_data()
    out = {k: [] for k in ('smoy', 'mip', 'alldef', 'allrookie', 'coy')}
    prev_ad = {}
    for s in sorted(ROWS):
        rows, v, st = ROWS[s], VOTES[s], STAND[s]
        annotate(s, rows)
        for r in rows:
            r['prev_alldef'] = prev_ad.get(r['id'], 0)
        bench = [r for r in rows if r['mp'] >= 500 and r['gs'] < r['g'] / 2]
        out['smoy'].append((s, bench, _order(bench, [i for i, _ in v.get('smoy', [])])))
        if s > FIRST:
            mip = [r for r in rows if r['mp'] >= 1000 and r['has_pre']]
            out['mip'].append((s, mip, _order(mip, [i for i, _ in v.get('mip', [])])))
        ad = [r for r in rows if r['mp'] >= 1200]
        nm = named(s, 'leading_all_defense', 'all_defense_team')
        miss = [i for i in nm if i not in {r['id'] for r in ad}]
        if miss: print('nba', s, 'all-defensive named outside pool', miss)
        out['alldef'].append((s, ad, _order(ad, nm)))
        for i in nm: prev_ad[i] = prev_ad.get(i, 0) + 1
        if s >= FIRST + 2:
            rk = [r for r in rows if r['rookie'] and r['mp'] >= 300]
            nm = named(s, 'leading_all_rookie', 'all_rookie_team')
            miss = [i for i in nm if i not in {r['id'] for r in rk}]
            if miss: print('nba', s, 'all-rookie named outside pool', miss)
            out['allrookie'].append((s, rk, _order(rk, nm)))
        st0 = STAND.get(s - 1) or standings(s - 1)
        ou = preseason_ou(s)
        teams = []
        g = {2012: 66, 2021: 72}.get(s, 82)                # the scheduled season the line was set on
        for t, x in st.items():
            pre = st0.get(t, {}).get('wp', .5)
            teams.append({'id': t, 'n': t, 'tm': t, 'wp': x['wp'], 'd_wp': x['wp'] - pre, 'pre_wp': pre,
                          'seed1': 1.0 if x['seed'] == 1 else 0.0,
                          'ovr': x['wp'] - (ou[t] / g if t in ou else pre), 'has_ou': t in ou})
        out['coy'].append((s, teams, _order(teams, [t for t, _ in v.get('coy', [])])))
    return out, prev_ad
