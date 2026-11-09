#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Counter-Strike event odds (the COUNTER-STRIKE ARKBOARD "event odds" tab): S-tier events simulated from the series
model (scripts/cs2_model.py), Swiss stages paired by Valve's Major rules, then single-elimination playoffs.

    python3 scripts/cs2_events.py --pull   # S-tier event catalog from bo3.gg -> scripts/data/cs2_events.json.gz
    python3 scripts/cs2_events.py --fit    # backtest on past S-tier events -> data/cs2_events_fit.json
    python3 scripts/cs2_events.py          # live: the next Major -> data/cs2_events.json (run after cs2_model.py)

Format (Valve's major-supplemental-rulebook, github.com/ValveSoftware/counter-strike_rules_and_regs; Liquipedia
PGL/2026/Singapore): three 16-team Swiss stages (3 wins advance, 3 losses out; elimination and advancement matches
Bo3, the rest Bo1; Stage 3 all Bo3), the top 8 of each stage seeded 9-16 into the next beside 8 invites (seeds 1-8),
then an 8-team single-elimination playoff (1v8, 4v5 | 2v7, 3v6; Bo3, grand final Bo5). Round 1 pairs seed i v i+8;
rounds 2-3 the highest seed meets the lowest available without a rematch; rounds 4-5 the rulebook's priority table.
Mid-stage seed: record, then Difficulty Score (Buchholz: opponents' wins minus losses), then initial seed.
Invites: Valve's invitation standings (invitation/<yr>/standings_<region>_<date>.md in the VRS repo), seeds by global
standing. Once bo3.gg lists a stage's matches, their pairings and results replace the simulated ones.

Backtest: every 16-team Swiss stage (P advance) and 8-team single-elimination bracket (P title) among bo3.gg's
S-tier events since Mar 2024, from ratings before the stage's first match; weights refit walk-forward on series
before the stage. Scored against the same simulator on Valve's VRS points alone.
"""
import datetime as dt
import gzip
import json
import math
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cs2_bo3  # noqa: E402
from cs2_swiss import bracket, major_tree, noisy, swiss  # noqa: E402
from cs2_data import VRS, key  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CAT = ROOT / "scripts" / "data" / "cs2_events.json.gz"
FIT = ROOT / "data" / "cs2_events_fit.json"
OUT = ROOT / "data" / "cs2_events.json"
UA = "arkndjl.net-arkboard/1.0 (https://arkndjl.net)"
API = "https://api.bo3.gg/api/v1/"
FIRST = "2024-03-01"


def get(path):
    import urllib.request
    for t in range(5):
        try:
            req = urllib.request.Request(API + path, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            if t == 4:
                raise
            print("bo3", path[:70], e, file=sys.stderr)
            time.sleep(2 ** t)


def tournament_matches(tid):
    out, off = [], 0
    while True:
        res = get(f"matches?page[offset]={off}&page[limit]=100&filter[matches.tournament_id][eq]={tid}&with=teams")
        for m in res["results"]:
            t1, t2 = m.get("team1") or {}, m.get("team2") or {}
            out.append([m["id"], m["start_date"], m["stage_id"], m["round_id"], m["team1_id"], m["team2_id"],
                        t1.get("name"), t2.get("name"), m["winner_team_id"], m["team1_score"], m["team2_score"],
                        m["bo_type"], m["status"]])
        if len(res["results"]) < 100:
            return out
        off += 100


def pull(ids=None):
    """S-tier tournaments since FIRST (finished, or the ids given) with every match: id, start, stage, round, team
    ids and names, winner, score, Bo, status."""
    cat = load()
    if ids is None:
        ts = []
        for off in range(0, 400, 100):
            res = get(f"tournaments?page[offset]={off}&page[limit]=100&sort=-start_date&filter[tournaments.tier][in]=s"
                      "&filter[tournaments.discipline_id][eq]=1&filter[tournaments.status][in]=finished")
            ts += res["results"]
            if len(res["results"]) < 100 or res["results"][-1]["start_date"] < FIRST:
                break
        ids = [t["id"] for t in ts if t["start_date"] >= FIRST and str(t["id"]) not in cat["events"]]
        names = {t["id"]: t["name"] for t in ts}
    else:
        names = {i: get(f"tournaments/{i}")["name"] for i in ids}
    for i in ids:
        cat["events"][str(i)] = {"name": names[i], "matches": tournament_matches(i)}
        print(i, names[i], len(cat["events"][str(i)]["matches"]))
        time.sleep(0.5)
    with gzip.open(CAT, "wt") as f:
        json.dump(cat, f, separators=(",", ":"))
    return cat


def load():
    try:
        with gzip.open(CAT, "rt") as f:
            return json.load(f)
    except (FileNotFoundError, OSError, ValueError):
        return {"events": {}}


# ---------------------------------------------------------------------------------------------------- past events
def stages(cat=None):
    """-> [{kind "swiss"/"se", event, stage, date, teams (bo3 ids), names, ...}] for every finished 16-team Swiss stage
    and single-elimination bracket in the catalog."""
    cat = cat or load()
    out = []
    for tid, ev in cat["events"].items():
        st = defaultdict(list)
        for m in ev["matches"]:
            if m[12] == "finished" and m[8] and m[4] and m[5]:
                st[m[2]].append(m)
        for sid, ms in st.items():
            ms.sort(key=lambda m: m[1])
            teams, W, L = set(), defaultdict(int), defaultdict(int)
            names = {}
            for m in ms:
                teams |= {m[4], m[5]}
                names[m[4]], names[m[5]] = m[6], m[7]
                W[m[8]] += 1
                L[m[5] if m[8] == m[4] else m[4]] += 1
            base = {"event": ev["name"], "tid": tid, "stage": sid, "date": ms[0][1][:10], "names": names,
                    "major": "major" in ev["name"].lower()}
            if len(teams) == 16 and len(ms) == 33 and all(W[t] == 3 or L[t] == 3 for t in teams):
                rounds = defaultdict(list)
                for m in ms:
                    rounds[m[3]].append(m)
                rr = sorted(rounds.values(), key=lambda v: min(m[1] for m in v))
                if len(rr) != 5 or len(rr[0]) != 8:
                    continue
                out.append(dict(base, kind="swiss", teams=sorted(teams), r1=[(m[4], m[5]) for m in rr[0]],
                                allbo3=all(m[11] == 3 for m in ms), adv=sorted(t for t in teams if W[t] == 3)))
            elif len(teams) >= 6 and len(ms) == len(teams) - 1 and all(L[t] <= 1 for t in teams):
                tree, last = [], {}
                for m in ms:
                    slots = [("w", last[t]) if t in last else ("t", t) for t in (m[4], m[5])]
                    tree.append((slots[0], slots[1], m[11] or 3))
                    last[m[8]] = len(tree) - 1
                champ = ms[-1][8]
                if any(sum(1 for s in tree for x in s[:2] if x == ("w", i)) != 1 for i in range(len(tree) - 1)):
                    continue
                out.append(dict(base, kind="se", teams=sorted(teams), tree=tree, champ=champ))
    return sorted(out, key=lambda s: s["date"])


class Model:
    """Series chance for bo3 team ids from the state before a date: player Elo of the last five + region offset,
    VRS points, the team map rating through the veto, the five's player rating (the live series model's four terms)."""

    def __init__(self, M, st, snap, vrs, tm, live, bo3, w, d, cols=(0, 1, 2, 3)):
        self.M, self.s, self.vrs, self.tm, self.live, self.bo3, self.w, self.d = M, snap, vrs, tm, live, bo3, w, d
        self.p, self.cols, self.cache, self.names = st, cols, {}, {}

    def parts(self, t):
        k = self.bo3.k(t) or key(self.names.get(t, str(t)))
        ros = self.s["lastros"].get(k)
        if ros:
            x = sum(self.s["pl"].get(q, self.p["mu_new"]) for q in ros) / len(ros)
        else:
            x = self.s["team"].get(k, self.p["mu_new"])
        rg = self.vrs.region(k, self.d)
        x += self.s["roff"].get(rg, 0) if rg else 0
        v = self.vrs.get(k, self.d)
        return k, ros, x / 400, (v[1] if v else 400) / 400, v

    def logit(self, a, b, bo):
        ck = (a, b, bo)
        if ck in self.cache:
            return self.cache[ck]
        ka, ra, xa, va, Va = self.parts(a)
        kb, rb, xb, vb, Vb = self.parts(b)
        top = bool(Va and Vb and Va[0] <= 50 and Vb[0] <= 50)
        w = self.w["top" if top else "rest"]
        f = [xa - xb, va - vb, self.tm.chance(a, b, bo, self.d) if 2 in self.cols else 0.0,
             self.live.z(ra, ka, rb, kb, self.d) if 3 in self.cols and self.live and self.live.w else 0.0]
        z = sum(w[i] * f[c] for i, c in enumerate(self.cols))
        self.cache[ck] = z
        self.cache[(b, a, bo)] = -z
        return z


def ll(q, y):
    q = min(max(q, 1e-4), 1 - 1e-4)
    return -(y * math.log(q) + (1 - y) * math.log(1 - q))


def sim_stage(s, logit, n, rng, sd=0.0):
    """-> {team: P(advance)} (Swiss) or {team: P(title)} (bracket)."""
    cnt = defaultdict(int)
    if s["kind"] == "swiss":
        seeds = s["seeds"]
        known = [[(a, b, None) for a, b in s["r1"]]]
        for _ in range(n):
            W, _, _ = swiss(seeds, noisy(logit, seeds, sd, rng), rng, known, s["allbo3"])
            for t in seeds:
                cnt[t] += W[t] == 3
    else:
        for _ in range(n):
            cnt[bracket(s["tree"], noisy(logit, s["teams"], sd, rng), rng)[0]] += 1
    return {t: cnt[t] / n for t in s["teams"]}


SDS = (0.0, 0.15, 0.3, 0.45, 0.6)
SPLIT = "2025-07-01"  # rating-uncertainty sd picked on stages before this, scored on stages from it


def stage_loss(s, P):
    if s["kind"] == "swiss":
        ys = {t: int(t in s["adv"]) for t in s["teams"]}
        return sum(ll(P[t], ys[t]) for t in ys), sum((P[t] - ys[t]) ** 2 for t in ys)
    return -math.log(max(P[s["champ"]], 1e-4)), sum((P[t] - (t == s["champ"])) ** 2 for t in P)


def tstat(dl):
    dl = np.asarray(dl)
    return round(float(dl.mean() / (dl.std(ddof=1) + 1e-12) * math.sqrt(len(dl))), 2) if len(dl) > 1 else None


def fit(nsim=3000):
    """Backtest (module doc). Pass: the series model's held-out stage log loss below VRS-only's, both on Swiss
    advancement and bracket titles."""
    import cs2_model as M
    import cs2_players
    H = json.load(gzip.open(M.HIST))
    vrs = M.Vrs(H["vrs"])
    p = json.loads(M.FIT.read_text())["params"]
    bo3 = cs2_bo3.Bo3()
    ss = [s for s in stages() if s["date"] >= "2024-10-01"]  # a few months of rows to fit the first weights on
    dates = sorted({s["date"] for s in ss})
    t0 = time.time()
    rows, st = M.replay(H["series"], vrs, p, bo3=bo3, snaps=dates)
    tm = cs2_bo3.TeamMaps(bo3)
    tm.play(snaps=dates)
    live = cs2_players.Live(bo3)
    rows = [r for r in rows if r["d"] >= "2024-08-07"]
    for r in rows:  # the player term for every scored series (as cs2_model.build() scores results)
        r["z"] = live.z(r["r"][4], r["a"], r["r"][5], r["b"], r["d"]) if live.w else 0.0
    print(f"replay + player term {time.time() - t0:.0f}s, {len(ss)} stages")

    def weights(d, cols):
        tr = [r for r in rows if r["d"] < d]
        out = {}
        for tier in (True, False):
            rr = [r for r in tr if r["top"] == tier]
            X = np.array([[(r["x"], r["v"], r["t"], r["z"])[c] for c in cols] for r in rr])
            out["top" if tier else "rest"] = list(M.fitlog(X, np.array([r["s"] for r in rr])))
        return out
    variants = {"ARK": (0, 1, 2, 3), "VRS": (1,)}
    rng = random.Random(7)
    res = []
    for s in ss:
        d = s["date"]
        s["seeds"] = sorted(s["teams"], key=lambda t: (v[0] if (v := vrs.get(bo3.k(t) or key(s["names"][t]), d)) else 999))
        row = {"event": s["event"], "kind": s["kind"], "date": d, "major": s["major"], "n": len(s["teams"]), "m": {}}
        for nm, cols in variants.items():
            mdl = Model(M, p, st["snaps"][d], vrs, tm.snaps[d], live, bo3, weights(d, cols), d, cols)
            mdl.names = s["names"]
            for sd in SDS:
                P = sim_stage(s, mdl.logit, nsim, rng, sd)
                l, b = stage_loss(s, P)
                row["m"][f"{nm} {sd}"] = {"ll": round(l, 4), "brier": round(b, 4),
                                           "P": {s["names"][t]: round(P[t], 3) for t in s["teams"]}}
        u = {"swiss": 16 * ll(0.5, 1), "se": math.log(len(s["teams"]))}[s["kind"]]
        row["m"]["equal"] = {"ll": round(u, 4), "brier": {"swiss": 4.0, "se": 1 - 1 / len(s["teams"])}[s["kind"]]}
        if s["kind"] == "se":
            row["champ"] = s["names"][s["champ"]]
        else:
            row["adv"] = [s["names"][t] for t in s["adv"]]
        res.append(row)
        print(f"{d} {s['kind']:5s} {s['event'][:40]:40s} ARK0 {row['m']['ARK 0.0']['ll']:.3f} ARK.3 "
              f"{row['m']['ARK 0.3']['ll']:.3f} VRS0 {row['m']['VRS 0.0']['ll']:.3f} ({time.time() - t0:.0f}s)")
    tune = [r for r in res if r["date"] < SPLIT]
    held = [r for r in res if r["date"] >= SPLIT]

    def total(rr, k):  # per kind mean, summed so Swiss (16 outcomes) and brackets (1) both count
        return sum(np.mean([r["m"][k]["ll"] for r in rr if r["kind"] == kind]) for kind in ("swiss", "se"))
    pick = {nm: min(SDS, key=lambda sd: total(tune, f"{nm} {sd}")) for nm in variants}
    A, V = f"ARK {pick['ARK']}", f"VRS {pick['VRS']}"
    score = {}
    for win_nm, rr in (("held", held), ("tune", tune), ("all", res)):
        for kind in ("swiss", "se"):
            for sub in ("all", "majors"):
                q = [r for r in rr if r["kind"] == kind and (sub == "all" or r["major"])]
                if not q:
                    continue
                dl = [r["m"][A]["ll"] - r["m"][V]["ll"] for r in q]
                d0 = [r["m"][A]["ll"] - r["m"]["ARK 0.0"]["ll"] for r in q]
                score[f"{win_nm}/{kind}/{sub}"] = {
                    "n": len(q), "outcomes": sum(r["n"] if kind == "swiss" else 1 for r in q),
                    "ll": {k: round(float(np.mean([r["m"][k]["ll"] for r in q])), 4) for k in (A, V, "ARK 0.0", "equal")},
                    "brier": {k: round(float(np.mean([r["m"][k]["brier"] for r in q])), 4) for k in (A, V, "ARK 0.0", "equal")},
                    "vsVrs": round(float(np.mean(dl)), 4), "t": tstat(dl), "won": [int(sum(x < 0 for x in dl)), len(dl)],
                    "vsNoSd": round(float(np.mean(d0)), 4), "tNoSd": tstat(d0)}
    grid = {k: {"tune": round(total(tune, k), 4), "held": round(total(held, k), 4)}
            for k in res[0]["m"] if k != "equal"}
    qs = np.array([pp for r in held if r["kind"] == "swiss" for pp in r["m"][A]["P"].values()])
    ys = np.array([int(t in r["adv"]) for r in held if r["kind"] == "swiss" for t in r["m"][A]["P"]])
    cal = []
    for lo in np.arange(0, 1, 0.2):
        m = (qs >= lo) & (qs < lo + 0.2 + (lo >= 0.79))
        if m.sum():
            cal.append({"bin": round(float(lo), 1), "n": int(m.sum()), "exp": round(float(qs[m].mean()), 3),
                        "obs": round(float(ys[m].mean()), 3)})
    hs, he = score.get("held/swiss/all", {}), score.get("held/se/all", {})
    ok = bool(hs and he and hs["vsVrs"] < 0 and he["vsVrs"] < 0)
    out = {"asof": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "nsim": nsim, "split": SPLIT, "sd": pick["ARK"],
           "sdVrs": pick["VRS"], "pass": ok, "score": score, "grid": grid, "calibration": cal, "stages": res}
    try:
        out["poly"] = poly_compare(out)
    except Exception as e:  # noqa: BLE001
        print("polymarket compare skipped:", e)
    FIT.write_text(json.dumps(out, indent=1))
    for k, v in score.items():
        print(k, v)
    print("grid", grid)
    print("sd", pick, "pass", ok, cal)
    return out


POLY = {"Perfect World Shanghai Major 2024": "15148", "StarLadder Budapest Major 2025": "59199",
        "Intel Extreme Masters Cologne Major 2026": "350795"}


def poly_compare(fj):
    """Data only (never a venue): Polymarket's Major winner prices at the playoff start (last hourly price before
    00:00 UTC that day, normalised over the eight teams left) against the backtest's title chances."""
    import cs2_poly
    out = []
    for r in fj["stages"]:
        if r["kind"] != "se" or r["event"] not in POLY:
            continue
        ev = cs2_poly.get(f"{cs2_poly.GAMMA}/{POLY[r['event']]}")
        if not ev:
            continue
        t0 = int(dt.datetime.fromisoformat(r["date"] + "T00:00:00+00:00").timestamp())
        ours = r["m"][f"ARK {fj['sd']}"]["P"]
        px = {}
        for m in ev.get("markets", []):
            nm = m.get("groupItemTitle") or ""
            k = next((t for t in ours if key(t) == key(nm) or key(t) in key(nm) or key(nm) in key(t)), None)
            if not k:
                continue
            tok = json.loads(m["clobTokenIds"])[0]
            h = cs2_poly.get(f"{cs2_poly.CLOB}?market={tok}&startTs={t0 - 3 * 86400}&endTs={t0}&fidelity=60") or {}
            hs = [x for x in h.get("history", []) if x["t"] <= t0]
            if hs:
                px[k] = hs[-1]["p"]
        if len(px) < len(ours):
            continue
        tot = sum(px.values())
        pm = {k: v / tot for k, v in px.items()}
        out.append({"event": r["event"], "champ": r["champ"], "ark": ours[r["champ"]], "poly": round(pm[r["champ"]], 3),
                    "llArk": round(-math.log(max(ours[r["champ"]], 1e-4)), 3),
                    "llPoly": round(-math.log(max(pm[r["champ"]], 1e-4)), 3),
                    "teams": {k: [ours[k], round(pm[k], 3)] for k in ours}})
    return out


