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
