#!/usr/bin/env python3
"""Big edges (Noah, Oct 30 2026): "Should we add predictions with an edge of 10 (or X number) or higher to the picks
board? Can we check to see what the games that we miss with a 10+ edge on have in common and use that absence to
improve the model?"

    python3 scripts/big_edge_research.py          # data/big_edge.json

Every game in the walk-forward files (scripts/data/games_wf/) with an opening line, bad opens out (clv.bad_open), the
model's side at the open, priced at Novig's -103 (games_picks.BT_PRICE) and judged by the close (clv.judge: clvRet) and
by the result. Seasons as the pick rules use them: tuning (games_picks.RULE_TUNE), validation (RULE_VAL), test (after).

1. Edge buckets in points (the picks table's Edge), and the moneyline board's Diff (model win % minus the open's), with
   the 3 sd cap the live picks skip as "a bad line" (games_picks_fit.json cap) marked.
2. The big-edge picks (gap 10+, or past the cap where the cap is under 10) that lost to the close: features fixed before
   looking (early season, postseason, neutral, favorite, long line, home, injuries against, FCS, bowl opt-outs, rest,
   the model's recent miss on each team, the open's source). A feature becomes an exclusion rule only if the picks it
   would drop lose to the close on the tuning seasons (t <= -1.65) and again on the held-out seasons.
3. The cap: picks past it, kept and staked as if at the cap, switched on by the rules' own bar (validation clvRet > 0,
   t >= 1.65, n >= 30; test-season veto).
NBA is an upper bound (the walk-forward model saw tip-time injury news); live picks are bet after part of the move
(units.TIMING).

Result (Oct 30 2026, at -103, judged by the close, held out = validation + test seasons):
- No adverse selection at the open: what a pick was worth rises with the gap to ~3 sd and then holds flat (pooled
  ex-NBA 2.5-3 sd +9.7%, 3-4 sd +9.9% held n 242, 4-5 sd +11.8% n 38; tuning alike). 10+ point edges held: CFB spread
  +5.3% (n 142), CFB total +8.7% (78), CBB total +10.1% (189), CBB spread past its 8.8 cap +9.2% (90).
- Most 10+ edges were not picks because of the 3 sd cap (games_picks.CAP), not the cuts. Shipped (games_picks.CAP_OUT):
  the board takes gaps out to 5 sd, sized as if at the cap. Walk-forward (pick_recal.py, edge0 s .5, 1x Kelly, cap 5):
  log growth at the close 480% -> 571% (true live edge x1), 292 -> 353 (x.75), 105 -> 135 (x.5), -45 -> -39 (x.3).
  Past 5 sd the tuning picks don't beat the close (+4.0% t .6; CBB spread -6.9% t -2.6): still skipped.
- Moneyline Diff 10+ (win % over the open's): CFB 10-15 held -0.2% (n 331), so no flat Diff rule; elsewhere a 10% Diff
  is ~3 points, which the spread cuts (2.5-4) already take.
- Big-edge losses: 14 features, none an exclusion (losing to the close on tuning and held out). The held-out losers
  cluster in openers against FCS / new D-I programs, CFB unders on 60+ totals and NBA's last two regular-season weeks,
  but each beats the close on the tuning seasons (FCS dogs covered 60% of 120 at the close 2017-20). Near miss:
  CFB spreads backing a team the model has overrated lately (last 3 games, 0.25 sd vs the opponent): tuning -1.1%
  (t -1.8), validation -2.9% (t -3.0), test +0.1% (2024-26 positive), so the test seasons veto it. As a model term
  (result minus model on that recent-miss gap) the market moves on it in every sport (close t 10-17) but held-out margin
  MAE barely moves (CFB -0.002 t -.1, NFL -0.019 t -1.0), as the earlier form tests found."""
import collections
import datetime
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import clv as C  # noqa: E402
import games_picks as GP  # noqa: E402

OUT = os.path.join(GP.ROOT, 'data', 'big_edge.json')
BIG = 10.0
BUCKETS = [(0.5, 2), (2, 4), (4, 6), (6, 8), (8, 10), (10, 12), (12, 15), (15, 99)]
DIFFS = [(0, 5), (5, 10), (10, 15), (15, 20), (20, 30), (30, 99)]
NOVIG_OVER = 2 / GP.dec(GP.BT_PRICE)              # -103 a side: the overround on a two-way price (1.0148)


