#!/usr/bin/env python3
"""Tennis data layer (TENNIS ARKBOARD and the tennis prospects board): every ATP and WTA singles match on one set of
player ids, from free sources.

    python3 scripts/tennis_data.py            # refresh the weekly tour feed and ESPN, rebuild the match history
    python3 scripts/tennis_data.py --hist     # (re)download the Sackmann archive (frozen, runs once)
    python3 scripts/tennis_data.py --export   # also write the full history for other threads to
                                              # /mnt/project-files/tennis/matches.csv.gz (+ players.json.gz)

Sources (all free, no key):
  - Jeff Sackmann's tennis_atp / tennis_wta (the GitHub repos went offline in mid-2026; the Hugging Face mirror
    datasets/Aneeshers/tennis-sackmann-archive keeps them through early June 2026): tour, Challenger, tour
    qualifying, Futures (ATP) and ITF + qualifying (WTA) matches with serve statistics, and player bios (dob, hand,
    height, IOC country). Frozen: downloaded once into scripts/.cache/tennis/sack.
  - minmaxxxer/atp-wta-matches-with-odds (Hugging Face, CC BY 4.0, "Min Maxxxer / Tennis Odds Actor"): ATP and WTA
    tour-level main draws from 2025 in Sackmann's layout, updated every Monday, with serve statistics and the
    bookmakers' no-vig opening and closing win probability. Its player ids are Flashscore's; they're joined to
    Sackmann's by the matches both sources hold (Jan 2025 to May 2026), then by name (scripts/names.py, country as
    the team, age within two years) for players new to the tour after that.
  - ESPN's public tennis scoreboard (site.api.espn.com/apis/site/v2/sports/tennis/<atp|wta>/scoreboard?dates=):
    this week's draws and order of play, ESPN athlete ids (headshots) and flags. ESPN ids join ours by the matches
    both hold, then by name + country.

Player ids: "a<Sackmann id>" (ATP), "w<Sackmann id>" (WTA); a player the archive never saw takes "afs<Flashscore id>" /
"wfs<...>". History rows (scripts/.cache/tennis/hist.json.gz, rebuilt each run; the players beside it) are lists in
COLS order, oldest first. The committed outputs are the id joins (scripts/data/tennis_idmap.json.gz) and, from
scripts/tennis_model.py, every active player's current ratings (scripts/data/tennis_ratings.json.gz).
Levels: G Grand Slam, M Masters / WTA 1000, F tour finals, A ATP 250-500 / WTA 250-500, D team events (Davis, BJK,
United Cup), O Olympics, C Challenger / WTA 125, Q tour qualifying, S Futures / ITF.
"""
import csv
import datetime as dt
import gzip
import io
import json
import os
import re
import sys
import time
import urllib.request
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import names  # noqa: E402

CACHE = os.path.join(HERE, '.cache', 'tennis')
SACK_DIR = os.path.join(CACHE, 'sack')
MM_DIR = os.path.join(CACHE, 'mm')
ESPN_DIR = os.path.join(CACHE, 'espn')
DATA = os.path.join(HERE, 'data')
HIST = os.path.join(CACHE, 'hist.json.gz')                 # rebuilt each run (22 MB: kept out of git)
PLAYERS = os.path.join(CACHE, 'players.json.gz')
IDMAP = os.path.join(DATA, 'tennis_idmap.json.gz')
ESPN_CUR = os.path.join(CACHE, 'espn_current.json.gz')
EXPORT = '/mnt/project-files/tennis'

SACK = 'https://huggingface.co/datasets/Aneeshers/tennis-sackmann-archive/resolve/main/'
MM = 'https://huggingface.co/datasets/minmaxxxer/atp-wta-matches-with-odds/resolve/main/'
ESPN = 'https://site.api.espn.com/apis/site/v2/sports/tennis/'
FIRST = 2005                       # history starts here (Elo burn-in before the 2010 tuning window)
MM_FIRST = 2025
SACK_CUT = 20260531                # the archive's tour-level files end with Roland Garros 2026 (tourney_date 20260525)

