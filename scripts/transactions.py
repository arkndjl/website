#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Transactions log for every sport's ARKBOARD page: trades (with the draft picks in each deal), waiver claims,
releases, signings, practice squad, call-ups and send-downs, college exits, soccer transfers.

Sources:
  nfl nba nhl cfb cbb  RotoWire's news feed moves (scripts/rotowire_moves.py -> scripts/data/rotowire_moves/), each
                       item read again with today's patterns. A trade's clubs and picks come from the item text
                       ("The Jaguars acquired Davis from the Eagles in exchange for a 2027 first-round pick and a 2029
                       second-round pick"): picks after "in exchange for" go to the club giving the player up, picks
                       named with him ("acquired Harrison and a 2027 sixth-round pick") go with him.
  soccer               Transfermarkt transfers (transfermarkt-datasets dump, transfers + clubs), the site's leagues.
  data/trade_picks.json  hand entries that win over the parse: {sport: [{d, player, frm, to, picks: [{y, r, frm,
                       to, cond}]}]}; a deal the feed missed can be added the same way.

data/transactions/<sport>.json {asof, rows, deals}:
  rows   one a player move, newest first: d, n (player), pos, k (trade / claim / release / sign / practice / up /
         down / exit / transfer), fr, to, pk (the deal's picks, "PHI '27 R1, '29 R2"), fee (soccer, EUR)
  deals  one a trade: d, players [[name, fr, to]], picks [[y, r, fr, to, cond]]
Draft picks for the NFL mock: picks(sport, draft_year) and scripts/cfb_teams.mjs ledgerNflTrades (same file).

  python3 scripts/transactions.py            # every sport
  python3 scripts/transactions.py nfl
"""
import gzip
import io
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rotowire_moves as RM  # noqa: E402

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'transactions')
HAND = os.path.join(ROOT, 'data', 'trade_picks.json')
SPORTS = ['nfl', 'nba', 'nhl', 'cfb', 'cbb', 'soccer']
LABEL = {'trade': 'trade', 'claim': 'claim', 'waived': 'release', 'sign': 'sign', 'practice': 'practice',
         'up': 'up', 'down': 'down', 'exit': 'exit'}
ORD = {'first': 1, 'second': 2, 'third': 3, 'fourth': 4, 'fifth': 5, 'sixth': 6, 'seventh': 7,
       '1st': 1, '2nd': 2, '3rd': 3, '4th': 4, '5th': 5, '6th': 6, '7th': 7}
_O = r'(?:first|second|third|fourth|fifth|sixth|seventh|1st|2nd|3rd|4th|5th|6th|7th)'
PICK = re.compile(r'((?:20\d\d(?:,? (?:and |or )?)?)+)?\s*(?:conditional )?\b((?:' + _O + r'-?,? (?:and |or )?)*' + _O +
                  r')[- ]round(?: draft)? (?:picks?|selections?)', re.I)
VOID = re.compile(r'fall(s|en)? through|fell through|voided|rescinded|nullified|fail(s|ed)? (his )?physical|'
                  r'won\'t be completed|called off', re.I)
TM = 'https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data/'
TM_LEAGUES = {'GB1': 'EPL', 'ES1': 'Liga', 'L1': 'Bund', 'IT1': 'SerA', 'FR1': 'Lig1', 'MLS1': 'MLS', 'NL1': 'Ered',
              'PO1': 'Prim', 'BE1': 'Belg', 'TR1': 'Süper', 'SC1': 'Scot'}
SEASON_START = '2026-06-01'


NUM = {'a': 1, 'an': 1, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'a pair of': 2, 'pair of': 2}


def parse_picks(body, frm, to, player=''):
    """[[y, r, from club, to club, conditional]] named in a trade item; frm/to: the player's old and new club.
    Picks named after "in exchange for" go the other way from the player, picks named with him go with him; when the
    item's text is about another player in the deal ("sending Leonard to Toronto for Ingram, Dick, two first-round
    picks"), this player is named after the cut and the sides flip. A pick swap moves no pick and is left out."""
    b = body or ''
    cut = re.search(r'in exchange for|in return for|\bfor (?=a |an |two |three |20\d\d |[A-Z])', b)
    last = (player or '').split()[-1] if player else ''
    flip = bool(cut and last and last in b[cut.end():] and last not in b[:cut.start()])
    out = []
    pat = re.compile(r'(?:\b(a pair of|pair of|two|three|four|five|one|an?) )?((?:20\d\d(?:,? (?:and |or )?)?)+)?\s*'
                     r'(?:(?:un)?protected |conditional |future |lottery-protected |top-\d+ protected )*\b((?:' + _O +
                     r'-?,? (?:and |or )?)*' + _O + r')[- ]round(?:er)?s?(?: draft)?( (?:picks?|selections?|pick swaps?|swaps?))?',
                     re.I)
    for m in pat.finditer(b):
        if m.group(4) is None and not re.search(r'rounders?', m.group(0), re.I):
            continue
        if re.match(r'\s*swaps?', b[m.end():]) or (m.group(4) and 'swap' in m.group(4).lower()):
            continue
        n = NUM.get((m.group(1) or 'a').lower(), 1)
        ys = re.findall(r'20\d\d', m.group(2) or '') or [None] * n
        rs = [ORD[x.lower()] for x in re.findall(_O, m.group(3), re.I)]
        after = bool(cut and m.start() > cut.start())
        a, z = (to, frm) if after != flip else (frm, to)
        cond = bool(re.search(r'conditional', b[max(0, m.start() - 30):m.end()], re.I) or
                    re.search(r'condition', b[m.end():m.end() + 80], re.I))
        for y in ys:
            for r in rs:
                out.append([int(y) if y else None, r, a, z, cond])
    return out


def _hand():
    try:
        return json.load(open(HAND))
    except (OSError, ValueError):
        return {}


def _kind(m):
    k = m['kind']
    if k != 'move':
        return k
    b = (m.get('body') or '') + ' ' + m['head']
    if re.search(r'waiver', b, re.I):
        return 'claim'
    if re.search(r'trad|acquir|deal|exchange|shipped|swap', b, re.I):
        return 'trade'
    if re.search(r'practice squad', b, re.I) and not re.search(r'signed .* off', b, re.I):
        return 'practice'
    return 'sign'


def pro(sport):
    sp = RM.SITE[sport]
    college = sport in ('cfb', 'cbb')
    teams = RM.teams(sp)
    rows, seen = [], {}
    for m in RM.moves(sp):
        k = _kind(m)
        t = teams.get(m['pid']) or {}
        if k == 'trade' and t.get('d', '') >= m['d'] and VOID.search(t.get('head') or ''):
            continue          # the deal fell through (Ebiketie, PHI -> CIN Nov 10)
        if k == 'trade' and not college and not m.get('to'):
            continue          # "Trade being finalized" to an unnamed club: the deal's own item follows
        if college:
            fr, to = (m['team'] if k == 'exit' else None), (None if k == 'exit' else m['team'])
        else:
            ab = None if m['abbr'] in RM.FA else m['abbr']
            to, fr = m.get('to'), m.get('frm')
            named = None
            if not (to or fr or ab):       # FA on RotoWire: the club the item text names
                R = RM._clubs_re(sp)
                x = R.search(m.get('body') or '') if R else None
                named = RM.club_of(sp, x.group(1)) if x else None
            if k in ('waived', 'exit'):
                fr, to = fr or ab or named, None
            elif k in ('practice', 'up', 'down'):
                to = to or ab or named
            elif k in ('sign', 'claim', 'trade'):
                cur = t.get('abbr') if t.get('abbr') not in RM.FA else None
                # RotoWire re-renders an item with the player's club as of the fetch: a few days on, a club that
                # differs from the parsed one means the text was about another player in the deal ("the trade
                # sending Leonard to Toronto for Ingram")
                if k == 'trade' and cur and to and cur != to and (datetime.fromisoformat(t.get('d') or m['d']) -
                                                                datetime.fromisoformat(m['d'])).days > 3 and cur == ab:
                    fr, to = (to if fr in (None, cur) else fr), cur
                to = to or ab
                if fr == to:
                    fr = None
        r = {'d': m['d'], 'n': m['player'], 'pos': m['pos'], 'k': LABEL.get(k, k), 'fr': fr, 'to': to,
             'h': m['head']}
        if k == 'trade':
            r['picks'] = parse_picks(m.get('body'), fr, to, m['player'])
        # one row a move: RotoWire often writes a trade twice ("Being traded to Jaguars", then "Sent to Jacksonville")
        key = (m['pid'], r['k'], r['to'])
        prev = seen.get(key)
        if prev is not None and abs((datetime.fromisoformat(m['d']) - datetime.fromisoformat(prev['d'])).days) <= 3:
            if r.get('picks') or not prev.get('picks'):
                prev.update(r)
            continue
        seen[key] = r
        rows.append(r)
    for h in _hand().get(sport, []):      # hand entries win
        hit = next((r for r in rows if r['k'] == 'trade' and r['n'] == h['player'] and abs(
            (datetime.fromisoformat(r['d']) - datetime.fromisoformat(h['d'])).days) <= 3), None)
        if not hit:
            hit = {'d': h['d'], 'n': h['player'], 'pos': h.get('pos', ''), 'k': 'trade', 'h': ''}
            rows.append(hit)
        hit.update({'fr': h['frm'], 'to': h['to'],
                    'picks': [[p['y'], p['r'], p['frm'], p['to'], bool(p.get('cond'))] for p in h.get('picks', [])]})
    # deals: trades on one day between one pair of clubs, picks pooled without repeats
    deals = {}
    for r in rows:
        if r['k'] != 'trade' or not r.get('to'):
            continue
        key = (r['d'], frozenset(x for x in (r['fr'], r['to']) if x))
        D = deals.setdefault(key, {'d': r['d'], 'players': [], 'picks': []})
        D['players'].append([r['n'], r['fr'], r['to']])
        # each player's item usually tells the whole deal: the fullest one's picks (no pooling, so a pick read
        # from two items is counted once)
        if len(r.get('picks') or []) > len(D['picks']):
            D['picks'] = list(r['picks'])
    for D in deals.values():
        txt = pick_text(D['picks'])
        for n, fr, to in D['players']:
            for r in rows:
                if r['k'] == 'trade' and r['n'] == n and r['d'] == D['d']:
                    r['pk'] = txt
    for r in rows:
        r.pop('picks', None)
    rows.sort(key=lambda r: r['d'], reverse=True)
    return rows, sorted(deals.values(), key=lambda D: D['d'], reverse=True)


def pick_text(picks):
    """"PHI '27 R1, '29 R2 · JAX '28 R7" (each club and the picks it receives)"""
    by = {}
    for y, r, a, z, c in picks:
        by.setdefault(z or '?', []).append(f"{chr(39) + str(y)[2:] if y else ''} R{r}{'*' if c else ''}".strip())
    return ' · '.join(f"{t} {', '.join(v)}" for t, v in by.items())


def picks(sport, draft_year):
    """[{round, from, to, cond, deal}] picks for one draft traded this season (the mock's real-trades list)"""
    p = os.path.join(OUT, f'{sport}.json')
    try:
        D = json.load(open(p))['deals']
    except (OSError, ValueError, KeyError):
        return []
    out = []
    for d in D:
        for y, r, a, z, c in d['picks']:
            if y == draft_year and a and z:
                out.append({'round': r, 'from': a, 'to': z, 'cond': c, 'deal': d['players'][0][0], 'd': d['d']})
    return out


def _tm(f):
    req = urllib.request.Request(TM + f, headers={'User-Agent': 'arkndjl.net arkboard'})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def soccer():
    import csv
    clubs = {}
    for c in csv.DictReader(io.TextIOWrapper(gzip.GzipFile(fileobj=io.BytesIO(_tm('clubs.csv.gz'))), 'utf-8')):
        if c['domestic_competition_id'] in TM_LEAGUES:
            clubs[c['club_id']] = TM_LEAGUES[c['domestic_competition_id']]
    rows = []
    for t in csv.DictReader(io.TextIOWrapper(gzip.GzipFile(fileobj=io.BytesIO(_tm('transfers.csv.gz'))), 'utf-8')):
        d = t['transfer_date'][:10]
        if d < SEASON_START or d > datetime.now(timezone.utc).date().isoformat():
            continue
        if t['from_club_id'] not in clubs and t['to_club_id'] not in clubs:
            continue
        fee = float(t['transfer_fee']) if t['transfer_fee'] not in ('', 'nan') else None
        rows.append({'d': d, 'n': t['player_name'], 'pos': '', 'k': 'loan' if re.search(r'loan', t.get('transfer_fee') or '', re.I) else 'transfer',
                     'fr': t['from_club_name'], 'to': t['to_club_name'], 'lg': clubs.get(t['to_club_id']) or clubs.get(t['from_club_id']),
                     'fee': fee, 'mv': float(t['market_value_in_eur']) if t['market_value_in_eur'] not in ('', 'nan') else None})
    rows.sort(key=lambda r: (r['d'], r['fee'] or 0), reverse=True)
    return rows, []


def build(sport):
    p = os.path.join(OUT, f'{sport}.json')
    if sport == 'soccer' and '--force' not in sys.argv:
        try:     # Transfermarkt's dump updates weekly at most: once a day
            a = datetime.fromisoformat(json.load(open(p))['asof'].replace('Z', '+00:00'))
            if (datetime.now(timezone.utc) - a).total_seconds() < 86400:
                return
        except (OSError, ValueError, KeyError):
            pass
    rows, deals = soccer() if sport == 'soccer' else pro(sport)
    os.makedirs(OUT, exist_ok=True)
    with open(p + '.tmp', 'w') as f:
        json.dump({'asof': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'rows': rows, 'deals': deals}, f,
                  separators=(',', ':'), ensure_ascii=False)
    os.replace(p + '.tmp', p)
    from collections import Counter
    print(f'transactions {sport}: {len(rows)} rows, {len(deals)} trades, {dict(Counter(r["k"] for r in rows))}')


if __name__ == '__main__':
    for s in ([a for a in sys.argv[1:] if not a.startswith('--')] or SPORTS):
        try:
            build(s)
        except Exception as e:  # noqa: BLE001
            print(f'transactions {s}: skipped ({e!r})')   # a source down keeps the last file
