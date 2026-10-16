"""NBA XPM leaderboard for the NBA ARKBOARD (static/data/nba-xpm/<season>.json, data/nba_xpm.json).

XPM is the board's NBA impact metric: 50/50 databallr DPM + Basketball-Reference BPM, offense and defense blended
the same way (O-XPM = .5 ODPM + .5 OBPM, D-XPM = .5 DDPM + .5 DBPM; BPM alone where a player has no DPM row). The
College Basketball ARKBOARD grades prospects on peak XPM, and the XPM test (project files cbb/xpm/README.md: 480
team-seasons 2011-26, forward + leave-one-season-out) found nothing that tracks team margin or wins better.
VORX is VORP on XPM: (XPM + 2) x MP / 19,680 (bbref's VORP formula with XPM in place of BPM).

  python3 scripts/nba_xpm.py 2010 2026     # seasons from..to (end year: 2026 = 2025-26)
  python3 scripts/nba_xpm.py --current     # the season in progress, for the daily refresh

Inputs: bbref's advanced table, fetched into scripts/.cache/nba/adv_<season>.html (refetched for the current
season); DPM from scripts/.cache/cbb/dpm/<season>.json (node scripts/cbb_dpm.mjs <season>). A season with no
DPM file keeps the DPM already in its published file, or goes out BPM-only. Stdlib only."""
import datetime as dt, html, json, os, re, sys, time, unicodedata, urllib.request

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'nba')
DPM = os.path.join(ROOT, 'scripts', '.cache', 'cbb', 'dpm')
OUT = os.path.join(ROOT, 'static', 'data', 'nba-xpm')
INDEX = os.path.join(ROOT, 'data', 'nba_xpm.json')
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36'


def current_season(today=None):
    t = today or dt.date.today()
    return t.year + 1 if t.month >= 10 else t.year          # the 2026-27 season is 2027 from October


def fetch(season, fresh):
    os.makedirs(CACHE, exist_ok=True)
    fn = os.path.join(CACHE, f'adv_{season}.html')
    if not fresh and os.path.exists(fn) and os.path.getsize(fn) > 50000:
        return open(fn, encoding='utf-8').read()
    url = f'https://www.basketball-reference.com/leagues/NBA_{season}_advanced.html'
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            h = urllib.request.urlopen(req, timeout=60).read().decode('utf-8', 'replace')
            open(fn, 'w', encoding='utf-8').write(h)
            time.sleep(4)                                   # bbref allows about 20 requests a minute
            return h
        except urllib.error.HTTPError as e:
            if e.code == 404: return ''                     # no page before the season's first game
            print(season, 'bbref', e, flush=True); time.sleep(20 * (attempt + 1))
        except Exception as e:
            print(season, 'bbref', e, flush=True); time.sleep(20 * (attempt + 1))
    return ''


def cell(s):
    return html.unescape(re.sub(r'<[^>]+>', '', s)).strip()


def num(s):
    try: return float(s)
    except (TypeError, ValueError): return None


def parse(h):
    """one row per player-season: the TOT/2TM row for traded players, with the teams in order"""
    tb = re.search(r'<table[^>]*id="advanced"[^>]*>(.*?)</table>', h, re.S)
    if not tb: return []
    out, by = [], {}
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', tb.group(1), re.S):
        c = dict((k, v) for k, v in re.findall(r'data-stat="([^"]+)"[^>]*>(.*?)</t[dh]>', tr, re.S))
        name = c.get('name_display', c.get('player'))
        pid = re.search(r'/players/\w/(\w+)\.html', name or '')
        if not pid: continue
        pid = pid.group(1)
        tm = cell(c.get('team_name_abbr', c.get('team_id', '')))
        r = {'id': pid, 'n': cell(name).rstrip('*'), 'tm': tm, 'pos': cell(c.get('pos', '')).split('-')[0],
             'age': num(cell(c.get('age', ''))), 'g': num(cell(c.get('games', c.get('g', '')))),
             'mp': num(cell(c.get('mp', ''))), 'obpm': num(cell(c.get('obpm', ''))),
             'dbpm': num(cell(c.get('dbpm', ''))), 'bpm': num(cell(c.get('bpm', '')))}
        if pid in by:                                       # a stint after the TOT row: collect its team
            if re.match(r'^(TOT|\dTM)$', by[pid]['tm']) or by[pid].get('tms'):
                by[pid].setdefault('tms', []).append(tm)
            continue
        by[pid] = r; out.append(r)
    for r in out:
        if r.get('tms'): r['tm'] = '/'.join(r.pop('tms'))
    return [r for r in out if r['mp'] and r['bpm'] is not None]


