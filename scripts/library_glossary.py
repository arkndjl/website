# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Build research/library.json (then run scripts/library_build.py): ARKBOARD Process tab content (glossary + FV conversion charts)."""
import json, math, os, re

import pathlib
ROOT = str(pathlib.Path(__file__).resolve().parent.parent)
OUT = ROOT + '/research/library.json'
ld = lambda p: json.load(open(f'{ROOT}/{p}'))

# live fit numbers (Process regenerates from these, never hand-typed)
_SC = ld('data/fv_scale.json')['boards']
_KT = ', '.join(f"{n} {_SC[b]['K']:.1f} / {_SC[b]['T']:.1f}" for n, b in
                (('CFB', 'cfb'), ('CBB', 'cbb'), ('hockey', 'hockey'), ('soccer', 'soccer'), ('ATP', 'atp'), ('WTA', 'wta')))
_CBBK = ld('data/cbb_live_fit.json')['k']
_CFPM = ld('data/cfb_cfp_memory.json')                       # CFP committee memory (scripts/cfb_cfp_memory.py)
_CFPMR, _CFPMS = _CFPM['realInputs'], _CFPM['sim']['hold']
_HKF = ld('data/hockey.json')['fit']
_HKN = {'ls': 'log slot (board rank as slot)', 'nhle': 'draft-year NHLe', 'D': 'defense', 'G': 'goalie',
        'chl1': 'CHL first-round pick', 'cs': 'class strength', 'agenh': 'age', 'ht': 'height', 'wt': 'weight'}
_HKEPT = ', '.join(dict.fromkeys(_HKN.get(k, k) for k in _HKF['kept'] if k != 'ls2'))

_NX = ld('data/nba_proj3y_fit.json')['exit']['res']['1.0']
_RX = ld('data/nba_rxpm_research.json')['metrics']
_NB = ld('data/nil_budgets.json')                           # reported roster budgets by school (yNIL)
_ND = ld('data/nil_deals.json')['deals']                       # reported deals (yNIL, xNIL, the price fit)
_NM = ld('data/cbb_market.json')['nilFit']['budget']           # basketball budget levels without a report
_NPOS = ', '.join(f'{g} {round((math.exp(v) - 1) * 100):+d}%' for g, v in ld('data/cfb.json')['nilFit'].get('pos', {}).items()) or 'none yet'
_nbm = lambda k: sum((lo + hi) / 2 for lo, hi in _NB[k]['teams'].values()) / len(_NB[k]['teams'])
_VX = ld('data/nba_vorx_research.json')                         # VORX on rXPM (scripts/nba_vorx_research.py)             # rXPM team adjustment (scripts/nba_rxpm_research.py)
_NT = ld('data/nba_trade_fit.json')                         # NBA draft-night trades (scripts/nba_draft_trades.py)
_AGY = ld('data/agencies_board.json')['sports']
_AGTR = ld('research/agency_tendency.json')
def _agt():
    out = []
    for sp, nm in (('cfb', 'Football'), ('cbb', 'Basketball')):
        parts = []
        for k in ('Deal', 'Situation', 'Reach', 'Breakout', 'Stability'):
            t = _AGTR.get(sp, {}).get(k)
            if t: parts.append('%s r %.2f, p %.3f%s' % (k, t['r'], t['p'], ' (shipped)' if t.get('ship') else ''))
        out.append(nm + ': ' + '; '.join(parts) + '.')
    return ' '.join(out) + ' Situation is growth in FV over last season against players with the same FV and class, Reach is a power conference spot against players with the same FV and position, and Stability is staying at his school against players with the same FV and class.'
_AGT = _agt()
_AGCR = ld('research/agency_composite.json')
_AGCOMP = ('A check on the 2022-26 search, which is not used: built from the clients on file and the 2022-24 sends, it ranks the %d agencies by the first-round picks they sent in 2025-26 at Spearman %.2f (p %.3f, %d agencies with such a pick). Sends alone %.2f, Deal %.2f, Breakout %.2f, client count %.2f.'
        % (_AGCR['n'], _AGCR['score']['rho'], _AGCR['score']['p'], _AGCR['agencies with a 2025-26 pick'], _AGCR['sent']['rho'], _AGCR['deal']['rho'], _AGCR['breakout']['rho'], _AGCR['vol']['rho']))               # NIL agencies (scripts/agencies.py)
_DR = ld('data/dect_fit.json')                             # DECT, declare / even / college / transfer in dollars (scripts/dect.py)
_TBX = {'cfb': ld('static/data/cfb-builder.json').get('nxFit') or {}, 'cbb': ld('static/data/cbb-builder.json').get('nxFit') or {}}   # scripts/team_builder_next.py
_DX = {k: ld(f'scripts/research/dect_features_nov27/results_{k}.json') for k in ('ret', 'cbb_move', 'cfb_move')}   # DECT as a feature (failed; scripts/research/dect_features_nov27)
_RP = ld('data/return_pay.json')                           # draft pay vs college pay in Return% (scripts/research/ret_pay_nov27/pay.py)
_RD = ld('data/return_drivers.json')                       # Return% sweep + reported-return lock (scripts/return_drivers.py, return_news.py)
_CL = {k: ld(f'scripts/research/coach_loyalty_nov27/results_{k}.json') for k in ('cbb', 'cfb', 'recruits_cfb', 'recruits_cbb')}   # coach loyalty tests
_CMF = ld('data/cbb_market_fit.json')['move']['test']
_CD = ld('data/cbb_declare_fit.json')                      # CBB stay-or-declare (scripts/cbb_declare.py)
_CX = ld('data/cbb_xpm_research.json')                     # CBB pXPM fit + tests (scripts/cbb_xpm.py, scripts/research/cbb_xpm_nov26)
_AG = ld('data/recruit_age_research.json')                  # recruit age for the class (scripts/research/recruit_age_nov26)
_AGB, _AGF = _AG['cbb'], _AG['cfb']
_CS = ld('data/class_score_research.json')                   # class score: top end vs depth against results (scripts/research/class_score_nov26)
_CSF, _CSB = _CS['cfb'], _CS['cbb']
_AS = ld('data/arkstars_research.json')                     # 5-star+ tests (scripts/research/arkstars_nov26)
_AH = ld('data/arkstars_hist_research.json')                # past classes' ARK stars (scripts/arkstars_hist.py --test)
_AHT = _AH['thin']['tests'][_AH['thin']['pick']]
_AHC = [v['graded'] for v in _AH['counts'].values()]
_ASF, _ASB = _AS['cfb'], _AS['cbb']
_STF = ld('data/cfb_recruit_retarget.json')['stars']        # CFB star cuts, 5-star+ model and held-out tiers
_STB = ld('data/cbb_recruits.json')['model']['stars']       # CBB star cuts and the 5-star+ sweep
_STB5 = next(x for x in _STB['plusSweep'] if x['perClass'] == _STB['plusPer'])
_pc = lambda x: f'{100 * x:.0f}%'
_AGC = _AG['coverage']['cfb'][max(_AG['coverage']['cfb'])]
_CX3 = _CX['pxpm3']                                        # board form as model input (Nov 26)
_CX2, _CR = _CX['pxpm2'], _CX['rxpm3']                    # board-form pXPM and rXPM rounds (Nov 26)
_SW = {k: ld(f'scripts/research/xpm_swap_nov26/{k}.json') for k in ('awards', 'next', 'next_inseason', 'breakout', 'declare', 'mock', 'market', 'school_dev', 'backup', 'nba_breakout')}   # BPM to XPM swap tests
_XX = ld('scripts/research/xpm_swap_nov26/xxpm.json')   # xBPM to xXPM test
_CXB = dict(zip(ld('data/cbb_xpm_fit.json')['cols2'], zip(ld('data/cbb_xpm_fit.json')['beta2']['o'], ld('data/cbb_xpm_fit.json')['beta2']['d'])))
import gzip as _gz
_CW = json.load(_gz.open(ROOT + '/scripts/data/cbb_tabs_2026.json.gz'))   # 2025-26 tabs: WAR fit, Stat+ norms (scripts/cbb_tabs.py --freeze)
_PX = ld('data/nba_pxpm_research.json')                     # pXPM fit + held-out tests (scripts/nba_pxpm_research.py)
_NBAEX = (f"Held out 2012-23 ({_NX['n']:,} player seasons, {100 * _NX['exitShare']:.0f}% out of the league), RMSE goes from {_NX['exit_vs_cp']['rmse'][1]:.2f} to "
          f"{_NX['exit_vs_cp']['rmse'][0]:.2f} (t = {_NX['exit_vs_cp']['t']:.1f}, {_NX['exit_vs_cp']['won']}/{_NX['exit_vs_cp']['of']} seasons).")


def _tbx_pot():
    """the targets paragraph, from the builder files' nxFit.pot"""
    P = (_TBX.get('cfb') or {}).get('pot') or {}; R = P.get('rates') or {}
    if not R: return 'Targets are uncommitted recruits a school is in on, each at his chance to sign there.'
    ov = ', '.join(f"{R[k][0]:.2f}".lstrip('0') + f" with {k[2]}" for k in ('ov2', 'ov3', 'ov4') if k in R)
    return ('Targets are uncommitted recruits a school is in on. His chance to sign there is the ARK lean model\'s for that school when '
            'the model has him (its top three schools), else On3\'s RPM share, else his visits: the rate at which committed recruits '
            f'signed with a school they took an official visit to was {ov} official visits and {f"{R.get('ov5', [0])[0]:.2f}".lstrip('0')} with five or more. '
            'Those rates include visits after the commitment, so they run high. A school under 5% is left off. Next class targets add '
            'their chance times what they add to the plan (football: On% times the room AV of his Y1 FV, in Elo; basketball: the team '
            'rating of his projected XPM in the rotation), shown as plan + targets.')

ALLP = ['CFB', 'NFL', 'CBB', 'NBA', 'NHL', 'Hockey', 'Soccer', 'Tennis']


def E(term, short, body, where, sports):
    return {'term': term, 'short': short, 'body': body, 'where': where, 'sports': sports}


sections = []

