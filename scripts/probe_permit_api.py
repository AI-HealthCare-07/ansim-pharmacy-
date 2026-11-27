"""읽기 전용: 허가정보 API(DrugPrdtPrmsnInfoService08)가 DUR 품목정보에 없는 약의
효능·용법·주의사항 문서(EE/UD/NB_DOC_DATA)와 주성분 정보를 주는지 필드 확인.
DB 접근 없음. 키는 출력하지 않음."""
import os, json, sys, ssl, urllib.parse, urllib.request
import certifi
CTX = ssl.create_default_context(cafile=certifi.where())

key = os.getenv("DATA_GO_KR_API_KEY")
if not key:
    sys.exit("DATA_GO_KR_API_KEY 없음 (set -a; source .env; set +a)")
BASE = "https://apis.data.go.kr/1471000/DrugPrdtPrmsnInfoService08/"
ITEMS = ["199900910", "201403884", "201309919"]

def call(op, **p):
    q = {"serviceKey": key, "pageNo": 1, "numOfRows": 3, "type": "json", **p}
    url = BASE + op + "?" + urllib.parse.urlencode(q)
    try:
        with urllib.request.urlopen(url, timeout=30, context=CTX) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        return "ERR", str(e)[:300].replace(key, "***")

for op in ["getDrugPrdtPrmsnDtlInq08", "getDrugPrdtMcpnDtlInq08"]:
    for it in ITEMS:
        st, body = call(op, item_seq=it)
        print(f"\n=== {op} item_seq={it} HTTP {st}")
        try:
            j = json.loads(body)
            b = j.get("body", {})
            print("totalCount:", b.get("totalCount"))
            items = b.get("items") or []
            if items:
                row = items[0] if isinstance(items, list) else items
                row = row.get("item", row) if isinstance(row, dict) else row
                for k, v in row.items():
                    s = str(v) if v is not None else ""
                    print(f"  {k}: {'(비어있음)' if not s else s[:60].replace(chr(10),' ')+('…' if len(s)>60 else '')} [len={len(s)}]")
            else:
                print("  items 없음:", body[:300].replace(key, "***"))
        except Exception:
            print("  JSON 아님:", body[:300].replace(key, "***"))
