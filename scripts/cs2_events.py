#!/usr/bin/env python3
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
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cs2_bo3  # noqa: E402
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




# ---------------------------------------------------------------------------------------------------- simulator
PRIORITY = [((1, 6), (2, 5), (3, 4)), ((1, 6), (2, 4), (3, 5)), ((1, 5), (2, 6), (3, 4)), ((1, 5), (2, 4), (3, 6)),
            ((1, 4), (2, 6), (3, 5)), ((1, 4), (2, 5), (3, 6)), ((1, 6), (2, 3), (4, 5)), ((1, 5), (2, 3), (4, 6)),
            ((1, 3), (2, 6), (4, 5)), ((1, 3), (2, 5), (4, 6)), ((1, 4), (2, 3), (5, 6)), ((1, 3), (2, 4), (5, 6)),
            ((1, 2), (3, 6), (4, 5)), ((1, 2), (3, 5), (4, 6)), ((1, 2), (3, 4), (5, 6))]


def high_low(pool, met):
    """Highest seed v the lowest available without a rematch (backtracking so the rest can still pair)."""
    if not pool:
        return []
    a = pool[0]
    for j in range(len(pool) - 1, 0, -1):
        b = pool[j]
        if b in met[a]:
            continue
        rest = high_low(pool[1:j] + pool[j + 1:], met)
        if rest is not None:
            return [(a, b)] + rest
    return None


def pair_pool(pool, met, rnd):
    if rnd >= 3 and len(pool) == 6:
        for row in PRIORITY:
            ps = [(pool[i - 1], pool[j - 1]) for i, j in row]
            if all(b not in met[a] for a, b in ps):
                return ps
        return [(pool[i - 1], pool[j - 1]) for i, j in PRIORITY[0]]
    ps = high_low(pool, met)
    return ps if ps is not None else [(pool[i], pool[-1 - i]) for i in range(len(pool) // 2)]


def swiss(seeds, win, rng, known=(), allbo3=False):
    """One 16-team Swiss stage. seeds: teams in seed order. win(a, b, bo) -> chance a beats b. known: per round, a
    list of (a, b, winner or None) already drawn (and played). -> (W, L, final seed order of all 16)."""
    W = {t: 0 for t in seeds}
    L = {t: 0 for t in seeds}
    met = {t: set() for t in seeds}
    sd = {t: i for i, t in enumerate(seeds)}

    def buch(t):
        return sum(W[o] - L[o] for o in met[t])

    for rnd in range(5):
        if rnd < len(known) and known[rnd]:
            ps = [(a, b) for a, b, _ in known[rnd]]
            res = {frozenset((a, b)): w for a, b, w in known[rnd]}
        else:
            res = {}
            if rnd == 0:
                ps = [(seeds[i], seeds[i + 8]) for i in range(8)]
            else:
                pools = defaultdict(list)
                for t in seeds:
                    if W[t] < 3 and L[t] < 3:
                        pools[(W[t], L[t])].append(t)
                ps = []
                for rec in sorted(pools, key=lambda r: (-r[0], r[1])):
                    pool = sorted(pools[rec], key=lambda t: (-buch(t), sd[t]))
                    ps += pair_pool(pool, met, rnd)
        for a, b in ps:
            bo = 3 if allbo3 or W[a] == 2 or L[a] == 2 else 1
            w = res.get(frozenset((a, b)))
            if w is None:
                w = a if rng.random() < win(a, b, bo) else b
            lo = b if w == a else a
            W[w] += 1
            L[lo] += 1
            met[a].add(b)
            met[b].add(a)
    order = sorted(seeds, key=lambda t: (-W[t], L[t], -buch(t), sd[t]))
    return W, L, order


def bracket(tree, win, rng):
    """Single elimination. tree: [(slot a, slot b, bo)], a slot is ("t", team) or ("w", match index). -> champion,
    and each match's winner."""
    won = []
    for sa, sb, bo, *res in tree:
        a = sa[1] if sa[0] == "t" else won[sa[1]]
        b = sb[1] if sb[0] == "t" else won[sb[1]]
        w = res[0] if res and res[0] in (a, b) else (a if rng.random() < win(a, b, bo) else b)
        won.append(w)
    return won[-1], won


def major_tree(order8):
    """Valve's playoff: 1v8, 4v5 | 2v7, 3v6 (Bo3), semis, grand final Bo5."""
    s = order8
    return [(("t", s[0]), ("t", s[7]), 3), (("t", s[3]), ("t", s[4]), 3), (("t", s[1]), ("t", s[6]), 3),
            (("t", s[2]), ("t", s[5]), 3), (("w", 0), ("w", 1), 3), (("w", 2), ("w", 3), 3), (("w", 4), ("w", 5), 5)]


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


def noisy(logit, teams, sd, rng):
    """win(a, b, bo) for one simulated event: each team's strength drawn once around its rating (sd on the logit
    scale), so a rating that is off stays off for the whole event."""
    e = {t: rng.gauss(0, sd) if sd else 0.0 for t in teams}
    return lambda a, b, bo: 1 / (1 + math.exp(-(logit(a, b, bo) + e[a] - e[b])))


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
    FIT.write_text(json.dumps(out, indent=1))
    for k, v in score.items():
        print(k, v)
    print("grid", grid)
    print("sd", pick, "pass", ok, cal)
    return out


if __name__ == "__main__":
    if "--pull" in sys.argv:
        pull()
    elif "--fit" in sys.argv:
        fit()
