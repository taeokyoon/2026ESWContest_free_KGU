# ai/export — AI ↔ firmware 인터페이스

X-CUBE-AI로 변환한 모델 C 코드(`network.c`, `network.h` 등)를 여기에 둡니다.

**계약**: firmware 팀은 이 폴더의 최신 파일을 `firmware/X-CUBE-AI/`로 그대로 가져가 통합합니다.
AI 팀은 STM32 HAL 코드를 몰라도 되고, firmware 팀은 모델 학습 과정을 몰라도 됩니다 — 이 폴더에 올라오는 파일 형식만 맞으면 됩니다.
