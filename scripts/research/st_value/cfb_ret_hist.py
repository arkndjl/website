# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Return production by player-season, FBS 2011-25, for the CFB FV test (Nov 2 2026).
    python3 scripts/research/st_value/cfb_ret_hist.py   -> scripts/.cache/fvrefit/ret_yoe.json, scripts/data/cfb_ret_hist.json.gz (2019-25)
Uses scripts/st_returners.py's parse (catch spot, yards over expected, drive points) on the cached ESPN play-by-play
(pull_cfb_hist.py). Rows: season, ESPN athlete id, name, ESPN team id + location, KR/PR count, yards, RYOE, POE.
"""
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import st_returners as S  # noqa: E402
import cfb_espn_hist as EH  # noqa: E402

OUT = os.path.join(EH.ROOT, 'scripts', '.cache', 'fvrefit', 'ret_yoe.json')

if __name__ == '__main__':
    rets, D, miss = S.cfb_returns(range(2011, 2026), pull=False)
    S.expected(rets)
    names = {}
    for f in os.listdir(os.path.join(EH.DIR, '..', 'espn_ret')):
        for tid, P in json.load(open(os.path.join(EH.DIR, '..', 'espn_ret', f))).items():
            for aid, nm in P.items():
                names[aid] = nm
    A = defaultdict(lambda: {'kr': 0, 'kry': 0.0, 'kryoe': 0.0, 'krpoe': 0.0, 'pr': 0, 'pry': 0.0, 'pryoe': 0.0, 'prpoe': 0.0})
    for r in rets:
        a = A[(r['s'], r['p'], r['t'])]; k = r['k']
        a[k] += 1; a[k + 'y'] += r['y']; a[k + 'yoe'] += r['ryoe']; a[k + 'poe'] += r['poe']
    out = [{'s': s, 'aid': p, 'tid': t, 'name': names.get(p, ''), **{k: round(v, 3) for k, v in a.items()}} for (s, p, t), a in A.items()]
    json.dump({'rows': out, 'unmatched': miss, 'n': len(rets)}, open(OUT, 'w'))
    # the frozen history the live board reads (scripts/st_returners.py cfb adds the seasons it pulls itself):
    # {season: {ESPN id: [KR, KR yards over expected, PR, PR yards over expected]}}
    import gzip
    H = defaultdict(dict)
    for o in out:
        if o['s'] >= 2019:
            x = H[str(o['s'])].setdefault(o['aid'], [0, 0.0, 0, 0.0])
            x[0] += o['kr']; x[1] = round(x[1] + o['kryoe'], 1); x[2] += o['pr']; x[3] = round(x[3] + o['pryoe'], 1)
    with gzip.open(os.path.join(EH.ROOT, 'scripts', 'data', 'cfb_ret_hist.json.gz'), 'wt') as f:
        json.dump(H, f, separators=(',', ':'))
    print(len(rets), 'returns,', len(out), 'player-team seasons, unmatched names', miss)
