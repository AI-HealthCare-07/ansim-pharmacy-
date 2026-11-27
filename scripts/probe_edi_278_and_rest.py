"""(A) 최근 급여목록에는 있으나 medicine_edi_codes에 행이 없는 EDI가 어느 약인지  (B) 교정·채움 후에도 주성분코드 없는 정상 약의 특성. 읽기 전용.
사용: set -a; source .env; set +a; PYTHONPATH=. .venv/bin/python scripts/probe_edi_278_and_rest.py
"""
import asyncio, csv, os, re, warnings
from collections import Counter
from pathlib import Path
import asyncpg, pandas as pd
from dotenv import dotenv_values
warnings.filterwarnings("ignore")

def latest_list():
    fs = []
    for f in Path("data/raw").glob("약제급여목록*.xlsx"):
        m = re.search(r"\((\d{4})\.(\d{1,2})\.(\d{1,2})\.\)", f.name)
        if m: fs.append((tuple(map(int, m.groups())), f))
    f = sorted(fs)[-1][1]
    raw = pd.read_excel(f, header=None, dtype=str, nrows=15)
    hr = next(i for i, r in raw.iterrows() if "제품코드" in " ".join(r.dropna().astype(str)))
    df = pd.read_excel(f, header=hr, dtype=str); df.columns = [str(c).strip().replace("\n", "") for c in df.columns]
    df["제품코드"] = df["제품코드"].str.strip()
    return f.name, df

def pct(c):
    t = sum(c.values()) or 1
    return {k: f"{v:,} ({v*100/t:.1f}%)" for k, v in c.most_common(8)}

async def main():
    name, df = latest_list()
    env = dotenv_values(".env"); g = lambda k, d=None: os.getenv(k) or env.get(k) or d
    con = await asyncpg.connect(host=g("POSTGRES_HOST","localhost"), port=int(g("POSTGRES_PORT","5432")),
        database=g("POSTGRES_DB"), user=g("POSTGRES_USER"), password=g("POSTGRES_PASSWORD"))
    try:
        have = {(r["edi_code"] or "").strip() for r in await con.fetch("SELECT edi_code FROM medicine_edi_codes")}
        miss = df[~df["제품코드"].isin(have)]
        print(f"[A] 최근 판({name})에는 있으나 medicine_edi_codes에 행이 없는 EDI: {len(miss):,}개")
        out, stat = [], Counter()
        for _, r in miss.iterrows():
            e = r["제품코드"]
            ms = await con.fetch("SELECT item_seq,item_name,cancel_name,edi_code FROM medicines WHERE edi_code LIKE '%'||$1||'%'", e)
            if not ms: stat["medicines에 없음"] += 1; out.append([e, r.get("제품명"), r.get("업체명"), r.get("주성분코드"), "", "", "", ""])
            for m in ms:
                multi = "복수코드" if len((m["edi_code"] or "").strip()) > 9 else "단일코드"
                stat[f"medicines에 있음/{m['cancel_name']}/{multi}"] += 1
                out.append([e, r.get("제품명"), r.get("업체명"), r.get("주성분코드"), m["item_seq"], m["item_name"], m["cancel_name"], m["edi_code"]])
        for k, v in stat.most_common(): print("  ", k, v)
        p = Path("docs/review/edi_278_261127.csv")
        with p.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f); w.writerow(["edi","list_product","list_company","list_main_ingr","item_seq","medicines_name","status","medicines_edi_code"]); w.writerows(out)
        print("  저장:", p)

        rows = await con.fetch("""SELECT m.item_seq,m.item_name,m.etc_otc_name,m.class_no,m.class_name,left(m.item_permit_date,4) y,
              EXISTS(SELECT 1 FROM v_item_ingredients v WHERE v.item_seq=m.item_seq) has_ing,
              EXISTS(SELECT 1 FROM medicine_permit_detail d WHERE d.item_seq=m.item_seq) has_detail
              FROM medicines m WHERE m.cancel_name='정상' AND coalesce(m.edi_code,'')<>''""")
    finally:
        await con.close()
    B = [r for r in rows if not r["has_ing"]]; A = [r for r in rows if r["has_ing"]]
    print(f"\n[B] 정상·EDI 있음 {len(rows):,}건 = 주성분코드 있음 {len(A):,} + 없음 {len(B):,}")
    def big(r):
        c = (r["class_no"] or "").strip()
        return c[1:2] if len(c) == 5 and c.isdigit() else ("(분류번호 없음)" if not c else "(형식 다름)")
    print("  분류번호 대분류(3자리 코드의 첫 자리)")
    print("    없음:", pct(Counter(big(r) for r in B)))
    print("    있음:", pct(Counter(big(r) for r in A)))
    print("  이름에 '(수출용)' 포함  없음:", sum("수출용" in (r["item_name"] or "") for r in B), "/", len(B), "| 있음:", sum("수출용" in (r["item_name"] or "") for r in A), "/", len(A))
    print("  허가 상세(medicine_permit_detail) 보유  없음:", sum(r["has_detail"] for r in B), "/", len(B), "| 있음:", sum(r["has_detail"] for r in A), "/", len(A))
    print("  전문/일반  없음:", pct(Counter(r["etc_otc_name"] or "(없음)" for r in B)), "| 있음:", pct(Counter(r["etc_otc_name"] or "(없음)" for r in A)))
asyncio.run(main())
