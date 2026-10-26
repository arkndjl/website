#!/usr/bin/env python3
"""1NT economy gameplan from parsed demos (research/esea_econ.json.gz, scripts/esea_econ_fetch.py) ->
data/esea_econ.json.

Buy classes from team equipment after buying (five players): pistol (rounds 1 and 13), eco < $5,000,
force $5,000-19,999, full >= $20,000. Splits per team and map: pistol win %, pistol conversion (won the
pistol, won the next round), full v full, anti-eco (full v eco/force), force v full, eco v full.

The decision: in a round where a team cannot afford a full buy (bank + kept equipment < $20,000), force or
save. Two-round value of each choice:
    V(save)  = p_eco   + p_eco   * c[eco,win]   + (1 - p_eco)   * c[eco,loss]
    V(force) = p_force + p_force * c[force,win] + (1 - p_force) * c[force,loss]
p = win probability this round against a full buy, c = win probability of the next round given the
choice and its result (league, measured on decision rounds). Team terms shift p and c on the logit
scale, shrunk to the league (ridge). gain = V(force) - V(save) in rounds per decision; aggressive above
+.03, conservative below -.03, else neutral.

Out of sample, leave-one-day-out: (1) do team buy-class terms beat league class rates on held-out
rounds (log loss, paired t)? (2) on held-out decision rounds, does the predicted gain sort the realized
two-round result of forcing vs saving (rounds won ~ force + force x gain)? A term ships only if it wins.

  python3 scripts/esea_econ.py [--synthetic]
"""
import gzip, json, math, sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / 'research' / 'esea_econ.json.gz'
OUT = ROOT / 'data' / 'esea_econ.json'
TEAM = '1NT'
ECO, FULL = 5000, 20000
LAM = 8.0          # ridge on team terms (logit units), refit below if a lower value wins out of sample
CUT = 0.03         # rounds per decision for an aggressive / conservative call


def cls(rn, eq):
    if rn in (1, 13):
        return 'pistol'
    return 'eco' if eq < ECO else 'full' if eq >= FULL else 'force'


def rows_of(maps):
    """One row per team per round: team, opp, map, day, round, side, class, opp class, won, broke, next won."""
    out = []
    for m in maps:
        # fold: match day when known, else the map itself
        day = m['at'] // 86400 if m.get('at') else 'm' + str(m.get('hash') or m.get('id'))
        rs = {r[0]: r for r in m['rounds']}
        for r in m['rounds']:
            rn, side1, b1, b2, k1, k2, e1, e2, w = r[:9]
            for me, (t, o, side, bank, kept, eq, eqo) in enumerate(((m['f1'], m['f2'], side1, b1, k1, e1, e2), (m['f2'], m['f1'], 5 - side1, b2, k2, e2, e1))):
                won = int(w == me + 1)
                nx = rs.get(rn + 1)
                nxt = None if nx is None or rn in (12, 24) else int(nx[8] == me + 1)
                out.append(dict(t=t, o=o, map=m['map'], day=day, rn=rn, side=side, c=cls(rn, eq), co=cls(rn, eqo), won=won,
                                broke=rn not in (1, 13) and bank + kept < FULL, nxt=nxt, prev=rs.get(rn - 1)))
    return out


def logit(p):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def sig(x):
    return 1 / (1 + math.exp(-x))


def base_rates(rows):
    """League win % by (class, opp class, side), Laplace-smoothed."""
    n, w = defaultdict(float), defaultdict(float)
    for r in rows:
        k = (r['c'], r['co'], r['side'])
        n[k] += 1; w[k] += r['won']
    return {k: (w[k] + 1) / (n[k] + 2) for k in n}


def role(c):
    return 'buy' if c == 'full' else 'broke' if c in ('eco', 'force') else 'pistol'


def fit_team(rows, base, lam=LAM, iters=25):
    """Ridge logistic team terms by role (buy / broke / pistol) on offence (own class) and defence (opp class),
    offset by the league class rate. Diagonal Newton steps."""
    keys, ix = [], {}

    def k(x):
        if x not in ix:
            ix[x] = len(keys); keys.append(x)
        return ix[x]
    io = np.array([k(('o', r['t'], role(r['c']))) for r in rows])
    idf = np.array([k(('d', r['o'], role(r['co']))) for r in rows])
    x0 = np.array([logit(base.get((r['c'], r['co'], r['side']), .5)) for r in rows])
    y = np.array([r['won'] for r in rows], float)
    eff, n = np.zeros(len(keys)), len(keys)
    for _ in range(iters):
        pr = 1 / (1 + np.exp(-(x0 + eff[io] - eff[idf])))
        res, w = y - pr, pr * (1 - pr)
        g = np.bincount(io, res, n) - np.bincount(idf, res, n) - lam * eff
        h = np.bincount(io, w, n) + np.bincount(idf, w, n) + lam
        eff += g / h
    return dict(zip(keys, eff.tolist()))


