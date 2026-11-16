# FV driver ports across sports: results (Nov 16 2026)

Pre-registration: prereg.md (sha256 6ba02138431e, written before any test ran; it holds the full driver x sport matrix).
Research only: nothing passed, no board or fit file changed.

| Test | Port (from -> to) | Primary (held out) | One-sided p | Holm | Co-gates | Result |
|---|---|---|---|---|---|---|
| C1 | soccer detailed position block -> CBB returner ladder (6 Barttorvik role dummies) | class folds t -0.85, 1/5 (player splits t -1.85, -1.01) | .80 | m 3 | held deviance t +1.52 but top 10/50 worse; fwd t +1.49 | FAIL |
| C2 | soccer lg_share -> CBB (z team strength + 2.5) x minutes share | class folds t -2.35, 1/5 | .99 | m 3 | held top 10/25/50 all worse | FAIL |
| C3 | soccer .5 linear + .5 GBM tree blend -> CBB ladder rungs | class folds t -1.24, 1/5 (player splits t -3.34, -3.26) | .89 | m 3 | held t -1.75 0/3, top 10 41.9 -> 40.9 | FAIL |
| T1 | intl basketball pooled rungs -> WTA hurdle fit on WTA + ATP | birth-year-out t -0.16, 7/19 (MSE 31.492 -> 31.493) | .56 | m 1 | inner CV picks the least pooling (lambda 1) in 19/19 years; fwd 28.734 -> 28.739 | FAIL |
| K1 | CFB special-teams terms -> hockey draft CHL short-handed points a game | class-out t 1.04, 7/12 | .16 | m 1 | top-64 MSE -0.63 but fwd MSE +0.23, fwd top-64 rho -.010 | FAIL |

Reading
- Pooling borrows strength only where the target is thin at the top: intl basketball had 23 careers at 50+ and 7 at 60+, so the
  college rows filled empty rungs. WTA has ~33k rows and a full top, so the inner fit turns pooling off every year.
- Team context times playing time (C2) is strong alone (NBA careers 2.14 vs 0.90 non) but adds nothing beyond power conference,
  BPM and PORPAG, which already carry team strength and minutes. Same story as CFB's SOS/team context and hockey's team GF.
- CBB's G/W/B role split already sits in the fit through ht_g, guard and big; the finer Barttorvik roles add noise on the top rung.
- Trees keep failing on fitted ladders with small upper rungs (60+ rung: ~50 positives under min leaf 40).

Every other cell in the prereg matrix was already tested by an earlier pass (memory notes named there) or has no data.

Rerun
- CBB: `python3 scripts/cbb_careers_kit.py`, then `python3 scripts/research/fv_port_nov16/cbb_port.py` (~1 min, needs scikit-learn).
- Tennis: extract /mnt/project-files/tennis/sackmann.tgz to scripts/.cache/tennis/, `python3 scripts/tennis_prospects.py --rows`
  (~3 min), then `python3 scripts/research/fv_port_nov16/tennis_port.py` (~2 min).
- Hockey: `python3 scripts/hockey_fv_drivers.py --pull` (~2 min), then
  `HOCKEY_DRV_OUT=/tmp/x.json python3 scripts/research/fv_port_nov16/hockey_port.py --cands=chlSH`. The draft-model part prints
  first; the harness's stage loop then stops on KeyError 'comp' (stage fit's comps column is not built by hockey_fv_drivers
  stage_cands), so hockey_results.json was copied from the printed line.
