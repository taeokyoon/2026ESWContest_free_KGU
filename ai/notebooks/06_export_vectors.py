"""C 구현 대조용 테스트 벡터 생성.

Python 정수 시뮬레이션의 판정을 그대로 담아 두고, firmware/test 의 [D] 케이스가
같은 윈도우를 C `vids_detect()` 에 넣어 100% 일치하는지 확인한다.

  VIDS_DATA=<데이터셋 폴더> python3 06_export_vectors.py [출력경로]

정상·공격·경계(임계값 근처) 윈도우를 골고루 섞어 뽑는다. 경계 표본이 중요하다 —
반올림 한 번 어긋나면 여기서만 판정이 갈리기 때문이다.
"""
import struct
import sys
from pathlib import Path

import numpy as np
from sklearn.model_selection import train_test_split

import _common as C
import _intquant as Q

MAGIC = 0x56494453
N_EACH = 400  # 정상 / 공격 / 경계 각각


def main():
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        C.REPO / "firmware" / "test" / "vectors.bin")

    X, lab, _ = C.load_windows(C.TRAIN_FILES, "train", recompute_norm=True)
    y, _ = C.window_labels(lab)
    X_train, X_val = train_test_split(X[~y], test_size=0.2, random_state=42)

    W, b, ws, Wq = C.load_quantized_weights()
    model = Q.IntModel(Wq, b, ws, C.LAYER_DIMS)
    model.calibrate(X_train)

    sa_val = Q.int_score_dims(X_val, model.forward(X_val), C.ID_DIMS)
    TA = float(np.percentile(sa_val, C.PCT_A))
    RU = float(np.percentile(X_val[:, 352], C.PCT_UNIQUE))
    RM = float(np.percentile(X_val[:, 353], C.PCT_REPEAT))

    score = Q.int_score_dims(X, model.forward(X), C.ID_DIMS)
    rule = (X[:, 352] < RU) | (X[:, 353] > RM)
    verdict = (score > TA) | rule

    rng = np.random.default_rng(0)
    normal_idx = rng.choice(np.where(~verdict)[0], N_EACH, replace=False)
    attack_idx = rng.choice(np.where(verdict)[0], N_EACH, replace=False)
    # 경계: 점수 A가 임계값에 가장 가까운 것들 (반올림 오차가 판정을 가르는 지점)
    border_idx = np.argsort(np.abs(score.astype(np.float64) - TA))[:N_EACH]

    idx = np.unique(np.concatenate([normal_idx, attack_idx, border_idx]))
    rng.shuffle(idx)

    Xs = X[idx].astype(np.float32)
    vs = verdict[idx].astype(np.uint8)
    ss = score[idx].astype(np.int64)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(struct.pack("<III", MAGIC, len(idx), C.INPUT_DIM))
        f.write(Xs.tobytes())
        f.write(vs.tobytes())
        f.write(ss.tobytes())

    near = int((np.abs(score[idx].astype(np.float64) - TA) < TA * 1e-4).sum())
    print(f"테스트 벡터 {len(idx):,}개 생성")
    print(f"  공격 판정 {int(vs.sum()):,} / 정상 판정 {int((~vs.astype(bool)).sum()):,}")
    print(f"  임계값 0.01% 이내 경계 표본 {near:,}개")
    print(f"  임계값 A(id 32칸) {TA:,.0f}   규칙 unique<{RU:.6f} repeat>{RM:.6f}")
    print(f"  -> {out_path}  ({out_path.stat().st_size:,} B)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
