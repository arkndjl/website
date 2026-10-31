#!/usr/bin/env python3
"""Nationality flags and headshots for the soccer tables (SOCCER and SOCCER PROSPECTS ARKBOARDs).

    python3 scripts/soccer_faces.py                # attach nat / ph / fv to this season's big-five player file
    python3 scripts/soccer_faces.py --prospects    # attach nat / ph to the soccer prospects board
    python3 scripts/soccer_faces.py --countries    # rebuild data/soccer_countries.json (needs the Transfermarkt
                                                   # dump in scripts/.cache/soccer_prospects/dump and pycountry)
    python3 scripts/soccer_faces.py --flags        # fetch any missing flag image into static/img/flags/<iso2>.png

Sources (both free, no key):
  - Transfermarkt's JSON API (tmapi-alpha, /player/<id>): nationality (a Transfermarkt country id) and portrait. The
    prospects board is keyed by Transfermarkt id; big-five players reach it through soccer_mv's Understat ->
    Transfermarkt link. Profiles are cached in scripts/data/soccer_faces.json.gz (tm id -> [Transfermarkt country
    id, portrait file, day fetched]) and refreshed after 30 days. Portraits load from Transfermarkt's image host (CORS open, so the GFX cards
    can draw them); Transfermarkt's grey placeholder counts as no photo.
  - FotMob (the other leagues' player stats, scripts/soccer_more.py): a three-letter country code on every stat row
    (FIFA-style, mapped to ISO 3166 here) and its player images by FotMob id.
Flags are ISO 3166 PNGs from flagcdn.com (England, Scotland, Wales, Northern Ireland as gb-eng etc.), saved once under
static/img/flags/. A row's fields: nat = iso2 flag code, ph = Transfermarkt portrait file, fph = FotMob player id;
big-five rows also take fv (and prov) from the prospects board when the player is on it.
"""
import datetime as dt
import gzip
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import soccer_data as D  # noqa: E402

ROOT = os.path.dirname(HERE)
CTRY = os.path.join(ROOT, 'data', 'soccer_countries.json')
FACES = os.path.join(HERE, 'data', 'soccer_faces.json.gz')            # big-five players (soccer.yml)
FACES_U22 = os.path.join(HERE, 'data', 'soccer_faces_u22.json.gz')    # the prospects board (soccer-prospects.yml)
LINK = os.path.join(HERE, 'data', 'soccer_mv_link.json.gz')
DUMP = os.path.join(HERE, '.cache', 'soccer_prospects', 'dump')
FLAGS = os.path.join(ROOT, 'static', 'img', 'flags')
WAR = os.path.join(ROOT, 'static', 'data', 'soccer-war')
MORE = os.path.join(ROOT, 'static', 'data', 'soccer-more')
PROS = os.path.join(ROOT, 'data', 'soccer_prospects.json')
TMAPI = 'https://tmapi-alpha.transfermarkt.technology'
PORTRAIT = 'https://img.a.transfermarkt.technology/portrait/big/'

# country names pycountry doesn't read (Transfermarkt's spellings), and the four home nations
NAME_FIX = {'England': 'gb-eng', 'Scotland': 'gb-sct', 'Wales': 'gb-wls', 'Northern Ireland': 'gb-nir',
            'Korea, South': 'kr', 'Korea, North': 'kp', "Cote d'Ivoire": 'ci', "Côte d'Ivoire": 'ci', 'DR Congo': 'cd',
            'Congo': 'cg', 'Kosovo': 'xk', 'Curacao': 'cw', 'Turkey': 'tr', 'Türkiye': 'tr', 'Russia': 'ru',
            'Iran': 'ir', 'Syria': 'sy', 'Venezuela': 've', 'Bolivia': 'bo', 'Tanzania': 'tz', 'Moldova': 'md',
            'Vietnam': 'vn', 'Laos': 'la', 'Cape Verde': 'cv', 'Czech Republic': 'cz', 'Chinese Taipei': 'tw',
            'Palestine': 'ps', 'Hongkong': 'hk', 'Hong Kong': 'hk', 'The Gambia': 'gm', 'Gambia': 'gm',
            'Bosnia-Herzegovina': 'ba', 'St. Kitts & Nevis': 'kn', 'St. Lucia': 'lc', 'Southern Sudan': 'ss',
            'South Sudan': 'ss', 'Faroe Islands': 'fo', 'Swaziland': 'sz', 'Eswatini': 'sz', 'Macedonia': 'mk',
            'North Macedonia': 'mk', 'United States': 'us', 'Netherlands Antilles': 'cw', 'Bahamas': 'bs',
            'The Bahamas': 'bs', 'East Timor': 'tl', 'Timor-Leste': 'tl', 'Kyrgyzstan': 'kg', 'Korea': 'kr',
            'Guadeloupe': 'gp', 'Martinique': 'mq', 'French Guiana': 'gf', 'Réunion': 're', 'Mayotte': 'yt',
            'St. Vincent & Grenadinen': 'vc', 'Neukaledonien': 'nc', 'Tahiti': 'pf', 'Saint-Martin': 'mf',
            'Sint Maarten': 'sx', 'Bonaire': 'bq'}
