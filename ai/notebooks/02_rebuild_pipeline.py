"""ai/README.md "빠른 재학습 절차" 1~7단계를 재현하고 문서에 남은 상수와 대조한다.

노트북 없이 파이프라인을 복원할 수 있음을 증명하는 스크립트다.
검산 7개가 모두 통과해야 이후 단계(정수화·평가)를 신뢰할 수 있다.

    VIDS_DATA=<데이터셋 폴더> python3 02_rebuild_pipeline.py
"""
import numpy as np
from sklearn.model_selection import train_test_split

import _common as C

REF = {
    "median": 0.01022195816040039,
    "log_min": 0.06283380660796888,
    "log_max": 11.873697951933963,
    "n_normal": 72139,
    "n_attack": 42612,
    "n_train": 57711,
    "n_val": 14428,
    "threshold_full": 0.07299177638757141,
    "threshold_last2": 0.01824626258918472,
}

_fails = []


def chk(label, got, ref, tol=1e-9):
    rel = abs(got - ref) / abs(ref) if ref else abs(got)
    good = rel < tol
    if not good:
        _fails.append(label)
    print(f"  [{'OK ' if good else 'FAIL'}] {label:24s} 재현 {got!r}")
    print(f"         {'':24s} 문서 {ref!r}  (상대오차 {rel:.2e})")
    return good


def main():
    print("데이터 로드 및 윈도우화 (최초 실행은 수십 초, 이후 캐시)...")
    X, lab, consts = C.load_windows(C.TRAIN_FILES, "train", recompute_norm=True)
    y, _ = C.window_labels(lab)
    print(f"  윈도우 {len(X):,} x {X.shape[1]}차원")

    print("\n=== 검산 (1) id_delta_t 정규화 상수 ===")
    chk("median", float(consts["median"]), REF["median"])
    chk("log_min", float(consts["log_min"]), REF["log_min"])
    chk("log_max", float(consts["log_max"]), REF["log_max"])

    print("\n=== 검산 (2) 윈도우 개수 ===")
    chk("정상 윈도우", int((~y).sum()), REF["n_normal"], tol=1e-12)
    chk("공격 윈도우", int(y.sum()), REF["n_attack"], tol=1e-12)

    X_norm = X[~y]
    X_train, X_val = train_test_split(X_norm, test_size=0.2, random_state=42)
    chk("train 개수", len(X_train), REF["n_train"], tol=1e-12)
    chk("val 개수", len(X_val), REF["n_val"], tol=1e-12)

    print("\n=== 검산 (3) 임계값 (val normal 기준) ===")
    W, b, _, _ = C.load_quantized_weights()
    out = C.forward_float(X_val, W, b)
    mse_full, mse_last2 = C.scores(X_val, out)
    chk("threshold_v5 (95%)", float(np.percentile(mse_full, 95)),
        REF["threshold_full"], tol=1e-4)
    chk("threshold_last2 (99.9%)", float(np.percentile(mse_last2, 99.9)),
        REF["threshold_last2"], tol=1e-4)

    print("\n" + "=" * 62)
    if _fails:
        print("❌ 실패한 검산:", ", ".join(_fails))
        return 1
    print("✅ 검산 7개 전부 통과 — 파이프라인 재현 성공")
    print(f"   캐시: {C.CACHE / 'train.npz'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
