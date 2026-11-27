"""급여목록 '비고'·'전일' 열 값 분포, 앞자리 0 소실 여부, 문자 시작 EDI 목록. 읽기 전용.
사용: set -a; source .env; set +a; PYTHONPATH=. .venv/bin/python scripts/probe_edi_note_cols.py
"""
import asyncio, os, warnings
from collections import Counter
from pathlib import Path
import asyncpg, pandas as pd
from dotenv import dotenv_values
warnings.filterwarnings("ignore")

async def main():
    f = next(Path("data/raw").glob("약제급여목록*.xlsx"))
    raw = pd.read_excel(f, header=None, dtype=str)
    hr = next(i for i, r in raw.head(15).iterrows() if "제품코드" in " ".join(r.dropna().astype(str)))
    df = pd.read_excel(f, header=hr, dtype=str); df.columns = [str(c).strip().replace("\n", "") for c in df.columns]
    cc = next(c for c in df.columns if "제품코드" in c)
    print("[엑셀] 제품코드 길이:", dict(Counter(df[cc].str.strip().str.len())))
    for col in ("전일", "비고", "투여", "식약분류"):
        if col in df.columns:
            s = df[col].fillna("(비어 있음)").str.replace(r"\s+", " ", regex=True)
            print(f"[엑셀] {col} 상위 15:", dict(Counter(s).most_common(15)))
    xs = set(df[cc].str.strip())
    env = dotenv_values(".env"); g = lambda k, d=None: os.getenv(k) or env.get(k) or d
    con = await asyncpg.connect(host=g("POSTGRES_HOST","localhost"), port=int(g("POSTGRES_PORT","5432")),
        database=g("POSTGRES_DB"), user=g("POSTGRES_USER"), password=g("POSTGRES_PASSWORD"))
    try:
        rows = await con.fetch("""SELECT m.item_seq, m.item_name, m.entp_name, m.edi_code, left(m.item_permit_date,4) y
            FROM medicines m WHERE m.cancel_name='정상' AND coalesce(m.edi_code,'')<>''
            AND NOT EXISTS (SELECT 1 FROM v_item_ingredients v WHERE v.item_seq=m.item_seq)""")
    finally:
        await con.close()
    z = [r for r in rows if r["edi_code"].strip().startswith("0")]
    print(f"\n[앞자리 0 점검] 0으로 시작하는 EDI {len(z)}건 중, 앞 0을 떼면 엑셀에 있는 코드: {sum(1 for r in z if r['edi_code'].strip().lstrip('0') in {x.lstrip('0') for x in xs})}건")
    L = [r for r in rows if not r["edi_code"].strip()[:1].isdigit()]
    print(f"\n[문자로 시작하는 EDI] {len(L)}건 (앞 40건)")
    for r in L[:40]:
        print(" ", r["edi_code"], "|", r["item_seq"], "|", r["item_name"], "|", r["entp_name"], "|", r["y"])
asyncio.run(main())
