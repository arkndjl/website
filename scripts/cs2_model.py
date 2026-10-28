#!/usr/bin/env python3
"""Counter-Strike ratings, ARK Ranking and match chances (the COUNTER-STRIKE ARKBOARD), from scripts/cs2_data.py.

    python3 scripts/cs2_model.py --fit   # backtest: tune Aug 2024 - Jun 2025, held out Jul 2025 on -> data/cs2_fit.json
    python3 scripts/cs2_model.py         # build data/cs2.json (ARK Ranking, matches, results, model card)

The rating (scored against Valve's VRS points and a team-name Elo, out of sample):
  - Player Elo. Every player carries a rating from team to team; a roster's strength is the mean of its five. A new
    player's K starts at Kmax and falls toward Kmin over ~n0 series. A series that joins a bo3.gg match
    (scripts/cs2_bo3.py) updates once per map on round share (x kmap of K each), so 13-3 counts more than 13-11:
    held out .5903 -> .5673 on its own (Oct 28 2026). Players first seen after the burn-in start at
    mu_new (most new names are tier-2 and below), and every player starts from Valve's 2022-23 sample season
    (data/matchdata_sample_20230829.json in Valve's repo, played forward with the same rules).
  - Region offsets (Europe / Americas / Asia, Valve's regions), moved only by inter-region series.
  - Team map rating (cs2_bo3.TeamMaps): bo3.gg team Elo on every map since Jun 2020, round share, team x map offsets,
    series chance through a greedy veto; a third logit term (0 when a series has no bo3 match): .5673 -> .5593.
  - Match chance: logistic on the rating gap plus Valve's VRS points gap (the snapshot before the day) plus the team
    map logit, weights fit separately for series between two VRS top-50 teams and the rest.
FAILED (weight 0, numbers in data/cs2_fit.json): team-name Elo beside player Elo, roster continuity, inactivity decay,
Bo1/Bo3/Bo5 slopes (tested on the 2022-23 sample, the only history with maps), Kalman player ratings.
"""
import bisect
import datetime as dt
import gzip
import json
import math
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cs2_data import CACHE, UA, VRS, key  # noqa: E402
import cs2_bo3  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
HIST = ROOT / "scripts" / "data" / "cs2_history.json.gz"
FIT = ROOT / "data" / "cs2_fit.json"
OUT = ROOT / "data" / "cs2.json"
LOGOS = ROOT / "static" / "img" / "cs2"
SAMPLE = VRS / "data" / "matchdata_sample_20230829.json"
TUNE = ("2024-08-07", "2025-06-30")
HELD = ("2025-07-01", "2099-12-31")
BURN = "2024-03-15"
TOP = 50
DEF = {"K": 480, "Kmin": 144, "n0": 100, "mu_new": -100, "Kr": 8, "warm": 1.0, "kmap": 0.6, "span": 0.4}
OLD = {"K": 160, "Kmin": 32, "n0": 100, "mu_new": -100, "Kr": 8, "warm": 1.0}  # the Oct 26 series-level model


def day(d):
    return dt.date.fromisoformat(d).toordinal()


def kfac(p, n):
    return p["Kmin"] + (p["K"] - p["Kmin"]) * math.exp(-n / p["n0"])


def warm_start(p):
    """Valve's 2022-23 sample season played forward (nicks join the live rosters); centred on its mean."""
    if not SAMPLE.exists() or not p.get("warm"):
        return {}
    d = json.load(open(SAMPLE))
    pl, pn = {}, defaultdict(int)
    for m in sorted(d["matches"], key=lambda m: m["matchStartTime"]):
        ra = [x["nick"] for x in m["team1Players"]]
        rb = [x["nick"] for x in m["team2Players"]]
        if len(ra) < 3 or len(rb) < 3:
            continue
        xa = sum(pl.get(q, p["mu_new"]) for q in ra) / len(ra)
        xb = sum(pl.get(q, p["mu_new"]) for q in rb) / len(rb)
        e = 1 / (1 + 10 ** (-(xa - xb) / 400))
        s = 1 if m["winningTeam"] == 1 else 0
        for ros, sg in ((ra, 1), (rb, -1)):
            for q in ros:
                pl[q] = pl.get(q, p["mu_new"]) + sg * kfac(p, pn[q]) * (s - e)
                pn[q] += 1
    mean = sum(pl.values()) / len(pl)
    return {q: (v - mean) * p["warm"] for q, v in pl.items()}


