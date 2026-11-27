"""문서ID가 비어 있는 약이 DUR 품목정보 API에서 어떻게 나오는지 시험한다. DB는 읽기만 한다(쓰기 없음).
사용: PYTHONPATH=. .venv/bin/python scripts/diag_nodoc_api.py [표본수=40]
확인하는 것: (1) 품목정보 API 전체 건수 (2) 빈 약의 표본을 itemSeq로 조회했을 때
  0건(API에 없음) / 1건이고 문서ID 있음(우리 적재가 빠진 것) / 1건이지만 문서ID 비어 있음(원천이 비어 있는 것).
"""
import asyncio, os, sys
from pathlib import Path
import asyncpg, httpx
from dotenv import dotenv_values

URL = "http://apis.data.go.kr/1471000/DURPrdlstInfoService03/getDurPrdlstInfoList03"


async def get(c, key, **p):
    r = await c.get(URL, params={"serviceKey": key, "type": "json", **p})
    j = r.json().get("body", {})
    items = j.get("items") or []
    if isinstance(items, dict):
        items = items.get("item") or []
    if isinstance(items, dict):
        items = [items]
    return int(j.get("totalCount") or 0), items


async def main(n):
    env = dotenv_values(Path(".env"))
    key = os.getenv("DATA_GO_KR_API_KEY") or env.get("DATA_GO_KR_API_KEY")
    if not key:
        sys.exit("DATA_GO_KR_API_KEY가 없어요")
    con = await asyncpg.connect(host=os.getenv("POSTGRES_HOST", env.get("POSTGRES_HOST", "localhost")),
                                port=int(os.getenv("POSTGRES_PORT", env.get("POSTGRES_PORT", "5432"))),
                                database=os.getenv("POSTGRES_DB", env.get("POSTGRES_DB")),
                                user=os.getenv("POSTGRES_USER", env.get("POSTGRES_USER")),
                                password=os.getenv("POSTGRES_PASSWORD", env.get("POSTGRES_PASSWORD")))
    seqs = [r["item_seq"] for r in await con.fetch(
        "SELECT item_seq FROM medicines WHERE cancel_name='정상' AND coalesce(nb_doc_id,'')='' ORDER BY random() LIMIT $1", n)]
    have = await con.fetchval("SELECT count(*) FROM medicines WHERE cancel_name='정상' AND coalesce(nb_doc_id,'')<>''")
    await con.close()
    async with httpx.AsyncClient(timeout=30) as c:
        total, _ = await get(c, key, pageNo=1, numOfRows=1)
        print(f"품목정보 API 전체 건수: {total:,}건 (우리 DB 정상 약 중 문서ID 있는 약: {have:,}건)")
        res = {"API에 없음": 0, "있음+문서ID있음(적재 누락)": 0, "있음+문서ID비어있음(원천 공백)": 0, "호출 실패": 0}
        ex = {k: [] for k in res}
        for s in seqs:
            try:
                cnt, items = await get(c, key, pageNo=1, numOfRows=1, itemSeq=s)
            except Exception:
                res["호출 실패"] += 1; continue
            if cnt == 0 or not items:
                k = "API에 없음"
            else:
                it = items[0]
                k = "있음+문서ID있음(적재 누락)" if (it.get("NB_DOC_ID") or it.get("EE_DOC_ID") or it.get("UD_DOC_ID")) else "있음+문서ID비어있음(원천 공백)"
            res[k] += 1
            if len(ex[k]) < 3: ex[k].append(s)
            await asyncio.sleep(0.1)
    print(f"\n표본 {len(seqs)}건 결과")
    for k, v in res.items():
        print(f"  {k}: {v}  예시 {ex[k]}")


asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 40))
