"""Build the 2011-19 signee outcome rows (scripts/cfb_recruit_retarget.py dataset()) and save them for the backup test."""
import gzip, json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import cfb_recruit_retarget as T
data, how, capfit = T.dataset()
print('rows', len(data), 'drafted', sum(r['drafted'] for r in data), dict(how))
out = [{k: v for k, v in r.items() if not isinstance(v, (list, dict, set))} for r in data]
json.dump({'capital': capfit, 'rows': out, 'fields': sorted(data[0].keys())}, gzip.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'rows.json.gz'), 'wt'))
