# 안심약국 API 명세서

> 기준: 요구사항 정의서(261125), `infra/db/schema.sql`, `docs/ERD_초안.md`, `docs/wireframe_5screens_초안.md`, `docs/privacy_policy_draft.md`, `docs/review/decision_log_261125.md`
> 261125 수정: 기획 검토 결정(D-01~D-24, F·S·W·PR·P 항목) 반영. 바뀐 엔드포인트는 **8장 변경 사항**이 각 절보다 우선합니다.
> 백엔드: FastAPI + Pydantic / 라우터: `app/routers/{auth, documents, drugs, guides, chat, system}`
> 형식: OT 자료집 「기획 문서 안내 2」의 API 명세서 구성(API 개요 → 요청 → 응답)을 따릅니다.

---

## 0. 공통 규칙

### 0-1. 기본 정보

| 항목 | 내용 |
|---|---|
| Base URL | `https://<배포 도메인>/api/v1` (로컬: `http://localhost:8000/api/v1`) |
| 데이터 형식 | JSON (UTF-8). 파일 업로드만 `multipart/form-data` |
| 날짜·시각 | 날짜 `YYYY-MM-DD`, 시각 ISO 8601 `+09:00` |
| ID | `document_id`, `guide_id`, `session_id`는 UUID / 나머지는 정수 |
| 문서 | FastAPI 자동 문서 `/docs`(Swagger)로 실제 스키마 확인 |

와이어프레임 문서의 경로는 `/api/v1` 접두어를 생략해 적었습니다. `POST /documents`는 실제로 `POST /api/v1/documents`입니다.

### 0-2. 인증

| 구분 | 방식 |
|---|---|
| access 토큰 | 로그인 응답 본문으로 받고, 요청마다 `Authorization: Bearer <access_token>` 헤더로 보냄. 유효 30분 (USR-002) |
| refresh 토큰 | `HttpOnly; Secure; SameSite=Strict` 쿠키 `refresh_token`. 유효 14일, DB에는 해시만 저장(`auth_refresh_tokens`) |
| 만료 처리 | 401 `TOKEN_EXPIRED`를 받으면 화면이 `POST /auth/refresh` 후 원래 요청을 한 번 다시 보냄 (USR-003) |
| 12/4 초기 모델 | `.env`의 `AUTH_MODE=demo`이면 토큰 없이 `user_id=1`로 동작. 12/7 이후 `AUTH_MODE=jwt` |
| 남의 자료 | 다른 사용자의 문서·안내서·대화방은 존재 여부를 숨기기 위해 403이 아니라 **404** `NOT_FOUND`로 응답 |

표의 "인증" 칸: **Y** = access 토큰 필요, **N** = 필요 없음.

### 0-3. 오류 응답 형식

```json
{ "error_code": "FILE_TOO_LARGE", "message": "파일이 20MB를 넘어요.", "detail": { "max_bytes": 20971520 } }
```

`message`는 화면에 그대로 보여줄 쉬운 문장입니다(SYS-002). FastAPI 기본 검증 오류(422)는 `RequestValidationError` 핸들러로 400 `VALIDATION_ERROR`로 바꿉니다(F-05). 실행 중 공공 API를 부르지 않으므로 502는 쓰지 않습니다(P-05). 실패가 "주의 문구 없음"처럼 보이지 않도록, 오류는 항상 이 형식으로 따로 보냅니다.

| HTTP | error_code | 상황 |
|---|---|---|
| 400 | `VALIDATION_ERROR` | 요청 형식 오류 (Pydantic 검증 실패, `detail`에 필드 목록) |
| 401 | `UNAUTHORIZED` / `TOKEN_EXPIRED` / `INVALID_CREDENTIALS` | 토큰 없음 / 만료 / 로그인 실패 |
| 403 | `CONSENT_REQUIRED` | 업로드 요청에 문서 처리 동의·건강 민감정보 동의 체크가 없음 (D1, 건별 동의 D-02) |
| 403 | `HEALTH_CONSENT_REQUIRED` | 건강 민감정보 동의가 현재 유효하지 않음 → 건강정보 저장(U4), 안내서(G1), 대화(C1·C3) 불가 (F-01) |
| 404 | `NOT_FOUND` / `DOCUMENT_NOT_FOUND` | 없거나 내 것이 아님 |
| 409 | `EMAIL_EXISTS` / `ITEMS_NOT_CONFIRMED` | 이메일 중복 / 확인 안 된 약이 있음 |
| 413 | `FILE_TOO_LARGE` | 20MB 초과 |
| 415 | `UNSUPPORTED_TYPE` | JPG·PNG·HEIC·PDF 외 |
| 422 | `PDF_TOO_MANY_PAGES` | PDF 50쪽 초과 |
| 429 | `LLM_DAILY_LIMIT` | AI 호출 일일 한도(서비스 전체 기준 200회) 초과. 화면: "오늘 AI 안내를 만들 수 있는 횟수를 다 썼어요. 주의 문구와 시간표는 그대로 볼 수 있어요." |
| 503 | `LLM_UNAVAILABLE` | Claude API 실패. 주의 문구 원문은 계속 볼 수 있음 |

### 0-4. 목록 페이지네이션

목록 API는 `?limit=30&cursor=<next_cursor>`로 넘깁니다. 응답에 `"next_cursor": null`이면 마지막 페이지입니다.

### 0-5. 전체 목록

