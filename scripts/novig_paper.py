#!/usr/bin/env python3
"""Place every open pick on Novig's Paper exchange and log the fills (Noah, Nov 1 2026: "Paper auto-betting on Novig").

PAPER ONLY. The host is fixed to https://api.paper.novig.com (play money, no location check). There is no switch to the
real exchange: a real-money placer would be a separate decision and a separate script.

Each run (the odds-snap workflow, after the picks refresh):
  1. reads the open picks the reminders send (scripts/bets_today.py rows: Picks tab logs, unstarted, not a pass);
  2. finds each pick's market on Paper: the moneyline, the spread or total rung at the pick's current line, a player
     prop at its line, a tennis match;
  3. sends one IOC buy per pick at most once (clientId = uuid5 of the pick key; a pick is never sent twice, checked
     against the ledger and the account's own fills): size = Kelly % of the bankroll (cash + cost of open positions),
     limit = the lower of the model's chance (pDU) and the quoted price + 2 points, snapped down to Novig's grid;
  4. reads the order's fills (contracts, cost, fee) and records them;
  5. once the pick is graded on the Picks tab, scores the fill: slippage (fill price minus the posted and the quoted
     price, in chance points), CLV-implied return at the fill price against the same close the Picks tab uses
     (clv.ret), and the result in dollars.
Ledger and summary: data/novig_paper.json.

Keys (repository secrets, never in the repo): NOVIG_PAPER_KEY_ID (a Paper trading key id) and NOVIG_PAPER_PEM (its
private key, PKCS#8 PEM). Without them the run prints a line and exits 0.

  python3 scripts/novig_paper.py                 # place new picks, update fills and grades (needs the secrets)
  python3 scripts/novig_paper.py --dry-run       # show what it would send; no orders (no keys needed)
  python3 scripts/novig_paper.py --grade-only    # update grades and the summary; no orders
  python3 scripts/novig_paper.py --test          # signer against Novig's published test vectors + unit checks
  python3 scripts/novig_paper.py --setup --mgmt-key-id ID --mgmt-pem FILE [--fund 10000]
        # one time, on your own computer: opens a Paper subaccount with a new trading key, funds it, prints the
        # two secrets to add (the management key never goes to GitHub)
"""
import argparse
import base64
import datetime
import hashlib
import json
import math
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bets_today  # noqa: E402
import clv  # noqa: E402
import names  # noqa: E402
import novig  # noqa: E402

HOST = 'https://api.paper.novig.com'          # Paper only. Never change this to the real exchange.
assert 'paper' in HOST
OUT = os.path.join(HERE, '..', 'data', 'novig_paper.json')
VECTORS = os.path.join(HERE, 'data', 'novig_signing_vectors.json')
NS = uuid.UUID('6f1c1d1e-7a43-4c5e-9a8e-2f1b0c0d1a01')
SLIP = 0.02          # the limit sits at most 2 chance points above the quoted price
LEAGUE = {'cfb': 'NCAAF', 'nfl': 'NFL', 'cbb': 'NCAAB', 'nba': 'NBA', 'nflprops': 'NFL'}
PROP_TYPE = {v: k for k, v in novig.NFL_PROPS.items()}
TEAM = ('cfb', 'nfl', 'cbb', 'nba')
UA = 'arkndjl.net arkboard (paper trading)'
KEEP_DAYS = 90       # ledger rows kept by start date


# ------------------------------------------------------------------ NOVIG-V3 signing (docs.novig.com/api/signing)

def _enc(s):
    out = []
    for b in s:
        c = chr(b)
        out.append(c if (c.isascii() and c.isalnum()) or c in '-._~' else f'%{b:02X}')
    return ''.join(out)


def _dec(s):
    raw, out, i = s.encode(), bytearray(), 0
    while i < len(raw):
        hx = raw[i + 1:i + 3]
        if raw[i] == 0x25 and len(hx) == 2 and all(chr(x) in '0123456789abcdefABCDEF' for x in hx):
            out.append(int(raw[i + 1:i + 3], 16))
            i += 3
        else:
            out.append(raw[i])
            i += 1
    return bytes(out)


