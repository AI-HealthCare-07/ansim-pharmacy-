-- 코드 없는 약 14,970건의 원인을 더 좁힌다. 읽기 전용(임시 테이블만 사용).
-- 사용: docker exec -i postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" < scripts/diag_nocode2.sql
CREATE TEMP TABLE nc AS (
  SELECT m.* FROM medicines m
  WHERE m.cancel_name='정상'
    AND NOT EXISTS (SELECT 1 FROM v_item_ingredients v WHERE v.item_seq=m.item_seq)
);

\echo '=== 1. 코드 없는 약: medicine_edi_codes 에 줄이 있나 (줄 있음/없음 × medicines.edi_code 유무) ==='
SELECT (coalesce(nc.edi_code,'')<>'') AS medicines_edi있음,
       EXISTS (SELECT 1 FROM medicine_edi_codes e WHERE e.item_seq=nc.item_seq) AS edi표_줄있음,
       count(*)
  FROM nc GROUP BY 1,2 ORDER BY 3 DESC;

\echo '=== 2. EDI는 있는데 코드 없는 약 표본 15 ==='
SELECT item_seq, left(item_name,24) AS 이름, edi_code, etc_otc_name, left(item_permit_date,4) AS 허가연도
  FROM nc WHERE coalesce(edi_code,'')<>'' ORDER BY item_seq LIMIT 15;

\echo '=== 3. 전문/일반 구분 없는 약 표본 15 ==='
SELECT item_seq, left(item_name,24) AS 이름, edi_code, left(item_permit_date,4) AS 허가연도
  FROM nc WHERE etc_otc_name IS NULL ORDER BY item_seq LIMIT 15;

\echo '=== 4. 구분 없는 약 중 표준코드(BarCodeData) 보유 / 분류번호 보유 ==='
SELECT (class_no IS NOT NULL AND class_no<>'') AS 분류번호있음, count(*) FROM nc WHERE etc_otc_name IS NULL GROUP BY 1;
