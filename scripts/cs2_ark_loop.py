#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""CS2 ARK Ranking self-retune loop (Noah Nov 23 2026: "use match data from now on to continuously improve ARK Ranking").

The ratings already move with every match (scripts/cs2_model.py replays all series each cs2 run). This loop retunes the
rating's settings as months of matches accrue, and ships a retune only when the retune procedure itself has won out of
sample. Pre-registered (Nov 23 2026, before any walk-forward number was read):

  - sealed months: a month is scored only once it is complete in Valve's history (a later month's series are listed)
    and, if SEAL_CAP is set, ends on or before it. Nothing in an unsealed month is read.
  - candidates: the shipped settings (data/cs2_fit.json params) and one-at-a-time steps on K, Kmin, n0 (K decay over a
    player's series), kmap (map-level K), kx (lower-tier K, the tier offset), Kr (region link K), span and mu_new.
    One replay per candidate (the replay is causal, so every month's row is point in time).
  - walk-forward from Jul 2025 (the model's held split): for each sealed month m, every candidate's blend weights
    (top-50 / rest, as cs2_model.fit) are fit on its rows Aug 7 2024 .. m-1 and the candidate with the lowest log loss
    there is picked; month m is then scored once with that pick against the shipped settings (weights fit the same way).
  - ship gate: the procedure's monthly log-loss gap to the shipped settings has mean < 0, t by month <= crit(look),
    top-50 series t by month < +1 (not worse), and calibration slope .7-1.3 on the scored months. crit(1) = -2.0;
    each later look (a new sealed month) spends alpha Bonferroni-style: crit(k) = Phi^-1(.0228 / k).
  - once passed: every new sealed month the settings picked on all sealed rows ship to data/cs2_fit.json (params and
    live weights), and the months after adoption keep being scored against the settings frozen at adoption; a t by month
    >= +2 there reverts to them.
    -> data/cs2_ark_loop.json (state + record), research/studies/cs2/cs2-ark-loop.json (Process card)

    python3 scripts/cs2_ark_loop.py          # weekly (cs2-ark-loop.yml); exits early when no new month has sealed
    python3 scripts/cs2_ark_loop.py --force  # rerun the walk-forward anyway (does not count as a look)
"""
import gzip
import json
import math
import os
import statistics
import sys
from collections import defaultdict
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cs2_bo3  # noqa: E402
import cs2_model as M  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "cs2_ark_loop.json"
CARD = ROOT / "research" / "studies" / "cs2" / "cs2-ark-loop.json"
START = "2025-07"          # first walk-forward month (the model's held split)
SEAL_CAP = None            # "YYYY-MM-DD": never read a series after it (a lockbox); None = rolling monthly seal
STEPS = {"K": ("x", .8, 1.25), "Kmin": ("x", .8, 1.25), "n0": ("x", .7, 1.4), "kmap": ("+", -.15, .15),
         "kx": ("+", -.25, .25), "Kr": ("x", .5, 2.0), "span": ("+", -.1, .1), "mu_new": ("+", -50, 50)}
_G = {}


def candidates(p0):
    out = [("shipped", dict(p0))]
    for k, (op, lo, hi) in STEPS.items():
        for f in (lo, hi):
            v = p0[k] * f if op == "x" else p0[k] + f
            v = round(v if k == "mu_new" else max(v, 0.0), 4)
            if k in ("K", "Kmin", "n0") and v < 1:
                continue
            if v != p0[k]:
                out.append((f"{k} {v:g}", dict(p0, **{k: v})))
    return out


def _init():
    H = json.load(gzip.open(M.HIST))
    _G["series"] = [r for r in H["series"] if r[6] == "vrs"]
    _G["vrs"] = M.Vrs(H["vrs"])


def _rows(args):
    name, p, cap = args
    series = [r for r in _G["series"] if not cap or r[0] <= cap]
    rows, _ = M.replay(series, _G["vrs"], p, bo3=cs2_bo3.Bo3())
    keep = [r for r in rows if r["d"] >= M.TUNE[0]]
    return name, {"m": np.array([r["d"][:7] for r in keep]), "X": np.array([[r["x"], r["v"], r.get("t", 0.0)] for r in keep]),
                  "top": np.array([r["top"] for r in keep]), "s": np.array([r["s"] for r in keep], float)}


def fit_pred(R, train, test):
    """Tiered blend (cs2_model.tiered on arrays): weights on `train` rows, chances on `test` rows."""
    q, ws = np.zeros(test.sum()), {}
    Xt, tt = R["X"][test], R["top"][test]
    for tier in (True, False):
        m = train & (R["top"] == tier)
        w = M.fitlog(R["X"][m], R["s"][m]) if m.sum() > 20 else np.zeros(3)
        ws["top" if tier else "rest"] = [round(float(z), 4) for z in w]
        q[tt == tier] = 1 / (1 + np.exp(-Xt[tt == tier] @ w))
    return q, ws


def tmonth(by):
    v = np.array(list(by.values()))
    if len(v) < 2:
        return 0.0
    return float(v.mean() / (v.std(ddof=1) / math.sqrt(len(v)) + 1e-12))


def slope(q, y):
    z = np.log(np.clip(q, 1e-6, 1 - 1e-6) / np.clip(1 - q, 1e-6, 1))
    b = 1.0
    for _ in range(50):
        pr = 1 / (1 + np.exp(-b * z))
        b -= np.sum((pr - y) * z) / (np.sum(pr * (1 - pr) * z * z) + 1e-9)
    return float(b)


def crit(look):
    return -2.0 if look <= 1 else statistics.NormalDist().inv_cdf(.0228 / look)


def walk(R, months, base, cands, since=START):
    """Walk-forward record: per sealed month, the pick (trained on earlier rows) vs `base`."""
    rec, dl_all, dl_top, qs, ys = [], {}, {}, [], []
    for mo in [m for m in months if m >= since]:
        train = {n: (r["m"] < mo) for n, r in R.items()}
        best, bl = None, 9.0
        for n in cands:
            tr = train[n]
            q, _ = fit_pred(R[n], tr, tr)
            l = float(M.ll(q, R[n]["s"][tr]).mean())
            if l < bl - 1e-9:
                best, bl = n, l
        out = {}
        for n in (best, base):
            te = R[n]["m"] == mo
            q, _ = fit_pred(R[n], train[n], te)
            out[n] = (q, R[n]["s"][te], R[n]["top"][te])
        (qp, y, top), (qb, _, _) = out[best], out[base]
        d = M.ll(qp, y) - M.ll(qb, y)
        dl_all[mo] = float(d.mean())
        if top.sum():
            dl_top[mo] = float(d[top].mean())
        qs.append(qp)
        ys.append(y)
        rec.append({"m": mo, "pick": best, "n": int(len(y)), "nTop": int(top.sum()), "ll": round(float(M.ll(qp, y).mean()), 4),
                    "llBase": round(float(M.ll(qb, y).mean()), 4), "d": round(dl_all[mo], 5)})
    q, y = (np.concatenate(qs), np.concatenate(ys)) if qs else (np.zeros(0), np.zeros(0))
    return {"months": rec, "d": round(float(np.mean(list(dl_all.values()))), 5) if dl_all else 0.0,
            "t": round(tmonth(dl_all), 2), "tTop": round(tmonth(dl_top), 2),
            "won": [sum(v < 0 for v in dl_all.values()), len(dl_all)],
            "slope": round(slope(q, y), 3) if len(y) else None, "n": int(len(y))}


def main():
    st = json.loads(OUT.read_text()) if OUT.exists() else {"looks": 0, "adopted": None, "lastSealed": None, "log": []}
    fitj = json.loads(M.FIT.read_text())
    p0 = dict(fitj["params"])
    H = json.load(gzip.open(M.HIST))
    vd = sorted(r[0] for r in H["series"] if r[6] == "vrs")
    cap = SEAL_CAP or os.environ.get("CS2_SEAL_CAP") or None
    last_d = min(vd[-1], cap) if cap else vd[-1]
    # sealed = every month before the month of the latest listed series (and, with a cap, wholly on or before it)
    sealed = sorted({d[:7] for d in vd if d[:7] < last_d[:7]})
    if cap and cap[8:] >= "28" and cap[:7] in {d[:7] for d in vd} and vd[-1][:7] > cap[:7]:
        sealed.append(cap[:7])
    new = sealed[-1] if sealed else None
    if new == st.get("lastSealed") and "--force" not in sys.argv:
        print("no new sealed month since", new)
        return
    centre = st["adopted"]["frozen"] if st.get("adopted") else p0
    cands = candidates(p0)
    if st.get("adopted"):   # the settings frozen at adoption are scored beside the moving ones
        cands.append(("frozen", dict(centre)))
    cut = f"{new}-31" if new else None
    with Pool(min(4, os.cpu_count() or 1), initializer=_init) as pool:
        R = dict(pool.map(_rows, [(n, p, cut) for n, p in cands]))
    names = [n for n, _ in cands if n != "frozen"]
    rec = walk(R, sealed, "shipped", names)
    look = st["looks"] + (1 if new != st.get("lastSealed") else 0)
    c = crit(look)
    print("record", {k: v for k, v in rec.items() if k != "months"}, "look", look, "crit", round(c, 2))
    passed = bool(rec["d"] < 0 and rec["t"] <= c and rec["tTop"] < 1 and rec["slope"] and .7 <= rec["slope"] <= 1.3)
    shipped = None
    if st.get("adopted"):
        y, mo = map(int, st["adopted"]["from"].split("-"))
        nxt = f"{y + mo // 12}-{mo % 12 + 1:02d}"   # months after adoption only
        post = walk(R, sealed, "frozen", names, since=nxt)
        st["adopted"]["post"] = post
        if post["won"][1] >= 2 and post["t"] >= 2:
            p_new = dict(st["adopted"]["frozen"])
            st["log"].append({"sealed": new, "event": "reverted", "t": post["t"]})
            st["adopted"] = None
        else:
            p_new = None
    elif passed:
        st["adopted"] = {"from": new, "frozen": dict(p0), "look": look}
        st["log"].append({"sealed": new, "event": "adopted", "t": rec["t"], "crit": round(c, 2)})
        p_new = None
    else:
        p_new = None
    if st.get("adopted") and p_new is None:   # retune on every sealed row: the pick ships
        allm = {n: R[n]["m"] <= new for n in names}
        ls = {n: float(M.ll(fit_pred(R[n], allm[n], allm[n])[0], R[n]["s"][allm[n]]).mean()) for n in names}
        best = min(ls, key=ls.get)
        p_new = dict(cands)[best]
    if p_new is not None and p_new != p0:
        fitj["params"] = p_new
        fitj["loop"] = {"sealed": new, "from": p0}
        # live weights on every scored row of the new settings, as cs2_model.fit (Aug 7 2024 on)
        name = next(n for n, p in cands if p == p_new)
        allr = np.ones(len(R[name]["s"]), bool)
        _, fitj["weights"] = fit_pred(R[name], allr, np.zeros(len(allr), bool))
        M.FIT.write_text(json.dumps(fitj, indent=1))
        shipped = {k: v for k, v in p_new.items() if p0.get(k) != v}
        st["log"].append({"sealed": new, "event": "shipped", "changed": shipped})
    if new != st.get("lastSealed"):
        st["looks"] = look
    st.update({"lastSealed": new, "cap": cap, "crit": round(c, 2), "pass": passed, "record": rec,
               "candidates": [n for n in names], "shipped": shipped,
               "gate": "mean < 0, t by month <= crit(look), top-50 t < +1, slope .7-1.3"})
    OUT.write_text(json.dumps(st, indent=1))
    card(st)
    print(json.dumps({k: v for k, v in st.items() if k != "record"}, indent=1))
    print("record", {k: v for k, v in rec.items() if k != "months"})
    for r in rec["months"]:
        print(" ", r)


def card(st):
    """Process > Research card, generated from the loop's record (never hand-edited)."""
    rec = st["record"]
    ms = rec["months"]
    picks = defaultdict(int)
    for r in ms:
        picks[r["pick"]] += 1
    top = sorted(picks.items(), key=lambda z: -z[1])[:3]
    verdict = "passes; retunes ship monthly" if st.get("adopted") else "fails; shipped settings kept"
    out = {
        "id": "cs2-ark-loop", "sport": "CS2",
        "question": "Does retuning the CS2 ARK rating every month beat keeping its settings fixed?",
        "answer": (f"Monthly retune {verdict}: {rec['d']:+.4f} log loss per series, t by month {rec['t']:+.2f} "
                   f"(bar {st['crit']:+.2f}), through {st['lastSealed']}."),
        "findings": [
            f"Won {rec['won'][0]} of {rec['won'][1]} months; top-50 series t {rec['tTop']:+.2f}.",
            f"Calibration slope {rec['slope']} on {rec['n']:,} scored series.",
            "Picks: " + ", ".join(f"{n} ({c} months)" for n, c in top) + ".",
            (f"Shipped {', '.join(f'{k} {v:g}' for k, v in st['shipped'].items())}." if st.get("shipped") else
             f"Look {st['looks']}: each new month tightens the bar (Bonferroni on looks).")],
        "method": ("Each month, the settings with the lowest log loss on all earlier series are picked from the shipped "
                   "set and one-step moves on K, K decay, map K, lower-tier K, region K, span and new-player start, "
                   "then scored once on that month against the shipped settings."),
        "data": f"Valve VRS series + bo3.gg maps, Aug 2024 to {st['lastSealed']}, {rec['n']:,} walk-forward series.",
        "n": rec["n"], "robust": bool(st.get("pass")), "interest": 3,
        "split_check": f"{rec['won'][0]}/{rec['won'][1]} months better; top-50 t {rec['tTop']:+.2f}.",
        "chart": {"type": "bar", "title": "Log loss, monthly retune minus fixed", "x_label": "month",
                  "y_label": "log loss gap", "y_fmt": "signed", "ref": {"y": 0, "label": "fixed"}, "mark": None,
                  "series": [{"name": "retune", "points": [{"x": r["m"][2:], "y": round(r["d"] * 1000, 2), "n": r["n"]}
                                                           for r in ms[-20:]]}]},
        "auto": "scripts/cs2_ark_loop.py"}
    out["chart"]["y_label"] = "log loss gap x1000"
    CARD.parent.mkdir(parents=True, exist_ok=True)
    CARD.write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