def canon_query(q):
    pairs = []
    for part in q.split('&'):
        if not part:
            continue
        k, _, v = part.partition('=')
        pairs.append((_enc(_dec(k)), _enc(_dec(v))))
    pairs.sort(key=lambda kv: (kv[0].encode(), kv[1].encode()))
    return '&'.join(f'{k}={v}' for k, v in pairs)


def to_sign(ts, method, path, query, body):
    return '\n'.join(['NOVIG-V3', str(ts), method.upper(), path, canon_query(query), hashlib.sha256(body).hexdigest()])


# Ed25519 (RFC 8032). The cryptography package when it is installed, else this pure-Python fallback (a few ms a
# signature; the runner's system Python may not carry cryptography).
_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_GY = 4 * pow(5, _P - 2, _P) % _P


def _xr(y, sign):
    x2 = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * pow(2, (_P - 1) // 4, _P) % _P
    return _P - x if x & 1 != sign else x


_G = (_xr(_GY, 0), _GY, 1, _xr(_GY, 0) * _GY % _P)


def _add(a, b):
    A = (a[1] - a[0]) * (b[1] - b[0]) % _P
    B = (a[1] + a[0]) * (b[1] + b[0]) % _P
    C = 2 * a[3] * b[3] * _D % _P
    Dd = 2 * a[2] * b[2] % _P
    E, F, G, H = B - A, Dd - C, Dd + C, B + A
    return (E * F % _P, G * H % _P, F * G % _P, E * H % _P)


def _mul(s, p):
    q = (0, 1, 1, 0)
    while s:
        if s & 1:
            q = _add(q, p)
        p = _add(p, p)
        s >>= 1
    return q


def _pt(p):
    zi = pow(p[2], _P - 2, _P)
    x, y = p[0] * zi % _P, p[1] * zi % _P
    return (y | ((x & 1) << 255)).to_bytes(32, 'little')


def _h(m):
    return int.from_bytes(hashlib.sha512(m).digest(), 'little')


def _sign_pure(seed, msg):
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], 'little')
    a &= (1 << 254) - 8
    a |= 1 << 254
    A = _pt(_mul(a, _G))
    r = _h(h[32:] + msg) % _L
    R = _pt(_mul(r, _G))
    s = (r + _h(R + A + msg) * a) % _L
    return R + s.to_bytes(32, 'little')


def seed_of(pem):
    """the 32-byte Ed25519 seed from a PKCS#8 PEM"""
    der = base64.b64decode(''.join(x for x in pem.strip().splitlines() if not x.startswith('-----')))
    if len(der) != 48 or der[:16] != bytes.fromhex('302e020100300506032b657004220420'):
        raise ValueError('not an Ed25519 PKCS#8 key (Novig keys made in the browser can be P-256: make an Ed25519 one)')
    return der[16:]


def sign(pem, msg):
    seed = seed_of(pem)
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        return Ed25519PrivateKey.from_private_bytes(seed).sign(msg)
    except ImportError:
        return _sign_pure(seed, msg)


class Client:
    def __init__(self, key_id, pem):
        self.key_id, self.pem = key_id, pem

    def call(self, method, path, query=None, body=None):
        q = urllib.parse.urlencode(query or {}, quote_via=urllib.parse.quote)
        data = b'' if body is None else json.dumps(body, separators=(',', ':')).encode()
        ts = int(time.time() * 1000)
        sig = base64.b64encode(sign(self.pem, to_sign(ts, method, path, q, data).encode())).decode()
        req = urllib.request.Request(HOST + path + (f'?{q}' if q else ''), data=data if body is not None else None, method=method,
                                     headers={'Novig-Key-Id': self.key_id, 'Novig-Timestamp': str(ts), 'Novig-Signature': sig,
                                              'Content-Type': 'application/json', 'User-Agent': UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                txt = r.read().decode()
                return r.status, (json.loads(txt) if txt else None)
        except urllib.error.HTTPError as e:
            txt = e.read().decode(errors='replace')
            try:
                return e.code, json.loads(txt)
            except json.JSONDecodeError:
                return e.code, {'error': txt[:300]}


# ------------------------------------------------------------------ prices

def grid_down(p):
    """snap a chance down to Novig's price grid (.001 below .05 and above .95, .005 between)"""
    m = math.floor(p * 1000 + 1e-9)
    if m < 1:
        return None
    if 51 <= m <= 949:
        m -= m % 5
    return f'{min(m, 999) / 1000:.3f}'


def prob(american):
    a = float(american)
    return -a / (-a + 100) if a < 0 else 100 / (a + 100)


def american(p):
    return -100 * p / (1 - p) if p >= .5 else 100 * (1 - p) / p


# ------------------------------------------------------------------ the Paper catalog (public, no key)

def get(path, **q):
    url = f"{HOST}/v3/public/catalog/{path}?{urllib.parse.urlencode({k: v for k, v in q.items() if v is not None})}"
    for i in range(3):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=30))
        except Exception:
            if i == 2:
                raise
            time.sleep(2 * (i + 1))