class Vrs:
    def __init__(self, vrs):
        self.dates = sorted(vrs)
        self.tab = {d: {} for d in self.dates}
        self.reg = defaultdict(dict)
        for d in self.dates:
            for rk, n, pts, ros, rg in vrs[d]:
                self.tab[d].setdefault(key(n), (rk, pts, n, ros))
                if rg:
                    self.reg[key(n)][d] = rg

    def before(self, date):
        i = bisect.bisect_left(self.dates, date) - 1
        return self.dates[i] if i >= 0 else None

    def get(self, k, date):
        v = self.before(date)
        return self.tab[v].get(k) if v else None

    def region(self, k, date):
        m = self.reg.get(k)
        if not m:
            return None
        v = self.before(date) or self.dates[0]
        ds = [x for x in m if x <= v]
        return m[max(ds)] if ds else m[min(m)]


def replay(series, vrs, p, ignore_warm=False, bo3=None):
    """Play every series forward. -> (rows: one per series with the pre-series gap, state at the end).
    With bo3 (cs2_bo3.Bo3): a series that joins a bo3.gg match updates the players once per map on round share (K x
    kmap each), and each row carries t, the bo3 team map rating's series logit through the veto (0 if not joined)."""
    warm = {} if ignore_warm else warm_start(p)
    tview, tm = {}, None
    if bo3 is not None:
        joined = bo3.join(series)
        ask = defaultdict(list)
        for i, m in joined.items():
            ask[m[0]].append(i)
        tm = cs2_bo3.TeamMaps(bo3)
        tview = tm.play(ask=ask)
    pl, pn, lastros, roff, team = {}, defaultdict(int), {}, defaultdict(float), {}
    hist = defaultdict(list)  # team key -> [(date, rating after)]
    rows = []
    for i, r in enumerate(series):
        d, a, b, y, ra, rb = r[:6]
        ka, kb = key(a), key(b)
        ra = ra or lastros.get(ka)
        rb = rb or lastros.get(kb)
        if ra:
            lastros[ka] = ra
        if rb:
            lastros[kb] = rb

        def pv(q):
            if q not in pl:
                pl[q] = warm.get(q, 0.0 if d < BURN else p["mu_new"])
            return pl[q]

        def tr(ros, k):
            return sum(pv(q) for q in ros) / len(ros) if ros else team.get(k, p["mu_new"])

        rga, rgb = vrs.region(ka, d), vrs.region(kb, d)
        sa = tr(ra, ka) + (roff[rga] if rga else 0)
        sb = tr(rb, kb) + (roff[rgb] if rgb else 0)
        e = 1 / (1 + 10 ** (-(sa - sb) / 400))
        s = 1 - y
        va, vb = vrs.get(ka, d), vrs.get(kb, d)
        t = 0.0
        if i in tview:
            t = tview[i][0] if bo3.k(tview[i][1]) == ka else -tview[i][0]
        rows.append({"i": i, "d": d, "a": ka, "b": kb, "x": (sa - sb) / 400,
                     "v": ((va[1] if va else 400) - (vb[1] if vb else 400)) / 400, "t": t,
                     "top": bool(va and vb and va[0] <= TOP and vb[0] <= TOP), "s": s, "r": r})
        team[ka] = team.get(ka, p["mu_new"]) + 32 * (s - e)
        team[kb] = team.get(kb, p["mu_new"]) - 32 * (s - e)
        if p["Kr"] and rga and rgb and rga != rgb:
            roff[rga] += p["Kr"] * (s - e)
            roff[rgb] -= p["Kr"] * (s - e)
        ups = bo3.map_updates(i, ka, p["span"]) if bo3 is not None else None
        if ups:
            for sm in ups:
                em = 1 / (1 + 10 ** (-(tr(ra, ka) - tr(rb, kb) + (roff[rga] if rga else 0)
                                       - (roff[rgb] if rgb else 0)) / 400))
                for ros, sg in ((ra, 1), (rb, -1)):
                    for q in ros or []:
                        pl[q] = pv(q) + sg * p["kmap"] * kfac(p, pn[q]) * (sm - em)
        else:
            for ros, sg in ((ra, 1), (rb, -1)):
                for q in ros or []:
                    pl[q] = pv(q) + sg * kfac(p, pn[q]) * (s - e)
        for ros in (ra, rb):
            for q in ros or []:
                pn[q] += 1
        for k, ros, rg in ((ka, ra, rga), (kb, rb, rgb)):
            hist[k].append((d, tr(ros, k) + (roff[rg] if rg else 0)))
    return rows, {"pl": pl, "pn": pn, "lastros": lastros, "roff": dict(roff), "team": team, "hist": hist, "tm": tm}