def st(xs):
    xs = [x for x in xs if x is not None]
    n = len(xs)
    if n < 2:
        return {'n': n, 'mean': round(xs[0], 4) if xs else None, 't': None}
    m = sum(xs) / n
    s = math.sqrt(sum((v - m) ** 2 for v in xs) / (n - 1))
    return {'n': n, 'mean': round(m, 4), 't': round(m / (s / math.sqrt(n)), 2) if s else None}


def rec(es):
    return {'n': len(es), 'clvRet': st([e['clvRet'] for e in es]), 'roi': st([e['profit'] for e in es]),
            'beat': round(sum(1 for e in es if (e.get('clv') or 0) > 0) / len(es), 3) if es else None}


def era(sport, S):
    if S in GP.RULE_TUNE[sport]:
        return 'tune'
    if S in GP.RULE_VAL[sport]:
        return 'val'
    return 'test' if S > max(GP.RULE_TUNE[sport] + GP.RULE_VAL[sport]) else 'other'


def day(g):
    return datetime.date.fromisoformat(str(g['date'])[:10])


def team_context(sport, rows):
    """per game id: rest days for home and away, and each team's mean model miss (result minus model, its own side)
    over its last 3 games, margin and total, all from games before this one"""
    hist = collections.defaultdict(list)       # team -> [(date, margin miss, total miss)]
    out = {}
    for g in sorted(rows, key=lambda r: (str(r['date']), str(r['id']))):
        d = day(g)
        c = {}
        for t, sg in ((g['home'], 1), (g['away'], -1)):
            h = [x for x in hist[t] if x[0].year >= d.year - 1 and (d - x[0]).days < 200]
            c[sg] = {'rest': (d - h[-1][0]).days if h else None,
                     'miss': sum(x[1] for x in h[-3:]) / len(h[-3:]) if len(h) >= 3 else None,
                     'tmiss': sum(x[2] for x in h[-3:] if x[2] is not None) / max(1, sum(1 for x in h[-3:] if x[2] is not None)) if len(h) >= 3 else None}
        out[g['id']] = c
        if g.get('res') is not None and g.get('m') is not None:
            tm = (g['tot'] - g.get('tmRaw', g.get('tm'))) if g.get('tot') is not None and g.get('tm') is not None else None
            hist[g['home']].append((d, g['res'] - g['m'], tm))
            hist[g['away']].append((d, -(g['res'] - g['m']), tm))
    return out


def season_start(rows):
    s = {}
    for g in rows:
        d = day(g)
        if g['S'] not in s or d < s[g['S']]:
            s[g['S']] = d
    return s