def pages(path, **q):
    items, after = [], None
    while True:
        d = get(path, limit=5000 if path == 'markets' else 500, after=after, **q)
        items += d.get('items') or []
        after = d.get('next')
        if not after:
            return items


def ask(m, i):
    """the ask on outcome i of a two-outcome market: 1 - the other side's best bid"""
    o = m['outcomes'][1 - i]
    b = novig.bid(o)
    return None if b is None else round(1 - b, 4)


class Catalog:
    """Paper markets per sport, keyed to ESPN game ids through novig.match (team names and a start within 3 hours)"""

    def __init__(self):
        self.cache = {}

    def team(self, sport):
        if sport in self.cache:
            return self.cache[sport]
        lg = LEAGUE[sport]
        base = 'nfl' if sport == 'nflprops' else sport
        ev = {e['eventId']: e for e in pages('events', league=lg, status='OPEN_PREGAME')}
        types = ','.join(novig.NFL_PROPS) if sport == 'nflprops' else 'MONEY,SPREAD,TOTAL'
        mk = pages('markets', league=lg, marketType=types, eventStatus='OPEN_PREGAME')
        nv = {}
        for eid, e in ev.items():
            away, _, home = (e.get('description') or '').partition(' @ ')
            if home:
                nv[eid] = {'h': home, 'a': away, 'k': datetime.datetime.fromtimestamp(e['startsTs'] / 1000, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
        espn = novig.espn_games(base, days=(0, 7))
        ids = novig.match(nv, espn)
        by = {}
        for m in mk:
            gid = ids.get(m.get('eventId'))
            if gid:
                by.setdefault(gid, []).append(m)
        self.cache[sport] = (by, {gid: espn[gid] for gid in by if gid in espn})
        return self.cache[sport]

    def tennis(self, tour):
        k = 'tennis-' + tour
        if k not in self.cache:
            lg = tour.upper()
            ev = {e['eventId']: e for e in pages('events', league=lg, status='OPEN_PREGAME')}
            mk = pages('markets', league=lg, marketType='MONEY', eventStatus='OPEN_PREGAME')
            out = []
            for m in mk:
                e, oc = ev.get(m.get('eventId')), m.get('outcomes') or []
                if not e or len(oc) != 2:
                    continue
                away, _, home = (e.get('description') or '').partition(' @ ')
                if home:
                    out.append((m, novig._full(home, oc[0].get('name')), novig._full(away, oc[1].get('name')), e['startsTs']))
            self.cache[k] = out
        return self.cache[k]


def find(cat, r):
    """(market, outcome index, line) on Paper for a bets_today row, or (None, reason, None)"""
    s, p, line = r['s'], r['pick'], r['at']
    if s == 'tennis':
        me = p['homeN'] if p['side'] == 'home' else p['awayN']
        op = p['awayN'] if p['side'] == 'home' else p['homeN']
        for m, b, a, _ in cat.tennis(p.get('tour') or 'atp'):
            for i, nm, other in ((0, b, a), (1, a, b)):
                if names.same(me, nm) and names.same(op, other):
                    return m, i, None
        return None, 'match not listed on Paper', None
    if s not in LEAGUE:
        return None, f'{s} not supported', None
    by, espn = cat.team(s)
    ms = by.get(str(p.get('espn') or p['id']))
    if not ms:
        return None, 'game not listed on Paper', None
    if p['mk'] == 'prop':
        typ = PROP_TYPE.get(p.get('stat'))
        for m in ms:
            if m.get('marketType') != typ or float(m.get('strike') or 'nan') != float(line):
                continue
            if names.same(p['player'], (m.get('description') or '').rsplit(' ', 2)[0]):
                over = (m['outcomes'][0].get('name') or '').lower().startswith('over')
                return m, (0 if over else 1) if p['side'] == 'over' else (1 if over else 0), line
        return None, f"no {line} rung for {p['player']}", None
    if p['mk'] == 'ml':
        for m in ms:
            if m.get('marketType') == 'MONEY' and len(m.get('outcomes') or []) == 2:
                return m, 0 if p['side'] == 'home' else 1, None       # outcome 0 is the home side (novig.games)
        return None, 'no moneyline on Paper', None
    if p['mk'] == 'total':
        for m in ms:
            if m.get('marketType') == 'TOTAL' and float(m.get('strike') or 'nan') == float(line):
                over = (m['outcomes'][0].get('name') or '').lower().startswith('over')
                return m, (0 if over else 1) if p['side'] == 'over' else (1 if over else 0), line
        return None, f'no total {line} rung on Paper', None
    for m in ms:      # spread: outcome 0 'HOME +h' is the home side at handicap h; the pick's line is -h
        if m.get('marketType') != 'SPREAD' or len(m.get('outcomes') or []) != 2:
            continue
        _, h = novig.handicap(m['outcomes'][0].get('name') or '')
        if h is not None and -h == float(line):
            return m, 0 if p['side'] == 'home' else 1, line
    return None, f'no spread {line} rung on Paper', None


# ------------------------------------------------------------------ ledger

def load_ledger():
    try:
        with open(OUT) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {'env': 'paper', 'bets': []}


def save(led):
    with open(OUT, 'w') as f:
        json.dump(led, f, indent=1, sort_keys=True)
        f.write('\n')


def body(led):
    return json.dumps({k: v for k, v in led.items() if k != 'asof'}, sort_keys=True)


def picks_rows(now, ref=None):
    """bets_today's open picks, with the raw pick attached"""
    out = []
    for s, _ in bets_today.SPORTS:
        d = bets_today.load(s, ref)
        if not d:
            continue
        by = {f"{s}:{p['id']}:{p['mk']}:{p['side']}": p for p in d.get('picks', [])}
        for r in bets_today.rows(ref, now, 12, 7):
            if r['key'] in by:
                p = by[r['key']]
                cur = p.get('now') or {}
                same = cur.get('mk', p['mk']) == p['mk']
                out.append({**r, 's': s, 'pick': p, 'at': (cur.get('line', p.get('line')) if same else p.get('line')),
                            'quote': float(cur.get('price', p['price']) if same else p['price'])})
    seen, uniq = set(), []
    for r in out:
        if r['key'] not in seen:
            seen.add(r['key'])
            uniq.append(r)
    return uniq


def bankroll(cl, key_id):
    st, b = cl.call('GET', f'/v3/account/subaccounts/{key_id}/balance')
    if st != 200:
        raise RuntimeError(f'balance {st} {b}')
    cash = float(b['balance'])
    st, pn = cl.call('GET', '/v3/portfolio/pnl')
    basis = float((pn or {}).get('basis') or 0) if st == 200 else 0.0
    return cash, basis


def known_clients(cl):
    st, d = cl.call('GET', '/v3/portfolio/fills', {'limit': 500})
    return {f.get('clientId') for f in (d or {}).get('items') or []} if st == 200 else set()


def fills_of(cl, order_id):
    st, d = cl.call('GET', '/v3/portfolio/fills', {'order': order_id, 'limit': 500})
    if st != 200:
        return None
    fs = (d or {}).get('items') or []
    qty = sum(int(f['qty']) for f in fs)
    cost = sum(float(f['cost']) for f in fs)
    fee = sum(float(f.get('fee') or 0) for f in fs)
    return {'qty': qty, 'cost': round(cost, 5), 'fee': round(fee, 5), 'px': round(cost * 100 / qty, 4) if qty else None, 'n': len(fs)}


def place(cl, led, rows, cash, basis, dry, now):
    done = {b['key'] for b in led['bets'] if b.get('status') not in ('retry', 'nomarket')}   # a game can list later
    tries = {b['key']: b.get('tries', 0) for b in led['bets']}
    sent = set() if dry else known_clients(cl)
    bank = cash + basis
    cat = Catalog()
    for r in rows:
        if r['key'] in done:
            continue
        cid = str(uuid.uuid5(NS, r['key']))
        p = r['pick']
        e = {'key': r['key'], 'cid': cid, 'sport': r['sport'], 'game': r['game'], 'bet': r['bet'], 'mk': p['mk'],
             'side': p['side'], 'kick': p['kick'], 'line': r['at'], 'posted': p['price'], 'quote': r['quote'],
             'kelly': r['kelly'], 'pDU': p.get('pDU', p.get('p')), 't': now.strftime('%Y-%m-%dT%H:%M:%SZ'), 'tries': tries.get(r['key'], 0) + 1}
        if cid in sent:
            e.update(status='placed', note='found in fills (ledger was missing it)')
        try:
            m, oi, _ = find(cat, r)
        except Exception as ex:
            print(f"  {r['key']}: catalog failed ({ex})")
            continue
        if m is None:
            e.update(status='nomarket', note=oi)
            print(f"  skip {r['bet']}: {oi}")
            if not dry:
                led['bets'] = [b for b in led['bets'] if b['key'] != r['key']] + [e]
            continue
        q = prob(r['quote'])
        lim = grid_down(min(e['pDU'] or q, q + SLIP))
        pa = ask(m, oi)
        stake = bank * r['kelly'] / 100
        qty = int(stake * 100 / float(lim)) if lim else 0
        e.update(market=m['marketId'], outcome=m['outcomes'][oi]['outcomeId'], oname=m['outcomes'][oi].get('name'), limit=lim,
                 ask=pa, stake=round(stake, 2), qty=qty, bank=round(bank, 2))
        if qty < 1 or not lim:
            e.update(status='nosize')
            led['bets'].append(e) if not dry else None
            continue
        print(f"  {'would send' if dry else 'send'} {r['sport']} {r['bet']}: {e['oname']} IOC {qty} @ <= {lim} (Paper ask {pa}, "
              f"quote {q:.3f}), ${stake:,.2f} = {r['kelly']}% of ${bank:,.2f}")
        if dry or e.get('status') == 'placed':
            if not dry:
                led['bets'].append(e)
            continue
        e['status'] = 'sending'
        led['bets'] = [b for b in led['bets'] if b['key'] != r['key']] + [e]
        save(led)               # on disk before the order goes out: a crash after here is never resent blind
        st, res = cl.call('POST', '/v3/orders', body={'clientId': cid, 'outcomeId': e['outcome'], 'price': lim, 'qty': qty, 'tif': 'IOC'})
        if st != 201:
            e.update(status='retry' if e['tries'] < 3 and st in (409, 423, 429, 503) else 'refused', http=st, note=str(res)[:200])
            print(f"    refused {st}: {res}")
            continue
        e.update(status='placed', order=res.get('orderId'))
        for _ in range(6):
            time.sleep(1)
            st, o = cl.call('GET', f"/v3/orders/{e['order']}")
            if st == 200 and o.get('status') in ('FILLED', 'CANCELED', 'REJECTED'):
                e['ostatus'] = o['status']
                break
        f = fills_of(cl, e['order'])
        if f:                   # every pick in one run is sized off the run's starting bankroll
            e['fill'] = f
        print(f"    {e.get('ostatus', 'pending')}: {f}")
        save(led)


# ------------------------------------------------------------------ grading

def graded_pick(key):
    s, pid, mk, side = key.split(':', 3)
    d = bets_today.load(s, None) or {}
    for p in (d.get('log') or []) + (d.get('recent') or []) + (d.get('picks') or []):
        if str(p['id']) == pid and p['mk'] == mk and p['side'] == side and (p.get('res') or p.get('clvRet') is not None):
            return s, p
    return s, None


def fill_ret(s, p, b, px):
    """CLV-implied return per $ at fill chance px, against the close the Picks tab used"""
    if p.get('close') is None:
        return None
    am = american(px)
    if s in TEAM:
        cml = tuple(p['closeML']) if p.get('closeML') and None not in p['closeML'] else None
        r = clv.ret(s, p['mk'], p['side'], b.get('line'), am, p['close'], cml)
        return None if r is None else round(r, 4)
    if s == 'tennis':
        return round(float(p['close']) / px - 1, 4)
    if p.get('clvRet') is not None and b.get('line') == p.get('line'):      # props: the pick's own close chance at its line
        w = (1 + p['clvRet']) / clv.dec(p['price'])
        return round(w / px - 1, 4)
    return None


def grade(led):
    for b in led['bets']:
        f = b.get('fill') or {}
        if not f.get('qty') or b.get('res'):
            continue
        s, p = graded_pick(b['key'])
        if not p:
            continue
        px = f['px']
        b['slip'] = round(px - prob(b['posted']), 4)
        b['slipQ'] = round(px - prob(b['quote']), 4)
        b['clvPick'] = p.get('clvRet')
        b['clvFill'] = fill_ret(s, p, b, px)
        if p.get('res') in ('w', 'l', 'p'):
            b['res'] = p['res']
            b['pnl'] = round({'w': f['qty'] / 100 - f['cost'], 'l': -f['cost'], 'p': 0.0}[p['res']] - f.get('fee', 0), 2)
        elif p.get('res') == 'void':                # walkover / didn't play: the stake comes back
            b['res'], b['pnl'] = 'void', round(-f.get('fee', 0), 2)


def summary(led, cash=None, basis=None):
    out = stats(led['bets'])
    out['bySport'] = {sp: stats([b for b in led['bets'] if b['sport'] == sp]) for sp in sorted({b['sport'] for b in led['bets']})}
    if cash is not None:
        out.update(cash=round(cash, 2), open=round(basis, 2), bank=round(cash + basis, 2))
    elif led.get('summary'):
        for k in ('cash', 'open', 'bank'):
            if k in led['summary']:
                out[k] = led['summary'][k]
    led['summary'] = out
    return out


def stats(bs):
    sent = [b for b in bs if b.get('order')]
    filled = [b for b in sent if (b.get('fill') or {}).get('qty')]
    want = sum(b['qty'] for b in sent)
    got = sum(b['fill']['qty'] for b in filled)

    def mean_t(xs):
        if not xs:
            return None, None
        m = sum(xs) / len(xs)
        if len(xs) < 2:
            return round(m, 4), None
        sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))
        return round(m, 4), (round(m / (sd / math.sqrt(len(xs))), 2) if sd else None)

    sl = [b['slip'] for b in filled if b.get('slip') is not None]
    sq = [b['slipQ'] for b in filled if b.get('slipQ') is not None]
    cf = [b['clvFill'] for b in filled if b.get('clvFill') is not None]
    cp = [b['clvPick'] for b in filled if b.get('clvFill') is not None and b.get('clvPick') is not None]
    done = [b for b in filled if b.get('res')]
    risk = sum(b['fill']['cost'] for b in done if b['res'] != 'void')
    pnl = sum(b['pnl'] for b in done)
    out = {'picks': len(bs), 'sent': len(sent), 'filled': len(filled), 'fillRate': round(got / want, 3) if want else None,
           'noMarket': sum(1 for b in bs if b.get('status') == 'nomarket'),
           'refused': sum(1 for b in bs if b.get('status') in ('refused', 'retry')),
           'slip': mean_t(sl)[0], 'slipQ': mean_t(sq)[0], 'clvN': len(cf), 'clvFill': mean_t(cf)[0], 'clvFillT': mean_t(cf)[1],
           'clvPick': mean_t(cp)[0], 'graded': len(done), 'risked': round(risk, 2), 'pnl': round(pnl, 2),
           'roi': round(pnl / risk, 4) if risk else None}
    return out


