"""Shared helpers for the NBA / CBB research studies.

Source: sportsdataverse-data GitHub releases (espn_nba_pbp, espn_mens_college_basketball_pbp),
ESPN play-by-play as parquet, one file per season. Raw files live in the scratchpad, never the repo.

normalize(league) turns every season into one compact event table (cached as parquet):
  game_id, season, stype, period, sec (seconds left in period), team (acting team id),
  home, away, hs, as_ (score after the play), kind, made, three, sub (foul subtype), ord
"""
import math
import os
import re
import sys

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

SCRATCH = "/tmp/claude-0/-home-user-website/74038a8a-b0f9-507c-bb0a-47f7b7c402f2/scratchpad/basketball"
RAW = os.path.join(SCRATCH, "raw")
OUT = os.path.dirname(os.path.abspath(__file__))
SEASONS = list(range(2012, 2027))
REG_PERIODS = {"nba": 4, "cbb": 2}

COLS = ["game_id", "game_play_number", "sequence_number", "type_text", "text", "period_number",
        "clock_display_value", "team_id", "home_team_id", "away_team_id", "home_score", "away_score",
        "scoring_play", "shooting_play", "score_value", "athlete_id_1", "season", "season_type"]


def _clock(s):
    s = s.fillna("0:0").astype(str)
    p = s.str.split(":", n=1, expand=True)
    m = pd.to_numeric(p[0], errors="coerce").fillna(0)
    sec = pd.to_numeric(p[1], errors="coerce").fillna(0) if p.shape[1] > 1 else 0
    return m * 60 + sec


def _norm_season(league, season):
    path = os.path.join(RAW, f"{league}_{season}.parquet")
    have = set(pq.read_schema(path).names)
    df = pq.read_table(path, columns=[c for c in COLS if c in have]).to_pandas()
    df["text"] = df["text"].fillna("").astype(str)
    df["type_text"] = df["type_text"].fillna("").astype(str)
    tl = df["text"].str.lower()
    ty = df["type_text"]
    kind = pd.Series("other", index=df.index, dtype=object)
    sub = pd.Series("", index=df.index, dtype=object)
    if league == "nba":
        is_ft = ty.str.startswith("Free Throw")
        is_foul = ty.str.contains("Foul") & ~ty.str.contains("Turnover") & ~ty.str.startswith("No Foul")
        is_tov = ty.str.contains("Turnover") & (ty != "No Turnover")
        is_to = ty.str.contains("Timeout") & ~ty.str.contains("Excess")
        sub[is_foul] = ty[is_foul]
        sub[is_ft & ty.str.contains("Technical|Flagrant|Clear Path")] = "special"
        is_shot = df["shooting_play"].fillna(False).astype(bool) & ~is_ft
    else:
        is_ft = tl.str.contains("free throw")
        is_foul = tl.str.startswith("foul on") | (ty == "PersonalFoul") | (ty == "Technical Foul")
        is_tov = tl.str.contains("turnover") & ~is_foul
        is_to = ty.str.contains("TimeOut") & ~ty.str.contains("Official")
        sub[is_foul] = np.where(ty[is_foul] == "Technical Foul", "Technical Foul", "Personal Foul")
        is_shot = df["shooting_play"].fillna(False).astype(bool) & ~is_ft & ~is_foul
    kind[is_shot] = "shot"
    kind[is_ft] = "ft"
    kind[is_foul] = "foul"
    kind[is_tov] = "tov"
    kind[is_to] = "timeout"
    kind[ty.str.contains("Steal")] = "steal"
    kind[ty.str.contains("Offensive Rebound")] = "oreb"
    kind[ty.str.contains("Defensive Rebound")] = "dreb"
    kind[ty.str.contains("Dead Ball Rebound")] = "dbreb"
    kind[ty == "End Period"] = "endp"
    kind[ty == "End Game"] = "endg"
    kind[ty.str.contains("Substitution")] = "subst"
    out = pd.DataFrame({
        "game_id": df["game_id"].astype("int64"),
        "season": season,
        "stype": df["season_type"].astype("int8"),
        "period": df["period_number"].astype("int16"),
        "sec": _clock(df["clock_display_value"]).astype("float32"),
        "team": df["team_id"].fillna(-1).astype("int64"),
        "home": df["home_team_id"].astype("int64"),
        "away": df["away_team_id"].astype("int64"),
        "hs": df["home_score"].astype("int32"),
        "as_": df["away_score"].astype("int32"),
        "kind": kind.astype("category"),
        "made": df["scoring_play"].fillna(False).astype(bool),
        "three": tl.str.contains("three point") | (is_shot & (df["score_value"] == 3)),
        "sub": sub.astype("category"),
        "player": df["athlete_id_1"].fillna(-1).astype("int64"),
        "ord": (df["game_play_number"] if "game_play_number" in df else df["sequence_number"]).astype("int64"),
    })
    if league == "nba":  # NBA misses have score_value 0; three flag from text only
        out["three"] = tl.str.contains("three point") | tl.str.contains("3pt")
    out = out[out.kind != "subst"]
    out = out.sort_values(["game_id", "ord"], kind="stable").reset_index(drop=True)
    return out


