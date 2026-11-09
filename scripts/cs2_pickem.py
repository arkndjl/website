#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Counter-Strike Major Pick'Em (the COUNTER-STRIKE ARKBOARD "pick'em" tab): the picks that give the best chance of
each Major coin tier, from the series model (scripts/cs2_model.py) through the Valve Swiss / bracket simulator
(scripts/cs2_events.py).

    python3 scripts/cs2_pickem.py --prep   # past stages' point-in-time logits -> scripts/data/cs2_pickem_prep.json.gz
    python3 scripts/cs2_pickem.py --fit    # backtest the pick policies on past stages -> data/cs2_pickem_fit.json
    live: cs2_model.build() calls live(logit, next stage) -> data/cs2_pickem.json

Pick'Em (Valve, Budapest 2025 / Singapore 2026 format): 11 challenges upgrade the coin (Bronze 1, Silver 4, Gold 8,
Diamond 11). Five are free (activate the pass; place the picks for Stages 1-3 and the playoffs), six are skill:
  - each Swiss stage: 10 picks, two to go 3-0, two to go 0-3, six to advance 3-1 or 3-2 (exact record: a 3-0 team in
    an advance slot scores nothing); 5 of 10 correct passes. Picks lock before the stage's first match and each
    stage is picked once its 16 teams and round-1 pairings are known.
  - playoffs: a full bracket (4 quarter-final, 2 semi-final winners, the champion); 2 QF, 1 SF and the final are
    three separate challenges.
So Silver is free, Gold = any 3 of the 6 skill challenges, Diamond = all 6.