# ------------------------------------------------------------------ setup (run once on your own computer)

def setup(a):
    mg = Client(a.mgmt_key_id, open(a.mgmt_pem).read())
    st, e = mg.call('POST', '/v3/echo', body={'hello': 'paper'})
    if st != 200:
        sys.exit(f'echo failed ({st} {e}): check the key id, the PEM and that both are from paper.novig.com')
    pem = a.out_pem
    if not os.path.exists(pem):
        subprocess.run(['openssl', 'genpkey', '-algorithm', 'ed25519', '-out', pem], check=True)
        os.chmod(pem, 0o600)
    pub = subprocess.run(['openssl', 'pkey', '-in', pem, '-pubout'], check=True, capture_output=True, text=True).stdout
    st, sub = mg.call('POST', '/v3/account/subaccounts', body={'label': 'arkboard-paper', 'publicKey': pub, 'algorithm': 'Ed25519'})
    if st != 201:
        sys.exit(f'open subaccount failed ({st} {sub})')
    kid = sub['keyId']
    st, t = mg.call('POST', f'/v3/account/subaccounts/{kid}/transfer',
                    body={'direction': 'fund', 'amount': f'{a.fund:.5f}', 'clientTransferId': f'arkboard-paper-{kid[:8]}'})
    print(f'fund: {st} {t}')
    print(f'\nTrading key id: {kid}\nPrivate key: {pem}\n\nAdd both as repository secrets (github.com/arkndjl/website > Settings > '
          f'Secrets and variables > Actions), or with the GitHub CLI:\n  gh secret set NOVIG_PAPER_KEY_ID -R arkndjl/website -b {kid}\n'
          f'  gh secret set NOVIG_PAPER_PEM -R arkndjl/website < {pem}\nThen delete {pem} from this computer.')


