#!/usr/bin/env python3
"""Tennis picks on the Predictions page (Noah, Oct 27 2026: "Why aren't counter strike and tennis on the game table /
picks page now that we're using Novig?"). The same pick rule as every other sport (scripts/games_picks.py, pick-rules):
the model's side when it sits X+ off the market, X set on the tuning season by closing line value, on only where the
picks beat the close held out.

    python3 scripts/tennis_picks.py --fit    # needs the tennis history (scripts/tennis_data.py): data/tennis_picks_fit.json
    python3 scripts/tennis_picks.py          # live: data/tennis.json's model chances at Novig's current moneylines ->
                                             # data/games_picks_tennis.json (same shape as games_picks_<sport>.json)

The backtest. The weekly feed (scripts/tennis_data.py, 2025+) carries each tour-level main-draw match's no-vig OPEN and
CLOSE. A pick is the model's side at the open when model minus open is X+ points of chance and the side is no longer
than -300/+300; it is judged by the close (CLV-implied return: the close's chance x the decimal price at the open plus
COST, Novig's half spread, minus 1) and by results. Tune 2025, held out 2026. The model adds nothing to the close (its
logistic weight beside the close is ~0, data/tennis_fit.json), but it does say where the open is going: the open-to-close
move runs k logits per logit of model-minus-open (tuning k), which is the edge the rule bets.

Live, the price is Novig's ask when the picks run (every odds snapshot), which sits somewhere between the open and the
close, so the backtest's close value is an upper bound: the calibrated chance moves only LEAK x k of the way from Novig's
no-vig chance toward the model's. Stakes are Dengler Units, 1x Kelly on that calibrated chance at the ask, capped at CAP
until live picks grade (a new market, like the NBA holds in scripts/units.py). Picks are graded from tennis.json's results
and judged at Novig's last pregame price in the archive (scripts/data/odds_novig/tennis-*.jsonl, scripts/novig.py).
"""
import datetime
import glob
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

FIT = os.path.join(ROOT, 'data', 'tennis_picks_fit.json')
OUT = os.path.join(ROOT, 'data', 'games_picks_tennis.json')
TEN = os.path.join(ROOT, 'data', 'tennis.json')
ARCH = os.path.join(HERE, 'data', 'odds_novig')
TOUR_LV = ('G', 'M', 'A', 'F', 'O')
COST = 0.0075            # half of Novig's median tennis moneyline spread (1.5%, Oct 27 2026)
MLCAP = 0.25             # the side's chance at the price: -300 to +300, as every sport's moneyline picks
GAPMAX = 0.35            # a gap past this is a bad line (a withdrawal, a wrong player), not a pick
XS = (0.04, 0.06, 0.08, 0.10, 0.12, 0.15, 0.18)
LEAK = 0.5               # the share of the open-to-close edge still there at the live price
CAP = 2.0                # DU a pick, held until live picks grade
TUNE, HELD = 2025, 2026


def sig(z):
    return 1 / (1 + math.exp(-z))


