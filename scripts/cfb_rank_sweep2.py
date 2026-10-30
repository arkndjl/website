#!/usr/bin/env python3
"""CFB team-rating sweep, round 2 (thread "Improve CFB team rankings and FV", Oct 30 2026): game-level ideas the
Oct 29 sweep (scripts/cfb_rank_sweep.py) and earlier work never tested, scored on top of the shipped walk-forward
margin m.

Rows: scripts/data/games_wf/cfb.json.gz (lined FBS games, shipped m, close L, result res) joined to
scripts/data/cfb_hist_md.json.gz (CFBD games, drives; 2015-25), so 2017-25. Each candidate x enters as
res = m + a + b x, fit on tune 2017-20 and scored as is on held 2021-25. Pre-registered (name, expected sign of b):
  retTD   (-) return-TD luck: a team's non-offensive TDs scored minus allowed a game (pick-sixes, fumble returns, punt
          and missed-FG returns, blocked punts) to date, shrunk by 3 games toward 0, home minus away. Elo rates on raw
          margins, so a team that scored on returns is over-rated if those don't repeat
  bowl    (+) bowl need: a team at exactly 5 wins entering its last regular-season game (not a title game), home minus
          away. 2020 out (eligibility waived)
  dead    (-) out of bowl contention: wins plus games left (this one included) under 6 in the last three regular-season
          games, home minus away. 2020 out
  riv     (-) rivalry compression: m x (pair is in Wikipedia's FBS rivalry list); b < 0 = rivalry margins land closer
  rivT    (-) the same for trophy games only
  bcr     (+) blue-chip ratio: share of a team's 247 composite signees in classes S-3..S rated .89+ (four and five
          stars), home minus away. The prior already has class talent (tal247, the mean composite); this asks whether
          the share of blue-chippers adds (Bud Elliott's rule: title teams sign more blue-chippers than not). Also
          reported on weeks 1-4 alone, where the prior weighs most. Cache: scripts/.cache/cfb/r247 (cfb_roster_hist.py --247)
  hfaP4   (+) home field by tier: 1 when the home team is Power 4 (SEC, Big Ten, Big 12, ACC, Pac-12 through 2023,
          Notre Dame) and the site is not neutral (bigger crowds)
Pass bar (project rule): tune paired squared error t <= -1.5 with the expected sign, held t <= 0 and MAE not worse;
clustered by game day; Benjamini-Hochberg over the family on the held p. Reported against the close as well.
    python3 scripts/cfb_rank_sweep2.py   -> data/cfb_rank_sweep2.json
Result Oct 30 2026 (7,513 games; squared error t tune / held, b fit on tune): nothing passes, nothing shipped.
  retTD -0.27 / -1.09 (b -0.64, negative 7 of 9 seasons, held MAE t -2.1, but tune fails; vs close held +0.5)
  bowl -0.81 / -0.03, dead -0.27 / -0.81, riv -0.70 / -0.20 and rivT -0.30 / -0.12 (b > 0: rivalry margins do NOT
  compress), hfaP4 -0.69 / +1.31, bcr 0.00 / +1.64 (+2.3 in weeks 1-4). BH q >= .68 for every one.
Cache: scripts/.cache/cfb/rivalries.txt (Wikipedia raw of List_of_NCAA_college_football_rivalry_games;
fetched by curl when missing).
"""
import collections
import datetime
import gzip
import json
import math
import os
import re
import subprocess
import sys
import unicodedata

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import harness as H  # noqa: E402

WF = os.path.join(HERE, 'data', 'games_wf', 'cfb.json.gz')
MD = os.path.join(HERE, 'data', 'cfb_hist_md.json.gz')
RIV = os.path.join(HERE, '.cache', 'cfb', 'rivalries.txt')
OUT = os.path.join(ROOT, 'data', 'cfb_rank_sweep2.json')
TUNE, HELD = range(2017, 2021), range(2021, 2026)
RET_TD = {'INT TD', 'FUMBLE TD', 'FUMBLE RETURN TD', 'PUNT TD', 'PUNT RETURN TD', 'MISSED FG TD'}
P4C = {'SEC', 'Big Ten', 'Big 12', 'ACC'}
SIGN = {'retTD': -1, 'bowl': 1, 'dead': -1, 'riv': -1, 'rivT': -1, 'hfaP4': 1, 'bcr': 1}
R247 = os.path.join(HERE, '.cache', 'cfb', 'r247')


