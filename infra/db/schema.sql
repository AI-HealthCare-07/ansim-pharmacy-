-- =============================================================================
--  안심약국 (Ansim Pharmacy) — PostgreSQL 16 서비스 스키마
--  파일: infra/db/schema.sql
--  기준 문서: 요구사항 정의서 겸 계획서(261125, 신혜원) + 구현계획 엑셀(261125)
--  261125 수정: 기획 검토 결정 반영 → 맨 아래 20장 (docs/review/decision_log_261125.md)
--  대상: PostgreSQL 16 + pgvector(0.5 이상, 운영 0.8.x) + pg_trgm
--
--  [실행 전제]
--   이미 적재된 기존 3개 테이블(medicines, medicine_edi_codes, dur_rules)은
--   이 파일이 만들지 않는다. 이 파일은 그 위에 인덱스·보조 컬럼·FK·뷰와
--   서비스 테이블을 "덧붙인다". 여러 번 실행해도 안전하도록(IF NOT EXISTS,
--   존재 확인 DO 블록) 작성했다.
--
--  [새 환경 재현(12/15 docker compose) 순서]
--   1) infra/db/00_base_tables.sql   ← 현재 DB에서 아래 명령으로 덤프해 저장
--        pg_dump --schema-only -t medicines -t medicine_edi_codes -t dur_rules \
--                ansim > infra/db/00_base_tables.sql
--   2) scripts/ingest_data_go_kr.py 등 적재 스크립트 실행
--   3) psql -v ON_ERROR_STOP=1 -f infra/db/schema.sql      ← 이 파일
--
--  [요구사항 ID 표기]  USR 회원 / DOC 문서·OCR / MED 의약품·주의·안내 /
--                      CHT 챗봇 / SAF 안전 / SYS 시스템 / QAT 검증 / DAT 데이터
--
--  [설계 원칙]
--   · 상태·유형 값은 PostgreSQL ENUM 대신 TEXT + CHECK (값 추가 시 ALTER TYPE 불필요)
--   · 사용자 소유 데이터는 모두 users → ON DELETE CASCADE 경로로 연결 (USR-006 탈퇴 삭제)
--   · 외부 공개 ID(URL에 노출)는 UUID: documents, guides, chat_sessions
--   · LLM은 Claude API (개발 Haiku / 시연 Sonnet). 국외 처리위탁(Anthropic, 미국)은 개인정보 처리방침에 공개
--     → 별도 '외부 AI 전송' 동의 항목은 두지 않고, 건강 민감정보 동의 안내문에 전송 사실을 명시
--   · LLM 입력·DB 저장 전 식별정보 마스킹 항상 적용, 가린 건수 기록 (SYS-005)
--   · 보관 원칙: 정리된 처방 기록·안내서·시간표·대화는 회원 탈퇴 또는 이용자 직접 삭제 시까지,
--     원본 사진·PDF는 읽기 완료 후 24시간 (USR-006, SYS-001 / 처리방침 작성지침 2026.4. 생성형 AI 부록)
--   · AI 답변 신고(SAF-003): ai_output_reports / 개별 기록 삭제(USR-006): fn_delete_document
--   · 처방 약 근거는 DB 정확 조회, 벡터 임베딩은 생활 수칙 문서(kb_chunks)에만 사용
--     (계획서 7장 운영 규칙 / 엑셀 '1인 5주 가능성' 조건 2)
-- =============================================================================

\set ON_ERROR_STOP on
SET client_min_messages = notice;

BEGIN;

-- -----------------------------------------------------------------------------
-- 0. 확장
-- -----------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS vector;    -- RAG 임베딩 (MED-006, CHT-002)
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- 약 이름 유사도·자동완성 (DOC-004, DOC-005)

-- -----------------------------------------------------------------------------
-- 1. 사전 점검: 기존 적재 테이블·컬럼 존재 확인 + item_seq 타입 도메인 생성
--    (기존 테이블 구조가 다르면 여기서 명확한 메시지로 중단된다)
-- -----------------------------------------------------------------------------
DO $$
DECLARE
  req   CONSTANT text[][] := ARRAY[
          ['medicines','item_seq'], ['medicines','item_name'], ['medicines','entp_name'],
          ['medicines','edi_code'], ['medicines','cancel_name'],
          ['medicine_edi_codes','item_seq'], ['medicine_edi_codes','edi_code'],
          ['medicine_edi_codes','main_ingredient_code'], ['medicine_edi_codes','ingredient_group_code'],
          ['dur_rules','dur_type'], ['dur_rules','ingr_code_a'], ['dur_rules','ingr_code_b'],
          ['dur_rules','ingr_name_a'], ['dur_rules','ingr_name_b'], ['dur_rules','grade'],
          ['dur_rules','age_limit'], ['dur_rules','prohibition_content']];
  missing text := '';
  i int;
  seq_type text;
BEGIN
  FOR i IN 1 .. array_length(req, 1) LOOP
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = req[i][1] AND column_name = req[i][2]) THEN
      missing := missing || format(' %s.%s', req[i][1], req[i][2]);
    END IF;
  END LOOP;
  IF missing <> '' THEN
    RAISE EXCEPTION '기존 적재 테이블에 필요한 컬럼이 없습니다:%  (00_base_tables.sql·적재 스크립트를 먼저 실행하세요)', missing;
  END IF;

  -- medicines.item_seq 의 실제 타입(varchar/text/bigint 등)을 그대로 따르는 도메인.
  -- 서비스 테이블의 FK 컬럼은 모두 이 도메인을 써서 타입 불일치 FK 오류를 원천 차단한다.
  IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
                  WHERE t.typname = 'item_seq_t' AND n.nspname = current_schema()) THEN
    SELECT format_type(a.atttypid, a.atttypmod) INTO seq_type
      FROM pg_attribute a
     WHERE a.attrelid = 'medicines'::regclass AND a.attname = 'item_seq';
    EXECUTE format('CREATE DOMAIN item_seq_t AS %s', seq_type);
    RAISE NOTICE 'item_seq_t 도메인 생성: %', seq_type;
  END IF;

  -- medicines.item_seq 가 FK 대상이 되려면 PK 또는 UNIQUE 가 필요
  IF NOT EXISTS (
      SELECT 1 FROM pg_index ix
        JOIN pg_attribute a ON a.attrelid = ix.indrelid AND a.attnum = ANY(ix.indkey)
       WHERE ix.indrelid = 'medicines'::regclass AND (ix.indisprimary OR ix.indisunique)
         AND ix.indnatts = 1 AND a.attname = 'item_seq') THEN
    RAISE EXCEPTION 'medicines.item_seq 에 PRIMARY KEY/UNIQUE 제약이 없습니다.';
  END IF;
END $$;

-- -----------------------------------------------------------------------------
-- 2. 공통 함수
-- -----------------------------------------------------------------------------
-- updated_at 자동 갱신
CREATE OR REPLACE FUNCTION fn_set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END $$;

-- 약 이름 정규화: 괄호 성분명 제거, 공백 제거, 단위 한글→영문, 소문자
--   '타이레놀정500밀리그램(아세트아미노펜)' → '타이레놀정500mg'
--   OCR 결과('타이레놀정 500mg')와 허가 제품명을 같은 기준으로 비교 (DOC-004)
CREATE OR REPLACE FUNCTION fn_norm_drug_name(p text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT lower(
           replace(replace(replace(replace(
             regexp_replace(regexp_replace(coalesce(p, ''), '\([^)]*\)', '', 'g'), '\s+', '', 'g'),
           '밀리그램', 'mg'), '마이크로그램', 'mcg'), '밀리리터', 'ml'), '그램', 'g'))
$$;

-- -----------------------------------------------------------------------------
-- 3. 기존 적재 테이블 보강 (구조 변경 최소화: 인덱스 + dur_rules 식별 컬럼 + FK)
-- -----------------------------------------------------------------------------
-- 3-1) medicines: 이름 자동완성·유사도 매칭 (DOC-004, DOC-005 화면 2)
CREATE INDEX IF NOT EXISTS idx_medicines_norm_name_trgm
  ON medicines USING gin (fn_norm_drug_name(item_name) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_medicines_item_name_trgm
  ON medicines USING gin (item_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_medicines_cancel_name
  ON medicines (cancel_name);

-- 3-2) medicine_edi_codes: EDI 9자리 1순위 매칭 + 성분코드 → DUR 연결 다리
CREATE INDEX IF NOT EXISTS idx_med_edi_edi_code       ON medicine_edi_codes (edi_code);
CREATE INDEX IF NOT EXISTS idx_med_edi_item_seq       ON medicine_edi_codes (item_seq);
CREATE INDEX IF NOT EXISTS idx_med_edi_main_ingr      ON medicine_edi_codes (main_ingredient_code);
CREATE INDEX IF NOT EXISTS idx_med_edi_ingr_group     ON medicine_edi_codes (ingredient_group_code);

-- medicine_edi_codes.item_seq → medicines FK (없을 때만 추가).
-- 낱알·허가 불일치 고아 행이 있을 수 있어 NOT VALID 로 추가 → 아래 점검 쿼리로 확인 후 VALIDATE.
--   SELECT count(*) FROM medicine_edi_codes e LEFT JOIN medicines m USING (item_seq) WHERE m.item_seq IS NULL;
--   ALTER TABLE medicine_edi_codes VALIDATE CONSTRAINT fk_med_edi_item_seq;
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                  WHERE conrelid = 'medicine_edi_codes'::regclass AND contype = 'f'
                    AND confrelid = 'medicines'::regclass) THEN
    ALTER TABLE medicine_edi_codes
      ADD CONSTRAINT fk_med_edi_item_seq FOREIGN KEY (item_seq)
      REFERENCES medicines (item_seq) ON UPDATE CASCADE ON DELETE CASCADE NOT VALID;
  END IF;
END $$;

-- 3-3) dur_rules: 서비스 테이블이 참조할 수 있도록 대리키(dur_rule_id) 보장
--      기존 PK 유무와 무관하게 UNIQUE identity 컬럼을 추가 (28,502행 즉시 채번)
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                  WHERE table_schema = current_schema()
                    AND table_name = 'dur_rules' AND column_name = 'dur_rule_id') THEN
    ALTER TABLE dur_rules ADD COLUMN dur_rule_id BIGINT GENERATED BY DEFAULT AS IDENTITY;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                  WHERE conrelid = 'dur_rules'::regclass AND conname = 'uq_dur_rules_dur_rule_id') THEN
    ALTER TABLE dur_rules ADD CONSTRAINT uq_dur_rules_dur_rule_id UNIQUE (dur_rule_id);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_dur_rules_type         ON dur_rules (dur_type);
CREATE INDEX IF NOT EXISTS idx_dur_rules_ingr_a       ON dur_rules (ingr_code_a);
CREATE INDEX IF NOT EXISTS idx_dur_rules_ingr_b       ON dur_rules (ingr_code_b) WHERE ingr_code_b IS NOT NULL;

-- 3-4) 연결 뷰
-- 품목 → 성분코드 (DUR 성분코드 ↔ 심평원 주성분코드 연결의 단일 진입점)
CREATE OR REPLACE VIEW v_item_ingredients AS
SELECT DISTINCT e.item_seq, e.main_ingredient_code, e.ingredient_group_code
  FROM medicine_edi_codes e
 WHERE e.main_ingredient_code IS NOT NULL;

-- 정상 품목 검색 대상 (cancel_name = '정상'; 낱알 단독 3,579건 등 허가상태 빈 값 제외)
CREATE OR REPLACE VIEW v_active_medicines AS
SELECT m.item_seq, m.item_name, m.entp_name, m.edi_code,
       fn_norm_drug_name(m.item_name) AS norm_name
  FROM medicines m
 WHERE m.cancel_name = '정상';

