#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""K1 (prereg.md): CHL short-handed points a game in the draft season on the hockey draft model, the analogue of
CFB's special-teams FV terms (return yards, punter net). Same harness, gates and folds as scripts/hockey_fv_drivers.py.

    python3 scripts/hockey_fv_drivers.py --pull
    HOCKEY_DRV_OUT=/tmp/x.json python3 scripts/research/fv_port_nov16/hockey_port.py --cands=chlSH"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); SCR = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, SCR)
import hockey_fv_drivers as HD

_chl, _cand = HD.chl_feats, HD.cand_feats


def chl_feats(T, lg, yr, name, birth):
    out = _chl(T, lg, yr, name, birth)
    if out:
        hit = HD.chl_line(T, lg, yr, name, birth)
        out['shpg'] = hit[0]['shp'] / hit[0]['gp']
    return out


def cand_feats(r):
    f = _cand(r)
    c0 = r['x'].get('chl0')
    f['chlSH'] = 0.0 if not c0 or r['G'] else (c0.get('shpg', 0.0) - .03) * 10
    return f


HD.chl_feats, HD.cand_feats = chl_feats, cand_feats
HD.CANDS = HD.CANDS + ['chlSH']
if __name__ == '__main__':
    HD.main()
