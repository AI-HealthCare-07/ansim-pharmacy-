"""테스트용 데이터 접근 차단 장치 (결정 기록: docs/review/data_split_policy_261127.md).

- 개발(dev) / 검증(validation) / 테스트(test) 3분화. 테스트용은 최종 1회 채점 전까지 열지 않는다.
- 이 파일은 표준 라이브러리만 쓴다. 데이터를 읽는 스크립트는 읽기 전에 assert_not_protected(경로)를 부른다.
- 해제하는 코드는 일부러 두지 않았다. 해제는 결정 기록 + 이 파일의 PROTECTED 수정 + 폴더 권한 복구를 사람이 직접 한다.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROTECTED = [ROOT / "data" / "synthetic" / "v2_test", ROOT / "data" / "synthetic" / "v2_test_b"]
MANIFEST = ROOT / "data" / "synthetic" / "splits_manifest.json"


def assert_not_protected(path) -> Path:
    """테스트용 폴더 안의 경로면 멈춘다. 상대 경로와 심볼릭 링크도 풀어서 비교한다."""
    p = Path(path).expanduser()
    p = (p if p.is_absolute() else Path.cwd() / p).resolve()
    for guarded in PROTECTED:
        g = guarded.resolve()
        if p == g or g in p.parents:
            raise SystemExit(
                f"[차단] 테스트용 데이터는 열 수 없어요: {path}\n"
                "최종 채점 전까지 학습·검증·튜닝에 쓰지 않기로 했어요(docs/review/data_split_policy_261127.md)."
            )
    return p


def known_item_seqs(splits=("dev", "test")) -> set[str]:
    """이미 어느 묶음에 들어간 약(item_seq) 목록. 새 묶음을 겹치지 않게 만들 때 쓴다.
    테스트용 폴더를 열지 않고 manifest에 적어 둔 목록만 읽는다."""
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {s for name in splits for s in man["splits"][name]["item_seq"]}
