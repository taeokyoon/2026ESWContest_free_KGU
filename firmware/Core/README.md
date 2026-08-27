# firmware/Core — 애플리케이션 코드

CubeMX가 생성한 NUCLEO-F103RB 프로젝트 소스와 V-IDS 수신 파이프라인이 함께 있습니다.

## 파일 구성

### V-IDS 파이프라인

| 파일 | 역할 | 컴파일 |
|---|---|---|
| `Inc/can_ringbuffer.h` | SPSC 링버퍼(ISR↔메인루프 분리). 헤더 온리(inline). | 호스트 O / 보드 O |
| `Inc/vids_pipeline.h` · `Src/vids_pipeline.c` | 소비자: 링버퍼→feature_extract→vids_detect→결과알림. HAL 무관. | 호스트 O / 보드 O |
| `Inc/can_bxcan.h` · `Src/can_bxcan.c` | bxCAN 설정 + RX 인터럽트(생산자) + µs 시계. **STM32 HAL 필요.** | 보드 O |
| `Src/app.c` | 전체 배선(app_setup / app_loop). | 보드 O |

### CubeMX 생성 코드

`main.c`, `can.c`, `gpio.c`, `i2c.c`, `usart.c`, `stm32f1xx_it.c`, `stm32f1xx_hal_msp.c`,
`system_stm32f1xx.c`, `syscalls.c`, `sysmem.c`, `Startup/`

**`.ioc` 재생성 시 덮어써집니다.** USER CODE 구간 밖은 손으로 고치지 마세요.
페리페럴 설정 변경은 STM32CubeMX GUI에서 하고 재생성합니다.
`.ioc`에는 NVIC 설정도 들어 있으므로, 재생성 후에는 `git diff`로 인터럽트 설정이
의도치 않게 바뀌지 않았는지 확인하세요.

### 외부 라이브러리

`ssd1306.c/h`, `ssd1306_fonts.c/h`, `ssd1306_conf.h` — OLED 구동. CubeMX 생성물이 아닙니다.

## ⚠️ 미해결 항목

아래 네 가지는 **아직 처리되지 않았습니다.** 통합 작업 전에 확인하세요.
1~3번은 서로 얽혀 있어 한 번에 처리해야 합니다(약 20줄 규모).

### 1. 링크 실패 — HAL 콜백 심볼 충돌

**현재 상태로 CubeIDE에서 빌드하면 링크 단계에서 실패합니다.**
컴파일은 31개 파일 전부 통과하며(경고 0), 마지막 링크에서 이 에러 하나만 남습니다.

```
ld: ./Core/Src/main.o: in function `HAL_CAN_RxFifo0MsgPendingCallback':
main.c:227: multiple definition of `HAL_CAN_RxFifo0MsgPendingCallback';
            can_bxcan.o:can_bxcan.c:113: first defined here
```

CAN 수신 인터럽트 콜백을 양쪽이 각각 정의하고 있습니다. HAL은 이 함수를 하나만
기대하므로 링커가 거부합니다. 프로젝트 전체에서 중복 심볼은 이 하나뿐입니다.

| | 내용 |
|---|---|
| `main.c` (7줄) | 수신 개수만 증가. 브링업 확인용 임시 코드 |
| `can_bxcan.c` (30줄) | 타임스탬프 부여, 프레임 필터링, `can_frame_t` 변환, 링버퍼 적재 |

방침(제안): `main.c` 쪽을 제거합니다. 단, `main.c`의 OLED 출력이 그 콜백의 변수
(`rx_count`, `RxHeader`, `RxData`)를 참조하므로 표시 내용을 링버퍼 통계로 함께
교체해야 합니다. → 2·3번과 같이 처리

### 2. CAN 초기화 중복

`can.c`(CubeMX)와 `can_bxcan.c`가 같은 `hcan`을 각각 초기화하며 **설정값이 다릅니다.**

| | CubeMX `can.c` | `can_bxcan.c` |
|---|---|---|
| 모드 | `CAN_MODE_NORMAL` (42행) | `CAN_MODE_SILENT` (91행) |
| AutoBusOff | `DISABLE` (47행) | — |

