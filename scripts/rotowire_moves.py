#!/usr/bin/env python3
"""RotoWire roster moves (Noah, Nov 5 2026: "use rotowire for trades/waiver claims/etc and go back through the past of
this season to make sure all rosters are accurate").

Source: each sport's whole news feed, paged back in time through RotoWire's "more updates" call (the same call
scripts/rotowire_history.py pages for injuries, 25 items a call). Two things are kept:
  moves  every item whose headline is a transaction: trade, waiver claim, waived/released/cut, signing (active roster,
         practice squad, two-way, contract), call-up/recall, send-down/assignment, college exits (dismissed, leaves
         the team, transfer portal). Key "<sport>:<pid>:<day>:<headline>".
  teams  RotoWire's club for every player the feed has named this season. The feed renders each item with the
         player's club as of the fetch (a player traded Oct 29 shows his new club on his September items), so this is
         RotoWire's roster as of the newest fetch that saw him: pid -> {player, pos, abbr, team, seen, d}.
         'FA' / 'Free Agent' = not on a club.
Soccer has no league-wide feed call on RotoWire (player and team pages only); Transfermarkt squads cover it.

scripts/data/rotowire_moves/<sport>.json: {oldest, newest, moves, teams}. Read through moves(sport),
teams(sport) and club(sport, name, pos) (shared name matcher). scripts/roster_audit.py compares every board's roster
with it; the depth chart builds call fix_depth() so a moved player leaves his old club's chart between ESPN updates.

  python3 scripts/rotowire_moves.py                  # every sport: new news, then any unfinished backfill
  python3 scripts/rotowire_moves.py football --calls 900
"""
import json
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rotowire as RW  # noqa: E402

DIR = os.path.join(RW.ROOT, 'scripts', 'data', 'rotowire_moves')
SPORTS = ['football', 'basketball', 'hockey', 'cfootball', 'cbasketball']
START = {'cfootball': '2026-08-10', 'football': '2026-07-20', 'basketball': '2026-07-01', 'cbasketball': '2026-10-01',
         'hockey': '2026-07-01'}
CALLS = 1200
FA = {'FA', 'Free Agent', ''}
FRESH = 30             # days: a newest item older than this that isn't a move says nothing about today's club

KINDS = [  # (kind, headline pattern), first match wins
    ('exit', r'overseas|\babroad\b|\b(to|in) (spain|greece|china|turkey|israel|italy|france|germany|japan|australia|'
             r'serbia|lithuania|russia|switzerland|sweden|finland|the khl|khl)\b|euroleague|announces retirement|'
             r'^retire|hangs? up|hanging up|ends? (his )?career|brings end to career|calls it a career|'
             r'bound for free agency|departs\b|parts? ways|parting ways'),
    ('trade', r'\btraded?\b|\bdealt\b|\bacquired?\b|part of (a |the )?trade|in trade|via trade|sent to [A-Z][a-z]+ in|'
              r'\bshipped\b|\bswapped\b|\bflipped\b|in exchange'),
    ('claim', r'\bclaimed\b|\bclaims?\b off waivers|waiver claim|\bscooped\b'),
    ('waived', r'\bwaived\b|placed on waivers|\bon waivers\b|clears waivers|cleared waivers|\bcut\b|\breleased?\b|'
               r'\bterminated\b|contract terminated|buyout|bought out|\bunconditional\b'),
    ('practice', r'practice squad|\bps\b'),
    ('up', r'\bpromoted\b|\brecalled?\b|called up|\bcall-up\b|elevated|signs to active|signing onto|to active roster|'
           r'joins? (the )?(nba|nhl|active)|back to (nba|nhl)|recall'),
    ('down', r'sent (down|to (the )?(ahl|echl|minors|g league))|\bassigned\b|\breassigned\b|\bdemoted\b|'
             r'to (the )?(ahl|echl|g league|minors)\b|\bloaned\b|optioned'),
    ('sign', r'\bsigns?\b|\bsigned\b|\bsigning\b|\binks?\b|agrees? to|lands? (a )?(deal|contract)|re-signs?|joins\b|'
             r'two-way (deal|contract|pact)|\bpact\b|camp deal|10-day|exhibit 10|extension|\bpto\b'),
    ('exit', r'dismissed|leaves? (the )?(team|program)|left the (team|program)|no longer (with|on)|transfer portal|'
             r'enters? portal|to transfer|transferring|steps away|stepping away|retires?\b|retiring'),
]
KRE = [(k, re.compile(p, re.I)) for k, p in KINDS]
NOT = re.compile(r'injur|practice[sd]? (fully|in|on|limited)|full practice|limited practice|game-time call|'
                 r'designation|status|absent|questionable|doubtful|inactive|out for|will play|won\'t play|returns? to '
                 r'practice|week \d+|signal|call\b', re.I)


