"""DOC-003: 가린 OCR 글자를 Claude Haiku로 처방 항목 JSON으로 정리한다.

- 입력은 가린 원문(documents.ocr_raw)만 쓴다. 보내기 직전에 남은 식별정보를 다시 검사한다.
- 도구 형식을 강제해 정해진 칸으로만 답하게 하고, Pydantic으로 검사한다. 형식 오류면 1번만 다시 요청한다.
- 처방에 적힌 내용만 옮긴다. 적히지 않은 시간·용도·진단은 추정하지 않는다.
"""
from __future__ import annotations

import os
import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from app.services.pii_mask import find_residual_pii

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
KCD_RE = re.compile(r"^[A-Z]\d{2}(?:\.\d{1,2})?$")
KCD_FIX = {"1": "I", "l": "I", "|": "I", "0": "O"}  # OCR이 자주 헷갈리는 첫 글자


class StructuringError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


class DrugItem(BaseModel):
    name: str = Field(description="문서에 적힌 약 이름 그대로(함량 포함). 성분명이 괄호에 있으면 포함")
    edi_code: str | None = Field(None, description="9자리 보험(EDI) 코드가 보이면 숫자만, 없으면 null")
    dose_per_time: float | None = Field(None, description="1회 투약량 숫자(0.5정이면 0.5)")
    dose_unit: str | None = Field(None, description="정, 캡슐, 포, mL 등 단위")
    times_per_day: int | None = Field(None, description="1일 투여 횟수")
    total_days: int | None = Field(None, description="총 투약 일수")
    timing: str | None = Field(None, description="복용 시점 원문 그대로(예: 식후 30분, 취침 전). 적혀 있지 않으면 null")

    @field_validator("edi_code")
    @classmethod
    def _edi(cls, v):
        if v is None:
            return None
        digits = re.sub(r"\D", "", v)
        return digits if len(digits) == 9 else None


class Diagnosis(BaseModel):
    kcd_code: str | None = Field(None, description="상병(질병분류)코드. 영문자 1개 + 숫자 2개 (+소수점)")
    name: str | None = Field(None, description="진단명(상병명) 원문")
    kcd_autocorrected: bool = Field(False, description="서버가 형식을 고쳤으면 true. 모델은 항상 false로 둔다")

    @model_validator(mode="after")
    def _fix_kcd(self):
        code = (self.kcd_code or "").strip().replace(" ", "")
        if not code:
            self.kcd_code = None
            return self
        fixed = code[0].upper() + code[1:]
        if not KCD_RE.match(fixed) and fixed[0] in KCD_FIX:
            fixed = KCD_FIX[fixed[0]] + fixed[1:]
            self.kcd_autocorrected = True
        self.kcd_code = fixed if KCD_RE.match(fixed) else None
        if self.kcd_code is None:
            self.kcd_autocorrected = False
        return self


class StructuredDoc(BaseModel):
    doc_kind: Literal["PRESCRIPTION", "MED_BAG", "MEDICAL_RECORD", "OTHER"]
    visit_date: date | None = Field(None, description="진료일·교부일·조제일 중 문서에 적힌 날짜(YYYY-MM-DD)")
    drugs: list[DrugItem] = Field(default_factory=list)
    diagnoses: list[Diagnosis] = Field(default_factory=list)
    unclear: list[str] = Field(default_factory=list, description="읽기 애매해서 확인이 필요한 부분")


TOOL = {
    "name": "record_prescription",
    "description": "문서에서 읽은 처방 항목을 기록한다.",
    "input_schema": StructuredDoc.model_json_schema(),
}

SYSTEM = """당신은 처방전·약봉투·진료기록의 OCR 글자를 정해진 칸으로 옮기는 도우미입니다.
규칙:
1. 문서에 적힌 내용만 옮깁니다. 적히지 않은 복용 시간, 약의 용도, 진단은 추정하지 말고 null로 둡니다.
2. 숫자는 바꾸지 않습니다. 0.5정은 0.5로 적습니다.
3. [이름], [주민번호], [의료기관], [약국] 같은 대괄호는 가린 개인정보이니 무시하고, 칸에 옮기지 않습니다.
4. 상병코드는 영문자로 시작합니다(예: I10.9). OCR이 I를 1로, O를 0으로 읽었을 수 있습니다.
5. 표가 줄 단위로 흩어져 있을 수 있습니다. 약 이름 다음 줄들의 숫자가 1회량·횟수·일수일 수 있습니다.
6. 확신이 없는 부분은 unclear에 짧게 적습니다.
반드시 record_prescription 도구로만 답합니다."""


def _client():
    import anthropic
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise StructuringError("NO_API_KEY", "ANTHROPIC_API_KEY가 설정되지 않았어요.")
    return anthropic.AsyncAnthropic(api_key=key)


async def structure_ocr(lines: list[str]) -> tuple[StructuredDoc, dict]:
    """가린 OCR 줄을 받아 StructuredDoc을 돌려준다. 두 번째 값은 호출 기록(토큰 수 등)."""
    text = "\n".join(lines)
    residual = find_residual_pii(text)
    if residual:  # 가림이 덜 된 글은 절대 보내지 않는다
        raise StructuringError("PII_RESIDUAL", f"가리지 못한 정보가 남아 전송하지 않았어요: {residual}")

    client = _client()
    messages = [{"role": "user", "content": f"다음은 가린 OCR 글자입니다.\n\n{text}"}]
    usage = {"model": MODEL, "attempts": 0, "input_tokens": 0, "output_tokens": 0}
    last_error = None
    for _ in range(2):  # 처음 + 형식 오류 시 1회 재시도
        usage["attempts"] += 1
        resp = await client.messages.create(
            model=MODEL, max_tokens=1500, system=SYSTEM,
            tools=[TOOL], tool_choice={"type": "tool", "name": TOOL["name"]}, messages=messages,
        )
        usage["input_tokens"] += resp.usage.input_tokens
        usage["output_tokens"] += resp.usage.output_tokens
        block = next((b for b in resp.content if b.type == "tool_use"), None)
        if block is None:
            last_error = "도구 응답이 없음"
            continue
        try:
            return StructuredDoc.model_validate(block.input), usage
        except ValidationError as e:
            last_error = str(e)
            messages += [
                {"role": "assistant", "content": resp.content},
                {"role": "user", "content": [{"type": "tool_result", "tool_use_id": block.id, "is_error": True,
                                              "content": f"형식 오류입니다. 고쳐서 다시 기록하세요:\n{last_error[:1500]}"}]},
            ]
    raise StructuringError("STRUCTURE_INVALID", f"정해진 형식으로 정리하지 못했어요: {(last_error or '')[:300]}")
