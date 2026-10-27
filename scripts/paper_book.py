#!/usr/bin/env python3
"""The paper book (ARK Betting Plan items 1, 4, 5 and 7, Oct 21 2026): every would-be bet from the pre-registered rules
in scripts/paper_rules.json, logged with its time, the book's line and price then, our model as it stood, the stake,
and what it was worth at the close. Paper only: no real money, free data only. The book is Novig since Oct 27 2026
(scripts/novig.py through odds_snap.py; DraftKings through ESPN before that and for a game Novig doesn't list); each
bet records the book of its entry (bk) and of its close (closeBk).

    python3 scripts/paper_book.py            # data/paper_book.json from the dense snapshots (scripts/odds_snap.py);
                                             # the odds-snap workflow runs it after every snapshot
    python3 scripts/paper_book.py --seed     # data/paper_seed.json: each rule replayed on the walk-forward history
                                             # (numpy); the expected numbers, never counted as the live record
    python3 scripts/paper_book.py --test     # self-check

The entry. A rule looks at a game once: the first snapshot with both the book's line and our model's number, if that
is within entry.hours of the first line we saw (else the game is skipped as late). The bet is that line at that price,
whatever ESPN calls the open; how far the line had already moved from ESPN's open is logged with it.

Sizing: Dengler Units (DU, scripts/units.py), the same stake the Predictions picks use; 1 DU = 1% of the bankroll now
(the starting bankroll is 100 DU):
    expected close = line + k x gap toward the bet (k: the rule's backtest, the points the close moved per point of gap)
    chance         = the bet's (win, push, loss) if that close is the truth (scripts/clv.py)
    stake          = DU for that chance at that price (the market's calibrated edge, its uncertainty shrink, lam, the
                     slate's size), x the bankroll now / 100
DU's calibration pools these bets once 20 are graded, so the stakes refit as the book grades. Caps: the market's DU cap
a game (several rules on one game share it) and slateCap % open on one sport's slate. Bets already logged keep their
stake (Oct 21 2026: quarter Kelly x .5, caps 2% a game, 3% a team a day, 10% a slate, a 25% drawdown halving them).
Close-model rules (type close, scripts/close_model.py, added Oct 21 with their own clock) bet the side the predicted
close moves toward when that side at -110 is worth more than tau there, and price the stake on that predicted close.
Several rules may take the same game; each keeps its own record.

Kill switch: the live rule monitor's test (scripts/rule_monitor.py, pre-registered in scripts/monitor_rules.json; the
Predictions pick rules stop on the same one): with 50+ bets judged by the close, a rule whose last 300 are worth clustered
t < -1 at the close, or whose CUSUM on close value crosses h, stops (stake 0, still logged at 0 DU so its record keeps
going) until the rule is changed. Changing a rule (anything but its note) restarts its clock: its
record counts only bets from the change on.

Gates (shown on the games page's paper book tab; all must pass before real money is even discussed): 400+ settled
bets, pooled close value >= +1% with t >= 2 on the effective count, the close moved our way on 52%+, no single rule
carrying it (the pool without its best rule still beats the close), and realized ROI within 2 standard errors of what
the close implied. Slate correlation: rho is the within-slate correlation of close value (one-way ANOVA), and the
effective count is the sum over slates of n / (1 + (n - 1) rho).

The control: the live pick-rules picks (data/games_picks_<sport>.json, scripts/games_picks.py) judged the same way at a
flat 1u, outside the bankroll and the gates.
"""
import datetime
import gzip
import hashlib
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import clv as C
import rule_monitor as RM
from odds_snap import rows_of, DENSE

RULES = os.path.join(HERE, 'paper_rules.json')
OUT = os.path.join(ROOT, 'data', 'paper_book.json')
SEED = os.path.join(ROOT, 'data', 'paper_seed.json')
HIGH = {'ACC', 'B10', 'B12', 'BE', 'SEC'}      # high-major conferences; any other game is low/mid-major


def iso(t):
    return datetime.datetime.fromisoformat(t.replace('Z', '+00:00'))


def dec(o):
    return C.dec(o)


def slate(sport, kick):
    """one sport's US day (kick moved to US Eastern, about UTC-5)"""
    return f"{sport}:{(iso(kick) - datetime.timedelta(hours=5)).date().isoformat()}"


