#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Counter-Strike economic value: player transfer values priced on prize money, team (roster) values, and value
change since each player joined (data/cs2_value.json; the "transfer values" group on the COUNTER-STRIKE ARKBOARD).

    python3 scripts/cs2_value.py --fit   # prize curve + fee fit backtests -> data/cs2_value_fit.json
    python3 scripts/cs2_value.py         # live -> data/cs2_value.json (run after scripts/cs2_players.py)

Revenue side (no fees needed): Valve's Regional Standings detail pages list each roster's prize winnings by event
(top ten per 6-month window, every snapshot since Aug 2024, so events since Feb 2024). Deduplicated into a prize
ledger (scripts/data/cs2_prizes.json.gz). The prize curve: a roster's prize money over the next 182 days on its five's
mean player rating (scripts/cs2_players.py), relative to the mean tier-1 starter (the VRS top 20's fives) that day:
Poisson, log link, rating + rating^2, monthly snapshots. Held out walk forward against the same curve on VRS points.

Player value = marginal revenue product: the prize money a team of four average tier-1 starters earns a year with
him minus with a replacement-level player, for two seasons (aging curve from cs2_players, 15%/yr discount), times
a multiple A (sponsor and brand value per prize dollar, and contract length) fit on publicly reported buyouts
(data/cs2_fees.json; group deals priced as the sum of the players), with the replacement level (tier-1 mean minus
q tier-1 SDs) picked on the same fees. Validation: leave one fee out, q and A refit each time.

Team value = the sum of the current five (Valve rosters in data/cs2.json). "At signing" = the same value at the
player's first map of his current stint with the team (bo3.gg maps); stints that began before the ratings had six
months of maps start at JUL0 and are flagged. Contract terms are not public and are not modelled.
"""
import datetime as dt
import gzip
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cs2_bo3  # noqa: E402
import cs2_players as P  # noqa: E402
from cs2_data import VRS, key  # noqa: E402
import names  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "scripts" / "data" / "cs2_prizes.json.gz"
FIT = ROOT / "data" / "cs2_value_fit.json"
OUT = ROOT / "data" / "cs2_value.json"
JUL0 = "2024-07-01"  # ratings need ~6 months of maps (stats start Jan 2024)
FEE0 = "2024-04-01"  # fee anchors: 3+ months of maps before the move (electroNic, Apr 2024)
TOP = 20             # tier-1 reference: the VRS global top 20's fives
DISC = 0.85
H = 182


# ---------------------------------------------------------------- prize ledger from Valve's detail pages
def parse_vrs():
    """-> {"snaps": [[date, team key, name, roster, rank value]], "prizes": [[team key, event date, usd]]}."""
    snaps, led = [], {}
    for f in sorted(VRS.glob("live/*/details/*/*.md")):
        t = f.read_text(errors="replace")
        nm = re.search(r"Team Name: (.*?)<br", t)
        ro = re.search(r"Roster: (.*?)<br", t)
        fr = re.search(r"Final Rank Value:\s*([\d.]+)", t)
        if not (nm and ro and fr):
            continue
        tk = key(nm.group(1).strip())
        snaps.append([f.parent.name.replace("_", "-"), tk, nm.group(1).strip(),
                      [x.strip() for x in ro.group(1).split(",")], float(fr.group(1))])
        i = t.find("Top ten winnings")
        if i < 0:
            continue
        for m in re.finditer(r"^\|\s*(\d{4}-\d\d-\d\d)\s*\|\s*[\d.]+\s*\|\s*\$([\d,.]+)", t[i:], re.M):
            led[(tk, m.group(1), m.group(2))] = float(m.group(2).replace(",", ""))
    return {"snaps": snaps, "prizes": [[k[0], k[1], round(v, 2)] for k, v in sorted(led.items())]}


def ledger():
    """Parse the VRS clone when it is there (cs2 workflow cache), merge with the committed ledger, save."""
    old = {"snaps": [], "prizes": []}
    if LEDGER.exists():
        with gzip.open(LEDGER, "rt") as fh:
            old = json.load(fh)
    if VRS.exists():
        new = parse_vrs()
        pz = {(a, b, c) for a, b, c in old["prizes"]} | {(a, b, c) for a, b, c in new["prizes"]}
        sn = {(s[0], s[1]): s for s in old["snaps"]}
        sn.update({(s[0], s[1]): s for s in new["snaps"]})
        old = {"snaps": sorted(sn.values()), "prizes": sorted(pz)}
        with gzip.open(LEDGER, "wt") as fh:
            json.dump(old, fh, separators=(",", ":"))
    return old


# ---------------------------------------------------------------- shared state
class Ctx:
    def __init__(self):
        fitj = json.loads(P.FIT.read_text())
        self.p = fitj["params"]
        self.ag = fitj["aging"]
        self.a = self.p["a"]
        self.M = P.Maps()
        beta = np.array([fitj["beta"][k] for k in P.STATS])
        self.c = P.contributions(self.M, beta, np.array(fitj["mline"]), self.p.get("pm", 0.0))
        self.bo3 = cs2_bo3.Bo3()
        self.nk, self.nkt = P.nick_index(self.M, self.bo3)
        self.pdir = P.load_pdir()
        L = ledger()
        self.snaps = defaultdict(list)
        for s in L["snaps"]:
            self.snaps[s[0]].append(s)
        self.sdates = sorted(self.snaps)
        self.prizes = defaultdict(list)
        for tk, d, v in L["prizes"]:
            self.prizes[tk].append((P.ordd(d), v))
        self.last_prize = max(P.ordd(d) for _, d, _ in L["prizes"])
        self._th = {}

    def th(self, T):
        if T not in self._th:
            self._th[T] = P.ratings(self.M, self.c, T, self.p)[0]
        return self._th[T]

    def pid(self, nick, tk):
        k = names.key(nick)
        return self.nkt.get((k, tk), self.nk.get(k))

    def snap_at(self, T):
        """The latest VRS snapshot on or before day T (rosters ranked by rank value)."""
        ds = [d for d in self.sdates if P.ordd(d) <= T] or self.sdates[:1]
        return sorted(self.snaps[ds[-1]], key=lambda s: -s[4])

    def five_mean(self, ros, tk, th):
        ix = [self.pid(q, tk) for q in ros]
        v = [th[i] for i in ix if i is not None]
        return float(np.mean(v)) if len(v) >= 3 else None

    def tier1(self, T):
        """(mean, sd) of the tier-1 starters' ratings at day T: the VRS top TOP's fives."""
        th = self.th(T)
        v = []
        for s in self.snap_at(T)[:TOP]:
            v += [th[i] for i in (self.pid(q, s[1]) for q in s[3]) if i is not None]
        return float(np.mean(v)), float(np.std(v) or 1)

    def repl(self, T):
        """Replacement level at day T: the mean rating of the VRS 51-100 rosters' starters (a pool a tier-1 team can
        sign from for little or nothing)."""
        th = self.th(T)
        v = [th[i] for s in self.snap_at(T)[50:100] for i in (self.pid(q, s[1]) for q in s[3]) if i is not None]
        return float(np.mean(v))

    def prize_fwd(self, tk, T, days=H):
        return sum(v for d, v in self.prizes.get(tk, []) if T < d <= T + days)


# ---------------------------------------------------------------- prize curve
def poisson(X, y, l2=1e-6, it=60):
    b = np.zeros(X.shape[1])
    b[0] = math.log(max(y.mean(), 1.0))
    for _ in range(it):
        mu = np.exp(np.clip(X @ b, -30, 30))
        g = X.T @ (y - mu) - l2 * b
        Hm = (X * mu[:, None]).T @ X + l2 * np.eye(len(b))
        step = np.linalg.solve(Hm, g)
        b += step
        if np.abs(step).max() < 1e-8:
            break
    return b


def dev(y, mu):
    mu = np.maximum(mu, 1e-9)
    return 2 * np.where(y > 0, y * np.log(np.maximum(y, 1e-9) / mu), 0) - 2 * (y - mu)


def curve_rows(C):
    """One row per (snapshot, roster): rating gap of the five vs tier-1 (x), VRS rank value, prize over next H days."""
    rows = []
    for d in C.sdates:
        T = P.ordd(d)
        if T + H > C.last_prize:
            continue
        th = C.th(T)
        mu1, sd1 = C.tier1(T)
        for s in C.snaps[d]:
            x = C.five_mean(s[3], s[1], th)
            if x is None:
                continue
            rows.append((T, (x - mu1) * C.a / 2, s[4] / 1000, C.prize_fwd(s[1], T)))
    return np.array(rows)


def design(x, kind):
    if kind == "rating":
        return np.column_stack([np.ones(len(x)), x[:, 1], x[:, 1] ** 2])
    if kind == "vrs":
        return np.column_stack([np.ones(len(x)), x[:, 2], x[:, 2] ** 2])
    return np.column_stack([np.ones(len(x)), x[:, 1], x[:, 1] ** 2, x[:, 2], x[:, 2] ** 2])


def curve_fit(C):
    R = curve_rows(C)
    print(f"curve rows {len(R)}, snapshots {len(set(R[:, 0]))}", file=sys.stderr)
    cut = P.ordd("2025-07-01")
    tr, te = R[R[:, 0] < cut], R[R[:, 0] >= cut]
    out = {"n": len(R), "nTest": len(te), "held": [dt.date.fromordinal(int(te[:, 0].min())).isoformat(),
                                                   dt.date.fromordinal(int(te[:, 0].max())).isoformat()]}
    y = te[:, 3]
    d0 = dev(y, np.full(len(y), tr[:, 3].mean()))
    res = {}
    for kind in ("rating", "vrs", "both"):
        b = poisson(design(tr, kind), tr[:, 3])
        mu = np.exp(design(te, kind) @ b)
        res[kind] = dev(y, mu)
    base = res["rating"]
    tests = []
    for kind, nm in (("rating", "five's rating (live)"), ("vrs", "VRS points"), ("both", "rating + VRS points")):
        dl = res[kind] - base
        tests.append({"name": nm, "d2": round(float(1 - res[kind].sum() / d0.sum()), 3),
                      "t": None if kind == "rating" else round(float(dl.mean() / (dl.std() + 1e-12) * math.sqrt(len(dl))), 1)})
    out["tests"] = tests
    b = poisson(design(R, "rating"), R[:, 3])
    out["b"] = [round(float(v), 5) for v in b]
    out["xmax"] = round(float(R[:, 1].max()), 2)
    print("curve", out, file=sys.stderr)
    return out


def prize_yr(cv, x):
    """Expected prize money a year (USD) for a five whose mean rating is x RWA over the tier-1 starter mean."""
    x = min(x, cv["xmax"])
    b = cv["b"]
    return 365 / H * math.exp(b[0] + b[1] * x + b[2] * x * x)


def mrp(cv, th, age, mu1, repl, a, ag):
    """Prize money added over a replacement-level player (rating repl) in a team of four average tier-1 starters
    (mu1), two seasons (aged, discounted). Gaps in RWA (a/2 x rating units); a five's mean moves by a fifth of the gap."""
    r = (repl - mu1) * a / 2
    tot = 0.0
    for y, x in enumerate(P.project(th, age, ag)):
        g = (x - mu1) * a / 2
        tot += DISC ** y * max(0.0, prize_yr(cv, g / 5) - prize_yr(cv, r / 5))
    return tot


