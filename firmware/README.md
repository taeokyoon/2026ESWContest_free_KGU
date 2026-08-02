# firmware — 임베디드/IoT 담당

STM32CubeIDE 기반 NUCLEO-F103RB 펌웨어 영역입니다.

- `Core/` — 애플리케이션 코드 (Src, Inc)
- `Drivers/` — HAL, CAN 트랜시버(SN65HVD230) 관련 드라이버
- `X-CUBE-AI/` — `ai/export/`에서 받은 모델 코드를 통합하는 위치 (자세한 내용은 `X-CUBE-AI/README.md` 참고)

담당 기능: CAN 수신 인터럽트 처리, 온보드 추론 파이프라인 통합, OLED/LED/부저 알림 출력
