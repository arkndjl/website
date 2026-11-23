# CS2 provisional (ESEA-only) FV drivers: results (Nov 23 2026)

Pre-registration: PREREG.md (amendment 1: cutoffs need 90+ days of bo3.gg history). Script: scripts/cs2_prov_research.py
-> data/cs2_prov_research.json (rerun weekly by esea-research.yml as a standing retest).

Data: ESEA seasons 47-52 fetched for this test (research/esea_regions_early.json.gz all regions,
research/esea_matches_early.json.gz NA box lines) + S53-59. 2,739 ESEA players linked to bo3.gg. Labeled rows (ESEA-only
at season end, 600+ bo3.gg rounds the next year): 798 (was 84 NA-only). Tune S49-52 421 rows, held S53-54 377 rows / 275 players.

| spec | vs | held MSE | clustered t | bias t | slope | Holm | result |
|---|---|---|---|---|---|---|---|
| S1 division x region | tune mean | 1.967 -> 1.875 | -2.03 | -3.15 | 1.40 | no (p .021) | FAIL (Holm, bias) |
| S2 + team round share, playoffs, playoff wins, top-3 | S1 | 1.875 -> 1.709 | -4.58 | -3.32 | 1.57 | yes | FAIL (bias, slope) |
| S3 + promoted / relegated / experience | S2 | 1.709 -> 1.688 | -0.81 | -2.87 | 1.52 | no | FAIL |
| S4 + FACEIT level + change | S3 | 1.688 -> 1.688 | -1.72 | -2.87 | 1.52 | no | FAIL |
| S5 NA K-D percentile in division | S1 (NA) | 2.256 -> 1.884 (41 rows) | -1.16 | -1.86 | .88 | no | FAIL (n) |

6-month robustness (S1): t +0.03, bias t -4.93.

Reading: team results carry real ranking signal (S2 t -4.6), but every spec over-projects the held seasons (bias t about -3:
2025 ESEA-to-pro movers rate lower than 2024's) and under-spreads them (slope 1.4-1.6). Nothing grades on the pro scale.
Even ungated, NA Main projects far under the floor: reachers' next-year FV p50 9.3, 83% at the 20 floor (EU Main p50 15.6).
LAURSEN_111: S1 11.1, S2 8.3-10.1 raw -> 20 either way; stays 20 provisional.

Not testable (no point-in-time history): FACEIT Elo (level only, ~all 10 in these divisions), Premier/Leetify, age, LAN, role,
pug stats, prize money (top-3 stands in).

Standing retest: held = every season 53+ with a full year (S55 joins mid-Dec 2026). On a pass the deepest passing spec grades
ESEA-only players (data/cs2_prov_research.json grades -> cs2_players "esea"/"eseaFv" -> prospects ESEA table + csprofile card).

Cross-sport: nothing passed, nothing to port. Lead only: team results within a lower league (S2) for hockey provisional /
soccer prospects, if a sport's provisional test shows the same signal without the era bias.
