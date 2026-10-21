#!/usr/bin/env python3
"""Closing line value: how picks are judged on the site (roadmap item 2, Oct 21 2026).

A pick's result is mostly noise: ROI on a -110 bet has a spread of about 0.95 units a bet, so a 2% edge takes about
9,000 bets to show at t 2. The closing line is the market's best estimate of the true chance, and the move from the
line a pick was taken at to the close has a spread of about 1.5-2 points, so the same edge shows in tens of bets. Every
pick is judged first by the close it beat, turned into a chance and an expected return; win-loss ROI is second.

    python3 scripts/clv.py --fit     # data/clv_fit.json: the margin and total distributions around the close (per
                                     # sport, key numbers for football), and the backtest: every pick rule bet at the
                                     # OPEN and judged by the CLOSE, where the history has both lines
    python3 scripts/clv.py --test    # self-check of the conversions

The conversion (all lines in the home-margin convention: L = the home side's expected margin, home -7 is L = +7).
The final margin around a close C is a discretized normal, sd the sport's miss against the close, each margin size
weighted by its frequency over what that normal expects (football's 3, 7, 10; the same key table cfb_picks.mjs uses,
KA = 10 games of prior weight toward 1). Then, for a bet on the home side at X:

    P(win | close C) = P(margin > X),  P(push) = P(margin = X),  P(loss) = P(margin < X)
    CLV-implied return = P(win) x (decimal price - 1) - P(loss)

Totals the same, around the closing total, normal without key weights. A moneyline is judged by the close's no-vig
chance when the closing moneylines are known, else by P(margin > 0) around the closing spread. CLV-implied return is
what the bet was worth if the close is the true price; 0% means the pick beat the vig exactly, -4.5% at -110 means the
line never moved.

Live (stdlib only, imported by games_picks.py and the four sport pick scripts): chances(), ret(), summary().
"""
import datetime
import gzip
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIT = os.path.join(ROOT, 'data', 'clv_fit.json')
WF = os.path.join(HERE, 'data', 'games_wf')
SPORTS = ('cfb', 'nfl', 'cbb', 'nba')
FOOTBALL = ('cfb', 'nfl')
KMAX, KA = 70, 10
TMAX = 320
# fallbacks until --fit has run: the miss against the close, points
SD0 = {'cfb': (15.5, 15.0), 'nfl': (13.3, 13.5), 'cbb': (10.6, 15.5), 'nba': (12.3, 18.5)}


def dec(o):
    return 1 + o / 100 if o > 0 else 1 + 100 / -o


def novig(a, b):
    pa, pb = 1 / dec(a), 1 / dec(b)
    return pa / (pa + pb)


