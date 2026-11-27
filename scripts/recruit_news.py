#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Recruiting news for the CFB and CBB recruit tabs: commitments, decommitments, flips, portal entries, portal
commitments and ranking moves, read from 247Sports and On3 headlines.

247sports.com serves a JS bot wall to scripts and on3.com blocks datacenter IPs (Nov 6/11/14 2026), so both come
through Google News search RSS (free, no key): `site:247sports.com` / `site:on3.com` queries, headline, date and link
only (no article text, nothing behind VIP/On3+). A move both sites report is one row with both sources (same player
key, move and school within 4 days). Players join the recruit classes and portal lists by the shared matcher
(scripts/names.py); a headline whose player isn't on a board is kept only when its pattern names him plainly
("X commits to Y").

data/recruit_news.json {asof, cfb: [rows], cbb: [rows]}, newest first, last 120 days, merged with the previous file:
  d date, n player, pos, cls class year, k move (commit / decommit / flip / portal / transfer / rank / cb), to school,
  fr school left, src {"247": url, "on3": url}, t headline, b 1 when the player is on a board

247Sports Crystal Ball alerts (k "cb", Nov 19 2026): headlines that a Crystal Ball went in on a board player
(`intitle:"crystal ball"` / `intitle:"where will"` on 247sports.com), with the school when the headline names it.
Alerts only: they move nothing on the boards and are not a model input (about 4% of Crystal Ball headlines name
player and school; scripts/research/recruit_experts_nov19/README.md).

    python3 scripts/recruit_news.py           # pull and merge
    python3 scripts/recruit_news.py --test    # headline parser cases
