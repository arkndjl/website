# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Build a slim combined nflverse play-by-play table (2015-2026) for the NFL studies.

Raw files: SCRATCH/raw/play_by_play_{YEAR}.parquet (downloaded from nflverse-data releases).
Output:    SCRATCH/pbp_slim.parquet
Run with:  python3 -I load.py
"""
import os, sys
import pandas as pd
import pyarrow.parquet as pq

SCRATCH = os.environ.get("NFL_SCRATCH", "/tmp/claude-0/-home-user-website/74038a8a-b0f9-507c-bb0a-47f7b7c402f2/scratchpad/nfl")
COLS = """play_id game_id season season_type week posteam defteam home_team away_team posteam_type
down ydstogo yardline_100 goal_to_go qtr game_seconds_remaining half_seconds_remaining game_half
score_differential posteam_score defteam_score posteam_timeouts_remaining defteam_timeouts_remaining
play_type play_type_nfl desc yards_gained first_down touchdown td_team penalty aborted_play play_deleted
qb_kneel qb_spike qb_scramble qb_dropback rush_attempt pass_attempt rush pass sack interception fumble_lost
run_location run_gap rusher_player_id passer_player_id
wp wpa vegas_wp ep epa fourth_down_converted fourth_down_failed third_down_converted third_down_failed
two_point_attempt two_point_conv_result extra_point_attempt extra_point_result
field_goal_attempt field_goal_result punt_attempt kickoff_attempt own_kickoff_recovery
result home_score away_score spread_line timeout timeout_team""".split()


def main():
    frames = []
    for y in range(2015, 2027):
        p = f"{SCRATCH}/raw/play_by_play_{y}.parquet"
        if not os.path.exists(p):
            continue
        names = set(pq.read_schema(p).names)
        cols = [c for c in COLS if c in names]
        df = pq.read_table(p, columns=cols).to_pandas()
        frames.append(df)
        print(y, len(df), df.game_id.nunique(), file=sys.stderr)
    df = pd.concat(frames, ignore_index=True)
    df.to_parquet(f"{SCRATCH}/pbp_slim.parquet")
    print(len(df), "rows", file=sys.stderr)


if __name__ == "__main__":
    main()
