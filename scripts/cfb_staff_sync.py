#!/usr/bin/env python3
"""Keep the head coaches in data/cfb_staff.json current (Nov 2 2026, "every model auto-updates").

    python3 scripts/cfb_staff_sync.py          # ESPN's current head coach for every team in the file
    python3 scripts/cfb_staff_sync.py --dry    # print the changes only

The staff file was built by hand on Oct 7 (ESPN rosters, Wikipedia infoboxes, athletics staff pages) and nothing
refreshed it, so a firing or an interim never reached the staff board or the coaching market. This reads ESPN's
team roster endpoint (the coach ESPN lists now, interims included) and, where the name differs, replaces the head
coach: name and source change, the old coach is kept under "prev" with the date, and the Wikipedia link is dropped
(the photo falls back to the team logo until someone adds one). Coordinators are left as they are (ESPN doesn't
list them). Names are compared through the shared matcher (scripts/names.py), so spelling variants don't count as
changes. Runs in the full cfb-board runs, before fetch_cfb.mjs; a failed pull changes nothing.
"""
import datetime as dt
import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import names  # noqa: E402

P = os.path.join(ROOT, 'data', 'cfb_staff.json')
URL = 'https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams/{}/roster'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36'


def current(tid):
    for _ in range(3):
        try:
            d = json.load(urllib.request.urlopen(urllib.request.Request(URL.format(tid), headers={'User-Agent': UA}), timeout=20))
            c = (d.get('coach') or [{}])[0]
            n = f"{c.get('firstName', '')} {c.get('lastName', '')}".strip()
            return tid, n or None
        except Exception:
            continue
    return tid, None


def main():
    dry = '--dry' in sys.argv
    S = json.load(open(P))
    teams = S['teams']
    with ThreadPoolExecutor(16) as ex:
        now = dict(ex.map(current, list(teams)))
    got = sum(1 for v in now.values() if v)
    if got < 0.8 * len(teams):
        print(f'cfb staff: only {got} of {len(teams)} ESPN pulls answered, nothing changed')
        return 0
    today = dt.date.today().isoformat()
    changes = []
    for tid, n in now.items():
        hc = teams[tid].get('hc') or {}
        if not n or (hc.get('name') and names.key(hc['name']) == names.key(n)):
            continue
        changes.append((tid, hc.get('name'), n))
        prev = {'name': hc.get('name'), 'until': today}
        teams[tid]['hc'] = {'name': n, 'src': f'espn:teams/{tid}/roster#coach', 'wiki': None,
                            'prev': [prev] + (hc.get('prev') or [])[:3]}
    for c in changes:
        print(f'cfb staff: team {c[0]} head coach {c[1]} -> {c[2]}')
    if not dry:
        S['asof'] = today
        S['hcSynced'] = today
        with open(P, 'w') as f:
            json.dump(S, f, indent=1, ensure_ascii=False)
            f.write('\n')
    print(f'cfb staff: {len(changes)} head coach change(s), {got}/{len(teams)} teams checked')
    return 0


if __name__ == '__main__':
    sys.exit(main())
