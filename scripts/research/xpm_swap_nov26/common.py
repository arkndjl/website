#!/usr/bin/env python3
"""Shared inputs for the BPM -> XPM swap tests (Nov 26 2026). Point in time throughout: scripts/cbb_xpm_hist.py (this folder's
first table, moved to production so the shipped fits train on the same numbers).

    get(pid, year, k): bpm, obpm, dbpm | xpm, oxpm, dxpm (rXPM of the season) | px, pxo, pxd (pXPM core form after the season)
                       | px2, px2o, px2d (pXPM board form) | e (minutes)
pXPM coefficients for a season-y line are refit on pairs (n, n + 1) with n + 1 <= y (expanding walk-forward; a line of
2008-2010 has under three pairs behind it and takes the pairs through 2010-11 less its own)."""
import os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import cbb_xpm_hist as XH
load, get = XH.load, XH.get


def tstat(d):
    d = np.asarray(d, float)
    return float(d.mean() / (d.std(ddof=1) / np.sqrt(len(d)))) if len(d) > 1 and d.std(ddof=1) > 0 else 0.0