COLS = ['d', 'tour', 'lv', 'sf', 'rd', 'bo', 'tid', 'w', 'l', 'score', 'ws', 'ls', 'wr', 'lr', 'pc', 'po']
# ws / ls: [svpt, 1stIn, 1stWon, 2ndWon, SvGms, bpSaved, bpFaced, ace, df] of the winner / loser, or None
# pc / po: winner's no-vig closing / opening win probability (minmaxxxer), or None
STAT = ['svpt', '1stIn', '1stWon', '2ndWon', 'SvGms', 'bpSaved', 'bpFaced', 'ace', 'df']
RORD = {'Q1': 0, 'Q2': 1, 'Q3': 2, 'Q4': 3, 'ER': 3, 'R128': 4, 'R64': 5, 'R32': 6, 'R16': 7, 'RR': 7, 'QF': 8,
        'SF': 9, 'BR': 9.5, 'F': 10}
SURF = {'Hard': 'H', 'Clay': 'C', 'Grass': 'G', 'Carpet': 'H'}

# IOC codes that aren't ISO 3166 alpha-3 (on top of soccer_faces.FIFA, which shares most of them)
IOC_FIX = {'GBR': 'gb', 'MON': 'mc', 'NGR': 'ng', 'LIB': 'lb', 'ISV': 'vi', 'IVB': 'vg', 'BRU': 'bn', 'SIN': 'sg',
           'BIZ': 'bz', 'GEQ': 'gq', 'ESA': 'sv', 'LBA': 'ly', 'HKG': 'hk', 'KOR': 'kr', 'PRK': 'kp', 'ROU': 'ro',
           'ROM': 'ro', 'TPE': 'tw', 'URS': 'ru', 'YUG': 'rs', 'SCG': 'rs', 'TCH': 'cz', 'FRG': 'de', 'GDR': 'de',
           'IRI': 'ir', 'MAS': 'my', 'INA': 'id', 'PUR': 'pr', 'RSA': 'za', 'MGL': 'mn', 'NEP': 'np', 'POC': '',
           'BAH': 'bs', 'BAR': 'bb', 'SAM': 'ws', 'TGA': 'to', 'VAN': 'vu', 'ZIM': 'zw', 'MRI': 'mu', 'TAN': 'tz',
           'ANT': 'ag', 'GUD': 'gp', 'NMI': 'mp', 'ASA': 'as', 'COK': 'ck', 'FSM': 'fm', 'PLW': 'pw', 'BER': 'bm',
           'CAY': 'ky', 'ARU': 'aw', 'AHO': 'cw', 'SKN': 'kn', 'LCA': 'lc', 'VIN': 'vc', 'GRN': 'gd', 'DMA': 'dm'}
_ISO = None


def iso2(code, name=None):
    """an IOC / FIFA / ISO alpha-3 country code (or ESPN's lower-case flag code) as the iso2 flag code, '' if none"""
    global _ISO
    if _ISO is None:
        try:
            import soccer_faces
            fifa = soccer_faces.FIFA
        except Exception:
            fifa = {}
        try:
            c = json.load(open(os.path.join(ROOT, 'data', 'soccer_countries.json')))
        except (OSError, ValueError):
            c = {'a3': {}, 'name': {}}
        _ISO = dict(c.get('a3', {}))
        _ISO.update(fifa)
        _ISO.update(IOC_FIX)
        _ISO['_name'] = {v.lower(): k for k, v in c.get('name', {}).items()}
    k = str(code or '').upper().strip()
    if k in _ISO and k != '_name': return _ISO[k]
    if name: return _ISO['_name'].get(str(name).lower(), '')
    return ''


def get(url, path=None, max_age=None, tries=4):
    """bytes at url, cached at path (re-fetched after max_age seconds; None = forever)"""
    if path and os.path.exists(path) and (max_age is None or time.time() - os.path.getmtime(path) < max_age):
        return open(path, 'rb').read()
    err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'arkboard (arkndjl.net)'})
            with urllib.request.urlopen(req, timeout=60) as r:
                b = r.read()
            if path:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                open(path, 'wb').write(b)
            return b
        except urllib.error.HTTPError as e:
            if e.code == 404: return None
            err = e
        except Exception as e:  # noqa: BLE001
            err = e
        time.sleep(2 ** i)
    if path and os.path.exists(path): return open(path, 'rb').read()
    raise err