def picks(sport, mk):
    """the model's side on every game with a usable open, with its features"""
    rows = [r for r in GP.load_wf(sport) if r.get('res') is not None]
    ctx = team_context(sport, rows)
    start = season_start(rows)
    # games each team has in the history before this one (a new or new-to-D-I program), and each season's last
    # regular-season day (rest and tanking at the end): added after reading the held-out losers, so judged on tuning
    cnt, prior, last = collections.Counter(), {}, {}
    for g in sorted(rows, key=lambda r: str(r['date'])):
        prior[g['id']] = min(cnt[g['home']], cnt[g['away']])
        cnt[g['home']] += 1
        cnt[g['away']] += 1
        if not g.get('po'):
            last[g['S']] = max(last.get(g['S'], day(g)), day(g))
    rs = [r for r in rows if (r.get('Lo') if mk == 'spread' else r.get('To')) is not None]
    es = GP.rule_bets(sport, rs, mk, 0.5, True, None)
    football = sport in ('cfb', 'nfl')
    sd = C.params(sport)[0 if mk == 'spread' else 1]
    out = []
    for e in es:
        g = e['g']
        if e.get('clvRet') is None:
            continue
        sg = 1 if e['side'] in ('home', 'over') else -1
        c = ctx.get(g['id'], {})
        us, them = (c.get(1), c.get(-1)) if mk == 'total' or sg == 1 else (c.get(-1), c.get(1))
        f = {}
        f['early'] = (g.get('wk') or 99) <= 3 if football else (day(g) - start[g['S']]).days < 21
        f['post'] = bool(g.get('po'))
        f['newTeam'] = prior[g['id']] < 5
        f['seasonEnd'] = not g.get('po') and (last[g['S']] - day(g)).days <= 14
        f['neutral'] = bool(g.get('neutral'))
        if mk == 'spread':
            f['fav'] = (e['line'] > 0) == (sg == 1) and e['line'] != 0
            f['home'] = sg == 1
            f['longLine'] = abs(e['line']) >= 14
            mus, mth = (us or {}).get('miss'), (them or {}).get('miss')
            f['modelHot'] = None if mus is None or mth is None else (mus - mth) < -0.25 * sd   # model too high on our side lately
            rus, rth = (us or {}).get('rest'), (them or {}).get('rest')
            if not football and rus is not None and rth is not None:
                f['restDown'] = rus <= 1 < rth
            if sport == 'cbb':
                f['injAgainst'] = (g.get('ij') or 0) * sg <= -GP.INJ_MIN
        else:
            f['over'] = sg == 1
            f['highTotal'] = e['line'] >= {'cfb': 60, 'nfl': 48, 'cbb': 150, 'nba': 235}[sport]
            tm = [x.get('tmiss') for x in (us, them) if x and x.get('tmiss') is not None]
            f['modelHot'] = None if len(tm) < 2 else sg * sum(tm) < -0.25 * sd       # model's total too far our way lately
            f['highUnder'] = f['highTotal'] and sg == -1
        if sport == 'cfb':
            f['fcs'] = bool(g.get('fcs'))
            f['optOuts'] = bool(g.get('opt'))
            if mk == 'spread':
                f['fcsDog'] = f['fcs'] and not f['fav']            # backing the FCS side
        src = g.get('Los' if mk == 'spread' else 'Tos')
        f['srcBackfill'] = src is not None and src != 'espn-draftkings'
        out.append({'S': g['S'], 'era': era(sport, g['S']), 'edge': e['edge'], 'sdEdge': e['edge'] / sd, 'clvRet': e['clvRet'],
                    'clv': e.get('clv'), 'profit': e['profit'], 'f': f, 'id': g['id'], 'game': f"{g['away']} at {g['home']}",
                    'date': str(g['date'])[:10], 'side': e['side'], 'line': e['line'], 'close': g['L'] if mk == 'spread' else g['T'],
                    'model': g['m'] if mk == 'spread' else g['tm']})
    return out


def ml_diffs(sport):
    """the moneyline board's Diff at the open: model win % minus the open spread's, the model's side on the moneyline at
    a fair open price with Novig's margin, judged by the close (no-vig closing moneyline, else the closing spread)"""
    rows = [r for r in GP.load_wf(sport) if r.get('res') is not None and r.get('Lo') is not None and r.get('m') is not None]
    out = []
    for g in rows:
        if C.bad_open_g(sport, 'spread', g) or not g['res']:
            continue
        ph = C.chances(sport, 'ml', 'home', None, g['m'])[0]
        qh = C.chances(sport, 'ml', 'home', None, g['Lo'])[0]
        side = 'home' if ph > qh else 'away'
        p, q = (ph, qh) if side == 'home' else (1 - ph, 1 - qh)
        if q < 0.25 or q > 0.75:                 # +-300 on the board: the picks' moneyline cap
            continue
        o = 1 / (q * NOVIG_OVER)
        mh, ma = GP.price(g.get('mlH')), GP.price(g.get('mlA'))
        cml = (mh, ma) if mh is not None and ma is not None and not (abs(g['L']) >= 3 and (mh < ma) != (g['L'] > 0)) else None
        w, _, l = C.chances(sport, 'ml', side, None, g['L'], cml)
        won = (g['res'] > 0) == (side == 'home')
        out.append({'S': g['S'], 'era': era(sport, g['S']), 'diff': 100 * (p - q), 'clvRet': w * (o - 1) - l,
                    'profit': (o - 1) if won else -1.0, 'flip': (ph > 0.5) != (qh > 0.5)})
    return out


def big_of(sport, mk, cap):
    return min(BIG, cap) if cap else BIG