def tier(hc, ac):
    if hc is None and ac is None:
        return None
    return 'high' if hc in HIGH and ac in HIGH else 'low/mid'


def rule_hash(r):
    return hashlib.sha1(json.dumps({k: v for k, v in r.items() if k not in ('note', 'registered')}, sort_keys=True).encode()).hexdigest()[:10]


def mean_t(xs):
    n = len(xs)
    if n < 2:
        return (round(xs[0], 4) if xs else None), None, None
    m = sum(xs) / n
    s = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    return round(m, 4), (round(m / (s / math.sqrt(n)), 2) if s else None), s


def rule_side(rule, m, line):
    """the side a rule takes at this line and model number, and the gap, or (None, gap)"""
    if m is None or line is None:
        return None, None
    gap = m - line
    if rule.get('cap') is not None and abs(gap) > rule['cap']:
        return None, abs(gap)                     # past three sd: a bad line, not a bet
    if rule['type'] == 'gap':
        if abs(gap) < rule['x']:
            return None, abs(gap)
        if rule['mk'] == 'total':
            return ('over' if gap > 0 else 'under'), abs(gap)
        return ('home' if gap > 0 else 'away'), abs(gap)
    if rule['type'] == 'dog':                     # the market underdog when the model has it winning outright, x+ off
        if line == 0 or m * line >= 0 or abs(gap) <= rule['x']:
            return None, abs(gap)
        return ('away' if line > 0 else 'home'), abs(gap)
    return None, abs(gap)


_CTX = {}


def context(sport):
    """{espn id: {home, away (full names), wk, po}} from the sport's last build, for the close model's cells"""
    if sport not in _CTX:
        out = {}
        try:
            d = json.load(open(os.path.join(ROOT, 'data', f'{sport}_games.json')))
        except (OSError, ValueError):
            d = {}
        for g in d.get('games', []):
            h, a = g.get('home'), g.get('away')
            nm = lambda x: (x.get('name') or x.get('n')) if isinstance(x, dict) else x
            out[str(g.get('espn') or g['id'])] = {'home': nm(h), 'away': nm(a), 'wk': d.get('week'), 'po': g.get('po'), 'neutral': g.get('neutral')}
        _CTX[sport] = out
    return _CTX[sport]


def close_side(rule, gid, g, at, b2b):
    """a close-predictor rule (scripts/close_model.py): the side the predicted close moves toward, when that side at
    -110 is worth more than tau there. -> (side, gap, predicted close) or (None, gap, None)"""
    import close_model as CM
    sport, mk = rule['sport'], rule['mk']
    line, m = (at.get('T'), at.get('tm')) if mk == 'total' else (at.get('L'), at.get('m'))
    if line is None or m is None:
        return None, None, None
    gap = abs(m - line)
    if rule.get('cap') is not None and gap > rule['cap']:
        return None, gap, None
    cx = context(sport).get(gid) or {}
    row = {'home': cx.get('home') or g.get('h'), 'away': cx.get('away') or g.get('a'), 'date': at['k'],
           'Lo' if mk == 'spread' else 'To': line, 'wk': cx.get('wk'), 'fcs': 0, 'po': cx.get('po') or 0,
           'neutral': 1 if (g.get('neutral') or cx.get('neutral')) else 0, 'b2b': b2b}
    try:
        e = CM.expected(sport, mk, {'o': line, 'm': m, 'neutral': row['neutral'], 'cells': CM.game_cells(sport, mk, row)})
    except Exception:
        return None, gap, None
    if not e or e.get('E') is None or e['E'] <= rule['tau']:
        return None, gap, None
    return e['side'], gap, e['close']


def bet_text(g, mk, side, line, price):
    p = f"{price:+.0f}" if price is not None else ''
    if mk == 'total':
        return f"{side} {line:g} {p}".strip()
    team = g.get('h') if side == 'home' else g.get('a')
    hl = -line if side == 'home' else line           # the bet side's own spread: home -3 is L +3
    return f"{team} {hl:+g} {p}".replace('+0 ', 'pk ').strip()


