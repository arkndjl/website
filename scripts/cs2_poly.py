#!/usr/bin/env python3
"""Polymarket CS2 prices as an input to the Counter-Strike match chance (data only, never a betting venue; Noah Oct 29 2026).

    python3 scripts/cs2_poly.py --fit    # backtest + weights -> data/cs2_poly.json (pulls ~12k price histories, cached)
    python3 scripts/cs2_poly.py          # live: today's open Polymarket CS2 moneylines (what cs2_model.build() reads)

Polymarket lists most pro and tier-2 CS2 series (series_id 10310 on gamma-api, Sep 2025 on; earlier ones under the
counter-strike / cs2 tags). The price an hour before the start, against our held-out chance (cs2_model, Jul 2025 on):
our model alone is the better forecast, but the price carries what the model lacks (stand-ins, roster news), mostly
outside the VRS top 50. The blend is a logistic on logit(model) and the price's gap from it, weights by tier, fit on
the first half of the joined series in time and scored on the second half (paired, clustered by day).

Endpoints (public, no key): gamma-api.polymarket.com/events (listing, outcomes, token ids, gameStartTime),
clob.polymarket.com/prices-history (hourly, a few days' window per call). Thin books spike to .5 or 0/1 when empty,
so prices outside .02-.98 are dropped.
"""
import datetime as dt
import gzip
import json
import math
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from cs2_data import key  # noqa: E402

OUT = ROOT / "data" / "cs2_poly.json"
CACHE = ROOT / "scripts" / ".cache" / "cs2_poly"
GAMMA = "https://gamma-api.polymarket.com/events"
CLOB = "https://clob.polymarket.com/prices-history"
SERIES = "10310"
TAGS = ("counter-strike", "cs2")       # listings before the CS2 series existed
LEAD = 3600                            # the price an hour before the start


def get(u, tries=4):
    for k in range(tries):
        try:
            r = subprocess.run(["curl", "-sS", "-m", "30", u], capture_output=True, text=True, timeout=40)
            return json.loads(r.stdout)
        except (ValueError, subprocess.TimeoutExpired):
            time.sleep(2 * (k + 1))
    return None


def moneylines(events):
    """the series moneyline of each event: [{ev, a, b, t0, tok, res}] (a = the first outcome; tok prices a)"""
    out = []
    for e in events:
        for m in e.get("markets", []):
            st, q = m.get("gameStartTime"), m.get("question") or ""
            if not st or not m.get("clobTokenIds"):
                continue
            smt = m.get("sportsMarketType")
            if smt and smt != "moneyline":
                continue
            if not smt and (" vs" not in q or any(w in q.lower() for w in ("map ", "o/u", "total", "handicap"))):
                continue
            outs = json.loads(m["outcomes"])
            if len(outs) != 2 or outs[0] in ("Yes", "No", "Over", "Under"):
                continue
            t0 = int(dt.datetime.fromisoformat(st.replace("+00", "+00:00").replace("Z", "+00:00")).timestamp())
            out.append({"ev": e["id"], "a": outs[0], "b": outs[1], "t0": t0, "tok": json.loads(m["clobTokenIds"])[0],
                        "res": json.loads(m.get("outcomePrices") or "[]"), "bid": m.get("bestBid"), "ask": m.get("bestAsk"),
                        "open": bool(m.get("acceptingOrders"))})
    return out


def listing(q, start, end, step=7):
    seen, out, d0 = set(), [], start
    while d0 < end:
        d1 = d0 + dt.timedelta(days=step)
        off = 0
        while True:
            d = get(f"{GAMMA}?{q}&limit=100&offset={off}&end_date_min={d0}T00:00:00Z&end_date_max={d1}T00:00:00Z")
            if not d:
                break
            out += [e for e in d if e["id"] not in seen]
            seen.update(e["id"] for e in d)
            off += 100
            if len(d) < 100:
                break
        d0 = d1
    return out


