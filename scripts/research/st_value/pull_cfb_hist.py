# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""CFB return history for the special teams FV test (Nov 2 2026): ESPN summaries 2011-2022, one call per FBS game.
Keeps the slim play-by-play (espn_pbp), the box with kick/punt returns (CFB_BOX_RETURNS=1) and the returner ids
(espn_ret, as scripts/st_returners.py), so neither st_returners nor cfb_roster_hist pulls the summary again.
    CFB_BOX_RETURNS=1 python3 scripts/research/st_value/pull_cfb_hist.py 2011 2022
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
os.environ.setdefault('CFB_BOX_RETURNS', '1')
import cfb_espn_pbp as P  # noqa: E402
import cfb_espn_hist as H  # noqa: E402

RET = os.path.join(H.DIR, '..', 'espn_ret')
_get = H.get


def get(url, tries=4):
    d = _get(url, tries)
    if d is not None and '/summary?event=' in url:
        gid = url.rsplit('=', 1)[1]
        out = {}
        for t in (d.get('boxscore') or {}).get('players') or []:
            for st in t.get('statistics') or []:
                if st.get('name') in ('kickReturns', 'puntReturns'):
                    for a in st.get('athletes') or []:
                        at = a.get('athlete') or {}
                        if at.get('id'):
                            out.setdefault(t['team']['id'], {})[at['id']] = at.get('displayName')
        with open(os.path.join(RET, f'{gid}.json'), 'w') as f:
            json.dump(out, f)
    return d


H.get = get

if __name__ == '__main__':
    os.makedirs(RET, exist_ok=True)
    for x in ('sum', 'odds', 'box'):
        os.makedirs(os.path.join(H.DIR, x), exist_ok=True)
    os.makedirs(P.PBP, exist_ok=True)
    import runpy
    sys.argv = ['cfb_espn_pbp.py'] + sys.argv[1:3]
    runpy.run_path(os.path.join(os.path.dirname(os.path.dirname(HERE)), 'cfb_espn_pbp.py'), run_name='__main__')