# FIFA codes that aren't the ISO alpha-3 (FotMob's ParticipantCountryCode)
FIFA = {'ENG': 'gb-eng', 'SCO': 'gb-sct', 'WAL': 'gb-wls', 'NIR': 'gb-nir', 'GER': 'de', 'NED': 'nl', 'POR': 'pt',
        'SUI': 'ch', 'DEN': 'dk', 'CRO': 'hr', 'GRE': 'gr', 'BUL': 'bg', 'SLO': 'si', 'LAT': 'lv', 'LIT': 'lt',
        'ROM': 'ro', 'KSA': 'sa', 'UAE': 'ae', 'IRI': 'ir', 'RSA': 'za', 'NGA': 'ng', 'ALG': 'dz', 'ANG': 'ao',
        'CGO': 'cg', 'COD': 'cd', 'CHA': 'td', 'CRC': 'cr', 'CHI': 'cl', 'PAR': 'py', 'URU': 'uy', 'HAI': 'ht',
        'HON': 'hn', 'GUA': 'gt', 'SLV': 'sv', 'TRI': 'tt', 'ZAM': 'zm', 'ZIM': 'zw', 'MAD': 'mg', 'MTN': 'mr',
        'GAM': 'gm', 'GUI': 'gn', 'BUR': 'bf', 'TOG': 'tg', 'NIG': 'ne', 'SUD': 'sd', 'LBY': 'ly', 'KUW': 'kw',
        'OMA': 'om', 'BHR': 'bh', 'QAT': 'qa', 'PHI': 'ph', 'MAS': 'my', 'INA': 'id', 'VIE': 'vn', 'MYA': 'mm',
        'TPE': 'tw', 'CAM': 'kh', 'NEP': 'np', 'SRI': 'lk', 'BAN': 'bd', 'BHU': 'bt', 'MGL': 'mn', 'KOS': 'xk',
        'CUW': 'cw', 'SUR': 'sr', 'GRN': 'gd', 'BAR': 'bb', 'BER': 'bm', 'ARU': 'aw', 'CAY': 'ky', 'PUR': 'pr',
        'SKN': 'kn', 'LCA': 'lc', 'VIN': 'vc', 'ATG': 'ag', 'DMA': 'dm', 'BAH': 'bs', 'ANT': 'ag', 'GRL': 'gl',
        'FRO': 'fo', 'EQG': 'gq', 'GBS': 'gw', 'CPV': 'cv', 'STP': 'st', 'CTA': 'cf', 'BOT': 'bw', 'LES': 'ls',
        'SWZ': 'sz', 'MWI': 'mw', 'MOZ': 'mz', 'TAN': 'tz', 'BDI': 'bi', 'SEY': 'sc', 'MRI': 'mu', 'COM': 'km',
        'SOM': 'so', 'DJI': 'dj', 'ERI': 'er', 'ETH': 'et', 'LBR': 'lr', 'SLE': 'sl', 'TAH': 'pf', 'NCL': 'nc',
        'FIJ': 'fj', 'VAN': 'vu', 'SOL': 'sb', 'SAM': 'ws', 'TGA': 'to', 'PNG': 'pg', 'GUM': 'gu', 'MAC': 'mo',
        'PLE': 'ps', 'KGZ': 'kg', 'TJK': 'tj', 'TKM': 'tm', 'ARM': 'am', 'MNE': 'me', 'SRB': 'rs'}


def ctry():
    try:
        return json.load(open(CTRY))
    except (OSError, ValueError):
        return {'tm': {}, 'name': {}}


def faces(path=FACES):
    try:
        return D.load(path)
    except OSError:
        return {}


def build_countries():
    """Transfermarkt country id -> iso2: the dump's countries and national teams by name, then each cached profile's
    nationality id against the dump's citizenship name for the same player"""
    import csv, io
    import pycountry

    def iso(n):
        if n in NAME_FIX:
            return NAME_FIX[n]
        try:
            return pycountry.countries.lookup(n).alpha_2.lower()
        except LookupError:
            try:
                return pycountry.countries.search_fuzzy(n)[0].alpha_2.lower()
            except LookupError:
                return None

    def rows(f):
        return csv.DictReader(io.TextIOWrapper(gzip.open(os.path.join(DUMP, f)), 'utf-8'))
    names = {}
    for f in ('countries.csv.gz', 'national_teams.csv.gz'):
        for r in rows(f):
            names[r['country_id']] = r['country_name']
    cit = {r['player_id']: r['country_of_citizenship'] for r in rows('players.csv.gz') if r.get('country_of_citizenship')}
    from collections import Counter, defaultdict
    vote = defaultdict(Counter)
    for pid, v in {**faces(FACES_U22), **faces()}.items():
        if v[0] and pid in cit:
            vote[str(v[0])][cit[pid]] += 1
    for k, c in vote.items():
        names.setdefault(k, c.most_common(1)[0][0])
    tm, nm = {}, {}
    for k, n in names.items():
        i = iso(n)
        if i:
            tm[k] = i
            nm.setdefault(i, n)
    for code, i in FIFA.items():
        nm.setdefault(i, (pycountry.countries.get(alpha_2=i.upper()).name if '-' not in i and pycountry.countries.get(alpha_2=i.upper()) else code))
    a3 = {c.alpha_3: c.alpha_2.lower() for c in pycountry.countries}
    json.dump({'tm': tm, 'name': nm, 'a3': a3}, open(CTRY, 'w'), sort_keys=True, ensure_ascii=False)
    print('countries', len(tm), 'tm ids,', len(nm), 'flags')


