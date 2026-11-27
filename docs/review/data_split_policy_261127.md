# 데이터 3분화와 테스트용 데이터 차단 (2026-11-27)

## 목적
테스트용 데이터를 개발·조정·검증 과정에서 한 번이라도 쓰면 최종 정확도 숫자를 믿을 수 없다. 그래서 묶음을 나누고 테스트용은 잠가 둔다.

## 3분화 (이 서비스는 자체 모델을 학습하지 않으므로 "학습" 대신 "개발(튜닝)"이라 부른다)
| 묶음 | 폴더 | 용도 | 상태 |
|---|---|---|---|
| 개발(dev) | data/synthetic/v2 (600종·2,000 처방) | 규칙·기준값을 조정한다. 얼마든지 열어 본다 | 있음 |
| 검증(validation) | data/synthetic/v2_val | 조정을 끝낸 뒤 "좋아졌는가"를 고정된 자료로 확인한다. 조정에는 쓰지 않는다 | **아직 없음.** 아래 명령으로 만든다 |
| 테스트(test) | data/synthetic/v2_test (3,000종·10,674 질의) | 규칙을 확정한 뒤 12/21에 **1회만** 채점한다 | 있음, **잠금** |

세 묶음은 약이 겹치지 않는다(개발·테스트 겹침 0 확인). 목록은 `data/synthetic/splits_manifest.json`에 적어 뒀다.
테스트용 폴더를 열지 않고도 새 묶음을 겹치지 않게 만들 수 있다.

## 차단 장치 (세 겹)
1. **폴더 권한 잠금**: data/synthetic/v2_test 를 열 수 없게 만든다.
   - 파일 먼저, 폴더 나중: `chmod a-rwx data/synthetic/v2_test/* && chmod a-rwx data/synthetic/v2_test`
2. **코드 차단**: `scripts/data_guard.py`의 `assert_not_protected()`가 테스트용 경로를 열려는 시도를 멈춘다.
   `scripts/eval_matching.py`(평가)와 `scripts/build_synthetic_v2.py`(생성의 --out·--exclude)에 연결했다.
   새 스크립트가 데이터를 읽으면 같은 함수를 먼저 부른다.
3. **점검 스크립트**: `python scripts/check_test_isolation.py`가 (가) 허용 목록 밖에서 v2_test를 가리키는 곳,
   (나) 폴더가 열려 있는지, (다) 묶음 사이에 겹치는 약이 있는지를 본다. 커밋 전에 돌린다.

해제하는 코드는 일부러 만들지 않았다.

## 해제 절차 (12/21 최종 채점 때만)
1. 결정 기록에 "규칙 확정, 최종 채점 실시"를 먼저 쓴다.
2. 사람이 직접 권한을 푼다(chmod u+rwx)와 data_guard.py의 PROTECTED에서 해당 경로를 뺀다.
3. 채점은 1회만 하고 결과를 기록한 뒤 다시 잠근다. 결과를 보고 규칙을 고치지 않는다(고치면 이 묶음은 더 이상 테스트가 아니다).

## 검증용 묶음 만들기 (DB 필요, 선생님이 실행)
```
PYTHONPATH=. .venv/bin/python scripts/build_synthetic_v2.py --pool 600 --records 2000 --seed 101 \
  --out data/synthetic/v2_val --exclude-manifest
```
만든 뒤 manifest의 validation.item_seq도 채워야 한다(다음에 같이 한다).

## 지금까지 확인된 것
- 테스트용 데이터를 만든 뒤(11/26) 평가·조정에 쓴 흔적은 없다(11/27 점검). 다만 증명 범위는 그때 확인한 범위다.
- data/ 폴더는 git에서 제외돼 있어 테스트용 파일은 저장소에 올라가지 않는다.
