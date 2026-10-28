#!/usr/bin/env python3
"""The paper book: every pick on the Predictions page's picks tab, at the line, price and stake it was posted with,
graded as the picks are graded. Paper only, no real money.

Since Oct 28 2026 (Noah: "Paper book picks and picks we display under picks should be identical") the book reads the
picks logs (data/games_picks_<sport>.json from scripts/games_picks.py and scripts/tennis_picks.py) and nothing else:
one source, so the two can't differ. A pick withdrawn before its start (its rule switched off) leaves the log and the
book with it. A pick marked pass before its start (no longer clearing at the current price) was never a bet: listed,
but out of the record and the bankroll, as on the picks tab.

    python3 scripts/paper_book.py            # data/paper_book.json; the odds-snap and picks-refresh workflows run it
    python3 scripts/paper_book.py --test     # self-check

Stakes are the picks' Dengler Units (scripts/units.py) as posted; profit = units x the flat result the log graded.
DU compounds as on the picks tab: 1 DU = 1% of the bankroll when the pick was posted, so the bankroll (100 at the
registration date, scripts/paper_rules.json) multiplies through the graded picks in start order.
Gates (all must pass before real money is discussed): 400+ picks judged by the close, close value >= +1% at t >= 2 on
the effective count (slate correlation, one-way ANOVA), the close moved our way on 52%+, no single market carrying it,
and results within 2 standard errors of what the close implied.

The rule-based book it replaced (pre-registered rules, Oct 21-28 2026) is kept as scripts/data/paper_book_rules_2026-10.json.
"""
import datetime
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import clv as C

RULES = os.path.join(HERE, 'paper_rules.json')
OUT = os.path.join(ROOT, 'data', 'paper_book.json')
SPORTS = ('cfb', 'nfl', 'cbb', 'nba', 'tennis')
MKN = {'spread': 'spread', 'total': 'total', 'ml': 'moneyline'}


def iso(t):
    return datetime.datetime.fromisoformat(t.replace('Z', '+00:00'))


def slate(sport, kick):
    """one sport's US day (kick moved to US Eastern, about UTC-5)"""
    return f"{sport}:{(iso(kick) - datetime.timedelta(hours=5)).date().isoformat()}"


def mean_t(xs):
    n = len(xs)
    if n < 2:
        return (round(xs[0], 4) if xs else None), None, None
    m = sum(xs) / n
    s = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    return round(m, 4), (round(m / (s / math.sqrt(n)), 2) if s else None), s


def bet_text(g, mk, side, line, price):
    p = f"{price:+.0f}" if price is not None else ''
    if mk == 'total':
        return f"{side} {line:g} {p}".strip()
    team = g.get('h') if side == 'home' else g.get('a')
    if mk == 'ml' or line is None:
        return f"{team} ML {p}".strip()
    hl = -line if side == 'home' else line           # the bet side's own spread: home -3 is L +3
    return f"{team} {hl:+g} {p}".replace('+0 ', 'pk ').strip()


def bet_of(sport, e):
    """a picks-log entry as a paper bet: its posted line, price and DU; graded from the log"""
    mk = e['mk']
    units = float(e.get('units') or 0.0)
    g = {'h': e.get('home'), 'a': e.get('away')}
    b = {'rule': f"{sport}-{mk}", 'sport': sport, 'id': str(e['id']), 'k': e['kick'], 'slate': slate(sport, e['kick']),
         'h': e.get('home'), 'a': e.get('away'), 'mk': mk, 'side': e['side'], 'line': e.get('line'), 'price': e.get('price'),
         'bet': bet_text(g, mk, e['side'], e.get('line'), e.get('price')), 'placed': e.get('flagged'), 'stake': round(units, 3),
         'edge': e.get('edge'), 'ev': e.get('evDU') if e.get('evDU') is not None else e.get('ev'),
         'event': e.get('ev_'), 'pass': bool(e.get('pass'))}
    for k in ('clvRet', 'clv', 'beat', 'close', 'score'):
        if e.get(k) is not None:
            b[k] = e[k]
    if e.get('res') in ('w', 'l', 'p'):
        flat = 0.0 if e['res'] == 'p' else (round(C.dec(e['price']) - 1, 4) if e['res'] == 'w' else -1.0)
        b.update({'res': e['res'], 'ret': flat, 'profit': round(units * flat, 4)})
    return b


