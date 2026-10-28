#!/usr/bin/env python3
"""Opening-line backfill for the open-based pick rules (Oct 28 2026, edge sweep item 3): more seasons with an opening
spread and total, so the rules in scripts/games_picks.py (X set by closing line value at the open) tune on more than
one or two seasons and CBB totals can be judged at all.

    python3 scripts/odds_opens.py --sbr             # parse the SportsbookReviewsOnline archive (raw pages mirrored in the
                                                    # project files, research/sbr-mirror/) -> scripts/data/odds_hist/sbr_<sport>.json.gz
    python3 scripts/odds_opens.py --espn 2016 2024  # ESPN CBB opens for these seasons -> scripts/data/odds_hist/espn_cbb_opens.json.gz
    python3 scripts/odds_opens.py --apply           # fill Lo/To in scripts/data/games_wf/{cbb,cfb,nfl}.json.gz
    python3 scripts/odds_opens.py --report          # coverage and the open vs close check by source and season

Sources (free):
  SBR  sportsbookreviewsonline.com: CBB xlsx 2007-08 to 2020-21, NFL HTML 2007-08 to 2021-22, CFB HTML 2007-08 to
       2022-23. One row per team: the favorite's row carries the spread, the other row the total, for the open and the
       close separately. The open is an offshore opener with no time or book. The pages went 404 for an hour on Oct 28,
       so the parsed rows are committed (every column the rules use) and the raw pages are mirrored.
  ESPN CBB core odds: the 'Opening' provider (2014-17: the opening spread and total) and the chosen book's open.total
       (2024-26). cbb_games_hist.py skips both: it picks the closing book.

Joining: date within a day and the final score (either orientation at a neutral site), then the name closest to ESPN's
when a date has two games with the same score.

Mixing books. A rule's closing line value is the close minus the open, so an open from one book and a close from
another would book their difference as line movement. An SBR row keeps its own move: Lo = L + (SBR open - SBR close),
the history's close shifted by the move SBR saw. A row whose SBR close sits more than CLOSE_TOL off the history's close
is a different game or a bad row and is left out. ESPN opens come with their own close (same feed) and are used as they
are. The shared cleaner (scripts/units.py bad_open) still screens every open when the rules read it.

Order where sources overlap: the history's own open (ESPN, same book as the close), then ESPN 'Opening', then SBR.
"""
import difflib
import glob
import gzip
import html
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DIR = os.path.join(HERE, 'data', 'odds_hist')
# the raw pages: the project's mirror when it is mounted, else a fresh pull into the cache
RAW = next((p for p in ('/mnt/project-files/research/sbr-mirror', os.path.join(HERE, '.cache', 'sbr')) if os.path.isdir(p)),
           os.path.join(HERE, '.cache', 'sbr'))
WF = os.path.join(HERE, 'data', 'games_wf')
CACHE = os.path.join(HERE, '.cache', 'cbb', 'games', 'odds')
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36'
SBR = 'https://www.sportsbookreviewsonline.com/'
SBR_URL = {'cbb': SBR + 'wp-content/uploads/sportsbookreviewsonline_com_737/ncaa-basketball-{a}-{b}.xlsx',
           'nfl': SBR + 'scoresoddsarchives/nfl-odds-{a}-{b}/', 'cfb': SBR + 'scoresoddsarchives/ncaa-football-{a}-{b}/'}
SBR_FILE = {'cbb': 'ncaa-basketball-{a}-{b}.xlsx', 'nfl': 'nfl-odds-{a}-{b}.html', 'cfb': 'ncaa-football-{a}-{b}.html'}
SBR_SEASONS = {'cbb': range(2008, 2022), 'nfl': range(2007, 2022), 'cfb': range(2007, 2023)}   # season = start year (football), end year (cbb)
ODDS = 'https://sports.core.api.espn.com/v2/sports/basketball/leagues/mens-college-basketball/events/{i}/competitions/{i}/odds?limit=50'
CLOSE_TOL = {'spread': 1.5, 'total': 2.0}
SPORTS = ('cbb', 'cfb', 'nfl')


