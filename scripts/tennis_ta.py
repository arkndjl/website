#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Challenger, ITF and qualifying results since the Sackmann archive froze (June 2026), from Tennis Abstract's player
pages, as history rows for scripts/tennis_data.py.

The archive's lower-level files end in early June 2026 and the weekly feed and ESPN only carry tour-level main draws,
so a player on the Challenger tour had no match on file after that: a stale rating, a "60 days of rest" context term
in his next tour-level match, and no place on the ARK Ranking once his last match is 183 days old. Each run reads the
pages of the top POOL players per tour by official rank (stalest first, inside a time budget; the ATP pages are a rate-
limited CGI), keeps every match that started after CUT, and merges it into scripts/data/tennis_ta.jsonl (committed, one
match a line, so a lost Actions cache costs nothing). tennis_data.build() adds the rows no other source holds.

    python3 scripts/tennis_ta.py            # refresh inside the budget, print the counts
    python3 scripts/tennis_ta.py --all      # no budget (first fill: about 15 minutes)
"""
import datetime as dt
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import names  # noqa: E402

CACHE = os.path.join(HERE, '.cache', 'tennis')
PAGES = os.path.join(CACHE, 'ta_full')
STORE = os.path.join(HERE, 'data', 'tennis_ta.jsonl')
CUT = 20260525                     # matches of events that started after this (the archive's lower levels end in early June)
POOL = 400                         # players per tour, by official rank
MAX_AGE = 3 * 86400                # a page is read again after three days
BUDGET = 600                       # seconds of fetching per run
PAUSE = 1.0                        # between ATP pages (the CGI answers 429 when hurried)
UA = 'Mozilla/5.0 (arkboard; arkndjl.net)'
# the page's match columns (Tennis Abstract's matchhead), the first 39
HEAD = ['date', 'tourn', 'surf', 'level', 'wl', 'rank', 'seed', 'entry', 'round', 'score', 'max', 'opp', 'orank',
        'oseed', 'oentry', 'ohand', 'obday', 'oht', 'ocountry', 'oactive', 'time', 'aces', 'dfs', 'pts', 'firsts',
        'fwon', 'swon', 'games', 'saved', 'chances', 'oaces', 'odfs', 'opts', 'ofirsts', 'ofwon', 'oswon', 'ogames',
        'osaved', 'ochances']
SURF = {'Hard': 'H', 'Clay': 'C', 'Grass': 'G', 'Carpet': 'H'}
TOUR_RAW = {'atp': ('G', 'M', 'A', 'F', 'O'), 'wta': ('G', 'PM', 'P', 'I', 'W', 'F', 'O')}


def param(name):
    s = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode()
    return ''.join(ch for ch in s if ch.isalpha())


def _matchmx(h):
    i = h.find('matchmx = [[')
    if i < 0: return []
    i = h.index('[', i)
    depth, j, q = 0, i, False
    while j < len(h):                          # the array ends where its brackets close (strings hold no brackets)
        c = h[j]
        if c == '"': q = not q
        elif not q and c == '[': depth += 1
        elif not q and c == ']':
            depth -= 1
            if depth == 0: break
        j += 1
    try:
        return [r[:len(HEAD)] for r in json.loads(h[i:j + 1])]
    except ValueError:
        return []


def page(name, tour, max_age=MAX_AGE, fetch=True):
    """(a player's matches after CUT as HEAD-ordered lists, fetched now?) or (None, False); cached by name"""
    os.makedirs(PAGES, exist_ok=True)
    p = param(name)
    f = os.path.join(PAGES, f'{tour}_{p}.json')
    if os.path.exists(f) and (not fetch or time.time() - os.path.getmtime(f) < max_age):
        return json.load(open(f)), False
    if not fetch: return None, False
    url = (f'https://www.tennisabstract.com/cgi-bin/player-classic.cgi?p={p}' if tour == 'atp'
           else f'https://www.tennisabstract.com/jsmatches/{p}.js')
    h = None
    for k in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            h = urllib.request.urlopen(req, timeout=40).read().decode('utf-8', 'replace')
            break
        except urllib.error.HTTPError as e:
            if e.code != 429: return None, True
            time.sleep(15 * (k + 1))
        except Exception:  # noqa: BLE001
            return None, True
    if h is None: return None, True
    if tour == 'atp': time.sleep(PAUSE)
    rows = [r for r in _matchmx(h) if r and str(r[0]).isdigit() and int(r[0]) > CUT]
    json.dump(rows, open(f, 'w'), separators=(',', ':'))
    return rows, True


def _pool(bios, ranks, tour):
    """[(rank, Tennis Abstract name, our id)] for the top POOL ranks"""
    rows = [dict(b, id=pid) for pid, b in bios.items() if pid[0] == tour[0]]
    for b in list(rows):
        if b.get('ioc') in ('CHN', 'TPE', 'HKG', 'KOR', 'PRK', 'MAC'):
            t = b.get('n', '').split()
            if len(t) >= 2: rows.append(dict(b, n=' '.join(t[1:] + t[:1])))
    m = names.Matcher(rows, name='n', team=None)
    out = []
    for n, rk in ranks.items():
        try:
            rk = int(rk)
        except (TypeError, ValueError):
            continue
        if rk > POOL: continue
        row, _ = m.find(n)
        if row: out.append((rk, n, row['id']))
    return sorted(out)


def _int(x):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return None


def _stat(d, o=''):
    v = [_int(d.get(o + k)) for k in ('pts', 'firsts', 'fwon', 'swon', 'games', 'saved', 'chances', 'aces', 'dfs')]
    return v if v[0] and v[0] > 0 and None not in v[:5] else None


def _level(tour, raw, rnd):
    raw = (raw or '').strip()
    if raw == 'D': return 'D'
    if raw in TOUR_RAW[tour]: return 'Q' if rnd.startswith('Q') else 'T'
    return 'C' if raw == 'C' else 'S'          # as the archive files them: the ITF W75 / W100 events are 'S'


def derive(pid, tour, rows, find):
    """a page's rows as history rows (tennis_data COLS + the event name); tour-level main draws are left to the feed"""
    out = []
    for r in rows:
        d = dict(zip(HEAD, list(r) + [''] * (len(HEAD) - len(r))))
        if d['wl'] not in ('W', 'L') or not str(d['date']).isdigit(): continue
        sc = (d['score'] or '').strip()
        up = sc.upper()
        if not sc or 'W/O' in up or 'WALKOVER' in up or up in ('DEF', 'UNK'): continue
        rd = (d['round'] or '').strip()
        lv = _level(tour, d['level'], rd)
        if lv == 'T': continue
        opp = find(d['opp'], d['obday'], d['ocountry'], d['ohand'], d['oht'])
        if not opp or opp == pid: continue
        me, ot = _stat(d), _stat(d, 'o')
        won = d['wl'] == 'W'
        w, l = (pid, opp) if won else (opp, pid)
        ws, ls = (me, ot) if won else (ot, me)
        wr, lr = (_int(d['rank']), _int(d['orank'])) if won else (_int(d['orank']), _int(d['rank']))
        tid = f"{tour[0]}ta{d['date']}-{re.sub(r'[^a-z0-9]+', '-', d['tourn'].lower()).strip('-')}"
        out.append([int(d['date']), tour, lv, SURF.get(d['surf'], 'H'), rd, 5 if _int(d['max']) == 5 else 3, tid, w, l, sc,
                    ws, ls, wr, lr, None, None, d['tourn']])
    return out


def key(r):
    return f'{r[0]}|{r[1]}|{r[4]}|' + '|'.join(sorted((r[7], r[8])))


def load():
    """(rows by key, bios of the players only these pages know)"""
    rows, bios = {}, {}
    try:
        with open(STORE, encoding='utf-8') as fh:
            for line in fh:
                x = json.loads(line)
                if isinstance(x, dict): bios[x['id']] = x['bio']
                else: rows[key(x)] = x
    except OSError:
        pass
    return rows, bios


def save(rows, bios):
    with open(STORE, 'w', encoding='utf-8') as fh:
        for pid in sorted(bios):
            fh.write(json.dumps({'id': pid, 'bio': bios[pid]}, separators=(',', ':'), ensure_ascii=False) + '\n')
        for k in sorted(rows):
            fh.write(json.dumps(rows[k], separators=(',', ':'), ensure_ascii=False) + '\n')


def finder(bios, tour, new):
    """opponent name + birthday (+ country) -> our id; a player no source knows takes "<a|w>ta<name key>" and a bio"""
    t = tour[0]
    by, nm, born = {}, {}, {}                    # (name key, birthday) -> id; name key -> ids; birthday -> ids

    def put(k, pid, dob):
        if dob: by.setdefault((k, dob), pid)
        if pid not in nm.setdefault(k, []): nm[k].append(pid)
    for pid, b in bios.items():
        if pid[0] != t: continue
        put(names.key(b.get('n', '')), pid, b.get('dob'))
        if b.get('dob'): born.setdefault(b['dob'], []).append(pid)
        if b.get('ioc') in ('CHN', 'TPE', 'HKG', 'KOR', 'PRK', 'MAC'):
            w = b.get('n', '').split()
            if len(w) >= 2: put(names.key(' '.join(w[1:] + w[:1])), pid, b.get('dob'))

    def find(name, bday, ioc, hand, ht):
        k = names.key(name or '')
        if not k: return None
        dob = _int(bday) if str(bday).isdigit() and len(str(bday)) == 8 else None
        if dob and (k, dob) in by: return by[(k, dob)]
        c = nm.get(k, [])
        if dob:                                    # a bio without a birthday, or a day or two off
            c = [p for p in c if not bios[p].get('dob') or abs(bios[p]['dob'] - dob) <= 2]
        if len(c) == 1: return c[0]
        if dob:                                    # another spelling: the same birthday, country and surname
            last = k.split()[-1]
            c = [p for p in born.get(dob, []) if bios[p].get('ioc') == ioc and names.key(bios[p].get('n', '')).split()[-1:] == [last]]
            if len(c) == 1: return c[0]
        pid = f"{t}ta{k.replace(' ', '')}{str(dob)[2:] if dob else ''}"
        b = {'n': name, 'ioc': ioc or '', 'dob': dob, 'hand': (hand or '')[:1].replace('U', ''), 'ht': _int(ht)}
        bios[pid] = new[pid] = b
        put(k, pid, dob)
        return pid
    return find


def refresh(bios, ranks, fetch=True, budget=BUDGET):
    """read the stalest pool pages inside the budget, merge their matches into the store; returns (rows, new bios).
    bios (our id -> dict(n, ioc, dob, ...)) gains the players only Tennis Abstract knows; ranks: {tour: {name: rank}}"""
    rows, tb = load()
    for pid, b in tb.items(): bios.setdefault(pid, b)
    t0, got, seen = time.time(), 0, 0
    for tour in ('wta', 'atp'):                    # the WTA pages are static files, the ATP ones a CGI: quick ones first
        pool = _pool(bios, ranks.get(tour) or {}, tour)

        def age(x):
            f = os.path.join(PAGES, f'{tour}_{param(x[1])}.json')
            return os.path.getmtime(f) if os.path.exists(f) else 0
        find = finder(bios, tour, tb)
        for rk, n, pid in sorted(pool, key=age):
            pg, new = page(n, tour, fetch=fetch and time.time() - t0 < budget)
            got += new
            if pg is None: continue
            seen += 1
            for r in derive(pid, tour, pg, find):
                k = key(r)
                if k not in rows or (r[10] and not rows[k][10]): rows[k] = r
    save(rows, tb)
    print(f'Tennis Abstract: {seen} pages on file ({got} read now), {len(rows)} lower-level matches since the archive froze, '
          f'{len(tb)} players new to the history')
    return list(rows.values()), tb


def add(hist, ta):
    """the Tennis Abstract rows no other source holds: same two players and round within two weeks = the same match"""
    def dn(d): return dt.date(d // 10000, d // 100 % 100, d % 100).toordinal()
    have = {}
    for r in hist:
        if r[0] >= CUT - 100: have.setdefault((frozenset((r[7], r[8])), r[4]), []).append(dn(r[0]))
    out = []
    for r in ta:
        ds = have.get((frozenset((r[7], r[8])), r[4]), ())
        if any(abs(dn(r[0]) - x) <= 14 for x in ds): continue
        out.append(r)
    return out


if __name__ == '__main__':
    import tennis_data as T
    bios = T.sack_players()
    try:
        _, players, _ = T.load()
        for pid, b in players.items(): bios.setdefault(pid, {'n': b.get('n', ''), 'ioc': '', 'dob': b.get('dob')})
    except OSError:
        pass
    refresh(bios, T.ta_ranks(), budget=10 ** 9 if '--all' in sys.argv else BUDGET)