"""
import datetime as dt
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import names  # noqa: E402

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'recruit_news.json')
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'
KEEP_DAYS = 120
SITES = {'247': '247sports.com', 'on3': 'on3.com'}
SPORT_WORD = {'cfb': 'football', 'cbb': 'basketball'}
QUERIES = ['commits', 'commitment', 'decommits', 'flips', 'reclassifies', 'signs', '"transfer portal"', 'rankings']

OTHER = re.compile(r"\bwomen'?s\b|\bWBB\b|\bgirls\b|\blady\b|softball|volleyball|baseball|soccer|wrestling|\btrack\b|"
                   r"\bgolf\b|lacrosse|gymnast|\bswim", re.I)
NOISE = re.compile(r"\bcommits? to (play|participate|compete) in\b|all-american bowl|polynesian bowl|all-star|"
                   r"\btracking\b|\bcommit list\b|\bcommits? (playing|in action|performed|stats)\b|\bwhere .* commits\b|"
                   r"\bpredict|\bcrystal ball\b|\bRPM\b|\?|\bcould\b|\bwould\b|\bshould\b|\bexpected to\b|\bnear(ing)?\b|"
                   r"\btrending\b|\bset to (commit|decide|announce)\b|\bdecision date\b|\bto announce\b|\bannounce(s|d)? (his )?"
                   r"(decision|commitment) date\b|\bfinalists?\b|\btop \d+ schools\b|\bcuts? list\b|\bvisits?\b", re.I)
KIND = [
    ('decommit', re.compile(r"\bde-?commit|\breopens? (his )?recruitment|\bbacks? (off|away from) (his )?(commitment|pledge)|"
                            r"\bloses? (a |\w+ )?commit(ment)?\b|\bparts? ways with (his )?commitment", re.I)),
    ('flip', re.compile(r"\bflip(s|ped)?\b(?! the script)", re.I)),
    ('portal', re.compile(r"\b(enter|enters|entering|entered|hits|into|in) the (transfer )?portal\b|\bto (enter|hit) (the )?portal\b|"
                          r"\bportal entry\b|\bplaces? (his )?name in the portal\b", re.I)),
    ('transfer', re.compile(r"\btransfer\b[^:]*\b(commits?|signs?|commitment|lands?|lands|lands a|lands transfer|picks)\b|"
                            r"\b(commits?|lands?|adds?|picks up)\b[^:]*\b(transfer|from the portal|portal)\b", re.I)),
    ('sign', re.compile(r"(?<!re-)(?<!re)\bsigns? with\b|\bsigned with\b|\bsigning of\b|\binks?\b|\bofficially signs?\b", re.I)),
    ('commit', re.compile(r"\bcommit(s|ted)? to\b|\bcommits\b|\bcommitment (to|from)\b|\bpledges?\b|\bverbal(ly)? commit|"
                          r"\bCOMMIT\b|\blands?\b|\bgets? (a )?commit|\bpicks up (a )?commit|\bsecures? (a )?commit|"
                          r"\bchooses\b|\bpicks\b", re.I)),
    ('rank', re.compile(r"\b(rises|climbs|jumps|moves up|falls|drops|slides|soars) (up )?(to|into|in|inside|out of|within)\b[^,]*\b"
                        r"(rankings?|No\. ?\d+|Top ?247|top-?\d+|five-star|four-star|5-star|4-star)\b|\brankings? (update|release)\b|\bbumped to\b|\bearns? "
                        r"(a |his )?(fifth|5th) star\b|\bnew (Top247|rankings)\b|\bre-?rank", re.I)),
]
RECLASS_TO = re.compile(r"\breclass(?:if(?:y|ies|ied|ying|ication))?\b[^,:;]*?\b(?:to|into)\s+(?:the\s+)?(?:class\s+of\s+)?"
                        r"(?:'(\d\d)\b|(20[2-3]\d)\b)", re.I)
RECLASS_FROM = re.compile(r"\breclass(?:if(?:y|ies|ied|ying|ication))?\b\s+(?:up\s+|down\s+)?from\s+(?:the\s+)?(?:class\s+of\s+)?"
                          r"(?:'(\d\d)\b|(20[2-3]\d)\b)", re.I)
NOUN_COMMIT = re.compile(r"\bcommit(s)?\b(?! to)", re.I)
POS_RE = re.compile(r"\b(QB|RB|WR|TE|OL|OT|OG|IOL|DL|DT|DE|EDGE|LB|CB|S|DB|ATH|K|P|LS|APB|PG|SG|SF|PF|CG|C)\b")
POS_WORD = {'quarterback': 'QB', 'running back': 'RB', 'receiver': 'WR', 'wideout': 'WR', 'tight end': 'TE',
            'offensive lineman': 'OL', 'offensive tackle': 'OT', 'defensive lineman': 'DL', 'defensive tackle': 'DT',
            'defensive end': 'DE', 'edge rusher': 'EDGE', 'edge': 'EDGE', 'linebacker': 'LB', 'cornerback': 'CB',
            'safety': 'S', 'athlete': 'ATH', 'kicker': 'K', 'punter': 'P', 'point guard': 'PG', 'shooting guard': 'SG',
            'combo guard': 'CG', 'guard': 'G', 'wing': 'W', 'small forward': 'SF', 'power forward': 'PF',
            'forward': 'F', 'center': 'C', 'big man': 'C'}
YEAR = re.compile(r"\b(?:class of )?(20[2-3]\d)\b", re.I)
DESC = (r"(?:(?:(?i:No\. ?\d+|\d+-star|five-star|four-star|three-star|top-?\d+|top247|composite|elite|blue-chip|in-state|"
        r"juco|jucco|transfer|former|ex-|class of|20[2-3]\d|national|ranked|top|local|prized|coveted|standout|prospect|"
        r"recruit|target|commit)|[A-Z]{1,4}|\w+(?:-\w+)? (?:quarterback|running back|receiver|tight end|lineman|tackle|end|"
        r"linebacker|cornerback|safety|athlete|guard|forward|center|wing|rusher))[,']?s? )*")
NAME = r"((?:[A-Z][a-zA-Z'\.\-]+|[A-Z]\.[A-Z]\.)(?: (?:[A-Z][a-zA-Z'\.\-]+|Jr\.?|Sr\.?|II|III|IV)){1,3})"
SCHOOL = r"([A-Z][A-Za-z&'\.\-]+(?: (?:[A-Z][A-Za-z&'\.\-]+|A&M|of))*)"
PLAIN = [  # player-first and school-first headline shapes that name the player plainly
    re.compile(rf"(?:^|[a-z0-9:,] ){DESC}{NAME},? (?:[^,]*?, )?(?:officially |verbally )?(?:commits|commits to|pledges to|flips to|flips from "
               rf"\S+(?: \S+)? to|decommits from|decommits|reclassifies|will reclassify|is reclassifying|reclassifying|enters the transfer portal|enters transfer portal|enters the portal|picks|chooses)\b"),
    re.compile(rf"\b{NAME}(?:'s)? (?:decommitment|de-commitment|decommits|flip|commitment)\b"),
    re.compile(rf"^(?:[^:]*: )?{SCHOOL} (?:lands|flips|adds|gets|secures|loses)(?: (?:commitment|commit|pledge) from)? {DESC}{NAME}\b"),
]
# the school that opens "Penn State flips Louisville linebacker commit Josiah Pouncy" is where he went: tried first
TO_RE = [re.compile(rf"^(?:[^:]*: )?{SCHOOL} (?:lands|flips|adds|gets|secures|picks up)\b"),
         re.compile(rf"\b(?:commits?|commitment|pledges?|flips?|flipped|transfers?|signs?|chooses|picks|heads?) (?:back )?"
                    rf"(?:to|with|from \S+(?: \S+)?(?: \S+)? to)? ?{SCHOOL}")]
FR_RE = [re.compile(rf"\b(?:decommits?|de-commits?|flips?|flipped|backs off|transfers?) from {SCHOOL}"),
         re.compile(rf"^(?:[^:]*: )?\S+(?: \S+){{0,2}} flips {SCHOOL} (?:[\w'-]+ ){{0,3}}commit\b"),
         re.compile(rf"\b(?:previously|formerly|once) committed to {SCHOOL}"),
         re.compile(rf"\bfrom {SCHOOL}"),
         re.compile(rf"^(?:[^:]*: )?{SCHOOL}(?: football| basketball| recruiting)?(?: \w+)?:? (?:loses?|sees)\b"),
         re.compile(rf"\b(?:former|ex-) {SCHOOL}\b")]
STOP_SCHOOL = {'the', 'his', 'a', 'top', 'five', 'four', 'no', 'class', 'early', 'national', 'signing', 'day', 'portal',
               'transfer', 'commit', 'commits', 'official', 'visit'}


SHORT = {'FSU': 'Florida State', 'Bama': 'Alabama', 'UGA': 'Georgia', 'OU': 'Oklahoma', 'UK': 'Kentucky', 'UF': 'Florida',
         'UT': 'Tennessee', 'Vandy': 'Vanderbilt', 'Cuse': 'Syracuse', 'ASU': 'Arizona State', 'KU': 'Kansas', 'UW': 'Washington'}


def gnews(q, timeout=25):
    u = 'https://news.google.com/rss/search?' + urllib.parse.urlencode({'q': q, 'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en'})
    for i in range(3):
        r = subprocess.run(['curl', '-sS', '-m', str(timeout), '-A', UA, u], capture_output=True, text=True)
        if r.returncode == 0 and '<rss' in r.stdout: break
        time.sleep(2 + 3 * i)
    else:
        print(f'google news: no feed for {q!r}', file=sys.stderr)
        return []
    out = []
    for it in re.findall(r'<item>(.*?)</item>', r.stdout, re.S):
        raw = html.unescape(html.unescape(re.search(r'<title>(.*?)</title>', it, re.S).group(1)))
        pub = html.unescape(re.search(r'<source[^>]*>(.*?)</source>', it, re.S).group(1)) if '<source' in it else ''
        link = re.search(r'<link>(.*?)</link>', it, re.S)
        try:
            when = dt.datetime.strptime(re.search(r'<pubDate>(.*?)</pubDate>', it).group(1)[5:25], '%d %b %Y %H:%M:%S')
        except (AttributeError, ValueError):
            continue
        title = re.sub(r'\s+-\s+[^-]+$', '', raw).strip() if pub and raw.endswith(pub) else raw.strip()
        out.append({'title': title, 'date': when.strftime('%Y-%m-%d'), 'url': link.group(1).strip() if link else None})
    return out


class Pool:
    """the players and schools a headline can name: the sport's recruit classes and portal list"""

    def __init__(self, sport):
        self.sport, self.rows, self.teams, self.logos = sport, [], {}, {}
        def j(p):
            try:
                return json.load(open(os.path.join(ROOT, p), encoding='utf-8'))
            except (OSError, ValueError):
                return {}
        def logo(t, u):
            if t and u: self.logos.setdefault(names.team_key(t), u)
        for t in (j('data/cfb_teams.json').get('teams') or []): logo(t.get('team'), t.get('logo'))
        for t in (j('data/cfb_recruits.json').get('teams') or []) + (j('data/cbb_recruits.json').get('teams') or []): logo(t.get('team'), t.get('logo'))
        for c in [{'list': j('data/cfb_recruits.json').get('class') or []}] + (j('data/cfb_recruits.json').get('future') or []) + (j('data/cbb_recruits.json').get('classes') or []):
            for r in c.get('list') or []: logo(r.get('team'), r.get('logo'))
        for r in j('data/cfb_portal.json').get('moves') or []: logo(r.get('from'), r.get('fromLogo')); logo(r.get('to'), r.get('toLogo'))
        for x in j('static/data/cbb/portal.json').get('seasons') or []:
            for r in x.get('rows') or []: logo(r.get('tm'), r.get('lo'))
        if sport == 'cfb':
            d = j('data/cfb_recruits.json')
            for r in d.get('class') or []: self.add(r.get('name'), r.get('pos'), d.get('next'), r.get('team'), r.get('rank'))
            for c in d.get('future') or []:
                for r in c.get('list') or []: self.add(r.get('name'), r.get('pos'), c.get('year'), r.get('team'), r.get('rank'))
            for t in d.get('teams') or []: self.team(t.get('team'))
            p = j('data/cfb_portal.json')
            for r in p.get('moves') or []:
                self.add(r.get('name'), r.get('pos'), None, r.get('to') or r.get('from'), None)
                self.team(r.get('from')); self.team(r.get('to'))
        else:
            d = j('data/cbb_recruits.json')
            for c in d.get('classes') or []:
                for r in c.get('list') or []: self.add(r.get('name'), r.get('pos'), c.get('year'), r.get('team'), r.get('rk'))
            for t in d.get('teams') or []: self.team(t.get('team'))
            p = j('static/data/cbb/portal.json')
            for s in p.get('seasons') or []:
                for r in s.get('rows') or []:
                    self.add(r.get('n'), r.get('pos'), None, r.get('tm'), None)
                    m = re.match(r'from (.+?) \(', r.get('sub') or '')
                    if m: self.team(m.group(1))
        for f in ('data/team_alias.json',):
            pass
        self.by = {}
        for r in self.rows: self.by.setdefault(names.key(r['n']), []).append(r)

    def add(self, n, pos, cls, team, rk):
        if not n: return
        self.rows.append({'n': n, 'pos': pos, 'cls': cls, 'team': team, 'rk': rk})
        self.team(team)

    def team(self, t):
        if t: self.teams.setdefault(names.team_key(t), t)

    def school(self, s):
        """the board's spelling of a school named in a headline, trimming trailing words until one fits"""
        if not s: return None
        w = s.split()
        w[0] = SHORT.get(w[0], w[0])
        for i in range(min(len(w), 4), 0, -1):
            k = names.team_key(' '.join(w[:i]))
            if k in self.teams: return self.teams[k]
        return None

    def player(self, title):
        """board rows whose full name appears in the headline (2-4 word windows), longest first"""
        toks = re.findall(r"[A-Za-z][A-Za-z'\.\-]*", title)
        for n in (4, 3, 2):
            for i in range(len(toks) - n + 1):
                k = names.key(' '.join(toks[i:i + n]))
                if k in self.by:
                    rows = self.by[k]
                    return rows[0] if len(rows) == 1 else max(rows, key=lambda r: r['cls'] or 0)
        return None


