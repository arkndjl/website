# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Ceiling column on the next up tab (NHL, soccer): evaluates a data/<sport>_ceiling_fit.json fit, stdlib only.

A fit's mean columns are base inputs, 'dU', 'dU2' and 'dU*<input>'; its spread columns are inputs or 'absdU'.
Ceiling = mean + q x spread (the 80th percentile of next season's value at that workload change)."""


def value(cf, v, du):
    f = cf['fit']
    v = dict(v, dU=du, dU2=du * du, absdU=abs(du))
    for c in f['cols'] + f['scol']:
        if c.startswith('dU*'):
            v[c] = du * v[c[3:]]
    m = f['b0'] + sum(b * v[c] for b, c in zip(f['b'], f['cols']))
    sp = max(f['floor'], f['c0'] + sum(c * v[k] for c, k in zip(f['c'], f['scol']))) if f['c'] else f['c0']
    return m + f['q'] * sp
