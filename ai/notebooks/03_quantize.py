"""활성값 캘리브레이션 + 정수 순전파 검증 + 운영점 확정 + 헤더 생성.

  VIDS_DATA=<데이터셋 폴더> python3 03_quantize.py

누수 방지: 활성값 스케일은 **train normal**로만 잡고, 임계값은 **val normal**로 잡는다.

판정 구조 (2026-08-26 변경 — 05_shortcut_audit.py 근거)
  기존: 점수 A(354차원 AE 오차)  OR  점수 B(마지막 2차원 AE 오차)
  변경: 점수 A(354차원 AE 오차)  OR  규칙(집계특성 2개 직접 비교)

  점수 B는 AE를 거쳐 집계특성 2개를 보는 것인데, 직접 임계값을 거는 것보다
  노이즈만 더한다는 것이 확인됐다. 규칙으로 바꾸면 오탐률은 그대로면서
  Flooding·Replay·Spoofing·Fuzzing 전부 올라간다.

  역할 분담: 규칙 = 빈도·구성 이상 / AE 점수 A = 내용 이상(Fuzzing)
"""
import numpy as np
from sklearn.model_selection import train_test_split

import _common as C
import _intquant as Q

K_CONSECUTIVE = 5      # k회 연속 양성일 때만 경보
PCT_A = 95.0           # 점수 A 임계 (val normal 백분위)
PCT_UNIQUE = 0.1       # unique_id_ratio 하위 백분위 (낮으면 이상)
PCT_REPEAT = 99.9      # max_repeat_ratio 상위 백분위 (높으면 이상)

LEGACY_TH_FULL = 0.07299177638757141
LEGACY_TH_LAST2 = 0.01824626258918472


def emit_header(path, model, th_full_q, uniq_q, rep_q, meta):
    d = model.act_scale
    L = [
        "#ifndef AUTOENCODER_V5_QUANT_H",
        "#define AUTOENCODER_V5_QUANT_H",
        "",
        "#include <stdint.h>",
        "",
        "/* ai/notebooks/03_quantize.py 가 생성한다. 직접 수정하지 말 것. */",
        f"/* 활성값 int16 / 가중치 int8 / 누산 int32.  {meta} */",
        "",
        f"#define VIDS_ACT_MAX       {Q.ACT_MAX}",
        f"#define VIDS_IO_SCALE      {Q.IO_SCALE:.12e}f",
        f"#define VIDS_K_CONSECUTIVE {K_CONSECUTIVE}",
        "",
        "/* 레이어별 bias — 활성값·가중치 스케일로 미리 나눈 정수 */",
    ]
    for l in range(4):
        v = ", ".join(str(int(x)) for x in model.b_q[l])
        L.append(f"static const int32_t vids_bias_q{l}[{len(model.b_q[l])}] = {{{v}}};")
    L += ["", "/* 재양자화: a_next = (acc * M0 + (1 << (SH-1))) >> SH */"]
    for l in range(3):
        m0, sh = model.mult[l]
        L.append(f"#define VIDS_REQUANT{l}_M0  {m0}")
        L.append(f"#define VIDS_REQUANT{l}_SH  {sh}")
    m0s, shs, offs = model.sig_mult
    L += [
        "",
        "/* 출력층 sigmoid — 부동소수점 없이 LUT 인덱스를 바로 만든다.",
        "   idx(8.8 고정소수점) = ((acc * M0 + (1<<(SH-1))) >> SH) + OFFSET",
        f"   참고: pre = acc * {model.out_prescale:.12e} 와 동치 */",
        f"#define VIDS_SIG_M0        {m0s}",
        f"#define VIDS_SIG_SH        {shs}",
        f"#define VIDS_SIG_OFFSET    {offs}",
        f"#define VIDS_SIG_FRAC_BITS {Q.FRAC_BITS}",
        "",
        f"/* sigmoid LUT: [{Q.SIG_LUT_LO}, {Q.SIG_LUT_HI}] 등간격 {Q.SIG_LUT_N}점, 선형보간 */",
        f"#define VIDS_SIG_LUT_N     {Q.SIG_LUT_N}",
        f"#define VIDS_SIG_LUT_LO    {Q.SIG_LUT_LO}f",
        f"#define VIDS_SIG_LUT_HI    {Q.SIG_LUT_HI}f",
    ]
    v = ", ".join(str(int(x)) for x in model.sig_lut)
    L += [
        f"static const int16_t vids_sigmoid_lut[{Q.SIG_LUT_N}] = {{{v}}};",
        "",
        "/* 판정 1 — 점수 A: 354차원 재구성오차 제곱합 (나눗셈 없이 직접 비교) */",
        f"#define VIDS_TH_FULL_Q     {th_full_q}LL",
        "",
        "/* 판정 2 — 규칙: 윈도우 집계 특성 2개를 int16 도메인에서 직접 비교 */",
        f"#define VIDS_TH_UNIQUE_Q   {uniq_q}   /* unique_id_ratio 가 이 값 미만이면 이상 */",
        f"#define VIDS_TH_REPEAT_Q   {rep_q}   /* max_repeat_ratio 가 이 값 초과면 이상 */",
        "",
        "/* 최종: (점수 A 초과 || 규칙 위반) 이 K회 연속일 때 경보 */",
        "",
        f"/* 참고 — 폐기된 float32 임계값: A {LEGACY_TH_FULL} / B {LEGACY_TH_LAST2} */",
        "",
        "#endif",
    ]
    path.write_text("\n".join(L) + "\n")