LEAD = re.compile(r"^(?:[A-Z]{1,4}|No\.|\d+|(?:five|four|three|\d)-star|Top-?\d*|Top247|JUCO|Elite|In-state|Former|Ex-|"
                  r"Composite|Class|Of|Five|Four|Three|Star|Prospect|Recruit|Target|Commit|After|Why|How|Report|Sources?|"
                  r"Breaking|Official|Instant|Analysis|Signee|Transfer|Portal|Alabama|Georgia|Texas|Florida|California|"
                  r"Ohio|Louisiana|Mississippi|Tennessee|Carolina|North|South|New|Virginia|Arizona|Michigan|Illinois|"
                  r"Maryland|Pennsylvania|Indiana|Kentucky|Missouri|Oklahoma|Arkansas|Kansas|Iowa|Nebraska|Colorado|"
                  r"Utah|Nevada|Oregon|Washington|Minnesota|Wisconsin|Jersey|York|Sunshine|State|Lone|Peach|Bayou)$", re.I)


def clean_name(cand, pool):
    """a player's name from a headline phrase: leading positions, star counts, ranks, states and schools trimmed"""
    w = re.sub(r"'s$", '', cand.strip()).split()
    while len(w) > 2 and (LEAD.match(w[0].rstrip(',')) or pool.school(w[0])):
        w = w[1:]
    while len(w) > 2 and LEAD.match(w[0]) and w[0].isupper():
        w = w[1:]
    if any(x.isupper() and len(x) <= 4 and x not in ('II', 'III', 'IV') and '.' not in x for x in w[1:]): return None
    if len(w) < 2 or len(w) > 3 or w[0].lower() in STOP_SCHOOL or w[0].isupper() and len(w[0]) <= 4 and '.' not in w[0]:
        return None
    if LEAD.match(w[0]) and not pool.player(' '.join(w)) and w[0].lower() in {'five', 'four', 'three', 'after', 'why', 'how'}:
        return None
    n = ' '.join(w)
    if pool.school(n) == n: return None
    return n