# ---------------------------------------------------------------- FV and grades
sections.append({'id': 'fv', 'title': 'FV and grades', 'entries': [
    E('FV (future value)', 'FV is a grade on the 20-80 scale of what a prospect becomes at his peak, set as the mean outcome of past players with the same profile.',
      ['50 is an average regular, 60 is a plus player, 70 is a star and 80 is generational. Tiers are every 5 points and grades move in steps of 1.',
       'Each board has its own outcome and rarity ladder. There is no shared FV scale across sports.',
       'The headline is the mean of the tier odds, busts and stars included, so it sits below the best case.',
       'The grade is absolute talent, read from a fixed map fit on pooled history, not a rank within a class or a board.',
       'A strong class gets more high grades. Age and the drivers that pass held out move the grade.'],
      'Every prospect board: CFB, CBB, hockey prospects, soccer prospects, tennis prospects; recruit tabs; MLB boards',
      ['CFB', 'CBB', 'Hockey', 'Soccer', 'Tennis', 'MLB']),
    E('Outcome ladder', 'The outcome ladder is the realized result each FV tier stands for, set by how rare it is on each board.',
      ['CFB: the NFL career (All-Pro, Pro Bowl, seasons as a starter), from the 2012-18 drafts.',
       'CBB: peak NBA XPM, as rare as the matching NBA role (7+ All-NBA teams = 80), for careers ending 2008-16.',
       'Hockey: peak NHL pWAR (best 3 of the first 7 seasons), by rarity in a draft class, 2008-19 classes.',
       'Soccer: peak GAR at ages 22-26, by rarity in a birth year and position group, for players who were 22 in 2013-21.',
       'Tennis: peak ranking points above No. 200 at ages 22-28, by rarity in a birth year on each tour, births 1979-97.',
       'The ATP fit also trains on births after 1997, with partial careers imputed to a final outcome.'],
      'fv model tab on each prospect page; FV conversion charts below', ['CFB', 'CBB', 'Hockey', 'Soccer', 'Tennis']),
    E('Stretched top', 'Above each board\'s knot K the headline runs in a straight line to 80 at T, so an 80 comes about once every 5 seasons.',
      ['The mean of a capped outcome can never reach 80. The stretch makes 80 reachable, but rare.',
       'K is the mean that about 3 players a season reach, and T is the level one player reaches about every 5 seasons (exponential tail, held out).',
       f'K / T: {_KT}.',
       'The order of players doesn\'t change. The exact mean (fvx) stays in the tooltips, and above K the headline reads higher than the realized means.'],
      'Headline FV on every prospect board (data/fv_scale.json)', ['CFB', 'CBB', 'Hockey', 'Soccer', 'Tennis']),
    E('FV range and tier odds', 'Each player\'s odds of reaching every outcome tier, and his 10th to 90th percentile outcome.',
      ['CFB and CBB use a location-scale ordered probit of the realized outcome on the grade, with cut points at 30, 35 ... 70.',
       'A spread term is kept only if it improves held-out RPS (CFB: early season ×2.1, walk-on, consensus, underclassman).',
       'Held out, CFB RPS is .0398 compared to .0408 with one spread, and CBB is .0767. Hockey, soccer and tennis use logistic odds for each tier.',
       'The odds are shown in the player dropdown only. The main boards show the single headline.'],
      'Player dropdowns (outlook), fvd column', ['CFB', 'CBB', 'Hockey', 'Soccer', 'Tennis']),
    E('Tier chances (NBA%, NHL%, Top%, Reg%, Star%)', 'The chance a player reaches a set outcome tier.',
      ['CBB NBA% is the chance he plays in the NBA, the first rung of the FV model.',
       'Hockey NHL% is the chance of 40+ (top 45 of a class), and Reg% is 50+ (an NHL regular, top 20 of a class).',
       'Soccer Top% is 40+ (a top-flight regular, top 250 of a birth year at the position), Reg% is 50+ (top 90) and Star% is 60+ (top 20).'],
      'Board columns: CBB, hockey prospects, soccer prospects', ['CBB', 'Hockey', 'Soccer']),
    E('+ (young for the grade)', 'A + marks a player whose odds of becoming a star beat those of a player 2.5 FV higher, because of his age.',
      ['The rule: + when P(60+ | FV, age) >= P(60+ | FV + 2.5). Age is the only upside signal that passed held out.',
       'Held out, soccer is t = 5.0 / 4.1 at 55+ / 60+, tennis ATP t = 4.3 / 3.3 and WTA 3.9 / 3.1. About 6% of tennis prospects and 30% of the soccer top 2000 get one.',
       'The CFB version failed held out (t = -.71 / -.34) and was removed. No signal passed in CBB or hockey.'],
      'Soccer prospects and tennis prospects boards', ['Soccer', 'Tennis']),
    E('Provisional grade', 'A player who isn\'t on the source board gets a provisional grade, which starts at the 20 floor and takes every driver available for him.',
      ['He is ranked in FV order with a prov tag. CBB uses a ridge on height, weight, class, age, recruit rank and the team\'s top-8 FV (R² .77).',
       'Hockey grades OHL, WHL, QMJHL, AHL and Liiga draft-eligibles from Tankathon on NHLe, age, weight and position.',
       'Soccer gives academy-only and youth-international players their own provisional line.',
       'CFB grades ESPN roster backups and carried-over players up from the 20 floor.'],
      'Boards (prov tag)', ['CFB', 'CBB', 'Hockey', 'Soccer']),
    E('FV scorecard', 'The scorecard checks each board held out: the FV band a player was given against what he became.',
      ['For each band it shows the mean FV given and the mean reached (90% CI), and the predicted 40+, 50+ and 60+ odds against the realized share.',
       'Slopes: CFB .99, CBB .97, soccer 1.01, tennis ATP .99 and WTA .97. Hockey is calibrated.',
       'Where it runs hot: WTA 45-64 by 2.5-4.8, and CFB 40+ odds by 6-8 points at FV 40-49.'],
      'fv model tab, fv scorecard window', ['CFB', 'CBB', 'Hockey', 'Soccer', 'Tennis']),
    E('Driver gate (FV)', 'An input goes into an FV model only if it cuts held-out error.',
      ['Hockey, soccer and tennis: t >= 2 across held-out classes, seasons or birth years, and it wins two thirds of them.',
       'CBB: dropping the driver has to raise out-of-sample deviance in 4 of 5 folds, with whole players held out.',
       'CFB: the multipliers are refit leaving one draft class out, and a driver stays only if the within-position r with NFL AV improves.'],
      'fv model tabs (drivers kept, out-of-sample evidence)', ['CFB', 'CBB', 'Hockey', 'Soccer', 'Tennis']),
    E('CFB FV model', 'The CFB model grades every FBS and FCS player on his NFL outcome.',
      ['The composite is production (Stat+, Marcel 5/4/3, regressed), On3 talent, age, frame, combine, badges and the XV parts.',
       'A player\'s composite rank in his class maps to FV through measured NFL outcome counts at each position (drafts 2012-18).',
       'The scouting consensus (9 boards and the Kiper top 25) is blended in at a weight of .5 at full coverage.',
       'Then comes the outcome step (ordered probit), the mean headline and the stretched top. Positional value scales elite RB, LB, DL, TE and S.'],
      'CFB board, draft board, fv model tab', ['CFB']),
    E('CBB FV model', 'The CBB model grades every D-I player and listed international on his NBA outcome.',
      ['E[FV] = 20 + 10 P(30+) + 10 P(40+) + 10 P(50+) + (mean 60+ career - 50) P(60+), with one ridge logistic for each rung.',
       'Newcomers are graded on recruit rank (On3, 247, Barttorvik) and class. Returners add 3-season BPM, conference power, age, size and rates.',
       'The board stage adds the June draft-board rank and guard combine testing. E maps to a grade on the pooled 2009-16 boards.',
       'The outcome odds are fit on each board\'s top 300. Below that they scale down to the floor those boards realized (1.8% NBA).',
       f"In season, E = (1 - w) × preseason + w × now, with w = minutes / (minutes + k). k is {_CBBK['newcomer']} for newcomers and {_CBBK['returner']} for returners."],
      'CBB board, fv model tab, in season window', ['CBB']),
    E('Hockey FV model', 'An OLS on outcome FV for the draft class and for drafted players short of 100 NHL games.',
      [f'The draft model keeps {_HKEPT}.',
       f"Leave-one-class-out error is {_HKF['mse']:.2f}, compared to {_HKF['mseSlot']:.2f} for draft slot alone ({_HKF['classes'][0]}-{str(_HKF['classes'][1])[2:]} classes, {_HKF['picks']:,} picks).",
       'After the draft, stage models add the latest NHLe, pro games, a World Juniors spot, NHL games and WAR so far.'],
      'Hockey prospects board, drafted prospects, fv model tab', ['Hockey']),
    E('Soccer FV model', 'An OLS on outcome FV for every under-22 in 33 leagues, plus academy and feeder leagues.',
      ['The inputs kept include age, market value (deflated to the level of the fit seasons), GAR this season and last,',
       'minutes share, club strength, scoring rate, height, position and PL2 minutes. 53,682 rows, 2013-20.',
       'The detailed position block (centre-back, full-back, defensive and attacking midfield, winger and striker, against central',
       'midfield) cuts season-out error by -0.10 (t = 3.9, 7 of 8 seasons), and the top 50 and forward tests are better too.',
       'The raw grade is the mean of the OLS grade and a gradient-boosted grade (300 trees of depth 3 on every design input,',
       'one set for each snapshot). Season-out error goes from 55.62 to 54.62 (t = 8.7, 8 of 8 seasons). The trees get no missing-height',
       'signal, and they see market values only as dated on a player\'s own lineups.',
       'Held out by birth cohort, the error is 54.84, compared to 64.42 for age and market value alone (R² .43).'],
      'Soccer prospects board, fv model tab', ['Soccer']),
    E('Tennis FV model', 'A hurdle model for every ATP and WTA player under 22 with a ranking or a pro match in the last year.',
      ['A logistic for any peak value, then an OLS on outcome FV given value: FV = (1 - p) × 20 + p × mean given value.',
       'ATP keeps age, rank, unranked, Elo, 52-week win rate, years since the pro debut and Futures volume.',
       'WTA keeps age, rank, unranked, Elo, rank × age and tour-qualifying volume. Held out by birth year, OOS R² is .50 / .46.',
       'Height is never an input, since the archive fills in height for the players who made it, which leaks the outcome.',
       'The ATP fit also trains on unfinished careers (later births at imputed targets): as-of 2011-18 error goes from 21.45 to 20.24, t = 7.8, 8 of 8.',
       "An ATP tree blend (the mean with a boosted-tree grade) went from 20.24 to 19.86 as of, t = 2.7, 7 of 8, p .015. It was a second form after the first failed, so it counts in the sweep's Holm family of 15 and misses the cut (p <= .005). It isn't used. The WTA trees failed going forward."],
      'Tennis prospects ATP and WTA boards, fv model tab', ['Tennis']),
    E('CS2 prospect FV', 'Projected RWA over the next year against tier-1 starters, on the 20-80 scale (50 = an average tier-1 starter).',
      ['A prospect is a player under 20 with maps at S-tier events. The projection uses rating, age and the share of last year\'s rounds at S/A-tier events.',
       'The S/A share is negative on top of the rating\'s tier lift (held t = -4.9). Rise and every stat line failed.',
       'Cutoffs are quarterly, fit on 2024-25 and held out from Jul 2025. A term ships only if it clears the Bonferroni cut for its batch.',
       'Badges (top 25% on a stat) were tested on prospects and on the main board. None passed, so CS2 shows none.'],
      'Counter-Strike prospects, player model', ['CS2']),
    E('MLB FV (hand-graded)', 'The baseball boards are graded by hand on the FanGraphs 20-80 tiers.',
      ['There is no model. 80 is top 5 overall (7+ WAR a season), 60 is an All-Star (3.4-4.9) and 50 is an average regular (1.6-2.4).',
       'Boards: 2026 draft hitters v1, U19 MiLB prospects and the White Sox org top 64, each in its article. Current prospect grades are on eephus.io.'],
      'Baseball Articles (draft hitters, U19 MiLB and White Sox org articles); eephus.io', ['MLB']),
    E('Recruit FV / xFV', 'Projected FV for high school recruits.',
      ['CFB xFV = P(on board) × FV if on + (1 - P(on)) × 20, in year 1, from a hurdle fit on the ESPN 2023-26 classes.',
       'The CFB recruit profile is weighted on the NFL outcomes of the 2011-19 classes, and the board sets the level.',
       'CBB uses a hurdle on consensus rank and old-for-class: P(reach NBA), then log(FV - 20) given NBA, trained on 2009-16.'],
      'Recruits tabs: 2027-2029 classes, class rankings, recruit model', ['CFB', 'CBB']),
    E('ARK stars', 'A recruit star rating cut on what past recruits with the same profile became, instead of the industry stars.',
      [f"CFB is cut on the recruit index (expected NFL outcome, 2011-19 classes). A class holds about {_STF['tiers'][1]['perClass']:.0f} five-stars, {_STF['tiers'][2]['perClass']:.0f} four-stars and {_STF['tiers'][3]['perClass']:.0f} three-stars.",
       'Share drafted in CFB, held out: ' + ', '.join(f"{'5-star+' if x['stars'] > 5 else str(x['stars']) + '-star'} {_pc(x['drafted'])}" for x in _STF['tiers']) + '.',
       'CBB is cut on FV. 5 = 2+ NBA seasons as a starter, 4 = reached the NBA, 3 = a D-I starter at BPM +3, 2 = played D-I, 1 = did not.',
       'There are half stars inside each tier. The arrow is ARK stars minus industry stars.',
       f"Past classes are graded back to 2008, so a college player carries his high school grade (HS). A CFB class has {min(_AHC):,} to {max(_AHC):,} graded recruits, from ESPN's class lists, the 247 composite and On3's team commit lists.",
       f"A recruit off ESPN's signee list with no ESPN grade gets a correction to his draft odds. Fit on {_AH['thin']['fitOn'][0]}-{str(_AH['thin']['fitOn'][1])[2:]}, tested forward on {_AH['thin']['forward'][0]}-{str(_AH['thin']['forward'][1])[2:]} ({_AH['thin']['nForward']:,} recruits): t = {_AHT['t']:.2f} by recruit, {_AHT['tSchool']:.2f} clustered by school.",
       'Share drafted in the ' + f"{_AH['thin']['forward'][0]}-{str(_AH['thin']['forward'][1])[2:]}" + ' classes against expected: ' + ', '.join(f"{x['k']:g}-star {100 * x['drafted']:.1f}% ({100 * x['expected']:.1f}%)" for x in _AH['tiers']['forward']['tiers'][:4]) + '.',
       f"Reading a lone service's grade on the industry scale failed (t = {_AH['lone']['tSchool']:.2f} clustered by school), so it is not used.",
       'A player no source lists is a 1-star. Kickers, punters and long snappers get no grade.',
       'CBB past classes read the rank to stars curve at the recruit\'s industry rank. No rank is a 1-star.'],
      'Recruits tabs; recruit cards; HS column on the portal tabs', ['CFB', 'CBB']),
    E('5-star+', 'The tier above five stars, for recruits at even odds or better of the top pro outcome.',
      [f"CFB: a five-star with a 50%+ chance of a top-64 pick. There are about {_STF['tiers'][0]['perClass']:.0f} a class. Held out, {_pc(_STF['tiers'][0]['top64'])} went top 64 and {_pc(_STF['tiers'][0]['drafted'])} were drafted (plain five-stars {_pc(_STF['tiers'][1]['top64'])} and {_pc(_STF['tiers'][1]['drafted'])}).",
       f"The chance reads the recruit index, the log industry rank and the industry rating past 95. Held out by class {_ASF['classes'][0]}-{str(_ASF['classes'][1])[2:]}: school-clustered t = {_ASF['E1']['t']:.2f}, {_ASF['E1']['won']} classes. The {_ASF['forwardClass']} class has {_ASF['forward']['new'][1]} of {_ASF['forward']['new'][0]} top-64.",
       f"Top-64 rate for the top 3 of a class: {_pc(_ASF['top3']['elite'])} with the industry terms, {_pc(_ASF['top3']['index'])} on the index alone and {_pc(_ASF['top3']['industry'])} on industry rank. Top 6: {_pc(_ASF['top6']['elite'])}, {_pc(_ASF['top6']['index'])}, {_pc(_ASF['top6']['industry'])}.",
       f"CBB: FV {_STB['cuts'][4]}+, about {_STB['plusPer']} a class. Held out, {_pc(_ASB['tier']['hit'])} became NBA starters (2+ seasons) and {_pc(_ASB['tier']['fv55'])} reached FV 55+ (plain five-stars {_pc(_ASB['plain']['hit'])}).",
       f"The CBB line was re-tested on the same even-odds rule. A line at FV {_ASB['rule']['line']:.1f} ({_ASB['rule']['perClass']:.1f} a class) hits {_pc(_ASB['rule']['hit'])}, but the recruits between the two lines hit {_pc(_ASB['between']['hit'])} and the six-tier R² falls from {_ASB['tierR2']['shipped']:.3f} to {_ASB['tierR2']['rule']:.3f}, so the line stays.",
       f"Position at the top failed in both: CFB quarterback and line flags t = {_ASF['E3']['t']:.2f}, CBB big and point guard flags t = {_ASB['B3']['t']:.2f}."],
      'Recruits tabs; recruit cards', ['CFB', 'CBB']),
    E('Age for the class', 'A recruit\'s age on Sep 1 of the class year, minus the class median. Positive means old for the class.',
      [f"The median is {_AGB['median']:.2f} in CBB ({_AGB['n']:,} ranked recruits 2009-16) and {_AGF['median']:.2f} in CFB ({_AGF['n']:,} top-400 recruits who reached the NFL).",
       f"CBB NBA rate at about the same rank: {100 * _AGB['bins'][0]['nba']:.0f}% under 17.9, {100 * _AGB['bins'][2]['nba']:.0f}% at 18.2-18.6 and {100 * _AGB['bins'][4]['nba']:.0f}% at 19.0+.",
       f"The CBB model input is old for the class (18+ on Oct 26 of the senior year), held out t = {_AGB['old']['t']:.2f}, {_AGB['old']['classes']}/8 classes.",
       f"Continuous age in its place is t = {_AGB['swap']['t']:.2f}, added on top t = {_AGB['add']['t']:.2f}, and a young flag t = {_AGB['young']['t']:.2f} (gate 2.0). None of them shipped.",
       f"CFB top-64 pick rate given an NFL entry: {100 * _AGF['bins'][1]['top64']:.0f}% at 18.0-18.4 and {100 * _AGF['bins'][4]['top64']:.0f}% at 19.2+. Draft slot t = {_AGF['pick']['t']:.2f}, {_AGF['pick']['classes']}.",
       f"CFB doesn't use it. It is short of the gate, and On3 lists an age for {_AGC['age']} of the top {_AGC['n']} in the latest class read.",
       'Birth dates come from On3\'s whole-year age, bounded tighter by each daily reading, plus FIBA youth rosters and pins.',
       'Cards show age against the class once the birth date is known to within 45 days. Hockey late birthdays and soccer birth month failed.'],
      'Recruit cards; CBB recruit model', ['CFB', 'CBB']),
    E('Class score', 'A class\'s commits\' FV points over the floor, summed. Top end and depth are its two parts.',
      [f"CFB sums xFV - 20 and CBB sums expected FV points. Top end is the best {_CSF['k']} commits in CFB and the best {_CSB['k']} in CBB, and depth is the rest.",
       f"Both parts were tested against results: program rating z, with the ratings before signing, a three-season baseline and program level as controls, held out and clustered by program. Reweightings were pre-registered: split, decay by rank in class, cap, star premium (points to a power), average + size, power x decay.",
       f"CFB, the four classes on a roster ({_CSF['roster4']['seasons'][0]}-{str(_CSF['roster4']['seasons'][1])[2:]}, n = {_CSF['roster4']['n']:,}): the sum beats no class score at t = {_CSF['roster4']['plain']['t']:.2f}, {_CSF['roster4']['plain']['up']} of {_CSF['roster4']['nSeasons']} seasons. A top-end point is worth {_CSF['roster4']['weights']['top'][0]:.4f} rating SD (SE {_CSF['roster4']['weights']['top'][1]:.4f}) and a depth point {_CSF['roster4']['weights']['depth'][0]:.4f} (SE {_CSF['roster4']['weights']['depth'][1]:.4f}), difference t = {_CSF['roster4']['weights']['t_diff']:.2f}.",
       f"Per standard deviation that is {_CSF['roster4']['weights']['per_sd'][0]:.2f} rating SD for top end and {_CSF['roster4']['weights']['per_sd'][1]:.2f} for depth. Raw correlation with the season's rating: {_CSF['roster4']['weights']['r'][0]:.2f} and {_CSF['roster4']['weights']['r'][1]:.2f}; after the controls {_CSF['roster4']['weights']['partial'][0]:.2f} and {_CSF['roster4']['weights']['partial'][1]:.2f}.",
       'No CFB reweighting beats the sum: ' + ', '.join(f"{k} t = {v['t']:.2f}" for k, v in _CSF['roster4']['forms'].items()) + f". One class at a time ({_CSF['classes'][0]}-{str(_CSF['classes'][1])[2:]}, n = {_CSF['n']:,}) the best is t = {max(v['t'] for v in _CSF['forms'].values()):.2f}. Quarterback and line points next to the sum: t = {_CSF['position']['t']:.2f}.",
       f"CBB, one class at a time ({_CSB['classes'][0]}-{str(_CSB['classes'][1])[2:]}, n = {_CSB['n']:,}): discounting depth looks better (power x decay t = {_CSB['forms']['power x decay']['t']:.2f}, {_CSB['forms']['power x decay']['up']} of {_CSB['nClasses']} classes) and a depth point reads {_CSB['weights']['depth'][0]:.4f}. That is roster turnover: a deep freshman class follows a thin returning roster.",
       f"With returning and transfer value held fixed (first season, n = {_CSB['roster']['all']['n']:,}), a CBB top-end point is worth {_CSB['roster']['all']['top'][0]:.4f} (SE {_CSB['roster']['all']['top'][1]:.4f}) and a depth point {_CSB['roster']['all']['depth'][0]:.4f} (SE {_CSB['roster']['all']['depth'][1]:.4f}), difference t = {_CSB['roster']['all']['t_diff']:.2f}, and every discount loses: " + ', '.join(f"{k} t = {v['t']:.2f}" for k, v in _CSB['bend']['first']['roster controls']['forms'].items()) + '.',
       f"CBB rating bends with the class total (diminishing returns, t = {_CSB['bend']['roster']['t']:.2f}), which changes no class's order. CFB does not bend (t = {_CSF['bend']['roster']['t']:.2f}).",
       f"The sum stays the class score in both sports, and top end and depth stay descriptive ranks. Lead: in NIL-era CFB seasons a top-end point is worth {_CSF['roster4']['nil']['weights']['top'][0]:.4f} and a depth point {_CSF['roster4']['nil']['weights']['depth'][0]:.4f} (t = {_CSF['roster4']['nil']['weights']['t_diff']:.2f}, n = {_CSF['roster4']['nil']['n']}); retest after the 2027 season.",
       f"Second pass, same test. Another value basis does not beat the one in use: CFB FV if on the board t = {_CSF['round4']['value']['roster']['forms']['FV if on the board']['t']:.2f} and year-3 xFV t = {_CSF['round4']['value']['roster']['forms']['year-3 xFV']['t']:.2f}; CBB headline FV t = {_CSB['round4']['value']['roster']['forms']['headline FV']['t']:.2f} and Y1 FV t = {_CSB['round4']['value']['roster']['forms']['Y1 FV']['t']:.2f}. Blends fail too.",
       f"Program development times the sum: CFB t = {_CSF['round4']['development']['forms']['sum x development']['t']:.2f}, CBB t = {_CSB['round4']['development']['forms']['sum x development']['t']:.2f}. Early and late commits weighted apart: t = {_CSF['round4']['timing']['forms']['early / late / undated']['t']:.2f} and {_CSB['round4']['timing']['forms']['early / late / undated']['t']:.2f}. CBB enrol rate of the three classes before: t = {_CSB['round4']['attrition']['forms']['sum x enrol rate']['t']:.2f}.",
       f"Incoming transfers next to the class, first season: CBB passes at t = {_CSB['round4']['portal']['forms']['class + transfers']['t']:.2f}, {_CSB['round4']['portal']['forms']['class + transfers']['up']} of {_CSB['round4']['portal']['folds']} classes (NIL era t = {_CSB['round4']['portal']['nil']['t']:.2f}). A unit of transfer value is worth {_CSB['round4']['portal']['coef'][1][0] / _CSB['round4']['portal']['coef'][0][0]:.1f} class points, and per standard deviation transfers move the rating {_CSB['round4']['portal']['coef'][1][0] * _CSB['round4']['portal']['sd'][1]:.2f} SD to the class's {_CSB['round4']['portal']['coef'][0][0] * _CSB['round4']['portal']['sd'][0]:.2f}. CFB incoming transfer production: t = {_CSF['round4']['portal']['forms']['class + transfers']['t']:.2f}.",
       'That is a net class (high school commits plus transfers), not a change to the high school score. Not testable on stored history: positional need against the returning roster, decommit risk, per-recruit Transfer% and Ret%.',
       f"History points are the live model's by composite rating and level (CFB) or consensus rank (CBB); against the live class scores r = {_CSF['map']['r']:.3f} and {_CSB['map']['r']:.3f}."],
      'Recruits tabs: class rankings; class rankings GFX', ['CFB', 'CBB']),
    E('Badges (players)', 'Bronze to platinum trait medals next to the name, each on one stat, regressed by volume.',
      ['The tiers are the 75th, 90th, 97th and 99th percentile of the position. CFB badges build archetypes.',
       'On the other boards a badge shows only if it predicts the sport\'s own outcome held out, beyond the value metric.',
       'They are display only, and no badge feeds FV or a projection. Volume and usage traits pass, and efficiency rates mostly fail.'],
      'Every board (medals by the name), player cards', ALLP),
    E('All-time FV', 'Each player\'s grade at his best season, listed by position.',
      ['CFB rebuilds every FBS season 2014-25, with the box-score era (2014-18) means recalibrated to NFL outcomes.',
       'The CFB outcome is NFL AV a season since the draft over a class horizon index h (mean 1 on the 2020-23 drafts), so years an old class spent out of the league don\'t count against it.',
       'The other boards read their past lists, and only grade-complete rows are used.'],
      'all-time FV tab on CFB, CBB, hockey, soccer and tennis prospect pages', ['CFB', 'CBB', 'Hockey', 'Soccer', 'Tennis']),
]})

