# Workflow rules

## Shipping

- After a task, commit, push, open the PR and merge it so the site goes live; no confirmation round-trip needed.
- Pull before starting, rebase on main before merging.
- After merging, run `python3 scripts/check_live.py` from the repo root (waits for arkndjl.net `/build.json` to
  serve main or a descendant, 20 minute limit). Don't say "live" before it passes. If it hasn't deployed in about
  20 minutes, look into it and retrigger the build (dispatch the deploy workflow; never an empty commit).
- Cloudflare builds with Hugo 0.147.7: test layout or data changes with that version. A red `build gate` on main
  freezes the site.
- Never write bare `NaN` to `data/*.json` (write null). Guard nullable fields with `with`/`if`, never `cond`.

## Posting schedule (mornings ET)

| Day | Boards |
| --- | --- |
| Mon | Soccer, CS2, Tennis (CS2/tennis delta cut Mon 10 AM, after Sunday finals) |
| Tue | NFL |
| Wed | CFB, NFL Draft |
| Thu | CBB, NBA Draft |
| Fri | NBA |
| Sat | NHL, hockey prospects |

After Dec 6, CFB can move to Monday. Weekly deltas baseline = the 10 AM ET posting-day snapshot. The calendar
`post` key in `data/seasons/<sport>.json` is the source of truth.

## Effort

- Match model, thinking effort and orchestration to the task: light for small edits, data refreshes and status
  checks; heavy for modelling, backtests and analysis. Multi-agent workflows only for broad audits or research
  sweeps, never by default.
- One thread per task. A stalled thread is ported to a new thread with a brief.

## Rules upkeep

- When a standing rule changes, update CLAUDE.md or `docs/rules/` and project memory in the same thread.
- A weekly sync compares project memory with these files and opens a PR with new public rules; the monthly
  PROCESS batch refreshes them too. Public repo: leave private details in memory only.
