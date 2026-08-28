# tools

PC에서 USB-CAN 애널라이저로 CAN 프레임을 재생(replay)하는 스크립트를 보관합니다.

PC에는 CAN 포트가 없으므로, 애널라이저가 USB와 CAN 버스 사이를 변환합니다.
NUCLEO는 수신만 하는 리스너이므로 **재생하는 쪽이 없으면 보드 화면에 아무 숫자도 뜨지 않습니다.**

## `replay.py`

Car Hacking Challenge 데이터셋 CSV를 CAN 버스에 순차 재생합니다.

```bash
pip install python-can pyserial

python replay.py Pre_train_D_0.csv --port COM7
python replay.py Pre_train_D_0.csv --port COM7 --limit 50000 --rate 2700
```

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--port` | `COM7` | USB-CAN 어댑터 포트 |
| `--bitrate` | `500000` | CAN 비트레이트 |
| `--baudrate` | `2000000` | 어댑터 시리얼 속도 |
| `--limit` | `20000` | 보낼 프레임 수 (`0`=전부) |
| `--rate` | `0` | 초당 프레임 수 제한 (`0`=제한 없음) |
| `--skip` | `0` | 앞에서 건너뛸 프레임 수 |

`pyserial`은 python-can의 의존성에 들어 있지 않지만 seeedstudio 어댑터에 필요합니다.
빠뜨리면 `the serial module is not installed`로 실패합니다.

포트를 열지 못하면 현재 연결된 시리얼 포트 목록을 대신 출력합니다.

종료 시 실제 달성한 fps를 출력합니다. 목표 속도의 90%에 못 미치면 PC나 어댑터가
병목이라는 뜻이므로 경고를 띄웁니다.

데이터셋은 레포에 포함하지 않습니다. 경로는 인자로 직접 넘기세요.

## 재생 데이터는 실제 트래픽이어야 합니다

같은 ID만 반복해서 보내면 **전처리 시간이 실제보다 훨씬 낮게 측정됩니다.**

`feature_extract.c`의 고유 ID 계산은 이미 센 항목을 건너뛰는 이중 루프라, 윈도우 안의
ID가 몇 종류인지에 따라 작업량이 크게 달라집니다.

| 재생 데이터 | 윈도우당 고유 ID | 내부 루프 실행 |
|---|---|---|
| `Pre_train_D_0.csv` (실제) | 평균 27.4 / 최대 32 | 평균 486회 / 최대 496회 |
| 같은 ID만 반복 | 1 | 31회 |

**16배 차이입니다.** 성능 측정에는 반드시 실제 데이터셋을 재생하세요.

## 파일별 참고

`Pre_train_D_0.csv`(9.3 MB, 179,346프레임)는 **전부 Normal**입니다. 고유 ID 73종류,
ID 범위 `0x043`~`0x5CD`. 재생해도 화면의 `ATK`는 0으로 유지되는 것이 정상이며,
그 자체가 오탐 관찰이 됩니다.
