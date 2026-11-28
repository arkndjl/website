# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Live tracking for "your favorites" (/favorites/, layouts/shortcodes/favorites.html, assets/js/favs.js).

    python3 scripts/favorites_track.py          # rewrite static/data/favs/*.json (skips files where only asof moved)
    python3 scripts/favorites_track.py --test   # check the shard hash against assets/js/favs.js

A visitor follows a team or player picked from the site search's index (static/data/search-players.json, rows keyed by
the board's page stem and the name). This file reads the same boards and writes one small file a sport, so the page
fetches only the sports someone follows:

  static/data/favs/<sport>.json      {"asof", "ps": player shards, "t": {team key: team}, "p": {player key: [player]}}
  static/data/favs/<sport>-p<i>.json {"p": {...}} when the sport's players are split into shards (CFB, CBB)

  team   {"n": name, "ab": short, "rk": ARK Ranking rank, "c": [[label, value]], "rec": record,
          "sch": [[date or "wk N", opponent, "v"/"@"/"n", our score, their score, p(win)]]: the last 3 played, the next 3}
  player [team, [[label, value]], team key]   (a list: same-name players on other teams stay apart)

Keys are the name in the search's slug form (lower case, runs of anything but a-z0-9 = "-"). Teams come from the boards'
ARK Ranking and schedules (static/data/teams/<sport>.json), players from the boards the search reads. Stdlib only.
Rerun by .github/workflows/search-index.yml with the search index."""
import glob, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'static/data/favs')
SHARDS = {'cfb': 16, 'cbb': 4}

# search board page stem -> sport file (assets/js/favs.js holds the same map)
PAGES = {'arkboard-college-football': 'cfb', 'arkboard-college-basketball': 'cbb', 'arkboard-nfl': 'nfl', 'arkboard-nba': 'nba',
         'arkboard-nhl': 'nhl', 'arkboard-soccer': 'soccer', 'arkboard-soccer-prospects': 'socp', 'arkboard-hockey-prospects': 'hkp',
         'arkboard-tennis': 'tennis', 'arkboard-tennis-prospects': 'tnp', 'arkboard-counter-strike': 'cs2'}


def load(rel):
    try:
        with open(os.path.join(ROOT, rel), encoding='utf-8') as f: return json.load(f)
    except (OSError, ValueError) as e:
        print(f'  skip {rel}: {e}', file=sys.stderr); return None


def latest(pattern):
    fs = sorted(glob.glob(os.path.join(ROOT, pattern)), key=lambda f: int(re.sub(r'\D', '', os.path.basename(f)) or 0))
    return os.path.relpath(fs[-1], ROOT) if fs else None


def slug(s):
    return re.sub(r'^-|-$', '', re.sub(r'[^a-z0-9]+', '-', str(s or '').lower()))


def shard(key, n):
    """The same hash as shard() in assets/js/favs.js: h = 31h + char code, 32-bit (keys are slugs, so ASCII)."""
    h = 0
    for ch in key: h = (h * 31 + ord(ch)) & 0xffffffff
    return h % n


def num(x, d=1, sign=False):
    if not isinstance(x, (int, float)): return None
    s = f'{x:+.{d}f}' if sign else f'{x:.{d}f}'
    return s.replace('-', '−')


def money(x):
    if not isinstance(x, (int, float)) or x <= 0: return None
    return f'${x / 1e6:.1f}M' if x >= 1e6 else f'${round(x / 1e3)}K'


def pct(x):
    if not isinstance(x, (int, float)): return None
    v = x * 100
    return '>99%' if v > 99.5 else '<1%' if v < 0.5 else f'{v:.0f}%'


def chips(*pairs):
    return [[l, v] for l, v in pairs if v not in (None, '', '−')]


def sched(rows, name, today):
    """[[date, opp, ha, us, them, p]]: the last 3 with a score and the next 3 without, opp as a name."""
    out = []
    for r in rows or []:
        d, opp, ha, us, them = r[0], r[1], r[2], r[3], r[4]
        p = r[5] if len(r) > 5 else None
        d = d if isinstance(d, str) else f'wk {d}'
        out.append([d, name(opp), ha, us, them, round(p, 3) if isinstance(p, (int, float)) else None])
    played = [r for r in out if r[3] is not None]
    left = [r for r in out if r[3] is None and r[1] not in ('TBD', '')]
    return played[-3:] + left[:3]


class Sport:
    def __init__(self, k):
        self.k, self.t, self.p = k, {}, {}

    def team(self, name, **kw):
        if name: self.t[slug(name)] = {'n': name, **{a: b for a, b in kw.items() if b not in (None, '', [])}}

    def player(self, name, team, cs, tkey=None):
        if not name: return
        row = [team or '', cs]
        if tkey: row.append(tkey)
        lst = self.p.setdefault(slug(name), [])
        if not any(x[0] == row[0] for x in lst): lst.append(row)


def teams_file(sp):
    return (load(f'static/data/teams/{sp}.json') or {}).get('teams') or {}


def cfb(today):
    s = Sport('cfb')
    rk = load('data/cfb_rank.json') or {}
    names = dict((load('static/data/teams/cfb.json') or {}).get('nm') or {})
    for t in rk.get('teams') or []: names[str(t.get('tid'))] = t.get('team')
    sch = teams_file('cfb')
    for t in rk.get('teams') or []:
        s.team(t.get('team'), ab=t.get('abbr'), rk=t.get('rk'), rec=t.get('rec'), l=t.get('logo'),
               c=chips(('ARK', num(t.get('rating'))), ('CFP', t.get('cfp') and f"#{t['cfp']}"), ('AP', t.get('ap') and f"#{t['ap']}")),
               sch=sched((sch.get(str(t.get('tid'))) or {}).get('sch'), lambda o: names.get(str(o), str(o)), today))
    d = load('static/data/cfb-all.json')
    if d:
        c = {k: i for i, k in enumerate(d['cols'])}
        for r in d['rows']:
            g = lambda k: r[c[k]] if k in c else None
            s.player(g('name'), g('team'), chips(('FV', g('fv')), (g('pos'), g('posRank') and f"#{g('posRank')}"), ('WAR', num(g('war'), 2)),
                                                  ('yNIL', money(g('ynil'))), ('xNIL', money(g('xnil'))), ('Draft%', pct(g('draftP'))),
                                                  ('snaps', g('snaps'))), slug(g('team')))
    return s


def cbb(today):
    s = Sport('cbb')
    g = load('data/cbb_games.json') or {}
    names = dict((load('static/data/teams/cbb.json') or {}).get('nm') or {})
    for t in g.get('power') or []: names[str(t.get('id'))] = t.get('t')
    sch = teams_file('cbb')
    for t in g.get('power') or []:
        s.team(t.get('t'), rk=t.get('rk'), rec=t.get('rec'), l=t.get('logo'),
               c=chips(('ARK', num(t.get('rating'))), ('xW', num(t.get('xW'), 0)), ('Title', pct(t.get('title')))),
               sch=sched((sch.get(str(t.get('id'))) or {}).get('sch'), lambda o: names.get(str(o), str(o)), today))
    d = load('static/data/cbb-all.json')
    if d:
        c = {k: i for i, k in enumerate(d['cols'])}
        for r in d['rows']:
            v = lambda k: r[c[k]] if k in c else None
            now = v('now') or {}
            s.player(v('name'), v('team'), chips(('FV', v('fv')), ('XPM', num(v('xpm'), 1, True)), ('PPG', num(now.get('ppg'))),
                                                  ('RPG', num(now.get('rpg'))), ('APG', num(now.get('apg'))), ('NBA%', pct(v('nbaP')))), slug(v('team')))
    return s


# Basketball-Reference team codes on the NBA player file -> the ESPN codes the schedules use
BBREF = {'BRK': 'BKN', 'CHO': 'CHA', 'GSW': 'GS', 'NOP': 'NO', 'NYK': 'NY', 'PHO': 'PHX', 'SAS': 'SA', 'UTA': 'UTAH', 'WAS': 'WSH'}


def pro(sp, today):
    s = Sport(sp)
    nm = (load('data/pro_team_names.json') or {}).get(sp, {})
    g = load(f'data/{sp}_games.json') or {}
    sch = teams_file(sp)
    for t in g.get('power') or []:
        code = t['t']
        if sp == 'nfl': cs = chips(('ARK', num(t.get('rating'))), ('WAR', num(t.get('war'))), ('QB', t.get('qb')))
        elif sp == 'nba': cs = chips(('ARK', num(t.get('rating'))), ('xW', num(t.get('wins'), 0)), ('Title', pct(t.get('title'))))
        else: cs = chips(('ARK', num(t.get('rating'), 2)), ('xPts', num(t.get('xpts'), 0)), ('Cup', pct(t.get('cup'))))
        s.team(nm.get(code) or code, ab=code, rk=t.get('rk'), rec=t.get('rec'), l=f'/img/{sp}/{code.lower()}.png', c=cs,
               sch=sched((sch.get(code) or {}).get('sch'), lambda o: o, today))
    src = 'static/data/nfl-war.json' if sp == 'nfl' else latest(f'static/data/{sp}-{"xpm" if sp == "nba" else "war"}/*.json')
    d = load(src) if src else None
    for p in (d or {}).get('players') or []:
        tm = p.get('t') or p.get('tm')
        if sp == 'nfl': cs = chips(('WAR', num(p.get('war'))), (p.get('pos'), p.get('line')), ('age', p.get('age')))
        elif sp == 'nba': cs = chips(('XPM', num(p.get('xpm'), 1, True)), ('VORX', num(p.get('vorx'))), ('MPG', num(p['mp'] / p['g']) if p.get('g') and p.get('mp') else None), ('age', p.get('age')))
        else: cs = chips(('WAR', num(p.get('war'), 2)), ('G', p.get('g')), ('PTS', p.get('pts')), ('pWAR', num(p.get('pwar'), 2)))
        s.player(p.get('n'), tm, cs, slug(nm.get(BBREF.get(tm, tm)) or tm))
    return s


def soccer(today):
    s = Sport('soccer')
    g = load('data/soccer_games.json') or {}
    names = dict((load('static/data/teams/soccer.json') or {}).get('nm') or {})
    for t in g.get('power') or []: names[str(t.get('id'))] = t.get('n')
    sch = teams_file('soccer')
    for t in g.get('power') or []:
        s.team(t.get('n'), ab=t.get('ab'), rk=t.get('rk'), rec=t.get('rec'), l=f"/img/soccer/{t['id']}.png",
               c=chips(('ARK', num(t.get('rating'), 2)), ('Pts', t.get('pts')), ('Title', pct(t.get('title')))),
               sch=sched((sch.get(str(t.get('id'))) or {}).get('sch'), lambda o: names.get(str(o), str(o)), today))
    src = latest('static/data/soccer-war/*.json')
    for p in ((load(src) if src else None) or {}).get('players') or []:
        s.player(p.get('n'), p.get('team'), chips(('SVAR', num(p.get('svar'), 2)), ('G', p.get('g')), ('A', p.get('a')),
                                                   ('xMV', p.get('xmv') and f"€{p['xmv']:.0f}m")), slug(p.get('team')))
    return s


def prospects():
    out = []
    s = Sport('socp')
    for p in (load('data/soccer_prospects.json') or {}).get('board') or []:
        s.player(p.get('name'), p.get('club'), chips(('FV', p.get('fv')), ('age', num(p.get('age'))), ('MV', p.get('mv') and f"€{p['mv'] / 1e6:.0f}m")))
    out.append(s)
    s = Sport('hkp')
    h = load('data/hockey.json') or {}
    for p in h.get('board') or []:
        s.player(p.get('name'), p.get('club'), chips(('FV', p.get('fv')), ('rank', p.get('rk') and f"#{p['rk']}"), ('age', num(p.get('age'))), ('PTS', p.get('pts'))))
    for p in h.get('pipe') or []:
        s.player(p.get('name'), p.get('team'), chips(('FV', p.get('fv')), ('pick', p.get('pick') and f"{p.get('year')} #{p['pick']}"), ('age', num(p.get('age')))))
    out.append(s)
    s = Sport('tennis')
    for tour, t in ((load('data/tennis.json') or {}).get('tours') or {}).items():
        for p in t.get('players') or []:
            s.player(p.get('n'), tour.upper(), chips(('rank', p.get('rank') and f"#{p['rank']}"), ('ARK', num(p.get('ark'), 3)), ('W-L', p.get('w') is not None and f"{p['w']}-{p.get('l', 0)}"), ('SV', num(p.get('sv')))))
    out.append(s)
    s = Sport('tnp')
    d = load('data/tennis_prospects.json') or {}
    for tour in ('atp', 'wta'):
        for p in (d.get(tour) or {}).get('board') or []:
            s.player(p.get('name'), tour.upper(), chips(('FV', p.get('fv')), ('rank', p.get('rank') and f"#{p['rank']}"), ('age', num(p.get('age')))))
    out.append(s)
    return out


def cs2(today):
    s = Sport('cs2')
    g = load('data/cs2.json') or {}
    for t in g.get('teams') or []:
        s.team(t.get('n'), rk=t.get('rk'), l=f"/img/cs2/{t['k']}.png" if t.get('logo') else None, rec=t.get('w90') is not None and f"{t['w90']}-{t.get('l90', 0)}",
               c=chips(('ARK', num(t.get('ark'), 3)), ('tier', t.get('tier') and f"T{t['tier']}"), ('form', t.get('form'))), last=t.get('last'))
    d = load('data/cs2_players.json') or {}
    for p in (d.get('board') or []) + (d.get('prospects') or []):
        s.player(p.get('n'), p.get('tm'), chips(('RWA', num(p.get('rwa'), 2, True)), ('ADR', num(p.get('adr'))), ('KAST', p.get('kast') and f"{p['kast']:.0f}%"), ('maps', p.get('maps'))), slug(p.get('tm')))
    return s


def write(rel, obj):
    p = os.path.join(OUT, rel)
    try:
        with open(p, encoding='utf-8') as f: old = json.load(f)
    except (OSError, ValueError): old = None
    if old is not None and {k: v for k, v in old.items() if k != 'asof'} == {k: v for k, v in obj.items() if k != 'asof'}: return False
    with open(p, 'w', encoding='utf-8') as f: json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))
    return True


def main():
    if '--test' in sys.argv:
        # values from shard() in assets/js/favs.js
        for k, n, want in (('jeremiah-smith', 16, None), ('a', 16, 97 % 16), ('ab', 4, (97 * 31 + 98) % 4)):
            got = shard(k, n)
            if want is not None and got != want: sys.exit(f'shard({k!r}, {n}) = {got}, want {want}')
        print('ok'); return
    import datetime
    today = datetime.date.today().isoformat()
    os.makedirs(OUT, exist_ok=True)
    asof = (load('static/data/search-players.json') or {}).get('asof') or datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ')
    sports = [cfb(today), cbb(today), pro('nfl', today), pro('nba', today), pro('nhl', today), soccer(today), cs2(today)] + prospects()
    n = 0
    for s in sports:
        k = SHARDS.get(s.k, 1)
        head = {'asof': asof, 'ps': k, 't': s.t}
        if k == 1: head['p'] = s.p
        else:
            parts = [{} for _ in range(k)]
            for key, v in s.p.items(): parts[shard(key, k)][key] = v
            for i, part in enumerate(parts): n += write(f'{s.k}-p{i}.json', {'p': part})
        n += write(f'{s.k}.json', head)
        print(s.k, 'teams', len(s.t), 'players', len(s.p))
    print('wrote', n, 'files')


if __name__ == '__main__':
    main()
