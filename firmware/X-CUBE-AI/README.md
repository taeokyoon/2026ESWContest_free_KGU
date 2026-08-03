# firmware/X-CUBE-AI — 모델 통합 지점

`ai/export/`에서 전달받은 코드(`feature_extract.h`/`.c`, `inference.h`/`.c`, `autoencoder_v5_weights_int8.h`)를 이 폴더에 넣고 `Core/`의 CAN 수신 파이프라인과 연결합니다. 가중치는 Flash 용량(F103RB 128KB) 문제로 int8로 압축되어 있지만, 사용하는 입장에서는 신경 쓸 필요 없습니다.

**사용법**: CAN 프레임이 도착할 때마다 `feature_extract_push(frame, buf)`를 호출하세요. 반환값이 1이면(32프레임 윈도우 완성) `buf`를 그대로 `vids_detect(buf)`에 넘기면 공격 여부(`VIDS_ATTACK`/`VIDS_NORMAL`)가 나옵니다. 반환값이 0이면 아직 윈도우가 덜 찬 것이니 다음 프레임을 기다리면 됩니다.

AI 팀이 모델을 갱신하면 이 폴더의 파일을 최신 버전으로 교체하세요.

## 중요 (2026-08-03): X-CUBE-AI를 쓰지 않기로 했습니다

폴더 이름은 `X-CUBE-AI`이지만, **실제로는 X-CUBE-AI 자동 변환 도구를 쓰지 않습니다.** ST의 AI 변환 도구(X-CUBE-AI, STM32Cube AI Studio) 둘 다 우리가 쓰는 NUCLEO-F103RB(Cortex-M3)를 공식 지원하지 않는다는 걸 뒤늦게 확인했습니다. 대신 AI팀이 학습된 가중치를 직접 C 배열로 뽑아내고, 순전파(forward pass) 연산도 손으로 작성한 일반 C 코드로 대체합니다.

즉 이 폴더에 들어올 파일은 ST 툴이 자동 생성한 코드가 아니라 **AI팀이 직접 작성한 일반 C 함수**입니다 — 사용하는 입장에서는 함수 시그니처(입력 배열 → 공격 여부 boolean)만 알면 되고, 내부 구현이 X-CUBE-AI 산출물이든 손으로 짠 코드든 통합 방식은 동일합니다. 상세 배경은 `ai/README.md`의 "MCU 이식 방식 최종 결정" 절 참고.
