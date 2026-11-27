"""Haiku 없이 match_document를 시험한다(약 목록을 직접 넣음). document_items에 실제로 저장한다.

사용법(프로젝트 폴더에서):
  set -a; source .env; set +a
  PYTHONPATH=. .venv/bin/python scripts/try_match_doc.py <document_id>
"""
import asyncio
import json
import sys

from tortoise import Tortoise

from app.core.db.databases import TORTOISE_ORM
from app.services.matching import match_document

DRUGS = [
    {"name": "지르텍정 10mg", "edi_code": None, "dose_per_time": 1, "dose_unit": "정", "times_per_day": 1, "total_days": 7, "timing": "취침 전"},
    {"name": "아목시실린캡슐500mg", "edi_code": None, "dose_per_time": 1, "dose_unit": "캡슐", "times_per_day": 3, "total_days": 7, "timing": "식후 30분"},
    {"name": "타이레놀정500mg", "edi_code": None, "dose_per_time": 1, "dose_unit": "정", "times_per_day": 3, "total_days": 3, "timing": "식후 30분"},
    {"name": "코러스레보설피리드정", "edi_code": "647200730", "dose_per_time": 1, "dose_unit": "정", "times_per_day": 3, "total_days": 7, "timing": "식전 30분"},
]


async def main(doc_id):
    await Tortoise.init(config=TORTOISE_ORM)
    rows = await match_document(doc_id, DRUGS)
    for r in rows:
        cands = r["match_candidates"] or []
        print(f"\n[{r['line_no']}] {r['drug_name']}  EDI={r['edi_code']}  방식={r['match_method']}  점수={r['match_score']}"
              f"  확인={r['confirmed_by']}  선택={r['matched_item_seq']}  확인필요={r['needs_review']}")
        for c in cands:
            print(f"     - {c['score']:.3f} {c['item_name'][:26]}  성분코드={'O' if c['has_ingr_code'] else 'X'}  EDI일치={c['edi_match']}")
    await Tortoise.close_connections()


asyncio.run(main(sys.argv[1]))
