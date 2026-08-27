"""ai/export/*.h 의 가중치를 numpy로 복원하고, int8 양자화를 재현해 대조한다.

데이터셋이 필요 없다. 파서가 정확한지, 그리고 양자화 방식이
`scale = max|w| / 127` 대칭 양자화가 맞는지를 검증한다.

    python3 01_parse_weights.py
"""
import numpy as np

import _common as C


def main():
    f32 = C.parse_weight_header(C.EXPORT / "autoencoder_v5_weights.h")
    q8 = C.parse_weight_header(C.EXPORT / "autoencoder_v5_weights_int8.h")
    scales = C.parse_defines(C.EXPORT / "autoencoder_v5_weights_int8.h")

    print("=== 파싱 결과 ===")
    total = 0
    for k in sorted(f32):
        print(f"  {k:20s} {f32[k].shape[0]:>6,}")
        total += f32[k].shape[0]
    print(f"  {'합계':20s} {total:>6,}")

    print("\n=== 양자화 재현 (scale = max|w| / 127, 대칭) ===")
    ok = True
    n_w = 0
    for i, (din, dout) in C.LAYER_DIMS.items():
        w = f32[f"layer{i}_weight"]
        wq_ref = q8[f"layer{i}_weight_q"]
        s_ref = scales[f"layer{i}_scale"]

        s_calc = np.abs(w).max() / 127.0
        wq_calc = np.clip(np.round(w / s_calc), -127, 127)

        n_diff = int((wq_calc != wq_ref).sum())
        s_err = abs(s_calc - s_ref) / s_ref
        good = n_diff == 0 and s_err < 1e-6
        ok &= good
        n_w += len(w)
        print(
            f"  layer{i} {din:>3}x{dout:<3}  scale 재현 {s_calc:.10f} / 헤더 {s_ref:.10f}"
            f"  (오차 {s_err:.1e})  불일치 {n_diff:,}/{len(w):,}  {'OK' if good else 'MISMATCH'}"
        )

    print("\n=== bias 는 양자화하지 않음 (float 유지) ===")
    for i in C.LAYER_DIMS:
        d = np.abs(f32[f"layer{i}_bias"] - q8[f"layer{i}_bias"]).max()
        print(f"  layer{i}_bias 최대차 {d:.3e}")

    print(f"\n가중치 {n_w:,}개 전수 대조 →", "✅ 양자화 방식 재현 성공" if ok else "❌ 불일치")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