def features(sport, mk, es, cap):
    """big-edge picks (and every pick 4+ off, for power): each feature's record with and without it, tuning and
    held-out; exclude = the picks with it lose to the close on tuning (t <= -1.65) and held out (mean < 0)"""
    b = [e for e in es if e['edge'] >= big_of(sport, mk, cap)]
    names = sorted({k for e in es for k in e['f']})
    out = {}
    for lo, lab0 in ((big_of(sport, mk, cap), 'big'), (4.0, 'gap4')):
        for k in names:
            row = {}
            for lab, sel in (('tune', ('tune',)), ('held', ('val', 'test'))):
                yes = [e for e in es if e['edge'] >= lo and e['era'] in sel and e['f'].get(k) is True]
                no = [e for e in es if e['edge'] >= lo and e['era'] in sel and e['f'].get(k) is False]
                row[lab] = {'with': rec(yes), 'without': rec(no)}
            tw, hw = row['tune']['with']['clvRet'], row['held']['with']['clvRet']
            row['exclude'] = bool((tw['t'] or 0) <= -GP.KEEP_T and (hw['mean'] or 0) < 0)
            out.setdefault(lab0, {})[k] = row
    return b, out


def cap_test(sport, mk, es, cap):
    """picks past the cap at the market's own bar (games_picks.fit_rules): on if the validation picks beat the close
    (clvRet > 0, t >= 1.65, n >= 30; tuning at t >= 2 where there is no validation season), vetoed if the test seasons lose"""
    past = [e for e in es if cap and e['edge'] > cap]
    by = {k: rec([e for e in past if e['era'] == k]) for k in ('tune', 'val', 'test')}
    v = by['val'] if GP.RULE_VAL[sport] else by['tune']
    need = GP.KEEP_T if GP.RULE_VAL[sport] else GP.TUNE_KEEP_T
    on = v['n'] >= 30 and (v['clvRet']['mean'] or 0) > 0 and (v['clvRet']['t'] or 0) >= need
    if on and (by['test']['n'] < 20 or (by['test']['clvRet']['mean'] or 0) <= 0):
        on = False
    # the curve past the cap: does the edge keep rising with the gap (the stake extrapolates it) or flatten?
    near = [e for e in es if cap and cap - 2 <= e['edge'] <= cap and e['era'] != 'tune']
    return {'cap': cap, 'capSd': 3, **by, 'on': on, 'nearCapHeld': rec(near), 'pastCapHeld': rec([e for e in past if e['era'] != 'tune'])}


def main():
    F = json.load(open(GP.FIT))['sports']
    res = {'asof': datetime.date.today().isoformat(), 'big': BIG, 'price': GP.BT_PRICE, 'sports': {}}
    for sport in GP.SPORTS:
        caps = F[sport]['cap']
        S = {'ml': {}, 'markets': {}}
        md = ml_diffs(sport)
        for lo, hi in DIFFS:
            S['ml'][f'{lo}-{hi}' if hi < 99 else f'{lo}+'] = {k: rec([e for e in md if lo <= e['diff'] < hi and e['era'] in sel])
                                                              for k, sel in (('tune', ('tune',)), ('held', ('val', 'test')))}
        S['ml']['10+'] = {k: rec([e for e in md if e['diff'] >= 10 and e['era'] in sel]) for k, sel in (('tune', ('tune',)), ('held', ('val', 'test')))}
        for mk in ('spread', 'total'):
            cap = caps[0] if mk == 'spread' else caps[1]
            es = picks(sport, mk)
            M = {'cap': cap, 'buckets': {}}
            for lo, hi in BUCKETS + [(BIG, 99)]:
                M['buckets'][f'{lo:g}-{hi:g}' if hi < 99 else f'{lo:g}+'] = {k: rec([e for e in es if lo <= e['edge'] < hi and e['era'] in sel])
                                                                             for k, sel in (('tune', ('tune',)), ('held', ('val', 'test')))}
            b, M['features'] = features(sport, mk, es, cap)
            M['bigAt'] = big_of(sport, mk, cap)
            M['bigN'] = {'tune': sum(1 for e in b if e['era'] == 'tune'), 'held': sum(1 for e in b if e['era'] in ('val', 'test'))}
            M['bigLosers'] = sorted([{k: e[k] for k in ('date', 'game', 'side', 'line', 'close', 'model', 'edge', 'clvRet', 'profit')} | {'f': [k for k, v in e['f'].items() if v]}
                                     for e in b if e['clvRet'] < 0 and e['era'] in ('val', 'test')], key=lambda x: x['clvRet'])[:40]
            M['capTest'] = cap_test(sport, mk, es, cap)
            S['markets'][mk] = M
        res['sports'][sport] = S
    with open(OUT, 'w') as f:
        json.dump(res, f, indent=1, default=lambda x: round(x, 4) if isinstance(x, float) else x)
    return res


if __name__ == '__main__':
    main()
