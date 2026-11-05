#!/usr/bin/env python3
"""RotoWire's free injury news (Noah, Nov 5 2026: "they seem to post faster than our current system"), every sport the
site prices: college and NFL football, NBA, college basketball, NHL, soccer.

Source: each sport's public injury news page (rotowire.com/<sport>/news.php?view=injuries: the newest 25 items, no
login; robots.txt allows it). Each item gives the player (RotoWire id, name, team, position), the injury, a headline
("Won't play Thursday") and the news sentence. The page shows only the day; the exact time comes from the item's own
headline page (datePublished), fetched once per item. College basketball items have no headline page: their time is
the source post's (an x.com status id carries its own time), else when this log first saw them.

Twenty-five items cover well under a day in season, so the poll runs every half hour (odds-snap.yml) and keeps a
rolling 21-day log, scripts/data/rotowire_news.json:
  items  "<sport>:<news id>" -> {sport, pid, player, team, pos, inj, head, body, ts, ts_src, seen}
         ts = RotoWire's publish time (epoch s), ts_src 'page' | 'tweet' | 'seen'; seen = first poll that had it.
The sport builds read it through items(sport) and refresh it first (python: refresh(sport); the CFB build runs this
script). Each build parses the status from the headline (the news sentence when the headline has none) with its own
status reader, so the same rates price a RotoWire Out as any other source's Out.

  python3 scripts/rotowire.py                 # poll every sport
  python3 scripts/rotowire.py cfootball football
  python3 scripts/rotowire.py --lead          # lead time vs Rotoballer and ESPN (data/rotowire_lead.json)
"""
import html
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, 'scripts', 'data', 'rotowire_news.json')
SPORTS = ['cfootball', 'football', 'basketball', 'cbasketball', 'hockey', 'soccer']
UA = 'arkndjl.net arkboard'
KEEP = 21 * 86400
PAGE_BUDGET = 60          # headline pages fetched per poll (the rest keep their first-seen time until the next poll)


def _get(url, timeout=30):
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=timeout) as r:
        return r.read().decode('utf-8', 'replace')


def _text(s):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', s or ''))).strip()


def parse(sport, h):
    """The news page's items, newest first."""
    out = []
    for b in re.split(r'<div class="news-update(?= |")[^"]*">', h)[1:]:
        p = re.search(r'class="news-update__player-link" href="/[a-z]+/player/[^"]*?-(\d+)">([^<]+)</a>', b)
        if not p:
            continue
        hd = re.search(r'class="news-update__headline"(?: href="([^"]+)")?>([^<]*)<', b)
        nid = re.search(r'-(\d+)$', hd.group(1) or '') if hd and hd.group(1) else None
        meta = re.search(r'class="news-update__pos">([^<]*)</b>([^<]*)</div>', b)
        inj = re.search(r'class="news-update__inj">([^<]*)<', b)
        day = re.search(r'class="news-update__timestamp">([^<]+)<', b)
        news = re.search(r'class="news-update__news">(.*?)</div>', b, re.S)
        logo = re.search(r'class="news-update__logo"[^>]*alt="([^"]*)"', b)
        head = _text(hd.group(2)) if hd else ''
        body = _text(news.group(1)) if news else ''
        tweet = re.search(r'(?:x|twitter)\.com/\w+/status/(\d{15,20})', news.group(1) if news else '')
        out.append({'id': nid.group(1) if nid else None, 'sport': sport, 'pid': p.group(1), 'player': _text(p.group(2)),
                    'team': _text(meta.group(2)) if meta else (logo.group(1) if logo else ''),
                    'abbr': logo.group(1) if logo else '', 'pos': _text(meta.group(1)) if meta else '',
                    'inj': _text(inj.group(1)) if inj else '', 'head': head, 'body': body[:600],
                    'day': _text(day.group(1)) if day else '', 'url': hd.group(1) if hd and hd.group(1) else None,
                    'tweet': tweet.group(1) if tweet else None})
    return out


def _published(url):
    h = _get('https://www.rotowire.com' + url)
    m = re.search(r'"datePublished":"([^"]+)"', h)
    return datetime.fromisoformat(m.group(1)).timestamp() if m else None


def _stable_key(it):
    # a page without a headline link: key on the player and the text, not Python's per-run hash
    if it['url']:
        return it['id']
    import hashlib
    return it['pid'] + '-' + hashlib.md5((it['head'] + '|' + it['body'][:80]).encode()).hexdigest()[:10]


def load():
    try:
        return json.load(open(LOG))
    except (OSError, ValueError):
        return {'items': {}}


