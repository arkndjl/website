#!/usr/bin/env python3
"""Backup watch (Noah, Oct 23 2026): second- and third-string players graded above the starter they back up, for the
backup watch tab in each sport (layouts/shortcodes/backupwatch.html). College football is scripts/backup_watch_cfb.mjs.

    python3 scripts/backup_watch.py [nfl nba cbb nhl]     -> data/backup_<sport>.json (one file a sport: each sport's
                                                         workflow commits its own)

NFL     ESPN's depth charts (offense and base defense; no specialists). The starter is the first name at each slot, the
        next two are the 2nd and 3rd string. The grade is production: the board's WAR a snap this season
        (static/data/nfl-war.json), shrunk toward replacement (0) with NFL_K snaps, per 1,000 snaps. A backup needs
        NFL_MIN snaps to be listed: with none, the grade is the shrink target, not a measure of him.
NBA     ESPN's depth charts (PG, SG, SF, PF, C). Starter = first at each slot; a non-starter listed 2nd or 3rd at a slot
        backs up that slot's starter (his highest listing). The grade is XPM (static/data/nba-xpm/): this season's
        minutes, last season's at half weight and the one before at a quarter (NBA_W: a starter back from a lost
        season keeps his line), shrunk to NBA_REPL with NBA_K weighted minutes. A backup needs NBA_MIN minutes.
NHL     ESPN's depth charts, even strength only (C, LW, RW, LD, RD, G; the power-play and penalty-kill units are
        skipped). Starter = first at each slot (the first-line player, the starting goalie); 2nd and 3rd names are the
        second and third lines and the backup goalie. The grade is HPM (static/data/nhl-war/, goals a 60 above average):
        this season's minutes, last season's at half weight and the one before at a quarter, shrunk to the position's
        replacement level with NHL_K weighted minutes (goalies NHL_KG). A backup needs NHL_MIN minutes.
CBB     No college depth charts, so the order is minutes: this season's minutes a game once a player has a line
        (static/data/cbb-all.json now), else the projected minutes share of the CBB roster prior (scripts/cbb_roster.py,
        fit walk-forward; saved to scripts/data/cbb_proj_min.json, rebuilt here when the research seasons are in the
        project files). Top five = starters, 6-10 2nd string, 11-15 3rd. A backup is compared with the lowest-graded
        starter in his group (G, F, C; a group with no starter falls back to the next one) and listed when his FV
        (headline = mean outcome) beats that starter's by FV_GAP or more.
"""
import json
import math
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import names as NM

PROJ_MIN = os.path.join(HERE, 'data', 'cbb_proj_min.json')
ESPN = 'https://site.api.espn.com/apis/site/v2/sports'
UA = {'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36'}
NFL_K, NFL_MIN = 300, 50
NBA_K, NBA_REPL, NBA_MIN, NBA_W = 500, -2.0, 50, (1.0, 0.5, 0.25)
NHL_K, NHL_KG, NHL_MIN, NHL_W = 600, 1500, 100, (1.0, 0.5, 0.25)
FV_GAP = 3
NFL_SKIP = {'pk', 'p', 'h', 'pr', 'kr', 'ls'}
NFL_SLOT = {'qb': 'QB', 'rb': 'RB', 'fb': 'FB', 'wr1': 'WR', 'wr2': 'WR', 'wr3': 'WR', 'te': 'TE', 'lt': 'LT', 'lg': 'LG',
            'c': 'C', 'rg': 'RG', 'rt': 'RT', 'lde': 'DE', 'rde': 'DE', 'ldt': 'DT', 'rdt': 'DT', 'nt': 'NT', 'wlb': 'WLB',
            'mlb': 'MLB', 'slb': 'SLB', 'lilb': 'ILB', 'rilb': 'ILB', 'lolb': 'OLB', 'rolb': 'OLB', 'lcb': 'CB',
            'rcb': 'CB', 'nb': 'NB', 'ss': 'SS', 'fs': 'FS'}
