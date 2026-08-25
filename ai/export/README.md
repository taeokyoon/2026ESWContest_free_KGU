# ai/export — AI ↔ firmware 인터페이스

모델 추론용 C 코드를 여기에 둡니다:
- `feature_extract.h`/`.c` — CAN 프레임을 32개씩 모아 354차원 특성 벡터로 변환 (`feature_extract_push()`)
- `inference.h`/`.c` + `autoencoder_v5_weights_int8.h` — 그 벡터를 받아 공격 여부 판정 (`vids_detect()`)

**사용 순서**: CAN 프레임이 들어올 때마다 `feature_extract_push(frame, buf)`를 호출하고, 반환값이 1이면(윈도우 완성) `buf`를 그대로 `vids_detect(buf)`에 넘기면 됩니다.

NUCLEO-F103RB(Cortex-M3)가 X-CUBE-AI/STM32Cube AI Studio 양쪽 다 공식 미지원이라, ST 툴 자동 변환 대신 AI팀이 순전파 연산을 직접 C로 작성합니다 (자세한 배경은 `ai/README.md`의 "MCU 이식 방식 최종 결정" 절 참고).

**가중치는 int8로 양자화되어 있습니다.** float32 그대로 저장하면 187KB로 F103RB Flash(128KB)를 초과해서, 가중치만 int8로 압축(계산은 float32 유지)했습니다. `autoencoder_v5_weights.h`(float32, 사용 안 함)는 과거 버전이니 참고용으로만 남아있습니다 — 실제 firmware 팀에 전달할 파일은 `autoencoder_v5_weights_int8.h`입니다.

**계약**: firmware 팀은 이 폴더의 최신 파일을 `firmware/X-CUBE-AI/`로 그대로 가져가 통합합니다.
AI 팀은 STM32 HAL 코드를 몰라도 되고, firmware 팀은 모델 학습 과정을 몰라도 됩니다 — 이 폴더에 올라오는 파일 형식만 맞으면 됩니다.