# ---------------------------------------------------------------- player value
sections.append({'id': 'value', 'title': 'Player value metrics', 'entries': [
    E('College WAR', 'Wins over a replacement starter in a 12-game season.',
      ['WAR = snap share × (line + weight × quality) × .227. One point of margin a game is worth .0189 win% (928 FBS team seasons).',
       'The line is the margin a team loses when an average starter sits: QB 2.7, RB 1.7, EDGE 1.4, WR 1.35, CB 1.3, S 1.1, DT 1.0, LB 1.0.',
       'Quality comes from Stat+, badges and FV. The QB keeps 1.25 points per SD, and the rest goes to his offensive teammates by snaps.',
       'A replacement lineup wins .18 (2 of 12), and an average team\'s starters add up to 3.8 WAR.'],
      'CFB board, WAR leaders tab, team talent', ['CFB']),
    E('WAA', 'WAR minus snap share × line, which is wins over an average starter at the position.',
      ['It compares across positions, and a below-average starter is below 0.'],
      'CFB WAR leaders tab', ['CFB', 'NFL']),
    E('XV', 'WAR with quality taken from the parts of the stat line that track winning.',
      ['CFB: the PFN score plus position parts (QB cmp %, yds/att and INT rate, OL pressure rate, DT splash, CB yds/target).',
       'It is fit on 2024-25 team margin. Held out, team r is .88 compared to .86 for WAR quality, and win% r is .73 compared to .68.',
       'NFL: the same idea, fit to team margin a game. On missed games it is t = 4.9, compared to 2.1 for AV WAR.',
       'Next-season forecasts tie with WAR, so the projections and the game models stay on WAR.'],
      'CFB and NFL WAR leaders tabs (XV column)', ['CFB', 'NFL']),
    E('NFL WAR', 'Wins over replacement, .6 × AV WAR + .4 × XV, season to date.',
      ['AV WAR = (AV - replacement AV at the sub-position × snap share) × .091 wins per AV.',
       'The .091 comes from team wins on team AV (160 team seasons 2021-25, r .86). A replacement team wins 3 of 17.',
       'Defensive AV is rebuilt from pressures, stops and plays on the ball. Two-way players earn WAR on each side.'],
      'NFL WAR leaders, team WAR, rookies, standouts', ['NFL']),
    E('Stat+', 'A production index: 100 + 25 × z of the position\'s all-in-one score this season.',
      ['The source scores are PFN QB+, RB+, WR+, TE+, OLi, EDGE+, DT+, LB+, CB+ and SAF+, with K and P by percentile.',
       'z is against the snap-weighted position mean, FBS or FCS, so 125 is 1 SD above average.',
       'It is an FV production driver. Validity against NFL AV: TE .52, WR .50, QB .48, RB .48, EDGE .40, LB .40, DT .37.'],
      'CFB board, WAR leaders, true freshmen', ['CFB']),
    E('xNIL / yNIL / zNIL', 'xNIL is what a player is worth on the NIL market now, yNIL is his estimated pay entering the season, and zNIL = xNIL - yNIL.',
      ['xNIL = position price × on-field value (AV at FV, × playing time), shared within the P4 and G5 pools.',
       f'yNIL splits each program\'s budget by a preseason index. The budget is the school\'s reported one: {len(_NB["cfb"]["teams"])} P4 football programs (mean ${_nbm("cfb"):.1f}M) and {len(_NB["cbb"]["teams"])} high-major basketball programs (mean ${_nbm("cbb"):.1f}M).',
       f'Without a report it is assumed: $3M in the G5, $0.4M in the FCS, ${_NM["MM"] / 1e6:.1f}M for a mid-major and ${_NM["LM"] / 1e6:.2f}M for a low-major in basketball. The mid-major level is The Athletic\'s coach survey, and it puts the 90th and 75th percentile player outside the power conferences within 1% of the College Sports Commission\'s report. The survey\'s low-major level put the median player at three times the reported one, so it was not used.',
       f'Football position prices are moved, against the other positions, to what schools report paying: {_NPOS}. On3 prices those positions higher. The defensive line is scored with linebackers, since schools list edge players as either.',
       'The budget pays the whole roster. A provisionally graded football backup is paid 5% of the median graded player at his position on the team, and a kicker or punter 20% of the team\'s median graded player, rising 10% per FV point. Both shares were set on the College Sports Commission\'s pay percentiles. Their xNIL shares the group\'s own pay by worth, so a backup\'s or a specialist\'s zNIL is against his group\'s going rate.',
       f'A reported deal ({len(_ND)} on file, read from headlines every three hours and held back unless a national outlet or two outlets carry it) moves the player half way from the model\'s number to the report: his yNIL when the deal is for this season, his xNIL when it was reported in the last year. It also enters the price fit, so a position\'s price follows the reports between On3\'s repricings. On3 moved toward each of the three reports it trailed.',
       f'A budget list from an earlier season is carried forward at the market\'s growth ({(_NB["cfb"].get("growth", 1) - 1) * 100:.0f}% a year).',
       'It isn\'t fit to On3 valuations, since those only move +18% per 10 FV. zNIL growth is 20% of each coach score.',
       'Checked against the College Sports Commission\'s pay percentiles by position, On3 valuations and reported deals.',
       'FCS players at an FBS-starter FV are priced at 40% of the FBS rate. CBB xNIL is minutes share × (BPM + 3) at the school\'s price.'],
      'CFB board, team talent, team builder, fv to xNIL charts; CBB recruits', ['CFB', 'CBB']),
    E('NIL agencies', 'Agencies ranked by tendency scores built from their clients, with the talent they represent.',
      ['Each client is one row in a ledger, named by the agency\'s own client page, an announcement or a report, with the source and its date. Family means a relative handles his deals and None means a source says he has no agent. A player no source names is left out.',
       'Each score is a plus score, 100 + 25 × (s - the mean agency) / SD, so 100 is the average agency. s is the mean over the agency\'s clients pulled toward the mean of every represented client: (sum + k × mean) / (n + k), with k the spread inside agencies over the spread between them (8 or more until eight agencies have three or more clients).',
       'Deal+ uses each college client\'s -zNIL over the sport\'s zNIL SD. Above 100 the agency gets its clients paid more than they are worth. Breakout+ uses FV minus the mean FV of board players with the same ARK stars and class. Above 100 its clients play above their high school grade.',
       'A score is shown only where it held up on a split-half test: each agency\'s clients are split in two at random and the two half means are correlated across agencies, against 300 shuffles of the clients between agencies, and it has to clear p < .05 both weighted by clients and unweighted. ' + _AGT,
       'Agency+ is the composite. Each part is z-scored across agencies and averaged: Deal as the shrunk edge, sum(v - mean) / (n + k), times the clients when it is above zero, so the same edge counts for more the more players it covers and a big roster is not charged per player for a low one, and sent, the drafted clients the agency had before the draft process (from 2027 on). Breakout+ is left out because it measures how good the clients turned out, not what the agency did for them. Deal only counts in a sport where it passed its test, so basketball has no Agency+ until its first tracked draft. ' + _AGCOMP,
       'Drafted counts clients picked in the NFL or NBA draft who signed with the agency before the draft process began (declaring, or Dec 1 for football and Mar 15 for basketball). It does not count an agency a player signed with to go pro. It counts from the 2027 drafts on, every pick recorded on draft day. First-round picks from 2022-26 were searched too, but the sources on who had a player before he declared are too thin to judge an agency on, so they are kept on file and not counted. Pro% is drafted over drafted plus the college clients on file now.',
       'Recruits count toward talent (FV, ARK stars) only. Low-confidence rows count toward talent only.',
       f'On file now: {len(_AGY["cfb"]["clients"])} football and {len(_AGY["cbb"]["clients"])} basketball players and recruits, {len(_AGY["cfb"]["agencies"])} and {len(_AGY["cbb"]["agencies"])} agencies.'],
      'CFB and CBB agencies tabs, player and recruit cards', ['CFB', 'CBB']),
    E('Season AV (college)', 'A college player\'s on-field value for a season: snap share × position weight × quality.',
      ['Quality = Stat+ z + .5 badge z + .25 FV z. Team R² against 2026 SRS is .63, compared to .44 for summed FV value.',
       'It is used for the cost of college injuries and for team value. NFL value stays on AV at FV.'],
      'CFB team talent (Season AV), fv to war chart', ['CFB']),
    E('XPM', 'XPM (Cross Plus-Minus) is an NBA impact metric, .5 databallr DPM + .5 Basketball-Reference BPM, in points per 100 possessions over an average player, as played.',
      ['It is the headline XPM on every NBA board. O-XPM and D-XPM are the same blend for each side.',
       'It includes BPM\'s team adjustment. Every player on a team moves by one amount on each side, so that minutes-weighted O-XPM × 5 = ORtg - league and D-XPM × 5 = league - DRtg.',
       f'Same-season team net R² is {_RX["rXPM (team-adjusted)"]["describe"]:.3f} (the box blend before the adjustment {_RX["XPM box blend"]["describe"]:.3f}, BPM {_RX["BPM"]["describe"]:.3f}). Next season it is {_RX["rXPM (team-adjusted)"]["predict"]:.3f} (box blend {_RX["XPM box blend"]["predict"]:.3f}, BPM {_RX["BPM"]["predict"]:.3f}).',
       'The box blend before the adjustment feeds pXPM, the game models (which shrink it themselves) and the CBB board target. A player with no DPM row uses BPM alone (*).',
       'The XPM and rookie boards default to qualified players, 1,000 MP per 82 team games. For qualified rookies 2010-23, XPM orders next-three-season VORX at .607 (VORX .604), and .330 for all rookies.'],
      'NBA VORX/XPM leaders, rookies, team pages, ARKLIST', ['NBA']),
    E('pXPM (predictive XPM)', 'Projected XPM for next season: XPM over three seasons by minutes, shrunk toward a role mean and aged. On the depth charts and backup watch it shrinks toward replacement.',
      ['Boards: (k × role mean + MP × XPM + w1 × MP-1 × XPM-1 + w2 × MP-2 × XPM-2) / (k + MP + w1 MP-1 + w2 MP-2) + the aging curve to next season.',
       f'k {_PX["ship"][0]} MP, w1 {_PX["ship"][1]}, w2 {_PX["ship"][2]}, role mean = {-2 + _PX["ship"][4]:g} + {_PX["ship"][5] * .5:g} ln(1 + MP82 / 100). Aging is the next-season change in XPM by age, fit on earlier seasons only.',
       f'Next-season XPM 2011-26, leaving one season out: RMSE {_PX["loo"]["player"]:.3f}, compared to {_PX["base"]["pXPM (live)"]["player"]:.3f} for a one-dial k 600 shrink and {_PX["base"]["rXPM"]["player"]:.2f} raw (t = {_PX["playerTest"]["t"]}, {_PX["playerTest"]["better"]}/{_PX["playerTest"]["of"]} seasons).',
       f'Next-season team net rating, nine pairs, held out: R² {_PX["loo"]["team"]:.3f}, against rXPM {_PX["base"]["rXPM"]["team"]:.3f}, BPM {_PX["base"]["BPM"]["team"]:.3f}, DPM {_PX["base"]["DPM"]["team"]:.3f} and the k 600 shrink {_PX["base"]["pXPM (live)"]["team"]:.3f}.',
       'Depth chart and backup watch: XPM over three seasons (minutes weighted 1, .5, .25) × M / (M + 500) + replacement (-1.4) × 500 / (M + 500).'],
      'NBA VORX/XPM leaders (pXPM chip), rookies, depth chart, backup watch', ['NBA']),
    E('VORX', 'VORX (Value Over Replacement XPM) is NBA wins over replacement: .030 × (XPM + 1.4) × MP / 48.',
      ['Replacement is -1.4 XPM. Both constants are fit to team wins (480 team seasons 2011-26). It is the default sort on the XPM and rookie boards.',
       f'Team W% from minutes-weighted value, 2011-26: same-season R² is {_VX["metrics"]["rXPM"]["same"]["r2"]:.3f} on XPM, compared to {_VX["metrics"]["XPM box blend"]["same"]["r2"]:.3f} on the box blend before the team adjustment (t = {_VX["test"]["same"]["t"]}, {_VX["test"]["same"]["better"]}/{_VX["test"]["same"]["of"]} seasons). Next season it is {_VX["metrics"]["rXPM"]["next"]["r2"]:.3f} compared to {_VX["metrics"]["XPM box blend"]["next"]["r2"]:.3f} (t = {_VX["test"]["next"]["t"]}).',
       'For rookies 2010-23, held out, VORX orders next-three-season VORX best (Spearman .398; pXPM .395, aXPM .379, XPM .330).',
       'For next-three-season XPM, the rookie 3Y orders it best (.481; aXPM .413, XPM .417, VORX .351).'],
      'NBA VORX/XPM leaders, projections, contract value', ['NBA']),
    E('1Y / 3Y XPM', 'Projected XPM next season (given he plays) and over the next three (× the chance he plays in them).',
      ['It is built from XPM (proj), age, projected minutes, a hinge above +3 and the two seasons before, with coefficients by the share of the season played.',
       'Given he plays, it is fit on seasons with minutes, weighted by them. Held out 2012-23 at 1,000+ minutes, 3Y RMSE is 1.13 and 1Y is 1.14.',
       '3Y = stay × XPM given he plays + (1 - stay) × -2. Stay is the chance he plays in the next three seasons (XPM, age, minutes, games).',
       _NBAEX, 'It is display only.'],
      'NBA VORX/XPM leaders (3Y chip), projections', ['NBA']),
    E('XPM (proj)', 'Season-to-date XPM blended with a preseason prior by minutes.',
      ['prior + (XPM - prior) × MP / (k + MP), with k 509 for veterans and 809 for newcomers (7,269 player seasons 2012-26).',
       'The 80% range covers .806 / .799 held out. It is display only.'],
      'NBA contract value, proj chip', ['NBA']),
    E('Contract value (surplus)', 'Minimum salary + projected VORX × the market price of a win, minus salary, for every year left on the deal.',
      ['The price of a win is payroll above the minimum divided by the league\'s projected VORX, refit on every update, rising 7% a year (an assumption).',
       'A player option counts only when it pays the player, and a team option only when it pays the team.'],
      'NBA contract value tab', ['NBA']),
    E('xAAV', 'The AAV a player would sign for as a free agent now, as a share of the cap from position, age and his last full season.',
      ['It is fit on real signings and held out a signing year at a time against the mean by position × age. The forms were pre-registered, and the live form is the lowest held-out MAE whose top end is calibrated (players priced at 7%+ of the cap signed for 85-115% of it). It models the square root of the cap share, smeared back, and is clipped to the league minimum and maximum.',
       'NHL: 3,241 CapWages deals 2010-26 (standard, 35+ and two-way, no ELCs or extensions), on WAR, pWAR, 3Y, points and TOI a game, games and age, by F/D/G. MAE is .83% of the cap compared to 1.70 (t = -40, 17/17 seasons, forward 11/11). Points and TOI alone tie it (t = -1.4), so the market pays for points.',
       'NFL: 12,192 OverTheCap veteran contracts 2014-26 (3+ years after the draft), on WAR the last two seasons, snaps, games and age, by position. MAE is .86% compared to 1.50 (t = -52, 13/13, forward 9/9). WAR adds over snaps alone (t = -18). The ceiling is the record 24.5% (Burrow 2023).',
       'NBA: 1,334 Basketball-Reference offseason signings 2011-26 (free agent, multi-year or plain contracts, with next season\'s salary on the signing team), on XPM the last two seasons, VORX, minutes, points and minutes a game, games, age and years in the league. MAE is 2.60% compared to 5.04 (t = -19, 16/16, forward 11/11). XPM and VORX add over points and minutes alone (t = -6, 14/16). The max is 25/30/35% by years in the league, and the 2026-27 cap is $165M (projected).',
       'Soccer isn\'t built. There is no public wage data I can reach (Capology blocks it), and xMV is the transfer-market equivalent.'],
      'NBA, NFL, NHL contract value tabs', ['NBA', 'NFL', 'NHL']),
    E('xXPM', 'Projected XPM this season, the board\'s projection for every player, freshmen and transfers included.',
      [re.sub(r'(?<![\d.])0\.(\d)', r'.\1', _t) for _t in ['A ridge on last season, recruiting, age and size, with rXPM (CBB) as the target. Returners also take pXPM (CBB), board form. In season it blends in XPM to date.',
       'Team context: returning teammates\' VORX, teammates\' recruiting (top 8, -ln rank), WAA and transferring up or down.',
       f'It was xBPM, the same ridge with BPM as the target and no pXPM. Walk-forward 2012-13 to 2025-26, next-season team R² over the whole roster goes from {_XX["whole roster"]["xBPM (both groups)"]["teamR2"]:.4f} to {_XX["whole roster"]["xXPM (rXPM target + pXPM board)"]["teamR2"]:.4f} ({_XX["whole roster"]["xXPM (rXPM target + pXPM board)"]["vs xBPM (both groups)"]["pairsBetter"]}, t = {_XX["whole roster"]["xXPM (rXPM target + pXPM board)"]["vs xBPM (both groups)"]["t"]}).',
       f'For returners, pXPM added moves it from {_XX["xBPM"]["teamR2"]:.4f} to {_XX["xBPM + pXPM board"]["teamR2"]:.4f} (t = {_XX["xBPM + pXPM board"]["t"]}). The box form of pXPM alone is t = {_XX["xBPM + pXPM core"]["t"]}, and the rXPM target alone is t = {_XX["rXPM target"]["t"]}. For newcomers the target swap is a tie (t = {_XX["newcomers"]["scored on xpm_now"]["t_rXPM_target_better"]} scored on XPM).',
       'The fit rows read pXPM point in time, from a refit that walks forward a season at a time.',
       'As xBPM, forward 2020-26, RMSE went from 2.558 to 2.462 for returners (t = 18) and from 3.439 to 3.229 for newcomers (t = 14) with team context. It is not an FV input.']],
      'CBB board hover, true freshmen, standouts, draft board, team talent, team builder', ['CBB']),
    E('rXPM (CBB)', 'XPM for a college season: Barttorvik BPM\'s split of credit inside the team, on team totals that track wins.',
      [re.sub(r'(?<![\d.])0\.(\d)', r'.\1', _t) for _t in ['For each side, rXPM = BPM + the team\'s minutes-weighted mean of (GBPM - BPM). GBPM is the minutes-weighted mean of his games\' BPM (Barttorvik).',
       'Team totals equal GBPM\'s, and the gaps between teammates equal BPM\'s.',
       f'Team totals, 2007-08 to 2025-26: wins above bubble a game R² is {_CR["team"]["wab_g"]["h"]:.3f} compared to {_CR["team"]["wab_g"]["bpm"]:.3f} for BPM (t = {_CR["team"]["wab_g"]["vsBPM"]["t"]:.1f}, {_CR["team"]["wab_g"]["vsBPM"]["seasonsBetter"]}/19), and win% is {_CR["team"]["wp"]["h"]:.3f} compared to {_CR["team"]["wp"]["bpm"]:.3f} ({_CR["team"]["wp"]["vsBPM"]["seasonsBetter"]}/19). On adjusted margin, which is BPM\'s own anchor, it is {_CR["team"]["em"]["h"]:.4f} compared to {_CR["team"]["em"]["bpm"]:.4f}.',
       'The split inside the team is tested on who sat out: game margin, adjusted for opponent and site, minus the team\'s season mean, on the minutes-weighted rating of the players who played, with ratings from the other games.',
       f'Against GBPM: all rotation players t = {_CR["sat"]["A"]["t"]} ({_CR["sat"]["A"]["seasonsBetter"]}/19), starters t = {_CR["sat"]["R1"]["t"]} ({_CR["sat"]["R1"]["seasonsBetter"]}/19), split halves t = {_CR["sat"]["R2b"]["t"]} ({_CR["sat"]["R2b"]["seasonsBetter"]}/19). Against BPM it is identical.',
       f'Next season, which isn\'t its job, team R² is {_CR["next"]["h"]["teamR2"]:.3f}, GBPM {_CR["next"]["gbpm"]["teamR2"]:.3f} (t = {_CR["nextVsGBPM"]["t"]}) and BPM {_CR["next"]["bpm"]["teamR2"]:.3f}. pXPM is the projection.',
       f'SD {_CR["sd"]["h"]:.2f} (BPM {_CR["sd"]["bpm"]:.2f}), r with BPM {_CR["rBPM"]:.3f}, mean gap {_CR["absBPM"]:.2f}.',
       'Failed held out: O/D blends of BPM and GBPM, college box weights fit to who sat out, wins or capped-margin anchors, and GBPM moved toward raw net rating (a schedule artifact).',
       f'As a model input in place of BPM it failed held out: the ten award voter models (t = {min(v["t"] for v in _SW["awards"].values())} to {max(v["t"] for v in _SW["awards"].values())}), Transfer% (t = {_SW["market"]["rXPM for BPM"]["move_t"]}), Ret% (t = {_SW["declare"]["rXPM for BPM"]["t"]}) and the school development outcome (rolling gain {_SW["school_dev"]["BPM"]["bpm"]["rolling"]["mseGainPct"]:.2f}% on BPM, {_SW["school_dev"]["rXPM"]["bpm"]["rolling"]["mseGainPct"]:.2f}% on rXPM). Those stay on BPM. Award conviction and the stats shown beside the awards use XPM.']],
      'CBB board (XPM), VORX/XPM leaders, stats, portal, award conviction, all-time list', ['CBB']),
    E('pXPM (CBB)', 'Projected XPM next season on offense and defense, from three seasons of box lines plus team and recruit ratings.',
      [re.sub(r'(?<![\d.])0\.(\d)', r'.\1', _t) for _t in ['For each side: (K × mean of sub-200-minute players + minutes × BPM, with the last three seasons weighted 1 / w1 / w2) / (K + weighted minutes),',
       'then a fit on next-season BPM from that history, ln minutes, class, and twelve box rates z-scored within the season × minutes / (minutes + 200)',
       '(steal, block, OREB, DREB, assist, turnover, FT rate, 3PA/100, rim share, usage, TS, height), with a ridge of 10 on the rates.',
       f'O: w .35 / .2, K 200. D: w .6 / .4, K 100. Fit on next-season minutes, 2008-09 to 2025-26 pairs (in the research form below, D took 25% GBPM).',
       f'Walk-forward 2012-13 to 2025-26: next-season team adjEM R² is {_CX["pxpm"]["teamR2"]:.3f} compared to {_CX["pxpm"]["bpm"]["teamR2"]:.3f} for BPM ({_CX["pxpm"]["vsBPM"]["pairsBetter"]}/14, t = {_CX["pxpm"]["vsBPM"]["t"]:.1f}). Player r is {_CX["pxpm"]["playerR"]:.3f} compared to {_CX["pxpm"]["bpm"]["playerR"]:.3f}, and RMSE {_CX["pxpm"]["playerRMSE"]:.2f} compared to {_CX["pxpm"]["bpm"]["playerRMSE"]:.2f}.',
       f'xXPM, the board\'s projection, takes the board form as an input next to recruiting and team context: for returners, team R² is {_XX["rXPM target + pXPM board"]["teamR2"]:.3f} and player r {_XX["rXPM target + pXPM board"]["playerR_vsBPM"]:.3f}.',
       f'In the roster prior, in place of last-season BPM, next-season team R² goes from {_CX["roster"]["teamR2"][0]:.3f} to {_CX["roster"]["teamR2"][1]:.3f} ({_CX["roster"]["pairsBetter"]}/14, t = {_CX["roster"]["t"]}). Game margin MAE goes from {_CX["game"]["tuneMae"][0]:.4f} to {_CX["game"]["tuneMae"][1]:.4f} in 2016-20 (t = {_CX["game"]["tuneT"]}) and from {_CX["game"]["heldMae"][0]:.4f} to {_CX["game"]["heldMae"][1]:.4f} in 2021-26 (t = {_CX["game"]["heldT"]}). xBPM fails there (t = {_CX["roster"]["xbpmSwap"]["t"]}).',
       f'As an FV returner driver, it adds +{_CX["fv"]["add"]["md5_gain"]:.2f}% out of sample (t = {_CX["fv"]["add"]["md5_t"]}, 5/5), and in place of 3-season BPM t = {_CX["fv"]["forBpm3"]["md5"]["t"]}. Nested pseudo-R² goes from {_CX["fv"]["gate"]["nestedR2"][0]:.3f} to {_CX["fv"]["gate"]["nestedR2"][1]:.3f}, RPS from {_CX["fv"]["gate"]["rps"][0]:.4f} to {_CX["fv"]["gate"]["rps"][1]:.4f}, and the 2017-19 top 50 from {_CX["fv"]["gate"]["top50_2017_19"][0]:.1f} to {_CX["fv"]["gate"]["top50_2017_19"][1]:.1f}.',
       f'In NBA mock conviction, in place of 3-season BPM, it is t = {_CX["mock"]["t"]} ({_CX["mock"]["drafts"]}/15 drafts), so 3-season BPM stays.',
       f'The board form adds team context (5 × the minutes-weighted mean side BPM of his team / 10; O {_CXB["ctx"][0]:.2f}, D {_CXB["ctx"][1]:.2f}) and recruit rating / 100 by class (Fr O {_CXB["rec_fr"][0]:.2f} D {_CXB["rec_fr"][1]:.2f}, So {_CXB["rec_so"][0]:.2f} / {_CXB["rec_so"][1]:.2f}, Jr+ {_CXB["rec_up"][0]:.2f} / {_CXB["rec_up"][1]:.2f}).',
       f'Walk-forward, team R² goes from {_CX2["v1"]["teamR2"]:.3f} to {_CX2["teamR2"]:.3f} ({_CX2["vsV1"]["pairsBetter"]}/14, t = {_CX2["vsV1"]["t"]}), against {_CX2["bpm"]["teamR2"]:.3f} for BPM ({_CX2["vsBPM"]["pairsBetter"]}/14, t = {_CX2["vsBPM"]["t"]:.1f}). Player r is {_CX2["playerR"]:.3f} and RMSE {_CX2["playerRMSE"]:.2f}.',
       f'On their own, team context is t = {_CX2["blocks"]["F3"]["t"]} and recruit rating t = {_CX2["blocks"]["F2"]["t"]}. Late-season form, age, role and freshman height, minutes share and its change, and game BPM consistency failed (t = {min(_CX2["blocks"][k]["t"] for k in ("F4", "F5", "F6", "F7"))} to {_CX2["blocks"]["F1"]["t"]} alone, and nothing once the two are in).',
       f'The board form in the roster prior goes from {_CX2["roster"]["teamR2"][0]:.3f} to {_CX2["roster"]["teamR2"][1]:.3f} ({_CX2["roster"]["pairsBetter"]}/14, t = {_CX2["roster"]["t"]}). As the FV driver in place of the box form it is t = {_CX2["fvSwap"]["md5"]["t"]}.',
       f'Through the game model, the board form moves held-out margin MAE (2021-26) from {_CX3["game"]["heldMae"][0]:.4f} to {_CX3["game"]["heldMae"][1]:.4f} (t = {_CX3["game"]["heldT"]}, worse in {_CX3["gameSeasonsWorse"]}/{_CX3["gameSeasons"]} seasons), and {_CX3["retune"]["core"]["held"]:.4f} against {_CX3["retune"]["full"]["held"]:.4f} with the prior weight retuned. In FV, nested R² goes from {_CX3["fv"]["nestedR2"][0]:.3f} to {_CX3["fv"]["nestedR2"][1]:.3f}, but the top-300 correlation with outcome on the 2017-19 boards goes from {_CX3["fv"]["top300Corr2017_19"][0]:.3f} to {_CX3["fv"]["top300Corr2017_19"][1]:.3f} and RPS from {_CX3["fv"]["rps"][0]:.4f} to {_CX3["fv"]["rps"][1]:.4f}. FV, the roster prior and the game model stay on the box form.',
       f'The board form also goes into the next-season value column (Next) in place of last-season BPM in the roster row: RMSE goes from {_SW["next"]["T0"]["base (BPM row, BPM value)"]["rmse"]:.2f} to {_SW["next"]["T0"]["pXPM board row"]["rmse"]:.2f} (t = {_SW["next"]["T0"]["pXPM board row"]["t"]}, {_SW["next"]["T0"]["pXPM board row"]["seasons"]} seasons), and in season it replaces 3-season BPM at every share of the season played (t = {min(v["t"] for v in _SW["next_inseason"].values())} to {max(v["t"] for v in _SW["next_inseason"].values())}).',
       f'Added to next up odds as the gap between pXPM and the shrunk value, the Brier score goes from {_SW["breakout"]["BPM definition"]["px2 added"]["base"]:.4f} to {_SW["breakout"]["BPM definition"]["px2 added"]["cand"]:.4f} (t = {_SW["breakout"]["BPM definition"]["px2 added"]["t"]}, {_SW["breakout"]["BPM definition"]["px2 added"]["won"]}/16).',
       f'In Transfer%, in place of BPM, log loss goes from {_SW["market"]["base"]["move_ll"]:.4f} to {_SW["market"]["pXPM board for BPM"]["move_ll"]:.4f} and AUC from {_SW["market"]["base"]["move_auc"]:.3f} to {_SW["market"]["pXPM board for BPM"]["move_auc"]:.3f} (t = {_SW["market"]["pXPM board for BPM"]["move_t"]}). In the landing spot model the right school is in the top 10 {100 * _SW["market"]["pXPM board for BPM"]["land_top10"]:.1f}% of the time, up from {100 * _SW["market"]["base"]["land_top10"]:.1f}% (t = {_SW["market"]["pXPM board for BPM"]["land_t"]}).',
       f'In the depth chart and backup watch grade it replaces last season\'s BPM (t = {min(v["t"] for v in _SW["backup"].values())} to {max(v["t"] for v in _SW["backup"].values())}, 12/12 seasons at every share of the season).',
       f'It failed in Ret% (t = {_SW["declare"]["pXPM for BPM"]["t"]}), and in NBA mock conviction (t = {_SW["mock"]["pXPM board for 3-season BPM"]["t"]}, {_SW["mock"]["pXPM board for 3-season BPM"]["drafts"]} drafts). The same gap added to NBA next up odds is t = {_SW["nba_breakout"]["pXPM gap added"]["t"]}, so it isn\'t there.',
       'The descriptive counterpart is rXPM (CBB).']],
      'CBB pXPM leaders, portal, board hover; box form: FV (returners), roster prior / game model', ['CBB']),
    E('CBB VORX / WAA', 'Wins over a replacement or an average D-I player.',
      [re.sub(r'(?<![\d.])0\.(\d)', r'.\1', _t) for _t in [f'VORX = (sXPM + 1.4) × minutes / 40 × 68 possessions a 40 / 100 × {_CW["wfit"]["wpp"]:.4f} wins a point. WAA uses sXPM alone.',
       'XPM is rXPM (CBB), and sXPM = (XPM × min + 100 × season mean) / (min + 100).',
       f'Replacement is 1.4 below average, the 9th man\'s sXPM in 2025-26. Wins a point is fit on {_CW["wfit"]["teams"]:,} team seasons 2017-26:',
       f'wins = {_CW["wfit"]["a"]:.2f} × games + team VORX (r {_CW["wfit"]["r"]:.2f}). It is season only, so no earlier season enters a season\'s VORX.',
       'GBPM over season BPM moved held-out team win% R² from .633 to .658, 15 of 15 seasons. The shrink cut half-B GBPM MSE from 16.2 to 11.4',
       '(10 of 10) and held-out team wins RMSE from 3.348 to 3.331 (14 of 14). rXPM then replaced GBPM, with the same team totals and BPM\'s split inside the team.',
       'The textbook slope (.0347 at a margin sd of 11.5) overstates it, since schedules pair strong teams with strong teams and win odds flatten at the ends.',
       'In the FV test, VORX, WAA, career VORX and 5/4/3 VORX all fail.',
       'It is the same value over replacement as NBA VORX, on the college scale. It was called WAR here before.']],
      'CBB VORX/XPM leaders, stats, portal, returning', ['CBB']),
    E('Stat+ (CBB)', 'XPM against the position, 100 + 25 × z.',
      [re.sub(r'(?<![\d.])0\.(\d)', r'.\1', _t) for _t in [f'z = (XPM - position mean) / position sd. The tabs use last season\'s norms (G {_CW["norms"]["G"][0]:.2f} / {_CW["norms"]["G"][1]:.2f}, F {_CW["norms"]["F"][0]:.2f} / {_CW["norms"]["F"][1]:.2f}, C {_CW["norms"]["C"][0]:.2f} / {_CW["norms"]["C"][1]:.2f}),',
       'then this season\'s own once 40 players at a position qualify. The FV driver is on BPM, with norms G .10 / 3.85, F .50 / 4.05, C .52 / 4.31 (2008-16).',
       'As an FV driver it passes all three fold rules (t = 2.9-3.5, 4-5/5), and it held in 2017-19 (+.17) and forward in 2020-23 (+.26).']],
      'CBB stats, WAR leaders, portal; FV inputs', ['CBB']),
    E('Game Score', 'Hollinger\'s single-game value.',
      ['PTS + .4 FGM - .7 FGA - .4 (FTA - FTM) + .7 ORB + .3 DRB + STL + .7 AST + .7 BLK - .4 PF - TOV.',
       'Every FV and xXPM test failed (a game, a 40, best game, 20+ games).'],
      'CBB top performers', ['CBB']),
    E('Standouts (CBB)', 'First and second-year players playing above their preseason projection.',
      ['xXPM up = live xXPM - preseason xXPM (minutes-blended). The tab also shows XPM over x, minutes, usage and FV gains.',
       'The last season view puts second-years against their freshman line (VORX, XPM, minutes and usage gains).',
       'In the FV tests, VORX gain, minutes gain, usage gain and BPM × (1 - minutes share) all fail. Low-minute BPM passes the folds, but not at the top of the board.'],
      'CBB standouts tab', ['CBB']),
    E('Returning / talent (CBB)', 'Team tables for how much of last season\'s minutes and VORX is back, and roster grades.',
      ['Ret Min% is the share of last season\'s minutes still on the roster (Barttorvik ids). In VORX is the VORX of incoming transfers.',
       'Talent is the mean FV of the top 8. xNBA is the sum of NBA%. TvE is talent rank minus ARK rank.',
       'In the FV tests, vacated minutes (opportunity), returning teammates\' VORX and teammates\' recruiting fail. The last two pass for xXPM.'],
      'CBB returning, team talent', ['CBB']),
    E('Peak XPM (CBB scale)', 'The CBB FV target, the mean of a career\'s best three NBA XPM seasons, each shrunk toward -2 by 500 minutes.',
      ['Each FV band starts at the XPM that as many careers reached as reached the matching NBA role. See the CBB chart.'],
      'CBB fv model tab (fv conversions)', ['CBB']),
    E('NHL WAR', 'Descriptive wins over replacement, at goal value.',
      ['5v5 on-ice xG against teammates, PP xG / 5, PK / 4, finishing (goals - ixG), penalties, and a share of the team\'s leftover xG.',
       'Goalies get GSAx at full credit. It sums to team goal differential (R² .991).',
       'Replacement is the level of players outside each team\'s top 13 F, 7 D and 2 G.'],
      'NHL WAR leaders, rookies', ['NHL']),
    E('pWAR / HPM', 'Projected WAR, and projected goals per 60 over an average player.',
      ['HPM is Marcel-weighted (1 / .5 / .25) shrunk rates, with each component weighted by how well it carries to the next season.',
       'pWAR = (HPM - replacement) × TOI / 60 / goals per win. Leave one season out, R² is .37 compared to .26 before (t = 4.24, 15/17 seasons).',
       'Goalie GSAx barely repeats (weight .21), so goalie pWAR is about 0.4 while goalie WAR runs about 7.'],
      'NHL WAR leaders, backup watch, rookies; hockey prospect outcome (skaters)', ['NHL', 'Hockey']),
    E('GSAx', 'Goals saved above expected (MoneyPuck xG).',
      ['The goalie tab shows GSAx a game, shrunk toward a new goalie\'s level. It feeds the NHL totals model.'],
      'NHL goalies tab, NHL WAR', ['NHL']),
    E('NHLe', 'NHL points over a full season, at a league\'s translation factor.',
      ['The factors are fit on every pick\'s career since 2008 from league pairs, with a year of age development taken out.',
       'They are shrunk toward the published factor by link count. CHL leagues sit around .10-.12, and the NCAA around .21.'],
      'Hockey prospects board, first-year tab', ['Hockey']),
    E('GAR (soccer, senior)', 'Goals above replacement, on one scale across leagues.',
      ['Shrunk per-90 rates (on-ice, npxG, xA, xGBuildup, keeper saves), weighted to next-season team goal difference.',
       'Replacement for each position is the regulars (900+ minutes) on the bottom three sides by goal difference of each finished league-season, pooled, less sides that collapsed: GK -.14, D -.09, M -.05, F .00 a match. League strength counts. Held out R² is .61.',
       'An average side totals about 26 GAR a season. 1Y / 3Y is fit on this line. Backup watch and the injury term of the game model grade on the earlier line (players under 900 minutes), in fit and live alike.',
       'PAR = GAR × points per goal of difference (.626).'],
      'Soccer player value, rookies, backup watch', ['Soccer']),
    E('tGAR (soccer prospects)', 'Team-share goals above replacement: minutes / 90 × (club rating - replacement) / 11.',
      ['Club rating is goals a match against an average big-five club. Replacement is -2.5, a bottom side in Scotland, Greece or Denmark.',
       'The outcome is the mean of the best three tGAR seasons at ages 22-26. It is a different scale from the senior GAR above, about 4-5× larger.'],
      'Soccer prospects board, first-year tab', ['Soccer']),
    E('xMV', 'Estimated market value in EUR millions, with no market input.',
      ['A ridge on log Transfermarkt value from GAR now and in the past two seasons, minutes, age, position, league and club.',
       'Held out R² runs from .68 in October to .78 in July. The gap to TM forecasts TM\'s next move (slope .23, 12/12 seasons).'],
      'Soccer player value, rookies', ['Soccer']),
    E('Elo / Elo+ (tennis)', 'Elo on every pro match since 1991 at every level, and Elo+ against players the same age.',
      ['K = 250 / (matches + 5)^0.4, Slams ×1.1, starting at 1500. Elo+ = 100 + 25 per SD against same-age players with 20+ matches.'],
      'Tennis prospects board, tennis ARK Ranking', ['Tennis']),
    E('RWA (CS2)', 'The round win % a Counter-Strike player adds per round, opponent-adjusted, where 0 is an average tier-1 starter.',
      ['The box part is the team\'s round share on its five players\' per-round stat lines (kills, deaths, assists, ADR, KAST, openings, trades,',
       'multi-kills, clutches, headshots, damage taken). The plus-minus part is half the round share the box misses, split across the five.',
       'There is no utility measure, since bo3.gg has no flash or utility damage data. Utility $ bought failed (t = -2.5), and accuracy hurt.',
       'Tier lift: +0.5 × the share of last year\'s rounds at S/A-tier events, since low-tier pools link to the top through few maps.',
       'Opponents are credited ×1.0, with a half-life of 180 days and 25 rounds of shrink. Held out R² is .131, compared to .120 before and .108 for K-D.'],
      'Counter-Strike players, prospects, player model', ['CS2']),
    E('SPW+ / RPW+ / xHold / xBreak', 'Serve and return points won over an average top-100 player, opponent-adjusted.',
      ['In percentage points, on hard court. xHold and xBreak are games held or broken against an average top-100 opponent, through the game chain.'],
      'Tennis serve + return tabs', ['Tennis']),
    E('SV (NFL QBs)', 'SV (season value) is this season\'s points a game over a replacement QB (-0.12 EPA a play), opponent-adjusted. Proj is the game model\'s QB term.',
      ['SV takes each dropback and QB run, minus how much EPA a play the defense allowed over the league\'s (in its other games, shrunk with 300 plays): '
       'sum(aEPA + 0.12) / games with 10+ plays. Split-half r is .512 raw and .528 adjusted (QB-seasons with 250+ plays, 2021-26). Wind, cold and rain added nothing.',
       'Proj is weighted career EPA/play shrunk toward replacement with %d pseudo-plays (fit), × the game model\'s QB coefficient. '
       'SV in the game model, as a swap or as an extra term, failed held out 2021-25 (margin MAE from 10.010 to 10.034 / 10.027).'
       % round(json.load(open(os.path.join(ROOT, 'data', 'nfl_games_fit.json')))['params']['qb_n0'])],
      'NFL QBs tab', ['NFL']),
    E('SV (NFL skill players, defenders)', 'SV (season value) is this season\'s points a game over replacement. Skill players are scored on EPA a run or target, and defenders on credited EPA on plays with negative EPA.',
      ['Skill (RB, WR, TE): EPA minus the defense\'s EPA allowed on that play type over the league\'s (other games, shrunk 300 plays) for RB and WR, and minus the play\'s weather for RB. '
       'Replacement is the level of players past the starters (RB 48, WR 96, TE 48 by volume, 2016-25).',
       'Defenders (DL, LB, DB) split -(EPA minus the offense\'s rate over the league\'s; DL, DB) on a sack, INT, pass defensed, forced fumble, TFL, QB hit or a tackle on a failed play. Replacement is the credit a snap past the starters (DL 128, LB 80, DB 160) × snaps.',
       'An adjustment is kept only where split-half r rose (P >= .9): opponent for RB .199 to .217, WR .172 to .190, DL .308 to .315 and DB .147 to .149. TE and LB stay raw. Weather is used only for RB (.217 to .220).',
       'In place of WAR a game in the game model\'s injury term, it failed held out 2021-25 (MAE from 10.010 to 10.070, 0/5 seasons), so WAR stays.'],
      'NFL skill players + defenders tabs', ['NFL']),
    E('SV (CFB QBs, skill players)', 'SV (season value) is this season\'s points a game over replacement from EPA a play (QB: dropbacks and runs; skill players: runs and targets), in FBS games.',
      ['QB and RB are opponent-adjusted (the defense\'s EPA allowed on that play type over the league\'s, other games, shrunk 300 plays): split-half r goes from .360 to .403 for QB and from .179 to .199 for RB. '
       'WR and TE stay raw (P .84 / .88 on 2025-26, when target ids are complete). Weather (Open-Meteo at the stadium) added nothing.',
       'Replacement is the level of players past the starters by volume in 2025 (QB 134, RB 268, WR 402, TE 134).',
       'Defenders are left out, since the public plays carry no tackles or snaps and splash credits had no split-half reliability.',
       'In the game model, the starter\'s adjusted season value scored the same as raw season EPA (t = +0.5), so the QB charge stays.'],
      'CFB QB SV + skill players tabs', ['CFB']),
    E('SVAR', 'SVAR is SV points over replacement for the season, in wins. It is shown next to WAR, and the models keep WAR.',
      ['NFL: 36 points a win, the game model\'s points a win. All-time seasons are put on 17 games (1999-2020 × 17 / 16).',
       'CFB: 53 points a win (FBS win % rises .0189 a point of margin a game over 12 games, from the cfb_war_backtest college fit).',
       'All-time SV history: NFL from 1999 (defenders from 2013, with snap counts) and CFB from 2014 (cfbfastR play-by-play), with CFB WR/TE and RB targets from 2025 (target ids). Replacement moves with each season\'s league EPA a play, for era.',
       'Every SV test in the game model failed against WAR (NFL QB MAE from 10.010 to 10.034, the NFL non-QB injury term 0/5 seasons, CFB QB = raw), so WAR stays the model input.'],
      'NFL QBs, skill players, defenders; CFB QB SV, skill players; rookie boards; all-time peak seasons', ['NFL', 'CFB']),
    E('SV / SVAR (soccer)', 'SV (season value) is this season\'s goals over replacement a 90, from this season alone. SVAR = SV × 90s, the season total in goals. It is shown next to GAR, and the models keep GAR.',
      (lambda F, R: ['It uses GAR\'s weights on this season\'s inputs only: on-pitch xG for and against, on minus off, npxG, xGBuildup, and an xG plus-minus over this season\'s spells alone '
                  '(GAR\'s spans three seasons). The xG part is scaled ×%.3f so a side\'s players add up to its xG difference (R² %.2f).' % (F['scale'], F['r2XgPart']),
                  'Finishing (goals minus npxG) and keepers\' goals saved against xG faced are shrunk toward the league average by min / (min + k), with k %s minutes for saves and %s for finishing, '
                  'from split-half reliability within a season (odd against even matches: r %.3f for saves and %.3f for finishing, with no player prior). '
                  'A side\'s players then add up to its goal difference with R² %.3f over %d team-seasons %d-%d (GAR on the same seasons %.3f).'
                  % (f"{F['kGk']:,}", f"{F['kFin']:,}", R['gk0']['splitHalfR'], R['fin']['splitHalfR'], F['r2Gd'], F['teamSeasons'], F['seasons'][0] - 1, F['seasons'][1], F['r2GarGd']),
                  'Replacement is the xG part of the bottom-three sides\' regulars, less sides that collapsed (GK %+.3f, D %+.3f, M %+.3f, F %+.3f a 90), with finishing and saves at league average. League strength is ×%.3f a goal of club rating.'
                  % (F['repl']['GK'], F['repl']['D'], F['repl']['M'], F['repl']['F'], F['lgScale']['k']),
                  'Weights fit on the same season (team goal difference, or first half to second half) could not split a side\'s xG between its players. '
                  'The team totals are the same either way, so GAR\'s split is kept.'])(json.load(open(os.path.join(ROOT, 'data', 'soccer_sv_fit.json'))),
                                                         json.load(open(os.path.join(ROOT, 'research', 'soccer_sv_shrink.json')))),
      'soccer SVAR leaders, rookies, all-time players, transactions; conviction awards (Ballon d\'Or pool by SVAR)', ['Soccer']),
    E('GAR / SVAR on FotMob (soccer)', 'The stand-in for soccer GAR and SVAR in a league where Understat is behind the results.',
      (lambda G, q, h, z: ['GAR is built on Understat\'s on-pitch data. When its match files trail a league by a round, that league\'s rows move to FotMob\'s season lists, and move back when Understat is in step.',
                  'A ridge fit per position maps FotMob\'s rates a 90 (npxG, xA, finishing, chances created, shots, passing, defensive actions, match rating, keepers\' goals prevented) and the side\'s xG for and against '
                  'to the player\'s Understat value a 90. The GAR fit also reads his Understat value from the season before. Held out by season %d-%d, r is %.2f for GAR and %.2f for SV.'
                  % (G['seasons'][0] - 1, G['seasons'][1], G['test']['r']['gar'], G['test']['r']['sv']),
                  'Rate = w × the frozen Understat rate + (1 - w) × the FotMob estimate, and the total is the rate × FotMob\'s minutes. w = a × min / (min + k) on his frozen minutes. '
                  'With three quarters of the matches seen, a is %.1f for GAR and %.1f for SV. With a quarter seen, %.1f and %.1f. A player Understat never saw gets the FotMob estimate.'
                  % (G['blend']['gar']['0.75'][0], G['blend']['sv']['0.75'][0], G['blend']['gar']['0.25'][0], G['blend']['sv']['0.25'][0]),
                  'Test: Understat frozen at a quarter, half and three quarters of each season, scored on the full-season totals of %s player-seasons. Frozen at three quarters, RMSE of SVAR is %.2f for the frozen total, '
                  '%.2f for the frozen rate on current minutes and %.2f for the blend (t %.1f, %d of %d seasons). GAR: %.2f, %.2f, %.2f (t %.1f).'
                  % (f"{q['n']:,}", q['rmse']['C0'], q['rmse']['C1'], q['rmse']['C3'], q['t_C3_vs_C1'], q['won_C3_vs_C1'], len(G['test']['seasons']),
                     h['rmse']['C0'], h['rmse']['C1'], h['rmse']['C3'], h['t_C3_vs_C1']),
                  'Frozen at a quarter, SVAR RMSE goes from %.2f to %.2f, and the top 150\'s rank correlation with the final order from %.2f to %.2f.'
                  % (z['rmse']['C0'], z['rmse']['C3'], z['top150']['C0'], z['top150']['C3']),
                  'Blended into GAR while Understat is up, it adds nothing to next season (team R² %.3f against %.3f, t %.1f), so it is only the fallback.'
                  % (G['test']['blendUp']['r2Blend'], G['test']['blendUp']['r2Understat'], -G['test']['blendUp']['t'])])(
          *(lambda G: (G, G['test']['freeze']['sv_0.75'], G['test']['freeze']['gar_0.75'], G['test']['freeze']['sv_0.25']))(json.load(open(os.path.join(ROOT, 'data', 'soccer_fm_gar_fit.json'))))),
      'Soccer SVAR leaders, rookies, awards, xMV and projections in a league Understat trails', ['Soccer']),
    E('Yds+ / YOE (returners)', 'Kick and punt return yards over expected, shrunk.',
      ['YOE is return yards minus the mean return from the same spot (5-yard bins, this season). It uses yards instead of EPA, since EPA doesn\'t repeat.'],
      'special teams tab on NFL and CFB pages', ['NFL', 'CFB']),
    E('Development (school / coach)', 'The outcome per recruit over what his recruiting rating predicted, shrunk by sample.',
      ['CFB: NFL FV per signee, with a school tau of .42 FV, rolling t = 5.3 (6/6). CBB NBA FV is null, and the college BPM change passes.',
       'CBB head coach BPM over expected: split t = 5.1. Shown with +/- 1 SD.'],
      'development tab on CFB and CBB pages', ['CFB', 'CBB']),
]})

