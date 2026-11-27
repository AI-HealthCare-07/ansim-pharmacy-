-- 주성분코드 교정·채움 전(백업) vs 후(현재): 정상 품목 중 dur_rules 성분코드(9자리 정확 일치)와 이어지는 품목 수. 읽기 전용.
-- 실행: docker exec -i postgres psql -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-ai_health}" < scripts/compare_correction_effect.sql
WITH codes AS (
  SELECT ingr_code_a AS c FROM dur_rules WHERE ingr_code_a IS NOT NULL
  UNION SELECT ingr_code_b FROM dur_rules WHERE ingr_code_b IS NOT NULL),
bak AS (SELECT DISTINCT e.item_seq FROM medicine_edi_codes_bak_20261127 e JOIN medicines m USING (item_seq)
         WHERE m.cancel_name='정상' AND e.main_ingredient_code IN (SELECT c FROM codes)),
cur AS (SELECT DISTINCT e.item_seq FROM medicine_edi_codes e JOIN medicines m USING (item_seq)
         WHERE m.cancel_name='정상' AND e.main_ingredient_code IN (SELECT c FROM codes))
SELECT (SELECT count(*) FROM codes)                                   AS 규칙_성분코드_수,
       (SELECT count(*) FROM bak)                                     AS 교정전_연결_품목,
       (SELECT count(*) FROM cur)                                     AS 교정후_연결_품목,
       (SELECT count(*) FROM cur WHERE item_seq NOT IN (SELECT item_seq FROM bak)) AS 새로_연결,
       (SELECT count(*) FROM bak WHERE item_seq NOT IN (SELECT item_seq FROM cur)) AS 연결_잃음;