현재는 `main.c`가 `app.c`를 호출하지 않아 **`can.c`의 NORMAL만 적용**됩니다.
배선을 넣는 순간 나중에 실행되는 쪽이 이깁니다.

방침(제안): `can.c`는 CubeMX 생성 영역이므로 건드리지 않고, `can_bxcan.c`에서 초기화
블록을 걷어내 **수신 처리 레이어로 축소**합니다.

### 3. 파이프라인 미배선

`main.c`는 `app_setup()` / `app_loop()`를 호출하지 않습니다. 지금 빌드하면 보드 브링업
동작(OLED에 CAN RX 카운트 표시)만 하고 V-IDS 추론은 돌지 않습니다.

`can_bxcan.c`의 콜백은 `hcan != s_hcan`이면 즉시 반환하는데 `s_hcan`은
`can_bxcan_start()`가 채웁니다. 즉 1번만 해결하고 배선을 넣지 않으면 CAN 수신이
아무 동작도 하지 않게 됩니다.

### 4. AutoBusOff 비활성

`can.c:47`이 `AutoBusOff = DISABLE`입니다. 버스오프가 나면 리셋 전까지 수신이 영구
정지합니다. `.ioc`에 해당 항목이 없어 CubeMX 기본값으로 생성된 상태이므로, CubeMX GUI에서
`Connectivity > CAN > Parameter Settings > Automatic Bus-Off Management`를 Enabled로
바꾸고 재생성해야 합니다. → 티켓 `[FW-3]`

## 해결된 항목

### 추론 코드 include 경로 (해결)

`can_ringbuffer.h`가 `feature_extract.h`(= `can_frame_t` 정의)를 참조하는데 그 파일은
`ai/export/`에 있어, 프로젝트 폴더 밖이라 CubeIDE가 찾지 못했습니다.

`ai/export`를 **링크 폴더 `ai_export`로 프로젝트에 연결**해 해결했습니다(`.project`,
`.cproject`에 반영). 파일을 복사하지 않으므로 `ai/export`가 갱신되면 그대로 따라갑니다.
경로는 `PARENT-1-PROJECT_LOC/ai/export` 형태의 상대 표기라 OS·설치 위치와 무관합니다.

`firmware/X-CUBE-AI/`는 사용하지 않습니다.

## 검증 상태

| 범위 | 상태 |
|---|---|
| 호스트 테스트 | `../test/build_and_run.sh` — 링버퍼·파이프라인 [A][B][C] 통과 |
| CubeIDE 빌드 | 컴파일 31개 파일 전부 통과, 경고 0. 링크는 위 1번으로 실패 |
| ARM 링크 (브링업 범위) | ✅ `.elf` 생성. Flash 40,296 / 131,072 (30.7%), SRAM 3,268 / 20,480 (16.0%) |
| ARM 링크 (팀 코드 포함) | ❌ 위 1번 심볼 충돌로 실패 |
| 보드 실동작 | 브링업 범위(OLED, CAN RX 카운트)까지 확인. V-IDS 경로는 미검증 |

### 배선 후 예상 용량

심볼 충돌을 무시하고 전 코드를 유지한 채 링크한 결과입니다(`--gc-sections` 미적용).

```
Flash  101,480 / 131,072  (77.4%)
SRAM    17,576 /  20,480  (85.8%)   여유 2,904 B
```

SRAM 상위 소비자:

| 크기 | 심볼 | 비고 |
|---|---|---|
| 8,192 B | `last_timestamp` | `ID_TABLE_SIZE` 2048 × 4B |
| 2,048 B | `id_seen` | `ID_TABLE_SIZE` 2048 × 1B |
| 1,536 B | `_end` | 스택 1KB + 힙 512B 예약 |
| 1,416 B | `s_feature_buf` | |
| 1,408 B | `window_raw` | |
| 1,024 B | `SSD1306_Buffer` | OLED 프레임버퍼 |
| 1,024 B | `s_storage` | CAN 링버퍼 64슬롯 |

