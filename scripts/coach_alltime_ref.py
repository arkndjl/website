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


def pro(d):
    """the NBA / NHL lines, when those sports are in the file"""
    P = [(k, d[k]) for k in ('nba', 'nhl') if k in d]
    if not P: return []
    wf = lambda t: t['walkForward'][-1]
    lab = ' / '.join(k.upper() for k, _ in P)
    j = lambda f: ' / '.join(f(x, x['test']) for _, x in P)
    return [
        f'{lab}: the same method on Sports Reference SRS (NBA points, NHL goals), with an 82-game season and the franchise as the program (one id through relocations). A league title counts as the national title, and a place in the Finals or Stanley Cup Final as the conference title. A coach replaced in season gets his share of the games. Seasons with an SRS on file: {j(lambda x, t: f"{x['from']}-{x['to']}")}.',
        f'{lab} replacement level is {j(lambda x, t: f"{abs(x['R0']):.2f}")} wins a season, and Score = cWAR + {j(lambda x, t: f"{x['lamN']:.0f}")} a title + {j(lambda x, t: f"{x['lamC']:.1f}")} a Finals appearance. The Hall of Fame label is the Naismith Coach category for the NBA ({P[0][1]["test"]["hof"]}/{P[0][1]["test"]["hofPool"]}) and the Hockey Hall of Fame Builder category for the NHL ({P[-1][1]["test"]["hof"]}/{P[-1][1]["test"]["hofPool"]}; that Hall has no coach class, and coaches inducted as players are left out of the fit).',
        f'{lab} tests: Hall of Fame AUC is {j(lambda x, t: f"{t['aucScore']:.2f}")} for Score, compared to {j(lambda x, t: f"{t['aucWins']:.2f}")} for raw wins. Movers r {j(lambda x, t: f"{t['movers']['r']:.2f} (n {t['movers']['n']}, t = {t['movers']['t']})")}. Walk-forward from {wf(P[0][1]["test"])["cut"]}, shrunk WAx to next-10 WAx is r {j(lambda x, t: f"{wf(t)['wax']['wax']['r']:.2f}")} (win% {j(lambda x, t: f"{wf(t)['wax']['wpct']['r']:.2f}")}), and Score per season to next-10 title equity is r {j(lambda x, t: f"{wf(t)['titles']['score']['r']:.2f}")} (win% {j(lambda x, t: f"{wf(t)['titles']['wpct']['r']:.2f}")}). Split-half {j(lambda x, t: f"{t['splitHalf']['r']:.2f}")}.',
    ]


def nfl(d):
    """the NFL lines, when that sport is in the file"""
    if 'nfl' not in d: return []
    x = d['nfl']; t = x['test']; w = t['walkForward'][-1]
    return [
        f"NFL: the same method on the all-time teams' ridge points a game (NFL, AFL and AAFC, {x['from']}-{x['to']}), with a 17-game season and the franchise as the program (one id through relocations). Head coaches and their records come from pro-football-history.com, with an in-season change split by games. A league title counts as the national title, and a title-game season (conference championship, or the league title game before the merger) as the conference title.",
        f"NFL replacement level is {abs(x['R0']):.2f} wins a season, and Score = cWAR + {x['lamN']:.0f} a title + {x['lamC']:.1f} a title-game season (Pro Football Hall of Fame coaches {t['hof']}/{t['hofPool']}; coaches inducted as players are left out of the fit). Coordinator seasons carry nothing into head-coaching WAx (slope .01, t = .07, 94 coaches), so there is no coordinator term.",
        f"NFL tests: Hall of Fame AUC is {t['aucScore']:.2f} for Score, compared to {t['aucWins']:.2f} for raw wins. Movers r {t['movers']['r']:.2f} (n {t['movers']['n']}, t = {t['movers']['t']}). Walk-forward from {w['cut']}, shrunk WAx to next-10 WAx is r {w['wax']['wax']['r']:.2f} (win% {w['wax']['wpct']['r']:.2f}), and Score per season to next-10 title equity is r {w['titles']['score']['r']:.2f} (win% {w['titles']['wpct']['r']:.2f}). Split-half {t['splitHalf']['r']:.2f}.",
    ]