| # | 메서드 | 경로 | 설명 | 인증 | 요구사항 | 화면 |
|---|---|---|---|---|---|---|
| A1 | POST | `/auth/signup` | 회원가입 | N | USR-001 | — |
| A2 | POST | `/auth/login` | 로그인 | N | USR-002 | — |
| A3 | POST | `/auth/refresh` | 토큰 재발급 | 쿠키 | USR-003 | — |
| A4 | POST | `/auth/logout` | 로그아웃 | Y | USR-003 | — |
| U1 | GET | `/users/me/consents` | 동의 현황 | Y | USR-004 | 1 |
| U2 | POST | `/users/me/consents` | 동의 철회 (마이페이지 '동의 관리', 건강 민감정보 전체 철회) | Y | USR-004 | 마이 |
| U3 | GET | `/users/me/health` | 건강정보 조회 | Y | USR-005 | 마이 |
| U4 | PATCH | `/users/me/health` | 건강정보 수정 | Y | USR-005 | 마이 |
| U5 | GET | `/users/me/records` | 내 기록 목록 | Y | USR-006 | 마이 |
| U6 | DELETE | `/users/me` | 회원 탈퇴 | Y | USR-006 | 마이 |
| D1 | POST | `/documents` | 문서 업로드 (건별 동의 함께 기록) | Y | DOC-001·007, USR-004 | 1 |
| D2 | GET | `/documents/{document_id}/status` | 처리 상태 | Y | DOC-002·006 | 1 |
| D3 | GET | `/documents/{document_id}/items` | 추출 약 목록 | Y | DOC-003·005 | 2 |
| D4 | PATCH | `/documents/{document_id}/items/{item_id}` | 약 한 줄 수정 (AI 안내 받지 않기 포함) | Y | DOC-005, MED-009 | 2 |
| D9 | PATCH | `/documents/{document_id}` | 진단명·진료일 수정, 처방 전체 AI 안내 받지 않기 | Y | DOC-005, SYS-005 | 2·기록 관리 |
| D5 | POST | `/documents/{document_id}/items` | 빠진 약 추가 | Y | DOC-005 | 2 |
| D6 | PUT | `/documents/{document_id}/confirmation` | 확인 완료 | Y | DOC-005 | 2 |
| D7 | GET | `/documents/{document_id}/analysis` | 나에게 맞춘 의약품 정보(DUR)·의약품 허가 정보·확인할 내용 | Y | MED-002~005, SAF-005 | 3 |
| D8 | DELETE | `/documents/{document_id}` | 기록 지우기 (기록 관리 화면) | Y | USR-006 | 기록 관리 |
| R1 | GET | `/drugs/search` | 약 이름 자동완성 | Y | DOC-004·005 | 2 |
| R2 | GET | `/drugs/{item_seq}` | 약 상세 | Y | MED-001 | 2 |
| G1 | POST | `/documents/{document_id}/guides` | AI가 쉽게 풀어 쓴 복약 안내 생성·재조회 | Y | MED-006·008, SAF-001·002·004, SYS-005 | 3 |
| G2 | GET | `/guides/{guide_id}` | 안내서 조회 | Y | MED-004·006 | 3 |
| G3 | POST | `/guides/{guide_id}/feedback` | 좋아요·별로예요 | Y | MED-008 | 3 |
| G4 | POST | `/guides/{guide_id}/regenerate` | 다시 만들기 | Y | MED-009 | 3 |
| G5 | GET | `/guides/{guide_id}/schedule` | 복약 시간표 | Y | MED-007 | 4 |
| G6 | POST | `/guides/{guide_id}/reports` | 안내서 신고 | Y | SAF-003 | 3 |
| C1 | POST | `/chat/sessions` | 대화방 만들기 | Y | CHT-001 | 5 |
| C2 | GET | `/chat/sessions/{session_id}/messages` | 대화 목록 | Y | CHT-001 | 5 |
| C3 | POST | `/chat/sessions/{session_id}/messages` | 질문 보내기 | Y | CHT-002·003, SAF-001·002 | 5 |
| C4 | POST | `/chat/sessions/{session_id}/visit-questions` | 방문 전 질문 | Y | CHT-004 | 5 |
| C5 | DELETE | `/chat/sessions/{session_id}` | 대화방 삭제 | Y | USR-006 | 5 |
| C6 | POST | `/chat/messages/{message_id}/reports` | 답변 신고 | Y | SAF-003 | 5 |
| S1 | GET | `/data-versions` | 자료 기준일 | N | DAT-001 | 3·4·5 |
| S2 | GET | `/health` | 서버·DB 상태 | N | SYS-003 | — |

선택 기능 USR-007(소셜 로그인)은 2차 범위라 맨 끝 부록에 경로만 적었습니다.

---

## 1. 회원·인증 (`auth`)

### A1. 회원가입

| 항목 | 내용 |
|---|---|
| API 이름 | 이메일 회원가입 |
| 설명 | 이메일·비밀번호·출생연도로 가입. 가입과 동시에 이용약관·개인정보 동의를 `consent_logs`에 기록 |
| 엔드포인트 | `/api/v1/auth/signup` |
| 메서드 | POST |
| 인증 필요 여부 | N |
| DB | `users`, `consent_logs` |

**요청 Body**

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `email` | string | Y | 이메일 형식, 대소문자 구분 없이 중복 불가 |
| `password` | string | Y | 8자 이상. bcrypt 해시로 저장 |
| `birth_year` | int | Y | 1900~현재. 만 14세 미만 가입 제한은 처리방침 결정에 따름 |
| `name` | string | N | 선택. AI로 보내지 않음 |
| `gender` | string | N | `M` / `F` / `OTHER` |
| `consents` | object | Y | `{"TERMS": true, "PRIVACY": true}` 둘 다 true여야 가입 |
| `terms_version` | string | Y | 예: `v1.0-2026-12-08` |

**응답 201**

```json
{ "user_id": 12, "email": "user@example.com", "created_at": "2026-12-07T10:00:00+09:00" }
```

**오류**: 409 `EMAIL_EXISTS`, 400 `VALIDATION_ERROR`

### A2. 로그인

| 항목 | 내용 |
|---|---|
| 엔드포인트 | `/api/v1/auth/login` |
| 메서드 | POST |
| 인증 필요 여부 | N |
| DB | `users.last_login_at`, `auth_refresh_tokens` |

**요청 Body**

```json
{ "email": "user@example.com", "password": "********" }
```

**응답 200** (refresh 토큰은 `Set-Cookie: refresh_token=...; HttpOnly; Secure; SameSite=Strict; Max-Age=1209600`)

```json
{ "access_token": "eyJ...", "token_type": "Bearer", "expires_in": 1800, "user": { "user_id": 12, "email": "user@example.com" } }
```

**오류**: 401 `INVALID_CREDENTIALS` (이메일·비밀번호 중 무엇이 틀렸는지 구분하지 않음)

### A3. 토큰 재발급

| 항목 | 내용 |
|---|---|
| 엔드포인트 | `/api/v1/auth/refresh` |
| 메서드 | POST |
| 인증 필요 여부 | refresh 쿠키 |

요청 본문은 없습니다. 쓰인 refresh 토큰은 폐기(`revoked_at`)하고 새 refresh 쿠키와 access 토큰을 줍니다.

**응답 200**: A2와 같은 형식 / **오류**: 401 `TOKEN_EXPIRED`

### A4. 로그아웃

| 항목 | 내용 |
|---|---|
| 엔드포인트 | `/api/v1/auth/logout` |
| 메서드 | POST |
| 인증 필요 여부 | Y |

현재 refresh 토큰을 폐기하고 쿠키를 지웁니다. **응답 204** (본문 없음)

---

## 2. 내 정보 (`auth` 라우터, `/users/me`)

### U1. 동의 현황

| 항목 | 내용 |
|---|---|
| 엔드포인트 | `/api/v1/users/me/consents` |
| 메서드 | GET |
| 인증 필요 여부 | Y |
| DB | `fn_has_active_consent(user_id, type)` |

**응답 200**

```json
{ "TERMS": true, "PRIVACY": true, "HEALTH_SENSITIVE": false, "DOCUMENT_PROCESSING": false,
  "terms_version": "v1.0-2026-12-08" }
```

### U2. 동의·철회 기록

| 항목 | 내용 |
|---|---|
| 엔드포인트 | `/api/v1/users/me/consents` |
| 메서드 | POST |
| 인증 필요 여부 | Y |
| DB | `consent_logs` (누적 전용, 수정 불가) |

**요청 Body**

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `items[].consent_type` | string | Y | `TERMS` / `PRIVACY` / `HEALTH_SENSITIVE` / `DOCUMENT_PROCESSING` |
| `items[].action` | string | Y | `AGREE` / `WITHDRAW` |
| `terms_version` | string | Y | 약관 판 |
| `channel` | string | N | `WEB`(기본) / `UPLOAD` / `SIGNUP` |

```json
{ "items": [ {"consent_type": "DOCUMENT_PROCESSING", "action": "AGREE"},
             {"consent_type": "HEALTH_SENSITIVE", "action": "AGREE"} ],
  "terms_version": "v1.0-2026-12-08", "channel": "UPLOAD" }
```

**응답 201**

```json
{ "consent_log_ids": { "DOCUMENT_PROCESSING": 41, "HEALTH_SENSITIVE": 42 } }
```

`HEALTH_SENSITIVE`를 `WITHDRAW`하면 서버가 `user_profiles` 행도 함께 지웁니다.

### U3. 건강정보 조회 / U4. 건강정보 수정

| 항목 | 내용 |
|---|---|
| 엔드포인트 | `/api/v1/users/me/health` |
| 메서드 | GET / PATCH |
| 인증 필요 여부 | Y |
| DB | `user_profiles` (건강 민감정보 동의 없으면 DB 트리거가 저장 차단) |