def kind_of(t):
    if OTHER.search(t) or NOISE.search(t): return None
    for k, rx in KIND:
        if rx.search(t):
            if k == 'commit' and not re.search(r"\bcommit(s|ted)? to\b|\bcommits\b|\bpledges?\b|\bCOMMIT\b|\bchooses\b|\bpicks\b|"
                                                r"\blands?\b|\bcommitment (to|from)\b|\bverbal", t, re.I):
                continue
            if k == 'commit' and NOUN_COMMIT.search(t) and not re.search(r"\bcommits\b(?! to)|\bcommits to\b|\bCOMMIT:", t):
                # "Maryland RB commit Terrance Grant" (the noun) is not a commitment story
                if not re.search(r"\b(lands|picks|chooses|pledges)\b", t, re.I): continue
            return k
    return None


def pos_of(t):
    low = t.lower()
    for w, p in sorted(POS_WORD.items(), key=lambda x: -len(x[0])):
        if re.search(rf"\b{w}\b", low): return p
    m = POS_RE.search(t)
    return m.group(1) if m else None


def reclass_of(t, row):
    """(new class, old class) of a reclassification headline, or None: "reclassifies to 2027", "reclassifies from 2029
    to 2028", "reclassifying from 2028" (one class up); the old class from the headline, else the board's, else one later"""
    if not re.search(r"\breclass", t, re.I) or re.search(r"\b(could|might|may|considering|weighs?|likely|possible|exploring)\b|\?", t, re.I):
        return None
    yr = lambda m: (2000 + int(m.group(1))) if m.group(1) else int(m.group(2))
    mt, mf = RECLASS_TO.search(t), RECLASS_FROM.search(t)
    new = yr(mt) if mt else None
    old = yr(mf) if mf else None
    if new is None and old is None: return None
    if new is None: new = old - 1
    if old is None:
        ys = [int(y) for y in YEAR.findall(t) if int(y) != new]
        old = ys[0] if ys else (row or {}).get('cls') if (row or {}).get('cls') not in (None, new) else new + 1
    return (new, old) if new != old else None


