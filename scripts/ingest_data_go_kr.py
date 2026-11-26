#!/usr/bin/env python3
"""
공공데이터포털(data.go.kr) 4대 의약품 API 전수 데이터 수집 및 PostgreSQL Upsert 적재 스크립트.

적재 순서:
  1. 의약품 제품 허가정보 (마스터 기준)
  2. e약은요 의약품 개요정보
  3. 의약품 낱알식별 정보 (이미지 URL 포함)
  4. DUR 품목 정보

주요 기능:
  - ITEM_SEQ(품목기준코드) 기준 Upsert (ON CONFLICT (item_seq) DO UPDATE)
  - XML/HTML 태그(<DOC>, <SECTION> 등) 순수 텍스트 정제 및 엔티티 언이스케이프
  - 페이지네이션(numOfRows=100) 및 네트워크 에러 지수 백오프 재시도(Retry)
  - 서버 부하 방지 딜레이(기본 0.1초)
  - tqdm 실시간 진행률 표시
"""

import argparse
import asyncio
import html
import math
import os
import re
import sys
from pathlib import Path
from typing import Any

import asyncpg
import httpx
from dotenv import dotenv_values
from tqdm import tqdm

# 프로젝트 루트 및 .env 설정 로드
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
env_vars = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}


def get_env(key: str, default: str = "") -> str:
    return os.getenv(key) or env_vars.get(key) or default


# API 엔드포인트 상수 정의
API_CONFIGS = {
    1: {
        "name": "① 의약품 제품 허가정보 (마스터)",
        "url": "https://apis.data.go.kr/1471000/DrugPrdtPrmsnInfoService08/getDrugPrdtPrmsnInq08",
        "key_field": "ITEM_SEQ",
    },
    2: {
        "name": "② e약은요 의약품 개요정보",
        "url": "http://apis.data.go.kr/1471000/DrbEasyDrugInfoService/getDrbEasyDrugList",
        "key_field": "itemSeq",
    },
    3: {
        "name": "③ 의약품 낱알식별 정보",
        "url": "http://apis.data.go.kr/1471000/MdcinGrnIdntfcInfoService03/getMdcinGrnIdntfcInfoList03",
        "key_field": "ITEM_SEQ",
    },
    4: {
        "name": "④ DUR 품목 정보",
        "url": "http://apis.data.go.kr/1471000/DURPrdlstInfoService03/getDurPrdlstInfoList03",
        "key_field": "ITEM_SEQ",
    },
}

CREATE_TABLE_SQL = """
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS medicines (
    item_seq VARCHAR(100) PRIMARY KEY,

    -- 1. 허가정보 (마스터)
    item_name TEXT,
    entp_name TEXT,
    item_eng_name TEXT,
    entp_eng_name TEXT,
    entp_seq TEXT,
    entp_no TEXT,
    item_permit_date TEXT,
    induty TEXT,
    prdlst_stdr_code TEXT,
    spclty_pblc TEXT,
    prduct_type TEXT,
    prduct_prmisn_no TEXT,
    item_ingr_name TEXT,
    item_ingr_cnt TEXT,
    big_prdt_img_url TEXT,
    permit_kind_code TEXT,
    cancel_date TEXT,
    cancel_name TEXT,
    edi_code TEXT,
    bizrno TEXT,

    -- 2. e약은요
    efcy_qesitm TEXT,
    use_method_qesitm TEXT,
    atpn_warn_qesitm TEXT,
    atpn_qesitm TEXT,
    intrc_qesitm TEXT,
    se_qesitm TEXT,
    deposit_method_qesitm TEXT,
    open_de TEXT,
    update_de TEXT,
    easy_drug_img_url TEXT,

    -- 3. 낱알식별정보
    item_image TEXT,
    chart TEXT,
    print_front TEXT,
    print_back TEXT,
    drug_shape TEXT,
    color_class1 TEXT,
    color_class2 TEXT,
    line_front TEXT,
    line_back TEXT,
    leng_long TEXT,
    leng_short TEXT,
    thick TEXT,
    img_regist_ts TEXT,
    class_no TEXT,
    class_name TEXT,
    etc_otc_name TEXT,
    form_code_name TEXT,
    mark_code_front_anal TEXT,
    mark_code_back_anal TEXT,
    mark_code_front_img TEXT,
    mark_code_back_img TEXT,
    change_date TEXT,

    -- 4. DUR품목정보
    bar_code TEXT,
    material_name TEXT,
    ee_doc_id TEXT,
    ud_doc_id TEXT,
    nb_doc_id TEXT,
    insert_file TEXT,
    storage_method TEXT,
    valid_term TEXT,
    reexam_target TEXT,
    reexam_date TEXT,
    pack_unit TEXT,
    type_code TEXT,
    type_name TEXT,

    -- 메타데이터
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_medicines_item_name_trgm ON medicines USING gin (item_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_medicines_entp_name_trgm ON medicines USING gin (entp_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_medicines_edi_code ON medicines (edi_code);
CREATE INDEX IF NOT EXISTS idx_medicines_bar_code ON medicines (bar_code);
"""


