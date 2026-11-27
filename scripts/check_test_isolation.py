"""테스트용 데이터 분리 점검(읽기 전용). 커밋 전에 돌린다.

1) 코드·문서가 테스트용 폴더(v2_test)를 가리키는 곳이 허용 목록 밖에 없는지
2) 테스트용 폴더가 실제로 잠겨 있는지(열리면 경고)
3) 개발용·테스트용 약 목록이 겹치지 않는지(manifest 기준, 테스트용 폴더는 열지 않는다)
사용: python scripts/check_test_isolation.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOW = {  # 테스트용을 언급해도 되는 파일(차단·기록용)
    "scripts/data_guard.py", "scripts/check_test_isolation.py", "scripts/build_synthetic_v2.py",
    "docs/review/data_split_policy_261127.md", "docs/plan_261127.md", "docs/2026-11-26.md",
    "docs/review/decision_261127_classification_principle.md", "docs/review/data_inventory_261127.md",
}
SKIP_DIRS = {".venv", ".git", "node_modules", "data", "__pycache__"}
problems = []

for dp, dns, fns in os.walk(ROOT):
    dns[:] = [d for d in dns if d not in SKIP_DIRS]
    for fn in fns:
        if not fn.endswith((".py", ".md", ".sh", ".sql", ".toml", ".yml", ".yaml", ".json")):
            continue
        rel = str((Path(dp) / fn).relative_to(ROOT))
        if rel in ALLOW:
            continue
        try:
            text = (Path(dp) / fn).read_text(encoding="utf-8")
        except Exception:
            continue
        if re.search(r"v2_test", text):
            problems.append(f"허용 목록 밖에서 v2_test를 가리킴: {rel}")

t = ROOT / "data" / "synthetic" / "v2_test"
if t.exists():
    try:
        os.listdir(t)  # 실제로 열어 보는 것이 가장 정확하다(권한 표시만으로는 속을 수 있다)
        problems.append("테스트용 폴더가 열려 있어요. 잠그세요(파일 먼저, 폴더 나중):\n"
                        "  chmod a-rwx data/synthetic/v2_test/* && chmod a-rwx data/synthetic/v2_test")
    except PermissionError:
        pass  # 잠겨 있음(정상)

man = ROOT / "data" / "synthetic" / "splits_manifest.json"
if man.exists():
    m = json.loads(man.read_text(encoding="utf-8"))["splits"]
    names = list(m)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            both = set(m[a]["item_seq"]) & set(m[b]["item_seq"])
            if both:
                problems.append(f"{a}와 {b}의 약이 {len(both)}종 겹침")
else:
    problems.append("splits_manifest.json이 없어요")

print("\n".join(["문제 있음:"] + problems) if problems else "이상 없음: 테스트용 데이터는 잠겨 있고 어디서도 쓰이지 않아요")
sys.exit(1 if problems else 0)
