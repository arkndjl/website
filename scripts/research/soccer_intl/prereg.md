# National-team picks test (pre-registered before any look at returns)

Model: scripts/soccer_intl.py Poisson ratings with the squad-value term, settings tuned on 2000-15 only.
Sample: every ESPN international match with the partner book's (ESPN BET to late 2025, DraftKings after) open and
close, June 2024 to Nov 2026. None of it was used in tuning.

1X2: at the open, take the outcome with the largest model EV = p_model x decimal_open - 1; a bet when EV >= 5%.
Totals: over/under at the open line (whole and half lines only), EV >= 5%.
Score: CLV = p_close (no-vig, proportional) x decimal_open - 1 per bet, clustered by month; realized return at the open.
Pass: mean CLV > 0 with t >= 2 AND realized return not below -2 SE. One pass, no cut search. A fail keeps
national-team picks off (paper only on Predictions).
Also reported (not a gate): open -> close tilt, logit(close) = logit(open) + b (logit(model) - logit(open)).
