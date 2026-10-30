#!/usr/bin/env python3
"""FV driver test (thread "Improve CFB team rankings and FV", Oct 30 2026): college "dominator" share, the player's
share of his team's production in his final college season. Never tested before (Oct 14 / 21 / 24 sweeps tested raw
production, breakout age, cast, context, AA, Senior Bowl, ESPN/PFF grades, measurables).

Pre-registered (expected sign +, one family):
  WR, TE  (receiving yards share + receiving TD share) / 2
  RB      (scrimmage yards share + scrimmage TD share) / 2
  EDGE/DL sacks share
  LB      (sacks + pass breakups + interceptions) share
  DB      (interceptions + pass breakups) share
(Tackles and TFL were the plan; cfbfastR's play-by-play has no tackler, and ESPN's byathlete offense leaderboard
now returns empty values, so defense uses the playmaking stats the play-by-play names.)
Shares are of the team's season totals (every play, cfbfastR pbp_players_pos parquet; 2013 is missing there).
Universe: NFL draftees 2015-23 (nflverse draft_picks) at those groups, joined by name + school (scripts/names.py) to
the season before the draft; cached in scripts/.cache/cfb/dom. Outcome: weighted AV a season through 2025. Control: the draft slot (group intercepts,
group x ln pick, ln pick squared), so a pass means the share carries information the draft (the market) missed, which
FV's production term doesn't hold (FV production is PFN's per-snap grade, not team share). Also reported with raw
volume (the same stat a game) in the control, so share is not just volume.
Gate (as cfb_draft_source_backtest.mjs): leave-one-class-out held-out R^2 gain with fold t >= 2, within-group
Spearman not worse, forward (fit 2014-19, score 2020-23) not worse.
    python3 scripts/cfb_dominator_backtest.py   -> data/cfb_dominator_backtest.json
Result Oct 30 2026 (1,358 draftees, 9 classes): FAILS. Share on the slot control b .03 (t .55), fold t -1.79 (3 of 9
classes up), within-group Spearman .5765 -> .5761, forward -0.12. With volume held, fold t .07 and forward -0.31. By
group (t): WR -1.3, TE .6, RB 1.5, EDGE -.6, DL .7, LB 1.4, DB -.1. The draft already prices team share.
Caveat: defenders with no sack, breakup or interception are absent from the play-by-play stats, so they drop out
(EDGE 96, DL 85, DB 134 unmatched).
"""
import collections
import datetime
import json
import math
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import names as N  # noqa: E402

C = os.path.join(HERE, '.cache', 'cfb', 'dom')
OUT = os.path.join(ROOT, 'data', 'cfb_dominator_backtest.json')
CLASSES, NFL_THROUGH, FWD = range(2015, 2024), 2025, 2020
GROUP = {'WR': 'WR', 'TE': 'TE', 'RB': 'RB', 'FB': 'RB', 'DE': 'EDGE', 'OLB': 'EDGE', 'EDGE': 'EDGE', 'DT': 'DL', 'NT': 'DL', 'DL': 'DL',
         'ILB': 'LB', 'LB': 'LB', 'MLB': 'LB', 'CB': 'DB', 'S': 'DB', 'SAF': 'DB', 'DB': 'DB', 'FS': 'DB', 'SS': 'DB'}
PBP = 'https://raw.githubusercontent.com/sportsdataverse/cfbfastR-data/main/data/parquet/pbp_players_pos_{S}.parquet'
STATS = ['recYds', 'recTd', 'tgt', 'rushYds', 'rushTd', 'sacks', 'pbu', 'ints']