def norm(n):
    n = unicodedata.normalize('NFKD', str(n)).encode('ascii', 'ignore').decode().lower()
    n = re.sub(r"[.'`-]", '', n); n = re.sub(r'\b(jr|sr|ii|iii|iv|v)\b', '', n)
    return re.sub(r'\s+', ' ', n).strip()


def load_dpm(season, prev):
    fn = os.path.join(DPM, f'{season}.json')
    # databallr's page shows last season before opening night: only rows for this season count
    rows = [r for r in json.load(open(fn)) if r.get('season', season) == season] if os.path.exists(fn) else []
    if rows:
        d = {}
        for r in sorted(rows, key=lambda r: r.get('min') or 0):
            d[norm(r['name'])] = (r['dpm'], r['odpm'], r['ddpm'])       # most minutes wins on a name clash
        # a name spelled two ways (Ron / Ronald Holland): last name + first initial, when only one player has it
        short = {}
        for k in list(d): short.setdefault(k.split()[-1] + k[0], []).append(k)
        for k, v in short.items():
            if len(v) == 1: d.setdefault('~' + k, d[v[0]])
        return d, 'databallr'
    if prev:                                                             # keep what the published file had
        return {norm(p['n']): (p['dpm'], p['odpm'], p['ddpm']) for p in prev['players'] if p.get('dpm') is not None}, prev.get('dpmSrc')
    return {}, None


def r1(x): return None if x is None else round(x, 1)


def build(season, fresh=False):
    h = fetch(season, fresh)
    rows = parse(h) if h else []
    if not rows:
        print(season, 'no bbref rows'); return None
    fn = os.path.join(OUT, f'{season}.json')
    prev = json.load(open(fn)) if os.path.exists(fn) else None
    dpm, src = load_dpm(season, prev)
    players, hit, hitmp, allmp = [], 0, 0, 0
    for r in rows:
        k = norm(r['n']); d = dpm.get(k) or dpm.get('~' + k.split()[-1] + k[0])
        x = lambda a, b: 0.5 * a + 0.5 * b if a is not None and b is not None else b
        p = {'id': r['id'], 'n': r['n'], 'tm': r['tm'], 'pos': r['pos'], 'age': None if r['age'] is None else int(r['age']),
             'g': int(r['g'] or 0), 'mp': int(r['mp']),
             'bpm': r['bpm'], 'obpm': r['obpm'], 'dbpm': r['dbpm'],
             'dpm': d and d[0], 'odpm': d and d[1], 'ddpm': d and d[2]}
        p['xpm'] = r1(x(p['dpm'], p['bpm'])); p['oxpm'] = r1(x(p['odpm'], p['obpm'])); p['dxpm'] = r1(x(p['ddpm'], p['dbpm']))
        p['vorx'] = round((p['xpm'] + 2) * p['mp'] / 19680, 2)
        allmp += p['mp']
        if d: hit += 1; hitmp += p['mp']
        players.append(p)
    players.sort(key=lambda p: -p['vorx'])
    gmax = min(82, max(p['g'] for p in players))    # a traded player's TOT can pass 82
    out = {'season': season, 'label': f'{season - 1}-{str(season)[2:]}', 'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'),
           'n': len(players), 'games': gmax, 'dpmSrc': src, 'dpmShare': round(hitmp / allmp, 3) if allmp else 0,
           'players': players}
    if prev and {k: v for k, v in prev.items() if k != 'asof'} == {k: v for k, v in out.items() if k != 'asof'}:
        print(season, 'unchanged'); return prev
    os.makedirs(OUT, exist_ok=True)
    json.dump(out, open(fn, 'w'), separators=(',', ':'))
    print(f"{season}: {len(players)} players, DPM on {hit} ({out['dpmShare']:.0%} of minutes), {gmax} games")
    return out


def write_index():
    seasons = []
    for f in sorted(os.listdir(OUT)):
        if not f.endswith('.json'): continue
        d = json.load(open(os.path.join(OUT, f)))
        seasons.append({'season': d['season'], 'label': d['label'], 'n': d['n'], 'games': d['games'], 'asof': d['asof'],
                        'dpmShare': d['dpmShare']})
    seasons.sort(key=lambda s: -s['season'])
    old = json.load(open(INDEX)) if os.path.exists(INDEX) else None
    idx = {'seasons': seasons, 'current': seasons[0]['season'] if seasons else None}
    if old != idx: json.dump(idx, open(INDEX, 'w'), indent=1)


if __name__ == '__main__':
    a = sys.argv[1:]
    if a and a[0] == '--current':
        s = current_season()
        if not build(s, fresh=True): build(s - 1, fresh=True)    # before opening night: last season's final
    else:
        lo, hi = int(a[0]), int(a[1] if len(a) > 1 else a[0])
        for s in range(lo, hi + 1): build(s, fresh=False)
    write_index()