def load(league):
    cache = os.path.join(SCRATCH, f"{league}_events.parquet")
    if os.path.exists(cache):
        return pd.read_parquet(cache)
    parts = []
    for s in SEASONS:
        p = _norm_season(league, s)
        parts.append(p)
        print(league, s, len(p), p.game_id.nunique(), file=sys.stderr)
    ev = pd.concat(parts, ignore_index=True)
    ev["kind"] = ev["kind"].astype("category")
    ev["sub"] = ev["sub"].astype("category")
    ev.to_parquet(cache)
    return ev


def game_table(ev, league):
    """One row per game: final score, max period, sanity flags."""
    g = ev.groupby("game_id").agg(season=("season", "first"), stype=("stype", "first"),
                                  home=("home", "first"), away=("away", "first"),
                                  fh=("hs", "max"), fa=("as_", "max"), maxp=("period", "max"),
                                  nplays=("kind", "size"))
    g["ot"] = g["maxp"] > REG_PERIODS[league]
    g = g[(g.fh != g.fa) & (g.nplays > 150)]
    return g


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (p, max(0.0, c - h), min(1.0, c + h))


def boot_mean(values, clusters=None, B=2000, seed=7):
    """Mean and 95% bootstrap CI, resampling clusters (games) when given."""
    v = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    if clusters is None:
        idx = rng.integers(0, len(v), (B, len(v)))
        bs = v[idx].mean(axis=1)
    else:
        cl = pd.Series(v).groupby(np.asarray(clusters)).agg(["sum", "count"])
        s, c = cl["sum"].to_numpy(), cl["count"].to_numpy()
        idx = rng.integers(0, len(s), (B, len(s)))
        bs = s[idx].sum(axis=1) / c[idx].sum(axis=1)
    return float(v.mean()), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def boot_diff(a, b, ca=None, cb=None, B=2000, seed=11):
    """Difference of means a-b with a bootstrap CI (clustered by game if cluster ids given)."""
    rng = np.random.default_rng(seed)
    out = []
    def prep(v, c):
        v = np.asarray(v, float)
        if c is None:
            return v, np.ones_like(v), None
        cl = pd.Series(v).groupby(np.asarray(c)).agg(["sum", "count"])
        return cl["sum"].to_numpy(), cl["count"].to_numpy(), True
    sa, na, _ = prep(a, ca)
    sb, nb, _ = prep(b, cb)
    for _ in range(B):
        ia = rng.integers(0, len(sa), len(sa))
        ib = rng.integers(0, len(sb), len(sb))
        out.append(sa[ia].sum() / na[ia].sum() - sb[ib].sum() / nb[ib].sum())
    d = float(np.mean(a) - np.mean(b))
    return d, float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))


def write_json(obj, name):
    import json
    path = os.path.join(OUT, name + ".json")
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)
    print("wrote", path)


def r3(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), 3)
