"""reliability of the role drivers: same player, next season's snapshot value vs this one (career-to-date drivers share
earlier seasons, so this is an upper bound), plus raw correlation with outcome FV inside the role"""
import json
import os
import pickle
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import soccer_pos_drivers as D  # noqa: E402

R = pickle.load(open(os.path.join(D.CACHE, 'rows.pkl'), 'rb'))
Z = R[(10, 24)]
out = {}
for c, role, base in [('GK_ga', 'GK', 'ga_oo'), ('CB_ga', 'CB', 'ga_oo'), ('FB_gd', 'FB', 'gd_oo'), ('DM_ga', 'DM', 'ga_oo'),
                      ('CM_gd', 'CM', 'gd_oo'), ('AM_gi', 'AM', 'gi_sh'), ('W_gi', 'W', 'gi_sh'), ('ST_g', 'ST', 'g_sh'),
                      ('FB_a90', 'FB', 'ast90'), ('ST_gf', 'ST', 'gf_oo')]:
    z = Z[Z.role.eq(role)]
    # season-only value: drivers over the latest season are not stored, so use the change between snapshots
    a = z[['pid', 't', base, 'gar_td', 'fv_out']]
    b = a.assign(t=a.t - 1)
    m = a.merge(b, on=['pid', 't'], suffixes=('', '_n'))
    m = m[(m[base] != 0) & (m[base + '_n'] != 0)]
    out[c] = {'n': int((z[base] != 0).sum()), 'sd': round(float(z[base].std()), 3),
              'next_snap_r': round(float(np.corrcoef(m[base], m[base + '_n'])[0, 1]), 2) if len(m) > 30 else None,
              'r_fv_out': round(float(np.corrcoef(z[base], z.fv_out)[0, 1]), 3),
              'r_gar_td': round(float(np.corrcoef(z[base], z.gar_td)[0, 1]), 3),
              'r_oo_weight': round(float(np.corrcoef(z[base], z.oo_w)[0, 1]), 3)}
    print(c, out[c])
json.dump(out, open(os.path.join(D.ROOT, 'data', 'soccer_pos_drivers_diag.json'), 'w'), indent=1)