def parse(title, pool):
    """one headline -> its move rows (without date/source): the move, and a reclassification when it names one
    ("K'Majay Jenkins commits to Kansas, will reclassify to 2027" is two rows)"""
    t = re.sub(r'\s+', ' ', title).strip()
    if OTHER.search(t): return []
    k = kind_of(t)
    row = pool.player(t)
    rc = reclass_of(t, row)
    if not k and not rc: return []
    hp = pos_of(t)
    if row and hp and not names.pos_fits(row.get('pos'), hp, 'football' if pool.sport == 'cfb' else 'basketball'):
        row = None      # a namesake: "JUCO OL Dorian Williams" is not the board's WR Dorian Williams
    on_board = row is not None
    name = row['n'] if row else None
    if not name:
        for rx in PLAIN:
            m = rx.search(t)
            if m:
                name = clean_name(m.group(m.lastindex), pool)
                if name: break
    if not name: return []
    to = fr = None
    for rx in TO_RE:
        for m in rx.finditer(t):
            s = pool.school(m.group(1))
            if s and not names.same(s, name): to = to or s
    for rx in FR_RE:
        m = rx.search(t)
        if m and pool.school(m.group(1)): fr = fr or pool.school(m.group(1))
    if k == 'decommit':
        fr, to = fr or to, None
    if to and fr and to == fr: fr = None
    yrs = [int(y) for y in YEAR.findall(t)]
    pos = (row or {}).get('pos') or hp
    out = []
    if rc:
        out.append({'n': name, 'pos': pos, 'cls': rc[0], 'ocls': rc[1], 'k': 'reclass', 'to': to if k in ('commit', 'sign', 'flip') else None,
                    't': t, 'b': 1 if on_board else None})
    if k and not (k in ('commit', 'sign', 'flip', 'transfer') and not to) and not (k == 'rank' and not on_board):
        cls = rc[0] if rc else (row or {}).get('cls') or (yrs[0] if yrs else None)
        out.append({'n': name, 'pos': pos, 'cls': cls, 'k': k, 'to': to, 'fr': fr, 't': t, 'b': 1 if on_board else None})
    return out


CB_QUERIES = ['intitle:"crystal ball"', 'intitle:"where will"']
CB_NAME = [re.compile(r"^(.+?)'s? Crystal Ball Predictions$"), re.compile(r"^Where will (.+?) commit to\?$")]
CB_TO = [re.compile(rf"\b(?:to|toward|towards) (?:the )?{SCHOOL}"), re.compile(rf"\bfor (?:the )?{SCHOOL}")]


def parse_cb(title, pool):
    """a 247Sports Crystal Ball headline -> [alert row] when it names a board player ("X's Crystal Ball Predictions",
    "Where will X commit to?", "Crystal Ball Forecast: QB X to Y"); the school only when the headline names one"""
    t = re.sub(r'\s+', ' ', title).strip()
    if OTHER.search(t) or re.search(r'\btransfer to\?|\bportal\b', t, re.I): return []
    if not (re.search(r'crystal ball', t, re.I) or CB_NAME[1].search(t)): return []
    row = None
    for rx in CB_NAME:
        m = rx.search(t)
        if m: row = pool.player(m.group(1)); break
    else:
        row = pool.player(t)
    if not row or not row.get('cls'): return []   # recruit classes only: a portal-list namesake is too easy to mistake
    hp = pos_of(t)
    if hp and not names.pos_fits(row.get('pos'), hp, 'football' if pool.sport == 'cfb' else 'basketball'): return []
    to = None
    if not any(rx.search(t) for rx in CB_NAME):
        for rx in CB_TO:
            for m in rx.finditer(t):
                sc = pool.school(m.group(1))
                if sc and not names.same(sc, row['n']): to = sc; break
            if to: break
    return [{'n': row['n'], 'pos': row.get('pos') or hp, 'cls': row.get('cls'), 'k': 'cb', 'to': to, 't': t, 'b': 1}]


def pull_cb(pools, today, days=7):
    """Crystal Ball alerts: the sport whose board names the player (both: the headline's sport words / position)"""
    since = (today - dt.timedelta(days=days + 3)).isoformat()
    found, seen = {s: [] for s in SPORT_WORD}, set()
    for q in CB_QUERIES:
        for it in gnews(f'{q} site:247sports.com when:{days}d'):
            if it['date'] < since or it['title'] in seen: continue
            seen.add(it['title'])
            rows = {s: parse_cb(it['title'], p) for s, p in pools.items()}
            hit = [s for s, v in rows.items() if v]
            if not hit: continue
            s = hit[0] if len(hit) == 1 else sport_of(it['title'], {x: (v[0] if v else None) for x, v in rows.items()}, 'cfb')
            for r in rows[s]:
                r.update(d=it['date'], src={'247': it['url']})
                found[s].append(r)
        time.sleep(1)
    return found


def same_move(a, b):
    ks = {a['k'], b['k']}
    if not (len(ks) == 1 or ks <= {'commit', 'flip', 'sign'}) or not names.same(a['n'], b['n']): return False
    if a.get('to') and b.get('to') and not names.same_team(a['to'], b['to']): return False
    da, db = dt.date.fromisoformat(a['d']), dt.date.fromisoformat(b['d'])
    # the same move to the same school is one move however late a site re-runs the story
    return abs((da - db).days) <= (60 if a['k'] == b['k'] and a.get('to') and b.get('to') or a['k'] == 'reclass' else 4)


def move_date(votes):
    """the date of a move from its headlines' dates ({date: headlines}): the earliest, unless it is a lone headline
    two or more days before a date two or more headlines carry. Google News sometimes dates one copy days early (DJ
    Jacobs' Nov 26 2026 decommitment: one 247 headline dated Nov 24 among a dozen dated Nov 26)."""
    d0, two = min(votes), [d for d, n in votes.items() if n >= 2]
    if votes[d0] >= 2 or not two: return d0
    c = min(two)
    return c if (dt.date.fromisoformat(c) - dt.date.fromisoformat(d0)).days >= 2 else d0


