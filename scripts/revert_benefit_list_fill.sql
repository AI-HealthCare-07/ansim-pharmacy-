-- 2026-11-27 잠정 교정·채움 원상 복구 (확정되지 않을 경우). 실행: docker exec -i postgres psql ... < scripts/revert_benefit_list_fill.sql
BEGIN;
UPDATE medicine_edi_codes
   SET main_ingredient_code = ingredient_code_prev,
       ingredient_group_code = left(ingredient_code_prev, 4),
       ingredient_source_list = NULL, ingredient_in_current_list = NULL,
       ingredient_code_prev = NULL, ingredient_code_changed_at = NULL
 WHERE ingredient_code_changed_at IS NOT NULL AND ingredient_code_prev IS NOT NULL;   -- 교정된 행: 이전 값으로
UPDATE medicine_edi_codes
   SET main_ingredient_code = NULL, ingredient_group_code = NULL,
       ingredient_source_list = NULL, ingredient_in_current_list = NULL, ingredient_code_changed_at = NULL
 WHERE ingredient_code_changed_at IS NOT NULL AND ingredient_code_prev IS NULL;       -- 새로 채워진 행: 비움
UPDATE medicine_edi_codes SET ingredient_source_list = NULL, ingredient_in_current_list = NULL
 WHERE ingredient_source_list IS NOT NULL;                                            -- 출처 기록만 한 행
COMMIT;
-- 백업 테이블 medicine_edi_codes_bak_20261127 로 결과 비교 가능.
