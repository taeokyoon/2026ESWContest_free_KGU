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

### 1. OLED 갱신이 파이프라인을 멈춤 (신규)

`ssd1306_UpdateScreen()`은 8페이지 × 128바이트를 **블로킹**으로 전송합니다
(`HAL_I2C_Mem_Write(..., HAL_MAX_DELAY)`). `i2c.c:41`의 `ClockSpeed`가 100 kHz이므로
1회 갱신에 약 1,150바이트 × 90 µs ≈ **100 ms**가 걸리고, 그동안 `app_loop()`가
호출되지 않아 링버퍼가 소비되지 않습니다.

2,700 fps 기준 100 ms면 270프레임이 쌓이는데 링버퍼는 64슬롯이므로 **추론 속도와
무관하게 드롭이 발생**합니다. `main.c`의 갱신 주기를 500 ms로 두어 영향을 20%로
줄였으나 근본 해결은 아닙니다.

영향 범위: 드롭 카운터(`DRP`)만 오염됩니다. `[FW-4]`의 추론 시간은 DWT로
`vids_detect()` 구간만 측정하므로 이 문제와 무관합니다.

방침(제안): `ClockSpeed`는 `.ioc` 소관이므로 `[FW-3]`의 CubeMX 재생성 때 400 kHz로
올립니다(약 25 ms로 감소). 그 이상이 필요하면 변경된 페이지만 전송하는 부분 갱신이나
I2C DMA를 검토합니다. **브링업 단계에서는 애널라이저 송신 속도를 낮춰 회피합니다.**

### 2. 스택 여유가 얇음 (신규)

`vids_detect()`가 지역 배열(`h0[64] h1[16] h2[64] output[354]`, 전부 float)로
**스택 2,064 B**를 씁니다(-O0 기준, `-fstack-usage` 실측).

```
main(80) → vids_pipeline_poll(32) → vids_detect(2,064) → dense_layer(48)  ≈ 2,224 B
+ CAN 수신 ISR 중첩(예외 프레임 + 콜백 지역변수)                          ≈   150 B
                                                                    합계 ≈ 2,400 B
```

SRAM 잔여가 3,028 B이므로 **여유는 약 600 B**입니다. 링크는 통과하지만 보드에서
스택 오버플로가 나면 `.bss` 상단(`last_timestamp`)을 침범해 원인 추적이 어려운
오동작으로 나타납니다.

`[AI-2]` 정수화 시 이 배열들이 int8/int16이 되어 스택 사용량이 1/4~1/2로 줄어듭니다.
정수화를 서둘러야 할 두 번째 이유입니다.

### 3. AutoBusOff 비활성

`can.c:47`이 `AutoBusOff = DISABLE`입니다. 버스오프가 나면 리셋 전까지 수신이 영구
정지합니다. `.ioc`에 해당 항목이 없어 CubeMX 기본값으로 생성된 상태이므로, CubeMX GUI에서
`Connectivity > CAN > Parameter Settings > Automatic Bus-Off Management`를 Enabled로
바꾸고 재생성해야 합니다. → 티켓 `[FW-3]`

## 해결된 항목

### 콜백 심볼 충돌 · CAN 초기화 중복 · 파이프라인 미배선 (해결, `[FW-5]`)

세 가지가 얽혀 있어 함께 처리했습니다.

| 대상 | 처리 |
|---|---|
| `main.c` 콜백(`HAL_CAN_RxFifo0MsgPendingCallback`)과 `rx_count`/`RxHeader`/`RxData` | 삭제. 정의는 `can_bxcan.c` 하나만 남음 |
| `main.c`의 CAN 재초기화·필터·Start·ActivateNotification 32줄 | 삭제 → `app_setup()` 호출로 대체 |
| `can_bxcan_start()`의 `Init.*` 대입과 `HAL_CAN_Init()` | 삭제. 페리페럴 설정은 `can.c`(CubeMX)만 담당 |
| `main.c` 메인 루프 | `app_loop()`를 매 반복 호출. `HAL_Delay(200)` 제거하고 `HAL_GetTick()` 기반 500 ms 주기 UI로 교체 |
| OLED 표시 | 링버퍼·파이프라인 통계(`RX`/`W`/`ATK`/`DRP`/`REJ`)로 교체 |
| `Inc/app.h` | 신규. `app_setup()`은 `can_bxcan_start()`의 코드를 반환하도록 변경 |

