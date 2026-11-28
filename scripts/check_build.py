# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""The build gate: what breaks a Cloudflare deploy, checked before a commit lands.

    python3 scripts/check_build.py            # strict JSON + file sizes (seconds; every bot workflow runs it before committing)
    python3 scripts/check_build.py --hugo     # also a full Hugo build into a temp folder (the build-gate workflow, PRs and main)

- every .json under data/ and static/ parses as strict JSON: a bare NaN or Infinity (Python's json.dump default) fails
  Hugo's data loader and every build with it (Oct 21)
- no file under static/ over Cloudflare Pages' 25 MiB per-file limit (warning from 23 MiB)
- static/data/cfb-all.json and cfb-detail.json carry the same dk (the board split in two, scripts/cfb_all.mjs): a
  mismatched pair leaves every scouting report off the board
- static/data/cbb-past.json carries fvg (the grade; fv and fvx at the mean outcome) and data/cbb_fit.json carries
  calibMean: both come from scripts/fv_dist.py past_at_mean, which cbb_fit.py runs after it rewrites the past boards
- data/fv_scale.json K and T match a refit from the boards' tables (scripts/fv_scale.py compute) within 0.25; hockey's
  gap is a warning until its scale is refit (`python3 scripts/fv_scale.py --fit`)
- every row of data/awards.json names a player and his team: a market name the build could not place on a roster must
  be left out by scripts/awards.py blend, never written as a bare row (no photo, team or position; Nov 19)
- with --hugo: data/team_alias.json (the browser's team short forms, layouts/partials/namekey.html) matches
  scripts/names.py TEAM_ALIAS; `python3 scripts/names.py --teams` rewrites it
Local hook: git config core.hooksPath .githooks (runs the fast checks on each commit). Stdlib only."""
import json, os, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIMIT, WARN = 25 * 2 ** 20, 23 * 2 ** 20


def bad_const(c):
    raise ValueError(f'bare {c}')


def check_json():
    errs, n = [], 0
    for top in ('data', 'static'):
        for d, _, fs in os.walk(os.path.join(ROOT, top)):
            for f in fs:
                if not f.endswith('.json'): continue
                p = os.path.join(d, f); n += 1
                try:
                    with open(p, encoding='utf-8') as fh: json.load(fh, parse_constant=bad_const)
                except Exception as e:
                    errs.append(f'{os.path.relpath(p, ROOT)}: {str(e)[:160]}')
    return errs, n


def check_sizes():
    errs, warns = [], []
    for d, _, fs in os.walk(os.path.join(ROOT, 'static')):
        for f in fs:
            p = os.path.join(d, f); s = os.path.getsize(p); r = os.path.relpath(p, ROOT)
            if s > LIMIT: errs.append(f'{r}: {s / 2 ** 20:.1f} MiB, over the 25 MiB Cloudflare limit')
            elif s > WARN: warns.append(f'{r}: {s / 2 ** 20:.1f} MiB (limit 25 MiB)')
    return errs, warns


def check_pairs():
    import re
    sd = os.path.join(ROOT, 'static', 'data')
    dk = lambda f: (re.search(r'"dk":"(\w+)"', open(os.path.join(sd, f), encoding='utf-8').read(400)) or [None, None])[1]
    if not os.path.exists(os.path.join(sd, 'cfb-detail.json')): return []
    a, b = dk('cfb-all.json'), dk('cfb-detail.json')
    return [] if a and a == b else [f'static/data/cfb-all.json dk {a} vs cfb-detail.json dk {b}: write both with scripts/cfb_all.mjs']


def check_cbb_mean():
    errs = []
    try:
        with open(os.path.join(ROOT, 'static', 'data', 'cbb-past.json'), encoding='utf-8') as fh: cols = json.load(fh)['cols']
        if 'fvg' not in cols: errs.append('static/data/cbb-past.json has no fvg (past boards on the grade): run python3 scripts/fv_dist.py --past')
    except (OSError, ValueError, KeyError):
        pass
    try:
        with open(os.path.join(ROOT, 'data', 'cbb_fit.json'), encoding='utf-8') as fh: F = json.load(fh)
        if not F.get('calibMean'): errs.append('data/cbb_fit.json has no calibMean: run python3 scripts/fv_dist.py --past')
    except (OSError, ValueError):
        pass
    return errs


def check_teams():
    sys.path.insert(0, os.path.join(ROOT, 'scripts'))
    import names
    try:
        built = json.load(open(names.TEAM_FILE, encoding='utf-8'))
    except (OSError, ValueError):
        built = None
    return [] if built == names.TEAM_ALIAS else ['data/team_alias.json is behind scripts/names.py TEAM_ALIAS: run python3 scripts/names.py --teams']


def check_terms():
    """data/terms.json (term hovers): a link to a glossary term that no longer exists is a warning, the hover just loses its link"""
    sys.path.insert(0, os.path.join(ROOT, 'scripts'))
    import check_terms as ct
    try:
        return ['terms: ' + b for b in ct.problems()[0]]
    except (OSError, ValueError, KeyError) as e:
        return [f'terms: data/terms.json unreadable ({e})']


def check_article_gfx():
    """articleGFX front matter: quotes and post text must be the article's own words (scripts/article_gfx.py)"""
    sys.path.insert(0, os.path.join(ROOT, 'scripts'))
    import article_gfx as ag
    return ag.problems()


def check_fv_scale(tol=0.25, warn_only=('hockey', 'soccer')):   # soccer: stretch held at the earlier fit (8-season tail)
    """stored K/T against a fresh fit from the tables on disk; returns (errors, warnings)"""
    sys.path.insert(0, os.path.join(ROOT, 'scripts'))
    try:
        import fv_scale
        fresh = fv_scale.compute()
        stored = json.load(open(os.path.join(ROOT, 'data', 'fv_scale.json')))['boards']
    except Exception as e:
        return [], [f'fv_scale check skipped: {type(e).__name__}: {e}']
    errs, warns = [], []
    for b, f in fresh.items():
        for k in ('K', 'T'):
            d = abs(f[k] - stored[b][k])
            if d > tol:
                (warns if b in warn_only else errs).append(
                    f'data/fv_scale.json {b} {k} {stored[b][k]} but the tables fit {f[k]}: rerun scripts/fv_scale.py --fit --restate')
    return errs, warns


def check_awards():
    try: d = json.load(open(os.path.join(ROOT, 'data', 'awards.json')))
    except Exception: return []
    return [f'data/awards.json {sp} {r.get("key")}: row "{x.get("n")}" has no team (unmatched market name; scripts/awards.py blend)'
            for sp, v in d.items() for r in v.get('races', []) for x in r.get('rows', []) if not (x.get('n') and x.get('tm'))]


def check_1nt_sync():
    """1NT + LAURSEN_111 numbers agree everywhere (Noah, Nov 23): season RWA/ARK in the season windows and the
    milestones = data/esea_rwa.json 'seasons'; the milestones' regular-season W-L = the season log's. A milestones
    file older than the RWA file (its step failed) only warns."""
    L = lambda f: json.load(open(os.path.join(ROOT, 'data', f)))
    try: rw, ss, mi = L('esea_rwa.json'), L('esea_seasons.json'), L('esea_milestones.json')
    except Exception: return [], []
    errs = []
    one = rw.get('seasons') or {}
    for sn, s in (ss.get('seasons') or {}).items():
        for p in s.get('players') or []:
            v = (one.get(p.get('name')) or {}).get(sn)
            if v and p.get('rwa') != v[0]:
                errs.append(f'data/esea_seasons.json S{sn} {p["name"]} RWA {p.get("rwa")} but esea_rwa.json has {v[0]}')
    for s in mi.get('seasons') or []:
        sn = str(s['season'])
        for p in s.get('players') or []:
            v = (one.get(p.get('name')) or {}).get(sn)
            if v and (p.get('rwa'), p.get('ark')) != (v[0], v[1]):
                errs.append(f'data/esea_milestones.json S{sn} {p["name"]} RWA/ARK {p.get("rwa")}/{p.get("ark")} but esea_rwa.json has {v[0]}/{v[1]}')
        x = (ss.get('seasons') or {}).get(sn) or {}
        if x and not s.get('current'):
            w = sum(1 for m in x.get('matches') or [] if not m.get('po') and m.get('res') == 'W')
            l = sum(1 for m in x.get('matches') or [] if not m.get('po') and m.get('res') == 'L')
            if (w, l) != (s.get('w'), s.get('l')):
                errs.append(f'S{sn} regular season {w}-{l} in esea_seasons.json but {s.get("w")}-{s.get("l")} in esea_milestones.json')
    if errs and (mi.get('asof') or '')[:16] < (rw.get('asof') or '')[:16]:
        return [], ['1NT numbers out of sync (milestones older than RWA: its step failed?): ' + e for e in errs]
    return errs, []


def check_moves():
    """the weekly move columns: a board file rewritten without scripts/board_moves.py loses them silently"""
    sys.path.insert(0, os.path.join(ROOT, 'scripts'))
    import board_moves
    return board_moves.check()


def check_public(out):
    """The built site: /index.xml is the articles feed, not every page's body (it was 12 MB, Nov 27)."""
    rss = os.path.join(out, 'index.xml')
    if not os.path.exists(rss): return ['public/index.xml (the RSS feed) is missing']
    if os.path.getsize(rss) > 2 ** 20: return [f'public/index.xml is {os.path.getsize(rss) / 2 ** 20:.1f} MiB: the feed lists articles with a summary (layouts/_default/rss.xml)']
    return []


def check_boards():
    """warnings for a board that carries one team or one player twice: an FBS team on the CFB board that is not in the
    team table (a source renamed it, e.g. Sam Houston State, and its roster split in two), and the same name at the
    same team twice on the CBB board (one player under two game-log ids)"""
    from collections import Counter
    out = []
    try:
        d = json.load(open(os.path.join(ROOT, 'static', 'data', 'cfb-all.json'), encoding='utf-8'))
        c = {k: i for i, k in enumerate(d['cols'])}
        have = {t['team'] for t in json.load(open(os.path.join(ROOT, 'data', 'cfb_teams.json'), encoding='utf-8'))['teams']}
        lost = Counter(r[c['team']] for r in d['rows'] if r[c['div']] == 'FBS' and r[c['team']] and r[c['team']] not in have)
        out += [f'CFB board: {n} players at "{t}", an FBS team missing from data/cfb_teams.json (team alias in scripts/fetch_cfb.mjs?)'
                for t, n in lost.items() if n >= 10]
    except (OSError, ValueError, KeyError) as e:
        out.append(f'CFB board team check unreadable ({e})')
    try:
        d = json.load(open(os.path.join(ROOT, 'static', 'data', 'cbb-all.json'), encoding='utf-8'))
        c = {k: i for i, k in enumerate(d['cols'])}
        dup = [k for k, n in Counter((r[c['name']], r[c['team']]) for r in d['rows']).items() if n > 1]
        if dup: out.append(f'CBB board: {len(dup)} players listed twice at one team ({", ".join(f"{a}, {b}" for a, b in dup[:4])})')
    except (OSError, ValueError, KeyError) as e:
        out.append(f'CBB board duplicate check unreadable ({e})')
    return out


def check_hugo():
    hugo = shutil.which('hugo') or os.environ.get('HUGO')
    if not hugo: return ['hugo not found (set HUGO or put it on PATH)']
    out = tempfile.mkdtemp(prefix='gate-')
    try:
        r = subprocess.run([hugo, '--quiet', '-d', out], cwd=ROOT, capture_output=True, text=True)
        if r.returncode != 0: return ['hugo build failed:\n' + (r.stderr or r.stdout)[-3000:]]
        return check_public(out)
    finally:
        shutil.rmtree(out, ignore_errors=True)


if __name__ == '__main__':
    errs, n = check_json()
    e2, warns = check_sizes(); errs += e2 + check_pairs() + check_cbb_mean() + check_awards() + check_article_gfx()
    e3, w3 = check_fv_scale(); errs += e3; warns += w3
    e4, w4 = check_1nt_sync(); errs += e4; warns += w4
    warns += check_terms() + check_boards()
    if '--hugo' in sys.argv[1:]: errs += check_teams() + check_moves()
    if '--hugo' in sys.argv[1:] and not errs: errs += check_hugo()
    for w in warns: print('warning:', w)
    for e in errs: print('FAIL:', e)
    print(f'build gate: {n} JSON files, {"FAILED" if errs else "ok"}')
    sys.exit(1 if errs else 0)