def clean_text(val: Any) -> str | None:
    """XML/HTML 태그 및 특수 엔티티를 정제하여 순수 텍스트로 변환."""
    if val is None:
        return None
    val_str = str(val).strip()
    if not val_str or val_str.lower() in ("none", "null", "undefined"):
        return None

    # HTML/XML 엔티티 변환 (&amp; -> &, &lt; -> < 등)
    text = html.unescape(val_str)

    # <SECTION title="효능효과"> -> \n[효능효과]\n
    text = re.sub(
        r'<(?:SECTION|ARTICLE)\s+[^>]*title=["\']([^"\']+)["\'][^>]*>',
        r"\n[\1]\n",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"<(?:SECTION|ARTICLE)\s*>", "\n", text, flags=re.IGNORECASE)

    # <p>, <br>, <tr>, <li> -> 줄바꿈 변환
    text = re.sub(r"<(?:br\s*/?|/p|/div|/tr|/li)>", "\n", text, flags=re.IGNORECASE)

    # 잔여 XML/HTML 태그 제거 (<DOC>, </DOC>, <PARAGRAPH>, <span> 등)
    text = re.sub(r"</?[a-zA-Z][^>]*>", " ", text)

    # 탭 및 다중 공백 정규화
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    # 연속 빈 줄 정규화
    text = re.sub(r"\n\s*\n", "\n\n", text)
    cleaned = text.strip()
    return cleaned if cleaned else None


def extract_items(data: dict) -> tuple[int, list[dict]]:
    """API JSON 응답에서 totalCount와 아이템 목록을 추출."""
    body = data.get("body", {})
    if not body:
        return 0, []
    total_count = int(body.get("totalCount", 0))
    raw_items = body.get("items")
    if not raw_items:
        return total_count, []
    if isinstance(raw_items, list):
        return total_count, raw_items
    if isinstance(raw_items, dict):
        if "item" in raw_items:
            inner = raw_items["item"]
            if isinstance(inner, list):
                return total_count, inner
            elif isinstance(inner, dict):
                return total_count, [inner]
        return total_count, [raw_items]
    return total_count, []


async def fetch_page_with_retry(
    client: httpx.AsyncClient,
    url: str,
    params: dict,
    max_retries: int = 5,
    backoff_factor: float = 1.5,
) -> dict:
    """네트워크 오류 및 일시적 서버 장애 시 지수 백오프로 재시도."""
    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = await client.get(url, params=params, timeout=20.0)
            if resp.status_code == 200:
                # 간혹 XML 에러 메시지가 200으로 반환되는 경우 체크
                if "SERVICE_KEY_IS_NOT_REGISTERED_ERROR" in resp.text:
                    raise ValueError("공공데이터포털 인증키 오류: SERVICE_KEY_IS_NOT_REGISTERED_ERROR")
                return resp.json()
            elif resp.status_code in (429, 500, 502, 503, 504):
                wait_time = backoff_factor**attempt
                await asyncio.sleep(wait_time)
                continue
            else:
                resp.raise_for_status()
        except Exception as e:
            last_exc = e
            if attempt == max_retries:
                break
            wait_time = backoff_factor**attempt
            await asyncio.sleep(wait_time)
    raise RuntimeError(f"API 요청 실패 ({url}, page={params.get('pageNo')}): {last_exc}")


