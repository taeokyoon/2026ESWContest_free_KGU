# firmware — 임베디드/IoT 담당

STM32CubeIDE 기반 NUCLEO-F103RB 펌웨어 영역입니다.
**이 폴더가 CubeIDE 프로젝트 루트**입니다(`.project`, `.cproject`, `blink_test.ioc`).

- `Core/` — 애플리케이션 코드. CubeMX 생성 소스와 V-IDS 파이프라인이 함께 있습니다 → `Core/README.md`
- `Drivers/` — STM32F1xx HAL 드라이버, CMSIS
- `X-CUBE-AI/` — 사용하지 않습니다. 모델 코드는 `ai/export/`를 링크 폴더로 연결해 씁니다
- `test/` — 호스트(PC) 검증. 보드 없이 링버퍼·파이프라인을 돌립니다

담당 기능: CAN 수신 인터럽트 처리, 온보드 추론 파이프라인 통합, OLED/LED/부저 알림 출력

## 빌드

- **보드** — STM32CubeIDE에서 `File > Open Projects from File System...`으로 이 폴더를
  엽니다(프로젝트명 `blink_test`). `ai/export` 연결과 include 경로는 프로젝트 파일에
  들어 있으므로 별도 설정이 필요 없습니다.
  워크스페이스는 이 폴더 바깥으로 지정하세요(폴더 자신을 워크스페이스로 쓰면 임포트되지 않습니다).
- **호스트 테스트** — `./test/build_and_run.sh`

## 현재 상태

보드에서 도는 것이 확인된 범위는 **브링업 동작(OLED 표시, CAN 수신 카운트)**까지입니다.
V-IDS 파이프라인은 소스가 들어와 있으나 `main.c`에 배선되지 않아 아직 동작하지 않습니다.

> 🔴 **CubeIDE에서 지금 빌드하면 링크 단계에서 실패합니다.**
> `HAL_CAN_RxFifo0MsgPendingCallback`이 `main.c`와 `can_bxcan.c` 양쪽에 정의돼 있습니다.
> 브링업 범위만 빌드하면(팀 코드 제외) 정상적으로 `.elf`가 생성됩니다.

⚠️ 통합 전에 처리해야 할 미해결 항목 5건(심볼 충돌, CAN 초기화 중복, 파이프라인 미배선,
AutoBusOff, include 경로)은 `Core/README.md`의 "미해결 항목"을 참고하세요.
