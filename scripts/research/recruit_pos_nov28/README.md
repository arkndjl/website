# Recruit position projection (Nov 28 2026)

Noah asked for recruit positions projected and shown more accurately: hybrid labels where a recruit can play two spots
(PF/C, G/F), and a college position for CFB ATHs (A'mir Sears, Miami). Live script: `scripts/recruit_pos.py`.

## Truth and inputs
- CFB: ESPN class lists in `scripts/data/arkstars_hist_cfb.json.gz` (2014-24 classes, 22,045 recruits with a roster
  match, 1,702 ATHs), each joined by ESPN athlete id to cfbfastR rosters; truth = share of seasons in years 2-4 at each
  group (QB, RB, WR, TE, OL, DL, LB, DB, K/P). Inputs: ESPN position code, height, weight (within the code's family),
  ESPN grade (within family).
- CBB: `scripts/data/cbb_recruit_hist.json.gz` (2009-25, 4,068 matched to Barttorvik), truth = Barttorvik role,
  minutes-weighted over the first two seasons, on five spots (Combo G half PG half SG, PF/C half PF half C). Inputs:
  listed position, height, weight, log rank.

## Results (held out by class; walk forward in brackets)
| | log loss, listed only | model | t | classes |
| --- | --- | --- | --- | --- |
| CFB, all | .645 | .567 | 16.2 (14.4) | 11/11 (8/8) |
| CFB, ATH | 1.551 | 1.232 | 17.0 (12.4) | 11/11 (8/8) |
| CBB | .990 | .887 | 9.2 (9.9) | 17/17 (13/13) |

ATHs: top pick right 39.7% listed only (the ATH base rates) to 47.9%. Size carries most of it (CFB t 13.6); grade adds
on top (t 5.9, 11/11) but not for ATHs (t .37). CBB rank adds on top of size (t 3.4, 13/17).

Failed: the signing school's own past ATH usage (point in time, shrunk; t -2.30, 1/9 classes, 2016-24).

## Labels
A second spot shows at 30% (CFB) or 35% (CBB). Held out: CFB 8.1% of rows get two spots and the truth is in the pair
90.3% of the time (84.7% for one spot); CBB 16.3% get two, 94.0% (63.7% for one).

## FV input (cross-sport rule)
- CFB (`cfb_fv_test.py`): NFL outcome of the 2014-19 classes (the index's target). Projected mix in place of the ATH
  group t -.09 (2/6); on top of the listed group t 1.12 (5/6). Fails. Retest after the 2027 NFL draft.
- CBB (`cbb_fv_test.py`): realized FV, 2009-22 classes, on log rank + square + old. Projected spots t .75 (9/14); with a
  rank interaction t -.92. Fails. Retest after the 2027 NBA draft.
