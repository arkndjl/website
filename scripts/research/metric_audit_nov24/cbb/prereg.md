# CBB metric audit, pre-registration (Nov 24 2026, written before any candidate was scored)

Data: Barttorvik getadvstats csv 2010-2026 + <season>_team_results.json (scripts/.cache/team_adj, not committed);
roster prior inputs from /mnt/project-files/cbb/backtest/research_seasons.csv. Lockbox: nothing from 2026-27 (2027 files
not downloaded). Season n = season ending in n. Pairs n = 2012 ... 2025 (n+1 = 2013 ... 2026), 14 pairs.

Exposure = minutes (gp x mpg). Team value = sum(rate x minutes) / games, centred within season.
Team results: (a) Barttorvik adjusted efficiency margin adjOE - adjDE (pts / 100, schedule adjusted);
(b) win% (wins / games, the actual result). Descriptive metrics are judged on (b), predictive on (a).

## Metrics scored (inventory)
Ours: BPM (= WAA rate; Torvik BPM is the input of CBB WAR), WAR rate (BPM + 2), Stat+ (position z of BPM, season norms),
roster prior BPM_hat (scripts/cbb_roster.py player model, walk-forward, predictive only; scored returners-only with the
same fill as the rest, and with its own freshman / newcomer projections).
Public (Barttorvik, free): GBPM (game-script BPM), PRPG! (porpag, offense only), total PRPG (porpag + dporpag).
Not scored: FV (target is NBA outcome, its own backtests), Next (WAR count on returners; data/cbb_next_fit.json has its
held-out record), EvanMiya / KenPom (no free player data), ORtg / DRtg (not additive values).

## Tests
describe: in-sample pooled R2 and leave-one-season-out slope R2 (1 - SSE / SST on centred values).
predict: season n rates x season n+1 minutes -> n+1 adjEM, pooled R2 (squared corr); missing players filled with the
mean of season-n players under 200 minutes. player r: season n value vs n+1 value (same metric, and vs n+1 BPM),
weighted by n+1 minutes, 300+ n+1 minutes. 90% intervals: 2000 bootstrap resamples of seasons / pairs.

## Candidates (each tuned leave-one-pair/season-out; one test each; Holm over the batch of 6)
Predictive (target: next-season team R2 on adjEM; per-pair R2 difference paired t, one-sided; plus guard: player r vs n+1
BPM must not fall more than .01):
- P1 two-year BPM: (B_n m_n + w B_n-1 m_n-1) / (m_n + w m_n-1), w in {0, .25, .5, .75, 1}
- P2 minutes shrink: (B m + c k) / (m + k), c = mean of under-200-minute players, k in {0, 100, 200, 400, 800}
- P3 class step: B + d(class n), d = mean minutes-weighted BPM change n -> n+1 by class (Fr, So, Jr, Sr) on training pairs
- P4 GBPM blend: (1 - a) BPM + a GBPM, a in {0, .25, .5, .75, 1}
Descriptive (target: held-out win% R2; per-season SSE difference paired t, one-sided):
- D1 GBPM blend as P4, a chosen on the other seasons' win% fit
- D2 PRPG blend: BPM + a x z(total PRPG rate) scaled to BPM sd, a in {0, .25, .5, 1}
Ship rule: Holm-adjusted p < .05 on its own target, held out, and the guard. Nothing else is tried.