def record(bs):
    """close value first (n with a close), results second"""
    jc = [b for b in bs if b.get('clvRet') is not None]
    r, t, _ = mean_t([b['clvRet'] for b in jc])
    st = [b for b in bs if b.get('res') is not None]
    roi, roiT, _ = mean_t([b['ret'] for b in st])
    risk = sum(b.get('stake', 0) for b in st)
    beat = [b['beat'] for b in jc if b.get('beat') is not None]
    pts = [b['clv'] for b in jc if b.get('clv') is not None]
    return {'n': len(bs), 'clvN': len(jc), 'clvRet': r, 'clvT': t, 'clv': round(sum(pts) / len(pts), 2) if pts else None,
            'beat': round(sum(1 for x in beat if x > 0) / len(beat), 3) if beat else None,
            'settled': len(st), 'w': sum(1 for b in st if b['res'] == 'w'), 'l': sum(1 for b in st if b['res'] == 'l'),
            'p': sum(1 for b in st if b['res'] == 'p'), 'roi': roi, 'roiT': roiT,
            'profit': round(sum(b.get('profit', 0) for b in st), 2), 'risked': round(risk, 2),
            'yield': round(sum(b.get('profit', 0) for b in st) / risk, 4) if risk else None}


def icc(bs):
    """within-slate correlation of close value (one-way ANOVA estimator) and the effective count"""
    by = {}
    for b in bs:
        if b.get('clvRet') is not None:
            by.setdefault(b['slate'], []).append(b['clvRet'])
    N = sum(len(v) for v in by.values())
    k = len(by)
    rho = None
    if k >= 3 and N > k:
        mu = sum(sum(v) for v in by.values()) / N
        ssb = sum(len(v) * (sum(v) / len(v) - mu) ** 2 for v in by.values())
        ssw = sum(sum((x - sum(v) / len(v)) ** 2 for x in v) for v in by.values())
        msb, msw = ssb / (k - 1), ssw / (N - k)
        m0 = (N - sum(len(v) ** 2 for v in by.values()) / N) / (k - 1)
        den = msb + (m0 - 1) * msw
        rho = max(0.0, min(1.0, (msb - msw) / den)) if den > 0 else 0.0
    r = rho or 0.0
    neff = sum(len(v) / (1 + (len(v) - 1) * r) for v in by.values())
    return {'rho': None if rho is None else round(rho, 3), 'n': N, 'slates': k, 'nEff': round(neff, 1),
            'avgSlate': round(N / k, 2) if k else None}


def gates(bs, G):
    jc = [b for b in bs if b.get('clvRet') is not None]
    rec = record(bs)
    cor = icc(bs)
    m, _, s = mean_t([b['clvRet'] for b in jc])
    tEff = round(m / (s / math.sqrt(cor['nEff'])), 2) if m is not None and s and cor['nEff'] else None
    # no single market carrying it: the pool without the market that adds the most close value still beats the close
    ids = sorted({b['rule'] for b in jc})
    best = max(ids, key=lambda i: sum(b['clvRet'] for b in jc if b['rule'] == i), default=None)
    rm, rt, _ = mean_t([b['clvRet'] for b in jc if b['rule'] != best])
    st = [b for b in bs if b.get('res') is not None and b.get('clvRet') is not None]
    roi, _, rs = mean_t([b['ret'] for b in st])
    cm = mean_t([b['clvRet'] for b in st])[0]
    se = (rs / math.sqrt(len(st))) if rs and st else None
    out = [
        {'gate': f"{G['minN']}+ picks judged by the close", 'value': rec['clvN'], 'pass': rec['clvN'] >= G['minN']},
        {'gate': f"close value {G['clvRet'] * 100:+.0f}%+ at t {G['t']:g}+ (effective n)", 'value': None if m is None else f"{m * 100:+.1f}% t {tEff}",
         'pass': m is not None and tEff is not None and m >= G['clvRet'] and tEff >= G['t']},
        {'gate': f"close moved our way {G['beat'] * 100:.0f}%+", 'value': None if rec['beat'] is None else f"{rec['beat'] * 100:.0f}%",
         'pass': rec['beat'] is not None and rec['beat'] >= G['beat']},
        {'gate': 'no single market carrying it', 'value': None if rm is None else f"without {best}: {rm * 100:+.1f}%",
         'pass': rm is not None and rm > 0 and (rt or 0) >= 1},
        {'gate': 'results within 2 SE of the close', 'value': None if roi is None or se is None else f"ROI {roi * 100:+.1f}% vs {cm * 100:+.1f}% (SE {se * 100:.1f})",
         'pass': roi is not None and se is not None and abs(roi - cm) <= G['se'] * se},
    ]
    return out, cor, tEff


