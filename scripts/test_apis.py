import os
import sys
from pathlib import Path
from dotenv import dotenv_values
import httpx

# Load .env file directly
env_path = Path(__file__).resolve().parent.parent / ".env"
env_vars = dotenv_values(env_path) if env_path.exists() else {}

print(f"=== [외부 API 키 연동 테스트] ===")
print(f"참조 .env 경로: {env_path}\n")

results = {}

# 1. OpenAI API 검증
openai_key = os.getenv("OPENAI_API_KEY") or env_vars.get("OPENAI_API_KEY")
if not openai_key:
    results["OpenAI"] = {
        "status": "FAIL",
        "reason": "환경변수 OPENAI_API_KEY 누락 (.env 파일에 미등록)",
        "solution": ".env 파일에 'OPENAI_API_KEY=sk-...' 형식으로 등록 필요"
    }
else:
    try:
        resp = httpx.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {openai_key}"},
            timeout=10.0
        )
        if resp.status_code == 200:
            results["OpenAI"] = {"status": "SUCCESS", "message": "API 키 인증 성공 및 응답 수신 완료"}
        else:
            results["OpenAI"] = {
                "status": "FAIL",
                "reason": f"HTTP {resp.status_code}: {resp.text}",
                "solution": "OpenAI API 키 유효성 및 크레딧 잔액 확인 필요"
            }
    except Exception as e:
        results["OpenAI"] = {"status": "ERROR", "reason": str(e), "solution": "네트워크 연결 확인 필요"}

# 2. Anthropic (Claude) API 검증
anthropic_key = os.getenv("ANTHROPIC_API_KEY") or env_vars.get("ANTHROPIC_API_KEY") or env_vars.get("CLAUDE_API_KEY")
if not anthropic_key:
    results["Claude (Anthropic)"] = {
        "status": "FAIL",
        "reason": "환경변수 ANTHROPIC_API_KEY 누락 (.env 파일에 미등록)",
        "solution": ".env 파일에 'ANTHROPIC_API_KEY=sk-ant-...' 형식으로 등록 필요"
    }
else:
    try:
        resp = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": anthropic_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": "claude-3-haiku-20240307",
                "max_tokens": 10,
                "messages": [{"role": "user", "content": "ping"}]
            },
            timeout=10.0
        )
        if resp.status_code == 200:
            results["Claude (Anthropic)"] = {"status": "SUCCESS", "message": "API 키 인증 성공 및 응답 수신 완료"}
        else:
            results["Claude (Anthropic)"] = {
                "status": "FAIL",
                "reason": f"HTTP {resp.status_code}: {resp.text}",
                "solution": "Anthropic API 키 유효성 및 크레딧 상태 확인 필요"
            }
    except Exception as e:
        results["Claude (Anthropic)"] = {"status": "ERROR", "reason": str(e), "solution": "네트워크 연결 확인 필요"}

# 3. Naver Cloud CLOVA OCR API 검증
clova_url = os.getenv("CLOVA_OCR_APIGW_URL") or env_vars.get("CLOVA_OCR_APIGW_URL")
clova_secret = os.getenv("CLOVA_OCR_SECRET_KEY") or env_vars.get("CLOVA_OCR_SECRET_KEY")
if not clova_secret or not clova_url:
    missing = []
    if not clova_secret:
        missing.append("CLOVA_OCR_SECRET_KEY")
    if not clova_url:
        missing.append("CLOVA_OCR_APIGW_URL")
    results["CLOVA OCR"] = {
        "status": "FAIL",
        "reason": f"환경변수 누락: {', '.join(missing)} (.env 파일에 미등록)",
        "solution": ".env 파일에 CLOVA_OCR_SECRET_KEY와 CLOVA_OCR_APIGW_URL 등록 필요"
    }
else:
    try:
        resp = httpx.post(
            clova_url,
            headers={
                "X-OCR-SECRET": clova_secret,
                "Content-Type": "application/json"
            },
            json={
                "images": [],
                "requestId": "health-check",
                "version": "V2",
                "timestamp": 0
            },
            timeout=10.0
        )
        # Secret key check: 400 with invalid json/images indicates valid secret, while 401/403 means auth fail
        if resp.status_code in (200, 400):
            results["CLOVA OCR"] = {"status": "SUCCESS", "message": f"인증 성공 (상태코드: {resp.status_code})"}
        else:
            results["CLOVA OCR"] = {
                "status": "FAIL",
                "reason": f"HTTP {resp.status_code}: {resp.text}",
                "solution": "CLOVA OCR APIGW URL 및 Secret Key 유효성 확인 필요"
            }
    except Exception as e:
        results["CLOVA OCR"] = {"status": "ERROR", "reason": str(e), "solution": "네트워크 또는 URL 확인 필요"}

# 4. 공공데이터포털 API 검증 (의약품개요정보 표준 API 예시)
data_go_key = os.getenv("DATA_GO_KR_API_KEY") or env_vars.get("DATA_GO_KR_API_KEY") or env_vars.get("PUBLIC_DATA_PORTAL_KEY")
if not data_go_key:
    results["공공데이터포털"] = {
        "status": "FAIL",
        "reason": "환경변수 DATA_GO_KR_API_KEY 누락 (.env 파일에 미등록)",
        "solution": ".env 파일에 'DATA_GO_KR_API_KEY=...' 형식으로 디코딩/인코딩 키 등록 필요"
    }
else:
    try:
        # e약은요 의약품 개요정보 서비스 ping
        test_url = "http://apis.data.go.kr/1471000/DrbEasyDrugInfoService/getDrbEasyDrugList"
        resp = httpx.get(
            test_url,
            params={"serviceKey": data_go_key, "pageNo": 1, "numOfRows": 1, "type": "json"},
            timeout=10.0
        )
        if resp.status_code == 200 and "SERVICE_KEY_IS_NOT_REGISTERED_ERROR" not in resp.text:
            results["공공데이터포털"] = {"status": "SUCCESS", "message": "공공데이터포털 API 호출 및 인증 성공"}
        else:
            results["공공데이터포털"] = {
                "status": "FAIL",
                "reason": f"응답: {resp.text[:200]}",
                "solution": "공공데이터포털 활용신청 상태(승인 여부 1~2시간 소요) 및 Decoding Key 확인 필요"
            }
    except Exception as e:
        results["공공데이터포털"] = {"status": "ERROR", "reason": str(e), "solution": "공공데이터포털 서버 연결 확인 필요"}

for service, res in results.items():
    print(f"[{res['status']}] {service}")
    if res["status"] == "SUCCESS":
        print(f"  -> {res.get('message')}")
    else:
        print(f"  -> 원인: {res.get('reason')}")
        print(f"  -> 해결방법: {res.get('solution')}")
    print()
