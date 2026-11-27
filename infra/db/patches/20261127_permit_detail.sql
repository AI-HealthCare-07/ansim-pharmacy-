-- 11/27 허가 상세 보충: DUR 품목정보 API에 없는 정상 약(11,714건)의 효능·용법·주의사항 본문과 주성분(M코드)을 담는다.
-- 원천: 식약처 의약품 제품 허가정보 상세(DrugPrdtPrmsnInfoService08/getDrugPrdtPrmsnDtlInq08).
-- medicines 는 건드리지 않고 별도 테이블에 둔다(적재 스크립트가 doc_id 빈 칸만 선택적으로 채움).
BEGIN;
CREATE TABLE IF NOT EXISTS medicine_permit_detail (
  item_seq       TEXT PRIMARY KEY,
  ee_doc_data    TEXT,            -- 효능효과 XML 원문
  ud_doc_data    TEXT,            -- 용법용량 XML 원문
  nb_doc_data    TEXT,            -- 사용상의주의사항 XML 원문
  main_item_ingr TEXT,            -- 원문 그대로 "[M코드]성분명|…"
  atc_code       TEXT,            -- 참고용. 규칙 연결에는 쓰지 않는다
  edi_code       TEXT,
  chart          TEXT,            -- 성상(복약지도서 '의약품의 명칭(성상 포함)')
  storage_method TEXT,            -- 저장방법(복약지도서 항목 5)
  valid_term     TEXT,
  change_date    TEXT,
  source_label   TEXT NOT NULL,
  fetched_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS medicine_permit_ingredients (
  item_seq  TEXT NOT NULL,
  m_code    TEXT NOT NULL,        -- 식약처 원료 코드(M…). 심평원 9자리 주성분코드·DUR 성분코드와 다른 체계
  ingr_name TEXT,
  PRIMARY KEY (item_seq, m_code)
);
CREATE INDEX IF NOT EXISTS idx_permit_ingr_m ON medicine_permit_ingredients (m_code);
COMMENT ON TABLE medicine_permit_detail IS '허가 상세(식약처) 본문. 안내 문구의 근거 원문이며 DUR 판정 근거가 아니다.';
COMMIT;
