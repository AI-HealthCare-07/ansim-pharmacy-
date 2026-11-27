-- 성분코드 없는 약의 성분명이 규칙(dur_rules) 성분명 + 공백 + 뒤말 형태인 경우를 눈으로 확인한다. 읽기 전용(저장·수정 없음).
-- 사용: docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" < scripts/diag_nocode_sample.sql

\echo '=== E. 성분명 쌍 무작위 60개 (약의 성분명 / 규칙 성분명 / 뒤에 붙은 말 / 해당 약 수) ==='
WITH rn AS (
  SELECT DISTINCT lower(trim(ingr_name_a)) AS nm FROM dur_rules WHERE coalesce(ingr_name_a,'') <> ''
),
nocode AS (
  SELECT lower(trim(m.item_ingr_name)) AS ingr, count(*) AS n
    FROM medicines m
   WHERE m.cancel_name = '정상' AND coalesce(m.item_ingr_name,'') <> ''
     AND NOT EXISTS (SELECT 1 FROM v_item_ingredients i WHERE i.item_seq = m.item_seq)
   GROUP BY 1
),
pairs AS (
  SELECT n.ingr, r.nm, n.n
    FROM nocode n JOIN rn r ON n.ingr LIKE r.nm || ' %'
)
SELECT left(ingr, 40) AS 약의_성분명, left(nm, 24) AS 규칙_성분명,
       left(substr(ingr, length(nm) + 2), 24) AS 뒤에_붙은_말, n AS 약수
  FROM pairs ORDER BY random() LIMIT 60;

\echo '=== F. 약 하나가 규칙 성분명 여러 개와 동시에 걸리는 성분명(오탐 의심) 개수 ==='
WITH rn AS (
  SELECT DISTINCT lower(trim(ingr_name_a)) AS nm FROM dur_rules WHERE coalesce(ingr_name_a,'') <> ''
),
nocode AS (
  SELECT DISTINCT lower(trim(m.item_ingr_name)) AS ingr
    FROM medicines m
   WHERE m.cancel_name = '정상' AND coalesce(m.item_ingr_name,'') <> ''
     AND NOT EXISTS (SELECT 1 FROM v_item_ingredients i WHERE i.item_seq = m.item_seq)
)
SELECT count(*) AS 규칙에_걸리는_성분명,
       count(*) FILTER (WHERE k > 1) AS 규칙_둘_이상에_걸림
  FROM (SELECT n.ingr, count(*) AS k FROM nocode n JOIN rn r ON n.ingr LIKE r.nm || ' %' GROUP BY n.ingr) t;
