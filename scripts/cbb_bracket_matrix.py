#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""The Bracket Matrix (bracketmatrix.com): every tracked bracketologist's seed for each team, as a consensus.

    python3 scripts/cbb_bracket_matrix.py          # append today's live matrix to the season ledger
    python3 scripts/cbb_bracket_matrix.py --test   # parser self-test

parse(path or html) -> [{team, seed (the page's first column: official seed on a past season's final page, the
matrix seed on the live page), avg (average seed), n (brackets naming the team), share}].
The ledger (scripts/data/ledger/cbb/bracket_matrix_<season>.jsonl, one line a day the page changed) is a record for
the season-end score of the committee model; nothing on the site reads it.
"""
import datetime as dt, html, json, os, re, sys, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
SEASON = 2027
LEDGER = os.path.join(HERE, 'data', 'ledger', 'cbb', f'bracket_matrix_{SEASON}.jsonl')
URL = 'https://www.bracketmatrix.com/'
UA = 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'


def parse(src):
    s = open(src, encoding='utf-8', errors='replace').read() if os.path.exists(src) else src
    out, seen = [], set()
    for r in re.findall(r'<tr[^>]*>(.*?)</tr>', s, re.S):
        c = [html.unescape(re.sub(r'<[^>]+>', '', x)).replace('\xa0', ' ').strip() for x in re.findall(r'<td[^>]*>(.*?)</td>', r, re.S)]
        if len(c) < 6 or not c[1]:
            continue
        try:
            avg, n = float(c[3]), int(c[4])
        except ValueError:
            continue
        team = re.sub(r'\s+', ' ', c[1])
        if not 1 <= avg <= 16.5 or n < 1 or team in seen:
            continue
        seen.add(team)
        out.append({'team': team, 'seed': int(c[0]) if c[0].isdigit() else None, 'avg': avg, 'n': n})
    tot = max((x['n'] for x in out), default=0)
    for x in out:
        x['share'] = round(x['n'] / tot, 4) if tot else 0.0
    return out


# the matrix's school names that the shared team key does not already join to ESPN's
ALIAS = {'Miami (FLA.)': 'Miami', "St. Mary's (CA)": "Saint Mary's", 'NC-Wilmington': 'UNC Wilmington', 'NC-Asheville': 'UNC Asheville',
         'NC-Greensboro': 'UNC Greensboro', 'College of Charleston': 'Charleston', 'McNeese State': 'McNeese', 'Louisiana-Lafayette': 'Louisiana',
         'Arkansas-Little Rock': 'Little Rock', 'Wisconsin-Green Bay': 'Green Bay', 'Wisconsin-Milwaukee': 'Milwaukee',
         'CSU Bakersfield': 'Cal State Bakersfield', 'E. Tennessee State': 'East Tennessee State', 'Maryland-Baltimore County': 'UMBC',
         'Texas-Arlington': 'UT Arlington', 'Miami (Ohio)': 'Miami (OH)', 'St. Francis (PA.)': 'Saint Francis', 'Appalachian State': 'App State',
         'Albany': 'UAlbany'}
FIT = os.path.join(os.path.dirname(HERE), 'data', 'cbb_bracket_matrix_fit.json')


def match(rows, id_name):
    """{ESPN team id: matrix row} by the shared team key (scripts/names.py); id_name: ESPN id -> ESPN school name"""
    import names as NM
    by = {}
    for i, n in id_name.items():
        by.setdefault(NM.team_key(n), []).append(i)
    out = {}
    for x in rows:
        ids = by.get(NM.team_key(ALIAS.get(x['team'], x['team'])), [])
        if len(ids) == 1 and ids[0] not in out:
            out[ids[0]] = x
    return out


def latest(max_age_days=2):
    """the newest logged matrix, when it is at most max_age_days old: [{team, seed, avg, n, share}]; else None"""
    try:
        last = None
        for ln in open(LEDGER):
            if ln.strip(): last = json.loads(ln)
        t = dt.datetime.strptime(last['t'], '%Y-%m-%dT%H:%MZ').replace(tzinfo=dt.timezone.utc)
        if (dt.datetime.now(dt.timezone.utc) - t).days > max_age_days:
            return None
        tot = max(r[3] for r in last['teams'])
        return [{'team': r[0], 'seed': r[1], 'avg': r[2], 'n': r[3], 'share': r[3] / tot} for r in last['teams']]
    except (OSError, ValueError, TypeError, KeyError):
        return None


def stack(teams, id_name):
    """the committee stack's inputs for cbb_tourney.run on Selection Sunday: the fit (data/cbb_bracket_matrix_fit.json)
    with each team's matrix average seed (nan when the matrix does not list it) and share of brackets; None without a
    fresh matrix or a fit"""
    rows = latest()
    if not rows or not os.path.exists(FIT):
        return None
    f = json.load(open(FIT))
    m = match(rows, id_name)
    if len(m) < 50:
        return None
    nan = float('nan')
    return {'seed_b': f['seed']['b'], 'sigma': f['seed']['sigma'], 'bid_b': f['bid']['b'],
            'avg': [m[t]['avg'] if t in m else nan for t in teams], 'share': [m[t]['share'] if t in m else 0.0 for t in teams]}


def log():
    req = urllib.request.Request(URL, headers={'User-Agent': UA})
    rows = parse(urllib.request.urlopen(req, timeout=60).read().decode('utf-8', 'replace'))
    if len(rows) < 40:
        sys.exit(f'bracket matrix: {len(rows)} teams parsed, nothing logged')
    teams = [[x['team'], x['seed'], x['avg'], x['n']] for x in rows]
    last = None
    if os.path.exists(LEDGER):
        for ln in open(LEDGER):
            if ln.strip(): last = json.loads(ln)
    if last and last.get('teams') == teams:
        print('bracket matrix: unchanged'); return
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER, 'a') as f:
        f.write(json.dumps({'t': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'), 'brackets': max(x['n'] for x in rows), 'teams': teams},
                           separators=(',', ':')) + '\n')
    print(f'bracket matrix: {len(rows)} teams, {max(x["n"] for x in rows)} brackets logged')


def self_test():
    page = ('<table><tr><td>1</td><td>Duke</td><td>ACC</td><td>1.00</td><td>50</td><td></td></tr>'
            '<tr><td></td><td>Others</td><td></td><td></td><td></td><td>x</td></tr>'
            '<tr><td></td><td>Miami&nbsp;(FLA.)</td><td>ACC</td><td>11.43</td><td>7</td><td></td></tr>'
            '<tr><td>1</td><td>Duke</td><td>ACC</td><td>1.00</td><td>50</td><td></td></tr></table>')
    r = parse(page)
    assert [x['team'] for x in r] == ['Duke', 'Miami (FLA.)'], r
    assert r[0]['seed'] == 1 and r[1]['seed'] is None and r[1]['share'] == 0.14, r
    print('cbb_bracket_matrix self-test ok')


if __name__ == '__main__':
    self_test() if '--test' in sys.argv else log()
