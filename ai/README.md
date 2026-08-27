# ai — AI/Data 담당

CAN 트래픽 이상탐지 모델의 데이터 전처리·학습·경량화를 담당하는 영역입니다.

- `notebooks/` — Colab에서 작업한 `.ipynb` 파일
- `data/` — 데이터셋 (원본 파일은 `.gitignore`로 제외, 다운로드 방법만 문서화)
- `models/` — 학습 완료 모델 (`.h5`, `.tflite` 등)
- `export/` — 추론용 C 코드(`inference.c`/`.h` + `autoencoder_v5_weights.h`) 산출물. firmware 팀과의 인터페이스 지점 (자세한 내용은 `export/README.md` 참고)

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
- [x] 6. MCU 이식 방식 결정 — X-CUBE-AI/STM32Cube AI Studio 둘 다 F103RB 미지원 확인 → 수작업 C 추론으로 전환 결정 (아래 "MCU 이식 방식 최종 결정" 참고)
- [x] 7. 추론 코드 작성 — `ai/export/inference.c`/`.h` + `autoencoder_v5_weights.h` 완성, firmware 팀 전달 대기 중

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

## MCU 이식 방식 최종 결정 (2026-08-03)

**결론: X-CUBE-AI/STM32Cube AI Studio 둘 다 쓰지 않고, 추론 코드를 직접 C로 작성한다.**

**시도했던 것과 실패 이유 (교훈으로 기록):**
1. `STM32Cube AI Studio`(신형 독립 도구) 설치까지 완료했으나, 프로젝트 생성 단계에서 **STM32F103RB(Cortex-M3)가 지원 목록에 없어 실패** — ST 공식 문서상 "STM32F1/F2, L1, U0, MP1/MP2 미지원"
2. 그래서 기존 방식(`X-CUBE-AI`를 독립 실행형 `STM32CubeMX`에서 설치해 사용)으로 전환 시도 → **X-CUBE-AI 10.2.1 릴리스 노트에도 Cortex-M7/M4/M0/M33/M55만 명시, M3 없음** — 이 역시 F103RB 미지원으로 확인됨
3. 즉 **F103RB는 ST의 AI 자동 변환 툴체인 자체가 지원하지 않는 칩**임이 최종 확인됨 (부품은 이미 구매되어 교체하지 않기로 결정)

**대안 — 수작업 C 추론 구현:**
- ⚠️ **아래 문장은 2026-08-22 실측으로 반증됐다. 기록으로 남긴다.**
  ~~"72MHz Cortex-M3에서도 소프트웨어 부동소수점 연산으로 충분히 빠르게 처리 가능
  (윈도우 1개=32프레임당 1회 추론이라 실시간 여유 충분)"~~
  - 실제로는 **윈도우당 약 92ms**로 추정됐고, 실시간 예산은 평상시 11.85ms,
    Flooding 공격 중에는 **3.01ms**다. 최대 30배 초과.
  - 원인: F103에는 FPU가 없어 47,360개 MAC이 전부 libgcc 소프트플로트 호출로 나간다.
    **int8 양자화는 Flash 용량 문제를 푼 것이지 속도 문제를 푼 것이 아니다.**
  - 해결: 연산 자체를 정수로 전환 → 아래 "정수 연산 전환" 절 참고
- Colab에서 학습된 가중치(`autoencoder_v5.keras`)를 그대로 불러와 C `float` 배열 헤더로 추출 (재학습 불필요, 이미 학습된 값을 옮기는 것뿐)
- `ai/export/autoencoder_v5_weights.h` 생성 완료 (레이어 4개: dense 354→64, 64→16, 16→64, 64→354)
- 판정에 쓰는 임계값(정상 검증셋 기준 재계산, 2026-08-03) — **float32 기준 초안, 아래 int8 양자화 이후 값으로 최종 교체됨**:
  - `threshold_v5`(전체 354차원 평균 오차, 95백분위) = 0.07249655798340462
  - `threshold_last2_strict`(마지막 2차원만의 평균 오차, 99.9백분위) = 0.01660382860087232
  - 판정 규칙: 두 오차 중 하나라도 각자의 임계값을 넘으면 공격
- 완료: `ai/export/inference.c`/`.h` 작성 완료 (Dense 순전파 4개 레이어 + 이중 임계값 OR 판정 로직)