# ---------------------------------------------------------------- player odds & projections
sections.append({'id': 'players', 'title': 'Player odds and projections', 'entries': [
    E('Draft%', 'P(declares) × P(picked in the 2027 draft).',
      ['Declare is a logit on ln xPick and age on draft day. Ranked underclassmen declare about 94% of the time, seniors about 69% and RS seniors 100%.',
       'Picked is a log-normal around the mock xPick, with an SD that narrows toward the draft (PFF dated boards, 2020-26).'],
      'CFB board, draft board', ['CFB']),
    (lambda f, t, k, r, n, q, qn: E('DECT', 'Declare, Even, College, Transfer: which is worth most to a draft prospect with eligibility left, with Even when the model cannot tell the top two apart.',
      [f"Declare = the rookie deal + later earnings over where he goes from his xPick (CBB: his consensus rank). College = what his school would pay him next season + the same draft value one year older: xNIL, his price on the open market, times the school's pay per market dollar (its roster's yNIL over its xNIL). Transfer = the same at the market price, xNIL. "
       f"Dollars are at this season's cap, later years count {f['d']:.2f} a year. It is what is worth more to him, not what he will do (that is Ret%).",
       f"Each side is a certainty equivalent: the sure amount he would trade the gamble for, with log utility over ${f['w0']:.0f}M (what a college graduate earns outside the sport) plus the outcome. "
       "A player gets one career and cannot spread the risk, so a sure yNIL counts for more than the same dollars spread over a few long careers. "
       f"The outcome spread is the pick spread times how far later earnings land from the fit at that pick, from the same drafts as the fit "
       f"(NBA: the {qn['drafts'][0]}-{str(qn['drafts'][1])[2:]} drafts, {qn['n']} picks and {qn['undrafted']} undrafted prospects). The hover keeps the edge on plain averages.",
       f"Even: the top two are inside one standard error. Against declare that is yNIL's error (log error {f['sig']['cfb']:.2f} CFB, {f['sig']['cbb']:.2f} CBB against On3) and the age term's. "
       f"College against transfer it is the width of the reported school budgets (log {f['gap']['cfb']:.2f} CFB, {f['gap']['cbb']:.2f} CBB). "
       f"On the {k['drafts'][0]}-{str(k['drafts'][-1])[2:]} CFB boards {100 * q['even']['share']:.0f}% were Even, on the CBB boards {100 * n['check']['readings']['even']['share']:.0f}%.",
       f"Three readings against who went back, CFB ({q['n']} prospects, {100 * q['returned']:.0f}% returned) / CBB ({n['check']['readings']['n']}, {100 * n['check']['readings']['returned']:.0f}%). "
       + ' '.join(f"{lab}: says college for {100 * q[key]['saysCollege']:.0f}% / {100 * n['check']['readings'][key]['saysCollege']:.0f}%, AUC inside rank thirds {q[key]['aucInThirds']:.2f} / {n['check']['readings'][key]['aucInThirds']:.2f}."
                  for lab, key in (('Average', 'mean'), ('Median', 'median'), ('Certainty equivalent', 'ce'))) +
       f" The average sends almost nobody back, so the board uses the certainty equivalent. Returned by verdict, CFB: Declare {100 * q['even']['returnedDeclare']:.0f}%, Even {100 * q['even']['returned']:.0f}%, "
       f"College {100 * q['even']['returnedCollege']:.0f}%. CBB: {100 * n['check']['readings']['even']['returnedDeclare']:.0f}%, {100 * n['check']['readings']['even']['returned']:.0f}%, {100 * n['check']['readings']['even']['returnedCollege']:.0f}%.",
       (lambda x, c, ro: f"Transfer carries no draft cost. Of {c['n']:,} returning CBB prospects in the {c['seasons'][0]}-{str(c['seasons'][1])[2:]} seasons, {c['moved']} moved; {100 * c['draftedMoved']:.0f}% of them were drafted later "
        f"against {100 * c['draftedStayed']:.0f}% of those who stayed, and with production, rank, age and height held the move is worth nothing either way (t = {c['t']:.1f}). CFB has no roster history to test yet. "
        f"Transfer shows when the market pays more than his school's budget can. A bigger role is not priced (the hover notes a player under half his team's snaps or minutes): of {ro['n']:,} returning prospects in {ro['seasons'][0]}-{str(ro['seasons'][1])[2:]}, players under half their team's minutes who moved went from "
        f"{ro['blockedMoved']['min0']:.0f}% of minutes to {ro['blockedMoved']['min1']:.0f}% and those who stayed from {ro['blockedStayed']['min0']:.0f}% to {ro['blockedStayed']['min1']:.0f}%; {100 * ro['blockedMoved']['draftedLater']:.0f}% and "
        f"{100 * ro['blockedStayed']['draftedLater']:.0f}% were drafted later, and the move adds nothing held out (t = {ro['t']:.1f} in the fit, log loss {ro['walkForward']['dLogLoss']:+.4f} walking forward from {ro['walkForward']['from']}). "
        f"On the CBB boards ({x['n']} prospects with a known next year: {100 * x['did']['D']:.0f}% declared, {100 * x['did']['C']:.0f}% stayed, {100 * x['did']['T']:.0f}% transferred) "
        + ' '.join(f"{lab} ({x['byVerdict'][key]['n']}): {100 * x['byVerdict'][key]['D']:.0f}% / {100 * x['byVerdict'][key]['C']:.0f}% / {100 * x['byVerdict'][key]['T']:.0f}%." for lab, key in (('Declare', 'D'), ('Even', 'E'), ('College', 'C'), ('Transfer', 'T')) if key in x['byVerdict'])
        + " Only mid-major prospects had a market price above their own school's in that history, so the Transfer row is small.")(n['transfer'], n['transfer']['cost'], n['role']),
       "The college side holds his draft stock where it is, so going back costs a year and pays yNIL. A young player who develops can beat that, and one who gets hurt falls under it. "
       "Who went back is not a fair sample of either (the ones told they would go late stay), so their record is shown below and not used.",
       f"NFL rookie deal: the 2026 slotted four-year totals, with the guaranteed share by pick from OverTheCap rookie deals and the rest counted at the odds he is still on a roster. "
       f"Later earnings: every veteran contract of the {f['later']['drafts'][0]}-{str(f['later']['drafts'][1])[2:]} drafts ({f['later']['n']:,} picks) as a share of the cap, fit on pick, position and age. "
       f"A year older at the same pick is {f['later']['agePct']:.0f}% in later earnings (t = {f['later']['ageT']:.1f}). "
       f"NBA: salary in seasons 1-4 by pick ({n['rookie']['drafts'][0]}-{str(n['rookie']['drafts'][1])[2:]} drafts, {n['rookie']['n']} college picks) and from season 5 on "
       f"({n['later']['drafts'][0]}-{str(n['later']['drafts'][1])[2:]}, {n['later']['n']} picks); a year older is {n['later']['agePct']:.0f}% (t = {n['later']['ageT']:.1f}). "
       f"Undrafted prospects on ESPN's final board made ${n['undrafted']['rookie']:.1f}M in seasons 1-4 and {100 * n['undrafted']['anyNba']:.0f}% drew an NBA salary.",
       f"Pick spread, from players with no choice: {f['spread']['declare']['n']} redshirt seniors and grads on each draft's last PFF board before the January deadline "
       f"({f['spread']['drafts'][0]}-{str(f['spread']['drafts'][-1])[2:]}; {100 * f['spread']['declare']['undrafted']:.0f}% undrafted, sd {f['spread']['declare']['sd']:.2f} in ln pick) and "
       f"{n['spread']['declare']['n']} seniors on the No Ceilings midseason board ({n['spread']['drafts'][0]}-{str(n['spread']['drafts'][-1])[2:]}; "
       f"{100 * n['spread']['declare']['undrafted']:.0f}% undrafted, sd {n['spread']['declare']['sd']:.2f}). Early entrants who left went undrafted "
       f"{100 * f['spread']['allDeclared']['undrafted']:.0f}% (all declared, CFB) and {100 * n['spread']['earlyEntrants']['undrafted']:.0f}% (CBB) of the time: they left knowing more than the board.",
       "Break-even yNIL, CFB by xPick (WR certainty equivalent / QB / WR on averages, $M): " + ', '.join(f"{x['xPick']} {x['ce']:.1f} / {x['ceQB']:.1f} / {x['breakEvenNil']:.1f}" for x in t if x['xPick'] in (10, 32, 50, 100, 150, 200, 300)) +
       ". CBB by consensus rank (age 20, certainty equivalent / averages): " + ', '.join(f"{x['rank']} {x['ce']:.1f} / {x['breakEvenNil']:.1f}" for x in n['table'] if x['rank'] in (5, 14, 30, 50, 60, 80, 100)) +
       f". With ${1:.0f}M or $4M outside the sport in place of ${f['w0']:.0f}M the CFB break-even at xPick 32 is " + ' or '.join(f"{x[k]:.1f}" for x in t if x['xPick'] == 32 for k in ('ceW1', 'ceW4')) + ".",
       f"The returners' record, CFB {k['drafts'][0]}-{str(k['drafts'][-1])[2:]} boards: {r['n']} went back, {100 * r['drafted']:.0f}% were drafted the next year and {100 * r['beatDeclare']:.0f}% came out ahead of "
       f"what declaring was worth on average (mean ${r['meanGot']:.1f}M with NIL scaled to that season's market, against ${r['meanDeclareEV']:.1f}M). CBB {n['check']['drafts'][0]}-{str(n['check']['drafts'][-1])[2:]}: "
       f"{n['check']['returners']['n']} returners with a draft or an exit the next year ({n['check']['returners']['again']} went back again), {100 * n['check']['returners']['drafted']:.0f}% drafted, "
       f"{100 * n['check']['returners']['beatDeclare']:.0f}% ahead (${n['check']['returners']['meanGot']:.1f}M against ${n['check']['returners']['meanDeclareEV']:.1f}M)."],
      'CFB draft board, CBB draft board', ['CFB', 'CBB']))(_DR, _DR['table'], _DR['check'], _DR['check']['returners'], _DR['nba'], _DR['check']['readings'], _DR['nba']['spreadN']),
    (lambda c, b, n, fails: E('Ret%', 'The chance a player is back in college next season instead of in the 2027 draft, 1 - P(declares).',
      [f"CFB uses the Draft% declare logit (ln xPick, age on draft day, by class group). Leaving one draft out on the 2021-25 fall PFF boards "
       f"({c['n']} prospects, without RS seniors and grads), log loss is {c['baselines']['live']:.3f}, compared to {c['baselines']['class']:.3f} for class only, "
       f"{c['baselines']['classPos']:.3f} for class + position and {c['baselines']['rate']:.3f} for the base rate (t = {c['baselines']['liveVsClass']['t']:.1f}, "
       f"{c['baselines']['liveVsClass']['cellsWon']}/{c['baselines']['liveVsClass']['cells']} draft × class cells).",
       f"A reported return in the decision window (CFB Nov 20 to the January deadline, CBB Mar 15 to the withdrawal date) sets Ret% to "
       f"{100 * (1 - max(n['cfb']['kinds']['return']['lockRate'], n['cbb']['kinds']['return']['lockRate'])):.0f}% in both sports. In CFB there were "
       f"{n['cfb']['kinds']['return']['n']} reported returners in the {n['cfb']['cycles'][0]}-{n['cfb']['cycles'][-1]} drafts, and {100 * n['cfb']['kinds']['return']['declared']:.0f}% declared "
       f"(the model said {100 * n['cfb']['kinds']['return']['model']:.0f}%). Log loss goes from {n['cfb']['kinds']['return']['logLossModel']:.2f} to "
       f"{n['cfb']['kinds']['return']['logLossLock']:.2f}, t = {n['cfb']['kinds']['return']['t']:.1f}, "
       f"{n['cfb']['kinds']['return']['cyclesWon']}/{n['cfb']['kinds']['return']['cycles']} cycles. "
       f"A reported declaration failed (t = {n['cfb']['kinds']['out']['t']:.1f}).",
       f"CBB uses class, era (NIL 2022+, COVID 2021, the 2024+ step), recruit rank and BPM shrunk by minutes. Walk-forward 2023-26, "
       f"log loss is {_CD['held']['logLoss']:.3f}, compared to {_CD['base']['logLoss']:.3f} for class and era (t = {_CD['held']['t']:.1f}). "
       f"The 2024+ step is t = {b['stageA']['singles']['e24']['t']:.1f}, {b['stageA']['singles']['e24']['won']}/{b['stageA']['singles']['e24']['of']}. "
       f"With the midseason board on top, leaving one draft out 2022-26, board-listed players are {_CD['stageB']['rankedOnly']['B']:.3f} compared to {b['stageB']['rateRanked']:.3f} for the base rate. "
       f"The board stage carries its own 2024+ step, shipped under the gate: {_CD['stageB']['step']['lodo']['seasonsWon']}/{_CD['stageB']['step']['lodo']['of']} drafts leaving one out "
       f"(t = {_CD['stageB']['step']['lodo']['t']:.1f}), t = {_CD['stageB']['step']['walkForward']['t']:.1f} walking forward. Board ranks 31-60 in 2025-26: "
       f"{100 * [x for x in _CD['stageB']['step']['bands'] if x['ranks'] == '31-60' and x['era'] == '2025-26'][0]['left']:.0f}% left, the model says "
       f"{100 * [x for x in _CD['stageB']['step']['bands'] if x['ranks'] == '31-60' and x['era'] == '2025-26'][0]['model']:.0f}% "
       f"({100 * [x for x in _CD['stageB']['step']['bands'] if x['ranks'] == '31-60' and x['era'] == '2025-26'][0]['before']:.0f}% before the step).",
       *([f"CBB reported return: {n['cbb']['kinds']['return']['n']} players, {100 * n['cbb']['kinds']['return']['declared']:.0f}% left "
          f"(the model said {100 * n['cbb']['kinds']['return']['model']:.0f}%), t = {n['cbb']['kinds']['return']['t']:.1f}, "
          f"{n['cbb']['kinds']['return']['cyclesWon']}/{n['cbb']['kinds']['return']['cycles']}. It {'passed' if n['cbb']['kinds']['return']['pass'] else 'failed'}."]
         if n.get('cbb', {}).get('kinds', {}).get('return', {}).get('n') else []),
       "Failed on top of the live model in both sports (each one was tried in both): " + fails + ".",
       (lambda c, b, bd: f"Draft pay in dollars (first-year cash over the pick spread against college pay, each scaled to its year's salary cap and NIL "
        f"market) failed in CFB (t = {c['onTop']['econ1p']['t']:.1f} as a log ratio, {c['onTop']['gap']['t']:.1f} as a dollar gap, "
        f"{c['drafts'][0]}-{str(c['drafts'][-1])[2:]} boards). In CBB the dollar gap passes leaving one draft out (t = {b['onTop']['gap']['t']:.1f}, "
        f"{b['onTop']['gap']['won']}/{b['onTop']['gap']['of']}), but it is the year level and not the player: beside a 2024+ step it is "
        f"t = {b['besideStep']['gap']['t']:.1f}, and walking forward t = {b['walkForward']['gap']['t']:.1f}. It didn't ship. Board ranks "
        f"{bd[0]['picks']}: {100 * bd[0]['left']:.0f}% left in {bd[0]['era']} (n = {bd[0]['n']}) and {100 * bd[1]['left']:.0f}% in {bd[1]['era']} "
        f"(n = {bd[1]['n']}; the model said {100 * bd[1]['model']:.0f}% then).")(
           _RP['cfb'], _RP['cbb']['stageB'], [x for x in _RP['cbb']['stageB']['bands'] if x['picks'] == '31-60'])],
      'CFB draft board, CBB draft board', ['CFB', 'CBB']))(
        _RD['cfb'], _RD['cbb'], _RD.get('news', {}),
        ', '.join(dict.fromkeys(
            [{'prod': 'PFF grade x snaps (CFB; the BPM analogue)', 'rec': 'recruit rank (CFB)', 'ht': 'height', 'covid': 'COVID year (CFB)',
              'nil22': 'NIL 2022+ step (CFB)', 'nil_lx': 'NIL x xPick', 'nil_age': 'NIL x age', 'econ': 'rookie deal vs NIL',
              'qb': 'QB', 'p4': 'Power 4 / high-major'}[k] for k, v in _RD['cfb']['singles'].items() if not v['pass']] +
            [{'age_c': 'age in class (CBB)', 'age': 'age (CBB)', 'hm': 'Power 4 / high-major', 'ht': 'height', 'guard': 'guard (QB analogue)',
              'nil_bpm': 'NIL x BPM', 'nil_rank': 'NIL x recruit rank', 'nil_age_c': 'NIL x age', 'e24': '2024+ step'}[k]
             for k, v in _RD['cbb']['stageA']['singles'].items() if not v['pass']] +
            [{'econ': 'rookie deal vs NIL', 'age_c': 'age in class (CBB)', 'hm': 'Power 4 / high-major', 'guard': 'guard (QB analogue)'}[k]
             for k, v in _RD['cbb']['stageB']['singles'].items() if not v['pass']]))),
    E('Transfer% (Xfer%)', 'The chance a player is on another FBS or FCS roster next season.',
      ['A ridge logit on the 2024-25 and 2025-26 cycles: class, production, role, recruit rank, record, P(HC change) and distance from home.',
       'Out-of-time AUC is .738. Transfer% + stay + exit = 100%. It uses NIL-era data only (July 2021 on).',
       f'Coach ties: in CBB the head coach\'s seasons at the school lower it (2025-26 held out t = {_CL["cbb"]["move"]["terms"]["T4 hc_ten"]["A"]["t"]}, log loss {_CMF["loglossRecal"]:.4f}, AUC {_CMF["auc"][1]:.3f}); in CFB the same term failed (t = {_CL["cfb"]["terms"]["T4 hc_ten"]["2024->25 fit, 2025->26 scored"]["t"]}).',
       f'A transfer who came with his head coach moved again {100 * _CL["cbb"]["move"]["rates"]["transfer in, came with coach"]["moved"]:.1f}% of the time in CBB against {100 * _CL["cbb"]["move"]["rates"]["transfer in, did not"]["moved"]:.1f}% for other transfers (n = {_CL["cbb"]["move"]["rates"]["transfer in, came with coach"]["n"]}), and {100 * _CL["cfb"]["rates"]["transfer in, came with head coach"]["transfer"]:.1f}% against {100 * _CL["cfb"]["rates"]["transfer in, did not"]["transfer"]:.1f}% in CFB (n = {_CL["cfb"]["rates"]["transfer in, came with head coach"]["n"]}). Too few to pass held out (t = {_CL["cbb"]["move"]["terms"]["T1 came_with"]["A"]["t"]} CBB, {_CL["cfb"]["terms"]["T1 came_with"]["2024->25 fit, 2025->26 scored"]["t"]} CFB). Seasons under the coach, players he inherited and a coach leaving x the tie failed in both sports too.'],
      'CFB board, portal, team builder; CBB portal', ['CFB', 'CBB']),
    E('team builder', 'Each program\'s next season: who comes back, who leaves, the class, the signings the budget buys, and what the team projects to be.',
      ['Returners count at their chance to be back (Ret%, Transfer%, the draft), the class at its chance to be on the field, signings at Transfer% x landing odds. Money is the school\'s NIL budget (its roster yNIL, which shares the reported budget) as a soft limit.',
       f'Football strength is Elo from the plan\'s college WAR, fit on this season\'s Elo across FBS (R2 = {_TBX["cfb"].get("r2", 0):.2f}, n = {_TBX["cfb"].get("n", 0)}). Basketball strength is the ARK rating of the plan\'s rotation.',
       f'xW is wins over a conference schedule at every team\'s projected strength: {_TBX["cfb"].get("games", 12)} games in football, {_TBX["cbb"].get("games", 31)} in basketball. Wins over replacement are xW less a 10th-percentile team on the same schedule, and NIL $ a win is next season\'s spend over those wins.',
       f'DECT as an input failed everywhere it was tested. In Ret% the staying edge made held-out log loss worse in both sports (CFB t = {_DX["ret"]["cfb"]["terms"]["R1 ce"]["lodo"]["t"]}, CBB t = {_DX["ret"]["cbb"]["terms"]["R1 ce"]["lodo"]["t"]} against it). CBB Transfer%: DECT t = {_DX["cbb_move"]["move"]["terms"]["T4 dect"]["A"]["t"]} on 2025-26 (needs 2), school pay per market dollar t = {_DX["cbb_move"]["move"]["terms"]["T2 k"]["A"]["t"]}, market over school pay t = {_DX["cbb_move"]["move"]["terms"]["T1 zgap"]["A"]["t"]}. CBB landing, money per market dollar at the destination t = {_DX["cbb_move"]["land"]["L1 dest_k"]["A"]["t"]}. CFB Transfer% has one fall board to test on and is retested after the 2026-27 cycle. DECT shows on the builder for reading only.',
       _tbx_pot()],
      'CFB team builder, CBB team builder', ['CFB', 'CBB']),
    E('FBS%', 'The chance an FCS player is on an FBS roster next season.',
      ['A logit on 2023-26 FCS-to-FBS moves: production, team strength, year in school and position. It is capped at 1 - Draft%.'],
      'CFB FCS board', ['CFB']),
    E('D-1%', 'The chance a D-II or D-III player is on a D-I roster next season.',
      ['A ridge logit on NCAA D-II/III box scores, for the 2023-24 and 2024-25 move-ups: production, starts, minutes, team SRS and division.',
       'Out of time on 2025-26 to 2026-27, AUC is .899 and log loss is .077, compared to .111 for the base rate.',
       'FV = 20 + D-1% × V. V is his line translated to a first D-I season (shrunk BPM; a ridge on 318 movers, out of time r .43/.60),',
       'then what the 2009-16 arrivals with that season and class became (Poisson index + monotone map, out-of-fold deviance t = 2.8).'],
      'CBB board (D-II / D-III filter)', ['CBB']),
    E('Dec%', 'The chance a college player leaves school for this NBA draft.',
      ['Recruit rank, minutes-shrunk BPM, class and era, plus the midseason board rank. Seniors and internationals are 100%.'],
      'CBB mocks', ['CBB']),
    E('P20 / P50 / P80 projections', 'The 20th, 50th and 80th percentile of WAR, VORX and stats, for the full season and the rest of the season.',
      ['Rest of season = rate × exposure (minutes, TOI, snaps), where the rate is a Marcel 1 / .7 / .5 with a fitted shrink.',
       'It is recalibrated for each season-left bin, and checked by PIT on held-out seasons (+/- .03 overall).'],
      'projections tab on NFL, NBA, NHL pages', ['NFL', 'NBA', 'NHL']),
    E('Player game projections', 'Per-game points, rebounds and assists (NBA, CBB) and fantasy lines (NFL, CFB).',
      ['The NBA version walks the game model\'s minutes and P(play), plus pace, opponent and the minutes freed up by teammates who are out.',
       'Held out 2024-26, PRA MAE is 6.20, compared to 6.46 for the season average. CBB is 5.42 compared to 5.58.'],
      'Predictions players group', ['NBA', 'CBB', 'NFL', 'CFB']),
    E('NFL fantasy VOR', 'A player\'s projection minus the replacement projection at his position, in a 12-team league.',
      ['Replacement is the first non-starter: QB13, RB30, WR31, TE13, K13, DST13. The overall rank is by VOR.'],
      'Predictions NFL rankings', ['NFL']),
    E('Standouts (NFL)', 'Young players\' weekly WAR over expected.',
      ['xWAR = his WAR rate a snap before the week (three seasons shrunk to the group, updated in season) × snaps.'],
      'NFL standouts tab', ['NFL']),
    E('Standouts (CFB)', 'First and second-year QB, RB, WR and TE whose touches and targets are rising.',
      ['It lists usage growth. It is a watch list, and no model grade is behind it.'],
      'CFB standouts tab', ['CFB']),
    E('Next up (breakout odds)', 'The chance of a first season at a quality bar next season, for players who have never reached it.',
      ['The bar is a shrunk value near the 75-80th percentile of regulars. Anyone already over it (career, this season included) is out.',
       'NBA: BPM +1.0, 1,000+ MP. CBB: BPM +2.8, 40%+ min. NHL: WAR/1,000 min 1.19. Soccer: GAR/90 .090. NFL: PPR/G 12 (TE 9). CFB: PFN z .32.',
       'A logistic on shrunk value plus signals. Each signal is added alone, leaving one season out, and needs t >= 2 and most seasons won, then Holm.',
       'The age or class curve passes everywhere. Low-volume efficiency and the projection gap pass in most sports. CBB adds team context (t = 3.8) and the pXPM gap.',
       'Failed: vacated role (all six sports), coaching change, opportunity ahead, improvement trend, splines, Platt, and boosted trees (they never beat the logistic).',
       'Held-out t: NBA 7.9, CBB 14.4, NHL 5.6, soccer 6.2, CFB 6.0, NFL 3.3.'],
      'next up tab on every sport page', ['NBA', 'CBB', 'NHL', 'Soccer', 'NFL', 'CFB']),
    E('Next up tiers (usage scaling)', 'A player\'s projected output at a bigger workload, from players whose workload changed.',
      ['Workload is USG (NBA, CBB), TOI split EV/PP (NHL), shot involvement SI% (soccer) and target or touch share (NFL).',
       'Next-season efficiency on this season\'s, shrunk for sample, plus workload change × context blocks, in a ridge held out by season.',
       'A workload change alone doesn\'t drop efficiency on average, which is selection: players earn the work.',
       'NBA: the shot profile sets the slope (high-2P% finishers lose the most). CBB: shot profile, role, frame, level and low-usage rates.',
       'NHL: EV P/60 rises with minutes (instrumented, 0.14 a minute). Soccer: role. NFL RB: -0.23 Y/OPP per 10 share points.',
       'Tiers past the 99th percentile of observed jumps are beyond the data. CFB has no tiers, since every test failed.',
       'CEIL is an 80th percentile season one tier up (NBA/CBB usage +5, NHL TOI +3, soccer SI% +10), on role seasons: mean + q × spread.',
       'CEIL scales: NBA XPM, CBB BPM, NHL shrunk WAR/1k, soccer shrunk GAR/90. Workload change × context passes in all four.',
       'CEIL held-out t (pinball .80): NBA 3.9, CBB 6.1, NHL 6.0, soccer 9.3. Coverage is 79-80% of workload-up seasons.'],
      'next up tab', ['NBA', 'CBB', 'NHL', 'Soccer', 'NFL']),
    E('Backup watch / xGap', 'Second and third-string players who grade above a starter.',
      ['Gap = backup value - starter value (WAA and BPM with pXPM in college; WAR, pXPM, HPM or GAR in the pros).',
       'They are ranked by xGap, the gap projected over two seasons with the age (or class) gap added. Held out t = -3.0 to -15.6.',
       'NFL xGap projects from the pXP/60 gap on its own fit of 2,457 pairs: held out squared error .0429 to .0375, t 5.1, 5 of 5.',
       'NHL adds the Marcel GAR a 60 gap (t -2.4, 9 of 10) and soccer the p/90 gap (t -5.9, 7 of 7) beside the grade gap.',
       'NBA grades are pXPM: next season XPM error 1.301 to 1.185, t 13, 15 of 15. With pXPM already aged, its age term drops out.'],
      'backup watch tab on every sport page', ['CFB', 'CBB', 'NFL', 'NBA', 'NHL', 'Soccer']),
    E('Comps', 'The nearest historical profiles, shown in the player dropdown.',
      ['CFB uses the nearest 2014-22 profiles. Hockey stage 3-4 comps also feed FV (they passed held out). Everywhere else they are display only.'],
      'Player dropdowns', ['CFB', 'Hockey']),
    E('G League NBA% / 500% / xVORX', 'A G League player\'s chance of NBA minutes next season, his chance of 500+ NBA minutes (per 82 games), and his expected NBA VORX over the next 3 seasons.',
      ['A ridge logistic (L2 1) on 8,036 G League seasons 2008-25, regular season + Showcase Cup, 50+ minutes. Showcase-only seasons 2022-25 are pooled in with a part-season flag.',
       'Inputs: age, age^2, log minutes, games, the per-36 box (pts reb ast stl blk tov 3PA FTA, Game Score, +/-), TS%, usage, AST%, OREB%, DREB%, net rating and PIE; NBA minutes and XPM (shrunk to -2 with 500 MP) through last season; draft round, log pick and years since the draft.',
       'xVORX = P(any NBA game in 3 seasons) × ridge E[3-season VORX | plays].',
       'Leaving one season out, against the same model without G League stats: NBA% log loss is .338 compared to .378 (t = -6.2, 16/18 seasons) and AUC .883 compared to .846 (.912 and .872 for players with no NBA minutes yet). 500% is .191 compared to .207 (t = -4.3), AUC .897 compared to .862. xVORX RMSE is .921 compared to .981 (t = -3.1). All of them pass Holm.',
       'It is calibrated by decile held out (the top NBA% decile was .87 predicted and .86 observed). The base rates are 23% / 8%.',
       'A two-way to standard contract isn\'t modelled, since there is no contract-type history.'],
      'NBA G League tab', ['NBA']),
]})