def fitlog(X, s, l2=1e-3):
    w = np.zeros(X.shape[1])
    for _ in range(60):
        q = 1 / (1 + np.exp(-X @ w))
        g = X.T @ (q - s) + l2 * w
        H = (X * (q * (1 - q))[:, None]).T @ X + l2 * np.eye(len(w))
        w -= np.linalg.solve(H, g)
    return w


def ll(q, s):
    q = np.clip(q, 1e-6, 1 - 1e-6)
    return -(s * np.log(q) + (1 - s) * np.log(1 - q))


def cols(rows, kind):
    x = np.array([r["x"] for r in rows])
    v = np.array([r["v"] for r in rows])
    t = np.array([r.get("t", 0.0) for r in rows])
    return {"ark": x[:, None], "vrs": v[:, None], "blend2": np.column_stack([x, v]),
            "blend": np.column_stack([x, v, t])}[kind]


def tiered(train, test, kind):
    """Fit the logistic separately for top-50 pairs and the rest; -> (chances on test, weights)."""
    out = np.zeros(len(test))
    ws = {}
    for tier in (True, False):
        tr = [r for r in train if r["top"] == tier]
        idx = [i for i, r in enumerate(test) if r["top"] == tier]
        w = fitlog(cols(tr, kind), np.array([r["s"] for r in tr]))
        ws["top" if tier else "rest"] = [round(float(z), 4) for z in w]
        if idx:
            out[idx] = 1 / (1 + np.exp(-cols([test[i] for i in idx], kind) @ w))
    return out, ws


def tstat(dl):
    return float(dl.mean() / (dl.std() + 1e-12) * math.sqrt(len(dl)))


