#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Reported NIL deals from headlines, into the ledger the NIL models read (data/nil_deals.json).

Google News search RSS (free, no key; headline, outlet, date and link only, as scripts/recruit_news.py). A headline
is a deal report when it names NIL or revenue share, a dollar amount and one player on a CFB / CBB board or recruit
class (scripts/names.py), and reads as done: an offer, an asking price, a valuation, a lawsuit, a rumour, a budget
or a pro contract is not one. A deal goes in the ledger (auto: 1) when

  - the headline names the player's school, or he is the only player of that name on the boards and a graded
    FBS / high-major one, and
  - a wire or national outlet carries it (TRUSTED), or two outlets carry the same player and amount (within 15%), and
  - it is no more than $8M a season (MAX_AUTO; larger ones have so far been multi-year totals).

Anything short of that waits in scripts/data/nil_deal_candidates.json (60 days) and is promoted when a second outlet
reports it. A row kept by hand is never changed; a player already in the ledger for the season is skipped.

Amount = dollars for one season: "$7.5M over two years" and "three-year, $2.3M" are divided by the years. Season:
football the fall's year (a report from November on is next fall's), basketball the spring's (a report from April
on is the season that starts that fall); a recruit's deal is his first season.

    python3 scripts/nil_deal_scan.py            # pull and add
    python3 scripts/nil_deal_scan.py --dry      # print what it would add
    python3 scripts/nil_deal_scan.py --test     # headline parser cases
