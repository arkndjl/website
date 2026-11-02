"""Shared loading for MLB research studies (Retrosheet parsed play-by-play CSV, 2015-2025).

Raw files live outside the repo:  $MLB_RAW/<year>plays.csv  (https://www.retrosheet.org/downloads/plays.html)
Run any script here with  python3 -I <script>  ; this module is loaded by path, not by sys.path.
"""
import os
import numpy as np
import pandas as pd

SCRATCH = "/tmp/claude-0/-home-user-website/74038a8a-b0f9-507c-bb0a-47f7b7c402f2/scratchpad/mlb"
RAW = os.environ.get("MLB_RAW", SCRATCH + "/raw")
CACHE = SCRATCH + "/plays_2015_2025.parquet"
OUT = os.path.dirname(os.path.abspath(__file__))
YEARS = list(range(2015, 2026))

COLS = ["gid", "event", "inning", "top_bot", "batteam", "pitteam", "score_v", "score_h", "batter", "pitcher",
        "lp", "bat_f", "bathand", "pithand", "pitches", "nump", "pa", "ab", "single", "double", "triple", "hr",
        "sh", "sf", "hbp", "walk", "k", "xi", "iw", "bunt", "sb2", "sb3", "sbh", "cs2", "cs3", "csh",
        "outs_pre", "outs_post", "br1_pre", "br2_pre", "br3_pre", "br1_post", "br2_post", "br3_post",
        "run_b", "run1", "run2", "run3", "runs", "date", "gametype"]

# wOBA weights (approx. 2015-2025 average of FanGraphs constants; fixed so seasons are comparable)
W = dict(ubb=0.69, hbp=0.72, single=0.89, double=1.27, triple=1.62, hr=2.10)


def build():
    parts = []
    for y in YEARS:
        d = pd.read_csv(f"{RAW}/{y}plays.csv", usecols=COLS, low_memory=False)
        d = d[d.gametype == "regular"].copy()
        d["season"] = y
        d["row"] = np.arange(len(d))
        parts.append(d)
    d = pd.concat(parts, ignore_index=True)
    for c in ["br1_pre", "br2_pre", "br3_pre", "br1_post", "br2_post", "br3_post", "run_b", "run1", "run2", "run3"]:
        d[c] = d[c].astype("string")
    d.to_parquet(CACHE)
    return d


def load():
    if not os.path.exists(CACHE):
        d = build()
    else:
        d = pd.read_parquet(CACHE)
    d = d.sort_values(["season", "row"]).reset_index(drop=True)
    d["home_bat"] = d.top_bot.astype(int)  # 1 = bottom half (home batting)
    d["bases"] = d.br1_pre.notna().astype(int) + 2 * d.br2_pre.notna() + 4 * d.br3_pre.notna()
    d["bases_post"] = d.br1_post.notna().astype(int) + 2 * d.br2_post.notna() + 4 * d.br3_post.notna()
    d["diff_home"] = d.score_h - d.score_v
    # final score / home win
    after_v = d.score_v + np.where(d.home_bat == 0, d.runs, 0)
    after_h = d.score_h + np.where(d.home_bat == 1, d.runs, 0)
    d["after_diff_home"] = after_h - after_v
    g = d.groupby("gid")
    fin = pd.DataFrame({"fv": after_v.groupby(d.gid).max(), "fh": after_h.groupby(d.gid).max(),
                        "last_inn": g.inning.max()})
    fin = fin[fin.fv != fin.fh]  # drop ties / suspended oddities
    d = d[d.gid.isin(fin.index)].copy()
    d["home_win"] = d.gid.map((fin.fh > fin.fv).astype(int))
    d["last_inn"] = d.gid.map(fin.last_inn)
    # 7-inning doubleheader games (2020-21): drop from inning-based analyses
    d["dh7"] = (d.season.isin([2020, 2021]) & d.gid.str[-1].isin(["1", "2"]))
    # ghost-runner era extra innings
    d["ghost"] = (d.season >= 2020) & (d.inning >= 10)
    # runs to end of half-inning
    d["half"] = d.gid + "_" + d.inning.astype(str) + "_" + d.top_bot.astype(str)
    h = d.groupby("half", sort=False)
    d["runs_half"] = h.runs.transform("sum")
    d["runs_before"] = h.runs.cumsum() - d.runs
    d["runs_rest"] = d.runs_half - d.runs_before
    d["half_complete"] = h.outs_post.transform("last") == 3
    return d


def wilson(k, n, z=1.96):
    if n == 0:
        return (np.nan, np.nan)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    hw = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (c - hw, c + hw)


def cluster_mean_ci(values, clusters, B=1000, seed=0):
    """Mean and 95% CI by cluster bootstrap (resample games)."""
    v = pd.Series(np.asarray(values, float))
    c = pd.Series(np.asarray(clusters))
    s = v.groupby(c.values).agg(["sum", "count"])
    rng = np.random.default_rng(seed)
    S, N = s["sum"].values, s["count"].values
    k = len(S)
    idx = rng.integers(0, k, size=(B, k))
    bs = S[idx].sum(1) / N[idx].sum(1)
    return float(v.mean()), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def woba_num(d):
    ubb = (d.walk == 1) & (d.iw == 0)
    return (W["ubb"] * ubb + W["hbp"] * d.hbp + W["single"] * d.single + W["double"] * d.double
            + W["triple"] * d.triple + W["hr"] * d.hr)


