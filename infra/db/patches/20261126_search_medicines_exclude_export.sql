BEGIN;
CREATE OR REPLACE FUNCTION fn_search_medicines(p_query TEXT, p_limit INT DEFAULT 10)
RETURNS TABLE (item_seq item_seq_t, item_name TEXT, entp_name TEXT, score NUMERIC)
LANGUAGE sql STABLE AS $$
  -- 괄호 속 성분명은 정규화에서 지워지므로 원래 이름으로도 찾는다(0.6점, 자동 확인 0.7 미만)
  -- 검색어에만 함량이 있고 제품명에는 없을 때(예: 지르텍정 10mg / 지르텍정(세티리진염산염))
  -- 함량을 뗀 이름으로 찾는다: 이름이 같으면 0.85, 그 이름으로 시작하면 0.75(여럿이면 동점 → 자동 확인 안 됨)
  WITH q AS (SELECT fn_norm_drug_name(p_query) AS qn,
                    regexp_replace(p_query, '\s', '', 'g') AS qr),
       q2 AS (SELECT qn, qr,
                     regexp_replace(qn, '[0-9][0-9./]*(mg|mcg|g|ml|iu)?$', '', 'i') AS qb
                FROM q)
  SELECT m.item_seq::item_seq_t, m.item_name, m.entp_name,
         round(greatest(
           similarity(fn_norm_drug_name(m.item_name), q2.qn),
           CASE WHEN fn_norm_drug_name(m.item_name) LIKE q2.qn || '%' THEN 0.9 ELSE 0 END,
           CASE WHEN q2.qb <> q2.qn AND fn_norm_drug_name(m.item_name) = q2.qb THEN 0.85 ELSE 0 END,
           CASE WHEN q2.qb <> q2.qn AND fn_norm_drug_name(m.item_name) LIKE q2.qb || '%' THEN 0.75 ELSE 0 END,
           CASE WHEN m.item_name LIKE '%' || q2.qr || '%' THEN 0.6 ELSE 0 END
         )::numeric, 3)
    FROM medicines m, q2
   WHERE m.cancel_name = '정상'
     AND m.item_name NOT LIKE '%수출용%'  -- 국내 조제되지 않는 수출용 제품 제외(수출명만 적힌 국내 제품은 남김)
     AND length(q2.qn) >= 2
     AND (fn_norm_drug_name(m.item_name) % q2.qn
          OR fn_norm_drug_name(m.item_name) LIKE '%' || q2.qn || '%'
          OR m.item_name LIKE '%' || q2.qr || '%'
          OR (q2.qb <> q2.qn AND length(q2.qb) >= 2
              AND fn_norm_drug_name(m.item_name) LIKE q2.qb || '%'))
   ORDER BY 4 DESC, length(m.item_name)
   LIMIT p_limit
$$;
COMMIT;