# ---------------------------------------------------------------------------
# 1. 의약품 제품 허가정보 Upsert
# ---------------------------------------------------------------------------
UPSERT_PERMISSION_SQL = """
INSERT INTO medicines (
    item_seq, item_name, entp_name, item_eng_name, entp_eng_name, entp_seq, entp_no,
    item_permit_date, induty, prdlst_stdr_code, spclty_pblc, prduct_type, prduct_prmisn_no,
    item_ingr_name, item_ingr_cnt, big_prdt_img_url, permit_kind_code, cancel_date,
    cancel_name, edi_code, bizrno, updated_at
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21,
    CURRENT_TIMESTAMP
)
ON CONFLICT (item_seq) DO UPDATE SET
    item_name = EXCLUDED.item_name,
    entp_name = EXCLUDED.entp_name,
    item_eng_name = EXCLUDED.item_eng_name,
    entp_eng_name = EXCLUDED.entp_eng_name,
    entp_seq = EXCLUDED.entp_seq,
    entp_no = EXCLUDED.entp_no,
    item_permit_date = EXCLUDED.item_permit_date,
    induty = EXCLUDED.induty,
    prdlst_stdr_code = EXCLUDED.prdlst_stdr_code,
    spclty_pblc = EXCLUDED.spclty_pblc,
    prduct_type = EXCLUDED.prduct_type,
    prduct_prmisn_no = EXCLUDED.prduct_prmisn_no,
    item_ingr_name = EXCLUDED.item_ingr_name,
    item_ingr_cnt = EXCLUDED.item_ingr_cnt,
    big_prdt_img_url = EXCLUDED.big_prdt_img_url,
    permit_kind_code = EXCLUDED.permit_kind_code,
    cancel_date = EXCLUDED.cancel_date,
    cancel_name = EXCLUDED.cancel_name,
    edi_code = EXCLUDED.edi_code,
    bizrno = EXCLUDED.bizrno,
    updated_at = CURRENT_TIMESTAMP;
"""


async def upsert_permission_batch(pool: asyncpg.Pool, items: list[dict]):
    records = []
    for item in items:
        item_seq = clean_text(item.get("ITEM_SEQ"))
        if not item_seq:
            continue
        records.append(
            (
                item_seq,
                clean_text(item.get("ITEM_NAME")),
                clean_text(item.get("ENTP_NAME")),
                clean_text(item.get("ITEM_ENG_NAME")),
                clean_text(item.get("ENTP_ENG_NAME")),
                clean_text(item.get("ENTP_SEQ")),
                clean_text(item.get("ENTP_NO")),
                clean_text(item.get("ITEM_PERMIT_DATE")),
                clean_text(item.get("INDUTY")),
                clean_text(item.get("PRDLST_STDR_CODE")),
                clean_text(item.get("SPCLTY_PBLC")),
                clean_text(item.get("PRDUCT_TYPE")),
                clean_text(item.get("PRDUCT_PRMISN_NO")),
                clean_text(item.get("ITEM_INGR_NAME")),
                clean_text(item.get("ITEM_INGR_CNT")),
                clean_text(item.get("BIG_PRDT_IMG_URL")),
                clean_text(item.get("PERMIT_KIND_CODE")),
                clean_text(item.get("CANCEL_DATE")),
                clean_text(item.get("CANCEL_NAME")),
                clean_text(item.get("EDI_CODE")),
                clean_text(item.get("BIZRNO")),
            )
        )
    if records:
        async with pool.acquire() as conn:
            await conn.executemany(UPSERT_PERMISSION_SQL, records)


# ---------------------------------------------------------------------------
# 2. e약은요 의약품 개요정보 Upsert
# ---------------------------------------------------------------------------
UPSERT_EASY_SQL = """
INSERT INTO medicines (
    item_seq, item_name, entp_name, efcy_qesitm, use_method_qesitm,
    atpn_warn_qesitm, atpn_qesitm, intrc_qesitm, se_qesitm,
    deposit_method_qesitm, open_de, update_de, easy_drug_img_url, bizrno, updated_at
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14,
    CURRENT_TIMESTAMP
)
ON CONFLICT (item_seq) DO UPDATE SET
    item_name = COALESCE(medicines.item_name, EXCLUDED.item_name),
    entp_name = COALESCE(medicines.entp_name, EXCLUDED.entp_name),
    efcy_qesitm = EXCLUDED.efcy_qesitm,
    use_method_qesitm = EXCLUDED.use_method_qesitm,
    atpn_warn_qesitm = EXCLUDED.atpn_warn_qesitm,
    atpn_qesitm = EXCLUDED.atpn_qesitm,
    intrc_qesitm = EXCLUDED.intrc_qesitm,
    se_qesitm = EXCLUDED.se_qesitm,
    deposit_method_qesitm = EXCLUDED.deposit_method_qesitm,
    open_de = EXCLUDED.open_de,
    update_de = EXCLUDED.update_de,
    easy_drug_img_url = EXCLUDED.easy_drug_img_url,
    bizrno = COALESCE(medicines.bizrno, EXCLUDED.bizrno),
    updated_at = CURRENT_TIMESTAMP;
"""