def season(S):
    """per (team, player) season totals from cfbfastR's play-by-play (offense: pos_team; defense: def_pos_team)"""
    p = os.path.join(C, f'stats{S}.json')
    if os.path.exists(p): return json.load(open(p))
    f = os.path.join(C, 'pbp', f'p{S}.parquet')
    if not os.path.exists(f):
        os.makedirs(os.path.dirname(f), exist_ok=True)
        subprocess.run(['curl', '-sSLf', '-m', '600', '-o', f, PBP.format(S=S)], check=True)
    import pandas as pd
    cols = ['pos_team', 'def_pos_team', 'reception_player', 'reception_yds', 'rush_player', 'rush_yds', 'touchdown_player', 'rush_td', 'pass_td',
            'target_player', 'sack_player', 'sack_stat', 'pass_breakup_player', 'interception_player']
    d = pd.read_parquet(f, columns=cols)
    acc = collections.defaultdict(lambda: dict.fromkeys(STATS, 0.0))
    def add(team, who, k, v):
        if isinstance(who, str) and who and isinstance(team, str): acc[(team, who)][k] += float(v)
    for r in d.itertuples(index=False):
        if isinstance(r.reception_player, str): add(r.pos_team, r.reception_player, 'recYds', r.reception_yds or 0)
        if isinstance(r.target_player, str): add(r.pos_team, r.target_player, 'tgt', 1)
        if isinstance(r.rush_player, str): add(r.pos_team, r.rush_player, 'rushYds', r.rush_yds or 0)
        if isinstance(r.touchdown_player, str):
            if r.pass_td == 1 and r.touchdown_player == r.reception_player: add(r.pos_team, r.touchdown_player, 'recTd', 1)
            elif r.rush_td == 1: add(r.pos_team, r.touchdown_player, 'rushTd', 1)
        if isinstance(r.sack_player, str): add(r.def_pos_team, r.sack_player, 'sacks', r.sack_stat if r.sack_stat == r.sack_stat and r.sack_stat else 1)
        if isinstance(r.pass_breakup_player, str): add(r.def_pos_team, r.pass_breakup_player, 'pbu', 1)
        if isinstance(r.interception_player, str): add(r.def_pos_team, r.interception_player, 'ints', 1)
    out = [{'team': t, 'n': n, **v} for (t, n), v in acc.items()]
    json.dump(out, open(p, 'w'))
    print('pbp', S, len(out), 'player-teams', flush=True)
    return out


def csv_rows(p):
    import csv
    return list(csv.DictReader(open(p, encoding='utf8')))


def stat(r, *ks):
    return sum(float(r.get(k) or 0) for k in ks)


SHARE = {  # group -> list of (numerator stat keys) averaged as shares; volume = the first one's season total
    'WR': [('recYds',), ('recTd',)],
    'TE': [('recYds',), ('recTd',)],
    'RB': [('rushYds', 'recYds'), ('rushTd', 'recTd')],
    'EDGE': [('sacks',)],
    'DL': [('sacks',)],
    'LB': [('sacks', 'pbu', 'ints')],
    'DB': [('ints', 'pbu')],
}


def main():
    os.makedirs(C, exist_ok=True)
    dp = os.path.join(C, 'draft_picks.csv')
    if not os.path.exists(dp):
        subprocess.run(['curl', '-sSL', '-m', '120', '-o', dp, 'https://github.com/nflverse/nflverse-data/releases/download/draft_picks/draft_picks.csv'], check=True)
    picks = [r for r in csv_rows(dp) if r['season'].isdigit() and int(r['season']) in CLASSES and GROUP.get(r['position'])]
    rows, miss = [], collections.Counter()
    for S in sorted({int(r['season']) - 1 for r in picks}):
        A = season(S)
        tot = collections.defaultdict(lambda: collections.defaultdict(float))
        for a in A:
            for k in STATS: tot[a['team']][k] += a[k]
        M = N.Matcher(A, name='n', team='team', pos=None, id=None)
        for p in (r for r in picks if int(r['season']) == S + 1):
            g = GROUP[p['position']]
            a, how = M.find(p['pfr_player_name'], team=p['college'], cross_team='none')
            if a is None: miss[g] += 1; continue
            T = tot[a['team']]
            parts = []
            for ks in SHARE[g]:
                den = sum(T.get(k, 0) for k in ks)
                parts.append(stat(a, *ks) / den if den > 0 else 0.0)
            D = S + 1
            rows.append({'cls': D, 'g': g, 'name': p['pfr_player_name'], 'pick': int(p['pick']), 'share': float(np.mean(parts)),
                         'vol': stat(a, *SHARE[g][0]), 'av': float(p['w_av'] or 0) / (NFL_THROUGH - D + 1)})
    print('rows', len(rows), 'unmatched', dict(miss), flush=True)
    res = evaluate(rows)
    res.update({'asof': datetime.date.today().isoformat(), 'n': len(rows), 'unmatched': dict(miss),
                'byGroup': {g: sum(1 for r in rows if r['g'] == g) for g in SHARE}})
    json.dump(res, open(OUT, 'w'), indent=1)
    print(json.dumps({k: v for k, v in res.items() if k != 'perClass'}, indent=1))


def design(rows, extra):
    G = sorted(SHARE)
    X = []
    for r in rows:
        lp = math.log(r['pick'])
        x = [1.0 if r['g'] == g else 0.0 for g in G] + [lp * (1.0 if r['g'] == g else 0.0) for g in G] + [lp * lp]
        X.append(x + [f(r) for f in extra])
    return np.array(X)


