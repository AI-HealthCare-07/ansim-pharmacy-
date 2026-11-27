"""약 한 개의 '성분 확인·DUR 연결·급여 정보' 상태를 정하는 순수 규칙 모듈(DB·네트워크 없음).

원칙(2026-11-27 결정)
- 공식 코드로 확인된 것만 '확인됨'. 이름 유사도·ATC 추정으로 성분을 정하지 않는다.
- 근거가 없으면 판단하지 않고 '확인할 수 없어요'.
- DUR 항목이 0건이어도 '안전하다'고 쓰지 않는다.
- 효능·용법·주의사항(허가 본문)은 제품 단위라 성분 확인과 무관하게 보여 준다.
- 최종 문구는 약사 확인 대상이다.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class IngredientState(str, Enum):
    CONFIRMED_HIRA = "CONFIRMED_HIRA"            # 심평원 주성분코드로 확인
    CONFIRMED_MFDS_ONLY = "CONFIRMED_MFDS_ONLY"  # 허가정보 주성분(M코드)만 확인
    UNRESOLVED = "UNRESOLVED"                    # 성분 근거 없음


class DurLink(str, Enum):
    FULL = "FULL"        # 모든 성분이 공식 코드로 연결됨
    PARTIAL = "PARTIAL"  # 일부 성분만 연결됨(복합제)
    NONE = "NONE"        # 연결 없음


@dataclass(frozen=True)
class MedicineStatus:
    ingredient: IngredientState
    dur_link: DurLink
    show_permit_text: bool          # 효능·용법·주의사항 표시 가능
    allow_ingredient_judgement: bool  # 병용·연령·임부 판단 허용
    age_rules_enabled: bool         # 연령·노인 규칙 적용(나이 입력 + 성분 연결 전체)
    pregnancy_rules_enabled: bool   # 임부 규칙 적용(임신 정보 입력 + 성분 연결 전체)
    coverage_note: str              # 급여 정보 문구
    dur_note: str                   # DUR 문구
    needs_pharmacist: bool = True


def decide(
    *,
    has_hira_code: bool,
    permit_ingredient_count: int,
    linked_ingredient_count: int,
    has_permit_text: bool,
    has_age: bool,
    has_pregnancy_info: bool,
) -> MedicineStatus:
    """linked_ingredient_count: 공식 코드로 DUR 규칙에 연결된 성분 수(이름 비교로 얻은 값은 넣지 않는다)."""
    if has_hira_code:
        ing = IngredientState.CONFIRMED_HIRA
    elif permit_ingredient_count > 0:
        ing = IngredientState.CONFIRMED_MFDS_ONLY
    else:
        ing = IngredientState.UNRESOLVED

    total = max(permit_ingredient_count, 1 if has_hira_code else 0)
    if ing is IngredientState.UNRESOLVED or linked_ingredient_count <= 0:
        link = DurLink.NONE
    elif total and linked_ingredient_count >= total:
        link = DurLink.FULL
    else:
        link = DurLink.PARTIAL

    if ing is IngredientState.CONFIRMED_HIRA:
        coverage = "급여 정보는 심평원 자료 기준으로 표시해요."
    else:
        coverage = "이 약의 급여 정보는 현재 자료에서 확인할 수 없어요. 비급여라는 뜻은 아니에요."

    dur_note = {
        DurLink.FULL: "DUR 항목이 있으면 보여 드려요. 항목이 없어도 안전하다는 뜻은 아니에요.",
        DurLink.PARTIAL: "일부 성분만 확인됐어요. 전체 성분 기준의 금기·주의는 판단하지 않았어요. 약사에게 확인해 주세요.",
        DurLink.NONE: "이 약의 금기·주의를 확인할 수 없어요. 약사에게 확인해 주세요.",
    }[link]

    return MedicineStatus(
        ingredient=ing,
        dur_link=link,
        show_permit_text=bool(has_permit_text),
        allow_ingredient_judgement=link is not DurLink.NONE,
        age_rules_enabled=(link is DurLink.FULL) and has_age,
        pregnancy_rules_enabled=(link is DurLink.FULL) and has_pregnancy_info,
        coverage_note=coverage,
        dur_note=dur_note,
    )
