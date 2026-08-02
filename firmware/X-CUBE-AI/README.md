# firmware/X-CUBE-AI — 모델 통합 지점

`ai/export/`에서 전달받은 X-CUBE-AI 산출물(`network.c`, `network.h` 등)을 이 폴더에 넣고 `Core/`의 추론 파이프라인과 연결합니다.

AI 팀이 모델을 갱신하면 이 폴더의 파일을 최신 버전으로 교체하세요.

## 참고 (2026-08-03): X-CUBE-AI 도구가 바뀌었습니다

기존에 STM32CubeIDE 메뉴 안에서 바로 쓰던 X-CUBE-AI가 `STM32Cube AI Studio`라는 별도 독립 프로그램으로 대체되었습니다. STM32CubeIDE만 설치해서는 X-CUBE-AI 관련 메뉴가 보이지 않으니, 혹시 직접 시도해보실 분은 이 폴더의 상위 `ai/README.md`의 "X-CUBE-AI 변환 진행 상황" 절을 먼저 참고해주세요 (필요한 프로그램 목록과 현재 진행 상황이 정리되어 있습니다).