**PATCH 요청 Body** (보낸 필드만 바뀜)

| 필드 | 타입 | 설명 |
|---|---|---|
| `pregnancy_status` | string | `NONE` / `PREGNANT` / `POSSIBLE` |
| `is_breastfeeding` | bool | 수유 여부 |
| `chronic_conditions` | string[] | 지병. 버튼값(고혈압·당뇨·위염 등) + 자유 입력 |
| `allergies` | string[] | 알레르기 자유 입력 |

**응답 200 (GET·PATCH 공통)**

```json
{ "pregnancy_status": "NONE", "is_breastfeeding": false, "chronic_conditions": ["고혈압"],
  "allergies": [], "updated_at": "2026-12-08T14:00:00+09:00" }
```

**오류**: 403 `HEALTH_CONSENT_REQUIRED`

### U5. 내 기록 목록

| 항목 | 내용 |
|---|---|
| 엔드포인트 | `/api/v1/users/me/records?limit=30&cursor=` |
| 메서드 | GET |
| 인증 필요 여부 | Y |
| DB | `documents`, `document_items`, `guides`, `chat_sessions` |

**응답 200**

```json
{ "records": [ { "document_id": "8f0c…", "doc_type": "PRESCRIPTION", "visit_date": "2026-11-26",
                 "item_count": 3, "status": "CONFIRMED", "guide_count": 1, "chat_session_count": 1,
                 "created_at": "2026-11-26T09:12:00+09:00" } ],
  "next_cursor": null }
```

### U6. 회원 탈퇴

| 항목 | 내용 |
|---|---|
| 엔드포인트 | `/api/v1/users/me` |
| 메서드 | DELETE |
| 인증 필요 여부 | Y |
| DB | `fn_withdraw_user(user_id)` → 모든 사용자 데이터 CASCADE 삭제, `deletion_logs`에 해시만 기록 |

**요청 Body**: `{ "confirm": true }` (실수 방지)
**응답 204**. 서버는 함수가 돌려준 원본 파일 경로를 저장소에서 지우고 refresh 쿠키를 삭제합니다.

---

## 3. 문서·OCR (`documents`)

### D1. 문서 업로드

| 항목 | 내용 |
|---|---|
| API 이름 | 처방전·약봉투·진료기록 올리기 |
| 설명 | 파일 검사 후 비공개 저장소에 저장하고 글자 읽기를 백그라운드로 시작 |
| 엔드포인트 | `/api/v1/documents` |
| 메서드 | POST (`multipart/form-data`) |
| 인증 필요 여부 | Y |
| DB | `documents` (본인의 DOCUMENT_PROCESSING AGREE 행이 있어야 INSERT) |

**요청 Form**

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `file` | file | Y | JPG·PNG·HEIC·PDF, 20MB 이하, PDF 50쪽 이하. HEIC는 서버에서 JPG로 변환 |
| `doc_type` | string | Y | `PRESCRIPTION` / `MED_BAG` / `MEDICAL_RECORD_PDF` |
| `consent_log_id` | int | Y | U2에서 받은 DOCUMENT_PROCESSING 동의 행 |

**응답 202**

```json
{ "document_id": "8f0c…", "status": "UPLOADED", "status_url": "/api/v1/documents/8f0c…/status" }
```

**오류**: 413 `FILE_TOO_LARGE`, 415 `UNSUPPORTED_TYPE`, 422 `PDF_TOO_MANY_PAGES`, 428 `CONSENT_REQUIRED`

처리 방식은 이렇습니다. `MEDICAL_RECORD_PDF`는 `source_track=A_PDF_PARSE`로 PyMuPDF가 글자·표를 바로 읽습니다. 그 외는 `B_OCR`로, 글자가 든 PDF는 바로 추출하고 사진·스캔 PDF는 RapidOCR로 읽습니다. 읽기가 끝나면 `purge_after = extracted_at + 24시간`이 정해집니다(SYS-001).

### D2. 처리 상태

| 항목 | 내용 |
|---|---|
| 엔드포인트 | `/api/v1/documents/{document_id}/status` |
| 메서드 | GET (화면이 1.5초 간격으로 호출) |
| 인증 필요 여부 | Y |

**응답 200**

| 필드 | 설명 |
|---|---|
| `status` | `UPLOADED` → `EXTRACTING` → `EXTRACTED` → `STRUCTURED` → `MATCHED` / `NEEDS_RETAKE` / `FAILED` |
| `quality` | `{ "ocr_avg_confidence": 0.52, "ocr_char_count": 14 }` — 0.6 미만 또는 20자 미만이면 `NEEDS_RETAKE` (DOC-006) |
| `error_code` | 실패 시 `OCR_LOW_QUALITY` 등 |
| `next` | `MATCHED`가 되면 `"/review.html?doc=8f0c…"` |

```json
{ "document_id": "8f0c…", "status": "NEEDS_RETAKE",
  "quality": { "ocr_avg_confidence": 0.52, "ocr_char_count": 14 },
  "error_code": "OCR_LOW_QUALITY", "message": "글자가 흐려 정확히 읽기 어려워요. 밝은 곳에서 평평하게 다시 찍어 주세요.",
  "next": null }
```

### D3. 추출 약 목록

| 항목 | 내용 |
|---|---|
| 엔드포인트 | `/api/v1/documents/{document_id}/items` |
| 메서드 | GET |
| 인증 필요 여부 | Y |
| DB | `documents`, `document_items` ⨝ `medicines` |

**응답 200** (약 한 줄의 필드)

| 필드 | 타입 | 설명 |
|---|---|---|
| `item_id` | int | |
| `line_no` | int | 문서 내 순서 |
| `drug_name` / `raw_text` / `ocr_confidence` | string / string / float | 정리된 이름 / OCR 원문 / 줄 신뢰도 |
| `edi_code` | string\|null | 9자리 보험코드 |
| `dose_per_time` / `dose_unit` | float / string | 1회량(0.5 허용) / 정·캡슐·mL… |
| `times_per_day` / `total_days` | int | 하루 횟수 / 총 일수 |
| `timing_text` | string | 처방 원문 그대로("식후 30분") |
| `matched_item_seq` / `matched_item_name` | string\|null | 연결된 식약처 품목 |
| `match_method` / `match_score` | string / float | `EDI_EXACT`·`NAME_TRGM`·`USER_SELECTED`·`NONE` / 0~1 |
| `match_candidates` | array | 상위 후보 `[{item_seq, item_name, score}]` |
| `needs_review` | bool | true면 노란 경고 (점수 < `MATCH_REVIEW_THRESHOLD`, 기본 0.7) |
| `user_confirmed` / `include_in_analysis` | bool | 확인 여부 / 분석 포함(진료기록 과거 약은 기본 false) |
| `dispensed_date` | date\|null | 진료기록의 조제일 |

```json
{ "document": { "document_id": "8f0c…", "doc_type": "PRESCRIPTION", "visit_date": "2026-11-26",
                "diagnoses": [{"name": "고혈압", "kcd_code": "I10"}], "status": "MATCHED" },
  "items": [ { "item_id": 103, "line_no": 3, "drug_name": "이소트레티논캡슐10", "raw_text": "이소트레티논캡슐10 0.5 1 7 취침전",
               "ocr_confidence": 0.71, "edi_code": null, "dose_per_time": 0.5, "dose_unit": "캡슐",
               "times_per_day": 1, "total_days": 7, "timing_text": "취침 전",
               "matched_item_seq": "200000004", "matched_item_name": "졸피뎀정10밀리그램",
               "match_method": "NAME_TRGM", "match_score": 0.62,
               "match_candidates": [{"item_seq": "200000004", "item_name": "졸피뎀정10밀리그램", "score": 0.62}],
               "needs_review": true, "user_confirmed": false, "include_in_analysis": true, "dispensed_date": null } ] }
```