def build(now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    stamp = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    P = json.load(open(RULES))
    try:
        old = json.load(open(OUT))
    except (OSError, ValueError):
        old = {}
    ledger = []
    for s in SPORTS:
        try:
            log = json.load(open(os.path.join(ROOT, 'data', f'games_picks_{s}.json'))).get('log', [])
        except (OSError, ValueError):
            continue
        ledger += [bet_of(s, e) for e in log if (e.get('flagged') or '') >= P['registered']]
    ledger.sort(key=lambda b: (b['k'], b['sport'], b['id'], b['mk']))
    bets = [b for b in ledger if not b['pass']]
    bank, peak, path = P['bankroll'], P['bankroll'], []
    for b in [b for b in bets if b.get('res') is not None]:
        bank *= 1 + b['stake'] / 100 * b['ret']
        peak = max(peak, bank)
        path.append(round(bank, 2))
    gate_rows, cor, tEff = gates(bets, P['gates'])
    markets = []
    for i in sorted({b['rule'] for b in bets}, key=lambda i: (SPORTS.index(i.split('-')[0]), i)):
        s, mk = i.split('-')
        markets.append({'id': i, 'label': f"{s.upper() if s != 'tennis' else 'Tennis'} {MKN[mk]}", 'sport': s, 'mk': mk,
                        **record([b for b in bets if b['rule'] == i])})
    out = {'asof': stamp, 'registered': P['registered'], 'source': 'picks',
           'bankroll': {'start': P['bankroll'], 'now': round(bank, 2), 'peak': round(peak, 2),
                        'drawdown': round((peak - bank) / peak, 4) if peak else 0,
                        'open': round(sum(b['stake'] for b in bets if b.get('res') is None), 2), 'path': path[-400:]},
           'record': record(bets), 'tEff': tEff, 'corr': cor, 'gates': gate_rows,
           'gatesPass': all(x['pass'] for x in gate_rows), 'markets': markets,
           'open': [b for b in ledger if b.get('res') is None],
           'recent': sorted([b for b in ledger if b.get('res') is not None], key=lambda b: b['k'], reverse=True)[:60],
           'ledger': ledger}
    if {k: v for k, v in old.items() if k != 'asof'} == json.loads(json.dumps({k: v for k, v in out.items() if k != 'asof'})):
        return print('paper book: no change')
    with open(OUT, 'w') as f:
        json.dump(out, f, indent=1, allow_nan=False)
    print(f"paper book: {len(ledger)} picks ({len(out['open'])} open), bankroll {bank:.2f} DU, gates {'pass' if out['gatesPass'] else 'not yet'}")


def test():
    assert bet_text({'h': 'ORL', 'a': 'ATL'}, 'spread', 'home', 2.5, -108) == 'ORL -2.5 -108'
    assert bet_text({'h': 'ORL', 'a': 'ATL'}, 'spread', 'away', 2.5, -112) == 'ATL +2.5 -112'
    assert bet_text({'h': 'ORL', 'a': 'ATL'}, 'ml', 'away', None, 150) == 'ATL ML +150'
    e = {'id': 1, 'kick': '2026-10-28T23:00:00Z', 'home': 'DET', 'away': 'CHA', 'mk': 'total', 'side': 'over', 'line': 215.5,
         'price': -110, 'units': 2.0, 'flagged': '2026-10-28T12:00:00Z', 'res': 'w', 'clvRet': .02}
    b = bet_of('nba', e)
    assert b['res'] == 'w' and abs(b['profit'] - 2 * 100 / 110) < 1e-3 and b['stake'] == 2.0
    assert bet_of('nba', {**e, 'res': 'p'})['profit'] == 0 and bet_of('nba', {**e, 'res': None}).get('res') is None
    c = icc([{'slate': s, 'clvRet': v} for s, v in (('a', .1), ('a', .1), ('b', -.1), ('b', -.1), ('c', 0), ('c', 0.01))])
    assert c['rho'] > 0.8 and c['nEff'] < 4, c
    print('paper book: ok')


if __name__ == '__main__':
    if sys.argv[1:] == ['--test']:
        test()
    else:
        build()
