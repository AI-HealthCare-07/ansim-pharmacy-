"""DUR 품목별 금기 API 시험 호출(읽기 전용). DB와 파일을 바꾸지 않고, 키는 출력하지 않는다.

사용: PYTHONPATH=. .venv/bin/python scripts/try_dur_taboo_api.py [품목기준코드 ...]
기본 시험 품목: 타이레놀정500밀리그람(202106092), 코러스레보설피리드정(200403778) - 둘 다 성분코드가 없는 약.
기능 이름은 기억에 기댄 후보라서, 404/오류가 나면 공공데이터포털 15059486 페이지의 기능 목록으로 고친다.
"""
import asyncio
import os
import sys
from pathlib import Path

import httpx
from dotenv import dotenv_values

BASE = "http://apis.data.go.kr/1471000/DURPrdlstInfoService03/"
OPS = {
    "품목기본": "getDurPrdlstInfoList03",
    "병용금기": "getUsjntTabooInfoList03",
    "특정연령대금기": "getSpcifyAgrdeTabooInfoList03",
    "임부금기": "getPwnmTabooInfoList03",
    "용량주의": "getCpctyAtentInfoList03",
    "투여기간주의": "getMdctnPdAtentInfoList03",
    "노인주의": "getOdsnAtentInfoList03",
    "효능군중복": "getEfcyDplctInfoList03",
}


async def main(seqs):
    key = os.getenv("DATA_GO_KR_API_KEY") or dotenv_values(Path(".env")).get("DATA_GO_KR_API_KEY")
    if not key:
        sys.exit("DATA_GO_KR_API_KEY가 없어요")
    async with httpx.AsyncClient(timeout=30) as c:
        for seq in seqs:
            print(f"\n##### 품목기준코드 {seq}")
            for label, op in OPS.items():
                try:
                    r = await c.get(BASE + op, params={"serviceKey": key, "pageNo": 1, "numOfRows": 3,
                                                       "itemSeq": seq, "type": "json"})
                    body = r.text.replace(key, "***")
                    try:
                        j = r.json().get("body", {})
                        n = j.get("totalCount")
                        items = j.get("items") or []
                        first = items[0] if isinstance(items, list) and items else None
                        print(f"[{label}] HTTP {r.status_code} 건수={n}  첫 항목 키={list(first)[:14] if isinstance(first, dict) else first}")
                    except Exception:
                        print(f"[{label}] HTTP {r.status_code}  {body[:160]!r}")
                except Exception as e:
                    print(f"[{label}] 호출 실패: {type(e).__name__}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or ["202106092", "200403778"]))
