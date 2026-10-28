#!/usr/bin/env python3
"""bo3.gg map results for the COUNTER-STRIKE ARKBOARD: every finished pro match since Jun 2020 with its maps (map name,
map number, winner, round score), and the map-level team rating built on them.

    python3 scripts/cs2_bo3.py           # add the last 14 days (matches + maps) to scripts/data/cs2_bo3.json.gz
    python3 scripts/cs2_bo3.py --full    # re-pull everything (~2,300 pages, ~15 min)

Source: bo3.gg's public API (api.bo3.gg/api/v1, no key): /matches (finished, with team ids, names, format, tier) and
/games (one row per map, winner and loser team ids through winner_team_clan / loser_team_clan). Odds fields are not
read or stored.

Used by scripts/cs2_model.py:
  - join(series): one bo3 match per Valve/Liquipedia series (same team keys, same day or one off, same winner), so a
    series' player Elo update can run map by map on round share.
  - TeamMaps: team Elo on bo3 team ids, one update per map on round share, plus each team's offset on each map;
    series chance through a greedy veto (each side bans its worst map and picks its best, both orders averaged).
Writes scripts/data/cs2_bo3.json.gz (committed): {"matches": [[id, start, team1, team2, name1, name2, winner, score1,
score2, bo, tier]], "games": [[id, match, begin, map, number, winner, loser, rounds won, rounds lost]]}.
"""
import datetime as dt
import gzip
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cs2_data import UA, key  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "scripts" / "data" / "cs2_bo3.json.gz"
API = "https://api.bo3.gg/api/v1/"
Q = {"games": "games?page[offset]={}&page[limit]=100&sort={}begin_at&with=winner_team_clan,loser_team_clan",
     "matches": "matches?page[offset]={}&page[limit]=100&sort={}start_date&filter[matches.status][in]=finished"
                "&with=teams"}
# team map Elo (tuned Aug 2024 - Jun 2025 on Valve's series, scripts/cs2_model.py --fit)
TM = {"K": 0.03, "Kn": 2.0, "Km": 0.04, "nm0": 10, "span": 0.3, "new": {"s": 0.3, "a": 0.2}}


def get(path):
    url = API + urllib.parse.quote(path, safe="/?&=,%")
    for t in range(5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            if t == 4:
                raise
            print("bo3", path[:60], e, file=sys.stderr)
            time.sleep(2 ** t)


def slim(kind, r):
    if kind == "games":
        w, lo = r.get("winner_team_clan") or {}, r.get("loser_team_clan") or {}
        return [r["id"], r["match_id"], r["begin_at"], r["map_name"], r["number"], w.get("team_id"), lo.get("team_id"),
                r["winner_clan_score"], r["loser_clan_score"]]
    t1, t2 = r.get("team1") or {}, r.get("team2") or {}
    return [r["id"], r["start_date"], r["team1_id"], r["team2_id"], t1.get("name"), t2.get("name"), r["winner_team_id"],
            r["team1_score"], r["team2_score"], r["bo_type"], r["tier"]]


def pull(kind, full):
    """-> rows: everything (full) or the newest pages back to 14 days ago."""
    if full:
        n = get(Q[kind].format(0, ""))["total"]["count"]
        with ThreadPoolExecutor(4) as ex:
            pages = ex.map(lambda o: get(Q[kind].format(o, ""))["results"], range(0, n + 100, 100))
            return [slim(kind, r) for p in pages for r in p]
    cut = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=14)).isoformat()
    out, off = [], 0
    while off < 5000:
        res = get(Q[kind].format(off, "-"))["results"]
        out += [slim(kind, r) for r in res]
        if not res or min((r.get("begin_at") or r.get("start_date") or "") for r in res) < cut:
            break
        off += 100
    return out


def load():
    try:
        with gzip.open(OUT, "rt") as f:
            return json.load(f)
    except (FileNotFoundError, OSError, ValueError):
        return {"matches": [], "games": []}


def sync(full=False):
    d = load()
    for kind in ("matches", "games"):
        rows = {r[0]: r for r in d[kind]}
        new = pull(kind, full)
        rows.update({r[0]: r for r in new})
        d[kind] = sorted(rows.values(), key=lambda r: (r[1] if kind == "matches" else r[2]) or "")
        print(f"bo3 {kind}: {len(new)} pulled, {len(d[kind])} kept")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT, "wt") as f:
        json.dump(d, f, separators=(",", ":"))


