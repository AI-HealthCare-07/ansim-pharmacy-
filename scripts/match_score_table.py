"""5번(DOC-004): 가상 데이터의 약 이름 20개를 fn_search_medicines로 매칭해 점수 표를 만든다.

자동 확인 규칙: 1등 점수 0.7 이상이고 2등과 동점이 아닐 때만. 동점·0.7 미만은 사용자 확인.
사용법: python scripts/match_score_table.py  (프로젝트 맨 위 폴더에서)
"""
import asyncio
import csv
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tortoise import Tortoise, connections  # noqa: E402

from app.core.db.databases import TORTOISE_ORM  # noqa: E402

META = Path("data/synthetic/kr_medical_3200_complete_metadata.json")
N_SAMPLES = 20
AUTO_THRESHOLD = 0.7


def pick_samples(records: list[dict]) -> list[tuple[str, str]]:
    """카테고리별로 돌아가며 서로 다른 약 이름을 고른다."""
    by_cat: dict[str, list[str]] = defaultdict(list)
    for r in records:
        for d in r.get("drugs", []):
            name = (d.get("name") or "").strip()
            if name and name not in by_cat[r.get("category_code", "?")]:
                by_cat[r.get("category_code", "?")].append(name)
    picked, seen = [], set()
    cats = sorted(by_cat)
    while len(picked) < N_SAMPLES and any(by_cat[c] for c in cats):
        for c in cats:
            while by_cat[c]:
                name = by_cat[c].pop(0)
                if name not in seen:
                    seen.add(name)
                    picked.append((c, name))
                    break
            if len(picked) >= N_SAMPLES:
                break
    return picked


async def main() -> None:
    records = json.loads(META.read_text(encoding="utf-8"))
    samples = pick_samples(records)
    await Tortoise.init(config=TORTOISE_ORM)
    conn = connections.get("default")
    rows = []
    for cat, name in samples:
        cands = await conn.execute_query_dict(
            "SELECT s.item_name, s.score::float AS score,"
            " (position(fn_norm_drug_name($1) in fn_norm_drug_name(s.item_name)) > 0 OR fn_norm_drug_name(s.item_name) = regexp_replace(fn_norm_drug_name($1), '[0-9][0-9./]*(mg|mcg|g|ml|iu)?$', '', 'i')) AS contains"
            " FROM fn_search_medicines($1, 5) s", [name])
        top = cands[0] if cands else None
        second = cands[1]["score"] if len(cands) > 1 else None
        tie = top is not None and second is not None and abs(top["score"] - second) < 1e-9
        auto = top is not None and top["score"] >= AUTO_THRESHOLD and not tie
        rows.append({
            "category": cat, "query": name,
            "top_item": top["item_name"] if top else "",
            "top_score": round(top["score"], 3) if top else 0.0,
            "second_score": round(second, 3) if second is not None else "",
            "candidates": len(cands), "tie": tie, "auto_confirm": auto,
            "top_contains_query": bool(top and top["contains"]),
        })
    await Tortoise.close_connections()

    n = len(rows)
    auto_n = sum(r["auto_confirm"] for r in rows)
    tie_n = sum(r["tie"] for r in rows)
    none_n = sum(r["candidates"] == 0 for r in rows)
    right_n = sum(r["top_contains_query"] for r in rows)
    wrong_auto = [r for r in rows if r["auto_confirm"] and not r["top_contains_query"]]

    print(f"{'분류':<5} {'검색어':<22} {'1등':>6} {'2등':>6} {'동점':<3} {'자동':<3} 1등 후보")
    for r in rows:
        print(f"{r['category']:<5} {r['query'][:20]:<22} {r['top_score']:>6} {str(r['second_score']):>6} "
              f"{'Y' if r['tie'] else '-':<3} {'Y' if r['auto_confirm'] else '-':<3} {r['top_item'][:40]}")
    print(f"\n표본 {n}개 | 자동 확인 {auto_n} | 동점 {tie_n} | 후보 없음 {none_n} | 1등이 검색어 포함 {right_n}")
    print("자동 확인인데 1등이 검색어를 포함하지 않는 경우(오매칭 의심):", [r["query"] for r in wrong_auto] or "없음")

    today = date.today().strftime("%y%m%d")
    Path("data/reports").mkdir(parents=True, exist_ok=True)
    csv_path = Path(f"data/reports/match_scores_{today}.csv")
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    md_path = Path(f"docs/review/match_scores_{today}.md")
    md_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# 약 연결 점수 표 ({date.today()})", "",
             f"- 표본: 가상 데이터 {n}개 약 이름(카테고리별 고르게), 함수: fn_search_medicines",
             f"- 자동 확인 규칙: 1등 {AUTO_THRESHOLD} 이상이고 2등과 동점 아님",
             f"- 결과: 자동 확인 {auto_n}, 동점 {tie_n}, 후보 없음 {none_n}, 1등이 검색어 포함 {right_n}",
             f"- 오매칭 의심(자동 확인인데 1등이 검색어 미포함): {', '.join(r['query'] for r in wrong_auto) or '없음'}",
             "", "| 분류 | 검색어 | 1등 점수 | 2등 점수 | 동점 | 자동 확인 | 1등 후보 |", "|---|---|---|---|---|---|---|"]
    lines += [f"| {r['category']} | {r['query']} | {r['top_score']} | {r['second_score']} | "
              f"{'Y' if r['tie'] else ''} | {'Y' if r['auto_confirm'] else ''} | {r['top_item']} |" for r in rows]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n저장: {csv_path} (GitHub 제외), {md_path}")


if __name__ == "__main__":
    asyncio.run(main())
