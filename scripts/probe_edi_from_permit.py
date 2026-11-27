"""허가 상세의 EDI_CODE(식약처)를 심평원 약제급여목록 제품코드와 정확히 맞춰 보고, 코드 없는 약이 몇 건 풀리는지 센다.
읽기 전용(DB 쓰기 없음, 파일 쓰기 없음). 이름 비교 없음 — 코드 문자열 완전 일치만 센다.
사용: set -a; source .env; set +a; PYTHONPATH=. .venv/bin/python scripts/probe_edi_from_permit.py
"""
import asyncio, os, re
from collections import Counter
from pathlib import Path
import asyncpg, pandas as pd
from dotenv import dotenv_values


def find_excel(raw: Path) -> Path:
    c = list(raw.glob("*.xlsx")) + list(raw.glob("*.xls"))
    h = [f for f in c if any(k in f.name for k in ["급여", "상한", "약제", "목록", "2026"])]
    t = h if h else c
    if not t:
        raise SystemExit("data/raw 에 엑셀이 없어요")
    return sorted(t, key=lambda p: p.stat().st_mtime)[-1]


async def main():
    env = dotenv_values(Path(".env"))
    g = lambda k, d=None: os.getenv(k) or env.get(k) or d
    xp = find_excel(Path("data/raw")); print("엑셀:", xp.name)
    pv = pd.read_excel(xp, nrows=15, header=None, dtype=str)
    hr = 0
    for i, r in pv.iterrows():
        if "제품코드" in " ".join(r.dropna().astype(str)) and "주성분코드" in " ".join(r.dropna().astype(str)):
            hr = i; break
    df = pd.read_excel(xp, header=hr, dtype=str); df.columns = [str(c).strip().replace("\n", "") for c in df.columns]
    cc = next(c for c in df.columns if "제품코드" in c); ic = next(c for c in df.columns if "주성분코드" in c)
    df = df[[cc, ic]].dropna(); df[cc] = df[cc].str.strip(); df[ic] = df[ic].str.strip()
    e2i = df.drop_duplicates(subset=[cc]).set_index(cc)[ic].to_dict()
    print(f"급여목록 제품코드 {len(e2i):,}개")
    con = await asyncpg.connect(host=g("POSTGRES_HOST", "localhost"), port=int(g("POSTGRES_PORT", "5432")),
                                database=g("POSTGRES_DB"), user=g("POSTGRES_USER"), password=g("POSTGRES_PASSWORD"))
    try:
        rows = await con.fetch("""
          SELECT m.item_seq, coalesce(m.edi_code,'') AS med_edi, coalesce(d.edi_code,'') AS permit_edi
            FROM medicines m JOIN medicine_permit_detail d USING (item_seq)
           WHERE m.cancel_name='정상' AND NOT EXISTS (SELECT 1 FROM v_item_ingredients v WHERE v.item_seq=m.item_seq)""")
    finally:
        await con.close()
    print(f"허가 상세가 있는 코드 없는 정상 약: {len(rows):,}건")
    has = [r for r in rows if r["permit_edi"].strip()]
    print(f"  그중 허가 EDI_CODE 있음: {len(has):,}건")
    pat = Counter(("9자리" if re.fullmatch(r"[0-9A-Z]{9}", r["permit_edi"].strip()) else "다른형식") for r in has)
    print("  EDI 형식:", dict(pat))
    print("  다른형식 예:", [r["permit_edi"] for r in has if not re.fullmatch(r"[0-9A-Z]{9}", r["permit_edi"].strip())][:5])
    hit = [r for r in has if r["permit_edi"].strip() in e2i]
    print(f"  허가 EDI가 급여목록 제품코드와 정확히 일치: {len(hit):,}건")
    new = [r for r in hit if not r["med_edi"].strip()]
    print(f"    그중 DB(medicines)에 EDI가 비어 있던 약(새로 풀림): {len(new):,}건")
    print("  예:", [(r["item_seq"], r["permit_edi"], e2i[r["permit_edi"].strip()]) for r in hit[:5]])

asyncio.run(main())