def merge(rows, new, kept=False):
    """new into rows: a move already listed (either site) gains the other source; its date is move_date over the
    headlines merged. kept: rows are earlier runs' and new is this pull (with its headline dates in _v), so an earlier
    run's lone date gives way to this pull's when this pull's headlines move it (see move_date)."""
    for r in new:
        hit = next((x for x in rows if same_move(x, r)), None)
        if hit:
            if r['k'] == 'flip' or (r['k'] == 'sign' and hit['k'] == 'commit'): hit['k'] = r['k']   # a commitment story about a flip
            for s, u in r['src'].items(): hit['src'].setdefault(s, u)
            if r.get('b') and not hit.get('b'): hit['n'] = r['n']   # the board's spelling (D.J. Jacobs, not On3's David Jacobs)
            rv = r.get('_v') or {r['d']: 1}
            if kept:
                v = dict(rv); v.setdefault(hit['d'], 1)
            else:
                v = hit.setdefault('_v', {hit['d']: 1})
                for d, n in rv.items(): v[d] = v.get(d, 0) + n
            hit['d'] = move_date(v)
            for f in ('pos', 'cls', 'ocls', 'to', 'fr', 'b'):
                if not hit.get(f) and r.get(f): hit[f] = r[f]
        else:
            rows.append(r)
    return rows


FOOT_POS = {'QB', 'RB', 'WR', 'TE', 'OL', 'OT', 'OG', 'IOL', 'DL', 'DT', 'DE', 'EDGE', 'LB', 'CB', 'S', 'DB', 'ATH', 'K', 'P', 'LS', 'APB'}
HOOP_POS = {'PG', 'SG', 'SF', 'PF', 'CG', 'G', 'W', 'F'}


def sport_of(t, rows, asked):
    """which board a headline belongs to: the sport it names, else the one board it matched, else its position,
    else the query's sport"""
    if re.search(r'\bfootball\b', t, re.I): return 'cfb'
    if re.search(r'\bbasketball\b|\bhoops\b|\bNBA\b', t, re.I): return 'cbb'
    on = [s for s, r in rows.items() if r and r.get('b')]
    if len(on) == 1: return on[0]
    hp = pos_of(t)
    if hp in FOOT_POS: return 'cfb'
    if hp in HOOP_POS or re.search(r"\b\d-(foot|footer)\b|7-foot", t): return 'cbb'
    return asked


def pull(today, days=7):
    pools = {s: Pool(s) for s in SPORT_WORD}
    since = (today - dt.timedelta(days=days + 3)).isoformat()
    found, seen = {s: [] for s in SPORT_WORD}, set()
    for src, site in SITES.items():
        for asked, word in SPORT_WORD.items():
            for q in QUERIES:
                for it in gnews(f'site:{site} {word} recruiting {q} when:{days}d'):
                    if it['date'] < since or (src, it['title']) in seen: continue
                    seen.add((src, it['title']))
                    rows = {s: parse(it['title'], p) for s, p in pools.items()}
                    s = sport_of(it['title'], {x: (v[0] if v else None) for x, v in rows.items()}, asked)
                    for r in rows[s]:
                        r.update(d=it['date'], src={src: it['url']})
                        found[s].append(r)
                time.sleep(1)
    for s, f in pull_cb(pools, today, days).items(): found[s] += f
    out = {}
    for s, f in found.items():
        f.sort(key=lambda r: (r['d'], '247' not in r['src']))
        out[s] = merge([], f)
    return out


