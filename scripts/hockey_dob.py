#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Exact birth dates for the hockey draft board (Nov 28 2026). Tankathon gives the birth month only (stored YYYY-MM-15);
each board player gets a day-precise date from the first source that has one, born in that same month:

  pin        data/dob_overrides.json "hockey" {"<names.key>|<club>": {dob, src}}: a date checked by hand against a page
  feed       the CHL, AHL, USHL and Liiga stat feeds (scripts/hockey_provisional.py exact_birth: same name, that month)
  hockeytech the OHL, WHL, QMJHL and USHL player search (HockeyTech), by last name; goalies too (the feeds are skaters)
  wikidata   Wikidata's entity search (scripts/dob_sources.py, ice hockey players), day precision, English label with the
             same name key, one item only

A date from a source that disagrees with the month, or two sources more than 3 days apart, goes to
data/dob_conflicts_hockey.json and the higher source wins (pin > feed > hockeytech > wikidata); a month disagreement
alone is not used. Found dates are kept in scripts/data/hockey_dob.json (a miss is tried again after 7 days), so the
daily build sends a Wikidata query only for new names. EliteProspects, QuantHockey and the KHL are not fetched (bot
challenge, AI crawlers refused or blocked from this region).

    python3 scripts/hockey_dob.py --test     # matcher cases, no network
