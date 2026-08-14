# firmware/Core — 애플리케이션 코드

수신 파이프라인 코드입니다. **하드웨어 무관 핵심**과 **STM32 접착부**가 분리되어 있습니다.

## 파일

| 파일 | 역할 | 컴파일 |
|---|---|---|
| `Inc/can_ringbuffer.h` | SPSC 링버퍼(ISR↔메인루프 분리). 헤더 온리(inline). | 호스트 O / 보드 O |
| `Inc/vids_pipeline.h` · `Src/vids_pipeline.c` | 소비자: 링버퍼→feature_extract→vids_detect→결과알림. HAL 무관. | 호스트 O / 보드 O |
| `Inc/can_bxcan.h` · `Src/can_bxcan.c` | bxCAN Silent 500k 설정 + RX 인터럽트(생산자) + µs 시계. **STM32 HAL 필요.** | 보드 O |
| `Src/app.c` | 전체 배선 예시(app_setup / app_loop). CubeMX main.c에서 호출. | 보드 O |

- **호스트 무관 핵심**(ringbuffer, pipeline)은 `../test`에서 PC로 검증됩니다.
- **HAL 접착부**(can_bxcan.c, app.c)는 STM32CubeIDE/CubeMX 프로젝트 안에서만 컴파일됩니다.

## 통합 시 주의

1. CubeMX로 CAN 페리페럴을 활성화(핸들 `hcan` 생성)해 두면, 저수준 설정
   (비트타이밍/Silent/필터/인터럽트)은 `can_bxcan.c`가 코드로 덮습니다.
2. 태옥의 추론 코드(`feature_extract`/`inference`/가중치)는 `firmware/X-CUBE-AI/`로
   통합합니다. `can_ringbuffer.h`가 `feature_extract.h`(=`can_frame_t`)를 참조하므로
   include 경로에 X-CUBE-AI를 추가하세요.
3. `timestamp` 단위는 태옥 학습 기준과 맞춰야 합니다(확인 대기 항목).
