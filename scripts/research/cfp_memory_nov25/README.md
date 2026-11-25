# CFP committee memory, Nov 25 2026

Production: `scripts/cfb_cfp_memory.py` -> `data/cfb_cfp_memory.json` (read by `cfb_model.mjs` simulate).

- `fit.py` (run with `PYTHONPATH=../..`): every memory shape on real inputs, per weeks-left, fit 2017-21, held 2022-25 (`fit.json`).
  Chosen on tune likelihood: lin rank + scaled committee model + wins above bubble since the release (3 per weeks-left).
- `realt.py`: paired t of that form vs the old live form on the held-out pairs.
- `sim.py` + `summ.py`: season-sim backtest from every release (also no-memory and lin-per-weeks-left variants).

Held out 2022-25: final log lik -865.9 (old) -> -714.2 (t 4.47, 18 of 20 releases); sim seed log loss 2.477 -> 2.422
(t 1.76); field log loss .0695 -> .0699 (t -.31, level); exact seeds 1.90 -> 1.95 a season (committee's own ranking that
week 2.25). Failed shapes: log rank, rank squared, new losses, rating change, champion flag, unranked flag.
Also fixed: the old gamma was keyed by ESPN's release label, which runs one lower in 2026 than 2025 for the same date.
