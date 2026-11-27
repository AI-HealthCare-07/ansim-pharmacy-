from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

from app.services.documents import MAX_BYTES, UploadError, save_upload

DEMO_USER_ID = 1  # 12/4 초기 모델: 고정 사용자. 로그인 완성(12/7~8) 후 토큰의 사용자로 교체

document_router = APIRouter(prefix="/documents", tags=["documents"])


@document_router.post("", status_code=201)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    doc_type: str = Form(...),
    consent_document_processing: bool = Form(False),
    consent_health_sensitive: bool = Form(False),
):
    raw = await file.read(MAX_BYTES + 1)  # 20MB를 넘는지만 알면 되므로 그 이상은 읽지 않는다
    try:
        return await save_upload(
            user_id=DEMO_USER_ID, doc_type=doc_type, filename=file.filename, raw=raw,
            consent_document_processing=consent_document_processing,
            consent_health_sensitive=consent_health_sensitive,
            user_agent=request.headers.get("user-agent"),
        )
    except UploadError as e:
        return JSONResponse(status_code=e.status, content={"error_code": e.code, "message": e.message})


import json as _json
import uuid as _uuid

from app.repositories import document_repository as _repo
from app.services.structuring import StructuringError, structure_ocr
from app.services.matching import match_document

STRUCT_ERR_STATUS = {"PII_RESIDUAL": 422, "NO_API_KEY": 500, "STRUCTURE_INVALID": 502}


@document_router.post("/{document_id}/structure")
async def structure_document(document_id: _uuid.UUID):
    row = await _repo.get_for_structure(document_id, DEMO_USER_ID)
    if row is None:
        return JSONResponse(status_code=404, content={"error_code": "NOT_FOUND", "message": "문서를 찾을 수 없어요."})
    raw = row["ocr_raw"]
    raw = _json.loads(raw) if isinstance(raw, str) else raw
    if not raw or row["status"] not in ("EXTRACTED", "STRUCTURED", "MATCHED"):
        return JSONResponse(status_code=409, content={
            "error_code": "NOT_READY", "message": "글자 읽기가 끝난 문서만 정리할 수 있어요."})
    try:
        doc, usage = await structure_ocr(raw["lines"])
    except StructuringError as e:
        return JSONResponse(status_code=STRUCT_ERR_STATUS.get(e.code, 500),
                            content={"error_code": e.code, "message": e.message})
    except Exception:
        import logging
        logging.getLogger(__name__).exception("structure failed: %s", document_id)
        return JSONResponse(status_code=502, content={
            "error_code": "AI_UNAVAILABLE", "message": "AI 응답을 받지 못했어요. 잠시 뒤 다시 시도해 주세요."})
    data = doc.model_dump(mode="json")
    await _repo.save_structured(document_id, _json.dumps(data, ensure_ascii=False), doc.visit_date,
                                _json.dumps(data["diagnoses"], ensure_ascii=False))
    items = await match_document(document_id, data["drugs"])
    return {"document_id": str(document_id), "status": "MATCHED", "structured": data, "items": items, "usage": usage}


from pydantic import BaseModel as _BaseModel, Field as _Field

from app.services.structuring import KCD_RE as _KCD_RE


class DiagnosisEdit(_BaseModel):
    kcd_code: str | None = _Field(None, max_length=10)
    name: str | None = _Field(None, max_length=100)


class DiagnosesEditRequest(_BaseModel):
    diagnoses: list[DiagnosisEdit] = _Field(max_length=20)


@document_router.patch("/{document_id}/diagnoses")
async def edit_diagnoses(document_id: _uuid.UUID, body: DiagnosesEditRequest):
    items = []
    for d in body.diagnoses:
        code = (d.kcd_code or "").strip().upper().replace(" ", "") or None
        if code and not _KCD_RE.match(code):
            return JSONResponse(status_code=400, content={
                "error_code": "INVALID_KCD", "message": f"상병코드 형식이 맞지 않아요: {code} (예: I10.9)"})
        name = (d.name or "").strip() or None
        if code or name:
            items.append({"kcd_code": code, "name": name, "kcd_autocorrected": False, "user_edited": True})
    row = await _repo.update_diagnoses(document_id, DEMO_USER_ID, _json.dumps(items, ensure_ascii=False))
    if row is None:
        return JSONResponse(status_code=409, content={
            "error_code": "NOT_EDITABLE", "message": "정리가 끝났고 아직 확정하지 않은 문서만 고칠 수 있어요."})
    return {"document_id": str(document_id), "status": row["status"], "diagnoses": items}
