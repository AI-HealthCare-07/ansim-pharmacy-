-- 잠정 교정(확정 아님): 되돌릴 수 있게 백업 + 이전 값 보관 컬럼. 기존 값은 이 패치에서 바꾸지 않음.
BEGIN;
CREATE TABLE IF NOT EXISTS medicine_edi_codes_bak_20261127 AS SELECT * FROM medicine_edi_codes;
ALTER TABLE medicine_edi_codes
  ADD COLUMN IF NOT EXISTS ingredient_code_prev       TEXT,          -- 교정 전 값(주성분코드_동일제형 열에서 들어간 값)
  ADD COLUMN IF NOT EXISTS ingredient_code_changed_at TIMESTAMPTZ;   -- 교정·채움 시각(잠정). NULL = 변경 없음
COMMENT ON COLUMN medicine_edi_codes.ingredient_code_prev IS '2026-11-27 교정 전 main_ingredient_code (잠정 교정, 확정 아님)';
COMMIT;