-- -----------------------------------------------------------------------------
-- 4. DAT-001 공식 자료 기준일 관리
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS data_versions (
  data_version_id  BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  source_code      TEXT        NOT NULL,           -- 아래 CHECK 참조
  source_name      TEXT        NOT NULL,           -- 화면 표시용 출처명
  provider         TEXT        NOT NULL,           -- 식품의약품안전처 / 건강보험심사평가원 / 질병관리청
  target_table     TEXT,                           -- 적재 대상 테이블
  api_endpoint_key TEXT,                           -- .env 키 이름 (주소 자체는 설정값으로 분리)
  base_label       TEXT,                           -- '2026.6 고시' 처럼 원천이 밝힌 기준
  base_date        DATE,                           -- 화면 "자료 기준일"
  fetched_at       TIMESTAMPTZ NOT NULL,           -- 받은 시각
  verified_at      TIMESTAMPTZ,                    -- 마지막 확인 시각
  record_count     INTEGER,
  valid_count      INTEGER,                        -- 정상 품목 등 서비스 사용 건수
  is_current       BOOLEAN     NOT NULL DEFAULT true,
  note             TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_data_versions_source CHECK (source_code IN (
    'MFDS_PERMIT',      -- 식약처 의약품 제품 허가정보
    'MFDS_EASY',        -- 식약처 e약은요
    'MFDS_PILL',        -- 식약처 낱알식별
    'HIRA_EDI_INGR',    -- 심평원 약가마스터(주성분코드)
    'MFDS_DUR',         -- DUR 성분단위
    'KDCA_HEALTHINFO',  -- 질병관리청 국가건강정보포털 생활 수칙
    'WARNING_LEXICON'   -- 주의 단어 사전(직접 작성)
  ))
);
-- 출처별 현재 버전은 하나만
CREATE UNIQUE INDEX IF NOT EXISTS uq_data_versions_current
  ON data_versions (source_code) WHERE is_current;

