"""성분 확인 현황 집계(읽기 전용: DB 읽기만, 파일 읽기만, API 호출 없음).
사용: PYTHONPATH=. .venv/bin/python scripts/report_ingredient_coverage.py
출력: 화면 + data/reports/ingredient_coverage.json
원칙: 공식 코드 연결만 센다. 이름 유사도·ATC 추정은 쓰지 않는다. 근거 없으면 '확인할 수 없어요'.
"""
import asyncio, csv, glob, json, os, re
from collections import defaultdict
import asyncpg

BAR = "data/raw/kpis/BarCodeData.txt"
DUR = glob.glob("data/raw/dur_api/*.jsonl")
PERMIT = "data/raw/permit_detail/detail.jsonl"
M_RE = re.compile(r"\[(M\d+)\]")


def load_bar():
    out = {}
    with open(BAR, encoding="cp949", newline="") as f:
        for r in csv.DictReader(f, delimiter="|"):
            k = (r.get("품목기준코드") or "").strip()
            g = (r.get("일반명코드(성분명코드)") or "").strip()
            if k and g:
                out.setdefault(k, g)
    return out


def load_permit():
    out = {}
    if os.path.exists(PERMIT):
        for l in open(PERMIT, encoding="utf-8"):
            r = json.loads(l); row = r.get("row")
            if row:
                out[r["_item_seq"]] = {"m": M_RE.findall(row.get("MAIN_ITEM_INGR") or ""),
                                       "doc": all((row.get(k) or "").strip() for k in ("EE_DOC_DATA", "UD_DOC_DATA", "NB_DOC_DATA"))}
    return out


def load_dur():
    item_d = defaultdict(set)   # 품목 → D코드(DUR 행에 직접 있는 것)
    item_m = defaultdict(set)   # 품목 → M코드(DUR 행의 MAIN_INGR, 단일 성분 행만)
    m_d = defaultdict(set)      # M코드 → D코드 (단일 성분 행에서만)
    for p in DUR:
        for l in open(p, encoding="utf-8"):
            r = json.loads(l)
            for pre in ("", "MIXTURE_"):
                seq, d, mix, main = r.get(pre + "ITEM_SEQ"), r.get(pre + "INGR_CODE"), r.get(pre + "MIX"), r.get(pre + "MAIN_INGR")
                if not (seq and d):
                    continue
                item_d[seq].add(d)
                ms = M_RE.findall(main or "")
                if mix == "단일" and len(ms) == 1:
                    item_m[seq].add(ms[0])
                if mix == "단일" and len(ms) == 1:
                    m_d[ms[0]].add(d)
    return item_d, m_d, item_m


async def main():
    bar, permit = load_bar(), load_permit()
    item_d, m_d, item_m = load_dur()
    amb = sum(1 for v in m_d.values() if len(v) > 1)
    con = await asyncpg.connect(host=os.getenv("POSTGRES_HOST", "localhost"), port=int(os.getenv("POSTGRES_PORT", "5432")),
                                database=os.environ["POSTGRES_DB"], user=os.environ["POSTGRES_USER"], password=os.environ["POSTGRES_PASSWORD"])
    have_codes = defaultdict(set)
    for r in await con.fetch("SELECT item_seq, main_ingredient_code FROM v_item_ingredients"):
        have_codes[r["item_seq"]].add(r["main_ingredient_code"])
    have = set(have_codes)
    meds = await con.fetch("SELECT item_seq, (coalesce(nb_doc_id,'')<>'') AS doc FROM medicines WHERE cancel_name='정상'")
    await con.close()

    # 교차표(규칙 쪽 코드 체계로 가는 길): 품목이 DUR 행의 M코드와 DB 주성분코드를 둘 다 가진 경우만 사용.
    m_p4 = defaultdict(set)
    for seq, ms in item_m.items():
        codes = have_codes.get(seq)
        if codes and len({c[:4] for c in codes}) == 1 and len(ms) == 1:
            m_p4[next(iter(ms))].add(next(iter(codes))[:4])
    ambig_p4 = sum(1 for v in m_p4.values() if len(v) > 1)

    R = defaultdict(int)
    for m in meds:
        s = m["item_seq"]; R["정상 전체"] += 1
        # 1) 성분 확인 단계
        if s in have: st = "S1 주성분코드 있음"
        elif s in bar: st = "S2 코드 없음 → 표준코드 일반명코드로 성분 확인"
        elif s in permit and permit[s]["m"]: st = "S3 코드 없음 → 허가정보 주성분(M코드)으로 성분 확인"
        else: st = "S4 성분 근거 없음 → 확인할 수 없어요"
        R[st] += 1
        # 2) DUR 연결
        d = set(item_d.get(s, set()))
        via = "DUR 행에 품목이 직접 있음" if d else ""
        if not d and s in permit:
            for mc in permit[s]["m"]:
                ds = m_d.get(mc, set())
                if len(ds) == 1: d |= ds; via = "M코드→D코드 대응(1:1)"
        R["DUR성분코드 연결됨: " + (via or "없음")] += 1
        # 2-2) 규칙(dur_rules) 쪽 코드 체계(앞 4자리)로 가는 길: 허가 M코드 → 교차표 1:1
        if s not in have and s in permit and permit[s]["m"]:
            p4 = [m_p4.get(mc, set()) for mc in permit[s]["m"]]
            ok = all(len(x) == 1 for x in p4)
            R["코드 없는 약 중 허가 M코드 전부 → 규칙 코드(앞4자리) 1:1 연결" if ok else "코드 없는 약 중 규칙 코드 연결 불가(교차표 없음 또는 1:N)"] += 1
        # 3) 문서
        R["효능·용법·주의사항 있음"] += 1 if (m["doc"] or (s in permit and permit[s]["doc"])) else 0
        R["효능·용법·주의사항 없음"] += 0 if (m["doc"] or (s in permit and permit[s]["doc"])) else 1
    out = dict(R)
    out["_메모"] = {"DUR 행 파일수": len(DUR), "M→D 대응 M코드수": len(m_d), "M이 D 여러 개로 가서 제외한 수": amb, "교차표 M코드 수": len(m_p4), "M이 앞4자리 여러 개로 가서 제외한 수": ambig_p4,
                  "허가상세 받은 품목수": len(permit), "표준코드 일반명코드 품목수": len(bar)}
    os.makedirs("data/reports", exist_ok=True)
    json.dump(out, open("data/reports/ingredient_coverage.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    for k, v in out.items():
        print(f"{k}: {v:,}" if isinstance(v, int) else f"{k}: {v}")

asyncio.run(main())