async def upsert_easy_batch(pool: asyncpg.Pool, items: list[dict]):
    records = []
    for item in items:
        item_seq = clean_text(item.get("itemSeq") or item.get("ITEM_SEQ"))
        if not item_seq:
            continue
        records.append(
            (
                item_seq,
                clean_text(item.get("itemName") or item.get("ITEM_NAME")),
                clean_text(item.get("entpName") or item.get("ENTP_NAME")),
                clean_text(item.get("efcyQesitm")),
                clean_text(item.get("useMethodQesitm")),
                clean_text(item.get("atpnWarnQesitm")),
                clean_text(item.get("atpnQesitm")),
                clean_text(item.get("intrcQesitm")),
                clean_text(item.get("seQesitm")),
                clean_text(item.get("depositMethodQesitm")),
                clean_text(item.get("openDe")),
                clean_text(item.get("updateDe")),
                clean_text(item.get("itemImage")),
                clean_text(item.get("bizrno") or item.get("BIZRNO")),
            )
        )
    if records:
        async with pool.acquire() as conn:
            await conn.executemany(UPSERT_EASY_SQL, records)


# ---------------------------------------------------------------------------
# 3. 의약품 낱알식별 정보 Upsert
# ---------------------------------------------------------------------------
UPSERT_IDENTIFICATION_SQL = """
INSERT INTO medicines (
    item_seq, item_name, entp_seq, entp_name, chart, item_image,
    print_front, print_back, drug_shape, color_class1, color_class2,
    line_front, line_back, leng_long, leng_short, thick, img_regist_ts,
    class_no, class_name, etc_otc_name, item_permit_date, form_code_name,
    mark_code_front_anal, mark_code_back_anal, mark_code_front_img,
    mark_code_back_img, item_eng_name, change_date, edi_code, bizrno, updated_at
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16,
    $17, $18, $19, $20, $21, $22, $23, $24, $25, $26, $27, $28, $29, $30,
    CURRENT_TIMESTAMP
)
ON CONFLICT (item_seq) DO UPDATE SET
    item_name = COALESCE(medicines.item_name, EXCLUDED.item_name),
    entp_name = COALESCE(medicines.entp_name, EXCLUDED.entp_name),
    chart = COALESCE(EXCLUDED.chart, medicines.chart),
    item_image = EXCLUDED.item_image,
    print_front = EXCLUDED.print_front,
    print_back = EXCLUDED.print_back,
    drug_shape = EXCLUDED.drug_shape,
    color_class1 = EXCLUDED.color_class1,
    color_class2 = EXCLUDED.color_class2,
    line_front = EXCLUDED.line_front,
    line_back = EXCLUDED.line_back,
    leng_long = EXCLUDED.leng_long,
    leng_short = EXCLUDED.leng_short,
    thick = EXCLUDED.thick,
    img_regist_ts = EXCLUDED.img_regist_ts,
    class_no = EXCLUDED.class_no,
    class_name = EXCLUDED.class_name,
    etc_otc_name = COALESCE(medicines.spclty_pblc, EXCLUDED.etc_otc_name),
    form_code_name = EXCLUDED.form_code_name,
    mark_code_front_anal = EXCLUDED.mark_code_front_anal,
    mark_code_back_anal = EXCLUDED.mark_code_back_anal,
    mark_code_front_img = EXCLUDED.mark_code_front_img,
    mark_code_back_img = EXCLUDED.mark_code_back_img,
    change_date = EXCLUDED.change_date,
    edi_code = COALESCE(medicines.edi_code, EXCLUDED.edi_code),
    bizrno = COALESCE(medicines.bizrno, EXCLUDED.bizrno),
    updated_at = CURRENT_TIMESTAMP;
"""