-- -----------------------------------------------------------------------------
-- 5. 회원 (USR-001 ~ USR-003, USR-006, USR-007)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
  user_id        BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  email          TEXT        NOT NULL,
  password_hash  TEXT,                              -- bcrypt. NULL 허용: 소셜 가입(USR-007) 대비
  birth_year     SMALLINT    NOT NULL,              -- DUR AGE/ELDERLY 판단 (생년월일 대신 최소 수집)
  name           TEXT,                              -- 선택 입력, LLM 입력 금지(SYS-005 마스킹 대상)
  gender         TEXT,                              -- 선택 입력
  status         TEXT        NOT NULL DEFAULT 'ACTIVE',
  is_demo        BOOLEAN     NOT NULL DEFAULT false,-- 12/4 초기 모델 고정 사용자(user_id=1)
  last_login_at  TIMESTAMPTZ,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_users_email      CHECK (email ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
  CONSTRAINT ck_users_birth_year CHECK (birth_year BETWEEN 1900 AND 2100),
  CONSTRAINT ck_users_gender     CHECK (gender IS NULL OR gender IN ('M','F','OTHER')),
  CONSTRAINT ck_users_status     CHECK (status IN ('ACTIVE','LOCKED'))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email_lower ON users (lower(email));  -- 중복 가입 409
DROP TRIGGER IF EXISTS trg_users_updated_at ON users;
CREATE TRIGGER trg_users_updated_at BEFORE UPDATE ON users
  FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();

-- USR-007(선택) 소셜 계정 연결
CREATE TABLE IF NOT EXISTS social_accounts (
  social_account_id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  user_id           BIGINT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
  provider          TEXT   NOT NULL CHECK (provider IN ('KAKAO','NAVER','GOOGLE')),
  provider_user_id  TEXT   NOT NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_social_provider_user UNIQUE (provider, provider_user_id),
  CONSTRAINT uq_social_user_provider UNIQUE (user_id, provider)
);

-- USR-002/003 refresh 토큰(14일) 발급·폐기 목록. 토큰 원문이 아닌 해시만 저장
CREATE TABLE IF NOT EXISTS auth_refresh_tokens (
  jti          UUID        PRIMARY KEY,
  user_id      BIGINT      NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
  token_hash   TEXT        NOT NULL,
  issued_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at   TIMESTAMPTZ NOT NULL,
  revoked_at   TIMESTAMPTZ,                          -- 로그아웃·재발급 시 즉시 폐기
  user_agent   TEXT
);
CREATE INDEX IF NOT EXISTS idx_refresh_user_active
  ON auth_refresh_tokens (user_id) WHERE revoked_at IS NULL;

-- -----------------------------------------------------------------------------
-- 6. USR-004 동의 이력 (누적 전용, 수정 금지)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS consent_logs (
  consent_log_id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  user_id        BIGINT      NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
  consent_type   TEXT        NOT NULL,
  action         TEXT        NOT NULL,
  terms_version  TEXT        NOT NULL,              -- 약관 판 (예: 'v1.0-2026-12-08')
  channel        TEXT        NOT NULL DEFAULT 'WEB',-- WEB(마이페이지/가입) / UPLOAD(화면 1 체크)
  ip_hash        TEXT,                              -- IP 원문 미저장
  user_agent     TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_consent_type CHECK (consent_type IN (
    'TERMS',               -- 서비스 이용약관
    'PRIVACY',             -- 개인정보 수집·이용
    'HEALTH_SENSITIVE',    -- 건강 민감정보 (이용약관과 별도, 미동의 시 건강정보 저장 불가)
    'DOCUMENT_PROCESSING'  -- 업로드 문서 OCR 처리·원본 24시간 후 삭제 (DOC-001, SYS-001)
  )),
  CONSTRAINT ck_consent_action  CHECK (action IN ('AGREE','WITHDRAW')),
  CONSTRAINT ck_consent_channel CHECK (channel IN ('WEB','UPLOAD','SIGNUP'))
);
CREATE INDEX IF NOT EXISTS idx_consent_user_type_time
  ON consent_logs (user_id, consent_type, created_at DESC, consent_log_id DESC);

CREATE OR REPLACE FUNCTION fn_consent_logs_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'consent_logs 는 누적 전용입니다. 변경은 새 행(AGREE/WITHDRAW)으로 추가하세요. (USR-004)';
END $$;
DROP TRIGGER IF EXISTS trg_consent_logs_no_update ON consent_logs;
CREATE TRIGGER trg_consent_logs_no_update BEFORE UPDATE ON consent_logs
  FOR EACH ROW EXECUTE FUNCTION fn_consent_logs_immutable();

-- 현재 유효 동의 여부 = 해당 종류의 가장 최근 행이 AGREE
CREATE OR REPLACE FUNCTION fn_has_active_consent(p_user_id BIGINT, p_type TEXT) RETURNS BOOLEAN
LANGUAGE sql STABLE AS $$
  SELECT coalesce((
    SELECT c.action = 'AGREE'
      FROM consent_logs c
     WHERE c.user_id = p_user_id AND c.consent_type = p_type
     ORDER BY c.created_at DESC, c.consent_log_id DESC
     LIMIT 1), false)
$$;

-- -----------------------------------------------------------------------------
-- 7. USR-005 건강정보 (users 1:1)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_profiles (
  user_id               BIGINT  PRIMARY KEY REFERENCES users (user_id) ON DELETE CASCADE,
  pregnancy_status      TEXT    NOT NULL DEFAULT 'NONE',
  is_breastfeeding      BOOLEAN NOT NULL DEFAULT false,
  chronic_conditions    TEXT[]  NOT NULL DEFAULT '{}',   -- 버튼값(고혈압·당뇨·위염…) + 자유 입력
  allergies             TEXT[]  NOT NULL DEFAULT '{}',   -- 자유 입력 원문
  allergy_ingr_codes    TEXT[]  NOT NULL DEFAULT '{}',   -- 선택: 주성분코드로 연결된 알레르기 성분
  health_consent_log_id BIGINT  REFERENCES consent_logs (consent_log_id) ON DELETE SET NULL,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_profile_pregnancy CHECK (pregnancy_status IN ('NONE','PREGNANT','POSSIBLE'))
);
CREATE INDEX IF NOT EXISTS idx_profiles_conditions_gin ON user_profiles USING gin (chronic_conditions);

-- 건강 민감정보 동의가 유효하지 않으면 저장 차단 (USR-004 → USR-005)
CREATE OR REPLACE FUNCTION fn_profile_requires_consent() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NOT fn_has_active_consent(NEW.user_id, 'HEALTH_SENSITIVE') THEN
    RAISE EXCEPTION USING
      ERRCODE = 'P0001',
      MESSAGE = 'HEALTH_CONSENT_REQUIRED',
      DETAIL  = '건강 민감정보 수집 동의(HEALTH_SENSITIVE)가 없어 건강정보를 저장할 수 없습니다.';
  END IF;
  NEW.updated_at := now();
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_profiles_consent ON user_profiles;
CREATE TRIGGER trg_profiles_consent BEFORE INSERT OR UPDATE ON user_profiles
  FOR EACH ROW EXECUTE FUNCTION fn_profile_requires_consent();

-- -----------------------------------------------------------------------------
-- 8. 문서 (DOC-001, DOC-002, DOC-006, DOC-007, SYS-001)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS documents (
  document_id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id             BIGINT      NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
  consent_log_id      BIGINT      NOT NULL REFERENCES consent_logs (consent_log_id),  -- 업로드 시점 DOCUMENT_PROCESSING 동의 행
  doc_type            TEXT        NOT NULL,
  source_track        TEXT        NOT NULL,       -- 트랙A: 진료기록 PDF 직접 파싱 / 트랙B: 사진·스캔 OCR
  original_filename   TEXT        NOT NULL,
  mime_type           TEXT        NOT NULL,
  file_size_bytes     INTEGER     NOT NULL,
  page_count          SMALLINT,
  file_sha256         CHAR(64)    NOT NULL,
  storage_path        TEXT,                       -- 비공개 저장소 경로. 원본 삭제 후 NULL
  status              TEXT        NOT NULL DEFAULT 'UPLOADED',
  extraction_method   TEXT,
  ocr_avg_confidence  NUMERIC(4,3),               -- DOC-006 품질 판단 (예: < 0.6 재촬영)
  ocr_char_count      INTEGER,                    -- DOC-006 품질 판단 (예: < 20자 재촬영)
  ocr_raw             JSONB,                      -- [{page, line_no, text, bbox:[x1,y1,x2,y2], conf}]
  structured_json     JSONB,                      -- DOC-003 Pydantic 검증 통과 결과 원본
  hospital_name       TEXT,                       -- DOC-007 병원·약국명 (LLM 입력 금지, 화면 표시만)
  visit_date          DATE,                       -- 진료일·조제일
  diagnoses           JSONB,                      -- [{name:'고혈압', kcd_code:'I10'}]
  error_code          TEXT,                       -- SYS-002 (OCR_LOW_QUALITY, PDF_TOO_MANY_PAGES …)
  error_message       TEXT,
  extracted_at        TIMESTAMPTZ,
  purge_after         TIMESTAMPTZ,                -- 읽기 완료 + 24h (SYS-001)
  original_deleted_at TIMESTAMPTZ,
  confirmed_at        TIMESTAMPTZ,                -- DOC-005 [확인 완료]
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_doc_type   CHECK (doc_type IN ('PRESCRIPTION','MED_BAG','MEDICAL_RECORD_PDF','OTHER')),
  CONSTRAINT ck_doc_track  CHECK (source_track IN ('A_PDF_PARSE','B_OCR')),
  CONSTRAINT ck_doc_mime   CHECK (mime_type IN ('image/jpeg','image/png','image/heic','application/pdf')),
  CONSTRAINT ck_doc_size   CHECK (file_size_bytes > 0 AND file_size_bytes <= 20 * 1024 * 1024),   -- 20MB
  CONSTRAINT ck_doc_pages  CHECK (page_count IS NULL OR page_count BETWEEN 1 AND 50),           -- PDF 50쪽
  CONSTRAINT ck_doc_status CHECK (status IN (
    'UPLOADED','EXTRACTING','NEEDS_RETAKE','EXTRACTED','STRUCTURED','MATCHED','CONFIRMED','FAILED')),
  CONSTRAINT ck_doc_method CHECK (extraction_method IS NULL OR extraction_method IN
    ('PDF_TEXT','PDF_OCR','IMAGE_OCR','PDF_TABLE_PARSE')),
  CONSTRAINT ck_doc_conf   CHECK (ocr_avg_confidence IS NULL OR ocr_avg_confidence BETWEEN 0 AND 1)
);
CREATE INDEX IF NOT EXISTS idx_documents_user_created ON documents (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_documents_purge_due
  ON documents (purge_after) WHERE original_deleted_at IS NULL AND storage_path IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_documents_user_sha ON documents (user_id, file_sha256);
DROP TRIGGER IF EXISTS trg_documents_updated_at ON documents;
CREATE TRIGGER trg_documents_updated_at BEFORE UPDATE ON documents
  FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();

-- 업로드 동의 행이 본인의 DOCUMENT_PROCESSING AGREE 인지 검사
CREATE OR REPLACE FUNCTION fn_documents_check_consent() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE ok boolean;
BEGIN
  SELECT (c.user_id = NEW.user_id AND c.consent_type = 'DOCUMENT_PROCESSING' AND c.action = 'AGREE')
    INTO ok FROM consent_logs c WHERE c.consent_log_id = NEW.consent_log_id;
  IF NOT coalesce(ok, false) THEN
    RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'DOCUMENT_CONSENT_REQUIRED',
      DETAIL = '문서 처리 동의(DOCUMENT_PROCESSING, AGREE) 행이 필요합니다.';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_documents_consent ON documents;
CREATE TRIGGER trg_documents_consent BEFORE INSERT ON documents
  FOR EACH ROW EXECUTE FUNCTION fn_documents_check_consent();

-- -----------------------------------------------------------------------------
-- 9. 문서 추출 약 항목 (DOC-003, DOC-004, DOC-005, DOC-007)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS document_items (
  item_id             BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  document_id         UUID        NOT NULL REFERENCES documents (document_id) ON DELETE CASCADE,
  line_no             SMALLINT    NOT NULL,             -- 문서 내 순서
  -- OCR·구조화 원본값 (수정 전 보존 → 오타 사전 후보)
  raw_text            TEXT,                             -- 해당 줄 OCR 원문
  raw_drug_name       TEXT,
  raw_edi_code        TEXT,                             -- 정규식으로 뽑은 9자리 (검증 전)
  ocr_confidence      NUMERIC(4,3),
  -- 구조화 결과 (Pydantic 스키마와 1:1)
  drug_name           TEXT        NOT NULL,
  edi_code            CHAR(9),
  dose_per_time       NUMERIC(6,2),                     -- 1회량 (0.5정 허용)
  dose_unit           TEXT,                             -- 정·캡슐·mL·포·방울 …
  times_per_day       SMALLINT,
  total_days          SMALLINT,
  timing_text         TEXT,                             -- 처방 원문 그대로 ('식후 30분', '취침 전')
  dispensed_date      DATE,                             -- DOC-007 조제일
  -- 약 연결 결과 (DOC-004)
  matched_item_seq    item_seq_t  REFERENCES medicines (item_seq) ON UPDATE CASCADE ON DELETE SET NULL,
  match_method        TEXT        NOT NULL DEFAULT 'NONE',
  match_score         NUMERIC(4,3),                     -- 0.000 ~ 1.000
  match_candidates    JSONB,                            -- 상위 후보 [{item_seq,item_name,score}]
  needs_review        BOOLEAN     NOT NULL DEFAULT true,-- score < 0.7(설정값) 또는 미매칭 → 노란 경고
  -- 사용자 확인 (DOC-005)
  is_user_edited      BOOLEAN     NOT NULL DEFAULT false,
  user_confirmed      BOOLEAN     NOT NULL DEFAULT false,
  include_in_analysis BOOLEAN     NOT NULL DEFAULT true,-- DOC-007 과거 약은 사용자가 골라야 true
  confirmed_at        TIMESTAMPTZ,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_doc_items_line UNIQUE (document_id, line_no),
  CONSTRAINT ck_items_edi      CHECK (edi_code IS NULL OR edi_code ~ '^[0-9]{9}$'),
  CONSTRAINT ck_items_dose     CHECK (dose_per_time IS NULL OR dose_per_time > 0),
  CONSTRAINT ck_items_times    CHECK (times_per_day IS NULL OR times_per_day BETWEEN 1 AND 12),
  CONSTRAINT ck_items_days     CHECK (total_days IS NULL OR total_days BETWEEN 1 AND 365),
  CONSTRAINT ck_items_method   CHECK (match_method IN ('EDI_EXACT','NAME_TRGM','USER_SELECTED','NONE')),
  CONSTRAINT ck_items_score    CHECK (match_score IS NULL OR match_score BETWEEN 0 AND 1),
  CONSTRAINT ck_items_ocr_conf CHECK (ocr_confidence IS NULL OR ocr_confidence BETWEEN 0 AND 1),
  CONSTRAINT ck_items_confirm  CHECK (NOT user_confirmed OR matched_item_seq IS NOT NULL)  -- 확인 완료는 연결된 약만
);
CREATE INDEX IF NOT EXISTS idx_doc_items_document  ON document_items (document_id, line_no);
CREATE INDEX IF NOT EXISTS idx_doc_items_item_seq  ON document_items (matched_item_seq);
CREATE INDEX IF NOT EXISTS idx_doc_items_review    ON document_items (document_id) WHERE needs_review;
DROP TRIGGER IF EXISTS trg_doc_items_updated_at ON document_items;
CREATE TRIGGER trg_doc_items_updated_at BEFORE UPDATE ON document_items
  FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();

-- DOC-004/005 오타 사전 (사용자 수정값은 후보로만 쌓고, 사람이 승인해야 반영)
CREATE TABLE IF NOT EXISTS ocr_typo_dictionary (
  typo_id         BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  wrong_text      TEXT    NOT NULL,
  correct_text    TEXT    NOT NULL,
  source          TEXT    NOT NULL DEFAULT 'USER_CORRECTION' CHECK (source IN ('SEED','USER_CORRECTION')),
  approved        BOOLEAN NOT NULL DEFAULT false,
  hit_count       INTEGER NOT NULL DEFAULT 1,
  from_item_id    BIGINT  REFERENCES document_items (item_id) ON DELETE SET NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_typo_pair UNIQUE (wrong_text, correct_text)
);

-- -----------------------------------------------------------------------------
-- 10. 약별 주의 문구 6유형 (MED-002 ~ MED-005)
--     허가정보 '사용상의 주의사항' XML 을 ARTICLE 단위로 쪼개 규칙 분류한 결과
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS drug_warnings (
  warning_id      BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  item_seq        item_seq_t NOT NULL REFERENCES medicines (item_seq) ON UPDATE CASCADE ON DELETE CASCADE,
  data_version_id BIGINT     REFERENCES data_versions (data_version_id) ON DELETE SET NULL,
  source_code     TEXT       NOT NULL DEFAULT 'MFDS_PERMIT' CHECK (source_code IN ('MFDS_PERMIT','MFDS_EASY')),
  article_seq     SMALLINT   NOT NULL,                 -- XML ARTICLE 순번
  sentence_seq    SMALLINT   NOT NULL,                 -- 항목 내 문장 순번
  article_title   TEXT       NOT NULL,                 -- 원문 항목 제목 ('다음 환자에는 투여하지 말 것' …)
  warning_type    TEXT       NOT NULL,
  life_flags      TEXT[]     NOT NULL DEFAULT '{}',    -- 일상생활 주의 세부: DROWSY, DIZZY, DRIVING, ALCOHOL
  is_emergency    BOOLEAN    NOT NULL DEFAULT false,   -- SAF-002 '중지하고 의사·약사와 상의' 문구
  sentence        TEXT       NOT NULL,                 -- 원문 그대로 (지어내지 않음)
  matched_terms   TEXT[]     NOT NULL DEFAULT '{}',    -- 주의 단어 사전 적중어 (대표어 107개 중)
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_drug_warning_pos UNIQUE (item_seq, source_code, article_seq, sentence_seq),
  CONSTRAINT ck_warning_type CHECK (warning_type IN (
    'CONTRAINDICATION',  -- 먹으면 안 되는 경우 (투여하지 말 것)
    'CAUTION',           -- 신중히 먹어야 하는 경우 (신중히 투여)
    'ADVERSE',           -- 주요 부작용 (이상반응)
    'DAILY_LIFE',        -- 일상생활 주의 (일반적 주의: 졸음·어지러움·운전·음주)
    'INTERACTION',       -- 함께 먹는 약·음식 (상호작용)
    'SPECIAL_POP'        -- 임신·수유·고령자
  ))
);
CREATE INDEX IF NOT EXISTS idx_drug_warnings_item_type ON drug_warnings (item_seq, warning_type);
CREATE INDEX IF NOT EXISTS idx_drug_warnings_emergency ON drug_warnings (item_seq) WHERE is_emergency;

-- -----------------------------------------------------------------------------
-- 11. 문서별 DUR 경고 결과 (화면 3 금기 배지 / MED-010 선택 기능의 1차 기반)
--     LLM 미사용. dur_rules 원문을 그대로 연결만 하고 위험도 점수는 만들지 않는다.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dur_alerts (
  alert_id        BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  document_id     UUID    NOT NULL REFERENCES documents (document_id) ON DELETE CASCADE,
  item_id_a       BIGINT  NOT NULL REFERENCES document_items (item_id) ON DELETE CASCADE,
  item_id_b       BIGINT  REFERENCES document_items (item_id) ON DELETE CASCADE,  -- 병용금기 상대 약
  dur_rule_id     BIGINT  NOT NULL REFERENCES dur_rules (dur_rule_id) ON DELETE CASCADE,
  dur_type        TEXT    NOT NULL,                  -- dur_rules.dur_type 복사 (조회 편의)
  trigger_reason  TEXT    NOT NULL,
  matched_code_a  TEXT,                              -- 연결에 쓰인 성분코드
  matched_code_b  TEXT,
  user_age        SMALLINT,                          -- 판단 시점 만 나이(연 단위 근사)
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_dur_alert_reason CHECK (trigger_reason IN (
    'PAIR_IN_DOCUMENT',   -- 같은 처방 안 두 약
    'PROFILE_PREGNANCY',  -- user_profiles.pregnancy_status
    'AGE_CHECK',          -- age_limit 원문 대조 필요 (앱에서 표시 판단)
    'ELDERLY_65',         -- 만 65세 이상
    'ITEM_RULE')),        -- 그 외 단일 성분 규칙
  CONSTRAINT ck_dur_alert_pair CHECK (item_id_b IS NULL OR item_id_b <> item_id_a)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_dur_alerts_dedup
  ON dur_alerts (document_id, dur_rule_id, item_id_a, coalesce(item_id_b, 0));
CREATE INDEX IF NOT EXISTS idx_dur_alerts_document ON dur_alerts (document_id, dur_type);

-- -----------------------------------------------------------------------------
-- 12. RAG 지식 문서 (질병관리청 국가건강정보포털 생활 수칙) + pgvector
--     임베딩 모델: intfloat/multilingual-e5-small (384차원, 로컬 실행)
--     ※ e5 계열 규칙: 저장 시 'passage: ' / 검색 시 'query: ' 접두어, 정규화 후 cosine
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kb_documents (
  kb_doc_id       BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  data_version_id BIGINT REFERENCES data_versions (data_version_id) ON DELETE SET NULL,
  source_org      TEXT   NOT NULL DEFAULT '질병관리청 국가건강정보포털',
  disease_name    TEXT   NOT NULL,                   -- 고혈압·당뇨병·위염·감기·비염 … (10개 안팎)
  kcd_codes       TEXT[] NOT NULL DEFAULT '{}',      -- 진료기록 상병코드와 연결 (I10, E11 …)
  title           TEXT   NOT NULL,
  source_url      TEXT   NOT NULL,
  license_note    TEXT,                              -- 이용 조건 확인 결과
  raw_text        TEXT   NOT NULL,                   -- 원문 전체 (문장 생성 금지, 원문만 근거)
  fetched_at      TIMESTAMPTZ NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_kb_documents_url UNIQUE (source_url)
);
CREATE INDEX IF NOT EXISTS idx_kb_documents_kcd ON kb_documents USING gin (kcd_codes);

CREATE TABLE IF NOT EXISTS kb_chunks (
  chunk_id        BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  kb_doc_id       BIGINT  NOT NULL REFERENCES kb_documents (kb_doc_id) ON DELETE CASCADE,
  chunk_no        INTEGER NOT NULL,                  -- 문단 순번
  section_title   TEXT,                              -- '생활 습관', '식이요법' …
  content         TEXT    NOT NULL,                  -- 문단 원문
  token_count     INTEGER,
  embedding       vector(384),                       -- multilingual-e5-small
  embedding_model TEXT    NOT NULL DEFAULT 'intfloat/multilingual-e5-small',
  content_tsv     tsvector GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED, -- 키워드 보조 검색
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_kb_chunks_pos UNIQUE (kb_doc_id, chunk_no)
);
-- 벡터 인덱스: 문단 수천 개 규모 → 학습 단계가 없는 HNSW 채택 (빈 테이블에도 생성 가능)
CREATE INDEX IF NOT EXISTS idx_kb_chunks_embedding_hnsw
  ON kb_chunks USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
-- [대안] IVFFlat — 데이터 적재 '후' 생성해야 품질이 나옴. lists ≈ 행수/1000 (최소 10)
-- CREATE INDEX idx_kb_chunks_embedding_ivf
--   ON kb_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10);
-- 검색 시: SET LOCAL hnsw.ef_search = 40;   (IVFFlat: SET LOCAL ivfflat.probes = 3;)
CREATE INDEX IF NOT EXISTS idx_kb_chunks_tsv ON kb_chunks USING gin (content_tsv);

-- -----------------------------------------------------------------------------
-- 13. 맞춤 복약·생활 안내서 (MED-006 ~ MED-009, SAF-001, SAF-002, SYS-005)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS guides (
  guide_id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id               BIGINT      NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
  document_id           UUID        NOT NULL REFERENCES documents (document_id) ON DELETE CASCADE,
  cache_key             CHAR(64)    NOT NULL,        -- sha256(확인된 약 목록 + 건강정보 + 자료 기준일) (MED-008)
  status                TEXT        NOT NULL DEFAULT 'GENERATING',
  -- 생성 입력 스냅샷 (식별정보 제거본만 저장, SYS-005)
  pii_mask_counts       JSONB       NOT NULL DEFAULT '{}'::jsonb,  -- {"NAME":1,"RRN":0,"PHONE":0,"HOSP_NO":0} 마스킹 건수 (QAT-001 점검)
  input_snapshot        JSONB       NOT NULL,        -- {items:[{item_seq,dose,times,days,timing}], profile:{...}, diagnoses:[...]}
  data_versions_used    JSONB       NOT NULL,        -- {"MFDS_PERMIT":12,"KDCA_HEALTHINFO":15}
  -- 생성 결과
  emergency_notice      TEXT        NOT NULL,        -- SAF-002 맨 위 고정 카드 (119 안내 포함)
  sections              JSONB       NOT NULL DEFAULT '{}'::jsonb,
                                                     -- {how_to_take:[{text,refs:[1,2]}], life_rules:[...],
                                                     --  warnings_by_type:{...}, ask_professional:[...]}
  content_md            TEXT,                        -- 렌더링·TTS(MED-013)용 본문
  disclaimer            TEXT        NOT NULL,        -- SAF-001 고정 면책 문구
  -- 안전 검사 결과 (SAF-001)
  safety_passed         BOOLEAN     NOT NULL DEFAULT false,
  removed_unsupported   SMALLINT    NOT NULL DEFAULT 0,   -- 근거 없어 제거된 문장 수 (목표 0 노출)
  removed_assertive     SMALLINT    NOT NULL DEFAULT 0,   -- 단정·지시 표현 제거 수
  -- 생성 메타
  llm_model             TEXT,                        -- claude-haiku-… (개발) / claude-sonnet-… (시연)
  prompt_version        TEXT        NOT NULL,
  latency_ms            INTEGER,
  input_tokens          INTEGER,
  output_tokens         INTEGER,
  regenerated_from      UUID        REFERENCES guides (guide_id) ON DELETE SET NULL,  -- MED-009
  error_code            TEXT,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_guides_status CHECK (status IN ('GENERATING','READY','STALE','FAILED'))
);
-- 같은 사용자·같은 조건의 READY 안내서는 하나만 → 즉시 재조회 (MED-008)
CREATE UNIQUE INDEX IF NOT EXISTS uq_guides_user_cache_ready
  ON guides (user_id, cache_key) WHERE status = 'READY';
CREATE INDEX IF NOT EXISTS idx_guides_document ON guides (document_id, created_at DESC);
DROP TRIGGER IF EXISTS trg_guides_updated_at ON guides;
CREATE TRIGGER trg_guides_updated_at BEFORE UPDATE ON guides
  FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();

-- MED-008 좋아요/싫어요
CREATE TABLE IF NOT EXISTS guide_feedback (
  feedback_id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  guide_id    UUID     NOT NULL REFERENCES guides (guide_id) ON DELETE CASCADE,
  user_id     BIGINT   NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
  rating      SMALLINT NOT NULL CHECK (rating IN (-1, 1)),
  comment     TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_guide_feedback UNIQUE (guide_id, user_id)
);

-- -----------------------------------------------------------------------------
-- 14. 복약 시간표 (MED-007) — 처방 원문을 칸에 배치만, 시각을 새로 정하지 않음
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS medication_schedules (
  schedule_id    BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  user_id        BIGINT   NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
  document_id    UUID     NOT NULL REFERENCES documents (document_id) ON DELETE CASCADE,
  item_id        BIGINT   NOT NULL REFERENCES document_items (item_id) ON DELETE CASCADE,
  guide_id       UUID     REFERENCES guides (guide_id) ON DELETE SET NULL,
  slot           TEXT     NOT NULL,
  meal_relation  TEXT     NOT NULL DEFAULT 'UNSPECIFIED',
  offset_minutes SMALLINT,                           -- '식후 30분' → 30 (원문에 있을 때만)
  dose_label     TEXT     NOT NULL,                  -- '1정', '0.5정'
  source_text    TEXT,                               -- 근거가 된 처방 원문
  mapping_rule   TEXT     NOT NULL,                  -- 'TIMES_3', 'BEDTIME_TEXT', 'AS_NEEDED_TEXT'
  start_date     DATE,
  end_date       DATE,                               -- start_date + total_days - 1
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_schedule_item_slot UNIQUE (item_id, slot),
  CONSTRAINT ck_schedule_slot  CHECK (slot IN ('MORNING','LUNCH','DINNER','BEDTIME','AS_NEEDED')),
  CONSTRAINT ck_schedule_meal  CHECK (meal_relation IN ('BEFORE_MEAL','AFTER_MEAL','WITH_MEAL','EMPTY_STOMACH','UNSPECIFIED')),
  CONSTRAINT ck_schedule_dates CHECK (end_date IS NULL OR start_date IS NULL OR end_date >= start_date)
);
CREATE INDEX IF NOT EXISTS idx_schedules_document_slot ON medication_schedules (document_id, slot);
CREATE INDEX IF NOT EXISTS idx_schedules_user_period  ON medication_schedules (user_id, start_date, end_date);

-- -----------------------------------------------------------------------------
-- 15. 챗봇 (CHT-001 ~ CHT-004, SAF-001)
-- -----------------------------------------------------------------------------
-- 추천·경계·상황 질문 목록 (직접 작성: 일반 15 + 경계 10 + 상황 버튼)
CREATE TABLE IF NOT EXISTS chat_preset_questions (
  preset_code     TEXT    PRIMARY KEY,               -- 'GEN-ALCOHOL', 'BND-STOP', 'SIT-MISSED' …
  category        TEXT    NOT NULL CHECK (category IN ('GENERAL','BOUNDARY','SITUATION')),
  question_text   TEXT    NOT NULL,
  show_when       JSONB   NOT NULL DEFAULT '{}'::jsonb,  -- {"warning_type":"DAILY_LIFE","life_flag":"ALCOHOL"} / {"pregnancy":true}
  sort_order      SMALLINT NOT NULL DEFAULT 100,
  is_active       BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS chat_sessions (
  session_id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id                  BIGINT      NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
  document_id              UUID        REFERENCES documents (document_id) ON DELETE CASCADE,
  guide_id                 UUID        REFERENCES guides (guide_id) ON DELETE SET NULL,
  title                    TEXT,
  context_snapshot         JSONB       NOT NULL,     -- 비식별: 약 목록(item_seq·이름)·건강정보 플래그·진단명
  recommended_presets      TEXT[]      NOT NULL DEFAULT '{}',  -- 생성 시 규칙으로 고른 preset_code
  summary                  TEXT,                     -- 10번 초과 시 Haiku 요약 (CHT-001)
  summarized_upto_msg_id   BIGINT,                   -- 요약에 포함된 마지막 메시지
  message_count            INTEGER     NOT NULL DEFAULT 0,
  status                   TEXT        NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','CLOSED')),
  created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_message_at          TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user ON chat_sessions (user_id, last_message_at DESC NULLS LAST);

CREATE TABLE IF NOT EXISTS chat_messages (
  message_id        BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  session_id        UUID        NOT NULL REFERENCES chat_sessions (session_id) ON DELETE CASCADE,
  role              TEXT        NOT NULL CHECK (role IN ('USER','ASSISTANT','SYSTEM')),
  input_mode        TEXT,                            -- USER 메시지만
  preset_code       TEXT        REFERENCES chat_preset_questions (preset_code) ON DELETE SET NULL,
  content           TEXT        NOT NULL,            -- USER 원문은 식별정보 가림 후 저장
  pii_mask_counts   JSONB       NOT NULL DEFAULT '{}'::jsonb,  -- USER 메시지 마스킹 건수 (SYS-005)
  -- 안전 검사 (CHT-003: 1차 규칙 + 2차 Haiku 분류)
  safety_label      TEXT,
  safety_rule_hit   TEXT,                            -- 적중 규칙 ID (예: 'RULE_STOP_DRUG')
  is_refusal        BOOLEAN     NOT NULL DEFAULT false,
  answer_status     TEXT,                            -- ASSISTANT: ANSWERED / NO_EVIDENCE / REFUSED / EMERGENCY / ERROR
  follow_up_presets TEXT[]      NOT NULL DEFAULT '{}',
  visit_questions   JSONB,                           -- CHT-004 방문 전 질문 3~5개
  disclaimer_shown  BOOLEAN     NOT NULL DEFAULT true, -- SAF-001 모든 AI 답변 하단 고정
  llm_model         TEXT,
  latency_ms        INTEGER,
  input_tokens      INTEGER,
  output_tokens     INTEGER,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_msg_input_mode CHECK (input_mode IS NULL OR input_mode IN ('PRESET','FREE_TEXT','SITUATION')),
  CONSTRAINT ck_msg_safety     CHECK (safety_label IS NULL OR safety_label IN ('SAFE','BOUNDARY','EMERGENCY')),
  CONSTRAINT ck_msg_answer     CHECK (answer_status IS NULL OR answer_status IN
                                      ('ANSWERED','NO_EVIDENCE','REFUSED','EMERGENCY','ERROR'))
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages (session_id, message_id);

-- 세션 메시지 수·마지막 시각 자동 갱신 (요약 트리거 기준 10번)
CREATE OR REPLACE FUNCTION fn_chat_session_touch() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  UPDATE chat_sessions
     SET message_count = message_count + 1, last_message_at = NEW.created_at
   WHERE session_id = NEW.session_id;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_chat_messages_touch ON chat_messages;
CREATE TRIGGER trg_chat_messages_touch AFTER INSERT ON chat_messages
  FOR EACH ROW EXECUTE FUNCTION fn_chat_session_touch();

-- -----------------------------------------------------------------------------
-- 16. 근거 인용 (MED-004, MED-006 문장별 근거 번호, CHT-002 답변 출처)
--     안내서 문장 또는 챗봇 답변 하나가 여러 근거를 가진다. 원문 스냅샷을 함께 저장해
--     원천 데이터가 갱신되어도 당시 근거를 재현할 수 있게 한다.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS evidence_citations (
  citation_id     BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  guide_id        UUID     REFERENCES guides (guide_id) ON DELETE CASCADE,
  message_id      BIGINT   REFERENCES chat_messages (message_id) ON DELETE CASCADE,
  ref_no          SMALLINT NOT NULL,                 -- 본문의 [1], [2] 번호
  source_kind     TEXT     NOT NULL,
  item_seq        item_seq_t REFERENCES medicines (item_seq) ON UPDATE CASCADE ON DELETE SET NULL,
  warning_id      BIGINT   REFERENCES drug_warnings (warning_id) ON DELETE SET NULL,
  chunk_id        BIGINT   REFERENCES kb_chunks (chunk_id) ON DELETE SET NULL,
  dur_rule_id     BIGINT   REFERENCES dur_rules (dur_rule_id) ON DELETE SET NULL,
  data_version_id BIGINT   REFERENCES data_versions (data_version_id) ON DELETE SET NULL,
  similarity      NUMERIC(5,4),                      -- KB_CHUNK 검색 점수
  source_title    TEXT     NOT NULL,                 -- '식약처 의약품 제품 허가정보 – 타이레놀정500mg'
  source_url      TEXT,
  quoted_text     TEXT     NOT NULL,                 -- 인용 원문 스냅샷
  base_date       DATE,                              -- 자료 기준일 표시 (DAT-001)
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_citation_owner CHECK (num_nonnulls(guide_id, message_id) = 1),
  CONSTRAINT ck_citation_kind  CHECK (source_kind IN
    ('MEDICINE_TEXT','DRUG_WARNING','EASY_TEXT','KB_CHUNK','DUR_RULE')),
  CONSTRAINT uq_citation_guide_ref UNIQUE (guide_id, ref_no),
  CONSTRAINT uq_citation_msg_ref   UNIQUE (message_id, ref_no)
);
CREATE INDEX IF NOT EXISTS idx_citations_guide   ON evidence_citations (guide_id)   WHERE guide_id   IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_citations_message ON evidence_citations (message_id) WHERE message_id IS NOT NULL;

-- -----------------------------------------------------------------------------
-- 16-2. AI 답변 신고·이의 제기 (SAF-003)
--     개인정보 처리방침 작성지침(2026.4.) 부록: 부적절한 답변(민감정보 노출 등)에 대한
--     피드백·신고 방법 안내. 신고 목록은 QAT-001 안전성 검증 자료로 사용
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ai_output_reports (
  report_id       BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  user_id         BIGINT      NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
  guide_id        UUID        REFERENCES guides (guide_id) ON DELETE CASCADE,
  message_id      BIGINT      REFERENCES chat_messages (message_id) ON DELETE CASCADE,
  reason_code     TEXT        NOT NULL,
  detail          TEXT,                              -- 저장 전 식별정보 마스킹
  status          TEXT        NOT NULL DEFAULT 'RECEIVED',
  resolution_note TEXT,                              -- 운영자 처리 내용 (수정·재생성·기각 사유)
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at     TIMESTAMPTZ,
  CONSTRAINT ck_report_owner  CHECK (num_nonnulls(guide_id, message_id) = 1),
  CONSTRAINT ck_report_reason CHECK (reason_code IN
    ('WRONG_INFO','UNSAFE_ADVICE','PRIVACY_EXPOSURE','NO_SOURCE','OTHER')),
  CONSTRAINT ck_report_status CHECK (status IN ('RECEIVED','REVIEWING','RESOLVED','REJECTED'))
);
CREATE INDEX IF NOT EXISTS idx_reports_open
  ON ai_output_reports ((reason_code = 'PRIVACY_EXPOSURE') DESC, created_at)
  WHERE status IN ('RECEIVED','REVIEWING');
CREATE INDEX IF NOT EXISTS idx_reports_user ON ai_output_reports (user_id, created_at DESC);

-- -----------------------------------------------------------------------------
-- 17. 운영 로그 (SYS-003 단계별 응답 시간, USR-006/SYS-001 삭제 기록)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pipeline_metrics (
  metric_id    BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  document_id  UUID   REFERENCES documents (document_id) ON DELETE SET NULL,
  guide_id     UUID   REFERENCES guides (guide_id) ON DELETE SET NULL,
  session_id   UUID   REFERENCES chat_sessions (session_id) ON DELETE SET NULL,
  stage        TEXT   NOT NULL CHECK (stage IN
                 ('UPLOAD','PDF_TEXT','OCR','QUALITY','STRUCTURE','MATCH','WARNING','DUR',
                  'RAG_SEARCH','LLM_GUIDE','SAFETY_CHECK','CHAT_ANSWER','PAGE_LOAD')),
  duration_ms  INTEGER NOT NULL CHECK (duration_ms >= 0),
  success      BOOLEAN NOT NULL,
  error_code   TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_metrics_stage_time ON pipeline_metrics (stage, created_at DESC);

-- 사용자 행이 지워진 뒤에도 남는 기록 → users FK 없음, 식별자는 해시만
CREATE TABLE IF NOT EXISTS deletion_logs (
  deletion_id    BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  kind           TEXT   NOT NULL CHECK (kind IN ('USER_WITHDRAW','USER_DELETE_RECORD','ORIGINAL_FILE_PURGE')),
  subject_hash   TEXT   NOT NULL,                    -- sha256(user_id) 또는 sha256(document_id)
  deleted_counts JSONB  NOT NULL DEFAULT '{}'::jsonb,
  storage_paths  TEXT[] NOT NULL DEFAULT '{}',       -- 앱이 실제 파일 삭제에 사용 후 확인
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- 18. 서비스 함수
-- -----------------------------------------------------------------------------
-- 18-1) DOC-004 1순위: EDI 9자리 정확 일치
CREATE OR REPLACE FUNCTION fn_match_by_edi(p_edi TEXT)
RETURNS TABLE (item_seq item_seq_t, item_name TEXT, entp_name TEXT, score NUMERIC)
LANGUAGE sql STABLE AS $$
  SELECT DISTINCT m.item_seq::item_seq_t, m.item_name, m.entp_name, 1.000::numeric
    FROM medicine_edi_codes e
    JOIN v_active_medicines m ON m.item_seq = e.item_seq
   WHERE e.edi_code = p_edi
$$;

-- 18-2) DOC-004 2순위 + 화면 2 자동완성: 정규화 이름 trigram 유사도
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
     AND length(q2.qn) >= 2
     AND (fn_norm_drug_name(m.item_name) % q2.qn
          OR fn_norm_drug_name(m.item_name) LIKE '%' || q2.qn || '%'
          OR m.item_name LIKE '%' || q2.qr || '%'
          OR (q2.qb <> q2.qn AND length(q2.qb) >= 2
              AND fn_norm_drug_name(m.item_name) LIKE q2.qb || '%'))
   ORDER BY 4 DESC, length(m.item_name)
   LIMIT p_limit
$$;

-- 18-3) 화면 3: 문서의 분석 대상 약 → DUR 규칙 후보 계산
--   DUR 성분코드(ingr_code_a/b)를 심평원 주성분코드(9자리) 또는 성분그룹코드와 대조한다.
--   ※ 실제 dur_rules.ingr_code 체계가 어느 쪽인지 첫 실행 후 아래 점검 쿼리로 연결률 확인:
--     SELECT count(*) FILTER (WHERE EXISTS (SELECT 1 FROM v_item_ingredients i
--              WHERE r.ingr_code_a IN (i.main_ingredient_code, i.ingredient_group_code))) AS linked,
--            count(*) AS total FROM dur_rules r;
CREATE OR REPLACE FUNCTION fn_dur_alerts_for_document(p_document_id UUID)
RETURNS TABLE (dur_rule_id BIGINT, dur_type TEXT, item_id_a BIGINT, item_id_b BIGINT,
               trigger_reason TEXT, matched_code_a TEXT, matched_code_b TEXT, user_age SMALLINT)
LANGUAGE sql STABLE AS $$
  WITH doc AS (
    SELECT d.document_id, d.user_id,
           (extract(year FROM now())::int - u.birth_year)::smallint AS age,
           coalesce(p.pregnancy_status, 'NONE') AS preg
      FROM documents d
      JOIN users u ON u.user_id = d.user_id
      LEFT JOIN user_profiles p ON p.user_id = d.user_id
     WHERE d.document_id = p_document_id
  ),
  it AS (   -- 분석 대상 약의 성분코드 (주성분 + 그룹)
    SELECT DISTINCT di.item_id, c.code
      FROM document_items di
      JOIN v_item_ingredients vi ON vi.item_seq = di.matched_item_seq
      CROSS JOIN LATERAL (VALUES (vi.main_ingredient_code), (vi.ingredient_group_code)) AS c(code)
     WHERE di.document_id = p_document_id
       AND di.include_in_analysis
       AND c.code IS NOT NULL
  ),
  pair AS ( -- 병용금기: 같은 처방 안 서로 다른 두 약 (규칙 방향 무관)
    SELECT DISTINCT r.dur_rule_id, r.dur_type,
           least(x.item_id, y.item_id) AS a, greatest(x.item_id, y.item_id) AS b,
           'PAIR_IN_DOCUMENT'::text AS reason,
           CASE WHEN x.item_id < y.item_id THEN x.code ELSE y.code END AS ca,
           CASE WHEN x.item_id < y.item_id THEN y.code ELSE x.code END AS cb
      FROM dur_rules r
      JOIN it x ON x.code = r.ingr_code_a
      JOIN it y ON y.code = r.ingr_code_b AND y.item_id <> x.item_id
     WHERE r.ingr_code_b IS NOT NULL
  ),
  single AS ( -- 단일 성분 규칙 + 사용자 상태
    SELECT DISTINCT r.dur_rule_id, r.dur_type, x.item_id AS a, NULL::bigint AS b,
           CASE r.dur_type
             WHEN 'PREGNANCY' THEN 'PROFILE_PREGNANCY'
             WHEN 'AGE'       THEN 'AGE_CHECK'
             WHEN 'ELDERLY'   THEN 'ELDERLY_65'
             ELSE 'ITEM_RULE' END AS reason,
           x.code AS ca, NULL::text AS cb
      FROM dur_rules r
      JOIN it x ON x.code = r.ingr_code_a
      CROSS JOIN doc
     WHERE r.ingr_code_b IS NULL
       AND (   (r.dur_type = 'PREGNANCY' AND doc.preg IN ('PREGNANT','POSSIBLE'))
            OR (r.dur_type = 'ELDERLY'   AND doc.age >= 65)
            OR (r.dur_type = 'AGE')
            OR (r.dur_type NOT IN ('PREGNANCY','ELDERLY','AGE','CONCOMITANT')))
  )
  SELECT s.dur_rule_id, s.dur_type, s.a, s.b, s.reason, s.ca, s.cb, doc.age
    FROM (SELECT * FROM pair UNION ALL SELECT * FROM single) s CROSS JOIN doc
$$;

-- 18-4) 화면 3 저장: 계산 결과를 dur_alerts 에 반영 (재실행 시 교체)
CREATE OR REPLACE FUNCTION fn_refresh_dur_alerts(p_document_id UUID) RETURNS INTEGER
LANGUAGE plpgsql AS $$
DECLARE n INTEGER;
BEGIN
  DELETE FROM dur_alerts WHERE document_id = p_document_id;
  INSERT INTO dur_alerts (document_id, item_id_a, item_id_b, dur_rule_id, dur_type,
                          trigger_reason, matched_code_a, matched_code_b, user_age)
  SELECT p_document_id, f.item_id_a, f.item_id_b, f.dur_rule_id, f.dur_type,
         f.trigger_reason, f.matched_code_a, f.matched_code_b, f.user_age
    FROM fn_dur_alerts_for_document(p_document_id) f
  ON CONFLICT DO NOTHING;
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END $$;

-- 18-5) RAG: 생활 수칙 문단 벡터 검색 (상위 k개, 질환 필터 선택)
--   p_query_vec 는 앱에서 'query: ' 접두어로 임베딩·정규화한 384차원 벡터
CREATE OR REPLACE FUNCTION fn_kb_search(p_query_vec vector(384), p_k INT DEFAULT 3,
                                        p_diseases TEXT[] DEFAULT NULL)
RETURNS TABLE (chunk_id BIGINT, kb_doc_id BIGINT, disease_name TEXT, title TEXT,
               source_url TEXT, content TEXT, similarity NUMERIC)
LANGUAGE sql STABLE AS $$
  SELECT c.chunk_id, d.kb_doc_id, d.disease_name, d.title, d.source_url, c.content,
         round((1 - (c.embedding <=> p_query_vec))::numeric, 4)
    FROM kb_chunks c
    JOIN kb_documents d ON d.kb_doc_id = c.kb_doc_id
   WHERE c.embedding IS NOT NULL
     AND (p_diseases IS NULL OR d.disease_name = ANY (p_diseases))
   ORDER BY c.embedding <=> p_query_vec
   LIMIT p_k
$$;

-- 18-6) USR-006 탈퇴: 삭제 로그 → CASCADE 삭제 → 앱이 지울 원본 파일 경로 반환
CREATE OR REPLACE FUNCTION fn_withdraw_user(p_user_id BIGINT) RETURNS TEXT[]
LANGUAGE plpgsql AS $$
DECLARE paths TEXT[]; counts JSONB;
BEGIN
  SELECT coalesce(array_agg(storage_path) FILTER (WHERE storage_path IS NOT NULL), '{}')
    INTO paths FROM documents WHERE user_id = p_user_id;
  SELECT jsonb_build_object(
           'documents',     (SELECT count(*) FROM documents     WHERE user_id = p_user_id),
           'guides',        (SELECT count(*) FROM guides        WHERE user_id = p_user_id),
           'chat_sessions', (SELECT count(*) FROM chat_sessions WHERE user_id = p_user_id),
           'consent_logs',  (SELECT count(*) FROM consent_logs  WHERE user_id = p_user_id))
    INTO counts;
  INSERT INTO deletion_logs (kind, subject_hash, deleted_counts, storage_paths)
  VALUES ('USER_WITHDRAW', encode(sha256(convert_to(p_user_id::text, 'UTF8')), 'hex'), counts, paths);
  DELETE FROM users WHERE user_id = p_user_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'USER_NOT_FOUND';
  END IF;
  RETURN paths;
END $$;

-- 18-7) USR-006 개별 기록 삭제: 처방 기록 하나와 연결된 안내서·시간표·DUR 결과·대화방을 함께 삭제
--       본인 문서가 아니면 0건 처리 후 예외. 반환값: 앱이 지울 원본 파일 경로(이미 삭제됐으면 NULL)
CREATE OR REPLACE FUNCTION fn_delete_document(p_user_id BIGINT, p_document_id UUID) RETURNS TEXT
LANGUAGE plpgsql AS $$
DECLARE v_path TEXT; counts JSONB;
BEGIN
  SELECT storage_path INTO v_path FROM documents
   WHERE document_id = p_document_id AND user_id = p_user_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'DOCUMENT_NOT_FOUND';
  END IF;
  SELECT jsonb_build_object(
           'document_items', (SELECT count(*) FROM document_items WHERE document_id = p_document_id),
           'guides',         (SELECT count(*) FROM guides         WHERE document_id = p_document_id),
           'chat_sessions',  (SELECT count(*) FROM chat_sessions  WHERE document_id = p_document_id))
    INTO counts;
  INSERT INTO deletion_logs (kind, subject_hash, deleted_counts, storage_paths)
  VALUES ('USER_DELETE_RECORD', encode(sha256(convert_to(p_document_id::text, 'UTF8')), 'hex'),
          counts, CASE WHEN v_path IS NULL THEN '{}'::text[] ELSE ARRAY[v_path] END);
  DELETE FROM documents WHERE document_id = p_document_id AND user_id = p_user_id;
  RETURN v_path;
