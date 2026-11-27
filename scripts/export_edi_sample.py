"""교정·채움 후에도 주성분코드 없는 정상 약(EDI 있음)의 표본 CSV + 수출용 표기 없는 약의 특성. 읽기 전용, 재현 가능(md5 순).
공식 조회 화면 대조용. 사용: PYTHONPATH=. .venv/bin/python scripts/export_edi_sample.py
"""
import asyncio, csv, os
from collections import Counter
from pathlib import Path
import asyncpg
from dotenv import dotenv_values

def pct(c):
    t = sum(c.values()) or 1
    return {k: f"{v:,} ({v*100/t:.1f}%)" for k, v in c.most_common(8)}

async def main():
    env = dotenv_values(".env"); g = lambda k, d=None: os.getenv(k) or env.get(k) or d
    con = await asyncpg.connect(host=g("POSTGRES_HOST","localhost"), port=int(g("POSTGRES_PORT","5432")),
        database=g("POSTGRES_DB"), user=g("POSTGRES_USER"), password=g("POSTGRES_PASSWORD"))
    try:
        rows = await con.fetch("""
          SELECT m.item_seq, m.item_name, m.entp_name, m.edi_code, m.etc_otc_name, m.class_no, left(m.item_permit_date,4) y,
                 (m.item_name LIKE '%수출%') export_mark
            FROM medicines m
           WHERE m.cancel_name='정상' AND coalesce(m.edi_code,'')<>''
             AND NOT EXISTS (SELECT 1 FROM v_item_ingredients v WHERE v.item_seq=m.item_seq)
           ORDER BY md5(m.item_seq)""")
    finally:
        await con.close()
    ex = [r for r in rows if r["export_mark"]]; non = [r for r in rows if not r["export_mark"]]
    print(f"주성분코드 없는 정상 약 {len(rows):,}건 = 이름에 '수출' 포함 {len(ex):,} + 없음 {len(non):,}")
    first = lambda r: (r["edi_code"] or "").strip()[:1]
    print("[수출 표기 없는 약] EDI 첫글자:", pct(Counter(first(r) for r in non)))
    print("  허가연도:", pct(Counter(r["y"] for r in non)))
    print("  전문/일반:", pct(Counter(r["etc_otc_name"] or "(없음)" for r in non)))
    print("  분류번호 있음:", sum(1 for r in non if (r["class_no"] or "").strip()), "/", len(non))
    pick = ex[:8]
    for key, n in (("6", 12), ("0", 5)): pick += [r for r in non if first(r) == key][:n]
    pick += [r for r in non if first(r) not in ("6", "0")][:5]
    out = Path("docs/review/edi_sample_261127.csv")
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(["구분","item_seq","item_name","entp_name","edi_code","etc_otc_name","permit_year","공식조회_결과(급여/비급여/삭제/없음)","확인일","출처화면"])
        for r in pick: w.writerow(["수출 표기" if r["export_mark"] else "표기 없음", r["item_seq"], r["item_name"].replace("\n"," "), r["entp_name"], r["edi_code"], r["etc_otc_name"], r["y"], "", "", ""])
    print(f"표본 {len(pick)}건 저장(수출 표기 {sum(1 for r in pick if r['export_mark'])} / 표기 없음 {sum(1 for r in pick if not r['export_mark'])}): {out}")
asyncio.run(main())