def sig(x):
    return 1 / (1 + math.exp(-x))


def logit(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def shift(d, k):
    return (dt.date.fromisoformat(d) + dt.timedelta(days=k)).isoformat()


def round_share(won, lost, span):
    """Map result as a score in [0, 1]: .5 + half the round share's distance from .5 over span (13-3 counts more)."""
    rs = won / ((won + lost) or 24)
    return min(1.0, max(0.0, (rs - 0.5) / span * 0.5 + 0.5))


class Bo3:
    def __init__(self, d=None):
        d = d or load()
        self.mt = {r[0]: r for r in d["matches"] if r[1] and r[2] is not None and r[3] is not None}
        self.maps = defaultdict(list)
        for g in d["games"]:
            if g[1] in self.mt and g[5] is not None and g[6] is not None and g[7] is not None:
                self.maps[g[1]].append(g)
        for v in self.maps.values():
            v.sort(key=lambda g: g[4] or 0)
        names = defaultdict(lambda: defaultdict(int))
        for r in self.mt.values():
            names[r[2]][key(r[4])] += 1
            names[r[3]][key(r[5])] += 1
        self.tkey = {t: max(v, key=v.get) for t, v in names.items()}
        self.alias = {}
        self.byday = defaultdict(list)
        for r in sorted(self.mt.values(), key=lambda r: r[1]):
            self.byday[r[1][:10]].append(r)

    def k(self, t):
        return self.alias.get(t, self.tkey.get(t))

    def _join(self, series):
        out, used = {}, set()
        for i, r in enumerate(series):
            d, a, b = r[0], key(r[1]), key(r[2])
            win = a if r[3] == 0 else b
            for off in (0, -1, 1):
                m = next((m for m in self.byday.get(shift(d, off), []) if m[0] not in used and m[6] is not None
                          and {self.k(m[2]), self.k(m[3])} == {a, b} and self.k(m[6]) == win), None)
                if m:
                    out[i] = m
                    used.add(m[0])
                    break
        return out

    def join(self, series):
        """-> {series index: bo3 match}. bo3 team names that differ from Valve's are learned from series that join on
        the other side, day and winner (3+ agreeing series)."""
        j = self._join(series)
        for _ in range(2):
            votes = defaultdict(lambda: defaultdict(int))
            used = {m[0] for m in j.values()}
            for i, r in enumerate(series):
                if i in j:
                    continue
                d, a, b = r[0], key(r[1]), key(r[2])
                for off in (0, -1, 1):
                    for m in self.byday.get(shift(d, off), []):
                        if m[0] in used:
                            continue
                        k1, k2 = self.tkey[m[2]], self.tkey[m[3]]
                        for x, tid in ((k1, m[3]), (k2, m[2])):
                            if x == a:
                                votes[tid][b] += 1
                            if x == b:
                                votes[tid][a] += 1
            self.alias = {t: max(v, key=v.get) for t, v in votes.items()
                          if max(v.values()) >= 3 and max(v, key=v.get) != self.tkey[t]}
            j = self._join(series)
        self.joined = j
        return j

    def map_updates(self, i, ka, span):
        """Joined series i -> [(score for side A in [0, 1])] per map, or None."""
        m = self.joined.get(i)
        if not m or not self.maps.get(m[0]):
            return None
        out = []
        for g in self.maps[m[0]]:
            aw = self.k(g[5]) == ka
            won, lost = (g[7], g[8]) if aw else (g[8], g[7])
            out.append(round_share(won, lost, span))
        return out

    def team_of(self, k):
        """Valve team key -> the bo3 team id that played most under it."""
        if not hasattr(self, "_tid"):
            n = defaultdict(lambda: defaultdict(int))
            for r in self.mt.values():
                for t in (r[2], r[3]):
                    n[self.k(t)][t] += 1
            self._tid = {kk: max(v, key=v.get) for kk, v in n.items()}
        return self._tid.get(k)


def veto(da, pool, bo):
    """Greedy veto on map edges da[map] (A minus B, logits): ban your worst, pick your best; both orders.
    -> [maps played] for each order (Bo3: pick, pick, decider)."""
    seq = {1: "BBBBBB", 5: "BBPPPP"}.get(bo, "BBPPBB")
    out = []
    for first in (1, -1):
        rem, played, side = list(pool), [], first
        for act in seq:
            if len(rem) <= 1:
                break
            if act == "B":
                m = min(rem, key=lambda q: side * da.get(q, 0))
            else:
                m = max(rem, key=lambda q: side * da.get(q, 0))
                played.append(m)
            rem.remove(m)
            side = -side
        out.append(played + rem[:1])
    return out


def series_from_maps(ps, bo):
    """Chance of winning the series from per-map chances in play order (Bo1 first map, Bo3 three, Bo5 five)."""
    if bo in (1, 2) or len(ps) < 3:
        p = ps[0] if ps else 0.5
        if bo == 3 and len(ps) < 3:
            return p * p * (3 - 2 * p)
        return p
    need = 3 if bo == 5 else 2
    # P(first to `need` wins) over the ordered maps
    states = {(0, 0): 1.0}
    win = 0.0
    for p in ps:
        nxt = defaultdict(float)
        for (w, lo), pr in states.items():
            for dw, q in ((1, p), (0, 1 - p)):
                s = (w + dw, lo + 1 - dw)
                if s[0] == need:
                    win += pr * q
                elif s[1] < need:
                    nxt[s] += pr * q
        states = nxt
    return win


class TeamMaps:
    """Team Elo on bo3 team ids (logit scale), one update per map on round share, plus team x map offsets."""

    def __init__(self, bo3, p=TM):
        self.b, self.p = bo3, p
        self.R, self.Mo = {}, defaultdict(float)
        self.n, self.nm = defaultdict(int), defaultdict(int)
        self.recent = []

    def pool(self, d):
        cut = shift(d[:10], -90)
        cnt = defaultdict(int)
        for day, mp in self.recent:
            if day >= cut:
                cnt[mp] += 1
        tot = sum(cnt.values()) or 1
        return [mp for mp, c in sorted(cnt.items(), key=lambda x: -x[1]) if c / tot > 0.03][:7]

    def chance(self, a, b, bo, d):
        """Series chance for bo3 team a over b (logit), through the veto."""
        x = self.R.get(a, 0.0) - self.R.get(b, 0.0)
        pool = self.pool(d)
        if not pool:
            return logit(series_from_maps([sig(x)], bo))
        da = {mp: self.Mo[(a, mp)] - self.Mo[(b, mp)] for mp in pool}
        pv = [series_from_maps([sig(x + da.get(q, 0)) for q in played] or [sig(x)], bo)
              for played in veto(da, pool, bo)]
        return logit(sum(pv) / len(pv))

    def play(self, upto=None, ask=None):
        """Play every bo3 match forward (to `upto`, exclusive). ask: {match id: [series index]} -> {index: logit for
        the bo3 team listed first}."""
        out = {}
        p = self.p
        for m in sorted(self.b.mt.values(), key=lambda r: r[1]):
            if upto and m[1] >= upto:
                break
            a, b = m[2], m[3]
            for t in (a, b):
                if t not in self.R:
                    self.R[t] = p["new"].get(m[10], 0.0)
            if ask and m[0] in ask:
                v = self.chance(a, b, m[9] or 3, m[1])
                for i in ask[m[0]]:
                    out[i] = (v, a)
            for g in self.b.maps.get(m[0], []):
                w, lo, mp = g[5], g[6], g[3]
                if {w, lo} != {a, b}:
                    continue
                self.recent.append((m[1][:10], mp))
                e = sig(self.R[w] + self.Mo[(w, mp)] - self.R[lo] - self.Mo[(lo, mp)])
                s = round_share(g[7], g[8], p["span"])
                for t, sg in ((w, 1), (lo, -1)):
                    self.R[t] += sg * p["K"] * (1 + p["Kn"] * math.exp(-self.n[t] / 30)) * (s - e)
                    self.n[t] += 1
                    self.Mo[(t, mp)] += sg * p["Km"] / (1 + self.nm[(t, mp)] / p["nm0"]) * (s - e)
                    self.nm[(t, mp)] += 1
            if len(self.recent) > 20000:
                self.recent = self.recent[-12000:]
        return out


if __name__ == "__main__":
    sync(full="--full" in sys.argv)
