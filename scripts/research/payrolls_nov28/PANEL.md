# Payroll panels (research input for scripts/research/payrolls_nov28/test.py)

One gzip JSON per league: `scripts/research/payrolls_nov28/panel_<lg>.json.gz`

```
{"lg": "nfl", "unit": "wins", "src": "...one line on sources...",
 "seasons": {"<s>": {"cap": cap $M, "min": league minimum salary $M, "gp": games a team plays}},
 "rows": [ {"s": 2019, "tm": "BUF", "w": 10, "gp": 16, "pts": null,
            "pl": [ {"id": "<stable id>", "n": "Name", "pay": 3.85, "v": 1.2}, ... ] } ] }
```

- `s`: season. NFL and MLS = the calendar year the season is played. NBA and NHL = the year the season ends (2024-25 = 2025).
- `w`: team wins that season (regular season). MLS: `w` = league points, `gp` = matches. NHL: `w` = standings points / 2 is fine,
  say which in `src`.
- `pl`: every player with a cap hit or a value row for that team that season.
  - `pay`: his cap hit / salary charged to this team that season, $M (null when he played but no pay row joined; 0 is a real 0).
  - `v`: his value over replacement that season with this team, in the league unit (NFL WAR, NBA VORX, NHL WAR in wins,
    MLS goals added above replacement), or null when he had pay but no value row (injured, did not play: count 0 later).
  - A traded player: split by team where the source allows; otherwise give the row to the team he finished with and say so in `src`.
- Dead money / buyouts: add rows with `"dead": 1`, `v` null, when the source has them; otherwise none.
- Point in time: everything in a row is about season `s` only. Do not put later projections or later seasons' numbers in.
- Use the site's existing data and fetchers first (static/data/*, scripts/data/*, scripts/xaav.py helpers, scripts/names.py for name joins).
  Respect robots.txt and a polite delay (>= 1.2 s a request; Basketball-Reference 3.5 s). Never fetch overthecap.com directly
  (its robots.txt bars AI agents); OverTheCap data comes only through nflverse.
- Print a join report: share of payroll $ matched to a value row, share of value matched to pay, per season.
