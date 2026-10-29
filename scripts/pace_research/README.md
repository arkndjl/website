# Pace research (Oct 29 2026)

Pace terms for every game model's total, judged against the closing line on held-out seasons. Each candidate is a
walk-forward stack (fit on the seasons before the one it scores) on the model total, and on the closing total plus the
model's gap to it. A term passes at tune t <= -1.5 (paired, clustered by day) with held-out t <= 0. Results:
data/pace_research.json. Downloads and outputs go to scripts/.cache/pace/. Run from this folder.

- `run_basic.py nba cbb nhl`: opponent-adjusted pace (possessions; NHL shots on goal and xG) as expected pace, pace x
  line, fast-vs-slow clash and recent trend. NBA and NHL fail (NHL shots pass held out only, t -3.0, tune -0.5 on two
  seasons of closes). CBB trend passes the screen.
- `run_cfb.py`: plays and drives. Plays help the model total (t -1.6 / -1.8) but add nothing over the close.
- `nfl_pull.py 2013 2019`, `nfl_pull.py 2020 2026`, then `run_nfl.py`: plays, neutral seconds a play, no-huddle share,
  drives (nflverse play-by-play). All fail.
- `soccer_pull.py`, then `run_soccer.py`: shots, shots on target and xG tempo on over/under 2.5 (big five, closes
  2020 on). All fail.
- `cbb_thl.py 20 45`: the CBB model with the total's tempo on its own half-life. Shipped at 20 days (scripts/cbb_games.py
  thl).