### D4. 약 한 줄 수정

| 항목 | 내용 |
|---|---|
| 엔드포인트 | `/api/v1/documents/{document_id}/items/{item_id}` |
| 메서드 | PATCH (보낸 필드만 바뀜) |
| 인증 필요 여부 | Y |
| DB | `document_items`, `ocr_typo_dictionary` |

**요청 Body**: `matched_item_seq`, `dose_per_time`, `dose_unit`, `times_per_day`, `total_days`, `timing_text`, `include_in_analysis`, `user_confirmed` 중 바꿀 것만

```json
{ "matched_item_seq": "200000004", "user_confirmed": true }
```

**응답 200**: D3의 약 한 줄과 같은 형식

약을 바꾸면 서버가 `match_method=USER_SELECTED`, `match_score=1.0`, `needs_review=false`, `is_user_edited=true`로 바꿉니다. 원래 OCR 이름과 다르면 오타 사전 후보(`approved=false`)로 쌓습니다. 이미 안내서가 있는 문서라면 `cache_key`가 달라져 화면 3에 [다시 만들기]가 뜹니다.

**오류**: 400 `VALIDATION_ERROR` (예: `user_confirmed=true`인데 `matched_item_seq` 없음)

### D5. 빠진 약 추가

| 항목 | 내용 |
|---|---|
| 엔드포인트 | `/api/v1/documents/{document_id}/items` |
| 메서드 | POST |
| 인증 필요 여부 | Y |

**요청 Body**: D4와 같은 필드 + `drug_name`(필수). `line_no`는 서버가 마지막 번호 + 1로 채웁니다. **응답 201**: 약 한 줄

### D6. 확인 완료

| 항목 | 내용 |
|---|---|
| 엔드포인트 | `/api/v1/documents/{document_id}/confirmation` |
| 메서드 | PUT |
| 인증 필요 여부 | Y |
| DB | `documents.status='CONFIRMED'`, `drug_warnings`(없으면 생성), `fn_refresh_dur_alerts` |

요청 본문은 없습니다.

**응답 200**

```json
{ "status": "CONFIRMED", "confirmed_at": "2026-11-27T10:12:00+09:00", "dur_alert_count": 4, "next": "/guide.html?doc=8f0c…" }
```

**오류**: 409 `ITEMS_NOT_CONFIRMED` → `{ "detail": { "item_ids": [103] } }`

### D7. 주의 분석·DUR

| 항목 | 내용 |
|---|---|
| API 이름 | 약별 주의 문구 6유형 + 공식 DUR 결과 |
| 설명 | DB 조회만 하고 AI를 쓰지 않음. 위험도 점수 없이 공식 원문만 보여줌 |
| 엔드포인트 | `/api/v1/documents/{document_id}/analysis` |
| 메서드 | GET |
| 인증 필요 여부 | Y |
| DB | `dur_alerts` ⨝ `dur_rules`, `drug_warnings`, `data_versions`, `user_profiles` |

**응답 200 주요 필드**

| 필드 | 설명 |
|---|---|
| `profile_flags` | 임신·수유·나이·지병 (유형 정렬에만 쓰고 결론은 내지 않음) |
| `dur_alerts[]` | `dur_type`, `badge`(함께 복용 금기·임부 금기·고령자 주의·연령 주의), `trigger_reason`, `items[]`, `rule{prohibition_content, grade, age_limit}`, `source{source_name, base_label}` |
| `dur_unlinked_item_ids` | 성분코드가 연결 안 돼 "DUR 확인 필요"로 보여줄 약 |
| `warnings_by_item[].status` | `OK` / `NO_WARNING`(공식 문구 없음, MED-005) / `NEED_CHECK`(조회 실패) |
| `warnings_by_item[].types[]` | 6유형 `warning_type`, `label`, `pinned`(건강정보 관련이라 위로), `sentences[]` 원문 |

```json
{ "profile_flags": { "pregnancy_status": "NONE", "is_breastfeeding": false, "age_band": "60대", "is_65_or_over": true, "age_note": "출생연도 기준", "chronic_conditions": ["고혈압"] },
  "dur_alerts": [ { "alert_id": 1, "dur_type": "CONCOMITANT", "badge": "함께 복용 금기", "trigger_reason": "PAIR_IN_DOCUMENT",
                    "items": [{"item_id": 101, "name": "와파린정2밀리그램"}, {"item_id": 102, "name": "쎄레브렉스캡슐200밀리그램"}],
                    "rule": { "dur_rule_id": 5521, "ingr_name_a": "와파린", "ingr_name_b": "세레콕시브", "grade": "1",
                              "age_limit": null, "prohibition_content": "출혈 위험 증가" },
                    "source": { "source_name": "DUR 성분단위 정보", "base_label": "2026.6 고시" } } ],
  "dur_unlinked_item_ids": [],
  "warnings_by_item": [ { "item_seq": "200000004", "item_name": "졸피뎀정10밀리그램", "status": "OK",
                          "types": [ { "warning_type": "DAILY_LIFE", "label": "일상생활 주의(졸음·운전)", "pinned": true,
                                       "sentences": [{ "warning_id": 9001, "article_title": "임부 및 수유부에 대한 투여", "sentence": "…", "life_flags": [] }] } ],
                          "source": { "source_name": "식약처 의약품 제품 허가정보", "base_date": "2026-11-20" } } ] }
```

`AGE`의 `trigger_reason=AGE_CHECK`는 화면이 `age_limit` 원문과 `age`를 대조해 해당할 때만 배지를 보여줍니다.

### D8. 처방 기록 삭제

| 항목 | 내용 |
|---|---|
| 엔드포인트 | `/api/v1/documents/{document_id}` |
| 메서드 | DELETE |
| 인증 필요 여부 | Y |
| DB | `fn_delete_document(user_id, document_id)` → 약·안내서·시간표·DUR 결과·대화방·신고 CASCADE |

**응답 200**

```json
{ "deleted": { "documents": 1, "document_items": 3, "guides": 2, "chat_sessions": 1 } }
```

함수가 원본 파일 경로를 돌려주면(24시간 전이라 남아 있으면) 서버가 저장소에서 지웁니다. **오류**: 404 `DOCUMENT_NOT_FOUND`

---

## 4. 의약품 (`drugs`)

### R1. 약 이름 자동완성

| 항목 | 내용 |
|---|---|
| 엔드포인트 | `/api/v1/drugs/search?q=이소트레&limit=10` |
| 메서드 | GET |
| 인증 필요 여부 | Y |
| DB | `fn_search_medicines(q, limit)` (정상 품목만, 정규화 이름 trigram) |

**Query**: `q`(2자 이상, 필수), `limit`(1~20, 기본 10)

**응답 200**

```json
[ { "item_seq": "200000004", "item_name": "졸피뎀정10밀리그램", "entp_name": "○○제약", "score": 0.90 } ]
```

목표 응답 시간은 0.5초 이내입니다. 화면은 250ms 디바운스로 호출합니다.

### R2. 약 상세

| 항목 | 내용 |
|---|---|
| 엔드포인트 | `/api/v1/drugs/{item_seq}` |
| 메서드 | GET |
| 인증 필요 여부 | Y |
| DB | `medicines` 정확 조회 |

**응답 200**

```json
{ "item_seq": "200000004", "item_name": "졸피뎀정10밀리그램", "entp_name": "○○제약",
  "efficacy": "…", "usage": "…", "easy_description": null, "pill_image_url": "https://…",
  "source": { "source_name": "식약처 의약품 제품 허가정보", "base_date": "2026-11-20" } }
```