# ---------------------------------------------------------------- team ratings
sections.append({'id': 'teams', 'title': 'Team ratings', 'entries': [
    E('ARK Ranking', 'Each sport\'s power ranking, which is the game model\'s neutral-site rating put in order.',
      ['It is the same number the game model uses, so the picks already read it. It splits into parts (Elo, efficiency, talent ...).',
       'The rank range is the 80% range of the true rank, from 4,000 draws at the rating sd measured on past seasons.',
       'In CBB 2016-26, ARK picks the winner 77.3% of the time compared to 76.8% for the AP poll, and 77.1% compared to 76.7% for the Coaches poll.'],
      'ARK Ranking tab on every sport page; ARKRANKING page', ['CFB', 'NFL', 'CBB', 'NBA', 'NHL', 'Soccer', 'Tennis', 'CS2']),
    E('CFB rating', 'Points against an average FBS team on a neutral field.',
      ['Elo (with a preseason prior from last season, SP+, 247 talent, returning production and transfers) + opponent-adjusted EPA/play.',
       'Plus home, rest, travel, altitude, FCS (and the FCS side\'s own margin rating), special teams, P4 tier, 4th-down aggressiveness, returning production',
       'and game control. The sim\'s win sd is 14.2. Current injuries are charged (Inj), and Full is the team at full strength.'],
      'CFB ARK Ranking, games, season odds', ['CFB']),
    E('NFL rating', 'Expected margin against an average team on a neutral field, with this week\'s QB and injuries.',
      ['Fitted terms: Elo, starting QB, rest, home, injuries, a market rating from earlier closes, and the return game.',
       'Injury cost = WAR a game × 36 points a win × P(miss), where questionable is .25 and doubtful is .98.'],
      'NFL ARK Ranking, games, season odds', ['NFL']),
    E('CBB rating', 'Expected margin against an average D-I team on a neutral floor.',
      ['Fitted terms: adjusted efficiency × possessions, Elo, home, game control, conference home game, injuries,',
       'home × attendance, ESPN BPI, form and the preseason injury report. The preseason prior comes from returning minutes, transfers and top-5 FV.',
       '50% of three-point luck is taken out.',
       'Market disagreement is each team\'s running gap between its earlier closes and the model (.2 a game, 0 at the start of the season), for spreads and totals. On lined games 2021-26, margin MAE goes from 9.057 to 9.009 (the close is 8.986) and totals from 13.401 to 13.366.'],
      'CBB ARK Ranking, games, season odds, tournament odds', ['CBB']),
    E('NBA rating', 'Expected margin against an average team on a neutral floor, with the current roster and today\'s injury report.',
      ['Fitted terms: Elo, net rating, market rating, home, lineup value (XPM × minutes × chance to play), playoff Elo and rest.',
       '25% of three-point luck is taken out. The Proj column (rest-of-season VORX) is display only.'],
      'NBA ARK Ranking, games, season odds', ['NBA']),
    E('NHL rating', 'Win chance from a logistic on Elo, an expected-goals rating, back-to-backs, home and lineup value.',
      ['The xG rating is an opponent-adjusted ridge with a half-life of 120 days, and .7 of it carries over a season. Lineup value follows trades.',
       'Totals use xG, goals, the market total and the starting goalie.'],
      'NHL ARK Ranking, games, season odds', ['NHL']),
    E('Soccer rating', 'Goals a match against an average big-five club on neutral ground, on one scale for every league.',
      ['An online Poisson attack and defence rating within each league, with league strength from cross-league matches only.',
       'The inputs are blended walk-forward: market-implied goals from earlier closes, xG (Understat, FotMob) and squad value.',
       'Dixon-Coles rho is -.04. In the big five, held out, log loss is .972 compared to .967 for the close.'],
      'Soccer ARK Ranking, league tabs, UEFA cups, MLS', ['Soccer']),
    E('Tennis ARK', 'Win chance against the average top-50 player in a best of three, over the tour\'s 52-week surface mix.',
      ['Surface Elo blended with a games-won rating and opponent-adjusted serve and return point ratings (Markov chain).',
       'It is fit on 2012-22 tour main draws. Held 2023-26, log loss is about .596, compared to .603 for Elo.'],
      'Tennis ATP / WTA ARK Ranking', ['Tennis']),
    E('CS2 ARK', 'Series win chance against the average top-20 team.',
      ['A player Elo that follows players between rosters (per map, on round share), the bo3.gg team map rating with veto,',
       'region offsets, Valve VRS points and the five players\' mean RWA. Held out log loss is .553, compared to .667 for VRS. There are no picks, since there is no free closing odds history.'],
      'Counter-Strike ARK Ranking, matches, model', ['CS2']),
    E('Elo', 'A rating from results and margin, where 1500 is average.',
      ['CFB Elo starts from a preseason prior. In CS2 Elo, +400 is 10 to 1 odds. Tennis Elo is on wins, at every level.'],
      'Ranking tabs', ['CFB', 'NFL', 'CBB', 'NBA', 'NHL', 'Tennis', 'CS2']),
    E('Game control', 'How much of each game a team spent with the win in hand.',
      ['A time-weighted win chance from score and clock only, opponent-adjusted and carried across seasons.',
       'It shipped in CFB (held out MAE t = -4.1) and CBB (t = -2.0). It failed in the NBA.'],
      'CFB and CBB ARK Ranking (Control)', ['CFB', 'CBB']),
    E('Talent / TvE', 'Talent is the value of the projected starters by FV, and TvE is Elo against the Elo that talent predicts, in SD.',
      ['CFB Talent is the sum over the projected starting 22 of expected college WAR a season at FV. A TvE above 0 means the team is playing above its talent.'],
      'CFB team talent, ARK Ranking', ['CFB']),
    E('Season odds', '10,000 simulated seasons from the game model.',
      ['The rating error sd shrinks with the season left (sd^2 = a + b × share left, measured on past seasons).',
       'xW = wins so far + the simulated rest. The outputs are conference, playoff and title odds, with full NFL tiebreakers.'],
      'season odds tab on every team sport; ARKRANKING', ['CFB', 'NFL', 'CBB', 'NBA', 'NHL', 'Soccer']),
    E('CFP odds', 'A committee model plus the bracket for the 12-team playoff.',
      ['A Plackett-Luce fit on the CFP releases 2017-25: losses, wins, rating, wins above bubble and P4. Held out field log loss is .029, compared to .090.',
       'Committee memory: final score = c × model + a × (26 - CFP rank) / 25 + d × wins above bubble since the release, with a, c and d by weeks to Selection Sunday.',
       f"Fit 2017-21 and held 2022-25 ({_CFPMR['pairs']} releases), final-ranking log lik goes from {_CFPMR['old']:.1f} to {_CFPMR['new']:.1f} (t = {_CFPMR['tVsOld']:.1f}), "
       f"and seed log loss from {_CFPMS['seedLL']['old']:.3f} to {_CFPMS['seedLL']['new']:.3f} (t = {_CFPMS['tSeedLL']:.1f}).",
       '2026 rules: the P4 champions are in, plus the best G6 champion, and Notre Dame if it is in the top 12. The top 4 get byes.'],
      'CFB season odds (Bye, Semis, Natl title), bracket', ['CFB']),
    E('NCAA tournament odds', 'Committee and bracket sims for bids, seeds and rounds.',
      ['The committee is fit on the 2015-26 fields from rating and wins above bubble (the 45th team), and gets 91% of at-large picks.',
       'The conference tournaments and the bracket are played out with the game model.'],
      'CBB tournament odds tab', ['CBB']),
    E('Futures', 'The title, conference and division sims against DraftKings futures, with the vig removed.',
      ['They are display only. The win-total backtests found no proven edge (NBA b .22, t = 3.0 in sample and t = 1.5 held out).'],
      'Predictions futures tab; title odds on ARKRANKING', ['NFL', 'NBA']),
    E('Team badges', 'Team trait medals, each on one stat, shrunk by games to a reliability of .5.',
      ['59 of 72 pass the repeat test. NFL Return Game also passed against the close, and it is in the NFL model.'],
      'ARK Ranking team dropdowns, team GFX cards', ['CFB', 'NFL', 'CBB', 'NBA', 'NHL', 'Soccer']),
    E('Staff score / coach pay', 'Head coach and coordinator scores, and a coach\'s market value against his public pay.',
      ['Pay is modelled on program plus wins (USA Today data). Surplus = Value - Pay. The staff score includes zNIL growth (20%).',
       'A coach\'s value-added doesn\'t carry to a new job (it failed the test), and the staff weights are set by hand.'],
      'CFB staff, coach pay, coaching jobs tabs', ['CFB']),
]})

