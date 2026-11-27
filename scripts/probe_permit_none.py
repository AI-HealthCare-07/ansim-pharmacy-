"""허가 상세 API가 빈 응답을 준 약(none)을 다시 확인한다. 읽기 전용(DB 안 씀, API만 호출, 약 15~20회).
1) 같은 요청 재시도로 일시 실패 여부  2) 같은 약이 목록 API에도 없는지  3) 2024년 이후 약 중 받아진 약(대조군)
사용: set -a; source .env; set +a; PYTHONPATH=. .venv/bin/python scripts/probe_permit_none.py
"""
import json, os, ssl, sys, time
from pathlib import Path
import certifi, httpx
from dotenv import dotenv_values

CTX = ssl.create_default_context(cafile=certifi.where())
BASE = "https://apis.data.go.kr/1471000/DrugPrdtPrmsnInfoService08/"
OPS = ["getDrugPrdtPrmsnDtlInq08", "getDrugPrdtPrmsnInq08", "getDrugPrdtPrmsnInq07"]
env = dotenv_values(Path(".env"))
key = os.getenv("DATA_GO_KR_API_KEY") or env.get("DATA_GO_KR_API_KEY")
none, ok24 = [], []
for l in open("data/raw/permit_detail/detail.jsonl", encoding="utf-8"):
    d = json.loads(l)
    if not d.get("row"):
        none.append(d["_item_seq"])
    elif d["_item_seq"].startswith("2024"):
        ok24.append(d["_item_seq"])
sample = [("빈응답", s) for s in (none[:3] + none[-3:] + [x for x in none if x.startswith("2026")][:2])] + \
         [("대조(받아진 2024)", s) for s in ok24[:3]]
with httpx.AsyncClient if False else httpx.Client(timeout=60, verify=CTX) as c:
    for tag, s in sample:
        for op in OPS:
            try:
                r = c.get(BASE + op, params={"serviceKey": key, "type": "json", "item_seq": s})
                b = r.json().get("body", {}) if r.status_code == 200 else {}
                it = b.get("items") or []
                it = it.get("item") if isinstance(it, dict) else it
                nm = (it[0].get("item", it[0]) if it else {}).get("ITEM_NAME") if it else None
                print(f"{tag:12} {s} {op:26} HTTP{r.status_code} total={b.get('totalCount')} name={nm}")
            except Exception as e:
                print(f"{tag:12} {s} {op:26} 오류 {type(e).__name__}")
            time.sleep(0.3)