def main():
    print("데이터 로드...")
    X, lab, _ = C.load_windows(C.TRAIN_FILES, "train", recompute_norm=True)
    y, sub = C.window_labels(lab)
    X_train, X_val = train_test_split(X[~y], test_size=0.2, random_state=42)
    print(f"  calib {len(X_train):,} / val {len(X_val):,} / 공격 {int(y.sum()):,}")

    W, b, w_scales, Wq = C.load_quantized_weights()
    model = Q.IntModel(Wq, b, w_scales, C.LAYER_DIMS)
    act = model.calibrate(X_train)

    print("\n=== 활성값 스케일 (train normal 기준) ===")
    for k in ("in", "h0", "h1", "h2", "out"):
        print(f"  {k:4s} {act[k]:.10e}  (표현 최대 {act[k] * Q.ACT_MAX:.4f})")

    print("\n=== 재양자화 승수 ===")
    for l in range(3):
        m0, sh = model.mult[l]
        print(f"  layer{l}  M0={m0:>11,}  SH={sh}   M={m0 * 2.0 ** -sh:.10f}")

    print("\n=== sigmoid LUT 근사오차 ===")
    xs = np.linspace(-16, 16, 200001)
    err = np.abs(1 / (1 + np.exp(-xs)) - Q.sigmoid_lut_eval(xs, model.sig_lut) * Q.IO_SCALE).max()
    print(f"  최대오차 {err:.3e}  ({'OK' if err < 1e-4 else 'FAIL'})")

    print("\n=== 누산기 오버플로 ===")
    model.acc_max = {}
    out_val = model.forward(X_val, track_acc=True)
    out_all = model.forward(X, track_acc=True)
    lim = 2 ** 31 - 1
    for l in range(4):
        a = model.acc_max[l]
        print(f"  layer{l} |acc|max {a:>13,} / {lim:,} ({a / lim * 100:5.2f}%)  "
              f"{'OK' if a < lim else 'OVERFLOW'}")

    print("\n=== float32 대비 정수화 판정 일치 ===")
    fa_v, _ = C.scores(X_val, C.forward_float(X_val, W, b))
    sa_v, _ = Q.int_scores(X_val, out_val)
    TA = float(np.percentile(sa_v, PCT_A))
    TAf = float(np.percentile(fa_v, PCT_A))
    fa_all, _ = C.scores(X, C.forward_float(X, W, b))
    sa_all, _ = Q.int_scores(X, out_all)
    n_diff = int(((sa_all > TA) != (fa_all > TAf)).sum())
    print(f"  점수 A 판정 불일치 {n_diff:,} / {len(X):,} ({n_diff / len(X) * 100:.4f}%)")

    RU = float(np.percentile(X_val[:, 352], PCT_UNIQUE))
    RM = float(np.percentile(X_val[:, 353], PCT_REPEAT))
    rule_all = (X[:, 352] < RU) | (X[:, 353] > RM)
    print(f"\n=== 확정 임계값 (val normal 기준) ===")
    print(f"  점수 A  제곱합 > {TA:,.0f}   (MSE 환산 {TA * Q.IO_SCALE ** 2 / C.INPUT_DIM:.17g})")
    print(f"  규칙    unique_id_ratio < {RU:.6f}  또는  max_repeat_ratio > {RM:.6f}")

    print(f"\n=== k 스윕 (학습 세션, 하이브리드) ===")
    print(f"  {'k':>2s} {'FPR':>8s} {'경보/시간':>10s}  " +
          "  ".join(f"{t[:4]:>8s}" for t in C.ATTACK_TYPES))
    for k in (1, 2, 3, 5, 8):
        fire = C.apply_k_consecutive((sa_all > TA) | rule_all, k)
        det, fpr = C.window_metrics(fire, y, sub)
        mark = "  <- 채택" if k == K_CONSECUTIVE else ""
        print(f"  {k:>2d} {fpr * 100:7.3f}% {fpr * 84.4 * 3600:9.1f}회  " +
              "  ".join(f"{det[t] * 100:7.2f}%" for t in C.ATTACK_TYPES) + mark)

    th_full_q = int(np.floor(TA))
    uniq_q = int(np.floor(RU / Q.IO_SCALE))
    rep_q = int(np.ceil(RM / Q.IO_SCALE))
    meta = f"k={K_CONSECUTIVE}, 점수A {PCT_A}%ile, 규칙 {PCT_UNIQUE}/{PCT_REPEAT}%ile"

    out = C.EXPORT / "autoencoder_v5_quant.h"
    emit_header(out, model, th_full_q, uniq_q, rep_q, meta)
    print(f"\n=== 헤더 생성 ===")
    print(f"  TH_FULL_Q {th_full_q:,}  TH_UNIQUE_Q {uniq_q:,}  TH_REPEAT_Q {rep_q:,}  K {K_CONSECUTIVE}")
    print(f"  -> {out}  ({out.stat().st_size:,} B)")

    np.savez(C.CACHE / "quant_state.npz", act_scale=np.array(model.act_scale, dtype=object),
             th_full_q=th_full_q, uniq_q=uniq_q, rep_q=rep_q, k=K_CONSECUTIVE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
