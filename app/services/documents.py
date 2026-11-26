"""문서 업로드(DOC-001): 형식·크기·쪽수 검사, HEIC→JPG 변환, 비공개 폴더 저장, 동의와 함께 DB 기록."""
from __future__ import annotations

import hashlib
import io
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pillow_heif
import pymupdf
from PIL import Image

from app.repositories import document_repository as repo

pillow_heif.register_heif_opener()

MAX_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 50
UPLOAD_ROOT = Path("data/uploads")
RETENTION = timedelta(hours=24)
DOC_TYPES = {"PRESCRIPTION", "MED_BAG", "MEDICAL_RECORD_PDF", "OTHER"}
HEIC_BRANDS = {b"heic", b"heix", b"hevc", b"heim", b"heis", b"mif1", b"msf1"}


class UploadError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def sniff_mime(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:5] == b"%PDF-":
        return "application/pdf"
    if data[4:8] == b"ftyp" and data[8:12] in HEIC_BRANDS:
        return "image/heic"
    return None


@dataclass
class PreparedFile:
    data: bytes
    mime_type: str
    ext: str
    page_count: int | None
    sha256: str


def prepare_file(raw: bytes) -> PreparedFile:
    if not raw:
        raise UploadError(400, "EMPTY_FILE", "빈 파일이에요.")
    if len(raw) > MAX_BYTES:
        raise UploadError(413, "FILE_TOO_LARGE", "파일은 20MB 이하만 올릴 수 있어요.")
    mime = sniff_mime(raw)
    if mime is None:
        raise UploadError(415, "UNSUPPORTED_TYPE", "JPG, PNG, HEIC, PDF 파일만 올릴 수 있어요.")

    page_count = None
    if mime == "application/pdf":
        try:
            doc = pymupdf.open(stream=raw, filetype="pdf")
        except Exception:
            raise UploadError(400, "BROKEN_PDF", "PDF 파일을 열 수 없어요.")
        if doc.needs_pass:
            doc.close()
            raise UploadError(400, "ENCRYPTED_PDF", "암호가 걸린 PDF는 올릴 수 없어요.")
        page_count = doc.page_count
        doc.close()
        if page_count > MAX_PDF_PAGES:
            raise UploadError(413, "TOO_MANY_PAGES", "PDF는 50쪽 이하만 올릴 수 있어요.")
        data, ext = raw, "pdf"
    elif mime == "image/heic":
        try:
            img = Image.open(io.BytesIO(raw)).convert("RGB")
        except Exception:
            raise UploadError(400, "BROKEN_IMAGE", "사진 파일을 열 수 없어요.")
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=92)
        data, mime, ext = buf.getvalue(), "image/jpeg", "jpg"
    else:
        try:
            Image.open(io.BytesIO(raw)).verify()
        except Exception:
            raise UploadError(400, "BROKEN_IMAGE", "사진 파일을 열 수 없어요.")
        data, ext = raw, ("jpg" if mime == "image/jpeg" else "png")

    if len(data) > MAX_BYTES:
        raise UploadError(413, "FILE_TOO_LARGE", "변환한 파일이 20MB를 넘어요.")
    return PreparedFile(data, mime, ext, page_count, hashlib.sha256(raw).hexdigest())


async def save_upload(
    *, user_id: int, doc_type: str, filename: str | None, raw: bytes,
    consent_document_processing: bool, consent_health_sensitive: bool, user_agent: str | None,
) -> dict:
    if doc_type not in DOC_TYPES:
        raise UploadError(400, "INVALID_DOC_TYPE", "문서 종류를 다시 골라 주세요.")
    if not (consent_document_processing and consent_health_sensitive):
        raise UploadError(400, "CONSENT_REQUIRED",
                          "문서 처리 동의와 건강 민감정보 동의를 모두 체크해야 문서를 읽을 수 있어요.")

    f = prepare_file(raw)
    if doc_type == "MEDICAL_RECORD_PDF" and f.mime_type != "application/pdf":
        raise UploadError(400, "PDF_REQUIRED", "진료기록은 PDF 파일로 올려 주세요.")
    track = "A_PDF_PARSE" if doc_type == "MEDICAL_RECORD_PDF" else "B_OCR"

    document_id = uuid.uuid4()
    user_dir = UPLOAD_ROOT / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(user_dir, 0o700)
    path = user_dir / f"{document_id}.{f.ext}"
    path.write_bytes(f.data)
    os.chmod(path, 0o600)

    try:
        row = await repo.create_document_with_consents(
            document_id=document_id, user_id=user_id, doc_type=doc_type, source_track=track,
            original_filename=os.path.basename(filename or "upload")[:200], mime_type=f.mime_type,
            file_size_bytes=len(f.data), page_count=f.page_count, file_sha256=f.sha256,
            storage_path=str(path), purge_after=datetime.now(timezone.utc) + RETENTION,
            user_agent=(user_agent or "")[:300] or None,
        )
    except Exception as e:
        path.unlink(missing_ok=True)
        if "CONSENT_REQUIRED" in str(e):
            raise UploadError(403, "CONSENT_REQUIRED", "동의가 확인되지 않아 문서를 저장하지 않았어요.")
        raise

    result = {**row, "doc_type": doc_type, "source_track": track,
              "mime_type": f.mime_type, "page_count": f.page_count}
    if f.mime_type.startswith("image/"):  # PDF는 품질 판정에서 제외(DOC-006)
        result.update(await assess_image_quality(document_id, path))
    return result


RETAKE_MESSAGES = {
    "TOO_FEW_CHARS": "글자가 거의 읽히지 않았어요. 문서 전체가 화면에 들어오게 다시 찍어 주세요.",
    "LOW_CONFIDENCE": "사진이 흐리거나 어두워 글자를 정확히 읽기 어려워요. 밝은 곳에서 흔들리지 않게 다시 찍어 주세요.",
}


async def assess_image_quality(document_id: uuid.UUID, path: Path) -> dict:
    """DOC-006: 사진 품질 판단. OCR 원문은 가림(6번) 전이라 저장하지 않는다."""
    from decimal import Decimal

    from starlette.concurrency import run_in_threadpool

    from app.services.ocr import judge_quality, run_ocr

    try:
        v = await run_in_threadpool(lambda: judge_quality(run_ocr(str(path))))
    except Exception:
        await repo.update_ocr_quality(document_id, "FAILED", None, None, "OCR_FAILED")
        return {"status": "FAILED", "quality": None,
                "message": "글자를 읽는 중 문제가 생겼어요. 잠시 뒤 다시 올려 주세요."}

    status = "EXTRACTED" if v.ok else "NEEDS_RETAKE"
    await repo.update_ocr_quality(document_id, status, Decimal(str(v.avg_score)), v.char_count, v.reason)
    return {
        "status": status,
        "quality": {"ok": v.ok, "reason": v.reason, "avg_confidence": v.avg_score, "char_count": v.char_count},
        "message": RETAKE_MESSAGES.get(v.reason) if v.reason else None,
    }