async def upsert_identification_batch(pool: asyncpg.Pool, items: list[dict]):
    records = []
    for item in items:
        item_seq = clean_text(item.get("ITEM_SEQ") or item.get("itemSeq"))
        if not item_seq:
            continue
        records.append(
            (
                item_seq,
                clean_text(item.get("ITEM_NAME")),
                clean_text(item.get("ENTP_SEQ")),
                clean_text(item.get("ENTP_NAME")),
                clean_text(item.get("CHART")),
                clean_text(item.get("ITEM_IMAGE")),
                clean_text(item.get("PRINT_FRONT")),
                clean_text(item.get("PRINT_BACK")),
                clean_text(item.get("DRUG_SHAPE")),
                clean_text(item.get("COLOR_CLASS1")),
                clean_text(item.get("COLOR_CLASS2")),
                clean_text(item.get("LINE_FRONT")),
                clean_text(item.get("LINE_BACK")),
                clean_text(item.get("LENG_LONG")),
                clean_text(item.get("LENG_SHORT")),
                clean_text(item.get("THICK")),
                clean_text(item.get("IMG_REGIST_TS")),
                clean_text(item.get("CLASS_NO")),
                clean_text(item.get("CLASS_NAME")),
                clean_text(item.get("ETC_OTC_NAME")),
                clean_text(item.get("ITEM_PERMIT_DATE")),
                clean_text(item.get("FORM_CODE_NAME")),
                clean_text(item.get("MARK_CODE_FRONT_ANAL")),
                clean_text(item.get("MARK_CODE_BACK_ANAL")),
                clean_text(item.get("MARK_CODE_FRONT_IMG")),
                clean_text(item.get("MARK_CODE_BACK_IMG")),
                clean_text(item.get("ITEM_ENG_NAME")),
                clean_text(item.get("CHANGE_DATE")),
                clean_text(item.get("EDI_CODE")),
                clean_text(item.get("BIZRNO")),
            )
        )
    if records:
        async with pool.acquire() as conn:
            await conn.executemany(UPSERT_IDENTIFICATION_SQL, records)


# ---------------------------------------------------------------------------
# 4. DUR 품목 정보 Upsert
# ---------------------------------------------------------------------------
UPSERT_DUR_SQL = """
INSERT INTO medicines (
    item_seq, item_name, entp_name, item_permit_date, spclty_pblc, class_no,
    chart, bar_code, material_name, ee_doc_id, ud_doc_id, nb_doc_id,
    insert_file, storage_method, valid_term, reexam_target, reexam_date,
    pack_unit, edi_code, cancel_date, cancel_name, type_code, type_name,
    change_date, bizrno, updated_at
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16,
    $17, $18, $19, $20, $21, $22, $23, $24, $25,
    CURRENT_TIMESTAMP
)
ON CONFLICT (item_seq) DO UPDATE SET
    item_name = COALESCE(medicines.item_name, EXCLUDED.item_name),
    entp_name = COALESCE(medicines.entp_name, EXCLUDED.entp_name),
    chart = COALESCE(medicines.chart, EXCLUDED.chart),
    bar_code = EXCLUDED.bar_code,
    material_name = EXCLUDED.material_name,
    ee_doc_id = EXCLUDED.ee_doc_id,
    ud_doc_id = EXCLUDED.ud_doc_id,
    nb_doc_id = EXCLUDED.nb_doc_id,
    insert_file = EXCLUDED.insert_file,
    storage_method = EXCLUDED.storage_method,
    valid_term = EXCLUDED.valid_term,
    reexam_target = EXCLUDED.reexam_target,
    reexam_date = EXCLUDED.reexam_date,
    pack_unit = EXCLUDED.pack_unit,
    edi_code = COALESCE(medicines.edi_code, EXCLUDED.edi_code),
    cancel_date = COALESCE(medicines.cancel_date, EXCLUDED.cancel_date),
    cancel_name = COALESCE(medicines.cancel_name, EXCLUDED.cancel_name),
    type_code = EXCLUDED.type_code,
    type_name = EXCLUDED.type_name,
    change_date = COALESCE(medicines.change_date, EXCLUDED.change_date),
    bizrno = COALESCE(medicines.bizrno, EXCLUDED.bizrno),
    updated_at = CURRENT_TIMESTAMP;
"""