# ---------------------------------------------------------------------------------------------------- the Major
MAJOR = {"name": "PGL Major Singapore 2026", "short": "Singapore Major", "invite": ("2026", "2026_11_02"),
         # bo3.gg tournaments: Stage 1, Stage 2, Stage 3 + playoffs
         "bo3": (6269, 6268, 4226), "dates": ("2026-11-24", "2026-11-28", "2026-12-02", "2026-12-10"), "end": "2026-12-13",
         # invites per stage and region, in regional standing order (Liquipedia PGL/2026/Singapore)
         "slots": {3: {"europe": (0, 6), "americas": (0, 2)}, 2: {"europe": (6, 12), "americas": (2, 3), "asia": (0, 1)},
                   1: {"europe": (12, 18), "americas": (3, 9), "asia": (1, 5)}}}
POS = ("s2", "s3", "po", "sf", "f", "win")


def invitation(yr, date):
    """Valve's invitation standings: {region: [(name, roster)]} in regional order, and {key: global standing}."""
    out, glob = {}, {}
    for rg in ("europe", "americas", "asia", "global"):
        f = VRS / "invitation" / yr / f"standings_{rg}_{date}.md"
        rows = []
        for line in f.read_text().splitlines():
            c = [x.strip() for x in line.strip().strip("|").split("|")]
            if len(c) >= 4 and c[0].isdigit():
                rows.append((int(c[0]), c[2], [q.strip() for q in c[3].split(",")]))
        if rg == "global":
            glob = {key(n): r for r, n, _ in rows}
        else:
            out[rg] = [(n, ros) for _, n, ros in rows]
    return out, glob


