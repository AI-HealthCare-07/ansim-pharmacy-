"""의약품 표준코드(BarCodeData)로 성분코드 공백을 얼마나 메우는지 센다. 읽기 전용(DB 쓰기 없음).
사용: PYTHONPATH=. .venv/bin/python scripts/measure_kpis_link.py
원칙: 공식 코드 연결만 센다. 이름 유사도는 쓰지 않는다.
"""
import asyncio, os, csv
import asyncpg

SRC = "data/raw/kpis/BarCodeData.txt"


def load():
    best = {}
    with open(SRC, encoding="cp949", newline="") as f:
        for r in csv.DictReader(f, delimiter="|"):
            k = (r.get("품목기준코드") or "").strip()
            if not k:
                continue
            g = (r.get("일반명코드(성분명코드)") or "").strip()
            a = (r.get("ATC코드") or "").strip()
            cur = best.setdefault(k, {"g": "", "a": ""})
            cur["g"] = cur["g"] or g
            cur["a"] = cur["a"] or a
    return best


async def main():
    bc = load()
    print(f"표준코드 품목 {len(bc):,}개 (일반명코드 있음 {sum(1 for v in bc.values() if v['g']):,}, ATC 있음 {sum(1 for v in bc.values() if v['a']):,})")
    con = await asyncpg.connect(host=os.getenv("POSTGRES_HOST", "localhost"), port=int(os.getenv("POSTGRES_PORT", "5432")),
                                database=os.environ["POSTGRES_DB"], user=os.environ["POSTGRES_USER"], password=os.environ["POSTGRES_PASSWORD"])
    nocode = [r["item_seq"] for r in await con.fetch(
        "SELECT m.item_seq FROM medicines m WHERE m.cancel_name='정상' AND NOT EXISTS (SELECT 1 FROM v_item_ingredients i WHERE i.item_seq=m.item_seq)")]
    have = {r["item_seq"]: r["c"] for r in await con.fetch(
        "SELECT item_seq, min(main_ingredient_code) c FROM v_item_ingredients GROUP BY item_seq")}
    n = len(nocode)
    inb = [s for s in nocode if s in bc]
    g = [s for s in nocode if bc.get(s, {}).get("g")]
    a = [s for s in nocode if bc.get(s, {}).get("a")]
    print(f"\n[성분코드 없는 정상 약 {n:,}건]")
    print(f"  표준코드 파일에 품목이 있음   {len(inb):,} ({len(inb)/n:.1%})")
    print(f"  일반명코드(성분명코드) 얻음   {len(g):,} ({len(g)/n:.1%})")
    print(f"  ATC코드만이라도 얻음          {len(a):,} ({len(a)/n:.1%})")
    both = [s for s in have if bc.get(s, {}).get("g")]
    p4 = sum(1 for s in both if have[s][:4] == bc[s]["g"][:4])
    ex = sum(1 for s in both if have[s] == bc[s]["g"])
    print(f"\n[이미 코드가 있는 약 중 표준코드 일반명코드도 있는 {len(both):,}건 비교]")
    print(f"  앞 4자리(성분) 일치 {p4:,} ({p4/max(len(both),1):.1%}) / 9자리 전체 일치 {ex:,} ({ex/max(len(both),1):.1%})")
    diff = [(s, have[s], bc[s]["g"]) for s in both if have[s][:4] != bc[s]["g"][:4]][:5]
    print("  불일치 예시(품목, DB코드, 표준코드):", diff)
    await con.close()

asyncio.run(main())