def settle(b, fin):
    h, a = fin
    if b['mk'] == 'total':
        d = h + a - b['line']
        win = None if d == 0 else (d > 0) == (b['side'] == 'over')
    else:
        d = h - a - b['line']
        win = None if d == 0 else (d > 0) == (b['side'] == 'home')
    b['score'] = [h, a]
    b['res'] = 'p' if win is None else ('w' if win else 'l')
    unit = b.get('stake', 1.0)
    b['profit'] = 0.0 if win is None else round(unit * (dec(b['price']) - 1) if win else -unit, 4)
    b['ret'] = 0.0 if win is None else round(dec(b['price']) - 1 if win else -1.0, 4)   # per unit risked


def games_of(sport):
    """{id: {rows (no finals), fin, first sighting}} from the dense snapshots"""
    G = {}
    for r in rows_of(sport):
        g = G.setdefault(r['id'], {'rows': [], 'fin': None})
        if 'fin' in r:
            g['fin'] = r['fin']
            continue
        if 'h' in r:
            g.update({k: r.get(k) for k in ('h', 'a', 'hc', 'ac', 'open')})
        g['rows'].append(r)
    for g in G.values():
        g['rows'].sort(key=lambda r: r['t'])
    return G


def close_of(g):
    pre = [r for r in g['rows'] if r['t'] < r['k']]
    return pre[-1] if pre else None


def judge_close(b, g, sport):
    c = close_of(g) if g else None
    if not c:
        return
    cl = c.get('T') if b['mk'] == 'total' else c.get('L')
    if cl is None:
        return
    b['close'] = cl
    b['closeBk'] = 'Novig' if c.get('src') == 'novig' else 'DraftKings'
    C.judge(b, sport, b['mk'], b['side'], b['line'], b['price'], cl)


# ---------------------------------------------------------------- the record

def record(bs):
    """close value first (n settled with a close), results second"""
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


def gates(bs, rule_ids, G):
    jc = [b for b in bs if b.get('clvRet') is not None]
    rec = record(bs)
    cor = icc(bs)
    m, _, s = mean_t([b['clvRet'] for b in jc])
    tEff = round(m / (s / math.sqrt(cor['nEff'])), 2) if m is not None and s and cor['nEff'] else None
    # no single rule carrying it: the pool without the rule that adds the most close value still beats the close
    best = max(rule_ids, key=lambda i: sum(b['clvRet'] for b in jc if b['rule'] == i), default=None)
    rest = [b['clvRet'] for b in jc if b['rule'] != best]
    rm, rt, _ = mean_t(rest)
    st = [b for b in bs if b.get('res') is not None and b.get('clvRet') is not None]
    roi, _, rs = mean_t([b['ret'] for b in st])
    cm = mean_t([b['clvRet'] for b in st])[0]
    se = (rs / math.sqrt(len(st))) if rs and st else None
    out = [
        {'gate': f"{G['minN']}+ settled bets", 'value': rec['clvN'], 'pass': rec['clvN'] >= G['minN']},
        {'gate': f"close value {G['clvRet'] * 100:+.0f}%+ at t {G['t']:g}+ (effective n)", 'value': None if m is None else f"{m * 100:+.1f}% t {tEff}",
         'pass': m is not None and tEff is not None and m >= G['clvRet'] and tEff >= G['t']},
        {'gate': f"close moved our way {G['beat'] * 100:.0f}%+", 'value': None if rec['beat'] is None else f"{rec['beat'] * 100:.0f}%",
         'pass': rec['beat'] is not None and rec['beat'] >= G['beat']},
        {'gate': 'no single rule carrying it', 'value': None if rm is None else f"without {best}: {rm * 100:+.1f}%",
         'pass': rm is not None and rm > 0 and (rt or 0) >= 1},
        {'gate': 'results within 2 SE of the close', 'value': None if roi is None or se is None else f"ROI {roi * 100:+.1f}% vs {cm * 100:+.1f}% (SE {se * 100:.1f})",
         'pass': roi is not None and se is not None and abs(roi - cm) <= G['se'] * se},
    ]
    return out, cor, tEff


# ---------------------------------------------------------------- build

