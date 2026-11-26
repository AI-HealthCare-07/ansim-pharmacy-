# 마이 복약 큐레이터 (안심 약국)

## 디자인
화면(HTML·CSS·JS), 보고서, 시각 자료를 만들 때는 항상 DESIGN.md의 색·글꼴·컴포넌트·문구 규칙을 따른다.

@DESIGN.md

## 디자인 도우미 (외부 AI CLI)
설치 위치: `~/.local/bin` (codex, gemini). 로그인은 사용자가 직접 한다 (`codex login`, `gemini` 첫 실행).

- **Gemini — 디자인 2차 의견:** 화면·보고서 시안을 만든 뒤 DESIGN.md 준수 여부, 가독성, 고령 사용자 관점 검토를 받는다.
  `gemini -p "DESIGN.md 기준으로 이 HTML의 색·글꼴·대비·접근성 문제를 지적해 줘: @reports/파일.html"`
- **Codex — UI 코드 검토·구현 보조:** 화면 코드 리뷰나 대안 구현을 받는다. 결과는 그대로 쓰지 말고 검토 후 반영한다.
  `codex exec "DESIGN.md를 따라 <작업>을 검토해 줘"` / `codex review`
- 외부 AI에는 개인 진료기록·처방전 원본 등 민감정보를 보내지 않는다 (SYS-005).
