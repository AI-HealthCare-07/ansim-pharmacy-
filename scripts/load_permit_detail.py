"""허가 상세 jsonl을 DB에 적재한다. 기본은 점검만(dry-run, 쓰기 없음). 적용은 --apply.

사용:  set -a; source .env; set +a
       PYTHONPATH=. .venv/bin/python scripts/load_permit_detail.py            # 점검만
       PYTHONPATH=. .venv/bin/python scripts/load_permit_detail.py --apply    # 적재
선행: infra/db/patches/20261127_permit_detail.sql 적용, 그리고 20261127_permit_detail_history.sql(이력 함수) 적용
적재 범위:
  - medicine_permit_detail / medicine_permit_ingredients : 전량 upsert
  - medicines.ee/ud/nb_doc_id : 비어 있는 정상 약만 채움(이미 값이 있으면 건드리지 않음)
원칙: 이름 매칭·추정 없음. 받은 원문 그대로 저장한다.
"""
import argparse, asyncio, json, os, re, sys
from pathlib import Path
import asyncpg
from dotenv import dotenv_values

SRC = Path("data/raw/permit_detail/detail.jsonl")
M_PART = re.compile(r"\[(M\d+)\]([^|]*)")


def parse(row):
    ingr = [(m, n.strip()) for m, n in M_PART.findall(row.get("MAIN_ITEM_INGR") or "")]
    return ingr


async def main(apply):
    env = dotenv_values(Path(".env"))
    g = lambda k, d=None: os.getenv(k) or env.get(k) or d
    recs = {}
    for line in SRC.open(encoding="utf-8"):
        r = json.loads(line)
        if r.get("row"):
            recs[r["_item_seq"]] = r["row"]            # 같은 품목이 여러 번이면 마지막 값
    full = sum(1 for r in recs.values() if all((r.get(k) or "").strip() for k in ("EE_DOC_DATA", "UD_DOC_DATA", "NB_DOC_DATA")))
    print(f"파일: 품목 {len(recs):,}건, 본문 3종 모두 있음 {full:,}건")
    con = await asyncpg.connect(host=g("POSTGRES_HOST", "localhost"), port=int(g("POSTGRES_PORT", "5432")),
                                database=g("POSTGRES_DB"), user=g("POSTGRES_USER"), password=g("POSTGRES_PASSWORD"))
    try:
        exist = {r["item_seq"]: r for r in await con.fetch(
            "SELECT item_seq, cancel_name, coalesce(nb_doc_id,'')<>'' AS has_doc FROM medicines WHERE item_seq = ANY($1::text[])", list(recs))}
        not_in_db = [s for s in recs if s not in exist]
        will_fill = [s for s in recs if s in exist and not exist[s]["has_doc"] and exist[s]["cancel_name"] == "정상"]
        print(f"DB에 없는 품목 {len(not_in_db):,}건(적재 안 함), doc_id 새로 채울 정상 약 {len(will_fill):,}건")
        if not apply:
            print("점검만 했어요. 적재하려면 --apply"); return
        async with con.transaction():
            for s, r in recs.items():
                if s not in exist:
                    continue
                await con.execute("""
                  INSERT INTO medicine_permit_detail (item_seq, ee_doc_data, ud_doc_data, nb_doc_data, main_item_ingr, atc_code, edi_code, chart, storage_method, valid_term, change_date, source_label)
                  VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,'허가정보 상세 API 2026-11-27')
                  ON CONFLICT (item_seq) DO UPDATE SET ee_doc_data=EXCLUDED.ee_doc_data, ud_doc_data=EXCLUDED.ud_doc_data,
                    nb_doc_data=EXCLUDED.nb_doc_data, main_item_ingr=EXCLUDED.main_item_ingr, atc_code=EXCLUDED.atc_code,
                    edi_code=EXCLUDED.edi_code, chart=EXCLUDED.chart, storage_method=EXCLUDED.storage_method,
                    valid_term=EXCLUDED.valid_term, change_date=EXCLUDED.change_date, fetched_at=now()""",
                    s, r.get("EE_DOC_DATA"), r.get("UD_DOC_DATA"), r.get("NB_DOC_DATA"), r.get("MAIN_ITEM_INGR"),
                    r.get("ATC_CODE"), r.get("EDI_CODE"), r.get("CHART"), r.get("STORAGE_METHOD"), r.get("VALID_TERM"), r.get("CHANGE_DATE"))
                await con.execute("SELECT snapshot_permit_detail($1)", s)   # 내용이 바뀐 경우에만 이력에 새 판 추가
                await con.execute("DELETE FROM medicine_permit_ingredients WHERE item_seq=$1", s)
                for m, n in parse(r):
                    await con.execute("INSERT INTO medicine_permit_ingredients (item_seq, m_code, ingr_name) VALUES ($1,$2,$3) ON CONFLICT DO NOTHING", s, m, n)
            await con.executemany(
                """UPDATE medicines SET ee_doc_id=$2, ud_doc_id=$3, nb_doc_id=$4, updated_at=CURRENT_TIMESTAMP
                    WHERE item_seq=$1 AND cancel_name='정상' AND coalesce(nb_doc_id,'')=''""",
                [(s, recs[s].get("EE_DOC_ID"), recs[s].get("UD_DOC_ID"), recs[s].get("NB_DOC_ID")) for s in will_fill])
        print("적재 완료")
    finally:
        await con.close()

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--apply", action="store_true")
    asyncio.run(main(ap.parse_args().apply))
