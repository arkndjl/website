#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""The roster chain for team builder years 2 and 3 (scripts/research/team_years_nov28/prereg.md): shared by the history
test (scripts/research/team_years_nov28/test.py, which writes data/team_years_fit.json) and the live builder
(scripts/team_builder_next.py), so the fit applies to the same quantity it was fit on.

A roster row: {'t': team, 'c': class 1-4 (Fr..Sr), 'v': value above replacement now, 'm': role weight}.
stay[c] = P(on the same team next season | class c), dev[c] = mean value change of stayers at class c."""
from collections import defaultdict

CLS = {'Fr': 1, 'So': 2, 'Jr': 3, 'Sr': 4}


def rates(pairs):
    """pairs: [(class, stayed 0/1, value change or None)] -> stay[c], dev[c] (classes 1-4; a thin class reads the pool)"""
    n = defaultdict(int); s = defaultdict(int); d = defaultdict(list)
    for c, st, dv in pairs:
        n[c] += 1; s[c] += st
        if st and dv is not None: d[c].append(dv)
    tot = sum(s.values()) / max(1, sum(n.values()))
    stay = {c: (s[c] + 5 * tot) / (n[c] + 5) for c in range(1, 5)}
    alld = [x for v in d.values() for x in v]; md = sum(alld) / len(alld) if alld else 0.0
    dev = {c: (sum(d[c]) + 5 * md) / (len(d[c]) + 5) for c in range(1, 5)}
    return stay, dev


def curve_of(fit):
    """the development curve (data/team_years_dev.json form) -> f(class, age, value, minutes share) = change in value a
    season; age None reads as his class's mean age"""
    if not fit: return None
    b, am = fit['b'], {int(c): v for c, v in fit['ageMean'].items()}
    def f(c, age, v, m):
        a = (age - am.get(c, age)) if age else 0.0
        return b[0] + b[1] * (c == 1) + b[2] * (c == 2) + b[3] * (c == 3) + b[4] * a + b[5] * v + b[6] * m
    return f


def chain(rows, stay, dev, k, floor=0.0, curve=None, rep=0.0):
    """team -> talent in season y + k: sum of P(there) x max(floor, value then) x role.
    A roster row (class c in season y) is there in y + 1 with p0 (live: the builder's P(back), from Ret%, Transfer% and
    the draft) or stay[c], then stay[class] each season after; value + dev[class] each season. A recruit row
    ('new': 1) arrives in y + 1 as a freshman with p0 (1 for a commit, P(signs here) for a target).
    curve: the player development curve in place of the class means (value = v + rep on the curve's scale; a row may
    carry 'age')."""
    T = defaultdict(float)
    for r in rows:
        c, v, age = r['c'], r['v'], r.get('age')
        def step():
            nonlocal c, v, age
            v += curve(c, age, v + rep, r.get('m', 0.0)) if curve else dev[c]
            c = min(4, c + 1); age = age + 1 if age else None
        if r.get('new'):
            p = r.get('p0', 1.0)
            for _ in range(k - 1): p *= stay[c]; step()
        else:
            p = r['p0'] if r.get('p0') is not None else stay[c]
            step()
            for _ in range(k - 1): p *= stay[c]; step()
        T[r['t']] += p * max(floor, v) * r.get('m', 1.0)
    return dict(T)


# ------------------------------------------------------------------------------------- CFB: composite and class
CFB_CLS = {'Fr': 1, 'RS-Fr': 2, 'So': 2, 'RS-So': 3, 'Jr': 3, 'RS-Jr': 4, 'Sr': 4, 'RS-Sr': 4, 'Gr': 4, 'RS-Gr': 4}   # seasons in college, as the history counts them


def cfb_index(pack):
    """name key -> [(class year, 247 composite, school)] from the CFBD recruit pack"""
    import names
    by = defaultdict(list)
    for cy, L in pack.items():
        for r in L: by[names.key(r[0])].append((int(cy), r[1], r[4]))
    return by


def cfb_recruit(by, name, team, y):
    """(class year, composite) of his recruit row: same name, class y-5 .. y, his school first when two share it"""
    import names
    c = [x for x in by.get(names.key(name), []) if y - 5 <= x[0] <= y]
    if len(c) > 1: c = [x for x in c if names.team_key(x[2]) == names.team_key(team)]
    return (c[0][0], c[0][1] or 0.80) if len(c) == 1 else (None, 0.80)


def cfb_value(comp): return max(0.0, (comp or 0.80) - 0.80) * 10


def predict(fit_h, z_now, z_tal):
    """the fitted z of a season k out (fit_h: data/team_years_fit.json h[k]); the base (strength alone) when the
    roster chain failed its test"""
    if fit_h.get('pass'):
        b = fit_h['b']; return b[0] + b[1] * z_now + b[2] * z_tal
    b = fit_h['b0']; return b[0] + b[1] * z_now