def pred(r, base, eff):
    x = logit(base.get((r['c'], r['co'], r['side']), .5))
    if eff:
        x += eff.get(('o', r['t'], role(r['c'])), 0) - eff.get(('d', r['o'], role(r['co'])), 0)
    return sig(x)


def ll(y, p):
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def tstat(d):
    d = np.asarray(d, float)
    return float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))) if len(d) > 2 and d.std() > 0 else 0.0


def continuation(rows):
    """c[choice][result]: next-round win % after a decision round, league."""
    n, w = defaultdict(float), defaultdict(float)
    for r in rows:
        if r['broke'] and r['co'] == 'full' and r['c'] in ('eco', 'force') and r['nxt'] is not None:
            k = (r['c'], r['won'])
            n[k] += 1; w[k] += r['nxt']
    return {k: (w[k] + 1) / (n[k] + 2) for k in n}


def gain(t, o, side, base, eff, cont):
    """V(force) - V(save) for team t against a full-buying o; team terms shift this round and the next."""
    def p(c, co):
        return pred(dict(t=t, o=o, c=c, co=co, side=side), base, eff)
    out = {}
    for c in ('eco', 'force'):
        pc = p(c, 'full')
        # next round: after a win the opponent is broken (we buy into them); after a loss we are still broke
        shift_w = logit(p('full', 'force')) - logit(sig(logit(base.get(('full', 'force', side), .5))))
        shift_l = logit(p('eco', 'full')) - logit(sig(logit(base.get(('eco', 'full', side), .5))))
        cw = sig(logit(cont.get((c, 1), .5)) + shift_w)
        cl = sig(logit(cont.get((c, 0), .5)) + shift_l)
        out[c] = pc + pc * cw + (1 - pc) * cl
    return out['force'] - out['eco']


def backtest(rows):
    days = sorted({r['day'] for r in rows})
    d_team, d_rule, by_lam = [], [], {}
    for lam in (2.0, 8.0, 32.0):
        dd = []
        for day in days:
            tr = [r for r in rows if r['day'] != day]
            te = [r for r in rows if r['day'] == day]
            if not te:
                continue
            b = base_rates(tr); e = fit_team(tr, b, lam)
            dd += [ll(r['won'], pred(r, b, e)) - ll(r['won'], pred(r, b, None)) for r in te]
        by_lam[lam] = (float(np.mean(dd)), tstat(dd), len(dd))
    lam = min(by_lam, key=lambda k: by_lam[k][0])
    xs, ys = [], []
    for day in days:
        tr = [r for r in rows if r['day'] != day]
        te = [r for r in rows if r['day'] == day and r['broke'] and r['co'] == 'full' and r['c'] in ('eco', 'force') and r['nxt'] is not None]
        if not te:
            continue
        b = base_rates(tr); e = fit_team(tr, b, lam); cont = continuation(tr)
        for r in te:
            g = gain(r['t'], r['o'], r['side'], b, e, cont)
            f = int(r['c'] == 'force')
            xs.append([1, f, f * g, g]); ys.append(r['won'] + r['nxt'])
    rule = None
    if len(ys) > 30:
        X, y = np.array(xs), np.array(ys, float)
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        res = y - X @ beta
        cov = np.linalg.inv(X.T @ X) * (res @ res) / (len(y) - X.shape[1])
        rule = dict(n=len(y), force=float(beta[1]), force_x_gain=float(beta[2]), t=float(beta[2] / math.sqrt(cov[2, 2])))
    return dict(lam=lam, team_terms={str(k): dict(d_ll=v[0], t=v[1], n=v[2]) for k, v in by_lam.items()}, rule=rule)


def splits(rows, t, mp=None):
    rr = [r for r in rows if r['t'] == t and (mp is None or r['map'] == mp)]

    def rate(f):
        x = [r['won'] for r in rr if f(r)]
        return [sum(x), len(x)]
    pist = [r for r in rr if r['c'] == 'pistol']
    conv = [r['nxt'] for r in pist if r['won'] and r['nxt'] is not None]
    brk = [r['nxt'] for r in pist if not r['won'] and r['nxt'] is not None]
    return dict(pistol=rate(lambda r: r['c'] == 'pistol'), conv=[sum(conv), len(conv)], brk=[sum(brk), len(brk)],
                ff=rate(lambda r: r['c'] == 'full' and r['co'] == 'full'), anti=rate(lambda r: r['c'] == 'full' and r['co'] in ('eco', 'force')),
                force=rate(lambda r: r['c'] == 'force' and r['co'] == 'full'), eco=rate(lambda r: r['c'] == 'eco' and r['co'] == 'full'),
                force_rate=[sum(r['c'] == 'force' for r in rr if r['broke'] and r['co'] == 'full'), sum(r['broke'] and r['co'] == 'full' and r['c'] in ('eco', 'force') for r in rr)])


