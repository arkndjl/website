#!/usr/bin/env python3
"""Counter-Strike picks test on Thunderpick's prices (Noah, Oct 28 2026: "Yes, allow Thunderpick odds"). Pre-registered:
picks stay off until this passes on the forward archive.

    python3 scripts/cs2_picks.py --fit    # -> data/cs2_picks_fit.json

Why forward only: bo3.gg keeps updating a match's price in play and stores only the last one, so a finished match's
stored Thunderpick price is not a close (its favourite won 94.5% of 368 finished matches, Oct 2026). The archive
(scripts/data/odds_tp/cs2-*.jsonl, cs2_bo3.odds_snap, every odds snapshot) keeps each upcoming series' price from its
first listing (the open) to its last snapshot before the start (the close), with the model's chance beside it.

The rule is the one every sport uses (pick-rules, scripts/tennis_picks.py): the model's side at the open when model minus
the open's no-vig chance is X+ points and the side is no longer than -300/+300; judged by the close (CLV-implied return:
the close's no-vig chance x the decimal price taken at the open, minus 1) and by results. Earlier half of the archived
series tunes X (max mean CLV), later half held out. Passes when the held-out picks at the tuned X beat the close with
t >= 1.5 and every X's held p survives Benjamini-Hochberg at q .10, on 150+ held-out picks.
"""
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cs2_bo3  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FIT = ROOT / "data" / "cs2_picks_fit.json"
XS = (0.04, 0.06, 0.08, 0.10, 0.12, 0.15)
MLCAP = 0.25
GAPMAX = 0.35
NMIN = 150


def tstat(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1)) or 1e-9
    return m / sd * math.sqrt(n)


def rows():
    """Archived series with an open carrying the model's chance, a pre-start close and a result."""
    d = cs2_bo3.load()
    win = {m[0]: m[6] for m in d["matches"]}
    out = []
    for mid, (o, c) in cs2_bo3.closes().items():
        w = win.get(mid)
        if o.get("m") is None or w is None:
            continue
        out.append({"id": mid, "start": o["start"], "m": o["m"], "po": o["p"], "pc": c["p"], "o1": o["o1"],
                    "o2": o["o2"], "w1": w == o["t1"]})
    return sorted(out, key=lambda r: r["start"])


def bets(R, x):
    b = []
    for r in R:
        g = r["m"] - r["po"]
        if abs(g) < x or abs(g) > GAPMAX:
            continue
        one = g > 0
        pside = r["po"] if one else 1 - r["po"]
        if pside < MLCAP or pside > 1 - MLCAP:
            continue
        price = r["o1"] if one else r["o2"]
        clv = (r["pc"] if one else 1 - r["pc"]) * price - 1
        res = (price - 1) if (r["w1"] == one) else -1.0
        b.append((clv, res))
    return b


def fit():
    R = rows()
    h = len(R) // 2
    tune, held = R[:h], R[h:]
    grid = []
    for x in XS:
        bt, bh = bets(tune, x), bets(held, x)
        t = tstat([c for c, _ in bh])
        grid.append({"x": x, "nTune": len(bt), "clvTune": round(sum(c for c, _ in bt) / len(bt), 4) if bt else None,
                     "nHeld": len(bh), "clvHeld": round(sum(c for c, _ in bh) / len(bh), 4) if bh else None,
                     "tHeld": round(t, 2), "pHeld": 0.5 * math.erfc(t / math.sqrt(2)),
                     "resHeld": round(sum(r for _, r in bh) / len(bh), 4) if bh else None})
    ok = [g for g in grid if g["clvTune"] is not None]
    best = max(ok, key=lambda g: g["clvTune"]) if ok else None
    ps = sorted(g["pHeld"] for g in grid)
    bh_ok = all(p <= 0.10 * (i + 1) / len(ps) for i, p in enumerate(ps)) if ps else False
    passed = bool(best and best["nHeld"] >= NMIN and best["tHeld"] >= 1.5 and bh_ok)
    out = {"asof": cs2_bo3.dt.datetime.now(cs2_bo3.dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "nSeries": len(R), "x": best["x"] if best else None, "passed": passed,
           "status": "on" if passed else ("waiting for data" if not best or best["nHeld"] < NMIN else "failed"),
           "grid": grid}
    FIT.write_text(json.dumps(out, indent=1))
    print(json.dumps({k: out[k] for k in ("nSeries", "x", "passed", "status")}))


if __name__ == "__main__":
    fit()