`easy_description`은 e약은요 자료가 있는 일반의약품만 채워지고, 없으면 허가정보 원문을 보여줍니다.

---

## 5. 안내서·시간표 (`guides`)

### G1. 안내서 생성·재조회

| 항목 | 내용 |
|---|---|
| API 이름 | 맞춤 복약·생활 안내서 |
| 설명 | 같은 조건의 완성본이 있으면 바로 돌려주고, 없으면 Claude로 새로 만듦 |
| 엔드포인트 | `/api/v1/documents/{document_id}/guides` |
| 메서드 | POST |
| 인증 필요 여부 | Y |
| DB | `guides`, `evidence_citations`, `kb_chunks`(`fn_kb_search`), `pipeline_metrics` |

요청 본문은 없습니다. 서버가 `cache_key = sha256(확인된 약·용법 + 건강정보 + 진단명 + 자료 기준일)`를 계산합니다.

**응답 200** (이미 있음, MED-008)

```json
{ "guide_id": "c2d1…", "status": "READY", "cached": true }
```

**응답 202** (새로 만드는 중 → G2를 폴링)

```json
{ "guide_id": "c2d1…", "status": "GENERATING", "cached": false }
```

서버 처리 순서는 이렇습니다.

1. 처방 약 원문과 `drug_warnings`를 정확 조회하고, 생활 수칙 문단을 벡터 검색합니다(12/10부터).
2. 이름·주민번호·병원 등록번호·전화번호를 가리고 병원명을 뺍니다. 가린 건수는 `pii_mask_counts`에 남깁니다(SYS-005).
3. Claude Haiku(개발)/Sonnet(시연)이 근거 번호를 단 문장으로만 작성합니다.
4. 근거 없는 문장과 단정·지시 표현을 제거합니다(SAF-001).

**오류**: 409 `ITEMS_NOT_CONFIRMED`, 429 `LLM_DAILY_LIMIT`, 503 `LLM_UNAVAILABLE`

### G2. 안내서 조회

| 항목 | 내용 |
|---|---|
| 엔드포인트 | `/api/v1/guides/{guide_id}` |
| 메서드 | GET |
| 인증 필요 여부 | Y |

**응답 200 주요 필드**

| 필드 | 설명 |
|---|---|
| `status` | `GENERATING` / `READY` / `STALE` / `FAILED` |
| `ai_generated` | 항상 true → 화면이 "AI 작성" 표시 (SAF-004) |
| `emergency_notice` / `disclaimer` | 고정 문구 (SAF-002 / SAF-001) |
| `sections.how_to_take[]`, `life_rules[]`, `ask_professional[]` | `{text, refs[]}` |
| `citations[]` | `ref_no`, `source_kind`, `source_title`, `quoted_text`, `base_date`, `source_url` |
| `export_label` | 복사·저장·PDF 맨 위에 넣을 문구 (인공지능기본법 제31조 제2항) |
| `is_stale` | 처방 수정이나 자료 갱신으로 다시 만들어야 하면 true |

```json
{ "guide_id": "c2d1…", "status": "READY", "ai_generated": true, "created_at": "2026-11-30T14:02:00+09:00",
  "llm_model": "claude-haiku-…", "prompt_version": "guide-v1",
  "emergency_notice": "숨쉬기 힘들거나 …", "disclaimer": "이 내용은 …",
  "sections": { "how_to_take": [ {"text": "와파린정: 하루 1번, 한 번에 1정, 아침 식사 30분 뒤", "refs": [1]} ],
                "life_rules": [ {"text": "국과 찌개는 국물을 줄이고, 짜게 먹지 않도록 해요.", "refs": [3]} ],
                "ask_professional": [ {"text": "와파린과 쎄레브렉스를 함께 먹어도 되는지 확인해 주세요.", "refs": [4]} ] },
  "citations": [ { "ref_no": 1, "source_kind": "MEDICINE_TEXT", "source_title": "식약처 의약품 제품 허가정보 – 와파린정2밀리그램",
                   "quoted_text": "…", "base_date": "2026-11-20", "source_url": null } ],
  "export_label": "[안심약국 · AI 작성] 이 내용은 생성형 AI가 공식 자료를 바탕으로 작성한 참고 정보입니다.",
  "feedback": { "my_rating": null }, "is_stale": false }
```

### G3. 좋아요·별로예요

| 항목 | 내용 |
|---|---|
| 엔드포인트 | `/api/v1/guides/{guide_id}/feedback` |
| 메서드 | POST (같은 사람이 다시 보내면 덮어씀) |
| 인증 필요 여부 | Y |
| DB | `guide_feedback` |

**요청**: `{ "rating": 1 }` (1 좋아요 / -1 별로예요, `comment` 선택) / **응답 200**: `{ "rating": 1 }`

### G4. 다시 만들기

| 항목 | 내용 |
|---|---|
| 엔드포인트 | `/api/v1/guides/{guide_id}/regenerate` |
| 메서드 | POST |
| 인증 필요 여부 | Y |

기존 안내서는 `STALE`이 되고, 새 안내서의 `regenerated_from`에 기존 ID가 들어갑니다.
**응답 202**: `{ "guide_id": "새 UUID", "status": "GENERATING", "regenerated_from": "c2d1…" }`

### G5. 복약 시간표

| 항목 | 내용 |
|---|---|
| 엔드포인트 | `/api/v1/guides/{guide_id}/schedule` |
| 메서드 | GET |
| 인증 필요 여부 | Y |
| DB | `medication_schedules` (없거나 약 정보가 바뀌었으면 규칙으로 다시 만든 뒤 응답) |

시간표는 AI를 쓰지 않고 처방 원문만 칸에 옮깁니다(하루 1번 → 아침, 2번 → 아침·저녁, 3번 → 아침·점심·저녁, "취침" → 자기 전).

**응답 200**

```json
{ "period": { "start_date": "2026-11-26", "end_date": "2026-12-02" },
  "slots": { "MORNING": [ { "schedule_id": 1, "item_id": 101, "drug_name": "와파린정2밀리그램", "dose_label": "1정",
                            "meal_relation": "AFTER_MEAL", "offset_minutes": 30, "source_text": "식후 30분" } ],
             "LUNCH": [], "DINNER": [ … ], "BEDTIME": [ … ], "AS_NEEDED": [] },
  "unscheduled": [ { "item_id": 104, "drug_name": "…", "reason": "복용 표시 없음" } ],
  "life_rules": [ { "text": "…", "refs": [3], "ai_generated": true } ],
  "citations": [ … ] }
```

### G6. 안내서 신고

| 항목 | 내용 |
|---|---|
| 엔드포인트 | `/api/v1/guides/{guide_id}/reports` |
| 메서드 | POST |
| 인증 필요 여부 | Y |
| DB | `ai_output_reports` |

**요청 Body**

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `reason_code` | string | Y | `WRONG_INFO` 내용이 틀림 / `UNSAFE_ADVICE` 위험한 권유 / `PRIVACY_EXPOSURE` 개인정보 노출 / `NO_SOURCE` 근거와 다름 / `OTHER` |
| `detail` | string | N | 500자 이내. 저장 전 식별정보 가림 |

**응답 201**: `{ "report_id": 17, "status": "RECEIVED" }`

---

## 6. 챗봇 (`chat`)

### C1. 대화방 만들기

| 항목 | 내용 |
|---|---|
| 엔드포인트 | `/api/v1/chat/sessions` |
| 메서드 | POST |
| 인증 필요 여부 | Y |
| DB | `chat_sessions`, `chat_preset_questions` |