def chain(fields, logit, n, rng, sd, known=None, po_known=None):
    """Simulate the three Swiss stages and the playoff n times. fields: {1: Stage 1 teams in seed order, 2: Stage 2
    invites, 3: Stage 3 invites}. known: {stage: rounds for swiss()}, po_known: {frozenset(a, b): winner}.
    -> {team: [P(Stage 2), P(Stage 3), P(playoffs), P(semis), P(final), P(title)]}."""
    known, po_known = known or {}, po_known or {}
    teams = fields[1] + fields[2] + fields[3]
    cnt = {t: [0] * 6 for t in teams}
    for _ in range(n):
        w0 = noisy(logit, teams, sd, rng)

        def win(a, b, bo):
            k = po_known.get(frozenset((a, b)))
            return w0(a, b, bo) if k is None else float(k == a)
        _, _, o1 = swiss(fields[1], win, rng, known.get(1, ()))
        for t in o1[:8]:
            cnt[t][0] += 1
        _, _, o2 = swiss(fields[2] + o1[:8], win, rng, known.get(2, ()))
        for t in o2[:8]:
            cnt[t][1] += 1
        _, _, o3 = swiss(fields[3] + o2[:8], win, rng, known.get(3, ()), allbo3=True)
        for t in o3[:8]:
            cnt[t][2] += 1
        champ, won = bracket(major_tree(o3[:8]), win, rng)
        for t in won[:4]:
            cnt[t][3] += 1
        for t in won[4:6]:
            cnt[t][4] += 1
        cnt[champ][5] += 1
    return {t: [c / n for c in v] for t, v in cnt.items()}