def save(log):
    now = time.time()
    log['items'] = {k: v for k, v in log['items'].items() if now - (v.get('ts') or v['seen']) < KEEP}
    log['asof'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%MZ')
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, 'w') as f:
        json.dump(log, f, separators=(',', ':'), sort_keys=True)
        f.write('\n')


def poll(sports=SPORTS, log=None):
    """Read each sport's page into the log; returns the log and the new item count per sport."""
    log = log or load()
    now, budget, fresh = time.time(), PAGE_BUDGET, {}
    for sp in sports:
        try:
            items = parse(sp, _get(f'https://www.rotowire.com/{sp}/news.php?view=injuries'))
        except Exception as e:
            print(f'rotowire {sp}: page unavailable: {e}')
            continue
        if not items:
            print(f'rotowire {sp}: no items (layout changed?)')
        n = 0
        for it in items:
            k = f'{sp}:{_stable_key(it)}'
            cur = log['items'].get(k)
            if cur and cur.get('ts_src') != 'seen':
                continue
            e = cur or {x: it[x] for x in ('sport', 'pid', 'player', 'team', 'abbr', 'pos', 'inj', 'head', 'body')}
            e.setdefault('seen', now)
            ts, src = None, 'seen'
            if it['url'] and budget > 0:
                budget -= 1
                try:
                    ts, src = _published(it['url']), 'page'
                except Exception as ex:
                    print(f'rotowire {sp}: headline page {it["url"]}: {ex}')
                time.sleep(0.4)
            if ts is None and it['tweet']:   # x.com status ids carry their post time (ms since 2010-11-04, << 22)
                ts, src = ((int(it['tweet']) >> 22) + 1288834974657) / 1000, 'tweet'
            if ts is None:
                ts, src = e['seen'], 'seen'
            e['ts'], e['ts_src'] = round(ts), src
            n += cur is None
            log['items'][k] = e
        fresh[sp] = n
        time.sleep(0.5)
    return log, fresh


def refresh(sport):
    """Poll one sport and save, for a build that runs between polls; never raises."""
    try:
        log, fresh = poll([sport])
        save(log)
        print(f'rotowire {sport}: {fresh.get(sport, 0)} new items')
    except Exception as e:
        print(f'rotowire {sport}: refresh failed: {e}')


def status_of(text):
    """A status from a headline or a news sentence (the NFL build's reader, scripts/nfl_games.py status_of): Out (season),
    Doubtful, Out, Questionable, Probable, Active; None = not availability news. The most serious reading wins."""
    t = (text or '').lower()
    if re.search(r"season-ending|out for (the )?(rest of the |remainder of the )?(season|year)|(rest|remainder) of the (season|year)|miss the (rest|remainder)|torn acl|achilles|placed on (injured reserve|ir)\b|lands on ir|to ir\b|career-ending", t):
        return 'Out (season)'
    if re.search(r"doubtful|unlikely to play", t):
        return 'Doubtful'
    if re.search(r"\bruled out|\bwill miss|\bto miss|\bmiss(es)? time|\bwon't play|\bwill not play|\bnot expected to play|\bis out\b|\bout\b(?! of)|\bsidelined|\binactive|healthy scratch|\bwill sit|\bnot dress|\bout for a (week|month)", t):
        return 'Out'
    if re.search(r"questionable|game-time decision|day-to-day|uncertain to play|status (is )?uncertain|limited in practice|week-to-week", t):
        return 'Questionable'
    if re.search(r"probable|optimistic|hopeful|expected to play|on track to (play|return)|trending toward playing|should play|full practice|practiced fully", t):
        return 'Probable'
    if re.search(r"\bcleared|will play|good to go|returns? to (action|the lineup)|back in the lineup|set to return|will return|will start|making his return|off (the )?injury report|activated|(that|now) he's healthy|(is|fully|now) healthy\b(?! scratch)|back to full health|\bin the lineup|\bwill dress|available", t):
        return 'Active'
    return None


def item_status(it):
    """The item's status: its headline's, else its news sentence's."""
    return status_of(it['head']) or status_of(re.split(r'(?<=[.!?])\s', it['body'], maxsplit=1)[0])


def matcher(rows, **kw):
    import names as NM
    return NM.Matcher(rows, **kw)


def items(sport, since=0):
    """The logged items for a sport, oldest first: dicts with ts (epoch s)."""
    return sorted((v for v in load()['items'].values() if v['sport'] == sport and v['ts'] >= since), key=lambda v: v['ts'])


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if '--lead' in sys.argv:
        import rotowire_lead
        rotowire_lead.main()
        return
    log, fresh = poll(args or SPORTS)
    save(log)
    print('rotowire:', ', '.join(f'{k} +{v}' for k, v in fresh.items()), f'({len(log["items"])} logged)')


if __name__ == '__main__':
    main()
