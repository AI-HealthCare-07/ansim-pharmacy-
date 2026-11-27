"""코드 없는 2,141건이 급여목록 월별 판(8~11월)에 어떻게 나타나는지. 읽기 전용.
사용: set -a; source .env; set +a; PYTHONPATH=. .venv/bin/python scripts/probe_edi_months.py
"""
import asyncio, os, re, warnings
from collections import Counter, defaultdict
from pathlib import Path
import asyncpg, pandas as pd
from dotenv import dotenv_values
warnings.filterwarnings("ignore")

def load(path):
    raw = pd.read_excel(path, header=None, dtype=str)
    hr = next(i for i, r in raw.head(15).iterrows() if "제품코드" in " ".join(r.dropna().astype(str)))
    df = pd.read_excel(path, header=hr, dtype=str); df.columns = [str(c).strip().replace("\n", "") for c in df.columns]
    cc = next(c for c in df.columns if "제품코드" in c)
    df[cc] = df[cc].str.strip()
    return df, cc

async def main():
    books = {}
    for f in sorted(Path("data/raw").glob("약제급여목록*.xlsx")):
        m = re.search(r"\((\d{4})\.(\d+)\.(\d+)\.\)", f.name)
        books[f"{m.group(1)}.{int(m.group(2)):02d}"] = load(f)
    months = sorted(books)
    for k in months: print(f"[{k}] 행 {len(books[k][0]):,} 열 {list(books[k][0].columns)}")
    codes = {k: set(books[k][0][books[k][1]]) for k in months}
    last, prev = months[-1], months[-2]
    print(f"\n[전체] {prev} 에 있고 {last} 에 없는 코드: {len(codes[prev]-codes[last]):,} | {last} 에 새로 생긴 코드: {len(codes[last]-codes[prev]):,}")
    env = dotenv_values(".env"); g = lambda k, d=None: os.getenv(k) or env.get(k) or d
    con = await asyncpg.connect(host=g("POSTGRES_HOST","localhost"), port=int(g("POSTGRES_PORT","5432")),
        database=g("POSTGRES_DB"), user=g("POSTGRES_USER"), password=g("POSTGRES_PASSWORD"))
    try:
        rows = await con.fetch("""SELECT m.item_seq, m.edi_code FROM medicines m
            WHERE m.cancel_name='정상' AND coalesce(m.edi_code,'')<>''
            AND NOT EXISTS (SELECT 1 FROM v_item_ingredients v WHERE v.item_seq=m.item_seq)""")
        allm = await con.fetchval("SELECT count(*) FROM medicines m WHERE m.cancel_name='정상' AND coalesce(m.edi_code,'')<>''")
        gone = await con.fetchval("SELECT count(*) FROM medicines m WHERE m.edi_code = ANY($1::text[])", list(codes[prev]-codes[last]))
    finally:
        await con.close()
    print(f"[전체] 위 '{prev}에만 있던 코드' 중 medicines에 edi_code로 있는 약: {gone:,}건")
    pat = Counter(); ing = defaultdict(set); note = Counter()
    for r in rows:
        e = r["edi_code"].strip()
        p = "".join("O" if e in codes[k] else "-" for k in months)
        pat[p] += 1
        for k in months:
            df, cc = books[k]
            if e in codes[k]:
                v = df.loc[df[cc] == e, "주성분코드"].iloc[0]; ing[e].add(v)
                if k == prev and "비고" in df.columns:
                    b = df.loc[df[cc] == e, "비고"].iloc[0]; note[b if isinstance(b, str) else "(비어 있음)"] += 1
    print(f"\n[판별 패턴] 순서 = {months} (O=있음, -=없음), 대상 {len(rows):,}건")
    for p, n in pat.most_common(): print(" ", p, f"{n:,}")
    multi = sum(1 for e, s in ing.items() if len(s) > 1)
    print(f"\n[주성분코드 일관성] 어느 판에든 나타난 {len(ing):,}개 EDI 중 판마다 주성분코드가 다른 것: {multi}건")
    print(f"[{prev} 판 비고] 이 약들의 비고 분포:", dict(note.most_common(10)))
asyncio.run(main())
