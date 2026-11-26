BEGIN;
CREATE OR REPLACE FUNCTION public.fn_search_medicines(p_query text, p_limit integer DEFAULT 10)
 RETURNS TABLE(item_seq item_seq_t, item_name text, entp_name text, score numeric)
 LANGUAGE sql STABLE
AS $function$
  WITH q AS (SELECT fn_norm_drug_name(p_query) AS qn,
                    regexp_replace(p_query, '\s', '', 'g') AS qr)
  SELECT m.item_seq::item_seq_t, m.item_name, m.entp_name,
         round(greatest(
           similarity(fn_norm_drug_name(m.item_name), q.qn),
           CASE WHEN fn_norm_drug_name(m.item_name) LIKE q.qn || '%' THEN 0.9 ELSE 0 END,
           CASE WHEN m.item_name LIKE '%' || q.qr || '%' THEN 0.6 ELSE 0 END
         )::numeric, 3)
    FROM medicines m, q
   WHERE m.cancel_name = '정상'
     AND length(q.qn) >= 2
     AND (fn_norm_drug_name(m.item_name) % q.qn
          OR fn_norm_drug_name(m.item_name) LIKE '%' || q.qn || '%'
          OR m.item_name LIKE '%' || q.qr || '%')
   ORDER BY 4 DESC, length(m.item_name)
   LIMIT p_limit
$function$;
COMMIT;
