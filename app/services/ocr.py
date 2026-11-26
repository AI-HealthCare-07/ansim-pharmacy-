"""RapidOCR 래퍼와 사진 품질 판단.

- 글자 찾기: 기본(v6 small), 글자 읽기: 한국어 v5 mobile (3.10 기본값은 한국어 미지원)
- 엔진은 처음 호출할 때 한 번만 만든다.
- 기준값은 임시값이다. 실제 처방전 사진으로 보정할 것.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

MIN_AVG_SCORE = 0.80  # 평균 신뢰도가 이보다 낮으면 다시 찍기
MIN_CHARS = 20        # 읽힌 글자(공백 제외)가 이보다 적으면 다시 찍기


@dataclass
class OcrResult:
    lines: list[str]
    scores: list[float]

    @property
    def char_count(self) -> int:
        return sum(len(t.replace(" ", "")) for t in self.lines)

    @property
    def avg_score(self) -> float:
        return sum(self.scores) / len(self.scores) if self.scores else 0.0


@dataclass
class QualityVerdict:
    ok: bool
    reason: str | None  # None, "TOO_FEW_CHARS", "LOW_CONFIDENCE"
    avg_score: float
    char_count: int


@lru_cache(maxsize=1)
def get_engine() -> RapidOCR:
    return RapidOCR(params={
        "Rec.lang_type": LangRec.KOREAN,
        "Rec.ocr_version": OCRVersion.PPOCRV5,
        "Rec.model_type": ModelType.MOBILE,
    })


def run_ocr(image) -> OcrResult:
    """image: 파일 경로, bytes, numpy 배열 또는 PIL 이미지."""
    r = get_engine()(image)
    return OcrResult(
        lines=list(r.txts or []),
        scores=[float(s) for s in (r.scores or [])],
    )


def judge_quality(res: OcrResult) -> QualityVerdict:
    avg, chars = round(res.avg_score, 3), res.char_count
    if chars < MIN_CHARS:
        return QualityVerdict(False, "TOO_FEW_CHARS", avg, chars)
    if avg < MIN_AVG_SCORE:
        return QualityVerdict(False, "LOW_CONFIDENCE", avg, chars)
    return QualityVerdict(True, None, avg, chars)
