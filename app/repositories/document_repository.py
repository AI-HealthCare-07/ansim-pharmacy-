"""documents·consent_logs 저장. 동의 유효성 검사는 DB 트리거(fn_documents_check_consent)가 맡는다."""
from __future__ import annotations

import uuid
from datetime import datetime

from tortoise.transactions import in_transaction

CONSENT_TERMS_VERSION = "doc-consent-v1-20261125"

INSERT_CONSENT = """
INSERT INTO consent_logs (user_id, consent_type, action, terms_version, channel, scope, document_id, user_agent)
VALUES ($1, $2, 'AGREE', $3, 'UPLOAD', 'DOCUMENT', $4, $5)
RETURNING consent_log_id
"""

INSERT_DOCUMENT = """
INSERT INTO documents (document_id, user_id, consent_log_id, doc_type, source_track, original_filename,
                       mime_type, file_size_bytes, page_count, file_sha256, storage_path, purge_after)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
RETURNING document_id, status, created_at, purge_after
"""


async def create_document_with_consents(
    *, document_id: uuid.UUID, user_id: int, doc_type: str, source_track: str, original_filename: str,
    mime_type: str, file_size_bytes: int, page_count: int | None, file_sha256: str, storage_path: str,
    purge_after: datetime, user_agent: str | None,
) -> dict:
    """consent_logs.document_id 외래키는 DEFERRED라 문서 행보다 먼저 넣어도 커밋 때 검사된다."""
    async with in_transaction() as conn:
        rows = await conn.execute_query_dict(
            INSERT_CONSENT, [user_id, "DOCUMENT_PROCESSING", CONSENT_TERMS_VERSION, document_id, user_agent])
        doc_consent_id = rows[0]["consent_log_id"]
        await conn.execute_query_dict(
            INSERT_CONSENT, [user_id, "HEALTH_SENSITIVE", CONSENT_TERMS_VERSION, document_id, user_agent])
        rows = await conn.execute_query_dict(INSERT_DOCUMENT, [
            document_id, user_id, doc_consent_id, doc_type, source_track, original_filename,
            mime_type, file_size_bytes, page_count, file_sha256, storage_path, purge_after])
        return rows[0]
