"""급여목록 엑셀 구조 점검 + EDI 있는 정상 약의 '주성분코드 있음 vs 없음' 분포 비교. 읽기 전용.
사용: set -a; source .env; set +a; PYTHONPATH=. .venv/bin/python scripts/probe_edi_baseline.py
"""
import asyncio, os, warnings
from collections import Counter
from pathlib import Path
import asyncpg, pandas as pd
from dotenv import dotenv_values
warnings.filterwarnings("ignore")

def dist(rows, key, n=8):
    c = Counter(key(r) for r in rows); t = sum(c.values()) or 1
    return {k: f"{v:,} ({v*100/t:.1f}%)" for k, v in c.most_common(n)}

async def main():
    f = next(Path("data/raw").glob("약제급여목록*.xlsx"))
    raw = pd.read_excel(f, header=None, dtype=str)
    hr = next(i for i, r in raw.head(15).iterrows() if "제품코드" in " ".join(r.dropna().astype(str)))
    df = pd.read_excel(f, header=hr, dtype=str); df.columns = [str(c).strip().replace("\n", "") for c in df.columns]
    cc = next(c for c in df.columns if "제품코드" in c)
    print("[엑셀] 전체 열:", list(df.columns))
    print(f"  행 {len(df):,} | 제품코드 있음 {df[cc].notna().sum():,} | 고유 {df[cc].nunique():,} | 중복행 {df[cc].notna().sum()-df[cc].nunique():,}")
    print("  제품코드 비어 있는 행 예:", df[df[cc].isna()].head(3).to_dict("records"))
    e = os.getenv; env = dotenv_values(".env"); g = lambda k, d=None: e(k) or env.get(k) or d
    con = await asyncpg.connect(host=g("POSTGRES_HOST","localhost"), port=int(g("POSTGRES_PORT","5432")),
        database=g("POSTGRES_DB"), user=g("POSTGRES_USER"), password=g("POSTGRES_PASSWORD"))
    try:
        rows = await con.fetch("""SELECT m.item_seq, m.edi_code, m.etc_otc_name, left(m.item_permit_date,4) y,
              EXISTS (SELECT 1 FROM v_item_ingredients v WHERE v.item_seq=m.item_seq) has_ing
              FROM medicines m WHERE m.cancel_name='정상' AND coalesce(m.edi_code,'')<>''""")
    finally:
        await con.close()
    A = [r for r in rows if r["has_ing"]]; B = [r for r in rows if not r["has_ing"]]
    print(f"\n[DB] EDI 있는 정상 약 {len(rows):,} = 주성분코드 있음 {len(A):,} + 없음 {len(B):,}")
    for nm, key in [("EDI 첫글자", lambda r: (r["edi_code"] or "")[:1]), ("EDI 길이", lambda r: len((r["edi_code"] or "").strip())),
                    ("허가연도", lambda r: r["y"]), ("전문/일반", lambda r: r["etc_otc_name"] or "(없음)")]:
        print(f"  {nm}\n    있음: {dist(A,key)}\n    없음: {dist(B,key)}")
    x = set(df[cc].dropna())
    print(f"\n[검산] 주성분코드 있음 중 엑셀에 코드 있음 {sum(1 for r in A if r['edi_code'].strip() in x):,}/{len(A):,}")
asyncio.run(main())