NFL_TEAM = {'LAR': 'LA', 'WSH': 'WAS'}                         # ESPN -> nflverse
NBA_TEAM = {'GS': 'GSW', 'NO': 'NOP', 'SA': 'SAS', 'NY': 'NYK', 'UTAH': 'UTA', 'WSH': 'WAS', 'PHX': 'PHO', 'BKN': 'BRK', 'CHA': 'CHO'}


def get(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return json.load(r)
        except Exception as e:
            if i == tries - 1:
                print('backup watch:', url, e)
            time.sleep(1.5 * 2 ** i)
    return None


def espn_depth(league):
    """[(team abbreviation, chart name, slot, [(name, espn id)...])] for every team"""
    d = get(f'{ESPN}/{league}/teams')
    teams = [t['team'] for t in d['sports'][0]['leagues'][0]['teams']] if d else []
    out = []
    for t in teams:
        dc = get(f"{ESPN}/{league}/teams/{t['id']}/depthcharts") or {}
        for u in dc.get('depthchart') or []:
            for slot, v in (u.get('positions') or {}).items():
                out.append((t['abbreviation'], u.get('name') or '', slot, [(a.get('displayName'), a.get('id')) for a in v.get('athletes') or []]))
        time.sleep(0.15)
    return out


def r1(x): return None if x is None else round(x, 1)
def r2(x): return None if x is None else round(x, 2)


def depth_rows(charts, grade, team_of, skip=lambda chart, slot: False, slot_name=str.upper, need=0):
    """the shared ESPN-chart logic: (backups above their slot's starter, slots compared). grade(name, team) -> dict
    with g (grade) and n (sample) or None"""
    starters, listed = set(), {}
    slots = []
    for tm, chart, slot, ath in charts:
        if skip(chart, slot) or not ath:
            continue
        t = team_of(tm)
        slots.append((t, chart, slot, ath))
        starters.add((t, NM.key(ath[0][0])))
    out, n = {}, 0
    for t, chart, slot, ath in slots:
        s = grade(ath[0][0], t)
        if s is None:
            continue
        n += 1
        for i, (nm, _) in enumerate(ath[1:3], start=2):
            if (t, NM.key(nm)) in starters:
                continue
            b = grade(nm, t)
            if b is None or b['n'] < need or b['g'] <= s['g']:
                continue
            row = {'name': nm, 'team': t, 'pos': slot_name(slot), 'str': i, 'g': b['g'], 'use': b['n'], 'pos2': b.get('pos'),
                   'starter': {'name': ath[0][0], 'g': s['g'], 'use': s['n']}, 'gap': round(b['g'] - s['g'], 2)}
            k = (t, NM.key(nm)); old = out.get(k)
            if old is None or (i, -row['gap']) < (old['str'], -old['gap']):
                out[k] = row
    rows = sorted(out.values(), key=lambda r: (-r['gap'], -r['g']))
    return rows, n


def nfl():
    W = json.load(open(os.path.join(ROOT, 'static', 'data', 'nfl-war.json')))
    M = NM.Matcher(W['players'], name='n', team='t', pos='pos')

    def grade(nm, t):
        p, _ = M.find(nm, team=t)
        if p is None:
            return None
        sn = p.get('sn') or 0
        return {'g': round(1000 * (p.get('war') or 0) / (sn + NFL_K), 2), 'n': sn, 'pos': p.get('pos')}
    # the base defense and the 3-WR offense (ESPN lists both units for every team; a team can carry a nickel chart too)
    charts = espn_depth('football/nfl')
    rows, n = depth_rows(charts, grade, lambda a: NFL_TEAM.get(a, a), need=NFL_MIN,
                         skip=lambda chart, slot: slot in NFL_SKIP or slot not in NFL_SLOT or 'special' in chart.lower(),
                         slot_name=lambda s: NFL_SLOT[s])
    return {'season': W['season'], 'week': W['week'], 'asof': W['last'], 'slots': n, 'k': NFL_K, 'min': NFL_MIN, 'rows': rows}


def nba():
    D = os.path.join(ROOT, 'static', 'data', 'nba-xpm')
    seasons = sorted(int(f[:4]) for f in os.listdir(D) if f[:4].isdigit())
    S = [json.load(open(os.path.join(D, f'{y}.json'))) for y in seasons[::-1][:len(NBA_W)]]
    cur, acc = S[0], {}
    for d, w in zip(S, NBA_W):
        for p in d['players']:
            if p.get('xpm') is None:
                continue
            a = acc.setdefault(p['id'], {'n': p['n'], 'tm': p['tm'], 'num': 0.0, 'den': 0.0, 'mp': 0})
            a['num'] += w * p['mp'] * p['xpm']; a['den'] += w * p['mp']; a['mp'] += p['mp']
    for p in cur['players']:          # this season's team
        acc[p['id']]['tm'] = p['tm']
    P = list(acc.values())
    M = NM.Matcher(P, name='n', team='tm', pos=None, sport='basketball')

    def grade(nm, t):
        p, _ = M.find(nm, team=t)
        if p is None:
            return {'g': NBA_REPL, 'n': 0}          # no NBA minutes yet (a rookie): the shrink target
        return {'g': round((p['num'] + NBA_K * NBA_REPL) / (p['den'] + NBA_K), 2), 'n': p['mp']}
    rows, n = depth_rows(espn_depth('basketball/nba'), grade, lambda a: NBA_TEAM.get(a, a), need=NBA_MIN)
    return {'season': cur['season'], 'label': cur['label'], 'asof': cur['asof'][:10], 'slots': n, 'k': NBA_K,
            'repl': NBA_REPL, 'w': NBA_W, 'min': NBA_MIN, 'rows': rows}


def nhl():
    import nhl_data as N
    D = os.path.join(ROOT, 'static', 'data', 'nhl-war')
    seasons = sorted(int(f[:4]) for f in os.listdir(D) if f[:4].isdigit())
    S = [json.load(open(os.path.join(D, f'{y}.json'))) for y in seasons[::-1][:len(NHL_W)]]
    cur, acc = S[0], {}
    for d, w in zip(S, NHL_W):
        for p in d['players']:
            if p.get('hpm') is None or not p.get('toi'):
                continue
            a = acc.setdefault(p['id'], {'n': p['n'], 'tm': p['tm'], 'grp': p['grp'], 'pos': p['pos'], 'num': 0.0, 'den': 0.0, 'toi': 0})
            a['num'] += w * p['toi'] * p['hpm']; a['den'] += w * p['toi']; a['toi'] += p['toi']
    for p in cur['players']:          # this season's team
        if p['id'] in acc:
            acc[p['id']]['tm'] = p['tm']
    M = NM.Matcher(list(acc.values()), name='n', team='tm', pos=None)
    repl = cur['repl']

    def grade(nm, t, grp):
        r, k = repl.get(grp) or 0.0, NHL_KG if grp == 'G' else NHL_K
        p, _ = M.find(nm, team=t)
        if p is None:
            return {'g': round(r, 3), 'n': 0}       # no NHL minutes yet: the shrink target
        return {'g': round((p['num'] + k * r) / (p['den'] + k), 3), 'n': round(p['toi']), 'pos': p['pos']}
    charts = [c for c in espn_depth('hockey/nhl') if c[1].lower() in ('default', '')]
    rows = []; n = 0
    for grp, slots in (('F', ('c', 'lw', 'rw')), ('D', ('ld', 'rd')), ('G', ('g',))):
        r, m = depth_rows([c for c in charts if c[2] in slots], lambda nm, t, g=grp: grade(nm, t, g), N.team, need=NHL_MIN)
        rows += r; n += m
    for r in rows:
        r['logo'] = f"/img/nhl/{r['team'].lower()}.png"
    rows.sort(key=lambda r: (-r['gap'], -r['g']))
    return {'season': cur['season'], 'label': cur['label'], 'asof': cur['asof'][:10], 'slots': n, 'k': NHL_K, 'kg': NHL_KG,
            'w': NHL_W, 'min': NHL_MIN, 'repl': repl, 'rows': rows}


def cbb_projected():
    """{name|team: projected minutes share (team's 500)} from the CBB roster prior; saved, and reused without the
    research seasons"""
    try:
        import cbb_roster as R
        import cbb_games as C
        by = R.load_seasons()
        ts = R.team_strength(by)
        _, _, models = R.build(by, ts, last=C.LAST + 1)
        Mo = models[C.LAST + 1]
        T = {}
        for team, k, x, nm, bteam in R.live_players(C.LAST + 1, ts, names=True):
            bw, mw = Mo[k]
            T.setdefault(team, []).append((nm, bteam, max(0.5, float(sum(a * b for a, b in zip(mw, x))))))
        out = {}
        for team, L in T.items():
            tot = sum(m for *_, m in L)
            for nm, bteam, m in L:
                out[f'{nm}|{bteam}'] = round(500 * m / tot, 1)
        json.dump({'season': C.LAST + 1, 'asof': time.strftime('%Y-%m-%d'), 'min': out}, open(PROJ_MIN, 'w'), separators=(',', ':'))
        print(f'backup watch cbb: projected minutes for {len(out)} players')
        return out
    except (OSError, ImportError) as e:
        print('backup watch cbb: projected minutes from the saved file:', str(e)[:120])
        return json.load(open(PROJ_MIN))['min']


CBB_NEXT = {'G': ['G', 'F'], 'F': ['F', 'C', 'G'], 'C': ['C', 'F']}


def cbb():
    A = json.load(open(os.path.join(ROOT, 'static', 'data', 'cbb-all.json')))
    ci = {k: i for i, k in enumerate(A['cols'])}
    proj = cbb_projected()
    teams, live = {}, 0
    for r in A['rows']:
        fv = r[ci['fv']]
        if fv is None or not r[ci['team']]:
            continue
        now = r[ci['now']] if 'now' in ci else None
        if now and (now.get('gp') or 0) >= 1:
            mpg, src = now['mpg'], 'season'; live += 1
        else:
            sh = proj.get(f"{r[ci['name']]}|{r[ci['team']]}")
            if sh is None:
                continue
            mpg, src = 40 * sh / 100, 'proj'
        teams.setdefault(r[ci['team']], []).append({'name': r[ci['name']], 'team': r[ci['team']], 'logo': r[ci['logo']],
            'conf': r[ci['conf']], 'pos': r[ci['pos']], 'cls': r[ci['cls']], 'fv': fv, 'mpg': round(mpg, 1), 'src': src})
    rows, rooms = [], 0
    for t, L in teams.items():
        if len(L) < 6:
            continue
        L.sort(key=lambda p: -p['mpg'])
        st = L[:5]; rooms += 1
        for i, b in enumerate(L[5:15]):
            grp = next((g for g in CBB_NEXT[b['pos']] if any(s['pos'] == g for s in st)), None)
            if grp is None:
                continue
            low = min((s for s in st if s['pos'] == grp), key=lambda s: s['fv'])
            if b['fv'] - low['fv'] < FV_GAP:
                continue
            rows.append({**b, 'str': 2 if i < 5 else 3, 'starter': {k: low[k] for k in ('name', 'pos', 'fv', 'mpg', 'cls')}, 'gap': b['fv'] - low['fv']})
    rows.sort(key=lambda r: (-r['gap'], -r['fv'], -r['mpg']))
    return {'asof': time.strftime('%Y-%m-%d'), 'teams': rooms, 'live': live, 'gap': FV_GAP, 'rows': rows}


def clean(o):
    """NaN -> null (a bare NaN in data/*.json breaks the Hugo build)"""
    if isinstance(o, float) and not math.isfinite(o):
        return None
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [clean(v) for v in o]
    return o


def main():
    want = [a for a in sys.argv[1:] if a in ('nfl', 'nba', 'cbb', 'nhl')] or ['nfl', 'nba', 'cbb', 'nhl']
    for s in want:
        try:
            d = {'nfl': nfl, 'nba': nba, 'cbb': cbb, 'nhl': nhl}[s]()
        except Exception as e:                    # one sport failing keeps its last table
            print(f'backup watch {s}: not updated ({type(e).__name__}: {str(e)[:160]})')
            continue
        json.dump(clean(d), open(os.path.join(ROOT, 'data', f'backup_{s}.json'), 'w'), indent=1)
        print(f"backup watch {s}: {len(d['rows'])} backups above the starter")


if __name__ == '__main__':
    main()