def save(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with gzip.GzipFile(path, 'wb', mtime=0) as f:
        f.write(json.dumps(rows, separators=(',', ':')).encode())


def load(path, default=None):
    return json.load(gzip.open(path)) if os.path.exists(path) else default


# ---------------------------------------------------------------- SBR

def sbr_raw(sport, s):
    """the raw file for one season (downloaded into the mirror when it is missing)"""
    a = s - 1 if sport == 'cbb' else s
    k = {'a': a, 'b': str(a + 1)[2:]}
    p = os.path.join(RAW, SBR_FILE[sport].format(**k))
    if not os.path.exists(p) or os.path.getsize(p) < 5000:
        os.makedirs(RAW, exist_ok=True)
        subprocess.run(['curl', '-s', '-m', '90', '-A', UA, SBR_URL[sport].format(**k), '-o', p], check=False)
        if os.path.exists(p) and os.path.getsize(p) < 5000:
            os.remove(p)
    return p if os.path.exists(p) else None


def sbr_cells(sport, p):
    if sport == 'cbb':
        import openpyxl
        ws = openpyxl.load_workbook(p, read_only=True).active
        rows = [[('' if c is None else str(c)).strip() for c in r[:11]] for r in ws.iter_rows(values_only=True)]
        return [r for r in rows if r and r[0].isdigit()], 6
    t = open(p, encoding='utf-8', errors='replace').read()
    out = []
    for r in re.findall(r'<tr[^>]*>(.*?)</tr>', t, re.S):
        c = [html.unescape(re.sub(r'<[^>]+>', '', x)).strip() for x in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', r, re.S)]
        if len(c) >= 12 and c[0].isdigit():
            out.append(c)
    return out, 8


def num(x):
    x = (x or '').strip().lower()
    if x in ('pk', "pk'", 'p'):
        return 0.0
    try:
        return float(x.replace('½', '.5'))
    except ValueError:
        return None


def split_line(v, h):
    """(home line, total) from the visitor's and the home row's numbers: the smaller is the favorite's spread and the
    larger the total. Home line = the home side's expected margin (home favored > 0)."""
    if v is None or h is None or v == h:
        return None, None
    if v < h:
        return -v, h
    return h, v


def parse_sbr(sport):
    out = []
    for s in SBR_SEASONS[sport]:
        p = sbr_raw(sport, s)
        if not p:
            print(sport, s, 'missing', flush=True)
            continue
        rows, fi = sbr_cells(sport, p)
        n = 0
        i = 0
        while i + 1 < len(rows):
            v, h = rows[i], rows[i + 1]
            if v[1].isdigit() and h[1].isdigit() and int(h[1]) != int(v[1]) + 1 or v[2] not in ('V', 'N') or h[2] not in ('H', 'N'):
                i += 1
                continue
            i += 2
            try:
                sv, sh = int(float(v[fi])), int(float(h[fi]))
            except ValueError:
                continue
            Lo, To = split_line(num(v[fi + 1]), num(h[fi + 1]))
            L, T = split_line(num(v[fi + 2]), num(h[fi + 2]))
            md = int(v[0])
            yr = (s if md < 700 else s - 1) if sport == 'cbb' else (s + 1 if md < 700 else s)
            try:
                d = date(yr, md // 100, md % 100).isoformat()
            except ValueError:
                continue
            out.append({'S': s, 'd': d, 'a': v[3], 'h': h[3], 'n': int(v[2] == 'N'), 'as': sv, 'hs': sh,
                        'Lo': Lo, 'L': L, 'To': To, 'T': T})
            n += 1
        print(sport, s, n, 'games', sum(r['Lo'] is not None for r in out if r['S'] == s), 'open spreads',
              sum(r['To'] is not None for r in out if r['S'] == s), 'open totals', flush=True)
    save(os.path.join(DIR, f'sbr_{sport}.json.gz'), out)


# ---------------------------------------------------------------- ESPN CBB opens

def espn_cached(i, season):
    p = os.path.join(CACHE, str(season), f'{i}.json')
    if os.path.exists(p):
        try:
            return json.load(open(p))
        except ValueError:
            pass
    os.makedirs(os.path.dirname(p), exist_ok=True)
    for k in range(3):
        subprocess.run(['curl', '-s', '-m', '40', '-A', UA, ODDS.format(i=i), '-o', p + '.tmp'], check=False)
        try:
            j = json.load(open(p + '.tmp'))
            os.replace(p + '.tmp', p)
            return j
        except (ValueError, OSError):
            time.sleep(1 + 2 * k)
    return None


def espn_open(j, close_book):
    """{'Lo', 'To', 'src'} from one game's ESPN odds: the 'Opening' provider's spread and total, else the closing book's
    own open (open.total; the spread open is already in the history). Spread on the history's scale (home favored > 0)."""
    out = {}
    for it in (j or {}).get('items', []):
        nm = it['provider']['name']
        if nm == 'Opening':
            sp = it.get('spread')
            if sp is not None and abs(sp) < 60:
                ho, ao = it.get('homeTeamOdds') or {}, it.get('awayTeamOdds') or {}
                if ho.get('favorite') and sp > 0 or ao.get('favorite') and sp < 0:
                    sp = -sp
                out['Lo'] = -float(sp)
            if it.get('overUnder') and 90 < it['overUnder'] < 220:
                out['To'] = float(it['overUnder'])
            if out:
                out['src'] = 'espn-opening'
        elif nm == close_book and 'To' not in out:
            t = (((it.get('open') or {}).get('total') or {}).get('alternateDisplayValue') or '').lstrip('ou')
            v = num(t)
            if v and 90 < v < 220 and it.get('overUnder'):
                out['To2'], out['Tc2'] = v, float(it['overUnder'])
    return out


def pull_espn(seasons):
    hist = [g for g in json.load(gzip.open(os.path.join(HERE, 'data', 'cbb_games_hist.json.gz'))) if g['season'] in seasons and g.get('hs') is not None]
    path = os.path.join(DIR, 'espn_cbb_opens.json.gz')
    out = load(path, {})
    t0 = time.time()
    with ThreadPoolExecutor(24) as ex:
        js = list(ex.map(lambda g: espn_cached(g['id'], g['season']), hist))
    for g, j in zip(hist, js):
        o = espn_open(j, g.get('book'))
        if o:
            out[g['id']] = o
    for s in seasons:
        ids = {g['id'] for g in hist if g['season'] == s}
        print(s, len(ids), 'games', sum('Lo' in out.get(i, {}) for i in ids), 'Opening spreads',
              sum('To' in out.get(i, {}) for i in ids), 'Opening totals', sum('To2' in out.get(i, {}) for i in ids),
              'book open totals', f'{time.time() - t0:.0f}s', flush=True)
    save(path, out)


NFL_ODDS = 'https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/events/{i}/competitions/{i}/odds?limit=50'
NFL_BOOKS = ('draftkings', 'espn bet', 'caesars', 'william hill', 'fanduel', 'betmgm', 'bet 365')


def espn_book_line(j, books):
    """(book, open spread, close spread, open total, close total) from the first book in order that has an open:
    spreads on the history's scale (home favored > 0)"""
    items = [it for it in (j or {}).get('items', []) if 'live' not in it['provider']['name'].lower()]
    items.sort(key=lambda it: next((k for k, b in enumerate(books) if b in it['provider']['name'].lower()), len(books)))
    for it in items:
        ho, ao = it.get('homeTeamOdds') or {}, it.get('awayTeamOdds') or {}
        o = {'book': it['provider']['name']}
        sp = it.get('spread')
        if sp is not None and abs(sp) < 60:
            if ho.get('favorite') and sp > 0 or ao.get('favorite') and sp < 0:
                sp = -sp
            o['L'] = -float(sp)
        op = num(((ho.get('open') or {}).get('pointSpread') or {}).get('american'))
        if op is not None and 'L' in o:
            o['Lo'] = -op
        if it.get('overUnder'):
            o['T'] = float(it['overUnder'])
            ot = num((((it.get('open') or {}).get('total') or {}).get('american') or '').lstrip('ou'))
            if ot:
                o['To'] = ot
        if 'Lo' in o or 'To' in o:
            return o
    return None


def pull_espn_nfl(seasons):
    """ESPN NFL opens (2022 on: the seasons the SBR archive lacks), keyed by the nflverse game id"""
    sys.path.insert(0, HERE)
    import nfl_games as N
    gs = [g for g in N.rows(N.get('games.csv', N.GAMES)) if int(g['season']) in seasons and g.get('espn') and g.get('home_score')]
    path = os.path.join(DIR, 'espn_nfl_opens.json.gz')
    out = load(path, {})

    def one(g):
        p = os.path.join(HERE, '.cache', 'nfl', 'espn_odds', g['espn'] + '.json')
        if os.path.exists(p):
            return json.load(open(p))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        subprocess.run(['curl', '-s', '-m', '40', '-A', UA, NFL_ODDS.format(i=g['espn']), '-o', p + '.tmp'], check=False)
        try:
            j = json.load(open(p + '.tmp'))
            os.replace(p + '.tmp', p)
            return j
        except (ValueError, OSError):
            return None
    with ThreadPoolExecutor(16) as ex:
        js = list(ex.map(one, gs))
    for g, j in zip(gs, js):
        o = espn_book_line(j, NFL_BOOKS)
        if o:
            out[g['game_id']] = o
    for s in seasons:
        ids = [g['game_id'] for g in gs if int(g['season']) == s]
        print(s, len(ids), 'games', sum('Lo' in out.get(i, {}) for i in ids), 'open spreads', sum('To' in out.get(i, {}) for i in ids), 'open totals', flush=True)
    save(path, out)


# ---------------------------------------------------------------- joining onto the walk-forward files

def key(s):
    return re.sub(r'[^a-z]', '', s.lower().replace('state', 'st').replace('saint', 'st'))


def local_date(d):
    if len(d) <= 10:
        return date.fromisoformat(d)
    t = datetime.fromisoformat(d.replace('Z', '+00:00'))
    return (t - timedelta(hours=6)).date()


def season_of(sport, x):
    # the walk-forward files' season: CBB the year it ends (SBR's too), football the year it starts
    return x['S']


def join_sbr(sport, rows, sbr):
    """{wf row index: (sbr row, flipped)}"""
    idx = {}
    for x in sbr:
        idx.setdefault((x['hs'], x['as']), []).append(x)
    out = {}
    for i, g in enumerate(rows):
        if g.get('res') is None:
            continue
        hs, as_ = sbr_scores(sport, g)
        if hs is None:
            continue
        d = local_date(g['date'])
        best = None
        for flip, k in ((0, (hs, as_)), (1, (as_, hs))):
            for x in idx.get(k, []):
                if abs((date.fromisoformat(x['d']) - d).days) > 1 or (flip and not (x['n'] or g.get('neutral'))):
                    continue
                hn, an = (x['a'], x['h']) if flip else (x['h'], x['a'])
                sc = difflib.SequenceMatcher(None, key(hn), key(g['home'])).ratio() + difflib.SequenceMatcher(None, key(an), key(g['away'])).ratio()
                if best is None or sc > best[0]:
                    best = (sc, x, flip)
        if best and best[0] >= 0.6:
            out[i] = (best[1], best[2])
    return out


def sbr_scores(sport, g):
    """(home score, away score) of a walk-forward row: res is the home margin and tot the total"""
    if g.get('res') is None or g.get('tot') is None:
        return None, None
    h2 = g['tot'] + g['res']
    if h2 % 2:
        return None, None
    return int(h2 // 2), int(g['tot'] - h2 // 2)


def apply():
    espn = load(os.path.join(DIR, 'espn_cbb_opens.json.gz'), {})
    enfl = load(os.path.join(DIR, 'espn_nfl_opens.json.gz'), {})
    for sport in SPORTS:
        p = os.path.join(WF, sport + '.json.gz')
        rows = json.load(gzip.open(p))
        sbr = load(os.path.join(DIR, f'sbr_{sport}.json.gz'), [])
        J = join_sbr(sport, rows, sbr)
        cnt, drop = {}, {}
        for i, g in enumerate(rows):
            for mk, ko, kc in (('spread', 'Lo', 'L'), ('total', 'To', 'T')):
                if g.get(kc) is None:
                    continue
                if g.get(ko) is not None and g.get(ko + 's') is None:
                    # the history's own open (same book as the close)
                    cnt[(g['S'], mk, 'own')] = cnt.get((g['S'], mk, 'own'), 0) + 1
                    continue
                g[ko] = None
                g.pop(ko + 's', None)
                # candidates in order: (source, open, that source's close or None when it is the history's own book)
                cand = []
                e = espn.get(str(g.get('id'))) if sport == 'cbb' else None
                if e and mk == 'total' and e.get('To2') is not None:
                    cand.append(('espn-book', e['To2'], e['Tc2']))
                if e and e.get(ko) is not None:
                    cand.append(('espn-opening', e[ko], None))
                n = enfl.get(str(g.get('id'))) if sport == 'nfl' else None
                if n and n.get(ko) is not None and n.get(kc) is not None:
                    cand.append(('espn-' + n['book'].lower().replace(' ', ''), n[ko], n[kc]))
                if i in J and J[i][0][ko] is not None and J[i][0][kc] is not None:
                    x, flip = J[i]
                    xo, xc = x[ko], x[kc]
                    if mk == 'spread' and flip:
                        xo, xc = -xo, -xc
                    cand.append(('sbr', xo, xc))
                for src, o, c in cand:
                    if c is not None and abs(c - g[kc]) > CLOSE_TOL[mk]:
                        drop[(sport, src, mk)] = drop.get((sport, src, mk), 0) + 1
                        continue
                    # a source's own move, put on the history's close
                    g[ko], g[ko + 's'] = (o if c is None else round(g[kc] + o - c, 2)), src
                    cnt[(g['S'], mk, src)] = cnt.get((g['S'], mk, src), 0) + 1
                    break
        with gzip.GzipFile(p, 'wb', mtime=0) as f:
            f.write(json.dumps(rows).encode())
        print(sport, len(rows), 'rows', len(J), 'joined to SBR; dropped (close off the history by more than', CLOSE_TOL, '):', drop)
        for k in sorted(cnt):
            print('  ', *k, cnt[k])


def report():
    import statistics as st
    for sport in SPORTS:
        rows = json.load(gzip.open(os.path.join(WF, sport + '.json.gz')))
        print(sport)
        for S in sorted({r['S'] for r in rows}):
            rs = [r for r in rows if r['S'] == S]
            line = [f'  {S} n {len(rs)}']
            for mk, ko, kc, kr in (('spread', 'Lo', 'L', 'res'), ('total', 'To', 'T', 'tot')):
                xs = [r for r in rs if r.get(ko) is not None and r.get(kc) is not None and r.get(kr) is not None]
                if not xs:
                    continue
                srcs = sorted({r.get(ko + 's') or 'own' for r in xs})
                mo = st.mean(abs(r[kr] - r[ko]) for r in xs)
                mc = st.mean(abs(r[kr] - r[kc]) for r in xs)
                mv = st.mean(abs(r[kc] - r[ko]) for r in xs)
                line.append(f'{mk} {len(xs)} {"/".join(srcs)} MAE open {mo:.2f} close {mc:.2f} |move| {mv:.2f}')
            print(' | '.join(line))


if __name__ == '__main__':
    a = sys.argv[1:]
    if '--sbr' in a:
        for sp in [x for x in a if x in SPORTS] or SPORTS:
            parse_sbr(sp)
    if '--espn' in a:
        pull_espn([int(x) for x in a if x.isdigit()])
    if '--espn-nfl' in a:
        pull_espn_nfl([int(x) for x in a if x.isdigit()])
    if '--apply' in a:
        apply()
    if '--report' in a:
        report()
