#!/usr/bin/env python3
"""Check that a rewritten JSON differs from git HEAD only in age fields (age, ax, ageEst).
    python3 scripts/research/frame_nov03/check_age_diff.py file...
"""
import json
import subprocess
import sys

AGE = {'age', 'ax', 'ageEst'}


def strip(o):
    if isinstance(o, dict):
        return {k: strip(v) for k, v in o.items() if k not in AGE}
    if isinstance(o, list):
        return [strip(v) for v in o]
    return o


for fn in sys.argv[1:]:
    old = json.loads(subprocess.run(['git', 'show', f'HEAD:{fn}'], capture_output=True, text=True, check=True).stdout)
    new = json.load(open(fn))
    print(fn, 'only age fields changed' if strip(old) == strip(new) else 'OTHER FIELDS CHANGED')