# ---------------------------------------------------------------- games & predictions
sections.append({'id': 'games', 'title': 'Game models and predictions', 'entries': [
    E('Game projection', 'The model line, win chance and projected score for every game.',
      ['The margin comes from the sport\'s rating (see Team ratings), and the win chance is a normal (or logistic) on the margin.',
       'The win sd is fit walk-forward: NBA about 12, CBB 11.9, CFB 14.2. Totals have a separate model in each sport.',
       'Soccer projects the score, over 2.5 and both-score from market totals ratings in 16 leagues (a league term and a lean for each club, learned from the closing over/under prices of earlier matches, never the match\'s own). Held out, over 2.5 log loss is .675 compared to .683 before, and the close is .672. 1X2 is unchanged.',
       'Predictions is the only page with picks, lines and props. The sport pages show projections only.'],
      'games and game table tabs; Predictions', ['CFB', 'NFL', 'CBB', 'NBA', 'NHL', 'Soccer', 'Tennis', 'CS2']),
    E('Walk-forward test', 'Each game is predicted with a model fit only on the games before it.',
      ['Seasons are split into tuning (where terms enter) and held out (which reports and can veto). Errors are clustered by game day.',
       'The game models tab compares live loss to the walk-forward expectation for the same month.'],
      'Predictions game models tab', ['CFB', 'NFL', 'CBB', 'NBA', 'NHL', 'Soccer']),
    E('Model ledger', 'One shared rule for every model term.',
      ['The evidence is the held-out t alone (drop-one). The tuning t is shown, but the two aren\'t combined. There is one Benjamini-Hochberg family over all terms with a held-out split.',
       'A term is kept at q <= .10, and dropped at q > .10 when held-out loss is no worse without it. Otherwise it is on watch. A term with no held-out split is on watch.',
       'Terms older than 365 days are flagged for a re-test.'],
      'Predictions game models tab (ledger view)', ['CFB', 'NFL', 'CBB', 'NBA', 'NHL', 'Soccer']),
    E('Edge / gap', 'The model minus the market, in points (spread, total) or in chance (moneyline, tennis).',
      ['Edge % on the full table is the raw model chance minus the no-vig market chance.',
       'Gaps past 5 sd are treated as bad lines, and picks between 3 and 5 sd are staked at the cap.'],
      'Predictions picks, game table', ['CFB', 'NFL', 'CBB', 'NBA', 'Tennis']),
    E('Pick rule (X)', 'A pick is the model\'s side when |model - line| >= X for that sport and market.',
      ['X is the smallest gap whose calibrated return at -103 is above 0 on the tuning seasons.',
       'A market or segment is on only if its held-out picks beat the close (clvRet > 0, t >= 1.65, n >= 30).',
       'There is one pick a game in each market family. Bet to is the worst line that still clears X.'],
      'Predictions picks, picks backtest', ['CFB', 'NFL', 'CBB', 'NBA', 'Tennis']),
    E('Calibrated edge', 'The expected return at the price, from held-out picks judged by the close.',
      ['Edge = min(EV, a + b (gap - mean gap)), where a blends close value and ROI, and b is the market\'s own slope, shrunk.',
       'History is priced at Novig -103. TIMING .5 halves every backtest edge, since live bets come after part of the move.',
       'The chance at the bet line is the market mid there (from both asks) plus the calibrated chance edge, with the gap measured from the market\'s fair line.',
       'The NBA backtest edge is also ×.5, since the history saw tip-time injury news that the open did not.'],
      'Predictions picks backtest', ['CFB', 'NFL', 'CBB', 'NBA', 'Tennis']),
    E('Kelly %', "The stake as a % of bankroll: Kelly on the calibrated edge × the book's live realization, compounding.",
      ['It was formerly Dengler Units (DU), where 1 DU = 1% of bankroll. A pick qualifies where its edge at the price is above 0.',
       'The cap is 5% a bet (tennis 2%). A joint slate Kelly gave the same growth as per-pick (rho about 0).',
       'Walk-forward, 1× Kelly had the most log growth at the backtest edge and at half of it.',
       'The stake multiplier r is close value per point of staked edge on the book\'s live picks, a normal update around .5 (sd .25), '
       'clipped 0-1. Walk-forward by game day it beat the posted stakes at the close (all books from -21.7% to -6.4% log growth, '
       'NBA from +0.81% to +1.05%).'],
      'Predictions picks, game table, paper book', ['CFB', 'NFL', 'CBB', 'NBA', 'Tennis']),
    E('Live vs the market', 'Every flagged pick, live and paper, judged out of sample.',
      ['Close value and ROI with 95% ranges clustered by game day, and a one-sided p on G - 1 df.',
       'Holm across the books (the unit that goes live or paper) and across rules with 8+ game days, family-wise .05.',
       "Win - chance is the win rate minus the stake's chance. Brier skill is against the close's chance at the pick's price.",
       'The venue is Novig, or Polymarket US after its taker fee (.095 p(1 - p)) when it pays more at the same line.',
       "Polymarket's flag-time price failed its pre-registered test as a signal (143 matched picks: slope t = .47). "
       'The filter kept worse picks, and it was a noisier forecast of the close than the posted price.'],
      'Predictions picks backtest', ['CFB', 'NFL', 'CBB', 'NBA', 'Tennis']),
    E('Nightly cap', 'The open picks on one ET date, across all sports, are scaled to at most 40% of bankroll.',
      ['Stake × min(1, 40 / total). Walk-forward, P(50% drawdown) is .12, compared to .27 uncapped at 1× edge.'],
      'Predictions picks (capped stake)', ['CFB', 'NFL', 'CBB', 'NBA', 'Tennis']),
    E('Close / CLV / Worth at close', 'Every pick is judged by the closing line first and by ROI second.',
      ['The close is the last snapshot before the start. CLV is the points the line moved our way.',
       'Worth at close (clvRet) is the return the pick was worth at the closing price, with its t.',
       'CLV needs far fewer bets than results to reach t = 2 (CBB 5+ points: about 228 compared to about 402).'],
      'Predictions picks, paper book, picks backtest', ['CFB', 'NFL', 'CBB', 'NBA', 'Tennis']),
    E('Bad open filter', 'Opening lines that mirror the close, or that move more than 6 sd (median-based), are dropped from the history.',
      ['The mirrored opens were home/away swaps (mostly 2025-26 CBB neutral sites), and they inflated the backtests.'],
      'All backtests', ['CFB', 'CBB', 'NBA']),
    E('Close predictor', 'It predicts the close from the open and the model gap (market softness b).',
      ['close - open = b × (model - open) + controls. b: CFB spread .10, CFB total .22, CBB .10, NBA spread .24, total .42.',
       'The break-even gap is where a -110 bet at the open breaks even at the predicted close.'],
      'Predictions picks backtest (close predictor)', ['CFB', 'CBB', 'NBA']),
    E('Totals recentring', 'The model total minus the mean gap between model and line over the slate and the season\'s last 100 games.',
      ['It keeps the totals picks from being a bet on the league\'s scoring level. Used in CFB, NBA and CBB.'],
      'Predictions picks', ['CFB', 'CBB', 'NBA']),
    E('Paper book', 'The posted picks, graded at the posted line, price and Kelly %, compounding.',
      ['It is identical to the picks tab, and it was reset on Oct 28 2026. No real money.'],
      'Predictions paper book tab', ['CFB', 'NFL', 'CBB', 'NBA', 'Tennis']),
    E('Rule monitor (CUSUM)', 'A live switch that stops a losing pick rule until it is refit.',
      ['A rule is judged after 50+ picks, by game day, with each day over 1 + (n - 1) rho (rho is the within-slate correlation of close value on held-out picks).',
       'It stops if the CUSUM around zero, S = max(0, S - clvRet / sd - .25), reaches 10, or if the CUSUM of the log likelihood ratio (no edge against the stakes\' edge) reaches ln 99.',
       'The last-300 clustered t (se floored at iid) is shown, but it doesn\'t stop a rule.'],
      'Predictions picks backtest (rule monitor), game models tab', ['CFB', 'NFL', 'CBB', 'NBA', 'Tennis']),
    E('Rule drift test (SPRT)', 'A sequential test of each rule\'s live close value against its backtest.',
      ['H1 is the backtest edge × TIMING and H0 is 0, with game days deflated by the within-slate correlation of close value. A rule pauses at 19:1 for no edge, and is confirmed at 19:1 for the edge.',
       'It takes about 250 (NBA totals) to 430 (CBB, CFB totals) bets to stop a rule with no edge.'],
      'Predictions picks backtest (new rules)', ['CFB', 'NFL', 'CBB', 'NBA', 'Tennis']),
    E('Growth / DD 25/50', 'Held-out log growth a season at the close, and the chance of a 25% or 50% fall from the peak.',
      ['Resampled from the walk-forward picks. Full Kelly accepts a high drawdown risk over long seasons.'],
      'Predictions picks backtest', ['CFB', 'NFL', 'CBB', 'NBA']),
    E('NFL props', 'One prop per player per game, at full Kelly on Novig prices, with the week scaled to a budget.',
      ['P(over) comes from the projection\'s shape by decile, shrunk .414. Held out 2025-26: 3,732 bets at 55.3%, t = 3.1 at -110.',
       'The weekly budget is 50% of bankroll until about 300 props are graded.'],
      'Predictions NFL fantasy (props), picks', ['NFL']),
    E('Tennis picks', 'The model\'s side when it differs from the Novig no-vig price by 4+ points of win chance.',
      ['Calibrated chance = no-vig + .5 × k toward the model (k .25 logits). The cap is 2% a bet.',
       'Tour-level main draws, tuned on 2025 and held out on 2026: 1,935 picks, +4.5% worth at close (t = 19).'],
      'Predictions picks, game table', ['Tennis']),
    E('Moneyline board / flip', 'Every game whose model winner is priced -200 to +200, or is the market underdog (a flip).',
      ['It is display only, and it isn\'t a pick rule. The held-out flip record across all sports is +1.2%, t = .6.'],
      'Predictions picks tab', ['CFB', 'NFL', 'CBB', 'NBA', 'NHL']),
    E('Not picked', 'The markets that were tested and are off, because they did not beat the close.',
      ['NHL (ML and totals), soccer (1X2, O/U 2.5, MLS, props), CS2 (no free closing odds) and NBA/NHL props.',
       'Their game projections still show, and Kelly % reads off.'],
      'Predictions game table', ['NHL', 'Soccer', 'CS2', 'NBA']),
    E("Major Pick'Em (CS2)", "The Valve Major Pick'Em picks with the best chance at each coin tier.",
      ['The coin has 11 challenges (Silver 4, Gold 8, Diamond 11). 5 are free and 6 take skill: 5+ of 10 in each Swiss stage, and 2 QF / 1 SF / the final in the bracket.',
       'Stage picks are two 3-0, two 0-3 and six 3-1 or 3-2 (exact record). They are made once the stage field and round 1 are known.',
       "A stage's picks only move that stage's chance, so every tier wants the highest P(5+ correct), which isn't the same as the most expected correct.",
       'P(5+) comes from joint stage sims (Valve pairing, Buchholz, Bo1 / Bo3, with team strength drawn once per sim, sd .45 logit).',
       'The search takes the exact max-expected set, then hill-climbs on P(5+), scored on a second set of sims. The bracket maximizes P(all 3).',
       'Held out since Jul 2025 over 15 Swiss stages, the predicted pass rate was 47% and the actual was 47% (seed chalk 40%, VRS 47%).',
       'Mean correct was 4.00, compared to 4.33 for chalk (t = -0.96), so there is no reliable edge over chalk in Swiss stages.',
       'Max P(5+) and max expected correct pick the same set in 21 of 25 stages. Where they differ, it is under 1 point of pass chance.',
       'In 12 held-out brackets it got 1.92 of 3 bracket challenges, compared to 1.42 for chalk and 1.50 for VRS.'],
      "Counter-Strike page, pick'em tab", ['CS2']),
]})