# ---------------------------------------------------------------- fees
def first_map(C, pi, tk, after=0):
    rows = np.where(C.M.p == pi)[0]
    ds = [int(C.M.d[i]) for i in rows if C.bo3.k(int(C.M.team[i])) == tk and C.M.d[i] >= after]
    return min(ds) if ds else None


def fee_points(C, bounds=False):
    fees = json.loads(P.FEES.read_text())["fees"]
    pts = []
    for f in fees:
        if f.get("skip") or (f.get("bound") and not bounds):
            continue
        to = key(f["to"])
        pl = []
        for nick in f["nick"].split("+"):
            pi = C.nk.get(names.key(nick.strip()))
            T = first_map(C, pi, to) if pi is not None else None
            if T is None or T < P.ordd(FEE0):
                pl = None
                break
            pl.append((nick.strip(), pi, T))
        if not pl:
            print("fee skipped (no maps or before", FEE0, "):", f["nick"], file=sys.stderr)
            continue
        T = min(t for _, _, t in pl)
        if bounds and not f.get("bound"):
            continue
        pts.append({"nick": f["nick"], "from": f["from"], "to": f["to"], "usd": f["usd"], "bound": f.get("bound"), "date": dt.date.fromordinal(T).isoformat(),
                    "pl": [(pi, T) for _, pi, T in pl], "n": len(pl)})
    return pts