def synthetic(nteams=24, nmaps=900, seed=7):
    """Fake league for a smoke test only (never written to data/)."""
    rng = np.random.default_rng(seed)
    teams = [f'T{i}' for i in range(nteams - 1)] + [TEAM]
    sk = {t: rng.normal(0, .3) for t in teams}
    maps = []
    for i in range(nmaps):
        a, b = rng.choice(teams, 2, replace=False)
        money = {a: 800 * 5, b: 800 * 5}
        rounds, s = [], {a: 0, b: 0}
        rn, side_a = 1, 3
        while max(s.values()) < 13 and rn <= 30:
            if rn == 13:
                side_a = 5 - side_a; money = {a: 4000, b: 4000}
            eq = {}
            for t in (a, b):
                if rn in (1, 13):
                    eq[t] = 3800
                elif money[t] >= 22000:
                    eq[t] = 22000 + rng.integers(0, 4000)
                elif rng.random() < .4:
                    eq[t] = max(5000, min(money[t], 15000))
                else:
                    eq[t] = 2000
            x = sk[a] - sk[b] + 1.6 * math.tanh((eq[a] - eq[b]) / 12000) + (.15 if side_a == 3 else -.15)
            wa = rng.random() < sig(x)
            rounds.append([rn, side_a, money[a], money[b], 0, 0, eq[a], eq[b], 1 if wa else 2, ''])
            for t, won in ((a, wa), (b, not wa)):
                kept = eq[t] * .6 if won else 0
                money[t] = min(80000, money[t] - min(eq[t], money[t]) + (16000 if won else 9500) + kept)
                s[t] += won
            rn += 1
        maps.append(dict(id=f'm{i}', n=0, at=1.75e9 + i * 86400 // 9, map=rng.choice(['mirage', 'nuke', 'ancient']), f1=a, f2=b, n1=a, n2=b, rounds=rounds))
    return maps


def main():
    syn = '--synthetic' in sys.argv
    if syn:
        maps = synthetic()
    else:
        if not SRC.exists():
            print(f'{SRC.relative_to(ROOT)} missing: run .github/workflows/esea-econ.yml first'); return
        maps = json.load(gzip.open(SRC))['maps']
    if not maps:
        print('no parsed maps'); return
    name = {}
    for m in maps:
        name[m['f1']] = m.get('n1', m['f1']); name[m['f2']] = m.get('n2', m['f2'])
    rows = rows_of(maps)
    us = next((k for k, v in name.items() if v == TEAM), None)
    print(f'{len(maps)} maps, {len(rows)} team-rounds, {sum(r["broke"] and r["co"] == "full" and r["c"] in ("eco", "force") for r in rows)} decision rounds')
    bt = backtest(rows)
    print(json.dumps(bt, indent=1))
    base = base_rates(rows)
    lam = bt['lam']
    team_ok = bt['team_terms'][str(lam)]['t'] < -1.645
    eff = fit_team(rows, base, lam) if team_ok else {}
    cont = continuation(rows)
    plan = []
    if us:
        opps = sorted({r['o'] for r in rows if r['t'] == us}, key=lambda o: name[o])
        for o in opps:
            for mp in sorted({m['map'] for m in maps}):
                g = np.mean([gain(us, o, s, base, eff, cont) for s in (2, 3)])
                call = 'aggressive' if g >= CUT else 'conservative' if g <= -CUT else 'neutral'
                plan.append(dict(opp=name[o], map=mp, gain=round(float(g), 3), call=call, opp_splits=splits(rows, o, mp)))
    out = dict(asof=maps[-1].get('at'), maps=len(maps), team_rounds=len(rows), cut=CUT, classes=dict(eco=ECO, full=FULL),
               league={f'{c}|{co}|{s}': round(p, 3) for (c, co, s), p in sorted(base.items())},
               continuation={f'{c}|{w}': round(p, 3) for (c, w), p in cont.items()}, backtest=bt, team_terms_used=team_ok,
               ours=splits(rows, us) if us else None, plan=plan)
    if syn:
        print(json.dumps({k: out[k] for k in ('continuation', 'ours')}, indent=1, default=lambda o: o.item())); print(plan[:3]); return
    OUT.write_text(json.dumps(out, separators=(',', ':'), default=lambda o: o.item()))
    print(f'wrote {OUT.relative_to(ROOT)}')


main()