**요청**: `{ "document_id": "8f0c…", "guide_id": "c2d1…" }` (`guide_id` 선택)

**응답 201**

```json
{ "session_id": "7a9e…",
  "ai_notice": "이 상담은 생성형 AI(Claude)가 11-26 처방 약과 등록하신 건강정보를 기준으로, 공식 자료 안에서 답해 드려요.",
  "context": { "items": [{"item_seq": "200000003", "name": "와파린정2밀리그램"}],
               "profile_flags": {"pregnancy_status": "NONE", "age_band": "60대", "is_65_or_over": true, "chronic_conditions": ["고혈압"]},
               "diagnoses": ["고혈압"] },
  "presets": [ {"preset_code": "GEN-HOWTO", "category": "GENERAL", "question_text": "이 약은 언제, 어떻게 먹어야 하나요?"},
               {"preset_code": "BND-STOP", "category": "BOUNDARY", "question_text": "속이 쓰린데 약을 임의로 끊거나 반만 먹어도 되나요?"} ],
  "situations": [ {"preset_code": "SIT-OTHERHOSP", "question_text": "다른 병원 약도 먹고 있어요"} ] }
```

`context`에는 이름·병원명이 들어가지 않습니다. 추천 질문은 처방 약의 주의 표시(음주·졸음), 임신·수유 여부, 진단명 유무에 맞춰 규칙으로 고릅니다.

### C2. 대화 목록

| 항목 | 내용 |
|---|---|
| 엔드포인트 | `/api/v1/chat/sessions/{session_id}/messages?limit=30&before=<message_id>` |
| 메서드 | GET |
| 인증 필요 여부 | Y |

**응답 200**: `{ "messages": [C3 응답의 메시지 형식, 오래된 순], "summary": "…", "next_before": 480 }`

### C3. 질문 보내기

| 항목 | 내용 |
|---|---|
| API 이름 | 근거 기반 복약 질의응답 |
| 엔드포인트 | `/api/v1/chat/sessions/{session_id}/messages` |
| 메서드 | POST |
| 인증 필요 여부 | Y |
| DB | `chat_messages`, `evidence_citations`, `kb_chunks` |

**요청 Body**

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `input_mode` | string | Y | `PRESET`(버튼) / `FREE_TEXT`(직접 입력, 12/9부터) |
| `preset_code` | string | PRESET일 때 | 예: `GEN-ALCOHOL` |
| `content` | string | FREE_TEXT일 때 | 500자 이내. 저장 전 식별정보 가림 |

**응답 200**

| 필드 | 설명 |
|---|---|
| `assistant.answer_status` | `ANSWERED` / `NO_EVIDENCE` / `REFUSED` / `EMERGENCY` / `ERROR` |
| `assistant.safety_label` | `SAFE` / `BOUNDARY` / `EMERGENCY` |
| `assistant.ai_generated` | Claude가 쓴 답이면 true. 고정 문구로 된 거절·응급 카드는 false |
| `assistant.citations[]` | G2와 같은 형식 |
| `assistant.follow_up_presets[]` | 이어서 물어볼 버튼 |
| `assistant.disclaimer` | 모든 답변 하단 고정 문구 |

```json
{ "user_message_id": 501,
  "assistant": { "message_id": 502, "answer_status": "ANSWERED", "safety_label": "SAFE", "ai_generated": true,
                 "content": "와파린정 허가정보의 '일상생활 주의'에 음주에 관한 문구가 있어요. … [1]",
                 "citations": [ {"ref_no": 1, "source_kind": "DRUG_WARNING", "source_title": "식약처 의약품 제품 허가정보 – 와파린정2밀리그램",
                                 "quoted_text": "…", "base_date": "2026-11-20"} ],
                 "follow_up_presets": ["GEN-DROWSY"], "disclaimer": "이 내용은 …" } }
```

경계 질문이면 Claude를 부르지 않고 바로 거절합니다.

```json
{ "user_message_id": 503,
  "assistant": { "message_id": 504, "answer_status": "REFUSED", "safety_label": "BOUNDARY", "ai_generated": false,
                 "content": "약을 끊거나 양·시간을 바꾸는 일은 여기서 답할 수 없어요. 처방한 의사나 약사와 꼭 상의하세요.",
                 "citations": [], "follow_up_presets": ["SIT-STOMACH"] } }
```

처리 순서는 다음과 같습니다(CHT-002·003).

1. 식별정보를 가린 뒤 저장합니다.
2. 1차로 규칙(끊기·줄이기·두 배·대체 약·시간 변경·진단 요청)을 검사해, 걸리면 바로 거절합니다.
3. 2차로 Haiku가 `SAFE`/`BOUNDARY`/`EMERGENCY`를 분류합니다.
4. `SAFE`이면 근거를 검색해 답합니다. 근거가 없으면 `NO_EVIDENCE` 고정 문구로 답합니다.
5. 메시지가 10개를 넘으면 앞 대화를 요약합니다.

**오류**: 400 `VALIDATION_ERROR`, 429 `LLM_DAILY_LIMIT`, 503 `LLM_UNAVAILABLE`

### C4. 방문 전 질문 만들기

| 항목 | 내용 |
|---|---|
| 엔드포인트 | `/api/v1/chat/sessions/{session_id}/visit-questions` |
| 메서드 | POST |
| 인증 필요 여부 | Y |

**요청**: `{ "situation_code": "SIT-OTHERHOSP" }`

**응답 200**

```json
{ "message_id": 510, "ai_generated": true,
  "visit_questions": [ "다른 병원에서 받은 혈압약도 먹고 있는데 지금 약과 함께 먹어도 괜찮은지 확인해 주세요.",
                       "와파린을 먹는 동안 피해야 할 약이나 음식이 있는지 알려 주세요." ],
  "export_label": "[안심약국 · AI 작성] 이 내용은 생성형 AI가 공식 자료를 바탕으로 작성한 참고 정보입니다.",
  "disclaimer": "이 내용은 …" }
```

질문은 3~5개이며, "~하세요"처럼 답을 주는 문장은 서버가 제거합니다(CHT-004). 화면에서 [복사]·[저장]할 때 `export_label`을 맨 위에 붙입니다.

### C5. 대화방 삭제

| 항목 | 내용 |
|---|---|
| 엔드포인트 | `/api/v1/chat/sessions/{session_id}` |
| 메서드 | DELETE |
| 인증 필요 여부 | Y |

메시지·근거·신고가 함께 삭제됩니다. **응답 204**

### C6. 답변 신고

| 항목 | 내용 |
|---|---|
| 엔드포인트 | `/api/v1/chat/messages/{message_id}/reports` |
| 메서드 | POST |
| 인증 필요 여부 | Y |

요청·응답은 G6과 같습니다. 본인 대화방의 `ASSISTANT` 메시지만 신고할 수 있습니다.

---

## 7. 시스템 (`system`)

### S1. 자료 기준일

| 항목 | 내용 |
|---|---|
| 엔드포인트 | `/api/v1/data-versions` |
| 메서드 | GET |
| 인증 필요 여부 | N |
| DB | `data_versions WHERE is_current` |

**응답 200**

```json
[ { "source_code": "MFDS_PERMIT", "source_name": "의약품 제품 허가정보", "provider": "식품의약품안전처",
    "base_date": "2026-11-20", "base_label": null, "verified_at": "2026-11-23T00:00:00+09:00" },
  { "source_code": "MFDS_DUR", "source_name": "DUR 성분단위 정보", "provider": "식품의약품안전처",
    "base_date": null, "base_label": "2026.6 고시", "verified_at": null } ]
```