ID 테이블 두 개가 10,240 B로 SRAM의 절반을 차지합니다. `ID_TABLE_SIZE`를 실제 데이터셋에
등장하는 ID 수에 맞춰 줄이면 여유를 크게 확보할 수 있습니다(확인 필요 항목).

## 확인 대기

- `timestamp` 단위를 학습 기준과 맞춰야 합니다.

---

## [AI-2] 정수 추론 전환이 이 폴더에 미친 영향 (2026-08-26)

`ai/export/inference.c`가 정수 연산으로 교체되면서 아래가 바뀌었습니다.
설계·검증 상세는 `ai/README.md`의 "정수 연산 전환" 절을 보세요.

### `vids_pipeline.c` — K회 연속 필터 추가

윈도우 판정이 **연속 `VIDS_K_CONSECUTIVE`(현재 5)회 양성**일 때만 `vids_on_result()`에
`VIDS_ATTACK`을 전달합니다. 오탐은 산발적이고 공격은 지속되므로, 임계값을 조이는 것보다
효율이 훨씬 좋습니다.

```
임계값 조이기 (FPR 0.1% 목표)  ->  Flooding 99.93%, Fuzzing  9.19%
k=5 연속 필터  (FPR 0.010%)    ->  Flooding 99.75%, Fuzzing 17.54%
```

탐지 지연은 `5 × 32프레임 ÷ 2,700fps ≈ 59ms`입니다.

`vids_stats_t`에 `windows_flagged`가 추가됐습니다.

| 필드 | 뜻 |
|---|---|
| `windows_flagged` | 윈도우 단위 양성 (필터 적용 **전**) |
| `attacks_detected` | 실제 경보 횟수 (K회 연속 충족) |

### 스택 사용량이 크게 줄었습니다

`vids_detect()`가 `float output[354]`를 없애고 출력층을 64개씩 청크로 흘려보내며
오차만 누적하도록 바뀌었습니다.

| | 이전(float32) | 현재(int16) |
|---|---|---|
| `vids_detect` 스택 | 2,064 B | **592 B** (-Og) / 648 B (-O0) |
| Flash | 56.9% | 53.5% (-Og) / 57.7% (-O0) |
| SRAM | 85.2% | 88.7% (입력 int16 사본 708 B가 bss로) |
| 잔여 SRAM | 3,036 B | 2,316 B |

**스택 마진이 약 662 B → 약 1,400 B로 늘었습니다.** SRAM 총량은 늘었지만 위험한 쪽인
스택 쪽이 넉넉해졌습니다.

`expf`가 링크에서 사라졌습니다(sigmoid LUT로 대체). `log1pf`는 남아 있습니다 —
`feature_extract.c`에서 여전히 쓰며, 실측 기준 약 0.09ms/윈도우로 미미해
**보드 실측(`[FW-4]`) 전에는 손대지 않습니다.**

### 호스트 테스트에 [D] 추가

`../test/build_and_run.sh`가 `vectors.bin`이 있으면 Python 정수 시뮬레이션과
C 구현의 판정이 100% 일치하는지 확인합니다(현재 1,198/1,198 통과, 경계 표본 24개 포함).

```
VIDS_DATA=<데이터셋> python3 ../../ai/notebooks/06_export_vectors.py
bash ../test/build_and_run.sh
```

### `ID_TABLE_SIZE 2048` — 축소 검토 종료

위쪽 "SRAM 상위 소비자" 절에 "`ID_TABLE_SIZE`를 줄이면 여유를 크게 확보할 수 있다"고
적혀 있으나, **줄이면 안 됩니다.**

평가셋 `Fin_host_session_submit_S.csv`에 **학습 데이터에 없던 CAN ID 7개**
(`002 2A0 350 370 430 5A0 5A2`)가 등장하고, 전체 최대 ID는 `0x7DC`입니다.
관측된 81개에 맞춰 줄였다면 배열 범위를 벗어났을 것입니다.
2048칸은 11비트 CAN ID 공간 전체를 덮는 **일반적 설계**이므로 유지합니다.
