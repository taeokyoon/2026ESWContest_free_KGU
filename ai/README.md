# ai — AI/Data 담당

CAN 트래픽 이상탐지 모델의 데이터 전처리·학습·경량화를 담당하는 영역입니다.

- `notebooks/` — Colab에서 작업한 `.ipynb` 파일
- `data/` — 데이터셋 (원본 파일은 `.gitignore`로 제외, 다운로드 방법만 문서화)
- `models/` — 학습 완료 모델 (`.h5`, `.tflite` 등)
- `export/` — X-CUBE-AI로 변환한 C 코드 산출물. firmware 팀과의 인터페이스 지점 (자세한 내용은 `export/README.md` 참고)