### S2. 서버 상태

| 항목 | 내용 |
|---|---|
| 엔드포인트 | `/api/v1/health` |
| 메서드 | GET |
| 인증 필요 여부 | N |

**응답 200**: `{ "status": "ok", "db": "ok", "version": "v0.1" }`. docker compose의 healthcheck에 씁니다.

---

---

## 8. 261125 변경 사항 (각 절보다 우선)

> 근거: `docs/review/decision_log_261125.md`. 괄호 안은 결정·지적 번호.

### 8-1. 공통

- **화면 용어**: 사용자에게 보이는 `message`·고정 문구에는 "DUR" 대신 "나에게 맞춘 의약품 정보", "식약처 금기·주의 정보"를 쓰고, 출처 줄에만 "식약처 고시 의약품 적정사용(DUR) 정보"를 씁니다. "공식 자료"처럼 뭉뚱그리지 않고 기관·자료명을 밝힙니다 (D-21, D-23).
- **LLM 입력의 나이**: 정확한 나이 대신 `age_band`(예: 60대)와 `is_65_or_over`만 보냅니다. 정확한 나이 판단은 DB에서만 합니다 (PR-07).
- **LLM 전송 전 가림 대상**: 환자 이름, 주민등록번호, 전화번호, **주소**, 병원 환자 등록번호, 교부번호, QR·바코드 문자열, 의료기관명·주소·전화, 의사 이름·면허번호, 약국명. 가린 건수는 `pii_mask_counts`에 기록 (F-06, PR-02, D-21 ⑦).
- **AI 안내를 받지 않기로 한 약**(`ai_excluded=true`)은 어떤 LLM 호출에도 넣지 않습니다. 규칙 기반 처리(금기·주의 확인, 허가 정보 원문, 시간표)에는 계속 포함합니다 (D-14).
- **문서 경계**: 안내서와 대화는 문서 하나의 정보만 씁니다. 문서 경계를 넘는 것은 금기·주의 확인(D7)의 처방 간 병용금기뿐입니다 (D-04, D-05).

### 8-2. U2 동의 철회 (마이페이지 '동의 관리')

- 업로드 때의 동의는 D1이 기록하므로 U2는 **철회 전용**으로 씁니다.
- `{"consent_type": "HEALTH_SENSITIVE", "action": "WITHDRAW"}` → 확인 창 후 호출. 처리: `fn_withdraw_health_consent` — 사람 단위 WITHDRAW 기록 → 모든 문서 `fn_delete_document` → 문서와 연결되지 않은 대화방 삭제 → `user_profiles` 삭제 (D-02, P-10). 응답에 지운 건수 `{"deleted": {"documents": 2, "guides": 2, "chat_sessions": 2}}`.
- 철회 후에도 회원 정보와 동의 기록은 남고, 업로드·안내서·대화는 403 `HEALTH_CONSENT_REQUIRED` (D-13 ④).

### 8-3. D1 문서 업로드 (건별 동의)

- 요청에서 `consent_log_id`를 **삭제**하고 `agree_document_processing`, `agree_health_sensitive`(둘 다 `true` 필수)를 받습니다. 하나라도 빠지면 403 `CONSENT_REQUIRED` (D-02, D-19).
- 서버는 `document_id`(UUID)를 먼저 만들고, 한 트랜잭션에서 동의 2행(`consent_logs`, `scope=DOCUMENT`, `document_id` 연결)과 `documents` 행을 만듭니다. 업로드 트리거는 해당 문서의 동의 행과 `fn_has_active_consent`를 함께 확인 (S-01).
- 처리 순서: 형식·크기·쪽수 검사 → 저장 → 글자 읽기(사진 OCR / PDF 직접 추출) → **가림 후** `ocr_raw` 저장 → **가림 후** Haiku 구조화(DOC-003) → 약 연결 (F-06, PR-01, PR-02).
- 진료기록 PDF(`A_PDF_PARSE`)는 OCR 신뢰도가 없으므로 `NEEDS_RETAKE` 판정에서 제외 (P-06).
- 선택 기능: 처리 중 [취소] → `DELETE /documents/{id}`와 같은 삭제, LLM 호출 전이면 전송 없음 (D-02).

### 8-4. D3 추출 약 목록 / D4 약 한 줄 수정 / D9 문서 수정

- D3 각 줄에 `confirmed_by`(`AUTO`|`USER`|null) 추가. 보험코드 일치(`EDI_EXACT`)이고 점수 0.7 이상이면 서버가 `user_confirmed=true, confirmed_by=AUTO`로 미리 표시. 화면 배지는 "보험코드로 약 이름 확인" (W-01, D-12).
- D4에 `ai_excluded`(boolean) 수정 허용: 약별 "AI 안내 받지 않기" (D-14). `include_in_analysis`는 진료기록 PDF 과거 약 선택용으로 그대로 둠.
- **D9 신설** `PATCH /documents/{document_id}`: `diagnoses`, `visit_date` 수정(F-04), `ai_excluded: true`면 그 문서의 모든 약 `ai_excluded=true`(기록 관리의 [AI 안내만 받지 않기], D-17). 진단명이 바뀌면 안내서에 "다시 만들기 필요" 표시.
- (선택) 확인 완료 뒤에도 D4·D5 허용, 수정 시 금기·주의 다시 계산 (W-11).

### 8-5. D6 확인 완료

- 확인 완료 시 `fn_purge_original` 호출: **원본 파일 즉시 삭제, `ocr_raw` 비움**. 확인하지 않으면 읽기 완료 24시간 뒤 예약 작업이 같은 처리 (D-03, PR-01).
- 2단계 미리보기 자리 문구: 확인 전 24시간 경과 "원본은 개인 민감정보 보호를 위해 삭제되었어요. 가지고 계신 종이 처방전이나 약봉투와 비교하며 확인해 주세요. 잘 맞지 않으면 다시 올려 주세요." / 확인 후 "원본은 확인을 마친 뒤 개인 민감정보 보호를 위해 삭제했어요." (D-03)

### 8-6. D7 나에게 맞춘 의약품 정보 · 의약품 허가 정보 · 확인할 내용

