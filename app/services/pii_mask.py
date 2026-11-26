"""SYS-005·DOC-003: OCR 원문 저장 전, Haiku 전송 전 식별정보 가림.

규칙 기반이라 놓칠 수 있으므로 find_residual_pii로 다시 검사하고, 남으면 저장·전송하지 않는다.
약 이름·용량·횟수·일수·상병코드·진단명·날짜는 남긴다.
"""
from __future__ import annotations

import re
from collections import Counter

# (분류, 이름표, 바꿀 글자). 한 줄에 이름표가 여럿이면 가장 앞의 것을 쓰고, 그 뒤 값을 통째로 가린다.
LABELS = [
    ("RRN", r"주민\s*등록\s*번호|주민번호", "[주민번호]"),
    ("BIZ_NO", r"사업자\s*등록\s*번호|사업자\s*번호", "[사업자번호]"),
    ("RECEIPT_NO",
     r"영수증\s*번호|신분\s*확인\s*번호|신분\s*확인|현금\s*승인\s*번호"
     r"|승인\s*번호|카드\s*번호|거래\s*번호",
     "[영수증번호]"),
    ("ISSUE_NO", r"교부\s*번호|처방전\s*번호|검증\s*코드", "[교부번호]"),
    ("PATIENT", r"환자\s*정보", "[환자정보]"),
    ("NAME", r"(?:환자\s*)?성\s*명|환자명|수진자", "[이름]"),
    ("BIRTH", r"생년\s*월일", "[생년월일]"),
    ("REG_NO",
     r"(?<!주민)(?<!주민\s)(?<!사업자)(?<!사업자\s)등록\s*번호"
     r"|병록\s*번호|차트\s*번호|요양기관\s*기호|면허\s*번호",
     "[등록번호]"),
    ("DOCTOR", r"처방\s*의사|처방의(?!료)|의사\s*성명|담당의|주치의|진료의(?![가-힣])", "[의사]"),
    ("PHARMACIST",
     r"(?:조제|관리|개설|대표|담당|근무|복약지도)\s*약사(?:\s*성명|명)?"
     r"|약사\s*성명|약사명|조제자|(?<![가-힣])약사(?![가-힣])",
     "[약사]"),
    ("PHONE", r"(?:전화(?:\s*번호)?|TEL|Tel|FAX|Fax|팩스)(?=[\s:：.)]*\(?\d)", "[전화]"),
    ("ADDRESS", r"약국\s*주소|(?<![가-힣])주\s*소(?![가-힣])|소재지", "[주소]"),
    ("ORG",
     r"의료기관\s*명칭|요양기관\s*명|병원명|병원\s*정보|의료기관\s*정보"
     r"|처방\s*의료기관|처방전\s*발행\s*기관|발행\s*기관|조제\s*약국|약국명"
     r"|(?<![가-힣])상\s*호(?!작용)",
     "[의료기관]"),
]
LABEL_RES = [(cat, re.compile(pat), ph) for cat, pat, ph in LABELS]
SEP = re.compile(r"^[\s:：|/\-.]*")

# 모양으로 찾는 규칙. 순서가 중요하다(주민번호를 긴 숫자보다 먼저).
P = {
    "RRN": re.compile(r"\d{6}\s*-\s*[1-8][\d*Xx]{6}"),
    "PHONE": re.compile(r"(?<!\d)(?:0\d{1,2}[-.)\s]\s?\d{3,4}[-.\s]\d{4}|1[5-9]\d{2}-\d{4})(?!\d)"),
    "BIZ_NO": re.compile(r"(?<!\d)\d{3}-\d{2}-\d{5}(?!\d)"),
    "ISSUE_NO": re.compile(r"제\s*\d{1,6}\s*호"),
    "ADDRESS": re.compile(
        r"[가-힣]+(?:특별시|광역시|특별자치시|도|시)\s+[가-힣]+(?:시|군|구)\s+"
        r"[가-힣0-9]+(?:로|길|동|읍|면)(?:\s*\d+(?:-\d+)?)?"),
    "BARCODE": re.compile(r"(?:\|+\s*){3,}[\w-]*"),
    "LONG_NO": re.compile(r"(?<!\d)\d{12,}(?!\d)"),
    "ENG_ORG": re.compile(r"(?i)\b(?:[a-z&.'\-]+\s+){0,4}(?:pharmacy|hospital|clinic|medical\s+center)\b"),
    "ORG": re.compile(r"[가-힣A-Za-z0-9]*(?:한의원|병원|의원|치과|클리닉|보건소|의료원)(?![가-힣])"),
    "PHARMACY": re.compile(r"[가-힣A-Za-z0-9]+약국"),
    "NAME": re.compile(r"(?<![가-힣])[가-힣]\*{1,2}[가-힣]?(?![가-힣])"),
}
PH = {
    "RRN": "[주민번호]", "PHONE": "[전화]", "BIZ_NO": "[사업자번호]", "ISSUE_NO": "[교부번호]",
    "ADDRESS": "[주소]", "BARCODE": "[바코드]", "LONG_NO": "[번호]", "ENG_ORG": "[기관영문명]",
    "ORG": "[의료기관]", "PHARMACY": "[약국]", "NAME": "[이름]",
}


