# Soccer metric audit, Nov 24 2026

`audit.py` -> `results.json` (`audit.log`); prereg `prereg.md` (+ Amendment 1, hashes in `prereg.sha256`);
`fotmob_pull.py` pulls FotMob big-five season lists into scripts/.cache/soccer/fms (gitignored). Seasons 2015..2026
(2014-15 .. 2025-26); 2026-27 never read. Big five, 1,170 team-seasons; result = league GD a match, centred by
league-season. 90% intervals from 2000 resamples of seasons / season pairs.

| metric | describe R2 | describe held-out | predict team R2 | predict player r (own) | r vs n+1 SV/90 | n pairs |
|---|---|---|---|---|---|---|
| GAR (/90) | .876 | .875 (.867-.884) | .648 (.634-.663) | .789 | .662 | 11 |
| SV / SVAR | **.895** | **.894 (.888-.900)** | .630 (.609-.653) | .682 | .682 | 11 |
| aGAR/90 | .872 | .872 | .649 (.635-.663) | .792 | .668 | 11 |
| p/90 (pg90, before) | .832 | .831 | .634 (.620-.651) | .918 (overlapping seasons) | .690 | 11 |
| p/90 (pg90, after: P4) | | | **.650** (held, LOPO) | | **.718** | 11 |
| xMV | .747 | .743 | .567 | .853 | .537 | 11 |
| Transfermarkt value | .703 | .698 | .568 | .898 | .562 | 11 |
| G+A/90 | .845 | .845 | .546 | .761 | .526 | 11 |
| npxG+xA/90 (Understat) | .780 | .779 | .556 | .864 | .543 | 11 |
| xGChain/90 (Understat) | .755 | .754 | .554 | .788 | .605 | 11 |
| on-pitch xGD/90 | .864 | .863 | .619 | .627 | .486 | 11 |
| FotMob rating (top lists only, ~45% matched) | .284 | .282 | .546 | .667 | .509 | 9 |
| team GD of season n (team baseline) | | | .584 (.553-.616) | | | 11 |

Totals (roster sum of n values over n+1 clubs -> n+1 GD; player r vs n+1 GAR total): 1Y (pj) team .653 vs GAR total
.655 on the same 2017+ pairs (pj better in 5/9 pairs); player r .745 vs .728. 3Y (p3) vs GAR over n+1..n+3: r .731 vs .697.
Prospect FV: not on this harness; cohort-out MSE 53.85 vs 63.3 age+MV (R2 .434, data/soccer_prospects_fit.json).

Best descriptive: **SV / SVAR** (held-out .894, interval clear of GAR's). Best predictive: **p/90 after P4** (team R2
.650 ties GAR .648 / aGAR .649 within interval, player r .718 clear of every other metric); ours either way.

## Candidates (predictive; target team R2 held out leave-one-pair-out, guard player r vs n+1 SV/90 within .01)

| candidate | team R2 before -> after | player r | t / p (11 pairs) | pairs | result |
|---|---|---|---|---|---|
| P1 pSV/90 (Marcel on SV) | .634 -> .643 | .690 -> .719 | 2.77 / .003 | 8/11 | pass (Holm) |
| P2 p/90 decay/K retune | .634 -> .640 | .690 -> .689 | 6.81 / <.001 | 10/11 | pass (Holm) |
| P3 p/90 + age over 29 | .634 -> .643 | .690 -> .693 | 3.53 / <.001 | 9/11 | pass (Holm) |
| P4 = P1 + P3 (post hoc, Amendment 1) | .634 -> .650 | .690 -> .718 | 5.70 / <.001 | 11/11 | pass, beats P1 (t 2.77) and P3 (t 2.33) |

Shipped P4 (Amendment 1 rule): scripts/soccer_players.py rate_attach on SVAR, weights 1/.5/.25, K F2.5 M2.5 D5 GK320
90s toward the SV regulars' mean, minus .008 a year over 29 (picks identical in all 11 folds; co sits on the grid edge).
