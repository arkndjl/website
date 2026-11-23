#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""SV (prereg.md): tennis season WAR, calendar year to date. Split-half r (odd vs even matches inside a season, players
with 30+ matches, seasons 2015-25), and r of SV with next season's SV and with the 52-week WAR at year end.
    python3 scripts/research/port_nov23/tennis_cs/tennis_sv.py  -> sv_results.json beside this file"""
import os, sys, json
from collections import defaultdict
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'tennis_nov13'))
from base import M, load_rows, live_P  # noqa: E402
import numpy as np


class Log(M.Model):
    def value_update(self, r, day):
        super().value_update(r, day)
        for p in (r[7], r[8]):
            v = self.wq[p][-1][1]
            self.log[(r[0] // 10000, r[1], p)].append(v)


def main():
    rows, _, _ = load_rows()
    m = Log(live_P())
    m.log = defaultdict(list)
    M.mark_two_week(rows)
    for r in rows:
        if r[0] // 10000 < 2014:
            m.update(r); continue
        m.update(r)
    res = {}
    for tour in ('atp', 'wta'):
        a, b, s1, s2 = [], [], [], []
        for (y, t, p), v in m.log.items():
            if t != tour or not 2015 <= y <= 2025 or len(v) < 30: continue
            a.append(sum(v[0::2])); b.append(sum(v[1::2]))
            nxt = m.log.get((y + 1, t, p))
            if nxt and len(nxt) >= 30 and y + 1 <= 2025:
                s1.append(sum(v)); s2.append(sum(nxt))
        r = float(np.corrcoef(a, b)[0, 1])
        res[tour] = {'n': len(a), 'split_half_r': round(r, 3), 'spearman_brown': round(2 * r / (1 + r), 3),
                     'next_season_r': round(float(np.corrcoef(s1, s2)[0, 1]), 3), 'n_next': len(s1)}
        print(tour, res[tour])
    json.dump(res, open(os.path.join(HERE, 'sv_results.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