END $$;

-- -----------------------------------------------------------------------------
-- 19. 초기 데이터 (자료 기준일, 시연 고정 사용자, 추천 질문)
-- -----------------------------------------------------------------------------
-- 19-1) DAT-001: 11/20~11/24 적재 실적 (계획서 5장 수치)
INSERT INTO data_versions (source_code, source_name, provider, target_table, api_endpoint_key,
                           base_label, base_date, fetched_at, verified_at, record_count, valid_count, note)
SELECT * FROM (VALUES
  ('MFDS_PERMIT','의약품 제품 허가정보','식품의약품안전처','medicines','MFDS_PERMIT_API_URL',
   NULL, DATE '2026-11-20', TIMESTAMPTZ '2026-11-20 00:00+09', TIMESTAMPTZ '2026-11-23 00:00+09',
   46305, 35187, '정상(cancel_name=정상) 35,187건만 서비스 사용. 허가상태 빈 3,579건 제외'),
  ('MFDS_EASY','의약품개요정보(e약은요)','식품의약품안전처','medicines','MFDS_EASY_API_URL',
   NULL, DATE '2026-11-20', TIMESTAMPTZ '2026-11-20 00:00+09', TIMESTAMPTZ '2026-11-23 00:00+09',
   4725, 4725, '일반의약품 위주. 처방약은 허가정보 원문으로 보완'),
  ('MFDS_PILL','의약품 낱알식별 정보','식품의약품안전처','medicines','MFDS_PILL_API_URL',
   NULL, DATE '2026-11-20', TIMESTAMPTZ '2026-11-20 00:00+09', TIMESTAMPTZ '2026-11-23 00:00+09',
   25496, NULL, '낱알 API 단독 3,579건은 허가상태 미확인'),
  ('HIRA_EDI_INGR','약가마스터(주성분코드)','건강보험심사평가원','medicine_edi_codes','HIRA_EDI_FILE',
   NULL, NULL, TIMESTAMPTZ '2026-11-24 00:00+09', NULL,
   23824, 21402, 'EDI 23,824건 중 주성분코드 매핑 21,402건'),
  ('MFDS_DUR','DUR 성분단위 정보','식품의약품안전처','dur_rules','MFDS_DUR_FILE',
   '2026.6 고시', NULL, TIMESTAMPTZ '2026-11-24 00:00+09', NULL,
   28502, 28502, 'csv 28,502행')
) AS v(source_code, source_name, provider, target_table, api_endpoint_key, base_label, base_date,
       fetched_at, verified_at, record_count, valid_count, note)