def main():
    if '--test' in sys.argv: return _test()
    today = dt.datetime.now(dt.timezone.utc).date()
    try:
        old = json.load(open(OUT, encoding='utf-8'))
    except (OSError, ValueError):
        old = {}
    cut = (today - dt.timedelta(days=KEEP_DAYS)).isoformat()
    out = {'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
    days = int(sys.argv[sys.argv.index('--days') + 1]) if '--days' in sys.argv else 7
    pulled = pull(today, days)
    for sport in ('cfb', 'cbb'):
        new = pulled[sport]
        pool = Pool(sport)       # earlier rows read again with today's patterns (a fixed false match drops out)
        kept = []
        for r in old.get(sport) or []:
            if r.get('d', '') < cut: continue
            x = next((x for x in (parse_cb if r.get('k') == 'cb' else parse)(r.get('t', ''), pool) if x['k'] == r['k']), None)
            if x is None and r['k'] == 'flip':   # a decommitment + commitment folded into a flip: its headline is the commitment's
                x = next((x for x in parse(r.get('t', ''), pool) if x['k'] == 'commit'), None)
            if x is None: continue
            if r['k'] != 'cb' and x.get('to') and not (r['k'] == 'flip' and x['k'] == 'commit'):   # today's patterns fix a misread school
                r['to'] = x['to']
                if x.get('fr'): r['fr'] = x['fr']
            kept.append(r)
        rows = merge(kept, new, kept=True)
        for r in rows: r.pop('_v', None)
        for r in rows:          # school logos (full colour, the boards' files)
            for f, lf in (('to', 'tl'), ('fr', 'fl')):
                u = pool.logos.get(names.team_key(r[f])) if r.get(f) else None
                if u: r[lf] = u
                else: r.pop(lf, None)
        # a decommitment story that names no school, within 4 days of a flip or commitment of his: the old school's
        # side of that move ("Alabama pushing for backs after Nigel Newkirk decommitment"), not a second move
        for rc in [r for r in rows if r['k'] == 'reclass']:     # his other stories from then on are in the new class
            for r in rows:
                if r is not rc and r.get('cls') == rc.get('ocls') and r['d'] >= rc['d'] and names.same(r['n'], rc['n']): r['cls'] = rc['cls']
        rows = [r for r in rows if not (r['k'] == 'decommit' and not r.get('fr') and any(
            x['k'] in ('flip', 'commit') and names.same(x['n'], r['n']) and
            abs((dt.date.fromisoformat(x['d']) - dt.date.fromisoformat(r['d'])).days) <= 4 for x in rows))]
        # a decommitment followed within a day by a commitment elsewhere is one flip (DJ Jacobs, Ohio State -> Miami,
        # Nov 26 2026): the commitment row becomes the flip and the decommitment goes
        for r in [r for r in rows if r['k'] == 'decommit' and r.get('fr')]:
            x = next((x for x in rows if x['k'] in ('flip', 'commit') and x.get('to') and names.same(x['n'], r['n'])
                      and not names.same_team(x['to'], r['fr'])
                      and 0 <= (dt.date.fromisoformat(x['d']) - dt.date.fromisoformat(r['d'])).days <= 1), None)
            if x:
                x['k'], x['fr'] = 'flip', x.get('fr') or r['fr']
                if r.get('fl') and not x.get('fl'): x['fl'] = r['fl']
                for s_, u in r['src'].items(): x['src'].setdefault(s_, u)
                rows.remove(r)
        # one spelling per player: a headline's name (On3's David Jacobs) takes the board's (D.J. Jacobs) when the shared
        # name rules, the class and the position agree
        for r in rows:
            if r.get('b') and pool.by.get(names.key(r['n'])): continue
            hit = [x for x in pool.rows if x.get('cls') and x['cls'] == r.get('cls') and names.same(x['n'], r['n'])
                   and (not r.get('pos') or not x.get('pos') or names.pos_fits(x['pos'], r['pos'], 'football' if sport == 'cfb' else 'basketball'))]
            if len({x['n'] for x in hit}) == 1: r['n'], r['b'] = hit[0]['n'], 1
        # confirmed NIL deals of recruits (data/nil_deals.json, the ledger the NIL models read), last 120 days
        from transactions import nil_deals
        have = {(r['d'], names.key(r['n']), r['k']) for r in rows}
        since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=120)).strftime('%Y-%m-%d')
        rows += [{'n': x['n'], 'pos': x['pos'], 'cls': x['cls'], 'k': 'nil', 'to': x['to'], 't': x['h'], 'd': x['d'], 'amt': x['amt'], 'b': 1, 'src': {}}
                 for x in nil_deals(sport, recruits=True) if x['d'] >= since and (x['d'], names.key(x['n']), 'nil') not in have]
        rows.sort(key=lambda r: (r['d'], r['n']), reverse=True)
        out[sport] = [{k: v for k, v in r.items() if v is not None} for r in rows]
        print(f'{sport}: {len(new)} moves pulled, {len(rows)} kept', file=sys.stderr)
    if not (out['cfb'] or out['cbb']) and (old.get('cfb') or old.get('cbb')):
        sys.exit('recruit news: nothing parsed, keeping the old file')
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
        f.write('\n')