MAYBE = re.compile(r'\bbut\b|likely to remain|pushes back|consider|mulling|weighs|contemplat|could|\bmay\b|might|'
                   r'rumou?r|denies|not (yet )?retir|un-?retir|comes? out of retirement|return', re.I)


def kind(head):
    """the move a headline reports, or None"""
    h = head or ''
    if MAYBE.search(h) and KRE[0][1].search(h):
        return None           # "Retired, but likely to remain on roster", "Mulling retirement"
    for k, r in KRE:
        if r.search(h):
            if k in ('up', 'sign', 'practice') and NOT.search(h) and not re.search(r'recall|sign|promot|squad', h, re.I):
                return None
            return k
    return None


def load(sp):
    try:
        return json.load(open(os.path.join(DIR, f'{sp}.json')))
    except (OSError, ValueError):
        return {'oldest': None, 'newest': None, 'moves': {}, 'teams': {}}


def save(sp, S):
    os.makedirs(DIR, exist_ok=True)
    p = os.path.join(DIR, f'{sp}.json')
    with open(p + '.tmp', 'w') as f:
        json.dump(S, f, indent=0, separators=(',', ':'), sort_keys=True)   # a line an entry: small diffs
    os.replace(p + '.tmp', p)


def _feed(sp, last):
    u = f'https://www.rotowire.com/{sp}/ajax/get-more-updates.php?' + urllib.parse.urlencode(
        {'type': 'sport', 'itemID': 1, 'lastUpdateTime': last, 'numUpdates': 25})
    return json.loads(RW._get(u))


def _day(s):
    try:
        return datetime.strptime(s.strip(), '%B %d, %Y').date().isoformat()
    except (ValueError, AttributeError):
        return None


def _add(S, items, fetched):
    n = 0
    for it in items:
        d = _day(it['day'])
        if not d or not it.get('pid'):
            continue
        k = kind(it['head'])
        t = S['teams'].get(it['pid'])
        # the feed is newest first: the first item a run sees for a player is his newest; a later run's same-day
        # item is newer than an earlier run's
        if t is None or d > t['d'] or (d == t['d'] and fetched > t['seen']):
            S['teams'][it['pid']] = {'player': it['player'], 'pos': it['pos'], 'abbr': it['abbr'], 'team': it['team'],
                                     'seen': fetched, 'd': d, 'head': it['head'], 'kind': k}
        if not k:
            continue
        key = f"{it['pid']}:{d}:{it['head']}"
        if key in S['moves']:
            continue
        S['moves'][key] = {'pid': it['pid'], 'player': it['player'], 'pos': it['pos'], 'abbr': it['abbr'],
                           'team': it['team'], 'head': it['head'], 'body': it['body'][:400], 'd': d, 'kind': k}
        n += 1
    return n


def walk(sp, calls=CALLS):
    """Page from now back to the newest stored fetch (new news), then on from the oldest page back to the season's
    start (an unfinished backfill). Saves after every 20 calls so a cut-off run keeps its pages."""
    S = load(sp)
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S.000')
    legs = []
    if S['newest']:
        legs.append(('new', now, S['newest']))
    if (S['oldest'] or now) > START[sp]:
        legs.append(('back', S['oldest'] or now, START[sp]))
    used = added = 0
    for kd, last, stop in legs:
        done = False
        while last and last > stop and used < calls:
            try:
                d = _feed(sp, last)
            except Exception as e:  # noqa: BLE001
                print(f'rotowire moves {sp}: {e}')
                time.sleep(5)
                try:
                    d = _feed(sp, last)
                except Exception:  # noqa: BLE001
                    break
            used += 1
            items = RW.parse(sp, d.get('updatesHTML') or '')
            added += _add(S, items, now)
            last = d.get('newLastUpdateTime')
            if kd == 'back':
                S['oldest'] = START[sp] if d.get('noMoreUpdates') or not last or last <= START[sp] else last
            if d.get('noMoreUpdates') or not items:
                done = True
                break
            if used % 20 == 0:
                save(sp, S)
            time.sleep(0.25)
        if kd == 'new' and (done or not last or last <= stop):
            S['newest'] = now
    if not S['newest'] and used:
        S['newest'] = now
    if sp in ('cfootball', 'cbasketball'):
        S['exits'] = exits(sp, S)     # read by scripts/fetch_cfb.mjs and scripts/cbb_games_live.py
    save(sp, S)
    print(f'rotowire moves {sp}: {used} calls, {added} new moves, {len(S["moves"])} moves, '
          f'{len(S["teams"])} players, back to {S["oldest"]}')
    return S