"""
import datetime as dt
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import names  # noqa: E402
from recruit_news import gnews, SHORT  # noqa: E402

ROOT = os.path.dirname(HERE)
LEDGER = os.path.join(ROOT, 'data', 'nil_deals.json')
CAND = os.path.join(HERE, 'data', 'nil_deal_candidates.json')
KEEP = 60
MAX_AUTO = 8e6        # a season above this waits for a hand check (the largest reported so far is $7.5M)
TRUSTED = ('ESPN', 'On3', 'The Athletic', 'CBS Sports', 'AP News', 'Associated Press', 'Yahoo Sports', '247Sports', 'Sports Illustrated',
           'The New York Times', 'USA Today', 'Front Office Sports', 'Sportico', 'NBC Sports', 'FOX Sports')
QUERIES = ['NIL deal million', 'NIL deal worth', '"revenue share" deal million', 'NIL package million to return',
           'NIL million transfer portal commits', 'NIL contract million signs']
SPORT_WORD = {'cfb': 'college football', 'cbb': 'college basketball'}

NUM = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, '1': 1, '2': 2, '3': 3, '4': 4, '5': 5}
AMT = re.compile(r'\$\s?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s?(million|mil\b|m\b|k\b|thousand)?', re.I)
YEARS = re.compile(r'\b(one|two|three|four|five|\d)[- ]years?\b', re.I)
PER = re.compile(r'\b(?:per|a|each|every)[- ](?:year|season)\b|\bannually\b|\ba year\b', re.I)
TOPIC = re.compile(r"\bNIL\b|\brev(?:enue)?[- ]shar(?:e|ing)\b|\bcollective\b", re.I)
# not a done deal for one player
NOT = re.compile(r"\bvaluations?\b|\bvalued\b|\boffer(?:s|ed|ing)?\b|\bturn(?:s|ed|ing)? down\b|\breject|\bdeclin|\basking\b|\bprice tag\b|"
                 r"\bseek(?:s|ing)\b|\bdemand|\bwants?\b|\bcould\b|\bwould\b|\bmight\b|\bmay\b|\brumou?r|\bexpected\b|\bprojected\b|"
                 r"\bsu(?:es|ed|ing)\b|\blawsuit\b|\bowed\b|\bbuyout\b|\bbudgets?\b|\brosters?\b|\bpayroll\b|\bfund\b|\bdonat|\braises?\b|"
                 r"\bcoach(?:es|'s)?\b|\bWNBA\b|\bMLB\b|\bworth of\b|\bmarket value\b|\bestimate|"
                 r"\blos(?:t|es|ing)\b|\bleft on the table\b|\bpassed (?:on|up)\b|\bfake\b|\bhoax\b|\bdenie[sd]\b|\bdeny\b|\brefut|\bnot true\b|"
                 r"\?\s*$|^[\W]*(?:how|why|what|should|will|is|can|does|did)\b|\bdig\b|\bcalls? out\b|\bslams?\b|\breacts?\b|\bresponds?\b|\bif\b|\bfine[sd]?\b|\btax(?:es)?\b|\bcharity\b|\bbets?\b|\bgambl", re.I)
KIND = [('recruit', re.compile(r'\brecruit|\bcommit(?:s|ted|ment)?\b|\bsign(?:s|ed|ing) with\b|\b(?:five|four|three)-star\b', re.I)),
        ('portal', re.compile(r'\btransfer|\bportal\b', re.I)),
        ('re-sign', re.compile(r'\breturn|\bstay|\bre-?sign|\bextension\b|\bextend|\bremain|\bback (?:at|to|for)\b|\bretain', re.I))]


def amount_of(t):
    """dollars a season from a headline, None when it names none, several different ones or a range"""
    found = []
    for m in AMT.finditer(t):
        v = float(m.group(1).replace(',', '')); u = (m.group(2) or '').lower()
        v *= 1e6 if u in ('million', 'mil', 'm') else 1e3 if u in ('k', 'thousand') else 1
        if v >= 1e4: found.append((v, m.end()))
    if not found or len({v for v, _ in found}) > 1: return None
    v, end = found[0]
    if re.match(r'\s?(?:-|–|to)\s?\$?\d', t[end:]): return None             # "$4M to $6M"
    y = YEARS.search(t)
    if y and not PER.search(t): v /= NUM[y.group(1).lower()]
    return int(round(v, -3)) if 5e4 <= v <= 2e7 else None


def season_of(sport, date, cls=None):
    d = dt.date.fromisoformat(date)
    if cls: return int(cls) if sport == 'cfb' else int(cls) + 1
    if sport == 'cfb': return d.year + (1 if d.month >= 11 else 0)
    return d.year + (1 if d.month >= 4 else 0)


class Pool:
    """the players a headline can name: the college board and the recruit classes of one sport"""
    def __init__(self, sport, rows=None):
        self.sport, self.by, self.teams = sport, {}, {}
        for r in (self._load() if rows is None else rows):
            if not r.get('n'): continue
            self.by.setdefault(names.key(r['n']), []).append(r)
            if r.get('team'): self.teams.setdefault(names.team_key(r['team']), r['team'])

    def _load(self):
        def j(p):
            try:
                return json.load(open(os.path.join(ROOT, p), encoding='utf-8'))
            except (OSError, ValueError):
                return {}
        out = []
        if self.sport == 'cfb':
            from cfb_all import read_cfb_all
            A = read_cfb_all() or {}
            c = {k: i for i, k in enumerate(A.get('cols') or [])}
            for r in A.get('rows') or []:
                out.append({'n': r[c['name']], 'team': r[c['team']], 'pos': r[c['pos']],
                            'top': r[c['div']] == 'FBS' and (r[c['fv']] or 0) >= 40 and r[c['src']] != 'espn' and not r[c['carried']]})
            d = j('data/cfb_recruits.json')
            for cl in [{'year': d.get('next'), 'list': d.get('class') or []}] + (d.get('future') or []):
                for r in cl.get('list') or []:
                    out.append({'n': r.get('name'), 'team': r.get('team'), 'pos': r.get('pos'), 'cls': cl.get('year'), 'top': (r.get('rank') or 999) <= 300})
        else:
            d = j('static/data/cbb-all.json'); c = {k: i for i, k in enumerate(d.get('cols') or [])}
            hm = {'ACC', 'B10', 'B12', 'SEC', 'BE'}
            for r in d.get('rows') or []:
                out.append({'n': r[c['name']], 'team': r[c['team']], 'pos': r[c['pos']], 'top': r[c['conf']] in hm and (r[c['fv']] or 0) >= 35})
            for cl in j('data/cbb_recruits.json').get('classes') or []:
                for r in cl.get('list') or []:
                    out.append({'n': r.get('name'), 'team': r.get('team'), 'pos': r.get('pos'), 'cls': cl.get('year'), 'top': (r.get('rk') or 999) <= 100})
        return out

    def schools(self, title):
        """board schools named in the headline (1-3 word windows, the site's short forms)"""
        toks = [SHORT.get(w, w) for w in re.findall(r"[A-Za-z&][A-Za-z&'\.\-]*", re.sub(r"'s\b", '', title))]
        hit = set()
        for n in (3, 2, 1):
            for i in range(len(toks) - n + 1):
                k = names.team_key(' '.join(toks[i:i + n]))
                if k in self.teams: hit.add(self.teams[k])
        return hit

    def players(self, title):
        """rows whose full name is in the headline (2-4 word windows, longest first)"""
        toks = re.findall(r"[A-Za-z][A-Za-z'\.\-]*", re.sub(r"'s\b", '', title))
        for n in (4, 3, 2):
            for i in range(len(toks) - n + 1):
                rows = self.by.get(names.key(' '.join(toks[i:i + n])))
                if rows: return rows
        return []


def parse(title, pool, date):
    """a deal row from one headline, or None. sure: the player is pinned down (school named, or the one graded
    player of that name)"""
    if not TOPIC.search(title) or NOT.search(title): return None
    amt = amount_of(title)
    rows = pool.players(title)
    if not amt or not rows: return None
    named = pool.schools(title)
    at = [r for r in rows if r.get('team') in named]
    if len(at) == 1: r, sure = at[0], True
    elif len(rows) == 1 and not (named and rows[0].get('team') and not rows[0].get('cls')): r, sure = rows[0], bool(rows[0].get('top'))
    elif len(rows) == 1 and rows[0].get('cls') and len(named) == 1: r, sure = dict(rows[0], team=next(iter(named))), bool(rows[0].get('top'))
    else: return None
    if not r.get('team'): return None
    kind = 'recruit' if r.get('cls') else next((k for k, rx in KIND[1:] if rx.search(title)), 're-sign')
    out = {'sport': pool.sport, 'player': r['n'], 'team': r['team'], 'pos': r.get('pos') or '', 'season': season_of(pool.sport, date, r.get('cls')),
           'amount': amt, 'date': date, 'kind': kind}
    if r.get('cls'): out['cls'] = r['cls']
    return out, sure


def trusted(pub): return any(pub.lower().startswith(t.lower()) or t.lower() in pub.lower() for t in TRUSTED)


def near(a, b): return abs(a - b) <= 0.15 * max(a, b)


def settle(found, ledger, cands, today):
    """found: [(row, sure, outlet, url)]. Returns (new ledger rows, the waiting list)"""
    cut = (today - dt.timedelta(days=KEEP)).isoformat()
    wait = [c for c in cands if c['date'] >= cut]
    for row, sure, pub, url in found:
        k = (row['sport'], names.key(row['player']), row['team'])
        c = next((c for c in wait if (c['sport'], names.key(c['player']), c['team']) == k and near(c['amount'], row['amount'])), None)
        if c is None:
            c = dict(row, sure=sure, outlets={}); wait.append(c)
        c['outlets'].setdefault(pub or 'unknown', url); c['sure'] = c['sure'] or sure
        c['date'] = min(c['date'], row['date'])
    have = {(d['sport'], names.key(d['player']), d['season']) for d in ledger}
    add, keep = [], []
    for c in wait:
        k = (c['sport'], names.key(c['player']), c['season'])
        if k in have: continue
        if c['sure'] and c['amount'] <= MAX_AUTO and (any(trusted(p) for p in c['outlets']) or len(c['outlets']) >= 2):
            src = sorted(c['outlets'], key=lambda p: (not trusted(p), p))[:3]
            add.append({**{f: c[f] for f in ('sport', 'player', 'team', 'pos', 'season', 'amount', 'date', 'kind')}, **({'cls': c['cls']} if c.get('cls') else {}),
                        'source': ', '.join(src), 'url': c['outlets'][src[0]], 'auto': 1})
            have.add(k)
        else:
            keep.append(c)
    return add, keep


def pull(today, days=4):
    pools = {s: Pool(s) for s in SPORT_WORD}
    since = (today - dt.timedelta(days=days + 1)).isoformat()
    found, seen = [], set()
    for sport, word in SPORT_WORD.items():
        for q in QUERIES:
            for it in gnews(f'{word} {q} when:{days}d'):
                if it['date'] < since or (it['title'], it.get('pub')) in seen: continue
                seen.add((it['title'], it.get('pub')))
                hits = {s: parse(it['title'], p, it['date']) for s, p in pools.items()}
                hit = hits[sport] or next((h for h in hits.values() if h), None)
                if hit: found.append((hit[0], hit[1], it.get('pub') or '', it.get('url')))
            time.sleep(1)
    return found


def main():
    if '--test' in sys.argv: return _test()
    today = dt.datetime.now(dt.timezone.utc).date()
    L = json.load(open(LEDGER, encoding='utf-8'))
    try:
        cands = json.load(open(CAND, encoding='utf-8'))['waiting']
    except (OSError, ValueError, KeyError):
        cands = []
    found = pull(today, int(sys.argv[sys.argv.index('--days') + 1]) if '--days' in sys.argv else 4)
    add, keep = settle(found, L['deals'], cands, today)
    for a in add: print('add', json.dumps(a, ensure_ascii=False))
    print(f'nil deals: {len(found)} headlines read as deals, {len(add)} added, {len(keep)} waiting', file=sys.stderr)
    if '--dry' in sys.argv:
        for c in keep: print('wait', json.dumps(c, ensure_ascii=False))
        return
    if add:
        L['deals'] += add
        with open(LEDGER, 'w', encoding='utf-8') as f:
            f.write('{\n "_readme": ' + json.dumps(L['_readme'], ensure_ascii=False) + ',\n "deals": [\n' +
                    ',\n'.join('  ' + json.dumps(d, ensure_ascii=False) for d in L['deals']) + '\n ]\n}\n')
    with open(CAND, 'w', encoding='utf-8') as f:
        json.dump({'asof': today.isoformat(), 'waiting': keep}, f, ensure_ascii=False, indent=1)
        f.write('\n')


def _test():
    cfb = Pool('cfb', [{'n': 'Kamario Taylor', 'team': 'Mississippi State', 'pos': 'QB', 'top': True},
                       {'n': 'Arch Manning', 'team': 'Texas', 'pos': 'QB', 'top': True},
                       {'n': 'Jalen Williams', 'team': 'Akron', 'pos': 'WR', 'top': False},
                       {'n': 'Jalen Williams', 'team': 'Georgia', 'pos': 'LB', 'top': True},
                       {'n': 'Chris Henry Jr.', 'team': 'Ohio State', 'pos': 'WR', 'cls': 2026, 'top': True},
                       {'n': 'Jared Curtis', 'team': None, 'pos': 'QB', 'cls': 2027, 'top': True},
                       {'n': 'Sam Leavitt', 'team': 'LSU', 'pos': 'QB', 'top': True}])
    D = '2026-11-26'
    cases = [
        ("Kamario Taylor to return to Mississippi State on $7.5 million NIL deal", ('Kamario Taylor', 'Mississippi State', 7500000, 2027, 're-sign', True)),
        ("Sources: Mississippi State QB Kamario Taylor signs two-year, $15M revenue share deal to stay", ('Kamario Taylor', 'Mississippi State', 7500000, 2027, 're-sign', True)),
        ("Arch Manning's NIL deal worth $6.8 million a year over two years, per report", ('Arch Manning', 'Texas', 6800000, 2027, 're-sign', True)),
        ("Sam Leavitt lands $5M NIL package after transfer to LSU", ('Sam Leavitt', 'LSU', 5000000, 2027, 'portal', True)),
        ("Five-star WR Chris Henry Jr. signs NIL deal worth $1.2 million with Ohio State", ('Chris Henry Jr.', 'Ohio State', 1200000, 2026, 'recruit', True)),
        ("Jared Curtis commits to Vanderbilt with $750K NIL deal", None),          # Vanderbilt is not a board school in this pool
        ("Georgia LB Jalen Williams agrees to $900,000 NIL deal", ('Jalen Williams', 'Georgia', 900000, 2027, 're-sign', True)),
        ("Jalen Williams agrees to $900,000 NIL deal", None),                          # two players of the name, no school
        ("Arch Manning NIL valuation climbs to $6.8 million", None),
        ("Kamario Taylor turned down $9 million NIL offer from SEC rival", None),
        ("Kamario Taylor could get $7.5 million in NIL to stay at Mississippi State", None),
        ("Mississippi State collective raises $12 million for NIL roster", None),
        ("Arch Manning signs NIL deal with Red Bull", None),
        ("Sam Leavitt NIL deal reportedly between $4 million to $6 million at LSU", None),
        ("Jalen Williams signs $240 million extension with Thunder", None),
        ("Is Kamario Taylor's $7.5 million NIL deal a mistake for Mississippi State?", None),
        ("How Kamario Taylor's $7.5 million NIL deal will affect Mississippi State", None),
        ("Analyst calls out Mississippi State over Kamario Taylor's reported $7.5M NIL deal", None),
    ]
    bad = 0
    for t, want in cases:
        h = parse(t, cfb, D)
        got = (h[0]['player'], h[0]['team'], h[0]['amount'], h[0]['season'], h[0]['kind'], h[1]) if h else None
        if got != want: bad += 1; print('FAIL', t, '\n  got ', got, '\n  want', want)
    # two outlets promote an unsure one; a trusted outlet alone adds a sure one; a player in the ledger is skipped
    row = lambda **k: dict({'sport': 'cfb', 'player': 'Kamario Taylor', 'team': 'Mississippi State', 'pos': 'QB', 'season': 2027, 'amount': 7500000, 'date': D, 'kind': 're-sign'}, **k)
    today = dt.date(2026, 11, 27)
    a, w = settle([(row(), True, 'Some Blog', 'u1')], [], [], today); ok = (len(a), len(w)) == (0, 1)
    a, w = settle([(row(amount=7400000), True, 'Other Site', 'u2')], [], w, today); ok &= (len(a), len(w)) == (1, 0) and a[0]['amount'] == 7500000
    a, w = settle([(row(), True, 'ESPN', 'u')], [], [], today); ok &= len(a) == 1 and a[0]['auto'] == 1
    a, w = settle([(row(), False, 'ESPN', 'u')], [], [], today); ok &= (len(a), len(w)) == (0, 1)
    a, w = settle([(row(), True, 'ESPN', 'u')], [row()], [], today); ok &= (len(a), len(w)) == (0, 0)
    if not ok: bad += 1; print('FAIL settle')
    print(f'{len(cases) + 1 - bad} of {len(cases) + 1} pass')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
