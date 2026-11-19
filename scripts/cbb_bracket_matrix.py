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