# ---- readers -------------------------------------------------------------------------------------------------------

_D = {}


def _data(sp):
    if sp not in _D:
        _D[sp] = load(sp)
    return _D[sp]


def moves(sp):
    """this season's moves, oldest first (re-read with today's patterns)"""
    out = []
    for m in _data(sp)['moves'].values():
        k = kind(m['head'])
        if k:
            out.append(dict(m, kind=k))
    return sorted(out, key=lambda m: m['d'])


def teams(sp):
    return _data(sp)['teams']


def exits(sp, S=None):
    """college: players whose newest move is leaving the program (dismissed, portal, medical retirement, left the
    team) and whose newest news since isn't a return: [{pid, player, team, pos, d, head}]"""
    S = S or _data(sp)
    last = {}
    for m in sorted(S['moves'].values(), key=lambda m: m['d']):
        k = kind(m['head'])
        if k:
            last[m['pid']] = dict(m, kind=k)
    out = []
    for pid, m in last.items():
        t = S['teams'].get(pid) or {}
        if m['kind'] != 'exit' or (t.get('d', '') > m['d'] and re.search(r'return|rejoin|back with', t.get('head', ''), re.I)):
            continue
        out.append({x: m[x] for x in ('pid', 'player', 'team', 'pos', 'd', 'head')})
    return sorted(out, key=lambda m: m['d'])


def last_move(sp):
    """pid -> newest move"""
    out = {}
    for m in moves(sp):
        out[m['pid']] = m
    return out


SITE = {'nfl': 'football', 'nba': 'basketball', 'nhl': 'hockey', 'cfb': 'cfootball', 'cbb': 'cbasketball'}
# RotoWire abbreviation -> the spellings the site's sources use (ESPN, nflverse, basketball-reference)
ALIAS = {'nfl': {'LAR': {'LA', 'LAR'}, 'WAS': {'WAS', 'WSH'}, 'JAX': {'JAX', 'JAC'}, 'LV': {'LV', 'LVR', 'OAK'}},
         'nba': {'BKN': {'BKN', 'BRK'}, 'CHA': {'CHA', 'CHO'}, 'PHO': {'PHO', 'PHX'}, 'GS': {'GS', 'GSW'},
                 'NY': {'NY', 'NYK'}, 'SA': {'SA', 'SAS'}, 'NO': {'NO', 'NOP'}, 'UTA': {'UTA', 'UTAH'},
                 'WAS': {'WAS', 'WSH'}},
         'nhl': {'LA': {'LA', 'LAK'}, 'NJ': {'NJ', 'NJD'}, 'SJ': {'SJ', 'SJS'}, 'TB': {'TB', 'TBL'},
                 'UTA': {'UTA', 'UTAH'}, 'WAS': {'WAS', 'WSH'}}}


