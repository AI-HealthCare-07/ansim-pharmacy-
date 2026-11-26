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

STRUCT_ERR_STATUS = {"PII_RESIDUAL": 422, "NO_API_KEY": 500, "STRUCTURE_INVALID": 502}


@document_router.post("/{document_id}/structure")
async def structure_document(document_id: _uuid.UUID):
    row = await _repo.get_for_structure(document_id, DEMO_USER_ID)
    if row is None:
        return JSONResponse(status_code=404, content={"error_code": "NOT_FOUND", "message": "문서를 찾을 수 없어요."})
    raw = row["ocr_raw"]
    raw = _json.loads(raw) if isinstance(raw, str) else raw
    if not raw or row["status"] not in ("EXTRACTED", "STRUCTURED"):
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
    return {"document_id": str(document_id), "status": "STRUCTURED", "structured": data, "usage": usage}