def fit():
    H = json.load(gzip.open(HIST))
    series = [r for r in H["series"] if r[6] == "vrs"]
    vrs = Vrs(H["vrs"])
    p = dict(DEF)
    win = lambda rows, w: [r for r in rows if w[0] <= r["d"] <= w[1]]  # noqa: E731
    bo3 = cs2_bo3.Bo3()
    rows, _ = replay(series, vrs, p, bo3=bo3)
    tr, he = win(rows, TUNE), win(rows, HELD)
    s = np.array([r["s"] for r in he])
    preds = {}
    preds["VRS points"], _ = tiered(tr, he, "vrs")
    preds["ARK rating"], _ = tiered(tr, he, "ark")
    preds["ARK + VRS"], wts = tiered(tr, he, "blend")
    # comparison ratings, same windows
    preds["ARK + VRS without the team map term"], _ = tiered(tr, he, "blend2")
    r2, _ = replay(series, vrs, OLD)
    preds["Oct 26 model: series-level player Elo + VRS"], _ = tiered(win(r2, TUNE), win(r2, HELD), "blend2")
    r2, _ = replay(series, vrs, dict(p, kmap=1.0))
    preds["series-level player Elo, K %d-%d" % (p["K"], p["Kmin"])], _ = tiered(win(r2, TUNE), win(r2, HELD), "ark")
    preds["team-name Elo"] = team_elo(series, vrs, win)
    joined = np.array([r["i"] in bo3.joined for r in he])
    subsets = {"all": [True] * len(he), "joined": joined, "top50": [r["top"] for r in he],
               "top20": [bool((va := vrs.get(r["a"], r["d"])) and (vb := vrs.get(r["b"], r["d"])) and va[0] <= 20
                              and vb[0] <= 20) for r in he]}
    score = {}
    base = ll(preds["VRS points"], s)
    ours = ll(preds["ARK + VRS"], s)
    for sub, m in subsets.items():
        m = np.array(m)
        score[sub] = {"n": int(m.sum()), "models": []}
        for nm, q in preds.items():
            l = ll(q, s)
            score[sub]["models"].append({
                "name": nm, "ll": round(float(l[m].mean()), 4),
                "acc": round(float(((q[m] > .5) == (s[m] == 1)).mean()), 4),
                "vsVrs": round(float((l - base)[m].mean()), 4), "tVrs": round(tstat((l - base)[m]), 2),
                "vsArk": round(float((l - ours)[m].mean()), 4), "tArk": round(tstat((l - ours)[m]), 2)})
    # live weights: refit on every scored series (tune + held out)
    _, live = tiered(win(rows, ("2024-08-07", "2099-12-31")), he[:1], "blend")
    cal = calib(preds["ARK + VRS"], s)
    old = ll(preds["Oct 26 model: series-level player Elo + VRS"], s)
    months = sorted({r["d"][:7] for r in he})
    mwin = sum(float(ours[[r["d"][:7] == mo for r in he]].mean()) < float(old[[r["d"][:7] == mo for r in he]].mean())
               for mo in months)
    out = {"params": p, "teamMaps": cs2_bo3.TM, "nJoined": len(bo3.joined), "nSeriesFit": len(series),
           "monthsBeatOld": [mwin, len(months)], "weights": live, "weightsTune": wts, "tune": list(TUNE), "held": [HELD[0], rows[-1]["d"]],
           "nTune": len(tr), "score": score, "calibration": cal,
           "failed": [
               {"term": "team-name Elo beside player Elo", "note": "player + team: held t +0.2 (all), +0.4 (top 50)"},
               {"term": "roster continuity", "note": "share of the five kept from the last series: tune -0.0002"},
               {"term": "inactivity decay", "note": "pull toward 0 after 30 days away: tune +-0.0001, held +0.0006 top 50"},
               {"term": "Bo1 / Bo3 / Bo5 slopes", "note": "2022-23 sample (maps known): Bo1 slope 1.21 vs Bo3 1.26, held t -0.9"},
               {"term": "team map Elo without round share", "note": "map wins only: tune .5822 vs .5801 on round share"},
               {"term": "player Elo per map on wins only", "note": "no round share: tune .5845 vs .5618"},
               {"term": "rating start by bo3 tier", "note": "lower start for tier-c/d teams: tune +.0006"},
               {"term": "Kalman player ratings", "note": "variance per player: tune .5985 vs Elo .5869"},
               {"term": "closing line", "note": "no free CS2 odds history, so no picks"}]}
    FIT.write_text(json.dumps(out, indent=1))
    for sub, v in score.items():
        print(sub, v["n"])
        for m in v["models"]:
            print(f"  {m['name']:38s} {m['ll']:.4f} acc {m['acc']:.3f} vs VRS {m['vsVrs']:+.4f} t {m['tVrs']:+.2f}"
                  f"  vs ARK+VRS {m['vsArk']:+.4f} t {m['tArk']:+.2f}")
    print("weights", live)


def team_elo(series, vrs, win):
    t, rows = {}, []
    for r in series:
        d, a, b, y = r[:4]
        ka, kb = key(a), key(b)
        xa, xb = t.get(ka, 0.0), t.get(kb, 0.0)
        e = 1 / (1 + 10 ** (-(xa - xb) / 400))
        s = 1 - y
        va, vb = vrs.get(ka, d), vrs.get(kb, d)
        rows.append({"d": d, "x": (xa - xb) / 400, "v": 0, "s": s,
                     "top": bool(va and vb and va[0] <= TOP and vb[0] <= TOP)})
        t[ka] = xa + 48 * (s - e)
        t[kb] = xb - 48 * (s - e)
    q, _ = tiered(win(rows, TUNE), win(rows, HELD), "ark")
    return q


def calib(q, s):
    out = []
    for lo in np.arange(0.5, 1.0, 0.05):
        qq = np.where(q >= 0.5, q, 1 - q)
        ss = np.where(q >= 0.5, s, 1 - s)
        m = (qq >= lo) & (qq < lo + 0.05)
        if m.sum():
            out.append({"bin": round(float(lo), 2), "n": int(m.sum()), "exp": round(float(qq[m].mean()), 3),
                        "obs": round(float(ss[m].mean()), 3)})
    return out


def fair(q):
    """American odds without the vig for chance q."""
    q = min(max(q, 0.01), 0.99)
    return round(-100 * q / (1 - q)) if q >= 0.5 else round(100 * (1 - q) / q)