def zs(rows, k):
    # z within group x class, so the share's scale differs by group but not the test
    by = collections.defaultdict(list)
    for r in rows: by[(r['g'], r['cls'])].append(r[k])
    st = {g: (np.mean(v), np.std(v) or 1) for g, v in by.items()}
    return lambda r: (r[k] - st[(r['g'], r['cls'])][0]) / st[(r['g'], r['cls'])][1]


def spear(a, b):
    from scipy.stats import spearmanr  # noqa
    return spearmanr(a, b).correlation


def wspear(rows, pr):
    s = n = 0
    for g in SHARE:
        ix = [i for i, r in enumerate(rows) if r['g'] == g]
        if len(ix) < 15: continue
        a, b = np.argsort(np.argsort(pr[ix])), np.argsort(np.argsort([rows[i]['av'] for i in ix]))
        s += len(ix) * np.corrcoef(a, b)[0, 1]; n += len(ix)
    return s / n


def evaluate(rows):
    y = np.array([r['av'] for r in rows])
    cls = np.array([r['cls'] for r in rows])
    zsh, zvol = zs(rows, 'share'), zs(rows, 'vol')
    out = {}
    for name, base, cand in (('share', [], [zsh]), ('share|vol', [zvol], [zsh]), ('vol', [], [zvol])):
        X0, X1 = design(rows, base), design(rows, base + cand)
        b1 = np.linalg.lstsq(X1, y, rcond=None)[0]
        e = y - X1 @ b1
        cov = np.linalg.pinv(X1.T @ X1) * (e @ e) / (len(y) - X1.shape[1])
        t_in = b1[-1] / math.sqrt(cov[-1, -1])
        gains, p0, p1 = [], np.zeros(len(y)), np.zeros(len(y))
        for c in CLASSES:
            tr, te = cls != c, cls == c
            for X, p in ((X0, p0), (X1, p1)):
                p[te] = X[te] @ np.linalg.lstsq(X[tr], y[tr], rcond=None)[0]
            sst = ((y[te] - y[te].mean()) ** 2).sum()
            gains.append(100 * (((y[te] - p0[te]) ** 2).sum() - ((y[te] - p1[te]) ** 2).sum()) / sst)
        g = np.array(gains)
        tr, te = cls < FWD, cls >= FWD
        f0 = X0[te] @ np.linalg.lstsq(X0[tr], y[tr], rcond=None)[0]; f1 = X1[te] @ np.linalg.lstsq(X1[tr], y[tr], rcond=None)[0]
        sst = ((y[te] - y[te].mean()) ** 2).sum()
        fwd = 100 * (((y[te] - f0) ** 2).sum() - ((y[te] - f1) ** 2).sum()) / sst
        rte = [rows[i] for i in np.where(te)[0]]
        o = {'b': round(float(b1[-1]), 3), 't_in': round(float(t_in), 2), 'foldGain': round(float(g.mean()), 3),
             'foldT': round(float(g.mean() / (g.std(ddof=1) / math.sqrt(len(g)))), 2), 'classesUp': int((g > 0).sum()),
             'spearman': [round(wspear(rows, p0), 4), round(wspear(rows, p1), 4)], 'fwdGain': round(float(fwd), 3),
             'fwdSpearman': [round(wspear(rte, f0), 4), round(wspear(rte, f1), 4)], 'perClass': [round(float(x), 2) for x in g]}
        o['pass'] = bool(o['foldT'] >= 2 and o['spearman'][1] >= o['spearman'][0] and o['fwdGain'] >= 0 and o['fwdSpearman'][1] >= o['fwdSpearman'][0])
        # by group (share alone on the slot control)
        if name == 'share':
            o['byGroup'] = {}
            for gg in SHARE:
                mk = np.array([r['g'] == gg for r in rows])
                Xg = X1[mk]; yg = y[mk]
                bb = np.linalg.lstsq(Xg, yg, rcond=None)[0]; ee = yg - Xg @ bb
                cv = np.linalg.pinv(Xg.T @ Xg) * (ee @ ee) / max(1, len(yg) - np.linalg.matrix_rank(Xg))
                o['byGroup'][gg] = {'n': int(mk.sum()), 'b': round(float(bb[-1]), 3), 't': round(float(bb[-1] / math.sqrt(max(cv[-1, -1], 1e-12))), 2)}
        out[name] = o
    return out


if __name__ == '__main__':
    main()
