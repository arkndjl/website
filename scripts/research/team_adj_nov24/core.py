"""Shared harness for the BPM-style team adjustment (scripts/nba_rxpm_research.py, ported Nov 24 2026).

A sport supplies, per season n:
  parts[n]  : list of (pid, team, exposure)          one row a player-team stint (minutes, ice time, snaps ...)
  val[n]    : {pid: rate}                             the descriptive metric a unit of exposure (season mean over stints)
  team[n]   : {team: (result, games)}                 team result total over the season, in the sport's result units
  grp[n]    : {pid: group}  (optional)                fill for players with no season-n value is the mean rate of
                                                      low-exposure players in the same group (as the NBA harness)
Adjustment: centred result/games = b x centred (sum rate x exposure)/games (centred within league-season groups), b fit pooled on the same seasons (descriptive, so
same-season fitting is fine); each team's players then move by one amount a unit of exposure so the fitted line hits the
team's centred result exactly (league offsets, e.g. soccer's league strength, stay); a mover takes his stints' shifts weighted by exposure.
Tests (as NBA):
  describe : same-season team R2 (squared correlation) of summed values vs result a game (-> 1 by construction)
  predict  : season-n rates x season n+1 exposure -> n+1 team result a game, pooled R2 over pairs  (must not fall)
  playerR  : season-n rate vs season n+1 UNADJUSTED rate, weighted by n+1 exposure, min exposure  (may fall <= .01)
  net      : optional {side key: team}: values shift per side, team tests sum the sides
  pk       : predictor rate shrunk v x E / (E + pk) on season-n exposure E (base and adjusted alike)
  bootstrap over pairs (P better) and pairs better."""
from collections import defaultdict
import numpy as np


def sums(parts, val, fill):
    s, e = defaultdict(float), defaultdict(float)
    for pid, t, x in parts:
        s[t] += val.get(pid, fill.get(pid, 0.0)) * x; e[t] += x
    return s, e


def centred(D, n, val, fill=None):
    """[(team, value a game, result a game)] centred within the season's groups (league-season; one group if none)"""
    s, _ = sums(D['parts'], val, fill or {})
    cg = D.get('cg', {})
    rows = [(t, s[t] / g, y / g, cg.get(t, 0)) for t, (y, g) in D['team'].items() if t in s and g]
    out = []
    for G in set(r[3] for r in rows):
        rr = [r for r in rows if r[3] == G]
        if len(rr) < 2: continue
        mx, my = np.mean([r[1] for r in rr]), np.mean([r[2] for r in rr])
        out += [(t, x - mx, y - my, mx) for t, x, y, _ in rr]
    return out


def net(rows, nm):
    """sum per-side rows (BPM adjusts O and D apart) into team rows; nm: side key -> team"""
    if not nm: return [(x, y) for t, x, y, _ in rows]
    a = defaultdict(lambda: [0.0, 0.0])
    for t, x, y, _ in rows: a[nm[t]][0] += x; a[nm[t]][1] += y
    return [tuple(v) for v in a.values()]


def fit_line(D):
    """slope b of centred result a game on centred summed value a game, pooled over seasons"""
    xs, ys = [], []
    for n in D:
        for t, x, y, _ in centred(D[n], n, D[n]['val']): xs.append(x); ys.append(y)
    return 0.0, float(np.polyfit(xs, ys, 1)[0])


def adjust(Dn, n, b):
    """each team's players move by one amount a unit of exposure so its centred value a game = centred result / b"""
    val = Dn['val']; _, e = sums(Dn['parts'], val, {})
    d = {t: (y / b - x) * Dn['team'][t][1] / e[t] for t, x, y, _ in centred(Dn, n, val) if e[t]}
    num, den = defaultdict(float), defaultdict(float)
    for pid, t, x in Dn['parts']:
        if t in d and pid in val: num[pid] += d[t] * x; den[pid] += x
    return {pid: v + (num[pid] / den[pid] if den[pid] else 0.0) for pid, v in val.items()}