def build(now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    stamp = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    P = json.load(open(RULES))
    S = P['stake']
    try:
        old = json.load(open(OUT))
    except (OSError, ValueError):
        old = {}
    ledger = old.get('ledger', [])
    clocks = old.get('clocks', {})
    killed = old.get('killed', {})
    rules = {r['id']: r for r in P['rules']}
    for i, r in rules.items():
        # the stake rules count as part of every rule: a sizing change restarts the clocks
        h = rule_hash({**r, '_stake': {k: v for k, v in S.items() if k != 'note'}})
        if i not in clocks or clocks[i]['hash'] != h:
            # a new or changed rule: its clock starts now (or at its registration, the first time)
            since = r['registered'] if i not in clocks else stamp
            if i in clocks:
                killed.pop(i, None)
            clocks[i] = {'hash': h, 'since': since}
    sports = sorted({r['sport'] for r in P['rules']} | {'cfb', 'nfl', 'cbb', 'nba'})
    G = {s: games_of(s) for s in sports}
    try:
        cbb_conf = {str(g['id']): (g['home'].get('conf'), g['away'].get('conf')) for g in json.load(open(os.path.join(ROOT, 'data', 'cbb_games.json')))['games']}
    except (OSError, ValueError, KeyError):
        cbb_conf = {}
    # back-to-backs (NBA): a team that started a game the local day before, from the snapshots
    played = set()
    for sp in G:
        for g in G[sp].values():
            if g['rows']:
                d0 = (iso(g['rows'][-1]['k']) - datetime.timedelta(hours=6)).date()
                played |= {(sp, g.get('h'), d0), (sp, g.get('a'), d0)}

    def b2b(sp, g, kick):
        d = (iso(kick) - datetime.timedelta(hours=6)).date() - datetime.timedelta(days=1)
        return 1 if (sp, g.get('h'), d) in played or (sp, g.get('a'), d) in played else 0
    have = {(b['rule'], b['id'], b['mk']) for b in ledger}
    seen_late = {(b['rule'], b['id'], b['mk']) for b in old.get('skipped', [])}
    skipped = [x for x in old.get('skipped', []) if iso(x['k']) > now - datetime.timedelta(days=3)]

    # settle and judge what's there first: the bankroll at each new bet counts only bets settled by then
    def refresh():
        for b in ledger:
            g = G.get(b['sport'], {}).get(b['id'])
            if g and b.get('res') is None and g.get('fin'):
                settle(b, g['fin'])
                b['settledAt'] = b.get('settledAt') or stamp
            if g and iso(b['k']) <= now:
                judge_close(b, g, b['sport'])
    refresh()
    import units as DU
    entries = []
    for i, r in rules.items():
        for gid, g in G.get(r['sport'], {}).items():
            if (i, gid, r['mk']) in have or (i, gid, r['mk']) in seen_late or not g['rows']:
                continue
            lk = 'T' if r['mk'] == 'total' else 'L'
            mkey = 'tm' if r['mk'] == 'total' else 'm'
            lined = [x for x in g['rows'] if x.get(lk) is not None]
            if not lined:
                continue
            first = iso(lined[0]['t'])
            at = next((x for x in lined if x.get(mkey) is not None), None)
            if at is None:
                continue
            if iso(at['t']) > first + datetime.timedelta(hours=P['entry']['hours']) or at['t'] >= at['k']:
                if iso(at['t']) > first + datetime.timedelta(hours=P['entry']['hours']):
                    skipped.append({'rule': i, 'id': gid, 'mk': r['mk'], 'k': at['k'], 'why': 'model number came after the entry window'})
                continue
            if at['t'] < clocks[i]['since']:            # a date or a stamp; either compares as text
                continue
            hc, ac = g.get('hc'), g.get('ac')
            if r['sport'] == 'cbb' and hc is None and ac is None:
                hc, ac = cbb_conf.get(gid, (None, None))
            pclose = None
            if r['type'] == 'close':
                side, gap, pclose = close_side(r, gid, g, at, b2b(r['sport'], g, at['k']))
            else:
                side, gap = rule_side(r, at[mkey], at[lk])
            if side is None:
                continue
            entries.append((at['t'], i, gid, g, at, side, gap, tier(hc, ac) if r['sport'] == 'cbb' else None, pclose))
    entries.sort(key=lambda e: (e[0], e[1]))
    for t, i, gid, g, at, side, gap, tr, pclose in entries:
        r = rules[i]
        mk = r['mk']
        line = at['T'] if mk == 'total' else at['L']
        pk = {('spread', 'home'): 'oH', ('spread', 'away'): 'oA', ('total', 'over'): 'oO', ('total', 'under'): 'oU'}[(mk, side)]
        price = at.get(pk) or -110.0
        # the bankroll then: the start plus every bet settled before this one was placed
        tt = iso(t)
        bank, peak = P['bankroll'], P['bankroll']
        for b in sorted([b for b in ledger if b.get('res') is not None and b.get('settledAt')], key=lambda b: b['settledAt']):
            if iso(b['settledAt']) <= tt:
                bank += b['profit']
                peak = max(peak, bank)
        sgn = 1 if side in ('home', 'over') else -1
        # the close the bet is priced on: the close model's prediction, or the rule's backtest move per point of gap
        close_x = pclose if pclose is not None else line + sgn * r['k'] * gap
        ev = C.ret(r['sport'], mk, side, line, price, close_x) or 0.0
        sl = slate(r['sport'], at['k'])
        dp = DU.params(r['sport'], mk)
        n_sl = 1 + sum(1 for b in ledger if b['slate'] == sl and b['sport'] == r['sport'] and b.get('stake'))
        c = C.chances(r['sport'], mk, side, line, close_x)
        f = (DU.stake(r['sport'], mk, c, price, n_sl, dp, gap) / 100) if c and ev > 0 else 0.0
        halved = False
        why = [] if ev > 0 else ['no edge at this price: logged at 0 DU']
        if i in killed:
            f, why = 0.0, ['rule stopped by the kill switch']
        stake = f * bank
        live = [b for b in ledger if b.get('res') is None or (b.get('settledAt') and iso(b['settledAt']) > tt)]
        room_game = dp['cap'] / 100 * bank - sum(b['stake'] for b in ledger if b['id'] == gid and b['sport'] == r['sport'])
        room_slate = S['slateCap'] / 100 * bank - sum(b['stake'] for b in live if b['slate'] == sl)
        cap = max(0.0, min(room_game, room_slate))
        if stake > cap:
            why.append('capped')
            stake = cap
        b = {'rule': i, 'sport': r['sport'], 'id': gid, 'k': at['k'], 'slate': sl, 'h': g.get('h'), 'a': g.get('a'), 'tier': tr,
             'mk': mk, 'side': side, 'line': line, 'price': price, 'bet': bet_text(g, mk, side, line, price),
             'bk': 'Novig' if at.get('src') == 'novig' else 'DraftKings',
             'placed': t, 'm': at.get('m'), 'tm': at.get('tm'), 'gap': round(gap, 2),
             'open': (g.get('open') or {}).get('T' if mk == 'total' else 'L'),
             'ev': round(ev, 4), 'du': {'edge': round(DU.edge(dp, ev, gap)[0], 4), 'lam': dp['lam'], 'cap': dp['cap'], 'slate': n_sl}, 'stake': round(stake, 3), 'pct': round(stake / bank * 100, 3) if bank else 0,
             'bank': round(bank, 2), 'halved': halved, 'notes': why}
        ledger.append(b)
        have.add((i, gid, mk))
    refresh()
    # the kill switch: the live rule monitor's test (scripts/rule_monitor.py, scripts/monitor_rules.json), the same one
    # the Predictions pick rules stop on: the last 300 judged by the close at clustered t < -1, or a CUSUM on close value
    # in the rule's backtest sd
    MP = RM.params()
    K = {**{k: MP[k] for k in ('window', 'minN', 't')}, 'cusum': {k: MP['cusum'][k] for k in ('k', 'h')}}
    try:
        seed_ = json.load(open(SEED))['rules']
    except (OSError, ValueError, KeyError):
        seed_ = {}

    def sd_rule(i):
        sr = seed_.get(i) or {}
        return RM.sd_of(sr['clean'] if (sr.get('clean') or {}).get('clvRet') is not None else sr)
    by_rule = {i: [b for b in ledger if b['rule'] == i and b['placed'] >= clocks[i]['since']] for i in rules}
    checks = {i: RM.decide(bs, sd_rule(i), MP) for i, bs in by_rule.items()}
    for i, d in checks.items():
        if d['stop'] and i not in killed:
            killed[i] = {'at': stamp, 'n': d['n'], 't': d['t'], 'cusum': d['cusum'], 'why': d['why']}
    # the bankroll path
    bank, peak, path = P['bankroll'], P['bankroll'], []
    for b in sorted([b for b in ledger if b.get('res') is not None], key=lambda b: (b.get('settledAt') or b['k'], b['k'])):
        bank += b['profit']
        peak = max(peak, bank)
        path.append(round(bank, 2))
    open_stake = sum(b['stake'] for b in ledger if b.get('res') is None)
    pool = [b for i in rules for b in by_rule[i]]
    gate_rows, cor, tEff = gates(pool, list(rules), P['gates'])
    try:
        seed = json.load(open(SEED))['rules']
    except (OSError, ValueError, KeyError):
        seed = {}
    rule_rows = []
    for i, r in rules.items():
        bs = by_rule[i]
        label = f"{r['sport'].upper()} {r['mk']} close model" if r['type'] == 'close' else f"{r['sport'].upper()} {'dog' if r['type'] == 'dog' else r['mk']} {r['x']:g}+"
        row = {'id': i, 'label': label, 'sport': r['sport'], 'mk': r['mk'], 'desc': r['desc'], 'since': clocks[i]['since'][:10],
               'status': 'stopped' if i in killed else 'on', 'killed': killed.get(i), 'rolling': checks[i]['t'], 'cusum': checks[i]['cusum'],
               **record(bs), 'seed': seed.get(i)}
        if r.get('split') == 'tier':
            row['tiers'] = {tname: record([b for b in bs if b.get('tier') == tname]) for tname in ('high', 'low/mid')}
        rule_rows.append(row)
    # the control: the live pick-rules picks, flat 1u, judged by the same closes
    ctrl = []
    for s in ('cfb', 'nfl', 'cbb', 'nba'):
        try:
            log = json.load(open(os.path.join(ROOT, 'data', f'games_picks_{s}.json'))).get('log', [])
        except (OSError, ValueError):
            continue
        for e in log:
            if (e.get('flagged') or '') < P['registered'] or e.get('mk') == 'ml' or e.get('line') is None:
                continue
            g = G.get(s, {}).get(str(e['id']))
            b = {'rule': 'control', 'sport': s, 'id': str(e['id']), 'k': e['kick'], 'slate': slate(s, e['kick']), 'h': e.get('home'), 'a': e.get('away'),
                 'mk': e['mk'], 'side': e['side'], 'line': e['line'], 'price': e['price'], 'placed': e['flagged'], 'stake': 1.0,
                 'bet': bet_text({'h': e.get('home'), 'a': e.get('away')}, e['mk'], e['side'], e['line'], e['price'])}
            if g:
                if iso(b['k']) <= now:
                    judge_close(b, g, s)
                if g.get('fin'):
                    settle(b, g['fin'])
            if b.get('clvRet') is None and e.get('clvRet') is not None:
                b.update({k: e.get(k) for k in ('clvRet', 'clv', 'beat', 'close')})
            if b.get('res') is None and e.get('res') in ('w', 'l', 'p'):
                b['res'] = e['res']
                b['ret'] = 0.0 if e['res'] == 'p' else (round(dec(e['price']) - 1, 4) if e['res'] == 'w' else -1.0)
                b['profit'] = b['ret']
            ctrl.append(b)
    snaps = {s: sum(len(g['rows']) for g in G[s].values()) for s in G}
    out = {'asof': stamp, 'registered': P['registered'], 'bankroll': {'start': P['bankroll'], 'now': round(bank, 2), 'peak': round(peak, 2),
           'drawdown': round((peak - bank) / peak, 4) if peak else 0, 'halved': False,
           'open': round(open_stake, 2), 'path': path[-400:]},
           'du': {s: {mk: {k: v for k, v in DU.params(s, mk).items() if k in ('a', 'b', 'lam', 'cap', 'rho', 'basis')} for mk in ('spread', 'total')} for s in sports},
           'stakeRules': S, 'record': record(pool), 'tEff': tEff, 'corr': cor, 'gates': gate_rows,
           'gatesPass': all(x['pass'] for x in gate_rows), 'rules': rule_rows, 'kill': K, 'killed': killed, 'clocks': clocks,
           'control': {'record': record(ctrl), 'recent': sorted(ctrl, key=lambda b: b['k'], reverse=True)[:30]},
           'open': sorted([b for b in ledger if b.get('res') is None], key=lambda b: (b['k'], b['rule'])),
           'recent': sorted([b for b in ledger if b.get('res') is not None], key=lambda b: b['k'], reverse=True)[:40],
           'snapshots': snaps, 'games': {s: len(G[s]) for s in G}, 'skipped': skipped[-200:], 'ledger': ledger}
    if {k: v for k, v in old.items() if k != 'asof'} == json.loads(json.dumps({k: v for k, v in out.items() if k != 'asof'})):
        return print('paper book: no change')
    with open(OUT, 'w') as f:
        json.dump(out, f, indent=1)
    print(f"paper book: {len(ledger)} bets ({len(out['open'])} open), bankroll {bank:.2f} DU, gates {'pass' if out['gatesPass'] else 'not yet'}")


# ---------------------------------------------------------------- seed (the backtest; expected numbers only)

def seed():
    P = json.load(open(RULES))
    cbb = json.load(open(os.path.join(ROOT, 'data', 'cbb_games.json')))['games']
    conf = {}
    for g in cbb:
        for s in ('home', 'away'):
            conf[g[s]['n']] = g[s].get('conf')
    out = {'asof': datetime.date.today().isoformat(), 'note': 'each rule bet at the history\'s opening line at -110, judged by its close; '
           'NBA: the walk-forward model saw tip-time injury news, an upper bound; CBB tiers use each team\'s current conference', 'rules': {}}
    import units as UN
    cf = json.load(open(os.path.join(ROOT, 'data', 'close_fit.json')))
    for r in P['rules']:
        if r['type'] == 'close':
            m = cf['sports'][r['sport']]['markets'][r['mk']]
            b = m['bets']['model']
            out['rules'][r['id']] = {'seasons': cf.get('heldSeasons') or 'held out (close_fit.json)', 'tau': m.get('tau'), 'calib': m.get('calib'),
                                     **{x: b.get(x) for x in ('clvN', 'clvRet', 'clvT', 'clv', 'beat', 'roi', 'roiT', 'w', 'l')},
                                     'clean': close_clean(r, UN)}
            print(r['id'], out['rules'][r['id']])
            continue
        rows = [g for g in C.load_wf(r['sport']) if g.get('res') is not None]
        lk, ck, mk_, rk = ('To', 'T', 'tm', 'tot') if r['mk'] == 'total' else ('Lo', 'L', 'm', 'res')
        bets = []
        for g in rows:
            if g.get(lk) is None or g.get(ck) is None or g.get(mk_) is None:
                continue
            if UN.bad_open(r['sport'], r['mk'], g):
                continue                      # a mirrored spread or a move past 6 robust sd: a history error (#302)
            side, gap = rule_side(r, g[mk_], g[lk])
            if side is None:
                continue
            bets.append({'mk': r['mk'], 'side': side, 'at': g[lk], 'price': -110, 'close': g[ck], 'res': g[rk], 'S': g['S'], 'gap': gap,
                         'tier': tier(conf.get(g['home']), conf.get(g['away']))})
        es = C.judge_bets(r['sport'], bets)
        for e, b in zip(es, bets):
            e['gap'], e['tier'] = b['gap'], b['tier']
        blk = C.block(es) if es else {'clvN': 0}
        k = round(sum(e['clv'] for e in es if e.get('clv') is not None) / sum(e['gap'] for e in es), 3) if es else None
        o = {'seasons': sorted({b['S'] for b in bets}), 'k': k, 'gap': round(sum(e['gap'] for e in es) / len(es), 2) if es else None,
             **{x: blk.get(x) for x in ('clvN', 'clvRet', 'clvT', 'clv', 'beat', 'roi', 'roiT', 'w', 'l')}}
        if r.get('split') == 'tier':
            o['tiers'] = {}
            for tname in ('high', 'low/mid'):
                sub = [e for e in es if e['tier'] == tname]
                bb = C.block(sub) if sub else {'clvN': 0}
                o['tiers'][tname] = {x: bb.get(x) for x in ('clvN', 'clvRet', 'clvT', 'roi')}
        out['rules'][r['id']] = o
        print(r['id'], o)
    for o in out['rules'].values():
        # does the backtest still hold on clean opens: the close-model rules are judged on their clean-open replay
        c = o.get('clean') or o
        o['verdict'] = 'holds' if (c.get('clvRet') or 0) > 0 and (c.get('clvT') or 0) >= 2 else \
            'thin' if (c.get('clvRet') or 0) > 0 and (c.get('clvT') or 0) >= 1 else 'collapsed'
    with open(SEED, 'w') as f:
        json.dump(out, f, indent=1)


def close_clean(r, UN):
    """a close-model rule replayed on its held-out seasons without bad opens (#302). close_fit.json's held-out record
    kept them; this uses the final fit, so it is in sample: a check on how much the bad opens carried, not a record"""
    import close_model as CM
    sp, mk = r['sport'], r['mk']
    held = set(CM.SPEC[sp]['held'])
    lk, ck, mkey = ('To', 'T', 'tm') if mk == 'total' else ('Lo', 'L', 'm')
    xs, nbad = [], 0
    for g in C.load_wf(sp):
        if g['S'] not in held or g.get(lk) is None or g.get(ck) is None or g.get(mkey) is None:
            continue
        if mk == 'spread' and CM.mirrored(g[lk], g[ck]):
            continue
        try:
            e = CM.expected(sp, mk, {'o': g[lk], 'm': g[mkey], 'neutral': g.get('neutral', 0), 'cells': CM.game_cells(sp, mk, {**g, 'b2b': 0})})
        except Exception:
            continue
        if not e or e.get('E') is None or e['E'] <= r['tau']:
            continue
        if UN.bad_open(sp, mk, g):
            nbad += 1
            continue
        xs.append(C.ret(sp, mk, e['side'], g[lk], -110, g[ck]))
    m, t, _ = mean_t(xs)
    return {'clvN': len(xs), 'clvRet': m, 'clvT': t, 'dropped': nbad, 'inSample': True}


def test():
    r = {'type': 'gap', 'x': 4, 'cap': 10, 'mk': 'total'}
    assert rule_side(r, 230, 235) == ('under', 5)
    assert rule_side(r, 230, 232) == (None, 2)
    assert rule_side(r, 220, 235)[0] is None          # past the cap
    r = {'type': 'gap', 'x': 3, 'cap': 8, 'mk': 'spread'}
    assert rule_side(r, 6.7, 1.5)[0] == 'home'
    d = {'type': 'dog', 'x': 4, 'cap': 11, 'mk': 'spread'}
    assert rule_side(d, -2, 3)[0] == 'away'           # home favored by 3, model has the away side winning by 2
    assert rule_side(d, 1, 3)[0] is None
    b = {'mk': 'spread', 'side': 'home', 'line': 3.0, 'price': -110, 'stake': 2.0}
    settle(b, (80, 75))
    assert b['res'] == 'w' and abs(b['profit'] - 2 * 100 / 110) < 1e-3
    b = {'mk': 'spread', 'side': 'away', 'line': 3.0, 'price': -110, 'stake': 1.0}
    settle(b, (78, 75))
    assert b['res'] == 'p' and b['profit'] == 0
    assert bet_text({'h': 'ORL', 'a': 'ATL'}, 'spread', 'home', 2.5, -108) == 'ORL -2.5 -108'
    assert bet_text({'h': 'ORL', 'a': 'ATL'}, 'spread', 'away', 2.5, -112) == 'ATL +2.5 -112'
    c = icc([{'slate': s, 'clvRet': v} for s, v in (('a', .1), ('a', .1), ('b', -.1), ('b', -.1), ('c', 0), ('c', 0.01))])
    assert c['rho'] > 0.8 and c['nEff'] < 4, c
    print('paper book: ok')


if __name__ == '__main__':
    a = sys.argv[1:]
    if a and a[0] == '--seed':
        seed()
    elif a and a[0] == '--test':
        test()
    else:
        build()