def lg(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def dec(o):
    o = float(o)
    return 1 + (o / 100 if o > 0 else 100 / -o)


def american(p):
    p = min(max(float(p), .01), .99)
    return round(-100 * p / (1 - p)) if p >= .5 else round(100 * (1 - p) / p)


def tstat(xs):
    n = len(xs)
    if n < 2:
        return None
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    return round(m / (sd / math.sqrt(n)), 2) if sd else None


# ---------------------------------------------------------------- backtest

def bets(D, x):
    """D rows (model, open, close, won by the first side) -> [(clv return, result return, gap)] for gaps X+"""
    out = []
    for pm, po, pc, y in D:
        e = pm - po
        if abs(e) < x or abs(e) > GAPMAX:
            continue
        so, sc, won = (po, pc, y) if e > 0 else (1 - po, 1 - pc, 1 - y)
        if not MLCAP <= so <= 1 - MLCAP:
            continue
        ask = so + COST
        out.append((sc / ask - 1, won / ask - 1, abs(e)))
    return out


def block(b):
    c = [x[0] for x in b]
    r = [x[1] for x in b]
    return {'n': len(b), 'clvRet': round(sum(c) / len(c), 4) if c else None, 'clvT': tstat(c),
            'roi': round(sum(r) / len(r), 4) if r else None, 'roiT': tstat(r),
            'w': sum(1 for x in r if x > 0), 'l': sum(1 for x in r if x <= 0)}


def growth(D, x, k):
    """log growth at the close of the picks X+ at the live stakes (1x Kelly on the open's no-vig chance moved LEAK x k
    toward the model, at the open's ask, capped at CAP)"""
    g = 0.0
    for pm, po, pc, y in D:
        e = pm - po
        if abs(e) < x or abs(e) > GAPMAX:
            continue
        so, sc, sm = (po, pc, pm) if e > 0 else (1 - po, 1 - pc, 1 - pm)
        if not MLCAP <= so <= 1 - MLCAP:
            continue
        ask = so + COST
        b = 1 / ask - 1
        cal = sig(lg(so) + LEAK * k * (lg(sm) - lg(so)))
        ev = cal * (b + 1) - 1
        if ev <= 0:
            continue
        f = min(CAP / 100, ev / b)
        g += sc * math.log(1 + f * b) + (1 - sc) * math.log(1 - f)
    return g


def fit():
    import tennis_model as M
    import tennis_data as T
    rows, _, _ = T.load()
    P = dict(M.DEFAULT, **json.load(open(M.FIT))['params'])
    # walk-forward model chances (each season's blend weights from the M.WIN seasons before it), so 2025 and 2026 are
    # both out of sample for the model; then the matches with an open and a close
    _, rec = M.run(rows, P, score=lambda r: M.scored(r, TUNE - M.WIN, 2100))
    pw = M.wf_probs(rec, P)
    D = {}
    i = 0
    for x, pm in zip(rec, pw):
        r = x[0]
        if not (r[0] // 10000 >= TUNE and r[14] and r[15] and 0 < r[14] < 1 and 0 < r[15] < 1):
            continue
        po, pc = r[15], r[14]                             # the winner's side
        if i % 2:                                         # half the rows from the loser's side, so 'won' is not always 1
            pm, po, pc, y = 1 - pm, 1 - po, 1 - pc, 0
        else:
            y = 1
        i += 1
        D.setdefault(r[0] // 10000, []).append((pm, po, pc, y))
    tune, held = D.get(TUNE, []), [d for y, v in D.items() if y >= HELD for d in v]
    # k: logits of open-to-close move per logit of model minus open, tuning season
    X = [lg(d[0]) - lg(d[1]) for d in tune]
    Y = [lg(d[2]) - lg(d[1]) for d in tune]
    k = sum(a * b for a, b in zip(X, Y)) / sum(a * a for a in X)
    grid = [{'x': x, **block(bets(tune, x)), 'growth': round(growth(tune, x, k) * 100, 2)} for x in XS]
    # X (Oct 27 2026): the cut with the most Kelly growth at the close on the tuning season, at the live stakes (1x Kelly
    # on the LEAK-calibrated chance at the ask), not the best average pick: on 2026 held out X 4 grew 80.6% at the close
    # (realized 124%) against X 15's 38.8% (10.6%), and still led (8.8% vs 5.2%) if the live edge is half the backtest's;
    # the Kelly stake itself drops the picks with no calibrated edge at the ask
    ok = [g for g in grid if g['n'] >= 40 and g['clvRet'] > 0 and (g['clvT'] or 0) >= 1]
    x = max(ok, key=lambda g: (g['growth'], -g['x']))['x'] if ok else None
    h = block(bets(held, x)) if x else None
    on = bool(h and h['n'] >= 30 and h['clvRet'] > 0 and (h['clvT'] or 0) >= 1.65)
    out = {'fit_at': datetime.date.today().isoformat(), 'tune': [TUNE], 'held': sorted(y for y in D if y >= HELD),
           'nTune': len(tune), 'nHeld': len(held), 'cost': COST, 'mlCap': MLCAP, 'gapMax': GAPMAX,
           'k': round(k, 3), 'leak': LEAK, 'cap': CAP, 'x': x, 'on': on, 'tuneAtX': next((g for g in grid if g['x'] == x), None),
           'heldAtX': h, 'grid': grid, 'heldGrid': [{'x': g, **block(bets(held, g))} for g in XS],
           'note': 'tour-level main draws, bet at the feed\'s no-vig open plus Novig\'s half spread, judged by its no-vig close; '
                   'the live price comes later than the open, so the close value is an upper bound'}
    json.dump(out, open(FIT, 'w'), indent=1)
    print(json.dumps({k_: v for k_, v in out.items() if k_ not in ('grid', 'heldGrid')}, indent=1))


# ---------------------------------------------------------------- live

def short(n):
    return n.split(' ')[-1] if n else n


def closes():
    """{novig event id: last archived (t, start, no-vig chance of the side after '@')} before each start"""
    out = {}
    for fn in sorted(glob.glob(os.path.join(ARCH, 'tennis-*.jsonl'))):
        for line in open(fn):
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get('p') is None or r['t'] >= r['k']:
                continue
            out[r['nid']] = r
    return out


def stake(pc, o):
    """DU: 1x Kelly on the calibrated chance pc at American price o, quarter units, 0.25 to CAP"""
    b = dec(o) - 1
    ev = pc * (b + 1) - 1
    if ev <= 0:
        return 0.0, ev
    return min(CAP, max(0.25, round(ev / b * 100 * 4) / 4)), ev


def live():
    import novig
    F = json.load(open(FIT))
    X, k = F['x'], F['k'] * LEAK
    on = F['on'] and X
    T = json.load(open(TEN))
    try:
        nvg = novig.h2h('tennis')
    except Exception as ex:  # noqa: BLE001
        print('novig tennis failed:', ex)
        nvg = []
    now = datetime.datetime.now(datetime.timezone.utc)
    stamp = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    try:
        old = json.load(open(OUT))
    except (OSError, ValueError):
        old = {}
    log = {str(e['id']): e for e in old.get('log', [])}
    games, board = {}, []
    for g in T.get('matches', []):
        if g.get('state') != 'pre' or g['tip'] <= stamp:
            continue
        a, b = g['a'], g['b']
        nv = novig.h2h_price(nvg, a['n'], b['n'], lg=g['tour'].upper()) if nvg else None
        if not nv:
            continue
        ng, _ = novig.h2h_find(nvg, a['n'], b['n'], lg=g['tour'].upper())
        pm, pn = float(g['p']), nv['p']                   # first player's chance: model, Novig no-vig
        e = pm - pn
        side = 'away' if e > 0 else 'home'                 # away = the first player (a), home = the second (b)
        sm, sn = (pm, pn) if e > 0 else (1 - pm, 1 - pn)
        o = nv['o'][0] if e > 0 else nv['o'][1]
        pc = sig(lg(sn) + k * (lg(sm) - lg(sn)))
        u, ev = stake(pc, o)
        row = {'id': g['id'], 'nid': ng['nid'] if ng else None, 'sport': 'tennis', 'tour': g['tour'], 'ev_': g['ev'],
               'kick': g['tip'], 'home': short(b['n']), 'away': short(a['n']), 'homeN': b['n'], 'awayN': a['n'],
               'mk': 'ml', 'side': side, 'line': None, 'price': o, 'edge': round(abs(e) * 100, 1), 'x': round(X * 100) if X else None,
               'm': round(sm, 4), 'mkt': round(sn, 4), 'p': round(pc, 4), 'ev': round(ev, 4), 'pDU': round(pc, 4), 'evDU': round(ev, 4)}
        tour_lv = g.get('lv') in TOUR_LV and not g.get('rd', '').startswith('Q')
        long_ = not MLCAP <= sn + COST <= 1 - MLCAP
        why = None
        if not on:
            why = 'tennis rule off'
        elif not tour_lv:
            why = 'not a tour-level main draw (untested)'
        elif abs(e) > GAPMAX:
            why = f'gap past {round(GAPMAX * 100)} (bad line)'
        elif long_:
            why = 'price past -300/+300'
        elif abs(e) < X:
            why = f'edge under {round(X * 100)}'
        elif u <= 0:
            why = 'no value at the ask'
        state = 'pick' if why is None else ('off' if not on else 'under')
        games[str(g['id'])] = {'mk': 'ml', 'side': side, 'line': None, 'price': o, 'edge': row['edge'], 'ev': row['ev'],
                               'units': u if state == 'pick' else 0.0, 'home': row['home'], 'away': row['away'], 'state': state}
        prev = log.get(str(g['id']))
        if prev is not None and prev.get('res') is None:
            prev['kick'] = g['tip']                        # ESPN moves order-of-play times as the draw fills
        if state == 'pick':
            if prev is None:
                log[str(g['id'])] = {**row, 'units': u, 'flagged': stamp}
            else:
                prev['now'] = {'mk': 'ml', 'side': side, 'line': None, 'price': o, 'units': u} if side == prev['side'] else None
                prev.pop('pass', None)
        else:
            if prev is not None and prev.get('res') is None:
                same = side == prev['side']
                prev['now'] = None
                prev['pass'] = True if not (same and abs(e) >= (X or 1)) else prev.get('pass')
            elif tour_lv and on and abs(e) >= X / 2:
                board.append({**row, 'why': why})
    # grade from tennis.json's results, judge at Novig's last pregame price
    res = {str(r['id']): r for r in T.get('results', [])}
    cl = closes()
    for e in log.values():
        if e.get('res') is not None:
            continue
        r = res.get(str(e['id']))
        if r:
            det = (r.get('detail') or '').lower()
            aw, hw = r['a'].get('won'), r['b'].get('won')
            if 'ret' in det or 'w/o' in det or 'walkover' in det or 'def' in det or aw == hw:
                e['res'], e['profit'] = 'void', 0.0
            else:
                won = aw if e['side'] == 'away' else hw
                e['res'] = 'w' if won else 'l'
                e['profit'] = round(dec(e['price']) - 1, 4) if won else -1.0
            e['score'] = r.get('sc')
        c = cl.get(e.get('nid'))
        if c and e.get('close') is None and e['kick'] <= stamp:
            pcl = 1 - c['p'] if e['side'] == 'away' else c['p']
            e['close'] = round(pcl, 4)
            e['clvRet'] = round(pcl * dec(e['price']) - 1, 4)
            e['clv'] = round((pcl - e['mkt']) * 100, 1)
            e['beat'] = 1 if pcl > e['mkt'] + .005 else (-1 if pcl < e['mkt'] - .005 else 0)
    L = sorted(log.values(), key=lambda e: e['kick'])
    done = [e for e in L if e.get('res') in ('w', 'l') and not e.get('pass')]
    rec = {'n': len(done)}
    if done:
        pr = [e['profit'] for e in done]
        risked = sum(e['units'] for e in done)
        su = sum(e['units'] * e['profit'] for e in done)
        bank = 1.0
        for e in done:
            bank *= 1 + e['units'] / 100 * e['profit']
        rec = {'n': len(done), 'w': sum(1 for x in pr if x > 0), 'l': sum(1 for x in pr if x < 0), 'units': round(sum(pr), 1),
               'roi': round(sum(pr) / len(pr), 3), 't': tstat(pr),
               'sized': {'units': round(su, 1), 'risked': round(risked, 1), 'roi': round(su / risked, 3) if risked else None, 'bank': round(bank, 4)}}
    cv = [e['clvRet'] for e in L if e.get('clvRet') is not None and not e.get('pass')]
    rec.update({'clvN': len(cv), 'clvRet': round(sum(cv) / len(cv), 4) if cv else None, 'clvT': tstat(cv)})
    cut = (now - datetime.timedelta(hours=4)).strftime('%Y-%m-%dT%H:%M:%SZ')
    picks = [e for e in L if e.get('res') is None and e['kick'] > cut]
    recent = [e for e in L if e.get('res') is not None][-12:]
    out = {'sport': 'tennis', 'name': 'Tennis', 'asof': stamp, 'rule': {'on': bool(on), 'x': F['x'], 'k': F['k'], 'leak': LEAK, 'cap': CAP,
           'held': F.get('heldAtX')}, 'picks': picks, 'withdrawn': [], 'board': sorted(board, key=lambda r: -r['edge'])[:12],
           'games': games, 'record': rec, 'recent': recent, 'log': L[-400:]}
    json.dump(out, open(OUT, 'w'), separators=(',', ':'), allow_nan=False)
    print(f"tennis picks: {len(picks)} open, {len(games)} priced at Novig, rule {'on X ' + str(X) if on else 'off'}, record {rec}")


if __name__ == '__main__':
    fit() if '--fit' in sys.argv else live()