WHERE NOT EXISTS (SELECT 1 FROM data_versions dv WHERE dv.source_code = v.source_code AND dv.is_current);

-- 19-2) 12/4 초기 모델 고정 사용자(user_id=1) + 시연용 동의
INSERT INTO users (user_id, email, password_hash, birth_year, is_demo)
VALUES (1, 'demo@ansim.local', NULL, 1958, true)
ON CONFLICT (user_id) DO NOTHING;
SELECT setval(pg_get_serial_sequence('users', 'user_id'),
              greatest((SELECT max(user_id) FROM users), 1));

INSERT INTO consent_logs (user_id, consent_type, action, terms_version, channel)
SELECT 1, t, 'AGREE', 'v0.1-demo', 'SIGNUP'
  FROM unnest(ARRAY['TERMS','PRIVACY','HEALTH_SENSITIVE','DOCUMENT_PROCESSING']) AS t
 WHERE NOT EXISTS (SELECT 1 FROM consent_logs WHERE user_id = 1);

-- 19-3) CHT-001~004 추천 질문 (초기 세트, 평가 세트 작성 시 확장)
INSERT INTO chat_preset_questions (preset_code, category, question_text, show_when, sort_order) VALUES
  ('GEN-HOWTO',    'GENERAL',  '이 약은 언제, 어떻게 먹어야 하나요?',                    '{}', 10),
  ('GEN-ALCOHOL',  'GENERAL',  '이 약을 먹는 동안 술을 마셔도 되는지 공식 자료에는 어떻게 나와 있나요?', '{"life_flag":"ALCOHOL"}', 20),
  ('GEN-DROWSY',   'GENERAL',  '졸음이나 어지러움 주의 문구가 있나요?',                   '{"life_flag":"DROWSY"}', 30),
  ('GEN-SIDEEFF',  'GENERAL',  '어떤 증상이 나타나면 의사·약사와 상의해야 하나요?',        '{}', 40),
  ('GEN-LIFE',     'GENERAL',  '제 질환에 맞는 생활 수칙을 알려 주세요.',                  '{"has_diagnosis":true}', 50),
  ('GEN-PREG',     'GENERAL',  '임신·수유 중 주의 문구가 있나요?',                        '{"pregnancy_or_breastfeeding":true}', 60),
  ('BND-STOP',     'BOUNDARY', '속이 쓰린데 약을 임의로 끊거나 반만 먹어도 되나요?',       '{}', 900),
  ('BND-DOUBLE',   'BOUNDARY', '한 번 빼먹었는데 다음에 두 배로 먹어도 되나요?',            '{}', 910),
  ('BND-SUBST',    'BOUNDARY', '이 약 대신 집에 있는 다른 약을 먹어도 되나요?',            '{}', 920),
  ('SIT-STOMACH',  'SITUATION','약을 먹고 속이 불편해요',                                  '{}', 1000),
  ('SIT-OTHERHOSP','SITUATION','다른 병원 약도 먹고 있어요',                               '{}', 1010),
  ('SIT-MISSED',   'SITUATION','약 먹는 걸 잊었어요',                                      '{}', 1020),
  ('SIT-PREG',     'SITUATION','임신·수유 중이에요',                                       '{}', 1030)
