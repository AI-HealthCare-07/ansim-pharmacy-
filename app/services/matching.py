"""DOC-004: 구조화된 약을 의약품 DB에 연결한다(구조화가 끝나면 서버가 이어서 실행).

세 갈래 규칙(11/26 결정 Q2 C):
  ① 보험코드(EDI)가 하나의 약과 일치하고 OCR 이름과 어느 정도 닮았으면 -> confirmed_by='AUTO'
  ② 이름 검색 1등이 0.7 이상이고 2등과 0.15 이상 차이 나면 -> 1등만 미리 선택(confirmed_by는 비움)
  ③ 그 밖 -> 미리 선택 없이 후보(최대 3개)만 둔다. 사용자가 고르거나 "잘 모르겠어요"(UNKNOWN)

사용자가 이미 결정한 줄(USER/UNKNOWN)이 있는 문서는 약 목록을 건드리지 않는다.
"""
from __future__ import annotations

import json
from decimal import Decimal

from tortoise.transactions import in_transaction

AUTO_NAME_MIN = 0.3      # EDI로 찾은 약 이름이 OCR 이름과 이 값 미만으로 닮으면 숫자 오독으로 보고 자동 확인에서 뺀다
PRESELECT_MIN = 0.7      # 이름 검색 1등이 이 점수 이상이어야 미리 선택
PRESELECT_GAP = 0.15     # 1등과 2등의 점수 차이가 이 값 이상이어야 미리 선택
MAX_CANDIDATES = 3

_HAS_CODE = """EXISTS (SELECT 1 FROM v_item_ingredients i
                         WHERE i.item_seq = m.item_seq AND i.main_ingredient_code IS NOT NULL)"""

SQL_EDI = f"""
SELECT m.item_seq::text AS item_seq, m.item_name, m.entp_name, m.item_ingr_name AS ingredient,
       {_HAS_CODE} AS has_ingr_code,
       similarity(fn_norm_drug_name($1), fn_norm_drug_name(m.item_name))::float AS name_sim
  FROM fn_match_by_edi($2) s JOIN medicines m ON m.item_seq = s.item_seq
"""

SQL_NAME = f"""
SELECT m.item_seq::text AS item_seq, m.item_name, m.entp_name, m.item_ingr_name AS ingredient,
       {_HAS_CODE} AS has_ingr_code,
       s.score::float AS score
  FROM fn_search_medicines($1, 10) s JOIN medicines m ON m.item_seq = s.item_seq
 ORDER BY s.score DESC, length(m.item_name)
"""

SQL_INSERT_ITEM = """
INSERT INTO document_items (document_id, line_no, raw_drug_name, raw_edi_code, drug_name, edi_code,
    dose_per_time, dose_unit, times_per_day, total_days, timing_text,
    matched_item_seq, match_method, match_score, match_candidates, needs_review, confirmed_by)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::item_seq_t, $13, $14, $15::jsonb, $16, $17)
"""

SQL_SELECT_ITEMS = """
SELECT item_id, line_no, drug_name, edi_code, dose_per_time, dose_unit, times_per_day, total_days,
       timing_text, matched_item_seq::text AS matched_item_seq, match_method, match_score,
       match_candidates, needs_review, confirmed_by, ai_excluded
  FROM document_items WHERE document_id = $1 ORDER BY line_no
"""


def _cand(r: dict, score: float, edi_match: bool = False) -> dict:
    return {
        "item_seq": r["item_seq"], "item_name": r["item_name"], "entp_name": r["entp_name"],
        "ingredient": r["ingredient"], "has_ingr_code": bool(r["has_ingr_code"]),
        "score": round(float(score), 3), "edi_match": edi_match,
    }


async def match_one(conn, drug: dict) -> dict:
    """약 한 줄을 연결한다. conn은 execute_query_dict(sql, values)를 가진 연결."""
    name = (drug.get("name") or "").strip()
    edi = drug.get("edi_code")

    edi_rows = await conn.execute_query_dict(SQL_EDI, [name, edi]) if edi else []
    if len(edi_rows) == 1 and edi_rows[0]["name_sim"] >= AUTO_NAME_MIN:
        c = _cand(edi_rows[0], 1.0, edi_match=True)
        return {"matched_item_seq": c["item_seq"], "match_method": "EDI_EXACT", "match_score": 1.0,
                "candidates": [c], "confirmed_by": "AUTO", "needs_review": False, "kind": "AUTO"}

    by_seq: dict[str, dict] = {}
    for r in edi_rows:  # 같은 보험코드에 품목이 여럿이거나 이름이 너무 다르면 자동 확인하지 않고 후보로만 둔다
        by_seq[r["item_seq"]] = _cand(r, r["name_sim"], edi_match=True)
    if len(name) >= 2:
        for r in await conn.execute_query_dict(SQL_NAME, [name]):
            c = _cand(r, r["score"])
            old = by_seq.get(c["item_seq"])
            if old is not None:
                c["edi_match"] = old["edi_match"]
            if old is None or c["score"] > old["score"]:
                by_seq[c["item_seq"]] = c

    cands = sorted(by_seq.values(), key=lambda c: -c["score"])[:MAX_CANDIDATES]
    pre = None
    if cands and cands[0]["score"] >= PRESELECT_MIN and (
            len(cands) == 1 or cands[0]["score"] - cands[1]["score"] >= PRESELECT_GAP):
        pre = cands[0]
    return {
        "matched_item_seq": pre["item_seq"] if pre else None,
        "match_method": "NAME_TRGM" if cands else "NONE",
        "match_score": pre["score"] if pre else None,
        "candidates": cands, "confirmed_by": None, "needs_review": True,
        "kind": "PRESELECTED" if pre else ("CANDIDATES" if cands else "NO_CANDIDATE"),
    }


def _dec(v):
    return None if v is None else Decimal(str(v))


async def match_document(document_id, drugs: list[dict]) -> list[dict]:
    """구조화된 약 목록을 document_items에 저장하고 매칭한다. 문서 상태를 MATCHED로 바꾼다."""
    async with in_transaction() as conn:
        decided = await conn.execute_query_dict(
            "SELECT 1 FROM document_items WHERE document_id = $1 AND confirmed_by IN ('USER', 'UNKNOWN') LIMIT 1",
            [document_id])
        if not decided:  # 사용자가 이미 고른 줄이 있으면 목록을 그대로 둔다
            await conn.execute_query_dict("DELETE FROM document_items WHERE document_id = $1", [document_id])
            for no, d in enumerate(drugs, start=1):
                m = await match_one(conn, d)
                await conn.execute_query_dict(SQL_INSERT_ITEM, [
                    document_id, no, d.get("name"), d.get("edi_code"), (d.get("name") or "(이름 없음)"),
                    d.get("edi_code"), _dec(d.get("dose_per_time")), d.get("dose_unit"),
                    d.get("times_per_day"), d.get("total_days"), d.get("timing"),
                    m["matched_item_seq"], m["match_method"], _dec(m["match_score"]),
                    json.dumps(m["candidates"], ensure_ascii=False), m["needs_review"], m["confirmed_by"],
                ])
        await conn.execute_query_dict(
            "UPDATE documents SET status = 'MATCHED' WHERE document_id = $1 AND status IN ('STRUCTURED', 'MATCHED')",
            [document_id])
        rows = await conn.execute_query_dict(SQL_SELECT_ITEMS, [document_id])

    for r in rows:
        if isinstance(r["match_candidates"], str):
            r["match_candidates"] = json.loads(r["match_candidates"])
    return rows