def live():
    """open CS2 moneylines starting in the next 3 days: [{a, b, ka, kb, t0, pa}] with pa = Polymarket's chance for a
    (mid of the best bid and ask when the spread is .10 or less)"""
    now = dt.datetime.now(dt.timezone.utc)
    ev = []
    for off in range(0, 1000, 100):
        d = get(f"{GAMMA}?series_id={SERIES}&closed=false&limit=100&offset={off}"
                f"&end_date_min={now:%Y-%m-%dT%H:%M:%SZ}&end_date_max={now + dt.timedelta(days=4):%Y-%m-%dT%H:%M:%SZ}")
        if not d:
            break
        ev += d
        if len(d) < 100:
            break
    out = []
    for m in moneylines(ev):
        if not m["open"] or m["t0"] < now.timestamp() or m["bid"] is None or m["ask"] is None:
            continue
        bid, ask = float(m["bid"]), float(m["ask"])
        if ask - bid > 0.10:
            continue
        pa = (bid + ask) / 2
        if 0.02 < pa < 0.98:
            out.append({"a": m["a"], "b": m["b"], "ka": key(m["a"]), "kb": key(m["b"]), "t0": m["t0"], "pa": round(pa, 4)})
    return out


def blend(q, p, top, fit=None):
    """our chance q with Polymarket's p (both for the same team), tier weights from data/cs2_poly.json"""
    fit = fit if fit is not None else (json.loads(OUT.read_text()) if OUT.exists() else {})
    w = (fit.get("weights") or {}).get("top" if top else "rest")
    if not w or p is None or not 0.02 < p < 0.98:
        return q
    lg = lambda x: math.log(x / (1 - x))  # noqa: E731
    z = w[0] * lg(q) + w[1] * (lg(p) - lg(q))
    return 1 / (1 + math.exp(-z))