def _test():
    class P(Pool):
        def __init__(self):
            self.sport, self.rows, self.teams = 'cfb', [], {}
            for t in ('Arkansas', 'Kentucky', 'Iowa State', 'Oklahoma', 'Maryland', 'North Carolina', 'Florida State',
                      'Alabama', 'Miami', 'Notre Dame', 'Texas A&M', 'Ohio State', 'LSU', 'Penn State', 'Tennessee',
                      'Michigan', 'Michigan State', 'Ole Miss', 'Kansas', 'SMU', 'Louisville'):
                self.team(t)
            self.add('Cayden Daughtry', 'WR', 2027, 'Arkansas', 3)
            self.add('Kaegan Morton', 'WR', 2027, 'Arkansas', 210)
            self.by = {}
            for r in self.rows: self.by.setdefault(names.key(r['n']), []).append(r)
    p = P()
    cases = [
        ('Penn State flips Louisville linebacker commit Josiah Pouncy', ('Josiah Pouncy', 'flip', 'Penn State', 'Louisville')),
        ('Five-star Cayden Daughtry commits to Arkansas', ('Cayden Daughtry', 'commit', 'Arkansas', None)),
        ('Georgia RB Trace Washington commits to Kentucky', ('Trace Washington', 'commit', 'Kentucky', None)),
        ('Commit: Iowa State lands JUCO DB Jontavius Wyman', ('Jontavius Wyman', 'commit', 'Iowa State', None)),
        ('Kamieon Compton-Nero commits to Oklahoma: Sooners land 2028 Top247 athlete', ('Kamieon Compton-Nero', 'commit', 'Oklahoma', None)),
        ('Connail Jackson commits to UNC: Tar Heels add Sunshine State RB to 2027 recruiting class', ('Connail Jackson', 'commit', 'North Carolina', None)),
        ('Arkansas flips 2027 WR Kaegan Morton', ('Kaegan Morton', 'flip', 'Arkansas', None)),
        ('Alabama pushing for several running backs after Nigel Newkirk decommitment', ('Nigel Newkirk', 'decommit', None, None)),
        ('Four-star LB John Smith decommits from Penn State', ('John Smith', 'decommit', None, 'Penn State')),
        ('Maryland RB commit Terrance Grant visits Washington, sets Alabama official visit', None),
        ('Kevin Hartsfield, 2028\'s No. 2 RB recruit, commits to play in 2027 adidas Polynesian Bowl', None),
        ('Tracking Kentucky football commits: Stats and highlights', None),
        ('COMMIT: Top 70 4-star Marley Spiers Commits to Gopher Women\'s Basketball', None),
        ('Ohio State 2027 Football Commits', None),
        ('Will Miami land five-star DJ Jacobs?', None),
        ('COMMITMENT: Michigan State lands 2028 De La Salle QB Grayson Thurston', None),
        ('Inside Notre Dame\'s rise for 2028 4-star DL Cayden Daughtry after the win', None),
        ('Ole Miss flips Top247 CB Tavares Harrington from Michigan', ('Tavares Harrington', 'flip', 'Ole Miss', 'Michigan')),
        ('Cayden Daughtry rises to No. 3 in the Top247 rankings', ('Cayden Daughtry', 'rank', None, None)),
    ]
    bad = 0
    for t, want in cases:
        rs = parse(t, p)
        got = None if not rs else (rs[-1]['n'], rs[-1]['k'], rs[-1]['to'], rs[-1]['fr'])
        if got != want:
            bad += 1
            print(f'FAIL {t!r}\n  want {want}\n  got  {got}')
    rc = [(r['k'], r.get('cls'), r.get('ocls'), r.get('to')) for t in (
        "No. 52-ranked 2028 recruit K'Majay Jenkins commits to Kansas, will reclassify to 2027",
        'SMU WR commit Sukora Cooper Jr. reclassifies from 2029 to 2028',
        'Michigan kicker commit Ryan Jung reclassifies to 2027; ready to compete for starting role',
        'Reclassification likely to play a major role in shaping the class of 2028') for r in parse(t, p)]
    want = [('reclass', 2027, 2028, 'Kansas'), ('commit', 2027, None, 'Kansas'), ('reclass', 2028, 2029, None), ('reclass', 2027, 2028, None)]
    if rc != want:
        bad += 1; print('FAIL reclass', rc)
    cb = [(r['n'], r['to']) for t in (
        "Cayden Daughtry's Crystal Ball Predictions", 'Where will Kaegan Morton commit to?',
        '247Sports Crystal Ball Forecast: WR Cayden Daughtry to Ohio State',
        'Crystal Ball prediction in for Arkansas receiver Kaegan Morton to Ole Miss',
        'Inside a Crystal Ball pick for Penn State to land Cayden Daughtry',
        'Where will Kaegan Morton transfer to?', 'Michigan 2027 Football Crystal Ball Predictions',
        '247Sports Crystal Ball Forecast: QB John Nobody to Tennessee') for r in parse_cb(t, p)]
    if cb != [('Cayden Daughtry', None), ('Kaegan Morton', None), ('Cayden Daughtry', 'Ohio State'), ('Kaegan Morton', 'Ole Miss'), ('Cayden Daughtry', 'Penn State')]:
        bad += 1; print('FAIL cb', cb)
    a = {'n': 'Cayden Daughtry', 'k': 'commit', 'to': 'Arkansas', 'd': '2026-11-17', 'src': {'247': 'x'}}
    b = {'n': 'Cayden Daughtry', 'k': 'commit', 'to': 'Arkansas', 'd': '2026-11-16', 'src': {'on3': 'y'}}
    m = merge([a], [b])
    if len(m) != 1 or set(m[0]['src']) != {'247', 'on3'} or m[0]['d'] != '2026-11-16':
        bad += 1; print('FAIL dedupe', m)
    j = [{'n': 'D.J. Jacobs', 'k': 'decommit', 'fr': 'Ohio State', 'd': d, 'src': {w: d}} for d, w in
         (('2026-11-24', '247'), ('2026-11-26', '247'), ('2026-11-26', 'on3'), ('2026-11-26', 'on3'))]
    m = merge([], j)
    if len(m) != 1 or m[0]['d'] != '2026-11-26':
        bad += 1; print('FAIL lone early date', m)
    k = merge([{'n': 'D.J. Jacobs', 'k': 'decommit', 'fr': 'Ohio State', 'd': '2026-11-24', 'src': {'247': 'x'}}],
              [{'n': 'D.J. Jacobs', 'k': 'decommit', 'fr': 'Ohio State', 'd': '2026-11-26', 'src': {'on3': 'y'}, '_v': {'2026-11-26': 3}}], kept=True)
    if k[0]['d'] != '2026-11-26':
        bad += 1; print('FAIL fresh date', k)
    print(f'{len(cases) + 5 - bad}/{len(cases) + 5} ok')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