def fetch_logos(keys, logos):
    """Liquipedia's team icons for the ranked teams, once each (a few a run, 2 s apart)."""
    LOGOS.mkdir(parents=True, exist_ok=True)
    got = 0
    for k in keys:
        f = LOGOS / f"{k}.png"
        if f.exists() or k not in logos or got >= 25:
            continue
        try:
            req = urllib.request.Request(logos[k], headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                f.write_bytes(r.read())
            got += 1
            time.sleep(2)
        except Exception as e:
            print("logo", k, e, file=sys.stderr)


def build():
    H = json.load(gzip.open(HIST))
    fitj = json.loads(FIT.read_text())
    p = fitj["params"]
    W = {k: np.array(v) for k, v in fitj["weights"].items()}
    vrs = Vrs(H["vrs"])
    bo3 = cs2_bo3.Bo3()
    rows, st = replay(H["series"], vrs, p, bo3=bo3)
    tm = st["tm"]
    today = dt.date.today().isoformat()
    last = vrs.dates[-1]
    vt = vrs.tab[last]

    def strength(k, ros=None):
        ros = ros or st["lastros"].get(k)
        rg = vrs.region(k, today)
        x = (sum(st["pl"].get(q, p["mu_new"]) for q in ros) / len(ros)) if ros else st["team"].get(k, p["mu_new"])
        x += st["roff"].get(rg, 0) if rg else 0
        v = vt.get(k)
        return x / 400, (v[1] if v else 400) / 400, v

    def tmap(ka, kb, bo):
        """bo3 team map rating, series logit through the veto (0 when either team has no bo3 id)."""
        ta, tb = bo3.team_of(ka), bo3.team_of(kb)
        return tm.chance(ta, tb, bo, today) if ta and tb and ta != tb else 0.0

    def logit_ab(ka, kb, bo=3, w=None):
        xa, va, ra = strength(ka)
        xb, vb, rb = strength(kb)
        if w is None:
            w = W["top"] if (ra and rb and ra[0] <= TOP and rb[0] <= TOP) else W["rest"]
        return w[0] * (xa - xb) + w[1] * (va - vb) + w[2] * tmap(ka, kb, bo)

    def chance(ka, kb, bo=3):
        return float(1 / (1 + math.exp(-logit_ab(ka, kb, bo))))

    # who is ranked: played in the last 120 days, 15+ series since Feb 2024
    lastd, n, form = {}, defaultdict(int), defaultdict(list)
    names = {}
    cut = (dt.date.today() - dt.timedelta(days=120)).isoformat()
    for r in rows:
        for k, nm, won in ((r["a"], r["r"][1], r["s"] == 1), (r["b"], r["r"][2], r["s"] == 0)):
            lastd[k] = r["d"]
            n[k] += 1
            names.setdefault(k, nm)
            if r["r"][6] == "vrs" or k in vt:
                names[k] = nm if r["r"][6] == "vrs" else names[k]
            form[k].append((r["d"], won))
    for k, v in vt.items():
        names[k] = v[2]
    cands = [k for k in lastd if lastd[k] >= cut and n[k] >= 15 and st["lastros"].get(k)]
    wt = W["top"]
    z = {k: wt[0] * strength(k)[0] + wt[1] * strength(k)[1] for k in cands}
    order = sorted(cands, key=lambda k: -z[k])
    # ARK: Bo3 chance against the top 20 (top-50 weights, veto included); the top 20 re-picked once on ARK itself
    vs = {}
    for _ in range(2):
        ref = order[:20]
        for k in order[:150]:
            vs[k] = [logit_ab(k, j, 3, wt) for j in ref if j != k]
        order = sorted(order[:150], key=lambda k: -np.mean([1 / (1 + math.exp(-x)) for x in vs[k]])) + order[150:]
    ref = order[:20]
    d30 = (dt.date.today() - dt.timedelta(days=30)).isoformat()

    def moved(k):  # rating change over 30 days (None if no series before then)
        before = [x for d, x in st["hist"][k] if d < d30]
        return strength(k)[0] * 400 - before[-1] if before else None
    # against the top 20's own move, so a pool-wide drift (new players entering low, region offsets) nets out
    drift = float(np.mean([m for m in map(moved, ref) if m is not None] or [0]))
    teams = []
    for i, k in enumerate(order[:100]):
        ark = float(np.mean([1 / (1 + math.exp(-x)) for x in vs[k]]))
        h = st["hist"][k]
        m30 = moved(k)
        x_now = strength(k)[0] * 400
        y90 = [w for d, w in form[k] if d >= (dt.date.today() - dt.timedelta(days=90)).isoformat()]
        v = vt.get(k)
        teams.append({"rk": i + 1, "k": k, "n": names.get(k, k), "ros": st["lastros"].get(k),
                      "rg": vrs.region(k, today), "ark": round(ark, 4),
                      "elo": round(1500 + float(np.mean(vs[k])) * 400 / math.log(10)),
                      "pl": round(x_now), "d30": round(m30 - drift) if m30 is not None else None,
                      "vrk": v[0] if v else None, "vpts": round(v[1]) if v else None,
                      "w90": sum(y90), "l90": len(y90) - sum(y90),
                      "form": "".join("W" if w else "L" for _, w in form[k][-10:]), "last": lastd[k],
                      "logo": (LOGOS / f"{k}.png").exists()})
    fetch_logos([t["k"] for t in teams], H.get("logos", {}))
    for t in teams:
        t["logo"] = (LOGOS / f"{t['k']}.png").exists()
    rank = {t["k"]: t["rk"] for t in teams}
    matches = []
    for m in H.get("upcoming", []):
        ka, kb = key(m["a"]), key(m["b"])
        if ka not in names and kb not in names:
            continue
        bo = int(m["fmt"][2:]) if (m.get("fmt") or "").startswith("Bo") and m["fmt"][2:].isdigit() else 3
        pa = chance(ka, kb, bo)
        matches.append(dict(m, a=names.get(ka, m["a"]), b=names.get(kb, m["b"]), ka=ka, kb=kb, pa=round(pa, 4), fair=[fair(pa), fair(1 - pa)], rka=rank.get(ka), rkb=rank.get(kb),
                            la=(LOGOS / f"{ka}.png").exists(), lb=(LOGOS / f"{kb}.png").exists()))
    # Novig's moneyline where it lists the series (none listed as of Oct 27 2026; scripts/novig.py archives any it does)
    try:
        import novig
        nvg = novig.h2h("cs2")
    except Exception as ex:  # noqa: BLE001
        print("novig cs2 skipped:", ex)
        nvg = []
    for m in matches:
        nv = novig.h2h_price(nvg, m["a"], m["b"], team=True) if nvg else None
        if nv:
            m["nv"] = nv
    # results: Liquipedia's finished series with the chance the model gave before each
    res = []
    for r in rows:
        if r["r"][6] != "lp":
            continue
        w = W["top"] if r["top"] else W["rest"]
        pa = 1 / (1 + math.exp(-(w[0] * r["x"] + w[1] * r["v"] + w[2] * r["t"])))
        rr = r["r"]
        res.append({"ts": rr[8], "a": names.get(r["a"], rr[1]), "b": names.get(r["b"], rr[2]), "ka": r["a"], "kb": r["b"], "sa": rr[9], "sb": rr[10],
                    "fmt": rr[7], "event": rr[11], "pa": round(float(pa), 4), "fair": [fair(pa), fair(1 - pa)], "rka": rank.get(r["a"]),
                    "rkb": rank.get(r["b"]), "la": (LOGOS / f"{r['a']}.png").exists(),
                    "lb": (LOGOS / f"{r['b']}.png").exists()})
    res = sorted(res, key=lambda x: -x["ts"])[:60]
    nlp = sum(1 for r in rows if r["r"][6] == "lp")
    out = {"asof": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "vrsDate": last, "lastVrs": H["lastVrs"],
           "nSeries": len(rows), "nLp": nlp, "first": rows[0]["d"], "teams": teams,
           "matches": sorted(matches, key=lambda m: m["ts"]), "results": res,
           "roff": {k: round(v) for k, v in st["roff"].items()},
           "fit": {k: fitj.get(k) for k in ("score", "calibration", "failed", "weights", "params", "tune", "held",
                                             "nTune", "nJoined", "nSeriesFit", "teamMaps", "monthsBeatOld")}}
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    print(f"{len(teams)} teams, {len(matches)} matches, {len(res)} results; #1 {teams[0]['n']} {teams[0]['ark']}")


if __name__ == "__main__":
    fit() if "--fit" in sys.argv else build()
