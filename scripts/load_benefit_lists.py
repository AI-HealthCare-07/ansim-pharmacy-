"""약제급여목록 월별 판(data/raw/약제급여목록*.xlsx)을 benefit_list_* 에 적재하고,
medicine_edi_codes 의 비어 있는 주성분코드를 '가장 최근 판'의 정확 일치 값으로 채운다.
- 기본은 드라이런(DB 쓰기 없음). --apply 로만 기록.
- 판 선택은 파일 수정시각이 아니라 파일명의 기준일 기준.
- 값이 비어 있으면 채움. 값이 다르면(과거 주성분코드_동일제형 열이 들어간 행) 이전 값을 ingredient_code_prev 에 보관하고 교정(잠정, 확정 아님).
- 사전 필요: 패치 20261127_benefit_list_history.sql, 20261127_benefit_list_history_b.sql. 되돌리기: scripts/revert_benefit_list_fill.sql
사용: set -a; source .env; set +a; PYTHONPATH=. .venv/bin/python scripts/load_benefit_lists.py [--apply]
"""
import asyncio, os, re, sys, warnings, datetime as dt
from collections import Counter
from pathlib import Path
import asyncpg, pandas as pd
from dotenv import dotenv_values
warnings.filterwarnings("ignore")
APPLY = "--apply" in sys.argv

def s(v):
    return None if v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() in ("", "nan") else str(v).strip()

def read_list(path):
    xl = pd.ExcelFile(path)
    for sh in xl.sheet_names:
        raw = pd.read_excel(path, sheet_name=sh, header=None, dtype=str, nrows=15)
        hr = next((i for i, r in raw.iterrows() if "제품코드" in " ".join(r.dropna().astype(str))), None)
        if hr is None: continue
        df = pd.read_excel(path, sheet_name=sh, header=hr, dtype=str)
        df.columns = [str(c).strip().replace("\n", "") for c in df.columns]
        col = lambda k: next((c for c in df.columns if c == k), None)
        out = []
        for _, r in df.iterrows():
            e = s(r[col("제품코드")])
            if not e: continue
            g = lambda k: s(r[col(k)]) if col(k) else None
            out.append((e, g("주성분코드"), g("주성분코드_동일제형"), g("주성분명"), g("제품명"), g("업체명"), g("비고")))
        return sh, out
    raise RuntimeError(f"제품코드 열이 있는 시트 없음: {path.name}")

