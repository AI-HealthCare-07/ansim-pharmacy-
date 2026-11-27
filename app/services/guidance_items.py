"""복약지도서에 담을 정보 항목과 우리 데이터의 대응(순수 규칙 모듈, DB 없음).

근거: 약사법 제24조제4항, 약사법 시행규칙 제15조의6제1항(2026.11.18 개정본, 보건복지부령 제1210호)
 1 의약품의 명칭(성상 포함) 2 용법·용량 3 효능·효과 4 부작용(상호작용·운전/기계조작 등 일상생활 위험 포함)
 5 저장방법 6 의약품 부작용 피해구제절차 안내
- 규칙상 이 항목들은 '약사가 필요하다고 판단하는 정보'이며, 이 서비스의 안내는 약사 지도를 대신하지 않는다.
- 항목마다 근거 데이터가 있을 때만 보여 준다. 없으면 '확인할 수 없어요'로 표시한다(추정·생성 금지).
- 항목 6(피해구제 절차)은 고정 안내 문구이며 문구 출처 확인이 끝나기 전에는 운영하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GuidanceItem:
    key: str
    label: str
    legal_no: int           # 시행규칙 제15조의6제1항 호 번호
    source_fields: tuple    # 근거가 되는 데이터 필드(medicines / medicine_permit_detail)


ITEMS: tuple = (
    GuidanceItem("name_chart", "의약품의 명칭(성상 포함)", 1, ("item_name", "chart")),
    GuidanceItem("usage", "용법·용량", 2, ("ud_doc_id", "ud_doc_data")),
    GuidanceItem("efficacy", "효능·효과", 3, ("ee_doc_id", "ee_doc_data")),
    GuidanceItem("adverse", "부작용(상호작용·운전·기계조작 등 위험 포함)", 4, ("nb_doc_id", "nb_doc_data")),
    GuidanceItem("storage", "저장방법", 5, ("storage_method",)),
    GuidanceItem("relief", "의약품 부작용 피해구제절차 안내", 6, ()),
)


def availability(record: dict, *, relief_text_verified: bool = False) -> dict:
    """record: 한 약의 필드 값 dict. 항목 key → '있음' / '확인할 수 없어요' 를 돌려준다."""
    out = {}
    for it in ITEMS:
        if it.key == "relief":
            out[it.key] = "있음" if relief_text_verified else "확인할 수 없어요"
            continue
        has = any(str(record.get(f) or "").strip() for f in it.source_fields)
        out[it.key] = "있음" if has else "확인할 수 없어요"
    return out


# 항목 6 고정 안내 문구(초안). 근거: 약사법 제86조의4제1항(피해구제급여는 의약품안전관리원의 장에게 신청).
# 연락처·누리집·서류 목록은 법령이 아니라 기관 안내이므로 공식 누리집 확인 전에는 넣지 않는다.
# 법제처 정본과 약사 확인이 끝나면 availability(..., relief_text_verified=True)로 켠다.
RELIEF_NOTICE_DRAFT = (
    "의약품을 정상적으로 사용했는데도 부작용 피해가 생기면, 약사법 제86조의4에 따라 "
    "한국의약품안전관리원에 피해구제급여를 신청할 수 있어요. 신청 방법은 약사에게 확인해 주세요."
)
