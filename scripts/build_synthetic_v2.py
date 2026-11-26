"""가상 데이터 v2: DB의 정상 유통 의약품에서 약을 뽑아 매칭 평가셋과 가상 처방 기록을 만든다.

v1(3,200건)은 약이 13종뿐이라 매칭 평가가 안 된다. v2는 실제 허가 의약품 수백 종을 쓰고 정답(item_seq)을 함께 저장한다.
환자 정보는 모두 지어낸 값이다(이름은 가린 형태, 나이는 나이대만).

출력 (data/ 아래라 GitHub에 올라가지 않음)
- data/synthetic/v2/drug_pool.json      뽑은 약 목록
- data/synthetic/v2/match_eval.jsonl    매칭 평가 질의(처방전에 적히는 여러 표기 + 정답)
- data/synthetic/v2/prescriptions.json  가상 처방 기록(약 1~5개, 용법, 상병코드, 정답 포함)

사용법: python scripts/build_synthetic_v2.py --pool 600 --records 2000
"""
import argparse
import asyncio
import json
import random
import re
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OUT = Path("data/synthetic/v2")
SEED = 20261126

# 약 분류(class_name)에 들어 있는 말 → (상병코드, 진단명, 장기 복용 여부). 위에서부터 먼저 맞는 것을 쓴다.
CLASS_MAP = [
    ("혈압", "I10.9", "본태성 고혈압", True),
    ("동맥경화", "E78.5", "고지혈증", True),
    ("고지혈", "E78.5", "고지혈증", True),
    ("당뇨", "E11.9", "합병증을 동반하지 않은 2형 당뇨병", True),
    ("혈액응고", "I48.9", "상세불명의 심방세동", True),
    ("갑상선", "E03.9", "상세불명의 갑상선기능저하증", True),
    ("소화성궤양", "K29.7", "상세불명의 위염", False),
    ("해열", "M54.5", "요통", False),
    ("진통", "M54.5", "요통", False),
    ("소염", "M17.9", "상세불명의 무릎관절증", False),
    ("항히스타민", "J30.4", "상세불명의 알레르기비염", False),
    ("알레르기", "J30.4", "상세불명의 알레르기비염", False),
    ("진해", "J20.9", "상세불명의 급성 기관지염", False),
    ("거담", "J20.9", "상세불명의 급성 기관지염", False),
    ("최면", "G47.0", "불면증", False),
    ("정신신경", "F41.9", "상세불명의 불안장애", True),
    ("항생", "J06.9", "상세불명의 급성 상기도감염", False),
]
DEFAULT_DX = ("R69", "상세불명 및 원인미상의 질병", False)
CONFUSE = {"정": "점", "텍": "택", "스": "수", "르": "로", "캡": "갭", "슐": "술", "타": "다", "0": "O", "1": "l"}
STRENGTH_TAIL = re.compile(r"\s*[0-9][0-9./]*\s*(mg|mcg|g|ml|밀리그램|마이크로그램|그램)?$", re.I)


def classify(class_name: str):
    for key, code, name, chronic in CLASS_MAP:
        if key in (class_name or ""):
            return code, name, chronic
    return DEFAULT_DX


def surface_forms(item_name: str, rng: random.Random) -> dict:
    """허가 이름 → 처방전·약봉투에 적히는 여러 표기."""
    base = re.sub(r"\(.*?\)", "", item_name).strip()
    base = base.replace("밀리그램", "mg").replace("마이크로그램", "mcg").replace("그램", "g")
    spaced = re.sub(r"(정|캡슐)\s*([0-9])", r"\1 \2", base)
    brand = STRENGTH_TAIL.sub("", base).strip()
    chars = list(spaced)
    idx = [i for i, ch in enumerate(chars) if ch in CONFUSE]
    if idx:
        i = rng.choice(idx)
        chars[i] = CONFUSE[chars[i]]
    ocr = "".join(chars).replace(" ", "")
    forms = {"full": item_name, "spaced": spaced, "ocr_noise": ocr}
    if brand and brand != spaced and len(brand) >= 2:
        forms["brand_only"] = brand
    return forms


def first_edi(raw: str | None) -> str | None:
    m = re.search(r"\d{9}", raw or "")
    return m.group(0) if m else None