"""
import datetime as dt
import json
import os
import re
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import names as NM

ROOT = os.path.dirname(HERE)
STORE = os.path.join(HERE, 'data', 'hockey_dob.json')
CONFLICTS = os.path.join(ROOT, 'data', 'dob_conflicts_hockey.json')
HT = {'OHL': ('f1aa699db3d81487', 'ohl'), 'WHL': ('41b145a848f4bd67', 'whl'), 'QMJHL': ('f322673b6bcae299', 'lhjmq'),
      'USHL': ('e828f89b243dc43f', 'ushl'), 'NTDP': ('e828f89b243dc43f', 'ushl')}
RANK = {'pin': 0, 'feed': 1, 'hockeytech': 2, 'wikidata': 3}
RETRY = 7
UA = 'arkboard-research/1.0 (+https://arkndjl.net)'


def _key(name, month):
    return f'{NM.key(name)}|{month}'


def same_month(dob, birth):
    return bool(dob) and bool(birth) and dob[:7] == birth[:7]


def ht_search(name, lg):
    """HockeyTech player search by last name -> [(full name, birth date, player id)]"""
    if lg not in HT:
        return []
    k, c = HT[lg]
    last = [w for w in name.split() if w.strip('.').lower() not in NM.SUFFIX][-1]
    term = max(last.split("'"), key=len)
    u = (f'https://lscluster.hockeytech.com/feed/index.php?feed=modulekit&view=searchplayers&search_term='
         f'{urllib.parse.quote(term)}&key={k}&client_code={c}&lang=en&fmt=json')
    for _ in range(2):
        try:
            j = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': UA}), timeout=30).read())
            return [(f"{p.get('first_name', '')} {p.get('last_name', '')}".strip(), (p.get('birthdate') or '')[:10], p.get('player_id'))
                    for p in (j.get('SiteKit') or {}).get('Searchplayers') or []]
        except Exception:
            pass
    return []


def pick(name, birth, cands):
    """the one date among [(name, dob, ref)] for this player born in birth's month: same name (shared matcher), or the
    same last name when no full name matches (a first name the matcher misses); None when none or several"""
    s = [c for c in cands if re.match(r'\d{4}-\d\d-\d\d$', c[1] or '') and same_month(c[1], birth)]
    c = [x for x in s if NM.same(x[0], name)]
    if not c:
        last = NM.tokens(name)[-1] if NM.tokens(name) else ''
        c = [x for x in s if NM.tokens(x[0]) and NM.tokens(x[0])[-1] == last]
    d = {x[1] for x in c}
    return (d.pop(), c[0][2]) if len(d) == 1 else None


def lookup(board, feed_birth, year, today=None):
    """board: [{name, club, league, birth (YYYY-MM-15)}] -> {name key|month: {dob, src, ref}}; feed_birth(name, birth)
    is the stat feeds' date or None. Writes the store and the conflict log."""
    import dob_sources as S
    today = today or dt.date.today().isoformat()
    try:
        store = json.load(open(STORE))
    except (OSError, ValueError):
        store = {'found': {}, 'miss': {}}
    pins = S.pinned('hockey')
    out, conflicts, ask = {}, [], []
    for t in board:
        if not t.get('birth'):
            continue
        k = _key(t['name'], t['birth'][:7])
        got = []
        p = pins.get(f"{NM.key(t['name'])}|{t.get('club')}")
        if p and p.get('dob'):
            got.append({'dob': p['dob'], 'src': 'pin', 'ref': (p.get('src') or [''])[0]})
        fb = feed_birth(t['name'], t['birth'])
        if fb:
            got.append({'dob': fb, 'src': 'feed', 'ref': t.get('league')})
        old = store['found'].get(k)
        if old and old['src'] in ('hockeytech', 'wikidata'):
            got.append(old)
        elif not got and (store['miss'].get(k) or '0') <= (dt.date.fromisoformat(today) - dt.timedelta(RETRY)).isoformat():
            h = pick(t['name'], t['birth'], ht_search(t['name'], t.get('league')))
            if h:
                got.append({'dob': h[0], 'src': 'hockeytech', 'ref': f"{t['league']}:{h[1]}"})
            else:
                ask.append(t)
        out[k] = got
    if ask:     # Wikidata: one SPARQL call a 40 names
        W = S.wikidata(sorted({t['name'] for t in ask}), 'hockey')
        for t in ask:
            k = _key(t['name'], t['birth'][:7])
            c = [x for x in W.get(t['name'], []) if x['dob'][:4] in (str(year - 19), str(year - 18), str(year - 20))]
            if len({x['qid'] for x in c}) == 1:
                x = c[0]
                if same_month(x['dob'], t['birth']):
                    out[k].append({'dob': x['dob'], 'src': 'wikidata', 'ref': x['qid']})
                else:
                    conflicts.append({'name': t['name'], 'club': t.get('club'), 'month': t['birth'][:7], 'wikidata': x['dob'], 'ref': x['qid'],
                                      'note': 'birth month differs from the board source; not used'})
    res = {}
    for t in board:
        if not t.get('birth'):
            continue
        k = _key(t['name'], t['birth'][:7])
        got = sorted(out.get(k) or [], key=lambda g: RANK[g['src']])
        if not got:
            store['miss'][k] = today
            store['found'].pop(k, None)
            continue
        if len({g['dob'] for g in got}) > 1 and S.disagree([g['dob'] for g in got]):
            conflicts.append({'name': t['name'], 'club': t.get('club'), 'month': t['birth'][:7], 'dates': got, 'note': 'sources disagree; the first is used'})
        res[k] = got[0]
        store['miss'].pop(k, None)
        if got[0]['src'] in ('hockeytech', 'wikidata'):
            store['found'][k] = got[0]
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    json.dump(store, open(STORE, 'w'), indent=0, sort_keys=True, ensure_ascii=False)
    json.dump({'asof': today, 'rows': conflicts}, open(CONFLICTS, 'w'), indent=1, ensure_ascii=False)
    return res


def get(res, name, birth):
    return res.get(_key(name, birth[:7])) if birth else None


def _test():
    b = '2008-11-15'
    assert pick('Noah Davidson', b, [('Noah Davidson', '2008-11-01', 1), ('Hyde Davidson', '2006-01-23', 2)]) == ('2008-11-01', 1)
    assert pick('Noah Davidson', b, [('Noah Davidson', '2008-12-01', 1)]) is None                      # another month
    assert pick('Noah Davidson', b, [('Noah Davidson', '2008-11-01', 1), ('Noah Davidson', '2008-11-20', 2)]) is None
    assert pick('Tim Smith', b, [('Timothy Smith', '2008-11-03', 5)]) == ('2008-11-03', 5)
    assert pick('Patrick Déniger', '2008-10-15', [('Patrick Deniger', '2008-10-02', 7)]) == ('2008-10-02', 7)
    assert pick('Eric Tu', b, [('Eric Tu', '', 1)]) is None
    print('hockey_dob: ok')


if __name__ == '__main__':
    if '--test' in sys.argv:
        _test()
