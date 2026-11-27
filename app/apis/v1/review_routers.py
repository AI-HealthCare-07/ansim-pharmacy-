"""Task 2: 확인·수정 API (D3 목록, D4 한 줄 수정, R1 약 검색, D6 확인 완료).

- 약 연결 결과는 document_items에 있다(app/services/matching.py가 만든다).
- 화면 용어: 사용자 화면에는 "DUR"을 쓰지 않는다(D-23). 이 파일은 API라 코드값만 다룬다.
- 확인 완료(D6)는 원본 파일과 ocr_raw를 즉시 지운다(D-03).
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from tortoise import connections
from tortoise.transactions import in_transaction

from app.apis.v1.document_routers import DEMO_USER_ID
from app.services.documents import UPLOAD_ROOT
from app.services.matching import SQL_NAME, SQL_SELECT_ITEMS

review_router = APIRouter(prefix="/documents", tags=["documents-review"])
drug_router = APIRouter(prefix="/drugs", tags=["drugs"])

EDITABLE = ("STRUCTURED", "MATCHED")


def _err(status: int, code: str, message: str, **extra):
    return JSONResponse(status_code=status, content={"error_code": code, "message": message, **extra})


async def _get_doc(conn, document_id, user_id: int):
    rows = await conn.execute_query_dict(
        "SELECT document_id, status, visit_date, diagnoses, storage_path, original_deleted_at, confirmed_at"
        "  FROM documents WHERE document_id = $1 AND user_id = $2", [document_id, user_id])
    return rows[0] if rows else None


def _load_json(v):
    return json.loads(v) if isinstance(v, str) else v


# ---------------------------------------------------------------- D3
@review_router.get("/{document_id}/items")
async def list_items(document_id: uuid.UUID):
    conn = connections.get("default")
    doc = await _get_doc(conn, document_id, DEMO_USER_ID)
    if doc is None:
        return _err(404, "NOT_FOUND", "문서를 찾을 수 없어요.")
    items = await conn.execute_query_dict(SQL_SELECT_ITEMS, [document_id])
    for it in items:
        it["match_candidates"] = _load_json(it["match_candidates"]) or []
        # 선택된 약에 금기·주의를 확인할 수 있는 성분코드가 있는지(화면의 "확인할 수 없어요" 안내용)
        sel = next((c for c in it["match_candidates"] if c["item_seq"] == it["matched_item_seq"]), None)
        it["has_ingr_code"] = sel["has_ingr_code"] if sel else None
        it["ingredient"] = sel["ingredient"] if sel else None
    undecided = sum(1 for it in items if it["confirmed_by"] is None)
    return {
        "document_id": str(document_id), "status": doc["status"], "visit_date": doc["visit_date"],
        "diagnoses": _load_json(doc["diagnoses"]) or [],
        "photo_available": bool(doc["storage_path"]),
        "items": items,
        "summary": {"total": len(items), "undecided": undecided,
                    "auto": sum(1 for it in items if it["confirmed_by"] == "AUTO"),
                    "user": sum(1 for it in items if it["confirmed_by"] == "USER"),
                    "unknown": sum(1 for it in items if it["confirmed_by"] == "UNKNOWN")},
    }


# ---------------------------------------------------------------- D4
class ItemPatch(BaseModel):
    """matched_item_seq: 후보·검색 결과 선택([모두 맞아요]도 미리 선택된 값으로 호출).
    unknown: "잘 모르겠어요". ai_excluded: AI 안내 제외 토글(D-14)."""
    matched_item_seq: str | None = Field(None, max_length=20, pattern=r"^[0-9]+$")
    unknown: bool = False
    ai_excluded: bool | None = None


@review_router.patch("/{document_id}/items/{item_id}")
async def patch_item(document_id: uuid.UUID, item_id: int, body: ItemPatch):
    if body.matched_item_seq and body.unknown:
        return _err(400, "INVALID_REQUEST", "약 선택과 '잘 모르겠어요'는 함께 보낼 수 없어요.")
    if not (body.matched_item_seq or body.unknown or body.ai_excluded is not None):
        return _err(400, "INVALID_REQUEST", "바꿀 내용이 없어요.")
    conn = connections.get("default")
    doc = await _get_doc(conn, document_id, DEMO_USER_ID)
    if doc is None:
        return _err(404, "NOT_FOUND", "문서를 찾을 수 없어요.")
    if doc["status"] not in EDITABLE:
        return _err(409, "NOT_EDITABLE", "확정한 문서는 고칠 수 없어요.")

    if body.matched_item_seq:
        ok = await conn.execute_query_dict(
            "SELECT 1 FROM v_active_medicines WHERE item_seq = $1::item_seq_t", [body.matched_item_seq])
        if not ok:
            return _err(400, "UNKNOWN_DRUG", "찾을 수 없는 약이에요.")
        rows = await conn.execute_query_dict(
            "UPDATE document_items SET"
            " is_user_edited = is_user_edited OR matched_item_seq IS DISTINCT FROM $3::item_seq_t,"
            " match_method = CASE WHEN matched_item_seq IS DISTINCT FROM $3::item_seq_t"
            "                     THEN 'USER_SELECTED' ELSE match_method END,"
            " match_score = CASE WHEN matched_item_seq IS DISTINCT FROM $3::item_seq_t THEN NULL ELSE match_score END,"
            " matched_item_seq = $3::item_seq_t, confirmed_by = 'USER', user_confirmed = true,"
            " needs_review = false, confirmed_at = now(),"
            " ai_excluded = coalesce($4, ai_excluded)"
            " WHERE item_id = $1 AND document_id = $2 RETURNING item_id",
            [item_id, document_id, body.matched_item_seq, body.ai_excluded])
    elif body.unknown:
        rows = await conn.execute_query_dict(
            "UPDATE document_items SET matched_item_seq = NULL, match_method = 'NONE', match_score = NULL,"
            " confirmed_by = 'UNKNOWN', user_confirmed = false, needs_review = false, confirmed_at = now(),"
            " ai_excluded = coalesce($3, ai_excluded)"
            " WHERE item_id = $1 AND document_id = $2 RETURNING item_id",
            [item_id, document_id, body.ai_excluded])
    else:  # AI 제외 토글만
        rows = await conn.execute_query_dict(
            "UPDATE document_items SET ai_excluded = $3 WHERE item_id = $1 AND document_id = $2 RETURNING item_id",
            [item_id, document_id, body.ai_excluded])
    if not rows:
        return _err(404, "ITEM_NOT_FOUND", "약 줄을 찾을 수 없어요.")

    items = await conn.execute_query_dict(SQL_SELECT_ITEMS, [document_id])
    item = next(it for it in items if it["item_id"] == item_id)
    item["match_candidates"] = _load_json(item["match_candidates"]) or []
    return {"document_id": str(document_id), "item": item,
            "undecided": sum(1 for it in items if it["confirmed_by"] is None)}


# ---------------------------------------------------------------- R1
@drug_router.get("/search")
async def search_drugs(q: str = Query(..., min_length=2, max_length=60)):
    rows = await connections.get("default").execute_query_dict(SQL_NAME, [q.strip()])
    seen, out = set(), []
    for r in rows:
        if r["item_seq"] in seen:
            continue
        seen.add(r["item_seq"])
        out.append({"item_seq": r["item_seq"], "item_name": r["item_name"], "entp_name": r["entp_name"],
                    "ingredient": r["ingredient"], "has_ingr_code": bool(r["has_ingr_code"]),
                    "score": round(float(r["score"]), 3)})
    return {"query": q, "results": out[:10]}


# ---------------------------------------------------------------- D6
@review_router.put("/{document_id}/confirmation")
async def confirm_document(document_id: uuid.UUID):
    """[확인 완료]: 모든 약이 결정된 문서만 확정하고, 원본 파일과 OCR 원문을 즉시 지운다(D-03)."""
    async with in_transaction() as conn:
        doc = await _get_doc(conn, document_id, DEMO_USER_ID)
        if doc is None:
            return _err(404, "NOT_FOUND", "문서를 찾을 수 없어요.")
        if doc["status"] == "CONFIRMED":
            return _err(409, "ALREADY_CONFIRMED", "이미 확인을 마친 문서예요.")
        if doc["status"] != "MATCHED":
            return _err(409, "NOT_READY", "약 확인 단계가 끝난 문서만 확인 완료할 수 있어요.")
        left = await conn.execute_query_dict(
            "SELECT item_id FROM document_items WHERE document_id = $1 AND confirmed_by IS NULL ORDER BY line_no",
            [document_id])
        if left:
            return _err(409, "ITEMS_NOT_CONFIRMED", "확인하지 않은 약이 있어요.",
                        item_ids=[r["item_id"] for r in left])
        # 약이 하나도 없는 문서를 확정하면 원본만 지워지고 남는 게 없다. 지금은 막아 둔다(결정 필요).
        n = await conn.execute_query_dict("SELECT count(*) AS n FROM document_items WHERE document_id = $1",
                                          [document_id])
        if n[0]["n"] == 0:
            return _err(409, "NO_ITEMS", "읽은 약이 없어서 확인 완료할 수 없어요. 다시 찍어 주세요.")
        await conn.execute_query_dict(
            "UPDATE documents SET status = 'CONFIRMED', confirmed_at = now() WHERE document_id = $1", [document_id])
        # 삭제 기록 해시(fn_subject_hash)가 쓰는 비밀값. 이 트랜잭션에만 적용한다(P-09).
        pepper = os.getenv("HASH_PEPPER")
        if not pepper:
            return _err(500, "SERVER_CONFIG", "서버 설정에 문제가 있어요. 잠시 뒤 다시 시도해 주세요.")
        await conn.execute_query_dict("SELECT set_config('app.hash_pepper', $1, true)", [pepper])
        purged = await conn.execute_query_dict("SELECT fn_purge_original($1) AS path", [document_id])
        path = purged[0]["path"]

    # 파일 삭제는 DB 커밋 뒤에. 업로드 폴더 밖의 경로는 지우지 않는다.
    deleted = False
    if path:
        p = Path(path).resolve()
        root = UPLOAD_ROOT.resolve()
        if root in p.parents:
            p.unlink(missing_ok=True)
            deleted = True
    return {"document_id": str(document_id), "status": "CONFIRMED", "original_deleted": deleted}
