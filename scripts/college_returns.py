#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""College return and NIL deal reports: who has re-signed or announced a return for next season, at what reported
price, and who has since entered the portal or declared. Feeds data/college_returns.json, which the boards read:
a reported return locks the player to his roster for next season (cfb: fetch_cfb.mjs Transfer%, transfer watch,
team builder, roster projections; cbb: cbb_market.py).

    python3 scripts/college_returns.py                 # pull the last 10 days, merge into data/college_returns.json
    python3 scripts/college_returns.py --days 60       # a longer look back
    python3 scripts/college_returns.py --backtest      # 2025-26 cycle: reported returners vs the portal (CFB)

Sources: Google News search RSS (on3.com is Cloudflare-blocked from datacenter IPs; its stories, ESPN's "Sources"
items and the team beats come through the RSS headline), plus RotoWire's college feeds (scripts/rotowire_moves.py
caches; "Re-signs with Missouri for 2027"). Headline only. A player is named in a headline when a run of its words is
a board player's name (scripts/names.py keys); a name two board players share needs the school in the headline too.
"""
import argparse
import datetime as dt
import html
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import names  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'college_returns.json')
TEST_OUT = os.path.join(ROOT, 'data', 'college_returns_backtest.json')
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'

SPORT = {
    'cfb': {'word': 'football', 'roto': 'cfootball', 'season': lambda d: d.year if d.month >= 7 else d.year - 1},
    'cbb': {'word': 'basketball', 'roto': 'cbasketball', 'season': lambda d: d.year + 1 if d.month >= 7 else d.year},
}
# Google News search terms; {w} is the sport word, {y} next season's year
QUERIES = [
    '("re-signs" OR "re-signed" OR "re-signing") {w}',
    '("return for {y}" OR "returning for {y}" OR "return in {y}" OR "back for {y}") {w}',
    '("deal to return" OR "signs to return" OR "signed to return" OR "agrees to return") {w}',
    '("announces return" OR "will return to" OR "decision to return" OR "decides to return" OR "commits to return") {w}',
    '("NIL deal" OR "revenue share" OR "million deal") (re-signs OR return OR stay) {w}',
    '("announces return" OR "announces he will return" OR "will return for" OR "returning to") college {w} {y}',
    '("staying at" OR "stays at" OR "will stay at" OR "remain at" OR "back with") college {w} {y}',
]
# the backtest also reads the recruiting sites' own pages through the same search (more of the beat stories)
SITES = ['on3.com', '247sports.com', 'si.com', 'rivals.com']

# headline readings. RET: he is back next season (signed, agreed or announced); PEND: a deal reported close, not done;
# OUT: he has entered the portal or declared (newest report wins); NEG: speculation, questions and other "returns"
RET = re.compile(r"\bre-?sign(s|ed|ing)?\b|\b(deal|contract|agreement|extension|terms) to (return|stay|remain)\b|"
                 r"\bsigns? (a |his )?(new )?(nil )?(deal|contract|extension)?\s*to (return|stay|remain)\b|"
                 r"\bannounces? (his |a )?return\b|\bannounces? (he will|he'll|that he will|he is) (return|stay|be back)|"
                 r"\b(will|to|set to|plans to|intends to|decides to|decided to|commits? to|chooses to|elects to) "
                 r"(return|stay|remain)\b(?! (from|to (practice|action|the field|the lineup|play)))|"
                 r"\breturning (to [\w .&'-]+ )?(for|in) (20\d\d|next season|his|another|one more)\b|"
                 r"\b(confirms?|reaffirms?) (his |he'll |he will )?(return|commitment)\b|\bdecision to (stay|return)\b|"
                 r"\b(back|return|returns) (for|in) (20\d\d|another season|one more|next season|his (sophomore|junior|senior|redshirt))|"
                 r"\bstay(s|ing)? (at|with|in) [\w .&'-]+ for (20\d\d|next season|another)|\bretains?\b|\bretained\b|"
                 r"\bis staying\b|\bstays? put\b|\bcoming back\b|\bfinali[sz](es|ing|ed) (a |his )?(deal|contract|return)",
                 re.I)
PEND = re.compile(r"\bplan(s|ning)? to\b|\binformed\b|\bfinali[sz]ing\b|\bclose to\b|\bnear(s|ing)? (a )?(deal|agreement)|\bexpected to (sign|re-?sign|return)|"
                  r"\bin talks\b|\bnegotiat", re.I)
OUT_RE = re.compile(r"\b(enter|enters|entered|entering|in|to enter|will enter|plans to enter|hits?|into) (the )?(transfer )?portal\b|"
                    r"\bdeclares? for (the )?(20\d\d )?(nfl|nba) draft\b|\b(enter|enters|entering|to enter|will enter) (the )?(20\d\d )?(nfl|nba) draft\b|"
                    r"\bstay(s|ing)? in (the )?(nfl|nba) draft\b", re.I)
NEG = re.compile(r"\?|\bpotential(ly)?\b|\bcould\b|\bmay\b|\bmight\b|\bif\b|\bwould\b|\bwhether\b|\brumou?rs?\b|\bhopes?\b|"
                 r"\bworking to\b|\bwants? to\b|\bpush(es|ing)? to\b|\bpitch\b|\bwill [\w .'-]+ (stay|return)\b|"
                 r"\bout for (the )?season\b|\b(from|after) (injury|surgery)\b|\breturns? (to|from) (practice|action|the field|"
                 r"the lineup|play|injury|campus)|\bkick(off)? return|\bpunt return|\breturn (yards|touchdown|td|man|specialist)|"
                 r"\bbowl\b|\bcoach(es|ing)?\b(?! (says|confirms))|\bcoordinator\b|\bdeadline\b|\bwatch\b|\btracker\b|\bpredict|"
                 r"\bodds\b|\bmock\b|\bsigning day\b|\bcommits? to\b(?! return)|\bflip|\bwilling\b|\boffer(s|ed)?\b|\bpay for\b|"
                 r"\bturn(s|ed)? down\b|\bbelieve|\bthink|\bconfident\b|\bI\b|\bI'm\b|\bshould\b|\bopinion\b|\b\d+(st|nd|rd|th) season\b", re.I)
# pro clubs that share a word with a college headline (Vikings, Chiefs): a pro re-signing is not a college return
PRO = {'cfb': re.compile(r"\b(nfl|vikings|packers|bears|lions|cowboys|giants|eagles|commanders|49ers|niners|seahawks|rams|cardinals|"
                         r"saints|falcons|panthers|buccaneers|bucs|patriots|jets|bills|dolphins|ravens|steelers|browns|bengals|"
                         r"texans|colts|jaguars|titans|chiefs|raiders|chargers|broncos|cfl|ufl|premier league|mls)\b", re.I),
       'cbb': re.compile(r"\b(nba|wnba|g league|lakers|celtics|knicks|nets|76ers|sixers|raptors|bulls|cavaliers|cavs|pistons|"
                         r"pacers|bucks|hawks|hornets|heat|magic|wizards|nuggets|timberwolves|thunder|trail blazers|blazers|jazz|"
                         r"warriors|clippers|suns|kings|mavericks|mavs|rockets|grizzlies|pelicans|spurs|euroleague)\b", re.I)}
AMT = re.compile(r"\$\s?(\d+(?:\.\d+)?)\s*(million|mil\b|m\b|k\b|thousand)?", re.I)
YEAR = re.compile(r"\b(20\d\d)(-\d\d)?\b|'(\d\d)\b")
NEXT_WORDS = re.compile(r"next (season|year)|sophomore|junior|senior|redshirt|another (season|year)|one more|final (season|year)", re.I)


def gnews(q, timeout=25):
    u = 'https://news.google.com/rss/search?' + urllib.parse.urlencode({'q': q, 'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en'})
    for i in range(3):
        r = subprocess.run(['curl', '-sS', '-m', str(timeout), '-A', UA, u], capture_output=True, text=True)
        if r.returncode == 0 and '<rss' in r.stdout: break
        time.sleep(2 + 3 * i)
    else:
        raise RuntimeError(f'google news: no feed for {q!r}')
    out = []
    for it in re.findall(r'<item>(.*?)</item>', r.stdout, re.S):
        raw = html.unescape(html.unescape(re.search(r'<title>(.*?)</title>', it, re.S).group(1)))
        pub = html.unescape(re.search(r'<source[^>]*>(.*?)</source>', it, re.S).group(1)) if '<source' in it else ''
        link = re.search(r'<link>(.*?)</link>', it, re.S)
        when = dt.datetime.strptime(re.search(r'<pubDate>(.*?)</pubDate>', it).group(1)[5:25], '%d %b %Y %H:%M:%S')
        title = re.sub(r'\s+-\s+[^-]+$', '', raw).strip() if pub and raw.endswith(pub) else raw.strip()
        out.append({'title': title, 'pub': pub, 'date': when.strftime('%Y-%m-%dT%H:%MZ'), 'url': link.group(1).strip() if link else None})
    return out


def amount(t):
    """reported deal value in dollars (the largest stated), or None"""
    best = None
    for m in AMT.finditer(t):
        v, u = float(m.group(1)), (m.group(2) or '').lower()
        v *= 1e6 if u.startswith('m') else 1e3 if u in ('k', 'thousand') else 1
        if v >= 5e4 and (best is None or v > best): best = v
    return int(best) if best else None


def reading(t, target, sport='cfb'):
    """(kind, pending) of a headline: kind 'return', 'out' or None. A return must be for the target season: a year in
    the headline other than it rules the headline out (last year's news, a "2026 class" story)"""
    yrs = {int(a) if a else 2000 + int(c) for a, _, c in YEAR.findall(t)}
    if OUT_RE.search(t) and not re.search(r"\bwithdraw|\bpull(s|ed)? (out|name)|\bwon'?t|\bnot (enter|go)", t, re.I):
        return ('out', False) if not re.search(r'\?|\bcould\b|\bmight\b|\bmay\b|\bconsider|\bweigh|\bexpected to\b|\bwould\b|\bif\b', t, re.I) else (None, False)
    if not RET.search(t) or NEG.search(t): return (None, False)
    if re.search(r'\bthis (season|year)\b|\bgranted\b', t, re.I): return (None, False)
    if sport == 'cbb':      # a basketball season is two years: "2027-28", or "next season"
        if not re.search(rf"\b{target - 1}-({target % 100:02d}|{target})\b|\bnext (season|year)\b", t, re.I): return (None, False)
    elif yrs and target not in yrs: return (None, False)
    return ('return', bool(PEND.search(t)))


class Index:
    """board players by name key; .find(title) -> rows named in the title (school in the title settles shared names)"""
    def __init__(self, rows):
        self.by = {}
        for r in rows:
            k = names.key(r['name'])
            if len(k.split()) >= 2: self.by.setdefault(k, []).append(r)

    def find(self, title):
        w = re.findall(r"[A-Za-z0-9.'’-]+", title.replace('’', "'"))
        tk = names.team_key(title) + ' ' + ' '.join(names.TEAM_ALIAS.get(names.team_key(x), '') for x in w)
        hits, used = [], set()
        for n in (4, 3, 2):
            for i in range(len(w) - n + 1):
                if any(j in used for j in range(i, i + n)): continue
                k = names.key(' '.join(w[i:i + n]).rstrip("'s").replace("'s ", ' '))
                if k.endswith(' s'): k = k[:-2]
                rows = self.by.get(k) or self.by.get(names.key(re.sub(r"'s$", '', ' '.join(w[i:i + n]))))
                if not rows: continue
                if len(rows) > 1:
                    at = [r for r in rows if any(names.team_key(t) and names.team_key(t) in tk for t in r['_teams'])]
                    # no school named: the far better player (news is about the prominent one), else unread
                    fv = sorted(rows, key=lambda r: -(r.get('fv') or 0))
                    rows = at if len(at) == 1 else fv[:1] if (fv[0].get('fv') or 0) - (fv[1].get('fv') or 0) >= 10 and not at else []
                    if len(rows) != 1: continue
                hits.append(rows[0]); used.update(range(i, i + n))
        return hits


def board_rows(sport):
    """every board player: name, school, position, Transfer% (for the backtest and lock reads)"""
    rows = []
    if sport == 'cfb':
        d = json.load(open(os.path.join(ROOT, 'static', 'data', 'cfb-all.json')))
        c = {n: i for i, n in enumerate(d['cols'])}
        for x in d['rows']:
            rows.append({'name': x[c['name']], 'team': x[c['team']], 'pos': x[c['pos']], 'tp': x[c['transferP']],
                         'fv': x[c['fv']], 'xnil': x[c['xnil']], 'ynil': x[c['ynil']], 'div': x[c['div']], '_teams': [x[c['team']]],
                         'cls': x[c['cls']], 'conf': x[c['conf']], 'logo': x[c['logo']], 'photo': x[c['photo']],
                         'locked': bool(x[c['lock']]) if 'lock' in c else False})
        pr = json.load(open(os.path.join(ROOT, 'data', 'cfb_portal.json')))['moves']
        ix = {(names.key(r['name']), names.team_key(r['team'])): r for r in rows}
        for m in pr:      # a mover's old school names him in last cycle's return stories
            r = ix.get((names.key(m['name']), names.team_key(m.get('to') or '')))
            if r and m.get('from'): r['_teams'].append(m['from'])
    else:
        d = json.load(open(os.path.join(ROOT, 'static', 'data', 'cbb-all.json')))
        c = {n: i for i, n in enumerate(d['cols'])}
        for x in d['rows']:
            rows.append({'name': x[c['name']], 'team': x[c['team']], 'pos': x[c['pos']], 'tp': None, 'fv': x[c['fv']],
                         'xnil': None, 'ynil': None, '_teams': [x[c['team']]]})
    return [r for r in rows if r['name'] and r['team']]


def roto_items(sport):
    f = os.path.join(ROOT, 'scripts', 'data', 'rotowire_moves', SPORT[sport]['roto'] + '.json')
    if not os.path.exists(f): return []
    out = []
    for x in json.load(open(f)).get('moves', {}).values():
        t = f"{x.get('player')} {x.get('head', '')}. {x.get('body', '')}"
        out.append({'title': t, 'pub': 'RotoWire', 'date': x['d'] + 'T12:00Z', 'url': None, '_name': x.get('player')})
    return out


def collect(sport, items, target, ix, since=None):
    """headline items -> report rows {name, team, pos, kind, pend, amt, date, src, title}"""
    out, seen = [], set()
    for it in items:
        if since and it['date'] < since: continue
        kind, pend = reading(it['title'], target, sport)
        if not kind or PRO[sport].search(it['title']): continue
        hits = ix.find(it['title'])
        if it.get('_name'): hits = [r for r in hits if names.same(r['name'], it['_name'])][:1]
        if len(hits) != 1: continue     # a list story ("Four Gophers starters confirm...") or nobody on the board
        r = hits[0]
        # the school, when the headline names one, must be his (a "commits to" story about his new school is a move)
        k = (names.key(r['name']), kind, it['date'][:10])
        if k in seen: continue
        seen.add(k)
        out.append({'name': r['name'], 'team': r['team'], 'pos': r['pos'], 'kind': kind, 'pend': pend or None,
                    'amt': amount(it['title']) if kind == 'return' else None, 'date': it['date'],
                    'src': it['pub'] or None, 'title': it['title'][:200], 'url': it.get('url')})
    return out


def pull(sport, days, target, ix):
    since = (dt.datetime.now(dt.UTC).replace(tzinfo=None) - dt.timedelta(days=days)).strftime('%Y-%m-%dT%H:%MZ')
    items = []
    for q in QUERIES:
        items += gnews(q.format(w=SPORT[sport]['word'], y=target) + f' when:{days}d')
        time.sleep(0.6)
    items += roto_items(sport)
    return collect(sport, items, target, ix, since)


def locks(feed):
    """newest report per player wins: a return (signed, or reported close) locks him; a later portal entry or
    declaration unlocks. The reported value is the largest any of his return stories gives"""
    by = {}
    for x in sorted(feed, key=lambda x: x['date']):
        k = names.key(x['name']) + '|' + names.team_key(x['team'])
        b = by.setdefault(k, {'name': x['name'], 'team': x['team'], 'pos': x['pos'], 'n': 0, 'amt': None, 'srcs': set()})
        if x['kind'] == 'return':
            b['n'] += 1; b['srcs'].add(x['src'] or '')
            b.setdefault('first', x['date'][:10])
            if x['amt'] and (b['amt'] is None or x['amt'] > b['amt']): b['amt'] = x['amt']
            if b.get('state') != 'signed': b['state'] = 'pending' if x['pend'] else 'signed'
            b['date'] = x['date'][:10]
        else:
            b['state'] = 'out'; b['date'] = x['date'][:10]
    out = []
    for b in by.values():
        if b.get('state') in ('signed', 'pending'):
            out.append({'name': b['name'], 'team': b['team'], 'pos': b['pos'], 'state': b['state'], 'amt': b['amt'],
                        'date': b['date'], 'first': b.get('first'), 'n': b['n'], 'srcs': len(b['srcs'])})
    return sorted(out, key=lambda x: (-(x['amt'] or 0), x['name']))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=10)
    ap.add_argument('--sport', default='cfb,cbb')
    ap.add_argument('--backtest', action='store_true')
    a = ap.parse_args()
    if a.backtest: return backtest()
    now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    prev = json.load(open(OUT)) if os.path.exists(OUT) else {}
    # Transfer% for a locked player: last cycle's measured rate among reported returners, only once the backtest passes
    # (CFB 2025-26: data/college_returns_backtest.json); a sport without a passing test gets the tag only
    lockP = {}
    if os.path.exists(TEST_OUT):
        t = json.load(open(TEST_OUT))
        if t.get('pass'): lockP['cfb'] = t['rate']
    res = {'asof': now.strftime('%Y-%m-%d'), 'lockP': lockP, 'test': {k: v for k, v in (json.load(open(TEST_OUT)) if os.path.exists(TEST_OUT) else {}).items() if k != 'players_list'}, 'sports': {}}
    for s in a.sport.split(','):
        target = SPORT[s]['season'](now) + 1
        ix = Index(board_rows(s))
        old = prev.get('sports', {}).get(s, {})
        feed = [x for x in old.get('feed', []) if old.get('target') == target]
        feed = [x for x in feed if reading(x['title'], target, s)[0] == x['kind']]   # re-read with today's rules
        try:
            new = pull(s, a.days, target, ix)
        except Exception as e:      # a dead feed keeps what was pulled before
            print(f'{s}: pull failed ({e}); keeping the cached feed', file=sys.stderr); new = []
        have = {(names.key(x['name']), x['kind'], x['date'][:10]) for x in feed}
        feed += [x for x in new if (names.key(x['name']), x['kind'], x['date'][:10]) not in have]
        feed.sort(key=lambda x: x['date'], reverse=True)
        lk = locks(feed)
        # board fields for the re-signed table; tp0 = Transfer% before the report (kept from the first run that saw him)
        was = {names.key(x['name']) + '|' + names.team_key(x['team']): x for x in old.get('locks', [])}
        by = {(names.key(r['name']), names.team_key(r['team'])): r for r in ix_rows(ix)}
        for x in lk:
            r = by.get((names.key(x['name']), names.team_key(x['team']))) or {}
            for f in ('cls', 'conf', 'logo', 'photo', 'fv', 'xnil', 'ynil'): x[f] = r.get(f)
            w = was.get(names.key(x['name']) + '|' + names.team_key(x['team']))
            x['tp0'] = w['tp0'] if w and w.get('tp0') is not None else (r.get('tp') if not r.get('locked') else None)
        res['sports'][s] = {'target': target, 'feed': feed, 'locks': lk}
        print(f"{s} {target}: {len(feed)} reports ({len(new)} pulled), {len(res['sports'][s]['locks'])} locked")
    for s, v in prev.get('sports', {}).items(): res['sports'].setdefault(s, v)
    with open(OUT, 'w') as f: json.dump(res, f, indent=1, ensure_ascii=False)