# ---------------------------------------------------------------- drafts & mocks
sections.append({'id': 'drafts', 'title': 'Drafts and mocks', 'entries': [
    E('Three mocks', 'Predictive, blended and conviction mock drafts for the NFL, NBA and NHL drafts.',
      ['Predictive is a projection of the real draft, from consensus boards plus the model (CFB board weight .75-.85, backtested).',
       'Conviction is the model board (FV before the consensus blend) plus team fit.',
       'Blended puts each slot at the geometric mean of the two xPicks. Predictive and conviction grade each other.'],
      'mock draft group on CFB, CBB, hockey prospects pages', ['CFB', 'CBB', 'Hockey']),
    E('xPick', 'Expected pick, a geometric blend of the consensus average rank and the rank by our draft value.',
      ['The market weight is .55 + .3 × sqrt(boards / 9). Unranked prospects get .65 at 1.3× the boards\' depth.',
       'A player past the last pick is projected undrafted (UDFA signings tab).'],
      'CFB mocks, udfa signings', ['CFB']),
    E('Team needs and pick rule', 'Teams pick on -ln(xPick) + need weight × need.',
      ['Need comes from the whole NFL position room: rookie-deal draft capital or salary, cut for age and expiring deals.',
       'There are penalties for doubling up, a set QB and position runs. The QB premium at the top of the draft decays by pick.'],
      'CFB mocks (pick reports)', ['CFB']),
    E('Trades', 'Projected trades: the NFL on Massey-Thaler pick values, and the NBA on a Trade% for each pick. Real traded picks come from Wikipedia.',
      ['There are trades in every round (5, 7, 6, 5, 5, 2, 1 a round), and next-year picks are worth .48 of a mid-round pick.',
       'A solid tag is a traded pick, and a dashed tag is a projected trade.',
       f"NBA Trade% is the chance a pick changes hands on draft night, from ln pick, its square, round 2 and ln picks the holder has, "
       f"fit on Wikipedia draft pages {_NT['drafts'][0]}-{_NT['drafts'][1]}, where {100 * _NT['rate']:.0f}% of picks were traded. Held out by draft, "
       f"log loss is {_NT['held']['ll']:.4f}, compared to {_NT['held']['llSlot']:.4f} for slot only (t = {_NT['held']['tSlot']:.1f}, {_NT['held']['wonSlot']}/{_NT['held']['of']}) and {_NT['held']['llFlat']:.4f} flat.",
       f"The NBA dashed tag goes on the likeliest picks in a round, as many as the expected count ({_NT['perRound']['R1']['expected']:.1f} in R1, {_NT['perRound']['R2']['expected']:.1f} in R2).",
       f"An NBA trade partner failed held out (top-3 hit {100 * _NT['partner']['top3']:.0f}%, compared to {100 * _NT['partner']['top3Uniform']:.0f}% uniform, t = {_NT['partner']['t']:.1f}), so no partner is named. "
       f"A value chart fit on NBA trades failed against Massey-Thaler ({_NT['curve']['n']} pure-pick deals {_NT['curve']['drafts'][0]}-{_NT['curve']['drafts'][1]}: |ln value ratio| {_NT['curve']['err']:.3f} compared to {_NT['curve']['errMT']:.3f}, t = {_NT['curve']['t']:.1f}, {_NT['curve']['won']}/{_NT['curve']['of']})."],
      'CFB and CBB mocks', ['CFB', 'CBB']),
    E('Reach / value', 'A pick the other mock takes 2.5×+ and 16+ picks later (reach) or earlier (value).',
      ['It is on the site table only. The GFX drops the chips.'],
      'Mock tables', ['CFB']),
    E('Mock sims', 'Simulated drafts give each prospect\'s pick range.',
      ['CFB: Gumbel pick noise by round (.40 / .525 / .625), 200 sims. CBB: a June board shock with sd 1.05 / .90 / .40 by days left.',
       'NBA lottery and NHL order: simulated standings × lottery odds, for P(#1).'],
      'Mocks (Range, Sims), lottery tab', ['CFB', 'CBB', 'NBA', 'Hockey']),
    E('Draft order', 'The order comes from projected standings (NFL tiebreakers in full) and the current pick owners.',
      ['The NFL order uses the sim\'s expected slot, the NHL uses projected points and Tankathon owners, and the NBA uses lottery sims.'],
      'Mock drafts', ['CFB', 'CBB', 'Hockey']),
    E('CBB mock inputs', 'A consensus of 2027 boards (.5 median rank + .5 mean), and conviction on slot plus the college line.',
      ['xXPM is the expected NBA peak XPM against the average drafted player, given slot and college line.',
       'Entrants come from Dec% draws, with an FV 40+ rule for the pool.'],
      'CBB mocks', ['CBB']),
    E('xSlot (hockey)', 'The draft slot a board rank points to.',
      ['An October board regresses toward the middle by June (Central Scouting January ranks against June slot).'],
      'Hockey prospects board', ['Hockey']),
]})

# ---------------------------------------------------------------- data & names
sections.append({'id': 'data', 'title': 'Data and names', 'entries': [
    E('Odds', 'Polymarket US (after its .095 p(1 - p) taker fee) is the price source. Novig fills the gaps, and DraftKings through ESPN is last.',
      ['A 50/50 side costs about .529 all in (-112). It is free, needs no key, and is paper only.',
       'Odds are snapshotted every 30 min, 13-04 UTC, plus 08 and 11 UTC.'],
      'Predictions; game cards', ['CFB', 'NFL', 'CBB', 'NBA', 'NHL', 'Soccer', 'Tennis']),
    E('Refresh cadence', 'The scheduled builds by sport, in season.',
      ['The CFB board runs about 3× daily (Aug-Jan), the NFL about 3× daily plus the Sunday game windows (Sep-Feb), and CBB 3× daily (Nov-Apr).',
       'NBA, NHL, soccer and tennis run 2× daily, CS2 every 4 h, and the soccer and tennis prospects daily.',
       'Picks refresh every 2 h and on every odds snapshot.'],
      'Window status bars (updated date)', ALLP + ['CS2']),
    E('Freshness / stale tag', 'Each window shows the date of its data, and a feed past its limit is tagged stale.',
      ['In season a feed is stale past 36 h, and in the off season past 10-14 days.'],
      'Every window status bar, ARKBOARD hub', ALLP + ['CS2']),
    E('Name matching', 'One shared matcher joins sources by player name in Python, Node and the browser.',
      ['It prefers a stable id (ESPN, Barttorvik pid, gsis) when both sides have one.',
       'An alias file covers the spellings the rules miss and common nicknames. A match still checks team and position.'],
      'Every board that joins sources', ALLP),
    E('Held out / LOSO / LOCO', 'The out-of-sample checks used across the site.',
      ['Held out means seasons that were never used to choose terms. LOSO is leave one season out, and LOCO is leave one class out.',
       'Prospect fits hold out whole players, classes, birth cohorts or birth years, so a player\'s rows stay together.'],
      'Model tabs', ALLP),
    E('Portal era rule', 'Transfer and roster models train only on NIL-era data (July 2021 on).',
      [],
      'CFB Transfer%, team builder, CBB roster terms', ['CFB', 'CBB']),
    E('ARKLIST', 'My hand-picked players, one list for each sport.',
      ['It is not a model output.'],
      'ARKLIST tab on each page; ARKLIST page', ALLP),
]})

# ---------------------------------------------------------------- FV tables
hk = ld('data/hockey.json')
sp = ld('data/soccer_prospects.json')
tf = ld('data/tennis_prospects_fit.json')
tp = ld('data/tennis_prospects.json')
cbb = ld('data/cbb.json')
cfb = ld('data/cfb.json')
fvd = ld('data/fv_dist.json')
scale = ld('data/fv_scale.json')['boards']


def pct(c, n):
    if c == 0:
        return 'none live'
    p = 100 * c / n
    ps = '<0.01%' if p < 0.01 else (f'{p:.2f}%' if p < 1 else f'{p:.1f}%')
    return f'{c:,} of {n:,} ({ps})'


