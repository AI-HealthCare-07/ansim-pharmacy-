"""매칭 규칙을 DB만으로 시험한다(Claude·서버 호출 없음, 저장 없음).

사용법(프로젝트 폴더에서):
  set -a; source .env; set +a
  PYTHONPATH=. python3 scripts/try_match.py
  PYTHONPATH=. python3 scripts/try_match.py "지르텍정 10mg" "타이레놀정500mg"
"""
import asyncio
import os
import sys

import asyncpg

from app.services.matching import match_one

DEFAULTS = ["지르텍정 10mg", "타이레놀정500mg", "코러스레보설피리드정", "아목시실린캡슐500mg", "라모진정100밀리그람"]


class Conn:
    def __init__(self, c):
        self.c = c

    async def execute_query_dict(self, sql, values=None):
        return [dict(r) for r in await self.c.fetch(sql, *(values or []))]


async def main(names):
    c = await asyncpg.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"), port=int(os.getenv("POSTGRES_PORT", "5432")),
        user=os.environ["POSTGRES_USER"], password=os.getenv("POSTGRES_PASSWORD"),
        database=os.environ["POSTGRES_DB"])
    conn = Conn(c)
    for n in names:
        m = await match_one(conn, {"name": n})
        print(f"\n== {n}\n   결과: {m['kind']}  선택={m['matched_item_seq']}  점수={m['match_score']}")
        for x in m["candidates"]:
            print(f"   - {x['score']:.3f}  {x['item_name'][:28]}  성분={str(x['ingredient'])[:20]}  성분코드={'O' if x['has_ingr_code'] else 'X'}")
    await c.close()


asyncio.run(main(sys.argv[1:] or DEFAULTS))
