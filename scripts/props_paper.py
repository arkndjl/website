#!/usr/bin/env python3
"""The NBA props paper book (Noah, Oct 21 2026): paper bets on player props (points, rebounds, assists,
PRA) from our projections (scripts/nba_players.py), judged by the close. Paper only. ESPN keeps no prop history, so
the rule below could not be backtested: it is pre-registered here, and props become picks only once its paper bets
beat the close.

    python3 scripts/props_paper.py     # the odds-snap workflow runs it after scripts/props_snap.py

Reads the snapshots in scripts/data/props/ and writes data/props_paper.json. Prices are DraftKings' (through ESPN)
until Oct 27 2026, then Novig's main rung wherever Novig lists the prop (bk on the entry and the close says which).

Rule (pre-registered 2026-10-21; changing RULE restarts its record):
    entry   a prop's first snapshot that carries our projection (the line and our number as they stood then)
    side    over or under, whichever our negative binomial chance beats the no-vig price by GAP or more
    filters he's not on the injury report as questionable or worse (our P(plays) >= .9), price between -150 and +150,
            one bet per player a game (his largest gap)
    stake   quarter Kelly on a chance shrunk toward the market (SHRINK of our gap: the market knows the role news we
            don't), 1 DU = 1% of the bankroll, capped at 1 DU
Judged first by the close (closing line value): the bet's return at the close's no-vig chance, moved along our
distribution when the line moved. Then by results (ESPN box scores; a player who doesn't play voids, as DK does).
Gate to picks: 200+ graded bets and closing line value t >= 2 with games as clusters (a player's props and teammates'
props in one game move together).
"""
import datetime
import hashlib
import json
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nba_players as NP  # noqa: E402

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'props_paper.json')
RULE = {'name': 'nba-prop-8', 'stats': ['pts', 'reb', 'ast', 'pra'], 'gap': 0.08, 'minPlay': 0.9, 'price': 150,
        'shrink': 0.25, 'kelly': 0.25, 'cap': 1.0, 'gate': {'n': 200, 't': 2.0}, 'registered': '2026-10-21'}
RULE_ID = hashlib.sha1(json.dumps(RULE, sort_keys=True).encode()).hexdigest()[:10]
# changes to the projections the rule reads (not to the rule, so its record carries on; judge before/after apart if needed)
RECAL_FROM = '2026-10-21T22:30:00Z'      # snapshots before this keep the plain negative binomial chance they were bet on
MODELS = [{'from': '2026-10-21T20:30:00Z', 'note': 'game script (blowout x role and favorite margin in minutes, points, '
           'rebounds) and P(plays) calibrated by role: bench players listed at .94 now ~.43-.82, so fewer pass the .9 filter'},
          {'from': RECAL_FROM, 'note': 'over chance recalibrated for each stat\'s skew (nba_players.p_over): the '
           'negative binomial put too many points and PRA under the line and too few assists; held out it moves a '
           'points over at the projection ~1.5 pts up and an assists over ~2.5 pts down'}]


def dec(o):
    return 1 + (o / 100 if o > 0 else 100 / -o)


def imp(o):
    return 100 / (o + 100) if o > 0 else -o / (-o + 100)


def nv(oO, oU):
    a, b = imp(oO), imp(oU)
    return a / (a + b)


def load():
    rows = defaultdict(list)
    if not os.path.isdir(NP.PROPS):
        return rows
    for fn in sorted(os.listdir(NP.PROPS)):
        if not (fn.startswith('nba-') and fn.endswith('.jsonl')):
            continue
        for ln in open(os.path.join(NP.PROPS, fn)):
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            r['t'], r['k'] = sec(r['t']), sec(r['k'])
            rows[(r['id'], r['a'], r['s'])].append(r)
    return rows


def sec(ts):
    """ISO time with seconds (ESPN and the snapshots drop them; Hugo needs them)"""
    return ts[:-1] + ':00Z' if len(ts) == 17 else ts


def entry(snaps):
    """the bet a prop's first snapshot with our number makes, or None"""
    for r in snaps:
        if r.get('m') is None or not r.get('sd') or r.get('oO') is None or r.get('oU') is None:
            continue
        if r['t'] >= r['k']:
            return None
        if (r.get('pr') or 0) < RULE['minPlay']:
            return None
        po = NP.p_over(r['s'], r['m'], r['sd'] ** 2, r['L'], recal={} if r['t'] < RECAL_FROM else None)
        q = nv(r['oO'], r['oU'])
        best = None
        for side, p, mkt, o in (('o', po, q, r['oO']), ('u', 1 - po, 1 - q, r['oU'])):
            if p - mkt >= RULE['gap'] and abs(o) <= RULE['price']:
                ps = mkt + RULE['shrink'] * (p - mkt)
                b = dec(o) - 1
                k = max(0.0, (ps * b - (1 - ps)) / b) * RULE['kelly'] * 100
                if k > 0:
                    best = {'side': side, 'p': round(p, 3), 'mkt': round(mkt, 3), 'gap': round(p - mkt, 3), 'o': o,
                            'u': round(min(RULE['cap'], k), 2)}
        if best:
            best.update({'t': r['t'], 'L': r['L'], 'm': r['m'], 'sd': r['sd'], 'bk': r.get('src', 'dk')})
        return best
    return None


