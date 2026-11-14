#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""CFP projected bracket backtest: the season sim's projected seeding against "if the season ended today".

    python3 scripts/cfb_cfp_seeds.py      # -> data/cfb_cfp_seeds.json (~2 min)

From the end of weeks 10 and 12 of 2017-25 (not 2020), the rest of the regular season and the title games simulated
as in scripts/cfb_cfp.py sim_backtest (2,000 finishes), the committee's final ranking drawn from the Plackett-Luce
fit on 2017-21 only (betaTune, so 2022-25 are held out), the 12-team field (five best-ranked champions + seven) and
seeds 1-12 by rank. The projected bracket = the assignment of teams to seeds with the most expected exact seeds
(scripts/bracket.py). Baseline: the committee's own ranking released after that week, the highest-ranked team of each
conference as its champion, the same field rule. Truth: the same rule on the final release and the real champions.
Committee memory: the final ranking leans on the committee's own ranking at the checkpoint; score + gamma x
(26 - rank) / 25 (0 unranked), gamma fit on the 2017-21 finals' real inputs. Scored per seed slot: exact team, team in the field; and the log loss of each real field team's seed under the sim's
seed odds (no baseline: it is a single bracket)."""
import json
import math
import os
from collections import defaultdict

import numpy as np

import cfb_cfp as C
import bracket as B

OUT = os.path.join(C.ROOT, 'data', 'cfb_cfp_seeds.json')
WEEKS = (10, 12)


def seeds_of(order, mask):
    f = set(C.pick12(order, mask))
    return [i for i in order if i in f][:12]


def main():
    hist, polls, wf = C.load()
    games = {int(S): g for S, g in hist['games'].items()}
    by_id = {str(g['id']): g for S in games for g in games[S]}
    wfr = C.wf_rows(wf, by_id)
    info = {S: C.season_info(games[S], S) for S in games}
    rels = defaultdict(list)
    for r in polls['releases']:
        if r['poll'] == 'cfp' and r['S'] in games and r['S'] >= 2017:
            rels[r['S']].append(r)
    fit = json.load(open(C.OUT))
    cols = [C.FEATS_ALL.index(f) for f in fit['feats']]
    beta = np.array(fit['betaTune'])
    rng = np.random.default_rng(20261114)
    # committee memory: the final ranking leans on the ranking the committee released after week wk. Fit gamma on the
    # 2017-21 finals' real inputs (beta fixed): s = x . beta + gamma x mem, mem = (26 - rank) / 25 in that release, 0 unranked
    finals = {}
    for S in range(2017, 2026):
        if S == 2020 or S not in rels:
            continue
        rs = sorted(rels[S], key=lambda r: r['date'])
        finals[S] = (rs, C.release_rows(S, rs[-1], info[S], wfr, True))
    def mem_of(rel, teams):
        rk = {x['id']: x['rk'] for x in rel['ranks']}
        return np.array([(26 - rk[t]) / 25 if t in rk else 0.0 for t in teams])
    def ll_final(fr, s):
        alive = np.ones(len(s), bool); out = 0.0
        for i in fr['order']:
            m = s[alive].max(); out += s[i] - m - math.log(np.exp(s[alive] - m).sum()); alive[i] = False
        return out
    gam = {}
    for wk in WEEKS:
        cand = {}
        for g in np.arange(0, 8.01, 0.25):
            tot = 0.0
            for S, (rs, fr) in finals.items():
                rel = next((r for r in rs if str(r['week']) == str(wk + 1)), None)
                if S in C.TUNE and rel is not None:
                    tot += ll_final(fr, fr['X'][:, cols] @ beta + g * mem_of(rel, fr['teams']))
            cand[round(float(g), 2)] = tot
        gam[wk] = max(cand, key=cand.get)
        hold = lambda g: sum(ll_final(fr, fr['X'][:, cols] @ beta + g * mem_of(next(r for r in rs if str(r['week']) == str(wk + 1)), fr['teams']))
                             for S, (rs, fr) in finals.items() if S in C.HOLD)
        print('week', wk, 'gamma', gam[wk], 'tune ll', round(cand[gam[wk]], 2), 'vs', round(cand[0.0], 2),
              'hold ll', round(hold(gam[wk]), 2), 'vs', round(hold(0.0), 2), flush=True)
    # live: gamma refit with the all-season beta on every final (the live sim uses that beta)
    beta_all = np.array(fit['beta'])
    gam_live = {}
    for wk in WEEKS:
        cand = {}
        for g in np.arange(0, 8.01, 0.25):
            cand[round(float(g), 2)] = sum(ll_final(fr, fr['X'][:, cols] @ beta_all + g * mem_of(next(r for r in rs if str(r['week']) == str(wk + 1)), fr['teams']))
                                           for S, (rs, fr) in finals.items() if any(str(r['week']) == str(wk + 1) for r in rs))
        gam_live[wk] = max(cand, key=cand.get)
    print('live gamma', gam_live, flush=True)
    rows = []
    for S in range(2017, 2026):
        if S == 2020 or S not in rels:
            continue
        rs = sorted(rels[S], key=lambda r: r['date'])
        fr = C.release_rows(S, rs[-1], info[S], wfr, True)
        teams = fr['teams']; T = len(teams)
        truth = seeds_of(list(fr['order']) + [i for i in range(T) if i not in fr['order']],
                         np.array([t in fr['champs'] for t in teams]))
        for wk in WEEKS:
            rel = next((r for r in rs if str(r['week']) == str(wk + 1)), None)
            if rel is None:
                continue
            D = C.sim_draws(S, wk, fr, info, wfr, rng)
            N, F, champ = D['N'], D['feats'], D['champ']
            sc = sum(beta[k] * F[C.FEATS_ALL[c]] for k, c in enumerate(cols)) + rng.gumbel(size=(N, T))
            tal = B.Tally({'cfp': 12}, ['in'])
            for n in range(N):
                tal.season(); tal.seeds('cfp', seeds_of(list(np.argsort(-sc[n])), champ[n].astype(bool)))
            proj, _, sd0 = tal.project()
            pj0 = [r['t'] for r in proj['cfp']]
            scm = sc + gam[wk] * mem_of(rel, teams)[None, :]
            tal = B.Tally({'cfp': 12}, ['in'])
            for n in range(N):
                tal.season(); tal.seeds('cfp', seeds_of(list(np.argsort(-scm[n])), champ[n].astype(bool)))
            proj, _, sd = tal.project()
            pj = [r['t'] for r in proj['cfp']]
            # baseline: that week's committee ranking, highest-ranked team per conference = champion
            conf = fr['conf']; ix = {t: i for i, t in enumerate(teams)}
            ranked = [ix[x['id']] for x in sorted(rel['ranks'], key=lambda x: x['rk']) if x['id'] in ix]
            seen, mask = set(), np.zeros(T, bool)
            for i in ranked:
                c = conf.get(teams[i])
                if c and 'Independent' not in c and c not in seen:
                    seen.add(c); mask[i] = True
            base = seeds_of(ranked + [i for i in range(T) if i not in ranked], mask)
            tset = set(truth)
            seedll = []
            for k, i in enumerate(truth):
                p = sd['cfp'].get(i, [0] * 12)[k]
                seedll.append(-math.log(max(p, 1 / (N + 1))))
            seedll0 = [-math.log(max(sd0['cfp'].get(i, [0] * 12)[k], 1 / (N + 1))) for k, i in enumerate(truth)]
            rows.append({'S': S, 'wk': wk, 'part': 'tune' if S in C.TUNE else 'hold',
                         'exactNoMem': [int(pj0[k] == truth[k]) for k in range(12)], 'inNoMem': sum(i in tset for i in pj0),
                         'seedLLNoMem': float(np.mean(seedll0)), 'seedLLs': seedll, 'seedLLs0': seedll0,
                         'exactProj': [int(pj[k] == truth[k]) for k in range(12)],
                         'exactBase': [int(base[k] == truth[k]) for k in range(12)],
                         'inProj': sum(i in tset for i in pj), 'inBase': sum(i in tset for i in base),
                         'seedLL': float(np.mean(seedll)),
                         'absProj': float(np.mean([abs(k - pj.index(i)) if i in pj else 12 - k for k, i in enumerate(truth)])),
                         'absBase': float(np.mean([abs(k - base.index(i)) if i in base else 12 - k for k, i in enumerate(truth)])),
                         'proj': [teams[i] for i in pj], 'base': [teams[i] for i in base], 'truth': [teams[i] for i in truth]})
            print(S, wk, 'nomem', sum(rows[-1]['exactNoMem']), rows[-1]['inNoMem'], 'exact', sum(rows[-1]['exactProj']), 'vs', sum(rows[-1]['exactBase']),
                  'field', rows[-1]['inProj'], 'vs', rows[-1]['inBase'], flush=True)
    res = {}
    for wk in WEEKS:
        for part in ('tune', 'hold', 'all'):
            rr = [r for r in rows if r['wk'] == wk and (part == 'all' or r['part'] == part)]
            if not rr:
                continue
            d = np.array([a - b for r in rr for a, b in zip(r['exactProj'], r['exactBase'])], float)
            dd = np.array([r['inProj'] - r['inBase'] for r in rr], float)
            da = np.array([r['absBase'] - r['absProj'] for r in rr], float)
            tt = lambda x: round(float(x.mean() / (x.std(ddof=1) / math.sqrt(len(x)))), 2) if x.std(ddof=1) > 0 else 0.0
            res[f'wk{wk}_{part}'] = {
                'seasons': len(rr), 'exactProj': round(float(np.mean([sum(r['exactProj']) for r in rr])), 2),
                'exactBase': round(float(np.mean([sum(r['exactBase']) for r in rr])), 2), 'tExact': tt(d),
                'fieldProj': round(float(np.mean([r['inProj'] for r in rr])), 2), 'fieldBase': round(float(np.mean([r['inBase'] for r in rr])), 2),
                'tField': tt(dd), 'absProj': round(float(np.mean([r['absProj'] for r in rr])), 2),
                'absBase': round(float(np.mean([r['absBase'] for r in rr])), 2), 'tAbs': tt(da),
                'seedLL': round(float(np.mean([r['seedLL'] for r in rr])), 3),
                'seedLLNoMem': round(float(np.mean([r['seedLLNoMem'] for r in rr])), 3),
                'tSeedLL': tt(np.array([a - b for r in rr for a, b in zip(r['seedLLs0'], r['seedLLs'])])),
                'exactNoMem': round(float(np.mean([sum(r['exactNoMem']) for r in rr])), 2),
                'fieldNoMem': round(float(np.mean([r['inNoMem'] for r in rr])), 2),
                'tExactVsNoMem': tt(np.array([a - b for r in rr for a, b in zip(r['exactProj'], r['exactNoMem'])], float)),
                'betterSeasons': sum(sum(r['exactProj']) > sum(r['exactBase']) for r in rr),
                'worseSeasons': sum(sum(r['exactProj']) < sum(r['exactBase']) for r in rr)}
    out = {'gamma': {str(k): v for k, v in gam.items()}, 'gammaLive': {str(k + 1): v for k, v in gam_live.items()},
           'gammaNote': 'gammaLive keyed by the release label (ESPN week of the CFP release: 11 = after week 10)', 'note': 'CFP projected bracket vs the committee ranking that week (scripts/cfb_cfp_seeds.py)', 'results': res, 'rows': rows}
    json.dump(out, open(OUT, 'w'), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == '__main__':
    main()
