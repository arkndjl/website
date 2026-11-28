"""Past Ko-fi payments (before the webhook) for the donate page's top donors board.

python3 scripts/kofi_past.py <ko-fi export.csv> [--public "Name One,Name Two"] [--all-public]

Reads Ko-fi's transaction CSV export (Ko-fi > Transactions > Export) and writes static/data/kofi-past.json, which
worker/site.js merges into /api/supporters by transaction id (new payments come from the webhook).
The repo is public, so a payer's name is written only when the CSV marks the payment public, or the name is passed
with --public, or --all-public is given. Every other row is written with no name and shows as anonymous.
Columns are found by name, case-insensitive, so small changes to Ko-fi's export still read.
"""
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "static/data/kofi-past.json"


def col(head, *names):
    low = {h.strip().lower(): h for h in head}
    for n in names:
        for h, orig in low.items():
            if h == n or h.startswith(n):
                return orig
    return None


def num(v):
    try:
        return float(str(v).replace("$", "").replace(",", "").strip())
    except ValueError:
        return None


def when(v):
    v = (v or "").strip()
    for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(v[:19], f).replace(tzinfo=timezone.utc).timestamp() * 1000)
        except ValueError:
            pass
    return 0


def main(argv):
    if not argv or argv[0].startswith("-"):
        sys.exit(__doc__)
    pub_names = set()
    all_pub = "--all-public" in argv
    if "--public" in argv:
        pub_names = {n.strip().lower() for n in argv[argv.index("--public") + 1].split(",") if n.strip()}
    with open(argv[0], newline="", encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        head = rd.fieldnames or []
        c_name = col(head, "from", "name", "supporter")
        c_amt = col(head, "received", "amount", "given")
        c_cur = col(head, "currency")
        c_type = col(head, "transactiontype", "transaction type", "type", "item")
        c_id = col(head, "transactionid", "transaction id", "reference", "id")
        c_t = col(head, "datetime", "date", "timestamp", "time")
        c_pub = col(head, "is_public", "ispublic", "public")
        if not (c_name and c_amt):
            sys.exit(f"no name/amount column in {head}")
        rows = []
        for r in rd:
            a = num(r.get(c_amt))
            if not a or a <= 0:
                continue
            name = (r.get(c_name) or "").strip()[:40]
            flag = str(r.get(c_pub, "")).strip().lower() in ("true", "1", "yes") if c_pub else False
            pub = 1 if name and (all_pub or flag or name.lower() in pub_names) else 0
            t = when(r.get(c_t)) if c_t else 0
            tid = (r.get(c_id) or "").strip() if c_id else ""
            if not tid:
                tid = "csv-" + hashlib.sha1(f"{name}|{a}|{t}".encode()).hexdigest()[:16]
            rows.append({
                "id": tid[:80],
                # private rows keep only a hash of the name, so one person's gifts still add up without the name in the repo
                "name": name if pub else ("h:" + hashlib.sha1(name.lower().encode()).hexdigest()[:12] if name else ""),
                "amount": round(a, 2),
                "currency": ((r.get(c_cur) or "USD").strip() or "USD")[:8],
                "pub": pub,
                "t": t,
                "type": ((r.get(c_type) or "") if c_type else "").strip()[:20],
            })
    OUT.write_text(json.dumps({"rows": rows}, separators=(",", ":")) + "\n")
    print(f"{len(rows)} payments, {sum(x['pub'] for x in rows)} public -> {OUT.relative_to(OUT.parent.parent.parent)}")


if __name__ == "__main__":
    main(sys.argv[1:])