async def main():
    lists = {}
    for f in Path("data/raw").glob("약제급여목록*.xlsx"):
        m = re.search(r"\((\d{4})\.(\d{1,2})\.(\d{1,2})\.\)", f.name)
        if not m: print("파일명에서 기준일을 못 읽어 건너뜀:", f.name); continue
        y, mo, d = map(int, m.groups())
        lists[f"{y}-{mo:02d}"] = (dt.date(y, mo, d), f)
    months = sorted(lists); latest = months[-1]
    print("판:", months, "| 최근 판:", latest, "| 모드:", "APPLY" if APPLY else "드라이런")
    data = {}
    for k in months:
        sh, rows = read_list(lists[k][1])
        eds = [r[0] for r in rows]
        data[k] = (sh, rows)
        print(f"  [{k}] 행 {len(rows):,} | 고유 코드 {len(set(eds)):,} | 중복 {len(eds)-len(set(eds))} | 주성분코드 빈 행 {sum(1 for r in rows if not r[1])}")
    # 코드별 가장 최근 판의 값 + 판 간 불일치
    best, seen = {}, {}
    for k in months:
        for r in data[k][1]:
            best[r[0]] = (k, r[1]); seen.setdefault(r[0], set()).add(r[1])
    incons = sum(1 for v in seen.values() if len(v) > 1)
    print(f"판 간 주성분코드가 다른 EDI: {incons}건")

    env = dotenv_values(".env"); g_ = lambda k, d=None: os.getenv(k) or env.get(k) or d
    con = await asyncpg.connect(host=g_("POSTGRES_HOST","localhost"), port=int(g_("POSTGRES_PORT","5432")),
        database=g_("POSTGRES_DB"), user=g_("POSTGRES_USER"), password=g_("POSTGRES_PASSWORD"))
    try:
        rows = await con.fetch("""SELECT item_seq, edi_code, main_ingredient_code FROM medicine_edi_codes""")
        fill, conflict, same, nolist, norow = [], [], [], 0, 0
        edi_rows = {}
        for r in rows: edi_rows.setdefault((r["edi_code"] or "").strip(), []).append(r)
        for e, rs in edi_rows.items():
            if e not in best:
                nolist += sum(1 for r in rs if r["main_ingredient_code"]); continue
            k, ing = best[e]
            for r in rs:
                cur = r["main_ingredient_code"]
                if cur is None and ing: fill.append((e, ing, k))
                elif cur and ing and cur.strip() != ing: conflict.append((e, cur, ing, k))
                elif cur and ing: same.append((e, k))
        print(f"\nmedicine_edi_codes {len(rows):,}행")
        print(f"  비어 있어 채울 행: {len(fill):,} (판별: {dict(Counter(k for _,_,k in fill))})")
        print(f"  이미 같은 값(출처 판만 기록): {len(same):,} (판별: {dict(Counter(k for _,k in same))})")
        print(f"  값이 달라 교정 대상(이전 값 보관): {len(conflict):,}  예: {conflict[:3]}")
        print(f"  값은 있으나 어느 판에도 EDI가 없는 행(출처 미기록 유지): {nolist:,}")
        miss = [e for e in best if e not in edi_rows]
        print(f"  급여목록에는 있으나 medicine_edi_codes에 행이 없는 EDI: {len(miss):,}")
        if fill:
            n_items = await con.fetchval("""SELECT count(DISTINCT e.item_seq) FROM medicine_edi_codes e JOIN medicines m USING (item_seq)
                WHERE m.cancel_name='정상' AND e.main_ingredient_code IS NULL AND e.edi_code = ANY($1::text[])""", [f[0] for f in fill])
            print(f"  채워지면 주성분코드가 생기는 정상 품목 수: {n_items:,}")
        if not APPLY: print("\n드라이런 끝. 적용하려면 --apply"); return
        async with con.transaction():
            for k in months:
                base, f = lists[k]; sh, rs = data[k]
                await con.execute("DELETE FROM benefit_list_entries WHERE list_month=$1", k)
                await con.execute("""INSERT INTO benefit_list_versions(list_month,base_date,source_file,sheet_name,row_count)
                    VALUES($1,$2,$3,$4,$5) ON CONFLICT (list_month) DO UPDATE SET base_date=EXCLUDED.base_date,
                    source_file=EXCLUDED.source_file, sheet_name=EXCLUDED.sheet_name, row_count=EXCLUDED.row_count, loaded_at=now()""",
                    k, base, f.name, sh, len(rs))
                uniq = {r[0]: r for r in rs}
                await con.copy_records_to_table("benefit_list_entries", records=[(k, *r) for r in uniq.values()],
                    columns=["list_month","edi_code","main_ingredient_code","same_form_code","ingredient_name","product_name","company_name","note"])
            await con.execute("CREATE TEMP TABLE t(edi TEXT, ingr TEXT, mon TEXT) ON COMMIT DROP")
            await con.copy_records_to_table("t", records=[(e, v[1], v[0]) for e, v in best.items() if v[1]])
            r0 = await con.execute("""UPDATE medicine_edi_codes e SET ingredient_code_prev=e.main_ingredient_code,
                   main_ingredient_code=t.ingr, ingredient_group_code=left(t.ingr,4),
                   ingredient_source_list=t.mon, ingredient_in_current_list=(t.mon=$1), ingredient_code_changed_at=now()
                 FROM t WHERE trim(e.edi_code)=t.edi AND e.main_ingredient_code IS NOT NULL AND e.main_ingredient_code<>t.ingr""", latest)
            r1 = await con.execute("""UPDATE medicine_edi_codes e SET main_ingredient_code=t.ingr, ingredient_group_code=left(t.ingr,4),
                   ingredient_source_list=t.mon, ingredient_in_current_list=(t.mon=$1), ingredient_code_changed_at=now()
                 FROM t WHERE trim(e.edi_code)=t.edi AND e.main_ingredient_code IS NULL""", latest)
            r2 = await con.execute("""UPDATE medicine_edi_codes e SET ingredient_source_list=t.mon, ingredient_in_current_list=(t.mon=$1)
                 FROM t WHERE trim(e.edi_code)=t.edi AND e.main_ingredient_code=t.ingr AND e.ingredient_source_list IS NULL""", latest)
            print("\n적용 완료: 교정", r0, "| 채움", r1, "| 출처만 기록", r2)
    finally:
        await con.close()
asyncio.run(main())
