-- 11/27 상병코드 사전: 심평원 상병마스터(20260331)를 담는다. 처방전의 상병코드가 실제 있는 코드인지 확인하고 이름을 붙이는 용도.
-- 같은 코드가 여러 줄(대표명 + 동의어)로 들어 있어 코드당 첫 줄만 적재한다. 코드는 소수점 없이 저장한다(E119).
BEGIN;
CREATE TABLE IF NOT EXISTS kcd_codes (
  sick_cd       TEXT PRIMARY KEY,          -- 상병기호(소수점 없음)
  name_ko       TEXT NOT NULL,             -- 한글명(코드당 첫 줄)
  name_en       TEXT,
  complete_flag TEXT,                      -- 완전코드구분 원본값
  main_flag     TEXT,                      -- 주상병사용구분 원본값
  cdd_class     TEXT,                      -- 법정감염병구분(제1~4급)
  sex_flag      TEXT,                      -- 성별구분 원본값(의미는 원본 설명서로 확인 필요)
  max_age       SMALLINT,
  min_age       SMALLINT,
  oriental_type TEXT,                      -- 양한방구분
  source_label  TEXT NOT NULL,             -- 출처 파일명
  loaded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE kcd_codes IS '심평원 상병마스터 기반 상병코드 사전. 코드 검증과 이름 표시용이며 진단 근거가 아니다.';
COMMIT;