# ---- backtest: did last cycle's reported returners stay? -------------------------------------------------------
def backtest():
    """2025-26 CFB cycle. Reports dated Oct 15 2025 - Jan 1 2026 (before the Jan 2 portal window) of a return for
    2026; outcome: in data/cfb_portal.json's 2026 moves out of that school. Compared with Transfer% for the same
    players (their 2026 board rows: one year on, the closest held read the site has of the model for them)."""
    ix = Index(board_rows('cfb'))
    items, d0 = [], dt.date(2025, 10, 15)
    qs = [q.format(w='football', y=2026) for q in QUERIES] + \
         [f'site:{x} (re-signs OR "return for 2026" OR "announces return" OR "deal to return" OR "will return")' for x in SITES]
    while d0 < dt.date(2026, 1, 2):
        d1 = min(d0 + dt.timedelta(days=4), dt.date(2026, 1, 2))
        for q in qs:
            items += gnews(q + f' after:{d0} before:{d1}')
            time.sleep(0.5)
        d0 = d1
    rep = collect('cfb', items, 2026, ix)
    lk = [x for x in locks(rep)]
    moves = json.load(open(os.path.join(ROOT, 'data', 'cfb_portal.json')))['moves']
    mv = {(names.key(m['name']), names.team_key(m['from'])): m for m in moves if m.get('from')}
    rows = {(names.key(r['name']), names.team_key(t)): r for r in ix_rows(ix) for t in r['_teams']}
    out = []
    for x in lk:
        k = (names.key(x['name']), names.team_key(x['team']))
        # the board row is the player's 2026 school; his return story named the 2025 school (same unless he moved)
        r = next((r for (kk, _), r in rows.items() if kk == k[0] and names.team_key(x['team']) in [names.team_key(t) for t in r['_teams']]), None)
        moved = any(kk[0] == k[0] and names.team_key(m['from']) in [names.team_key(t) for t in (r['_teams'] if r else [x['team']])]
                    and m.get('date', '9') >= (x.get('first') or '') for kk, m in mv.items() if kk[0] == k[0])
        out.append({**x, 'moved': moved, 'tp': r['tp'] if r else None, 'fv': r['fv'] if r else None})
    n = len(out); m = sum(o['moved'] for o in out)
    tp = [o for o in out if o['tp'] is not None]
    # Laplace-shrunk lock rate, cross-validated: each player's lock P is the rate among the others
    def ll(p, y): p = min(max(p, 1e-4), 1 - 1e-4); return -(y * math.log(p) + (1 - y) * math.log(1 - p))
    cv = [ll((m - o['moved'] + 0.5) / (n - 1 + 1), o['moved']) for o in tp]
    base = [ll(o['tp'], o['moved']) for o in tp]
    diff = [b - c for b, c in zip(base, cv)]
    mu = sum(diff) / len(diff); sd = (sum((d - mu) ** 2 for d in diff) / (len(diff) - 1)) ** .5
    rate = (m + 0.5) / (n + 1)
    lo, hi = wilson(m, n)
    res = {'cycle': '2025-26', 'window': ['2025-10-15', '2026-01-01'], 'reports': len(rep), 'players': n, 'moved': m,
           'rate': round(rate, 4), 'wilson95': [round(lo, 4), round(hi, 4)],
           'with_tp': len(tp), 'tp_mean': round(sum(o['tp'] for o in tp) / len(tp), 4),
           'logloss_model': round(sum(base) / len(base), 4), 'logloss_lock_cv': round(sum(cv) / len(cv), 4),
           'gain_t': round(mu / (sd / len(diff) ** .5), 2), 'pass': mu / (sd / len(diff) ** .5) >= 2,
           'players_list': sorted(out, key=lambda o: (not o['moved'], o['name']))}
    json.dump(res, open(TEST_OUT, 'w'), indent=1, ensure_ascii=False)
    print({k: v for k, v in res.items() if k != 'players_list'})


def ix_rows(ix):
    seen = set()
    for rs in ix.by.values():
        for r in rs:
            if id(r) not in seen: seen.add(id(r)); yield r


def wilson(k, n, z=1.96):
    if not n: return 0, 1
    p = k / n; d = 1 + z * z / n; c = p + z * z / (2 * n); h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - h) / d, (c + h) / d


if __name__ == '__main__':
    main()