**Flash 용량 초과 발견 및 int8 양자화 (2026-08-03 추가):**
- 위 `float32` 가중치 헤더(`autoencoder_v5_weights.h`)를 그대로 쓰면 가중치만 47,858개 × 4바이트 ≈ **187KB**로, F103RB의 Flash 전체(128KB)를 이미 초과 — 연산 속도만 확인하고 저장 용량은 확인하지 않았던 것이 원인
- 해결: **가중치만 int8로 압축, 계산은 float32 유지**하는 방식 채택 (레이어별 `scale = max(|w|)/127`로 대칭 양자화 후 `int8`로 저장, 순전파 시 `weight_q * scale`로 복원해서 계산 — 속도가 아니라 저장 공간만 문제였으므로 연산 정밀도는 그대로 둠)
- 검증: Colab에서 양자화 시뮬레이션(가중치만 반올림 후 float 복원) → 정상 오탐률 5.10% → 5.10%(변화 없음), 전체 공격 탐지율 기존 가중평균 약 52.93% → 양자화 후 52.80%(오차 범위 수준) — 성능 저하 사실상 없음 확인 후 적용
- `ai/export/autoencoder_v5_weights_int8.h` 생성 완료 (레이어별 `layer{i}_weight_q`(int8) + `layer{i}_scale`(float) + `layer{i}_bias`(float, 크기가 작아 양자화하지 않음)) — 가중치 총량 약 46.7KB + bias 약 2KB ≈ **48.7KB**로 Flash 예산 안에 확보
- 양자화 반영 후 재계산한 최종 임계값:
  - `threshold_v5` = **0.07299177638757141**
  - `threshold_last2_strict` = **0.01824626258918472**
  - (기존 float32 전용 임계값 0.07249655798340462 / 0.01660382860087232는 더 이상 쓰지 않음 — 실제 MCU 연산 정밀도에 맞춘 값으로 교체)
- 이제 `ai/export/` 폴더 구성: `inference.h`, `inference.c`(양자화 버전으로 수정 완료), `autoencoder_v5_weights_int8.h`(사용 중), `autoencoder_v5_weights.h`(과거 float32 버전, 참고용으로 보관)

**빌드/용량 최종 검증 (2026-08-03):**
- **RAM**: `vids_detect()` 실행 중 쓰는 임시 배열(`h0`+`h1`+`h2`+`output`) 합 약 2KB + 입력 벡터(1.4KB) ≈ **약 3.4KB** — F103RB RAM 20KB 중 일부만 사용, 여유 충분
- **컴파일**: 로컬 gcc(`-Wall -Wextra -std=c99`)로 `inference.c` 문법·타입 체크 — 경고 없이 통과 (실제 ARM 툴체인 빌드는 firmware 팀 프로젝트 생성 후 재확인 필요)
- **아직 안 된 것 (중요)**: `vids_detect()`는 이미 계산된 354차원 벡터를 입력받는 함수일 뿐, **원시 CAN 프레임(ID/DLC/Data/타임스탬프)을 그 354차원 벡터로 변환하는 코드(특성 추출 파이프라인)가 아직 없음** — 윈도우(32프레임) 수집, ID별 `id_delta_t` 계산(이전 타임스탬프 이력 필요), `unique_id_ratio`/`max_repeat_ratio` 집계를 C로 재구현해야 함. 이건 firmware 팀이 스스로 알 수 없는 모델 설계 지식이 필요하므로 AI팀이 작성 예정 (다음 단계)
- 완료: 특성 추출 C 코드(`ai/export/feature_extract.c`/`.h`) 작성 완료
  - CAN 프레임 1개씩 받아 32개 윈도우로 누적(`feature_extract_push()`), 다 차면 354차원 벡터 완성 후 리셋(논오버랩)
  - ID별 마지막 타임스탬프 기록: 2048칸 배열(ID값=인덱스, RAM 8KB) — 정확도 우선, 해시테이블 방식 대신 채택(팀 논의 결정)
  - `id_delta_t` 정규화에 쓰는 고정 상수(2026-08-03 노트북에서 확인): median=`0.01022195816040039`, log-min=`0.06283380660796888`, log-max=`11.873697951933963`
  - 로컬 gcc 컴파일 검증 + 기능 테스트(32프레임 중 ID 2종 반복 패턴) 통과: `unique_id_ratio`/`max_repeat_ratio` 예상값과 정확히 일치
