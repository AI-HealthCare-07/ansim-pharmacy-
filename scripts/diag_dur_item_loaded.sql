-- DUR 품목정보 수집 스크립트(ingest_data_go_kr.py)로 들어온 값이 DB에 있는지 센다. 읽기 전용.
-- 사용: docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" < scripts/diag_dur_item_loaded.sql
\echo '=== 정상 약 전체와 DUR 품목정보 컬럼 채움 수 ==='
SELECT count(*)                                            AS 정상약,
       count(*) FILTER (WHERE coalesce(bar_code,'')      <> '') AS 바코드,
       count(*) FILTER (WHERE coalesce(material_name,'') <> '') AS 원료성분,
       count(*) FILTER (WHERE coalesce(nb_doc_id,'')     <> '') AS 주의사항문서,
       count(*) FILTER (WHERE coalesce(ee_doc_id,'')     <> '') AS 효능문서,
       count(*) FILTER (WHERE coalesce(ud_doc_id,'')     <> '') AS 용법문서
  FROM medicines WHERE cancel_name = '정상';
\echo '=== 성분코드 없는 정상 약 중 원료성분(material_name)이 있는 수 ==='
SELECT count(*) AS 코드없는약,
       count(*) FILTER (WHERE coalesce(m.material_name,'') <> '') AS 원료성분있음
  FROM medicines m
 WHERE m.cancel_name = '정상'
   AND NOT EXISTS (SELECT 1 FROM v_item_ingredients i WHERE i.item_seq = m.item_seq);
\echo '=== 원료성분 예시 3건 ==='
SELECT item_seq, left(item_name,20) AS 이름, left(material_name,120) AS 원료성분
  FROM medicines WHERE coalesce(material_name,'') <> '' ORDER BY random() LIMIT 3;