def close_of(snaps):
    pre = [r for r in snaps if r['t'] < r['k']]
    return pre[-1] if pre else None


def main():
    snaps = load()
    now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    names = {}
    bets = []
    for (gid, a, s), lst in snaps.items():
        if s not in RULE['stats']:
            continue
        for r in lst:
            if r.get('n'):
                names[a] = r['n']
        b = entry(lst)
        if not b:
            continue
        c = close_of(lst)
        b.update({'id': gid, 'a': a, 's': s, 'k': lst[0]['k'], 'n': names.get(a)})
        # the close is final once the game tips (before that the file stays put, so a snapshot alone doesn't rebuild the site)
        # (a prop that never moved after the entry closes at the entry's own price)
        if c and c.get('oO') is not None and c.get('oU') is not None and c['t'] >= b['t'] and b['k'] <= now:
            q = nv(c['oO'], c['oU'])
            if c['L'] != b['L']:
                # move the close's chance from its line to ours along our distribution
                v = b['sd'] ** 2
                rc = {} if b['t'] < RECAL_FROM else None
                q += NP.p_over(b['s'], b['m'], v, b['L'], rc) - NP.p_over(b['s'], b['m'], v, c['L'], rc)
                q = min(max(q, 0.01), 0.99)
            pc = q if b['side'] == 'o' else 1 - q
            b['close'] = {'L': c['L'], 'oO': c['oO'], 'oU': c['oU'], 'p': round(pc, 3), 'bk': c.get('src', 'dk')}
            b['clv'] = round(pc * dec(b['o']) - 1, 4)
        bets.append(b)
    # one bet per player a game: his largest gap
    keep = {}
    for b in bets:
        k = (b['id'], b['a'])
        if k not in keep or b['gap'] > keep[k]['gap']:
            keep[k] = b
    bets = sorted(keep.values(), key=lambda b: (b['k'], -b['gap']))
    # results from ESPN box scores (a player who didn't play: void)
    boxes = {}
    for b in bets:
        if b['k'] > now or 'res' in b:
            continue
        if b['id'] not in boxes:
            boxes[b['id']] = NP.pbox(b['id'], final=True)      # graded only once the game is final
        bx = boxes[b['id']]
        if not bx:
            continue
        row = next((r for t in bx for r in bx[t] if r[0] == b['a']), None)
        if row is None:
            b['res'] = 'void'
            continue
        val = {'pts': row[5], 'reb': row[6], 'ast': row[7]}
        val['pra'] = val['pts'] + val['reb'] + val['ast']
        x = val[b['s']]
        b['x'] = x
        if x == b['L']:
            b['res'], b['ret'] = 'push', 0.0
        else:
            win = x > b['L'] if b['side'] == 'o' else x < b['L']
            b['res'] = 'w' if win else 'l'
            b['ret'] = round(dec(b['o']) - 1 if win else -1.0, 4)
    graded = [b for b in bets if b.get('res') in ('w', 'l', 'push')]
    cl = [b for b in bets if 'clv' in b]

    def clustered(xs):
        """mean and t with games as clusters"""
        if len(xs) < 2:
            return None, None
        by = defaultdict(list)
        for gid, v in xs:
            by[gid].append(v)
        n = len(xs)
        mu = sum(v for _, v in xs) / n
        var = sum(sum(v - mu for v in vs) ** 2 for vs in by.values()) / n ** 2
        return mu, (mu / math.sqrt(var) if var > 0 and len(by) > 1 else None)

    cm, ct = clustered([(b['id'], b['clv']) for b in cl])
    rm, rt = clustered([(b['id'], b['ret']) for b in graded])
    units = sum(b['u'] * b['ret'] for b in graded)
    staked = sum(b['u'] for b in graded)
    gate = RULE['gate']
    res = {'rule': RULE, 'ruleId': RULE_ID, 'models': MODELS, 'asof': now,
           'record': {'n': len(bets), 'graded': len(graded), 'w': sum(b['res'] == 'w' for b in graded),
                      'l': sum(b['res'] == 'l' for b in graded), 'push': sum(b['res'] == 'push' for b in graded),
                      'clvN': len(cl), 'clvRet': None if cm is None else round(cm, 4), 'clvT': None if ct is None else round(ct, 2),
                      'beat': None if not cl else round(sum(b['clv'] > 0 for b in cl) / len(cl), 3),
                      'roi': None if rm is None else round(rm, 4), 'roiT': None if rt is None else round(rt, 2),
                      'units': round(units, 2), 'staked': round(staked, 2)},
           'live': bool(len(graded) >= gate['n'] and ct is not None and ct >= gate['t'] and cm > 0),
           'bets': bets[-400:]}
    try:
        old = json.load(open(OUT))
        if {k: v for k, v in old.items() if k != 'asof'} == {k: v for k, v in res.items() if k != 'asof'}:
            return print('props paper: no change')
    except (OSError, ValueError):
        pass
    with open(OUT, 'w') as f:
        json.dump(res, f, separators=(',', ':'))
    print('props paper:', len(bets), 'bets,', len(graded), 'graded,', len(cl), 'with a close')


if __name__ == '__main__':
    main()
