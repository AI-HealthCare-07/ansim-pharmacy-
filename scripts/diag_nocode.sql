-- 주성분코드가 없는 정상 약의 특징을 센다. 읽기 전용.
-- 사용: docker exec -i postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" < scripts/diag_nocode.sql
-- 임시 테이블(세션 안에서만 존재, 디스크에 남지 않음)에 한 번 모아 아래 쿼리에서 함께 쓴다.
CREATE TEMP TABLE nc AS (
  SELECT m.* FROM medicines m
  WHERE m.cancel_name='정상'
    AND NOT EXISTS (SELECT 1 FROM v_item_ingredients v WHERE v.item_seq=m.item_seq)
);
-- A. 전체
SELECT '전체 코드없음' AS 구분, count(*) FROM nc;

-- B. 전문/일반
SELECT coalesce(etc_otc_name,'(없음)') AS 전문일반, count(*) FROM nc GROUP BY 1 ORDER BY 2 DESC;

-- C. EDI 코드 유무(급여 청구 이력 단서)
SELECT (coalesce(edi_code,'')<>'') AS edi있음, count(*) FROM nc GROUP BY 1;

-- D. 허가 연도
SELECT left(item_permit_date,4) AS 허가연도, count(*) FROM nc GROUP BY 1 ORDER BY 1 DESC LIMIT 15;

-- E. 코드 있는 약과 비교: EDI 유무
SELECT (coalesce(m.edi_code,'')<>'') AS edi있음, count(*) AS 코드있는약
  FROM medicines m
 WHERE m.cancel_name='정상' AND EXISTS (SELECT 1 FROM v_item_ingredients v WHERE v.item_seq=m.item_seq)
 GROUP BY 1;
