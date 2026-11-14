#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Economy baselines from pro round data (scripts/data/cs2_rounds, scripts/cs2_rounds.py) -> data/cs2_econ.json.

    python3 scripts/cs2_econ.py

Regulation rounds only (overtime has its own money rules), maps with 13+ winner rounds. Buy classes by team equipment
value after the buy: eco under 5,000, force 5,000 to 19,999, full 20,000+; pistol rounds are their own class.
  buy    T-side round win % for each T buy x CT buy cell (and pistols), all tiers and by tier, with n
  conv   after a pistol win / loss, by the side played: % winning the next round, % winning both of the next two
         (win) or either of them (loss), rounds won of the next two
  force  the round after a lost round, short of a full buy: rounds won over that round and the next one when the
         team forced and when it saved, the difference, its standard error (clustered by map). Bands: the round after
         a lost pistol, then the losing streak (1, 2, 3+ rounds, which sets the loss bonus). Rounds with either team
         on 12 are left out, so the next round always exists. bo3.gg carries no bank, so the bands stand in for money.
Cells under THIN rounds are flagged thin. Descriptive: no opponent or map adjustment.
"""
import datetime as dt
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cs2_bo3  # noqa: E402
import cs2_rounds  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "cs2_econ.json"
THIN = 200
TIERS = ["all", "s", "a", "b", "c"]
CLS = ["eco", "force", "full"]
BANDS = ["pistol", "1", "2", "3+"]
HALF, REG = 12, 24


def r4(x):
    return None if x is None or x != x else round(x, 4)


class Mean:
    """Running mean with a standard error clustered by map."""
    __slots__ = ("n", "s", "cl", "cur", "cs", "cn")

    def __init__(self):
        self.n = 0
        self.s = 0.0
        self.cl = []
        self.cur = None
        self.cs = self.cn = 0

    def add(self, gid, v):
        if gid != self.cur:
            if self.cn:
                self.cl.append((self.cs, self.cn))
            self.cur, self.cs, self.cn = gid, 0.0, 0
        self.n += 1
        self.s += v
        self.cs += v
        self.cn += 1

    def done(self):
        if self.cn:
            self.cl.append((self.cs, self.cn))
            self.cn = 0
        if not self.n:
            return None, None
        m = self.s / self.n
        g = len(self.cl)
        if g < 2:
            return m, None
        var = sum((s - m * n) ** 2 for s, n in self.cl) * g / (g - 1) / self.n ** 2
        return m, math.sqrt(var)


def build(bo3=None, rd=None, until=None):
    bo3 = bo3 or cs2_bo3.load()
    rd = rd if rd is not None else cs2_rounds.load()
    tier = {m[0]: m[10] for m in bo3["matches"]}
    buy = defaultdict(lambda: [0, 0])                    # (tier, T class, CT class) -> [T wins, n]; class 9 = pistol
    conv = defaultdict(lambda: [0, 0, 0, 0])             # (tier, won pistol, side) -> [n, next, both / either, rounds]
    frc = defaultdict(Mean)                              # (tier, band, side, class) -> two-round value
    nmap, nrd = defaultdict(int), defaultdict(int)
    last = ""
    for g in sorted(bo3["games"], key=lambda g: g[0]):
        rr = rd.get(g[0])
        if not rr or not g[2] or not cs2_bo3.real_map(g) or (until and g[2][:10] > until):
            continue
        tr = tier.get(g[1])
        if tr not in ("s", "a", "b", "c"):
            continue
        last = max(last, g[2][:10])
        rr = rr[:REG]
        for t in ("all", tr):
            nmap[t] += 1
            nrd[t] += len(rr)
        sw = sl = 0                                       # score before each round, map winner's view
        for i, r in enumerate(rr):
            tw = r[1] if r[0] == 0 else 1 - r[1]          # the T side won
            eqT, eqC = (r[3], r[4]) if r[0] == 0 else (r[4], r[3])
            first = i % HALF == 0
            if first:
                c = (9, 9)
            elif eqT or eqC:
                c = (cs2_rounds.klass(eqT), cs2_rounds.klass(eqC))
            else:
                c = None
            if c:
                for t in ("all", tr):
                    b = buy[(t, *c)]
                    b[0] += tw
                    b[1] += 1
            if first and i + 2 < min(len(rr), i + HALF):
                for w in (1, 0):                          # the map winner's view, then the other team's
                    won = r[1] if w else 1 - r[1]
                    side = r[0] if w else 1 - r[0]
                    a, b2 = (rr[i + 1][1], rr[i + 2][1]) if w else (1 - rr[i + 1][1], 1 - rr[i + 2][1])
                    for t in ("all", tr):
                        cv = conv[(t, won, side)]
                        cv[0] += 1
                        cv[1] += a
                        cv[2] += (a and b2) if won else (a or b2)
                        cv[3] += a + b2
            if not first and i % HALF != HALF - 1 and i + 1 < len(rr) and sw < 12 and sl < 12 and (r[3] or r[4]):
                for w in (1, 0):
                    if (rr[i - 1][1] if w else 1 - rr[i - 1][1]):
                        continue                          # only the team that lost the round before
                    k = cs2_rounds.klass(r[3] if w else r[4])
                    if i % HALF == 1:
                        band = "pistol"
                    else:
                        n = 1
                        while i - 1 - n >= (i // HALF) * HALF and not (rr[i - 1 - n][1] if w else 1 - rr[i - 1 - n][1]):
                            n += 1
                        band = "3+" if n >= 3 else str(n)
                    side = r[0] if w else 1 - r[0]
                    v = (r[1] + rr[i + 1][1]) if w else (2 - r[1] - rr[i + 1][1])
                    for t in ("all", tr):
                        for sd in (side, 2):
                            frc[(t, band, sd, k)].add(g[0], v)
            sw += r[1]
            sl += 1 - r[1]

    def cellp(t, a, b):
        w, n = buy.get((t, a, b), (0, 0))
        return {"p": r4(w / n) if n else None, "n": n, **({"thin": True} if n < THIN else {})}
    out = {"asof": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "through": last, "thin": THIN,
           "classes": {"eco": [0, 5000], "force": [5000, 20000], "full": [20000, None]},
           "tiers": {t: {"maps": nmap[t], "rounds": nrd[t]} for t in TIERS},
           "buy": [{"t": "pistol", "ct": "pistol", **{t: cellp(t, 9, 9) for t in TIERS}}] +
                  [{"t": CLS[a], "ct": CLS[b], **{t: cellp(t, a, b) for t in TIERS}} for a in (2, 1, 0) for b in (2, 1, 0)],
           "conv": [], "force": []}
    for won in (1, 0):
        for side in (0, 1):
            row = {"after": "win" if won else "loss", "side": "CT" if side else "T"}
            for t in TIERS:
                n, a, b, s = conv.get((t, won, side), (0, 0, 0, 0))
                row[t] = {"n": n, "next": r4(a / n) if n else None, "two": r4(b / n) if n else None,
                          "rd": r4(s / n) if n else None, **({"thin": True} if n < THIN else {})}
            out["conv"].append(row)
    for band in BANDS:
        for sd in (2, 0, 1):
            row = {"band": band, "side": ("T", "CT", "all")[sd]}
            for t in TIERS:
                c = {}
                for k, nm in ((0, "save"), (1, "force"), (2, "full")):
                    m = frc.get((t, band, sd, k))
                    v, se = m.done() if m else (None, None)
                    c[nm] = {"n": m.n if m else 0, "v": r4(v), "se": r4(se)}
                sv, fo = c["save"], c["force"]
                if sv["v"] is not None and fo["v"] is not None:
                    c["d"] = r4(fo["v"] - sv["v"])
                    c["se"] = r4(math.sqrt((fo["se"] or 0) ** 2 + (sv["se"] or 0) ** 2)) if fo["se"] and sv["se"] else None
                if min(sv["n"], fo["n"]) < THIN:
                    c["thin"] = True
                row[t] = c
            out["force"].append(row)
    return out


def main():
    out = build()
    OUT.write_text(json.dumps(out, separators=(",", ":"), allow_nan=False) + "\n")
    print(f"cs2_econ: {out['tiers']['all']['maps']} maps, {out['tiers']['all']['rounds']} rounds through {out['through']}")
    for r in out["buy"]:
        print(f"  T {r['t']:6} v CT {r['ct']:6} " + "  ".join(f"{t} {r[t]['p'] or 0:.3f} n{r[t]['n']}" for t in TIERS))
    for r in out["conv"]:
        print("  pistol", r["after"], r["side"], "  ".join(f"{t} {r[t]['next']} {r[t]['two']}" for t in ("all", "c")))
    for r in out["force"]:
        a = r["all"]
        print("  after", r["band"], r["side"], "save", a["save"]["n"], a["save"]["v"], "force", a["force"]["n"], a["force"]["v"],
              "d", a.get("d"), "se", a.get("se"), "| c:", r["c"].get("d"), r["c"].get("se"), r["c"].get("thin", ""))


if __name__ == "__main__":
    main()
