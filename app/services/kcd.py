"""상병코드 사전 조회. 코드가 사전에 있는지와 이름을 알려 줄 뿐, 진단이나 판단은 하지 않는다."""
from __future__ import annotations

import logging

from tortoise import connections

log = logging.getLogger(__name__)


def normalize_kcd(code: str | None) -> str | None:
    """소수점·공백을 지우고 대문자로. 사전(kcd_codes.sick_cd)과 같은 모양."""
    if not code:
        return None
    c = code.replace(".", "").replace(" ", "").upper()
    return c or None


async def enrich_diagnoses(items: list[dict]) -> None:
    """각 진단에 kcd_valid(사전에 있음 True/없음 False/확인 못 함 None)와 kcd_name(사전 이름)을 붙인다."""
    codes = sorted({normalize_kcd(d.get("kcd_code")) for d in items if d.get("kcd_code")} - {None})
    found: dict[str, str] = {}
    ok = True
    if codes:
        try:
            rows = await connections.get("default").execute_query_dict(
                "SELECT sick_cd, name_ko FROM kcd_codes WHERE sick_cd = ANY($1::text[])", [codes])
            found = {r["sick_cd"]: r["name_ko"] for r in rows}
        except Exception:  # 사전이 아직 없거나 DB 오류: 검사를 못 했을 뿐 실패로 보지 않는다
            log.exception("kcd lookup failed")
            ok = False
    for d in items:
        c = normalize_kcd(d.get("kcd_code"))
        if not c:
            d["kcd_valid"], d["kcd_name"] = None, None
        elif not ok:
            d["kcd_valid"], d["kcd_name"] = None, None
        else:
            d["kcd_valid"], d["kcd_name"] = c in found, found.get(c)