def norm(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode().lower()
    s = s.replace('&', 'and').replace('state', 'st')
    return re.sub(r'[^a-z0-9]', '', s)


def rivalries():
    if not os.path.exists(RIV):
        os.makedirs(os.path.dirname(RIV), exist_ok=True)
        subprocess.run(['curl', '-sSL', '-m', '60', '-A', 'Mozilla/5.0 (research script)', '-o', RIV,
                        'https://en.wikipedia.org/w/index.php?title=List_of_NCAA_college_football_rivalry_games&action=raw'], check=True)
    txt = open(RIV, encoding='utf8').read()
    fbs = txt.split('==NCAA Division I Football Championship Subdivision==')[0]
    pairs, trophy = set(), set()
    for m in re.finditer(r'\{\{Trophy game\|(.*?)\}\}\s*$', fbs, re.M):
        parts, depth, cur = [], 0, ''
        for ch in m.group(1):
            if ch in '[{': depth += 1
            if ch in ']}': depth -= 1
            if ch == '|' and depth == 0: parts.append(cur); cur = ''
            else: cur += ch
        parts.append(cur)
        if len(parts) < 4: continue
        team = lambda p: re.sub(r'\[\[(?:[^|\]]*\|)?([^\]]*)\]\]', r'\1', p).strip()
        a, b = norm(team(parts[2])), norm(team(parts[3]))
        if not a or not b: continue
        k = frozenset((a, b)); pairs.add(k)
        if parts[1].strip(): trophy.add(k)
    return pairs, trophy


def main():
    md = json.load(gzip.open(MD))
    wf = json.load(gzip.open(WF))
    games = {str(g['id']): g for S in md['games'] for g in md['games'][S]}
    pairs, trophy = rivalries()

    # per season: each team's games in date order (all completed games, FCS included) and return TDs a game
    ret = collections.defaultdict(lambda: collections.defaultdict(int))  # gid -> team -> net return TDs
    for S, ds in md['drives'].items():
        for d in ds:
            if d['res'] in RET_TD:
                ret[str(d['g'])][d['d']] += 1; ret[str(d['g'])][d['o']] -= 1
    sched = collections.defaultdict(list)  # (S, team) -> games
    for S, gs in md['games'].items():
        for g in gs:
            if g['seasonType'] != 'regular': continue
            for t in (g['homeTeam'], g['awayTeam']): sched[(int(S), t)].append(g)
    for v in sched.values(): v.sort(key=lambda g: g['startDate'])

    def team_state(S, t, gid, date):
        gs = sched.get((S, t), [])
        before = [g for g in gs if g['startDate'] < date and g['completed'] and g['homePoints'] is not None]
        wins = sum(1 for g in before if (g['homePoints'] > g['awayPoints']) == (g['homeTeam'] == t))
        rt = sum(ret[str(g['id'])].get(t, 0) for g in before)
        reg = [g for g in gs if 'championship' not in (g['notes'] or '').lower()]
        idx = next((i for i, g in enumerate(reg) if str(g['id']) == gid), None)
        left = len(reg) - idx if idx is not None else None
        return {'wins': wins, 'n': len(before), 'ret': rt / (len(before) + 3), 'left': left}

    cls = {y: json.load(open(os.path.join(R247, f'{y}.json'))) for y in range(2013, 2026) if os.path.exists(os.path.join(R247, f'{y}.json'))}
    bcr = {}
    for S in range(2017, 2026):
        n, b = collections.Counter(), collections.Counter()
        for y in range(S - 3, S + 1):
            for x in cls.get(y, []):
                if not x['school']: continue
                k = norm(x['school']); n[k] += 1; b[k] += x['comp'] >= 0.89
        bcr[S] = {k: b[k] / n[k] for k in n}
    rows = []
    for r in wf:
        g = games.get(r['id'])
        if not g or r['S'] not in TUNE and r['S'] not in HELD or r.get('res') is None: continue
        S, date, h, a = r['S'], g['startDate'], g['homeTeam'], g['awayTeam']
        hs, as_ = team_state(S, h, r['id'], date), team_state(S, a, r['id'], date)
        reg = g['seasonType'] == 'regular' and 'championship' not in (g['notes'] or '').lower()
        bowl = lambda s: 1.0 if reg and S != 2020 and s['left'] == 1 and s['wins'] == 5 else 0.0
        dead = lambda s: 1.0 if reg and S != 2020 and s['left'] is not None and s['left'] <= 3 and s['wins'] + s['left'] < 6 else 0.0
        pr = frozenset((norm(h), norm(a)))
        p4 = lambda c: 1.0 if c in P4C or (c == 'Pac-12' and S <= 2023) or c == 'FBS Independents' and h == 'Notre Dame' else 0.0
        rows.append({'S': S, 'day': date[:10], 'm': r['m'], 'L': r.get('L'), 'res': r['res'], 'sig': r.get('sigma') or 16,
                     'x': {'retTD': hs['ret'] - as_['ret'], 'bowl': bowl(hs) - bowl(as_), 'dead': dead(hs) - dead(as_),
                           'riv': r['m'] * (1.0 if pr in pairs else 0.0), 'rivT': r['m'] * (1.0 if pr in trophy else 0.0),
                           'hfaP4': 0.0 if g['neutralSite'] else p4(g['homeConference']),
                           'bcr': bcr.get(S, {}).get(norm(h), 0.0) - bcr.get(S, {}).get(norm(a), 0.0)},
                     'wk': g['week'] if g['seasonType'] == 'regular' else 20,
                     'flags': {'riv': pr in pairs, 'rivT': pr in trophy}})
    S = np.array([r['S'] for r in rows]); y = np.array([r['res'] for r in rows], float); m = np.array([r['m'] for r in rows], float)
    day = np.array([r['day'] for r in rows]); sig = np.array([r['sig'] for r in rows], float)
    L = np.array([np.nan if r['L'] is None else r['L'] for r in rows], float)
    tune, held = np.isin(S, list(TUNE)), np.isin(S, list(HELD))
    # wf L is the home line in margin units (m and L share a sign convention: corr check below)
    Lm = L if np.nanmean(np.abs(L - m)) < np.nanmean(np.abs(-L - m)) else -L
    Phi = lambda z: 0.5 * (1 + np.vectorize(math.erf)(z / math.sqrt(2)))
    ll = lambda p: -(np.where(y > 0, np.log(np.clip(p, 1e-9, 1)), 0) + np.where(y < 0, np.log(np.clip(1 - p, 1e-9, 1)), 0))
    out = {'asof': datetime.date.today().isoformat(), 'rows': len(rows), 'tune': [TUNE[0], TUNE[-1]], 'held': [HELD[0], HELD[-1]],
           'rivalryPairs': len(pairs), 'trophyPairs': len(trophy),
           'rivalryGames': int(sum(r['flags']['riv'] for r in rows)), 'trophyGames': int(sum(r['flags']['rivT'] for r in rows)),
           'base': {p: {'maeModel': round(float(np.abs(y - m)[mk].mean()), 3), 'maeClose': round(float(np.nanmean(np.abs(y - Lm)[mk])), 3), 'n': int(mk.sum())}
                    for p, mk in (('tune', tune), ('held', held))}, 'cands': {}}
    ps = []
    for k, sg in SIGN.items():
        x = np.array([r['x'][k] for r in rows], float)
        X = np.column_stack([np.ones(len(x)), x])
        b = np.linalg.lstsq(X[tune], (y - m)[tune], rcond=None)[0]
        new = m + X @ b
        old = m + (y - m)[tune].mean()  # intercept-only refit, so the test is x alone
        o = {'b': round(float(b[1]), 3), 'nonzero': int((x != 0).sum()), 'mean|x|': round(float(np.abs(x).mean()), 3)}
        for part, mk in (('tune', tune), ('held', held)):
            pse = H.paired(H.se(new[mk], y[mk]), H.se(old[mk], y[mk]), cluster=day[mk])
            pae = H.paired(np.abs(new - y)[mk], np.abs(old - y)[mk], cluster=day[mk])
            pll = H.paired(ll(Phi(new / sig))[mk], ll(Phi(old / sig))[mk], cluster=day[mk])
            o[part] = {'se_t': round(pse['t'], 2), 'se_d': round(pse['d'], 4), 'p': pse['p'], 'mae_d': round(pae['d'], 4), 'mae_t': round(pae['t'], 2), 'll_t': round(pll['t'], 2)}
        # held-out, against the close: does x explain res - close? (b fit on tune on res - L)
        okL = ~np.isnan(Lm)
        bc = np.linalg.lstsq(X[tune & okL], (y - Lm)[tune & okL], rcond=None)[0]
        mk = held & okL
        pc = H.paired(H.se((Lm + X @ bc)[mk], y[mk]), H.se((Lm + bc[0])[mk], y[mk]), cluster=day[mk])
        o['close'] = {'b': round(float(bc[1]), 3), 'held_se_t': round(pc['t'], 2)}
        # per-season sign of b (refit within each season)
        o['bBySeason'] = {}
        for s in sorted(set(S.tolist())):
            mk = S == s
            if (x[mk] != 0).sum() < 10: continue
            o['bBySeason'][int(s)] = round(float(np.linalg.lstsq(X[mk], (y - m)[mk], rcond=None)[0][1]), 3)
        signok = o['b'] * sg > 0
        e = np.array([r['wk'] <= 4 for r in rows])
        for part, mk in (('tuneWk1_4', tune & e), ('heldWk1_4', held & e)):
            pse = H.paired(H.se(new[mk], y[mk]), H.se(old[mk], y[mk]), cluster=day[mk])
            o[part] = {'se_t': round(pse['t'], 2), 'se_d': round(pse['d'], 4)}
        o['pass'] = bool(signok and o['tune']['se_t'] <= -1.5 and o['held']['se_t'] <= 0 and o['held']['mae_d'] <= 0)
        ps.append(o['held']['p'])
        out['cands'][k] = o
        print(k, json.dumps(o), flush=True)
    q = H.bh(ps)
    for (k, o), qq in zip(out['cands'].items(), q): o['q_held'] = round(float(qq), 3)
    json.dump(out, open(OUT, 'w'), indent=1)
    print('->', OUT)


if __name__ == '__main__':
    main()
