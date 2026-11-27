"""급여목록 엑셀에 없는 EDI(코드 없는 약 중 medicines.edi_code 가 있는 2,141건 등)가 왜 없는지 단서를 찾는다. 읽기 전용.
1) data/raw 의 모든 엑셀 파일·시트 구조  2) 같은 EDI가 다른 판·다른 시트(삭제 등)에 있는지  3) 약 특성(허가연도·전문/일반·EDI 첫 글자)
사용: set -a; source .env; set +a; PYTHONPATH=. .venv/bin/python scripts/probe_edi_missing_reason.py
"""
import asyncio, os
from collections import Counter
from pathlib import Path
import asyncpg, pandas as pd
from dotenv import dotenv_values


def read_codes(path):
    """파일의 모든 시트에서 제품코드 열을 찾아 {시트이름: 코드집합}과 열 목록을 돌려준다."""
    out, info = {}, {}
    xl = pd.ExcelFile(path)
    for sh in xl.sheet_names:
        pv = xl.parse(sh, nrows=15, header=None, dtype=str)
        hr = None
        for i, r in pv.iterrows():
            if "제품코드" in " ".join(r.dropna().astype(str)):
                hr = i; break
        if hr is None:
            info[sh] = "제품코드 열 없음"; continue
        df = xl.parse(sh, header=hr, dtype=str); df.columns = [str(c).strip().replace("\n", "") for c in df.columns]
        cc = next(c for c in df.columns if "제품코드" in c)
        out[sh] = set(df[cc].dropna().astype(str).str.strip())
        info[sh] = f"{len(out[sh]):,}개 | 열: {list(df.columns)[:10]}"
    return out, info


async def main():
    env = dotenv_values(Path(".env"))
    g = lambda k, d=None: os.getenv(k) or env.get(k) or d
    files = sorted(list(Path("data/raw").glob("*.xlsx")) + list(Path("data/raw").glob("*.xls")))
    print("엑셀 파일:", [f.name for f in files])
    books = {}
    for f in files:
        try:
            books[f.name], info = read_codes(f)
            print(f"\n[{f.name}]")
            for sh, t in info.items():
                print("  시트", sh, "→", t)
        except Exception as e:
            print(f.name, "읽기 실패:", type(e).__name__)
    con = await asyncpg.connect(host=g("POSTGRES_HOST", "localhost"), port=int(g("POSTGRES_PORT", "5432")),
                                database=g("POSTGRES_DB"), user=g("POSTGRES_USER"), password=g("POSTGRES_PASSWORD"))
    try:
        rows = await con.fetch("""
          SELECT m.item_seq, m.edi_code, m.etc_otc_name, left(m.item_permit_date,4) AS y
            FROM medicines m
           WHERE m.cancel_name='정상' AND coalesce(m.edi_code,'')<>''
             AND NOT EXISTS (SELECT 1 FROM v_item_ingredients v WHERE v.item_seq=m.item_seq)""")
    finally:
        await con.close()
    print(f"\nEDI 있고 주성분코드 없는 정상 약: {len(rows):,}건")
    edis = [(r["edi_code"] or "").strip() for r in rows]
    for name, sheets in books.items():
        for sh, codes in sheets.items():
            print(f"  [{name} / {sh}]에 있는 EDI: {sum(1 for e in edis if e in codes):,}건")
    print("  EDI 첫 글자:", dict(Counter(e[:1] for e in edis).most_common(8)))
    print("  허가연도(상위):", dict(Counter(r['y'] for r in rows).most_common(8)))
    print("  전문/일반:", dict(Counter(r['etc_otc_name'] or '(없음)' for r in rows)))

asyncio.run(main())