ON CONFLICT (preset_code) DO NOTHING;


-- =============================================================================
-- 20. 261125 기획 검토 반영 (docs/review/decision_log_261125.md)
--     앞 절의 같은 이름 함수는 여기서 다시 정의한 것이 최종본이다.
-- =============================================================================
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- 삭제 기록 해시 HMAC (P-09)

-- 20-1) 건별 동의·건별 철회 (D-02, D-19, S-01)
--   scope: USER = 마이페이지·가입 등 사람 단위 / DOCUMENT = 업로드할 때 받은 그 문서 동의, 그 문서 철회
ALTER TABLE consent_logs ADD COLUMN IF NOT EXISTS scope       TEXT NOT NULL DEFAULT 'USER';
ALTER TABLE consent_logs ADD COLUMN IF NOT EXISTS document_id UUID;
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_consent_scope') THEN
    ALTER TABLE consent_logs ADD CONSTRAINT ck_consent_scope CHECK (scope IN ('USER','DOCUMENT'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_consent_document') THEN
    -- D1은 앱이 만든 document_id로 동의 2행을 먼저 넣고 같은 트랜잭션에서 문서를 넣는다 → 지연 검사
    ALTER TABLE consent_logs ADD CONSTRAINT fk_consent_document FOREIGN KEY (document_id)
      REFERENCES documents (document_id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED;
  END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_consent_document ON consent_logs (document_id) WHERE document_id IS NOT NULL;

-- 누적 전용 유지. 단 문서 삭제 때 FK가 document_id만 비우는 경우는 허용
CREATE OR REPLACE FUNCTION fn_consent_logs_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.document_id IS NOT NULL AND NEW.document_id IS NULL
     AND (to_jsonb(NEW) - 'document_id') = (to_jsonb(OLD) - 'document_id') THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'consent_logs 는 누적 전용입니다. 변경은 새 행(AGREE/WITHDRAW)으로 추가하세요. (USR-004)';
END $$;

-- 사람 단위 현재 동의 = 해당 종류에서 (사람 단위 행 + 모든 AGREE 행) 중 가장 최근이 AGREE
--   문서 단위 철회(그 문서 지우기)는 다른 문서·사람 단위 상태에 영향을 주지 않는다
CREATE OR REPLACE FUNCTION fn_has_active_consent(p_user_id BIGINT, p_type TEXT) RETURNS BOOLEAN
LANGUAGE sql STABLE AS $$
  SELECT coalesce((
    SELECT c.action = 'AGREE'
      FROM consent_logs c
     WHERE c.user_id = p_user_id AND c.consent_type = p_type
       AND (c.scope = 'USER' OR c.action = 'AGREE')
     ORDER BY c.created_at DESC, c.consent_log_id DESC
     LIMIT 1), false)
$$;

-- 업로드 트리거: 넘겨받은 동의 행 + 현재 유효한 문서 처리·건강 민감정보 동의를 함께 확인 (S-01, F-01)
CREATE OR REPLACE FUNCTION fn_documents_check_consent() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE ok boolean;
BEGIN
  SELECT (c.user_id = NEW.user_id AND c.consent_type = 'DOCUMENT_PROCESSING' AND c.action = 'AGREE')
    INTO ok FROM consent_logs c WHERE c.consent_log_id = NEW.consent_log_id;
  IF NOT coalesce(ok, false)
     OR NOT fn_has_active_consent(NEW.user_id, 'DOCUMENT_PROCESSING')
     OR NOT fn_has_active_consent(NEW.user_id, 'HEALTH_SENSITIVE') THEN
    RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'CONSENT_REQUIRED',
      DETAIL = '문서 처리 동의와 건강 민감정보 동의가 모두 현재 유효해야 합니다.';
  END IF;
  RETURN NEW;
END $$;

-- 20-2) 처방 항목: 자동 확인 표시(W-01), AI 안내 받지 않기(D-14)
ALTER TABLE document_items ADD COLUMN IF NOT EXISTS confirmed_by TEXT;
ALTER TABLE document_items ADD COLUMN IF NOT EXISTS ai_excluded  BOOLEAN NOT NULL DEFAULT false;
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_items_confirmed_by') THEN
    ALTER TABLE document_items ADD CONSTRAINT ck_items_confirmed_by
      CHECK (confirmed_by IS NULL OR confirmed_by IN ('AUTO','USER'));
  END IF;
END $$;
COMMENT ON COLUMN document_items.needs_review IS '확인이 필요한 약: 점수 0.7 미만 또는 미매칭 (화면 주황 카드)';
COMMENT ON COLUMN document_items.confirmed_by IS 'AUTO = 보험코드 일치·점수 0.7 이상이라 서버가 미리 확인 표시, USER = 사용자가 확인 (W-01)';
COMMENT ON COLUMN document_items.ai_excluded  IS 'true = AI 안내를 받지 않기로 한 약. LLM 입력에서만 빠지고 금기·주의 확인·허가 정보·시간표에는 포함 (D-14)';
COMMENT ON COLUMN document_items.include_in_analysis IS 'false = 진료기록 PDF의 과거 약 중 고르지 않은 약(DOC-007). 금기·주의 확인에서도 빠짐';
COMMENT ON COLUMN guides.cache_key IS 'sha256(분석 대상 약(ai_excluded 제외) + 그 문서 진단명 + 건강정보 + 자료 기준일) (MED-008, D-04)';

-- 20-3) 금기·주의 결과: 처방 간 병용금기, 나이 판단 서버화 (D-05, D-07, F-03, S-02)
ALTER TABLE dur_alerts ADD COLUMN IF NOT EXISTS period_check_needed BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE dur_alerts DROP CONSTRAINT IF EXISTS ck_dur_alert_reason;
ALTER TABLE dur_alerts ADD CONSTRAINT ck_dur_alert_reason CHECK (trigger_reason IN (
  'PAIR_IN_DOCUMENT',       -- 같은 처방 안 두 약
  'PAIR_ACROSS_DOCUMENTS',  -- 복용 기간이 겹치는 다른 처방의 약 (D-05)
  'PROFILE_PREGNANCY',      -- user_profiles.pregnancy_status
  'AGE_MATCHED',            -- age_limit 원문을 해석해 해당
  'AGE_CHECK_NEEDED',       -- 해석 불가 또는 기준 나이 ±1세 (출생연도 근사, P-02)
  'ELDERLY_65',             -- 만 65세 이상
  'AGE_CHECK','ITEM_RULE')); -- 이전 버전 호환용(새로 만들지 않음)

-- 1차 계산 유형: CONCOMITANT(병용금기)·PREGNANCY·AGE·ELDERLY 4종만 (D-07).
--   실제 dur_type 값은 infra/db/00_precheck.sql 의 유형별 건수로 확인 후 맞출 것.
DROP FUNCTION IF EXISTS fn_dur_alerts_for_document(UUID);
CREATE FUNCTION fn_dur_alerts_for_document(p_document_id UUID)
RETURNS TABLE (dur_rule_id BIGINT, dur_type TEXT, item_id_a BIGINT, item_id_b BIGINT,
               trigger_reason TEXT, matched_code_a TEXT, matched_code_b TEXT,
               user_age SMALLINT, period_check_needed BOOLEAN)
LANGUAGE sql STABLE AS $$
  WITH doc AS (
    SELECT d.document_id, d.user_id,
           (extract(year FROM now())::int - u.birth_year)::smallint AS age,
           coalesce(p.pregnancy_status, 'NONE') AS preg,
           coalesce(d.visit_date, d.created_at::date) AS d_start,
           coalesce(d.visit_date, d.created_at::date)
             + coalesce((SELECT max(i.total_days) FROM document_items i
                          WHERE i.document_id = d.document_id), 30) - 1 AS d_end
      FROM documents d
      JOIN users u ON u.user_id = d.user_id
      LEFT JOIN user_profiles p ON p.user_id = d.user_id
     WHERE d.document_id = p_document_id
  ),
  codes AS (   -- 분석 대상 약 → 성분코드 (주성분 + 그룹). ai_excluded 약도 포함 (D-14)
    SELECT di.item_id, di.document_id, di.total_days, c.code
      FROM document_items di
      JOIN v_item_ingredients vi ON vi.item_seq = di.matched_item_seq
      CROSS JOIN LATERAL (VALUES (vi.main_ingredient_code), (vi.ingredient_group_code)) AS c(code)
     WHERE di.include_in_analysis
       AND c.code IS NOT NULL
  ),
  it AS (SELECT DISTINCT item_id, code FROM codes WHERE document_id = p_document_id),
  other AS (   -- 같은 사용자의 확인 완료된 다른 처방 중 복용 기간이 겹치는 약 (일수 없으면 30일로 보고 표시)
    SELECT DISTINCT k.item_id, k.code, (k.total_days IS NULL) AS period_unknown
      FROM codes k
      JOIN documents o ON o.document_id = k.document_id
      CROSS JOIN doc
     WHERE o.user_id = doc.user_id
       AND o.document_id <> doc.document_id
       AND o.confirmed_at IS NOT NULL
       AND coalesce(o.visit_date, o.created_at::date) <= doc.d_end
       AND coalesce(o.visit_date, o.created_at::date) + coalesce(k.total_days, 30) - 1 >= doc.d_start
  ),
  pair_in AS ( -- 같은 처방 안 서로 다른 두 약 (규칙 방향 무관)
    SELECT DISTINCT r.dur_rule_id, r.dur_type,
           least(x.item_id, y.item_id) AS a, greatest(x.item_id, y.item_id) AS b,
           'PAIR_IN_DOCUMENT'::text AS reason,
           CASE WHEN x.item_id < y.item_id THEN x.code ELSE y.code END AS ca,
           CASE WHEN x.item_id < y.item_id THEN y.code ELSE x.code END AS cb,
           false AS pc
      FROM dur_rules r
      JOIN it x ON x.code = r.ingr_code_a
      JOIN it y ON y.code = r.ingr_code_b AND y.item_id <> x.item_id
     WHERE r.ingr_code_b IS NOT NULL AND r.dur_type = 'CONCOMITANT'
  ),
  pair_across AS ( -- 이 처방의 약 x + 다른 처방의 약 y (D-05)
    SELECT DISTINCT r.dur_rule_id, r.dur_type, x.item_id AS a, y.item_id AS b,
           'PAIR_ACROSS_DOCUMENTS'::text AS reason, x.code AS ca, y.code AS cb,
           y.period_unknown AS pc
      FROM dur_rules r
      JOIN it x ON x.code IN (r.ingr_code_a, r.ingr_code_b)
      JOIN other y ON y.code = CASE WHEN x.code = r.ingr_code_a THEN r.ingr_code_b ELSE r.ingr_code_a END
     WHERE r.ingr_code_b IS NOT NULL AND r.dur_type = 'CONCOMITANT'
  ),
  age_rules AS (
    SELECT r.dur_rule_id, r.dur_type, r.ingr_code_a,
           regexp_match(coalesce(r.age_limit, ''), '([0-9]+)\s*세\s*(미만|이하|이상|초과)') AS m
      FROM dur_rules r
     WHERE r.dur_type = 'AGE' AND r.ingr_code_b IS NULL
  ),
  single AS (
    SELECT DISTINCT r.dur_rule_id, r.dur_type, x.item_id AS a, NULL::bigint AS b,
           CASE r.dur_type WHEN 'PREGNANCY' THEN 'PROFILE_PREGNANCY' ELSE 'ELDERLY_65' END AS reason,
           x.code AS ca, NULL::text AS cb, false AS pc
      FROM dur_rules r
      JOIN it x ON x.code = r.ingr_code_a
      CROSS JOIN doc
     WHERE r.ingr_code_b IS NULL
       AND (   (r.dur_type = 'PREGNANCY' AND doc.preg IN ('PREGNANT','POSSIBLE'))
            OR (r.dur_type = 'ELDERLY'   AND doc.age >= 65))
    UNION
    SELECT DISTINCT ar.dur_rule_id, ar.dur_type, x.item_id, NULL::bigint,
           CASE WHEN ar.m IS NULL OR abs(doc.age - ar.m[1]::int) <= 1
                THEN 'AGE_CHECK_NEEDED' ELSE 'AGE_MATCHED' END,
           x.code, NULL::text, false
      FROM age_rules ar
      JOIN it x ON x.code = ar.ingr_code_a
      CROSS JOIN doc
     WHERE ar.m IS NULL
        OR abs(doc.age - ar.m[1]::int) <= 1
        OR (ar.m[2] = '미만' AND doc.age <  ar.m[1]::int)
        OR (ar.m[2] = '이하' AND doc.age <= ar.m[1]::int)
        OR (ar.m[2] = '이상' AND doc.age >= ar.m[1]::int)
        OR (ar.m[2] = '초과' AND doc.age >  ar.m[1]::int)
  )
  SELECT s.dur_rule_id, s.dur_type, s.a, s.b, s.reason, s.ca, s.cb, doc.age, s.pc
    FROM (SELECT * FROM pair_in
          UNION ALL SELECT * FROM pair_across
          UNION ALL SELECT * FROM single) s
   CROSS JOIN doc
$$;

-- 화면 3을 열 때마다 다시 계산 (D-05). 다른 처방을 지우면 FK CASCADE로 처방 간 결과도 사라짐
CREATE OR REPLACE FUNCTION fn_refresh_dur_alerts(p_document_id UUID) RETURNS INTEGER
LANGUAGE plpgsql AS $$
DECLARE n INTEGER;
BEGIN
  DELETE FROM dur_alerts WHERE document_id = p_document_id;
  INSERT INTO dur_alerts (document_id, item_id_a, item_id_b, dur_rule_id, dur_type,
                          trigger_reason, matched_code_a, matched_code_b, user_age, period_check_needed)
  SELECT p_document_id, f.item_id_a, f.item_id_b, f.dur_rule_id, f.dur_type,
         f.trigger_reason, f.matched_code_a, f.matched_code_b, f.user_age, f.period_check_needed
    FROM fn_dur_alerts_for_document(p_document_id) f
  ON CONFLICT DO NOTHING;
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END $$;

-- 20-4) 복약 시간표: 시간 표시 없는 하루 1번 약 (D-01, S-03)
ALTER TABLE medication_schedules ADD COLUMN IF NOT EXISTS slot_source TEXT NOT NULL DEFAULT 'PRESCRIPTION';
ALTER TABLE medication_schedules DROP CONSTRAINT IF EXISTS ck_schedule_slot;
ALTER TABLE medication_schedules ADD CONSTRAINT ck_schedule_slot
  CHECK (slot IN ('MORNING','LUNCH','DINNER','BEDTIME','AS_NEEDED','DAILY_UNSPECIFIED'));
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_schedule_slot_source') THEN
    ALTER TABLE medication_schedules ADD CONSTRAINT ck_schedule_slot_source
      CHECK (slot_source IN ('PRESCRIPTION','USER'));
  END IF;
