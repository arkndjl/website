#!/usr/bin/env python3
"""Club logos for every soccer table that names a club rather than an ESPN team id (data/soccer_logos.json).

    python3 scripts/soccer_logos.py      # map names -> logo, fetch the missing crests

The match tables, power rankings and league/cup tables already carry ESPN ids (static/img/soccer/<id>.png, fetched
by soccer_games.py). The players, xMV and backup watch tables name clubs the Understat way ("RasenBallsport
Leipzig"), and the prospects board the Transfermarkt way ("Bayer 04 Leverkusen"):
  - Understat/ESPN names -> ESPN id: exact name first, then the best token match, among the ESPN clubs that played in
    that league since 2014-15 (scripts/soccer_games_hist.json.gz); ALIAS for the spellings neither reaches. Crest: ESPN 500 px, saved at 64 px.
  - Transfermarkt names -> Transfermarkt club id from the dump (clubs, games, players, transfers); a name used by
    several ids (youth or women's sides, a refounded club) takes the id with the most games in the last three
    seasons, then overall. Crest: Transfermarkt's, saved at 64 px
    under static/img/soccer/tm/.
Both sources are free. Logos are full colour, not pixelated (like the CFB/NFL logos).
"""
import collections, gzip, io, json, os, re, sys, unicodedata, urllib.request, zipfile
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, 'data')
IMG = os.path.join(ROOT, 'static', 'img', 'soccer')
OUT = os.path.join(DATA, 'soccer_logos.json')
DUMPD = os.path.join(HERE, '.cache', 'soccer_prospects', 'dump')
DUMP_URL = 'https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data/transfermarkt-datasets.zip'
ESPN = 'https://site.api.espn.com/apis/site/v2/sports/soccer'
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36'
# Understat spellings the token match can't reach (ESPN display name on the right)
ALIAS = {'RasenBallsport Leipzig': 'RB Leipzig', 'Hamburger SV': 'Hamburg SV', 'Inter': 'Internazionale',
         'AC Milan': 'AC Milan', 'Athletic Club': 'Athletic Club', 'Paris FC': 'Paris FC',
         'Racing Santander': 'Racing Santander', 'Real Sociedad': 'Real Sociedad'}
STOP = set('fc cf afc sc sv kv sk ac as ssc rc ud cd sd ca club de del la le cfc fk nk hnk bk if ik osc ogc rcd '
           'vfb vfl tsg bsc spvgg ssv fsv calcio balompie futbol football us'.split())


def get(url, raw=False):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            b = r.read()
        return b if raw else json.loads(b)
    except Exception:
        return None


def norm(s):
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode().lower()
    s = re.sub(r'[^a-z0-9 ]', ' ', s.replace('-', ' '))
    s = re.sub(r'([aou])e', r'\1', s)                             # Duesseldorf = Dusseldorf
    return ' '.join(w for w in s.split() if w not in STOP and not w.isdigit())


def espn_team(job):
    lg, tid = job
    t = (get(f'{ESPN}/{lg}/teams/{tid}') or {}).get('team') or {}
    return lg, tid, [t.get('displayName'), t.get('shortDisplayName'), t.get('location')]


def espn_map(names):
    """{Understat/ESPN name: ESPN id}, names = {name: league}"""
    hist = json.load(gzip.open(os.path.join(HERE, 'soccer_games_hist.json.gz'), 'rt'))
    jobs = sorted({(g['lg'], g[k]) for g in hist if g['lg'] in names.values() and g['day'] >= '2014-07'
                   for k in ('h', 'a')})
    by = collections.defaultdict(dict)
    with ThreadPoolExecutor(12) as ex:
        for lg, tid, ns in ex.map(espn_team, jobs):
            if ns[0]:
                by[lg][tid] = ns
    for lg in set(names.values()):                                 # this season's promoted clubs
        d = get(f'{ESPN}/{lg}/teams')
        for sp in (d or {}).get('sports') or []:
            for L in sp.get('leagues') or []:
                for t in L.get('teams') or []:
                    t = t.get('team') or {}
                    by[lg][t.get('id')] = [t.get('displayName'), t.get('shortDisplayName'), t.get('location')]
    out = {}
    for n, lg in names.items():
        pool = by.get(lg, {})
        want = ALIAS.get(n, n)
        hit = [i for i, ns in pool.items() if want in ns] or [i for i, ns in pool.items() if norm(want) in map(norm, ns)]
        if not hit:
            s = set(norm(want).split())
            score = {}
            for i, ns in pool.items():
                for x in ns:
                    t = set(norm(x).split())
                    if t and (t <= s or s <= t):
                        score[i] = max(score.get(i, 0), len(t & s))
            if score:
                top = max(score.values())
                hit = [i for i, v in score.items() if v == top]
        if len(hit) == 1:
            out[n] = hit[0]
        else:
            print('no ESPN club for', n, lg, [pool[i][0] for i in hit], file=sys.stderr)
    return out