def fm_iso(code, C=None):
    """FotMob's three-letter code -> iso2"""
    if not code:
        return None
    c = code.upper()
    if c in FIFA:
        return FIFA[c]
    return (C or ctry()).get('a3', {}).get(c)


def fetch_flags(codes):
    os.makedirs(FLAGS, exist_ok=True)
    todo = [c for c in sorted(codes) if c and not os.path.exists(os.path.join(FLAGS, f'{c}.png'))]

    def one(c):
        b = D.get(f'https://flagcdn.com/h20/{c}.png', raw=True)
        if b and b[:4] == b'\x89PNG':
            open(os.path.join(FLAGS, f'{c}.png'), 'wb').write(b)
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(one, todo))
    if todo:
        print('flags', len(todo), 'fetched')


def refresh(ids, days=30, path=FACES):
    """Transfermarkt profiles for ids not cached (or older than days): [country id, portrait file, day]"""
    F = faces(path)
    today = dt.date.today().isoformat()
    lim = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    todo = [str(i) for i in ids if i and (str(i) not in F or F[str(i)][2] < lim)]

    def one(i):
        return i, D.get(f'{TMAPI}/player/{i}', tries=2, headers={'Accept': 'application/json'})
    with ThreadPoolExecutor(10) as ex:
        for i, r in ex.map(one, todo):
            d = (r or {}).get('data')
            if not d:
                continue
            nat = str((((d.get('nationalityDetails') or {}).get('nationalities') or {}).get('nationalityId')) or '')
            url = d.get('portraitUrl') or ''
            ph = url[len(PORTRAIT):] if url.startswith(PORTRAIT) and 'default' not in url else None
            F[i] = [nat or None, ph, today]
    if todo:
        D.save(path, F)
    print('faces', len(todo), 'fetched of', len(ids), flush=True)
    return F


def put(o, f, C):
    if f:
        if C.get(str(f[0])):
            o['nat'] = C[str(f[0])]
        if f[1]:
            o['ph'] = f[1]


def attach_war(F, C, link, S):
    fn = os.path.join(WAR, f'{S}.json')
    if not os.path.exists(fn):
        return set()
    J = json.load(open(fn))
    try:
        fv = {str(o['id']): (o['fv'], o.get('prov')) for o in json.load(open(PROS))['board']}
    except (OSError, KeyError, ValueError):
        fv = {}
    for o in J['players']:
        tm = str(link.get(o['p']) or '')
        put(o, F.get(tm), C)
        o.pop('fv', None); o.pop('prov', None)
        if tm in fv:                     # under 22: the soccer prospects board's FV
            o['fv'] = fv[tm][0]
            if fv[tm][1]:
                o['prov'] = 1
    open(fn, 'w').write(json.dumps(J, separators=(',', ':'), allow_nan=False))
    return {o.get('nat') for o in J['players']}


def attach_prospects(F, C):
    if not os.path.exists(PROS):
        return set()
    J = json.load(open(PROS))
    for o in J['board'] + J.get('past', []):        # past prospects: grade-vs-outcome table
        put(o, F.get(str(o.get('id'))), C)
    open(PROS, 'w').write(json.dumps(J, separators=(',', ':'), allow_nan=False))
    return {o.get('nat') for o in J['board']}


def main(which):
    """which: 'war' (this season's big-five file, the other leagues' flags) or 'prospects' (the board)"""
    C = ctry()['tm']
    codes = set()
    if which == 'war':
        S = D.current_season()
        link = (D.load(LINK) if os.path.exists(LINK) else {}).get('p', {})
        fn = os.path.join(WAR, f'{S}.json')
        ids = {link.get(o['p']) for o in json.load(open(fn))['players']} if os.path.exists(fn) else set()
        F = refresh(sorted(str(i) for i in ids if i))
        codes |= attach_war(F, C, link, S)
        for fm in (os.path.join(MORE, f) for f in (os.listdir(MORE) if os.path.isdir(MORE) else [])):
            codes |= {o.get('nat') for o in json.load(open(fm))['players']}
    else:
        J = json.load(open(PROS)) if os.path.exists(PROS) else {}
        ids = {o.get('id') for o in J.get('board', []) + J.get('past', [])}
        F = refresh(sorted(str(i) for i in ids if i), path=FACES_U22)
        codes |= attach_prospects(F, C)
    fetch_flags(codes - {None})


if __name__ == '__main__':
    if '--countries' in sys.argv:
        build_countries()
    elif '--flags' in sys.argv:
        fetch_flags(set(ctry()['tm'].values()) | set(FIFA.values()))
    else:
        main('prospects' if '--prospects' in sys.argv else 'war')