- 열 때마다 `fn_refresh_dur_alerts` 재계산 (D-05).
- **1차 계산 유형**: 병용금기, 연령금기, 임부금기, 노인주의 4종(D-07, DUR 유형별 건수 확인 후 확정). 나이 판단은 서버에서 `age_limit` 원문을 해석, 해석 불가는 `CHECK_NEEDED` (F-03, S-02). 나이 표기는 "68세(출생연도 기준)" (P-02).
- **처방 간 병용금기**: 같은 사용자가 확인을 마친 다른 문서 중 복용 기간(진료·조제일 ~ +총 일수)이 겹치는 약 포함, `trigger_reason: PAIR_ACROSS_DOCUMENTS`. 일수 없는 약은 최근 30일 처방만, `period_check_needed: true` (D-05).
- 응답 구조(화면 세 영역, D-24): `personal_info`(나에게 맞춘 의약품 정보: 금기·주의 목록, 출처 `source_label: "식약처 고시 의약품 적정사용(DUR) 정보"`, 기준일), `permit_info`(의약품 허가 정보: 약별 6유형 원문, 출처 "식약처 의약품 제품 허가정보"), `coverage_notices`(고정 안내 문구 배열), `coverage_questions`(확인할 내용).
- `coverage_notices` 고정 문구: "올려 주신 처방의 약끼리만 확인했어요. 다른 병원 약이나 사서 드시는 약이 있으면 약사에게 함께 보여주세요." / "영양제·건강기능식품은 식약처 금기·주의 정보에 없어서 여기서 살펴볼 수 없어요." / "병원·약국에서 처방·조제할 때 하는 건강보험심사평가원의 실시간 점검과는 달라요. 그동안 처방받은 약 기록 전체를 보지 않고, 올려 주신 처방만 살펴봐요." / 지운 처방이 있으면 "지운 처방의 약은 확인에 포함되지 않아요." (D-06, D-13, D-21, D-23)
- 결과 0건 문구: "올려 주신 약끼리는 식약처 금기·주의 정보에서 확인된 항목이 없어요. 함께 먹어도 안전하다는 뜻은 아니에요." (W-03)
- `coverage_questions`: `[{"key","text","reason","gap_type"}]`. `gap_type` = `NOT_UPLOADED`·`WITHDRAWN`·`DURATION_UNKNOWN`·`TIME_UNSPECIFIED`·`NO_OFFICIAL_DATA`·`DRUG_NOT_MATCHED`·`DUR_UNLINKED`(확인 못한 내용) · `EXCLUDED_BY_USER`·`PROFESSIONAL_JUDGMENT`(안내하지 못하는 내용) · `PAIR_FOUND`. 규칙 기반(LLM 미사용). AI 안내를 받지 않기로 한 약은 이름 대신 "AI 안내를 받지 않기로 하신 약"으로 (D-15, D-16).
- 쿼리 `?other_meds=yes|no|later`: 첫 확인 때 짧은 질문의 답. **저장하지 않고** 이번 응답의 질문 생성에만 사용 (D-16).
- (선택) 고위험 약 표시 `high_risk: true`(분류번호 또는 진단명 C코드) → 3단계 맨 위 고정 안내 (D-10, 컬럼 확인 후).

### 8-7. D8 기록 지우기 (기록 관리)

- 화면은 처방 카드의 [기록 관리] → 관리 화면에서 [AI 안내만 받지 않기](D9) / [기록 지우기](D8) / [그대로 두기] (D-17, D-19, D-21).
- 처리: `fn_delete_document` 한 번으로 그 문서 동의의 WITHDRAW 기록(`scope=DOCUMENT`) →(원본, 문서, 처방 항목, 안내서·근거, 시간표, 금기·주의 결과, 대화방, 신고, 승인 전 오타 후보) → `deletion_logs`(HMAC 해시·건수) (D-11, D-20, P-09).
- 응답: `{"deleted": {"items": 2, "guides": 1, "chat_sessions": 1}}` — 확인 창의 "지워지는 것" 건수와 같은 값.

### 8-8. G1 AI가 쉽게 풀어 쓴 복약 안내

- 건강 민감정보 동의 확인 → 없으면 403 `HEALTH_CONSENT_REQUIRED` (F-01).
- 입력: 그 문서의 `include_in_analysis=true`이고 `ai_excluded=false`인 약만, 진단명은 그 문서 것만, 건강정보는 `user_profiles` (D-04, D-14).
- 프롬프트·출력 검사(SAF-001) 금지: 처방 원문에 없는 시간대 표현("아침" 등, D-01), 약의 용도를 진단과 엮은 추정("이 약은 ○○ 때문에", D-12), 증상 원인 판단 양방향("~때문이에요/~때문은 아니에요/~의 부작용이에요", D-18), 단정 표현. `refs` 번호가 `citations`에 없으면 그 문장 제거 (F-02).
- 허가 효능을 보여줄 때 고정 문구 `OFF_LABEL_NOTE`: "의사는 환자 상태에 따라 허가 내용과 다른 이유로 처방하기도 해요. 처방 이유가 궁금하면 처방한 의사나 조제한 약사에게 물어보세요. 처방받은 약은 임의로 끊지 말고 먼저 상의하세요." (D-12)
- (선택) 고위험 약은 일반 생활 수칙을 만들지 않고 허가 원문·의료진 상담 안내만 (D-10).

### 8-9. G5 복약 시간표

- `slot`에 `DAILY_UNSPECIFIED` 추가: 시간 표시 없는 하루 1번 약은 "하루 1번 · 시간은 처방 안내대로" 칸 (D-01, S-03).
- 배치 규칙은 위에서부터 먼저 맞는 하나: 복용 시점 글자(취침·자기 전 등) → 횟수(2번 아침·저녁, 3번 아침·점심·저녁, 4번 + 취침 전) → 1번은 `DAILY_UNSPECIFIED`.
- 각 줄에 `slot_source`(`PRESCRIPTION`|`USER`). (선택) `PATCH /guides/{guide_id}/schedule/{schedule_id}`로 사용자가 약사에게 들은 시간을 골라 이동, "시간: 직접 선택" 표시.

### 8-10. C1 대화방 / C3 질문 보내기 / C4 방문 전 질문

- C1: 건강 민감정보 동의 확인(F-01). 같은 문서로 다시 요청하면 기존 대화방 반환(P-07). `context`에서 AI 안내를 받지 않기로 한 약은 제외하고 `excluded_count`만 (D-14).
- C3 처리 순서: ① 가림 ② **응급 키워드 규칙**(처방·동의·철회와 무관하게 항상, 맞으면 고정 응급 카드 `answer_status: EMERGENCY`, LLM 미호출) ③ 경계 규칙(끊기·양 조절, **처방 이유·적정성 질문** → `BOUNDARY`) ④ Haiku 2차 분류 ⑤ 답변 생성 ⑥ **출력 검사**(G1과 같은 금지 목록, refs↔citations 대조) (P-01, D-12, D-18, F-02). Claude 장애(503) 때도 ②는 동작.
- 증상 질문의 답에는 항상 "올려 주신 약 말고 다른 약이나 영양제도 원인일 수 있어요"를 붙이고, 응답에 `added_question`(확인할 내용에 추가된 질문)을 넣음 (D-16, D-18).
- AI 안내를 받지 않기로 한 약을 물으면: "이 약은 AI 안내에서 빼 두셨어요. 식약처 허가 정보 원문은 3단계에서 볼 수 있어요." (D-14)
- C4 상황 버튼 프리셋: `SIT-OTHERDRUG`(다른 약도 먹고 있어요 / 다른 병원 약 · 약국에서 산 약 · 영양제), `SIT-DROWSY`(졸리거나 어지러워요), `SIT-PREG`은 임신·수유 정보가 있을 때만 (D-09, S-04).
- 첫 메시지 AI 고지: "이 상담은 생성형 AI(Claude)가 올려 주신 처방과 건강정보를 기준으로, 식약처 의약품 허가정보·금기·주의 정보와 질병관리청 국가건강정보포털 자료 안에서만 답해 드려요." (D-21 ⑩)

### 8-11. C6·G6 신고

- 대상은 AI가 쓴 영역(안내서·생활 수칙·답변)만. 사유에 "약 이름·복용량이 처방과 달라요"는 넣지 않음(그 경우는 약 정보 고치기). 화면 버튼 문구 "틀린 내용 알리기" (W-11).

### 8-12. 2차 메모

- 내 약 목록(사람 중심), 「내가 먹는 약! 한눈에」 투약이력 읽기와 동일성분·효능군 중복(D-22), 철회 시 "지금 먹는 약에 남기기"(D-13 ⑦), 약사에게 보여주기 화면, 영양제 정보.

## 부록. 2차(선택) 범위

| 메서드 | 경로 | 요구사항 |
|---|---|---|
| GET | `/api/v1/auth/{provider}/login` | USR-007 소셜 로그인 시작 (`kakao`·`naver`·`google`) |
| GET | `/api/v1/auth/{provider}/callback` | USR-007 콜백 → A2와 같은 토큰 발급 |