def fee_mrp(C, cv, pt, q=None):
    """Summed MRP of a deal's players at their move dates; q: replacement = tier-1 mean - q tier-1 SDs instead of
    the live rule (the VRS 51-100 starters' mean)."""
    tot = 0.0
    for pi, T in pt["pl"]:
        th = C.th(T)
        mu1, sd1 = C.tier1(T)
        repl = C.repl(T) if q is None else mu1 - q * sd1
        age = P.ages(C.M, C.pdir, T)[pi]
        tot += mrp(cv, th[pi], age if age == age else 24.0, mu1, repl, C.a, C.ag)
    return tot


def fee_fit(C, cv):
    """A = geometric mean of fee / MRP, replacement level (tier-1 mean - q SDs) picked on the same fees. Leave one fee
    out (q and A refit without it) against the replacement fixed at the VRS 51-100 starters (A only) and a flat price
    per player (no model). The fixed rule misses the SAW trio by x5: buyouts are flatter than prize money."""
    pts = fee_points(C)
    n = len(pts)
    ly = np.log([pt["usd"] for pt in pts])
    npl = np.array([pt["n"] for pt in pts], dtype=float)
    G = np.array([fee_mrp(C, cv, pt) for pt in pts])
    qs = [round(x, 2) for x in np.arange(0.5, 4.01, 0.25)]
    GQ = {q: np.array([fee_mrp(C, cv, pt, q) for pt in pts]) for q in qs}

    def best_q(ix):
        r = []
        for q in qs:
            g = GQ[q][ix]
            if (g > 0).all():
                la = float(np.mean(ly[ix] - np.log(g)))
                r.append((float(np.mean((ly[ix] - la - np.log(g)) ** 2)), q, la))
        return min(r)

    loo = {"live": [], "tuned": [], "flat": []}
    for j in range(n):
        ix = np.array([i for i in range(n) if i != j])
        loo["live"].append(ly[j] - float(np.mean(ly[ix] - np.log(G[ix]))) - math.log(G[j]))
        _, q, la = best_q(ix)
        loo["tuned"].append(ly[j] - la - math.log(GQ[q][j]))
        loo["flat"].append(ly[j] - float(np.mean(ly[ix] - np.log(npl[ix]))) - math.log(npl[j]))
    err = {k: math.sqrt(float(np.mean(np.square(v)))) for k, v in loo.items()}
    e, q, la = best_q(np.arange(n))
    out = {"A": round(math.exp(la), 3), "q": q, "n": n, "rmseLog": round(math.sqrt(e), 3),
           "loo": [{"name": nm, "log": round(err[k], 3), "fx": round(math.exp(err[k]), 2)} for k, nm in
                   (("tuned", "prize MRP, replacement level tuned on the fees (live)"),
                    ("live", "prize MRP, replacement = VRS 51-100 starters"), ("flat", "flat price per player"))],
           "pts": []}
    for j, pt in enumerate(pts):
        out["pts"].append({"nick": pt["nick"].replace("+", ", "), "to": pt["to"], "date": pt["date"], "usd": pt["usd"],
                           "xtv": int(round(math.exp(la) * GQ[q][j], -3)),
                           "loo": int(round(pt["usd"] / math.exp(loo["tuned"][j]), -3))})
    out["checks"] = []
    for pt in fee_points(C, bounds=True):   # reported bounds (not fit): does the live price respect them?
        x = math.exp(la) * fee_mrp(C, cv, pt, q)
        out["checks"].append({"nick": pt["nick"].replace("+", ", "), "to": pt["to"], "date": pt["date"], "bound": pt["bound"],
                              "usd": pt["usd"], "xtv": int(round(x, -3)), "ok": bool(x <= pt["usd"]) if pt["bound"] == "max" else bool(x >= pt["usd"])})
    print("fees", json.dumps(out), file=sys.stderr)
    return out


