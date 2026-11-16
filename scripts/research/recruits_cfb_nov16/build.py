# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Rebuild the recruit index history rows (scripts/cfb_recruit_retarget.py dataset()) and pickle them for the tests."""
import os, pickle, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import cfb_recruit_fit as R
import cfb_recruit_retarget as T
data, how, cap = T.dataset()
print('rows', len(data), 'drafted', sum(r['drafted'] for r in data), dict(how))
pickle.dump((data, how, cap), open(os.path.join(R.CACHE, 'hist_nov16.pkl'), 'wb'))
