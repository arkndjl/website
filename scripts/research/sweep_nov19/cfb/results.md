prereg sha256: bb57fb70c8a40611279602618ddd90e2faa89ad7f8448642847292e415fbc2b6 (impl/cfb/prereg.md, written before any scoring)

# CFB sweep leads: results (Nov 19 2026)

Branch sweep-cfb, worktree /home/user/wt-cfb. Zero CFBD calls. No 2026 game from week 11 on was read.
The container has no scripts/.cache (CFBD pulls live only in the Actions cache; the research artifact expired), which
shaped leads 1, 3, 10 and 11: see each row.

| # | Lead | Verdict | n | Split | Effect | t | Holm p | Why |
|---|------|---------|---|-------|--------|---|--------|-----|
| 1 | Board off CFBD (mirror parity) | FAILED parity, not switched; tools built, dormant | 685 games, 121,979 plays; 129 RB + 60 WR/TE lines; 138 teams | 2026 wk 1-10 vs the Nov 10 CFBD-built board | RB line identical 83.7%, WR/TE 93.3% (bar 99%); style within .01: run 64%, success 70%, PPA 7-14%, explosiveness 9% | - | - | Coverage is 685/685 games, but player lines and team PPA do not match the committed CFBD-built numbers within rounding |
| 3 | Transfer% on 5 cycles | FAILED | 10,751 held (33,652 over 3 folds) | walk-forward; held 2025->26 | log loss .5447 -> .5517 (worse); AUC .644 -> .648 | -1.42 | 1.0 | More cycles lose on log loss in all 3 folds (-2.7, -8.5, -1.4): the transfer rate drifts by year |
| 3b | recency weights (on the 5-cycle fit) | not shippable | same | same | +.0095 ll vs equal weights | 4.11 | - | Beats equal weights but the 5-cycle fit itself loses to the 1-cycle fit |
| 3c | 247 transfer rating x level (landing) | BLOCKED | - | - | - | - | - | Needs the CFBD portal pulls in the cfbhist cache |
| 5 | Pre-draft meetings in the mock | PASSED; LOGGING on, mock weight not wired | 300 picks, 96 draft-teams | leave one draft out, 2024-26 | +.144 log-lik a pick (2024 +.190, 2025 +.222, 2026 +.019); top-1 5.7% -> 9.3% | 4.52 | .00005 | T30/private visits carry team information; weight is 3.0 log-pick units in a 40-player window, too large to drop into the live utility untested |
| 6 | Deep final boards for Draft% | BLOCKED (time rule in prereg) | - | - | - | - | - | Not scored; live baseline (FV order) also cannot be rebuilt for past drafts |
| 7 | Coach-level development | FAILED | 13,652 rolling; 3,841 mover rows, 50 coaches | classes 2011-19 | 7a net-of-program slope .49; 7b mover slope -.02 | 1.60 / -0.11 | .27 / 1.0 | Coach effect does not travel; raw rolling t 3.16 is the school effect (school net t 3.22 on the same rows) |
| 8 | Coordinators from Wikipedia infoboxes | SHIPPED (display data) | 138/138 pages, 253 team-roles | vs committed staff file | agreement 97.6% (bar 90%); 6 of 6 disagreements hand-read: infobox right | - | - | 5 mid-season coordinator changes applied with prev records; schemes stored |
| 9 | Ourlads depth charts (absence flag) | BLOCKED | - | - | - | - | - | ~1,240 archive pages from a commercial site at >= 2 s is past the fetch budget left |
| 10 | ESPN-to-recruit id crosswalk | BLOCKED | - | - | - | - | - | cfbd_recruit_ids join to CFBD recruit ids, which no committed file keeps (cfb_recruits_cfbd.json.gz has names only); raw pulls are in the Actions cache |
| 11 | EADA football expenses in landing | FAILED | 2,189 held moves, 134 origin teams | fit 2024->25, hold 2025->26 (proxy model) | -.0012 log-lik a move; swapped fold +.0023 | -0.35 (swap +0.55) | 1.0 | Federal expenses add nothing over donor money + private flag; 130 of 135 FBS schools matched |
| 12 | Sigma from incoming transfers | FAILED | 578 held, 262 tune | tune 2022-23, hold 2024-26 wk 1-4 | tuned c -.25; held log loss +.0040 (worse) | +1.15 | 1.0 | Wrong sign held; 2 of 3 held seasons marginally better, 2026 much worse |

## Notes by lead
- 1. Mirror = cfbfastR_cfb_pbp play_by_play_2026.parquet (Last-Modified Mon Nov 16). Reference = board files of commit
  4993af3c (Nov 10 11:12Z, weeks 10, 685 games). 1a strings through the unchanged cfb_pbp.mjs: RB 108/129, WR/TE 56/60.
  ESPN box scores as a third count on 8 mismatched backs: the mirror is right on 3, the CFBD-built board on 4, neither
  on 1, so both feeds drop plays the other keeps. 1b own aggregates vs CFBD season advanced: r .998 run, .993/.990
  success, .975/.976 PPA, .83 explosiveness, PPA offset +.034. 1c: the live margin is fit on ESPN play-by-play
  (liveInput), no CFBD plays/drives/advanced input reaches runModel on the live path, so margins are unchanged by
  construction. 1d: 685 of 685 FBS games. The release's play_type is cfbfastR's cleaned label (436 "Pass Reception"
  rows relabelled touchdowns); orig_play_type is CFBD's. Built and left dormant: scripts/cfb_mirror.py (parquet ->
  weekly CFBD-shaped files, ETag-keyed, deletes the download), scripts/cfb_mirror.mjs (reader, coverage guard),
  .github/workflows/cfb-mirror-parity.yml + mirror_parity_cache.mjs (play-by-play comparison against the cfb- cache,
  zero CFBD calls). fetch_cfb.mjs is unchanged.
- By-week player box loader for the markets-awards worker: none was built as a module. The pattern used is in
  scripts/research/sweep_nov19/cfb/transfer_cycles.py (espn_cfb_player_box/player_box_<Y>.parquet joined to
  espn_cfb_schedules/cfb_schedule_<Y>.parquet on game_id for week and date; athlete_id is numeric-as-string).
- 3. Self-contained features (year in school from first roster season, position, level, games with a box line, home
  distance, home state); not the live PFN feature set. Transfer rate among stay-or-move rows: 2025->26 25.5%.
- 5. Pages stamped Apr 24 2024, Apr 23 2025, Apr 20 2026: all before round 1. Baseline (board log-rank + repeat
  position) is weak in a 40-player choice set (log-lik -3.63 to -4.00); no historical team-need term. Fit on all
  three: T30/PRI 1.378, other 0.804, board 0.457. scripts/nfl_meetings.py logs the 2027 page with dates once it exists.
- 7. Head coach by season from scripts/data/coach_alltime_src.json.gz (20,424 of 24,450 signees matched).
- 8. Applied: Florida State DC Ernie Sims, Michigan OC Jim Harding, Oklahoma OC Jason Witten, Marshall OC Gunter
  Brewer, Oregon OC Jay Johnson. The file changes only when the infobox names someone it does not have (infoboxes
  often list one of two co-coordinators). Reads /wiki/<title>?action=raw; /w/ is disallowed in robots.txt.
