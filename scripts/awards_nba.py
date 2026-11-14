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
            hm = re.search(r'href="/teams/([A-Z]{3})/', v)
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
    for aw in ('mvp', 'dpoy', 'roy'):
        rows = [(r['_id'], f(r.get('award_share'))) for r in table(h, aw) if r.get('_id') and r.get('award_share')]
        out[aw] = sorted(rows, key=lambda t: -t[1])
    return out


def standings(season):
    h = fetch(f'nba_season_{season}.html', f'https://www.basketball-reference.com/leagues/NBA_{season}.html')
    out = {}
    for tid in ('confs_standings_E', 'confs_standings_W'):
        rows = [r for r in table(h, tid) if r.get('_tm') and r.get('wins')]
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
        out[i] = {k: f(r.get(k)) for k in ('games', 'pts_per_g', 'trb_per_g', 'ast_per_g', 'stl_per_g',
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
                   'vorx': r.get('vorx', 0) or 0, 'xpm': r.get('xpm', 0) or 0, 'dxpm': r.get('dxpm', 0) or 0,
                   'ppg': p['pts_per_g'], 'rpg': p['trb_per_g'], 'apg': p['ast_per_g'],
                   'stocks': p['stl_per_g'] + p['blk_per_g'], 'mpg': p['mp_per_g'],
                   'big': 1.0 if r.get('pos', '') in ('C', 'PF') else 0.0,
                   'wp': wp, 'seed1': seed1, 'gfrac': p['games'] / n_games,
                   'prev_mvp': prev['mvp'].get(pid, 0), 'prev_dpoy': prev['dpoy'].get(pid, 0),
                   'rookie': pid not in seen}
            rows.append(row)
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
