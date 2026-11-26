"""5번 평가(v2): match_eval.jsonl의 질의를 fn_search_medicines로 찾아 정답(item_seq)과 비교한다.

- 1등 정확도: 1등이 정답이거나 정답과 같은 이름(제조사만 다른 동명 제품)
- 자동 확인: 1등 0.7 이상이고 2등과 동점 아님
- 자동 확인 정밀도: 자동 확인된 것 중 맞은 비율 (안전 지표, 높아야 함)
사용법: python scripts/eval_matching.py [--limit 0]
"""
import argparse
import asyncio
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tortoise import Tortoise, connections  # noqa: E402

from app.core.db.databases import TORTOISE_ORM  # noqa: E402

EVAL = Path("data/synthetic/v2/match_eval.jsonl")
AUTO = 0.7
GAP = 0.15  # 1등과 2등 점수 차이가 이보다 작으면 사람이 확인


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="0이면 전부")
    args = ap.parse_args()
    qs = [json.loads(line) for line in EVAL.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.limit:
        qs = qs[: args.limit]
    await Tortoise.init(config=TORTOISE_ORM)
    conn = connections.get("default")
    stats = defaultdict(lambda: {"n": 0, "top1": 0, "auto": 0, "auto_ok": 0, "none": 0})
    wrong_auto = []
    for i, q in enumerate(qs, 1):
        c = await conn.execute_query_dict(
            "SELECT s.item_seq::text AS seq, s.item_name, s.score::float AS score FROM fn_search_medicines($1, 5) s",
            [q["query"]])
        ok = bool(c) and (c[0]["seq"] == q["truth_item_seq"] or c[0]["item_name"] == q["truth_item_name"])
        auto = bool(c) and c[0]["score"] >= AUTO and (len(c) == 1 or c[0]["score"] - c[1]["score"] >= GAP)
        for key in ("전체", q["variant"]):
            s = stats[key]
            s["n"] += 1
            s["top1"] += ok
            s["auto"] += auto
            s["auto_ok"] += auto and ok
            s["none"] += not c
        if auto and not ok:
            wrong_auto.append((q["query"], q["truth_item_name"], c[0]["item_name"], c[0]["score"]))
        if i % 200 == 0:
            print(f"  {i}/{len(qs)}")
    await Tortoise.close_connections()

    def pct(a, b):
        return f"{(100 * a / b):.1f}%" if b else "-"

    lines = [f"# 약 매칭 평가 v2 ({date.today()})", "",
             f"- 질의 {len(qs)}개 (DB 정상 의약품에서 뽑은 약의 여러 표기), 함수: fn_search_medicines",
             f"- 자동 확인 규칙: 1등 {AUTO} 이상이고 2등과 {GAP} 이상 차이", "",
             "| 표기 | 질의 수 | 1등 정확도 | 자동 확인 비율 | 자동 확인 정밀도 | 후보 없음 |", "|---|---|---|---|---|---|"]
    for key in ["전체", "full", "spaced", "brand_only", "ocr_noise"]:
        if key in stats:
            s = stats[key]
            lines.append(f"| {key} | {s['n']} | {pct(s['top1'], s['n'])} | {pct(s['auto'], s['n'])} | "
                         f"{pct(s['auto_ok'], s['auto'])} | {s['none']} |")
    lines += ["", f"## 자동 확인인데 틀린 경우 ({len(wrong_auto)}건, 최대 20건 표시)", "",
              "| 질의 | 정답 | 1등 | 점수 |", "|---|---|---|---|"]
    lines += [f"| {a} | {b} | {c} | {d:.3f} |" for a, b, c, d in wrong_auto[:20]]
    text = "\n".join(lines) + "\n"
    print(text)
    out = Path(f"docs/review/match_eval_v2_{date.today().strftime('%y%m%d')}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print("저장:", out)


if __name__ == "__main__":
    asyncio.run(main())