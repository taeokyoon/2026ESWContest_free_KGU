# ai — AI/Data 담당

CAN 트래픽 이상탐지 모델의 데이터 전처리·학습·경량화를 담당하는 영역입니다.

- `notebooks/` — Colab에서 작업한 `.ipynb` 파일
- `data/` — 데이터셋 (원본 파일은 `.gitignore`로 제외, 다운로드 방법만 문서화)
- `models/` — 학습 완료 모델 (`.h5`, `.tflite` 등)
- `export/` — X-CUBE-AI로 변환한 C 코드 산출물. firmware 팀과의 인터페이스 지점 (자세한 내용은 `export/README.md` 참고)

## 데이터셋

**Car Hacking: Attack & Defense Challenge 2020** (현대 아반떼 CN7, Flooding/Spoofing/Replay/Fuzzing 4종)
- 다운로드: [IEEE DataPort](https://ieee-dataport.org/open-access/car-hacking-attack-defense-challenge-2020-dataset) (무료, IEEE 계정 필요)
- 형식: CSV (Timestamp, Arbitration_ID, DLC, Data, Class, SubClass)

## 진행 단계

- [x] 1. 데이터셋 다운로드 (IEEE DataPort)
- [x] 2. Colab 환경 세팅 (Google Drive 업로드 → 마운트 → 노트북 생성, T4 GPU)
- [x] 3. 탐색적 데이터 분석(EDA) — Class/SubClass 분포, CAN ID·DATA 값 패턴 확인
- [x] 4. 전처리 설계 — 윈도우(32개 프레임) 단위 입력으로 결정
- [x] 5. 모델 선정 및 학습 — 경량 오토인코더 (v5로 확정, 아래 실험 기록 참고)
- [ ] 6. X-CUBE-AI 변환 — 학습된 모델을 `export/`에 C 코드로 산출 → firmware 팀 전달 (일시 중단, 아래 "X-CUBE-AI 변환 진행 상황" 참고)

임베디드팀(2명)은 1~6번과 병행해 CAN 수신 로직·OLED/부저 출력을 먼저 구현하며, `export/`에 결과물이 올라오는 시점에 통합한다.

## 실험 기록 (Colab 노트북 진행 상황)

### EDA 결과
- 전체 3,672,151행 (Pre_train_D/S 0~2 6개 파일 병합)
- `Class`: Normal 3,372,743 (91.8%) / Attack 299,408 (8.2%)
- `SubClass`: Flooding 154,180 / Fuzzing 89,879 / Replay 47,593 / Spoofing 7,756 — Spoofing이 가장 희소(가장 탐지 어려운 유형)
- 고유 CAN ID 81개, 핵심 컬럼 결측치 없음
- **버그 발견 및 수정**: `SubClass`가 파일마다 정상 행을 `"Normal"` 문자열 또는 `NaN`으로 다르게 표기 → `fillna('Normal')`로 통일

### 전처리 설계
- **윈도우 크기 32** (2의 거듭제곱, MCU 링버퍼 구현 용이 + RAM/속도 예산에 여유)
- **윈도우는 파일 경계를 넘지 않도록 구성** (`boundaries` 배열로 6개 파일 구간을 구분 후 구간 내에서만 슬라이싱) — 서로 다른 녹화 세션이 섞이는 걸 방지
- 윈도우 라벨: 32개 프레임 중 하나라도 Attack이면 해당 윈도우를 Attack으로 표시
- 프레임 → 숫자 변환: **처음엔 Arbitration_ID를 원-핫(81차원)으로 인코딩했으나, 윈도우 입력 차원이 2,880까지 커져 첫 레이어만 738KB(Flash 128KB 초과) → ID를 정규화된 스칼라 값 하나로 변경**해 프레임당 특성을 10개(ID, DLC, DATA 8바이트)로 축소
- 결과: 정상 윈도우 72,139개(학습 57,711 / 검증 14,428), 공격 윈도우 42,612개(테스트 전용)

### 모델 v1 — 실패 원인 분석 완료
- 구조: Dense 320→32→8→32→320 (21,384 파라미터, 83.53KB, 8bit 양자화 시 Flash 예산 내)
- 학습 30epoch, loss/val_loss 0.09→0.075로 과적합 없이 수렴
- 임계값(정상 95백분위) 기준 **전체 탐지율 18.95%, 오탐률 5%** — 유형별 분해 결과:
  - Flooding 0.50% / Fuzzing 57.60% / Replay 6.43% / Spoofing 6.45%
- **원인**: 특성에 타이밍 정보(Timestamp)가 전혀 없음 → Flooding(빈도 기반 공격)은 프레임 내용만으론 정상과 완전히 동일해 탐지 불가. Replay는 정의상 과거 정상 프레임을 그대로 재전송하므로 내용 기반 탐지가 원리적으로 불가능
- 채점 방식(평균 vs 최댓값 vs top-3 평균) 튜닝을 시도했으나 개선 없음 — 평균(mean) 방식이 오히려 가장 나음. **결론: 채점 방식이 아니라 특성 자체에 정보가 부족한 게 근본 원인**

### 모델 v2 — `delta_t` 추가했으나 효과 없음
- `delta_t`(직전 프레임과의 시간 간격, 파일 경계 내에서 계산) 특성 추가 → 프레임당 11개, 윈도우 입력 352차원
- Flooding 탐지율 0.50% → 0.69%, 사실상 개선 없음
- **원인 진단**: `delta_t`를 "바로 이전 프레임과의 간격(아무 ID나 상관없이)"으로 계산했더니, Flooding 구간(중앙값 0.00024s)과 정상 구간(중앙값 0.00024s)이 거의 동일 — CAN 버스가 정상 상태에서도 이미 포화(약 500kbps에서 프레임 전송 물리 한계 시간과 일치)에 가까워서, 이 특성은 "버스가 얼마나 바쁜가"만 측정할 뿐 특정 메시지의 빈도 이상은 잡지 못함

### 모델 v3 — `id_delta_t`로 교체, 여전히 효과 없음
- `delta_t`를 "**동일 CAN ID가 재등장하는 간격**"(`groupby(['file_id','Arbitration_ID'])['Timestamp'].diff()`)으로 교체 — 윈도우 차원은 352 그대로
- 실제 신호 확인: Flooding 구간 중앙값 741µs vs 정상 구간 중앙값 10.25ms → **14배 차이로 신호 자체는 명확히 존재**
- 그런데도 Flooding 탐지율 1.39%로 거의 그대로 — "특성에 신호가 있는데 모델이 못 씀"이라는 모순적 상황
- 채점 방식(mean/max/top-3 평균) 재실험 → mean이 여전히 최선, 병목은 아님
- 데이터 부족 가설도 배제: train/val loss가 거의 같은 곡선으로 수렴(과적합 없음) → 데이터량 문제가 아니라 용량/구조 문제로 진단

### 모델 v4 — 병목 확장, 소폭 개선에 그침
- 병목 8→16, 첫 레이어 32→64 (파라미터 21,384→47,600, 83.53KB→185.94KB)
- loss 0.068→0.063로 소폭 개선, Flooding 탐지율 1.39%→2.41% — **병목 용량도 핵심 원인이 아니라고 결론**

### 모델 v5 — 원인 발견 및 해결 (최종 확정)
- **가설**: Dense 오토인코더는 윈도우를 통째로 flatten하기 때문에 "위치 불변성"이 없음. `id_delta_t`처럼 프레임마다 다른 위치에 흩어지는 특성은 MLP가 학습하기 매우 어려움
- **해결**: 윈도우 32프레임 전체를 한 번에 요약하는 **윈도우 단위 집계 특성 2개** 추가 (항상 같은 위치, 위치 불변적)
  - `unique_id_ratio` = 윈도우 내 서로 다른 CAN ID 개수 / 32 → Flooding처럼 한 ID가 도배하면 급감
  - `max_repeat_ratio` = 윈도우 내 가장 많이 반복된 ID의 비율 → Flooding에서 급증
  - 윈도우 입력 차원 352 → **354**
- 354차원 전체로 채점하니 Flooding 2.88%로 여전히 미미 → **2차 진단**: 새 특성 2개가 전체 354차원 평균에 희석됨(신호가 2/354만큼만 반영)
- **검증**: 마지막 2차원만 따로 채점 → Flooding 탐지율 **99.96%**로 폭증 → 특성은 처음부터 맞았고, "평균 오차 하나로 채점"이라는 방식 자체가 병목이었음이 확정
- **최종 설계 — 이중 채점(단일 모델, 점수 2개)**:
  - 오토인코더는 **1개**(354→64→16→64→354), 여기서 나온 재구성값으로 점수만 2가지 계산
  - 점수 A: 354차원 전체 평균 재구성 오차, 임계값 = 정상 검증셋 95백분위 (콘텐츠 기반 공격용, Fuzzing에 강함)
  - 점수 B: 마지막 2차원(`unique_id_ratio`, `max_repeat_ratio`)만의 평균 재구성 오차, 임계값 = 정상 검증셋 **99.9백분위** (빈도 기반 공격용, Flooding에 강함)
  - 최종 판정 = **점수 A 또는 점수 B가 각자의 임계값을 넘으면 공격** (OR 결합)
  - B의 임계값을 95→99.9백분위로 올린 이유: Flooding은 워낙 압도적으로 갈리므로(741µs vs 10.25ms) 임계값을 크게 올려도 탐지율 손실이 거의 없는 반면(99.96%→99.94%), 정상 오탐률은 크게 줄어듦(9.81%→5.10%)
  - MCU 이식 시에도 모델은 1개만 export하면 되고, firmware 쪽에는 "재구성 오차 계산 후 두 조건 중 하나 확인"이라는 간단한 로직만 추가하면 됨

**최종 성능 (v5, 이중 채점 기준)**

| 유형 | 탐지율 |
|---|---|
| Flooding | 99.94% |
| Fuzzing | 59.43% |
| Replay | 10.05% |
| Spoofing | 8.45% |
| 정상 오탐률 | 5.10% |

- Replay(과거 정상 프레임을 그대로 재전송 — 콘텐츠상 정상과 구분 불가)와 Spoofing(정상 범위 내 미세한 값 변조)은 구조적으로 남은 한계. 필요 시 순서/이전 프레임 유사도 기반 특성으로 추가 개선 여지 있음(현재 범위 밖, 확정된 한계로 문서화)

## X-CUBE-AI 변환 진행 상황 (일시 중단, 2026-08-03 기준)

**완료된 것:**
- Colab에서 확정 모델을 `autoencoder_v5.h5`와 `autoencoder_v5.keras`(신형 포맷) 두 가지로 저장, 로컬 `ai/models/`에 다운로드 완료
- STM32CubeIDE(workspace_2.2.0) 설치 완료 (ST-LINK 드라이버만 설치, SEGGER J-Link는 불필요해서 제외)
- 테스트 프로젝트(`2026ESWContest_free_KGU`, NUCLEO-F103RB 타겟, C, Executable) 생성 완료

**막힌 지점 및 원인:**
- 이 버전의 STM32CubeIDE에는 `Help > Manage Embedded Software Packages` 메뉴도, `.ioc Device Configuration File` 새로 만들기 마법사도 없음
- 원인: **X-CUBE-AI가 `STM32Cube AI Studio`라는 별도 독립 프로그램으로 대체됨.** 더 이상 STM32CubeIDE 메뉴 안에서 바로 쓰는 방식이 아님
- 이걸 쓰려면 추가로 4개 프로그램 설치 필요: `ST Edge AI Core`(변환 엔진), `STM32CubeMX`(독립 실행형), `STM32CubeProgrammer`(보드 플래싱용, 어차피 나중에 필요), `STM32Cube AI Studio`(모델 변환 도구 본체) — 설치 부담이 커서 여기서 일단 중단

**다음 세션 재개 순서:**
1. 위 4개 프로그램 설치 (순서: ST Edge AI Core → STM32CubeMX → STM32CubeProgrammer → STM32Cube AI Studio)
2. STM32Cube AI Studio에서 `ai/models/autoencoder_v5.keras` 임포트, 타겟 `STM32F103RB` 지정
3. Analyze 실행 → Flash(128KB)/RAM(20KB) 예산 내 확인 (핵심 검증 지점, 아직 미검증)
4. Generate Code → `network.c`/`network.h`를 `ai/export/`에 복사
5. `ai/README.md`, `ai/export/README.md`, `firmware/X-CUBE-AI/README.md`, 프로젝트 메모리 갱신

## 빠른 재학습 절차 (검증된 단계만)

전체 실험 과정 중 실패한 시도(원-핫 인코딩, naive `delta_t`, max/top-3 채점 등)는 제외하고, **v5 결과를 그대로 재현하는 데 필요한 단계만** 정리.

1. **데이터 로드 + 라벨 정리**
   ```python
   df['SubClass'] = df['SubClass'].fillna('Normal')
   ```
2. **프레임 특성 생성** (프레임당 11개: ID 정규화, DLC, DATA 8바이트, `id_delta_t`)
   ```python
   df['id_delta_t'] = df.groupby(['file_id', 'Arbitration_ID'])['Timestamp'].diff()
   # 이후 클리핑 + 정규화
   ```
3. **윈도우화** (32프레임, `boundaries`로 파일 경계 보호) → 프레임 특성 352차원
4. **윈도우 집계 특성 추가** → 354차원
   ```python
   vals, counts = np.unique(ids_arr[s:e], return_counts=True)
   unique_id_ratio = len(vals) / WINDOW
   max_repeat_ratio = counts.max() / WINDOW
   ```
5. **정상/공격 분리 + train/val 분리** (정상만 학습, `test_size=0.2`)
6. **오토인코더 학습** — Dense 354→64→16→64→354, Adam, MSE, 30 epoch, batch 256
7. **이중 채점 + 판정**
   ```python
   threshold_full = np.percentile(val_errors, 95)
   threshold_last2 = np.percentile(err_last2_normal, 99.9)
   is_attack = (errors_full > threshold_full) | (err_last2 > threshold_last2)
   ```
