"""식약처 DUR 품목정보 API(DURPrdlstInfoService03) 기능별 전체 목록 수집. 읽기 전용 호출, 키는 출력하지 않는다.

기본은 건수만 센다(기능당 1회 호출). 내려받으려면 --download.
  PYTHONPATH=. .venv/bin/python scripts/fetch_dur_api.py                 # 건수만
  PYTHONPATH=. .venv/bin/python scripts/fetch_dur_api.py --download      # 전체 내려받기(이어받기 가능)
저장: data/raw/dur_api/<기능>.jsonl (한 줄에 한 항목, 응답 그대로). data/는 git에서 제외돼 있다.
하루 호출 한도(개발계정 10,000건)를 넘지 않도록 --budget(기본 7000)에서 멈추고, 다음 날 같은 명령으로 이어받는다.
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import dotenv_values

BASE = "http://apis.data.go.kr/1471000/DURPrdlstInfoService03/"
OPS = {
    "병용금기": "getUsjntTabooInfoList03", "특정연령대금기": "getSpcifyAgrdeTabooInfoList03",
    "임부금기": "getPwnmTabooInfoList03", "용량주의": "getCpctyAtentInfoList03",
    "투여기간주의": "getMdctnPdAtentInfoList03", "노인주의": "getOdsnAtentInfoList03",
    "효능군중복": "getEfcyDplctInfoList03", "서방정분할주의": "getSeobangjeongPartitnAtentInfoList03",
}
OUT = Path("data/raw/dur_api")
ROWS = 100


async def call(c, key, op, page, rows):
    for attempt in range(4):
        try:
            r = await c.get(BASE + op, params={"serviceKey": key, "pageNo": page, "numOfRows": rows, "type": "json"})
            if r.status_code == 200:
                return r.json().get("body", {})
        except Exception:
            pass
        await asyncio.sleep(1.5 * (attempt + 1))
    return None


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--budget", type=int, default=7000, help="이번 실행에서 쓸 최대 호출 수")
    ap.add_argument("--ops", default="", help="쉼표로 기능 이름 선택(기본 전체)")
    a = ap.parse_args()
    key = os.getenv("DATA_GO_KR_API_KEY") or dotenv_values(".env").get("DATA_GO_KR_API_KEY")
    if not key:
        sys.exit("DATA_GO_KR_API_KEY가 없어요")
    ops = {k: v for k, v in OPS.items() if not a.ops or k in a.ops.split(",")}
    OUT.mkdir(parents=True, exist_ok=True)
    used = 0
    async with httpx.AsyncClient(timeout=40) as c:
        for label, op in ops.items():
            b = await call(c, key, op, 1, 1)
            used += 1
            total = int(b["totalCount"]) if b and b.get("totalCount") is not None else None
            pages = -(-total // ROWS) if total is not None else None
            print(f"[{label}] 전체 {total}건 → {pages}회 호출 필요")
            if not a.download or not total:
                continue
            f = OUT / f"{label}.jsonl"
            done_pages = sum(1 for _ in f.open(encoding="utf-8")) // ROWS if f.exists() else 0  # 이어받기: 100줄 = 1쪽
            if f.exists() and done_pages * ROWS != sum(1 for _ in f.open(encoding="utf-8")) and total > done_pages * ROWS:
                lines = f.read_text(encoding="utf-8").splitlines()[: done_pages * ROWS]  # 마지막 쪽이 덜 써졌으면 버린다
                f.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
            with f.open("a", encoding="utf-8") as w:
                for page in range(done_pages + 1, pages + 1):
                    if used >= a.budget:
                        print(f"  호출 한도({a.budget}) 도달. 같은 명령으로 이어받으세요. 현재 {label} {page - 1}/{pages}쪽")
                        return
                    b = await call(c, key, op, page, ROWS)
                    used += 1
                    if not b:
                        print(f"  {label} {page}쪽 실패. 같은 명령으로 이어받으세요.")
                        return
                    items = b.get("items") or []
                    for it in items:
                        w.write(json.dumps(it, ensure_ascii=False) + "\n")
                    w.flush()
                    await asyncio.sleep(0.1)
            print(f"  {label} 저장 완료: {f}")
    print(f"이번 실행 호출 수: {used}")


if __name__ == "__main__":
    asyncio.run(main())