- 이제 `ai/export/`에 firmware 팀 통합에 필요한 파일 전부 준비됨: `inference.h`/`.c`, `feature_extract.h`/`.c`, `autoencoder_v5_weights_int8.h`
- 다음 단계: firmware 팀이 `Core/`의 CAN 수신 파이프라인에서 `feature_extract_push()` → (윈도우 완성 시) `vids_detect()` 순서로 호출하도록 통합

## 빠른 재학습 절차 (검증된 단계만, 2026-08-03 노트북 실제 셀 기준 확인)

전체 실험 과정 중 폐기된 시도(원-핫 인코딩 자체는 남아있지만 최종 특성엔 미반영, naive `delta_t`/`features_v2`, max/top-3 채점 등)는 제외하고, **v5를 그대로 재현하는 데 필요한 단계만** 정리. 데이터 전처리 단계는 재학습(`fit`) 없이도 필요하다(임계값 재계산 시에도 필요).

1. **데이터 로드 + 라벨 정리**
   ```python
   from google.colab import drive
   drive.mount('/content/drive')
   import pandas as pd
   data_path = '/content/drive/MyDrive/2026ESWContest_free_KGU/data/'
   files = ['Pre_train_D_0.csv', 'Pre_train_D_1.csv', 'Pre_train_D_2.csv',
            'Pre_train_S_0.csv', 'Pre_train_S_1.csv', 'Pre_train_S_2.csv']
   df = pd.concat([pd.read_csv(data_path + f) for f in files], ignore_index=True)
   df['SubClass'] = df['SubClass'].fillna('Normal')
   ```
2. **DATA 바이트 분리** (이후 스칼라 특성에서 재사용)
   ```python
   data_bytes = df['Data'].str.split(' ', expand=True).apply(lambda col: col.apply(lambda x: int(x, 16)))
   data_bytes.columns = [f"byte_{i}" for i in range(8)]
   data_bytes = data_bytes / 255.0
   ```
3. **스칼라 특성 생성** (ID 정규화 + DLC + DATA 8바이트 = 10차원, 원-핫 아님)
   ```python
   id_norm = (df['Arbitration_ID'].apply(lambda x: int(x, 16)) / 0x7FF).rename('id_norm')
   dlc_norm = (df['DLC'] / 8.0).rename('dlc')
   features = pd.concat([id_norm, dlc_norm, data_bytes], axis=1)
   ```
4. **`id_delta_t` 추가** (동일 CAN ID 재등장 간격, 파일 경계 보호용 `file_id` 필요) → 11차원
   ```python
   file_id = np.zeros(len(df), dtype=int)
   for idx, (start, end) in enumerate(zip(boundaries[:-1], boundaries[1:])):
       file_id[start:end] = idx
   df['file_id'] = file_id
   id_delta_t = df.groupby(['file_id', 'Arbitration_ID'])['Timestamp'].diff()
   id_delta_t = id_delta_t.fillna(id_delta_t.median())
   id_delta_t_log = np.log1p(id_delta_t.values * 1000)
   id_delta_t_norm = (id_delta_t_log - id_delta_t_log.min()) / (id_delta_t_log.max() - id_delta_t_log.min())
   features_v3 = pd.concat([features, pd.Series(id_delta_t_norm, name='id_delta_t')], axis=1)
   ```
   `boundaries`(파일별 누적 행 수)와 `WINDOW=32`는 EDA 직후 미리 정의되어 있어야 함(정확한 코드는 노트북 상단 참고).
5. **윈도우화** → `X_windows_v3` (352차원)
   ```python
   feat_array_v3 = features_v3.values
   X_windows_v3 = []
   for start, end in zip(boundaries[:-1], boundaries[1:]):
       n_windows = (end - start) // WINDOW
       for i in range(n_windows):
           s, e = start + i * WINDOW, start + (i + 1) * WINDOW
           X_windows_v3.append(feat_array_v3[s:e].flatten())
   X_windows_v3 = np.array(X_windows_v3)
   ```
6. **윈도우 집계 특성 추가** → `X_windows_v5` (354차원)
   ```python
   ids_arr = df['Arbitration_ID'].values
   unique_id_ratio, max_repeat_ratio = [], []
   for start, end in zip(boundaries[:-1], boundaries[1:]):
       n_windows = (end - start) // WINDOW
       for i in range(n_windows):
           s, e = start + i * WINDOW, start + (i + 1) * WINDOW
           vals, counts = np.unique(ids_arr[s:e], return_counts=True)
           unique_id_ratio.append(len(vals) / WINDOW)
           max_repeat_ratio.append(counts.max() / WINDOW)
   X_windows_v5 = np.hstack([X_windows_v3, np.array(unique_id_ratio).reshape(-1,1), np.array(max_repeat_ratio).reshape(-1,1)])
   ```