def known_rounds(ms, tk):
    """bo3.gg matches of one Swiss stage -> rounds for swiss() (round order by first start), team keys via tk."""
    rounds = defaultdict(list)
    for m in ms:
        rounds[m[3]].append(m)
    out = []
    for rr in sorted(rounds.values(), key=lambda v: min(x[1] for x in v)):
        out.append([(tk(m[4], m[6]), tk(m[5], m[7]),
                     (tk(m[4], m[6]) if m[8] == m[4] else tk(m[5], m[7])) if m[12] == "finished" and m[8] else None)
                    for m in rr])
    return out


def memo(logit):
    cache = {}

    def f(a, b, bo):
        k = (a, b, bo)
        if k not in cache:
            cache[k] = logit(a, b, bo)
            cache[(b, a, bo)] = -cache[k]
        return cache[k]
    return f


def live(logit, names, rank, bo3, n=20000, sd=None):
    """The Major's odds from the live series model (cs2_model.build passes logit(a, b, bo) on team keys)."""
    fj = json.loads(FIT.read_text()) if FIT.exists() else {}
    sd = fj.get("sd", 0.45) if sd is None else sd
    logit = memo(logit)
    ev = MAJOR
    try:
        inv, glob = invitation(*ev["invite"])
    except OSError as e:
        print("cs2 events: no invitation standings", e)
        return None
    fields, home = {}, {}
    for st, slots in ev["slots"].items():
        ts = []
        for rg, (a, b) in slots.items():
            for nm, _ in inv[rg][a:b]:
                ts.append(key(nm))
                names.setdefault(key(nm), nm)
                home[key(nm)] = rg
        fields[st] = sorted(ts, key=lambda k: glob.get(k, 999))
    # bo3.gg pairings and results once listed (they replace the invites: late replacements, drawn rounds)
    tk = lambda t, nm: bo3.k(t) or key(nm)  # noqa: E731
    known, po_known, rec = {}, {}, {}
    try:
        ms = {i: tournament_matches(i) for i in ev["bo3"]}
    except Exception as e:  # noqa: BLE001
        print("cs2 events: bo3.gg pull failed", e)
        ms = {}
    # bo3.gg files stages under any of the event's tournaments: Swiss stages (8 matches in their first round) in date
    # order are Stages 1-3, a stage opening with 4 matches is the playoff
    st = defaultdict(list)
    for i in ev["bo3"]:
        for m in ms.get(i, []):
            if m[4] and m[5]:
                st[m[2]].append(m)
    sw, po = [], []
    for v in sorted(st.values(), key=lambda v: min(x[1] for x in v)):
        first = [x for x in v if x[3] == min(v, key=lambda y: y[1])[3]]
        (sw if len(first) >= 8 else po).append(v)
    by_stage = sw[:3] + [[] for _ in range(3 - len(sw[:3]))] + po[:1]
    for si, sm in enumerate(by_stage[:4]):
        if not sm:
            continue
        if si < 3:
            kr = known_rounds(sm, tk)
            known[si + 1] = kr
            r1 = {t for a, b, _ in kr[0] for t in (a, b)} if kr else set()
            if si == 0 and len(r1) == 16 and set(fields[1]) != r1:  # the field as bo3.gg lists it
                fields[1] = sorted(r1, key=lambda k: glob.get(k, 999))
            for rr in kr:
                for a, b, w in rr:
                    if w:
                        lo = b if w == a else a
                        rec.setdefault(si + 1, {}).setdefault(w, [0, 0])[0] += 1
                        rec[si + 1].setdefault(lo, [0, 0])[1] += 1
        else:
            for m in sm:
                if m[12] == "finished" and m[8]:
                    po_known[frozenset((tk(m[4], m[6]), tk(m[5], m[7])))] = tk(m[4], m[6]) if m[8] == m[4] else tk(m[5], m[7])
    for k, nm in ((k, nm) for st in by_stage for m in st for k, nm in ((tk(m[4], m[6]), m[6]), (tk(m[5], m[7]), m[7]))):
        names.setdefault(k, nm)
    P = chain(fields, logit, n, random.Random(11), sd, known, po_known)
    nxt = next_stage(fields, known, po_known, names, by_stage, logit)
    start = {t: st for st, ts in fields.items() for t in ts}
    teams = []
    for t, pr in P.items():
        r = {"k": t, "n": names.get(t, t), "st": start[t], "seed": glob.get(t), "rk": rank.get(t), "rg": home.get(t),
             "p": [round(x, 4) for x in pr], "fair": fair(pr[5])}
        cur = next((rec[s][t] for s in (3, 2, 1) if t in rec.get(s, {})), None)
        if cur:
            r["rec"] = cur
        teams.append(r)
    teams.sort(key=lambda r: (-r["p"][5], -r["p"][2], r["seed"] or 999))
    print(f"{ev['name']}: {len(teams)} teams, favourite {teams[0]['n']} {teams[0]['p'][5]:.3f}")
    return {"name": ev["name"], "short": ev["short"], "dates": ev["dates"], "end": ev["end"], "nsim": n, "sd": sd, "teams": teams,
            "live": any(by_stage), "inviteDate": ev["invite"][1].replace("_", "-"), "next": nxt}


