"""분류번호 예규 제223호 별표(전사본 CSV) vs medicines.class_no/class_name 비교. 읽기 전용.
사용: set -a; source .env; set +a; PYTHONPATH=. .venv/bin/python scripts/diag_class_table.py
"""
import asyncio, csv, os, re
from pathlib import Path
import asyncpg
from dotenv import dotenv_values

CSV = Path("docs/ref/law_tables/class223_table.csv")


async def main():
    env = dotenv_values(Path(".env"))
    g = lambda k, d=None: os.getenv(k) or env.get(k) or d
    law = {r["class_no"]: r["class_name"] for r in csv.DictReader(CSV.open(encoding="utf-8"))}
    con = await asyncpg.connect(host=g("POSTGRES_HOST", "localhost"), port=int(g("POSTGRES_PORT", "5432")),
                                user=g("POSTGRES_USER"), password=g("POSTGRES_PASSWORD"), database=g("POSTGRES_DB"))
    try:
        print("=== 0. 저장 형식(상위 10) ===")
        for r in await con.fetch("SELECT class_no, class_name, count(*) n FROM medicines GROUP BY 1,2 ORDER BY 3 DESC LIMIT 10"):
            print(dict(r))
        rows = await con.fetch("SELECT class_no, class_name, count(*) n FROM medicines GROUP BY 1,2")
        empty = sum(r["n"] for r in rows if not (r["class_no"] or "").strip())
        notin, diff = {}, {}
        for r in rows:
            c = (r["class_no"] or "").strip()
            if not c:
                continue
            if c not in law:
                notin[c] = notin.get(c, 0) + r["n"]
            elif (r["class_name"] or "").replace(" ", "") != law[c].replace(" ", ""):
                diff[(c, r["class_name"], law[c])] = r["n"]
        print(f"\n=== A. 별표에 없는 분류번호 {len(notin)}종 (상위 20) ===")
        for c, n in sorted(notin.items(), key=lambda x: -x[1])[:20]:
            print(c, n)
        print(f"\n=== B. 번호는 같고 이름이 다름 {len(diff)}건 (상위 20) ===")
        for k, n in sorted(diff.items(), key=lambda x: -x[1])[:20]:
            print(k, n)
        print(f"\n=== C. 분류번호 없음(전체): {empty}건 ===")
        norm = lambda x: (x or "").replace(".", ",").replace(" ", "")
        ok = bad = shape = 0
        bad_ex = {}
        shape_ex = []
        for r in rows:
            c = (r["class_no"] or "").strip()
            if not c:
                continue
            if not (len(c) == 5 and c[0] == "0" and c[4] == "0"):
                shape += r["n"]; shape_ex.append((c, r["class_name"], r["n"])); continue
            cand = c[1:4]
            if cand in law and norm(law[cand]) == norm(r["class_name"]):
                ok += r["n"]
            else:
                bad += r["n"]; bad_ex[(c, r["class_name"], law.get(cand))] = r["n"]
        print("\n=== D. 5자리(0+3자리+0) → 가운데 3자리로 별표와 번호·이름 모두 일치 ===")
        print("일치", ok, "/ 불일치", bad, "/ 형식 다름", shape)
        for k, n in sorted(bad_ex.items(), key=lambda x: -x[1])[:25]:
            print(k, n)
        print("\n=== D2. 5자리 형식이 아닌 값 ===")
        for x in sorted(shape_ex, key=lambda t: -t[2])[:30]:
            print(x)
        okb = badb = other = 0
        for c, nm, n in shape_ex:
            m = re.match(r"\[(\d{3})\](.*)$", c)
            if not m:
                other += n; print("형식 불명:", c, nm, n); continue
            if m.group(1) in law and norm(law[m.group(1)]) == norm(m.group(2)):
                okb += n
            else:
                badb += n; print("번호는 있으나 이름 다름:", c, "| 별표:", law.get(m.group(1)), n)
        print("\n=== D3. [번호]이름 형식: 번호·이름 일치", okb, "/ 불일치", badb, "/ 형식 불명", other)
        print("\n=== E. 정상 품목 중 분류번호 없음 ===")
        r = await con.fetchrow("SELECT count(*) FILTER (WHERE coalesce(class_no,'')='') e, count(*) t FROM medicines WHERE cancel_name='정상'")
        print(dict(r))
    finally:
        await con.close()

asyncio.run(main())
