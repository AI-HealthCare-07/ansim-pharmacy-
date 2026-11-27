-- 11/27 질문 1: "잘 모르겠어요"를 저장하기 위해 confirmed_by에 UNKNOWN 추가
BEGIN;
ALTER TABLE document_items DROP CONSTRAINT IF EXISTS ck_items_confirmed_by;
ALTER TABLE document_items ADD CONSTRAINT ck_items_confirmed_by
  CHECK (confirmed_by IS NULL OR confirmed_by IN ('AUTO','USER','UNKNOWN'));
COMMIT;