7. **모델 불러오기 (재학습 불필요) + 분리**
   ```python
   from tensorflow import keras
   autoencoder_v5 = keras.models.load_model('/content/drive/MyDrive/2026ESWContest_free_KGU/models/autoencoder_v5.keras')
   X_normal_v5 = X_windows_v5[y_windows == 'Normal']
   X_attack_v5 = X_windows_v5[y_windows == 'Attack']
   X_train_v5, X_val_normal_v5 = train_test_split(X_normal_v5, test_size=0.2, random_state=42)
   ```
   `y_windows`(윈도우별 Normal/Attack 라벨)도 4~5단계 사이에 정의되어 있어야 함.


---

## 정수 연산 전환 ([AI-2], 2026-08-26)

`inference.c`가 int8 가중치를 계산 직전에 float으로 되돌려 곱하고 있어, F103(FPU 없음)에서
윈도우당 약 92ms가 걸렸다. **연산 자체를 정수로 바꿨다.**

### 설계

| | 형식 | 근거 |
|---|---|---|
| 가중치 | **int8** (기존 유지) | Flash 제약. float32면 185KB > 128KB |
| 활성값 | **int16** | Cortex-M3에는 SIMD가 없어 int8이 더 빠르지 않다(아래 참고). int8은 정확도만 잃는다 |
| 누산 | **int32** | 실측 최대 26,646,758 = int32 한계의 1.24% |
| sigmoid | **LUT 513점 + 선형보간** | `expf` 354회 제거. 최대오차 5.2e-5 |

**int8을 쓰지 않은 이유** — CMSIS-NN 원논문(arXiv 1801.06601):
> "Most NNFunctions use the **16-bit MAC instructions**, hence data transformation is required
> to **convert the 8-bit data type (q7_t) into 16-bit data type (q15_t)**."

CMSIS-NN의 int8 커널조차 내부적으로 int16으로 확장한다. int8의 속도 이득은 SIMD(`SMLAD` 등)를
전제하는데, 그건 Cortex-M4부터다. ARM 공식 비교표에서 **Cortex-M3의 DSP Extension은 `No`**.

### 판정 구조 변경 — 점수 B를 규칙으로 교체

기존은 `점수 A(354차원 AE 오차) OR 점수 B(마지막 2차원 AE 오차)`였다.
`05_shortcut_audit.py`에서 **집계특성 2개를 중립화하면 Flooding이 99.65% → 0%**가 되는 것을
확인했다. 즉 점수 B는 AE를 거쳐 그 2개를 보는 것인데, 직접 임계값을 거는 편이 더 낫다.

```
변경 후:  점수 A (354차원 AE 재구성오차)  OR  규칙 (집계특성 2개 직접 비교)
역할 분담: AE = 내용 이상(Fuzzing)  /  규칙 = 빈도·구성 이상(Flooding·Replay·Spoofing)
```

오탐률은 그대로면서 전 공격유형 탐지율이 올라갔다 (학습 세션, k=5 기준):

| | Flooding | Fuzzing | Replay(에피소드) | Spoofing |
|---|---|---|---|---|
| 기존 (A OR B) | 99.65% | 12.65% | 11% | 0.02% |
| **변경 (A OR 규칙)** | **99.75%** | **17.54%** | **100%** | **0.74%** |

**규칙 단독으로도 Flooding 99.75%가 나온다.** AE의 기여는 Fuzzing이다(규칙만으론 0%).
이것이 "왜 AI가 필요한가"에 대한 근거 있는 답이다.

### k회 연속 필터

윈도우 판정이 **K=5회 연속 양성**일 때만 경보한다. 오탐은 산발적이고 공격은 지속되므로,
임계값을 조이는 것보다 훨씬 효율적이다.

| 방식 | FPR | Flooding | Fuzzing |
|---|---|---|---|
| 임계값 조이기 (FPR 0.1% 목표) | 0.100% | 99.93% | 9.19% |
| **k=5 연속 필터** | **0.010%** | **99.75%** | **17.54%** |

탐지 지연은 `5 × 32프레임 ÷ 2,700fps ≈ 59ms`.

