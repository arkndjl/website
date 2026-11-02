"""Shared helpers for the NFL studies."""
import json, math, os
import numpy as np
import pandas as pd

SCRATCH = os.environ.get("NFL_SCRATCH", "/tmp/claude-0/-home-user-website/74038a8a-b0f9-507c-bb0a-47f7b7c402f2/scratchpad/nfl")
OUT = os.path.dirname(os.path.abspath(__file__))


def load():
    return pd.read_parquet(f"{SCRATCH}/pbp_slim.parquet")


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"),) * 3
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, c - h, c + h


def cluster_mean_ci(values, groups, B=1000, seed=0):
    """Mean with 95% CI from a bootstrap that resamples groups (games)."""
    df = pd.DataFrame({"v": np.asarray(values, float), "g": np.asarray(groups)})
    agg = df.groupby("g")["v"].agg(["sum", "count"])
    s, c = agg["sum"].to_numpy(), agg["count"].to_numpy()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(s), size=(B, len(s)))
    boots = s[idx].sum(1) / c[idx].sum(1)
    return float(s.sum() / c.sum()), float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))


def cluster_sum_ci(values, groups, B=1000, seed=0):
    df = pd.DataFrame({"v": np.asarray(values, float), "g": np.asarray(groups)})
    s = df.groupby("g")["v"].sum().to_numpy()
    rng = np.random.default_rng(seed)
    boots = s[rng.integers(0, len(s), size=(B, len(s)))].sum(1)
    return float(s.sum()), float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))


def r(x, k=4):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), k)


def write(study):
    p = os.path.join(OUT, f"{study['id']}.json")
    with open(p, "w") as f:
        json.dump(study, f, indent=2)
    print("wrote", p)