def _first_label(line: str):
    best = None
    for cat, rx, ph in LABEL_RES:
        m = rx.search(line)
        if m and (best is None or m.start() < best[0].start()):
            best = (m, cat, ph)
    return best


def mask_lines(lines: list[str]) -> tuple[list[str], dict]:
    """OCR 줄 목록을 가린다. 이름표만 있고 값이 다음 줄에 있으면(표 칸 분리) 다음 줄을 통째로 가린다."""
    counts: Counter = Counter()
    out: list[str] = []
    pending = None
    for line in lines:
        if pending and _first_label(line) is None:
            cat, ph = pending
            out.append(ph)
            counts[cat] += 1
            pending = None
            continue
        pending = None
        hit = _first_label(line)
        if hit:
            m, cat, ph = hit
            if SEP.sub("", line[m.end():]):
                line = line[:m.end()] + " " + ph
                counts[cat] += 1
            else:
                pending = (cat, ph)
        for cat, rx in P.items():
            line, n = rx.subn(PH[cat], line)
            if n:
                counts[cat] += n
        out.append(line)
    return mask_org_neighbors(out, dict(counts))


RESIDUAL = {
    "RRN": re.compile(r"\d{6}\s*-\s*[1-8]"),
    "PHONE": P["PHONE"],
    "BIZ_NO": P["BIZ_NO"],
    "LONG_NO": P["LONG_NO"],
    "ENG_ORG": P["ENG_ORG"],
    "ORG": re.compile(r"[가-힣]+(?:한의원|병원|의원|보건소|의료원)(?![가-힣])"),
    "PHARMACY": re.compile(r"[가-힣]+약국"),
    "NAME": P["NAME"],
}


def find_residual_pii(text: str) -> list[str]:
    """가린 뒤에도 남은 식별정보 분류 목록. 비어 있어야 저장·전송할 수 있다."""
    return sorted(cat for cat, rx in RESIDUAL.items() if rx.search(text))


def age_band(birth_year: int, this_year: int) -> str:
    """SYS-005: AI에는 나이 대신 나이대만 보낸다."""
    return f"{((this_year - birth_year) // 10) * 10}대"


# 장식 글꼴 약국 이름은 OCR이 깨진 글자로 읽어 모양 규칙에 안 걸린다(예: 이무문작영).
# 약국을 가리키는 줄 앞뒤의 짧은 글자 줄을 위치로 가린다. 병원 칸은 진단명과 붙어 있을 수 있어 기준에서 뺀다.
ANCHORS = ("[전화]", "[주소]", "[약사]", "[기관영문명]", "[사업자번호]", "[약국]")
KEEP = re.compile(r"\d|\[|mg|ml|정$|캡슐|시럽|복용|식후|식전|아침|점심|저녁|취침|공복"
                  r"|상병|진단|질병|병명|분류|증$|염$|압$")

ADDR_EXTRA = re.compile(r"아파트|빌딩|타워|프라자|플라자|상가|오피스텔|\d+\s*층|번\s*출구|바로\s*앞|맞은\s*편")


def mask_org_neighbors(lines: list[str], counts: dict, window: int = 2) -> tuple[list[str], dict]:
    anchors = {i for i, line in enumerate(lines) if any(a in line for a in ANCHORS)}
    out = list(lines)
    for i in sorted(anchors):
        for j in range(max(0, i - window), min(len(out), i + window + 1)):
            core = re.sub(r"[\s.,·()]", "", out[j])
            if j not in anchors and "[" not in out[j] and ADDR_EXTRA.search(out[j]):
                out[j] = "[주소]"
                counts["ADDRESS"] = counts.get("ADDRESS", 0) + 1
                continue
            if j in anchors or not 2 <= len(core) <= 20 or KEEP.search(out[j]):
                continue
            out[j] = "[약국정보]"
            counts["ORG_NEAR"] = counts.get("ORG_NEAR", 0) + 1
    return out, counts
