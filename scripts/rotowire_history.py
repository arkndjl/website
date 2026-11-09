#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""RotoWire's past injury news and current injury cards: the exact status and return window of every player out for
the season or for weeks (Noah, Nov 5 2026: "go back to previous weeks of RotoWire reports to figure out the exact
injury status of players who are out for the season or out for multiple weeks").

1. History. Each sport's whole news feed, paged back in time through the site's own "more updates" call
   (/<sport>/ajax/get-more-updates.php?type=sport, 25 items a call, ~1,000 a week in season) to the season's start,
   then forward from the newest stored item on later runs. Kept: items about an injury (RotoWire tags the injury,
   or the headline/news reads a status). scripts/data/rotowire_history/<sport>.json.gz.
2. Long-term candidates. A player whose injury news since his last healthy item reads season-ending, injured
   reserve, out indefinitely, surgery, a timeline of 2+ weeks or a month, or Out on items 10+ days apart.
3. The card. Each candidate's RotoWire player page carries his current injury panel: status, injury, estimated
   return (free). No panel = healthy now (dropped). That is his exact status; the news gives when it began and,
   when the card has no date, the return window the timeline implies (news day + the weeks quoted).

Writes scripts/data/rotowire_long.json:
  sports -> sport -> RotoWire player id -> {player, team, abbr, pos, status, injury, since, last, ret, window,
  season, note, card}
    status  the card's ('Out', 'IR', 'Day-To-Day', ...), season true when the card or the news says season-ending
    since   first injury item of this spell (yyyy-mm-dd); last = newest injury item (epoch s)
    ret     the card's estimated return (yyyy-mm-dd) or None; window = [lo, hi] dates from the quoted timeline
The sport builds read it through rotowire.long_term(sport).

  python3 scripts/rotowire_history.py                 # every sport: history, then cards
  python3 scripts/rotowire_history.py cfootball --cards 400
"""
import gzip
import json
import os
import re
import sys
import time
import urllib.parse
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rotowire as RW  # noqa: E402

HDIR = os.path.join(RW.ROOT, 'scripts', 'data', 'rotowire_history')
LONG = os.path.join(RW.ROOT, 'scripts', 'data', 'rotowire_long.json')
START = {'cfootball': '2026-08-10', 'football': '2026-07-20', 'basketball': '2026-09-20', 'cbasketball': '2026-10-01',
         'hockey': '2026-09-10'}
# soccer: RotoWire's soccer feed has no league-wide archive call (player and team only); Transfermarkt's dated spells
# with expected returns (scripts/soccer_tm_injuries.py) already give soccer's long-term absences
CALLS = 900               # feed calls per sport per run (a full backfill is ~600 for football)
CARDS = 250               # player pages per sport per run
CARD_AGE = 20 * 3600      # a card younger than this is reused
LONG_RE = re.compile(r"season-ending|for the (rest of the |remainder of the )?season|rest of the (season|year)|out for (the )?season|"
                     r"injured reserve|\bon ir\b|\bto ir\b|\bltir\b|long-term injured|\bpup\b|physically unable|non-football injury|"
                     r"indefinitely|surgery|surgical|torn|fracture|broken|\bweeks\b|week-to-week|\bmonths?\b|multiple games|several games|"
                     r"no timetable|without a timetable|extended absence|sidelined for|out until|miss (the )?(next|remainder)")
WEEKS_RE = re.compile(r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|twelve)(?:\s*(?:-|to|or)\s*(\d+|two|three|four|five|six|seven|eight|nine|ten|twelve))?[\s-]*(week|month)s?")
NUM = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10, 'twelve': 12}
HEALTHY = {'Active', 'Probable'}
# a return after the regular season's last games is a season-ending absence
SEASON_END = {'cfootball': '2026-12-06', 'football': '2027-01-10', 'basketball': '2027-04-12', 'cbasketball': '2027-03-15',
              'hockey': '2027-04-16'}
SHORT = re.compile(r'^(questionable|probable|gtd|game[- ]time|day-to-day|dtd)', re.I)


def _day(s):
    try:
        return datetime.strptime(s.strip(), '%B %d, %Y').date()
    except (ValueError, AttributeError):
        return None


def _hpath(sp):
    return os.path.join(HDIR, f'{sp}.json.gz')


def load(sp):
    try:
        return json.load(gzip.open(_hpath(sp)))
    except (OSError, ValueError):
        return {'items': {}, 'oldest': None, 'newest': None}


def save(sp, h):
    os.makedirs(HDIR, exist_ok=True)
    with gzip.open(_hpath(sp), 'wt') as f:
        json.dump(h, f, separators=(',', ':'), sort_keys=True)


def _feed(sp, last):
    u = f'https://www.rotowire.com/{sp}/ajax/get-more-updates.php?' + urllib.parse.urlencode(
        {'type': 'sport', 'itemID': 1, 'lastUpdateTime': last, 'numUpdates': 25})
    return json.loads(RW._get(u))


def _keep(it):
    return bool(it['inj']) or RW.item_status(it) is not None or bool(LONG_RE.search((it['head'] + ' ' + it['body']).lower()))


def _add(h, sp, items):
    n = 0
    for it in items:
        d = _day(it['day'])
        if not d or not _keep(it):
            continue
        k = RW._stable_key(it)
        if k in h['items']:
            continue
        h['items'][k] = {x: it[x] for x in ('pid', 'player', 'team', 'abbr', 'pos', 'inj', 'head')}
        h['items'][k]['body'] = it['body'][:300]
        h['items'][k]['d'] = d.isoformat()
        n += 1
    return n


def walk(sp, calls=CALLS):
    """Page the feed: from now back to the newest stored item (new news), then on from the oldest stored item back
    to the season's start (an unfinished backfill)."""
    h, used, added = load(sp), 0, 0
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S.000')
    legs = []
    if h['newest']:
        legs.append(('new', now, h['newest']))
    if (h['oldest'] or now) > START[sp]:
        legs.append(('back', h['oldest'] or now, START[sp]))
    for kind, last, stop in legs:
        while last and last > stop and used < calls:
            try:
                d = _feed(sp, last)
            except Exception as e:  # noqa: BLE001
                print(f'rotowire history {sp}: {e}'); break
            used += 1
            items = RW.parse(sp, d.get('updatesHTML') or '')
            added += _add(h, sp, items)
            last = d.get('newLastUpdateTime')
            if kind == 'back':
                h['oldest'] = START[sp] if d.get('noMoreUpdates') or not last or last <= START[sp] else last
            if d.get('noMoreUpdates') or not items:
                break
            time.sleep(0.3)
        if kind == 'new' and (not last or last <= stop or used < calls):
            h['newest'] = now
    if not h['newest'] and used:
        h['newest'] = now
    save(sp, h)
    print(f'rotowire history {sp}: {used} calls, {added} new items, {len(h["items"])} kept, back to {h["oldest"]}')
    return h


def _weeks(text):
    """the first timeline quoted ("4-6 weeks", "two weeks", "a month"): (low, high) in weeks, or None"""
    m = WEEKS_RE.search(text)
    if not m:
        return None
    n = lambda x: NUM.get(x) or (int(x) if x and x.isdigit() else None)
    a = n(m.group(1)); b = n(m.group(2)) if m.group(2) else a
    if a is None or b is None or b > 52:
        return None
    k = 4.3 if m.group(3) == 'month' else 1
    return a * k, b * k


def candidates(sp, h):
    """RotoWire id -> his injury items since his last healthy one, for players whose spell reads long-term."""
    by = {}
    for it in h['items'].values():
        by.setdefault(it['pid'], []).append(it)
    out = {}
    for pid, L in by.items():
        L.sort(key=lambda x: x['d'])
        sts = [RW.item_status(x) for x in L]
        cut = max((i for i, s in enumerate(sts) if s in HEALTHY), default=-1)
        spell = L[cut + 1:]
        if not spell:
            continue
        text = ' '.join((x['head'] + ' ' + x['body']).lower() for x in spell)
        outs = [x['d'] for x, s in zip(spell, sts[cut + 1:]) if s and s.startswith('Out')]
        span = (date.fromisoformat(outs[-1]) - date.fromisoformat(outs[0])).days if outs else 0
        w = _weeks(text)
        if LONG_RE.search(text) and (w is None or w[1] >= 2 or not re.search(r'\bweeks\b|\bmonths?\b', text)
                                     or re.search(r'season|reserve|\bir\b|indefinite|surgery|torn', text)) or span >= 10:
            out[pid] = spell
    return out


def card(sp, pid):
    """The player page's injury panel: (status, injury, est. return text) or None (no panel: healthy)."""
    h = RW._get(f'https://www.rotowire.com/{sp}/player.php?id={pid}', timeout=40)
    i = max(h.find('class="p-card__injury"'), h.find('pp2-panel pp2-injury'))
    if i < 0:
        return None
    i = h.find('>', i) + 1
    t = [x for x in (RW._text(s) for s in re.split(r'<[^>]+>', h[i:i + 2500])) if x]
    st = t[0] if t and t[0].lower() != 'injury' else (t[1] if len(t) > 1 else '')
    if st.lower() == 'injury':
        st = t[1] if len(t) > 1 else ''
    if t and t[0].lower() == 'injury':          # the NBA layout: Injury, status, injury, Est. return, date
        inj = t[2] if len(t) > 2 and t[2].lower() != 'est. return' else ''
    else:                                         # the others: status, Injury, injury, Est. Return, date
        inj = t[t.index('Injury') + 1] if 'Injury' in t[:6] and t.index('Injury') + 1 < len(t) else ''
    ret = next((t[k + 1] for k, x in enumerate(t[:12]) if x.lower() == 'est. return' and k + 1 < len(t)), None)
    return st, inj, ret


def _ret_date(s, today):
    if not s:
        return None
    for f in ('%m/%d/%Y', '%b %d %Y'):
        try:
            d = datetime.strptime(s if '/' in s else f'{s} {today.year}', f).date()
            return d.replace(year=d.year + 1) if '/' not in s and d < today - timedelta(days=60) else d
        except ValueError:
            continue
    return None


def long_term(sp, h, cards=CARDS):
    try:
        old = json.load(open(LONG))
    except (OSError, ValueError):
        old = {'sports': {}}
    prev = old['sports'].get(sp, {})
    today = date.today()
    out, used = {}, 0
    cand = candidates(sp, h)
    # newest spells first: the budget goes to the players whose status is most likely to have moved
    for pid, spell in sorted(cand.items(), key=lambda kv: kv[1][-1]['d'], reverse=True):
        p = prev.get(pid)
        if p and time.time() - p.get('card', 0) < CARD_AGE and p.get('last_d') == spell[-1]['d']:
            out[pid] = p; continue
        if used >= cards:
            if p:
                out[pid] = p
            continue
        try:
            c = card(sp, pid)
        except Exception as e:  # noqa: BLE001
            print(f'rotowire card {sp} {pid}: {e}')
            if p:
                out[pid] = p
            continue
        used += 1
        time.sleep(0.4)
        if not c:
            continue                                     # no injury panel: healthy now
        st, inj, rtxt = c
        text = ' '.join((x['head'] + ' ' + x['body']).lower() for x in spell)
        ret = _ret_date(rtxt, today)
        # season-ending: the card says so (OFS, Out For Season, or a return past the season), else the news does and
        # the card gives no return date
        if SHORT.search(st):
            continue                                     # a game-to-game status: not a long absence
        season = bool(re.search(r'season|\bofs\b', st.lower() + ' ' + (rtxt or '').lower())) or bool(ret and ret.isoformat() > SEASON_END[sp]) or not ret and \
            RW.status_of(text) == 'Out (season)' and not re.search(r'\breturn(ed|s)? to practice\b|\bactivated\b', spell[-1]['head'].lower())
        w = _weeks(' '.join((x['head'] + ' ' + x['body']).lower() for x in spell[::-1]))
        wd = next((x['d'] for x in spell[::-1] if _weeks((x['head'] + ' ' + x['body']).lower())), None)
        win = [(date.fromisoformat(wd) + timedelta(weeks=w[0])).isoformat(), (date.fromisoformat(wd) + timedelta(weeks=w[1])).isoformat()] if w and wd else None
        last = spell[-1]
        # long-term: season-ending, a reserve list, a return 10+ days out, or a quoted timeline of 2+ weeks still running
        far = ret and (ret - today).days >= 10
        lst = re.search(r'\bir\b|reserve|ltir|pup|season|nfi|suspen', st.lower())
        running = win and win[1] >= (today + timedelta(days=7)).isoformat()
        if not (season or far or lst or running):
            continue
        out[pid] = {'player': last['player'], 'team': last['team'], 'abbr': last['abbr'], 'pos': last['pos'], 'status': st,
                    'injury': inj or last['inj'], 'since': spell[0]['d'], 'last_d': last['d'], 'ret': ret.isoformat() if ret else None,
                    'ret_text': rtxt, 'window': win, 'season': season, 'note': f"{last['head']}: {last['body'][:200]}",
                    'card': round(time.time())}
    old['sports'][sp] = out
    old['asof'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%MZ')
    with open(LONG, 'w') as f:
        json.dump(old, f, separators=(',', ':'), sort_keys=True)
        f.write('\n')
    print(f'rotowire long-term {sp}: {len(cand)} candidates, {used} cards read, {len(out)} still injured '
          f'({sum(v["season"] for v in out.values())} season, {sum(bool(v["ret"]) for v in out.values())} with a return date)')
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    cards = int(sys.argv[sys.argv.index('--cards') + 1]) if '--cards' in sys.argv else CARDS
    calls = int(sys.argv[sys.argv.index('--calls') + 1]) if '--calls' in sys.argv else CALLS
    for sp in [a for a in args if a in START] or list(START):
        h = walk(sp, calls)
        if '--no-cards' not in sys.argv:
            long_term(sp, h, cards)


if __name__ == '__main__':
    main()
