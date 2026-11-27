-- 허가 상세 이력(수집일 기준 스냅샷). 허가사항은 과거 판을 나중에 되돌려 받을 수 없으므로 받을 때마다 변경된 판만 쌓는다.
-- medicine_permit_detail 은 '최신판', 이 테이블은 '판별 이력'. 조제일 기준 조회·"당시와 같은가" 판단의 근거가 된다.
-- 선행: 20261127_permit_detail.sql 적용 + load_permit_detail.py --apply 완료(첫 시점 = 그 적재본)
BEGIN;
CREATE TABLE IF NOT EXISTS medicine_permit_detail_history (
  id             BIGSERIAL PRIMARY KEY,
  item_seq       TEXT NOT NULL,
  content_hash   TEXT NOT NULL,   -- 본문·성상·저장방법·변경일 등 내용 해시(같은 내용이면 새 줄을 만들지 않음)
  ee_doc_data    TEXT,
  ud_doc_data    TEXT,
  nb_doc_data    TEXT,
  main_item_ingr TEXT,
  atc_code       TEXT,
  edi_code       TEXT,
  chart          TEXT,
  storage_method TEXT,
  valid_term     TEXT,
  change_date    TEXT,            -- 식약처 변경일자(의미 확인 전: 허가사항 전체의 변경일인지 미확정)
  source_label   TEXT NOT NULL,
  fetched_at     TIMESTAMPTZ NOT NULL   -- 이 판을 처음 수집한 시각
);
CREATE INDEX IF NOT EXISTS idx_permit_hist_item ON medicine_permit_detail_history (item_seq, id);

CREATE OR REPLACE FUNCTION permit_detail_hash(d medicine_permit_detail) RETURNS TEXT AS $$
  SELECT md5(concat_ws(E'\x1f', coalesce(d.ee_doc_data,''), coalesce(d.ud_doc_data,''), coalesce(d.nb_doc_data,''),
    coalesce(d.main_item_ingr,''), coalesce(d.atc_code,''), coalesce(d.edi_code,''), coalesce(d.chart,''),
    coalesce(d.storage_method,''), coalesce(d.valid_term,''), coalesce(d.change_date,'')))
$$ LANGUAGE sql IMMUTABLE;

-- 최신판이 마지막 이력과 다를 때만 새 줄을 추가한다(같으면 아무 것도 안 함).
CREATE OR REPLACE FUNCTION snapshot_permit_detail(p_item_seq TEXT) RETURNS VOID AS $$
  INSERT INTO medicine_permit_detail_history
    (item_seq, content_hash, ee_doc_data, ud_doc_data, nb_doc_data, main_item_ingr, atc_code, edi_code,
     chart, storage_method, valid_term, change_date, source_label, fetched_at)
  SELECT d.item_seq, permit_detail_hash(d), d.ee_doc_data, d.ud_doc_data, d.nb_doc_data, d.main_item_ingr,
         d.atc_code, d.edi_code, d.chart, d.storage_method, d.valid_term, d.change_date, d.source_label, d.fetched_at
    FROM medicine_permit_detail d
   WHERE d.item_seq = p_item_seq
     AND permit_detail_hash(d) IS DISTINCT FROM
         (SELECT h.content_hash FROM medicine_permit_detail_history h WHERE h.item_seq = p_item_seq ORDER BY h.id DESC LIMIT 1);
$$ LANGUAGE sql;

-- 첫 시점 백필: 지금 적재된 최신판을 이력의 첫 줄로 남긴다(이미 있으면 건너뜀).
SELECT snapshot_permit_detail(item_seq) FROM medicine_permit_detail;
COMMENT ON TABLE medicine_permit_detail_history IS '허가 상세의 수집일 기준 판 이력. 과거 허가사항 재현은 이 테이블에 쌓인 시점부터만 가능하다.';
COMMIT;
