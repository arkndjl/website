# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Measured height and weight from several listings: each source corrected for its bias and weighted by 1 / its error
variance (a precision-weighted mean), so a combine measurement outweighs a roster listing, which outweighs a high
school listing. Shared by the boards; each sport passes its own source table.

    est = blend([(value, bias, sd, label), ...])  ->  {'v': estimate, 'sd': its error SD, 'mix': {label: weight share}}

College basketball (CBB, barefoot inches and pounds; fit Nov 3 2026, research in /mnt/project-files/fv/frame-nov03/cbb/):
  height   NBA combine barefoot (truth, sd .25); school roster listing as ESPN and Barttorvik show it, which agree 88% of
           the time so they count as one source (+1.17 in over barefoot, sd .72; 1,017 combine testers 2004-26, recency
           -weighted listings over seasons beat the last one, .735 vs .750); Tankathon (after a combine it shows the
           combine in shoes: +1.25, sd 0 on 20 of 2026; else a listing, sd .75); On3 high school listing (+1.06, sd .95)
  weight   NBA combine (sd 3, plus 6 lb a year since it: the 2026 testers back in school list +6.4 by fall, sd 7.3);
           ESPN roster (sd 7.3); Tankathon (sd 7.3); On3 high school listing + 16 lb (the board's ESPN listings run
           15-17 lb over each recruit's On3 weight in every class year, sd 14)
"""

CBB_HT = {'combine': (0.0, 0.25), 'roster': (1.17, 0.72), 'tankathon': (1.2, 0.75), 'hs': (1.06, 0.95)}
CBB_WT = {'combine': (0.0, 3.0), 'roster': (0.0, 7.3), 'tankathon': (0.0, 7.3), 'hs': (-16.0, 14.0)}
COMBINE_WT_DRIFT = 6.0   # lb of error SD per year since the combine


def blend(obs):
    """obs: [(value, bias, sd, label)]: value = truth + bias + error(sd). Precision-weighted mean of value - bias."""
    obs = [o for o in obs if o[0] is not None and o[2] and o[2] > 0]
    if not obs: return None
    w = [1 / o[2] ** 2 for o in obs]
    W = sum(w)
    v = sum(wi * (o[0] - o[1]) for wi, o in zip(w, obs)) / W
    mix = {}
    for wi, o in zip(w, obs): mix[o[3]] = mix.get(o[3], 0) + wi / W
    return {'v': v, 'sd': (1 / W) ** 0.5, 'mix': mix}


def cbb(espn_ht=None, bt_ht=None, tk_ht=None, hs_ht=None, comb_ht=None, espn_wt=None, tk_wt=None, hs_wt=None,
        comb_wt=None, comb_years=0.0):
    """CBB measured height (barefoot inches) and weight (lb). Roster = mean of ESPN and Barttorvik when both list him."""
    ros = [x for x in (espn_ht, bt_ht) if x]
    ht = blend([(comb_ht, *CBB_HT['combine'], 'combine'), (sum(ros) / len(ros) if ros else None, *CBB_HT['roster'], 'roster'),
                (None if comb_ht else tk_ht, *CBB_HT['tankathon'], 'Tankathon'), (hs_ht, *CBB_HT['hs'], 'high school')])
    cb = CBB_WT['combine']
    wt = blend([(comb_wt, cb[0], (cb[1] ** 2 + (COMBINE_WT_DRIFT * comb_years) ** 2) ** 0.5, 'combine'),
                (espn_wt, *CBB_WT['roster'], 'roster'), (None if comb_wt else tk_wt, *CBB_WT['tankathon'], 'Tankathon'),
                (hs_wt, *CBB_WT['hs'], 'high school')])
    return ht, wt


def fmt_in(x):
    """76.75 -> 6' 4.75\" (quarter inches)"""
    q = round(x * 4) / 4
    ft, inch = int(q // 12), q - 12 * int(q // 12)
    s = f'{inch:.2f}'.rstrip('0').rstrip('.')
    return f"{ft}' {s}\""