### 검증 결과

| 항목 | 결과 |
|---|---|
| 누산기 오버플로 | 최대 26,646,758 / 2^31 (1.24%) |
| sigmoid LUT 오차 | 5.2e-5 |
| float32 대비 판정 불일치 | 학습 2/114,751 · Pre_submit_D 0/62,522 · Pre_submit_S 0/54,728 · Fin_host 0/39,697 |
| **Python ↔ C 판정 일치** | **1,198/1,198** (경계 표본 24개 포함) |
| `vids_detect` 스택 | 2,064 B → **592 B** |
| Flash / SRAM | 53.5% / 88.7% |

⚠️ **추론 시간 실측은 아직 없다.** 보드가 필요하며 `[FW-4]`가 담당한다.
MAC당 4~8사이클 가정 시 2.6~5.3ms로 추정되나, **추정치를 실측처럼 쓰지 말 것.**

### 재현 방법

```bash
export VIDS_DATA=<데이터셋 폴더>          # Pre_train_*.csv 등이 있는 곳
python3 ai/notebooks/01_parse_weights.py   # 가중치 파서 + 양자화 재현 검증
python3 ai/notebooks/02_rebuild_pipeline.py # 파이프라인 재현, 검산 7개
python3 ai/notebooks/03_quantize.py         # 캘리브레이션 -> autoencoder_v5_quant.h 생성
python3 ai/notebooks/04_evaluate.py         # 세 단위 평가 (윈도우/프레임/에피소드)
python3 ai/notebooks/05_shortcut_audit.py   # ID 의존도 감사
python3 ai/notebooks/06_export_vectors.py   # C 대조용 벡터
bash firmware/test/build_and_run.sh         # [A][B][C][D]
```

## 평가 — 세 가지 단위를 반드시 구분할 것

같은 시스템도 평가 단위에 따라 수치가 크게 다르다. 섞어 쓰면 오도가 된다.

| 단위 | 뜻 | 주의 |
|---|---|---|
| 윈도우 | 매 순간 정확도 | 공격 사전확률이 프레임 대비 5배(10%→52%). **"전부 공격"이라 답하는 분류기도 F1 0.68** |
| 프레임 | **대회 공식 채점 단위** | 대회 1위 F1 0.869. 우리 수치를 논문과 비교하려면 이 축 |
| 에피소드 | 공격 한 번에 경보가 울렸는가 | 실제 제품 동작. 단, 학습셋은 에피소드가 8~9개뿐이라 표본이 적다 |

### 탐지율은 주입 밀도로 결정된다

공격 윈도우 32프레임 중 실제 공격 프레임이 차지하는 비율:

| 공격 (데이터셋) | 밀도 | 탐지율(윈도우) |
|---|---|---|
| Flooding | 34.6% | 99.9% |
| **Spoofing (Fin_host)** | **33.3%** | **99.9%** |
| Fuzzing (Fin_host) | 28.4% | 47.5% |
| Fuzzing (Pre_train/submit) | 23.3% | 11~18% |
| Replay | 14.8% | 0.6~0.8% |
| Spoofing (Pre_train/submit) | 7.2% | 0.1~0.7% |

**공격 종류가 아니라 밀도가 탐지율을 결정한다.** 같은 Spoofing인데 데이터셋에 따라
0.7%와 99.9%로 갈린다. 따라서 **"Spoofing 8.45%"는 모델의 한계가 아니라
"그 데이터셋의 Spoofing이 희소했다"는 뜻**이다.

주최측도 Spoofing을 의도적으로 어렵게 설계했다 (Kang et al., AutoSec 2021):
> "We included 1), 2) to the training set, and 3), 4), 5) to the test set;
> **different CAN IDs were used in the test set to increase detection difficulty.**"

### shortcut learning 감사 (Heydari 2026 대응)

프레임별 `id_norm`을 무작위로 섞어도 성능이 유지된다 → **모델이 CAN ID를 외운 것이 아니다.**

| 변형 | Flooding | Fuzzing | Spoofing(Fin_host) |
|---|---|---|---|
| 원본 | 99.65% | 12.65% | 90.41% |
| id_norm 셔플 | 99.69% | 12.59% | 89.25% |
| 집계특성 2개 중립화 | **0.00%** | 12.33% | **0.00%** |

마지막 줄이 위에서 말한 "Flooding 탐지는 전적으로 집계특성이 담당한다"의 근거다.