def fit():
    C = Ctx()
    cv = curve_fit(C)
    fv = fee_fit(C, cv)
    FIT.write_text(json.dumps({"asof": dt.date.today().isoformat(), "curve": cv, "fees": fv}, indent=1))


# ---------------------------------------------------------------- live
def stint_start(C, pi, tk):
    """First map of the player's current run with team tk (a map for another team ends a run)."""
    rows = np.where(C.M.p == pi)[0]
    rows = rows[np.argsort(C.M.d[rows], kind="stable")]
    start = None
    for i in rows[::-1]:
        if C.bo3.k(int(C.M.team[i])) == tk:
            start = int(C.M.d[i])
        else:
            break
    return start


def build():
    fj = json.loads(FIT.read_text())
    cv, fv = fj["curve"], fj["fees"]
    C = Ctx()
    A = fv["A"]
    today = dt.date.today()
    T = today.toordinal() + 1
    th = C.th(T)
    mu1, sd1 = C.tier1(T)
    q = fv["q"]
    repl = mu1 - q * sd1
    age = P.ages(C.M, C.pdir, T)
    cs = json.loads((ROOT / "data" / "cs2.json").read_text())
    pl = json.loads((ROOT / "data" / "cs2_players.json").read_text())
    prow = {r["id"]: r for r in pl["board"] + pl["prospects"]}
    paid = defaultdict(dict)
    for f in json.loads(P.FEES.read_text())["fees"]:
        if f.get("bound"):
            continue
        ns = f["nick"].split("+")
        for nick in ns:
            paid[key(f["to"])][names.key(nick.strip())] = int(round(f["usd"] / len(ns), -3))
    j0 = P.ordd(JUL0)
    teams, signs = [], []
    for t in cs["teams"]:
        if t.get("tier", 4) > 3 or not t.get("ros"):
            continue
        tk = t["k"]
        five = []
        for nick in t["ros"]:
            pi = C.pid(nick, tk)
            if pi is None:
                five.append(None)
                continue
            pid = int(C.M.pids[pi])
            a0 = age[pi] if age[pi] == age[pi] else 24.0
            now = A * mrp(cv, th[pi], a0, mu1, repl, C.a, C.ag)
            s0 = stint_start(C, pi, tk)
            Ts = max(s0 or j0, j0)
            Ts = dt.date.fromordinal(Ts).replace(day=1).toordinal() if Ts > j0 else j0  # monthly rating cache
            ths = C.th(Ts)
            m1s, sd1s = C.tier1(Ts)
            ags = P.ages(C.M, C.pdir, Ts)[pi]
            then = A * mrp(cv, ths[pi], ags if ags == ags else a0 - (T - Ts) / 365.25, m1s, m1s - q * sd1s, C.a, C.ag)
            r = prow.get(pid, {})
            f = paid.get(tk, {}).get(names.key(nick))
            row = {"id": pid, "n": C.M.nick.get(pid) or nick, "ph": r.get("ph"), "nat": r.get("nat"),
                   "age": None if age[pi] != age[pi] else round(float(age[pi]), 1),
                   "rwa": round(float((th[pi] - mu1) * C.a / 2), 2), "rwa0": round(float((ths[pi] - m1s) * C.a / 2), 2),
                   "v": int(round(now, -3)), "v0": int(round(then, -3)),
                   "since": dt.date.fromordinal(s0).isoformat() if s0 else None, "pre": bool(not s0 or s0 < j0),
                   "fee": f,
                   "tm": t["n"], "tk": tk, "tier": t.get("tier", 4), "logo": bool(t.get("logo")), "trk": t.get("rk")}
            five.append(row)
            signs.append(row)
        got = [x for x in five if x]
        if len(got) < 4:
            continue
        v, v0 = sum(x["v"] for x in got), sum(x["v0"] for x in got)
        top = max(got, key=lambda x: x["v"])
        teams.append({"k": tk, "n": t["n"], "rk": t.get("rk"), "tier": t.get("tier", 4), "logo": bool(t.get("logo")),
                      "fl": t.get("fl"), "v": v, "v0": v0, "dv": v - v0, "dp": round(100 * (v - v0) / v0, 1) if v0 >= 50000 else None,
                      "top": top["n"], "topv": top["v"], "nk": len(got),
                      "prize": int(round(C.prize_fwd(tk, T - 365, 365), -2)),
                      "xp": int(round(prize_yr(cv, (C.five_mean(t["ros"], tk, th) - mu1) * C.a / 2), -3)),
                      "paid": sum(x["fee"] or 0 for x in got) or None,
                      "ros": [x["n"] if x else nick for x, nick in zip(five, t["ros"])],
                      "since": min((x["since"] for x in got if x["since"]), default=None)})
    teams.sort(key=lambda r: -r["v"])
    for i, r in enumerate(teams):
        r["vrk"] = i + 1
    signs.sort(key=lambda r: -(r["v"] - r["v0"]))
    out = {"asof": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "jul0": JUL0,
           "repl": round((repl - mu1) * C.a / 2, 2), "teams": teams, "signings": signs,
           "fit": {"A": A, "q": q, "curve": cv, "fees": fv,
                   "prizeYr": {str(x): int(round(prize_yr(cv, x), -3)) for x in (-1.0, -0.5, 0.0, 0.5)}}}
    OUT.write_text(json.dumps(out, separators=(",", ":"), allow_nan=False))
    # one transfer value on the whole page: the players board, prospects and the player model's fee table read this one
    for r in pl["board"] + pl["prospects"]:
        j = int(np.searchsorted(C.M.pids, r["id"]))
        if j < len(C.M.pids) and int(C.M.pids[j]) == r["id"]:
            a0 = age[j] if age[j] == age[j] else 24.0
            r["xtv"] = int(round(A * mrp(cv, th[j], a0, mu1, repl, C.a, C.ag), -3))
    pl["fit"]["value"] = {"n": fv["n"], "fx": fv["loo"][0]["fx"], "pts": fv["pts"]}
    (ROOT / "data" / "cs2_players.json").write_text(json.dumps(pl, separators=(",", ":"), allow_nan=False))
    print(f"teams {len(teams)}: #1 {teams[0]['n']} ${teams[0]['v'] / 1e6:.1f}M; signings {len(signs)}")


if __name__ == "__main__":
    if "--fit" in sys.argv:
        fit()
    else:
        build()
