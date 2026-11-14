#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Writes the Reference (Glossary/Methodology) entry for all-time coaches into research/library.json from the numbers
in data/coach_alltime.json, then rerun scripts/library_build.py.

    python3 scripts/coach_alltime_ref.py && python3 scripts/library_build.py
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TERM = 'All-time coaches'


def main():
    d = json.load(open(os.path.join(ROOT, 'data', 'coach_alltime.json')))
    f, b = d['cfb'], d['cbb']; tf, tb = f['test'], b['test']
    wf = lambda t: t['walkForward'][-1]
    co = tf.get('coord', {})
    e = dict(term=TERM,
             short='Head coaches ranked by Score, in wins: value over what the program does with other coaches, plus titles weighted the way the Halls of Fame weigh them.',
             body=[
                 'WAx: each season, wins over the program\'s expectation on a standard season (CFB 12 games, CBB 30): G x [Phi(r/s) - Phi(e/s)], s = the decade\'s points-to-wins probit scale.',
                 'Expectation e: the program\'s other coaches\' seasons within 15 years (weight exp(-gap/6), the 2 seasons after he leaves skipped), shrunk 1 season toward the conference that year.',
                 f'Ratings: CFB ridge SRS from every major-college game since 1900; CBB Sports Reference SRS from 1950, 1939-49 estimated from win% and conference.',
                 f'cWAR = WAx + {abs(f["R0"]):.2f} (CFB) / {abs(b["R0"]):.2f} (CBB) a season: replacement level = the mean season of coaches with two or fewer seasons.',
                 'NT / CT: national and conference title shares, ties split. CFB national: AP from 1936, AP + Coaches Poll halves from 1950, share of major-selector picks before 1936. CFB conference: title game, else best conference record. CBB: NCAA title; regular-season conference title.',
                 f'Title difficulty: log2(1 + sum exp(z/t)) over the field (z = season rating z-score, t = {tf["titleTemp"]:.2f} fit on who won), over its mean.',
                 f'Score = cWAR + {f["lamN"]:.0f} a national title + {f["lamC"]:.1f} a conference title (CFB); {b["lamN"]:.0f} + {b["lamC"]:.1f} (CBB). Weights: logistic fit of Hall of Fame selection on cWAR, NT, CT (done by 2019, 8+ seasons; {tf["hof"]}/{tf["hofPool"]} CFB, {tb["hof"]}/{tb["hofPool"]} CBB), title coefficient / cWAR coefficient.',
                 (f'Coord (CFB): OC/DC unit points over the program\'s unit expectation, 1990-2025, in wins (column). In Score x {f["coordW"]:.2f} = slope of later head-coach WAx rate on coordinator rate (n {co.get("n")}, t {co.get("t")}; OC r {tf["coord_oc"]["r"]:.2f}, DC r {tf["coord_dc"]["r"]:.2f}): coordinator results barely carry. CBB: no assistant history.'
                  if co else 'Coord (CFB): no usable coordinator history. CBB: no assistant history.'),
                 f'Hall of Fame AUC: Score {tf["aucScore"]:.2f} vs raw wins {tf["aucWins"]:.2f} (CFB); {tb["aucScore"]:.2f} vs {tb["aucWins"]:.2f} (CBB).',
                 f'Movers (old-job WAx rate vs new job, 3+ seasons each): CFB r {tf["movers"]["r"]:.2f} (n {tf["movers"]["n"]}, t {tf["movers"]["t"]}); CBB r {tb["movers"]["r"]:.2f} (n {tb["movers"]["n"]}, t {tb["movers"]["t"]}).',
                 f'Walk-forward from {wf(tf)["cut"]}: shrunk WAx predicts the next 10 seasons\' WAx at r {wf(tf)["wax"]["wax"]["r"]:.2f} CFB / {wf(tb)["wax"]["wax"]["r"]:.2f} CBB (win% {wf(tf)["wax"]["wpct"]["r"]:.2f} / {wf(tb)["wax"]["wpct"]["r"]:.2f}); Score per season predicts next-10 title equity at r {wf(tf)["titles"]["score"]["r"]:.2f} / {wf(tb)["titles"]["score"]["r"]:.2f} (win% {wf(tf)["titles"]["wpct"]["r"]:.2f} / {wf(tb)["titles"]["wpct"]["r"]:.2f}).',
                 f'Stability: top-100 rank correlation across expectation settings (decay 3-12, shrink 1-3, no skip) {min(tf["stability"].values()):.2f}+ CFB, {min(tb["stability"].values()):.2f}+ CBB; odd/even-season WAx split-half {tf["splitHalf"]["r"]:.2f} / {tb["splitHalf"]["r"]:.2f}.',
             ],
             where='all-time coaches tab on the CFB and CBB pages (market group)', sports=['CFB', 'CBB'])
    p = os.path.join(ROOT, 'research', 'library.json'); lib = json.load(open(p))
    sec = next(s for s in lib['sections'] if s['id'] == 'teams')
    sec['entries'] = [x for x in sec['entries'] if x['term'] != TERM] + [e]
    json.dump(lib, open(p, 'w'), ensure_ascii=False, indent=1)
    print('ref entry written')


if __name__ == '__main__':
    main()