def done(kr):
    return len(kr) == 5 and all(w for rr in kr for _, _, w in rr)


def next_stage(fields, known, po_known, names, by_stage, logit):
    """The stage being played or next to be played: {event, stage, start, seeds, names, r1, known, allbo3,
    projected}. Earlier stages must be complete (their final seeds carry into this one)."""
    rng = random.Random(0)
    carry = []
    for st in (1, 2, 3):
        seeds = fields[st] + carry if st > 1 else fields[1]
        kr = known.get(st, [])
        if not done(kr):
            sm = by_stage[st - 1] if len(by_stage) >= st else []
            return {"event": MAJOR["name"], "stage": f"Stage {st}",
                    "start": min(m[1] for m in sm) if sm else MAJOR["dates"][st - 1] + "T00:00:00Z",
                    "seeds": seeds, "names": {t: names.get(t, t) for t in seeds},
                    "r1": [(a, b) for a, b, _ in kr[0]] if kr else [(seeds[i], seeds[i + 8]) for i in range(8)],
                    "known": kr, "allbo3": st == 3, "projected": not kr}
        _, _, order = swiss(seeds, lambda a, b, bo: 0.5, rng, kr, st == 3)
        carry = order[:8]
    sm = by_stage[3] if len(by_stage) >= 4 else []
    return {"event": MAJOR["name"], "stage": "Playoffs",
            "start": min(m[1] for m in sm) if sm else MAJOR["dates"][3] + "T00:00:00Z", "seeds": carry,
            "names": {t: names.get(t, t) for t in carry}, "r1": [(carry[i], carry[7 - i]) for i in (0, 3, 1, 2)],
            "known": [[(a, b, po_known.get(frozenset((a, b)))) for a, b in
                       [(carry[i], carry[7 - i]) for i in (0, 3, 1, 2)]]], "allbo3": True, "projected": False}


