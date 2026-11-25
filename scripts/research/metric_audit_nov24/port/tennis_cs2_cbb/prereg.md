# Port round, tennis / CS2 players / CBB + duplicate games check (Nov 24 2026), pre-registration

Written before any candidate below was scored. Rules as BRIEF.md / PORT.md: held out only, each change judged on its own
target, Holm within each batch (one-sided, .05), lockbox untouched (tennis / CS2 nothing from Nov 11 2026; CBB nothing
from 2026-27), season values stay season-only (shrink toward league average allowed, never toward a prior rating).
Not redone: round-1 tennis D1-D2 / P1-P2, CS2 P1-P3 / D1-D4, CBB P1-P4 / D1-D2, and every item on the BRIEF don't-redo list.

## Tennis (harness: scripts/research/metric_audit_nov24/tennis, live model scripts/tennis_model.py with round-1 changes)
T-P1 (idea 7) player x surface offsets on top of the live match blend. Walk-forward pass of the live model; every row
  (all levels, 2008 on) gets the live blend chance p (walk-forward blend weights as wf_probs). Offset per player x
  surface before each row: o_s = R_s / (V_s + k) - R_all / (V_all + k), R = decayed sum of (won - p), V = decayed sum of
  p(1 - p) (half-life h days), so only the surface-specific part of the residual counts. Term c x (o_a - o_b) added to
  the blend logit. c fit on tune seasons 2012-19; k in {10, 30, 100}, h in {365, 1000} chosen on tune; held 2020-26
  (to the export's Oct 26 2026 end). Target: log loss of tour-level main-draw matches (scored rows), t by tournament.
  Pass: Holm p < .05, held log loss down, 4+ of 7 held seasons better.
T-D1 (idea 2) rPA as the per-match mean of match-level rPA (each match's 100 x PA / points, equal weight a match), shrunk
  toward 0 by k_m matches, k_m = 300 / median points a match in the data (fixed, the shipped 300-point shrink in matches).
  Base = rPA shrunk 300 (shipped). Target: describe held out (half-A metric -> half-B matches, round-1 score.py), t by
  tournament, 9+ of 15 seasons, player r not down > .01.
  SV per-match mean: SV is already the sum of match-level credits, so "per-match mean x matches" is SV itself; not a
  change (reported only).

## CS2 players (harness: scripts/research/metric_audit_nov24/cs2, frozen copy of scripts/cs2_players.py)
Predictive batch (target: held months Jul 2025 - Oct 2026 next-month map round-share MSE, walk forward, t by month,
player r vs next-month box RWA not down > .01, same sign on tune months):
C-P1 (idea 5) tier weighting in the RWA rating: map rows at B / C / D-tier events (bo3.gg tier 3-5) weighted lam
  in the rating's decayed mean (S / A tiers 1). lam in {0.85, 0.7, 0.5}, chosen on tune months [1::2].
Descriptive batch (target: held-out-half describe R2 a month, held months; tune months for grids and sign):
C-D1 (idea 5) season RWA (window mean, no shrink: what alltime.py ships) shrunk toward 0 (league average contribution)
  by k rounds, k in {50, 100, 200, 400, 800} on tune months. Season-only (no prior rating).
C-D2 (idea 2) season RWA as the per-map mean of map-level RWA (equal weight a map) instead of rounds-weighted.
C-D3 (idea 5) displayed K-D per round shrunk toward the month's rounds-weighted mean by k rounds (grid as C-D1).
C-D4 (idea 5) displayed ADR shrunk the same way.
Also reported (not a candidate): round-1 D4 shrinks season RWA toward the rating at the window start, a prior rating,
which the port rule forbids for season values.

## CBB (harness: scripts/research/metric_audit_nov24/cbb/audit.py, Barttorvik game logs scripts/.cache/cbb/games 2017-26)
B-P1 (idea 5) level weighting in a predictive rate: per-game GBPM mean (minutes x possessions weighted) with games
  against opponents ranked outside the season's top 200 by Barttorvik adjEM weighted lam, lam in {1, .85, .7, .5}
  chosen leave one pair out. Base = lam 1. Target: next-season team adjEM R2 (audit.py predict), t by pair.
  Even if it passes, ship only if the roster prior (the site's predictive metric) does not already beat it.
B-D1 (idea 5) displayed rate shrink: a player's GBPM (WAR's rate) from half A of his games (game-date hash) shrunk toward
  the season's minutes-weighted mean by k minutes, k in {0, 50, 100, 200, 400} chosen leave one season out; target
  minutes-weighted squared error vs his half-B GBPM (players with minutes in both halves), t by season. Raw box
  percentages (3P%, TS%) are counts and stay raw.
B-C1 (idea 7) home-court player offsets: plausibility gate first. Split-half reliability of (home GBPM - away GBPM)
  over odd / even games, players with 200+ minutes both sites; only if r >= .10 is an offset model tested.

## Idea 8 duplicate games (every sport's game logs used by replays / models)
Counts per log: (a) repeated game id; (b) same date + same unordered pair of team ids; (c) same date (+-1 day) + same
final score + one side the same team or the same player set, other side under another id/name (alias); (d) for logs with
lineups / boxes: same date and a side's player set identical to a side of another game. Logs: nhl_games_hist,
nba_games_hist, cbb_games_hist + Barttorvik player game logs, cfb_hist_md (cfb_model inputs), nflverse games.csv,
soccer_games_hist, tennis matches.csv.gz, ESEA research/esea_matches.json.gz, bo3.gg CS2 maps. A clear, small loader bug
gets a data fix; anything else is reported.