def make_prescription(i: int, pool: list[dict], rng: random.Random) -> dict:
    drugs = rng.sample(pool, k=min(len(pool), rng.choices([1, 2, 3, 4, 5], weights=[15, 30, 30, 15, 10])[0]))
    chronic_any = False
    items, dxs = [], {}
    for d in drugs:
        code, name, chronic = classify(d["class_name"])
        chronic_any = chronic_any or chronic
        dxs[code] = name
        sleep = "최면" in d["class_name"]
        times = 1 if (chronic or sleep) else rng.choice([2, 3, 3])
        items.append({
            "printed_name": rng.choice([d["forms"]["spaced"], d["forms"]["full"]]),
            "edi_code": d["edi_code"] if rng.random() < 0.6 else None,
            "dose_per_time": rng.choice([1, 1, 1, 1, 0.5, 2]),
            "dose_unit": "캡슐" if "캡슐" in d["item_name"] else "정",
            "times_per_day": times,
            "timing": "취침 전" if sleep else ("아침 식후 30분" if times == 1 else "식후 30분"),
            "truth_item_seq": d["item_seq"],
            "truth_item_name": d["item_name"],
        })
    days = rng.choice([28, 30, 56, 90]) if chronic_any else rng.choice([3, 5, 7, 14])
    for it in items:
        it["total_days"] = days
    visit = date(2026, 1, 1) + timedelta(days=rng.randrange(300))
    family = "김이박최정강조윤장임한오서신권황안송"
    return {
        "record_id": f"SYN2-{i:05d}",
        "doc_kind": rng.choice(["PRESCRIPTION", "PRESCRIPTION", "MED_BAG"]),
        "patient_name_masked": rng.choice(family) + "*" + rng.choice("민수영지현준서아"),
        "age_band": rng.choice(["30대", "40대", "50대", "60대", "60대", "70대", "80대"]),
        "sex": rng.choice(["M", "F"]),
        "visit_date": visit.isoformat(),
        "drugs": items,
        "diagnoses": [{"kcd_code": c, "name": n} for c, n in dxs.items()],
    }


async def load_pool(n: int, rng: random.Random, skip: set = frozenset()) -> list[dict]:
    from tortoise import Tortoise, connections
    from app.core.db.databases import TORTOISE_ORM
    await Tortoise.init(config=TORTOISE_ORM)
    rows = await connections.get("default").execute_query_dict(
        "SELECT item_seq, item_name, entp_name, edi_code,"
        " coalesce(spclty_pblc, etc_otc_name, '') AS kind, coalesce(class_name, '') AS class_name,"
        " (efcy_qesitm IS NOT NULL) AS has_easy"
        " FROM medicines WHERE cancel_name = '정상' AND item_name ~ '(정|캡슐)'"
        " AND item_name !~ '(수출|주사|외용|연고|크림|겔|패치)'")
    await Tortoise.close_connections()
    rows = [r for r in rows if str(r["item_seq"]) not in skip]
    rx = [r for r in rows if "전문" in r["kind"]]
    otc = [r for r in rows if "전문" not in r["kind"]]

    def take(src, k):
        easy = [r for r in src if r["has_easy"]]
        rest = [r for r in src if not r["has_easy"]]
        a = rng.sample(easy, min(len(easy), k // 2))
        b = rng.sample(rest, min(len(rest), k - len(a)))
        return a + b

    picked = take(rx, int(n * 0.7)) + take(otc, n - int(n * 0.7))
    pool = []
    for r in picked:
        pool.append({"item_seq": str(r["item_seq"]), "item_name": r["item_name"], "entp_name": r["entp_name"],
                     "edi_code": first_edi(r["edi_code"]), "kind": r["kind"], "class_name": r["class_name"],
                     "forms": surface_forms(r["item_name"], rng)})
    print(f"후보 {len(rows)}종 중 {len(pool)}종 선택 (전문 {sum('전문' in p['kind'] for p in pool)})")
    return pool


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", type=int, default=600)
    ap.add_argument("--records", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=0, help="난수 씨앗")
    ap.add_argument("--out", default="data/synthetic/v2", help="출력 폴더")
    ap.add_argument("--exclude", default="", help="제외할 drug_pool.json (쉼표 구분)")
    args = ap.parse_args()

    global OUT
    OUT = Path(args.out)
    OUT.mkdir(parents=True, exist_ok=True)

    rng = random.Random(args.seed)
    skip = {d["item_seq"] for f in filter(None, args.exclude.split(",")) for d in json.loads(Path(f).read_text(encoding="utf-8"))}
    pool = await load_pool(args.pool, rng, skip)
    (OUT / "drug_pool.json").write_text(json.dumps(pool, ensure_ascii=False, indent=1), encoding="utf-8")
    n_q = 0
    with (OUT / "match_eval.jsonl").open("w", encoding="utf-8") as f:
        for d in pool:
            for kind, q in d["forms"].items():
                f.write(json.dumps({"query": q, "variant": kind, "truth_item_seq": d["item_seq"],
                                    "truth_item_name": d["item_name"]}, ensure_ascii=False) + "\n")
                n_q += 1
    recs = [make_prescription(i, pool, rng) for i in range(1, args.records + 1)]
    (OUT / "prescriptions.json").write_text(json.dumps(recs, ensure_ascii=False, indent=1), encoding="utf-8")
    used = {it["truth_item_seq"] for r in recs for it in r["drugs"]}
    print(f"매칭 평가 질의 {n_q}개, 가상 처방 {len(recs)}건, 처방에 쓰인 약 {len(used)}종")
    print(f"저장: {OUT}/ (GitHub 제외)")


if __name__ == "__main__":
    asyncio.run(main())