class Ref:
    """RotoWire's newest word on each player of one sport (site key nfl/nba/nhl/cfb/cbb), joined by the shared name
    matcher: name + club first, then the exact name on another club with a fitting position (two players with one
    name are left alone)."""

    def __init__(self, sport):
        import names as NM
        self.sport, self.NM = sport, NM
        self.college = sport in ('cfb', 'cbb')
        canon = {v: k for k, vs in ALIAS.get(sport, {}).items() for v in vs}
        self.canon = lambda t: canon.get(t, t)
        eq = NM.same_team if self.college else (lambda a, b: bool(a) and bool(b) and self.canon(a) == self.canon(b))
        self.eq = eq
        self.rows = [dict(v, pid=k) for k, v in teams(SITE[sport]).items()]
        from datetime import date, timedelta
        self.fresh = (date.today() - timedelta(days=FRESH)).isoformat()
        self._moves = moves(SITE[sport])
        self.last = {}
        for m in self._moves:
            self.last[m['pid']] = m
        self.M = NM.Matcher(self.rows, name='player', team='team' if self.college else 'abbr', pos='pos',
                            sport='basketball' if sport in ('nba', 'cbb') else 'football', team_eq=eq)

    def check(self, name, club, pos=None):
        """None (same club, or RotoWire can't say) or {flag, rotowire, d, head, kind, pid}:
          moved     RotoWire's newest item has him on another club
          released  ... as a free agent (waived, released, cut, retired, gone overseas)
          practice  NFL: on a practice squad (off the 53; RotoWire lists him FA)
          minors    NHL: his newest item sent him to the AHL/ECHL (still the club's, off its NHL roster)
          exit      college: his newest move is leaving the program (dismissed, portal, retirement)"""
        hit, how = self.M.find(name, team=club, pos=None if self.sport == 'nhl' else pos)
        if not hit:
            return None
        rw = hit['team'] if self.college else hit['abbr']
        mv = self.last.get(hit['pid'])
        k = hit.get('kind') or kind(hit.get('head') or '')
        out = lambda f: {'flag': f, 'rotowire': rw if rw and rw not in FA else 'FA', 'd': hit['d'],
                         'head': hit.get('head'), 'kind': k, 'pid': hit['pid'],
                         'move': {x: mv[x] for x in ('d', 'kind', 'head')} if mv else None}
        if how and how.endswith('+team'):
            if self.college and k == 'exit':
                return out('exit')
            if self.sport == 'nhl' and k == 'down':
                return out('minors')
            if not self.college and k == 'exit':
                return out('released')   # retired, gone overseas, left the club (RotoWire may keep the old club)
            return None
        if self.college:
            return None       # college players don't change schools in season: another school = another player
        # another club: the same name could be another player. Football needs the same position group (or a
        # logged move this season); NHL rows join without positions, so two players of one name never join
        moved_logged = hit['pid'] in self.last
        if self.sport == 'nfl' and not moved_logged:
            g = lambda x: self.NM._POSGRP.get(str(x or '').upper().split('/')[0])
            if not pos or not g(pos) or g(pos) != g(hit.get('pos')):
                return None
        # an old item that isn't a move (a summer-league line in July) doesn't outweigh today's chart
        if not k and hit['d'] < self.fresh:
            return None
        if k == 'exit':
            return out('released')   # retired or gone abroad; RotoWire may still show a club
        if rw in FA:
            if k in ('sign', 'claim', 'trade', 'up'):
                return None   # written before the signing took effect: the item still shows FA
            if k == 'practice' or (not k and mv and mv['kind'] == 'practice'):
                return out('practice')   # on a practice squad (RotoWire lists FA); club kept
            if self.sport == 'nfl' and not moved_logged:
                return None
            return out('released')
        return out('moved') if rw else None

def retag(sport, rows, club='tm', name='n', pos='pos', released=False, hist=None, label=''):
    """Put each row on RotoWire's club when RotoWire has him moved (trade, claim, signing since the source's
    roster); released=True also sets 'FA' for a player RotoWire has waived, released or retired (forward-looking
    boards: contract value, projections). hist names a 'A/B' clubs-so-far field that gets the new club appended.
    Writes the source's own spelling of the club. Never raises: a missing log leaves the rows as they are."""
    if not isinstance(rows, list):
        return 0              # an id -> value map (NBA xAAV): no clubs to retag
    try:
        R = Ref(sport)
        have = {r.get(club) for r in rows}
        n = 0
        for r in rows:
            if not r.get(name) or not r.get(club):
                continue
            c = R.check(r[name], r[club], r.get(pos))
            if not c:
                continue
            if c['flag'] == 'moved':
                to = next((x for x in sorted(ALIAS.get(sport, {}).get(c['rotowire'], {c['rotowire']})) if x in have),
                          c['rotowire'])
            elif c['flag'] == 'released' and released:
                to = 'FA'
            else:
                continue
            if hist and r.get(hist) is not None:
                r[hist] = '/'.join([x for x in str(r[hist]).split('/') if x and x != to] + [to])
            r[club] = to
            n += 1
        if n:
            print(f'rotowire moves: {n} {sport} {label} rows retagged to RotoWire clubs')
        return n
    except Exception as e:  # noqa: BLE001
        print(f'rotowire moves: retag {sport} {label} skipped ({e!r})')
        return 0


def drop_moved(sport, name, club, pos=None, R={}):
    """True when a depth chart should drop this player from this club: RotoWire's newest item moved, released or
    (NHL) sent him to the minors, and that item is a transaction from the last FRESH days (ESPN's chart is daily;
    this only covers the gap)."""
    try:
        if sport not in R:
            R[sport] = Ref(sport)
        c = R[sport].check(name, club, pos)
        return bool(c and c['flag'] in ('moved', 'released', 'minors') and c['kind'] and c['d'] >= R[sport].fresh)
    except Exception:  # noqa: BLE001
        return False


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    calls = int(sys.argv[sys.argv.index('--calls') + 1]) if '--calls' in sys.argv else CALLS
    if '--calls' in sys.argv:
        args = [a for a in args if a != str(calls)]
    for sp in (args or SPORTS):
        walk(sp, calls)
