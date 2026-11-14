# National-team soccer (Nov 14 2026)

`scripts/soccer_intl.py --fit` -> `data/soccer_intl_fit.json`. Pre-registration for the picks test: `prereg.md`.

| | matches | model | no squad value | Elo |
|---|---|---|---|---|
| tuning 2000-15 | 14721 | 0.88046 | 0.88218 | 0.90077 |
| held 2016+ | 10133 | 0.85946 | 0.86179 | 0.87502 |

Held out: squad value term t -5.9, model vs Elo t -8.3 (clustered by month).
Against the book (2024-06-02 on, 1525 matches): model 0.84852, close 0.83489, open 0.84994.
Picks at the open, EV 5%+: 1X2 766 bets CLV -0.7% (t -0.48),
O/U 571 bets CLV -1.4% (t -2.53): FAIL, no picks.
Also tried: top-11 instead of top-23 squad value (same to .0001).