def fit():
    import numpy as np
    import cs2_bo3
    import cs2_model as M
    CACHE.mkdir(parents=True, exist_ok=True)
    lp = CACHE / "listing.json.gz"
    if lp.exists():
        ev = json.load(gzip.open(lp))
    else:
        today = dt.date.today()
        ev = listing(f"series_id={SERIES}&closed=true", dt.date(2025, 8, 1), today)
        for t in TAGS:
            ev += listing(f"tag_slug={t}&closed=true", dt.date(2024, 8, 1), dt.date(2025, 11, 1))
        json.dump(ev, gzip.open(lp, "wt"))
    ml = {m["tok"]: m for m in moneylines(ev) if m["res"] in (["1", "0"], ["0", "1"])}
    hp = CACHE / "prices.jsonl"
    have = {}
    if hp.exists():
        for line in open(hp):
            r = json.loads(line)
            have[r["tok"]] = r["h"]
    todo = [m for t, m in ml.items() if t not in have]
    print(f"{len(ml)} moneylines, {len(todo)} price histories to pull")
    with open(hp, "a") as f:
        for i, m in enumerate(todo):
            d = get(f"{CLOB}?market={m['tok']}&startTs={m['t0'] - 3 * 86400}&endTs={m['t0']}&fidelity=60")
            h = [[x["t"], x["p"]] for x in (d or {}).get("history", [])]
            have[m["tok"]] = h
            f.write(json.dumps({"tok": m["tok"], "h": h}) + "\n")
            if i % 500 == 0:
                print(i, flush=True)
    # our held-out chances, exactly as cs2_model --fit scores them
    H = json.load(gzip.open(M.HIST))
    series = [r for r in H["series"] if r[6] == "vrs"]
    rows, _ = M.replay(series, M.Vrs(H["vrs"]), dict(M.DEF), bo3=cs2_bo3.Bo3())
    win = lambda rs, w: [r for r in rs if w[0] <= r["d"] <= w[1]]  # noqa: E731
    he = win(rows, M.HELD)
    q, _ = M.tiered(win(rows, M.TUNE), he, "blend")
    idx = defaultdict(list)
    for r, x in zip(he, q):
        idx[(r["d"], r["a"], r["b"])].append((r, float(x)))
    J, seen = [], set()
    for t, m in ml.items():
        h = have.get(t) or []
        v = [p for ts, p in h if ts <= m["t0"] - LEAD]
        if not v or not 0.02 < v[-1] < 0.98 or m["ev"] in seen:
            continue
        ka, kb = key(m["a"]), key(m["b"])
        d0 = dt.datetime.fromtimestamp(m["t0"], dt.timezone.utc).date()
        hit = None
        for dd in (0, -1, 1, 2):
            d = (d0 + dt.timedelta(days=dd)).isoformat()
            if idx.get((d, ka, kb)):
                hit = (idx[(d, ka, kb)][0], v[-1])
            elif idx.get((d, kb, ka)):
                hit = (idx[(d, kb, ka)][0], 1 - v[-1])
            if hit:
                break
        if not hit:
            continue
        seen.add(m["ev"])
        (r, qa), pa = hit
        J.append({"d": r["d"], "s": r["s"], "q": qa, "p": pa, "top": bool(r["top"])})
    J.sort(key=lambda r: r["d"])
    h = len(J) // 2
    lg = lambda x: math.log(x / (1 - x))  # noqa: E731
    ll = lambda p, s: -(s * math.log(p) + (1 - s) * math.log(1 - p))  # noqa: E731

    def fitlog(X, y):
        w = np.zeros(X.shape[1])
        for _ in range(50):
            z = 1 / (1 + np.exp(-X @ w))
            w -= np.linalg.solve(X.T @ (X * (z * (1 - z))[:, None]) + 1e-6 * np.eye(X.shape[1]), X.T @ (z - y))
        return w

    def tclust(d, rs):
        g = defaultdict(float)
        for r, x in zip(rs, d):
            g[r["d"]] += x
        g = np.array(list(g.values()))
        return round(float(d.mean() / (g.std(ddof=1) * math.sqrt(len(g)) / len(d))), 2)

    X = lambda rs: np.array([[lg(r["q"]), lg(r["p"]) - lg(r["q"])] for r in rs])  # noqa: E731
    X1 = lambda rs: np.array([[lg(r["q"])] for r in rs])  # noqa: E731
    out = {"asof": dt.date.today().isoformat(), "n": len(J), "split": [J[0]["d"], J[h]["d"], J[-1]["d"]],
           "lead": "price 1 hour before the start", "tiers": {}, "weights": {}, "weightsTune": {}}
    for tier, sel in (("top", lambda r: r["top"]), ("rest", lambda r: not r["top"])):
        tr = [r for r in J[:h] if sel(r)]
        te = [r for r in J[h:] if sel(r)]
        if len(tr) < 100 or len(te) < 100:
            continue
        y = lambda rs: np.array([r["s"] for r in rs])  # noqa: E731
        w = fitlog(X(tr), y(tr))
        w1 = fitlog(X1(tr), y(tr))
        zb = 1 / (1 + np.exp(-X(te) @ w))
        z1 = 1 / (1 + np.exp(-X1(te) @ w1))
        lb = np.array([ll(a, b) for a, b in zip(zb, y(te))])
        l1 = np.array([ll(a, b) for a, b in zip(z1, y(te))])
        lq = np.array([ll(r["q"], r["s"]) for r in te])
        lpm = np.array([ll(r["p"], r["s"]) for r in te])
        out["tiers"][tier] = {"nTune": len(tr), "nHeld": len(te), "llModel": round(float(lq.mean()), 4),
                              "llPoly": round(float(lpm.mean()), 4), "llBlend": round(float(lb.mean()), 4),
                              "blendVsModel": round(float((lb - l1).mean()), 4), "t": tclust(lb - l1, te),
                              "modelVsPoly": round(float((lq - lpm).mean()), 4), "tModelVsPoly": tclust(lq - lpm, te)}
        out["weightsTune"][tier] = [round(float(x), 3) for x in w]
        # live weights on every joined series, kept only when the held-out blend beat the recalibrated model (t <= -2)
        if out["tiers"][tier]["t"] <= -2:
            wa = fitlog(X([r for r in J if sel(r)]), y([r for r in J if sel(r)]))
            out["weights"][tier] = [round(float(x), 3) for x in wa]
        print(tier, out["tiers"][tier])
    OUT.write_text(json.dumps(out, indent=1))
    print("weights", out["weights"])


if __name__ == "__main__":
    if "--fit" in sys.argv:
        fit()
    else:
        print(json.dumps(live(), indent=1))
