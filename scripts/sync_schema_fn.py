"""패치 파일의 함수 정의를 infra/db/schema.sql의 같은 함수에 반영한다.

DB에만 고치면 다음에 schema.sql을 다시 적용할 때 옛 함수로 돌아가므로, 패치 후 꼭 실행한다.
사용법: python scripts/sync_schema_fn.py infra/db/patches/<패치>.sql <함수이름>
"""
import re
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    patch, fn = Path(sys.argv[1]), sys.argv[2]
    body = patch.read_text(encoding="utf-8")
    if "BEGIN;\n" in body:
        body = body.split("BEGIN;\n", 1)[1]
    body = body.rsplit("COMMIT;", 1)[0].strip()
    schema = Path("infra/db/schema.sql")
    s = schema.read_text(encoding="utf-8")
    pat = re.compile(r"CREATE OR REPLACE FUNCTION (?:public\.)?" + re.escape(fn) + r"\(.*?\n\$\$;", re.S)
    n = len(pat.findall(s))
    print("schema.sql에서 찾은 개수:", n)
    if n != 1:
        print("바꾸지 않았어요. 함수가 정확히 하나일 때만 바꿔요.")
        sys.exit(1)
    schema.write_text(pat.sub(lambda m: body, s, count=1), encoding="utf-8")
    print("schema.sql 반영 완료:", fn)


if __name__ == "__main__":
    main()
