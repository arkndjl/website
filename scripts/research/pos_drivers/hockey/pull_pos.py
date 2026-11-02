#!/usr/bin/env python3
"""CHL goalie season tables and team standings (HockeyTech modulekit, OHL/WHL/QMJHL, 2007-26 end years) for the
position-purpose FV driver test (Nov 2 2026) -> scripts/.cache/hockey/pos/<league>_<end year>_{gk,st}.json"""
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, SCRIPTS)
import hockey_fv_drivers as HD

OUT = os.path.join(SCRIPTS, '.cache', 'hockey', 'pos')


def main():
    os.makedirs(OUT, exist_ok=True)
    jobs = []
    for c, k in HD.HTKEY.items():
        for s in (HD._get(HD.HT % (k, c) + '&view=seasons') or {}).get('SiteKit', {}).get('Seasons') or []:
            m = re.match(r'(\d{4}) ?- ?(\d{2,4}) \|? ?Regular Season$', s['season_name'].strip())
            if m and 2006 <= int(m.group(1)) <= 2025:
                jobs.append((c, k, s['season_id'], int(m.group(1)) + 1))

    def one(j):
        c, k, sid, yr = j
        for tag, q in (('gk', f'&view=statviewtype&type=topgoalies&season_id={sid}&first=0&limit=1000&qualified=all&order_direction='),
                       ('st', f'&view=statviewtype&type=standings&stat=conference&season_id={sid}')):
            fn = os.path.join(OUT, f'{c}_{yr}_{tag}.json')
            if not os.path.exists(fn):
                d = HD._get(HD.HT % (k, c) + q)
                if d:
                    json.dump(d['SiteKit'].get('Statviewtype'), open(fn, 'w'))
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(one, jobs))
    print(len(jobs), 'league-seasons;', len(os.listdir(OUT)), 'files')


if __name__ == '__main__':
    main()
