# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""The recruit-index history (scripts/cfb_recruit_retarget.py dataset: ESPN 2011-19 signees with NFL outcomes), pickled
once for the tests in this folder."""
import os
import pickle
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE))))
sys.path.insert(0, os.path.dirname(HERE))
PK = os.path.join(os.path.dirname(HERE), '..', '.cache', 'recruit', 'retarget_rows.pkl')


def load():
    if os.path.exists(PK): return pickle.load(open(PK, 'rb'))
    import cfb_recruit_retarget as T
    data, how, cap = T.dataset()
    pickle.dump(data, open(PK, 'wb'))
    return data


if __name__ == '__main__':
    from collections import Counter
    d = load()
    print(len(d), Counter(r['year'] for r in d))
    print('rated', sum(r['grade'] >= 60 for r in d), 'g70', sum(r['grade'] >= 70 for r in d), 'g75', sum(r['grade'] >= 75 for r in d), 'comp', sum(bool(r.get('comp')) for r in d))
    print({k: d[0][k] for k in d[0] if k != 'offers'})