async def upsert_dur_batch(pool: asyncpg.Pool, items: list[dict]):
    records = []
    for item in items:
        item_seq = clean_text(item.get("ITEM_SEQ") or item.get("itemSeq"))
        if not item_seq:
            continue
        type_name = clean_text(item.get("TYPE_NAME  ") or item.get("TYPE_NAME"))
        records.append(
            (
                item_seq,
                clean_text(item.get("ITEM_NAME")),
                clean_text(item.get("ENTP_NAME")),
                clean_text(item.get("ITEM_PERMIT_DATE")),
                clean_text(item.get("ETC_OTC_CODE")),
                clean_text(item.get("CLASS_NO")),
                clean_text(item.get("CHART")),
                clean_text(item.get("BAR_CODE")),
                clean_text(item.get("MATERIAL_NAME")),
                clean_text(item.get("EE_DOC_ID")),
                clean_text(item.get("UD_DOC_ID")),
                clean_text(item.get("NB_DOC_ID")),
                clean_text(item.get("INSERT_FILE")),
                clean_text(item.get("STORAGE_METHOD")),
                clean_text(item.get("VALID_TERM")),
                clean_text(item.get("REEXAM_TARGET")),
                clean_text(item.get("REEXAM_DATE")),
                clean_text(item.get("PACK_UNIT")),
                clean_text(item.get("EDI_CODE")),
                clean_text(item.get("CANCEL_DATE")),
                clean_text(item.get("CANCEL_NAME")),
                clean_text(item.get("TYPE_CODE")),
                type_name,
                clean_text(item.get("CHANGE_DATE")),
                clean_text(item.get("BIZRNO")),
            )
        )
    if records:
        async with pool.acquire() as conn:
            await conn.executemany(UPSERT_DUR_SQL, records)


# ---------------------------------------------------------------------------
# 공통 파이프라인 수집 처리기
# ---------------------------------------------------------------------------
async def collect_api(
    step: int,
    pool: asyncpg.Pool,
    client: httpx.AsyncClient,
    api_key: str,
    num_rows: int = 100,
    delay: float = 0.1,
    limit: int | None = None,
):
    cfg = API_CONFIGS[step]
    name = cfg["name"]
    url = cfg["url"]

    print("\n==================================================")
    print(f"[{step}/4] {name} 수집 및 적재 시작")
    print(f"엔드포인트: {url}")
    print("==================================================")

    # 1페이지 호출하여 totalCount 확인
    first_resp = await fetch_page_with_retry(
        client,
        url,
        params={"serviceKey": api_key, "pageNo": 1, "numOfRows": num_rows, "type": "json"},
    )
    total_count, first_items = extract_items(first_resp)
    print(f"  -> 전체 데이터 건수: {total_count:,}건")

    if total_count == 0:
        print("  -> 수집 대상 데이터가 없습니다.")
        return

    target_count = min(total_count, limit) if limit else total_count
    total_pages = math.ceil(target_count / num_rows)
    print(f"  -> 수집 목표: {target_count:,}건 ({total_pages} 페이지)")

    # 배치 함수 매핑
    batch_handlers = {
        1: upsert_permission_batch,
        2: upsert_easy_batch,
        3: upsert_identification_batch,
        4: upsert_dur_batch,
    }
    handler = batch_handlers[step]

    # 첫 페이지 적재
    current_items = first_items[:target_count] if limit else first_items
    await handler(pool, current_items)
    processed_count = len(current_items)

    with tqdm(total=target_count, desc=f"{name[:12]}...", unit="건") as pbar:
        pbar.update(len(current_items))

        for page in range(2, total_pages + 1):
            await asyncio.sleep(delay)
            resp = await fetch_page_with_retry(
                client,
                url,
                params={"serviceKey": api_key, "pageNo": page, "numOfRows": num_rows, "type": "json"},
            )
            _, items = extract_items(resp)
            if not items:
                break

            if limit:
                remaining = target_count - processed_count
                if remaining <= 0:
                    break
                items = items[:remaining]

            await handler(pool, items)
            processed_count += len(items)
            pbar.update(len(items))

    print(f"  -> {name} 적재 완료 (처리 건수: {processed_count:,}건)")