def woba_pa(d):
    """Rows counted in the wOBA denominator: PA excluding IBB, sac bunts, catcher interference."""
    return (d.pa == 1) & (d.iw == 0) & (d.sh == 0) & (d.xi == 0)


# ---------------------------------------------------------------- win expectancy
def we_key_cols(inning, home_bat, outs, bases, diff_home, ghost):
    inn = np.minimum(inning, 10)
    dif = np.clip(diff_home, -7, 7)
    return pd.MultiIndex.from_arrays([inn, home_bat, outs, bases, dif, ghost.astype(int)])


class WE:
    """Empirical home win expectancy by (inning<=10+, half, outs, bases, home score diff +-7, ghost era).
    Cells shrunk toward the same state with bases pooled (k=50 pseudo-games)."""

    def __init__(self, d):
        x = d[~d.dh7]
        inn = np.minimum(x.inning, 10)
        dif = np.clip(x.diff_home, -7, 7)
        key = pd.DataFrame({"inn": inn.values, "hb": x.home_bat.values, "o": x.outs_pre.values,
                            "b": x.bases.values, "df": dif.values, "gh": x.ghost.astype(int).values,
                            "w": x.home_win.values})
        key = key[key.o < 3]
        fine = key.groupby(["inn", "hb", "o", "b", "df", "gh"]).w.agg(["sum", "count"])
        coarse = key.groupby(["inn", "hb", "o", "df", "gh"]).w.agg(["sum", "count"])
        cm = coarse["sum"] / coarse["count"]
        prior = cm.reindex(fine.index.droplevel("b")).values
        self.k = 50
        self.tab = (fine["sum"] + self.k * prior) / (fine["count"] + self.k)
        self.n = fine["count"]
        self.coarse = cm

    def pre(self, inning, home_bat, outs, bases, diff_home, ghost):
        idx = pd.MultiIndex.from_arrays([np.minimum(inning, 10), home_bat, outs, bases,
                                         np.clip(diff_home, -7, 7), np.asarray(ghost).astype(int)])
        return self.tab.reindex(idx).values

    def post(self, inning, home_bat, outs_post, bases_post, diff_home_after, season):
        """Home WE after a play; handles end of half-inning and game end."""
        inning = np.asarray(inning); home_bat = np.asarray(home_bat); outs_post = np.asarray(outs_post)
        bases_post = np.asarray(bases_post); dfa = np.asarray(diff_home_after); season = np.asarray(season)
        out = np.full(len(inning), np.nan)
        live = outs_post < 3
        gh = (season >= 2020) & (inning >= 10)
        out[live] = self.pre(inning[live], home_bat[live], outs_post[live], bases_post[live], dfa[live], gh[live])
        # walk-off during bottom half 9+
        wo = live & (home_bat == 1) & (inning >= 9) & (dfa > 0)
        out[wo] = 1.0
        end = ~live
        # end of top half
        et = end & (home_bat == 0)
        fin_top = et & (inning >= 9) & (dfa > 0)
        out[fin_top] = 1.0
        rest = et & ~fin_top
        if rest.any():
            out[rest] = self.pre(inning[rest], np.ones(rest.sum(), int), np.zeros(rest.sum(), int),
                                 np.where(gh[rest], 2, 0), dfa[rest], gh[rest])
        # end of bottom half
        eb = end & (home_bat == 1)
        over = eb & (inning >= 9) & (dfa != 0)
        out[over] = (dfa[over] > 0).astype(float)
        rest = eb & ~over
        if rest.any():
            ni = inning[rest] + 1
            ngh = (season[rest] >= 2020) & (ni >= 10)
            out[rest] = self.pre(ni, np.zeros(rest.sum(), int), np.zeros(rest.sum(), int),
                                 np.where(ngh, 2, 0), dfa[rest], ngh)
        return out


def add_we(d, we):
    d["we_pre"] = we.pre(d.inning.values, d.home_bat.values, d.outs_pre.values, d.bases.values,
                         d.diff_home.values, d.ghost.values)
    d["we_post"] = we.post(d.inning.values, d.home_bat.values, d.outs_post.values, d.bases_post.values,
                           d.after_diff_home.values, d.season.values)
    sign = np.where(d.home_bat == 1, 1, -1)
    d["dwe_bat"] = sign * (d.we_post - d.we_pre)  # WE change for the batting team
    return d


def re_table(d, seasons):
    """RE24: mean runs to end of half-inning by (outs, bases); innings 1-8, complete halves."""
    x = d[d.season.isin(seasons) & (d.inning <= 8) & d.half_complete & ~d.dh7 & (d.outs_pre < 3)]
    t = x.groupby(["outs_pre", "bases"]).runs_rest.mean()
    return t


def batter_quality(d):
    """Batter-season wOBA, shrunk to league mean with 200 PA of prior; leave-one-out not needed at this n."""
    m = woba_pa(d)
    x = d[m]
    num = woba_num(x)
    g = pd.DataFrame({"s": x.season, "b": x.batter, "num": num}).groupby(["s", "b"]).num.agg(["sum", "count"])
    lg = num.sum() / len(num)
    q = (g["sum"] + 200 * lg) / (g["count"] + 200)
    return q, lg