def sack_files(year=None):
    out = []
    for y in range(FIRST, dt.date.today().year + 1):
        if year and y != year: continue
        out += [('atp', f'atp_matches_{y}'), ('atp', f'atp_matches_qual_chall_{y}'), ('atp', f'atp_matches_futures_{y}'),
                ('wta', f'wta_matches_{y}'), ('wta', f'wta_matches_qual_itf_{y}')]
    return out


def fetch_sack():
    for tour, f in sack_files() + [('atp', 'atp_players'), ('wta', 'wta_players'), ('atp', 'atp_rankings_current'),
                                   ('wta', 'wta_rankings_current')]:
        p = os.path.join(SACK_DIR, f + '.csv')
        if not os.path.exists(p): get(SACK + f'{tour}/{f}.csv', p)


def _int(x):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return None


def _flt(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def level(tour, raw, rnd, fname):
    raw = (raw or '').strip()
    if rnd and rnd.startswith('Q') and raw not in ('C',) and 'futures' not in fname and raw not in ('15', '25', '35', '50', '75', '100', 'S'):
        return 'Q'
    if tour == 'wta':
        return {'G': 'G', 'PM': 'M', 'P': 'A', 'I': 'A', 'W': 'A', 'F': 'F', 'D': 'D', 'O': 'O', 'C': 'C', 'T1': 'M',
                'T2': 'A', 'T3': 'A', 'T4': 'A', 'T5': 'A'}.get(raw, 'S')
    return {'G': 'G', 'M': 'M', 'A': 'A', 'F': 'F', 'D': 'D', 'O': 'O', 'C': 'C'}.get(raw, 'S')


def _stats(r, p):
    v = [_int(r.get(p + s)) for s in STAT]
    return v if v[0] and v[0] > 0 and None not in v[:5] else None


def read_csv(path):
    if not os.path.exists(path): return []
    with open(path, encoding='utf-8', errors='replace', newline='') as fh:
        return list(csv.DictReader(fh))


def sack_rows():
    """the archive's singles matches as history rows (Sackmann ids), oldest first"""
    out = []
    for tour, f in sack_files():
        p = tour[0]
        for r in read_csv(os.path.join(SACK_DIR, f + '.csv')):
            d, w, l = _int(r.get('tourney_date')), _int(r.get('winner_id')), _int(r.get('loser_id'))
            if not d or not w or not l: continue
            rnd = (r.get('round') or '').strip()
            sc = (r.get('score') or '').strip()
            if not sc or 'W/O' in sc.upper() or sc.upper() in ('DEF', 'UNK'): continue      # walkovers carry no information
            out.append([d, tour, level(tour, r.get('tourney_level'), rnd, f), SURF.get(r.get('surface'), 'H'), rnd,
                        _int(r.get('best_of')) or 3, f"{p}{r['tourney_id']}", f'{p}{w}', f'{p}{l}', sc,
                        _stats(r, 'w_'), _stats(r, 'l_'), _int(r.get('winner_rank')), _int(r.get('loser_rank')), None, None,
                        r.get('tourney_name') or ''])
    return out


def sack_players():
    """Sackmann bios: id -> dict(n, ioc, dob, hand, ht)"""
    out = {}
    for tour in ('atp', 'wta'):
        for r in read_csv(os.path.join(SACK_DIR, f'{tour}_players.csv')):
            pid = _int(r.get('player_id'))
            if not pid: continue
            n = f"{(r.get('name_first') or '').strip()} {(r.get('name_last') or '').strip()}".strip()
            out[f'{tour[0]}{pid}'] = {'n': n, 'ioc': r.get('ioc') or '', 'dob': _int(r.get('dob')),
                                      'hand': (r.get('hand') or '')[:1].replace('U', ''), 'ht': _int(r.get('height')),
                                      'wd': (r.get('wikidata_id') or '').strip() or None}
    return out


def mm_rows(refresh=True):
    out = []
    for y in range(MM_FIRST, dt.date.today().year + 1):
        for tour in ('atp', 'wta'):
            f = f'{tour}_matches_{y}.csv'
            p = os.path.join(MM_DIR, f)
            cur = y == dt.date.today().year
            get(MM + f, p, max_age=(6 * 3600 if (cur and refresh) else None))
            for r in read_csv(p):
                r['_tour'] = tour
                out.append(r)
    return out


def mm_name(n):
    """"Sinner J." / "Davidovich Fokina A." -> "J. Sinner" / "A. Davidovich Fokina\""""
    n = (n or '').strip()
    m = re.match(r'^(.*?\S)\s+((?:[A-Z][a-z]{0,2}[.-]\s?)*[A-Z][a-z]{0,2}\.)$', n)
    return f'{m.group(2).strip()} {m.group(1)}' if m else n


def _last(n):
    k = names.key(n).split()
    return k[-1] if k else ''


EAST = {'CHN', 'TPE', 'HKG', 'KOR', 'PRK', 'MAC'}    # the archive writes these surname first ("Bu Yunchaokete")


def lasts(b):
    """the surname keys a bio can go by: the last word, and the first for a surname-first name"""
    k = names.key(b.get('n', '')).split()
    if not k: return {''}
    return {k[-1], k[0]} if b.get('ioc') in EAST else {k[-1]}


def swapped(b):
    """a surname-first bio's name the other way round (Bu Yunchaokete -> Yunchaokete Bu), else None"""
    if b.get('ioc') not in EAST: return None
    t = b.get('n', '').split()
    return ' '.join(t[1:] + t[:1]) if len(t) >= 2 else None


def join_mm(sack, mm, bios):
    """minmaxxxer player id -> our id, from the matches both sources hold, then by name + country + age"""
    idx = defaultdict(list)          # (tour, last w, last l) -> sackmann rows (tour level, 2025+)
    for r in sack:
        if r[0] < 20241215 or r[2] in ('S', 'C', 'Q'): continue
        for a in lasts(bios.get(r[7], {})):
            for b in lasts(bios.get(r[8], {})): idx[(r[1], a, b)].append(r)
    votes = defaultdict(Counter)
    hit = {}
    for i, r in enumerate(mm):
        d = _int(r.get('tourney_date'))
        if not d or d > SACK_CUT: continue
        wn, ln = mm_name(r['winner_name']), mm_name(r['loser_name'])
        c = [s for s in idx.get((r['_tour'], _last(wn), _last(ln)), [])
             if abs((dt.date(s[0] // 10000, s[0] // 100 % 100, s[0] % 100) - dt.date(d // 10000, d // 100 % 100, d % 100)).days) <= 9]
        if len(c) != 1: continue
        s = c[0]
        hit[i] = s
        votes[r['winner_id']][s[7]] += 1
        votes[r['loser_id']][s[8]] += 1
    idmap = {k: v.most_common(1)[0][0] for k, v in votes.items()}
    # the rest by name: country as the team, birth year within two years of the age the feed gives
    pool = {}
    for pid, b in bios.items():
        pool.setdefault(pid[0], []).append(dict(b, id=pid, team=iso2(b['ioc'])))
        if swapped(b): pool[pid[0]].append(dict(b, n=swapped(b), id=pid, team=iso2(b['ioc'])))
    ms = {t: names.Matcher(rows, name='n', team='team', cls='dob') for t, rows in pool.items()}
    for r in mm:
        for side in ('winner', 'loser'):
            fid = r[f'{side}_id']
            if not fid or fid in idmap: continue
            t = r['_tour'][0]
            age, d = _flt(r.get(f'{side}_age')), _int(r.get('tourney_date')) or 0
            yob = (d // 10000 - age) if age else None
            fits = (lambda dob, yob=yob: yob is None or not dob or abs(dob // 10000 + (dob // 100 % 100) / 12 - yob) <= 2)
            nat = iso2(r.get(f'{side}_ioc'), r.get(f'{side}_country'))
            row = None
            for team in ([nat] if nat else ['ru', 'by']):        # no country: a neutral (Russian or Belarusian)
                row, how = ms[t].find(mm_name(r[f'{side}_name']), team=team, cls=fits)
                if row: break
            idmap[fid] = row['id'] if row else f'{t}fs{fid}'
    return idmap, hit


def mm_bio(r, side):
    return {'n': mm_name(r[f'{side}_name']), 'ioc': r.get(f'{side}_ioc') or '', 'dob': None,
            'hand': (r.get(f'{side}_hand') or '')[:1], 'ht': _int(r.get(f'{side}_ht'))}


def mm_level(r):
    lv = (r.get('tourney_level') or 'A').strip()
    return lv if lv in ('G', 'M', 'A', 'F', 'D', 'O') else 'A'


# ---------------------------------------------------------------- ESPN
def espn_day(league, day, max_age=None):
    p = os.path.join(ESPN_DIR, league, f'{day}.json')
    b = get(f'{ESPN}{league}/scoreboard?dates={day}', p, max_age=max_age)
    try:
        return json.loads(b) if b else {}
    except ValueError:
        return {}


def espn_comps(sb, league):
    """singles competitions on a scoreboard: dict(eid, tn, tid, date, rd, tour, state, comp, players=[(espn id, name,
    flag code, country, winner, sets)])"""
    out = []
    for e in sb.get('events', []):
        for g in e.get('groupings', []):
            gn = g.get('grouping', {}).get('displayName', '')
            if 'Singles' not in gn: continue
            tour = 'wta' if gn.startswith("Women") else 'atp'
            for c in g.get('competitions', []):
                ps = []
                for x in c.get('competitors', []):
                    a = x.get('athlete') or {}
                    fl = (a.get('flag') or {})
                    code = os.path.basename(fl.get('href', '')).split('.')[0]
                    ps.append((str(x.get('id')), a.get('displayName') or '', code, fl.get('alt') or '', bool(x.get('winner')),
                               [int(s.get('value', 0)) for s in x.get('linescores', [])], x.get('order')))
                if len(ps) != 2: continue
                st = c.get('status', {}).get('type', {})
                out.append({'eid': e.get('id'), 'tn': e.get('name', ''), 'tid': str(c.get('tournamentId') or e.get('id', '').split('-')[0]),
                            'date': c.get('date') or c.get('startDate'), 'rd': (c.get('round') or {}).get('displayName', ''),
                            'tour': tour, 'state': st.get('state'), 'done': bool(st.get('completed')), 'detail': st.get('shortDetail', ''),
                            'id': str(c.get('id')), 'court': (c.get('venue') or {}).get('court', ''),
                            'city': (c.get('venue') or {}).get('fullName', ''), 'players': ps,
                            'note': ' '.join(n.get('text', '') for n in c.get('notes', []))})
    return out


def espn_range(start, end, step=3, recent_days=10):
    """every ESPN singles competition between two dates (scoreboards every `step` days; each lists whole events)"""
    seen, out = set(), []
    today = dt.date.today()
    d = start
    while d <= end:
        for lg in ('atp', 'wta'):
            age = 3 * 3600 if (today - d).days < recent_days else None
            for c in espn_comps(espn_day(lg, d.strftime('%Y%m%d'), max_age=age), lg):
                if c['id'] in seen: continue
                seen.add(c['id'])
                out.append(c)
        d += dt.timedelta(days=step)
    return out


def espn_round(rd):
    rd = (rd or '').lower()
    if 'qualif' in rd:
        m = re.search(r'(\d)', rd)
        return f"Q{m.group(1) if m else 1}"
    if 'final' == rd or rd == 'finals' or rd.endswith(' final') and 'semi' not in rd and 'quarter' not in rd: return 'F'
    if 'semi' in rd: return 'SF'
    if 'quarter' in rd: return 'QF'
    if 'round robin' in rd or 'group' in rd: return 'RR'
    m = re.search(r'round (\d)', rd)
    return f'R{m.group(1)}' if m else rd


def join_espn(comps, hist, bios):
    """ESPN athlete id -> our id: the ESPN matches that are also history rows (same week, both last names), then by
    name with the flag's country as the team"""
    idx = defaultdict(list)
    for r in hist:
        if r[0] < 20241215 or r[2] in ('S',): continue
        for a in lasts(bios.get(r[7], {})):
            for b in lasts(bios.get(r[8], {})): idx[(r[1], frozenset((a, b)))].append(r)
    votes = defaultdict(Counter)
    kind = defaultdict(Counter)       # ESPN tournament id -> (level, surface) of the history rows it matched
    for c in comps:
        if not c['done']: continue
        (i1, n1, *_), (i2, n2, *_) = c['players']
        try:
            cd = dt.date.fromisoformat(c['date'][:10])
        except (TypeError, ValueError):
            continue
        cand = [r for r in idx.get((c['tour'], frozenset((_last(n1), _last(n2)))), [])
                if -3 <= (cd - dt.date(r[0] // 10000, r[0] // 100 % 100, r[0] % 100)).days <= 16]
        if len(cand) != 1: continue
        r = cand[0]
        w1 = c['players'][0][4]
        win, los = (i1, i2) if w1 else (i2, i1)
        if not (c['players'][0][4] or c['players'][1][4]): continue
        votes[win][r[7]] += 1
        votes[los][r[8]] += 1
        if r[2] != 'Q': kind[c['tid']][(r[2], r[3])] += 1
    idmap = {k: v.most_common(1)[0][0] for k, v in votes.items()}
    pool = defaultdict(list)
    active = {r[7] for r in hist if r[0] >= 20230101} | {r[8] for r in hist if r[0] >= 20230101}
    for pid in active:
        b = bios.get(pid)
        if b: pool[pid[0]].append(dict(b, id=pid, team=iso2(b['ioc'])))
        if b and swapped(b): pool[pid[0]].append(dict(b, n=swapped(b), id=pid, team=iso2(b['ioc'])))
    ms = {t: names.Matcher(rows, name='n', team='team') for t, rows in pool.items()}
    for c in comps:
        t = c['tour'][0]
        for (eid, n, code, alt, *_r) in c['players']:
            if eid in idmap or t not in ms: continue
            row, how = ms[t].find(n, team=iso2(code, alt) or None)
            if row: idmap[eid] = row['id']
    return idmap, {k: v.most_common(1)[0][0] for k, v in kind.items()}


def espn_score(c):
    """(winner's side first) score string from ESPN's set linescores, and who won (0 / 1), or (None, None)"""
    a, b = c['players']
    if a[4] == b[4]: return None, None
    wi = 0 if a[4] else 1
    w, l = c['players'][wi][5], c['players'][1 - wi][5]
    sets = [f'{x}-{y}' for x, y in zip(w, l)]
    if not sets: return None, None
    note = c.get('note', '').lower()
    if 'walkover' in note or 'w/o' in note: return None, None
    ret = ' RET' if ('retire' in note or 'ret.' in note or 'ret)' in note) else ''
    return ' '.join(sets) + ret, wi


RDAY = {'Q1': -3, 'Q2': -2, 'Q3': -1, 'Q4': -1, 'R128': 0, 'R64': 1, 'R32': 2, 'R16': 4, 'RR': 3, 'QF': 5, 'SF': 6,
        'BR': 6, 'F': 7}      # tennis_model.RDAY


def espn_rows(comps, eid, kind, hist):
    """finished ESPN singles matches the history doesn't hold yet (the days since the weekly feed's last update)"""
    last = {}
    have = set()
    for r in hist:
        last[r[1]] = max(last.get(r[1], 0), r[0])
        if r[0] >= 20260801: have.add((r[1], frozenset((r[7], r[8]))))
    out = []
    for c in comps:
        if not c['done'] or not c['date']: continue
        d0 = dt.date.fromisoformat(c['date'][:10])
        lt = last.get(c['tour'])
        if lt and d0 <= dt.date(lt // 10000, lt // 100 % 100, lt % 100) - dt.timedelta(days=7): continue
        sc, wi = espn_score(c)
        if sc is None: continue
        w, l = eid.get(c['players'][wi][0]), eid.get(c['players'][1 - wi][0])
        if not w or not l: continue
        key = (c['tour'], frozenset((w, l)))
        if key in have: continue
        have.add(key)
        lv, sf = kind.get(c['tid'], ('A', 'H'))
        rd = espn_round(c['rd'])
        # history rows carry the tournament's start date and the model adds the round's day (tennis_model.RDAY):
        # back the match date off by that offset so the model's day is the day it was played
        d = int((d0 - dt.timedelta(days=RDAY.get(rd, 2))).strftime('%Y%m%d'))
        if rd.startswith('Q'): lv = 'Q'
        out.append([d, c['tour'], lv, sf, rd, 5 if (lv == 'G' and c['tour'] == 'atp' and not rd.startswith('Q')) else 3,
                    f"{c['tour'][0]}e{c['eid']}", w, l, sc, None, None, None, None, None, None, c['tn']])
    return out


def rankings(players):
    """pid -> {rank, pts}: ESPN's top 150 (with points), Tennis Abstract's current ranks by name for the rest"""
    out = {}
    im = {}
    try:
        with gzip.open(IDMAP, 'rt') as fh: im = json.load(fh).get('espn', {})
    except (OSError, ValueError):
        pass
    for tour in ('atp', 'wta'):
        try:
            d = json.loads(get(f'{ESPN}{tour}/rankings', os.path.join(ESPN_DIR, f'rankings_{tour}.json'), max_age=6 * 3600) or b'{}')
            for x in d['rankings'][0]['ranks']:
                pid = im.get(str(x['athlete']['id']))
                if pid: out[pid] = {'rank': int(x['current']), 'pts': int(x.get('points') or 0)}
        except Exception as e:  # noqa: BLE001
            print('ESPN rankings', tour, e)
        try:
            b = get(f'https://www.tennisabstract.com/jsplayers/curr_rank_{tour}.js', os.path.join(CACHE, f'ta_rank_{tour}.js'), max_age=6 * 3600)
            js = b.decode('utf-8', 'replace')
            ranks = json.loads(js[js.index('{'):js.rindex('}') + 1])
        except Exception as e:  # noqa: BLE001
            print('Tennis Abstract ranks', tour, e)
            continue
        pool = [dict(v, id=k) for k, v in players.items() if k[0] == tour[0]]
        for v in list(pool):
            if v.get('nat') in ('cn', 'tw', 'hk', 'kr', 'kp', 'mo'):
                t = v['n'].split()
                if len(t) >= 2: pool.append(dict(v, n=' '.join(t[1:] + t[:1])))
        m = names.Matcher(pool, name='n', team=None)
        for n, rk in ranks.items():
            row, how = m.find(n)
            if row and row['id'] not in out: out[row['id']] = {'rank': int(rk), 'pts': None}
    return out


# ---------------------------------------------------------------- build
def build(refresh=True):
    fetch_sack()
    bios = sack_players()
    sack = sack_rows()
    mm = mm_rows(refresh)
    idmap, hit = join_mm(sack, mm, bios)
    print(f'archive {len(sack)} matches; feed {len(mm)} matches, {len(hit)} matched to the archive; '
          f'{len(idmap)} feed players ({sum(1 for v in idmap.values() if "fs" in v)} new to the archive)')
    # closing / opening prices onto the archive rows the feed also holds
    for i, s in hit.items():
        r = mm[i]
        s[14], s[15] = _flt(r.get('winner_close_prob')), _flt(r.get('winner_open_prob'))
    hist = [s for s in sack]
    for r in mm:
        d = _int(r.get('tourney_date'))
        if not d or d <= SACK_CUT: continue
        sc = (r.get('score') or '').strip()
        if not sc or 'W/O' in sc.upper(): continue
        w, l = idmap.get(r['winner_id']), idmap.get(r['loser_id'])
        if not w or not l: continue
        for side, pid in (('winner', w), ('loser', l)):
            if pid not in bios: bios[pid] = mm_bio(r, side)
        hist.append([d, r['_tour'], mm_level(r), SURF.get(r.get('surface'), 'H'), (r.get('round') or '').strip(),
                     _int(r.get('best_of')) or 3, f"{r['_tour'][0]}{r['tourney_id']}", w, l, sc, _stats(r, 'w_'), _stats(r, 'l_'),
                     _int(r.get('winner_rank')), _int(r.get('loser_rank')), _flt(r.get('winner_close_prob')),
                     _flt(r.get('winner_open_prob')), r.get('tourney_name') or ''])
    # a bio's missing country / hand / height from the feed
    for r in mm:
        for side in ('winner', 'loser'):
            pid = idmap.get(r[f'{side}_id'])
            b = bios.get(pid)
            if not b: continue
            if not b.get('ioc') and r.get(f'{side}_ioc'): b['ioc'] = r[f'{side}_ioc']
            if not b.get('ht') and _int(r.get(f'{side}_ht')): b['ht'] = _int(r[f'{side}_ht'])
    hist.sort(key=lambda r: (r[0], r[6], RORD.get(r[4], 5)))
    # ESPN: 2025 to next week, for ids (headshots), flags and each ESPN tournament's surface
    today = dt.date.today()
    comps = espn_range(dt.date(2025, 1, 1), today + dt.timedelta(days=7))
    eid, kind = join_espn(comps, hist, bios)
    extra = espn_rows(comps, eid, kind, hist)
    hist += extra
    hist.sort(key=lambda r: (r[0], r[6], RORD.get(r[4], 5)))
    print(f'ESPN {len(comps)} singles matches, {len(eid)} ESPN players joined, {len(extra)} new results this week')
    for e, pid in eid.items():
        if pid in bios: bios[pid]['espn'] = int(e)
    players = {}
    used = {r[7] for r in hist} | {r[8] for r in hist}
    for pid in used:
        b = bios.get(pid) or {}
        players[pid] = {'n': b.get('n', ''), 'nat': iso2(b.get('ioc')), 'dob': b.get('dob'), 'hand': b.get('hand') or None,
                        'ht': b.get('ht'), 'espn': b.get('espn'), 'wd': b.get('wd')}
    with gzip.open(IDMAP, 'wt') as fh: json.dump({'mm': idmap, 'espn': eid}, fh, separators=(',', ':'), sort_keys=True)
    rk = rankings(players)
    for pid, v in rk.items():
        if pid in players: players[pid].update(v)
    print(f'current ranks for {len(rk)} players')
    os.makedirs(DATA, exist_ok=True)
    rows = [r[:16] for r in hist]
    tn = {}
    for r in hist: tn[r[6]] = r[16]
    with gzip.open(HIST, 'wt') as fh: json.dump({'cols': COLS, 'rows': rows, 'tn': tn}, fh, separators=(',', ':'))
    with gzip.open(PLAYERS, 'wt') as fh: json.dump(players, fh, separators=(',', ':'), sort_keys=True)
    with gzip.open(os.path.join(DATA, 'tennis_espn_kind.json.gz'), 'wt') as fh: json.dump(kind, fh, separators=(',', ':'))
    print(f'history {len(rows)} matches, {len(players)} players -> {os.path.relpath(HIST, ROOT)}')
    with gzip.open(ESPN_CUR, 'wt') as fh:
        json.dump([c for c in comps if (c['date'] or '') >= (today - dt.timedelta(days=8)).isoformat()], fh, separators=(',', ':'))
    return rows, players, comps, tn


def load_espn():
    """(this fortnight's ESPN singles competitions, ESPN id -> our id, ESPN tournament id -> (level, surface))"""
    with gzip.open(ESPN_CUR, 'rt') as fh: comps = json.load(fh)
    with gzip.open(IDMAP, 'rt') as fh: eid = json.load(fh)['espn']
    with gzip.open(os.path.join(DATA, 'tennis_espn_kind.json.gz'), 'rt') as fh: kind = json.load(fh)
    return comps, eid, {k: tuple(v) for k, v in kind.items()}


def load():
    """(rows, players, tournament names) from the last build"""
    with gzip.open(HIST, 'rt') as fh: h = json.load(fh)
    with gzip.open(PLAYERS, 'rt') as fh: p = json.load(fh)
    return h['rows'], p, h.get('tn', {})


def export(rows, players, tn):
    os.makedirs(EXPORT, exist_ok=True)
    p = os.path.join(EXPORT, 'matches.csv.gz')
    with gzip.open(p, 'wt', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(COLS[:10] + ['tname'] + [f'w_{s}' for s in STAT] + [f'l_{s}' for s in STAT] + COLS[12:])
        for r in rows:
            w.writerow(r[:10] + [tn.get(r[6], '')] + (r[10] or [''] * 9) + (r[11] or [''] * 9) + r[12:16])
    with gzip.open(os.path.join(EXPORT, 'players.json.gz'), 'wt') as fh: json.dump(players, fh, separators=(',', ':'))
    print('exported', p)


if __name__ == '__main__':
    if '--hist' in sys.argv:
        fetch_sack()
    rows, players, comps, tn = build(refresh='--offline' not in sys.argv)
    if '--export' in sys.argv: export(rows, players, tn)