**CAN 설정의 단일 출처는 `can.c`(= `.ioc`)입니다.** `can_bxcan.c`가 `Init.*`를 덮어쓰면
`[FW-3]`에서 CubeMX로 AutoBusOff를 켜도 다시 `DISABLE`로 되돌아가기 때문입니다.
따라서 모드는 현재 `.ioc`의 `CAN_MODE_NORMAL`이 적용됩니다.

`app_setup()` 실패 시 OLED에 `CAN FAIL:<코드>`를 표시하고 정지합니다
(`-2` 필터, `-3` 인터럽트 활성화, `-4` Start).

### 동작 모드 — NORMAL 채택 근거 (확정)

IDS는 버스에 개입하지 않아야 하므로 최종 목표는 SILENT입니다. 다만 SILENT는 ACK를
보내지 않으므로, **현재 검증 환경(USB-CAN 애널라이저 + 보드, 2노드)에서는 ACK를 줄
노드가 없어** 송신 측이 ACK 에러·재전송을 반복하다 bus-off로 갑니다.

따라서 브링업·검증 단계는 NORMAL로 진행합니다. SILENT 전환은 ACK를 제공하는 3번째
노드나 실차 버스가 확보된 뒤 별도로 검증합니다(미착수).

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
| 호스트 테스트 | ✅ `../test/build_and_run.sh` — [A][B][C] 전부 통과 |
| ARM 컴파일 (전 코드) | ✅ 32개 전부 통과, **경고 0** (`-Wall`, -O0/-Og 양쪽) |
| ARM 링크 (전 코드) | ✅ `.elf` 생성. 중복 심볼 없음(`nm`으로 콜백 정의 1개 확인) |
| 파이프라인 링크 확인 | ✅ `app_setup`/`app_loop`/`vids_detect`/`vids_pipeline_poll`이 `--gc-sections` 후에도 남음 |
| CubeIDE 빌드 (Debug) | ✅ `blink_test.elf` 생성. `Debug/ai_export/`에 링크 폴더 오브젝트 2개 생성 확인 |
| 보드 실동작 | ⬜ 미검증 — V-IDS 경로는 아직 보드에서 돌린 적 없음 |

명령줄 검증에 쓴 툴체인은 `/Applications/ArmGNUToolchain/15.3.rel1`이며, 링크 옵션은
`-T STM32F103RBTX_FLASH.ld -specs=nano.specs -specs=nosys.specs -Wl,--gc-sections`,
라이브러리는 `-lc -lm`입니다.

macOS에서 CubeIDE 헤드리스 빌드(`-application org.eclipse.cdt.managedbuilder.core.headlessbuild`)는
빌드가 성공해도 런처가 `Java was started but returned exit code=1` 창을 띄웁니다.
**종료 코드로 성공 여부를 판단하지 말고 `Debug/blink_test.elf`의 생성 시각을 확인하세요.**

### 실측 용량 (`[FW-5]` 배선 완료 상태)

| 빌드 | Flash | SRAM | 잔여 SRAM |
|---|---|---|---|
| **CubeIDE Debug** | **74,644 / 131,072 (56.9%)** | **17,444 / 20,480 (85.2%)** | **3,036 B** |
| 명령줄 `-O0` | 74,756 / 131,072 (57.0%) | 17,452 / 20,480 (85.2%) | 3,028 B |
| 명령줄 `-Og` | 69,540 / 131,072 (53.0%) | 17,444 / 20,480 (85.2%) | 3,036 B |

이전 문서의 "배선 후 예상 Flash 77.4%"는 `--gc-sections` 미적용 추정치였습니다.
실제로는 **Flash에 약 43% 여유**가 있어, `[AI-2]`에서 `expf`/`log1pf`를 LUT로
대체할 공간은 충분합니다. 반면 **SRAM은 예상대로 85.2%로 빠듯합니다.**

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
