"""shortcut learning 감사 — 모델이 CAN ID를 외운 것인지 확인한다.

배경: Heydari 2026 "Shortcut Learning and Identifier/Composition Stress Testing in
Frame-Level CAN Intrusion Detection"은 CAN IDS가 고정 ID 룩업만으로도 높은 성능을
내는 경우가 있음을 지적한다. 우리도 id_norm 을 입력 특성에 넣으므로 확인이 필요하다.

354차원 입력에서 ID가 관여하는 곳은 두 군데다.
  (a) 프레임별 id_norm      — 인덱스 0, 11, 22, ..., 341
  (b) 윈도우 집계 2개        — 인덱스 352(unique_id_ratio), 353(max_repeat_ratio)

(b)는 Flooding 탐지를 위해 **의도적으로** 넣은 특성이므로, 여기에 의존하는 것은
shortcut이 아니라 설계대로다. 문제는 (a)에 숨은 의존이 있는지다.

재학습하지 않고 추론 시점에 입력을 교란해 판정 변화를 본다.

  VIDS_DATA=<데이터셋 폴더> python3 05_shortcut_audit.py
"""
import numpy as np
from sklearn.model_selection import train_test_split

import _common as C
import _intquant as Q

K = C.K_CONSECUTIVE
ID_COLS = list(range(0, C.WINDOW * C.FEATURES_PER_FRAME, C.FEATURES_PER_FRAME))
AGG_COLS = [352, 353]


def variants(X, rng, agg_median):
    yield "원본 (그대로)", X

    v = X.copy()
    v[:, ID_COLS] = 0.0
    yield "(a) 프레임 id_norm 제거", v

    v = X.copy()
    flat = v[:, ID_COLS].ravel()
    v[:, ID_COLS] = rng.permutation(flat).reshape(len(v), len(ID_COLS))
    yield "(a) 프레임 id_norm 셔플", v

    v = X.copy()
    v[:, AGG_COLS] = agg_median
    yield "(b) 윈도우 집계 2개 중립화", v

    v = X.copy()
    v[:, ID_COLS] = 0.0
    v[:, AGG_COLS] = agg_median
    yield "(a)+(b) ID 정보 전부 제거", v


def main():
    print("기준 모델·임계값 준비...")
    Xtr, ltr, _ = C.load_windows(C.TRAIN_FILES, "train", recompute_norm=True)
    ytr, _ = C.window_labels(ltr)
    X_calib, X_val = train_test_split(Xtr[~ytr], test_size=0.2, random_state=42)

    W, b, ws, Wq = C.load_quantized_weights()
    m = Q.IntModel(Wq, b, ws, C.LAYER_DIMS)
    m.calibrate(X_calib)
    sa = Q.int_score_dims(X_val, m.forward(X_val), C.ID_DIMS)
    TA = float(np.percentile(sa, C.PCT_A))
    RU = float(np.percentile(X_val[:, 352], C.PCT_UNIQUE))
    RM = float(np.percentile(X_val[:, 353], C.PCT_REPEAT))
    agg_median = np.median(X_calib[:, AGG_COLS], axis=0)
    print(f"  임계값 A(id 32칸) {TA:,.0f}   규칙 unique<{RU:.6f} repeat>{RM:.6f}")
    print(f"  집계특성 중립값 unique_id_ratio {agg_median[0]:.4f}  max_repeat_ratio {agg_median[1]:.4f}")

    rng = np.random.default_rng(42)

    for title, files, cache in [("학습 세션", C.TRAIN_FILES, "train"),
                                ("미사용 Pre_submit_D", ["Pre_submit_D.csv"], "submit_d"),
                                ("미사용 Fin_host", ["Fin_host_session_submit_S.csv"], "fin_host")]:
        X, lab, _ = C.load_windows(files, cache, recompute_norm=(cache == "train"))
        y, sub = C.window_labels(lab)
        print("\n" + "=" * 76)
        print(f"### {title}  (k={K}, 윈도우 단위 탐지율)")
        print(f"  {'변형':28s} {'FPR':>8s}  " + "  ".join(f"{t[:4]:>8s}" for t in C.ATTACK_TYPES))

        base = None
        for name, Xv in variants(X, rng, agg_median):
            SA = Q.int_score_dims(Xv, m.forward(Xv), C.ID_DIMS)
            rule = (Xv[:, 352] < RU) | (Xv[:, 353] > RM)
            fire = C.apply_k_consecutive((SA > TA) | rule, K)
            det, fpr = C.window_metrics(fire, y, sub)
            row = "  ".join(
                f"{det[t] * 100:7.2f}%" if t in det else "      — " for t in C.ATTACK_TYPES
            )
            mark = ""
            if base is None:
                base = det
            else:
                worst = max((base[t] - det.get(t, 0)) for t in base) if base else 0
                mark = f"   (최대 하락 {worst * 100:5.2f}%p)"
            print(f"  {name:28s} {fpr * 100:7.3f}%  {row}{mark}")

    print("\n" + "=" * 76)
    print("해석 기준")
    print("  (a)에서 성능이 유지되면 → 프레임별 ID를 외운 shortcut이 아님 (좋음)")
    print("  (b)에서 Flooding이 무너지면 → 설계대로 집계특성이 신호를 담고 있음")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