def phi(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


_F = None


def params(sport):
    global _F
    if _F is None:
        try:
            _F = json.load(open(FIT))
        except (OSError, ValueError):
            _F = {}
    p = (_F.get('sports') or {}).get(sport) or {}
    return p.get('sd') or SD0[sport][0], p.get('sdT') or SD0[sport][1], p.get('key')


def pmf(center, sd, key=None, lo=-KMAX, hi=KMAX):
    """{integer: probability} around center; key[|k|] weights each margin size (index 0 = a tie)"""
    out = {}
    a, b = int(math.floor(center - 6 * sd)), int(math.ceil(center + 6 * sd))
    for k in range(max(lo, a), min(hi, b) + 1):
        p = phi((k + 0.5 - center) / sd) - phi((k - 0.5 - center) / sd)
        if key is not None:
            p *= key[min(abs(k), len(key) - 1)]
        out[k] = p
    t = sum(out.values()) or 1.0
    return {k: v / t for k, v in out.items()}


def split(d, x):
    w = sum(p for k, p in d.items() if k > x)
    push = sum(p for k, p in d.items() if k == x)
    return w, push, max(0.0, 1 - w - push)


def chances(sport, mk, side, at, close, close_ml=None):
    """(win, push, loss) for a bet taken at `at`, if the close is the truth. mk spread/total: at and close are lines
    (home margin / total points); mk ml: at is ignored, close is the closing home-margin line, close_ml (home, away)
    the closing moneylines if known."""
    sd, sdT, key = params(sport)
    if mk == 'ml':
        if close_ml and close_ml[0] is not None and close_ml[1] is not None:
            q = novig(*close_ml)
            return (q, 0.0, 1 - q) if side == 'home' else (1 - q, 0.0, q)
        if close is None:
            return None
        hw, hp, hl = split(pmf(close, sd, key), 0)
        hw, hl = hw / (hw + hl), hl / (hw + hl)          # a tie isn't a result on the moneyline
        return (hw, 0.0, hl) if side == 'home' else (hl, 0.0, hw)
    if at is None or close is None:
        return None
    if mk == 'total':
        hw, hp, hl = split(pmf(close, sdT, None, 0, TMAX), at)
        return (hw, hp, hl) if side == 'over' else (hl, hp, hw)
    hw, hp, hl = split(pmf(close, sd, key), at)        # basketball: plain normal (overtime settles a tie near 0)
    return (hw, hp, hl) if side == 'home' else (hl, hp, hw)


def ret(sport, mk, side, at, price, close, close_ml=None):
    """CLV-implied return per unit risked at `price` (American), or None"""
    c = chances(sport, mk, side, at, close, close_ml)
    if c is None or price is None:
        return None
    w, _, l = c
    return w * (dec(price) - 1) - l


def pts(mk, side, at, close):
    """points the line moved toward the bet between the bet and the close (spread/total only)"""
    if at is None or close is None or mk == 'ml':
        return None
    return (close - at) if side in ('home', 'over') else (at - close)


def _t(xs):
    n = len(xs)
    if n < 2:
        return None
    m = sum(xs) / n
    s = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    return round(m / (s / math.sqrt(n)), 2) if s else None


def summary(entries):
    """the record line every pick table leads with. entries: dicts with clvRet (CLV-implied return), clv (points),
    beat (+1 the close moved toward the pick, 0 no move, -1 away)."""
    r = [e['clvRet'] for e in entries if e.get('clvRet') is not None]
    p = [e['clv'] for e in entries if e.get('clv') is not None]
    b = [e['beat'] for e in entries if e.get('beat') is not None]
    out = {'clvN': len(r), 'clvRet': round(sum(r) / len(r), 4) if r else None, 'clvT': _t(r),
           'clv': round(sum(p) / len(p), 2) if p else None,
           'beat': round(sum(1 for x in b if x > 0) / len(b), 3) if b else None,
           'still': round(sum(1 for x in b if x == 0) / len(b), 3) if b else None}
    return out


def judge(e, sport, mk, side, at, price, close, close_ml=None, at_ml=None):
    """fill e with clv (points), clvRet and beat from the bet and the close; mk ml compares no-vig chances"""
    e['clvRet'] = None if (r := ret(sport, mk, side, at, price, close, close_ml)) is None else round(r, 4)
    if mk == 'ml':
        e['clv'] = None
        q0 = 1 / dec(price) if price is not None else None
        c = chances(sport, 'ml', side, None, close, close_ml)
        # beat: the close's no-vig chance above the flag price's break-even chance
        e['beat'] = None if c is None or q0 is None else (1 if c[0] > q0 + 1e-9 else -1)
    else:
        d = pts(mk, side, at, close)
        e['clv'] = None if d is None else round(d, 1)
        e['beat'] = None if d is None else (1 if d > 0 else 0 if d == 0 else -1)
    return e


def judge_pick(e, sport, close, close_ml=None):
    """an upset or favorite pick (the sport pick tabs): e has side, L (home-margin line when flagged) and ml (the flag
    price, None when it was graded on the spread at -110). Points: the spread's move toward the pick; the return: the
    graded bet (the moneyline, else the spread) priced at the close."""
    mk = 'ml' if e.get('ml') is not None else 'spread'
    cml = tuple(close_ml) if close_ml and None not in close_ml else None
    r = ret(sport, mk, e['side'], e['L'], e['ml'] if mk == 'ml' else -110, close, cml)
    e['clvRet'] = None if r is None else round(r, 4)
    d = pts('spread', e['side'], e['L'], close)
    e['clv'] = None if d is None else round(d, 1)
    e['beat'] = None if d is None else (1 if d > 0 else 0 if d == 0 else -1)
    return e


# ---------------------------------------------------------------- fit and backtest (numpy)

def load_wf(sport):
    fn = os.path.join(WF, sport + '.json.gz')
    return [r for r in json.load(gzip.open(fn)) if r.get('L') is not None] if os.path.exists(fn) else []


# ---------------------------------------------------------------- bad opening lines (Oct 21 2026)
# The history's opens have errors no one could have bet: spreads with home and away swapped (-4.5 then 4.5, most at
# neutral sites in 2025-26 CBB) and moves to the close no market makes (Harvard -12.5 to +1.5). They show up as huge
# closing line value: 45 of CBB's 102 held-out picks. The one cleaner for every script (games_picks rules and
# segments, units.py, close_model.py, paper_book.py, this file's backtest).
MOVE_K = 6           # an open-to-close move past 6 robust sd (MAD x 1.4826; ~9 pts on a CBB spread) is a bad line
_MOVE = {}


def mirrored(o, c):
    """an open that is the close with home and away swapped: an orientation error, not a line move"""
    return abs(o + c) <= 1 and min(abs(o), abs(c)) >= 2.5


def move_cut(sport, mk):
    """the largest open-to-close move the history believes, points"""
    if (sport, mk) not in _MOVE:
        ko, kc = ('Lo', 'L') if mk == 'spread' else ('To', 'T')
        mv = sorted(r[kc] - r[ko] for r in load_wf(sport) if r.get(ko) is not None and r.get(kc) is not None
                    and not (mk == 'spread' and mirrored(r[ko], r[kc])))
        if not mv:
            _MOVE[(sport, mk)] = None
        else:
            med = mv[len(mv) // 2]
            _MOVE[(sport, mk)] = MOVE_K * 1.4826 * sorted(abs(v - med) for v in mv)[len(mv) // 2]
    return _MOVE[(sport, mk)]


def bad_open(sport, mk, o, c):
    """True when an opening line (o) can't be believed against its close (c)"""
    if o is None or c is None:
        return False
    if mk == 'spread' and mirrored(o, c):
        return True
    cut = move_cut(sport, mk)
    return cut is not None and abs(c - o) > cut


def bad_open_g(sport, mk, g):
    """bad_open for a history row"""
    return bad_open(sport, mk, *((g.get('Lo'), g.get('L')) if mk == 'spread' else (g.get('To'), g.get('T'))))


def key_table(rows, sd):
    obs = [0.0] * (KMAX + 1)
    ex = [0.0] * (KMAX + 1)
    for g in rows:
        obs[min(KMAX, int(abs(round(g['res']))))] += 1
        L = g['L']
        a, b = int(math.floor(L - 6 * sd)), int(math.ceil(L + 6 * sd))
        for k in range(max(-KMAX, a), min(KMAX, b) + 1):
            ex[abs(k)] += phi((k + 0.5 - L) / sd) - phi((k - 0.5 - L) / sd)
    return [round(0.0 if d == 0 else (o + KA) / (x + KA), 4) for d, (o, x) in enumerate(zip(obs, ex))]


def stats(xs):
    import numpy as np
    x = np.asarray(xs, float)
    n = len(x)
    if n < 2:
        return {'n': n}
    m, s = float(x.mean()), float(x.std(ddof=1))
    return {'n': n, 'mean': round(m, 4), 't': round(m / (s / math.sqrt(n)), 2) if s else None, 'sd': round(s, 3),
            'need': int(math.ceil((2 * s / m) ** 2)) if m > 0 and s else None}


def slope(x, y):
    """OLS y = a + b x with HC1 t on b: the share of the model's disagreement with the open the close took"""
    import numpy as np
    x, y = np.asarray(x, float), np.asarray(y, float)
    n = len(x)
    if n < 30:
        return None
    X = np.column_stack([np.ones(n), x])
    XtXi = np.linalg.inv(X.T @ X)
    beta = XtXi @ X.T @ y
    e = y - X @ beta
    V = XtXi @ (X.T * e ** 2) @ X @ XtXi * n / (n - 2)
    return {'n': n, 'b': round(float(beta[1]), 3), 't': round(float(beta[1] / math.sqrt(V[1, 1])), 1)}


def judge_bets(sport, bets):
    """bets: {mk, side, at, price, close, res} -> the CLV block and the result block side by side"""
    out = []
    for b in bets:
        e = judge({}, sport, b['mk'], b['side'], b['at'], b['price'], b['close'])
        d = (b['res'] - b['at']) if b['side'] in ('home', 'over') else (b['at'] - b['res'])
        if b['mk'] == 'ml':
            d = b['res'] if b['side'] == 'home' else -b['res']
        e['profit'] = 0.0 if d == 0 else (dec(b['price']) - 1 if d > 0 else -1.0)
        e['S'] = b['S']
        out.append(e)
    return out


def block(es):
    s = summary(es)
    r = stats([e['clvRet'] for e in es if e.get('clvRet') is not None])
    p = stats([e['clv'] for e in es if e.get('clv') is not None])
    roi = stats([e['profit'] for e in es])
    return {**s, 'clvT': r.get('t'), 'clvNeed': r.get('need'), 'ptsT': p.get('t'), 'ptsSd': p.get('sd'),
            'roi': roi.get('mean'), 'roiT': roi.get('t'), 'roiNeed': roi.get('need'),
            'w': sum(1 for e in es if e['profit'] > 0), 'l': sum(1 for e in es if e['profit'] < 0)}


def verdict(b):
    if not b or (b.get('clvN') or 0) < 30 or b.get('clvT') is None:
        return 'too few'
    if b['clvRet'] > 0 and b['clvT'] >= 2:
        return 'beats the close'
    if b['clvT'] <= -2:
        return 'the close disagrees'
    return 'unproven'


def fit():
    import numpy as np
    sys.path.insert(0, HERE)
    import games_picks as GP
    import nfl_picks as K
    gp_fit = json.load(open(GP.FIT))['sports']
    res = {'asof': datetime.date.today().isoformat(), 'ka': KA, 'sports': {}, 'backtest': {}}
    rows_by = {s: load_wf(s) for s in SPORTS}
    for s, rows in rows_by.items():
        if not rows:
            continue
        r = [g for g in rows if g.get('res') is not None]
        sd = float(np.std([g['res'] - g['L'] for g in r]))
        tt = [g['tot'] - g['T'] for g in r if g.get('T') is not None and g.get('tot') is not None]
        sdT = float(np.std(tt)) if tt else SD0[s][1]
        key = key_table(r, sd) if s in FOOTBALL else None
        res['sports'][s] = {'sd': round(sd, 2), 'sdT': round(sdT, 2), 'key': key, 'games': len(r)}
    global _F
    _F = res
    for s, rows in rows_by.items():
        G = gp_fit.get(s)
        held = GP.HELD[s]
        op = [g for g in rows if g.get('Lo') is not None and g.get('res') is not None]
        if not op or not G:
            res['backtest'][s] = {'name': GP.NAMES[s], 'none': 'no opening lines in the history; judged live from the odds archive'}
            continue
        seasons = sorted({g['S'] for g in op})
        cap = tuple(G.get('cap') or (None, None))
        cuts = {mk: G['markets'][mk]['cut'] for mk in GP.MARKETS}
        out = {'name': GP.NAMES[s], 'seasons': seasons, 'held': held, 'games': len(op),
               'opensTotal': sum(1 for g in op if g.get('To') is not None)}
        # 1. the share of the model's disagreement with the open that the close took
        out['slope'] = {'spread': slope([g['m'] - g['Lo'] for g in op], [g['L'] - g['Lo'] for g in op])}
        tp = [g for g in op if g.get('To') is not None and g.get('tm') is not None and g.get('T') is not None]
        out['slope']['total'] = slope([g['tm'] - g['To'] for g in tp], [g['T'] - g['To'] for g in tp]) if tp else None
        out['slopeBySeason'] = {str(S): slope([g['m'] - g['Lo'] for g in op if g['S'] == S], [g['L'] - g['Lo'] for g in op if g['S'] == S]) for S in seasons}
        # 2. the model's side at the open by disagreement, judged by the close (and by the result, second)
        grid = {}
        for mk, th in (('spread', (1, 2, 3, 4, 5, 6)), ('total', (2, 3, 4, 6, 8))):
            grid[mk] = []
            for c in th:
                bets = []
                for g in (op if mk == 'spread' else tp):
                    o, m = (g['Lo'], g['m']) if mk == 'spread' else (g['To'], g['tm'])
                    if abs(m - o) < c or (cap[0 if mk == 'spread' else 1] is not None and abs(m - o) > cap[0 if mk == 'spread' else 1]) or bad_open_g(s, mk, g):
                        continue                # past three sd of the disagreement: a bad opening line, not a bet
                    side = ('home' if m > o else 'away') if mk == 'spread' else ('over' if m > o else 'under')
                    bets.append({'mk': mk, 'side': side, 'at': o, 'price': -110, 'close': g['L'] if mk == 'spread' else g['T'],
                                 'res': g['res'] if mk == 'spread' else g['tot'], 'S': g['S']})
                es = judge_bets(s, bets)
                grid[mk].append({'cut': c, 'all': block(es), 'held': block([e for e in es if e['S'] >= held])})
        out['grid'] = grid
        # 3. the shipped rules taken at the open: the games-page pricing (b fit on the closes before each season,
        # spreads and totals at -110; no opening moneylines exist) and the upset and favorite rules
        rules = {}
        coefs = {int(S): c for S, c in G['bBySeason'].items()}
        gp_bets, gp_all = [], []
        for g in op:
            go = {**g, 'L': g['Lo'], 'T': g.get('To'), 'mlH': None, 'mlA': None, 'oH': -110, 'oA': -110, 'oO': -110, 'oU': -110}
            if go['T'] is None:
                go['tm'] = None
            bs = [b for b in GP.bets_for(go, coefs.get(g['S'], {}), cap) if b['mk'] != 'ml']
            for b, into in ((GP.choose(bs, cuts), gp_bets), (GP.choose(bs, {'spread': 0.0, 'total': 0.0}), gp_all)):
                for x in b:
                    into.append({'mk': x['mk'], 'side': x['side'], 'at': go['L'] if x['mk'] == 'spread' else go['T'], 'price': -110,
                                 'close': g['L'] if x['mk'] == 'spread' else g['T'], 'res': g['res'] if x['mk'] == 'spread' else g['tot'], 'S': g['S']})
        for name, bets in (('games page picks', gp_bets), ('games page, every +EV bet', gp_all)):
            for mk in ('spread', 'total'):
                es = judge_bets(s, [b for b in bets if b['mk'] == mk])
                if es:
                    rules[f'{name}|{mk}'] = {'all': block(es), 'held': block([e for e in es if e['S'] >= held])}
        for typ in ('upset', 'fav'):
            bets_pts = []
            for g in op:
                if (cap[0] is not None and abs(g['m'] - g['Lo']) > cap[0]) or bad_open_g(s, 'spread', g):
                    continue
                side = K.upset_side(g['m'], g['Lo']) if typ == 'upset' else K.fav_side(g['m'], g['Lo'], K.odds(g.get('mlH')), K.odds(g.get('mlA')))
                if not side:
                    continue
                bets_pts.append({'mk': 'spread', 'side': side, 'at': g['Lo'], 'price': -110, 'close': g['L'], 'res': g['res'], 'S': g['S']})
            es = judge_bets(s, bets_pts)
            if es:
                rules[f'{typ}|spread'] = {'all': block(es), 'held': block([e for e in es if e['S'] >= held])}
        for k, v in rules.items():
            v['verdict'] = verdict(v['held'] if (v['held'].get('clvN') or 0) >= 30 else v['all'])
        out['rules'] = rules
        res['backtest'][s] = out
    # NBA's walk-forward model sees each game's final injury report, which the open didn't: its CLV at the open is
    # an upper bound until the archive (model as it stood when the line was seen) has a season
    if 'nba' in res['backtest'] and 'rules' in res['backtest']['nba']:
        res['backtest']['nba']['leak'] = 'the model saw tip-time injury news the open did not have'
    with open(FIT, 'w') as f:
        json.dump(res, f, indent=1)
    for s, b in res['backtest'].items():
        if 'none' in b:
            print(s, b['none'])
            continue
        print(s, 'slope', b['slope'])
        for mk, gg in b['grid'].items():
            for c in gg:
                a = c['held']
                print(f"  {mk} {c['cut']}+: n {a['clvN']} clv {a['clv']} (t {a['ptsT']}) beat {a['beat']} clvRet {a['clvRet']} t {a['clvT']} need {a['clvNeed']} | roi {a['roi']} t {a['roiT']} need {a['roiNeed']}")
        for k, v in b['rules'].items():
            a = v['held'] if (v['held'].get('clvN') or 0) >= 30 else v['all']
            print(f"  {k}: n {a['clvN']} clv {a['clv']} beat {a['beat']} clvRet {a['clvRet']} t {a['clvT']} | roi {a['roi']} t {a['roiT']} -> {v['verdict']}")


# ---------------------------------------------------------------- bet timing (from the odds archive)

def timing(sport, rows, min_edge):
    """rows: the archive's snapshots for one sport. For every snapshot of a game before its kick, the model's side at
    that line, judged by the game's last snapshot before kick (the close). Buckets by hours to kick."""
    by = {}
    for r in rows:
        by.setdefault(r['id'], []).append(r)
    buckets = (('24h+', 24, 1e9), ('6-24h', 6, 24), ('1-6h', 1, 6), ('<1h', 0, 1))
    acc = {b[0]: [] for b in buckets}
    for gid, snaps in by.items():
        snaps.sort(key=lambda r: r['t'])
        kick = snaps[-1].get('k')
        if not kick:
            continue
        pre = [r for r in snaps if r['t'] < kick and r.get('L') is not None]
        if len(pre) < 2:
            continue
        close = pre[-1]
        for r in pre[:-1]:
            if r.get('m') is None or abs(r['m'] - r['L']) < min_edge:
                continue
            h = (datetime.datetime.fromisoformat(kick.replace('Z', '+00:00')) - datetime.datetime.fromisoformat(r['t'].replace('Z', '+00:00'))).total_seconds() / 3600
            side = 'home' if r['m'] > r['L'] else 'away'
            e = judge({}, sport, 'spread', side, r['L'], -110, close['L'])
            for name, lo, hi in buckets:
                if lo <= h < hi:
                    acc[name].append(e)
    return [{'when': name, **summary(acc[name])} for name, _, _ in buckets]


def test():
    global _F
    _F = {}
    # a bet at the close is worth the vig: about -4.5% at -110 with no key numbers in play
    r = ret('nba', 'spread', 'home', 4.5, -110, 4.5)
    assert -0.06 < r < -0.03, r
    # beating the close by 2 points in the NBA is worth about +7-8 points of return
    r2 = ret('nba', 'spread', 'home', 2.5, -110, 4.5)
    assert r2 > r + 0.05, (r, r2)
    # direction: home at 3 with the close at 3.5 (the home side's margin expected higher) beats it
    assert pts('spread', 'home', 3, 3.5) == 0.5 and pts('spread', 'away', 3, 3.5) == -0.5
    assert pts('total', 'under', 150, 147) == 3
    w, p, l = chances('nfl', 'spread', 'home', 3, 3)
    assert p > 0.02 and abs(w - l) < 0.02, (w, p, l)
    # the moneyline with no closing prices: home favored by 7 wins about 70% in the NFL
    w, _, _ = chances('nfl', 'ml', 'home', None, 7)
    assert 0.65 < w < 0.75, w
    q = chances('nba', 'ml', 'away', None, 3, (-150, 130))[0]
    assert abs(q - (1 - novig(-150, 130))) < 1e-9
    s = summary([{'clvRet': 0.02, 'clv': 1, 'beat': 1}, {'clvRet': -0.01, 'clv': -0.5, 'beat': -1}, {'clvRet': 0.0, 'clv': 0, 'beat': 0}])
    assert s['clvN'] == 3 and s['beat'] == 0.333 and s['still'] == 0.333, s
    print('clv: ok')


if __name__ == '__main__':
    a = sys.argv[1:]
    if a and a[0] == '--fit':
        fit()
    elif a and a[0] == '--test':
        test()
    else:
        print(__doc__)