def r2(x, y): return float(np.corrcoef(x, y)[0, 1] ** 2) if len(x) > 2 else float('nan')


def wcorr(x, y, w):
    x, y, w = map(np.asarray, (x, y, w)); mx, my = np.average(x, weights=w), np.average(y, weights=w)
    return float(np.average((x - mx) * (y - my), weights=w) / np.sqrt(np.average((x - mx) ** 2, weights=w) * np.average((y - my) ** 2, weights=w)))


def fillv(val, expo, grp, lo):
    by = defaultdict(list)
    for pid, v in val.items():
        if expo.get(pid, 0) < lo: by[grp.get(pid)].append(v)
    allv = [v for l in by.values() for v in l] or [0.0]
    return {g: float(np.mean(l)) for g, l in by.items()}, float(np.mean(allv))


def run(D, pairs, lo_fill, min_next, label='', pk=0.0, PD=None):
    """D[n] = dict(parts, val, team, grp?, cg?, net?); pairs = n with n and n+1 in D. PD (optional) = {n: (Dn, Dn1)}: a
    season's data as seen by pair n (NFL: XV weights fit without n and n+1), else (D[n], D[n+1])."""
    PD = PD or {n: (D[n], D[n + 1]) for n in pairs}
    a, b = fit_line(D)
    out = {'line': {'b': round(b, 4)}, 'pairs': pairs}
    rows = {}
    for k in ('base', 'adj'):
        V = (lambda Dn, n: Dn['val']) if k == 'base' else (lambda Dn, n: adjust(Dn, n, b))
        dx, dy = [], []
        for n in D:
            for x, y in net(centred(D[n], n, V(D[n], n)), D[n].get('net')): dx.append(x); dy.append(y)
        per, px, py, pw = {}, [], [], []
        for n in pairs:
            Dn, nx = PD[n]; vv = V(Dn, n); expo = defaultdict(float)
            for pid, t, x in Dn['parts']: expo[pid] += x
            vn = {pid: v * expo[pid] / (expo[pid] + pk) for pid, v in vv.items()} if pk else vv
            gf, af = fillv(vn, expo, Dn.get('grp', {}), lo_fill)
            g1 = nx.get('grp', {})
            fill = {pid: gf.get(g1.get(pid), af) for pid, t, x in nx['parts'] if pid not in vn}
            per[n] = net(centred(nx, n + 1, vn, fill), nx.get('net'))
            e1 = defaultdict(float)
            for pid, t, x in nx['parts']: e1[pid] += x
            for pid, x in e1.items():
                if x >= min_next and pid in vn and pid in nx['val']:
                    px.append(vn[pid]); py.append(nx['val'][pid]); pw.append(x)
        allp = [r for n in pairs for r in per[n]]
        rows[k] = per
        out[k] = {'describe': round(r2(dx, dy), 4), 'predict': round(r2(*zip(*allp)), 4), 'playerR': round(wcorr(px, py, pw), 4),
                  'nPlayers': len(px), 'teamSeasons': len(allp)}
        out[k]['byPair'] = {n: round(r2(*zip(*per[n])), 4) for n in pairs}
        out[k]['rByPair'] = {n: round(float(np.corrcoef(*zip(*per[n]))[0, 1]), 3) for n in pairs}
    rng = np.random.default_rng(0)
    f = lambda per, pp: r2(*zip(*[r for n in pp for r in per[n]]))
    bs = [rng.choice(pairs, len(pairs)) for _ in range(2000)]
    out['pBetter'] = round(float(np.mean([f(rows['adj'], p) > f(rows['base'], p) for p in bs])), 3)
    out['pairsBetter'] = int(sum(out['adj']['byPair'][n] > out['base']['byPair'][n] for n in pairs))
    out['pass'] = bool(out['adj']['predict'] >= out['base']['predict'] and out['adj']['playerR'] >= out['base']['playerR'] - .01)
    print(label, {k: out[k] for k in ('line', 'base', 'adj', 'pBetter', 'pairsBetter', 'pass')}, flush=True)
    return out