# ------------------------------------------------------------------ tests

def test():
    v = json.load(open(VECTORS))
    for x in v['vectors']:
        i = x['input']
        s = to_sign(i['timestamp'], i['method'], i['path'], i['query'], i['body'].encode())
        assert s == x['string_to_sign'], (x['id'], s, x['string_to_sign'])
        assert base64.b64encode(_sign_pure(seed_of(v['key']), s.encode())).decode() == x['signature'], x['id']
        assert base64.b64encode(sign(v['key'], s.encode())).decode() == x['signature'], x['id']
    assert grid_down(.5098) == '0.505' and grid_down(.512) == '0.510' and grid_down(.0457) == '0.045' and grid_down(.9567) == '0.956'
    assert abs(prob(-104) - .5098) < 1e-4 and abs(prob(150) - .4) < 1e-9 and abs(american(.6) + 150) < 1e-9
    assert fill_ret('tennis', {'close': .615}, {}, .605) == round(.615 / .605 - 1, 4)
    b = {'line': 229.5}
    r = fill_ret('nba', {'mk': 'total', 'side': 'over', 'close': 229.5, 'line': 229.5, 'price': -104}, b, prob(-104))
    assert r is not None and abs(r - clv.ret('nba', 'total', 'over', 229.5, -104, 229.5)) < 1e-3
    print(f"novig_paper: {len(v['vectors'])} signing vectors and unit checks pass")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--grade-only', action='store_true')
    ap.add_argument('--test', action='store_true')
    ap.add_argument('--setup', action='store_true')
    ap.add_argument('--mgmt-key-id')
    ap.add_argument('--mgmt-pem')
    ap.add_argument('--out-pem', default='novig-paper-trading.pem')
    ap.add_argument('--fund', type=float, default=10000)
    a = ap.parse_args()
    if a.test:
        return test()
    if a.setup:
        return setup(a)
    now = datetime.datetime.now(datetime.timezone.utc)
    led = load_ledger()
    orig = body(led)
    kid, pem = os.environ.get('NOVIG_PAPER_KEY_ID'), os.environ.get('NOVIG_PAPER_PEM')
    if not (kid and pem) and not a.dry_run:
        grade(led)
        summary(led)
        if led['bets']:
            save(led)
        print('novig_paper: no NOVIG_PAPER_KEY_ID / NOVIG_PAPER_PEM secrets, no orders')
        return
    cl = Client(kid, pem) if kid and pem else None
    cash = basis = None
    if cl:
        cash, basis = bankroll(cl, kid)
        # orders sent earlier whose fills weren't read yet
        for b in led['bets']:
            if b.get('order') and b.get('fill') is None:
                b['fill'] = fills_of(cl, b['order'])
    if not a.grade_only:
        rows = picks_rows(now)
        print(f'novig_paper: {len(rows)} open picks, bankroll ${(cash or 10000) + (basis or 0):,.2f}')
        place(cl, led, rows, cash if cash is not None else 10000.0, basis or 0.0, a.dry_run, now)
    if a.dry_run:
        return
    grade(led)
    cut = (now - datetime.timedelta(days=KEEP_DAYS)).strftime('%Y-%m-%dT%H:%M')
    led['bets'] = [b for b in led['bets'] if (b.get('kick') or '') >= cut]
    s = summary(led, cash, basis)
    stamp = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    if orig != body(led):
        led['asof'] = stamp      # a run that changed nothing leaves the file alone (no commit, no site build)
        save(led)
    print('novig_paper:', s)


if __name__ == '__main__':
    main()
