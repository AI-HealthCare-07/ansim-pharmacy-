-- 정상 약 중 효능·용법·주의사항 문서 ID(ee/ud/nb_doc_id)가 비어 있는 약의 특징을 센다. 읽기 전용.
-- 사용: set -a; source .env; set +a
--       docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" < scripts/diag_nodoc.sql
\echo '=== A. 문서ID 유무 x DUR 품목정보 컬럼(바코드·원료성분·보관방법·유효기간) 유무 ==='
SELECT (coalesce(nb_doc_id,'')<>'') AS 문서ID있음,
       (coalesce(bar_code,'')<>'' OR coalesce(material_name,'')<>'' OR coalesce(storage_method,'')<>'' OR coalesce(valid_term,'')<>'') AS 품목정보컬럼있음,
       count(*) AS 약수
  FROM medicines WHERE cancel_name='정상' GROUP BY 1,2 ORDER BY 1,2;

\echo '=== B. 전문/일반(spclty_pblc) x 문서ID 유무 ==='
SELECT coalesce(nullif(spclty_pblc,''),'(빈값)') AS 구분,
       count(*) AS 약수,
       count(*) FILTER (WHERE coalesce(nb_doc_id,'')='') AS 문서ID없음,
       round(100.0*count(*) FILTER (WHERE coalesce(nb_doc_id,'')='')/count(*),1) AS 없음비율
  FROM medicines WHERE cancel_name='정상' GROUP BY 1 ORDER BY 2 DESC;

\echo '=== C. 허가연도 x 문서ID 없음 비율 ==='
SELECT CASE WHEN left(item_permit_date,4) ~ '^[0-9]{4}$' THEN left(item_permit_date,4) ELSE '(빈값/형식이상)' END AS 허가연도,
       count(*) AS 약수,
       count(*) FILTER (WHERE coalesce(nb_doc_id,'')='') AS 문서ID없음,
       round(100.0*count(*) FILTER (WHERE coalesce(nb_doc_id,'')='')/count(*),1) AS 없음비율
  FROM medicines WHERE cancel_name='정상' GROUP BY 1 ORDER BY 1 DESC LIMIT 15;

\echo '=== D. 다른 출처 보유 여부 x 문서ID 없음 ==='
SELECT 'e약은요 본문 있음' AS 구분, count(*) FILTER (WHERE coalesce(efcy_qesitm,'')<>'') AS 약수,
       count(*) FILTER (WHERE coalesce(efcy_qesitm,'')<>'' AND coalesce(nb_doc_id,'')='') AS 문서ID없음 FROM medicines WHERE cancel_name='정상'
UNION ALL
SELECT '낱알(모양) 정보 있음', count(*) FILTER (WHERE coalesce(drug_shape,'')<>''),
       count(*) FILTER (WHERE coalesce(drug_shape,'')<>'' AND coalesce(nb_doc_id,'')='') FROM medicines WHERE cancel_name='정상'
UNION ALL
SELECT 'EDI코드 있음', count(*) FILTER (WHERE coalesce(edi_code,'')<>''),
       count(*) FILTER (WHERE coalesce(edi_code,'')<>'' AND coalesce(nb_doc_id,'')='') FROM medicines WHERE cancel_name='정상'
UNION ALL
SELECT '허가 마스터 원료(item_ingr_name) 있음', count(*) FILTER (WHERE coalesce(item_ingr_name,'')<>''),
       count(*) FILTER (WHERE coalesce(item_ingr_name,'')<>'' AND coalesce(nb_doc_id,'')='') FROM medicines WHERE cancel_name='정상';

\echo '=== E. 분류번호(class_no 앞 3자리) 중 문서ID 없는 약이 많은 상위 12 ==='
SELECT coalesce(nullif(left(class_no,3),''),'(빈값)') AS 분류, count(*) AS 약수,
       count(*) FILTER (WHERE coalesce(nb_doc_id,'')='') AS 문서ID없음
  FROM medicines WHERE cancel_name='정상' GROUP BY 1 ORDER BY 3 DESC LIMIT 12;

\echo '=== F. 문서ID 없는 약 무작위 10건 ==='
SELECT item_seq, left(item_name,24) AS 이름, spclty_pblc AS 구분, left(item_permit_date,8) AS 허가일,
       (coalesce(bar_code,'')<>'') AS 바코드, (coalesce(efcy_qesitm,'')<>'') AS e약은요
  FROM medicines WHERE cancel_name='정상' AND coalesce(nb_doc_id,'')='' ORDER BY random() LIMIT 10;