END $$;

-- 20-5) 삭제 기록 해시: 비밀값을 섞은 HMAC (P-09). 앱은 연결마다 SET app.hash_pepper = <.env 값>
CREATE OR REPLACE FUNCTION fn_subject_hash(p_value TEXT) RETURNS TEXT
LANGUAGE plpgsql STABLE AS $$
DECLARE k TEXT := current_setting('app.hash_pepper', true);
BEGIN
  IF k IS NULL OR k = '' THEN
    RAISE EXCEPTION 'HASH_PEPPER_NOT_SET';
  END IF;
  RETURN encode(hmac(convert_to(p_value, 'UTF8'), convert_to(k, 'UTF8'), 'sha256'), 'hex');
END $$;
COMMENT ON COLUMN deletion_logs.subject_hash IS 'fn_subject_hash(user_id 또는 document_id): HMAC-SHA256, 비밀값 없이 되돌릴 수 없음';

-- 20-6) 회원 탈퇴 (해시만 교체)
CREATE OR REPLACE FUNCTION fn_withdraw_user(p_user_id BIGINT) RETURNS TEXT[]
LANGUAGE plpgsql AS $$
DECLARE paths TEXT[]; counts JSONB;
BEGIN
  SELECT coalesce(array_agg(storage_path) FILTER (WHERE storage_path IS NOT NULL), '{}')
    INTO paths FROM documents WHERE user_id = p_user_id;
  SELECT jsonb_build_object(
           'documents',     (SELECT count(*) FROM documents     WHERE user_id = p_user_id),
           'guides',        (SELECT count(*) FROM guides        WHERE user_id = p_user_id),
           'chat_sessions', (SELECT count(*) FROM chat_sessions WHERE user_id = p_user_id),
           'consent_logs',  (SELECT count(*) FROM consent_logs  WHERE user_id = p_user_id))
    INTO counts;
  INSERT INTO deletion_logs (kind, subject_hash, deleted_counts, storage_paths)
  VALUES ('USER_WITHDRAW', fn_subject_hash(p_user_id::text), counts, paths);
  DELETE FROM users WHERE user_id = p_user_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'USER_NOT_FOUND';
  END IF;
  RETURN paths;
