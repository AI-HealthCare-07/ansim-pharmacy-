-- 분류번호 예규 제223호 별표 전사본 vs medicines 분류 비교 (읽기 전용 + 임시 테이블)
-- 실행: psql "$DATABASE_URL" -f scripts/diag_class_table.sql   (프로젝트 루트에서)
CREATE TEMP TABLE law_class(class_no text, class_name text, level text, note text);
\copy law_class FROM 'docs/ref/law_tables/class223_table.csv' CSV HEADER
-- 0. 저장 형식 확인(상위 10)
SELECT class_no, class_name, count(*) FROM medicines GROUP BY 1,2 ORDER BY 3 DESC LIMIT 10;
-- A. 분류번호가 있는 약 중 별표에 없는 번호
SELECT class_no, count(*) AS 건수 FROM medicines
 WHERE class_no IS NOT NULL AND class_no<>'' AND class_no NOT IN (SELECT class_no FROM law_class)
 GROUP BY 1 ORDER BY 2 DESC LIMIT 30;
-- B. 번호는 있으나 이름이 별표와 다른 경우(공백 제거 비교)
SELECT m.class_no, m.class_name AS db_name, l.class_name AS law_name, count(*) AS 건수
  FROM medicines m JOIN law_class l USING(class_no)
 WHERE replace(coalesce(m.class_name,''),' ','') <> replace(l.class_name,' ','')
 GROUP BY 1,2,3 ORDER BY 4 DESC LIMIT 30;
-- C. 분류번호 없는 약 수(별도 공백)
SELECT count(*) AS 분류번호_없음 FROM medicines WHERE class_no IS NULL OR class_no='';
