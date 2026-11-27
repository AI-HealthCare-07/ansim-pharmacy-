-- 약제급여목록 월별 판 이력 + 주성분코드 출처 판 기록 (2026-11-27)
-- 원칙: 급여목록 엑셀의 (제품코드=EDI 9자리 → 주성분코드) 정확 일치만 사용. 이름·성분 유사 추정 없음.
-- 기존 값은 바꾸지 않음. 컬럼 추가 + 새 테이블 + 새 뷰만.
BEGIN;

CREATE TABLE IF NOT EXISTS benefit_list_versions (
  list_month    TEXT PRIMARY KEY,          -- '2026-11'
  base_date     DATE NOT NULL,             -- 파일명에 적힌 기준일 (예: 2026.11.1.)
  source_file   TEXT NOT NULL,
  sheet_name    TEXT,
  row_count     INTEGER NOT NULL,
  loaded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS benefit_list_entries (
  list_month            TEXT NOT NULL REFERENCES benefit_list_versions(list_month),
  edi_code              TEXT NOT NULL,     -- 제품코드(EDI 9자리)
  main_ingredient_code  TEXT,              -- 주성분코드 (9자리)
  same_form_code        TEXT,              -- 주성분코드_동일제형
  ingredient_name       TEXT,
  product_name          TEXT,
  company_name          TEXT,
  note                  TEXT,              -- 비고 원문 (등재·정지 표기 등)
  PRIMARY KEY (list_month, edi_code)
);
CREATE INDEX IF NOT EXISTS idx_benefit_entries_edi ON benefit_list_entries (edi_code);

ALTER TABLE medicine_edi_codes
  ADD COLUMN IF NOT EXISTS ingredient_source_list      TEXT,     -- 주성분코드를 가져온 급여목록 판 ('2026-10')
  ADD COLUMN IF NOT EXISTS ingredient_in_current_list  BOOLEAN;  -- 그 판이 가장 최근 적재 판인지

COMMENT ON COLUMN medicine_edi_codes.ingredient_source_list IS '주성분코드 출처: benefit_list_versions.list_month. NULL = 출처 판 미기록(기존 적재분)';
COMMENT ON COLUMN medicine_edi_codes.ingredient_in_current_list IS 'FALSE = 최근 판에는 없고 이전 판 값을 사용. 화면은 "급여목록 {판} 기준"으로 표시, 급여 여부는 말하지 않음';

CREATE OR REPLACE VIEW v_item_ingredients_src AS
SELECT DISTINCT e.item_seq, e.main_ingredient_code, e.ingredient_group_code,
       e.ingredient_source_list, e.ingredient_in_current_list
  FROM medicine_edi_codes e
 WHERE e.main_ingredient_code IS NOT NULL;

COMMIT;