def held(sc):
    out = {}
    for b in sc['bands']:
        o = {x['t']: x['real'] for x in b['odds']}
        lab = f"{b['lo']}+" if b['hi'] is None else f"{b['lo']}-{b['hi']}"
        out[b['lo']] = f"{lab}: {b['pred']} -> {b['real']} (n {b['n']}, 50+ {round(100 * o[50])}%)"
    return out


def knot(b, name):
    s = scale[b]
    return f"{name}: the headline is the mean up to {s['K']:.1f}, then a straight line to 80 at {s['T']:.1f} (an 80 about once every 5 seasons)."


fv_tables = []

# all boards at a glance (fvglance)
hkc = {str(c[0]): c[1] for c in hk['fit']['cuts']}
hper = {'80': '1 in 4 classes', '75': '1 in 2 classes', '70': '#1 / class', '65': 'top 2 / class', '60': 'top 5 / class',
        '55': 'top 10 / class', '50': 'top 20 / class', '45': 'top 30 / class', '40': 'top 45 / class'}
sper = {'80': '#1 / 2 birth years', '75': '#1 / birth year', '70': 'top 3 / birth year', '65': 'top 8 / birth year',
        '60': 'top 20 / birth year', '55': 'top 45 / birth year', '50': 'top 90 / birth year (big-five regular)',
        '45': 'top 150 / birth year', '40': 'top 250 / birth year (top-flight regular)'}
gl = [('80', 'generational', '5+ time All-Pro', '7+ All-NBA teams', 'top 5 overall'),
      ('70', 'star', '2-time All-Pro', '3+ All-NBA teams', 'top 10 overall'),
      ('60', 'plus', 'Pro Bowler', '2+ All-Star', 'All-Star / #3 SP'),
      ('55', 'above average', '6+ seasons starting', 'above-avg starter', 'above-average regular'),
      ('50', 'average', '4+ seasons starting', 'average starter', 'average regular'),
      ('45', 'below average', '2+ seasons starting', 'low-end starter', 'low-end regular / platoon'),
      ('40', 'bench', 'rotational', 'end of rotation', 'bench'),
      ('30', 'organizational', 'camp body', 'two-way / fringe', 'up and down'),
      ('20', 'non-pro', 'non-NFL', 'G-League', 'organizational')]
xlo = {str(r['fv']): r['xpmLo'] for r in cbb['fvTable']}
rows = []
for f, tier, fb, bb, mlb in gl:
    if xlo.get(f) is not None: bb = f"{bb}, {xlo[f]:.1f}+ peak XPM"
    h = {'30': 'some NHL games', '20': 'no NHL games'}.get(f) or f"{hper[f]}, {hkc[f]:.2f}+ peak WAR"
    s = {'30': 'some senior value', '20': 'no senior value'}.get(f) or sper[f]
    rows.append([f, tier, fb, bb, h, s, mlb])
fv_tables.append({'board': 'All boards: the 20-80 scale', 'note': 'The tier labels for each sport, as on the ARKBOARD hub (fv at a glance). Each board keeps its own ladder.',
                  'cols': ['FV', 'tier', 'football', 'basketball', 'hockey', 'soccer', 'baseball'], 'rows': rows})

# CFB / NFL
cd = cfb['dist']['all']
ncfb = sum(cd.values())
ge = lambda t: sum(c for f, c in cd.items() if int(f) >= t)
hc = held(fvd['cfb']['scorecard'])
cfb_rows = [
    ('80', '5+ time All-Pro (generational)', '~1', '1.04 / 0.47', 'No. 1 pick'),
    ('75', '3+ time All-Pro', '~1', '0.89 / 0.29', 'top 2 pick'),
    ('70', '2-time All-Pro', '~3', '0.67 / 0.23', 'top 5 pick'),
    ('65', 'All-Pro or 3+ Pro Bowls', '~7', '0.49 / 0.17', 'top 10 pick'),
    ('60', 'Pro Bowler', '~16', '0.40 / 0.13', '1st round'),
    ('55', '6+ seasons as a starter', '~25', '0.31 / 0.10', 'late 1st / 2nd round'),
    ('50', '4+ seasons as a starter', '~32', '0.19 / 0.07', 'rounds 2-3'),
    ('45', '2+ seasons as a starter', '~43', '0.09 / 0.05', 'rounds 3-4'),
    ('40', 'rotation, 48+ games', '~64', '0 / 0.02', 'rounds 4-6'),
    ('35', 'backup, 16+ games', '~98', '0 / 0.01', 'late round'),
    ('30', 'drafted / camp roster', '~150', '0 / 0', 'late round / UDFA'),
    ('20', 'non-NFL', '-', '- / 0', '-')]
rows = []
for f, m, pc, war, dv in cfb_rows:
    fi = int(f)
    rows.append([f, m, pc, pct(ge(fi), ncfb) if fi > 20 else 'all', war, dv, hc.get(fi, '-') if fi < 65 else (hc[65] if fi == 65 else '-')])
fv_tables.append({'board': 'CFB / NFL prospects',
                  'note': f'The outcome is the NFL career, from the 2012-18 drafts. Per class is the players in the band in a draft class, and pct is the share of the live FBS+FCS board '
                          f'({ncfb:,} graded) at that FV or higher. {knot("cfb", "Stretch")}',
                  'cols': ['FV', 'meaning', 'per class', 'pct', 'NFL WAR prime / a year', 'draft value', 'held out: graded -> reached'],
                  'rows': rows})

# CBB / NBA
cbbrows = ld('static/data/cbb-all.json')
ci = cbbrows['cols'].index('fv')
cv = [r[ci] for r in cbbrows['rows'] if isinstance(r[ci], (int, float))]
hb = held(fvd['cbb']['scorecard'])
ANCH = {80: '7+ All-NBA', 75: '5+ All-NBA', 70: '3+ All-NBA', 65: 'All-NBA', 60: '2+ All-Star',
        55: 'All-Star or 6+ seasons as a starter', 50: '4+ seasons as a starter', 45: '2+ seasons as a starter',
        40: 'rotation, 3+ seasons', 35: 'bench, 100+ games', 30: 'reached the NBA', 20: 'non-NBA'}
rows = []
for r in cbb['fvTable']:
    f = r['fv']
    if r['xpmLo'] is None:
        xr = f"below {r['xpmHi']:+.1f}"
    elif r['xpmHi'] is None:
        xr = f"{r['xpmLo']:+.1f} and up"
    else:
        xr = f"{r['xpmLo']:+.1f} to {r['xpmHi']:+.1f}"
    meaning = f"{ANCH[f]}; most common: {r['role']} ({round(100 * r['roleShare'])}%)"
    perc = f"{r['perClass']:.2f}" if r['perClass'] < 10 else f"{r['perClass']:.0f}"
    perb = '-' if r['perBoard'] is None else (f"{r['perBoard']:.1f}" if r['perBoard'] < 10 else f"{r['perBoard']:.0f}")
    pk = f"median pick {r['medPick']}, {round(100 * r['drafted'])}% drafted"
    c = sum(1 for x in cv if x >= f)
    rows.append([str(f), meaning, perc, pct(c, len(cv)) if f > 20 else 'all', xr, perb, pk, hb.get(f, '-')])
fv_tables.append({'board': 'CBB / NBA prospects',
                  'note': f'The outcome is peak NBA XPM, for careers ending 2008-16. Per class is the careers in the band in a college class, and per board is the players '
                          f'on a preseason board who reach that FV or better. pct is the share of the live D-I board ({len(cv):,}). {knot("cbb", "Stretch")}',
                  'cols': ['FV', 'meaning (rarity anchor; most common role in band)', 'per class', 'pct', 'peak XPM', 'per board', 'draft slot', 'held out: graded -> reached'],
                  'rows': rows})

# Hockey
cal = {c['band']: c for c in hk['fit']['calib']}
per_class_picks = hk['fit']['picks'] / (hk['fit']['classes'][1] - hk['fit']['classes'][0] + 1)
rank_in_class = {'80': .25, '75': .5, '70': 1, '65': 2, '60': 5, '55': 10, '50': 20, '45': 30, '40': 45}
hlab = {'80': 'one in four classes', '75': 'one in two classes', '70': 'the best of a class', '65': 'top 2 of a class',
        '60': 'top 5 of a class', '55': 'top 10', '50': 'top 20 (NHL regular)', '45': 'top 30', '40': 'top 45 (NHL career)'}
hbv = [r.get('fv') for r in hk['board'] if r.get('fv') is not None]
hpv = [r.get('fv') for r in hk['pipe'] if r.get('fv') is not None]
hlive = lambda t: f"{sum(1 for x in hbv if x >= t)} / {sum(1 for x in hpv if x >= t)}"
rows = []
for f, w in hk['fit']['cuts']:
    k = str(f)
    c = cal.get(f)
    hcell = f"{f}-{f + 4}: {c['pred']} -> {c['real']} (n {c['n']}, NHL {round(100 * c['nhl'])}%)" if c else '-'
    rows.append([k, f'{w:.2f}+ peak WAR a season', hlab[k], f"top {100 * rank_in_class[k] / per_class_picks:.1f}% of picks", hlive(f), hcell])
for f, m, b in [(30, 'some NHL games', 30), (20, 'no NHL games', 20)]:
    c = cal[b]
    rows.append([str(f), m, '-', '-', hlive(f) if f > 20 else f"{len(hbv)} / {len(hpv)}", f"{b}-{b + 4}: {c['pred']} -> {c['real']} (n {c['n']}, NHL {round(100 * c['nhl'])}%)"])
fv_tables.append({'board': 'Hockey prospects (NHL)',
                  'note': f"The outcome is the mean of the best three WAR seasons in the first 7 after the draft, and goalies are graded by the same rarity among goalies. "
                          f"pct is the share of a draft class (~{per_class_picks:.0f} picks, 2008-19). live is the 2027 board / drafted prospects at that FV or higher. "
                          f"{knot('hockey', 'Stretch')}",
                  'cols': ['FV', 'meaning', 'per class', 'pct', 'live', 'held out: graded band -> reached'],
                  'rows': rows})

# Soccer
sb = sp['board']
pool = sp['pool']
sv = [r.get('fv') for r in sb if r.get('fv') is not None]
scal = {c['band']: c for c in sp['fit']['calib']}
slab = {'80': 'one in two birth years', '75': 'the best of a birth year', '70': 'top 3 of a birth year', '65': 'top 8',
        '60': 'top 20', '55': 'top 45', '50': 'top 90 (big-five regular)', '45': 'top 150', '40': 'top 250 (top-flight regular)'}
rows = []
for f, g, d, m, fw in sp['fit']['cuts']:
    k = str(f)
    c = sum(1 for x in sv if x >= f)
    cc = scal.get(f)
    hcell = f"{f}-{f + 4}: {cc['pred']} -> {cc['real']} (n {cc['n']}, 50+ {round(100 * cc['p50'])}%)" if cc else '-'
    rows.append([k, f'peak GAR a season GK {g:.1f} / D {d:.1f} / M {m:.1f} / F {fw:.1f}', slab[k] + ' at the position', pct(c, pool), hcell])
for f, m in [(30, 'some senior value'), (20, 'no senior value')]:
    cc = scal[f]
    c = sum(1 for x in sv if x >= f)
    rows.append([str(f), m, '-', pct(c, pool) if f > 20 else 'all', f"{f}-{f + 4}: {cc['pred']} -> {cc['real']} (n {cc['n']}, 50+ {round(100 * cc['p50'])}%)"])
fv_tables.append({'board': 'Soccer prospects',
                  'note': f"The outcome is the best three GAR seasons at ages 22-26, by rarity within a birth year and position group (players who were 22 in 2013-21). "
                          f"pct is the share of the live pool of {pool:,} under-22s. {knot('soccer', 'Stretch')}",
                  'cols': ['FV', 'meaning', 'per class', 'pct', 'held out: graded band -> reached'],
                  'rows': rows})

# Tennis
tlab = {'80': 'one in eight birth years', '75': 'one in four birth years', '70': 'one in two birth years', '65': 'the best of a birth year',
        '60': 'top 2 of a birth year', '55': 'top 4', '50': 'top 7', '45': 'top 10', '40': 'top 13 (top-100 regular)'}
for tour, TL in [('atp', 'ATP'), ('wta', 'WTA')]:
    fit = tf[tour]
    cr = {str(a): b for a, b in fit['cutRank']}
    tv = [r.get('fv') for r in tp[tour]['board'] if r.get('fv') is not None]
    tpool = tp[tour]['pool']
    ht = held(fit['scorecard'])
    rows = []
    for f, share in fit['cuts']:
        k = str(f)
        c = sum(1 for x in tv if x >= f)
        hcell = ht.get(f) if f < 65 else (ht[65] if f == 65 else '-')
        rows.append([k, f'peak like year-end No. {cr[k]}', tlab[k], pct(c, tpool), hcell or '-'])
    rows.append(['30', 'some value: peak between No. 200 and No. 100', '-', pct(sum(1 for x in tv if x >= 30), tpool), ht.get(30, '-')])
    rows.append(['20', 'never above No. 200 at ages 22-28', '-', 'all', ht.get(20, '-')])
    fv_tables.append({'board': f'Tennis prospects ({TL})',
                      'note': f"The outcome is the best three seasons at ages 22-28 of year-end points above No. 200, as a share of the top 100's mean, "
                              f"for births 1979-97. pct is the share of the live pool of {tpool} under-22s. {knot(tour, 'Stretch')}",
                      'cols': ['FV', 'meaning', 'per class', 'pct', 'held out: graded -> reached'],
                      'rows': rows})

# MLB (hand-graded, FanGraphs tiers)
mlb = [('80', 'top 5 overall', '#1 (top 1-3 arm)', '-', '7.0+'), ('75', 'top 5-10', '#1/2', '-', '6.0'),
       ('70', 'top 10 overall', '#2', '-', '5.0-7.0'), ('65', 'perennial All-Star', '#2/3', '-', '4.2'),
       ('60', 'All-Star', '#3', 'high closer', '3.4-4.9'), ('55', 'above-average regular', '#3/4', 'mid closer', '2.5-3.3'),
       ('50', 'average everyday player', '#4', 'low closer / high setup', '1.6-2.4'),
       ('45', 'low-end regular / platoon', '#4/5', 'low setup', '0.8-1.5'),
       ('40', 'bench', 'back-end / spot starter', 'middle relief', '0.0-0.7'),
       ('35', 'emergency call-up', 'emergency call-up', 'emergency call-up', '~0'),
       ('30', 'up and down', 'up and down', 'up and down', 'below -0.1'),
       ('20', 'organizational', 'organizational', 'organizational', '-')]
fv_tables.append({'board': 'MLB prospects (hand-graded)',
                  'note': 'These are the FanGraphs primer tiers. The grades are by hand, so there is no model, live rarity or held-out check. WAR is per season at peak.',
                  'cols': ['FV', 'hitter', 'starting pitcher', 'reliever', 'WAR / season'],
                  'rows': [list(r) for r in mlb]})

# ---------------------------------------------------------------- added terms and lines (research/library_adds.json)
# Test write-ups that are not read from a fit file: new terms ("add"), lines added to a term ("append"), a term's body ("replace").
try:
    _adds = ld('research/library_adds.json')
except OSError:
    _adds = {}
_by = {e['term']: e for sec in sections for e in sec['entries']}
for _r in _adds.get('replace', []):
    _by[_r['term']]['body'] = list(_r['body'])
for _a in _adds.get('append', []):
    _by[_a['term']]['body'] += [x for x in _a['lines'] if x not in _by[_a['term']]['body']]
for _n in _adds.get('add', []):
    _ents = next(x for x in sections if x['id'] == _n['section'])['entries']
    _ents[:] = [e for e in _ents if e['term'] != _n['entry']['term']]
    _at = next((i + 1 for i, e in enumerate(_ents) if e['term'] == _n.get('after')), len(_ents))
    _ents.insert(_at, dict(_n['entry']))

# ---------------------------------------------------------------- abbreviations (data/terms.json)
# The site's term hovers (assets/js/terms.js) read data/terms.json. A label with no glossary term of its own links to its
# group's entry here, one line per label, so every hover has a Process entry behind it.
_terms = ld('data/terms.json')
_abbr = {}
for _k, _e in _terms['terms'].items():
    for _v in [_e] + list((_e.get('by') or {}).values()) + list(_e.get('when') or []):
        if _v.get('g') or (_v is _e and not _e.get('a')) or (_v is not _e and not (_v.get('n') or _v.get('a'))):
            continue
        _line = f"{_k}: {_v.get('n') or _e['n']}. {_v.get('d') or _e['d']}"
        _rows = _abbr.setdefault(_v.get('a') or _e.get('a'), [])
        if _line not in _rows:
            _rows.append(_line)
sections.append({'id': 'abbr', 'title': 'Abbreviations', 'entries': [
    E(_g['term'], _g['short'], sorted(_abbr.get(_id, []), key=str.lower), 'every table', _g['sports'])
    for _id, _g in _terms['groups'].items() if _abbr.get(_id)]})

lib = {'asof': '2026-11-02',
       'about': 'ARKBOARD Process: the definition and method for every metric and model, and the FV conversion chart for each board.',
       'sections': sections, 'fv_tables': fv_tables}

# ---------------------------------------------------------------- copy checks
bad = re.compile(r'\b(delve|robust|leverage|comprehensive|seamless|cutting-edge|unlock|empower|game-changer|elevate)\b', re.I)
problems = []


def chk(s, where):
    if '—' in s or '–' in s:
        problems.append(f'dash: {where}: {s}')
    if bad.search(s):
        problems.append(f'word: {where}: {s}')
    if re.search('[\U0001F300-\U0001FAFF☀-➿]', s):
        problems.append(f'emoji: {where}: {s}')


for sec in sections:
    for e in sec['entries']:
        for k in ('term', 'short', 'where'):
            chk(e[k], e['term'])
        for line in e['body']:
            chk(line, e['term'])
            if len(line) > 400:
                problems.append(f'long {len(line)}: {e["term"]}: {line}')
for t in fv_tables:
    chk(t['note'], t['board'])
    for r in t['rows']:
        assert len(r) == len(t['cols']), (t['board'], r)
        for c in r:
            chk(str(c), t['board'])
for p in problems:
    print(p)
# keep entries other scripts write into research/library.json (alltime_ref.py) or that were added there by hand
try:
    _old = json.load(open(OUT))
except (OSError, ValueError):
    _old = {'sections': []}
_mine = {e['term'] for sec in sections for e in sec['entries']} | {'CBB WAR / WAA', 'xBPM', 'DEC', 'DoR'}   # renamed terms: the old name is not carried over
for osec in _old.get('sections', []):
    sec = next((x for x in sections if x['id'] == osec['id']), None)
    if sec is None:
        continue
    sec['entries'] += [e for e in osec['entries'] if e['term'] not in _mine]
# coach terms in the recruit model (scripts/research/coach_loyalty_nov27): one line on the carried ARK lean entry, rewritten each run
_rl, _rb = _CL['recruits_cfb'], _CL['recruits_cbb']
_cl_line = (f'Coach terms (CFB, classes 2022-26 held out): a school whose head coach is gone after the recruit\'s senior fall is picked less (t = {_rl["R4 late"]["t"]:.1f}, '
            f'log loss {-_rl["base"]["ll"]:.3f} to {-_rl["R4 late"]["with"]["ll"]:.3f}). Head coach tenure passed alone (t = {_rl["R2 hc_ten"]["t"]:.1f}) but not in every class on top of that. '
            f'Failed: a first-year coach (t = {_rl["R1 newhc"]["t"]:.1f}), a coach who came from a school on his list (t = {_rl["R3 hc_from_list"]["t"]:.1f}), and all four in CBB (t = {min(_rb[k]["t"] for k in ("R1 newhc", "R2 hc_ten", "R3 hc_from_list", "R4 late")):.1f} to {max(_rb[k]["t"] for k in ("R1 newhc", "R2 hc_ten", "R3 hc_from_list", "R4 late")):.1f}).')
for sec in sections:
    for e in sec['entries']:
        if e['term'] == 'ARK lean (recruit commitment)':
            e['body'] = [b for b in e['body'] if not b.startswith('Coach terms')] + [_cl_line]
json.dump(lib, open(OUT, 'w'), indent=1, ensure_ascii=False)
print('sections', len(sections), 'entries', sum(len(s['entries']) for s in sections), 'tables', len(fv_tables), 'problems', len(problems))
for s in sections:
    print(' ', s['id'], len(s['entries']))