async def main():
    parser = argparse.ArgumentParser(description="공공데이터포털 4대 의약품 API 수집 및 PostgreSQL Upsert 적재")
    parser.add_argument("--limit", type=int, default=None, help="각 API별 수집할 최대 건수 (테스트용, 예: 300)")
    parser.add_argument(
        "--steps",
        nargs="+",
        type=int,
        choices=[1, 2, 3, 4],
        default=[1, 2, 3, 4],
        help="실행할 단계 (1: 허가, 2: e약은요, 3: 낱알식별, 4: DUR)",
    )
    parser.add_argument("--delay", type=float, default=0.1, help="페이지 간 요청 지연 시간(초)")
    parser.add_argument("--num-rows", type=int, default=100, help="한 페이지당 결과 건수")
    args = parser.parse_args()

    api_key = get_env("DATA_GO_KR_API_KEY")
    if not api_key:
        print("[ERROR] .env에 DATA_GO_KR_API_KEY가 설정되어 있지 않습니다.", file=sys.stderr)
        sys.exit(1)

    pg_host = get_env("POSTGRES_HOST", "localhost")
    pg_port = int(get_env("POSTGRES_PORT", "5432"))
    pg_user = get_env("POSTGRES_USER", "postgres")
    pg_password = get_env("POSTGRES_PASSWORD", "postgres1234")
    pg_db = get_env("POSTGRES_DB", "ai_health")

    print("=== [공공데이터포털 의약품 4대 API 수집 파이프라인] ===")
    print(f"PostgreSQL: {pg_user}@{pg_host}:{pg_port}/{pg_db}")
    print(f"수집 단계: {args.steps}")
    if args.limit:
        print(f"건수 제한 모드: 각 API별 최대 {args.limit:,}건")
    else:
        print("전수 수집 모드: 전체 데이터 적재")
    print(f"요청 딜레이: {args.delay}초, 페이지 크기: {args.num_rows}건\n")

    # DB 커넥션 풀 생성
    pool = await asyncpg.create_pool(
        host=pg_host,
        port=pg_port,
        user=pg_user,
        password=pg_password,
        database=pg_db,
        min_size=2,
        max_size=10,
    )

    # 테이블 및 인덱스 생성
    async with pool.acquire() as conn:
        await conn.execute(CREATE_TABLE_SQL)
    print("  -> medicines 테이블 및 인덱스 준비 완료.")

    async with httpx.AsyncClient(headers={"User-Agent": "AIHealth/1.0"}) as client:
        for step in sorted(args.steps):
            await collect_api(
                step=step,
                pool=pool,
                client=client,
                api_key=api_key,
                num_rows=args.num_rows,
                delay=args.delay,
                limit=args.limit,
            )

    # 적재 결과 집계 출력
    async with pool.acquire() as conn:
        total_rows = await conn.fetchval("SELECT COUNT(*) FROM medicines;")
        easy_count = await conn.fetchval("SELECT COUNT(*) FROM medicines WHERE efcy_qesitm IS NOT NULL;")
        img_count = await conn.fetchval("SELECT COUNT(*) FROM medicines WHERE item_image IS NOT NULL;")
        dur_count = await conn.fetchval(
            "SELECT COUNT(*) FROM medicines WHERE bar_code IS NOT NULL OR material_name IS NOT NULL;"
        )

        sample_rows = await conn.fetch(
            "SELECT item_seq, item_name, entp_name, spclty_pblc, item_image, efcy_qesitm, bar_code FROM medicines ORDER BY item_seq ASC LIMIT 3;"
        )

    print("\n==================================================")
    print("=== 최종 적재 현황 ===")
    print(f"전체 의약품 수 (PK 기준): {total_rows:,}건")
    print(f"  - e약은요 정보 병합 건수: {easy_count:,}건")
    print(f"  - 낱알식별 이미지 병합 건수: {img_count:,}건")
    print(f"  - DUR 안전 정보 병합 건수: {dur_count:,}건")
    print("==================================================")

    print("\n[샘플 적재 데이터 확인 (상위 3건)]")
    for r in sample_rows:
        img_flag = "있음" if r["item_image"] else "없음"
        efcy_snippet = (r["efcy_qesitm"] or "없음")[:30].replace("\n", " ")
        print(f"  - 품목기준코드: {r['item_seq']} | 제품명: {r['item_name']} | 제조사: {r['entp_name']}")
        print(f"    구분: {r['spclty_pblc']} | 이미지: {img_flag} | 효능: {efcy_snippet} | 바코드: {r['bar_code']}")

    await pool.close()
    print("\n수집 파이프라인 작업이 완료되었습니다.")


if __name__ == "__main__":
    asyncio.run(main())