def stage_sims(nxt, logit, n, sd=0.45, seed=5):
    """Raw joint simulations of one Swiss stage (the "next" block): -> (seeds, W, L) with W, L int arrays [n, 16]
    (one row per simulated stage, columns in seed order). Rating uncertainty drawn once per simulation."""
    seeds = nxt["seeds"]
    rng = random.Random(seed)
    W = np.zeros((n, len(seeds)), dtype=np.int8)
    L = np.zeros((n, len(seeds)), dtype=np.int8)
    known = [[tuple(x) for x in rr] for rr in nxt.get("known") or []] or [[(a, b, None) for a, b in nxt["r1"]]]
    for i in range(n):
        w, lo, _ = swiss(seeds, noisy(logit, seeds, sd, rng), rng, known, nxt.get("allbo3", False))
        W[i] = [w[t] for t in seeds]
        L[i] = [lo[t] for t in seeds]
    return seeds, W, L


def fair(q):
    q = min(max(q, 0.0005), 0.9995)
    return round(-100 * q / (1 - q)) if q >= 0.5 else round(100 * (1 - q) / q)


if __name__ == "__main__":
    if "--pull" in sys.argv:
        pull()
    elif "--fit" in sys.argv:
        fit()
    elif "--poly" in sys.argv:
        f = json.loads(FIT.read_text())
        f["poly"] = poly_compare(f)
        FIT.write_text(json.dumps(f, indent=1))
        print(json.dumps(f["poly"], indent=1))
