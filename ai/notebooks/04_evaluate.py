"""정직한 평가 — 세 가지 단위로, 학습 세션과 미사용 평가셋 양쪽에서.

  VIDS_DATA=<데이터셋 폴더> python3 04_evaluate.py

평가 단위를 셋으로 나누는 이유
  윈도우 단위 : 매 순간 얼마나 정확한가
  프레임 단위 : 대회 공식 채점 기준(1위 F1 0.869)과 같은 축
  에피소드 단위: 공격 한 번에 부저가 울렸는가 (실제 제품 동작)

셋을 섞어 쓰면 오도가 된다. 윈도우 단위는 공격 사전확률이 프레임 대비 5배로 뛰어
"전부 공격"이라 답하는 분류기조차 F1 0.68이 나온다.

임계값은 **학습 세션의 val normal**로만 잡고, 평가셋에는 그대로 적용한다.
판정은 firmware 와 동일한 `점수 A OR 규칙`이며, 상수는 `_common.py` 한 곳에서 온다.
"""
import numpy as np
from sklearn.model_selection import train_test_split

import _common as C
import _intquant as Q

K_VALUES = (1, 2, 3, 5, 8)
WINDOWS_PER_SEC = 84.4  # 2,700 fps / 32

DATASETS = [
    ("학습 세션", C.TRAIN_FILES, "train"),
    ("미사용 Pre_submit_D", ["Pre_submit_D.csv"], "submit_d"),
    ("미사용 Pre_submit_S", ["Pre_submit_S.csv"], "submit_s"),
    ("미사용 Fin_host", ["Fin_host_session_submit_S.csv"], "fin_host"),
]


def fmt_det(det, key=lambda v: v):
    return "  ".join(
        f"{key(det[t]) * 100:6.2f}%" if t in det else "     — " for t in C.ATTACK_TYPES
    )


def main():
    print("임계값 산출 (학습 세션 val normal 기준, 누수 방지)...")
    Xtr_all, lab_tr, _ = C.load_windows(C.TRAIN_FILES, "train", recompute_norm=True)
    y_tr, _ = C.window_labels(lab_tr)
    X_train, X_val = train_test_split(Xtr_all[~y_tr], test_size=0.2, random_state=42)

    W, b, w_scales, Wq = C.load_quantized_weights()
    model = Q.IntModel(Wq, b, w_scales, C.LAYER_DIMS)
    model.calibrate(X_train)

    sa = Q.int_score_dims(X_val, model.forward(X_val), C.ID_DIMS)
    TA = float(np.percentile(sa, C.PCT_A))
    RU = float(np.percentile(X_val[:, 352], C.PCT_UNIQUE))
    RM = float(np.percentile(X_val[:, 353], C.PCT_REPEAT))
    print(f"  정수 임계값  A(id 32칸) {TA:,.0f}")
    print(f"  규칙  unique_id_ratio < {RU:.6f}  또는  max_repeat_ratio > {RM:.6f}")

    fa = ((X_val.astype(np.float32) - C.forward_float(X_val, W, b))[:, C.ID_DIMS] ** 2).sum(1)
    TAf = float(np.percentile(fa, C.PCT_A))

    for title, files, cache in DATASETS:
        print("\n" + "=" * 78)
        print(f"### {title}")
        X, lab, _ = C.load_windows(files, cache, recompute_norm=(cache == "train"))
        y, sub = C.window_labels(lab)
        n_frames = lab["is_attack"].size
        print(f"  윈도우 {len(X):,}  (공격 {y.sum():,} = {y.mean() * 100:.2f}%)"
              f"   프레임 {n_frames:,} (공격 {lab['is_attack'].sum() / n_frames * 100:.2f}%)")

        dens = C.injection_density(lab, sub)
        print("  주입 밀도(공격 윈도우 32프레임 중 공격 프레임 비율):",
              "  ".join(f"{t[:4]} {dens[t] * 100:.1f}%" for t in C.ATTACK_TYPES if t in dens))

        rule = (X[:, 352] < RU) | (X[:, 353] > RM)
        SA = Q.int_score_dims(X, model.forward(X), C.ID_DIMS)
        raw_q = (SA > TA) | rule
        FA = ((X.astype(np.float32) - C.forward_float(X, W, b))[:, C.ID_DIMS] ** 2).sum(1)
        raw_f = (FA > TAf) | rule

        print(f"\n  [정수화 영향] 윈도우 판정 불일치 "
              f"{int((raw_q != raw_f).sum()):,} / {len(X):,} "
              f"({(raw_q != raw_f).mean() * 100:.4f}%)")

        print(f"\n  {'k':>2s} {'경보/시간':>9s} | " + "  ".join(f"{t[:4]:>6s}" for t in C.ATTACK_TYPES)
              + " | " + "  ".join(f"{t[:4]:>6s}" for t in C.ATTACK_TYPES)
              + " | " + f"{'P':>6s} {'R':>6s} {'F1':>6s}")
        print(f"  {'':>2s} {'(FPR)':>9s} | {'--- 윈도우 단위 ---':^34s}"
              f" | {'--- 에피소드 단위 ---':^34s} | {'프레임 단위':^20s}")
        for k in K_VALUES:
            fire = C.apply_k_consecutive(raw_q, k)
            mark = "  <- 채택" if k == C.K_CONSECUTIVE else ""

            det_w, fpr = C.window_metrics(fire, y, sub)
            det_e = C.episode_metrics(fire, sub)
            prec, rec, f1 = C.frame_metrics(fire, lab)
            print(f"  {k:>2d} {fpr * WINDOWS_PER_SEC * 3600:8.1f}회 | {fmt_det(det_w)}"
                  f" | {fmt_det(det_e, key=lambda v: v[0])}"
                  f" | {prec:6.3f} {rec:6.3f} {f1:6.3f}{mark}")

        eps = {t: len(C.find_episodes(sub == t)) for t in C.ATTACK_TYPES}
        print("  에피소드 개수:", "  ".join(f"{t[:4]} {eps[t]:,}" for t in C.ATTACK_TYPES if eps[t]))

    print("\n" + "=" * 78)
    print("주의: 윈도우 단위 수치를 프레임 단위로 평가한 논문·대회 수치와 나란히 놓지 말 것.")
    print("      대회 공식 채점은 프레임 단위이며 1위 F1은 0.869였다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