END $$;

-- 20-7) 기록 지우기 (D8, D-11, D-19, D-20): 문서 단위 철회 기록 → 승인 전 오타 후보 삭제 → 연쇄 삭제
--   지우는 것: 원본(경로 반환), 문서(진단명·병원명·OCR 원문·JSON), 처방 항목, 안내서·근거, 시간표,
--             금기·주의 결과(다른 처방의 처방 간 결과 포함), 대화방·메시지, 신고
--   남는 것: 동의·철회 행(document_id 는 NULL 로), 삭제 기록(HMAC·건수), 승인된 오타 사전 항목
CREATE OR REPLACE FUNCTION fn_delete_document(p_user_id BIGINT, p_document_id UUID) RETURNS TEXT
LANGUAGE plpgsql AS $$
DECLARE v_path TEXT; v_terms TEXT; counts JSONB;
BEGIN
  SELECT d.storage_path, c.terms_version INTO v_path, v_terms
    FROM documents d LEFT JOIN consent_logs c ON c.consent_log_id = d.consent_log_id
   WHERE d.document_id = p_document_id AND d.user_id = p_user_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'DOCUMENT_NOT_FOUND';
  END IF;
  INSERT INTO consent_logs (user_id, consent_type, action, terms_version, channel, scope, document_id)
  SELECT p_user_id, t, 'WITHDRAW', coalesce(v_terms, 'unknown'), 'WEB', 'DOCUMENT', p_document_id
    FROM unnest(ARRAY['DOCUMENT_PROCESSING','HEALTH_SENSITIVE']) AS t;
  SELECT jsonb_build_object(
           'items',          (SELECT count(*) FROM document_items WHERE document_id = p_document_id),
           'guides',         (SELECT count(*) FROM guides         WHERE document_id = p_document_id),
           'chat_sessions',  (SELECT count(*) FROM chat_sessions  WHERE document_id = p_document_id))
    INTO counts;
  DELETE FROM ocr_typo_dictionary
   WHERE NOT approved
     AND from_item_id IN (SELECT item_id FROM document_items WHERE document_id = p_document_id);
  INSERT INTO deletion_logs (kind, subject_hash, deleted_counts, storage_paths)
  VALUES ('USER_DELETE_RECORD', fn_subject_hash(p_document_id::text),
          counts, CASE WHEN v_path IS NULL THEN '{}'::text[] ELSE ARRAY[v_path] END);
  DELETE FROM documents WHERE document_id = p_document_id AND user_id = p_user_id;
  RETURN v_path;
END $$;

-- 20-8) 건강 민감정보 동의 전체 철회 (U2, D-02, D-13, P-10): 모든 처방 기록 + 문서 없는 대화방 + 건강정보
CREATE OR REPLACE FUNCTION fn_withdraw_health_consent(p_user_id BIGINT, p_terms_version TEXT)
RETURNS TEXT[]
LANGUAGE plpgsql AS $$
DECLARE r RECORD; p TEXT; paths TEXT[] := '{}';
BEGIN
  INSERT INTO consent_logs (user_id, consent_type, action, terms_version, channel, scope)
  VALUES (p_user_id, 'HEALTH_SENSITIVE', 'WITHDRAW', p_terms_version, 'WEB', 'USER');
  FOR r IN SELECT document_id FROM documents WHERE user_id = p_user_id LOOP
    p := fn_delete_document(p_user_id, r.document_id);
    IF p IS NOT NULL THEN paths := paths || p; END IF;
  END LOOP;
  DELETE FROM chat_sessions WHERE user_id = p_user_id AND document_id IS NULL;
  DELETE FROM user_profiles WHERE user_id = p_user_id;
  RETURN paths;
END $$;

-- 20-9) 원본 파일 삭제: 확인 완료 즉시 또는 읽기 완료 24시간 뒤 (D-03, PR-01). OCR 원문도 함께 비움
CREATE OR REPLACE FUNCTION fn_purge_original(p_document_id UUID) RETURNS TEXT
LANGUAGE plpgsql AS $$
DECLARE v_path TEXT;
BEGIN
  SELECT storage_path INTO v_path FROM documents WHERE document_id = p_document_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'DOCUMENT_NOT_FOUND';
  END IF;
  UPDATE documents
     SET storage_path = NULL, ocr_raw = NULL,
         original_deleted_at = coalesce(original_deleted_at, now())
   WHERE document_id = p_document_id;
  IF v_path IS NOT NULL THEN
    INSERT INTO deletion_logs (kind, subject_hash, deleted_counts, storage_paths)
    VALUES ('ORIGINAL_FILE_PURGE', fn_subject_hash(p_document_id::text), '{"files":1}'::jsonb, ARRAY[v_path]);
  END IF;
  RETURN v_path;   -- 앱이 실제 파일을 지운다
END $$;
COMMENT ON COLUMN documents.ocr_raw IS '가림 처리 후 저장, 원본 삭제(fn_purge_original) 때 NULL (PR-01)';

-- 20-10) 추천·상황 질문 시드 갱신 (D-09, D-12, S-04)
DELETE FROM chat_preset_questions WHERE preset_code = 'SIT-OTHERHOSP';
INSERT INTO chat_preset_questions (preset_code, category, question_text, show_when, sort_order) VALUES
  ('SIT-OTHERDRUG','SITUATION','다른 약도 먹고 있어요',                                   '{}', 1010),
  ('SIT-DROWSY',   'SITUATION','졸리거나 어지러워요',                                     '{}', 1025),
  ('SIT-PREG',     'SITUATION','임신·수유 중이에요',                                       '{"pregnancy_or_breastfeeding":true}', 1030),
  ('BND-WHY',      'BOUNDARY', '이 약이 제 병과 안 맞는 것 같아요. 왜 처방됐나요?',        '{}', 930)
ON CONFLICT (preset_code) DO UPDATE
  SET question_text = EXCLUDED.question_text, show_when = EXCLUDED.show_when, sort_order = EXCLUDED.sort_order;

COMMIT;

-- =============================================================================
-- 적용 후 점검 쿼리 (수동 실행)
-- -----------------------------------------------------------------------------
-- 1) EDI FK 고아 행 수 → 0이면 VALIDATE
--    SELECT count(*) FROM medicine_edi_codes e LEFT JOIN medicines m USING (item_seq) WHERE m.item_seq IS NULL;
-- 2) DUR ↔ 주성분코드 연결률 (계획서 '가장 위험한 부분')
--    SELECT dur_type, count(*) total,
--           count(*) FILTER (WHERE EXISTS (SELECT 1 FROM v_item_ingredients i
--                 WHERE r.ingr_code_a IN (i.main_ingredient_code, i.ingredient_group_code))) linked
--      FROM dur_rules r GROUP BY dur_type ORDER BY total DESC;
-- 3) 자동완성 속도 (목표: 일반 화면 3초 이내, SYS-001)
--    EXPLAIN ANALYZE SELECT * FROM fn_search_medicines('타이레놀500', 10);
-- =============================================================================