def dump():
    if os.path.exists(os.path.join(DUMPD, 'clubs.csv.gz')):
        return
    os.makedirs(DUMPD, exist_ok=True)
    with urllib.request.urlopen(DUMP_URL, timeout=600) as r:
        z = zipfile.ZipFile(io.BytesIO(r.read()))
    for f in z.namelist():
        if f.endswith('.csv.gz'):
            with open(os.path.join(DUMPD, os.path.basename(f)), 'wb') as w:
                w.write(z.read(f))


def tm_map(names):
    """{Transfermarkt name: club id}"""
    import pandas as pd
    dump()
    rd = lambda f, **kw: pd.read_csv(os.path.join(DUMPD, f + '.csv.gz'), **kw)
    ids, games = collections.defaultdict(set), collections.Counter()
    c = rd('clubs', usecols=['club_id', 'name'])
    for i, n in zip(c.club_id, c.name):
        ids[n].add(int(i))
    g = rd('games', usecols=['season', 'home_club_id', 'away_club_id', 'home_club_name', 'away_club_name'])
    p = rd('players', usecols=['current_club_id', 'current_club_name'])
    t = rd('transfers', usecols=['from_club_id', 'to_club_id', 'from_club_name', 'to_club_name'])
    for df, a, b in [(g, 'home_club_id', 'home_club_name'), (g, 'away_club_id', 'away_club_name'),
                     (p, 'current_club_id', 'current_club_name'), (t, 'from_club_id', 'from_club_name'),
                     (t, 'to_club_id', 'to_club_name')]:
        x = df[[a, b]].dropna()
        for i, n in zip(x[a], x[b]):
            ids[n].add(int(i))
    recent = collections.Counter()
    for col in ('home_club_id', 'away_club_id'):
        games.update(int(i) for i in g[col].dropna())
        recent.update(int(i) for i in g.loc[g.season >= g.season.max() - 2, col].dropna())
    out = {}
    for n in names:
        if n in ids:
            out[n] = max(ids[n], key=lambda i: (recent[i], games[i], -i))
        else:
            print('no Transfermarkt club for', n, file=sys.stderr)
    return out


def save(url, path):
    if os.path.exists(path):
        return True
    b = get(url, raw=True)
    if not b:
        return False
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(b)).convert('RGBA')
        bb = im.getbbox()
        if bb:
            im = im.crop(bb)
        im.thumbnail((64, 64))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        im.save(path, optimize=True)
        return True
    except Exception:
        return False


def main():
    war = json.load(open(os.path.join(DATA, 'soccer_war.json')))
    names = {p['team']: p['lg'] for p in war['players']}
    sd = os.path.join(ROOT, 'static', 'data', 'soccer-war')       # every past season the players tables can show
    for f in sorted(os.listdir(sd)) if os.path.isdir(sd) else []:
        if f.endswith('.json') and f[:-5].isdigit():
            names.update({p['team']: p['lg'] for p in json.load(open(os.path.join(sd, f))).get('players', [])})
    bp = os.path.join(DATA, 'backup_soccer.json')
    if os.path.exists(bp):
        names.update({r['team']: r['lg'] for r in json.load(open(bp))['rows']})
    espn = espn_map(names)
    pr = json.load(open(os.path.join(DATA, 'soccer_prospects.json')))
    clubs = sorted({r['club'] for r in pr['board'] + pr.get('past', []) if r.get('club')})
    tm = tm_map(clubs)

    with ThreadPoolExecutor(12) as ex:
        ok_e = dict(zip(espn, ex.map(lambda i: save(f'https://a.espncdn.com/i/teamlogos/soccer/500/{i}.png',
                                                    os.path.join(IMG, f'{i}.png')), espn.values())))
        ok_t = dict(zip(tm, ex.map(lambda i: save(f'https://tmssl.akamaized.net/images/wappen/head/{i}.png',
                                                  os.path.join(IMG, 'tm', f'{i}.png')), tm.values())))
    out = {'espn': {n: i for n, i in sorted(espn.items()) if ok_e[n]},
           'tm': {n: i for n, i in sorted(tm.items()) if ok_t[n]}}
    keep = {f'{i}.png' for i in out['tm'].values()}
    for f in os.listdir(os.path.join(IMG, 'tm')):
        if f not in keep:
            os.remove(os.path.join(IMG, 'tm', f))
    json.dump(out, open(OUT, 'w'), ensure_ascii=False, separators=(',', ':'))
    print(f"{len(out['espn'])}/{len(names)} Understat names, {len(out['tm'])}/{len(clubs)} Transfermarkt names")


if __name__ == '__main__':
    main()
