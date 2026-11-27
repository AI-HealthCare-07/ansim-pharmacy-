"""심평원 상병마스터 CSV를 kcd_codes에 적재한다(전체 교체).

사용:  set -a; source .env; set +a
       PYTHONPATH=. .venv/bin/python scripts/load_kcd_codes.py [CSV경로]
- 인코딩 CP949. 같은 코드가 여러 줄이면 첫 줄(대표명)만 쓴다.
- 코드는 소수점을 지우고 대문자로 저장한다.
"""
from __future__ import annotations

import asyncio
import glob
import os
import sys

import asyncpg
import pandas as pd

DEFAULT = "docs/ref/law/*상병마스터*.csv"


def clean(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    return s or None


def small(v):
    s = clean(v)
    return int(s) if s and s.isdigit() else None


async def main(path: str) -> None:
    df = pd.read_csv(path, dtype=str, encoding="cp949")
    df["code"] = df["상병기호"].map(lambda x: (clean(x) or "").replace(".", "").replace(" ", "").upper())
    df = df[df["code"] != ""]
    total = len(df)
    df = df.drop_duplicates("code", keep="first")
    src = os.path.basename(path)
    rows = [(r["code"], clean(r["한글명"]) or "", clean(r["영문명"]), clean(r["완전코드구분"]),
             clean(r["주상병사용구분"]), clean(r["법정감염병구분"]), clean(r["성별구분"]),
             small(r["상한연령"]), small(r["하한연령"]), clean(r["양한방구분"]), src)
            for _, r in df.iterrows()]
    conn = await asyncpg.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"), port=int(os.getenv("POSTGRES_PORT", "5432")),
        database=os.getenv("POSTGRES_DB"), user=os.getenv("POSTGRES_USER"), password=os.getenv("POSTGRES_PASSWORD"))
    try:
        async with conn.transaction():
            await conn.execute("TRUNCATE kcd_codes")
            await conn.copy_records_to_table(
                "kcd_codes", records=rows,
                columns=["sick_cd", "name_ko", "name_en", "complete_flag", "main_flag", "cdd_class", "sex_flag",
                         "max_age", "min_age", "oriental_type", "source_label"])
        n = await conn.fetchval("SELECT count(*) FROM kcd_codes")
    finally:
        await conn.close()
    print(f"원본 {total}줄 → 코드 {len(rows)}개 적재, 테이블 {n}행 ({src})")


if __name__ == "__main__":
    files = sys.argv[1:] or sorted(glob.glob(DEFAULT))
    if not files:
        sys.exit("CSV를 찾지 못했어요: " + DEFAULT)
    asyncio.run(main(files[-1]))
