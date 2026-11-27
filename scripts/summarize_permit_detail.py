"""data/raw/permit_detail/detail.jsonl 집계(읽기 전용, DB·API 호출 없음).
사용: PYTHONPATH=. .venv/bin/python scripts/summarize_permit_detail.py"""
import json
from pathlib import Path
from collections import Counter

P = Path("data/raw/permit_detail/detail.jsonl")
c = Counter(); n = 0
for line in P.open(encoding="utf-8"):
    r = json.loads(line); n += 1
    row = r.get("row")
    if not row:
        c["API에 없음(totalCount=%s)" % r.get("_total")] += 1
        continue
    c["받음"] += 1
    for k in ["EE_DOC_DATA", "UD_DOC_DATA", "NB_DOC_DATA", "MAIN_ITEM_INGR", "ATC_CODE", "EDI_CODE",
              "EE_DOC_ID", "UD_DOC_ID", "NB_DOC_ID"]:
        if (row.get(k) or "").strip():
            c[k + " 있음"] += 1
    if all((row.get(k) or "").strip() for k in ["EE_DOC_DATA", "UD_DOC_DATA", "NB_DOC_DATA"]):
        c["효능·용법·주의사항 3종 모두 있음"] += 1
print("조회한 건수:", n)
for k, v in sorted(c.items()):
    print(f"  {k}: {v} ({100*v/n:.1f}%)")
