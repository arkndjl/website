#!/usr/bin/env python3
"""Lead time of RotoWire's injury news over the site's other news sources (scripts/rotowire.py --lead).

For each logged RotoWire item with a status and an exact time (its headline page's datePublished, or the source
post's time for items without one), the same player's earliest item with the same status group (out / questionable
/ playing) in each other source within 72 hours either side:
  rotoballer  Rotoballer's player news (the CFB and NFL builds read it), headline time
  espn        ESPN's league injury feed (every build but soccer), the entry's date
lead = other's time - RotoWire's, minutes (positive: RotoWire first). An item the other source doesn't have yet is
counted apart ('only'), with how long it has been out. Writes scripts/data/rotowire_lead.json."""
import json
import os
import re
import statistics
import sys
import time
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import names as NM  # noqa: E402
import rotowire as RW  # noqa: E402

OUT = os.path.join(RW.ROOT, 'scripts', 'data', 'rotowire_lead.json')
RB = {'cfootball': 'cfb', 'football': 'nfl', 'basketball': 'nba', 'hockey': 'nhl'}
ESPN = {'cfootball': 'football/college-football', 'football': 'football/nfl', 'basketball': 'basketball/nba',
        'hockey': 'hockey/nhl'}
RB_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'
WIN = 72 * 3600


def group(st):
    s = (st or '').lower()
    if not s:
        return None
    if re.search(r'out|injured reserve|suspen|season|inactive|ir\b|physically unable', s):
        return 'out'
    if re.search(r'questionable|day-to-day|doubtful|game time|game-time', s):
        return 'q'
    if re.search(r'active|probable|available', s):
        return 'ok'
    return None


def rotoballer(sport, pages=10):
    out, seen = [], set()
    for pg in range(1, pages + 1):
        u = (f'https://www.rotoballer.com/player-news?sport={RB[sport]}' if pg == 1
             else f'https://www.rotoballer.com/player-news/page/{pg}?sport={RB[sport]}')
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': RB_UA}), timeout=30) as r:
                h = r.read().decode('utf-8', 'replace')
        except Exception:  # noqa: BLE001
            break
        fresh = 0
        for c in h.split('<div class="rb-news-card')[1:]:
            m = re.search(r'title="Permanent Link to ([^"]+)"', c); ts = re.search(r'data-ts="(\d+)"', c)
            if not m or not ts or m.group(1) + ts.group(1) in seen:
                continue
            seen.add(m.group(1) + ts.group(1)); fresh += 1
            t = re.sub(r'&#0?39;|&#8217;', "'", m.group(1)).replace('&amp;', '&')
            out.append({'text': t, 'key': ' ' + NM.key(t) + ' ', 'ts': int(ts.group(1)), 'g': group(RW.status_of(t))})
        if not fresh:
            break
        time.sleep(0.4)
    return out


def espn(sport):
    try:
        with urllib.request.urlopen(urllib.request.Request(f'https://site.api.espn.com/apis/site/v2/sports/{ESPN[sport]}/injuries',
                                                           headers={'User-Agent': 'arkndjl.net arkboard'}), timeout=30) as r:
            j = json.load(r)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for t in j.get('injuries', []):
        for i in t.get('injuries', []):
            try:
                ts = datetime.fromisoformat((i.get('date') or '').replace('Z', '+00:00')).timestamp()
            except ValueError:
                continue
            nm = (i.get('athlete') or {}).get('displayName') or ''
            out.append({'key': NM.key(nm), 'ts': ts, 'g': group(i.get('status'))})
    return out


def main():
    now = time.time()
    res = {'asof': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%MZ'), 'sports': {}}
    for sp in RB:
        rw = [it for it in RW.items(sp) if it['ts_src'] in ('page', 'tweet')]
        rw = [dict(it, g=group(RW.item_status(it))) for it in rw]
        rw = [it for it in rw if it['g']]
        srcs = {'rotoballer': rotoballer(sp), 'espn': espn(sp)}
        S = {'items': len(rw)}
        for name, other in srcs.items():
            leads, only = [], []
            for it in rw:
                k = NM.key(it['player'])
                if name == 'rotoballer':
                    hits = [o for o in other if f' {k} ' in o['key'] and o['g'] == it['g'] and abs(o['ts'] - it['ts']) < WIN]
                else:
                    hits = [o for o in other if o['key'] == k and o['g'] == it['g'] and abs(o['ts'] - it['ts']) < WIN]
                if hits:
                    leads.append((min(o['ts'] for o in hits) - it['ts']) / 60)
                elif other and it['ts'] >= min(o['ts'] for o in other):      # inside the window the source covers
                    only.append((now - it['ts']) / 60)
            S[name] = {'matched': len(leads), 'rotowire_first': sum(x > 0 for x in leads),
                       'median_lead_min': round(statistics.median(leads), 1) if leads else None,
                       'mean_lead_min': round(statistics.fmean(leads), 1) if leads else None,
                       'only_rotowire': len(only), 'only_age_median_min': round(statistics.median(only), 1) if only else None,
                       'source_items': len(other)}
        res['sports'][sp] = S
        print(sp, json.dumps(S))
    with open(OUT, 'w') as f:
        json.dump(res, f, indent=1)
        f.write('\n')


if __name__ == '__main__':
    main()