Policy. A stage's picks change only that stage's chance (later fields and results do not depend on them), so for
every coin tier the best Swiss picks are the ones that maximize P(5+ correct) given what is known, NOT the ones
with the most expected correct picks. That chance is read off joint simulations (one row per simulated stage), so
the correlation between picks is kept: two 3-0 picks that meet in round 2 cannot both hit, a 3-0 pick and an
advance pick on the same path compete for the same wins. The bracket's three challenges do interact: its picks
maximize P(at least k of the three) for the k the coin still needs (k = 3 for Diamond).
"""
import gzip
import itertools
import json
import math
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cs2_events as E  # noqa: E402
from cs2_data import key  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PREP = ROOT / "scripts" / "data" / "cs2_pickem_prep.json.gz"
FIT = ROOT / "data" / "cs2_pickem_fit.json"
OUT = ROOT / "data" / "cs2_pickem.json"
NEED = 5
SLOTS = (("30", 2), ("03", 2), ("adv", 6))
CLS = {"30": 0, "adv": 1, "out": 2, "03": 3}
SPLIT = E.SPLIT
COIN = {"Bronze": 1, "Silver": 4, "Gold": 8, "Diamond": 11}
FREE = 5


# ---------------------------------------------------------------------------------------------------- simulation
def classes(W, L, teams):
    """record class per team: 0 = 3-0, 1 = 3-1 / 3-2, 2 = 2-3 / 1-3, 3 = 0-3."""
    return [0 if W[t] == 3 and L[t] == 0 else 1 if W[t] == 3 else 3 if W[t] == 0 else 2 for t in teams]


def sim_swiss(seeds, logit, r1, allbo3, n, sd, rng):
    """-> n x 16 record classes, columns in seed order."""
    known = [[(a, b, None) for a, b in r1]] if r1 else ()
    out = np.empty((n, len(seeds)), np.int8)
    for i in range(n):
        W, L, _ = E.swiss(seeds, E.noisy(logit, seeds, sd, rng), rng, known, allbo3)
        out[i] = classes(W, L, seeds)
    return out


def sim_bracket(qf, logit, n, sd, rng, bo_final=3):
    """qf: four (a, b) quarter-finals in bracket order (winners of 0/1 meet, 2/3 meet). -> n x 7 winners (QF x4,
    SF x2, F) as the team ids qf uses."""
    teams = [t for p in qf for t in p]
    tree = [(("t", a), ("t", b), 3) for a, b in qf] + [(("w", 0), ("w", 1), 3), (("w", 2), ("w", 3), 3),
                                                       (("w", 4), ("w", 5), bo_final)]
    out = np.empty((n, 7), np.int16)
    for i in range(n):
        _, won = E.bracket(tree, E.noisy(logit, teams, sd, rng), rng)
        out[i] = won
    return out, teams


# ---------------------------------------------------------------------------------------------------- Swiss picks
def hits(C):
    """-> {slot: n x 16 float32 hit matrix}."""
    return {s: (C == CLS[s]).astype(np.float32) for s, _ in SLOTS}


def score(H, pk):
    return sum(H[s][:, pk[s]].sum(1) for s, _ in SLOTS)


def p_pass(H, pk, need=NEED):
    return float((score(H, pk) >= need).mean())


def ev_picks(P, top=1):
    """Most expected correct picks (exact: every 3-0 pair x every 0-3 pair, best six advance of the rest).
    P: 16 x 4 class chances. -> the `top` best pick sets."""
    n = len(P)
    best = []
    for a in itertools.combinations(range(n), 2):
        ea = P[a[0], 0] + P[a[1], 0]
        rest = [t for t in range(n) if t not in a]
        for z in itertools.combinations(rest, 2):
            ez = P[z[0], 3] + P[z[1], 3]
            r2 = sorted((t for t in rest if t not in z), key=lambda t: -P[t, 1])[:6]
            best.append((ea + ez + sum(P[t, 1] for t in r2), {"30": list(a), "03": list(z), "adv": r2}))
    best.sort(key=lambda x: -x[0])
    return [b[1] for b in best[:top]]


def tier_picks(H, starts, need=NEED):
    """Hill-climb P(need+ correct) on the joint sims from each start: move an unpicked team into a slot, or swap
    two picked teams between slots, while it helps. -> best pick set, its chance (on these sims)."""
    n = next(iter(H.values())).shape[1]
    best, bv = None, -1
    for st in starts:
        pk = {s: list(v) for s, v in st.items()}
        cur = p_pass(H, pk, need)
        while True:
            used = {t for v in pk.values() for t in v}
            base = score(H, pk)
            mv, mvv = None, cur
            for s, _ in SLOTS:
                for i, t in enumerate(pk[s]):
                    less = base - H[s][:, t]
                    for u in range(n):  # unpicked team in
                        if u in used:
                            continue
                        v = float((less + H[s][:, u] >= need).mean())
                        if v > mvv + 1e-9:
                            mv, mvv = ("in", s, i, u), v
                    for s2, _ in SLOTS:  # swap with a pick in another slot
                        if s2 <= s:
                            continue
                        for j, u in enumerate(pk[s2]):
                            v = float((less - H[s2][:, u] + H[s][:, u] + H[s2][:, t] >= need).mean())
                            if v > mvv + 1e-9:
                                mv, mvv = ("sw", s, i, s2, j), v
            if mv is None:
                break
            if mv[0] == "in":
                pk[mv[1]][mv[2]] = mv[3]
            else:
                _, s, i, s2, j = mv
                pk[s][i], pk[s2][j] = pk[s2][j], pk[s][i]
            cur = mvv
        if cur > bv:
            best, bv = pk, cur
    return best, bv


def chalk(n=16):
    """Seed order only: top two seeds 3-0, bottom two 0-3, seeds 3-8 advance."""
    return {"30": [0, 1], "03": [n - 2, n - 1], "adv": list(range(2, 8))}


def pick_swiss(C_search, C_eval, need=NEED):
    """-> {policy: (picks, P(pass) on held sims, expected correct, P(pass) if picks were independent)}."""
    Hs, He = hits(C_search), hits(C_eval)
    P = np.stack([(C_search == c).mean(0) for c in range(4)], 1)
    evs = ev_picks(P, top=12)
    tp, _ = tier_picks(Hs, evs[:6] + [chalk(len(P))], need)
    Pe = np.stack([(C_eval == c).mean(0) for c in range(4)], 1)
    out = {}
    for nm, pk in (("tier", tp), ("ev", evs[0]), ("chalk", chalk(len(P)))):
        ps = [Pe[t, CLS[s]] for s, _ in SLOTS for t in pk[s]]
        out[nm] = {"picks": pk, "pPass": round(p_pass(He, pk, need), 4),
                   "ev": round(float(sum(ps)), 3), "pInd": round(pbinom_tail(ps, need), 4)}
    return out, Pe


def pbinom_tail(ps, k):
    """P(at least k of independent events with chances ps)."""
    d = np.zeros(len(ps) + 1)
    d[0] = 1
    for p in ps:
        d[1:] = d[1:] * (1 - p) + d[:-1] * p
        d[0] *= 1 - p
    return float(d[k:].sum())


# ---------------------------------------------------------------------------------------------------- bracket picks
BRACKETS = [(q, s, f) for q in itertools.product((0, 1), repeat=4) for s in itertools.product((0, 1), repeat=2)
            for f in (0, 1)]


def bracket_of(b, qf):
    """bits -> 7 winners (team ids from qf, the four quarter-finals in bracket order)."""
    q, s, f = b
    qw = [qf[i][q[i]] for i in range(4)]
    sw = [qw[2 * i + s[i]] for i in range(2)]
    return qw + sw + [sw[f]]


def bracket_challenges(X, pk):
    """X: n x 7 simulated winners, pk: 7 picked winners -> n x 3 (2+ QF, 1+ SF, final) booleans."""
    pk = np.asarray(pk)
    h = X == pk
    return np.stack([h[:, :4].sum(1) >= 2, h[:, 4:6].sum(1) >= 1, h[:, 6]], 1)


def pick_bracket(X_search, X_eval, qf):
    """-> {policy: {picks, P(k+ of 3) for k 1-3, EV of the 7 picks}} for k-max policies, most expected correct,
    and seed chalk (the lower team id, i.e. the better seed, wins every match)."""
    allb = [bracket_of(b, qf) for b in BRACKETS]
    rows = []
    for pk in allb:
        c = bracket_challenges(X_search, pk).sum(1)
        rows.append(([float((c >= k).mean()) for k in (1, 2, 3)], float((X_search == np.asarray(pk)).sum(1).mean())))
    pol = {f"k{k}": allb[max(range(len(allb)), key=lambda i: rows[i][0][k - 1])] for k in (1, 2, 3)}
    pol["ev"] = allb[max(range(len(allb)), key=lambda i: rows[i][1])]
    pol["chalk"] = chalk_bracket(qf)
    out = {}
    for nm, pk in pol.items():
        c = bracket_challenges(X_eval, pk).sum(1)
        out[nm] = {"picks": [int(x) for x in pk], "pk": [round(float((c >= k).mean()), 4) for k in (1, 2, 3)],
                   "ev": round(float((X_eval == np.asarray(pk)).sum(1).mean()), 3)}
    return out


# ---------------------------------------------------------------------------------------------------- backtest
def records(cat, tid, sid):
    W, L = defaultdict(int), defaultdict(int)
    for m in cat["events"][tid]["matches"]:
        if m[2] == sid and m[12] == "finished" and m[8]:
            W[m[8]] += 1
            L[m[5] if m[8] == m[4] else m[4]] += 1
    return W, L


def prep():
    """Point-in-time logits for every past 16-team Swiss stage and 8-team bracket (the series model's weights refit on
    series before each stage, as cs2_events.fit does), so --fit can rerun the policies without the replay."""
    import cs2_bo3
    import cs2_model as M
    import cs2_players
    H = json.load(gzip.open(M.HIST))
    vrs = M.Vrs(H["vrs"])
    p = json.loads(M.FIT.read_text())["params"]
    bo3 = cs2_bo3.Bo3()
    cat = E.load()
    ss = [s for s in E.stages(cat) if s["date"] >= "2024-10-01" and (s["kind"] == "swiss" or len(s["teams"]) == 8)]
    dates = sorted({s["date"] for s in ss})
    t0 = time.time()
    rows, st = M.replay(H["series"], vrs, p, bo3=bo3, snaps=dates)
    tm = cs2_bo3.TeamMaps(bo3)
    tm.play(snaps=dates)
    live = cs2_players.Live(bo3)
    rows = [r for r in rows if r["d"] >= "2024-08-07"]
    for r in rows:
        r["z"] = live.z(r["r"][4], r["a"], r["r"][5], r["b"], r["d"]) if live.w else 0.0
    print(f"replay {time.time() - t0:.0f}s, {len(ss)} stages")

    def weights(d, cols):
        tr = [r for r in rows if r["d"] < d]
        out = {}
        for tier in (True, False):
            rr = [r for r in tr if r["top"] == tier]
            X = np.array([[(r["x"], r["v"], r["t"], r["z"])[c] for c in cols] for r in rr])
            out["top" if tier else "rest"] = list(M.fitlog(X, np.array([r["s"] for r in rr])))
        return out
    out = []
    for s in ss:
        d = s["date"]
        teams = sorted(s["teams"], key=lambda t: (v[0] if (v := vrs.get(bo3.k(t) or key(s["names"][t]), d)) else 999))
        row = {k: s[k] for k in ("event", "tid", "stage", "date", "major", "kind")}
        row["names"] = [s["names"][t] for t in teams]
        ix = {t: i for i, t in enumerate(teams)}
        if s["kind"] == "swiss":
            W, L = records(cat, s["tid"], s["stage"])
            row["W"], row["L"] = [W[t] for t in teams], [L[t] for t in teams]
            row["r1"] = [(ix[a], ix[b]) for a, b in s["r1"]]
            row["allbo3"] = s["allbo3"]
            bos = (1, 3)
        else:
            tr = s["tree"]
            if not (len(tr) == 7 and all(x[0][0] == "t" and x[1][0] == "t" for x in tr[:4])):
                continue
            # bracket order: QF 0/1 feed one semi, 2/3 the other
            sf = [(x[0][1], x[1][1]) for x in tr[4:6]]
            qf = [(ix[tr[i][0][1]], ix[tr[i][1][1]]) for q in sf for i in q]
            res = [m for m in cat["events"][s["tid"]]["matches"] if m[2] == s["stage"] and m[12] == "finished"]
            res.sort(key=lambda m: m[1])
            qset = {frozenset(q): i for i, q in enumerate(qf)}
            qw = [None] * 4
            rest = []
            for m in res:
                f = frozenset((ix[m[4]], ix[m[5]]))
                if f in qset:
                    qw[qset[f]] = ix[m[8]]
                else:
                    rest.append(m)
            if None in qw or len(rest) != 3:
                continue
            sfw = [None, None]
            for m in rest[:2]:
                a = ix[m[4]]
                sfw[0 if a in (qw[0], qw[1]) else 1] = ix[m[8]]
            row["qf"], row["won"] = qf, qw + sfw + [ix[rest[2][8]]]
            row["boF"] = tr[6][2]
            bos = (3, tr[6][2])
        for nm, cols in (("ARK", (0, 1, 2, 3)), ("VRS", (1,))):
            mdl = E.Model(M, p, st["snaps"][d], vrs, tm.snaps[d], live, bo3, weights(d, cols), d, cols)
            mdl.names = s["names"]
            row[nm] = {str(bo): [[round(mdl.logit(a, b, bo), 4) if a != b else 0 for b in teams] for a in teams]
                       for bo in sorted(set(bos))}
        out.append(row)
        print(d, row["kind"], row["event"][:44], f"{time.time() - t0:.0f}s")
    with gzip.open(PREP, "wt") as f:
        json.dump({"asof": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "stages": out}, f,
                  separators=(",", ":"))


def mat_logit(m):
    M = {int(bo): np.asarray(v) for bo, v in m.items()}
    return lambda a, b, bo: M[bo if bo in M else max(M)][a, b]


def fit(n=8000):
    """Backtest: each past stage picked from the ratings before it (sd from cs2_events' tune window), scored on the
    real records. Policies: tier (max P 5+), ev (max expected correct), chalk (seed order), and the same on
    VRS-only ratings. Pass: on held-out stages (from SPLIT) the ARK tier picks' mean correct and pass rate are at
    least chalk's and VRS tier's, and its P(pass) is better calibrated than the independent-picks chance."""
    sd = json.loads(E.FIT.read_text()).get("sd", 0.45)
    pr = json.load(gzip.open(PREP))["stages"]
    rng = random.Random(11)
    rows = []
    t0 = time.time()
    for s in pr:
        r = {k: s[k] for k in ("event", "date", "major", "kind")}
        if s["kind"] == "swiss":
            y = np.array(classes(dict(enumerate(s["W"])), dict(enumerate(s["L"])), range(16)))
            r["m"] = {}
            for nm in ("ARK", "VRS"):
                lg = mat_logit(s[nm])
                seeds = list(range(16))
                Cs = sim_swiss(seeds, lg, s["r1"], s["allbo3"], n, sd, rng)
                Ce = sim_swiss(seeds, lg, s["r1"], s["allbo3"], n, sd, rng)
                pol, Pe = pick_swiss(Cs, Ce)
                for k, v in pol.items():
                    c = sum(int(y[t] == CLS[sl]) for sl, _ in SLOTS for t in v["picks"][sl])
                    v["correct"], v["pass"] = c, int(c >= NEED)
                r["m"][nm] = pol
                r["cls_ll"] = r.get("cls_ll", {})
                r["cls_ll"][nm] = round(float(-np.log(np.clip(Pe[np.arange(16), y], 1e-3, 1)).sum()), 4)
            r["cls_ll"]["equal"] = round(float(-np.log(np.array([1 / 16, 6 / 16, 6 / 16, 1 / 16])[y]).sum()), 4)
            r["names"] = {sl: [s["names"][t] for t in r["m"]["ARK"]["tier"]["picks"][sl]] for sl, _ in SLOTS}
            r["actual"] = {"30": [s["names"][t] for t in range(16) if y[t] == 0],
                           "03": [s["names"][t] for t in range(16) if y[t] == 3]}
        else:
            won = np.array(s["won"])
            r["m"] = {}
            for nm in ("ARK", "VRS"):
                lg = mat_logit(s[nm])
                Xs, _ = sim_bracket(s["qf"], lg, n, sd, rng, s["boF"])
                Xe, _ = sim_bracket(s["qf"], lg, n, sd, rng, s["boF"])
                pol = pick_bracket(Xs, Xe, s["qf"])
                for k, v in pol.items():
                    pk = v["picks"]
                    ch = bracket_challenges(won[None, :], pk)[0]
                    v["got"] = [int(x) for x in ch]
                    v["nGot"] = int(ch.sum())
                    v["correct"] = int((won == np.asarray(pk)).sum())
                r["m"][nm] = pol
        rows.append(r)
        print(f"{r['date']} {r['kind']:5s} {r['event'][:40]:40s}", summary_line(r), f"{time.time() - t0:.0f}s")
    out = {"asof": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "nsim": n, "sd": sd, "split": SPLIT,
           "score": scores(rows), "majors": majors(rows), "stages": rows}
    FIT.write_text(json.dumps(out, indent=1))
    print(json.dumps(out["score"], indent=1))
    print(json.dumps(out["majors"], indent=1))
    return out


def chalk_bracket(qf):
    """Higher seed (lower index = better VRS rank) wins every match."""
    qw = [min(a, b) for a, b in qf]
    sw = [min(qw[0], qw[1]), min(qw[2], qw[3])]
    return qw + sw + [min(sw)]


def summary_line(r):
    if r["kind"] == "swiss":
        a = r["m"]["ARK"]
        return " ".join(f"{k} {v['correct']}/{v['pPass']:.2f}" for k, v in a.items()) + \
            f" | VRS tier {r['m']['VRS']['tier']['correct']}"
    a = r["m"]["ARK"]
    return " ".join(f"{k} {v['nGot']}" for k, v in a.items())


def tstat(d):
    d = np.asarray(d, float)
    return round(float(d.mean() / (d.std(ddof=1) + 1e-12) * math.sqrt(len(d))), 2) if len(d) > 1 else None


def scores(rows):
    out = {}
    pols = [("ARK", "tier"), ("ARK", "ev"), ("ARK", "chalk"), ("VRS", "tier"), ("VRS", "ev")]
    for win, f in (("held", lambda r: r["date"] >= SPLIT), ("tune", lambda r: r["date"] < SPLIT),
                   ("all", lambda r: True)):
        sw = [r for r in rows if r["kind"] == "swiss" and f(r)]
        if sw:
            o = {"n": len(sw)}
            for m, p in pols:
                o[f"{m} {p}"] = {"correct": round(float(np.mean([r["m"][m][p]["correct"] for r in sw])), 3),
                                 "pass": round(float(np.mean([r["m"][m][p]["pass"] for r in sw])), 3),
                                 "pPass": round(float(np.mean([r["m"][m][p]["pPass"] for r in sw])), 3),
                                 "ev": round(float(np.mean([r["m"][m][p]["ev"] for r in sw])), 3)}
            base = "ARK tier"
            for other in ("ARK chalk", "VRS tier", "ARK ev"):
                m, p = other.split()
                d = [r["m"]["ARK"]["tier"]["correct"] - r["m"][m][p]["correct"] for r in sw]
                o[f"{base} - {other}"] = {"correct": round(float(np.mean(d)), 3), "t": tstat(d)}
            # calibration of the stage-pass chance: joint sims vs picks treated as independent
            pj = [r["m"]["ARK"]["tier"]["pPass"] for r in sw]
            pi = [r["m"]["ARK"]["tier"]["pInd"] for r in sw]
            y = [r["m"]["ARK"]["tier"]["pass"] for r in sw]
            o["brierPass"] = {"joint": round(float(np.mean([(a - b) ** 2 for a, b in zip(pj, y)])), 4),
                              "independent": round(float(np.mean([(a - b) ** 2 for a, b in zip(pi, y)])), 4)}
            o["clsLL"] = {k: round(float(np.mean([r["cls_ll"][k] for r in sw])), 3) for k in ("ARK", "VRS", "equal")}
            d = [r["cls_ll"]["ARK"] - r["cls_ll"]["VRS"] for r in sw]
            o["clsLL"]["t"] = tstat(d)
            out[f"{win}/swiss"] = o
        se = [r for r in rows if r["kind"] == "se" and f(r)]
        if se:
            o = {"n": len(se)}
            for m in ("ARK", "VRS"):
                for p in ("k1", "k2", "k3", "ev", "chalk"):
                    if m == "VRS" and p == "chalk":
                        continue
                    o[f"{m} {p}"] = {"nGot": round(float(np.mean([r["m"][m][p]["nGot"] for r in se])), 3),
                                     "all3": round(float(np.mean([r["m"][m][p]["nGot"] == 3 for r in se])), 3),
                                     "pAll3": round(float(np.mean([r["m"][m][p]["pk"][2] for r in se])), 3)}
            out[f"{win}/se"] = o
    return out


def majors(rows):
    """Per Major with three Swiss stages + the playoffs: skill challenges passed (of 6) and the coin, per policy."""
    ev = defaultdict(list)
    for r in rows:
        if r["major"]:
            ev[r["event"].split(" Stage")[0].split(" Opening")[0]].append(r)
    out = {}
    for nm, rr in sorted(ev.items(), key=lambda x: x[1][0]["date"]):
        sw = [r for r in rr if r["kind"] == "swiss"]
        se = [r for r in rr if r["kind"] == "se"]
        o = {"stages": len(sw), "playoffs": bool(se)}
        for m, p, bp in (("ARK", "tier", "k3"), ("ARK", "ev", "ev"), ("ARK", "chalk", "chalk"), ("VRS", "tier", "k3")):
            got = sum(r["m"][m][p]["pass"] for r in sw) + (se[0]["m"][m][bp]["nGot"] if se else 0)
            tot = FREE + got
            o[f"{m} {p}"] = {"skill": got, "challenges": tot,
                             "coin": max((c for c, k in COIN.items() if tot >= k), key=lambda c: COIN[c])}
        out[nm] = o
    return out


# ---------------------------------------------------------------------------------------------------- live
def coin_odds(p_stage, fit):
    """P(Gold) and P(Diamond) for the whole Major: the known stages' pass chances (p_stage: {stage: P}), the
    backtest's mean model chance for stages not drawn yet, and the playoff challenge count from the backtest's
    brackets, treated as independent of each other (each stage is picked on its own field)."""
    sw = fit["score"]["all/swiss"]["ARK tier"]["pPass"]
    pk = fit["score"]["all/se"]
    k = [pk["ARK k3"]["pAll3"]]
    # P(at least 1 / 2 / 3 of the bracket's three) from the held brackets' simulated chances
    rows = [r["m"]["ARK"]["k3"]["pk"] for r in fit["stages"] if r["kind"] == "se"]
    ge = np.mean(rows, 0) if rows else np.array([0.8, 0.5, k[0]])
    dist = np.array([1 - ge[0], ge[0] - ge[1], ge[1] - ge[2], ge[2]])
    for st in ("Stage 1", "Stage 2", "Stage 3"):
        q = p_stage.get(st, sw)
        d2 = np.zeros(len(dist) + 1)
        d2[:-1] += dist * (1 - q)
        d2[1:] += dist * q
        dist = d2
    return {"Silver": 1.0, "Gold": round(float(dist[3:].sum()), 3), "Diamond": round(float(dist[6]), 3)}


def team_row(k, names, logos, P=None):
    r = {"k": k, "n": names.get(k, k), "logo": (logos / f"{k}.png").exists()}
    if P is not None:
        r["p"] = [round(float(x), 3) for x in P]
    return r


def live(logit, st, n=40000):
    """Picks for the next Major stage, called at the end of cs2_model.build() with its series logit(ka, kb, bo) and
    cs2_events' "next" stage (event, stage, start, seeds in seed order, names, r1, known, allbo3, projected).
    Picks lock at the stage's first match: after that the saved picks stay and only their chance updates."""
    import cs2_model as M
    fit = json.loads(FIT.read_text())
    sd = fit["sd"]
    if not st or not st.get("seeds"):
        print("pick'em: no Major stage to pick")
        return
    prev = json.loads(OUT.read_text()) if OUT.exists() else {}
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    locked = bool(st.get("start")) and now >= st["start"][:19] + "Z"
    same = prev.get("event") == st["event"] and prev.get("stage") == st["stage"]
    rng = random.Random(int(time.time()) // 86400)
    seeds, names = st["seeds"], st.get("names", {})
    out = {"asof": now, "event": st["event"], "stage": st["stage"], "start": st.get("start"), "locked": locked,
           "projected": bool(st.get("projected")), "nsim": n, "sd": sd}
    if st["stage"] == "Playoffs":
        s8 = seeds[:8]
        qf = [(s8[0], s8[7]), (s8[3], s8[4]), (s8[1], s8[6]), (s8[2], s8[5])]
        Xs, _ = sim_bracket(qf, logit, n, sd, rng, 5)
        Xe, _ = sim_bracket(qf, logit, n, sd, rng, 5)
        pol = pick_bracket(Xs, Xe, qf)
        if locked and same and prev.get("bracket"):
            pol = {k: dict(v, picks=prev["bracket"][k]["picks"]) for k, v in pol.items()}
        out["qf"] = [[team_row(a, names, M.LOGOS), team_row(b, names, M.LOGOS)] for a, b in qf]
        out["bracket"] = {k: {"picks": [team_row(t, names, M.LOGOS) for t in v["picks"]], "pk": v["pk"]}
                          for k, v in pol.items() if k in ("k1", "k2", "k3")}
        p_stage = {f"Stage {i}": 1.0 for i in (1, 2, 3)}
    else:
        known = [[tuple(x) for x in rr] for rr in st.get("known") or []] or \
            ([[(a, b, None) for a, b in st["r1"]]] if st.get("r1") else ())

        def sims():
            C = np.empty((n, 16), np.int8)
            for i in range(n):
                W, L, _ = E.swiss(seeds, E.noisy(logit, seeds, sd, rng), rng, known, st.get("allbo3", False))
                C[i] = classes(W, L, seeds)
            return C
        Cs, Ce = sims(), sims()
        pol, Pe = pick_swiss(Cs, Ce)
        tier = pol["tier"]
        if locked and same and prev.get("picks"):
            ix = {k: i for i, k in enumerate(seeds)}
            tier = {"picks": {sl: [ix[t["k"]] for t in prev["picks"][sl]] for sl, _ in SLOTS}}
            ps = [Pe[t, CLS[sl]] for sl, _ in SLOTS for t in tier["picks"][sl]]
            tier.update(pPass=round(p_pass(hits(Ce), tier["picks"]), 4), ev=round(float(sum(ps)), 3))
        out["picks"] = {sl: [team_row(seeds[t], names, M.LOGOS, Pe[t]) for t in tier["picks"][sl]] for sl, _ in SLOTS}
        out["pPass"], out["ev"] = tier["pPass"], tier["ev"]
        out["pEv"] = pol["ev"]["pPass"]
        out["teams"] = [dict(team_row(k, names, M.LOGOS, Pe[i]), seed=i + 1) for i, k in enumerate(seeds)]
        p_stage = {st["stage"]: tier["pPass"]}
        for i in range(1, int(st["stage"][-1])):
            p_stage[f"Stage {i}"] = 1.0  # earlier stages are scored by now; the coin line counts the rest
    out["coin"] = coin_odds(p_stage, fit)
    hs = fit["score"]["held/swiss"]
    out["bt"] = {"n": hs["n"], "pPass": hs["ARK tier"]["pPass"], "pass": hs["ARK tier"]["pass"],
                 "chalk": hs["ARK chalk"]["pass"], "correct": hs["ARK tier"]["correct"],
                 "chalkCorrect": hs["ARK chalk"]["correct"], "nSe": fit["score"]["held/se"]["n"],
                 "se": fit["score"]["held/se"]["ARK k3"]["nGot"], "seChalk": fit["score"]["held/se"]["ARK chalk"]["nGot"]}
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    print(st["event"], st["stage"], "P(5+)", out.get("pPass"), out["coin"])


if __name__ == "__main__":
    if "--prep" in sys.argv:
        prep()
    elif "--fit" in sys.argv:
        fit()
