"""문서ID가 빈 정상 약(DUR 품목정보에 없는 약)의 허가 상세정보를 받아 파일로 저장한다.
DB는 읽기만 한다(쓰기 없음). 저장: data/raw/permit_detail/detail.jsonl (이어받기 가능)
사용: PYTHONPATH=. .venv/bin/python scripts/fetch_permit_detail.py [--budget 8000] [--limit N]
받는 것: EE/UD/NB_DOC_DATA(효능·용법·주의사항 본문), MAIN_ITEM_INGR, ATC_CODE, EDI_CODE 등 상세 전체.
"""
import argparse, asyncio, json, os, sys
from pathlib import Path
import asyncpg, httpx
from dotenv import dotenv_values

URL = "https://apis.data.go.kr/1471000/DrugPrdtPrmsnInfoService08/getDrugPrdtPrmsnDtlInq08"
OUT = Path("data/raw/permit_detail/detail.jsonl")


async def main(budget, limit, retry_none):
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
        "SELECT item_seq FROM medicines WHERE cancel_name='정상' AND coalesce(nb_doc_id,'')='' ORDER BY item_seq")]
    await con.close()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if OUT.exists():
        for line in OUT.open(encoding="utf-8"):
            try:
                d = json.loads(line)
                if retry_none and not d.get("row"):
                    continue          # 빈 응답은 다시 시도 대상
                done.add(d["_item_seq"])
            except Exception:
                pass
    todo = [s for s in seqs if s not in done]
    if limit:
        todo = todo[:limit]
    todo = todo[:budget]
    print(f"대상 {len(seqs)}건, 이미 받음 {len(done)}건, 이번 호출 {len(todo)}건")
    sem = asyncio.Semaphore(5)
    stats = {"ok": 0, "none": 0, "err": 0, "quota": 0}
    stop = asyncio.Event()
    f = OUT.open("a", encoding="utf-8")
    async with httpx.AsyncClient(timeout=60) as c:
        async def one(s):
            async with sem:
                if stop.is_set():
                    return
                for _ in range(3):
                    try:
                        r = await c.get(URL, params={"serviceKey": key, "type": "json", "item_seq": s})
                        if r.status_code == 429:          # 일일 호출 한도 초과: 기록하지 않고 전체 중단
                            stats["quota"] += 1; stop.set(); return
                        if r.status_code != 200:
                            await asyncio.sleep(2); continue
                        b = r.json().get("body")
                        if b is None:                      # 정상 응답 형식이 아님: 기록하지 않음
                            await asyncio.sleep(2); continue
                        items = b.get("items") or []
                        if isinstance(items, dict):
                            items = items.get("item") or []
                        if isinstance(items, dict):
                            items = [items]
                        rec = {"_item_seq": s, "_total": int(b.get("totalCount") or 0),
                               "row": (items[0].get("item", items[0]) if items else None)}
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n"); f.flush()
                        stats["ok" if items else "none"] += 1
                        return
                    except Exception:
                        await asyncio.sleep(2)
                stats["err"] += 1
        await asyncio.gather(*(one(s) for s in todo))
    f.close()
    print("결과:", stats)
    if stats["quota"]:
        print("호출 한도(429) 초과로 중단했어요. 한도가 초기화된 뒤 --retry-none 으로 이어받으세요.")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=int, default=8000)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--retry-none", action="store_true", help="이전에 빈 응답(none)이던 약만 다시 시도")
    a = ap.parse_args()
    asyncio.run(main(a.budget, a.limit, a.retry_none))