def main():
    d = json.load(open(os.path.join(ROOT, 'data', 'coach_alltime.json')))
    f, b = d['cfb'], d['cbb']; tf, tb = f['test'], b['test']
    wf = lambda t: t['walkForward'][-1]
    co = tf.get('coord', {})
    e = dict(term=TERM,
             short='Head coaches ranked by Score, in wins. Score is a coach\'s value over what the program does with other coaches, plus titles weighted the way the Halls of Fame weigh them.',
             body=[
                 'WAx is each season\'s wins over the program\'s expectation on a standard season (CFB 12 games, CBB 30): G × [Phi(r/s) - Phi(e/s)], where s is the decade\'s points-to-wins probit scale.',
                 'The expectation e comes from the seasons of the program\'s other coaches within 15 years (weight exp(-gap/6), skipping the 2 seasons after he leaves), shrunk 1 season toward the conference that year.',
                 f'Ratings: CFB is a ridge SRS from every major-college game since 1900. CBB is Sports Reference SRS from 1950, with 1939-49 estimated from win% and conference.',
                 f'cWAR = WAx + {abs(f["R0"]):.2f} (CFB) / {abs(b["R0"]):.2f} (CBB) a season. Replacement level is the mean season of coaches with two or fewer seasons.',
                 'NT / CT are national and conference title shares, with ties split. CFB national: AP from 1936, AP + Coaches Poll halves from 1950, and the share of major-selector picks before 1936. CFB conference: the title game, or else the best conference record. CBB: the NCAA title, and the regular-season conference title.',
                 f'Title difficulty: log2(1 + sum exp(z/t)) over the field (z is the season rating z-score, and t = {tf["titleTemp"]:.2f} is fit on who won), over its mean.',
                 f'Score = cWAR + {f["lamN"]:.0f} a national title + {f["lamC"]:.1f} a conference title (CFB); {b["lamN"]:.0f} + {b["lamC"]:.1f} (CBB). The weights come from a logistic fit of Hall of Fame selection on cWAR, NT and CT (done by 2019, 8+ seasons; {tf["hof"]}/{tf["hofPool"]} CFB, {tb["hof"]}/{tb["hofPool"]} CBB), as the title coefficient over the cWAR coefficient.',
                 (f'Coord (CFB): OC/DC unit points over the program\'s unit expectation, 1990-2025, in wins (column). It goes into Score × {f["coordW"]:.2f}, the slope of later head-coach WAx rate on coordinator rate (n {co.get("n")}, t = {co.get("t")}; OC r {tf["coord_oc"]["r"]:.2f}, DC r {tf["coord_dc"]["r"]:.2f}), so coordinator results barely carry. CBB has no assistant history.'
                  if co else 'Coord (CFB): there is no usable coordinator history. CBB has no assistant history.'),
                 f'Hall of Fame AUC is {tf["aucScore"]:.2f} for Score, compared to {tf["aucWins"]:.2f} for raw wins (CFB), and {tb["aucScore"]:.2f} compared to {tb["aucWins"]:.2f} (CBB).',
                 f'Movers (old-job WAx rate against the new job, 3+ seasons each): CFB r {tf["movers"]["r"]:.2f} (n {tf["movers"]["n"]}, t = {tf["movers"]["t"]}), CBB r {tb["movers"]["r"]:.2f} (n {tb["movers"]["n"]}, t = {tb["movers"]["t"]}).',
                 f'Walk-forward from {wf(tf)["cut"]}, shrunk WAx predicts the next 10 seasons\' WAx at r {wf(tf)["wax"]["wax"]["r"]:.2f} CFB / {wf(tb)["wax"]["wax"]["r"]:.2f} CBB (win% {wf(tf)["wax"]["wpct"]["r"]:.2f} / {wf(tb)["wax"]["wpct"]["r"]:.2f}), and Score per season predicts next-10 title equity at r {wf(tf)["titles"]["score"]["r"]:.2f} / {wf(tb)["titles"]["score"]["r"]:.2f} (win% {wf(tf)["titles"]["wpct"]["r"]:.2f} / {wf(tb)["titles"]["wpct"]["r"]:.2f}).',
                 f'Stability: the top-100 rank correlation across expectation settings (decay 3-12, shrink 1-3, no skip) is {min(tf["stability"].values()):.2f}+ CFB and {min(tb["stability"].values()):.2f}+ CBB. Odd/even-season WAx split-half is {tf["splitHalf"]["r"]:.2f} / {tb["splitHalf"]["r"]:.2f}.',
             ] + pro(d) + nfl(d) + ([
                 'Era check: the mid-career decades of the top 100 by Score against every ranked coach\'s coached seasons by decade (a career total grows with seasons), as a KL, with the era-blind 95% line (top 100 drawn at random), and the per-season Score rate against coaches by decade: '
                 + '; '.join(f"{k.upper()} {d[k]['test']['era'][0]:.3f} (line {d[k]['test']['era'][1]:.3f}), rate {d[k]['test']['eraRate'][0]:.3f} (line {d[k]['test']['eraRate'][1]:.3f})" for k in ('cfb', 'cbb', 'nba', 'nhl', 'nfl') if k in d and 'era' in d[k]['test']) + '.']
                 if all('era' in d[k]['test'] for k in ('cfb', 'cbb') if k in d) else []),
             where='all-time coaches tab on the CFB and CBB pages (market group)' + (' and the NBA and NHL pages (teams group)' if pro(d) else '') + ('; NFL page (teams group, all-time)' if nfl(d) else ''),
             sports=['CFB', 'CBB'] + [k.upper() for k in ('nba', 'nhl', 'nfl') if k in d])
    p = os.path.join(ROOT, 'research', 'library.json'); lib = json.load(open(p))
    sec = next(s for s in lib['sections'] if s['id'] == 'teams')
    sec['entries'] = [x for x in sec['entries'] if x['term'] != TERM] + [e]
    json.dump(lib, open(p, 'w'), ensure_ascii=False, indent=1)
    print('ref entry written')


if __name__ == '__main__':
    main()
